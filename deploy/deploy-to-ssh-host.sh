#!/usr/bin/env bash
set -euo pipefail
set +x

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "${ROOT_DIR}/deploy/common.sh"

SSH_HOST="${NPCINK_CLOUD_DEPLOY_SSH_HOST:-}"
SSH_USER="${NPCINK_CLOUD_DEPLOY_SSH_USER:-}"
SSH_PORT="${NPCINK_CLOUD_DEPLOY_SSH_PORT:-22}"
SSH_IDENTITY_FILE="${NPCINK_CLOUD_DEPLOY_IDENTITY_FILE:-}"
SSH_CONNECT_TIMEOUT_SECONDS="${NPCINK_CLOUD_DEPLOY_SSH_CONNECT_TIMEOUT_SECONDS:-10}"
DEPLOY_HOST_PYTHON="${NPCINK_CLOUD_DEPLOY_HOST_PYTHON:-/usr/bin/python3.11}"
REMOTE_DIR="${NPCINK_CLOUD_DEPLOY_REMOTE_DIR:-/opt/npcink-ai-cloud}"
BUNDLE_PATH="${NPCINK_CLOUD_DEPLOY_BUNDLE_PATH:-${ROOT_DIR}/dist/deploy-bundle.tgz}"
CONTROLLED_CVE_RISK_ACCEPTANCE="${NPCINK_CLOUD_CONTROLLED_CVE_RISK_ACCEPTANCE:-}"
CONTROLLED_CVE_RISK_ACCEPTANCE_CHECKSUM="${NPCINK_CLOUD_CONTROLLED_CVE_RISK_ACCEPTANCE_CHECKSUM:-}"
ENV_FILE="${NPCINK_CLOUD_ENV_FILE:-}"
IMAGE_PLATFORM="${NPCINK_CLOUD_IMAGE_PLATFORM:-}"
BASE_URL="${NPCINK_CLOUD_BASE_URL:-http://127.0.0.1:${NPCINK_CLOUD_PORT:-8010}}"
REMOTE_COMPOSE_FILE="${NPCINK_CLOUD_REMOTE_COMPOSE_FILE:-}"
SITE_ID="${NPCINK_CLOUD_SITE_ID:-site_smoke}"
KEY_ID="${NPCINK_CLOUD_KEY_ID:-key_default}"
SECRET="${NPCINK_CLOUD_SECRET:-}"
export -n SECRET 2>/dev/null || true
SCOPES="${NPCINK_CLOUD_SCOPES:-catalog:read,runtime:resolve,runtime:execute,runtime:read,stats:read}"
PROFILE_ID="${NPCINK_CLOUD_PROFILE_ID:-text.balanced}"
ABILITY_NAME="${NPCINK_CLOUD_ABILITY_NAME:-npcink-abilities-toolkit/build-article-block-plan}"
EXECUTION_KIND="${NPCINK_CLOUD_EXECUTION_KIND:-text}"
IDEMPOTENCY_SUFFIX="${NPCINK_CLOUD_IDEMPOTENCY_SUFFIX:-}"
PROMPT_TEXT="${NPCINK_CLOUD_PROMPT_TEXT:-remote deploy smoke request}"
EXPECTED_PROVIDER_ID="${NPCINK_CLOUD_EXPECTED_PROVIDER_ID:-}"
EXPECTED_MODEL_ID="${NPCINK_CLOUD_EXPECTED_MODEL_ID:-}"
EXPECTED_INSTANCE_ID="${NPCINK_CLOUD_EXPECTED_INSTANCE_ID:-}"
MEMBER_EMAIL="${NPCINK_CLOUD_MEMBER_EMAIL:-}"
SKIP_BUNDLE_BUILD=0
STAGE_ONLY=0
SKIP_SEED=0
SKIP_SMOKE=0
WITH_PORTAL_SMOKE=0
REFRESH_PROVIDERS="${NPCINK_CLOUD_REFRESH_PROVIDERS:-0}"
WITH_OPERATIONAL_READY="${NPCINK_CLOUD_WITH_OPERATIONAL_READY:-0}"
SKIP_FRONTEND_IMAGE="${NPCINK_CLOUD_SKIP_FRONTEND_IMAGE:-0}"
STAGE_ONLY_DISALLOWED_CLI=()

while [ "$#" -gt 0 ]; do
	case "$1" in
		--)
			shift
			;;
		--ssh-host)
			SSH_HOST="$2"
			shift 2
			;;
		--ssh-user)
			SSH_USER="$2"
			shift 2
			;;
		--ssh-port)
			SSH_PORT="$2"
			shift 2
			;;
		--identity-file)
			SSH_IDENTITY_FILE="$2"
			shift 2
			;;
		--host-python)
			DEPLOY_HOST_PYTHON="$2"
			shift 2
			;;
		--remote-dir)
			REMOTE_DIR="$2"
			shift 2
			;;
		--bundle-path)
			BUNDLE_PATH="$2"
			shift 2
			;;
		--controlled-cve-risk-acceptance)
			CONTROLLED_CVE_RISK_ACCEPTANCE="$2"
			shift 2
			;;
		--controlled-cve-risk-acceptance-checksum)
			CONTROLLED_CVE_RISK_ACCEPTANCE_CHECKSUM="$2"
			shift 2
			;;
		--env-file)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			ENV_FILE="$2"
			shift 2
			;;
		--image-platform)
			IMAGE_PLATFORM="$2"
			shift 2
			;;
		--base-url)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			BASE_URL="$2"
			shift 2
			;;
		--remote-compose-file)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			REMOTE_COMPOSE_FILE="$2"
			shift 2
			;;
		--site-id)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			SITE_ID="$2"
			shift 2
			;;
		--key-id)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			KEY_ID="$2"
			shift 2
			;;
		--secret)
			echo "[fail] --secret is forbidden because process arguments are observable; --stage-only accepts only bundle/platform, controlled-CVE evidence, SSH, managed-root, and host-Python options. Use NPCINK_CLOUD_SECRET from a protected process environment for a full deployment." >&2
			exit 1
			;;
		--scopes)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			SCOPES="$2"
			shift 2
			;;
		--profile-id)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			PROFILE_ID="$2"
			shift 2
			;;
		--ability-name)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			ABILITY_NAME="$2"
			shift 2
			;;
		--execution-kind)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			EXECUTION_KIND="$2"
			shift 2
			;;
		--idempotency-suffix)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			IDEMPOTENCY_SUFFIX="$2"
			shift 2
			;;
		--prompt-text)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			PROMPT_TEXT="$2"
			shift 2
			;;
		--expected-provider-id)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			EXPECTED_PROVIDER_ID="$2"
			shift 2
			;;
		--expected-model-id)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			EXPECTED_MODEL_ID="$2"
			shift 2
			;;
		--expected-instance-id)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			EXPECTED_INSTANCE_ID="$2"
			shift 2
			;;
		--member-email)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			MEMBER_EMAIL="$2"
			shift 2
			;;
		--skip-bundle-build)
			SKIP_BUNDLE_BUILD=1
			shift
			;;
		--stage-only)
			STAGE_ONLY=1
			shift
			;;
		--skip-seed)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			SKIP_SEED=1
			shift
			;;
		--skip-smoke)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			SKIP_SMOKE=1
			shift
			;;
		--with-portal-smoke)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			WITH_PORTAL_SMOKE=1
			shift
			;;
		--refresh-providers)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			REFRESH_PROVIDERS=1
			shift
			;;
		--with-operational-ready)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			WITH_OPERATIONAL_READY=1
			shift
			;;
		--skip-frontend-image)
			STAGE_ONLY_DISALLOWED_CLI+=("$1")
			SKIP_FRONTEND_IMAGE=1
			shift
			;;
		*)
			echo "[fail] Unknown argument: $1" >&2
			exit 1
			;;
	esac
done

# Retain the runtime signing value only as a non-exported shell variable. This
# keeps it out of every ssh/scp/build child environment and all process argv.
unset NPCINK_CLOUD_SECRET

# The checksum is a sidecar of the final CLI-selected bundle path. Deriving it
# before argument parsing would silently verify/upload the wrong receipt.
BUNDLE_CHECKSUM_PATH="${BUNDLE_PATH}.sha256"

if [ "${REMOTE_DIR}" = "/" ] || [[ ! "${REMOTE_DIR}" =~ ^/[A-Za-z0-9._/-]+$ ]]; then
	echo "[fail] Remote deploy directory must be a non-root absolute path using only A-Z, a-z, 0-9, dot, underscore, dash, and slash." >&2
	exit 1
fi
case "/${REMOTE_DIR#/}/" in
	*//*|*/./*|*/../*)
		echo "[fail] Remote deploy directory must use canonical path segments." >&2
		exit 1
		;;
esac

for forbidden_deploy_override in \
	NPCINK_CLOUD_DEPLOY_SMOKE_BACKEND_ENV \
	NPCINK_CLOUD_DEPLOY_SMOKE_FRONTEND_ENV \
	NPCINK_CLOUD_DEPLOY_SMOKE_SETUP_STATE_OVERRIDE \
	NPCINK_CLOUD_API_WORKERS; do
	if [ -n "${!forbidden_deploy_override:-}" ]; then
		echo "[fail] Production deployment rejects contract override: ${forbidden_deploy_override}" >&2
		exit 1
	fi
done
if [ -z "${SSH_HOST}" ]; then
	echo "[fail] Missing --ssh-host or NPCINK_CLOUD_DEPLOY_SSH_HOST" >&2
	exit 1
fi

if [ -n "${SSH_IDENTITY_FILE}" ] && [ ! -f "${SSH_IDENTITY_FILE}" ]; then
	echo "[fail] SSH identity file not found: ${SSH_IDENTITY_FILE}" >&2
	exit 1
fi

if [ -z "${DEPLOY_HOST_PYTHON}" ]; then
	echo "[fail] --host-python or NPCINK_CLOUD_DEPLOY_HOST_PYTHON must not be empty." >&2
	exit 1
fi

if [ "${STAGE_ONLY}" = "1" ] && [ -n "${ENV_FILE}" ]; then
	echo "[fail] --stage-only does not accept an env file." >&2
	exit 1
fi

if [ "${STAGE_ONLY}" = "1" ] && [ "${#STAGE_ONLY_DISALLOWED_CLI[@]}" -ne 0 ]; then
	echo "[fail] --stage-only accepts only bundle/platform, controlled-CVE evidence, SSH, managed-root, and host-Python options; rejected: ${STAGE_ONLY_DISALLOWED_CLI[*]}" >&2
	exit 1
fi

if [ "${STAGE_ONLY}" != "1" ] && \
	{ [ "${SKIP_SEED}" != "1" ] || [ "${SKIP_SMOKE}" != "1" ]; } && \
	[ -z "${SECRET}" ]; then
	echo "[fail] NPCINK_CLOUD_SECRET is required unless both runtime seed and signed smoke are skipped." >&2
	exit 1
fi

if [ -n "${ENV_FILE}" ] && [ ! -f "${ENV_FILE}" ]; then
	echo "[fail] Env file not found: ${ENV_FILE}" >&2
	exit 1
fi

if { [ -n "${CONTROLLED_CVE_RISK_ACCEPTANCE}" ] && [ -z "${CONTROLLED_CVE_RISK_ACCEPTANCE_CHECKSUM}" ]; } || \
	{ [ -z "${CONTROLLED_CVE_RISK_ACCEPTANCE}" ] && [ -n "${CONTROLLED_CVE_RISK_ACCEPTANCE_CHECKSUM}" ]; }; then
	echo "[fail] Controlled CVE risk acceptance and its independent checksum must be supplied together." >&2
	exit 1
fi

for command_name in bash ssh scp tar mktemp; do
	npcink_ai_cloud_require_cmd "${command_name}"
done
LOCAL_RELEASE_TOOL_PYTHON="$(npcink_ai_cloud_release_tool_python)"
npcink_ai_cloud_require_release_tool_python "${LOCAL_RELEASE_TOOL_PYTHON}"

if [ -n "${REMOTE_COMPOSE_FILE}" ]; then
	echo "[info] Requested remote compose file: ${REMOTE_COMPOSE_FILE}"
fi

SSH_TARGET="${SSH_HOST}"
if [ -n "${SSH_USER}" ]; then
	SSH_TARGET="${SSH_USER}@${SSH_HOST}"
fi

SSH_ARGS=(
	-p "${SSH_PORT}"
	-o StrictHostKeyChecking=yes
	-o BatchMode=yes
	-o ConnectTimeout="${SSH_CONNECT_TIMEOUT_SECONDS}"
)
SCP_ARGS=(
	-P "${SSH_PORT}"
	-o StrictHostKeyChecking=yes
	-o BatchMode=yes
	-o ConnectTimeout="${SSH_CONNECT_TIMEOUT_SECONDS}"
)

if [ -n "${SSH_IDENTITY_FILE}" ]; then
	SSH_ARGS+=(-i "${SSH_IDENTITY_FILE}")
	SCP_ARGS+=(-i "${SSH_IDENTITY_FILE}")
fi

resolve_remote_platform() {
	local remote_arch="$1"
	case "${remote_arch}" in
		x86_64|amd64)
			echo "linux/amd64"
			;;
		aarch64|arm64)
			echo "linux/arm64"
			;;
		*)
			echo ""
			;;
	esac
}

remote_shell_arg() {
	printf '%q' "$1"
}

npcink_ai_cloud_start_timing_summary "Deploy Step Timing"

if ! npcink_ai_cloud_run_timed "ssh reachability check" ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "true" >/dev/null 2>&1; then
	echo "[fail] SSH target is not reachable: ${SSH_TARGET}:${SSH_PORT}" >&2
	echo "[fail] Check NPCINK_CLOUD_DEPLOY_IDENTITY_FILE, firewall/security group, and sshd." >&2
	exit 1
fi
if ! REMOTE_DEPLOY_UID="$(ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "id -u")"; then
	echo "[fail] Remote deployment account UID could not be verified." >&2
	exit 1
