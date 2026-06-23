from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.adapters.repositories.stats_repository import StatsRepository
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import SITE_STATUS_SUSPENDED, HealthSnapshot, ProviderCallRecord, RunRecord
from app.domain.catalog.service import CatalogService
from app.domain.runtime.models import RuntimeRequest
from app.domain.runtime.service import RuntimeService
from app.domain.usage.rollup import ALERT_EVALUATE_BATCH_SCOPE
from app.workers.alert_provider_degradation import run_once
from tests.conftest import seed_site_auth


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'alert-worker.sqlite3'}"


def test_alert_worker_generates_active_provider_degradation_batches(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    CatalogService(database_url).scan_provider_health()
    seed_site_auth(database_url, site_id="site_alpha", scopes=["stats:read"])
    seed_site_auth(
        database_url,
        site_id="site_suspended",
        scopes=["stats:read"],
        site_status=SITE_STATUS_SUSPENDED,
    )

    runtime_service = RuntimeService(database_url)
    result = runtime_service.execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="worker-alert-provider-a",
            trace_id="worker-alert-provider-a",
            input_payload={"messages": [{"role": "user", "content": "worker batch"}]},
        )
    )

    fixed_now = datetime(2026, 3, 24, 9, 20, tzinfo=UTC)
    with get_session(database_url) as session:
        run = session.scalar(select(RunRecord).where(RunRecord.run_id == result.run_id))
        assert run is not None
        run.started_at = fixed_now - timedelta(minutes=10)
        run.finished_at = fixed_now - timedelta(minutes=10) + timedelta(milliseconds=25000)

        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord)
                .where(ProviderCallRecord.run_id == result.run_id)
                .order_by(ProviderCallRecord.id.asc())
            )
        )
        assert provider_calls
        primary_call = provider_calls[0]
        primary_call.created_at = fixed_now - timedelta(minutes=5)
        primary_call.latency_ms = 25000
        primary_call.error_code = "provider.timeout"

        session.add(
            HealthSnapshot(
                provider_id=primary_call.provider_id,
                instance_id=primary_call.instance_id,
                status="degraded",
                reason="worker smoke",
                measured_at=fixed_now - timedelta(minutes=2),
            )
        )
        session.commit()
        provider_id = primary_call.provider_id

    summary = run_once(
        Settings(
            project_name="Npcink AI Cloud Test",
            environment="test",
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
            alert_worker_window_minutes=30,
            alert_worker_site_limit=10,
            alert_worker_min_requests=1,
            alert_worker_error_rate_threshold=0.1,
            alert_worker_latency_ms_threshold=1000,
        ),
        now_factory=lambda: fixed_now,
    )

    assert summary["source"] == "cloud_alert_provider_degradation_worker"
    assert summary["sites_total"] == 1
    assert summary["stored_batches_total"] == 1
    assert summary["delivery_owner"] == "wordpress_fetch_apply"
    assert summary["rollup_scope_kind"] == ALERT_EVALUATE_BATCH_SCOPE
    assert summary["events_total"] == 1
    batch = summary["site_batches"][0]
    assert batch["site_id"] == "site_alpha"
    assert batch["events_total"] == 1
    assert batch["touched_rule_types"] == ["provider_degradation"]
    assert batch["providers"] == [provider_id]
    assert batch["source"] == "cloud_alert_evaluate"
    assert batch["scope_id"] == "2026-03-24T08:50:00Z__2026-03-24T09:20:00Z"

    with get_session(database_url) as session:
        repository = StatsRepository(session)
        stored_batches = repository.list_usage_rollups(
            site_scope="site_alpha",
            scope_kind=ALERT_EVALUATE_BATCH_SCOPE,
        )

    assert len(stored_batches) == 1
    assert stored_batches[0].payload_json["delivery"]["buffer_kind"] == "usage_rollup"
    assert stored_batches[0].payload_json["events"][0]["rule_type"] == "provider_degradation"

    dispose_engine(database_url)
