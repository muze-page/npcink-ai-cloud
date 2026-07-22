#!/usr/bin/env bash
set -euo pipefail
set +x

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"
RELEASE_TOOL_PYTHON="${NPCINK_CLOUD_RELEASE_TOOL_PYTHON:-/usr/bin/python3.11}"
npcink_ai_cloud_require_host_release_tool_python "${RELEASE_TOOL_PYTHON}"
export NPCINK_CLOUD_RELEASE_TOOL_PYTHON="${RELEASE_TOOL_PYTHON}"
RELEASE_NAME="${ROOT_DIR##*/}"
if [[ ! "${RELEASE_NAME}" =~ ^release-[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
	echo "[fail] First-install preparation must run from a direct managed release-* directory." >&2
	exit 1
fi
MANAGED_ROOT="$(cd "${ROOT_DIR}/.." && pwd -P)"
if [ "${ROOT_DIR}" != "${MANAGED_ROOT}/${RELEASE_NAME}" ]; then
	echo "[fail] First-install release layout is not canonical." >&2
	exit 1
fi
CURRENT_LINK="${MANAGED_ROOT}/current"
CONFIG_DIR="${NPCINK_CLOUD_CONFIG_DIR_HOST:-${MANAGED_ROOT}/shared/config}"
MODE="initialize"

case "${1:-}" in
	"") ;;
	--rotate) MODE="rotate" ;;
	*) echo "Usage: prepare-first-install.sh [--rotate]" >&2; exit 64 ;;
esac

if [ "${EUID}" -ne 0 ]; then
	echo "[fail] First-install preparation requires the root production operator." >&2
	exit 1
fi
if [ "${MODE}" = "rotate" ]; then
	if [ ! -t 1 ]; then
		echo "[fail] Setup-code rotation requires an interactive TTY; refusing to expose plaintext to captured output." >&2
		exit 1
	fi
fi

