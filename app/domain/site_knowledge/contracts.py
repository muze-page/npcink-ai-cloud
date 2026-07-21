from __future__ import annotations

from typing import Any

SITE_KNOWLEDGE_SEARCH_ABILITY = "npcink-cloud/site-knowledge-search"
SITE_KNOWLEDGE_STATUS_ABILITY = "npcink-cloud/site-knowledge-status"
SITE_KNOWLEDGE_SYNC_ABILITY = "npcink-cloud/site-knowledge-sync"

SITE_KNOWLEDGE_ABILITIES = frozenset(
    {
        SITE_KNOWLEDGE_SEARCH_ABILITY,
        SITE_KNOWLEDGE_STATUS_ABILITY,
        SITE_KNOWLEDGE_SYNC_ABILITY,
    }
)

SITE_KNOWLEDGE_CONTRACTS = {
    SITE_KNOWLEDGE_SEARCH_ABILITY: "site_knowledge_search.v1",
    SITE_KNOWLEDGE_STATUS_ABILITY: "site_knowledge_status.v1",
    SITE_KNOWLEDGE_SYNC_ABILITY: "site_knowledge_sync.v1",
}

SITE_KNOWLEDGE_PROFILE_ID = "site-knowledge.managed"
SITE_KNOWLEDGE_EXECUTION_KIND = "knowledge"
SITE_KNOWLEDGE_ABILITY_FAMILY = "knowledge"
SITE_KNOWLEDGE_DATA_CLASSIFICATION = "public_site_content"

ALLOWED_SEARCH_INTENTS = frozenset(
    {
        "site_search",
        "related_content",
        "writing_context",
        "internal_links",
        "refresh_suggestions",
        "image_context",
        "faq_candidates",
        "content_gap_analysis",
        "duplicate_check",
        "writing_support_plan",
    }
)
ALLOWED_RESULT_GRANULARITIES = frozenset({"chunk", "document"})
ALLOWED_SYNC_MODES = frozenset({"refresh", "rebuild", "delete"})
PUBLIC_POST_STATUSES = frozenset({"publish"})
PUBLIC_POST_TYPES = frozenset({"post", "page"})
PUBLIC_COMMENT_STATUSES = frozenset({"approved", "approve", "1"})
PUBLIC_SOURCE_TYPES = frozenset({"post", "page", "comment"})

FORBIDDEN_WRITE_KEYS = frozenset(
    {
        "apply_policy",
        "callback_secret",
        "cloud_secret",
        "confirm_token",
        "direct_publish",
        "direct_wordpress_write",
        "final_write_policy",
        "final_write_target",
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


class SiteKnowledgeContractViolation(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def validate_site_knowledge_runtime_contract(
    *,
    ability_name: str,
    contract_version: str,
    input_payload: dict[str, Any],
) -> None:
    expected_contract = SITE_KNOWLEDGE_CONTRACTS.get(ability_name)
    if expected_contract is None:
        raise SiteKnowledgeContractViolation(
            "site_knowledge.unknown_ability",
            "site knowledge ability_name is not supported",
        )
    if contract_version != expected_contract:
        raise SiteKnowledgeContractViolation(
            "site_knowledge.contract_mismatch",
            "site knowledge contract_version does not match ability_name",
        )
    if not isinstance(input_payload, dict):
        raise SiteKnowledgeContractViolation(
            "site_knowledge.invalid_input",
            "site knowledge input must be an object",
        )
    if str(input_payload.get("contract_version") or contract_version) != expected_contract:
        raise SiteKnowledgeContractViolation(
            "site_knowledge.input_contract_mismatch",
            "site knowledge input contract_version does not match runtime contract",
        )
    if str(input_payload.get("write_posture") or "") != "suggestion_only":
        raise SiteKnowledgeContractViolation(
            "site_knowledge.write_posture_required",
            "site knowledge input must use suggestion_only write_posture",
        )
    result_granularity = input_payload.get("result_granularity")
    if result_granularity is not None and str(result_granularity).strip() not in (
        ALLOWED_RESULT_GRANULARITIES
    ):
        raise SiteKnowledgeContractViolation(
            "site_knowledge.result_granularity_unsupported",
            "site knowledge result_granularity must be chunk or document",
        )
    forbidden_path = find_forbidden_write_field(input_payload)
    if forbidden_path:
        raise SiteKnowledgeContractViolation(
            "site_knowledge.write_field_forbidden",
            f"site knowledge input may not include write/control field '{forbidden_path}'",
        )


def find_forbidden_write_field(value: Any, *, path: str = "") -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").strip().lower()
            current_path = f"{path}.{normalized_key}" if path else normalized_key
            if normalized_key in FORBIDDEN_WRITE_KEYS:
                if normalized_key == "direct_wordpress_write" and item is False:
                    continue
                return current_path
            nested = find_forbidden_write_field(item, path=current_path)
            if nested:
                return nested
    if isinstance(value, list):
        for index, item in enumerate(value):
            nested = find_forbidden_write_field(item, path=f"{path}[{index}]")
            if nested:
                return nested
    return ""


def coerce_positive_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return max(1, min(maximum, normalized))
