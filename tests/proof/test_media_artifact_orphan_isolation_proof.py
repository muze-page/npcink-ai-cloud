"""P3-B4C3 PostgreSQL and named-volume isolation proof harness."""

from __future__ import annotations

import hashlib
import io
import os
import signal
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import cast

import pytest
from sqlalchemy import create_engine, delete, event, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.repositories.runtime_repository import RuntimeRepository
from app.core.db import dispose_engine, get_engine, get_session
from app.core.models import (
    MediaArtifact,
    MediaArtifactOrphanCandidate,
    MediaArtifactReconciliationPass,
    Site,
)
from app.domain.media_artifacts.orphan_reconciliation import (
    MediaArtifactOrphanReconciliationService,
    _CleanupClaim,
)
from app.domain.media_artifacts.store import (
    ArtifactReconciliationSession,
    ArtifactStorageMetadata,
    LocalVolumeArtifactStore,
)

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get("NPCINK_CLOUD_DATABASE_URL", "")
ARTIFACT_ROOT = Path(
    os.environ.get(
        "NPCINK_CLOUD_ARTIFACT_STORE_ROOT",
        "/var/lib/npcink-ai-cloud/artifacts",
    )
)
ROLE = os.environ.get("NPCINK_CLOUD_P3_B4C3_PROOF_ROLE", "")
MIGRATION_HEAD = "20260716_0066"
SAFETY_WINDOW_SECONDS = 3600
HANDSHAKE_TIMEOUT_SECONDS = 45.0
STORE_GENERATION = "proof_claim_generation"
OLD_STALE_CLAIM_ID = "proof_old_stale_claim"

pytestmark = pytest.mark.skipif(
    ROLE not in {"a", "b"},
    reason="the isolated compose proof supplies both proof roles",
)


class _ProofSync:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def record(self, phase: str, actor: str, value: int = 1) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO p3_b4c3_proof_sync (phase, actor, value_int)
                    VALUES (:phase, :actor, :value)
                    ON CONFLICT (phase, actor)
                    DO UPDATE SET value_int = EXCLUDED.value_int
                    """
                ),
                {"phase": phase, "actor": actor, "value": int(value)},
            )

    def signal(self, phase: str) -> None:
        self.record(phase, "coordinator")

    def wait_count(self, phase: str, expected: int) -> None:
        deadline = monotonic() + HANDSHAKE_TIMEOUT_SECONDS
        while monotonic() < deadline:
            try:
                with self._engine.connect() as connection:
                    observed = int(
                        connection.scalar(
                            text(
                                "SELECT count(*) FROM p3_b4c3_proof_sync "
                                "WHERE phase = :phase"
                            ),
                            {"phase": phase},
                        )
                        or 0
                    )
                if observed >= expected:
                    return
            except SQLAlchemyError:
                pass
            _database_handshake_pause(self._engine)
        raise AssertionError("bounded proof database handshake timed out")

    def values(self, phase: str) -> dict[str, int]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT actor, value_int FROM p3_b4c3_proof_sync "
                    "WHERE phase = :phase ORDER BY actor"
                ),
                {"phase": phase},
            ).all()
        return {str(actor): int(value) for actor, value in rows}


class _ClaimReconciliation:
    @property
    def store_generation(self) -> str:
        return STORE_GENERATION


def _matches_pass_insert(statement: str) -> bool:
    normalized = " ".join(statement.lower().split())
    return normalized.startswith("insert into media_artifact_reconciliation_passes ")


def _matches_claim_update(statement: str) -> bool:
    normalized = " ".join(statement.lower().split())
    required_assignments = (
        "state=",
        "claim_id=",
        "claim_expires_at=",
        "attempt_count=",
        "retry_at=",
        "last_error_code=",
    )
    return normalized.startswith("update media_artifact_orphan_candidates set ") and all(
        assignment in normalized for assignment in required_assignments
    )


@contextmanager
def _contested_sql_barrier(
    sync: _ProofSync,
    *,
    case: str,
    matcher: Callable[[str], bool],
) -> Iterator[None]:
    """Release one contested statement only after both processes reach it."""

    production_engine = get_engine(DATABASE_URL)
    reached = False
    phase = f"{case}_sql_ready"

    def before_cursor_execute(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal reached
        if reached or not matcher(statement):
            return
        reached = True
        sync.record(phase, ROLE)
        sync.wait_count(phase, 2)

    event.listen(production_engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield
    finally:
        event.remove(production_engine, "before_cursor_execute", before_cursor_execute)
        assert reached


def _database_handshake_pause(engine: Engine) -> None:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT pg_sleep(0.02)"))
    except SQLAlchemyError:
        return


def _wait_for_migration_head(engine: Engine) -> None:
    deadline = monotonic() + HANDSHAKE_TIMEOUT_SECONDS
    while monotonic() < deadline:
        try:
            with engine.connect() as connection:
                version = connection.scalar(text("SELECT version_num FROM alembic_version"))
            if version == MIGRATION_HEAD:
                return
        except SQLAlchemyError:
            pass
        _database_handshake_pause(engine)
    raise AssertionError("bounded migration database handshake timed out")


def _bootstrap_database(engine: Engine) -> _ProofSync:
    if ROLE == "a":
        completed = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=ROOT,
            env={**os.environ, "NPCINK_CLOUD_DATABASE_URL": DATABASE_URL},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=HANDSHAKE_TIMEOUT_SECONDS,
            check=False,
        )
        assert completed.returncode == 0
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS p3_b4c3_proof_sync (
                        phase VARCHAR(96) NOT NULL,
                        actor VARCHAR(16) NOT NULL,
                        value_int INTEGER NOT NULL,
                        PRIMARY KEY (phase, actor)
                    )
                    """
                )
            )
            connection.execute(text("TRUNCATE TABLE p3_b4c3_proof_sync"))
        sync = _ProofSync(engine)
        sync.signal("bootstrap_ready")
        return sync

    _wait_for_migration_head(engine)
    sync = _ProofSync(engine)
    sync.wait_count("bootstrap_ready", 1)
    return sync


