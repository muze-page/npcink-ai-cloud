from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import socket
import stat
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.engine import URL

DEFAULT_CONFIG_DIR = Path("/run/npcink-config")
RUNTIME_CONFIG_FILE = "runtime-config.json"
INSTALL_STATE_FILE = "install-state.json"
RDS_CA_FILE = "rds-ca.pem"
FRONTEND_INTERNAL_TOKEN_FILE = "frontend/internal-auth-token"
SETUP_REVISION = "first-install-v1"

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PRODUCTION_ENVIRONMENTS = {"production", "prod", "staging"}
_PRODUCTION_RUNTIME_ENV_KEYS = {
    "NPCINK_CLOUD_DATABASE_URL",
    "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN",
    "NPCINK_CLOUD_ADMIN_KEY",
    "NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN",
    "NPCINK_CLOUD_ADMIN_KEY_SHA256",
    "NPCINK_CLOUD_ADMIN_SESSION_SECRET",
    "NPCINK_CLOUD_SERVICE_SETTINGS_SECRET",
    "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID",
    "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET",
    "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID",
    "NPCINK_CLOUD_PORTAL_JWT_SECRET",
}


class RuntimeConfigError(RuntimeError):
    """Raised when the protected first-install configuration is unavailable or invalid."""


def resolve_private_database_address(host: str, port: int) -> str:
    try:
        candidates = socket.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except OSError as error:
        raise RuntimeConfigError("runtime database hostname could not be resolved") from error
    addresses = sorted({str(candidate[4][0]) for candidate in candidates})
    if not addresses:
        raise RuntimeConfigError("runtime database hostname could not be resolved")
    parsed: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for raw_address in addresses:
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as error:
            raise RuntimeConfigError("runtime database hostname resolution is invalid") from error
        if (
            not address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_unspecified
            or address.is_reserved
        ):
            raise RuntimeConfigError(
                "runtime database hostname must resolve only to private addresses"
            )
        parsed.append(address)
    return parsed[0].compressed


def config_dir_from_environment() -> Path:
    raw = str(os.environ.get("NPCINK_CLOUD_CONFIG_DIR") or "").strip()
    return Path(raw) if raw else DEFAULT_CONFIG_DIR


def environment_from_environment() -> str:
    return str(os.environ.get("NPCINK_CLOUD_ENVIRONMENT") or "development").strip().lower()


def production_runtime_enabled() -> bool:
    return environment_from_environment() in _PRODUCTION_ENVIRONMENTS


def runtime_config_path(config_dir: Path | None = None) -> Path:
    return (config_dir or config_dir_from_environment()) / RUNTIME_CONFIG_FILE


def install_state_path(config_dir: Path | None = None) -> Path:
    return (config_dir or config_dir_from_environment()) / INSTALL_STATE_FILE


def rds_ca_path(config_dir: Path | None = None) -> Path:
    return (config_dir or config_dir_from_environment()) / RDS_CA_FILE


def internal_auth_token_path(config_dir: Path | None = None) -> Path:
    return (config_dir or config_dir_from_environment()) / FRONTEND_INTERNAL_TOKEN_FILE


def read_internal_auth_token(config_dir: Path | None = None) -> str:
    path = internal_auth_token_path(config_dir)
    value = _read_secret_text(path)
    if len(value) < 32:
        raise RuntimeConfigError("internal auth token projection is invalid")
    return value


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def runtime_config_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def configure_alembic_database_url(alembic_config: Any, database_url: str) -> None:
    """Set a runtime URL without exposing ConfigParser interpolation failures."""
    try:
        alembic_config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    except Exception:
        raise RuntimeConfigError("migration database configuration is invalid") from None


def build_database_url(
    database: dict[str, Any],
    *,
    ca_path: Path,
    hostaddr: str | None = None,
) -> str:
    query = {
        "sslmode": "verify-full",
        "sslrootcert": str(ca_path),
        "connect_timeout": "5",
    }
    if hostaddr:
        query["hostaddr"] = hostaddr
    return URL.create(
        drivername="postgresql+psycopg",
        username=_required_string(database, "username"),
        password=_required_string(database, "password"),
        host=_required_string(database, "host"),
        port=_required_int(database, "port", minimum=1, maximum=65535),
        database=_required_string(database, "database"),
        query=query,
    ).render_as_string(hide_password=False)


