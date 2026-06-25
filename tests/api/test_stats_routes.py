from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import HealthSnapshot, ProviderCallRecord, RunRecord, RuntimeGuardEvent
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from app.domain.runtime.models import RuntimeRequest
from app.domain.runtime.service import RuntimeService
from app.domain.usage.rollup import UsageRollupService
from tests.conftest import build_auth_headers, seed_site_auth


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'stats-api.sqlite3'}"


def _build_client(tmp_path: Path) -> tuple[str, TestClient, datetime]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    CatalogService(database_url).scan_provider_health()
    seed_site_auth(database_url, site_id="site_alpha", scopes=["stats:read"])

    runtime_service = RuntimeService(database_url)
    run_a = runtime_service.execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="stats-api-run-a",
            trace_id="stats-api-trace-a",
            input_payload={"messages": [{"role": "user", "content": "direct success"}]},
        )
    )
    run_b = runtime_service.execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="stats-api-run-b",
            trace_id="stats-api-trace-b",
            input_payload={
                "messages": [{"role": "user", "content": "fallback success"}],
                "simulate_error_for_instances": [
                    "openai-us-east-text-balanced",
                ],
            },
            policy={"allow_fallback": True},
        )
    )

    now = datetime.now(UTC)
    with get_session(database_url) as session:
        run_specs = {
            run_a.run_id: {
                "started_at": now - timedelta(minutes=25),
                "finished_at": now - timedelta(minutes=25) + timedelta(milliseconds=95),
            },
            run_b.run_id: {
                "started_at": now - timedelta(minutes=15),
                "finished_at": now - timedelta(minutes=15) + timedelta(milliseconds=180),
            },
        }

        for run_id, spec in run_specs.items():
            run = session.scalar(select(RunRecord).where(RunRecord.run_id == run_id))
            assert run is not None
            run.started_at = spec["started_at"]
            run.finished_at = spec["finished_at"]
            run.policy_json = {
                "callback_url": "https://callbacks.example.test/runtime",
                "preset_id": "preset.alpha" if run_id == run_a.run_id else "preset.beta",
            }

            provider_calls = list(
                session.scalars(
                    select(ProviderCallRecord)
                    .where(ProviderCallRecord.run_id == run_id)
                    .order_by(ProviderCallRecord.id.asc())
                )
            )
            for index, provider_call in enumerate(provider_calls):
                provider_call.created_at = spec["started_at"] + timedelta(seconds=index + 1)
                if run_id == run_a.run_id:
                    provider_call.latency_ms = 95
                if run_id == run_b.run_id and index == 0:
                    provider_call.error_code = "quota.rate_limited"
                    provider_call.latency_ms = 120
                elif run_id == run_b.run_id:
                    provider_call.latency_ms = 180

        health_snapshots = list(
            session.scalars(select(HealthSnapshot).order_by(HealthSnapshot.id.asc()))
        )
        for health_snapshot in health_snapshots:
            health_snapshot.measured_at = now - timedelta(minutes=5)

        failed_run = session.scalar(select(RunRecord).where(RunRecord.run_id == run_a.run_id))
        assert failed_run is not None
        failed_run.callback_status = "failed"
        failed_run.callback_last_attempt_at = now - timedelta(minutes=4)
        failed_run.error_code = "callback.failed"

        due_run = session.scalar(select(RunRecord).where(RunRecord.run_id == run_b.run_id))
        assert due_run is not None
        due_run.callback_status = "pending"
        due_run.callback_next_attempt_at = now - timedelta(minutes=3)

        session.add(
            RuntimeGuardEvent(
                auth_surface="openapi",
                scope_kind="site",
                scope_id="site_alpha",
                site_id="site_alpha",
                key_id="key_alpha",
                client_ref="client_alpha",
                event_code="auth.rate_limit_exceeded",
                status_code=429,
                method="GET",
                path="/v1/runtime/execute",
                trace_id="trace-guard-1",
                payload_json={"reason": "synthetic"},
                created_at=now - timedelta(minutes=2),
            )
        )

        session.commit()

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    return database_url, TestClient(create_app(CloudServices(settings=settings))), now


