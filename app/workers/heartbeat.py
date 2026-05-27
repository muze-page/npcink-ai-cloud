from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.config import Settings
from app.domain.commercial.service import CommercialService, ServiceAuditContext

WORKER_HEARTBEAT_EVENT_KIND = "worker.heartbeat"
WORKER_SCOPE_KIND = "worker"
EXPECTED_WORKER_IDS = (
    "runtime_queue",
    "callback_dispatch",
    "ops_cadence",
)


def expected_worker_ids(settings: Settings) -> tuple[str, ...]:
    return EXPECTED_WORKER_IDS


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


def _audit_context(worker_id: str) -> ServiceAuditContext:
    return ServiceAuditContext(
        trace_id="",
        idempotency_key="",
        method="POST",
        path=f"/internal/workers/{worker_id}/heartbeat",
        actor_kind="system_worker",
        actor_ref=worker_id,
    )


def record_worker_heartbeat(
    settings: Settings,
    *,
    worker_id: str,
    status: str = "idle",
    payload: dict[str, object] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    heartbeat_payload = {
        "worker_id": worker_id,
        "status": status,
        "recorded_at": current_time.isoformat().replace("+00:00", "Z"),
        **(payload or {}),
    }
    CommercialService(settings.database_url, settings=settings).record_service_audit_event(
        audit_context=_audit_context(worker_id),
        event_kind=WORKER_HEARTBEAT_EVENT_KIND,
        outcome="succeeded",
        scope_kind=WORKER_SCOPE_KIND,
        scope_id=worker_id,
        payload_json=heartbeat_payload,
    )
    return heartbeat_payload


@dataclass
class WorkerHeartbeat:
    settings: Settings
    worker_id: str
    interval_seconds: int
    last_recorded_at: datetime | None = None

    def maybe_record(
        self,
        *,
        status: str,
        payload: dict[str, object] | None = None,
        now: datetime | None = None,
        force: bool = False,
    ) -> bool:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        if not force and self.last_recorded_at is not None:
            age_seconds = (current_time - self.last_recorded_at).total_seconds()
            if age_seconds < self.interval_seconds:
                return False
        record_worker_heartbeat(
            self.settings,
            worker_id=self.worker_id,
            status=status,
            payload=payload,
            now=current_time,
        )
        self.last_recorded_at = current_time
        return True


def build_worker_heartbeat_summary(
    settings: Settings,
    *,
    worker_ids: tuple[str, ...] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    effective_worker_ids = worker_ids or expected_worker_ids(settings)
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    interval_seconds = max(30, int(settings.worker_heartbeat_interval_seconds))
    stale_after_seconds = interval_seconds * 2
    heartbeat_events = CommercialService(
        settings.database_url,
        settings=settings,
    ).list_service_audit_events(
        event_kind=WORKER_HEARTBEAT_EVENT_KIND,
        outcome="succeeded",
        limit=max(20, len(effective_worker_ids) * 10),
    )["items"]

    latest_by_worker: dict[str, dict[str, object]] = {}
    for event in heartbeat_events:
        if not isinstance(event, dict):
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        worker_id = str(payload.get("worker_id") or event.get("scope_id") or "").strip()
        if not worker_id or worker_id in latest_by_worker:
            continue
        latest_by_worker[worker_id] = event

    items: list[dict[str, object]] = []
    for worker_id in effective_worker_ids:
        event = latest_by_worker.get(worker_id)
        payload = event.get("payload") if isinstance(event, dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        recorded_at = _parse_timestamp(payload.get("recorded_at") or (event or {}).get("created_at"))
        age_seconds = (
            max(0, int((current_time - recorded_at).total_seconds()))
            if recorded_at is not None
            else -1
        )
        if recorded_at is None:
            freshness = "missing"
        elif age_seconds > stale_after_seconds:
            freshness = "stale"
        elif age_seconds > interval_seconds:
            freshness = "attention"
        else:
            freshness = "fresh"
        items.append(
            {
                "worker_id": worker_id,
                "freshness": freshness,
                "status": str(payload.get("status") or ""),
                "last_seen_at": str(payload.get("recorded_at") or (event or {}).get("created_at") or ""),
                "age_seconds": age_seconds,
            }
        )

    return {
        "generated_at": current_time.isoformat().replace("+00:00", "Z"),
        "interval_seconds": interval_seconds,
        "stale_after_seconds": stale_after_seconds,
        "items": items,
        "totals": {
            "workers_total": len(items),
            "fresh_total": sum(1 for item in items if item["freshness"] == "fresh"),
            "attention_total": sum(1 for item in items if item["freshness"] == "attention"),
            "stale_total": sum(1 for item in items if item["freshness"] == "stale"),
            "missing_total": sum(1 for item in items if item["freshness"] == "missing"),
        },
    }
