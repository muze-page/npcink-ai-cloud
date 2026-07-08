#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "${ROOT_DIR}/deploy/common.sh"

npcink_ai_cloud_require_cmd bash
npcink_ai_cloud_require_cmd ssh
npcink_ai_cloud_require_cmd scp
npcink_ai_cloud_require_cmd tar

SSH_HOST="${NPCINK_CLOUD_DEPLOY_SSH_HOST:-}"
SSH_USER="${NPCINK_CLOUD_DEPLOY_SSH_USER:-}"
SSH_PORT="${NPCINK_CLOUD_DEPLOY_SSH_PORT:-22}"
SSH_IDENTITY_FILE="${NPCINK_CLOUD_DEPLOY_IDENTITY_FILE:-}"
SSH_CONNECT_TIMEOUT_SECONDS="${NPCINK_CLOUD_DEPLOY_SSH_CONNECT_TIMEOUT_SECONDS:-10}"
REMOTE_DIR="${NPCINK_CLOUD_DEPLOY_REMOTE_DIR:-/opt/npcink-ai-cloud}"
BUNDLE_PATH="${NPCINK_CLOUD_DEPLOY_BUNDLE_PATH:-${ROOT_DIR}/dist/deploy-bundle.tgz}"
ENV_FILE="${NPCINK_CLOUD_ENV_FILE:-}"
IMAGE_PLATFORM="${NPCINK_CLOUD_IMAGE_PLATFORM:-}"
BASE_URL="${NPCINK_CLOUD_BASE_URL:-http://127.0.0.1:${NPCINK_CLOUD_PORT:-8010}}"
REMOTE_COMPOSE_FILE="${NPCINK_CLOUD_REMOTE_COMPOSE_FILE:-}"
SITE_ID="${NPCINK_CLOUD_SITE_ID:-site_smoke}"
KEY_ID="${NPCINK_CLOUD_KEY_ID:-key_default}"
SECRET="${NPCINK_CLOUD_SECRET:-npcink-cloud-test-secret}"
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
SKIP_SEED=0
SKIP_SMOKE=0
WITH_PORTAL_SMOKE=0
REFRESH_PROVIDERS="${NPCINK_CLOUD_REFRESH_PROVIDERS:-0}"
WITH_OPERATIONAL_READY="${NPCINK_CLOUD_WITH_OPERATIONAL_READY:-0}"
SKIP_FRONTEND_IMAGE="${NPCINK_CLOUD_SKIP_FRONTEND_IMAGE:-0}"

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
		--remote-dir)
			REMOTE_DIR="$2"
			shift 2
			;;
		--bundle-path)
			BUNDLE_PATH="$2"
			shift 2
			;;
		--env-file)
			ENV_FILE="$2"
			shift 2
			;;
		--image-platform)
			IMAGE_PLATFORM="$2"
			shift 2
			;;
		--base-url)
			BASE_URL="$2"
			shift 2
			;;
		--remote-compose-file)
			REMOTE_COMPOSE_FILE="$2"
			shift 2
			;;
		--site-id)
			SITE_ID="$2"
			shift 2
			;;
		--key-id)
			KEY_ID="$2"
			shift 2
			;;
		--secret)
			SECRET="$2"
			shift 2
			;;
		--scopes)
			SCOPES="$2"
			shift 2
			;;
		--profile-id)
			PROFILE_ID="$2"
			shift 2
			;;
		--ability-name)
			ABILITY_NAME="$2"
			shift 2
			;;
		--execution-kind)
			EXECUTION_KIND="$2"
			shift 2
			;;
		--idempotency-suffix)
			IDEMPOTENCY_SUFFIX="$2"
			shift 2
			;;
		--prompt-text)
			PROMPT_TEXT="$2"
			shift 2
			;;
		--expected-provider-id)
			EXPECTED_PROVIDER_ID="$2"
			shift 2
			;;
		--expected-model-id)
			EXPECTED_MODEL_ID="$2"
			shift 2
			;;
		--expected-instance-id)
			EXPECTED_INSTANCE_ID="$2"
			shift 2
			;;
		--member-email)
			MEMBER_EMAIL="$2"
			shift 2
			;;
		--skip-bundle-build)
			SKIP_BUNDLE_BUILD=1
			shift
			;;
		--skip-seed)
			SKIP_SEED=1
			shift
			;;
		--skip-smoke)
			SKIP_SMOKE=1
			shift
			;;
		--with-portal-smoke)
			WITH_PORTAL_SMOKE=1
			shift
			;;
		--refresh-providers)
			REFRESH_PROVIDERS=1
			shift
			;;
		--with-operational-ready)
			WITH_OPERATIONAL_READY=1
			shift
			;;
		--skip-frontend-image)
			SKIP_FRONTEND_IMAGE=1
			shift
			;;
		*)
			echo "[fail] Unknown argument: $1" >&2
			exit 1
			;;
	esac
