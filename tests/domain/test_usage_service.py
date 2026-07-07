from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.adapters.providers.openai import OpenAIProviderAdapter
from app.adapters.repositories.stats_repository import StatsRepository
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import HealthSnapshot, ProviderCallRecord, RunRecord
from app.domain.catalog.service import CatalogService
from app.domain.runtime.models import RuntimeRequest
from app.domain.runtime.service import RuntimeService
from app.domain.usage.service import UsageService
from tests.conftest import seed_openai_model_allowlist, seed_site_auth


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'usage-domain.sqlite3'}"


def _seed_runtime_activity(database_url: str, now: datetime) -> None:
    providers = {"openai": OpenAIProviderAdapter()}
    catalog_service = CatalogService(database_url, providers=providers)
    catalog_service.refresh_catalog()
    seed_openai_model_allowlist(database_url)
    catalog_service.scan_provider_health()
    seed_site_auth(database_url, site_id="site_alpha")

    runtime_service = RuntimeService(database_url, providers=providers)
    run_a = runtime_service.execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="usage-domain-run-a",
            trace_id="usage-domain-trace-a",
            input_payload={"messages": [{"role": "user", "content": "direct success"}]},
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
            idempotency_key="usage-domain-run-b",
            trace_id="usage-domain-trace-b",
            input_payload={
                "messages": [{"role": "user", "content": "fallback success"}],
                "simulate_error_for_instances": [
                    "openai-us-east-text-balanced",
                ],
                "router_preset_id": "preset.beta",
            },
            policy={"allow_fallback": True},
        )
    )
    run_c = runtime_service.execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="usage-domain-run-c",
            trace_id="usage-domain-trace-c",
            input_payload={"messages": [{"role": "user", "content": "rolling only"}]},
        )
    )

    with get_session(database_url) as session:
        run_specs = {
            run_a.run_id: {
                "started_at": now - timedelta(hours=1),
                "finished_at": now - timedelta(hours=1) + timedelta(milliseconds=90),
                "call_times": [
                    now - timedelta(hours=1) + timedelta(seconds=1),
                ],
            },
            run_b.run_id: {
                "started_at": now - timedelta(minutes=40),
                "finished_at": now - timedelta(minutes=40) + timedelta(milliseconds=180),
                "call_times": [
                    now - timedelta(minutes=40) + timedelta(seconds=1),
                    now - timedelta(minutes=40) + timedelta(seconds=2),
                ],
            },
            run_c.run_id: {
                "started_at": datetime(2026, 3, 11, 23, 30, tzinfo=UTC),
                "finished_at": datetime(2026, 3, 11, 23, 30, tzinfo=UTC)
                + timedelta(milliseconds=120),
                "call_times": [
                    datetime(2026, 3, 11, 23, 30, 1, tzinfo=UTC),
                ],
            },
        }

        for run_id, spec in run_specs.items():
            run = session.scalar(select(RunRecord).where(RunRecord.run_id == run_id))
            assert run is not None
            run.started_at = spec["started_at"]
            run.finished_at = spec["finished_at"]
            if run_id == run_a.run_id:
                run.policy_json = {"preset_id": "preset.alpha"}
            if run_id == run_b.run_id:
                run.policy_json = {"router_preset_id": "preset.beta"}

            provider_calls = list(
                session.scalars(
                    select(ProviderCallRecord)
                    .where(ProviderCallRecord.run_id == run_id)
                    .order_by(ProviderCallRecord.id.asc())
                )
            )
            for index, provider_call in enumerate(provider_calls):
                provider_call.created_at = spec["call_times"][index]
                if run_id == run_a.run_id:
                    provider_call.latency_ms = 60
                if run_id == run_b.run_id and index == 0:
                    provider_call.error_code = "quota.rate_limited"
                    provider_call.latency_ms = 100
                elif run_id == run_b.run_id and index == 1:
                    provider_call.latency_ms = 140
                elif run_id == run_c.run_id:
                    provider_call.latency_ms = 150

        health_snapshots = list(
            session.scalars(select(HealthSnapshot).order_by(HealthSnapshot.id.asc()))
        )
        for health_snapshot in health_snapshots:
            health_snapshot.measured_at = now - timedelta(minutes=5)

        session.commit()


