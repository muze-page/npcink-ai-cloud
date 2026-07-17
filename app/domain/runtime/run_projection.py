from __future__ import annotations

from datetime import UTC, datetime

from app.core.error_taxonomy import get_error_taxonomy
from app.core.models import (
    RUN_CALLBACK_STATUS_DELIVERED,
    RUN_CALLBACK_STATUS_DISPATCHING,
    RUN_CALLBACK_STATUS_FAILED,
    RUN_CALLBACK_STATUS_NOT_REQUESTED,
    RUN_CALLBACK_STATUS_PENDING,
    ProviderCallRecord,
    RunRecord,
)
from app.domain.cloud_batch_runtime.contracts import CLOUD_BATCH_RUNTIME_ABILITIES
from app.domain.runtime.models import (
    RUNTIME_STORAGE_MODE_RESULT_ONLY,
    RuntimeExecutionContext,
    RuntimeFailureDetails,
)


class RuntimeRunProjector:
    """Stateless projection of durable run evidence into public runtime payloads."""

    def build_failure_details(
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

    def public_execution_pattern(self, execution_pattern: str) -> str:
        if execution_pattern == "whole_run_offload":
            return "whole_run_offload"
        return "inline"

    def build_execution_context(self, run: RunRecord) -> RuntimeExecutionContext:
        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
        return RuntimeExecutionContext(
            skill_id=run.skill_id or "",
            workflow_id=run.workflow_id or "",
            contract_version=run.contract_version or "",
            ability_family=run.ability_family or "text",
            execution_tier=run.execution_tier,
            execution_pattern=self.public_execution_pattern(run.execution_pattern),
            data_classification=run.data_classification,
            storage_mode=str(policy.get("storage_mode") or RUNTIME_STORAGE_MODE_RESULT_ONLY),
        )

    def build_execution_context_payload(self, run: RunRecord) -> dict[str, str]:
        context = self.build_execution_context(run)
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

    def build_task_backend_payload(self, run: RunRecord) -> dict[str, object]:
        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
        return self.build_task_backend_payload_from_policy(policy, run_status=run.status)

    def build_run_lifecycle(self, run: RunRecord) -> dict[str, object]:
        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
        phase_map = {
            "queued": "queued",
            "running": "processing",
            "succeeded": "terminal",
            "failed": "terminal",
            "canceled": "terminal",
        }
        callback_requested = self.has_callback_target(policy)
        retention_ttl = max(0, self._coerce_int(policy.get("retention_ttl"), default=0))
        terminal_status = run.status if run.status in {"succeeded", "failed", "canceled"} else ""
        cancel_supported = self.supports_public_cancel(run.execution_pattern, policy)

        return {
            "phase": phase_map.get(run.status, "requested"),
            "queue_mode": self.get_queue_mode(run.execution_pattern, policy),
            "requested_at": self.serialize_timestamp(run.started_at),
            "processing_started_at": self.serialize_timestamp(run.processing_started_at),
            "terminal_at": self.serialize_timestamp(run.finished_at),
            "terminal_status": terminal_status,
            "cancel": {
                "supported": cancel_supported,
                "state": self.resolve_cancel_state(run, supported=cancel_supported),
                "requested_at": self.serialize_timestamp(run.cancel_requested_at),
                "canceled_at": self.serialize_timestamp(run.canceled_at),
            },
            "callback": {
                "requested": callback_requested,
                "mode": self.get_callback_mode(policy),
                "url_present": callback_requested,
                "dispatch_status": self.resolve_callback_dispatch_status(
                    run,
                    callback_requested,
                ),
                "attempt_count": max(0, int(run.callback_attempt_count or 0)),
                "last_attempt_at": self.serialize_timestamp(run.callback_last_attempt_at),
                "delivered_at": self.serialize_timestamp(run.callback_delivered_at),
                "next_attempt_at": self.serialize_timestamp(run.callback_next_attempt_at),
                "last_error_code": run.callback_last_error_code or "",
            },
            "retention": {
                "ttl_seconds": retention_ttl,
                "expires_at": self.serialize_timestamp(run.retention_expires_at),
                "state": self.get_retention_state(run, retention_ttl),
                "result_purged_at": self.serialize_timestamp(run.result_purged_at),
            },
        }

    def build_run_state_payload(
        self,
        run: RunRecord,
        provider_calls: list[ProviderCallRecord],
    ) -> dict[str, object]:
        result = run.result_json if isinstance(run.result_json, dict) else {}
        result_state = result.get("execution_state")
        result_state = result_state if isinstance(result_state, dict) else {}
        lifecycle = self.build_run_lifecycle(run)
        failure_details = self.build_failure_details(run, provider_calls)
        failed_provider_call = next(
            (call for call in reversed(provider_calls) if call.error_code),
            None,
        )
        retryable = bool(
            result_state.get("retry", {}).get("retryable")
            if isinstance(result_state.get("retry"), dict)
            else failure_details.retryable
        )
        failed_action_ids: list[object] = []
        if isinstance(result_state.get("retry"), dict):
            raw_failed_action_ids = result_state["retry"].get("failed_action_ids")
            if isinstance(raw_failed_action_ids, list):
                failed_action_ids = raw_failed_action_ids[:10]

        return {
            "contract_version": "cloud_run_state.v1",
            "state_machine": "requested->queued->running->terminal",
            "phase": lifecycle.get("phase", "requested"),
            "status": run.status,
            "terminal_status": lifecycle.get("terminal_status", ""),
            "worker_phase": str(result.get("worker_phase") or ""),
            "partial_success": bool(result_state.get("partial_success")),
            "retry": {
                "retryable": retryable,
                "retry_owner": (
                    "cloud_runtime"
                    if retryable
                    else "not_needed"
                    if run.status == "succeeded"
                    else "operator_review"
                ),
                "retry_exhausted": failure_details.retry_exhausted,
                "failed_action_ids": failed_action_ids,
                "operator_next_action": self.resolve_run_state_next_action(
                    run,
                    retryable=retryable,
                    failed_action_ids=failed_action_ids,
                ),
                "resubmit_requires_new_idempotency_key": retryable,
                "retry_source": (
                    "resubmit_runtime_execute_payload"
                    if str(run.ability_name or "") in CLOUD_BATCH_RUNTIME_ABILITIES
                    else "runtime_specific"
                ),
            },
            "idempotency": {
                "idempotency_key": run.idempotency_key or "",
                "request_fingerprint": run.request_fingerprint or "",
                "replay_safe": bool(run.idempotency_key),
                "canonical_truth": "run_records",
            },
            "error": {
                "error_code": run.error_code or "",
                "error_message": run.error_message or "",
                "error_stage": failure_details.error_stage,
                "provider_error_code": failed_provider_call.error_code
                if failed_provider_call is not None
                else "",
            },
            "observability": {
                "trace_id": run.trace_id,
                "provider_call_count": len(provider_calls),
                "usage_meter_truth": "usage_meter_events",
                "run_record_truth": "run_records",
            },
            "boundary": {
                "cloud_role": "runtime_detail",
                "cloud_scheduler_truth": False,
                "direct_wordpress_write": False,
            },
        }

    def resolve_run_state_next_action(
        self,
        run: RunRecord,
        *,
        retryable: bool,
        failed_action_ids: list[object],
    ) -> str:
        if run.status == "queued":
            return "poll_run_status"
        if run.status == "running":
            return "wait_for_terminal_result"
        if retryable:
            return (
                "retry_failed_cloud_analysis"
                if failed_action_ids
                else "resubmit_runtime_request_with_new_idempotency_key"
            )
        if run.status == "failed":
            return "inspect_runtime_failure_detail"
        if run.status == "canceled":
            return "resubmit_if_operator_still_needs_result"
        return "review_result"

    def build_planned_run_lifecycle(
        self,
        *,
        execution_pattern: str,
        policy: dict[str, object],
        initial_phase: str,
    ) -> dict[str, object]:
        callback_requested = self.has_callback_target(policy)
        retention_ttl = max(0, self._coerce_int(policy.get("retention_ttl"), default=0))
        cancel_supported = self.supports_public_cancel(execution_pattern, policy)
        return {
            "phase": "requested",
            "next_phase": initial_phase,
            "queue_mode": self.get_queue_mode(execution_pattern, policy),
            "cancel": {
                "supported": cancel_supported,
                "state": "available" if cancel_supported else "not_available",
                "requested_at": None,
                "canceled_at": None,
            },
            "callback": {
                "requested": callback_requested,
                "mode": self.get_callback_mode(policy),
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

    def build_task_backend_payload_from_policy(
        self,
        policy: dict[str, object],
        *,
        run_status: str,
    ) -> dict[str, object]:
        raw_task_backend = policy.get("task_backend")
        raw_task_backend = raw_task_backend if isinstance(raw_task_backend, dict) else {}
        enabled = bool(raw_task_backend.get("enabled"))
        callback_target = self.get_callback_target(policy)
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
            "callback_url": "",
            "timeout_seconds": timeout_seconds,
            "retry_max": retry_max,
            "retention_ttl": retention_ttl,
            "status": status_map.get(run_status, "queued" if enabled else "disabled"),
        }

    def get_queue_mode(self, execution_pattern: str, policy: dict[str, object]) -> str:
        if execution_pattern == "whole_run_offload" and self.is_task_backend_enabled(policy):
            return "queue_backed"
        return "inline"

    def get_callback_mode(self, policy: dict[str, object]) -> str:
        task_backend = policy.get("task_backend")
        if isinstance(task_backend, dict):
            return str(task_backend.get("callback_mode") or "")
        return ""

    def get_retention_state(self, run: RunRecord, retention_ttl: int) -> str:
        if retention_ttl <= 0:
            return "disabled"
        if run.finished_at is None:
            return "pending_terminal"
        if self.is_run_result_expired(run):
            return "expired"
        return "retained"

    def is_run_result_expired(self, run: RunRecord) -> bool:
        if run.result_purged_at is not None:
            return True
        if run.retention_expires_at is None:
            return False
        retention_expires_at = self.normalize_timestamp(run.retention_expires_at)
        return retention_expires_at <= datetime.now(UTC)

    def supports_public_cancel(
        self,
        execution_pattern: str,
        policy: dict[str, object],
    ) -> bool:
        return self.get_queue_mode(execution_pattern, policy) == "queue_backed"

    def resolve_cancel_state(self, run: RunRecord, *, supported: bool) -> str:
        if not supported:
            return "not_available"
        if run.status == "canceled":
            return "canceled"
        if run.finished_at is not None:
            return "closed"
        if run.cancel_requested_at is not None:
            return "requested"
        return "available"

    def resolve_callback_dispatch_status(
        self,
        run: RunRecord,
        callback_requested: bool,
    ) -> str:
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

    def get_callback_target(self, policy: dict[str, object]) -> dict[str, object]:
        runtime_callback = policy.get("runtime_callback")
        return runtime_callback if isinstance(runtime_callback, dict) else {}

    def has_callback_target(self, policy: dict[str, object]) -> bool:
        return bool(self.get_callback_target(policy))

    def is_task_backend_enabled(self, policy: dict[str, object]) -> bool:
        task_backend = policy.get("task_backend")
        return isinstance(task_backend, dict) and bool(task_backend.get("enabled"))

    def serialize_timestamp(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return self.normalize_timestamp(value).isoformat()

    def normalize_timestamp(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _coerce_int(value: object | None, *, default: int) -> int:
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
