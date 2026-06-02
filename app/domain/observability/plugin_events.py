from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, desc, func, select

from app.core.db import get_session
from app.core.models import PluginObservabilityEvent

ALLOWED_EVENT_FIELDS = {
    "schema_version",
    "plugin_slug",
    "plugin_version",
    "source",
    "event_kind",
    "event_id",
    "emitted_at",
    "captured_at",
    "status",
    "status_detail",
    "error_code",
    "latency_ms",
    "ability_id",
    "proposal_id",
    "correlation_id",
    "adapter_request_id",
    "method",
    "route",
    "status_code",
    "mode",
    "deduplicated",
    "proposal_count",
    "blocked_count",
    "executed_count",
    "failed_count",
}


class PluginObservabilityService:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def ingest_events(
        self,
        *,
        site_id: str,
        key_id: str,
        events: list[dict[str, Any]],
        received_at: datetime | None = None,
    ) -> dict[str, object]:
        current_time = (received_at or datetime.now(UTC)).astimezone(UTC)
        normalized_events = [
            self._normalize_event(site_id=site_id, key_id=key_id, event=event)
            for event in events
        ]
        dedupe_keys = [event["dedupe_key"] for event in normalized_events]

        with get_session(self.database_url) as session:
            existing = set(
                session.scalars(
                    select(PluginObservabilityEvent.dedupe_key).where(
                        PluginObservabilityEvent.dedupe_key.in_(dedupe_keys)
                    )
                )
            )
            stored_count = 0
            for event in normalized_events:
                if event["dedupe_key"] in existing:
                    continue
                session.add(
                    PluginObservabilityEvent(
                        dedupe_key=str(event["dedupe_key"]),
                        site_id=site_id,
                        key_id=key_id or None,
                        schema_version=str(event.get("schema_version") or ""),
                        plugin_slug=str(event.get("plugin_slug") or ""),
                        plugin_version=str(event.get("plugin_version") or "") or None,
                        source=str(event.get("source") or "local"),
                        event_kind=str(event.get("event_kind") or ""),
                        event_id=str(event.get("event_id") or "") or None,
                        status=str(event.get("status") or "") or None,
                        status_detail=str(event.get("status_detail") or "") or None,
                        error_code=str(event.get("error_code") or "") or None,
                        latency_ms=self._optional_int(event.get("latency_ms")),
                        ability_id=str(event.get("ability_id") or "") or None,
                        proposal_id=str(event.get("proposal_id") or "") or None,
                        correlation_id=str(event.get("correlation_id") or "") or None,
                        adapter_request_id=str(event.get("adapter_request_id") or "") or None,
                        method=str(event.get("method") or "").upper() or None,
                        route=str(event.get("route") or "") or None,
                        status_code=self._optional_int(event.get("status_code")),
                        payload_json=self._payload_json(event),
                        emitted_at=self._parse_datetime(event.get("emitted_at")),
                        captured_at=self._parse_datetime(event.get("captured_at")),
                        received_at=current_time,
                    )
                )
                existing.add(str(event["dedupe_key"]))
                stored_count += 1
            session.commit()

        return {
            "accepted_count": len(normalized_events),
            "stored_count": stored_count,
            "duplicate_count": len(normalized_events) - stored_count,
            "received_at": current_time.isoformat().replace("+00:00", "Z"),
        }

    def get_summary(
        self,
        *,
        site_id: str,
        window_hours: int = 24,
        plugin_slug: str = "",
        now: datetime | None = None,
    ) -> dict[str, object]:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        bounded_hours = min(168, max(1, int(window_hours or 24)))
        start_at = current_time - timedelta(hours=bounded_hours)

        with get_session(self.database_url) as session:
            base_conditions = [
                PluginObservabilityEvent.site_id == site_id,
                PluginObservabilityEvent.received_at >= start_at,
                PluginObservabilityEvent.received_at <= current_time,
            ]
            if plugin_slug:
                base_conditions.append(PluginObservabilityEvent.plugin_slug == plugin_slug)

            totals_row = session.execute(
                select(
                    func.count(PluginObservabilityEvent.id),
                    func.sum(
                        case(
                            (PluginObservabilityEvent.status == "error", 1),
                            else_=0,
                        )
                    ),
                    func.avg(PluginObservabilityEvent.latency_ms),
                    func.max(PluginObservabilityEvent.received_at),
                ).where(*base_conditions)
            ).one()

            plugin_rows = session.execute(
                select(
                    PluginObservabilityEvent.plugin_slug,
                    func.count(PluginObservabilityEvent.id),
                    func.sum(
                        case(
                            (PluginObservabilityEvent.status == "error", 1),
                            else_=0,
                        )
                    ),
                    func.avg(PluginObservabilityEvent.latency_ms),
                    func.max(PluginObservabilityEvent.received_at),
                )
                .where(*base_conditions)
                .group_by(PluginObservabilityEvent.plugin_slug)
                .order_by(PluginObservabilityEvent.plugin_slug.asc())
            ).all()

            event_kind_rows = session.execute(
                select(
                    PluginObservabilityEvent.plugin_slug,
                    PluginObservabilityEvent.event_kind,
                    func.count(PluginObservabilityEvent.id),
                    func.sum(
                        case(
                            (PluginObservabilityEvent.status == "error", 1),
                            else_=0,
                        )
                    ),
                    func.avg(PluginObservabilityEvent.latency_ms),
                    func.max(PluginObservabilityEvent.received_at),
                )
                .where(*base_conditions)
                .group_by(
                    PluginObservabilityEvent.plugin_slug,
                    PluginObservabilityEvent.event_kind,
                )
                .order_by(
                    PluginObservabilityEvent.plugin_slug.asc(),
                    PluginObservabilityEvent.event_kind.asc(),
                )
            ).all()

            error_rows = session.execute(
                select(
                    PluginObservabilityEvent.plugin_slug,
                    PluginObservabilityEvent.event_kind,
                    PluginObservabilityEvent.error_code,
                    func.count(PluginObservabilityEvent.id),
                    func.max(PluginObservabilityEvent.received_at),
                )
                .where(
                    *base_conditions,
                    PluginObservabilityEvent.error_code.is_not(None),
                    PluginObservabilityEvent.error_code != "",
                )
                .group_by(
                    PluginObservabilityEvent.plugin_slug,
                    PluginObservabilityEvent.event_kind,
                    PluginObservabilityEvent.error_code,
                )
                .order_by(desc(func.count(PluginObservabilityEvent.id)))
                .limit(25)
            ).all()

            recent_errors = list(
                session.scalars(
                    select(PluginObservabilityEvent)
                    .where(
                        *base_conditions,
                        PluginObservabilityEvent.status == "error",
                    )
                    .order_by(PluginObservabilityEvent.received_at.desc())
                    .limit(10)
                )
            )

        plugins = self._build_plugin_summary(plugin_rows, event_kind_rows)
        return {
            "contract_version": "magick-plugin-observability-summary-v1",
            "generated_at": self._format_datetime(current_time),
            "window": {
                "hours": bounded_hours,
                "start_at": self._format_datetime(start_at),
                "end_at": self._format_datetime(current_time),
            },
            "totals": self._build_totals(totals_row),
            "plugins": plugins,
            "errors": [self._error_summary(row) for row in error_rows],
            "recent_errors": [self._recent_error(event) for event in recent_errors],
        }

    def get_admin_summary(
        self,
        *,
        window_hours: int = 24,
        site_id: str = "",
        plugin_slug: str = "",
        now: datetime | None = None,
    ) -> dict[str, object]:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        bounded_hours = min(168, max(1, int(window_hours or 24)))
        start_at = current_time - timedelta(hours=bounded_hours)

        with get_session(self.database_url) as session:
            base_conditions = [
                PluginObservabilityEvent.received_at >= start_at,
                PluginObservabilityEvent.received_at <= current_time,
            ]
            if site_id:
                base_conditions.append(PluginObservabilityEvent.site_id == site_id)
            if plugin_slug:
                base_conditions.append(PluginObservabilityEvent.plugin_slug == plugin_slug)

            totals_row = session.execute(
                select(
                    func.count(PluginObservabilityEvent.id),
                    func.sum(
                        case(
                            (PluginObservabilityEvent.status == "error", 1),
                            else_=0,
                        )
                    ),
                    func.avg(PluginObservabilityEvent.latency_ms),
                    func.max(PluginObservabilityEvent.received_at),
                ).where(*base_conditions)
            ).one()

            active_site_count = session.execute(
                select(
                    func.count(func.distinct(PluginObservabilityEvent.site_id))
                ).where(*base_conditions)
            ).scalar() or 0

            active_plugin_count = session.execute(
                select(
                    func.count(func.distinct(PluginObservabilityEvent.plugin_slug))
                ).where(*base_conditions)
            ).scalar() or 0

            plugin_rows = session.execute(
                select(
                    PluginObservabilityEvent.plugin_slug,
                    func.count(PluginObservabilityEvent.id),
                    func.sum(
                        case(
                            (PluginObservabilityEvent.status == "error", 1),
                            else_=0,
                        )
                    ),
                    func.avg(PluginObservabilityEvent.latency_ms),
                    func.max(PluginObservabilityEvent.received_at),
                )
                .where(*base_conditions)
                .group_by(PluginObservabilityEvent.plugin_slug)
                .order_by(PluginObservabilityEvent.plugin_slug.asc())
            ).all()

            event_kind_rows = session.execute(
                select(
                    PluginObservabilityEvent.plugin_slug,
                    PluginObservabilityEvent.event_kind,
                    func.count(PluginObservabilityEvent.id),
                    func.sum(
                        case(
                            (PluginObservabilityEvent.status == "error", 1),
                            else_=0,
                        )
                    ),
                    func.avg(PluginObservabilityEvent.latency_ms),
                    func.max(PluginObservabilityEvent.received_at),
                )
                .where(*base_conditions)
                .group_by(
                    PluginObservabilityEvent.plugin_slug,
                    PluginObservabilityEvent.event_kind,
                )
                .order_by(
                    PluginObservabilityEvent.plugin_slug.asc(),
                    PluginObservabilityEvent.event_kind.asc(),
                )
            ).all()

            site_rows = session.execute(
                select(
                    PluginObservabilityEvent.site_id,
                    func.count(PluginObservabilityEvent.id),
                    func.sum(
                        case(
                            (PluginObservabilityEvent.status == "error", 1),
                            else_=0,
                        )
                    ),
                    func.avg(PluginObservabilityEvent.latency_ms),
                    func.count(func.distinct(PluginObservabilityEvent.plugin_slug)),
                    func.max(PluginObservabilityEvent.received_at),
                )
                .where(*base_conditions)
                .group_by(PluginObservabilityEvent.site_id)
                .order_by(PluginObservabilityEvent.site_id.asc())
            ).all()

            error_rows = session.execute(
                select(
                    PluginObservabilityEvent.site_id,
                    PluginObservabilityEvent.plugin_slug,
                    PluginObservabilityEvent.event_kind,
                    PluginObservabilityEvent.error_code,
                    func.count(PluginObservabilityEvent.id),
                    func.max(PluginObservabilityEvent.received_at),
                )
                .where(
                    *base_conditions,
                    PluginObservabilityEvent.error_code.is_not(None),
                    PluginObservabilityEvent.error_code != "",
                )
                .group_by(
                    PluginObservabilityEvent.site_id,
                    PluginObservabilityEvent.plugin_slug,
                    PluginObservabilityEvent.event_kind,
                    PluginObservabilityEvent.error_code,
                )
                .order_by(desc(func.count(PluginObservabilityEvent.id)))
                .limit(25)
            ).all()

            recent_errors = list(
                session.scalars(
                    select(PluginObservabilityEvent)
                    .where(
                        *base_conditions,
                        PluginObservabilityEvent.status == "error",
                    )
                    .order_by(PluginObservabilityEvent.received_at.desc())
                    .limit(10)
                )
            )

        events_total = int(totals_row[0] or 0)
        error_total = int(totals_row[1] or 0)
        ok_total = max(0, events_total - error_total)

        plugins = self._build_plugin_summary(plugin_rows, event_kind_rows)

        sites = []
        for row in site_rows:
            site_events_total = int(row[1] or 0)
            site_error_total = int(row[2] or 0)
            sites.append({
                "site_id": str(row[0] or ""),
                "events_total": site_events_total,
                "error_total": site_error_total,
                "ok_total": max(0, site_events_total - site_error_total),
                "success_rate": self._success_rate(site_events_total, site_error_total),
                "avg_latency_ms": self._optional_avg(row[3]),
                "plugin_count": int(row[4] or 0),
                "last_seen_at": self._format_datetime(row[5]),
            })

        errors = []
        for row in error_rows:
            errors.append({
                "site_id": str(row[0] or "") or None,
                "plugin_slug": str(row[1] or ""),
                "event_kind": str(row[2] or ""),
                "error_code": str(row[3] or ""),
                "count": int(row[4] or 0),
                "last_seen_at": self._format_datetime(row[5]),
            })

        return {
            "contract_version": "magick-plugin-observability-admin-summary-v1",
            "generated_at": self._format_datetime(current_time),
            "window": {
                "hours": bounded_hours,
                "start_at": self._format_datetime(start_at),
                "end_at": self._format_datetime(current_time),
            },
            "totals": {
                "events_total": events_total,
                "ok_total": ok_total,
                "error_total": error_total,
                "success_rate": self._success_rate(events_total, error_total),
                "avg_latency_ms": self._optional_avg(totals_row[2]),
                "last_seen_at": self._format_datetime(totals_row[3]),
                "active_site_count": int(active_site_count),
                "active_plugin_count": int(active_plugin_count),
            },
            "plugins": plugins,
            "sites": sites,
            "errors": errors,
            "recent_errors": [self._admin_recent_error(event) for event in recent_errors],
        }

    def _normalize_event(
        self,
        *,
        site_id: str,
        key_id: str,
        event: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = {
            key: value
            for key, value in event.items()
            if key in ALLOWED_EVENT_FIELDS and self._is_safe_scalar(value)
        }
        dedupe_source = "|".join(
            [
                site_id,
                key_id,
                str(normalized.get("event_id") or ""),
                str(normalized.get("plugin_slug") or ""),
                str(normalized.get("event_kind") or ""),
                str(normalized.get("emitted_at") or ""),
                str(normalized.get("captured_at") or ""),
                str(normalized.get("correlation_id") or ""),
                str(normalized.get("adapter_request_id") or ""),
            ]
        )
        normalized["dedupe_key"] = hashlib.sha256(dedupe_source.encode("utf-8")).hexdigest()
        return normalized

    def _payload_json(self, event: dict[str, Any]) -> dict[str, object]:
        return {
            key: value
            for key, value in event.items()
            if key in ALLOWED_EVENT_FIELDS
            and key
            not in {
                "schema_version",
                "plugin_slug",
                "plugin_version",
                "source",
                "event_kind",
                "event_id",
                "emitted_at",
                "captured_at",
                "status",
                "status_detail",
                "error_code",
                "latency_ms",
                "ability_id",
                "proposal_id",
                "correlation_id",
                "adapter_request_id",
                "method",
                "route",
                "status_code",
            }
            and self._is_safe_scalar(value)
            and value not in ("", None)
        }

    def _parse_datetime(self, value: object) -> datetime | None:
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

    def _optional_int(self, value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _is_safe_scalar(self, value: object) -> bool:
        return value is None or isinstance(value, str | int | float | bool)

    def _build_totals(self, row: object) -> dict[str, object]:
        events_total = int(row[0] or 0)  # type: ignore[index]
        error_total = int(row[1] or 0)  # type: ignore[index]
        return {
            "events_total": events_total,
            "error_total": error_total,
            "ok_total": max(0, events_total - error_total),
            "success_rate": self._success_rate(events_total, error_total),
            "avg_latency_ms": self._optional_avg(row[2]),  # type: ignore[index]
            "last_seen_at": self._format_datetime(row[3]),  # type: ignore[index]
        }

    def _build_plugin_summary(
        self,
        plugin_rows: list[object],
        event_kind_rows: list[object],
    ) -> list[dict[str, object]]:
        events_by_plugin: dict[str, list[dict[str, object]]] = {}
        for row in event_kind_rows:
            plugin_slug = str(row[0] or "")  # type: ignore[index]
            events_total = int(row[2] or 0)  # type: ignore[index]
            error_total = int(row[3] or 0)  # type: ignore[index]
            events_by_plugin.setdefault(plugin_slug, []).append(
                {
                    "event_kind": str(row[1] or ""),  # type: ignore[index]
                    "events_total": events_total,
                    "error_total": error_total,
                    "success_rate": self._success_rate(events_total, error_total),
                    "avg_latency_ms": self._optional_avg(row[4]),  # type: ignore[index]
                    "last_seen_at": self._format_datetime(row[5]),  # type: ignore[index]
                }
            )

        summaries = []
        for row in plugin_rows:
            plugin_slug = str(row[0] or "")  # type: ignore[index]
            events_total = int(row[1] or 0)  # type: ignore[index]
            error_total = int(row[2] or 0)  # type: ignore[index]
            summaries.append(
                {
                    "plugin_slug": plugin_slug,
                    "events_total": events_total,
                    "error_total": error_total,
                    "ok_total": max(0, events_total - error_total),
                    "success_rate": self._success_rate(events_total, error_total),
                    "avg_latency_ms": self._optional_avg(row[3]),  # type: ignore[index]
                    "last_seen_at": self._format_datetime(row[4]),  # type: ignore[index]
                    "event_kinds": events_by_plugin.get(plugin_slug, []),
                }
            )
        return summaries

    def _error_summary(self, row: object) -> dict[str, object]:
        return {
            "plugin_slug": str(row[0] or ""),  # type: ignore[index]
            "event_kind": str(row[1] or ""),  # type: ignore[index]
            "error_code": str(row[2] or ""),  # type: ignore[index]
            "count": int(row[3] or 0),  # type: ignore[index]
            "last_seen_at": self._format_datetime(row[4]),  # type: ignore[index]
        }

    def _recent_error(self, event: PluginObservabilityEvent) -> dict[str, object]:
        return {
            "plugin_slug": event.plugin_slug,
            "event_kind": event.event_kind,
            "error_code": event.error_code or "",
            "status": event.status or "",
            "ability_id": event.ability_id or "",
            "proposal_id": event.proposal_id or "",
            "route": event.route or "",
            "received_at": self._format_datetime(event.received_at),
        }

    def _admin_recent_error(self, event: PluginObservabilityEvent) -> dict[str, object]:
        return {
            **self._recent_error(event),
            "site_id": event.site_id,
        }

    def _success_rate(self, events_total: int, error_total: int) -> float:
        if events_total <= 0:
            return 0.0
        return round(max(0, events_total - error_total) / events_total, 4)

    def _optional_avg(self, value: object) -> int:
        if value is None:
            return 0
        return int(round(float(value)))

    def _format_datetime(self, value: object) -> str:
        if not isinstance(value, datetime):
            return ""
        normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return normalized.isoformat().replace("+00:00", "Z")
