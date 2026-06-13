from __future__ import annotations

from collections.abc import Iterable

AI_CREDIT_RATE_VERSION = "ai-credit-ledger-v1"

AI_CREDIT_BREAKDOWN_ORDER = (
    "runs",
    "tokens_total",
    "web_search",
    "image_recommendation",
    "provider_calls_other",
    "vector_documents",
    "vector_chunks",
)

AI_CREDIT_COMPONENT_LABELS = {
    "runs": "Hosted runs",
    "tokens_total": "Model tokens",
    "web_search": "Search calls",
    "image_recommendation": "Image recommendation calls",
    "provider_calls_other": "Other provider calls",
    "vector_documents": "Vector indexed articles",
    "vector_chunks": "Vector indexed chunks",
}


def classify_provider_credit_component(
    *,
    execution_kind: str | None,
    ability_family: str | None,
) -> dict[str, object]:
    normalized_execution_kind = str(execution_kind or "").strip().lower()
    normalized_ability_family = str(ability_family or "").strip().lower()
    if "search" in normalized_execution_kind:
        return {
            "source_type": "web_search",
            "rate": 5.0,
            "unit": "call",
            "rate_unit": None,
        }
    if "image" in normalized_execution_kind or normalized_ability_family == "vision":
        return {
            "source_type": "image_recommendation",
            "rate": 3.0,
            "unit": "call",
            "rate_unit": None,
        }
    return {
        "source_type": "provider_calls_other",
        "rate": 0.0,
        "unit": "call",
        "rate_unit": None,
    }


def usage_meter_credit_component(event: object) -> dict[str, object] | None:
    meter_key = str(getattr(event, "meter_key", "") or "").strip()
    quantity = _coerce_float(getattr(event, "quantity", 0.0))
    if meter_key == "runs":
        return {
            "source_type": "runs",
            "quantity": quantity,
            "unit": "run",
            "rate": 1.0,
            "rate_unit": None,
            "credits": quantity,
        }
    if meter_key == "tokens_total":
        return {
            "source_type": "tokens_total",
            "quantity": quantity,
            "unit": "token",
            "rate": 1.0,
            "rate_unit": "1000_tokens",
            "credits": quantity / 1000.0,
        }
    if meter_key == "provider_calls":
        component = classify_provider_credit_component(
            execution_kind=str(getattr(event, "execution_kind", "") or ""),
            ability_family=str(getattr(event, "ability_family", "") or ""),
        )
        return {
            **component,
            "quantity": quantity,
            "credits": quantity * _coerce_float(component.get("rate")),
        }
    return None


def vector_credit_component(
    *,
    source_type: str,
    quantity: int | float,
) -> dict[str, object] | None:
    quantity_value = _coerce_float(quantity)
    if quantity_value <= 0:
        return None
    if source_type == "vector_documents":
        return {
            "source_type": "vector_documents",
            "quantity": quantity_value,
            "unit": "document",
            "rate": 2.0,
            "rate_unit": None,
            "credits": quantity_value * 2.0,
        }
    if source_type == "vector_chunks":
        return {
            "source_type": "vector_chunks",
            "quantity": quantity_value,
            "unit": "chunk",
            "rate": 0.1,
            "rate_unit": None,
            "credits": quantity_value * 0.1,
        }
    return None


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
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
