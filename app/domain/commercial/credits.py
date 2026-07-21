from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from math import ceil
from typing import Any, cast

from app.domain.site_knowledge.contracts import SITE_KNOWLEDGE_SYNC_ABILITY

AI_CREDIT_RATE_VERSION = "ai-credit-ledger-v2"
AI_CREDIT_CHARGE_CONTRACT_VERSION = "ai-credit-charge-contract-v1"
SITE_KNOWLEDGE_INDEX_METERING_CLASS = "site_knowledge_index_maintenance"
PAID_CREDIT_BALANCE_SOURCE_TYPES = frozenset(
    {"credit_pack_purchase", "credit_pack_refund"}
)
AI_CREDIT_CHARGE_COMPONENT_REQUIRED_FIELDS = (
    "source_type",
    "charge_mode",
    "unit",
    "rate",
    "minimum_charge",
    "idempotency_scope",
    "budget_key",
)
AI_CREDIT_CHARGE_CAPABILITY_REQUIRED_FIELDS = (
    "capability_key",
    "charge_mode",
    "request_base_credits",
    "ledger_components",
    "idempotency_scope",
    "budget_key",
)
AI_CREDIT_FEATURE_CHARGE_RULE_REQUIRED_FIELDS = (
    "feature_key",
    "capability_key",
    "charge_policy",
    "ledger_components",
    "limit_policy",
    "budget_key",
    "contract_version",
)


def package_credit_net_delta(entries: Iterable[object]) -> float:
    """Return period delta for package quota, excluding paid-credit balance events."""

    total = 0.0
    for entry in entries:
        source_type = str(getattr(entry, "source_type", "") or "")
        if source_type in PAID_CREDIT_BALANCE_SOURCE_TYPES:
            continue
        total += float(getattr(entry, "credit_delta", 0.0) or 0.0)
    return round(total, 6)


def package_credit_used(entries: Iterable[object]) -> float:
    """Return package allowance used after ordinary grants and adjustments."""

    return round(max(0.0, -package_credit_net_delta(entries)), 6)

AI_CREDIT_BREAKDOWN_ORDER = (
    "runs",
    "tokens_total",
    "web_search",
    "zhihu_global_search",
    "zhihu_research",
    "zhihu_hot_topics",
    "zhihu_direct_answer_simple",
    "zhihu_direct_answer_deep",
    "zhihu_direct_answer_deepsearch",
    "image_recommendation",
    "audio_generation",
    "provider_calls_other",
    "vector_documents",
    "vector_chunks",
)

AI_CREDIT_COMPONENT_LABELS = {
    "runs": "Hosted runs",
    "tokens_total": "Model tokens",
    "web_search": "Search calls",
    "zhihu_global_search": "Zhihu global search calls",
    "zhihu_research": "Zhihu search calls",
    "zhihu_hot_topics": "Zhihu hot-list calls",
    "zhihu_direct_answer_simple": "Zhihu direct answer simple calls",
    "zhihu_direct_answer_deep": "Zhihu direct answer deep calls",
    "zhihu_direct_answer_deepsearch": "Zhihu direct answer DeepSearch calls",
    "image_recommendation": "Image recommendation calls",
    "audio_generation": "Audio generation calls",
    "provider_calls_other": "Other provider calls",
    "vector_documents": "Vector indexed articles",
    "vector_chunks": "Vector indexed chunks",
}

