from __future__ import annotations

import json
from typing import Any

from app.domain.hosted_model_defaults import GROK_IMAGINE_IMAGE_PROFILE_ID

IMAGE_GENERATION_CLOUD_ABILITY = "npcink-cloud/generate-image"
IMAGE_GENERATION_TOOLBOX_ABILITY = "npcink-toolbox/generate-image"
IMAGE_GENERATION_ABILITIES = frozenset(
    {IMAGE_GENERATION_CLOUD_ABILITY, IMAGE_GENERATION_TOOLBOX_ABILITY}
)
IMAGE_GENERATION_CONTRACT = "image_generation_request.v1"
IMAGE_GENERATION_PROFILE_ID = GROK_IMAGINE_IMAGE_PROFILE_ID
IMAGE_GENERATION_EXECUTION_KIND = "image_generation"
IMAGE_GENERATION_ABILITY_FAMILY = "vision"
IMAGE_GENERATION_DATA_CLASSIFICATION = "internal"
IMAGE_GENERATION_RESULT_CONTRACT = "image_generation_result.v1"

ALLOWED_IMAGE_GENERATION_RESPONSE_FORMATS = frozenset({"url", "b64_json"})
ALLOWED_IMAGE_GENERATION_ASPECT_RATIOS = frozenset(
    {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}
)
ALLOWED_IMAGE_GENERATION_RESOLUTIONS = frozenset({"", "low", "medium", "high"})
IMAGE_GENERATION_MAX_PROMPT_CHARS = 4000
IMAGE_GENERATION_MAX_IMAGES = 4
IMAGE_GENERATION_MAX_CONTEXT_CHARS = 6000
IMAGE_GENERATION_CONTEXT_FIELDS = frozenset({"media_context", "review", "source_handoff"})

FORBIDDEN_IMAGE_GENERATION_KEYS = frozenset(
    {
        "api_key",
        "apply_policy",
        "callback_secret",
        "cloud_secret",
        "confirm_token",
        "direct_publish",
        "direct_wordpress_write",
        "final_write_policy",
        "final_write_target",
        "headers",
        "provider_key",
        "provider_secret",
        "publish",
        "secret",
        "set_featured_image",
        "set_post_content",
        "update_media",
        "update_post",
        "wordpress_password",
        "wordpress_secret",
        "wordpress_write_policy",
        "wordpress_write_target",
        "write_confirmed",
        "write_control",
        "write_controls",
    }
)


class ImageGenerationContractViolation(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def validate_image_generation_runtime_contract(
    *,
    ability_name: str,
    contract_version: str,
    input_payload: dict[str, Any],
) -> None:
    if ability_name not in IMAGE_GENERATION_ABILITIES:
        raise ImageGenerationContractViolation(
            "image_generation.unknown_ability",
            "image generation ability_name is not supported",
        )
    if contract_version != IMAGE_GENERATION_CONTRACT:
        raise ImageGenerationContractViolation(
            "image_generation.contract_mismatch",
            "image generation contract_version does not match ability_name",
        )
    if not isinstance(input_payload, dict):
        raise ImageGenerationContractViolation(
            "image_generation.invalid_input",
            "image generation input must be an object",
        )
    if str(input_payload.get("contract_version") or contract_version) != IMAGE_GENERATION_CONTRACT:
        raise ImageGenerationContractViolation(
            "image_generation.input_contract_mismatch",
            "image generation input contract_version does not match runtime contract",
        )
    forbidden_path = find_forbidden_image_generation_field(input_payload)
    if forbidden_path:
        raise ImageGenerationContractViolation(
            "image_generation.write_or_secret_field_forbidden",
            "image generation input may not include provider secret or write/control "
            f"field '{forbidden_path}'",
        )
    prompt = str(input_payload.get("prompt") or input_payload.get("text") or "").strip()
    if not prompt:
        raise ImageGenerationContractViolation(
            "image_generation.prompt_required",
            "image generation prompt is required",
        )
    if len(prompt) > IMAGE_GENERATION_MAX_PROMPT_CHARS:
        raise ImageGenerationContractViolation(
            "image_generation.prompt_too_long",
            "image generation prompt must be "
            f"{IMAGE_GENERATION_MAX_PROMPT_CHARS} characters or fewer",
        )
    image_count = _coerce_int(input_payload.get("n"), default=1)
    if image_count < 1 or image_count > IMAGE_GENERATION_MAX_IMAGES:
        raise ImageGenerationContractViolation(
            "image_generation.image_count_invalid",
            f"image generation n must be between 1 and {IMAGE_GENERATION_MAX_IMAGES}",
        )
    response_format = str(input_payload.get("response_format") or "url").strip()
    if response_format not in ALLOWED_IMAGE_GENERATION_RESPONSE_FORMATS:
        raise ImageGenerationContractViolation(
            "image_generation.response_format_invalid",
            "image generation response_format must be url or b64_json",
        )
    aspect_ratio = str(input_payload.get("aspect_ratio") or "1:1").strip()
    if aspect_ratio not in ALLOWED_IMAGE_GENERATION_ASPECT_RATIOS:
        raise ImageGenerationContractViolation(
            "image_generation.aspect_ratio_invalid",
            "image generation aspect_ratio is not supported",
        )
    resolution = str(input_payload.get("resolution") or "").strip()
    if resolution not in ALLOWED_IMAGE_GENERATION_RESOLUTIONS:
        raise ImageGenerationContractViolation(
            "image_generation.resolution_invalid",
            "image generation resolution must be low, medium, or high",
        )
    for field in IMAGE_GENERATION_CONTEXT_FIELDS:
        if field not in input_payload:
            continue
        context_value = input_payload.get(field)
        if not isinstance(context_value, dict):
            raise ImageGenerationContractViolation(
                "image_generation.context_invalid",
                f"image generation {field} must be an object",
            )
        if _serialized_size(context_value) > IMAGE_GENERATION_MAX_CONTEXT_CHARS:
            raise ImageGenerationContractViolation(
                "image_generation.context_too_large",
                f"image generation {field} must serialize to "
                f"{IMAGE_GENERATION_MAX_CONTEXT_CHARS} characters or fewer",
            )


def find_forbidden_image_generation_field(value: Any, *, path: str = "") -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").strip().lower()
            current_path = f"{path}.{normalized_key}" if path else normalized_key
            if normalized_key in FORBIDDEN_IMAGE_GENERATION_KEYS:
                if normalized_key == "direct_wordpress_write" and item is False:
                    continue
                return current_path
            nested = find_forbidden_image_generation_field(item, path=current_path)
            if nested:
                return nested
    if isinstance(value, list):
        for index, item in enumerate(value):
            nested = find_forbidden_image_generation_field(item, path=f"{path}[{index}]")
            if nested:
                return nested
    return ""


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _serialized_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError):
        return IMAGE_GENERATION_MAX_CONTEXT_CHARS + 1
