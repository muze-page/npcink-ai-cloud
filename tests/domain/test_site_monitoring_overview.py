from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import get_session, init_schema
from app.core.models import (
    AccountSubscription,
    MediaDerivativeJobMetric,
    PluginObservabilityEvent,
    RunRecord,
    Site,
    SiteApiKey,
    SiteKnowledgeSearchMetric,
    UsageMeterEvent,
)
from app.domain.commercial.service import CommercialService
from app.domain.observability.site_monitoring_overview import SiteMonitoringOverviewService
from tests.conftest import TEST_INTERNAL_AUTH_TOKEN, seed_site_auth


def _database_url(tmp_path: Path) -> str:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'site-monitoring-overview.sqlite3'}"
    init_schema(database_url)
    return database_url


def _settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
    )


def _run_record(
    run_id: str,
    site_id: str,
    *,
    now: datetime,
    status: str = "succeeded",
    ability_family: str = "text",
) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        site_id=site_id,
        account_id=f"account_{site_id}",
        subscription_id=f"sub_{site_id}",
        plan_version_id="plan-test-v1",
        ability_name="npcink-abilities-toolkit/test",
        ability_family=ability_family,
        skill_id="",
        workflow_id="",
        contract_version="test.v1",
        channel="openapi",
        execution_kind="test",
        execution_tier="cloud",
        execution_pattern="inline",
        data_classification="internal",
        profile_id="default",
        canonical_run_id=None,
        status=status,
        idempotency_key=f"idem-{run_id}",
        request_fingerprint=f"fingerprint-{run_id}",
        trace_id=f"trace-{run_id}",
        input_json={},
        execution_input_ciphertext=None,
        policy_json={},
        selected_provider_id="test",
        selected_model_id="test-model",
        selected_instance_id="test-instance",
        fallback_used=False,
        started_at=now - timedelta(seconds=5),
        processing_started_at=now - timedelta(seconds=4),
        finished_at=now,
    )


def _policy(database_url: str, site_id: str) -> dict[str, object]:
    service = CommercialService(database_url, settings=_settings(database_url))
    return service.inspect_commercial_policy(site_id)


def _json_contains(value: object, needle: str) -> bool:
    return needle in json.dumps(value, sort_keys=True)


