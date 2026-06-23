from __future__ import annotations

from typing import Any

SITE_OPS_ANALYSIS_CLOUD_ABILITY = "npcink-cloud/analyze-site-ops"
SITE_OPS_ANALYSIS_TOOLBOX_ABILITY = "npcink-toolbox/analyze-site-ops"
SITE_OPS_ANALYSIS_ABILITIES = frozenset(
    {SITE_OPS_ANALYSIS_CLOUD_ABILITY, SITE_OPS_ANALYSIS_TOOLBOX_ABILITY}
)
SITE_OPS_ANALYSIS_REQUEST_CONTRACT = "site_ops_cloud_analysis_request.v1"
SITE_OPS_ANALYSIS_RESULT_CONTRACT = "site_ops_cloud_analysis_result.v1"
SITE_OPS_ANALYSIS_EXECUTION_KIND = "site_ops_cloud_analysis"
SITE_OPS_ANALYSIS_PROFILE_ID = "site-ops-analysis.managed"
SITE_OPS_ANALYSIS_ABILITY_FAMILY = "automation"
SITE_OPS_ANALYSIS_DATA_CLASSIFICATION = "public_site_aggregate"

FORBIDDEN_SITE_OPS_ANALYSIS_KEYS = frozenset(
    {
        "apply_decision",
        "apply_policy",
        "approval_decision",
        "comment_agent",
        "comment_author_email",
        "comment_author_ip",
        "comment_author_ip_address",
        "comment_content",
        "confirm_token",
        "create_proposal",
        "direct_publish",
        "direct_wordpress_write",
        "final_write_policy",
        "final_write_target",
        "ip_address",
        "private_content",
        "provider_secret",
        "request_log",
        "schedule_instruction",
        "update_post",
        "user_agent",
        "wordpress_password",
        "wordpress_secret",
        "wordpress_write_action",
        "wordpress_write_policy",
        "wordpress_write_target",
        "write_confirmed",
        "write_control",
        "write_controls",
    }
)


class SiteOpsAnalysisContractViolation(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def validate_site_ops_analysis_runtime_contract(
    *,
    ability_name: str,
    contract_version: str,
    input_payload: dict[str, Any],
) -> None:
    if ability_name not in SITE_OPS_ANALYSIS_ABILITIES:
        raise SiteOpsAnalysisContractViolation(
            "site_ops_analysis.unknown_ability",
            "site ops analysis ability_name is not supported",
        )
    if contract_version != SITE_OPS_ANALYSIS_REQUEST_CONTRACT:
        raise SiteOpsAnalysisContractViolation(
            "site_ops_analysis.contract_mismatch",
            "site ops analysis contract_version does not match ability_name",
        )
    if not isinstance(input_payload, dict):
        raise SiteOpsAnalysisContractViolation(
            "site_ops_analysis.invalid_input",
            "site ops analysis input must be an object",
        )
    if str(input_payload.get("contract_version") or contract_version) != (
        SITE_OPS_ANALYSIS_REQUEST_CONTRACT
    ):
        raise SiteOpsAnalysisContractViolation(
            "site_ops_analysis.input_contract_mismatch",
            "site ops analysis input contract_version does not match runtime contract",
        )
    if str(input_payload.get("expected_result_contract") or "") not in {
        "",
        SITE_OPS_ANALYSIS_RESULT_CONTRACT,
    }:
        raise SiteOpsAnalysisContractViolation(
            "site_ops_analysis.result_contract_mismatch",
            "site ops analysis expected_result_contract is not supported",
        )
    if str(input_payload.get("write_posture") or "") != "suggestion_only":
        raise SiteOpsAnalysisContractViolation(
            "site_ops_analysis.write_posture_required",
            "site ops analysis request must declare suggestion_only write posture",
        )
    if input_payload.get("direct_wordpress_write") is not False:
        raise SiteOpsAnalysisContractViolation(
            "site_ops_analysis.direct_write_forbidden",
            "site ops analysis request must disable direct WordPress writes",
        )
    if input_payload.get("core_proposal_created") is not False:
        raise SiteOpsAnalysisContractViolation(
            "site_ops_analysis.proposal_creation_forbidden",
            "site ops analysis request must not create Core proposals",
        )
    input_object = input_payload.get("input")
    if not isinstance(input_object, dict):
        raise SiteOpsAnalysisContractViolation(
            "site_ops_analysis.input_object_required",
            "site ops analysis request input must include an object",
        )
    if not isinstance(input_object.get("sample_summaries"), dict):
        raise SiteOpsAnalysisContractViolation(
            "site_ops_analysis.sample_summaries_required",
            "site ops analysis request input must include sample_summaries",
        )
    if not isinstance(input_object.get("local_findings"), list):
        raise SiteOpsAnalysisContractViolation(
            "site_ops_analysis.local_findings_required",
            "site ops analysis request input must include local_findings",
        )
    forbidden_path = find_forbidden_site_ops_analysis_field(input_payload)
    if forbidden_path:
        raise SiteOpsAnalysisContractViolation(
            "site_ops_analysis.private_or_write_field_forbidden",
            "site ops analysis input may not include private comment, provider "
            f"secret, local scheduler, or WordPress write field '{forbidden_path}'",
        )


def find_forbidden_site_ops_analysis_field(value: Any, *, path: str = "") -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").strip().lower()
            current_path = f"{path}.{normalized_key}" if path else normalized_key
            if normalized_key in FORBIDDEN_SITE_OPS_ANALYSIS_KEYS:
                if normalized_key == "direct_wordpress_write" and item is False:
                    continue
                return current_path
            nested = find_forbidden_site_ops_analysis_field(item, path=current_path)
            if nested:
                return nested
    if isinstance(value, list):
        for index, item in enumerate(value):
            nested = find_forbidden_site_ops_analysis_field(item, path=f"{path}[{index}]")
            if nested:
                return nested
    return ""
