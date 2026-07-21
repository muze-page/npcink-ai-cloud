from __future__ import annotations

import errno
import fcntl
import hashlib
import heapq
import os
import re
import secrets
import stat
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable
from uuid import uuid4

from app.core.config import Settings

_STORAGE_KEY = re.compile(r"^obj_[0-9a-f]{32}$")
_SHARD = re.compile(r"^[0-9a-f]{2}$")
_ARTIFACT_INVENTORY_MAX_PAGE_SIZE = 500
_PUBLICATION_FENCE_FILE = ".artifact-publication.lock"
_STORE_BOOTSTRAP_LOCK_FILE = ".artifact-store-bootstrap.lock"
_STORE_GENERATION_FILE = ".artifact-store-generation"
_STORE_GENERATION = re.compile(r"^gen_[0-9a-f]{32}$")


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
    object_version: str = ""


@dataclass(frozen=True, slots=True)
class ArtifactInventoryPage:
    items: tuple[ArtifactInventoryItem, ...]
    next_cursor: str | None
    store_generation: str = ""


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


class ArtifactPublicationSession(Protocol):
    def validate(self) -> None: ...

    def put(
        self,
        stream: BinaryIO,
        *,
        max_bytes: int,
        metadata: Mapping[str, str] | None = None,
    ) -> ArtifactStorageMetadata: ...

    def delete_published(self, storage_key: str) -> None: ...
    def release(self) -> None: ...


class ArtifactConditionalDeleteResult(StrEnum):
    DELETED_DURABLE = "deleted_durable"
    ALREADY_ABSENT_DURABLE = "already_absent_durable"
    OBJECT_CHANGED = "object_changed"
    UNSAFE_LAYOUT = "unsafe_layout"


class ArtifactReconciliationSession(Protocol):
    @property
    def store_generation(self) -> str: ...

    def validate(self) -> None: ...

    def delete_if_unchanged(
        self,
        storage_key: str,
        object_version: str,
    ) -> ArtifactConditionalDeleteResult: ...

    def release(self) -> None: ...


@runtime_checkable
class ArtifactSessionStore(Protocol):
    def open_publication_session(self) -> ArtifactPublicationSession: ...

    def try_open_reconciliation_session(
        self,
    ) -> ArtifactReconciliationSession | None: ...


@runtime_checkable
class ArtifactPublicationFenceStore(Protocol):
    """Optional cross-process fence used by publication and future deletion."""

    def acquire_publication_guard(self) -> ArtifactPublicationGuard: ...

    def try_acquire_reconciliation_guard(self) -> ArtifactPublicationGuard | None: ...


