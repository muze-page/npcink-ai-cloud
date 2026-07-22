from __future__ import annotations

import fcntl
import json
import os
import secrets
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.runtime_config import (
    FRONTEND_INTERNAL_TOKEN_FILE,
    INSTALL_STATE_FILE,
    RDS_CA_FILE,
    RUNTIME_CONFIG_FILE,
    SETUP_REVISION,
    canonical_json_bytes,
)

SETUP_AUTH_FILE = "setup-auth.json"
RETIRED_SETUP_AUTH_FILE = ".setup-auth.retired.json"
INSTALL_LOCK_FILE = ".install.lock"


class SetupStateError(RuntimeError):
    pass


class InstallationInProgressError(SetupStateError):
    pass


@dataclass(frozen=True, slots=True)
class InstallationState:
    installation_state: str
    setup_revision: str
    retry_allowed: bool
    updated_at: str
    config_digest: str = ""
    attempt_id: str = ""
    idempotency_key_sha256: str = ""
    install_request_hmac_sha256: str = ""
    database_contract: str = ""

    def public_payload(self) -> dict[str, object]:
        return {
            "installation_state": self.installation_state,
            "setup_revision": self.setup_revision,
            "retry_allowed": self.retry_allowed,
        }


@dataclass(frozen=True, slots=True)
class SetupAuth:
    setup_code_sha256: str
    session_secret: str
    created_at: str


