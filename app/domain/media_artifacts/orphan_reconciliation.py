from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import exists, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.core.db import get_session
from app.core.models import (
    MediaArtifact,
    MediaArtifactOrphanCandidate,
    MediaArtifactReconciliationPass,
)
from app.domain.media_artifacts.store import (
    ArtifactConditionalDeleteResult,
    ArtifactInventoryItem,
    ArtifactInventoryPage,
    ArtifactInventoryStore,
    ArtifactReconciliationSession,
    ArtifactSessionStore,
    ArtifactStore,
)

_PASS_ACTIVE_SLOT = "active"
_PASS_HEAD_SLOT = "head"
_STORE_ABSENT_GENERATION = "store_absent"
_DELETE_ERROR_CODE = "artifact_store.conditional_delete_failed"


class MediaArtifactOrphanReconciliationError(RuntimeError):
    error_code = "media_artifact.orphan_reconciliation_failed"

    def __init__(self) -> None:
        super().__init__("media artifact orphan reconciliation failed")


@dataclass(frozen=True, slots=True)
class MediaArtifactOrphanReconciliationEvidence:
    store_examined: int = 0
    referenced_present: int = 0
    orphan_observed: int = 0
    orphan_deferred: int = 0
    orphan_eligible: int = 0
    cleanup_candidates_eligible: int = 0
    db_available_examined: int = 0
    referenced_missing: int = 0
    pass_started: int = 0
    pass_busy: int = 0
    pass_completed: int = 0
    pass_abandoned: int = 0
    candidates_claimed: int = 0
    candidates_deleted: int = 0
    candidates_invalidated: int = 0
    retry_scheduled: int = 0
    stale_claims_reclaimed: int = 0
    superseded_finalizations: int = 0
    cleanup_fence_busy: int = 0
    deletion_enabled: bool = False
    fixed_root_sessions_supported: bool = False

    def as_dict(self) -> dict[str, int | bool]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        }


@dataclass(frozen=True, slots=True)
class _PassClaim:
    pass_id: str
    claim_id: str
    previous_completed_pass_id: str | None
    store_generation: str
    next_cursor: str | None
    last_storage_key: str | None
    started: bool
    abandoned_previous: bool


@dataclass(frozen=True, slots=True)
class _CleanupClaim:
    storage_key: str
    object_version: str
    claim_id: str
    attempt_count: int


