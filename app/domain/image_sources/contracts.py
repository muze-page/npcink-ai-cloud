from __future__ import annotations

from typing import Any

IMAGE_SOURCE_CLOUD_ABILITY = "npcink-cloud/search-image-source"
IMAGE_SOURCE_TOOLBOX_ABILITY = "npcink-toolbox/search-image-source"
IMAGE_SOURCE_ABILITIES = frozenset({IMAGE_SOURCE_CLOUD_ABILITY, IMAGE_SOURCE_TOOLBOX_ABILITY})
IMAGE_SOURCE_CONTRACT = "image_source_cloud_request.v1"
IMAGE_SOURCE_PROFILE_ID = "image-source.managed"
IMAGE_SOURCE_EXECUTION_KIND = "image_source"
IMAGE_SOURCE_ABILITY_FAMILY = "knowledge"
IMAGE_SOURCE_DATA_CLASSIFICATION = "public_reference_media"
IMAGE_CANDIDATE_CONTRACT = "image_candidate.v1"

ALLOWED_IMAGE_SOURCE_PROVIDERS = frozenset({"auto", "cloud", "unsplash", "pixabay", "pexels"})
ALLOWED_IMAGE_SOURCE_ORIENTATIONS = frozenset({"", "landscape", "portrait", "squarish", "square"})

FORBIDDEN_IMAGE_SOURCE_KEYS = frozenset(
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
        "set_post_content",
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


class ImageSourceContractViolation(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def validate_image_source_runtime_contract(
    *,
    ability_name: str,
    contract_version: str,
    input_payload: dict[str, Any],
) -> None:
    if ability_name not in IMAGE_SOURCE_ABILITIES:
        raise ImageSourceContractViolation(
            "image_source.unknown_ability",
            "image source ability_name is not supported",
        )
    if contract_version != IMAGE_SOURCE_CONTRACT:
        raise ImageSourceContractViolation(
            "image_source.contract_mismatch",
            "image source contract_version does not match ability_name",
        )
    if not isinstance(input_payload, dict):
        raise ImageSourceContractViolation(
            "image_source.invalid_input",
            "image source input must be an object",
        )
    if str(input_payload.get("contract_version") or contract_version) != IMAGE_SOURCE_CONTRACT:
        raise ImageSourceContractViolation(
            "image_source.input_contract_mismatch",
            "image source input contract_version does not match runtime contract",
        )
    candidate_contract = str(
        input_payload.get("candidate_contract")
        or input_payload.get("candidate_contract_version")
        or IMAGE_CANDIDATE_CONTRACT
    )
    if candidate_contract != IMAGE_CANDIDATE_CONTRACT:
        raise ImageSourceContractViolation(
            "image_source.candidate_contract_mismatch",
            "image source output must use image_candidate.v1",
        )
    forbidden_path = find_forbidden_image_source_field(input_payload)
    if forbidden_path:
        raise ImageSourceContractViolation(
            "image_source.write_or_secret_field_forbidden",
            "image source input may not include provider secret or write/control "
            f"field '{forbidden_path}'",
        )


def find_forbidden_image_source_field(value: Any, *, path: str = "") -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").strip().lower()
            current_path = f"{path}.{normalized_key}" if path else normalized_key
            if normalized_key in FORBIDDEN_IMAGE_SOURCE_KEYS:
                if normalized_key == "direct_wordpress_write" and item is False:
                    continue
                return current_path
            nested = find_forbidden_image_source_field(item, path=current_path)
            if nested:
                return nested
    if isinstance(value, list):
        for index, item in enumerate(value):
            nested = find_forbidden_image_source_field(item, path=f"{path}[{index}]")
            if nested:
                return nested
    return ""


def coerce_positive_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return max(1, min(maximum, normalized))
