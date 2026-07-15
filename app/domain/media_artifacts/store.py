from __future__ import annotations

import errno
import fcntl
import hashlib
import heapq
import os
import re
import stat
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable
from uuid import uuid4

from app.core.config import Settings

_STORAGE_KEY = re.compile(r"^obj_[0-9a-f]{32}$")
_SHARD = re.compile(r"^[0-9a-f]{2}$")
_ARTIFACT_INVENTORY_MAX_PAGE_SIZE = 500
_PUBLICATION_FENCE_FILE = ".artifact-publication.lock"


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


@dataclass(frozen=True, slots=True)
class ArtifactInventoryItem:
    storage_key: str
    byte_size: int
    last_modified_at: datetime


@dataclass(frozen=True, slots=True)
class ArtifactInventoryPage:
    items: tuple[ArtifactInventoryItem, ...]
    next_cursor: str | None


class ArtifactStore(Protocol):
    chunk_size: int

    def put(
        self, stream: BinaryIO, *, max_bytes: int, metadata: Mapping[str, str] | None = None
    ) -> ArtifactStorageMetadata: ...

    def open(self, storage_key: str) -> BinaryIO: ...
    def delete(self, storage_key: str) -> None: ...
    def metadata(self, storage_key: str) -> ArtifactStorageMetadata: ...


