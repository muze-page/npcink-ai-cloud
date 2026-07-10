from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import unquote_plus

from app.adapters.repositories.runtime_repository import RuntimeRepository
from app.adapters.repositories.stats_repository import StatsRepository
from app.core.db import get_session
from app.core.models import (
    CatalogInstance,
    HealthSnapshot,
    ProviderCallRecord,
    RunRecord,
)
from app.domain.health.scoring import assess_instance_health


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return default


def _coerce_float(value: object, default: float = 0.0) -> float:
    try:
        return float(cast(Any, value))
    except (TypeError, ValueError):
        return default


def _dict_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _datetime_value(value: object) -> datetime | None:
    return value if isinstance(value, datetime) else None


class UsageInstanceNotFoundError(ValueError):
    def __init__(self, instance_id: str) -> None:
        super().__init__(f"instance not found: {instance_id}")
        self.instance_id = instance_id
        self.error_code = "stats.instance_not_found"
        self.message = "stats instance not found"


class UsageProfileNotFoundError(ValueError):
    def __init__(self, profile_id: str) -> None:
        super().__init__(f"profile not found: {profile_id}")
        self.profile_id = profile_id
        self.error_code = "stats.profile_not_found"
        self.message = "stats profile not found"


class UsageService:
    def __init__(
        self,
        database_url: str,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.database_url = database_url
        self.now_factory = now_factory or (lambda: datetime.now(UTC))

    def get_instance_stats(
        self,
        instance_id: str,
        *,
        site_id: str | None = None,
    ) -> dict[str, Any]:
        now = self.now_factory()
        windows = self._build_windows(now)
        rolling_window = windows["rolling_24h"]

        with get_session(self.database_url) as session:
            repository = StatsRepository(session)
            instance = repository.get_instance(instance_id)
            if instance is None:
                raise UsageInstanceNotFoundError(instance_id)

            provider_calls = repository.list_provider_calls_for_instance(
                instance_id,
                site_id,
                start_at=rolling_window["start_at"],
                end_at=rolling_window["end_at"],
            )
            health_snapshots = repository.list_health_snapshots([instance_id])
            today_metrics = repository.aggregate_provider_calls_window(
                start_at=windows["today"]["start_at"],
                end_at=windows["today"]["end_at"],
                site_id=site_id,
                instance_id=instance_id,
            )
            today_latencies = repository.list_provider_call_latency_values_window(
                start_at=windows["today"]["start_at"],
                end_at=windows["today"]["end_at"],
                site_id=site_id,
                instance_id=instance_id,
            )
            rolling_metrics = repository.aggregate_provider_calls_window(
                start_at=rolling_window["start_at"],
                end_at=rolling_window["end_at"],
                site_id=site_id,
                instance_id=instance_id,
            )
            rolling_latencies = repository.list_provider_call_latency_values_window(
                start_at=rolling_window["start_at"],
                end_at=rolling_window["end_at"],
                site_id=site_id,
                instance_id=instance_id,
            )

        latest_health = self._latest_health_by_instance(health_snapshots).get(instance_id)
        health_assessment = assess_instance_health(provider_calls, now=now)
        today_window = self._build_provider_window_from_metrics(
            windows["today"],
            metrics=today_metrics,
            latency_values=today_latencies,
        )
        rolling_window_payload = self._build_provider_window_from_metrics(
            rolling_window,
            metrics=rolling_metrics,
            latency_values=rolling_latencies,
        )

        return {
            "status": "ready" if today_window["calls_total"] > 0 else "empty",
            "error": "",
            "source": "logs" if rolling_window_payload["calls_total"] > 0 else "empty",
            "timezone": "UTC",
            "generated_at": self._format_datetime(now),
            "instance_id": instance.instance_id,
            "provider_id": instance.provider_id,
            "model_id": instance.model_id,
            "region": instance.region,
            "endpoint_variant": instance.endpoint_variant,
            "health_status": latest_health.status if latest_health is not None else "unknown",
            "health_reason": latest_health.reason if latest_health is not None else "",
            "health_measured_at": self._format_datetime_or_empty(
                latest_health.measured_at if latest_health is not None else None
            ),
            "health_score": health_assessment.score,
            "health_window_calls": health_assessment.calls_total,
            "today_calls": today_window["calls_total"],
            "success_rate": today_window["success_rate"],
            "avg_latency_ms": today_window["avg_latency_ms"],
            "latency_ms_p50": today_window["latency_ms_p50"],
            "latency_ms_p95": today_window["latency_ms_p95"],
            "fallback_rate": today_window["fallback_rate"],
            "windows": {
                "today": today_window,
                "rolling_24h": rolling_window_payload,
            },
        }

    def build_empty_instance_stats(
        self,
        instance_id: str,
        *,
        source: str = "cloud_latency_probe_empty",
    ) -> dict[str, Any]:
        now = self.now_factory()
        windows = self._build_windows(now)

        with get_session(self.database_url) as session:
            repository = StatsRepository(session)
            instance = repository.get_instance(instance_id)
            if instance is None:
                raise UsageInstanceNotFoundError(instance_id)

        empty_today = self._build_empty_provider_window(windows["today"])
        empty_rolling = self._build_empty_provider_window(windows["rolling_24h"])

        return {
            "status": "empty",
            "error": "",
            "source": source,
            "timezone": "UTC",
            "generated_at": self._format_datetime(now),
            "instance_id": instance.instance_id,
            "provider_id": instance.provider_id,
            "model_id": instance.model_id,
            "region": instance.region,
            "endpoint_variant": instance.endpoint_variant,
            "health_status": "unknown",
            "health_reason": "",
            "health_measured_at": "",
            "health_score": 0,
            "health_window_calls": 0,
            "today_calls": 0,
            "success_rate": 0.0,
            "avg_latency_ms": 0,
            "latency_ms_p50": 0,
            "latency_ms_p95": 0,
            "fallback_rate": 0.0,
            "windows": {
                "today": empty_today,
                "rolling_24h": empty_rolling,
            },
        }

    def get_profile_stats(
        self,
        profile_id: str,
        *,
        site_id: str | None = None,
    ) -> dict[str, Any]:
        now = self.now_factory()
        windows = self._build_windows(now)
        rolling_window = windows["rolling_24h"]

        with get_session(self.database_url) as session:
            repository = StatsRepository(session)
            profile = repository.get_profile(profile_id)
            if profile is None:
                raise UsageProfileNotFoundError(profile_id)

            binding = repository.get_routing_binding(profile_id)
            candidate_instance_ids = (
                list(binding.candidate_instance_ids) if binding is not None else []
            )
            instances = repository.list_instances_by_ids(candidate_instance_ids)
            provider_calls = repository.list_provider_calls_for_instances(
                candidate_instance_ids,
                site_id,
                start_at=rolling_window["start_at"],
                end_at=rolling_window["end_at"],
            )
            health_snapshots = repository.list_health_snapshots(candidate_instance_ids)
            today_metrics = repository.aggregate_runs_window(
                start_at=windows["today"]["start_at"],
                end_at=windows["today"]["end_at"],
                site_id=site_id,
                profile_id=profile_id,
            )
            today_latencies = repository.list_run_latency_values_window(
                start_at=windows["today"]["start_at"],
                end_at=windows["today"]["end_at"],
                site_id=site_id,
                profile_id=profile_id,
            )
            rolling_metrics = repository.aggregate_runs_window(
                start_at=rolling_window["start_at"],
                end_at=rolling_window["end_at"],
                site_id=site_id,
                profile_id=profile_id,
            )
            rolling_latencies = repository.list_run_latency_values_window(
                start_at=rolling_window["start_at"],
                end_at=rolling_window["end_at"],
                site_id=site_id,
                profile_id=profile_id,
            )

        today_window = self._build_run_window_from_metrics(
            windows["today"],
            metrics=today_metrics,
            latency_values=today_latencies,
        )
        rolling_window_payload = self._build_run_window_from_metrics(
            rolling_window,
            metrics=rolling_metrics,
            latency_values=rolling_latencies,
        )
        health_summary = self._build_health_summary(
            instances,
            health_snapshots,
            provider_calls,
            now,
        )

        return {
            "status": "ready" if today_window["calls_total"] > 0 else "empty",
            "error": "",
            "source": "runs" if rolling_window_payload["calls_total"] > 0 else "empty",
            "timezone": "UTC",
            "generated_at": self._format_datetime(now),
            "profile_id": profile.profile_id,
            "execution_kind": profile.execution_kind,
            "candidate_instance_ids": candidate_instance_ids,
            "today_calls": today_window["calls_total"],
            "success_rate": today_window["success_rate"],
            "avg_latency_ms": today_window["avg_latency_ms"],
            "fallback_rate": today_window["fallback_rate"],
            "health": health_summary,
            "windows": {
                "today": today_window,
                "rolling_24h": rolling_window_payload,
            },
        }

    def get_hosted_discovery(
        self,
        *,
        site_id: str | None = None,
    ) -> dict[str, Any]:
        now = self.now_factory()

        with get_session(self.database_url) as session:
            repository = StatsRepository(session)
            profiles = repository.list_profiles()
            instances = repository.list_instances()

        instances_by_id = {instance.instance_id: instance for instance in instances}
        profile_items: list[dict[str, Any]] = []

        with get_session(self.database_url) as session:
            repository = StatsRepository(session)
            for profile in profiles:
                binding = repository.get_routing_binding(profile.profile_id)
                candidate_instance_ids = (
                    list(binding.candidate_instance_ids) if binding is not None else []
                )
                candidate_instances = [
                    instances_by_id[instance_id]
                    for instance_id in candidate_instance_ids
                    if instance_id in instances_by_id
                ]
                provider_ids = sorted(
                    {
                        str(instance.provider_id or "").strip()
                        for instance in candidate_instances
                        if str(instance.provider_id or "").strip()
                    }
                )
                profile_items.append(
                    {
                        "profile_id": profile.profile_id,
                        "execution_kind": profile.execution_kind,
                        "candidate_total": len(candidate_instances),
                        "candidate_instance_ids": candidate_instance_ids,
                        "provider_ids": provider_ids,
                    }
                )

        instance_items = [
            {
                "instance_id": instance.instance_id,
                "provider_id": instance.provider_id,
                "model_id": instance.model_id,
                "region": instance.region,
                "endpoint_variant": instance.endpoint_variant,
                "health_status": instance.health_status,
            }
            for instance in instances
        ]

        return {
            "source": "catalog",
            "site_id": site_id or "",
            "timezone": "UTC",
            "generated_at": self._format_datetime(now),
            "profiles": profile_items,
            "instances": instance_items,
        }

    def get_hosted_profile_metadata(
        self,
        profile_id: str,
        *,
        site_id: str | None = None,
    ) -> dict[str, Any]:
        now = self.now_factory()

        with get_session(self.database_url) as session:
            repository = StatsRepository(session)
            profile = repository.get_profile(profile_id)
            if profile is None:
                raise UsageProfileNotFoundError(profile_id)

            binding = repository.get_routing_binding(profile_id)
            candidate_instance_ids = (
                list(binding.candidate_instance_ids) if binding is not None else []
            )
            instances = repository.list_instances_by_ids(candidate_instance_ids)
            models = repository.list_models_by_ids(
                [
                    instance.model_id
                    for instance in instances
                    if str(instance.model_id or "").strip()
                ]
            )

        models_by_id = {model.model_id: model for model in models}
        candidate_rows = [
            self._serialize_hosted_instance_metadata(
                instance,
                models_by_id.get(instance.model_id),
            )
            for instance in instances
        ]
        capability_tags = sorted(
            {
                str(tag).strip()
                for row in candidate_rows
                for tag in row.get("capability_tags", [])
                if str(tag).strip()
            }
        )
        price_inputs = [
            float(row["price_input"])
            for row in candidate_rows
            if row.get("price_input") is not None
        ]
        price_outputs = [
            float(row["price_output"])
            for row in candidate_rows
            if row.get("price_output") is not None
        ]
        providers = sorted(
            {
                str(row.get("provider_id") or "").strip()
                for row in candidate_rows
                if str(row.get("provider_id") or "").strip()
            }
        )

        return {
            "source": "catalog",
            "site_id": site_id or "",
            "timezone": "UTC",
            "generated_at": self._format_datetime(now),
            "profile_id": profile.profile_id,
            "execution_kind": profile.execution_kind,
            "candidate_total": len(candidate_rows),
            "candidate_instance_ids": candidate_instance_ids,
            "provider_ids": providers,
            "capability_tags": capability_tags,
            "pricing": {
                "source": "catalog",
                "unit": "per_million_tokens_usd",
                "input_min": min(price_inputs) if price_inputs else None,
                "input_max": max(price_inputs) if price_inputs else None,
                "output_min": min(price_outputs) if price_outputs else None,
                "output_max": max(price_outputs) if price_outputs else None,
            },
            "candidates": candidate_rows,
        }

    def get_hosted_instance_metadata(
        self,
        instance_id: str,
        *,
        site_id: str | None = None,
    ) -> dict[str, Any]:
        now = self.now_factory()

        with get_session(self.database_url) as session:
            repository = StatsRepository(session)
            instance = repository.get_instance(instance_id)
            if instance is None:
                raise UsageInstanceNotFoundError(instance_id)
            model = repository.get_model(instance.model_id)

        return {
            "source": "catalog",
            "site_id": site_id or "",
            "timezone": "UTC",
            "generated_at": self._format_datetime(now),
            **self._serialize_hosted_instance_metadata(instance, model),
        }

    def get_usage_summary(
        self,
        *,
        site_id: str | None = None,
        site_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        now = self.now_factory()
        windows = self._build_windows(now)
        rolling_window = windows["rolling_24h"]
        normalized_site_ids = (
            sorted({str(item).strip() for item in site_ids if str(item).strip()})
            if site_ids is not None
            else None
        )

        with get_session(self.database_url) as session:
            repository = StatsRepository(session)
            instances = repository.list_instances()
            provider_calls = repository.list_provider_calls(
                site_id,
                site_ids=normalized_site_ids,
                start_at=rolling_window["start_at"],
                end_at=rolling_window["end_at"],
            )
            health_snapshots = repository.list_health_snapshots()
            sites_total = repository.count_sites()
            profiles_total = repository.count_profiles()
            today_run_metrics = repository.aggregate_runs_window(
                start_at=windows["today"]["start_at"],
                end_at=windows["today"]["end_at"],
                site_id=site_id,
                site_ids=normalized_site_ids,
            )
            today_run_latencies = repository.list_run_latency_values_window(
                start_at=windows["today"]["start_at"],
                end_at=windows["today"]["end_at"],
                site_id=site_id,
                site_ids=normalized_site_ids,
            )
            today_provider_metrics = repository.aggregate_provider_calls_window(
                start_at=windows["today"]["start_at"],
                end_at=windows["today"]["end_at"],
                site_id=site_id,
                site_ids=normalized_site_ids,
                constrain_run_started=True,
            )
            rolling_run_metrics = repository.aggregate_runs_window(
                start_at=rolling_window["start_at"],
                end_at=rolling_window["end_at"],
                site_id=site_id,
                site_ids=normalized_site_ids,
            )
            rolling_run_latencies = repository.list_run_latency_values_window(
                start_at=rolling_window["start_at"],
                end_at=rolling_window["end_at"],
                site_id=site_id,
                site_ids=normalized_site_ids,
            )
            rolling_provider_metrics = repository.aggregate_provider_calls_window(
                start_at=rolling_window["start_at"],
                end_at=rolling_window["end_at"],
                site_id=site_id,
                site_ids=normalized_site_ids,
                constrain_run_started=True,
            )

        latest_health = self._build_health_summary(
            instances,
            health_snapshots,
            provider_calls,
            now,
        )
        today_window = self._build_usage_summary_window_from_metrics(
            windows["today"],
            run_metrics=today_run_metrics,
            provider_metrics=today_provider_metrics,
            latency_values=today_run_latencies,
        )
        rolling_window_payload = self._build_usage_summary_window_from_metrics(
            rolling_window,
            run_metrics=rolling_run_metrics,
            provider_metrics=rolling_provider_metrics,
            latency_values=rolling_run_latencies,
        )

        return {
            "timezone": "UTC",
            "generated_at": self._format_datetime(now),
            "totals": {
                "sites_total": (
                    1
                    if site_id
                    else len(normalized_site_ids)
                    if normalized_site_ids is not None
                    else sites_total
                ),
                "profiles_total": profiles_total,
                "instances_total": len(instances),
                "providers_total": len({instance.provider_id for instance in instances}),
            },
            "windows": {
                "today": today_window,
                "rolling_24h": rolling_window_payload,
            },
            "health": latest_health,
        }

    def get_router_recommendation_summary(
        self,
        *,
        site_id: str,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = self.now_factory()
        recommendations = self.get_logs_analytics_recommendations(
            site_id=site_id,
            filters=filters,
        )
        alerts = self.get_alert_provider_degradation_projection(
            site_id=site_id,
            window_minutes=30,
            min_requests=20,
            error_rate_threshold=0.25,
            latency_ms_threshold=20000,
        )

        recommended_provider_ids = [
            str(provider_id).strip()
            for provider_id in recommendations.get("recommended_providers", [])
            if str(provider_id).strip()
        ]
        degraded_provider_ids = sorted(
            {
                str((event.get("summary") or {}).get("provider") or "").strip()
                for event in alerts.get("events", [])
                if isinstance(event, dict)
                and str(event.get("status") or "").strip().lower() != "healthy"
                and str((event.get("summary") or {}).get("provider") or "").strip()
            }
        )

        with get_session(self.database_url) as session:
            repository = StatsRepository(session)
            profiles = repository.list_profiles()
            bindings = {
                profile.profile_id: repository.get_routing_binding(profile.profile_id)
                for profile in profiles
            }
            instance_ids = [
                instance_id
                for binding in bindings.values()
                if binding is not None
                for instance_id in list(binding.candidate_instance_ids or [])
            ]
            instances = repository.list_instances_by_ids(instance_ids)

        instances_by_id = {instance.instance_id: instance for instance in instances}
        profile_matches: list[dict[str, Any]] = []

        for profile in profiles:
            binding = bindings.get(profile.profile_id)
            candidate_instance_ids = (
                list(binding.candidate_instance_ids) if binding is not None else []
            )
            candidate_instances = [
                instances_by_id[instance_id]
                for instance_id in candidate_instance_ids
                if instance_id in instances_by_id
            ]
            candidate_provider_ids = sorted(
                {
                    str(instance.provider_id or "").strip()
                    for instance in candidate_instances
                    if str(instance.provider_id or "").strip()
                }
            )
            matched_provider_ids = [
                provider_id
                for provider_id in candidate_provider_ids
                if provider_id in recommended_provider_ids
            ]
            degraded_match_ids = [
                provider_id
                for provider_id in candidate_provider_ids
                if provider_id in degraded_provider_ids
            ]
            profile_matches.append(
                {
                    "profile_id": profile.profile_id,
                    "execution_kind": profile.execution_kind,
                    "candidate_instance_ids": candidate_instance_ids,
                    "candidate_provider_ids": candidate_provider_ids,
                    "matched_provider_ids": matched_provider_ids,
                    "degraded_provider_ids": degraded_match_ids,
                }
            )

        recommended_profile_ids = [
            row["profile_id"] for row in profile_matches if row["matched_provider_ids"]
        ]
        avoid_profile_ids = [
            row["profile_id"]
            for row in profile_matches
            if row["degraded_provider_ids"] and not row["matched_provider_ids"]
        ]

        summary_lines: list[str] = []
        if recommended_provider_ids:
            summary_lines.append(
                "Recommended providers: " + ", ".join(recommended_provider_ids[:5])
            )
        else:
            summary_lines.append("No provider recommendation available in the current window.")
        if degraded_provider_ids:
            summary_lines.append("Degraded providers: " + ", ".join(degraded_provider_ids[:5]))
        else:
            summary_lines.append("No provider degradation signals in the current window.")
        if recommended_profile_ids:
            summary_lines.append(
                "Profiles with matching providers: " + ", ".join(recommended_profile_ids[:5])
            )

        return {
            "source": "stats+catalog",
            "site_id": site_id,
            "timezone": "UTC",
            "generated_at": self._format_datetime(now),
            "recommended_provider_ids": recommended_provider_ids,
            "recommended_profile_ids": recommended_profile_ids,
            "avoid_provider_ids": degraded_provider_ids,
            "avoid_profile_ids": avoid_profile_ids,
            "recommended_error_codes": recommendations.get("recommended_error_codes", []),
            "summary_lines": summary_lines,
            "evidence": {
                "provider_alerts": alerts.get("events", []),
                "profile_matches": profile_matches,
            },
        }

    def get_router_performance_snapshot_projection(
        self,
        *,
        site_id: str,
        start_at: datetime,
        end_at: datetime,
    ) -> dict[str, Any]:
        normalized_start = self._normalize_required_datetime(start_at)
        normalized_end = self._normalize_required_datetime(end_at)
        if normalized_end <= normalized_start:
            raise ValueError("projection end must be after start")

        with get_session(self.database_url) as session:
            repository = StatsRepository(session)
            runs = repository.list_runs(site_id)
            provider_calls = repository.list_provider_calls(site_id)

        runs_by_id = {run.run_id: run for run in runs}
        aggregates: dict[tuple[str, str, str, str], dict[str, Any]] = {}

        for provider_call in provider_calls:
            created_at = self._normalize_datetime(provider_call.created_at)
            if created_at is None or not (normalized_start <= created_at < normalized_end):
                continue

            run = runs_by_id.get(provider_call.run_id)
            if run is None:
                continue

            bucket_start = created_at.replace(minute=0, second=0, microsecond=0)
            bucket_gmt = self._format_datetime(bucket_start)
            ability_id = str(run.ability_name or "").strip()
            caller_id = str(run.channel or "").strip()
            instance_id = str(provider_call.instance_id or "").strip()
            if not bucket_gmt or not ability_id or not caller_id or not instance_id:
                continue

            key = (bucket_gmt, ability_id, caller_id, instance_id)
            row = aggregates.get(key)
            if row is None:
                preset_id = self._extract_router_preset_id(run)
                row = {
                    "bucket_gmt": bucket_gmt,
                    "ability_id": ability_id,
                    "caller_id": caller_id,
                    "preset_id": preset_id,
                    "router_instance_id": instance_id,
                    "selected_model_instance_id": instance_id,
                    "request_total": 0,
                    "success_total": 0,
                    "guard_fail_total": 0,
                    "quality_sum": 0.0,
                    "quality_count": 0,
                    "reward_sum": 0.0,
                    "reward_count": 0,
                    "avg_latency_ms": 0.0,
                    "_latency_total": 0,
                }
                aggregates[key] = row

            row["request_total"] += 1
            if not provider_call.error_code:
                row["success_total"] += 1
            if self._is_router_guard_failure(provider_call.error_code, run.error_code):
                row["guard_fail_total"] += 1
            row["_latency_total"] += max(0, int(provider_call.latency_ms))

        rows: list[dict[str, Any]] = []
        for key in sorted(aggregates.keys()):
            row = aggregates[key]
            request_total = max(1, int(row["request_total"]))
            latency_total = int(row.pop("_latency_total", 0))
            success_total = max(0, int(row["success_total"]))
            row["avg_latency_ms"] = round(latency_total / request_total, 4)
            # First runtime-only proxy until cloud owns feedback snapshots.
            row["quality_sum"] = float(success_total)
            row["quality_count"] = request_total
            row["reward_sum"] = float(success_total)
            row["reward_count"] = request_total
            rows.append(row)

        return {
            "source": "cloud_router_performance_snapshot",
            "site_id": site_id,
            "generated_at": self._format_datetime(self.now_factory()),
            "metric_sources": {
                "quality": "runtime_success_proxy",
                "reward": "runtime_success_proxy",
            },
            "apply_policy": {
                "snapshot_rows": True,
                "feedback_quality_writeback": False,
                "feedback_reward_writeback": False,
            },
            "deferred_truths": [
                "quality.feedback",
                "reward.feedback",
            ],
            "window": {
                "start_gmt": self._format_datetime(normalized_start),
                "end_gmt": self._format_datetime(normalized_end),
            },
            "cursor": {
                "previous_end_gmt": self._format_datetime(normalized_start),
                "next_end_gmt": self._format_datetime(normalized_end),
            },
            "rows": rows,
        }

    def build_empty_router_performance_snapshot_projection(
        self,
        *,
        site_id: str,
        start_at: datetime,
        end_at: datetime,
        source: str = "cloud_router_performance_snapshot_empty",
    ) -> dict[str, Any]:
        normalized_start = self._normalize_required_datetime(start_at)
        normalized_end = self._normalize_required_datetime(end_at)
        if normalized_end <= normalized_start:
            raise ValueError("projection end must be after start")

        return {
            "source": source,
            "site_id": site_id,
            "generated_at": self._format_datetime(self.now_factory()),
            "metric_sources": {
                "quality": "runtime_success_proxy",
                "reward": "runtime_success_proxy",
            },
            "apply_policy": {
                "snapshot_rows": True,
                "feedback_quality_writeback": False,
                "feedback_reward_writeback": False,
            },
            "deferred_truths": [
                "quality.feedback",
                "reward.feedback",
            ],
            "window": {
                "start_gmt": self._format_datetime(normalized_start),
                "end_gmt": self._format_datetime(normalized_end),
            },
            "cursor": {
                "previous_end_gmt": self._format_datetime(normalized_start),
                "next_end_gmt": self._format_datetime(normalized_end),
            },
            "rows": [],
        }

    def get_logs_analytics_summary(
        self,
        *,
        site_id: str,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the canonical cloud-owned heavy logs analytics summary."""
        context = self._build_logs_analytics_context(site_id=site_id, filters=filters)
        status_counts = context["status_counts"]
        total = len(context["provider_calls"])
        success_total = int(status_counts["success"])
        error_only_total = int(status_counts["error"])
        timeout_total = int(status_counts["timeout"])
        blocked_total = int(status_counts["blocked"])
        canceled_total = int(status_counts["canceled"])
        error_total = total - success_total
        latency_values = [max(0, int(call.latency_ms or 0)) for call in context["provider_calls"]]

        return {
            "source": "cloud_logs_analytics_summary",
            "site_id": site_id,
            "generated_at": self._format_datetime(context["now"]),
            "updated_at": self._format_datetime(context["latest_seen_at"] or context["now"]),
            "total": total,
            "success": success_total,
            "error": error_total,
            "error_only": error_only_total,
            "timeout": timeout_total,
            "blocked": blocked_total,
            "canceled": canceled_total,
            "success_rate": self._safe_rate(success_total, total),
            "error_rate": self._safe_rate(error_total, total),
            "timeout_rate": self._safe_rate(timeout_total, total),
            "blocked_rate": self._safe_rate(blocked_total, total),
            "canceled_rate": self._safe_rate(canceled_total, total),
            "avg_elapsed_ms": self._average_latency(latency_values),
            "p50_elapsed_ms": self._calculate_percentile(latency_values, 50.0),
            "p95_elapsed_ms": self._calculate_percentile(latency_values, 95.0),
            "latency_samples": len(latency_values),
            "tool_latency_p50_ms": self._calculate_percentile(latency_values, 50.0),
            "tool_latency_p95_ms": self._calculate_percentile(latency_values, 95.0),
            "tool_latency_samples": len(latency_values),
            "tool_latency_source": "cloud",
            "top_errors": self._build_logs_top_error_rows(
                context["provider_calls"], context["runs_by_id"]
            ),
            "trend_7d": self._build_logs_trend_rows(
                context["provider_calls"],
                context["runs_by_id"],
                context["window"]["end_at"],
            ),
            "status_distribution": {
                "total": total,
                "success": success_total,
                "error": error_only_total,
                "timeout": timeout_total,
                "blocked": blocked_total,
                "canceled": canceled_total,
            },
        }

    def get_logs_analytics_tool_latency(
        self,
        *,
        site_id: str,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the canonical cloud-owned tool-latency projection for logs analytics."""
        context = self._build_logs_analytics_context(site_id=site_id, filters=filters)
        latency_values = [max(0, int(call.latency_ms or 0)) for call in context["provider_calls"]]
        return {
            "source": "cloud",
            "site_id": site_id,
            "generated_at": self._format_datetime(context["now"]),
            "p50_ms": self._calculate_percentile(latency_values, 50.0),
            "p95_ms": self._calculate_percentile(latency_values, 95.0),
            "samples": len(latency_values),
        }

    def get_logs_analytics_recommendations(
        self,
        *,
        site_id: str,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the canonical cloud-owned recommendation projection for logs analytics."""
        context = self._build_logs_analytics_context(site_id=site_id, filters=filters)
        provider_counts: defaultdict[str, int] = defaultdict(int)
        error_counts: defaultdict[str, int] = defaultdict(int)

        for provider_call in context["provider_calls"]:
            provider_id = str(provider_call.provider_id or "").strip().lower()
            if provider_id:
                provider_counts[provider_id] += 1
            error_code = self._normalize_logs_error_code(
                provider_call=provider_call,
                run=context["runs_by_id"].get(provider_call.run_id),
            )
            if error_code:
                error_counts[error_code] += 1

        recommended_providers = [
            provider_id
            for provider_id, _count in sorted(
                provider_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:5]
        ]
        recommended_error_codes = [
            error_code
            for error_code, _count in sorted(
                error_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:5]
        ]

        return {
            "source": "cloud",
            "site_id": site_id,
            "generated_at": self._format_datetime(context["now"]),
            "recommended_providers": recommended_providers,
            "recommended_error_codes": recommended_error_codes,
            "providers": recommended_providers,
            "error_codes": recommended_error_codes,
        }

    def get_logs_analytics_mcp_zone(
        self,
        *,
        site_id: str,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the canonical cloud-owned MCP-zone projection for logs analytics."""
        base_filters = filters.copy() if isinstance(filters, dict) else {}
        now = self._normalize_required_datetime(self.now_factory())
        mcp_filters = {
            **base_filters,
            "range": "24h",
            "start_gmt": self._format_datetime(now - timedelta(hours=24)),
            "end_gmt": self._format_datetime(now),
        }
        context = self._build_logs_analytics_context(site_id=site_id, filters=mcp_filters)
        ability_counts: defaultdict[str, int] = defaultdict(int)
        error_counts: defaultdict[str, int] = defaultdict(int)
        caller_options: set[str] = set()
        calls_total = 0
        failed_total = 0
        blocked_total = 0

        for provider_call in context["provider_calls"]:
            run = context["runs_by_id"].get(provider_call.run_id)
            if run is None or not self._is_mcp_runtime_call(run):
                continue
            calls_total += 1
            caller_id = str(run.channel or "").strip().lower()
            if caller_id:
                caller_options.add(caller_id)
            ability_id = str(run.ability_name or "").strip().lower()
            if ability_id:
                ability_counts[ability_id] += 1
            status = self._classify_logs_call_status(run=run, provider_call=provider_call)
            if status != "success":
                failed_total += 1
            if status == "blocked":
                blocked_total += 1
            error_code = self._normalize_logs_error_code(provider_call=provider_call, run=run)
            if error_code:
                error_counts[error_code] += 1

        return {
            "window": "24h",
            "calls_total": calls_total,
            "failed_total": failed_total,
            "blocked_total": blocked_total,
            "top_abilities": [
                {"ability_id": ability_id, "count": count}
                for ability_id, count in sorted(
                    ability_counts.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:5]
            ],
            "top_error_codes": [
                {"error_code": error_code, "count": count}
                for error_code, count in sorted(
                    error_counts.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:5]
            ],
            "server_options": [],
            "app_options": [],
            "caller_options": sorted(caller_options),
            "filters": {
                "mcp_server_id": str(base_filters.get("mcp_server_id") or ""),
                "app_id": str(base_filters.get("app_id") or ""),
                "caller_id": str(base_filters.get("caller_id") or ""),
            },
            "source": "cloud",
            "generated_at": self._format_datetime(context["now"]),
        }

    def _extract_router_preset_id(self, run: RunRecord) -> str:
        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
        input_payload = run.input_json if isinstance(run.input_json, dict) else {}
        candidates = (
            policy.get("preset_id"),
            policy.get("router_preset_id"),
            input_payload.get("preset_id"),
            input_payload.get("router_preset_id"),
        )
        for value in candidates:
            if value is None:
                continue
            preset_id = str(value).strip()
            if preset_id:
                return preset_id[:191]
        return ""

    def _is_router_guard_failure(
        self, provider_error_code: str | None, run_error_code: str | None
    ) -> bool:
        codes = [str(provider_error_code or "").lower(), str(run_error_code or "").lower()]
        for code in codes:
            if not code:
                continue
            if (
                code.startswith("guard.")
                or code.startswith("policy.")
                or code.startswith("safety.")
                or code.startswith("quota.")
                or code.startswith("auth.")
                or code.startswith("authz.")
                or code.startswith("tool.not_allowed")
                or code.startswith("tool.confirm_required")
            ):
                return True
        return False

    def get_alert_provider_degradation_projection(
        self,
        *,
        site_id: str,
        window_minutes: int,
        min_requests: int,
        error_rate_threshold: float,
        latency_ms_threshold: int,
    ) -> dict[str, Any]:
        now = self._normalize_required_datetime(self.now_factory())
        normalized_window_minutes = max(5, int(window_minutes))
        normalized_min_requests = max(1, int(min_requests))
        normalized_error_rate_threshold = min(1.0, max(0.01, float(error_rate_threshold)))
        normalized_latency_ms_threshold = max(1, int(latency_ms_threshold))
        start_at = now - timedelta(minutes=normalized_window_minutes)

        with get_session(self.database_url) as session:
            repository = StatsRepository(session)
            instances = repository.list_instances()
            provider_calls = repository.list_provider_calls(site_id)
            health_snapshots = repository.list_health_snapshots()

        instances_by_id = {instance.instance_id: instance for instance in instances}
        latest_health_by_instance = self._latest_health_by_instance(health_snapshots)
        scoped_calls = [
            call for call in provider_calls if self._is_in_window(call.created_at, start_at, now)
        ]

        provider_calls_by_provider: defaultdict[str, list[ProviderCallRecord]] = defaultdict(list)
        for provider_call in scoped_calls:
            provider_id = str(provider_call.provider_id or "").strip()
            if not provider_id:
                instance = instances_by_id.get(provider_call.instance_id)
                provider_id = str(instance.provider_id if instance is not None else "").strip()
            if not provider_id:
                continue
            provider_calls_by_provider[provider_id].append(provider_call)

        provider_instances: defaultdict[str, list[CatalogInstance]] = defaultdict(list)
        for instance in instances:
            provider_id = str(instance.provider_id or "").strip()
            if not provider_id:
                continue
            provider_instances[provider_id].append(instance)

        events: list[dict[str, Any]] = []
        for provider_id in sorted(
            set(provider_instances.keys()) | set(provider_calls_by_provider.keys())
        ):
            calls = provider_calls_by_provider.get(provider_id, [])
            total = len(calls)
            if total < normalized_min_requests:
                continue

            errors = sum(1 for call in calls if call.error_code)
            error_rate = self._safe_rate(errors, total)
            avg_latency_ms = self._average_latency([call.latency_ms for call in calls])
            if (
                error_rate < normalized_error_rate_threshold
                and avg_latency_ms < normalized_latency_ms_threshold
            ):
                continue

            health_counts: defaultdict[str, int] = defaultdict(int)
            last_measured_at: datetime | None = None
            for instance in provider_instances.get(provider_id, []):
                snapshot = latest_health_by_instance.get(instance.instance_id)
                status = snapshot.status if snapshot is not None else "unknown"
                health_counts[status] += 1
                normalized_measured_at = self._normalize_datetime(
                    snapshot.measured_at if snapshot is not None else None
                )
                if normalized_measured_at is not None and (
                    last_measured_at is None or normalized_measured_at > last_measured_at
                ):
                    last_measured_at = normalized_measured_at

            events.append(
                {
                    "rule_type": "provider_degradation",
                    "fingerprint": f"provider_degradation:{provider_id.lower()}",
                    "status": "open",
                    "summary": {
                        "provider": provider_id,
                        "window_minutes": normalized_window_minutes,
                        "total": total,
                        "errors": errors,
                        "error_rate": error_rate,
                        "avg_latency_ms": avg_latency_ms,
                        "error_rate_threshold": normalized_error_rate_threshold,
                        "latency_ms_threshold": normalized_latency_ms_threshold,
                        "source": "cloud_provider_stats",
                    },
                    "context": {
                        "provider": provider_id,
                        "window_minutes": normalized_window_minutes,
                        "total": total,
                        "errors": errors,
                        "error_rate": error_rate,
                        "avg_latency_ms": avg_latency_ms,
                        "error_rate_threshold": normalized_error_rate_threshold,
                        "latency_ms_threshold": normalized_latency_ms_threshold,
                        "healthy_instances_total": int(health_counts["healthy"]),
                        "degraded_instances_total": int(health_counts["degraded"]),
                        "unhealthy_instances_total": int(health_counts["unhealthy"]),
                        "unknown_instances_total": int(health_counts["unknown"]),
                        "last_measured_at": self._format_datetime_or_empty(last_measured_at),
                        "source": "cloud_provider_stats",
                    },
                    "channels": {
                        "email": False,
                        "webhook": False,
                        "log": True,
                    },
                }
            )

        return {
            "source": "cloud_alert_evaluate",
            "site_id": site_id,
            "generated_at": self._format_datetime(now),
            "window": {
                "start_gmt": self._format_datetime(start_at),
                "end_gmt": self._format_datetime(now),
            },
            "touched_rule_types": ["provider_degradation"],
            "events": events,
        }

    def get_router_diagnostics_projection(
        self,
        *,
        site_id: str,
        config_revision: str,
        enabled_total: int,
        tagless_enabled: bool,
        high_risk_count: int,
        has_warnings: bool,
        recent_minutes: int = 60,
    ) -> dict[str, Any]:
        now = self._normalize_required_datetime(self.now_factory())
        normalized_recent_minutes = max(1, min(1440, int(recent_minutes)))
        recent_since = now - timedelta(minutes=normalized_recent_minutes)

        with get_session(self.database_url) as session:
            runtime_repository = RuntimeRepository(session)
            runtime_summary = runtime_repository.get_runtime_diagnostics_summary(
                site_id=site_id,
                now=now,
                recent_since=recent_since,
            )
            guard_summary = {
                "recent_events": runtime_repository.count_runtime_guard_events(
                    since=recent_since,
                    site_id=site_id,
                ),
                "recent_rate_limit_exceeded": runtime_repository.count_runtime_guard_events(
                    since=recent_since,
                    site_id=site_id,
                    event_code="auth.rate_limit_exceeded",
                ),
            }
            regression_items = self._build_router_diagnostics_regression_items(
                runtime_repository=runtime_repository,
                site_id=site_id,
                now=now,
            )
            quality_items = self._build_router_diagnostics_quality_items(
                runtime_repository=runtime_repository,
                site_id=site_id,
                now=now,
                recent_since=recent_since,
            )

        queue_summary = _dict_value(runtime_summary.get("queue"))
        callback_summary = _dict_value(runtime_summary.get("callback"))
        retention_summary = _dict_value(runtime_summary.get("retention"))
        cancel_summary = _dict_value(runtime_summary.get("cancel"))

        regression_failed = (
            _coerce_int(callback_summary.get("failed"))
            + _coerce_int(retention_summary.get("due_purge"))
            + _coerce_int(cancel_summary.get("active_requests"))
        )
        quality_failed = (
            _coerce_int(queue_summary.get("queued_runs"))
            + _coerce_int(queue_summary.get("running_runs"))
            + _coerce_int(callback_summary.get("due_now"))
            + _coerce_int(guard_summary.get("recent_rate_limit_exceeded"))
        )
        derived_warnings = bool(has_warnings) or regression_failed > 0 or quality_failed > 0
        stale_after = now + timedelta(minutes=15)

        return {
            "source": "cloud_router_diagnostics",
            "site_id": site_id,
            "generated_at": self._format_datetime(now),
            "config_revision": config_revision,
            "stale_after_gmt": self._format_datetime(stale_after),
            "report": {
                "validation": {
                    "checked_at": int(now.timestamp()),
                    "source": "cloud_runtime_summary",
                    "tagless_enabled": bool(tagless_enabled),
                    "enabled_total": max(0, int(enabled_total)),
                    "has_warnings": derived_warnings,
                },
                "high_risk": {
                    "count": max(0, int(high_risk_count)),
                },
                "regressions": {
                    "count": regression_failed,
                    "passed": 0,
                    "failed": regression_failed,
                    "items": regression_items,
                },
                "quality_regressions": {
                    "enabled": True,
                    "count": quality_failed,
                    "passed": 0,
                    "failed": quality_failed,
                    "reason": "cloud_runtime_summary",
                    "items": quality_items,
                },
            },
        }

    def build_empty_router_diagnostics_projection(
        self,
        *,
        site_id: str,
        config_revision: str,
        enabled_total: int,
        tagless_enabled: bool,
        high_risk_count: int,
        has_warnings: bool,
        recent_minutes: int = 60,
        source: str = "cloud_router_diagnostics_empty",
    ) -> dict[str, Any]:
        now = self._normalize_required_datetime(self.now_factory())
        stale_after = now + timedelta(minutes=15)

        return {
            "source": source,
            "site_id": site_id,
            "generated_at": self._format_datetime(now),
            "config_revision": config_revision,
            "stale_after_gmt": self._format_datetime(stale_after),
            "report": {
                "validation": {
                    "checked_at": int(now.timestamp()),
                    "source": "usage_rollup_empty",
                    "tagless_enabled": bool(tagless_enabled),
                    "enabled_total": max(0, int(enabled_total)),
                    "has_warnings": bool(has_warnings),
                },
                "high_risk": {
                    "count": max(0, int(high_risk_count)),
                },
                "regressions": {
                    "count": 0,
                    "passed": 1,
                    "failed": 0,
                    "items": [],
                },
                "quality_regressions": {
                    "enabled": True,
                    "count": 0,
                    "passed": 1,
                    "failed": 0,
                    "reason": "",
                    "items": [],
                },
            },
        }

    def _build_router_diagnostics_regression_items(
        self,
        *,
        runtime_repository: RuntimeRepository,
        site_id: str,
        now: datetime,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        issue_kinds = (
            ("callback_failed", "callback failed"),
            ("retention_due", "retention purge overdue"),
            ("cancel_requested", "cancel request still active"),
        )
        for issue_kind, label in issue_kinds:
            runs = runtime_repository.list_runtime_diagnostic_runs(
                issue_kind=issue_kind,
                site_id=site_id,
                limit=2,
                now=now,
            )
            for run in runs:
                items.append(
                    self._serialize_router_diagnostics_run_item(
                        run=run,
                        kind=issue_kind,
                        label=label,
                    )
                )
        return items

    def _build_router_diagnostics_quality_items(
        self,
        *,
        runtime_repository: RuntimeRepository,
        site_id: str,
        now: datetime,
        recent_since: datetime,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        recent_guard_events = runtime_repository.list_runtime_guard_events_since(
            since=recent_since,
            site_id=site_id,
            limit=10,
        )
        latest_guard_event_by_code = {
            str(event.event_code or ""): event
            for event in recent_guard_events
            if str(event.event_code or "").strip()
        }
        issue_kinds = (
            ("queued", "queued run backlog"),
            ("running", "long-running execution"),
            ("callback_due", "callback due now"),
        )
        for issue_kind, label in issue_kinds:
            runs = runtime_repository.list_runtime_diagnostic_runs(
                issue_kind=issue_kind,
                site_id=site_id,
                limit=2,
                now=now,
            )
            for run in runs:
                items.append(
                    self._serialize_router_diagnostics_run_item(
                        run=run,
                        kind=issue_kind,
                        label=label,
                    )
                )

        for event in runtime_repository.summarize_runtime_guard_event_codes(
            since=recent_since,
            site_id=site_id,
            limit=2,
        ):
            event_code = str(event.get("event_code") or "")
            items.append(
                {
                    "kind": "guard_event",
                    "label": "runtime guard event",
                    "event_code": event_code,
                    "count": _coerce_int(event.get("event_count")),
                    "summary": event_code or "runtime guard event",
                    "last_seen_at": str(event.get("last_seen_at") or ""),
                    "details": self._serialize_router_diagnostics_guard_event_details(
                        latest_guard_event_by_code.get(event_code)
                    ),
                }
            )
        return items

    def _serialize_router_diagnostics_run_item(
        self,
        *,
        run: RunRecord,
        kind: str,
        label: str,
    ) -> dict[str, Any]:
        observed_at = (
            run.callback_last_attempt_at
            or run.callback_next_attempt_at
            or run.cancel_requested_at
            or run.retention_expires_at
            or run.processing_started_at
            or run.started_at
        )
        return {
            "kind": kind,
            "label": label,
            "run_id": str(run.run_id or ""),
            "status": str(run.status or ""),
            "callback_status": str(run.callback_status or ""),
            "event_code": "",
            "count": 0,
            "summary": str(run.error_code or run.error_message or run.ability_name or kind),
            "last_seen_at": self._format_datetime(self._normalize_required_datetime(observed_at))
            if observed_at is not None
            else "",
            "details": {
                "ability_name": str(run.ability_name or ""),
                "channel": str(run.channel or ""),
                "profile_id": str(run.profile_id or ""),
                "execution_kind": str(run.execution_kind or ""),
                "selected_provider_id": str(run.selected_provider_id or ""),
                "selected_instance_id": str(run.selected_instance_id or ""),
                "error_code": str(run.error_code or ""),
                "error_message": str(run.error_message or ""),
                "callback_last_error_code": str(run.callback_last_error_code or ""),
                "callback_last_error_message": str(run.callback_last_error_message or ""),
                "started_at": self._format_datetime(
                    self._normalize_required_datetime(run.started_at)
                )
                if run.started_at is not None
                else "",
                "finished_at": self._format_datetime(
                    self._normalize_required_datetime(run.finished_at)
                )
                if run.finished_at is not None
                else "",
            },
        }

    def _serialize_router_diagnostics_guard_event_details(
        self,
        event: Any | None,
    ) -> dict[str, Any]:
        if event is None:
            return {
                "auth_surface": "",
                "scope_kind": "",
                "scope_id": "",
                "status_code": 0,
                "method": "",
                "path": "",
                "trace_id": "",
                "client_ref": "",
                "key_id": "",
            }
        return {
            "auth_surface": str(getattr(event, "auth_surface", "") or ""),
            "scope_kind": str(getattr(event, "scope_kind", "") or ""),
            "scope_id": str(getattr(event, "scope_id", "") or ""),
            "status_code": int(getattr(event, "status_code", 0) or 0),
            "method": str(getattr(event, "method", "") or ""),
            "path": str(getattr(event, "path", "") or ""),
            "trace_id": str(getattr(event, "trace_id", "") or ""),
            "client_ref": str(getattr(event, "client_ref", "") or ""),
            "key_id": str(getattr(event, "key_id", "") or ""),
        }

    def _build_windows(self, now: datetime) -> dict[str, dict[str, datetime]]:
        today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
        rolling_start = now - timedelta(hours=24)
        return {
            "today": {
                "start_at": today_start,
                "end_at": now,
            },
            "rolling_24h": {
                "start_at": rolling_start,
                "end_at": now,
            },
        }

    def _build_empty_provider_window(self, window: dict[str, datetime]) -> dict[str, Any]:
        return {
            "start_at": self._format_datetime(window["start_at"]),
            "end_at": self._format_datetime(window["end_at"]),
            "calls_total": 0,
            "success_total": 0,
            "error_total": 0,
            "success_rate": 0.0,
            "avg_latency_ms": 0,
            "latency_ms_p50": 0,
            "latency_ms_p95": 0,
            "fallback_total": 0,
            "fallback_rate": 0.0,
            "last_seen_at": "",
        }

    def _build_provider_window_from_metrics(
        self,
        window: dict[str, datetime],
        *,
        metrics: dict[str, object],
        latency_values: list[int],
    ) -> dict[str, Any]:
        calls_total = _coerce_int(metrics.get("calls_total"))
        success_total = _coerce_int(metrics.get("success_total"))
        fallback_total = _coerce_int(metrics.get("fallback_total"))
        last_seen_at = self._normalize_datetime(_datetime_value(metrics.get("last_seen_at")))
        return {
            "start_at": self._format_datetime(window["start_at"]),
            "end_at": self._format_datetime(window["end_at"]),
            "calls_total": calls_total,
            "success_total": success_total,
            "error_total": calls_total - success_total,
            "success_rate": self._safe_rate(success_total, calls_total),
            "avg_latency_ms": _coerce_int(metrics.get("avg_latency_ms")),
            "latency_ms_p50": self._calculate_percentile(latency_values, 50.0),
            "latency_ms_p95": self._calculate_percentile(latency_values, 95.0),
            "fallback_total": fallback_total,
            "fallback_rate": self._safe_rate(fallback_total, calls_total),
            "last_seen_at": self._format_datetime_or_empty(last_seen_at),
        }

    def _build_run_window_from_metrics(
        self,
        window: dict[str, datetime],
        *,
        metrics: dict[str, object],
        latency_values: list[int],
    ) -> dict[str, Any]:
        calls_total = _coerce_int(metrics.get("runs_total"))
        success_total = _coerce_int(metrics.get("success_total"))
        fallback_total = _coerce_int(metrics.get("fallback_total"))
        last_seen_at = self._normalize_datetime(_datetime_value(metrics.get("last_seen_at")))
        return {
            "start_at": self._format_datetime(window["start_at"]),
            "end_at": self._format_datetime(window["end_at"]),
            "calls_total": calls_total,
            "success_total": success_total,
            "error_total": calls_total - success_total,
            "success_rate": self._safe_rate(success_total, calls_total),
            "avg_latency_ms": _coerce_int(metrics.get("avg_latency_ms")),
            "fallback_total": fallback_total,
            "fallback_rate": self._safe_rate(fallback_total, calls_total),
            "last_seen_at": self._format_datetime_or_empty(last_seen_at),
        }

    def _build_usage_summary_window_from_metrics(
        self,
        window: dict[str, datetime],
        *,
        run_metrics: dict[str, object],
        provider_metrics: dict[str, object],
        latency_values: list[int],
    ) -> dict[str, Any]:
        runs_total = _coerce_int(run_metrics.get("runs_total"))
        success_total = _coerce_int(run_metrics.get("success_total"))
        fallback_total = _coerce_int(run_metrics.get("fallback_total"))
        last_seen_at = self._normalize_datetime(_datetime_value(run_metrics.get("last_seen_at")))
        return {
            "start_at": self._format_datetime(window["start_at"]),
            "end_at": self._format_datetime(window["end_at"]),
            "runs_total": runs_total,
            "provider_calls_total": _coerce_int(provider_metrics.get("calls_total")),
            "success_total": success_total,
            "error_total": runs_total - success_total,
            "success_rate": self._safe_rate(success_total, runs_total),
            "avg_latency_ms": _coerce_int(run_metrics.get("avg_latency_ms")),
            "fallback_total": fallback_total,
            "fallback_rate": self._safe_rate(fallback_total, runs_total),
            "tokens_in_total": _coerce_int(provider_metrics.get("tokens_in_total")),
            "tokens_out_total": _coerce_int(provider_metrics.get("tokens_out_total")),
            "cost_total": round(_coerce_float(provider_metrics.get("cost_total")), 6),
            "active_sites_total": _coerce_int(run_metrics.get("active_sites_total")),
            "latency_ms_p50": self._calculate_percentile(latency_values, 50.0),
            "latency_ms_p95": self._calculate_percentile(latency_values, 95.0),
            "last_seen_at": self._format_datetime_or_empty(last_seen_at),
        }

    def _build_health_summary(
        self,
        instances: list[CatalogInstance],
        health_snapshots: list[HealthSnapshot],
        provider_calls: list[ProviderCallRecord],
        now: datetime,
    ) -> dict[str, Any]:
        latest_by_instance = self._latest_health_by_instance(health_snapshots)
        provider_calls_by_instance: defaultdict[str, list[ProviderCallRecord]] = defaultdict(list)
        for provider_call in provider_calls:
            provider_calls_by_instance[provider_call.instance_id].append(provider_call)
        status_counts: defaultdict[str, int] = defaultdict(int)
        last_measured_at: datetime | None = None
        scores: list[float] = []

        for instance in instances:
            snapshot = latest_by_instance.get(instance.instance_id)
            status = snapshot.status if snapshot is not None else "unknown"
            status_counts[status] += 1
            assessment = assess_instance_health(
                provider_calls_by_instance.get(instance.instance_id, []),
                now=now,
            )
            scores.append(assessment.score)
            measured_at = snapshot.measured_at if snapshot is not None else None
            normalized = self._normalize_datetime(measured_at)
            if normalized is not None and (
                last_measured_at is None or normalized > last_measured_at
            ):
                last_measured_at = normalized

        return {
            "providers_total": len({instance.provider_id for instance in instances}),
            "instances_total": len(instances),
            "healthy_total": int(status_counts["healthy"]),
            "degraded_total": int(status_counts["degraded"]),
            "unhealthy_total": int(status_counts["unhealthy"]),
            "unknown_total": int(status_counts["unknown"]),
            "avg_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
            "min_score": round(min(scores), 4) if scores else 0.0,
            "scored_instances_total": len(scores),
            "last_measured_at": self._format_datetime_or_empty(last_measured_at),
        }

    def _latest_health_by_instance(
        self,
        health_snapshots: list[HealthSnapshot],
    ) -> dict[str, HealthSnapshot]:
        latest_by_instance: dict[str, HealthSnapshot] = {}
        for snapshot in health_snapshots:
            if not snapshot.instance_id:
                continue
            current = latest_by_instance.get(snapshot.instance_id)
            if current is None:
                latest_by_instance[snapshot.instance_id] = snapshot
                continue
            snapshot_measured_at = self._normalize_required_datetime(snapshot.measured_at)
            current_measured_at = self._normalize_required_datetime(current.measured_at)
            if snapshot_measured_at > current_measured_at:
                latest_by_instance[snapshot.instance_id] = snapshot
        return latest_by_instance

    def _run_latency_ms(self, run: RunRecord) -> int | None:
        started_at = self._normalize_datetime(run.started_at)
        finished_at = self._normalize_datetime(run.finished_at)
        if started_at is None or finished_at is None:
            return None
        delta_ms = int(round((finished_at - started_at).total_seconds() * 1000))
        return max(0, delta_ms)

    def _average_latency(self, latencies: list[int]) -> int:
        if not latencies:
            return 0
        return int(round(sum(latencies) / len(latencies)))

    def _safe_rate(self, numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(numerator / denominator, 4)

    def _is_in_window(self, value: datetime | None, start_at: datetime, end_at: datetime) -> bool:
        normalized = self._normalize_datetime(value)
        if normalized is None:
            return False
        return start_at <= normalized <= end_at

    def _normalize_datetime(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return self._normalize_required_datetime(value)

    def _normalize_required_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _format_datetime(self, value: datetime) -> str:
        normalized = self._normalize_datetime(value)
        if normalized is None:
            return ""
        return normalized.strftime("%Y-%m-%d %H:%M:%S")

    def _format_datetime_or_empty(self, value: datetime | None) -> str:
        normalized = self._normalize_datetime(value)
        if normalized is None:
            return ""
        return normalized.strftime("%Y-%m-%d %H:%M:%S")

    def _build_logs_analytics_context(
        self,
        *,
        site_id: str,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_filters = filters.copy() if isinstance(filters, dict) else {}
        now = self._normalize_required_datetime(self.now_factory())
        window = self._resolve_logs_analytics_window(normalized_filters, now)
        unsupported_filters = self._logs_filters_require_unavailable_dimensions(normalized_filters)

        with get_session(self.database_url) as session:
            repository = StatsRepository(session)
            runs = repository.list_runs(site_id)
            provider_calls = repository.list_provider_calls(site_id)

        runs_by_id = {run.run_id: run for run in runs}
        filtered_calls: list[ProviderCallRecord] = []
        latest_seen_at: datetime | None = None
        status_counts: defaultdict[str, int] = defaultdict(int)

        if unsupported_filters:
            return {
                "now": now,
                "window": window,
                "runs_by_id": runs_by_id,
                "provider_calls": filtered_calls,
                "latest_seen_at": latest_seen_at,
                "status_counts": status_counts,
            }

        for provider_call in provider_calls:
            run = runs_by_id.get(provider_call.run_id)
            if run is None:
                continue

            created_at = self._normalize_datetime(provider_call.created_at)
            if created_at is None or not (window["start_at"] <= created_at <= window["end_at"]):
                continue

            status = self._classify_logs_call_status(run=run, provider_call=provider_call)
            if not self._logs_call_matches_filters(
                run=run,
                provider_call=provider_call,
                status=status,
                filters=normalized_filters,
            ):
                continue

            filtered_calls.append(provider_call)
            status_counts[status] += 1
            if latest_seen_at is None or created_at > latest_seen_at:
                latest_seen_at = created_at

        return {
            "now": now,
            "window": window,
            "runs_by_id": runs_by_id,
            "provider_calls": filtered_calls,
            "latest_seen_at": latest_seen_at,
            "status_counts": status_counts,
        }

    def _serialize_hosted_instance_metadata(
        self,
        instance: CatalogInstance,
        model: Any | None,
    ) -> dict[str, Any]:
        capability_tags = [
            str(tag).strip() for tag in list(instance.capability_tags or []) if str(tag).strip()
        ]
        return {
            "instance_id": instance.instance_id,
            "provider_id": instance.provider_id,
            "model_id": instance.model_id,
            "region": instance.region,
            "endpoint_variant": instance.endpoint_variant,
            "health_status": instance.health_status,
            "capability_tags": capability_tags,
            "price_input": None if model is None else model.price_input,
            "price_output": None if model is None else model.price_output,
            "revision": "" if model is None else str(model.revision or ""),
            "updated_at": self._format_datetime_or_empty(instance.updated_at),
        }

    def _resolve_logs_analytics_window(
        self,
        filters: dict[str, Any],
        now: datetime,
    ) -> dict[str, datetime]:
        range_key = str(filters.get("range") or "").strip().lower()
        start_gmt = str(filters.get("start_gmt") or "").strip()
        end_gmt = str(filters.get("end_gmt") or "").strip()

        parsed_start = self._parse_logs_analytics_datetime(start_gmt)
        parsed_end = self._parse_logs_analytics_datetime(end_gmt)
        if parsed_start is not None and parsed_end is not None:
            if parsed_end <= parsed_start:
                raise ValueError("logs analytics end must be after start")
            return {
                "start_at": parsed_start,
                "end_at": parsed_end,
            }

        hours_map = {
            "1h": 1,
            "24h": 24,
            "7d": 24 * 7,
            "30d": 24 * 30,
        }
        hours = hours_map.get(range_key, 24)
        return {
            "start_at": now - timedelta(hours=hours),
            "end_at": now,
        }

    def _parse_logs_analytics_datetime(self, value: str) -> datetime | None:
        normalized_value = str(value or "").strip()
        normalized_value = normalized_value.replace("%%20", " ").replace("%20", " ")
        normalized_value = normalized_value.replace("% ", " ")
        normalized_value = unquote_plus(normalized_value).strip()
        normalized_value = normalized_value.replace("T", " ")
        if not normalized_value:
            return None
        return datetime.strptime(normalized_value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)

    def _coerce_non_negative_int(self, value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    def _logs_filters_require_unavailable_dimensions(
        self,
        filters: dict[str, Any],
    ) -> bool:
        unsupported_string_fields = (
            "app_id",
            "role_id",
            "resource_id",
            "mcp_server_id",
            "mcp_method",
        )
        unsupported_numeric_fields = ("user_id", "post_id")

        for field in unsupported_string_fields:
            if str(filters.get(field) or "").strip():
                return True
        for field in unsupported_numeric_fields:
            try:
                value = int(filters.get(field) or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                return True
        return False

    def _logs_call_matches_filters(
        self,
        *,
        run: RunRecord,
        provider_call: ProviderCallRecord,
        status: str,
        filters: dict[str, Any],
    ) -> bool:
        status_filter = str(filters.get("status") or "all").strip().lower()
        if status_filter and status_filter != "all" and status != status_filter:
            return False

        provider_filter = str(filters.get("provider") or "").strip().lower()
        if (
            provider_filter
            and str(provider_call.provider_id or "").strip().lower() != provider_filter
        ):
            return False

        model_filter = str(filters.get("model") or "").strip().lower()
        if model_filter and str(provider_call.model_id or "").strip().lower() != model_filter:
            return False

        trace_filter = str(filters.get("trace_id") or "").strip().lower()
        if trace_filter and str(run.trace_id or "").strip().lower() != trace_filter:
            return False

        caller_filter = str(filters.get("caller_id") or "").strip().lower()
        if caller_filter and str(run.channel or "").strip().lower() != caller_filter:
            return False

        ability_filter = str(filters.get("ability_id") or "").strip().lower()
        if ability_filter and str(run.ability_name or "").strip().lower() != ability_filter:
            return False

        error_filter = str(filters.get("error_code") or "").strip().lower()
        error_code = self._normalize_logs_error_code(provider_call=provider_call, run=run)
        if error_filter and error_code != error_filter:
            return False

        log_type_filter = str(filters.get("log_type") or "").strip().lower()
        if log_type_filter:
            call_types = self._derive_logs_call_types(run)
            if log_type_filter not in call_types:
                return False

        return True

    def _derive_logs_call_types(self, run: RunRecord) -> set[str]:
        output = {
            str(run.execution_kind or "").strip().lower(),
            str(run.ability_family or "").strip().lower(),
        }
        if self._is_mcp_runtime_call(run):
            output.add("mcp")
        return {value for value in output if value}

    def _is_mcp_runtime_call(self, run: RunRecord) -> bool:
        ability_name = str(run.ability_name or "").strip().lower()
        channel = str(run.channel or "").strip().lower()
        execution_kind = str(run.execution_kind or "").strip().lower()
        return "mcp" in ability_name or "mcp" in channel or execution_kind == "mcp"

    def _classify_logs_call_status(
        self,
        *,
        run: RunRecord,
        provider_call: ProviderCallRecord,
    ) -> str:
        error_code = self._normalize_logs_error_code(provider_call=provider_call, run=run)
        if not error_code:
            if run.canceled_at is not None or str(run.status or "").strip().lower() == "canceled":
                return "canceled"
            return "success"
        if "timeout" in error_code:
            return "timeout"
        if (
            error_code.startswith("guard.")
            or error_code.startswith("policy.")
            or error_code.startswith("quota.")
            or error_code.startswith("auth.")
            or error_code.startswith("authz.")
            or error_code.startswith("tool.not_allowed")
            or error_code.startswith("tool.confirm_required")
            or "blocked" in error_code
        ):
            return "blocked"
        if "cancel" in error_code:
            return "canceled"
        return "error"

    def _normalize_logs_error_code(
        self,
        *,
        provider_call: ProviderCallRecord,
        run: RunRecord | None,
    ) -> str:
        candidates = (
            str(provider_call.error_code or "").strip().lower(),
            str((run.error_code if run is not None else "") or "").strip().lower(),
        )
        for candidate in candidates:
            if candidate:
                return candidate
        return ""

    def _build_logs_top_error_rows(
        self,
        provider_calls: list[ProviderCallRecord],
        runs_by_id: dict[str, RunRecord],
    ) -> list[dict[str, Any]]:
        error_counts: defaultdict[str, int] = defaultdict(int)
        for provider_call in provider_calls:
            error_code = self._normalize_logs_error_code(
                provider_call=provider_call,
                run=runs_by_id.get(provider_call.run_id),
            )
            if error_code:
                error_counts[error_code] += 1
        return [
            {"error_code": error_code, "count": count}
            for error_code, count in sorted(
                error_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:5]
        ]

    def _build_logs_trend_rows(
        self,
        provider_calls: list[ProviderCallRecord],
        runs_by_id: dict[str, RunRecord],
        end_at: datetime,
    ) -> list[dict[str, Any]]:
        day_counts: dict[str, dict[str, int]] = {}
        for offset in range(6, -1, -1):
            bucket_day = (end_at - timedelta(days=offset)).strftime("%Y-%m-%d")
            day_counts[bucket_day] = {
                "total": 0,
                "success": 0,
                "error": 0,
            }

        for provider_call in provider_calls:
            created_at = self._normalize_datetime(provider_call.created_at)
            if created_at is None:
                continue
            bucket_day = created_at.strftime("%Y-%m-%d")
            bucket = day_counts.get(bucket_day)
            if bucket is None:
                continue
            bucket["total"] += 1
            run = runs_by_id.get(provider_call.run_id)
            if run is None:
                bucket["error"] += 1
                continue
            status = self._classify_logs_call_status(
                run=run,
                provider_call=provider_call,
            )
            if status == "success":
                bucket["success"] += 1
            else:
                bucket["error"] += 1

        return [
            {
                "label": label,
                "total": counts["total"],
                "success": counts["success"],
                "error": counts["error"],
            }
            for label, counts in day_counts.items()
        ]

    def _calculate_percentile(self, values: list[int], percentile: float) -> int:
        if not values:
            return 0
        normalized = sorted(max(0, int(value)) for value in values)
        if len(normalized) == 1:
            return normalized[0]
        rank = max(
            0,
            min(
                len(normalized) - 1,
                int((len(normalized) * max(0.0, float(percentile))) / 100.0 + 0.999999) - 1,
            ),
        )
        return normalized[rank]
