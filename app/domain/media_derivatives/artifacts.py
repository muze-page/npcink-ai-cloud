from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import MediaDerivativeArtifact
from app.domain.agent_workflow_metadata import (
    MEDIA_DERIVATIVE_WORKFLOW_ID,
    get_workflow_metadata,
    metadata_projection_tokens,
)
from app.domain.media_derivatives.contracts import ARTIFACT_DEFAULT_TTL_MINUTES
from app.domain.media_derivatives.processor import MediaDerivativeResult


def create_artifact(
    *,
    session: Session,
    run_id: str,
    site_id: str,
    result: MediaDerivativeResult,
    source_media_type: str,
    ttl_minutes: int = ARTIFACT_DEFAULT_TTL_MINUTES,
) -> MediaDerivativeArtifact:
    artifact_id = f"art_{uuid4().hex}"
    now = datetime.now(UTC)
    artifact = MediaDerivativeArtifact(
        artifact_id=artifact_id,
        run_id=run_id,
        site_id=site_id,
        storage_ref=f"blob://media_derivative/{artifact_id}",
        blob_data=result.output_bytes,
        mime_type=result.mime_type,
        format=result.format,
        width=result.width,
        height=result.height,
        filesize_bytes=result.filesize_bytes,
        checksum=result.checksum,
        source_media_type=source_media_type,
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
) -> MediaDerivativeArtifact | None:
    statement = select(MediaDerivativeArtifact).where(
        MediaDerivativeArtifact.artifact_id == artifact_id,
    )
    if site_id:
        statement = statement.where(MediaDerivativeArtifact.site_id == site_id)
    return session.scalar(statement)


def is_artifact_expired(artifact: MediaDerivativeArtifact, *, now: datetime | None = None) -> bool:
    current_time = now or datetime.now(UTC)
    if artifact.purged_at is not None:
        return True
    expires_at = artifact.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= current_time


def cleanup_expired_artifacts(
    *,
    database_url: str,
    now: datetime | None = None,
    session: Session | None = None,
    batch_size: int = 100,
) -> int:
    from app.core.db import get_session as _get_session

    current_time = now or datetime.now(UTC)

    def _cleanup_with_session(s: Session) -> int:
        statement = (
            select(MediaDerivativeArtifact)
            .where(
                MediaDerivativeArtifact.expires_at <= current_time,
                MediaDerivativeArtifact.purged_at.is_(None),
            )
            .limit(batch_size)
        )
        artifacts = list(s.scalars(statement))
        for artifact in artifacts:
            artifact.purged_at = current_time
            artifact.blob_data = b""
        s.flush()
        return len(artifacts)

    if session is not None:
        return _cleanup_with_session(session)

    with _get_session(database_url) as s:
        count = _cleanup_with_session(s)
        s.commit()
        return count


def build_artifact_result_json(artifact: MediaDerivativeArtifact) -> dict[str, object]:
    warnings: list[str] = []
    if isinstance(artifact.processing_warnings_json, dict):
        warnings = artifact.processing_warnings_json.get("warnings", [])
    elif isinstance(artifact.processing_warnings_json, list):
        warnings = artifact.processing_warnings_json
    suggested_filename = _suggested_artifact_filename(artifact)
    return {
        "workflow_metadata": _media_derivative_workflow_metadata(),
        "artifact": {
            "artifact_id": artifact.artifact_id,
            "artifact_reference": {"artifact_id": artifact.artifact_id},
            "download_url": f"/v1/runtime/artifacts/{artifact.artifact_id}/download",
            "expires_at": artifact.expires_at.isoformat() if artifact.expires_at else None,
            "suggested_filename": suggested_filename,
            "filename_basis": {
                "owner": "wordpress_write_ability_final",
                "strategy": "format_checksum",
                "final_sanitize_unique_required": True,
            },
            "mime_type": artifact.mime_type,
            "format": artifact.format,
            "width": artifact.width,
            "height": artifact.height,
            "filesize_bytes": artifact.filesize_bytes,
            "checksum": artifact.checksum,
            "processing_warnings": warnings,
        },
    }


def _suggested_artifact_filename(artifact: MediaDerivativeArtifact) -> str:
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
            "triggering_ability": "generate_optimized_media_derivative",
            "triggering_contract": "media_derivative_cloud_request.v1",
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
