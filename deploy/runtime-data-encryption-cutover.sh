#!/usr/bin/env bash
set -Eeuo pipefail
set +x

umask 077

CONTRACT="p1_e06_runtime_data_encryption_cutover.v1"
EXPECTED_SOURCE_REVISION="20260710_0058"
EXPECTED_TARGET_REVISION="20260717_0068"
EXPECTED_RUNTIME_LEGACY_TOTAL=18
EXPECTED_SERVICE_LEGACY_TOTAL=12
EXPECTED_LEGACY_TOTAL=$((EXPECTED_RUNTIME_LEGACY_TOTAL + EXPECTED_SERVICE_LEGACY_TOTAL))
EXPECTED_RUNTIME_ROW_IDENTIFIERS_SHA256="675cce444dbbf801bc8ab7fb35b717888c878e062097e5fb7f2f5f110e5a764c"
EXPECTED_SERVICE_ROW_IDENTIFIERS_SHA256="e5010d2b0a2afe22b7729c4c2395c91001a078e282abee87f03a5f0289aa0bf6"
OFF_HOST_RECEIPT_CONTRACT="p1_e06_off_host_backup_receipt.v1"
OFF_HOST_ACK="I_ACKNOWLEDGE_THE_BACKUP_COPY_IS_OFF_HOST_AND_INDEPENDENT"
RESTORE_ACK="I_ACKNOWLEDGE_ROLLBACK_RESTORES_DATABASE_RELEASE_ENV_AND_BOTH_OLD_ROOTS_TOGETHER"
CUTOVER_ACK="I_AUTHORIZE_THE_P1_E06_PRODUCTION_CUTOVER"

usage() {
	cat <<'EOF'
Usage: deploy/runtime-data-encryption-cutover.sh \
  --remote-dir /opt/npcink-ai-cloud \
  --staged-release /opt/npcink-ai-cloud/release-<id> \
  --maintenance-env /run/npcink-ai-cloud/runtime-data-reencrypt.env \
  --backup-path /var/backups/npcink-ai-cloud/p1-e06.dump \
  --off-host-receipt /run/npcink-ai-cloud/p1-e06-off-host-receipt.json \
  --host-python /usr/bin/python3.11 \
  [--off-host-receipt-timeout-seconds 900] \
  --confirm-off-host-handoff I_ACKNOWLEDGE_THE_BACKUP_COPY_IS_OFF_HOST_AND_INDEPENDENT \
  --confirm-whole-database-restore I_ACKNOWLEDGE_ROLLBACK_RESTORES_DATABASE_RELEASE_ENV_AND_BOTH_OLD_ROOTS_TOGETHER \
  --confirm-production-cutover I_AUTHORIZE_THE_P1_E06_PRODUCTION_CUTOVER

Run the one-time, fail-closed P1-E06 encryption cutover on the
production Docker host. The staged release must be an already extracted exact
release bundle. The maintenance env must be mode 0600 and contain exactly:

  NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET=<target-root>
  NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID=<target-key-id>
  NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET=<old-root>
  NPCINK_CLOUD_SERVICE_SETTINGS_SECRET=<target-root>
  NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID=<target-key-id>
  NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET=<old-root>

After the fresh backup is published, the script writes a mode-0600 handoff
marker and waits for an operator-created receipt that did not exist at startup.
The receipt must be a mode-0600, non-symlink file owned by the current operator:

  {"contract":"p1_e06_off_host_backup_receipt.v1","status":"passed",
   "backup_sha256":"<same-sha256>","off_host_copy":true}

The operator owns the actual off-host transfer. The script does not infer an
off-host copy from filesystem device numbers and does not claim one without the
validated receipt.

The script never accepts a secret value as an argument. It keeps evidence mode
0600, retains .deploy-lock after every failure, never restarts old code after
migration starts, and requires recovery from the matched whole-database dump,
previous release, previous external env, and both old roots.
EOF
}

fail() {
	printf '[p1-e06:fail] stage=%s %s\n' "${CURRENT_STAGE:-preflight}" "$*" >&2
	exit 1
}

