from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import BinaryIO
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.models import MediaArtifact, MediaArtifactDelivery
from app.domain.media_artifacts.store import ArtifactStore, ArtifactStoreError

MEDIA_ARTIFACT_DELIVERY_ACK_CONTRACT = "media_artifact_delivery_ack.v1"
MEDIA_ARTIFACT_ACK_DEADLINE_SECONDS = 15 * 60
MEDIA_ARTIFACT_ACK_RETENTION_SECONDS = 5 * 60


class MediaArtifactDeliveryAckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    contract_version: str
    delivery_id: str = Field(min_length=1, max_length=191)
    received_byte_size: int = Field(ge=0)
    received_checksum: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class MediaArtifactDeliveryError(RuntimeError):
    status_code = 400
    error_code = "media_artifact.delivery_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class MediaArtifactNotFoundError(MediaArtifactDeliveryError):
    status_code = 404
    error_code = "media_artifact.not_found"


class MediaArtifactNotAvailableError(MediaArtifactDeliveryError):
    status_code = 409
    error_code = "media_artifact.not_available"


class MediaArtifactExpiredError(MediaArtifactDeliveryError):
    status_code = 410
    error_code = "media_artifact.expired"


class MediaArtifactBytesUnavailableError(MediaArtifactDeliveryError):
    status_code = 503
    error_code = "media_artifact.bytes_unavailable"


class MediaArtifactDeliveryNotFoundError(MediaArtifactDeliveryError):
    status_code = 404
    error_code = "media_artifact.delivery_not_found"


class MediaArtifactDeliveryNotCompletedError(MediaArtifactDeliveryError):
    status_code = 409
    error_code = "media_artifact.delivery_not_completed"


class MediaArtifactDeliveryExpiredError(MediaArtifactDeliveryError):
    status_code = 410
    error_code = "media_artifact.delivery_expired"


class MediaArtifactDeliveryAckConflictError(MediaArtifactDeliveryError):
    status_code = 409
    error_code = "media_artifact.delivery_ack_conflict"


class MediaArtifactDeliveryIntegrityError(MediaArtifactDeliveryError):
    status_code = 422
    error_code = "media_artifact.delivery_integrity_mismatch"


@dataclass(frozen=True, slots=True)
class PreparedMediaArtifactDelivery:
    artifact: MediaArtifact
    delivery: MediaArtifactDelivery
    stream: BinaryIO
    chunk_size: int


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def prepare_media_artifact_delivery(
    *,
    session: Session,
    artifact_store: ArtifactStore,
    artifact_id: str,
    site_id: str,
    trace_id: str,
    now: datetime | None = None,
) -> PreparedMediaArtifactDelivery:
    current_time = now or datetime.now(UTC)
    artifact = session.scalar(
        select(MediaArtifact).where(
            MediaArtifact.artifact_id == artifact_id,
            MediaArtifact.site_id == site_id,
        )
    )
    if artifact is None:
        raise MediaArtifactNotFoundError("media artifact was not found")
    if (
        artifact.status in {"purge_pending", "purged"}
        or artifact.purged_at is not None
        or _as_utc(artifact.expires_at) <= current_time
    ):
        raise MediaArtifactExpiredError("media artifact has expired")
    if artifact.status != "available":
        raise MediaArtifactNotAvailableError("media artifact is not available")

    try:
        metadata = artifact_store.metadata(artifact.storage_key)
    except ArtifactStoreError as error:
        raise MediaArtifactBytesUnavailableError("media artifact bytes are unavailable") from error
    if metadata.byte_size != artifact.byte_size or metadata.checksum != artifact.checksum:
        raise MediaArtifactBytesUnavailableError(
            "media artifact storage metadata does not match runtime evidence"
        )

    delivery = MediaArtifactDelivery(
        delivery_id=f"mdl_{uuid4().hex}",
        artifact_id=artifact.artifact_id,
        site_id=artifact.site_id,
        expected_byte_size=artifact.byte_size,
        expected_checksum=artifact.checksum,
        pull_trace_id=trace_id,
        started_at=current_time,
        ack_deadline_at=min(
            _as_utc(artifact.expires_at),
            current_time + timedelta(seconds=MEDIA_ARTIFACT_ACK_DEADLINE_SECONDS),
        ),
    )
    session.add(delivery)
    session.flush()
    try:
        stream = artifact_store.open(artifact.storage_key)
    except ArtifactStoreError as error:
        raise MediaArtifactBytesUnavailableError("media artifact bytes are unavailable") from error
    return PreparedMediaArtifactDelivery(
        artifact=artifact,
        delivery=delivery,
        stream=stream,
        chunk_size=artifact_store.chunk_size,
    )


def iter_verified_delivery_chunks(
    stream: BinaryIO,
    *,
    database_url: str,
    delivery_id: str,
    expected_byte_size: int,
    expected_checksum: str,
    chunk_size: int,
) -> Iterator[bytes]:
    digest = hashlib.sha256()
    byte_size = 0
    reached_eof = False
    try:
        with stream:
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    reached_eof = True
                    break
                if byte_size + len(chunk) > expected_byte_size:
                    break
                byte_size += len(chunk)
                digest.update(chunk)
                yield chunk
    finally:
        checksum = f"sha256:{digest.hexdigest()}"
        if (
            reached_eof
            and byte_size == expected_byte_size
            and checksum == expected_checksum
        ):
            with get_session(database_url) as session:
                delivery = session.get(MediaArtifactDelivery, delivery_id)
                if (
                    delivery is not None
                    and delivery.completed_at is None
                    and delivery.revoked_at is None
                ):
                    delivery.completed_at = datetime.now(UTC)
                    delivery.completed_byte_size = byte_size
                    delivery.completed_checksum = checksum
                    session.commit()


