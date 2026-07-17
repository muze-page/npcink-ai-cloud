from __future__ import annotations

import ast
import io
import multiprocessing
from collections.abc import Mapping
from pathlib import Path
from typing import BinaryIO

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.domain.media_artifacts import publication as publication_tracker
from app.domain.media_artifacts.publication import (
    ArtifactPublicationCleanupUncertainError,
    publish_and_track_artifact,
    track_artifact_publication,
    tracked_artifact_storage_keys,
    uncertain_artifact_storage_keys,
)
from app.domain.media_artifacts.store import (
    ArtifactStorageMetadata,
    ArtifactStoreError,
    ArtifactStorePublicationUncertainError,
    LocalVolumeArtifactStore,
)

ROOT = Path(__file__).resolve().parents[2]


class _Base(DeclarativeBase):
    pass


class _UniquePublicationRow(_Base):
    __tablename__ = "test_unique_publication_rows"

    id: Mapped[int] = mapped_column(primary_key=True)


class _RecordingStore:
    chunk_size = 4096

    def __init__(
        self,
        *storage_keys: str,
        publication_uncertain: bool = False,
        delete_fails: bool = False,
    ) -> None:
        self.storage_keys = list(storage_keys)
        self.publication_uncertain = publication_uncertain
        self.delete_fails = delete_fails
        self.put_calls: list[bytes] = []
        self.delete_calls: list[str] = []
        self.publication_error: ArtifactStorePublicationUncertainError | None = None

    def put(
        self,
        stream: BinaryIO,
        *,
        max_bytes: int,
        metadata: Mapping[str, str] | None = None,
    ) -> ArtifactStorageMetadata:
        del metadata
        payload = stream.read()
        assert len(payload) <= max_bytes
        self.put_calls.append(payload)
        storage_key = self.storage_keys.pop(0)
        stored = ArtifactStorageMetadata(
            storage_key=storage_key,
            byte_size=len(payload),
            checksum=f"sha256:{'a' * 64}",
        )
        if self.publication_uncertain:
            self.publication_error = ArtifactStorePublicationUncertainError(stored)
            raise self.publication_error
        return stored

    def delete(self, storage_key: str) -> None:
        self.delete_calls.append(storage_key)
        if self.delete_fails:
            raise ArtifactStoreError("injected delete failure")


class _RecordingGuard:
    def __init__(self) -> None:
        self.release_count = 0

    @property
    def released(self) -> bool:
        return self.release_count > 0

    def release(self) -> None:
        self.release_count += 1


class _FencedRecordingStore(_RecordingStore):
    def __init__(self, *storage_keys: str, **kwargs: object) -> None:
        super().__init__(*storage_keys, **kwargs)  # type: ignore[arg-type]
        self.guards: list[_RecordingGuard] = []
        self.guard_state_during_delete: list[bool] = []

    def acquire_publication_guard(self) -> _RecordingGuard:
        guard = _RecordingGuard()
        self.guards.append(guard)
        return guard

    def try_acquire_reconciliation_guard(self) -> _RecordingGuard | None:
        return None

    def delete(self, storage_key: str) -> None:
        self.guard_state_during_delete.append(self.guards[-1].released)
        super().delete(storage_key)


def _try_local_volume_exclusive(root: str, result_queue: object) -> None:
    store = LocalVolumeArtifactStore(root)
    guard = store.try_acquire_reconciliation_guard()
    result_queue.put(guard is not None)  # type: ignore[attr-defined]
    if guard is not None:
        guard.release()


def _exclusive_is_available(root: Path) -> bool:
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    process = context.Process(
        target=_try_local_volume_exclusive,
        args=(str(root), result_queue),
    )
    process.start()
    try:
        result = bool(result_queue.get(timeout=10))
    finally:
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
            process.join(timeout=10)
    assert process.exitcode == 0
    return result


def _publish(session: Session, store: _RecordingStore) -> ArtifactStorageMetadata:
    return publish_and_track_artifact(
        session,
        store=store,  # type: ignore[arg-type]
        stream=io.BytesIO(b"artifact-payload"),
        max_bytes=1024,
        metadata={"media_kind": "image"},
    )


