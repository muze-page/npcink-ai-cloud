from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.adapters.repositories.stats_repository import StatsRepository
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import ProviderCallRecord, RunRecord
from app.domain.catalog.service import CatalogService
from app.domain.runtime.models import RuntimeRequest
from app.domain.runtime.service import RuntimeService
from app.domain.usage.rollup import (
    ALERT_EVALUATE_BATCH_SCOPE,
    GLOBAL_SITE_SCOPE,
    LATENCY_PROBE_BATCH_SCOPE,
    ROUTER_DIAGNOSTICS_BATCH_SCOPE,
    ROUTER_PERFORMANCE_BATCH_SCOPE,
    UsageRollupService,
)
from tests.conftest import seed_site_auth


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'usage-rollup-domain.sqlite3'}"


def test_usage_rollup_service_writes_summary_profile_and_instance_snapshots(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    CatalogService(database_url).scan_provider_health()
    seed_site_auth(database_url, site_id="site_alpha")

    runtime_result = RuntimeService(database_url).execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="rollup-run-001",
            trace_id="rollup-trace-001",
            input_payload={"messages": [{"role": "user", "content": "rollup me"}]},
        )
    )
    fixed_now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    with get_session(database_url) as session:
        run = session.scalar(select(RunRecord).where(RunRecord.run_id == runtime_result.run_id))
        assert run is not None
        run.started_at = fixed_now.replace(hour=7, minute=50)
        run.finished_at = fixed_now.replace(hour=7, minute=50)

        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord)
                .where(ProviderCallRecord.run_id == runtime_result.run_id)
                .order_by(ProviderCallRecord.id.asc())
            )
        )
        for index, provider_call in enumerate(provider_calls):
            provider_call.created_at = fixed_now.replace(hour=7, minute=50, second=index + 1)

        session.commit()

    service = UsageRollupService(
        database_url,
        now_factory=lambda: fixed_now,
    )
    with get_session(database_url) as session:
        repository = StatsRepository(session)
        expected_profile_rollups = len(repository.list_profiles()) * 2
        expected_instance_rollups = len(repository.list_instances()) * 2

    result = service.generate_rollups(site_ids=["site_alpha"], include_global=True)

    assert result["counts"] == {
        "summary": 2,
        "profile": expected_profile_rollups,
        "instance": expected_instance_rollups,
    }
    assert result["rollups_total"] == 2 + expected_profile_rollups + expected_instance_rollups

    with get_session(database_url) as session:
        repository = StatsRepository(session)
        global_summary = next(
            rollup
            for rollup in repository.list_usage_rollups(
                site_scope=GLOBAL_SITE_SCOPE,
                scope_kind="summary",
            )
            if rollup.scope_id == "__summary__"
        )
        site_summary = next(
            rollup
            for rollup in repository.list_usage_rollups(
                site_scope="site_alpha",
                scope_kind="summary",
            )
            if rollup.scope_id == "__summary__"
        )
        instance_rollup = next(
            rollup
            for rollup in repository.list_usage_rollups(
                site_scope="site_alpha",
                scope_kind="instance",
            )
            if rollup.scope_id == "openai-us-east-text-balanced"
        )

    assert global_summary.payload_json["windows"]["today"]["runs_total"] == 1
    assert site_summary.payload_json["windows"]["today"]["runs_total"] == 1
    assert instance_rollup.payload_json["instance_id"] == "openai-us-east-text-balanced"
    assert "health_score" in instance_rollup.payload_json

    dispose_engine(database_url)


