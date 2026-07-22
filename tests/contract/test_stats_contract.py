from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    HealthSnapshot,
    ProviderCallRecord,
    ProviderConnection,
    RunRecord,
    RuntimeGuardEvent,
)
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from app.domain.runtime.models import RuntimeRequest
from app.domain.runtime.service import RuntimeService
from app.domain.usage.rollup import UsageRollupService
from tests.conftest import build_auth_headers, seed_site_auth


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'stats-contract.sqlite3'}"


def _seed_openai_model_allowlist(database_url: str) -> None:
    with get_session(database_url) as session:
        session.add(
            ProviderConnection(
                connection_id="openai",
                provider_type="openai_compatible",
                display_name="OpenAI",
                enabled=True,
                base_url="https://api.openai.test/v1",
                config_json={
                    "provider_id": "openai",
                    "kind": "openai_compatible",
                    "capability_ids": ["text_generation"],
                    "runtime_profile_ids": ["text.balanced"],
                    "model_ids": ["gpt-4.1-mini"],
                },
                secret_ciphertext="configured-in-test",
                status="ready",
                source_role="execution_source",
                metadata_json={},
            )
        )
        session.commit()


def test_stats_response_shapes_are_stable(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    _seed_openai_model_allowlist(database_url)
    CatalogService(database_url).scan_provider_health()
    seed_site_auth(database_url, site_id="site_contract", scopes=["stats:read"])

    runtime_result = RuntimeService(database_url).execute(
        RuntimeRequest(
            site_id="site_contract",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="stats-contract-run-a",
            trace_id="stats-contract-trace-a",
            input_payload={"messages": [{"role": "user", "content": "contract shape"}]},
        )
    )

    now = datetime.now(UTC)
    with get_session(database_url) as session:
        run = session.scalar(select(RunRecord).where(RunRecord.run_id == runtime_result.run_id))
        assert run is not None
        run.started_at = now - timedelta(minutes=10)
        run.finished_at = now - timedelta(minutes=10) + timedelta(milliseconds=90)

        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord)
                .where(ProviderCallRecord.run_id == runtime_result.run_id)
                .order_by(ProviderCallRecord.id.asc())
            )
        )
        for index, provider_call in enumerate(provider_calls):
            provider_call.created_at = run.started_at + timedelta(seconds=index + 1)
            provider_call.latency_ms = 90

        health_snapshots = list(
            session.scalars(select(HealthSnapshot).order_by(HealthSnapshot.id.asc()))
        )
        for health_snapshot in health_snapshots:
            health_snapshot.measured_at = now - timedelta(minutes=5)

        session.commit()

    probe_end = now.replace(second=0, microsecond=0)
    probe_start = probe_end - timedelta(minutes=15)
    UsageRollupService(database_url, now_factory=lambda: probe_end).store_latency_probe_batches(
        site_instances={"site_contract": ["openai-us-east-text-balanced"]},
        start_at=probe_start,
        end_at=probe_end,
    )

    projection_end = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    projection_start = projection_end - timedelta(hours=1)
    UsageRollupService(
        database_url, now_factory=lambda: projection_end
    ).store_router_performance_snapshot_batches(
        site_ids=["site_contract"],
        start_at=projection_start,
        end_at=projection_end,
    )

    UsageRollupService(database_url, now_factory=lambda: now).store_router_diagnostics_batches(
        site_ids=["site_contract"],
        recent_minutes=60,
        config_revision="stable-shape-buffer",
    )

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    instance_response = client.get(
        "/v1/stats/instances/openai-us-east-text-balanced",
        headers=build_auth_headers(
            "GET",
            "/v1/stats/instances/openai-us-east-text-balanced",
            site_id="site_contract",
            trace_id="tracecontractstats0010000000000000",
        ),
    )
    profile_response = client.get(
        "/v1/stats/profiles/text.balanced",
        headers=build_auth_headers(
            "GET",
            "/v1/stats/profiles/text.balanced",
            site_id="site_contract",
            trace_id="tracecontractstats0020000000000000",
        ),
    )
    hosted_discovery_response = client.get(
        "/v1/stats/hosted/discovery",
        headers=build_auth_headers(
            "GET",
            "/v1/stats/hosted/discovery",
            site_id="site_contract",
            trace_id="tracecontractstats0022000000000000",
        ),
    )
    hosted_profile_metadata_response = client.get(
        "/v1/stats/hosted/profiles/text.balanced/metadata",
        headers=build_auth_headers(
            "GET",
            "/v1/stats/hosted/profiles/text.balanced/metadata",
            site_id="site_contract",
            trace_id="tracecontractstats0023000000000000",
        ),
    )
    hosted_instance_metadata_response = client.get(
        "/v1/stats/hosted/instances/openai-us-east-text-balanced/metadata",
        headers=build_auth_headers(
            "GET",
            "/v1/stats/hosted/instances/openai-us-east-text-balanced/metadata",
            site_id="site_contract",
            trace_id="tracecontractstats0024000000000000",
        ),
    )
    usage_response = client.get(
        "/v1/usage/summary",
        headers=build_auth_headers(
            "GET",
            "/v1/usage/summary",
            site_id="site_contract",
            trace_id="tracecontractstats0030000000000000",
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
            site_id="site_contract",
            trace_id="tracecontractstats0040000000000000",
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
            site_id="site_contract",
            trace_id="tracecontractstats0050000000000000",
            query=alert_query,
        ),
    )
    diagnostics_query = (
        "config_revision=cfg-contract-1"
        "&enabled_total=5"
        "&tagless_enabled=false"
        "&high_risk_count=1"
        "&has_warnings=true"
        "&recent_minutes=60"
    )
    diagnostics_response = client.get(
        f"/v1/router/diagnostics?{diagnostics_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/router/diagnostics",
            site_id="site_contract",
            trace_id="tracecontractstats0060000000000000",
            query=diagnostics_query,
        ),
    )
    recommendation_response = client.get(
        f"/v1/router/recommendation?{diagnostics_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/router/recommendation",
            site_id="site_contract",
            trace_id="tracecontractstats0060500000000000",
            query=diagnostics_query,
        ),
    )
    logs_query = (
        "range=24h"
        "&start_gmt="
        + (now - timedelta(hours=1)).strftime("%Y-%m-%d%%20%H:%M:%S")
        + "&end_gmt="
        + now.strftime("%Y-%m-%d%%20%H:%M:%S")
        + "&status=all"
    )
    logs_summary_response = client.get(
        f"/v1/logs/analytics/summary?{logs_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/logs/analytics/summary",
            site_id="site_contract",
            trace_id="tracecontractstats0061000000000000",
            query=logs_query,
        ),
    )
    logs_latency_response = client.get(
        f"/v1/logs/analytics/tool-latency?{logs_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/logs/analytics/tool-latency",
            site_id="site_contract",
            trace_id="tracecontractstats0062000000000000",
            query=logs_query,
        ),
    )
    logs_recommendations_response = client.get(
        f"/v1/logs/analytics/recommendations?{logs_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/logs/analytics/recommendations",
            site_id="site_contract",
            trace_id="tracecontractstats0063000000000000",
            query=logs_query,
        ),
    )
    logs_mcp_zone_response = client.get(
        f"/v1/logs/analytics/mcp-zone?{logs_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/logs/analytics/mcp-zone",
            site_id="site_contract",
            trace_id="tracecontractstats0064000000000000",
            query=logs_query,
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
    assert logs_summary_response.status_code == 200
    assert logs_latency_response.status_code == 200
    assert logs_recommendations_response.status_code == 200
    assert logs_mcp_zone_response.status_code == 200

    instance_payload = instance_response.json()
    assert set(instance_payload.keys()) == {"status", "error_code", "message", "data", "meta"}
    assert set(instance_payload["data"].keys()) == {
        "status",
        "error",
        "source",
        "timezone",
        "generated_at",
        "instance_id",
        "provider_id",
        "model_id",
        "region",
        "endpoint_variant",
        "health_status",
        "health_reason",
        "health_measured_at",
        "health_score",
        "health_window_calls",
        "today_calls",
        "success_rate",
        "avg_latency_ms",
        "latency_ms_p50",
        "latency_ms_p95",
        "fallback_rate",
        "windows",
        "delivery",
    }
    assert set(instance_payload["data"]["windows"].keys()) == {"today", "rolling_24h"}
    assert set(instance_payload["data"]["windows"]["today"].keys()) == {
        "start_at",
        "end_at",
        "calls_total",
        "success_total",
        "error_total",
        "success_rate",
        "avg_latency_ms",
        "latency_ms_p50",
        "latency_ms_p95",
        "fallback_total",
        "fallback_rate",
        "last_seen_at",
    }

    profile_payload = profile_response.json()
    assert set(profile_payload["data"].keys()) == {
        "status",
        "error",
        "source",
        "timezone",
        "generated_at",
        "profile_id",
        "execution_kind",
        "candidate_instance_ids",
        "today_calls",
        "success_rate",
        "avg_latency_ms",
        "fallback_rate",
        "health",
        "windows",
    }
    assert set(profile_payload["data"]["health"].keys()) == {
        "providers_total",
        "instances_total",
        "healthy_total",
        "degraded_total",
        "unhealthy_total",
        "unknown_total",
        "avg_score",
        "min_score",
        "scored_instances_total",
        "last_measured_at",
    }

    hosted_discovery_payload = hosted_discovery_response.json()
    assert set(hosted_discovery_payload["data"].keys()) == {
        "source",
        "site_id",
        "timezone",
        "generated_at",
        "profiles",
        "instances",
    }

    hosted_profile_metadata_payload = hosted_profile_metadata_response.json()
    assert set(hosted_profile_metadata_payload["data"].keys()) == {
        "source",
        "site_id",
        "timezone",
        "generated_at",
        "profile_id",
        "execution_kind",
        "candidate_total",
        "candidate_instance_ids",
        "provider_ids",
        "capability_tags",
        "pricing",
        "candidates",
    }
    assert set(hosted_profile_metadata_payload["data"]["pricing"].keys()) == {
        "source",
        "unit",
        "input_min",
        "input_max",
        "output_min",
        "output_max",
    }
    if hosted_profile_metadata_payload["data"]["candidates"]:
        assert set(hosted_profile_metadata_payload["data"]["candidates"][0].keys()) == {
            "instance_id",
            "provider_id",
            "model_id",
            "region",
            "endpoint_variant",
            "health_status",
            "capability_tags",
            "price_input",
            "price_output",
            "revision",
            "updated_at",
        }

    hosted_instance_metadata_payload = hosted_instance_metadata_response.json()
    assert set(hosted_instance_metadata_payload["data"].keys()) == {
        "source",
        "site_id",
        "timezone",
        "generated_at",
        "instance_id",
        "provider_id",
        "model_id",
        "region",
        "endpoint_variant",
        "health_status",
        "capability_tags",
        "price_input",
        "price_output",
        "revision",
        "updated_at",
    }

    usage_payload = usage_response.json()
    assert set(usage_payload["data"].keys()) == {
        "timezone",
        "generated_at",
        "totals",
        "windows",
        "health",
    }
    assert set(usage_payload["data"]["health"].keys()) == {
        "providers_total",
        "instances_total",
        "healthy_total",
        "degraded_total",
        "unhealthy_total",
        "unknown_total",
        "avg_score",
        "min_score",
        "scored_instances_total",
        "last_measured_at",
    }
    assert set(usage_payload["data"]["windows"]["today"].keys()) == {
        "start_at",
        "end_at",
        "runs_total",
        "provider_calls_total",
        "success_total",
        "error_total",
        "success_rate",
        "avg_latency_ms",
        "latency_ms_p50",
        "latency_ms_p95",
        "fallback_total",
        "fallback_rate",
        "tokens_in_total",
        "tokens_out_total",
        "cost_total",
        "active_sites_total",
        "last_seen_at",
    }

    projection_payload = projection_response.json()
    assert set(projection_payload["data"].keys()) == {
        "source",
        "site_id",
        "generated_at",
        "metric_sources",
        "apply_policy",
        "deferred_truths",
        "window",
        "cursor",
        "rows",
        "delivery",
    }
    assert set(projection_payload["data"]["metric_sources"].keys()) == {
        "quality",
        "reward",
    }
    assert set(projection_payload["data"]["apply_policy"].keys()) == {
        "snapshot_rows",
        "feedback_quality_writeback",
        "feedback_reward_writeback",
    }
    assert set(projection_payload["data"]["window"].keys()) == {"start_gmt", "end_gmt"}
    assert set(projection_payload["data"]["cursor"].keys()) == {
        "previous_end_gmt",
        "next_end_gmt",
    }
    assert set(projection_payload["data"]["delivery"].keys()) == {
        "owner",
        "buffer_kind",
        "scope_kind",
    }
    if projection_payload["data"]["rows"]:
        assert set(projection_payload["data"]["rows"][0].keys()) == {
            "bucket_gmt",
            "ability_id",
            "caller_id",
            "preset_id",
            "router_instance_id",
            "selected_model_instance_id",
            "request_total",
            "success_total",
            "guard_fail_total",
            "quality_sum",
            "quality_count",
            "reward_sum",
            "reward_count",
            "avg_latency_ms",
        }

    alert_payload = alert_response.json()
    assert set(alert_payload["data"].keys()) == {
        "source",
        "site_id",
        "generated_at",
        "window",
        "touched_rule_types",
        "events",
    }
    assert set(alert_payload["data"]["window"].keys()) == {"start_gmt", "end_gmt"}
    assert alert_payload["data"]["touched_rule_types"] == ["provider_degradation"]
    assert set(alert_payload["data"]["events"][0].keys()) == {
        "rule_type",
        "fingerprint",
        "status",
        "summary",
        "context",
        "channels",
    }
    assert set(alert_payload["data"]["events"][0]["summary"].keys()) == {
        "provider",
        "window_minutes",
        "total",
        "errors",
        "error_rate",
        "avg_latency_ms",
        "error_rate_threshold",
        "latency_ms_threshold",
        "source",
    }
    assert set(alert_payload["data"]["events"][0]["context"].keys()) == {
        "provider",
        "window_minutes",
        "total",
        "errors",
        "error_rate",
        "avg_latency_ms",
        "error_rate_threshold",
        "latency_ms_threshold",
        "healthy_instances_total",
        "degraded_instances_total",
        "unhealthy_instances_total",
        "unknown_instances_total",
        "last_measured_at",
        "source",
    }
    assert set(alert_payload["data"]["events"][0]["channels"].keys()) == {
        "email",
        "webhook",
        "log",
    }

    diagnostics_payload = diagnostics_response.json()
    assert set(diagnostics_payload["data"].keys()) == {
        "source",
        "site_id",
        "generated_at",
        "config_revision",
        "stale_after_gmt",
        "report",
        "delivery",
    }
    assert set(diagnostics_payload["data"]["report"].keys()) == {
        "validation",
        "high_risk",
        "regressions",
        "quality_regressions",
    }
    assert set(diagnostics_payload["data"]["report"]["validation"].keys()) == {
        "checked_at",
        "source",
        "tagless_enabled",
        "enabled_total",
        "has_warnings",
    }
    assert set(diagnostics_payload["data"]["report"]["high_risk"].keys()) == {"count"}
    assert set(diagnostics_payload["data"]["report"]["regressions"].keys()) == {
        "count",
        "passed",
        "failed",
        "items",
    }
    assert set(diagnostics_payload["data"]["report"]["quality_regressions"].keys()) == {
        "enabled",
        "count",
        "passed",
        "failed",
        "reason",
        "items",
    }
    if diagnostics_payload["data"]["report"]["regressions"]["items"]:
        assert set(diagnostics_payload["data"]["report"]["regressions"]["items"][0].keys()) == {
            "kind",
            "label",
            "run_id",
            "status",
            "callback_status",
            "event_code",
            "count",
            "summary",
            "last_seen_at",
        }
    if diagnostics_payload["data"]["report"]["quality_regressions"]["items"]:
        assert set(
            diagnostics_payload["data"]["report"]["quality_regressions"]["items"][0].keys()
        ) == {
            "kind",
            "label",
            "run_id",
            "status",
            "callback_status",
            "event_code",
            "count",
            "summary",
            "last_seen_at",
        }

    recommendation_payload = recommendation_response.json()
    assert set(recommendation_payload["data"].keys()) == {
        "source",
        "site_id",
        "timezone",
        "generated_at",
        "recommended_provider_ids",
        "recommended_profile_ids",
        "avoid_provider_ids",
        "avoid_profile_ids",
        "recommended_error_codes",
        "summary_lines",
        "evidence",
    }
    assert set(recommendation_payload["data"]["evidence"].keys()) == {
        "provider_alerts",
        "profile_matches",
    }

    logs_summary_payload = logs_summary_response.json()
    assert set(logs_summary_payload["data"].keys()) == {
        "source",
        "site_id",
        "generated_at",
        "updated_at",
        "total",
        "success",
        "error",
        "error_only",
        "timeout",
        "blocked",
        "canceled",
        "success_rate",
        "error_rate",
        "timeout_rate",
        "blocked_rate",
        "canceled_rate",
        "avg_elapsed_ms",
        "p50_elapsed_ms",
        "p95_elapsed_ms",
        "latency_samples",
        "tool_latency_p50_ms",
        "tool_latency_p95_ms",
        "tool_latency_samples",
        "tool_latency_source",
        "top_errors",
        "trend_7d",
        "status_distribution",
    }
    assert set(logs_summary_payload["data"]["status_distribution"].keys()) == {
        "total",
        "success",
        "error",
        "timeout",
        "blocked",
        "canceled",
    }
    assert set(logs_summary_payload["data"]["trend_7d"][0].keys()) == {
        "label",
        "total",
        "success",
        "error",
    }

    logs_latency_payload = logs_latency_response.json()
    assert set(logs_latency_payload["data"].keys()) == {
        "source",
        "site_id",
        "generated_at",
        "p50_ms",
        "p95_ms",
        "samples",
    }

    logs_recommendations_payload = logs_recommendations_response.json()
    assert set(logs_recommendations_payload["data"].keys()) == {
        "source",
        "site_id",
        "generated_at",
        "recommended_providers",
        "recommended_error_codes",
        "providers",
        "error_codes",
    }

    logs_mcp_zone_payload = logs_mcp_zone_response.json()
    assert set(logs_mcp_zone_payload["data"].keys()) == {
        "window",
        "calls_total",
        "failed_total",
        "blocked_total",
        "top_abilities",
        "top_error_codes",
        "server_options",
        "app_options",
        "caller_options",
        "filters",
        "source",
        "generated_at",
    }
    assert set(logs_mcp_zone_payload["data"]["filters"].keys()) == {
        "mcp_server_id",
        "app_id",
        "caller_id",
    }

    dispose_engine(database_url)


def test_instance_stats_contract_exposes_latency_probe_delivery_buffer_metadata(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    _seed_openai_model_allowlist(database_url)
    CatalogService(database_url).scan_provider_health()
    seed_site_auth(database_url, site_id="site_contract", scopes=["stats:read"])

    runtime_result = RuntimeService(database_url).execute(
        RuntimeRequest(
            site_id="site_contract",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="stats-contract-latency-buffer-a",
            trace_id="stats-contract-latency-buffer-a",
            input_payload={"messages": [{"role": "user", "content": "latency buffer"}]},
        )
    )

    probe_end = datetime(2026, 3, 24, 9, 20, tzinfo=UTC)
    probe_start = probe_end - timedelta(minutes=15)
    with get_session(database_url) as session:
        run = session.scalar(select(RunRecord).where(RunRecord.run_id == runtime_result.run_id))
        assert run is not None
        run.started_at = probe_start + timedelta(minutes=5)
        run.finished_at = probe_start + timedelta(minutes=5, milliseconds=90)

        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord)
                .where(ProviderCallRecord.run_id == runtime_result.run_id)
                .order_by(ProviderCallRecord.id.asc())
            )
        )
        for index, provider_call in enumerate(provider_calls):
            provider_call.created_at = run.started_at + timedelta(seconds=index + 1)

        health_snapshots = list(
            session.scalars(select(HealthSnapshot).order_by(HealthSnapshot.id.asc()))
        )
        for health_snapshot in health_snapshots:
            health_snapshot.measured_at = probe_end - timedelta(minutes=2)

        session.commit()

    UsageRollupService(database_url, now_factory=lambda: probe_end).store_latency_probe_batches(
        site_instances={"site_contract": ["openai-us-east-text-balanced"]},
        start_at=probe_start,
        end_at=probe_end,
    )

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    response = client.get(
        "/v1/stats/instances/openai-us-east-text-balanced",
        headers=build_auth_headers(
            "GET",
            "/v1/stats/instances/openai-us-east-text-balanced",
            site_id="site_contract",
            trace_id="tracecontractstats0015000000000000",
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["source"] == "cloud_latency_probe_buffer"
    assert payload["delivery"] == {
        "owner": "wordpress_fetch_apply",
        "buffer_kind": "usage_rollup",
        "scope_kind": "latency_probe_batch",
    }
    assert payload["windows"]["today"]["start_at"] == probe_start.strftime("%Y-%m-%d %H:%M:%S")
    assert payload["windows"]["today"]["end_at"] == probe_end.strftime("%Y-%m-%d %H:%M:%S")
    assert payload["today_calls"] >= 1
    assert payload["avg_latency_ms"] >= 0

    dispose_engine(database_url)


def test_alert_provider_degradation_contract_exposes_delivery_buffer_metadata(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    _seed_openai_model_allowlist(database_url)
    CatalogService(database_url).scan_provider_health()
    seed_site_auth(database_url, site_id="site_contract", scopes=["stats:read"])

    runtime_result = RuntimeService(database_url).execute(
        RuntimeRequest(
            site_id="site_contract",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="stats-contract-alert-buffer-a",
            trace_id="stats-contract-alert-buffer-a",
            input_payload={"messages": [{"role": "user", "content": "alert buffer"}]},
        )
    )

    now = datetime.now(UTC)
    with get_session(database_url) as session:
        run = session.scalar(select(RunRecord).where(RunRecord.run_id == runtime_result.run_id))
        assert run is not None
        run.started_at = now - timedelta(minutes=10)
        run.finished_at = now - timedelta(minutes=10) + timedelta(milliseconds=90)

        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord)
                .where(ProviderCallRecord.run_id == runtime_result.run_id)
                .order_by(ProviderCallRecord.id.asc())
            )
        )
        for index, provider_call in enumerate(provider_calls):
            provider_call.created_at = run.started_at + timedelta(seconds=index + 1)
            if index == 0:
                provider_call.error_code = "quota.rate_limited"

        health_snapshots = list(
            session.scalars(select(HealthSnapshot).order_by(HealthSnapshot.id.asc()))
        )
        for health_snapshot in health_snapshots:
            health_snapshot.measured_at = now - timedelta(minutes=5)

        session.commit()

    UsageRollupService(
        database_url, now_factory=lambda: now
    ).store_alert_provider_degradation_batches(
        site_ids=["site_contract"],
        window_minutes=30,
        min_requests=1,
        error_rate_threshold=0.25,
        latency_ms_threshold=1,
    )

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    alert_query = (
        "window_minutes=30&min_requests=1&error_rate_threshold=0.25&latency_ms_threshold=1"
    )
    response = client.get(
        f"/v1/alerts/provider-degradation?{alert_query}",
        headers=build_auth_headers(
            "GET",
            "/v1/alerts/provider-degradation",
            site_id="site_contract",
            trace_id="tracecontractstats0055000000000000",
            query=alert_query,
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["delivery"] == {
        "owner": "wordpress_fetch_apply",
        "buffer_kind": "usage_rollup",
        "scope_kind": "alert_evaluate_batch",
    }
    assert payload["touched_rule_types"] == ["provider_degradation"]
    assert len(payload["events"]) == 1
    assert payload["events"][0]["rule_type"] == "provider_degradation"

    dispose_engine(database_url)


def test_router_diagnostics_contract_exposes_case_detail_shape(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    _seed_openai_model_allowlist(database_url)
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
            idempotency_key="stats-contract-diag-a",
            trace_id="stats-contract-diag-trace-a",
            input_payload={"messages": [{"role": "user", "content": "diag details"}]},
        )
    )
    run_b = runtime_service.execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="stats-contract-diag-b",
            trace_id="stats-contract-diag-trace-b",
            input_payload={"messages": [{"role": "user", "content": "diag due"}]},
        )
    )

    now = datetime.now(UTC)
    with get_session(database_url) as session:
        first_run = session.scalar(select(RunRecord).where(RunRecord.run_id == run_a.run_id))
        second_run = session.scalar(select(RunRecord).where(RunRecord.run_id == run_b.run_id))
        assert first_run is not None
        assert second_run is not None

        first_run.started_at = now - timedelta(minutes=20)
        first_run.finished_at = now - timedelta(minutes=19)
        first_run.policy_json = {"callback_url": "https://callbacks.example.test/runtime"}
        first_run.callback_status = "failed"
        first_run.callback_last_attempt_at = now - timedelta(minutes=4)
        first_run.error_code = "callback.failed"

        second_run.started_at = now - timedelta(minutes=18)
        second_run.finished_at = now - timedelta(minutes=17)
        second_run.policy_json = {"callback_url": "https://callbacks.example.test/runtime"}
        second_run.callback_status = "pending"
        second_run.callback_next_attempt_at = now - timedelta(minutes=3)

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
                trace_id="trace-guard-contract-1",
                payload_json={"reason": "synthetic"},
                created_at=now - timedelta(minutes=2),
            )
        )
        session.commit()

    UsageRollupService(database_url, now_factory=lambda: now).store_router_diagnostics_batches(
        site_ids=["site_alpha"],
        recent_minutes=60,
        config_revision="contract-case-details",
    )

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    diagnostics_query = (
        "config_revision=cfg-contract-details"
        "&enabled_total=5"
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
            trace_id="tracecontractstats0070000000000000",
            query=diagnostics_query,
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert set(payload["report"]["regressions"]["items"][0].keys()) == {
        "kind",
        "label",
        "run_id",
        "status",
        "callback_status",
        "event_code",
        "count",
        "summary",
        "last_seen_at",
        "details",
    }
    assert set(payload["report"]["regressions"]["items"][0]["details"].keys()) == {
        "ability_name",
        "channel",
        "profile_id",
        "execution_kind",
        "selected_provider_id",
        "selected_instance_id",
        "error_code",
        "error_message",
        "callback_last_error_code",
        "callback_last_error_message",
        "started_at",
        "finished_at",
    }
    assert set(payload["report"]["quality_regressions"]["items"][1]["details"].keys()) == {
        "auth_surface",
        "scope_kind",
        "scope_id",
        "status_code",
        "method",
        "path",
        "trace_id",
        "client_ref",
        "key_id",
    }
    assert set(payload["report"]["quality_regressions"]["items"][0].keys()) == {
        "kind",
        "label",
        "run_id",
        "status",
        "callback_status",
        "event_code",
        "count",
        "summary",
        "last_seen_at",
        "details",
    }

    dispose_engine(database_url)


def test_router_diagnostics_contract_exposes_delivery_buffer_metadata(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    _seed_openai_model_allowlist(database_url)
    CatalogService(database_url).scan_provider_health()
    seed_site_auth(database_url, site_id="site_alpha", scopes=["stats:read"])

    runtime_service = RuntimeService(database_url)
    run = runtime_service.execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="stats-contract-diag-buffer-a",
            trace_id="stats-contract-diag-buffer-a",
            input_payload={"messages": [{"role": "user", "content": "diag buffer"}]},
        )
    )

    now = datetime.now(UTC)
    with get_session(database_url) as session:
        row = session.scalar(select(RunRecord).where(RunRecord.run_id == run.run_id))
        assert row is not None
        row.started_at = now - timedelta(minutes=15)
        row.finished_at = now - timedelta(minutes=15) + timedelta(milliseconds=120)
        row.policy_json = {"callback_url": "https://callbacks.example.test/runtime"}
        row.callback_status = "failed"
        row.callback_last_attempt_at = now - timedelta(minutes=3)
        row.error_code = "callback.failed"
        session.commit()

    UsageRollupService(database_url, now_factory=lambda: now).store_router_diagnostics_batches(
        site_ids=["site_alpha"],
        recent_minutes=60,
        config_revision="buffer-config",
    )

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    diagnostics_query = (
        "config_revision=cfg-contract-buffer"
        "&enabled_total=5"
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
            trace_id="tracecontractstats0075000000000000",
            query=diagnostics_query,
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["delivery"] == {
        "owner": "wordpress_fetch_apply",
        "buffer_kind": "usage_rollup",
        "scope_kind": "router_diagnostics_batch",
    }
    assert payload["config_revision"] == "cfg-contract-buffer"
    assert payload["report"]["validation"]["enabled_total"] == 5
    assert payload["report"]["validation"]["tagless_enabled"] is False
    assert payload["report"]["validation"]["has_warnings"] is True
    assert payload["report"]["high_risk"]["count"] == 1
    assert payload["report"]["regressions"]["items"]

    dispose_engine(database_url)


def test_router_performance_snapshot_contract_exposes_first_tranche_dimensions(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    _seed_openai_model_allowlist(database_url)
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
            idempotency_key="stats-contract-performance-a",
            trace_id="stats-contract-performance-a",
            input_payload={"messages": [{"role": "user", "content": "projection a"}]},
            policy={"preset_id": "preset.alpha"},
        )
    )
    run_b = runtime_service.execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="stats-contract-performance-b",
            trace_id="stats-contract-performance-b",
            input_payload={
                "messages": [{"role": "user", "content": "projection b"}],
                "simulate_error_for_instances": [
                    "openai-us-east-text-balanced",
                ],
                "router_preset_id": "preset.beta",
            },
            policy={"allow_fallback": True},
        )
    )

    now = datetime.now(UTC)
    with get_session(database_url) as session:
        run_specs = {
            run_a.run_id: {
                "started_at": now - timedelta(minutes=30),
                "finished_at": now - timedelta(minutes=30) + timedelta(milliseconds=90),
                "preset_id": "preset.alpha",
            },
            run_b.run_id: {
                "started_at": now - timedelta(minutes=20),
                "finished_at": now - timedelta(minutes=20) + timedelta(milliseconds=180),
                "preset_id": "preset.beta",
            },
        }

        for run_id, spec in run_specs.items():
            run = session.scalar(select(RunRecord).where(RunRecord.run_id == run_id))
            assert run is not None
            run.started_at = spec["started_at"]
            run.finished_at = spec["finished_at"]
            run.policy_json = {"preset_id": spec["preset_id"]}

            provider_calls = list(
                session.scalars(
                    select(ProviderCallRecord)
                    .where(ProviderCallRecord.run_id == run_id)
                    .order_by(ProviderCallRecord.id.asc())
                )
            )
            for index, provider_call in enumerate(provider_calls):
                provider_call.created_at = spec["started_at"] + timedelta(seconds=index + 1)
                if run_id == run_b.run_id and index == 0:
                    provider_call.error_code = "quota.rate_limited"

        session.commit()

    projection_end = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    projection_start = projection_end - timedelta(hours=24)
    UsageRollupService(
        database_url, now_factory=lambda: projection_end
    ).store_router_performance_snapshot_batches(
        site_ids=["site_alpha"],
        start_at=projection_start,
        end_at=projection_end,
    )

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

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
            trace_id="tracecontractstats0080000000000000",
            query=projection_query,
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    rows = payload["rows"]
    assert rows
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
    assert {"preset.alpha", "preset.beta"}.issubset({str(row["preset_id"]) for row in rows})
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


