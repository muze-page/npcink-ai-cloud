from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import BinaryIO
from uuid import uuid4

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import MediaArtifact
from app.domain.agent_workflow_metadata import (
    MEDIA_DERIVATIVE_WORKFLOW_ID,
    get_workflow_metadata,
    metadata_projection_tokens,
)
from app.domain.media_artifacts import ArtifactStorageMetadata, ArtifactStore, ArtifactStoreError
from app.domain.media_artifacts.publication import publish_and_track_artifact
from app.domain.media_derivatives.contracts import (
    ARTIFACT_DEFAULT_TTL_MINUTES,
    MAX_IMAGE_DIMENSION,
    MAX_PIXEL_COUNT,
    MAX_UPLOAD_BYTES_IMAGE,
    MEDIA_DERIVATIVE_ARTIFACT_TYPE,
    MEDIA_DERIVATIVE_RESULT_CONTRACT,
    MEDIA_UPLOAD_ARTIFACT_TYPE,
    MEDIA_UPLOAD_RESULT_CONTRACT,
)
from app.domain.media_derivatives.errors import (
    MediaDerivativeAnimatedSourceUnavailableError,
    MediaDerivativeSourceDecodeFailedError,
    MediaDerivativeSourceTooLargeError,
    MediaUploadContentTypeMismatchError,
    MediaUploadFormatUnavailableError,
    MediaUploadTooLargeError,
)
from app.domain.media_derivatives.processor import MediaDerivativeResult

