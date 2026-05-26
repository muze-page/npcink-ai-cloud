from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.adapters.repositories.stats_repository import StatsRepository
from app.core.config import Settings
from app.core.db import get_session
from app.core.feature_flags import EnvFeatureFlagProvider
from app.core.services import ReadyReport
from app.domain.runtime.service import RuntimeService
from app.workers.heartbeat import build_worker_heartbeat_summary, expected_worker_ids
from app.workers.ops_cadence import build_cadence_summary

STRICT_CADENCE_TASK_IDS = (
    "retention_cleanup",
    "usage_rollup",
    "router_diagnostics_summary",
    "latency_probe_summary",
    "alert_provider_degradation",
    "provider_health_scan",
)


class ObservabilityService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_summary(
        self,
        *,
        ready_report: ReadyReport,
        recent_minutes: int = 60,
        backlog_limit: int = 10,
        now: datetime | None = None,
    ) -> dict[str, object]:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        runtime_service = RuntimeService(self.settings.database_url, settings=self.settings)
        cadence = build_cadence_summary(self.settings, now=current_time)
        workers = build_worker_heartbeat_summary(self.settings, now=current_time)
        providers = self._build_provider_health_summary(current_time)
        feature_flags = EnvFeatureFlagProvider(self.settings).build_summary()
        runtime = runtime_service.get_runtime_diagnostics_summary(
            recent_minutes=recent_minutes,
        )
        backlog = runtime_service.get_runtime_backlog_diagnostics(
            scope_kind="site_id",
            limit=backlog_limit,
        )
        return {
            "generated_at": current_time.isoformat().replace("+00:00", "Z"),
            "ready": {
                "status": "ok" if ready_report.ok else "error",
                "checks": ready_report.checks,
                "details": ready_report.details,
            },
            "tracing": {
                "service_name": self.settings.otel_service_name,
                "otlp_endpoint": str(self.settings.otel_exporter_otlp_endpoint or ""),
                "otlp_configured": bool(str(self.settings.otel_exporter_otlp_endpoint or "").strip()),
                "trace_sink_otlp_endpoint": str(self.settings.otel_trace_sink_otlp_endpoint or ""),
                "trace_sink_query_url": str(self.settings.otel_trace_query_url or ""),
                "trace_sink_configured": bool(
                    str(self.settings.otel_trace_sink_otlp_endpoint or "").strip()
                ),
            },
            "workers": workers,
            "cadence": cadence,
            "providers": providers,
            "feature_flags": feature_flags,
            "runtime": {
                "summary": runtime,
                "backlog": backlog,
            },
        }

    def build_operational_readiness(
        self,
        *,
        ready_report: ReadyReport,
        now: datetime | None = None,
    ) -> dict[str, object]:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        summary = self.build_summary(
            ready_report=ready_report,
            recent_minutes=60,
            backlog_limit=10,
            now=current_time,
        )
        workers = summary["workers"] if isinstance(summary.get("workers"), dict) else {}
        worker_items = workers.get("items") if isinstance(workers.get("items"), list) else []
        worker_freshness = {
            str(item.get("worker_id") or ""): str(item.get("freshness") or "")
            for item in worker_items
            if isinstance(item, dict)
        }
        cadence = summary["cadence"] if isinstance(summary.get("cadence"), dict) else {}
        cadence_items = cadence.get("items") if isinstance(cadence.get("items"), list) else []
        cadence_freshness = {
            str(item.get("task_id") or ""): str(item.get("freshness") or "")
            for item in cadence_items
            if isinstance(item, dict)
        }
        providers = summary["providers"] if isinstance(summary.get("providers"), dict) else {}

        required_worker_ids = expected_worker_ids(self.settings)
        worker_checks = {
            f"worker.{worker_id}.fresh": worker_freshness.get(worker_id) == "fresh"
            for worker_id in required_worker_ids
        }
        cadence_checks = {
            f"cadence.{task_id}.fresh": cadence_freshness.get(task_id) == "fresh"
            for task_id in STRICT_CADENCE_TASK_IDS
        }
        checks = {
            "dependencies.ready": ready_report.ok,
            "providers.fresh": str(providers.get("freshness") or "") == "fresh",
            **worker_checks,
            **cadence_checks,
        }
        details = {
            "dependencies.ready": "database and redis dependency checks passed"
            if ready_report.ok
            else "database or redis dependency checks failed",
            "providers.fresh": (
                f"provider health freshness={str(providers.get('freshness') or 'missing')}"
            ),
        }
        for worker_id in required_worker_ids:
            details[f"worker.{worker_id}.fresh"] = (
                f"worker freshness={worker_freshness.get(worker_id, 'missing')}"
            )
        for task_id in STRICT_CADENCE_TASK_IDS:
            details[f"cadence.{task_id}.fresh"] = (
                f"cadence freshness={cadence_freshness.get(task_id, 'missing')}"
            )
        return {
            "generated_at": current_time.isoformat().replace("+00:00", "Z"),
            "ok": all(checks.values()),
            "checks": checks,
            "details": details,
            "required_workers": list(required_worker_ids),
            "required_cadence_tasks": list(STRICT_CADENCE_TASK_IDS),
            "summary": summary,
        }

    def _build_provider_health_summary(
        self,
        current_time: datetime,
    ) -> dict[str, object]:
        with get_session(self.settings.database_url) as session:
            repository = StatsRepository(session)
            instances = repository.list_instances()
            health_snapshots = repository.list_health_snapshots()

        latest_by_instance: dict[str, Any] = {}
        for snapshot in health_snapshots:
            current = latest_by_instance.get(snapshot.instance_id)
            if current is None or snapshot.measured_at > current.measured_at:
                latest_by_instance[snapshot.instance_id] = snapshot

        status_counts = {
            "healthy": 0,
            "degraded": 0,
            "unhealthy": 0,
            "unknown": 0,
        }
        degraded_provider_ids: set[str] = set()
        last_measured_at: datetime | None = None
        for instance in instances:
            snapshot = latest_by_instance.get(instance.instance_id)
            status = str(getattr(snapshot, "status", "unknown") or "unknown")
            if status not in status_counts:
                status = "unknown"
            status_counts[status] += 1
            if status in {"degraded", "unhealthy"}:
                degraded_provider_ids.add(str(instance.provider_id))
            measured_at = self._normalize_datetime(getattr(snapshot, "measured_at", None))
            if measured_at is not None and (
                last_measured_at is None or measured_at > last_measured_at
            ):
                last_measured_at = measured_at

        last_measured_at = self._normalize_datetime(last_measured_at)
        age_seconds = (
            max(0, int((current_time - last_measured_at).total_seconds()))
            if last_measured_at is not None
            else -1
        )
        interval_seconds = max(60, int(self.settings.provider_health_scan_interval_seconds))
        if last_measured_at is None:
            freshness = "missing"
        elif age_seconds > interval_seconds * 2:
            freshness = "stale"
        elif age_seconds > interval_seconds:
            freshness = "attention"
        else:
            freshness = "fresh"
        return {
            "interval_seconds": interval_seconds,
            "freshness": freshness,
            "last_measured_at": (
                last_measured_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
                if last_measured_at is not None
                else ""
            ),
            "age_seconds": age_seconds,
            "providers_total": len({instance.provider_id for instance in instances}),
            "instances_total": len(instances),
            "status_counts": status_counts,
            "degraded_provider_ids": sorted(degraded_provider_ids),
        }

    def _normalize_datetime(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