def load_runtime_settings_values(
    config_dir: Path | None = None,
    *,
    require_complete: bool = True,
) -> dict[str, Any]:
    directory = config_dir or config_dir_from_environment()
    _validate_config_directory(directory)
    if production_runtime_enabled():
        duplicates = sorted(key for key in _PRODUCTION_RUNTIME_ENV_KEYS if os.environ.get(key))
        if duplicates:
            raise RuntimeConfigError(
                "production runtime secrets must not be duplicated in environment variables"
            )

    runtime_path = runtime_config_path(directory)
    try:
        runtime_bytes = runtime_path.read_bytes()
    except OSError as error:
        raise RuntimeConfigError("runtime configuration could not be read") from error
    if require_complete:
        state_payload = _read_json_object(install_state_path(directory), secret=False)
        if state_payload.get("installation_state") != "complete" or state_payload.get(
            "database_contract"
        ) != "pg18_empty_initialization.v1":
            raise RuntimeConfigError("completed installation evidence is unavailable")
        observed_digest = hashlib.sha256(runtime_bytes).hexdigest()
        expected_digest = str(state_payload.get("config_digest") or "")
        transition = str(state_payload.get("config_transition") or "")
        previous_digest = str(state_payload.get("previous_config_digest") or "")
        accepted_digests = [expected_digest]
        if transition or previous_digest:
            if (
                transition != "admin_key_rotation.v1"
                or _SHA256_PATTERN.fullmatch(previous_digest) is None
                or previous_digest == expected_digest
            ):
                raise RuntimeConfigError("runtime configuration transition is invalid")
            accepted_digests.append(previous_digest)
        if not any(
            hmac.compare_digest(observed_digest, candidate)
            for candidate in accepted_digests
        ):
            raise RuntimeConfigError("runtime configuration digest is invalid")
    payload = _read_json_object(runtime_path, secret=True)
    if payload.get("config_version") != "runtime-config-v1":
        raise RuntimeConfigError("runtime configuration version is invalid")
    cloud = _required_object(payload, "cloud")
    database = _required_object(payload, "database")
    security = _required_object(payload, "security")

    public_base_url = _required_string(cloud, "public_base_url")
    parsed = urlsplit(public_base_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise RuntimeConfigError("runtime public base URL is invalid")

    if _required_string(database, "ssl_mode") != "verify-full":
        raise RuntimeConfigError("runtime database TLS mode is invalid")
    database_host = _required_string(database, "host")
    database_port = _required_int(database, "port", minimum=1, maximum=65535)
    database_hostaddr = resolve_private_database_address(database_host, database_port)
    configured_ca_digest = _required_string(database, "ca_sha256")
    ca_bytes = _read_protected_bytes(
        rds_ca_path(directory),
        expected_mode=0o600,
        label="runtime database CA",
    )
    observed_ca_digest = hashlib.sha256(ca_bytes).hexdigest()
    if (
        _SHA256_PATTERN.fullmatch(configured_ca_digest) is None
        or configured_ca_digest != observed_ca_digest
    ):
        raise RuntimeConfigError("runtime database CA digest is invalid")
    internal_token_file = _required_string(security, "internal_auth_token_file")
    if internal_token_file != FRONTEND_INTERNAL_TOKEN_FILE:
        raise RuntimeConfigError("runtime internal auth token projection is invalid")
    admin_key_sha256 = _required_string(security, "admin_key_sha256")
    if _SHA256_PATTERN.fullmatch(admin_key_sha256) is None:
        raise RuntimeConfigError("runtime admin key digest is invalid")

    hostname = str(parsed.hostname).lower()
    trusted_host = hostname if parsed.port is None else f"{hostname}:{parsed.port}"
    return {
        "_env_file": None,
        "project_name": _required_string(cloud, "name"),
        "environment": "production",
        "database_url": build_database_url(
            database,
            ca_path=rds_ca_path(directory),
            hostaddr=database_hostaddr,
        ),
        "internal_auth_token": read_internal_auth_token(directory),
        "admin_key_sha256": admin_key_sha256,
        "admin_session_secret": _required_string(security, "admin_session_secret"),
        "service_settings_secret": _required_string(security, "service_settings_secret"),
        "service_settings_encryption_key_id": _required_string(
            security, "service_settings_encryption_key_id"
        ),
        "runtime_data_encryption_secret": _required_string(
            security, "runtime_data_encryption_secret"
        ),
        "runtime_data_encryption_key_id": _required_string(
            security, "runtime_data_encryption_key_id"
        ),
        "portal_jwt_secret": _required_string(security, "portal_jwt_secret"),
        "browser_origin_allowlist": public_base_url.rstrip("/"),
        "trusted_host_allowlist": trusted_host,
        "database_pool_size": 2,
        "database_max_overflow": 1,
        "database_pool_timeout_seconds": 10,
        "database_pool_recycle_seconds": 1800,
        "database_connect_timeout_seconds": 5,
    }


def _read_json_object(path: Path, *, secret: bool) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        if not path.is_file() or path.is_symlink():
            raise RuntimeConfigError("protected configuration file is invalid")
        if secret and metadata.st_mode & 0o077:
            raise RuntimeConfigError("protected configuration permissions are too broad")
        if not secret and metadata.st_mode & 0o027:
            raise RuntimeConfigError("protected configuration permissions are too broad")
        raw = path.read_bytes()
        payload = json.loads(raw)
    except RuntimeConfigError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeConfigError("protected configuration could not be read") from error
    if not isinstance(payload, dict):
        raise RuntimeConfigError("protected configuration must be an object")
    return payload


def _validate_config_directory(directory: Path) -> None:
    try:
        metadata = directory.lstat()
        if directory.is_symlink() or not directory.is_dir() or metadata.st_mode & 0o077:
            raise RuntimeConfigError("protected configuration directory is invalid")
    except RuntimeConfigError:
        raise
    except OSError as error:
        raise RuntimeConfigError("protected configuration directory is unavailable") from error


def _read_secret_text(path: Path) -> str:
    try:
        _validate_projection_directory(path.parent)
        raw = _read_protected_bytes(
            path,
            expected_mode=0o640,
            label="protected secret projection",
        ).decode("utf-8")
    except RuntimeConfigError:
        raise
    except UnicodeDecodeError as error:
        raise RuntimeConfigError("protected secret projection could not be read") from error
    value = raw.strip()
    if not value or "\n" in value or "\r" in value:
        raise RuntimeConfigError("protected secret projection is invalid")
    return value


def _validate_projection_directory(directory: Path) -> None:
    try:
        metadata = directory.lstat()
        if (
            directory.is_symlink()
            or not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o750
            or metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
        ):
            raise RuntimeConfigError("protected secret projection directory is invalid")
    except RuntimeConfigError:
        raise
    except OSError as error:
        raise RuntimeConfigError(
            "protected secret projection directory is unavailable"
        ) from error


def _read_protected_bytes(path: Path, *, expected_mode: int, label: str) -> bytes:
    descriptor = -1
    try:
        path_metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(path_metadata.st_mode):
            raise RuntimeConfigError(f"{label} file is invalid")
        descriptor = os.open(
            path,
            os.O_RDONLY
            | os.O_CLOEXEC
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or (metadata.st_dev, metadata.st_ino)
            != (path_metadata.st_dev, path_metadata.st_ino)
        ):
            raise RuntimeConfigError(f"{label} file is invalid")
        if stat.S_IMODE(metadata.st_mode) != expected_mode:
            raise RuntimeConfigError(f"{label} permissions are invalid")
        if metadata.st_uid != os.geteuid() or metadata.st_gid != os.getegid():
            raise RuntimeConfigError(f"{label} owner is invalid")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            return stream.read()
    except RuntimeConfigError:
        raise
    except OSError as error:
        raise RuntimeConfigError(f"{label} could not be read") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _required_object(payload: dict[str, Any], name: str) -> dict[str, Any]:
    value = payload.get(name)
    if not isinstance(value, dict):
        raise RuntimeConfigError(f"runtime configuration {name} is invalid")
    return value


def _required_string(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value or value != value.strip():
        raise RuntimeConfigError(f"runtime configuration {name} is invalid")
    return value


def _required_int(
    payload: dict[str, Any],
    name: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise RuntimeConfigError(f"runtime configuration {name} is invalid")
    return value
