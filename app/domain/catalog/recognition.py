from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

RECOGNITION_BUNDLE_SCHEMA_VERSION = "recognition_bundle_v1"
RECOGNITION_MANUAL_VERSION = "recognition_manual_v1"
RECOGNITION_UPSTREAM_EVIDENCE_VERSION = "recognition_upstream_v1"
RECOGNITION_HF_ALIAS_BRIDGE_VERSION = "recognition_hf_alias_bridge_v1"
RECOGNITION_SOURCE_DEFAULTS = {
    "litellm_revision": "unconfigured",
    "openrouter_snapshot": "unconfigured",
    "siliconflow_snapshot": "unconfigured",
    "hf_snapshot": "unconfigured",
    "ollama_snapshot": "unconfigured",
}
DATA_ROOT = Path(__file__).resolve().parent / "data"
HF_ALIAS_BRIDGE_CONFIDENCE_PENALTIES: dict[str, float] = {
    "exact_repo": 0.0,
    "family_match": 0.03,
    "name_match": 0.06,
}

FEATURE_DEFAULTS: dict[str, dict[str, Any]] = {
    "text": {
        "model_type": "chat",
        "preview_type": "text",
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "capabilities": {
            "text_input": True,
            "image_input": False,
            "image_output": False,
            "vision": False,
            "tools": True,
            "structured_output": True,
        },
        "confidence": 0.88,
        "evidence_source": "feature_mapping",
    },
    "vision": {
        "model_type": "vision",
        "preview_type": "text",
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "capabilities": {
            "text_input": True,
            "image_input": True,
            "image_output": False,
            "vision": True,
            "tools": True,
            "structured_output": True,
        },
        "confidence": 0.9,
        "evidence_source": "feature_mapping",
    },
    "embedding": {
        "model_type": "embedding",
        "preview_type": "embedding",
        "input_modalities": ["text"],
        "output_modalities": ["embedding"],
        "capabilities": {
            "text_input": True,
            "image_input": False,
            "image_output": False,
            "vision": False,
            "tools": False,
            "structured_output": False,
        },
        "confidence": 0.9,
        "evidence_source": "feature_mapping",
    },
    "image": {
        "model_type": "image_generation",
        "preview_type": "image",
        "input_modalities": ["text", "image"],
        "output_modalities": ["image"],
        "capabilities": {
            "text_input": True,
            "image_input": True,
            "image_output": True,
            "vision": False,
            "tools": False,
            "structured_output": False,
        },
        "confidence": 0.9,
        "evidence_source": "feature_mapping",
    },
}

FAMILY_HINTS: tuple[dict[str, Any], ...] = (
    {
        "id": "family_hint_flux",
        "pattern": re.compile(r"(^|[\s:/_-])(flux|sdxl|stable-diffusion)([\s:/_-]|$)", re.I),
        "model_type": "image_generation",
        "preview_type": "image",
        "input_modalities": ["text", "image"],
        "output_modalities": ["image"],
        "capabilities": {
            "text_input": True,
            "image_input": True,
            "image_output": True,
            "vision": False,
            "tools": False,
            "structured_output": False,
        },
        "confidence": 0.82,
    },
    {
        "id": "family_hint_llava",
        "pattern": re.compile(r"(^|[\s:/_-])(llava|vision|vl)([\s:/_-]|$)", re.I),
        "model_type": "vision",
        "preview_type": "text",
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "capabilities": {
            "text_input": True,
            "image_input": True,
            "image_output": False,
            "vision": True,
            "tools": False,
            "structured_output": False,
        },
        "confidence": 0.78,
    },
    {
        "id": "family_hint_bge",
        "pattern": re.compile(r"(^|[\s:/_-])(bge|e5|gte|embed|embedding)([\s:/_-]|$)", re.I),
        "model_type": "embedding",
        "preview_type": "embedding",
        "input_modalities": ["text"],
        "output_modalities": ["embedding"],
        "capabilities": {
            "text_input": True,
            "image_input": False,
            "image_output": False,
            "vision": False,
            "tools": False,
            "structured_output": False,
        },
        "confidence": 0.8,
    },
)

