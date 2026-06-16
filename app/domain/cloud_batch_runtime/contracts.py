from __future__ import annotations

from typing import Any

CLOUD_BATCH_RUNTIME_TOOLBOX_ABILITY = "magick-ai-toolbox/analyze-nightly-content-batch"
CLOUD_BATCH_RUNTIME_CLOUD_ABILITY = "magick-ai-cloud/analyze-nightly-content-batch"
CLOUD_BATCH_RUNTIME_ABILITIES = frozenset(
    {CLOUD_BATCH_RUNTIME_TOOLBOX_ABILITY, CLOUD_BATCH_RUNTIME_CLOUD_ABILITY}
)
CLOUD_BATCH_RUNTIME_REQUEST_CONTRACT = "cloud_batch_runtime_request.v1"
CLOUD_BATCH_RUNTIME_RESULT_CONTRACT = "cloud_batch_runtime_result.v1"
CLOUD_BATCH_RUNTIME_EXECUTION_KIND = "nightly_site_inspection"
CLOUD_BATCH_RUNTIME_PROFILE_ID = "cloud-batch-runtime.managed"
CLOUD_BATCH_RUNTIME_ABILITY_FAMILY = "automation"
CLOUD_BATCH_RUNTIME_DATA_CLASSIFICATION = "internal"
NIGHTLY_SITE_INSPECTION_RESULT_CONTRACT = "nightly_site_inspection_result.v1"
NIGHTLY_SITE_INSPECTION_CORE_REVIEW_PLAN_CONTRACT = (
    "nightly_site_inspection_core_review_plan.v1"
)
NIGHTLY_SITE_INSPECTION_CORE_REVIEW_PLAN_ARTIFACT = "nightly_site_inspection_review_plan"
NIGHTLY_SITE_INSPECTION_CORE_REVIEW_PLAN_ABILITY = (
    "npcink-toolbox/build-nightly-inspection-review-plan"
)

MAX_CLOUD_BATCH_ITEMS = 50

FORBIDDEN_CLOUD_BATCH_KEYS = frozenset(
    {
        "api_key",
        "apply_decision",
        "apply_policy",
        "approval_decision",
        "approval_token",
        "callback_secret",
        "cloud_secret",
        "confirm_token",
        "cookie",
        "direct_publish",
        "direct_wordpress_write",
        "final_write_policy",
        "final_write_target",
        "headers",
        "metadata_patch",
        "nonce",
        "password",
        "publish",
        "replace_file",
        "secret",
        "set_post_content",
        "target_attachment_id",
        "update_attachment_metadata",
        "update_post",
        "wordpress_password",
        "wordpress_secret",
        "wordpress_write",
        "wordpress_write_policy",
        "wordpress_write_target",
        "write_confirmed",
        "write_control",
        "write_controls",
    }
)


class CloudBatchRuntimeContractViolation(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def validate_cloud_batch_runtime_contract(
    *,
    ability_name: str,
    contract_version: str,
    input_payload: dict[str, Any],
) -> None:
    if ability_name not in CLOUD_BATCH_RUNTIME_ABILITIES:
        raise CloudBatchRuntimeContractViolation(
            "cloud_batch_runtime.unknown_ability",
            "cloud batch runtime ability_name is not supported",
        )
    if contract_version != CLOUD_BATCH_RUNTIME_REQUEST_CONTRACT:
        raise CloudBatchRuntimeContractViolation(
            "cloud_batch_runtime.contract_mismatch",
            "cloud batch runtime contract_version does not match ability_name",
        )
    if not isinstance(input_payload, dict):
        raise CloudBatchRuntimeContractViolation(
            "cloud_batch_runtime.invalid_input",
            "cloud batch runtime input must be an object",
        )
    if (
        str(input_payload.get("contract_version") or contract_version)
        != CLOUD_BATCH_RUNTIME_REQUEST_CONTRACT
    ):
        raise CloudBatchRuntimeContractViolation(
            "cloud_batch_runtime.input_contract_mismatch",
            "cloud batch runtime input contract_version does not match runtime contract",
        )
    forbidden_path = find_forbidden_cloud_batch_runtime_field(input_payload)
    if forbidden_path:
        raise CloudBatchRuntimeContractViolation(
            "cloud_batch_runtime.write_or_secret_field_forbidden",
            "cloud batch runtime input may not include WordPress write/control "
            f"or secret field '{forbidden_path}'",
        )

    items = _candidate_items(input_payload)
    if not items:
        raise CloudBatchRuntimeContractViolation(
            "cloud_batch_runtime.items_required",
            "cloud batch runtime input requires at least one content item",
        )
    if len(items) > MAX_CLOUD_BATCH_ITEMS:
        raise CloudBatchRuntimeContractViolation(
            "cloud_batch_runtime.items_limit_exceeded",
            f"cloud batch runtime accepts at most {MAX_CLOUD_BATCH_ITEMS} items",
        )


def find_forbidden_cloud_batch_runtime_field(value: Any, *, path: str = "") -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").strip().lower()
            current_path = f"{path}.{normalized_key}" if path else normalized_key
            if normalized_key in FORBIDDEN_CLOUD_BATCH_KEYS:
                if normalized_key == "direct_wordpress_write" and item is False:
                    continue
                return current_path
            nested = find_forbidden_cloud_batch_runtime_field(item, path=current_path)
            if nested:
                return nested
    if isinstance(value, list):
        for index, item in enumerate(value):
            nested = find_forbidden_cloud_batch_runtime_field(item, path=f"{path}[{index}]")
            if nested:
                return nested
    return ""


def _candidate_items(input_payload: dict[str, Any]) -> list[Any]:
    items = input_payload.get("items")
    if isinstance(items, list):
        return items
    snapshot = input_payload.get("snapshot")
    if isinstance(snapshot, dict) and isinstance(snapshot.get("items"), list):
        return list(snapshot["items"])
    return []
