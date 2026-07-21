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
MEDIA_ARTIFACT_MIN_PULL_WINDOW_SECONDS = 5 * 60


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


class MediaArtifactDeliveryWindowUnavailableError(MediaArtifactDeliveryError):
    status_code = 409
    error_code = "media_artifact.delivery_window_unavailable"


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


@dataclass(frozen=True, slots=True)
class _CommittedMediaArtifactDeliverySnapshot:
    artifact_found: bool
    artifact_status: str
    artifact_purged_at: datetime | None
    artifact_expires_at: datetime | None
    delivery_found: bool
    delivery_completed_at: datetime | None
    delivery_acked_at: datetime | None
    delivery_revoked_at: datetime | None
    delivery_ack_deadline_at: datetime | None


@dataclass(frozen=True, slots=True)
class _CommittedMediaArtifactDeliverySnapshotLoad:
    snapshot: _CommittedMediaArtifactDeliverySnapshot | None
    query_error: BaseException | None
    exit_error: BaseException | None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _delivery_clock_now() -> datetime:
    return datetime.now(UTC)


def _delivery_time(now: datetime | None) -> datetime:
    return _as_utc(now) if now is not None else _delivery_clock_now()


def _ensure_artifact_can_start_delivery(
    artifact: MediaArtifact,
    *,
    current_time: datetime,
) -> None:
    if (
        artifact.status in {"purge_pending", "purged"}
        or artifact.purged_at is not None
        or _as_utc(artifact.expires_at) <= current_time
    ):
        raise MediaArtifactExpiredError("media artifact has expired")
    if artifact.status != "available":
        raise MediaArtifactNotAvailableError("media artifact is not available")
    if _as_utc(artifact.expires_at) - current_time <= timedelta(
        seconds=MEDIA_ARTIFACT_MIN_PULL_WINDOW_SECONDS
    ):
        raise MediaArtifactDeliveryWindowUnavailableError(
            "media artifact delivery window is unavailable"
        )


def _close_stream_best_effort(stream: BinaryIO) -> None:
    try:
        stream.close()
    except BaseException:
        pass


def _rollback_session_best_effort(session: Session) -> None:
    try:
        session.rollback()
    except BaseException:
        pass


def _ensure_committed_delivery_can_be_exposed(
    snapshot: _CommittedMediaArtifactDeliverySnapshot,
    *,
    current_time: datetime,
) -> None:
    if not snapshot.artifact_found or snapshot.artifact_expires_at is None:
        raise MediaArtifactNotAvailableError("media artifact delivery is not available")
    if (
        snapshot.artifact_status in {"purge_pending", "purged"}
        or snapshot.artifact_purged_at is not None
        or _as_utc(snapshot.artifact_expires_at) <= current_time
    ):
        raise MediaArtifactExpiredError("media artifact has expired")
    if snapshot.artifact_status != "available":
        raise MediaArtifactNotAvailableError("media artifact is not available")
    if _as_utc(snapshot.artifact_expires_at) - current_time <= timedelta(
        seconds=MEDIA_ARTIFACT_MIN_PULL_WINDOW_SECONDS
    ):
        raise MediaArtifactDeliveryWindowUnavailableError(
            "media artifact delivery window is unavailable"
        )
    if not snapshot.delivery_found or snapshot.delivery_ack_deadline_at is None:
        raise MediaArtifactNotAvailableError("media artifact delivery is not available")
    if (
        snapshot.delivery_completed_at is not None
        or snapshot.delivery_acked_at is not None
        or snapshot.delivery_revoked_at is not None
    ):
        raise MediaArtifactNotAvailableError("media artifact delivery is not available")
    if _as_utc(snapshot.delivery_ack_deadline_at) <= current_time:
        raise MediaArtifactDeliveryExpiredError(
            "media artifact delivery acknowledgement deadline has expired"
        )
    if _as_utc(snapshot.delivery_ack_deadline_at) - current_time <= timedelta(
        seconds=MEDIA_ARTIFACT_MIN_PULL_WINDOW_SECONDS
    ):
        raise MediaArtifactDeliveryWindowUnavailableError(
            "media artifact delivery window is unavailable"
        )