def test_router_performance_projection_contract_exposes_delivery_buffer_metadata(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    _seed_openai_model_allowlist(database_url)
    CatalogService(database_url).scan_provider_health()
    seed_site_auth(database_url, site_id="site_contract", scopes=["stats:read"])

    runtime_result = RuntimeService(database_url).execute(
        RuntimeRequest(
            site_id="site_contract",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="stats-contract-buffer-a",
            trace_id="stats-contract-buffer-a",
            input_payload={"messages": [{"role": "user", "content": "buffer shape"}]},
            policy={"preset_id": "preset.buffer"},
        )
    )

    now = datetime.now(UTC)
    projection_end = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    projection_start = projection_end - timedelta(hours=1)
    with get_session(database_url) as session:
        run = session.scalar(select(RunRecord).where(RunRecord.run_id == runtime_result.run_id))
        assert run is not None
        run.started_at = projection_start + timedelta(minutes=10)
        run.finished_at = projection_start + timedelta(minutes=10, milliseconds=90)
        run.policy_json = {"preset_id": "preset.buffer"}

        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord)
                .where(ProviderCallRecord.run_id == runtime_result.run_id)
                .order_by(ProviderCallRecord.id.asc())
            )
        )
        for index, provider_call in enumerate(provider_calls):
            provider_call.created_at = run.started_at + timedelta(seconds=index + 1)

        session.commit()

    UsageRollupService(
        database_url, now_factory=lambda: projection_end
    ).store_router_performance_snapshot_batches(
        site_ids=["site_contract"],
        start_at=projection_start,
        end_at=projection_end,
    )

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

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
            site_id="site_contract",
            trace_id="tracecontractstats0090000000000000",
            query=projection_query,
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["delivery"] == {
        "owner": "wordpress_fetch_apply",
        "buffer_kind": "usage_rollup",
        "scope_kind": "router_performance_batch",
    }
    assert payload["window"]["start_gmt"] == projection_start.strftime("%Y-%m-%d %H:00:00")
    assert payload["window"]["end_gmt"] == projection_end.strftime("%Y-%m-%d %H:00:00")
    assert payload["rows"]

    dispose_engine(database_url)
