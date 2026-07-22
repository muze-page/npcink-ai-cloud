#!/usr/bin/env bash
set -euo pipefail
set +x

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
RELEASE_DIR="${TMP_DIR}/release-smoke"
STATE_DIR="${TMP_DIR}/.release-state/release-smoke"
DEPLOY_LOCK_DIR="${TMP_DIR}/.deploy-lock"
CONFIG_DIR="${TMP_DIR}/shared/config"
FRONTEND_CONFIG_DIR="${CONFIG_DIR}/frontend"
BACKEND_ENV_FILE="${STATE_DIR}/env.deploy"
PG18_PROOF_COMPOSE="${ROOT_DIR}/docker-compose.pg18-proof.yml"
PG18_PROOF_OVERRIDE="${TMP_DIR}/docker-compose.pg18-proof.host-port.yml"
DEPLOY_LOCK_OWNER="dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
install -d -m 0700 \
	"${RELEASE_DIR}" "${TMP_DIR}/.release-state" "${STATE_DIR}" "${DEPLOY_LOCK_DIR}" \
	"${CONFIG_DIR}"
install -d -m 0750 "${FRONTEND_CONFIG_DIR}"
printf '%s\n' "${DEPLOY_LOCK_OWNER}" >"${DEPLOY_LOCK_DIR}/one-off-owner"
chmod 0600 "${DEPLOY_LOCK_DIR}/one-off-owner"
export NPCINK_CLOUD_DEPLOY_LOCK_OWNER="${DEPLOY_LOCK_OWNER}"
PROJECT_NAME="npcink-ai-cloud-deploy-smoke-$(date +%s)"
PG18_PROOF_PROJECT_NAME="${PROJECT_NAME}-pg18"
PG18_PROOF_PORT="${NPCINK_CLOUD_DEPLOY_SMOKE_POSTGRES_PORT:-55432}"
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
unset NPCINK_CLOUD_SECRET
DEPLOY_SMOKE_POSTGRES_PASSWORD="${NPCINK_CLOUD_DEPLOY_SMOKE_POSTGRES_PASSWORD:-npcink-cloud-deploy-postgres-secret}"
DEPLOY_SMOKE_INTERNAL_TOKEN="${NPCINK_CLOUD_INTERNAL_AUTH_TOKEN:-npcink-cloud-deploy-internal-token-32b}"
if [[ ! "${DEPLOY_SMOKE_POSTGRES_PASSWORD}" =~ ^[A-Za-z0-9._-]{16,128}$ ]]; then
	fail "NPCINK_CLOUD_DEPLOY_SMOKE_POSTGRES_PASSWORD must be 16-128 URL-safe characters"
fi
if [[ ! "${PG18_PROOF_PORT}" =~ ^[0-9]+$ ]] ||
	[ "${PG18_PROOF_PORT}" -lt 1024 ] || [ "${PG18_PROOF_PORT}" -gt 65535 ]; then
	fail "NPCINK_CLOUD_DEPLOY_SMOKE_POSTGRES_PORT must be an integer from 1024 through 65535"
fi

# The database fixture is a separate Compose project so the production
# remove-orphans phase cannot delete it. A smoke-only host port preserves that
# boundary while release containers use their existing host-gateway mapping.
printf '%s\n' \
	'services:' \
	'  postgres18-proof:' \
	'    ports:' \
	"      - \"0.0.0.0:${PG18_PROOF_PORT}:5432\"" \
	>"${PG18_PROOF_OVERRIDE}"

