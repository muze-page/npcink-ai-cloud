from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from app.adapters.providers.registry import resolve_live_provider_adapters
from app.core.config import Settings, get_settings
from app.core.db import require_database_connection
from app.core.logging import configure_logging, get_logger
from app.domain.catalog.service import CatalogService
from app.domain.commercial.service import CommercialService, ServiceAuditContext
from app.domain.observability.plugin_events import PluginObservabilityService
from app.domain.runtime.service import RuntimeService
from app.domain.usage.rollup import UsageRollupService
from app.workers.alert_provider_degradation import run_once as run_alert_provider_degradation
from app.workers.heartbeat import WorkerHeartbeat
from app.workers.latency_probe_summary import run_once as run_latency_probe_summary
from app.workers.router_diagnostics_summary import run_once as run_router_diagnostics_summary

CADENCE_SCOPE_KIND = "ops_cadence"
CADENCE_SCOPE_ID = "managed"


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return default


def _dict_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


@dataclass(frozen=True)
class CadenceTaskSpec:
    task_id: str
    event_kind: str
    interval_seconds: Callable[[Settings], int]
    runner: Callable[[Settings], dict[str, object]]


def _run_retention_cleanup(settings: Settings) -> dict[str, object]:
    purged_runs = RuntimeService(
        settings.database_url,
        settings=settings,
    ).cleanup_expired_run_results()
    return {"purged_runs": purged_runs}


def _run_plugin_observability_cleanup(settings: Settings) -> dict[str, object]:
    return PluginObservabilityService(settings.database_url).cleanup_expired_events(
        retention_days=settings.plugin_observability_retention_days,
    )


def _run_usage_rollup(settings: Settings) -> dict[str, object]:
    result = UsageRollupService(settings.database_url).generate_rollups()
    return {
        "rollups_total": _coerce_int(result.get("rollups_total")),
        "sites_total": _coerce_int(result.get("sites_total")),
        "profile_rollups_total": _coerce_int(result.get("profile_rollups_total")),
        "instance_rollups_total": _coerce_int(result.get("instance_rollups_total")),
    }


def _run_router_diagnostics_summary(settings: Settings) -> dict[str, object]:
    result = run_router_diagnostics_summary(settings)
    return {
        "sites_total": int(result.get("sites_total") or 0),
        "stored_batches_total": int(result.get("stored_batches_total") or 0),
        "callback_attempted_total": int(result.get("callback_attempted_total") or 0),
        "callback_delivered_total": int(result.get("callback_delivered_total") or 0),
        "callback_failed_total": int(result.get("callback_failed_total") or 0),
        "callback_skipped_total": int(result.get("callback_skipped_total") or 0),
        "rollup_scope_kind": str(result.get("rollup_scope_kind") or ""),
    }


def _run_latency_probe_summary(settings: Settings) -> dict[str, object]:
    result = run_latency_probe_summary(settings)
    return {
        "sites_total": int(result.get("sites_total") or 0),
        "stored_batches_total": int(result.get("stored_batches_total") or 0),
        "instances_total": int(result.get("instances_total") or 0),
        "ready_total": int(result.get("ready_total") or 0),
        "healthy_total": int(result.get("healthy_total") or 0),
        "rollup_scope_kind": str(result.get("rollup_scope_kind") or ""),
    }


def _run_alert_provider_degradation_summary(settings: Settings) -> dict[str, object]:
    result = run_alert_provider_degradation(settings)
    return {
        "sites_total": int(result.get("sites_total") or 0),
        "stored_batches_total": int(result.get("stored_batches_total") or 0),
        "events_total": int(result.get("events_total") or 0),
        "rollup_scope_kind": str(result.get("rollup_scope_kind") or ""),
    }


def _run_provider_health_scan(settings: Settings) -> dict[str, object]:
    result = CatalogService(
        settings.database_url,
        providers=resolve_live_provider_adapters(
            settings,
            include_enabled_connections=True,
        ),
    ).scan_provider_health()
    return {
        "providers_total": len(list(result.get("providers") or [])),
        "scanned_count": int(result.get("scanned_count") or 0),
        "status_counts": dict(result.get("status_counts") or {}),
    }


def _run_artifact_cleanup(settings: Settings) -> dict[str, object]:
    from app.domain.media_derivatives.artifacts import cleanup_expired_artifacts

    purged = cleanup_expired_artifacts(database_url=settings.database_url)
    return {"purged_artifacts": purged}


