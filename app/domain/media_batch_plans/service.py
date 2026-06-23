from __future__ import annotations

import hashlib
import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings
from app.domain.media_batch_plans.contracts import (
    MEDIA_BATCH_PLAN_OUTPUT_CONTRACT,
    validate_media_batch_plan_runtime_contract,
)

TARGET_FORMATS = ("webp", "avif", "jpeg", "jpg", "png", "original")
MONTH_NAMES = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


@dataclass(slots=True)
class MediaBatchPlanExecutionResult:
    result_json: dict[str, Any]


class MediaBatchPlanService:
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
    ) -> MediaBatchPlanExecutionResult:
        validate_media_batch_plan_runtime_contract(
            ability_name=ability_name,
            contract_version=contract_version,
            input_payload=input_payload,
        )
        user_request = _normalize_text(
            input_payload.get("user_request")
            or input_payload.get("intent_text")
            or input_payload.get("prompt"),
            limit=2000,
        )
        context = _dict(input_payload.get("site_context"))
        current_time = _resolve_current_time(context)
        operation = _build_operation(user_request, input_payload)
        scope = _build_scope(user_request, input_payload, current_time=current_time)
        exclusions = _build_exclusions(user_request, input_payload, operation=operation)
        recommended_chunk_size = _recommended_chunk_size(self.settings)
        warnings = _build_warnings(user_request, operation=operation, exclusions=exclusions)
        plan = {
            "contract_version": MEDIA_BATCH_PLAN_OUTPUT_CONTRACT,
            "artifact_type": "media_derivative_batch_plan",
            "status": "ready",
            "site_id": site_id,
            "plan_id": f"mbp_{_hash_text(f'{site_id}:{run_id}:{user_request}')[:24]}",
            "intent": "optimize_media_batch",
            "source": {
                "provider": "npcink_ai_cloud",
                "provider_mode": "deterministic_intent_parser",
                "user_request_hash": _hash_text(user_request),
                "user_request_chars": len(user_request),
            },
            "scope": scope,
            "operation": operation,
            "exclusions": exclusions,
            "execution_plan": {
                "mode": "chunked_single_derivative_runs",
                "runtime_endpoint": "/v1/runtime/media-derivatives",
                "recommended_chunk_size": recommended_chunk_size,
                "max_chunk_size": int(self.settings.media_derivative_batch_max_chunk_size),
                "batch_context_template": {
                    "batch_id": "provided_by_local_or_adapter",
                    "item_index": 1,
                    "item_count": 0,
                    "chunk_size": recommended_chunk_size,
                    "explicit_avif": bool(operation["target_format"] == "avif"),
                },
                "queue_pressure_source": "media_derivative_response.queue_pressure",
            },
            "confirmation": {
                "requires_operator_confirmation": True,
                "requires_core_proposal": True,
                "summary": _confirmation_summary(scope=scope, operation=operation),
                "primary_action": "generate_previews",
                "final_action": "submit_core_proposal",
            },
            "handoff": {
                "plan_contract": MEDIA_BATCH_PLAN_OUTPUT_CONTRACT,
                "derivative_request_contract": "media_derivative_cloud_request.v1",
                "final_writes": "core_proposal_required",
                "direct_wordpress_write": False,
                "wordpress_write_owner": "core_proposal_approval",
            },
            "plan_confidence": _plan_confidence(scope=scope, operation=operation),
            "warnings": warnings,
            "write_posture": "plan_only",
            "direct_wordpress_write": False,
        }
        return MediaBatchPlanExecutionResult(result_json=plan)


def _build_operation(user_request: str, input_payload: dict[str, Any]) -> dict[str, Any]:
    overrides = _dict(input_payload.get("defaults"))
    target_format = _resolve_target_format(user_request, overrides)
    crop = _resolve_crop(user_request, overrides)
    watermark = _resolve_watermark(user_request, overrides)
    operation: dict[str, Any] = {
        "target_format": target_format,
        "max_width": _resolve_max_width(user_request, overrides),
        "quality": _resolve_quality(user_request, overrides),
        "source_media_type": "image",
        "crop": crop,
        "watermark": watermark,
    }
    return operation


def _build_scope(
    user_request: str,
    input_payload: dict[str, Any],
    *,
    current_time: datetime,
) -> dict[str, Any]:
    requested_scope = _dict(input_payload.get("scope"))
    month_range = _resolve_month_range(user_request, current_time=current_time)
    scope = {
        "media_type": "image",
        "uploaded_from": str(requested_scope.get("uploaded_from") or month_range[0]),
        "uploaded_to": str(requested_scope.get("uploaded_to") or month_range[1]),
        "selection_mode": "media_library_query",
        "requires_local_media_enumeration": True,
    }
    if _contains_any(user_request, ("当前媒体库", "媒体库", "media library", "uploads")):
        scope["source"] = "wordpress_media_library"
    if _contains_any(user_request, ("特色图", "featured image", "thumbnail")):
        scope["role"] = "featured_image"
    return scope


