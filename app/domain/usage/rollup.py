from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.adapters.repositories.stats_repository import StatsRepository
from app.core.db import get_session
from app.domain.usage.service import UsageService

GLOBAL_SITE_SCOPE = "__global__"
ROUTER_PERFORMANCE_BATCH_SCOPE = "router_performance_batch"
ROUTER_DIAGNOSTICS_BATCH_SCOPE = "router_diagnostics_batch"
LATENCY_PROBE_BATCH_SCOPE = "latency_probe_batch"
ALERT_EVALUATE_BATCH_SCOPE = "alert_evaluate_batch"
ALERT_EVALUATE_BATCH_SCOPE = "alert_evaluate_batch"


class UsageRollupService:
    def __init__(
        self,
        database_url: str,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.database_url = database_url
        self.now_factory = now_factory or (lambda: datetime.now(UTC))
        self.usage_service = UsageService(database_url, now_factory=self.now_factory)

    def generate_rollups(
        self,
        *,
        site_ids: list[str] | None = None,
        include_global: bool = True,
    ) -> dict[str, object]:
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = StatsRepository(session)
            resolved_site_ids = site_ids or repository.list_site_ids()
            profiles = repository.list_profiles()
            instances = repository.list_instances()

            site_scopes = list(resolved_site_ids)
            if include_global:
                site_scopes = [GLOBAL_SITE_SCOPE, *site_scopes]

            counts = {
                "summary": 0,
                "profile": 0,
                "instance": 0,
            }

            for site_scope in site_scopes:
                site_id = None if site_scope == GLOBAL_SITE_SCOPE else site_scope
                summary_payload = self.usage_service.get_usage_summary(site_id=site_id)
                repository.upsert_usage_rollup(
                    rollup_key=self._build_rollup_key(site_scope, "summary", "__summary__"),
                    site_scope=site_scope,
                    scope_kind="summary",
                    scope_id="__summary__",
                    payload_json=summary_payload,
                )
                counts["summary"] += 1

                for profile in profiles:
                    profile_payload = self.usage_service.get_profile_stats(
                        profile.profile_id,
                        site_id=site_id,
                    )
                    repository.upsert_usage_rollup(
                        rollup_key=self._build_rollup_key(
                            site_scope,
                            "profile",
                            profile.profile_id,
                        ),
                        site_scope=site_scope,
                        scope_kind="profile",
                        scope_id=profile.profile_id,
                        payload_json=profile_payload,
                    )
                    counts["profile"] += 1

                for instance in instances:
                    instance_payload = self.usage_service.get_instance_stats(
                        instance.instance_id,
                        site_id=site_id,
                    )
                    repository.upsert_usage_rollup(
                        rollup_key=self._build_rollup_key(
                            site_scope,
                            "instance",
                            instance.instance_id,
                        ),
                        site_scope=site_scope,
                        scope_kind="instance",
                        scope_id=instance.instance_id,
                        payload_json=instance_payload,
                    )
                    counts["instance"] += 1

            session.commit()

        return {
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "site_scopes": site_scopes,
            "counts": counts,
            "rollups_total": sum(counts.values()),
        }

    def store_router_performance_snapshot_batches(
        self,
        *,
        site_ids: list[str],
        start_at: datetime,
        end_at: datetime,
    ) -> dict[str, object]:
        normalized_start = start_at.astimezone(UTC).replace(microsecond=0)
        normalized_end = end_at.astimezone(UTC).replace(microsecond=0)
        if normalized_end <= normalized_start:
            raise ValueError("projection end must be after start")

        now = self.now_factory()
        site_batches: list[dict[str, object]] = []
        scope_id = self._build_router_performance_scope_id(normalized_start, normalized_end)

        with get_session(self.database_url) as session:
            repository = StatsRepository(session)

            for site_id in site_ids:
                payload = self.usage_service.get_router_performance_snapshot_projection(
                    site_id=site_id,
                    start_at=normalized_start,
                    end_at=normalized_end,
                )
                rows = list(payload.get("rows") or [])
                payload["delivery"] = {
                    "owner": "wordpress_fetch_apply",
                    "buffer_kind": "usage_rollup",
                    "scope_kind": ROUTER_PERFORMANCE_BATCH_SCOPE,
                }
                rollup_key = self._build_rollup_key(
                    site_id,
                    ROUTER_PERFORMANCE_BATCH_SCOPE,
                    scope_id,
                )
                repository.upsert_usage_rollup(
                    rollup_key=rollup_key,
                    site_scope=site_id,
                    scope_kind=ROUTER_PERFORMANCE_BATCH_SCOPE,
                    scope_id=scope_id,
                    payload_json=payload,
                )
                site_batches.append(
                    {
                        "site_id": site_id,
                        "rollup_key": rollup_key,
                        "scope_id": scope_id,
                        "rows_total": len(rows),
                        "request_total": sum(int(row.get("request_total") or 0) for row in rows),
                        "success_total": sum(int(row.get("success_total") or 0) for row in rows),
                        "guard_fail_total": sum(
                            int(row.get("guard_fail_total") or 0) for row in rows
                        ),
                        "source": str(payload.get("source") or ""),
                        "window": payload.get("window") or {},
                    }
                )

            session.commit()

        return {
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "window": {
                "start_gmt": normalized_start.strftime("%Y-%m-%d %H:%M:%S"),
                "end_gmt": normalized_end.strftime("%Y-%m-%d %H:%M:%S"),
            },
            "scope_kind": ROUTER_PERFORMANCE_BATCH_SCOPE,
            "delivery_owner": "wordpress_fetch_apply",
            "sites_total": len(site_batches),
            "stored_batches_total": len(site_batches),
            "rows_total": sum(int(item["rows_total"]) for item in site_batches),
            "request_total": sum(int(item["request_total"]) for item in site_batches),
            "success_total": sum(int(item["success_total"]) for item in site_batches),
            "guard_fail_total": sum(int(item["guard_fail_total"]) for item in site_batches),
            "site_batches": site_batches,
        }

    def get_router_performance_snapshot_batch(
        self,
        *,
        site_id: str,
        start_at: datetime,
        end_at: datetime,
    ) -> dict[str, object] | None:
        normalized_start = start_at.astimezone(UTC).replace(microsecond=0)
        normalized_end = end_at.astimezone(UTC).replace(microsecond=0)
        scope_id = self._build_router_performance_scope_id(normalized_start, normalized_end)
        rollup_key = self._build_rollup_key(
            site_id,
            ROUTER_PERFORMANCE_BATCH_SCOPE,
            scope_id,
        )

        with get_session(self.database_url) as session:
            repository = StatsRepository(session)
            rollups = repository.list_usage_rollups(
                site_scope=site_id,
                scope_kind=ROUTER_PERFORMANCE_BATCH_SCOPE,
            )

        for rollup in rollups:
            if getattr(rollup, "rollup_key", "") == rollup_key:
                payload = rollup.payload_json if isinstance(rollup.payload_json, dict) else {}
                if not payload:
                    return None
                payload.setdefault(
                    "delivery",
                    {
                        "owner": "wordpress_fetch_apply",
                        "buffer_kind": "usage_rollup",
                        "scope_kind": ROUTER_PERFORMANCE_BATCH_SCOPE,
                    },
                )
                return payload

        return None

    def store_router_diagnostics_batches(
        self,
        *,
        site_ids: list[str],
        recent_minutes: int,
        config_revision: str = "cloud_runtime_summary_worker",
    ) -> dict[str, object]:
        if recent_minutes <= 0:
            raise ValueError("recent_minutes must be positive")

        now = self.now_factory()
        generated_at = now.astimezone(UTC).replace(microsecond=0)
        scope_id = self._build_router_diagnostics_scope_id(
            generated_at=generated_at,
            recent_minutes=recent_minutes,
        )
        site_batches: list[dict[str, object]] = []

        with get_session(self.database_url) as session:
            repository = StatsRepository(session)

            for site_id in site_ids:
                payload = self.usage_service.get_router_diagnostics_projection(
                    site_id=site_id,
                    config_revision=config_revision,
                    enabled_total=0,
                    tagless_enabled=False,
                    high_risk_count=0,
                    has_warnings=False,
                    recent_minutes=recent_minutes,
                )
                payload["delivery"] = {
                    "owner": "wordpress_fetch_apply",
                    "buffer_kind": "usage_rollup",
                    "scope_kind": ROUTER_DIAGNOSTICS_BATCH_SCOPE,
                }
                report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
                regressions = (
                    report.get("regressions") if isinstance(report.get("regressions"), dict) else {}
                )
                quality = (
                    report.get("quality_regressions")
                    if isinstance(report.get("quality_regressions"), dict)
                    else {}
                )
                rollup_key = self._build_rollup_key(
                    site_id,
                    ROUTER_DIAGNOSTICS_BATCH_SCOPE,
                    scope_id,
                )
                repository.upsert_usage_rollup(
                    rollup_key=rollup_key,
                    site_scope=site_id,
                    scope_kind=ROUTER_DIAGNOSTICS_BATCH_SCOPE,
                    scope_id=scope_id,
                    payload_json=payload,
                )
                site_batches.append(
                    {
                        "site_id": site_id,
                        "rollup_key": rollup_key,
                        "scope_id": scope_id,
                        "regressions_count": int(regressions.get("count") or 0),
                        "quality_regressions_count": int(quality.get("count") or 0),
                        "regression_items_total": len(list(regressions.get("items") or [])),
                        "quality_items_total": len(list(quality.get("items") or [])),
                        "source": str(payload.get("source") or ""),
                        "generated_at": str(payload.get("generated_at") or ""),
                        "stale_after_gmt": str(payload.get("stale_after_gmt") or ""),
                    }
                )

            session.commit()

        return {
            "generated_at": generated_at.strftime("%Y-%m-%d %H:%M:%S"),
            "recent_minutes": recent_minutes,
            "config_revision": config_revision,
            "scope_kind": ROUTER_DIAGNOSTICS_BATCH_SCOPE,
            "delivery_owner": "wordpress_fetch_apply",
            "sites_total": len(site_batches),
            "stored_batches_total": len(site_batches),
            "regressions_total": sum(int(item["regressions_count"]) for item in site_batches),
            "quality_regressions_total": sum(
                int(item["quality_regressions_count"]) for item in site_batches
            ),
            "site_batches": site_batches,
        }

    def get_router_diagnostics_batch(
        self,
        *,
        site_id: str,
        recent_minutes: int,
    ) -> dict[str, object] | None:
        if recent_minutes <= 0:
            raise ValueError("recent_minutes must be positive")

        scope_suffix = f"__{recent_minutes}m"
        with get_session(self.database_url) as session:
            repository = StatsRepository(session)
            rollups = repository.list_usage_rollups(
                site_scope=site_id,
                scope_kind=ROUTER_DIAGNOSTICS_BATCH_SCOPE,
            )

        for rollup in reversed(rollups):
            if not str(getattr(rollup, "scope_id", "")).endswith(scope_suffix):
                continue
            payload = rollup.payload_json if isinstance(rollup.payload_json, dict) else {}
            if not payload:
                return None
            payload.setdefault(
                "delivery",
                {
                    "owner": "wordpress_fetch_apply",
                    "buffer_kind": "usage_rollup",
                    "scope_kind": ROUTER_DIAGNOSTICS_BATCH_SCOPE,
                },
            )
            return payload

        return None

    def store_latency_probe_batches(
        self,
        *,
        site_instances: dict[str, list[str]],
        start_at: datetime,
        end_at: datetime,
    ) -> dict[str, object]:
        normalized_start = start_at.astimezone(UTC).replace(microsecond=0)
        normalized_end = end_at.astimezone(UTC).replace(microsecond=0)
        if normalized_end <= normalized_start:
            raise ValueError("probe end must be after start")

        now = self.now_factory()
        scope_id = self._build_latency_probe_scope_id(
            start_at=normalized_start,
            end_at=normalized_end,
        )
        site_batches: list[dict[str, object]] = []

        with get_session(self.database_url) as session:
            repository = StatsRepository(session)

            for site_id, instance_ids in site_instances.items():
                instances: list[dict[str, object]] = []
                skipped_total = 0
                for instance_id in instance_ids:
                    summary = self.usage_service.get_instance_stats(instance_id, site_id=site_id)
                    source = str(summary.get("source") or "")
                    if source == "empty":
                        skipped_total += 1
                        continue
                    instances.append(
                        {
                            "instance_id": instance_id,
                            "runtime": "hosted_profile",
                            "profile_id": "",
                            "sample_count": int(summary.get("today_calls") or 0),
                            "latency_ms_p50": int(summary.get("latency_ms_p50") or 0),
                            "latency_ms_p95": int(summary.get("latency_ms_p95") or 0),
                            "health": {
                                "status": str(summary.get("health_status") or ""),
                                "score": int(summary.get("health_score") or 0),
                            },
                            "routing": {
                                "latency_tier": "",
                            },
                            "source": "cloud_instance_stats",
                        }
                    )

                payload = {
                    "source": "cloud_latency_probe",
                    "site_id": site_id,
                    "generated_at": normalized_end.strftime("%Y-%m-%d %H:%M:%S"),
                    "window": {
                        "start_gmt": normalized_start.strftime("%Y-%m-%d %H:%M:%S"),
                        "end_gmt": normalized_end.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                    "instances": instances,
                    "delivery": {
                        "owner": "wordpress_fetch_apply",
                        "buffer_kind": "usage_rollup",
                        "scope_kind": LATENCY_PROBE_BATCH_SCOPE,
                    },
                }
                rollup_key = self._build_rollup_key(
                    site_id,
                    LATENCY_PROBE_BATCH_SCOPE,
                    scope_id,
                )
                repository.upsert_usage_rollup(
                    rollup_key=rollup_key,
                    site_scope=site_id,
                    scope_kind=LATENCY_PROBE_BATCH_SCOPE,
                    scope_id=scope_id,
                    payload_json=payload,
                )
                site_batches.append(
                    {
                        "site_id": site_id,
                        "rollup_key": rollup_key,
                        "scope_id": scope_id,
                        "instances_total": len(instances),
                        "skipped_total": skipped_total,
                        "ready_total": len(instances),
                        "healthy_total": sum(
                            1
                            for item in instances
                            if str((item.get("health") or {}).get("status") or "") == "healthy"
                        ),
                        "avg_latency_ms": int(
                            round(
                                sum(
                                    int(item.get("latency_ms_p50") or 0)
                                    for item in instances
                                )
                                / len(instances)
                            )
                        )
                        if instances
                        else 0,
                        "instance_batches": instances,
                    }
                )

            session.commit()

        return {
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "window": {
                "start_gmt": normalized_start.strftime("%Y-%m-%d %H:%M:%S"),
                "end_gmt": normalized_end.strftime("%Y-%m-%d %H:%M:%S"),
            },
            "scope_kind": LATENCY_PROBE_BATCH_SCOPE,
            "delivery_owner": "wordpress_fetch_apply",
            "sites_total": len(site_batches),
            "stored_batches_total": len(site_batches),
            "instances_total": sum(int(item["instances_total"]) for item in site_batches),
            "ready_total": sum(int(item["ready_total"]) for item in site_batches),
            "healthy_total": sum(int(item["healthy_total"]) for item in site_batches),
            "site_batches": site_batches,
        }

    def get_latency_probe_instance_batch(
        self,
        *,
        site_id: str,
        instance_id: str,
    ) -> dict[str, object] | None:
        with get_session(self.database_url) as session:
            repository = StatsRepository(session)
            rollups = repository.list_usage_rollups(
                site_scope=site_id,
                scope_kind=LATENCY_PROBE_BATCH_SCOPE,
            )

        for rollup in reversed(rollups):
            payload = rollup.payload_json if isinstance(rollup.payload_json, dict) else {}
            if not payload:
                continue
            instances = payload.get("instances") if isinstance(payload.get("instances"), list) else []
            for row in instances:
                if not isinstance(row, dict):
                    continue
                if str(row.get("instance_id") or "") != instance_id:
                    continue
                health = row.get("health") if isinstance(row.get("health"), dict) else {}
                generated_at = str(payload.get("generated_at") or "")
                latency_ms = float(row.get("latency_ms_p50") or 0.0)
                latency_ms_p95 = float(row.get("latency_ms_p95") or latency_ms)
                sample_count = int(row.get("sample_count") or 0)
                delivery = payload.get("delivery") if isinstance(payload.get("delivery"), dict) else {}
                return {
                    "status": "ready" if sample_count > 0 else "empty",
                    "error": "",
                    "source": "cloud_latency_probe_buffer",
                    "timezone": "UTC",
                    "generated_at": generated_at,
                    "instance_id": instance_id,
                    "provider_id": "",
                    "model_id": "",
                    "region": "",
                    "endpoint_variant": "",
                    "health_status": str(health.get("status") or ""),
                    "health_reason": "",
                    "health_measured_at": generated_at,
                    "health_score": int(health.get("score") or 0),
                    "health_window_calls": sample_count,
                    "today_calls": sample_count,
                    "success_rate": 0.0,
                    "avg_latency_ms": latency_ms,
                    "latency_ms_p50": latency_ms,
                    "latency_ms_p95": latency_ms_p95,
                    "fallback_rate": 0.0,
                    "windows": {
                        "today": {
                            "start_at": str(((payload.get("window") or {}) if isinstance(payload.get("window"), dict) else {}).get("start_gmt") or ""),
                            "end_at": str(((payload.get("window") or {}) if isinstance(payload.get("window"), dict) else {}).get("end_gmt") or ""),
                            "calls_total": sample_count,
                            "success_total": 0,
                            "error_total": 0,
                            "success_rate": 0.0,
                            "avg_latency_ms": latency_ms,
                            "latency_ms_p50": latency_ms,
                            "latency_ms_p95": latency_ms_p95,
                            "fallback_total": 0,
                            "fallback_rate": 0.0,
                            "last_seen_at": generated_at,
                        },
                        "rolling_24h": {
                            "start_at": str(((payload.get("window") or {}) if isinstance(payload.get("window"), dict) else {}).get("start_gmt") or ""),
                            "end_at": str(((payload.get("window") or {}) if isinstance(payload.get("window"), dict) else {}).get("end_gmt") or ""),
                            "calls_total": sample_count,
                            "success_total": 0,
                            "error_total": 0,
                            "success_rate": 0.0,
                            "avg_latency_ms": latency_ms,
                            "latency_ms_p50": latency_ms,
                            "latency_ms_p95": latency_ms_p95,
                            "fallback_total": 0,
                            "fallback_rate": 0.0,
                            "last_seen_at": generated_at,
                        },
                    },
                    "delivery": {
                        "owner": str(delivery.get("owner") or "wordpress_fetch_apply"),
                        "buffer_kind": str(delivery.get("buffer_kind") or "usage_rollup"),
                        "scope_kind": str(delivery.get("scope_kind") or LATENCY_PROBE_BATCH_SCOPE),
                    },
                }

        return None

    def store_alert_provider_degradation_batches(
        self,
        *,
        site_ids: list[str],
        window_minutes: int,
        min_requests: int,
        error_rate_threshold: float,
        latency_ms_threshold: int,
    ) -> dict[str, object]:
        if window_minutes <= 0:
            raise ValueError("window_minutes must be positive")

        now = self.now_factory()
        generated_at = now.astimezone(UTC).replace(microsecond=0)
        start_at = generated_at - timedelta(minutes=window_minutes)
        scope_id = self._build_alert_evaluate_scope_id(
            start_at=start_at,
            end_at=generated_at,
        )
        site_batches: list[dict[str, object]] = []

        with get_session(self.database_url) as session:
            repository = StatsRepository(session)

            for site_id in site_ids:
                payload = self.usage_service.get_alert_provider_degradation_projection(
                    site_id=site_id,
                    window_minutes=window_minutes,
                    min_requests=min_requests,
                    error_rate_threshold=error_rate_threshold,
                    latency_ms_threshold=latency_ms_threshold,
                )
                payload["delivery"] = {
                    "owner": "wordpress_fetch_apply",
                    "buffer_kind": "usage_rollup",
                    "scope_kind": ALERT_EVALUATE_BATCH_SCOPE,
                }
                events = list(payload.get("events") or [])
                rollup_key = self._build_rollup_key(
                    site_id,
                    ALERT_EVALUATE_BATCH_SCOPE,
                    scope_id,
                )
                repository.upsert_usage_rollup(
                    rollup_key=rollup_key,
                    site_scope=site_id,
                    scope_kind=ALERT_EVALUATE_BATCH_SCOPE,
                    scope_id=scope_id,
                    payload_json=payload,
                )
                site_batches.append(
                    {
                        "site_id": site_id,
                        "rollup_key": rollup_key,
                        "scope_id": scope_id,
                        "events_total": len(events),
                        "touched_rule_types": list(payload.get("touched_rule_types") or []),
                        "providers": [
                            str(((event.get("summary") or {}).get("provider") or "")).strip()
                            for event in events
                        ],
                        "window": payload.get("window") or {},
                        "source": str(payload.get("source") or ""),
                    }
                )

            session.commit()

        return {
            "generated_at": generated_at.strftime("%Y-%m-%d %H:%M:%S"),
            "window": {
                "start_gmt": start_at.strftime("%Y-%m-%d %H:%M:%S"),
                "end_gmt": generated_at.strftime("%Y-%m-%d %H:%M:%S"),
            },
            "scope_kind": ALERT_EVALUATE_BATCH_SCOPE,
            "delivery_owner": "wordpress_fetch_apply",
            "sites_total": len(site_batches),
            "stored_batches_total": len(site_batches),
            "events_total": sum(int(item["events_total"]) for item in site_batches),
            "site_batches": site_batches,
        }

    def store_alert_provider_degradation_batches(
        self,
        *,
        site_ids: list[str],
        window_minutes: int,
        min_requests: int,
        error_rate_threshold: float,
        latency_ms_threshold: int,
    ) -> dict[str, object]:
        if window_minutes <= 0:
            raise ValueError("window_minutes must be positive")

        now = self.now_factory()
        generated_at = now.astimezone(UTC).replace(microsecond=0)
        start_at = generated_at - timedelta(minutes=window_minutes)
        scope_id = self._build_alert_evaluate_scope_id(
            start_at=start_at,
            end_at=generated_at,
        )
        site_batches: list[dict[str, object]] = []

        with get_session(self.database_url) as session:
            repository = StatsRepository(session)

            for site_id in site_ids:
                payload = self.usage_service.get_alert_provider_degradation_projection(
                    site_id=site_id,
                    window_minutes=window_minutes,
                    min_requests=min_requests,
                    error_rate_threshold=error_rate_threshold,
                    latency_ms_threshold=latency_ms_threshold,
                )
                payload["delivery"] = {
                    "owner": "wordpress_fetch_apply",
                    "buffer_kind": "usage_rollup",
                    "scope_kind": ALERT_EVALUATE_BATCH_SCOPE,
                }
                events = list(payload.get("events") or [])
                rollup_key = self._build_rollup_key(
                    site_id,
                    ALERT_EVALUATE_BATCH_SCOPE,
                    scope_id,
                )
                repository.upsert_usage_rollup(
                    rollup_key=rollup_key,
                    site_scope=site_id,
                    scope_kind=ALERT_EVALUATE_BATCH_SCOPE,
                    scope_id=scope_id,
                    payload_json=payload,
                )
                site_batches.append(
                    {
                        "site_id": site_id,
                        "rollup_key": rollup_key,
                        "scope_id": scope_id,
                        "events_total": len(events),
                        "touched_rule_types": list(payload.get("touched_rule_types") or []),
                        "providers": [
                            str(((event.get("summary") or {}).get("provider") or "")).strip()
                            for event in events
                        ],
                        "window": payload.get("window") or {},
                        "source": str(payload.get("source") or ""),
                    }
                )

            session.commit()

        return {
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "window": {
                "start_gmt": start_at.strftime("%Y-%m-%d %H:%M:%S"),
                "end_gmt": generated_at.strftime("%Y-%m-%d %H:%M:%S"),
            },
            "scope_kind": ALERT_EVALUATE_BATCH_SCOPE,
            "delivery_owner": "wordpress_fetch_apply",
            "sites_total": len(site_batches),
            "stored_batches_total": len(site_batches),
            "events_total": sum(int(item["events_total"]) for item in site_batches),
            "site_batches": site_batches,
        }

    def get_alert_provider_degradation_batch(
        self,
        *,
        site_id: str,
        window_minutes: int,
    ) -> dict[str, object] | None:
        if window_minutes <= 0:
            raise ValueError("window_minutes must be positive")

        with get_session(self.database_url) as session:
            repository = StatsRepository(session)
            rollups = repository.list_usage_rollups(
                site_scope=site_id,
                scope_kind=ALERT_EVALUATE_BATCH_SCOPE,
            )

        for rollup in reversed(rollups):
            payload = rollup.payload_json if isinstance(rollup.payload_json, dict) else {}
            if not payload:
                continue
            window = payload.get("window") if isinstance(payload.get("window"), dict) else {}
            start_gmt = str(window.get("start_gmt") or "")
            end_gmt = str(window.get("end_gmt") or "")
            if not start_gmt or not end_gmt:
                continue
            try:
                start_at = datetime.strptime(start_gmt, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                end_at = datetime.strptime(end_gmt, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            except ValueError:
                continue
            if int((end_at - start_at).total_seconds() // 60) != int(window_minutes):
                continue
            payload.setdefault(
                "delivery",
                {
                    "owner": "wordpress_fetch_apply",
                    "buffer_kind": "usage_rollup",
                    "scope_kind": ALERT_EVALUATE_BATCH_SCOPE,
                },
            )
            return payload

        return None

    def get_alert_provider_degradation_batch(
        self,
        *,
        site_id: str,
        window_minutes: int,
    ) -> dict[str, object] | None:
        if window_minutes <= 0:
            raise ValueError("window_minutes must be positive")

        with get_session(self.database_url) as session:
            repository = StatsRepository(session)
            rollups = repository.list_usage_rollups(
                site_scope=site_id,
                scope_kind=ALERT_EVALUATE_BATCH_SCOPE,
            )

        for rollup in reversed(rollups):
            payload = rollup.payload_json if isinstance(rollup.payload_json, dict) else {}
            if not payload:
                continue
            window = payload.get("window") if isinstance(payload.get("window"), dict) else {}
            start_gmt = str(window.get("start_gmt") or "")
            end_gmt = str(window.get("end_gmt") or "")
            if not start_gmt or not end_gmt:
                continue
            try:
                start_at = datetime.strptime(start_gmt, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                end_at = datetime.strptime(end_gmt, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            except ValueError:
                continue
            if int((end_at - start_at).total_seconds() // 60) != int(window_minutes):
                continue
            payload.setdefault(
                "delivery",
                {
                    "owner": "wordpress_fetch_apply",
                    "buffer_kind": "usage_rollup",
                    "scope_kind": ALERT_EVALUATE_BATCH_SCOPE,
                },
            )
            return payload

        return None

    def _build_rollup_key(
        self,
        site_scope: str,
        scope_kind: str,
        scope_id: str,
    ) -> str:
        return f"{site_scope}:{scope_kind}:{scope_id}"

    def _build_router_performance_scope_id(
        self,
        start_at: datetime,
        end_at: datetime,
    ) -> str:
        return (
            f"{start_at.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            f"__{end_at.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )

    def _build_router_diagnostics_scope_id(
        self,
        *,
        generated_at: datetime,
        recent_minutes: int,
    ) -> str:
        return (
            f"{generated_at.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            f"__{recent_minutes}m"
        )

    def _build_latency_probe_scope_id(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> str:
        return (
            f"{start_at.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            f"__{end_at.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )

    def _build_alert_evaluate_scope_id(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> str:
        return (
            f"{start_at.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            f"__{end_at.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )

    def _build_alert_evaluate_scope_id(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> str:
        return (
            f"{start_at.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            f"__{end_at.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )
