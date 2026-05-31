from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ALLOWED_RUNTIME_REQUEST_POLICY_KEYS = frozenset({"allow_fallback"})
ALLOWED_RUNTIME_TASK_BACKEND_KEYS = frozenset(
    {
        "enabled",
        "mode",
        "callback_mode",
        "polling_interval_sec",
    }
)
BLOCKED_RUNTIME_GOVERNANCE_POLICY_KEYS = frozenset(
    {
        "requires_confirm",
        "required_scope",
        "required_scopes",
        "tool_policy",
        "approval_policy",
        "apply_policy",
        "final_write_policy",
        "final_write_target",
        "wordpress_write_policy",
        "wordpress_write_target",
        "write_control",
        "write_controls",
    }
)
RUNTIME_DIAGNOSTIC_ISSUE_KINDS = frozenset(
    {
        "queued",
        "queued_stale",
        "running",
        "running_stale",
        "cancel_requested",
        "cancel_stuck",
        "callback_due",
        "callback_overdue",
        "callback_failed",
        "callback_dispatching",
        "canceled_recent",
        "retention_due",
    }
)
RUNTIME_DIAGNOSTIC_ISSUE_KIND_PATTERN = "^(" + "|".join(sorted(RUNTIME_DIAGNOSTIC_ISSUE_KINDS)) + ")$"
RUNTIME_BACKLOG_SCOPE_KINDS = frozenset({"site_id", "ability_family", "execution_pattern"})
RUNTIME_BACKLOG_SCOPE_KIND_PATTERN = (
    "^(" + "|".join(sorted(RUNTIME_BACKLOG_SCOPE_KINDS)) + ")$"
)
RUNTIME_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS = 300
RUNTIME_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS = 900
RUNTIME_DIAGNOSTIC_CANCEL_STUCK_AFTER_SECONDS = 300
RUNTIME_DIAGNOSTIC_CALLBACK_OVERDUE_AFTER_SECONDS = 300
RUNTIME_DIAGNOSTIC_CALLBACK_DISPATCHING_STALE_AFTER_SECONDS = 300
RUNTIME_BACKLOG_QUEUED_AGING_AFTER_SECONDS = (
    RUNTIME_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS // 2
)
RUNTIME_BACKLOG_RUNNING_AGING_AFTER_SECONDS = (
    RUNTIME_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS // 2
)
RUNTIME_CALLBACK_DISPATCH_LEASE_RECOVERY_AFTER_SECONDS = (
    RUNTIME_DIAGNOSTIC_CALLBACK_DISPATCHING_STALE_AFTER_SECONDS
)
RUNTIME_CALLBACK_DISPATCH_LEASE_RECOVERY_ERROR_CODE = (
    "runtime.callback_dispatch_lease_recovered"
)
ABUSE_GUARD_ATTENTION_RATIO = 0.8
ABUSE_GUARD_CRITICAL_RATIO = 1.0
RUNTIME_STORAGE_MODE_NO_STORE = "no_store"
RUNTIME_STORAGE_MODE_RESULT_ONLY = "result_only"
RUNTIME_STORAGE_MODE_FULL_STORE_WITH_TTL = "full_store_with_ttl"
RUNTIME_STORAGE_MODES = frozenset(
    {
        RUNTIME_STORAGE_MODE_NO_STORE,
        RUNTIME_STORAGE_MODE_RESULT_ONLY,
        RUNTIME_STORAGE_MODE_FULL_STORE_WITH_TTL,
    }
)
RUNTIME_CALLBACK_MODES = frozenset(
    {
        "",
        "polling_only",
        "polling_preferred",
        "terminal_callback_required",
    }
)
RUNTIME_MAX_TIMEOUT_SECONDS = 3600
RUNTIME_MAX_RETRY_MAX = 5
RUNTIME_MAX_RETENTION_TTL = 604800
RUNTIME_CALLBACK_EVENT = "runtime.run.terminal"
RUNTIME_PUBLIC_EXECUTION_PATTERNS = frozenset({"inline", "whole_run_offload"})