export NPCINK_CLOUD_PG18_PROOF_PASSWORD="${DEPLOY_SMOKE_POSTGRES_PASSWORD}"
export NPCINK_CLOUD_ENVIRONMENT="${NPCINK_CLOUD_ENVIRONMENT:-test}"
export NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST="${NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST:-${BASE_URL}}"
export NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST="${NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST:-${BASE_HOST},127.0.0.1,localhost}"
export NPCINK_CLOUD_SKIP_FRONTEND_IMAGE="${NPCINK_CLOUD_SKIP_FRONTEND_IMAGE:-0}"
export NPCINK_CLOUD_INCLUDE_EXTERNAL_IMAGES="${NPCINK_CLOUD_INCLUDE_EXTERNAL_IMAGES:-1}"
export NPCINK_CLOUD_CONFIG_DIR_HOST="${CONFIG_DIR}"
export NPCINK_CLOUD_ENV_FILE="${BACKEND_ENV_FILE}"
export NPCINK_CLOUD_BACKEND_ENV_FILE="${BACKEND_ENV_FILE}"
export NPCINK_CLOUD_DEPLOY_SMOKE_BACKEND_ENV="test"
export NPCINK_CLOUD_DEPLOY_SMOKE_FRONTEND_ENV="test"
export NPCINK_CLOUD_DEPLOY_SMOKE_SETUP_STATE_OVERRIDE="complete"

printf '%s\n' \
	'{"config_digest":"0000000000000000000000000000000000000000000000000000000000000000","database_contract":"pg18_empty_initialization.v1","installation_state":"complete","retry_allowed":false,"setup_revision":"first-install-v1","updated_at":"2026-01-01T00:00:00Z"}' \
	>"${CONFIG_DIR}/install-state.json"
printf '%s\n' "${DEPLOY_SMOKE_INTERNAL_TOKEN}" \
	>"${FRONTEND_CONFIG_DIR}/internal-auth-token"
chmod 0640 "${CONFIG_DIR}/install-state.json" "${FRONTEND_CONFIG_DIR}/internal-auth-token"

{
	printf 'NPCINK_CLOUD_ENVIRONMENT=%s\n' "${NPCINK_CLOUD_ENVIRONMENT}"
	printf 'NPCINK_CLOUD_DATABASE_URL=postgresql+psycopg://npcink:%s@host.docker.internal:%s/npcink_ai_cloud\n' \
		"${DEPLOY_SMOKE_POSTGRES_PASSWORD}" "${PG18_PROOF_PORT}"
	printf 'NPCINK_CLOUD_INTERNAL_AUTH_TOKEN=%s\n' "${DEPLOY_SMOKE_INTERNAL_TOKEN}"
	printf 'NPCINK_CLOUD_ADMIN_SESSION_SECRET=%s\n' "${NPCINK_CLOUD_ADMIN_SESSION_SECRET:-npcink-cloud-deploy-admin-session-secret-32b}"
	printf 'NPCINK_CLOUD_SERVICE_SETTINGS_SECRET=%s\n' "${NPCINK_CLOUD_SERVICE_SETTINGS_SECRET:-Tk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk5OTk4=}" # gitleaks:allow
	printf 'NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID=%s\n' "${NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID:-deploy-smoke-service-settings-v1}"
	printf 'NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET=%s\n' "${NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET:-UlJSUlJSUlJSUlJSUlJSUlJSUlJSUlJSUlJSUlJSUlI=}" # gitleaks:allow
	printf 'NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID=%s\n' "${NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID:-deploy-smoke-runtime-data-v1}"
	printf 'NPCINK_CLOUD_PORTAL_JWT_SECRET=%s\n' "${NPCINK_CLOUD_PORTAL_JWT_SECRET:-npcink-cloud-deploy-portal-jwt-secret-32b}"
	printf 'NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST=%s\n' "${NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST}"
	printf 'NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST=%s\n' "${NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST}"
} >"${BACKEND_ENV_FILE}"
chmod 0600 "${BACKEND_ENV_FILE}"

