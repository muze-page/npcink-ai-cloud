from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.adapters.providers.base import ProviderAdapter
from app.core.config import Settings
from app.core.db import get_session
from app.core.models import RunRecord
from app.domain.audio_generation.admin_config import AudioProviderAdminConfigService
from app.domain.hosted_model_defaults import (
    AUDIO_NARRATION_MODEL_ID,
    AUDIO_NARRATION_PROFILE_ID,
    AUDIO_NARRATION_QUALITY_MODEL_ID,
    AUDIO_NARRATION_QUALITY_PROFILE_ID,
    FREE_GPT55_MODEL_ID,
    FREE_GPT55_TEXT_PROFILE_ID,
    TEXT_AI_PROFILE_ID,
)
from app.domain.image_sources.admin_config import ImageSourceAdminConfigService
from app.domain.web_search.admin_config import WebSearchAdminConfigService

AI_RESOURCES_PROFILE_ENV_KEYS = {
    "audio_summary_text_profile_id": "NPCINK_CLOUD_AUDIO_SUMMARY_TEXT_PROFILE_ID",
    "audio_narration_profile_id": "NPCINK_CLOUD_AUDIO_NARRATION_PROFILE_ID",
    "audio_summary_audio_profile_id": "NPCINK_CLOUD_AUDIO_SUMMARY_AUDIO_PROFILE_ID",
}
ALLOWED_TEXT_PROFILE_IDS = frozenset({TEXT_AI_PROFILE_ID, FREE_GPT55_TEXT_PROFILE_ID})
ALLOWED_AUDIO_PROFILE_IDS = frozenset(
    {AUDIO_NARRATION_PROFILE_ID, AUDIO_NARRATION_QUALITY_PROFILE_ID}
)
TEXT_PROFILE_MODEL_IDS = {
    TEXT_AI_PROFILE_ID: FREE_GPT55_MODEL_ID,
    FREE_GPT55_TEXT_PROFILE_ID: FREE_GPT55_MODEL_ID,
}
AUDIO_PROFILE_MODEL_IDS = {
    AUDIO_NARRATION_PROFILE_ID: AUDIO_NARRATION_MODEL_ID,
    AUDIO_NARRATION_QUALITY_PROFILE_ID: AUDIO_NARRATION_QUALITY_MODEL_ID,
}


class AIResourceProfilePreferenceError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass(slots=True)
class AIResourceProfilePreferenceService:
    settings: Settings

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_payload(payload)
        current_env = _read_env_file(self._env_path())
        merged = dict(current_env)
        for field, env_key in AI_RESOURCES_PROFILE_ENV_KEYS.items():
            merged[env_key] = str(normalized[field])
        _write_env_values(self._env_path(), merged)
        self._apply_to_settings(normalized)
        return build_admin_ai_resource_projection(self.settings)

    def _env_path(self) -> Path:
        return Path(str(self.settings.ai_resources_admin_env_path or ".env.local"))

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, str]:
        text_profile_id = _value(
            payload,
            "audio_summary_text_profile_id",
            _selected_audio_summary_text_profile_id(self.settings),
        )
        audio_narration_profile_id = _value(
            payload,
            "audio_narration_profile_id",
            _selected_audio_narration_profile_id(self.settings),
        )
        audio_summary_audio_profile_id = _value(
            payload,
            "audio_summary_audio_profile_id",
            _selected_audio_summary_audio_profile_id(self.settings),
        )
        if text_profile_id not in ALLOWED_TEXT_PROFILE_IDS:
            raise AIResourceProfilePreferenceError(
                "ai_resources.profile_preference_invalid",
                "audio_summary_text_profile_id must be text.ai or text.free-gpt55",
            )
        if audio_narration_profile_id not in ALLOWED_AUDIO_PROFILE_IDS:
            raise AIResourceProfilePreferenceError(
                "ai_resources.profile_preference_invalid",
                (
                    "audio_narration_profile_id must be audio.narration.default "
                    "or audio.narration.quality"
                ),
            )
        if audio_summary_audio_profile_id not in ALLOWED_AUDIO_PROFILE_IDS:
            raise AIResourceProfilePreferenceError(
                "ai_resources.profile_preference_invalid",
                (
                    "audio_summary_audio_profile_id must be audio.narration.default "
                    "or audio.narration.quality"
                ),
            )
        return {
            "audio_summary_text_profile_id": text_profile_id,
            "audio_narration_profile_id": audio_narration_profile_id,
            "audio_summary_audio_profile_id": audio_summary_audio_profile_id,
        }

    def _apply_to_settings(self, normalized: dict[str, str]) -> None:
        self.settings.audio_summary_text_profile_id = normalized[
            "audio_summary_text_profile_id"
        ]
        self.settings.audio_narration_profile_id = normalized[
            "audio_narration_profile_id"
        ]
        self.settings.audio_summary_audio_profile_id = normalized[
            "audio_summary_audio_profile_id"
        ]