def _verify_postgres_and_connections(
    engine: Engine,
    sync: _ProofSync,
    *,
    backend_pid: int,
) -> None:
    sync.record("live_connection", ROLE, backend_pid)
    if ROLE != "a":
        sync.wait_count("connections_verified", 1)
        return

    sync.wait_count("live_connection", 2)
    pids = sync.values("live_connection")
    assert set(pids) == {"a", "b"}
    assert pids["a"] != pids["b"]
    with engine.connect() as connection:
        server_version_num = int(connection.scalar(text("SHOW server_version_num")) or 0)
        migration_head = connection.scalar(text("SELECT version_num FROM alembic_version"))
        live_connections = int(
            connection.scalar(
                text("SELECT count(*) FROM pg_stat_activity WHERE pid IN (:pid_a, :pid_b)"),
                {"pid_a": pids["a"], "pid_b": pids["b"]},
            )
            or 0
        )
    assert server_version_num // 10000 == 16
    assert migration_head == MIGRATION_HEAD
    assert live_connections == 2
    sync.signal("connections_verified")


def _clear_reconciliation_state() -> None:
    with get_session(DATABASE_URL) as session:
        session.execute(delete(MediaArtifactOrphanCandidate))
        session.execute(delete(MediaArtifactReconciliationPass))
        session.commit()


def _run_active_pass_race(sync: _ProofSync) -> None:
    service = MediaArtifactOrphanReconciliationService(
        DATABASE_URL,
        artifact_store=LocalVolumeArtifactStore(ARTIFACT_ROOT),
    )
    if ROLE == "a":
        _clear_reconciliation_state()
        sync.signal("active_setup")
    sync.wait_count("active_setup", 1)
    sync.record("active_ready", ROLE)
    if ROLE == "a":
        sync.wait_count("active_ready", 2)
        sync.signal("active_go")
    sync.wait_count("active_go", 1)

    now = datetime.now(UTC)
    with _contested_sql_barrier(
        sync,
        case="active",
        matcher=_matches_pass_insert,
    ):
        claim = service._acquire_pass(
            now=now,
            cutoff=now - timedelta(seconds=SAFETY_WINDOW_SECONDS),
            store_generation=STORE_GENERATION,
            lease_seconds=60,
        )
    sync.record("active_result", ROLE, int(claim is not None))
    if ROLE == "a":
        sync.wait_count("active_result", 2)
        assert sum(sync.values("active_result").values()) == 1
        sync.signal("active_release")
    sync.wait_count("active_release", 1)
    if claim is not None:
        service._abandon_pass(claim)
    sync.record("active_cleaned", ROLE)
    if ROLE == "a":
        sync.wait_count("active_cleaned", 2)
        sync.signal("active_done")
    else:
        sync.wait_count("active_done", 1)


