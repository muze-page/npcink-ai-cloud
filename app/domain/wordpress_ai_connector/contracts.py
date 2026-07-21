from __future__ import annotations

import json
import re
from typing import Any

WORDPRESS_OPERATION_CONTRACT = "wordpress_operation.v1"
WORDPRESS_OPERATION_FIELDS = frozenset({"contract_version", "task", "request"})
WP_AI_CONNECTOR_EXECUTION_KIND = "text"
WP_AI_CONNECTOR_ABILITY_FAMILY = "text"
WP_AI_CONNECTOR_DATA_CLASSIFICATION = "public_site_content"
WP_AI_CONNECTOR_VISION_EXECUTION_KIND = "vision"
WP_AI_CONNECTOR_VISION_ABILITY_FAMILY = "vision"
WP_AI_CONNECTOR_VISION_DATA_CLASSIFICATION = "internal"
WP_AI_CONNECTOR_MAX_PROMPT_CHARS = 12000
WP_AI_CONNECTOR_MAX_SOURCE_TEXT_CHARS = WP_AI_CONNECTOR_MAX_PROMPT_CHARS
WP_AI_CONNECTOR_MAX_SYSTEM_INSTRUCTION_CHARS = WP_AI_CONNECTOR_MAX_PROMPT_CHARS
WP_AI_CONNECTOR_MAX_TIMEOUT_SECONDS = 60
WP_AI_CONNECTOR_SOURCE_ARTIFACT_ID_CHARS = 36
WP_AI_CONNECTOR_SITE_KNOWLEDGE_REFERENCE_MODES_BY_TASK = {
    "title_generation": "site_title_style",
    "excerpt_generation": "site_excerpt_style",
    "meta_description": "site_meta_style",
    "content_summary": "site_summary_style",
    "content_classification": "site_taxonomy_history",
}
WP_AI_CONNECTOR_SOURCE_ARTIFACT_ID_PATTERN = re.compile(r"^art_[0-9a-f]{32}$")
WP_AI_CONNECTOR_ALT_TEXT_REQUEST_FIELDS = frozenset(
    {
        "existing_alt",
        "existing_caption",
        "filename",
        "locale",
        "max_tokens",
        "prompt",
        "source_artifact_id",
        "title",
    }
)
WP_AI_CONNECTOR_ALT_TEXT_OPTIONAL_STRING_LIMITS = {
    "filename": 160,
    "title": 160,
    "existing_alt": 240,
    "existing_caption": 240,
    "locale": 32,
}
WP_AI_CONNECTOR_INLINE_MEDIA_PATTERN = re.compile(
    r"data:image/[a-z0-9.+-]+(?:;[^,]*)?;base64,",
    re.IGNORECASE,
)
WP_AI_CONNECTOR_B64_JSON_PATTERN = re.compile(
    r"\bb64[\s_-]*json\s*[:=]",
    re.IGNORECASE,
)
WP_AI_CONNECTOR_LONG_BASE64_PATTERN = re.compile(
    r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{128,}={0,2}(?![A-Za-z0-9+/=])"
)
WP_AI_CONNECTOR_IMAGE_BASE64_MAGIC_PATTERN = re.compile(
    r"(?<![A-Za-z0-9+/])(?:iVBORw0KGgo|/9j/|UklGR)[A-Za-z0-9+/=]*"
)