def normalize_runtime_request_policy(policy: dict[str, Any] | None) -> dict[str, object]:
    raw_policy = policy if isinstance(policy, dict) else {}
    normalized: dict[str, object] = {}

    for key in ALLOWED_RUNTIME_REQUEST_POLICY_KEYS:
        if key == "allow_fallback" and key in raw_policy:
            normalized[key] = bool(raw_policy.get(key))

    return normalized


def normalize_runtime_task_backend(task_backend: dict[str, Any] | None) -> dict[str, object]:
    raw_task_backend = task_backend if isinstance(task_backend, dict) else {}
    normalized: dict[str, object] = {}

    if "enabled" in raw_task_backend:
        normalized["enabled"] = bool(raw_task_backend.get("enabled"))
    if "mode" in raw_task_backend:
        normalized["mode"] = str(raw_task_backend.get("mode") or "")
    if "callback_mode" in raw_task_backend:
        normalized["callback_mode"] = str(raw_task_backend.get("callback_mode") or "")
    if "polling_interval_sec" in raw_task_backend:
        value = raw_task_backend.get("polling_interval_sec")
        try:
            normalized["polling_interval_sec"] = max(0, int(value or 0))
        except (TypeError, ValueError):
            normalized["polling_interval_sec"] = 0

    return {
        key: value
        for key, value in normalized.items()
        if key in ALLOWED_RUNTIME_TASK_BACKEND_KEYS
    }


@dataclass(slots=True)
class RuntimeFailureDetails:
    error_stage: str
    retryable: bool
    retry_exhausted: bool


@dataclass(slots=True)
class RuntimeRequest:
    site_id: str
    ability_name: str
    channel: str
    execution_kind: str
    profile_id: str
    input_payload: dict[str, Any]
    canonical_run_id: str = ""
    ability_family: str = "text"
    skill_id: str = ""
    workflow_id: str = ""
    contract_version: str = "v1"
    execution_tier: str = "cloud"
    execution_pattern: str = "inline"
    data_classification: str = "internal"
    storage_mode: str = RUNTIME_STORAGE_MODE_RESULT_ONLY
    timeout_seconds: int = 0
    retry_max: int = 0
    retention_ttl: int = 0
    callback_url: str = ""
    task_backend: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    trace_id: str | None = None
    allow_legacy_callback_url: bool = True

    def __post_init__(self) -> None:
        self.input_payload = self.input_payload if isinstance(self.input_payload, dict) else {}
        self.task_backend = normalize_runtime_task_backend(self.task_backend)
        self.policy = normalize_runtime_request_policy(self.policy)
        normalized_storage_mode = str(self.storage_mode or RUNTIME_STORAGE_MODE_RESULT_ONLY).strip()
        if normalized_storage_mode not in RUNTIME_STORAGE_MODES:
            normalized_storage_mode = RUNTIME_STORAGE_MODE_RESULT_ONLY
        self.storage_mode = normalized_storage_mode


@dataclass(slots=True)
class RuntimeExecutionContext:
    skill_id: str
    workflow_id: str
    contract_version: str
    ability_family: str
    execution_tier: str
    execution_pattern: str
    data_classification: str
    storage_mode: str


@dataclass(slots=True)
class RuntimeExecutionResponse:
    run_id: str
    canonical_run_id: str
    status: str
    trace_id: str
    profile_id: str
    provider_id: str
    model_id: str
    instance_id: str
    fallback_used: bool
    idempotent_replay: bool
    error_code: str
    error_message: str
    error_stage: str
    retryable: bool
    retry_exhausted: bool
    provider_call_count: int
    execution_context: RuntimeExecutionContext
    task_backend: dict[str, Any]
    run_lifecycle: dict[str, Any]
    result: dict[str, Any]