def test_stats_routes_return_windowed_metrics_and_health(tmp_path: Path) -> None:
    database_url, client, seeded_now = _build_client(tmp_path)

    probe_end = seeded_now.replace(second=0, microsecond=0)
    probe_start = probe_end - timedelta(minutes=15)
    UsageRollupService(database_url, now_factory=lambda: probe_end).store_latency_probe_batches(
        site_instances={"site_alpha": ["openai-us-east-text-balanced"]},
        start_at=probe_start,
        end_at=probe_end,
    )

    projection_end = seeded_now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    projection_start = projection_end - timedelta(hours=24)
    UsageRollupService(
        database_url,
        now_factory=lambda: projection_end,
    ).store_router_performance_snapshot_batches(
        site_ids=["site_alpha"],
        start_at=projection_start,
        end_at=projection_end,
    )

    UsageRollupService(
        database_url,
        now_factory=lambda: seeded_now,
    ).store_router_diagnostics_batches(
        site_ids=["site_alpha"],
        recent_minutes=60,
        config_revision="windowed-metrics",
    )

    instance_response = client.get(
        "/v1/stats/instances/openai-us-east-text-balanced",
        headers=build_auth_headers(
            "GET",
            "/v1/stats/instances/openai-us-east-text-balanced",
            site_id="site_alpha",
            trace_id="tracestatsapi0010000000000000000",
        ),
    )
    profile_response = client.get(
        "/v1/stats/profiles/text.balanced",
        headers=build_auth_headers(
            "GET",
            "/v1/stats/profiles/text.balanced",
            site_id="site_alpha",
            trace_id="tracestatsapi0020000000000000000",
        ),
    )
    hosted_discovery_response = client.get(
        "/v1/stats/hosted/discovery",
        headers=build_auth_headers(
            "GET",
            "/v1/stats/hosted/discovery",
            site_id="site_alpha",
            trace_id="tracestatsapi0022000000000000000",
        ),
    )
    hosted_profile_metadata_response = client.get(
        "/v1/stats/hosted/profiles/text.balanced/metadata",
        headers=build_auth_headers(
            "GET",
            "/v1/stats/hosted/profiles/text.balanced/metadata",
            site_id="site_alpha",
            trace_id="tracestatsapi0023000000000000000",
        ),
    )
    hosted_instance_metadata_response = client.get(
        "/v1/stats/hosted/instances/openai-us-east-text-balanced/metadata",
        headers=build_auth_headers(
            "GET",
            "/v1/stats/hosted/instances/openai-us-east-text-balanced/metadata",
            site_id="site_alpha",
            trace_id="tracestatsapi0024000000000000000",
        ),
    )
    usage_response = client.get(
        "/v1/usage/summary",
        headers=build_auth_headers(
            "GET",
            "/v1/usage/summary",
            site_id="site_alpha",
            trace_id="tracestatsapi0030000000000000000",
        ),
    )
    projection_query = (
        "start_gmt="
        + projection_start.strftime("%Y-%m-%d%%20%H:00:00")
        + "&end_gmt="
        + projection_end.strftime("%Y-%m-%d%%20%H:00:00")
    )
    projection_response = client.get(
        f"/v1/router/performance-snapshot?{projection_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/router/performance-snapshot",
            site_id="site_alpha",
            trace_id="tracestatsapi0035000000000000000",
            query=projection_query,
        ),
    )
    alert_query = (
        "window_minutes=30&min_requests=1&error_rate_threshold=0.25&latency_ms_threshold=1"
    )
    alert_response = client.get(
        f"/v1/alerts/provider-degradation?{alert_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/alerts/provider-degradation",
            site_id="site_alpha",
            trace_id="tracestatsapi0037000000000000000",
            query=alert_query,
        ),
    )
    diagnostics_query = (
        "config_revision=cfg-test-1"
        "&enabled_total=7"
        "&tagless_enabled=true"
        "&high_risk_count=2"
        "&has_warnings=true"
        "&recent_minutes=60"
    )
    diagnostics_response = client.get(
        f"/v1/router/diagnostics?{diagnostics_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/router/diagnostics",
            site_id="site_alpha",
            trace_id="tracestatsapi0038000000000000000",
            query=diagnostics_query,
        ),
    )
    recommendation_response = client.get(
        f"/v1/router/recommendation?{diagnostics_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/router/recommendation",
            site_id="site_alpha",
            trace_id="tracestatsapi0039000000000000000",
            query=diagnostics_query,
        ),
    )
    assert instance_response.status_code == 200
    assert profile_response.status_code == 200
    assert hosted_discovery_response.status_code == 200
    assert hosted_profile_metadata_response.status_code == 200
    assert hosted_instance_metadata_response.status_code == 200
    assert usage_response.status_code == 200
    assert projection_response.status_code == 200
    assert alert_response.status_code == 200
    assert diagnostics_response.status_code == 200
    assert recommendation_response.status_code == 200

    instance_payload = instance_response.json()["data"]
    profile_payload = profile_response.json()["data"]
    discovery_payload = hosted_discovery_response.json()["data"]
    hosted_profile_metadata_payload = hosted_profile_metadata_response.json()["data"]
    hosted_instance_metadata_payload = hosted_instance_metadata_response.json()["data"]
    usage_payload = usage_response.json()["data"]
    projection_payload = projection_response.json()["data"]
    alert_payload = alert_response.json()["data"]
    diagnostics_payload = diagnostics_response.json()["data"]
    recommendation_payload = recommendation_response.json()["data"]

    assert instance_payload["today_calls"] == 2
    assert instance_payload["source"] == "cloud_latency_probe_buffer"
    assert instance_payload["windows"]["today"]["success_total"] == 0
    assert instance_payload["health_status"] == "healthy"
    assert instance_payload["health_score"] >= 0
    assert instance_payload["health_window_calls"] == 2

    assert profile_payload["today_calls"] == 2
    assert profile_payload["fallback_rate"] == 0.5
    assert profile_payload["health"]["healthy_total"] == 3
    assert profile_payload["health"]["avg_score"] == 0.8333
    assert discovery_payload["profiles"]
    assert discovery_payload["instances"]
    assert hosted_profile_metadata_payload["profile_id"] == "text.balanced"
    assert hosted_profile_metadata_payload["candidate_total"] >= 1
    assert "pricing" in hosted_profile_metadata_payload
    assert "capability_tags" in hosted_profile_metadata_payload
    assert hosted_instance_metadata_payload["instance_id"] == "openai-us-east-text-balanced"
    assert "capability_tags" in hosted_instance_metadata_payload
    assert "price_input" in hosted_instance_metadata_payload
    assert "price_output" in hosted_instance_metadata_payload

    assert usage_payload["windows"]["today"]["runs_total"] == 2
    assert usage_payload["windows"]["today"]["provider_calls_total"] == 3
    usage_health = usage_payload["health"]
    assert usage_health["instances_total"] >= len(discovery_payload["instances"])
    assert usage_health["healthy_total"] >= 1
    assert (
        usage_health["healthy_total"]
        + usage_health["degraded_total"]
        + usage_health["unhealthy_total"]
        + usage_health["unknown_total"]
        == usage_health["instances_total"]
    )
    assert usage_health["avg_score"] > 0
    assert projection_payload["source"] == "cloud_router_performance_snapshot"
    assert projection_payload["site_id"] == "site_alpha"
    assert projection_payload["window"]["start_gmt"] == projection_start.strftime(
        "%Y-%m-%d %H:00:00"
    )
    assert projection_payload["window"]["end_gmt"] == projection_end.strftime("%Y-%m-%d %H:00:00")
    assert projection_payload["cursor"]["next_end_gmt"] == projection_end.strftime(
        "%Y-%m-%d %H:00:00"
    )
    rows = projection_payload["rows"]
    assert len(rows) >= 2
    assert all(
        row["ability_id"] == "npcink-abilities-toolkit/build-article-block-plan" for row in rows
    )
    assert all(row["caller_id"] == "openapi" for row in rows)
    assert sum(int(row["request_total"]) for row in rows) == 3
    assert sum(int(row["success_total"]) for row in rows) == 2
    latencies = sorted(float(row["avg_latency_ms"]) for row in rows)
    assert latencies[-1] > 0.0
    assert latencies[-1] >= latencies[0]
    assert alert_payload["source"] == "cloud_alert_evaluate"
    assert alert_payload["site_id"] == "site_alpha"
    assert alert_payload["touched_rule_types"] == ["provider_degradation"]
    assert len(alert_payload["events"]) == 1
    alert_event = alert_payload["events"][0]
    assert alert_event["rule_type"] == "provider_degradation"
    assert alert_event["status"] == "open"
    assert alert_event["fingerprint"] == "provider_degradation:openai"
    assert alert_event["summary"]["provider"] == "openai"
    assert alert_event["summary"]["total"] == 3
    assert alert_event["summary"]["errors"] == 1
    assert alert_event["summary"]["error_rate"] == 0.3333
    assert alert_event["summary"]["avg_latency_ms"] > 0
    assert alert_event["context"]["healthy_instances_total"] >= 1
    assert alert_event["channels"]["log"] is True
    assert diagnostics_payload["source"] == "cloud_router_diagnostics"
    assert diagnostics_payload["site_id"] == "site_alpha"
    assert diagnostics_payload["config_revision"] == "cfg-test-1"
    assert diagnostics_payload["report"]["validation"]["enabled_total"] == 7
    assert diagnostics_payload["report"]["validation"]["tagless_enabled"] is True
    assert diagnostics_payload["report"]["high_risk"]["count"] == 2
    assert diagnostics_payload["report"]["validation"]["has_warnings"] is True
    assert diagnostics_payload["report"]["regressions"]["count"] == 1
    assert diagnostics_payload["report"]["quality_regressions"]["count"] == 2
    assert diagnostics_payload["report"]["quality_regressions"]["reason"] == "cloud_runtime_summary"
    assert diagnostics_payload["report"]["regressions"]["items"][0]["kind"] == "callback_failed"
    assert diagnostics_payload["report"]["regressions"]["items"][0]["run_id"] != ""
    assert (
        diagnostics_payload["report"]["regressions"]["items"][0]["details"]["ability_name"]
        == "npcink-abilities-toolkit/build-article-block-plan"
    )
    assert (
        diagnostics_payload["report"]["regressions"]["items"][0]["details"]["channel"] == "openapi"
    )
    assert (
        diagnostics_payload["report"]["quality_regressions"]["items"][0]["kind"] == "callback_due"
    )
    assert diagnostics_payload["report"]["quality_regressions"]["items"][0]["run_id"] != ""
    assert diagnostics_payload["report"]["quality_regressions"]["items"][1]["kind"] == "guard_event"
    assert (
        diagnostics_payload["report"]["quality_regressions"]["items"][1]["event_code"]
        == "auth.rate_limit_exceeded"
    )
    assert (
        diagnostics_payload["report"]["quality_regressions"]["items"][1]["details"]["status_code"]
        == 429
    )
    assert (
        diagnostics_payload["report"]["quality_regressions"]["items"][1]["details"]["path"]
        == "/v1/runtime/execute"
    )
    assert "recommended_provider_ids" in recommendation_payload
    assert "recommended_profile_ids" in recommendation_payload
    assert "summary_lines" in recommendation_payload

    dispose_engine(database_url)


