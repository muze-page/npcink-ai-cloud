from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.domain.commercial.service import CommercialService
from app.domain.runtime.service import RuntimeService
from app.domain.usage.service import UsageService

ADVISOR_VERSION = "internal-ai-advisor-v1"


class InternalAIAdvisorService:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def get_runtime_advisor(
        self,
        *,
        site_id: str | None = None,
        recent_minutes: int = 60,
    ) -> dict[str, Any]:
        diagnostics = RuntimeService(self.database_url).get_runtime_diagnostics_summary(
            site_id=site_id,
            recent_minutes=recent_minutes,
        )
        queue = _dict(diagnostics.get("queue"))
        callback = _dict(diagnostics.get("callback"))
        guard = _dict(diagnostics.get("guard"))

        actions: list[dict[str, Any]] = []
        signals: list[dict[str, Any]] = []
        severity = "info"
        status = "ok"
        headline = "Runtime summary is healthy"
        summary = "Current runtime diagnostics do not show an immediate operator blocker."

        if _int(callback.get("failed")) > 0 or str(callback.get("pressure_state")) in {
            "attention",
            "critical",
        }:
            status = "attention"
            severity = "error" if str(callback.get("pressure_state")) == "critical" else "warning"
            headline = "Callback delivery needs operator review"
            summary = "Callback failures or pressure are present in the selected window."
            signals.append(
                {
                    "code": "runtime.callback_pressure",
                    "state": str(callback.get("pressure_state") or "attention"),
                    "failed": _int(callback.get("failed")),
                }
            )
            actions.append(_action("inspect_callback_delivery_and_site_runtime"))

        if _int(queue.get("queued_runs")) > 0 or str(queue.get("pressure_state")) in {
            "attention",
            "critical",
        }:
            status = "attention"
            severity = _max_severity(
                severity,
                "error" if str(queue.get("pressure_state")) == "critical" else "warning",
            )
            if headline == "Runtime summary is healthy":
                headline = "Runtime queue needs operator review"
                summary = "Queued or backlogged runs are present in the selected window."
            signals.append(
                {
                    "code": "runtime.queue_pressure",
                    "state": str(queue.get("pressure_state") or "attention"),
                    "queued_runs": _int(queue.get("queued_runs")),
                }
            )
            actions.append(_action("inspect_runtime_queue_and_worker"))

        if _int(guard.get("recent_events")) > 0:
            status = "attention"
            severity = _max_severity(severity, "warning")
            if headline == "Runtime summary is healthy":
                headline = "Runtime guard events need operator review"
                summary = "Recent guard events may indicate policy, throttle, or auth pressure."
            signals.append(
                {
                    "code": "runtime.guard_events",
                    "recent_events": _int(guard.get("recent_events")),
                    "recent_rate_limit_exceeded": _int(
                        guard.get("recent_rate_limit_exceeded")
                    ),
                    "recent_replay_blocked": _int(guard.get("recent_replay_blocked")),
                }
            )
            actions.append(_action("inspect_commercial_entitlement_and_runtime_guard"))

        if not actions:
            actions.append(_action("continue_runtime_monitoring"))

        return self._advisor_payload(
            scope="runtime_operations",
            status=status,
            severity=severity,
            headline=headline,
            summary=summary,
            evidence=[
                _evidence(
                    "runtime_diagnostics",
                    "/internal/service/runtime/diagnostics/summary",
                    "runtime diagnostics summary",
                )
            ],
            recommended_actions=_dedupe_actions(actions),
            confidence="high" if status == "attention" else "medium",
            filters={
                "site_id": site_id or "",
                "recent_minutes": recent_minutes,
            },
            signals=signals,
            source={"runtime_diagnostics": diagnostics},
        )

    def get_commercial_advisor(
        self,
        *,
        usage_window_days: int = 7,
        audit_window_minutes: int = 1440,
    ) -> dict[str, Any]:
        overview = CommercialService(self.database_url).get_admin_overview(
            usage_window_days=usage_window_days,
            audit_window_minutes=audit_window_minutes,
        )
        attention_subscriptions = _list(overview.get("attention_subscriptions"))
        expiring = _dict(overview.get("expiring_subscriptions"))
        recent_usage = _dict(overview.get("recent_usage"))
        recent_decisions = _dict(overview.get("recent_commercial_decision_summary"))
        recent_decision_items = _list(recent_decisions.get("items"))

        signals: list[dict[str, Any]] = []
        actions: list[dict[str, Any]] = []
        status = "ok"
        severity = "info"
        headline = "Commercial posture is stable"
        summary = "No immediate usage, entitlement, or subscription attention item is present."

        if attention_subscriptions:
            status = "attention"
            severity = "warning"
            headline = "Subscriptions need operator review"
            summary = "Past-due or suspended subscriptions are present in the admin overview."
            signals.append(
                {
                    "code": "commercial.subscription_attention",
                    "count": len(attention_subscriptions),
                }
            )
            actions.append(_action("inspect_attention_subscriptions"))

        if _int(expiring.get("within_7_days")) > 0:
            status = "attention"
            severity = _max_severity(severity, "warning")
            if headline == "Commercial posture is stable":
                headline = "Subscriptions are expiring soon"
                summary = "One or more active subscriptions expire within 7 days."
            signals.append(
                {
                    "code": "commercial.subscription_expiring_soon",
                    "within_7_days": _int(expiring.get("within_7_days")),
                    "within_30_days": _int(expiring.get("within_30_days")),
                }
            )
            actions.append(_action("review_expiring_subscription_coverage"))

        usage_totals = _dict(recent_usage.get("totals"))
        if _float(usage_totals.get("cost")) > 0 or _int(recent_usage.get("event_count")) > 0:
            signals.append(
                {
                    "code": "commercial.usage_present",
                    "event_count": _int(recent_usage.get("event_count")),
                    "totals": usage_totals,
                }
            )

        if recent_decision_items:
            signals.append(
                {
                    "code": "commercial.recent_decisions",
                    "count": len(recent_decision_items),
                }
            )

        if not actions:
            actions.append(_action("continue_commercial_monitoring"))

        return self._advisor_payload(
            scope="commercial_operations",
            status=status,
            severity=severity,
            headline=headline,
            summary=summary,
            evidence=[
                _evidence(
                    "admin_overview",
                    "/internal/service/admin/overview",
                    "admin overview summary",
                )
            ],
            recommended_actions=_dedupe_actions(actions),
            confidence="medium",
            filters={
                "usage_window_days": usage_window_days,
                "audit_window_minutes": audit_window_minutes,
            },
            signals=signals,
            source={
                "counts": _dict(overview.get("counts")),
                "expiring_subscriptions": {
                    "within_7_days": _int(expiring.get("within_7_days")),
                    "within_30_days": _int(expiring.get("within_30_days")),
                },
                "attention_subscriptions": {"count": len(attention_subscriptions)},
                "recent_usage": {
                    "window_days": _int(recent_usage.get("window_days")),
                    "event_count": _int(recent_usage.get("event_count")),
                    "totals": usage_totals,
                },
                "recent_commercial_decision_summary": {
                    "window_minutes": _int(recent_decisions.get("window_minutes")),
                    "item_count": len(recent_decision_items),
                },
            },
        )

    def get_routing_advisor(
        self,
        *,
        site_id: str,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        recommendation = UsageService(self.database_url).get_router_recommendation_summary(
            site_id=site_id,
            filters=filters,
        )
        recommended_profile_ids = [
            str(profile_id).strip()
            for profile_id in _list(recommendation.get("recommended_profile_ids"))
            if str(profile_id).strip()
        ]
        avoid_provider_ids = [
            str(provider_id).strip()
            for provider_id in _list(recommendation.get("avoid_provider_ids"))
            if str(provider_id).strip()
        ]
        avoid_profile_ids = [
            str(profile_id).strip()
            for profile_id in _list(recommendation.get("avoid_profile_ids"))
            if str(profile_id).strip()
        ]

        status = "ok"
        severity = "info"
        headline = "No routing change candidate is available"
        summary = "Current site-scoped routing evidence does not produce a review candidate."
        actions = [_action("continue_routing_monitoring")]
        signals: list[dict[str, Any]] = []

        if recommended_profile_ids:
            status = "ready"
            headline = "Routing profile candidates are available"
            summary = "Provider usage evidence maps to one or more hosted routing profiles."
            actions = [_action("review_hosted_routing_profile_candidates")]
            signals.append(
                {
                    "code": "routing.profile_candidates",
                    "recommended_profile_ids": recommended_profile_ids,
                }
            )

        if avoid_provider_ids or avoid_profile_ids:
            status = "attention"
            severity = "warning"
            headline = "Provider degradation may affect routing"
            summary = "Provider degradation evidence is present for this site."
            actions.insert(0, _action("inspect_provider_degradation_before_profile_adoption"))
            signals.append(
                {
                    "code": "routing.provider_degradation",
                    "avoid_provider_ids": avoid_provider_ids,
                    "avoid_profile_ids": avoid_profile_ids,
                }
            )

        return self._advisor_payload(
            scope="routing_operations",
            status=status,
            severity=severity,
            headline=headline,
            summary=summary,
            evidence=[
                _evidence(
                    "router_recommendation_summary",
                    "/v1/router/recommendation",
                    "site-scoped router recommendation summary",
                )
            ],
            recommended_actions=_dedupe_actions(actions),
            confidence="medium" if status != "ok" else "low",
            filters={"site_id": site_id, **(filters or {})},
            signals=signals,
            source={"router_recommendation": recommendation},
        )

    def _advisor_payload(
        self,
        *,
        scope: str,
        status: str,
        severity: str,
        headline: str,
        summary: str,
        evidence: list[dict[str, str]],
        recommended_actions: list[dict[str, Any]],
        confidence: str,
        filters: dict[str, Any],
        signals: list[dict[str, Any]],
        source: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "advisor_version": ADVISOR_VERSION,
            "scope": scope,
            "status": status,
            "severity": severity,
            "headline": headline,
            "summary": summary,
            "evidence": evidence,
            "recommended_actions": recommended_actions,
            "confidence": confidence,
            "filters": filters,
            "signals": signals,
            "source": source,
            "generated_at": datetime.now(UTC).isoformat(),
        }


def _action(action: str) -> dict[str, Any]:
    return {"action": action, "requires_operator": True}


def _evidence(kind: str, ref: str, label: str) -> dict[str, str]:
    return {"kind": kind, "ref": ref, "label": label}


def _dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for action in actions:
        action_id = str(action.get("action") or "").strip()
        if not action_id or action_id in seen:
            continue
        seen.add(action_id)
        deduped.append(action)
    return deduped


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _max_severity(current: str, candidate: str) -> str:
    order = {"info": 0, "warning": 1, "error": 2}
    return candidate if order.get(candidate, 0) > order.get(current, 0) else current
