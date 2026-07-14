from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from app.core.models import ProviderCallRecord, RunRecord
from app.domain.cloud_batch_runtime.contracts import (
    CLOUD_BATCH_RUNTIME_CLOUD_ABILITY,
)
from app.domain.runtime.run_projection import RuntimeRunProjector

NOW = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
EXPIRED_RETENTION_AT = datetime(2000, 1, 1, tzinfo=UTC)
RETAINED_UNTIL = datetime(2999, 1, 1, tzinfo=UTC)


def _run(status: str, **overrides: Any) -> RunRecord:
    terminal = status in {"succeeded", "failed", "canceled"}
    values: dict[str, Any] = {
        "run_id": f"run_{status}",
        "site_id": "site_alpha",
        "account_id": "acct_alpha",
        "subscription_id": "sub_alpha",
        "plan_version_id": "plan-v1",
        "ability_name": "npcink/test-runtime",
        "ability_family": "text",
        "skill_id": "skill_alpha",
        "workflow_id": "workflow_alpha",
        "contract_version": "runtime-test.v1",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "whole_run_offload",
        "data_classification": "internal",
        "profile_id": "text.balanced",
        "canonical_run_id": None,
        "status": status,
        "idempotency_key": f"idem_{status}",
        "request_fingerprint": f"fingerprint_{status}",
        "trace_id": f"trace_{status}",
        "cancel_requested_at": None,
        "canceled_at": NOW if status == "canceled" else None,
        "input_json": {},
        "execution_input_ciphertext": None,
        "policy_json": {
            "storage_mode": "result_only",
            "task_backend": {
                "enabled": True,
                "mode": "queue",
                "callback_mode": "polling_preferred",
                "polling_interval_sec": 3,
            },
            "runtime_callback": {"url": "https://callback.example.test/runtime"},
            "timeout_seconds": 30,
            "retry_max": 1,
            "max_retries": 1,
            "retention_ttl": 3600,
        },
        "result_ref": "inline",
        "result_json": {},
        "error_code": "runtime.execute_failed" if status == "failed" else None,
        "error_message": "runtime failed" if status == "failed" else None,
        "callback_status": "not_requested",
        "callback_attempt_count": 0,
        "callback_last_attempt_at": None,
        "callback_delivered_at": None,
        "callback_next_attempt_at": None,
        "callback_last_error_code": None,
        "callback_last_error_message": None,
        "selected_provider_id": "openai",
        "selected_model_id": "gpt-test",
        "selected_instance_id": "openai:gpt-test",
        "fallback_used": False,
        "started_at": NOW - timedelta(minutes=2),
        "processing_started_at": (
            NOW - timedelta(minutes=1) if status != "queued" else None
        ),
        "finished_at": NOW if terminal else None,
        "retention_expires_at": RETAINED_UNTIL if terminal else None,
        "result_purged_at": None,
    }
    values.update(overrides)
    return RunRecord(**values)


def _provider_call(*, retry_count: int, error_code: str | None) -> ProviderCallRecord:
    return ProviderCallRecord(
        run_id="run_failed",
        provider_id="openai",
        model_id="gpt-test",
        instance_id="openai:gpt-test",
        region="global",
        latency_ms=30_000,
        tokens_in=10,
        tokens_out=0,
        cost=0.0,
        retry_count=retry_count,
        fallback_used=False,
        error_code=error_code,
        created_at=NOW,
    )


@pytest.mark.parametrize(
    ("status", "phase", "terminal_status", "next_action", "backend_status"),
    [
        ("queued", "queued", "", "poll_run_status", "queued"),
        ("running", "processing", "", "wait_for_terminal_result", "running"),
        ("succeeded", "terminal", "succeeded", "review_result", "completed"),
        (
            "failed",
            "terminal",
            "failed",
            "inspect_runtime_failure_detail",
            "failed",
        ),
        (
            "canceled",
            "terminal",
            "canceled",
            "resubmit_if_operator_still_needs_result",
            "canceled",
        ),
    ],
)
def test_run_projection_covers_public_status_states(
    status: str,
    phase: str,
    terminal_status: str,
    next_action: str,
    backend_status: str,
) -> None:
    projector = RuntimeRunProjector()
    run = _run(status)

    lifecycle = projector.build_run_lifecycle(run)
    run_state = projector.build_run_state_payload(run, [])
    task_backend = projector.build_task_backend_payload(run)

    assert lifecycle["phase"] == phase
    assert lifecycle["terminal_status"] == terminal_status
    assert lifecycle["queue_mode"] == "queue_backed"
    assert run_state["phase"] == phase
    assert cast(dict[str, object], run_state["retry"])["operator_next_action"] == next_action
    assert task_backend["status"] == backend_status
    assert task_backend["callback_url"] == ""