if [[ "${CONFIG_DIR}" != /* ]]; then
	echo "[fail] NPCINK_CLOUD_CONFIG_DIR_HOST must be an absolute path." >&2
	exit 64
fi
if [ "$(readlink -f "${CONFIG_DIR}" 2>/dev/null || printf '%s' "${CONFIG_DIR}")" != "${MANAGED_ROOT}/shared/config" ]; then
	echo "[fail] First-install preparation requires the canonical shared/config path." >&2
	exit 1
fi
if [ "$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)" != "${ROOT_DIR}" ] && \
	[ "${NPCINK_CLOUD_INSTALL_LOCK_HELD:-0}" != "1" ]; then
	echo "[fail] First-install preparation must run from the active managed release." >&2
	exit 1
fi
if [ "$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)" != "${ROOT_DIR}" ]; then
	npcink_ai_cloud_require_deploy_lock_owner "${ROOT_DIR}" || {
		echo "[fail] Pre-current first-install preparation requires the active deployment-lock owner proof." >&2
		exit 1
	}
fi
if [ "${MODE}" = "rotate" ] && \
	[ "$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)" != "${ROOT_DIR}" ]; then
	echo "[fail] Setup-code rotation must run from the active managed release." >&2
	exit 1
fi
if [ -e "${MANAGED_ROOT}/.installation-complete" ] || \
	[ -L "${MANAGED_ROOT}/.installation-complete" ]; then
	echo "[fail] Completed-installation sentinel exists; setup authentication cannot be recreated." >&2
	exit 1
fi
if [ -e "${MANAGED_ROOT}/.first-install-pending.json" ] || \
	[ -L "${MANAGED_ROOT}/.first-install-pending.json" ]; then
	"${RELEASE_TOOL_PYTHON}" - "${MANAGED_ROOT}/.first-install-pending.json" "${ROOT_DIR}" <<'PY'
import json
import os
import stat
import sys
from pathlib import Path

marker_path = Path(sys.argv[1])
release = Path(sys.argv[2])
metadata = marker_path.lstat()
if (
    marker_path.is_symlink()
    or not stat.S_ISREG(metadata.st_mode)
    or stat.S_IMODE(metadata.st_mode) != 0o600
    or (metadata.st_uid, metadata.st_gid) != (0, 0)
):
    raise SystemExit("[fail] First-install lifecycle marker is unsafe.")
payload = json.loads(marker_path.read_text(encoding="utf-8"))
if payload.get("contract") != "first_install_pending.v1" or Path(str(payload.get("release") or "")) != release:
    raise SystemExit("[fail] First-install lifecycle marker does not authorize this release.")
PY
fi

"${RELEASE_TOOL_PYTHON}" - "${CONFIG_DIR}" "${MODE}" <<'PY'
from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import secrets
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"[fail] {message}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def token(prefix: str) -> str:
    return prefix + base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


def atomic_json(path: Path, payload: dict[str, object], mode: int) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode, follow_symlinks=False)
        if os.geteuid() == 0:
            os.chown(temporary, 999, 999, follow_symlinks=False)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


config_dir = Path(sys.argv[1])
mode = sys.argv[2]
if config_dir != Path(os.path.abspath(config_dir)) or config_dir == Path("/"):
    fail("configuration directory must be a non-root canonical absolute path")

config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
metadata = config_dir.lstat()
if not stat.S_ISDIR(metadata.st_mode) or config_dir.is_symlink():
    fail("configuration path must be a real directory")
if os.geteuid() == 0:
    os.chown(config_dir, 999, 999, follow_symlinks=False)
os.chmod(config_dir, 0o700)

# Setup and deployment share this inode lock. The deployment entrypoint may
# already hold it across the complete cutover; direct prepare/rotate calls keep
# this descriptor open for every state/auth mutation below.
lock_path = config_dir / ".install.lock"


def validate_lock_descriptor(descriptor: int) -> None:
    descriptor_metadata = os.fstat(descriptor)
    path_metadata = os.lstat(lock_path)
    if not stat.S_ISREG(descriptor_metadata.st_mode):
        fail("setup/deployment lock fd must reference a regular file")
    if lock_path.is_symlink() or not stat.S_ISREG(path_metadata.st_mode):
        fail("setup/deployment lock path must be a regular non-symlink file")
    if (descriptor_metadata.st_dev, descriptor_metadata.st_ino) != (
        path_metadata.st_dev,
        path_metadata.st_ino,
    ):
        fail("setup/deployment lock fd does not match the canonical lock path")
    if (
        (descriptor_metadata.st_uid, descriptor_metadata.st_gid) != (999, 999)
        or stat.S_IMODE(descriptor_metadata.st_mode) != 0o600
    ):
        fail("setup/deployment lock ownership or mode is unsafe")


held_fd = os.environ.get("NPCINK_CLOUD_INSTALL_LOCK_FD", "")
if os.environ.get("NPCINK_CLOUD_INSTALL_LOCK_HELD") == "1":
    try:
        install_lock_descriptor = int(held_fd)
        validate_lock_descriptor(install_lock_descriptor)
        fcntl.flock(install_lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        validate_lock_descriptor(install_lock_descriptor)
    except (BlockingIOError, OSError, ValueError):
        fail("inherited setup/deployment lock fd is not valid and exclusively held")
else:
    flags = (
        os.O_RDWR
        | os.O_CLOEXEC
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    created = False
    try:
        install_lock_descriptor = os.open(lock_path, flags | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
    except FileExistsError:
        install_lock_descriptor = os.open(lock_path, flags)
    try:
        if created:
            os.fchmod(install_lock_descriptor, 0o600)
            if os.geteuid() == 0:
                os.fchown(install_lock_descriptor, 999, 999)
        validate_lock_descriptor(install_lock_descriptor)
        fcntl.flock(install_lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        validate_lock_descriptor(install_lock_descriptor)
    except (BlockingIOError, OSError):
        os.close(install_lock_descriptor)
        fail("a first-install operation or deployment is already active")

frontend_dir = config_dir / "frontend"
frontend_dir.mkdir(mode=0o750, exist_ok=True)
if frontend_dir.is_symlink() or not stat.S_ISDIR(frontend_dir.lstat().st_mode):
    fail("frontend secret projection path must be a real directory")
if os.geteuid() == 0:
    os.chown(frontend_dir, 999, 999, follow_symlinks=False)
os.chmod(frontend_dir, 0o750)

state_path = config_dir / "install-state.json"
auth_path = config_dir / "setup-auth.json"
runtime_artifacts = (
    config_dir / "runtime-config.json",
    config_dir / "rds-ca.pem",
    frontend_dir / "internal-auth-token",
)
state: dict[str, object] | None = None
if state_path.exists():
    if state_path.is_symlink() or not stat.S_ISREG(state_path.lstat().st_mode):
        fail("install-state.json is not a protected regular file")
    try:
        loaded = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"install-state.json is invalid: {exc}")
    if not isinstance(loaded, dict):
        fail("install-state.json must be a JSON object")
    state = loaded
elif any(path.exists() or path.is_symlink() for path in runtime_artifacts):
    fail("install-state.json is missing while runtime artifacts exist; refusing to reopen setup")

installation_state = "" if state is None else str(state.get("installation_state", ""))
if installation_state == "complete":
    fail("completed installations cannot create or rotate a setup code")
if installation_state not in {"", "pending"}:
    fail("setup code may only be managed while installation is pending")
if installation_state == "pending" and any(
    path.exists() or path.is_symlink() for path in runtime_artifacts
):
    fail("pending installation retains runtime artifacts; refusing to reopen setup")
if mode == "initialize" and state is not None:
    if not auth_path.is_file() or auth_path.is_symlink():
        fail("pending installation has no protected setup auth; use --rotate explicitly")
    print("[ok] First-install state already exists; the plaintext setup code is intentionally unavailable.")
    raise SystemExit(0)

setup_code = token("nca_setup_")
session_secret = token("")
now = utc_now()
atomic_json(
    auth_path,
    {
        "created_at": now,
        "session_secret": session_secret,
        "setup_code_sha256": hashlib.sha256(setup_code.encode("utf-8")).hexdigest(),
    },
    0o600,
)
if state is None:
    atomic_json(
        state_path,
        {
            "config_digest": "",
            "installation_state": "pending",
            "retry_allowed": True,
            "setup_revision": "first-install-v1",
            "updated_at": now,
        },
        0o640,
    )
elif mode == "rotate":
    # A new session root intentionally invalidates every old Setup cookie.
    # Request fingerprints are keyed by that root, so an explicit operator
    # rotation also resets the bounded retry fingerprint while retaining the
    # attempt ID used to recognize an interrupted Alembic installation.
    state["idempotency_key_sha256"] = ""
    state["install_request_hmac_sha256"] = ""
    state["retry_allowed"] = True
    state["updated_at"] = now
    atomic_json(state_path, state, 0o640)

if mode == "rotate":
    print("[setup-code] Save this one-time value now; only its SHA-256 digest remains on the host:")
    print(setup_code)
else:
    print("[ok] First-install authentication digest initialized without disclosing plaintext.")
    print("[info] Issue the usable setup code interactively with deploy/setup-code-rotate.sh.")
PY