def _commit_then_lose_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
    engine: sa.Engine,
) -> None:
    original_do_commit = engine.dialect.do_commit

    def commit_then_raise(dbapi_connection: object) -> None:
        original_do_commit(dbapi_connection)  # type: ignore[arg-type]
        raise OSError("commit acknowledgement lost")

    monkeypatch.setattr(engine.dialect, "do_commit", commit_then_raise)


def _assert_no_transient_listener_state(session: Session) -> None:
    assert "media_artifact_publication_connection_commit_listener.v1" not in session.info
    assert "media_artifact_publication_outcome.v1" not in session.info


def test_successful_commit_keeps_published_object() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    store = _RecordingStore("obj_00000000000000000000000000000001")
    with Session(engine) as session:
        stored = _publish(session, store)
        assert tracked_artifact_storage_keys(session) == (stored.storage_key,)

        session.commit()

        assert tracked_artifact_storage_keys(session) == ()
        assert uncertain_artifact_storage_keys(session) == ()
        assert store.delete_calls == []
        _assert_no_transient_listener_state(session)

        session.execute(sa.text("SELECT 1"))
        session.commit()
        _assert_no_transient_listener_state(session)
    engine.dispose()


def test_ordinary_rollback_deletes_published_object() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    store = _RecordingStore("obj_00000000000000000000000000000002")
    with Session(engine) as session:
        stored = _publish(session, store)

        session.rollback()

        assert store.delete_calls == [stored.storage_key]
        assert tracked_artifact_storage_keys(session) == ()
        assert uncertain_artifact_storage_keys(session) == ()
    engine.dispose()


def test_publication_fence_releases_after_definitive_commit() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    store = _FencedRecordingStore("obj_00000000000000000000000000000021")
    with Session(engine) as session:
        _publish(session, store)
        assert store.guards[0].released is False

        session.commit()

        assert store.guards[0].release_count == 1
        assert store.delete_calls == []
    engine.dispose()


def test_real_local_volume_fence_covers_commit_until_outcome(
    tmp_path: Path,
) -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    root = tmp_path / "commit-artifacts"
    store = LocalVolumeArtifactStore(root)
    with Session(engine) as session:
        _publish(session, store)  # type: ignore[arg-type]
        assert _exclusive_is_available(root) is False

        session.commit()

        assert _exclusive_is_available(root) is True
    engine.dispose()


def test_publication_fence_covers_rollback_delete_then_releases() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    store = _FencedRecordingStore("obj_00000000000000000000000000000022")
    with Session(engine) as session:
        _publish(session, store)

        session.rollback()

        assert store.guard_state_during_delete == [False]
        assert store.guards[0].release_count == 1
        assert uncertain_artifact_storage_keys(session) == ()
    engine.dispose()


def test_real_local_volume_fence_covers_rollback_delete_until_outcome(
    tmp_path: Path,
) -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    root = tmp_path / "rollback-artifacts"
    store = LocalVolumeArtifactStore(root)
    with Session(engine) as session:
        stored = _publish(session, store)  # type: ignore[arg-type]
        assert _exclusive_is_available(root) is False

        session.rollback()

        assert store.contains(stored.storage_key) is False
        assert _exclusive_is_available(root) is True
    engine.dispose()


def test_publication_fence_releases_when_uncertain_commit_is_quarantined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    _commit_then_lose_acknowledgement(monkeypatch, engine)
    storage_key = "obj_00000000000000000000000000000023"
    store = _FencedRecordingStore(storage_key)
    with Session(engine) as session:
        _publish(session, store)
        with pytest.raises(OSError, match="commit acknowledgement lost"):
            session.commit()

        assert store.guards[0].released is False
        session.rollback()

        assert store.guards[0].release_count == 1
        assert uncertain_artifact_storage_keys(session) == (storage_key,)
        assert store.delete_calls == []
    engine.dispose()