def cadence_task_specs() -> list[CadenceTaskSpec]:
    return [
        CadenceTaskSpec(
            task_id="retention_cleanup",
            event_kind="runtime.retention_cleanup.cadence",
            interval_seconds=lambda settings: settings.retention_cleanup_interval_seconds,
            runner=_run_retention_cleanup,
        ),
        CadenceTaskSpec(
            task_id="plugin_observability_cleanup",
            event_kind="plugin_observability.retention_cleanup.cadence",
            interval_seconds=lambda settings: (
                settings.plugin_observability_cleanup_interval_seconds
            ),
            runner=_run_plugin_observability_cleanup,
        ),
        CadenceTaskSpec(
            task_id="usage_rollup",
            event_kind="usage.rollup_cadence",
            interval_seconds=lambda settings: settings.usage_rollup_interval_seconds,
            runner=_run_usage_rollup,
        ),
        CadenceTaskSpec(
            task_id="router_diagnostics_summary",
            event_kind="router.diagnostics_summary_cadence",
            interval_seconds=lambda settings: settings.router_diagnostics_interval_seconds,
            runner=_run_router_diagnostics_summary,
        ),
        CadenceTaskSpec(
            task_id="latency_probe_summary",
            event_kind="latency.probe_summary_cadence",
            interval_seconds=lambda settings: settings.latency_probe_interval_seconds,
            runner=_run_latency_probe_summary,
        ),
        CadenceTaskSpec(
            task_id="alert_provider_degradation",
            event_kind="alert.provider_degradation_cadence",
            interval_seconds=lambda settings: settings.alert_provider_degradation_interval_seconds,
            runner=_run_alert_provider_degradation_summary,
        ),
        CadenceTaskSpec(
            task_id="provider_health_scan",
            event_kind="provider.health_scan_cadence",
            interval_seconds=lambda settings: settings.provider_health_scan_interval_seconds,
            runner=_run_provider_health_scan,
        ),
        CadenceTaskSpec(
            task_id="artifact_cleanup",
            event_kind="runtime.artifact_cleanup.cadence",
            interval_seconds=lambda s: s.artifact_cleanup_interval_seconds,
            runner=_run_artifact_cleanup,
        ),
    ]


def _audit_context(task_id: str) -> ServiceAuditContext:
    return ServiceAuditContext(
        trace_id="",
        idempotency_key="",
        method="POST",
        path=f"/internal/workers/ops-cadence/{task_id}",
        actor_kind="system_worker",
        actor_ref="ops_cadence",
    )


