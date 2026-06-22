from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any

from app.adapters.providers.base import (
    ProviderAdapter,
    ProviderExecutionError,
    ProviderExecutionRequest,
    ProviderExecutionResult,
)
from app.core.config import Settings
from app.domain.image_context_evidence.contracts import (
    IMAGE_CONTEXT_EVIDENCE_REQUEST_CONTRACT,
    IMAGE_CONTEXT_EVIDENCE_RESULT_CONTRACT,
    extract_image_context_evidence_request,
    validate_image_context_evidence_runtime_contract,
)

MAX_PROMPT_METADATA_CHARS = 500


@dataclass(slots=True)
class ImageContextEvidenceProviderUsage:
    provider_id: str
    model_id: str
    instance_id: str
    region: str
    latency_ms: int
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    error_code: str | None = None


@dataclass(slots=True)
class ImageContextEvidenceExecutionResult:
    result_json: dict[str, Any]
    usage: ImageContextEvidenceProviderUsage


class ImageContextEvidenceProviderError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        usage: ImageContextEvidenceProviderUsage | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.usage = usage


class ImageContextEvidenceService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def execute(
        self,
        *,
        site_id: str,
        ability_name: str,
        contract_version: str,
        input_payload: dict[str, Any],
        run_id: str,
        provider: ProviderAdapter,
        provider_id: str,
        model_id: str,
        instance_id: str,
        endpoint_variant: str,
        region: str,
        trace_id: str,
        profile_id: str,
        policy: dict[str, Any],
        timeout_ms: int,
        price_input: float | None = None,
        price_output: float | None = None,
    ) -> ImageContextEvidenceExecutionResult:
        validate_image_context_evidence_runtime_contract(
            ability_name=ability_name,
            contract_version=contract_version,
            input_payload=input_payload,
        )
        evidence_request = extract_image_context_evidence_request(input_payload)
        provider_input = _build_provider_input(evidence_request)
        request = ProviderExecutionRequest(
            run_id=run_id,
            site_id=site_id,
            ability_name=ability_name,
            profile_id=profile_id,
            execution_kind="vision",
            model_id=model_id,
            instance_id=instance_id,
            endpoint_variant=endpoint_variant,
            trace_id=trace_id,
            input_payload=provider_input,
            policy=policy,
            timeout_ms=timeout_ms,
            price_input=price_input,
            price_output=price_output,
            retry_count=0,
        )
        started = time.monotonic()
        try:
            provider_result = provider.execute(request)
        except ProviderExecutionError as error:
            usage = ImageContextEvidenceProviderUsage(
                provider_id=provider_id,
                model_id=model_id,
                instance_id=instance_id,
                region=region,
                latency_ms=max(0, int((time.monotonic() - started) * 1000)),
                tokens_in=max(0, int(error.tokens_in)),
                tokens_out=max(0, int(error.tokens_out)),
                cost=max(0.0, float(error.cost)),
                error_code=error.error_code,
            )
            raise ImageContextEvidenceProviderError(
                error.error_code,
                error.message,
                usage=usage,
            ) from error

        usage = ImageContextEvidenceProviderUsage(
            provider_id=provider_id,
            model_id=model_id,
            instance_id=instance_id,
            region=region,
            latency_ms=provider_result.latency_ms,
            tokens_in=provider_result.tokens_in,
            tokens_out=provider_result.tokens_out,
            cost=provider_result.cost,
        )
        result_json = _build_result_json(
            evidence_request,
            provider_result=provider_result,
            site_id=site_id,
            run_id=run_id,
            provider_id=provider_id,
            model_id=model_id,
            instance_id=instance_id,
            region=region,
        )
        return ImageContextEvidenceExecutionResult(result_json=result_json, usage=usage)