class _LocalVolumeRootSession:
    def __init__(
        self,
        store: LocalVolumeArtifactStore,
        *,
        root_descriptor: int,
        lock_descriptor: int,
        marker_descriptor: int,
        store_generation: str,
    ) -> None:
        self._store = store
        self._root_descriptor: int | None = root_descriptor
        self._lock_descriptor: int | None = lock_descriptor
        self._marker_descriptor: int | None = marker_descriptor
        self._root_identity = _identity(os.fstat(root_descriptor))
        self._lock_identity = _identity(os.fstat(lock_descriptor))
        self._marker_identity = _identity(os.fstat(marker_descriptor))
        self._store_generation = store_generation
        self._release_lock = threading.Lock()

    @property
    def store_generation(self) -> str:
        return self._store_generation

    @property
    def root_descriptor(self) -> int:
        if self._root_descriptor is None:
            raise ArtifactStoreError("artifact store session is unavailable")
        return self._root_descriptor

    @property
    def root_device(self) -> int:
        return int(os.fstat(self.root_descriptor).st_dev)

    def validate(self, *, require_configured_root: bool = True) -> None:
        root_descriptor = self.root_descriptor
        lock_descriptor = self._lock_descriptor
        marker_descriptor = self._marker_descriptor
        if lock_descriptor is None or marker_descriptor is None:
            raise ArtifactStoreError("artifact store session is unavailable")
        try:
            root_stat = os.fstat(root_descriptor)
            lock_stat = os.fstat(lock_descriptor)
            marker_stat = os.fstat(marker_descriptor)
            if (
                not stat.S_ISDIR(root_stat.st_mode)
                or _identity(root_stat) != self._root_identity
                or not _safe_private_regular(lock_stat, device=int(root_stat.st_dev))
                or _identity(lock_stat) != self._lock_identity
                or not _safe_private_regular(marker_stat, device=int(root_stat.st_dev))
                or _identity(marker_stat) != self._marker_identity
            ):
                raise ArtifactStoreError("artifact store session validation failed")
            if require_configured_root:
                configured_root = os.stat(self._store.root, follow_symlinks=False)
                if _identity(configured_root) != self._root_identity:
                    raise ArtifactStoreError("artifact store session validation failed")
            lock_path_stat = os.stat(
                _PUBLICATION_FENCE_FILE,
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
            marker_path_stat = os.stat(
                _STORE_GENERATION_FILE,
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
            if (
                _identity(lock_path_stat) != self._lock_identity
                or _identity(marker_path_stat) != self._marker_identity
                or self._store._read_generation(marker_descriptor)
                != self._store_generation
            ):
                raise ArtifactStoreError("artifact store session validation failed")
        except ArtifactStoreError:
            raise
        except Exception:
            raise ArtifactStoreError("artifact store session validation failed") from None

    def release(self) -> None:
        with self._release_lock:
            descriptors = (
                self._marker_descriptor,
                self._lock_descriptor,
                self._root_descriptor,
            )
            self._marker_descriptor = None
            self._lock_descriptor = None
            self._root_descriptor = None
        marker_descriptor, lock_descriptor, root_descriptor = descriptors
        if lock_descriptor is not None:
            try:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        for descriptor in (marker_descriptor, lock_descriptor, root_descriptor):
            if descriptor is not None:
                self._store._close_descriptor(descriptor)


class _LocalVolumePublicationSession(_LocalVolumeRootSession):
    def put(
        self,
        stream: BinaryIO,
        *,
        max_bytes: int,
        metadata: Mapping[str, str] | None = None,
    ) -> ArtifactStorageMetadata:
        del metadata
        if max_bytes <= 0:
            raise ArtifactStoreError("artifact size limit must be positive")
        self.validate()
        storage_key = f"obj_{uuid4().hex}"
        leaf_descriptor = self._store._open_storage_leaf(
            self.root_descriptor,
            storage_key,
            expected_device=self.root_device,
            create=True,
        )
        assert leaf_descriptor is not None
        temp_name = f".{storage_key}.{uuid4().hex}.tmp"
        temp_descriptor: int | None = None
        published = False
        digest = hashlib.sha256()
        byte_size = 0
        storage_metadata: ArtifactStorageMetadata | None = None
        try:
            temp_descriptor = os.open(
                temp_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=leaf_descriptor,
            )
            os.fchmod(temp_descriptor, 0o600)
            while True:
                chunk = stream.read(self._store.chunk_size)
                if not chunk:
                    break
                byte_size += len(chunk)
                if byte_size > int(max_bytes):
                    raise ArtifactStoreError("artifact exceeds size limit")
                digest.update(chunk)
                _write_all(temp_descriptor, chunk)
            self._store._fsync_descriptor(temp_descriptor)
            os.close(temp_descriptor)
            temp_descriptor = None
            os.rename(
                temp_name,
                storage_key,
                src_dir_fd=leaf_descriptor,
                dst_dir_fd=leaf_descriptor,
            )
            published = True
            storage_metadata = ArtifactStorageMetadata(
                storage_key=storage_key,
                byte_size=byte_size,
                checksum=f"sha256:{digest.hexdigest()}",
            )
            try:
                self._store._fsync_publication_directory(leaf_descriptor)
                self.validate()
            except Exception as publication_error:
                self._rollback_publication(
                    leaf_descriptor,
                    storage_key,
                    storage_metadata,
                )
                raise ArtifactStoreError(
                    "artifact publication failed and was rolled back"
                ) from publication_error
            return storage_metadata
        except ArtifactStoreError:
            if (
                published
                and storage_metadata is not None
                and self._published_object_exists(leaf_descriptor, storage_key)
            ):
                self._rollback_publication(
                    leaf_descriptor,
                    storage_key,
                    storage_metadata,
                )
            raise
        except BaseException as error:
            if published and storage_metadata is not None:
                try:
                    self._rollback_publication(
                        leaf_descriptor,
                        storage_key,
                        storage_metadata,
                    )
                except ArtifactStorePublicationUncertainError:
                    raise
            if isinstance(error, Exception):
                raise ArtifactStoreError("artifact write failed") from None
            raise
        finally:
            if temp_descriptor is not None:
                self._store._close_descriptor(temp_descriptor)
            try:
                os.unlink(temp_name, dir_fd=leaf_descriptor)
            except FileNotFoundError:
                pass
            except OSError:
                pass
            self._store._close_descriptor(leaf_descriptor)

    def delete_published(self, storage_key: str) -> None:
        self._store._raw_path(storage_key)
        self.validate(require_configured_root=False)
        leaf_descriptor = self._store._open_storage_leaf(
            self.root_descriptor,
            storage_key,
            expected_device=self.root_device,
            create=False,
        )
        if leaf_descriptor is None:
            return
        try:
            try:
                os.unlink(storage_key, dir_fd=leaf_descriptor)
            except FileNotFoundError:
                pass
            self._store._fsync_publication_directory(leaf_descriptor)
            self.validate(require_configured_root=False)
        except ArtifactStoreError:
            raise
        except Exception:
            raise ArtifactStoreError("artifact delete failed") from None
        finally:
            self._store._close_descriptor(leaf_descriptor)

    def _rollback_publication(
        self,
        leaf_descriptor: int,
        storage_key: str,
        storage_metadata: ArtifactStorageMetadata,
    ) -> None:
        try:
            self.validate(require_configured_root=False)
            os.unlink(storage_key, dir_fd=leaf_descriptor)
            self._store._fsync_publication_directory(leaf_descriptor)
        except Exception as rollback_error:
            raise ArtifactStorePublicationUncertainError(
                storage_metadata
            ) from rollback_error

    @staticmethod
    def _published_object_exists(leaf_descriptor: int, storage_key: str) -> bool:
        try:
            os.stat(storage_key, dir_fd=leaf_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return False
        except OSError:
            return True
        return True


class _LocalVolumeReconciliationSession(_LocalVolumeRootSession):
    def validate(self, *, require_configured_root: bool = True) -> None:
        del require_configured_root
        super().validate(require_configured_root=True)
        if not _safe_reconciliation_directory(os.fstat(self.root_descriptor)):
            raise ArtifactStoreError("artifact store permissions are unsafe")

    def delete_if_unchanged(
        self,
        storage_key: str,
        object_version: str,
    ) -> ArtifactConditionalDeleteResult:
        self._store._raw_path(storage_key)
        self.validate()
        try:
            opened = self._store._open_versioned_object(
                self.root_descriptor,
                storage_key,
                store_generation=self.store_generation,
            )
        except ArtifactStoreError:
            return ArtifactConditionalDeleteResult.UNSAFE_LAYOUT
        if opened is None:
            try:
                deepest_descriptor, owned_descriptors = (
                    self._store._open_deepest_storage_directory(
                        self.root_descriptor,
                        storage_key,
                    )
                )
            except ArtifactStoreError:
                return ArtifactConditionalDeleteResult.UNSAFE_LAYOUT
            try:
                if not self._store._missing_directory_chain_is_safe(
                    self.root_descriptor,
                    storage_key,
                    owned_descriptors,
                ):
                    return ArtifactConditionalDeleteResult.UNSAFE_LAYOUT
                self._store._fsync_descriptor(deepest_descriptor)
                if not self._store._missing_directory_chain_is_safe(
                    self.root_descriptor,
                    storage_key,
                    owned_descriptors,
                ):
                    return ArtifactConditionalDeleteResult.UNSAFE_LAYOUT
                self.validate()
                return ArtifactConditionalDeleteResult.ALREADY_ABSENT_DURABLE
            finally:
                for descriptor in reversed(owned_descriptors):
                    self._store._close_descriptor(descriptor)
        first_descriptor, leaf_descriptor, observed_version = opened
        try:
            if not all(
                _safe_reconciliation_directory(os.fstat(descriptor))
                for descriptor in (first_descriptor, leaf_descriptor)
            ):
                return ArtifactConditionalDeleteResult.UNSAFE_LAYOUT
            storage_stat = os.stat(
                storage_key,
                dir_fd=leaf_descriptor,
                follow_symlinks=False,
            )
            if not _safe_reconciliation_file(
                storage_stat,
                device=self.root_device,
            ):
                return ArtifactConditionalDeleteResult.UNSAFE_LAYOUT
            if not secrets.compare_digest(observed_version, object_version):
                return ArtifactConditionalDeleteResult.OBJECT_CHANGED
            self.validate()
            repeated = self._store._object_version_from_descriptors(
                self.root_descriptor,
                first_descriptor,
                leaf_descriptor,
                storage_key,
                store_generation=self.store_generation,
            )
            if repeated is None:
                return ArtifactConditionalDeleteResult.OBJECT_CHANGED
            if not secrets.compare_digest(repeated, object_version):
                return ArtifactConditionalDeleteResult.OBJECT_CHANGED
            self.validate()
            try:
                os.unlink(storage_key, dir_fd=leaf_descriptor)
            except FileNotFoundError:
                self._store._fsync_descriptor(leaf_descriptor)
                self.validate()
                return ArtifactConditionalDeleteResult.ALREADY_ABSENT_DURABLE
            self._store._fsync_descriptor(leaf_descriptor)
            self.validate()
            return ArtifactConditionalDeleteResult.DELETED_DURABLE
        except ArtifactStoreError:
            raise
        except OSError:
            return ArtifactConditionalDeleteResult.UNSAFE_LAYOUT
        finally:
            self._store._close_descriptor(leaf_descriptor)
            self._store._close_descriptor(first_descriptor)
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
        if max_bytes <= 0:
            raise ArtifactStoreError("artifact size limit must be positive")
        publication_session = self.open_publication_session()
        try:
            return publication_session.put(
                stream,
                max_bytes=max_bytes,
                metadata=metadata,
            )
        finally:
            publication_session.release()

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
                return ArtifactInventoryPage(
                    items=(),
                    next_cursor=None,
                    store_generation="",
                )
            root_device = int(os.fstat(root_descriptor).st_dev)
            try:
                marker_descriptor = self._open_generation_marker(
                    root_descriptor,
                    expected_device=root_device,
                )
            except ArtifactStoreError:
                if (
                    not self._generation_marker_is_missing(root_descriptor)
                    or self._has_storage_shard_entry(root_descriptor)
                ):
                    raise
                return ArtifactInventoryPage(
                    items=(),
                    next_cursor=None,
                    store_generation="",
                )
            try:
                store_generation = self._read_generation(marker_descriptor)
            finally:
                self._close_descriptor(marker_descriptor)
            first_shards = self._strict_child_directory_names(root_descriptor)
            selected: list[tuple[str, os.stat_result, str]] = []
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
                                    root_descriptor,
                                    first_descriptor,
                                    leaf_descriptor,
                                    first_shard=first_shard,
                                    second_shard=second_shard,
                                    store_generation=store_generation,
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
                    object_version=object_version,
                )
                for storage_key, storage_stat, object_version in page_entries
            )
        except Exception:
            raise ArtifactStoreError("artifact inventory failed") from None
        return ArtifactInventoryPage(
            items=items,
            next_cursor=items[-1].storage_key if has_more else None,
            store_generation=store_generation,
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
        return self.open_publication_session()

    def try_acquire_reconciliation_guard(self) -> ArtifactPublicationGuard | None:
        return self.try_open_reconciliation_session()

    def open_publication_session(self) -> ArtifactPublicationSession:
        opened = self._open_root_session(
            exclusive=False,
            nonblocking=False,
            create=True,
            session_type=_LocalVolumePublicationSession,
        )
        assert isinstance(opened, _LocalVolumePublicationSession)
        return opened

    def try_open_reconciliation_session(
        self,
    ) -> ArtifactReconciliationSession | None:
        opened = self._open_root_session(
            exclusive=True,
            nonblocking=True,
            create=False,
            session_type=_LocalVolumeReconciliationSession,
        )
        if opened is None:
            return None
        assert isinstance(opened, _LocalVolumeReconciliationSession)
        return opened

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
        try:
            with os.scandir(leaf_descriptor) as entries:

                def candidates() -> Iterator[tuple[str, os.stat_result, str]]:
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
                        object_version = self._object_version_from_descriptors(
                            root_descriptor,
                            first_descriptor,
                            leaf_descriptor,
                            storage_key,
                            store_generation=store_generation,
                        )
                        if object_version is None:
                            continue
                        yield storage_key, storage_stat, object_version

                return heapq.nsmallest(limit, candidates(), key=lambda item: item[0])
        except OSError:
            raise ArtifactStoreError("artifact inventory failed") from None

    def _open_root_session(
        self,
        *,
        exclusive: bool,
        nonblocking: bool,
        create: bool,
        session_type: type[_LocalVolumeRootSession],
    ) -> _LocalVolumeRootSession | None:
        root_descriptor: int | None = None
        lock_descriptor: int | None = None
        marker_descriptor: int | None = None
        try:
            if create:
                self.root.mkdir(parents=True, exist_ok=True)
            root_descriptor = os.open(self.root, self._directory_open_flags())
            root_stat = os.fstat(root_descriptor)
            if not stat.S_ISDIR(root_stat.st_mode):
                raise ArtifactStoreError("artifact store session is unavailable")
            root_device = int(root_stat.st_dev)
            lock_descriptor = self._open_publication_lock(
                root_descriptor,
                expected_device=root_device,
                create=create,
            )
            if not exclusive and create:
                marker_descriptor = self._open_publication_generation_marker(
                    root_descriptor,
                    lock_descriptor,
                    expected_device=root_device,
                )
            else:
                operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
                if nonblocking:
                    operation |= fcntl.LOCK_NB
                try:
                    fcntl.flock(lock_descriptor, operation)
                except BlockingIOError:
                    return None
                marker_descriptor = self._open_generation_marker(
                    root_descriptor,
                    expected_device=root_device,
                )
            store_generation = self._read_generation(marker_descriptor)
            opened = session_type(
                self,
                root_descriptor=root_descriptor,
                lock_descriptor=lock_descriptor,
                marker_descriptor=marker_descriptor,
                store_generation=store_generation,
            )
            root_descriptor = None
            lock_descriptor = None
            marker_descriptor = None
            try:
                opened.validate()
            except BaseException:
                opened.release()
                raise
            return opened
        except ArtifactStoreError:
            raise
        except FileNotFoundError:
            raise ArtifactStoreError("artifact store session is unavailable") from None
        except Exception:
            raise ArtifactStoreError("artifact store session is unavailable") from None
        except BaseException:
            raise
        finally:
            if lock_descriptor is not None:
                try:
                    fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
            for descriptor in (
                marker_descriptor,
                lock_descriptor,
                root_descriptor,
            ):
                if descriptor is not None:
                    self._close_descriptor(descriptor)

    def _open_publication_lock(
        self,
        root_descriptor: int,
        *,
        expected_device: int,
        create: bool,
    ) -> int:
        flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor: int | None = None
        try:
            if create:
                try:
                    descriptor = os.open(
                        _PUBLICATION_FENCE_FILE,
                        flags | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=root_descriptor,
                    )
                    os.fchmod(descriptor, 0o600)
                except FileExistsError:
                    descriptor = os.open(
                        _PUBLICATION_FENCE_FILE,
                        flags,
                        dir_fd=root_descriptor,
                    )
            else:
                descriptor = os.open(
                    _PUBLICATION_FENCE_FILE,
                    flags,
                    dir_fd=root_descriptor,
                )
            descriptor_stat = os.fstat(descriptor)
            path_stat = os.stat(
                _PUBLICATION_FENCE_FILE,
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
            if (
                not _safe_private_regular(descriptor_stat, device=expected_device)
                or _identity(path_stat) != _identity(descriptor_stat)
            ):
                raise ArtifactStoreError("artifact publication fence is unavailable")
            return descriptor
        except ArtifactStoreError:
            if descriptor is not None:
                self._close_descriptor(descriptor)
            raise
        except FileNotFoundError:
            if descriptor is not None:
                self._close_descriptor(descriptor)
            if not create:
                raise
            raise ArtifactStoreError("artifact publication fence is unavailable") from None
        except Exception:
            if descriptor is not None:
                self._close_descriptor(descriptor)
            raise ArtifactStoreError("artifact publication fence is unavailable") from None
        except BaseException:
            if descriptor is not None:
                self._close_descriptor(descriptor)
            raise

    def _open_generation_marker(
        self,
        root_descriptor: int,
        *,
        expected_device: int,
    ) -> int:
        flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor: int | None = None
        try:
            descriptor = os.open(
                _STORE_GENERATION_FILE,
                flags,
                dir_fd=root_descriptor,
            )
            marker_stat = os.fstat(descriptor)
            if not _safe_private_regular(marker_stat, device=expected_device):
                raise ArtifactStoreError("artifact store generation is unavailable")
            self._read_generation(descriptor)
            return descriptor
        except ArtifactStoreError:
            if descriptor is not None:
                self._close_descriptor(descriptor)
            raise
        except Exception:
            if descriptor is not None:
                self._close_descriptor(descriptor)
            raise ArtifactStoreError("artifact store generation is unavailable") from None
        except BaseException:
            if descriptor is not None:
                self._close_descriptor(descriptor)
            raise

    def _open_publication_generation_marker(
        self,
        root_descriptor: int,
        lock_descriptor: int,
        *,
        expected_device: int,
    ) -> int:
        """Pin a complete marker while retaining only a publication SH lock."""

        fcntl.flock(lock_descriptor, fcntl.LOCK_SH)
        try:
            return self._open_generation_marker(
                root_descriptor,
                expected_device=expected_device,
            )
        except ArtifactStoreError:
            if not self._can_bootstrap_generation_marker(
                root_descriptor,
                expected_device=expected_device,
            ):
                raise
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)

        bootstrap_descriptor: int | None = None
        try:
            bootstrap_descriptor = self._open_bootstrap_lock(
                root_descriptor,
                expected_device=expected_device,
            )
            fcntl.flock(bootstrap_descriptor, fcntl.LOCK_EX)
            self._validate_bootstrap_lock(
                root_descriptor,
                bootstrap_descriptor,
                expected_device=expected_device,
            )

            # Another initializer may have completed before this contender
            # acquired the short bootstrap mutex. Join its SH publication
            # fence immediately; never queue for EX behind its DB transaction.
            fcntl.flock(lock_descriptor, fcntl.LOCK_SH)
            try:
                return self._open_generation_marker(
                    root_descriptor,
                    expected_device=expected_device,
                )
            except ArtifactStoreError:
                if not self._can_bootstrap_generation_marker(
                    root_descriptor,
                    expected_device=expected_device,
                ):
                    raise
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)

            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            self._validate_bootstrap_lock(
                root_descriptor,
                bootstrap_descriptor,
                expected_device=expected_device,
            )
            try:
                marker_descriptor = self._open_generation_marker(
                    root_descriptor,
                    expected_device=expected_device,
                )
            except ArtifactStoreError:
                if not self._can_bootstrap_generation_marker(
                    root_descriptor,
                    expected_device=expected_device,
                ):
                    raise
                self._bootstrap_generation_marker(
                    root_descriptor,
                    expected_device=expected_device,
                )
                marker_descriptor = self._open_generation_marker(
                    root_descriptor,
                    expected_device=expected_device,
                )
            try:
                fcntl.flock(lock_descriptor, fcntl.LOCK_SH)
            except BaseException:
                self._close_descriptor(marker_descriptor)
                raise
            return marker_descriptor
        finally:
            if bootstrap_descriptor is not None:
                try:
                    fcntl.flock(bootstrap_descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
                self._close_descriptor(bootstrap_descriptor)

    def _open_bootstrap_lock(
        self,
        root_descriptor: int,
        *,
        expected_device: int,
    ) -> int:
        flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor: int | None = None
        try:
            try:
                descriptor = os.open(
                    _STORE_BOOTSTRAP_LOCK_FILE,
                    flags | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=root_descriptor,
                )
                os.fchmod(descriptor, 0o600)
            except FileExistsError:
                descriptor = os.open(
                    _STORE_BOOTSTRAP_LOCK_FILE,
                    flags,
                    dir_fd=root_descriptor,
                )
            self._validate_bootstrap_lock(
                root_descriptor,
                descriptor,
                expected_device=expected_device,
            )
            return descriptor
        except ArtifactStoreError:
            if descriptor is not None:
                self._close_descriptor(descriptor)
            raise
        except Exception:
            if descriptor is not None:
                self._close_descriptor(descriptor)
            raise ArtifactStoreError("artifact store bootstrap lock is unavailable") from None
        except BaseException:
            if descriptor is not None:
                self._close_descriptor(descriptor)
            raise

    @staticmethod
    def _validate_bootstrap_lock(
        root_descriptor: int,
        descriptor: int,
        *,
        expected_device: int,
    ) -> None:
        try:
            descriptor_stat = os.fstat(descriptor)
            path_stat = os.stat(
                _STORE_BOOTSTRAP_LOCK_FILE,
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
        except OSError:
            raise ArtifactStoreError("artifact store bootstrap lock is unavailable") from None
        if (
            not _safe_private_regular(descriptor_stat, device=expected_device)
            or _identity(path_stat) != _identity(descriptor_stat)
        ):
            raise ArtifactStoreError("artifact store bootstrap lock is unavailable")

    def _bootstrap_generation_marker(
        self,
        root_descriptor: int,
        *,
        expected_device: int,
    ) -> None:
        if not self._can_bootstrap_generation_marker(
            root_descriptor,
            expected_device=expected_device,
        ):
            raise ArtifactStoreError("artifact store generation is unavailable")
        temp_name = f".{_STORE_GENERATION_FILE}.{uuid4().hex}.tmp"
        temp_descriptor: int | None = None
        published_identity: tuple[int, int] | None = None
        renamed = False
        complete = False
        try:
            temp_descriptor = os.open(
                temp_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=root_descriptor,
            )
            os.fchmod(temp_descriptor, 0o600)
            _write_all(temp_descriptor, f"gen_{uuid4().hex}\n".encode("ascii"))
            self._fsync_descriptor(temp_descriptor)
            temp_stat = os.fstat(temp_descriptor)
            if not _safe_private_regular(temp_stat, device=expected_device):
                raise ArtifactStoreError("artifact store generation is unavailable")
            published_identity = _identity(temp_stat)
            os.replace(
                temp_name,
                _STORE_GENERATION_FILE,
                src_dir_fd=root_descriptor,
                dst_dir_fd=root_descriptor,
            )
            renamed = True
            marker_stat = os.stat(
                _STORE_GENERATION_FILE,
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
            if _identity(marker_stat) != published_identity:
                raise ArtifactStoreError("artifact store generation is unavailable")
            self._fsync_descriptor(root_descriptor)
            complete = True
            return
        except ArtifactStoreError:
            raise
        except Exception:
            raise ArtifactStoreError("artifact store generation is unavailable") from None
        finally:
            if temp_descriptor is not None:
                self._close_descriptor(temp_descriptor)
            if renamed and not complete and published_identity is not None:
                try:
                    current = os.stat(
                        _STORE_GENERATION_FILE,
                        dir_fd=root_descriptor,
                        follow_symlinks=False,
                    )
                except OSError:
                    current = None
                if current is not None and _identity(current) == published_identity:
                    try:
                        os.unlink(_STORE_GENERATION_FILE, dir_fd=root_descriptor)
                    except OSError:
                        pass
            try:
                os.unlink(temp_name, dir_fd=root_descriptor)
            except OSError:
                pass
            if not complete:
                try:
                    self._fsync_descriptor(root_descriptor)
                except OSError:
                    pass

    def _can_bootstrap_generation_marker(
        self,
        root_descriptor: int,
        *,
        expected_device: int,
    ) -> bool:
        if self._has_storage_shard_entry(root_descriptor):
            return False
        try:
            marker_stat = os.stat(
                _STORE_GENERATION_FILE,
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return True
        except OSError:
            return False
        return _safe_private_regular(marker_stat, device=expected_device)

    @staticmethod
    def _generation_marker_is_missing(root_descriptor: int) -> bool:
        try:
            os.stat(
                _STORE_GENERATION_FILE,
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return True
        except OSError:
            return False
        return False

    @staticmethod
    def _has_storage_shard_entry(root_descriptor: int) -> bool:
        try:
            with os.scandir(root_descriptor) as entries:
                return any(_SHARD.fullmatch(entry.name) for entry in entries)
        except OSError:
            raise ArtifactStoreError("artifact storage layout is unavailable") from None

    @staticmethod
    def _read_generation(descriptor: int) -> str:
        try:
            raw = os.pread(descriptor, 128, 0)
            value = raw.decode("ascii").strip()
        except Exception:
            raise ArtifactStoreError("artifact store generation is unavailable") from None
        if not _STORE_GENERATION.fullmatch(value):
            raise ArtifactStoreError("artifact store generation is unavailable")
        return value

    def _open_storage_leaf(
        self,
        root_descriptor: int,
        storage_key: str,
        *,
        expected_device: int,
        create: bool,
    ) -> int | None:
        first_descriptor = self._open_or_create_child_directory(
            root_descriptor,
            storage_key[4:6],
            expected_device=expected_device,
            create=create,
        )
        if first_descriptor is None:
            return None
        try:
            return self._open_or_create_child_directory(
                first_descriptor,
                storage_key[6:8],
                expected_device=expected_device,
                create=create,
            )
        finally:
            self._close_descriptor(first_descriptor)

    def _open_or_create_child_directory(
        self,
        parent_descriptor: int,
        name: str,
        *,
        expected_device: int,
        create: bool,
    ) -> int | None:
        if not _SHARD.fullmatch(name):
            raise ArtifactStoreError("artifact storage layout is unsafe")
        try:
            child_stat = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            if not create:
                return None
            try:
                os.mkdir(name, 0o700, dir_fd=parent_descriptor)
                self._fsync_descriptor(parent_descriptor)
            except FileExistsError:
                pass
            child_stat = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if (
            not stat.S_ISDIR(child_stat.st_mode)
            or int(child_stat.st_dev) != expected_device
        ):
            raise ArtifactStoreError("artifact storage layout is unsafe")
        try:
            descriptor = os.open(
                name,
                self._directory_open_flags(),
                dir_fd=parent_descriptor,
            )
        except Exception:
            raise ArtifactStoreError("artifact storage layout is unsafe") from None
        opened_stat = os.fstat(descriptor)
        if (
            _identity(opened_stat) != _identity(child_stat)
            or not stat.S_ISDIR(opened_stat.st_mode)
            or int(opened_stat.st_dev) != expected_device
        ):
            self._close_descriptor(descriptor)
            raise ArtifactStoreError("artifact storage layout is unsafe")
        return descriptor

    def _open_versioned_object(
        self,
        root_descriptor: int,
        storage_key: str,
        *,
        store_generation: str,
    ) -> tuple[int, int, str] | None:
        root_device = int(os.fstat(root_descriptor).st_dev)
        first_descriptor = self._open_or_create_child_directory(
            root_descriptor,
            storage_key[4:6],
            expected_device=root_device,
            create=False,
        )
        if first_descriptor is None:
            return None
        leaf_descriptor: int | None = None
        try:
            leaf_descriptor = self._open_or_create_child_directory(
                first_descriptor,
                storage_key[6:8],
                expected_device=root_device,
                create=False,
            )
            if leaf_descriptor is None:
                self._close_descriptor(first_descriptor)
                return None
            version = self._object_version_from_descriptors(
                root_descriptor,
                first_descriptor,
                leaf_descriptor,
                storage_key,
                store_generation=store_generation,
            )
            if version is None:
                self._close_descriptor(leaf_descriptor)
                self._close_descriptor(first_descriptor)
                return None
            return first_descriptor, leaf_descriptor, version
        except BaseException:
            if leaf_descriptor is not None:
                self._close_descriptor(leaf_descriptor)
            self._close_descriptor(first_descriptor)
            raise

    def _open_deepest_storage_directory(
        self,
        root_descriptor: int,
        storage_key: str,
    ) -> tuple[int, tuple[int, ...]]:
        root_device = int(os.fstat(root_descriptor).st_dev)
        first_descriptor = self._open_or_create_child_directory(
            root_descriptor,
            storage_key[4:6],
            expected_device=root_device,
            create=False,
        )
        if first_descriptor is None:
            return root_descriptor, ()
        try:
            leaf_descriptor = self._open_or_create_child_directory(
                first_descriptor,
                storage_key[6:8],
                expected_device=root_device,
                create=False,
            )
        except BaseException:
            self._close_descriptor(first_descriptor)
            raise
        if leaf_descriptor is None:
            return first_descriptor, (first_descriptor,)
        return leaf_descriptor, (first_descriptor, leaf_descriptor)

    def _missing_directory_chain_is_safe(
        self,
        root_descriptor: int,
        storage_key: str,
        owned_descriptors: tuple[int, ...],
    ) -> bool:
        descriptors = (root_descriptor, *owned_descriptors)
        try:
            if not all(
                _safe_reconciliation_directory(os.fstat(descriptor))
                for descriptor in descriptors
            ):
                return False
            if owned_descriptors:
                first_path_stat = os.stat(
                    storage_key[4:6],
                    dir_fd=root_descriptor,
                    follow_symlinks=False,
                )
                if _identity(first_path_stat) != _identity(
                    os.fstat(owned_descriptors[0])
                ):
                    return False
            if len(owned_descriptors) == 2:
                leaf_path_stat = os.stat(
                    storage_key[6:8],
                    dir_fd=owned_descriptors[0],
                    follow_symlinks=False,
                )
                if _identity(leaf_path_stat) != _identity(
                    os.fstat(owned_descriptors[1])
                ):
                    return False
        except OSError:
            return False
        return True

    def _object_version_from_descriptors(
        self,
        root_descriptor: int,
        first_descriptor: int,
        leaf_descriptor: int,
        storage_key: str,
        *,
        store_generation: str,
    ) -> str | None:
        try:
            storage_stat = os.stat(
                storage_key,
                dir_fd=leaf_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return None
        root_stat = os.fstat(root_descriptor)
        first_stat = os.fstat(first_descriptor)
        leaf_stat = os.fstat(leaf_descriptor)
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or not stat.S_ISDIR(first_stat.st_mode)
            or not stat.S_ISDIR(leaf_stat.st_mode)
            or not stat.S_ISREG(storage_stat.st_mode)
            or int(storage_stat.st_nlink) != 1
            or any(
                int(item.st_dev) != int(root_stat.st_dev)
                for item in (first_stat, leaf_stat, storage_stat)
            )
        ):
            raise ArtifactStoreError("artifact storage layout is unsafe")
        return _object_version(
            storage_key,
            store_generation,
            root_stat,
            first_stat,
            leaf_stat,
            storage_stat,
        )

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

    @staticmethod
    def _fsync_descriptor(descriptor: int) -> None:
        os.fsync(descriptor)

    def _fsync_publication_directory(self, descriptor: int) -> None:
        self._fsync_descriptor(descriptor)

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


def _identity(value: os.stat_result) -> tuple[int, int]:
    return int(value.st_dev), int(value.st_ino)


def _safe_private_regular(value: os.stat_result, *, device: int) -> bool:
    return (
        stat.S_ISREG(value.st_mode)
        and int(value.st_dev) == int(device)
        and int(value.st_nlink) == 1
        and int(value.st_uid) == int(os.geteuid())
        and stat.S_IMODE(value.st_mode) == 0o600
    )


def _safe_reconciliation_directory(value: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(value.st_mode)
        and int(value.st_uid) == int(os.geteuid())
        and stat.S_IMODE(value.st_mode) & 0o022 == 0
    )


def _safe_reconciliation_file(value: os.stat_result, *, device: int) -> bool:
    return (
        stat.S_ISREG(value.st_mode)
        and int(value.st_dev) == int(device)
        and int(value.st_nlink) == 1
        and int(value.st_uid) == int(os.geteuid())
        and stat.S_IMODE(value.st_mode) & 0o022 == 0
    )


def _stat_fields(value: os.stat_result) -> tuple[int, ...]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
        int(value.st_mode),
        int(value.st_uid),
        int(value.st_gid),
        int(value.st_nlink),
    )


def _object_version(
    storage_key: str,
    store_generation: str,
    *identities: os.stat_result,
) -> str:
    values = ["artifact-object-version.v1", store_generation, storage_key]
    directories = identities[:3]
    storage_stat = identities[3]
    for label, identity in zip(
        ("root", "first_shard", "second_shard"),
        directories,
        strict=True,
    ):
        values.append(label)
        values.extend(str(value) for value in _identity(identity))
    values.append("object")
    values.extend(str(value) for value in _stat_fields(storage_stat))
    return hashlib.sha256("\x1f".join(values).encode("ascii")).hexdigest()


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("artifact write failed")
        view = view[written:]


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
