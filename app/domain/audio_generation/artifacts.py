from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy.orm import Session

from app.core.models import MediaArtifact, RunRecord
from app.domain.media_artifacts import ArtifactStore
from app.domain.media_artifacts.publication import publish_and_track_artifact

AUDIO_ARTIFACT_DEFAULT_TTL_MINUTES = 60
AUDIO_ARTIFACT_DEFAULT_MAX_BYTES = 24 * 1024 * 1024
AUDIO_ARTIFACT_DEFAULT_TIMEOUT_SECONDS = 20.0

_AUDIO_MIME_BY_FORMAT = {
    "mp3": "audio/mpeg",
    "mpeg": "audio/mpeg",
    "wav": "audio/wav",
    "wave": "audio/wav",
    "pcm": "audio/L16",
}
_ALLOWED_AUDIO_MIME_PREFIXES = ("audio/", "application/octet-stream")


@dataclass(frozen=True)
class AudioArtifactMaterializationConfig:
    ttl_minutes: int = AUDIO_ARTIFACT_DEFAULT_TTL_MINUTES
    max_bytes: int = AUDIO_ARTIFACT_DEFAULT_MAX_BYTES
    timeout_seconds: float = AUDIO_ARTIFACT_DEFAULT_TIMEOUT_SECONDS


class AudioArtifactMaterializationError(RuntimeError):
    error_code = "audio_generation.artifact_materialization_failed"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def materialize_audio_generation_candidates(
    *,
    session: Session,
    run: RunRecord,
    result_json: dict[str, Any],
    artifact_store: ArtifactStore,
    config: AudioArtifactMaterializationConfig | None = None,
) -> dict[str, Any]:
    if not _is_audio_generation_result(result_json):
        return result_json

    materialize_config = config or AudioArtifactMaterializationConfig()
    audios = result_json.get("audios")
    if not isinstance(audios, list) or not audios:
        raise AudioArtifactMaterializationError(
            "provider audio result did not contain an audio candidate"
        )
    if len(audios) != 1:
        raise AudioArtifactMaterializationError(
            "provider audio result must contain exactly one audio candidate"
        )

    next_audios: list[dict[str, Any]] = []
    materialized_count = 0
    for raw_audio in audios:
        if not isinstance(raw_audio, dict):
            raise AudioArtifactMaterializationError(
                "provider audio result contained an invalid audio candidate"
            )
        audio = dict(raw_audio)
        audio_bytes, source_kind, source_url = _audio_bytes_for_candidate(
            audio,
            config=materialize_config,
        )
        if not audio_bytes:
            raise AudioArtifactMaterializationError(
                "provider audio candidate did not contain materializable bytes"
            )

        audio_format = _safe_audio_format(audio.get("format"))
        mime_type = _safe_audio_mime(audio.get("mime_type"), audio_format)
        artifact = _create_audio_artifact(
            session=session,
            run=run,
            audio_bytes=audio_bytes,
            audio_format=audio_format,
            mime_type=mime_type,
            ttl_minutes=materialize_config.ttl_minutes,
            source_kind=source_kind,
            source_url_present=bool(source_url),
            artifact_store=artifact_store,
        )
        for credential_field in (
            "url",
            "audio_url",
            "download_url",
            "authenticated_download_url",
            "subtitle_url",
            "b64_json",
            "base64",
            "data_url",
        ):
            audio.pop(credential_field, None)
        audio.update(
            {
                "artifact_id": artifact.artifact_id,
                "artifact": {
                    "artifact_id": artifact.artifact_id,
                    "artifact_reference": {"artifact_id": artifact.artifact_id},
                    "expires_at": artifact.expires_at.isoformat() if artifact.expires_at else None,
                    "mime_type": artifact.content_type,
                    "format": artifact.format,
                    "filesize_bytes": artifact.byte_size,
                    "checksum": artifact.checksum,
                    "source_media_type": "audio",
                },
                "mime_type": mime_type,
                "format": audio_format,
                "size_bytes": artifact.byte_size,
                "provider_url_status": "materialized",
            }
        )
        next_audios.append(audio)
        materialized_count += 1

    next_result = dict(result_json)
    next_result["audios"] = next_audios
    if isinstance(next_result.get("items"), list):
        next_result["items"] = next_audios
    next_result["provider_response_format"] = "artifact_reference"
    next_result["audio_materialization"] = {
        "status": "materialized",
        "artifact_count": materialized_count,
        "storage": "cloud_short_ttl_artifact",
        "direct_wordpress_write": False,
    }
    return next_result