def _build_provider_input(evidence_request: dict[str, Any]) -> dict[str, Any]:
    items = [_normalize_request_item(item) for item in _list(evidence_request.get("items"))]
    prompt_context = {
        "contract_version": IMAGE_CONTEXT_EVIDENCE_REQUEST_CONTRACT,
        "locale": _text(evidence_request.get("locale"), limit=32) or "zh_CN",
        "task": (
            "Inspect each supplied image and return only JSON matching "
            "image_context_evidence.v1. The result supports WordPress media ALT "
            "and caption suggestions. Do not claim any WordPress write happened."
        ),
        "items": [
            {
                "attachment_id": item["attachment_id"],
                "title": item["title"],
                "filename": item["filename"],
                "mime_type": item["mime_type"],
                "existing_alt": item["existing_alt"],
                "existing_caption": item["existing_caption"],
            }
            for item in items
        ],
        "output_schema": {
            "contract_version": IMAGE_CONTEXT_EVIDENCE_RESULT_CONTRACT,
            "artifact_type": "image_context_evidence",
            "items": [
                {
                    "attachment_id": "same id as request item",
                    "visual_summary": "short visual description",
                    "visible_text": ["visible text snippets, if any"],
                    "subject_tags": ["concrete visual subjects"],
                    "alt_text_basis": "facts useful for ALT suggestion",
                    "caption_basis": "facts useful for caption suggestion",
                    "confidence": 0.0,
                    "uncertainty_flags": ["low_resolution or ambiguous_subject if relevant"],
                }
            ],
            "direct_wordpress_write": False,
            "requires_human_visual_check": True,
        },
    }

    responses_content: list[dict[str, Any]] = [
        {"type": "input_text", "text": json.dumps(prompt_context, ensure_ascii=False)}
    ]
    chat_content: list[dict[str, Any]] = [
        {"type": "text", "text": json.dumps(prompt_context, ensure_ascii=False)}
    ]
    for item in items:
        label = (
            f"attachment_id={item['attachment_id']} title={item['title']} "
            f"filename={item['filename']}"
        ).strip()
        image_url = item["source_url"] or item["thumbnail_url"]
        responses_content.extend(
            [
                {"type": "input_text", "text": label},
                {"type": "input_image", "image_url": image_url},
            ]
        )
        chat_content.extend(
            [
                {"type": "text", "text": label},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]
        )

    return {
        "input": [{"role": "user", "content": responses_content}],
        "messages": [{"role": "user", "content": chat_content}],
        "params": {
            "temperature": 0.0,
            "max_tokens": 1400,
            "max_output_tokens": 1400,
            "response_format": {"type": "json_object"},
        },
    }


def _build_result_json(
    evidence_request: dict[str, Any],
    *,
    provider_result: ProviderExecutionResult,
    site_id: str,
    run_id: str,
    provider_id: str,
    model_id: str,
    instance_id: str,
    region: str,
) -> dict[str, Any]:
    requested_items = [
        _normalize_request_item(item) for item in _list(evidence_request.get("items"))
    ]
    requested_by_id = {item["attachment_id"]: item for item in requested_items}
    payload = _parse_provider_json(provider_result.output)
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raw_items = payload.get("evidence_items")
    if not isinstance(raw_items, list):
        raise ImageContextEvidenceProviderError(
            "image_context_evidence.invalid_provider_response",
            "vision provider response did not include an items array",
            usage=ImageContextEvidenceProviderUsage(
                provider_id=provider_id,
                model_id=model_id,
                instance_id=instance_id,
                region=region,
                latency_ms=provider_result.latency_ms,
                tokens_in=provider_result.tokens_in,
                tokens_out=provider_result.tokens_out,
                cost=provider_result.cost,
                error_code="image_context_evidence.invalid_provider_response",
            ),
        )

    normalized_items: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        attachment_id = _text(raw_item.get("attachment_id"), limit=120)
        if attachment_id not in requested_by_id:
            continue
        request_item = requested_by_id[attachment_id]
        normalized_items.append(_normalize_evidence_item(raw_item, request_item=request_item))

    if not normalized_items:
        raise ImageContextEvidenceProviderError(
            "image_context_evidence.empty_provider_response",
            "vision provider response did not include evidence for requested attachments",
            usage=ImageContextEvidenceProviderUsage(
                provider_id=provider_id,
                model_id=model_id,
                instance_id=instance_id,
                region=region,
                latency_ms=provider_result.latency_ms,
                tokens_in=provider_result.tokens_in,
                tokens_out=provider_result.tokens_out,
                cost=provider_result.cost,
                error_code="image_context_evidence.empty_provider_response",
            ),
        )

    return {
        "contract_version": IMAGE_CONTEXT_EVIDENCE_RESULT_CONTRACT,
        "artifact_type": "image_context_evidence",
        "status": "ready" if len(normalized_items) == len(requested_items) else "partial",
        "site_id": site_id,
        "run_id": run_id,
        "request_hash": _hash_json(evidence_request),
        "source": {
            "provider_id": provider_id,
            "model_id": model_id,
            "instance_id": instance_id,
            "evidence_basis": "cloud_vision_model",
        },
        "items": normalized_items,
        "requires_human_visual_check": True,
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
    }