def test_site_monitoring_overview_prioritizes_actions_and_quota(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    now = datetime.now(UTC)
    site_id = "site-monitoring-001"
    seed_site_auth(
        database_url,
        site_id=site_id,
        scopes=["runtime:execute", "stats:read"],
        expires_at=now + timedelta(days=2),
        budgets={
            "max_runs_per_period": 10,
            "max_tokens_per_period": 100,
            "max_cost_per_period": 5,
        },
    )
    with get_session(database_url) as session:
        site = session.get(Site, site_id)
        assert site is not None
        key = session.scalar(select(SiteApiKey).where(SiteApiKey.site_id == site_id))
        assert key is not None
        key.last_used_at = now - timedelta(hours=1)
        subscription = session.scalar(
            select(AccountSubscription)
            .where(AccountSubscription.account_id == site.account_id)
            .order_by(AccountSubscription.created_at.desc())
        )
        assert subscription is not None
        subscription.current_period_start_at = now - timedelta(days=1)
        subscription.current_period_end_at = now + timedelta(days=29)
        session.add_all(
            [
                UsageMeterEvent(
                    account_id=site.account_id,
                    site_id=site_id,
                    subscription_id=subscription.subscription_id,
                    plan_version_id=subscription.plan_version_id,
                    event_kind="meter",
                    meter_key="runs",
                    quantity=9.5,
                    ability_family="text",
                    channel="openapi",
                    execution_kind="test",
                    execution_tier="cloud",
                    data_classification="internal",
                    dedupe_key="usage-runs-001",
                    created_at=now - timedelta(minutes=10),
                ),
                PluginObservabilityEvent(
                    dedupe_key="plugin-overview-001",
                    site_id=site_id,
                    key_id="key_default",
                    schema_version="2026-06-01",
                    plugin_slug="npcink-abilities-toolkit",
                    plugin_version="0.1.0",
                    source="local",
                    event_kind="abilities.callback.failed",
                    event_id="evt-overview-001",
                    status="error",
                    error_code="abilities.callback_timeout",
                    payload_json={"secret": "must-not-leak"},
                    received_at=now - timedelta(minutes=5),
                    captured_at=now - timedelta(minutes=5),
                ),
                _run_record("run-media-overview-001", site_id, now=now, status="failed"),
                _run_record(
                    "run-vector-overview-001",
                    site_id,
                    now=now - timedelta(minutes=1),
                    ability_family="knowledge",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                MediaDerivativeJobMetric(
                    run_id="run-media-overview-001",
                    site_id=site_id,
                    account_id=site.account_id,
                    subscription_id=subscription.subscription_id,
                    status="failed",
                    error_code="media.timeout",
                    target_format="webp",
                    output_format=None,
                    source_media_type="image",
                    source_bytes=1000,
                    output_bytes=0,
                    processing_duration_ms=12000,
                    queue_wait_ms=200,
                    total_duration_ms=12200,
                    created_at=now - timedelta(minutes=4),
                    finished_at=now - timedelta(minutes=4),
                ),
                SiteKnowledgeSearchMetric(
                    run_id="run-vector-overview-001",
                    site_id=site_id,
                    account_id=site.account_id,
                    subscription_id=subscription.subscription_id,
                    status="succeeded",
                    intent="site_search",
                    result_count=0,
                    no_hit=True,
                    top1_score=0,
                    avg_score=0,
                    query_hash="hash-only",
                    query_chars=20,
                    max_results=8,
                    filter_json={},
                    embedding_provider="deterministic",
                    embedding_model="test-embedding",
                    embedding_dimensions=16,
                    vector_backend="local",
                    latency_ms=100,
                    created_at=now - timedelta(minutes=1),
                    finished_at=now - timedelta(minutes=1),
                ),
            ]
        )
        session.commit()

    summary = SiteMonitoringOverviewService(database_url).get_summary(
        site_id=site_id,
        commercial_policy=_policy(database_url, site_id),
        window_hours=24,
        now=now,
    )

    assert summary["contract_version"] == "magick-site-monitoring-overview-v1"
    assert summary["health"]["status"] in {"warning", "error"}
    assert summary["quota"]["top_pressure"] == "runs"
    assert summary["quota"]["runs"]["usage_ratio"] == 0.95
    codes = {item["code"] for item in summary["action_required"]}
    assert "site_monitoring.api_key_expiring" in codes
    assert "site_monitoring.quota_runs" in codes
    assert "site_monitoring.media_failures" in codes
    assert "site_monitoring.vector_no_hit_pressure" in codes
    assert summary["activity"]["plugin_errors_total"] == 1
    assert summary["activity"]["media_failed_total"] == 1
    assert summary["activity"]["vector_no_hit_total"] == 1
    assert not _json_contains(summary, "must-not-leak")
    assert not _json_contains(summary, "secret_hash")
    assert not _json_contains(summary, "key_default")


def test_site_monitoring_overview_flags_missing_active_key(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    site_id = "site-monitoring-no-key"
    seed_site_auth(
        database_url,
        site_id=site_id,
        scopes=["runtime:execute"],
        key_status="revoked",
        revoked_at=datetime.now(UTC) - timedelta(hours=1),
    )

    summary = SiteMonitoringOverviewService(database_url).get_summary(
        site_id=site_id,
        commercial_policy=_policy(database_url, site_id),
        window_hours=24,
        now=datetime.now(UTC),
    )

    assert summary["health"]["status"] == "error"
    assert summary["health"]["score"] == 0
    codes = {item["code"] for item in summary["action_required"]}
    assert "site_monitoring.connection_credential_missing" in codes
    assert not _json_contains(summary, "secret_hash")
    assert not _json_contains(summary, "key_default")
