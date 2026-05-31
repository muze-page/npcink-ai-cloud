from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from app.adapters.callbacks.base import (
    RuntimeCallbackDispatcher,
    RuntimeCallbackDispatchError,
    RuntimeCallbackDispatchRequest,
)
from app.adapters.providers.base import (
    ProviderAdapter,
    ProviderExecutionError,
    ProviderExecutionRequest,
)
from app.adapters.providers.openai import OpenAIProviderAdapter
from app.adapters.queue.base import RuntimeQueue, RuntimeQueueError
from app.adapters.repositories.runtime_repository import RuntimeRepository
from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.error_taxonomy import get_error_taxonomy
from app.core.logging import get_logger
from app.core.models import (
    RUN_CALLBACK_STATUS_DELIVERED,
    RUN_CALLBACK_STATUS_DISPATCHING,
    RUN_CALLBACK_STATUS_FAILED,
    RUN_CALLBACK_STATUS_NOT_REQUESTED,
    RUN_CALLBACK_STATUS_PENDING,
    SITE_STATUS_ACTIVE,
    ProviderCallRecord,
    RunRecord,
    RuntimeGuardEvent,
)
from app.core.secrets import (
    decrypt_runtime_execution_input,
    decrypt_runtime_terminal_callback_secret,
    encrypt_runtime_execution_input,
)
from app.core.security import (
    REPLAY_SCOPE_INTERNAL_POST,
    REPLAY_SCOPE_INTERNAL_POST_IP,
    REPLAY_SCOPE_PUBLIC_POST_IP,
    REPLAY_SCOPE_PUBLIC_POST_KEY,
    REPLAY_SCOPE_PUBLIC_POST_SITE,
)
from app.domain.commercial.service import CommercialService, ServiceAuditContext
from app.domain.routing.models import RoutingCandidate, RoutingResolution
from app.domain.routing.service import RoutingService
from app.domain.runtime.analysis_result import build_analysis_result_envelope
from app.domain.runtime.errors import (
    RuntimeBatchLimitExceededError,
    RuntimeCallbackConfigurationError,
    RuntimeCancelNotAllowedError,
    RuntimeErrorBase,
    RuntimeExecutionContractError,
    RuntimeIdempotencyConflictError,
    RuntimeResultExpiredError,
    RuntimeResultNotReadyError,
    RuntimeRunNotFoundError,
    RuntimeSiteInactiveError,
    RuntimeSiteNotProvisionedError,
)
from app.domain.runtime.models import (
    ABUSE_GUARD_ATTENTION_RATIO,
    ABUSE_GUARD_CRITICAL_RATIO,
    RUNTIME_BACKLOG_QUEUED_AGING_AFTER_SECONDS,
    RUNTIME_BACKLOG_RUNNING_AGING_AFTER_SECONDS,
    RUNTIME_CALLBACK_DISPATCH_LEASE_RECOVERY_AFTER_SECONDS,
    RUNTIME_CALLBACK_DISPATCH_LEASE_RECOVERY_ERROR_CODE,
    RUNTIME_CALLBACK_EVENT,
    RUNTIME_DIAGNOSTIC_CALLBACK_DISPATCHING_STALE_AFTER_SECONDS,
    RUNTIME_DIAGNOSTIC_CALLBACK_OVERDUE_AFTER_SECONDS,
    RUNTIME_DIAGNOSTIC_CANCEL_STUCK_AFTER_SECONDS,
    RUNTIME_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS,
    RUNTIME_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS,
    RUNTIME_MAX_RETENTION_TTL,
    RUNTIME_MAX_RETRY_MAX,
    RUNTIME_MAX_TIMEOUT_SECONDS,
    RUNTIME_STORAGE_MODE_FULL_STORE_WITH_TTL,
    RUNTIME_STORAGE_MODE_NO_STORE,
    RUNTIME_STORAGE_MODE_RESULT_ONLY,
    RuntimeExecutionContext,
    RuntimeExecutionResponse,
    RuntimeFailureDetails,
    RuntimeRequest,
    normalize_runtime_request_policy,
    normalize_runtime_task_backend,
)

logger = get_logger(__name__)

OPERATOR_REPAIR_REASON_MIN_LENGTH = 12
OPERATOR_REPAIR_EVIDENCE_MIN_LENGTH = 24