AI_CREDIT_COMPONENT_POLICY_REGISTRY: dict[str, dict[str, object]] = {
    "runs": {
        "source_type": "runs",
        "label": AI_CREDIT_COMPONENT_LABELS["runs"],
        "charge_mode": "consume",
        "unit": "run",
        "rate": 1.0,
        "rate_unit": None,
        "rounding": "none",
    },
    "tokens_total": {
        "source_type": "tokens_total",
        "label": AI_CREDIT_COMPONENT_LABELS["tokens_total"],
        "charge_mode": "consume",
        "unit": "token",
        "rate": 1.0,
        "rate_unit": "1000_tokens_rounded_up",
        "rounding": "ceil_per_1000",
    },
    "web_search": {
        "source_type": "web_search",
        "label": AI_CREDIT_COMPONENT_LABELS["web_search"],
        "charge_mode": "consume",
        "unit": "call",
        "rate": 5.0,
        "rate_unit": None,
        "rounding": "none",
    },
    "zhihu_global_search": {
        "source_type": "zhihu_global_search",
        "label": AI_CREDIT_COMPONENT_LABELS["zhihu_global_search"],
        "charge_mode": "consume",
        "unit": "call",
        "rate": 2.0,
        "rate_unit": None,
        "rounding": "none",
    },
    "zhihu_research": {
        "source_type": "zhihu_research",
        "label": AI_CREDIT_COMPONENT_LABELS["zhihu_research"],
        "charge_mode": "consume",
        "unit": "call",
        "rate": 2.0,
        "rate_unit": None,
        "rounding": "none",
    },
    "zhihu_hot_topics": {
        "source_type": "zhihu_hot_topics",
        "label": AI_CREDIT_COMPONENT_LABELS["zhihu_hot_topics"],
        "charge_mode": "consume",
        "unit": "call",
        "rate": 1.0,
        "rate_unit": None,
        "rounding": "none",
    },
    "zhihu_direct_answer_simple": {
        "source_type": "zhihu_direct_answer_simple",
        "label": AI_CREDIT_COMPONENT_LABELS["zhihu_direct_answer_simple"],
        "charge_mode": "consume",
        "unit": "call",
        "rate": 2.0,
        "rate_unit": None,
        "rounding": "none",
    },
    "zhihu_direct_answer_deep": {
        "source_type": "zhihu_direct_answer_deep",
        "label": AI_CREDIT_COMPONENT_LABELS["zhihu_direct_answer_deep"],
        "charge_mode": "consume",
        "unit": "call",
        "rate": 5.0,
        "rate_unit": None,
        "rounding": "none",
    },
    "zhihu_direct_answer_deepsearch": {
        "source_type": "zhihu_direct_answer_deepsearch",
        "label": AI_CREDIT_COMPONENT_LABELS["zhihu_direct_answer_deepsearch"],
        "charge_mode": "consume",
        "unit": "call",
        "rate": 10.0,
        "rate_unit": None,
        "rounding": "none",
    },
    "image_recommendation": {
        "source_type": "image_recommendation",
        "label": AI_CREDIT_COMPONENT_LABELS["image_recommendation"],
        "charge_mode": "consume",
        "unit": "call",
        "rate": 3.0,
        "rate_unit": None,
        "rounding": "none",
    },
    "audio_generation": {
        "source_type": "audio_generation",
        "label": AI_CREDIT_COMPONENT_LABELS["audio_generation"],
        "charge_mode": "consume",
        "unit": "call",
        "rate": 5.0,
        "rate_unit": None,
        "rounding": "none",
    },
    "provider_calls_other": {
        "source_type": "provider_calls_other",
        "label": AI_CREDIT_COMPONENT_LABELS["provider_calls_other"],
        "charge_mode": "meter_only",
        "unit": "call",
        "rate": 0.0,
        "rate_unit": None,
        "rounding": "none",
    },
    "vector_documents": {
        "source_type": "vector_documents",
        "label": AI_CREDIT_COMPONENT_LABELS["vector_documents"],
        "charge_mode": "meter_only",
        "unit": "document",
        "rate": 0.0,
        "rate_unit": None,
        "rounding": "none",
    },
    "vector_chunks": {
        "source_type": "vector_chunks",
        "label": AI_CREDIT_COMPONENT_LABELS["vector_chunks"],
        "charge_mode": "meter_only",
        "unit": "chunk",
        "rate": 0.0,
        "rate_unit": "10_chunks",
        "rounding": "ceil_per_10",
    },
}