fi
if [ "${REMOTE_DEPLOY_UID}" != "0" ]; then
	echo "[fail] Production releases use a root-managed tree; the remote deployment account must have UID 0." >&2
	exit 1
fi
REMOTE_PYTHON_PROBE='import sys; print(".".join(map(str, sys.version_info[:3]))); raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
if ! REMOTE_HOST_PYTHON_VERSION="$(
	ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" \
		"$(remote_shell_arg "${DEPLOY_HOST_PYTHON}") -c $(remote_shell_arg "${REMOTE_PYTHON_PROBE}")"
)"; then
	echo "[fail] Remote host release-tool Python must be executable and version 3.11 or newer: ${DEPLOY_HOST_PYTHON}" >&2
	exit 1
fi
echo "[info] Remote host release-tool Python: ${DEPLOY_HOST_PYTHON} (${REMOTE_HOST_PYTHON_VERSION})"
REMOTE_ARCH_STARTED_AT="$(date +%s)"
REMOTE_ARCH="$(ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "uname -m")"
REMOTE_ARCH_DURATION_SECONDS=$(($(date +%s) - REMOTE_ARCH_STARTED_AT))
echo "[timing] resolve remote architecture: ${REMOTE_ARCH_DURATION_SECONDS}s"
npcink_ai_cloud_append_timing_summary "resolve remote architecture" "${REMOTE_ARCH_DURATION_SECONDS}"
REMOTE_PLATFORM="$(resolve_remote_platform "${REMOTE_ARCH}")"
if [ -z "${REMOTE_PLATFORM}" ]; then
	echo "[fail] Unsupported remote architecture: ${REMOTE_ARCH}" >&2
	exit 1
fi
if [ -n "${IMAGE_PLATFORM}" ] && [ "${IMAGE_PLATFORM}" != "${REMOTE_PLATFORM}" ]; then
	echo "[fail] Requested image platform ${IMAGE_PLATFORM} does not match remote architecture ${REMOTE_ARCH} (${REMOTE_PLATFORM})." >&2
	exit 1
fi
IMAGE_PLATFORM="${REMOTE_PLATFORM}"
echo "[info] Remote architecture ${REMOTE_ARCH}; selected image platform ${IMAGE_PLATFORM}"

if [ "${SKIP_BUNDLE_BUILD}" -eq 0 ]; then
	echo "[info] Building deploy bundle"
	npcink_ai_cloud_run_timed "build deploy bundle" \
		env \
		NPCINK_CLOUD_IMAGE_PLATFORM="${IMAGE_PLATFORM}" \
		NPCINK_CLOUD_SKIP_FRONTEND_IMAGE="${SKIP_FRONTEND_IMAGE}" \
		bash "${ROOT_DIR}/deploy/bundle-images.sh"
fi

if [ ! -f "${BUNDLE_PATH}" ]; then
	echo "[fail] Deploy bundle not found: ${BUNDLE_PATH}" >&2
	exit 1
fi
if [ ! -f "${BUNDLE_CHECKSUM_PATH}" ]; then
	echo "[fail] Deploy bundle checksum not found: ${BUNDLE_CHECKSUM_PATH}" >&2
	exit 1
fi
npcink_ai_cloud_run_timed "verify local deploy bundle archive" \
	bash "${ROOT_DIR}/deploy/verify-release-bundle.sh" --archive \
	"${BUNDLE_PATH}" "${BUNDLE_CHECKSUM_PATH}"
BUNDLE_PLATFORM="$(
	"${LOCAL_RELEASE_TOOL_PYTHON}" "${ROOT_DIR}/scripts/verify-release-bundle-manifest.py" archive-platform \
		--bundle "${BUNDLE_PATH}" --checksum "${BUNDLE_CHECKSUM_PATH}"
)"
if [ "${BUNDLE_PLATFORM}" != "${IMAGE_PLATFORM}" ]; then
	echo "[fail] Deploy bundle platform ${BUNDLE_PLATFORM} does not match target platform ${IMAGE_PLATFORM}." >&2
	exit 1
fi

FIRST_INSTALL_CVE_GATE_ARGS=(--bundle "${BUNDLE_PATH}")
if [ -n "${CONTROLLED_CVE_RISK_ACCEPTANCE}" ]; then
	FIRST_INSTALL_CVE_GATE_ARGS+=(
		--controlled-risk-acceptance "${CONTROLLED_CVE_RISK_ACCEPTANCE}"
		--controlled-risk-acceptance-checksum "${CONTROLLED_CVE_RISK_ACCEPTANCE_CHECKSUM}"
	)
fi

if [ "${STAGE_ONLY}" != "1" ]; then
	REMOTE_INSTALLATION_STATE="$(
		ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" \
			"$(remote_shell_arg "${DEPLOY_HOST_PYTHON}") - $(remote_shell_arg "${REMOTE_DIR}/shared/config/install-state.json")" <<'PY'
import json
import os
import stat
import sys
from pathlib import Path

MAX_INSTALL_STATE_BYTES = 1024 * 1024


def validate_metadata(metadata: os.stat_result) -> None:
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o640
        or (metadata.st_uid, metadata.st_gid) != (999, 999)
    ):
        raise ValueError("Remote install-state.json protection is unsafe.")


def snapshot(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


path = Path(sys.argv[1])
try:
    path_metadata_before = path.lstat()
except FileNotFoundError:
    print("missing")
    raise SystemExit(0)
descriptor = -1
try:
    validate_metadata(path_metadata_before)
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0),
    )
    descriptor_metadata_before = os.fstat(descriptor)
    validate_metadata(descriptor_metadata_before)
    expected_snapshot = snapshot(descriptor_metadata_before)
    if snapshot(path_metadata_before) != expected_snapshot:
        raise ValueError("install-state path changed while opening")
    chunks: list[bytes] = []
    observed_bytes = 0
    while True:
        chunk = os.read(descriptor, 65536)
        if not chunk:
            break
        observed_bytes += len(chunk)
        if observed_bytes > MAX_INSTALL_STATE_BYTES:
            raise ValueError("install-state.json exceeds the protected size limit")
        chunks.append(chunk)
    descriptor_metadata_after = os.fstat(descriptor)
    path_metadata_after = path.lstat()
    validate_metadata(descriptor_metadata_after)
    validate_metadata(path_metadata_after)
    if (
        snapshot(descriptor_metadata_after) != expected_snapshot
        or snapshot(path_metadata_after) != expected_snapshot
    ):
        raise ValueError("install-state path changed while reading")
    payload = json.loads(b"".join(chunks).decode("utf-8"))
except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
    raise SystemExit("[fail] Remote installation state is unreadable.") from exc
finally:
    if descriptor >= 0:
        os.close(descriptor)
state = payload.get("installation_state") if isinstance(payload, dict) else None
if state not in {"pending", "initializing", "complete"}:
    raise SystemExit("[fail] Remote installation state is unsupported.")
print(state)
PY
	)"
	case "${REMOTE_INSTALLATION_STATE}" in
		missing|pending)
			"${LOCAL_RELEASE_TOOL_PYTHON}" \
				"${ROOT_DIR}/scripts/check-first-install-cve-gate.py" \
				"${FIRST_INSTALL_CVE_GATE_ARGS[@]}" >/dev/null || {
				echo "[fail] First-install host mutation is forbidden while the exact release retains the Python 3.14.6 CVE exceptions." >&2
				exit 1
			}
			;;
		initializing)
			echo "[fail] Remote first installation is initializing; deployment will not mutate the host." >&2
			exit 1
			;;
		complete) ;;
	esac
fi

if [ "${STAGE_ONLY}" = "1" ]; then
	"${LOCAL_RELEASE_TOOL_PYTHON}" \
		"${ROOT_DIR}/scripts/check-first-install-cve-gate.py" \
		"${FIRST_INSTALL_CVE_GATE_ARGS[@]}" >/dev/null || {
		echo "[fail] Stage-only upload is forbidden while the exact release retains unaccepted Python 3.14.6 CVE exceptions." >&2
		exit 1
	}
fi

BUNDLE_CHECKSUM_LINE="$(cat "${BUNDLE_CHECKSUM_PATH}")"
BUNDLE_SHA256="${BUNDLE_CHECKSUM_LINE%% *}"
if [[ ! "${BUNDLE_SHA256}" =~ ^[0-9a-f]{64}$ ]]; then
	echo "[fail] Deploy bundle checksum receipt is invalid." >&2
	exit 1
fi
UPLOAD_ID="${BUNDLE_SHA256:0:16}-$(date -u +%Y%m%d%H%M%S)-$$"
RELEASE_NAME="release-${UPLOAD_ID}"
REMOTE_INCOMING_DIR="${REMOTE_DIR}/.incoming/${UPLOAD_ID}"
REMOTE_BUNDLE_PATH="${REMOTE_INCOMING_DIR}/deploy-bundle.tgz"
REMOTE_BUNDLE_CHECKSUM_PATH="${REMOTE_BUNDLE_PATH}.sha256"
REMOTE_PREFLIGHT_DIR="${REMOTE_INCOMING_DIR}/preflight"
REMOTE_ENV_BASENAME=".env.deploy"
REMOTE_ENV_PATH=""
REMOTE_DEPLOY_INPUT_PATH="${REMOTE_INCOMING_DIR}/deploy-input.json"
LOCAL_DEPLOY_INPUT_DIR=""
LOCAL_DEPLOY_INPUT_PATH=""
LOCAL_DEPLOY_INPUT_NEEDS_CLEANUP=0
REMOTE_INCOMING_NEEDS_CLEANUP=1

cleanup_remote_incoming_on_exit() {
	local exit_status="$?"
	local cleanup_failed=0
	trap - EXIT
	set +e
	if [ "${LOCAL_DEPLOY_INPUT_NEEDS_CLEANUP}" = "1" ]; then
		rm -f -- "${LOCAL_DEPLOY_INPUT_PATH}" || cleanup_failed=1
		rmdir -- "${LOCAL_DEPLOY_INPUT_DIR}" || cleanup_failed=1
		if [ -e "${LOCAL_DEPLOY_INPUT_DIR}" ] || [ -L "${LOCAL_DEPLOY_INPUT_DIR}" ]; then
			cleanup_failed=1
		fi
	fi
	if [ "${REMOTE_INCOMING_NEEDS_CLEANUP}" = "1" ]; then
		if ! ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" \
			"rm -rf $(remote_shell_arg "${REMOTE_INCOMING_DIR}") && test ! -e $(remote_shell_arg "${REMOTE_INCOMING_DIR}")" >/dev/null 2>&1; then
			echo "[fail] Could not prove remote incoming upload cleanup: ${REMOTE_INCOMING_DIR}" >&2
			cleanup_failed=1
		fi
	fi
	if [ "${cleanup_failed}" -ne 0 ]; then
		echo "[fail] Deployment credential/upload cleanup did not complete." >&2
		exit_status=1
	fi
	exit "${exit_status}"
}
trap cleanup_remote_incoming_on_exit EXIT

echo "[info] Preparing remote directory ${SSH_TARGET}:${REMOTE_DIR}"
npcink_ai_cloud_run_timed "prepare remote directory" \
	ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" \
		"mkdir -p $(remote_shell_arg "${REMOTE_DIR}") $(remote_shell_arg "${REMOTE_PREFLIGHT_DIR}/deploy") $(remote_shell_arg "${REMOTE_PREFLIGHT_DIR}/scripts") && chmod 0700 $(remote_shell_arg "${REMOTE_INCOMING_DIR}")"

echo "[info] Uploading deploy bundle"
npcink_ai_cloud_run_timed "upload deploy bundle" \
	scp "${SCP_ARGS[@]}" "${BUNDLE_PATH}" "${SSH_TARGET}:${REMOTE_BUNDLE_PATH}"
npcink_ai_cloud_run_timed "upload deploy bundle checksum" \
	scp "${SCP_ARGS[@]}" "${BUNDLE_CHECKSUM_PATH}" "${SSH_TARGET}:${REMOTE_BUNDLE_CHECKSUM_PATH}"
npcink_ai_cloud_run_timed "upload deploy bundle preflight" \
	scp "${SCP_ARGS[@]}" \
	"${ROOT_DIR}/deploy/verify-release-bundle.sh" \
	"${SSH_TARGET}:${REMOTE_PREFLIGHT_DIR}/deploy/verify-release-bundle.sh"
npcink_ai_cloud_run_timed "upload deploy bundle preflight common helper" \
	scp "${SCP_ARGS[@]}" \
	"${ROOT_DIR}/deploy/common.sh" \
	"${SSH_TARGET}:${REMOTE_PREFLIGHT_DIR}/deploy/common.sh"
npcink_ai_cloud_run_timed "upload deploy bundle manifest verifier" \
	scp "${SCP_ARGS[@]}" \
	"${ROOT_DIR}/scripts/verify-release-bundle-manifest.py" \
	"${SSH_TARGET}:${REMOTE_PREFLIGHT_DIR}/scripts/verify-release-bundle-manifest.py"
npcink_ai_cloud_run_timed "verify remote deploy bundle before extraction" \
	ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" \
		"set +e; NPCINK_CLOUD_RELEASE_TOOL_PYTHON=$(remote_shell_arg "${DEPLOY_HOST_PYTHON}") bash $(remote_shell_arg "${REMOTE_PREFLIGHT_DIR}/deploy/verify-release-bundle.sh") --archive $(remote_shell_arg "${REMOTE_BUNDLE_PATH}") $(remote_shell_arg "${REMOTE_BUNDLE_CHECKSUM_PATH}"); preflight_status=\$?; rm -rf $(remote_shell_arg "${REMOTE_PREFLIGHT_DIR}"); exit \${preflight_status}"

if [ -n "${ENV_FILE}" ]; then
	REMOTE_ENV_PATH="${REMOTE_INCOMING_DIR}/${REMOTE_ENV_BASENAME}"
	echo "[info] Uploading env file"
	npcink_ai_cloud_run_timed "upload env file" \
		scp "${SCP_ARGS[@]}" "${ENV_FILE}" "${SSH_TARGET}:${REMOTE_ENV_PATH}"
	npcink_ai_cloud_run_timed "restrict uploaded env file" \
		ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" \
			"chmod 0600 $(remote_shell_arg "${REMOTE_ENV_PATH}") && test \"\$(stat -c '%a' $(remote_shell_arg "${REMOTE_ENV_PATH}"))\" = 600"