class RuntimeService:
    def __init__(
        self,
        database_url: str,
        settings: Settings | None = None,
        providers: dict[str, ProviderAdapter] | None = None,
        runtime_queue: RuntimeQueue | None = None,
        callback_dispatcher: RuntimeCallbackDispatcher | None = None,
        callback_max_attempts: int = 3,
        callback_retry_backoff_seconds: int = 30,
    ) -> None:
        self.database_url = database_url
        self.settings = settings or get_settings()
        self.routing_service = RoutingService(database_url)
        self.commercial_service = CommercialService(database_url, settings=self.settings)
        self.providers = providers or {
            OpenAIProviderAdapter.provider_id: OpenAIProviderAdapter()
        }
        self.runtime_queue = runtime_queue
        self.callback_dispatcher = callback_dispatcher
        self.callback_max_attempts = max(1, callback_max_attempts)
        self.callback_retry_backoff_seconds = max(0, callback_retry_backoff_seconds)

    def resolve(self, request: RuntimeRequest) -> dict[str, object]:
        resolution = self.routing_service.resolve(
            profile_id=request.profile_id,
            execution_kind=request.execution_kind,
        )

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            site = self._require_active_site(repository, request.site_id)
            commercial_decision = self.commercial_service.authorize_runtime_request(
                session=session,
                site_id=request.site_id,
                ability_family=request.ability_family,
                channel=request.channel,
                execution_kind=request.execution_kind,
                execution_tier=request.execution_tier,
                data_classification=request.data_classification,
                trace_id=request.trace_id or "",
                idempotency_key=request.idempotency_key,
                request_kind="resolve",
            )
            self._enforce_batch_limits(
                request=request,
                commercial_decision=commercial_decision,
            )
            execution_contract = self._build_execution_contract(
                request=request,
                resolution=resolution,
                site=site,
            )
            session.commit()

        merged_policy = self._merge_policy(resolution.default_policy, request.policy)
        merged_policy = self._apply_execution_contract(
            merged_policy,
            execution_contract=execution_contract,
        )
        merged_policy = self._apply_routing_snapshot(merged_policy, resolution)
        merged_policy = self._apply_commercial_policy_overrides(
            merged_policy,
            commercial_decision=commercial_decision,
        )
        should_enqueue = self._should_enqueue(request, merged_policy)

        candidates = [
            self._serialize_routing_candidate(candidate)
            for candidate in resolution.candidates
        ]
        task_backend_status = "queued" if should_enqueue else "running"

        return {
            "profile_id": resolution.profile_id,
            "execution_kind": resolution.execution_kind,
            "revision": resolution.revision,
            "policy": merged_policy,
            "selected_candidate": candidates[0],
            "candidates": candidates,
            "run_lifecycle": self._build_planned_run_lifecycle(
                request=request,
                policy=merged_policy,
                initial_phase="queued" if task_backend_status == "queued" else "processing",
            ),
            "task_backend": self._build_task_backend_payload_from_policy(
                merged_policy,
                run_status=task_backend_status,
            ),
        }

    def execute(self, request: RuntimeRequest) -> RuntimeExecutionResponse:
        resolution = self.routing_service.resolve(
            profile_id=request.profile_id,
            execution_kind=request.execution_kind,
        )
        merged_policy = self._merge_policy(resolution.default_policy, request.policy)
        merged_policy = self._apply_routing_snapshot(merged_policy, resolution)
        trace_id = request.trace_id or uuid4().hex
        run_id = f"run_{uuid4().hex}"
        request_fingerprint = self._build_request_fingerprint(request, merged_policy)
        should_enqueue = self._should_enqueue(request, merged_policy)
        selected_candidate = resolution.selected_candidate

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            site = self._require_active_site(repository, request.site_id)
            execution_contract = self._build_execution_contract(
                request=request,
                resolution=resolution,
                site=site,
            )
            merged_policy = self._apply_execution_contract(
                merged_policy,
                execution_contract=execution_contract,
            )

            if request.idempotency_key:
                existing = repository.get_run_by_idempotency(
                    request.site_id,
                    request.idempotency_key,
                )
                if existing is not None:
                    if existing.request_fingerprint != request_fingerprint:
                        raise RuntimeIdempotencyConflictError(
                            request.site_id,
                            request.idempotency_key,
                        )
                    session.commit()
                    return self._build_execution_response(
                        existing,
                        repository=repository,
                        idempotent_replay=True,
                    )

            commercial_decision = self.commercial_service.authorize_runtime_request(
                session=session,
                site_id=request.site_id,
                ability_family=request.ability_family,
                channel=request.channel,
                execution_kind=request.execution_kind,
                execution_tier=request.execution_tier,
                data_classification=request.data_classification,
                trace_id=trace_id,
                idempotency_key=request.idempotency_key,
                request_kind="execute",
                run_id=run_id,
            )
            self._enforce_batch_limits(
                request=request,
                commercial_decision=commercial_decision,
            )
            merged_policy = self._apply_commercial_policy_overrides(
                merged_policy,
                commercial_decision=commercial_decision,
            )
            should_enqueue = self._should_enqueue(request, merged_policy)
            storage_mode = self._get_storage_mode(merged_policy)
            prepared_input = self._prepare_input_for_storage(
                request.input_payload,
                storage_mode=storage_mode,
            )
            execution_input_ciphertext = None
            if should_enqueue:
                execution_input_ciphertext = encrypt_runtime_execution_input(
                    request.input_payload,
                    settings=self.settings,
                )

            run = repository.create_run(
                run_id=run_id,
                site_id=request.site_id,
                account_id=str(commercial_decision.get("account_id") or "") or None,
                subscription_id=str(commercial_decision.get("subscription_id") or "") or None,
                plan_version_id=str(commercial_decision.get("plan_version_id") or "") or None,
                ability_name=request.ability_name,
                ability_family=request.ability_family,
                skill_id=request.skill_id,
                workflow_id=request.workflow_id,
                contract_version=request.contract_version,
                channel=request.channel,
                execution_kind=request.execution_kind,
                execution_tier=request.execution_tier,
                execution_pattern=request.execution_pattern,
                data_classification=request.data_classification,
                profile_id=request.profile_id,
                canonical_run_id=request.canonical_run_id or None,
                status="queued" if should_enqueue else "running",
                idempotency_key=request.idempotency_key,
                request_fingerprint=request_fingerprint,
                trace_id=trace_id,
                input_json=prepared_input,
                execution_input_ciphertext=execution_input_ciphertext,
                policy_json=merged_policy,
                selected_provider_id=selected_candidate.provider_id,
                selected_model_id=selected_candidate.model_id,
                selected_instance_id=selected_candidate.instance_id,
            )
            self.commercial_service.record_run_acceptance(session=session, run=run)

            if should_enqueue:
                self._publish_queue_signal(run.run_id)
                session.commit()
                return self._build_execution_response(
                    run,
                    repository=repository,
                    idempotent_replay=False,
                )

            self._execute_candidate_chain(
                run,
                repository=repository,
                candidates=resolution.candidates,
                input_payload=request.input_payload,
            )
            session.commit()
            return self._build_execution_response(
                run,
                repository=repository,
                idempotent_replay=False,
            )

    def process_next_queued_run(self, *, timeout_seconds: int = 1) -> dict[str, object] | None:
        processed = self.process_queued_runs(max_runs=1, timeout_seconds=timeout_seconds)
        if not processed:
            return None
        return processed[0]

    def process_queued_runs(
        self,
        *,
        max_runs: int = 1,
        timeout_seconds: int = 1,
    ) -> list[dict[str, object]]:
        processed: list[dict[str, object]] = []
        remaining_timeout = max(0, timeout_seconds)

        for _ in range(max(1, max_runs)):
            result = self._process_single_queued_run(timeout_seconds=remaining_timeout)
            if result is None:
                break
            processed.append(result)
            # Only the first dequeue should block; after that, drain any additional
            # queued work immediately before returning control to the worker loop.
            remaining_timeout = 0

        return processed

    def _process_single_queued_run(
        self,
        *,
        timeout_seconds: int = 1,
    ) -> dict[str, object] | None:
        signaled_run_id = self._consume_queue_signal(timeout_seconds)

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            run: RunRecord | None = None
            if signaled_run_id:
                run = repository.claim_run_if_queued(signaled_run_id)

            if run is None:
                run = repository.claim_next_queued_run()

            if run is None:
                session.commit()
                return None

            self._execute_existing_run(run, repository=repository)
            session.commit()
            return {
                "run_id": run.run_id,
                "status": run.status,
                "trace_id": run.trace_id,
            }

    def get_run(self, run_id: str, *, site_id: str | None = None) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            run = repository.get_run(run_id)
            if run is None or (site_id and run.site_id != site_id):
                raise RuntimeRunNotFoundError(run_id)

            provider_calls = repository.list_provider_calls(run_id)
            failure_details = self._build_failure_details(run, provider_calls)

        return {
            "run_id": run.run_id,
            "canonical_run_id": run.canonical_run_id or "",
            "site_id": run.site_id,
            "ability_name": run.ability_name,
            "skill_id": run.skill_id or "",
            "workflow_id": run.workflow_id or "",
            "contract_version": run.contract_version or "",
            "channel": run.channel,
            "execution_kind": run.execution_kind,
            "execution_tier": run.execution_tier,
            "execution_pattern": self._public_execution_pattern(run.execution_pattern),
            "data_classification": run.data_classification,
            "profile_id": run.profile_id,
            "status": run.status,
            "idempotency_key": run.idempotency_key,
            "trace_id": run.trace_id,
            "provider_id": run.selected_provider_id,
            "model_id": run.selected_model_id,
            "instance_id": run.selected_instance_id,
            "fallback_used": run.fallback_used,
            "error_code": run.error_code,
            "error_message": run.error_message,
            "error_stage": failure_details.error_stage,
            "retryable": failure_details.retryable,
            "retry_exhausted": failure_details.retry_exhausted,
            "started_at": self._serialize_timestamp(run.started_at),
            "finished_at": self._serialize_timestamp(run.finished_at),
            "provider_call_count": len(provider_calls),
            "task_backend": self._build_task_backend_payload(run),
            "run_lifecycle": self._build_run_lifecycle(run),
        }

    def get_run_result(self, run_id: str, *, site_id: str | None = None) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            run = repository.get_run(run_id)
            if run is None or (site_id and run.site_id != site_id):
                raise RuntimeRunNotFoundError(run_id)
            if self._is_run_result_expired(run):
                raise RuntimeResultExpiredError(run_id)
            if run.result_json is None:
                raise RuntimeResultNotReadyError(run_id, run.status)

            provider_calls = repository.list_provider_calls(run_id)

        result = build_analysis_result_envelope(
            run.result_json if isinstance(run.result_json, dict) else {},
            ability_family=run.ability_family or "text",
            ability_name=run.ability_name or "",
            input_payload=run.input_json if isinstance(run.input_json, dict) else {},
        )
        return {
            "run_id": run.run_id,
            "canonical_run_id": run.canonical_run_id or "",
            "status": run.status,
            "execution_context": self._build_execution_context_payload(run),
            "task_backend": self._build_task_backend_payload(run),
            "run_lifecycle": self._build_run_lifecycle(run),
            "result": result,
            "provider_calls": [
                {
                    "provider_id": call.provider_id,
                    "model_id": call.model_id,
                    "instance_id": call.instance_id,
                    "region": call.region,
                    "latency_ms": call.latency_ms,
                    "tokens_in": call.tokens_in,
                    "tokens_out": call.tokens_out,
                    "cost": call.cost,
                    "retry_count": call.retry_count,
                    "fallback_used": call.fallback_used,
                    "error_code": call.error_code,
                    "error_stage": get_error_taxonomy(call.error_code).error_stage,
                    "retryable": get_error_taxonomy(call.error_code).retryable,
                }
                for call in provider_calls
            ],
        }

    def get_runtime_diagnostics_summary(
        self,
        *,
        site_id: str | None = None,
        recent_minutes: int = 60,
    ) -> dict[str, object]:
        current_time = datetime.now(UTC)
        recent_since = current_time - timedelta(minutes=max(1, recent_minutes))
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            summary = repository.get_runtime_diagnostics_summary(
                site_id=site_id,
                now=current_time,
                recent_since=recent_since,
            )
            guard_summary = {
                "recent_events": repository.count_runtime_guard_events(
                    since=recent_since,
                    site_id=site_id,
                ),
                "recent_rate_limit_exceeded": repository.count_runtime_guard_events(
                    since=recent_since,
                    site_id=site_id,
                    event_code="auth.rate_limit_exceeded",
                ),
                "recent_replay_blocked": repository.count_runtime_guard_events(
                    since=recent_since,
                    site_id=site_id,
                    event_code="auth.replay_blocked",
                ),
                "recent_payload_too_large": repository.count_runtime_guard_events(
                    since=recent_since,
                    site_id=site_id,
                    event_code="auth.payload_too_large",
                ),
                "recent_invalid_nonce": repository.count_runtime_guard_events(
                    since=recent_since,
                    site_id=site_id,
                    event_code="auth.invalid_nonce",
                ),
                "recent_invalid_idempotency_key": repository.count_runtime_guard_events(
                    since=recent_since,
                    site_id=site_id,
                    event_code="auth.invalid_idempotency_key",
                ),
                "event_codes": repository.summarize_runtime_guard_event_codes(
                    since=recent_since,
                    site_id=site_id,
                    limit=10,
                ),
            }
        summary = self._augment_runtime_diagnostics_summary(summary, current_time)
        return {
            "filters": {
                "site_id": site_id or "",
                "recent_minutes": recent_minutes,
            },
            "generated_at": self._serialize_timestamp(current_time),
            "guard": guard_summary,
            **summary,
        }

    def get_runtime_backlog_diagnostics(
        self,
        *,
        scope_kind: str,
        site_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, object]:
        current_time = datetime.now(UTC)
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            runs = repository.list_runtime_backlog_runs(site_id=site_id)

        queued_ages: list[int] = []
        running_ages: list[int] = []
        grouped_runs: dict[str, dict[str, object]] = {}
        for run in runs:
            age_seconds = self._resolve_backlog_age_seconds(run, current_time)
            scope_id = self._resolve_backlog_scope_id(run, scope_kind)
            entry = grouped_runs.setdefault(
                scope_id,
                {
                    "scope_kind": scope_kind,
                    "scope_id": scope_id,
                    "queued_ages": [],
                    "running_ages": [],
                },
            )
            if run.status == "queued":
                queued_ages.append(age_seconds)
                cast(list[int], entry["queued_ages"]).append(age_seconds)
            elif run.status == "running":
                running_ages.append(age_seconds)
                cast(list[int], entry["running_ages"]).append(age_seconds)

        total_queued = self._summarize_backlog_status(
            queued_ages,
            aging_after_seconds=RUNTIME_BACKLOG_QUEUED_AGING_AFTER_SECONDS,
            stale_after_seconds=RUNTIME_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS,
        )
        total_running = self._summarize_backlog_status(
            running_ages,
            aging_after_seconds=RUNTIME_BACKLOG_RUNNING_AGING_AFTER_SECONDS,
            stale_after_seconds=RUNTIME_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS,
        )

        items: list[dict[str, object]] = []
        for item in grouped_runs.values():
            item_queued = self._summarize_backlog_status(
                cast(list[int], item["queued_ages"]),
                aging_after_seconds=RUNTIME_BACKLOG_QUEUED_AGING_AFTER_SECONDS,
                stale_after_seconds=RUNTIME_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS,
            )
            item_running = self._summarize_backlog_status(
                cast(list[int], item["running_ages"]),
                aging_after_seconds=RUNTIME_BACKLOG_RUNNING_AGING_AFTER_SECONDS,
                stale_after_seconds=RUNTIME_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS,
            )
            pressure_state, pressure_reasons = self._classify_backlog_pressure(
                queued_state=str(item_queued["state"]),
                running_state=str(item_running["state"]),
            )
            items.append(
                {
                    "scope_kind": str(item["scope_kind"]),
                    "scope_id": str(item["scope_id"]),
                    "total_runs": int(item_queued["runs"]) + int(item_running["runs"]),
                    "queued": item_queued,
                    "running": item_running,
                    "bottleneck_state": self._classify_backlog_bottleneck(
                        queued_state=str(item_queued["state"]),
                        running_state=str(item_running["state"]),
                    ),
                    "pressure_state": pressure_state,
                    "pressure_reasons": pressure_reasons,
                    "lease_recovery_inputs": {
                        "queued_stale_runs": int(item_queued["stale_runs"]),
                        "running_stale_runs": int(item_running["stale_runs"]),
                        "total_stale_runs": (
                            int(item_queued["stale_runs"]) + int(item_running["stale_runs"])
                        ),
                    },
                }
            )

        items.sort(
            key=lambda item: (
                0
                if item["pressure_state"] == "critical"
                else 1
                if item["pressure_state"] == "attention"
                else 2,
                -int(item["lease_recovery_inputs"]["total_stale_runs"]),
                -int(item["total_runs"]),
                str(item["scope_id"]),
            )
        )
        limited_items = items[: max(1, limit)]
        active_scope_count = len(items)
        pressured_scope_count = sum(1 for item in items if item["pressure_state"] != "healthy")
        stale_scope_count = sum(
            1
            for item in items
            if int(item["lease_recovery_inputs"]["total_stale_runs"]) > 0
        )
        total_active_runs = max(
            1,
            int(total_queued["runs"]) + int(total_running["runs"]),
        )
        dominant_scope_share = (
            round(int(items[0]["total_runs"]) / total_active_runs, 3) if items else 0.0
        )
        total_pressure_state, total_pressure_reasons = self._classify_backlog_pressure(
            queued_state=str(total_queued["state"]),
            running_state=str(total_running["state"]),
        )

        return {
            "filters": {
                "site_id": site_id or "",
                "scope_kind": scope_kind,
                "limit": limit,
            },
            "generated_at": self._serialize_timestamp(current_time),
            "thresholds": {
                "queued_aging_after_seconds": RUNTIME_BACKLOG_QUEUED_AGING_AFTER_SECONDS,
                "queued_stale_after_seconds": RUNTIME_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS,
                "running_aging_after_seconds": RUNTIME_BACKLOG_RUNNING_AGING_AFTER_SECONDS,
                "running_stale_after_seconds": RUNTIME_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS,
            },
            "totals": {
                "queued": total_queued,
                "running": total_running,
                "bottleneck_state": self._classify_backlog_bottleneck(
                    queued_state=str(total_queued["state"]),
                    running_state=str(total_running["state"]),
                ),
                "pressure_state": total_pressure_state,
                "pressure_reasons": total_pressure_reasons,
                "lease_recovery_inputs": {
                    "queued_stale_runs": int(total_queued["stale_runs"]),
                    "running_stale_runs": int(total_running["stale_runs"]),
                    "stale_scope_count": stale_scope_count,
                },
            },
            "scope_pressure": {
                "scope_kind": scope_kind,
                "active_scope_count": active_scope_count,
                "pressured_scope_count": pressured_scope_count,
                "stale_scope_count": stale_scope_count,
                "spread_state": self._classify_backlog_spread_state(
                    pressured_scope_count=pressured_scope_count,
                    stale_scope_count=stale_scope_count,
                    dominant_scope_share=dominant_scope_share,
                ),
                "dominant_scope_share": dominant_scope_share,
            },
            "items": limited_items,
        }

    def list_runtime_diagnostic_runs(
        self,
        *,
        issue_kind: str,
        site_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            runs = repository.list_runtime_diagnostic_runs(
                issue_kind=issue_kind,
                site_id=site_id,
                limit=limit,
            )
        return {
            "filters": {
                "issue_kind": issue_kind,
                "site_id": site_id or "",
                "limit": limit,
            },
            "items": [self._serialize_runtime_diagnostic_run(run) for run in runs],
        }

    def repair_run(
        self,
        *,
        run_id: str,
        action: str,
        audit_context: ServiceAuditContext | None,
        site_id: str | None = None,
        operator_reason: str = "",
        operator_evidence: str = "",
    ) -> dict[str, object]:
        normalized_action = str(action or "").strip()
        reason = str(operator_reason or "").strip()
        evidence = str(operator_evidence or "").strip()
        current_time = datetime.now(UTC)

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            run = repository.get_run(run_id)
            if run is None or (site_id and run.site_id != site_id):
                raise RuntimeRunNotFoundError(run_id)

            before = self._serialize_runtime_diagnostic_run(run)

            if normalized_action == "requeue_stale_queued":
                if run.status != "queued" or not self._is_queued_run_stale(run, current_time):
                    raise RuntimeExecutionContractError(
                        "runtime.repair_not_allowed",
                        "requeue_stale_queued requires a stale queued run",
                    )
                self._publish_queue_signal(run.run_id)
                outcome = {
                    "repair_action": normalized_action,
                    "state_transition": "queued->queued",
                    "operator_reason": reason,
                    "operator_evidence": evidence,
                }
            elif normalized_action == "redeliver_failed_callback":
                if not self._can_redeliver_callback(run, current_time):
                    raise RuntimeExecutionContractError(
                        "runtime.repair_not_allowed",
                        "redeliver_failed_callback requires a failed or overdue callback run",
                    )
                run.callback_status = RUN_CALLBACK_STATUS_PENDING
                run.callback_next_attempt_at = current_time
                run.callback_delivered_at = None
                if reason:
                    run.callback_last_error_message = reason
                session.flush()
                self._publish_queue_signal(run.run_id)
                outcome = {
                    "repair_action": normalized_action,
                    "state_transition": f"{before.get('callback_status') or ''}->pending",
                    "operator_reason": reason,
                    "operator_evidence": evidence,
                }
            elif normalized_action == "mark_stale_running_failed":
                if run.status != "running" or not self._is_running_run_stale(run, current_time):
                    raise RuntimeExecutionContractError(
                        "runtime.repair_not_allowed",
                        "mark_stale_running_failed requires a stale running run",
                    )
                self._validate_operator_repair_evidence(
                    action=normalized_action,
                    operator_reason=reason,
                    operator_evidence=evidence,
                )
                repository.mark_run_failed(
                    run,
                    error_code="runtime.operator_stale_running_failed",
                    error_message=f"operator marked stale running failed: {reason}",
                )
                outcome = {
                    "repair_action": normalized_action,
                    "state_transition": "running->failed",
                    "operator_reason": reason,
                    "operator_evidence": evidence,
                }
            else:
                raise RuntimeExecutionContractError(
                    "runtime.repair_action_invalid",
                    "unsupported runtime repair action",
                )

            after = self._serialize_runtime_diagnostic_run(run)
            session.commit()

        self.commercial_service.record_service_audit_event(
            audit_context=audit_context,
            event_kind=f"runtime.repair.{normalized_action}",
            outcome="succeeded",
            account_id=run.account_id,
            site_id=run.site_id,
            subscription_id=run.subscription_id,
            plan_version_id=run.plan_version_id,
            scope_kind="runtime_run",
            scope_id=run.run_id,
            payload_json={
                "run_id": run.run_id,
                "canonical_run_id": str(run.canonical_run_id or ""),
                "before": before,
                "after": after,
                **outcome,
            },
        )

        return {
            "run_id": run.run_id,
            "canonical_run_id": str(run.canonical_run_id or ""),
            "repair_action": normalized_action,
            "before": before,
            "after": after,
            "summary": outcome,
        }

    def _validate_operator_repair_evidence(
        self,
        *,
        action: str,
        operator_reason: str,
        operator_evidence: str,
    ) -> None:
        normalized_action = str(action or "").strip()
        if normalized_action != "mark_stale_running_failed":
            return

        reason = str(operator_reason or "").strip()
        evidence = str(operator_evidence or "").strip()
        if not reason or not evidence:
            raise RuntimeExecutionContractError(
                "runtime.repair_reason_required",
                "mark_stale_running_failed requires operator_reason and operator_evidence",
            )
        if len(reason) < OPERATOR_REPAIR_REASON_MIN_LENGTH:
            raise RuntimeExecutionContractError(
                "runtime.repair_reason_too_short",
                "mark_stale_running_failed requires a reason that explains why the run "
                "is considered stale",
            )
        if len(evidence) < OPERATOR_REPAIR_EVIDENCE_MIN_LENGTH:
            raise RuntimeExecutionContractError(
                "runtime.repair_evidence_too_short",
                "mark_stale_running_failed requires evidence that records the observed "
                "stale-running signals",
            )

    def run_bounded_auto_repairs(
        self,
        *,
        worker_id: str,
        max_stale_queued: int = 0,
        max_callback_overdue: int = 0,
        max_running_stale_suggestions: int = 20,
        site_id: str | None = None,
    ) -> dict[str, object]:
        normalized_worker_id = str(worker_id or "").strip() or "runtime_worker"
        queued_limit = max(0, int(max_stale_queued))
        callback_limit = max(0, int(max_callback_overdue))
        suggestion_limit = max(0, int(max_running_stale_suggestions))

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            stale_queued_runs = (
                repository.list_runtime_diagnostic_runs(
                    issue_kind="queued_stale",
                    site_id=site_id,
                    limit=queued_limit,
                )
                if queued_limit > 0
                else []
            )
            callback_overdue_runs = (
                repository.list_runtime_diagnostic_runs(
                    issue_kind="callback_overdue",
                    site_id=site_id,
                    limit=callback_limit,
                )
                if callback_limit > 0
                else []
            )
            running_stale_runs = repository.list_runtime_diagnostic_runs(
                issue_kind="running_stale",
                site_id=site_id,
                limit=max(1, suggestion_limit) if suggestion_limit > 0 else 1,
            ) if suggestion_limit > 0 else []
            session.commit()

        audit_context = ServiceAuditContext(
            trace_id=f"trace_runtime_auto_repair_{normalized_worker_id}_{uuid4().hex[:16]}",
            idempotency_key="",
            method="WORKER",
            path=f"/internal/workers/runtime/{normalized_worker_id}/auto-repair",
            actor_kind="system_worker",
            actor_ref=normalized_worker_id,
        )
        requeued_stale_queued: list[dict[str, object]] = []
        redelivered_callback_overdue: list[dict[str, object]] = []
        running_stale_suggestions: list[dict[str, object]] = []

        for run in stale_queued_runs:
            try:
                repair = self.repair_run(
                    run_id=run.run_id,
                    action="requeue_stale_queued",
                    audit_context=audit_context,
                    site_id=site_id,
                )
            except RuntimeErrorBase:
                continue
            requeued_stale_queued.append(
                {
                    "run_id": str(repair.get("run_id") or ""),
                    "canonical_run_id": str(repair.get("canonical_run_id") or ""),
                    "repair_action": "requeue_stale_queued",
                }
            )

        for run in callback_overdue_runs:
            try:
                repair = self.repair_run(
                    run_id=run.run_id,
                    action="redeliver_failed_callback",
                    audit_context=audit_context,
                    site_id=site_id,
                )
            except RuntimeErrorBase:
                continue
            redelivered_callback_overdue.append(
                {
                    "run_id": str(repair.get("run_id") or ""),
                    "canonical_run_id": str(repair.get("canonical_run_id") or ""),
                    "repair_action": "redeliver_failed_callback",
                }
            )

        current_time = datetime.now(UTC)
        for run in running_stale_runs:
            if not self._is_running_run_stale(run, current_time):
                continue
            running_stale_suggestions.append(
                {
                    "run_id": run.run_id,
                    "canonical_run_id": str(run.canonical_run_id or ""),
                    "status": run.status,
                    "suggested_action": "mark_stale_running_failed",
                    "mode": "operator_only",
                    "requires_operator_reason": True,
                    "requires_operator_evidence": True,
                }
            )

        return {
            "worker_id": normalized_worker_id,
            "site_id": site_id or "",
            "requeued_stale_queued_total": len(requeued_stale_queued),
            "redelivered_callback_overdue_total": len(redelivered_callback_overdue),
            "running_stale_operator_queue_total": len(running_stale_suggestions),
            "requeued_stale_queued": requeued_stale_queued,
            "redelivered_callback_overdue": redelivered_callback_overdue,
            "running_stale_operator_queue": running_stale_suggestions,
        }

    def list_runtime_guard_events(
        self,
        *,
        site_id: str | None = None,
        scope_kind: str | None = None,
        event_code: str | None = None,
        limit: int = 20,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            events = repository.list_runtime_guard_events(
                site_id=site_id,
                scope_kind=scope_kind,
                event_code=event_code,
                limit=limit,
            )
        return {
            "filters": {
                "site_id": site_id or "",
                "scope_kind": scope_kind or "",
                "event_code": event_code or "",
                "limit": limit,
            },
            "items": [self._serialize_runtime_guard_event(event) for event in events],
        }

    def get_abuse_guard_diagnostics(
        self,
        *,
        window_seconds: int,
        cooldown_window_seconds: int,
        limit_per_scope: int,
        public_post_site_limit: int,
        public_post_key_limit: int,
        public_post_ip_limit: int,
        public_guard_site_cooldown_limit: int,
        public_guard_key_cooldown_limit: int,
        public_guard_ip_cooldown_limit: int,
        internal_post_token_limit: int,
        internal_post_ip_limit: int,
        internal_guard_token_cooldown_limit: int,
        internal_guard_ip_cooldown_limit: int,
    ) -> dict[str, object]:
        current_time = datetime.now(UTC)
        since = current_time - timedelta(seconds=max(1, window_seconds))
        cooldown_since = current_time - timedelta(seconds=max(1, cooldown_window_seconds))
        scope_kinds = [
            REPLAY_SCOPE_PUBLIC_POST_SITE,
            REPLAY_SCOPE_PUBLIC_POST_KEY,
            REPLAY_SCOPE_PUBLIC_POST_IP,
            REPLAY_SCOPE_INTERNAL_POST,
            REPLAY_SCOPE_INTERNAL_POST_IP,
        ]
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            grouped = repository.summarize_replay_receipts(
                scope_kinds=scope_kinds,
                since=since,
                limit_per_scope=limit_per_scope,
            )
            cooldown_grouped = repository.summarize_runtime_guard_events(
                scope_kinds=scope_kinds,
                since=cooldown_since,
                limit_per_scope=limit_per_scope,
            )
            event_codes = repository.summarize_runtime_guard_event_codes(
                since=cooldown_since,
                limit=limit_per_scope,
            )
            cooldown_code_breakdown = (
                repository.summarize_runtime_guard_event_code_breakdown_by_scope(
                    scope_kinds=scope_kinds,
                    since=cooldown_since,
                    limit_per_scope=3,
                )
            )
        scope_specs = {
            REPLAY_SCOPE_PUBLIC_POST_SITE: {
                "request_limit": public_post_site_limit,
                "cooldown_limit": public_guard_site_cooldown_limit,
            },
            REPLAY_SCOPE_PUBLIC_POST_KEY: {
                "request_limit": public_post_key_limit,
                "cooldown_limit": public_guard_key_cooldown_limit,
            },
            REPLAY_SCOPE_PUBLIC_POST_IP: {
                "request_limit": public_post_ip_limit,
                "cooldown_limit": public_guard_ip_cooldown_limit,
            },
            REPLAY_SCOPE_INTERNAL_POST: {
                "request_limit": internal_post_token_limit,
                "cooldown_limit": internal_guard_token_cooldown_limit,
            },
            REPLAY_SCOPE_INTERNAL_POST_IP: {
                "request_limit": internal_post_ip_limit,
                "cooldown_limit": internal_guard_ip_cooldown_limit,
            },
        }
        scopes: dict[str, dict[str, object]] = {}
        watchlist: list[dict[str, object]] = []
        for scope_kind in scope_kinds:
            request_limit = max(0, int(scope_specs[scope_kind]["request_limit"]))
            cooldown_limit = max(0, int(scope_specs[scope_kind]["cooldown_limit"]))
            request_items = [
                self._decorate_abuse_guard_item(
                    scope_kind=scope_kind,
                    item=item,
                    observed_count=max(0, int(item.get("request_count") or 0)),
                    limit=request_limit,
                    signal_kind="request_burst",
                    near_limit_reason="request_burst_near_limit",
                    exceeded_reason="request_burst_limit_exceeded",
                )
                for item in grouped.get(scope_kind, [])
            ]
            cooldown_items = []
            for item in cooldown_grouped.get(scope_kind, []):
                scope_id = str(item.get("scope_id") or "")
                breakdown = cooldown_code_breakdown.get((scope_kind, scope_id), [])
                cooldown_items.append(
                    self._decorate_abuse_guard_item(
                        scope_kind=scope_kind,
                        item=item,
                        observed_count=max(0, int(item.get("event_count") or 0)),
                        limit=cooldown_limit,
                        signal_kind="reject_storm",
                        near_limit_reason="reject_storm_near_limit",
                        exceeded_reason="reject_storm_limit_exceeded",
                        event_code_breakdown=breakdown,
                    )
                )

            scopes[scope_kind] = {
                "max_requests_per_window": request_limit,
                "items": request_items,
                "request_pressure": self._summarize_abuse_guard_pressure(request_items),
                "max_reject_events_per_cooldown_window": cooldown_limit,
                "cooldown_items": cooldown_items,
                "cooldown_pressure": self._summarize_abuse_guard_pressure(cooldown_items),
            }
            watchlist.extend(
                item
                for item in (*request_items, *cooldown_items)
                if item["severity"] != "healthy"
            )

        sorted_watchlist = sorted(
            watchlist,
            key=lambda item: (
                0 if item["severity"] == "critical" else 1,
                -float(item["limit_ratio"]),
                -int(item["observed_count"]),
                str(item["scope_kind"]),
                str(item["scope_id"]),
            ),
        )
        return {
            "generated_at": self._serialize_timestamp(current_time),
            "window_seconds": window_seconds,
            "cooldown_window_seconds": cooldown_window_seconds,
            "limit_per_scope": limit_per_scope,
            "guard_event_codes": event_codes,
            "watchlist_summary": {
                "highest_severity": (
                    "critical"
                    if any(item["severity"] == "critical" for item in sorted_watchlist)
                    else "attention"
                    if sorted_watchlist
                    else "healthy"
                ),
                "attention_count": sum(
                    1 for item in sorted_watchlist if item["severity"] == "attention"
                ),
                "critical_count": sum(
                    1 for item in sorted_watchlist if item["severity"] == "critical"
                ),
                "request_burst_count": sum(
                    1 for item in sorted_watchlist if item["signal_kind"] == "request_burst"
                ),
                "reject_storm_count": sum(
                    1 for item in sorted_watchlist if item["signal_kind"] == "reject_storm"
                ),
            },
            "watchlist": sorted_watchlist,
            "scopes": scopes,
        }

    def _augment_runtime_diagnostics_summary(
        self,
        summary: dict[str, object],
        current_time: datetime,
    ) -> dict[str, object]:
        queue = dict(summary.get("queue") or {})
        queued_oldest_age_seconds = self._calculate_age_seconds(
            current_time,
            queue.get("queued_oldest_requested_at"),
        )
        running_oldest_age_seconds = self._calculate_age_seconds(
            current_time,
            queue.get("running_oldest_processing_started_at"),
        )
        queue["queued_oldest_age_seconds"] = queued_oldest_age_seconds
        queue["running_oldest_age_seconds"] = running_oldest_age_seconds
        queue["pressure_thresholds"] = {
            "queued_stale_after_seconds": RUNTIME_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS,
            "running_stale_after_seconds": RUNTIME_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS,
        }
        queue["pressure_state"], queue["pressure_reasons"] = self._classify_runtime_pressure(
            (
                (
                    "queue.queued_stale",
                    queued_oldest_age_seconds is not None
                    and queued_oldest_age_seconds >= RUNTIME_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS,
                    queued_oldest_age_seconds is not None
                    and queued_oldest_age_seconds
                    >= (RUNTIME_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS * 3),
                ),
                (
                    "queue.running_stale",
                    running_oldest_age_seconds is not None
                    and running_oldest_age_seconds
                    >= RUNTIME_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS,
                    running_oldest_age_seconds is not None
                    and running_oldest_age_seconds
                    >= (RUNTIME_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS * 3),
                ),
            )
        )

        cancel = dict(summary.get("cancel") or {})
        oldest_request_age_seconds = self._calculate_age_seconds(
            current_time,
            cancel.get("oldest_requested_at"),
        )
        cancel["oldest_request_age_seconds"] = oldest_request_age_seconds
        cancel["pressure_thresholds"] = {
            "cancel_stuck_after_seconds": RUNTIME_DIAGNOSTIC_CANCEL_STUCK_AFTER_SECONDS,
        }
        cancel["pressure_state"], cancel["pressure_reasons"] = self._classify_runtime_pressure(
            (
                (
                    "cancel.request_stuck",
                    oldest_request_age_seconds is not None
                    and oldest_request_age_seconds >= RUNTIME_DIAGNOSTIC_CANCEL_STUCK_AFTER_SECONDS,
                    oldest_request_age_seconds is not None
                    and oldest_request_age_seconds
                    >= (RUNTIME_DIAGNOSTIC_CANCEL_STUCK_AFTER_SECONDS * 3),
                ),
            )
        )

        callback = dict(summary.get("callback") or {})
        pending = max(0, int(callback.get("pending") or 0))
        due_now = max(0, int(callback.get("due_now") or 0))
        failed = max(0, int(callback.get("failed") or 0))
        dispatching = max(0, int(callback.get("dispatching") or 0))
        recoverable_dispatching = max(0, int(callback.get("recoverable_dispatching") or 0))
        oldest_due_age_seconds = self._calculate_age_seconds(
            current_time,
            callback.get("oldest_due_at"),
        )
        dispatching_oldest_age_seconds = self._calculate_age_seconds(
            current_time,
            callback.get("dispatching_oldest_last_attempt_at"),
        )
        callback["pending_not_due"] = max(0, pending - due_now)
        callback["oldest_due_age_seconds"] = oldest_due_age_seconds
        callback["dispatching_oldest_age_seconds"] = dispatching_oldest_age_seconds
        callback["recovery_action"] = "requeue_pending_after_stale_dispatch_lease"
        callback["pressure_thresholds"] = {
            "callback_overdue_after_seconds": RUNTIME_DIAGNOSTIC_CALLBACK_OVERDUE_AFTER_SECONDS,
            "dispatching_stale_after_seconds": (
                RUNTIME_DIAGNOSTIC_CALLBACK_DISPATCHING_STALE_AFTER_SECONDS
            ),
        }
        callback["pressure_state"], callback["pressure_reasons"] = self._classify_runtime_pressure(
            (
                ("callback.failed", failed > 0, failed >= 3),
                (
                    "callback.overdue",
                    oldest_due_age_seconds is not None
                    and oldest_due_age_seconds >= RUNTIME_DIAGNOSTIC_CALLBACK_OVERDUE_AFTER_SECONDS,
                    oldest_due_age_seconds is not None
                    and oldest_due_age_seconds
                    >= (RUNTIME_DIAGNOSTIC_CALLBACK_OVERDUE_AFTER_SECONDS * 3),
                ),
                (
                    "callback.due_now",
                    due_now > 0
                    and (
                        oldest_due_age_seconds is None
                        or oldest_due_age_seconds
                        < RUNTIME_DIAGNOSTIC_CALLBACK_OVERDUE_AFTER_SECONDS
                    ),
                    False,
                ),
                (
                    "callback.dispatching_stale",
                    recoverable_dispatching > 0,
                    recoverable_dispatching >= 3
                    or (
                        dispatching_oldest_age_seconds is not None
                        and dispatching_oldest_age_seconds
                        >= (RUNTIME_DIAGNOSTIC_CALLBACK_DISPATCHING_STALE_AFTER_SECONDS * 3)
                    ),
                ),
                (
                    "callback.dispatching",
                    dispatching > 0
                    and (
                        dispatching_oldest_age_seconds is None
                        or dispatching_oldest_age_seconds
                        < RUNTIME_DIAGNOSTIC_CALLBACK_DISPATCHING_STALE_AFTER_SECONDS
                    ),
                    False,
                ),
            )
        )

        failures = dict(summary.get("failures") or {})
        failed_recent = max(0, int(failures.get("failed_recent") or 0))
        provider_error_calls_recent = max(
            0,
            int(failures.get("provider_error_calls_recent") or 0),
        )
        failures["pressure_state"], failures["pressure_reasons"] = self._classify_runtime_pressure(
            (
                ("failures.failed_recent", failed_recent > 0, failed_recent >= 3),
                (
                    "failures.provider_error_calls_recent",
                    provider_error_calls_recent > 0,
                    provider_error_calls_recent >= 3,
                ),
            )
        )
        failures["dominant_error"] = self._build_dominant_runtime_error(failures)
        operator_guidance = self._build_runtime_operator_guidance(
            queue=queue,
            cancel=cancel,
            callback=callback,
            failures=failures,
            retention=dict(summary.get("retention") or {}),
        )

        return {
            **summary,
            "queue": queue,
            "cancel": cancel,
            "callback": callback,
            "failures": failures,
            "operator_guidance": operator_guidance,
        }

    def _build_dominant_runtime_error(
        self,
        failures: dict[str, object],
    ) -> dict[str, object]:
        top_error_codes = failures.get("top_error_codes")
        top_provider_errors = failures.get("top_provider_errors")
        candidates: list[dict[str, object]] = []
        if isinstance(top_error_codes, list):
            candidates.extend(item for item in top_error_codes if isinstance(item, dict))
        if isinstance(top_provider_errors, list):
            candidates.extend(item for item in top_provider_errors if isinstance(item, dict))
        if not candidates:
            return {
                "error_code": "",
                "error_stage": "",
                "count": 0,
                "provider_id": "",
                "last_seen_at": "",
            }

        def sort_key(item: dict[str, object]) -> tuple[int, str]:
            return (
                int(item.get("count") or 0),
                str(item.get("last_seen_at") or ""),
            )

        dominant = sorted(candidates, key=sort_key, reverse=True)[0]
        error_code = str(dominant.get("error_code") or "")
        taxonomy = get_error_taxonomy(error_code)
        return {
            "error_code": error_code,
            "error_stage": taxonomy.error_stage,
            "count": int(dominant.get("count") or 0),
            "provider_id": str(dominant.get("provider_id") or ""),
            "last_seen_at": str(dominant.get("last_seen_at") or ""),
        }

    def _build_runtime_operator_guidance(
        self,
        *,
        queue: dict[str, object],
        cancel: dict[str, object],
        callback: dict[str, object],
        failures: dict[str, object],
        retention: dict[str, object],
    ) -> dict[str, object]:
        candidates: list[dict[str, object]] = []

        def add_candidate(
            *,
            reason: str,
            state: str,
            evidence_path: str,
            action: str,
            mode: str,
            priority: int,
        ) -> None:
            candidates.append(
                {
                    "reason": reason,
                    "state": state,
                    "evidence_path": evidence_path,
                    "suggested_action": action,
                    "mode": mode,
                    "priority": priority,
                }
            )

        if callback.get("pressure_state") in {"attention", "critical"}:
            add_candidate(
                reason="callback_delivery",
                state=str(callback.get("pressure_state") or "attention"),
                evidence_path="callback.pressure_reasons",
                action="inspect_callback_delivery_and_retry_buffer",
                mode="operator_review",
                priority=10,
            )
        if queue.get("pressure_state") in {"attention", "critical"}:
            add_candidate(
                reason="runtime_queue",
                state=str(queue.get("pressure_state") or "attention"),
                evidence_path="queue.pressure_reasons",
                action="inspect_runtime_worker_and_backlog_scope",
                mode="operator_review",
                priority=20,
            )
        if cancel.get("pressure_state") in {"attention", "critical"}:
            add_candidate(
                reason="cancel_requests",
                state=str(cancel.get("pressure_state") or "attention"),
                evidence_path="cancel.pressure_reasons",
                action="inspect_stuck_cancel_requests",
                mode="operator_review",
                priority=30,
            )
        if failures.get("pressure_state") in {"attention", "critical"}:
            dominant = failures.get("dominant_error")
            dominant_error = dominant if isinstance(dominant, dict) else {}
            error_stage = str(dominant_error.get("error_stage") or "runtime")
            action_by_stage = {
                "provider": "inspect_provider_credentials_quota_and_health",
                "auth": "inspect_site_key_signature_and_request_headers",
                "routing": "inspect_profile_catalog_and_routing_candidates",
                "runtime": "inspect_runtime_execution_error_and_worker_logs",
            }
            add_candidate(
                reason=f"{error_stage}_failures",
                state=str(failures.get("pressure_state") or "attention"),
                evidence_path="failures.dominant_error",
                action=action_by_stage.get(error_stage, "inspect_runtime_failure_detail"),
                mode="operator_review",
                priority=40,
            )
        if int(retention.get("due_purge") or 0) > 0:
            add_candidate(
                reason="retention_due",
                state="attention",
                evidence_path="retention.due_purge",
                action="run_retention_cleanup_or_check_ops_cadence",
                mode="worker_auto",
                priority=50,
            )

        candidates.sort(key=lambda item: int(item["priority"]))
        primary = candidates[0] if candidates else {
            "reason": "none",
            "state": "healthy",
            "evidence_path": "",
            "suggested_action": "continue_monitoring",
            "mode": "none",
            "priority": 100,
        }
        return {
            "state": str(primary["state"]),
            "primary_reason": str(primary["reason"]),
            "primary_evidence_path": str(primary["evidence_path"]),
            "suggested_actions": [
                {
                    "action": str(item["suggested_action"]),
                    "reason": str(item["reason"]),
                    "mode": str(item["mode"]),
                    "evidence_path": str(item["evidence_path"]),
                }
                for item in candidates[:5]
            ],
        }

    def cancel_run(self, run_id: str, *, site_id: str | None = None) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            run = repository.get_run(run_id)
            if run is None or (site_id and run.site_id != site_id):
                raise RuntimeRunNotFoundError(run_id)

            policy = run.policy_json if isinstance(run.policy_json, dict) else {}
            if not self._supports_public_cancel(run.execution_pattern, policy):
                raise RuntimeCancelNotAllowedError(run_id, run.status)

            if run.status == "queued":
                repository.mark_run_canceled(run, message="run canceled before worker claim")
            elif run.status == "running":
                repository.request_run_cancel(run)
            elif run.status == "canceled":
                pass
            else:
                raise RuntimeCancelNotAllowedError(run_id, run.status)

            session.commit()

        return self.get_run(run_id, site_id=site_id)

    def dispatch_pending_callbacks(
        self,
        *,
        max_callbacks: int = 1,
    ) -> list[dict[str, object]]:
        if self.callback_dispatcher is None:
            return []

        self._recover_stale_callback_dispatches(limit=max(1, max_callbacks))
        dispatched: list[dict[str, object]] = []
        for _ in range(max(1, max_callbacks)):
            result = self._dispatch_single_pending_callback()
            if result is None:
                break
            dispatched.append(result)
        return dispatched

    def _execute_existing_run(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
    ) -> None:
        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
        candidates = self._deserialize_routing_candidates(policy)
        if not candidates:
            resolution = self.routing_service.resolve(
                profile_id=run.profile_id,
                execution_kind=run.execution_kind,
            )
            policy = self._apply_routing_snapshot(policy, resolution)
            run.policy_json = policy
            candidates = resolution.candidates

        self._execute_candidate_chain(
            run,
            repository=repository,
            candidates=candidates,
            input_payload=self._get_execution_input_payload(run),
        )

    def _execute_candidate_chain(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        candidates: list[RoutingCandidate],
        input_payload: dict[str, Any],
    ) -> None:
        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
        allow_fallback = bool(policy.get("allow_fallback", True))
        max_retries = max(0, self._coerce_int(policy.get("max_retries"), default=0))
        timeout_ms = max(1, self._coerce_int(policy.get("timeout_ms"), default=30_000))

        last_error_code = "runtime.execute_failed"
        last_error_message = "runtime execution failed"
        last_fallback_used = False
        last_provider_id = ""
        last_model_id = ""
        last_instance_id = ""

        if self._cancel_requested_before_attempt(run, repository=repository):
            repository.mark_run_canceled(run)
            return

        for candidate_index, candidate in enumerate(candidates):
            fallback_used = candidate_index > 0

            for retry_count in range(max_retries + 1):
                if self._cancel_requested_before_attempt(run, repository=repository):
                    repository.mark_run_canceled(run)
                    return
                last_fallback_used = fallback_used
                last_provider_id = candidate.provider_id
                last_model_id = candidate.model_id
                last_instance_id = candidate.instance_id
                provider = self.providers.get(candidate.provider_id)
                if provider is None:
                    last_error_code = "runtime.provider_not_configured"
                    last_error_message = (
                        f"provider adapter is not configured for {candidate.provider_id}"
                    )
                    if allow_fallback and get_error_taxonomy(last_error_code).fallback_eligible:
                        break

                    repository.mark_run_failed(
                        run,
                        error_code=last_error_code,
                        error_message=last_error_message,
                        provider_id=candidate.provider_id,
                        model_id=candidate.model_id,
                        instance_id=candidate.instance_id,
                        fallback_used=fallback_used,
                    )
                    return

                try:
                    provider_result = provider.execute(
                        ProviderExecutionRequest(
                            run_id=run.run_id,
                            site_id=run.site_id,
                            ability_name=run.ability_name,
                            profile_id=run.profile_id,
                            execution_kind=run.execution_kind,
                            model_id=candidate.model_id,
                            instance_id=candidate.instance_id,
                            endpoint_variant=candidate.endpoint_variant,
                            trace_id=run.trace_id,
                            input_payload=input_payload,
                            policy=policy,
                            timeout_ms=timeout_ms,
                            price_input=candidate.price_input,
                            price_output=candidate.price_output,
                            retry_count=retry_count,
                        )
                    )
                except ProviderExecutionError as error:
                    provider_call = repository.record_provider_call(
                        run_id=run.run_id,
                        provider_id=candidate.provider_id,
                        model_id=candidate.model_id,
                        instance_id=candidate.instance_id,
                        region=candidate.region,
                        latency_ms=timeout_ms if error.error_code == "provider.timeout" else 0,
                        tokens_in=max(0, int(getattr(error, "tokens_in", 0) or 0)),
                        tokens_out=max(0, int(getattr(error, "tokens_out", 0) or 0)),
                        cost=max(0.0, float(getattr(error, "cost", 0.0) or 0.0)),
                        retry_count=retry_count,
                        fallback_used=fallback_used,
                        error_code=error.error_code,
                    )
                    self.commercial_service.record_provider_call_usage(
                        session=repository.session,
                        run=run,
                        provider_call=provider_call,
                    )
                    last_error_code = error.error_code
                    last_error_message = error.message

                    error_taxonomy = get_error_taxonomy(error.error_code)
                    should_retry = (
                        retry_count < max_retries
                        and error.retryable
                        and error_taxonomy.retryable
                    )
                    if should_retry:
                        continue

                    should_fallback = allow_fallback and error_taxonomy.fallback_eligible
                    if should_fallback:
                        break

                    repository.mark_run_failed(
                        run,
                        error_code=last_error_code,
                        error_message=last_error_message,
                        provider_id=candidate.provider_id,
                        model_id=candidate.model_id,
                        instance_id=candidate.instance_id,
                        fallback_used=fallback_used,
                    )
                    return

                provider_call = repository.record_provider_call(
                    run_id=run.run_id,
                    provider_id=candidate.provider_id,
                    model_id=candidate.model_id,
                    instance_id=candidate.instance_id,
                    region=candidate.region,
                    latency_ms=provider_result.latency_ms,
                    tokens_in=provider_result.tokens_in,
                    tokens_out=provider_result.tokens_out,
                    cost=provider_result.cost,
                    retry_count=retry_count,
                    fallback_used=fallback_used,
                )
                self.commercial_service.record_provider_call_usage(
                    session=repository.session,
                    run=run,
                    provider_call=provider_call,
                )
                prepared_result = self._prepare_result_for_storage(
                    provider_result.output,
                    storage_mode=self._get_storage_mode(
                        run.policy_json if isinstance(run.policy_json, dict) else {}
                    ),
                )
                wrapped_result = build_analysis_result_envelope(
                    prepared_result,
                    ability_family=run.ability_family or "text",
                    ability_name=run.ability_name or "",
                    input_payload=input_payload,
                )
                repository.mark_run_succeeded(
                    run,
                    result_json=wrapped_result,
                    provider_id=candidate.provider_id,
                    model_id=candidate.model_id,
                    instance_id=candidate.instance_id,
                    fallback_used=fallback_used,
                )
                return

            if not allow_fallback:
                break

        repository.mark_run_failed(
            run,
            error_code=last_error_code,
            error_message=last_error_message,
            provider_id=last_provider_id or None,
            model_id=last_model_id or None,
            instance_id=last_instance_id or None,
            fallback_used=last_fallback_used,
        )

    def _publish_queue_signal(self, run_id: str) -> None:
        if self.runtime_queue is None:
            return
        try:
            self.runtime_queue.publish(run_id)
        except RuntimeQueueError:
            # The worker also polls queued runs from the database; a lost wake-up signal
            # must not turn a valid queued run into a failed request.
            return

    def _consume_queue_signal(self, timeout_seconds: int) -> str | None:
        if self.runtime_queue is None:
            return None
        try:
            return self.runtime_queue.consume(timeout_seconds)
        except RuntimeQueueError:
            return None

    def _merge_policy(
        self,
        default_policy: dict[str, object],
        request_policy: dict[str, object],
    ) -> dict[str, object]:
        merged = dict(default_policy)
        merged.update(normalize_runtime_request_policy(request_policy))
        return merged

    def _apply_runtime_controls(
        self,
        policy: dict[str, object],
        request: RuntimeRequest,
    ) -> dict[str, object]:
        updated = dict(policy)
        if request.timeout_seconds > 0:
            updated["timeout_seconds"] = max(0, int(request.timeout_seconds))
            updated["timeout_ms"] = max(0, int(request.timeout_seconds)) * 1000
        if request.retry_max > 0 or request.retry_max == 0:
            updated["retry_max"] = max(0, int(request.retry_max))
            updated["max_retries"] = max(0, int(request.retry_max))
        if request.retention_ttl > 0:
            updated["retention_ttl"] = max(0, int(request.retention_ttl))
        normalized_task_backend = normalize_runtime_task_backend(request.task_backend)
        if normalized_task_backend:
            updated["task_backend"] = normalized_task_backend
        updated["storage_mode"] = str(
            request.storage_mode or RUNTIME_STORAGE_MODE_RESULT_ONLY
        )
        if request.callback_url:
            updated["callback_url"] = str(request.callback_url or "").strip()
        return updated

    def _require_active_site(
        self,
        repository: RuntimeRepository,
        site_id: str,
    ) -> Any:
        site = repository.get_site(site_id)
        if site is None:
            raise RuntimeSiteNotProvisionedError(site_id)
        if site.status != SITE_STATUS_ACTIVE:
            raise RuntimeSiteInactiveError(site_id, site.status)
        return site

    def _build_execution_contract(
        self,
        *,
        request: RuntimeRequest,
        resolution: RoutingResolution,
        site: Any,
    ) -> dict[str, object]:
        if not str(request.ability_name or "").strip():
            raise RuntimeExecutionContractError(
                "runtime.contract_invalid",
                "ability_name is required for hosted runtime execution",
            )
        if not str(request.contract_version or "").strip():
            raise RuntimeExecutionContractError(
                "runtime.contract_version_required",
                "contract_version is required for hosted runtime execution",
            )
        if request.profile_id != resolution.profile_id:
            raise RuntimeExecutionContractError(
                "runtime.contract_profile_mismatch",
                "profile_id does not match the resolved routing profile",
            )
        if request.timeout_seconds > RUNTIME_MAX_TIMEOUT_SECONDS:
            raise RuntimeExecutionContractError(
                "runtime.contract_timeout_exceeded",
                f"timeout_seconds exceeds max allowed value {RUNTIME_MAX_TIMEOUT_SECONDS}",
            )
        if request.retry_max > RUNTIME_MAX_RETRY_MAX:
            raise RuntimeExecutionContractError(
                "runtime.contract_retry_exceeded",
                f"retry_max exceeds max allowed value {RUNTIME_MAX_RETRY_MAX}",
            )
        if request.retention_ttl > RUNTIME_MAX_RETENTION_TTL:
            raise RuntimeExecutionContractError(
                "runtime.contract_retention_exceeded",
                f"retention_ttl exceeds max allowed value {RUNTIME_MAX_RETENTION_TTL}",
            )
        if (
            request.storage_mode == RUNTIME_STORAGE_MODE_FULL_STORE_WITH_TTL
            and request.retention_ttl <= 0
        ):
            raise RuntimeExecutionContractError(
                "runtime.contract_retention_required",
                "full_store_with_ttl requires a positive retention_ttl",
            )

        task_backend = normalize_runtime_task_backend(request.task_backend)
        callback_mode = str(task_backend.get("callback_mode") or "")
        callback_target = self._resolve_callback_target(
            site=site,
            request=request,
            callback_mode=callback_mode,
        )
        if request.execution_pattern == "whole_run_offload" and not bool(
            task_backend.get("enabled")
        ):
            raise RuntimeExecutionContractError(
                "runtime.contract_task_backend_required",
                "whole_run_offload requires task_backend.enabled=true",
            )

        return {
            "ability_name": request.ability_name,
            "contract_version": request.contract_version,
            "profile_id": resolution.profile_id,
            "execution_pattern": request.execution_pattern,
            "data_classification": request.data_classification,
            "storage_mode": request.storage_mode,
            "timeout_seconds": max(0, request.timeout_seconds),
            "retry_max": max(0, request.retry_max),
            "retention_ttl": max(0, request.retention_ttl),
            "task_backend": task_backend,
            "callback_target": callback_target,
        }

    def _enforce_batch_limits(
        self,
        *,
        request: RuntimeRequest,
        commercial_decision: dict[str, object],
    ) -> None:
        batch_limits = commercial_decision.get("batch_limits")
        batch_limits = batch_limits if isinstance(batch_limits, dict) else {}
        max_batch_items = max(0, self._coerce_int(batch_limits.get("max_batch_items"), default=0))
        requested_items = self._resolve_batch_request_size(request)
        if requested_items <= 0:
            return
        if max_batch_items <= 0 or requested_items > max_batch_items:
            raise RuntimeBatchLimitExceededError(
                feature_id=self._resolve_batch_feature_id(request),
                requested_items=requested_items,
                limit=max_batch_items,
            )

    def _resolve_batch_request_size(self, request: RuntimeRequest) -> int:
        feature_id = self._resolve_batch_feature_id(request)
        input_payload = (
            request.input_payload if isinstance(request.input_payload, dict) else {}
        )
        if feature_id == "media_alt_completion":
            items = input_payload.get("items")
            if isinstance(items, list):
                return len([item for item in items if isinstance(item, dict)])
            return 0
        if feature_id == "media_nightly_image_optimize":
            items = input_payload.get("items")
            if isinstance(items, list):
                return len([item for item in items if isinstance(item, dict)])
            return max(0, self._coerce_int(input_payload.get("per_page"), default=0))
        return 0

    def _resolve_batch_feature_id(self, request: RuntimeRequest) -> str:
        workflow_id = str(request.workflow_id or "").strip()
        if workflow_id in {"media_alt_completion", "media_nightly_image_optimize"}:
            return workflow_id
        ability_name = str(request.ability_name or "").strip()
        if ability_name.endswith("/media_alt_completion"):
            return "media_alt_completion"
        if ability_name.endswith("/media_nightly_image_optimize"):
            return "media_nightly_image_optimize"
        return ""

    def _resolve_callback_target(
        self,
        *,
        site: Any,
        request: RuntimeRequest,
        callback_mode: str,
    ) -> dict[str, object]:
        registered = self._resolve_registered_callback_config(site)
        requires_callback = callback_mode in {"polling_preferred", "terminal_callback_required"}
        if request.callback_url:
            if not request.allow_legacy_callback_url:
                raise RuntimeCallbackConfigurationError(
                    request.site_id,
                    "public runtime callback_url overrides are no longer accepted; "
                    "register runtime_callbacks.terminal on the site instead",
                )
            return {
                "source": "legacy_request",
                "callback_url": str(request.callback_url or "").strip(),
                "key_id": "",
                "callback_id": "",
                "registered": False,
            }
        if not requires_callback:
            return {}
        if not bool(registered.get("enabled")):
            if callback_mode == "terminal_callback_required":
                raise RuntimeCallbackConfigurationError(
                    request.site_id,
                    "terminal callback is disabled for the site",
                )
            return {}
        callback_url = str(registered.get("callback_url") or "").strip()
        key_id = str(registered.get("key_id") or "").strip()
        secret = str(registered.get("secret") or "").strip()
        secret_error = str(registered.get("secret_error") or "").strip()
        if secret_error:
            raise RuntimeCallbackConfigurationError(
                request.site_id,
                secret_error,
            )
        if not callback_url or not key_id or not secret:
            if callback_mode == "terminal_callback_required":
                raise RuntimeCallbackConfigurationError(
                    request.site_id,
                    "terminal callback requires registered callback_url, key_id, and secret",
                )
            return {}
        return {
            "source": "site_registered",
            "callback_url": callback_url,
            "key_id": key_id,
            "callback_id": str(registered.get("callback_id") or "runtime_terminal"),
            "registered": True,
        }

    def _resolve_registered_callback_config(self, site: Any) -> dict[str, object]:
        metadata = getattr(site, "metadata_json", None) or {}
        callbacks = metadata.get("runtime_callbacks")
        callback = callbacks.get("terminal") if isinstance(callbacks, dict) else {}
        callback = callback if isinstance(callback, dict) else {}

        enabled_raw = callback.get("enabled")
        if enabled_raw is None:
            enabled_raw = metadata.get("runtime_terminal_callback_enabled")

        secret_ciphertext = str(callback.get("secret_ciphertext") or "").strip()
        legacy_secret = str(
            callback.get("secret")
            or metadata.get("runtime_terminal_callback_secret")
            or ""
        ).strip()
        secret = ""
        secret_error = ""
        if secret_ciphertext:
            try:
                secret = decrypt_runtime_terminal_callback_secret(
                    secret_ciphertext,
                    settings=self.settings,
                )
            except RuntimeError as error:
                secret_error = str(error)
        elif legacy_secret:
            secret_error = (
                "terminal callback secret must be re-saved as ciphertext before hosted callbacks "
                "can run"
            )

        return {
            "enabled": True if enabled_raw is None else bool(enabled_raw),
            "callback_url": str(
                callback.get("callback_url")
                or callback.get("url")
                or metadata.get("runtime_terminal_callback_url")
                or ""
            ).strip(),
            "key_id": str(
                callback.get("key_id")
                or metadata.get("runtime_terminal_callback_key_id")
                or ""
            ).strip(),
            "secret": secret.strip(),
            "secret_error": secret_error.strip(),
            "callback_id": str(
                callback.get("callback_id")
                or metadata.get("runtime_terminal_callback_id")
                or "runtime_terminal"
            ).strip()
            or "runtime_terminal",
        }

    def _apply_execution_contract(
        self,
        merged_policy: dict[str, object],
        *,
        execution_contract: dict[str, object],
    ) -> dict[str, object]:
        policy = dict(merged_policy)
        timeout_seconds = max(
            0,
            self._coerce_int(execution_contract.get("timeout_seconds"), default=0),
        )
        retry_max = max(0, self._coerce_int(execution_contract.get("retry_max"), default=0))
        retention_ttl = max(
            0,
            self._coerce_int(execution_contract.get("retention_ttl"), default=0),
        )
        task_backend = execution_contract.get("task_backend")
        callback_target = execution_contract.get("callback_target")
        callback_target = callback_target if isinstance(callback_target, dict) else {}

        if timeout_seconds > 0:
            policy["timeout_seconds"] = timeout_seconds
            policy["timeout_ms"] = timeout_seconds * 1000
        if retry_max > 0 or execution_contract.get("retry_max") == 0:
            policy["retry_max"] = retry_max
            policy["max_retries"] = retry_max
        if retention_ttl > 0:
            policy["retention_ttl"] = retention_ttl
        if isinstance(task_backend, dict) and task_backend:
            policy["task_backend"] = task_backend
        policy["storage_mode"] = str(
            execution_contract.get("storage_mode") or RUNTIME_STORAGE_MODE_RESULT_ONLY
        )
        policy["execution_contract"] = {
            "ability_name": str(execution_contract.get("ability_name") or ""),
            "contract_version": str(execution_contract.get("contract_version") or ""),
            "profile_id": str(execution_contract.get("profile_id") or ""),
            "execution_pattern": str(execution_contract.get("execution_pattern") or ""),
            "data_classification": str(execution_contract.get("data_classification") or ""),
            "storage_mode": str(execution_contract.get("storage_mode") or ""),
            "timeout_seconds": timeout_seconds,
            "retry_max": retry_max,
            "retention_ttl": retention_ttl,
            "task_backend": task_backend if isinstance(task_backend, dict) else {},
        }
        if callback_target:
            policy["runtime_callback"] = callback_target
            if str(callback_target.get("source") or "") == "legacy_request":
                policy["callback_url"] = str(callback_target.get("callback_url") or "")
            else:
                policy.pop("callback_url", None)
        else:
            policy.pop("runtime_callback", None)
            policy.pop("callback_url", None)
        return policy

    def _apply_routing_snapshot(
        self,
        merged_policy: dict[str, object],
        resolution: RoutingResolution,
    ) -> dict[str, object]:
        policy = dict(merged_policy)
        policy["routing_revision"] = resolution.revision
        policy["routing_candidates"] = [
            self._serialize_routing_candidate(candidate) for candidate in resolution.candidates
        ]
        return policy

    def _apply_commercial_policy_overrides(
        self,
        merged_policy: dict[str, object],
        *,
        commercial_decision: dict[str, object],
    ) -> dict[str, object]:
        policy = dict(merged_policy)
        overrides = commercial_decision.get("runtime_policy_overrides")
        overrides = overrides if isinstance(overrides, dict) else {}
        for key, value in overrides.items():
            if (
                key == "task_backend"
                and isinstance(policy.get("task_backend"), dict)
                and isinstance(value, dict)
            ):
                task_backend = dict(policy.get("task_backend") or {})
                task_backend.update(value)
                policy["task_backend"] = task_backend
                continue
            policy[key] = value
        policy = self._enforce_policy_within_execution_contract(policy)
        policy["commercial_policy"] = {
            "decision_code": str(commercial_decision.get("decision_code") or ""),
            "policy_actions": commercial_decision.get("policy_actions")
            if isinstance(commercial_decision.get("policy_actions"), list)
            else [],
            "runtime_policy_overrides": overrides,
        }
        return policy

    def _enforce_policy_within_execution_contract(
        self,
        policy: dict[str, object],
    ) -> dict[str, object]:
        execution_contract = policy.get("execution_contract")
        execution_contract = execution_contract if isinstance(execution_contract, dict) else {}
        if not execution_contract:
            return policy

        timeout_seconds = max(0, self._coerce_int(policy.get("timeout_seconds"), default=0))
        contract_timeout_seconds = max(
            0,
            self._coerce_int(execution_contract.get("timeout_seconds"), default=0),
        )
        if contract_timeout_seconds > 0 and timeout_seconds > contract_timeout_seconds:
            raise RuntimeExecutionContractError(
                "runtime.contract_override_out_of_range",
                "commercial override may not increase timeout_seconds beyond the "
                "execution contract",
            )

        retry_max = max(0, self._coerce_int(policy.get("retry_max"), default=0))
        contract_retry_max = max(
            0,
            self._coerce_int(execution_contract.get("retry_max"), default=0),
        )
        if retry_max > contract_retry_max:
            raise RuntimeExecutionContractError(
                "runtime.contract_override_out_of_range",
                "commercial override may not increase retry_max beyond the execution contract",
            )

        retention_ttl = max(0, self._coerce_int(policy.get("retention_ttl"), default=0))
        contract_retention_ttl = max(
            0,
            self._coerce_int(execution_contract.get("retention_ttl"), default=0),
        )
        if contract_retention_ttl > 0 and retention_ttl > contract_retention_ttl:
            raise RuntimeExecutionContractError(
                "runtime.contract_override_out_of_range",
                "commercial override may not increase retention_ttl beyond the execution contract",
            )

        contract_task_backend = execution_contract.get("task_backend")
        contract_task_backend = (
            contract_task_backend if isinstance(contract_task_backend, dict) else {}
        )
        task_backend = policy.get("task_backend")
        task_backend = task_backend if isinstance(task_backend, dict) else {}

        if bool(task_backend.get("enabled")) and not bool(contract_task_backend.get("enabled")):
            raise RuntimeExecutionContractError(
                "runtime.contract_override_out_of_range",
                "commercial override may not enable task_backend when the execution "
                "contract disabled it",
            )
        if not bool(task_backend.get("enabled")):
            return policy
        contract_mode = str(contract_task_backend.get("mode") or "")
        override_mode = str(task_backend.get("mode") or "")
        if contract_mode and override_mode and override_mode != contract_mode:
            raise RuntimeExecutionContractError(
                "runtime.contract_override_out_of_range",
                "commercial override may not replace task_backend.mode outside the "
                "execution contract",
            )
        contract_callback_mode = str(contract_task_backend.get("callback_mode") or "")
        override_callback_mode = str(task_backend.get("callback_mode") or "")
        if contract_callback_mode and override_callback_mode not in {"", contract_callback_mode}:
            raise RuntimeExecutionContractError(
                "runtime.contract_override_out_of_range",
                "commercial override may not widen task_backend.callback_mode beyond "
                "the execution contract",
            )
        return policy

    def _serialize_routing_candidate(self, candidate: RoutingCandidate) -> dict[str, object]:
        return {
            "provider_id": candidate.provider_id,
            "model_id": candidate.model_id,
            "instance_id": candidate.instance_id,
            "endpoint_variant": candidate.endpoint_variant,
            "region": candidate.region,
            "weight": candidate.weight,
            "health_status": candidate.health_status,
            "price_input": candidate.price_input,
            "price_output": candidate.price_output,
            "capability_tags": candidate.capability_tags,
        }

    def _deserialize_routing_candidates(self, policy: dict[str, object]) -> list[RoutingCandidate]:
        raw_candidates = policy.get("routing_candidates")
        if not isinstance(raw_candidates, list):
            return []

        candidates: list[RoutingCandidate] = []
        for item in raw_candidates:
            if not isinstance(item, dict):
                continue
            candidates.append(
                RoutingCandidate(
                    provider_id=str(item.get("provider_id") or ""),
                    model_id=str(item.get("model_id") or ""),
                    instance_id=str(item.get("instance_id") or ""),
                    endpoint_variant=str(item.get("endpoint_variant") or ""),
                    region=str(item.get("region") or ""),
                    weight=max(0, self._coerce_int(item.get("weight"), default=0)),
                    health_status=str(item.get("health_status") or "unknown"),
                    price_input=self._coerce_float(item.get("price_input")),
                    price_output=self._coerce_float(item.get("price_output")),
                    capability_tags=[
                        str(tag) for tag in item.get("capability_tags", []) if isinstance(tag, str)
                    ],
                )
            )
        return [
            candidate
            for candidate in candidates
            if candidate.provider_id and candidate.model_id and candidate.instance_id
        ]

    def _should_enqueue(
        self,
        request: RuntimeRequest,
        merged_policy: dict[str, object],
    ) -> bool:
        if request.execution_pattern == "whole_run_offload":
            return self._is_task_backend_enabled(merged_policy)
        return False

    def _is_task_backend_enabled(self, merged_policy: dict[str, object]) -> bool:
        task_backend = merged_policy.get("task_backend")
        return isinstance(task_backend, dict) and bool(task_backend.get("enabled"))

    def _build_execution_response(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        idempotent_replay: bool,
    ) -> RuntimeExecutionResponse:
        provider_calls = repository.list_provider_calls(run.run_id)
        failure_details = self._build_failure_details(run, provider_calls)
        result = build_analysis_result_envelope(
            run.result_json or {},
            ability_family=run.ability_family or "text",
            ability_name=run.ability_name or "",
            input_payload=run.input_json if isinstance(run.input_json, dict) else {},
        )
        return RuntimeExecutionResponse(
            run_id=run.run_id,
            canonical_run_id=run.canonical_run_id or "",
            status=run.status,
            trace_id=run.trace_id,
            profile_id=run.profile_id,
            provider_id=run.selected_provider_id or "",
            model_id=run.selected_model_id or "",
            instance_id=run.selected_instance_id or "",
            fallback_used=run.fallback_used,
            idempotent_replay=idempotent_replay,
            error_code=run.error_code or "",
            error_message=run.error_message or "",
            error_stage=failure_details.error_stage,
            retryable=failure_details.retryable,
            retry_exhausted=failure_details.retry_exhausted,
            provider_call_count=len(provider_calls),
            execution_context=self._build_execution_context(run),
            task_backend=self._build_task_backend_payload(run),
            run_lifecycle=self._build_run_lifecycle(run),
            result=self._apply_analysis_envelope(result, run),
        )

    def _apply_analysis_envelope(self, result: dict[str, Any], run: Any) -> dict[str, Any]:
        if (run.ability_family or "text") != "openclaw":
            return result
        return build_analysis_result_envelope(
            result,
            ability_family=run.ability_family or "text",
            ability_name=run.ability_name or "",
            input_payload=run.input_payload if hasattr(run, 'input_payload') else {},
        )

    def cleanup_expired_run_results(self, *, now: datetime | None = None) -> int:
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            purged = repository.purge_expired_run_results(now=now)
            session.commit()
            return purged

    def _dispatch_single_pending_callback(self) -> dict[str, object] | None:
        callback_request = self._claim_next_pending_callback()
        if callback_request is None:
            return None

        attempted_at = datetime.now(UTC)
        try:
            result = self.callback_dispatcher.dispatch(callback_request)
        except RuntimeCallbackDispatchError as error:
            retry_at = self._resolve_callback_retry_at(
                callback_request.run_id,
                retryable=error.retryable,
                attempted_at=attempted_at,
            )
            with get_session(self.database_url) as session:
                repository = RuntimeRepository(session)
                run = repository.get_run(callback_request.run_id)
                if run is None:
                    session.commit()
                    return None
                repository.mark_callback_delivery_failed(
                    run,
                    error_code=error.error_code,
                    error_message=error.message,
                    retry_at=retry_at,
                )
                session.commit()
                return {
                    "run_id": run.run_id,
                    "callback_status": run.callback_status,
                    "trace_id": run.trace_id,
                }

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            run = repository.get_run(callback_request.run_id)
            if run is None:
                session.commit()
                return None
            repository.mark_callback_delivered(run, delivered_at=attempted_at)
            session.commit()
            return {
                "run_id": run.run_id,
                "callback_status": run.callback_status,
                "trace_id": run.trace_id,
                "status_code": result.status_code,
            }

    def _build_failure_details(
        self,
        run: RunRecord,
        provider_calls: list[ProviderCallRecord],
    ) -> RuntimeFailureDetails:
        error_taxonomy = get_error_taxonomy(run.error_code)
        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
        max_retries = max(0, self._coerce_int(policy.get("max_retries"), default=0))
        last_provider_call = provider_calls[-1] if provider_calls else None
        retry_exhausted = False
        if (
            run.status == "failed"
            and last_provider_call is not None
            and getattr(last_provider_call, "error_code", None)
        ):
            retry_exhausted = bool(
                error_taxonomy.retryable
                and getattr(last_provider_call, "retry_count", 0) >= max_retries
            )

        return RuntimeFailureDetails(
            error_stage=error_taxonomy.error_stage,
            retryable=error_taxonomy.retryable,
            retry_exhausted=retry_exhausted,
        )

    def _build_request_fingerprint(
        self,
        request: RuntimeRequest,
        merged_policy: dict[str, object],
    ) -> str:
        canonical_payload = json.dumps(
            {
                "site_id": request.site_id,
                "ability_name": request.ability_name,
                "ability_family": request.ability_family,
                "skill_id": request.skill_id,
                "workflow_id": request.workflow_id,
                "contract_version": request.contract_version,
                "channel": request.channel,
                "execution_kind": request.execution_kind,
                "execution_tier": request.execution_tier,
                "execution_pattern": request.execution_pattern,
                "data_classification": request.data_classification,
                "profile_id": request.profile_id,
                "input": request.input_payload,
                "policy": merged_policy,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

    def _public_execution_pattern(self, execution_pattern: str) -> str:
        if execution_pattern == "whole_run_offload":
            return "whole_run_offload"
        return "inline"

    def _build_execution_context(self, run: RunRecord) -> RuntimeExecutionContext:
        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
        return RuntimeExecutionContext(
            skill_id=run.skill_id or "",
            workflow_id=run.workflow_id or "",
            contract_version=run.contract_version or "",
            ability_family=run.ability_family or "text",
            execution_tier=run.execution_tier,
            execution_pattern=self._public_execution_pattern(run.execution_pattern),
            data_classification=run.data_classification,
            storage_mode=str(policy.get("storage_mode") or RUNTIME_STORAGE_MODE_RESULT_ONLY),
        )

    def _build_execution_context_payload(self, run: RunRecord) -> dict[str, str]:
        context = self._build_execution_context(run)
        return {
            "skill_id": context.skill_id,
            "workflow_id": context.workflow_id,
            "contract_version": context.contract_version,
            "ability_family": context.ability_family,
            "execution_tier": context.execution_tier,
            "execution_pattern": context.execution_pattern,
            "data_classification": context.data_classification,
            "storage_mode": context.storage_mode,
        }

    def _build_task_backend_payload(self, run: RunRecord) -> dict[str, object]:
        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
        return self._build_task_backend_payload_from_policy(policy, run_status=run.status)

    def _build_run_lifecycle(self, run: RunRecord) -> dict[str, object]:
        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
        phase_map = {
            "queued": "queued",
            "running": "processing",
            "succeeded": "terminal",
            "failed": "terminal",
            "canceled": "terminal",
        }
        callback_requested = self._has_callback_target(policy)
        retention_ttl = max(0, self._coerce_int(policy.get("retention_ttl"), default=0))
        terminal_status = run.status if run.status in {"succeeded", "failed", "canceled"} else ""
        cancel_supported = self._supports_public_cancel(run.execution_pattern, policy)

        return {
            "phase": phase_map.get(run.status, "requested"),
            "queue_mode": self._get_queue_mode(run.execution_pattern, policy),
            "requested_at": self._serialize_timestamp(run.started_at),
            "processing_started_at": self._serialize_timestamp(run.processing_started_at),
            "terminal_at": self._serialize_timestamp(run.finished_at),
            "terminal_status": terminal_status,
            "cancel": {
                "supported": cancel_supported,
                "state": self._resolve_cancel_state(run, supported=cancel_supported),
                "requested_at": self._serialize_timestamp(run.cancel_requested_at),
                "canceled_at": self._serialize_timestamp(run.canceled_at),
            },
            "callback": {
                "requested": callback_requested,
                "mode": self._get_callback_mode(policy),
                "url_present": callback_requested,
                "dispatch_status": self._resolve_callback_dispatch_status(run, callback_requested),
                "attempt_count": max(0, int(run.callback_attempt_count or 0)),
                "last_attempt_at": self._serialize_timestamp(run.callback_last_attempt_at),
                "delivered_at": self._serialize_timestamp(run.callback_delivered_at),
                "next_attempt_at": self._serialize_timestamp(run.callback_next_attempt_at),
                "last_error_code": run.callback_last_error_code or "",
            },
            "retention": {
                "ttl_seconds": retention_ttl,
                "expires_at": self._serialize_timestamp(run.retention_expires_at),
                "state": self._get_retention_state(run, retention_ttl),
                "result_purged_at": self._serialize_timestamp(run.result_purged_at),
            },
        }

    def _serialize_runtime_diagnostic_run(self, run: RunRecord) -> dict[str, object]:
        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
        return {
            "run_id": run.run_id,
            "site_id": run.site_id,
            "status": run.status,
            "trace_id": run.trace_id,
            "ability_name": run.ability_name,
            "ability_family": run.ability_family,
            "profile_id": run.profile_id,
            "execution_pattern": self._public_execution_pattern(run.execution_pattern),
            "callback_requested": self._has_callback_target(policy),
            "callback_status": run.callback_status,
            "callback_attempt_count": max(0, int(run.callback_attempt_count or 0)),
            "callback_next_attempt_at": self._serialize_timestamp(run.callback_next_attempt_at),
            "callback_last_attempt_at": self._serialize_timestamp(run.callback_last_attempt_at),
            "callback_last_error_code": run.callback_last_error_code or "",
            "cancel_requested_at": self._serialize_timestamp(run.cancel_requested_at),
            "canceled_at": self._serialize_timestamp(run.canceled_at),
            "retention_expires_at": self._serialize_timestamp(run.retention_expires_at),
            "result_purged_at": self._serialize_timestamp(run.result_purged_at),
            "started_at": self._serialize_timestamp(run.started_at),
            "processing_started_at": self._serialize_timestamp(run.processing_started_at),
            "finished_at": self._serialize_timestamp(run.finished_at),
            "suggested_actions": self._build_runtime_suggested_actions(run),
        }

    def _is_queued_run_stale(self, run: RunRecord, current_time: datetime) -> bool:
        started_at = self._normalize_timestamp(run.started_at)
        return run.status == "queued" and started_at <= (
            current_time - timedelta(seconds=RUNTIME_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS)
        )

    def _is_running_run_stale(self, run: RunRecord, current_time: datetime) -> bool:
        if run.status != "running" or run.processing_started_at is None:
            return False
        processing_started_at = self._normalize_timestamp(run.processing_started_at)
        return processing_started_at <= (
            current_time - timedelta(seconds=RUNTIME_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS)
        )

    def _can_redeliver_callback(self, run: RunRecord, current_time: datetime) -> bool:
        if run.finished_at is None or not self._has_callback_target(
            run.policy_json if isinstance(run.policy_json, dict) else {}
        ):
            return False
        if run.callback_status == RUN_CALLBACK_STATUS_FAILED:
            return True
        if (
            run.callback_status == RUN_CALLBACK_STATUS_PENDING
            and run.callback_next_attempt_at is not None
        ):
            return self._normalize_timestamp(run.callback_next_attempt_at) <= (
                current_time
                - timedelta(seconds=RUNTIME_DIAGNOSTIC_CALLBACK_OVERDUE_AFTER_SECONDS)
            )
        return False

    def _build_runtime_suggested_actions(
        self,
        run: RunRecord,
    ) -> list[dict[str, object]]:
        current_time = datetime.now(UTC)
        actions: list[dict[str, object]] = []
        if self._is_queued_run_stale(run, current_time):
            actions.append(
                {
                    "action": "requeue_stale_queued",
                    "mode": "worker_auto",
                    "requires_operator_reason": False,
                    "requires_operator_evidence": False,
                }
            )
        if self._can_redeliver_callback(run, current_time):
            actions.append(
                {
                    "action": "redeliver_failed_callback",
                    "mode": (
                        "worker_auto"
                        if run.callback_status == RUN_CALLBACK_STATUS_PENDING
                        else "operator_repair"
                    ),
                    "requires_operator_reason": False,
                    "requires_operator_evidence": False,
                }
            )
        if self._is_running_run_stale(run, current_time):
            actions.append(
                {
                    "action": "mark_stale_running_failed",
                    "mode": "operator_only",
                    "requires_operator_reason": True,
                    "requires_operator_evidence": True,
                }
            )
        return actions

    def _decorate_abuse_guard_item(
        self,
        *,
        scope_kind: str,
        item: dict[str, object],
        observed_count: int,
        limit: int,
        signal_kind: str,
        near_limit_reason: str,
        exceeded_reason: str,
        event_code_breakdown: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        limit_ratio = self._calculate_limit_ratio(observed_count, limit)
        severity = self._classify_abuse_guard_severity(limit_ratio)
        reason_codes: list[str] = []
        if severity == "critical":
            reason_codes.append(exceeded_reason)
        elif severity == "attention":
            reason_codes.append(near_limit_reason)
        if signal_kind == "reject_storm":
            reason_codes.extend(
                self._derive_guard_breakdown_reason_codes(event_code_breakdown or [])
            )
        return {
            **item,
            "scope_kind": scope_kind,
            "signal_kind": signal_kind,
            "severity": severity,
            "observed_count": observed_count,
            "limit": limit,
            "limit_ratio": limit_ratio,
            "remaining_before_limit": max(limit - observed_count, 0),
            "exceeded_by": max(observed_count - limit, 0),
            "reason_codes": reason_codes,
            "event_code_breakdown": event_code_breakdown or [],
        }

    def _summarize_abuse_guard_pressure(
        self,
        items: list[dict[str, object]],
    ) -> dict[str, object]:
        return {
            "highest_severity": (
                "critical"
                if any(item["severity"] == "critical" for item in items)
                else "attention"
                if any(item["severity"] == "attention" for item in items)
                else "healthy"
            ),
            "healthy_count": sum(1 for item in items if item["severity"] == "healthy"),
            "attention_count": sum(1 for item in items if item["severity"] == "attention"),
            "critical_count": sum(1 for item in items if item["severity"] == "critical"),
        }

    def _calculate_limit_ratio(self, observed_count: int, limit: int) -> float:
        if limit <= 0:
            return 0.0
        return round(observed_count / limit, 3)

    def _classify_abuse_guard_severity(self, limit_ratio: float) -> str:
        if limit_ratio >= ABUSE_GUARD_CRITICAL_RATIO:
            return "critical"
        if limit_ratio >= ABUSE_GUARD_ATTENTION_RATIO:
            return "attention"
        return "healthy"

    def _derive_guard_breakdown_reason_codes(
        self,
        breakdown: list[dict[str, object]],
    ) -> list[str]:
        reason_codes: list[str] = []
        if any(item.get("event_code") == "auth.replay_blocked" for item in breakdown):
            reason_codes.append("rejects_include_replay_blocks")
        if any(item.get("event_code") == "auth.rate_limit_exceeded" for item in breakdown):
            reason_codes.append("rejects_include_rate_limits")
        if any(item.get("event_code") == "auth.payload_too_large" for item in breakdown):
            reason_codes.append("rejects_include_payload_limits")
        if any(item.get("event_code") == "auth.invalid_nonce" for item in breakdown):
            reason_codes.append("rejects_include_invalid_nonce")
        if any(item.get("event_code") == "auth.invalid_idempotency_key" for item in breakdown):
            reason_codes.append("rejects_include_invalid_idempotency_key")
        return reason_codes

    def _resolve_backlog_scope_id(
        self,
        run: RunRecord,
        scope_kind: str,
    ) -> str:
        if scope_kind == "site_id":
            return str(run.site_id or "unknown")
        if scope_kind == "ability_family":
            return str(run.ability_family or "unknown")
        if scope_kind == "execution_pattern":
            return str(run.execution_pattern or "unknown")
        return "unknown"

    def _resolve_backlog_age_seconds(
        self,
        run: RunRecord,
        current_time: datetime,
    ) -> int:
        if run.status == "running" and run.processing_started_at is not None:
            started_at = self._normalize_timestamp(run.processing_started_at)
        else:
            started_at = self._normalize_timestamp(run.started_at)
        return max(0, int((current_time - started_at).total_seconds()))

    def _summarize_backlog_status(
        self,
        ages: list[int],
        *,
        aging_after_seconds: int,
        stale_after_seconds: int,
    ) -> dict[str, object]:
        ordered = sorted(max(0, int(age)) for age in ages)
        fresh_count = sum(1 for age in ordered if age < aging_after_seconds)
        aging_count = sum(
            1 for age in ordered if age >= aging_after_seconds and age < stale_after_seconds
        )
        stale_count = sum(1 for age in ordered if age >= stale_after_seconds)
        if not ordered:
            state = "idle"
        elif stale_count > 0:
            state = "stale"
        elif aging_count > 0:
            state = "aging"
        else:
            state = "fresh_wave"
        return {
            "runs": len(ordered),
            "stale_runs": stale_count,
            "oldest_age_seconds": ordered[-1] if ordered else None,
            "p95_age_seconds": self._calculate_percentile(ordered, percentile=95),
            "state": state,
            "age_buckets": {
                "fresh": fresh_count,
                "aging": aging_count,
                "stale": stale_count,
            },
        }

    def _calculate_percentile(
        self,
        ordered_values: list[int],
        *,
        percentile: int,
    ) -> int | None:
        if not ordered_values:
            return None
        bounded = min(100, max(1, percentile))
        index = max(0, ((len(ordered_values) * bounded) - 1) // 100)
        return ordered_values[index]

    def _classify_backlog_pressure(
        self,
        *,
        queued_state: str,
        running_state: str,
    ) -> tuple[str, list[str]]:
        reasons: list[str] = []
        if queued_state == "stale":
            reasons.append("queue.stale")
        elif queued_state == "aging":
            reasons.append("queue.aging")
        if running_state == "stale":
            reasons.append("worker.stale")
        elif running_state == "aging":
            reasons.append("worker.aging")

        if any(reason.endswith(".stale") for reason in reasons):
            return "critical", reasons
        if reasons:
            return "attention", reasons
        return "healthy", []

    def _classify_backlog_bottleneck(
        self,
        *,
        queued_state: str,
        running_state: str,
    ) -> str:
        queued_abnormal = queued_state in {"aging", "stale"}
        running_abnormal = running_state in {"aging", "stale"}
        if queued_abnormal and running_abnormal:
            return "mixed"
        if queued_abnormal:
            return "queue_claiming_lag"
        if running_abnormal:
            return "worker_stall"
        return "healthy"

    def _classify_backlog_spread_state(
        self,
        *,
        pressured_scope_count: int,
        stale_scope_count: int,
        dominant_scope_share: float,
    ) -> str:
        if pressured_scope_count <= 0:
            return "none"
        if stale_scope_count <= 1 and dominant_scope_share >= 0.8:
            return "isolated"
        if pressured_scope_count == 1:
            return "isolated"
        return "multi_scope"

    def _classify_runtime_pressure(
        self,
        rules: tuple[tuple[str, bool, bool], ...],
    ) -> tuple[str, list[str]]:
        reasons: list[str] = []
        critical = False
        for code, active, is_critical in rules:
            if not active:
                continue
            reasons.append(code)
            critical = critical or is_critical
        if critical:
            return "critical", reasons
        if reasons:
            return "attention", reasons
        return "healthy", []

    def _calculate_age_seconds(
        self,
        current_time: datetime,
        serialized_timestamp: object,
    ) -> int | None:
        if not isinstance(serialized_timestamp, str) or not serialized_timestamp:
            return None
        try:
            parsed = datetime.fromisoformat(serialized_timestamp.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        age = current_time - parsed.astimezone(UTC)
        return max(0, int(age.total_seconds()))

    def _serialize_runtime_guard_event(self, event: RuntimeGuardEvent) -> dict[str, object]:
        return {
            "id": event.id,
            "auth_surface": event.auth_surface,
            "scope_kind": event.scope_kind,
            "scope_id": event.scope_id,
            "site_id": event.site_id or "",
            "key_id": event.key_id or "",
            "client_ref": event.client_ref or "",
            "event_code": event.event_code,
            "status_code": event.status_code,
            "method": event.method or "",
            "path": event.path or "",
            "trace_id": event.trace_id or "",
            "payload": event.payload_json or {},
            "created_at": self._serialize_timestamp(event.created_at),
        }

    def _build_planned_run_lifecycle(
        self,
        *,
        request: RuntimeRequest,
        policy: dict[str, object],
        initial_phase: str,
    ) -> dict[str, object]:
        callback_requested = self._has_callback_target(policy)
        retention_ttl = max(0, self._coerce_int(policy.get("retention_ttl"), default=0))
        cancel_supported = self._supports_public_cancel(request.execution_pattern, policy)
        return {
            "phase": "requested",
            "next_phase": initial_phase,
            "queue_mode": self._get_queue_mode(request.execution_pattern, policy),
            "cancel": {
                "supported": cancel_supported,
                "state": "available" if cancel_supported else "not_available",
                "requested_at": None,
                "canceled_at": None,
            },
            "callback": {
                "requested": callback_requested,
                "mode": self._get_callback_mode(policy),
                "url_present": callback_requested,
                "dispatch_status": "pending_terminal" if callback_requested else "not_requested",
                "attempt_count": 0,
                "last_attempt_at": None,
                "delivered_at": None,
                "next_attempt_at": None,
                "last_error_code": "",
            },
            "retention": {
                "ttl_seconds": retention_ttl,
                "state": "pending_terminal" if retention_ttl > 0 else "disabled",
            },
        }

    def _get_queue_mode(
        self,
        execution_pattern: str,
        policy: dict[str, object],
    ) -> str:
        if execution_pattern == "whole_run_offload" and self._is_task_backend_enabled(policy):
            return "queue_backed"
        return "inline"

    def _get_callback_mode(self, policy: dict[str, object]) -> str:
        task_backend = policy.get("task_backend")
        if isinstance(task_backend, dict):
            return str(task_backend.get("callback_mode") or "")
        return ""

    def _get_retention_state(self, run: RunRecord, retention_ttl: int) -> str:
        if retention_ttl <= 0:
            return "disabled"
        if run.finished_at is None:
            return "pending_terminal"
        if self._is_run_result_expired(run):
            return "expired"
        return "retained"

    def _is_run_result_expired(self, run: RunRecord) -> bool:
        if run.result_purged_at is not None:
            return True
        if run.retention_expires_at is None:
            return False
        retention_expires_at = self._normalize_timestamp(run.retention_expires_at)
        return retention_expires_at <= datetime.now(UTC)

    def _serialize_timestamp(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return self._normalize_timestamp(value).isoformat()

    def _normalize_timestamp(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _build_task_backend_payload_from_policy(
        self,
        policy: dict[str, object],
        *,
        run_status: str,
    ) -> dict[str, object]:
        raw_task_backend = policy.get("task_backend")
        raw_task_backend = raw_task_backend if isinstance(raw_task_backend, dict) else {}
        enabled = bool(raw_task_backend.get("enabled"))
        callback_target = self._get_callback_target(policy)
        timeout_seconds = max(0, self._coerce_int(policy.get("timeout_seconds"), default=0))
        retry_max = max(0, self._coerce_int(policy.get("retry_max"), default=0))
        retention_ttl = max(0, self._coerce_int(policy.get("retention_ttl"), default=0))

        if (
            not raw_task_backend
            and not callback_target
            and timeout_seconds <= 0
            and retry_max <= 0
            and retention_ttl <= 0
        ):
            return {}

        status_map = {
            "queued": "queued",
            "running": "running",
            "succeeded": "completed",
            "failed": "failed",
            "canceled": "canceled",
        }

        return {
            "enabled": enabled,
            "mode": str(raw_task_backend.get("mode") or ""),
            "callback_mode": str(raw_task_backend.get("callback_mode") or ""),
            "polling_interval_sec": max(
                0,
                self._coerce_int(raw_task_backend.get("polling_interval_sec"), default=0),
            ),
            "callback_url": (
                str(callback_target.get("callback_url") or "")
                if str(callback_target.get("source") or "") == "legacy_request"
                else ""
            ),
            "timeout_seconds": timeout_seconds,
            "retry_max": retry_max,
            "retention_ttl": retention_ttl,
            "status": status_map.get(run_status, "queued" if enabled else "disabled"),
        }

    def _claim_next_pending_callback(self) -> RuntimeCallbackDispatchRequest | None:
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            due_run_ids = repository.list_due_callback_run_ids(limit=1, now=datetime.now(UTC))
            if not due_run_ids:
                session.commit()
                return None

            run = repository.claim_callback_dispatch(due_run_ids[0], now=datetime.now(UTC))
            if run is None:
                session.commit()
                return None

            callback_policy = run.policy_json if isinstance(run.policy_json, dict) else {}
            callback_target = self._get_callback_target(callback_policy)
            if not callback_target:
                session.commit()
                return None
            callback_secret = ""
            if str(callback_target.get("source") or "") == "site_registered":
                site = repository.get_site(run.site_id)
                if site is None:
                    session.commit()
                    return None
                registered = self._resolve_registered_callback_config(site)
                secret_error = str(registered.get("secret_error") or "").strip()
                if secret_error:
                    repository.mark_callback_delivery_failed(
                        run,
                        error_code="runtime.callback_config_invalid",
                        error_message=secret_error,
                        retry_at=None,
                    )
                    session.commit()
                    return {
                        "run_id": run.run_id,
                        "callback_status": run.callback_status,
                        "trace_id": run.trace_id,
                    }
                callback_secret = str(registered.get("secret") or "").strip()
            payload = self._build_callback_payload(run)
            session.commit()
            return RuntimeCallbackDispatchRequest(
                run_id=run.run_id,
                trace_id=run.trace_id,
                callback_url=str(callback_target.get("callback_url") or ""),
                payload=payload,
                site_id=run.site_id,
                event=RUNTIME_CALLBACK_EVENT,
                key_id=str(callback_target.get("key_id") or ""),
                secret=callback_secret,
                callback_id=str(callback_target.get("callback_id") or run.run_id),
            )

    def _recover_stale_callback_dispatches(self, *, limit: int) -> None:
        current_time = datetime.now(UTC)
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            recovered_runs = repository.reclaim_stale_callback_dispatches(
                limit=limit,
                now=current_time,
            )
            session.commit()

        for run in recovered_runs:
            self._record_callback_dispatch_recovery(run, recovered_at=current_time)

    def _record_callback_dispatch_recovery(
        self,
        run: RunRecord,
        *,
        recovered_at: datetime,
    ) -> None:
        if run.callback_last_attempt_at is None:
            return
        last_attempt_at = self._normalize_timestamp(run.callback_last_attempt_at)
        stale_for_seconds = max(0, int((recovered_at - last_attempt_at).total_seconds()))
        try:
            self.commercial_service.record_service_audit_event(
                audit_context=ServiceAuditContext(
                    trace_id=run.trace_id,
                    idempotency_key=str(run.idempotency_key or ""),
                    method="WORKER",
                    path="/internal/workers/runtime/callback-dispatch-recovery",
                    actor_kind="system_worker",
                    actor_ref="runtime_queue",
                ),
                event_kind="runtime.callback_dispatch_recovered",
                outcome="succeeded",
                account_id=run.account_id,
                site_id=run.site_id,
                subscription_id=run.subscription_id,
                plan_version_id=run.plan_version_id,
                scope_kind="runtime_run",
                scope_id=run.run_id,
                payload_json={
                    "run_id": run.run_id,
                    "trace_id": run.trace_id,
                    "callback_status": run.callback_status,
                    "callback_attempt_count": max(0, int(run.callback_attempt_count or 0)),
                    "callback_last_attempt_at": self._serialize_timestamp(
                        run.callback_last_attempt_at
                    ),
                    "callback_next_attempt_at": self._serialize_timestamp(
                        run.callback_next_attempt_at
                    ),
                    "callback_last_error_code": (
                        run.callback_last_error_code
                        or RUNTIME_CALLBACK_DISPATCH_LEASE_RECOVERY_ERROR_CODE
                    ),
                    "recovery_action": "requeue_pending_after_stale_dispatch_lease",
                    "stale_after_seconds": (
                        RUNTIME_CALLBACK_DISPATCH_LEASE_RECOVERY_AFTER_SECONDS
                    ),
                    "stale_for_seconds": stale_for_seconds,
                },
            )
        except Exception:
            logger.exception(
                "runtime callback dispatch recovery audit failed: operation=%s "
                "run_id=%s site_id=%s trace_id=%s error_code=%s",
                "record_callback_dispatch_recovery_audit",
                run.run_id,
                run.site_id,
                run.trace_id,
                run.callback_last_error_code
                or RUNTIME_CALLBACK_DISPATCH_LEASE_RECOVERY_ERROR_CODE,
            )

    def _build_callback_payload(self, run: RunRecord) -> dict[str, object]:
        return {
            "event": "runtime.run.terminal",
            "run_id": run.run_id,
            "canonical_run_id": run.canonical_run_id or "",
            "site_id": run.site_id,
            "trace_id": run.trace_id,
            "status": run.status,
            "error_code": run.error_code or "",
            "error_message": run.error_message or "",
            "execution_context": self._build_execution_context_payload(run),
            "task_backend": self._build_task_backend_payload(run),
            "run_lifecycle": self._build_run_lifecycle(run),
            "result": self._build_callback_result_payload(run),
        }

    def _build_callback_result_payload(self, run: RunRecord) -> dict[str, object]:
        return run.result_json if isinstance(run.result_json, dict) else {}

    def _prepare_input_for_storage(
        self,
        input_payload: dict[str, Any],
        *,
        storage_mode: str,
    ) -> dict[str, Any]:
        if storage_mode in {
            RUNTIME_STORAGE_MODE_NO_STORE,
            RUNTIME_STORAGE_MODE_RESULT_ONLY,
        }:
            return {}
        return input_payload if isinstance(input_payload, dict) else {}

    def _get_execution_input_payload(self, run: RunRecord) -> dict[str, Any]:
        ciphertext = str(getattr(run, "execution_input_ciphertext", "") or "").strip()
        if ciphertext:
            return decrypt_runtime_execution_input(ciphertext, settings=self.settings)
        return run.input_json if isinstance(run.input_json, dict) else {}

    def _prepare_result_for_storage(
        self,
        result_json: dict[str, Any],
        *,
        storage_mode: str,
    ) -> dict[str, Any]:
        if storage_mode == RUNTIME_STORAGE_MODE_NO_STORE:
            return {
                "stored": False,
                "status": "omitted",
            }
        return result_json if isinstance(result_json, dict) else {}

    def _resolve_callback_retry_at(
        self,
        run_id: str,
        *,
        retryable: bool,
        attempted_at: datetime,
    ) -> datetime | None:
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            run = repository.get_run(run_id)
            session.commit()

        if run is None:
            return None

        if not retryable or run.callback_attempt_count >= self.callback_max_attempts:
            return None

        return attempted_at + timedelta(seconds=self.callback_retry_backoff_seconds)

    def _cancel_requested_before_attempt(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
    ) -> bool:
        repository.refresh_run(run)
        return run.cancel_requested_at is not None and run.status == "running"

    def _supports_public_cancel(
        self,
        execution_pattern: str,
        policy: dict[str, object],
    ) -> bool:
        return self._get_queue_mode(execution_pattern, policy) == "queue_backed"

    def _resolve_cancel_state(self, run: RunRecord, *, supported: bool) -> str:
        if not supported:
            return "not_available"
        if run.status == "canceled":
            return "canceled"
        if run.finished_at is not None:
            return "closed"
        if run.cancel_requested_at is not None:
            return "requested"
        return "available"

    def _resolve_callback_dispatch_status(self, run: RunRecord, callback_requested: bool) -> str:
        if not callback_requested:
            return RUN_CALLBACK_STATUS_NOT_REQUESTED
        if run.finished_at is None:
            return "pending_terminal"
        callback_status = str(run.callback_status or RUN_CALLBACK_STATUS_NOT_REQUESTED)
        if callback_status == RUN_CALLBACK_STATUS_NOT_REQUESTED:
            return RUN_CALLBACK_STATUS_PENDING
        if callback_status in {
            RUN_CALLBACK_STATUS_PENDING,
            RUN_CALLBACK_STATUS_DISPATCHING,
            RUN_CALLBACK_STATUS_DELIVERED,
            RUN_CALLBACK_STATUS_FAILED,
        }:
            return callback_status
        return RUN_CALLBACK_STATUS_PENDING

    def _get_callback_target(self, policy: dict[str, object]) -> dict[str, object]:
        runtime_callback = policy.get("runtime_callback")
        runtime_callback = runtime_callback if isinstance(runtime_callback, dict) else {}
        if runtime_callback:
            return runtime_callback
        callback_url = str(policy.get("callback_url") or "").strip()
        if not callback_url:
            return {}
        return {
            "source": "legacy_request",
            "callback_url": callback_url,
            "key_id": "",
            "callback_id": "",
            "registered": False,
        }

    def _has_callback_target(self, policy: dict[str, object]) -> bool:
        return bool(self._get_callback_target(policy))

    def _get_storage_mode(self, policy: dict[str, object]) -> str:
        storage_mode = str(policy.get("storage_mode") or RUNTIME_STORAGE_MODE_RESULT_ONLY)
        if storage_mode == RUNTIME_STORAGE_MODE_NO_STORE:
            return RUNTIME_STORAGE_MODE_NO_STORE
        if storage_mode == RUNTIME_STORAGE_MODE_FULL_STORE_WITH_TTL:
            return RUNTIME_STORAGE_MODE_FULL_STORE_WITH_TTL
        return RUNTIME_STORAGE_MODE_RESULT_ONLY

    def _coerce_int(self, value: object | None, *, default: int) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return default
        return default

    def _coerce_float(self, value: object | None) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None