def _claim_storage_key(case: str) -> str:
    return "art_" + hashlib.sha256(f"p3-b4c3-{case}".encode()).hexdigest()


def _prepare_claim_case(case: str) -> tuple[str, str, int]:
    _clear_reconciliation_state()
    now = datetime.now(UTC)
    pass_id = f"proof_head_{case}"
    storage_key = _claim_storage_key(case)
    object_version = hashlib.sha256(f"object-{case}".encode()).hexdigest()
    attempt_count = 3 if case == "stale" else 1
    state = {
        "eligible": "eligible",
        "retry": "retry_wait",
        "stale": "claimed",
    }[case]
    with get_session(DATABASE_URL) as session:
        session.add(
            MediaArtifactReconciliationPass(
                pass_id=pass_id,
                state="completed",
                active_slot=None,
                head_slot="head",
                scan_claim_id=None,
                lease_expires_at=None,
                previous_completed_pass_id=None,
                store_generation=STORE_GENERATION,
                next_cursor=None,
                last_storage_key=None,
                store_examined=1,
                referenced_present=0,
                orphan_observed=1,
                orphan_deferred=0,
                orphan_eligible=1,
                db_available_examined=0,
                referenced_missing=0,
                started_at=now - timedelta(hours=2),
                cutoff_at=now - timedelta(hours=1),
                completed_at=now - timedelta(hours=1),
            )
        )
        session.flush()
        session.add(
            MediaArtifactOrphanCandidate(
                storage_key=storage_key,
                object_version=object_version,
                store_generation=STORE_GENERATION,
                first_pass_id=pass_id,
                last_pass_id=pass_id,
                state=state,
                claim_id=OLD_STALE_CLAIM_ID if case == "stale" else None,
                claim_expires_at=(
                    now - timedelta(seconds=1) if case == "stale" else None
                ),
                attempt_count=attempt_count,
                retry_at=now - timedelta(seconds=1) if case == "retry" else None,
                last_error_code=(
                    "artifact_store.conditional_delete_failed"
                    if case == "retry"
                    else None
                ),
                first_observed_at=now - timedelta(hours=2),
                last_observed_at=now - timedelta(hours=1),
                resolved_at=None,
            )
        )
        session.commit()
    return storage_key, object_version, attempt_count


