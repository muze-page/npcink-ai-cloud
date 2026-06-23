from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from app.domain.web_search.contracts import ALLOWED_WEB_SEARCH_INTENTS, WEB_SEARCH_CONTRACT
from app.domain.web_search.service import WEB_SEARCH_PROVIDER_ORDER

AUTO_SEARCH_TRIGGER_INTENTS = frozenset(
    {
        "fact_check",
        "news",
        "writing_context",
        "competitor_research",
        "source_discovery",
        "external_links",
    }
)
AUTO_SEARCH_MODES = frozenset({"off", "auto", "required", "dry_run"})
AUTO_SEARCH_CHANNELS = frozenset(
    {
        "agent_gateway",
        "agent_gateway_direct",
        "openapi",
        "openclaw",
        "openclaw_adapter",
    }
)
AUTO_SEARCH_HINT_TERMS = frozenset(
    {
        "breaking",
        "citation",
        "citations",
        "competitor",
        "current",
        "fact check",
        "fact-check",
        "latest",
        "news",
        "recent",
        "source",
        "sources",
        "verify",
    }
)
MAX_AUTO_SEARCH_RESULTS = 5
MAX_AUTO_SEARCH_RECENCY_DAYS = 30


@dataclass(slots=True)
class AutomaticWebSearchPlan:
    mode: str
    trigger: str
    query: str
    intent: str
    provider: str
    max_results: int
    recency_days: int
    language: str
    region: str
    enhance_with_reader: bool
    evidence_policy: dict[str, Any]

    @property
    def is_required(self) -> bool:
        return self.mode == "required"

    @property
    def is_dry_run(self) -> bool:
        return self.mode == "dry_run"

    def to_web_search_input(self) -> dict[str, Any]:
        return {
            "contract_version": WEB_SEARCH_CONTRACT,
            "query": self.query,
            "intent": self.intent,
            "provider": self.provider,
            "max_results": self.max_results,
            "recency_days": self.recency_days,
            "language": self.language,
            "region": self.region,
            "enhance_with_reader": self.enhance_with_reader,
            "evidence_policy": self.evidence_policy,
            "write_posture": "suggestion_only",
        }

    def to_report(self, *, status: str, error_code: str = "", message: str = "") -> dict[str, Any]:
        return {
            "status": status,
            "mode": self.mode,
            "trigger": self.trigger,
            "intent": self.intent,
            "provider": self.provider,
            "query_hash": _hash_query(self.query),
            "query_chars": len(self.query),
            "max_results": self.max_results,
            "recency_days": self.recency_days,
            "enhance_with_reader": self.enhance_with_reader,
            "error_code": error_code,
            "message": message,
            "write_posture": "suggestion_only",
            "direct_wordpress_write": False,
        }


def build_automatic_web_search_plan(
    input_payload: dict[str, Any],
    *,
    ability_name: str,
    workflow_id: str = "",
    channel: str = "",
) -> AutomaticWebSearchPlan | None:
    if not isinstance(input_payload, dict):
        return None

    raw_policy = input_payload.get("search_policy") or input_payload.get("web_search_policy")
    policy = raw_policy if isinstance(raw_policy, dict) else {}
    requires_external_evidence = _bool(
        policy.get("requires_external_evidence")
        if "requires_external_evidence" in policy
        else input_payload.get("requires_external_evidence")
    )
    mode = _normalize_mode(policy.get("mode"))
    trigger = "search_policy"
    channel = _normalize_channel(channel or input_payload.get("channel") or "")

    if not mode:
        if requires_external_evidence:
            mode = "auto"
            trigger = "requires_external_evidence"
        elif _has_channel_auto_search_hint(
            input_payload,
            ability_name=ability_name,
            workflow_id=workflow_id,
            channel=channel,
        ):
            mode = "auto"
            requires_external_evidence = True
            trigger = "channel_external_evidence_hint"
        else:
            return None
    if mode == "off":
        return None

    intent = _normalize_intent(
        policy.get("intent") or input_payload.get("search_intent") or input_payload.get("intent")
    )
    if (
        mode == "auto"
        and not requires_external_evidence
        and intent not in AUTO_SEARCH_TRIGGER_INTENTS
    ):
        return None

    query = _normalize_query(
        policy.get("query")
        or input_payload.get("search_query")
        or input_payload.get("query")
        or input_payload.get("topic")
        or input_payload.get("title")
        or input_payload.get("headline")
    )
    if not query:
        if mode == "required":
            query = _fallback_query(ability_name=ability_name, workflow_id=workflow_id)
        if not query:
            return None

    return AutomaticWebSearchPlan(
        mode=mode,
        trigger=trigger,
        query=query,
        intent=intent,
        provider=_normalize_provider(policy.get("provider")),
        max_results=_positive_int(
            policy.get("max_results"),
            default=3,
            maximum=MAX_AUTO_SEARCH_RESULTS,
        ),
        recency_days=max(
            0,
            min(
                MAX_AUTO_SEARCH_RECENCY_DAYS,
                _positive_int(
                    policy.get("recency_days"),
                    default=_default_recency_days(intent),
                    maximum=MAX_AUTO_SEARCH_RECENCY_DAYS,
                ),
            ),
        ),
        language=_normalize_token(policy.get("language") or input_payload.get("language")),
        region=_normalize_token(policy.get("region") or input_payload.get("region")),
        enhance_with_reader=_bool(policy.get("enhance_with_reader")),
        evidence_policy=_normalize_evidence_policy(policy.get("evidence_policy")),
    )