def _build_exclusions(
    user_request: str,
    input_payload: dict[str, Any],
    *,
    operation: dict[str, Any],
) -> dict[str, Any]:
    requested = _dict(input_payload.get("exclusions"))
    skip_formats = _normalize_string_list(requested.get("skip_formats")) or ["gif", "svg"]
    if operation["target_format"] != "png" and _contains_any(
        user_request,
        ("透明", "transparent", "alpha"),
    ):
        skip_formats.append("png")
    skip_width = _coerce_int(requested.get("skip_if_width_below"), default=0)
    skip_size = _coerce_int(requested.get("skip_if_filesize_below"), default=0)
    if skip_width <= 0 and _contains_any(user_request, ("大图", "large image", "big image")):
        skip_width = 800
    if skip_size <= 0 and _contains_any(user_request, ("小图", "small image", "tiny")):
        skip_size = 100_000
    return {
        "skip_formats": sorted(set(skip_formats)),
        "skip_if_width_below": max(0, skip_width),
        "skip_if_filesize_below": max(0, skip_size),
        "skip_animated": True,
        "skip_missing_source_file": True,
        "skip_when_derivative_preview_unavailable": True,
    }


def _resolve_target_format(user_request: str, overrides: dict[str, Any]) -> str:
    raw_override = str(overrides.get("target_format") or "").strip().lower()
    if raw_override in TARGET_FORMATS:
        return "jpeg" if raw_override == "jpg" else raw_override
    lowered = user_request.lower()
    for fmt in TARGET_FORMATS:
        if re.search(rf"(?<![a-z0-9]){fmt}(?![a-z0-9])", lowered):
            return "jpeg" if fmt == "jpg" else fmt
    if "智能" in user_request or "自动" in user_request or "optimiz" in lowered:
        return "webp"
    return "webp"


def _resolve_max_width(user_request: str, overrides: dict[str, Any]) -> int:
    override = _coerce_int(overrides.get("max_width"), default=0)
    if override > 0:
        return min(10000, override)
    patterns = (
        r"(?:max[_\s-]?width|width|宽度|最长边|不超过|最大)[^\d]{0,12}(\d{3,5})",
        r"(\d{3,5})[^\d]{0,8}(?:px|像素|宽|宽度)",
    )
    for pattern in patterns:
        match = re.search(pattern, user_request, flags=re.IGNORECASE)
        if match:
            return min(10000, max(1, int(match.group(1))))
    return 1600


def _resolve_quality(user_request: str, overrides: dict[str, Any]) -> int:
    override = _coerce_int(overrides.get("quality"), default=0)
    if override > 0:
        return min(100, max(1, override))
    match = re.search(
        r"(?:quality|质量|品质|压缩质量)[^\d]{0,12}(\d{1,3})",
        user_request,
        flags=re.IGNORECASE,
    )
    if match:
        return min(100, max(1, int(match.group(1))))
    return 82


def _resolve_watermark(user_request: str, overrides: dict[str, Any]) -> dict[str, Any]:
    requested = _dict(overrides.get("watermark"))
    if requested:
        requested.setdefault("requires_local_asset_selection", True)
        return requested
    if not _contains_any(user_request, ("水印", "watermark", "logo", "LOGO")):
        return {}
    watermark_type = "image" if _contains_any(user_request, ("logo", "LOGO", "标志")) else "text"
    watermark: dict[str, Any] = {
        "type": watermark_type,
        "position": _resolve_position(user_request),
        "opacity": 0.75,
        "margin_px": 24,
        "requires_local_asset_selection": watermark_type == "image",
    }
    if watermark_type == "image":
        watermark["scale_percent"] = 18
    else:
        watermark["text"] = "AI"
        watermark["font_size"] = 48
    return watermark


def _resolve_crop(user_request: str, overrides: dict[str, Any]) -> dict[str, Any]:
    requested = _dict(overrides.get("crop"))
    if requested:
        ratio = _normalize_crop_ratio(str(requested.get("aspect_ratio") or "16:9"))
        position = str(requested.get("position") or "center")
        if position not in {
            "top_left",
            "top",
            "top_right",
            "left",
            "center",
            "right",
            "bottom_left",
            "bottom",
            "bottom_right",
        }:
            position = "center"
        return {"type": "aspect_ratio", "aspect_ratio": ratio, "position": position}

    lowered = user_request.lower()
    ratio = ""
    match = re.search(r"([1-9][0-9]{0,2})\s*[:：]\s*([1-9][0-9]{0,2})", user_request)
    if match and _contains_any(user_request, ("裁剪", "比例", "ratio", "crop", "aspect")):
        ratio = _normalize_crop_ratio(f"{match.group(1)}:{match.group(2)}")
    elif _contains_any(user_request, ("方图", "正方形", "square")):
        ratio = "1:1"
    elif _contains_any(user_request, ("横版", "landscape")) and _contains_any(
        user_request,
        ("裁剪", "crop", "ratio", "比例"),
    ):
        ratio = "16:9"
    elif _contains_any(user_request, ("竖版", "portrait")) and _contains_any(
        user_request,
        ("裁剪", "crop", "ratio", "比例"),
    ):
        ratio = "9:16"
    elif "16x9" in lowered or "16 by 9" in lowered:
        ratio = "16:9"
    elif "1x1" in lowered or "1 by 1" in lowered:
        ratio = "1:1"

    if not ratio:
        return {}
    return {
        "type": "aspect_ratio",
        "aspect_ratio": ratio,
        "position": "center",
    }