def test_usage_service_aggregates_instance_profile_and_summary_windows(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    fixed_now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    _seed_runtime_activity(database_url, fixed_now)

    service = UsageService(database_url, now_factory=lambda: fixed_now)
    instance_stats = service.get_instance_stats("openai-us-east-text-balanced")
    profile_stats = service.get_profile_stats("text.balanced")
    usage_summary = service.get_usage_summary()

    assert instance_stats["today_calls"] == 2
    assert instance_stats["success_rate"] == 0.5
    assert instance_stats["latency_ms_p50"] == 60
    assert instance_stats["latency_ms_p95"] == 100
    assert instance_stats["windows"]["today"]["latency_ms_p50"] == 60
    assert instance_stats["windows"]["today"]["latency_ms_p95"] == 100
    assert instance_stats["windows"]["rolling_24h"]["calls_total"] == 3
    assert instance_stats["windows"]["rolling_24h"]["success_total"] == 2
    assert instance_stats["windows"]["rolling_24h"]["latency_ms_p50"] == 100
    assert instance_stats["windows"]["rolling_24h"]["latency_ms_p95"] == 150
    assert instance_stats["health_status"] == "healthy"
    assert instance_stats["health_score"] == 0.6667
    assert instance_stats["health_window_calls"] == 3

    assert profile_stats["today_calls"] == 2
    assert profile_stats["success_rate"] == 1.0
    assert profile_stats["fallback_rate"] == 0.5
    assert profile_stats["windows"]["rolling_24h"]["calls_total"] == 3
    assert profile_stats["windows"]["rolling_24h"]["fallback_rate"] == 0.3333
    assert profile_stats["health"]["healthy_total"] == 3
    assert profile_stats["health"]["avg_score"] == 0.8889
    assert profile_stats["health"]["scored_instances_total"] == 3

    assert usage_summary["windows"]["today"]["runs_total"] == 2
    assert usage_summary["windows"]["today"]["provider_calls_total"] == 3
    assert usage_summary["windows"]["rolling_24h"]["runs_total"] == 3
    assert usage_summary["windows"]["rolling_24h"]["provider_calls_total"] == 4
    assert usage_summary["health"]["instances_total"] == 6
    assert usage_summary["health"]["healthy_total"] == 6
    assert usage_summary["health"]["avg_score"] == 0.9444

    dispose_engine(database_url)

def test_usage_service_window_aggregations_avoid_full_history_list_scans(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    fixed_now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    _seed_runtime_activity(database_url, fixed_now)

    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("full-history list scan should not be used for window aggregation")

    original_list_provider_calls = StatsRepository.list_provider_calls
    original_list_provider_calls_for_instance = StatsRepository.list_provider_calls_for_instance
    original_list_provider_calls_for_instances = StatsRepository.list_provider_calls_for_instances

    def guarded_list_provider_calls(self, site_id=None, *, start_at=None, end_at=None):
        assert start_at is not None
        assert end_at is not None
        return original_list_provider_calls(self, site_id, start_at=start_at, end_at=end_at)

    def guarded_list_provider_calls_for_instance(
        self,
        instance_id,
        site_id=None,
        *,
        start_at=None,
        end_at=None,
    ):
        assert start_at is not None
        assert end_at is not None
        return original_list_provider_calls_for_instance(
            self,
            instance_id,
            site_id,
            start_at=start_at,
            end_at=end_at,
        )

    def guarded_list_provider_calls_for_instances(
        self,
        instance_ids,
        site_id=None,
        *,
        start_at=None,
        end_at=None,
    ):
        assert start_at is not None
        assert end_at is not None
        return original_list_provider_calls_for_instances(
            self,
            instance_ids,
            site_id,
            start_at=start_at,
            end_at=end_at,
        )

    monkeypatch.setattr(StatsRepository, "list_runs", fail_if_called)
    monkeypatch.setattr(StatsRepository, "list_runs_for_profile", fail_if_called)
    monkeypatch.setattr(StatsRepository, "list_provider_calls", guarded_list_provider_calls)
    monkeypatch.setattr(
        StatsRepository,
        "list_provider_calls_for_instance",
        guarded_list_provider_calls_for_instance,
    )
    monkeypatch.setattr(
        StatsRepository,
        "list_provider_calls_for_instances",
        guarded_list_provider_calls_for_instances,
    )

    service = UsageService(database_url, now_factory=lambda: fixed_now)
    instance_stats = service.get_instance_stats("openai-us-east-text-balanced")
    profile_stats = service.get_profile_stats("text.balanced")
    usage_summary = service.get_usage_summary()

    assert instance_stats["windows"]["today"]["calls_total"] == 2
    assert profile_stats["windows"]["today"]["calls_total"] == 2
    assert usage_summary["windows"]["rolling_24h"]["provider_calls_total"] == 4

    dispose_engine(database_url)


def test_usage_service_builds_router_performance_snapshot_projection(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    fixed_now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    _seed_runtime_activity(database_url, fixed_now)

    service = UsageService(database_url, now_factory=lambda: fixed_now)
    payload = service.get_router_performance_snapshot_projection(
        site_id="site_alpha",
        start_at=datetime(2026, 3, 12, 7, 0, tzinfo=UTC),
        end_at=datetime(2026, 3, 12, 8, 0, tzinfo=UTC),
    )

    assert payload["source"] == "cloud_router_performance_snapshot"
    assert payload["site_id"] == "site_alpha"
    assert payload["window"]["start_gmt"] == "2026-03-12 07:00:00"
    assert payload["window"]["end_gmt"] == "2026-03-12 08:00:00"
    assert payload["cursor"]["previous_end_gmt"] == "2026-03-12 07:00:00"
    assert payload["cursor"]["next_end_gmt"] == "2026-03-12 08:00:00"
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
    assert len(payload["rows"]) == 2

    rows = payload["rows"]
    assert all(row["bucket_gmt"] == "2026-03-12 07:00:00" for row in rows)
    assert all(
        row["ability_id"] == "npcink-abilities-toolkit/build-article-block-plan" for row in rows
    )
    assert all(row["caller_id"] == "openapi" for row in rows)
    assert {"preset.alpha", "preset.beta"} == {str(row["preset_id"]) for row in rows}
    assert sum(int(row["guard_fail_total"]) for row in rows) == 1
    assert sum(float(row["quality_sum"]) for row in rows) == 2.0
    assert sum(int(row["quality_count"]) for row in rows) == 3
    assert sum(float(row["reward_sum"]) for row in rows) == 2.0
    assert sum(int(row["reward_count"]) for row in rows) == 3
    assert sum(int(row["request_total"]) for row in rows) == 3
    assert sum(int(row["success_total"]) for row in rows) == 2
    latencies = sorted(float(row["avg_latency_ms"]) for row in rows)
    assert latencies[0] == 80.0
    assert latencies[1] > latencies[0]

    dispose_engine(database_url)


def test_usage_service_builds_logs_analytics_projections(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    fixed_now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    _seed_runtime_activity(database_url, fixed_now)

    service = UsageService(database_url, now_factory=lambda: fixed_now)
    filters = {
        "range": "24h",
        "start_gmt": "2026-03-11 08:00:00",
        "end_gmt": "2026-03-12 08:00:00",
        "status": "all",
    }

    summary = service.get_logs_analytics_summary(site_id="site_alpha", filters=filters)
    tool_latency = service.get_logs_analytics_tool_latency(
        site_id="site_alpha",
        filters=filters,
    )
    recommendations = service.get_logs_analytics_recommendations(
        site_id="site_alpha",
        filters=filters,
    )
    unsupported = service.get_logs_analytics_summary(
        site_id="site_alpha",
        filters={**filters, "app_id": "unsupported-app"},
    )

    assert summary["source"] == "cloud_logs_analytics_summary"
    assert summary["total"] == 4
    assert summary["success"] == 3
    assert summary["error"] == 1
    assert summary["error_only"] == 0
    assert summary["blocked"] == 1
    assert summary["status_distribution"]["total"] == 4
    assert summary["status_distribution"]["error"] == 0
    assert summary["status_distribution"]["blocked"] == 1
    assert len(summary["trend_7d"]) == 7
    assert summary["top_errors"][0]["error_code"] == "quota.rate_limited"

    assert tool_latency["source"] == "cloud"
    assert tool_latency["samples"] == 4
    assert tool_latency["p95_ms"] >= tool_latency["p50_ms"]

    assert recommendations["recommended_providers"]
    assert recommendations["recommended_providers"][0] == "openai"
    assert recommendations["recommended_error_codes"] == ["quota.rate_limited"]

    assert unsupported["total"] == 0
    assert unsupported["status_distribution"]["total"] == 0

    dispose_engine(database_url)
