#!/usr/bin/env bash
set -Eeuo pipefail
set +x

umask 077

CONTRACT="p1_e06_full_recovery.v1"
FULL_RESTORE_ACK="I_ACKNOWLEDGE_THE_MATCHED_P1_E06_FULL_RECOVERY"
WRITE_LOSS_ACK="I_ACCEPT_LOSS_OF_POST_BACKUP_CUTOVER_WRITES"
EXPECTED_SOURCE_REVISION="20260710_0058"

usage() {
	cat <<'EOF'
Usage: deploy/runtime-data-encryption-recovery.sh \
  --remote-dir /opt/npcink-ai-cloud \
  --failure-marker /opt/npcink-ai-cloud/.cutover-failed \
  --host-python /usr/bin/python3.11 \
  [--preflight-only] \
  --confirm-full-restore I_ACKNOWLEDGE_THE_MATCHED_P1_E06_FULL_RECOVERY \
  --confirm-write-loss I_ACCEPT_LOSS_OF_POST_BACKUP_CUTOVER_WRITES

Recover only a failed P1-E06 migration that reached database migration but did
not publish activation-commit.json. The failure marker is the sole recovery
point selector. Secret values are read only from protected snapshots and never
accepted through argv or written to ordinary output.
EOF
}

CURRENT_STAGE="preflight"
fail() {
	printf '[p1-e06-recovery:fail] stage=%s %s\n' "${CURRENT_STAGE}" "$*" >&2
	exit 1
}

require_cmd() {
	command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

mode_of() {
	stat -c '%a' "$1"
}

REMOTE_DIR=""
FAILURE_MARKER=""
HOST_PYTHON_CANDIDATE=""
CONFIRM_FULL_RESTORE=""
CONFIRM_WRITE_LOSS=""
PREFLIGHT_ONLY=0

while [ "$#" -gt 0 ]; do
	case "$1" in
		--remote-dir)
			[ "$#" -ge 2 ] || fail "--remote-dir requires a path"
			REMOTE_DIR="$2"
			shift 2
			;;
		--failure-marker)
			[ "$#" -ge 2 ] || fail "--failure-marker requires a path"
			FAILURE_MARKER="$2"
			shift 2
			;;
		--host-python)
			[ "$#" -ge 2 ] || fail "--host-python requires a path"
			HOST_PYTHON_CANDIDATE="$2"
			shift 2
			;;
		--preflight-only)
			PREFLIGHT_ONLY=1
			shift
			;;
		--confirm-full-restore)
			[ "$#" -ge 2 ] || fail "--confirm-full-restore requires the exact acknowledgement"
			CONFIRM_FULL_RESTORE="$2"
			shift 2
			;;
		--confirm-write-loss)
			[ "$#" -ge 2 ] || fail "--confirm-write-loss requires the exact acknowledgement"
			CONFIRM_WRITE_LOSS="$2"
			shift 2
			;;
		-h|--help)
			usage
			exit 0
			;;
		*) fail "unsupported argument" ;;
	esac
done

[ "$(id -u)" = "0" ] || fail "recovery must run as root"
[ -n "${REMOTE_DIR}" ] && [ -n "${FAILURE_MARKER}" ] && [ -n "${HOST_PYTHON_CANDIDATE}" ] || \
	fail "remote dir, failure marker, and host Python are required"
