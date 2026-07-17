from __future__ import annotations

import fcntl
import io
import multiprocessing
import os
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domain.media_artifacts import (
    ArtifactConditionalDeleteResult,
    ArtifactInventoryPage,
    ArtifactStoreError,
    ArtifactStorePublicationUncertainError,
    LocalVolumeArtifactStore,
)
from app.domain.media_artifacts import store as artifact_store_module
from app.domain.media_derivatives.artifacts import create_artifact


class BoundedReader(io.BytesIO):
    def __init__(self, value: bytes, limit: int) -> None:
        super().__init__(value)
        self.limit = limit

    def read(self, size: int = -1) -> bytes:
        assert 0 < size <= self.limit
        return super().read(size)


def _inventory_path(root: Path, storage_key: str) -> Path:
    return root / storage_key[4:6] / storage_key[6:8] / storage_key


def _write_inventory_object(
    root: Path,
    storage_key: str,
    payload: bytes,
    *,
    modified_at: datetime | None = None,
) -> Path:
    initializer = LocalVolumeArtifactStore(root)
    publication_session = initializer.open_publication_session()
    publication_session.release()
    path = _inventory_path(root, storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    if modified_at is not None:
        timestamp = modified_at.timestamp()
        os.utime(path, (timestamp, timestamp))
    return path


def _try_exclusive_artifact_fence(root: str, result_queue: object) -> None:
    store = LocalVolumeArtifactStore(root)
    guard = store.try_acquire_reconciliation_guard()
    result_queue.put(guard is not None)  # type: ignore[attr-defined]
    if guard is not None:
        guard.release()


def _acquire_shared_artifact_fence(root: str, result_queue: object) -> None:
    guard = LocalVolumeArtifactStore(root).acquire_publication_guard()
    result_queue.put(True)  # type: ignore[attr-defined]
    guard.release()


def _hold_bootstrap_lock(root: str, result_queue: object) -> None:
    store = LocalVolumeArtifactStore(root)
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    root_descriptor = os.open(root_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    descriptor = store._open_bootstrap_lock(  # type: ignore[attr-defined]
        root_descriptor,
        expected_device=int(os.fstat(root_descriptor).st_dev),
    )
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    result_queue.put(True)  # type: ignore[attr-defined]
    threading.Event().wait(60)


def test_put_is_bounded_atomic_private_and_reports_metadata(tmp_path: Path) -> None:
    store = LocalVolumeArtifactStore(tmp_path / "artifacts", chunk_size=4096)
    payload = b"a" * 9000
    result = store.put(BoundedReader(payload, 4096), max_bytes=len(payload))

    assert result.byte_size == len(payload)
    assert result.checksum.startswith("sha256:")
    with store.open(result.storage_key) as stored:
        assert stored.read(4096) == payload[:4096]
        mode = stat.S_IMODE(Path(stored.name).stat().st_mode)
    assert mode == 0o600
    assert not list((tmp_path / "artifacts").rglob("*.tmp"))


def test_put_fsyncs_parent_directory_after_atomic_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalVolumeArtifactStore(tmp_path / "artifacts")
    original = store._fsync_publication_directory
    calls: list[int] = []

    def record(descriptor: int) -> None:
        calls.append(descriptor)
        original(descriptor)

    monkeypatch.setattr(store, "_fsync_publication_directory", record)
    result = store.put(io.BytesIO(b"payload"), max_bytes=7)
    assert store.contains(result.storage_key) is True
    assert len(calls) == 1


def test_parent_fsync_failure_rolls_back_published_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalVolumeArtifactStore(tmp_path / "artifacts")
    original = store._fsync_publication_directory
    attempts = 0

    def fail_once(descriptor: int) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("directory fsync failed")
        original(descriptor)

    monkeypatch.setattr(store, "_fsync_publication_directory", fail_once)
    with pytest.raises(ArtifactStoreError, match="rolled back"):
        store.put(io.BytesIO(b"payload"), max_bytes=7)
    assert attempts == 2
    assert not [path for path in (tmp_path / "artifacts").rglob("obj_*") if path.is_file()]
    assert not list((tmp_path / "artifacts").rglob("*.tmp"))


def test_parent_fsync_and_rollback_fsync_failure_reports_uncertain_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalVolumeArtifactStore(tmp_path / "artifacts")

    def fail(descriptor: int) -> None:
        raise OSError(f"cannot fsync descriptor {descriptor}")

    monkeypatch.setattr(store, "_fsync_publication_directory", fail)
    with pytest.raises(ArtifactStorePublicationUncertainError) as caught:
        store.put(io.BytesIO(b"payload"), max_bytes=7)
    assert caught.value.storage_metadata.byte_size == 7
    assert caught.value.storage_metadata.storage_key.startswith("obj_")
    assert not list((tmp_path / "artifacts").rglob("*.tmp"))


def test_root_replacement_during_put_rolls_back_on_pinned_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "configured-artifacts"
    pinned_root = tmp_path / "pinned-artifacts"
    store = LocalVolumeArtifactStore(root)
    original = store._fsync_publication_directory
    replaced = False

    def replace_after_publication(descriptor: int) -> None:
        nonlocal replaced
        original(descriptor)
        if not replaced:
            replaced = True
            root.rename(pinned_root)
            replacement = LocalVolumeArtifactStore(root).open_publication_session()
            replacement.release()

    monkeypatch.setattr(
        store,
        "_fsync_publication_directory",
        replace_after_publication,
    )

    with pytest.raises(ArtifactStoreError, match="rolled back"):
        store.put(io.BytesIO(b"payload"), max_bytes=7)

    assert replaced is True
    assert not [path for path in pinned_root.rglob("obj_*") if path.is_file()]
    assert not [path for path in root.rglob("obj_*") if path.is_file()]


def test_put_rejects_over_budget_and_removes_temp(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    store = LocalVolumeArtifactStore(root, chunk_size=4096)
    with pytest.raises(ArtifactStoreError, match="size limit"):
        store.put(BoundedReader(b"a" * 5000, 4096), max_bytes=4999)
    assert not list(root.rglob("*tmp"))
    assert not [path for path in root.rglob("obj_*") if path.is_file()]


@pytest.mark.parametrize("max_bytes", [0, -1])
def test_put_rejects_non_positive_budget_before_writing(tmp_path: Path, max_bytes: int) -> None:
    root = tmp_path / "artifacts"
    store = LocalVolumeArtifactStore(root)
    with pytest.raises(ArtifactStoreError, match="must be positive"):
        store.put(io.BytesIO(b"payload"), max_bytes=max_bytes)
    assert not root.exists()


def test_root_and_storage_key_validation_prevent_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        LocalVolumeArtifactStore("relative/artifacts")
    store = LocalVolumeArtifactStore(tmp_path / "artifacts")
    with pytest.raises(ArtifactStoreError, match="invalid"):
        store.open("../../etc/passwd")


def test_delete_is_idempotent_and_metadata_never_exposes_path(tmp_path: Path) -> None:
    store = LocalVolumeArtifactStore(tmp_path / "artifacts")
    result = store.put(io.BytesIO(b"payload"), max_bytes=7)
    assert store.metadata(result.storage_key) == result
    assert str(tmp_path) not in repr(store.metadata(result.storage_key))
    store.delete(result.storage_key)
    store.delete(result.storage_key)


def test_metadata_normalizes_stream_read_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingReader(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            raise OSError("volume read failed")

    store = LocalVolumeArtifactStore(tmp_path / "artifacts")
    monkeypatch.setattr(store, "open", lambda storage_key: FailingReader(b"payload"))

    with pytest.raises(ArtifactStoreError, match="metadata read failed"):
        store.metadata("obj_" + ("a" * 32))


def test_inventory_is_strict_bounded_stable_and_read_only(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    store = LocalVolumeArtifactStore(root)
    observed_at = datetime(2026, 7, 15, 10, 30, tzinfo=UTC)
    storage_keys = tuple(f"obj_{index:032x}" for index in (3, 1, 4, 2))
    for index, storage_key in enumerate(storage_keys):
        _write_inventory_object(
            root,
            storage_key,
            b"x" * (index + 1),
            modified_at=observed_at,
        )

    first = store.list_objects(limit=2)
    second = store.list_objects(cursor=first.next_cursor, limit=2)

    assert isinstance(first, ArtifactInventoryPage)
    assert tuple(item.storage_key for item in first.items) == tuple(sorted(storage_keys)[:2])
    assert tuple(item.storage_key for item in second.items) == tuple(sorted(storage_keys)[2:])
    assert first.next_cursor == first.items[-1].storage_key
    assert second.next_cursor is None
    assert all(item.last_modified_at == observed_at for item in first.items + second.items)
    assert {
        item.storage_key: item.byte_size for item in first.items + second.items
    } == {
        storage_key: len(_inventory_path(root, storage_key).read_bytes())
        for storage_key in storage_keys
    }


def test_object_version_rejects_inode_swap_with_same_size_and_mtime(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    store = LocalVolumeArtifactStore(root)
    stored = store.put(io.BytesIO(b"payload"), max_bytes=7)
    before = store.list_objects().items[0]
    path = _inventory_path(root, stored.storage_key)
    original_stat = path.stat()
    replacement = path.with_name("replacement.tmp")
    replacement.write_bytes(b"payload")
    os.chmod(replacement, 0o600)
    os.utime(
        replacement,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )
    os.replace(replacement, path)

    after = store.list_objects().items[0]
    assert after.byte_size == before.byte_size
    assert after.last_modified_at == before.last_modified_at
    assert after.object_version != before.object_version
    reconciliation = store.try_open_reconciliation_session()
    assert reconciliation is not None
    try:
        result = reconciliation.delete_if_unchanged(
            stored.storage_key,
            before.object_version,
        )
    finally:
        reconciliation.release()
    assert result == ArtifactConditionalDeleteResult.OBJECT_CHANGED
    assert store.contains(stored.storage_key) is True


def test_object_version_ignores_sibling_churn_but_binds_shard_inode(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    store = LocalVolumeArtifactStore(root)
    stored = store.put(io.BytesIO(b"payload"), max_bytes=7)
    before = store.list_objects().items[0].object_version
    sibling_key = f"obj_{stored.storage_key[4:8]}{'f' * 28}"
    if sibling_key == stored.storage_key:
        sibling_key = f"obj_{stored.storage_key[4:8]}{'e' * 28}"
    sibling = _inventory_path(root, sibling_key)
    sibling.write_bytes(b"sibling")
    os.chmod(sibling, 0o600)
    after_sibling = next(
        item
        for item in store.list_objects().items
        if item.storage_key == stored.storage_key
    )
    assert after_sibling.object_version == before

    leaf = _inventory_path(root, stored.storage_key).parent
    old_leaf = leaf.with_name(f"{leaf.name}-old")
    leaf.rename(old_leaf)
    leaf.mkdir(mode=0o700)
    os.replace(old_leaf / stored.storage_key, leaf / stored.storage_key)
    after_shard_replace = next(
        item
        for item in store.list_objects().items
        if item.storage_key == stored.storage_key
    )
    assert after_shard_replace.object_version != before


def test_store_generation_is_persistent_and_changes_with_root_identity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    old_root = tmp_path / "old-artifacts"
    store = LocalVolumeArtifactStore(root)
    store.put(io.BytesIO(b"first"), max_bytes=5)
    first_generation = store.list_objects().store_generation
    assert first_generation.startswith("gen_")
    assert LocalVolumeArtifactStore(root).list_objects().store_generation == first_generation

    root.rename(old_root)
    replacement = LocalVolumeArtifactStore(root)
    replacement.put(io.BytesIO(b"second"), max_bytes=6)
    assert replacement.list_objects().store_generation != first_generation


def test_existing_empty_root_inventory_is_stable_and_read_only(tmp_path: Path) -> None:
    root = tmp_path / "empty-artifacts"
    root.mkdir()
    store = LocalVolumeArtifactStore(root)

    assert store.list_objects() == ArtifactInventoryPage(items=(), next_cursor=None)
    assert store.list_objects() == ArtifactInventoryPage(items=(), next_cursor=None)
    assert list(root.iterdir()) == []


def test_markerless_root_with_storage_shard_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "markerless-shard"
    (root / "aa").mkdir(parents=True)
    store = LocalVolumeArtifactStore(root)

    with pytest.raises(ArtifactStoreError, match="generation is unavailable"):
        store.list_objects()
    with pytest.raises(ArtifactStoreError, match="generation is unavailable"):
        store.open_publication_session()
    assert (root / ".artifact-store-generation").exists() is False


@pytest.mark.parametrize("workers", [8, 16])
def test_concurrent_first_publication_sessions_observe_one_complete_generation(
    tmp_path: Path,
    workers: int,
) -> None:
    for attempt in range(20):
        root = tmp_path / f"concurrent-bootstrap-{workers}-{attempt}"
        root.mkdir()
        start = threading.Barrier(workers)

        def open_first(
            *,
            barrier: threading.Barrier = start,
            artifact_root: Path = root,
        ) -> str:
            barrier.wait(timeout=10)
            session = LocalVolumeArtifactStore(artifact_root).open_publication_session()
            try:
                return session.store_generation
            finally:
                session.release()

        with ThreadPoolExecutor(max_workers=workers) as executor:
            generations = tuple(
                executor.map(lambda _index: open_first(), range(workers))
            )

        assert len(set(generations)) == 1
        assert generations[0].startswith("gen_")
        marker = root / ".artifact-store-generation"
        assert marker.read_text(encoding="ascii").strip() == generations[0]
        assert stat.S_IMODE(marker.stat().st_mode) == 0o600
        assert marker.stat().st_nlink == 1


def test_existing_unsafe_publication_lock_fails_closed_without_repair(
    tmp_path: Path,
) -> None:
    root = tmp_path / "unsafe-publication-lock"
    root.mkdir()
    lock_path = root / ".artifact-publication.lock"
    lock_path.write_bytes(b"")
    os.chmod(lock_path, 0o666)

    with pytest.raises(ArtifactStoreError, match="publication fence is unavailable"):
        LocalVolumeArtifactStore(root).open_publication_session()

    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o666
    assert (root / ".artifact-store-generation").exists() is False


def test_valid_marker_waiter_returns_while_initializer_publication_is_held(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bootstrap-short-lock"
    store = LocalVolumeArtifactStore(root)
    initializer = store.open_publication_session()
    bootstrap_path = root / ".artifact-store-bootstrap.lock"
    assert bootstrap_path.is_file()
    bootstrap_path.unlink()

    with ThreadPoolExecutor(max_workers=1) as executor:
        waiting = executor.submit(store.open_publication_session)
        joined = waiting.result(timeout=2)
        try:
            assert joined.store_generation == initializer.store_generation
            assert bootstrap_path.exists() is False
        finally:
            joined.release()
    initializer.release()


def test_bootstrap_base_exception_releases_short_mutex_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FatalBootstrap(BaseException):
        pass

    root = tmp_path / "bootstrap-fatal"
    store = LocalVolumeArtifactStore(root)
    failure = FatalBootstrap("exact bootstrap crash")
    original = store._bootstrap_generation_marker
    monkeypatch.setattr(
        store,
        "_bootstrap_generation_marker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )

    with pytest.raises(FatalBootstrap) as caught:
        store.open_publication_session()
    assert caught.value is failure

    monkeypatch.setattr(store, "_bootstrap_generation_marker", original)
    retry = store.open_publication_session()
    retry.release()


def test_crashed_bootstrap_lock_holder_is_recoverable(tmp_path: Path) -> None:
    root = tmp_path / "bootstrap-process-crash"
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    holder = context.Process(
        target=_hold_bootstrap_lock,
        args=(str(root), ready),
    )
    holder.start()
    assert ready.get(timeout=10) is True
    holder.terminate()
    holder.join(timeout=10)
    assert holder.is_alive() is False

    recovered = LocalVolumeArtifactStore(root).open_publication_session()
    recovered.release()


@pytest.mark.parametrize("failure_kind", ["unsafe", "replaced"])
def test_unsafe_or_replaced_bootstrap_lock_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    root = tmp_path / f"bootstrap-lock-{failure_kind}"
    root.mkdir()
    bootstrap_path = root / ".artifact-store-bootstrap.lock"
    bootstrap_path.write_bytes(b"")
    os.chmod(bootstrap_path, 0o600 if failure_kind == "replaced" else 0o666)
    store = LocalVolumeArtifactStore(root)
    if failure_kind == "replaced":
        original = store._open_bootstrap_lock

        def open_then_replace(*args: object, **kwargs: object) -> int:
            descriptor = original(*args, **kwargs)  # type: ignore[arg-type]
            bootstrap_path.rename(bootstrap_path.with_suffix(".old"))
            bootstrap_path.write_bytes(b"")
            os.chmod(bootstrap_path, 0o600)
            return descriptor

        monkeypatch.setattr(store, "_open_bootstrap_lock", open_then_replace)

    with pytest.raises(ArtifactStoreError, match="bootstrap lock is unavailable"):
        store.open_publication_session()
    assert (root / ".artifact-store-generation").exists() is False


@pytest.mark.parametrize("failure_kind", ["write", "temp_fsync", "root_fsync"])
def test_marker_bootstrap_failure_is_retryable_without_partial_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    root = tmp_path / f"bootstrap-{failure_kind}"
    store = LocalVolumeArtifactStore(root)
    original_write = artifact_store_module._write_all
    original_fsync = store._fsync_descriptor
    failed = False
    fsync_calls = 0

    def fail_write(descriptor: int, payload: bytes) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("injected marker write failure")
        original_write(descriptor, payload)

    def fail_fsync(descriptor: int) -> None:
        nonlocal failed, fsync_calls
        fsync_calls += 1
        target_call = 1 if failure_kind == "temp_fsync" else 2
        if not failed and fsync_calls == target_call:
            failed = True
            raise OSError("injected marker fsync failure")
        original_fsync(descriptor)

    if failure_kind == "write":
        monkeypatch.setattr(artifact_store_module, "_write_all", fail_write)
    else:
        monkeypatch.setattr(store, "_fsync_descriptor", fail_fsync)

    with pytest.raises(ArtifactStoreError, match="generation is unavailable"):
        store.open_publication_session()
    assert (root / ".artifact-store-generation").exists() is False

    monkeypatch.setattr(artifact_store_module, "_write_all", original_write)
    monkeypatch.setattr(store, "_fsync_descriptor", original_fsync)
    retry = store.open_publication_session()
    generation = retry.store_generation
    retry.release()
    assert generation.startswith("gen_")
    assert (root / ".artifact-store-generation").read_text().strip() == generation


def test_empty_root_repairs_private_bad_marker_but_sharded_root_refuses(
    tmp_path: Path,
) -> None:
    empty_root = tmp_path / "bad-empty-marker"
    empty_root.mkdir()
    empty_marker = empty_root / ".artifact-store-generation"
    empty_marker.write_text("incomplete", encoding="ascii")
    os.chmod(empty_marker, 0o600)

    repaired = LocalVolumeArtifactStore(empty_root).open_publication_session()
    repaired_generation = repaired.store_generation
    repaired.release()
    assert repaired_generation.startswith("gen_")
    assert empty_marker.read_text().strip() == repaired_generation

    sharded_root = tmp_path / "bad-sharded-marker"
    (sharded_root / "aa").mkdir(parents=True)
    sharded_marker = sharded_root / ".artifact-store-generation"
    sharded_marker.write_text("incomplete", encoding="ascii")
    os.chmod(sharded_marker, 0o600)
    with pytest.raises(ArtifactStoreError, match="generation is unavailable"):
        LocalVolumeArtifactStore(sharded_root).open_publication_session()
    assert sharded_marker.read_text() == "incomplete"


def test_destructive_session_never_creates_missing_root_or_marker(tmp_path: Path) -> None:
    root = tmp_path / "missing-artifacts"
    store = LocalVolumeArtifactStore(root)
    with pytest.raises(ArtifactStoreError, match="session is unavailable"):
        store.try_open_reconciliation_session()
    assert root.exists() is False

    root.mkdir()
    with pytest.raises(ArtifactStoreError, match="session is unavailable"):
        store.try_open_reconciliation_session()
    assert list(root.iterdir()) == []


def test_missing_retry_fsyncs_deepest_leaf_after_unlink_fsync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts"
    store = LocalVolumeArtifactStore(root)
    stored = store.put(io.BytesIO(b"payload"), max_bytes=7)
    token = store.list_objects().items[0].object_version
    original = store._fsync_descriptor
    fail_once = True

    def crash_after_unlink(descriptor: int) -> None:
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise OSError("injected leaf fsync crash")
        original(descriptor)

    monkeypatch.setattr(store, "_fsync_descriptor", crash_after_unlink)
    first = store.try_open_reconciliation_session()
    assert first is not None
    try:
        assert (
            first.delete_if_unchanged(stored.storage_key, token)
            == ArtifactConditionalDeleteResult.UNSAFE_LAYOUT
        )
    finally:
        first.release()
    assert store.contains(stored.storage_key) is False

    fsync_calls = 0

    def record_fsync(descriptor: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        original(descriptor)

    monkeypatch.setattr(store, "_fsync_descriptor", record_fsync)
    retry = store.try_open_reconciliation_session()
    assert retry is not None
    try:
        assert (
            retry.delete_if_unchanged(stored.storage_key, token)
            == ArtifactConditionalDeleteResult.ALREADY_ABSENT_DURABLE
        )
    finally:
        retry.release()
    assert fsync_calls == 1


@pytest.mark.parametrize("unsafe_directory", ["first", "leaf"])
def test_missing_retry_validates_every_pinned_directory_permission(
    tmp_path: Path,
    unsafe_directory: str,
) -> None:
    root = tmp_path / f"missing-unsafe-{unsafe_directory}"
    store = LocalVolumeArtifactStore(root)
    stored = store.put(io.BytesIO(b"payload"), max_bytes=7)
    token = store.list_objects().items[0].object_version
    path = _inventory_path(root, stored.storage_key)
    path.unlink()
    first = path.parents[1]
    leaf = path.parent
    os.chmod(first if unsafe_directory == "first" else leaf, 0o777)

    reconciliation = store.try_open_reconciliation_session()
    assert reconciliation is not None
    try:
        result = reconciliation.delete_if_unchanged(stored.storage_key, token)
    finally:
        reconciliation.release()

    assert result == ArtifactConditionalDeleteResult.UNSAFE_LAYOUT


@pytest.mark.parametrize("replacement", ["first", "leaf"])
def test_missing_retry_detects_directory_replacement_during_fsync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    root = tmp_path / f"missing-replacement-{replacement}"
    store = LocalVolumeArtifactStore(root)
    stored = store.put(io.BytesIO(b"payload"), max_bytes=7)
    token = store.list_objects().items[0].object_version
    path = _inventory_path(root, stored.storage_key)
    path.unlink()
    first = path.parents[1]
    leaf = path.parent
    original_fsync = store._fsync_descriptor
    replaced = False

    def replace_during_fsync(descriptor: int) -> None:
        nonlocal replaced
        if not replaced:
            replaced = True
            if replacement == "first":
                first.rename(first.with_name(f"{first.name}-old"))
                first.mkdir(mode=0o700)
            else:
                leaf.rename(leaf.with_name(f"{leaf.name}-old"))
                leaf.mkdir(mode=0o700)
        original_fsync(descriptor)

    reconciliation = store.try_open_reconciliation_session()
    assert reconciliation is not None
    monkeypatch.setattr(store, "_fsync_descriptor", replace_during_fsync)
    try:
        result = reconciliation.delete_if_unchanged(stored.storage_key, token)
    finally:
        reconciliation.release()

    assert replaced is True
    assert result == ArtifactConditionalDeleteResult.UNSAFE_LAYOUT


@pytest.mark.parametrize("replacement", ["first", "leaf", "nonregular"])
def test_conditional_delete_fails_closed_on_layout_inode_replacement(
    tmp_path: Path,
    replacement: str,
) -> None:
    root = tmp_path / "artifacts"
    store = LocalVolumeArtifactStore(root)
    stored = store.put(io.BytesIO(b"payload"), max_bytes=7)
    token = store.list_objects().items[0].object_version
    path = _inventory_path(root, stored.storage_key)
    first = path.parents[1]
    leaf = path.parent
    reconciliation = store.try_open_reconciliation_session()
    assert reconciliation is not None
    if replacement == "first":
        old_first = first.with_name(f"{first.name}-old")
        first.rename(old_first)
        first.mkdir(mode=0o700)
        leaf.mkdir(mode=0o700)
        os.replace(
            old_first / leaf.name / stored.storage_key,
            path,
        )
        expected = ArtifactConditionalDeleteResult.OBJECT_CHANGED
    elif replacement == "leaf":
        old_leaf = leaf.with_name(f"{leaf.name}-old")
        leaf.rename(old_leaf)
        leaf.mkdir(mode=0o700)
        os.replace(old_leaf / stored.storage_key, path)
        expected = ArtifactConditionalDeleteResult.OBJECT_CHANGED
    else:
        path.unlink()
        path.mkdir()
        expected = ArtifactConditionalDeleteResult.UNSAFE_LAYOUT
    try:
        assert reconciliation.delete_if_unchanged(stored.storage_key, token) == expected
    finally:
        reconciliation.release()
        reconciliation.release()
    assert path.exists()
    following = store.try_open_reconciliation_session()
    assert following is not None
    following.release()


@pytest.mark.parametrize("replacement", ["root", "lock", "marker"])
def test_reconciliation_session_detects_root_lock_or_marker_replacement(
    tmp_path: Path,
    replacement: str,
) -> None:
    root = tmp_path / "artifacts"
    store = LocalVolumeArtifactStore(root)
    stored = store.put(io.BytesIO(b"payload"), max_bytes=7)
    token = store.list_objects().items[0].object_version
    reconciliation = store.try_open_reconciliation_session()
    assert reconciliation is not None
    if replacement == "root":
        old_root = tmp_path / "old-artifacts"
        root.rename(old_root)
        replacement_session = LocalVolumeArtifactStore(root).open_publication_session()
        replacement_session.release()
        pinned_path = _inventory_path(old_root, stored.storage_key)
    elif replacement == "lock":
        lock = root / ".artifact-publication.lock"
        lock.rename(root / ".artifact-publication.lock.old")
        lock.write_bytes(b"")
        os.chmod(lock, 0o600)
        pinned_path = _inventory_path(root, stored.storage_key)
    else:
        marker = root / ".artifact-store-generation"
        marker.rename(root / ".artifact-store-generation.old")
        marker.write_text(f"gen_{'f' * 32}\n", encoding="ascii")
        os.chmod(marker, 0o600)
        pinned_path = _inventory_path(root, stored.storage_key)
    try:
        with pytest.raises(ArtifactStoreError, match="validation failed"):
            reconciliation.delete_if_unchanged(stored.storage_key, token)
    finally:
        reconciliation.release()
        reconciliation.release()
    assert pinned_path.is_file()


def test_inventory_excludes_untrusted_layout_entries(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    store = LocalVolumeArtifactStore(root)
    valid_key = "obj_00000000000000000000000000000001"
    wrong_shard_key = "obj_11000000000000000000000000000002"
    symlink_key = "obj_00000000000000000000000000000003"
    hardlink_key = "obj_00000000000000000000000000000004"
    directory_symlink_key = "obj_aa000000000000000000000000000005"
    leaf_symlink_key = "obj_bbcc0000000000000000000000000006"

    _write_inventory_object(root, valid_key, b"valid")
    (root / "00" / "00" / wrong_shard_key).write_bytes(b"wrong shard")
    external = tmp_path / "external"
    external.mkdir()
    external_file = external / "payload"
    external_file.write_bytes(b"external")
    symlink_path = _inventory_path(root, symlink_key)
    symlink_path.symlink_to(external_file)
    hardlink_path = _inventory_path(root, hardlink_key)
    os.link(external_file, hardlink_path)

    outside_first = tmp_path / "outside-first"
    _write_inventory_object(outside_first, directory_symlink_key, b"outside")
    (root / "aa").symlink_to(outside_first / "aa", target_is_directory=True)
    outside_leaf = tmp_path / "outside-leaf"
    _write_inventory_object(outside_leaf, leaf_symlink_key, b"outside")
    (root / "bb").mkdir()
    (root / "bb" / "cc").symlink_to(
        outside_leaf / "bb" / "cc",
        target_is_directory=True,
    )
    (root / "00" / "00" / f".{valid_key}.tmp").write_bytes(b"temporary")
    (root / "00" / "00" / "obj_malformed").write_bytes(b"malformed")

    page = store.list_objects(limit=100)

    assert tuple(item.storage_key for item in page.items) == (valid_key,)
    assert store.contains(valid_key) is True
    assert store.contains(symlink_key) is False
    assert store.contains(hardlink_key) is False
    assert store.contains(directory_symlink_key) is False
    assert store.contains(leaf_symlink_key) is False


@pytest.mark.parametrize("replacement_kind", ["symlink", "hardlink"])
def test_conditional_delete_returns_unsafe_for_link_replacement(
    tmp_path: Path,
    replacement_kind: str,
) -> None:
    root = tmp_path / "artifacts"
    store = LocalVolumeArtifactStore(root)
    stored = store.put(io.BytesIO(b"payload"), max_bytes=7)
    token = store.list_objects().items[0].object_version
    path = _inventory_path(root, stored.storage_key)
    external = tmp_path / "external"
    external.write_bytes(b"payload")
    path.unlink()
    if replacement_kind == "symlink":
        path.symlink_to(external)
    else:
        os.link(external, path)

    reconciliation = store.try_open_reconciliation_session()
    assert reconciliation is not None
    try:
        result = reconciliation.delete_if_unchanged(stored.storage_key, token)
    finally:
        reconciliation.release()

    assert result == ArtifactConditionalDeleteResult.UNSAFE_LAYOUT
    assert external.read_bytes() == b"payload"


def test_inventory_never_follows_a_shard_replaced_by_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts"
    store = LocalVolumeArtifactStore(root)
    publication_session = store.open_publication_session()
    publication_session.release()
    (root / "aa").mkdir()
    external_root = tmp_path / "outside"
    external_key = "obj_aabb" + ("0" * 28)
    _write_inventory_object(external_root, external_key, b"outside")
    original = store._strict_child_directory_names
    calls = 0

    def replace_after_listing(parent_descriptor: int) -> list[str]:
        nonlocal calls
        names = original(parent_descriptor)
        calls += 1
        if calls == 1:
            (root / "aa").rmdir()
            (root / "aa").symlink_to(
                external_root / "aa",
                target_is_directory=True,
            )
        return names

    monkeypatch.setattr(store, "_strict_child_directory_names", replace_after_listing)

    assert store.list_objects().items == ()
    assert store.contains(external_key) is False


def test_inventory_contains_pins_leaf_before_symlink_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts"
    (root / "aa" / "bb").mkdir(parents=True)
    external_root = tmp_path / "outside"
    external_key = "obj_aabb" + ("1" * 28)
    external_path = _write_inventory_object(external_root, external_key, b"outside")
    store = LocalVolumeArtifactStore(root)
    original = store._try_open_child_directory

    def replace_after_open(
        parent_descriptor: int,
        name: str,
        *,
        expected_device: int,
    ) -> int | None:
        descriptor = original(
            parent_descriptor,
            name,
            expected_device=expected_device,
        )
        if name == "bb" and descriptor is not None:
            (root / "aa" / "bb").rmdir()
            (root / "aa" / "bb").symlink_to(
                external_path.parent,
                target_is_directory=True,
            )
        return descriptor

    monkeypatch.setattr(store, "_try_open_child_directory", replace_after_open)

    assert store.contains(external_key) is False


def test_inventory_cursor_skips_earlier_shards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts"
    earlier_key = "obj_0000" + ("0" * 28)
    later_key = "obj_ffff" + ("f" * 28)
    _write_inventory_object(root, earlier_key, b"earlier")
    _write_inventory_object(root, later_key, b"later")
    store = LocalVolumeArtifactStore(root)
    original = store._smallest_inventory_entries
    scanned_first_shards: list[str] = []

    def record_scan(
        root_descriptor: int,
        first_descriptor: int,
        leaf_descriptor: int,
        *,
        first_shard: str,
        second_shard: str,
        store_generation: str,
        cursor: str | None,
        limit: int,
    ) -> list[tuple[str, os.stat_result, str]]:
        scanned_first_shards.append(first_shard)
        return original(
            root_descriptor,
            first_descriptor,
            leaf_descriptor,
            first_shard=first_shard,
            second_shard=second_shard,
            store_generation=store_generation,
            cursor=cursor,
            limit=limit,
        )

    monkeypatch.setattr(store, "_smallest_inventory_entries", record_scan)
    cursor = "obj_8080" + ("0" * 28)

    page = store.list_objects(cursor=cursor, limit=10)

    assert tuple(item.storage_key for item in page.items) == (later_key,)
    assert "00" not in scanned_first_shards


def test_inventory_missing_root_and_invalid_requests_are_stable_and_redacted(
    tmp_path: Path,
) -> None:
    store = LocalVolumeArtifactStore(tmp_path / "private-artifacts")
    assert store.list_objects() == ArtifactInventoryPage(items=(), next_cursor=None)
    assert store.contains("obj_" + ("a" * 32)) is False

    for request in (
        {"limit": 0},
        {"limit": 501},
        {"cursor": str(tmp_path / "private-object")},
    ):
        with pytest.raises(ArtifactStoreError) as caught:
            store.list_objects(**request)  # type: ignore[arg-type]
        assert str(caught.value) == "artifact inventory request is invalid"
        assert str(tmp_path) not in str(caught.value)


def test_publication_fence_is_private_cross_process_and_not_inventory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    store = LocalVolumeArtifactStore(root)
    shared_guard = store.acquire_publication_guard()
    lock_path = root / ".artifact-publication.lock"
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600
    assert store.list_objects().items == ()

    context = multiprocessing.get_context("spawn")
    shared_queue = context.Queue()
    shared = context.Process(
        target=_acquire_shared_artifact_fence,
        args=(str(root), shared_queue),
    )
    shared.start()
    try:
        assert shared_queue.get(timeout=10) is True
    finally:
        shared_guard.release()
        shared.join(timeout=10)
        if shared.is_alive():
            shared.terminate()
            shared.join(timeout=10)
    assert shared.exitcode == 0

    shared_guard = store.acquire_publication_guard()
    blocked_queue = context.Queue()
    blocked = context.Process(
        target=_try_exclusive_artifact_fence,
        args=(str(root), blocked_queue),
    )
    blocked.start()
    try:
        assert blocked_queue.get(timeout=10) is False
    finally:
        blocked.join(timeout=10)
        if blocked.is_alive():
            blocked.terminate()
            blocked.join(timeout=10)
    assert blocked.exitcode == 0

    shared_guard.release()
    acquired_queue = context.Queue()
    acquired = context.Process(
        target=_try_exclusive_artifact_fence,
        args=(str(root), acquired_queue),
    )
    acquired.start()
    assert acquired_queue.get(timeout=10) is True
    acquired.join(timeout=10)
    assert acquired.exitcode == 0


def test_reconciliation_refuses_group_or_world_writable_root(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    store = LocalVolumeArtifactStore(root)
    stored = store.put(io.BytesIO(b"payload"), max_bytes=7)
    os.chmod(root, 0o777)

    with pytest.raises(ArtifactStoreError, match="permissions are unsafe"):
        store.try_open_reconciliation_session()

    assert store.contains(stored.storage_key) is True


def test_reconciliation_refuses_group_or_world_writable_shard(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    store = LocalVolumeArtifactStore(root)
    stored = store.put(io.BytesIO(b"payload"), max_bytes=7)
    inventory = store.list_objects()
    item = inventory.items[0]
    os.chmod(root / stored.storage_key[4:6], 0o777)
    reconciliation = store.try_open_reconciliation_session()
    assert reconciliation is not None
    try:
        result = reconciliation.delete_if_unchanged(
            stored.storage_key,
            item.object_version,
        )
    finally:
        reconciliation.release()

    assert result == ArtifactConditionalDeleteResult.UNSAFE_LAYOUT
    assert store.contains(stored.storage_key) is True


def test_reconciliation_refuses_group_or_world_writable_file(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    store = LocalVolumeArtifactStore(root)
    stored = store.put(io.BytesIO(b"payload"), max_bytes=7)
    token = store.list_objects().items[0].object_version
    os.chmod(_inventory_path(root, stored.storage_key), 0o666)
    reconciliation = store.try_open_reconciliation_session()
    assert reconciliation is not None
    try:
        result = reconciliation.delete_if_unchanged(stored.storage_key, token)
    finally:
        reconciliation.release()
    assert result == ArtifactConditionalDeleteResult.UNSAFE_LAYOUT
    assert store.contains(stored.storage_key) is True


def test_example_environment_keys_match_settings_contract() -> None:
    example = (Path(__file__).resolve().parents[2] / ".env.example").read_text()
    assert "NPCINK_CLOUD_ARTIFACT_STORE_ROOT=" in example
    assert "NPCINK_CLOUD_ARTIFACT_STORE_CHUNK_BYTES=" in example
    assert "NPCINK_CLOUD_ARTIFACT_RECONCILIATION_INTERVAL_SECONDS=3600" in example
    assert "NPCINK_CLOUD_ARTIFACT_RECONCILIATION_SAFETY_WINDOW_SECONDS=86400" in example
    assert "NPCINK_CLOUD_ARTIFACT_RECONCILIATION_PAGE_SIZE=200" in example
    assert "NPCINK_CLOUD_ARTIFACT_RECONCILIATION_LEASE_SECONDS=300" in example
    assert "NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_ENABLED=false" in example
    assert "NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_BATCH_SIZE=25" in example
    assert "NPCINK_CLOUD_ARTIFACT_ORPHAN_CLAIM_LEASE_SECONDS=300" in example
    assert "NPCINK_CLOUD_ARTIFACT_ORPHAN_RETRY_BASE_SECONDS=30" in example
    assert "NPCINK_CLOUD_ARTIFACT_ORPHAN_RETRY_MAX_SECONDS=3600" in example
    fields = Settings.model_fields
    assert "artifact_store_root" in fields
    assert "artifact_store_chunk_bytes" in fields
    assert "artifact_reconciliation_interval_seconds" in fields
    assert "artifact_reconciliation_safety_window_seconds" in fields
    assert "artifact_reconciliation_page_size" in fields
    assert fields["artifact_orphan_cleanup_enabled"].default is False
    assert fields["artifact_orphan_cleanup_batch_size"].default == 25


def test_reconciliation_settings_are_bounded_and_prod_wiring_is_ops_only() -> None:
    settings_kwargs = {
        "environment": "test",
        "internal_auth_token": "i" * 32,
    }
    for override in (
        {"artifact_reconciliation_interval_seconds": 59},
        {"artifact_reconciliation_safety_window_seconds": 3599},
        {"artifact_reconciliation_page_size": 0},
        {"artifact_reconciliation_page_size": 501},
        {"artifact_reconciliation_lease_seconds": 299},
        {"artifact_reconciliation_lease_seconds": 3601},
        {"artifact_orphan_cleanup_batch_size": 101},
        {"artifact_orphan_claim_lease_seconds": 29},
        {"artifact_orphan_claim_lease_seconds": 3601},
        {"artifact_orphan_retry_base_seconds": 3601},
        {"artifact_orphan_retry_max_seconds": 86401},
        {
            "artifact_orphan_retry_base_seconds": 60,
            "artifact_orphan_retry_max_seconds": 30,
        },
    ):
        with pytest.raises(ValueError):
            Settings(**settings_kwargs, **override)

    compose = (
        Path(__file__).resolve().parents[2] / "docker-compose.prod.yml"
    ).read_text()
    for variable in (
        "NPCINK_CLOUD_ARTIFACT_RECONCILIATION_INTERVAL_SECONDS",
        "NPCINK_CLOUD_ARTIFACT_RECONCILIATION_SAFETY_WINDOW_SECONDS",
        "NPCINK_CLOUD_ARTIFACT_RECONCILIATION_PAGE_SIZE",
        "NPCINK_CLOUD_ARTIFACT_RECONCILIATION_LEASE_SECONDS",
        "NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_ENABLED",
        "NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_BATCH_SIZE",
        "NPCINK_CLOUD_ARTIFACT_ORPHAN_CLAIM_LEASE_SECONDS",
        "NPCINK_CLOUD_ARTIFACT_ORPHAN_RETRY_BASE_SECONDS",
        "NPCINK_CLOUD_ARTIFACT_ORPHAN_RETRY_MAX_SECONDS",
    ):
        assert compose.count(variable) == 2
    ops_worker = compose.split("  ops-worker:", maxsplit=1)[1]
    assert "NPCINK_CLOUD_ARTIFACT_RECONCILIATION_INTERVAL_SECONDS:" in ops_worker
    assert "NPCINK_CLOUD_ARTIFACT_RECONCILIATION_SAFETY_WINDOW_SECONDS:" in ops_worker
    assert "NPCINK_CLOUD_ARTIFACT_RECONCILIATION_PAGE_SIZE:" in ops_worker
    assert "NPCINK_CLOUD_ARTIFACT_RECONCILIATION_LEASE_SECONDS:" in ops_worker
    assert "NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_ENABLED:" in ops_worker
    assert "NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_BATCH_SIZE:" in ops_worker
    assert "NPCINK_CLOUD_ARTIFACT_ORPHAN_CLAIM_LEASE_SECONDS:" in ops_worker
    assert "NPCINK_CLOUD_ARTIFACT_ORPHAN_RETRY_BASE_SECONDS:" in ops_worker
    assert "NPCINK_CLOUD_ARTIFACT_ORPHAN_RETRY_MAX_SECONDS:" in ops_worker


def test_metadata_flush_failure_rollback_removes_new_store_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    store = LocalVolumeArtifactStore(tmp_path / "artifacts")
    result = SimpleNamespace(
        output_bytes=b"result",
        filesize_bytes=6,
        mime_type="image/png",
        format="png",
        width=1,
        height=1,
        checksum="sha256:ignored",
        processing_warnings=[],
    )
    with Session(engine) as session:
        def fail_flush() -> None:
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(session, "flush", fail_flush)
        with pytest.raises(RuntimeError, match="database unavailable"):
            create_artifact(
                session=session,
                artifact_store=store,
                run_id="run_test",
                site_id="site_test",
                result=cast(Any, result),
                source_media_type="image",
            )
        session.rollback()
    engine.dispose()
    assert not [path for path in (tmp_path / "artifacts").rglob("obj_*") if path.is_file()]
