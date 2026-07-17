from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.exc import StatementError

from app.core.config import Settings
from app.core.db import dispose_engine, init_schema
from app.domain.catalog.service import CatalogService
from app.domain.commercial.service import CommercialService, ServiceAuditContext
from app.domain.media_artifacts.lifecycle import (
    MediaArtifactLifecycleError,
    MediaArtifactLifecycleService,
)
from app.workers import ops_cadence as ops_cadence_module
from app.workers.ops_cadence import build_cadence_summary, run_due_tasks


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'ops-cadence-worker.sqlite3'}"


def test_ops_cadence_worker_records_managed_task_audit_and_respects_intervals(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
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
        artifact_store_root=str(artifact_root),
        artifact_reconciliation_interval_seconds=60,
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
        "artifact_inventory_reconciliation",
        "payment_order_expiration",
    }
    assert all(item["outcome"] == "succeeded" for item in first_results)
    artifact_cleanup = next(
        item for item in first_results if item["task_id"] == "artifact_cleanup"
    )
    assert artifact_cleanup["payload"] == {
        "claimed": 0,
        "purged": 0,
        "retry_scheduled": 0,
        "stale_claims_reclaimed": 0,
        "superseded_finalizations": 0,
        "interval_seconds": 60,
    }
    artifact_reconciliation = next(
        item
        for item in first_results
        if item["task_id"] == "artifact_inventory_reconciliation"
    )
    assert artifact_reconciliation["payload"] == {
        "store_examined": 0,
        "referenced_present": 0,
        "orphan_observed": 0,
        "orphan_deferred": 0,
        "orphan_eligible": 0,
        "cleanup_candidates_eligible": 0,
        "db_available_examined": 0,
        "referenced_missing": 0,
        "pass_started": 1,
        "pass_busy": 0,
        "pass_completed": 1,
        "pass_abandoned": 0,
        "candidates_claimed": 0,
        "candidates_deleted": 0,
        "candidates_invalidated": 0,
        "retry_scheduled": 0,
        "stale_claims_reclaimed": 0,
        "superseded_finalizations": 0,
        "cleanup_fence_busy": 0,
        "deletion_enabled": False,
        "fixed_root_sessions_supported": True,
        "interval_seconds": 60,
    }
    assert (artifact_root / ".artifact-store-generation").exists() is False

    service = CommercialService(database_url, settings=settings)
    first_events = service.list_service_audit_events(limit=20)["items"]
    assert len(first_events) == 10
    cleanup_event = next(
        item for item in first_events if item["event_kind"] == "runtime.artifact_cleanup.cadence"
    )
    assert cleanup_event["payload"] == artifact_cleanup["payload"]
    reconciliation_event = next(
        item
        for item in first_events
        if item["event_kind"]
        == "runtime.artifact_inventory_reconciliation.cadence"
    )
    assert reconciliation_event["payload"] == artifact_reconciliation["payload"]

    latest_created_at = datetime.fromisoformat(
        str(first_events[0]["created_at"]).replace("Z", "+00:00")
    )
    second_results = run_due_tasks(settings, now=latest_created_at + timedelta(seconds=30))
    assert second_results == []

    third_results = run_due_tasks(settings, now=latest_created_at + timedelta(seconds=61))
    assert len(third_results) == 10
    assert {item["task_id"] for item in third_results} == {
        "retention_cleanup",
        "plugin_observability_cleanup",
        "usage_rollup",
        "router_diagnostics_summary",
        "latency_probe_summary",
        "alert_provider_degradation",
        "provider_health_scan",
        "artifact_cleanup",
        "artifact_inventory_reconciliation",
        "payment_order_expiration",
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
        "artifact_inventory_reconciliation",
        "payment_order_expiration",
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
        "artifact_inventory_reconciliation",
        "payment_order_expiration",
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


def test_artifact_cleanup_unexpected_delete_error_records_stable_cadence_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token="i" * 32,
        artifact_cleanup_interval_seconds=60,
    )

    def fail_cleanup(
        _service: MediaArtifactLifecycleService,
        **_kwargs: object,
    ) -> dict[str, int]:
        raise MediaArtifactLifecycleError() from None

    monkeypatch.setattr(
        MediaArtifactLifecycleService,
        "cleanup_expired_artifacts",
        fail_cleanup,
    )
    monkeypatch.setattr(
        ops_cadence_module,
        "cadence_task_specs",
        lambda: [
            ops_cadence_module.CadenceTaskSpec(
                task_id="artifact_cleanup",
                event_kind="runtime.artifact_cleanup.cadence",
                interval_seconds=lambda _settings: 60,
                runner=ops_cadence_module._run_artifact_cleanup,
            )
        ],
    )

    results = run_due_tasks(settings, now=datetime(2026, 7, 15, 19, 0, tzinfo=UTC))

    assert results == [
        {
            "task_id": "artifact_cleanup",
            "event_kind": "runtime.artifact_cleanup.cadence",
            "outcome": "error",
            "payload": {
                "interval_seconds": 60,
                "message": "media artifact lifecycle cleanup failed",
                "error_code": "ops.cadence_task_failed",
            },
        }
    ]
    dispose_engine(database_url)