AI_CREDIT_CAPABILITY_POLICY_REGISTRY: dict[str, dict[str, object]] = {
    "runtime:text": {
        "capability_key": "runtime:text",
        "ability_families": ["text", "workflow", "automation", "openclaw"],
        "execution_kinds": ["text"],
        "charge_mode": "run_and_provider_usage",
        "request_base_credits": 1.0,
        "ledger_components": ["runs", "tokens_total", "provider_calls_other"],
    },
    "runtime:web_search": {
        "capability_key": "runtime:web_search",
        "ability_families": ["tool", "knowledge", "workflow"],
        "execution_kinds": ["web_search", "search"],
        "charge_mode": "run_and_provider_usage",
        "request_base_credits": 1.0,
        "ledger_components": [
            "runs",
            "web_search",
            "zhihu_global_search",
            "zhihu_research",
            "zhihu_hot_topics",
            "zhihu_direct_answer_simple",
            "zhihu_direct_answer_deep",
            "zhihu_direct_answer_deepsearch",
        ],
    },
    "runtime:image": {
        "capability_key": "runtime:image",
        "ability_families": ["vision"],
        "execution_kinds": [
            "image_source",
            "image_generation",
            "vision",
            "media_derivative",
        ],
        "charge_mode": "run_and_provider_usage",
        "request_base_credits": 1.0,
        "ledger_components": ["runs", "tokens_total", "image_recommendation"],
    },
    "runtime:audio": {
        "capability_key": "runtime:audio",
        "ability_families": ["audio"],
        "execution_kinds": ["audio_generation"],
        "charge_mode": "run_and_provider_usage",
        "request_base_credits": 1.0,
        "ledger_components": ["runs", "tokens_total", "audio_generation"],
    },
    "runtime:site_knowledge": {
        "capability_key": "runtime:site_knowledge",
        "ability_families": ["knowledge"],
        "execution_kinds": ["embedding", "site_knowledge"],
        "charge_mode": "run_and_query_embedding_usage",
        "request_base_credits": 1.0,
        "ledger_components": ["runs", "tokens_total"],
    },
    "runtime:batch": {
        "capability_key": "runtime:batch",
        "ability_families": ["automation", "workflow"],
        "execution_kinds": ["nightly_site_inspection", "cloud_batch_runtime"],
        "charge_mode": "run_and_provider_usage",
        "request_base_credits": 1.0,
        "ledger_components": ["runs", "tokens_total", "provider_calls_other"],
    },
}

AI_CREDIT_FEATURE_CHARGE_RULES_VERSION = "ai-credit-feature-charge-rules-v1"
AI_CREDIT_FEATURE_CHARGE_RULES: dict[str, dict[str, object]] = {
    "hosted_text_runtime": {
        "feature_key": "hosted_text_runtime",
        "capability_key": "runtime:text",
        "charge_policy": "charge_base_run_and_provider_usage",
        "ledger_components": ["runs", "tokens_total", "provider_calls_other"],
        "limit_policy": "ai_credits_required_before_execute",
        "budget_key": "ai_credits",
        "contract_version": AI_CREDIT_FEATURE_CHARGE_RULES_VERSION,
    },
    "ai_search": {
        "feature_key": "ai_search",
        "capability_key": "runtime:web_search",
        "charge_policy": "charge_base_run_and_search_provider_usage",
        "ledger_components": [
            "runs",
            "web_search",
            "zhihu_global_search",
            "zhihu_research",
            "zhihu_hot_topics",
            "zhihu_direct_answer_simple",
            "zhihu_direct_answer_deep",
            "zhihu_direct_answer_deepsearch",
        ],
        "limit_policy": "ai_credits_required_before_execute",
        "budget_key": "ai_credits",
        "contract_version": AI_CREDIT_FEATURE_CHARGE_RULES_VERSION,
    },
    "image_recommendation_generation": {
        "feature_key": "image_recommendation_generation",
        "capability_key": "runtime:image",
        "charge_policy": "charge_base_run_tokens_and_image_provider_usage",
        "ledger_components": ["runs", "tokens_total", "image_recommendation"],
        "limit_policy": "ai_credits_required_before_execute",
        "budget_key": "ai_credits",
        "contract_version": AI_CREDIT_FEATURE_CHARGE_RULES_VERSION,
    },
    "audio_generation": {
        "feature_key": "audio_generation",
        "capability_key": "runtime:audio",
        "charge_policy": "charge_base_run_tokens_and_audio_provider_usage",
        "ledger_components": ["runs", "tokens_total", "audio_generation"],
        "limit_policy": "ai_credits_required_before_execute",
        "budget_key": "ai_credits",
        "contract_version": AI_CREDIT_FEATURE_CHARGE_RULES_VERSION,
    },
    "batch_cloud_runtime": {
        "feature_key": "batch_cloud_runtime",
        "capability_key": "runtime:batch",
        "charge_policy": "charge_base_run_and_provider_usage",
        "ledger_components": ["runs", "tokens_total", "provider_calls_other"],
        "limit_policy": "ai_credits_required_before_execute",
        "budget_key": "ai_credits",
        "contract_version": AI_CREDIT_FEATURE_CHARGE_RULES_VERSION,
    },
}