def test_real_local_volume_fence_holds_through_uncertain_commit_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    _commit_then_lose_acknowledgement(monkeypatch, engine)
    root = tmp_path / "uncertain-commit-artifacts"
    store = LocalVolumeArtifactStore(root)
    with Session(engine) as session:
        stored = _publish(session, store)  # type: ignore[arg-type]
        assert _exclusive_is_available(root) is False
        with pytest.raises(OSError, match="commit acknowledgement lost"):
            session.commit()

        assert _exclusive_is_available(root) is False
        session.rollback()

        assert uncertain_artifact_storage_keys(session) == (stored.storage_key,)
        assert store.contains(stored.storage_key) is True
        assert _exclusive_is_available(root) is True
    engine.dispose()


def test_publication_fence_releases_after_uncertain_publication_rollback() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    storage_key = "obj_00000000000000000000000000000024"
    store = _FencedRecordingStore(storage_key, publication_uncertain=True)
    with Session(engine) as session:
        with pytest.raises(ArtifactStorePublicationUncertainError):
            _publish(session, store)
        assert store.guards[0].released is False

        session.rollback()

        assert store.guard_state_during_delete == [False]
        assert store.guards[0].release_count == 1
    engine.dispose()


def test_publication_fence_releases_when_rollback_delete_is_quarantined() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    storage_key = "obj_00000000000000000000000000000025"
    store = _FencedRecordingStore(storage_key, delete_fails=True)
    with Session(engine) as session:
        _publish(session, store)

        with pytest.raises(ArtifactPublicationCleanupUncertainError):
            session.rollback()

        assert store.guard_state_during_delete == [False]
        assert store.guards[0].release_count == 1
        assert uncertain_artifact_storage_keys(session) == (storage_key,)
    engine.dispose()


def test_publication_fence_releases_and_preserves_exact_base_exception() -> None:
    class FatalDelete(BaseException):
        pass

    fatal = FatalDelete("fatal delete")

    class FatalDeleteStore(_FencedRecordingStore):
        def delete(self, storage_key: str) -> None:
            self.guard_state_during_delete.append(self.guards[-1].released)
            self.delete_calls.append(storage_key)
            raise fatal

    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    storage_key = "obj_00000000000000000000000000000026"
    store = FatalDeleteStore(storage_key)
    with Session(engine) as session:
        _publish(session, store)

        with pytest.raises(FatalDelete) as caught:
            session.rollback()

        assert caught.value is fatal
        assert store.guard_state_during_delete == [False]
        assert store.guards[0].release_count == 1
        assert uncertain_artifact_storage_keys(session) == (storage_key,)
    engine.dispose()


def test_real_local_volume_fence_releases_after_delete_base_exception(
    tmp_path: Path,
) -> None:
    class FatalDelete(BaseException):
        pass

    failure = FatalDelete("fatal local delete")

    class FatalPublicationSession:
        def __init__(self, inner: object) -> None:
            self.inner = inner

        def validate(self) -> None:
            self.inner.validate()  # type: ignore[attr-defined]

        def put(self, *args: object, **kwargs: object) -> ArtifactStorageMetadata:
            return self.inner.put(*args, **kwargs)  # type: ignore[attr-defined,no-any-return]

        def delete_published(self, storage_key: str) -> None:
            del storage_key
            raise failure

        def release(self) -> None:
            self.inner.release()  # type: ignore[attr-defined]

    class FatalLocalVolumeStore(LocalVolumeArtifactStore):
        def open_publication_session(self) -> FatalPublicationSession:
            return FatalPublicationSession(super().open_publication_session())

    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    root = tmp_path / "fatal-delete-artifacts"
    store = FatalLocalVolumeStore(root)
    with Session(engine) as session:
        stored = _publish(session, store)  # type: ignore[arg-type]
        assert _exclusive_is_available(root) is False

        with pytest.raises(FatalDelete) as caught:
            session.rollback()

        assert caught.value is failure
        assert uncertain_artifact_storage_keys(session) == (stored.storage_key,)
        assert _exclusive_is_available(root) is True
    engine.dispose()