def acknowledge_media_artifact_delivery(
    *,
    session: Session,
    artifact_id: str,
    site_id: str,
    idempotency_key: str,
    trace_id: str,
    payload: MediaArtifactDeliveryAckRequest,
    now: datetime | None = None,
) -> dict[str, object]:
    if payload.contract_version != MEDIA_ARTIFACT_DELIVERY_ACK_CONTRACT:
        raise MediaArtifactDeliveryIntegrityError(
            "media artifact delivery acknowledgement contract is invalid"
        )
    fingerprint = hashlib.sha256(
        json.dumps(payload.model_dump(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    delivery = session.scalar(
        select(MediaArtifactDelivery)
        .where(
            MediaArtifactDelivery.delivery_id == payload.delivery_id,
            MediaArtifactDelivery.artifact_id == artifact_id,
            MediaArtifactDelivery.site_id == site_id,
        )
        .with_for_update()
    )
    if delivery is None:
        raise MediaArtifactDeliveryNotFoundError("media artifact delivery was not found")
    if delivery.acked_at is not None:
        if (
            delivery.ack_idempotency_key == idempotency_key
            and delivery.ack_request_fingerprint == fingerprint
        ):
            return _ack_projection(delivery, idempotent_replay=True)
        raise MediaArtifactDeliveryAckConflictError(
            "media artifact delivery acknowledgement conflicts with existing evidence"
        )
    existing_key_delivery = session.scalar(
        select(MediaArtifactDelivery).where(
            MediaArtifactDelivery.site_id == site_id,
            MediaArtifactDelivery.ack_idempotency_key == idempotency_key,
            MediaArtifactDelivery.delivery_id != delivery.delivery_id,
        )
    )
    if existing_key_delivery is not None:
        raise MediaArtifactDeliveryAckConflictError(
            "delivery acknowledgement idempotency key is already in use"
        )
    if delivery.completed_at is None:
        raise MediaArtifactDeliveryNotCompletedError("media artifact delivery is not completed")
    artifact = session.scalar(
        select(MediaArtifact)
        .where(
            MediaArtifact.artifact_id == artifact_id,
            MediaArtifact.site_id == site_id,
        )
        .with_for_update()
    )
    if artifact is None:
        raise MediaArtifactNotFoundError("media artifact was not found")
    current_time = now or datetime.now(UTC)
    if (
        delivery.revoked_at is not None
        or _as_utc(delivery.ack_deadline_at) <= current_time
        or artifact.status != "available"
        or artifact.purged_at is not None
        or _as_utc(artifact.expires_at) <= current_time
    ):
        raise MediaArtifactDeliveryExpiredError(
            "media artifact delivery acknowledgement deadline has expired"
        )
    if (
        payload.received_byte_size != delivery.expected_byte_size
        or payload.received_checksum != delivery.expected_checksum
        or delivery.completed_byte_size != delivery.expected_byte_size
        or delivery.completed_checksum != delivery.expected_checksum
    ):
        raise MediaArtifactDeliveryIntegrityError(
            "media artifact delivery acknowledgement does not match delivered bytes"
        )
    retention_before = _as_utc(artifact.expires_at)
    retention_after = min(
        retention_before,
        current_time + timedelta(seconds=MEDIA_ARTIFACT_ACK_RETENTION_SECONDS),
    )
    try:
        with session.begin_nested():
            artifact.expires_at = retention_after
            delivery.acked_at = current_time
            delivery.ack_idempotency_key = idempotency_key
            delivery.ack_request_fingerprint = fingerprint
            delivery.ack_trace_id = trace_id
            delivery.received_byte_size = payload.received_byte_size
            delivery.received_checksum = payload.received_checksum
            delivery.byte_size_verified = True
            delivery.checksum_verified = True
            delivery.retention_expires_at_before = retention_before
            delivery.retention_expires_at_after = retention_after
            session.flush()
    except IntegrityError as error:
        raise MediaArtifactDeliveryAckConflictError(
            "delivery acknowledgement idempotency key is already in use"
        ) from error
    return _ack_projection(delivery, idempotent_replay=False)


def _ack_projection(
    delivery: MediaArtifactDelivery,
    *,
    idempotent_replay: bool,
) -> dict[str, object]:
    return {
        "contract_version": MEDIA_ARTIFACT_DELIVERY_ACK_CONTRACT,
        "delivery_id": delivery.delivery_id,
        "artifact_id": delivery.artifact_id,
        "status": "acknowledged",
        "received_byte_size": int(delivery.received_byte_size or 0),
        "received_checksum": str(delivery.received_checksum or ""),
        "byte_size_verified": bool(delivery.byte_size_verified),
        "checksum_verified": bool(delivery.checksum_verified),
        "acknowledged_at": (
            _as_utc(delivery.acked_at).isoformat() if delivery.acked_at is not None else None
        ),
        "artifact_expires_at": (
            _as_utc(delivery.retention_expires_at_after).isoformat()
            if delivery.retention_expires_at_after is not None
            else None
        ),
        "idempotent_replay": idempotent_replay,
        "acknowledgement_scope": "verified_transfer_only",
    }
