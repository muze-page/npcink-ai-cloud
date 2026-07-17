from __future__ import annotations

import inspect
import io
import os
from dataclasses import replace as dataclass_replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    MediaArtifact,
    MediaArtifactOrphanCandidate,
    MediaArtifactReconciliationPass,
)
from app.domain.media_artifacts.orphan_reconciliation import (
    MediaArtifactOrphanReconciliationError,
    MediaArtifactOrphanReconciliationService,
    _CleanupClaim,
    _PassClaim,
)
from app.domain.media_artifacts.store import ArtifactStoreError, LocalVolumeArtifactStore


@pytest.fixture
def reconciliation_database(tmp_path: Path) -> str:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'orphan-reconciliation.sqlite3'}"
    init_schema(database_url)
    yield database_url
    dispose_engine(database_url)


def _age_object(root: Path, storage_key: str, *, modified_at: datetime) -> None:
    path = root / storage_key[4:6] / storage_key[6:8] / storage_key
    timestamp = modified_at.timestamp()
    os.utime(path, (timestamp, timestamp))


def _reference(storage_key: str, *, status: str, now: datetime) -> MediaArtifact:
    return MediaArtifact(
        artifact_id=f"art_{storage_key[4:]}",
        run_id="run_unknown_status",
        site_id="site_unknown_status",
        media_kind="image",
        operation="image.transform.v1",
        content_type="image/png",
        byte_size=1,
        storage_key=storage_key,
        status=status,
        format="png",
        width=1,
        height=1,
        checksum="sha256:" + ("a" * 64),
        expires_at=now + timedelta(days=1),
        created_at=now,
    )


def _prepare_eligible_candidate(
    database_url: str,
    root: Path,
) -> tuple[
    MediaArtifactOrphanReconciliationService,
    LocalVolumeArtifactStore,
    str,
    datetime,
]:
    store = LocalVolumeArtifactStore(root)
    stored = store.put(io.BytesIO(b"orphan"), max_bytes=6)
    started_at = datetime.now(UTC) + timedelta(days=2)
    _age_object(root, stored.storage_key, modified_at=started_at - timedelta(days=2))
    service = MediaArtifactOrphanReconciliationService(
        database_url,
        artifact_store=store,
    )
    service.reconcile(now=started_at, safety_window_seconds=3600)
    second = service.reconcile(
        now=started_at + timedelta(seconds=3601),
        safety_window_seconds=3600,
    )
    assert second.cleanup_candidates_eligible == 1
    return service, store, stored.storage_key, started_at + timedelta(seconds=3601)


