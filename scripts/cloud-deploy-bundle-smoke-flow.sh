#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_DOCKER_HOST=""
if [[ "${DOCKER_HOST:-}" == ssh://* ]]; then
	REMOTE_DOCKER_HOST="${DOCKER_HOST#ssh://}"
fi
if [[ -n "${REMOTE_DOCKER_HOST}" ]]; then
	SHARED_TMP_ROOT="${MAGICK_AI_DEPLOY_SMOKE_SHARED_TMP_ROOT:-${ROOT_DIR}/.tmp/cloud-deploy-smoke}"
	mkdir -p "${SHARED_TMP_ROOT}"
	TMP_DIR="$(mktemp -d "${SHARED_TMP_ROOT}/run.XXXXXX")"
else
	TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/magick-ai-cloud-deploy-smoke.XXXXXX")"
fi
PROJECT_NAME="magick-ai-cloud-deploy-smoke-$(date +%s)"
PORT="${MAGICK_AI_DEPLOY_SMOKE_PORT:-8110}"
BASE_URL="${MAGICK_AI_DEPLOY_SMOKE_BASE_URL:-http://127.0.0.1:${PORT}}"
BASE_HOST="$(python3 - "${BASE_URL}" <<'PY'
from urllib.parse import urlparse
import sys

print(urlparse(sys.argv[1]).hostname or "")
PY
)"
SITE_ID="${MAGICK_AI_CLOUD_SITE_ID:-site_deploy_smoke}"
KEY_ID="${MAGICK_AI_CLOUD_KEY_ID:-key_deploy_smoke}"
SECRET="${MAGICK_AI_CLOUD_SECRET:-magick-cloud-deploy-secret}"
DEPLOY_SMOKE_POSTGRES_PASSWORD="${MAGICK_AI_DEPLOY_SMOKE_POSTGRES_PASSWORD:-magick-cloud-deploy-postgres-secret}"

export POSTGRES_PASSWORD="${DEPLOY_SMOKE_POSTGRES_PASSWORD}"
export MAGICK_CLOUD_DATABASE_URL="postgresql+psycopg://magick:${DEPLOY_SMOKE_POSTGRES_PASSWORD}@postgres:5432/magick_ai_cloud"
export MAGICK_CLOUD_INTERNAL_AUTH_TOKEN="${MAGICK_CLOUD_INTERNAL_AUTH_TOKEN:-magick-cloud-deploy-internal-token-32b}"
export MAGICK_CLOUD_ADMIN_BOOTSTRAP_TOKEN="${MAGICK_CLOUD_ADMIN_BOOTSTRAP_TOKEN:-magick-cloud-deploy-bootstrap-token-32b}"
export MAGICK_CLOUD_ADMIN_SESSION_SECRET="${MAGICK_CLOUD_ADMIN_SESSION_SECRET:-magick-cloud-deploy-admin-session-secret-32b}"
export MAGICK_CLOUD_PROVIDER_CONNECTION_SECRET="${MAGICK_CLOUD_PROVIDER_CONNECTION_SECRET:-magick-cloud-deploy-provider-secret-32b}"
export MAGICK_CLOUD_PORTAL_JWT_SECRET="${MAGICK_CLOUD_PORTAL_JWT_SECRET:-magick-cloud-deploy-portal-jwt-secret-32b}"
export MAGICK_CLOUD_PORTAL_EMAIL_SMTP_HOST="${MAGICK_CLOUD_PORTAL_EMAIL_SMTP_HOST:-smtp.invalid}"
export MAGICK_CLOUD_PORTAL_EMAIL_FROM_EMAIL="${MAGICK_CLOUD_PORTAL_EMAIL_FROM_EMAIL:-noreply@magick.invalid}"
export MAGICK_CLOUD_BROWSER_ORIGIN_ALLOWLIST="${MAGICK_CLOUD_BROWSER_ORIGIN_ALLOWLIST:-${BASE_URL}}"
export MAGICK_CLOUD_TRUSTED_HOST_ALLOWLIST="${MAGICK_CLOUD_TRUSTED_HOST_ALLOWLIST:-${BASE_HOST},127.0.0.1,localhost}"

fail() {
	echo "[fail] $*" >&2
	exit 1
}

ok() {
	echo "[ok] $*"
}

require_cmd() {
	local cmd="$1"
	command -v "${cmd}" >/dev/null 2>&1 || fail "Missing required command: ${cmd}"
}

cleanup() {
	if [ "${MAGICK_AI_DEPLOY_SMOKE_KEEP:-0}" = "1" ]; then
		return 0
	fi
	if [ -n "${REMOTE_DOCKER_HOST}" ]; then
		ssh "${REMOTE_DOCKER_HOST}" "if [ -f $(printf '%q' "${TMP_DIR}/docker-compose.prod.yml") ]; then cd $(printf '%q' "${TMP_DIR}") && COMPOSE_PROJECT_NAME=$(printf '%q' "${PROJECT_NAME}") MAGICK_CLOUD_PORT=$(printf '%q' "${PORT}") docker compose -f docker-compose.prod.yml down -v --remove-orphans >/dev/null 2>&1 || true; fi" >/dev/null 2>&1 || true
	elif [ -f "${TMP_DIR}/docker-compose.prod.yml" ]; then
		COMPOSE_PROJECT_NAME="${PROJECT_NAME}" \
		MAGICK_CLOUD_PORT="${PORT}" \
		docker compose -f "${TMP_DIR}/docker-compose.prod.yml" down -v --remove-orphans >/dev/null 2>&1 || true
	fi
	if [ -n "${REMOTE_DOCKER_HOST}" ]; then
		ssh "${REMOTE_DOCKER_HOST}" "rm -rf $(printf '%q' "${TMP_DIR}")" >/dev/null 2>&1 || true
	fi
	rm -rf "${TMP_DIR}"
}

trap cleanup EXIT

remote_env_prefix() {
	local env_names=(
		POSTGRES_PASSWORD
		MAGICK_CLOUD_DATABASE_URL
		MAGICK_CLOUD_INTERNAL_AUTH_TOKEN
		MAGICK_CLOUD_ADMIN_BOOTSTRAP_TOKEN
		MAGICK_CLOUD_ADMIN_SESSION_SECRET
		MAGICK_CLOUD_PROVIDER_CONNECTION_SECRET
		MAGICK_CLOUD_PORTAL_JWT_SECRET
		MAGICK_CLOUD_PORTAL_EMAIL_SMTP_HOST
		MAGICK_CLOUD_PORTAL_EMAIL_FROM_EMAIL
		MAGICK_CLOUD_BROWSER_ORIGIN_ALLOWLIST
		MAGICK_CLOUD_TRUSTED_HOST_ALLOWLIST
		MAGICK_CLOUD_JAEGER_UI_PORT
		COMPOSE_PROJECT_NAME
		MAGICK_CLOUD_PORT
		MAGICK_CLOUD_BASE_URL
		MAGICK_CLOUD_PORTAL_PUBLIC_BASE_URL
		MAGICK_CLOUD_SITE_ID
		MAGICK_CLOUD_KEY_ID
		MAGICK_CLOUD_SECRET
		MAGICK_CLOUD_OPERATIONAL_READY_WAIT_ATTEMPTS
		MAGICK_CLOUD_OPERATIONAL_READY_WAIT_DELAY_SECONDS
	)
	local prefix="env"
	local name
	for name in "${env_names[@]}"; do
		prefix+=" $(printf '%q' "${name}=${!name:-}")"
	done
	printf '%s' "${prefix}"
}

run_deploy_command() {
	if [ -z "${REMOTE_DOCKER_HOST}" ]; then
		( cd "${TMP_DIR}" && "$@" )
		return 0
	fi

	local quoted_cmd
	printf -v quoted_cmd ' %q' "$@"
	ssh "${REMOTE_DOCKER_HOST}" "cd $(printf '%q' "${TMP_DIR}") && $(remote_env_prefix)${quoted_cmd}"
}

require_cmd docker
require_cmd tar
require_cmd bash
if [ -n "${REMOTE_DOCKER_HOST}" ]; then
	require_cmd rsync
	require_cmd ssh
fi

cd "${ROOT_DIR}"

ok "Building deploy bundle"
if [ "${MAGICK_AI_DEPLOY_SMOKE_SKIP_BUILD:-0}" = "1" ] && [ -f "dist/deploy-bundle.tgz" ]; then
	ok "Reusing existing deploy bundle"
elif [ -n "${REMOTE_DOCKER_HOST}" ]; then
	ok "Syncing deploy scripts to ${REMOTE_DOCKER_HOST}"
	ssh "${REMOTE_DOCKER_HOST}" "mkdir -p $(printf '%q' "${ROOT_DIR}/deploy") $(printf '%q' "${ROOT_DIR}/dist")"
	rsync -az --delete "${ROOT_DIR}/deploy/" "${REMOTE_DOCKER_HOST}:${ROOT_DIR}/deploy/"
	rsync -az "${ROOT_DIR}/docker-compose.prod.yml" "${REMOTE_DOCKER_HOST}:${ROOT_DIR}/docker-compose.prod.yml"
	MAGICK_CLOUD_REMOTE_BUNDLE_ONLY=1 bash deploy/bundle-images.sh
else
	bash deploy/bundle-images.sh
fi

ok "Extracting deploy bundle to ${TMP_DIR}"
if [ -n "${REMOTE_DOCKER_HOST}" ]; then
	ssh "${REMOTE_DOCKER_HOST}" "mkdir -p $(printf '%q' "${TMP_DIR}")"
	ssh "${REMOTE_DOCKER_HOST}" "tar xzf $(printf '%q' "${ROOT_DIR}/dist/deploy-bundle.tgz") -C $(printf '%q' "${TMP_DIR}")"
else
	tar xzf dist/deploy-bundle.tgz -C "${TMP_DIR}"
fi

export COMPOSE_PROJECT_NAME="${PROJECT_NAME}"
export MAGICK_CLOUD_PORT="${PORT}"
export MAGICK_CLOUD_BASE_URL="${BASE_URL}"
export MAGICK_CLOUD_PORTAL_PUBLIC_BASE_URL="${MAGICK_CLOUD_PORTAL_PUBLIC_BASE_URL:-${BASE_URL}}"
export MAGICK_CLOUD_SITE_ID="${SITE_ID}"
export MAGICK_CLOUD_KEY_ID="${KEY_ID}"
export MAGICK_CLOUD_SECRET="${SECRET}"

ok "Replaying remote load/up"
run_deploy_command bash deploy/remote-load-and-up.sh

ok "Replaying remote migrate"
run_deploy_command bash deploy/remote-migrate.sh

ok "Replaying remote seed"
run_deploy_command bash deploy/remote-seed-runtime.sh --site-id "${SITE_ID}" --key-id "${KEY_ID}" --secret "${SECRET}"

ok "Running remote smoke"
run_deploy_command bash deploy/remote-smoke.sh --base-url "${BASE_URL}" --site-id "${SITE_ID}" --key-id "${KEY_ID}" --secret "${SECRET}"

ok "Cloud deploy bundle smoke completed successfully."
