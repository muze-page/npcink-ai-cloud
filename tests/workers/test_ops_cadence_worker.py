from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import Settings
from app.core.db import dispose_engine, init_schema
from app.domain.catalog.service import CatalogService
from app.domain.commercial.service import CommercialService, ServiceAuditContext
from app.workers.ops_cadence import build_cadence_summary, run_due_tasks


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'ops-cadence-worker.sqlite3'}"


def test_ops_cadence_worker_records_managed_task_audit_and_respects_intervals(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token="i" * 32,
        retention_cleanup_interval_seconds=60,
        plugin_observability_cleanup_interval_seconds=60,
        usage_rollup_interval_seconds=60,
        router_diagnostics_interval_seconds=60,
        latency_probe_interval_seconds=60,
        alert_provider_degradation_interval_seconds=60,
        provider_health_scan_interval_seconds=60,
        artifact_cleanup_interval_seconds=60,
    )

    first_now = datetime(2026, 4, 12, 12, 0, tzinfo=UTC)
    first_results = run_due_tasks(settings, now=first_now)

    assert {item["task_id"] for item in first_results} == {
        "retention_cleanup",
        "plugin_observability_cleanup",
        "usage_rollup",
        "router_diagnostics_summary",
        "latency_probe_summary",
        "alert_provider_degradation",
        "provider_health_scan",
        "artifact_cleanup",
    }
    assert all(item["outcome"] == "succeeded" for item in first_results)

    service = CommercialService(database_url, settings=settings)
    first_events = service.list_service_audit_events(limit=20)["items"]
    assert len(first_events) == 8

    latest_created_at = datetime.fromisoformat(
        str(first_events[0]["created_at"]).replace("Z", "+00:00")
    )
    second_results = run_due_tasks(settings, now=latest_created_at + timedelta(seconds=30))
    assert second_results == []

    third_results = run_due_tasks(settings, now=latest_created_at + timedelta(seconds=61))
    assert len(third_results) == 8
    assert {item["task_id"] for item in third_results} == {
        "retention_cleanup",
        "plugin_observability_cleanup",
        "usage_rollup",
        "router_diagnostics_summary",
        "latency_probe_summary",
        "alert_provider_degradation",
        "provider_health_scan",
        "artifact_cleanup",
    }

    fourth_results = run_due_tasks(settings, now=latest_created_at + timedelta(seconds=121))
    assert {item["task_id"] for item in fourth_results} == {
        "retention_cleanup",
        "plugin_observability_cleanup",
        "usage_rollup",
        "router_diagnostics_summary",
        "latency_probe_summary",
        "alert_provider_degradation",
        "provider_health_scan",
        "artifact_cleanup",
    }

    fifth_results = run_due_tasks(settings, now=latest_created_at + timedelta(seconds=301))
    assert {item["task_id"] for item in fifth_results} == {
        "retention_cleanup",
        "plugin_observability_cleanup",
        "usage_rollup",
        "router_diagnostics_summary",
        "latency_probe_summary",
        "alert_provider_degradation",
        "provider_health_scan",
        "artifact_cleanup",
    }

    dispose_engine(database_url)


def test_cadence_summary_hides_stale_error_details_after_newer_success(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token="i" * 32,
    )
    service = CommercialService(database_url, settings=settings)
    audit_context = ServiceAuditContext(
        trace_id="",
        idempotency_key="",
        method="POST",
        path="/internal/workers/ops-cadence/retention_cleanup",
        actor_kind="system_worker",
        actor_ref="ops_cadence",
    )
    service.record_service_audit_event(
        audit_context=audit_context,
        event_kind="runtime.retention_cleanup.cadence",
        outcome="error",
        scope_kind="ops_cadence",
        scope_id="retention_cleanup",
        payload_json={"message": "old error", "error_code": "ops.cadence_task_failed"},
    )
    service.record_service_audit_event(
        audit_context=audit_context,
        event_kind="runtime.retention_cleanup.cadence",
        outcome="succeeded",
        scope_kind="ops_cadence",
        scope_id="retention_cleanup",
        payload_json={"purged_runs": 1},
    )

    summary = build_cadence_summary(settings, now=datetime.now(UTC))
    item = next(
        candidate for candidate in summary["items"] if candidate["task_id"] == "retention_cleanup"
    )
    assert item["last_outcome"] == "succeeded"
    assert item["last_error_at"] == ""
    assert item["last_error_message"] == ""
    assert item["last_error_code"] == ""

    dispose_engine(database_url)