class MediaArtifactOrphanReconciliationService:
    """Persists complete-pass orphan evidence and conditionally deletes candidates."""

    def __init__(self, database_url: str, *, artifact_store: ArtifactStore) -> None:
        self._database_url = database_url
        self._artifact_store = artifact_store

    def reconcile(
        self,
        *,
        now: datetime | None = None,
        safety_window_seconds: int = 24 * 60 * 60,
        page_size: int = 200,
        pass_lease_seconds: int = 5 * 60,
        cleanup_enabled: bool = False,
        cleanup_batch_size: int = 25,
        claim_lease_seconds: int = 5 * 60,
        retry_base_seconds: int = 30,
        retry_max_seconds: int = 60 * 60,
    ) -> MediaArtifactOrphanReconciliationEvidence:
        wall_clock_anchor = self._clock_now()
        current_time = _as_utc(now) if now is not None else wall_clock_anchor
        logical_clock_offset = current_time - wall_clock_anchor
        try:
            _validate_settings(
                safety_window_seconds=safety_window_seconds,
                page_size=page_size,
                pass_lease_seconds=pass_lease_seconds,
                cleanup_batch_size=cleanup_batch_size,
                claim_lease_seconds=claim_lease_seconds,
                retry_base_seconds=retry_base_seconds,
                retry_max_seconds=retry_max_seconds,
            )
            if not isinstance(self._artifact_store, ArtifactInventoryStore):
                raise MediaArtifactOrphanReconciliationError()
            fixed_sessions = isinstance(self._artifact_store, ArtifactSessionStore)
            evidence = MediaArtifactOrphanReconciliationEvidence(
                deletion_enabled=bool(cleanup_enabled),
                fixed_root_sessions_supported=fixed_sessions,
            )
            probe = self._artifact_store.list_objects(cursor=None, limit=page_size)
            generation = _page_generation(probe)
            claim = self._acquire_pass(
                now=current_time,
                cutoff=current_time - timedelta(seconds=safety_window_seconds),
                store_generation=generation,
                lease_seconds=pass_lease_seconds,
            )
            if claim is None:
                return replace(evidence, pass_busy=1)
            evidence = replace(
                evidence,
                pass_started=int(claim.started),
                pass_abandoned=int(claim.abandoned_previous),
            )
            try:
                self._scan_pass(
                    claim=claim,
                    probe=probe,
                    page_size=page_size,
                    lease_seconds=pass_lease_seconds,
                    now=current_time,
                )
                db_counts = self._inspect_available_database_inventory(page_size=page_size)
                verification = self._artifact_store.list_objects(cursor=None, limit=1)
                if _page_generation(verification) != claim.store_generation:
                    raise MediaArtifactOrphanReconciliationError()
                completed_at = self._clock_now() + logical_clock_offset
                completed = self._complete_pass(
                    claim=claim,
                    now=completed_at,
                    db_counts=db_counts,
                )
                if completed is None:
                    raise MediaArtifactOrphanReconciliationError()
                evidence = _replace_evidence(
                    evidence,
                    completed,
                    db_counts,
                    {"pass_completed": 1},
                )
            except Exception:
                self._abandon_pass(claim)
                raise

            if cleanup_enabled:
                cleanup = self._cleanup_candidates(
                    now=self._clock_now() + logical_clock_offset,
                    batch_size=cleanup_batch_size,
                    claim_lease_seconds=claim_lease_seconds,
                    retry_base_seconds=retry_base_seconds,
                    retry_max_seconds=retry_max_seconds,
                )
                evidence = _replace_evidence(evidence, cleanup)
            return evidence
        except MediaArtifactOrphanReconciliationError:
            raise
        except Exception:
            raise MediaArtifactOrphanReconciliationError() from None

    def _acquire_pass(
        self,
        *,
        now: datetime,
        cutoff: datetime,
        store_generation: str,
        lease_seconds: int,
    ) -> _PassClaim | None:
        claim_id = f"rcl_{uuid4().hex}"
        lease_now = self._clock_now()
        lease_expires_at = lease_now + timedelta(seconds=lease_seconds)
        abandoned_previous = False
        try:
            with get_session(self._database_url) as session:
                active = session.scalar(
                    select(MediaArtifactReconciliationPass)
                    .where(
                        MediaArtifactReconciliationPass.active_slot
                        == _PASS_ACTIVE_SLOT
                    )
                    .with_for_update()
                )
                head = session.scalar(
                    select(MediaArtifactReconciliationPass).where(
                        MediaArtifactReconciliationPass.head_slot == _PASS_HEAD_SLOT
                    )
                )
                if active is not None:
                    active_expiry = (
                        _as_utc(active.lease_expires_at)
                        if active.lease_expires_at is not None
                        else now
                    )
                    if active_expiry > lease_now:
                        return None
                    active.state = "abandoned"
                    active.active_slot = None
                    active.scan_claim_id = None
                    active.lease_expires_at = None
                    session.flush()
                    abandoned_previous = True

                pass_id = f"rcp_{uuid4().hex}"
                session.add(
                    MediaArtifactReconciliationPass(
                        pass_id=pass_id,
                        state="running",
                        active_slot=_PASS_ACTIVE_SLOT,
                        head_slot=None,
                        scan_claim_id=claim_id,
                        lease_expires_at=lease_expires_at,
                        previous_completed_pass_id=(head.pass_id if head is not None else None),
                        store_generation=store_generation,
                        next_cursor=None,
                        last_storage_key=None,
                        store_examined=0,
                        referenced_present=0,
                        orphan_observed=0,
                        orphan_deferred=0,
                        orphan_eligible=0,
                        db_available_examined=0,
                        referenced_missing=0,
                        started_at=now,
                        cutoff_at=cutoff,
                        completed_at=None,
                    )
                )
                session.commit()
                return _PassClaim(
                    pass_id=pass_id,
                    claim_id=claim_id,
                    previous_completed_pass_id=head.pass_id if head is not None else None,
                    store_generation=store_generation,
                    next_cursor=None,
                    last_storage_key=None,
                    started=True,
                    abandoned_previous=abandoned_previous,
                )
        except IntegrityError:
            return None

    def _scan_pass(
        self,
        *,
        claim: _PassClaim,
        probe: ArtifactInventoryPage,
        page_size: int,
        lease_seconds: int,
        now: datetime,
    ) -> None:
        cursor = claim.next_cursor
        last_storage_key = claim.last_storage_key
        seen_cursors: set[str] = set()
        first_page = probe if claim.started and cursor is None else None
        while True:
            page = (
                first_page
                if first_page is not None
                else cast(
                    ArtifactInventoryStore,
                    self._artifact_store,
                ).list_objects(cursor=cursor, limit=page_size)
            )
            first_page = None
            if _page_generation(page) != claim.store_generation:
                raise MediaArtifactOrphanReconciliationError()
            items = _validated_persistent_page(
                page,
                cursor=cursor,
                last_storage_key=last_storage_key,
                page_size=page_size,
            )
            self._persist_page(
                claim=claim,
                items=items,
                expected_cursor=cursor,
                expected_last_storage_key=last_storage_key,
                next_cursor=page.next_cursor,
                now=now,
                lease_seconds=lease_seconds,
            )
            if items:
                last_storage_key = items[-1].storage_key
            if page.next_cursor is None:
                return
            if page.next_cursor in seen_cursors:
                raise MediaArtifactOrphanReconciliationError()
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor

    def _persist_page(
        self,
        *,
        claim: _PassClaim,
        items: tuple[ArtifactInventoryItem, ...],
        expected_cursor: str | None,
        expected_last_storage_key: str | None,
        next_cursor: str | None,
        now: datetime,
        lease_seconds: int,
    ) -> None:
        storage_keys = tuple(item.storage_key for item in items)
        with get_session(self._database_url) as session:
            lease_now = self._clock_now()
            cursor_condition = (
                MediaArtifactReconciliationPass.next_cursor.is_(None)
                if expected_cursor is None
                else MediaArtifactReconciliationPass.next_cursor == expected_cursor
            )
            last_key_condition = (
                MediaArtifactReconciliationPass.last_storage_key.is_(None)
                if expected_last_storage_key is None
                else MediaArtifactReconciliationPass.last_storage_key
                == expected_last_storage_key
            )
            renewed = cast(
                CursorResult[Any],
                session.execute(
                    update(MediaArtifactReconciliationPass)
                    .where(
                        MediaArtifactReconciliationPass.pass_id == claim.pass_id,
                        MediaArtifactReconciliationPass.state == "running",
                        MediaArtifactReconciliationPass.active_slot == _PASS_ACTIVE_SLOT,
                        MediaArtifactReconciliationPass.scan_claim_id == claim.claim_id,
                        MediaArtifactReconciliationPass.lease_expires_at > lease_now,
                        cursor_condition,
                        last_key_condition,
                    )
                    .values(
                        lease_expires_at=lease_now + timedelta(seconds=lease_seconds)
                    )
                    .execution_options(synchronize_session=False)
                ),
            )
            if renewed.rowcount != 1:
                raise MediaArtifactOrphanReconciliationError()
            active = session.scalar(
                select(MediaArtifactReconciliationPass)
                .where(
                    MediaArtifactReconciliationPass.pass_id == claim.pass_id,
                    MediaArtifactReconciliationPass.state == "running",
                    MediaArtifactReconciliationPass.active_slot == _PASS_ACTIVE_SLOT,
                    MediaArtifactReconciliationPass.scan_claim_id == claim.claim_id,
                )
            )
            if active is None:
                raise MediaArtifactOrphanReconciliationError()
            referenced = (
                set(
                    session.scalars(
                        select(MediaArtifact.storage_key).where(
                            MediaArtifact.storage_key.in_(storage_keys)
                        )
                    )
                )
                if storage_keys
                else set()
            )
            candidates_by_key = {
                candidate.storage_key: candidate
                for candidate in session.scalars(
                    select(MediaArtifactOrphanCandidate)
                    .where(MediaArtifactOrphanCandidate.storage_key.in_(storage_keys))
                    .order_by(MediaArtifactOrphanCandidate.storage_key.asc())
                    .with_for_update()
                )
            }
            referenced_present = 0
            orphan_observed = 0
            orphan_deferred = 0
            orphan_age_eligible = 0
            for item in items:
                candidate = candidates_by_key.get(item.storage_key)
                active_candidate_claim = bool(
                    candidate is not None
                    and candidate.state == "claimed"
                    and candidate.claim_expires_at is not None
                    and _as_utc(candidate.claim_expires_at) > self._clock_now()
                )
                if item.storage_key in referenced:
                    referenced_present += 1
                    if candidate is not None and not active_candidate_claim:
                        self._compare_and_set_candidate(
                            session,
                            candidate=candidate,
                            values=_candidate_invalidation_values(now=now),
                        )
                    continue
                orphan_observed += 1
                if _as_utc(item.last_modified_at) > _as_utc(active.cutoff_at):
                    orphan_deferred += 1
                    if candidate is not None and not active_candidate_claim:
                        self._compare_and_set_candidate(
                            session,
                            candidate=candidate,
                            values=_candidate_invalidation_values(now=now),
                        )
                    continue
                orphan_age_eligible += 1
                continuity = bool(
                    candidate is not None
                    and candidate.state not in {"deleted", "invalidated"}
                    and candidate.last_pass_id == claim.previous_completed_pass_id
                    and candidate.store_generation == claim.store_generation
                    and candidate.object_version == item.object_version
                )
                if active_candidate_claim:
                    if candidate is not None and continuity:
                        self._compare_and_set_candidate(
                            session,
                            candidate=candidate,
                            values={
                                "last_pass_id": claim.pass_id,
                                "last_observed_at": now,
                            },
                        )
                    continue
                if (
                    candidate is not None
                    and candidate.state == "claimed"
                    and continuity
                ):
                    # Preserve the stale claim token so cleanup can reclaim it
                    # under the per-candidate EX fence. Only advance its
                    # observation link; never clear or replace the claim here.
                    self._compare_and_set_candidate(
                        session,
                        candidate=candidate,
                        values={
                            "last_pass_id": claim.pass_id,
                            "last_observed_at": now,
                        },
                    )
                    continue
                if (
                    candidate is not None
                    and continuity
                    and candidate.state in {"eligible", "retry_wait"}
                ):
                    # A complete scan advances current-head membership without
                    # erasing a still-active eligibility or retry decision.
                    self._compare_and_set_candidate(
                        session,
                        candidate=candidate,
                        values={
                            "last_pass_id": claim.pass_id,
                            "last_observed_at": now,
                        },
                    )
                    continue
                if candidate is None:
                    candidate = MediaArtifactOrphanCandidate(
                        storage_key=item.storage_key,
                        object_version=item.object_version,
                        store_generation=claim.store_generation,
                        first_pass_id=claim.pass_id,
                        last_pass_id=claim.pass_id,
                        state="observed",
                        claim_id=None,
                        claim_expires_at=None,
                        attempt_count=0,
                        retry_at=None,
                        last_error_code=None,
                        first_observed_at=now,
                        last_observed_at=now,
                        resolved_at=None,
                    )
                    session.add(candidate)
                else:
                    self._compare_and_set_candidate(
                        session,
                        candidate=candidate,
                        values={
                            "object_version": item.object_version,
                            "store_generation": claim.store_generation,
                            "first_pass_id": (
                                candidate.first_pass_id
                                if continuity
                                else claim.pass_id
                            ),
                            "last_pass_id": claim.pass_id,
                            "state": "observed",
                            "claim_id": None,
                            "claim_expires_at": None,
                            "attempt_count": (
                                candidate.attempt_count if continuity else 0
                            ),
                            "retry_at": None,
                            "last_error_code": None,
                            "first_observed_at": (
                                candidate.first_observed_at if continuity else now
                            ),
                            "last_observed_at": now,
                            "resolved_at": None,
                        },
                    )
            active.store_examined += len(items)
            active.referenced_present += referenced_present
            active.orphan_observed += orphan_observed
            active.orphan_deferred += orphan_deferred
            active.orphan_eligible += orphan_age_eligible
            active.next_cursor = next_cursor
            active.last_storage_key = items[-1].storage_key if items else active.last_storage_key
            session.commit()

    @staticmethod
    def _compare_and_set_candidate(
        session: Session,
        *,
        candidate: MediaArtifactOrphanCandidate,
        values: dict[str, object],
    ) -> bool:
        """Apply an observer transition only if the locked snapshot is unchanged."""

        conditions = [
            MediaArtifactOrphanCandidate.storage_key == candidate.storage_key,
            MediaArtifactOrphanCandidate.state == candidate.state,
            MediaArtifactOrphanCandidate.object_version == candidate.object_version,
            MediaArtifactOrphanCandidate.store_generation == candidate.store_generation,
            MediaArtifactOrphanCandidate.first_pass_id == candidate.first_pass_id,
            MediaArtifactOrphanCandidate.last_pass_id == candidate.last_pass_id,
            MediaArtifactOrphanCandidate.attempt_count == candidate.attempt_count,
            _nullable_match(
                MediaArtifactOrphanCandidate.claim_id,
                candidate.claim_id,
            ),
            _nullable_match(
                MediaArtifactOrphanCandidate.claim_expires_at,
                candidate.claim_expires_at,
            ),
            _nullable_match(
                MediaArtifactOrphanCandidate.retry_at,
                candidate.retry_at,
            ),
        ]
        result = cast(
            CursorResult[Any],
            session.execute(
                update(MediaArtifactOrphanCandidate)
                .where(*conditions)
                .values(**values)
                .execution_options(synchronize_session=False)
            ),
        )
        return result.rowcount == 1

    def _inspect_available_database_inventory(self, *, page_size: int) -> dict[str, int]:
        inventory_store = cast(ArtifactInventoryStore, self._artifact_store)
        examined = 0
        missing = 0
        cursor: str | None = None
        while True:
            with get_session(self._database_url) as session:
                statement = (
                    select(MediaArtifact.storage_key)
                    .where(MediaArtifact.status == "available")
                    .order_by(MediaArtifact.storage_key.asc())
                    .limit(page_size)
                )
                if cursor is not None:
                    statement = statement.where(MediaArtifact.storage_key > cursor)
                keys = tuple(session.scalars(statement))
            for storage_key in keys:
                examined += 1
                if not inventory_store.contains(storage_key):
                    missing += 1
            if len(keys) < page_size:
                break
            if keys[-1] == cursor:
                raise MediaArtifactOrphanReconciliationError()
            cursor = keys[-1]
        return {
            "db_available_examined": examined,
            "referenced_missing": missing,
        }

    def _complete_pass(
        self,
        *,
        claim: _PassClaim,
        now: datetime,
        db_counts: dict[str, int],
    ) -> dict[str, int] | None:
        with get_session(self._database_url) as session:
            lease_now = self._clock_now()
            claimed = cast(
                CursorResult[Any],
                session.execute(
                    update(MediaArtifactReconciliationPass)
                    .where(
                        MediaArtifactReconciliationPass.pass_id == claim.pass_id,
                        MediaArtifactReconciliationPass.state == "running",
                        MediaArtifactReconciliationPass.active_slot == _PASS_ACTIVE_SLOT,
                        MediaArtifactReconciliationPass.scan_claim_id == claim.claim_id,
                        MediaArtifactReconciliationPass.lease_expires_at > lease_now,
                        MediaArtifactReconciliationPass.next_cursor.is_(None),
                    )
                    .values(lease_expires_at=lease_now + timedelta(seconds=30))
                    .execution_options(synchronize_session=False)
                ),
            )
            if claimed.rowcount != 1:
                return None
            active = session.scalar(
                select(MediaArtifactReconciliationPass)
                .where(
                    MediaArtifactReconciliationPass.pass_id == claim.pass_id,
                    MediaArtifactReconciliationPass.state == "running",
                    MediaArtifactReconciliationPass.active_slot == _PASS_ACTIVE_SLOT,
                    MediaArtifactReconciliationPass.scan_claim_id == claim.claim_id,
                )
            )
            if active is None:
                return None
            previous_head = session.scalar(
                select(MediaArtifactReconciliationPass)
                .where(MediaArtifactReconciliationPass.head_slot == _PASS_HEAD_SLOT)
                .with_for_update()
            )
            first_pass = aliased(MediaArtifactReconciliationPass)
            eligible_result = cast(
                CursorResult[Any],
                session.execute(
                    update(MediaArtifactOrphanCandidate)
                    .where(
                        MediaArtifactOrphanCandidate.last_pass_id == active.pass_id,
                        MediaArtifactOrphanCandidate.state == "observed",
                        MediaArtifactOrphanCandidate.first_pass_id != active.pass_id,
                        exists(
                            select(first_pass.pass_id).where(
                                first_pass.pass_id
                                == MediaArtifactOrphanCandidate.first_pass_id,
                                first_pass.state == "completed",
                                first_pass.completed_at.is_not(None),
                                first_pass.completed_at <= active.cutoff_at,
                            )
                        ),
                    )
                    .values(state="eligible")
                    .execution_options(synchronize_session=False)
                ),
            )
            eligible = max(0, int(eligible_result.rowcount or 0))
            if previous_head is not None:
                previous_head.head_slot = None
                session.flush()
            active.state = "completed"
            active.active_slot = None
            active.head_slot = _PASS_HEAD_SLOT
            active.scan_claim_id = None
            active.lease_expires_at = None
            active.db_available_examined = int(
                db_counts.get("db_available_examined", 0)
            )
            active.referenced_missing = int(db_counts.get("referenced_missing", 0))
            active.completed_at = now
            session.commit()
            return {
                "store_examined": active.store_examined,
                "referenced_present": active.referenced_present,
                "orphan_observed": active.orphan_observed,
                "orphan_deferred": active.orphan_deferred,
                "orphan_eligible": active.orphan_eligible,
                "cleanup_candidates_eligible": eligible,
                "candidates_invalidated": 0,
            }

    @staticmethod
    def _clock_now() -> datetime:
        return datetime.now(UTC)

    def _abandon_pass(self, claim: _PassClaim) -> None:
        try:
            with get_session(self._database_url) as session:
                session.execute(
                    update(MediaArtifactReconciliationPass)
                    .where(
                        MediaArtifactReconciliationPass.pass_id == claim.pass_id,
                        MediaArtifactReconciliationPass.state == "running",
                        MediaArtifactReconciliationPass.active_slot == _PASS_ACTIVE_SLOT,
                        MediaArtifactReconciliationPass.scan_claim_id == claim.claim_id,
                    )
                    .values(
                        state="abandoned",
                        active_slot=None,
                        head_slot=None,
                        scan_claim_id=None,
                        lease_expires_at=None,
                    )
                )
                session.commit()
        except Exception:
            return

    def _cleanup_candidates(
        self,
        *,
        now: datetime,
        batch_size: int,
        claim_lease_seconds: int,
        retry_base_seconds: int,
        retry_max_seconds: int,
    ) -> dict[str, int]:
        wall_clock_anchor = self._clock_now()
        logical_clock_offset = _as_utc(now) - wall_clock_anchor

        def logical_now() -> datetime:
            return self._clock_now() + logical_clock_offset

        evidence = {
            "candidates_claimed": 0,
            "candidates_deleted": 0,
            "candidates_invalidated": 0,
            "retry_scheduled": 0,
            "stale_claims_reclaimed": 0,
            "superseded_finalizations": 0,
            "cleanup_fence_busy": 0,
        }
        if not isinstance(self._artifact_store, ArtifactSessionStore):
            evidence["cleanup_fence_busy"] = 1
            return evidence
        candidate_keys = self._select_cleanup_candidates(
            now=logical_now(),
            batch_size=batch_size,
        )
        for storage_key in candidate_keys:
            reconciliation = self._artifact_store.try_open_reconciliation_session()
            if reconciliation is None:
                evidence["cleanup_fence_busy"] += 1
                break
            try:
                reconciliation.validate()
                claim, reclaimed, invalidated = self._claim_one_candidate(
                    reconciliation=reconciliation,
                    storage_key=storage_key,
                    now=logical_now(),
                    claim_lease_seconds=claim_lease_seconds,
                )
                evidence["stale_claims_reclaimed"] += int(reclaimed)
                evidence["candidates_invalidated"] += int(invalidated)
                if claim is None:
                    continue
                evidence["candidates_claimed"] += 1
                try:
                    predelete = self._refresh_and_recheck_claim(
                        reconciliation=reconciliation,
                        claim=claim,
                        now=logical_now(),
                        claim_lease_seconds=claim_lease_seconds,
                    )
                except Exception:
                    finalized = self._finalize_cleanup_failure(
                        claim=claim,
                        now=logical_now(),
                        retry_base_seconds=retry_base_seconds,
                        retry_max_seconds=retry_max_seconds,
                    )
                    evidence[
                        "retry_scheduled"
                        if finalized
                        else "superseded_finalizations"
                    ] += 1
                    continue
                if predelete != "proceed":
                    evidence[
                        "candidates_invalidated"
                        if predelete == "invalidated"
                        else "superseded_finalizations"
                    ] += 1
                    continue
                try:
                    reconciliation.validate()
                    result = reconciliation.delete_if_unchanged(
                        claim.storage_key,
                        claim.object_version,
                    )
                except Exception:
                    finalized = self._finalize_cleanup_failure(
                        claim=claim,
                        now=logical_now(),
                        retry_base_seconds=retry_base_seconds,
                        retry_max_seconds=retry_max_seconds,
                    )
                    evidence[
                        "retry_scheduled" if finalized else "superseded_finalizations"
                    ] += 1
                    continue
                if result in {
                    ArtifactConditionalDeleteResult.DELETED_DURABLE,
                    ArtifactConditionalDeleteResult.ALREADY_ABSENT_DURABLE,
                }:
                    finalized = self._finalize_cleanup_success(
                        claim=claim,
                        now=logical_now(),
                    )
                    evidence[
                        "candidates_deleted" if finalized else "superseded_finalizations"
                    ] += 1
                elif result == ArtifactConditionalDeleteResult.OBJECT_CHANGED:
                    finalized = self._finalize_cleanup_invalidation(
                        claim=claim,
                        now=logical_now(),
                    )
                    evidence[
                        "candidates_invalidated"
                        if finalized
                        else "superseded_finalizations"
                    ] += 1
                else:
                    finalized = self._finalize_cleanup_failure(
                        claim=claim,
                        now=logical_now(),
                        retry_base_seconds=retry_base_seconds,
                        retry_max_seconds=retry_max_seconds,
                    )
                    evidence[
                        "retry_scheduled" if finalized else "superseded_finalizations"
                    ] += 1
            finally:
                reconciliation.release()
        return evidence

    def _select_cleanup_candidates(
        self,
        *,
        now: datetime,
        batch_size: int,
    ) -> tuple[str, ...]:
        lease_now = self._clock_now()
        with get_session(self._database_url) as session:
            head = session.scalar(
                select(MediaArtifactReconciliationPass).where(
                    MediaArtifactReconciliationPass.head_slot == _PASS_HEAD_SLOT,
                    MediaArtifactReconciliationPass.state == "completed",
                )
            )
            if head is None:
                return ()
            return tuple(
                session.scalars(
                    select(MediaArtifactOrphanCandidate.storage_key)
                    .where(
                        MediaArtifactOrphanCandidate.last_pass_id == head.pass_id,
                        MediaArtifactOrphanCandidate.store_generation
                        == head.store_generation,
                        or_(
                            MediaArtifactOrphanCandidate.state == "eligible",
                            (
                                (MediaArtifactOrphanCandidate.state == "retry_wait")
                                & (MediaArtifactOrphanCandidate.retry_at <= now)
                            ),
                            (
                                (MediaArtifactOrphanCandidate.state == "claimed")
                                & (
                                    MediaArtifactOrphanCandidate.claim_expires_at
                                    <= lease_now
                                )
                            ),
                        ),
                    )
                    .order_by(MediaArtifactOrphanCandidate.storage_key.asc())
                    .limit(batch_size)
                )
            )

    def _claim_one_candidate(
        self,
        *,
        reconciliation: ArtifactReconciliationSession,
        storage_key: str,
        now: datetime,
        claim_lease_seconds: int,
    ) -> tuple[_CleanupClaim | None, bool, bool]:
        lease_now = self._clock_now()
        with get_session(self._database_url) as session:
            head = session.scalar(
                select(MediaArtifactReconciliationPass).where(
                    MediaArtifactReconciliationPass.head_slot == _PASS_HEAD_SLOT,
                    MediaArtifactReconciliationPass.state == "completed",
                )
            )
            if head is None or head.store_generation != reconciliation.store_generation:
                return None, False, False
            candidate = session.get(MediaArtifactOrphanCandidate, storage_key)
            if (
                candidate is None
                or candidate.last_pass_id != head.pass_id
                or candidate.store_generation != reconciliation.store_generation
                or not _candidate_due(
                    candidate,
                    retry_now=now,
                    lease_now=lease_now,
                )
            ):
                return None, False, False
            referenced = session.scalar(
                select(MediaArtifact.artifact_id)
                .where(MediaArtifact.storage_key == storage_key)
                .limit(1)
            )
            if referenced is not None:
                _invalidate_candidate(candidate, now=now)
                session.commit()
                return None, False, True
            previous_state = candidate.state
            previous_claim_id = candidate.claim_id
            previous_attempt_count = int(candidate.attempt_count or 0)
            state_condition = _candidate_claim_condition(
                candidate,
                retry_now=now,
                lease_now=lease_now,
            )
            claim_id = f"ocl_{uuid4().hex}"
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(MediaArtifactOrphanCandidate)
                    .where(
                        MediaArtifactOrphanCandidate.storage_key == storage_key,
                        MediaArtifactOrphanCandidate.last_pass_id == head.pass_id,
                        MediaArtifactOrphanCandidate.store_generation
                        == reconciliation.store_generation,
                        MediaArtifactOrphanCandidate.object_version
                        == candidate.object_version,
                        MediaArtifactOrphanCandidate.attempt_count
                        == previous_attempt_count,
                        state_condition,
                    )
                    .values(
                        state="claimed",
                        claim_id=claim_id,
                        claim_expires_at=lease_now
                        + timedelta(seconds=claim_lease_seconds),
                        attempt_count=previous_attempt_count + 1,
                        retry_at=None,
                        last_error_code=None,
                    )
                    .execution_options(synchronize_session=False)
                ),
            )
            session.commit()
            if result.rowcount != 1:
                return None, False, False
            return (
                _CleanupClaim(
                    storage_key=storage_key,
                    object_version=candidate.object_version,
                    claim_id=claim_id,
                    attempt_count=previous_attempt_count + 1,
                ),
                previous_state == "claimed" and previous_claim_id is not None,
                False,
            )

    def _refresh_and_recheck_claim(
        self,
        *,
        reconciliation: ArtifactReconciliationSession,
        claim: _CleanupClaim,
        now: datetime,
        claim_lease_seconds: int,
    ) -> str:
        # Validate immediately before the final all-status DB reference check;
        # then the caller validates once more immediately before unlink.
        reconciliation.validate()
        with get_session(self._database_url) as session:
            candidate = session.scalar(
                select(MediaArtifactOrphanCandidate)
                .where(
                    MediaArtifactOrphanCandidate.storage_key == claim.storage_key,
                    MediaArtifactOrphanCandidate.state == "claimed",
                    MediaArtifactOrphanCandidate.claim_id == claim.claim_id,
                    MediaArtifactOrphanCandidate.object_version
                    == claim.object_version,
                )
                .with_for_update()
            )
            if candidate is None:
                return "superseded"
            referenced = session.scalar(
                select(MediaArtifact.artifact_id)
                .where(MediaArtifact.storage_key == claim.storage_key)
                .limit(1)
            )
            if referenced is not None:
                _invalidate_candidate(candidate, now=now)
                session.commit()
                return "invalidated"
            candidate.claim_expires_at = self._clock_now() + timedelta(
                seconds=claim_lease_seconds
            )
            session.commit()
            return "proceed"

    def _finalize_cleanup_success(self, *, claim: _CleanupClaim, now: datetime) -> bool:
        return self._finalize_claim(
            claim=claim,
            values={
                "state": "deleted",
                "claim_id": None,
                "claim_expires_at": None,
                "retry_at": None,
                "last_error_code": None,
                "resolved_at": now,
            },
        )

    def _finalize_cleanup_invalidation(
        self,
        *,
        claim: _CleanupClaim,
        now: datetime,
    ) -> bool:
        return self._finalize_claim(
            claim=claim,
            values={
                "state": "invalidated",
                "claim_id": None,
                "claim_expires_at": None,
                "retry_at": None,
                "last_error_code": None,
                "resolved_at": now,
            },
        )

    def _finalize_cleanup_failure(
        self,
        *,
        claim: _CleanupClaim,
        now: datetime,
        retry_base_seconds: int,
        retry_max_seconds: int,
    ) -> bool:
        return self._finalize_claim(
            claim=claim,
            values={
                "state": "retry_wait",
                "claim_id": None,
                "claim_expires_at": None,
                "retry_at": now
                + timedelta(
                    seconds=_retry_delay_seconds(
                        claim.attempt_count,
                        base=retry_base_seconds,
                        maximum=retry_max_seconds,
                    )
                ),
                "last_error_code": _DELETE_ERROR_CODE,
                "resolved_at": None,
            },
        )

    def _finalize_claim(
        self,
        *,
        claim: _CleanupClaim,
        values: dict[str, object],
    ) -> bool:
        with get_session(self._database_url) as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(MediaArtifactOrphanCandidate)
                    .where(
                        MediaArtifactOrphanCandidate.storage_key == claim.storage_key,
                        MediaArtifactOrphanCandidate.state == "claimed",
                        MediaArtifactOrphanCandidate.claim_id == claim.claim_id,
                        MediaArtifactOrphanCandidate.object_version
                        == claim.object_version,
                    )
                    .values(**values)
                    .execution_options(synchronize_session=False)
                ),
            )
            session.commit()
            return result.rowcount == 1


