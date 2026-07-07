from __future__ import annotations

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
    if task not in WP_AI_CONNECTOR_ALLOWED_TASKS:
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

    request = input_payload.get("request")
    if not isinstance(request, dict):
        raise WordPressAIConnectorContractViolation(
            "wp_ai_connector.request_required",
            "WordPress AI connector input requires a scene request object",
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
    if task == "alt_text_suggest":
        validate_alt_text_suggest_request(request)


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