def _parse_provider_json(output: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {}
    for key in ("image_context_evidence", "result", "json"):
        nested = output.get(key)
        if isinstance(nested, dict):
            return nested
    output_text = output.get("output_text")
    if isinstance(output_text, str):
        parsed = _parse_json_text(output_text)
        if isinstance(parsed, dict):
            return parsed
    messages = output.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str):
                parsed = _parse_json_text(content)
                if isinstance(parsed, dict):
                    return parsed
    return output


def _parse_json_text(text: str) -> dict[str, Any] | None:
    normalized = text.strip()
    if not normalized:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", normalized, flags=re.DOTALL)
    if fence:
        normalized = fence.group(1).strip()
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError:
        start = normalized.find("{")
        end = normalized.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(normalized[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_request_item(item: Any) -> dict[str, str]:
    raw = item if isinstance(item, dict) else {}
    return {
        "attachment_id": _text(raw.get("attachment_id"), limit=120),
        "source_url": _text(raw.get("source_url") or raw.get("url"), limit=2048),
        "thumbnail_url": _text(raw.get("thumbnail_url"), limit=2048),
        "title": _text(raw.get("title"), limit=MAX_PROMPT_METADATA_CHARS),
        "filename": _text(raw.get("filename"), limit=MAX_PROMPT_METADATA_CHARS),
        "mime_type": _text(raw.get("mime_type"), limit=120),
        "existing_alt": _text(raw.get("existing_alt"), limit=MAX_PROMPT_METADATA_CHARS),
        "existing_caption": _text(raw.get("existing_caption"), limit=MAX_PROMPT_METADATA_CHARS),
    }


def _normalize_evidence_item(
    raw_item: dict[str, Any],
    *,
    request_item: dict[str, str],
) -> dict[str, Any]:
    return {
        "attachment_id": request_item["attachment_id"],
        "source_url": request_item["source_url"],
        "thumbnail_url": request_item["thumbnail_url"],
        "visual_summary": _text(raw_item.get("visual_summary"), limit=500),
        "visible_text": _string_list(raw_item.get("visible_text"), limit=80, max_items=8),
        "subject_tags": _string_list(raw_item.get("subject_tags"), limit=60, max_items=12),
        "alt_text_basis": _text(raw_item.get("alt_text_basis"), limit=300),
        "caption_basis": _text(raw_item.get("caption_basis"), limit=500),
        "confidence": _confidence(raw_item.get("confidence")),
        "uncertainty_flags": _string_list(raw_item.get("uncertainty_flags"), limit=80, max_items=8),
        "requires_human_visual_check": True,
    }


def _string_list(value: Any, *, limit: int, max_items: int) -> list[str]:
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, list):
        candidates = value
    else:
        candidates = []
    normalized: list[str] = []
    for item in candidates:
        text = _text(item, limit=limit)
        if text and text not in normalized:
            normalized.append(text)
        if len(normalized) >= max_items:
            break
    return normalized


def _confidence(value: Any) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        normalized = 0.0
    return round(max(0.0, min(1.0, normalized)), 3)


def _text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        return text[:limit].rstrip()
    return text


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _hash_json(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()
