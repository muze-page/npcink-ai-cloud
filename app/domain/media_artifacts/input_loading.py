from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import MediaArtifact
from app.domain.media_artifacts.store import (
    ArtifactStore,
    ArtifactStoreError,
    read_artifact_bytes,
)

VISION_IMAGE_MAX_BYTES = 8 * 1024 * 1024
VISION_IMAGE_CONTENT_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)
VISION_IMAGE_FORMAT_BY_CONTENT_TYPE = {
    "image/jpeg": "jpeg",
    "image/png": "png",
    "image/webp": "webp",
}


class ArtifactInputError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass(frozen=True, slots=True)
class ArtifactInputReference:
    artifact_id: str
    content_type: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class LoadedArtifactInput:
    artifact_id: str
    content_type: str
    byte_size: int
    content_bytes: bytes = field(repr=False)


def admit_artifact_input(
    session: Session,
    *,
    site_id: str,
    artifact_id: str,
    now: datetime | None = None,
    max_bytes: int = VISION_IMAGE_MAX_BYTES,
) -> ArtifactInputReference:
    artifact = _find_artifact(
        session,
        site_id=site_id,
        artifact_id=artifact_id,
    )
    _validate_artifact_metadata(
        artifact,
        now=now or datetime.now(UTC),
        max_bytes=max_bytes,
    )
    return ArtifactInputReference(
        artifact_id=artifact.artifact_id,
        content_type=artifact.content_type,
        byte_size=artifact.byte_size,
    )


def load_artifact_input(
    session: Session,
    store: ArtifactStore,
    *,
    site_id: str,
    artifact_id: str,
    now: datetime | None = None,
    max_bytes: int = VISION_IMAGE_MAX_BYTES,
) -> LoadedArtifactInput:
    artifact = _find_artifact(
        session,
        site_id=site_id,
        artifact_id=artifact_id,
    )
    _validate_artifact_metadata(
        artifact,
        now=now or datetime.now(UTC),
        max_bytes=max_bytes,
    )
    try:
        content_bytes = read_artifact_bytes(
            store,
            artifact.storage_key,
            max_bytes=max_bytes,
            expected_bytes=artifact.byte_size,
            expected_checksum=artifact.checksum,
        )
    except ArtifactStoreError as error:
        raise ArtifactInputError(
            "wordpress_operation.alt_text_source_artifact_unavailable",
            "WordPress AI alt text source artifact bytes are unavailable",
        ) from error
    return LoadedArtifactInput(
        artifact_id=artifact.artifact_id,
        content_type=artifact.content_type,
        byte_size=artifact.byte_size,
        content_bytes=content_bytes,
    )


def _find_artifact(
    session: Session,
    *,
    site_id: str,
    artifact_id: str,
) -> MediaArtifact:
    artifact = session.scalar(
        select(MediaArtifact)
        .where(
            MediaArtifact.artifact_id == artifact_id,
            MediaArtifact.site_id == site_id,
        )
        .execution_options(populate_existing=True)
    )
    if artifact is None:
        raise ArtifactInputError(
            "wordpress_operation.alt_text_source_artifact_not_found",
            "WordPress AI alt text source artifact was not found",
        )
    return artifact


def _validate_artifact_metadata(
    artifact: MediaArtifact,
    *,
    now: datetime,
    max_bytes: int,
) -> None:
    expires_at = artifact.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    current_time = now if now.tzinfo is not None else now.replace(tzinfo=UTC)

    if artifact.purged_at is not None:
        raise ArtifactInputError(
            "wordpress_operation.alt_text_source_artifact_unavailable",
            "WordPress AI alt text source artifact is unavailable",
        )
    if expires_at <= current_time:
        raise ArtifactInputError(
            "wordpress_operation.alt_text_source_artifact_expired",
            "WordPress AI alt text source artifact has expired",
        )
    if artifact.status != "available":
        raise ArtifactInputError(
            "wordpress_operation.alt_text_source_artifact_unavailable",
            "WordPress AI alt text source artifact is unavailable",
        )
    expected_format = VISION_IMAGE_FORMAT_BY_CONTENT_TYPE.get(artifact.content_type)
    if (
        artifact.media_kind != "image"
        or artifact.content_type not in VISION_IMAGE_CONTENT_TYPES
        or str(artifact.format or "").strip().lower() != expected_format
    ):
        raise ArtifactInputError(
            "wordpress_operation.alt_text_artifact_type_not_allowed",
            "WordPress AI alt text source artifact must be a JPEG, PNG, or WebP image",
        )
    if artifact.byte_size > max_bytes:
        raise ArtifactInputError(
            "wordpress_operation.alt_text_source_artifact_too_large",
            "WordPress AI alt text source artifact exceeds the 8 MiB vision limit",
        )
    if (
        artifact.byte_size <= 0
        or not artifact.storage_key
        or not artifact.checksum
    ):
        raise ArtifactInputError(
            "wordpress_operation.alt_text_source_artifact_unavailable",
            "WordPress AI alt text source artifact metadata is unavailable",
        )
