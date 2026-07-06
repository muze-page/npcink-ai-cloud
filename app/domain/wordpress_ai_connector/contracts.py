from __future__ import annotations

from typing import Any

WP_AI_CONNECTOR_ABILITY = "npcink-cloud/wp-ai-connector"
WP_AI_CONNECTOR_ABILITIES = frozenset({WP_AI_CONNECTOR_ABILITY})
WP_AI_CONNECTOR_CONTRACT = "wp_ai_connector_runtime.v1"
WP_AI_CONNECTOR_EXECUTION_KIND = "text"
WP_AI_CONNECTOR_ABILITY_FAMILY = "text"
WP_AI_CONNECTOR_DATA_CLASSIFICATION = "public_site_content"
WP_AI_CONNECTOR_RESULT_CONTRACT = "wp_ai_connector_result.v1"
WP_AI_CONNECTOR_MAX_PROMPT_CHARS = 12000
WP_AI_CONNECTOR_MAX_TIMEOUT_SECONDS = 60

WP_AI_CONNECTOR_ALLOWED_TASKS = frozenset(
    {
        "alt_text_suggest",
        "comment_moderation",
        "comment_reply_suggest",
        "content_classification",
        "content_rewrite",
        "content_summary",
        "excerpt_generation",
        "meta_description",
        "title_generation",
    }
)

WP_AI_CONNECTOR_FORBIDDEN_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "chat_id",
        "conversation_id",
        "cookie",
        "credentials",
        "function_call",
        "functions",
        "messages",
        "nonce",
        "password",
        "secret",
        "session_id",
        "stream",
        "thread_id",
        "tool_calls",
        "tools",
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
