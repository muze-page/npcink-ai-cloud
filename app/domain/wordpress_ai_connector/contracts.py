from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

WP_AI_CONNECTOR_ABILITY = "npcink-cloud/wp-ai-connector"
WP_AI_CONNECTOR_ABILITIES = frozenset({WP_AI_CONNECTOR_ABILITY})
WP_AI_CONNECTOR_CONTRACT = "wp_ai_connector_runtime.v1"
WP_AI_CONNECTOR_EXECUTION_KIND = "text"
WP_AI_CONNECTOR_ABILITY_FAMILY = "text"
WP_AI_CONNECTOR_DATA_CLASSIFICATION = "public_site_content"
WP_AI_CONNECTOR_VISION_EXECUTION_KIND = "vision"
WP_AI_CONNECTOR_VISION_ABILITY_FAMILY = "vision"
WP_AI_CONNECTOR_VISION_DATA_CLASSIFICATION = "public_reference_media"
WP_AI_CONNECTOR_RESULT_CONTRACT = "wp_ai_connector_result.v1"
WP_AI_CONNECTOR_MAX_PROMPT_CHARS = 12000
WP_AI_CONNECTOR_MAX_TIMEOUT_SECONDS = 60
WP_AI_CONNECTOR_MAX_IMAGE_URL_CHARS = 2048
WP_AI_CONNECTOR_MAX_IMAGE_DATA_URL_CHARS = 900_000
WP_AI_CONNECTOR_SITE_KNOWLEDGE_REFERENCE_MODES_BY_TASK = {
    "title_generation": "site_title_style",
    "excerpt_generation": "site_excerpt_style",
    "meta_description": "site_meta_style",
    "content_summary": "site_summary_style",
    "content_classification": "site_taxonomy_history",
}
WP_AI_CONNECTOR_IMAGE_DATA_URL_PATTERN = re.compile(
    r"^data:(image/(?:gif|jpeg|png|webp))(?:;[^,]*)?;base64,([A-Za-z0-9+/=\r\n]+)$",
    re.IGNORECASE,
)
WP_AI_CONNECTOR_ALT_TEXT_IMAGE_MIME_TYPES = frozenset(
    {
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)

WP_AI_CONNECTOR_ALLOWED_TASKS = frozenset(
    {
        "alt_text_suggest",
        "article_audio_summary",
        "article_narration",
        "audio_summary_script",
        "comment_moderation",
        "comment_reply_suggest",
        "content_classification",
        "content_rewrite",
        "content_summary",
        "excerpt_generation",
        "image_generation",
        "meta_description",
        "title_generation",
    }
)

AI_TASK_CONTRACT = "ai_task_contract.v1"
AI_TASK_ALLOWED_FAMILIES = frozenset(
    {"generation", "classification", "transformation", "analysis"}
)
AI_TASK_ALLOWED_CONTEXTS = frozenset(
    {
        "current_content",
        "site_style_profile",
        "taxonomy_candidates",
        "none",
    }
)
AI_TASK_ALLOWED_CONSTRAINTS = frozenset(
    {
        "single_value",
        "source_grounded",
        "no_new_numbers",
        "json_object",
        "existing_terms_only",
    }
)
AI_TASK_MAX_OUTPUT_SCHEMA_BYTES = 12_000

WP_AI_CONNECTOR_FORBIDDEN_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "base64",
        "b64",
        "b64_json",
        "callback_secret",
        "chat_id",
        "conversation_id",
        "cookie",
        "credentials",
        "function_call",
        "functions",
        "headers",
        "image_base64",
        "image_data",
        "messages",
        "nonce",
        "password",
        "provider_key",
        "provider_secret",
        "secret",
        "session_id",
        "stream",
        "thread_id",
        "tool_calls",
        "tools",
        "update_attachment_metadata",
        "wordpress_write_policy",
        "wordpress_write_target",
        "write_control",
        "write_controls",
        "x_magick_signature",
        "x_npcink_signature",
    }
)


