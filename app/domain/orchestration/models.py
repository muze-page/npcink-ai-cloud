from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ALLOWED_ORCHESTRATION_STATUS = frozenset(
    {"queued", "running", "succeeded", "failed", "canceled"}
)

ALLOWED_STEP_STATUS = frozenset(
    {"pending", "running", "succeeded", "failed", "skipped"}
)

ORCHESTRATION_MAX_DURATION_DEFAULT = 3600
ORCHESTRATION_MAX_STEPS_DEFAULT = 50
ORCHESTRATION_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS = 300
ORCHESTRATION_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS = 900

ALLOWED_WHEN_OPERATORS = frozenset(
    {
        "always",
        "never",
        "truthy",
        "falsy",
        "exists",
        "not_exists",
        "eq",
        "neq",
        "empty",
        "not_empty",
    }
)

COMPLEX_WHEN_OPERATORS = frozenset({"any", "all", "in", "not_in"})

REF_PATH_PREFIXES = frozenset({"$input", "$steps"})


@dataclass(slots=True)
class OrchestrationStepDefinition:
    step_id: str
    ability_name: str
    input_map: dict[str, Any] = field(default_factory=dict)
    when: dict[str, Any] | None = None
    retry: int = 0
    timeout: int = 60
    foreach: str | None = None


@dataclass(slots=True)
class OrchestrationSubmission:
    workflow_id: str
    workflow_version: int
    steps: list[OrchestrationStepDefinition]
    initial_input: dict[str, Any]
    callback_url: str = ""
    max_duration_seconds: int = ORCHESTRATION_MAX_DURATION_DEFAULT
    idempotency_key: str | None = None
    trace_id: str | None = None


@dataclass(slots=True)
class OrchestrationResult:
    orchestration_run_id: str
    status: str
    workflow_id: str
    workflow_version: int
    submitted_at: str
    completed_at: str | None = None
    callback_url: str = ""
    result_summary: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    failed_step_index: int | None = None
    step_count: int = 0
    succeeded_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0


@dataclass(slots=True)
class StepResult:
    step_id: str
    step_index: int
    ability_name: str
    status: str
    input_payload: dict[str, Any] | None = None
    step_output: dict[str, Any] | None = None
    started_at: str | None = None
    completed_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retry_count: int = 0
    max_retries: int = 0
    timeout_seconds: int = 60
    foreach_iteration_count: int | None = None
