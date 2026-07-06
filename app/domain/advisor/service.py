from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, desc, func, select
from sqlalchemy.orm.attributes import flag_modified

from app.adapters.providers.base import (
    ProviderAdapter,
    ProviderExecutionError,
    ProviderExecutionRequest,
)
from app.core.db import get_session
from app.core.models import (
    ProviderCallRecord,
    RunRecord,
    ServiceAuditEvent,
    SiteServiceProjection,
)
from app.domain.agent_workflow_metadata import (
    INTERNAL_OPS_ADVISOR_AGENT_ID,
    get_agent_handoff_metadata,
)
from app.domain.commercial.service import CommercialService
from app.domain.hosted_model_defaults import FREE_GPT55_MODEL_ID
from app.domain.observability.site_monitoring_overview import SiteMonitoringOverviewService
from app.domain.runtime.service import RuntimeService
from app.domain.site_knowledge.metrics import SiteKnowledgeObservabilityService
from app.domain.usage.service import UsageService

ADVISOR_VERSION = "internal-ai-advisor-v1"
SUMMARIZER_VERSION = "internal-ops-summarizer-v1"
AI_DISCLOSURE_VERSION = "ai-generated-content-disclosure-v1"


class InternalAIAdvisorService:
    def __init__(
        self,
        database_url: str,
        *,
        providers: dict[str, ProviderAdapter] | None = None,
        allowed_summarizer_provider_ids: set[str] | None = None,
    ) -> None:
        self.database_url = database_url
        self.providers = providers or {}
        self.allowed_summarizer_provider_ids = {
            str(provider_id).strip()
            for provider_id in (allowed_summarizer_provider_ids or set())
            if str(provider_id).strip()
        }

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
                    "recent_rate_limit_exceeded": _int(guard.get("recent_rate_limit_exceeded")),
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

    def get_site_diagnostic_advisor(
        self,
        *,
        site_id: str,
        window_hours: int = 24,
    ) -> dict[str, Any]:
        normalized_site_id = str(site_id or "").strip()
        if not normalized_site_id:
            raise ValueError("site_id is required for site diagnostics")
        bounded_window_hours = min(168, max(1, int(window_hours or 24)))
        commercial_service = CommercialService(self.database_url)
        commercial_policy = commercial_service.inspect_commercial_policy(normalized_site_id)
        overview = SiteMonitoringOverviewService(self.database_url).get_summary(
            site_id=normalized_site_id,
            commercial_policy=commercial_policy,
            window_hours=bounded_window_hours,
        )
        action_required = _list(overview.get("action_required"))
        health = _dict(overview.get("health"))
        generated_at = str(overview.get("generated_at") or datetime.now(UTC).isoformat())
        window = _dict(overview.get("window"))
        diagnostic_items = [
            _site_diagnostic_item(
                _dict(item),
                generated_at=generated_at,
                window=window,
            )
            for item in action_required[:3]
            if isinstance(item, dict)
        ]
        diagnostic_workflow = _site_diagnostic_workflow_summary(diagnostic_items)
        status = "attention" if diagnostic_items else "ok"
        severity = "info"
        if any(item.get("severity") == "error" for item in diagnostic_items):
            severity = "error"
        elif diagnostic_items:
            severity = "warning"

        if diagnostic_items:
            headline = "Site diagnostics need review"
            summary = (
                f"{len(diagnostic_items)} prioritized diagnostic item(s) need operator review. "
                f"Top item: {diagnostic_items[0].get('title') or 'Review monitoring detail'}."
            )
            recommended_actions = [
                _action(str(item.get("recommended_action_id") or "inspect_site_monitoring_detail"))
                for item in diagnostic_items
            ]
        else:
            headline = "Site diagnostics look stable"
            summary = "Current site monitoring evidence does not show an immediate diagnostic item."
            recommended_actions = [_action("continue_site_monitoring")]

        signals: list[dict[str, Any]] = [
            {
                "code": "site_diagnostics.health",
                "status": str(health.get("status") or "inactive"),
                "score": _int(health.get("score")),
                "action_required_count": len(action_required),
            },
            {
                "code": "site_diagnostics.priority_items",
                "items": [
                    {
                        "code": str(item.get("code") or ""),
                        "severity": str(item.get("severity") or ""),
                        "source": str(item.get("source") or ""),
                    }
                    for item in diagnostic_items
                ],
            },
        ]

        payload = self._advisor_payload(
            scope="site_diagnostics",
            status=status,
            severity=severity,
            headline=headline,
            summary=summary,
            evidence=[
                _evidence(
                    "site_monitoring_overview",
                    "/portal/v1/sites/{site_id}/monitoring-overview",
                    "site-scoped monitoring overview",
                )
            ],
            recommended_actions=_dedupe_actions(recommended_actions),
            confidence="high" if diagnostic_items else "medium",
            filters={
                "site_id": normalized_site_id,
                "window_hours": bounded_window_hours,
            },
            signals=signals,
            source={
                "monitoring_overview": {
                    "contract_version": str(overview.get("contract_version") or ""),
                    "site_id": normalized_site_id,
                    "window": _dict(overview.get("window")),
                    "health": health,
                    "activity": _dict(overview.get("activity")),
                    "components": _list(overview.get("components")),
                    "action_required": [
                        _pick_fields(
                            _dict(item),
                            {
                                "code",
                                "severity",
                                "source",
                                "title",
                                "detail",
                                "suggested_action",
                                "sort_weight",
                            },
                        )
                        for item in action_required[:8]
                        if isinstance(item, dict)
                    ],
                }
            },
        )
        payload["diagnostic_items"] = diagnostic_items
        payload["diagnostic_workflow"] = diagnostic_workflow
        payload["evidence_window"] = {
            "hours": _int(window.get("hours")),
            "start_at": str(window.get("start_at") or ""),
            "end_at": str(window.get("end_at") or ""),
        }
        payload["safety"] = {
            "write_posture": "suggestion_only",
            "direct_wordpress_write": False,
            "operator_review_required": True,
            "automatic_repair_allowed": False,
            "raw_payload_exposed": False,
        }
        return payload

    def get_operations_advisor(
        self,
        *,
        site_id: str | None = None,
        window_hours: int = 24,
        usage_window_days: int = 7,
        audit_window_minutes: int = 1440,
    ) -> dict[str, Any]:
        bounded_window_hours = min(168, max(1, int(window_hours or 24)))
        bounded_usage_window_days = min(90, max(1, int(usage_window_days or 7)))
        bounded_audit_window_minutes = min(10080, max(1, int(audit_window_minutes or 1440)))
        commercial = CommercialService(self.database_url).get_admin_overview(
            usage_window_days=bounded_usage_window_days,
            audit_window_minutes=bounded_audit_window_minutes,
        )
        runtime = RuntimeService(self.database_url).get_runtime_diagnostics_summary(
            site_id=site_id,
            recent_minutes=bounded_window_hours * 60,
        )
        knowledge = SiteKnowledgeObservabilityService(self.database_url).get_summary(
            window_hours=bounded_window_hours,
            site_id=str(site_id or "").strip(),
        )
        provider = self._get_provider_operations_metrics(
            site_id=site_id,
            window_hours=bounded_window_hours,
        )
        runs = self._get_run_operations_metrics(
            site_id=site_id,
            window_hours=bounded_window_hours,
        )

        counts = _dict(commercial.get("counts"))
        recent_usage = _dict(commercial.get("recent_usage"))
        usage_totals = _dict(recent_usage.get("totals"))
        attention_subscriptions = _list(commercial.get("attention_subscriptions"))
        expiring = _dict(commercial.get("expiring_subscriptions"))
        queue = _dict(runtime.get("queue"))
        callback = _dict(runtime.get("callback"))
        guard = _dict(runtime.get("guard"))
        knowledge_totals = _dict(knowledge.get("totals"))

        signals: list[dict[str, Any]] = [
            {
                "code": "ops.platform_coverage",
                "active_sites": _int(counts.get("sites_active")),
                "total_sites": _int(counts.get("sites_total")),
                "attention_subscriptions": len(attention_subscriptions),
                "subscriptions_expiring_7d": _int(expiring.get("within_7_days")),
            },
            {
                "code": "ops.usage_cost",
                "usage_events": _int(recent_usage.get("event_count")),
                "meter_quantity": _float(usage_totals.get("quantity")),
                "reported_cost": _float(usage_totals.get("cost")),
                "provider_cost": _float(provider.get("cost")),
                "tokens_total": _int(provider.get("tokens_total")),
            },
            {
                "code": "ops.runtime_quality",
                "total_runs": _int(runs.get("total_runs")),
                "failed_runs": _int(runs.get("failed_runs")),
                "run_failure_rate": _float(runs.get("failure_rate")),
                "queued_runs": _int(queue.get("queued_runs")),
                "callback_failed": _int(callback.get("failed")),
                "guard_events": _int(guard.get("recent_events")),
            },
            {
                "code": "ops.provider_quality",
                "provider_calls": _int(provider.get("call_count")),
                "provider_errors": _int(provider.get("error_count")),
                "provider_error_rate": _float(provider.get("error_rate")),
                "fallbacks": _int(provider.get("fallback_count")),
                "avg_latency_ms": _int(provider.get("avg_latency_ms")),
                "top_provider": str(provider.get("top_provider_id") or ""),
            },
            {
                "code": "ops.knowledge_quality",
                "knowledge_searches": _int(knowledge_totals.get("search_queries_total")),
                "knowledge_no_hits": _int(knowledge_totals.get("no_hit_total")),
                "knowledge_no_hit_rate": _float(knowledge_totals.get("no_hit_rate")),
                "knowledge_failed_searches": _int(knowledge_totals.get("search_failed_total")),
                "indexed_documents": _int(knowledge_totals.get("current_document_count")),
                "indexed_chunks": _int(knowledge_totals.get("current_chunk_count")),
            },
        ]

        actions: list[dict[str, Any]] = []
        status = "ok"
        severity = "info"
        headline = "Operations posture is stable"
        summary = (
            "Recent usage, runtime, provider, and knowledge signals do not show "
            "a high-priority operator action."
        )

        if _int(runs.get("failed_runs")) > 0 or _float(runs.get("failure_rate")) >= 0.1:
            status = "attention"
            severity = _max_severity(severity, "warning")
            headline = "Runtime failures need operations review"
            summary = "Recent run failures are visible in the selected operations window."
            actions.append(_action("inspect_failed_runs_by_site_and_ability"))

        if _int(provider.get("error_count")) > 0 or _float(provider.get("error_rate")) >= 0.05:
            status = "attention"
            severity = _max_severity(severity, "warning")
            headline = "Provider reliability needs review"
            summary = "Provider errors or fallback pressure are present in recent traffic."
            actions.append(_action("inspect_provider_errors_latency_and_fallbacks"))

        if (
            _float(knowledge_totals.get("no_hit_rate")) >= 0.25
            and _int(knowledge_totals.get("search_queries_total")) >= 4
        ):
            status = "attention"
            severity = _max_severity(severity, "warning")
            headline = "Knowledge search value may be low"
            summary = "Knowledge searches show elevated no-hit pressure in the selected window."
            actions.append(_action("review_site_knowledge_no_hit_queries_and_index_coverage"))

        if attention_subscriptions or _int(expiring.get("within_7_days")) > 0:
            status = "attention"
            severity = _max_severity(severity, "warning")
            if headline == "Operations posture is stable":
                headline = "Commercial follow-up is visible"
                summary = "Subscription attention or near-term expiry signals are present."
            actions.append(_action("review_subscription_attention_and_expiry_coverage"))

        if _int(queue.get("queued_runs")) > 0 or _int(callback.get("failed")) > 0:
            status = "attention"
            severity = _max_severity(severity, "warning")
            if headline == "Operations posture is stable":
                headline = "Runtime delivery needs operator review"
                summary = "Queue or callback pressure is present in recent runtime diagnostics."
            actions.append(_action("inspect_queue_worker_and_callback_delivery"))

        if not actions:
            actions.append(_action("continue_operations_monitoring"))

        return self._advisor_payload(
            scope="operations_analysis",
            status=status,
            severity=severity,
            headline=headline,
            summary=summary,
            evidence=[
                _evidence(
                    "admin_overview",
                    "/internal/service/admin/overview",
                    "commercial coverage and usage summary",
                ),
                _evidence(
                    "runtime_diagnostics",
                    "/internal/service/runtime/diagnostics/summary",
                    "runtime queue, callback, and guard summary",
                ),
                _evidence(
                    "site_knowledge_observability",
                    "/internal/service/site-knowledge/observability/summary",
                    "knowledge search and index health summary",
                ),
                _evidence(
                    "provider_call_records",
                    "provider_call_records",
                    "provider call metrics aggregated from run telemetry",
                ),
            ],
            recommended_actions=_dedupe_actions(actions),
            confidence="high" if status == "attention" else "medium",
            filters={
                "site_id": site_id or "",
                "window_hours": bounded_window_hours,
                "usage_window_days": bounded_usage_window_days,
                "audit_window_minutes": bounded_audit_window_minutes,
            },
            signals=signals,
            source={
                "commercial": {
                    "counts": counts,
                    "recent_usage": {
                        "event_count": _int(recent_usage.get("event_count")),
                        "totals": usage_totals,
                    },
                    "attention_subscriptions": {"count": len(attention_subscriptions)},
                    "expiring_subscriptions": {
                        "within_7_days": _int(expiring.get("within_7_days")),
                        "within_30_days": _int(expiring.get("within_30_days")),
                    },
                },
                "runtime": {
                    "queue": queue,
                    "callback": callback,
                    "guard": guard,
                    "runs": runs,
                },
                "provider": provider,
                "site_knowledge": {
                    "totals": knowledge_totals,
                    "health": _dict(knowledge.get("health")),
                    "top_sites": _list(knowledge.get("sites"))[:5],
                    "top_intents": _list(knowledge.get("intents"))[:5],
                },
            },
        )

    def get_ops_summary(
        self,
        *,
        scope: str,
        site_id: str | None = None,
        draft_kind: str = "support_reply",
        recent_minutes: int = 60,
        usage_window_days: int = 7,
        audit_window_minutes: int = 1440,
        range_filter: str = "24h",
        limit: int = 25,
        provider_id: str = "",
        model_id: str = FREE_GPT55_MODEL_ID,
        record_audit: bool = True,
        force_refresh: bool = False,
        cache_ttl_seconds: int = 1800,
    ) -> dict[str, Any]:
        advisor = self._resolve_advisor_payload(
            scope=scope,
            site_id=site_id,
            recent_minutes=recent_minutes,
            usage_window_days=usage_window_days,
            audit_window_minutes=audit_window_minutes,
            range_filter=range_filter,
            limit=limit,
        )
        redacted_context = self._build_redacted_summarizer_context(
            advisor,
            draft_kind=draft_kind,
        )
        deterministic = self._build_deterministic_ops_summary(
            redacted_context,
            draft_kind=draft_kind,
        )

        normalized_scope = str(advisor.get("scope") or scope or "").strip()
        normalized_draft_kind = _normalize_draft_kind(draft_kind)
        requested_provider_id = str(provider_id or "").strip()
        if requested_provider_id and not self._is_summarizer_provider_allowed(
            requested_provider_id
        ):
            self._maybe_record_summarizer_audit_event(
                record_audit=record_audit,
                event={
                    "scope": normalized_scope,
                    "site_id": site_id,
                    "draft_kind": normalized_draft_kind,
                    "provider_id": requested_provider_id,
                    "model_id": model_id,
                    "generation_mode": "deterministic_fallback",
                    "outcome": "blocked",
                    "error_code": "provider_not_allowlisted",
                },
            )
            return {
                **deterministic,
                "generation": {
                    "mode": "deterministic_fallback",
                    "provider_id": requested_provider_id,
                    "model_id": model_id,
                    "error_code": "provider_not_allowlisted",
                },
                "ai_disclosure": _build_ai_disclosure("deterministic_fallback"),
            }

        provider = self._select_provider(requested_provider_id)
        if provider is None:
            error_code = "provider_not_configured" if requested_provider_id else ""
            self._maybe_record_summarizer_audit_event(
                record_audit=record_audit,
                event={
                    "scope": normalized_scope,
                    "site_id": site_id,
                    "draft_kind": normalized_draft_kind,
                    "provider_id": requested_provider_id,
                    "model_id": model_id if requested_provider_id else "",
                    "generation_mode": "deterministic_fallback",
                    "outcome": "fallback",
                    "error_code": error_code,
                },
            )
            return {
                **deterministic,
                "generation": {
                    "mode": "deterministic_fallback",
                    "provider_id": requested_provider_id,
                    "model_id": model_id if requested_provider_id else "",
                    "error_code": error_code,
                },
                "ai_disclosure": _build_ai_disclosure("deterministic_fallback"),
            }

        cache_key = _build_ops_summary_cache_key(
            scope=normalized_scope,
            site_id=site_id,
            draft_kind=normalized_draft_kind,
            recent_minutes=recent_minutes,
            usage_window_days=usage_window_days,
            audit_window_minutes=audit_window_minutes,
            range_filter=range_filter,
            limit=limit,
            provider_id=provider.provider_id,
            model_id=model_id,
        )
        if cache_ttl_seconds > 0 and not force_refresh:
            cached = self._get_cached_ops_summary(cache_key=cache_key)
            if cached is not None:
                self._maybe_record_summarizer_audit_event(
                    record_audit=record_audit,
                    event={
                        "scope": normalized_scope,
                        "site_id": site_id,
                        "draft_kind": normalized_draft_kind,
                        "provider_id": provider.provider_id,
                        "model_id": model_id,
                        "generation_mode": "llm_cached",
                        "outcome": "cache_hit",
                        "error_code": "",
                    },
                )
                return cached

        try:
            llm_result = provider.execute(
                ProviderExecutionRequest(
                    run_id=f"advisor_{scope}_{int(datetime.now(UTC).timestamp())}",
                    site_id=site_id or "internal",
                    ability_name="internal_ops_summarizer",
                    profile_id="internal.ops.summarizer",
                    execution_kind="text",
                    model_id=model_id,
                    instance_id=f"{provider.provider_id}:internal-ops-summarizer",
                    endpoint_variant="chat_completions",
                    trace_id="internal_ops_summarizer",
                    input_payload=self._build_summarizer_input_payload(
                        redacted_context,
                        draft_kind=draft_kind,
                    ),
                    policy={
                        "data_contract": SUMMARIZER_VERSION,
                        "customer_content_allowed": False,
                    },
                    timeout_ms=12_000,
                )
            )
        except ProviderExecutionError as error:
            self._maybe_record_summarizer_audit_event(
                record_audit=record_audit,
                event={
                    "scope": normalized_scope,
                    "site_id": site_id,
                    "draft_kind": normalized_draft_kind,
                    "provider_id": provider.provider_id,
                    "model_id": model_id,
                    "generation_mode": "deterministic_fallback",
                    "outcome": "provider_error",
                    "error_code": error.error_code,
                    "tokens_in": error.tokens_in,
                    "tokens_out": error.tokens_out,
                    "cost": error.cost,
                },
            )
            return {
                **deterministic,
                "generation": {
                    "mode": "deterministic_fallback",
                    "provider_id": provider.provider_id,
                    "model_id": model_id,
                    "error_code": error.error_code,
                },
                "ai_disclosure": _build_ai_disclosure("deterministic_fallback"),
            }

        parsed = self._parse_llm_summary_output(
            str(llm_result.output.get("output_text") or ""),
            fallback=deterministic,
        )
        self._maybe_record_summarizer_audit_event(
            record_audit=record_audit,
            event={
                "scope": normalized_scope,
                "site_id": site_id,
                "draft_kind": normalized_draft_kind,
                "provider_id": provider.provider_id,
                "model_id": model_id,
                "generation_mode": "llm",
                "outcome": "success",
                "error_code": "",
                "tokens_in": llm_result.tokens_in,
                "tokens_out": llm_result.tokens_out,
                "cost": llm_result.cost,
            },
        )
        live_result = {
            **parsed,
            "generation": {
                "mode": "llm",
                "provider_id": provider.provider_id,
                "model_id": model_id,
                "error_code": "",
                "tokens_in": llm_result.tokens_in,
                "tokens_out": llm_result.tokens_out,
                "cost": llm_result.cost,
                "request_cost": llm_result.cost,
                "cache_status": "miss",
                "cache_hit": False,
                "cache_key": cache_key,
            },
            "ai_disclosure": _build_ai_disclosure("llm"),
        }
        if cache_ttl_seconds > 0:
            self._store_cached_ops_summary(
                cache_key=cache_key,
                payload=live_result,
                cache_ttl_seconds=cache_ttl_seconds,
                site_id=site_id,
            )
        return live_result

    def get_ops_summary_preview(
        self,
        *,
        scope: str,
        site_id: str | None = None,
        draft_kind: str = "support_reply",
        recent_minutes: int = 60,
        usage_window_days: int = 7,
        audit_window_minutes: int = 1440,
        range_filter: str = "24h",
        limit: int = 25,
        provider_id: str = "",
        model_id: str = FREE_GPT55_MODEL_ID,
        force_refresh: bool = False,
        cache_ttl_seconds: int = 1800,
    ) -> dict[str, Any]:
        baseline = self.get_ops_summary(
            scope=scope,
            site_id=site_id,
            draft_kind=draft_kind,
            recent_minutes=recent_minutes,
            usage_window_days=usage_window_days,
            audit_window_minutes=audit_window_minutes,
            range_filter=range_filter,
            limit=limit,
            provider_id="",
            model_id=model_id,
            record_audit=False,
        )
        ai = self.get_ops_summary(
            scope=scope,
            site_id=site_id,
            draft_kind=draft_kind,
            recent_minutes=recent_minutes,
            usage_window_days=usage_window_days,
            audit_window_minutes=audit_window_minutes,
            range_filter=range_filter,
            limit=limit,
            provider_id=provider_id,
            model_id=model_id,
            record_audit=True,
            force_refresh=force_refresh,
            cache_ttl_seconds=cache_ttl_seconds,
        )
        comparison = _build_ops_summary_comparison(
            baseline=baseline,
            ai=ai,
            requested_provider_id=provider_id,
            model_id=model_id,
        )
        return {
            "preview_version": "internal-ops-summarizer-preview-v1",
            "baseline": baseline,
            "ai": ai,
            "comparison": comparison,
            "safety": {
                "prompt_saved": False,
                "output_text_saved": False,
                "wordpress_write_allowed": False,
                "customer_article_generation_allowed": False,
                "requires_operator_review": True,
            },
        }

    def list_ops_summary_history(
        self,
        *,
        site_id: str | None = None,
        scope: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        bounded_limit = min(100, max(1, int(limit or 20)))
        normalized_site_id = str(site_id or "").strip()
        normalized_scope = str(scope or "").strip()
        conditions = [SiteServiceProjection.projection_kind == "internal_ops_summary_cache"]
        if normalized_site_id:
            conditions.append(SiteServiceProjection.site_id == normalized_site_id)
        with get_session(self.database_url) as session:
            projections = list(
                session.scalars(
                    select(SiteServiceProjection)
                    .where(*conditions)
                    .order_by(
                        SiteServiceProjection.generated_at.desc(),
                        SiteServiceProjection.projection_id.desc(),
                    )
                    .limit(bounded_limit * 3)
                )
            )

        items: list[dict[str, Any]] = []
        for projection in projections:
            item = _ops_summary_history_item(projection)
            if normalized_scope and str(item.get("scope") or "") != normalized_scope:
                continue
            items.append(item)
            if len(items) >= bounded_limit:
                break

        return {
            "history_version": "internal-ops-summary-history-v1",
            "items": items,
            "filters": {
                "site_id": normalized_site_id,
                "scope": normalized_scope,
                "limit": bounded_limit,
            },
        }

    def get_ops_summary_value_metrics(
        self,
        *,
        site_id: str | None = None,
        scope: str = "",
        window_days: int = 7,
        limit: int = 10,
    ) -> dict[str, Any]:
        bounded_window_days = min(90, max(1, int(window_days or 7)))
        bounded_limit = min(50, max(1, int(limit or 10)))
        normalized_site_id = str(site_id or "").strip()
        normalized_scope = _normalize_advisor_scope(scope)
        now = datetime.now(UTC)
        window_start = now - timedelta(days=bounded_window_days)

        conditions = [
            ServiceAuditEvent.event_kind == "internal_advisor.ops_summary",
            ServiceAuditEvent.created_at >= window_start,
        ]
        if normalized_site_id:
            conditions.append(ServiceAuditEvent.site_id == normalized_site_id)
        if normalized_scope:
            conditions.append(ServiceAuditEvent.scope_id == normalized_scope)

        projection_conditions = [
            SiteServiceProjection.projection_kind == "internal_ops_summary_cache",
            SiteServiceProjection.generated_at >= window_start,
        ]
        if normalized_site_id:
            projection_conditions.append(SiteServiceProjection.site_id == normalized_site_id)

        with get_session(self.database_url) as session:
            audit_events = list(
                session.scalars(
                    select(ServiceAuditEvent)
                    .where(*conditions)
                    .order_by(ServiceAuditEvent.created_at.desc(), ServiceAuditEvent.id.desc())
                    .limit(500)
                )
            )
            projections = list(
                session.scalars(
                    select(SiteServiceProjection)
                    .where(*projection_conditions)
                    .order_by(
                        SiteServiceProjection.generated_at.desc(),
                        SiteServiceProjection.projection_id.desc(),
                    )
                    .limit(500)
                )
            )

        by_generation_mode: dict[str, int] = {}
        by_outcome: dict[str, int] = {}
        by_provider: dict[str, dict[str, Any]] = {}
        by_model: dict[str, dict[str, Any]] = {}
        recent_events: list[dict[str, Any]] = []
        totals = {
            "analysis_requests": 0,
            "ai_used": 0,
            "ai_called": 0,
            "cache_hits": 0,
            "deterministic_fallbacks": 0,
            "provider_errors": 0,
            "blocked": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "tokens_total": 0,
            "cost": 0.0,
            "request_cost": 0.0,
            "estimated_cache_savings": 0.0,
        }

        live_costs: list[float] = []
        for event in audit_events:
            payload = _dict(event.payload_json)
            generation_mode = str(payload.get("generation_mode") or "").strip()
            outcome = str(event.outcome or "").strip()
            provider_id = str(payload.get("provider_id") or "").strip()
            model_id = str(payload.get("model_id") or "").strip()
            tokens_in = _int(payload.get("tokens_in"))
            tokens_out = _int(payload.get("tokens_out"))
            cost = _float(payload.get("cost"))
            cache_hit = generation_mode == "llm_cached" or outcome == "cache_hit"

            totals["analysis_requests"] += 1
            totals["tokens_in"] += tokens_in
            totals["tokens_out"] += tokens_out
            totals["cost"] += cost
            totals["request_cost"] += 0.0 if cache_hit else cost
            if generation_mode in {"llm", "llm_cached"}:
                totals["ai_used"] += 1
            if generation_mode == "llm":
                totals["ai_called"] += 1
                live_costs.append(cost)
            if cache_hit:
                totals["cache_hits"] += 1
            if generation_mode == "deterministic_fallback":
                totals["deterministic_fallbacks"] += 1
            if outcome == "provider_error":
                totals["provider_errors"] += 1
            if outcome == "blocked":
                totals["blocked"] += 1

            by_generation_mode[generation_mode or "unknown"] = (
                by_generation_mode.get(generation_mode or "unknown", 0) + 1
            )
            by_outcome[outcome or "unknown"] = by_outcome.get(outcome or "unknown", 0) + 1
            if provider_id:
                provider_item = by_provider.setdefault(
                    provider_id,
                    {"provider_id": provider_id, "requests": 0, "ai_calls": 0, "cost": 0.0},
                )
                provider_item["requests"] += 1
                provider_item["cost"] += cost
                if generation_mode == "llm":
                    provider_item["ai_calls"] += 1
            if model_id:
                model_item = by_model.setdefault(
                    model_id,
                    {"model_id": model_id, "requests": 0, "ai_calls": 0, "cost": 0.0},
                )
                model_item["requests"] += 1
                model_item["cost"] += cost
                if generation_mode == "llm":
                    model_item["ai_calls"] += 1
            if len(recent_events) < bounded_limit:
                recent_events.append(
                    {
                        "created_at": _format_datetime(event.created_at),
                        "site_id": str(event.site_id or ""),
                        "scope": str(event.scope_id or ""),
                        "outcome": outcome,
                        "generation_mode": generation_mode,
                        "provider_id": provider_id,
                        "model_id": model_id,
                        "tokens_in": tokens_in,
                        "tokens_out": tokens_out,
                        "cost": cost,
                        "cache_hit": cache_hit,
                        "error_code": str(payload.get("error_code") or ""),
                    }
                )

        totals["tokens_total"] = totals["tokens_in"] + totals["tokens_out"]
        average_live_cost = sum(live_costs) / len(live_costs) if live_costs else 0.0
        totals["estimated_cache_savings"] = average_live_cost * totals["cache_hits"]
        request_count = max(1, totals["analysis_requests"])
        review_counts = {
            "cached_ai_items": 0,
            "needs_review": 0,
            "human_confirmed": 0,
            "edited_after_ai": 0,
            "reviewed": 0,
        }
        for projection in projections:
            history_item = _ops_summary_history_item(projection)
            if normalized_scope and str(history_item.get("scope") or "") != normalized_scope:
                continue
            disclosure = _dict(history_item.get("ai_disclosure"))
            if not bool(disclosure.get("generated_by_ai")):
                continue
            review_counts["cached_ai_items"] += 1
            review_status = str(disclosure.get("review_status") or "").strip()
            if review_status in review_counts:
                review_counts[review_status] += 1
            if review_status in {"human_confirmed", "edited_after_ai"}:
                review_counts["reviewed"] += 1

        cached_ai_items = max(1, review_counts["cached_ai_items"])
        rates = {
            "ai_usage_rate": totals["ai_used"] / request_count,
            "ai_call_rate": totals["ai_called"] / request_count,
            "cache_hit_rate": totals["cache_hits"] / request_count,
            "fallback_rate": totals["deterministic_fallbacks"] / request_count,
            "review_rate": review_counts["reviewed"] / cached_ai_items,
            "confirmed_rate": review_counts["human_confirmed"] / cached_ai_items,
            "edited_after_ai_rate": review_counts["edited_after_ai"] / cached_ai_items,
            "average_live_request_cost": average_live_cost,
        }
        value_signal = _build_ops_summary_value_signal(
            analysis_requests=int(totals["analysis_requests"]),
            ai_called=int(totals["ai_called"]),
            cache_hits=int(totals["cache_hits"]),
            provider_errors=int(totals["provider_errors"]),
            review_rate=rates["review_rate"],
            confirmed_rate=rates["confirmed_rate"],
            request_cost=totals["request_cost"],
        )
        return {
            "value_metrics_version": "internal-ops-summary-value-v1",
            "window": {
                "days": bounded_window_days,
                "start_at": window_start.isoformat(),
                "end_at": now.isoformat(),
            },
            "filters": {
                "site_id": normalized_site_id,
                "scope": normalized_scope,
                "limit": bounded_limit,
            },
            "totals": totals,
            "rates": rates,
            "review": review_counts,
            "value_signal": value_signal,
            "breakdown": {
                "by_generation_mode": by_generation_mode,
                "by_outcome": by_outcome,
                "by_provider": sorted(
                    by_provider.values(),
                    key=lambda item: (
                        -_float(item.get("cost")),
                        str(item.get("provider_id") or ""),
                    ),
                ),
                "by_model": sorted(
                    by_model.values(),
                    key=lambda item: (-_float(item.get("cost")), str(item.get("model_id") or "")),
                ),
            },
            "recent_events": recent_events,
        }

    def _get_cached_ops_summary(self, *, cache_key: str) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        projection_id = _ops_summary_cache_projection_id(cache_key)
        with get_session(self.database_url) as session:
            projection = session.get(SiteServiceProjection, projection_id)
            if projection is None or _to_utc(projection.fresh_until) <= now:
                return None
            payload = _dict(projection.payload_json)
        cached = _dict(payload.get("summary"))
        if not cached:
            return None
        generation = {
            **_dict(cached.get("generation")),
            "mode": "llm_cached",
            "cache_status": "hit",
            "cache_hit": True,
            "cache_key": cache_key,
            "cache_generated_at": str(payload.get("generated_at") or ""),
            "cache_expires_at": str(payload.get("fresh_until") or ""),
            "request_cost": 0.0,
        }
        cached_disclosure = _dict(cached.get("ai_disclosure"))
        ai_disclosure = {
            **_build_ai_disclosure(
                "llm_cached",
                generated_at=str(payload.get("generated_at") or ""),
            ),
            **cached_disclosure,
            "source_generation_mode": "llm_cached",
            "generated_at": str(
                cached_disclosure.get("generated_at") or payload.get("generated_at") or ""
            ),
        }
        return {
            **cached,
            "generation": generation,
            "ai_disclosure": ai_disclosure,
            "agent_registry_metadata": _agent_registry_metadata(cached),
        }

    def review_ops_summary_disclosure(
        self,
        *,
        cache_key: str,
        review_status: str,
        actor_ref: str,
        note: str = "",
    ) -> dict[str, Any]:
        normalized_cache_key = str(cache_key or "").strip()
        normalized_status = str(review_status or "").strip()
        if normalized_status not in {"human_confirmed", "edited_after_ai", "needs_review"}:
            raise ValueError(
                "review_status must be human_confirmed, edited_after_ai, or needs_review"
            )
        if not normalized_cache_key:
            raise ValueError("cache_key is required")

        now = datetime.now(UTC)
        reviewed_at = now.isoformat()
        projection_id = _ops_summary_cache_projection_id(normalized_cache_key)
        with get_session(self.database_url) as session:
            projection = session.get(SiteServiceProjection, projection_id)
            if projection is None:
                raise ValueError("ops summary cache entry was not found")
            payload = _dict(projection.payload_json)
            summary = _dict(payload.get("summary"))
            if not summary:
                raise ValueError("ops summary cache entry has no summary payload")

            disclosure = {
                **_build_ai_disclosure(
                    "llm_cached",
                    generated_at=str(payload.get("generated_at") or ""),
                ),
                **_dict(summary.get("ai_disclosure")),
            }
            if not bool(disclosure.get("generated_by_ai")):
                raise ValueError("only AI-generated summaries can be reviewed")

            previous_status = str(disclosure.get("review_status") or "")
            disclosure["review_status"] = normalized_status
            disclosure["reviewed_by"] = str(actor_ref or "internal").strip() or "internal"
            disclosure["reviewed_at"] = reviewed_at
            disclosure["review_note"] = str(note or "").strip()[:512]
            if normalized_status == "human_confirmed":
                disclosure["visible_notice"] = "Generated by Npcink AI. Human confirmed before use."
            elif normalized_status == "edited_after_ai":
                disclosure["visible_notice"] = (
                    "AI assisted by Npcink AI. Edited after AI generation; "
                    "human review required before use."
                )
            else:
                disclosure["visible_notice"] = (
                    "Generated by Npcink AI. Human review required before use."
                )

            summary["ai_disclosure"] = disclosure
            payload["summary"] = summary
            projection.payload_json = payload
            flag_modified(projection, "payload_json")
            session.add(
                ServiceAuditEvent(
                    site_id=projection.site_id if projection.site_id != "__platform__" else None,
                    scope_kind="advisor_summary",
                    scope_id=projection.projection_id,
                    event_kind="internal_advisor.ai_disclosure_review",
                    outcome=normalized_status,
                    actor_kind="platform_admin",
                    actor_ref=str(actor_ref or "internal").strip() or "internal",
                    payload_json={
                        "disclosure_version": AI_DISCLOSURE_VERSION,
                        "cache_key": normalized_cache_key,
                        "previous_review_status": previous_status,
                        "review_status": normalized_status,
                        "generated_by_ai": bool(disclosure.get("generated_by_ai")),
                        "content_origin": str(disclosure.get("content_origin") or ""),
                        "source_generation_mode": str(
                            disclosure.get("source_generation_mode") or ""
                        ),
                        "prompt_saved": False,
                        "output_text_saved": False,
                    },
                )
            )
            session.commit()

        return {
            "cache_key": normalized_cache_key,
            "review_status": normalized_status,
            "reviewed_at": reviewed_at,
            "ai_disclosure": disclosure,
        }

    def _store_cached_ops_summary(
        self,
        *,
        cache_key: str,
        payload: dict[str, Any],
        cache_ttl_seconds: int,
        site_id: str | None,
    ) -> None:
        now = datetime.now(UTC)
        fresh_until = now + timedelta(seconds=min(86400, max(60, int(cache_ttl_seconds))))
        projection_id = _ops_summary_cache_projection_id(cache_key)
        cache_payload = {
            "cache_version": "internal-ops-summary-cache-v1",
            "cache_key": cache_key,
            "prompt_saved": False,
            "raw_payload_saved": False,
            "summary": payload,
            "generated_at": now.isoformat(),
            "fresh_until": fresh_until.isoformat(),
        }
        with get_session(self.database_url) as session:
            projection = session.get(SiteServiceProjection, projection_id)
            if projection is None:
                projection = SiteServiceProjection(
                    projection_id=projection_id,
                    site_id=str(site_id or "").strip() or "__platform__",
                    projection_kind="internal_ops_summary_cache",
                    payload_json=cache_payload,
                    generated_at=now,
                    fresh_until=fresh_until,
                    source_revision=SUMMARIZER_VERSION,
                    generation_ms=0,
                    last_error=None,
                    last_error_at=None,
                )
                session.add(projection)
            else:
                projection.site_id = str(site_id or "").strip() or "__platform__"
                projection.payload_json = cache_payload
                projection.generated_at = now
                projection.fresh_until = fresh_until
                projection.source_revision = SUMMARIZER_VERSION
                projection.generation_ms = 0
                projection.last_error = None
                projection.last_error_at = None
            session.commit()

    def _resolve_advisor_payload(
        self,
        *,
        scope: str,
        site_id: str | None,
        recent_minutes: int,
        usage_window_days: int,
        audit_window_minutes: int,
        range_filter: str,
        limit: int,
    ) -> dict[str, Any]:
        normalized_scope = str(scope or "").strip().lower()
        if normalized_scope in {"runtime", "runtime_operations"}:
            return self.get_runtime_advisor(
                site_id=site_id,
                recent_minutes=recent_minutes,
            )
        if normalized_scope in {"commercial", "commercial_operations"}:
            return self.get_commercial_advisor(
                usage_window_days=usage_window_days,
                audit_window_minutes=audit_window_minutes,
            )
        if normalized_scope in {"routing", "routing_operations"}:
            if not str(site_id or "").strip():
                raise ValueError("site_id is required for routing ops summary")
            return self.get_routing_advisor(
                site_id=str(site_id or "").strip(),
                filters={"range": range_filter, "limit": limit},
            )
        if normalized_scope in {"site_diagnostics", "site", "diagnostics"}:
            if not str(site_id or "").strip():
                raise ValueError("site_id is required for site diagnostics ops summary")
            return self.get_site_diagnostic_advisor(
                site_id=str(site_id or "").strip(),
                window_hours=_range_to_hours(range_filter),
            )
        if normalized_scope in {"operations", "operations_analysis", "ops"}:
            return self.get_operations_advisor(
                site_id=site_id,
                window_hours=_range_to_hours(range_filter),
                usage_window_days=usage_window_days,
                audit_window_minutes=audit_window_minutes,
            )
        raise ValueError(
            "scope must be runtime, commercial, routing, site_diagnostics, or operations"
        )

    def _build_redacted_summarizer_context(
        self,
        advisor: dict[str, Any],
        *,
        draft_kind: str,
    ) -> dict[str, Any]:
        return {
            "summarizer_version": SUMMARIZER_VERSION,
            "draft_kind": _normalize_draft_kind(draft_kind),
            "advisor": {
                "advisor_version": str(advisor.get("advisor_version") or ""),
                "scope": str(advisor.get("scope") or ""),
                "status": str(advisor.get("status") or ""),
                "severity": str(advisor.get("severity") or ""),
                "headline": str(advisor.get("headline") or ""),
                "summary": str(advisor.get("summary") or ""),
                "confidence": str(advisor.get("confidence") or ""),
                "agent_handoff": _redacted_agent_handoff(advisor.get("agent_handoff")),
                "evidence": [
                    {
                        "kind": str(item.get("kind") or ""),
                        "ref": str(item.get("ref") or ""),
                        "label": str(item.get("label") or ""),
                    }
                    for item in _list(advisor.get("evidence"))
                    if isinstance(item, dict)
                ][:6],
                "recommended_actions": [
                    {
                        "action": str(item.get("action") or ""),
                        "requires_operator": bool(item.get("requires_operator")),
                    }
                    for item in _list(advisor.get("recommended_actions"))
                    if isinstance(item, dict)
                ][:6],
                "signals": [
                    self._redact_signal(signal)
                    for signal in _list(advisor.get("signals"))
                    if isinstance(signal, dict)
                ][:8],
                "drilldown": self._build_redacted_advisor_drilldown(advisor),
            },
            "forbidden": [
                "do_not_generate_customer_article_or_marketing_content",
                "do_not_write_or_modify_wordpress",
                "do_not_claim_operator_action_was_taken",
                "do_not_include_secrets_prompts_payloads_or_callback_bodies",
            ],
        }

    def _redact_signal(self, signal: dict[str, Any]) -> dict[str, Any]:
        allowed_keys = {
            "code",
            "state",
            "count",
            "failed",
            "queued_runs",
            "recent_events",
            "recent_rate_limit_exceeded",
            "recent_replay_blocked",
            "within_7_days",
            "within_30_days",
            "recommended_profile_ids",
            "avoid_provider_ids",
            "avoid_profile_ids",
            "active_sites",
            "total_sites",
            "attention_subscriptions",
            "subscriptions_expiring_7d",
            "usage_events",
            "meter_quantity",
            "reported_cost",
            "provider_cost",
            "tokens_total",
            "total_runs",
            "failed_runs",
            "run_failure_rate",
            "callback_failed",
            "guard_events",
            "provider_calls",
            "provider_errors",
            "provider_error_rate",
            "fallbacks",
            "avg_latency_ms",
            "top_provider",
            "knowledge_searches",
            "knowledge_no_hits",
            "knowledge_no_hit_rate",
            "knowledge_failed_searches",
            "indexed_documents",
            "indexed_chunks",
        }
        return {
            key: value
            for key, value in signal.items()
            if key in allowed_keys and _is_json_scalar_or_list(value)
        }

    def _build_redacted_advisor_drilldown(
        self,
        advisor: dict[str, Any],
    ) -> dict[str, Any]:
        if str(advisor.get("scope") or "") != "operations_analysis":
            return {}
        source = _dict(advisor.get("source"))
        runtime = _dict(source.get("runtime"))
        runs = _dict(runtime.get("runs"))
        provider = _dict(source.get("provider"))
        site_knowledge = _dict(source.get("site_knowledge"))
        commercial = _dict(source.get("commercial"))

        return {
            "failed_runs": [
                _pick_fields(
                    item,
                    {
                        "run_id",
                        "site_id",
                        "ability_name",
                        "ability_family",
                        "status",
                        "error_code",
                        "selected_provider_id",
                        "selected_model_id",
                        "started_at",
                    },
                )
                for item in _list(runs.get("recent_failed_runs"))[:8]
                if isinstance(item, dict)
            ],
            "run_sites": [
                _pick_fields(item, {"site_id", "run_count", "failed_runs", "last_run_at"})
                for item in _list(runs.get("top_sites"))[:8]
                if isinstance(item, dict)
            ],
            "ability_families": [
                _pick_fields(item, {"ability_family", "run_count", "failed_runs"})
                for item in _list(runs.get("ability_families"))[:8]
                if isinstance(item, dict)
            ],
            "provider_breakdown": [
                _pick_fields(
                    item,
                    {
                        "provider_id",
                        "call_count",
                        "error_count",
                        "cost",
                        "avg_latency_ms",
                        "last_call_at",
                    },
                )
                for item in _list(provider.get("providers"))[:8]
                if isinstance(item, dict)
            ],
            "model_breakdown": [
                _pick_fields(item, {"model_id", "call_count", "cost"})
                for item in _list(provider.get("models"))[:8]
                if isinstance(item, dict)
            ],
            "knowledge_sites": [
                _pick_fields(
                    item,
                    {
                        "site_id",
                        "queries_total",
                        "no_hit_total",
                        "no_hit_rate",
                        "avg_latency_ms",
                        "document_count",
                        "chunk_count",
                        "last_search_finished_at",
                    },
                )
                for item in _list(site_knowledge.get("top_sites"))[:8]
                if isinstance(item, dict)
            ],
            "knowledge_intents": [
                _pick_fields(
                    item,
                    {"intent", "queries_total", "no_hit_total", "no_hit_rate", "avg_latency_ms"},
                )
                for item in _list(site_knowledge.get("top_intents"))[:8]
                if isinstance(item, dict)
            ],
            "usage": {
                "event_count": _int(_dict(commercial.get("recent_usage")).get("event_count")),
                "totals": _pick_fields(
                    _dict(_dict(commercial.get("recent_usage")).get("totals")),
                    {"runs", "tokens", "cost", "quantity"},
                ),
            },
        }

    def _build_summarizer_input_payload(
        self,
        redacted_context: dict[str, Any],
        *,
        draft_kind: str,
    ) -> dict[str, Any]:
        return {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You write internal cloud operations summaries only. "
                        "Do not generate articles, SEO content, WordPress content, "
                        "or customer-facing claims that action has already been taken. "
                        "Return strict JSON with keys operator_summary, support_draft, "
                        "operator_next_step, and safety_note."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": _normalize_draft_kind(draft_kind),
                            "redacted_context": redacted_context,
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                },
            ],
            "params": {
                "temperature": 0.2,
                "max_tokens": 900,
                "response_format": {"type": "json_object"},
            },
        }

    def _build_deterministic_ops_summary(
        self,
        redacted_context: dict[str, Any],
        *,
        draft_kind: str,
    ) -> dict[str, Any]:
        advisor = _dict(redacted_context.get("advisor"))
        actions = _list(advisor.get("recommended_actions"))
        first_action = (
            str(_dict(actions[0]).get("action") or "continue_monitoring")
            if actions
            else "continue_monitoring"
        )
        headline = str(advisor.get("headline") or "Cloud advisor summary")
        summary = str(advisor.get("summary") or "Review the linked evidence.")
        support_draft = (
            "We are reviewing a cloud service signal for your site. "
            "The current evidence points to an operational condition, and our "
            "team will follow up after checking the referenced diagnostics."
        )
        if _normalize_draft_kind(draft_kind) == "operator_summary":
            support_draft = ""

        return {
            "summarizer_version": SUMMARIZER_VERSION,
            "draft_kind": _normalize_draft_kind(draft_kind),
            "scope": str(advisor.get("scope") or ""),
            "status": str(advisor.get("status") or ""),
            "severity": str(advisor.get("severity") or ""),
            "headline": headline,
            "operator_summary": f"{headline}: {summary}",
            "support_draft": support_draft,
            "operator_next_step": first_action,
            "safety_note": (
                "Internal ops draft only. It does not generate customer content, "
                "write WordPress, or execute operator actions."
            ),
            "agent_handoff": _redacted_agent_handoff(advisor.get("agent_handoff")),
            "agent_registry_metadata": _agent_registry_metadata(advisor),
            "evidence": _list(advisor.get("evidence")),
            "source_context": redacted_context,
            "generated_at": datetime.now(UTC).isoformat(),
            "ai_disclosure": _build_ai_disclosure("deterministic_fallback"),
        }

    def _select_provider(self, provider_id: str) -> ProviderAdapter | None:
        normalized_provider_id = str(provider_id or "").strip()
        if not normalized_provider_id:
            return None
        return self.providers.get(normalized_provider_id)

    def _is_summarizer_provider_allowed(self, provider_id: str) -> bool:
        normalized_provider_id = str(provider_id or "").strip()
        return normalized_provider_id in self.allowed_summarizer_provider_ids

    def _record_summarizer_audit_event(
        self,
        *,
        scope: str,
        site_id: str | None,
        draft_kind: str,
        provider_id: str,
        model_id: str,
        generation_mode: str,
        outcome: str,
        error_code: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost: float = 0.0,
    ) -> None:
        with get_session(self.database_url) as session:
            session.add(
                ServiceAuditEvent(
                    site_id=str(site_id or "").strip() or None,
                    scope_kind="advisor_scope",
                    scope_id=str(scope or "").strip() or None,
                    event_kind="internal_advisor.ops_summary",
                    outcome=outcome,
                    actor_kind="internal_token",
                    payload_json={
                        "summarizer_version": SUMMARIZER_VERSION,
                        "draft_kind": _normalize_draft_kind(draft_kind),
                        "generation_mode": generation_mode,
                        "provider_id": str(provider_id or ""),
                        "model_id": str(model_id or ""),
                        "error_code": str(error_code or ""),
                        "tokens_in": max(0, int(tokens_in or 0)),
                        "tokens_out": max(0, int(tokens_out or 0)),
                        "cost": max(0.0, float(cost or 0.0)),
                        "prompt_saved": False,
                        "output_text_saved": False,
                    },
                )
            )
            session.commit()

    def _maybe_record_summarizer_audit_event(
        self,
        *,
        record_audit: bool,
        event: dict[str, Any],
    ) -> None:
        if not record_audit:
            return
        self._record_summarizer_audit_event(
            scope=str(event.get("scope") or ""),
            site_id=str(event.get("site_id") or "") or None,
            draft_kind=str(event.get("draft_kind") or ""),
            provider_id=str(event.get("provider_id") or ""),
            model_id=str(event.get("model_id") or ""),
            generation_mode=str(event.get("generation_mode") or ""),
            outcome=str(event.get("outcome") or ""),
            error_code=str(event.get("error_code") or ""),
            tokens_in=_int(event.get("tokens_in")),
            tokens_out=_int(event.get("tokens_out")),
            cost=_float(event.get("cost")),
        )

    def _parse_llm_summary_output(
        self,
        output_text: str,
        *,
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        parsed = _parse_json_object_text(output_text)

        operator_summary = str(parsed.get("operator_summary") or "").strip()
        support_draft = str(parsed.get("support_draft") or "").strip()
        operator_next_step = str(parsed.get("operator_next_step") or "").strip()
        safety_note = str(parsed.get("safety_note") or "").strip()
        if not operator_summary and output_text.strip():
            operator_summary = output_text.strip()[:1000]

        return {
            **fallback,
            "operator_summary": operator_summary or fallback["operator_summary"],
            "support_draft": support_draft or fallback["support_draft"],
            "operator_next_step": operator_next_step or fallback["operator_next_step"],
            "safety_note": safety_note or fallback["safety_note"],
        }

    def _get_run_operations_metrics(
        self,
        *,
        site_id: str | None,
        window_hours: int,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        since = now - timedelta(hours=min(168, max(1, int(window_hours or 24))))
        conditions = [RunRecord.started_at >= since, RunRecord.started_at <= now]
        if site_id:
            conditions.append(RunRecord.site_id == site_id)
        with get_session(self.database_url) as session:
            totals = session.execute(
                select(
                    func.count(RunRecord.run_id),
                    func.sum(case((RunRecord.status == "succeeded", 1), else_=0)),
                    func.sum(case((RunRecord.status == "failed", 1), else_=0)),
                    func.sum(case((RunRecord.status == "queued", 1), else_=0)),
                    func.sum(case((RunRecord.status == "running", 1), else_=0)),
                    func.count(func.distinct(RunRecord.site_id)),
                    func.max(RunRecord.started_at),
                ).where(*conditions)
            ).one()
            site_rows = session.execute(
                select(
                    RunRecord.site_id,
                    func.count(RunRecord.run_id),
                    func.sum(case((RunRecord.status == "failed", 1), else_=0)),
                    func.max(RunRecord.started_at),
                )
                .where(*conditions)
                .group_by(RunRecord.site_id)
                .order_by(desc(func.count(RunRecord.run_id)))
                .limit(5)
            ).all()
            ability_rows = session.execute(
                select(
                    RunRecord.ability_family,
                    func.count(RunRecord.run_id),
                    func.sum(case((RunRecord.status == "failed", 1), else_=0)),
                )
                .where(*conditions)
                .group_by(RunRecord.ability_family)
                .order_by(desc(func.count(RunRecord.run_id)))
                .limit(5)
            ).all()
            recent_failed_runs = list(
                session.scalars(
                    select(RunRecord)
                    .where(*conditions, RunRecord.status == "failed")
                    .order_by(RunRecord.started_at.desc(), RunRecord.run_id.desc())
                    .limit(8)
                )
            )

        total_runs = _int(totals[0])
        failed_runs = _int(totals[2])
        return {
            "window_hours": window_hours,
            "total_runs": total_runs,
            "succeeded_runs": _int(totals[1]),
            "failed_runs": failed_runs,
            "queued_runs": _int(totals[3]),
            "running_runs": _int(totals[4]),
            "active_site_count": _int(totals[5]),
            "failure_rate": round(failed_runs / total_runs, 4) if total_runs else 0.0,
            "last_run_at": _format_datetime(totals[6]),
            "top_sites": [
                {
                    "site_id": str(row[0] or ""),
                    "run_count": _int(row[1]),
                    "failed_runs": _int(row[2]),
                    "last_run_at": _format_datetime(row[3]),
                }
                for row in site_rows
            ],
            "ability_families": [
                {
                    "ability_family": str(row[0] or ""),
                    "run_count": _int(row[1]),
                    "failed_runs": _int(row[2]),
                }
                for row in ability_rows
            ],
            "recent_failed_runs": [
                {
                    "run_id": run.run_id,
                    "site_id": run.site_id,
                    "ability_name": run.ability_name,
                    "ability_family": run.ability_family,
                    "status": run.status,
                    "error_code": run.error_code or "",
                    "selected_provider_id": run.selected_provider_id or "",
                    "selected_model_id": run.selected_model_id or "",
                    "started_at": _format_datetime(run.started_at),
                }
                for run in recent_failed_runs
            ],
        }

    def _get_provider_operations_metrics(
        self,
        *,
        site_id: str | None,
        window_hours: int,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        since = now - timedelta(hours=min(168, max(1, int(window_hours or 24))))
        conditions = [
            ProviderCallRecord.created_at >= since,
            ProviderCallRecord.created_at <= now,
        ]
        needs_run_join = bool(site_id)
        if site_id:
            conditions.append(RunRecord.site_id == site_id)
        with get_session(self.database_url) as session:
            statement = select(
                func.count(ProviderCallRecord.id),
                func.sum(case((ProviderCallRecord.error_code != "", 1), else_=0)),
                func.sum(case((ProviderCallRecord.fallback_used.is_(True), 1), else_=0)),
                func.sum(ProviderCallRecord.tokens_in),
                func.sum(ProviderCallRecord.tokens_out),
                func.sum(ProviderCallRecord.cost),
                func.avg(ProviderCallRecord.latency_ms),
                func.max(ProviderCallRecord.created_at),
            )
            provider_statement = select(
                ProviderCallRecord.provider_id,
                func.count(ProviderCallRecord.id),
                func.sum(case((ProviderCallRecord.error_code != "", 1), else_=0)),
                func.sum(ProviderCallRecord.cost),
                func.avg(ProviderCallRecord.latency_ms),
                func.max(ProviderCallRecord.created_at),
            )
            model_statement = select(
                ProviderCallRecord.model_id,
                func.count(ProviderCallRecord.id),
                func.sum(ProviderCallRecord.cost),
            )
            if needs_run_join:
                statement = statement.join(
                    RunRecord,
                    RunRecord.run_id == ProviderCallRecord.run_id,
                )
                provider_statement = provider_statement.join(
                    RunRecord,
                    RunRecord.run_id == ProviderCallRecord.run_id,
                )
                model_statement = model_statement.join(
                    RunRecord,
                    RunRecord.run_id == ProviderCallRecord.run_id,
                )
            totals = session.execute(statement.where(*conditions)).one()
            provider_rows = session.execute(
                provider_statement.where(*conditions)
                .group_by(ProviderCallRecord.provider_id)
                .order_by(desc(func.count(ProviderCallRecord.id)))
                .limit(5)
            ).all()
            model_rows = session.execute(
                model_statement.where(*conditions)
                .group_by(ProviderCallRecord.model_id)
                .order_by(desc(func.count(ProviderCallRecord.id)))
                .limit(5)
            ).all()

        call_count = _int(totals[0])
        error_count = _int(totals[1])
        tokens_in = _int(totals[3])
        tokens_out = _int(totals[4])
        top_provider_id = str(provider_rows[0][0] or "") if provider_rows else ""
        return {
            "window_hours": window_hours,
            "call_count": call_count,
            "error_count": error_count,
            "error_rate": round(error_count / call_count, 4) if call_count else 0.0,
            "fallback_count": _int(totals[2]),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "tokens_total": tokens_in + tokens_out,
            "cost": round(_float(totals[5]), 6),
            "avg_latency_ms": round(_float(totals[6])),
            "last_call_at": _format_datetime(totals[7]),
            "top_provider_id": top_provider_id,
            "providers": [
                {
                    "provider_id": str(row[0] or ""),
                    "call_count": _int(row[1]),
                    "error_count": _int(row[2]),
                    "cost": round(_float(row[3]), 6),
                    "avg_latency_ms": round(_float(row[4])),
                    "last_call_at": _format_datetime(row[5]),
                }
                for row in provider_rows
            ],
            "models": [
                {
                    "model_id": str(row[0] or ""),
                    "call_count": _int(row[1]),
                    "cost": round(_float(row[2]), 6),
                }
                for row in model_rows
            ],
        }

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
            "agent_handoff": _advisor_agent_handoff(scope),
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


def _site_diagnostic_item(
    item: dict[str, Any],
    *,
    generated_at: str,
    window: dict[str, Any],
) -> dict[str, Any]:
    source = str(item.get("source") or "").strip().lower()
    code = str(item.get("code") or "site_diagnostics.attention").strip()
    state = _dict(item.get("state"))
    workflow_status = _site_diagnostic_workflow_status(
        str(state.get("workflow_status") or item.get("workflow_status") or "active")
    )
    updated_at = str(state.get("updated_at") or generated_at)
    diagnostic_key = _site_diagnostic_key(
        attention_key=str(item.get("attention_key") or ""),
        source=source,
        code=code,
        title=str(item.get("title") or ""),
    )
    return {
        "diagnostic_key": diagnostic_key,
        "code": code,
        "severity": str(item.get("severity") or "warning"),
        "source": source or "monitoring",
        "title": str(item.get("title") or "Site monitoring needs attention"),
        "evidence_summary": str(item.get("detail") or ""),
        "likely_cause": _site_diagnostic_likely_cause(source=source, code=code),
        "next_step": str(item.get("suggested_action") or "Open site monitoring detail."),
        "recommended_action_id": _site_diagnostic_action_id(source=source, code=code),
        "workflow_status": workflow_status,
        "status_detail": {
            "workflow_status": workflow_status,
            "status_source": "operator_state" if state else "monitoring_signal",
            "allowed_statuses": ["new", "acknowledged", "muted", "resolved"],
            "muted_until": str(state.get("muted_until") or ""),
            "operator_note": str(state.get("operator_note") or ""),
            "updated_at": updated_at,
        },
        "evidence_window": {
            "hours": _int(window.get("hours")),
            "start_at": str(window.get("start_at") or ""),
            "end_at": str(window.get("end_at") or ""),
        },
        "last_updated_at": updated_at,
        "operator_review_required": True,
        "direct_wordpress_write": False,
    }


def _site_diagnostic_key(
    *,
    attention_key: str,
    source: str,
    code: str,
    title: str,
) -> str:
    if attention_key:
        return f"plugin_attention:{attention_key}"
    seed = json.dumps(
        {
            "source": source or "monitoring",
            "code": code,
            "title": title,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"site_diag:{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:24]}"


def _site_diagnostic_workflow_status(value: str) -> str:
    status = str(value or "").strip().lower()
    if status == "active":
        return "new"
    if status in {"new", "acknowledged", "muted", "resolved"}:
        return status
    return "new"


def _site_diagnostic_workflow_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        "new": 0,
        "acknowledged": 0,
        "muted": 0,
        "resolved": 0,
    }
    for item in items:
        status = _site_diagnostic_workflow_status(str(item.get("workflow_status") or "new"))
        counts[status] += 1
    return {
        **counts,
        "total": len(items),
        "needs_attention": counts["new"] + counts["acknowledged"],
        "allowed_statuses": ["new", "acknowledged", "muted", "resolved"],
    }


def _site_diagnostic_likely_cause(*, source: str, code: str) -> str:
    if source == "keys":
        return "Cloud API key state can block telemetry, runtime requests, or diagnostics."
    if source == "plugins":
        return (
            "Plugin telemetry reports active errors, stale reporting, or missing expected "
            "plugins."
        )
    if source == "media":
        return "Cloud media processing is failing or receiving unsupported source assets."
    if source == "vector":
        return (
            "Site Knowledge index coverage may be empty, stale, or missing matching public "
            "content."
        )
    if source == "runtime":
        return "Hosted runtime runs are failing or experiencing provider/runtime pressure."
    if source == "quota":
        return "Current period usage is close to or over the active entitlement budget."
    if source == "activity":
        return "The connected WordPress site may not be flushing recent telemetry to Cloud."
    if "api_key" in code:
        return "Cloud API key connectivity needs review."
    return "Site monitoring has evidence that should be reviewed before attempting a local fix."


def _site_diagnostic_action_id(*, source: str, code: str) -> str:
    if source == "keys":
        return "inspect_cloud_api_key_connection"
    if source == "plugins":
        return "inspect_plugin_observability_attention"
    if source == "media":
        return "inspect_media_failures_and_source_assets"
    if source == "vector":
        return "inspect_site_knowledge_index_and_refresh"
    if source == "runtime":
        return "inspect_runtime_runs_provider_health"
    if source == "quota":
        return "review_usage_quota_and_entitlement"
    if source == "activity":
        return "verify_cloud_addon_connection_and_event_flush"
    if "api_key" in code:
        return "inspect_cloud_api_key_connection"
    return "inspect_site_monitoring_detail"


def _redacted_agent_handoff(value: Any) -> dict[str, Any]:
    handoff = _dict(value)
    if not handoff:
        return {}
    return {
        "agent_id": str(handoff.get("agent_id") or ""),
        "agent_version": str(handoff.get("agent_version") or ""),
        "agent_role": str(handoff.get("agent_role") or ""),
        "handoff_type": str(handoff.get("handoff_type") or ""),
        "handoff_owner": str(handoff.get("handoff_owner") or ""),
        "requires_operator_review": bool(handoff.get("requires_operator_review")),
        "direct_wordpress_write": bool(handoff.get("direct_wordpress_write")),
        "execution_pattern": str(handoff.get("execution_pattern") or ""),
        "storage_mode": str(handoff.get("storage_mode") or ""),
        "allowed_actions": [
            str(item) for item in _list(handoff.get("allowed_actions"))[:8] if str(item).strip()
        ],
        "stop_conditions": [
            str(item) for item in _list(handoff.get("stop_conditions"))[:8] if str(item).strip()
        ],
        "forbidden_actions": [
            str(item) for item in _list(handoff.get("forbidden_actions"))[:10] if str(item).strip()
        ],
        "fail_closed_behavior": str(handoff.get("fail_closed_behavior") or ""),
    }


def _advisor_agent_handoff(scope: str) -> dict[str, Any]:
    normalized_scope = str(scope or "").strip() or "runtime_operations"
    return get_agent_handoff_metadata(
        INTERNAL_OPS_ADVISOR_AGENT_ID,
        agent_role=normalized_scope,
    )


def _agent_registry_metadata(value: Any) -> dict[str, Any]:
    handoff = _redacted_agent_handoff(
        _dict(value).get("agent_registry_metadata") or _dict(value).get("agent_handoff")
    )
    agent_id = str(handoff.get("agent_id") or "").strip()
    if not agent_id:
        return {}
    return _redacted_agent_handoff(
        get_agent_handoff_metadata(
            agent_id,
            agent_role=str(handoff.get("agent_role") or "").strip() or None,
        )
    )


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


def _pick_fields(value: dict[str, Any], allowed_keys: set[str]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if key in allowed_keys and _is_json_scalar_or_list(item)
    }


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


def _normalize_draft_kind(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"operator_summary", "support_reply"}:
        return normalized
    return "support_reply"


def _normalize_advisor_scope(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"runtime", "runtime_operations"}:
        return "runtime_operations"
    if normalized in {"commercial", "commercial_operations"}:
        return "commercial_operations"
    if normalized in {"routing", "routing_operations"}:
        return "routing_operations"
    if normalized in {"site", "diagnostics", "site_diagnostics"}:
        return "site_diagnostics"
    if normalized in {"operations", "operations_analysis", "ops"}:
        return "operations_analysis"
    return normalized


def _build_ops_summary_value_signal(
    *,
    analysis_requests: int,
    ai_called: int,
    cache_hits: int,
    provider_errors: int,
    review_rate: float,
    confirmed_rate: float,
    request_cost: float,
) -> dict[str, str]:
    if analysis_requests <= 0:
        return {
            "status": "insufficient_data",
            "headline": "No AI analysis usage yet",
            "next_step": (
                "Run a few manual AI analyses, then review cost, cache reuse, "
                "and human confirmation."
            ),
        }
    if provider_errors > 0 and ai_called == 0:
        return {
            "status": "provider_blocked",
            "headline": "Provider calls are not producing usable AI output",
            "next_step": "Fix provider configuration or allowlist before judging value.",
        }
    if ai_called == 0 and cache_hits == 0:
        return {
            "status": "not_using_ai",
            "headline": "Current traffic is not exercising the AI branch",
            "next_step": (
                "Enable an allowlisted provider or run preview with a provider id "
                "to measure AI value."
            ),
        }
    if confirmed_rate >= 0.5:
        return {
            "status": "promising",
            "headline": "Human confirmations suggest the AI analysis is useful",
            "next_step": (
                "Keep the feature manual-triggered and watch cache hit rate before "
                "expanding user exposure."
            ),
        }
    if review_rate <= 0.0 and request_cost > 0:
        return {
            "status": "needs_review_loop",
            "headline": "AI is costing money before operators confirm value",
            "next_step": (
                "Require operators to mark useful, edited, or rejected outputs "
                "before increasing traffic."
            ),
        }
    return {
        "status": "monitor",
        "headline": "AI value is still inconclusive",
        "next_step": (
            "Collect more manual analyses and compare confirmation rate against request cost."
        ),
    }


def _range_to_hours(value: str) -> int:
    normalized = str(value or "").strip().lower()
    if normalized.endswith("h"):
        return min(168, max(1, _int(normalized[:-1])))
    if normalized.endswith("d"):
        return min(168, max(1, _int(normalized[:-1]) * 24))
    if normalized in {"7d", "week"}:
        return 168
    return 24


def _to_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.fromtimestamp(0, UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _format_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return ""


def _build_ops_summary_cache_key(
    *,
    scope: str,
    site_id: str | None,
    draft_kind: str,
    recent_minutes: int,
    usage_window_days: int,
    audit_window_minutes: int,
    range_filter: str,
    limit: int,
    provider_id: str,
    model_id: str,
) -> str:
    payload = {
        "version": SUMMARIZER_VERSION,
        "scope": str(scope or ""),
        "site_id": str(site_id or ""),
        "draft_kind": str(draft_kind or ""),
        "recent_minutes": max(1, int(recent_minutes or 0)),
        "usage_window_days": max(1, int(usage_window_days or 0)),
        "audit_window_minutes": max(1, int(audit_window_minutes or 0)),
        "range": str(range_filter or ""),
        "limit": max(1, int(limit or 0)),
        "provider_id": str(provider_id or ""),
        "model_id": str(model_id or ""),
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _ops_summary_cache_projection_id(cache_key: str) -> str:
    return f"internal-ops-summary-cache:{cache_key[:64]}"


def _ops_summary_history_item(projection: SiteServiceProjection) -> dict[str, Any]:
    payload = _dict(projection.payload_json)
    summary = _dict(payload.get("summary"))
    generation = _dict(summary.get("generation"))
    disclosure = _dict(summary.get("ai_disclosure"))
    cache_key = str(payload.get("cache_key") or generation.get("cache_key") or "")
    cost = _float(generation.get("cost"))
    request_cost = _float(generation.get("request_cost"))
    return {
        "projection_id": str(projection.projection_id or ""),
        "cache_key": cache_key,
        "site_id": "" if projection.site_id == "__platform__" else str(projection.site_id or ""),
        "scope": str(summary.get("scope") or ""),
        "status": str(summary.get("status") or ""),
        "severity": str(summary.get("severity") or ""),
        "headline": str(summary.get("headline") or ""),
        "operator_summary": str(summary.get("operator_summary") or "")[:600],
        "operator_next_step": str(summary.get("operator_next_step") or ""),
        "draft_kind": str(summary.get("draft_kind") or ""),
        "generated_at": str(
            payload.get("generated_at") or _format_datetime(projection.generated_at)
        ),
        "fresh_until": str(payload.get("fresh_until") or _format_datetime(projection.fresh_until)),
        "is_stale": _to_utc(projection.fresh_until) <= datetime.now(UTC),
        "generation": {
            "mode": str(generation.get("mode") or ""),
            "provider_id": str(generation.get("provider_id") or ""),
            "model_id": str(generation.get("model_id") or ""),
            "tokens_in": _int(generation.get("tokens_in")),
            "tokens_out": _int(generation.get("tokens_out")),
            "cost": cost,
            "request_cost": request_cost,
            "cache_status": str(generation.get("cache_status") or ""),
            "cache_hit": bool(generation.get("cache_hit")),
        },
        "ai_disclosure": {
            "version": str(disclosure.get("version") or ""),
            "content_origin": str(disclosure.get("content_origin") or ""),
            "generated_by_ai": bool(disclosure.get("generated_by_ai")),
            "visible_label": str(disclosure.get("visible_label") or ""),
            "visible_notice": str(disclosure.get("visible_notice") or ""),
            "review_status": str(disclosure.get("review_status") or ""),
            "reviewed_by": str(disclosure.get("reviewed_by") or ""),
            "reviewed_at": str(disclosure.get("reviewed_at") or ""),
            "source_generation_mode": str(disclosure.get("source_generation_mode") or ""),
        },
        "agent_handoff": _redacted_agent_handoff(summary.get("agent_handoff")),
        "agent_registry_metadata": _agent_registry_metadata(summary),
    }


def _build_ai_disclosure(
    generation_mode: str,
    *,
    generated_at: str = "",
) -> dict[str, Any]:
    mode = str(generation_mode or "").strip()
    is_ai_generated = mode in {"llm", "llm_cached"}
    if is_ai_generated:
        return {
            "version": AI_DISCLOSURE_VERSION,
            "content_origin": "ai_generated",
            "generated_by_ai": True,
            "ai_assisted": True,
            "visible_label_required": True,
            "visible_label": "AI generated",
            "brand_label": "Npcink AI",
            "visible_notice": "Generated by Npcink AI. Human review required before use.",
            "review_status": "needs_review",
            "provider_brand_visible": False,
            "machine_readable_required": True,
            "copy_export_notice": "AI generated by Npcink AI; human review required.",
            "source_generation_mode": mode,
            "generated_at": generated_at,
        }
    return {
        "version": AI_DISCLOSURE_VERSION,
        "content_origin": "rule_generated",
        "generated_by_ai": False,
        "ai_assisted": False,
        "visible_label_required": False,
        "visible_label": "Rule generated",
        "brand_label": "Npcink AI",
        "visible_notice": "Generated from deterministic cloud rules.",
        "review_status": "not_ai_generated",
        "provider_brand_visible": False,
        "machine_readable_required": False,
        "copy_export_notice": "",
        "source_generation_mode": mode,
        "generated_at": generated_at,
    }


def _parse_json_object_text(value: str) -> dict[str, Any]:
    text = str(value or "").strip()
    if not text:
        return {}
    candidates = [text]
    if text.startswith("```"):
        unfenced = text.strip("`").strip()
        if unfenced.lower().startswith("json"):
            unfenced = unfenced[4:].strip()
        candidates.append(unfenced)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _build_ops_summary_comparison(
    *,
    baseline: dict[str, Any],
    ai: dict[str, Any],
    requested_provider_id: str,
    model_id: str,
) -> dict[str, Any]:
    baseline_generation = _dict(baseline.get("generation"))
    ai_generation = _dict(ai.get("generation"))
    tokens_in = _int(ai_generation.get("tokens_in"))
    tokens_out = _int(ai_generation.get("tokens_out"))
    cost = _float(ai_generation.get("cost"))
    request_cost = _float(ai_generation.get("request_cost"))
    cache_hit = bool(ai_generation.get("cache_hit"))
    cache_status = str(ai_generation.get("cache_status") or "")
    text_changed = any(
        str(baseline.get(field) or "").strip() != str(ai.get(field) or "").strip()
        for field in (
            "operator_summary",
            "support_draft",
            "operator_next_step",
            "safety_note",
        )
    )
    ai_mode = str(ai_generation.get("mode") or "")
    ai_called = ai_mode == "llm"
    ai_used = ai_mode in {"llm", "llm_cached"}
    error_code = str(ai_generation.get("error_code") or "")
    if ai_used and text_changed:
        value_check = "review_ai_output"
    elif requested_provider_id and error_code == "provider_not_allowlisted":
        value_check = "configure_provider_allowlist"
    elif requested_provider_id and error_code == "provider_not_configured":
        value_check = "configure_provider_adapter"
    elif not requested_provider_id:
        value_check = "pass_provider_id_to_test_llm"
    else:
        value_check = "no_material_difference"

    return {
        "baseline_mode": str(baseline_generation.get("mode") or ""),
        "ai_mode": ai_mode,
        "requested_provider_id": str(requested_provider_id or ""),
        "model_id": str(model_id or ""),
        "ai_used": ai_used,
        "ai_called": ai_called,
        "cache_hit": cache_hit,
        "cache_status": cache_status,
        "text_changed": text_changed,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost": cost,
        "request_cost": request_cost,
        "error_code": error_code,
        "value_check": value_check,
    }


def _is_json_scalar_or_list(value: Any) -> bool:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return True
    if isinstance(value, list):
        return all(isinstance(item, (str, int, float, bool)) for item in value[:12])
    return False
