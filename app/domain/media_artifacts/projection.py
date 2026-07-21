from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import MediaArtifact
from app.domain.audio_generation.contracts import AUDIO_GENERATION_RESULT_CONTRACT
from app.domain.image_generation.contracts import IMAGE_GENERATION_RESULT_CONTRACT
from app.domain.media_derivatives.contracts import (
    MEDIA_DERIVATIVE_ARTIFACT_TYPE,
    MEDIA_DERIVATIVE_RESULT_CONTRACT,
    MEDIA_UPLOAD_ARTIFACT_TYPE,
    MEDIA_UPLOAD_RESULT_CONTRACT,
)

MEDIA_ARTIFACT_PROJECTION_MAX_IDS = 100
_AUDIO_GENERATION_ARTIFACT_TYPE = "audio_generation_candidates"
_IMAGE_GENERATION_ARTIFACT_TYPE = "image_generation_artifacts"

_MEDIA_DERIVATIVE_PUBLIC_ARTIFACT_FIELDS = frozenset(
    {
        "artifact_id",
        "artifact_reference",
        "expires_at",
        "suggested_filename",
        "filename_basis",
        "mime_type",
        "format",
        "width",
        "height",
        "filesize_bytes",
        "checksum",
        "processing_warnings",
    }
)

_PRIVATE_ARTIFACT_FIELDS = frozenset(
    {
        "storage_key",
        "purge_attempt_count",
        "purge_last_attempt_at",
        "purge_next_attempt_at",
        "purge_last_error_code",
        "purge_claim_id",
        "purge_claim_expires_at",
        "url",
        "audio_url",
        "download_url",
        "authenticated_download_url",
        "subtitle_url",
        "public_download_token",
        "token",
        "b64_json",
        "base64",
        "data_url",
    }
)


