from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.models import AudioAsset, RunRecord
from app.domain.media_derivatives.artifacts import get_artifact, is_artifact_expired

AUDIO_ASSET_STATUS_ACTIVE = "active"
AUDIO_ASSET_STATUS_REVOKED = "revoked"
AUDIO_ASSET_DEFAULT_PLAYBACK_TTL_SECONDS = 15 * 60
AUDIO_ASSET_MAX_PLAYBACK_TTL_SECONDS = 60 * 60


class AudioAssetError(RuntimeError):
    status_code = 400
    error_code = "audio_asset.error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AudioAssetNotFoundError(AudioAssetError):
    status_code = 404
    error_code = "audio_asset.not_found"


class AudioAssetArtifactInvalidError(AudioAssetError):
    status_code = 422
    error_code = "audio_asset.source_artifact_invalid"


class AudioAssetPlaybackTokenInvalidError(AudioAssetError):
    status_code = 403
    error_code = "audio_asset.playback_token_invalid"


class AudioAssetPlaybackTokenExpiredError(AudioAssetError):
    status_code = 410
    error_code = "audio_asset.playback_token_expired"


class AudioAssetSigningNotConfiguredError(AudioAssetError):
    status_code = 503
    error_code = "audio_asset.signing_not_configured"


@dataclass(frozen=True)
class PlaybackUrl:
    url: str
    expires_at: datetime
    ttl_seconds: int


def promote_audio_asset_from_artifact(
    *,
    session: Session,
    site_id: str,
    artifact_id: str,
    source_content_hash: str = "",
    metadata: dict[str, Any] | None = None,
) -> AudioAsset:
    artifact = get_artifact(session, artifact_id, site_id=site_id)
    if artifact is None:
        raise AudioAssetNotFoundError("audio source artifact was not found")
    if is_artifact_expired(artifact):
        raise AudioAssetArtifactInvalidError("audio source artifact has expired")
    if artifact.source_media_type != "audio":
        raise AudioAssetArtifactInvalidError("source artifact is not an audio artifact")
    if not artifact.blob_data:
        raise AudioAssetArtifactInvalidError("source artifact has no audio payload")

    existing = session.scalar(
        select(AudioAsset).where(
            AudioAsset.site_id == site_id,
            AudioAsset.source_artifact_id == artifact.artifact_id,
            AudioAsset.status == AUDIO_ASSET_STATUS_ACTIVE,
        )
    )
    if existing is not None:
        return existing

    run = session.get(RunRecord, artifact.run_id)
    candidate = _candidate_for_artifact(run.result_json if run is not None else None, artifact_id)
    asset_id = f"aud_{uuid4().hex}"
    asset = AudioAsset(
        asset_id=asset_id,
        site_id=site_id,
        source_artifact_id=artifact.artifact_id,
        source_run_id=artifact.run_id,
        status=AUDIO_ASSET_STATUS_ACTIVE,
        storage_ref=f"blob://audio_asset/{asset_id}",
        blob_data=artifact.blob_data,
        mime_type=artifact.mime_type,
        format=artifact.format,
        duration_seconds=_coerce_float(candidate.get("duration_seconds"), default=0.0),
        filesize_bytes=artifact.filesize_bytes,
        checksum=artifact.checksum,
        source_content_hash=_normalize_source_content_hash(source_content_hash),
        provider_id=str(run.selected_provider_id or "") if run is not None else None,
        model_id=str(run.selected_model_id or "") if run is not None else None,
        trace_id=str(run.trace_id or "") if run is not None else None,
        metadata_json={
            "asset_kind": "article_audio",
            "playback_mode": "cloud_hosted",
            "direct_wordpress_write": False,
            "source_artifact_expires_at": (
                artifact.expires_at.isoformat() if artifact.expires_at else None
            ),
            "source": {
                "artifact_id": artifact.artifact_id,
                "run_id": artifact.run_id,
                "provider_id": str(run.selected_provider_id or "") if run is not None else "",
                "model_id": str(run.selected_model_id or "") if run is not None else "",
                "trace_id": str(run.trace_id or "") if run is not None else "",
            },
            "candidate": _safe_candidate_metadata(candidate),
            "adoption_metadata": _safe_metadata(metadata or {}),
        },
    )
    session.add(asset)
    session.flush()
    return asset


def get_audio_asset(
    session: Session,
    asset_id: str,
    *,
    site_id: str | None = None,
) -> AudioAsset | None:
    statement = select(AudioAsset).where(AudioAsset.asset_id == asset_id)
    if site_id:
        statement = statement.where(AudioAsset.site_id == site_id)
    return session.scalar(statement)