def build_admin_ai_resource_projection(
    settings: Settings,
    *,
    providers: dict[str, ProviderAdapter] | None = None,
    database_url: str | None = None,
) -> dict[str, Any]:
    provider_adapters = providers or {}
    audio_config = AudioProviderAdminConfigService(settings).get_config()
    image_source_config = ImageSourceAdminConfigService(settings).get_config()
    web_search_config = WebSearchAdminConfigService(settings).get_config()

    text_configured = (
        bool(str(settings.openai_api_key or "").strip()) or "openai" in provider_adapters
    )
    text_status = "ready" if text_configured else "missing_secret"
    text_label = str(settings.openai_provider_label or "").strip() or "OpenAI-compatible"

    minimax = _dict(audio_config.get("providers")).get("minimax", {})
    minimax_configured = bool(_dict(minimax).get("configured")) or "minimax" in provider_adapters
    minimax_enabled = bool(_dict(minimax).get("enabled")) or "minimax" in provider_adapters
    audio_status = "ready" if minimax_configured and minimax_enabled else "missing_secret"

    web_search_mode = str(web_search_config.get("provider_mode") or "disabled")
    web_search_ready = web_search_mode != "disabled" and _has_configured_provider(
        _dict(web_search_config.get("providers"))
    )
    image_source_mode = str(image_source_config.get("provider_mode") or "disabled")
    image_source_ready = image_source_mode != "disabled" and _has_configured_provider(
        _dict(image_source_config.get("providers"))
    )
    audio_narration_profile_id = _selected_audio_narration_profile_id(settings)
    audio_summary_text_profile_id = _selected_audio_summary_text_profile_id(settings)
    audio_summary_audio_profile_id = _selected_audio_summary_audio_profile_id(settings)
    resolved_database_url = str(database_url or getattr(settings, "database_url", "") or "")
    recent_runs = _recent_runtime_evidence(
        resolved_database_url,
        profile_ids=[
            TEXT_AI_PROFILE_ID,
            FREE_GPT55_TEXT_PROFILE_ID,
            AUDIO_NARRATION_PROFILE_ID,
            AUDIO_NARRATION_QUALITY_PROFILE_ID,
        ],
    )

    connections = [
        {
            "connection_id": "openai_compatible",
            "provider_id": "openai",
            "display_name": text_label,
            "kind": "text_provider",
            "enabled": text_configured,
            "configured": text_configured,
            "status": text_status,
            "base_url": str(settings.openai_base_url or ""),
            "secrets": {
                "api_key": {
                    "configured": text_configured,
                    "display": "configured" if text_configured else "missing",
                }
            },
            "capability_ids": ["text_generation"],
            "runtime_profile_ids": [TEXT_AI_PROFILE_ID, FREE_GPT55_TEXT_PROFILE_ID],
        },
        {
            "connection_id": "minimax_audio",
            "provider_id": "minimax",
            "display_name": str(_dict(minimax).get("display_name") or "MiniMax"),
            "kind": "audio_provider",
            "enabled": minimax_enabled,
            "configured": minimax_configured,
            "status": audio_status,
            "base_url": str(_dict(minimax).get("base_url") or ""),
            "secrets": {
                "api_key": _dict(_dict(minimax).get("api_key")),
                "group_id": _dict(_dict(minimax).get("group_id")),
            },
            "capability_ids": ["audio_generation"],
            "runtime_profile_ids": [
                AUDIO_NARRATION_PROFILE_ID,
                AUDIO_NARRATION_QUALITY_PROFILE_ID,
            ],
            "detail_href": "/admin/audio-providers",
        },
    ]

    capabilities = [
        {
            "capability_id": "text_generation",
            "label": "Text generation",
            "status": "ready" if text_configured else "missing_provider",
            "default_profile_id": audio_summary_text_profile_id,
            "connection_ids": ["openai_compatible"] if text_configured else [],
            "used_by": ["Content Support", "Audio summary script"],
            "write_posture": "suggestion_only",
        },
        {
            "capability_id": "audio_generation",
            "label": "Audio generation",
            "status": "ready" if audio_status == "ready" else "missing_provider",
            "default_profile_id": audio_narration_profile_id,
            "connection_ids": ["minimax_audio"] if audio_status == "ready" else [],
            "used_by": ["Article narration", "Audio summary playback"],
            "write_posture": "candidate_artifact_only",
        },
        {
            "capability_id": "web_search",
            "label": "Web search",
            "status": "ready" if web_search_ready else "disabled",
            "default_profile_id": "web-search.managed",
            "connection_ids": _configured_provider_ids(web_search_config),
            "used_by": ["Evidence preflight"],
            "write_posture": "suggestion_only",
        },
        {
            "capability_id": "image_source",
            "label": "Image source",
            "status": "ready" if image_source_ready else "disabled",
            "default_profile_id": "image-source.managed",
            "connection_ids": _configured_provider_ids(image_source_config),
            "used_by": ["Image source candidates"],
            "write_posture": "candidate_artifact_only",
        },
        {
            "capability_id": "embedding",
            "label": "Embedding",
            "status": "ready",
            "default_profile_id": "embed.default",
            "connection_ids": [str(settings.site_knowledge_embedding_provider or "deterministic")],
            "used_by": ["Site Knowledge"],
            "write_posture": "runtime_metadata_only",
        },
    ]

    runtime_profiles = [
        {
            "profile_id": TEXT_AI_PROFILE_ID,
            "kind": "runtime_profile",
            "capability_id": "text_generation",
            "selected_connection_id": "openai_compatible",
            "selected_provider_id": "openai",
            "selected_model_id": FREE_GPT55_MODEL_ID,
            "status": "ready" if text_configured else "missing_provider",
            "selection_owner": "cloud_runtime_metadata",
            "used_by": ["Hosted Content Support", "Audio summary script"],
            "last_run": recent_runs.get(TEXT_AI_PROFILE_ID, {}),
            "selected_for": (
                ["audio_summary_script"]
                if audio_summary_text_profile_id == TEXT_AI_PROFILE_ID
                else []
            ),
        },
        {
            "profile_id": FREE_GPT55_TEXT_PROFILE_ID,
            "kind": "runtime_profile",
            "capability_id": "text_generation",
            "selected_connection_id": "openai_compatible",
            "selected_provider_id": "openai",
            "selected_model_id": FREE_GPT55_MODEL_ID,
            "status": "ready" if text_configured else "missing_provider",
            "selection_owner": "cloud_runtime_metadata",
            "used_by": ["Audio summary script"],
            "last_run": recent_runs.get(FREE_GPT55_TEXT_PROFILE_ID, {}),
            "selected_for": (
                ["audio_summary_script"]
                if audio_summary_text_profile_id == FREE_GPT55_TEXT_PROFILE_ID
                else []
            ),
        },
        {
            "profile_id": AUDIO_NARRATION_PROFILE_ID,
            "kind": "runtime_profile",
            "capability_id": "audio_generation",
            "selected_connection_id": "minimax_audio",
            "selected_provider_id": "minimax",
            "selected_model_id": AUDIO_NARRATION_MODEL_ID,
            "status": "ready" if audio_status == "ready" else "missing_provider",
            "selection_owner": "cloud_runtime_metadata",
            "used_by": ["Article narration", "Audio summary playback"],
            "last_run": recent_runs.get(AUDIO_NARRATION_PROFILE_ID, {}),
            "selected_for": _audio_selected_for(
                AUDIO_NARRATION_PROFILE_ID,
                audio_narration_profile_id=audio_narration_profile_id,
                audio_summary_audio_profile_id=audio_summary_audio_profile_id,
            ),
        },
        {
            "profile_id": AUDIO_NARRATION_QUALITY_PROFILE_ID,
            "kind": "runtime_profile",
            "capability_id": "audio_generation",
            "selected_connection_id": "minimax_audio",
            "selected_provider_id": "minimax",
            "selected_model_id": AUDIO_NARRATION_QUALITY_MODEL_ID,
            "status": "ready" if audio_status == "ready" else "missing_provider",
            "selection_owner": "cloud_runtime_metadata",
            "used_by": ["Article narration", "Audio summary playback"],
            "last_run": recent_runs.get(AUDIO_NARRATION_QUALITY_PROFILE_ID, {}),
            "selected_for": _audio_selected_for(
                AUDIO_NARRATION_QUALITY_PROFILE_ID,
                audio_narration_profile_id=audio_narration_profile_id,
                audio_summary_audio_profile_id=audio_summary_audio_profile_id,
            ),
        },
        {
            "profile_id": "audio.summary.default",
            "kind": "pipeline_profile",
            "capability_id": "audio_generation",
            "selected_connection_id": (
                f"{audio_summary_text_profile_id} + {audio_summary_audio_profile_id}"
            ),
            "selected_provider_id": "openai + minimax",
            "selected_model_id": (
                f"{TEXT_PROFILE_MODEL_IDS[audio_summary_text_profile_id]} + "
                f"{AUDIO_PROFILE_MODEL_IDS[audio_summary_audio_profile_id]}"
            ),
            "status": "ready"
            if text_configured and audio_status == "ready"
            else "missing_provider",
            "selection_owner": "cloud_runtime_metadata",
            "used_by": ["Long-form audio summary"],
            "last_run": _pipeline_last_run(
                recent_runs,
                text_profile_id=audio_summary_text_profile_id,
                audio_profile_id=audio_summary_audio_profile_id,
            ),
            "selected_for": ["article_audio_summary"],
        },
    ]

    return {
        "surface": "admin_ai_resources",
        "connections": connections,
        "capabilities": capabilities,
        "runtime_profiles": runtime_profiles,
        "recent_runtime_evidence": {
            "source": "run_records",
            "content_exposed": False,
            "profiles": recent_runs,
        },
        "profile_preferences": {
            "env_path": str(settings.ai_resources_admin_env_path or ".env.local"),
            "requires_worker_restart_after_save": True,
            "audio_summary_text_profile_id": audio_summary_text_profile_id,
            "audio_narration_profile_id": audio_narration_profile_id,
            "audio_summary_audio_profile_id": audio_summary_audio_profile_id,
            "allowed": {
                "text_profile_ids": sorted(ALLOWED_TEXT_PROFILE_IDS),
                "audio_profile_ids": sorted(ALLOWED_AUDIO_PROFILE_IDS),
            },
            "boundary": {
                "owner": "cloud_runtime_metadata",
                "direct_wordpress_write": False,
                "prompt_router_preset_truth": False,
            },
        },
        "boundary": {
            "owner": "cloud_runtime",
            "secret_exposure": "masked_status_only",
            "direct_wordpress_write": False,
            "final_writes": "core_proposal_required",
            "not_a_control_plane": True,
            "does_not_own": [
                "wordpress_writes",
                "approval_truth",
                "ability_registry",
                "workflow_registry",
                "prompt_router_preset_truth",
            ],
        },
    }