def prepare_media_artifact_delivery(
    *,
    session: Session,
    artifact_store: ArtifactStore,
    artifact_id: str,
    site_id: str,
    trace_id: str,
    now: datetime | None = None,
) -> PreparedMediaArtifactDelivery:
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
    initial_time = _delivery_time(now)
    _ensure_artifact_can_start_delivery(artifact, current_time=initial_time)

    try:
        metadata = artifact_store.metadata(artifact.storage_key)
    except ArtifactStoreError as error:
        raise MediaArtifactBytesUnavailableError("media artifact bytes are unavailable") from error
    if metadata.byte_size != artifact.byte_size or metadata.checksum != artifact.checksum:
        raise MediaArtifactBytesUnavailableError(
            "media artifact storage metadata does not match runtime evidence"
        )
    try:
        stream = artifact_store.open(artifact.storage_key)
    except ArtifactStoreError as error:
        raise MediaArtifactBytesUnavailableError("media artifact bytes are unavailable") from error

    try:
        final_time = _delivery_time(now)
        _ensure_artifact_can_start_delivery(artifact, current_time=final_time)
    except BaseException:
        _close_stream_best_effort(stream)
        raise

    delivery = MediaArtifactDelivery(
        delivery_id=f"mdl_{uuid4().hex}",
        artifact_id=artifact.artifact_id,
        site_id=artifact.site_id,
        expected_byte_size=artifact.byte_size,
        expected_checksum=artifact.checksum,
        pull_trace_id=trace_id,
        started_at=final_time,
        ack_deadline_at=min(
            _as_utc(artifact.expires_at),
            final_time + timedelta(seconds=MEDIA_ARTIFACT_ACK_DEADLINE_SECONDS),
        ),
    )
    try:
        session.add(delivery)
        session.flush()
        precommit_time = _delivery_time(now)
        _ensure_artifact_can_start_delivery(artifact, current_time=precommit_time)
        delivery.started_at = precommit_time
        delivery.ack_deadline_at = min(
            _as_utc(artifact.expires_at),
            precommit_time + timedelta(seconds=MEDIA_ARTIFACT_ACK_DEADLINE_SECONDS),
        )
        session.flush()
    except BaseException:
        _close_stream_best_effort(stream)
        _rollback_session_best_effort(session)
        raise
    return PreparedMediaArtifactDelivery(
        artifact=artifact,
        delivery=delivery,
        stream=stream,
        chunk_size=artifact_store.chunk_size,
    )


def revalidate_committed_media_artifact_delivery(
    *,
    database_url: str,
    artifact_id: str,
    site_id: str,
    delivery_id: str,
    now: datetime | None = None,
) -> None:
    loaded = _load_committed_media_artifact_delivery_snapshot(
        database_url=database_url,
        artifact_id=artifact_id,
        site_id=site_id,
        delivery_id=delivery_id,
    )
    final_time = _delivery_time(now)
    if loaded.snapshot is not None and loaded.query_error is None:
        _ensure_committed_delivery_can_be_exposed(
            loaded.snapshot,
            current_time=final_time,
        )
        if loaded.exit_error is None:
            return
        if not isinstance(loaded.exit_error, Exception):
            raise loaded.exit_error
        raise MediaArtifactNotAvailableError(
            "media artifact delivery is not available"
        ) from None

    primary_error = loaded.query_error or loaded.exit_error
    if primary_error is not None and not isinstance(primary_error, Exception):
        raise primary_error
    raise MediaArtifactNotAvailableError(
        "media artifact delivery is not available"
    ) from None


def _load_committed_media_artifact_delivery_snapshot(
    *,
    database_url: str,
    artifact_id: str,
    site_id: str,
    delivery_id: str,
) -> _CommittedMediaArtifactDeliverySnapshotLoad:
    session_context = get_session(database_url)
    try:
        session = session_context.__enter__()
    except BaseException as error:
        return _CommittedMediaArtifactDeliverySnapshotLoad(
            snapshot=None,
            query_error=error,
            exit_error=None,
        )
    snapshot: _CommittedMediaArtifactDeliverySnapshot | None = None
    query_error: BaseException | None = None
    exit_error: BaseException | None = None
    try:
        artifact = session.scalar(
            select(MediaArtifact)
            .where(
                MediaArtifact.artifact_id == artifact_id,
                MediaArtifact.site_id == site_id,
            )
            .with_for_update()
        )
        if artifact is None:
            snapshot = _CommittedMediaArtifactDeliverySnapshot(
                artifact_found=False,
                artifact_status="",
                artifact_purged_at=None,
                artifact_expires_at=None,
                delivery_found=False,
                delivery_completed_at=None,
                delivery_acked_at=None,
                delivery_revoked_at=None,
                delivery_ack_deadline_at=None,
            )
        else:
            delivery = session.scalar(
                select(MediaArtifactDelivery)
                .where(
                    MediaArtifactDelivery.delivery_id == delivery_id,
                    MediaArtifactDelivery.artifact_id == artifact_id,
                    MediaArtifactDelivery.site_id == site_id,
                )
                .with_for_update()
            )
            snapshot = _CommittedMediaArtifactDeliverySnapshot(
                artifact_found=True,
                artifact_status=str(artifact.status),
                artifact_purged_at=artifact.purged_at,
                artifact_expires_at=artifact.expires_at,
                delivery_found=delivery is not None,
                delivery_completed_at=(delivery.completed_at if delivery is not None else None),
                delivery_acked_at=delivery.acked_at if delivery is not None else None,
                delivery_revoked_at=delivery.revoked_at if delivery is not None else None,
                delivery_ack_deadline_at=(
                    delivery.ack_deadline_at if delivery is not None else None
                ),
            )
    except BaseException as error:
        query_error = error
    try:
        session_context.__exit__(
            type(query_error) if query_error is not None else None,
            query_error,
            query_error.__traceback__ if query_error is not None else None,
        )
    except BaseException as error:
        exit_error = error
    return _CommittedMediaArtifactDeliverySnapshotLoad(
        snapshot=snapshot if query_error is None else None,
        query_error=query_error,
        exit_error=exit_error,
    )