for component_policy in AI_CREDIT_COMPONENT_POLICY_REGISTRY.values():
    component_policy.setdefault("minimum_charge", 0.0)
    component_policy.setdefault("idempotency_scope", "ledger_component")
    component_policy.setdefault("budget_key", "ai_credits")

for capability_policy in AI_CREDIT_CAPABILITY_POLICY_REGISTRY.values():
    capability_policy.setdefault("idempotency_scope", "runtime_request")
    capability_policy.setdefault("budget_key", "ai_credits")

ZHIHU_PROVIDER_CREDIT_COMPONENTS: dict[str, dict[str, object]] = {
    "zhihu_global_search": {
        "source_type": "zhihu_global_search",
        **AI_CREDIT_COMPONENT_POLICY_REGISTRY["zhihu_global_search"],
    },
    "zhihu_research": {
        "source_type": "zhihu_research",
        **AI_CREDIT_COMPONENT_POLICY_REGISTRY["zhihu_research"],
    },
    "zhihu_hot_topics": {
        "source_type": "zhihu_hot_topics",
        **AI_CREDIT_COMPONENT_POLICY_REGISTRY["zhihu_hot_topics"],
    },
    "zhida_simple": {
        "source_type": "zhihu_direct_answer_simple",
        **AI_CREDIT_COMPONENT_POLICY_REGISTRY["zhihu_direct_answer_simple"],
    },
    "zhida_deep": {
        "source_type": "zhihu_direct_answer_deep",
        **AI_CREDIT_COMPONENT_POLICY_REGISTRY["zhihu_direct_answer_deep"],
    },
    "zhida_deepsearch": {
        "source_type": "zhihu_direct_answer_deepsearch",
        **AI_CREDIT_COMPONENT_POLICY_REGISTRY["zhihu_direct_answer_deepsearch"],
    },
}


def classify_provider_credit_component(
    *,
    execution_kind: str | None,
    ability_family: str | None,
    payload_json: dict[str, object] | None = None,
) -> dict[str, object]:
    normalized_execution_kind = str(execution_kind or "").strip().lower()
    normalized_ability_family = str(ability_family or "").strip().lower()
    zhihu_component = classify_zhihu_provider_credit_component(payload_json)
    if zhihu_component is not None:
        return zhihu_component
    if "search" in normalized_execution_kind:
        return dict(AI_CREDIT_COMPONENT_POLICY_REGISTRY["web_search"])
    if "audio" in normalized_execution_kind or normalized_ability_family == "audio":
        return dict(AI_CREDIT_COMPONENT_POLICY_REGISTRY["audio_generation"])
    if "image" in normalized_execution_kind or normalized_ability_family == "vision":
        return dict(AI_CREDIT_COMPONENT_POLICY_REGISTRY["image_recommendation"])
    return dict(AI_CREDIT_COMPONENT_POLICY_REGISTRY["provider_calls_other"])


def classify_zhihu_provider_credit_component(
    payload_json: dict[str, object] | None,
) -> dict[str, object] | None:
    payload = payload_json if isinstance(payload_json, dict) else {}
    provider = _payload_token(payload, "provider", "provider_id")
    source_type = _payload_token(payload, "source_type", "managed_source")
    intent = _payload_token(payload, "intent")
    if provider and provider != "zhihu" and not source_type.startswith("zhihu"):
        return None

    lane = source_type or intent
    if lane == "zhihu_hot_list":
        lane = "zhihu_hot_topics"
    if lane == "zhihu_search":
        lane = "zhihu_research"
    if lane in ZHIHU_PROVIDER_CREDIT_COMPONENTS:
        return dict(ZHIHU_PROVIDER_CREDIT_COMPONENTS[lane])
    if provider == "zhihu":
        return dict(ZHIHU_PROVIDER_CREDIT_COMPONENTS["zhihu_research"])
    return None