class WordPressAIConnectorContractViolation(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def validate_wordpress_ai_connector_runtime_contract(
    *,
    ability_name: str,
    contract_version: str,
    input_payload: dict[str, Any],
) -> None:
    if ability_name not in WP_AI_CONNECTOR_ABILITIES:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.unknown_ability",
            "WordPress AI connector ability_name is not supported",
        )
    if contract_version != WP_AI_CONNECTOR_CONTRACT:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.contract_mismatch",
            "WordPress AI connector contract_version does not match ability_name",
        )
    if not isinstance(input_payload, dict):
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.invalid_input",
            "WordPress AI connector input must be an object",
        )
    if str(input_payload.get("contract_version") or contract_version) != (
        WP_AI_CONNECTOR_CONTRACT
    ):
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.input_contract_mismatch",
            "WordPress AI connector input contract_version does not match runtime contract",
        )
    if str(input_payload.get("source_surface") or "") != "wordpress_ai_connector":
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.source_surface_required",
            "WordPress AI connector input must declare source_surface=wordpress_ai_connector",
        )
    if str(input_payload.get("connector_id") or "") != "npcink-cloud":
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.connector_id_required",
            "WordPress AI connector input must declare connector_id=npcink-cloud",
        )
    task = str(input_payload.get("task") or "").strip()
    request = input_payload.get("request")
    if not isinstance(request, dict):
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.request_required",
            "WordPress AI connector input requires a scene request object",
        )

    task_contract = request.get("task_contract")
    if task_contract is not None:
        validate_ai_task_contract(task_contract, task=task)
    elif task not in WP_AI_CONNECTOR_ALLOWED_TASKS:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.task_not_allowed",
            "WordPress AI connector task is not supported",
        )
    if str(input_payload.get("write_posture") or "") != "suggestion_only":
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.write_posture_required",
            "WordPress AI connector input must use suggestion_only write_posture",
        )
    if input_payload.get("direct_wordpress_write") is not False:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.direct_write_forbidden",
            "WordPress AI connector input must set direct_wordpress_write=false",
        )
    if input_payload.get("no_conversation") is not True:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.no_conversation_required",
            "WordPress AI connector input must set no_conversation=true",
        )

    forbidden_path = find_forbidden_wordpress_ai_connector_field(input_payload)
    if forbidden_path:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.chat_or_secret_field_forbidden",
            "WordPress AI connector input may not include generic chat, tool, stream, "
            f"credential, or signed-header field '{forbidden_path}'",
        )

    prompt = str(request.get("prompt") or "")
    if len(prompt) > WP_AI_CONNECTOR_MAX_PROMPT_CHARS:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.prompt_too_large",
            "WordPress AI connector prompt exceeds the scene runtime size limit",
        )
    validate_site_knowledge_reference(
        request,
        task=task,
        task_contract=task_contract if isinstance(task_contract, dict) else {},
    )
    if task == "alt_text_suggest":
        validate_alt_text_suggest_request(request)


def validate_ai_task_contract(value: Any, *, task: str) -> None:
    if not isinstance(value, dict):
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.ai_task_contract_invalid",
            "AI task contract must be an object",
        )
    allowed_fields = {
        "contract_version",
        "ability_name",
        "task",
        "task_family",
        "context_requirements",
        "constraints",
        "output_schema",
        "write_posture",
    }
    if set(value) - allowed_fields:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.ai_task_contract_fields_forbidden",
            "AI task contract contains unsupported fields",
        )
    if str(value.get("contract_version") or "") != AI_TASK_CONTRACT:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.ai_task_contract_version_invalid",
            "AI task contract requires ai_task_contract.v1",
        )
    ability_name = str(value.get("ability_name") or "").strip()
    projected_task = str(value.get("task") or "").strip()
    family = str(value.get("task_family") or "").strip()
    valid_ability_name = re.fullmatch(r"[a-z0-9_-]+/[a-z0-9_-]+", ability_name) is not None
    valid_task = re.fullmatch(r"[a-z0-9_]{1,64}", projected_task) is not None
    if (
        not valid_ability_name
        or not valid_task
        or projected_task != task
        or family not in AI_TASK_ALLOWED_FAMILIES
    ):
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.ai_task_contract_identity_invalid",
            "AI task contract identity does not match the registered task projection",
        )
    if str(value.get("write_posture") or "") != "suggestion_only":
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.ai_task_contract_write_posture_invalid",
            "AI task contract must remain suggestion_only",
        )
    contexts = value.get("context_requirements")
    constraints = value.get("constraints")
    if (
        not isinstance(contexts, list)
        or not all(isinstance(item, str) and item in AI_TASK_ALLOWED_CONTEXTS for item in contexts)
        or not isinstance(constraints, list)
        or not all(
            isinstance(item, str) and item in AI_TASK_ALLOWED_CONSTRAINTS
            for item in constraints
        )
    ):
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.ai_task_contract_vocabulary_invalid",
            "AI task contract contains an unsupported context requirement or constraint",
        )
    if "none" in contexts and len(contexts) != 1:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.ai_task_contract_none_invalid",
            "AI task contract context none cannot be combined with other values",
        )
    output_schema = value.get("output_schema")
    if not isinstance(output_schema, dict):
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.ai_task_contract_output_schema_invalid",
            "AI task contract requires an Ability-owned output schema",
        )
    try:
        encoded_schema = json.dumps(output_schema, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.ai_task_contract_output_schema_invalid",
            "AI task contract output schema must be JSON serializable",
        ) from error
    if len(encoded_schema.encode("utf-8")) > AI_TASK_MAX_OUTPUT_SCHEMA_BYTES:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.ai_task_contract_output_schema_too_large",
            "AI task contract output schema exceeds the runtime projection limit",
        )


