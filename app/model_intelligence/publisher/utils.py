from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any


def now_iso(now: datetime | None = None) -> str:
    value = now or datetime.now(UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def ensure_dir(path: str | Path) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    ensure_dir(target.parent)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_text(path: str | Path, value: str) -> None:
    target = Path(path)
    ensure_dir(target.parent)
    target.write_text(value, encoding="utf-8")


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_checksum(payload: Any) -> str:
    return sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def normalize_supports(values: list[Any]) -> list[str]:
    mapping = {
        "text": "text",
        "chat": "text",
        "vision": "vision",
        "image": "vision",
        "image_input": "vision",
        "image_generation": "image_generation",
        "embedding": "embedding",
        "embeddings": "embedding",
        "tools": "tools",
        "tool_use": "tools",
        "structured": "structured",
        "structured_output": "structured",
        "json": "structured",
    }
    return unique_strings(
        [mapping.get(str(raw or "").strip().lower(), str(raw or "").strip().lower()) for raw in values]
    )


def build_safe_aliases(*groups: Any) -> list[str]:
    aliases: list[str] = []
    for raw in groups:
        values = raw if isinstance(raw, list) else [raw]
        for value in values:
            normalized = str(value or "").strip()
            if not normalized:
                continue
            no_tag = _strip_trailing_tag(normalized)
            short = _last_path_segment(no_tag)
            aliases.extend([normalized, no_tag, short])
            size_alias = _build_size_colon_alias(no_tag)
            if size_alias:
                aliases.append(size_alias)
            short_alias = _build_size_colon_alias(short)
            if short_alias:
                aliases.append(short_alias)
    return unique_strings(aliases)


def merge_models(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    if existing is None:
        derived_aliases = build_safe_aliases(
            incoming.get("model_id"),
            incoming.get("display_name"),
            incoming.get("aliases") or [],
        )
        return {
            **incoming,
            "aliases": unique_strings([*(incoming.get("aliases") or []), *derived_aliases]),
            "supports": normalize_supports(incoming.get("supports") or []),
            "source_ids": unique_strings(incoming.get("source_ids") or [incoming.get("provider")]),
        }

    existing_supports = normalize_supports(existing.get("supports") or [])
    incoming_supports = normalize_supports(incoming.get("supports") or [])
    existing_aliases = unique_strings(
        [
            *(existing.get("aliases") or []),
            *build_safe_aliases(
                existing.get("model_id"),
                existing.get("display_name"),
                existing.get("aliases") or [],
            ),
        ]
    )
    incoming_aliases = unique_strings(
        [
            *(incoming.get("aliases") or []),
            *build_safe_aliases(
                incoming.get("model_id"),
                incoming.get("display_name"),
                incoming.get("aliases") or [],
            ),
        ]
    )
    existing_sources = unique_strings(existing.get("source_ids") or [existing.get("provider")])
    incoming_sources = unique_strings(incoming.get("source_ids") or [incoming.get("provider")])

    def choose(current: Any, new_value: Any) -> Any:
        return current if str(current or "").strip() else new_value

    def choose_price_kind() -> str:
        current = str(existing.get("price_reference_kind") or "").strip()
        new_value = str(incoming.get("price_reference_kind") or "").strip()
        if current == "exact" or new_value == "exact":
            return "exact"
        if current == "estimated" or new_value == "estimated":
            return "estimated"
        return current or new_value or "unavailable"

    return {
        **existing,
        "display_name": choose(existing.get("display_name"), incoming.get("display_name")),
        "model_type": choose(existing.get("model_type"), incoming.get("model_type")),
        "preview_type": choose(existing.get("preview_type"), incoming.get("preview_type")),
        "supports": normalize_supports([*existing_supports, *incoming_supports]),
        "aliases": unique_strings([*existing_aliases, *incoming_aliases]),
        "source_ids": unique_strings([*existing_sources, *incoming_sources]),
        "capability_profile": choose(existing.get("capability_profile"), incoming.get("capability_profile")),
        "price_reference_kind": choose_price_kind(),
        "price_input": existing.get("price_input")
        if existing.get("price_reference_kind") == "exact" and existing.get("price_input") is not None
        else incoming.get("price_input", existing.get("price_input")),
        "price_output": existing.get("price_output")
        if existing.get("price_reference_kind") == "exact" and existing.get("price_output") is not None
        else incoming.get("price_output", existing.get("price_output")),
        "price_tier": choose(existing.get("price_tier"), incoming.get("price_tier")),
        "price_summary": choose(existing.get("price_summary"), incoming.get("price_summary")),
        "short_description": choose(existing.get("short_description"), incoming.get("short_description")),
        "best_for": choose(existing.get("best_for"), incoming.get("best_for")),
        "why_recommended": choose(existing.get("why_recommended"), incoming.get("why_recommended")),
        "updated_at": choose(existing.get("updated_at"), incoming.get("updated_at")),
        "source_url": choose(existing.get("source_url"), incoming.get("source_url")),
        "metadata": {
            **(existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {}),
            **(incoming.get("metadata") if isinstance(incoming.get("metadata"), dict) else {}),
        },
    }


def html_decode(value: Any) -> str:
    return unescape(str(value or ""))


def infer_price_tier(price_input: float | None, price_output: float | None) -> str:
    finite_values = [
        float(value)
        for value in (price_input, price_output)
        if isinstance(value, (int, float))
    ]
    max_price = max(finite_values, default=0.0)
    if max_price <= 0:
        return "low"
    if max_price < 0.5:
        return "low"
    if max_price < 2.5:
        return "medium"
    return "high"


def build_price_summary(
    *,
    kind: str,
    price_input: float | None,
    price_output: float | None,
    tier: str,
) -> str:
    if kind == "unavailable":
        return "暂无参考价"
    if kind == "estimated":
        tier_label = {
            "low": "低价",
            "medium": "中价",
            "high": "高价",
            "unknown": "未知价位",
        }.get(tier, "未知价位")
        return f"近似参考价，当前为{tier_label}"
    return f"输入 {format_usd(price_input)} / 输出 {format_usd(price_output)}（每 1M tokens）"


def format_usd(amount: float | None) -> str:
    if amount is None:
        return "N/A"
    if amount == 0:
        return "$0.0000"
    return f"${amount:.3f}" if amount >= 1 else f"${amount:.4f}"


def validate_bundle_shape(bundle: dict[str, Any]) -> None:
    if not isinstance(bundle, dict):
        raise ValueError("bundle must be an object")
    for key in ("bundle_kind", "schema_version", "generated_at", "checksum"):
        if not str(bundle.get(key) or "").strip():
            raise ValueError(f"bundle missing {key}")
    if not isinstance(bundle.get("sources"), list):
        raise ValueError("bundle.sources must be an array")
    if not isinstance(bundle.get("models"), list):
        raise ValueError("bundle.models must be an array")


def _strip_trailing_tag(value: str) -> str:
    return value.strip().removesuffix(":latest")


def _last_path_segment(value: str) -> str:
    return value.split("/")[-1] if "/" in value else value


def _build_size_colon_alias(value: str) -> str:
    import re

    match = re.match(r"^(.*?)-(\d+(?:\.\d+)?b)(-[a-z0-9._-]+)?$", value.strip(), re.I)
    if not match:
        return ""
    prefix = str(match.group(1) or "").strip()
    size = str(match.group(2) or "").strip().lower()
    suffix = str(match.group(3) or "").strip()
    if not prefix or not size:
        return ""
    return f"{prefix}:{size}{suffix}"
