from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.engine import CursorResult

from app.core.db import get_session
from app.core.models import MediaArtifact, MediaArtifactDelivery
from app.domain.media_artifacts.store import ArtifactStore, ArtifactStoreError

MEDIA_ARTIFACT_PURGE_LEASE_SECONDS = 5 * 60
MEDIA_ARTIFACT_PURGE_RETRY_BASE_SECONDS = 30
MEDIA_ARTIFACT_PURGE_RETRY_MAX_SECONDS = 60 * 60
MEDIA_ARTIFACT_PURGE_ERROR_CODE = "artifact_store.delete_failed"


@dataclass(frozen=True, slots=True)
class _PurgeClaim:
    artifact_id: str
    storage_key: str
    claim_id: str
    attempt_count: int


class MediaArtifactLifecycleError(RuntimeError):
    error_code = "media_artifact.lifecycle_cleanup_failed"

    def __init__(self) -> None:
        super().__init__("media artifact lifecycle cleanup failed")


class MediaArtifactLifecycleService:
    """Owns fenced TTL purge without holding a DB transaction during byte deletion."""

    def __init__(self, database_url: str, *, artifact_store: ArtifactStore) -> None:
        self._database_url = database_url
        self._artifact_store = artifact_store

    def cleanup_expired_artifacts(
        self,
        *,
        now: datetime | None = None,
        batch_size: int = 100,
    ) -> dict[str, int]:
        wall_clock_anchor = self._clock_now()
        current_time = _as_utc(now) if now is not None else wall_clock_anchor
        logical_clock_offset = current_time - wall_clock_anchor
        try:
            claims, stale_claims_reclaimed = self._claim_batch(
                now=current_time,
                batch_size=max(1, int(batch_size)),
                logical_clock_offset=logical_clock_offset,
            )
        except Exception:
            raise MediaArtifactLifecycleError() from None
        evidence = {
            "claimed": len(claims),
            "purged": 0,
            "retry_scheduled": 0,
            "stale_claims_reclaimed": stale_claims_reclaimed,
            "superseded_finalizations": 0,
        }

        for claim in claims:
            try:
                self._artifact_store.delete(claim.storage_key)
            except ArtifactStoreError:
                try:
                    finalized = self._finalize_failure(
                        claim=claim,
                        now=self._clock_now() + logical_clock_offset,
                    )
                except Exception:
                    raise MediaArtifactLifecycleError() from None
                evidence["retry_scheduled" if finalized else "superseded_finalizations"] += 1
            except Exception:
                try:
                    self._finalize_failure(
                        claim=claim,
                        now=self._clock_now() + logical_clock_offset,
                    )
                except Exception:
                    raise MediaArtifactLifecycleError() from None
                raise MediaArtifactLifecycleError() from None
            else:
                try:
                    finalized = self._finalize_success(
                        claim=claim,
                        now=self._clock_now() + logical_clock_offset,
                    )
                except Exception:
                    raise MediaArtifactLifecycleError() from None
                evidence["purged" if finalized else "superseded_finalizations"] += 1

        return evidence

    def _claim_batch(
        self,
        *,
        now: datetime,
        batch_size: int,
        logical_clock_offset: timedelta,
    ) -> tuple[list[_PurgeClaim], int]:
        claims: list[_PurgeClaim] = []
        stale_claims_reclaimed = 0
        with get_session(self._database_url) as session:
            artifacts = list(
                session.scalars(
                    select(MediaArtifact)
                    .where(
                        MediaArtifact.expires_at <= now,
                        MediaArtifact.purged_at.is_(None),
                        MediaArtifact.status != "purged",
                        or_(
                            MediaArtifact.purge_next_attempt_at.is_(None),
                            MediaArtifact.purge_next_attempt_at <= now,
                        ),
                        or_(
                            MediaArtifact.purge_claim_id.is_(None),
                            MediaArtifact.purge_claim_expires_at.is_(None),
                            MediaArtifact.purge_claim_expires_at <= now,
                        ),
                    )
                    .order_by(
                        func.coalesce(
                            MediaArtifact.purge_next_attempt_at,
                            MediaArtifact.expires_at,
                        ),
                        MediaArtifact.expires_at,
                        MediaArtifact.artifact_id,
                    )
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            )
            for artifact in artifacts:
                was_stale = (
                    artifact.purge_claim_id is not None
                    and artifact.purge_claim_expires_at is not None
                    and _as_utc(artifact.purge_claim_expires_at) <= now
                )

                claim_id = f"pcl_{uuid4().hex}"
                previous_attempt_count = int(artifact.purge_attempt_count or 0)
                attempt_count = previous_attempt_count + 1
                claim_result = cast(
                    CursorResult[Any],
                    session.execute(
                        update(MediaArtifact)
                        .where(
                            MediaArtifact.artifact_id == artifact.artifact_id,
                            MediaArtifact.storage_key == artifact.storage_key,
                            MediaArtifact.expires_at <= now,
                            MediaArtifact.purged_at.is_(None),
                            MediaArtifact.status != "purged",
                            func.coalesce(MediaArtifact.purge_attempt_count, 0)
                            == previous_attempt_count,
                            or_(
                                MediaArtifact.purge_next_attempt_at.is_(None),
                                MediaArtifact.purge_next_attempt_at <= now,
                            ),
                            or_(
                                MediaArtifact.purge_claim_id.is_(None),
                                MediaArtifact.purge_claim_expires_at.is_(None),
                                MediaArtifact.purge_claim_expires_at <= now,
                            ),
                        )
                        .values(
                            status="purge_pending",
                            purge_claim_id=claim_id,
                            purge_claim_expires_at=now
                            + timedelta(seconds=MEDIA_ARTIFACT_PURGE_LEASE_SECONDS),
                            purge_attempt_count=attempt_count,
                            purge_last_attempt_at=now,
                            purge_next_attempt_at=None,
                            purge_last_error_code=None,
                        )
                        .execution_options(synchronize_session=False)
                    ),
                )
                if claim_result.rowcount != 1:
                    continue
                if was_stale:
                    stale_claims_reclaimed += 1

                deliveries = list(
                    session.scalars(
                        select(MediaArtifactDelivery)
                        .where(
                            MediaArtifactDelivery.artifact_id == artifact.artifact_id,
                            MediaArtifactDelivery.acked_at.is_(None),
                            MediaArtifactDelivery.revoked_at.is_(None),
                        )
                        .order_by(MediaArtifactDelivery.delivery_id.asc())
                        .with_for_update()
                    )
                )
                for delivery in deliveries:
                    revoked_at = now
                    if (
                        delivery.completed_at is not None
                        and _as_utc(delivery.completed_at) > revoked_at
                    ):
                        revoked_at = _as_utc(delivery.completed_at)
                    delivery.revoked_at = revoked_at

                claims.append(
                    _PurgeClaim(
                        artifact_id=artifact.artifact_id,
                        storage_key=artifact.storage_key,
                        claim_id=claim_id,
                        attempt_count=attempt_count,
                    )
                )
            session.flush()
            if claims:
                refreshed_expiry = self._clock_now() + logical_clock_offset + timedelta(
                    seconds=MEDIA_ARTIFACT_PURGE_LEASE_SECONDS
                )
                for claim in claims:
                    refresh_result = cast(
                        CursorResult[Any],
                        session.execute(
                            update(MediaArtifact)
                            .where(
                                MediaArtifact.artifact_id == claim.artifact_id,
                                MediaArtifact.purge_claim_id == claim.claim_id,
                                MediaArtifact.purged_at.is_(None),
                                MediaArtifact.status == "purge_pending",
                            )
                            .values(purge_claim_expires_at=refreshed_expiry)
                            .execution_options(synchronize_session=False)
                        ),
                    )
                    if refresh_result.rowcount != 1:
                        raise MediaArtifactLifecycleError()
            session.commit()
        return claims, stale_claims_reclaimed

    def _finalize_success(self, *, claim: _PurgeClaim, now: datetime) -> bool:
        with get_session(self._database_url) as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(MediaArtifact)
                    .where(
                        MediaArtifact.artifact_id == claim.artifact_id,
                        MediaArtifact.purge_claim_id == claim.claim_id,
                        MediaArtifact.purged_at.is_(None),
                        MediaArtifact.status == "purge_pending",
                    )
                    .values(
                        status="purged",
                        purged_at=now,
                        purge_next_attempt_at=None,
                        purge_last_error_code=None,
                        purge_claim_id=None,
                        purge_claim_expires_at=None,
                    )
                ),
            )
            session.commit()
        return result.rowcount == 1

    def _finalize_failure(self, *, claim: _PurgeClaim, now: datetime) -> bool:
        with get_session(self._database_url) as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(MediaArtifact)
                    .where(
                        MediaArtifact.artifact_id == claim.artifact_id,
                        MediaArtifact.purge_claim_id == claim.claim_id,
                        MediaArtifact.purged_at.is_(None),
                        MediaArtifact.status == "purge_pending",
                    )
                    .values(
                        status="purge_pending",
                        purge_next_attempt_at=now
                        + timedelta(
                            seconds=_purge_retry_delay_seconds(claim.attempt_count)
                        ),
                        purge_last_error_code=MEDIA_ARTIFACT_PURGE_ERROR_CODE,
                        purge_claim_id=None,
                        purge_claim_expires_at=None,
                    )
                ),
            )
            session.commit()
        return result.rowcount == 1

    @staticmethod
    def _clock_now() -> datetime:
        return datetime.now(UTC)


def _purge_retry_delay_seconds(attempt_count: int) -> int:
    attempt = max(1, int(attempt_count or 0))
    if attempt >= 8:
        return MEDIA_ARTIFACT_PURGE_RETRY_MAX_SECONDS
    return min(
        MEDIA_ARTIFACT_PURGE_RETRY_MAX_SECONDS,
        MEDIA_ARTIFACT_PURGE_RETRY_BASE_SECONDS * (2 ** (attempt - 1)),
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