fi

if [ "${STAGE_ONLY}" != "1" ]; then
	LOCAL_DEPLOY_INPUT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/npcink-cloud-deploy-input.XXXXXX")"
	LOCAL_DEPLOY_INPUT_PATH="${LOCAL_DEPLOY_INPUT_DIR}/deploy-input.json"
	LOCAL_DEPLOY_INPUT_NEEDS_CLEANUP=1
	chmod 0700 "${LOCAL_DEPLOY_INPUT_DIR}"
	NPCINK_INPUT_REMOTE_ENV_BASENAME="${REMOTE_ENV_BASENAME}" \
	NPCINK_INPUT_SITE_ID="${SITE_ID}" \
	NPCINK_INPUT_KEY_ID="${KEY_ID}" \
	NPCINK_INPUT_SECRET="${SECRET}" \
	NPCINK_INPUT_SCOPES="${SCOPES}" \
	NPCINK_INPUT_BASE_URL="${BASE_URL}" \
	NPCINK_INPUT_PROFILE_ID="${PROFILE_ID}" \
	NPCINK_INPUT_ABILITY_NAME="${ABILITY_NAME}" \
	NPCINK_INPUT_EXECUTION_KIND="${EXECUTION_KIND}" \
	NPCINK_INPUT_IDEMPOTENCY_SUFFIX="${IDEMPOTENCY_SUFFIX}" \
	NPCINK_INPUT_PROMPT_TEXT="${PROMPT_TEXT}" \
	NPCINK_INPUT_EXPECTED_PROVIDER_ID="${EXPECTED_PROVIDER_ID}" \
	NPCINK_INPUT_EXPECTED_MODEL_ID="${EXPECTED_MODEL_ID}" \
	NPCINK_INPUT_EXPECTED_INSTANCE_ID="${EXPECTED_INSTANCE_ID}" \
	NPCINK_INPUT_MEMBER_EMAIL="${MEMBER_EMAIL}" \
	NPCINK_INPUT_SKIP_SEED="${SKIP_SEED}" \
	NPCINK_INPUT_SKIP_SMOKE="${SKIP_SMOKE}" \
	NPCINK_INPUT_REMOTE_ENV_PATH="${REMOTE_ENV_PATH}" \
	NPCINK_INPUT_WITH_PORTAL_SMOKE="${WITH_PORTAL_SMOKE}" \
	NPCINK_INPUT_SKIP_FRONTEND_IMAGE="${SKIP_FRONTEND_IMAGE}" \
	NPCINK_INPUT_REMOTE_COMPOSE_FILE="${REMOTE_COMPOSE_FILE}" \
	NPCINK_INPUT_REFRESH_PROVIDERS="${REFRESH_PROVIDERS}" \
	NPCINK_INPUT_WITH_OPERATIONAL_READY="${WITH_OPERATIONAL_READY}" \
		"${LOCAL_RELEASE_TOOL_PYTHON}" - "${LOCAL_DEPLOY_INPUT_PATH}" <<'PY'
from __future__ import annotations

import json
import os
import stat
import sys

path = sys.argv[1]
prefix = "NPCINK_INPUT_"
payload = {
    key.removeprefix(prefix): value
    for key, value in os.environ.items()
    if key.startswith(prefix)
}
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    handle.write("\n")
metadata = os.lstat(path)
if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
    raise SystemExit("[fail] Local deployment input must be a regular mode-0600 file.")
if metadata.st_uid != os.geteuid():
    raise SystemExit("[fail] Local deployment input must be owned by the current account.")
PY
	echo "[info] Uploading protected deployment input"
	npcink_ai_cloud_run_timed "upload protected deployment input" \
		scp "${SCP_ARGS[@]}" "${LOCAL_DEPLOY_INPUT_PATH}" "${SSH_TARGET}:${REMOTE_DEPLOY_INPUT_PATH}"
	npcink_ai_cloud_run_timed "restrict protected deployment input" \
		ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" \
			"test ! -L $(remote_shell_arg "${REMOTE_DEPLOY_INPUT_PATH}") && test -f $(remote_shell_arg "${REMOTE_DEPLOY_INPUT_PATH}") && chmod 0600 $(remote_shell_arg "${REMOTE_DEPLOY_INPUT_PATH}") && test \"\$(stat -c '%a' $(remote_shell_arg "${REMOTE_DEPLOY_INPUT_PATH}"))\" = 600 && test \"\$(stat -c '%u' $(remote_shell_arg "${REMOTE_DEPLOY_INPUT_PATH}"))\" = 0"
	if ! rm -f -- "${LOCAL_DEPLOY_INPUT_PATH}" || \
		! rmdir -- "${LOCAL_DEPLOY_INPUT_DIR}" || \
		[ -e "${LOCAL_DEPLOY_INPUT_DIR}" ] || [ -L "${LOCAL_DEPLOY_INPUT_DIR}" ]; then
		echo "[fail] Local deployment input cleanup did not complete." >&2
		exit 1
	fi
	LOCAL_DEPLOY_INPUT_NEEDS_CLEANUP=0
fi

if [ "${WITH_OPERATIONAL_READY}" = "1" ]; then
	echo "[info] Operational readiness gate: enabled"
else
	echo "[info] Operational readiness gate: disabled"
fi

if [ "${STAGE_ONLY}" = "1" ]; then
	# Keep the stage-only remote argv intentionally minimal. In particular, no
	# site credential, smoke prompt, member email, or deployment env path crosses
	# the SSH command line for a staging-only operation.
	REMOTE_SEQUENCE_VALUES=(
		stage-only
		"${REMOTE_DIR}"
		"${RELEASE_NAME}"
		"${REMOTE_BUNDLE_PATH}"
		"${REMOTE_INCOMING_DIR}"
		"${DEPLOY_HOST_PYTHON}"
	)
else
	REMOTE_SEQUENCE_VALUES=(
		deploy
		"${REMOTE_DIR}"
		"${RELEASE_NAME}"
		"${REMOTE_BUNDLE_PATH}"
		"${REMOTE_INCOMING_DIR}"
		"${DEPLOY_HOST_PYTHON}"
	)
fi
REMOTE_SEQUENCE_ARGS=()
for remote_sequence_value in "${REMOTE_SEQUENCE_VALUES[@]}"; do
	REMOTE_SEQUENCE_ARGS+=("$(remote_shell_arg "${remote_sequence_value}")")
done

echo "[info] Running remote deploy sequence on ${SSH_TARGET}"
npcink_ai_cloud_run_timed "remote deploy sequence" \
	ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" bash -s -- \
	"${REMOTE_SEQUENCE_ARGS[@]}" <<'EOF'
set -euo pipefail
set +x

if [ "$#" -lt 1 ]; then
	echo "[fail] Missing remote deployment sequence mode." >&2
	exit 64
fi
REMOTE_SEQUENCE_MODE="$1"
shift

case "${REMOTE_SEQUENCE_MODE}" in
	stage-only)
		[ "$#" -eq 5 ] || {
			echo "[fail] Stage-only remote entry requires exactly five arguments." >&2
			exit 64
		}
		REMOTE_DIR="$1"
		RELEASE_NAME="$2"
		REMOTE_BUNDLE_PATH="$3"
		REMOTE_INCOMING_DIR="$4"
		RELEASE_TOOL_PYTHON="$5"
		REMOTE_ENV_BASENAME=".env.deploy"
		SITE_ID=""
		KEY_ID=""
		SECRET=""
		SCOPES=""
		BASE_URL=""
		PROFILE_ID=""
		ABILITY_NAME=""
		EXECUTION_KIND=""
		IDEMPOTENCY_SUFFIX=""
		PROMPT_TEXT=""
		EXPECTED_PROVIDER_ID=""
		EXPECTED_MODEL_ID=""
		EXPECTED_INSTANCE_ID=""
		MEMBER_EMAIL=""
		SKIP_SEED=1
		SKIP_SMOKE=1
		REMOTE_ENV_PATH=""
		WITH_PORTAL_SMOKE=0
		SKIP_FRONTEND_IMAGE=0
		REMOTE_COMPOSE_FILE=""
		REFRESH_PROVIDERS=0
		WITH_OPERATIONAL_READY=0
		STAGE_ONLY=1
		;;
	deploy)
		[ "$#" -eq 5 ] || {
			echo "[fail] Full remote deployment entry requires exactly five non-secret arguments." >&2
			exit 64
		}
		REMOTE_DIR="$1"
		RELEASE_NAME="$2"
		REMOTE_BUNDLE_PATH="$3"
		REMOTE_INCOMING_DIR="$4"
		RELEASE_TOOL_PYTHON="$5"
		REMOTE_DEPLOY_INPUT_PATH="${REMOTE_INCOMING_DIR}/deploy-input.json"
		if [ "$(id -u)" != "0" ] || [ -L "${REMOTE_DEPLOY_INPUT_PATH}" ] || \
			[ ! -f "${REMOTE_DEPLOY_INPUT_PATH}" ] || \
			[ "$(stat -c '%a' "${REMOTE_DEPLOY_INPUT_PATH}")" != "600" ] || \
			[ "$(stat -c '%u' "${REMOTE_DEPLOY_INPUT_PATH}")" != "0" ]; then
			echo "[fail] Protected deployment input must be a root-owned regular mode-0600 file." >&2
			exit 1
		fi
		if ! REMOTE_INPUT_ASSIGNMENTS="$("${RELEASE_TOOL_PYTHON}" - "${REMOTE_DEPLOY_INPUT_PATH}" <<'PY'
from __future__ import annotations

import json
import shlex
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)
mapping = {
    "REMOTE_ENV_BASENAME": "REMOTE_ENV_BASENAME",
    "SITE_ID": "SITE_ID",
    "KEY_ID": "KEY_ID",
    "SECRET": "SECRET",
    "SCOPES": "SCOPES",
    "BASE_URL": "BASE_URL",
    "PROFILE_ID": "PROFILE_ID",
    "ABILITY_NAME": "ABILITY_NAME",
    "EXECUTION_KIND": "EXECUTION_KIND",
    "IDEMPOTENCY_SUFFIX": "IDEMPOTENCY_SUFFIX",
    "PROMPT_TEXT": "PROMPT_TEXT",
    "EXPECTED_PROVIDER_ID": "EXPECTED_PROVIDER_ID",
    "EXPECTED_MODEL_ID": "EXPECTED_MODEL_ID",
    "EXPECTED_INSTANCE_ID": "EXPECTED_INSTANCE_ID",
    "MEMBER_EMAIL": "MEMBER_EMAIL",
    "SKIP_SEED": "SKIP_SEED",
    "SKIP_SMOKE": "SKIP_SMOKE",
    "REMOTE_ENV_PATH": "REMOTE_ENV_PATH",
    "WITH_PORTAL_SMOKE": "WITH_PORTAL_SMOKE",
    "SKIP_FRONTEND_IMAGE": "SKIP_FRONTEND_IMAGE",
    "REMOTE_COMPOSE_FILE": "REMOTE_COMPOSE_FILE",
    "REFRESH_PROVIDERS": "REFRESH_PROVIDERS",
    "WITH_OPERATIONAL_READY": "WITH_OPERATIONAL_READY",
}
if not isinstance(payload, dict) or set(payload) != set(mapping):
    raise SystemExit("[fail] Protected deployment input schema mismatch.")
for source, target in mapping.items():
    value = payload[source]
    if not isinstance(value, str):
        raise SystemExit("[fail] Protected deployment input values must be strings.")
    print(f"{target}={shlex.quote(value)}")
PY
)"; then
			echo "[fail] Protected deployment input could not be parsed." >&2
			exit 1
		fi
		eval "${REMOTE_INPUT_ASSIGNMENTS}"
		unset REMOTE_INPUT_ASSIGNMENTS
		export -n SECRET 2>/dev/null || true
		if ! rm -f -- "${REMOTE_DEPLOY_INPUT_PATH}" || \
			[ -e "${REMOTE_DEPLOY_INPUT_PATH}" ] || [ -L "${REMOTE_DEPLOY_INPUT_PATH}" ]; then
			echo "[fail] Protected deployment input cleanup did not complete." >&2
			exit 1
		fi
		STAGE_ONLY=0
		;;
	*)
		echo "[fail] Unsupported remote deployment sequence mode: ${REMOTE_SEQUENCE_MODE}" >&2
		exit 64
		;;
esac
export NPCINK_CLOUD_RELEASE_TOOL_PYTHON="${RELEASE_TOOL_PYTHON}"

RELEASE_DIR="${REMOTE_DIR}/${RELEASE_NAME}"
CURRENT_LINK="${REMOTE_DIR}/current"
DEPLOY_LOCK_DIR="${REMOTE_DIR}/.deploy-lock"
DEPLOY_LOCK_OWNER_FILE="${DEPLOY_LOCK_DIR}/one-off-owner"
DEPLOY_LOCK_OWNER=""
DEPLOY_LOCK_OWNER_INSTALLED=0
FAILURE_MARKER="${REMOTE_DIR}/.cutover-failed"
RELEASE_STATE_ROOT="${REMOTE_DIR}/.release-state"
GLOBAL_ONE_OFF_LOCK_DIR="${RELEASE_STATE_ROOT}/.release-one-off.lock"
RELEASE_STATE_DIR="${RELEASE_STATE_ROOT}/${RELEASE_NAME}"
RELEASE_ENV_FILE="${RELEASE_STATE_DIR}/env.deploy"
RELEASE_ENV_TMP=""
ROLLBACK_IMAGE_MAP="${RELEASE_STATE_DIR}/rollback-images.tsv"
ROLLBACK_TAG_SUFFIX="${RELEASE_NAME#release-}"
REMOTE_DIR_CANONICAL="$(readlink -f "${REMOTE_DIR}")"
PREVIOUS_RELEASE_DIR=""
PREVIOUS_ENV_FILE=""
PREVIOUS_COMPOSE_FILE=""
PREVIOUS_COMPOSE_PROJECT_NAME=""
PREVIOUS_RUNTIME_NETWORK_SNAPSHOT=""
PREVIOUS_RUNTIME_NETWORK_SUBNET=""
PREVIOUS_RUNTIME_NETWORK_GATEWAY=""
PREVIOUS_RUNTIME_PROXY_IPV4=""
NEW_COMPOSE_FILE=""
NEW_COMPOSE_RELATIVE=""
COMPOSE_PROJECT_NAME_EFFECTIVE="npcink-ai-cloud"
APPLICATION_SERVICES=(caddy proxy)
if [ "${SKIP_FRONTEND_IMAGE}" != "1" ]; then
	# Backend-only releases deliberately preserve the existing frontend
	# container promised by --skip-frontend-image.
	APPLICATION_SERVICES+=(frontend)