def test_artifact_cleanup_claim_database_error_never_reaches_cadence_payload_or_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token="i" * 32,
        artifact_cleanup_interval_seconds=60,
    )
    private_statement = "SELECT purge_claim_id FROM media_artifacts WHERE storage_key=:key"
    private_storage_key = "private/object/cadence-claim.png"

    def fail_claim(
        _service: MediaArtifactLifecycleService,
        **_kwargs: object,
    ) -> tuple[list[object], int]:
        raise StatementError(
            "private cadence claim failure",
            private_statement,
            {"key": private_storage_key},
            RuntimeError("private database driver detail"),
        )

    monkeypatch.setattr(MediaArtifactLifecycleService, "_claim_batch", fail_claim)
    monkeypatch.setattr(
        ops_cadence_module,
        "cadence_task_specs",
        lambda: [
            ops_cadence_module.CadenceTaskSpec(
                task_id="artifact_cleanup",
                event_kind="runtime.artifact_cleanup.cadence",
                interval_seconds=lambda _settings: 60,
                runner=ops_cadence_module._run_artifact_cleanup,
            )
        ],
    )
    caplog.set_level("ERROR", logger="npcink_ai_cloud.ops_cadence")

    results = run_due_tasks(settings, now=datetime(2026, 7, 15, 19, 1, tzinfo=UTC))

    assert results[0]["payload"] == {
        "interval_seconds": 60,
        "message": "media artifact lifecycle cleanup failed",
        "error_code": "ops.cadence_task_failed",
    }
    observed = f"{results!r}\n{caplog.text}"
    assert private_statement not in observed
    assert private_storage_key not in observed
    assert "private database driver detail" not in observed
    dispose_engine(database_url)


def test_artifact_reconciliation_error_is_independent_stable_and_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token="i" * 32,
        artifact_reconciliation_interval_seconds=60,
    )
    private_path = "/private/customer/artifact.png"

    class FailingInventoryStore:
        chunk_size = 4096

        def list_objects(self, **_kwargs: object) -> object:
            raise StatementError(
                "private inventory query failed",
                private_path,
                {"path": private_path},
                RuntimeError("private inventory driver detail"),
            )

        def contains(self, storage_key: str) -> bool:
            raise AssertionError(storage_key)

    import app.domain.media_artifacts as media_artifacts_module

    monkeypatch.setattr(
        media_artifacts_module,
        "build_artifact_store",
        lambda _settings: FailingInventoryStore(),
    )
    monkeypatch.setattr(
        ops_cadence_module,
        "cadence_task_specs",
        lambda: [
            ops_cadence_module.CadenceTaskSpec(
                task_id="artifact_inventory_reconciliation",
                event_kind="runtime.artifact_inventory_reconciliation.cadence",
                interval_seconds=lambda _settings: 60,
                runner=ops_cadence_module._run_artifact_inventory_reconciliation,
            )
        ],
    )
    caplog.set_level("ERROR", logger="npcink_ai_cloud.ops_cadence")

    results = run_due_tasks(settings, now=datetime(2026, 7, 15, 19, 2, tzinfo=UTC))

    assert results == [
        {
            "task_id": "artifact_inventory_reconciliation",
            "event_kind": "runtime.artifact_inventory_reconciliation.cadence",
            "outcome": "error",
            "payload": {
                "interval_seconds": 60,
                "message": "media artifact orphan reconciliation failed",
                "error_code": "ops.cadence_task_failed",
            },
        }
    ]
    observed = f"{results!r}\n{caplog.text}"
    assert private_path not in observed
    dispose_engine(database_url)


def test_artifact_reconciliation_store_construction_error_is_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    private_root = tmp_path / "private-customer-artifact-root"
    private_root.symlink_to(private_root, target_is_directory=True)
    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token="i" * 32,
        artifact_store_root=str(private_root),
        artifact_reconciliation_interval_seconds=60,
    )
    monkeypatch.setattr(
        ops_cadence_module,
        "cadence_task_specs",
        lambda: [
            ops_cadence_module.CadenceTaskSpec(
                task_id="artifact_inventory_reconciliation",
                event_kind="runtime.artifact_inventory_reconciliation.cadence",
                interval_seconds=lambda _settings: 60,
                runner=ops_cadence_module._run_artifact_inventory_reconciliation,
            )
        ],
    )
    caplog.set_level("ERROR", logger="npcink_ai_cloud.ops_cadence")

    results = run_due_tasks(settings, now=datetime(2026, 7, 15, 19, 3, tzinfo=UTC))

    assert results[0]["payload"] == {
        "interval_seconds": 60,
        "message": "media artifact orphan reconciliation failed",
        "error_code": "ops.cadence_task_failed",
    }
    observed = f"{results!r}\n{caplog.text}"
    assert str(private_root) not in observed
    dispose_engine(database_url)