cleanup() {
	local rollback_reference=""
	if [ "${NPCINK_CLOUD_DEPLOY_SMOKE_KEEP:-0}" = "1" ]; then
		return 0
	fi
	if [ -f "${STATE_DIR}/rollback-images.tsv" ]; then
		while IFS=$'\t' read -r _target_reference rollback_reference _image_id; do
			[ -n "${rollback_reference}" ] && [ "${rollback_reference}" != "-" ] || continue
			docker image rm "${rollback_reference}" >/dev/null 2>&1 || true
		done <"${STATE_DIR}/rollback-images.tsv"
	fi
	if [ -f "${RELEASE_DIR}/docker-compose.prod.yml" ]; then
		COMPOSE_PROJECT_NAME="${PG18_PROOF_PROJECT_NAME}" \
			docker compose -f "${PG18_PROOF_COMPOSE}" -f "${PG18_PROOF_OVERRIDE}" \
			down -v --remove-orphans >/dev/null 2>&1 || true
		COMPOSE_PROJECT_NAME="${PROJECT_NAME}" \
		NPCINK_CLOUD_PORT="${PORT}" \
		NPCINK_CLOUD_CONFIG_DIR_HOST="${CONFIG_DIR}" \
		NPCINK_CLOUD_BACKEND_ENV_FILE="${BACKEND_ENV_FILE}" \
			docker compose -f "${RELEASE_DIR}/docker-compose.prod.yml" down -v --remove-orphans >/dev/null 2>&1 || true
	fi
	rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

run_deploy_command() {
	( cd "${RELEASE_DIR}" && "$@" )
}

prepare_smoke_config_permissions() {
	docker run --rm --network none --read-only --user 0:0 \
		--volume "${CONFIG_DIR}:/config" \
		--entrypoint /bin/sh npcink-ai-cloud-api:prod -ceu '
			chown 999:999 /config /config/install-state.json /config/frontend /config/frontend/internal-auth-token
			chmod 0700 /config
			chmod 0750 /config/frontend
			chmod 0640 /config/install-state.json /config/frontend/internal-auth-token
		'
}

ensure_external_pg18_proof() {
	local server_version=""
	COMPOSE_PROJECT_NAME="${PG18_PROOF_PROJECT_NAME}" \
		docker compose -f "${PG18_PROOF_COMPOSE}" -f "${PG18_PROOF_OVERRIDE}" \
		up -d --wait postgres18-proof
	server_version="$(COMPOSE_PROJECT_NAME="${PG18_PROOF_PROJECT_NAME}" \
		docker compose -f "${PG18_PROOF_COMPOSE}" -f "${PG18_PROOF_OVERRIDE}" \
		exec -T postgres18-proof \
		psql -v ON_ERROR_STOP=1 -U npcink -d npcink_ai_cloud -Atc \
		"select case when current_setting('server_version_num')::int between 180000 and 189999 then 'postgresql-18' else current_setting('server_version') end")" \
		|| fail "External deploy-smoke database version could not be read"
	[ "${server_version}" = "postgresql-18" ] || \
		fail "External deploy-smoke database is not PostgreSQL 18"
	ok "External PostgreSQL 18 proof target is healthy (local no-TLS fixture; not RDS evidence)"
}

stop_replay_application_services() {
	local service=""
	local running_ids=""
	run_deploy_command docker compose -f docker-compose.prod.yml stop \
		api worker callback-worker ops-worker frontend proxy
	for service in api worker callback-worker ops-worker frontend proxy; do
		running_ids="$(
			run_deploy_command docker compose -f docker-compose.prod.yml ps -q "${service}"
		)" || fail "Docker could not prove ${service} stopped before data replay"
		[ -z "${running_ids}" ] || \
			fail "Application service remained running before data replay: ${service}"
	done
}