def _is_audio_generation_result(result_json: dict[str, Any]) -> bool:
    return str(result_json.get("artifact_type") or "") == "audio_generation_candidates"


def _audio_bytes_for_candidate(
    audio: dict[str, Any],
    *,
    config: AudioArtifactMaterializationConfig,
) -> tuple[bytes, str, str]:
    b64 = str(audio.get("b64_json") or "").strip()
    if b64:
        try:
            audio_bytes = base64.b64decode(b64, validate=True)
        except ValueError as error:
            raise AudioArtifactMaterializationError(
                "audio candidate contained invalid base64 data"
            ) from error
        _enforce_audio_size(audio_bytes, config.max_bytes)
        return audio_bytes, "b64_json", ""

    source_url = str(audio.get("url") or audio.get("audio_url") or "").strip()
    if not source_url.lower().startswith(("http://", "https://")):
        return b"", "", ""
    return _download_audio_url(source_url, config=config), "provider_url", source_url


def _download_audio_url(
    source_url: str,
    *,
    config: AudioArtifactMaterializationConfig,
) -> bytes:
    try:
        with httpx.Client(timeout=config.timeout_seconds, follow_redirects=True) as client:
            response = client.get(source_url)
    except httpx.RequestError as error:
        raise AudioArtifactMaterializationError(
            "provider audio URL could not be downloaded"
        ) from error

    if response.status_code < 200 or response.status_code >= 300:
        raise AudioArtifactMaterializationError(
            f"provider audio URL returned HTTP {response.status_code}"
        )

    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type and not content_type.startswith(_ALLOWED_AUDIO_MIME_PREFIXES):
        raise AudioArtifactMaterializationError(
            f"provider audio URL returned unsupported content type {content_type}"
        )

    audio_bytes = response.content
    _enforce_audio_size(audio_bytes, config.max_bytes)
    return audio_bytes


def _enforce_audio_size(audio_bytes: bytes, max_bytes: int) -> None:
    if not audio_bytes:
        raise AudioArtifactMaterializationError("provider audio payload was empty")
    if len(audio_bytes) > max(1, int(max_bytes)):
        raise AudioArtifactMaterializationError("provider audio payload exceeded size limit")


def _create_audio_artifact(
    *,
    session: Session,
    run: RunRecord,
    audio_bytes: bytes,
    audio_format: str,
    mime_type: str,
    ttl_minutes: int,
    source_kind: str,
    source_url_present: bool,
    artifact_store: ArtifactStore,
) -> MediaArtifact:
    artifact_id = f"art_{uuid4().hex}"
    stored = publish_and_track_artifact(
        session,
        store=artifact_store,
        stream=BytesIO(audio_bytes),
        max_bytes=len(audio_bytes),
        metadata={"media_kind": "audio"},
    )
    now = datetime.now(UTC)
    artifact = MediaArtifact(
        artifact_id=artifact_id,
        run_id=run.run_id,
        site_id=run.site_id,
        storage_key=stored.storage_key,
        media_kind="audio",
        operation="audio_generation",
        content_type=mime_type,
        byte_size=stored.byte_size,
        status="available",
        format=audio_format,
        width=0,
        height=0,
        checksum=stored.checksum,
        processing_warnings_json={
            "warnings": [],
            "source_kind": source_kind,
            "provider_url_present": source_url_present,
        },
        expires_at=now + timedelta(minutes=max(1, int(ttl_minutes))),
    )
    session.add(artifact)
    session.flush()
    return artifact


def _safe_audio_format(value: Any) -> str:
    normalized = "".join(
        ch for ch in str(value or "mp3").strip().lower() if ch.isalnum() or ch in {"+", "-"}
    )
    return normalized if normalized in _AUDIO_MIME_BY_FORMAT else "mp3"


def _safe_audio_mime(value: Any, audio_format: str) -> str:
    mime_type = str(value or "").split(";", 1)[0].strip().lower()
    if mime_type.startswith("audio/"):
        return mime_type
    return _AUDIO_MIME_BY_FORMAT.get(audio_format, "audio/mpeg")