def is_site_knowledge_index_meter_event(event: object) -> bool:
    return _event_payload(event).get("metering_class") == SITE_KNOWLEDGE_INDEX_METERING_CLASS


def usage_meter_credit_component(event: object) -> dict[str, object] | None:
    if is_site_knowledge_index_meter_event(event):
        return None
    meter_key = str(getattr(event, "meter_key", "") or "").strip()
    quantity = _coerce_float(getattr(event, "quantity", 0.0))
    if meter_key == "runs":
        return {
            **AI_CREDIT_COMPONENT_POLICY_REGISTRY["runs"],
            "quantity": quantity,
            "credits": quantity,
        }
    if meter_key == "tokens_total":
        return {
            **AI_CREDIT_COMPONENT_POLICY_REGISTRY["tokens_total"],
            "quantity": quantity,
            "credits": rounded_token_credits(quantity),
        }
    if meter_key == "provider_calls":
        component = classify_provider_credit_component(
            execution_kind=str(getattr(event, "execution_kind", "") or ""),
            ability_family=str(getattr(event, "ability_family", "") or ""),
            payload_json=_event_payload(event),
        )
        return {
            **component,
            "quantity": quantity,
            "credits": quantity * _coerce_float(component.get("rate")),
        }
    return None


def resolve_ai_credit_capability_policy(
    *,
    ability_family: str | None,
    execution_kind: str | None,
) -> dict[str, object]:
    normalized_family = str(ability_family or "").strip().lower()
    normalized_kind = str(execution_kind or "").strip().lower()
    if normalized_kind in {"web_search", "search"} or "search" in normalized_kind:
        return dict(AI_CREDIT_CAPABILITY_POLICY_REGISTRY["runtime:web_search"])
    if normalized_family == "audio" or "audio" in normalized_kind:
        return dict(AI_CREDIT_CAPABILITY_POLICY_REGISTRY["runtime:audio"])
    if normalized_family == "vision" or "image" in normalized_kind or normalized_kind == "vision":
        return dict(AI_CREDIT_CAPABILITY_POLICY_REGISTRY["runtime:image"])
    if normalized_family == "knowledge" or normalized_kind in {"embedding", "site_knowledge"}:
        return dict(AI_CREDIT_CAPABILITY_POLICY_REGISTRY["runtime:site_knowledge"])
    if normalized_kind in {"nightly_site_inspection", "cloud_batch_runtime"}:
        return dict(AI_CREDIT_CAPABILITY_POLICY_REGISTRY["runtime:batch"])
    return dict(AI_CREDIT_CAPABILITY_POLICY_REGISTRY["runtime:text"])


def list_ai_credit_feature_charge_rules() -> list[dict[str, object]]:
    return [
        dict(rule)
        for _, rule in sorted(AI_CREDIT_FEATURE_CHARGE_RULES.items(), key=lambda item: item[0])
    ]


def estimate_runtime_request_ai_credits(
    *,
    ability_family: str | None,
    execution_kind: str | None,
    ability_name: str | None = None,
    payload_json: dict[str, object] | None = None,
) -> float:
    if str(ability_name or "").strip() == SITE_KNOWLEDGE_SYNC_ABILITY:
        return 0.0
    capability = resolve_ai_credit_capability_policy(
        ability_family=ability_family,
        execution_kind=execution_kind,
    )
    estimate = _coerce_float(capability.get("request_base_credits"))
    normalized_kind = str(execution_kind or "").strip().lower()
    if normalized_kind in {"web_search", "search"} or "search" in normalized_kind:
        provider_component = classify_provider_credit_component(
            execution_kind=execution_kind,
            ability_family=ability_family,
            payload_json=payload_json,
        )
        estimate += max(0.0, _coerce_float(provider_component.get("rate")))
    elif str(ability_family or "").strip().lower() == "vision" or "image" in normalized_kind:
        estimate += _coerce_float(
            AI_CREDIT_COMPONENT_POLICY_REGISTRY["image_recommendation"].get("rate")
        )
    elif str(ability_family or "").strip().lower() == "audio" or "audio" in normalized_kind:
        estimate += _coerce_float(
            AI_CREDIT_COMPONENT_POLICY_REGISTRY["audio_generation"].get("rate")
        )
    return round(max(0.0, estimate), 6)