fi
APPLICATION_SERVICES+=(api worker callback-worker ops-worker jaeger otel-collector release-one-off)
RECOVERY_REQUIRED_SERVICES=(redis proxy frontend api worker callback-worker ops-worker)
PREVIOUS_WRITER_SERVICES=(api worker callback-worker ops-worker)
CONFIG_DIR_HOST="${REMOTE_DIR}/shared/config"
INSTALL_LOCK_FILE="${CONFIG_DIR_HOST}/.install.lock"
FIRST_INSTALL_PENDING_MARKER="${REMOTE_DIR}/.first-install-pending.json"
INSTALLATION_COMPLETE_MARKER="${REMOTE_DIR}/.installation-complete"
INSTALLATION_STATE=""
FIRST_INSTALL_PENDING=0
FRESH_PG18_INSTALL=0
INSTALL_LOCK_HELD=0
APPLICATIONS_STOPPED=0
MIGRATION_STARTED=0
CUTOVER_MUTATION_STARTED=0
DEPLOY_SUCCEEDED=0
RETAIN_DEPLOY_LOCK=0
ONE_OFF_BUSY_BEFORE_MUTATION=0
ROLLBACK_IMAGE_MAP_SNAPSHOT_OPEN=0
CUTOVER_PHASE="initialize"

if ! mkdir "${DEPLOY_LOCK_DIR}" 2>/dev/null; then
	if [ "${STAGE_ONLY}" = "1" ]; then
		rm -rf "${REMOTE_INCOMING_DIR}" >/dev/null 2>&1 || true
	fi
	echo "[fail] Another deployment is already active: ${DEPLOY_LOCK_DIR}" >&2
	exit 1
fi
if ! chmod 0700 "${DEPLOY_LOCK_DIR}" || \
	[ "$(stat -c '%u' "${DEPLOY_LOCK_DIR}")" != "0" ] || \
	[ "$(stat -c '%a' "${DEPLOY_LOCK_DIR}")" != "700" ]; then
	rmdir "${DEPLOY_LOCK_DIR}" >/dev/null 2>&1 || true
	echo "[fail] Deployment lock must be a root-owned mode-0700 directory: ${DEPLOY_LOCK_DIR}" >&2
	exit 1
fi

remote_run_timed() {
	local label="$1"
	shift
	local started_at
	local completed_at
	local duration_seconds
	local status
	local restore_errexit=0

	case "$-" in
		*e*)
			restore_errexit=1
			;;
	esac

	started_at="$(date +%s)"
	echo "[timing] ${label}: start"
	set +e
	"$@"
	status=$?
	if [ "${restore_errexit}" -eq 1 ]; then
		set -e
	else
		set +e
	fi
	completed_at="$(date +%s)"
	duration_seconds=$((completed_at - started_at))
	if [ "${status}" -eq 0 ]; then
		echo "[timing] ${label}: ${duration_seconds}s"
	else
		echo "[timing] ${label}: ${duration_seconds}s (failed: ${status})" >&2
	fi
	return "${status}"
}

if [ "${STAGE_ONLY}" = "1" ]; then
	STAGE_RELEASE_CREATED=0
	stage_only_failure_cleanup() {
		local exit_status="$?"
		local cleanup_failed=0
		trap - EXIT
		set +e
		if [ "${STAGE_RELEASE_CREATED}" = "1" ]; then
			rm -rf "${RELEASE_DIR}" || cleanup_failed=1
		fi
		rm -rf "${REMOTE_INCOMING_DIR}" || cleanup_failed=1
		rmdir "${DEPLOY_LOCK_DIR}" || cleanup_failed=1
		if [ "${cleanup_failed}" -ne 0 ]; then
			echo "[fail] Stage-only cleanup did not complete." >&2
			if [ "${exit_status}" -eq 0 ]; then
				exit_status=1
			fi
		fi
		exit "${exit_status}"
	}
	trap stage_only_failure_cleanup EXIT

	# Stage-only deliberately exits before resolving current, creating release
	# state, loading images, or touching any running service.
	mkdir "${RELEASE_DIR}"
	STAGE_RELEASE_CREATED=1
	remote_run_timed "remote extract bundle for staging" \
		tar xzf "${REMOTE_BUNDLE_PATH}" -C "${RELEASE_DIR}"
	remote_run_timed "verify staged exact release bundle" \
		bash "${RELEASE_DIR}/deploy/verify-release-bundle.sh" \
			--pre-load "${RELEASE_DIR}" </dev/null
	STAGED_RELEASE="$(readlink -f "${RELEASE_DIR}")"
	if [ -z "${STAGED_RELEASE}" ] || \
		[ "${STAGED_RELEASE}" != "${REMOTE_DIR_CANONICAL}/${RELEASE_NAME}" ]; then
		echo "[fail] Staged release did not resolve to the expected absolute path." >&2
		exit 1
	fi
	if ! rm -rf "${REMOTE_INCOMING_DIR}"; then
		echo "[fail] Stage-only incoming cleanup failed: ${REMOTE_INCOMING_DIR}" >&2
		exit 1
	fi
	if ! rmdir "${DEPLOY_LOCK_DIR}"; then
		echo "[fail] Stage-only deploy lock release failed: ${DEPLOY_LOCK_DIR}" >&2
		exit 1
	fi
	trap - EXIT
	printf 'staged_release=%s\n' "${STAGED_RELEASE}"
	exit 0
fi

atomic_set_current() {
	local target_release="$1"
	local next_link="${CURRENT_LINK}.next.$$"
	rm -f "${next_link}"
	ln -s "${target_release}" "${next_link}"
	mv -Tf "${next_link}" "${CURRENT_LINK}"
}

restore_previous_current_pointer() {
	if [ -n "${PREVIOUS_RELEASE_DIR}" ]; then
		atomic_set_current "${PREVIOUS_RELEASE_DIR}"
	else
		rm -f "${CURRENT_LINK}"
	fi
}

assert_previous_current_pointer() {
	local resolved=""
	if [ -n "${PREVIOUS_RELEASE_DIR}" ]; then
		[ -L "${CURRENT_LINK}" ] || {
			echo "[fail] Current release pointer was not restored as a symlink." >&2
			return 1
		}
		resolved="$(readlink -f "${CURRENT_LINK}")"
		if [ "${resolved}" != "${PREVIOUS_RELEASE_DIR}" ]; then
			echo "[fail] Current release pointer does not reference the previous release." >&2
			return 1
		fi
	elif [ -e "${CURRENT_LINK}" ] || [ -L "${CURRENT_LINK}" ]; then
		echo "[fail] Current release pointer exists even though no previous release was active." >&2
		return 1
	fi
}

resolve_previous_release() {
	local resolved=""
	local resolved_parent=""
	local resolved_name=""
	if [ -L "${CURRENT_LINK}" ]; then
		resolved="$(readlink -f "${CURRENT_LINK}")"
		if [ -z "${resolved}" ] || [ ! -d "${resolved}" ]; then
			echo "[fail] The current release link is broken: ${CURRENT_LINK}" >&2
			return 1
		fi
		resolved_parent="$(dirname "${resolved}")"
		resolved_name="$(basename "${resolved}")"
		if [ "${resolved_parent}" != "${REMOTE_DIR_CANONICAL}" ] || \
			[[ ! "${resolved_name}" =~ ^release-[A-Za-z0-9._-]+$ ]]; then
			echo "[fail] The current release is not a direct managed release child: ${resolved}" >&2
			return 1
		fi
		PREVIOUS_RELEASE_DIR="${resolved}"
	elif [ -e "${CURRENT_LINK}" ]; then
		echo "[fail] The current release path must be a symbolic link: ${CURRENT_LINK}" >&2
		return 1
	fi
}

write_failure_marker() {
	local outcome="$1"
	local marker_tmp="${FAILURE_MARKER}.tmp.$$"
	(
		umask 077
		printf 'phase=%s\noutcome=%s\nfailed_release=%s\nprevious_release=%s\n' \
			"${CUTOVER_PHASE}" "${outcome}" "${RELEASE_DIR}" "${PREVIOUS_RELEASE_DIR}" \
			>"${marker_tmp}"
	)
	mv -f "${marker_tmp}" "${FAILURE_MARKER}"
	chmod 0600 "${FAILURE_MARKER}"
}

restore_release_image_tags() {
	local target_reference=""
	local rollback_reference=""
	local previous_image_id=""
	local restored_image_id=""
	local restore_failed=0

	if [ ! -f "${ROLLBACK_IMAGE_MAP}" ]; then
		return 0
	fi

	while IFS=$'\t' read -r target_reference rollback_reference previous_image_id; do
		[ -n "${target_reference}" ] || continue
		if [ "${rollback_reference}" = "-" ]; then
			if docker image inspect "${target_reference}" >/dev/null 2>&1; then
				if ! docker image rm "${target_reference}" >/dev/null 2>&1; then
					echo "[fail] Could not remove release image tag that was absent before cutover: ${target_reference}" >&2
					restore_failed=1
					continue
				fi
			elif ! docker info >/dev/null 2>&1; then
				echo "[fail] Docker could not prove the prior absence of release image tag: ${target_reference}" >&2
				restore_failed=1
				continue
			fi
			if docker image inspect "${target_reference}" >/dev/null 2>&1; then
				echo "[fail] Release image tag still exists after recovery removal: ${target_reference}" >&2
				restore_failed=1
			elif ! docker info >/dev/null 2>&1; then
				echo "[fail] Docker could not prove release image tag removal: ${target_reference}" >&2
				restore_failed=1
			fi
			continue
		fi
		if ! docker tag "${rollback_reference}" "${target_reference}"; then
			echo "[fail] Could not restore release image tag: ${target_reference}" >&2
			restore_failed=1
			continue
		fi
		if ! restored_image_id="$(docker image inspect --format '{{.Id}}' "${target_reference}")"; then
			echo "[fail] Could not verify restored release image tag: ${target_reference}" >&2
			restore_failed=1
		elif [ "${restored_image_id}" != "${previous_image_id}" ]; then
			echo "[fail] Restored release image tag has the wrong image ID: ${target_reference}" >&2
			restore_failed=1
		fi
	done <"${ROLLBACK_IMAGE_MAP}"

	return "${restore_failed}"
}

discard_rollback_image_tags() {
	local _target_reference=""
	local rollback_reference=""
	local _previous_image_id=""
	local cleanup_failed=0
	local rollback_tag_present=0
	if [ ! -f "${ROLLBACK_IMAGE_MAP}" ]; then
		echo "[fail] Rollback image map is missing during post-commit cleanup: ${ROLLBACK_IMAGE_MAP}" >&2
		return 1
	fi
	while IFS=$'\t' read -r _target_reference rollback_reference _previous_image_id; do
		if [ -n "${rollback_reference}" ] && [ "${rollback_reference}" != "-" ]; then
			rollback_tag_present=0
			if docker image inspect "${rollback_reference}" >/dev/null 2>&1; then
				rollback_tag_present=1
			elif ! docker info >/dev/null 2>&1; then
				echo "[fail] Docker could not prove rollback image tag state before cleanup: ${rollback_reference}" >&2
				cleanup_failed=1
				continue
			fi
			if [ "${rollback_tag_present}" = "1" ]; then
				docker image rm "${rollback_reference}" >/dev/null 2>&1 || true
			fi
			if docker image inspect "${rollback_reference}" >/dev/null 2>&1; then
				echo "[fail] Rollback image tag still exists after cleanup: ${rollback_reference}" >&2
				cleanup_failed=1
			elif ! docker info >/dev/null 2>&1; then
				echo "[fail] Docker could not prove rollback image tag deletion: ${rollback_reference}" >&2
				cleanup_failed=1
			fi
		fi
	done <"${ROLLBACK_IMAGE_MAP}"
	return "${cleanup_failed}"
}