def project_media_artifact_lifecycle(
    result: dict[str, Any],
    *,
    session: Session,
    site_id: str,
    run_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Project safe current state for known media result envelopes.

    The durable run result remains a creation-time snapshot. This projection is
    deliberately limited to the platform-owned media envelopes below and never
    recursively scans arbitrary result JSON. Media derivative artifacts are the
    exception to lifecycle overlays: WordPress consumes their immutable exact12
    descriptor, while signed pull and ACK resources enforce live availability.
    """

    if not _is_known_artifact_envelope(result):
        return result

    projected = deepcopy(result)
    _strip_known_delivery_credentials(projected)

    # The derivative result artifact is an exact immutable descriptor consumed
    # by WordPress. Current availability is enforced by the signed pull and ACK
    # resources; adding lifecycle fields here would break the public Cloud12
    # contract and create a second, contradictory descriptor shape.
    if _is_media_derivative_envelope(projected):
        _freeze_media_derivative_artifact(projected)
        return projected

    references = _known_artifact_references(projected)

    artifact_ids = _bounded_unique_artifact_ids(references)
    artifacts_by_id: dict[str, MediaArtifact] = {}
    if artifact_ids:
        statement = select(MediaArtifact).where(
            MediaArtifact.site_id == site_id,
            MediaArtifact.run_id == run_id,
            MediaArtifact.artifact_id.in_(artifact_ids),
        )
        artifacts_by_id = {
            artifact.artifact_id: artifact for artifact in session.scalars(statement).all()
        }

    current_time = _as_utc(now or datetime.now(UTC))
    for reference in references:
        artifact_id = _artifact_id(reference)
        artifact = artifacts_by_id.get(artifact_id)
        if artifact is None:
            _project_unavailable(reference)
            continue
        _project_current_lifecycle(reference, artifact=artifact, now=current_time)

    return projected


def _is_media_derivative_envelope(result: dict[str, Any]) -> bool:
    return (
        str(result.get("artifact_type") or "") == MEDIA_DERIVATIVE_ARTIFACT_TYPE
        and str(result.get("contract_version") or "") == MEDIA_DERIVATIVE_RESULT_CONTRACT
    )


def _freeze_media_derivative_artifact(result: dict[str, Any]) -> None:
    artifact = result.get("artifact")
    if not isinstance(artifact, dict):
        return
    for field in tuple(artifact):
        if field not in _MEDIA_DERIVATIVE_PUBLIC_ARTIFACT_FIELDS:
            artifact.pop(field, None)


def _is_known_artifact_envelope(result: dict[str, Any]) -> bool:
    artifact_type = str(result.get("artifact_type") or "")
    contract_version = str(result.get("contract_version") or "")
    return (artifact_type, contract_version) in {
        (MEDIA_UPLOAD_ARTIFACT_TYPE, MEDIA_UPLOAD_RESULT_CONTRACT),
        (MEDIA_DERIVATIVE_ARTIFACT_TYPE, MEDIA_DERIVATIVE_RESULT_CONTRACT),
        (_IMAGE_GENERATION_ARTIFACT_TYPE, IMAGE_GENERATION_RESULT_CONTRACT),
        (_AUDIO_GENERATION_ARTIFACT_TYPE, AUDIO_GENERATION_RESULT_CONTRACT),
    }


def _strip_known_delivery_credentials(result: dict[str, Any]) -> None:
    artifact = result.get("artifact")
    if isinstance(artifact, dict):
        _strip_private_fields(artifact)
    artifacts = result.get("artifacts")
    if isinstance(artifacts, list):
        for item in artifacts:
            if isinstance(item, dict):
                _strip_private_fields(item)
    for collection_name in ("audios", "items"):
        items = result.get(collection_name)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            _strip_private_fields(item)
            nested_artifact = item.get("artifact")
            if isinstance(nested_artifact, dict):
                _strip_private_fields(nested_artifact)


def _known_artifact_references(result: dict[str, Any]) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    artifact_type = str(result.get("artifact_type") or "")
    contract_version = str(result.get("contract_version") or "")

    root_artifact = result.get("artifact")
    if (
        (artifact_type, contract_version)
        in {
            (MEDIA_UPLOAD_ARTIFACT_TYPE, MEDIA_UPLOAD_RESULT_CONTRACT),
            (MEDIA_DERIVATIVE_ARTIFACT_TYPE, MEDIA_DERIVATIVE_RESULT_CONTRACT),
        }
        and isinstance(root_artifact, dict)
    ):
        references.append(root_artifact)

    root_artifacts = result.get("artifacts")
    if (
        artifact_type == _IMAGE_GENERATION_ARTIFACT_TYPE
        and contract_version == IMAGE_GENERATION_RESULT_CONTRACT
        and isinstance(root_artifacts, list)
    ):
        references.extend(item for item in root_artifacts if isinstance(item, dict))

    if (
        artifact_type == _AUDIO_GENERATION_ARTIFACT_TYPE
        and contract_version == AUDIO_GENERATION_RESULT_CONTRACT
    ):
        audios = result.get("audios")
        if isinstance(audios, list):
            references.extend(_nested_artifact_references(audios))
        items = result.get("items")
        if isinstance(items, list):
            references.extend(_nested_artifact_references(items))

    return references


def _nested_artifact_references(items: list[Any]) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        artifact = item.get("artifact")
        if isinstance(artifact, dict):
            references.append(artifact)
    return references


def _bounded_unique_artifact_ids(references: list[dict[str, Any]]) -> list[str]:
    artifact_ids: list[str] = []
    seen: set[str] = set()
    for reference in references:
        artifact_id = _artifact_id(reference)
        if not artifact_id or artifact_id in seen:
            continue
        if len(artifact_ids) >= MEDIA_ARTIFACT_PROJECTION_MAX_IDS:
            break
        seen.add(artifact_id)
        artifact_ids.append(artifact_id)
    return artifact_ids


def _artifact_id(reference: dict[str, Any]) -> str:
    value = reference.get("artifact_id")
    return value.strip() if isinstance(value, str) else ""


def _project_current_lifecycle(
    reference: dict[str, Any],
    *,
    artifact: MediaArtifact,
    now: datetime,
) -> None:
    _strip_private_fields(reference)
    expires_at = _as_utc(artifact.expires_at)
    purged_at = _as_utc(artifact.purged_at) if artifact.purged_at is not None else None
    if purged_at is not None or artifact.status == "purged":
        status = "purged"
    elif expires_at <= now or artifact.status == "purge_pending":
        status = "expired"
    else:
        status = artifact.status

    reference["status"] = status
    reference["expires_at"] = expires_at.isoformat()
    reference["purged_at"] = purged_at.isoformat() if purged_at is not None else None


def _project_unavailable(reference: dict[str, Any]) -> None:
    _strip_private_fields(reference)
    reference["status"] = "unavailable"
    reference["expires_at"] = None
    reference["purged_at"] = None


def _strip_private_fields(reference: dict[str, Any]) -> None:
    for field in _PRIVATE_ARTIFACT_FIELDS:
        reference.pop(field, None)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