def require_active_audio_asset(
    session: Session,
    asset_id: str,
    *,
    site_id: str | None = None,
) -> AudioAsset:
    asset = get_audio_asset(session, asset_id, site_id=site_id)
    if asset is None:
        raise AudioAssetNotFoundError("audio asset was not found")
    if asset.status != AUDIO_ASSET_STATUS_ACTIVE or asset.revoked_at is not None:
        raise AudioAssetNotFoundError("audio asset is not active")
    return asset


def build_audio_asset_projection(
    asset: AudioAsset,
    *,
    playback_url: PlaybackUrl | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "asset_id": asset.asset_id,
        "site_id": asset.site_id,
        "status": asset.status,
        "playback_mode": "cloud_hosted",
        "storage": "cloud_audio_asset",
        "source_artifact_id": asset.source_artifact_id,
        "source_run_id": asset.source_run_id,
        "duration_seconds": asset.duration_seconds,
        "mime_type": asset.mime_type,
        "format": asset.format,
        "filesize_bytes": asset.filesize_bytes,
        "checksum": asset.checksum,
        "source_content_hash": asset.source_content_hash,
        "provider_id": asset.provider_id,
        "model_id": asset.model_id,
        "trace_id": asset.trace_id,
        "direct_wordpress_write": False,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
    }
    if playback_url is not None:
        data["playback_url"] = playback_url.url
        data["playback_url_expires_at"] = playback_url.expires_at.isoformat()
        data["playback_url_ttl_seconds"] = playback_url.ttl_seconds
    return data


def build_audio_asset_playback_url(
    asset: AudioAsset,
    *,
    settings: Settings,
    ttl_seconds: int | None = None,
) -> PlaybackUrl:
    ttl = _resolve_playback_ttl(settings, ttl_seconds)
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
    expires = int(expires_at.timestamp())
    token = _sign_playback_token(asset, settings=settings, expires=expires)
    return PlaybackUrl(
        url=f"/v1/runtime/audio-assets/{asset.asset_id}/playback?expires={expires}&token={token}",
        expires_at=expires_at,
        ttl_seconds=ttl,
    )


def validate_audio_asset_playback_token(
    asset: AudioAsset,
    *,
    settings: Settings,
    expires: int,
    token: str,
) -> None:
    if datetime.fromtimestamp(expires, tz=UTC) <= datetime.now(UTC):
        raise AudioAssetPlaybackTokenExpiredError("audio asset playback URL has expired")
    expected = _sign_playback_token(asset, settings=settings, expires=expires)
    if not token or not hmac.compare_digest(expected, token):
        raise AudioAssetPlaybackTokenInvalidError("audio asset playback token is invalid")


def _sign_playback_token(asset: AudioAsset, *, settings: Settings, expires: int) -> str:
    secret = _playback_secret(settings)
    payload = "|".join(
        [
            asset.asset_id,
            asset.site_id,
            str(expires),
            str(asset.checksum or ""),
            str(asset.status or ""),
        ]
    )
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _playback_secret(settings: Settings) -> str:
    secret = str(
        settings.audio_asset_playback_token_secret
        or settings.admin_session_secret
        or settings.internal_auth_token
        or ""
    ).strip()
    if not secret:
        raise AudioAssetSigningNotConfiguredError("audio asset playback signing is not configured")
    return secret


def _resolve_playback_ttl(settings: Settings, ttl_seconds: int | None) -> int:
    default_ttl = max(60, int(settings.audio_asset_playback_url_ttl_seconds or 0))
    max_ttl = max(60, int(settings.audio_asset_playback_url_max_ttl_seconds or 0))
    requested = default_ttl if ttl_seconds is None or ttl_seconds <= 0 else int(ttl_seconds)
    return max(60, min(requested, max_ttl))


def _candidate_for_artifact(result_json: Any, artifact_id: str) -> dict[str, Any]:
    if not isinstance(result_json, dict):
        return {}
    for key in ("audios", "items"):
        items = result_json.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("artifact_id") or "") == artifact_id:
                return item
            artifact = item.get("artifact")
            if isinstance(artifact, dict) and str(artifact.get("artifact_id") or "") == artifact_id:
                return item
    return {}


def _safe_candidate_metadata(candidate: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "intent",
        "voice_id",
        "duration_seconds",
        "mime_type",
        "format",
        "size_bytes",
        "provider_url_status",
    }
    return {key: candidate[key] for key in allowed if key in candidate}


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "post_id",
        "post_type",
        "post_status",
        "source_content_hash",
        "content_version",
        "title",
    }
    safe: dict[str, Any] = {}
    for key in allowed:
        value = metadata.get(key)
        if isinstance(value, str):
            safe[key] = value[:512]
        elif isinstance(value, int | float | bool):
            safe[key] = value
    return safe


def _normalize_source_content_hash(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized.startswith("sha256:"):
        normalized = normalized[7:]
    normalized = "".join(ch for ch in normalized if ch in "0123456789abcdef")
    if len(normalized) == 64:
        return f"sha256:{normalized}"
    return ""


def _coerce_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