def test_lifecycle_projects_callback_cancel_retention_and_task_backend() -> None:
    projector = RuntimeRunProjector()
    run = _run(
        "succeeded",
        callback_status="delivered",
        callback_attempt_count=2,
        callback_last_attempt_at=NOW - timedelta(seconds=5),
        callback_delivered_at=NOW,
    )

    lifecycle = projector.build_run_lifecycle(run)
    task_backend = projector.build_task_backend_payload(run)

    assert lifecycle["cancel"] == {
        "supported": True,
        "state": "closed",
        "requested_at": None,
        "canceled_at": None,
    }
    assert lifecycle["callback"] == {
        "requested": True,
        "mode": "polling_preferred",
        "url_present": True,
        "dispatch_status": "delivered",
        "attempt_count": 2,
        "last_attempt_at": (NOW - timedelta(seconds=5)).isoformat(),
        "delivered_at": NOW.isoformat(),
        "next_attempt_at": None,
        "last_error_code": "",
    }
    assert lifecycle["retention"] == {
        "ttl_seconds": 3600,
        "expires_at": RETAINED_UNTIL.isoformat(),
        "state": "retained",
        "result_purged_at": None,
    }
    assert task_backend == {
        "enabled": True,
        "mode": "queue",
        "callback_mode": "polling_preferred",
        "polling_interval_sec": 3,
        "callback_url": "",
        "timeout_seconds": 30,
        "retry_max": 1,
        "retention_ttl": 3600,
        "status": "completed",
    }


def test_failure_projection_marks_retry_exhaustion_and_cloud_batch_retry_source() -> None:
    projector = RuntimeRunProjector()
    run = _run(
        "failed",
        ability_name=CLOUD_BATCH_RUNTIME_CLOUD_ABILITY,
        error_code="provider.timeout",
        result_json={
            "execution_state": {
                "partial_success": True,
                "retry": {
                    "retryable": True,
                    "failed_action_ids": ["action_1"],
                },
            }
        },
    )
    provider_calls = [_provider_call(retry_count=1, error_code="provider.timeout")]

    failure = projector.build_failure_details(run, provider_calls)
    run_state = projector.build_run_state_payload(run, provider_calls)

    assert failure.error_stage == "provider"
    assert failure.retryable is True
    assert failure.retry_exhausted is True
    assert run_state["partial_success"] is True
    assert run_state["retry"] == {
        "retryable": True,
        "retry_owner": "cloud_runtime",
        "retry_exhausted": True,
        "failed_action_ids": ["action_1"],
        "operator_next_action": "retry_failed_cloud_analysis",
        "resubmit_requires_new_idempotency_key": True,
        "retry_source": "resubmit_runtime_execute_payload",
    }
    assert cast(dict[str, object], run_state["error"])["provider_error_code"] == (
        "provider.timeout"
    )


def test_planned_lifecycle_projects_queue_callback_cancel_and_retention() -> None:
    projector = RuntimeRunProjector()
    policy: dict[str, object] = {
        "task_backend": {
            "enabled": True,
            "mode": "queue",
            "callback_mode": "polling_preferred",
        },
        "runtime_callback": {"url": "https://callback.example.test/runtime"},
        "retention_ttl": 7200,
    }

    lifecycle = projector.build_planned_run_lifecycle(
        execution_pattern="whole_run_offload",
        policy=policy,
        initial_phase="queued",
    )

    assert lifecycle == {
        "phase": "requested",
        "next_phase": "queued",
        "queue_mode": "queue_backed",
        "cancel": {
            "supported": True,
            "state": "available",
            "requested_at": None,
            "canceled_at": None,
        },
        "callback": {
            "requested": True,
            "mode": "polling_preferred",
            "url_present": True,
            "dispatch_status": "pending_terminal",
            "attempt_count": 0,
            "last_attempt_at": None,
            "delivered_at": None,
            "next_attempt_at": None,
            "last_error_code": "",
        },
        "retention": {"ttl_seconds": 7200, "state": "pending_terminal"},
    }