def _selected_audio_summary_text_profile_id(settings: Settings) -> str:
    value = str(settings.audio_summary_text_profile_id or "").strip()
    return value if value in ALLOWED_TEXT_PROFILE_IDS else TEXT_AI_PROFILE_ID


def _selected_audio_narration_profile_id(settings: Settings) -> str:
    value = str(settings.audio_narration_profile_id or "").strip()
    return value if value in ALLOWED_AUDIO_PROFILE_IDS else AUDIO_NARRATION_PROFILE_ID


def _selected_audio_summary_audio_profile_id(settings: Settings) -> str:
    value = str(settings.audio_summary_audio_profile_id or "").strip()
    return value if value in ALLOWED_AUDIO_PROFILE_IDS else AUDIO_NARRATION_PROFILE_ID


def _audio_selected_for(
    profile_id: str,
    *,
    audio_narration_profile_id: str,
    audio_summary_audio_profile_id: str,
) -> list[str]:
    selected: list[str] = []
    if profile_id == audio_narration_profile_id:
        selected.append("article_narration")
    if profile_id == audio_summary_audio_profile_id:
        selected.append("article_audio_summary")
    return selected


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _has_configured_provider(providers: dict[str, Any]) -> bool:
    return any(bool(_dict(provider).get("configured")) for provider in providers.values())