def discard_pristine_media_artifact_delivery_best_effort(
    *,
    database_url: str,
    artifact_id: str,
    site_id: str,
    delivery_id: str,
) -> None:
    try:
        with get_session(database_url) as session:
            artifact = session.scalar(
                select(MediaArtifact)
                .where(
                    MediaArtifact.artifact_id == artifact_id,
                    MediaArtifact.site_id == site_id,
                )
                .with_for_update()
            )
            if artifact is None:
                return
            delivery = session.scalar(
                select(MediaArtifactDelivery)
                .where(
                    MediaArtifactDelivery.delivery_id == delivery_id,
                    MediaArtifactDelivery.artifact_id == artifact_id,
                    MediaArtifactDelivery.site_id == site_id,
                )
                .with_for_update()
            )
            if (
                delivery is None
                or delivery.completed_at is not None
                or delivery.acked_at is not None
                or delivery.revoked_at is not None
            ):
                return
            session.delete(delivery)
            session.commit()
    except BaseException:
        pass


def iter_verified_delivery_chunks(
    stream: BinaryIO,
    *,
    database_url: str,
    artifact_id: str,
    site_id: str,
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
        if reached_eof and byte_size == expected_byte_size and checksum == expected_checksum:
            _complete_media_artifact_delivery(
                database_url=database_url,
                artifact_id=artifact_id,
                site_id=site_id,
                delivery_id=delivery_id,
                byte_size=byte_size,
                checksum=checksum,
            )


def _complete_media_artifact_delivery(
    *,
    database_url: str,
    artifact_id: str,
    site_id: str,
    delivery_id: str,
    byte_size: int,
    checksum: str,
) -> None:
    with get_session(database_url) as session:
        artifact = session.scalar(
            select(MediaArtifact)
            .where(
                MediaArtifact.artifact_id == artifact_id,
                MediaArtifact.site_id == site_id,
            )
            .with_for_update()
        )
        if artifact is None:
            return
        delivery = session.scalar(
            select(MediaArtifactDelivery)
            .where(
                MediaArtifactDelivery.delivery_id == delivery_id,
                MediaArtifactDelivery.artifact_id == artifact_id,
                MediaArtifactDelivery.site_id == site_id,
            )
            .with_for_update()
        )
        if (
            delivery is None
            or delivery.completed_at is not None
            or delivery.revoked_at is not None
            or artifact.status != "available"
            or artifact.purged_at is not None
            or delivery.expected_byte_size != byte_size
            or delivery.expected_checksum != checksum
        ):
            return
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
    delivery_scope = session.execute(
        select(
            MediaArtifactDelivery.artifact_id,
            MediaArtifactDelivery.site_id,
        ).where(MediaArtifactDelivery.delivery_id == payload.delivery_id)
    ).one_or_none()
    if (
        delivery_scope is None
        or delivery_scope.artifact_id != artifact_id
        or delivery_scope.site_id != site_id
    ):
        raise MediaArtifactDeliveryNotFoundError("media artifact delivery was not found")
    artifact = session.scalar(
        select(MediaArtifact)
        .where(
            MediaArtifact.artifact_id == artifact_id,
            MediaArtifact.site_id == site_id,
        )
        .with_for_update()
    )
    if artifact is None:
        raise MediaArtifactDeliveryNotFoundError("media artifact delivery was not found")
    delivery = session.scalar(
        select(MediaArtifactDelivery)
        .where(
            MediaArtifactDelivery.delivery_id == payload.delivery_id,
            MediaArtifactDelivery.artifact_id == artifact_id,
            MediaArtifactDelivery.site_id == site_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
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
    current_time = _as_utc(now or datetime.now(UTC))
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
    # ACK proves one verified transfer; it does not make the immutable result
    # descriptor stale or prevent a later reviewed WordPress adoption. The
    # artifact remains available until its original bounded expiry.
    retention_after = retention_before
    try:
        with session.begin_nested():
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