write_first_install_pending_marker() {
	local marker_tmp="${FIRST_INSTALL_PENDING_MARKER}.tmp.$$"
	"${RELEASE_TOOL_PYTHON}" - \
		"${marker_tmp}" "${FIRST_INSTALL_PENDING_MARKER}" "${REMOTE_DIR_CANONICAL}" \
		"${RELEASE_DIR}" "${PREVIOUS_RELEASE_DIR}" "${PREVIOUS_ENV_FILE}" \
		"${PREVIOUS_COMPOSE_FILE}" "${PREVIOUS_COMPOSE_PROJECT_NAME}" \
		"${ROLLBACK_IMAGE_MAP}" <<'PY'
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

(
    temporary_raw,
    marker_raw,
    managed_root_raw,
    release_raw,
    previous_release_raw,
    previous_env_raw,
    previous_compose_raw,
    previous_project,
    rollback_map_raw,
) = sys.argv[1:]
managed_root = Path(managed_root_raw)
marker = Path(marker_raw)
temporary = Path(temporary_raw)

def managed_path(value: str, *, required: bool) -> str:
    if not value:
        if required:
            raise SystemExit("[fail] First-install lifecycle path is missing.")
        return ""
    path = Path(value)
    if not path.is_absolute() or path == managed_root or managed_root not in path.parents:
        raise SystemExit("[fail] First-install lifecycle path escapes the managed root.")
    return str(path)

payload = {
    "contract": "first_install_pending.v1",
    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    "release": managed_path(release_raw, required=True),
    "previous_release": managed_path(previous_release_raw, required=False),
    "previous_env_file": managed_path(previous_env_raw, required=False),
    "previous_compose_file": managed_path(previous_compose_raw, required=False),
    "previous_compose_project": previous_project,
    "rollback_image_map": managed_path(rollback_map_raw, required=True),
}
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
    os.chmod(temporary, 0o600, follow_symlinks=False)
    os.chown(temporary, 0, 0, follow_symlinks=False)
    os.replace(temporary, marker)
    directory_fd = os.open(marker.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
finally:
    try:
        temporary.unlink()
    except FileNotFoundError:
        pass
PY
}

restore_rollback_image_map_snapshot() {
	local restore_tmp="${ROLLBACK_IMAGE_MAP}.restore.$$"
	if [ "${ROLLBACK_IMAGE_MAP_SNAPSHOT_OPEN}" != "1" ] || \
		[ -e "${ROLLBACK_IMAGE_MAP}" ] || [ -L "${ROLLBACK_IMAGE_MAP}" ]; then
		return 0
	fi
	if ! (
		umask 077
		cat <&9 >"${restore_tmp}"
	) || ! chmod 0600 "${restore_tmp}" || \
		! mv -f "${restore_tmp}" "${ROLLBACK_IMAGE_MAP}"; then
		rm -f "${restore_tmp}" >/dev/null 2>&1 || true
		echo "[fail] Rollback image map could not be restored after finalization failure: ${ROLLBACK_IMAGE_MAP}" >&2
		return 1
	fi
}

record_post_commit_cleanup_failure() {
	local message="$1"
	RETAIN_DEPLOY_LOCK=1
	restore_rollback_image_map_snapshot || true
	if ! write_failure_marker "post_commit_cleanup_incomplete"; then
		echo "[fail] Durable post-commit cleanup failure evidence could not be written: ${FAILURE_MARKER}" >&2
	fi
	echo "[fail] ${message}" >&2
}

install_deploy_lock_owner() {
	DEPLOY_LOCK_OWNER="$("${RELEASE_TOOL_PYTHON}" -c 'import secrets; print(secrets.token_hex(32))')" || return 1
	[[ "${DEPLOY_LOCK_OWNER}" =~ ^[0-9a-f]{64}$ ]] || return 1
	if ! (umask 077; set -o noclobber; printf '%s\n' "${DEPLOY_LOCK_OWNER}" >"${DEPLOY_LOCK_OWNER_FILE}") || \
		! chmod 0600 "${DEPLOY_LOCK_OWNER_FILE}" || \
		[ ! -f "${DEPLOY_LOCK_OWNER_FILE}" ] || [ -L "${DEPLOY_LOCK_OWNER_FILE}" ] || \
		[ "$(stat -c '%u' "${DEPLOY_LOCK_OWNER_FILE}")" != "0" ] || \
		[ "$(stat -c '%a' "${DEPLOY_LOCK_OWNER_FILE}")" != "600" ]; then
		RETAIN_DEPLOY_LOCK=1
		return 1
	fi
	export NPCINK_CLOUD_DEPLOY_LOCK_OWNER="${DEPLOY_LOCK_OWNER}"
	DEPLOY_LOCK_OWNER_INSTALLED=1
}

release_deploy_lock_owner() {
	[ "${DEPLOY_LOCK_OWNER_INSTALLED}" = "1" ] || return 0
	if ! rm -f -- "${DEPLOY_LOCK_OWNER_FILE}" || \
		[ -e "${DEPLOY_LOCK_OWNER_FILE}" ] || [ -L "${DEPLOY_LOCK_OWNER_FILE}" ]; then
		return 1
	fi
	unset NPCINK_CLOUD_DEPLOY_LOCK_OWNER
	DEPLOY_LOCK_OWNER=""
	DEPLOY_LOCK_OWNER_INSTALLED=0
}

ensure_private_release_state_directory() {
	local directory="$1"
	if [ ! -e "${directory}" ] && [ ! -L "${directory}" ]; then
		if ! (umask 077; mkdir -- "${directory}"); then
			echo "[fail] Release state directory could not be created safely: ${directory}" >&2
			return 1
		fi
		chmod 0700 "${directory}" || return 1
	fi
	if [ ! -d "${directory}" ] || [ -L "${directory}" ] || \
		[ "$(stat -c '%u' "${directory}" 2>/dev/null || true)" != "0" ] || \
		[ "$(stat -c '%a' "${directory}" 2>/dev/null || true)" != "700" ]; then
		echo "[fail] Release state directory must be root-owned, non-symlink, and mode 0700: ${directory}" >&2
		return 1
	fi
}

application_container_ids() {
	local service_name="$1"
	local docker_status=0
	if [ "${service_name}" = "release-one-off" ]; then
		docker ps -aq \
			--filter "label=com.docker.compose.service=${service_name}" || \
			docker_status=$?
		return "${docker_status}"
	fi
	docker ps -aq \
		--filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
		--filter "label=com.docker.compose.service=${service_name}" || docker_status=$?
	return "${docker_status}"
}

stop_application_services() {
	local service_name=""
	local container_id=""
	# Mark the deployment as stopped before touching the first container. A
	# partial stop must take the same recovery path as a complete stop.
	APPLICATIONS_STOPPED=1
	for service_name in "${APPLICATION_SERVICES[@]}"; do
		while IFS= read -r container_id; do
			[ -n "${container_id}" ] || continue
			docker stop --time 30 "${container_id}"
			docker rm -f "${container_id}"
		done < <(application_container_ids "${service_name}")
	done
}

force_fail_closed() {
	local service_name=""
	local container_id=""
	APPLICATIONS_STOPPED=1
	for service_name in "${APPLICATION_SERVICES[@]}"; do
		while IFS= read -r container_id; do
			[ -n "${container_id}" ] || continue
			docker stop --time 10 "${container_id}" >/dev/null 2>&1 || true
			docker rm -f "${container_id}" >/dev/null 2>&1 || true
		done < <(application_container_ids "${service_name}" 2>/dev/null)
	done
}

assert_application_services_stopped() {
	local service_name=""
	local running_ids=""
	for service_name in "${APPLICATION_SERVICES[@]}"; do
		if ! running_ids="$(docker ps -q \
			--filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
			--filter "label=com.docker.compose.service=${service_name}")"; then
			echo "[fail] Docker could not prove application services are stopped." >&2
			return 1
		fi
		if [ -n "${running_ids}" ]; then
			echo "[fail] Application service is still running during atomic cutover: ${service_name}" >&2
			return 1
		fi
	done
	echo "[ok] Public and write-capable application services are stopped."
}

assert_governed_one_off_absent() {
	local container_ids=""
	if [ -e "${GLOBAL_ONE_OFF_LOCK_DIR}" ] || [ -L "${GLOBAL_ONE_OFF_LOCK_DIR}" ]; then
		echo "[fail] Governed release one-off lock remains present: ${GLOBAL_ONE_OFF_LOCK_DIR}" >&2
		return 1
	fi
	container_ids="$(application_container_ids release-one-off 2>/dev/null)" || {
		echo "[fail] Docker could not prove governed release one-off containers absent." >&2
		return 1
	}
	if [ -n "${container_ids}" ]; then
		echo "[fail] Governed release one-off container remains present." >&2
		return 1
	fi
	echo "[ok] Governed release one-off lock and containers are absent."
}

previous_runtime_network_snapshot() (
	local state_dir=""
	local state_file=""
	local digests=""

	export NPCINK_CLOUD_RELEASE_TOOL_PYTHON="${RELEASE_TOOL_PYTHON}"
	npcink_ai_cloud_prepare_runtime_compose_environment \
		"${PREVIOUS_RELEASE_DIR}" "${PREVIOUS_COMPOSE_FILE}" \
		"${PREVIOUS_COMPOSE_PROJECT_NAME}" || return 1
	if [ -z "${NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET+x}" ]; then
		printf 'legacy\n'
		return 0
	fi
	state_dir="$(npcink_ai_cloud_release_state_dir "${PREVIOUS_RELEASE_DIR}")" || return 1
	state_file="${state_dir}/runtime-network.env"
	digests="$("${RELEASE_TOOL_PYTHON}" - \
		"${state_file}" "${NPCINK_CLOUD_RUNTIME_NGINX_CONFIG_PATH}" <<'PY'
from __future__ import annotations

import hashlib
import os
import sys

digests = []
for path in sys.argv[1:]:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            digests.append(hashlib.sha256(handle.read()).hexdigest())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
print(*digests, sep="\t")
PY
	)" || return 1
	printf 'parameterized\t%s\t%s\t%s\t%s\t%s\n' \
		"${NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET}" \
		"${NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY}" \
		"${NPCINK_CLOUD_RUNTIME_PROXY_IPV4}" \
		"${NPCINK_CLOUD_RUNTIME_NGINX_CONFIG_PATH}" "${digests}"
)

freeze_previous_runtime_network_contract() {
	local kind=""
	local nginx_config_path=""
	local state_sha256=""
	local nginx_sha256=""

	[ -n "${PREVIOUS_RELEASE_DIR}" ] || return 0
	PREVIOUS_RUNTIME_NETWORK_SNAPSHOT="$(previous_runtime_network_snapshot)" || return 1
	if [ "${PREVIOUS_RUNTIME_NETWORK_SNAPSHOT}" = "legacy" ]; then
		echo "[info] Previous release uses the pre-runtime-network Compose contract."
		return 0
	fi
	IFS=$'\t' read -r kind \
		PREVIOUS_RUNTIME_NETWORK_SUBNET PREVIOUS_RUNTIME_NETWORK_GATEWAY \
		PREVIOUS_RUNTIME_PROXY_IPV4 nginx_config_path state_sha256 nginx_sha256 \
		<<<"${PREVIOUS_RUNTIME_NETWORK_SNAPSHOT}"
	if [ "${kind}" != "parameterized" ] || [ -z "${nginx_config_path}" ] || \
		[[ ! "${state_sha256}" =~ ^[0-9a-f]{64}$ ]] || \
		[[ ! "${nginx_sha256}" =~ ^[0-9a-f]{64}$ ]]; then
		echo "[fail] Previous runtime network snapshot is incomplete." >&2
		return 1
	fi
	echo "[ok] Previous runtime network contract is frozen for inspection and rollback: subnet=${PREVIOUS_RUNTIME_NETWORK_SUBNET} gateway=${PREVIOUS_RUNTIME_NETWORK_GATEWAY} proxy=${PREVIOUS_RUNTIME_PROXY_IPV4}"
}

assert_previous_runtime_network_contract_unchanged() {
	local observed=""

	[ -n "${PREVIOUS_RELEASE_DIR}" ] || return 0
	observed="$(previous_runtime_network_snapshot)" || {
		echo "[fail] Previous runtime network contract drifted or became unsafe after it was frozen." >&2
		return 1
	}
	if [ "${observed}" != "${PREVIOUS_RUNTIME_NETWORK_SNAPSHOT}" ]; then
		echo "[fail] Previous runtime network contract drifted after it was frozen for this cutover." >&2
		return 1
	fi
}

compose_previous_release() {
	local clean_env=(env -i "PATH=${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}")
	local passthrough_key=""
	assert_previous_runtime_network_contract_unchanged || return 1
	# The new release env has already been loaded into this shell. Do not let
	# those values outrank --env-file while reconstructing the previous release.
	# Preserve only process/Docker transport settings needed to reach the same
	# daemon; all Compose interpolation comes from PREVIOUS_ENV_FILE.
	for passthrough_key in \
		HOME USER LOGNAME TMPDIR XDG_CONFIG_HOME XDG_RUNTIME_DIR SSH_AUTH_SOCK \
		DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DOCKER_CERT_PATH \
		DOCKER_TLS_VERIFY DOCKER_API_VERSION; do
		if [ -n "${!passthrough_key+x}" ]; then
			clean_env+=("${passthrough_key}=${!passthrough_key}")
		fi
	done

	"${clean_env[@]}" \
		NPCINK_CLOUD_RELEASE_TOOL_PYTHON="${RELEASE_TOOL_PYTHON}" \
		NPCINK_CLOUD_COMPOSE_PROJECT_NAME="${PREVIOUS_COMPOSE_PROJECT_NAME}" \
		NPCINK_CLOUD_COMPOSE_FILE="${PREVIOUS_COMPOSE_FILE}" \
		NPCINK_CLOUD_ENV_FILE="${PREVIOUS_ENV_FILE}" \
		NPCINK_CLOUD_BACKEND_ENV_FILE="${PREVIOUS_ENV_FILE}" \
		bash -ceu '
			common_file="$1"
			previous_root="$2"
			shift 2
			. "${common_file}"
			npcink_ai_cloud_compose "${previous_root}" "$@"
		' bash "${RELEASE_DIR}/deploy/common.sh" "${PREVIOUS_RELEASE_DIR}" "$@"
}