def test_usage_rollup_service_stores_router_performance_projection_batches(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    CatalogService(database_url).scan_provider_health()
    seed_site_auth(database_url, site_id="site_alpha")

    runtime_result = RuntimeService(database_url).execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="router-performance-rollup-001",
            trace_id="router-performance-rollup-001",
            input_payload={"messages": [{"role": "user", "content": "snapshot me"}]},
            policy={"preset_id": "preset.alpha"},
        )
    )

    fixed_now = datetime(2026, 3, 24, 9, 20, tzinfo=UTC)
    with get_session(database_url) as session:
        run = session.scalar(select(RunRecord).where(RunRecord.run_id == runtime_result.run_id))
        assert run is not None
        run.started_at = fixed_now.replace(hour=8, minute=15)
        run.finished_at = fixed_now.replace(hour=8, minute=15)
        run.policy_json = {"preset_id": "preset.alpha"}

        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord)
                .where(ProviderCallRecord.run_id == runtime_result.run_id)
                .order_by(ProviderCallRecord.id.asc())
            )
        )
        for index, provider_call in enumerate(provider_calls):
            provider_call.created_at = fixed_now.replace(hour=8, minute=15, second=index + 1)
            if index == 0:
                provider_call.error_code = "quota.rate_limited"

        session.commit()

    service = UsageRollupService(database_url, now_factory=lambda: fixed_now)
    result = service.store_router_performance_snapshot_batches(
        site_ids=["site_alpha"],
        start_at=fixed_now.replace(hour=8, minute=0, second=0, microsecond=0),
        end_at=fixed_now.replace(hour=9, minute=0, second=0, microsecond=0),
    )

    assert result["scope_kind"] == ROUTER_PERFORMANCE_BATCH_SCOPE
    assert result["stored_batches_total"] == 1
    assert result["rows_total"] >= 1

    with get_session(database_url) as session:
        repository = StatsRepository(session)
        stored_batch = next(
            rollup
            for rollup in repository.list_usage_rollups(
                site_scope="site_alpha",
                scope_kind=ROUTER_PERFORMANCE_BATCH_SCOPE,
            )
            if rollup.scope_id == "2026-03-24T08:00:00Z__2026-03-24T09:00:00Z"
        )

    assert stored_batch.payload_json["delivery"]["owner"] == "wordpress_fetch_apply"
    assert stored_batch.payload_json["source"] == "cloud_router_performance_snapshot"
    assert stored_batch.payload_json["window"]["start_gmt"] == "2026-03-24 08:00:00"
    assert stored_batch.payload_json["window"]["end_gmt"] == "2026-03-24 09:00:00"
    row = stored_batch.payload_json["rows"][0]
    assert row["preset_id"] == "preset.alpha"
    assert row["guard_fail_total"] >= 1

    dispose_engine(database_url)


def test_usage_rollup_service_stores_router_diagnostics_projection_batches(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    CatalogService(database_url).scan_provider_health()
    seed_site_auth(database_url, site_id="site_alpha", scopes=["stats:read"])

    runtime_result = RuntimeService(database_url).execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="router-diagnostics-rollup-001",
            trace_id="router-diagnostics-rollup-001",
            input_payload={"messages": [{"role": "user", "content": "diagnose me"}]},
        )
    )

    fixed_now = datetime(2026, 3, 24, 9, 20, tzinfo=UTC)
    with get_session(database_url) as session:
        run = session.scalar(select(RunRecord).where(RunRecord.run_id == runtime_result.run_id))
        assert run is not None
        run.started_at = fixed_now - timedelta(minutes=20)
        run.finished_at = fixed_now - timedelta(minutes=19)
        run.policy_json = {"callback_url": "https://callbacks.example.test/runtime"}
        run.callback_status = "failed"
        run.error_code = "callback.failed"
        session.commit()

    service = UsageRollupService(database_url, now_factory=lambda: fixed_now)
    result = service.store_router_diagnostics_batches(
        site_ids=["site_alpha"],
        recent_minutes=60,
        config_revision="cloud_runtime_summary_worker",
    )

    assert result["scope_kind"] == ROUTER_DIAGNOSTICS_BATCH_SCOPE
    assert result["stored_batches_total"] == 1
    assert result["regressions_total"] >= 1

    with get_session(database_url) as session:
        repository = StatsRepository(session)
        stored_batch = next(
            rollup
            for rollup in repository.list_usage_rollups(
                site_scope="site_alpha",
                scope_kind=ROUTER_DIAGNOSTICS_BATCH_SCOPE,
            )
            if rollup.scope_id == "2026-03-24T09:20:00Z__60m"
        )

    assert stored_batch.payload_json["delivery"]["owner"] == "wordpress_fetch_apply"
    assert stored_batch.payload_json["source"] == "cloud_router_diagnostics"
    assert stored_batch.payload_json["config_revision"] == "cloud_runtime_summary_worker"
    report = stored_batch.payload_json["report"]
    assert report["regressions"]["count"] >= 1
    assert isinstance(report["regressions"]["items"], list)

    dispose_engine(database_url)