def build_automatic_web_search_success_report(
    plan: AutomaticWebSearchPlan,
    result_json: dict[str, Any],
    *,
    usage: Any = None,
) -> dict[str, Any]:
    evidence_gate = result_json.get("evidence_gate")
    evidence_gate = evidence_gate if isinstance(evidence_gate, dict) else {}
    results = result_json.get("results")
    result_count = len(results) if isinstance(results, list) else 0
    report = plan.to_report(status="ready")
    report.update(
        {
            "provider": str(result_json.get("provider") or plan.provider),
            "result_count": result_count,
            "evidence_gate": evidence_gate,
            "reader_enhancement": result_json.get("reader_enhancement")
            if isinstance(result_json.get("reader_enhancement"), dict)
            else {},
            "usage_summary": _usage_summary(usage),
        }
    )
    return report


def attach_automatic_web_search_evidence(
    input_payload: dict[str, Any],
    *,
    result_json: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    updated = dict(input_payload)
    raw_cloud_evidence = updated.get("cloud_evidence")
    cloud_evidence = raw_cloud_evidence if isinstance(raw_cloud_evidence, dict) else {}
    cloud_evidence = dict(cloud_evidence)
    cloud_evidence["web_search"] = {
        "source": "cloud_managed_automatic_web_search",
        "report": report,
        "result": result_json,
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
    }
    updated["cloud_evidence"] = cloud_evidence
    return updated


def _normalize_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in AUTO_SEARCH_MODES else ""


def _normalize_intent(value: Any) -> str:
    intent = str(value or "").strip().lower()
    return intent if intent in ALLOWED_WEB_SEARCH_INTENTS else "general_research"


def _normalize_provider(value: Any) -> str:
    provider = str(value or "auto").strip().lower()
    return provider if provider in {"auto", *WEB_SEARCH_PROVIDER_ORDER} else "auto"


def _normalize_channel(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _normalize_query(value: Any) -> str:
    return " ".join(str(value or "").split())[:500].strip()


def _fallback_query(*, ability_name: str, workflow_id: str) -> str:
    query = " ".join(part for part in (workflow_id, ability_name) if part).strip()
    return query[:500]


def _default_recency_days(intent: str) -> int:
    if intent == "news":
        return 7
    if intent in {"competitor_research", "external_links", "fact_check", "source_discovery"}:
        return 30
    return 7


def _has_channel_auto_search_hint(
    input_payload: dict[str, Any],
    *,
    ability_name: str,
    workflow_id: str,
    channel: str,
) -> bool:
    detected_channel = channel
    if detected_channel not in AUTO_SEARCH_CHANNELS:
        caller = input_payload.get("caller")
        caller = caller if isinstance(caller, dict) else {}
        detected_channel = _normalize_channel(
            caller.get("caller_type")
            or caller.get("channel")
            or input_payload.get("caller_type")
            or input_payload.get("source_channel")
        )
    if detected_channel not in AUTO_SEARCH_CHANNELS:
        return False

    if str(ability_name or "").startswith("npcink-cloud/"):
        return False

    text = " ".join(
        str(value or "")
        for value in (
            input_payload.get("search_intent"),
            input_payload.get("intent"),
            input_payload.get("topic"),
            input_payload.get("title"),
            input_payload.get("headline"),
            input_payload.get("user_intent"),
            input_payload.get("user_request"),
            input_payload.get("request"),
            workflow_id,
            ability_name,
        )
    ).lower()
    if not text.strip():
        return False
    return any(term in text for term in AUTO_SEARCH_HINT_TERMS)


def _normalize_token(value: Any) -> str:
    return " ".join(str(value or "").split()).replace(" ", "")[:16]


def _normalize_evidence_policy(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    return {
        "min_score": _nonnegative_float(raw.get("min_score")),
        "required_sources": _positive_int(raw.get("required_sources"), default=1, maximum=5),
        "no_hit_policy": str(raw.get("no_hit_policy") or "abstain")
        if str(raw.get("no_hit_policy") or "abstain") in {"abstain", "fallback_to_general"}
        else "abstain",
    }


def _positive_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return max(1, min(maximum, normalized))


def _nonnegative_float(value: Any) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, normalized)


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _hash_query(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def _usage_summary(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    return {
        "provider_id": str(getattr(usage, "provider_id", "") or ""),
        "model_id": str(getattr(usage, "model_id", "") or ""),
        "instance_id": str(getattr(usage, "instance_id", "") or ""),
        "region": str(getattr(usage, "region", "") or ""),
        "latency_ms": max(0, int(getattr(usage, "latency_ms", 0) or 0)),
        "cost": max(0.0, float(getattr(usage, "cost", 0.0) or 0.0)),
        "error_code": str(getattr(usage, "error_code", "") or ""),
    }
