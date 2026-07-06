from __future__ import annotations

import json
from typing import Any

from app.domain.hosted_model_defaults import AUDIO_NARRATION_PROFILE_ID

AUDIO_GENERATION_CLOUD_ABILITY = "npcink-cloud/generate-audio"
AUDIO_GENERATION_TOOLBOX_ABILITY = "npcink-toolbox/generate-audio"
AUDIO_GENERATION_ABILITIES = frozenset(
    {AUDIO_GENERATION_CLOUD_ABILITY, AUDIO_GENERATION_TOOLBOX_ABILITY}
)
AUDIO_GENERATION_CONTRACT = "audio_generation_request.v1"
AUDIO_GENERATION_PROFILE_ID = AUDIO_NARRATION_PROFILE_ID
AUDIO_GENERATION_EXECUTION_KIND = "audio_generation"
AUDIO_GENERATION_ABILITY_FAMILY = "audio"
AUDIO_GENERATION_DATA_CLASSIFICATION = "internal"
AUDIO_GENERATION_RESULT_CONTRACT = "audio_generation_result.v1"

ALLOWED_AUDIO_GENERATION_INTENTS = frozenset(
    {"article_narration", "article_audio_summary"}
)
ALLOWED_AUDIO_GENERATION_FORMATS = frozenset({"mp3", "wav", "pcm"})
ALLOWED_AUDIO_GENERATION_RESPONSE_FORMATS = frozenset({"url", "b64_json"})
ALLOWED_AUDIO_GENERATION_SAMPLE_RATES = frozenset({16000, 22050, 24000, 32000, 44100})
ALLOWED_AUDIO_GENERATION_CHANNELS = frozenset({1, 2})
AUDIO_GENERATION_MAX_TEXT_CHARS = 5000
AUDIO_GENERATION_MAX_CONTEXT_CHARS = 6000
AUDIO_GENERATION_CONTEXT_FIELDS = frozenset({"article_context", "summary_context", "review"})

FORBIDDEN_AUDIO_GENERATION_KEYS = frozenset(
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
        "update_media",
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


class AudioGenerationContractViolation(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def validate_audio_generation_runtime_contract(
    *,
    ability_name: str,
    contract_version: str,
    input_payload: dict[str, Any],
) -> None:
    if ability_name not in AUDIO_GENERATION_ABILITIES:
        raise AudioGenerationContractViolation(
            "audio_generation.unknown_ability",
            "audio generation ability_name is not supported",
        )
    if contract_version != AUDIO_GENERATION_CONTRACT:
        raise AudioGenerationContractViolation(
            "audio_generation.contract_mismatch",
            "audio generation contract_version does not match ability_name",
        )
    if not isinstance(input_payload, dict):
        raise AudioGenerationContractViolation(
            "audio_generation.invalid_input",
            "audio generation input must be an object",
        )
    if str(input_payload.get("contract_version") or contract_version) != AUDIO_GENERATION_CONTRACT:
        raise AudioGenerationContractViolation(
            "audio_generation.input_contract_mismatch",
            "audio generation input contract_version does not match runtime contract",
        )
    forbidden_path = find_forbidden_audio_generation_field(input_payload)
    if forbidden_path:
        raise AudioGenerationContractViolation(
            "audio_generation.write_or_secret_field_forbidden",
            "audio generation input may not include provider secret or write/control "
            f"field '{forbidden_path}'",
        )
    intent = str(input_payload.get("intent") or "article_narration").strip()
    if intent not in ALLOWED_AUDIO_GENERATION_INTENTS:
        raise AudioGenerationContractViolation(
            "audio_generation.intent_invalid",
            "audio generation intent is not supported",
        )
    text = resolve_audio_generation_text(input_payload)
    if not text:
        raise AudioGenerationContractViolation(
            "audio_generation.text_required",
            "audio generation text or summary_text is required",
        )
    if len(text) > AUDIO_GENERATION_MAX_TEXT_CHARS:
        raise AudioGenerationContractViolation(
            "audio_generation.text_too_long",
            "audio generation text must be "
            f"{AUDIO_GENERATION_MAX_TEXT_CHARS} characters or fewer",
        )
    audio_format = str(input_payload.get("format") or "mp3").strip().lower()
    if audio_format not in ALLOWED_AUDIO_GENERATION_FORMATS:
        raise AudioGenerationContractViolation(
            "audio_generation.format_invalid",
            "audio generation format must be mp3, wav, or pcm",
        )
    response_format = str(input_payload.get("response_format") or "url").strip()
    if response_format not in ALLOWED_AUDIO_GENERATION_RESPONSE_FORMATS:
        raise AudioGenerationContractViolation(
            "audio_generation.response_format_invalid",
            "audio generation response_format must be url or b64_json",
        )
    sample_rate = _coerce_int(input_payload.get("sample_rate"), default=32000)
    if sample_rate not in ALLOWED_AUDIO_GENERATION_SAMPLE_RATES:
        raise AudioGenerationContractViolation(
            "audio_generation.sample_rate_invalid",
            "audio generation sample_rate is not supported",
        )
    channel = _coerce_int(input_payload.get("channel"), default=1)
    if channel not in ALLOWED_AUDIO_GENERATION_CHANNELS:
        raise AudioGenerationContractViolation(
            "audio_generation.channel_invalid",
            "audio generation channel must be 1 or 2",
        )
    for numeric_key in ("speed", "volume", "pitch"):
        if numeric_key not in input_payload:
            continue
        value = _coerce_float(input_payload.get(numeric_key), default=1.0)
        if value < 0.5 or value > 2.0:
            raise AudioGenerationContractViolation(
                f"audio_generation.{numeric_key}_invalid",
                f"audio generation {numeric_key} must be between 0.5 and 2.0",
            )
    for field in AUDIO_GENERATION_CONTEXT_FIELDS:
        if field not in input_payload:
            continue
        context_value = input_payload.get(field)
        if not isinstance(context_value, dict):
            raise AudioGenerationContractViolation(
                "audio_generation.context_invalid",
                f"audio generation {field} must be an object",
            )
        if _serialized_size(context_value) > AUDIO_GENERATION_MAX_CONTEXT_CHARS:
            raise AudioGenerationContractViolation(
                "audio_generation.context_too_large",
                f"audio generation {field} must serialize to "
                f"{AUDIO_GENERATION_MAX_CONTEXT_CHARS} characters or fewer",
            )


def resolve_audio_generation_text(input_payload: dict[str, Any]) -> str:
    for key in ("summary_text", "script", "text", "input"):
        value = input_payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def find_forbidden_audio_generation_field(value: Any, *, path: str = "") -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").strip().lower()
            current_path = f"{path}.{normalized_key}" if path else normalized_key
            if normalized_key in FORBIDDEN_AUDIO_GENERATION_KEYS:
                if normalized_key == "direct_wordpress_write" and item is False:
                    continue
                return current_path
            nested = find_forbidden_audio_generation_field(item, path=current_path)
            if nested:
                return nested
    if isinstance(value, list):
        for index, item in enumerate(value):
            nested = find_forbidden_audio_generation_field(item, path=f"{path}[{index}]")
            if nested:
                return nested
    return ""


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _serialized_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError):
        return AUDIO_GENERATION_MAX_CONTEXT_CHARS + 1
