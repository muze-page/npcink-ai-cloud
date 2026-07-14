from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from app.adapters.queue.base import RuntimeQueue, RuntimeQueueError
from app.adapters.repositories.runtime_repository import RuntimeRepository
from app.core.db import get_session
from app.core.error_taxonomy import get_error_taxonomy
from app.core.models import RunRecord
from app.domain.runtime.analysis_result import build_analysis_result_envelope
from app.domain.runtime.errors import (
    RuntimeCancelNotAllowedError,
    RuntimeIdempotencyConflictError,
    RuntimeResultExpiredError,
    RuntimeResultNotReadyError,
    RuntimeRunNotFoundError,
)
from app.domain.runtime.models import RuntimeRequest
from app.domain.runtime.run_projection import RuntimeRunProjector


class ClaimedRunExecutor(Protocol):
    def __call__(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class RuntimeRunCreationCommand:
    run_id: str
    site_id: str
    account_id: str | None
    subscription_id: str | None
    plan_version_id: str | None
    ability_name: str
    ability_family: str
    skill_id: str
    workflow_id: str
    contract_version: str
    channel: str
    execution_kind: str
    execution_tier: str
    execution_pattern: str
    data_classification: str
    profile_id: str
    canonical_run_id: str | None
    status: str
    idempotency_key: str | None
    request_fingerprint: str
    trace_id: str
    input_json: dict[str, Any]
    execution_input_ciphertext: str | None
    policy_json: dict[str, Any]
    selected_provider_id: str | None = None
    selected_model_id: str | None = None
    selected_instance_id: str | None = None


class RuntimeRunLifecycleService:
    """Owns durable run lookup, replay, queue claim, cancel, and retention lifecycle."""

    def __init__(
        self,
        *,
        database_url: str,
        runtime_queue: RuntimeQueue | None,
        run_projector: RuntimeRunProjector,
        claimed_run_executor: ClaimedRunExecutor,
        media_derivative_site_running_limit: int,
    ) -> None:
        self.database_url = database_url
        self.runtime_queue = runtime_queue
        self.run_projector = run_projector
        self.claimed_run_executor = claimed_run_executor
        self.media_derivative_site_running_limit = max(
            1,
            int(media_derivative_site_running_limit),
        )

    def create_durable_run(
        self,
        *,
        repository: RuntimeRepository,
        command: RuntimeRunCreationCommand,
    ) -> RunRecord:
        return repository.create_run(
            run_id=command.run_id,
            site_id=command.site_id,
            account_id=command.account_id,
            subscription_id=command.subscription_id,
            plan_version_id=command.plan_version_id,
            ability_name=command.ability_name,
            ability_family=command.ability_family,
            skill_id=command.skill_id,
            workflow_id=command.workflow_id,
            contract_version=command.contract_version,
            channel=command.channel,
            execution_kind=command.execution_kind,
            execution_tier=command.execution_tier,
            execution_pattern=command.execution_pattern,
            data_classification=command.data_classification,
            profile_id=command.profile_id,
            canonical_run_id=command.canonical_run_id,
            status=command.status,
            idempotency_key=command.idempotency_key,
            request_fingerprint=command.request_fingerprint,
            trace_id=command.trace_id,
            input_json=command.input_json,
            execution_input_ciphertext=command.execution_input_ciphertext,
            policy_json=command.policy_json,
            selected_provider_id=command.selected_provider_id,
            selected_model_id=command.selected_model_id,
            selected_instance_id=command.selected_instance_id,
        )

    def succeed_run(
        self,
        repository: RuntimeRepository,
        run: RunRecord,
        *,
        result_json: dict[str, Any],
        provider_id: str,
        model_id: str,
        instance_id: str,
        fallback_used: bool,
    ) -> RunRecord:
        return repository.mark_run_succeeded(
            run,
            result_json=result_json,
            provider_id=provider_id,
            model_id=model_id,
            instance_id=instance_id,
            fallback_used=fallback_used,
        )

    def fail_run(
        self,
        repository: RuntimeRepository,
        run: RunRecord,
        *,
        error_code: str,
        error_message: str,
        provider_id: str | None = None,
        model_id: str | None = None,
        instance_id: str | None = None,
        fallback_used: bool | None = None,
    ) -> RunRecord:
        return repository.mark_run_failed(
            run,
            error_code=error_code,
            error_message=error_message,
            provider_id=provider_id,
            model_id=model_id,
            instance_id=instance_id,
            fallback_used=fallback_used,
        )

    def cancel_run_durably(
        self,
        *,
        repository: RuntimeRepository,
        run: RunRecord,
        now: datetime | None = None,
        message: str = "run canceled before execution completed",
    ) -> RunRecord:
        return repository.mark_run_canceled(run, now=now, message=message)

    def cancel_if_requested(
        self,
        *,
        repository: RuntimeRepository,
        run: RunRecord,
    ) -> bool:
        repository.refresh_run(run)
        if run.cancel_requested_at is None or run.status != "running":
            return False
        self.cancel_run_durably(repository=repository, run=run)
        return True

    def build_request_fingerprint(
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

    def build_media_derivative_request_fingerprint(
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

    def get_idempotent_replay(
        self,
        *,
        repository: RuntimeRepository,
        site_id: str,
        idempotency_key: str | None,
        request_fingerprint: str,
    ) -> RunRecord | None:
        if not idempotency_key:
            return None
        existing = repository.get_run_by_idempotency(site_id, idempotency_key)
        if existing is None:
            return None
        if existing.request_fingerprint != request_fingerprint:
            raise RuntimeIdempotencyConflictError(site_id, idempotency_key)
        return existing

    def publish_queue_signal(self, run_id: str) -> None:
        if self.runtime_queue is None:
            return
        try:
            self.runtime_queue.publish(run_id)
        except RuntimeQueueError:
            # Durable run_records remain worker truth; a wake-up failure is recoverable
            # through the database polling fallback.
            return

    def process_next_queued_run(
        self,
        *,
        timeout_seconds: int = 1,
    ) -> dict[str, object] | None:
        processed = self.process_queued_runs(
            max_runs=1,
            timeout_seconds=timeout_seconds,
        )
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
            result = self._process_single_queued_run(
                timeout_seconds=remaining_timeout,
            )
            if result is None:
                break
            processed.append(result)
            # Only the first dequeue should block; then drain durable queued work.
            remaining_timeout = 0

        return processed

    def get_run(self, run_id: str, *, site_id: str | None = None) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            run = self._get_site_scoped_run(
                repository,
                run_id=run_id,
                site_id=site_id,
            )
            provider_calls = repository.list_provider_calls(run_id)
            failure_details = self.run_projector.build_failure_details(
                run,
                provider_calls,
            )

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
            "execution_pattern": self.run_projector.public_execution_pattern(run.execution_pattern),
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
            "started_at": self.run_projector.serialize_timestamp(run.started_at),
            "finished_at": self.run_projector.serialize_timestamp(run.finished_at),
            "provider_call_count": len(provider_calls),
            "task_backend": self.run_projector.build_task_backend_payload(run),
            "run_lifecycle": self.run_projector.build_run_lifecycle(run),
        }

    def get_run_result(
        self,
        run_id: str,
        *,
        site_id: str | None = None,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            run = self._get_site_scoped_run(
                repository,
                run_id=run_id,
                site_id=site_id,
            )
            if self.run_projector.is_run_result_expired(run):
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
            "execution_context": self.run_projector.build_execution_context_payload(run),
            "task_backend": self.run_projector.build_task_backend_payload(run),
            "run_lifecycle": self.run_projector.build_run_lifecycle(run),
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

    def cancel_run(self, run_id: str, *, site_id: str | None = None) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            run = self._get_site_scoped_run(
                repository,
                run_id=run_id,
                site_id=site_id,
            )
            policy = run.policy_json if isinstance(run.policy_json, dict) else {}
            if not self.run_projector.supports_public_cancel(
                run.execution_pattern,
                policy,
            ):
                raise RuntimeCancelNotAllowedError(run_id, run.status)

            if run.status == "queued":
                self.cancel_run_durably(
                    repository=repository,
                    run=run,
                    message="run canceled before worker claim",
                )
            elif run.status == "running":
                repository.request_run_cancel(run)
            elif run.status == "canceled":
                pass
            else:
                raise RuntimeCancelNotAllowedError(run_id, run.status)

            session.commit()

        return self.get_run(run_id, site_id=site_id)

    def cleanup_expired_run_results(self, *, now: datetime | None = None) -> int:
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            purged = repository.purge_expired_run_results(now=now)
            session.commit()
            return purged

    def _process_single_queued_run(
        self,
        *,
        timeout_seconds: int,
    ) -> dict[str, object] | None:
        signaled_run_id = self._consume_queue_signal(timeout_seconds)

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            run: RunRecord | None = None
            if signaled_run_id:
                candidate = repository.get_run(signaled_run_id)
                if (
                    candidate is not None
                    and candidate.execution_kind == "media_derivative"
                    and repository.count_running_media_derivative_runs(candidate.site_id)
                    >= self.media_derivative_site_running_limit
                ):
                    run = None
                else:
                    run = repository.claim_run_if_queued(signaled_run_id)

            if run is None:
                run = repository.claim_next_queued_run(
                    media_derivative_site_running_limit=(self.media_derivative_site_running_limit),
                )

            if run is None:
                session.commit()
                return None

            self.claimed_run_executor(run, repository=repository)
            session.commit()
            return {
                "run_id": run.run_id,
                "status": run.status,
                "trace_id": run.trace_id,
            }

    def _consume_queue_signal(self, timeout_seconds: int) -> str | None:
        if self.runtime_queue is None:
            return None
        try:
            return self.runtime_queue.consume(timeout_seconds)
        except RuntimeQueueError:
            return None

    @staticmethod
    def _get_site_scoped_run(
        repository: RuntimeRepository,
        *,
        run_id: str,
        site_id: str | None,
    ) -> RunRecord:
        run = repository.get_run(run_id)
        if run is None or (site_id and run.site_id != site_id):
            raise RuntimeRunNotFoundError(run_id)
        return run
