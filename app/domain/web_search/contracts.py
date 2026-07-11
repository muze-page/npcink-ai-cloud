from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit

WEB_SEARCH_ABILITY = "npcink-cloud/web-search"
NPCINK_WEB_SEARCH_ABILITY = "npcink-cloud/web-search"
WEB_SEARCH_ABILITIES = frozenset({WEB_SEARCH_ABILITY, NPCINK_WEB_SEARCH_ABILITY})
WEB_SEARCH_CONTRACT = "web_search.v1"
SEARCH_EVIDENCE_PACK_CONTRACT = "search_evidence_pack.v1"
SOURCE_EVIDENCE_CONTRACT = "source_evidence.v1"
TOPIC_CANDIDATE_CONTRACT = "topic_candidate.v1"
GROUNDED_ANSWER_CONTRACT = "grounded_answer.v1"
SOURCE_EXTRACTION_PREVIEW_CONTRACT = "source_extraction_preview.v1"
ATOMIC_OUTPUT_CONTRACTS = frozenset(
    {
        SOURCE_EVIDENCE_CONTRACT,
        TOPIC_CANDIDATE_CONTRACT,
        GROUNDED_ANSWER_CONTRACT,
    }
)
WEB_SEARCH_PROFILE_ID = "web-search.managed"
WEB_SEARCH_EXECUTION_KIND = "web_search"
WEB_SEARCH_ABILITY_FAMILY = "knowledge"
WEB_SEARCH_DATA_CLASSIFICATION = "public"

ALLOWED_WEB_SEARCH_INTENTS = frozenset(
    {
        "general_research",
        "article_background",
        "fact_check",
        "news",
        "writing_context",
        "competitor_research",
        "pricing_snapshot",
        "product_comparison",
        "source_discovery",
        "source_extraction_preview",
        "external_links",
        "zhihu_global_search",
        "zhihu_research",
        "zhihu_hot_topics",
        "zhida_simple",
        "zhida_deep",
        "zhida_deepsearch",
    }
)

FORBIDDEN_WEB_SEARCH_KEYS = frozenset(
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


class WebSearchContractViolation(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def validate_web_search_runtime_contract(
    *,
    ability_name: str,
    contract_version: str,
    input_payload: dict[str, Any],
) -> None:
    if ability_name not in WEB_SEARCH_ABILITIES:
        raise WebSearchContractViolation(
            "web_search.unknown_ability",
            "web search ability_name is not supported",
        )
    if contract_version != WEB_SEARCH_CONTRACT:
        raise WebSearchContractViolation(
            "web_search.contract_mismatch",
            "web search contract_version does not match ability_name",
        )
    if not isinstance(input_payload, dict):
        raise WebSearchContractViolation(
            "web_search.invalid_input",
            "web search input must be an object",
        )
    if str(input_payload.get("contract_version") or contract_version) != WEB_SEARCH_CONTRACT:
        raise WebSearchContractViolation(
            "web_search.input_contract_mismatch",
            "web search input contract_version does not match runtime contract",
        )
    if str(input_payload.get("write_posture") or "") != "suggestion_only":
        raise WebSearchContractViolation(
            "web_search.write_posture_required",
            "web search input must use suggestion_only write_posture",
        )
    forbidden_path = find_forbidden_web_search_field(input_payload)
    if forbidden_path:
        raise WebSearchContractViolation(
            "web_search.write_or_secret_field_forbidden",
            "web search input may not include provider secret or write/control "
            f"field '{forbidden_path}'",
        )
    if str(input_payload.get("intent") or "").strip() == "source_extraction_preview":
        source_url = validate_public_source_url(
            input_payload.get("source_url") or input_payload.get("query"),
        )
        query_url = validate_public_source_url(input_payload.get("query"))
        if query_url.rstrip("/") != source_url.rstrip("/"):
            raise WebSearchContractViolation(
                "web_search.source_query_mismatch",
                "source extraction query and source_url must identify the same URL",
            )


def validate_public_source_url(value: Any) -> str:
    source_url = str(value or "").strip()
    if len(source_url) > 2048:
        raise WebSearchContractViolation(
            "web_search.source_url_too_long",
            "source extraction URL exceeds the accepted length",
        )
    try:
        parsed = urlsplit(source_url)
    except ValueError as error:
        raise WebSearchContractViolation(
            "web_search.source_url_invalid",
            "source extraction requires one valid public HTTP or HTTPS URL",
        ) from error
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise WebSearchContractViolation(
            "web_search.source_url_invalid",
            "source extraction requires one public HTTP or HTTPS URL",
        )
    if parsed.username or parsed.password:
        raise WebSearchContractViolation(
            "web_search.source_url_credentials_forbidden",
            "source extraction URL may not contain credentials",
        )

    host = str(parsed.hostname or "").strip().lower().rstrip(".")
    blocked_suffixes = (".localhost", ".local", ".test")
    if host == "localhost" or host.endswith(blocked_suffixes):
        raise WebSearchContractViolation(
            "web_search.source_url_not_public",
            "source extraction URL must use a public hostname",
        )
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is None and re.fullmatch(r"[0-9.]+", host):
        raise WebSearchContractViolation(
            "web_search.source_url_not_public",
            "source extraction URL may not use an alternate numeric IP address",
        )
    if address is None and "." not in host:
        raise WebSearchContractViolation(
            "web_search.source_url_not_public",
            "source extraction URL must use a public hostname",
        )
    if address is not None and not address.is_global:
        raise WebSearchContractViolation(
            "web_search.source_url_not_public",
            "source extraction URL may not use a private or reserved IP address",
        )
    return source_url


def find_forbidden_web_search_field(value: Any, *, path: str = "") -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").strip().lower()
            current_path = f"{path}.{normalized_key}" if path else normalized_key
            if normalized_key in FORBIDDEN_WEB_SEARCH_KEYS:
                if normalized_key == "direct_wordpress_write" and item is False:
                    continue
                return current_path
            nested = find_forbidden_web_search_field(item, path=current_path)
            if nested:
                return nested
    if isinstance(value, list):
        for index, item in enumerate(value):
            nested = find_forbidden_web_search_field(item, path=f"{path}[{index}]")
            if nested:
                return nested
    return ""


def coerce_positive_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return max(1, min(maximum, normalized))