def record_credit_ledger_component(
    *,
    repository: object,
    account_id: str | None,
    site_id: str | None,
    subscription_id: str | None,
    plan_version_id: str | None,
    run_id: str | None,
    provider_call_id: int | None,
    component: Mapping[str, object],
    source_id: str,
    idempotency_key: str,
    metadata_json: dict[str, object] | None = None,
    created_at: datetime | None = None,
) -> object | None:
    source_type = str(component.get("source_type") or "").strip()
    if not source_type:
        return None
    credits = _coerce_float(component.get("credits"))
    if credits <= 0:
        return None
    return cast(Any, repository).record_credit_ledger_entry(
        account_id=account_id,
        site_id=site_id,
        subscription_id=subscription_id,
        plan_version_id=plan_version_id,
        run_id=run_id,
        provider_call_id=provider_call_id,
        source_type=source_type,
        source_id=source_id,
        credit_delta=-credits,
        quantity=_coerce_float(component.get("quantity")),
        unit=str(component.get("unit") or "credit"),
        rate=_coerce_float(component.get("rate")),
        rate_unit=(
            str(component.get("rate_unit"))
            if component.get("rate_unit") is not None
            else None
        ),
        rate_version=AI_CREDIT_RATE_VERSION,
        idempotency_key=idempotency_key,
        metadata_json=metadata_json,
        created_at=created_at,
    )


def rounded_token_credits(quantity: int | float) -> int:
    return _ceil_positive(_coerce_float(quantity) / 1000.0)


def build_credit_breakdown_from_ledger(entries: Iterable[object]) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    for entry in entries:
        if str(getattr(entry, "event_type", "") or "") != "consume":
            continue
        source_type = str(getattr(entry, "source_type", "") or "").strip()
        if not source_type:
            continue
        item = grouped.setdefault(
            source_type,
            {
                "key": source_type,
                "label": AI_CREDIT_COMPONENT_LABELS.get(source_type, source_type),
                "quantity": 0.0,
                "unit": str(getattr(entry, "unit", "") or "credit"),
                "rate": _coerce_float(getattr(entry, "rate", 0.0)),
                "rate_unit": getattr(entry, "rate_unit", None),
                "credits": 0.0,
            },
        )
        item["quantity"] = _coerce_float(item.get("quantity")) + _coerce_float(
            getattr(entry, "quantity", 0.0)
        )
        item["credits"] = _coerce_float(item.get("credits")) + max(
            0.0,
            -_coerce_float(getattr(entry, "credit_delta", 0.0)),
        )

    def sort_key(item: dict[str, object]) -> tuple[int, str]:
        key = str(item.get("key") or "")
        try:
            return (AI_CREDIT_BREAKDOWN_ORDER.index(key), key)
        except ValueError:
            return (len(AI_CREDIT_BREAKDOWN_ORDER), key)

    items = sorted(grouped.values(), key=sort_key)
    return [
        {
            **item,
            "quantity": round(_coerce_float(item.get("quantity")), 6),
            "credits": round(_coerce_float(item.get("credits")), 6),
        }
        for item in items
        if _coerce_float(item.get("quantity")) > 0
    ]


def _coerce_float(value: object) -> float:
    try:
        return float(cast(Any, value) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _event_payload(event: object) -> dict[str, object]:
    payload = getattr(event, "payload_json", None)
    return payload if isinstance(payload, dict) else {}


def _payload_token(payload: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = str(payload.get(key) or "").strip().lower()
        if value:
            return value
    return ""


def _ceil_positive(value: float) -> int:
    if value <= 0:
        return 0
    return int(ceil(value))