def test_usage_rollup_service_stores_latency_probe_projection_batches(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    CatalogService(database_url).scan_provider_health()
    seed_site_auth(database_url, site_id="site_alpha", scopes=["stats:read"])

    runtime_result = RuntimeService(database_url).execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="latency-probe-rollup-001",
            trace_id="latency-probe-rollup-001",
            input_payload={"messages": [{"role": "user", "content": "probe me"}]},
        )
    )

    fixed_now = datetime(2026, 3, 24, 9, 20, tzinfo=UTC)
    with get_session(database_url) as session:
        run = session.scalar(select(RunRecord).where(RunRecord.run_id == runtime_result.run_id))
        assert run is not None
        run.started_at = fixed_now - timedelta(minutes=30)
        run.finished_at = fixed_now - timedelta(minutes=30)

        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord)
                .where(ProviderCallRecord.run_id == runtime_result.run_id)
                .order_by(ProviderCallRecord.id.asc())
            )
        )
        assert provider_calls
        provider_calls[0].created_at = fixed_now - timedelta(minutes=20)
        provider_calls[0].latency_ms = 420
        if len(provider_calls) > 1:
            provider_calls[1].created_at = fixed_now - timedelta(minutes=18)
            provider_calls[1].latency_ms = 900
        else:
            session.add(
                ProviderCallRecord(
                    run_id=runtime_result.run_id,
                    provider_id=provider_calls[0].provider_id,
                    model_id=provider_calls[0].model_id,
                    instance_id=provider_calls[0].instance_id,
                    region=provider_calls[0].region,
                    latency_ms=900,
                    tokens_in=1,
                    tokens_out=1,
                    cost=0.0,
                    retry_count=0,
                    fallback_used=False,
                    error_code=None,
                    created_at=fixed_now - timedelta(minutes=18),
                )
            )
        session.commit()
        primary_instance_id = provider_calls[0].instance_id

    service = UsageRollupService(database_url, now_factory=lambda: fixed_now)
    result = service.store_latency_probe_batches(
        site_instances={"site_alpha": [primary_instance_id]},
        start_at=fixed_now - timedelta(minutes=60),
        end_at=fixed_now,
    )

    assert result["scope_kind"] == LATENCY_PROBE_BATCH_SCOPE
    assert result["stored_batches_total"] == 1
    assert result["instances_total"] == 1

    with get_session(database_url) as session:
        repository = StatsRepository(session)
        stored_batch = next(
            rollup
            for rollup in repository.list_usage_rollups(
                site_scope="site_alpha",
                scope_kind=LATENCY_PROBE_BATCH_SCOPE,
            )
            if rollup.scope_id == "2026-03-24T08:20:00Z__2026-03-24T09:20:00Z"
        )

    assert stored_batch.payload_json["delivery"]["owner"] == "wordpress_fetch_apply"
    assert stored_batch.payload_json["source"] == "cloud_latency_probe"
    instance = stored_batch.payload_json["instances"][0]
    assert instance["instance_id"] == primary_instance_id
    assert instance["runtime"] == "hosted_profile"
    assert instance["latency_ms_p50"] == 420
    assert instance["latency_ms_p95"] == 900

    dispose_engine(database_url)