WP_AI_CONNECTOR_ALLOWED_TASKS = frozenset(
    {
        "alt_text_suggest",
        "audio_summary_script",
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
WP_AI_CONNECTOR_SOURCE_TEXT_TASKS = frozenset(
    {
        "content_rewrite",
        "content_summary",
        "title_generation",
    }
)

WORDPRESS_OPERATION_REQUEST_CONTROL_FIELDS = frozenset(
    {
        "source_surface",
        "connector_id",
        "connector_version",
        "site_url",
        "platform_kind",
        "object_ref",
        "operation_contract",
        "expected_response_contract",
        "suggestion_only",
        "write_posture",
        "no_conversation",
        "direct_wordpress_write",
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
        "direct_wordpress_write",
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


class WordPressOperationContractViolation(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def validate_wordpress_operation_contract(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WordPressOperationContractViolation(
            "wordpress_operation.invalid",
            "WordPress operation contract must be an object",
        )
    if set(value) != WORDPRESS_OPERATION_FIELDS:
        raise WordPressOperationContractViolation(
            "wordpress_operation.fields_invalid",
            "WordPress operation contract requires exactly contract_version, task, and request",
        )
    if str(value.get("contract_version") or "") != WORDPRESS_OPERATION_CONTRACT:
        raise WordPressOperationContractViolation(
            "wordpress_operation.contract_mismatch",
            "WordPress operation contract_version is not supported",
        )

    task = str(value.get("task") or "").strip()
    request = value.get("request")
    if not isinstance(request, dict):
        raise WordPressOperationContractViolation(
            "wordpress_operation.request_required",
            "WordPress operation contract requires a scene request object",
        )
    if task == "alt_text_suggest":
        request = validate_alt_text_suggest_request(request)

    task_contract = request.get("task_contract")
    if task_contract is not None:
        validate_ai_task_contract(task_contract, task=task)
    elif task not in WP_AI_CONNECTOR_ALLOWED_TASKS:
        raise WordPressOperationContractViolation(
            "wordpress_operation.task_not_allowed",
            "WordPress operation task is not supported",
        )

    forbidden_control_path = find_forbidden_wordpress_operation_control_field(
        request
    )
    if forbidden_control_path:
        raise WordPressOperationContractViolation(
            "wordpress_operation.control_field_forbidden",
            "WordPress operation request may not include connector envelope, result, "
            f"or write-control field '{forbidden_control_path}'",
        )

    forbidden_path = find_forbidden_wordpress_ai_connector_field(value)
    if forbidden_path:
        raise WordPressOperationContractViolation(
            "wordpress_operation.chat_or_secret_field_forbidden",
            "WordPress operation contract may not include generic chat, tool, stream, "
            f"credential, or signed-header field '{forbidden_path}'",
        )

    normalized_request = dict(request)
    if task in WP_AI_CONNECTOR_SOURCE_TEXT_TASKS:
        normalized_request["source_text"] = validate_source_text_request(request)
        if "system_instruction" in request:
            normalized_request["system_instruction"] = validate_system_instruction(
                request
            )
    else:
        prompt = str(request.get("prompt") or "")
        if len(prompt) > WP_AI_CONNECTOR_MAX_PROMPT_CHARS:
            raise WordPressOperationContractViolation(
                "wordpress_operation.prompt_too_large",
                "WordPress operation prompt exceeds the scene runtime size limit",
            )
    validate_site_knowledge_reference(
        normalized_request,
        task=task,
        task_contract=task_contract if isinstance(task_contract, dict) else {},
    )
    return {
        "contract_version": WORDPRESS_OPERATION_CONTRACT,
        "task": task,
        "request": normalized_request,
    }


def validate_source_text_request(request: dict[str, Any]) -> str:
    if "prompt" in request:
        raise WordPressOperationContractViolation(
            "wordpress_operation.prompt_forbidden",
            "WordPress text scene tasks require source_text and do not accept prompt",
        )
    source_text = request.get("source_text")
    if not isinstance(source_text, str) or not source_text.strip():
        raise WordPressOperationContractViolation(
            "wordpress_operation.source_text_required",
            "WordPress text scene tasks require source_text as a nonempty string",
        )
    normalized = source_text.strip()
    if len(normalized) > WP_AI_CONNECTOR_MAX_SOURCE_TEXT_CHARS:
        raise WordPressOperationContractViolation(
            "wordpress_operation.source_text_too_large",
            "WordPress text scene source_text exceeds the 12000 character limit",
        )
    return normalized


def validate_system_instruction(request: dict[str, Any]) -> str:
    system_instruction = request.get("system_instruction")
    if not isinstance(system_instruction, str):
        raise WordPressOperationContractViolation(
            "wordpress_operation.system_instruction_invalid",
            "WordPress text scene system_instruction must be a string",
        )
    normalized = system_instruction.strip()
    if len(normalized) > WP_AI_CONNECTOR_MAX_SYSTEM_INSTRUCTION_CHARS:
        raise WordPressOperationContractViolation(
            "wordpress_operation.system_instruction_too_large",
            "WordPress text scene system_instruction exceeds the 12000 character limit",
        )
    return normalized


def find_forbidden_wordpress_operation_control_field(
    value: Any,
    *,
    path: str = "request",
    depth: int = 0,
) -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").strip().lower().replace("-", "_")
            current_path = f"{path}.{normalized_key}"
            if (
                depth == 0
                and normalized_key in WORDPRESS_OPERATION_REQUEST_CONTROL_FIELDS
            ) or normalized_key == "direct_wordpress_write":
                return current_path
            nested = find_forbidden_wordpress_operation_control_field(
                item,
                path=current_path,
                depth=depth + 1,
            )
            if nested:
                return nested
    if isinstance(value, list):
        for index, item in enumerate(value):
            nested = find_forbidden_wordpress_operation_control_field(
                item,
                path=f"{path}[{index}]",
                depth=depth + 1,
            )
            if nested:
                return nested
    return ""


def validate_ai_task_contract(value: Any, *, task: str) -> None:
    if not isinstance(value, dict):
        raise WordPressOperationContractViolation(
            "wordpress_operation.ai_task_contract_invalid",
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
        raise WordPressOperationContractViolation(
            "wordpress_operation.ai_task_contract_fields_forbidden",
            "AI task contract contains unsupported fields",
        )
    if str(value.get("contract_version") or "") != AI_TASK_CONTRACT:
        raise WordPressOperationContractViolation(
            "wordpress_operation.ai_task_contract_version_invalid",
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
        raise WordPressOperationContractViolation(
            "wordpress_operation.ai_task_contract_identity_invalid",
            "AI task contract identity does not match the registered task projection",
        )
    if str(value.get("write_posture") or "") != "suggestion_only":
        raise WordPressOperationContractViolation(
            "wordpress_operation.ai_task_contract_write_posture_invalid",
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
        raise WordPressOperationContractViolation(
            "wordpress_operation.ai_task_contract_vocabulary_invalid",
            "AI task contract contains an unsupported context requirement or constraint",
        )
    if "none" in contexts and len(contexts) != 1:
        raise WordPressOperationContractViolation(
            "wordpress_operation.ai_task_contract_none_invalid",
            "AI task contract context none cannot be combined with other values",
        )
    output_schema = value.get("output_schema")
    if not isinstance(output_schema, dict):
        raise WordPressOperationContractViolation(
            "wordpress_operation.ai_task_contract_output_schema_invalid",
            "AI task contract requires an Ability-owned output schema",
        )
    try:
        encoded_schema = json.dumps(output_schema, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise WordPressOperationContractViolation(
            "wordpress_operation.ai_task_contract_output_schema_invalid",
            "AI task contract output schema must be JSON serializable",
        ) from error
    if len(encoded_schema.encode("utf-8")) > AI_TASK_MAX_OUTPUT_SCHEMA_BYTES:
        raise WordPressOperationContractViolation(
            "wordpress_operation.ai_task_contract_output_schema_too_large",
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
        raise WordPressOperationContractViolation(
            "wordpress_operation.site_knowledge_reference_invalid",
            "WordPress AI connector site_knowledge_reference must be an object",
        )

    unknown_fields = set(reference) - {"enabled", "mode"}
    if unknown_fields:
        raise WordPressOperationContractViolation(
            "wordpress_operation.site_knowledge_reference_fields_forbidden",
            "WordPress AI connector site_knowledge_reference accepts only enabled and mode",
        )

    enabled = reference.get("enabled")
    if not isinstance(enabled, bool):
        raise WordPressOperationContractViolation(
            "wordpress_operation.site_knowledge_reference_enabled_invalid",
            "WordPress AI connector site_knowledge_reference.enabled must be boolean",
        )
    expected_mode = resolve_site_knowledge_reference_mode(
        task=task,
        task_contract=task_contract,
    )
    mode = str(reference.get("mode") or expected_mode or "site_title_style")
    if enabled and not expected_mode:
        raise WordPressOperationContractViolation(
            "wordpress_operation.site_knowledge_reference_task_not_allowed",
            "WordPress AI connector Site Knowledge reference is not supported for this task",
        )
    if (expected_mode and mode != expected_mode) or (
        not expected_mode and mode != "site_title_style"
    ):
        raise WordPressOperationContractViolation(
            "wordpress_operation.site_knowledge_reference_mode_invalid",
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


def validate_alt_text_suggest_request(request: dict[str, Any]) -> dict[str, Any]:
    inline_candidates = {
        raw_key: item
        for raw_key, item in request.items()
        if not isinstance(raw_key, str)
        or re.sub(r"[-\s]+", "_", raw_key.strip().lower()) != "source_artifact_id"
    }
    if contains_inline_media_transport(inline_candidates):
        raise WordPressOperationContractViolation(
            "wordpress_operation.alt_text_inline_media_forbidden",
            "WordPress AI alt text suggestions do not accept inline media transport",
        )

    normalized_request: dict[str, Any] = {}
    for raw_key, item in request.items():
        if not isinstance(raw_key, str):
            raise WordPressOperationContractViolation(
                "wordpress_operation.alt_text_request_fields_forbidden",
                "WordPress AI alt text scene request fields must use canonical names",
            )
        stripped_key = raw_key.strip()
        canonical_key = re.sub(r"[-\s]+", "_", stripped_key.lower())
        if (
            raw_key != canonical_key
            or canonical_key in normalized_request
            or canonical_key not in WP_AI_CONNECTOR_ALT_TEXT_REQUEST_FIELDS
        ):
            raise WordPressOperationContractViolation(
                "wordpress_operation.alt_text_request_fields_forbidden",
                "WordPress AI alt text scene request contains an unsupported, aliased, "
                "or duplicate field",
            )
        normalized_request[canonical_key] = item

    artifact_id = normalized_request.get("source_artifact_id")
    if not isinstance(artifact_id, str):
        raise WordPressOperationContractViolation(
            "wordpress_operation.alt_text_source_artifact_required",
            "WordPress AI alt text suggestions require source_artifact_id",
        )
    normalized = artifact_id.strip()
    if (
        not normalized
        or len(normalized) != WP_AI_CONNECTOR_SOURCE_ARTIFACT_ID_CHARS
        or WP_AI_CONNECTOR_SOURCE_ARTIFACT_ID_PATTERN.fullmatch(normalized) is None
    ):
        raise WordPressOperationContractViolation(
            "wordpress_operation.alt_text_source_artifact_required",
            "WordPress AI alt text suggestions require a valid source_artifact_id",
        )
    normalized_request["source_artifact_id"] = normalized

    prompt = normalized_request.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise WordPressOperationContractViolation(
            "wordpress_operation.alt_text_prompt_invalid",
            "WordPress AI alt text prompt must be a nonempty string",
        )
    normalized_prompt = prompt.strip()
    if len(normalized_prompt) > 500:
        raise WordPressOperationContractViolation(
            "wordpress_operation.alt_text_prompt_too_large",
            "WordPress AI alt text prompt exceeds the 500 character limit",
        )
    normalized_request["prompt"] = normalized_prompt

    for field_name, max_chars in WP_AI_CONNECTOR_ALT_TEXT_OPTIONAL_STRING_LIMITS.items():
        if field_name not in normalized_request:
            continue
        field_value = normalized_request[field_name]
        if not isinstance(field_value, str):
            raise WordPressOperationContractViolation(
                "wordpress_operation.alt_text_request_value_invalid",
                f"WordPress AI alt text {field_name} must be a string",
            )
        normalized_value = field_value.strip()
        if len(normalized_value) > max_chars:
            raise WordPressOperationContractViolation(
                "wordpress_operation.alt_text_request_value_too_large",
                f"WordPress AI alt text {field_name} exceeds its character limit",
            )
        normalized_request[field_name] = normalized_value

    if "max_tokens" in normalized_request:
        max_tokens = normalized_request["max_tokens"]
        if (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or not 1 <= max_tokens <= 96
        ):
            raise WordPressOperationContractViolation(
                "wordpress_operation.alt_text_max_tokens_invalid",
                "WordPress AI alt text max_tokens must be an integer from 1 to 96",
            )
    return normalized_request


def contains_inline_media_transport(value: Any) -> bool:
    if isinstance(value, str):
        compacted = re.sub(r"\s+", "", value)
        return bool(
            WP_AI_CONNECTOR_INLINE_MEDIA_PATTERN.search(compacted)
            or WP_AI_CONNECTOR_B64_JSON_PATTERN.search(value)
            or WP_AI_CONNECTOR_LONG_BASE64_PATTERN.search(value)
            or WP_AI_CONNECTOR_IMAGE_BASE64_MAGIC_PATTERN.search(compacted)
        )
    if isinstance(value, dict):
        return any(contains_inline_media_transport(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_inline_media_transport(item) for item in value)
    return False