assert_fresh_pg18_install_gate() {
	local state_file="${CONFIG_DIR_HOST}/install-state.json"
	local runtime_file="${CONFIG_DIR_HOST}/runtime-config.json"
	local ca_file="${CONFIG_DIR_HOST}/rds-ca.pem"
	local internal_token_file="${CONFIG_DIR_HOST}/frontend/internal-auth-token"

	if [ -z "${PREVIOUS_RELEASE_DIR}" ]; then
		echo "[fail] An installed deployment requires an existing managed current release." >&2
		return 1
	fi
	"${RELEASE_TOOL_PYTHON}" \
		"${RELEASE_DIR}/deploy/validate-installation-complete.py" \
		--managed-root "${REMOTE_DIR}" \
		--sentinel "${INSTALLATION_COMPLETE_MARKER}" \
		--state "${state_file}" \
		--runtime "${runtime_file}" >/dev/null || {
		echo "[fail] Ordinary deployment requires durable installation-complete acceptance and matching current PostgreSQL 18 runtime state." >&2
		return 1
	}
	"${RELEASE_TOOL_PYTHON}" - \
		"${state_file}" "${runtime_file}" "${ca_file}" "${internal_token_file}" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path

state_path = Path(sys.argv[1])
runtime_path = Path(sys.argv[2])
ca_path = Path(sys.argv[3])
token_path = Path(sys.argv[4])
for path, expected_mode in (
    (state_path, 0o640),
    (runtime_path, 0o600),
    (ca_path, 0o600),
    (token_path, 0o640),
):
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SystemExit(
            f"[fail] Fresh PostgreSQL 18 installation evidence is unavailable: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise SystemExit("[fail] Fresh PostgreSQL 18 installation evidence must be regular files.")
    if stat.S_IMODE(metadata.st_mode) != expected_mode or (metadata.st_uid, metadata.st_gid) != (
        999,
        999,
    ):
        raise SystemExit("[fail] Fresh PostgreSQL 18 installation evidence has unsafe ownership or mode.")

try:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    runtime_bytes = runtime_path.read_bytes()
    runtime = json.loads(runtime_bytes)
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(
        f"[fail] Fresh PostgreSQL 18 installation evidence is invalid: {type(exc).__name__}"
    ) from exc
if not isinstance(state, dict) or not isinstance(runtime, dict):
    raise SystemExit("[fail] Fresh PostgreSQL 18 installation evidence must contain JSON objects.")
if state.get("installation_state") != "complete":
    raise SystemExit("[fail] Fresh PostgreSQL 18 installation is not complete.")
if state.get("database_contract") != "pg18_empty_initialization.v1":
    raise SystemExit("[fail] Fresh PostgreSQL 18 database contract marker is missing.")
digest = state.get("config_digest")
if not isinstance(digest, str) or digest != hashlib.sha256(runtime_bytes).hexdigest():
    raise SystemExit("[fail] Fresh PostgreSQL 18 runtime configuration digest does not match.")
print("[ok] Fresh PostgreSQL 18 installation marker and every protected runtime projection are valid.")
PY
}

previous_release_is_restartable() {
	local services=""
	local images=""
	local service_name=""
	local image_reference=""

	[ -n "${PREVIOUS_RELEASE_DIR}" ] || return 1
	[ -d "${PREVIOUS_RELEASE_DIR}" ] || return 1
	[ -f "${PREVIOUS_ENV_FILE}" ] || return 1
	[ "$(stat -c '%a' "${PREVIOUS_ENV_FILE}")" = "600" ] || return 1
	[ -f "${PREVIOUS_COMPOSE_FILE}" ] || return 1
	if ! assert_previous_runtime_network_contract_unchanged; then
		RETAIN_DEPLOY_LOCK=1
		return 1
	fi

	services="$(compose_previous_release config --services 2>/dev/null)" || return 1
	while IFS= read -r service_name; do
		case "${service_name}" in
			caddy|jaeger|otel-collector)
				echo "[warn] Previous release contains a retired production service: ${service_name}" >&2
				return 1
				;;
		esac
	done <<<"${services}"

	images="$(compose_previous_release config --images 2>/dev/null)" || return 1
	while IFS= read -r image_reference; do
		[ -n "${image_reference}" ] || continue
		docker image inspect "${image_reference}" >/dev/null 2>&1 || return 1
	done <<<"${images}"
	return 0
}

assert_previous_writer_project_alignment() {
	local service_name=""
	local required_services=("${PREVIOUS_WRITER_SERVICES[@]}")
	local container_ids=""
	local container_count=0
	local container_id=""
	local observed_project=""
	local running=""

	if [ -z "${PREVIOUS_RELEASE_DIR}" ]; then
		if [ "${SKIP_FRONTEND_IMAGE}" = "1" ]; then
			echo "[fail] --skip-frontend-image requires an existing managed release with a running frontend to preserve." >&2
			return 1
		fi
		return 0
	fi
	if [ "${SKIP_FRONTEND_IMAGE}" = "1" ]; then
		required_services+=(frontend)
	fi
	for service_name in "${required_services[@]}"; do
		if ! container_ids="$(compose_previous_release ps -q "${service_name}")"; then
			echo "[fail] Could not inspect the previous ${service_name} container before cutover." >&2
			return 1
		fi
		container_count="$(printf '%s\n' "${container_ids}" | awk 'NF { count += 1 } END { print count + 0 }')"
		if [ "${container_count}" -ne 1 ]; then
			echo "[fail] Previous release must have exactly one running ${service_name} container under Compose project ${PREVIOUS_COMPOSE_PROJECT_NAME}; found ${container_count}." >&2
			return 1
		fi
		container_id="${container_ids}"
		if ! observed_project="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "${container_id}")"; then
			echo "[fail] Could not inspect the previous ${service_name} container labels." >&2
			return 1
		fi
		if ! running="$(docker inspect --format '{{.State.Running}}' "${container_id}")"; then
			echo "[fail] Could not inspect the previous ${service_name} container state." >&2
			return 1
		fi
		if [ "${observed_project}" != "${PREVIOUS_COMPOSE_PROJECT_NAME}" ] || [ "${running}" != "true" ]; then
			echo "[fail] Previous ${service_name} container is not a running member of expected Compose project ${PREVIOUS_COMPOSE_PROJECT_NAME}." >&2
			return 1
		fi
	done
	echo "[ok] Previous write-capable containers belong to the expected Compose project."
}

assert_previous_release_services_running() {
	local previous_compose_config="$1"
	local service_name=""
	local container_ids=""
	local container_id=""
	local container_state=""
	local container_count=0
	local expected_reference=""

	for service_name in "${RECOVERY_REQUIRED_SERVICES[@]}"; do
		expected_reference="$(
			npcink_ai_cloud_compose_service_image_reference \
				"${RELEASE_TOOL_PYTHON}" "${service_name}" <<<"${previous_compose_config}"
		)" || {
			echo "[fail] Previous Compose has no unique image reference for recovery service: ${service_name}" >&2
			return 1
		}
		container_ids="$(compose_previous_release ps -q "${service_name}")" || return 1
		container_count="$(printf '%s\n' "${container_ids}" | awk 'NF { count += 1 } END { print count + 0 }')"
		if [ "${container_count}" -ne 1 ]; then
			echo "[fail] Previous release service must have exactly one container after recovery: ${service_name} (found ${container_count})" >&2
			return 1
		fi
		while IFS= read -r container_id; do
			[ -n "${container_id}" ] || continue
			container_state="$(docker inspect --format '{{.State.Running}} {{.State.Restarting}} {{.RestartCount}}' "${container_id}")" || return 1
			if [ "${container_state}" != "true false 0" ]; then
				echo "[fail] Previous release service is not stably running: ${service_name}" >&2
				return 1
			fi
			if ! npcink_ai_cloud_assert_container_matches_rollback_image \
				"${ROLLBACK_IMAGE_MAP}" "${container_id}" "${service_name}" \
				"${expected_reference}"; then
				return 1
			fi
		done <<<"${container_ids}"
	done
}

force_recovery_services_stopped() {
	local service_name=""
	local container_id=""
	local running_ids=""
	local failed=0

	APPLICATIONS_STOPPED=1
	for service_name in "${RECOVERY_REQUIRED_SERVICES[@]}"; do
		while IFS= read -r container_id; do
			[ -n "${container_id}" ] || continue
			docker stop --time 10 "${container_id}" >/dev/null 2>&1 || failed=1
			docker rm -f "${container_id}" >/dev/null 2>&1 || failed=1
		done < <(application_container_ids "${service_name}" 2>/dev/null)
	done
	for service_name in "${RECOVERY_REQUIRED_SERVICES[@]}"; do
		running_ids="$(docker ps -q \
			--filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
			--filter "label=com.docker.compose.service=${service_name}" 2>/dev/null)" || {
			failed=1
			continue
		}
		[ -z "${running_ids}" ] || failed=1
	done
	[ "${failed}" -eq 0 ]
}

restart_previous_release() {
	local previous_compose_config=""
	local service_name=""
	local expected_reference=""
	local recovery_failed=0

	previous_compose_config="$(compose_previous_release config --format json)" || {
		echo "[fail] Previous release Compose config could not be rendered for recovery proof." >&2
		return 1
	}
	for service_name in "${RECOVERY_REQUIRED_SERVICES[@]}"; do
		expected_reference="$(
			npcink_ai_cloud_compose_service_image_reference \
				"${RELEASE_TOOL_PYTHON}" "${service_name}" <<<"${previous_compose_config}"
		)" || recovery_failed=1
		if [ "${recovery_failed}" -eq 0 ] && ! \
			npcink_ai_cloud_expected_rollback_image_id \
				"${ROLLBACK_IMAGE_MAP}" "${expected_reference}" >/dev/null; then
			recovery_failed=1
		fi
		if [ "${recovery_failed}" -ne 0 ]; then
			echo "[fail] Previous release recovery image expectation is invalid: ${service_name}" >&2
			RETAIN_DEPLOY_LOCK=1
			return 1
		fi
	done
	if ! remote_run_timed "restore previous release services" \
		compose_previous_release up -d --pull never --no-build --force-recreate \
			--remove-orphans "${RECOVERY_REQUIRED_SERVICES[@]}"; then
		echo "[fail] Previous release Compose start failed." >&2
		recovery_failed=1
	fi
	if [ "${recovery_failed}" -eq 0 ] && \
		! assert_previous_release_services_running "${previous_compose_config}"; then
		echo "[fail] Previous release containers could not be proven running." >&2
		recovery_failed=1
	fi
	if [ "${recovery_failed}" -eq 0 ] && \
		! npcink_ai_cloud_wait_for_ready "${BASE_URL}" 20 2; then
		echo "[fail] Previous release did not become healthy after recovery." >&2
		recovery_failed=1
	fi
	if [ "${recovery_failed}" -ne 0 ]; then
		force_recovery_services_stopped || true
		RETAIN_DEPLOY_LOCK=1
		return 1
	fi
	atomic_set_current "${PREVIOUS_RELEASE_DIR}"
	assert_previous_current_pointer
	APPLICATIONS_STOPPED=0
	echo "[ok] Previous release restored after pre-migration failure."
}

prove_fail_closed_recovery() {
	local proven_outcome="$1"
	local success_message="$2"
	local recovery_failed=0

	force_fail_closed
	if ! assert_application_services_stopped; then
		recovery_failed=1
	fi
	if ! assert_governed_one_off_absent; then
		recovery_failed=1
	fi
	if ! restore_previous_current_pointer; then
		recovery_failed=1
	elif ! assert_previous_current_pointer; then
		recovery_failed=1
	fi
	if [ "${recovery_failed}" -eq 0 ]; then
		if ! write_failure_marker "${proven_outcome}"; then
			recovery_failed=1
		fi
	fi
	if [ "${recovery_failed}" -ne 0 ]; then
		write_failure_marker "recovery_incomplete" >/dev/null 2>&1 || true
		echo "[fail] Recovery could not prove services stopped, pointer restored, and failure evidence written; deploy lock retained." >&2
		return 1
	fi
	echo "${success_message}" >&2
}

recover_failed_cutover() {
	local image_restore_status=0

	echo "[warn] Recovering failed production cutover at phase: ${CUTOVER_PHASE}" >&2
	if [ "${CUTOVER_MUTATION_STARTED}" != "1" ]; then
		if ! write_failure_marker "validation_failed_before_mutation"; then
			return 1
		fi
		if [ "${ONE_OFF_BUSY_BEFORE_MUTATION}" = "1" ]; then
			echo "[ok] Another governed one-off was already active; this deploy made no mutation and left it untouched." >&2
		else
			echo "[ok] Validation failed before any image/container mutation; running services were untouched." >&2
		fi
		return 0
	fi
	if ! assert_governed_one_off_absent; then
		force_fail_closed
		assert_application_services_stopped >/dev/null 2>&1 || true
		write_failure_marker "recovery_incomplete" >/dev/null 2>&1 || true
		RETAIN_DEPLOY_LOCK=1
		echo "[fail] Governed one-off cleanup is unproved; public/write services remain stopped and the deploy lock is retained." >&2
		return 1
	fi
	restore_release_image_tags || image_restore_status=$?
	if [ "${image_restore_status}" -ne 0 ]; then
		# Tag restoration is part of the pre-migration recovery point. Even when
		# stopped services and the pointer can be proven, leave the lock in place
		# so a later deploy cannot snapshot the wrong image set as its baseline.
		prove_fail_closed_recovery \
			"recovery_incomplete" \
			"[fail] Image-tag recovery is incomplete; public/write services remain stopped and the deploy lock is retained." || true
		return 1
	fi

	if [ "${MIGRATION_STARTED}" = "1" ]; then
		# Database compatibility with the old application is no longer proven.
		# Never manufacture a rollback by starting the old API after this point.
		prove_fail_closed_recovery \
			"fail_closed_after_migration_started" \
			"[fail] Migration had started; public/write services remain stopped for operator recovery."
		return $?
	fi

	if [ "${APPLICATIONS_STOPPED}" = "0" ] && [ -n "${PREVIOUS_RELEASE_DIR}" ]; then
		if ! atomic_set_current "${PREVIOUS_RELEASE_DIR}" || \
			! assert_previous_current_pointer || \
			! write_failure_marker "previous_release_remained_running"; then
			write_failure_marker "recovery_incomplete" >/dev/null 2>&1 || true
			return 1
		fi
		echo "[ok] Previous release remained running; image tags were restored."
		return 0
	fi

	if previous_release_is_restartable; then
		if restart_previous_release; then
			if write_failure_marker "previous_release_restored"; then
				return 0
			fi
			write_failure_marker "recovery_incomplete" >/dev/null 2>&1 || true
			return 1
		fi
	fi

	prove_fail_closed_recovery \
		"fail_closed_without_safe_rollback" \
		"[fail] A safe previous release could not be proven; public/write services remain stopped."
}