@runtime_checkable
class ArtifactInventoryStore(Protocol):
    """Optional read-only inventory seam for stores that can enumerate objects.

    Cursor values are backend-opaque continuation tokens. A non-null token
    means more matching objects remain, and one traversal over a quiescent
    store must neither repeat a token nor skip a matching object. Concurrent
    mutations may become visible in the current or next complete traversal.
    Storage keys are unique and strictly ascending within a page, and every
    later page starts after the preceding page's final storage key.
    """

    def list_objects(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> ArtifactInventoryPage: ...

    def contains(self, storage_key: str) -> bool: ...


class ArtifactPublicationGuard(Protocol):
    def release(self) -> None: ...


@runtime_checkable
class ArtifactPublicationFenceStore(Protocol):
    """Optional cross-process fence used by publication and future deletion."""

    def acquire_publication_guard(self) -> ArtifactPublicationGuard: ...

    def try_acquire_reconciliation_guard(self) -> ArtifactPublicationGuard | None: ...


class _LocalVolumeArtifactGuard:
    def __init__(self, descriptor: int) -> None:
        self._descriptor: int | None = descriptor
        self._release_lock = threading.Lock()

    def release(self) -> None:
        with self._release_lock:
            descriptor = self._descriptor
            self._descriptor = None
        if descriptor is None:
            return
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(descriptor)
        except OSError:
            pass


class LocalVolumeArtifactStore:
    def __init__(self, root: str | Path, *, chunk_size: int = 64 * 1024) -> None:
        raw_root = Path(root).expanduser()
        if not raw_root.is_absolute():
            raise ValueError("artifact store root must be absolute")
        try:
            self.root = raw_root.resolve()
        except Exception:
            raise ValueError("artifact store root is invalid") from None
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

    def list_objects(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> ArtifactInventoryPage:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= _ARTIFACT_INVENTORY_MAX_PAGE_SIZE
        ):
            raise ArtifactStoreError("artifact inventory request is invalid")
        if cursor is not None and not _STORAGE_KEY.fullmatch(cursor):
            raise ArtifactStoreError("artifact inventory request is invalid")

        root_descriptor: int | None = None
        try:
            try:
                root_descriptor = os.open(self.root, self._directory_open_flags())
            except FileNotFoundError:
                return ArtifactInventoryPage(items=(), next_cursor=None)
            root_device = int(os.fstat(root_descriptor).st_dev)
            first_shards = self._strict_child_directory_names(root_descriptor)
            selected: list[tuple[str, os.stat_result]] = []
            scan_limit = limit + 1
            cursor_first_shard = cursor[4:6] if cursor is not None else None
            cursor_second_shard = cursor[6:8] if cursor is not None else None
            for first_shard in first_shards:
                if cursor_first_shard is not None and first_shard < cursor_first_shard:
                    continue
                first_descriptor = self._try_open_child_directory(
                    root_descriptor,
                    first_shard,
                    expected_device=root_device,
                )
                if first_descriptor is None:
                    continue
                try:
                    second_shards = self._strict_child_directory_names(first_descriptor)
                    for second_shard in second_shards:
                        if (
                            first_shard == cursor_first_shard
                            and cursor_second_shard is not None
                            and second_shard < cursor_second_shard
                        ):
                            continue
                        remaining = scan_limit - len(selected)
                        if remaining <= 0:
                            break
                        leaf_descriptor = self._try_open_child_directory(
                            first_descriptor,
                            second_shard,
                            expected_device=root_device,
                        )
                        if leaf_descriptor is None:
                            continue
                        try:
                            selected.extend(
                                self._smallest_inventory_entries(
                                    leaf_descriptor,
                                    first_shard=first_shard,
                                    second_shard=second_shard,
                                    cursor=cursor,
                                    limit=remaining,
                                )
                            )
                        finally:
                            self._close_descriptor(leaf_descriptor)
                finally:
                    self._close_descriptor(first_descriptor)
                if len(selected) >= scan_limit:
                    break
        except ArtifactStoreError:
            raise
        except Exception:
            raise ArtifactStoreError("artifact inventory failed") from None
        finally:
            if root_descriptor is not None:
                self._close_descriptor(root_descriptor)

        try:
            has_more = len(selected) > limit
            page_entries = selected[:limit]
            items = tuple(
                ArtifactInventoryItem(
                    storage_key=storage_key,
                    byte_size=int(storage_stat.st_size),
                    last_modified_at=datetime.fromtimestamp(storage_stat.st_mtime, UTC),
                )
                for storage_key, storage_stat in page_entries
            )
        except Exception:
            raise ArtifactStoreError("artifact inventory failed") from None
        return ArtifactInventoryPage(
            items=items,
            next_cursor=items[-1].storage_key if has_more else None,
        )

    def contains(self, storage_key: str) -> bool:
        self._raw_path(storage_key)
        root_descriptor: int | None = None
        first_descriptor: int | None = None
        leaf_descriptor: int | None = None
        try:
            root_descriptor = os.open(self.root, self._directory_open_flags())
            root_device = int(os.fstat(root_descriptor).st_dev)
            first_descriptor = self._try_open_child_directory(
                root_descriptor,
                storage_key[4:6],
                expected_device=root_device,
            )
            if first_descriptor is None:
                return False
            leaf_descriptor = self._try_open_child_directory(
                first_descriptor,
                storage_key[6:8],
                expected_device=root_device,
            )
            if leaf_descriptor is None:
                return False
            storage_stat = os.stat(
                storage_key,
                dir_fd=leaf_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return False
        except OSError:
            raise ArtifactStoreError("artifact existence check failed") from None
        finally:
            for descriptor in (leaf_descriptor, first_descriptor, root_descriptor):
                if descriptor is not None:
                    self._close_descriptor(descriptor)
        return stat.S_ISREG(storage_stat.st_mode) and storage_stat.st_nlink == 1

    def acquire_publication_guard(self) -> ArtifactPublicationGuard:
        guard = self._acquire_guard(exclusive=False, nonblocking=False)
        assert guard is not None
        return guard

    def try_acquire_reconciliation_guard(self) -> ArtifactPublicationGuard | None:
        return self._acquire_guard(exclusive=True, nonblocking=True)

    def _strict_child_directory_names(self, parent_descriptor: int) -> list[str]:
        try:
            with os.scandir(parent_descriptor) as entries:
                return sorted(
                    entry.name
                    for entry in entries
                    if _SHARD.fullmatch(entry.name)
                )
        except OSError:
            raise ArtifactStoreError("artifact inventory failed") from None

    def _try_open_child_directory(
        self,
        parent_descriptor: int,
        name: str,
        *,
        expected_device: int,
    ) -> int | None:
        descriptor: int | None = None
        try:
            descriptor = os.open(
                name,
                self._directory_open_flags(),
                dir_fd=parent_descriptor,
            )
            directory_stat = os.fstat(descriptor)
            if (
                not stat.S_ISDIR(directory_stat.st_mode)
                or int(directory_stat.st_dev) != expected_device
            ):
                self._close_descriptor(descriptor)
                return None
            return descriptor
        except (FileNotFoundError, NotADirectoryError):
            if descriptor is not None:
                self._close_descriptor(descriptor)
            return None
        except OSError as error:
            if descriptor is not None:
                self._close_descriptor(descriptor)
            if error.errno == errno.ELOOP:
                return None
            raise
        except BaseException:
            if descriptor is not None:
                self._close_descriptor(descriptor)
            raise

    def _smallest_inventory_entries(
        self,
        leaf_descriptor: int,
        *,
        first_shard: str,
        second_shard: str,
        cursor: str | None,
        limit: int,
    ) -> list[tuple[str, os.stat_result]]:
        try:
            with os.scandir(leaf_descriptor) as entries:

                def candidates() -> Iterator[tuple[str, os.stat_result]]:
                    for entry in entries:
                        storage_key = entry.name
                        if (
                            not _STORAGE_KEY.fullmatch(storage_key)
                            or storage_key[4:6] != first_shard
                            or storage_key[6:8] != second_shard
                            or (cursor is not None and storage_key <= cursor)
                        ):
                            continue
                        try:
                            storage_stat = entry.stat(follow_symlinks=False)
                        except FileNotFoundError:
                            continue
                        if not stat.S_ISREG(storage_stat.st_mode) or storage_stat.st_nlink != 1:
                            continue
                        yield storage_key, storage_stat

                return heapq.nsmallest(limit, candidates(), key=lambda item: item[0])
        except OSError:
            raise ArtifactStoreError("artifact inventory failed") from None

    @staticmethod
    def _directory_open_flags() -> int:
        return (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )

    @staticmethod
    def _close_descriptor(descriptor: int) -> None:
        try:
            os.close(descriptor)
        except OSError:
            pass

    def _acquire_guard(
        self,
        *,
        exclusive: bool,
        nonblocking: bool,
    ) -> ArtifactPublicationGuard | None:
        descriptor: int | None = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(self.root / _PUBLICATION_FENCE_FILE, flags, 0o600)
            lock_stat = os.fstat(descriptor)
            if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_nlink != 1:
                raise ArtifactStoreError("artifact publication fence is unavailable")
            os.fchmod(descriptor, 0o600)
            operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            if nonblocking:
                operation |= fcntl.LOCK_NB
            try:
                fcntl.flock(descriptor, operation)
            except BlockingIOError:
                os.close(descriptor)
                return None
            guard = _LocalVolumeArtifactGuard(descriptor)
            descriptor = None
            return guard
        except ArtifactStoreError:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise
        except Exception:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise ArtifactStoreError("artifact publication fence is unavailable") from None
        except BaseException:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise

    def _raw_path(self, storage_key: str) -> Path:
        if not _STORAGE_KEY.fullmatch(storage_key):
            raise ArtifactStoreError("invalid artifact storage key")
        return self.root / storage_key[4:6] / storage_key[6:8] / storage_key

    def _path(self, storage_key: str) -> Path:
        path = self._raw_path(storage_key)
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