def resolve_site_knowledge_reference_mode(
    *,
    task: str,
    task_contract: dict[str, Any] | None = None,
) -> str:
    expected_mode = WP_AI_CONNECTOR_SITE_KNOWLEDGE_REFERENCE_MODES_BY_TASK.get(task, "")
    if expected_mode or not task_contract:
        return expected_mode
    contexts = task_contract.get("context_requirements")
    contexts = contexts if isinstance(contexts, list) else []
    if "taxonomy_candidates" in contexts:
        return "site_taxonomy_history"
    if "site_style_profile" in contexts:
        return (
            "site_title_style"
            if str(task_contract.get("task_family") or "") == "generation"
            else "site_excerpt_style"
        )
    return ""


def validate_site_knowledge_reference(
    request: dict[str, Any],
    *,
    task: str,
    task_contract: dict[str, Any] | None = None,
) -> None:
    reference = request.get("site_knowledge_reference")
    if reference is None:
        return
    if not isinstance(reference, dict):
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.site_knowledge_reference_invalid",
            "WordPress AI connector site_knowledge_reference must be an object",
        )

    unknown_fields = set(reference) - {"enabled", "mode"}
    if unknown_fields:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.site_knowledge_reference_fields_forbidden",
            "WordPress AI connector site_knowledge_reference accepts only enabled and mode",
        )

    enabled = reference.get("enabled")
    if not isinstance(enabled, bool):
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.site_knowledge_reference_enabled_invalid",
            "WordPress AI connector site_knowledge_reference.enabled must be boolean",
        )
    expected_mode = resolve_site_knowledge_reference_mode(
        task=task,
        task_contract=task_contract,
    )
    mode = str(reference.get("mode") or expected_mode or "site_title_style")
    if enabled and not expected_mode:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.site_knowledge_reference_task_not_allowed",
            "WordPress AI connector Site Knowledge reference is not supported for this task",
        )
    if (expected_mode and mode != expected_mode) or (
        not expected_mode and mode != "site_title_style"
    ):
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.site_knowledge_reference_mode_invalid",
            "WordPress AI connector site_knowledge_reference.mode is not supported",
        )


def find_forbidden_wordpress_ai_connector_field(value: Any, *, path: str = "") -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").strip().lower().replace("-", "_")
            current_path = f"{path}.{normalized_key}" if path else normalized_key
            if normalized_key in WP_AI_CONNECTOR_FORBIDDEN_KEYS:
                return current_path
            nested = find_forbidden_wordpress_ai_connector_field(item, path=current_path)
            if nested:
                return nested
    if isinstance(value, list):
        for index, item in enumerate(value):
            nested = find_forbidden_wordpress_ai_connector_field(item, path=f"{path}[{index}]")
            if nested:
                return nested
    return ""


def validate_alt_text_suggest_request(request: dict[str, Any]) -> None:
    image_url = str(request.get("image_url") or "").strip()
    thumbnail_url = str(request.get("thumbnail_url") or "").strip()
    if not image_url and not thumbnail_url:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.alt_text_image_required",
            "WordPress AI alt text suggestions require image_url or thumbnail_url",
        )

    for field_name, url in (("image_url", image_url), ("thumbnail_url", thumbnail_url)):
        if url:
            validate_alt_text_image_url(url, field_name=field_name)

    mime_type = str(request.get("mime_type") or "").split(";", 1)[0].strip().lower()
    if mime_type and mime_type not in WP_AI_CONNECTOR_ALT_TEXT_IMAGE_MIME_TYPES:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.alt_text_mime_type_not_allowed",
            "WordPress AI alt text suggestions require a supported image MIME type",
        )


def validate_alt_text_image_url(url: str, *, field_name: str) -> None:
    if url.lower().startswith("data:"):
        validate_alt_text_image_data_url(url, field_name=field_name)
        return
    if len(url) > WP_AI_CONNECTOR_MAX_IMAGE_URL_CHARS:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.alt_text_image_url_too_long",
            f"WordPress AI alt text {field_name} is too long",
        )
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.alt_text_image_url_invalid",
            f"WordPress AI alt text {field_name} must be an http(s) URL or image data URL",
        )


def validate_alt_text_image_data_url(url: str, *, field_name: str) -> None:
    if len(url) > WP_AI_CONNECTOR_MAX_IMAGE_DATA_URL_CHARS:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.alt_text_image_data_url_too_long",
            f"WordPress AI alt text {field_name} data URL is too long",
        )
    match = WP_AI_CONNECTOR_IMAGE_DATA_URL_PATTERN.match(url)
    if match is None:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.alt_text_image_url_invalid",
            f"WordPress AI alt text {field_name} must be an http(s) URL or image data URL",
        )
    mime_type = match.group(1).lower()
    if mime_type not in WP_AI_CONNECTOR_ALT_TEXT_IMAGE_MIME_TYPES:
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.alt_text_mime_type_not_allowed",
            "WordPress AI alt text suggestions require a supported image MIME type",
        )
