from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import select

from app.adapters.providers.base import ProviderAdapter
from app.core.config import Settings
from app.core.db import get_session
from app.core.models import ProviderCallRecord, RunRecord
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
from app.domain.provider_connections.service import ProviderConnectionAdminService


def build_admin_ai_resource_projection(
    settings: Settings,
    *,
    providers: dict[str, ProviderAdapter] | None = None,
    database_url: str | None = None,
) -> dict[str, Any]:
    provider_adapters = providers or {}
    default_audio_profile_id = AUDIO_NARRATION_PROFILE_ID
    default_summary_script_profile_id = TEXT_AI_PROFILE_ID
    default_summary_playback_profile_id = AUDIO_NARRATION_PROFILE_ID
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
    text_connection_id = _first_connection_id_for_capability(
        managed_connections,
        "text_generation",
        fallback="openai" if "openai" in provider_adapters else "",
    )
    text_provider_id = _provider_id_for_connection(
        managed_connections,
        text_connection_id,
        fallback="openai" if "openai" in provider_adapters else "",
    )
    text_configured = bool(text_connection_id)
    audio_connection_id = _first_connection_id_for_capability(
        managed_connections,
        "audio_generation",
        fallback="minimax" if "minimax" in provider_adapters else "",
    )
    audio_provider_id = _provider_id_for_connection(
        managed_connections,
        audio_connection_id,
        fallback="minimax" if "minimax" in provider_adapters else "",
    )
    audio_status = "ready" if audio_connection_id else "missing_secret"
    image_generation_connection_id = _first_connection_id_for_capability(
        managed_connections,
        "image_generation",
        fallback=text_connection_id,
    )
    image_generation_provider_id = _provider_id_for_connection(
        managed_connections,
        image_generation_connection_id,
        fallback=text_provider_id,
    )
    embedding_provider = str(settings.site_knowledge_embedding_provider or "deterministic")
    embedding_model = str(settings.site_knowledge_embedding_model or "BAAI/bge-m3")
    embedding_connection_id = _first_connection_id_for_capability(
        managed_connections,
        "embedding",
        fallback="" if embedding_provider == "deterministic" else f"embedding_{embedding_provider}",
    )

    connections = _merge_connections([], managed_connections)

    capabilities = [
        {
            "capability_id": "text_generation",
            "label": "Text generation",
            "status": "ready"
            if text_configured or managed_ready_by_capability.get("text_generation")
            else "missing_provider",
            "default_profile_id": default_summary_script_profile_id,
            "connection_ids": _merge_ids(
                [text_connection_id] if text_connection_id else [],
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
            "default_profile_id": default_audio_profile_id,
            "connection_ids": _merge_ids(
                [audio_connection_id] if audio_connection_id else [],
                managed_connection_ids_by_capability.get("audio_generation", []),
            ),
            "used_by": ["Article narration", "Audio summary playback"],
            "write_posture": "candidate_artifact_only",
        },
        {
            "capability_id": "web_search",
            "label": "Web search",
            "status": "ready" if managed_ready_by_capability.get("web_search") else "disabled",
            "default_profile_id": "web-search.managed",
            "connection_ids": managed_connection_ids_by_capability.get("web_search", []),
            "used_by": ["Evidence preflight"],
            "write_posture": "suggestion_only",
        },
        {
            "capability_id": "image_source",
            "label": "Image source",
            "status": "ready" if managed_ready_by_capability.get("image_source") else "disabled",
            "default_profile_id": "image-source.managed",
            "connection_ids": managed_connection_ids_by_capability.get("image_source", []),
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
                [image_generation_connection_id] if image_generation_connection_id else [],
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
                [embedding_connection_id] if embedding_connection_id else [],
                managed_connection_ids_by_capability.get("embedding", []),
            ),
            "used_by": ["Site Knowledge"],
            "write_posture": "runtime_metadata_only",
        },
    ]

    audio_summary_connection_label = (
        f"{text_connection_id or default_summary_script_profile_id} + "
        f"{audio_connection_id or default_summary_playback_profile_id}"
    )
    audio_summary_provider_label = f"{text_provider_id or 'text'} + {audio_provider_id or 'audio'}"
    runtime_profiles = [
        {
            "profile_id": TEXT_AI_PROFILE_ID,
            "kind": "runtime_profile",
            "capability_id": "text_generation",
            "selected_connection_id": text_connection_id,
            "selected_provider_id": text_provider_id,
            "selected_model_id": FREE_GPT55_MODEL_ID,
            "status": "ready" if text_configured else "missing_provider",
            "selection_owner": "cloud_runtime_metadata",
            "used_by": ["Hosted Content Support", "Audio summary script"],
            "last_run": recent_runs.get(TEXT_AI_PROFILE_ID, {}),
            "selected_for": (
                ["audio_summary_script"]
                if default_summary_script_profile_id == TEXT_AI_PROFILE_ID
                else []
            ),
        },
        {
            "profile_id": FREE_GPT55_TEXT_PROFILE_ID,
            "kind": "runtime_profile",
            "capability_id": "text_generation",
            "selected_connection_id": text_connection_id,
            "selected_provider_id": text_provider_id,
            "selected_model_id": FREE_GPT55_MODEL_ID,
            "status": "ready" if text_configured else "missing_provider",
            "selection_owner": "cloud_runtime_metadata",
            "used_by": ["Audio summary script"],
            "last_run": recent_runs.get(FREE_GPT55_TEXT_PROFILE_ID, {}),
            "selected_for": (
                ["audio_summary_script"]
                if default_summary_script_profile_id == FREE_GPT55_TEXT_PROFILE_ID
                else []
            ),
        },
        {
            "profile_id": AUDIO_NARRATION_PROFILE_ID,
            "kind": "runtime_profile",
            "capability_id": "audio_generation",
            "selected_connection_id": audio_connection_id,
            "selected_provider_id": audio_provider_id,
            "selected_model_id": AUDIO_NARRATION_MODEL_ID,
            "status": "ready" if audio_status == "ready" else "missing_provider",
            "selection_owner": "cloud_runtime_metadata",
            "used_by": ["Article narration", "Audio summary playback"],
            "last_run": recent_runs.get(AUDIO_NARRATION_PROFILE_ID, {}),
            "selected_for": _audio_selected_for(
                AUDIO_NARRATION_PROFILE_ID,
                default_audio_profile_id=default_audio_profile_id,
                default_summary_playback_profile_id=default_summary_playback_profile_id,
            ),
        },
        {
            "profile_id": AUDIO_NARRATION_QUALITY_PROFILE_ID,
            "kind": "runtime_profile",
            "capability_id": "audio_generation",
            "selected_connection_id": audio_connection_id,
            "selected_provider_id": audio_provider_id,
            "selected_model_id": AUDIO_NARRATION_QUALITY_MODEL_ID,
            "status": "ready" if audio_status == "ready" else "missing_provider",
            "selection_owner": "cloud_runtime_metadata",
            "used_by": ["Article narration", "Audio summary playback"],
            "last_run": recent_runs.get(AUDIO_NARRATION_QUALITY_PROFILE_ID, {}),
            "selected_for": _audio_selected_for(
                AUDIO_NARRATION_QUALITY_PROFILE_ID,
                default_audio_profile_id=default_audio_profile_id,
                default_summary_playback_profile_id=default_summary_playback_profile_id,
            ),
        },
        {
            "profile_id": "audio.summary.default",
            "kind": "pipeline_profile",
            "capability_id": "audio_generation",
            "selected_connection_id": audio_summary_connection_label,
            "selected_provider_id": audio_summary_provider_label,
            "selected_model_id": (f"{FREE_GPT55_MODEL_ID} + {AUDIO_NARRATION_MODEL_ID}"),
            "status": "ready"
            if text_configured and audio_status == "ready"
            else "missing_provider",
            "selection_owner": "cloud_runtime_metadata",
            "used_by": ["Long-form audio summary"],
            "last_run": _pipeline_last_run(
                recent_runs,
                text_profile_id=default_summary_script_profile_id,
                audio_profile_id=default_summary_playback_profile_id,
            ),
            "selected_for": ["article_audio_summary"],
        },
        {
            "profile_id": GROK_IMAGINE_IMAGE_PROFILE_ID,
            "kind": "runtime_profile",
            "capability_id": "image_generation",
            "selected_connection_id": image_generation_connection_id,
            "selected_provider_id": image_generation_provider_id,
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
            "selected_connection_id": embedding_connection_id,
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
        default_summary_script_profile_id=default_summary_script_profile_id,
        default_audio_profile_id=default_audio_profile_id,
    )
    provider_model_health = _build_provider_model_health(resolved_database_url)

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


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _audio_selected_for(
    profile_id: str,
    *,
    default_audio_profile_id: str,
    default_summary_playback_profile_id: str,
) -> list[str]:
    selected: list[str] = []
    if profile_id == default_audio_profile_id:
        selected.append("article_narration")
    if profile_id == default_summary_playback_profile_id:
        selected.append("article_audio_summary")
    return selected


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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
    default_summary_script_profile_id: str,
    default_audio_profile_id: str,
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
            "profile_id": default_summary_script_profile_id,
            "surface": "Audio summary",
        },
        {
            "feature_id": "article_narration",
            "label": "Article narration",
            "capability_id": "audio_generation",
            "profile_id": default_audio_profile_id,
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
            _dict(connections_by_id.get(connection_id)) for connection_id in selected_connection_ids
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
                "selection_owner": str(profile.get("selection_owner") or "cloud_runtime_metadata"),
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
            hours=int(cast(Any, spec["hours"])),
            recent_call_limit=recent_call_limit,
            now=resolved_now,
        )
        for spec in window_specs
    ]
    default_window = windows[0] if windows else {}
    default_rows = [item for item in default_window.get("rows", []) if isinstance(item, dict)]
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
        int(record.latency_ms) for record in records if isinstance(record.latency_ms, int)
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


def _normalize_id_list(value: object) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = str(value or "").split(",")
    normalized: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _first_connection_id_for_capability(
    connections: list[dict[str, Any]],
    capability_id: str,
    *,
    fallback: str = "",
) -> str:
    for connection in connections:
        if (
            bool(connection.get("configured"))
            and bool(connection.get("enabled", True))
            and capability_id in _normalize_id_list(connection.get("capability_ids"))
        ):
            return str(connection.get("connection_id") or "")
    return fallback


def _provider_id_for_connection(
    connections: list[dict[str, Any]],
    connection_id: str,
    *,
    fallback: str = "",
) -> str:
    for connection in connections:
        if str(connection.get("connection_id") or "") == connection_id:
            return str(connection.get("provider_id") or "")
    return fallback


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