on_deploy_exit() {
	local exit_status="$?"
	local recovery_status=0
	trap - EXIT
	set +e
	if [ -n "${RELEASE_ENV_TMP}" ]; then
		if ! rm -f -- "${RELEASE_ENV_TMP}" || \
			[ -e "${RELEASE_ENV_TMP}" ] || [ -L "${RELEASE_ENV_TMP}" ]; then
			exit_status=1
			recovery_status=1
			RETAIN_DEPLOY_LOCK=1
			echo "[fail] Temporary release env cleanup could not be proved; deploy lock retained." >&2
		fi
	fi
	if [ "${exit_status}" -ne 0 ] && [ "${DEPLOY_SUCCEEDED}" != "1" ]; then
		recover_failed_cutover || recovery_status=$?
		if [ "${recovery_status}" -eq 0 ] && [ "${FIRST_INSTALL_PENDING}" = "1" ]; then
			rm -f -- "${FIRST_INSTALL_PENDING_MARKER}" || recovery_status=1
		fi
	fi
	if [ "${CUTOVER_MUTATION_STARTED}" = "1" ] && \
		! assert_governed_one_off_absent; then
		exit_status=1
		recovery_status=1
		RETAIN_DEPLOY_LOCK=1
		restore_rollback_image_map_snapshot || true
		if [ "${DEPLOY_SUCCEEDED}" = "1" ]; then
			write_failure_marker "post_commit_cleanup_incomplete" >/dev/null 2>&1 || true
		else
			write_failure_marker "recovery_incomplete" >/dev/null 2>&1 || true
		fi
		echo "[fail] Governed one-off absence was not proved; deployment lock retained." >&2
	fi
	if [ "${RETAIN_DEPLOY_LOCK}" = "1" ]; then
		exit_status=1
		restore_rollback_image_map_snapshot || true
		echo "[fail] Deployment lock retained for operator recovery: ${DEPLOY_LOCK_DIR}" >&2
	elif [ "${recovery_status}" -eq 0 ]; then
		if ! release_deploy_lock_owner; then
			CUTOVER_PHASE="finalize-deploy-lock-owner-release"
			RETAIN_DEPLOY_LOCK=1
			restore_rollback_image_map_snapshot || true
			write_failure_marker "post_commit_cleanup_incomplete" >/dev/null 2>&1 || true
			echo "[fail] Deployment lock owner cleanup could not be proved; lock retained." >&2
			exit_status=1
		elif ! rmdir "${DEPLOY_LOCK_DIR}" >/dev/null 2>&1 || \
			[ -e "${DEPLOY_LOCK_DIR}" ] || [ -L "${DEPLOY_LOCK_DIR}" ]; then
			CUTOVER_PHASE="finalize-deploy-lock-release"
			RETAIN_DEPLOY_LOCK=1
			echo "[fail] Deployment lock release could not be proved: ${DEPLOY_LOCK_DIR}" >&2
			restore_rollback_image_map_snapshot || true
			if ! write_failure_marker "post_commit_cleanup_incomplete"; then
				echo "[fail] Durable deploy-lock failure evidence could not be written: ${FAILURE_MARKER}" >&2
			fi
			echo "[fail] Deployment lock retained for operator recovery: ${DEPLOY_LOCK_DIR}" >&2
			exit_status=1
		fi
	else
		echo "[fail] Deployment lock retained for operator recovery: ${DEPLOY_LOCK_DIR}" >&2
	fi
	if [ "${ROLLBACK_IMAGE_MAP_SNAPSHOT_OPEN}" = "1" ]; then
		exec 9<&-
		ROLLBACK_IMAGE_MAP_SNAPSHOT_OPEN=0
	fi
	if [ "${INSTALL_LOCK_HELD}" = "1" ]; then
		npcink_ai_cloud_stop_install_lock_broker || exit_status=1
		INSTALL_LOCK_HELD=0
	fi
	if [ "${exit_status}" -eq 0 ] && [ "${DEPLOY_SUCCEEDED}" = "1" ]; then
		echo "[ok] Remote release ready at ${RELEASE_DIR}"
		if [ "${FIRST_INSTALL_PENDING}" = "1" ]; then
			printf 'installation_state=pending\n'
		else
			printf 'installation_state=complete\n'
		fi
	fi
	exit "${exit_status}"
}
trap on_deploy_exit EXIT
install_deploy_lock_owner || {
	echo "[fail] Deployment lock owner proof could not be installed." >&2
	exit 1
}

resolve_previous_release

# Archive integrity, schema, complete payload hashes, and tar paths were checked
# on the remote host before this extraction. The extracted directory is checked
# again by remote-load-and-up before the first docker load.
mkdir -p "${RELEASE_DIR}"
remote_run_timed "remote extract bundle" tar xzf "${REMOTE_BUNDLE_PATH}" -C "${RELEASE_DIR}"

. "${RELEASE_DIR}/deploy/common.sh"

ensure_private_release_state_directory "${RELEASE_STATE_ROOT}"
ensure_private_release_state_directory "${RELEASE_STATE_DIR}"
export NPCINK_CLOUD_CONFIG_DIR_HOST="${CONFIG_DIR_HOST}"

"${RELEASE_TOOL_PYTHON}" - "${CONFIG_DIR_HOST}" <<'PY'
import os
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.mkdir(parents=True, exist_ok=True, mode=0o700)
metadata = path.lstat()
if path.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
    raise SystemExit("[fail] Shared configuration path must be a real directory.")
if os.geteuid() == 0:
    os.chown(path, 999, 999, follow_symlinks=False)
os.chmod(path, 0o700)
PY
npcink_ai_cloud_start_install_lock_broker \
	"${RELEASE_DIR}" "${INSTALL_LOCK_FILE}" 1 \
	env \
		NPCINK_CLOUD_RELEASE_TOOL_PYTHON="${RELEASE_TOOL_PYTHON}" \
		NPCINK_CLOUD_CONFIG_DIR_HOST="${CONFIG_DIR_HOST}" \
		bash "${RELEASE_DIR}/deploy/prepare-installation-under-lock.sh" || {
	echo "[fail] A first-install operation is active; deployment will not race it." >&2
	exit 1
}
INSTALL_LOCK_HELD=1
if [ -e "${FIRST_INSTALL_PENDING_MARKER}" ] || [ -L "${FIRST_INSTALL_PENDING_MARKER}" ]; then
	echo "[fail] A first-install release awaits explicit finalize or rollback; another deployment is forbidden." >&2
	exit 1
fi

INSTALLATION_STATE="$("${RELEASE_TOOL_PYTHON}" - "${CONFIG_DIR_HOST}/install-state.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists():
    print("missing")
    raise SystemExit(0)
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    raise SystemExit("[fail] Shared install-state.json is invalid.")
state = payload.get("installation_state")
if state not in {"pending", "initializing", "complete"}:
    raise SystemExit("[fail] Shared installation state is unsupported.")
print(state)
PY
)"
case "${INSTALLATION_STATE}" in
	missing)
		echo "[fail] Lock-governed first-install preparation did not publish pending state." >&2
		exit 1
		;;
	pending)
		FIRST_INSTALL_PENDING=1
		;;
	initializing)
		echo "[fail] A first-install operation is already initializing; deployment will not race it." >&2
		exit 1
		;;
	complete)
		;;
esac

if [ -n "${PREVIOUS_RELEASE_DIR}" ]; then
	PREVIOUS_ENV_FILE="$(NPCINK_CLOUD_ENV_FILE= npcink_ai_cloud_resolve_env_file "${PREVIOUS_RELEASE_DIR}")"
	if [ -z "${PREVIOUS_ENV_FILE}" ] || [ ! -f "${PREVIOUS_ENV_FILE}" ]; then
		echo "[fail] Previous release env file is missing." >&2
		exit 1
	fi
	PREVIOUS_COMPOSE_PROJECT_NAME="$(npcink_ai_cloud_compose_project_name_from_env "${PREVIOUS_ENV_FILE}")"
fi

NEW_ENV_SOURCE=""
if [ -n "${REMOTE_ENV_PATH}" ] && [ -f "${REMOTE_ENV_PATH}" ]; then
	NEW_ENV_SOURCE="${REMOTE_ENV_PATH}"
elif [ -n "${PREVIOUS_ENV_FILE}" ]; then
	NEW_ENV_SOURCE="${PREVIOUS_ENV_FILE}"
elif [ -f "${REMOTE_DIR}/${REMOTE_ENV_BASENAME}" ]; then
	NEW_ENV_SOURCE="${REMOTE_DIR}/${REMOTE_ENV_BASENAME}"
fi
if [ -z "${NEW_ENV_SOURCE}" ]; then
	echo "[fail] No deployment env source is available for ${RELEASE_NAME}." >&2
	exit 1
fi
if [ ! -f "${NEW_ENV_SOURCE}" ] || [ -L "${NEW_ENV_SOURCE}" ] || \
	[ "$(stat -c '%u' "${NEW_ENV_SOURCE}" 2>/dev/null || true)" != "0" ] || \
	[ "$(stat -c '%a' "${NEW_ENV_SOURCE}" 2>/dev/null || true)" != "600" ]; then
	echo "[fail] Deployment env source must be a root-owned, non-symlink mode-0600 regular file." >&2
	exit 1
fi
"${RELEASE_TOOL_PYTHON}" - "${NEW_ENV_SOURCE}" <<'PY'
import sys
from pathlib import Path

forbidden = {
    "NPCINK_CLOUD_API_WORKERS",
    "NPCINK_CLOUD_DEPLOY_SMOKE_BACKEND_ENV",
    "NPCINK_CLOUD_DEPLOY_SMOKE_FRONTEND_ENV",
    "NPCINK_CLOUD_DEPLOY_SMOKE_SETUP_STATE_OVERRIDE",
}
observed = set()
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in line:
        continue
    key = line.split("=", 1)[0].strip()
    if key in forbidden:
        observed.add(key)
if observed:
    raise SystemExit(
        "[fail] Production .env.deploy explicitly forbids contract overrides: "
        + ",".join(sorted(observed))
    )
PY
if [ -e "${RELEASE_ENV_FILE}" ] || [ -L "${RELEASE_ENV_FILE}" ]; then
	echo "[fail] Fresh per-release env destination already exists: ${RELEASE_ENV_FILE}" >&2
	exit 1
fi
RELEASE_ENV_TMP="${RELEASE_STATE_DIR}/.env.deploy.tmp.$$"
if [ -e "${RELEASE_ENV_TMP}" ] || [ -L "${RELEASE_ENV_TMP}" ] || \
	! (umask 077; set -o noclobber; : >"${RELEASE_ENV_TMP}") 2>/dev/null || \
	! install -m 0600 "${NEW_ENV_SOURCE}" "${RELEASE_ENV_TMP}" || \
	[ ! -f "${RELEASE_ENV_TMP}" ] || [ -L "${RELEASE_ENV_TMP}" ] || \
	[ "$(stat -c '%u' "${RELEASE_ENV_TMP}" 2>/dev/null || true)" != "0" ] || \
	[ "$(stat -c '%a' "${RELEASE_ENV_TMP}" 2>/dev/null || true)" != "600" ]; then
	echo "[fail] Protected per-release env staging failed." >&2
	exit 1
fi
if [ "${FIRST_INSTALL_PENDING}" = "1" ]; then
	"${RELEASE_TOOL_PYTHON}" - "${RELEASE_ENV_TMP}" <<'PY'
from __future__ import annotations

import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
forbidden = {
    "NPCINK_CLOUD_DATABASE_URL",
    "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN",
    "NPCINK_CLOUD_ADMIN_KEY",
    "NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN",
    "NPCINK_CLOUD_ADMIN_SESSION_SECRET",
    "NPCINK_CLOUD_SERVICE_SETTINGS_SECRET",
    "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID",
    "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET",
    "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID",
    "NPCINK_CLOUD_PORTAL_JWT_SECRET",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
}
kept: list[str] = []
for line in path.read_text(encoding="utf-8").splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        kept.append(line)
        continue
    key = line.split("=", 1)[0].strip()
    if key not in forbidden:
        kept.append(line)

temporary = path.with_name(f".{path.name}.sanitized.{os.getpid()}")
descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write("\n".join(kept).rstrip("\n") + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
finally:
    try:
        temporary.unlink()
    except FileNotFoundError:
        pass
PY
fi
"${RELEASE_TOOL_PYTHON}" - "${RELEASE_ENV_TMP}" "${RELEASE_STATE_DIR}" <<'PY'
import os
import sys

for path in sys.argv[1:]:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
PY
# Both BSD and GNU mv support -n, while GNU-only -T is unavailable on the
# macOS contract runner. The destination was proved absent while the global
# deploy lock was held; retaining the source after mv is the no-clobber signal.
if ! mv -n "${RELEASE_ENV_TMP}" "${RELEASE_ENV_FILE}" || \
	[ -e "${RELEASE_ENV_TMP}" ] || [ -L "${RELEASE_ENV_TMP}" ] || \
	[ ! -f "${RELEASE_ENV_FILE}" ] || [ -L "${RELEASE_ENV_FILE}" ] || \
	[ "$(stat -c '%u' "${RELEASE_ENV_FILE}" 2>/dev/null || true)" != "0" ] || \
	[ "$(stat -c '%a' "${RELEASE_ENV_FILE}" 2>/dev/null || true)" != "600" ]; then
	echo "[fail] Per-release env publication was not atomic and private." >&2
	exit 1
fi
RELEASE_ENV_TMP=""
"${RELEASE_TOOL_PYTHON}" - "${RELEASE_STATE_DIR}" <<'PY'
import os
import sys

descriptor = os.open(sys.argv[1], os.O_RDONLY)
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY
export NPCINK_CLOUD_ENV_FILE="${RELEASE_ENV_FILE}"
export NPCINK_CLOUD_BACKEND_ENV_FILE="${RELEASE_ENV_FILE}"
COMPOSE_PROJECT_NAME_EFFECTIVE="$(npcink_ai_cloud_compose_project_name_from_env "${RELEASE_ENV_FILE}")"
if [ -n "${PREVIOUS_RELEASE_DIR}" ] && \
	[ "${PREVIOUS_COMPOSE_PROJECT_NAME}" != "${COMPOSE_PROJECT_NAME_EFFECTIVE}" ]; then
	echo "[fail] Compose project rename is not supported during ordinary deployment: ${PREVIOUS_COMPOSE_PROJECT_NAME} -> ${COMPOSE_PROJECT_NAME_EFFECTIVE}." >&2
	exit 1
fi
export NPCINK_CLOUD_COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME_EFFECTIVE}"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME_EFFECTIVE}"

