from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol
from uuid import uuid4

from app.core.config import Settings

_STORAGE_KEY = re.compile(r"^obj_[0-9a-f]{32}$")


class ArtifactStoreError(RuntimeError):
    pass


class ArtifactStorePublicationUncertainError(ArtifactStoreError):
    def __init__(self, storage_metadata: ArtifactStorageMetadata) -> None:
        super().__init__("artifact publication durability is uncertain")
        self.storage_metadata = storage_metadata


@dataclass(frozen=True, slots=True)
class ArtifactStorageMetadata:
    storage_key: str
    byte_size: int
    checksum: str


class ArtifactStore(Protocol):
    chunk_size: int

    def put(
        self, stream: BinaryIO, *, max_bytes: int, metadata: Mapping[str, str] | None = None
    ) -> ArtifactStorageMetadata: ...

    def open(self, storage_key: str) -> BinaryIO: ...
    def delete(self, storage_key: str) -> None: ...
    def metadata(self, storage_key: str) -> ArtifactStorageMetadata: ...


class LocalVolumeArtifactStore:
    def __init__(self, root: str | Path, *, chunk_size: int = 64 * 1024) -> None:
        raw_root = Path(root).expanduser()
        if not raw_root.is_absolute():
            raise ValueError("artifact store root must be absolute")
        self.root = raw_root.resolve()
        self.chunk_size = max(4096, min(int(chunk_size), 1024 * 1024))

    def put(
        self, stream: BinaryIO, *, max_bytes: int, metadata: Mapping[str, str] | None = None
    ) -> ArtifactStorageMetadata:
        del metadata
        if max_bytes <= 0:
            raise ArtifactStoreError("artifact size limit must be positive")
        storage_key = f"obj_{uuid4().hex}"
        destination = self._path(storage_key)
        temp = destination.parent / f".{storage_key}.{uuid4().hex}.tmp"
        digest = hashlib.sha256()
        byte_size = 0
        storage_metadata: ArtifactStorageMetadata | None = None
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with temp.open("xb") as output:
                os.fchmod(output.fileno(), 0o600)
                while True:
                    chunk = stream.read(self.chunk_size)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    byte_size += len(chunk)
                    if byte_size > int(max_bytes):
                        raise ArtifactStoreError("artifact exceeds size limit")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp, destination)
            storage_metadata = ArtifactStorageMetadata(
                storage_key,
                byte_size,
                f"sha256:{digest.hexdigest()}",
            )
            try:
                self._fsync_directory(destination.parent)
            except OSError as publication_error:
                try:
                    destination.unlink(missing_ok=True)
                    self._fsync_directory(destination.parent)
                except OSError as rollback_error:
                    raise ArtifactStorePublicationUncertainError(
                        storage_metadata
                    ) from rollback_error
                raise ArtifactStoreError(
                    "artifact publication failed and was rolled back"
                ) from publication_error
        except ArtifactStorePublicationUncertainError:
            temp.unlink(missing_ok=True)
            raise
        except ArtifactStoreError:
            temp.unlink(missing_ok=True)
            raise
        except Exception as error:
            temp.unlink(missing_ok=True)
            raise ArtifactStoreError("artifact write failed") from error
        assert storage_metadata is not None
        return storage_metadata

    def open(self, storage_key: str) -> BinaryIO:
        try:
            return self._path(storage_key).open("rb")
        except OSError as error:
            raise ArtifactStoreError("artifact is unavailable") from error

    def delete(self, storage_key: str) -> None:
        path = self._path(storage_key)
        try:
            path.unlink(missing_ok=True)
            if path.parent.exists():
                self._fsync_directory(path.parent)
        except OSError as error:
            raise ArtifactStoreError("artifact delete failed") from error

    def metadata(self, storage_key: str) -> ArtifactStorageMetadata:
        digest = hashlib.sha256()
        byte_size = 0
        try:
            with self.open(storage_key) as stream:
                while True:
                    chunk = stream.read(self.chunk_size)
                    if not chunk:
                        break
                    digest.update(chunk)
                    byte_size += len(chunk)
        except ArtifactStoreError:
            raise
        except OSError as error:
            raise ArtifactStoreError("artifact metadata read failed") from error
        return ArtifactStorageMetadata(storage_key, byte_size, f"sha256:{digest.hexdigest()}")

    def _path(self, storage_key: str) -> Path:
        if not _STORAGE_KEY.fullmatch(storage_key):
            raise ArtifactStoreError("invalid artifact storage key")
        path = self.root / storage_key[4:6] / storage_key[6:8] / storage_key
        resolved = path.resolve()
        if self.root not in resolved.parents:
            raise ArtifactStoreError("invalid artifact storage key")
        return resolved

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(directory, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def build_artifact_store(settings: Settings) -> ArtifactStore:
    return LocalVolumeArtifactStore(
        settings.artifact_store_root,
        chunk_size=settings.artifact_store_chunk_bytes,
    )


def iter_artifact_chunks(store: ArtifactStore, storage_key: str) -> Iterator[bytes]:
    with store.open(storage_key) as stream:
        while True:
            chunk = stream.read(store.chunk_size)
            if not chunk:
                break
            yield chunk


def read_artifact_bytes(
    store: ArtifactStore,
    storage_key: str,
    *,
    max_bytes: int | None = None,
    expected_bytes: int | None = None,
    expected_checksum: str | None = None,
) -> bytes:
    payload = bytearray()
    digest = hashlib.sha256()
    try:
        with store.open(storage_key) as stream:
            while True:
                chunk = stream.read(store.chunk_size)
                if not chunk:
                    break
                payload.extend(chunk)
                digest.update(chunk)
                if max_bytes is not None and len(payload) > max_bytes:
                    raise ArtifactStoreError("artifact exceeds size limit")
    except ArtifactStoreError:
        raise
    except OSError as error:
        raise ArtifactStoreError("artifact read failed") from error
    if expected_bytes is not None and len(payload) != int(expected_bytes):
        raise ArtifactStoreError("artifact byte size does not match metadata")
    checksum = f"sha256:{digest.hexdigest()}"
    if expected_checksum is not None and checksum != expected_checksum:
        raise ArtifactStoreError("artifact checksum does not match metadata")
    return bytes(payload)
