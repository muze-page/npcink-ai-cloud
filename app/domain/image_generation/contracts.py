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

ALLOWED_IMAGE_GENERATION_ASPECT_RATIOS = frozenset(
    {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}
)
ALLOWED_IMAGE_GENERATION_RESOLUTIONS = frozenset({"", "low", "medium", "high"})
ALLOWED_IMAGE_GENERATION_INPUT_FIELDS = frozenset(
    {
        "aspect_ratio",
        "connector_id",
        "connector_version",
        "contract_version",
        "media_context",
        "n",
        "prompt",
        "resolution",
        "review",
        "source_handoff",
        "source_surface",
        "task",
    }
)
IMAGE_GENERATION_MAX_PROMPT_CHARS = 4000
IMAGE_GENERATION_MAX_IMAGES = 4
IMAGE_GENERATION_MAX_CONTEXT_CHARS = 6000
IMAGE_GENERATION_CONTEXT_FIELDS = frozenset({"media_context", "review", "source_handoff"})

FORBIDDEN_IMAGE_GENERATION_PROVIDER_MEDIA_KEYS = frozenset(
    {
        "b64",
        "b64_json",
        "base64",
        "bytes",
        "content_bytes",
        "data_url",
        "download_url",
        "fetch",
        "fetch_url",
        "image_url",
        "provider_response_format",
        "response_format",
        "source_url",
        "url",
    }
)

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
    if str(input_payload.get("contract_version") or "") != IMAGE_GENERATION_CONTRACT:
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
    provider_media_path = find_forbidden_image_generation_provider_media_field(input_payload)
    if provider_media_path:
        raise ImageGenerationContractViolation(
            "image_generation.provider_media_field_forbidden",
            "image generation input may not select or carry provider media field "
            f"'{provider_media_path}'",
        )
    unknown_fields = sorted(
        str(key)
        for key in input_payload
        if not isinstance(key, str) or key not in ALLOWED_IMAGE_GENERATION_INPUT_FIELDS
    )
    if unknown_fields:
        raise ImageGenerationContractViolation(
            "image_generation.unknown_input_field",
            f"image generation input field '{unknown_fields[0]}' is not supported",
        )
    raw_prompt = input_payload.get("prompt")
    if raw_prompt is not None and not isinstance(raw_prompt, str):
        raise ImageGenerationContractViolation(
            "image_generation.prompt_invalid",
            "image generation prompt must be a string",
        )
    prompt = (raw_prompt or "").strip()
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
    raw_image_count = input_payload.get("n", 1)
    if isinstance(raw_image_count, bool) or not isinstance(raw_image_count, int):
        raise ImageGenerationContractViolation(
            "image_generation.image_count_invalid",
            f"image generation n must be an integer between 1 and {IMAGE_GENERATION_MAX_IMAGES}",
        )
    image_count = raw_image_count
    if image_count < 1 or image_count > IMAGE_GENERATION_MAX_IMAGES:
        raise ImageGenerationContractViolation(
            "image_generation.image_count_invalid",
            f"image generation n must be between 1 and {IMAGE_GENERATION_MAX_IMAGES}",
        )
    raw_aspect_ratio = input_payload.get("aspect_ratio", "1:1")
    if not isinstance(raw_aspect_ratio, str):
        raise ImageGenerationContractViolation(
            "image_generation.aspect_ratio_invalid",
            "image generation aspect_ratio must be a string",
        )
    aspect_ratio = raw_aspect_ratio.strip() or "1:1"
    if aspect_ratio not in ALLOWED_IMAGE_GENERATION_ASPECT_RATIOS:
        raise ImageGenerationContractViolation(
            "image_generation.aspect_ratio_invalid",
            "image generation aspect_ratio is not supported",
        )
    raw_resolution = input_payload.get("resolution", "")
    if not isinstance(raw_resolution, str):
        raise ImageGenerationContractViolation(
            "image_generation.resolution_invalid",
            "image generation resolution must be a string",
        )
    resolution = raw_resolution.strip()
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


def find_forbidden_image_generation_provider_media_field(
    value: Any,
    *,
    path: str = "",
) -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").strip().lower()
            current_path = f"{path}.{normalized_key}" if path else normalized_key
            if _is_forbidden_image_generation_provider_media_key(normalized_key):
                return current_path
            nested = find_forbidden_image_generation_provider_media_field(
                item,
                path=current_path,
            )
            if nested:
                return nested
    if isinstance(value, list):
        for index, item in enumerate(value):
            nested = find_forbidden_image_generation_provider_media_field(
                item,
                path=f"{path}[{index}]",
            )
            if nested:
                return nested
    return ""


def _is_forbidden_image_generation_provider_media_key(value: str) -> bool:
    compact = value.replace("_", "").replace("-", "")
    return (
        value in FORBIDDEN_IMAGE_GENERATION_PROVIDER_MEDIA_KEYS
        or value.endswith(("_url", "_urls", "_bytes"))
        or value in {"urls"}
        or "fetch" in compact
        or "base64" in compact
        or compact.startswith("b64")
    )


def _serialized_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError):
        return IMAGE_GENERATION_MAX_CONTEXT_CHARS + 1