def test_usage_rollup_service_skips_missing_latency_probe_instances(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_site_auth(database_url, site_id="site_alpha", scopes=["stats:read"])

    fixed_now = datetime(2026, 3, 24, 9, 20, tzinfo=UTC)
    service = UsageRollupService(database_url, now_factory=lambda: fixed_now)
    result = service.store_latency_probe_batches(
        site_instances={"site_alpha": ["retired-instance"]},
        start_at=fixed_now - timedelta(minutes=60),
        end_at=fixed_now,
    )

    assert result["scope_kind"] == LATENCY_PROBE_BATCH_SCOPE
    assert result["stored_batches_total"] == 1
    assert result["instances_total"] == 0
    assert result["site_batches"][0]["skipped_total"] == 1
    assert result["site_batches"][0]["instance_batches"] == []

    with get_session(database_url) as session:
        repository = StatsRepository(session)
        stored_batch = next(
            rollup
            for rollup in repository.list_usage_rollups(
                site_scope="site_alpha",
                scope_kind=LATENCY_PROBE_BATCH_SCOPE,
            )
            if rollup.scope_id == "2026-03-24T08:20:00Z__2026-03-24T09:20:00Z"
        )

    assert stored_batch.payload_json["source"] == "cloud_latency_probe"
    assert stored_batch.payload_json["instances"] == []

    dispose_engine(database_url)


def test_usage_rollup_service_stores_alert_provider_degradation_batches(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    CatalogService(database_url).scan_provider_health()
    seed_site_auth(database_url, site_id="site_alpha", scopes=["stats:read"])

    runtime_result = RuntimeService(database_url).execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="alert-rollup-001",
            trace_id="alert-rollup-001",
            input_payload={"messages": [{"role": "user", "content": "alert me"}]},
        )
    )

    fixed_now = datetime(2026, 3, 24, 9, 20, tzinfo=UTC)
    with get_session(database_url) as session:
        run = session.scalar(select(RunRecord).where(RunRecord.run_id == runtime_result.run_id))
        assert run is not None
        run.started_at = fixed_now - timedelta(minutes=10)
        run.finished_at = fixed_now - timedelta(minutes=10) + timedelta(milliseconds=25000)

        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord)
                .where(ProviderCallRecord.run_id == runtime_result.run_id)
                .order_by(ProviderCallRecord.id.asc())
            )
        )
        assert provider_calls
        provider_calls[0].created_at = fixed_now - timedelta(minutes=5)
        provider_calls[0].latency_ms = 25000
        provider_calls[0].error_code = "provider.timeout"
        session.commit()
        provider_id = provider_calls[0].provider_id

    service = UsageRollupService(database_url, now_factory=lambda: fixed_now)
    result = service.store_alert_provider_degradation_batches(
        site_ids=["site_alpha"],
        window_minutes=30,
        min_requests=1,
        error_rate_threshold=0.1,
        latency_ms_threshold=1000,
    )

    assert result["scope_kind"] == ALERT_EVALUATE_BATCH_SCOPE
    assert result["stored_batches_total"] == 1
    assert result["events_total"] == 1

    with get_session(database_url) as session:
        repository = StatsRepository(session)
        stored_batch = next(
            rollup
            for rollup in repository.list_usage_rollups(
                site_scope="site_alpha",
                scope_kind=ALERT_EVALUATE_BATCH_SCOPE,
            )
            if rollup.scope_id == "2026-03-24T08:50:00Z__2026-03-24T09:20:00Z"
        )

    assert stored_batch.payload_json["delivery"]["owner"] == "wordpress_fetch_apply"
    assert stored_batch.payload_json["source"] == "cloud_alert_evaluate"
    assert stored_batch.payload_json["touched_rule_types"] == ["provider_degradation"]
    event = stored_batch.payload_json["events"][0]
    assert event["rule_type"] == "provider_degradation"
    assert event["summary"]["provider"] == provider_id

    dispose_engine(database_url)