def test_execution_context_timestamp_and_expiry_projection() -> None:
    projector = RuntimeRunProjector()
    naive_started_at = datetime(2026, 7, 14, 8, 0)
    run = _run(
        "succeeded",
        execution_pattern="step_offload",
        started_at=naive_started_at,
        retention_expires_at=EXPIRED_RETENTION_AT,
    )

    context = projector.build_execution_context_payload(run)

    assert context == {
        "skill_id": "skill_alpha",
        "workflow_id": "workflow_alpha",
        "contract_version": "runtime-test.v1",
        "ability_family": "text",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "data_classification": "internal",
        "storage_mode": "result_only",
    }
    assert projector.serialize_timestamp(naive_started_at) == "2026-07-14T08:00:00+00:00"
    assert projector.is_run_result_expired(run) is True
    run.result_purged_at = NOW
    run.retention_expires_at = RETAINED_UNTIL
    assert projector.is_run_result_expired(run) is True


def test_runtime_service_no_longer_defines_run_projection_details() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    service_path = repository_root / "app/domain/runtime/service.py"
    projection_path = repository_root / "app/domain/runtime/run_projection.py"
    service_tree = ast.parse(service_path.read_text(encoding="utf-8"))
    projection_tree = ast.parse(projection_path.read_text(encoding="utf-8"))
    service_class = next(
        node
        for node in service_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "RuntimeService"
    )
    projector_class = next(
        node
        for node in projection_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "RuntimeRunProjector"
    )
    service_methods = {
        node.name for node in service_class.body if isinstance(node, ast.FunctionDef)
    }
    projector_methods = {
        node.name for node in projector_class.body if isinstance(node, ast.FunctionDef)
    }
    moved_service_methods = {
        "_build_failure_details",
        "_public_execution_pattern",
        "_build_execution_context",
        "_build_execution_context_payload",
        "_build_task_backend_payload",
        "_build_task_backend_payload_from_policy",
        "_build_run_lifecycle",
        "_build_run_state_payload",
        "_resolve_run_state_next_action",
        "_build_planned_run_lifecycle",
        "_get_queue_mode",
        "_get_callback_mode",
        "_get_retention_state",
        "_is_run_result_expired",
        "_serialize_timestamp",
        "_normalize_timestamp",
        "_supports_public_cancel",
        "_resolve_cancel_state",
        "_resolve_callback_dispatch_status",
        "_get_callback_target",
        "_has_callback_target",
        "_is_task_backend_enabled",
    }
    imported_modules = {
        alias.name
        for node in ast.walk(projection_tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_modules.update(
        node.module
        for node in ast.walk(projection_tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )
    forbidden_import_prefixes = (
        "app.domain.runtime.service",
        "app.adapters.repositories",
        "app.core.db",
        "sqlalchemy.orm",
        "app.domain.commercial",
        "app.adapters.queue",
        "app.adapters.callbacks",
    )
    forbidden_transaction_calls = {
        node.func.attr
        for node in ast.walk(projection_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"commit", "rollback", "flush", "add", "delete"}
    }

    assert service_methods.isdisjoint(moved_service_methods)
    assert {
        "build_failure_details",
        "build_execution_context_payload",
        "build_task_backend_payload",
        "build_run_lifecycle",
        "build_run_state_payload",
        "build_planned_run_lifecycle",
        "is_run_result_expired",
    } <= projector_methods
    assert not {
        module
        for module in imported_modules
        if any(
            module == prefix or module.startswith(f"{prefix}.")
            for prefix in forbidden_import_prefixes
        )
    }
    assert forbidden_transaction_calls == set()
