from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import func, select

from app.core.db import get_session
from app.core.models import SiteApiKey
from app.domain.media_derivatives.metrics import MediaDerivativeObservabilityService
from app.domain.observability.plugin_events import PluginObservabilityService
from app.domain.site_knowledge.metrics import SiteKnowledgeObservabilityService
from app.domain.usage.service import UsageService


class SiteMonitoringOverviewService:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def get_summary(
        self,
        *,
        site_id: str,
        commercial_policy: dict[str, object],
        window_hours: int = 24,
        now: datetime | None = None,
    ) -> dict[str, object]:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        bounded_hours = min(168, max(1, int(window_hours or 24)))
        start_at = current_time - timedelta(hours=bounded_hours)

        plugin_summary = PluginObservabilityService(self.database_url).get_summary(
            site_id=site_id,
            window_hours=bounded_hours,
            now=current_time,
        )
        media_summary = MediaDerivativeObservabilityService(self.database_url).get_summary(
            site_id=site_id,
            window_hours=bounded_hours,
            now=current_time,
        )
        vector_summary = SiteKnowledgeObservabilityService(self.database_url).get_summary(
            site_id=site_id,
            window_hours=bounded_hours,
            now=current_time,
        )
        usage_summary = UsageService(
            self.database_url,
            now_factory=lambda: current_time,
        ).get_usage_summary(site_id=site_id)
        key_state = self._build_key_state(site_id=site_id, current_time=current_time)
        quota = self._build_quota(commercial_policy)
        activity = self._build_activity(
            key_state=key_state,
            plugin_summary=plugin_summary,
            media_summary=media_summary,
            vector_summary=vector_summary,
            usage_summary=usage_summary,
        )
        components, actions = self._build_components_and_actions(
            current_time=current_time,
            key_state=key_state,
            plugin_summary=plugin_summary,
            media_summary=media_summary,
            vector_summary=vector_summary,
            usage_summary=usage_summary,
            quota=quota,
            activity=activity,
        )
        health = self._build_health(components=components, activity=activity)

        return {
            "contract_version": "magick-site-monitoring-overview-v1",
            "site_id": site_id,
            "generated_at": self._format_datetime(current_time),
            "window": {
                "hours": bounded_hours,
                "start_at": self._format_datetime(start_at),
                "end_at": self._format_datetime(current_time),
            },
            "health": health,
            "action_required": sorted(
                actions,
                key=lambda item: (
                    -self._severity_rank(str(item.get("severity") or "")),
                    self._coerce_int(item.get("sort_weight")),
                    str(item.get("code") or ""),
                ),
            )[:8],
            "quota": quota,
            "activity": activity,
            "components": components,
        }

    def _build_key_state(self, *, site_id: str, current_time: datetime) -> dict[str, object]:
        with get_session(self.database_url) as session:
            active_key_count = int(
                session.scalar(
                    select(func.count(SiteApiKey.key_id)).where(
                        SiteApiKey.site_id == site_id,
                        SiteApiKey.status == "active",
                        SiteApiKey.revoked_at.is_(None),
                        (SiteApiKey.expires_at.is_(None) | (SiteApiKey.expires_at > current_time)),
                    )
                )
                or 0
            )
            latest_last_used_at = session.scalar(
                select(func.max(SiteApiKey.last_used_at)).where(SiteApiKey.site_id == site_id)
            )
            next_expires_at = session.scalar(
                select(func.min(SiteApiKey.expires_at)).where(
                    SiteApiKey.site_id == site_id,
                    SiteApiKey.status == "active",
                    SiteApiKey.revoked_at.is_(None),
                    SiteApiKey.expires_at.is_not(None),
                    SiteApiKey.expires_at > current_time,
                )
            )
            newest_active_created_at = session.scalar(
                select(func.max(SiteApiKey.created_at)).where(
                    SiteApiKey.site_id == site_id,
                    SiteApiKey.status == "active",
                    SiteApiKey.revoked_at.is_(None),
                )
            )

        expires_in_days = None
        if next_expires_at is not None:
            resolved_expires_at = self._to_utc(next_expires_at)
            expires_in_days = int((resolved_expires_at - current_time).total_seconds() // 86400)
        return {
            "active_key_count": active_key_count,
            "last_used_at": self._format_datetime(latest_last_used_at),
            "next_expires_at": self._format_datetime(next_expires_at),
            "newest_active_created_at": self._format_datetime(newest_active_created_at),
            "expires_in_days": expires_in_days,
        }

    def _build_quota(self, commercial_policy: dict[str, object]) -> dict[str, object]:
        budget_state = commercial_policy.get("budget_state")
        budget_state = budget_state if isinstance(budget_state, dict) else {}
        metrics = {
            meter_key: self._build_quota_metric(budget_state.get(meter_key))
            for meter_key in ("runs", "tokens", "cost")
        }
        pressure_candidates = [
            (meter_key, self._coerce_float(metric.get("usage_ratio")))
            for meter_key, metric in metrics.items()
            if self._coerce_float(metric.get("limit")) > 0
        ]
        top_pressure = "none"
        if pressure_candidates:
            top_pressure = max(pressure_candidates, key=lambda item: item[1])[0]
        return {
            "period_start_at": str(commercial_policy.get("period_start_at") or ""),
            "period_end_at": str(commercial_policy.get("period_end_at") or ""),
            "runs": metrics["runs"],
            "tokens": metrics["tokens"],
            "cost": metrics["cost"],
            "top_pressure": top_pressure,
            "summary": self._quota_summary(metrics=metrics, top_pressure=top_pressure),
        }

    def _build_quota_metric(self, raw_state: object) -> dict[str, object]:
        state = raw_state if isinstance(raw_state, dict) else {}
        used = round(float(state.get("current_total") or 0.0), 6)
        limit = round(float(state.get("limit") or 0.0), 6)
        remaining = round(max(0.0, limit - used), 6) if limit > 0 else 0.0
        usage_ratio = round(used / limit, 4) if limit > 0 else 0.0
        return {
            "used": used,
            "limit": limit,
            "remaining": remaining,
            "usage_ratio": usage_ratio,
            "over_limit": bool(state.get("over_limit")) if limit > 0 else False,
        }

    def _build_activity(
        self,
        *,
        key_state: dict[str, object],
        plugin_summary: dict[str, object],
        media_summary: dict[str, object],
        vector_summary: dict[str, object],
        usage_summary: dict[str, object],
    ) -> dict[str, object]:
        plugin_totals = self._dict(plugin_summary.get("totals"))
        media_totals = self._dict(media_summary.get("totals"))
        vector_totals = self._dict(vector_summary.get("totals"))
        usage_windows = self._dict(usage_summary.get("windows"))
        rolling_usage = self._dict(usage_windows.get("rolling_24h"))
        last_activity_at = self._latest_datetime(
            [
                key_state.get("last_used_at"),
                plugin_totals.get("last_seen_at"),
                media_totals.get("last_finished_at"),
                vector_totals.get("last_search_finished_at"),
                vector_totals.get("last_index_job_finished_at"),
                rolling_usage.get("last_seen_at"),
            ]
        )
        return {
            "last_seen_at": self._format_datetime(last_activity_at),
            "plugin_events_total": int(plugin_totals.get("events_total") or 0),
            "plugin_errors_total": int(plugin_totals.get("error_total") or 0),
            "media_jobs_total": int(media_totals.get("jobs_total") or 0),
            "media_failed_total": int(media_totals.get("failed_total") or 0),
            "vector_searches_total": int(vector_totals.get("search_queries_total") or 0),
            "vector_no_hit_total": int(vector_totals.get("no_hit_total") or 0),
            "runtime_runs_total": int(rolling_usage.get("runs_total") or 0),
            "runtime_success_rate": float(rolling_usage.get("success_rate") or 0.0),
            "runtime_p95_latency_ms": int(rolling_usage.get("latency_ms_p95") or 0),
        }

    def _build_components_and_actions(
        self,
        *,
        current_time: datetime,
        key_state: dict[str, object],
        plugin_summary: dict[str, object],
        media_summary: dict[str, object],
        vector_summary: dict[str, object],
        usage_summary: dict[str, object],
        quota: dict[str, object],
        activity: dict[str, object],
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        components: list[dict[str, object]] = []
        actions: list[dict[str, object]] = []
        active_key_count = self._coerce_int(key_state.get("active_key_count"))
        expires_in_days = key_state.get("expires_in_days")
        if active_key_count <= 0:
            components.append(
                self._component("connection", "error", 0, "No active Cloud connection credential.")
            )
            actions.append(
                self._action(
                    code="site_monitoring.connection_credential_missing",
                    severity="error",
                    source="connection",
                    title="No active Cloud connection credential",
                    detail="This site cannot reliably send Cloud telemetry or runtime requests.",
                    suggested_action=(
                        "Reconnect the site from the WordPress plugin so Cloud can issue "
                        "a fresh connection credential automatically."
                    ),
                    sort_weight=10,
                )
            )
        elif isinstance(expires_in_days, int) and expires_in_days <= 7:
            components.append(
                self._component(
                    "api_key",
                    "warning",
                    80,
                    f"Active key expires in {max(0, expires_in_days)} day(s).",
                )
            )
            actions.append(
                self._action(
                    code="site_monitoring.api_key_expiring",
                    severity="warning",
                    source="connection",
                    title="Cloud API key expires soon",
                    detail="A site API key is close to expiry.",
                    suggested_action=(
                        "Rotate the key before the expiry date to avoid telemetry gaps."
                    ),
                    sort_weight=20,
                )
            )
        else:
            components.append(self._component("api_key", "ok", 100, "Active Cloud API key."))

        self._append_plugin_component(plugin_summary, components, actions)
        self._append_media_component(media_summary, components, actions)
        self._append_vector_component(vector_summary, components, actions)
        self._append_runtime_component(usage_summary, components, actions)
        self._append_quota_component(quota, components, actions)
        if not activity.get("last_seen_at") and active_key_count > 0:
            components.append(
                self._component(
                    "activity",
                    "warning",
                    75,
                    "No Cloud activity has been observed for this site.",
                )
            )
            actions.append(
                self._action(
                    code="site_monitoring.no_activity",
                    severity="warning",
                    source="activity",
                    title="No Cloud activity observed",
                    detail=(
                        "The site has an active key, but Cloud has not received recent telemetry."
                    ),
                    suggested_action=(
                        "Confirm Cloud Addon is installed, connected, and able to flush events."
                    ),
                    sort_weight=70,
                )
            )
        self._append_key_staleness_action(
            current_time=current_time,
            key_state=key_state,
            actions=actions,
        )
        return components, actions

    def _append_plugin_component(
        self,
        summary: dict[str, object],
        components: list[dict[str, object]],
        actions: list[dict[str, object]],
    ) -> None:
        health = self._dict(summary.get("health"))
        status = str(health.get("status") or "inactive")
        score = int(health.get("score") or 0)
        components.append(
            self._component(
                "plugins",
                status,
                score,
                str(health.get("summary") or "No plugin telemetry."),
            )
        )
        for item in self._dict_items(summary.get("attention"))[:2]:
            item = self._dict(item)
            state = self._dict(item.get("state"))
            workflow_status = str(state.get("workflow_status") or "active")
            if workflow_status in {"resolved", "muted"}:
                continue
            actions.append(
                self._action(
                    code=str(item.get("code") or "site_monitoring.plugin_attention"),
                    severity=str(item.get("severity") or "warning"),
                    source="plugins",
                    title=str(item.get("title") or "Plugin monitoring needs attention"),
                    detail=str(item.get("detail") or item.get("summary") or ""),
                    suggested_action=str(item.get("suggested_action") or "Open plugin monitoring."),
                    sort_weight=30,
                    attention_key=str(item.get("attention_key") or ""),
                    workflow_status=workflow_status,
                    state=state,
                )
            )

    def _append_media_component(
        self,
        summary: dict[str, object],
        components: list[dict[str, object]],
        actions: list[dict[str, object]],
    ) -> None:
        health = self._dict(summary.get("health"))
        totals = self._dict(summary.get("totals"))
        status = str(health.get("status") or "inactive")
        components.append(
            self._component(
                "media",
                status,
                int(health.get("score") or 0),
                str(health.get("summary") or "No media processing activity."),
            )
        )
        failed_total = int(totals.get("failed_total") or 0)
        if failed_total > 0:
            severity = "error" if failed_total >= 3 else "warning"
            actions.append(
                self._action(
                    code="site_monitoring.media_failures",
                    severity=severity,
                    source="media",
                    title="Media processing failures detected",
                    detail=f"{failed_total} media job(s) failed in the selected window.",
                    suggested_action="Open Media monitoring and inspect recent failure codes.",
                    sort_weight=40,
                )
            )

    def _append_vector_component(
        self,
        summary: dict[str, object],
        components: list[dict[str, object]],
        actions: list[dict[str, object]],
    ) -> None:
        health = self._dict(summary.get("health"))
        totals = self._dict(summary.get("totals"))
        status = str(health.get("status") or "inactive")
        components.append(
            self._component(
                "vector",
                status,
                int(health.get("score") or 0),
                str(health.get("summary") or "No site knowledge activity."),
            )
        )
        no_hit_rate = float(totals.get("no_hit_rate") or 0.0)
        search_queries_total = int(totals.get("search_queries_total") or 0)
        if search_queries_total > 0 and no_hit_rate >= 0.25:
            actions.append(
                self._action(
                    code="site_monitoring.vector_no_hit_pressure",
                    severity="warning" if no_hit_rate < 0.5 else "error",
                    source="vector",
                    title="Site knowledge no-hit rate is high",
                    detail=f"{no_hit_rate * 100:.1f}% of vector searches returned no result.",
                    suggested_action=(
                        "Review indexed content coverage and run a refresh sync if needed."
                    ),
                    sort_weight=45,
                )
            )
        if search_queries_total > 0 and int(totals.get("current_chunk_count") or 0) <= 0:
            actions.append(
                self._action(
                    code="site_monitoring.vector_index_empty",
                    severity="error",
                    source="vector",
                    title="Vector searches are running against an empty index",
                    detail="Searches were observed, but no indexed chunks are currently recorded.",
                    suggested_action=(
                        "Run a site knowledge sync and confirm the index snapshot updates."
                    ),
                    sort_weight=35,
                )
            )

    def _append_runtime_component(
        self,
        summary: dict[str, object],
        components: list[dict[str, object]],
        actions: list[dict[str, object]],
    ) -> None:
        windows = self._dict(summary.get("windows"))
        rolling = self._dict(windows.get("rolling_24h"))
        runs_total = int(rolling.get("runs_total") or 0)
        success_rate = float(rolling.get("success_rate") or 0.0)
        p95_latency = int(rolling.get("latency_ms_p95") or 0)
        if runs_total <= 0:
            components.append(self._component("runtime", "inactive", 0, "No runtime runs."))
            return
        score = 100
        if success_rate < 0.90:
            score -= 30
        elif success_rate < 0.97:
            score -= 12
        if p95_latency >= 10000:
            score -= 15
        elif p95_latency >= 5000:
            score -= 8
        status = self._status_from_score(score)
        components.append(
            self._component(
                "runtime",
                status,
                score,
                f"{runs_total} runtime run(s), {success_rate * 100:.1f}% success.",
            )
        )
        if success_rate < 0.97:
            actions.append(
                self._action(
                    code="site_monitoring.runtime_success_rate",
                    severity="error" if success_rate < 0.90 else "warning",
                    source="runtime",
                    title="Runtime success rate dropped",
                    detail=f"Runtime success rate is {success_rate * 100:.1f}% in 24 hours.",
                    suggested_action="Check runtime logs and provider health before traffic grows.",
                    sort_weight=25,
                )
            )

    def _append_quota_component(
        self,
        quota: dict[str, object],
        components: list[dict[str, object]],
        actions: list[dict[str, object]],
    ) -> None:
        top_pressure = str(quota.get("top_pressure") or "none")
        metric = self._dict(quota.get(top_pressure)) if top_pressure != "none" else {}
        ratio = float(metric.get("usage_ratio") or 0.0)
        over_limit = bool(metric.get("over_limit"))
        status = "ok"
        score = 100
        if over_limit:
            status = "error"
            score = 45
        elif ratio >= 0.9:
            status = "warning"
            score = 70
        elif ratio >= 0.75:
            status = "warning"
            score = 82
        components.append(
            self._component(
                "quota",
                status,
                score,
                str(quota.get("summary") or "No quota limit is configured."),
            )
        )
        if over_limit or ratio >= 0.9:
            actions.append(
                self._action(
                    code=f"site_monitoring.quota_{top_pressure}",
                    severity="error" if over_limit else "warning",
                    source="quota",
                    title=f"{top_pressure.title()} quota pressure is high",
                    detail=str(quota.get("summary") or ""),
                    suggested_action=(
                        "Review current period usage and upgrade or top up before requests fail."
                    ),
                    sort_weight=15,
                )
            )

    def _append_key_staleness_action(
        self,
        *,
        current_time: datetime,
        key_state: dict[str, object],
        actions: list[dict[str, object]],
    ) -> None:
        if self._coerce_int(key_state.get("active_key_count")) <= 0:
            return
        last_used_at = self._parse_datetime(key_state.get("last_used_at"))
        if last_used_at is None:
            return
        if current_time - last_used_at <= timedelta(days=7):
            return
        actions.append(
            self._action(
                code="site_monitoring.api_key_stale",
                severity="warning",
            source="connection",
                title="Cloud API key has not been used recently",
                detail=f"Last key usage was {self._format_datetime(last_used_at)}.",
                suggested_action=(
                    "Confirm the WordPress site is still connected to this Cloud account."
                ),
                sort_weight=65,
            )
        )

    def _build_health(
        self,
        *,
        components: list[dict[str, object]],
        activity: dict[str, object],
    ) -> dict[str, object]:
        active_components = [
            item for item in components if str(item.get("status") or "") != "inactive"
        ]
        if not active_components:
            return {
                "status": "inactive",
                "score": 0,
                "summary": "No Cloud monitoring activity has been observed for this site.",
                "components_count": len(components),
            }
        score = min(self._coerce_int(item.get("score")) for item in active_components)
        status = self._status_from_score(score)
        error_count = sum(1 for item in components if item.get("status") == "error")
        warning_count = sum(1 for item in components if item.get("status") == "warning")
        if error_count:
            summary = f"{error_count} critical monitoring area(s) need attention."
        elif warning_count:
            summary = f"{warning_count} monitoring area(s) should be reviewed."
        else:
            summary = "Site Cloud monitoring looks healthy."
        if activity.get("last_seen_at"):
            summary = f"{summary} Last activity {activity.get('last_seen_at')}."
        return {
            "status": status,
            "score": max(0, min(100, score)),
            "summary": summary,
            "components_count": len(components),
        }

    def _quota_summary(
        self,
        *,
        metrics: dict[str, dict[str, object]],
        top_pressure: str,
    ) -> str:
        if top_pressure == "none":
            return "No period quota limit is configured."
        metric = metrics[top_pressure]
        ratio = self._coerce_float(metric.get("usage_ratio"))
        used = self._coerce_float(metric.get("used"))
        limit = self._coerce_float(metric.get("limit"))
        return (
            f"{top_pressure.title()} usage is {ratio * 100:.1f}% "
            f"of period quota ({used:g}/{limit:g})."
        )

    def _component(
        self,
        component: str,
        status: str,
        score: int,
        summary: str,
    ) -> dict[str, object]:
        return {
            "component": component,
            "status": status if status in {"ok", "warning", "error", "inactive"} else "inactive",
            "score": max(0, min(100, int(score or 0))),
            "summary": summary,
        }

    def _action(
        self,
        *,
        code: str,
        severity: str,
        source: str,
        title: str,
        detail: str,
        suggested_action: str,
        sort_weight: int,
        attention_key: str = "",
        workflow_status: str = "active",
        state: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        action: dict[str, object] = {
            "code": code,
            "severity": severity if severity in {"warning", "error"} else "warning",
            "source": source,
            "title": title,
            "detail": detail,
            "suggested_action": suggested_action,
            "sort_weight": sort_weight,
            "workflow_status": workflow_status if workflow_status else "active",
        }
        if attention_key:
            action["attention_key"] = attention_key
        if state:
            action["state"] = state
        return action

    def _status_from_score(self, score: int) -> str:
        if score < 70:
            return "error"
        if score < 90:
            return "warning"
        return "ok"

    def _severity_rank(self, severity: str) -> int:
        return {"error": 2, "warning": 1}.get(severity, 0)

    def _dict(self, value: object) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _dict_items(self, value: object) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [self._dict(item) for item in value if isinstance(item, dict)]

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

    def _latest_datetime(self, values: list[object]) -> datetime | None:
        latest: datetime | None = None
        for value in values:
            resolved = self._parse_datetime(value)
            if resolved is None:
                continue
            if latest is None or resolved > latest:
                latest = resolved
        return latest

    def _parse_datetime(self, value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return self._to_utc(value)
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            try:
                return self._to_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
            except ValueError:
                return None
        return None

    def _to_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _format_datetime(self, value: object) -> str:
        resolved = self._parse_datetime(value)
        if resolved is None:
            return ""
        return resolved.isoformat().replace("+00:00", "Z")