def _configured_provider_ids(config: dict[str, Any]) -> list[str]:
    providers = _dict(config.get("providers"))
    return [
        str(provider_id)
        for provider_id, provider in providers.items()
        if bool(_dict(provider).get("configured"))
    ]


def _recent_runtime_evidence(
    database_url: str,
    *,
    profile_ids: list[str],
) -> dict[str, dict[str, Any]]:
    if not database_url:
        return {}
    evidence: dict[str, dict[str, Any]] = {}
    with get_session(database_url) as session:
        for profile_id in profile_ids:
            run = session.scalar(
                select(RunRecord)
                .where(RunRecord.profile_id == profile_id)
                .order_by(RunRecord.started_at.desc())
                .limit(1)
            )
            if run is None:
                continue
            evidence[profile_id] = {
                "run_id": run.run_id,
                "site_id": run.site_id,
                "status": run.status,
                "profile_id": run.profile_id,
                "provider_id": run.selected_provider_id or "",
                "model_id": run.selected_model_id or "",
                "instance_id": run.selected_instance_id or "",
                "trace_id": run.trace_id,
                "error_code": run.error_code or "",
                "started_at": run.started_at.isoformat() if run.started_at else "",
                "finished_at": run.finished_at.isoformat() if run.finished_at else "",
            }
    return evidence


def _pipeline_last_run(
    recent_runs: dict[str, dict[str, Any]],
    *,
    text_profile_id: str,
    audio_profile_id: str,
) -> dict[str, Any]:
    text_run = recent_runs.get(text_profile_id, {})
    audio_run = recent_runs.get(audio_profile_id, {})
    return {
        "text": text_run,
        "audio": audio_run,
        "status": "ready" if text_run and audio_run else "not_observed",
    }


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
    updated_keys = set(AI_RESOURCES_PROFILE_ENV_KEYS.values())
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
    missing = [key for key in AI_RESOURCES_PROFILE_ENV_KEYS.values() if key not in seen]
    if missing:
        if output and output[-1].strip():
            output.append("")
        output.append(
            "# Cloud-managed AI resource profile preferences. This is runtime metadata only."
        )
        for key in missing:
            output.append(f"{key}={values.get(key, '')}")
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def _value(payload: dict[str, Any], key: str, default: Any) -> str:
    return str(payload.get(key) if key in payload else default).strip()