replay_staged_release() {
	NPCINK_CLOUD_LOAD_MODE=prepare-only \
	NPCINK_CLOUD_ROLLBACK_IMAGE_MAP="${STATE_DIR}/rollback-images.tsv" \
	NPCINK_CLOUD_ROLLBACK_TAG_SUFFIX=deploy-smoke \
		run_deploy_command bash deploy/remote-load-and-up.sh
	prepare_smoke_config_permissions
	stop_replay_application_services
	NPCINK_CLOUD_LOAD_MODE=data-only \
		run_deploy_command bash deploy/remote-load-and-up.sh
	ensure_external_pg18_proof
	run_deploy_command bash deploy/remote-migrate.sh
	NPCINK_CLOUD_LOAD_MODE=api-only \
		run_deploy_command bash deploy/remote-load-and-up.sh
	NPCINK_CLOUD_LOAD_MODE=workers-only \
		run_deploy_command bash deploy/remote-load-and-up.sh
	NPCINK_CLOUD_LOAD_MODE=traffic-only \
		run_deploy_command bash deploy/remote-load-and-up.sh
}

require_cmd docker
require_cmd tar
require_cmd bash
require_cmd python3
require_cmd git

cd "${ROOT_DIR}"

ok "Preparing one exact deploy bundle"
if [ "${NPCINK_CLOUD_DEPLOY_SMOKE_SKIP_BUILD:-0}" = "1" ]; then
	[ -f "dist/deploy-bundle.tgz" ] && [ -f "dist/deploy-bundle.tgz.sha256" ] || \
		fail "Exact deploy bundle/checksum is missing; skip-build never rebuilds implicitly"
	ok "Reusing existing deploy bundle without rebuilding"
else
	bash deploy/bundle-images.sh || fail "Exact deploy bundle build and scan failed"
fi

ok "Verifying exact bundle before extraction"
bash deploy/verify-release-bundle.sh --archive \
	dist/deploy-bundle.tgz dist/deploy-bundle.tgz.sha256
BUNDLE_REVISION="$(
	tar -xOf dist/deploy-bundle.tgz release-bundle-manifest.json |
		python3 -c 'import json,sys; print(json.load(sys.stdin)["source"]["revision"])'
)"
CURRENT_REVISION="$(git rev-parse HEAD)"
[ "${BUNDLE_REVISION}" = "${CURRENT_REVISION}" ] || \
	fail "Exact deploy bundle revision ${BUNDLE_REVISION} does not match current HEAD ${CURRENT_REVISION}"
BUNDLE_RECEIPT="$(cat dist/deploy-bundle.tgz.sha256)"

ok "Extracting deploy bundle to ${RELEASE_DIR}"
tar xzf dist/deploy-bundle.tgz -C "${RELEASE_DIR}"

export COMPOSE_PROJECT_NAME="${PROJECT_NAME}"
export NPCINK_CLOUD_PORT="${PORT}"
export NPCINK_CLOUD_BASE_URL="${BASE_URL}"
export NPCINK_CLOUD_SITE_ID="${SITE_ID}"
export NPCINK_CLOUD_KEY_ID="${KEY_ID}"
ok "Replaying bundle load/up"
replay_staged_release

ok "Replaying the same verified bundle a second time (no build)"
replay_staged_release

ok "Proving the exact bundle archive was not replaced during replay"
bash deploy/verify-release-bundle.sh --archive \
	dist/deploy-bundle.tgz dist/deploy-bundle.tgz.sha256
FINAL_BUNDLE_RECEIPT="$(cat dist/deploy-bundle.tgz.sha256)"
[ "${FINAL_BUNDLE_RECEIPT}" = "${BUNDLE_RECEIPT}" ] || fail "Deploy bundle receipt changed during smoke replay"
ok "The same exact bundle receipt was reused: ${BUNDLE_RECEIPT%%  *}"

ok "Replaying seed"
NPCINK_CLOUD_SECRET="${SECRET}" \
	run_deploy_command bash deploy/remote-seed-runtime.sh --site-id "${SITE_ID}" --key-id "${KEY_ID}"

ok "Running smoke"
NPCINK_CLOUD_SECRET="${SECRET}" \
	run_deploy_command bash deploy/remote-smoke.sh --base-url "${BASE_URL}" --site-id "${SITE_ID}" --key-id "${KEY_ID}"

ok "Cloud deploy bundle smoke completed successfully."