def build_recognition_bundle(
    *,
    models: list[Any],
    catalog_revision: str,
    published_at: str,
    evidence_snapshot_path: str | Path | None = None,
) -> dict[str, Any]:
    upstream_payload = load_active_upstream_evidence_payload(evidence_snapshot_path)
    bundle_models = [
        serialize_recognition_model(model, upstream_payload=upstream_payload)
        for model in models
    ]
    bundle_rules = [
        {
            **rule,
            "updated_at": published_at,
        }
        for rule in _recognition_pattern_rules()
    ]
    revision = (
        f"recognition-{catalog_revision}"
        if catalog_revision != "bootstrap"
        else "recognition-bootstrap"
    )
    checksum = hashlib.sha256(
        json.dumps(
            {
                "revision": revision,
                "schema_version": RECOGNITION_BUNDLE_SCHEMA_VERSION,
                "published_at": published_at,
                "models": bundle_models,
                "pattern_rules": bundle_rules,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    return {
        "revision": revision,
        "schema_version": RECOGNITION_BUNDLE_SCHEMA_VERSION,
        "published_at": published_at,
        "checksum": checksum,
        "sources": {
            "catalog_revision": catalog_revision,
            "recognition_derivation": "catalog_service_v2",
            "manual_curation_version": RECOGNITION_MANUAL_VERSION,
            "hf_alias_bridge_version": _huggingface_alias_bridge_version(),
            "upstream_evidence_version": str(
                upstream_payload.get("version") or RECOGNITION_UPSTREAM_EVIDENCE_VERSION
            ),
            **_upstream_evidence_bundle_sources(upstream_payload),
        },
        "models": bundle_models,
        "pattern_rules": bundle_rules,
    }


def build_recognition_bundle_from_upstream_snapshot(
    *,
    snapshot_payload: Mapping[str, Any],
    catalog_revision: str,
    published_at: str,
    source_label: str = "cloud_intelligence",
) -> dict[str, Any]:
    raw_records = dict(snapshot_payload.get("records", {}))
    bundle_models = [
        serialize_snapshot_recognition_record(
            provider_id=provider_id,
            model_id=model_id,
            record=record,
            published_at=published_at,
            source_label=source_label,
        )
        for provider_id, model_id, record in _iterate_snapshot_record_items(raw_records)
    ]
    bundle_rules = [
        {
            **rule,
            "updated_at": published_at,
        }
        for rule in _recognition_pattern_rules()
    ]
    revision = (
        f"recognition-{catalog_revision}"
        if catalog_revision != "bootstrap"
        else "recognition-bootstrap"
    )
    checksum = hashlib.sha256(
        json.dumps(
            {
                "revision": revision,
                "schema_version": RECOGNITION_BUNDLE_SCHEMA_VERSION,
                "published_at": published_at,
                "models": bundle_models,
                "pattern_rules": bundle_rules,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    return {
        "revision": revision,
        "schema_version": RECOGNITION_BUNDLE_SCHEMA_VERSION,
        "published_at": published_at,
        "checksum": checksum,
        "sources": {
            "catalog_revision": catalog_revision,
            "recognition_derivation": "upstream_snapshot_v1",
            "manual_curation_version": RECOGNITION_MANUAL_VERSION,
            "hf_alias_bridge_version": _huggingface_alias_bridge_version(),
            "upstream_evidence_version": str(
                snapshot_payload.get("version") or RECOGNITION_UPSTREAM_EVIDENCE_VERSION
            ),
            **_upstream_evidence_bundle_sources(snapshot_payload),
        },
        "source_runs": list(snapshot_payload.get("source_runs") or []),
        "source_run_ids": list(snapshot_payload.get("source_run_ids") or []),
        "source_failures": list(snapshot_payload.get("source_failures") or []),
        "models": bundle_models,
        "pattern_rules": bundle_rules,
    }


def serialize_recognition_model(
    model: Any,
    *,
    upstream_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    provider_id = str(model.provider_id)
    model_id = str(model.model_id)
    family = str(getattr(model, "family", "") or "")
    raw_json = model.raw_json if isinstance(model.raw_json, Mapping) else {}
    record, evidence = _base_record_from_feature(model.feature)
    record = {
        **record,
        "provider": provider_id,
        "model_id": model_id,
        "aliases": _default_aliases(provider_id, model_id),
        "match_keys": _default_match_keys(provider_id, model_id),
        "source": "cloud_published",
        "updated_at": _serialize_timestamp(getattr(model, "updated_at", None)),
        "deprecated": bool(model.is_deprecated),
    }

    raw_hints = _derive_raw_json_hints(raw_json)
    if raw_hints:
        record = _merge_record(record, raw_hints)
        evidence.append(
            {
                "source": "provider_raw_json",
                "confidence": float(raw_hints.get("confidence", 0.7)),
            }
        )

    family_hint = _derive_family_hint(model_id, family)
    if family_hint:
        record = _merge_record(record, family_hint)
        evidence.append(
            {
                "source": "family_hint",
                "confidence": float(family_hint.get("confidence", 0.8)),
            }
        )

    upstream, upstream_evidence_source = _resolve_upstream_record(
        provider_id,
        model_id,
        upstream_payload,
    )
    if upstream:
        record = _merge_record(record, upstream)
        evidence.append(
            {
                "source": upstream_evidence_source,
                "confidence": float(upstream.get("confidence", 0.85)),
            }
        )

    manual = _manual_recognition_overrides().get(f"{provider_id}::{model_id}")
    if manual:
        record = _merge_record(record, manual)
        evidence.append(
            {
                "source": "manual_curation",
                "confidence": float(manual.get("confidence", 0.99)),
            }
        )

    record["evidence"] = evidence
    record["confidence"] = max(
        0.0,
        min(
            1.0,
            float(
                manual.get("confidence", record.get("confidence", 0.0))
                if manual
                else record.get("confidence", 0.0)
            ),
        ),
    )
    record["price_input"] = _normalize_optional_price(record.get("price_input"))
    record["price_output"] = _normalize_optional_price(record.get("price_output"))
    record["source_details"] = _normalize_source_details(record.get("source_details"))
    record["source_coverage_sources"] = sorted(
        [
            str(source_key).strip()
            for source_key in dict(record.get("source_details", {})).keys()
            if str(source_key).strip()
        ]
    )
    record["source_coverage_count"] = len(record["source_coverage_sources"])
    pricing_meta = _build_pricing_meta(record.get("source_details"))
    capability_meta = _build_capability_meta(record.get("source_details"))
    record.update(pricing_meta)
    record.update(capability_meta)
    record.update(_build_user_facing_description_fields(record))
    return record


def serialize_snapshot_recognition_record(
    *,
    provider_id: str,
    model_id: str,
    record: Mapping[str, Any],
    published_at: str,
    source_label: str = "cloud_intelligence",
) -> dict[str, Any]:
    normalized_record = {
        "provider": str(provider_id).strip(),
        "model_id": str(model_id).strip(),
        "aliases": _default_aliases(provider_id, model_id),
        "match_keys": _default_match_keys(provider_id, model_id),
        "source": str(source_label).strip() or "cloud_intelligence",
        "updated_at": published_at,
        "deprecated": bool(record.get("deprecated", False)),
    }
    feature, evidence = _base_record_from_feature(
        _feature_from_snapshot_record(record)
    )
    normalized_record = _merge_record(normalized_record, feature)
    normalized_record = _merge_record(normalized_record, dict(record))
    normalized_record["evidence"] = evidence + [
        {
            "source": str(record.get("evidence_source") or "upstream_snapshot"),
            "confidence": float(record.get("confidence", 0.85) or 0.85),
        }
    ]
    normalized_record["confidence"] = max(
        0.0,
        min(1.0, float(normalized_record.get("confidence", 0.0) or 0.0)),
    )
    normalized_record["price_input"] = _normalize_optional_price(
        normalized_record.get("price_input")
    )
    normalized_record["price_output"] = _normalize_optional_price(
        normalized_record.get("price_output")
    )
    normalized_record["source_details"] = _normalize_source_details(
        normalized_record.get("source_details")
    )
    normalized_record["source_coverage_sources"] = sorted(
        [
            str(source_key).strip()
            for source_key in dict(normalized_record.get("source_details", {})).keys()
            if str(source_key).strip()
        ]
    )
    normalized_record["source_coverage_count"] = len(
        normalized_record["source_coverage_sources"]
    )
    normalized_record.update(_build_pricing_meta(normalized_record.get("source_details")))
    normalized_record.update(
        _build_capability_meta(normalized_record.get("source_details"))
    )
    normalized_record.update(_build_user_facing_description_fields(normalized_record))
    return normalized_record


def _base_record_from_feature(feature: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    key = str(feature)
    defaults = FEATURE_DEFAULTS.get(key, FEATURE_DEFAULTS["text"])
    record = {
        "model_type": defaults["model_type"],
        "preview_type": defaults["preview_type"],
        "input_modalities": list(defaults["input_modalities"]),
        "output_modalities": list(defaults["output_modalities"]),
        "capabilities": dict(defaults["capabilities"]),
        "confidence": float(defaults["confidence"]),
    }
    evidence = [
        {
            "source": "provider_catalog",
            "confidence": 0.91,
        },
        {
            "source": str(defaults["evidence_source"]),
            "confidence": float(defaults["confidence"]),
        },
    ]
    return record, evidence


def _feature_from_snapshot_record(record: Mapping[str, Any]) -> str:
    model_type = str(record.get("model_type") or "").strip().lower()
    if model_type == "vision":
        return "vision"
    if model_type == "embedding":
        return "embedding"
    if model_type == "image_generation":
        return "image"
    return "text"


def _iterate_snapshot_record_items(
    raw_records: Mapping[str, Any],
) -> list[tuple[str, str, Mapping[str, Any]]]:
    items: list[tuple[str, str, Mapping[str, Any]]] = []
    for key, value in raw_records.items():
        if not isinstance(key, str) or not isinstance(value, Mapping):
            continue
        provider_id = ""
        model_id = ""
        if "::" in key:
            provider_id, model_id = key.split("::", 1)
        else:
            provider_id = str(value.get("provider") or "").strip()
            model_id = str(value.get("model_id") or "").strip()
        provider_id = str(provider_id).strip()
        model_id = str(model_id).strip()
        if not provider_id or not model_id:
            continue
        items.append((provider_id, model_id, value))
    items.sort(key=lambda item: (item[0], item[1]))
    return items


def _derive_raw_json_hints(raw_json: Mapping[str, Any]) -> dict[str, Any]:
    if not raw_json:
        return {}

    merged = json.dumps(raw_json, sort_keys=True).lower()
    capabilities = dict(_default_capabilities())
    hints: dict[str, Any] = {}

    if "pipeline_tag" in raw_json:
        pipeline_tag = str(raw_json.get("pipeline_tag") or "").lower()
        if pipeline_tag in {"image-text-to-text", "visual-question-answering"}:
            hints["model_type"] = "vision"
            hints["preview_type"] = "text"
            hints["input_modalities"] = ["text", "image"]
            hints["output_modalities"] = ["text"]
            capabilities.update({"text_input": True, "image_input": True, "vision": True})
        elif pipeline_tag in {"text-embedding", "sentence-similarity"}:
            hints["model_type"] = "embedding"
            hints["preview_type"] = "embedding"
            hints["input_modalities"] = ["text"]
            hints["output_modalities"] = ["embedding"]
            capabilities.update({"text_input": True})
        elif pipeline_tag in {"text-to-image", "image-to-image"}:
            hints["model_type"] = "image_generation"
            hints["preview_type"] = "image"
            hints["input_modalities"] = ["text", "image"]
            hints["output_modalities"] = ["image"]
            capabilities.update(
                {"text_input": True, "image_input": "image-to-image" == pipeline_tag, "image_output": True}
            )

    if "vision" in merged or "image_input" in merged:
        capabilities["vision"] = True
        capabilities["image_input"] = True
        hints.setdefault("model_type", "vision")
        hints.setdefault("preview_type", "text")
        hints.setdefault("input_modalities", ["text", "image"])
        hints.setdefault("output_modalities", ["text"])
    if "tool" in merged or "function_call" in merged:
        capabilities["tools"] = True
    if "json" in merged or "structured" in merged or "schema" in merged:
        capabilities["structured_output"] = True

    if not hints and capabilities == _default_capabilities():
        return {}

    hints["capabilities"] = capabilities
    hints["confidence"] = 0.74
    return hints


def _derive_family_hint(model_id: str, family: str) -> dict[str, Any]:
    haystack = f"{model_id} {family}".strip()
    for hint in FAMILY_HINTS:
        if hint["pattern"].search(haystack):
            return {
                "model_type": hint["model_type"],
                "preview_type": hint["preview_type"],
                "input_modalities": list(hint["input_modalities"]),
                "output_modalities": list(hint["output_modalities"]),
                "capabilities": dict(hint["capabilities"]),
                "confidence": float(hint["confidence"]),
            }
    return {}


def _merge_record(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key in ("model_type", "preview_type", "provider", "model_id", "source", "updated_at"):
        if key in override and override[key]:
            merged[key] = override[key]

    for key in ("input_modalities", "output_modalities", "aliases", "match_keys"):
        if key in override and override[key]:
            merged[key] = _unique_strings(list(override[key]))

    if "capabilities" in override and isinstance(override["capabilities"], Mapping):
        capabilities = dict(merged.get("capabilities", _default_capabilities()))
        capabilities.update(
            {
                capability_key: bool(capability_value)
                for capability_key, capability_value in dict(override["capabilities"]).items()
            }
        )
        merged["capabilities"] = capabilities

    if "confidence" in override:
        merged["confidence"] = float(override["confidence"])
    if "deprecated" in override:
        merged["deprecated"] = bool(override["deprecated"])
    for key in ("price_input", "price_output"):
        normalized_price = _normalize_optional_price(override.get(key))
        if normalized_price is not None:
            merged[key] = normalized_price
    merged["source_details"] = _merge_source_details(
        merged.get("source_details"),
        override.get("source_details"),
    )
    return merged


def _default_aliases(provider_id: str, model_id: str) -> list[str]:
    return _unique_strings([model_id, f"{provider_id}/{model_id}"])


def _default_match_keys(provider_id: str, model_id: str) -> list[str]:
    return _unique_strings(
        [model_id, f"{provider_id}/{model_id}", f"{provider_id}:{model_id}", model_id.lower()]
    )


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _default_capabilities() -> dict[str, bool]:
    return {
        "text_input": False,
        "image_input": False,
        "image_output": False,
        "vision": False,
        "tools": False,
        "structured_output": False,
    }


def _resolve_upstream_record(
    provider_id: str,
    model_id: str,
    upstream_payload: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    upstream_records = _upstream_evidence_records(upstream_payload)
    direct_key = f"{provider_id}::{model_id}"
    direct = upstream_records.get(direct_key)
    if direct:
        return direct, str(direct.get("evidence_source", "upstream_evidence"))

    bridge = _huggingface_alias_bridge().get(direct_key, {})
    bridge_repo_id = str(bridge.get("repo_id") or "").strip()
    if not bridge_repo_id:
        return None, ""

    bridged = upstream_records.get(f"huggingface::{bridge_repo_id}")
    if not bridged:
        return None, ""
    bridge_quality = _normalize_hf_alias_bridge_quality(bridge.get("quality"))

    allowed_keys = {
        "model_type",
        "preview_type",
        "input_modalities",
        "output_modalities",
        "capabilities",
        "confidence",
        "deprecated",
        "price_input",
        "price_output",
    }
    bridged_confidence = float(bridged.get("confidence", 0.0) or 0.0)
    penalty = HF_ALIAS_BRIDGE_CONFIDENCE_PENALTIES.get(bridge_quality, 0.06)
    bridged_record = {key: value for key, value in bridged.items() if key in allowed_keys}
    bridged_record["confidence"] = max(0.0, min(1.0, bridged_confidence - penalty))
    bridged_record["source_details"] = _normalize_source_details(bridged.get("source_details"))
    return (
        bridged_record,
        f"huggingface_alias_bridge_{bridge_quality}",
    )


def _serialize_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@lru_cache(maxsize=1)
def _manual_recognition_overrides() -> dict[str, dict[str, Any]]:
    payload = _load_json_asset("recognition-manual-overrides.json")
    return {
        str(key): dict(value)
        for key, value in payload.items()
        if isinstance(key, str) and isinstance(value, Mapping)
    }


@lru_cache(maxsize=1)
def _recognition_pattern_rules() -> tuple[dict[str, Any], ...]:
    payload = _load_json_asset("recognition-pattern-rules.json")
    rules: list[dict[str, Any]] = []
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, Mapping):
                rules.append(dict(item))
    return tuple(rules)


def load_active_upstream_evidence_payload(
    snapshot_path: str | Path | None = None,
) -> dict[str, Any]:
    if snapshot_path:
        path = Path(snapshot_path)
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, Mapping):
                return normalize_upstream_evidence_payload(payload)
    return _bundled_upstream_evidence_payload()


def inspect_upstream_evidence_snapshot(
    snapshot_path: str | Path | None,
) -> dict[str, Any]:
    configured_path = str(snapshot_path or "").strip()
    if not configured_path:
        return {
            "configured": False,
            "snapshot_exists": False,
            "snapshot_path": "",
            "version": "",
            "generated_at": "",
            "records_total": 0,
            "source_keys": [],
            "sources": {},
            "source_runs": [],
            "source_run_ids": [],
            "source_failures": [],
            "sample_record_keys": [],
        }

    path = Path(configured_path)
    if not path.exists():
        return {
            "configured": True,
            "snapshot_exists": False,
            "snapshot_path": str(path),
            "version": "",
            "generated_at": "",
            "records_total": 0,
            "source_keys": [],
            "sources": {},
            "source_runs": [],
            "source_run_ids": [],
            "source_failures": [],
            "sample_record_keys": [],
        }

    payload = json.loads(path.read_text(encoding="utf-8"))
    normalized = normalize_upstream_evidence_payload(payload if isinstance(payload, Mapping) else {})
    records = normalized.get("records", {})
    record_keys = sorted(records.keys()) if isinstance(records, Mapping) else []
    sources = normalized.get("sources", {})
    source_keys = sorted(sources.keys()) if isinstance(sources, Mapping) else []
    return {
        "configured": True,
        "snapshot_exists": True,
        "snapshot_path": str(path),
        "version": str(normalized.get("version") or ""),
        "generated_at": str(normalized.get("generated_at") or ""),
        "records_total": len(record_keys),
        "source_keys": source_keys,
        "sources": dict(sources) if isinstance(sources, Mapping) else {},
        "source_runs": list(normalized.get("source_runs") or []),
        "source_run_ids": list(normalized.get("source_run_ids") or []),
        "source_failures": list(normalized.get("source_failures") or []),
        "sample_record_keys": record_keys[:10],
    }


def normalize_upstream_evidence_payload(
    payload: Mapping[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    normalized_sources = {
        str(key): str(value)
        for key, value in dict(payload.get("sources", {})).items()
        if str(key).strip() and str(value).strip()
    } if isinstance(payload.get("sources", {}), Mapping) else {}
    for key, value in RECOGNITION_SOURCE_DEFAULTS.items():
        normalized_sources.setdefault(key, value)
    normalized_records: dict[str, dict[str, Any]] = {}
    raw_records = payload.get("records", {})
    if isinstance(raw_records, Mapping):
        for key, value in raw_records.items():
            if not isinstance(key, str) or not isinstance(value, Mapping):
                continue
            normalized_record: dict[str, Any] = {}
            for field in ("model_type", "preview_type", "evidence_source", "provider", "model_id"):
                if field in value and str(value[field]).strip():
                    normalized_record[field] = str(value[field]).strip()
            for field in ("input_modalities", "output_modalities", "aliases", "match_keys"):
                field_value = value.get(field)
                if isinstance(field_value, list):
                    normalized_record[field] = _unique_strings(list(field_value))
            capabilities = value.get("capabilities")
            if isinstance(capabilities, Mapping):
                normalized_record["capabilities"] = {
                    str(capability_key): bool(capability_value)
                    for capability_key, capability_value in capabilities.items()
                    if str(capability_key).strip()
                }
            if "confidence" in value:
                normalized_record["confidence"] = float(value["confidence"])
            if "deprecated" in value:
                normalized_record["deprecated"] = bool(value["deprecated"])
            for field in ("price_input", "price_output"):
                normalized_price = _normalize_optional_price(value.get(field))
                if normalized_price is not None:
                    normalized_record[field] = normalized_price
            source_details = _normalize_source_details(value.get("source_details"))
            if not source_details:
                derived_source_key = str(value.get("evidence_source") or "").strip()
                if derived_source_key:
                    derived_payload = {
                        "provider": normalized_record.get("provider"),
                        "model_id": normalized_record.get("model_id"),
                        "model_type": normalized_record.get("model_type"),
                        "preview_type": normalized_record.get("preview_type"),
                        "capabilities": normalized_record.get("capabilities"),
                        "confidence": normalized_record.get("confidence"),
                        "deprecated": normalized_record.get("deprecated"),
                        "price_input": normalized_record.get("price_input"),
                        "price_output": normalized_record.get("price_output"),
                        "price_source": derived_source_key,
                    }
                    source_details = {
                        derived_source_key: {
                            key: value
                            for key, value in derived_payload.items()
                            if value not in (None, "", [], {})
                        }
                    }
            if source_details:
                normalized_record["source_details"] = source_details
            normalized_records[key] = normalized_record
    normalized_source_runs = _normalize_source_runs(payload.get("source_runs"))
    normalized_source_failures = _normalize_source_failures(payload.get("source_failures"))
    normalized_source_run_ids = _normalize_source_run_ids(
        payload.get("source_run_ids"),
        source_runs=normalized_source_runs,
    )
    return {
        "version": str(payload.get("version") or RECOGNITION_UPSTREAM_EVIDENCE_VERSION),
        "generated_at": generated_at
        or str(payload.get("generated_at") or _serialize_timestamp(datetime.now(UTC))),
        "sources": normalized_sources,
        "source_runs": normalized_source_runs,
        "source_run_ids": normalized_source_run_ids,
        "source_failures": normalized_source_failures,
        "records": normalized_records,
    }


def merge_upstream_evidence_payloads(
    *payloads: Mapping[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    merged_sources: dict[str, str] = {}
    merged_records: dict[str, dict[str, Any]] = {}
    merged_source_runs: list[dict[str, Any]] = []
    merged_source_failures: list[dict[str, str]] = []
    version = RECOGNITION_UPSTREAM_EVIDENCE_VERSION

    for payload in payloads:
        normalized = normalize_upstream_evidence_payload(payload)
        version = str(normalized.get("version") or version)
        sources = normalized.get("sources", {})
        if isinstance(sources, Mapping):
            for key, value in sources.items():
                normalized_key = str(key).strip()
                normalized_value = str(value).strip()
                if normalized_key and normalized_value:
                    merged_sources[normalized_key] = normalized_value
        merged_source_runs.extend(_normalize_source_runs(normalized.get("source_runs")))
        merged_source_failures.extend(
            _normalize_source_failures(normalized.get("source_failures"))
        )
        raw_records = normalized.get("records", {})
        if not isinstance(raw_records, Mapping):
            continue
        for key, value in raw_records.items():
            if not isinstance(key, str) or not isinstance(value, Mapping):
                continue
            existing = merged_records.get(key)
            if existing is None:
                merged_records[key] = dict(value)
                continue
            merged_records[key] = _merge_upstream_record(existing, value)

    return {
        "version": version,
        "generated_at": generated_at or _serialize_timestamp(datetime.now(UTC)),
        "sources": merged_sources,
        "source_runs": merged_source_runs,
        "source_run_ids": _normalize_source_run_ids(
            None,
            source_runs=merged_source_runs,
        ),
        "source_failures": merged_source_failures,
        "records": merged_records,
    }


def _normalize_source_runs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        source_name = str(item.get("source") or item.get("source_name") or "").strip()
        if not source_name:
            continue
        run_id = str(item.get("run_id") or f"{source_name}:{item.get('generated_at') or ''}").strip(":")
        normalized_item: dict[str, Any] = {
            "source": source_name,
            "run_id": run_id or source_name,
            "status": str(item.get("status") or "unknown").strip() or "unknown",
        }
        generated_at = str(item.get("generated_at") or "").strip()
        if generated_at:
            normalized_item["generated_at"] = generated_at
        for key in ("records_fetched", "records_accepted", "duration_ms"):
            try:
                if item.get(key) is not None:
                    normalized_item[key] = max(0, int(item.get(key)))
            except (TypeError, ValueError):
                continue
        error_text = str(item.get("error") or "").strip()
        if error_text:
            normalized_item["error"] = error_text
        normalized.append(normalized_item)
    return normalized


def _normalize_source_failures(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        source_name = str(item.get("source") or "").strip()
        error_text = str(item.get("error") or "").strip()
        if not source_name or not error_text:
            continue
        normalized.append(
            {
                "source": source_name,
                "error": error_text,
            }
        )
    return normalized


def _normalize_source_run_ids(
    value: Any,
    *,
    source_runs: list[dict[str, Any]],
) -> list[str]:
    if isinstance(value, list):
        normalized_ids = _unique_strings(list(value))
        if normalized_ids:
            return normalized_ids
    return _unique_strings(
        [
            str(item.get("run_id") or "").strip()
            for item in source_runs
            if isinstance(item, Mapping)
        ]
    )


def write_upstream_evidence_snapshot(
    snapshot_path: str | Path,
    payload: Mapping[str, Any],
) -> Path:
    path = Path(snapshot_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _merge_upstream_record(
    base: Mapping[str, Any],
    overlay: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(base)
    for key in ("provider", "model_id", "model_type", "preview_type"):
        if not merged.get(key) and overlay.get(key):
            merged[key] = overlay[key]

    for key in ("input_modalities", "output_modalities", "aliases", "match_keys"):
        base_values = list(merged.get(key, [])) if isinstance(merged.get(key), list) else []
        overlay_values = list(overlay.get(key, [])) if isinstance(overlay.get(key), list) else []
        merged_values = _unique_strings(base_values + overlay_values)
        if merged_values:
            merged[key] = merged_values

    base_capabilities = (
        dict(merged.get("capabilities", {}))
        if isinstance(merged.get("capabilities"), Mapping)
        else {}
    )
    overlay_capabilities = (
        dict(overlay.get("capabilities", {}))
        if isinstance(overlay.get("capabilities"), Mapping)
        else {}
    )
    if overlay_capabilities:
        for capability_key, capability_value in overlay_capabilities.items():
            normalized_key = str(capability_key).strip()
            if not normalized_key:
                continue
            if normalized_key not in base_capabilities:
                base_capabilities[normalized_key] = bool(capability_value)
        merged["capabilities"] = base_capabilities

    base_confidence = float(merged.get("confidence", 0.0) or 0.0)
    overlay_confidence = float(overlay.get("confidence", 0.0) or 0.0)
    merged["confidence"] = max(base_confidence, overlay_confidence)

    if not merged.get("evidence_source") and overlay.get("evidence_source"):
        merged["evidence_source"] = overlay["evidence_source"]
    if "deprecated" in overlay and "deprecated" not in merged:
        merged["deprecated"] = bool(overlay["deprecated"])
    for key in ("price_input", "price_output"):
        if key in merged and _normalize_optional_price(merged.get(key)) is None:
            merged.pop(key, None)
        overlay_price = _normalize_optional_price(overlay.get(key))
        if overlay_price is not None and key not in merged:
            merged[key] = overlay_price
    merged["source_details"] = _merge_source_details(
        merged.get("source_details"),
        overlay.get("source_details"),
    )

    return merged


def _normalize_source_details(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for raw_source, raw_payload in value.items():
        source_key = str(raw_source or "").strip()
        if not source_key or not isinstance(raw_payload, Mapping):
            continue
        detail: dict[str, Any] = {}
        for field in ("provider", "model_id", "model_type", "preview_type", "price_source", "price_updated_at"):
            field_value = raw_payload.get(field)
            if str(field_value or "").strip():
                detail[field] = str(field_value).strip()
        if "capabilities" in raw_payload and isinstance(raw_payload.get("capabilities"), Mapping):
            detail["capabilities"] = {
                str(key): bool(val)
                for key, val in dict(raw_payload.get("capabilities", {})).items()
                if str(key).strip()
            }
        for field in ("confidence", "price_confidence"):
            if field in raw_payload:
                try:
                    detail[field] = float(raw_payload.get(field) or 0.0)
                except (TypeError, ValueError):
                    pass
        for field in ("deprecated",):
            if field in raw_payload:
                detail[field] = bool(raw_payload.get(field))
        for field in ("price_input", "price_output"):
            normalized_price = _normalize_optional_price(raw_payload.get(field))
            if normalized_price is not None:
                detail[field] = normalized_price
        if detail:
            normalized[source_key] = detail
    return normalized


def _merge_source_details(base: Any, overlay: Any) -> dict[str, dict[str, Any]]:
    merged = _normalize_source_details(base)
    overlay_normalized = _normalize_source_details(overlay)
    for source_key, source_payload in overlay_normalized.items():
        existing = merged.get(source_key, {})
        combined = dict(existing)
        for key, value in source_payload.items():
            if key == "capabilities" and isinstance(value, Mapping):
                capabilities = dict(combined.get("capabilities", {}))
                capabilities.update(
                    {
                        str(capability_key): bool(capability_value)
                        for capability_key, capability_value in dict(value).items()
                        if str(capability_key).strip()
                    }
                )
                combined["capabilities"] = capabilities
                continue
            combined[key] = value
        merged[source_key] = combined
    return merged


def _build_pricing_meta(source_details: Any) -> dict[str, Any]:
    details = _normalize_source_details(source_details)
    priced_sources = []
    unique_pairs: set[tuple[float | None, float | None]] = set()
    for source_key, payload in details.items():
        price_input = _normalize_optional_price(payload.get("price_input"))
        price_output = _normalize_optional_price(payload.get("price_output"))
        if price_input is None and price_output is None:
            continue
        unique_pairs.add((price_input, price_output))
        priced_sources.append(
            {
                "source": source_key,
                "price_input": price_input,
                "price_output": price_output,
                "price_source": str(payload.get("price_source") or source_key),
                "price_updated_at": str(payload.get("price_updated_at") or ""),
                "price_confidence": float(payload.get("price_confidence", payload.get("confidence", 0.0)) or 0.0),
            }
        )
    priced_sources.sort(key=lambda item: (item["price_confidence"], item["source"]), reverse=True)
    primary = priced_sources[0] if priced_sources else None
    return {
        "price_sources": priced_sources,
        "price_source": primary["price_source"] if primary else "",
        "price_updated_at": primary["price_updated_at"] if primary else "",
        "price_confidence": float(primary["price_confidence"]) if primary else 0.0,
        "has_price_conflict": len(unique_pairs) > 1,
    }


def _build_capability_meta(source_details: Any) -> dict[str, Any]:
    details = _normalize_source_details(source_details)
    capability_sources = []
    signatures: set[tuple[str, str, tuple[tuple[str, bool], ...]]] = set()
    for source_key, payload in details.items():
        capabilities = payload.get("capabilities") if isinstance(payload.get("capabilities"), Mapping) else {}
        normalized_capabilities = {
            str(key): bool(val)
            for key, val in dict(capabilities).items()
            if str(key).strip()
        }
        model_type = str(payload.get("model_type") or "").strip()
        preview_type = str(payload.get("preview_type") or "").strip()
        if not model_type and not preview_type and not normalized_capabilities:
            continue
        signatures.add(
            (
                model_type,
                preview_type,
                tuple(sorted(normalized_capabilities.items())),
            )
        )
        capability_sources.append(
            {
                "source": source_key,
                "model_type": model_type,
                "preview_type": preview_type,
                "capabilities": normalized_capabilities,
                "confidence": float(payload.get("confidence", 0.0) or 0.0),
            }
        )
    capability_sources.sort(key=lambda item: (item["confidence"], item["source"]), reverse=True)
    return {
        "capability_sources": capability_sources,
        "has_capability_conflict": len(signatures) > 1,
    }


def _build_user_facing_description_fields(record: Mapping[str, Any]) -> dict[str, Any]:
    model_type = str(record.get("model_type") or "").strip()
    preview_type = str(record.get("preview_type") or "").strip()
    capabilities = (
        dict(record.get("capabilities", {}))
        if isinstance(record.get("capabilities"), Mapping)
        else {}
    )
    supports = []
    if capabilities.get("text_input"):
        supports.append("text")
    if capabilities.get("vision") or capabilities.get("image_input"):
        supports.append("vision")
    if capabilities.get("image_output"):
        supports.append("image_generation")
    if preview_type == "embedding" or model_type == "embedding":
        supports.append("embedding")

    if model_type == "embedding":
        short_description = "适合向量检索、召回和相似度计算。"
        best_for = "知识库检索与语义搜索"
    elif model_type == "image_generation":
        short_description = "适合文本生图或图像生成工作流。"
        best_for = "海报、配图与创意图像生成"
    elif model_type == "vision":
        short_description = "适合图文理解、视觉问答和多模态分析。"
        best_for = "图像理解与视觉问答"
    else:
        short_description = "适合通用文本对话、写作和推理任务。"
        best_for = "通用问答、写作与推理"

    price_input = _normalize_optional_price(record.get("price_input"))
    price_output = _normalize_optional_price(record.get("price_output"))
    if price_input is None and price_output is None:
        price_summary = "暂无稳定价格信息"
    elif price_input is not None and price_output is not None:
        price_summary = f"输入 ${price_input:.4f} / 输出 ${price_output:.4f}（每 1M tokens）"
    elif price_input is not None:
        price_summary = f"输入 ${price_input:.4f}（每 1M tokens）"
    else:
        price_summary = f"输出 ${price_output:.4f}（每 1M tokens）"

    return {
        "short_description": short_description,
        "best_for": best_for,
        "supports": supports,
        "price_summary": price_summary,
        "why_recommended": "基于多源模型情报汇聚与平台管理员审查结果生成。",
    }


@lru_cache(maxsize=1)
def _bundled_upstream_evidence_payload() -> dict[str, Any]:
    payload = _load_json_asset("recognition-upstream-evidence.json")
    if not isinstance(payload, Mapping):
        return normalize_upstream_evidence_payload({})
    return normalize_upstream_evidence_payload(payload)


@lru_cache(maxsize=1)
def _huggingface_alias_bridge() -> dict[str, dict[str, str]]:
    payload = _load_json_asset("recognition-hf-alias-bridge.json")
    if not isinstance(payload, Mapping):
        return {}
    mappings = payload.get("mappings", {})
    if not isinstance(mappings, Mapping):
        return {}
    normalized: dict[str, dict[str, str]] = {}
    for source_key, value in mappings.items():
        normalized_key = str(source_key).strip()
        if not normalized_key:
            continue
        if isinstance(value, str):
            repo_id = value.strip()
            quality = "name_match"
        elif isinstance(value, Mapping):
            repo_id = str(value.get("repo_id") or "").strip()
            quality = _normalize_hf_alias_bridge_quality(value.get("quality"))
        else:
            continue
        if not repo_id:
            continue
        normalized[normalized_key] = {
            "repo_id": repo_id,
            "quality": quality,
        }
    return normalized


@lru_cache(maxsize=1)
def _huggingface_alias_bridge_version() -> str:
    payload = _load_json_asset("recognition-hf-alias-bridge.json")
    if not isinstance(payload, Mapping):
        return RECOGNITION_HF_ALIAS_BRIDGE_VERSION
    version = str(payload.get("version") or "").strip()
    return version or RECOGNITION_HF_ALIAS_BRIDGE_VERSION


def _normalize_hf_alias_bridge_quality(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in HF_ALIAS_BRIDGE_CONFIDENCE_PENALTIES:
        return normalized
    return "name_match"


def _upstream_evidence_records(
    upstream_payload: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    payload = dict((upstream_payload or _bundled_upstream_evidence_payload())).get("records", {})
    if not isinstance(payload, Mapping):
        return {}
    return {
        str(key): dict(value)
        for key, value in payload.items()
        if isinstance(key, str) and isinstance(value, Mapping)
    }


def _upstream_evidence_bundle_sources(
    upstream_payload: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    sources = dict((upstream_payload or _bundled_upstream_evidence_payload())).get("sources", {})
    if not isinstance(sources, Mapping):
        return {}
    return {
        str(key): str(value)
        for key, value in sources.items()
        if str(key).strip() and str(value).strip()
    }


def _normalize_optional_price(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None
    if normalized < 0:
        return None
    return round(normalized, 6)


def _load_json_asset(filename: str) -> Any:
    path = DATA_ROOT / filename
    return json.loads(path.read_text(encoding="utf-8"))
