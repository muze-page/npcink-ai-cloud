#!/usr/bin/env bash
set -euo pipefail
set +x

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"
RELEASE_TOOL_PYTHON="${NPCINK_CLOUD_RELEASE_TOOL_PYTHON:-/usr/bin/python3.11}"
npcink_ai_cloud_require_host_release_tool_python "${RELEASE_TOOL_PYTHON}"
export NPCINK_CLOUD_RELEASE_TOOL_PYTHON="${RELEASE_TOOL_PYTHON}"
MANAGED_ROOT="$(npcink_ai_cloud_managed_root_for_release "${ROOT_DIR}" 1)" || exit 1
CURRENT_LINK="${MANAGED_ROOT}/current"
if [ "$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)" != "${ROOT_DIR}" ]; then
	echo "[fail] Administrator-key rotation must run from the active managed release." >&2
	exit 1
fi
CONFIG_DIR="${NPCINK_CLOUD_CONFIG_DIR_HOST:-${MANAGED_ROOT}/shared/config}"

if [[ "${CONFIG_DIR}" != /* ]] || [ "${CONFIG_DIR}" = "/" ]; then
	echo "[fail] NPCINK_CLOUD_CONFIG_DIR_HOST must be a non-root absolute path." >&2
	exit 64
fi
if [ "$(id -u)" != "0" ]; then
	echo "[fail] Administrator-key rotation requires the root production operator." >&2
	exit 1
fi
if [ ! -t 1 ]; then
	echo "[fail] Administrator-key rotation requires an interactive TTY; refusing to expose plaintext to captured output." >&2
	exit 1
fi
if [ "$(readlink -f "${CONFIG_DIR}")" != "${MANAGED_ROOT}/shared/config" ]; then
	echo "[fail] Administrator-key rotation requires the canonical shared/config path." >&2
	exit 1
fi
LOCK_DIR="${MANAGED_ROOT}/.deploy-lock"

if ! mkdir -m 0700 "${LOCK_DIR}" 2>/dev/null; then
	echo "[fail] Another deployment or administrator-key rotation is active." >&2
	exit 1
fi
if [ -L "${LOCK_DIR}" ] || [ ! -d "${LOCK_DIR}" ] || \
	[ "$(stat -c '%u:%g:%a' -- "${LOCK_DIR}")" != "0:0:700" ]; then
	rmdir "${LOCK_DIR}" >/dev/null 2>&1 || true
	echo "[fail] Shared deployment lock must be a root-owned mode-0700 directory." >&2
	exit 1
fi
API_FENCE_ACTIVE=0
API_CONTAINER_ID=""
COMPOSE_PROJECT=""

prove_api_stopped() {
	local compose_running=""
	local docker_running=""
	compose_running="$(npcink_ai_cloud_compose "${ROOT_DIR}" ps --status running -q api)" || return 1
	docker_running="$(docker container ls -q \
		--filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" \
		--filter "label=com.docker.compose.service=api")" || return 1
	if [ -n "${compose_running}" ] || [ -n "${docker_running}" ]; then
		echo "[fail] Exact Compose project still has a running API container." >&2
		return 1
	fi
}

cleanup() {
	local exit_status="$?"
	trap - EXIT
	unset ADMIN_KEY 2>/dev/null || true
	if [ "${API_FENCE_ACTIVE}" = "1" ]; then
		# Once a rotation has fenced the API, every failure remains fail-closed.
		# Do not revive either the old key/cookie session or an undisclosed new key.
		npcink_ai_cloud_compose "${ROOT_DIR}" stop -t 30 api >/dev/null 2>&1 || exit_status=1
		prove_api_stopped >/dev/null 2>&1 || exit_status=1
	fi
	if ! rmdir "${LOCK_DIR}" >/dev/null 2>&1 || [ -e "${LOCK_DIR}" ] || [ -L "${LOCK_DIR}" ]; then
		echo "[fail] Shared deployment lock could not be released: ${LOCK_DIR}" >&2
		exit_status=1
	fi
	exit "${exit_status}"
}
trap cleanup EXIT

npcink_ai_cloud_require_cmd docker
export NPCINK_CLOUD_CONFIG_DIR_HOST="${CONFIG_DIR}"
npcink_ai_cloud_load_env_file "${ROOT_DIR}"
ENV_FILE="$(npcink_ai_cloud_resolve_env_file "${ROOT_DIR}")"
if [ -z "${ENV_FILE}" ] || [ ! -f "${ENV_FILE}" ] || [ -L "${ENV_FILE}" ]; then
	echo "[fail] Active release environment authority is unavailable." >&2
	exit 1
fi
COMPOSE_PROJECT="$(npcink_ai_cloud_compose_project_name_from_env "${ENV_FILE}")"
export NPCINK_CLOUD_COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT}"
API_CONTAINER_ID="$(npcink_ai_cloud_compose "${ROOT_DIR}" ps --all -q api)"
if [[ ! "${API_CONTAINER_ID}" =~ ^[0-9a-f]{12,64}$ ]] || \
	[ "$(printf '%s\n' "${API_CONTAINER_ID}" | wc -l | tr -d ' ')" != "1" ]; then
	echo "[fail] Exact active-release API container could not be identified before rotation." >&2
	exit 1
fi
LABELED_API_CONTAINER_ID="$(docker container ls -aq --no-trunc \
	--filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" \
	--filter "label=com.docker.compose.service=api")"
if [ "${LABELED_API_CONTAINER_ID}" != "${API_CONTAINER_ID}" ]; then
	echo "[fail] Exact Compose project/service does not identify one API container." >&2
	exit 1
fi

# Establish the serving fence before touching either protected configuration
# file. A stop/proof failure therefore leaves every key and session unchanged.
API_FENCE_ACTIVE=1
echo "[info] Stopping the exact active-release API before administrator-key mutation."
npcink_ai_cloud_compose "${ROOT_DIR}" stop -t 30 api
prove_api_stopped

ADMIN_KEY="$("${RELEASE_TOOL_PYTHON}" - "${CONFIG_DIR}" <<'PY'
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path


CONFIG_FILE_UID = 999
CONFIG_FILE_GID = 999
MAX_PROTECTED_JSON_BYTES = 1024 * 1024


def fail(message: str) -> None:
    raise SystemExit(f"[fail] {message}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def token(prefix: str) -> str:
    encoded = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    return prefix + encoded


def validate_protected_metadata(
    metadata: os.stat_result,
    *,
    label: str,
    expected_mode: int,
) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        fail(f"{label} must be a regular non-symlink file")
    if (metadata.st_uid, metadata.st_gid) != (CONFIG_FILE_UID, CONFIG_FILE_GID):
        fail(f"{label} ownership is unsafe")
    if stat.S_IMODE(metadata.st_mode) != expected_mode:
        fail(f"{label} mode is unsafe")


def protected_snapshot(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def load_protected_object(
    path: Path,
    label: str,
    *,
    expected_mode: int,
) -> tuple[dict[str, object], bytes]:
    descriptor = -1
    try:
        path_metadata_before = os.lstat(path)
    except OSError as exc:
        fail(f"{label} is unavailable: {type(exc).__name__}")
    validate_protected_metadata(
        path_metadata_before,
        label=label,
        expected_mode=expected_mode,
    )
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
        descriptor_metadata_before = os.fstat(descriptor)
        validate_protected_metadata(
            descriptor_metadata_before,
            label=label,
            expected_mode=expected_mode,
        )
        if protected_snapshot(descriptor_metadata_before) != protected_snapshot(
            path_metadata_before
        ):
            fail(f"{label} changed while it was opened")

        chunks: list[bytes] = []
        observed_bytes = 0
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            observed_bytes += len(chunk)
            if observed_bytes > MAX_PROTECTED_JSON_BYTES:
                fail(f"{label} exceeds the protected configuration size limit")
            chunks.append(chunk)

        descriptor_metadata_after = os.fstat(descriptor)
        path_metadata_after = os.lstat(path)
        validate_protected_metadata(
            descriptor_metadata_after,
            label=label,
            expected_mode=expected_mode,
        )
        validate_protected_metadata(
            path_metadata_after,
            label=label,
            expected_mode=expected_mode,
        )
        expected_snapshot = protected_snapshot(descriptor_metadata_before)
        if (
            protected_snapshot(descriptor_metadata_after) != expected_snapshot
            or protected_snapshot(path_metadata_after) != expected_snapshot
        ):
            fail(f"{label} changed while it was read")
        raw = b"".join(chunks)
    except SystemExit:
        raise
    except OSError as exc:
        fail(f"{label} could not be safely read: {type(exc).__name__}")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"{label} is invalid: {type(exc).__name__}")
    if not isinstance(value, dict):
        fail(f"{label} must be a JSON object")
    return value, raw


def canonical_bytes(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def atomic_write(path: Path, payload: bytes, mode: int) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode, follow_symlinks=False)
        if os.geteuid() == 0:
            os.chown(
                temporary,
                CONFIG_FILE_UID,
                CONFIG_FILE_GID,
                follow_symlinks=False,
            )
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
if config_dir != Path(os.path.abspath(config_dir)) or config_dir == Path("/"):
    fail("configuration directory must be canonical")
if config_dir.is_symlink() or not config_dir.is_dir():
    fail("configuration directory must be a real directory")

runtime_path = config_dir / "runtime-config.json"
state_path = config_dir / "install-state.json"
runtime, runtime_bytes = load_protected_object(
    runtime_path,
    "runtime-config.json",
    expected_mode=0o600,
)
state, _ = load_protected_object(
    state_path,
    "install-state.json",
    expected_mode=0o640,
)
if (
    state.get("installation_state") != "complete"
    or state.get("database_contract") != "pg18_empty_initialization.v1"
):
    fail("administrator key may only rotate after installation is complete")
expected_digest = state.get("config_digest")
transition = state.get("config_transition", "")
previous_digest = state.get("previous_config_digest", "")
observed_digest = hashlib.sha256(runtime_bytes).hexdigest()
if (
    not isinstance(expected_digest, str)
    or len(expected_digest) != 64
    or any(character not in "0123456789abcdef" for character in expected_digest)
):
    fail("completed installation configuration digest is invalid")
accepted_digests = [expected_digest]
if transition or previous_digest:
    if (
        transition != "admin_key_rotation.v1"
        or not isinstance(previous_digest, str)
        or len(previous_digest) != 64
        or any(character not in "0123456789abcdef" for character in previous_digest)
        or previous_digest == expected_digest
    ):
        fail("administrator-key rotation transition is invalid")
    accepted_digests.append(previous_digest)
if not any(secrets.compare_digest(observed_digest, value) for value in accepted_digests):
    fail("runtime configuration digest does not match completed installation state")

# A completed installation must not retain setup authentication. Clean a
# crash-leftover only after proving the complete state and protected file
# shape; never follow or silently remove an unexpected path.
setup_auth_path = config_dir / "setup-auth.json"
if setup_auth_path.exists() or setup_auth_path.is_symlink():
    metadata = setup_auth_path.lstat()
    if (
        setup_auth_path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or (metadata.st_uid, metadata.st_gid) != (CONFIG_FILE_UID, CONFIG_FILE_GID)
    ):
        fail("completed installation retains unsafe setup authentication residue")
    setup_auth_path.unlink()
    directory_fd = os.open(config_dir, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)

security = runtime.get("security")
if not isinstance(security, dict):
    fail("runtime-config.json security section is missing")

admin_key = token("nca_admin_")
security["admin_key_sha256"] = hashlib.sha256(admin_key.encode("utf-8")).hexdigest()
security["admin_session_secret"] = token("")
runtime_bytes = canonical_bytes(runtime)

new_digest = hashlib.sha256(runtime_bytes).hexdigest()
state["config_digest"] = new_digest
state["config_transition"] = "admin_key_rotation.v1"
state["previous_config_digest"] = observed_digest
state["updated_at"] = utc_now()
transition_state_bytes = canonical_bytes(state)

# Publish a bounded dual-digest transition before replacing runtime config.
# The application accepts the observed old digest or the new target digest
# only while this marker exists, so every interruption point remains readable
# and a rerun can supersede an admin key whose plaintext was never displayed.
atomic_write(state_path, transition_state_bytes, 0o640)
atomic_write(runtime_path, runtime_bytes, 0o600)
state.pop("config_transition", None)
state.pop("previous_config_digest", None)
atomic_write(state_path, canonical_bytes(state), 0o640)
print(admin_key)
PY
)"

echo "[info] Starting the same API container with the rotated key and session secret."
npcink_ai_cloud_compose "${ROOT_DIR}" start api
STARTED_API_CONTAINER_ID="$(npcink_ai_cloud_compose "${ROOT_DIR}" ps -q api)"
if [ "${STARTED_API_CONTAINER_ID}" != "${API_CONTAINER_ID}" ]; then
	echo "[fail] Administrator-key rotation changed the exact API container identity." >&2
	exit 1
fi
npcink_ai_cloud_wait_for_internal_endpoint \
	"${ROOT_DIR}" "/health/ready" "[ok] Administrator key rotated and API is ready."

printf '%s\n' "[admin-key] Save this one-time value now; it will not be shown again:"
printf '%s\n' "${ADMIN_KEY}"
API_FENCE_ACTIVE=0
unset ADMIN_KEY