_UPLOAD_MIME_BY_PILLOW_FORMAT = {
    "AVIF": "image/avif",
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


@dataclass(frozen=True, slots=True)
class ValidatedImageUpload:
    byte_size: int
    checksum: str
    content_type: str
    format: str
    width: int
    height: int


def validate_image_upload_stream(
    stream: BinaryIO,
    *,
    declared_content_type: str,
) -> ValidatedImageUpload:
    digest = hashlib.sha256()
    byte_size = 0
    try:
        try:
            stream.seek(0)
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                byte_size += len(chunk)
                if byte_size > MAX_UPLOAD_BYTES_IMAGE:
                    raise MediaUploadTooLargeError()
                digest.update(chunk)
        except OSError as error:
            raise ArtifactStoreError("upload spool read failed") from error
        if byte_size == 0:
            raise MediaDerivativeSourceDecodeFailedError()

        try:
            stream.seek(0)
        except OSError as error:
            raise ArtifactStoreError("upload spool seek failed") from error
        with Image.open(stream) as probe:
            pillow_format = str(probe.format or "").upper()
            width = int(probe.width)
            height = int(probe.height)
            if (
                width < 1
                or height < 1
                or width > MAX_IMAGE_DIMENSION
                or height > MAX_IMAGE_DIMENSION
                or width * height > MAX_PIXEL_COUNT
            ):
                raise MediaDerivativeSourceTooLargeError()
            if int(getattr(probe, "n_frames", 1)) > 1:
                raise MediaDerivativeAnimatedSourceUnavailableError()
            detected_content_type = _UPLOAD_MIME_BY_PILLOW_FORMAT.get(pillow_format, "")
            if not detected_content_type:
                raise MediaUploadFormatUnavailableError(pillow_format.lower() or "unknown")
            if declared_content_type.strip().lower() != detected_content_type:
                raise MediaUploadContentTypeMismatchError(
                    declared_content_type.strip().lower(),
                    detected_content_type,
                )
            probe.verify()

        try:
            stream.seek(0)
        except OSError as error:
            raise ArtifactStoreError("upload spool seek failed") from error
        with Image.open(stream) as decoded:
            if int(getattr(decoded, "n_frames", 1)) > 1:
                raise MediaDerivativeAnimatedSourceUnavailableError()
            decoded.load()
        try:
            stream.seek(0)
        except OSError as error:
            raise ArtifactStoreError("upload spool seek failed") from error
    except (
        MediaDerivativeAnimatedSourceUnavailableError,
        MediaDerivativeSourceDecodeFailedError,
        MediaDerivativeSourceTooLargeError,
        MediaUploadTooLargeError,
        MediaUploadContentTypeMismatchError,
        MediaUploadFormatUnavailableError,
        ArtifactStoreError,
    ):
        raise
    except Image.DecompressionBombError:
        raise MediaDerivativeSourceTooLargeError() from None
    except (OSError, SyntaxError, ValueError):
        raise MediaDerivativeSourceDecodeFailedError() from None
    finally:
        try:
            stream.seek(0)
        except OSError:
            pass

    return ValidatedImageUpload(
        byte_size=byte_size,
        checksum=f"sha256:{digest.hexdigest()}",
        content_type=detected_content_type,
        format=pillow_format.lower(),
        width=width,
        height=height,
    )


def create_uploaded_artifact(
    *,
    session: Session,
    run_id: str,
    site_id: str,
    stored: ArtifactStorageMetadata,
    upload: ValidatedImageUpload,
    ttl_minutes: int,
) -> MediaArtifact:
    now = datetime.now(UTC)
    artifact = MediaArtifact(
        artifact_id=f"art_{uuid4().hex}",
        run_id=run_id,
        site_id=site_id,
        storage_key=stored.storage_key,
        media_kind="image",
        operation="image.upload.v1",
        content_type=upload.content_type,
        byte_size=stored.byte_size,
        status="available",
        format=upload.format,
        width=upload.width,
        height=upload.height,
        checksum=stored.checksum,
        processing_warnings_json={"warnings": []},
        expires_at=now + timedelta(minutes=ttl_minutes),
    )
    session.add(artifact)
    session.flush()
    return artifact


def build_upload_artifact_result_json(artifact: MediaArtifact) -> dict[str, object]:
    return {
        "artifact_type": MEDIA_UPLOAD_ARTIFACT_TYPE,
        "contract_version": MEDIA_UPLOAD_RESULT_CONTRACT,
        "artifact": {
            "artifact_id": artifact.artifact_id,
            "media_kind": artifact.media_kind,
            "status": artifact.status,
            "content_type": artifact.content_type,
            "format": artifact.format,
            "width": artifact.width,
            "height": artifact.height,
            "filesize_bytes": artifact.byte_size,
            "checksum": artifact.checksum,
            "expires_at": artifact.expires_at.isoformat() if artifact.expires_at else None,
        }
    }


def create_artifact(
    *,
    session: Session,
    artifact_store: ArtifactStore,
    run_id: str,
    site_id: str,
    result: MediaDerivativeResult,
    source_media_type: str,
    ttl_minutes: int = ARTIFACT_DEFAULT_TTL_MINUTES,
    operation: str = "image.transform.v1",
) -> MediaArtifact:
    artifact_id = f"art_{uuid4().hex}"
    now = datetime.now(UTC)
    stored = publish_and_track_artifact(
        session,
        store=artifact_store,
        stream=BytesIO(result.output_bytes),
        max_bytes=max(1, result.filesize_bytes),
        metadata={"media_kind": source_media_type},
    )
    artifact = MediaArtifact(
        artifact_id=artifact_id,
        run_id=run_id,
        site_id=site_id,
        storage_key=stored.storage_key,
        media_kind=source_media_type,
        operation=operation,
        content_type=result.mime_type,
        byte_size=stored.byte_size,
        status="available",
        format=result.format,
        width=result.width,
        height=result.height,
        checksum=stored.checksum,
        processing_warnings_json={"warnings": result.processing_warnings},
        expires_at=now + timedelta(minutes=ttl_minutes),
    )
    session.add(artifact)
    session.flush()
    return artifact


def get_artifact(
    session: Session,
    artifact_id: str,
    *,
    site_id: str | None = None,
) -> MediaArtifact | None:
    statement = select(MediaArtifact).where(
        MediaArtifact.artifact_id == artifact_id,
    )
    if site_id:
        statement = statement.where(MediaArtifact.site_id == site_id)
    return session.scalar(statement)


def is_artifact_expired(artifact: MediaArtifact, *, now: datetime | None = None) -> bool:
    current_time = now or datetime.now(UTC)
    if artifact.status != "available" or artifact.purged_at is not None:
        return True
    expires_at = artifact.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= current_time


def build_artifact_result_json(artifact: MediaArtifact) -> dict[str, object]:
    warnings: list[str] = []
    if isinstance(artifact.processing_warnings_json, dict):
        warnings = artifact.processing_warnings_json.get("warnings", [])
    elif isinstance(artifact.processing_warnings_json, list):
        warnings = artifact.processing_warnings_json
    suggested_filename = _suggested_artifact_filename(artifact)
    return {
        "artifact_type": MEDIA_DERIVATIVE_ARTIFACT_TYPE,
        "contract_version": MEDIA_DERIVATIVE_RESULT_CONTRACT,
        "workflow_metadata": _media_derivative_workflow_metadata(),
        "artifact": {
            "artifact_id": artifact.artifact_id,
            "artifact_reference": {"artifact_id": artifact.artifact_id},
            "expires_at": artifact.expires_at.isoformat() if artifact.expires_at else None,
            "suggested_filename": suggested_filename,
            "filename_basis": {
                "owner": "wordpress_write_ability_final",
                "strategy": "format_checksum",
                "final_sanitize_unique_required": True,
            },
            "mime_type": artifact.content_type,
            "format": artifact.format,
            "width": artifact.width,
            "height": artifact.height,
            "filesize_bytes": artifact.byte_size,
            "checksum": artifact.checksum,
            "processing_warnings": warnings,
        },
    }


def _suggested_artifact_filename(artifact: MediaArtifact) -> str:
    extension = _extension_for_format(str(artifact.format or ""))
    checksum = str(artifact.checksum or "")
    if checksum.startswith("sha256:"):
        checksum = checksum[7:]
    checksum_part = "".join(ch for ch in checksum.lower() if ch in "0123456789abcdef")[:8]
    if not checksum_part:
        checksum_part = artifact.artifact_id.replace("art_", "")[:8]
    return f"media-derivative-{str(artifact.format or 'image').lower()}-{checksum_part}.{extension}"


def _media_derivative_workflow_metadata() -> dict[str, object]:
    metadata = dict(get_workflow_metadata(MEDIA_DERIVATIVE_WORKFLOW_ID))
    metadata.update(
        {
            "workflow_kind": "fixed_worker_workflow",
            "triggering_ability": "media_image_transform",
            "triggering_contract": "media_job_request.v1",
            "cloud_output": "temporary_derivative_artifact",
            "write_posture": "artifact_only",
            "steps": metadata_projection_tokens(metadata.get("steps")),
            "stop_conditions": metadata_projection_tokens(metadata.get("stop_conditions")),
        }
    )
    return metadata


def _extension_for_format(format_name: str) -> str:
    normalized = format_name.strip().lower()
    if normalized == "jpeg":
        return "jpg"
    if normalized in {"webp", "avif", "png"}:
        return normalized
    return "bin"