def _invalidate_candidate(
    candidate: MediaArtifactOrphanCandidate,
    *,
    now: datetime,
) -> None:
    candidate.state = "invalidated"
    candidate.claim_id = None
    candidate.claim_expires_at = None
    candidate.retry_at = None
    candidate.last_error_code = None
    candidate.resolved_at = now


def _candidate_invalidation_values(*, now: datetime) -> dict[str, object]:
    return {
        "state": "invalidated",
        "claim_id": None,
        "claim_expires_at": None,
        "retry_at": None,
        "last_error_code": None,
        "resolved_at": now,
    }


def _nullable_match(column: Any, value: object | None) -> Any:
    return column.is_(None) if value is None else column == value


def _candidate_due(
    candidate: MediaArtifactOrphanCandidate,
    *,
    retry_now: datetime,
    lease_now: datetime,
) -> bool:
    if candidate.state == "eligible":
        return True
    if candidate.state == "retry_wait":
        return bool(
            candidate.retry_at is not None
            and _as_utc(candidate.retry_at) <= retry_now
        )
    return bool(
        candidate.state == "claimed"
        and candidate.claim_expires_at is not None
        and _as_utc(candidate.claim_expires_at) <= lease_now
    )


def _candidate_claim_condition(
    candidate: MediaArtifactOrphanCandidate,
    *,
    retry_now: datetime,
    lease_now: datetime,
) -> Any:
    if candidate.state == "eligible":
        return MediaArtifactOrphanCandidate.state == "eligible"
    if candidate.state == "retry_wait":
        return (
            (MediaArtifactOrphanCandidate.state == "retry_wait")
            & (MediaArtifactOrphanCandidate.retry_at <= retry_now)
        )
    return (
        (MediaArtifactOrphanCandidate.state == "claimed")
        & (MediaArtifactOrphanCandidate.claim_id == candidate.claim_id)
        & (MediaArtifactOrphanCandidate.claim_expires_at <= lease_now)
    )


