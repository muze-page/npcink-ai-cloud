from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.adapters.providers.base import ProviderExecutionRequest
from app.adapters.providers.minimax import MiniMaxProviderAdapter
from app.core.config import Settings
from app.domain.audio_generation.contracts import (
    AUDIO_GENERATION_CLOUD_ABILITY,
    AUDIO_GENERATION_CONTRACT,
    AUDIO_GENERATION_EXECUTION_KIND,
)
from app.domain.hosted_model_defaults import (
    AUDIO_NARRATION_MODEL_ID,
    AUDIO_NARRATION_PROFILE_ID,
)

ENV_KEYS = {
    "provider_enabled": "NPCINK_CLOUD_MINIMAX_PROVIDER_ENABLED",
    "base_url": "NPCINK_CLOUD_MINIMAX_BASE_URL",
    "api_key": "NPCINK_CLOUD_MINIMAX_API_KEY",
    "group_id": "NPCINK_CLOUD_MINIMAX_GROUP_ID",
    "timeout_seconds": "NPCINK_CLOUD_MINIMAX_TIMEOUT_SECONDS",
    "default_voice_id": "NPCINK_CLOUD_MINIMAX_DEFAULT_VOICE_ID",
}

SECRET_FIELDS = {"api_key", "group_id"}
MINIMAX_SAMPLE_TEXT = "这是一段用于验证 MiniMax 云端语音生成的短旁白。"


