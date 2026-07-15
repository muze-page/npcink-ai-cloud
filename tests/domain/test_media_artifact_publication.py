from __future__ import annotations

import ast
import io
from collections.abc import Mapping
from pathlib import Path
from typing import BinaryIO

import pytest
import sqlalchemy as sa
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