def test_root_replacement_after_put_blocks_commit_and_rolls_back_on_pinned_root(
    tmp_path: Path,
) -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    _Base.metadata.create_all(engine)
    root = tmp_path / "configured-artifacts"
    pinned_root = tmp_path / "pinned-artifacts"
    replacement_store = LocalVolumeArtifactStore(root)
    store = LocalVolumeArtifactStore(root)
    with Session(engine) as session:
        stored = _publish(session, store)  # type: ignore[arg-type]
        session.add(_UniquePublicationRow(id=101))
        root.rename(pinned_root)
        replacement = replacement_store.open_publication_session()
        replacement.release()

        with pytest.raises(ArtifactStoreError, match="validation failed"):
            session.commit()

        pinned_path = (
            pinned_root
            / stored.storage_key[4:6]
            / stored.storage_key[6:8]
            / stored.storage_key
        )
        assert pinned_path.is_file()
        session.rollback()

        assert pinned_path.exists() is False
        assert uncertain_artifact_storage_keys(session) == ()
        assert _exclusive_is_available(pinned_root) is True

    with Session(engine) as verification:
        assert verification.get(_UniquePublicationRow, 101) is None
    engine.dispose()


def test_root_replacement_after_commit_before_release_is_quarantined(
    tmp_path: Path,
) -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    _Base.metadata.create_all(engine)
    root = tmp_path / "configured-artifacts"
    pinned_root = tmp_path / "committed-pinned-artifacts"
    store = LocalVolumeArtifactStore(root)
    replacement_store = LocalVolumeArtifactStore(root)
    with Session(engine) as session:
        stored = _publish(session, store)  # type: ignore[arg-type]
        session.add(_UniquePublicationRow(id=102))

        def replace_root_after_commit(_session: Session) -> None:
            root.rename(pinned_root)
            replacement = replacement_store.open_publication_session()
            replacement.release()

        event.listen(session, "after_commit", replace_root_after_commit, once=True)
        session.commit()

        assert uncertain_artifact_storage_keys(session) == (stored.storage_key,)
        pinned_path = (
            pinned_root
            / stored.storage_key[4:6]
            / stored.storage_key[6:8]
            / stored.storage_key
        )
        assert pinned_path.is_file()
        assert replacement_store.contains(stored.storage_key) is False
        assert _exclusive_is_available(pinned_root) is True

    with Session(engine) as verification:
        assert verification.get(_UniquePublicationRow, 102) is not None
    engine.dispose()


def test_low_level_tracking_releases_guard_when_listener_install_escapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ListenerFailure(BaseException):
        pass

    failure = ListenerFailure("listener failure")
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    store = _RecordingStore()
    guard = _RecordingGuard()
    monkeypatch.setattr(
        publication_tracker,
        "_install_session_listeners",
        lambda _session: (_ for _ in ()).throw(failure),
    )
    with Session(engine) as session:
        with pytest.raises(ListenerFailure) as caught:
            track_artifact_publication(
                session,
                store=store,  # type: ignore[arg-type]
                storage_key="obj_00000000000000000000000000000027",
                publication_guard=guard,
            )

        assert caught.value is failure
        assert guard.release_count == 1
        assert tracked_artifact_storage_keys(session) == ()
        session.rollback()
    engine.dispose()


def test_publish_helper_releases_non_idempotent_guard_once_on_listener_escape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ListenerFailure(BaseException):
        pass

    class StrictGuard:
        def __init__(self) -> None:
            self.release_count = 0

        def release(self) -> None:
            self.release_count += 1
            if self.release_count > 1:
                raise AssertionError("guard released more than once")

    failure = ListenerFailure("listener failure")
    guard = StrictGuard()

    class StrictFenceStore(_RecordingStore):
        def acquire_publication_guard(self) -> StrictGuard:
            return guard

        def try_acquire_reconciliation_guard(self) -> StrictGuard | None:
            return None

    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    store = StrictFenceStore("obj_00000000000000000000000000000028")
    monkeypatch.setattr(
        publication_tracker,
        "_install_session_listeners",
        lambda _session: (_ for _ in ()).throw(failure),
    )
    with Session(engine) as session:
        with pytest.raises(ListenerFailure) as caught:
            _publish(session, store)

        assert caught.value is failure
        assert guard.release_count == 1
        assert tracked_artifact_storage_keys(session) == ()
        session.rollback()
    engine.dispose()