def _replace_evidence(
    evidence: MediaArtifactOrphanReconciliationEvidence,
    *updates: dict[str, int],
) -> MediaArtifactOrphanReconciliationEvidence:
    values = evidence.as_dict()
    for update_values in updates:
        values.update(update_values)
    return MediaArtifactOrphanReconciliationEvidence(**cast(Any, values))


def _page_generation(page: ArtifactInventoryPage) -> str:
    generation = str(page.store_generation or "").strip()
    if generation:
        return generation
    if page.items:
        raise MediaArtifactOrphanReconciliationError()
    return _STORE_ABSENT_GENERATION


def _validated_persistent_page(
    page: ArtifactInventoryPage,
    *,
    cursor: str | None,
    last_storage_key: str | None,
    page_size: int,
) -> tuple[ArtifactInventoryItem, ...]:
    items = tuple(page.items)
    if len(items) > page_size:
        raise MediaArtifactOrphanReconciliationError()
    keys = tuple(item.storage_key for item in items)
    if keys != tuple(sorted(set(keys))):
        raise MediaArtifactOrphanReconciliationError()
    if last_storage_key is not None and keys and keys[0] <= last_storage_key:
        raise MediaArtifactOrphanReconciliationError()
    if any(not item.object_version for item in items):
        raise MediaArtifactOrphanReconciliationError()
    if page.next_cursor is not None and (
        not items or page.next_cursor == cursor or page.next_cursor != keys[-1]
    ):
        raise MediaArtifactOrphanReconciliationError()
    return items


def _validate_settings(
    *,
    safety_window_seconds: int,
    page_size: int,
    pass_lease_seconds: int,
    cleanup_batch_size: int,
    claim_lease_seconds: int,
    retry_base_seconds: int,
    retry_max_seconds: int,
) -> None:
    values = (
        safety_window_seconds,
        page_size,
        pass_lease_seconds,
        cleanup_batch_size,
        claim_lease_seconds,
        retry_base_seconds,
        retry_max_seconds,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise MediaArtifactOrphanReconciliationError()
    if (
        safety_window_seconds < 3600
        or not 1 <= page_size <= 500
        or not 300 <= pass_lease_seconds <= 3600
        or not 1 <= cleanup_batch_size <= 100
        or not 30 <= claim_lease_seconds <= 3600
        or not 1 <= retry_base_seconds <= 3600
        or not retry_base_seconds <= retry_max_seconds <= 86400
    ):
        raise MediaArtifactOrphanReconciliationError()


def _retry_delay_seconds(attempt_count: int, *, base: int, maximum: int) -> int:
    attempt = max(1, int(attempt_count))
    if attempt >= 16:
        return maximum
    return min(maximum, base * (2 ** (attempt - 1)))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
