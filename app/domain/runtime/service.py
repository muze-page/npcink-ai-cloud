from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.adapters.callbacks.base import (
    RuntimeCallbackDispatcher,
    RuntimeCallbackDispatchError,
    RuntimeCallbackDispatchRequest,
)
from app.adapters.providers.base import (
    ProviderAdapter,
    ProviderExecutionError,
    ProviderExecutionRequest,
    ProviderExecutionResult,
)
from app.adapters.providers.registry import build_provider_adapters
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
    UsageMeterEvent,
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
from app.domain.cloud_batch_runtime.contracts import (
    CLOUD_BATCH_RUNTIME_ABILITIES,
    CLOUD_BATCH_RUNTIME_PROFILE_ID,
    CloudBatchRuntimeContractViolation,
    validate_cloud_batch_runtime_contract,
)
from app.domain.cloud_batch_runtime.service import CloudBatchRuntimeService
from app.domain.commercial.service import CommercialService, ServiceAuditContext
from app.domain.hosted_model_defaults import FREE_GPT55_TEXT_PROFILE_ID
from app.domain.image_generation.contracts import (
    IMAGE_GENERATION_ABILITIES,
    ImageGenerationContractViolation,
    validate_image_generation_runtime_contract,
)
from app.domain.image_sources.contracts import (
    IMAGE_SOURCE_ABILITIES,
    IMAGE_SOURCE_PROFILE_ID,
    ImageSourceContractViolation,
    validate_image_source_runtime_contract,
)
from app.domain.image_sources.service import ImageSourceProviderError, ImageSourceService
from app.domain.media_batch_plans.contracts import (
    MEDIA_BATCH_PLAN_ABILITIES,
    MEDIA_BATCH_PLAN_PROFILE_ID,
    MediaBatchPlanContractViolation,
    validate_media_batch_plan_runtime_contract,
)
from app.domain.media_batch_plans.service import MediaBatchPlanService
from app.domain.routing.errors import RoutingError
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
from app.domain.site_knowledge.backends import SiteKnowledgeBackendError
from app.domain.site_knowledge.contracts import (
    SITE_KNOWLEDGE_ABILITIES,
    SITE_KNOWLEDGE_CONTRACTS,
    SITE_KNOWLEDGE_SEARCH_ABILITY,
    SITE_KNOWLEDGE_STATUS_ABILITY,
    SITE_KNOWLEDGE_SYNC_ABILITY,
    SiteKnowledgeContractViolation,
    validate_site_knowledge_runtime_contract,
)
from app.domain.site_knowledge.metrics import (
    record_site_knowledge_failure_metric,
    record_site_knowledge_run_metric,
)
from app.domain.site_knowledge.service import SiteKnowledgeService
from app.domain.web_search.auto_policy import (
    attach_automatic_web_search_evidence,
    build_automatic_web_search_plan,
    build_automatic_web_search_success_report,
)
from app.domain.web_search.contracts import (
    WEB_SEARCH_ABILITIES,
    WEB_SEARCH_ABILITY,
    WEB_SEARCH_CONTRACT,
    WebSearchContractViolation,
    validate_web_search_runtime_contract,
)
from app.domain.web_search.service import WebSearchProviderError, WebSearchService

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
        self.providers = (
            providers if providers is not None else build_provider_adapters(self.settings)
        )
        self.runtime_queue = runtime_queue
        self.callback_dispatcher = callback_dispatcher
        self.callback_max_attempts = max(1, callback_max_attempts)
        self.callback_retry_backoff_seconds = max(0, callback_retry_backoff_seconds)

    def resolve(self, request: RuntimeRequest) -> dict[str, object]:
        if self._is_image_generation_request(request):
            self._validate_image_generation_contract(request)

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
            self._serialize_routing_candidate(candidate) for candidate in resolution.candidates
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
        if self._is_cloud_batch_runtime_request(request):
            return self._execute_cloud_batch_runtime_request(request)
        if self._is_media_batch_plan_request(request):
            return self._execute_media_batch_plan_request(request)
        if self._is_image_source_request(request):
            return self._execute_image_source_request(request)
        if self._is_site_knowledge_request(request):
            return self._execute_site_knowledge_request(request)
        if self._is_web_search_request(request):
            return self._execute_web_search_request(request)
        if self._is_image_generation_request(request):
            self._validate_image_generation_contract(request)

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

    def _execute_site_knowledge_request(
        self,
        request: RuntimeRequest,
    ) -> RuntimeExecutionResponse:
        self._validate_site_knowledge_contract(request)
        trace_id = request.trace_id or uuid4().hex
        run_id = f"run_{uuid4().hex}"
        merged_policy = self._build_site_knowledge_policy(request)
        request_fingerprint = self._build_request_fingerprint(request, merged_policy)
        should_enqueue = self._should_enqueue(request, merged_policy)

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            self._require_active_site(repository, request.site_id)

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
                request_kind=(
                    "status" if request.ability_name == SITE_KNOWLEDGE_STATUS_ABILITY else "execute"
                ),
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
                input_json=self._prepare_input_for_storage(
                    request.input_payload,
                    storage_mode=storage_mode,
                ),
                execution_input_ciphertext=execution_input_ciphertext,
                policy_json=merged_policy,
                selected_provider_id="site_knowledge",
                selected_model_id="site-knowledge-managed",
                selected_instance_id="cloud-runtime",
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

            self._execute_site_knowledge_run(
                run,
                repository=repository,
                input_payload=request.input_payload,
            )
            session.commit()
            return self._build_execution_response(
                run,
                repository=repository,
                idempotent_replay=False,
            )

    def _execute_cloud_batch_runtime_request(
        self,
        request: RuntimeRequest,
    ) -> RuntimeExecutionResponse:
        self._validate_cloud_batch_runtime_contract(request)
        trace_id = request.trace_id or uuid4().hex
        run_id = f"run_{uuid4().hex}"
        merged_policy = self._build_cloud_batch_runtime_policy(request)
        request_fingerprint = self._build_request_fingerprint(request, merged_policy)
        should_enqueue = self._should_enqueue(request, merged_policy)

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            self._require_active_site(repository, request.site_id)

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
                profile_id=request.profile_id or CLOUD_BATCH_RUNTIME_PROFILE_ID,
                canonical_run_id=request.canonical_run_id or None,
                status="queued" if should_enqueue else "running",
                idempotency_key=request.idempotency_key,
                request_fingerprint=request_fingerprint,
                trace_id=trace_id,
                input_json=self._prepare_input_for_storage(
                    request.input_payload,
                    storage_mode=storage_mode,
                ),
                execution_input_ciphertext=execution_input_ciphertext,
                policy_json=merged_policy,
                selected_provider_id="cloud_batch_runtime",
                selected_model_id="deterministic-content-quality-v1",
                selected_instance_id="cloud-runtime",
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

            self._execute_cloud_batch_runtime_run(
                run,
                repository=repository,
                input_payload=request.input_payload,
            )
            session.commit()
            return self._build_execution_response(
                run,
                repository=repository,
                idempotent_replay=False,
            )

    def enqueue_media_derivative_run(
        self,
        *,
        site_id: str,
        input_payload: dict[str, Any],
        source_bytes: bytes,
        watermark_bytes: bytes | None = None,
        ttl_minutes: int = 30,
        idempotency_key: str | None = None,
        trace_id: str | None = None,
    ) -> RuntimeExecutionResponse:
        import base64

        resolved_trace_id = trace_id or uuid4().hex
        run_id = f"run_{uuid4().hex}"
        resolved_idempotency_key = idempotency_key or f"auto_{uuid4().hex}"
        source_checksum = hashlib.sha256(source_bytes).hexdigest()
        watermark_checksum = hashlib.sha256(watermark_bytes).hexdigest() if watermark_bytes else ""
        media_derivative_policy = self._build_media_derivative_policy(input_payload)
        request_fingerprint = self._build_request_fingerprint_for_media_derivative(
            site_id,
            input_payload,
            source_checksum=source_checksum,
            watermark_checksum=watermark_checksum,
        )

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            self._require_active_site(repository, site_id)

            existing = repository.get_run_by_idempotency(site_id, resolved_idempotency_key)
            if existing is not None:
                if existing.request_fingerprint != request_fingerprint:
                    raise RuntimeIdempotencyConflictError(
                        site_id,
                        resolved_idempotency_key,
                    )
                session.commit()
                return self._build_execution_response(
                    existing,
                    repository=repository,
                    idempotent_replay=True,
                )

            commercial_decision = self.commercial_service.authorize_runtime_request(
                session=session,
                site_id=site_id,
                ability_family="vision",
                channel="openapi",
                execution_kind="media_derivative",
                execution_tier="cloud",
                data_classification="internal",
                trace_id=resolved_trace_id,
                idempotency_key=resolved_idempotency_key,
                request_kind="execute",
                run_id=run_id,
            )

            media_input = {
                **input_payload,
                "_source_bytes_b64": base64.b64encode(source_bytes).decode("ascii"),
            }
            if watermark_bytes:
                media_input["_watermark_bytes_b64"] = base64.b64encode(watermark_bytes).decode(
                    "ascii"
                )

            policy = {
                "storage_mode": "result_only",
                "media_derivative": media_derivative_policy,
                "execution_contract": {
                    "ability_name": "generate_optimized_media_derivative",
                    "contract_version": "media_derivative_cloud_request.v1",
                    "profile_id": "media_derivative.worker",
                    "execution_pattern": "whole_run_offload",
                    "data_classification": "internal",
                    "storage_mode": "result_only",
                    "timeout_seconds": 300,
                    "retry_max": 0,
                    "retention_ttl": 3600,
                    "task_backend": {"enabled": True},
                },
            }

            run = repository.create_run(
                run_id=run_id,
                site_id=site_id,
                account_id=str(commercial_decision.get("account_id") or "") or None,
                subscription_id=str(commercial_decision.get("subscription_id") or "") or None,
                plan_version_id=str(commercial_decision.get("plan_version_id") or "") or None,
                ability_name="generate_optimized_media_derivative",
                ability_family="vision",
                skill_id="",
                workflow_id="",
                contract_version="media_derivative_cloud_request.v1",
                channel="openapi",
                execution_kind="media_derivative",
                execution_tier="cloud",
                execution_pattern="whole_run_offload",
                data_classification="internal",
                profile_id="media_derivative.worker",
                canonical_run_id=None,
                status="queued",
                idempotency_key=resolved_idempotency_key,
                request_fingerprint=request_fingerprint,
                trace_id=resolved_trace_id,
                input_json={},
                execution_input_ciphertext=encrypt_runtime_execution_input(
                    media_input,
                    settings=self.settings,
                ),
                policy_json=policy,
                selected_provider_id="media_derivative",
                selected_model_id="pillow",
                selected_instance_id="cloud-worker",
            )
            self.commercial_service.record_run_acceptance(session=session, run=run)
            self._publish_queue_signal(run.run_id)
            session.commit()
            return self._build_execution_response(
                run,
                repository=repository,
                idempotent_replay=False,
            )

    def get_media_derivative_queue_pressure(self, *, site_id: str) -> dict[str, object]:
        queued_limit = max(1, int(self.settings.media_derivative_site_queued_limit))
        running_limit = max(1, int(self.settings.media_derivative_site_running_limit))
        default_chunk_size = max(
            1,
            min(
                int(self.settings.media_derivative_batch_default_chunk_size),
                int(self.settings.media_derivative_batch_max_chunk_size),
            ),
        )
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            counts = repository.summarize_media_derivative_queue_pressure(site_id)
            session.commit()

        queued = int(counts.get("queued") or 0)
        running = int(counts.get("running") or 0)
        queue_remaining = max(0, queued_limit - queued)
        running_remaining = max(0, running_limit - running)
        pressure_state = "healthy"
        pressure_reasons: list[str] = []
        if queued >= queued_limit:
            pressure_state = "rejecting"
            pressure_reasons.append("site_media_derivative_queue_full")
        elif running >= running_limit or queued >= max(default_chunk_size * 2, queued_limit // 2):
            pressure_state = "attention"
            if running >= running_limit:
                pressure_reasons.append("site_media_derivative_running_saturated")
            if queued >= max(default_chunk_size * 2, queued_limit // 2):
                pressure_reasons.append("site_media_derivative_queue_depth_high")

        return {
            "scope": "site",
            "site_id": site_id,
            "queued": queued,
            "running": running,
            "limits": {
                "queued": queued_limit,
                "running": running_limit,
            },
            "remaining": {
                "queued": queue_remaining,
                "running": running_remaining,
            },
            "pressure_state": pressure_state,
            "pressure_reasons": pressure_reasons,
            "recommended_chunk_size": max(1, min(default_chunk_size, queue_remaining or 1)),
        }

    def _build_request_fingerprint_for_media_derivative(
        self,
        site_id: str,
        input_payload: dict[str, Any],
        *,
        source_checksum: str,
        watermark_checksum: str = "",
    ) -> str:
        canonical_payload = json.dumps(
            {
                "site_id": site_id,
                "execution_kind": "media_derivative",
                "input": input_payload,
                "source_checksum": source_checksum,
                "watermark_checksum": watermark_checksum,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

    def _build_media_derivative_policy(self, input_payload: dict[str, Any]) -> dict[str, object]:
        cloud_job_payload = self._dict_or_empty(
            input_payload.get("cloud_job_payload")
        )
        batch_context = self._dict_or_empty(
            input_payload.get("batch_context")
        )
        return {
            "target_format": str(cloud_job_payload.get("target_format") or "webp"),
            "source_media_type": str(cloud_job_payload.get("source_media_type") or "image"),
            "batch_context": {
                "batch_id": str(batch_context.get("batch_id") or ""),
                "item_index": self._coerce_int(batch_context.get("item_index"), default=1),
                "item_count": self._coerce_int(batch_context.get("item_count"), default=1),
                "chunk_size": self._coerce_int(
                    batch_context.get("chunk_size"),
                    default=int(self.settings.media_derivative_batch_default_chunk_size),
                ),
                "explicit_avif": bool(batch_context.get("explicit_avif")),
            }
            if batch_context
            else {},
            "limits": {
                "site_queued": int(self.settings.media_derivative_site_queued_limit),
                "site_running": int(self.settings.media_derivative_site_running_limit),
                "batch_max_chunk_size": int(self.settings.media_derivative_batch_max_chunk_size),
            },
            "write_posture": "artifact_only",
            "direct_wordpress_write": False,
        }

    def _execute_media_derivative_run(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
    ) -> None:
        import base64

        from app.domain.media_derivatives.artifacts import (
            build_artifact_result_json,
            create_artifact,
        )
        from app.domain.media_derivatives.contracts import ARTIFACT_DEFAULT_TTL_MINUTES
        from app.domain.media_derivatives.errors import (
            MediaDerivativeAnimatedSourceUnavailableError,
            MediaDerivativeFormatUnavailableError,
            MediaDerivativeProcessingFailedError,
            MediaDerivativeSourceDecodeFailedError,
            MediaDerivativeSourceTooLargeError,
        )
        from app.domain.media_derivatives.metrics import record_media_derivative_job_metric
        from app.domain.media_derivatives.processor import process_media_derivative

        media_input = self._get_execution_input_payload(run)
        cloud_job_payload = media_input.get("cloud_job_payload", {})
        source_media_type = cloud_job_payload.get("source_media_type", "image")
        target_format = cloud_job_payload.get("target_format", "webp")
        max_width = int(cloud_job_payload.get("max_width", 1200))
        quality = int(cloud_job_payload.get("quality", 82))
        crop_options = cloud_job_payload.get("crop")
        crop_options = crop_options if isinstance(crop_options, dict) else None
        watermark_options = cloud_job_payload.get("watermark")
        watermark_options = watermark_options if isinstance(watermark_options, dict) else None
        ttl_minutes = int(media_input.get("ttl_minutes", ARTIFACT_DEFAULT_TTL_MINUTES))

        source_b64 = media_input.get("_source_bytes_b64", "")
        source_bytes = base64.b64decode(source_b64) if source_b64 else b""
        watermark_b64 = media_input.get("_watermark_bytes_b64", "")
        watermark_bytes = base64.b64decode(watermark_b64) if watermark_b64 else None
        processing_started_at = datetime.now(UTC)
        watermark_applied = bool(watermark_bytes) or bool(
            watermark_options and watermark_options.get("type") == "text"
        )

        if not source_bytes:
            repository.mark_run_failed(
                run,
                error_code="media_derivative.source_decode_failed",
                error_message="no source bytes found in media derivative run",
            )
            run.result_json = {
                "status": "failed",
                "error_code": "media_derivative.source_decode_failed",
                "error_message": "no source bytes found in media derivative run",
            }
            record_media_derivative_job_metric(
                session=repository.session,
                run=run,
                target_format=target_format,
                source_media_type=source_media_type,
                source_bytes=0,
                processing_started_at=processing_started_at,
                error_code="media_derivative.source_decode_failed",
                watermark_applied=watermark_applied,
            )
            return

        try:
            result = process_media_derivative(
                source_bytes=source_bytes,
                source_media_type=source_media_type,
                target_format=target_format,
                max_width=max_width,
                quality=quality,
                crop_options=crop_options,
                watermark_bytes=watermark_bytes,
                watermark_options=watermark_options,
            )
        except (
            MediaDerivativeSourceDecodeFailedError,
            MediaDerivativeSourceTooLargeError,
            MediaDerivativeAnimatedSourceUnavailableError,
            MediaDerivativeFormatUnavailableError,
            MediaDerivativeProcessingFailedError,
        ) as error:
            repository.mark_run_failed(
                run,
                error_code=error.error_code,
                error_message=error.message,
            )
            run.result_json = {
                "status": "failed",
                "error_code": error.error_code,
                "error_message": error.message,
            }
            record_media_derivative_job_metric(
                session=repository.session,
                run=run,
                target_format=target_format,
                source_media_type=source_media_type,
                source_bytes=len(source_bytes),
                processing_started_at=processing_started_at,
                error_code=error.error_code,
                watermark_applied=watermark_applied,
            )
            return

        artifact = create_artifact(
            session=repository.session,
            run_id=run.run_id,
            site_id=run.site_id,
            result=result,
            source_media_type=source_media_type,
            ttl_minutes=ttl_minutes,
        )
        result_json = build_artifact_result_json(artifact)
        repository.mark_run_succeeded(
            run,
            result_json=result_json,
            provider_id="media_derivative",
            model_id="pillow",
            instance_id="cloud-worker",
            fallback_used=False,
        )
        record_media_derivative_job_metric(
            session=repository.session,
            run=run,
            target_format=target_format,
            source_media_type=source_media_type,
            source_bytes=len(source_bytes),
            processing_started_at=processing_started_at,
            result=result,
            artifact=artifact,
            watermark_applied=watermark_applied,
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
            media_derivative_site_running_limit = max(
                1,
                int(self.settings.media_derivative_site_running_limit),
            )
            if signaled_run_id:
                candidate = repository.get_run(signaled_run_id)
                if (
                    candidate is not None
                    and candidate.execution_kind == "media_derivative"
                    and repository.count_running_media_derivative_runs(candidate.site_id)
                    >= media_derivative_site_running_limit
                ):
                    run = None
                else:
                    run = repository.claim_run_if_queued(signaled_run_id)

            if run is None:
                run = repository.claim_next_queued_run(
                    media_derivative_site_running_limit=media_derivative_site_running_limit,
                )

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

    def get_hosted_model_governance_diagnostics(
        self,
        *,
        site_id: str | None = None,
        recent_minutes: int = 60,
        limit: int = 20,
    ) -> dict[str, object]:
        current_time = datetime.now(UTC)
        recent_since = current_time - timedelta(minutes=max(1, recent_minutes))
        max_items = max(1, min(100, limit))
        with get_session(self.database_url) as session:
            run_statement = select(RunRecord).where(RunRecord.started_at >= recent_since)
            if site_id:
                run_statement = run_statement.where(RunRecord.site_id == site_id)
            runs = list(
                session.scalars(
                    run_statement.order_by(
                        RunRecord.started_at.desc(),
                        RunRecord.run_id.desc(),
                    ).limit(5000)
                )
            )

            call_statement = (
                select(ProviderCallRecord, RunRecord)
                .join(RunRecord, ProviderCallRecord.run_id == RunRecord.run_id)
                .where(ProviderCallRecord.created_at >= recent_since)
            )
            if site_id:
                call_statement = call_statement.where(RunRecord.site_id == site_id)
            provider_call_rows = list(
                session.execute(
                    call_statement.order_by(
                        ProviderCallRecord.created_at.desc(),
                        ProviderCallRecord.id.desc(),
                    ).limit(10000)
                )
            )

            meter_statement = select(UsageMeterEvent).where(
                UsageMeterEvent.created_at >= recent_since
            )
            if site_id:
                meter_statement = meter_statement.where(UsageMeterEvent.site_id == site_id)
            meter_events = list(
                session.scalars(
                    meter_statement.order_by(
                        UsageMeterEvent.created_at.desc(),
                        UsageMeterEvent.id.desc(),
                    ).limit(10000)
                )
            )

        run_ids = {run.run_id for run in runs}
        provider_call_run_ids = {
            call.run_id for call, _run in provider_call_rows if call.run_id in run_ids
        }
        meter_run_ids = {
            str(event.run_id or "") for event in meter_events if str(event.run_id or "") in run_ids
        }
        run_groups: dict[str, dict[str, object]] = {}
        profile_groups: dict[str, dict[str, object]] = {}
        execution_kind_groups: dict[str, dict[str, object]] = {}
        provider_model_groups: dict[str, dict[str, object]] = {}

        for run in runs:
            family = str(run.ability_family or "unknown").strip() or "unknown"
            profile_id = str(run.profile_id or "unknown").strip() or "unknown"
            execution_kind = str(run.execution_kind or "unknown").strip() or "unknown"
            self._update_hosted_governance_run_group(
                run_groups.setdefault(
                    family,
                    self._empty_hosted_governance_group(
                        group_kind="ability_family",
                        group_id=family,
                    ),
                ),
                run,
            )
            self._update_hosted_governance_run_group(
                profile_groups.setdefault(
                    profile_id,
                    self._empty_hosted_governance_group(
                        group_kind="profile_id",
                        group_id=profile_id,
                    ),
                ),
                run,
            )
            self._update_hosted_governance_run_group(
                execution_kind_groups.setdefault(
                    execution_kind,
                    self._empty_hosted_governance_group(
                        group_kind="execution_kind",
                        group_id=execution_kind,
                    ),
                ),
                run,
            )

        for call, run in provider_call_rows:
            family = str(run.ability_family or "unknown").strip() or "unknown"
            profile_id = str(run.profile_id or "unknown").strip() or "unknown"
            execution_kind = str(run.execution_kind or "unknown").strip() or "unknown"
            provider_model_key = f"{call.provider_id or 'unknown'}::{call.model_id or 'unknown'}"
            for group in (
                run_groups.setdefault(
                    family,
                    self._empty_hosted_governance_group(
                        group_kind="ability_family",
                        group_id=family,
                    ),
                ),
                profile_groups.setdefault(
                    profile_id,
                    self._empty_hosted_governance_group(
                        group_kind="profile_id",
                        group_id=profile_id,
                    ),
                ),
                execution_kind_groups.setdefault(
                    execution_kind,
                    self._empty_hosted_governance_group(
                        group_kind="execution_kind",
                        group_id=execution_kind,
                    ),
                ),
                provider_model_groups.setdefault(
                    provider_model_key,
                    self._empty_hosted_governance_group(
                        group_kind="provider_model",
                        group_id=provider_model_key,
                    ),
                ),
            ):
                self._update_hosted_governance_provider_call_group(group, call)

        for event in meter_events:
            family = str(event.ability_family or "unknown").strip() or "unknown"
            execution_kind = str(event.execution_kind or "unknown").strip() or "unknown"
            for group in (
                run_groups.setdefault(
                    family,
                    self._empty_hosted_governance_group(
                        group_kind="ability_family",
                        group_id=family,
                    ),
                ),
                execution_kind_groups.setdefault(
                    execution_kind,
                    self._empty_hosted_governance_group(
                        group_kind="execution_kind",
                        group_id=execution_kind,
                    ),
                ),
            ):
                self._update_hosted_governance_meter_group(group, event)

        capability_items = self._finalize_hosted_governance_groups(
            run_groups.values(),
            limit=max_items,
            provider_call_run_ids=provider_call_run_ids,
            meter_run_ids=meter_run_ids,
        )
        profile_items = self._finalize_hosted_governance_groups(
            profile_groups.values(),
            limit=max_items,
            provider_call_run_ids=provider_call_run_ids,
            meter_run_ids=meter_run_ids,
        )
        execution_kind_items = self._finalize_hosted_governance_groups(
            execution_kind_groups.values(),
            limit=max_items,
            provider_call_run_ids=provider_call_run_ids,
            meter_run_ids=meter_run_ids,
        )
        provider_model_items = self._finalize_hosted_governance_groups(
            provider_model_groups.values(),
            limit=max_items,
            provider_call_run_ids=provider_call_run_ids,
            meter_run_ids=meter_run_ids,
        )
        governance_gaps = self._build_hosted_governance_gap_summary(
            capability_items=capability_items,
            runs_total=len(runs),
            provider_call_run_ids=provider_call_run_ids,
            meter_run_ids=meter_run_ids,
        )
        result: dict[str, object] = {
            "filters": {
                "site_id": site_id or "",
                "recent_minutes": recent_minutes,
                "limit": max_items,
            },
            "generated_at": self._serialize_timestamp(current_time),
            "window": {
                "since": self._serialize_timestamp(recent_since),
                "until": self._serialize_timestamp(current_time),
            },
            "totals": {
                "runs": len(runs),
                "provider_calls": len(provider_call_rows),
                "usage_meter_events": len(meter_events),
                "provider_call_run_coverage_rate": self._safe_ratio(
                    len(provider_call_run_ids),
                    len(runs),
                ),
                "metered_run_coverage_rate": self._safe_ratio(len(meter_run_ids), len(runs)),
            },
            "capability_groups": capability_items,
            "profile_groups": profile_items,
            "execution_kind_groups": execution_kind_items,
            "provider_model_groups": provider_model_items,
            "governance_gaps": governance_gaps,
            "boundary": {
                "surface": "internal_operator_diagnostics",
                "cloud_role": "hosted_runtime_detail",
                "local_control_plane": "wordpress_plugin",
                "direct_wordpress_write": False,
                "contains_prompt_or_result_payloads": False,
            },
        }
        result["alert_summary"] = self._build_hosted_governance_alert_summary(result)
        return result

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
                    "total_runs": self._coerce_int(item_queued.get("runs"), default=0)
                    + self._coerce_int(item_running.get("runs"), default=0),
                    "queued": item_queued,
                    "running": item_running,
                    "bottleneck_state": self._classify_backlog_bottleneck(
                        queued_state=str(item_queued["state"]),
                        running_state=str(item_running["state"]),
                    ),
                    "pressure_state": pressure_state,
                    "pressure_reasons": pressure_reasons,
                    "lease_recovery_inputs": {
                        "queued_stale_runs": self._coerce_int(
                            item_queued.get("stale_runs"), default=0
                        ),
                        "running_stale_runs": self._coerce_int(
                            item_running.get("stale_runs"), default=0
                        ),
                        "total_stale_runs": (
                            self._coerce_int(item_queued.get("stale_runs"), default=0)
                            + self._coerce_int(item_running.get("stale_runs"), default=0)
                        ),
                    },
                }
            )

        def backlog_sort_key(item: dict[str, object]) -> tuple[int, int, int, str]:
            lease_recovery_inputs = self._dict_or_empty(item.get("lease_recovery_inputs"))
            return (
                0
                if item.get("pressure_state") == "critical"
                else 1
                if item.get("pressure_state") == "attention"
                else 2,
                -self._coerce_int(lease_recovery_inputs.get("total_stale_runs"), default=0),
                -self._coerce_int(item.get("total_runs"), default=0),
                str(item.get("scope_id") or ""),
            )

        items.sort(key=backlog_sort_key)
        limited_items = items[: max(1, limit)]
        active_scope_count = len(items)
        pressured_scope_count = sum(1 for item in items if item["pressure_state"] != "healthy")
        stale_scope_count = sum(
            1
            for item in items
            if self._coerce_int(
                self._dict_or_empty(item.get("lease_recovery_inputs")).get("total_stale_runs"),
                default=0,
            )
            > 0
        )
        total_active_runs = max(
            1,
            self._coerce_int(total_queued.get("runs"), default=0)
            + self._coerce_int(total_running.get("runs"), default=0),
        )
        dominant_scope_share = (
            round(self._coerce_int(items[0].get("total_runs"), default=0) / total_active_runs, 3)
            if items
            else 0.0
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
                    "queued_stale_runs": self._coerce_int(
                        total_queued.get("stale_runs"), default=0
                    ),
                    "running_stale_runs": self._coerce_int(
                        total_running.get("stale_runs"), default=0
                    ),
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

    def _empty_hosted_governance_group(
        self,
        *,
        group_kind: str,
        group_id: str,
    ) -> dict[str, object]:
        return {
            "group_kind": group_kind,
            "group_id": group_id,
            "run_ids": set(),
            "provider_call_run_ids": set(),
            "meter_run_ids": set(),
            "runs_total": 0,
            "succeeded": 0,
            "failed": 0,
            "queued": 0,
            "running": 0,
            "canceled": 0,
            "provider_calls": 0,
            "provider_errors": 0,
            "latency_ms_total": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "cost": 0.0,
            "meter_events": 0,
            "meter_totals": {},
            "profile_ids": set(),
            "execution_kinds": set(),
            "provider_ids": set(),
            "model_ids": set(),
            "instance_ids": set(),
            "data_classifications": set(),
        }

    def _update_hosted_governance_run_group(
        self,
        group: dict[str, object],
        run: RunRecord,
    ) -> None:
        cast(set[str], group["run_ids"]).add(run.run_id)
        group["runs_total"] = self._coerce_int(group.get("runs_total"), default=0) + 1
        status = str(run.status or "unknown")
        if status == "succeeded":
            group["succeeded"] = self._coerce_int(group.get("succeeded"), default=0) + 1
        elif status == "failed":
            group["failed"] = self._coerce_int(group.get("failed"), default=0) + 1
        elif status == "queued":
            group["queued"] = self._coerce_int(group.get("queued"), default=0) + 1
        elif status == "running":
            group["running"] = self._coerce_int(group.get("running"), default=0) + 1
        elif status == "canceled":
            group["canceled"] = self._coerce_int(group.get("canceled"), default=0) + 1

        self._add_nonempty(cast(set[str], group["profile_ids"]), run.profile_id)
        self._add_nonempty(cast(set[str], group["execution_kinds"]), run.execution_kind)
        self._add_nonempty(
            cast(set[str], group["data_classifications"]),
            run.data_classification,
        )

    def _update_hosted_governance_provider_call_group(
        self,
        group: dict[str, object],
        call: ProviderCallRecord,
    ) -> None:
        cast(set[str], group["run_ids"]).add(call.run_id)
        cast(set[str], group["provider_call_run_ids"]).add(call.run_id)
        group["provider_calls"] = self._coerce_int(group.get("provider_calls"), default=0) + 1
        if call.error_code:
            group["provider_errors"] = self._coerce_int(group.get("provider_errors"), default=0) + 1
        group["latency_ms_total"] = self._coerce_int(
            group.get("latency_ms_total"), default=0
        ) + self._coerce_int(call.latency_ms, default=0)
        group["tokens_in"] = self._coerce_int(group.get("tokens_in"), default=0) + self._coerce_int(
            call.tokens_in, default=0
        )
        group["tokens_out"] = self._coerce_int(
            group.get("tokens_out"), default=0
        ) + self._coerce_int(call.tokens_out, default=0)
        cost = self._coerce_float(group.get("cost")) or 0.0
        group["cost"] = round(cost + float(call.cost or 0.0), 8)
        self._add_nonempty(cast(set[str], group["provider_ids"]), call.provider_id)
        self._add_nonempty(cast(set[str], group["model_ids"]), call.model_id)
        self._add_nonempty(cast(set[str], group["instance_ids"]), call.instance_id)

    def _update_hosted_governance_meter_group(
        self,
        group: dict[str, object],
        event: UsageMeterEvent,
    ) -> None:
        run_id = str(event.run_id or "").strip()
        if run_id:
            cast(set[str], group["run_ids"]).add(run_id)
            cast(set[str], group["meter_run_ids"]).add(run_id)
        group["meter_events"] = self._coerce_int(group.get("meter_events"), default=0) + 1
        meter_key = str(event.meter_key or "unknown").strip() or "unknown"
        meter_totals = cast(dict[str, float], group["meter_totals"])
        meter_totals[meter_key] = round(
            float(meter_totals.get(meter_key, 0.0)) + float(event.quantity or 0.0),
            8,
        )

    def _finalize_hosted_governance_groups(
        self,
        groups: Any,
        *,
        limit: int,
        provider_call_run_ids: set[str],
        meter_run_ids: set[str],
    ) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for raw_group in groups:
            group = dict(raw_group)
            run_ids = cast(set[str], group.pop("run_ids", set()))
            group_provider_call_run_ids = cast(
                set[str],
                group.pop("provider_call_run_ids", set()),
            )
            group_meter_run_ids = cast(set[str], group.pop("meter_run_ids", set()))
            runs_total = max(
                self._coerce_int(group.get("runs_total"), default=0),
                len(run_ids),
            )
            provider_calls = self._coerce_int(group.get("provider_calls"), default=0)
            provider_errors = self._coerce_int(group.get("provider_errors"), default=0)
            latency_total = self._coerce_int(group.pop("latency_ms_total", 0), default=0)
            tokens_in = self._coerce_int(group.get("tokens_in"), default=0)
            tokens_out = self._coerce_int(group.get("tokens_out"), default=0)
            group["runs_total"] = runs_total
            group["tokens_total"] = tokens_in + tokens_out
            group["avg_latency_ms"] = (
                round(latency_total / provider_calls, 2) if provider_calls else 0.0
            )
            group["provider_error_rate"] = self._safe_ratio(provider_errors, provider_calls)
            group["provider_call_run_coverage_rate"] = self._safe_ratio(
                len(run_ids & provider_call_run_ids) or len(group_provider_call_run_ids),
                runs_total,
            )
            group["metered_run_coverage_rate"] = self._safe_ratio(
                len(run_ids & meter_run_ids) or len(group_meter_run_ids),
                runs_total,
            )
            group["profile_ids"] = sorted(cast(set[str], group["profile_ids"]))[:10]
            group["execution_kinds"] = sorted(cast(set[str], group["execution_kinds"]))[:10]
            group["provider_ids"] = sorted(cast(set[str], group["provider_ids"]))[:10]
            group["model_ids"] = sorted(cast(set[str], group["model_ids"]))[:10]
            group["instance_ids"] = sorted(cast(set[str], group["instance_ids"]))[:10]
            group["data_classifications"] = sorted(cast(set[str], group["data_classifications"]))[
                :10
            ]
            items.append(group)

        items.sort(
            key=lambda item: (
                -self._coerce_int(item.get("runs_total"), default=0),
                -self._coerce_int(item.get("provider_calls"), default=0),
                -(self._coerce_float(item.get("cost")) or 0.0),
                str(item.get("group_id") or ""),
            )
        )
        return items[: max(1, limit)]

    def _build_hosted_governance_gap_summary(
        self,
        *,
        capability_items: list[dict[str, object]],
        runs_total: int,
        provider_call_run_ids: set[str],
        meter_run_ids: set[str],
    ) -> dict[str, object]:
        unmetered_capabilities = [
            str(item.get("group_id") or "")
            for item in capability_items
            if self._coerce_int(item.get("runs_total"), default=0) > 0
            and (self._coerce_float(item.get("metered_run_coverage_rate")) or 0.0)
            < 1.0
        ]
        missing_provider_call_capabilities = [
            str(item.get("group_id") or "")
            for item in capability_items
            if self._coerce_int(item.get("runs_total"), default=0) > 0
            and self._coerce_int(item.get("provider_calls"), default=0) <= 0
            and str(item.get("group_id") or "") not in {"vision"}
        ]
        return {
            "unmetered_capabilities": unmetered_capabilities,
            "missing_provider_call_capabilities": missing_provider_call_capabilities,
            "unmetered_run_count": max(0, runs_total - len(meter_run_ids)),
            "runs_without_provider_call_count": max(0, runs_total - len(provider_call_run_ids)),
            "review_guidance": (
                "Inspect capabilities below full metering coverage before enabling "
                "new hosted model families at higher traffic."
            )
            if unmetered_capabilities or missing_provider_call_capabilities
            else "Recent hosted model families have runtime meter coverage in this window.",
        }

    def _build_hosted_governance_alert_summary(
        self,
        diagnostics: dict[str, object],
    ) -> dict[str, object]:
        totals = self._dict_or_empty(diagnostics.get("totals"))
        gaps = self._dict_or_empty(diagnostics.get("governance_gaps"))
        raw_capability_items = diagnostics.get("capability_groups")
        raw_capability_items = (
            raw_capability_items if isinstance(raw_capability_items, list) else []
        )
        capability_items = [
            self._dict_or_empty(item)
            for item in raw_capability_items
            if isinstance(item, dict)
        ]
        runs_total = self._coerce_int(totals.get("runs"), default=0)
        provider_calls = self._coerce_int(totals.get("provider_calls"), default=0)
        meter_events = self._coerce_int(totals.get("usage_meter_events"), default=0)
        metered_rate = self._coerce_float(totals.get("metered_run_coverage_rate")) or 0.0
        provider_rate = self._coerce_float(totals.get("provider_call_run_coverage_rate")) or 0.0
        unmetered_run_count = self._coerce_int(gaps.get("unmetered_run_count"), default=0)
        runs_without_provider_call_count = self._coerce_int(
            gaps.get("runs_without_provider_call_count"),
            default=0,
        )

        alerts: list[dict[str, object]] = []

        def add_alert(
            *,
            code: str,
            severity: str,
            title: str,
            summary: str,
            count: int,
            capabilities: list[str],
            suggested_action: str,
        ) -> None:
            alerts.append(
                {
                    "code": code,
                    "severity": severity,
                    "title": title,
                    "summary": summary,
                    "count": max(0, count),
                    "capabilities": capabilities[:10],
                    "suggested_action": suggested_action,
                    "href": "/admin/hosted-models",
                }
            )

        unmetered_capabilities = [
            str(item)
            for item in self._list_or_empty(gaps.get("unmetered_capabilities"))
            if str(item or "").strip()
        ]
        if unmetered_run_count > 0 or unmetered_capabilities:
            add_alert(
                code="hosted_model.unmetered_runs",
                severity="error",
                title="Hosted model meter coverage gap",
                summary="Some hosted model runs are not represented in usage metering.",
                count=unmetered_run_count,
                capabilities=unmetered_capabilities,
                suggested_action="inspect_metering_callback_or_usage_event_mapping",
            )

        provider_gap_capabilities = [
            str(item.get("group_id") or "")
            for item in capability_items
            if isinstance(item, dict)
            and self._coerce_int(item.get("runs_total"), default=0) > 0
            and (self._coerce_float(item.get("provider_call_run_coverage_rate")) or 0.0)
            < 1.0
        ]
        if runs_without_provider_call_count > 0 or provider_gap_capabilities:
            add_alert(
                code="hosted_model.provider_call_gap",
                severity="warning",
                title="Hosted model provider call coverage gap",
                summary="Some hosted runs do not have matching provider call telemetry.",
                count=runs_without_provider_call_count,
                capabilities=provider_gap_capabilities,
                suggested_action="inspect_provider_call_recording_for_hosted_profiles",
            )

        provider_error_groups = [
            str(item.get("group_id") or "")
            for item in capability_items
            if isinstance(item, dict)
            and self._coerce_int(item.get("provider_errors"), default=0) > 0
        ]
        provider_errors = sum(
            self._coerce_int(item.get("provider_errors"), default=0)
            for item in capability_items
            if isinstance(item, dict)
        )
        if provider_errors > 0:
            add_alert(
                code="hosted_model.provider_errors",
                severity="error" if provider_errors >= 5 else "warning",
                title="Hosted model provider errors",
                summary="Provider calls are returning errors in the current governance window.",
                count=provider_errors,
                capabilities=provider_error_groups,
                suggested_action="inspect_provider_credentials_quota_and_health",
            )

        failed_groups = [
            str(item.get("group_id") or "")
            for item in capability_items
            if isinstance(item, dict) and self._coerce_int(item.get("failed"), default=0) > 0
        ]
        failed_runs = sum(
            self._coerce_int(item.get("failed"), default=0)
            for item in capability_items
            if isinstance(item, dict)
        )
        if failed_runs > 0:
            add_alert(
                code="hosted_model.failed_runs",
                severity="warning",
                title="Hosted model failed runs",
                summary="Hosted model runs are failing before or during provider execution.",
                count=failed_runs,
                capabilities=failed_groups,
                suggested_action="inspect_runtime_failure_detail_for_hosted_models",
            )

        alerts.sort(
            key=lambda item: (
                0 if item["severity"] == "error" else 1,
                -self._coerce_int(item.get("count"), default=0),
                str(item.get("code") or ""),
            )
        )
        status = (
            "inactive"
            if runs_total <= 0
            else "error"
            if any(item["severity"] == "error" for item in alerts)
            else "warning"
            if alerts
            else "ok"
        )
        if status == "inactive":
            summary = "No hosted model runs were observed in this governance window."
            next_action = "continue_monitoring"
        elif status == "error":
            summary = "Hosted model governance has coverage or provider errors that need review."
            next_action = str(alerts[0].get("suggested_action") or "inspect_hosted_models")
        elif status == "warning":
            summary = "Hosted model governance has telemetry gaps to review before traffic expands."
            next_action = str(alerts[0].get("suggested_action") or "inspect_hosted_models")
        else:
            summary = "Hosted model governance is covered in this window."
            next_action = "continue_monitoring"

        return {
            "status": status,
            "summary": summary,
            "next_action": next_action,
            "href": "/admin/hosted-models",
            "alerts": alerts[:8],
            "alert_count": len(alerts),
            "daily_digest": {
                "runs": runs_total,
                "provider_calls": provider_calls,
                "meter_events": meter_events,
                "metered_run_coverage_rate": metered_rate,
                "provider_call_run_coverage_rate": provider_rate,
                "unmetered_run_count": unmetered_run_count,
                "runs_without_provider_call_count": runs_without_provider_call_count,
            },
            "boundary": {
                "surface": "internal_admin_summary",
                "cloud_role": "hosted_runtime_detail",
                "local_control_plane": "wordpress_plugin",
                "direct_wordpress_write": False,
                "contains_prompt_or_result_payloads": False,
            },
        }

    def _add_nonempty(self, values: set[str], value: object) -> None:
        normalized = str(value or "").strip()
        if normalized:
            values.add(normalized)

    def _safe_ratio(self, numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(max(0, numerator) / denominator, 4)

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
            running_stale_runs = (
                repository.list_runtime_diagnostic_runs(
                    issue_kind="running_stale",
                    site_id=site_id,
                    limit=max(1, suggestion_limit) if suggestion_limit > 0 else 1,
                )
                if suggestion_limit > 0
                else []
            )
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
            scope_spec = scope_specs[scope_kind]
            request_limit = max(0, self._coerce_int(scope_spec.get("request_limit"), default=0))
            cooldown_limit = max(0, self._coerce_int(scope_spec.get("cooldown_limit"), default=0))
            request_items = [
                self._decorate_abuse_guard_item(
                    scope_kind=scope_kind,
                    item=item,
                    observed_count=max(0, self._coerce_int(item.get("request_count"), default=0)),
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
                        observed_count=max(0, self._coerce_int(item.get("event_count"), default=0)),
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
                item for item in (*request_items, *cooldown_items) if item["severity"] != "healthy"
            )

        sorted_watchlist = sorted(
            watchlist,
            key=lambda item: (
                0 if item.get("severity") == "critical" else 1,
                -(self._coerce_float(item.get("limit_ratio")) or 0.0),
                -self._coerce_int(item.get("observed_count"), default=0),
                str(item.get("scope_kind") or ""),
                str(item.get("scope_id") or ""),
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
        queue = self._dict_or_empty(summary.get("queue"))
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

        cancel = self._dict_or_empty(summary.get("cancel"))
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

        callback = self._dict_or_empty(summary.get("callback"))
        pending = max(0, self._coerce_int(callback.get("pending"), default=0))
        due_now = max(0, self._coerce_int(callback.get("due_now"), default=0))
        failed = max(0, self._coerce_int(callback.get("failed"), default=0))
        dispatching = max(0, self._coerce_int(callback.get("dispatching"), default=0))
        recoverable_dispatching = max(
            0, self._coerce_int(callback.get("recoverable_dispatching"), default=0)
        )
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

        failures = self._dict_or_empty(summary.get("failures"))
        failed_recent = max(0, self._coerce_int(failures.get("failed_recent"), default=0))
        provider_error_calls_recent = max(
            0,
            self._coerce_int(failures.get("provider_error_calls_recent"), default=0),
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
            retention=self._dict_or_empty(summary.get("retention")),
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
                self._coerce_int(item.get("count"), default=0),
                str(item.get("last_seen_at") or ""),
            )

        dominant = sorted(candidates, key=sort_key, reverse=True)[0]
        error_code = str(dominant.get("error_code") or "")
        taxonomy = get_error_taxonomy(error_code)
        return {
            "error_code": error_code,
            "error_stage": taxonomy.error_stage,
            "count": self._coerce_int(dominant.get("count"), default=0),
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
        if self._coerce_int(retention.get("due_purge"), default=0) > 0:
            add_candidate(
                reason="retention_due",
                state="attention",
                evidence_path="retention.due_purge",
                action="run_retention_cleanup_or_check_ops_cadence",
                mode="worker_auto",
                priority=50,
            )

        candidates.sort(key=lambda item: self._coerce_int(item.get("priority"), default=0))
        primary = (
            candidates[0]
            if candidates
            else {
                "reason": "none",
                "state": "healthy",
                "evidence_path": "",
                "suggested_action": "continue_monitoring",
                "mode": "none",
                "priority": 100,
            }
        )
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
        if self._is_cloud_batch_runtime_run(run):
            self._execute_cloud_batch_runtime_run(run, repository=repository)
            return
        if run.execution_kind == "media_derivative":
            self._execute_media_derivative_run(run, repository=repository)
            return
        if self._is_media_batch_plan_run(run):
            self._execute_media_batch_plan_run(run, repository=repository)
            return
        if self._is_image_source_run(run):
            self._execute_image_source_run(run, repository=repository)
            return
        if self._is_site_knowledge_run(run):
            self._execute_site_knowledge_run(run, repository=repository)
            return
        if self._is_web_search_run(run):
            self._execute_web_search_run(run, repository=repository)
            return

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
        input_payload = self._apply_automatic_web_search(
            run,
            repository=repository,
            input_payload=input_payload,
            policy=policy,
        )
        if run.status == "failed":
            return
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
                        retry_count < max_retries and error.retryable and error_taxonomy.retryable
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
                automatic_web_search = policy.get("automatic_web_search")
                if isinstance(automatic_web_search, dict):
                    prepared_result = dict(prepared_result)
                    prepared_result["automatic_web_search"] = automatic_web_search
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

    def _apply_automatic_web_search(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any],
        policy: dict[str, object],
    ) -> dict[str, Any]:
        plan = build_automatic_web_search_plan(
            input_payload,
            ability_name=run.ability_name or "",
            workflow_id=run.workflow_id or "",
            channel=run.channel or "",
        )
        if plan is None:
            return input_payload

        if plan.is_dry_run:
            self._record_automatic_web_search_report(
                run,
                policy=policy,
                report=plan.to_report(status="would_search"),
            )
            return input_payload

        try:
            search_result = WebSearchService(self.settings).execute(
                site_id=run.site_id,
                ability_name=WEB_SEARCH_ABILITY,
                contract_version=WEB_SEARCH_CONTRACT,
                input_payload=plan.to_web_search_input(),
                run_id=f"{run.run_id}:automatic-web-search",
            )
        except WebSearchProviderError as error:
            if error.usage is not None:
                self._record_automatic_web_search_provider_call(
                    run,
                    repository=repository,
                    usage=error.usage,
                )
            report = plan.to_report(
                status="failed",
                error_code=error.error_code,
                message=error.message,
            )
            if error.usage is not None:
                report["usage_summary"] = {
                    "provider_id": str(getattr(error.usage, "provider_id", "") or ""),
                    "model_id": str(getattr(error.usage, "model_id", "") or ""),
                    "instance_id": str(getattr(error.usage, "instance_id", "") or ""),
                    "region": str(getattr(error.usage, "region", "") or ""),
                    "latency_ms": max(0, int(getattr(error.usage, "latency_ms", 0) or 0)),
                    "cost": max(0.0, float(getattr(error.usage, "cost", 0.0) or 0.0)),
                    "error_code": str(getattr(error.usage, "error_code", "") or ""),
                }
            self._record_automatic_web_search_report(run, policy=policy, report=report)
            if plan.is_required:
                repository.mark_run_failed(
                    run,
                    error_code=error.error_code,
                    error_message=error.message,
                    provider_id="web_search",
                    model_id="web-search-managed",
                    instance_id="cloud-runtime",
                    fallback_used=False,
                )
            return input_payload
        except WebSearchContractViolation as error:
            report = plan.to_report(
                status="failed",
                error_code=error.error_code,
                message=error.message,
            )
            self._record_automatic_web_search_report(run, policy=policy, report=report)
            if plan.is_required:
                repository.mark_run_failed(
                    run,
                    error_code=error.error_code,
                    error_message=error.message,
                    provider_id="web_search",
                    model_id="web-search-managed",
                    instance_id="cloud-runtime",
                    fallback_used=False,
                )
            return input_payload

        self._record_automatic_web_search_provider_call(
            run,
            repository=repository,
            usage=search_result.usage,
        )
        report = build_automatic_web_search_success_report(
            plan,
            search_result.result_json,
            usage=search_result.usage,
        )
        self._record_automatic_web_search_report(run, policy=policy, report=report)
        return attach_automatic_web_search_evidence(
            input_payload,
            result_json=search_result.result_json,
            report=report,
        )

    def _record_automatic_web_search_provider_call(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        usage: Any,
    ) -> None:
        provider_call = repository.record_provider_call(
            run_id=run.run_id,
            provider_id=usage.provider_id,
            model_id=usage.model_id,
            instance_id=usage.instance_id,
            region=usage.region,
            latency_ms=usage.latency_ms,
            tokens_in=0,
            tokens_out=0,
            cost=usage.cost,
            retry_count=0,
            fallback_used=False,
            error_code=usage.error_code,
        )
        self.commercial_service.record_provider_call_usage(
            session=repository.session,
            run=run,
            provider_call=provider_call,
        )

    def _record_automatic_web_search_report(
        self,
        run: RunRecord,
        *,
        policy: dict[str, object],
        report: dict[str, Any],
    ) -> None:
        updated_policy = dict(policy)
        updated_policy["automatic_web_search"] = report
        run.policy_json = updated_policy
        flag_modified(run, "policy_json")
        policy.clear()
        policy.update(updated_policy)

    def _execute_site_knowledge_run(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any] | None = None,
    ) -> None:
        if self._cancel_requested_before_attempt(run, repository=repository):
            repository.mark_run_canceled(run)
            return

        payload = (
            input_payload
            if isinstance(input_payload, dict)
            else self._get_execution_input_payload(run)
        )
        execution_started_at = datetime.now(UTC)

        def record_progress(progress: dict[str, Any]) -> None:
            run.result_json = {
                "artifact_type": "site_knowledge_sync_progress",
                "composition_role": "site_knowledge_sync_progress",
                "status": str(progress.get("status") or "running"),
                "run_id": run.run_id,
                "progress": progress,
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            }
            flag_modified(run, "result_json")
            repository.session.flush()
            repository.session.commit()

        def record_embedding_usage(
            provider_id: str,
            provider_request: ProviderExecutionRequest,
            provider_result: ProviderExecutionResult | None,
            provider_error: ProviderExecutionError | None,
        ) -> None:
            self._record_site_knowledge_embedding_provider_call(
                run,
                repository=repository,
                provider_id=provider_id,
                provider_request=provider_request,
                provider_result=provider_result,
                provider_error=provider_error,
            )

        try:
            result_json = SiteKnowledgeService(
                repository.session,
                settings=self.settings,
                providers=self.providers,
                progress_callback=record_progress
                if run.ability_name == SITE_KNOWLEDGE_SYNC_ABILITY
                else None,
                embedding_usage_callback=record_embedding_usage,
            ).execute(
                site_id=run.site_id,
                ability_name=run.ability_name,
                contract_version=run.contract_version or "",
                input_payload=payload,
                run_id=run.run_id,
            )
        except (SiteKnowledgeContractViolation, SiteKnowledgeBackendError) as error:
            repository.mark_run_failed(
                run,
                error_code=error.error_code,
                error_message=error.message,
                provider_id="site_knowledge",
                model_id="site-knowledge-managed",
                instance_id="cloud-runtime",
                fallback_used=False,
            )
            record_site_knowledge_failure_metric(
                session=repository.session,
                run=run,
                input_payload=payload,
                error_code=error.error_code,
                execution_started_at=execution_started_at,
                settings=self.settings,
            )
            return

        repository.mark_run_succeeded(
            run,
            result_json=result_json,
            provider_id="site_knowledge",
            model_id="site-knowledge-managed",
            instance_id="cloud-runtime",
            fallback_used=False,
        )
        record_site_knowledge_run_metric(
            session=repository.session,
            run=run,
            input_payload=payload,
            result_json=result_json,
            execution_started_at=execution_started_at,
            settings=self.settings,
        )

    def _record_site_knowledge_embedding_provider_call(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        provider_id: str,
        provider_request: ProviderExecutionRequest,
        provider_result: ProviderExecutionResult | None = None,
        provider_error: ProviderExecutionError | None = None,
    ) -> None:
        provider_call = repository.record_provider_call(
            run_id=run.run_id,
            provider_id=provider_id,
            model_id=provider_request.model_id,
            instance_id=provider_request.instance_id,
            region="unspecified",
            latency_ms=provider_result.latency_ms if provider_result is not None else 0,
            tokens_in=(
                provider_result.tokens_in
                if provider_result is not None
                else max(0, int(getattr(provider_error, "tokens_in", 0) or 0))
            ),
            tokens_out=(
                provider_result.tokens_out
                if provider_result is not None
                else max(0, int(getattr(provider_error, "tokens_out", 0) or 0))
            ),
            cost=(
                provider_result.cost
                if provider_result is not None
                else max(0.0, float(getattr(provider_error, "cost", 0.0) or 0.0))
            ),
            retry_count=provider_request.retry_count,
            fallback_used=False,
            error_code=provider_error.error_code if provider_error is not None else None,
        )
        self.commercial_service.record_provider_call_usage(
            session=repository.session,
            run=run,
            provider_call=provider_call,
        )

    def _execute_web_search_request(
        self,
        request: RuntimeRequest,
    ) -> RuntimeExecutionResponse:
        self._validate_web_search_contract(request)
        trace_id = request.trace_id or uuid4().hex
        run_id = f"run_{uuid4().hex}"
        merged_policy = self._build_web_search_policy(request)
        request_fingerprint = self._build_request_fingerprint(request, merged_policy)

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            self._require_active_site(repository, request.site_id)

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
            storage_mode = self._get_storage_mode(merged_policy)
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
                status="running",
                idempotency_key=request.idempotency_key,
                request_fingerprint=request_fingerprint,
                trace_id=trace_id,
                input_json=self._prepare_input_for_storage(
                    request.input_payload,
                    storage_mode=storage_mode,
                ),
                execution_input_ciphertext=None,
                policy_json=merged_policy,
                selected_provider_id="web_search",
                selected_model_id="web-search-managed",
                selected_instance_id="cloud-runtime",
            )
            self.commercial_service.record_run_acceptance(session=session, run=run)
            self._execute_web_search_run(
                run,
                repository=repository,
                input_payload=request.input_payload,
            )
            session.commit()
            return self._build_execution_response(
                run,
                repository=repository,
                idempotent_replay=False,
            )

    def _execute_web_search_run(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any] | None = None,
    ) -> None:
        if self._cancel_requested_before_attempt(run, repository=repository):
            repository.mark_run_canceled(run)
            return

        payload = (
            input_payload
            if isinstance(input_payload, dict)
            else self._get_execution_input_payload(run)
        )
        try:
            execution = WebSearchService(self.settings).execute(
                site_id=run.site_id,
                ability_name=run.ability_name,
                contract_version=run.contract_version or "",
                input_payload=payload,
                run_id=run.run_id,
            )
        except WebSearchContractViolation as error:
            repository.mark_run_failed(
                run,
                error_code=error.error_code,
                error_message=error.message,
                provider_id="web_search",
                model_id="web-search-managed",
                instance_id="cloud-runtime",
                fallback_used=False,
            )
            return
        except WebSearchProviderError as error:
            if error.usage is not None:
                provider_call = repository.record_provider_call(
                    run_id=run.run_id,
                    provider_id=error.usage.provider_id,
                    model_id=error.usage.model_id,
                    instance_id=error.usage.instance_id,
                    region=error.usage.region,
                    latency_ms=error.usage.latency_ms,
                    tokens_in=0,
                    tokens_out=0,
                    cost=error.usage.cost,
                    retry_count=0,
                    fallback_used=False,
                    error_code=error.usage.error_code or error.error_code,
                )
                self.commercial_service.record_provider_call_usage(
                    session=repository.session,
                    run=run,
                    provider_call=provider_call,
                )
            repository.mark_run_failed(
                run,
                error_code=error.error_code,
                error_message=error.message,
                provider_id="web_search",
                model_id="web-search-managed",
                instance_id="cloud-runtime",
                fallback_used=False,
            )
            return

        provider_call = repository.record_provider_call(
            run_id=run.run_id,
            provider_id=execution.usage.provider_id,
            model_id=execution.usage.model_id,
            instance_id=execution.usage.instance_id,
            region=execution.usage.region,
            latency_ms=execution.usage.latency_ms,
            tokens_in=0,
            tokens_out=0,
            cost=execution.usage.cost,
            retry_count=0,
            fallback_used=False,
            error_code=execution.usage.error_code,
        )
        self.commercial_service.record_provider_call_usage(
            session=repository.session,
            run=run,
            provider_call=provider_call,
        )
        repository.mark_run_succeeded(
            run,
            result_json=execution.result_json,
            provider_id="web_search",
            model_id="web-search-managed",
            instance_id="cloud-runtime",
            fallback_used=False,
        )

    def _execute_image_source_request(
        self,
        request: RuntimeRequest,
    ) -> RuntimeExecutionResponse:
        self._validate_image_source_contract(request)
        trace_id = request.trace_id or uuid4().hex
        run_id = f"run_{uuid4().hex}"
        merged_policy = self._build_image_source_policy(request)
        request_fingerprint = self._build_request_fingerprint(request, merged_policy)

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            self._require_active_site(repository, request.site_id)

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
            storage_mode = self._get_storage_mode(merged_policy)
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
                profile_id=request.profile_id or IMAGE_SOURCE_PROFILE_ID,
                canonical_run_id=request.canonical_run_id or None,
                status="running",
                idempotency_key=request.idempotency_key,
                request_fingerprint=request_fingerprint,
                trace_id=trace_id,
                input_json=self._prepare_input_for_storage(
                    request.input_payload,
                    storage_mode=storage_mode,
                ),
                execution_input_ciphertext=None,
                policy_json=merged_policy,
                selected_provider_id="image_source",
                selected_model_id="image-source-managed",
                selected_instance_id="cloud-runtime",
            )
            self.commercial_service.record_run_acceptance(session=session, run=run)
            self._execute_image_source_run(
                run,
                repository=repository,
                input_payload=request.input_payload,
            )
            session.commit()
            return self._build_execution_response(
                run,
                repository=repository,
                idempotent_replay=False,
            )

    def _execute_media_batch_plan_request(
        self,
        request: RuntimeRequest,
    ) -> RuntimeExecutionResponse:
        self._validate_media_batch_plan_contract(request)
        trace_id = request.trace_id or uuid4().hex
        run_id = f"run_{uuid4().hex}"
        merged_policy = self._build_media_batch_plan_policy(request)
        request_fingerprint = self._build_request_fingerprint(request, merged_policy)

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            self._require_active_site(repository, request.site_id)

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
            storage_mode = self._get_storage_mode(merged_policy)
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
                profile_id=request.profile_id or MEDIA_BATCH_PLAN_PROFILE_ID,
                canonical_run_id=request.canonical_run_id or None,
                status="running",
                idempotency_key=request.idempotency_key,
                request_fingerprint=request_fingerprint,
                trace_id=trace_id,
                input_json=self._prepare_input_for_storage(
                    request.input_payload,
                    storage_mode=storage_mode,
                ),
                execution_input_ciphertext=None,
                policy_json=merged_policy,
                selected_provider_id="media_batch_plan",
                selected_model_id="deterministic-intent-parser",
                selected_instance_id="cloud-runtime",
            )
            self.commercial_service.record_run_acceptance(session=session, run=run)
            self._execute_media_batch_plan_run(
                run,
                repository=repository,
                input_payload=request.input_payload,
            )
            session.commit()
            return self._build_execution_response(
                run,
                repository=repository,
                idempotent_replay=False,
            )

    def _execute_media_batch_plan_run(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any] | None = None,
    ) -> None:
        if self._cancel_requested_before_attempt(run, repository=repository):
            repository.mark_run_canceled(run)
            return

        payload = (
            input_payload
            if isinstance(input_payload, dict)
            else self._get_execution_input_payload(run)
        )
        try:
            execution = MediaBatchPlanService(self.settings).execute(
                site_id=run.site_id,
                ability_name=run.ability_name,
                contract_version=run.contract_version or "",
                input_payload=payload,
                run_id=run.run_id,
            )
        except MediaBatchPlanContractViolation as error:
            repository.mark_run_failed(
                run,
                error_code=error.error_code,
                error_message=error.message,
                provider_id="media_batch_plan",
                model_id="deterministic-intent-parser",
                instance_id="cloud-runtime",
                fallback_used=False,
            )
            return

        repository.mark_run_succeeded(
            run,
            result_json=execution.result_json,
            provider_id="media_batch_plan",
            model_id="deterministic-intent-parser",
            instance_id="cloud-runtime",
            fallback_used=False,
        )

    def _execute_cloud_batch_runtime_run(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any] | None = None,
    ) -> None:
        if self._cancel_requested_before_attempt(run, repository=repository):
            repository.mark_run_canceled(run)
            return

        payload = (
            input_payload
            if isinstance(input_payload, dict)
            else self._get_execution_input_payload(run)
        )
        try:
            execution = CloudBatchRuntimeService().execute(
                site_id=run.site_id,
                ability_name=run.ability_name,
                contract_version=run.contract_version or "",
                input_payload=payload,
                run_id=run.run_id,
            )
        except CloudBatchRuntimeContractViolation as error:
            repository.mark_run_failed(
                run,
                error_code=error.error_code,
                error_message=error.message,
                provider_id="cloud_batch_runtime",
                model_id="deterministic-content-quality-v1",
                instance_id="cloud-runtime",
                fallback_used=False,
            )
            return

        provider_call = repository.record_provider_call(
            run_id=run.run_id,
            provider_id="cloud_batch_runtime",
            model_id="deterministic-content-quality-v1",
            instance_id="cloud-runtime",
            region=self.settings.deployment_region,
            latency_ms=0,
            tokens_in=0,
            tokens_out=0,
            cost=0.0,
            retry_count=0,
            fallback_used=False,
        )
        self.commercial_service.record_provider_call_usage(
            session=repository.session,
            run=run,
            provider_call=provider_call,
        )
        repository.mark_run_succeeded(
            run,
            result_json=execution.result_json,
            provider_id="cloud_batch_runtime",
            model_id="deterministic-content-quality-v1",
            instance_id="cloud-runtime",
            fallback_used=False,
        )

    def _execute_image_source_run(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any] | None = None,
    ) -> None:
        if self._cancel_requested_before_attempt(run, repository=repository):
            repository.mark_run_canceled(run)
            return

        payload = (
            input_payload
            if isinstance(input_payload, dict)
            else self._get_execution_input_payload(run)
        )
        if self._image_source_fast_first(payload):
            site_knowledge_context = self._skipped_image_source_site_knowledge_context(
                reason="fast_first_deferred"
            )
            llm_prompt_plan = self._skipped_image_source_llm_prompt_plan(
                reason="fast_first_deferred"
            )
        else:
            site_knowledge_context = self._build_image_source_site_knowledge_context(
                run,
                repository=repository,
                input_payload=payload,
            )
            llm_prompt_plan = self._build_image_source_llm_prompt_plan(
                run,
                repository=repository,
                input_payload=payload,
                site_knowledge_context=site_knowledge_context,
            )
        try:
            execution = ImageSourceService(self.settings).execute(
                site_id=run.site_id,
                ability_name=run.ability_name,
                contract_version=run.contract_version or "",
                input_payload=payload,
                run_id=run.run_id,
                site_knowledge_context=site_knowledge_context,
                llm_prompt_plan=llm_prompt_plan,
            )
        except ImageSourceContractViolation as error:
            repository.mark_run_failed(
                run,
                error_code=error.error_code,
                error_message=error.message,
                provider_id="image_source",
                model_id="image-source-managed",
                instance_id="cloud-runtime",
                fallback_used=False,
            )
            return
        except ImageSourceProviderError as error:
            if error.usage is not None:
                provider_call = repository.record_provider_call(
                    run_id=run.run_id,
                    provider_id=error.usage.provider_id,
                    model_id=error.usage.model_id,
                    instance_id=error.usage.instance_id,
                    region=error.usage.region,
                    latency_ms=error.usage.latency_ms,
                    tokens_in=0,
                    tokens_out=0,
                    cost=error.usage.cost,
                    retry_count=0,
                    fallback_used=False,
                    error_code=error.usage.error_code or error.error_code,
                )
                self.commercial_service.record_provider_call_usage(
                    session=repository.session,
                    run=run,
                    provider_call=provider_call,
                )
            repository.mark_run_failed(
                run,
                error_code=error.error_code,
                error_message=error.message,
                provider_id="image_source",
                model_id="image-source-managed",
                instance_id="cloud-runtime",
                fallback_used=False,
            )
            return

        provider_call = repository.record_provider_call(
            run_id=run.run_id,
            provider_id=execution.usage.provider_id,
            model_id=execution.usage.model_id,
            instance_id=execution.usage.instance_id,
            region=execution.usage.region,
            latency_ms=execution.usage.latency_ms,
            tokens_in=0,
            tokens_out=0,
            cost=execution.usage.cost,
            retry_count=0,
            fallback_used=False,
            error_code=execution.usage.error_code,
        )
        self.commercial_service.record_provider_call_usage(
            session=repository.session,
            run=run,
            provider_call=provider_call,
        )
        repository.mark_run_succeeded(
            run,
            result_json=execution.result_json,
            provider_id="image_source",
            model_id="image-source-managed",
            instance_id="cloud-runtime",
            fallback_used=False,
        )

    def _image_source_fast_first(self, input_payload: dict[str, Any]) -> bool:
        visual_context = self._dict_or_empty(input_payload.get("visual_context"))
        latency_mode = str(
            input_payload.get("latency_mode") or visual_context.get("latency_mode") or ""
        ).strip().lower()
        enhancement_mode = str(input_payload.get("enhancement_mode") or "").strip().lower()
        if latency_mode == "fast_first" or enhancement_mode == "deferred":
            return True

        cloud_steps = visual_context.get("cloud_ai_steps")
        if isinstance(cloud_steps, list) and cloud_steps:
            normalized_steps = {str(step).strip() for step in cloud_steps}
            return (
                "site_context_vectors" not in normalized_steps
                and "candidate_rerank" not in normalized_steps
            )
        return False

    def _skipped_image_source_site_knowledge_context(self, *, reason: str) -> dict[str, Any]:
        return {
            "status": "deferred",
            "reason": reason,
            "intent": "image_context",
            "results": [],
            "write_posture": "suggestion_only",
            "direct_wordpress_write": False,
        }

    def _skipped_image_source_llm_prompt_plan(self, *, reason: str) -> dict[str, Any]:
        return {
            "status": "deferred",
            "reason": reason,
            "fallback": "rule_prompt_candidates",
            "prompt_candidates": [],
        }

    def _build_image_source_site_knowledge_context(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any],
    ) -> dict[str, Any]:
        query = self._image_source_site_knowledge_query(input_payload)
        if not query:
            return {
                "status": "skipped",
                "reason": "no_visual_context",
                "intent": "image_context",
                "results": [],
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            }

        visual_context = self._dict_or_empty(input_payload.get("visual_context"))
        current_post_id = self._coerce_int(
            visual_context.get("post_id") or input_payload.get("post_id"),
            default=0,
        )
        candidate_limits = self._dict_or_empty(visual_context.get("candidate_limits"))
        max_results = min(
            4,
            max(
                1,
                self._coerce_int(
                    candidate_limits.get("max_site_context_results"),
                    default=3,
                ),
            ),
        )

        def record_embedding_usage(
            provider_id: str,
            provider_request: ProviderExecutionRequest,
            provider_result: ProviderExecutionResult | None,
            provider_error: ProviderExecutionError | None,
        ) -> None:
            self._record_site_knowledge_embedding_provider_call(
                run,
                repository=repository,
                provider_id=provider_id,
                provider_request=provider_request,
                provider_result=provider_result,
                provider_error=provider_error,
            )

        try:
            result = SiteKnowledgeService(
                repository.session,
                settings=self.settings,
                providers=self.providers,
                embedding_usage_callback=record_embedding_usage,
            ).execute(
                site_id=run.site_id,
                ability_name=SITE_KNOWLEDGE_SEARCH_ABILITY,
                contract_version=SITE_KNOWLEDGE_CONTRACTS[SITE_KNOWLEDGE_SEARCH_ABILITY],
                input_payload={
                    "contract_version": SITE_KNOWLEDGE_CONTRACTS[SITE_KNOWLEDGE_SEARCH_ABILITY],
                    "query": query,
                    "intent": "image_context",
                    "max_results": max_results,
                    "current_post_id": current_post_id,
                    "filters": {
                        "post_types": ["post", "page"],
                        "status": ["publish"],
                        "source_types": ["post", "page"],
                    },
                    "evidence_policy": {
                        "min_score": 0.2,
                        "required_sources": 1,
                        "no_hit_policy": "fallback_to_general",
                    },
                    "write_posture": "suggestion_only",
                },
                run_id=run.run_id,
            )
        except (SiteKnowledgeContractViolation, SiteKnowledgeBackendError) as error:
            return {
                "status": "unavailable",
                "intent": "image_context",
                "error_code": error.error_code,
                "results": [],
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            }

        results = result.get("results") if isinstance(result.get("results"), list) else []
        return {
            "status": str(result.get("status") or "ready")
            if results
            else str(result.get("evidence_gate", {}).get("status") or "insufficient_evidence"),
            "intent": str(result.get("intent") or "image_context"),
            "evidence_gate": result.get("evidence_gate")
            if isinstance(result.get("evidence_gate"), dict)
            else {},
            "rerank": result.get("rerank") if isinstance(result.get("rerank"), dict) else {},
            "results": results,
            "write_posture": "suggestion_only",
            "direct_wordpress_write": False,
        }

    def _build_image_source_llm_prompt_plan(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any],
        site_knowledge_context: dict[str, Any],
    ) -> dict[str, Any]:
        query = self._image_source_site_knowledge_query(input_payload)
        if not query:
            return {
                "status": "skipped",
                "fallback": "rule_prompt_candidates",
                "prompt_candidates": [],
            }

        try:
            candidate, profile_id, default_policy = self._resolve_image_prompt_planner_candidate()
        except RoutingError as error:
            return {
                "status": "unavailable",
                "error_code": error.error_code,
                "fallback": "rule_prompt_candidates",
                "prompt_candidates": [],
            }

        provider = self.providers.get(candidate.provider_id)
        if provider is None:
            return {
                "status": "unavailable",
                "error_code": "runtime.provider_not_configured",
                "profile_id": profile_id,
                "provider_id": candidate.provider_id,
                "model_id": candidate.model_id,
                "fallback": "rule_prompt_candidates",
                "prompt_candidates": [],
            }

        timeout_ms = max(1, self._coerce_int(default_policy.get("timeout_ms"), default=12_000))
        request = ProviderExecutionRequest(
            run_id=run.run_id,
            site_id=run.site_id,
            ability_name="magick-ai-cloud/image-prompt-planner",
            profile_id=profile_id,
            execution_kind="text",
            model_id=candidate.model_id,
            instance_id=candidate.instance_id,
            endpoint_variant=candidate.endpoint_variant,
            trace_id=run.trace_id or run.run_id,
            input_payload=self._build_image_prompt_planner_input(
                input_payload=input_payload,
                site_knowledge_context=site_knowledge_context,
            ),
            policy={"storage_mode": "result_only"},
            timeout_ms=timeout_ms,
            price_input=candidate.price_input,
            price_output=candidate.price_output,
        )
        try:
            provider_result = provider.execute(request)
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
                retry_count=0,
                fallback_used=False,
                error_code=error.error_code,
            )
            self.commercial_service.record_provider_call_usage(
                session=repository.session,
                run=run,
                provider_call=provider_call,
            )
            return {
                "status": "failed",
                "error_code": error.error_code,
                "profile_id": profile_id,
                "provider_id": candidate.provider_id,
                "model_id": candidate.model_id,
                "fallback": "rule_prompt_candidates",
                "prompt_candidates": [],
            }

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
            retry_count=0,
            fallback_used=False,
            error_code=None,
        )
        self.commercial_service.record_provider_call_usage(
            session=repository.session,
            run=run,
            provider_call=provider_call,
        )
        prompt_candidates = self._parse_image_prompt_planner_output(
            provider_result.output.get("output_text"),
        )
        if not prompt_candidates:
            return {
                "status": "failed",
                "error_code": "image_prompt_planner.invalid_output",
                "profile_id": profile_id,
                "provider_id": candidate.provider_id,
                "model_id": candidate.model_id,
                "fallback": "rule_prompt_candidates",
                "prompt_candidates": [],
            }
        return {
            "status": "ready",
            "profile_id": profile_id,
            "provider_id": candidate.provider_id,
            "model_id": candidate.model_id,
            "prompt_candidates": prompt_candidates,
        }

    def _resolve_image_prompt_planner_candidate(
        self,
    ) -> tuple[RoutingCandidate, str, dict[str, object]]:
        last_error: RoutingError | None = None
        for profile_id in (FREE_GPT55_TEXT_PROFILE_ID, "text.balanced"):
            try:
                resolution = self.routing_service.resolve(
                    profile_id=profile_id,
                    execution_kind="text",
                )
                return (
                    resolution.selected_candidate,
                    resolution.profile_id,
                    resolution.default_policy,
                )
            except RoutingError as error:
                last_error = error
        if last_error is not None:
            raise last_error
        raise RoutingError(
            "routing.profile_not_found",
            "image prompt planner text routing profile is not configured",
        )

    def _build_image_prompt_planner_input(
        self,
        *,
        input_payload: dict[str, Any],
        site_knowledge_context: dict[str, Any],
    ) -> dict[str, Any]:
        visual_context = self._dict_or_empty(input_payload.get("visual_context"))
        evidence = []
        for item in site_knowledge_context.get("results", []):
            if not isinstance(item, dict):
                continue
            evidence.append(
                {
                    "title": str(item.get("title") or "")[:160],
                    "match_context": str(item.get("match_context") or item.get("chunk_text") or "")[
                        :320
                    ],
                    "score": item.get("score", 0),
                }
            )
        planner_context = {
            "query": str(input_payload.get("query") or "")[:300],
            "image_mode": str(
                visual_context.get("image_mode") or visual_context.get("image_use") or ""
            )[:40],
            "title": str(visual_context.get("title") or "")[:160],
            "excerpt": str(visual_context.get("excerpt") or "")[:240],
            "selected_text": str(
                visual_context.get("selected_text")
                or visual_context.get("selected_block_text")
                or ""
            )[:600],
            "site_evidence": evidence[:4],
        }
        return {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an editorial image prompt planner. Return only JSON. "
                        "Plan original image-generation prompts from the selected article "
                        "context and site evidence. Do not copy article wording as visible "
                        "image text. Do not include logos, watermarks, UI screenshots, "
                        "credentials, or WordPress write instructions."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Return JSON with key prompt_candidates, an array of 1 to 3 "
                        "objects. Each object must include id, label, direction_type, "
                        "visual_strategy, reason, and prompt. Use direction_type values "
                        "like editorial_scene, conceptual_metaphor, workflow_detail, "
                        "or article_cover so the editor can show distinct visual choices. "
                        "reason must briefly explain why the direction fits the selected "
                        "paragraph and nearby article context. Prompts must be "
                        "publication-safe, concrete, and "
                        "must explicitly forbid visible text, letters, numbers, logos, "
                        "watermarks, screenshots, and copied article wording.\n\n"
                        f"Context:\n{json.dumps(planner_context, ensure_ascii=False)}"
                    ),
                },
            ],
            "params": {
                "temperature": 0.3,
                "max_tokens": 900,
                "max_output_tokens": 900,
            },
        }

    def _parse_image_prompt_planner_output(self, output_text: object) -> list[dict[str, object]]:
        text = str(output_text or "").strip()
        if not text:
            return []
        payload: object
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                return []
            try:
                payload = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return []
        if not isinstance(payload, dict):
            return []
        raw_candidates = payload.get("prompt_candidates")
        if not isinstance(raw_candidates, list):
            return []
        candidates: list[dict[str, object]] = []
        for index, item in enumerate(raw_candidates[:3], start=1):
            if not isinstance(item, dict):
                continue
            prompt = " ".join(str(item.get("prompt") or "").split())[:1200]
            if not prompt:
                continue
            candidates.append(
                {
                    "id": str(item.get("id") or f"llm_prompt_{index}")[:80],
                    "label": str(item.get("label") or f"LLM prompt {index}")[:80],
                    "direction_type": str(item.get("direction_type") or "")[:80],
                    "visual_strategy": str(item.get("visual_strategy") or "")[:160],
                    "reason": str(item.get("reason") or "")[:220],
                    "image_use": str(item.get("image_use") or "")[:80],
                    "prompt": prompt,
                }
            )
        return candidates

    def _image_source_site_knowledge_query(self, input_payload: dict[str, Any]) -> str:
        visual_context = self._dict_or_empty(input_payload.get("visual_context"))
        parts = [
            visual_context.get("selected_text"),
            visual_context.get("selected_block_text"),
            visual_context.get("manual_query"),
            visual_context.get("fallback_query"),
            visual_context.get("title"),
            visual_context.get("excerpt"),
            input_payload.get("query"),
        ]
        text = " ".join(str(part or "").strip() for part in parts if str(part or "").strip())
        return " ".join(text.split())[:500]

    def _is_image_source_request(self, request: RuntimeRequest) -> bool:
        return request.ability_name in IMAGE_SOURCE_ABILITIES

    def _is_image_generation_request(self, request: RuntimeRequest) -> bool:
        return request.ability_name in IMAGE_GENERATION_ABILITIES

    def _is_media_batch_plan_request(self, request: RuntimeRequest) -> bool:
        return request.ability_name in MEDIA_BATCH_PLAN_ABILITIES

    def _is_cloud_batch_runtime_request(self, request: RuntimeRequest) -> bool:
        return request.ability_name in CLOUD_BATCH_RUNTIME_ABILITIES

    def _is_site_knowledge_request(self, request: RuntimeRequest) -> bool:
        return request.ability_name in SITE_KNOWLEDGE_ABILITIES

    def _is_web_search_request(self, request: RuntimeRequest) -> bool:
        return request.ability_name in WEB_SEARCH_ABILITIES

    def _is_image_source_run(self, run: RunRecord) -> bool:
        return str(run.ability_name or "") in IMAGE_SOURCE_ABILITIES

    def _is_image_generation_run(self, run: RunRecord) -> bool:
        return str(run.ability_name or "") in IMAGE_GENERATION_ABILITIES

    def _is_media_batch_plan_run(self, run: RunRecord) -> bool:
        return str(run.ability_name or "") in MEDIA_BATCH_PLAN_ABILITIES

    def _is_cloud_batch_runtime_run(self, run: RunRecord) -> bool:
        return str(run.ability_name or "") in CLOUD_BATCH_RUNTIME_ABILITIES

    def _is_site_knowledge_run(self, run: RunRecord) -> bool:
        return str(run.ability_name or "") in SITE_KNOWLEDGE_ABILITIES

    def _is_web_search_run(self, run: RunRecord) -> bool:
        return str(run.ability_name or "") in WEB_SEARCH_ABILITIES

    def _validate_site_knowledge_contract(self, request: RuntimeRequest) -> None:
        try:
            validate_site_knowledge_runtime_contract(
                ability_name=request.ability_name,
                contract_version=request.contract_version,
                input_payload=request.input_payload,
            )
        except SiteKnowledgeContractViolation as error:
            raise RuntimeExecutionContractError(error.error_code, error.message) from error
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

    def _build_site_knowledge_policy(self, request: RuntimeRequest) -> dict[str, object]:
        policy = self._apply_runtime_controls(dict(request.policy), request)
        if request.ability_name == SITE_KNOWLEDGE_SYNC_ABILITY:
            policy.setdefault("allow_fallback", False)
        if request.execution_pattern == "whole_run_offload":
            task_backend = policy.get("task_backend")
            if not isinstance(task_backend, dict) or not task_backend:
                policy["task_backend"] = {
                    "enabled": True,
                    "mode": "queue",
                    "callback_mode": "polling_preferred",
                    "polling_interval_sec": 5,
                }
        policy["execution_contract"] = {
            "ability_name": request.ability_name,
            "contract_version": request.contract_version,
            "profile_id": request.profile_id,
            "execution_pattern": request.execution_pattern,
            "data_classification": request.data_classification,
            "storage_mode": request.storage_mode,
            "timeout_seconds": max(0, request.timeout_seconds),
            "retry_max": max(0, request.retry_max),
            "retention_ttl": max(0, request.retention_ttl),
            "task_backend": (
                policy.get("task_backend") if isinstance(policy.get("task_backend"), dict) else {}
            ),
        }
        return policy

    def _validate_cloud_batch_runtime_contract(self, request: RuntimeRequest) -> None:
        try:
            validate_cloud_batch_runtime_contract(
                ability_name=request.ability_name,
                contract_version=request.contract_version,
                input_payload=request.input_payload,
            )
        except CloudBatchRuntimeContractViolation as error:
            raise RuntimeExecutionContractError(error.error_code, error.message) from error
        if request.ability_name not in CLOUD_BATCH_RUNTIME_ABILITIES:
            raise RuntimeExecutionContractError(
                "cloud_batch_runtime.unknown_ability",
                "cloud batch runtime ability_name is not supported",
            )
        if request.execution_pattern not in {"inline", "whole_run_offload"}:
            raise RuntimeExecutionContractError(
                "cloud_batch_runtime.execution_pattern_invalid",
                "cloud batch runtime supports inline or whole_run_offload execution",
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

    def _build_cloud_batch_runtime_policy(self, request: RuntimeRequest) -> dict[str, object]:
        policy = self._apply_runtime_controls(dict(request.policy), request)
        policy["allow_fallback"] = False
        if request.execution_pattern == "whole_run_offload":
            task_backend = policy.get("task_backend")
            if not isinstance(task_backend, dict) or not task_backend:
                policy["task_backend"] = {
                    "enabled": True,
                    "mode": "queue",
                    "callback_mode": "polling_preferred",
                    "polling_interval_sec": 10,
                }
        policy["execution_contract"] = {
            "ability_name": request.ability_name,
            "contract_version": request.contract_version,
            "profile_id": request.profile_id or CLOUD_BATCH_RUNTIME_PROFILE_ID,
            "execution_pattern": request.execution_pattern,
            "data_classification": request.data_classification,
            "storage_mode": request.storage_mode,
            "timeout_seconds": max(0, request.timeout_seconds),
            "retry_max": max(0, request.retry_max),
            "retention_ttl": max(0, request.retention_ttl),
            "result_contract": "cloud_batch_runtime_result.v1",
            "runtime_owner": "npcink-local-automation-runtime",
            "cloud_role": "runtime_detail",
            "final_writes": "core_proposal_required",
            "direct_wordpress_write": False,
            "task_backend": (
                policy.get("task_backend") if isinstance(policy.get("task_backend"), dict) else {}
            ),
        }
        return policy

    def _validate_image_source_contract(self, request: RuntimeRequest) -> None:
        try:
            validate_image_source_runtime_contract(
                ability_name=request.ability_name,
                contract_version=request.contract_version,
                input_payload=request.input_payload,
            )
        except ImageSourceContractViolation as error:
            raise RuntimeExecutionContractError(error.error_code, error.message) from error
        if request.ability_name not in IMAGE_SOURCE_ABILITIES:
            raise RuntimeExecutionContractError(
                "image_source.unknown_ability",
                "image source ability_name is not supported",
            )
        if request.execution_pattern not in {"inline", "step_offload"}:
            raise RuntimeExecutionContractError(
                "image_source.inline_required",
                "image source currently supports inline-compatible execution only",
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

    def _validate_image_generation_contract(self, request: RuntimeRequest) -> None:
        try:
            validate_image_generation_runtime_contract(
                ability_name=request.ability_name,
                contract_version=request.contract_version,
                input_payload=request.input_payload,
            )
        except ImageGenerationContractViolation as error:
            raise RuntimeExecutionContractError(error.error_code, error.message) from error
        if request.ability_name not in IMAGE_GENERATION_ABILITIES:
            raise RuntimeExecutionContractError(
                "image_generation.unknown_ability",
                "image generation ability_name is not supported",
            )
        if request.execution_pattern not in {"inline", "whole_run_offload"}:
            raise RuntimeExecutionContractError(
                "image_generation.execution_pattern_invalid",
                "image generation supports inline or whole_run_offload execution",
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

    def _validate_media_batch_plan_contract(self, request: RuntimeRequest) -> None:
        try:
            validate_media_batch_plan_runtime_contract(
                ability_name=request.ability_name,
                contract_version=request.contract_version,
                input_payload=request.input_payload,
            )
        except MediaBatchPlanContractViolation as error:
            raise RuntimeExecutionContractError(error.error_code, error.message) from error
        if request.ability_name not in MEDIA_BATCH_PLAN_ABILITIES:
            raise RuntimeExecutionContractError(
                "media_batch_plan.unknown_ability",
                "media batch plan ability_name is not supported",
            )
        if request.execution_pattern != "inline":
            raise RuntimeExecutionContractError(
                "media_batch_plan.inline_required",
                "media batch plan currently supports inline execution only",
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

    def _build_media_batch_plan_policy(self, request: RuntimeRequest) -> dict[str, object]:
        policy = self._apply_runtime_controls(dict(request.policy), request)
        policy["allow_fallback"] = False
        policy["execution_contract"] = {
            "ability_name": request.ability_name,
            "contract_version": request.contract_version,
            "profile_id": request.profile_id or MEDIA_BATCH_PLAN_PROFILE_ID,
            "execution_pattern": request.execution_pattern,
            "data_classification": request.data_classification,
            "storage_mode": request.storage_mode,
            "timeout_seconds": max(0, request.timeout_seconds),
            "retry_max": max(0, request.retry_max),
            "retention_ttl": max(0, request.retention_ttl),
            "plan_contract": "media_derivative_batch_plan.v1",
            "final_writes": "core_proposal_required",
            "direct_wordpress_write": False,
        }
        return policy

    def _build_image_source_policy(self, request: RuntimeRequest) -> dict[str, object]:
        policy = self._apply_runtime_controls(dict(request.policy), request)
        policy["allow_fallback"] = False
        policy["execution_contract"] = {
            "ability_name": request.ability_name,
            "contract_version": request.contract_version,
            "profile_id": request.profile_id or IMAGE_SOURCE_PROFILE_ID,
            "execution_pattern": request.execution_pattern,
            "data_classification": request.data_classification,
            "storage_mode": request.storage_mode,
            "timeout_seconds": max(0, request.timeout_seconds),
            "retry_max": max(0, request.retry_max),
            "retention_ttl": max(0, request.retention_ttl),
            "provider_source": "cloud_managed",
            "candidate_contract": "image_candidate.v1",
            "final_writes": "core_proposal_required",
            "direct_wordpress_write": False,
        }
        return policy

    def _validate_web_search_contract(self, request: RuntimeRequest) -> None:
        try:
            validate_web_search_runtime_contract(
                ability_name=request.ability_name,
                contract_version=request.contract_version,
                input_payload=request.input_payload,
            )
        except WebSearchContractViolation as error:
            raise RuntimeExecutionContractError(error.error_code, error.message) from error
        if request.ability_name not in WEB_SEARCH_ABILITIES:
            raise RuntimeExecutionContractError(
                "web_search.unknown_ability",
                "web search ability_name is not supported",
            )
        if request.execution_pattern != "inline":
            raise RuntimeExecutionContractError(
                "web_search.inline_required",
                "web search currently supports inline execution only",
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

    def _build_web_search_policy(self, request: RuntimeRequest) -> dict[str, object]:
        policy = self._apply_runtime_controls(dict(request.policy), request)
        policy["allow_fallback"] = False
        policy["execution_contract"] = {
            "ability_name": request.ability_name,
            "contract_version": request.contract_version,
            "profile_id": request.profile_id,
            "execution_pattern": request.execution_pattern,
            "data_classification": request.data_classification,
            "storage_mode": request.storage_mode,
            "timeout_seconds": max(0, request.timeout_seconds),
            "retry_max": max(0, request.retry_max),
            "retention_ttl": max(0, request.retention_ttl),
            "provider_source": "cloud_managed",
        }
        return policy

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
        updated["storage_mode"] = str(request.storage_mode or RUNTIME_STORAGE_MODE_RESULT_ONLY)
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
        if max_batch_items <= 0:
            return
        if requested_items > max_batch_items:
            raise RuntimeBatchLimitExceededError(
                feature_id=self._resolve_batch_feature_id(request),
                requested_items=requested_items,
                limit=max_batch_items,
            )

    def _resolve_batch_request_size(self, request: RuntimeRequest) -> int:
        feature_id = self._resolve_batch_feature_id(request)
        input_payload = request.input_payload if isinstance(request.input_payload, dict) else {}
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
        if feature_id == "nightly_site_inspection":
            items = input_payload.get("items")
            if isinstance(items, list):
                return len([item for item in items if isinstance(item, dict)])
            snapshot = input_payload.get("snapshot")
            if isinstance(snapshot, dict) and isinstance(snapshot.get("items"), list):
                return len([item for item in snapshot["items"] if isinstance(item, dict)])
            return 0
        return 0

    def _resolve_batch_feature_id(self, request: RuntimeRequest) -> str:
        workflow_id = str(request.workflow_id or "").strip()
        if workflow_id in {"media_alt_completion", "media_nightly_image_optimize"}:
            return workflow_id
        ability_name = str(request.ability_name or "").strip()
        if ability_name in CLOUD_BATCH_RUNTIME_ABILITIES:
            return "nightly_site_inspection"
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
            callback.get("secret") or metadata.get("runtime_terminal_callback_secret") or ""
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
                callback.get("key_id") or metadata.get("runtime_terminal_callback_key_id") or ""
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
                task_backend = self._dict_or_empty(policy.get("task_backend"))
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
            input_payload=run.input_payload if hasattr(run, "input_payload") else {},
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
        dispatcher = self.callback_dispatcher
        if dispatcher is None:
            return None
        try:
            result = dispatcher.dispatch(callback_request)
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
                current_time - timedelta(seconds=RUNTIME_DIAGNOSTIC_CALLBACK_OVERDUE_AFTER_SECONDS)
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
                    return None
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
                    "stale_after_seconds": (RUNTIME_CALLBACK_DISPATCH_LEASE_RECOVERY_AFTER_SECONDS),
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
                run.callback_last_error_code or RUNTIME_CALLBACK_DISPATCH_LEASE_RECOVERY_ERROR_CODE,
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

    def _dict_or_empty(self, value: object | None) -> dict[str, object]:
        return value if isinstance(value, dict) else {}

    def _list_or_empty(self, value: object | None) -> list[object]:
        return value if isinstance(value, list) else []