def test_low_level_tracking_joins_empty_session_transaction() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    storage_key = "obj_00000000000000000000000000000010"
    store = _RecordingStore()
    with Session(engine) as session:
        track_artifact_publication(
            session,
            store=store,  # type: ignore[arg-type]
            storage_key=storage_key,
        )
        assert session.in_transaction()

        session.rollback()

        assert store.delete_calls == [storage_key]
        assert tracked_artifact_storage_keys(session) == ()
    engine.dispose()


def test_put_publication_uncertain_is_tracked_and_definitive_rollback_cleans_it() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    storage_key = "obj_00000000000000000000000000000003"
    store = _RecordingStore(storage_key, publication_uncertain=True)
    with Session(engine) as session:
        with pytest.raises(ArtifactStorePublicationUncertainError) as caught:
            _publish(session, store)
        assert caught.value is store.publication_error
        assert tracked_artifact_storage_keys(session) == (storage_key,)

        session.rollback()

        assert store.delete_calls == [storage_key]
        assert tracked_artifact_storage_keys(session) == ()
        assert uncertain_artifact_storage_keys(session) == ()
    engine.dispose()


def test_connection_acquisition_failure_happens_before_store_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    store = _RecordingStore("obj_00000000000000000000000000000009")

    def fail_connection_acquisition() -> object:
        raise OSError("connection unavailable")

    monkeypatch.setattr(engine, "connect", fail_connection_acquisition)
    with Session(engine) as session:
        with pytest.raises(OSError, match="connection unavailable"):
            _publish(session, store)

        assert store.put_calls == []
        assert tracked_artifact_storage_keys(session) == ()
        session.rollback()
    engine.dispose()


def test_commit_uncertain_moves_publication_out_of_active_before_future_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    _commit_then_lose_acknowledgement(monkeypatch, engine)
    storage_key = "obj_00000000000000000000000000000004"
    store = _RecordingStore(storage_key)
    with Session(engine) as session:
        _publish(session, store)
        with pytest.raises(OSError, match="commit acknowledgement lost"):
            session.commit()

        session.rollback()

        assert tracked_artifact_storage_keys(session) == ()
        assert uncertain_artifact_storage_keys(session) == (storage_key,)
        assert store.delete_calls == []
        _assert_no_transient_listener_state(session)

        session.execute(sa.text("SELECT 1"))
        session.rollback()
        assert store.delete_calls == []
        assert uncertain_artifact_storage_keys(session) == (storage_key,)
        _assert_no_transient_listener_state(session)
    engine.dispose()


def test_multiple_commit_uncertain_publications_accumulate_without_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    _commit_then_lose_acknowledgement(monkeypatch, engine)
    first_key = "obj_00000000000000000000000000000005"
    second_key = "obj_00000000000000000000000000000006"
    store = _RecordingStore(first_key, second_key, first_key)
    with Session(engine) as session:
        for _ in range(3):
            _publish(session, store)
            with pytest.raises(OSError, match="commit acknowledgement lost"):
                session.commit()
            session.rollback()

        assert tracked_artifact_storage_keys(session) == ()
        assert uncertain_artifact_storage_keys(session) == (first_key, second_key)
        assert store.delete_calls == []
    engine.dispose()


def test_flush_integrity_error_is_definitive_rollback_and_cleans_publication() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    _Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(sa.insert(_UniquePublicationRow).values(id=1))
    storage_key = "obj_00000000000000000000000000000007"
    store = _RecordingStore(storage_key)
    with Session(engine) as session:
        _publish(session, store)
        session.add(_UniquePublicationRow(id=1))

        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        assert store.delete_calls == [storage_key]
        assert tracked_artifact_storage_keys(session) == ()
        assert uncertain_artifact_storage_keys(session) == ()
        _assert_no_transient_listener_state(session)

        session.execute(sa.text("SELECT 1"))
        session.commit()
        _assert_no_transient_listener_state(session)
    engine.dispose()