def _run_claim_race(sync: _ProofSync, case: str) -> None:
    setup_phase = f"claim_{case}_setup"
    ready_phase = f"claim_{case}_ready"
    go_phase = f"claim_{case}_go"
    result_phase = f"claim_{case}_result"
    reclaimed_phase = f"claim_{case}_reclaimed"
    done_phase = f"claim_{case}_done"
    if ROLE == "a":
        storage_key, object_version, attempt_count = _prepare_claim_case(case)
        sync.signal(setup_phase)
    else:
        storage_key = _claim_storage_key(case)
        object_version = hashlib.sha256(f"object-{case}".encode()).hexdigest()
        attempt_count = 3 if case == "stale" else 1
    sync.wait_count(setup_phase, 1)
    sync.record(ready_phase, ROLE)
    if ROLE == "a":
        sync.wait_count(ready_phase, 2)
        sync.signal(go_phase)
    sync.wait_count(go_phase, 1)

    service = MediaArtifactOrphanReconciliationService(
        DATABASE_URL,
        artifact_store=LocalVolumeArtifactStore(ARTIFACT_ROOT),
    )
    with _contested_sql_barrier(
        sync,
        case=case,
        matcher=_matches_claim_update,
    ):
        claim, reclaimed, invalidated = service._claim_one_candidate(
            reconciliation=cast(
                ArtifactReconciliationSession,
                _ClaimReconciliation(),
            ),
            storage_key=storage_key,
            now=datetime.now(UTC),
            claim_lease_seconds=60,
        )
    assert invalidated is False
    sync.record(result_phase, ROLE, int(claim is not None))
    sync.record(reclaimed_phase, ROLE, int(reclaimed))

    if ROLE == "a":
        sync.wait_count(result_phase, 2)
        sync.wait_count(reclaimed_phase, 2)
        assert sum(sync.values(result_phase).values()) == 1
        expected_reclaims = 1 if case == "stale" else 0
        assert sum(sync.values(reclaimed_phase).values()) == expected_reclaims
        if case == "stale":
            old_finalize = service._finalize_cleanup_success(
                claim=_CleanupClaim(
                    storage_key=storage_key,
                    object_version=object_version,
                    claim_id=OLD_STALE_CLAIM_ID,
                    attempt_count=attempt_count,
                ),
                now=datetime.now(UTC),
            )
            assert old_finalize is False
            with get_session(DATABASE_URL) as session:
                candidate = session.get(MediaArtifactOrphanCandidate, storage_key)
                assert candidate is not None
                assert candidate.state == "claimed"
                assert candidate.claim_id not in {None, OLD_STALE_CLAIM_ID}
        sync.signal(done_phase)
    else:
        sync.wait_count(done_phase, 1)


def _run_publication_fence_proof(sync: _ProofSync) -> None:
    store = LocalVolumeArtifactStore(ARTIFACT_ROOT)
    if ROLE == "a":
        publication = store.open_publication_session()
        try:
            sync.signal("fence_shared_held")
            sync.wait_count("fence_busy_result", 1)
            assert sum(sync.values("fence_busy_result").values()) == 1
        finally:
            publication.release()
        sync.signal("fence_shared_released")
        sync.wait_count("fence_exclusive_result", 1)
        assert sum(sync.values("fence_exclusive_result").values()) == 1
        sync.signal("fence_done")
        return

    sync.wait_count("fence_shared_held", 1)
    reconciliation = store.try_open_reconciliation_session()
    busy = reconciliation is None
    if reconciliation is not None:
        reconciliation.release()
    sync.record("fence_busy_result", ROLE, int(busy))
    sync.wait_count("fence_shared_released", 1)
    reconciliation = store.try_open_reconciliation_session()
    acquired = reconciliation is not None
    if reconciliation is not None:
        reconciliation.release()
    sync.record("fence_exclusive_result", ROLE, int(acquired))
    sync.wait_count("fence_done", 1)


def _seed_reference_run() -> None:
    with get_session(DATABASE_URL) as session:
        session.add(
            Site(
                site_id="site_p3_b4c3_proof",
                name="P3 B4C3 proof",
                status="active",
            )
        )
        session.flush()
        RuntimeRepository(session).create_run(
            run_id="run_p3_b4c3_proof",
            site_id="site_p3_b4c3_proof",
            account_id=None,
            subscription_id=None,
            plan_version_id=None,
            ability_name="npcink-cloud/p3-b4c3-proof",
            ability_family="media",
            skill_id="",
            workflow_id="",
            contract_version="p3_b4c3_proof.v1",
            channel="internal",
            execution_kind="media",
            execution_tier="cloud",
            execution_pattern="inline",
            data_classification="internal",
            profile_id="media.p3_b4c3.proof",
            canonical_run_id=None,
            status="succeeded",
            idempotency_key="p3-b4c3-proof",
            request_fingerprint="p3-b4c3-proof",
            trace_id="p3b4c3proof",
            input_json={},
            execution_input_ciphertext=None,
            policy_json={"storage_mode": "result_only"},
        )
        session.commit()


def _reference_artifact(
    stored: ArtifactStorageMetadata,
    *,
    index: int,
    status: str,
    now: datetime,
) -> MediaArtifact:
    expires_at = now - timedelta(hours=1) if status == "expired" else now + timedelta(days=1)
    return MediaArtifact(
        artifact_id=f"proof_artifact_{index}",
        run_id="run_p3_b4c3_proof",
        site_id="site_p3_b4c3_proof",
        media_kind="image",
        operation="image.transform.v1",
        content_type="image/png",
        byte_size=stored.byte_size,
        storage_key=stored.storage_key,
        status=status,
        format="png",
        width=1,
        height=1,
        checksum=stored.checksum,
        expires_at=expires_at,
        purged_at=now if status == "purged" else None,
        created_at=now,
    )


