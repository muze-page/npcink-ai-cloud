from __future__ import annotations

import io
import multiprocessing
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domain.media_artifacts import (
    ArtifactInventoryPage,
    ArtifactStoreError,
    ArtifactStorePublicationUncertainError,
    LocalVolumeArtifactStore,
)
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
    original = store._fsync_directory
    calls: list[Path] = []

    def record(directory: Path) -> None:
        calls.append(directory)
        original(directory)

    monkeypatch.setattr(store, "_fsync_directory", record)
    result = store.put(io.BytesIO(b"payload"), max_bytes=7)
    with store.open(result.storage_key) as stream:
        expected_parent = Path(stream.name).parent
    assert calls == [expected_parent]


def test_parent_fsync_failure_rolls_back_published_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalVolumeArtifactStore(tmp_path / "artifacts")
    original = store._fsync_directory
    attempts = 0

    def fail_once(directory: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("directory fsync failed")
        original(directory)

    monkeypatch.setattr(store, "_fsync_directory", fail_once)
    with pytest.raises(ArtifactStoreError, match="rolled back"):
        store.put(io.BytesIO(b"payload"), max_bytes=7)
    assert attempts == 2
    assert not [path for path in (tmp_path / "artifacts").rglob("obj_*") if path.is_file()]
    assert not list((tmp_path / "artifacts").rglob("*.tmp"))


def test_parent_fsync_and_rollback_fsync_failure_reports_uncertain_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalVolumeArtifactStore(tmp_path / "artifacts")

    def fail(directory: Path) -> None:
        raise OSError(f"cannot fsync {directory.name}")

    monkeypatch.setattr(store, "_fsync_directory", fail)
    with pytest.raises(ArtifactStorePublicationUncertainError) as caught:
        store.put(io.BytesIO(b"payload"), max_bytes=7)
    assert caught.value.storage_metadata.byte_size == 7
    assert caught.value.storage_metadata.storage_key.startswith("obj_")
    assert not list((tmp_path / "artifacts").rglob("*.tmp"))


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


def test_inventory_never_follows_a_shard_replaced_by_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts"
    (root / "aa").mkdir(parents=True)
    external_root = tmp_path / "outside"
    external_key = "obj_aabb" + ("0" * 28)
    _write_inventory_object(external_root, external_key, b"outside")
    store = LocalVolumeArtifactStore(root)
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
        leaf_descriptor: int,
        *,
        first_shard: str,
        second_shard: str,
        cursor: str | None,
        limit: int,
    ) -> list[tuple[str, os.stat_result]]:
        scanned_first_shards.append(first_shard)
        return original(
            leaf_descriptor,
            first_shard=first_shard,
            second_shard=second_shard,
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


def test_example_environment_keys_match_settings_contract() -> None:
    example = (Path(__file__).resolve().parents[2] / ".env.example").read_text()
    assert "NPCINK_CLOUD_ARTIFACT_STORE_ROOT=" in example
    assert "NPCINK_CLOUD_ARTIFACT_STORE_CHUNK_BYTES=" in example
    assert "NPCINK_CLOUD_ARTIFACT_RECONCILIATION_INTERVAL_SECONDS=3600" in example
    assert "NPCINK_CLOUD_ARTIFACT_RECONCILIATION_SAFETY_WINDOW_SECONDS=86400" in example
    assert "NPCINK_CLOUD_ARTIFACT_RECONCILIATION_PAGE_SIZE=200" in example
    fields = Settings.model_fields
    assert "artifact_store_root" in fields
    assert "artifact_store_chunk_bytes" in fields
    assert "artifact_reconciliation_interval_seconds" in fields
    assert "artifact_reconciliation_safety_window_seconds" in fields
    assert "artifact_reconciliation_page_size" in fields


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
    ):
        assert compose.count(variable) == 2
    ops_worker = compose.split("  ops-worker:", maxsplit=1)[1]
    assert "NPCINK_CLOUD_ARTIFACT_RECONCILIATION_INTERVAL_SECONDS:" in ops_worker
    assert "NPCINK_CLOUD_ARTIFACT_RECONCILIATION_SAFETY_WINDOW_SECONDS:" in ops_worker
    assert "NPCINK_CLOUD_ARTIFACT_RECONCILIATION_PAGE_SIZE:" in ops_worker


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