def test_default_cleanup_error_is_platform_neutral_and_opaque() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    storage_key = "obj_00000000000000000000000000000008"
    store = _RecordingStore(storage_key, delete_fails=True)
    with Session(engine) as session:
        _publish(session, store)

        with pytest.raises(ArtifactPublicationCleanupUncertainError) as caught:
            session.rollback()

        assert caught.value.error_code == "media_artifact.publication_cleanup_uncertain"
        assert isinstance(caught.value, ArtifactStoreError)
        assert caught.value.storage_keys == (storage_key,)
        assert "/" not in str(caught.value)
        assert tracked_artifact_storage_keys(session) == ()
        assert uncertain_artifact_storage_keys(session) == (storage_key,)

        session.execute(sa.text("SELECT 1"))
        session.commit()
        assert tracked_artifact_storage_keys(session) == ()
        assert uncertain_artifact_storage_keys(session) == (storage_key,)
        assert store.delete_calls == [storage_key]
    engine.dispose()


def test_rollback_quarantines_only_delete_failures() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    deleted_key = "obj_00000000000000000000000000000012"
    failed_key = "obj_00000000000000000000000000000013"

    class SelectiveDeleteStore(_RecordingStore):
        def delete(self, storage_key: str) -> None:
            self.delete_calls.append(storage_key)
            if storage_key == failed_key:
                raise ArtifactStoreError("injected selective delete failure")

    store = SelectiveDeleteStore(deleted_key, failed_key)
    with Session(engine) as session:
        _publish(session, store)
        _publish(session, store)

        with pytest.raises(ArtifactPublicationCleanupUncertainError) as caught:
            session.rollback()

        assert caught.value.storage_keys == (failed_key,)
        assert store.delete_calls == [deleted_key, failed_key]
        assert tracked_artifact_storage_keys(session) == ()
        assert uncertain_artifact_storage_keys(session) == (failed_key,)
    engine.dispose()


def test_rollback_same_key_across_stores_quarantines_only_failed_identity() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    shared_key = "obj_00000000000000000000000000000014"
    successful_store = _RecordingStore(shared_key)
    failed_store = _RecordingStore(shared_key, delete_fails=True)
    with Session(engine) as session:
        _publish(session, successful_store)
        _publish(session, failed_store)

        with pytest.raises(ArtifactPublicationCleanupUncertainError) as caught:
            session.rollback()

        assert caught.value.storage_keys == (shared_key,)
        assert successful_store.delete_calls == [shared_key]
        assert failed_store.delete_calls == [shared_key]
        assert tracked_artifact_storage_keys(session) == ()
        assert uncertain_artifact_storage_keys(session) == (shared_key,)
        quarantined = publication_tracker._quarantined_publications(session)
        assert len(quarantined) == 1
        assert quarantined[0].store is failed_store
    engine.dispose()


def test_active_artifact_producers_use_unified_publication_helper() -> None:
    producer_paths = (
        ROOT / "app/domain/runtime/artifact_coordination.py",
        ROOT / "app/domain/media_derivatives/artifacts.py",
        ROOT / "app/domain/audio_generation/artifacts.py",
        ROOT / "app/domain/image_generation/materialization.py",
    )
    for path in producer_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        direct_put_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "put"
        ]
        assert "publish_and_track_artifact" in called_names, path
        assert direct_put_calls == [], path


def test_nested_publication_producer_keeps_explicit_cleanup_contract() -> None:
    producer_paths = (
        ROOT / "app/domain/runtime/artifact_coordination.py",
        ROOT / "app/domain/media_derivatives/artifacts.py",
        ROOT / "app/domain/audio_generation/artifacts.py",
        ROOT / "app/domain/image_generation/materialization.py",
    )
    nested_producers: list[Path] = []
    for path in producer_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "begin_nested"
            for node in ast.walk(tree)
        ):
            nested_producers.append(path)

    image_path = ROOT / "app/domain/image_generation/materialization.py"
    assert nested_producers == [image_path]
    image_tree = ast.parse(image_path.read_text(encoding="utf-8"))
    called_names = {
        node.func.id
        for node in ast.walk(image_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert {"_cleanup_failed_batch", "quarantine_artifact_publications"} <= called_names
