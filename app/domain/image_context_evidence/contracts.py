from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

IMAGE_CONTEXT_EVIDENCE_ABILITY = "npcink-cloud/image-context-evidence"
IMAGE_CONTEXT_EVIDENCE_ABILITIES = frozenset({IMAGE_CONTEXT_EVIDENCE_ABILITY})
IMAGE_CONTEXT_EVIDENCE_REQUEST_CONTRACT = "image_context_evidence_request.v1"
IMAGE_CONTEXT_EVIDENCE_RESULT_CONTRACT = "image_context_evidence.v1"
IMAGE_CONTEXT_EVIDENCE_EXECUTION_KIND = "image_context_evidence"
IMAGE_CONTEXT_EVIDENCE_PROFILE_ID = "vision.ai"
IMAGE_CONTEXT_EVIDENCE_ABILITY_FAMILY = "vision"
IMAGE_CONTEXT_EVIDENCE_DATA_CLASSIFICATION = "public_site_media_metadata"
MAX_IMAGE_CONTEXT_EVIDENCE_ITEMS = 10

FORBIDDEN_IMAGE_CONTEXT_EVIDENCE_KEYS = frozenset(
    {
        "api_key",
        "apply_decision",
        "apply_policy",
        "approval_decision",
        "callback_secret",
        "cloud_secret",
        "confirm_token",
        "direct_publish",
        "direct_wordpress_write",
        "final_write_policy",
        "final_write_target",
        "headers",
        "metadata_patch",
        "provider_key",
        "provider_secret",
        "publish",
        "secret",
        "set_post_content",
        "update_attachment_metadata",
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


class ImageContextEvidenceContractViolation(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def validate_image_context_evidence_runtime_contract(
    *,
    ability_name: str,
    contract_version: str,
    input_payload: dict[str, Any],
) -> None:
    if ability_name not in IMAGE_CONTEXT_EVIDENCE_ABILITIES:
        raise ImageContextEvidenceContractViolation(
            "image_context_evidence.unknown_ability",
            "image context evidence ability_name is not supported",
        )
    if contract_version != IMAGE_CONTEXT_EVIDENCE_REQUEST_CONTRACT:
        raise ImageContextEvidenceContractViolation(
            "image_context_evidence.contract_mismatch",
            "image context evidence contract_version does not match ability_name",
        )
    if not isinstance(input_payload, dict):
        raise ImageContextEvidenceContractViolation(
            "image_context_evidence.invalid_input",
            "image context evidence input must be an object",
        )
    evidence_request = extract_image_context_evidence_request(input_payload)
    if str(evidence_request.get("contract_version") or contract_version) != (
        IMAGE_CONTEXT_EVIDENCE_REQUEST_CONTRACT
    ):
        raise ImageContextEvidenceContractViolation(
            "image_context_evidence.input_contract_mismatch",
            "image context evidence input contract_version does not match runtime contract",
        )
    forbidden_path = find_forbidden_image_context_evidence_field(input_payload)
    if forbidden_path:
        raise ImageContextEvidenceContractViolation(
            "image_context_evidence.write_or_secret_field_forbidden",
            "image context evidence input may not include provider secret or write/control "
            f"field '{forbidden_path}'",
        )

    items = evidence_request.get("items")
    if not isinstance(items, list) or not items:
        raise ImageContextEvidenceContractViolation(
            "image_context_evidence.items_required",
            "image context evidence requires at least one item",
        )
    if len(items) > MAX_IMAGE_CONTEXT_EVIDENCE_ITEMS:
        raise ImageContextEvidenceContractViolation(
            "image_context_evidence.too_many_items",
            f"image context evidence accepts at most {MAX_IMAGE_CONTEXT_EVIDENCE_ITEMS} items",
        )
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ImageContextEvidenceContractViolation(
                "image_context_evidence.invalid_item",
                f"image context evidence item {index} must be an object",
            )
        attachment_id = str(item.get("attachment_id") or "").strip()
        if not attachment_id:
            raise ImageContextEvidenceContractViolation(
                "image_context_evidence.attachment_id_required",
                f"image context evidence item {index} requires attachment_id",
            )
        source_url = str(item.get("source_url") or item.get("url") or "").strip()
        thumbnail_url = str(item.get("thumbnail_url") or "").strip()
        if not source_url and not thumbnail_url:
            raise ImageContextEvidenceContractViolation(
                "image_context_evidence.image_url_required",
                f"image context evidence item {index} requires source_url or thumbnail_url",
            )
        for field_name, url in (("source_url", source_url), ("thumbnail_url", thumbnail_url)):
            if url:
                _validate_public_image_url(url, field_name=field_name, item_index=index)


def extract_image_context_evidence_request(input_payload: dict[str, Any]) -> dict[str, Any]:
    nested = input_payload.get("image_context_evidence_request")
    if isinstance(nested, dict):
        return nested
    return input_payload


def find_forbidden_image_context_evidence_field(value: Any, *, path: str = "") -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").strip().lower()
            current_path = f"{path}.{normalized_key}" if path else normalized_key
            if normalized_key in FORBIDDEN_IMAGE_CONTEXT_EVIDENCE_KEYS:
                if normalized_key == "direct_wordpress_write" and item is False:
                    continue
                return current_path
            nested = find_forbidden_image_context_evidence_field(item, path=current_path)
            if nested:
                return nested
    if isinstance(value, list):
        for index, item in enumerate(value):
            nested = find_forbidden_image_context_evidence_field(item, path=f"{path}[{index}]")
            if nested:
                return nested
    return ""


def _validate_public_image_url(url: str, *, field_name: str, item_index: int) -> None:
    if len(url) > 2048:
        raise ImageContextEvidenceContractViolation(
            "image_context_evidence.image_url_too_long",
            f"image context evidence item {item_index} {field_name} is too long",
        )
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ImageContextEvidenceContractViolation(
            "image_context_evidence.image_url_invalid",
            f"image context evidence item {item_index} {field_name} must be an http(s) URL",
        )