def _parse_timestamp(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _latest_event(
    commercial_service: CommercialService,
    *,
    event_kind: str,
    outcome: str | None = None,
) -> dict[str, object] | None:
    result = commercial_service.list_service_audit_events(
        event_kind=event_kind,
        outcome=outcome,
        limit=1,
    )
    items = result.get("items")
    if not isinstance(items, list) or not items:
        return None
    item = items[0]
    return item if isinstance(item, dict) else None


def build_cadence_summary(
    settings: Settings,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    commercial_service = CommercialService(settings.database_url, settings=settings)
    items: list[dict[str, object]] = []

    for spec in cadence_task_specs():
        interval_seconds = max(60, int(spec.interval_seconds(settings)))
        last_event = _latest_event(commercial_service, event_kind=spec.event_kind)
        last_success = _latest_event(
            commercial_service,
            event_kind=spec.event_kind,
            outcome="succeeded",
        )
        last_error = _latest_event(
            commercial_service,
            event_kind=spec.event_kind,
            outcome="error",
        )
        last_run_at = _parse_timestamp((last_event or {}).get("created_at"))
        age_seconds = (
            max(0, int((current_time - last_run_at).total_seconds()))
            if last_run_at is not None
            else None
        )
        if last_run_at is None:
            freshness = "missing"
        elif age_seconds is not None and age_seconds > interval_seconds * 2:
            freshness = "stale"
        elif age_seconds is not None and age_seconds > interval_seconds:
            freshness = "attention"
        else:
            freshness = "fresh"

        last_error_payload = _dict_value(_dict_value(last_error).get("payload"))
        last_error_at_value = str((last_error or {}).get("created_at") or "")
        last_error_message = str(last_error_payload.get("message") or "")
        last_error_code = str(last_error_payload.get("error_code") or "")
        if last_event is not None and str((last_event or {}).get("outcome") or "") == "succeeded":
            last_error_at_value = ""
            last_error_message = ""
            last_error_code = ""
        items.append(
            {
                "task_id": spec.task_id,
                "event_kind": spec.event_kind,
                "interval_seconds": interval_seconds,
                "freshness": freshness,
                "last_outcome": str((last_event or {}).get("outcome") or ""),
                "last_run_at": str((last_event or {}).get("created_at") or ""),
                "last_success_at": str((last_success or {}).get("created_at") or ""),
                "last_error_at": last_error_at_value,
                "last_error_message": last_error_message,
                "last_error_code": last_error_code,
                "age_seconds": age_seconds if age_seconds is not None else -1,
            }
        )

    stale_total = sum(1 for item in items if item["freshness"] in {"attention", "stale", "missing"})
    return {
        "generated_at": current_time.isoformat().replace("+00:00", "Z"),
        "items": items,
        "totals": {
            "tasks_total": len(items),
            "fresh_total": sum(1 for item in items if item["freshness"] == "fresh"),
            "attention_total": sum(1 for item in items if item["freshness"] == "attention"),
            "stale_total": sum(1 for item in items if item["freshness"] == "stale"),
            "missing_total": sum(1 for item in items if item["freshness"] == "missing"),
            "non_fresh_total": stale_total,
        },
    }


def run_due_tasks(
    settings: Settings,
    *,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    commercial_service = CommercialService(settings.database_url, settings=settings)
    logger = get_logger("npcink_ai_cloud.ops_cadence")
    results: list[dict[str, object]] = []

    for spec in cadence_task_specs():
        interval_seconds = max(60, int(spec.interval_seconds(settings)))
        last_event = _latest_event(commercial_service, event_kind=spec.event_kind)
        last_run_at = _parse_timestamp((last_event or {}).get("created_at"))
        due = last_run_at is None or current_time >= (
            last_run_at + timedelta(seconds=interval_seconds)
        )
        if not due:
            continue

        try:
            payload = dict(spec.runner(settings))
            payload["interval_seconds"] = interval_seconds
            commercial_service.record_service_audit_event(
                audit_context=_audit_context(spec.task_id),
                event_kind=spec.event_kind,
                outcome="succeeded",
                scope_kind=CADENCE_SCOPE_KIND,
                scope_id=spec.task_id,
                payload_json=payload,
            )
            result: dict[str, object] = {
                "task_id": spec.task_id,
                "event_kind": spec.event_kind,
                "outcome": "succeeded",
                "payload": payload,
            }
            results.append(result)
            logger.info("ops cadence task succeeded: %s", result)
        except Exception as error:
            payload = {
                "interval_seconds": interval_seconds,
                "message": str(error),
                "error_code": "ops.cadence_task_failed",
            }
            commercial_service.record_service_audit_event(
                audit_context=_audit_context(spec.task_id),
                event_kind=spec.event_kind,
                outcome="error",
                scope_kind=CADENCE_SCOPE_KIND,
                scope_id=spec.task_id,
                payload_json=payload,
            )
            error_result: dict[str, object] = {
                "task_id": spec.task_id,
                "event_kind": spec.event_kind,
                "outcome": "error",
                "payload": payload,
            }
            results.append(error_result)
            logger.exception("ops cadence task failed: task_id=%s", spec.task_id)

    return results


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    require_database_connection(settings.database_url)
    logger = get_logger("npcink_ai_cloud.ops_cadence")
    heartbeat = WorkerHeartbeat(
        settings=settings,
        worker_id="ops_cadence",
        interval_seconds=settings.worker_heartbeat_interval_seconds,
    )
    task_ids = [spec.task_id for spec in cadence_task_specs()]
    logger.info(
        "ops cadence worker started (poll=%ss, tasks=%s)",
        settings.ops_cadence_poll_seconds,
        task_ids,
    )
    heartbeat.maybe_record(
        status="started",
        payload={"tasks": task_ids},
        force=True,
    )

    while True:
        results = run_due_tasks(settings)
        heartbeat.maybe_record(
            status="processed" if results else "idle",
            payload={"tasks_executed": len(results)},
        )
        time.sleep(settings.ops_cadence_poll_seconds)


if __name__ == "__main__":
    main()