def _run_two_pass_named_volume_proof() -> None:
    assert SAFETY_WINDOW_SECONDS >= 3600
    assert os.environ.get("NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_ENABLED") == "true"
    _clear_reconciliation_state()
    _seed_reference_run()
    store = LocalVolumeArtifactStore(ARTIFACT_ROOT)
    orphan = store.put(io.BytesIO(b"proof-orphan"), max_bytes=64)
    statuses = ("available", "expired", "purged", "future_proof_state")
    referenced = tuple(
        store.put(io.BytesIO(f"proof-reference-{status}".encode()), max_bytes=64)
        for status in statuses
    )
    service = MediaArtifactOrphanReconciliationService(
        DATABASE_URL,
        artifact_store=store,
    )
    first_started_at = datetime.now(UTC) + timedelta(
        seconds=SAFETY_WINDOW_SECONDS * 2
    )
    first = service.reconcile(
        now=first_started_at,
        safety_window_seconds=SAFETY_WINDOW_SECONDS,
        page_size=2,
        cleanup_enabled=False,
    )
    assert first.pass_completed == 1
    assert first.deletion_enabled is False
    assert first.cleanup_candidates_eligible == 0
    assert first.candidates_deleted == 0

    with get_session(DATABASE_URL) as session:
        session.add_all(
            _reference_artifact(stored, index=index, status=status, now=first_started_at)
            for index, (stored, status) in enumerate(zip(referenced, statuses, strict=True))
        )
        session.commit()

    second = service.reconcile(
        now=first_started_at + timedelta(seconds=SAFETY_WINDOW_SECONDS + 60),
        safety_window_seconds=SAFETY_WINDOW_SECONDS,
        page_size=2,
        cleanup_enabled=True,
        cleanup_batch_size=16,
    )
    assert second.pass_completed == 1
    assert second.deletion_enabled is True
    assert second.cleanup_candidates_eligible == 1
    assert second.candidates_claimed == 1
    assert second.candidates_deleted == 1
    assert store.contains(orphan.storage_key) is False
    assert all(store.contains(stored.storage_key) for stored in referenced)

    with get_session(DATABASE_URL) as session:
        orphan_candidate = session.get(MediaArtifactOrphanCandidate, orphan.storage_key)
        assert orphan_candidate is not None
        assert orphan_candidate.state == "deleted"
        reference_candidates = tuple(
            session.get(MediaArtifactOrphanCandidate, stored.storage_key)
            for stored in referenced
        )
        assert all(candidate is not None for candidate in reference_candidates)
        assert all(
            candidate is not None and candidate.state == "invalidated"
            for candidate in reference_candidates
        )
        assert session.scalar(
            select(func.count(MediaArtifact.artifact_id)).where(
                MediaArtifact.status.in_(statuses)
            )
        ) == len(statuses)


def test_postgres_16_named_volume_concurrency_and_cleanup_proof() -> None:
    assert ROLE in {"a", "b"}
    assert DATABASE_URL.startswith("postgresql+psycopg://")
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        sync = _bootstrap_database(engine)
        with engine.connect() as anchor:
            backend_pid = int(anchor.scalar(text("SELECT pg_backend_pid()")) or 0)
            _verify_postgres_and_connections(engine, sync, backend_pid=backend_pid)
            _run_active_pass_race(sync)
            for case in ("eligible", "retry", "stale"):
                _run_claim_race(sync, case)
            _run_publication_fence_proof(sync)
            if ROLE == "a":
                _run_two_pass_named_volume_proof()
                sync.signal("proof_complete")
                sync.wait_count("proof_complete_observed", 1)
            else:
                sync.wait_count("proof_complete", 1)
                sync.record("proof_complete_observed", ROLE)
                signal.pause()
    finally:
        engine.dispose()
        dispose_engine(DATABASE_URL)
