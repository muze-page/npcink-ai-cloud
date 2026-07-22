#!/usr/bin/env bash
set -euo pipefail
set +x

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"

if [ "$(id -u)" != "0" ]; then
	echo "[fail] First-install finalization requires the root production operator." >&2
	exit 1
fi
RELEASE_TOOL_PYTHON="${NPCINK_CLOUD_RELEASE_TOOL_PYTHON:-/usr/bin/python3.11}"
npcink_ai_cloud_require_host_release_tool_python "${RELEASE_TOOL_PYTHON}"
export NPCINK_CLOUD_RELEASE_TOOL_PYTHON="${RELEASE_TOOL_PYTHON}"
MANAGED_ROOT="$(npcink_ai_cloud_managed_root_for_release "${ROOT_DIR}" 1)" || exit 1
CURRENT_LINK="${MANAGED_ROOT}/current"
CONFIG_DIR="${NPCINK_CLOUD_CONFIG_DIR_HOST:-${MANAGED_ROOT}/shared/config}"
PENDING_MARKER="${MANAGED_ROOT}/.first-install-pending.json"
COMPLETE_MARKER="${MANAGED_ROOT}/.installation-complete"
DEPLOY_LOCK_DIR="${MANAGED_ROOT}/.deploy-lock"

if [[ "${CONFIG_DIR}" != /* ]] || [ -L "${CONFIG_DIR}" ] || \
	[ "$(readlink -f "${CONFIG_DIR}" 2>/dev/null || true)" != "${MANAGED_ROOT}/shared/config" ]; then
	echo "[fail] Finalize requires the canonical non-symlink shared/config path." >&2
	exit 1
fi
if ! mkdir -m 0700 "${DEPLOY_LOCK_DIR}" 2>/dev/null; then
	echo "[fail] Another deployment or production mutation is active." >&2
	exit 1
fi
cleanup() {
	local status="$?"
	trap - EXIT
	npcink_ai_cloud_stop_install_lock_broker || status=1
	if ! rmdir "${DEPLOY_LOCK_DIR}" >/dev/null 2>&1; then
		echo "[fail] Deployment lock could not be released: ${DEPLOY_LOCK_DIR}" >&2
		status=1
	fi
	exit "${status}"
}
trap cleanup EXIT

npcink_ai_cloud_require_cmd docker
INSTALL_LOCK_FILE="${CONFIG_DIR}/.install.lock"
npcink_ai_cloud_start_install_lock_broker "${ROOT_DIR}" "${INSTALL_LOCK_FILE}" 0 || {
	echo "[fail] Setup installation is active; finalization will not race it." >&2
	exit 1
}
if { [ -e "${COMPLETE_MARKER}" ] || [ -L "${COMPLETE_MARKER}" ]; } && \
	[ ! -e "${PENDING_MARKER}" ] && [ ! -L "${PENDING_MARKER}" ]; then
	"${RELEASE_TOOL_PYTHON}" \
		"${ROOT_DIR}/deploy/validate-installation-complete.py" \
		--managed-root "${MANAGED_ROOT}" \
		--sentinel "${COMPLETE_MARKER}" \
		--expected-release "${ROOT_DIR}" >/dev/null
	echo "[ok] First-install acceptance was already finalized."
	exit 0
fi

MARKER_VALUES="$("${RELEASE_TOOL_PYTHON}" - \
	"${MANAGED_ROOT}" "${ROOT_DIR}" "${CONFIG_DIR}" "${PENDING_MARKER}" \
	"${ROOT_DIR}/deploy/validate-installation-complete.py" <<'PY'
from __future__ import annotations

import hashlib
import os
import runpy
import stat
import sys
from pathlib import Path

managed_root, current_release, config_dir, marker_path, validator_path = map(
    Path, sys.argv[1:]
)
validator = runpy.run_path(str(validator_path))
load_protected_json = validator["_load_protected_json"]
try:
    marker, _ = load_protected_json(
        marker_path,
        label="first-install pending marker",
        uid=0,
        gid=0,
        mode=0o600,
    )
    state, _ = load_protected_json(
        config_dir / "install-state.json",
        label="install-state.json",
        uid=999,
        gid=999,
        mode=0o640,
    )
    runtime, runtime_bytes = load_protected_json(
        config_dir / "runtime-config.json",
        label="runtime-config.json",
        uid=999,
        gid=999,
        mode=0o600,
    )
except (OSError, ValueError) as exc:
    raise SystemExit(f"[fail] Protected first-install state is unsafe: {exc}") from exc
marker_contract = marker.get("contract")
if marker_contract not in {"first_install_pending.v1", "first_install_finalizing.v1"}:
    raise SystemExit("[fail] First-install lifecycle marker contract is invalid.")
if Path(str(marker.get("release") or "")) != current_release:
    raise SystemExit("[fail] First-install pending marker does not match the active release.")
if (
    state.get("installation_state") != "complete"
    or state.get("database_contract") != "pg18_empty_initialization.v1"
    or state.get("config_digest") != hashlib.sha256(runtime_bytes).hexdigest()
):
    raise SystemExit("[fail] Completed PostgreSQL 18 installation evidence is invalid.")
for path, expected_mode in (
    (config_dir / "rds-ca.pem", 0o600),
    (config_dir / "frontend" / "internal-auth-token", 0o640),
):
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != expected_mode
        or (metadata.st_uid, metadata.st_gid) != (999, 999)
    ):
        raise SystemExit("[fail] Protected runtime projection is unsafe.")
rollback_map = Path(str(marker.get("rollback_image_map") or ""))
if not rollback_map.is_absolute() or managed_root not in rollback_map.parents:
    raise SystemExit("[fail] First-install rollback map escapes the managed root.")
if marker_contract == "first_install_pending.v1":
    rollback_metadata = rollback_map.lstat()
    if (
        rollback_map.is_symlink()
        or not stat.S_ISREG(rollback_metadata.st_mode)
        or stat.S_IMODE(rollback_metadata.st_mode) != 0o600
        or (rollback_metadata.st_uid, rollback_metadata.st_gid) != (0, 0)
    ):
        raise SystemExit("[fail] First-install rollback map is not protected.")
previous_project = str(marker.get("previous_compose_project") or "npcink-ai-cloud")
if not previous_project or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for ch in previous_project):
    raise SystemExit("[fail] First-install Compose project is invalid.")
print(rollback_map)
print(previous_project)
print(str(state["config_digest"]))
print(str(marker_contract))
PY
)"
ROLLBACK_IMAGE_MAP="$(printf '%s\n' "${MARKER_VALUES}" | sed -n '1p')"
COMPOSE_PROJECT="$(printf '%s\n' "${MARKER_VALUES}" | sed -n '2p')"
CONFIG_DIGEST="$(printf '%s\n' "${MARKER_VALUES}" | sed -n '3p')"
LIFECYCLE_CONTRACT="$(printf '%s\n' "${MARKER_VALUES}" | sed -n '4p')"
unset MARKER_VALUES

export NPCINK_CLOUD_CONFIG_DIR_HOST="${CONFIG_DIR}"
npcink_ai_cloud_load_env_file "${ROOT_DIR}"
npcink_ai_cloud_wait_for_internal_endpoint \
	"${ROOT_DIR}" "/health/ready" "[ok] Installed API is ready before first-install acceptance."
npcink_ai_cloud_wait_for_internal_endpoint \
	"${ROOT_DIR}" "/health/operational-ready" "[ok] Installed API and workers are operationally ready."

"${RELEASE_TOOL_PYTHON}" - \
	"${PENDING_MARKER}" "${COMPLETE_MARKER}" "${ROOT_DIR}" "${CONFIG_DIGEST}" \
	"${ROOT_DIR}/deploy/validate-installation-complete.py" <<'PY'
from __future__ import annotations

import json
import os
import runpy
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

pending, complete, release = map(Path, sys.argv[1:4])
digest = sys.argv[4]
validator_path = Path(sys.argv[5])
validator = runpy.run_path(str(validator_path))
load_protected_json = validator["_load_protected_json"]
try:
    marker, _ = load_protected_json(
        pending,
        label="first-install pending marker",
        uid=0,
        gid=0,
        mode=0o600,
    )
except (OSError, ValueError) as exc:
    raise SystemExit(f"[fail] First-install pending marker is unsafe: {exc}") from exc
contract = marker.get("contract")
if contract == "first_install_pending.v1":
    marker["contract"] = "first_install_finalizing.v1"
    marker["accepted_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    marker["config_digest"] = digest
elif (
    contract != "first_install_finalizing.v1"
    or marker.get("config_digest") != digest
):
    raise SystemExit("[fail] First-install finalizing transition is invalid.")

def atomic_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.chown(temporary, 0, 0)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass

# The atomic finalizing marker is the durable acceptance transition. If the
# host stops before the sentinel publication, rerunning resumes deterministically.
atomic_json(pending, marker)
sentinel = {
    "accepted_at": marker["accepted_at"],
    "config_digest": digest,
    "contract": "installation_complete.v1",
    "release": str(release),
}
atomic_json(complete, sentinel)
directory_fd = os.open(complete.parent, os.O_RDONLY)
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY

"${RELEASE_TOOL_PYTHON}" - "${CONFIG_DIR}" <<'PY'
import os
import stat
import sys
from pathlib import Path

config_dir = Path(sys.argv[1])
path = config_dir / "setup-auth.json"
if path.exists() or path.is_symlink():
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or (metadata.st_uid, metadata.st_gid) != (999, 999)
    ):
        raise SystemExit("[fail] Setup-auth residue is unsafe.")
    path.unlink()
    directory_fd = os.open(config_dir, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
PY

while IFS= read -r container_id; do
	[ -n "${container_id}" ] || continue
	docker rm -f "${container_id}" >/dev/null
done < <(docker ps -aq \
	--filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" \
	--filter "label=com.docker.compose.service=postgres")

if [ -e "${ROLLBACK_IMAGE_MAP}" ]; then
	while IFS=$'\t' read -r _target rollback_reference _previous_id; do
		[ -n "${rollback_reference}" ] && [ "${rollback_reference}" != "-" ] || continue
		docker image rm "${rollback_reference}" >/dev/null 2>&1 || true
		if docker image inspect "${rollback_reference}" >/dev/null 2>&1; then
			echo "[fail] Rollback image tag remains after finalize: ${rollback_reference}" >&2
			exit 1
		fi
	done <"${ROLLBACK_IMAGE_MAP}"
	rm -f -- "${ROLLBACK_IMAGE_MAP}"
fi

"${RELEASE_TOOL_PYTHON}" - \
	"${PENDING_MARKER}" "${ROOT_DIR}/deploy/validate-installation-complete.py" <<'PY'
import os
import runpy
import sys
from pathlib import Path

path = Path(sys.argv[1])
validator_path = Path(sys.argv[2])
validator = runpy.run_path(str(validator_path))
load_protected_json = validator["_load_protected_json"]
try:
    payload, _ = load_protected_json(
        path,
        label="first-install finalizing marker",
        uid=0,
        gid=0,
        mode=0o600,
    )
except (OSError, ValueError) as exc:
    raise SystemExit(f"[fail] First-install cleanup marker is unsafe: {exc}") from exc
if payload.get("contract") != "first_install_finalizing.v1":
    raise SystemExit("[fail] First-install cleanup marker is not finalizing.")
path.unlink()
descriptor = os.open(path.parent, os.O_RDONLY)
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY

echo "[ok] First-install acceptance finalized; legacy PostgreSQL rollback assets may now be pruned."
