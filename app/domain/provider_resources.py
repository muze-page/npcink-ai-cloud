from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.adapters.providers.base import ProviderAdapter
from app.core.config import Settings
from app.core.db import get_session
from app.core.models import ProviderCallRecord, RunRecord
from app.domain.audio_generation.admin_config import AudioProviderAdminConfigService
from app.domain.hosted_model_defaults import (
    AUDIO_NARRATION_MODEL_ID,
    AUDIO_NARRATION_PROFILE_ID,
    AUDIO_NARRATION_QUALITY_MODEL_ID,
    AUDIO_NARRATION_QUALITY_PROFILE_ID,
    FREE_GPT55_MODEL_ID,
    FREE_GPT55_TEXT_PROFILE_ID,
    GROK_IMAGINE_IMAGE_MODEL_ID,
    GROK_IMAGINE_IMAGE_PROFILE_ID,
    TEXT_AI_PROFILE_ID,
)
from app.domain.image_sources.admin_config import ImageSourceAdminConfigService
from app.domain.provider_connections.service import ProviderConnectionAdminService
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
            GROK_IMAGINE_IMAGE_PROFILE_ID,
            "embed.default",
        ],
    )
    managed_connections = _managed_provider_connections(settings, resolved_database_url)
    managed_connection_ids_by_capability = _connection_ids_by_capability(managed_connections)
    managed_ready_by_capability = _ready_by_capability(managed_connections)

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
    connections.extend(
        _provider_connections_from_config(
            web_search_config,
            connection_prefix="web_search",
            kind="web_search_provider",
            capability_ids=["web_search"],
            runtime_profile_ids=["web-search.managed"],
            detail_href="/admin/web-search",
        )
    )
    connections.extend(
        _provider_connections_from_config(
            image_source_config,
            connection_prefix="image_source",
            kind="image_source_provider",
            capability_ids=["image_source"],
            runtime_profile_ids=["image-source.managed"],
            detail_href="/admin/image-sources",
        )
    )
    embedding_provider = str(settings.site_knowledge_embedding_provider or "deterministic")
    embedding_model = str(settings.site_knowledge_embedding_model or "BAAI/bge-m3")
    connections.append(
        {
            "connection_id": f"embedding_{embedding_provider}",
            "provider_id": embedding_provider,
            "display_name": f"Site Knowledge embedding ({embedding_provider})",
            "kind": "embedding_provider",
            "enabled": True,
            "configured": _site_knowledge_embedding_configured(settings),
            "status": "ready"
            if _site_knowledge_embedding_configured(settings)
            else "missing_secret",
            "base_url": _site_knowledge_embedding_base_url(settings),
            "secrets": {
                "secret": {
                    "configured": _site_knowledge_embedding_configured(settings),
                    "display": (
                        "configured"
                        if _site_knowledge_embedding_configured(settings)
                        else "missing"
                    ),
                }
            },
            "capability_ids": ["embedding"],
            "runtime_profile_ids": ["embed.default"],
        }
    )
    rerank_provider = str(settings.site_knowledge_rerank_provider or "disabled")
    if rerank_provider != "disabled":
        rerank_configured = bool(str(settings.site_knowledge_jina_api_key or "").strip())
        connections.append(
            {
                "connection_id": f"rerank_{rerank_provider}",
                "provider_id": rerank_provider,
                "display_name": f"Site Knowledge rerank ({rerank_provider})",
                "kind": "rerank_provider",
                "enabled": True,
                "configured": rerank_configured,
                "status": "ready" if rerank_configured else "missing_secret",
                "base_url": str(settings.site_knowledge_jina_base_url or ""),
                "secrets": {
                    "secret": {
                        "configured": rerank_configured,
                        "display": "configured" if rerank_configured else "missing",
                    }
                },
                "capability_ids": ["site_knowledge_rerank"],
                "runtime_profile_ids": ["site-knowledge.rerank"],
            }
        )

    connections = _merge_connections(connections, managed_connections)

    capabilities = [
        {
            "capability_id": "text_generation",
            "label": "Text generation",
            "status": "ready"
            if text_configured or managed_ready_by_capability.get("text_generation")
            else "missing_provider",
            "default_profile_id": audio_summary_text_profile_id,
            "connection_ids": _merge_ids(
                ["openai_compatible"] if text_configured else [],
                managed_connection_ids_by_capability.get("text_generation", []),
            ),
            "used_by": ["Content Support", "Audio summary script"],
            "write_posture": "suggestion_only",
        },
        {
            "capability_id": "audio_generation",
            "label": "Audio generation",
            "status": "ready"
            if audio_status == "ready" or managed_ready_by_capability.get("audio_generation")
            else "missing_provider",
            "default_profile_id": audio_narration_profile_id,
            "connection_ids": _merge_ids(
                ["minimax_audio"] if audio_status == "ready" else [],
                managed_connection_ids_by_capability.get("audio_generation", []),
            ),
            "used_by": ["Article narration", "Audio summary playback"],
            "write_posture": "candidate_artifact_only",
        },
        {
            "capability_id": "web_search",
            "label": "Web search",
            "status": "ready"
            if web_search_ready or managed_ready_by_capability.get("web_search")
            else "disabled",
            "default_profile_id": "web-search.managed",
            "connection_ids": _merge_ids(
                _configured_provider_ids(
                    web_search_config,
                    connection_prefix="web_search",
                ),
                managed_connection_ids_by_capability.get("web_search", []),
            ),
            "used_by": ["Evidence preflight"],
            "write_posture": "suggestion_only",
        },
        {
            "capability_id": "image_source",
            "label": "Image source",
            "status": "ready"
            if image_source_ready or managed_ready_by_capability.get("image_source")
            else "disabled",
            "default_profile_id": "image-source.managed",
            "connection_ids": _merge_ids(
                _configured_provider_ids(
                    image_source_config,
                    connection_prefix="image_source",
                ),
                managed_connection_ids_by_capability.get("image_source", []),
            ),
            "used_by": ["Image source candidates"],
            "write_posture": "candidate_artifact_only",
        },
        {
            "capability_id": "image_generation",
            "label": "Image generation",
            "status": "ready"
            if text_configured or managed_ready_by_capability.get("image_generation")
            else "missing_provider",
            "default_profile_id": GROK_IMAGINE_IMAGE_PROFILE_ID,
            "connection_ids": _merge_ids(
                ["openai_compatible"] if text_configured else [],
                managed_connection_ids_by_capability.get("image_generation", []),
            ),
            "used_by": ["Generated image candidates"],
            "write_posture": "candidate_artifact_only",
        },
        {
            "capability_id": "embedding",
            "label": "Embedding",
            "status": "ready"
            if _site_knowledge_embedding_configured(settings)
            or managed_ready_by_capability.get("embedding")
            else "missing_provider",
            "default_profile_id": "embed.default",
            "connection_ids": _merge_ids(
                [f"embedding_{embedding_provider}"],
                managed_connection_ids_by_capability.get("embedding", []),
            ),
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
        {
            "profile_id": GROK_IMAGINE_IMAGE_PROFILE_ID,
            "kind": "runtime_profile",
            "capability_id": "image_generation",
            "selected_connection_id": "openai_compatible",
            "selected_provider_id": "openai",
            "selected_model_id": GROK_IMAGINE_IMAGE_MODEL_ID,
            "status": "ready" if text_configured else "missing_provider",
            "selection_owner": "cloud_runtime_metadata",
            "used_by": ["Generated image candidates"],
            "last_run": recent_runs.get(GROK_IMAGINE_IMAGE_PROFILE_ID, {}),
            "selected_for": ["image_generation"],
        },
        {
            "profile_id": "embed.default",
            "kind": "runtime_profile",
            "capability_id": "embedding",
            "selected_connection_id": f"embedding_{embedding_provider}",
            "selected_provider_id": embedding_provider,
            "selected_model_id": embedding_model,
            "status": "ready"
            if _site_knowledge_embedding_configured(settings)
            else "missing_provider",
            "selection_owner": "cloud_runtime_metadata",
            "used_by": ["Site Knowledge"],
            "last_run": recent_runs.get("embed.default", {}),
            "selected_for": ["site_knowledge"],
        },
    ]
    runtime_resolution = _build_runtime_resolution(
        capabilities,
        runtime_profiles,
        connections,
        provider_adapters,
    )
    provider_call_evidence = _provider_call_evidence(
        resolved_database_url,
        _runtime_profile_run_ids(runtime_profiles),
    )
    feature_model_usage = _build_feature_model_usage(
        capabilities,
        runtime_profiles,
        connections,
        provider_call_evidence,
        audio_summary_text_profile_id=audio_summary_text_profile_id,
        audio_narration_profile_id=audio_narration_profile_id,
    )
    provider_model_health = _build_provider_model_health(resolved_database_url)
    env_migration = _build_env_migration_summary(
        settings,
        managed_connections,
    )

    return {
        "surface": "admin_ai_resources",
        "connections": connections,
        "capabilities": capabilities,
        "capability_matrix": _build_capability_matrix(capabilities, runtime_profiles),
        "runtime_resolution": runtime_resolution,
        "feature_model_usage": feature_model_usage,
        "provider_model_health": provider_model_health,
        "runtime_profiles": runtime_profiles,
        "recent_runtime_evidence": {
            "source": "run_records",
            "content_exposed": False,
            "profiles": recent_runs,
        },
        "env_migration": env_migration,
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


def _provider_connections_from_config(
    config: dict[str, Any],
    *,
    connection_prefix: str,
    kind: str,
    capability_ids: list[str],
    runtime_profile_ids: list[str],
    detail_href: str,
) -> list[dict[str, Any]]:
    providers = _dict(config.get("providers"))
    connections: list[dict[str, Any]] = []
    for provider_id, provider_value in sorted(providers.items()):
        provider = _dict(provider_value)
        configured = bool(provider.get("configured"))
        enabled = bool(provider.get("enabled"))
        connections.append(
            {
                "connection_id": f"{connection_prefix}_{provider_id}",
                "provider_id": str(provider_id),
                "display_name": str(provider.get("display_name") or provider_id),
                "kind": kind,
                "enabled": enabled,
                "configured": configured,
                "status": str(provider.get("status") or "missing_secret"),
                "base_url": str(provider.get("base_url") or ""),
                "secrets": {
                    "secret": {
                        "configured": configured,
                        "display": "configured" if configured else "missing",
                    }
                },
                "capability_ids": capability_ids,
                "runtime_profile_ids": runtime_profile_ids,
                "detail_href": detail_href,
            }
        )
    return connections


def _build_runtime_resolution(
    capabilities: list[dict[str, Any]],
    runtime_profiles: list[dict[str, Any]],
    connections: list[dict[str, Any]],
    provider_adapters: dict[str, ProviderAdapter],
) -> list[dict[str, Any]]:
    connections_by_id = {str(item.get("connection_id") or ""): item for item in connections}
    rows: list[dict[str, Any]] = []
    for capability in capabilities:
        capability_id = str(capability.get("capability_id") or "")
        profiles = [
            profile
            for profile in runtime_profiles
            if str(profile.get("capability_id") or "") == capability_id
        ]
        connection_ids = [
            str(connection_id)
            for connection_id in capability.get("connection_ids", [])
            if str(connection_id)
        ]
        ready_connection_ids = [
            connection_id
            for connection_id in connection_ids
            if _dict(connections_by_id.get(connection_id)).get("status") == "ready"
        ]
        selected_profile_id = str(capability.get("default_profile_id") or "")
        selected_profiles = [
            profile
            for profile in profiles
            if str(profile.get("profile_id") or "") == selected_profile_id
        ]
        if not selected_profiles and profiles:
            selected_profiles = [profiles[0]]
        selected_profile = selected_profiles[0] if selected_profiles else {}
        provider_id = str(selected_profile.get("selected_provider_id") or "")
        model_id = str(selected_profile.get("selected_model_id") or "")
        rows.append(
            {
                "capability_id": capability_id,
                "label": str(capability.get("label") or capability_id),
                "status": str(capability.get("status") or "disabled"),
                "selected_profile_id": selected_profile_id,
                "selected_provider_id": provider_id,
                "selected_model_id": model_id,
                "selected_connection_ids": connection_ids,
                "ready_connection_ids": ready_connection_ids,
                "runtime_provider_available": bool(
                    provider_id and provider_id in provider_adapters
                ),
                "runtime_provider_ids": sorted(provider_adapters.keys()),
                "write_posture": str(capability.get("write_posture") or ""),
                "selection_owner": str(
                    selected_profile.get("selection_owner") or "cloud_runtime_metadata"
                ),
                "direct_wordpress_write": False,
            }
        )
    return rows


def _build_feature_model_usage(
    capabilities: list[dict[str, Any]],
    runtime_profiles: list[dict[str, Any]],
    connections: list[dict[str, Any]],
    provider_call_evidence: dict[str, dict[str, Any]],
    *,
    audio_summary_text_profile_id: str,
    audio_narration_profile_id: str,
) -> list[dict[str, Any]]:
    capabilities_by_id = {str(item.get("capability_id") or ""): item for item in capabilities}
    profiles_by_id = {str(item.get("profile_id") or ""): item for item in runtime_profiles}
    connections_by_id = {str(item.get("connection_id") or ""): item for item in connections}
    specs = [
        {
            "feature_id": "content_support",
            "label": "Content Support",
            "capability_id": "text_generation",
            "profile_id": TEXT_AI_PROFILE_ID,
            "surface": "Hosted Content Support",
        },
        {
            "feature_id": "audio_summary_script",
            "label": "Audio summary script",
            "capability_id": "text_generation",
            "profile_id": audio_summary_text_profile_id,
            "surface": "Audio summary",
        },
        {
            "feature_id": "article_narration",
            "label": "Article narration",
            "capability_id": "audio_generation",
            "profile_id": audio_narration_profile_id,
            "surface": "Audio workbench",
        },
        {
            "feature_id": "article_audio_summary",
            "label": "Long-form audio summary",
            "capability_id": "audio_generation",
            "profile_id": "audio.summary.default",
            "surface": "Audio workbench",
        },
        {
            "feature_id": "generated_image_candidates",
            "label": "Generated image candidates",
            "capability_id": "image_generation",
            "profile_id": GROK_IMAGINE_IMAGE_PROFILE_ID,
            "surface": "Image generation",
        },
        {
            "feature_id": "site_knowledge_embedding",
            "label": "Site Knowledge embedding",
            "capability_id": "embedding",
            "profile_id": "embed.default",
            "surface": "Site Knowledge",
        },
        {
            "feature_id": "evidence_preflight",
            "label": "Evidence preflight",
            "capability_id": "web_search",
            "profile_id": "web-search.managed",
            "surface": "Runtime evidence",
        },
        {
            "feature_id": "image_source_candidates",
            "label": "Image source candidates",
            "capability_id": "image_source",
            "profile_id": "image-source.managed",
            "surface": "Media candidates",
        },
    ]
    rows: list[dict[str, Any]] = []
    for spec in specs:
        capability = _dict(capabilities_by_id.get(str(spec["capability_id"])))
        profile = _dict(profiles_by_id.get(str(spec["profile_id"])))
        last_run = _feature_last_run(profile)
        provider_call = provider_call_evidence.get(str(last_run.get("run_id") or ""), {})
        selected_connection_ids = _feature_connection_ids(capability, profile)
        selected_connections = [
            _dict(connections_by_id.get(connection_id))
            for connection_id in selected_connection_ids
        ]
        rows.append(
            {
                "feature_id": spec["feature_id"],
                "label": spec["label"],
                "surface": spec["surface"],
                "capability_id": spec["capability_id"],
                "profile_id": spec["profile_id"],
                "status": str(profile.get("status") or capability.get("status") or "disabled"),
                "provider_id": str(
                    provider_call.get("provider_id")
                    or last_run.get("provider_id")
                    or profile.get("selected_provider_id")
                    or ""
                ),
                "model_id": str(
                    provider_call.get("model_id")
                    or last_run.get("model_id")
                    or profile.get("selected_model_id")
                    or ""
                ),
                "connection_ids": selected_connection_ids,
                "connection_sources": sorted(
                    {
                        str(connection.get("managed_by") or "env_or_legacy")
                        for connection in selected_connections
                        if connection
                    }
                ),
                "write_posture": str(capability.get("write_posture") or ""),
                "selection_owner": str(
                    profile.get("selection_owner") or "cloud_runtime_metadata"
                ),
                "last_run": last_run,
                "last_provider_call": provider_call,
                "evidence": {
                    "run_metadata_only": True,
                    "content_exposed": False,
                    "source": "run_records+provider_call_records",
                },
                "boundary": {
                    "direct_wordpress_write": False,
                    "not_a_control_plane": True,
                },
            }
        )
    return rows


def _feature_connection_ids(
    capability: dict[str, Any],
    profile: dict[str, Any],
) -> list[str]:
    selected = str(profile.get("selected_connection_id") or "").strip()
    if selected and " + " not in selected:
        return [selected]
    values = [str(item).strip() for item in capability.get("connection_ids", [])]
    return [item for item in values if item]


def _feature_last_run(profile: dict[str, Any]) -> dict[str, Any]:
    last_run = profile.get("last_run")
    if isinstance(last_run, dict) and str(last_run.get("run_id") or ""):
        return last_run
    if isinstance(last_run, dict):
        audio = _dict(last_run.get("audio"))
        text = _dict(last_run.get("text"))
        if str(audio.get("run_id") or ""):
            return audio
        if str(text.get("run_id") or ""):
            return text
    return {}


def _runtime_profile_run_ids(runtime_profiles: list[dict[str, Any]]) -> list[str]:
    run_ids: list[str] = []
    for profile in runtime_profiles:
        last_run = profile.get("last_run")
        if isinstance(last_run, dict):
            for candidate in (
                last_run,
                _dict(last_run.get("text")),
                _dict(last_run.get("audio")),
            ):
                run_id = str(candidate.get("run_id") or "")
                if run_id and run_id not in run_ids:
                    run_ids.append(run_id)
    return run_ids


def _provider_call_evidence(
    database_url: str,
    run_ids: list[str],
) -> dict[str, dict[str, Any]]:
    if not database_url or not run_ids:
        return {}
    with get_session(database_url) as session:
        statement = (
            select(ProviderCallRecord)
            .where(ProviderCallRecord.run_id.in_(run_ids))
            .order_by(ProviderCallRecord.created_at.desc(), ProviderCallRecord.id.desc())
        )
        rows = list(session.scalars(statement))
    evidence: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.run_id in evidence:
            continue
        evidence[row.run_id] = {
            "provider_id": row.provider_id,
            "model_id": row.model_id,
            "instance_id": row.instance_id,
            "latency_ms": row.latency_ms,
            "tokens_in": row.tokens_in,
            "tokens_out": row.tokens_out,
            "cost": row.cost,
            "retry_count": row.retry_count,
            "fallback_used": bool(row.fallback_used),
            "error_code": row.error_code or "",
            "created_at": _iso(row.created_at),
        }
    return evidence


def _build_provider_model_health(
    database_url: str,
    *,
    recent_call_limit: int = 200,
    now: datetime | None = None,
) -> dict[str, Any]:
    resolved_now = now or datetime.now(UTC)
    window_specs = [
        {"window_id": "last_24h", "label": "Last 24h", "hours": 24},
        {"window_id": "last_7d", "label": "Last 7d", "hours": 168},
    ]
    windows = [
        _build_provider_model_health_window(
            database_url,
            window_id=str(spec["window_id"]),
            label=str(spec["label"]),
            hours=int(spec["hours"]),
            recent_call_limit=recent_call_limit,
            now=resolved_now,
        )
        for spec in window_specs
    ]
    default_window = windows[0] if windows else {}
    default_rows = [
        item for item in default_window.get("rows", []) if isinstance(item, dict)
    ]
    return {
        "source": "provider_call_records",
        "content_exposed": False,
        "recent_call_limit": recent_call_limit,
        "default_window_id": str(default_window.get("window_id") or "last_24h"),
        "rows": default_rows,
        "windows": windows,
        "alert_summary": _build_provider_model_alert_summary(
            default_rows,
            window_id=str(default_window.get("window_id") or "last_24h"),
        ),
        "boundary": {
            "owner": "cloud_runtime_diagnostics",
            "direct_wordpress_write": False,
            "not_a_control_plane": True,
            "prompt_router_preset_truth": False,
        },
    }


def _build_provider_model_health_window(
    database_url: str,
    *,
    window_id: str,
    label: str,
    hours: int,
    recent_call_limit: int,
    now: datetime,
) -> dict[str, Any]:
    rows: list[ProviderCallRecord] = []
    since = now - timedelta(hours=hours)
    if database_url:
        with get_session(database_url) as session:
            statement = (
                select(ProviderCallRecord)
                .where(ProviderCallRecord.created_at >= since)
                .order_by(ProviderCallRecord.created_at.desc(), ProviderCallRecord.id.desc())
                .limit(recent_call_limit)
            )
            rows = list(session.scalars(statement))

    grouped: dict[tuple[str, str], list[ProviderCallRecord]] = {}
    for row in rows:
        provider_id = str(row.provider_id or "")
        model_id = str(row.model_id or "")
        if not provider_id or not model_id:
            continue
        grouped.setdefault((provider_id, model_id), []).append(row)

    health_rows = [
        _provider_model_health_row(
            provider_id,
            model_id,
            records,
            recent_call_limit=recent_call_limit,
        )
        for (provider_id, model_id), records in grouped.items()
    ]
    status_priority = {"error": 0, "degraded": 1, "healthy": 2, "not_observed": 3}
    health_rows.sort(
        key=lambda item: (
            status_priority.get(str(item.get("status") or ""), 9),
            str(item.get("provider_id") or ""),
            str(item.get("model_id") or ""),
        )
    )
    return {
        "window_id": window_id,
        "label": label,
        "hours": hours,
        "started_at": _iso(since),
        "ended_at": _iso(now),
        "rows": health_rows,
        "alert_summary": _build_provider_model_alert_summary(
            health_rows,
            window_id=window_id,
        ),
        "evidence": {
            "source": "provider_call_records",
            "content_exposed": False,
            "recent_call_limit": recent_call_limit,
        },
    }


def _provider_model_health_row(
    provider_id: str,
    model_id: str,
    records: list[ProviderCallRecord],
    *,
    recent_call_limit: int,
) -> dict[str, Any]:
    call_count = len(records)
    success_count = sum(1 for record in records if not record.error_code)
    error_count = call_count - success_count
    latencies = sorted(
        int(record.latency_ms)
        for record in records
        if isinstance(record.latency_ms, int)
    )
    success_rate = (success_count / call_count) if call_count else 0.0
    avg_latency_ms = round(sum(latencies) / len(latencies), 2) if latencies else None
    p95_latency_ms = latencies[_percentile_index(len(latencies), 95)] if latencies else None
    status = _provider_model_health_status(
        call_count=call_count,
        success_rate=success_rate,
        p95_latency_ms=p95_latency_ms,
    )
    last_observed = max((_iso(record.created_at) for record in records), default="")
    last_error = next((record.error_code for record in records if record.error_code), "")
    return {
        "provider_id": provider_id,
        "model_id": model_id,
        "status": status,
        "call_count": call_count,
        "success_count": success_count,
        "error_count": error_count,
        "success_rate": round(success_rate, 4),
        "avg_latency_ms": avg_latency_ms,
        "p95_latency_ms": p95_latency_ms,
        "tokens_in": sum(int(record.tokens_in or 0) for record in records),
        "tokens_out": sum(int(record.tokens_out or 0) for record in records),
        "cost": round(sum(float(record.cost or 0.0) for record in records), 6),
        "retry_count": sum(int(record.retry_count or 0) for record in records),
        "fallback_count": sum(1 for record in records if bool(record.fallback_used)),
        "last_error_code": str(last_error or ""),
        "last_observed_at": last_observed,
        "evidence": {
            "source": "provider_call_records",
            "content_exposed": False,
            "recent_call_limit": recent_call_limit,
        },
        "boundary": {
            "direct_wordpress_write": False,
            "not_a_control_plane": True,
        },
    }


def _provider_model_health_status(
    *,
    call_count: int,
    success_rate: float,
    p95_latency_ms: int | None,
) -> str:
    if call_count <= 0:
        return "not_observed"
    if success_rate <= 0:
        return "error"
    if success_rate < 0.95 or (p95_latency_ms is not None and p95_latency_ms > 20_000):
        return "degraded"
    return "healthy"


def _build_provider_model_alert_summary(
    rows: list[dict[str, Any]],
    *,
    window_id: str,
) -> dict[str, Any]:
    alerts: list[dict[str, Any]] = []
    for row in rows:
        provider_id = str(row.get("provider_id") or "")
        model_id = str(row.get("model_id") or "")
        status = str(row.get("status") or "")
        if status == "error":
            alerts.append(
                _provider_model_alert(
                    code="provider_model.all_calls_failed",
                    severity="error",
                    provider_id=provider_id,
                    model_id=model_id,
                    message="All observed calls failed in this window.",
                    row=row,
                )
            )
        elif status == "degraded":
            alerts.append(
                _provider_model_alert(
                    code="provider_model.degraded",
                    severity="warning",
                    provider_id=provider_id,
                    model_id=model_id,
                    message="Success rate or p95 latency is outside the operator threshold.",
                    row=row,
                )
            )
        if float(row.get("cost") or 0.0) >= 1.0:
            alerts.append(
                _provider_model_alert(
                    code="provider_model.cost_threshold",
                    severity="warning",
                    provider_id=provider_id,
                    model_id=model_id,
                    message="Observed cost crossed the diagnostic threshold for this window.",
                    row=row,
                )
            )
        if int(row.get("fallback_count") or 0) > 0:
            alerts.append(
                _provider_model_alert(
                    code="provider_model.fallback_used",
                    severity="info",
                    provider_id=provider_id,
                    model_id=model_id,
                    message="Fallback was used for this provider/model in this window.",
                    row=row,
                )
            )
    severity_counts = {
        "error": sum(1 for item in alerts if item.get("severity") == "error"),
        "warning": sum(1 for item in alerts if item.get("severity") == "warning"),
        "info": sum(1 for item in alerts if item.get("severity") == "info"),
    }
    return {
        "window_id": window_id,
        "alert_count": len(alerts),
        "severity_counts": severity_counts,
        "thresholds": {
            "minimum_success_rate": 0.95,
            "p95_latency_ms": 20_000,
            "cost": 1.0,
        },
        "alerts": alerts[:20],
        "boundary": {
            "direct_wordpress_write": False,
            "not_a_control_plane": True,
            "automatic_routing_change": False,
        },
    }


def _provider_model_alert(
    *,
    code: str,
    severity: str,
    provider_id: str,
    model_id: str,
    message: str,
    row: dict[str, Any],
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "provider_id": provider_id,
        "model_id": model_id,
        "message": message,
        "evidence": {
            "status": str(row.get("status") or ""),
            "call_count": int(row.get("call_count") or 0),
            "success_rate": float(row.get("success_rate") or 0.0),
            "p95_latency_ms": row.get("p95_latency_ms"),
            "cost": float(row.get("cost") or 0.0),
            "fallback_count": int(row.get("fallback_count") or 0),
            "content_exposed": False,
        },
    }


def _percentile_index(count: int, percentile: int) -> int:
    if count <= 1:
        return 0
    return min(count - 1, max(0, ((count * percentile) + 99) // 100 - 1))


def _build_env_migration_summary(
    settings: Settings,
    managed_connections: list[dict[str, Any]],
) -> dict[str, Any]:
    managed_ids = {str(item.get("provider_id") or "") for item in managed_connections}
    sources = [
        {
            "connection_id": "openai_env",
            "provider_id": "openai",
            "label": "OpenAI-compatible",
            "source": "env",
            "configured": bool(str(settings.openai_api_key or "").strip()),
            "managed_connection_present": "openai" in managed_ids,
            "env_keys": [
                "NPCINK_CLOUD_OPENAI_API_KEY",
                "NPCINK_CLOUD_OPENAI_BASE_URL",
                "NPCINK_CLOUD_OPENAI_PROVIDER_LABEL",
            ],
            "import_supported": True,
        },
        {
            "connection_id": "minimax_env",
            "provider_id": "minimax",
            "label": "MiniMax",
            "source": "env",
            "configured": bool(str(settings.minimax_api_key or "").strip()),
            "managed_connection_present": "minimax" in managed_ids,
            "env_keys": [
                "NPCINK_CLOUD_MINIMAX_API_KEY",
                "NPCINK_CLOUD_MINIMAX_BASE_URL",
                "NPCINK_CLOUD_MINIMAX_GROUP_ID",
            ],
            "import_supported": True,
        },
    ]
    configured_env_sources = [
        source for source in sources if bool(source.get("configured"))
    ]
    importable_sources = [
        source
        for source in configured_env_sources
        if not bool(source.get("managed_connection_present"))
    ]
    return {
        "surface": "admin_provider_connection_env_migration",
        "env_path": str(settings.ai_resources_admin_env_path or ".env.local"),
        "configured_env_source_count": len(configured_env_sources),
        "importable_source_count": len(importable_sources),
        "sources": sources,
        "recommended_primary": "provider_connections",
        "env_role": "fallback",
        "secret_exposure": "presence_only",
        "boundary": {
            "owner": "cloud_runtime",
            "direct_wordpress_write": False,
            "not_a_control_plane": True,
        },
    }


def _has_configured_provider(providers: dict[str, Any]) -> bool:
    return any(bool(_dict(provider).get("configured")) for provider in providers.values())


def _configured_provider_ids(
    config: dict[str, Any],
    *,
    connection_prefix: str,
) -> list[str]:
    providers = _dict(config.get("providers"))
    return [
        f"{connection_prefix}_{provider_id}"
        for provider_id, provider in providers.items()
        if bool(_dict(provider).get("configured"))
    ]


def _managed_provider_connections(
    settings: Settings,
    database_url: str,
) -> list[dict[str, Any]]:
    if not database_url:
        return []
    try:
        result = ProviderConnectionAdminService(database_url, settings).list_connections()
    except Exception:
        return []
    connections = result.get("connections")
    if not isinstance(connections, list):
        return []
    return [item for item in connections if isinstance(item, dict)]


def _connection_ids_by_capability(
    connections: list[dict[str, Any]],
) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for connection in connections:
        if not bool(connection.get("configured")):
            continue
        connection_id = str(connection.get("connection_id") or "")
        if not connection_id:
            continue
        for capability_id in connection.get("capability_ids") or []:
            grouped.setdefault(str(capability_id), []).append(connection_id)
    return grouped


def _ready_by_capability(connections: list[dict[str, Any]]) -> dict[str, bool]:
    ready: dict[str, bool] = {}
    for connection in connections:
        if connection.get("status") != "ready":
            continue
        for capability_id in connection.get("capability_ids") or []:
            ready[str(capability_id)] = True
    return ready


def _merge_connections(
    base_connections: list[dict[str, Any]],
    managed_connections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for connection in base_connections + managed_connections:
        connection_id = str(connection.get("connection_id") or "")
        if not connection_id:
            continue
        merged[connection_id] = connection
    return list(merged.values())


def _merge_ids(base_ids: list[str], extra_ids: list[str]) -> list[str]:
    merged: list[str] = []
    for item in base_ids + extra_ids:
        if item and item not in merged:
            merged.append(item)
    return merged


def _site_knowledge_embedding_configured(settings: Settings) -> bool:
    provider = str(settings.site_knowledge_embedding_provider or "deterministic")
    if provider == "deterministic":
        return True
    if provider == "tei":
        return bool(settings.tei_provider_enabled and str(settings.tei_base_url or "").strip())
    if provider == "openai":
        return bool(str(settings.openai_api_key or "").strip())
    if provider == "siliconflow":
        return bool(
            settings.siliconflow_provider_enabled
            and str(settings.siliconflow_api_key or "").strip()
        )
    return False


def _site_knowledge_embedding_base_url(settings: Settings) -> str:
    provider = str(settings.site_knowledge_embedding_provider or "deterministic")
    if provider == "tei":
        return str(settings.tei_base_url or "")
    if provider == "openai":
        return str(settings.openai_base_url or "")
    if provider == "siliconflow":
        return str(settings.siliconflow_base_url or "")
    return "local-deterministic"


def _build_capability_matrix(
    capabilities: list[dict[str, Any]],
    runtime_profiles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    profiles_by_capability: dict[str, list[dict[str, Any]]] = {}
    for profile in runtime_profiles:
        profiles_by_capability.setdefault(str(profile.get("capability_id") or ""), []).append(
            profile
        )

    rows: list[dict[str, Any]] = []
    for capability in capabilities:
        capability_id = str(capability["capability_id"])
        profiles = profiles_by_capability.get(capability_id, [])
        selected_profiles = [
            profile
            for profile in profiles
            if profile.get("profile_id") == capability.get("default_profile_id")
            or profile.get("selected_for")
        ]
        rows.append(
            {
                "capability_id": capability_id,
                "label": capability["label"],
                "status": capability["status"],
                "used_by": capability["used_by"],
                "write_posture": capability["write_posture"],
                "default_profile_id": capability["default_profile_id"],
                "connection_ids": capability["connection_ids"],
                "profiles": selected_profiles or profiles,
                "selection_owner": "cloud_runtime_metadata",
                "direct_wordpress_write": False,
            }
        )
    return rows


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


def _iso(value: Any) -> str:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else ""


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
