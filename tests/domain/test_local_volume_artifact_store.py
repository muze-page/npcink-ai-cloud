from __future__ import annotations

import io
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.core.config import Settings
from app.domain.media_artifacts import (
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


def test_example_environment_keys_match_settings_contract() -> None:
    example = (Path(__file__).resolve().parents[2] / ".env.example").read_text()
    assert "NPCINK_CLOUD_ARTIFACT_STORE_ROOT=" in example
    assert "NPCINK_CLOUD_ARTIFACT_STORE_CHUNK_BYTES=" in example
    fields = Settings.model_fields
    assert "artifact_store_root" in fields
    assert "artifact_store_chunk_bytes" in fields


def test_metadata_flush_failure_removes_new_store_object(tmp_path: Path) -> None:
    class FailingSession:
        def add(self, value: object) -> None:
            pass

        def flush(self) -> None:
            raise RuntimeError("database unavailable")

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
    with pytest.raises(RuntimeError, match="database unavailable"):
        create_artifact(
            session=cast(Any, FailingSession()),
            artifact_store=store,
            run_id="run_test",
            site_id="site_test",
            result=cast(Any, result),
            source_media_type="image",
        )
    assert not [path for path in (tmp_path / "artifacts").rglob("obj_*") if path.is_file()]
