from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, desc, func, select

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
)
from app.domain.commercial.service import CommercialService
from app.domain.runtime.service import RuntimeService
from app.domain.site_knowledge.metrics import SiteKnowledgeObservabilityService
from app.domain.usage.service import UsageService

ADVISOR_VERSION = "internal-ai-advisor-v1"
SUMMARIZER_VERSION = "internal-ops-summarizer-v1"


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

        signals = [
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
                "knowledge_failed_searches": _int(
                    knowledge_totals.get("search_failed_total")
                ),
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

        if _float(knowledge_totals.get("no_hit_rate")) >= 0.25 and _int(
            knowledge_totals.get("search_queries_total")
        ) >= 4:
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
        model_id: str = "internal-ops-summarizer",
        record_audit: bool = True,
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
            }

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
        return {
            **parsed,
            "generation": {
                "mode": "llm",
                "provider_id": provider.provider_id,
                "model_id": model_id,
                "error_code": "",
                "tokens_in": llm_result.tokens_in,
                "tokens_out": llm_result.tokens_out,
                "cost": llm_result.cost,
            },
        }

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
        model_id: str = "internal-ops-summarizer",
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
        if normalized_scope in {"operations", "operations_analysis", "ops"}:
            return self.get_operations_advisor(
                site_id=site_id,
                window_hours=_range_to_hours(range_filter),
                usage_window_days=usage_window_days,
                audit_window_minutes=audit_window_minutes,
            )
        raise ValueError("scope must be runtime, commercial, routing, or operations")

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
                "max_tokens": 600,
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
            "evidence": _list(advisor.get("evidence")),
            "source_context": redacted_context,
            "generated_at": datetime.now(UTC).isoformat(),
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


def _normalize_draft_kind(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"operator_summary", "support_reply"}:
        return normalized
    return "support_reply"


def _range_to_hours(value: str) -> int:
    normalized = str(value or "").strip().lower()
    if normalized.endswith("h"):
        return min(168, max(1, _int(normalized[:-1])))
    if normalized.endswith("d"):
        return min(168, max(1, _int(normalized[:-1]) * 24))
    if normalized in {"7d", "week"}:
        return 168
    return 24


def _format_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return ""


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
    text_changed = any(
        str(baseline.get(field) or "").strip() != str(ai.get(field) or "").strip()
        for field in (
            "operator_summary",
            "support_draft",
            "operator_next_step",
            "safety_note",
        )
    )
    ai_called = str(ai_generation.get("mode") or "") == "llm"
    error_code = str(ai_generation.get("error_code") or "")
    if ai_called and text_changed:
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
        "ai_mode": str(ai_generation.get("mode") or ""),
        "requested_provider_id": str(requested_provider_id or ""),
        "model_id": str(model_id or ""),
        "ai_called": ai_called,
        "text_changed": text_changed,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost": cost,
        "error_code": error_code,
        "value_check": value_check,
    }


def _is_json_scalar_or_list(value: Any) -> bool:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return True
    if isinstance(value, list):
        return all(isinstance(item, (str, int, float, bool)) for item in value[:12])
    return False
