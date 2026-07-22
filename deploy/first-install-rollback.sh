#!/usr/bin/env bash
set -euo pipefail
set +x

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"

if [ "$(id -u)" != "0" ]; then
	echo "[fail] First-install rollback requires the root production operator." >&2
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
	echo "[fail] Rollback requires the canonical non-symlink shared/config path." >&2
	exit 1
fi
if [ -e "${COMPLETE_MARKER}" ] || [ -L "${COMPLETE_MARKER}" ]; then
	echo "[fail] Permanent installation-complete acceptance forbids first-install rollback." >&2
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
	if ! rmdir "${DEPLOY_LOCK_DIR}" >/dev/null 2>&1; then status=1; fi
	exit "${status}"
}
trap cleanup EXIT
npcink_ai_cloud_require_cmd docker
INSTALL_LOCK_FILE="${CONFIG_DIR}/.install.lock"
npcink_ai_cloud_start_install_lock_broker "${ROOT_DIR}" "${INSTALL_LOCK_FILE}" 0 || {
	echo "[fail] Setup installation is active; rollback will not race it." >&2
	exit 1
}

VALUES="$("${RELEASE_TOOL_PYTHON}" - \
	"${MANAGED_ROOT}" "${ROOT_DIR}" "${CONFIG_DIR}" "${PENDING_MARKER}" \
	"${COMPLETE_MARKER}" "${ROOT_DIR}/deploy/validate-installation-complete.py" <<'PY'
import os
import runpy
import sys
from pathlib import Path

managed, current, config, marker_path, complete_path, validator_path = map(
    Path, sys.argv[1:]
)
validator = runpy.run_path(str(validator_path))
load_protected_json = validator["_load_protected_json"]

def reject_completed_installation() -> None:
    try:
        os.lstat(complete_path)
    except FileNotFoundError:
        return
    raise SystemExit(
        "[fail] Permanent installation-complete acceptance forbids first-install rollback."
    )

reject_completed_installation()
try:
    marker, _ = load_protected_json(
        marker_path,
        label="first-install pending marker",
        uid=0,
        gid=0,
        mode=0o600,
    )
    state, _ = load_protected_json(
        config / "install-state.json",
        label="install-state.json",
        uid=999,
        gid=999,
        mode=0o640,
    )
except (OSError, ValueError) as exc:
    raise SystemExit(f"[fail] Protected first-install state is unsafe: {exc}") from exc
reject_completed_installation()
if marker.get("contract") != "first_install_pending.v1" or Path(str(marker.get("release") or "")) != current:
    raise SystemExit("[fail] First-install pending marker is invalid.")
if state.get("installation_state") != "pending":
    raise SystemExit("[fail] First-install rollback is allowed only before installation completes.")
values = [
    marker.get("previous_release"), marker.get("previous_env_file"),
    marker.get("previous_compose_file"), marker.get("previous_compose_project"),
    marker.get("rollback_image_map"),
]
if any(not isinstance(value, str) or not value for value in values):
    raise SystemExit("[fail] No previous managed release is available for rollback.")
for raw in (values[0], values[1], values[2], values[4]):
    path = Path(raw)
    if not path.is_absolute() or managed not in path.parents:
        raise SystemExit("[fail] First-install rollback path escapes the managed root.")
print(*values, sep="\n")
PY
)"
PREVIOUS_RELEASE="$(printf '%s\n' "${VALUES}" | sed -n '1p')"
PREVIOUS_ENV="$(printf '%s\n' "${VALUES}" | sed -n '2p')"
PREVIOUS_COMPOSE="$(printf '%s\n' "${VALUES}" | sed -n '3p')"
PREVIOUS_PROJECT="$(printf '%s\n' "${VALUES}" | sed -n '4p')"
ROLLBACK_IMAGE_MAP="$(printf '%s\n' "${VALUES}" | sed -n '5p')"
unset VALUES

if [ -e "${COMPLETE_MARKER}" ] || [ -L "${COMPLETE_MARKER}" ]; then
	echo "[fail] Permanent installation-complete acceptance forbids first-install rollback." >&2
	exit 1
fi

while IFS=$'\t' read -r target_reference rollback_reference previous_image_id; do
	[ -n "${target_reference}" ] || continue
	if [ "${rollback_reference}" = "-" ]; then
		docker image rm "${target_reference}" >/dev/null 2>&1 || true
		continue
	fi
	docker tag "${rollback_reference}" "${target_reference}"
	[ "$(docker image inspect --format '{{.Id}}' "${target_reference}")" = "${previous_image_id}" ] || {
		echo "[fail] Restored rollback image identity mismatch: ${target_reference}" >&2
		exit 1
	}
done <"${ROLLBACK_IMAGE_MAP}"

env -i \
	PATH="${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}" \
	NPCINK_CLOUD_COMPOSE_PROJECT_NAME="${PREVIOUS_PROJECT}" \
	NPCINK_CLOUD_COMPOSE_FILE="${PREVIOUS_COMPOSE}" \
	NPCINK_CLOUD_ENV_FILE="${PREVIOUS_ENV}" \
	NPCINK_CLOUD_BACKEND_ENV_FILE="${PREVIOUS_ENV}" \
	bash -ceu '
		root="$1"
		. "${root}/deploy/common.sh"
		npcink_ai_cloud_compose "${root}" up -d --pull never --no-build --force-recreate --remove-orphans
	' bash "${PREVIOUS_RELEASE}"

PREVIOUS_BASE_URL="$(npcink_ai_cloud_read_env_value "${PREVIOUS_ENV}" NPCINK_CLOUD_BASE_URL || true)"
PREVIOUS_BASE_URL="${PREVIOUS_BASE_URL:-http://127.0.0.1:8010}"
if ! npcink_ai_cloud_wait_for_ready "${PREVIOUS_BASE_URL}" 20 2; then
	echo "[fail] Previous release did not become ready; lifecycle marker and rollback evidence are retained." >&2
	exit 1
fi

NEXT_LINK="${CURRENT_LINK}.rollback.$$"
ln -s "${PREVIOUS_RELEASE}" "${NEXT_LINK}"
mv -Tf "${NEXT_LINK}" "${CURRENT_LINK}"
while IFS=$'\t' read -r _target rollback_reference _previous_id; do
	[ -n "${rollback_reference}" ] && [ "${rollback_reference}" != "-" ] || continue
	docker image rm "${rollback_reference}" >/dev/null 2>&1 || true
done <"${ROLLBACK_IMAGE_MAP}"
rm -f -- "${PENDING_MARKER}" "${ROLLBACK_IMAGE_MAP}"
"${RELEASE_TOOL_PYTHON}" - "${MANAGED_ROOT}" <<'PY'
import os
import sys

descriptor = os.open(sys.argv[1], os.O_RDONLY)
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY
echo "[ok] Previous managed release restored; first-install state remains pending for an explicit retry."