[ "${CONFIRM_FULL_RESTORE}" = "${FULL_RESTORE_ACK}" ] || fail "full recovery acknowledgement is missing"
[ "${CONFIRM_WRITE_LOSS}" = "${WRITE_LOSS_ACK}" ] || fail "post-backup write-loss acknowledgement is missing"
[[ "${REMOTE_DIR}" = /* ]] && [[ "${REMOTE_DIR}" =~ ^/[A-Za-z0-9._/-]+$ ]] || fail "remote dir is invalid"
[ "${REMOTE_DIR}" != "/" ] || fail "remote dir must not be root"
[ "${FAILURE_MARKER}" = "${REMOTE_DIR}/.cutover-failed" ] || fail "failure marker must be the managed canonical path"

for command_name in docker curl nginx systemctl sha256sum stat readlink awk sed find flock; do
	require_cmd "${command_name}"
done

HOST_PYTHON="$(command -v -- "${HOST_PYTHON_CANDIDATE}" 2>/dev/null || true)"
[ -n "${HOST_PYTHON}" ] && [ -x "${HOST_PYTHON}" ] || fail "host Python is unavailable"
HOST_PYTHON="$(readlink -f "${HOST_PYTHON}")"
"${HOST_PYTHON}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || \
	fail "host Python 3.11 or newer is required"

# Recovery-point selection is local filesystem state. Never let ambient Docker
# context variables redirect the matching container/database mutations to a
# different daemon.
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DOCKER_CERT_PATH DOCKER_TLS_VERIFY DOCKER_API_VERSION
DOCKER_ENDPOINT="$(docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)"
[[ "${DOCKER_ENDPOINT}" = unix:///* ]] || fail "recovery requires the local Docker Unix socket"
export DOCKER_HOST="${DOCKER_ENDPOINT}"
DOCKER_DAEMON_ID="$(docker info --format '{{.ID}}' 2>/dev/null || true)"
[[ "${DOCKER_DAEMON_ID}" =~ ^[A-Za-z0-9._:-]{8,128}$ ]] || fail "local Docker daemon identity is unavailable"

assert_local_docker_identity() {
	local observed=""
	[[ "${DOCKER_HOST:-}" = unix:///* ]] || return 1
	[ -z "${DOCKER_CONTEXT:-}" ] && [ -z "${DOCKER_CONFIG:-}" ] && \
		[ -z "${DOCKER_CERT_PATH:-}" ] && [ -z "${DOCKER_TLS_VERIFY:-}" ] || return 1
	observed="$(docker info --format '{{.ID}}' 2>/dev/null || true)"
	[ "${observed}" = "${DOCKER_DAEMON_ID}" ]
}

[ -d "${REMOTE_DIR}" ] && [ ! -L "${REMOTE_DIR}" ] || fail "managed remote dir is missing or unsafe"
[ "$(stat -c '%u' "${REMOTE_DIR}")" = "0" ] || fail "managed remote dir must be root-owned"
REMOTE_DIR_MODE="$(mode_of "${REMOTE_DIR}")"
[[ "${REMOTE_DIR_MODE}" =~ ^[0-7]{3,4}$ ]] && (( (8#${REMOTE_DIR_MODE} & 0022) == 0 )) || \
	fail "managed remote dir must not be group/world writable"

# Serialize the entire preflight/recovery/terminalization state machine on the
# retained deploy-lock directory inode. The descriptor remains locked even
# after successful terminalization removes the directory entry.
EARLY_DEPLOY_LOCK="${REMOTE_DIR}/.deploy-lock"
[ -d "${EARLY_DEPLOY_LOCK}" ] && [ ! -L "${EARLY_DEPLOY_LOCK}" ] || \
	fail "retained deploy lock is missing or unsafe"
[ "$(mode_of "${EARLY_DEPLOY_LOCK}")" = "700" ] && \
	[ "$(stat -c '%u' "${EARLY_DEPLOY_LOCK}")" = "0" ] || \
	fail "retained deploy lock must be root-owned mode 0700"
exec {RECOVERY_EXECUTION_LOCK_FD}<"${EARLY_DEPLOY_LOCK}" || fail "retained deploy lock inode cannot be opened"
flock -n "${RECOVERY_EXECUTION_LOCK_FD}" || fail "another recovery or recovery preflight is already running"

# A committed recovery removes the canonical failure marker before it removes
# the deploy lock. If the host loses power in that narrow window, reconstruct
# only the two canonical lock inputs from hard-linked, result-bound archives.
# Preflight never performs this repair: its contract is strictly read-only.
if [ ! -e "${FAILURE_MARKER}" ] && [ ! -L "${FAILURE_MARKER}" ]; then
	CURRENT_STAGE="detect-interrupted-terminalization"
	TERMINALIZATION_STATE="$({
		"${HOST_PYTHON}" - "${REMOTE_DIR}" "${FAILURE_MARKER}" "${PREFLIGHT_ONLY}" <<'PY'
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import stat
import sys

remote_dir, marker_path, preflight = sys.argv[1:]
state_root = os.path.join(remote_dir, ".release-state")
lock_path = os.path.join(remote_dir, ".deploy-lock")

def protected_file(path: str, mode: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != mode
            or metadata.st_uid != 0
        ):
            raise SystemExit(1)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)

result_paths = glob.glob(
    os.path.join(
        state_root,
        "release-*",
        "p1-e06-runtime-data-cutover",
        "recovery-result.json",
    )
)
valid: list[tuple[str, str, str, dict[str, object]]] = []
for result_path in result_paths:
    evidence_dir = os.path.dirname(result_path)
    archive_path = os.path.join(evidence_dir, "failure-before-recovery.txt")
    owner_archive = os.path.join(evidence_dir, "recovery-lock-owner.txt")
    try:
        result_raw = protected_file(result_path, 0o600)
        archive_raw = protected_file(archive_path, 0o600)
        owner_raw = protected_file(owner_archive, 0o600)
        result = json.loads(result_raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        continue
    if not isinstance(result, dict):
        continue
    failed_release = str(result.get("failed_release") or "")
    active_release = str(result.get("active_release") or "")
    if (
        result.get("contract") != "p1_e06_full_recovery.v1"
        or result.get("status") != "passed"
        or result.get("database_revision") != "20260710_0058"
        or os.path.dirname(failed_release) != remote_dir
        or os.path.dirname(active_release) != remote_dir
        or not re.fullmatch(r"release-[A-Za-z0-9._-]+", os.path.basename(failed_release))
        or not re.fullmatch(r"release-[A-Za-z0-9._-]+", os.path.basename(active_release))
        or hashlib.sha256(archive_raw).hexdigest() != result.get("failure_marker_sha256")
        or hashlib.sha256(owner_raw).hexdigest() != result.get("deploy_lock_owner_sha256")
    ):
        continue
    marker_values: dict[str, str] = {}
    try:
        for raw_line in archive_raw.decode("utf-8").splitlines():
            if not raw_line or "=" not in raw_line:
                raise ValueError
            key, value = raw_line.split("=", 1)
            if key in marker_values or not value:
                raise ValueError
            marker_values[key] = value
    except (UnicodeDecodeError, ValueError):
        continue
    if (
        marker_values.get("contract") != "p1_e06_runtime_data_encryption_cutover.v1"
        or marker_values.get("status") != "failed"
        or marker_values.get("migration_started") != "1"
        or marker_values.get("activation_committed") != "0"
        or marker_values.get("failed_release") != failed_release
        or marker_values.get("previous_release") != active_release
        or os.path.dirname(marker_values.get("previous_external_env_snapshot", ""))
        != evidence_dir
    ):
        continue
    valid.append((archive_path, owner_archive, evidence_dir, result))

if len(valid) != 1:
    raise SystemExit(1)
archive_path, owner_archive, _evidence_dir, _result = valid[0]
if os.path.lexists(lock_path):
    lock_meta = os.lstat(lock_path)
    if (
        not stat.S_ISDIR(lock_meta.st_mode)
        or stat.S_IMODE(lock_meta.st_mode) != 0o700
        or lock_meta.st_uid != 0
    ):
        raise SystemExit(1)
    entries = sorted(os.listdir(lock_path))
    if entries not in ([], ["one-off-owner"]):
        raise SystemExit(1)
    if preflight == "1":
        print("repair-required")
        raise SystemExit(0)
    owner_path = os.path.join(lock_path, "one-off-owner")
    if entries == []:
        os.link(owner_archive, owner_path, follow_symlinks=False)
        lock_fd = os.open(lock_path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(lock_fd)
        finally:
            os.close(lock_fd)
    else:
        owner_raw = protected_file(owner_path, 0o600)
        if hashlib.sha256(owner_raw).hexdigest() != _result.get("deploy_lock_owner_sha256"):
            raise SystemExit(1)
    os.link(archive_path, marker_path, follow_symlinks=False)
    remote_fd = os.open(remote_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(remote_fd)
    finally:
        os.close(remote_fd)
    print("repaired")
else:
    print("completed")
PY
	} 2>/dev/null)" || fail "missing failure marker does not match one committed recovery"
	case "${TERMINALIZATION_STATE}" in
		completed)
			fail "committed recovery appears terminalized; verify the healthy runtime instead of recreating recovery state"
			;;
		repaired)
			printf '[p1-e06-recovery] repaired interrupted terminalization inputs from committed evidence.\n'
			;;
		repair-required)
			fail "preflight found an interrupted terminalization; run the acknowledged recovery command to repair it"
			;;
		*) fail "missing failure marker state is invalid" ;;
	esac
fi
[ -f "${FAILURE_MARKER}" ] && [ ! -L "${FAILURE_MARKER}" ] || fail "failure marker is missing or unsafe"
[ "$(mode_of "${FAILURE_MARKER}")" = "600" ] && [ "$(stat -c '%u' "${FAILURE_MARKER}")" = "0" ] || \
	fail "failure marker must be root-owned mode 0600"

CURRENT_STAGE="parse-frozen-failure-contract"
MARKER_FIELDS="$("${HOST_PYTHON}" - "${FAILURE_MARKER}" "${REMOTE_DIR}" <<'PY'
from __future__ import annotations

import os
import re
import sys

marker_path, remote_dir = sys.argv[1:]
allowed = {
    "contract", "status", "phase", "outcome", "recovery", "failed_release",
    "previous_release", "observed_current_release", "migration_started",
    "data_switch_attempted", "data_services_switched", "image_tags_restored",
    "previous_data_services_restored", "previous_runtime_restored",
    "post_migration_writer_stop_proved", "activation_committed",
    "previous_external_env", "previous_external_env_snapshot",
    "previous_external_env_snapshot_sha256", "edge_readiness_handoff_evidence",
    "edge_readiness_handoff_evidence_sha256", "maintenance_env_snapshot",
    "maintenance_env_snapshot_sha256", "required_old_root_env_names",
    "database_recovery_point", "off_host_receipt", "off_host_receipt_sha256",
    "conflicting_terminal_evidence",
}
values: dict[str, str] = {}
with open(marker_path, "r", encoding="utf-8") as handle:
    for raw in handle:
        line = raw.rstrip("\n")
        if not line or "=" not in line:
            raise SystemExit(1)
        key, value = line.split("=", 1)
        if key not in allowed or key in values or not value or any(c in value for c in "\r\t"):
            raise SystemExit(1)
        values[key] = value
required_exact = {
    "contract": "p1_e06_runtime_data_encryption_cutover.v1",
    "status": "failed",
    "phase": "restore-public-traffic",
    "outcome": "full_database_restore_required",
    "recovery": "restore_whole_database_previous_release_external_env_and_both_old_roots_together",
    "migration_started": "1",
    "data_switch_attempted": "1",
    "data_services_switched": "1",
    "post_migration_writer_stop_proved": "1",
    "activation_committed": "0",
    "required_old_root_env_names": "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET,NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET",
}
for key, expected in required_exact.items():
    if values.get(key) != expected:
        raise SystemExit(1)
path_keys = (
    "failed_release", "previous_release", "previous_external_env",
    "previous_external_env_snapshot", "edge_readiness_handoff_evidence",
    "maintenance_env_snapshot", "database_recovery_point", "off_host_receipt",
)
safe_path = re.compile(r"/[A-Za-z0-9._/-]+")
for key in path_keys:
    value = values.get(key, "")
    if not safe_path.fullmatch(value) or os.path.normpath(value) != value:
        raise SystemExit(1)
for key in (
    "previous_external_env_snapshot_sha256", "edge_readiness_handoff_evidence_sha256",
    "maintenance_env_snapshot_sha256", "off_host_receipt_sha256",
):
    if not re.fullmatch(r"[0-9a-f]{64}", values.get(key, "")):
        raise SystemExit(1)
failed = values["failed_release"]
previous = values["previous_release"]
if os.path.dirname(failed) != remote_dir or os.path.dirname(previous) != remote_dir:
    raise SystemExit(1)
if not re.fullmatch(r"release-[A-Za-z0-9._-]+", os.path.basename(failed)):
    raise SystemExit(1)
if not re.fullmatch(r"release-[A-Za-z0-9._-]+", os.path.basename(previous)):
    raise SystemExit(1)
previous_state = os.path.join(remote_dir, ".release-state", os.path.basename(previous))
if values["previous_external_env"] != os.path.join(previous_state, "env.deploy"):
    raise SystemExit(1)
evidence = os.path.dirname(values["previous_external_env_snapshot"])
expected_evidence = os.path.join(
    remote_dir, ".release-state", os.path.basename(failed), "p1-e06-runtime-data-cutover"
)
if evidence != expected_evidence:
    raise SystemExit(1)
if values["maintenance_env_snapshot"] != os.path.join(evidence, ".maintenance-env.snapshot"):
    raise SystemExit(1)
if values["edge_readiness_handoff_evidence"] != os.path.join(evidence, "edge-readiness-env-handoff.json"):
    raise SystemExit(1)
print("\t".join(values[key] for key in (
    "failed_release", "previous_release", "previous_external_env",
    "previous_external_env_snapshot", "previous_external_env_snapshot_sha256",
    "edge_readiness_handoff_evidence", "edge_readiness_handoff_evidence_sha256",
    "maintenance_env_snapshot", "maintenance_env_snapshot_sha256",
    "database_recovery_point", "off_host_receipt", "off_host_receipt_sha256",
)))
PY
)" || fail "failure marker contract is invalid"

IFS=$'\t' read -r \
	FAILED_RELEASE PREVIOUS_RELEASE PREVIOUS_ENV ENV_SNAPSHOT ENV_SNAPSHOT_SHA256 \
	EDGE_HANDOFF EDGE_HANDOFF_SHA256 MAINTENANCE_SNAPSHOT MAINTENANCE_SNAPSHOT_SHA256 \
	BACKUP_PATH OFF_HOST_RECEIPT OFF_HOST_RECEIPT_SHA256 <<<"${MARKER_FIELDS}"
unset MARKER_FIELDS

EVIDENCE_DIR="$(dirname "${ENV_SNAPSHOT}")"
ROLLBACK_IMAGE_MAP="${EVIDENCE_DIR}/rollback-images.tsv"
OLD_DATA_STATE="${EVIDENCE_DIR}/old-data-service-state.tsv"
OLD_WRITER_IMAGE_IDS="${EVIDENCE_DIR}/old-writer-image-ids.txt"
OFF_HOST_RECEIPT_EVIDENCE="${EVIDENCE_DIR}/off-host-receipt-verified.json"
ACTIVATION_COMMIT="${EVIDENCE_DIR}/activation-commit.json"
CUTOVER_RESULT="${EVIDENCE_DIR}/cutover-result.json"
GLOBAL_ACTIVATION_RECEIPT="${REMOTE_DIR}/.release-state/p1-e06-activation.json"
RECOVERY_RESULT="${EVIDENCE_DIR}/recovery-result.json"
RECOVERY_IMAGE_PLAN="${EVIDENCE_DIR}/recovery-images.tsv"
ARCHIVED_FAILURE="${EVIDENCE_DIR}/failure-before-recovery.txt"
RECOVERY_LOCK_OWNER_ARCHIVE="${EVIDENCE_DIR}/recovery-lock-owner.txt"
DEPLOY_LOCK="${REMOTE_DIR}/.deploy-lock"
LOCK_OWNER_FILE="${DEPLOY_LOCK}/one-off-owner"
CURRENT_LINK="${REMOTE_DIR}/current"
MARKER_SHA256="$(sha256sum "${FAILURE_MARKER}" | awk '{print $1}')"

assert_protected_file() {
	local path="$1"
	local expected_mode="$2"
	[ -f "${path}" ] && [ ! -L "${path}" ] || return 1
	[ "$(stat -c '%u' "${path}")" = "0" ] || return 1
	[ "$(mode_of "${path}")" = "${expected_mode}" ]
}

assert_digest() {
	local path="$1"
	local expected="$2"
	[ "$(sha256sum "${path}" | awk '{print $1}')" = "${expected}" ]
}

assert_secure_directory() {
	local path="$1"
	local mode=""
	[ -d "${path}" ] && [ ! -L "${path}" ] || return 1
	[ "$(stat -c '%u' "${path}")" = "0" ] || return 1
	mode="$(mode_of "${path}")"
	[[ "${mode}" =~ ^[0-7]{3,4}$ ]] && (( (8#${mode} & 0022) == 0 ))
}

assert_root_immutable_file() {
	local path="$1"
	local mode=""
	[ -f "${path}" ] && [ ! -L "${path}" ] || return 1
	[ "$(stat -c '%u' "${path}")" = "0" ] || return 1
	mode="$(mode_of "${path}")"
	[[ "${mode}" =~ ^[0-7]{3,4}$ ]] && (( (8#${mode} & 0022) == 0 ))
}

read_env_value() {
	local path="$1"
	local requested_key="$2"
	"${HOST_PYTHON}" - "${path}" "${requested_key}" <<'PY'
from __future__ import annotations

import os
import re
import stat
import sys

path, requested = sys.argv[1:]
if not re.fullmatch(r"[A-Z][A-Z0-9_]*", requested):
    raise SystemExit(1)
descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
try:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != 0
    ):
        raise SystemExit(1)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
finally:
    os.close(descriptor)
values: dict[str, str] = {}
for raw_line in b"".join(chunks).decode("utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    if "=" not in line:
        raise SystemExit(1)
    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
        raise SystemExit(1)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    if any(character in value for character in "\r\n\t"):
        raise SystemExit(1)
    values[key] = value
if requested in values:
    print(values[requested])
PY
}

CURRENT_STAGE="validate-recovery-point"
for release_path in "${FAILED_RELEASE}" "${PREVIOUS_RELEASE}"; do
	[ -d "${release_path}" ] && [ ! -L "${release_path}" ] || fail "matched release directory is missing or unsafe"
	[ "$(stat -c '%u' "${release_path}")" = "0" ] || fail "matched release must be root-owned"
	[ "$(dirname "${release_path}")" = "${REMOTE_DIR}" ] || fail "matched release must be a direct managed child"
	assert_secure_directory "${release_path}" || fail "matched release directory is writable by an untrusted principal"
	assert_root_immutable_file "${release_path}/docker-compose.runtime.yml" || \
		fail "matched runtime Compose file is missing, linked, or writable"
done
RELEASE_STATE_ROOT="${REMOTE_DIR}/.release-state"
FAILED_STATE_DIR="${RELEASE_STATE_ROOT}/$(basename "${FAILED_RELEASE}")"
[ "${EVIDENCE_DIR}" = "${FAILED_STATE_DIR}/p1-e06-runtime-data-cutover" ] || \
	fail "recovery evidence directory is outside the failed release state"
assert_secure_directory "${RELEASE_STATE_ROOT}" || fail "release-state root is unsafe"
assert_secure_directory "${FAILED_STATE_DIR}" || fail "failed release-state directory is unsafe"
assert_secure_directory "${EVIDENCE_DIR}" || fail "recovery evidence directory is unsafe"
FAILED_MANIFEST="${FAILED_RELEASE}/release-bundle-manifest.json"
FAILED_MANIFEST_HELPER="${FAILED_RELEASE}/scripts/verify-release-bundle-manifest.py"
assert_root_immutable_file "${FAILED_MANIFEST}" || fail "failed release exact-bundle manifest is unsafe"
assert_root_immutable_file "${FAILED_MANIFEST_HELPER}" && [ -x "${FAILED_MANIFEST_HELPER}" ] || \
	fail "failed release manifest verifier is unsafe"
"${HOST_PYTHON}" "${FAILED_MANIFEST_HELPER}" verify-directory --root "${FAILED_RELEASE}" || \
	fail "failed release no longer matches its exact-bundle manifest"
assert_protected_file "${ENV_SNAPSHOT}" 600 && assert_digest "${ENV_SNAPSHOT}" "${ENV_SNAPSHOT_SHA256}" || \
	fail "original external env snapshot drifted"
assert_protected_file "${MAINTENANCE_SNAPSHOT}" 600 && assert_digest "${MAINTENANCE_SNAPSHOT}" "${MAINTENANCE_SNAPSHOT_SHA256}" || \
	fail "maintenance root snapshot drifted"
assert_protected_file "${EDGE_HANDOFF}" 600 && assert_digest "${EDGE_HANDOFF}" "${EDGE_HANDOFF_SHA256}" || \
	fail "Edge handoff evidence drifted"
assert_protected_file "${ROLLBACK_IMAGE_MAP}" 600 || fail "rollback image map is missing or unsafe"
assert_protected_file "${OLD_DATA_STATE}" 600 || fail "old data-service state is missing or unsafe"
assert_protected_file "${OLD_WRITER_IMAGE_IDS}" 600 || fail "old/new writer image fence is missing or unsafe"
"${HOST_PYTHON}" - "${OLD_WRITER_IMAGE_IDS}" <<'PY' || fail "old/new writer image fence is invalid"
import re
import sys
values = [line.strip() for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
if not values or len(values) != len(set(values)):
    raise SystemExit(1)
if any(not re.fullmatch(r"sha256:[0-9a-f]{64}", value) for value in values):
    raise SystemExit(1)
PY
assert_protected_file "${OFF_HOST_RECEIPT_EVIDENCE}" 600 || fail "validated off-host receipt evidence is missing"
assert_protected_file "${OFF_HOST_RECEIPT}" 600 && assert_digest "${OFF_HOST_RECEIPT}" "${OFF_HOST_RECEIPT_SHA256}" || \
	fail "off-host receipt drifted"
assert_protected_file "${BACKUP_PATH}" 400 || fail "database recovery point is missing or unsafe"
assert_protected_file "${BACKUP_PATH}.sha256" 400 || fail "database recovery checksum is missing or unsafe"
BACKUP_SHA256="$(sha256sum "${BACKUP_PATH}" | awk '{print $1}')"
[ "$(awk 'NR == 1 {print $1} NR > 1 {exit 1}' "${BACKUP_PATH}.sha256")" = "${BACKUP_SHA256}" ] || \
	fail "database recovery checksum differs"
"${HOST_PYTHON}" - \
	"${OFF_HOST_RECEIPT}" "${OFF_HOST_RECEIPT_SHA256}" \
	"${OFF_HOST_RECEIPT_EVIDENCE}" "${BACKUP_SHA256}" <<'PY' || \
	fail "off-host receipt evidence is not bound to the database recovery point"
from __future__ import annotations

import hashlib
import json
import sys

receipt_path, expected_receipt_sha256, evidence_path, expected_backup_sha256 = sys.argv[1:]
receipt_raw = open(receipt_path, "rb").read()
if hashlib.sha256(receipt_raw).hexdigest() != expected_receipt_sha256:
    raise SystemExit(1)
receipt = json.loads(receipt_raw)
if receipt != {
    "contract": "p1_e06_off_host_backup_receipt.v1",
    "status": "passed",
    "backup_sha256": expected_backup_sha256,
    "off_host_copy": True,
}:
    raise SystemExit(1)
evidence = json.load(open(evidence_path, "r", encoding="utf-8"))
if evidence != {
    "contract": "p1_e06_off_host_backup_receipt_evidence.v1",
    "source_receipt_path": receipt_path,
    "source_receipt_sha256": expected_receipt_sha256,
    "status": "passed",
    "validated_receipt": receipt,
}:
    raise SystemExit(1)
PY
[ ! -e "${ACTIVATION_COMMIT}" ] && [ ! -L "${ACTIVATION_COMMIT}" ] || fail "activation commit exists; destructive recovery is forbidden"
[ ! -e "${CUTOVER_RESULT}" ] && [ ! -L "${CUTOVER_RESULT}" ] || fail "cutover result exists; destructive recovery is forbidden"
[ ! -e "${GLOBAL_ACTIVATION_RECEIPT}" ] && [ ! -L "${GLOBAL_ACTIVATION_RECEIPT}" ] || \
	fail "global activation receipt exists; destructive recovery is forbidden"

[ -d "${DEPLOY_LOCK}" ] && [ ! -L "${DEPLOY_LOCK}" ] && [ "$(mode_of "${DEPLOY_LOCK}")" = "700" ] && \
	[ "$(stat -c '%u' "${DEPLOY_LOCK}")" = "0" ] || fail "retained deploy lock is missing or unsafe"
assert_protected_file "${LOCK_OWNER_FILE}" 600 || fail "retained deploy-lock owner proof is missing"
DEPLOY_LOCK_OWNER="$(<"${LOCK_OWNER_FILE}")"
[[ "${DEPLOY_LOCK_OWNER}" =~ ^[0-9a-f]{64}$ ]] || fail "deploy-lock owner proof is invalid"
DEPLOY_LOCK_OWNER_SHA256="$(sha256sum "${LOCK_OWNER_FILE}" | awk '{print $1}')"
export NPCINK_CLOUD_DEPLOY_LOCK_OWNER

COMPOSE_PROJECT_NAME_EFFECTIVE="$(read_env_value "${ENV_SNAPSHOT}" NPCINK_CLOUD_COMPOSE_PROJECT_NAME)" || \
	fail "previous Compose project name cannot be read safely"
if [ -z "${COMPOSE_PROJECT_NAME_EFFECTIVE}" ]; then
	COMPOSE_PROJECT_NAME_EFFECTIVE="$(read_env_value "${ENV_SNAPSHOT}" COMPOSE_PROJECT_NAME)" || \
		fail "previous Compose project name cannot be read safely"
fi
COMPOSE_PROJECT_NAME_EFFECTIVE="${COMPOSE_PROJECT_NAME_EFFECTIVE:-npcink-ai-cloud}"
[[ "${COMPOSE_PROJECT_NAME_EFFECTIVE}" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || fail "previous Compose project name is invalid"
OBSERVED_CURRENT_RELEASE="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"
if [ "${OBSERVED_CURRENT_RELEASE}" != "${FAILED_RELEASE}" ] && [ "${OBSERVED_CURRENT_RELEASE}" != "${PREVIOUS_RELEASE}" ]; then
	fail "current release pointer does not belong to the matched recovery point"
fi

clean_env() {
	local clean=(env -i "PATH=${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}")
	local key=""
	for key in HOME USER LOGNAME TMPDIR XDG_CONFIG_HOME XDG_RUNTIME_DIR SSH_AUTH_SOCK DOCKER_HOST; do
		if [ -n "${!key+x}" ]; then clean+=("${key}=${!key}"); fi
	done
	"${clean[@]}" "$@"
}

compose_previous() {
	clean_env \
		COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
		NPCINK_CLOUD_COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
		NPCINK_CLOUD_ENV_FILE="${PREVIOUS_ENV}" \
		NPCINK_CLOUD_BACKEND_ENV_FILE="${PREVIOUS_ENV}" \
		docker compose \
		--project-directory "${PREVIOUS_RELEASE}" \
		--env-file "${PREVIOUS_ENV}" \
		-f "${PREVIOUS_RELEASE}/docker-compose.runtime.yml" "$@"
}

APPLICATION_SERVICES=(api worker callback-worker ops-worker frontend proxy caddy)
RECOVERY_COMMITTED=0

stop_application_services() {
	local service="" ids="" id="" failed=0
	for service in "${APPLICATION_SERVICES[@]}"; do
		ids="$(docker ps -q \
			--filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
			--filter "label=com.docker.compose.service=${service}" 2>/dev/null)" || { failed=1; continue; }
		while IFS= read -r id; do
			[ -n "${id}" ] || continue
			docker stop --time 10 "${id}" >/dev/null 2>&1 || failed=1
		done <<<"${ids}"
	done
	ids="$(docker ps -q --filter 'label=com.docker.compose.service=release-one-off' 2>/dev/null)" || failed=1
	while IFS= read -r id; do
		[ -n "${id}" ] || continue
		docker stop --time 10 "${id}" >/dev/null 2>&1 || failed=1
	done <<<"${ids}"
	while IFS= read -r id; do
		[ -n "${id}" ] || continue
		ids="$(docker ps -q --filter "ancestor=${id}" 2>/dev/null)" || { failed=1; continue; }
		while IFS= read -r container_id; do
			[ -n "${container_id}" ] || continue
			docker stop --time 10 "${container_id}" >/dev/null 2>&1 || failed=1
		done <<<"${ids}"
	done <"${OLD_WRITER_IMAGE_IDS}"
	return "${failed}"
}

assert_application_services_stopped() {
	local service="" ids="" image_id=""
	for service in "${APPLICATION_SERVICES[@]}"; do
		ids="$(docker ps -q \
			--filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
			--filter "label=com.docker.compose.service=${service}")" || return 1
		[ -z "${ids}" ] || return 1
	done
	ids="$(docker ps -q --filter 'label=com.docker.compose.service=release-one-off')" || return 1
	[ -z "${ids}" ] || return 1
	while IFS= read -r image_id; do
		[ -n "${image_id}" ] || continue
		ids="$(docker ps -q --filter "ancestor=${image_id}")" || return 1
		[ -z "${ids}" ] || return 1
	done <"${OLD_WRITER_IMAGE_IDS}"
}

copy_protected_file_fresh() {
	local source="$1"
	local target="$2"
	"${HOST_PYTHON}" - "${source}" "${target}" <<'PY'
from __future__ import annotations

import os
import stat
import sys

source, target = sys.argv[1:]
source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
try:
    metadata = os.fstat(source_fd)
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise SystemExit(1)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(source_fd, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
finally:
    os.close(source_fd)
target_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
try:
    for chunk in chunks:
        view = memoryview(chunk)
        while view:
            view = view[os.write(target_fd, view):]
    os.fchmod(target_fd, 0o600)
    os.fchown(target_fd, metadata.st_uid, metadata.st_gid)
    os.fsync(target_fd)
finally:
    os.close(target_fd)
parent_fd = os.open(os.path.dirname(target), os.O_RDONLY)
try:
    os.fsync(parent_fd)
finally:
    os.close(parent_fd)
PY
}

link_protected_file_fresh() {
	local source="$1"
	local target="$2"
	"${HOST_PYTHON}" - "${source}" "${target}" <<'PY'
from __future__ import annotations

import os
import stat
import sys

source, target = sys.argv[1:]
source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
try:
    metadata = os.fstat(source_fd)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != 0
    ):
        raise SystemExit(1)
finally:
    os.close(source_fd)
os.link(source, target, follow_symlinks=False)
parent_fd = os.open(os.path.dirname(target), os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(parent_fd)
finally:
    os.close(parent_fd)
PY
}

publish_fresh_temp() {
	local temporary="$1"
	local target="$2"
	local allow_identical_existing="${3:-0}"
	"${HOST_PYTHON}" - "${temporary}" "${target}" "${allow_identical_existing}" <<'PY'
from __future__ import annotations

import os
import stat
import sys

temporary, target, allow_identical = sys.argv[1:]

def read_protected(path: str) -> tuple[bytes, os.stat_result]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != 0
        ):
            raise SystemExit(1)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks), metadata
    finally:
        os.close(descriptor)

temporary_raw, temporary_meta = read_protected(temporary)
if os.path.lexists(target):
    if allow_identical != "1":
        raise SystemExit(1)
    target_raw, target_meta = read_protected(target)
    if target_raw != temporary_raw or target_meta.st_uid != temporary_meta.st_uid:
        raise SystemExit(1)
else:
    os.link(temporary, target, follow_symlinks=False)
os.unlink(temporary)
parent_fd = os.open(os.path.dirname(target), os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(parent_fd)
finally:
    os.close(parent_fd)
if os.path.lexists(temporary):
    raise SystemExit(1)
target_raw, _target_meta = read_protected(target)
if target_raw != temporary_raw:
    raise SystemExit(1)
PY
}

assert_service_images() {
	local requested=("$@")
	local service="" reference="" expected="" source="" immutable_reference="" id="" count=0 actual_ref="" actual_id="" state=""
	local requested_service="" selected=0 matched=0 expected_matches=8 immutable_id=""
	if [ "${#requested[@]}" -gt 0 ]; then expected_matches="${#requested[@]}"; fi
	while IFS=$'\t' read -r service reference expected source immutable_reference; do
		if [ "${#requested[@]}" -gt 0 ]; then
			selected=0
			for requested_service in "${requested[@]}"; do
				if [ "${service}" = "${requested_service}" ]; then selected=1; break; fi
			done
			[ "${selected}" -eq 1 ] || continue
		fi
		id="$(compose_previous ps -q "${service}" 2>/dev/null)" || return 1
		count="$(printf '%s\n' "${id}" | awk 'NF {n += 1} END {print n + 0}')"
		[ "${count}" -eq 1 ] || return 1
		actual_ref="$(docker inspect --format '{{.Config.Image}}' "${id}")" || return 1
		actual_id="$(docker inspect --format '{{.Image}}' "${id}")" || return 1
		state="$(docker inspect --format '{{.State.Running}} {{.State.Restarting}} {{.RestartCount}}' "${id}")" || return 1
		[ "${actual_ref}" = "${reference}" ] && [ "${actual_id}" = "${expected}" ] && [ "${state}" = "true false 0" ] || return 1
		case "${source}" in
			old-data-state|rollback-map)
				[ "${immutable_reference}" = "${expected}" ] || return 1
				;;
				retained-lock-repo-digest)
					[[ "${immutable_reference}" =~ ^[A-Za-z0-9._/-]+@sha256:[0-9a-f]{64}$ ]] || return 1
					immutable_id="$(docker image inspect --format '{{.Id}}' "${immutable_reference}" 2>/dev/null || true)"
					[ "${immutable_id}" = "${expected}" ] || return 1
					;;
				*) return 1 ;;
			esac
		matched=$((matched + 1))
	done <"${RECOVERY_IMAGE_PLAN}"
	[ "${matched}" -eq "${expected_matches}" ]
}

create_prove_and_start_exact_services() {
	local services=("$@")
	local candidate_file="${EVIDENCE_DIR}/.recovery-candidates.$$"
	local service="" row="" reference="" expected="" source="" immutable_reference=""
	local ids="" id="" count=0 actual_ref="" actual_id="" state=""
	local candidate_service="" candidate_id="" candidate_reference="" candidate_expected=""
	: >"${candidate_file}"
	chmod 0600 "${candidate_file}"
	if ! compose_previous up --no-start --pull never --no-build --no-deps --force-recreate \
		"${services[@]}" >/dev/null; then
		rm -f "${candidate_file}"
		return 1
	fi
	for service in "${services[@]}"; do
		row="$(awk -F '\t' -v service="${service}" '$1 == service {print}' "${RECOVERY_IMAGE_PLAN}")" || return 1
		[ "$(printf '%s\n' "${row}" | awk 'NF {n += 1} END {print n + 0}')" -eq 1 ] || return 1
		IFS=$'\t' read -r _ reference expected source immutable_reference <<<"${row}"
		ids="$(compose_previous ps --all -q "${service}" 2>/dev/null)" || return 1
		count="$(printf '%s\n' "${ids}" | awk 'NF {n += 1} END {print n + 0}')"
		[ "${count}" -eq 1 ] || return 1
		id="${ids}"
		actual_ref="$(docker inspect --format '{{.Config.Image}}' "${id}")" || return 1
		actual_id="$(docker inspect --format '{{.Image}}' "${id}")" || return 1
		state="$(docker inspect --format '{{.State.Running}} {{.State.Restarting}} {{.RestartCount}}' "${id}")" || return 1
		[ "${actual_ref}" = "${reference}" ] && [ "${actual_id}" = "${expected}" ] && [ "${state}" = "false false 0" ] || return 1
		printf '%s\t%s\t%s\t%s\n' "${service}" "${id}" "${reference}" "${expected}" >>"${candidate_file}"
	done
	while IFS=$'\t' read -r candidate_service candidate_id candidate_reference candidate_expected; do
		[ -n "${candidate_service}" ] || continue
		docker start "${candidate_id}" >/dev/null || return 1
	done <"${candidate_file}"
	while IFS=$'\t' read -r candidate_service candidate_id candidate_reference candidate_expected; do
		[ -n "${candidate_service}" ] || continue
		ids="$(compose_previous ps --all -q "${candidate_service}" 2>/dev/null)" || return 1
		[ "${ids}" = "${candidate_id}" ] || return 1
		actual_ref="$(docker inspect --format '{{.Config.Image}}' "${candidate_id}")" || return 1
		actual_id="$(docker inspect --format '{{.Image}}' "${candidate_id}")" || return 1
		state="$(docker inspect --format '{{.State.Running}} {{.State.Restarting}} {{.RestartCount}}' "${candidate_id}")" || return 1
		[ "${actual_ref}" = "${candidate_reference}" ] && [ "${actual_id}" = "${candidate_expected}" ] && [ "${state}" = "true false 0" ] || return 1
	done <"${candidate_file}"
	rm -f "${candidate_file}"
	[ ! -e "${candidate_file}" ]
}

emit_internal_auth_header() {
	"${HOST_PYTHON}" - "${PREVIOUS_ENV}" <<'PY'
from __future__ import annotations

import os
import stat
import sys

descriptor = os.open(sys.argv[1], os.O_RDONLY | os.O_NOFOLLOW)
try:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != 0
    ):
        raise SystemExit(1)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
finally:
    os.close(descriptor)
values: dict[str, str] = {}
for raw_line in b"".join(chunks).decode("utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    if "=" not in line:
        raise SystemExit(1)
    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip()
    if key in values:
        raise SystemExit(1)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    if any(character in value for character in "\r\n\t"):
        raise SystemExit(1)
    values[key] = value
token = values.get("NPCINK_CLOUD_INTERNAL_AUTH_TOKEN", "")
if not token:
    raise SystemExit(1)
sys.stdout.write(f"X-Npcink-Internal-Token: {token}\n")
PY
}

curl_previous_public_ready() {
	local base_url="$1"
	local domain_name="$2"
	emit_internal_auth_header | \
		curl -fsS --connect-timeout 5 --max-time 15 --header @- \
			--resolve "${domain_name}:443:127.0.0.1" \
			"${base_url%/}/health/ready" >/dev/null
}

assert_previous_public_ready() {
	local base_url="" domain_name=""
	base_url="$(read_env_value "${PREVIOUS_ENV}" NPCINK_CLOUD_BASE_URL)" || return 1
	domain_name="$(read_env_value "${PREVIOUS_ENV}" NPCINK_CLOUD_DOMAIN_NAME)" || return 1
	"${HOST_PYTHON}" - "${base_url}" "${domain_name}" <<'PY' || return 1
from urllib.parse import urlsplit
import sys
base, domain = sys.argv[1:]
parsed = urlsplit(base)
if parsed.scheme != "https" or parsed.hostname != domain or parsed.port not in (None, 443):
    raise SystemExit(1)
if parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
    raise SystemExit(1)
PY
	systemctl is-active --quiet nginx || return 1
	nginx -t >/dev/null 2>&1 || return 1
	curl_previous_public_ready "${base_url}" "${domain_name}"
}

validate_recovery_result() {
	local result_path="$1"
	local rollback_map_sha256="$2"
	local image_plan_sha256="$3"
	local lock_owner_sha256="$4"
	"${HOST_PYTHON}" - \
		"${result_path}" "${FAILED_RELEASE}" "${PREVIOUS_RELEASE}" "${MARKER_SHA256}" \
		"${BACKUP_SHA256}" "${ENV_SNAPSHOT_SHA256}" "${MAINTENANCE_SNAPSHOT_SHA256}" \
		"${rollback_map_sha256}" "${image_plan_sha256}" "${lock_owner_sha256}" <<'PY'
import json
import sys

(path, failed_release, previous_release, marker_sha256, backup_sha256,
 env_sha256, maintenance_sha256, rollback_map_sha256, image_plan_sha256,
 lock_owner_sha256) = sys.argv[1:]
payload = json.load(open(path, "r", encoding="utf-8"))
expected = {
    "contract": "p1_e06_full_recovery.v1",
    "status": "passed",
    "failed_release": failed_release,
    "active_release": previous_release,
    "database_revision": "20260710_0058",
    "failure_marker_sha256": marker_sha256,
    "backup_sha256": backup_sha256,
    "previous_env_sha256": env_sha256,
    "maintenance_snapshot_sha256": maintenance_sha256,
    "rollback_image_map_sha256": rollback_map_sha256,
    "recovery_image_plan_sha256": image_plan_sha256,
    "deploy_lock_owner_sha256": lock_owner_sha256,
    "whole_database_restored": True,
    "previous_release_restored": True,
    "previous_external_env_restored": True,
    "both_old_roots_restored": True,
    "host_nginx_retained": True,
    "retired_caddy_started": False,
    "secret_values_included": False,
}
if payload != expected:
    raise SystemExit(1)
PY
}

terminalize_recovery() {
	CURRENT_STAGE="archive-and-clear-failure-marker-under-lock"
	if [ -e "${RECOVERY_LOCK_OWNER_ARCHIVE}" ] || [ -L "${RECOVERY_LOCK_OWNER_ARCHIVE}" ]; then
		assert_protected_file "${RECOVERY_LOCK_OWNER_ARCHIVE}" 600 && \
			assert_digest "${RECOVERY_LOCK_OWNER_ARCHIVE}" "${DEPLOY_LOCK_OWNER_SHA256}" || return 1
	else
		link_protected_file_fresh "${LOCK_OWNER_FILE}" "${RECOVERY_LOCK_OWNER_ARCHIVE}" || return 1
		assert_protected_file "${RECOVERY_LOCK_OWNER_ARCHIVE}" 600 && \
			assert_digest "${RECOVERY_LOCK_OWNER_ARCHIVE}" "${DEPLOY_LOCK_OWNER_SHA256}" || return 1
	fi
	if [ -e "${ARCHIVED_FAILURE}" ] || [ -L "${ARCHIVED_FAILURE}" ]; then
		assert_protected_file "${ARCHIVED_FAILURE}" 600 && assert_digest "${ARCHIVED_FAILURE}" "${MARKER_SHA256}" || return 1
	else
		link_protected_file_fresh "${FAILURE_MARKER}" "${ARCHIVED_FAILURE}" || return 1
		assert_protected_file "${ARCHIVED_FAILURE}" 600 && assert_digest "${ARCHIVED_FAILURE}" "${MARKER_SHA256}" || return 1
	fi
	rm -f "${FAILURE_MARKER}" || return 1
	[ ! -e "${FAILURE_MARKER}" ] && [ ! -L "${FAILURE_MARKER}" ] || return 1
	"${HOST_PYTHON}" - "${REMOTE_DIR}" <<'PY' || return 1
import os
import sys
fd = os.open(sys.argv[1], os.O_RDONLY)
try:
    os.fsync(fd)
finally:
    os.close(fd)
PY

	CURRENT_STAGE="release-recovery-lock-last"
	[ "$(find "${DEPLOY_LOCK}" -mindepth 1 -maxdepth 1 -printf '%f\n')" = "one-off-owner" ] || return 1
	rm -f "${LOCK_OWNER_FILE}" || return 1
	[ ! -e "${LOCK_OWNER_FILE}" ] && [ ! -L "${LOCK_OWNER_FILE}" ] || return 1
	"${HOST_PYTHON}" - "${DEPLOY_LOCK}" <<'PY' || return 1
import os
import sys
fd = os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(fd)
finally:
    os.close(fd)
PY
	if ! rmdir "${DEPLOY_LOCK}"; then
		link_protected_file_fresh "${RECOVERY_LOCK_OWNER_ARCHIVE}" "${LOCK_OWNER_FILE}" >/dev/null 2>&1 || true
		return 1
	fi
	"${HOST_PYTHON}" - "${REMOTE_DIR}" <<'PY' || return 1
import os
import sys
fd = os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(fd)
finally:
    os.close(fd)
PY
	[ ! -e "${DEPLOY_LOCK}" ] && [ ! -L "${DEPLOY_LOCK}" ]
}

assert_recovery_images_available() {
	local target="" rollback="" expected="" observed="" service="" _container="" image_id=""
	while IFS=$'\t' read -r target rollback expected; do
		[ -n "${target}" ] || continue
		if [ "${rollback}" = "-" ] && [ "${expected}" = "-" ]; then
			continue
		fi
		[[ "${expected}" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
		observed="$(docker image inspect --format '{{.Id}}' "${rollback}" 2>/dev/null || true)"
		if [ "${observed}" != "${expected}" ]; then
			observed="$(docker image inspect --format '{{.Id}}' "${expected}" 2>/dev/null || true)"
		fi
		[ "${observed}" = "${expected}" ] || return 1
	done <"${ROLLBACK_IMAGE_MAP}"
	while IFS=$'\t' read -r service _container image_id; do
		[ -n "${service}" ] || continue
		[[ "${image_id}" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
		[ "$(docker image inspect --format '{{.Id}}' "${image_id}" 2>/dev/null || true)" = "${image_id}" ] || return 1
	done <"${OLD_DATA_STATE}"
	return 0
}

assert_expected_absent_image_tags() {
	local target="" rollback="" expected=""
	while IFS=$'\t' read -r target rollback expected; do
		[ -n "${target}" ] || continue
		if [ "${rollback}" = "-" ] && [ "${expected}" = "-" ]; then
			docker image inspect "${target}" >/dev/null 2>&1 && return 1
		fi
	done <"${ROLLBACK_IMAGE_MAP}"
	return 0
}

on_exit() {
	local status="$?"
	trap - EXIT HUP INT TERM
	set +e
	if [ "${status}" -ne 0 ] && [ "${RECOVERY_COMMITTED}" != "1" ] && [ "${PREFLIGHT_ONLY}" != "1" ]; then
		stop_application_services >/dev/null 2>&1 || true
		if [ -d "${DEPLOY_LOCK}" ] && [ ! -L "${DEPLOY_LOCK}" ]; then
			printf '[p1-e06-recovery:fail] recovery not committed; public/write services remain fenced and deploy lock retained.\n' >&2
		else
			printf '[p1-e06-recovery:fail] recovery not committed; public/write services fenced, but deploy-lock state needs operator review.\n' >&2
		fi
	elif [ "${status}" -ne 0 ] && [ "${PREFLIGHT_ONLY}" = "1" ]; then
		printf '[p1-e06-recovery:fail] preflight failed; no recovery mutation was attempted.\n' >&2
	elif [ "${status}" -ne 0 ]; then
		if [ -d "${DEPLOY_LOCK}" ] && [ ! -L "${DEPLOY_LOCK}" ] && \
			[ ! -e "${FAILURE_MARKER}" ] && [ -f "${ARCHIVED_FAILURE}" ] && \
			[ ! -L "${ARCHIVED_FAILURE}" ]; then
			link_protected_file_fresh "${ARCHIVED_FAILURE}" "${FAILURE_MARKER}" >/dev/null 2>&1 || true
		fi
		if [ -d "${DEPLOY_LOCK}" ] && [ ! -L "${DEPLOY_LOCK}" ] && \
			[ ! -e "${LOCK_OWNER_FILE}" ] && [ -f "${RECOVERY_LOCK_OWNER_ARCHIVE}" ] && \
			[ ! -L "${RECOVERY_LOCK_OWNER_ARCHIVE}" ]; then
			link_protected_file_fresh "${RECOVERY_LOCK_OWNER_ARCHIVE}" "${LOCK_OWNER_FILE}" >/dev/null 2>&1 || true
		fi
		if [ -d "${DEPLOY_LOCK}" ] && [ ! -L "${DEPLOY_LOCK}" ]; then
			printf '[p1-e06-recovery:fail] recovery committed; healthy previous runtime and deploy lock retained for terminalization.\n' >&2
		else
			printf '[p1-e06-recovery:fail] recovery committed and lock released; healthy previous runtime retained, but terminal evidence cleanup needs review.\n' >&2
		fi
	fi
	exit "${status}"
}
trap on_exit EXIT
trap 'CURRENT_STAGE=signal-hup; exit 129' HUP
trap 'CURRENT_STAGE=signal-int; exit 130' INT
trap 'CURRENT_STAGE=signal-term; exit 143' TERM

if [ -e "${RECOVERY_RESULT}" ] || [ -L "${RECOVERY_RESULT}" ]; then
	CURRENT_STAGE="terminalization-only-validate-committed-recovery"
	assert_protected_file "${RECOVERY_RESULT}" 600 || fail "existing recovery result is unsafe"
	assert_protected_file "${RECOVERY_IMAGE_PLAN}" 600 || fail "committed recovery image plan is missing or unsafe"
	assert_protected_file "${RECOVERY_LOCK_OWNER_ARCHIVE}" 600 && \
		assert_digest "${RECOVERY_LOCK_OWNER_ARCHIVE}" "${DEPLOY_LOCK_OWNER_SHA256}" || \
		fail "committed recovery lock-owner archive is missing or unsafe"
	ROLLBACK_IMAGE_MAP_SHA256="$(sha256sum "${ROLLBACK_IMAGE_MAP}" | awk '{print $1}')"
	RECOVERY_IMAGE_PLAN_SHA256="$(sha256sum "${RECOVERY_IMAGE_PLAN}" | awk '{print $1}')"
	validate_recovery_result "${RECOVERY_RESULT}" "${ROLLBACK_IMAGE_MAP_SHA256}" "${RECOVERY_IMAGE_PLAN_SHA256}" \
		"${DEPLOY_LOCK_OWNER_SHA256}" || \
		fail "existing recovery result does not match the retained recovery point"
	# From this point onward the durable commit already exists. A transient
	# verification failure must never route through the pre-commit EXIT fence
	# and stop the successfully restored generation.
	RECOVERY_COMMITTED=1
	assert_local_docker_identity || fail "local Docker daemon identity drifted before terminalization"
	[ "$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)" = "${PREVIOUS_RELEASE}" ] || \
		fail "committed previous release pointer drifted"
	assert_protected_file "${PREVIOUS_ENV}" 600 && assert_digest "${PREVIOUS_ENV}" "${ENV_SNAPSHOT_SHA256}" || \
		fail "committed previous external env drifted"
	assert_service_images || fail "committed recovered service images or states drifted"
	assert_expected_absent_image_tags || fail "post-migration-only image tags reappeared after recovery commit"
	POSTGRES_ID="$(compose_previous ps -q postgres)"
	[ "$(printf '%s\n' "${POSTGRES_ID}" | awk 'NF {n += 1} END {print n + 0}')" -eq 1 ] || \
		fail "committed PostgreSQL container is not unique"
	[ "$(docker exec "${POSTGRES_ID}" sh -c \
		'exec psql -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select version_num from alembic_version"')" = "${EXPECTED_SOURCE_REVISION}" ] || \
		fail "committed recovered database revision drifted"
	assert_previous_public_ready || fail "committed recovered public readiness drifted"
	[ -z "$(docker ps -q \
		--filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
		--filter "label=com.docker.compose.service=caddy")" ] || fail "retired Caddy appeared after recovery commit"
	if [ "${PREFLIGHT_ONLY}" = "1" ]; then
		printf '[p1-e06-recovery:ok] committed-recovery preflight passed; no terminal state was changed.\n'
		exit 0
	fi
	trap '' HUP INT TERM
	terminalize_recovery || fail "committed recovery terminalization failed"
	trap 'CURRENT_STAGE=signal-hup; exit 129' HUP
	trap 'CURRENT_STAGE=signal-int; exit 130' INT
	trap 'CURRENT_STAGE=signal-term; exit 143' TERM
	printf '[p1-e06-recovery:ok] committed recovery terminalized without another database restore; evidence=%s\n' "${RECOVERY_RESULT}"
	exit 0
fi

CURRENT_STAGE="re-prove-writer-fence"
assert_local_docker_identity || fail "local Docker daemon identity drifted before recovery"
if [ "${PREFLIGHT_ONLY}" != "1" ]; then
	stop_application_services || fail "application services could not be stopped"
fi
assert_application_services_stopped || fail "application/public writer fence is incomplete"

CURRENT_STAGE="validate-old-roots-against-original-env"
"${HOST_PYTHON}" - "${ENV_SNAPSHOT}" "${MAINTENANCE_SNAPSHOT}" <<'PY' || fail "old-root snapshot does not match the original runtime env"
from __future__ import annotations

import os
import stat
import sys

def read_values(path: str) -> dict[str, str]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or stat.S_IMODE(meta.st_mode) != 0o600:
            raise SystemExit(1)
        raw = b""
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            raw += chunk
    finally:
        os.close(fd)
    values: dict[str, str] = {}
    for raw_line in raw.decode("utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SystemExit(1)
        key, value = line.split("=", 1)
        if key in values:
            raise SystemExit(1)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values

original = read_values(sys.argv[1])
maintenance = read_values(sys.argv[2])
runtime_root = (
    original.get("NPCINK_CLOUD_ADMIN_SESSION_SECRET")
    or original.get("NPCINK_CLOUD_PORTAL_JWT_SECRET")
    or original.get("NPCINK_CLOUD_INTERNAL_AUTH_TOKEN")
)
service_root = original.get("NPCINK_CLOUD_SERVICE_SETTINGS_SECRET")
if not runtime_root or not service_root:
    raise SystemExit(1)
if maintenance.get("NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET") != runtime_root:
    raise SystemExit(1)
if maintenance.get("NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET") != service_root:
    raise SystemExit(1)
PY

if [ "${PREFLIGHT_ONLY}" = "1" ]; then
	CURRENT_STAGE="preflight-only-image-availability"
	assert_application_services_stopped || fail "preflight requires the retained writer/public fence"
	assert_recovery_images_available || fail "one or more frozen previous images are unavailable"
	assert_protected_file "${PREVIOUS_RELEASE}/.env.deploy" 600 && \
		assert_digest "${PREVIOUS_RELEASE}/.env.deploy" "${ENV_SNAPSHOT_SHA256}" || \
		fail "previous exact release env does not match the recovery snapshot"
fi

restore_image_tags() {
	local target="" rollback="" expected="" observed="" failed=0 matches=0
	while IFS=$'\t' read -r target rollback expected; do
		[ -n "${target}" ] || continue
		[[ "${target}" =~ ^[A-Za-z0-9._/-]+:[A-Za-z0-9._-]+$ ]] || return 1
		if [ "${rollback}" = "-" ] && [ "${expected}" = "-" ]; then
			# The target PostgreSQL tag can still be the sole tag of the
			# currently running post-migration data image. Defer its exact
			# removal until the stopped old-data candidates have replaced that
			# container; never force-remove an in-use recovery image.
			continue
		fi
		[[ "${rollback}" =~ ^[A-Za-z0-9._/-]+:[A-Za-z0-9._-]+$ ]] || return 1
		[[ "${expected}" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
		docker tag "${rollback}" "${target}" >/dev/null 2>&1 || docker tag "${expected}" "${target}" >/dev/null 2>&1 || { failed=1; continue; }
		observed="$(docker image inspect --format '{{.Id}}' "${target}" 2>/dev/null || true)"
		[ "${observed}" = "${expected}" ] || failed=1
		matches=$((matches + 1))
	done <"${ROLLBACK_IMAGE_MAP}"
	[ "${matches}" -ge 1 ] && [ "${failed}" -eq 0 ]
}

remove_expected_absent_image_tags() {
	local target="" rollback="" expected="" failed=0
	while IFS=$'\t' read -r target rollback expected; do
		[ -n "${target}" ] || continue
		if [ "${rollback}" != "-" ] || [ "${expected}" != "-" ]; then
			continue
		fi
		[[ "${target}" =~ ^[A-Za-z0-9._/-]+:[A-Za-z0-9._-]+$ ]] || return 1
		docker image rm "${target}" >/dev/null 2>&1 || true
		if docker image inspect "${target}" >/dev/null 2>&1; then failed=1; fi
	done <"${ROLLBACK_IMAGE_MAP}"
	[ "${failed}" -eq 0 ]
}

restore_previous_env() {
	"${HOST_PYTHON}" - "${PREVIOUS_ENV}" "${ENV_SNAPSHOT}" "${ENV_SNAPSHOT_SHA256}" <<'PY'
from __future__ import annotations

import hashlib
import os
import stat
import sys

target, snapshot, expected = sys.argv[1:]
source_fd = os.open(snapshot, os.O_RDONLY | os.O_NOFOLLOW)
try:
    source_meta = os.fstat(source_fd)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(source_fd, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
finally:
    os.close(source_fd)
raw = b"".join(chunks)
if (
    not stat.S_ISREG(source_meta.st_mode)
    or stat.S_IMODE(source_meta.st_mode) != 0o600
    or source_meta.st_uid != 0
):
    raise SystemExit(1)
if hashlib.sha256(raw).hexdigest() != expected:
    raise SystemExit(1)
target_fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
try:
    target_meta = os.fstat(target_fd)
    if (
        not stat.S_ISREG(target_meta.st_mode)
        or stat.S_IMODE(target_meta.st_mode) != 0o600
        or target_meta.st_uid != 0
    ):
        raise SystemExit(1)
finally:
    os.close(target_fd)
temporary = os.path.join(os.path.dirname(target), f".{os.path.basename(target)}.recover.{os.getpid()}")
fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
try:
    view = memoryview(raw)
    while view:
        view = view[os.write(fd, view):]
    os.fchmod(fd, 0o600)
    os.fchown(fd, target_meta.st_uid, target_meta.st_gid)
    os.fsync(fd)
finally:
    os.close(fd)
try:
    observed = os.lstat(target)
    if (
        not stat.S_ISREG(observed.st_mode)
        or observed.st_dev != target_meta.st_dev
        or observed.st_ino != target_meta.st_ino
        or observed.st_uid != 0
    ):
        raise SystemExit(1)
    os.replace(temporary, target)
    parent = os.open(os.path.dirname(target), os.O_RDONLY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
finally:
    if os.path.lexists(temporary):
        os.unlink(temporary)
PY
}

CURRENT_STAGE="freeze-previous-compose-image-plan"
PREVIOUS_CONFIG="$(compose_previous config --format json)" || fail "previous Compose config cannot be rendered"
if [ "${PREFLIGHT_ONLY}" = "1" ]; then
	RECOVERY_IMAGE_PLAN_TARGET="-"
else
	RECOVERY_IMAGE_PLAN_TARGET="${RECOVERY_IMAGE_PLAN}.tmp.$$"
fi
"${HOST_PYTHON}" - "${RECOVERY_IMAGE_PLAN_TARGET}" "${ROLLBACK_IMAGE_MAP}" "${OLD_DATA_STATE}" \
	3<<<"${PREVIOUS_CONFIG}" <<'PY' || fail "previous Compose image plan cannot be frozen"
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

target, rollback_path, data_path = sys.argv[1:]
config = json.load(os.fdopen(3, "r", encoding="utf-8"))
services = config.get("services", {})
required = ("postgres", "redis", "api", "worker", "callback-worker", "ops-worker", "frontend", "proxy")
rollback: dict[str, tuple[str, str]] = {}
rollback_seen: set[str] = set()
with open(rollback_path, "r", encoding="utf-8") as handle:
    for raw in handle:
        fields = raw.rstrip("\n").split("\t")
        if len(fields) != 3:
            raise SystemExit(1)
        ref, private, image_id = fields
        if ref in rollback_seen or not re.fullmatch(r"[A-Za-z0-9._/-]+:[A-Za-z0-9._-]+", ref):
            raise SystemExit(1)
        rollback_seen.add(ref)
        if image_id == "-" or private == "-":
            if (private, image_id) != ("-", "-"):
                raise SystemExit(1)
        else:
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
                raise SystemExit(1)
            if not re.fullmatch(r"[A-Za-z0-9._/-]+:[A-Za-z0-9._-]+", private):
                raise SystemExit(1)
            rollback[ref] = (private, image_id)
expected_rollback_refs = {
    "npcink-ai-cloud-api:prod",
    "npcink-ai-cloud-callback-worker:prod",
    "npcink-ai-cloud-external-nginx:prod",
    "npcink-ai-cloud-external-redis:prod",
    "npcink-ai-cloud-frontend:prod",
    "npcink-ai-cloud-ops-worker:prod",
    "npcink-ai-cloud-postgres:prod",
    "npcink-ai-cloud-worker:prod",
}
if rollback_seen != expected_rollback_refs or len(rollback) != 5:
    raise SystemExit(1)
data: dict[str, str] = {}
with open(data_path, "r", encoding="utf-8") as handle:
    for raw in handle:
        fields = raw.rstrip("\n").split("\t")
        if len(fields) != 3 or not re.fullmatch(r"sha256:[0-9a-f]{64}", fields[2]):
            raise SystemExit(1)
        if fields[0] in data:
            raise SystemExit(1)
        data[fields[0]] = fields[2]
if set(data) != {"postgres", "redis"}:
    raise SystemExit(1)
lines: list[str] = []
for service in required:
    item = services.get(service)
    if not isinstance(item, dict):
        raise SystemExit(1)
    reference = item.get("image")
    if not isinstance(reference, str) or not reference.strip() or reference != reference.strip():
        raise SystemExit(1)
    if service in data:
        expected = data[service]
        source = "old-data-state"
        immutable_reference = expected
    elif reference in rollback:
        rollback_reference, expected = rollback[reference]
        source = "rollback-map"
        immutable_reference = expected
        observed_rollback = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", rollback_reference],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        if observed_rollback != expected:
            raise SystemExit(1)
    elif service == "proxy":
        if reference != "nginx:1.27-alpine":
            raise SystemExit(1)
        inspect = json.loads(subprocess.run(
            ["docker", "image", "inspect", reference],
            check=True, capture_output=True, text=True,
        ).stdout)
        if not isinstance(inspect, list) or len(inspect) != 1:
            raise SystemExit(1)
        expected = str(inspect[0].get("Id") or "")
        repo_digests = sorted(
            value for value in inspect[0].get("RepoDigests") or []
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._/-]+@sha256:[0-9a-f]{64}", value)
        )
        if not repo_digests:
            raise SystemExit(1)
        source = "retained-lock-repo-digest"
        immutable_reference = repo_digests[0]
    else:
        # Every application image except the historical official proxy must be
        # bound to pre-failure rollback evidence. Never freeze an arbitrary
        # current tag as the previous application generation.
        raise SystemExit(1)
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected):
        raise SystemExit(1)
    if source != "rollback-map":
        observed = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", reference],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        if observed != expected:
            raise SystemExit(1)
    lines.append(f"{service}\t{reference}\t{expected}\t{source}\t{immutable_reference}\n")
if len(lines) != len(required):
    raise SystemExit(1)
if target != "-":
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        raw = "".join(lines).encode()
        view = memoryview(raw)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)
PY
unset PREVIOUS_CONFIG
if [ "${PREFLIGHT_ONLY}" = "1" ]; then
	printf '[p1-e06-recovery:ok] preflight passed; no production state was changed.\n'
	exit 0
fi
publish_fresh_temp "${RECOVERY_IMAGE_PLAN_TARGET}" "${RECOVERY_IMAGE_PLAN}" 1 || \
	fail "recovery image plan could not be published exactly"
assert_protected_file "${RECOVERY_IMAGE_PLAN}" 600 || fail "recovery image plan is unsafe after publication"
RECOVERY_IMAGE_PLAN_SHA256="$(sha256sum "${RECOVERY_IMAGE_PLAN}" | awk '{print $1}')"

CURRENT_STAGE="restore-previous-image-tags"
assert_local_docker_identity || fail "local Docker daemon identity drifted before image recovery"
restore_image_tags || fail "previous image tags could not be restored exactly"

CURRENT_STAGE="restore-previous-external-env"
restore_previous_env || fail "previous external env could not be restored atomically"
assert_protected_file "${PREVIOUS_ENV}" 600 && assert_digest "${PREVIOUS_ENV}" "${ENV_SNAPSHOT_SHA256}" || \
	fail "restored previous env digest differs"
assert_protected_file "${PREVIOUS_RELEASE}/.env.deploy" 600 && assert_digest "${PREVIOUS_RELEASE}/.env.deploy" "${ENV_SNAPSHOT_SHA256}" || \
	fail "previous exact release env does not match the recovery snapshot"

wait_for_data_health() {
	local attempt=0 state="" service=""
	for service in postgres redis; do
		attempt=0
		while [ "${attempt}" -lt 30 ]; do
			state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$(compose_previous ps -q "${service}")" 2>/dev/null || true)"
			[ "${state}" = "healthy" ] && break
			attempt=$((attempt + 1))
			sleep 2
		done
		[ "${state}" = "healthy" ] || return 1
	done
}

CURRENT_STAGE="restore-previous-data-services"
assert_local_docker_identity || fail "local Docker daemon identity drifted before data-service recovery"
create_prove_and_start_exact_services postgres redis || \
	fail "previous PostgreSQL and Redis exact candidates could not be proved and started"
remove_expected_absent_image_tags || \
	fail "post-migration-only image tags could not be removed after exact old data replacement"
wait_for_data_health || fail "previous PostgreSQL or Redis did not become healthy"
assert_service_images postgres redis || fail "previous data-service image identity differs before database restore"

CURRENT_STAGE="restore-whole-database"
assert_local_docker_identity || fail "local Docker daemon identity drifted before whole-database recovery"
POSTGRES_ID="$(compose_previous ps -q postgres)"
[ "$(printf '%s\n' "${POSTGRES_ID}" | awk 'NF {n += 1} END {print n + 0}')" -eq 1 ] || fail "previous PostgreSQL container is not unique"
docker exec "${POSTGRES_ID}" sh -c '
  set -eu
  case "$POSTGRES_DB" in postgres|template0|template1|"") exit 1 ;; esac
  dropdb --force --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB"
  createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" "$POSTGRES_DB"
' >/dev/null || fail "production database could not be recreated cleanly"
docker exec -i "${POSTGRES_ID}" sh -c \
	'exec pg_restore --exit-on-error --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
	<"${BACKUP_PATH}" >/dev/null || fail "whole database restore failed"
DATABASE_REVISION="$(docker exec "${POSTGRES_ID}" sh -c \
	'exec psql -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select version_num from alembic_version"')"
[ "${DATABASE_REVISION}" = "${EXPECTED_SOURCE_REVISION}" ] || fail "restored database is not exact revision 0058"
assert_digest "${BACKUP_PATH}" "${BACKUP_SHA256}" || fail "backup changed during restore"

CURRENT_STAGE="restore-previous-release-pointer"
NEXT_LINK="${CURRENT_LINK}.recovery.$$"
rm -f "${NEXT_LINK}"
ln -s "${PREVIOUS_RELEASE}" "${NEXT_LINK}"
mv -Tf "${NEXT_LINK}" "${CURRENT_LINK}"
[ "$(readlink -f "${CURRENT_LINK}")" = "${PREVIOUS_RELEASE}" ] || fail "previous release pointer was not restored"
"${HOST_PYTHON}" - "${REMOTE_DIR}" <<'PY' || fail "previous release pointer directory could not be synchronized"
import os
import sys
fd = os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(fd)
finally:
    os.close(fd)
PY

CURRENT_STAGE="start-previous-api"
assert_local_docker_identity || fail "local Docker daemon identity drifted before previous runtime startup"
WORKER_CUTOFF="$(date -u +%Y-%m-%dT%H:%M:%S.%6NZ)"
create_prove_and_start_exact_services api || fail "previous API exact candidate could not be proved and started"
API_ID="$(compose_previous ps -q api)"
attempt=0
while [ "${attempt}" -lt 30 ]; do
	if docker exec -i "${API_ID}" python - <<'PY' >/dev/null 2>&1
import os
import re
import urllib.request

domain = os.environ.get("NPCINK_CLOUD_DOMAIN_NAME", "").strip()
trusted = next(
    (
        item.strip()
        for item in os.environ.get("NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST", "").split(",")
        if item.strip()
    ),
    "",
)
host = domain or trusted
if host.startswith("*."):
    host = host[2:]
if not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]+)?", host):
    raise SystemExit(1)
internal_token = os.environ.get("NPCINK_CLOUD_INTERNAL_AUTH_TOKEN", "")
if not internal_token:
    raise SystemExit(1)
request = urllib.request.Request(
    "http://127.0.0.1:8000/health/ready",
    headers={"Host": host, "X-Npcink-Internal-Token": internal_token},
)
with urllib.request.urlopen(request, timeout=5) as response:
    raise SystemExit(0 if response.status == 200 else 1)
PY
	then break; fi
	attempt=$((attempt + 1))
	sleep 2
done
[ "${attempt}" -lt 30 ] || fail "previous API did not become ready"

CURRENT_STAGE="prove-previous-runtime-can-decrypt-restored-data"
docker exec -i "${API_ID}" python - <<'PY' >/dev/null || \
	fail "previous runtime could not decrypt one restored ciphertext from each legacy root"
from __future__ import annotations

from sqlalchemy import text

from app.core.config import Settings
from app.core.db import get_engine
from app.core.secrets import (
    decrypt_provider_connection_secret,
    decrypt_service_setting_secret,
    decrypt_site_api_signing_secret,
)

settings = Settings()
engine = get_engine(settings.database_url)
with engine.connect() as connection:
    runtime_ciphertext = connection.execute(
        text(
            "select signing_secret_ciphertext from site_api_keys "
            "where signing_secret_ciphertext is not null and signing_secret_ciphertext <> '' "
            "order by key_id limit 1"
        )
    ).scalar_one_or_none()
    provider_ciphertext = connection.execute(
        text(
            "select secret_ciphertext from provider_connections "
            "where secret_ciphertext is not null and secret_ciphertext <> '' "
            "order by connection_id limit 1"
        )
    ).scalar_one_or_none()
    service_ciphertexts = connection.execute(
        text(
            "select secret_ciphertext_json from service_settings "
            "where secret_ciphertext_json is not null order by setting_id"
        )
    ).scalars().all()

if not isinstance(runtime_ciphertext, str) or not runtime_ciphertext:
    raise SystemExit(1)
runtime_plaintext = decrypt_site_api_signing_secret(runtime_ciphertext, settings=settings)
if not runtime_plaintext:
    raise SystemExit(1)

service_plaintext = ""
if isinstance(provider_ciphertext, str) and provider_ciphertext:
    service_plaintext = decrypt_provider_connection_secret(provider_ciphertext, settings=settings)
else:
    for payload in service_ciphertexts:
        if not isinstance(payload, dict):
            continue
        for key in sorted(payload):
            ciphertext = payload.get(key)
            if isinstance(ciphertext, str) and ciphertext:
                service_plaintext = decrypt_service_setting_secret(ciphertext, settings=settings)
                break
        if service_plaintext:
            break
if not service_plaintext:
    raise SystemExit(1)

# Do not print or persist decrypted values. Reaching this point is the proof.
del runtime_plaintext, service_plaintext
PY

CURRENT_STAGE="start-previous-workers"
create_prove_and_start_exact_services worker callback-worker ops-worker || \
	fail "previous worker exact candidates could not be proved and started"
docker exec -i "${API_ID}" python - "${WORKER_CUTOFF}" <<'PY' >/dev/null || fail "previous worker heartbeat proof did not pass"
from __future__ import annotations

from datetime import datetime
import json
import os
import re
import sys
import time
import urllib.request

cutoff = datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
required = {"runtime_queue", "callback_dispatch", "ops_cadence"}
domain = os.environ.get("NPCINK_CLOUD_DOMAIN_NAME", "").strip()
trusted = next((x.strip() for x in os.environ.get("NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST", "").split(",") if x.strip()), "")
host = domain or trusted or "127.0.0.1"
if host.startswith("*."):
    host = host[2:]
if not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]+)?", host):
    raise SystemExit(1)
request = urllib.request.Request(
    "http://127.0.0.1:8000/internal/service/observability/summary",
    headers={"Host": host, "X-Npcink-Internal-Token": os.environ["NPCINK_CLOUD_INTERNAL_AUTH_TOKEN"]},
)
for _ in range(40):
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.load(response)
        seen: dict[str, datetime] = {}
        for item in payload.get("data", {}).get("workers", {}).get("items", []):
            worker_id = str(item.get("worker_id") or "")
            last_seen = str(item.get("last_seen_at") or "")
            if worker_id in required and last_seen:
                seen[worker_id] = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
        if all(seen.get(worker_id) and seen[worker_id] > cutoff for worker_id in required):
            raise SystemExit(0)
    except (KeyError, OSError, TypeError, ValueError):
        pass
    time.sleep(2)
raise SystemExit(1)
PY

CURRENT_STAGE="restore-previous-public-traffic"
create_prove_and_start_exact_services frontend proxy || \
	fail "previous frontend and proxy exact candidates could not be proved and started"
systemctl is-active --quiet nginx || fail "host NGINX is not active"
nginx -t >/dev/null 2>&1 || fail "host NGINX configuration is invalid"
BASE_URL="$(read_env_value "${PREVIOUS_ENV}" NPCINK_CLOUD_BASE_URL)" || fail "previous base URL cannot be read safely"
DOMAIN_NAME="$(read_env_value "${PREVIOUS_ENV}" NPCINK_CLOUD_DOMAIN_NAME)" || fail "previous domain cannot be read safely"
"${HOST_PYTHON}" - "${BASE_URL}" "${DOMAIN_NAME}" <<'PY' || fail "previous public origin contract is invalid"
from urllib.parse import urlsplit
import sys
base, domain = sys.argv[1:]
parsed = urlsplit(base)
if parsed.scheme != "https" or parsed.hostname != domain or parsed.port not in (None, 443):
    raise SystemExit(1)
if parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
    raise SystemExit(1)
PY
attempt=0
while [ "${attempt}" -lt 30 ]; do
	if curl_previous_public_ready "${BASE_URL}" "${DOMAIN_NAME}" >/dev/null 2>&1; then break; fi
	attempt=$((attempt + 1))
	sleep 2
done
[ "${attempt}" -lt 30 ] || fail "previous public HTTPS readiness did not recover"

CURRENT_STAGE="validate-matched-recovery"
assert_local_docker_identity || fail "local Docker daemon identity drifted before recovery commit"
assert_service_images || fail "recovered service image identity differs from the frozen recovery plan"
assert_expected_absent_image_tags || fail "post-migration-only image tags reappeared before recovery commit"
[ "$(readlink -f "${CURRENT_LINK}")" = "${PREVIOUS_RELEASE}" ] || fail "current pointer drifted after recovery"
assert_digest "${PREVIOUS_ENV}" "${ENV_SNAPSHOT_SHA256}" || fail "previous env drifted after recovery"
assert_digest "${MAINTENANCE_SNAPSHOT}" "${MAINTENANCE_SNAPSHOT_SHA256}" || fail "old-root snapshot drifted after recovery"
[ "$(docker exec "${POSTGRES_ID}" sh -c \
	'exec psql -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select version_num from alembic_version"')" = "${EXPECTED_SOURCE_REVISION}" ] || \
	fail "database revision drifted after recovery"
[ -z "$(docker ps -q \
	--filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
	--filter "label=com.docker.compose.service=caddy")" ] || fail "retired Caddy must remain stopped behind host NGINX"

CURRENT_STAGE="commit-recovery-evidence"
ROLLBACK_IMAGE_MAP_SHA256="$(sha256sum "${ROLLBACK_IMAGE_MAP}" | awk '{print $1}')"
[ ! -e "${RECOVERY_RESULT}" ] && [ ! -L "${RECOVERY_RESULT}" ] || fail "recovery result appeared while the deploy lock was held"
[ ! -e "${RECOVERY_LOCK_OWNER_ARCHIVE}" ] && [ ! -L "${RECOVERY_LOCK_OWNER_ARCHIVE}" ] || {
	assert_protected_file "${RECOVERY_LOCK_OWNER_ARCHIVE}" 600 && \
		assert_digest "${RECOVERY_LOCK_OWNER_ARCHIVE}" "${DEPLOY_LOCK_OWNER_SHA256}" || \
		fail "existing recovery lock-owner archive does not match the retained lock"
}
if [ ! -e "${RECOVERY_LOCK_OWNER_ARCHIVE}" ]; then
	link_protected_file_fresh "${LOCK_OWNER_FILE}" "${RECOVERY_LOCK_OWNER_ARCHIVE}" || \
		fail "recovery lock-owner archive could not be published"
fi
assert_protected_file "${RECOVERY_LOCK_OWNER_ARCHIVE}" 600 && \
	assert_digest "${RECOVERY_LOCK_OWNER_ARCHIVE}" "${DEPLOY_LOCK_OWNER_SHA256}" || \
	fail "recovery lock-owner archive is unsafe"
RECOVERY_TMP="${RECOVERY_RESULT}.tmp.$$"
trap '' HUP INT TERM
"${HOST_PYTHON}" - \
	"${RECOVERY_TMP}" "${FAILED_RELEASE}" "${PREVIOUS_RELEASE}" "${MARKER_SHA256}" \
	"${BACKUP_SHA256}" "${ENV_SNAPSHOT_SHA256}" "${MAINTENANCE_SNAPSHOT_SHA256}" \
	"${ROLLBACK_IMAGE_MAP_SHA256}" "${RECOVERY_IMAGE_PLAN_SHA256}" \
	"${DEPLOY_LOCK_OWNER_SHA256}" <<'PY'
import json
import os
import sys

(path, failed_release, previous_release, marker_sha256, backup_sha256,
 env_sha256, maintenance_sha256, rollback_map_sha256, image_plan_sha256,
 lock_owner_sha256) = sys.argv[1:]
payload = {
    "contract": "p1_e06_full_recovery.v1",
    "status": "passed",
    "failed_release": failed_release,
    "active_release": previous_release,
    "database_revision": "20260710_0058",
    "failure_marker_sha256": marker_sha256,
    "backup_sha256": backup_sha256,
    "previous_env_sha256": env_sha256,
    "maintenance_snapshot_sha256": maintenance_sha256,
    "rollback_image_map_sha256": rollback_map_sha256,
    "recovery_image_plan_sha256": image_plan_sha256,
    "deploy_lock_owner_sha256": lock_owner_sha256,
    "whole_database_restored": True,
    "previous_release_restored": True,
    "previous_external_env_restored": True,
    "both_old_roots_restored": True,
    "host_nginx_retained": True,
    "retired_caddy_started": False,
    "secret_values_included": False,
}
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
try:
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    view = memoryview(raw)
    while view:
        view = view[os.write(fd, view):]
    os.fchmod(fd, 0o600)
    os.fchown(fd, 0, 0)
    os.fsync(fd)
finally:
    os.close(fd)
PY
publish_fresh_temp "${RECOVERY_TMP}" "${RECOVERY_RESULT}" 0 || fail "recovery result fresh publication failed"
RECOVERY_COMMITTED=1
[ ! -e "${RECOVERY_TMP}" ] && [ ! -L "${RECOVERY_TMP}" ] || fail "recovery result temporary file remains"
assert_protected_file "${RECOVERY_RESULT}" 600 || fail "recovery result could not be published safely"
validate_recovery_result "${RECOVERY_RESULT}" "${ROLLBACK_IMAGE_MAP_SHA256}" \
	"${RECOVERY_IMAGE_PLAN_SHA256}" "${DEPLOY_LOCK_OWNER_SHA256}" || \
	fail "published recovery result does not match the exact committed recovery"
trap 'CURRENT_STAGE=signal-hup; exit 129' HUP
trap 'CURRENT_STAGE=signal-int; exit 130' INT
trap 'CURRENT_STAGE=signal-term; exit 143' TERM

trap '' HUP INT TERM
terminalize_recovery || fail "recovery terminalization failed"
trap 'CURRENT_STAGE=signal-hup; exit 129' HUP
trap 'CURRENT_STAGE=signal-int; exit 130' INT
trap 'CURRENT_STAGE=signal-term; exit 143' TERM

printf '[p1-e06-recovery:ok] matched 0058 recovery complete; evidence=%s\n' "${RECOVERY_RESULT}"
exit 0