def test_instance_stats_prefers_latency_probe_delivery_buffer_when_present(
    tmp_path: Path,
) -> None:
    database_url, client, seeded_now = _build_client(tmp_path)

    probe_end = seeded_now.replace(second=0, microsecond=0)
    probe_start = probe_end - timedelta(minutes=15)
    UsageRollupService(database_url, now_factory=lambda: probe_end).store_latency_probe_batches(
        site_instances={"site_alpha": ["openai-us-east-text-balanced"]},
        start_at=probe_start,
        end_at=probe_end,
    )

    response = client.get(
        "/v1/stats/instances/openai-us-east-text-balanced",
        headers=build_auth_headers(
            "GET",
            "/v1/stats/instances/openai-us-east-text-balanced",
            site_id="site_alpha",
            trace_id="tracestatsapi0015000000000000000",
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["source"] == "cloud_latency_probe_buffer"
    assert payload["delivery"]["owner"] == "wordpress_fetch_apply"
    assert payload["delivery"]["buffer_kind"] == "usage_rollup"
    assert payload["delivery"]["scope_kind"] == "latency_probe_batch"
    assert payload["today_calls"] >= 1
    assert payload["avg_latency_ms"] > 0
    assert payload["health_status"] != ""
    assert payload["windows"]["today"]["start_at"] == probe_start.strftime("%Y-%m-%d %H:%M:%S")
    assert payload["windows"]["today"]["end_at"] == probe_end.strftime("%Y-%m-%d %H:%M:%S")

    dispose_engine(database_url)


def test_instance_stats_returns_bounded_empty_payload_when_delivery_buffer_is_absent(
    tmp_path: Path,
) -> None:
    database_url, client, _ = _build_client(tmp_path)

    response = client.get(
        "/v1/stats/instances/openai-us-east-text-balanced",
        headers=build_auth_headers(
            "GET",
            "/v1/stats/instances/openai-us-east-text-balanced",
            site_id="site_alpha",
            trace_id="tracestatsapi0016000000000000000",
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["source"] == "cloud_latency_probe_empty"
    assert payload["status"] == "empty"
    assert payload["today_calls"] == 0
    assert payload["windows"]["today"]["calls_total"] == 0
    assert payload["windows"]["rolling_24h"]["calls_total"] == 0

    dispose_engine(database_url)


def test_alert_provider_degradation_prefers_delivery_buffer_when_present(
    tmp_path: Path,
) -> None:
    database_url, client, _ = _build_client(tmp_path)

    UsageRollupService(database_url).store_alert_provider_degradation_batches(
        site_ids=["site_alpha"],
        window_minutes=30,
        min_requests=1,
        error_rate_threshold=0.25,
        latency_ms_threshold=1,
    )

    alert_query = (
        "window_minutes=30&min_requests=1&error_rate_threshold=0.25&latency_ms_threshold=1"
    )
    response = client.get(
        f"/v1/alerts/provider-degradation?{alert_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/alerts/provider-degradation",
            site_id="site_alpha",
            trace_id="tracestatsapi0017000000000000000",
            query=alert_query,
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["source"] == "cloud_alert_evaluate"
    assert payload["delivery"]["owner"] == "wordpress_fetch_apply"
    assert payload["delivery"]["buffer_kind"] == "usage_rollup"
    assert payload["delivery"]["scope_kind"] == "alert_evaluate_batch"
    assert payload["touched_rule_types"] == ["provider_degradation"]
    assert len(payload["events"]) == 1

    dispose_engine(database_url)


def test_logs_analytics_routes_return_cloud_projection_payloads(tmp_path: Path) -> None:
    database_url, client, seeded_now = _build_client(tmp_path)
    window_start = (seeded_now - timedelta(hours=1)).strftime("%Y-%m-%d%%20%H:%M:%S")
    window_end = seeded_now.strftime("%Y-%m-%d%%20%H:%M:%S")
    logs_query = f"range=24h&start_gmt={window_start}&end_gmt={window_end}&status=all"

    summary_response = client.get(
        f"/v1/logs/analytics/summary?{logs_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/logs/analytics/summary",
            site_id="site_alpha",
            trace_id="tracestatsapi0041000000000000000",
            query=logs_query,
        ),
    )
    tool_latency_response = client.get(
        f"/v1/logs/analytics/tool-latency?{logs_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/logs/analytics/tool-latency",
            site_id="site_alpha",
            trace_id="tracestatsapi0041100000000000000",
            query=logs_query,
        ),
    )
    recommendations_response = client.get(
        f"/v1/logs/analytics/recommendations?{logs_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/logs/analytics/recommendations",
            site_id="site_alpha",
            trace_id="tracestatsapi0041200000000000000",
            query=logs_query,
        ),
    )
    mcp_zone_response = client.get(
        f"/v1/logs/analytics/mcp-zone?{logs_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/logs/analytics/mcp-zone",
            site_id="site_alpha",
            trace_id="tracestatsapi0041300000000000000",
            query=logs_query,
        ),
    )

    assert summary_response.status_code == 200
    assert tool_latency_response.status_code == 200
    assert recommendations_response.status_code == 200
    assert mcp_zone_response.status_code == 200

    summary_payload = summary_response.json()["data"]
    tool_latency_payload = tool_latency_response.json()["data"]
    recommendations_payload = recommendations_response.json()["data"]
    mcp_zone_payload = mcp_zone_response.json()["data"]

    assert summary_payload["source"] == "cloud_logs_analytics_summary"
    assert summary_payload["total"] == 3
    assert summary_payload["success"] == 1
    assert summary_payload["error"] == 2
    assert summary_payload["error_only"] == 1
    assert summary_payload["status_distribution"]["error"] == 1
    assert summary_payload["status_distribution"]["blocked"] == 1
    assert len(summary_payload["trend_7d"]) == 7

    assert tool_latency_payload["source"] == "cloud"
    assert tool_latency_payload["samples"] == 3
    assert tool_latency_payload["p95_ms"] >= tool_latency_payload["p50_ms"]

    assert recommendations_payload["source"] == "cloud"
    assert recommendations_payload["recommended_providers"][0] == "openai"
    assert recommendations_payload["recommended_error_codes"] == [
        "callback.failed",
        "quota.rate_limited",
    ]

    assert mcp_zone_payload["source"] == "cloud"
    assert mcp_zone_payload["window"] == "24h"
    assert mcp_zone_payload["calls_total"] == 0
    assert mcp_zone_payload["caller_options"] == []

    dispose_engine(database_url)


def test_router_diagnostics_summary_exposes_runtime_case_details(tmp_path: Path) -> None:
    database_url, client, seeded_now = _build_client(tmp_path)

    UsageRollupService(
        database_url,
        now_factory=lambda: seeded_now,
    ).store_router_diagnostics_batches(
        site_ids=["site_alpha"],
        recent_minutes=60,
        config_revision="case-details",
    )

    diagnostics_query = (
        "config_revision=cfg-details-1"
        "&enabled_total=7"
        "&tagless_enabled=true"
        "&high_risk_count=2"
        "&has_warnings=true"
        "&recent_minutes=60"
    )
    response = client.get(
        f"/v1/router/diagnostics?{diagnostics_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/router/diagnostics",
            site_id="site_alpha",
            trace_id="tracestatsapi0042000000000000000",
            query=diagnostics_query,
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["source"] == "cloud_router_diagnostics"
    assert payload["report"]["regressions"]["items"][0]["kind"] == "callback_failed"
    assert payload["report"]["regressions"]["items"][0]["run_id"] != ""
    assert (
        payload["report"]["regressions"]["items"][0]["details"]["ability_name"]
        == "npcink-abilities-toolkit/build-article-block-plan"
    )
    assert payload["report"]["regressions"]["items"][0]["details"]["selected_instance_id"] != ""
    assert payload["report"]["quality_regressions"]["items"][0]["kind"] == "callback_due"
    assert payload["report"]["quality_regressions"]["items"][0]["run_id"] != ""
    assert payload["report"]["quality_regressions"]["items"][1]["kind"] == "guard_event"
    assert (
        payload["report"]["quality_regressions"]["items"][1]["event_code"]
        == "auth.rate_limit_exceeded"
    )
    assert (
        payload["report"]["quality_regressions"]["items"][1]["details"]["auth_surface"] == "openapi"
    )
    assert (
        payload["report"]["quality_regressions"]["items"][1]["details"]["trace_id"]
        == "trace-guard-1"
    )

    dispose_engine(database_url)


def test_router_diagnostics_returns_bounded_empty_payload_when_delivery_buffer_is_absent(
    tmp_path: Path,
) -> None:
    database_url, client, _ = _build_client(tmp_path)

    diagnostics_query = (
        "config_revision=cfg-empty-1"
        "&enabled_total=3"
        "&tagless_enabled=false"
        "&high_risk_count=1"
        "&has_warnings=true"
        "&recent_minutes=60"
    )
    response = client.get(
        f"/v1/router/diagnostics?{diagnostics_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/router/diagnostics",
            site_id="site_alpha",
            trace_id="tracestatsapi0042550000000000000",
            query=diagnostics_query,
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["source"] == "cloud_router_diagnostics_empty"
    assert payload["report"]["validation"]["enabled_total"] == 3
    assert payload["report"]["high_risk"]["count"] == 1
    assert payload["report"]["regressions"]["count"] == 0
    assert payload["report"]["regressions"]["items"] == []
    assert payload["report"]["quality_regressions"]["count"] == 0
    assert payload["report"]["quality_regressions"]["items"] == []

    dispose_engine(database_url)


def test_router_diagnostics_prefers_delivery_buffer_when_present(tmp_path: Path) -> None:
    database_url, client, _ = _build_client(tmp_path)

    UsageRollupService(database_url).store_router_diagnostics_batches(
        site_ids=["site_alpha"],
        recent_minutes=60,
        config_revision="buffer-config",
    )

    diagnostics_query = (
        "config_revision=cfg-buffer-1"
        "&enabled_total=7"
        "&tagless_enabled=true"
        "&high_risk_count=2"
        "&has_warnings=true"
        "&recent_minutes=60"
    )
    response = client.get(
        f"/v1/router/diagnostics?{diagnostics_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/router/diagnostics",
            site_id="site_alpha",
            trace_id="tracestatsapi0042500000000000000",
            query=diagnostics_query,
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["delivery"]["owner"] == "wordpress_fetch_apply"
    assert payload["delivery"]["buffer_kind"] == "usage_rollup"
    assert payload["delivery"]["scope_kind"] == "router_diagnostics_batch"
    assert payload["config_revision"] == "cfg-buffer-1"
    assert payload["report"]["validation"]["enabled_total"] == 7
    assert payload["report"]["validation"]["tagless_enabled"] is True
    assert payload["report"]["validation"]["has_warnings"] is True
    assert payload["report"]["high_risk"]["count"] == 2
    assert payload["report"]["validation"]["checked_at"] > 0
    assert payload["report"]["regressions"]["count"] >= 1
    assert payload["report"]["quality_regressions"]["count"] >= 1

    dispose_engine(database_url)


def test_router_performance_snapshot_exposes_first_tranche_deferred_dimensions(
    tmp_path: Path,
) -> None:
    database_url, client, seeded_now = _build_client(tmp_path)

    projection_end = seeded_now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    projection_start = projection_end - timedelta(hours=24)
    UsageRollupService(
        database_url,
        now_factory=lambda: projection_end,
    ).store_router_performance_snapshot_batches(
        site_ids=["site_alpha"],
        start_at=projection_start,
        end_at=projection_end,
    )
    projection_query = (
        "start_gmt="
        + projection_start.strftime("%Y-%m-%d%%20%H:00:00")
        + "&end_gmt="
        + projection_end.strftime("%Y-%m-%d%%20%H:00:00")
    )
    response = client.get(
        f"/v1/router/performance-snapshot?{projection_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/router/performance-snapshot",
            site_id="site_alpha",
            trace_id="tracestatsapi0045000000000000000",
            query=projection_query,
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["source"] == "cloud_router_performance_snapshot"

    rows = payload["rows"]
    assert len(rows) >= 2
    preset_ids = {str(row["preset_id"]) for row in rows}
    assert "preset.alpha" in preset_ids
    assert "preset.beta" in preset_ids
    assert sum(int(row["guard_fail_total"]) for row in rows) >= 1
    assert sum(float(row["quality_sum"]) for row in rows) == sum(
        int(row["success_total"]) for row in rows
    )
    assert sum(int(row["quality_count"]) for row in rows) == sum(
        int(row["request_total"]) for row in rows
    )
    assert sum(float(row["reward_sum"]) for row in rows) == sum(
        int(row["success_total"]) for row in rows
    )
    assert sum(int(row["reward_count"]) for row in rows) == sum(
        int(row["request_total"]) for row in rows
    )

    dispose_engine(database_url)


def test_router_performance_snapshot_returns_bounded_empty_payload_when_delivery_buffer_is_absent(
    tmp_path: Path,
) -> None:
    database_url, client, seeded_now = _build_client(tmp_path)

    projection_end = seeded_now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    projection_start = projection_end - timedelta(hours=24)
    projection_query = (
        "start_gmt="
        + projection_start.strftime("%Y-%m-%d%%20%H:00:00")
        + "&end_gmt="
        + projection_end.strftime("%Y-%m-%d%%20%H:00:00")
    )
    response = client.get(
        f"/v1/router/performance-snapshot?{projection_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/router/performance-snapshot",
            site_id="site_alpha",
            trace_id="tracestatsapi0045500000000000000",
            query=projection_query,
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["source"] == "cloud_router_performance_snapshot_empty"
    assert payload["rows"] == []
    assert payload["window"]["start_gmt"] == projection_start.strftime("%Y-%m-%d %H:%M:%S")
    assert payload["window"]["end_gmt"] == projection_end.strftime("%Y-%m-%d %H:%M:%S")

    dispose_engine(database_url)


def test_router_performance_snapshot_prefers_delivery_buffer_when_present(
    tmp_path: Path,
) -> None:
    database_url, client, seeded_now = _build_client(tmp_path)

    projection_end = seeded_now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    projection_start = projection_end - timedelta(hours=24)
    UsageRollupService(
        database_url,
        now_factory=lambda: projection_end,
    ).store_router_performance_snapshot_batches(
        site_ids=["site_alpha"],
        start_at=projection_start,
        end_at=projection_end,
    )

    projection_query = (
        "start_gmt="
        + projection_start.strftime("%Y-%m-%d%%20%H:00:00")
        + "&end_gmt="
        + projection_end.strftime("%Y-%m-%d%%20%H:00:00")
    )
    response = client.get(
        f"/v1/router/performance-snapshot?{projection_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/router/performance-snapshot",
            site_id="site_alpha",
            trace_id="tracestatsapi0046000000000000000",
            query=projection_query,
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["source"] == "cloud_router_performance_snapshot"
    assert payload["delivery"]["owner"] == "wordpress_fetch_apply"
    assert payload["delivery"]["buffer_kind"] == "usage_rollup"
    assert payload["delivery"]["scope_kind"] == "router_performance_batch"
    assert payload["metric_sources"] == {
        "quality": "runtime_success_proxy",
        "reward": "runtime_success_proxy",
    }
    assert payload["apply_policy"] == {
        "snapshot_rows": True,
        "feedback_quality_writeback": False,
        "feedback_reward_writeback": False,
    }
    assert payload["deferred_truths"] == ["quality.feedback", "reward.feedback"]
    assert payload["window"]["start_gmt"] == projection_start.strftime("%Y-%m-%d %H:00:00")
    assert payload["window"]["end_gmt"] == projection_end.strftime("%Y-%m-%d %H:00:00")
    assert len(payload["rows"]) >= 1

    dispose_engine(database_url)


def test_stats_routes_reject_stale_timestamp(tmp_path: Path) -> None:
    database_url, client, _ = _build_client(tmp_path)
    response = client.get(
        "/v1/usage/summary",
        headers=build_auth_headers(
            "GET",
            "/v1/usage/summary",
            site_id="site_alpha",
            trace_id="tracestatsapi0040000000000000000",
            timestamp="1",
        ),
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.stale_timestamp"

    dispose_engine(database_url)


def test_stats_routes_reject_expired_key(tmp_path: Path) -> None:
    database_url, client, _ = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["stats:read"],
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    response = client.get(
        "/v1/usage/summary",
        headers=build_auth_headers(
            "GET",
            "/v1/usage/summary",
            site_id="site_alpha",
            trace_id="tracestatsapi0050000000000000000",
        ),
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.invalid_key"

    dispose_engine(database_url)


def test_stats_routes_accept_legacy_read_scope_alias(tmp_path: Path) -> None:
    database_url, client, _ = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["read"],
    )

    response = client.get(
        "/v1/usage/summary",
        headers=build_auth_headers(
            "GET",
            "/v1/usage/summary",
            site_id="site_alpha",
            trace_id="tracestatsapi0051000000000000000",
        ),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    dispose_engine(database_url)


def test_router_performance_projection_rejects_invalid_window(tmp_path: Path) -> None:
    database_url, client, _ = _build_client(tmp_path)
    query = "start_gmt=2026-03-24%2012:00:00&end_gmt=2026-03-24%2011:00:00"
    response = client.get(
        f"/v1/router/performance-snapshot?{query}",
        headers=build_auth_headers(
            "GET",
            "/v1/router/performance-snapshot",
            site_id="site_alpha",
            trace_id="tracestatsapi0060000000000000000",
            query=query,
        ),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "stats.invalid_projection_window"

    dispose_engine(database_url)