require_cmd() {
	command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

require_absolute_target() {
	local path="$1"
	local label="$2"
	[[ "${path}" = /* ]] || fail "${label} must be an absolute path"
	[ ! -L "${path}" ] || fail "${label} must not be a symbolic link"
}

mode_of() {
	stat -c '%a' "$1"
}

canonical_target() {
	local path="$1"
	local parent=""
	parent="$(cd "$(dirname "${path}")" && pwd -P)" || return 1
	printf '%s/%s' "${parent}" "$(basename "${path}")"
}

REMOTE_DIR=""
STAGED_RELEASE=""
MAINTENANCE_ENV=""
BACKUP_PATH=""
OFF_HOST_RECEIPT=""
HOST_PYTHON_CANDIDATE=""
HOST_PYTHON=""
OFF_HOST_RECEIPT_TIMEOUT_SECONDS=900
CONFIRM_OFF_HOST=""
CONFIRM_RESTORE=""
CONFIRM_CUTOVER=""

while [ "$#" -gt 0 ]; do
	case "$1" in
		--remote-dir)
			[ "$#" -ge 2 ] || fail "--remote-dir requires a path"
			REMOTE_DIR="$2"
			shift 2
			;;
		--staged-release)
			[ "$#" -ge 2 ] || fail "--staged-release requires a path"
			STAGED_RELEASE="$2"
			shift 2
			;;
		--maintenance-env)
			[ "$#" -ge 2 ] || fail "--maintenance-env requires a path"
			MAINTENANCE_ENV="$2"
			shift 2
			;;
		--backup-path)
			[ "$#" -ge 2 ] || fail "--backup-path requires a path"
			BACKUP_PATH="$2"
			shift 2
			;;
		--off-host-receipt)
			[ "$#" -ge 2 ] || fail "--off-host-receipt requires a path"
			OFF_HOST_RECEIPT="$2"
			shift 2
			;;
		--host-python)
			[ "$#" -ge 2 ] || fail "--host-python requires an executable candidate"
			HOST_PYTHON_CANDIDATE="$2"
			shift 2
			;;
		--off-host-receipt-timeout-seconds)
			[ "$#" -ge 2 ] || fail "--off-host-receipt-timeout-seconds requires an integer"
			OFF_HOST_RECEIPT_TIMEOUT_SECONDS="$2"
			shift 2
			;;
		--confirm-off-host-handoff)
			[ "$#" -ge 2 ] || fail "--confirm-off-host-handoff requires the exact acknowledgement"
			CONFIRM_OFF_HOST="$2"
			shift 2
			;;
		--confirm-whole-database-restore)
			[ "$#" -ge 2 ] || fail "--confirm-whole-database-restore requires the exact acknowledgement"
			CONFIRM_RESTORE="$2"
			shift 2
			;;
		--confirm-production-cutover)
			[ "$#" -ge 2 ] || fail "--confirm-production-cutover requires the exact acknowledgement"
			CONFIRM_CUTOVER="$2"
			shift 2
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			fail "unsupported argument"
			;;
	esac
done

CURRENT_STAGE="preflight"
for required_value in \
	REMOTE_DIR STAGED_RELEASE MAINTENANCE_ENV BACKUP_PATH OFF_HOST_RECEIPT HOST_PYTHON_CANDIDATE; do
	[ -n "${!required_value}" ] || fail "missing required option for ${required_value}"
done
[ "${CONFIRM_OFF_HOST}" = "${OFF_HOST_ACK}" ] || fail "off-host handoff acknowledgement is missing"
[ "${CONFIRM_RESTORE}" = "${RESTORE_ACK}" ] || fail "whole-database restore acknowledgement is missing"
[ "${CONFIRM_CUTOVER}" = "${CUTOVER_ACK}" ] || fail "production cutover acknowledgement is missing"

require_cmd docker
require_cmd sha256sum
require_cmd stat
require_cmd install
require_cmd readlink
require_cmd mktemp
require_cmd curl
require_cmd nginx
require_cmd systemctl
require_cmd id

HOST_PYTHON="$(command -v -- "${HOST_PYTHON_CANDIDATE}" 2>/dev/null || true)"
[ -n "${HOST_PYTHON}" ] && [ -x "${HOST_PYTHON}" ] || fail "host Python candidate is unavailable or not executable"
HOST_PYTHON="$(readlink -f "${HOST_PYTHON}")"
[[ "${HOST_PYTHON}" = /* ]] && [ -f "${HOST_PYTHON}" ] && [ -x "${HOST_PYTHON}" ] || \
	fail "host Python candidate must resolve to an absolute executable file"
HOST_PYTHON_VERSION="$("${HOST_PYTHON}" - <<'PY'
import sys

print(f"{sys.version_info.major}.{sys.version_info.minor}")
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
)" || fail "host Python 3.11 or newer is required"
[[ "${HOST_PYTHON_VERSION}" =~ ^[0-9]+\.[0-9]+$ ]] || fail "host Python version proof is invalid"

CURRENT_UID="$(id -u)"
[ "${CURRENT_UID}" = "0" ] || fail "production cutover must run as root"

require_absolute_target "${REMOTE_DIR}" "remote directory"
[ -d "${REMOTE_DIR}" ] || fail "remote directory is missing"
REMOTE_DIR="$(cd "${REMOTE_DIR}" && pwd -P)"
[ "$(stat -c '%u' "${REMOTE_DIR}")" = "0" ] || fail "managed remote directory must be owned by root"
REMOTE_DIR_MODE="$(mode_of "${REMOTE_DIR}")"
[[ "${REMOTE_DIR_MODE}" =~ ^[0-7]{3,4}$ ]] || fail "managed remote directory mode is invalid"
(( (8#${REMOTE_DIR_MODE} & 0022) == 0 )) || fail "managed remote directory must not be group/world writable"

require_absolute_target "${STAGED_RELEASE}" "staged release"
require_absolute_target "${MAINTENANCE_ENV}" "maintenance env"
require_absolute_target "${BACKUP_PATH}" "backup path"
require_absolute_target "${OFF_HOST_RECEIPT}" "off-host receipt"
[[ "${OFF_HOST_RECEIPT_TIMEOUT_SECONDS}" =~ ^[0-9]+$ ]] || fail "off-host receipt timeout must be an integer"
[ "${OFF_HOST_RECEIPT_TIMEOUT_SECONDS}" -ge 1 ] && [ "${OFF_HOST_RECEIPT_TIMEOUT_SECONDS}" -le 3600 ] || \
	fail "off-host receipt timeout must be from 1 to 3600 seconds"

[ -d "${STAGED_RELEASE}" ] || fail "staged release is missing"
STAGED_RELEASE="$(cd "${STAGED_RELEASE}" && pwd -P)"
[ "$(dirname "${STAGED_RELEASE}")" = "${REMOTE_DIR}" ] || fail "staged release must be a direct managed child"
[[ "$(basename "${STAGED_RELEASE}")" =~ ^release-[A-Za-z0-9._-]+$ ]] || fail "staged release name is invalid"
BACKUP_PATH="$(canonical_target "${BACKUP_PATH}")" || fail "backup parent is missing"
OFF_HOST_RECEIPT="$(canonical_target "${OFF_HOST_RECEIPT}")" || fail "off-host receipt parent is missing"
MAINTENANCE_ENV="$(canonical_target "${MAINTENANCE_ENV}")" || fail "maintenance env parent is missing"

for required_file in \
	docker-compose.runtime.yml \
	deploy/common.sh \
	deploy/certificate-renewal-readiness.sh \
	deploy/remote-load-and-up.sh \
	deploy/remote-operational-ready.sh \
	deploy/remote-baseline-status.sh \
	deploy/verify-release-bundle.sh \
	scripts/verify-release-bundle-manifest.py; do
	[ -f "${STAGED_RELEASE}/${required_file}" ] || fail "staged exact bundle is incomplete"
done

[ -f "${MAINTENANCE_ENV}" ] || fail "maintenance env is missing"
[ ! -L "${MAINTENANCE_ENV}" ] || fail "maintenance env must not be a symbolic link"
[ "$(mode_of "${MAINTENANCE_ENV}")" = "600" ] || fail "maintenance env must have mode 0600"
[ "$(stat -c '%u' "${MAINTENANCE_ENV}")" = "0" ] || fail "maintenance env must be owned by root"
case "${MAINTENANCE_ENV}" in
	"${REMOTE_DIR}"/*) fail "maintenance env must stay outside the managed release directory" ;;
esac

BACKUP_PARENT="$(dirname "${BACKUP_PATH}")"
OFF_HOST_RECEIPT_PARENT="$(dirname "${OFF_HOST_RECEIPT}")"
[ -d "${BACKUP_PARENT}" ] && [ -w "${BACKUP_PARENT}" ] || fail "backup parent must exist and be writable"
[ -d "${OFF_HOST_RECEIPT_PARENT}" ] && [ -w "${OFF_HOST_RECEIPT_PARENT}" ] || fail "off-host receipt parent must exist and be writable"
[ "$(stat -c '%u' "${BACKUP_PARENT}")" = "0" ] || fail "backup parent must be owned by root"
[ "$(stat -c '%u' "${OFF_HOST_RECEIPT_PARENT}")" = "0" ] || fail "receipt parent must be owned by root"
for fresh_path in "${BACKUP_PATH}" "${BACKUP_PATH}.sha256" "${OFF_HOST_RECEIPT}"; do
	[ ! -e "${fresh_path}" ] && [ ! -L "${fresh_path}" ] || fail "fresh backup or receipt target already exists"
done

# Validate a single no-follow file descriptor before taking the deploy lock.
# The lock-held freeze below must match this exact inode and content digest.
MAINTENANCE_ENV_SOURCE_PROOF="$(
	"${HOST_PYTHON}" - "${MAINTENANCE_ENV}" <<'PY'
from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import stat
import sys

path = sys.argv[1]
descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
try:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise SystemExit(1)
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise SystemExit(1)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
finally:
    os.close(descriptor)
raw = b"".join(chunks)
text = raw.decode("utf-8")
allowed = {
    "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET",
    "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID",
    "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET",
    "NPCINK_CLOUD_SERVICE_SETTINGS_SECRET",
    "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID",
    "NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET",
}
values: dict[str, str] = {}
for raw_line in text.splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    if "=" not in line:
        raise SystemExit(1)
    key, value = line.split("=", 1)
    if key not in allowed or key in values or value != value.strip():
        raise SystemExit(1)
    values[key] = value
if set(values) != allowed:
    raise SystemExit(1)
def require_target_root(name: str) -> None:
    value = values[name]
    try:
        decoded = base64.b64decode(value, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        raise SystemExit(1) from None
    if len(decoded) != 32:
        raise SystemExit(1)
    if base64.urlsafe_b64encode(decoded).decode("ascii") != value:
        raise SystemExit(1)


for target_name in (
    "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET",
    "NPCINK_CLOUD_SERVICE_SETTINGS_SECRET",
):
    require_target_root(target_name)

secret_pattern = re.compile(r"[A-Za-z0-9._~+/=-]{32,}")
for old_name in (
    "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET",
    "NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET",
):
    if not secret_pattern.fullmatch(values[old_name]):
        raise SystemExit(1)

target_names = (
    "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET",
    "NPCINK_CLOUD_SERVICE_SETTINGS_SECRET",
)
old_names = (
    "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET",
    "NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET",
)
for target_name in target_names:
    for old_name in old_names:
        if values[target_name] == values[old_name]:
            raise SystemExit(1)

key_id_pattern = re.compile(r"[A-Za-z0-9_-]{1,64}")
for key_id_name in (
    "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID",
    "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID",
):
    if not key_id_pattern.fullmatch(values[key_id_name]):
        raise SystemExit(1)
if values["NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET"] == values[
    "NPCINK_CLOUD_SERVICE_SETTINGS_SECRET"
]:
    raise SystemExit(1)
if values["NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID"] == values[
    "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID"
]:
    raise SystemExit(1)
print(
    f"{hashlib.sha256(raw).hexdigest()}\t{metadata.st_dev}\t{metadata.st_ino}"
)
PY
)" || fail "maintenance env contract is invalid"
IFS=$'\t' read -r \
	MAINTENANCE_ENV_SOURCE_SHA256 \
	MAINTENANCE_ENV_SOURCE_DEVICE \
	MAINTENANCE_ENV_SOURCE_INODE <<<"${MAINTENANCE_ENV_SOURCE_PROOF}"
[[ "${MAINTENANCE_ENV_SOURCE_SHA256}" =~ ^[0-9a-f]{64}$ ]] || \
	fail "maintenance env content digest proof is invalid"
[[ "${MAINTENANCE_ENV_SOURCE_DEVICE}" =~ ^[0-9]+$ ]] || \
	fail "maintenance env device proof is invalid"
[[ "${MAINTENANCE_ENV_SOURCE_INODE}" =~ ^[0-9]+$ ]] || \
	fail "maintenance env inode proof is invalid"
unset MAINTENANCE_ENV_SOURCE_PROOF

RELEASE_STATE_ROOT="${REMOTE_DIR}/.release-state"
GLOBAL_ONE_OFF_LOCK_DIR="${RELEASE_STATE_ROOT}/.release-one-off.lock"
STAGED_STATE_DIR="${RELEASE_STATE_ROOT}/$(basename "${STAGED_RELEASE}")"
EVIDENCE_DIR="${STAGED_STATE_DIR}/p1-e06-runtime-data-cutover"
MAINTENANCE_ENV_SNAPSHOT="${EVIDENCE_DIR}/.maintenance-env.snapshot"
GLOBAL_ACTIVATION_RECEIPT="${RELEASE_STATE_ROOT}/p1-e06-activation.json"
GLOBAL_ACTIVATION_RECEIPT_TMP=""
GLOBAL_ACTIVATION_RECEIPT_ABSENT_AT_START=0

DEPLOY_LOCK_DIR="${REMOTE_DIR}/.deploy-lock"
DEPLOY_LOCK_OWNER_FILE="${DEPLOY_LOCK_DIR}/one-off-owner"
DEPLOY_LOCK_OWNER=""
FAILURE_MARKER="${REMOTE_DIR}/.cutover-failed"

cleanup_private_cutover_artifacts() {
	local path=""
	local failed=0
	for path in "${MAINTENANCE_ENV_SNAPSHOT:-}" "${GLOBAL_ACTIVATION_RECEIPT_TMP:-}"; do
		[ -n "${path}" ] || continue
		rm -f -- "${path}" >/dev/null 2>&1 || failed=1
		if [ -e "${path}" ] || [ -L "${path}" ]; then
			failed=1
		fi
	done
	if [ "${GLOBAL_ACTIVATION_RECEIPT_ABSENT_AT_START:-0}" = "1" ] && \
		[ "${CUTOVER_SUCCEEDED:-0}" != "1" ]; then
		rm -f -- "${GLOBAL_ACTIVATION_RECEIPT:-}" >/dev/null 2>&1 || failed=1
		if [ -e "${GLOBAL_ACTIVATION_RECEIPT:-}" ] || \
			[ -L "${GLOBAL_ACTIVATION_RECEIPT:-}" ]; then
			failed=1
		fi
	fi
	return "${failed}"
}

assert_maintenance_env_source_unchanged() {
	[ -f "${MAINTENANCE_ENV}" ] && [ ! -L "${MAINTENANCE_ENV}" ] || return 1
	[ "$(mode_of "${MAINTENANCE_ENV}")" = "600" ] || return 1
	[ "$(stat -c '%u' "${MAINTENANCE_ENV}")" = "0" ] || return 1
	"${HOST_PYTHON}" - \
		"${MAINTENANCE_ENV}" \
		"${MAINTENANCE_ENV_SOURCE_SHA256}" \
		"${MAINTENANCE_ENV_SOURCE_DEVICE}" \
		"${MAINTENANCE_ENV_SOURCE_INODE}" <<'PY'
from __future__ import annotations

import hashlib
import os
import stat
import sys

path, expected_sha256, expected_device, expected_inode = sys.argv[1:]
try:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
except OSError as exc:
    raise SystemExit(1) from exc
try:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise SystemExit(1)
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise SystemExit(1)
    if metadata.st_dev != int(expected_device) or metadata.st_ino != int(expected_inode):
        raise SystemExit(1)
    digest = hashlib.sha256()
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
finally:
    os.close(descriptor)
if digest.hexdigest() != expected_sha256:
    raise SystemExit(1)
PY
}

early_on_exit() {
	local status="$?"
	local marker_tmp="${FAILURE_MARKER}.tmp.$$"
	trap - EXIT
	cleanup_private_cutover_artifacts || true
	if [ -n "${EVIDENCE_DIR:-}" ]; then
		rmdir "${EVIDENCE_DIR}" >/dev/null 2>&1 || true
	fi
	if [ "${status}" -eq 0 ]; then
		status=1
	fi
	{
		printf 'contract=%s\n' "${CONTRACT}"
		printf 'status=failed\n'
		printf 'phase=%s\n' "${CURRENT_STAGE}"
		printf 'outcome=initialization_failed_with_lock_retained\n'
	} >"${marker_tmp}" 2>/dev/null || true
	chmod 0600 "${marker_tmp}" >/dev/null 2>&1 || true
	mv -f "${marker_tmp}" "${FAILURE_MARKER}" >/dev/null 2>&1 || true
	printf '[p1-e06:fail] initialization failed; deployment lock retained.\n' >&2
	exit "${status}"
}

if ! mkdir "${DEPLOY_LOCK_DIR}" 2>/dev/null; then
	fail "another deployment or recovery is active"
fi
trap early_on_exit EXIT
trap 'CURRENT_STAGE="signal-hup-before-initialization"; exit 129' HUP
trap 'CURRENT_STAGE="signal-int-before-initialization"; exit 130' INT
trap 'CURRENT_STAGE="signal-term-before-initialization"; exit 143' TERM
chmod 0700 "${DEPLOY_LOCK_DIR}"
DEPLOY_LOCK_OWNER="$("${HOST_PYTHON}" -c 'import secrets; print(secrets.token_hex(32))')"
[[ "${DEPLOY_LOCK_OWNER}" =~ ^[0-9a-f]{64}$ ]] || \
	fail "deployment lock owner token generation failed"
if ! (umask 077; set -o noclobber; printf '%s\n' "${DEPLOY_LOCK_OWNER}" >"${DEPLOY_LOCK_OWNER_FILE}") || \
	! chmod 0600 "${DEPLOY_LOCK_OWNER_FILE}" || \
	[ ! -f "${DEPLOY_LOCK_OWNER_FILE}" ] || [ -L "${DEPLOY_LOCK_OWNER_FILE}" ] || \
	[ ! -O "${DEPLOY_LOCK_OWNER_FILE}" ] || \
	[ "$(mode_of "${DEPLOY_LOCK_OWNER_FILE}")" != "600" ]; then
	fail "deployment lock owner proof could not be published safely"
fi
export NPCINK_CLOUD_DEPLOY_LOCK_OWNER="${DEPLOY_LOCK_OWNER}"

CURRENT_STAGE="freeze-maintenance-env-after-lock"
[ ! -e "${GLOBAL_ACTIVATION_RECEIPT}" ] && [ ! -L "${GLOBAL_ACTIVATION_RECEIPT}" ] || \
	fail "global P1-E06 activation receipt already exists"
GLOBAL_ACTIVATION_RECEIPT_ABSENT_AT_START=1
[ ! -e "${EVIDENCE_DIR}" ] && [ ! -L "${EVIDENCE_DIR}" ] || \
	fail "fresh cutover evidence directory already exists"
install -d -m 0700 "${RELEASE_STATE_ROOT}" "${STAGED_STATE_DIR}" "${EVIDENCE_DIR}"
for protected_dir in "${RELEASE_STATE_ROOT}" "${STAGED_STATE_DIR}" "${EVIDENCE_DIR}"; do
	[ -d "${protected_dir}" ] && [ ! -L "${protected_dir}" ] || \
		fail "maintenance env snapshot parent must be a real directory"
	[ "$(stat -c '%u' "${protected_dir}")" = "0" ] || \
		fail "maintenance env snapshot parent must be owned by root"
	[ "$(mode_of "${protected_dir}")" = "700" ] || \
		fail "maintenance env snapshot parent must have mode 0700"
done
assert_maintenance_env_source_unchanged || \
	fail "maintenance env changed before its lock-held snapshot was frozen"
"${HOST_PYTHON}" - \
	"${MAINTENANCE_ENV}" \
	"${MAINTENANCE_ENV_SNAPSHOT}" \
	"${MAINTENANCE_ENV_SOURCE_SHA256}" \
	"${MAINTENANCE_ENV_SOURCE_DEVICE}" \
	"${MAINTENANCE_ENV_SOURCE_INODE}" <<'PY' || fail "maintenance env could not be frozen safely"
from __future__ import annotations

import hashlib
import os
import stat
import sys

source, snapshot, expected_sha256, expected_device, expected_inode = sys.argv[1:]
source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
try:
    source_metadata = os.fstat(source_fd)
    if not stat.S_ISREG(source_metadata.st_mode):
        raise SystemExit(1)
    if stat.S_IMODE(source_metadata.st_mode) != 0o600:
        raise SystemExit(1)
    if (
        source_metadata.st_dev != int(expected_device)
        or source_metadata.st_ino != int(expected_inode)
    ):
        raise SystemExit(1)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(source_fd, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
finally:
    os.close(source_fd)
raw = b"".join(chunks)
if hashlib.sha256(raw).hexdigest() != expected_sha256:
    raise SystemExit(1)
snapshot_fd = os.open(
    snapshot,
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
    0o600,
)
try:
    view = memoryview(raw)
    while view:
        written = os.write(snapshot_fd, view)
        view = view[written:]
    os.fsync(snapshot_fd)
    snapshot_metadata = os.fstat(snapshot_fd)
    if stat.S_IMODE(snapshot_metadata.st_mode) != 0o600:
        raise SystemExit(1)
finally:
    os.close(snapshot_fd)
parent_fd = os.open(os.path.dirname(snapshot), os.O_RDONLY)
try:
    os.fsync(parent_fd)
finally:
    os.close(parent_fd)
PY
assert_maintenance_env_source_unchanged || \
	fail "maintenance env changed while its lock-held snapshot was frozen"
[ -f "${MAINTENANCE_ENV_SNAPSHOT}" ] && [ ! -L "${MAINTENANCE_ENV_SNAPSHOT}" ] || \
	fail "frozen maintenance env must be a regular non-symlink file"
[ "$(mode_of "${MAINTENANCE_ENV_SNAPSHOT}")" = "600" ] || \
	fail "frozen maintenance env must have mode 0600"
[ "$(stat -c '%u' "${MAINTENANCE_ENV_SNAPSHOT}")" = "0" ] || \
	fail "frozen maintenance env must be owned by root"
[ "$(sha256sum "${MAINTENANCE_ENV_SNAPSHOT}" | awk '{print $1}')" = \
	"${MAINTENANCE_ENV_SOURCE_SHA256}" ] || fail "frozen maintenance env digest differs from its source"

# Export only from the frozen copy without source/eval. Compose v2.27 receives
# only `-e KEY` flags, so no secret value enters argv or ordinary logs.
while IFS= read -r maintenance_line || [ -n "${maintenance_line}" ]; do
	case "${maintenance_line}" in
		''|'#'*) continue ;;
	esac
	maintenance_key="${maintenance_line%%=*}"
	maintenance_value="${maintenance_line#*=}"
	case "${maintenance_key}" in
		NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET|NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID|NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET|NPCINK_CLOUD_SERVICE_SETTINGS_SECRET|NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID|NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET)
			printf -v "${maintenance_key}" '%s' "${maintenance_value}"
			export "${maintenance_key}"
			;;
		*) fail "frozen maintenance env contains an unsupported key" ;;
	esac
done <"${MAINTENANCE_ENV_SNAPSHOT}"
unset NPCINK_CLOUD_DATABASE_URL

CURRENT_STAGE="freeze-current-release-after-lock"
CURRENT_LINK="${REMOTE_DIR}/current"
[ -L "${CURRENT_LINK}" ] || fail "current must be a managed symbolic link"
PREVIOUS_RELEASE="$(readlink -f "${CURRENT_LINK}")"
[ -d "${PREVIOUS_RELEASE}" ] || fail "current release target is missing"
[ "$(dirname "${PREVIOUS_RELEASE}")" = "${REMOTE_DIR}" ] || fail "current release must be a direct managed child"
[[ "$(basename "${PREVIOUS_RELEASE}")" =~ ^release-[A-Za-z0-9._-]+$ ]] || fail "current release name is invalid"
[ "${PREVIOUS_RELEASE}" != "${STAGED_RELEASE}" ] || fail "staged release must differ from current"

PREVIOUS_STATE_DIR="${RELEASE_STATE_ROOT}/$(basename "${PREVIOUS_RELEASE}")"
STAGED_ENV_FILE="${STAGED_STATE_DIR}/env.deploy"
ROLLBACK_IMAGE_MAP="${EVIDENCE_DIR}/rollback-images.tsv"
MANIFEST_HELPER="${STAGED_RELEASE}/scripts/verify-release-bundle-manifest.py"
ROLLBACK_TAG_SUFFIX="p1e06-$(basename "${STAGED_RELEASE}" | sed 's/^release-//')"
WRITER_SERVICES=(api worker callback-worker ops-worker)
PREVIOUS_RUNTIME_SERVICES=(proxy frontend api worker callback-worker ops-worker)
PUBLIC_AND_WRITER_SERVICES=("${PREVIOUS_RUNTIME_SERVICES[@]}" release-one-off)
DATA_SERVICES=(postgres redis)
WRITERS_FENCED=0
MIGRATION_STARTED=0
POINTER_ACTIVATED=0
CUTOVER_SUCCEEDED=0
ACTIVATION_COMMITTED=0
LOCK_HELD=1
IMAGE_PREPARE_STARTED=0
IMAGE_TAGS_RESTORED=0
DATA_SWITCH_ATTEMPTED=0
DATA_SERVICES_SWITCHED=0
PREVIOUS_DATA_SERVICES_RESTORED=0
PREVIOUS_RUNTIME_RESTORED=0
POST_MIGRATION_WRITER_STOP_PROVED=0
BACKUP_PUBLISHED=0
OFF_HOST_RECEIPT_VERIFIED=0
RESTORE_CONTAINER=""
RESTORE_VOLUME=""
RESTORE_DB_ENV=""
BACKUP_TMP=""
BACKUP_CHECKSUM_TMP=""
OLD_WRITER_IMAGE_IDS_FILE=""
OLD_DATA_SERVICE_STATE_FILE=""
NEW_DATA_SERVICE_IMAGE_IDS_FILE=""
CURRENT_ENV_FILE=""
CURRENT_ENV_SHA256=""
HANDOFF_MARKER="${EVIDENCE_DIR}/off-host-handoff.json"
HANDOFF_TMP=""
RECEIPT_EVIDENCE="${EVIDENCE_DIR}/off-host-receipt-verified.json"
RECEIPT_SHA256=""
ACTIVATION_COMMIT_MARKER="${EVIDENCE_DIR}/activation-commit.json"
PASSED_RESULT="${EVIDENCE_DIR}/cutover-result.json"
FINAL_RESULT_TMP=""
ACTIVE_ONE_OFF_PID=""
ONE_OFF_PID_ARMING=0
ONE_OFF_PREVIOUS_ASYNC_PID=""

write_failure_marker() {
	local status_label="$1"
	local outcome="$2"
	local recovery="$3"
	local marker_tmp="${FAILURE_MARKER}.tmp.$$"
	local observed_release="unavailable"
	local conflicting_terminal_evidence=""
	local quarantine_path=""
	local terminal_evidence_path=""
	observed_release="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"
	[ -n "${observed_release}" ] || observed_release="unavailable"
	# A committed activation is not the same as a completed cutover. Until the
	# global receipt is published and the deployment lock is released, private
	# success evidence must remain retractable so a terminalization failure can
	# never advertise status=passed.
	if [ "${CUTOVER_SUCCEEDED:-0}" != "1" ]; then
		for terminal_evidence_path in "${PASSED_RESULT}" "${FINAL_RESULT_TMP}"; do
			[ -n "${terminal_evidence_path}" ] || continue
			rm -f -- "${terminal_evidence_path}" >/dev/null 2>&1 || true
			if [ -e "${terminal_evidence_path}" ] || [ -L "${terminal_evidence_path}" ]; then
				if [ "${terminal_evidence_path}" = "${PASSED_RESULT}" ]; then
					quarantine_path="${EVIDENCE_DIR}/.conflicting-cutover-result.$$.json"
				else
					quarantine_path="${EVIDENCE_DIR}/.conflicting-cutover-result-tmp.$$.json"
				fi
				if [ ! -f "${terminal_evidence_path}" ] || \
					[ -L "${terminal_evidence_path}" ] || \
					[ -e "${quarantine_path}" ] || [ -L "${quarantine_path}" ] || \
					! chmod 0600 "${terminal_evidence_path}" || \
					! mv -Tn "${terminal_evidence_path}" "${quarantine_path}" || \
					[ -e "${terminal_evidence_path}" ] || \
					[ -L "${terminal_evidence_path}" ] || \
					[ ! -f "${quarantine_path}" ] || \
					[ -L "${quarantine_path}" ] || \
					[ "$(mode_of "${quarantine_path}")" != "600" ] || \
					[ "$(stat -c '%u' "${quarantine_path}")" != "0" ]; then
					printf '[p1-e06:fail] canonical terminal success evidence could not be atomically quarantined; no ordinary failure marker was written and the deployment lock remains held.\n' >&2
					return 1
				fi
				conflicting_terminal_evidence="${quarantine_path}"
				printf '[p1-e06:warn] conflicting terminal success evidence quarantined at %s.\n' \
					"${quarantine_path}" >&2
			fi
		done
	fi
	{
		printf 'contract=%s\n' "${CONTRACT}"
		printf 'status=%s\n' "${status_label}"
		printf 'phase=%s\n' "${CURRENT_STAGE}"
		printf 'outcome=%s\n' "${outcome}"
		printf 'recovery=%s\n' "${recovery}"
		printf 'failed_release=%s\n' "${STAGED_RELEASE}"
		printf 'previous_release=%s\n' "${PREVIOUS_RELEASE}"
		printf 'observed_current_release=%s\n' "${observed_release}"
		printf 'migration_started=%s\n' "${MIGRATION_STARTED}"
		printf 'data_switch_attempted=%s\n' "${DATA_SWITCH_ATTEMPTED}"
		printf 'data_services_switched=%s\n' "${DATA_SERVICES_SWITCHED}"
		printf 'image_tags_restored=%s\n' "${IMAGE_TAGS_RESTORED}"
		printf 'previous_data_services_restored=%s\n' "${PREVIOUS_DATA_SERVICES_RESTORED}"
		printf 'previous_runtime_restored=%s\n' "${PREVIOUS_RUNTIME_RESTORED}"
		printf 'post_migration_writer_stop_proved=%s\n' "${POST_MIGRATION_WRITER_STOP_PROVED}"
		printf 'activation_committed=%s\n' "${ACTIVATION_COMMITTED}"
		if [ "${MIGRATION_STARTED}" = "1" ]; then
			printf 'previous_external_env=%s\n' "${CURRENT_ENV_FILE}"
			printf 'required_old_root_env_names=%s\n' \
				'NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET,NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET'
		fi
		if [ "${BACKUP_PUBLISHED}" = "1" ]; then
			printf 'database_recovery_point=%s\n' "${BACKUP_PATH}"
		fi
		if [ "${OFF_HOST_RECEIPT_VERIFIED}" = "1" ]; then
			printf 'off_host_receipt=%s\n' "${OFF_HOST_RECEIPT}"
			printf 'off_host_receipt_sha256=%s\n' "${RECEIPT_SHA256}"
		fi
		if [ -n "${conflicting_terminal_evidence}" ]; then
			printf 'conflicting_terminal_evidence=%s\n' "${conflicting_terminal_evidence}"
		fi
	} >"${marker_tmp}"
	chmod 0600 "${marker_tmp}"
	mv -f "${marker_tmp}" "${FAILURE_MARKER}"
	chmod 0600 "${FAILURE_MARKER}"
}

clean_env() {
	local clean=(env -i "PATH=${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}")
	local key=""
	for key in \
		HOME USER LOGNAME TMPDIR XDG_CONFIG_HOME XDG_RUNTIME_DIR SSH_AUTH_SOCK \
		DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DOCKER_CERT_PATH \
		DOCKER_TLS_VERIFY DOCKER_API_VERSION; do
		if [ -n "${!key+x}" ]; then
			clean+=("${key}=${!key}")
		fi
	done
	"${clean[@]}" "$@"
}

compose() {
	clean_env \
		COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
		NPCINK_CLOUD_COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
		NPCINK_CLOUD_ENV_FILE="${STAGED_ENV_FILE}" \
		NPCINK_CLOUD_BACKEND_ENV_FILE="${STAGED_ENV_FILE}" \
		docker compose \
		--project-directory "${STAGED_RELEASE}" \
		--env-file "${STAGED_ENV_FILE}" \
		-f "${STAGED_RELEASE}/docker-compose.runtime.yml" "$@"
}

assert_governed_one_off_absent() {
	local compose_container_ids=""
	local labelled_container_ids=""
	if [ -e "${GLOBAL_ONE_OFF_LOCK_DIR}" ] || [ -L "${GLOBAL_ONE_OFF_LOCK_DIR}" ]; then
		printf '[p1-e06:fail] governed release one-off lock is already present: %s\n' \
			"${GLOBAL_ONE_OFF_LOCK_DIR}" >&2
		return 1
	fi
	compose_container_ids="$(compose ps --all -q release-one-off 2>/dev/null)" || {
		printf '[p1-e06:fail] Compose could not prove governed one-off containers absent.\n' >&2
		return 1
	}
	labelled_container_ids="$(
		docker container ls -aq --no-trunc \
			--filter 'label=com.docker.compose.service=release-one-off' 2>/dev/null
	)" || {
		printf '[p1-e06:fail] Docker could not prove governed one-off containers absent.\n' >&2
		return 1
	}
	if [ -n "${compose_container_ids}" ] || [ -n "${labelled_container_ids}" ]; then
		printf '[p1-e06:fail] a governed one-off container is already present.\n' >&2
		return 1
	fi
}

release_helper() {
	clean_env \
		COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
		NPCINK_CLOUD_COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
		NPCINK_CLOUD_ENV_FILE="${STAGED_ENV_FILE}" \
		NPCINK_CLOUD_BACKEND_ENV_FILE="${STAGED_ENV_FILE}" \
		NPCINK_CLOUD_COMPOSE_FILE="${STAGED_RELEASE}/docker-compose.runtime.yml" \
		NPCINK_CLOUD_RELEASE_TOOL_PYTHON="${HOST_PYTHON}" \
		NPCINK_CLOUD_DEPLOY_LOCK_OWNER="${DEPLOY_LOCK_OWNER}" \
		"$@"
}

compose_previous() {
	clean_env \
		COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
		NPCINK_CLOUD_COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
		NPCINK_CLOUD_ENV_FILE="${CURRENT_ENV_FILE}" \
		NPCINK_CLOUD_BACKEND_ENV_FILE="${CURRENT_ENV_FILE}" \
		docker compose \
		--project-directory "${PREVIOUS_RELEASE}" \
		--env-file "${CURRENT_ENV_FILE}" \
		-f "${PREVIOUS_RELEASE}/docker-compose.runtime.yml" "$@"
}

stop_expected_services_and_verify() {
	local service=""
	local container_id=""
	local container_ids=""
	local failed=0
	compose stop "${PUBLIC_AND_WRITER_SERVICES[@]}" >/dev/null 2>&1 || failed=1
	for service in "${PUBLIC_AND_WRITER_SERVICES[@]}"; do
		if [ "${service}" = "release-one-off" ]; then
			container_ids="$(docker ps -q \
				--filter "label=com.docker.compose.service=${service}" 2>/dev/null)" || {
				failed=1
				continue
			}
		else
			container_ids="$(docker ps -q \
				--filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
				--filter "label=com.docker.compose.service=${service}" 2>/dev/null)" || {
				failed=1
				continue
			}
		fi
		while IFS= read -r container_id; do
			[ -n "${container_id}" ] || continue
			docker stop --time 10 "${container_id}" >/dev/null 2>&1 || failed=1
		done <<<"${container_ids}"
	done
	assert_no_running_writers || failed=1
	[ "${failed}" -eq 0 ] || return 1
	POST_MIGRATION_WRITER_STOP_PROVED=1
}

cleanup_restore_resources() {
	local cleanup_failed=0
	local temporary_path=""
	if [ -n "${RESTORE_CONTAINER}" ]; then
		docker rm -f "${RESTORE_CONTAINER}" >/dev/null 2>&1 || cleanup_failed=1
		if docker container inspect "${RESTORE_CONTAINER}" >/dev/null 2>&1; then
			cleanup_failed=1
		fi
	fi
	if [ -n "${RESTORE_VOLUME}" ]; then
		docker volume rm -f "${RESTORE_VOLUME}" >/dev/null 2>&1 || cleanup_failed=1
		if docker volume inspect "${RESTORE_VOLUME}" >/dev/null 2>&1; then
			cleanup_failed=1
		fi
	fi
	for temporary_path in \
		"${RESTORE_DB_ENV}" "${BACKUP_TMP}" "${BACKUP_CHECKSUM_TMP}" \
		"${HANDOFF_TMP}"; do
		[ -n "${temporary_path}" ] || continue
		rm -f -- "${temporary_path}" >/dev/null 2>&1 || cleanup_failed=1
	done
	return "${cleanup_failed}"
}

restore_release_image_tags() {
	local target_reference=""
	local rollback_reference=""
	local previous_image_id=""
	local restored_image_id=""
	local failed=0
	[ "${IMAGE_PREPARE_STARTED}" = "1" ] || return 0
	[ -f "${ROLLBACK_IMAGE_MAP}" ] || return 1
	while IFS=$'\t' read -r target_reference rollback_reference previous_image_id; do
		[ -n "${target_reference}" ] || continue
		if [ "${rollback_reference}" = "-" ]; then
			docker image rm "${target_reference}" >/dev/null 2>&1 || true
			if docker image inspect "${target_reference}" >/dev/null 2>&1; then
				failed=1
			fi
			continue
		fi
		if ! docker tag "${rollback_reference}" "${target_reference}" >/dev/null 2>&1; then
			# Finalization may already have removed a private rollback tag. The
			# immutable image ID in the protected map is still an executable
			# recovery source as long as Docker has not pruned it.
			if ! docker tag "${previous_image_id}" "${target_reference}" >/dev/null 2>&1; then
				failed=1
				continue
			fi
		fi
		restored_image_id="$(docker image inspect --format '{{.Id}}' "${target_reference}" 2>/dev/null || true)"
		[ "${restored_image_id}" = "${previous_image_id}" ] || failed=1
	done <"${ROLLBACK_IMAGE_MAP}"
	[ "${failed}" -eq 0 ] || return 1
	IMAGE_TAGS_RESTORED=1
}

discard_rollback_image_tags_and_map() {
	local _target_reference=""
	local rollback_reference=""
	local _previous_image_id=""
	local failed=0
	[ -f "${ROLLBACK_IMAGE_MAP}" ] || return 1
	while IFS=$'\t' read -r _target_reference rollback_reference _previous_image_id; do
		if [ -n "${rollback_reference}" ] && [ "${rollback_reference}" != "-" ]; then
			docker image rm "${rollback_reference}" >/dev/null 2>&1 || failed=1
			if docker image inspect "${rollback_reference}" >/dev/null 2>&1; then
				failed=1
			fi
		fi
	done <"${ROLLBACK_IMAGE_MAP}"
	[ "${failed}" -eq 0 ] || return 1
	rm -f "${ROLLBACK_IMAGE_MAP}" || return 1
	[ ! -e "${ROLLBACK_IMAGE_MAP}" ]
}

assert_previous_services_running() {
	local previous_compose_config="$1"
	local service=""
	local ids=""
	local count=0
	local state=""
	local expected_reference=""
	for service in "${PREVIOUS_RUNTIME_SERVICES[@]}"; do
		expected_reference="$(
			npcink_ai_cloud_compose_service_image_reference \
				"${HOST_PYTHON}" "${service}" <<<"${previous_compose_config}"
		)" || return 1
		ids="$(compose_previous ps -q "${service}" 2>/dev/null)" || return 1
		count="$(printf '%s\n' "${ids}" | awk 'NF {n += 1} END {print n + 0}')"
		[ "${count}" -eq 1 ] || return 1
		state="$(docker inspect --format '{{.State.Running}} {{.State.Restarting}} {{.RestartCount}}' "${ids}" 2>/dev/null)"
		[ "${state}" = "true false 0" ] || return 1
		npcink_ai_cloud_assert_container_matches_rollback_image \
			"${ROLLBACK_IMAGE_MAP}" "${ids}" "${service}" \
			"${expected_reference}" || return 1
	done
}

fence_previous_runtime_recovery() {
	local service=""
	local container_id=""
	local container_ids=""
	local failed=0

	compose_previous stop "${PREVIOUS_RUNTIME_SERVICES[@]}" >/dev/null 2>&1 || failed=1
	for service in "${PREVIOUS_RUNTIME_SERVICES[@]}"; do
		container_ids="$(docker ps -q \
			--filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
			--filter "label=com.docker.compose.service=${service}" 2>/dev/null)" || {
			failed=1
			continue
		}
		while IFS= read -r container_id; do
			[ -n "${container_id}" ] || continue
			docker stop --time 10 "${container_id}" >/dev/null 2>&1 || failed=1
		done <<<"${container_ids}"
	done
	for service in "${PREVIOUS_RUNTIME_SERVICES[@]}"; do
		container_ids="$(docker ps -q \
			--filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
			--filter "label=com.docker.compose.service=${service}" 2>/dev/null)" || {
			failed=1
			continue
		}
		[ -z "${container_ids}" ] || failed=1
	done
	[ "${failed}" -eq 0 ]
}

restart_previous_services_without_caddy() {
	local previous_compose_config=""
	local service=""
	local expected_reference=""
	local restart_failed=0

	# Data dependencies must already have been proved healthy at revision 0058.
	# Recreate only the stopped public/writer generation, never retired Caddy.
	previous_compose_config="$(compose_previous config --format json 2>/dev/null)" || return 1
	for service in "${PREVIOUS_RUNTIME_SERVICES[@]}"; do
		expected_reference="$(
			npcink_ai_cloud_compose_service_image_reference \
				"${HOST_PYTHON}" "${service}" <<<"${previous_compose_config}"
		)" || return 1
		npcink_ai_cloud_expected_rollback_image_id \
			"${ROLLBACK_IMAGE_MAP}" "${expected_reference}" >/dev/null || return 1
	done
	compose_previous up -d --pull never --no-build --no-deps --force-recreate \
		api worker callback-worker ops-worker frontend proxy >/dev/null 2>&1 || restart_failed=1
	if [ "${restart_failed}" -eq 0 ] && \
		! assert_previous_services_running "${previous_compose_config}"; then
		restart_failed=1
	fi
	if [ "${restart_failed}" -eq 0 ] && \
		! loopback_edge_health "${CURRENT_BASE_URL}" "${CURRENT_DOMAIN_NAME}"; then
		restart_failed=1
	fi
	if [ "${restart_failed}" -ne 0 ]; then
		fence_previous_runtime_recovery || true
		return 1
	fi
}

freeze_original_data_services() {
	local service=""
	local container_id=""
	local image_id=""
	: >"${OLD_DATA_SERVICE_STATE_FILE}"
	chmod 0600 "${OLD_DATA_SERVICE_STATE_FILE}"
	for service in "${DATA_SERVICES[@]}"; do
		container_id="$(compose ps -q "${service}" 2>/dev/null)" || return 1
		[ "$(printf '%s\n' "${container_id}" | awk 'NF {n += 1} END {print n + 0}')" -eq 1 ] || return 1
		image_id="$(docker inspect --format '{{.Image}}' "${container_id}" 2>/dev/null)" || return 1
		[[ "${image_id}" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
		printf '%s\t%s\t%s\n' "${service}" "${container_id}" "${image_id}" >>"${OLD_DATA_SERVICE_STATE_FILE}"
	done
}

freeze_target_data_service_images() {
	local service=""
	local role=""
	local reference=""
	local expected_image_id=""
	local observed_image_id=""
	: >"${NEW_DATA_SERVICE_IMAGE_IDS_FILE}"
	chmod 0600 "${NEW_DATA_SERVICE_IMAGE_IDS_FILE}"
	for service in "${DATA_SERVICES[@]}"; do
		case "${service}" in
			postgres)
				role="postgres"
				reference="npcink-ai-cloud-postgres:prod"
				;;
			redis)
				role="external_redis"
				reference="npcink-ai-cloud-external-redis:prod"
				;;
			*) return 1 ;;
		esac
		expected_image_id="$(
			"${HOST_PYTHON}" "${MANIFEST_HELPER}" loaded-role-daemon-id \
				--root "${STAGED_RELEASE}" --role "${role}"
		)" || return 1
		[[ "${expected_image_id}" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
		observed_image_id="$(docker image inspect --format '{{.Id}}' "${reference}" 2>/dev/null)" || return 1
		[ "${observed_image_id}" = "${expected_image_id}" ] || return 1
		printf '%s\t%s\t%s\n' \
			"${service}" "${reference}" "${expected_image_id}" >>"${NEW_DATA_SERVICE_IMAGE_IDS_FILE}"
	done
}

assert_target_data_image_tags_frozen() {
	local service=""
	local reference=""
	local expected_image_id=""
	local actual_image_id=""
	while IFS=$'\t' read -r service reference expected_image_id; do
		[ -n "${service}" ] || continue
		actual_image_id="$(docker image inspect --format '{{.Id}}' "${reference}" 2>/dev/null)" || return 1
		[ "${actual_image_id}" = "${expected_image_id}" ] || return 1
	done <"${NEW_DATA_SERVICE_IMAGE_IDS_FILE}"
}

assert_data_services_healthy_with_images() {
	local expected_state_file="$1"
	local require_original_container_ids="$2"
	local compose_kind="$3"
	local expected_revision="${4:-${EXPECTED_SOURCE_REVISION}}"
	local service=""
	local expected_container_id=""
	local expected_image_id=""
	local actual_container_id=""
	local actual_image_id=""
	local state=""
	while IFS=$'\t' read -r service expected_container_id expected_image_id; do
		[ -n "${service}" ] || continue
		if [ "${compose_kind}" = "previous" ]; then
			actual_container_id="$(compose_previous ps -q "${service}" 2>/dev/null)" || return 1
		else
			actual_container_id="$(compose ps -q "${service}" 2>/dev/null)" || return 1
		fi
		[ "$(printf '%s\n' "${actual_container_id}" | awk 'NF {n += 1} END {print n + 0}')" -eq 1 ] || return 1
		if [ "${require_original_container_ids}" = "1" ]; then
			[ "${actual_container_id}" = "${expected_container_id}" ] || return 1
		fi
		actual_image_id="$(docker inspect --format '{{.Image}}' "${actual_container_id}" 2>/dev/null)" || return 1
		[ "${actual_image_id}" = "${expected_image_id}" ] || return 1
		state="$(docker inspect --format '{{.State.Running}} {{.State.Restarting}} {{.RestartCount}} {{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "${actual_container_id}" 2>/dev/null)" || return 1
		[ "${state}" = "true false 0 healthy" ] || return 1
	done <"${expected_state_file}"
	if [ "${compose_kind}" = "previous" ]; then
		[ "$(compose_previous exec -T postgres sh -c \
			'exec psql -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select version_num from alembic_version"')" = "${expected_revision}" ]
	else
		[ "$(database_revision)" = "${expected_revision}" ]
	fi
}

assert_new_data_services_healthy() {
	local expected_revision="${1:-${EXPECTED_SOURCE_REVISION}}"
	local normalized="${EVIDENCE_DIR}/new-data-service-runtime-state.tsv"
	local service=""
	local reference=""
	local image_id=""
	: >"${normalized}"
	chmod 0600 "${normalized}"
	while IFS=$'\t' read -r service reference image_id; do
		[ -n "${service}" ] || continue
		printf '%s\t-\t%s\n' "${service}" "${image_id}" >>"${normalized}"
	done <"${NEW_DATA_SERVICE_IMAGE_IDS_FILE}"
	assert_data_services_healthy_with_images "${normalized}" 0 staged "${expected_revision}"
}

restore_previous_data_services() {
	# Tags must already be restored to their frozen old IDs. Recreate both data
	# services from those exact IDs, then prove health and revision before apps.
	compose_previous up -d --pull never --no-build --no-deps --force-recreate \
		postgres redis >/dev/null 2>&1 || return 1
	assert_data_services_healthy_with_images "${OLD_DATA_SERVICE_STATE_FILE}" 0 previous || return 1
	PREVIOUS_DATA_SERVICES_RESTORED=1
}

ensure_failure_lock() {
	if [ "${LOCK_HELD}" = "1" ]; then
		if [ -d "${DEPLOY_LOCK_DIR}" ] && [ ! -L "${DEPLOY_LOCK_DIR}" ] && \
			[ "$(mode_of "${DEPLOY_LOCK_DIR}" 2>/dev/null || true)" = "700" ] && \
			[ "$(stat -c '%u' "${DEPLOY_LOCK_DIR}" 2>/dev/null || true)" = "0" ]; then
			return 0
		fi
		LOCK_HELD=0
	fi
	if mkdir "${DEPLOY_LOCK_DIR}" 2>/dev/null; then
		chmod 0700 "${DEPLOY_LOCK_DIR}" || return 1
		[ ! -L "${DEPLOY_LOCK_DIR}" ] && \
			[ "$(mode_of "${DEPLOY_LOCK_DIR}")" = "700" ] && \
			[ "$(stat -c '%u' "${DEPLOY_LOCK_DIR}")" = "0" ] || return 1
		LOCK_HELD=1
		return 0
	fi
	return 1
}

publish_fresh_file() {
	local temporary_path="$1"
	local final_path="$2"
	[ ! -e "${final_path}" ] && [ ! -L "${final_path}" ] || fail "fresh file destination appeared during cutover"
	mv -Tn "${temporary_path}" "${final_path}"
	[ ! -e "${temporary_path}" ] && [ -f "${final_path}" ] && [ ! -L "${final_path}" ] || \
		fail "fresh file publication was not atomic"
}

on_exit() {
	local status="$?"
	local outcome="validation_failed_before_image_or_database_mutation"
	local recovery="no_runtime_or_database_recovery_required"
	local recovery_failed=0
	trap - EXIT HUP INT TERM
	set +e

	cleanup_private_cutover_artifacts || recovery_failed=1
	cleanup_restore_resources || recovery_failed=1
	# The governed one-off helper removes this global lock only after proving
	# that its stopped/running candidate and protected stdin are both absent.
	# Any residual filesystem object therefore makes automatic recovery claims
	# unsafe, even when the previous release itself can still be restarted.
	if [ -e "${GLOBAL_ONE_OFF_LOCK_DIR}" ] || [ -L "${GLOBAL_ONE_OFF_LOCK_DIR}" ]; then
		printf '[p1-e06:fail] governed API one-off cleanup remains unproved; global one-off lock retained.\n' >&2
		recovery_failed=1
	fi
	if [ "${status}" -ne 0 ] || [ "${CUTOVER_SUCCEEDED}" != "1" ]; then
		if [ "${status}" -eq 0 ]; then
			status=1
		fi
		if [ "${ACTIVATION_COMMITTED}" = "1" ]; then
			# The final active runtime validation is the irreversible commit point.
			# Terminalization failures must never disturb the healthy new runtime.
			ensure_failure_lock || recovery_failed=1
			if ! write_failure_marker \
				"terminalization_incomplete" \
				"activation_committed_terminalization_incomplete" \
				"do_not_rollback_healthy_active_runtime"; then
				recovery_failed=1
			fi
			printf '[p1-e06:fail] activation committed; runtime left healthy and deployment lock retained for terminalization repair.\n' >&2
			exit "${status}"
		elif [ "${MIGRATION_STARTED}" = "1" ]; then
			# After migration begins, never guess at pointer/tag rollback. Stop every
			# labelled or old/new-image writer and require matched whole-DB recovery.
			stop_expected_services_and_verify || recovery_failed=1
			outcome="full_database_restore_required"
			recovery="restore_whole_database_previous_release_external_env_and_both_old_roots_together"
		else
			if [ "${IMAGE_PREPARE_STARTED}" = "1" ]; then
				restore_release_image_tags || recovery_failed=1
			fi
			if [ "${WRITERS_FENCED}" = "1" ]; then
				[ "$(readlink -f "${CURRENT_LINK}" 2>/dev/null)" = "${PREVIOUS_RELEASE}" ] || recovery_failed=1
				if [ "${recovery_failed}" -eq 0 ]; then
					if [ "${DATA_SWITCH_ATTEMPTED}" = "1" ]; then
						restore_previous_data_services || recovery_failed=1
					else
						# Before the explicit data switch, the exact original containers
						# must still be present. Never recreate them on this path.
						assert_data_services_healthy_with_images \
							"${OLD_DATA_SERVICE_STATE_FILE}" 1 previous || recovery_failed=1
					fi
				fi
				if [ "${recovery_failed}" -eq 0 ]; then
					restart_previous_services_without_caddy || recovery_failed=1
				fi
				if [ "${recovery_failed}" -eq 0 ]; then
					PREVIOUS_RUNTIME_RESTORED=1
					outcome="previous_release_restored_before_migration"
					recovery="previous_release_proved_at_0058_without_database_restore"
				fi
			elif [ "${IMAGE_PREPARE_STARTED}" = "1" ]; then
				loopback_edge_health "${CURRENT_BASE_URL}" "${CURRENT_DOMAIN_NAME}" || recovery_failed=1
				if [ "${recovery_failed}" -eq 0 ]; then
					outcome="previous_release_remained_running_before_migration"
					recovery="previous_release_remained_running_at_0058"
				fi
			fi
		fi
		ensure_failure_lock || recovery_failed=1
		if [ "${recovery_failed}" -ne 0 ]; then
			outcome="recovery_incomplete"
			recovery="manual_recovery_required_from_observed_state"
		fi
		if ! write_failure_marker "failed" "${outcome}" "${recovery}"; then
			recovery_failed=1
		fi
		if [ "${MIGRATION_STARTED}" = "1" ]; then
			printf '[p1-e06:fail] migration started; lock retained. Verify writer-stop proof, then restore the matched whole database, previous release, previous external env, and both old roots.\n' >&2
		else
			printf '[p1-e06:fail] pre-migration recovery attempted; deployment lock retained.\n' >&2
		fi
		exit "${status:-1}"
	fi

	[ "${recovery_failed}" -eq 0 ] || exit 1
	[ "${LOCK_HELD}" = "0" ] || exit 1
	[ -f "${PASSED_RESULT}" ] || exit 1
	[ ! -e "${FAILURE_MARKER}" ] || exit 1
	printf '[p1-e06:ok] cutover complete; evidence=%s\n' "${EVIDENCE_DIR}"
	exit 0
}

on_signal() {
	local signal_name="$1"
	local signal_status="$2"
	local signal_stage="$3"
	local observed_async_pid=""
	if [ "${ONE_OFF_PID_ARMING}" = "1" ] && [ -z "${ACTIVE_ONE_OFF_PID}" ]; then
		set +u
		observed_async_pid="$!"
		set -u
		if [ -n "${observed_async_pid}" ] && \
			[ "${observed_async_pid}" != "${ONE_OFF_PREVIOUS_ASYNC_PID}" ]; then
			ACTIVE_ONE_OFF_PID="${observed_async_pid}"
		else
			trap - HUP INT TERM
			CURRENT_STAGE="${signal_stage}"
			exit "${signal_status}"
		fi
	fi
	trap - HUP INT TERM
	CURRENT_STAGE="${signal_stage}"
	if [ -n "${ACTIVE_ONE_OFF_PID}" ]; then
		kill "-${signal_name}" "${ACTIVE_ONE_OFF_PID}" >/dev/null 2>&1 || true
		wait "${ACTIVE_ONE_OFF_PID}" >/dev/null 2>&1 || true
		ACTIVE_ONE_OFF_PID=""
	fi
	exit "${signal_status}"
}
trap on_exit EXIT
trap 'on_signal HUP 129 signal-hup' HUP
trap 'on_signal INT 130 signal-int' INT
trap 'on_signal TERM 143 signal-term' TERM

CURRENT_STAGE="prepare-external-release-state"
install -d -m 0700 "${RELEASE_STATE_ROOT}" "${PREVIOUS_STATE_DIR}" "${STAGED_STATE_DIR}" "${EVIDENCE_DIR}"
[ "$(mode_of "${RELEASE_STATE_ROOT}")" = "700" ] || fail "release state root must have mode 0700"
[ "$(mode_of "${PREVIOUS_STATE_DIR}")" = "700" ] || fail "previous release state must have mode 0700"
[ "$(mode_of "${STAGED_STATE_DIR}")" = "700" ] || fail "staged release state must have mode 0700"
[ "$(mode_of "${EVIDENCE_DIR}")" = "700" ] || fail "evidence directory must have mode 0700"

CURRENT_ENV_FILE="${PREVIOUS_STATE_DIR}/env.deploy"
if [ ! -f "${CURRENT_ENV_FILE}" ]; then
	LEGACY_ENV_FILE="${REMOTE_DIR}/.env.deploy"
	[ -f "${LEGACY_ENV_FILE}" ] && [ ! -L "${LEGACY_ENV_FILE}" ] || fail "current release external env is missing"
	[ "$(mode_of "${LEGACY_ENV_FILE}")" = "600" ] || fail "legacy env transition source must have mode 0600"
	install -m 0600 "${LEGACY_ENV_FILE}" "${CURRENT_ENV_FILE}"
	printf 'legacy_env_transition=1\n' >"${EVIDENCE_DIR}/external-state-transition.txt"
	chmod 0600 "${EVIDENCE_DIR}/external-state-transition.txt"
fi
[ ! -L "${CURRENT_ENV_FILE}" ] && [ "$(mode_of "${CURRENT_ENV_FILE}")" = "600" ] || fail "current release env must be a mode 0600 regular file"
[ "$(stat -c '%u' "${CURRENT_ENV_FILE}")" = "${CURRENT_UID}" ] || fail "current release env owner differs from the operator"
[ -f "${PREVIOUS_RELEASE}/docker-compose.runtime.yml" ] || fail "previous exact runtime Compose file is missing"
CURRENT_ENV_SHA256="$(sha256sum "${CURRENT_ENV_FILE}" | awk '{print $1}')"
install -m 0600 "${CURRENT_ENV_FILE}" "${STAGED_ENV_FILE}"
"${HOST_PYTHON}" - "${STAGED_ENV_FILE}" <<'PY' || fail "staged env legacy-root sanitization failed"
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
legacy_keys = {
    "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET",
    "NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET",
}
kept = [
    line
    for line in path.read_text(encoding="utf-8").splitlines()
    if (line.split("=", 1)[0] if "=" in line else "") not in legacy_keys
]
temporary = path.with_name(f".{path.name}.sanitize.{os.getpid()}")
with temporary.open("x", encoding="utf-8") as handle:
    handle.write("\n".join(kept).rstrip("\n") + "\n")
    handle.flush()
    os.fsync(handle.fileno())
os.chmod(temporary, 0o600)
os.replace(temporary, path)
directory_fd = os.open(path.parent, os.O_RDONLY)
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
[ "$(mode_of "${STAGED_ENV_FILE}")" = "600" ] || fail "staged release env must have mode 0600"

. "${STAGED_RELEASE}/deploy/common.sh"
COMPOSE_PROJECT_NAME_EFFECTIVE="$(npcink_ai_cloud_compose_project_name_from_env "${STAGED_ENV_FILE}")"
CURRENT_BASE_URL="$(npcink_ai_cloud_read_env_value "${CURRENT_ENV_FILE}" NPCINK_CLOUD_BASE_URL || true)"
CURRENT_DOMAIN_NAME="$(npcink_ai_cloud_read_env_value "${CURRENT_ENV_FILE}" NPCINK_CLOUD_DOMAIN_NAME || true)"
CURRENT_EXTERNAL_EDGE_READY="$(npcink_ai_cloud_read_env_value "${CURRENT_ENV_FILE}" NPCINK_CLOUD_EXTERNAL_EDGE_READY || true)"
CURRENT_CERTIFICATE_RENEWAL_CERT_PATH="$(npcink_ai_cloud_read_env_value "${CURRENT_ENV_FILE}" NPCINK_CLOUD_CERTIFICATE_RENEWAL_CERT_PATH || true)"
CURRENT_CERTIFICATE_RENEWAL_EVIDENCE_PATH="$(npcink_ai_cloud_read_env_value "${CURRENT_ENV_FILE}" NPCINK_CLOUD_CERTIFICATE_RENEWAL_EVIDENCE_PATH || true)"
CURRENT_CERTIFICATE_RENEWAL_TIMER="$(npcink_ai_cloud_read_env_value "${CURRENT_ENV_FILE}" NPCINK_CLOUD_CERTIFICATE_RENEWAL_TIMER || true)"
CURRENT_CERTIFICATE_RENEWAL_HOOK_PATH="$(npcink_ai_cloud_read_env_value "${CURRENT_ENV_FILE}" NPCINK_CLOUD_CERTIFICATE_RENEWAL_HOOK_PATH || true)"
OLD_WRITER_IMAGE_IDS_FILE="${EVIDENCE_DIR}/old-writer-image-ids.txt"
OLD_DATA_SERVICE_STATE_FILE="${EVIDENCE_DIR}/old-data-service-state.tsv"
NEW_DATA_SERVICE_IMAGE_IDS_FILE="${EVIDENCE_DIR}/new-data-service-image-ids.tsv"
: >"${OLD_WRITER_IMAGE_IDS_FILE}"
chmod 0600 "${OLD_WRITER_IMAGE_IDS_FILE}"
printf 'host_python=%s\nhost_python_version=%s\n' \
	"${HOST_PYTHON}" "${HOST_PYTHON_VERSION}" >"${EVIDENCE_DIR}/host-python.txt"
chmod 0600 "${EVIDENCE_DIR}/host-python.txt"

loopback_edge_health() {
	local base_url="$1"
	local domain_name="$2"
	"${HOST_PYTHON}" - "${base_url}" "${domain_name}" <<'PY' || return 1
from __future__ import annotations

import sys
from urllib.parse import urlsplit

base_url, domain_name = sys.argv[1:]
parsed = urlsplit(base_url)
if parsed.scheme != "https" or parsed.hostname != domain_name or parsed.port not in (None, 443):
    raise SystemExit(1)
if parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
    raise SystemExit(1)
PY
	curl -fsS --connect-timeout 5 --max-time 15 \
		--resolve "${domain_name}:443:127.0.0.1" \
		"${base_url%/}/health/live" >/dev/null
}

CURRENT_STAGE="verify-certificate-renewal-readiness"
[ -n "${CURRENT_DOMAIN_NAME}" ] || fail "current production domain is missing"
[ -n "${CURRENT_CERTIFICATE_RENEWAL_CERT_PATH}" ] || fail "current env must define NPCINK_CLOUD_CERTIFICATE_RENEWAL_CERT_PATH"
[ -n "${CURRENT_CERTIFICATE_RENEWAL_EVIDENCE_PATH}" ] || fail "current env must define NPCINK_CLOUD_CERTIFICATE_RENEWAL_EVIDENCE_PATH"
[ -n "${CURRENT_CERTIFICATE_RENEWAL_TIMER}" ] || fail "current env must define NPCINK_CLOUD_CERTIFICATE_RENEWAL_TIMER"
[ -n "${CURRENT_CERTIFICATE_RENEWAL_HOOK_PATH}" ] || fail "current env must define NPCINK_CLOUD_CERTIFICATE_RENEWAL_HOOK_PATH"
NPCINK_CLOUD_RELEASE_TOOL_PYTHON="${HOST_PYTHON}" \
	bash "${STAGED_RELEASE}/deploy/certificate-renewal-readiness.sh" verify \
	--domain "${CURRENT_DOMAIN_NAME}" \
	--certificate-path "${CURRENT_CERTIFICATE_RENEWAL_CERT_PATH}" \
	--owner certbot \
	--timer "${CURRENT_CERTIFICATE_RENEWAL_TIMER}" \
	--deploy-hook-path "${CURRENT_CERTIFICATE_RENEWAL_HOOK_PATH}" \
	--evidence-path "${CURRENT_CERTIFICATE_RENEWAL_EVIDENCE_PATH}" || \
	fail "certificate renewal readiness verification failed"

CURRENT_STAGE="verify-local-docker-and-host-edge"
[ -z "${DOCKER_HOST:-}" ] || [[ "${DOCKER_HOST}" = unix:///* ]] || fail "production cutover requires a local Docker Unix socket"
DOCKER_ENDPOINT="$(docker context inspect --format '{{.Endpoints.docker.Host}}')" || fail "active Docker context cannot be inspected"
[[ "${DOCKER_ENDPOINT}" = unix:///* ]] || fail "active Docker context is not a local Unix socket"
docker info >/dev/null 2>&1 || fail "local Docker daemon is unavailable"
[ "${CURRENT_EXTERNAL_EDGE_READY}" = "true" ] || fail "current env must explicitly acknowledge the external Edge"
CADDY_IDS="$(docker ps -q \
	--filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
	--filter "label=com.docker.compose.service=caddy")"
[ -z "${CADDY_IDS}" ] || fail "retired project Caddy containers must not be running before cutover"
systemctl is-active --quiet nginx || fail "host NGINX is not active"
nginx -t >"${EVIDENCE_DIR}/host-nginx-test.log" 2>&1 || fail "host NGINX configuration test failed"
chmod 0600 "${EVIDENCE_DIR}/host-nginx-test.log"
loopback_edge_health "${CURRENT_BASE_URL}" "${CURRENT_DOMAIN_NAME}" || fail "loopback-resolved HTTPS Edge health failed"
printf 'contract=p1_e06_host_edge_preflight.v1\nstatus=passed\n' >"${EVIDENCE_DIR}/host-edge-preflight.txt"
chmod 0600 "${EVIDENCE_DIR}/host-edge-preflight.txt"

assert_expected_and_no_foreign_writers() {
	local service=""
	local expected_ids=""
	local all_ids=""
	local count=0
	local container_id=""
	local project=""
	local image_id=""
	for service in "${WRITER_SERVICES[@]}"; do
		expected_ids="$(docker ps -q \
			--filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
			--filter "label=com.docker.compose.service=${service}")"
		count="$(printf '%s\n' "${expected_ids}" | awk 'NF {n += 1} END {print n + 0}')"
		[ "${count}" -eq 1 ] || fail "expected exactly one running writer for each managed service"
		all_ids="$(docker ps -q --filter "label=com.docker.compose.service=${service}")"
		while IFS= read -r container_id; do
			[ -n "${container_id}" ] || continue
			project="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "${container_id}")"
			[ "${project}" = "${COMPOSE_PROJECT_NAME_EFFECTIVE}" ] || fail "foreign Compose writer is running"
		done <<<"${all_ids}"
		image_id="$(docker inspect --format '{{.Image}}' "${expected_ids}")"
		printf '%s\n' "${image_id}" >>"${OLD_WRITER_IMAGE_IDS_FILE}"
	done
	LC_ALL=C sort -u -o "${OLD_WRITER_IMAGE_IDS_FILE}" "${OLD_WRITER_IMAGE_IDS_FILE}"
}

assert_no_running_writers() {
	local service=""
	local image_id=""
	local running_ids=""
	for service in "${WRITER_SERVICES[@]}"; do
		running_ids="$(docker ps -q --filter "label=com.docker.compose.service=${service}")" || return 1
		[ -z "${running_ids}" ] || return 1
	done
	while IFS= read -r image_id; do
		[ -n "${image_id}" ] || continue
		running_ids="$(docker ps -q --filter "ancestor=${image_id}")" || return 1
		[ -z "${running_ids}" ] || return 1
	done <"${OLD_WRITER_IMAGE_IDS_FILE}"
}

database_revision() {
	compose exec -T postgres sh -c \
		'exec psql -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select version_num from alembic_version"'
}

assert_database_clients_quiesced() {
	local count=""
	count="$(compose exec -T postgres sh -c \
		'exec psql -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select count(*) from pg_stat_activity where datname=current_database() and pid<>pg_backend_pid() and backend_type=\$\$client backend\$\$"')"
	[ "${count}" = "0" ] || fail "database still has a foreign client session after writer fencing"
}

CURRENT_STAGE="verify-current-writers"
assert_expected_and_no_foreign_writers
[ "$(database_revision)" = "${EXPECTED_SOURCE_REVISION}" ] || fail "production database is not at the expected 0058 source revision"
freeze_original_data_services || fail "current PostgreSQL/Redis container and image IDs could not be frozen"
assert_data_services_healthy_with_images "${OLD_DATA_SERVICE_STATE_FILE}" 1 staged || \
	fail "current PostgreSQL/Redis services are not healthy at the frozen 0058 generation"

CURRENT_STAGE="prove-governed-one-off-absence-before-mutation"
assert_governed_one_off_absent || \
	fail "governed one-off absence was not proved before image or database mutation"

CURRENT_STAGE="prepare-exact-bundle-images"
IMAGE_PREPARE_STARTED=1
PREPARE_LOG="${EVIDENCE_DIR}/prepare-only.log"
: >"${PREPARE_LOG}"
chmod 0600 "${PREPARE_LOG}"
if ! release_helper \
	NPCINK_CLOUD_LOAD_MODE=prepare-only \
	NPCINK_CLOUD_ROLLBACK_IMAGE_MAP="${ROLLBACK_IMAGE_MAP}" \
	NPCINK_CLOUD_ROLLBACK_TAG_SUFFIX="${ROLLBACK_TAG_SUFFIX}" \
	bash "${STAGED_RELEASE}/deploy/remote-load-and-up.sh" \
	>"${PREPARE_LOG}" 2>&1; then
	fail "exact bundle prepare-only phase failed"
fi
[ -f "${ROLLBACK_IMAGE_MAP}" ] && [ "$(mode_of "${ROLLBACK_IMAGE_MAP}")" = "600" ] || fail "prepare-only rollback image map is missing or unsafe"
NEW_API_IMAGE_ID="$(
	"${HOST_PYTHON}" "${MANIFEST_HELPER}" loaded-role-daemon-id \
		--root "${STAGED_RELEASE}" --role api
)" || fail "bundle-proved target-daemon API image ID could not be frozen"
[[ "${NEW_API_IMAGE_ID}" =~ ^sha256:[0-9a-f]{64}$ ]] || fail "prepared API image ID is invalid"
[ "$(docker image inspect --format '{{.Id}}' npcink-ai-cloud-api:prod)" = "${NEW_API_IMAGE_ID}" ] || \
	fail "prepared API tag differs from the bundle-proved target-daemon image ID"
printf '%s\n' "${NEW_API_IMAGE_ID}" >>"${OLD_WRITER_IMAGE_IDS_FILE}"
LC_ALL=C sort -u -o "${OLD_WRITER_IMAGE_IDS_FILE}" "${OLD_WRITER_IMAGE_IDS_FILE}"
freeze_target_data_service_images || fail "prepared PostgreSQL/Redis image IDs could not be frozen"
assert_target_data_image_tags_frozen || fail "prepared PostgreSQL/Redis tags drifted after image preparation"

CURRENT_STAGE="fence-public-and-writer-services"
WRITERS_FENCED=1
FENCE_LOG="${EVIDENCE_DIR}/writer-fence.log"
: >"${FENCE_LOG}"
chmod 0600 "${FENCE_LOG}"
if ! compose stop "${PUBLIC_AND_WRITER_SERVICES[@]}" >"${FENCE_LOG}" 2>&1; then
	fail "managed public and writer services could not be stopped"
fi
assert_no_running_writers || fail "a labelled or old/new-image writer remains after fencing"
assert_database_clients_quiesced

CURRENT_STAGE="create-fresh-custom-backup"
BACKUP_TMP="$(mktemp "${BACKUP_PARENT}/.$(basename "${BACKUP_PATH}").XXXXXX")"
chmod 0600 "${BACKUP_TMP}"
BACKUP_LOG="${EVIDENCE_DIR}/backup.log"
: >"${BACKUP_LOG}"
chmod 0600 "${BACKUP_LOG}"
if ! compose exec -T postgres sh -c \
	'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl' \
	>"${BACKUP_TMP}" 2>"${BACKUP_LOG}"; then
	fail "custom-format PostgreSQL backup failed"
fi
[ -s "${BACKUP_TMP}" ] || fail "custom-format PostgreSQL backup is empty"
if ! compose exec -T postgres pg_restore --list <"${BACKUP_TMP}" >>"${BACKUP_LOG}" 2>&1; then
	fail "custom-format PostgreSQL backup catalog is unreadable"
fi
publish_fresh_file "${BACKUP_TMP}" "${BACKUP_PATH}"
chmod 0400 "${BACKUP_PATH}"
BACKUP_SHA256="$(sha256sum "${BACKUP_PATH}" | awk '{print $1}')"
BACKUP_CHECKSUM_TMP="$(mktemp "${BACKUP_PARENT}/.$(basename "${BACKUP_PATH}").sha256.XXXXXX")"
printf '%s  %s\n' "${BACKUP_SHA256}" "$(basename "${BACKUP_PATH}")" >"${BACKUP_CHECKSUM_TMP}"
chmod 0600 "${BACKUP_CHECKSUM_TMP}"
publish_fresh_file "${BACKUP_CHECKSUM_TMP}" "${BACKUP_PATH}.sha256"
chmod 0400 "${BACKUP_PATH}.sha256"
BACKUP_TMP=""
BACKUP_CHECKSUM_TMP=""

fsync_paths_and_parents() {
	"${HOST_PYTHON}" - "$@" <<'PY'
import os
import sys

parents: set[str] = set()
for raw_path in sys.argv[1:]:
    descriptor = os.open(raw_path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    parents.add(os.path.dirname(raw_path))
for parent in sorted(parents):
    descriptor = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
PY
}
fsync_paths_and_parents "${BACKUP_PATH}" "${BACKUP_PATH}.sha256"
BACKUP_PUBLISHED=1

assert_backup_integrity() {
	local actual_sha256=""
	local expected_line="${BACKUP_SHA256}  $(basename "${BACKUP_PATH}")"
	[ -f "${BACKUP_PATH}" ] && [ ! -L "${BACKUP_PATH}" ] || return 1
	[ -f "${BACKUP_PATH}.sha256" ] && [ ! -L "${BACKUP_PATH}.sha256" ] || return 1
	[ "$(mode_of "${BACKUP_PATH}")" = "400" ] || return 1
	[ "$(mode_of "${BACKUP_PATH}.sha256")" = "400" ] || return 1
	[ "$(stat -c '%u' "${BACKUP_PATH}")" = "0" ] || return 1
	[ "$(stat -c '%u' "${BACKUP_PATH}.sha256")" = "0" ] || return 1
	actual_sha256="$(sha256sum "${BACKUP_PATH}" | awk '{print $1}')" || return 1
	[ "${actual_sha256}" = "${BACKUP_SHA256}" ] || return 1
	[ "$(cat "${BACKUP_PATH}.sha256")" = "${expected_line}" ] || return 1
}
assert_backup_integrity || fail "published read-only backup integrity proof failed"

CURRENT_STAGE="wait-for-off-host-backup-receipt"
HANDOFF_TMP="${HANDOFF_MARKER}.tmp.$$"
"${HOST_PYTHON}" - "${HANDOFF_TMP}" "${BACKUP_PATH}" "${BACKUP_SHA256}" "${OFF_HOST_RECEIPT}" <<'PY'
import json
import os
import sys

path, backup_path, backup_sha256, receipt_path = sys.argv[1:]
payload = {
    "contract": "p1_e06_off_host_backup_handoff.v1",
    "status": "awaiting_off_host_copy",
    "backup_path": backup_path,
    "backup_sha256": backup_sha256,
    "receipt_path": receipt_path,
}
with open(path, "x", encoding="utf-8") as handle:
    json.dump(payload, handle, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.chmod(path, 0o600)
PY
publish_fresh_file "${HANDOFF_TMP}" "${HANDOFF_MARKER}"
HANDOFF_TMP=""
fsync_paths_and_parents "${HANDOFF_MARKER}"
printf '[p1-e06:handoff] marker=%s receipt=%s\n' "${HANDOFF_MARKER}" "${OFF_HOST_RECEIPT}"
RECEIPT_WAITED_SECONDS=0
while [ ! -e "${OFF_HOST_RECEIPT}" ] && [ ! -L "${OFF_HOST_RECEIPT}" ]; do
	[ "${RECEIPT_WAITED_SECONDS}" -lt "${OFF_HOST_RECEIPT_TIMEOUT_SECONDS}" ] || fail "off-host receipt wait timed out"
	sleep 1
	RECEIPT_WAITED_SECONDS=$((RECEIPT_WAITED_SECONDS + 1))
done
[ -f "${OFF_HOST_RECEIPT}" ] && [ ! -L "${OFF_HOST_RECEIPT}" ] || fail "off-host receipt must be a regular non-symlink file"
[ "$(mode_of "${OFF_HOST_RECEIPT}")" = "600" ] || fail "off-host receipt must have mode 0600"
[ "$(stat -c '%u' "${OFF_HOST_RECEIPT}")" = "0" ] || fail "off-host receipt must be owned by root"
RECEIPT_SHA256="$(sha256sum "${OFF_HOST_RECEIPT}" | awk '{print $1}')"
"${HOST_PYTHON}" - \
	"${OFF_HOST_RECEIPT}" "${BACKUP_SHA256}" "${RECEIPT_EVIDENCE}" "${RECEIPT_SHA256}" <<'PY' || \
	fail "off-host receipt contract is invalid"
import json
import os
import sys
from pathlib import Path

source_path = Path(sys.argv[1])
receipt = json.loads(source_path.read_text(encoding="utf-8"))
expected = {
    "contract": "p1_e06_off_host_backup_receipt.v1",
    "status": "passed",
    "backup_sha256": sys.argv[2],
    "off_host_copy": True,
}
if receipt != expected:
    raise SystemExit(1)
evidence_path = Path(sys.argv[3])
payload = {
    "contract": "p1_e06_off_host_backup_receipt_evidence.v1",
    "status": "passed",
    "source_receipt_path": str(source_path),
    "source_receipt_sha256": sys.argv[4],
    "validated_receipt": receipt,
}
with evidence_path.open("x", encoding="utf-8") as handle:
    json.dump(payload, handle, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.chmod(evidence_path, 0o600)
PY
fsync_paths_and_parents "${RECEIPT_EVIDENCE}"
OFF_HOST_RECEIPT_VERIFIED=1
assert_backup_integrity || fail "backup changed after the off-host receipt was verified"

validate_report() {
	local report_path="$1"
	local expected_mode="$2"
	local family="$3"
	local expected_total=""
	local expected_identifiers_sha256=""
	case "${family}" in
		runtime)
			expected_total="${EXPECTED_RUNTIME_LEGACY_TOTAL}"
			expected_identifiers_sha256="${EXPECTED_RUNTIME_ROW_IDENTIFIERS_SHA256}"
			;;
		service)
			expected_total="${EXPECTED_SERVICE_LEGACY_TOTAL}"
			expected_identifiers_sha256="${EXPECTED_SERVICE_ROW_IDENTIFIERS_SHA256}"
			;;
		*) return 1 ;;
	esac
	"${HOST_PYTHON}" - \
		"${report_path}" "${expected_mode}" "${family}" "${expected_total}" \
		"${expected_identifiers_sha256}" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
mode = sys.argv[2]
family = sys.argv[3]
expected_total = int(sys.argv[4])
expected_identifiers_sha256 = sys.argv[5]
if not isinstance(report, dict) or set(report) != {
    "mode",
    "total",
    "legacy",
    "current",
    "migrated",
    "would_migrate",
    "counts_by_kind",
    "row_identifiers",
}:
    raise SystemExit(1)
expected = {
    "inventory": (expected_total, expected_total, 0, 0, expected_total),
    "dry-run": (expected_total, expected_total, 0, 0, expected_total),
    "apply": (expected_total, 0, expected_total, expected_total, expected_total),
    "verify": (expected_total, 0, expected_total, 0, 0),
}[mode]
actual = tuple(
    int(report.get(key, -1))
    for key in ("total", "legacy", "current", "migrated", "would_migrate")
)
if report.get("mode") != mode or actual != expected:
    raise SystemExit(1)
counts = report.get("counts_by_kind")
if not isinstance(counts, dict):
    raise SystemExit(1)
expected_kinds_by_family = {
    "runtime": {
        "site_api_key": 17,
        "site_runtime_callback": 0,
        "addon_connection_payload": 1,
        "portal_idempotency_response": 0,
        "runtime_execution_input": 0,
    },
    "service": {
        "provider_connection_secret": 8,
        "service_setting_secret": 4,
    },
}
expected_kinds = expected_kinds_by_family.get(family)
if expected_kinds is None:
    raise SystemExit(1)
if set(counts) != set(expected_kinds):
    raise SystemExit(1)
for kind, total in expected_kinds.items():
    kind_counts = counts[kind]
    if not isinstance(kind_counts, dict):
        raise SystemExit(1)
    if int(kind_counts.get("total", -1)) != total:
        raise SystemExit(1)
identifiers = report.get("row_identifiers")
if not isinstance(identifiers, list) or len(identifiers) != expected_total:
    raise SystemExit(1)
if len(set(identifiers)) != expected_total:
    raise SystemExit(1)
canonical_identifiers = json.dumps(
    sorted(identifiers),
    ensure_ascii=True,
    separators=(",", ":"),
).encode("utf-8")
if hashlib.sha256(canonical_identifiers).hexdigest() != expected_identifiers_sha256:
    raise SystemExit(1)
PY
}

assert_new_api_tag_frozen() {
	local observed_image_id=""
	observed_image_id="$(
		docker image inspect --format '{{.Id}}' npcink-ai-cloud-api:prod 2>/dev/null
	)" || return 1
	[ "${observed_image_id}" = "${NEW_API_IMAGE_ID}" ]
}

run_exact_api_one_off_isolated() {
	local exec_env_names=()
	local exec_env_args=()
	local payload=()
	local env_name=""
	local exported_name=""
	local keep_exported_name=0
	while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do
		[ "$#" -ge 2 ] && [ "$1" = "-e" ] || {
			printf '[p1-e06:fail] exact API one-off env option must be a names-only -e pair.\n' >&2
			return 1
		}
		env_name="$2"
		[[ "${env_name}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || {
			printf '[p1-e06:fail] exact API one-off env name is invalid.\n' >&2
			return 1
		}
		exec_env_names+=("${env_name}")
		exec_env_args+=(--exec-env "${env_name}")
		shift 2
	done
	[ "$#" -gt 0 ] && [ "$1" = "--" ] || {
		printf '[p1-e06:fail] exact API one-off payload delimiter is missing.\n' >&2
		return 1
	}
	shift
	payload=("$@")
	[ "${#payload[@]}" -gt 0 ] || {
		printf '[p1-e06:fail] exact API one-off payload is empty.\n' >&2
		return 1
	}
	# Match the former maintenance-Compose isolation without creating a second
	# container lifecycle. Only names explicitly requested for docker exec and
	# the minimum local Docker client context survive ambient-env contraction.
	while IFS= read -r exported_name; do
		keep_exported_name=0
		case "${exported_name}" in
			PATH|HOME|USER|LOGNAME|TMPDIR|XDG_CONFIG_HOME|XDG_RUNTIME_DIR|SSH_AUTH_SOCK|DOCKER_HOST|DOCKER_CONTEXT|DOCKER_CONFIG|DOCKER_CERT_PATH|DOCKER_TLS_VERIFY|DOCKER_API_VERSION|NPCINK_CLOUD_DEPLOY_LOCK_OWNER)
				keep_exported_name=1
				;;
		esac
		if [ "${keep_exported_name}" -eq 0 ]; then
			if [ "${#exec_env_names[@]}" -gt 0 ]; then
				for env_name in "${exec_env_names[@]}"; do
					if [ "${exported_name}" = "${env_name}" ]; then
						keep_exported_name=1
						break
					fi
				done
			fi
		fi
		[ "${keep_exported_name}" -eq 1 ] || unset "${exported_name}"
	done < <(compgen -e)
	local COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME_EFFECTIVE}"
	local NPCINK_CLOUD_COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME_EFFECTIVE}"
	local NPCINK_CLOUD_ENV_FILE="${STAGED_ENV_FILE}"
	local NPCINK_CLOUD_BACKEND_ENV_FILE="${STAGED_ENV_FILE}"
	local NPCINK_CLOUD_COMPOSE_FILE="${STAGED_RELEASE}/docker-compose.runtime.yml"
	local NPCINK_CLOUD_RELEASE_TOOL_PYTHON="${HOST_PYTHON}"
	local NPCINK_CLOUD_API_RELEASE_IMAGE=""
	export COMPOSE_PROJECT_NAME NPCINK_CLOUD_COMPOSE_PROJECT_NAME
	export NPCINK_CLOUD_ENV_FILE NPCINK_CLOUD_BACKEND_ENV_FILE NPCINK_CLOUD_COMPOSE_FILE

	if [ "${#exec_env_args[@]}" -gt 0 ]; then
		npcink_ai_cloud_compose_run_with_image_proof \
			"${STAGED_RELEASE}" api npcink-ai-cloud-api:prod "${NEW_API_IMAGE_ID}" \
			"${exec_env_args[@]}" -- "${payload[@]}" </dev/null
	else
		npcink_ai_cloud_compose_run_with_image_proof \
			"${STAGED_RELEASE}" api npcink-ai-cloud-api:prod "${NEW_API_IMAGE_ID}" \
			-- "${payload[@]}" </dev/null
	fi
}

run_exact_api_one_off() {
	local run_status=0
	set +u
	ONE_OFF_PREVIOUS_ASYNC_PID="$!"
	set -u
	ONE_OFF_PID_ARMING=1
	run_exact_api_one_off_isolated "$@" &
	ACTIVE_ONE_OFF_PID="$!"
	ONE_OFF_PID_ARMING=0
	ONE_OFF_PREVIOUS_ASYNC_PID=""
	if wait "${ACTIVE_ONE_OFF_PID}"; then
		run_status=0
	else
		run_status=$?
	fi
	ACTIVE_ONE_OFF_PID=""
	return "${run_status}"
}

run_api_evidence() {
	local prefix="$1"
	local mode="$2"
	shift 2
	local output="${EVIDENCE_DIR}/${prefix}-${mode}.json"
	local errors="${EVIDENCE_DIR}/${prefix}-${mode}.stderr"
	local env_flags=(
		-e NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET
		-e NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID
		-e NPCINK_CLOUD_SERVICE_SETTINGS_SECRET
		-e NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID
	)
	local old_root_was_set=0
	local old_root_value=""
	local service_old_root_was_set=0
	local service_old_root_value=""
	local run_status=0
	case "${mode}" in
		dry-run|apply) env_flags+=(-e NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET) ;;
		inventory|verify) ;;
		*) fail "unsupported runtime-data evidence mode" ;;
	esac
	if [ -n "${NPCINK_CLOUD_DATABASE_URL+x}" ]; then
		env_flags+=(-e NPCINK_CLOUD_DATABASE_URL)
	fi
	: >"${output}"
	: >"${errors}"
	chmod 0600 "${output}" "${errors}"
	if [ -n "${NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET+x}" ]; then
		old_root_was_set=1
		old_root_value="${NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET}"
	fi
	if [ -n "${NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET+x}" ]; then
		service_old_root_was_set=1
		service_old_root_value="${NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET}"
	fi
	unset NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET
	if [ "${mode}" != "dry-run" ] && [ "${mode}" != "apply" ]; then
		unset NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET
	fi
	if run_exact_api_one_off "${env_flags[@]}" -- \
		python -m app.dev.reencrypt_runtime_data "$@" \
		>"${output}" 2>"${errors}"; then
		run_status=0
	else
		run_status=$?
	fi
	if [ "${old_root_was_set}" = "1" ]; then
		export NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET="${old_root_value}"
	else
		unset NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET
	fi
	if [ "${service_old_root_was_set}" = "1" ]; then
		export NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET="${service_old_root_value}"
	else
		unset NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET
	fi
	if [ "${run_status}" -ne 0 ]; then
		fail "runtime-data ${mode} phase failed"
	fi
	validate_report "${output}" "${mode}" runtime || \
		fail "runtime-data ${mode} evidence did not match the frozen 18-row inventory"
}

run_service_api_evidence() {
	local prefix="$1"
	local mode="$2"
	shift 2
	local output="${EVIDENCE_DIR}/${prefix}-service-${mode}.json"
	local errors="${EVIDENCE_DIR}/${prefix}-service-${mode}.stderr"
	local env_flags=(
		-e NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET
		-e NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID
		-e NPCINK_CLOUD_SERVICE_SETTINGS_SECRET
		-e NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID
	)
	local runtime_old_root_was_set=0
	local runtime_old_root_value=""
	local old_root_was_set=0
	local old_root_value=""
	local run_status=0
	case "${mode}" in
		dry-run|apply) env_flags+=(-e NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET) ;;
		inventory|verify) ;;
		*) fail "unsupported service-secret evidence mode" ;;
	esac
	if [ -n "${NPCINK_CLOUD_DATABASE_URL+x}" ]; then
		env_flags+=(-e NPCINK_CLOUD_DATABASE_URL)
	fi
	: >"${output}"
	: >"${errors}"
	chmod 0600 "${output}" "${errors}"
	if [ -n "${NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET+x}" ]; then
		runtime_old_root_was_set=1
		runtime_old_root_value="${NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET}"
	fi
	if [ -n "${NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET+x}" ]; then
		old_root_was_set=1
		old_root_value="${NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET}"
	fi
	unset NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET
	if [ "${mode}" != "dry-run" ] && [ "${mode}" != "apply" ]; then
		unset NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET
	fi
	if run_exact_api_one_off "${env_flags[@]}" -- \
		python -m app.dev.reencrypt_service_secrets "$@" \
		>"${output}" 2>"${errors}"; then
		run_status=0
	else
		run_status=$?
	fi
	if [ "${runtime_old_root_was_set}" = "1" ]; then
		export NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET="${runtime_old_root_value}"
	else
		unset NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET
	fi
	if [ "${old_root_was_set}" = "1" ]; then
		export NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET="${old_root_value}"
	else
		unset NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET
	fi
	if [ "${run_status}" -ne 0 ]; then
		fail "service-secret ${mode} phase failed"
	fi
	validate_report "${output}" "${mode}" service || \
		fail "service-secret ${mode} evidence did not match the frozen 12-row inventory"
}

run_api_command_evidence() {
	local label="$1"
	shift
	local output="${EVIDENCE_DIR}/${label}.stdout"
	local errors="${EVIDENCE_DIR}/${label}.stderr"
	local env_flags=(
		-e NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET
		-e NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID
		-e NPCINK_CLOUD_SERVICE_SETTINGS_SECRET
		-e NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID
	)
	local runtime_old_root_was_set=0
	local runtime_old_root_value=""
	local service_old_root_was_set=0
	local service_old_root_value=""
	local run_status=0
	if [ -n "${NPCINK_CLOUD_DATABASE_URL+x}" ]; then
		env_flags+=(-e NPCINK_CLOUD_DATABASE_URL)
	fi
	: >"${output}"
	: >"${errors}"
	chmod 0600 "${output}" "${errors}"
	if [ -n "${NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET+x}" ]; then
		runtime_old_root_was_set=1
		runtime_old_root_value="${NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET}"
	fi
	if [ -n "${NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET+x}" ]; then
		service_old_root_was_set=1
		service_old_root_value="${NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET}"
	fi
	unset NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET
	unset NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET
	if run_exact_api_one_off "${env_flags[@]}" -- "$@" \
		>"${output}" 2>"${errors}"; then
		run_status=0
	else
		run_status=$?
	fi
	if [ "${runtime_old_root_was_set}" = "1" ]; then
		export NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET="${runtime_old_root_value}"
	else
		unset NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET
	fi
	if [ "${service_old_root_was_set}" = "1" ]; then
		export NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET="${service_old_root_value}"
	else
		unset NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET
	fi
	if [ "${run_status}" -ne 0 ]; then
		fail "${label} failed"
	fi
}

CURRENT_STAGE="independent-postgres16-restore"
RESTORE_SUFFIX="$(date -u +%Y%m%d%H%M%S)_$$_${RANDOM}"
RESTORE_CONTAINER="npcink_p1e06_restore_${RESTORE_SUFFIX}"
RESTORE_VOLUME="npcink_p1e06_restore_data_${RESTORE_SUFFIX}"
RESTORE_ALIAS="p1e06-restore-${RESTORE_SUFFIX//_/-}"
RESTORE_NETWORK_IDS="$(docker network ls -q \
	--filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
	--filter "label=com.docker.compose.network=default")"
[ "$(printf '%s\n' "${RESTORE_NETWORK_IDS}" | awk 'NF {n += 1} END {print n + 0}')" -eq 1 ] || fail "managed Compose default network is not unique"
RESTORE_NETWORK_ID="${RESTORE_NETWORK_IDS}"
RESTORE_PASSWORD="$("${HOST_PYTHON}" - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
RESTORE_DB_ENV="${EVIDENCE_DIR}/.restore-database.env"
{
	printf 'POSTGRES_DB=npcink_p1e06_restore\n'
	printf 'POSTGRES_USER=npcink_p1e06_restore\n'
	printf 'POSTGRES_PASSWORD=%s\n' "${RESTORE_PASSWORD}"
} >"${RESTORE_DB_ENV}"
chmod 0600 "${RESTORE_DB_ENV}"
printf -v NPCINK_CLOUD_DATABASE_URL \
	'postgresql+psycopg://npcink_p1e06_restore:%s@%s:5432/npcink_p1e06_restore' \
	"${RESTORE_PASSWORD}" "${RESTORE_ALIAS}"
export NPCINK_CLOUD_DATABASE_URL
unset RESTORE_PASSWORD

RESTORE_POSTGRES_IMAGE_ID="$(awk -F '\t' '$1 == "postgres" { print $3 }' \
	"${NEW_DATA_SERVICE_IMAGE_IDS_FILE}")"
[[ "${RESTORE_POSTGRES_IMAGE_ID}" =~ ^sha256:[0-9a-f]{64}$ ]] || \
	fail "frozen PostgreSQL restore image ID is invalid"
assert_target_data_image_tags_frozen || fail "prepared data-service tags drifted before independent restore startup"

docker volume create "${RESTORE_VOLUME}" >/dev/null
docker run -d \
	--pull=never \
	--name "${RESTORE_CONTAINER}" \
	--network "${RESTORE_NETWORK_ID}" \
	--network-alias "${RESTORE_ALIAS}" \
	--env-file "${RESTORE_DB_ENV}" \
	-v "${RESTORE_VOLUME}:/var/lib/postgresql/data" \
	"${RESTORE_POSTGRES_IMAGE_ID}" >"${EVIDENCE_DIR}/restore-container.id"
chmod 0600 "${EVIDENCE_DIR}/restore-container.id"
assert_target_data_image_tags_frozen || fail "prepared data-service tags drifted during independent restore startup"
RESTORE_READY=0
_attempt=0
while [ "${_attempt}" -lt 30 ]; do
	if docker exec "${RESTORE_CONTAINER}" sh -c \
		'exec pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
		RESTORE_READY=1
		break
	fi
	_attempt=$((_attempt + 1))
	sleep 2
done
[ "${RESTORE_READY}" = "1" ] || fail "independent PostgreSQL restore container did not become ready"
RESTORE_SERVER_VERSION="$(docker exec "${RESTORE_CONTAINER}" sh -c \
	'exec psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "show server_version_num"')"
[[ "${RESTORE_SERVER_VERSION}" =~ ^[0-9]+$ ]] || fail "independent restore PostgreSQL version is invalid"
[ "${RESTORE_SERVER_VERSION}" -ge 160000 ] && [ "${RESTORE_SERVER_VERSION}" -lt 170000 ] || fail "independent restore must run PostgreSQL 16"
assert_backup_integrity || fail "backup changed before independent PostgreSQL restore"
if ! docker exec -i "${RESTORE_CONTAINER}" sh -c \
	'exec pg_restore --exit-on-error --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
	<"${BACKUP_PATH}" >"${EVIDENCE_DIR}/restore.stdout" 2>"${EVIDENCE_DIR}/restore.stderr"; then
	fail "independent PostgreSQL restore failed"
fi
chmod 0600 "${EVIDENCE_DIR}/restore.stdout" "${EVIDENCE_DIR}/restore.stderr"
RESTORED_SOURCE_REVISION="$(docker exec "${RESTORE_CONTAINER}" sh -c \
	'exec psql -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select version_num from alembic_version"')"
[ "${RESTORED_SOURCE_REVISION}" = "${EXPECTED_SOURCE_REVISION}" ] || fail "restored backup is not the expected 0058 source revision"

CURRENT_STAGE="independent-restore-migration-rehearsal"
run_api_command_evidence "restore-migrate-to-head" alembic upgrade head
RESTORED_TARGET_REVISION="$(docker exec "${RESTORE_CONTAINER}" sh -c \
	'exec psql -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select version_num from alembic_version"')"
[ "${RESTORED_TARGET_REVISION}" = "${EXPECTED_TARGET_REVISION}" ] || fail "independent restore migration did not reach the expected head"

CURRENT_STAGE="independent-restore-encryption-rehearsal"
run_api_evidence restore inventory inventory
run_service_api_evidence restore inventory inventory
run_api_evidence restore dry-run dry-run \
	--old-root-env NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET
run_service_api_evidence restore dry-run dry-run \
	--old-root-env NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET
run_api_evidence restore apply apply \
	--confirm-maintenance-window \
	--old-root-env NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET
run_service_api_evidence restore apply apply \
	--confirm-maintenance-window \
	--old-root-env NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET
run_api_evidence restore verify verify
run_service_api_evidence restore verify verify
"${HOST_PYTHON}" - "${EVIDENCE_DIR}/restore-proof.json" "${BACKUP_SHA256}" <<'PY'
import json
import os
import sys

path = sys.argv[1]
payload = {
    "contract": "p1_e06_independent_pg16_restore.v1",
    "status": "passed",
    "postgres_major": 16,
    "source_revision": "20260710_0058",
    "target_revision": "20260717_0068",
    "runtime_legacy_rows": 18,
    "service_legacy_rows": 12,
    "legacy_rows": 30,
    "backup_sha256": sys.argv[2],
    "plaintext_included": False,
    "ciphertext_included": False,
    "root_secret_included": False,
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, sort_keys=True)
    handle.write("\n")
os.chmod(path, 0o600)
PY
cleanup_restore_resources || fail "independent restore resources could not be removed"
RESTORE_CONTAINER=""
RESTORE_VOLUME=""
RESTORE_DB_ENV=""
unset NPCINK_CLOUD_DATABASE_URL

CURRENT_STAGE="switch-production-data-services-to-target-images"
assert_no_running_writers || fail "a labelled or old/new-image writer reappeared before the data-service switch"
assert_database_clients_quiesced
[ "$(database_revision)" = "${EXPECTED_SOURCE_REVISION}" ] || fail "production revision changed before migration"
assert_backup_integrity || fail "backup changed before the production data-service switch"
assert_target_data_image_tags_frozen || fail "prepared PostgreSQL/Redis tags drifted before the data-service switch"
DATA_SWITCH_ATTEMPTED=1
if ! release_helper \
	NPCINK_CLOUD_LOAD_MODE=data-only \
	bash "${STAGED_RELEASE}/deploy/remote-load-and-up.sh" \
	>"${EVIDENCE_DIR}/data-service-switch.log" 2>&1; then
	fail "PostgreSQL/Redis could not be switched to the exact target bundle images"
fi
chmod 0600 "${EVIDENCE_DIR}/data-service-switch.log"
DATA_SERVICES_SWITCHED=1
assert_target_data_image_tags_frozen || fail "prepared PostgreSQL/Redis tags drifted during the data-service switch"
assert_new_data_services_healthy "${EXPECTED_SOURCE_REVISION}" || \
	fail "target PostgreSQL/Redis services are not healthy at revision 0058"

CURRENT_STAGE="recheck-production-fence-before-migration"
assert_no_running_writers || fail "a labelled or old/new-image writer reappeared before production migration"
assert_database_clients_quiesced
assert_backup_integrity || fail "backup changed before production migration"
assert_new_data_services_healthy "${EXPECTED_SOURCE_REVISION}" || \
	fail "target PostgreSQL/Redis proof drifted before production migration"
assert_maintenance_env_source_unchanged || \
	fail "maintenance env changed before production migration"

CURRENT_STAGE="production-migrate-0058-to-head"
MIGRATION_STARTED=1
run_api_command_evidence "production-migrate-to-head" alembic upgrade head
[ "$(database_revision)" = "${EXPECTED_TARGET_REVISION}" ] || fail "production migration did not reach the expected head"

CURRENT_STAGE="production-encryption-inventory"
assert_no_running_writers || fail "a labelled or old/new-image writer appeared after migration"
assert_database_clients_quiesced
run_api_evidence production inventory inventory
run_service_api_evidence production inventory inventory

CURRENT_STAGE="production-encryption-dry-run"
run_api_evidence production dry-run dry-run \
	--old-root-env NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET
run_service_api_evidence production dry-run dry-run \
	--old-root-env NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET

CURRENT_STAGE="production-encryption-apply"
assert_no_running_writers || fail "a labelled or old/new-image writer appeared before encryption apply"
assert_database_clients_quiesced
run_api_evidence production apply apply \
	--confirm-maintenance-window \
	--old-root-env NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET
run_service_api_evidence production apply apply \
	--confirm-maintenance-window \
	--old-root-env NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET

CURRENT_STAGE="production-encryption-new-key-only-verify"
run_api_evidence production verify verify
run_service_api_evidence production verify verify

CURRENT_STAGE="recheck-maintenance-env-before-activation"
assert_maintenance_env_source_unchanged || \
	fail "maintenance env changed before staged runtime-key activation"

CURRENT_STAGE="activate-staged-runtime-key"
"${HOST_PYTHON}" - "${STAGED_ENV_FILE}" "${MAINTENANCE_ENV_SNAPSHOT}" <<'PY' || fail "staged env could not be updated safely"
from __future__ import annotations

import os
import sys
from pathlib import Path

target_path = Path(sys.argv[1])
maintenance_path = Path(sys.argv[2])
target_keys = {
    "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET",
    "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID",
    "NPCINK_CLOUD_SERVICE_SETTINGS_SECRET",
    "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID",
}
removed_keys = target_keys | {
    "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET",
    "NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET",
}
selected: dict[str, str] = {}
for line in maintenance_path.read_text(encoding="utf-8").splitlines():
    if "=" not in line:
        continue
    key, _value = line.split("=", 1)
    if key in target_keys:
        selected[key] = line
if set(selected) != target_keys:
    raise SystemExit(1)
kept: list[str] = []
for line in target_path.read_text(encoding="utf-8").splitlines():
    key = line.split("=", 1)[0] if "=" in line else ""
    if key not in removed_keys:
        kept.append(line)
kept.extend(selected[key] for key in sorted(target_keys))
temporary = target_path.with_name(f".{target_path.name}.p1e06.{os.getpid()}")
with temporary.open("x", encoding="utf-8") as handle:
    handle.write("\n".join(kept).rstrip("\n") + "\n")
    handle.flush()
    os.fsync(handle.fileno())
os.chmod(temporary, 0o600)
os.replace(temporary, target_path)
directory_fd = os.open(target_path.parent, os.O_RDONLY)
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
[ "$(mode_of "${STAGED_ENV_FILE}")" = "600" ] || fail "updated staged env must have mode 0600"
[ "$("${HOST_PYTHON}" - "${STAGED_ENV_FILE}" <<'PY'
import sys
from pathlib import Path

legacy_keys = {
    "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET",
    "NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET",
}
keys = {
    line.split("=", 1)[0]
    for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    if "=" in line
}
print("absent" if legacy_keys.isdisjoint(keys) else "present")
PY
)" = "absent" ] || fail "active staged env retained the legacy root secret"
[ "$(sha256sum "${CURRENT_ENV_FILE}" | awk '{print $1}')" = "${CURRENT_ENV_SHA256}" ] || fail "previous release env changed during cutover"

CURRENT_STAGE="activate-staged-release-pointer"
assert_no_running_writers || fail "a labelled or old/new-image writer appeared before pointer activation"
NEXT_LINK="${CURRENT_LINK}.next.$$"
rm -f "${NEXT_LINK}"
ln -s "${STAGED_RELEASE}" "${NEXT_LINK}"
mv -Tf "${NEXT_LINK}" "${CURRENT_LINK}"
POINTER_ACTIVATED=1
[ "$(readlink -f "${CURRENT_LINK}")" = "${STAGED_RELEASE}" ] || fail "staged release pointer activation failed"

run_helper_evidence() {
	local label="$1"
	shift
	local log="${EVIDENCE_DIR}/${label}.log"
	: >"${log}"
	chmod 0600 "${log}"
	if ! release_helper "$@" >"${log}" 2>&1; then
		fail "${label} failed"
	fi
}

CURRENT_STAGE="start-new-api"
run_helper_evidence start-new-api \
	NPCINK_CLOUD_LOAD_MODE=api-only \
	bash "${STAGED_RELEASE}/deploy/remote-load-and-up.sh"

CURRENT_STAGE="start-new-workers"
WORKER_CUTOFF="$("${HOST_PYTHON}" - <<'PY'
from datetime import datetime, timezone

print(datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"))
PY
)"
printf '%s\n' "${WORKER_CUTOFF}" >"${EVIDENCE_DIR}/worker-cutoff.txt"
chmod 0600 "${EVIDENCE_DIR}/worker-cutoff.txt"
run_helper_evidence start-new-workers \
	NPCINK_CLOUD_LOAD_MODE=workers-only \
	bash "${STAGED_RELEASE}/deploy/remote-load-and-up.sh"

CURRENT_STAGE="prove-new-worker-generation"
BASE_URL="$(npcink_ai_cloud_read_env_value "${STAGED_ENV_FILE}" NPCINK_CLOUD_BASE_URL || true)"
[ -n "${BASE_URL}" ] || fail "staged production base URL is missing"
run_helper_evidence operational-ready \
	NPCINK_CLOUD_OPERATIONAL_READY_INTERNAL=1 \
	bash "${STAGED_RELEASE}/deploy/remote-operational-ready.sh" \
	--base-url "${BASE_URL}" \
	--worker-cutoff "${WORKER_CUTOFF}"

CURRENT_STAGE="restore-public-traffic"
run_helper_evidence restore-public-traffic \
	NPCINK_CLOUD_LOAD_MODE=traffic-only \
	bash "${STAGED_RELEASE}/deploy/remote-load-and-up.sh"

CURRENT_STAGE="validate-active-release"
run_helper_evidence baseline-status \
	bash "${STAGED_RELEASE}/deploy/remote-baseline-status.sh"

CURRENT_STAGE="prepare-private-success-evidence"
FINAL_RESULT_TMP="${PASSED_RESULT}.tmp.$$"
"${HOST_PYTHON}" - \
	"${FINAL_RESULT_TMP}" "${BACKUP_SHA256}" "${PREVIOUS_RELEASE}" "${STAGED_RELEASE}" \
	"${OFF_HOST_RECEIPT}" "${RECEIPT_SHA256}" "${RECEIPT_EVIDENCE}" <<'PY'
import json
import os
import sys

path = sys.argv[1]
payload = {
    "contract": "p1_e06_runtime_data_encryption_cutover.v1",
    "status": "passed",
    "source_revision": "20260710_0058",
    "target_revision": "20260717_0068",
    "runtime_legacy_rows_migrated": 18,
    "service_legacy_rows_migrated": 12,
    "legacy_rows_migrated": 30,
    "backup_sha256": sys.argv[2],
    "previous_release": sys.argv[3],
    "active_release": sys.argv[4],
    "off_host_receipt": sys.argv[5],
    "off_host_receipt_sha256": sys.argv[6],
    "off_host_receipt_evidence": sys.argv[7],
    "off_host_copy_verified": True,
    "independent_postgres16_restore_verified": True,
    "exact_data_service_images_activated": True,
    "activation_committed": True,
    "old_code_automatically_restarted_after_failure": False,
    "whole_database_restore_required_for_rollback": True,
    "plaintext_included": False,
    "ciphertext_included": False,
    "root_secret_included": False,
}
with open(path, "x", encoding="utf-8") as handle:
    json.dump(payload, handle, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.chmod(path, 0o600)
PY

CURRENT_STAGE="final-validation-before-unlock"
assert_maintenance_env_source_unchanged || \
	fail "maintenance env changed before final activation validation"
[ "$(readlink -f "${CURRENT_LINK}")" = "${STAGED_RELEASE}" ] || fail "active release pointer drifted before completion"
[ "$(sha256sum "${CURRENT_ENV_FILE}" | awk '{print $1}')" = "${CURRENT_ENV_SHA256}" ] || fail "previous recovery env drifted before completion"
[ "$(mode_of "${STAGED_ENV_FILE}")" = "600" ] || fail "active release env mode drifted before completion"
[ "$(stat -c '%u' "${STAGED_ENV_FILE}")" = "0" ] || fail "active release env must remain owned by root"
ACTIVE_DOMAIN_NAME="$(npcink_ai_cloud_read_env_value "${STAGED_ENV_FILE}" NPCINK_CLOUD_DOMAIN_NAME || true)"
loopback_edge_health "${BASE_URL}" "${ACTIVE_DOMAIN_NAME}" || fail "final loopback-resolved HTTPS health failed"
assert_new_api_tag_frozen || fail "prepared API tag drifted before activation commit"
assert_target_data_image_tags_frozen || fail "prepared data-service tags drifted before activation commit"
assert_new_data_services_healthy "${EXPECTED_TARGET_REVISION}" || fail "active data services are not the exact target images at revision 0068"
assert_backup_integrity || fail "backup changed before activation commit"
[ -f "${RECEIPT_EVIDENCE}" ] && [ ! -L "${RECEIPT_EVIDENCE}" ] && \
	[ "$(mode_of "${RECEIPT_EVIDENCE}")" = "600" ] || fail "validated off-host receipt evidence drifted"
[ -f "${FINAL_RESULT_TMP}" ] && [ "$(mode_of "${FINAL_RESULT_TMP}")" = "600" ] || \
	fail "private terminal success evidence is not ready"

CURRENT_STAGE="commit-validated-activation"
"${HOST_PYTHON}" - \
	"${ACTIVATION_COMMIT_MARKER}" "${STAGED_RELEASE}" "${BACKUP_SHA256}" "${RECEIPT_SHA256}" <<'PY'
import json
import os
import sys

path, active_release, backup_sha256, receipt_sha256 = sys.argv[1:]
payload = {
    "contract": "p1_e06_activation_commit.v1",
    "status": "committed",
    "active_release": active_release,
    "database_revision": "20260717_0068",
    "runtime_legacy_rows_migrated": 18,
    "service_legacy_rows_migrated": 12,
    "legacy_rows_migrated": 30,
    "backup_sha256": backup_sha256,
    "off_host_receipt_sha256": receipt_sha256,
}
with open(path, "x", encoding="utf-8") as handle:
    json.dump(payload, handle, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.chmod(path, 0o600)
directory_fd = os.open(os.path.dirname(path), os.O_RDONLY)
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
ACTIVATION_COMMITTED=1

CURRENT_STAGE="remove-frozen-maintenance-env"
cleanup_private_cutover_artifacts || \
	fail "frozen maintenance env or temporary activation receipt could not be removed"

CURRENT_STAGE="cleanup-rollback-images-and-map"
discard_rollback_image_tags_and_map || fail "rollback image tag/map cleanup failed"
[ ! -e "${ROLLBACK_IMAGE_MAP}" ] || fail "rollback image map remains after cleanup"

CURRENT_STAGE="publish-terminal-success-evidence"
publish_fresh_file "${FINAL_RESULT_TMP}" "${PASSED_RESULT}"
FINAL_RESULT_TMP=""
fsync_paths_and_parents "${PASSED_RESULT}"

CURRENT_STAGE="publish-global-activation-receipt"
ACTIVATION_COMMIT_SHA256="$(sha256sum "${ACTIVATION_COMMIT_MARKER}" | awk '{print $1}')"
CUTOVER_RESULT_SHA256="$(sha256sum "${PASSED_RESULT}" | awk '{print $1}')"
[[ "${ACTIVATION_COMMIT_SHA256}" =~ ^[0-9a-f]{64}$ ]] || \
	fail "activation commit digest is invalid"
[[ "${CUTOVER_RESULT_SHA256}" =~ ^[0-9a-f]{64}$ ]] || \
	fail "cutover result digest is invalid"
GLOBAL_ACTIVATION_RECEIPT_TMP="${GLOBAL_ACTIVATION_RECEIPT}.tmp.$$"
"${HOST_PYTHON}" - \
	"${GLOBAL_ACTIVATION_RECEIPT_TMP}" \
	"${STAGED_RELEASE}" \
	"${ACTIVATION_COMMIT_SHA256}" \
	"${CUTOVER_RESULT_SHA256}" \
	"${EXPECTED_SOURCE_REVISION}" \
	"${EXPECTED_TARGET_REVISION}" \
	"${EXPECTED_RUNTIME_LEGACY_TOTAL}" \
	"${EXPECTED_SERVICE_LEGACY_TOTAL}" \
	"${EXPECTED_LEGACY_TOTAL}" <<'PY' || fail "global activation receipt could not be prepared"
import json
import os
import sys

(
    path,
    active_release,
    activation_commit_sha256,
    cutover_result_sha256,
    source_revision,
    target_revision,
    runtime_legacy_rows_migrated,
    service_legacy_rows_migrated,
    legacy_rows_migrated,
) = sys.argv[1:]
payload = {
    "contract": "p1_e06_global_activation.v1",
    "status": "passed",
    "source_revision": source_revision,
    "target_revision": target_revision,
    "runtime_legacy_rows_migrated": int(runtime_legacy_rows_migrated),
    "service_legacy_rows_migrated": int(service_legacy_rows_migrated),
    "legacy_rows_migrated": int(legacy_rows_migrated),
    "active_release": active_release,
    "activation_commit_sha256": activation_commit_sha256,
    "cutover_result_sha256": cutover_result_sha256,
}
with open(path, "x", encoding="utf-8") as handle:
    json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.chmod(path, 0o600)
PY
[ -f "${GLOBAL_ACTIVATION_RECEIPT_TMP}" ] && \
	[ ! -L "${GLOBAL_ACTIVATION_RECEIPT_TMP}" ] && \
	[ "$(mode_of "${GLOBAL_ACTIVATION_RECEIPT_TMP}")" = "600" ] && \
	[ "$(stat -c '%u' "${GLOBAL_ACTIVATION_RECEIPT_TMP}")" = "0" ] || \
	fail "prepared global activation receipt is not a root-owned mode-0600 regular file"
publish_fresh_file "${GLOBAL_ACTIVATION_RECEIPT_TMP}" "${GLOBAL_ACTIVATION_RECEIPT}"
GLOBAL_ACTIVATION_RECEIPT_TMP=""
fsync_paths_and_parents "${GLOBAL_ACTIVATION_RECEIPT}"
[ -f "${GLOBAL_ACTIVATION_RECEIPT}" ] && \
	[ ! -L "${GLOBAL_ACTIVATION_RECEIPT}" ] && \
	[ "$(mode_of "${GLOBAL_ACTIVATION_RECEIPT}")" = "600" ] && \
	[ "$(stat -c '%u' "${GLOBAL_ACTIVATION_RECEIPT}")" = "0" ] || \
	fail "published global activation receipt is not a root-owned mode-0600 regular file"

CURRENT_STAGE="release-deploy-lock"
# A signal between filesystem unlock and the corresponding in-memory commit
# flags could otherwise make EXIT believe a missing lock was still held.
# Terminal activation is already committed, so ignore terminal signals across
# this short non-interruptible unlock/state transition.
trap '' HUP INT TERM
rm -f "${FAILURE_MARKER}" >/dev/null 2>&1 || fail "stale failure marker could not be removed"
rm -f -- "${DEPLOY_LOCK_OWNER_FILE}" || fail "deployment lock owner cleanup failed"
[ ! -e "${DEPLOY_LOCK_OWNER_FILE}" ] && [ ! -L "${DEPLOY_LOCK_OWNER_FILE}" ] || \
	fail "deployment lock owner cleanup could not be proved"
unset NPCINK_CLOUD_DEPLOY_LOCK_OWNER
DEPLOY_LOCK_OWNER=""
rmdir "${DEPLOY_LOCK_DIR}" || fail "deployment lock could not be released"
LOCK_HELD=0
CUTOVER_SUCCEEDED=1
CURRENT_STAGE="complete"
