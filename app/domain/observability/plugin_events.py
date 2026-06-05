from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import case, delete, desc, func, select
from sqlalchemy.sql.elements import ColumnElement

from app.core.db import get_session
from app.core.models import (
    PluginObservabilityAttentionState,
    PluginObservabilityEvent,
)

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

EXPECTED_PLUGIN_SLUGS = (
    "magick-ai-abilities",
    "magick-ai-core",
    "magick-ai-adapter",
)
ERROR_RATE_HIGH_THRESHOLD = 0.05
LATENCY_WARNING_MS = 3000
CATALOG_CHURN_THRESHOLD = 4
ATTENTION_WORKFLOW_STATUSES = {
    "active",
    "acknowledged",
    "muted",
    "resolved",
}
ATTENTION_STATE_ACTIONS = {
    "acknowledge": "acknowledged",
    "mute": "muted",
    "resolve": "resolved",
}

type SQLAFilter = ColumnElement[bool]


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
            base_conditions: list[SQLAFilter] = [
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

            timeline = self._build_timeline(
                session,
                base_conditions=base_conditions,
                start_at=start_at,
                end_at=current_time,
            )

        totals = self._build_totals(totals_row)
        plugins = self._build_plugin_summary(plugin_rows, event_kind_rows)
        errors = [self._error_summary(row) for row in error_rows]
        health, attention = self._build_health_and_attention(
            totals=totals,
            plugins=plugins,
            errors=errors,
            current_time=current_time,
            window_hours=bounded_hours,
            include_missing_plugins="" == plugin_slug,
            site_id=site_id,
        )
        attention, attention_workflow = self._apply_attention_states(
            attention,
            current_time=current_time,
        )
        digest = self._build_digest(
            totals=totals,
            plugins=plugins,
            errors=errors,
            attention=attention,
            attention_workflow=attention_workflow,
            window_hours=bounded_hours,
        )
        return {
            "contract_version": "magick-plugin-observability-summary-v1",
            "generated_at": self._format_datetime(current_time),
            "window": {
                "hours": bounded_hours,
                "start_at": self._format_datetime(start_at),
                "end_at": self._format_datetime(current_time),
            },
            "totals": totals,
            "health": health,
            "attention": attention,
            "attention_workflow": attention_workflow,
            "digest": digest,
            "plugins": plugins,
            "timeline": timeline,
            "errors": errors,
            "recent_errors": [self._recent_error(event) for event in recent_errors],
        }

    def cleanup_expired_events(
        self,
        *,
        retention_days: int = 180,
        now: datetime | None = None,
    ) -> dict[str, object]:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        bounded_days = max(1, int(retention_days or 180))
        cutoff_at = current_time - timedelta(days=bounded_days)

        with get_session(self.database_url) as session:
            result = session.execute(
                delete(PluginObservabilityEvent).where(
                    PluginObservabilityEvent.received_at < cutoff_at
                )
            )
            session.commit()

        return {
            "purged_events": self._rowcount(result),
            "retention_days": bounded_days,
            "cutoff_at": self._format_datetime(cutoff_at),
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
            base_conditions: list[SQLAFilter] = [
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

            timeline = self._build_timeline(
                session,
                base_conditions=base_conditions,
                start_at=start_at,
                end_at=current_time,
            )

        events_total = int(totals_row[0] or 0)
        error_total = int(totals_row[1] or 0)
        ok_total = max(0, events_total - error_total)

        plugins = self._build_plugin_summary(plugin_rows, event_kind_rows)

        sites = []
        for row in site_rows:
            site_events_total = int(row[1] or 0)
            site_error_total = int(row[2] or 0)
            site_summary: dict[str, object] = {
                "site_id": str(row[0] or ""),
                "events_total": site_events_total,
                "error_total": site_error_total,
                "ok_total": max(0, site_events_total - site_error_total),
                "success_rate": self._success_rate(site_events_total, site_error_total),
                "avg_latency_ms": self._optional_avg(row[3]),
                "plugin_count": self._coerce_int(row[4]),
                "last_seen_at": self._format_datetime(row[5]),
            }
            site_summary["health"] = self._build_health(
                events_total=site_events_total,
                error_total=site_error_total,
                avg_latency_ms=self._coerce_int(site_summary.get("avg_latency_ms")),
                last_seen_at=str(site_summary["last_seen_at"]),
                current_time=current_time,
                window_hours=bounded_hours,
            )
            sites.append(site_summary)

        errors: list[dict[str, object]] = []
        for row in error_rows:
            errors.append({
                "site_id": str(row[0] or "") or None,
                "plugin_slug": str(row[1] or ""),
                "event_kind": str(row[2] or ""),
                "error_code": str(row[3] or ""),
                "count": int(row[4] or 0),
                "last_seen_at": self._format_datetime(row[5]),
            })

        totals = {
            "events_total": events_total,
            "ok_total": ok_total,
            "error_total": error_total,
            "success_rate": self._success_rate(events_total, error_total),
            "avg_latency_ms": self._optional_avg(totals_row[2]),
            "last_seen_at": self._format_datetime(totals_row[3]),
            "active_site_count": self._coerce_int(active_site_count),
            "active_plugin_count": self._coerce_int(active_plugin_count),
        }
        health, attention = self._build_health_and_attention(
            totals=totals,
            plugins=plugins,
            errors=errors,
            current_time=current_time,
            window_hours=bounded_hours,
            include_missing_plugins="" == plugin_slug,
            site_id=site_id or "",
        )
        attention, attention_workflow = self._apply_attention_states(
            attention,
            current_time=current_time,
        )
        digest = self._build_digest(
            totals=totals,
            plugins=plugins,
            errors=errors,
            attention=attention,
            attention_workflow=attention_workflow,
            window_hours=bounded_hours,
        )

        return {
            "contract_version": "magick-plugin-observability-admin-summary-v1",
            "generated_at": self._format_datetime(current_time),
            "window": {
                "hours": bounded_hours,
                "start_at": self._format_datetime(start_at),
                "end_at": self._format_datetime(current_time),
            },
            "totals": totals,
            "health": health,
            "attention": attention,
            "attention_workflow": attention_workflow,
            "digest": digest,
            "plugins": plugins,
            "sites": sites,
            "timeline": timeline,
            "errors": errors,
            "recent_errors": [self._admin_recent_error(event) for event in recent_errors],
        }

    def update_attention_state(
        self,
        *,
        attention_key: str,
        attention_code: str,
        action: str,
        site_id: str = "",
        plugin_slug: str = "",
        event_kind: str = "",
        error_code: str = "",
        mute_hours: int = 24,
        operator_note: str = "",
        actor_ref: str = "internal",
        now: datetime | None = None,
    ) -> dict[str, object]:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        normalized_action = str(action or "").strip().lower()
        if normalized_action == "clear":
            with get_session(self.database_url) as session:
                state = session.scalar(
                    select(PluginObservabilityAttentionState).where(
                        PluginObservabilityAttentionState.attention_key
                        == attention_key
                    )
                )
                if state is not None:
                    session.delete(state)
                    session.commit()
            return {
                "attention_key": attention_key,
                "workflow_status": "active",
                "cleared": True,
            }

        workflow_status = ATTENTION_STATE_ACTIONS.get(normalized_action)
        if workflow_status is None:
            raise ValueError("unsupported attention state action")

        bounded_mute_hours = min(720, max(1, int(mute_hours or 24)))
        muted_until = (
            current_time + timedelta(hours=bounded_mute_hours)
            if workflow_status == "muted"
            else None
        )

        with get_session(self.database_url) as session:
            state = session.scalar(
                select(PluginObservabilityAttentionState).where(
                    PluginObservabilityAttentionState.attention_key == attention_key
                )
            )
            if state is None:
                state = PluginObservabilityAttentionState(
                    attention_key=attention_key,
                    attention_code=attention_code,
                    site_id=site_id or None,
                    plugin_slug=plugin_slug or None,
                    event_kind=event_kind or None,
                    error_code=error_code or None,
                    workflow_status=workflow_status,
                    muted_until=muted_until,
                    operator_note=operator_note or None,
                    actor_ref=actor_ref or None,
                )
                session.add(state)
            else:
                state.attention_code = attention_code or state.attention_code
                state.site_id = site_id or state.site_id
                state.plugin_slug = plugin_slug or state.plugin_slug
                state.event_kind = event_kind or state.event_kind
                state.error_code = error_code or state.error_code
                state.workflow_status = workflow_status
                state.muted_until = muted_until
                state.operator_note = operator_note or None
                state.actor_ref = actor_ref or state.actor_ref
            session.commit()
            return self._attention_state_summary(state, current_time=current_time)

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
        event_id = str(normalized.get("event_id") or "")
        dedupe_fields = [
            site_id,
            key_id,
            str(normalized.get("plugin_slug") or ""),
            str(normalized.get("event_kind") or ""),
        ]
        if event_id:
            dedupe_fields.append(event_id)
        else:
            dedupe_fields.extend(
                [
                    str(normalized.get("emitted_at") or ""),
                    str(normalized.get("captured_at") or ""),
                    str(normalized.get("correlation_id") or ""),
                    str(normalized.get("adapter_request_id") or ""),
                ]
            )
        dedupe_source = "|".join(dedupe_fields)
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
            return int(cast(Any, value))
        except (TypeError, ValueError):
            return None

    def _coerce_int(self, value: object, default: int = 0) -> int:
        try:
            return int(cast(Any, value))
        except (TypeError, ValueError):
            return default

    def _coerce_float(self, value: object, default: float = 0.0) -> float:
        try:
            return float(cast(Any, value))
        except (TypeError, ValueError):
            return default

    def _dict_items(self, value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
            return []
        return [
            {str(key): item for key, item in candidate.items()}
            for candidate in value
            if isinstance(candidate, dict)
        ]

    def _string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _rowcount(self, result: object) -> int:
        return self._coerce_int(getattr(result, "rowcount", 0))

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
        plugin_rows: Sequence[object],
        event_kind_rows: Sequence[object],
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

    def _build_timeline(
        self,
        session: object,
        *,
        base_conditions: Sequence[SQLAFilter],
        start_at: datetime,
        end_at: datetime,
    ) -> list[dict[str, object]]:
        bucket_start = self._hour_floor(start_at)
        bucket_end = self._hour_floor(end_at)
        bucket_count = max(
            1,
            int((bucket_end - bucket_start).total_seconds() // 3600) + 1,
        )
        buckets: dict[datetime, dict[str, object]] = {}
        for index in range(bucket_count):
            current_bucket = bucket_start + timedelta(hours=index)
            buckets[current_bucket] = {
                "bucket_start_at": self._format_datetime(current_bucket),
                "bucket_end_at": self._format_datetime(
                    current_bucket + timedelta(hours=1)
                ),
                "bucket_hours": 1,
                "events_total": 0,
                "ok_total": 0,
                "error_total": 0,
                "success_rate": 0.0,
                "avg_latency_ms": 0,
                "_latency_total": 0,
                "_latency_count": 0,
            }

        rows = session.execute(  # type: ignore[attr-defined]
            select(
                PluginObservabilityEvent.received_at,
                PluginObservabilityEvent.status,
                PluginObservabilityEvent.latency_ms,
            ).where(*base_conditions)
        ).all()
        for received_at, status, latency_ms in rows:
            if not isinstance(received_at, datetime):
                continue
            bucket = self._hour_floor(received_at)
            if bucket not in buckets:
                continue
            item = buckets[bucket]
            events_total = self._coerce_int(item.get("events_total")) + 1
            error_total = self._coerce_int(item.get("error_total")) + (
                1 if str(status or "") == "error" else 0
            )
            item["events_total"] = events_total
            item["error_total"] = error_total
            item["ok_total"] = max(0, events_total - error_total)
            item["success_rate"] = self._success_rate(events_total, error_total)
            if latency_ms is not None:
                item["_latency_total"] = self._coerce_int(
                    item.get("_latency_total")
                ) + self._coerce_int(latency_ms)
                item["_latency_count"] = self._coerce_int(
                    item.get("_latency_count")
                ) + 1
                item["avg_latency_ms"] = self._optional_avg(
                    self._coerce_int(item.get("_latency_total"))
                    / self._coerce_int(item.get("_latency_count"), default=1)
                )

        timeline = []
        for item in buckets.values():
            item.pop("_latency_total", None)
            item.pop("_latency_count", None)
            timeline.append(item)
        return timeline

    def _hour_floor(self, value: datetime) -> datetime:
        normalized = (
            value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        )
        return normalized.replace(minute=0, second=0, microsecond=0)

    def _attention_key(
        self,
        *,
        code: str,
        site_id: str = "",
        plugin_slug: str = "",
        event_kind: str = "",
        error_code: str = "",
    ) -> str:
        source = "|".join(
            [
                str(code or ""),
                str(site_id or ""),
                str(plugin_slug or ""),
                str(event_kind or ""),
                str(error_code or ""),
            ]
        )
        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    def _apply_attention_states(
        self,
        attention: list[dict[str, object]],
        *,
        current_time: datetime,
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        if not attention:
            return attention, self._attention_workflow_summary(attention)

        keys = [str(item.get("attention_key") or "") for item in attention]
        keys = [key for key in keys if key]
        if not keys:
            return attention, self._attention_workflow_summary(attention)

        with get_session(self.database_url) as session:
            states = {
                state.attention_key: state
                for state in session.scalars(
                    select(PluginObservabilityAttentionState).where(
                        PluginObservabilityAttentionState.attention_key.in_(keys)
                    )
                )
            }

        resolved_attention = []
        for item in attention:
            attention_key = str(item.get("attention_key") or "")
            state = states.get(attention_key)
            workflow_status = "active"
            if state is not None:
                workflow_status = self._effective_workflow_status(
                    state,
                    current_time=current_time,
                )
                item["state"] = self._attention_state_summary(
                    state,
                    current_time=current_time,
                )
            item["workflow_status"] = workflow_status
            resolved_attention.append(item)
        return resolved_attention, self._attention_workflow_summary(resolved_attention)

    def _effective_workflow_status(
        self,
        state: PluginObservabilityAttentionState,
        *,
        current_time: datetime,
    ) -> str:
        workflow_status = str(state.workflow_status or "active")
        if workflow_status not in ATTENTION_WORKFLOW_STATUSES:
            return "active"
        if workflow_status == "muted":
            muted_until = state.muted_until
            if muted_until is None:
                return "active"
            normalized = (
                muted_until.replace(tzinfo=UTC)
                if muted_until.tzinfo is None
                else muted_until.astimezone(UTC)
            )
            if normalized <= current_time:
                return "active"
        return workflow_status

    def _attention_state_summary(
        self,
        state: PluginObservabilityAttentionState,
        *,
        current_time: datetime,
    ) -> dict[str, object]:
        return {
            "attention_key": state.attention_key,
            "attention_code": state.attention_code,
            "workflow_status": self._effective_workflow_status(
                state,
                current_time=current_time,
            ),
            "stored_workflow_status": state.workflow_status,
            "muted_until": self._format_datetime(state.muted_until),
            "operator_note": state.operator_note or "",
            "actor_ref": state.actor_ref or "",
            "updated_at": self._format_datetime(state.updated_at),
        }

    def _attention_workflow_summary(
        self,
        attention: list[dict[str, object]],
    ) -> dict[str, object]:
        counts = {
            "active": 0,
            "acknowledged": 0,
            "muted": 0,
            "resolved": 0,
        }
        for item in attention:
            status = str(item.get("workflow_status") or "active")
            if status not in counts:
                status = "active"
            counts[status] += 1
        return {
            **counts,
            "total": len(attention),
            "needs_attention": counts["active"],
        }

    def _build_digest(
        self,
        *,
        totals: dict[str, object],
        plugins: list[dict[str, object]],
        errors: list[dict[str, object]],
        attention: list[dict[str, object]],
        attention_workflow: dict[str, object],
        window_hours: int,
    ) -> dict[str, object]:
        events_total = self._coerce_int(totals.get("events_total"))
        error_total = self._coerce_int(totals.get("error_total"))
        success_rate = self._coerce_float(totals.get("success_rate"))
        needs_attention = self._coerce_int(attention_workflow.get("needs_attention"))
        period_label = "weekly" if window_hours >= 168 else "daily"
        top_plugin_candidate = max(
            plugins,
            key=lambda item: self._coerce_int(item.get("error_total")),
            default={},
        )
        top_plugin = (
            top_plugin_candidate
            if self._coerce_int(top_plugin_candidate.get("error_total")) > 0
            else {}
        )
        top_error = errors[0] if errors else {}

        if events_total <= 0:
            headline = "No plugin monitoring data in this window."
        elif error_total <= 0 and needs_attention <= 0:
            headline = "Plugin telemetry is reporting normally."
        elif needs_attention > 0:
            headline = f"{needs_attention} plugin monitoring item(s) need review."
        else:
            headline = "Plugin monitoring has handled items in this window."

        bullets = [
            f"{events_total} metadata event(s), {error_total} error event(s).",
            f"Success rate is {round(success_rate * 100, 1)} percent.",
        ]
        if top_plugin:
            bullets.append(
                "Highest plugin error pressure: "
                f"{top_plugin.get('plugin_slug')} "
                f"({top_plugin.get('error_total')} error event(s))."
            )
        if top_error:
            bullets.append(
                "Top error code: "
                f"{top_error.get('error_code')} "
                f"({top_error.get('count')} occurrence(s))."
            )
        if attention:
            bullets.append(
                "Current watch workflow: "
                f"{attention_workflow.get('active', 0)} open, "
                f"{attention_workflow.get('acknowledged', 0)} acknowledged, "
                f"{attention_workflow.get('muted', 0)} muted."
            )

        return {
            "period_label": period_label,
            "window_hours": window_hours,
            "headline": headline,
            "bullets": bullets[:5],
            "top_plugin_slug": str(top_plugin.get("plugin_slug") or ""),
            "top_error_code": str(top_error.get("error_code") or ""),
        }

    def _build_health_and_attention(
        self,
        *,
        totals: dict[str, object],
        plugins: list[dict[str, object]],
        errors: list[dict[str, object]],
        current_time: datetime,
        window_hours: int,
        include_missing_plugins: bool,
        site_id: str = "",
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        health = self._build_health(
            events_total=self._coerce_int(totals.get("events_total")),
            error_total=self._coerce_int(totals.get("error_total")),
            avg_latency_ms=self._coerce_int(totals.get("avg_latency_ms")),
            last_seen_at=str(totals.get("last_seen_at") or ""),
            current_time=current_time,
            window_hours=window_hours,
        )
        attention: list[dict[str, object]] = []
        if health["status"] == "inactive":
            attention.append(
                self._attention_item(
                    severity="warning",
                    code="plugin_observability.inactive",
                    title="No plugin events",
                    detail="No plugin observability events were received in the selected window.",
                    site_id=site_id,
                    suggested_action=(
                        "Verify Cloud Addon monitoring and generate local plugin activity."
                    ),
                )
            )
            return health, attention

        events_total = self._coerce_int(totals.get("events_total"))
        error_total = self._coerce_int(totals.get("error_total"))
        error_rate = error_total / events_total if events_total > 0 else 0.0
        if error_rate >= ERROR_RATE_HIGH_THRESHOLD:
            attention.append(
                self._attention_item(
                    severity="error",
                    code="plugin_observability.error_rate_high",
                    title="High error rate",
                    detail=f"{round(error_rate * 100, 1)} percent of plugin events are errors.",
                    site_id=site_id,
                    suggested_action=(
                        "Open recent errors and inspect the highest ranked error code."
                    ),
                )
            )
        elif error_total > 0:
            attention.append(
                self._attention_item(
                    severity="warning",
                    code="plugin_observability.error_rate_elevated",
                    title="Plugin errors present",
                    detail="At least one plugin event reported an error in the selected window.",
                    site_id=site_id,
                    suggested_action="Review recent errors before treating the site as clear.",
                )
            )

        avg_latency_ms = self._coerce_int(totals.get("avg_latency_ms"))
        if avg_latency_ms >= LATENCY_WARNING_MS:
            attention.append(
                self._attention_item(
                    severity="warning",
                    code="plugin_observability.latency_high",
                    title="High average latency",
                    detail=f"Average plugin event latency is {avg_latency_ms}ms.",
                    site_id=site_id,
                    suggested_action="Inspect the slow plugin and recent event kinds.",
                )
            )

        stale_detail = self._stale_detail(
            str(totals.get("last_seen_at") or ""),
            current_time=current_time,
            window_hours=window_hours,
        )
        if stale_detail:
            attention.append(
                self._attention_item(
                    severity="warning",
                    code="plugin_observability.reporting_stale",
                    title="Reporting is stale",
                    detail=stale_detail,
                    site_id=site_id,
                    suggested_action="Check whether the site and Cloud Addon are still active.",
                )
            )

        for plugin in plugins:
            plugin_events_total = self._coerce_int(plugin.get("events_total"))
            plugin_error_total = self._coerce_int(plugin.get("error_total"))
            if plugin_events_total <= 0 or plugin_error_total <= 0:
                continue
            plugin_error_rate = plugin_error_total / plugin_events_total
            attention.append(
                self._attention_item(
                    severity=(
                        "error"
                        if plugin_error_rate >= ERROR_RATE_HIGH_THRESHOLD
                        else "warning"
                    ),
                    code="plugin_observability.plugin_error",
                    title="Plugin error pressure",
                    detail=(
                        f"{plugin.get('plugin_slug')} reported "
                        f"{plugin_error_total} error event(s)."
                    ),
                    site_id=site_id,
                    plugin_slug=str(plugin.get("plugin_slug") or ""),
                    suggested_action="Inspect this plugin's event kinds and recent errors.",
                )
            )

            for event_kind in self._dict_items(plugin.get("event_kinds")):
                if (
                    str(event_kind.get("event_kind") or "")
                    == "abilities.catalog.changed"
                    and self._coerce_int(event_kind.get("events_total"))
                    >= CATALOG_CHURN_THRESHOLD
                ):
                    attention.append(
                        self._attention_item(
                            severity="warning",
                            code="plugin_observability.catalog_churn",
                            title="Ability catalog changed repeatedly",
                            detail=(
                                "The ability catalog changed multiple times in the "
                                "selected window."
                            ),
                            site_id=site_id,
                            plugin_slug=str(plugin.get("plugin_slug") or ""),
                            event_kind="abilities.catalog.changed",
                            suggested_action=(
                                "Check for plugin activation loops or catalog refresh "
                                "churn."
                            ),
                        )
                    )

        if include_missing_plugins:
            observed = {str(plugin.get("plugin_slug") or "") for plugin in plugins}
            missing = [slug for slug in EXPECTED_PLUGIN_SLUGS if slug not in observed]
            if missing:
                attention.append(
                    self._attention_item(
                        severity="warning",
                        code="plugin_observability.plugin_missing",
                        title="Expected plugin not reporting",
                        detail="Missing plugin telemetry: " + ", ".join(missing),
                        site_id=site_id,
                        suggested_action=(
                            "Confirm the plugin is installed, active, and collected "
                            "by Cloud Addon."
                        ),
                    )
                )

        if errors:
            first_error = errors[0]
            if str(first_error.get("error_code") or ""):
                attention.append(
                    self._attention_item(
                        severity="warning",
                        code="plugin_observability.top_error",
                        title="Top error code",
                        detail=(
                            f"{first_error.get('error_code')} occurred "
                            f"{first_error.get('count')} time(s)."
                        ),
                        site_id=str(first_error.get("site_id") or site_id),
                        plugin_slug=str(first_error.get("plugin_slug") or ""),
                        event_kind=str(first_error.get("event_kind") or ""),
                        error_code=str(first_error.get("error_code") or ""),
                        suggested_action="Use the event catalog to route the investigation.",
                    )
                )

        health = self._health_from_attention(health, attention)
        return health, attention[:8]

    def _build_health(
        self,
        *,
        events_total: int,
        error_total: int,
        avg_latency_ms: int,
        last_seen_at: str,
        current_time: datetime,
        window_hours: int,
    ) -> dict[str, object]:
        if events_total <= 0:
            return {
                "status": "inactive",
                "score": 0,
                "summary": "No plugin events in the selected window.",
                "reasons": ["plugin_observability.inactive"],
            }

        reasons: list[str] = []
        score = 100
        error_rate = error_total / events_total
        if error_rate >= ERROR_RATE_HIGH_THRESHOLD:
            reasons.append("plugin_observability.error_rate_high")
            score -= 50
        elif error_total > 0:
            reasons.append("plugin_observability.error_rate_elevated")
            score -= 15

        if avg_latency_ms >= LATENCY_WARNING_MS:
            reasons.append("plugin_observability.latency_high")
            score -= 15

        if self._stale_detail(
            last_seen_at,
            current_time=current_time,
            window_hours=window_hours,
        ):
            reasons.append("plugin_observability.reporting_stale")
            score -= 20

        score = max(0, min(100, score))
        status = "ok"
        if score < 60 or "plugin_observability.error_rate_high" in reasons:
            status = "error"
        elif reasons or score < 95:
            status = "warning"

        return {
            "status": status,
            "score": score,
            "summary": self._health_summary(status),
            "reasons": reasons,
        }

    def _health_from_attention(
        self,
        health: dict[str, object],
        attention: list[dict[str, object]],
    ) -> dict[str, object]:
        if health.get("status") == "inactive":
            return health
        reasons = self._string_list(health.get("reasons"))
        score = self._coerce_int(health.get("score"))
        has_error = False
        has_warning = False
        for item in attention:
            code = str(item.get("code") or "")
            if code and code not in reasons:
                reasons.append(code)
            severity = str(item.get("severity") or "")
            has_error = has_error or severity == "error"
            has_warning = has_warning or severity == "warning"
        if any(item.get("code") == "plugin_observability.plugin_missing" for item in attention):
            score = max(0, score - 10)
        if any(item.get("code") == "plugin_observability.catalog_churn" for item in attention):
            score = max(0, score - 10)
        if has_error or score < 60:
            status = "error"
        elif has_warning or reasons:
            status = "warning"
        else:
            status = "ok"
        return {
            "status": status,
            "score": score,
            "summary": self._health_summary(status),
            "reasons": reasons,
        }

    def _health_summary(self, status: str) -> str:
        if status == "error":
            return "Error pressure needs operator attention."
        if status == "warning":
            return "Review the highlighted monitoring signals."
        if status == "inactive":
            return "No plugin events in the selected window."
        return "Plugin telemetry is reporting normally."

    def _stale_detail(
        self,
        last_seen_at: str,
        *,
        current_time: datetime,
        window_hours: int,
    ) -> str:
        last_seen = self._parse_datetime(last_seen_at)
        if not last_seen:
            return ""
        stale_threshold = timedelta(hours=min(24, max(2, window_hours // 4)))
        age = current_time - last_seen
        if age <= stale_threshold:
            return ""
        age_hours = round(age.total_seconds() / 3600, 1)
        return f"Last plugin event was received {age_hours} hours ago."

    def _attention_item(
        self,
        *,
        severity: str,
        code: str,
        title: str,
        detail: str,
        site_id: str = "",
        plugin_slug: str = "",
        event_kind: str = "",
        error_code: str = "",
        suggested_action: str = "",
    ) -> dict[str, object]:
        attention_key = self._attention_key(
            code=code,
            site_id=site_id,
            plugin_slug=plugin_slug,
            event_kind=event_kind,
            error_code=error_code,
        )
        item: dict[str, object] = {
            "attention_key": attention_key,
            "severity": severity,
            "code": code,
            "title": title,
            "detail": detail,
            "suggested_action": suggested_action,
            "workflow_status": "active",
        }
        if site_id:
            item["site_id"] = site_id
        if plugin_slug:
            item["plugin_slug"] = plugin_slug
        if event_kind:
            item["event_kind"] = event_kind
        if error_code:
            item["error_code"] = error_code
        return item

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
        return int(round(self._coerce_float(value)))

    def _format_datetime(self, value: object) -> str:
        if not isinstance(value, datetime):
            return ""
        normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return normalized.isoformat().replace("+00:00", "Z")