class SetupConfigStore:
    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir

    @property
    def state_path(self) -> Path:
        return self.config_dir / INSTALL_STATE_FILE

    @property
    def setup_auth_path(self) -> Path:
        return self.config_dir / SETUP_AUTH_FILE

    @property
    def retired_setup_auth_path(self) -> Path:
        return self.config_dir / RETIRED_SETUP_AUTH_FILE

    @property
    def runtime_config_path(self) -> Path:
        return self.config_dir / RUNTIME_CONFIG_FILE

    @property
    def ca_path(self) -> Path:
        return self.config_dir / RDS_CA_FILE

    @property
    def internal_token_path(self) -> Path:
        return self.config_dir / FRONTEND_INTERNAL_TOKEN_FILE

    def read_state(self) -> InstallationState:
        self._validate_directory()
        if not self.state_path.exists():
            raise SetupStateError("installation state is missing")
        payload = self._read_json(self.state_path, secret=False)
        installation_state = str(payload.get("installation_state") or "")
        setup_revision = str(payload.get("setup_revision") or "")
        retry_allowed = payload.get("retry_allowed")
        if (
            installation_state not in {"pending", "initializing", "complete"}
            or setup_revision != SETUP_REVISION
            or not isinstance(retry_allowed, bool)
        ):
            raise SetupStateError("installation state is invalid")
        config_digest = str(payload.get("config_digest") or "")
        idempotency_key_sha256 = str(payload.get("idempotency_key_sha256") or "")
        install_request_hmac_sha256 = str(payload.get("install_request_hmac_sha256") or "")
        database_contract = str(payload.get("database_contract") or "")
        config_transition = str(payload.get("config_transition") or "")
        previous_config_digest = str(payload.get("previous_config_digest") or "")
        if idempotency_key_sha256 and (
            len(idempotency_key_sha256) != 64
            or any(character not in "0123456789abcdef" for character in idempotency_key_sha256)
        ):
            raise SetupStateError("installation idempotency evidence is invalid")
        if install_request_hmac_sha256 and (
            len(install_request_hmac_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in install_request_hmac_sha256
            )
        ):
            raise SetupStateError("installation request evidence is invalid")
        if installation_state == "complete" and (
            len(config_digest) != 64
            or any(character not in "0123456789abcdef" for character in config_digest)
            or database_contract != "pg18_empty_initialization.v1"
        ):
            raise SetupStateError("completed installation evidence is invalid")
        if config_transition or previous_config_digest:
            if (
                installation_state != "complete"
                or config_transition != "admin_key_rotation.v1"
                or len(previous_config_digest) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in previous_config_digest
                )
                or previous_config_digest == config_digest
            ):
                raise SetupStateError("runtime configuration transition is invalid")
        if installation_state != "complete" and database_contract:
            raise SetupStateError("pending installation evidence is invalid")
        if installation_state == "pending" and self._has_runtime_artifacts():
            raise SetupStateError(
                "pending installation cannot retain runtime artifacts"
            )
        return InstallationState(
            installation_state=installation_state,
            setup_revision=setup_revision,
            retry_allowed=retry_allowed,
            updated_at=str(payload.get("updated_at") or ""),
            config_digest=config_digest,
            attempt_id=str(payload.get("attempt_id") or ""),
            idempotency_key_sha256=idempotency_key_sha256,
            install_request_hmac_sha256=install_request_hmac_sha256,
            database_contract=database_contract,
        )

    def read_setup_auth(self) -> SetupAuth:
        self._validate_directory()
        payload = self._read_json(self.setup_auth_path, secret=True)
        digest = str(payload.get("setup_code_sha256") or "")
        session_secret = str(payload.get("session_secret") or "")
        created_at = str(payload.get("created_at") or "")
        if (
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or len(session_secret) != 43
            or not created_at
        ):
            raise SetupStateError("setup authentication is invalid")
        return SetupAuth(digest, session_secret, created_at)

    def mark_initializing(
        self,
        *,
        attempt_id: str,
        idempotency_key_sha256: str,
        install_request_hmac_sha256: str,
    ) -> InstallationState:
        state = InstallationState(
            installation_state="initializing",
            setup_revision=SETUP_REVISION,
            retry_allowed=False,
            updated_at=_utc_now(),
            attempt_id=attempt_id,
            idempotency_key_sha256=idempotency_key_sha256,
            install_request_hmac_sha256=install_request_hmac_sha256,
        )
        self.write_state(state)
        return state

    def mark_pending(
        self,
        *,
        attempt_id: str = "",
        idempotency_key_sha256: str = "",
        install_request_hmac_sha256: str = "",
    ) -> InstallationState:
        state = InstallationState(
            installation_state="pending",
            setup_revision=SETUP_REVISION,
            retry_allowed=True,
            updated_at=_utc_now(),
            attempt_id=attempt_id,
            idempotency_key_sha256=idempotency_key_sha256,
            install_request_hmac_sha256=install_request_hmac_sha256,
        )
        self.write_state(state)
        return state

    def mark_complete(self, *, config_digest: str) -> InstallationState:
        state = InstallationState(
            installation_state="complete",
            setup_revision=SETUP_REVISION,
            retry_allowed=False,
            updated_at=_utc_now(),
            config_digest=config_digest,
            database_contract="pg18_empty_initialization.v1",
        )
        self.write_state(state)
        return state

    def write_state(self, state: InstallationState) -> None:
        self.atomic_write_json(
            self.state_path,
            {
                "installation_state": state.installation_state,
                "setup_revision": state.setup_revision,
                "retry_allowed": state.retry_allowed,
                "updated_at": state.updated_at,
                "config_digest": state.config_digest,
                "attempt_id": state.attempt_id,
                "idempotency_key_sha256": state.idempotency_key_sha256,
                "install_request_hmac_sha256": state.install_request_hmac_sha256,
                "database_contract": state.database_contract,
            },
            mode=0o640,
        )

    def write_runtime_config(self, payload: dict[str, Any]) -> None:
        self.atomic_write_json(self.runtime_config_path, payload, mode=0o600)

    def write_ca(self, ca_pem: str) -> None:
        self.atomic_write_bytes(self.ca_path, ca_pem.encode("utf-8"), mode=0o600)

    def write_internal_auth_token(self, token: str) -> None:
        parent = self.internal_token_path.parent
        parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        os.chmod(parent, 0o750)
        self.atomic_write_bytes(self.internal_token_path, token.encode("utf-8"), mode=0o640)

    def retire_setup_auth(self) -> None:
        self._validate_directory()
        active_exists = self._path_exists(self.setup_auth_path)
        retired_exists = self._path_exists(self.retired_setup_auth_path)
        if retired_exists:
            self._read_json(self.retired_setup_auth_path, secret=True)
            if active_exists:
                raise SetupStateError("setup authentication retirement is ambiguous")
            return
        if not active_exists:
            raise SetupStateError("setup authentication is unavailable")
        self._read_json(self.setup_auth_path, secret=True)
        self._replace_and_fsync(self.setup_auth_path, self.retired_setup_auth_path)

    def restore_retired_setup_auth(self) -> None:
        self._validate_directory()
        active_exists = self._path_exists(self.setup_auth_path)
        retired_exists = self._path_exists(self.retired_setup_auth_path)
        if not retired_exists:
            if not active_exists:
                raise SetupStateError("setup authentication recovery is unavailable")
            self._read_json(self.setup_auth_path, secret=True)
            return
        self._read_json(self.retired_setup_auth_path, secret=True)
        if active_exists:
            raise SetupStateError("setup authentication recovery is ambiguous")
        self._replace_and_fsync(self.retired_setup_auth_path, self.setup_auth_path)

    def delete_retired_setup_auth(self) -> None:
        if not self._path_exists(self.retired_setup_auth_path):
            return
        self._read_json(self.retired_setup_auth_path, secret=True)
        self._unlink(self.retired_setup_auth_path)

    def delete_partial_runtime(self) -> None:
        for path in (self.runtime_config_path, self.ca_path, self.internal_token_path):
            self._unlink(path)

    def _has_runtime_artifacts(self) -> bool:
        return any(
            path.exists() or path.is_symlink()
            for path in (self.runtime_config_path, self.ca_path, self.internal_token_path)
        )

    @staticmethod
    def _path_exists(path: Path) -> bool:
        return path.exists() or path.is_symlink()

    @contextmanager
    def install_lock(self) -> Iterator[None]:
        self._validate_directory()
        lock_path = self.config_dir / INSTALL_LOCK_FILE
        descriptor = self._open_install_lock(lock_path)
        locked = False
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise InstallationInProgressError("installation is already in progress") from error
            except OSError as error:
                raise SetupStateError("installation lock is unavailable") from error
            locked = True
            self._validate_install_lock_descriptor(descriptor, lock_path)
            yield
        finally:
            try:
                if locked:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _open_install_lock(self, lock_path: Path) -> int:
        flags = (
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as error:
            raise SetupStateError("installation lock is unavailable") from error
        try:
            self._validate_install_lock_descriptor(descriptor, lock_path)
        except Exception:
            os.close(descriptor)
            raise
        return descriptor

    @staticmethod
    def _validate_install_lock_descriptor(descriptor: int, lock_path: Path) -> None:
        try:
            descriptor_metadata = os.fstat(descriptor)
            path_metadata = lock_path.lstat()
        except OSError as error:
            raise SetupStateError("installation lock is unavailable") from error
        if (
            not stat.S_ISREG(descriptor_metadata.st_mode)
            or stat.S_IMODE(descriptor_metadata.st_mode) != 0o600
            or descriptor_metadata.st_uid != os.geteuid()
            or descriptor_metadata.st_gid != os.getegid()
            or not stat.S_ISREG(path_metadata.st_mode)
            or path_metadata.st_dev != descriptor_metadata.st_dev
            or path_metadata.st_ino != descriptor_metadata.st_ino
        ):
            raise SetupStateError("installation lock is invalid")

    def atomic_write_json(self, path: Path, payload: dict[str, Any], *, mode: int) -> None:
        self.atomic_write_bytes(path, canonical_json_bytes(payload), mode=mode)

    def atomic_write_bytes(self, path: Path, content: bytes, *, mode: int) -> None:
        self._validate_directory()
        if path.parent != self.config_dir:
            path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary_path = Path(temporary_name)
        try:
            os.fchmod(descriptor, mode)
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(temporary_path, path)
            directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except Exception:
            if descriptor >= 0:
                os.close(descriptor)
            temporary_path.unlink(missing_ok=True)
            raise

    def _read_json(self, path: Path, *, secret: bool) -> dict[str, Any]:
        try:
            metadata = path.lstat()
            if path.is_symlink() or not path.is_file():
                raise SetupStateError("protected setup file is invalid")
            if secret and metadata.st_mode & 0o077:
                raise SetupStateError("protected setup file permissions are invalid")
            if not secret and metadata.st_mode & 0o027:
                raise SetupStateError("protected setup file permissions are invalid")
            payload = json.loads(path.read_bytes())
        except SetupStateError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SetupStateError("protected setup file could not be read") from error
        if not isinstance(payload, dict):
            raise SetupStateError("protected setup file must contain an object")
        return payload

    def _validate_directory(self) -> None:
        try:
            metadata = self.config_dir.lstat()
            if (
                self.config_dir.is_symlink()
                or not self.config_dir.is_dir()
                or metadata.st_mode & 0o077
            ):
                raise SetupStateError("configuration directory is invalid")
        except OSError as error:
            raise SetupStateError("configuration directory is unavailable") from error

    @staticmethod
    def _unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
            directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except FileNotFoundError:
            return

    def _replace_and_fsync(self, source: Path, target: Path) -> None:
        self._validate_directory()
        os.replace(source, target)
        directory_descriptor = os.open(self.config_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)


def new_attempt_id() -> str:
    return f"install_{secrets.token_hex(16)}"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