def test_two_complete_generations_are_required_before_delete(
    reconciliation_database: str,
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    store = LocalVolumeArtifactStore(root)
    stored = store.put(io.BytesIO(b"orphan"), max_bytes=6)
    started_at = datetime.now(UTC) + timedelta(days=2)
    _age_object(root, stored.storage_key, modified_at=started_at - timedelta(days=2))
    service = MediaArtifactOrphanReconciliationService(
        reconciliation_database,
        artifact_store=store,
    )

    first = service.reconcile(
        now=started_at,
        safety_window_seconds=3600,
        cleanup_enabled=True,
    )
    assert first.orphan_eligible == 1
    assert first.cleanup_candidates_eligible == 0
    assert first.candidates_deleted == 0
    assert store.contains(stored.storage_key) is True

    second = service.reconcile(
        now=started_at + timedelta(seconds=3601),
        safety_window_seconds=3600,
        cleanup_enabled=True,
    )
    assert second.orphan_eligible == 1
    assert second.cleanup_candidates_eligible == 1
    assert second.candidates_claimed == 1
    assert second.candidates_deleted == 1
    assert store.contains(stored.storage_key) is False
    with get_session(reconciliation_database) as session:
        candidate = session.get(MediaArtifactOrphanCandidate, stored.storage_key)
        assert candidate is not None
        assert candidate.state == "deleted"
        assert candidate.claim_id is None


def test_future_mtime_is_deferred_and_never_forms_continuous_evidence(
    reconciliation_database: str,
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    store = LocalVolumeArtifactStore(root)
    stored = store.put(io.BytesIO(b"future"), max_bytes=6)
    started_at = datetime.now(UTC) + timedelta(days=1)
    _age_object(root, stored.storage_key, modified_at=started_at + timedelta(days=2))
    service = MediaArtifactOrphanReconciliationService(
        reconciliation_database,
        artifact_store=store,
    )

    first = service.reconcile(now=started_at, safety_window_seconds=3600)
    second = service.reconcile(
        now=started_at + timedelta(seconds=7200),
        safety_window_seconds=3600,
        cleanup_enabled=True,
    )

    assert first.orphan_deferred == 1
    assert second.orphan_deferred == 1
    assert second.orphan_eligible == 0
    assert second.cleanup_candidates_eligible == 0
    assert second.candidates_deleted == 0
    assert store.contains(stored.storage_key) is True
    with get_session(reconciliation_database) as session:
        assert session.get(MediaArtifactOrphanCandidate, stored.storage_key) is None


def test_expired_incomplete_pass_is_abandoned_and_old_worker_cannot_write(
    reconciliation_database: str,
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    old_pass_id = "rcp_old_incomplete"
    old_claim_id = "rcl_old_worker"
    with get_session(reconciliation_database) as session:
        session.add(
            MediaArtifactReconciliationPass(
                pass_id=old_pass_id,
                state="running",
                active_slot="active",
                head_slot=None,
                scan_claim_id=old_claim_id,
                lease_expires_at=now - timedelta(seconds=1),
                previous_completed_pass_id=None,
                store_generation="store_absent",
                next_cursor=None,
                last_storage_key=None,
                store_examined=0,
                referenced_present=0,
                orphan_observed=0,
                orphan_deferred=0,
                orphan_eligible=0,
                db_available_examined=0,
                referenced_missing=0,
                started_at=now - timedelta(hours=1),
                cutoff_at=now - timedelta(days=1),
                completed_at=None,
            )
        )
        session.commit()
    service = MediaArtifactOrphanReconciliationService(
        reconciliation_database,
        artifact_store=LocalVolumeArtifactStore(tmp_path / "missing-store"),
    )

    evidence = service.reconcile(now=now)
    assert evidence.pass_abandoned == 1
    with get_session(reconciliation_database) as session:
        old = session.get(MediaArtifactReconciliationPass, old_pass_id)
        head = session.scalar(
            session.query(MediaArtifactReconciliationPass)
            .filter(MediaArtifactReconciliationPass.head_slot == "head")
            .statement
        )
        assert old is not None and old.state == "abandoned"
        assert head is not None and head.pass_id != old_pass_id

    stale_claim = _PassClaim(
        pass_id=old_pass_id,
        claim_id=old_claim_id,
        previous_completed_pass_id=None,
        store_generation="store_absent",
        next_cursor=None,
        last_storage_key=None,
        started=True,
        abandoned_previous=False,
    )
    with pytest.raises(MediaArtifactOrphanReconciliationError):
        service._persist_page(
            claim=stale_claim,
            items=(),
            expected_cursor=None,
            expected_last_storage_key=None,
            next_cursor=None,
            now=now,
            lease_seconds=300,
        )


def test_long_first_scan_does_not_shorten_inter_pass_safety_window(
    reconciliation_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts"
    store = LocalVolumeArtifactStore(root)
    stored = store.put(io.BytesIO(b"slow"), max_bytes=4)
    started_at = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    _age_object(root, stored.storage_key, modified_at=started_at - timedelta(days=2))
    service = MediaArtifactOrphanReconciliationService(
        reconciliation_database,
        artifact_store=store,
    )
    clock = [started_at]
    monkeypatch.setattr(service, "_clock_now", lambda: clock[0])
    original_list = store.list_objects
    list_calls = 0

    def slow_first_list(**kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal list_calls
        page = original_list(**kwargs)  # type: ignore[arg-type]
        list_calls += 1
        if list_calls == 1:
            clock[0] += timedelta(minutes=10)
        return page

    monkeypatch.setattr(store, "list_objects", slow_first_list)
    service.reconcile(now=started_at, safety_window_seconds=3600)
    clock[0] = started_at + timedelta(seconds=3600)

    second = service.reconcile(
        now=started_at + timedelta(seconds=3600),
        safety_window_seconds=3600,
        cleanup_enabled=True,
    )

    assert second.orphan_eligible == 1
    assert second.cleanup_candidates_eligible == 0
    assert second.candidates_deleted == 0
    assert store.contains(stored.storage_key) is True


def test_completion_persists_database_inventory_aggregates(
    reconciliation_database: str,
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    missing_key = f"obj_{'a' * 32}"
    with get_session(reconciliation_database) as session:
        session.add(_reference(missing_key, status="available", now=now))
        session.commit()
    service = MediaArtifactOrphanReconciliationService(
        reconciliation_database,
        artifact_store=LocalVolumeArtifactStore(tmp_path / "missing-inventory"),
    )

    evidence = service.reconcile(now=now)

    assert evidence.db_available_examined == 1
    assert evidence.referenced_missing == 1
    with get_session(reconciliation_database) as session:
        head = session.scalar(
            session.query(MediaArtifactReconciliationPass)
            .filter(MediaArtifactReconciliationPass.head_slot == "head")
            .statement
        )
        assert head is not None
        assert head.db_available_examined == 1
        assert head.referenced_missing == 1


def test_completion_eligibility_sql_requires_completed_first_pass() -> None:
    source = inspect.getsource(
        MediaArtifactOrphanReconciliationService._complete_pass
    )

    assert 'first_pass.state == "completed"' in source
    assert "first_pass.completed_at <= active.cutoff_at" in source
    assert "update(MediaArtifactOrphanCandidate)" in source
    assert "session.get(" not in source
    assert "list(" not in source


def test_cleanup_uses_one_nonblocking_exclusive_session_per_candidate(
    reconciliation_database: str,
    tmp_path: Path,
) -> None:
    class CountingSession:
        def __init__(self, inner: object, store: CountingStore) -> None:
            self._inner = inner
            self._store = store

        @property
        def store_generation(self) -> str:
            return self._inner.store_generation  # type: ignore[attr-defined,no-any-return]

        def validate(self) -> None:
            self._inner.validate()  # type: ignore[attr-defined]

        def delete_if_unchanged(self, storage_key: str, object_version: str):  # type: ignore[no-untyped-def]
            return self._inner.delete_if_unchanged(  # type: ignore[attr-defined,no-any-return]
                storage_key,
                object_version,
            )

        def release(self) -> None:
            self._store.release_count += 1
            self._inner.release()  # type: ignore[attr-defined]

    class CountingStore(LocalVolumeArtifactStore):
        acquire_count = 0
        release_count = 0

        def try_open_reconciliation_session(self):  # type: ignore[no-untyped-def]
            self.acquire_count += 1
            inner = super().try_open_reconciliation_session()
            return None if inner is None else CountingSession(inner, self)

    root = tmp_path / "artifacts"
    store = CountingStore(root)
    stored = (
        store.put(io.BytesIO(b"first"), max_bytes=5),
        store.put(io.BytesIO(b"second"), max_bytes=6),
    )
    started_at = datetime.now(UTC) + timedelta(days=2)
    for item in stored:
        _age_object(root, item.storage_key, modified_at=started_at - timedelta(days=2))
    service = MediaArtifactOrphanReconciliationService(
        reconciliation_database,
        artifact_store=store,
    )
    service.reconcile(now=started_at, safety_window_seconds=3600)

    result = service.reconcile(
        now=started_at + timedelta(seconds=3601),
        safety_window_seconds=3600,
        cleanup_enabled=True,
    )

    assert result.candidates_deleted == 2
    assert store.acquire_count == 2
    assert store.release_count == 2


def test_candidate_missing_one_complete_pass_must_restart_continuity(
    reconciliation_database: str,
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    store = LocalVolumeArtifactStore(root)
    stored = store.put(io.BytesIO(b"orphan"), max_bytes=6)
    started_at = datetime.now(UTC) + timedelta(days=2)
    _age_object(root, stored.storage_key, modified_at=started_at - timedelta(days=2))
    service = MediaArtifactOrphanReconciliationService(
        reconciliation_database,
        artifact_store=store,
    )
    service.reconcile(now=started_at, safety_window_seconds=3600)
    store.delete(stored.storage_key)
    service.reconcile(
        now=started_at + timedelta(seconds=3601),
        safety_window_seconds=3600,
    )

    path = root / stored.storage_key[4:6] / stored.storage_key[6:8] / stored.storage_key
    path.write_bytes(b"orphan")
    os.chmod(path, 0o600)
    _age_object(
        root,
        stored.storage_key,
        modified_at=started_at - timedelta(days=2),
    )
    third = service.reconcile(
        now=started_at + timedelta(seconds=7202),
        safety_window_seconds=3600,
        cleanup_enabled=True,
    )

    assert third.orphan_eligible == 1
    assert third.cleanup_candidates_eligible == 0
    assert third.candidates_deleted == 0
    assert store.contains(stored.storage_key) is True


@pytest.mark.parametrize("change", ["generation", "object_token"])
def test_generation_or_object_token_change_restarts_continuity(
    reconciliation_database: str,
    tmp_path: Path,
    change: str,
) -> None:
    root = tmp_path / "artifacts"
    store = LocalVolumeArtifactStore(root)
    stored = store.put(io.BytesIO(b"orphan"), max_bytes=6)
    started_at = datetime.now(UTC) + timedelta(days=2)
    old_mtime = started_at - timedelta(days=2)
    _age_object(root, stored.storage_key, modified_at=old_mtime)
    service = MediaArtifactOrphanReconciliationService(
        reconciliation_database,
        artifact_store=store,
    )
    service.reconcile(now=started_at, safety_window_seconds=3600)
    path = root / stored.storage_key[4:6] / stored.storage_key[6:8] / stored.storage_key
    if change == "generation":
        root.rename(tmp_path / "old-artifacts")
        replacement = LocalVolumeArtifactStore(root)
        publication = replacement.open_publication_session()
        publication.release()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"orphan")
        os.chmod(path, 0o600)
    else:
        replacement = path.with_name("replacement.tmp")
        replacement.write_bytes(b"orphan")
        os.chmod(replacement, 0o600)
        os.replace(replacement, path)
    _age_object(root, stored.storage_key, modified_at=old_mtime)

    second = service.reconcile(
        now=started_at + timedelta(seconds=3601),
        safety_window_seconds=3600,
        cleanup_enabled=True,
    )

    assert second.orphan_eligible == 1
    assert second.cleanup_candidates_eligible == 0
    assert second.candidates_deleted == 0
    assert path.is_file()


@pytest.mark.parametrize("status", ["purged", "future_unknown_status"])
def test_any_reference_status_blocks_claim_before_delete(
    reconciliation_database: str,
    tmp_path: Path,
    status: str,
) -> None:
    service, store, storage_key, now = _prepare_eligible_candidate(
        reconciliation_database,
        tmp_path / status,
    )
    with get_session(reconciliation_database) as session:
        session.add(_reference(storage_key, status=status, now=now))
        session.commit()

    evidence = service._cleanup_candidates(
        now=now,
        batch_size=25,
        claim_lease_seconds=300,
        retry_base_seconds=30,
        retry_max_seconds=3600,
    )

    assert evidence["candidates_claimed"] == 0
    assert evidence["candidates_invalidated"] == 1
    assert store.contains(storage_key) is True


def test_reference_inserted_after_claim_is_caught_by_final_recheck(
    reconciliation_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, store, storage_key, now = _prepare_eligible_candidate(
        reconciliation_database,
        tmp_path / "final-recheck",
    )
    original = service._claim_one_candidate

    def claim_then_reference(**kwargs: object):  # type: ignore[no-untyped-def]
        result = original(**kwargs)  # type: ignore[arg-type]
        if result[0] is not None:
            with get_session(reconciliation_database) as session:
                session.add(
                    _reference(
                        storage_key,
                        status="unknown_after_claim",
                        now=now,
                    )
                )
                session.commit()
        return result

    monkeypatch.setattr(service, "_claim_one_candidate", claim_then_reference)
    evidence = service._cleanup_candidates(
        now=now,
        batch_size=25,
        claim_lease_seconds=300,
        retry_base_seconds=30,
        retry_max_seconds=3600,
    )

    assert evidence["candidates_claimed"] == 1
    assert evidence["candidates_invalidated"] == 1
    assert evidence["candidates_deleted"] == 0
    assert store.contains(storage_key) is True


def test_observer_preserves_unexpired_claim_and_ex_busy_claims_nothing(
    reconciliation_database: str,
    tmp_path: Path,
) -> None:
    root = tmp_path / "active-claim"
    store = LocalVolumeArtifactStore(root)
    stored = store.put(io.BytesIO(b"orphan"), max_bytes=6)
    started_at = datetime.now(UTC) + timedelta(days=2)
    _age_object(root, stored.storage_key, modified_at=started_at - timedelta(days=2))
    service = MediaArtifactOrphanReconciliationService(
        reconciliation_database,
        artifact_store=store,
    )
    service.reconcile(now=started_at, safety_window_seconds=3600)
    with get_session(reconciliation_database) as session:
        candidate = session.get(MediaArtifactOrphanCandidate, stored.storage_key)
        assert candidate is not None
        candidate.state = "claimed"
        candidate.claim_id = "ocl_active"
        candidate.claim_expires_at = datetime.now(UTC) + timedelta(hours=1)
        candidate.attempt_count = 1
        session.commit()

    service.reconcile(
        now=started_at + timedelta(seconds=3601),
        safety_window_seconds=3600,
    )
    with get_session(reconciliation_database) as session:
        candidate = session.get(MediaArtifactOrphanCandidate, stored.storage_key)
        assert candidate is not None
        assert candidate.state == "claimed"
        assert candidate.claim_id == "ocl_active"

    # Make a fresh eligible candidate and hold SH so EX|NB cannot be acquired.
    busy_service, busy_store, busy_key, busy_now = _prepare_eligible_candidate(
        reconciliation_database,
        tmp_path / "busy-fence",
    )
    publication = busy_store.open_publication_session()
    try:
        evidence = busy_service._cleanup_candidates(
            now=busy_now,
            batch_size=25,
            claim_lease_seconds=300,
            retry_base_seconds=30,
            retry_max_seconds=3600,
        )
    finally:
        publication.release()
    assert evidence["cleanup_fence_busy"] == 1
    assert evidence["candidates_claimed"] == 0
    assert busy_store.contains(busy_key) is True


def test_stale_observer_compare_and_set_cannot_clear_new_cleanup_claim(
    reconciliation_database: str,
    tmp_path: Path,
) -> None:
    service, store, storage_key, now = _prepare_eligible_candidate(
        reconciliation_database,
        tmp_path / "observer-claim-race",
    )
    with get_session(reconciliation_database) as observer_reader:
        stale_snapshot = observer_reader.get(
            MediaArtifactOrphanCandidate,
            storage_key,
        )
        assert stale_snapshot is not None and stale_snapshot.state == "eligible"
        observer_reader.expunge(stale_snapshot)
        observer_reader.rollback()

    reconciliation = store.try_open_reconciliation_session()
    assert reconciliation is not None
    try:
        claim, _, _ = service._claim_one_candidate(
            reconciliation=reconciliation,
            storage_key=storage_key,
            now=now,
            claim_lease_seconds=300,
        )
    finally:
        reconciliation.release()
    assert claim is not None

    with get_session(reconciliation_database) as stale_observer_writer:
        applied = service._compare_and_set_candidate(
            stale_observer_writer,
            candidate=stale_snapshot,
            values={
                "state": "observed",
                "claim_id": None,
                "claim_expires_at": None,
                "retry_at": None,
                "last_error_code": None,
                "resolved_at": None,
            },
        )
        stale_observer_writer.commit()
    assert applied is False
    with get_session(reconciliation_database) as verification:
        candidate = verification.get(MediaArtifactOrphanCandidate, storage_key)
        assert candidate is not None
        assert candidate.state == "claimed"
        assert candidate.claim_id == claim.claim_id


def test_continuous_retry_wait_survives_scan_and_future_backoff(
    reconciliation_database: str,
    tmp_path: Path,
) -> None:
    service, store, storage_key, second_started_at = _prepare_eligible_candidate(
        reconciliation_database,
        tmp_path / "retry-continuity",
    )
    third_started_at = second_started_at + timedelta(seconds=3601)
    retry_at = third_started_at + timedelta(hours=1)
    with get_session(reconciliation_database) as session:
        candidate = session.get(MediaArtifactOrphanCandidate, storage_key)
        assert candidate is not None
        candidate.state = "retry_wait"
        candidate.attempt_count = 4
        candidate.retry_at = retry_at
        candidate.last_error_code = "artifact_store.conditional_delete_failed"
        session.commit()

    evidence = service.reconcile(
        now=third_started_at,
        safety_window_seconds=3600,
        cleanup_enabled=True,
    )

    assert evidence.candidates_claimed == 0
    assert evidence.candidates_deleted == 0
    assert store.contains(storage_key) is True
    with get_session(reconciliation_database) as session:
        candidate = session.get(MediaArtifactOrphanCandidate, storage_key)
        head = session.scalar(
            session.query(MediaArtifactReconciliationPass)
            .filter(MediaArtifactReconciliationPass.head_slot == "head")
            .statement
        )
        assert candidate is not None and head is not None
        assert candidate.last_pass_id == head.pass_id
        assert candidate.state == "retry_wait"
        assert candidate.attempt_count == 4
        assert candidate.retry_at is not None
        assert candidate.retry_at.replace(tzinfo=UTC) == retry_at
        assert candidate.last_error_code == "artifact_store.conditional_delete_failed"


def test_object_token_change_starts_new_candidate_generation_without_attempts(
    reconciliation_database: str,
    tmp_path: Path,
) -> None:
    service, store, storage_key, second_started_at = _prepare_eligible_candidate(
        reconciliation_database,
        tmp_path / "retry-new-generation",
    )
    with get_session(reconciliation_database) as session:
        candidate = session.get(MediaArtifactOrphanCandidate, storage_key)
        assert candidate is not None
        candidate.state = "retry_wait"
        candidate.attempt_count = 7
        candidate.retry_at = second_started_at + timedelta(days=1)
        candidate.last_error_code = "artifact_store.conditional_delete_failed"
        session.commit()
    path = (
        store.root / storage_key[4:6] / storage_key[6:8] / storage_key
    )
    replacement = path.with_name("replacement.tmp")
    replacement.write_bytes(b"orphan")
    os.chmod(replacement, 0o600)
    os.replace(replacement, path)
    third_started_at = second_started_at + timedelta(seconds=3601)
    _age_object(
        store.root,
        storage_key,
        modified_at=third_started_at - timedelta(days=2),
    )

    evidence = service.reconcile(
        now=third_started_at,
        safety_window_seconds=3600,
        cleanup_enabled=True,
    )

    assert evidence.cleanup_candidates_eligible == 0
    assert evidence.candidates_claimed == 0
    assert store.contains(storage_key) is True
    with get_session(reconciliation_database) as session:
        candidate = session.get(MediaArtifactOrphanCandidate, storage_key)
        assert candidate is not None
        assert candidate.state == "observed"
        assert candidate.attempt_count == 0
        assert candidate.retry_at is None
        assert candidate.last_error_code is None


def test_claim_cas_stale_reclaim_and_old_finalize_cannot_overwrite(
    reconciliation_database: str,
    tmp_path: Path,
) -> None:
    service, store, storage_key, now = _prepare_eligible_candidate(
        reconciliation_database,
        tmp_path / "claim-cas",
    )
    reconciliation = store.try_open_reconciliation_session()
    assert reconciliation is not None
    try:
        first, _, _ = service._claim_one_candidate(
            reconciliation=reconciliation,
            storage_key=storage_key,
            now=now,
            claim_lease_seconds=300,
        )
        second, _, _ = service._claim_one_candidate(
            reconciliation=reconciliation,
            storage_key=storage_key,
            now=now,
            claim_lease_seconds=300,
        )
    finally:
        reconciliation.release()
    assert first is not None
    assert second is None
    old = _CleanupClaim(
        storage_key=storage_key,
        object_version=first.object_version,
        claim_id="ocl_superseded",
        attempt_count=1,
    )
    assert service._finalize_cleanup_success(claim=old, now=now) is False
    assert (
        service._finalize_cleanup_failure(
            claim=old,
            now=now,
            retry_base_seconds=30,
            retry_max_seconds=3600,
        )
        is False
    )

    with get_session(reconciliation_database) as session:
        candidate = session.get(MediaArtifactOrphanCandidate, storage_key)
        assert candidate is not None
        candidate.claim_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    evidence = service._cleanup_candidates(
        now=datetime.now(UTC),
        batch_size=25,
        claim_lease_seconds=300,
        retry_base_seconds=30,
        retry_max_seconds=3600,
    )
    assert evidence["stale_claims_reclaimed"] == 1
    assert evidence["candidates_deleted"] == 1


def test_unlink_then_finalize_loss_converges_through_durable_missing_retry(
    reconciliation_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, store, storage_key, now = _prepare_eligible_candidate(
        reconciliation_database,
        tmp_path / "finalize-loss",
    )
    original_finalize = service._finalize_cleanup_success
    monkeypatch.setattr(service, "_finalize_cleanup_success", lambda **_kwargs: False)
    first = service._cleanup_candidates(
        now=now,
        batch_size=25,
        claim_lease_seconds=300,
        retry_base_seconds=30,
        retry_max_seconds=3600,
    )
    assert first["superseded_finalizations"] == 1
    assert store.contains(storage_key) is False
    with get_session(reconciliation_database) as session:
        candidate = session.get(MediaArtifactOrphanCandidate, storage_key)
        assert candidate is not None and candidate.state == "claimed"
        candidate.claim_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    monkeypatch.setattr(service, "_finalize_cleanup_success", original_finalize)
    second = service._cleanup_candidates(
        now=now + timedelta(seconds=1),
        batch_size=25,
        claim_lease_seconds=300,
        retry_base_seconds=30,
        retry_max_seconds=3600,
    )
    assert second["stale_claims_reclaimed"] == 1
    assert second["candidates_deleted"] == 1
    with get_session(reconciliation_database) as session:
        candidate = session.get(MediaArtifactOrphanCandidate, storage_key)
        assert candidate is not None and candidate.state == "deleted"


@pytest.mark.parametrize("fatal", [False, True])
def test_delete_errors_release_fence_and_preserve_retry_or_base_exception(
    reconciliation_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fatal: bool,
) -> None:
    service, store, storage_key, now = _prepare_eligible_candidate(
        reconciliation_database,
        tmp_path / f"delete-error-{fatal}",
    )

    class FatalDelete(BaseException):
        pass

    fatal_error = FatalDelete("exact fatal delete")
    release_count = 0

    class FailingSession:
        def __init__(self, inner: object) -> None:
            self._inner = inner

        @property
        def store_generation(self) -> str:
            return self._inner.store_generation  # type: ignore[attr-defined,no-any-return]

        def validate(self) -> None:
            self._inner.validate()  # type: ignore[attr-defined]

        def delete_if_unchanged(self, key: str, token: str):  # type: ignore[no-untyped-def]
            del key, token
            if fatal:
                raise fatal_error
            raise ArtifactStoreError("private backend failure")

        def release(self) -> None:
            nonlocal release_count
            release_count += 1
            self._inner.release()  # type: ignore[attr-defined]

    original_open = store.try_open_reconciliation_session

    def open_failing():  # type: ignore[no-untyped-def]
        inner = original_open()
        return None if inner is None else FailingSession(inner)

    monkeypatch.setattr(store, "try_open_reconciliation_session", open_failing)
    if fatal:
        with pytest.raises(FatalDelete) as caught:
            service._cleanup_candidates(
                now=now,
                batch_size=25,
                claim_lease_seconds=300,
                retry_base_seconds=30,
                retry_max_seconds=3600,
            )
        assert caught.value is fatal_error
    else:
        evidence = service._cleanup_candidates(
            now=now,
            batch_size=25,
            claim_lease_seconds=300,
            retry_base_seconds=30,
            retry_max_seconds=3600,
        )
        assert evidence["retry_scheduled"] == 1
    assert release_count == 1
    assert store.contains(storage_key) is True
    with get_session(reconciliation_database) as session:
        candidate = session.get(MediaArtifactOrphanCandidate, storage_key)
        assert candidate is not None
        if fatal:
            assert candidate.state == "claimed"
            assert candidate.claim_id is not None
        else:
            assert candidate.state == "retry_wait"
            assert candidate.last_error_code == "artifact_store.conditional_delete_failed"


@pytest.mark.parametrize("fatal", [False, True])
def test_final_reference_recheck_failure_never_deletes_and_preserves_fatal_claim(
    reconciliation_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fatal: bool,
) -> None:
    service, store, storage_key, now = _prepare_eligible_candidate(
        reconciliation_database,
        tmp_path / f"final-recheck-error-{fatal}",
    )

    class FatalRecheck(BaseException):
        pass

    failure: BaseException = (
        FatalRecheck("exact fatal final recheck")
        if fatal
        else RuntimeError("final reference query failed")
    )

    def fail_recheck(**_kwargs: object) -> str:
        raise failure

    monkeypatch.setattr(service, "_refresh_and_recheck_claim", fail_recheck)
    if fatal:
        with pytest.raises(FatalRecheck) as caught:
            service._cleanup_candidates(
                now=now,
                batch_size=25,
                claim_lease_seconds=300,
                retry_base_seconds=30,
                retry_max_seconds=3600,
            )
        assert caught.value is failure
    else:
        evidence = service._cleanup_candidates(
            now=now,
            batch_size=25,
            claim_lease_seconds=300,
            retry_base_seconds=30,
            retry_max_seconds=3600,
        )
        assert evidence["retry_scheduled"] == 1
        assert evidence["candidates_deleted"] == 0
    assert store.contains(storage_key) is True
    with get_session(reconciliation_database) as session:
        candidate = session.get(MediaArtifactOrphanCandidate, storage_key)
        assert candidate is not None
        if fatal:
            assert candidate.state == "claimed"
            assert candidate.claim_id is not None
        else:
            assert candidate.state == "retry_wait"
            assert candidate.last_error_code == "artifact_store.conditional_delete_failed"


def test_retry_backoff_starts_when_late_candidate_failure_occurs(
    reconciliation_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, store, storage_key, logical_start = _prepare_eligible_candidate(
        reconciliation_database,
        tmp_path / "late-retry-clock",
    )
    wall_clock = [datetime.now(UTC)]
    monkeypatch.setattr(service, "_clock_now", lambda: wall_clock[0])

    def fail_after_slow_precheck(**_kwargs: object) -> str:
        wall_clock[0] += timedelta(seconds=120)
        raise RuntimeError("late final reference query failure")

    monkeypatch.setattr(
        service,
        "_refresh_and_recheck_claim",
        fail_after_slow_precheck,
    )

    evidence = service._cleanup_candidates(
        now=logical_start,
        batch_size=25,
        claim_lease_seconds=300,
        retry_base_seconds=30,
        retry_max_seconds=3600,
    )

    assert evidence["retry_scheduled"] == 1
    assert store.contains(storage_key) is True
    with get_session(reconciliation_database) as session:
        candidate = session.get(MediaArtifactOrphanCandidate, storage_key)
        assert candidate is not None
        assert candidate.state == "retry_wait"
        assert candidate.retry_at is not None
        assert candidate.retry_at.replace(tzinfo=UTC) == (
            logical_start + timedelta(seconds=150)
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"safety_window_seconds": 3599},
        {"page_size": 0},
        {"page_size": 501},
        {"pass_lease_seconds": 299},
        {"pass_lease_seconds": 3601},
        {"cleanup_batch_size": 0},
        {"cleanup_batch_size": 101},
        {"claim_lease_seconds": 29},
        {"claim_lease_seconds": 3601},
        {"retry_base_seconds": 0},
        {"retry_base_seconds": 3601},
        {"retry_base_seconds": 60, "retry_max_seconds": 30},
        {"retry_max_seconds": 86401},
    ],
)
def test_service_rejects_direct_unbounded_reconciliation_settings(
    reconciliation_database: str,
    tmp_path: Path,
    overrides: dict[str, int],
) -> None:
    service = MediaArtifactOrphanReconciliationService(
        reconciliation_database,
        artifact_store=LocalVolumeArtifactStore(tmp_path / "invalid-settings"),
    )

    with pytest.raises(MediaArtifactOrphanReconciliationError):
        service.reconcile(**overrides)


@pytest.mark.parametrize("failure_kind", ["generation", "database_scan"])
def test_mid_pass_ordinary_failure_never_becomes_completed_head(
    reconciliation_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    root = tmp_path / failure_kind
    store = LocalVolumeArtifactStore(root)
    store.put(io.BytesIO(b"first"), max_bytes=5)
    store.put(io.BytesIO(b"second"), max_bytes=6)
    service = MediaArtifactOrphanReconciliationService(
        reconciliation_database,
        artifact_store=store,
    )
    if failure_kind == "generation":
        original = store.list_objects
        calls = 0

        def drift_generation(**kwargs: object):  # type: ignore[no-untyped-def]
            nonlocal calls
            page = original(**kwargs)  # type: ignore[arg-type]
            calls += 1
            if calls == 2:
                return dataclass_replace(page, store_generation=f"gen_{'f' * 32}")
            return page

        monkeypatch.setattr(store, "list_objects", drift_generation)
    else:
        monkeypatch.setattr(
            service,
            "_inspect_available_database_inventory",
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("private DB failure")),
        )

    with pytest.raises(MediaArtifactOrphanReconciliationError):
        service.reconcile(
            now=datetime.now(UTC) + timedelta(days=2),
            page_size=1,
        )

    with get_session(reconciliation_database) as session:
        passes = list(session.query(MediaArtifactReconciliationPass))
        assert passes
        assert all(item.state == "abandoned" for item in passes)
        assert all(item.head_slot is None for item in passes)


def test_mid_pass_base_exception_escapes_exactly_and_never_completes(
    reconciliation_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FatalScan(BaseException):
        pass

    failure = FatalScan("exact fatal scan")
    store = LocalVolumeArtifactStore(tmp_path / "fatal-scan")
    store.put(io.BytesIO(b"orphan"), max_bytes=6)
    service = MediaArtifactOrphanReconciliationService(
        reconciliation_database,
        artifact_store=store,
    )
    monkeypatch.setattr(
        service,
        "_inspect_available_database_inventory",
        lambda **_kwargs: (_ for _ in ()).throw(failure),
    )

    with pytest.raises(FatalScan) as caught:
        service.reconcile(now=datetime.now(UTC) + timedelta(days=2))
    assert caught.value is failure
    with get_session(reconciliation_database) as session:
        passes = list(session.query(MediaArtifactReconciliationPass))
        assert len(passes) == 1
        assert passes[0].state == "running"
        assert passes[0].head_slot is None