export NPCINK_CLOUD_SKIP_FRONTEND_IMAGE="${SKIP_FRONTEND_IMAGE}"
if [ -n "${REMOTE_COMPOSE_FILE}" ]; then
	export NPCINK_CLOUD_COMPOSE_FILE="${RELEASE_DIR}/${REMOTE_COMPOSE_FILE}"
	if [ ! -f "${NPCINK_CLOUD_COMPOSE_FILE}" ]; then
		echo "[fail] Remote compose file not found: ${NPCINK_CLOUD_COMPOSE_FILE}" >&2
		exit 1
	fi
	echo "[info] Remote compose file: ${NPCINK_CLOUD_COMPOSE_FILE}"
fi

npcink_ai_cloud_load_env_file "${RELEASE_DIR}"
npcink_ai_cloud_require_cmd docker
npcink_ai_cloud_require_cmd curl
npcink_ai_cloud_require_host_release_tool_python "${RELEASE_TOOL_PYTHON}"

NEW_COMPOSE_FILE="${NPCINK_CLOUD_COMPOSE_FILE:-${RELEASE_DIR}/docker-compose.prod.yml}"
if [[ "${NEW_COMPOSE_FILE}" != /* ]]; then
	NEW_COMPOSE_FILE="${RELEASE_DIR}/${NEW_COMPOSE_FILE#./}"
fi
if [ ! -f "${NEW_COMPOSE_FILE}" ]; then
	echo "[fail] New release Compose file not found: ${NEW_COMPOSE_FILE}" >&2
	exit 1
fi
NEW_COMPOSE_FILE="$(readlink -f "${NEW_COMPOSE_FILE}")"
case "${NEW_COMPOSE_FILE}" in
	"${RELEASE_DIR}"/*)
		NEW_COMPOSE_RELATIVE="${NEW_COMPOSE_FILE#"${RELEASE_DIR}"/}"
		;;
	*)
		echo "[fail] New release Compose file must come from the exact release bundle." >&2
		exit 1
		;;
esac
export NPCINK_CLOUD_COMPOSE_FILE="${NEW_COMPOSE_FILE}"
if [ -n "${PREVIOUS_RELEASE_DIR}" ]; then
	PREVIOUS_COMPOSE_FILE="${PREVIOUS_RELEASE_DIR}/${NEW_COMPOSE_RELATIVE}"
fi
freeze_previous_runtime_network_contract
assert_previous_writer_project_alignment
if [ "${FIRST_INSTALL_PENDING}" = "1" ]; then
	echo "[ok] First-install deployment defers empty PostgreSQL 18 initialization to setup."
else
	FRESH_PG18_INSTALL=1
	assert_fresh_pg18_install_gate
fi

CUTOVER_PHASE="prove-governed-one-off-absence-before-mutation"
if ! remote_run_timed "assert governed one-off absent before mutation" \
	assert_governed_one_off_absent; then
	ONE_OFF_BUSY_BEFORE_MUTATION=1
	exit 1
fi

cd "${RELEASE_DIR}"
CUTOVER_PHASE="prepare-release-images"
CUTOVER_MUTATION_STARTED=1
remote_run_timed "remote load and up" \
	env \
	NPCINK_CLOUD_LOAD_MODE=prepare-only \
	NPCINK_CLOUD_ROLLBACK_IMAGE_MAP="${ROLLBACK_IMAGE_MAP}" \
	NPCINK_CLOUD_ROLLBACK_TAG_SUFFIX="${ROLLBACK_TAG_SUFFIX}" \
	bash deploy/remote-load-and-up.sh </dev/null

if [ "${FIRST_INSTALL_PENDING}" = "1" ]; then
	CUTOVER_PHASE="publish-first-install-recovery-contract"
	write_first_install_pending_marker
fi

if [ "${FRESH_PG18_INSTALL}" = "1" ]; then
	CUTOVER_PHASE="candidate-runtime-config-and-pg18-preflight"
	remote_run_timed "candidate runtime config, PostgreSQL 18, and Alembic-current preflight" \
		bash deploy/remote-runtime-config-preflight.sh </dev/null
fi

CUTOVER_PHASE="stop-old-application-services"
remote_run_timed "stop public and write-capable application services" stop_application_services
remote_run_timed "assert application services stopped" assert_application_services_stopped

CUTOVER_PHASE="start-data-services"
remote_run_timed "remote start data services only" \
	env NPCINK_CLOUD_LOAD_MODE=data-only \
	bash deploy/remote-load-and-up.sh </dev/null

if [ "${FIRST_INSTALL_PENDING}" = "1" ]; then
	CUTOVER_PHASE="defer-empty-pg18-migration-to-setup"
	echo "[ok] Empty PostgreSQL 18 migration is deferred to the authenticated setup installer."
else
	CUTOVER_PHASE="migrate-with-staged-image"
	# From this assignment forward the old application is never auto-started: a
	# failed/partial migration may have made the database incompatible with it.
	MIGRATION_STARTED=1
	remote_run_timed "remote migrate" \
		bash deploy/remote-migrate.sh </dev/null
fi

if [ "${FIRST_INSTALL_PENDING}" != "1" ] && [ "${REFRESH_PROVIDERS}" = "1" ]; then
	CUTOVER_PHASE="refresh-provider-projections-with-staged-image"
	remote_run_timed "remote refresh providers" \
		bash deploy/remote-refresh-providers.sh </dev/null
fi

CUTOVER_PHASE="activate-new-release-pointer"
atomic_set_current "${RELEASE_DIR}"

CUTOVER_PHASE="start-new-api"
remote_run_timed "remote start new API only" \
	env NPCINK_CLOUD_LOAD_MODE=api-only \
	bash deploy/remote-load-and-up.sh </dev/null

CUTOVER_PHASE="start-new-workers"
WORKER_CUTOFF="$("${RELEASE_TOOL_PYTHON}" - <<'PY'
from datetime import datetime, timezone

print(datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"))
PY
)"
remote_run_timed "remote start new workers after API readiness" \
	env NPCINK_CLOUD_LOAD_MODE=workers-only \
	bash deploy/remote-load-and-up.sh </dev/null

if [ "${FIRST_INSTALL_PENDING}" = "1" ]; then
	CUTOVER_PHASE="workers-wait-for-first-install"
	echo "[ok] Worker containers are running the bounded install-state wait wrapper."
else
	CUTOVER_PHASE="verify-worker-operational-readiness"
	remote_run_timed "remote internal operational readiness before traffic" \
		env NPCINK_CLOUD_OPERATIONAL_READY_INTERNAL=1 \
		bash deploy/remote-operational-ready.sh \
			--base-url "${BASE_URL}" \
			--worker-cutoff "${WORKER_CUTOFF}" </dev/null
fi

CUTOVER_PHASE="restore-frontend-and-proxy-traffic"
remote_run_timed "remote restore frontend and proxy traffic last" \
	env \
	NPCINK_CLOUD_LOAD_MODE=traffic-only \
	NPCINK_CLOUD_PRESERVE_FIRST_INSTALL_POSTGRES="${FIRST_INSTALL_PENDING}" \
	bash deploy/remote-load-and-up.sh </dev/null

if [ "${FIRST_INSTALL_PENDING}" = "1" ]; then
	CUTOVER_PHASE="publish-first-install-entry"
	echo "[ok] Setup-capable Cloud is live at ${BASE_URL%/}/setup"
	echo "[info] Issue the setup code from an interactive SSH TTY with deploy/setup-code-rotate.sh, then complete PostgreSQL 18 installation in the browser."
else
	CUTOVER_PHASE="validate-new-application-version"
	remote_run_timed "remote baseline status" bash deploy/remote-baseline-status.sh </dev/null
fi

if [ "${FIRST_INSTALL_PENDING}" != "1" ] && [ "${SKIP_SEED}" != "1" ]; then
	NPCINK_CLOUD_SECRET="${SECRET}" \
	remote_run_timed "remote seed runtime" bash deploy/remote-seed-runtime.sh \
		--site-id "${SITE_ID}" \
		--key-id "${KEY_ID}" \
		--scopes "${SCOPES}" \
		</dev/null
fi

if [ "${FIRST_INSTALL_PENDING}" != "1" ] && [ "${SKIP_SMOKE}" != "1" ]; then
	SMOKE_ARGS=(
		--base-url "${BASE_URL}"
		--site-id "${SITE_ID}"
		--key-id "${KEY_ID}"
		--profile-id "${PROFILE_ID}"
		--ability-name "${ABILITY_NAME}"
		--execution-kind "${EXECUTION_KIND}"
		--prompt-text "${PROMPT_TEXT}"
	)
	if [ -n "${IDEMPOTENCY_SUFFIX}" ]; then
		SMOKE_ARGS+=(--idempotency-suffix "${IDEMPOTENCY_SUFFIX}")
	fi
	if [ -n "${EXPECTED_PROVIDER_ID}" ]; then
		SMOKE_ARGS+=(--expected-provider-id "${EXPECTED_PROVIDER_ID}")
	fi
	if [ -n "${EXPECTED_MODEL_ID}" ]; then
		SMOKE_ARGS+=(--expected-model-id "${EXPECTED_MODEL_ID}")
	fi
	if [ -n "${EXPECTED_INSTANCE_ID}" ]; then
		SMOKE_ARGS+=(--expected-instance-id "${EXPECTED_INSTANCE_ID}")
	fi
	NPCINK_CLOUD_SECRET="${SECRET}" \
	remote_run_timed "remote smoke" bash deploy/remote-smoke.sh "${SMOKE_ARGS[@]}" </dev/null
fi

if [ "${FIRST_INSTALL_PENDING}" != "1" ] && [ "${WITH_PORTAL_SMOKE}" = "1" ]; then
	if [ -z "${MEMBER_EMAIL}" ]; then
		echo "[fail] --with-portal-smoke requires --member-email or NPCINK_CLOUD_MEMBER_EMAIL" >&2
		exit 1
	fi
	remote_run_timed "remote bootstrap portal site" bash deploy/remote-bootstrap-portal-site.sh \
		--base-url "${BASE_URL}" \
		--site-id "${SITE_ID}" \
		--member-email "${MEMBER_EMAIL}" \
		</dev/null
	remote_run_timed "remote portal smoke" bash deploy/remote-portal-smoke.sh \
		--base-url "${BASE_URL}" \
		--site-id "${SITE_ID}" \
		--member-email "${MEMBER_EMAIL}" \
		</dev/null
fi

if [ "${FIRST_INSTALL_PENDING}" != "1" ] && [ "${WITH_OPERATIONAL_READY}" = "1" ]; then
	echo "[info] Running remote operational readiness gate"
	OPERATIONAL_READY_TOKEN="$(npcink_ai_cloud_read_internal_token_projection "${RELEASE_DIR}")"
	NPCINK_CLOUD_INTERNAL_AUTH_TOKEN="${OPERATIONAL_READY_TOKEN}" \
		remote_run_timed "remote operational readiness" \
		bash deploy/remote-operational-ready.sh --base-url "${BASE_URL}" </dev/null
	unset OPERATIONAL_READY_TOKEN
	echo "[ok] Remote operational readiness gate passed"
fi

CUTOVER_PHASE="finalize-incoming-cleanup"
DEPLOY_SUCCEEDED=1
if ! rm -rf -- "${REMOTE_INCOMING_DIR}" || \
	[ -e "${REMOTE_INCOMING_DIR}" ] || [ -L "${REMOTE_INCOMING_DIR}" ]; then
	record_post_commit_cleanup_failure \
		"Release activated, but protected incoming cleanup could not be proved: ${REMOTE_INCOMING_DIR}"
	exit 1
fi
CUTOVER_PHASE="finalize-rollback-image-tags"
if [ "${FIRST_INSTALL_PENDING}" != "1" ]; then
	if ! discard_rollback_image_tags; then
		record_post_commit_cleanup_failure \
			"Release activated, but rollback image tag cleanup could not be proved."
		exit 1
	fi
else
	echo "[ok] First-install rollback image tags remain pinned until explicit post-install finalize."
fi
CUTOVER_PHASE="finalize-failure-evidence"
if ! rm -f "${FAILURE_MARKER}" || \
	[ -e "${FAILURE_MARKER}" ] || [ -L "${FAILURE_MARKER}" ]; then
	record_post_commit_cleanup_failure \
		"Release activated, but stale failure evidence cleanup could not be proved: ${FAILURE_MARKER}"
	exit 1
fi
CUTOVER_PHASE="finalize-rollback-image-map"
if [ "${FIRST_INSTALL_PENDING}" != "1" ]; then
	if ! exec 9<"${ROLLBACK_IMAGE_MAP}"; then
		record_post_commit_cleanup_failure \
			"Release activated, but rollback image map snapshot could not be opened: ${ROLLBACK_IMAGE_MAP}"
		exit 1
	fi
	ROLLBACK_IMAGE_MAP_SNAPSHOT_OPEN=1
	if ! rm -f "${ROLLBACK_IMAGE_MAP}" || \
		[ -e "${ROLLBACK_IMAGE_MAP}" ] || [ -L "${ROLLBACK_IMAGE_MAP}" ]; then
		record_post_commit_cleanup_failure \
			"Release activated, but rollback image map cleanup could not be proved: ${ROLLBACK_IMAGE_MAP}"
		exit 1
	fi
else
	echo "[ok] First-install rollback map remains protected until explicit post-install finalize."
fi
CUTOVER_PHASE="finalize-current-release"
EOF

REMOTE_INCOMING_NEEDS_CLEANUP=0
trap - EXIT
if [ "${STAGE_ONLY}" = "1" ]; then
	echo "[ok] Remote release staged on ${SSH_TARGET}"
else
	echo "[ok] Remote deploy completed: ${SSH_TARGET}:${REMOTE_DIR}/current"
fi
