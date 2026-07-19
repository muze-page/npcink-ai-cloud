#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

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

# Formal images are built and scanned against one local Unix Docker daemon.
# Remote deployment is exercised by deploy/deploy-to-ssh-host.sh, which uploads
# the already verified bundle instead of redirecting this build through SSH.
[ -z "${DOCKER_HOST:-}" ] || fail "deploy-bundle smoke forbids DOCKER_HOST; build and replay locally"
[ -z "${DOCKER_CONTEXT:-}" ] || fail "deploy-bundle smoke forbids DOCKER_CONTEXT overrides"

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/npcink-ai-cloud-deploy-smoke.XXXXXX")"
PROJECT_NAME="npcink-ai-cloud-deploy-smoke-$(date +%s)"
PORT="${NPCINK_CLOUD_DEPLOY_SMOKE_PORT:-8110}"
BASE_URL="${NPCINK_CLOUD_DEPLOY_SMOKE_BASE_URL:-http://127.0.0.1:${PORT}}"
BASE_HOST="$(python3 - "${BASE_URL}" <<'PY'
from urllib.parse import urlparse
import sys

print(urlparse(sys.argv[1]).hostname or "")
PY
)"
SITE_ID="${NPCINK_CLOUD_SITE_ID:-site_deploy_smoke}"
KEY_ID="${NPCINK_CLOUD_KEY_ID:-key_deploy_smoke}"
SECRET="${NPCINK_CLOUD_SECRET:-npcink-cloud-deploy-secret}"
DEPLOY_SMOKE_POSTGRES_PASSWORD="${NPCINK_CLOUD_DEPLOY_SMOKE_POSTGRES_PASSWORD:-npcink-cloud-deploy-postgres-secret}"

export POSTGRES_PASSWORD="${DEPLOY_SMOKE_POSTGRES_PASSWORD}"
export NPCINK_CLOUD_ENVIRONMENT="${NPCINK_CLOUD_ENVIRONMENT:-test}"
export NPCINK_CLOUD_DATABASE_URL="postgresql+psycopg://npcink:${DEPLOY_SMOKE_POSTGRES_PASSWORD}@postgres:5432/npcink_ai_cloud"
export NPCINK_CLOUD_INTERNAL_AUTH_TOKEN="${NPCINK_CLOUD_INTERNAL_AUTH_TOKEN:-npcink-cloud-deploy-internal-token-32b}"
export NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN="${NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN:-npcink-cloud-deploy-bootstrap-token-32b}"
export NPCINK_CLOUD_ADMIN_SESSION_SECRET="${NPCINK_CLOUD_ADMIN_SESSION_SECRET:-npcink-cloud-deploy-admin-session-secret-32b}"
export NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET="${NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET:-npcink-cloud-deploy-runtime-data-secret-32b}"
export NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID="${NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID:-deploy-smoke-runtime-data-v1}"
export NPCINK_CLOUD_PORTAL_JWT_SECRET="${NPCINK_CLOUD_PORTAL_JWT_SECRET:-npcink-cloud-deploy-portal-jwt-secret-32b}"
export NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST="${NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST:-${BASE_URL}}"
export NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST="${NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST:-${BASE_HOST},127.0.0.1,localhost}"
export NPCINK_CLOUD_SKIP_FRONTEND_IMAGE="${NPCINK_CLOUD_SKIP_FRONTEND_IMAGE:-0}"
export NPCINK_CLOUD_INCLUDE_EXTERNAL_IMAGES="${NPCINK_CLOUD_INCLUDE_EXTERNAL_IMAGES:-1}"

cleanup() {
	if [ "${NPCINK_CLOUD_DEPLOY_SMOKE_KEEP:-0}" = "1" ]; then
		return 0
	fi
	if [ -f "${TMP_DIR}/docker-compose.prod.yml" ]; then
		COMPOSE_PROJECT_NAME="${PROJECT_NAME}" \
		NPCINK_CLOUD_PORT="${PORT}" \
			docker compose -f "${TMP_DIR}/docker-compose.prod.yml" down -v --remove-orphans >/dev/null 2>&1 || true
	fi
	rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

run_deploy_command() {
	( cd "${TMP_DIR}" && "$@" )
}

require_cmd docker
require_cmd tar
require_cmd bash
require_cmd python3

cd "${ROOT_DIR}"

ok "Preparing one exact deploy bundle"
if [ "${NPCINK_CLOUD_DEPLOY_SMOKE_SKIP_BUILD:-0}" = "1" ]; then
	[ -f "dist/deploy-bundle.tgz" ] && [ -f "dist/deploy-bundle.tgz.sha256" ] || \
		fail "Exact deploy bundle/checksum is missing; skip-build never rebuilds implicitly"
	ok "Reusing existing deploy bundle without rebuilding"
else
	bash deploy/bundle-images.sh
fi

ok "Verifying exact bundle before extraction"
bash deploy/verify-release-bundle.sh --archive \
	dist/deploy-bundle.tgz dist/deploy-bundle.tgz.sha256
BUNDLE_RECEIPT="$(cat dist/deploy-bundle.tgz.sha256)"

ok "Extracting deploy bundle to ${TMP_DIR}"
tar xzf dist/deploy-bundle.tgz -C "${TMP_DIR}"

export COMPOSE_PROJECT_NAME="${PROJECT_NAME}"
export NPCINK_CLOUD_PORT="${PORT}"
export NPCINK_CLOUD_BASE_URL="${BASE_URL}"
export NPCINK_CLOUD_SITE_ID="${SITE_ID}"
export NPCINK_CLOUD_KEY_ID="${KEY_ID}"
export NPCINK_CLOUD_SECRET="${SECRET}"

ok "Replaying bundle load/up"
run_deploy_command bash deploy/remote-load-and-up.sh

ok "Replaying the same verified bundle a second time (no build)"
run_deploy_command bash deploy/remote-load-and-up.sh

ok "Proving the exact bundle archive was not replaced during replay"
bash deploy/verify-release-bundle.sh --archive \
	dist/deploy-bundle.tgz dist/deploy-bundle.tgz.sha256
FINAL_BUNDLE_RECEIPT="$(cat dist/deploy-bundle.tgz.sha256)"
[ "${FINAL_BUNDLE_RECEIPT}" = "${BUNDLE_RECEIPT}" ] || fail "Deploy bundle receipt changed during smoke replay"
ok "The same exact bundle receipt was reused: ${BUNDLE_RECEIPT%%  *}"

ok "Replaying migrate"
run_deploy_command bash deploy/remote-migrate.sh

ok "Replaying seed"
run_deploy_command bash deploy/remote-seed-runtime.sh --site-id "${SITE_ID}" --key-id "${KEY_ID}" --secret "${SECRET}"

ok "Running smoke"
run_deploy_command bash deploy/remote-smoke.sh --base-url "${BASE_URL}" --site-id "${SITE_ID}" --key-id "${KEY_ID}" --secret "${SECRET}"

ok "Cloud deploy bundle smoke completed successfully."