def _normalize_crop_ratio(value: str) -> str:
    match = re.fullmatch(r"\s*([1-9][0-9]{0,2})\s*[:：xX]\s*([1-9][0-9]{0,2})\s*", value)
    if not match:
        return "16:9"
    width = max(1, min(100, int(match.group(1))))
    height = max(1, min(100, int(match.group(2))))
    return f"{width}:{height}"


def _resolve_position(user_request: str) -> str:
    if _contains_any(user_request, ("右下", "bottom right", "bottom-right")):
        return "bottom_right"
    if _contains_any(user_request, ("左下", "bottom left", "bottom-left")):
        return "bottom_left"
    if _contains_any(user_request, ("右上", "top right", "top-right")):
        return "top_right"
    if _contains_any(user_request, ("左上", "top left", "top-left")):
        return "top_left"
    if _contains_any(user_request, ("居中", "center", "中央")):
        return "center"
    return "bottom_right"


def _resolve_month_range(
    user_request: str,
    *,
    current_time: datetime,
) -> tuple[str, str]:
    chinese = re.search(r"(?:(20\d{2})\s*年)?\s*(1[0-2]|[1-9])\s*月", user_request)
    if chinese:
        year = int(chinese.group(1) or current_time.year)
        month = int(chinese.group(2))
        return _month_bounds(year, month)
    lowered = user_request.lower()
    for name, month in MONTH_NAMES.items():
        if re.search(rf"(?<![a-z]){name}(?![a-z])", lowered):
            year_match = re.search(r"(20\d{2})", user_request)
            year = int(year_match.group(1)) if year_match else current_time.year
            return _month_bounds(year, month)
    return "", ""


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    last_day = monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"


def _build_warnings(
    user_request: str,
    *,
    operation: dict[str, Any],
    exclusions: dict[str, Any],
) -> list[str]:
    warnings = [
        "This is a planning artifact only; Core proposal approval is required "
        "before WordPress writes.",
        "Hard-coded image URLs in post content or theme/plugin settings require "
        "local preflight handling.",
    ]
    if operation["target_format"] == "avif":
        warnings.append(
            "AVIF batch processing is CPU intensive and requires explicit batch opt-in."
        )
    if operation.get("watermark"):
        warnings.append("Watermark asset selection and authorization remain local/operator-owned.")
    if operation.get("crop"):
        warnings.append(
            "Crop previews should be visually reviewed before Core proposal submission."
        )
    if "png" in exclusions.get("skip_formats", []):
        warnings.append(
            "Transparent PNG inputs are excluded unless the local plan owner overrides it."
        )
    if _contains_any(user_request, ("全部", "all", "所有")):
        warnings.append(
            "Review a sampled before/after preview before submitting the Core proposal."
        )
    return warnings


def _confirmation_summary(*, scope: dict[str, Any], operation: dict[str, Any]) -> str:
    date_part = ""
    if scope.get("uploaded_from") and scope.get("uploaded_to"):
        date_part = f" from {scope['uploaded_from']} to {scope['uploaded_to']}"
    watermark_part = " with watermark" if operation.get("watermark") else ""
    crop_part = ""
    if operation.get("crop"):
        crop = operation["crop"]
        crop_part = f" and crop {crop.get('aspect_ratio', '')}"
    return (
        f"Generate preview derivatives for image media{date_part}: "
        f"{operation['target_format']} at max width {operation['max_width']} "
        f"and quality {operation['quality']}{crop_part}{watermark_part}."
    )


def _plan_confidence(*, scope: dict[str, Any], operation: dict[str, Any]) -> float:
    score = 0.72
    if scope.get("uploaded_from") and scope.get("uploaded_to"):
        score += 0.1
    if operation.get("target_format"):
        score += 0.08
    if operation.get("watermark"):
        score += 0.04
    if operation.get("crop"):
        score += 0.03
    return min(0.94, round(score, 2))


def _recommended_chunk_size(settings: Settings) -> int:
    default_chunk = int(settings.media_derivative_batch_default_chunk_size)
    max_chunk = int(settings.media_derivative_batch_max_chunk_size)
    return max(1, min(default_chunk, max_chunk))


def _resolve_current_time(context: dict[str, Any]) -> datetime:
    raw = str(context.get("current_date") or context.get("now") or "").strip()
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _normalize_text(value: Any, *, limit: int) -> str:
    text = str(value or "").strip()
    text = " ".join(text.split())
    return text[:limit]


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item or "").strip().lower() for item in value if str(item or "").strip()]


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
