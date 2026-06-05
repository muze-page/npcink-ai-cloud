from __future__ import annotations

from typing import Any

MEDIA_BATCH_PLAN_CLOUD_ABILITY = "magick-ai-cloud/plan-media-derivative-batch"
MEDIA_BATCH_PLAN_TOOLBOX_ABILITY = "magick-ai-toolbox/plan-media-derivative-batch"
MEDIA_BATCH_PLAN_ABILITIES = frozenset(
    {MEDIA_BATCH_PLAN_CLOUD_ABILITY, MEDIA_BATCH_PLAN_TOOLBOX_ABILITY}
)
MEDIA_BATCH_PLAN_REQUEST_CONTRACT = "media_derivative_batch_plan_request.v1"
MEDIA_BATCH_PLAN_OUTPUT_CONTRACT = "media_derivative_batch_plan.v1"
MEDIA_BATCH_PLAN_EXECUTION_KIND = "media_derivative_batch_plan"
MEDIA_BATCH_PLAN_PROFILE_ID = "media-derivative-batch-plan.managed"
MEDIA_BATCH_PLAN_ABILITY_FAMILY = "vision"
MEDIA_BATCH_PLAN_DATA_CLASSIFICATION = "internal"

FORBIDDEN_MEDIA_BATCH_PLAN_KEYS = frozenset(
    {
        "apply_decision",
        "apply_policy",
        "approval_decision",
        "confirm_token",
        "direct_publish",
        "direct_wordpress_write",
        "final_write_policy",
        "final_write_target",
        "metadata_patch",
        "replace_file",
        "target_attachment_id",
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


class MediaBatchPlanContractViolation(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def validate_media_batch_plan_runtime_contract(
    *,
    ability_name: str,
    contract_version: str,
    input_payload: dict[str, Any],
) -> None:
    if ability_name not in MEDIA_BATCH_PLAN_ABILITIES:
        raise MediaBatchPlanContractViolation(
            "media_batch_plan.unknown_ability",
            "media batch plan ability_name is not supported",
        )
    if contract_version != MEDIA_BATCH_PLAN_REQUEST_CONTRACT:
        raise MediaBatchPlanContractViolation(
            "media_batch_plan.contract_mismatch",
            "media batch plan contract_version does not match ability_name",
        )
    if not isinstance(input_payload, dict):
        raise MediaBatchPlanContractViolation(
            "media_batch_plan.invalid_input",
            "media batch plan input must be an object",
        )
    if (
        str(input_payload.get("contract_version") or contract_version)
        != MEDIA_BATCH_PLAN_REQUEST_CONTRACT
    ):
        raise MediaBatchPlanContractViolation(
            "media_batch_plan.input_contract_mismatch",
            "media batch plan input contract_version does not match runtime contract",
        )
    forbidden_path = find_forbidden_media_batch_plan_field(input_payload)
    if forbidden_path:
        raise MediaBatchPlanContractViolation(
            "media_batch_plan.write_field_forbidden",
            "media batch plan input may not include WordPress write/control "
            f"field '{forbidden_path}'",
        )
    user_request = str(
        input_payload.get("user_request")
        or input_payload.get("intent_text")
        or input_payload.get("prompt")
        or ""
    ).strip()
    if not user_request:
        raise MediaBatchPlanContractViolation(
            "media_batch_plan.user_request_required",
            "media batch plan user_request is required",
        )
    if len(user_request) > 2000:
        raise MediaBatchPlanContractViolation(
            "media_batch_plan.user_request_too_long",
            "media batch plan user_request must be 2000 characters or fewer",
        )


def find_forbidden_media_batch_plan_field(value: Any, *, path: str = "") -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").strip().lower()
            current_path = f"{path}.{normalized_key}" if path else normalized_key
            if normalized_key in FORBIDDEN_MEDIA_BATCH_PLAN_KEYS:
                if normalized_key == "direct_wordpress_write" and item is False:
                    continue
                return current_path
            nested = find_forbidden_media_batch_plan_field(item, path=current_path)
            if nested:
                return nested
    if isinstance(value, list):
        for index, item in enumerate(value):
            nested = find_forbidden_media_batch_plan_field(item, path=f"{path}[{index}]")
            if nested:
                return nested
    return ""