done

if [ -z "${SSH_HOST}" ]; then
	echo "[fail] Missing --ssh-host or NPCINK_CLOUD_DEPLOY_SSH_HOST" >&2
	exit 1
fi

if [ -n "${SSH_IDENTITY_FILE}" ] && [ ! -f "${SSH_IDENTITY_FILE}" ]; then
	echo "[fail] SSH identity file not found: ${SSH_IDENTITY_FILE}" >&2
	exit 1
fi

if [ -n "${ENV_FILE}" ] && [ ! -f "${ENV_FILE}" ]; then
	echo "[fail] Env file not found: ${ENV_FILE}" >&2
	exit 1
fi

if [ -n "${REMOTE_COMPOSE_FILE}" ]; then
	echo "[info] Requested remote compose file: ${REMOTE_COMPOSE_FILE}"
fi

SSH_TARGET="${SSH_HOST}"
if [ -n "${SSH_USER}" ]; then
	SSH_TARGET="${SSH_USER}@${SSH_HOST}"
fi

SSH_ARGS=(
	-p "${SSH_PORT}"
	-o StrictHostKeyChecking=accept-new
	-o BatchMode=yes
	-o ConnectTimeout="${SSH_CONNECT_TIMEOUT_SECONDS}"
)
SCP_ARGS=(
	-P "${SSH_PORT}"
	-o StrictHostKeyChecking=accept-new
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

if [ -z "${IMAGE_PLATFORM}" ]; then
	if ! ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "true" >/dev/null 2>&1; then
		echo "[fail] SSH target is not reachable: ${SSH_TARGET}:${SSH_PORT}" >&2
		echo "[fail] Check NPCINK_CLOUD_DEPLOY_IDENTITY_FILE, firewall/security group, and sshd." >&2
		exit 1
	fi
	REMOTE_ARCH="$(ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "uname -m")"
	IMAGE_PLATFORM="$(resolve_remote_platform "${REMOTE_ARCH}")"
	if [ -z "${IMAGE_PLATFORM}" ]; then
		echo "[fail] Unsupported remote architecture: ${REMOTE_ARCH}" >&2
		exit 1
	fi
	echo "[info] Remote architecture ${REMOTE_ARCH}; selected image platform ${IMAGE_PLATFORM}"
fi

if [ "${SKIP_BUNDLE_BUILD}" -eq 0 ]; then
	echo "[info] Building deploy bundle"
	NPCINK_CLOUD_IMAGE_PLATFORM="${IMAGE_PLATFORM}" \
	NPCINK_CLOUD_SKIP_FRONTEND_IMAGE="${SKIP_FRONTEND_IMAGE}" \
		bash "${ROOT_DIR}/deploy/bundle-images.sh"
fi

if [ ! -f "${BUNDLE_PATH}" ]; then
	echo "[fail] Deploy bundle not found: ${BUNDLE_PATH}" >&2
	exit 1
fi

RELEASE_NAME="release-$(date -u +%Y%m%d%H%M%S)"
REMOTE_BUNDLE_PATH="${REMOTE_DIR}/deploy-bundle.tgz"
REMOTE_ENV_BASENAME=".env.deploy"
REMOTE_ENV_PATH=""

echo "[info] Preparing remote directory ${SSH_TARGET}:${REMOTE_DIR}"
ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "mkdir -p '${REMOTE_DIR}'"

echo "[info] Uploading deploy bundle"
scp "${SCP_ARGS[@]}" "${BUNDLE_PATH}" "${SSH_TARGET}:${REMOTE_BUNDLE_PATH}"

if [ -n "${ENV_FILE}" ]; then
	REMOTE_ENV_PATH="${REMOTE_DIR}/${REMOTE_ENV_BASENAME}"
	echo "[info] Uploading env file"
	scp "${SCP_ARGS[@]}" "${ENV_FILE}" "${SSH_TARGET}:${REMOTE_ENV_PATH}"
fi

if [ "${WITH_OPERATIONAL_READY}" = "1" ]; then
	echo "[info] Operational readiness gate: enabled"
else
	echo "[info] Operational readiness gate: disabled"
fi

echo "[info] Running remote deploy sequence on ${SSH_TARGET}"
ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" bash -s -- \
	"$(remote_shell_arg "${REMOTE_DIR}")" \
	"$(remote_shell_arg "${RELEASE_NAME}")" \
	"$(remote_shell_arg "${REMOTE_ENV_BASENAME}")" \
	"$(remote_shell_arg "${SITE_ID}")" \
	"$(remote_shell_arg "${KEY_ID}")" \
	"$(remote_shell_arg "${SECRET}")" \
	"$(remote_shell_arg "${SCOPES}")" \
	"$(remote_shell_arg "${BASE_URL}")" \
	"$(remote_shell_arg "${PROFILE_ID}")" \
	"$(remote_shell_arg "${ABILITY_NAME}")" \
	"$(remote_shell_arg "${EXECUTION_KIND}")" \
	"$(remote_shell_arg "${IDEMPOTENCY_SUFFIX}")" \
	"$(remote_shell_arg "${PROMPT_TEXT}")" \
	"$(remote_shell_arg "${EXPECTED_PROVIDER_ID}")" \
	"$(remote_shell_arg "${EXPECTED_MODEL_ID}")" \
	"$(remote_shell_arg "${EXPECTED_INSTANCE_ID}")" \
	"$(remote_shell_arg "${MEMBER_EMAIL}")" \
	"$(remote_shell_arg "${SKIP_SEED}")" \
	"$(remote_shell_arg "${SKIP_SMOKE}")" \
	"$(remote_shell_arg "${REMOTE_ENV_PATH}")" \
	"$(remote_shell_arg "${WITH_PORTAL_SMOKE}")" \
	"$(remote_shell_arg "${SKIP_FRONTEND_IMAGE}")" \
	"$(remote_shell_arg "${REMOTE_COMPOSE_FILE}")" \
	"$(remote_shell_arg "${REFRESH_PROVIDERS}")" \
	"$(remote_shell_arg "${WITH_OPERATIONAL_READY}")" <<'EOF'
set -euo pipefail

REMOTE_DIR="$1"
RELEASE_NAME="$2"
REMOTE_ENV_BASENAME="$3"
SITE_ID="$4"
KEY_ID="$5"
SECRET="$6"
SCOPES="$7"
BASE_URL="$8"
PROFILE_ID="${9:-text.balanced}"
ABILITY_NAME="${10:-npcink-abilities-toolkit/build-article-block-plan}"
EXECUTION_KIND="${11:-text}"
IDEMPOTENCY_SUFFIX="${12:-}"
PROMPT_TEXT="${13:-remote deploy smoke request}"
EXPECTED_PROVIDER_ID="${14:-}"
EXPECTED_MODEL_ID="${15:-}"
EXPECTED_INSTANCE_ID="${16:-}"
MEMBER_EMAIL="${17:-}"
SKIP_SEED="${18:-0}"
SKIP_SMOKE="${19:-0}"
REMOTE_ENV_PATH="${20:-}"
WITH_PORTAL_SMOKE="${21:-0}"
SKIP_FRONTEND_IMAGE="${22:-0}"
REMOTE_COMPOSE_FILE="${23:-}"
REFRESH_PROVIDERS="${24:-0}"
WITH_OPERATIONAL_READY="${25:-0}"

RELEASE_DIR="${REMOTE_DIR}/${RELEASE_NAME}"
CURRENT_LINK="${REMOTE_DIR}/current"

mkdir -p "${RELEASE_DIR}"
tar xzf "${REMOTE_DIR}/deploy-bundle.tgz" -C "${RELEASE_DIR}"

if [ -n "${REMOTE_ENV_PATH}" ] && [ -f "${REMOTE_ENV_PATH}" ]; then
	cp "${REMOTE_ENV_PATH}" "${RELEASE_DIR}/${REMOTE_ENV_BASENAME}"
	export NPCINK_CLOUD_ENV_FILE="${RELEASE_DIR}/${REMOTE_ENV_BASENAME}"
elif [ -f "${CURRENT_LINK}/${REMOTE_ENV_BASENAME}" ]; then
	cp "${CURRENT_LINK}/${REMOTE_ENV_BASENAME}" "${RELEASE_DIR}/${REMOTE_ENV_BASENAME}"
	export NPCINK_CLOUD_ENV_FILE="${RELEASE_DIR}/${REMOTE_ENV_BASENAME}"
fi

export NPCINK_CLOUD_SKIP_FRONTEND_IMAGE="${SKIP_FRONTEND_IMAGE}"
if [ -n "${REMOTE_COMPOSE_FILE}" ]; then
	export NPCINK_CLOUD_COMPOSE_FILE="${RELEASE_DIR}/${REMOTE_COMPOSE_FILE}"
	if [ ! -f "${NPCINK_CLOUD_COMPOSE_FILE}" ]; then
		echo "[fail] Remote compose file not found: ${NPCINK_CLOUD_COMPOSE_FILE}" >&2
		exit 1
	fi
	echo "[info] Remote compose file: ${NPCINK_CLOUD_COMPOSE_FILE}"
fi

ln -sfn "${RELEASE_DIR}" "${CURRENT_LINK}"

cd "${RELEASE_DIR}"
bash deploy/remote-load-and-up.sh
bash deploy/remote-migrate.sh
bash deploy/remote-baseline-status.sh

if [ "${REFRESH_PROVIDERS}" = "1" ]; then
	bash deploy/remote-refresh-providers.sh
fi

if [ "${SKIP_SEED}" != "1" ]; then
	bash deploy/remote-seed-runtime.sh \
		--site-id "${SITE_ID}" \
		--key-id "${KEY_ID}" \
		--secret "${SECRET}" \
		--scopes "${SCOPES}"
fi

if [ "${SKIP_SMOKE}" != "1" ]; then
	SMOKE_ARGS=(
		--base-url "${BASE_URL}"
		--site-id "${SITE_ID}"
		--key-id "${KEY_ID}"
		--secret "${SECRET}"
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
	bash deploy/remote-smoke.sh "${SMOKE_ARGS[@]}"
fi

if [ "${WITH_PORTAL_SMOKE}" = "1" ]; then
	if [ -z "${MEMBER_EMAIL}" ]; then
		echo "[fail] --with-portal-smoke requires --member-email or NPCINK_CLOUD_MEMBER_EMAIL" >&2
		exit 1
	fi
	bash deploy/remote-bootstrap-portal-site.sh \
		--base-url "${BASE_URL}" \
		--site-id "${SITE_ID}" \
		--member-email "${MEMBER_EMAIL}"
	bash deploy/remote-portal-smoke.sh \
		--base-url "${BASE_URL}" \
		--site-id "${SITE_ID}" \
		--member-email "${MEMBER_EMAIL}"
fi

if [ "${WITH_OPERATIONAL_READY}" = "1" ]; then
	echo "[info] Running remote operational readiness gate"
	bash deploy/remote-operational-ready.sh --base-url "${BASE_URL}"
	echo "[ok] Remote operational readiness gate passed"
fi

echo "[ok] Remote release ready at ${RELEASE_DIR}"
EOF

echo "[ok] Remote deploy completed: ${SSH_TARGET}:${REMOTE_DIR}/current"