class AudioProviderAdminConfigError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass(slots=True)
class AudioProviderAdminConfigService:
    settings: Settings

    def get_config(self) -> dict[str, Any]:
        api_key_configured = bool(str(self.settings.minimax_api_key or "").strip())
        group_id_configured = bool(str(self.settings.minimax_group_id or "").strip())
        enabled = bool(self.settings.minimax_provider_enabled or api_key_configured)
        return {
            "provider_mode": "minimax" if enabled else "disabled",
            "env_path": str(self.settings.minimax_admin_env_path or ".env.local"),
            "requires_worker_restart_after_save": True,
            "providers": {
                "minimax": {
                    "provider_id": "minimax",
                    "display_name": "MiniMax",
                    "enabled": enabled,
                    "configured": api_key_configured,
                    "status": "ready"
                    if enabled and api_key_configured
                    else ("configured" if api_key_configured else "missing_secret"),
                    "base_url": str(self.settings.minimax_base_url or ""),
                    "api_key": {
                        "configured": api_key_configured,
                        "display": "configured" if api_key_configured else "missing",
                    },
                    "group_id": {
                        "configured": group_id_configured,
                        "display": "configured" if group_id_configured else "not_configured",
                        "optional": True,
                    },
                },
            },
            "runtime": {
                "timeout_seconds": float(self.settings.minimax_timeout_seconds),
                "default_voice_id": str(self.settings.minimax_default_voice_id or ""),
                "models": ["speech-2.8-turbo", "speech-2.8-hd"],
                "supported_intents": ["article_narration", "article_audio_summary"],
            },
            "boundary": {
                "owner": "cloud_runtime",
                "wordpress_users_configure_provider_keys": False,
                "secret_exposure": "masked_status_only",
                "final_writes": "core_proposal_required",
            },
        }

    def save_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_payload(payload)
        current_env = _read_env_file(self._env_path())
        merged = dict(current_env)
        for field, env_key in ENV_KEYS.items():
            if field in SECRET_FIELDS:
                secret_value = str(normalized.get(field) or "").strip()
                clear_secret = bool(normalized.get(f"clear_{field}"))
                if clear_secret:
                    merged[env_key] = ""
                elif secret_value:
                    merged[env_key] = secret_value
                elif env_key not in merged:
                    merged[env_key] = ""
                continue
            merged[env_key] = str(normalized.get(field, "")).strip()

        _write_env_values(self._env_path(), merged)
        self._apply_to_settings(merged)
        return self.get_config()

    def test_minimax_connection(self) -> dict[str, Any]:
        api_key = str(self.settings.minimax_api_key or "").strip()
        if not api_key:
            raise AudioProviderAdminConfigError(
                "audio_provider.minimax_secret_missing",
                "MiniMax API key is not configured",
            )

        now = datetime.now(UTC)
        adapter = MiniMaxProviderAdapter(
            base_url=self.settings.minimax_base_url,
            api_key=api_key,
            group_id=self.settings.minimax_group_id,
            timeout_seconds=self.settings.minimax_timeout_seconds,
            default_voice_id=self.settings.minimax_default_voice_id,
        )
        request = ProviderExecutionRequest(
            run_id=f"admin_audio_provider_test_{int(now.timestamp())}",
            site_id="admin_provider_test",
            ability_name=AUDIO_GENERATION_CLOUD_ABILITY,
            profile_id=AUDIO_NARRATION_PROFILE_ID,
            execution_kind=AUDIO_GENERATION_EXECUTION_KIND,
            model_id=AUDIO_NARRATION_MODEL_ID,
            instance_id="minimax-global-speech-28-turbo",
            endpoint_variant="t2a_v2",
            trace_id=f"admin-audio-provider-test-{int(now.timestamp())}",
            input_payload={
                "contract_version": AUDIO_GENERATION_CONTRACT,
                "intent": "article_narration",
                "text": MINIMAX_SAMPLE_TEXT,
                "format": "mp3",
                "response_format": "url",
                "language_boost": "auto",
            },
            policy={"allow_fallback": False},
            timeout_ms=max(1, int(float(self.settings.minimax_timeout_seconds or 30) * 1000)),
        )
        execution = adapter.execute(request)
        return {
            "provider_id": "minimax",
            "status": "ok",
            "generated_at": now.isoformat(),
            "sample_text": MINIMAX_SAMPLE_TEXT,
            "model_id": AUDIO_NARRATION_MODEL_ID,
            "profile_id": AUDIO_NARRATION_PROFILE_ID,
            "default_voice_id": str(self.settings.minimax_default_voice_id or ""),
            "latency_ms": execution.latency_ms,
            "tokens_in": execution.tokens_in,
            "tokens_out": execution.tokens_out,
            "cost": execution.cost,
            "artifact": execution.output,
            "boundary": {
                "owner": "cloud_runtime",
                "direct_wordpress_write": False,
                "final_writes": "core_proposal_required",
            },
        }

    def _env_path(self) -> Path:
        return Path(str(self.settings.minimax_admin_env_path or ".env.local"))

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        providers = _dict(payload.get("providers"))
        minimax = _dict(providers.get("minimax"))
        runtime = _dict(payload.get("runtime"))
        provider_mode = str(payload.get("provider_mode") or "").strip().lower()
        enabled = bool(
            minimax.get("enabled")
            if "enabled" in minimax
            else provider_mode == "minimax" or self.settings.minimax_provider_enabled
        )
        return {
            "provider_enabled": "true" if enabled else "false",
            "base_url": _value(minimax, "base_url", self.settings.minimax_base_url),
            "api_key": _value(minimax, "secret", ""),
            "clear_api_key": bool(minimax.get("clear_secret")),
            "group_id": _value(minimax, "group_id", ""),
            "clear_group_id": bool(minimax.get("clear_group_id")),
            "timeout_seconds": _positive_float(
                runtime.get("timeout_seconds"),
                self.settings.minimax_timeout_seconds,
            ),
            "default_voice_id": _value(
                runtime,
                "default_voice_id",
                self.settings.minimax_default_voice_id,
            )
            or "male-qn-qingse",
        }

    def _apply_to_settings(self, env: dict[str, str]) -> None:
        self.settings.minimax_provider_enabled = _bool(
            env.get(ENV_KEYS["provider_enabled"])
        )
        self.settings.minimax_base_url = env.get(
            ENV_KEYS["base_url"],
            "https://api.minimaxi.com",
        )
        self.settings.minimax_api_key = env.get(ENV_KEYS["api_key"], "")
        self.settings.minimax_group_id = env.get(ENV_KEYS["group_id"], "")
        self.settings.minimax_timeout_seconds = _positive_float(
            env.get(ENV_KEYS["timeout_seconds"]),
            30,
        )
        self.settings.minimax_default_voice_id = env.get(
            ENV_KEYS["default_voice_id"],
            "male-qn-qingse",
        )


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _write_env_values(path: Path, values: dict[str, str]) -> None:
    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    updated_keys = set(ENV_KEYS.values())
    output: list[str] = []
    seen: set[str] = set()
    for line in existing_lines:
        if "=" not in line or line.lstrip().startswith("#"):
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updated_keys:
            output.append(f"{key}={values.get(key, '')}")
            seen.add(key)
        else:
            output.append(line)
    missing = [key for key in ENV_KEYS.values() if key not in seen]
    if missing:
        if output and output[-1].strip():
            output.append("")
        output.append(
            "# Cloud-managed Audio Providers. WordPress users never provide provider keys."
        )
        for key in missing:
            output.append(f"{key}={values.get(key, '')}")
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _value(payload: dict[str, Any], key: str, default: Any) -> str:
    return str(payload.get(key) if key in payload else default).strip()


def _positive_float(value: Any, default: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(default or 0)
    return max(0.001, number)


def _bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
