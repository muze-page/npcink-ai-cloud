#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

M4_SSH_HOST="${NPCINK_CLOUD_M4_SSH_HOST:-muze@100.102.170.79}"
M4_REMOTE_DIR="${NPCINK_CLOUD_M4_REMOTE_DIR:-/Users/muze/gitee/npcink-ai-cloud}"
M4_PROJECT_NAME="${NPCINK_CLOUD_M4_PROJECT_NAME:-npcink-ai-cloud-m4-preview}"
M4_EXTERNAL_URL="${NPCINK_CLOUD_M4_EXTERNAL_URL:-https://cloud.mqzjmax.top}"
M4_TAILSCALE_IP="${NPCINK_CLOUD_M4_TAILSCALE_IP:-100.102.170.79}"

RELAY_SSH_HOST="${NPCINK_CLOUD_M4_RELAY_SSH_HOST:-root@74.82.195.160}"
RELAY_TAILSCALE_IP="${NPCINK_CLOUD_M4_RELAY_TAILSCALE_IP:-100.90.87.36}"
RELAY_HTTP_PORT="${NPCINK_CLOUD_M4_RELAY_HTTP_PORT:-18080}"

WITH_IMAGES=0
DRY_RUN=0
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
TMP_DIR=""
RELAY_UNIT=""
RELAY_DIR=""
RELAY_BUNDLE_NAME=""

usage() {
	cat <<'EOF'
Usage: deploy/m4-preview-deploy.sh [--with-images] [--dry-run]

Deploy the current M5 working-tree snapshot to the M4 Docker preview.

Default mode is fast source-only deployment. It reuses the dev images already
loaded on M4, applies Alembic migrations, recreates API/frontend/proxy, and
runs loopback plus Cloudflare Access smoke checks.

Options:
  --with-images  Rebuild API/frontend images on M5 and transfer them through
                 the temporary Tailscale-only relay before deploying source.
  --dry-run      Validate and package locally, but do not contact M4 or relay.
  --help         Show this help.

Common overrides:
  NPCINK_CLOUD_M4_SSH_HOST
  NPCINK_CLOUD_M4_REMOTE_DIR
  NPCINK_CLOUD_M4_EXTERNAL_URL
  NPCINK_CLOUD_M4_RELAY_SSH_HOST
  NPCINK_CLOUD_M4_RELAY_TAILSCALE_IP
EOF
}

log() {
	printf '[m4-preview] %s\n' "$*"
}

fail() {
	printf '[m4-preview] fail: %s\n' "$*" >&2
	exit 1
}

require_cmd() {
	command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

cleanup() {
	local status=$?
	if [ -n "${RELAY_UNIT}" ]; then
		ssh -o BatchMode=yes -o ConnectTimeout=10 "${RELAY_SSH_HOST}" \
			"systemctl stop '${RELAY_UNIT}' >/dev/null 2>&1 || true; rm -f '${RELAY_DIR}/${RELAY_BUNDLE_NAME}'; rmdir '${RELAY_DIR}' >/dev/null 2>&1 || true" \
			>/dev/null 2>&1 || true
	fi
	if [ -n "${TMP_DIR}" ] && [ -d "${TMP_DIR}" ]; then
		find "${TMP_DIR}" -depth -delete
	fi
	exit "${status}"
}

while [ "$#" -gt 0 ]; do
	case "$1" in
		--)
			shift
			;;
		--with-images)
			WITH_IMAGES=1
			shift
			;;
		--dry-run)
			DRY_RUN=1
			shift
			;;
		--help|-h)
			usage
			exit 0
			;;
		*)
			fail "unknown argument: $1"
			;;
	esac
done

for cmd in docker git rsync scp ssh tar curl gzip shasum; do
	require_cmd "${cmd}"
done

case "${RELAY_TAILSCALE_IP}" in
	*[!0-9.]*|'') fail "relay Tailscale IP must contain only digits and dots" ;;
esac
case "${RELAY_HTTP_PORT}" in
	*[!0-9]*|'') fail "relay HTTP port must be numeric" ;;
esac

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/npcink-m4-preview.XXXXXX")"
trap cleanup EXIT INT TERM

COMPOSE_FILES=(
	-f "${ROOT_DIR}/docker-compose.dev.yml"
	-f "${ROOT_DIR}/docker-compose.m4-preview.yml"
)
COMPOSE_ENV=(--env-file "${ROOT_DIR}/.env" --env-file "${ROOT_DIR}/.env.local")

test -f "${ROOT_DIR}/.env" || fail "missing local .env"
test -f "${ROOT_DIR}/.env.local" || fail "missing local .env.local"

log "validating Compose and preview Nginx configuration"
docker compose "${COMPOSE_ENV[@]}" "${COMPOSE_FILES[@]}" config --quiet
docker run --rm \
	-v "${ROOT_DIR}/deploy/nginx.m4-preview.conf:/etc/nginx/conf.d/default.conf:ro" \
	nginx:1.27-alpine nginx -t >/dev/null

dependency_fingerprint() {
	local files=(
		Dockerfile
		pyproject.toml
		uv.lock
		frontend/Dockerfile.dev
		frontend/package.json
		frontend/pnpm-lock.yaml
		pnpm-lock.yaml
	)
	local present=()
	local file=""
	for file in "${files[@]}"; do
		if [ -f "${ROOT_DIR}/${file}" ]; then
			present+=("${file}")
		fi
	done
	(
		cd "${ROOT_DIR}"
		shasum -a 256 "${present[@]}" | shasum -a 256 | awk '{print $1}'
	)
}

IMAGE_INPUT_SHA256="$(dependency_fingerprint)"
SOURCE_STAGE="${TMP_DIR}/source"
SOURCE_FILE_LIST="${TMP_DIR}/source-files"
SOURCE_BUNDLE="${TMP_DIR}/source.tgz"
mkdir -p "${SOURCE_STAGE}"

log "packaging tracked and non-ignored M5 source"
(
	cd "${ROOT_DIR}"
	git ls-files -z --cached --others --exclude-standard -- \
		. \
		':(exclude).env' \
		':(exclude).env.local' \
		':(exclude).env.deploy' > "${SOURCE_FILE_LIST}"
)
rsync -a --from0 --files-from="${SOURCE_FILE_LIST}" "${ROOT_DIR}/" "${SOURCE_STAGE}/"
COPYFILE_DISABLE=1 tar -czf "${SOURCE_BUNDLE}" -C "${SOURCE_STAGE}" .
SOURCE_BUNDLE_SHA256="$(shasum -a 256 "${SOURCE_BUNDLE}" | awk '{print $1}')"
SOURCE_REVISION="$(git -C "${ROOT_DIR}" rev-parse --short=12 HEAD)"
if ! git -C "${ROOT_DIR}" diff --quiet || ! git -C "${ROOT_DIR}" diff --cached --quiet ||
	[ -n "$(git -C "${ROOT_DIR}" ls-files --others --exclude-standard)" ]; then
	SOURCE_REVISION="${SOURCE_REVISION}+working-tree"
fi

log "source revision: ${SOURCE_REVISION}"
log "source bundle: ${SOURCE_BUNDLE_SHA256}"

if [ "${DRY_RUN}" = "1" ]; then
	if [ "${WITH_IMAGES}" = "1" ]; then
		log "dry-run: would build API/frontend images and transfer through ${RELAY_SSH_HOST}"
	fi
	log "dry-run: would deploy to ${M4_SSH_HOST}:${M4_REMOTE_DIR}"
	exit 0
fi

SSH_ARGS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)
SCP_ARGS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)

log "checking M4 reachability and preview prerequisites"
ssh "${SSH_ARGS[@]}" "${M4_SSH_HOST}" bash -s -- \
	"${M4_REMOTE_DIR}" "${IMAGE_INPUT_SHA256}" "${WITH_IMAGES}" <<'REMOTE_PREFLIGHT'
set -euo pipefail
remote_dir="$1"
local_image_sha="$2"
with_images="$3"
cache_dir="$HOME/.cache/npcink-ai-cloud-m4-preview"
marker="$cache_dir/image-input.sha256"

command -v docker >/dev/null
command -v rsync >/dev/null
test -f "$remote_dir/.env"
test -f "$remote_dir/.env.local"

if [ "$with_images" != "1" ]; then
	docker image inspect npcink-ai-cloud-api:dev >/dev/null
	docker image inspect npcink-ai-cloud-frontend:dev >/dev/null
	if [ -f "$marker" ] && [ "$(cat "$marker")" != "$local_image_sha" ]; then
		echo '[m4-preview] dependency inputs changed; rerun with --with-images' >&2
		exit 42
	fi
fi
REMOTE_PREFLIGHT

transfer_images_via_relay() {
	local image_bundle="${TMP_DIR}/m4-images.tar.gz"
	local image_sha=""
	local remote_image_bundle="/tmp/npcink-ai-cloud-m4-images-${RUN_ID}.tar.gz"

	log "building API/frontend images on M5"
	docker compose "${COMPOSE_ENV[@]}" "${COMPOSE_FILES[@]}" build api frontend
	log "packing API/frontend images"
	docker save npcink-ai-cloud-api:dev npcink-ai-cloud-frontend:dev | gzip -1 > "${image_bundle}"
	image_sha="$(shasum -a 256 "${image_bundle}" | awk '{print $1}')"

	RELAY_UNIT="npcink-m4-images-${RUN_ID}.service"
	RELAY_DIR="/var/tmp/npcink-m4-images-${RUN_ID}"
	RELAY_BUNDLE_NAME="$(basename "${image_bundle}")"

	log "uploading image bundle to the temporary relay"
	ssh "${SSH_ARGS[@]}" "${RELAY_SSH_HOST}" "install -d -m 700 '${RELAY_DIR}'"
	scp "${SCP_ARGS[@]}" "${image_bundle}" "${RELAY_SSH_HOST}:${RELAY_DIR}/${RELAY_BUNDLE_NAME}"
	ssh "${SSH_ARGS[@]}" "${RELAY_SSH_HOST}" \
		"systemd-run --quiet --unit='${RELAY_UNIT}' --property=Restart=no /usr/bin/python3 -m http.server '${RELAY_HTTP_PORT}' --bind '${RELAY_TAILSCALE_IP}' --directory '${RELAY_DIR}'"

	log "loading image bundle on M4 over the Tailscale-only relay"
	ssh "${SSH_ARGS[@]}" "${M4_SSH_HOST}" bash -s -- \
		"http://${RELAY_TAILSCALE_IP}:${RELAY_HTTP_PORT}/${RELAY_BUNDLE_NAME}" \
		"${remote_image_bundle}" "${image_sha}" <<'REMOTE_IMAGE_LOAD'
set -euo pipefail
url="$1"
bundle="$2"
expected_sha="$3"
trap 'rm -f "$bundle"' EXIT
curl -fL --retry 3 --retry-connrefused --retry-delay 1 \
	--connect-timeout 10 --max-time 1800 "$url" -o "$bundle"
actual_sha="$(shasum -a 256 "$bundle" | awk '{print $1}')"
test "$actual_sha" = "$expected_sha"
gzip -dc "$bundle" | docker load
REMOTE_IMAGE_LOAD

	ssh "${SSH_ARGS[@]}" "${RELAY_SSH_HOST}" \
		"systemctl stop '${RELAY_UNIT}' >/dev/null 2>&1 || true; rm -f '${RELAY_DIR}/${RELAY_BUNDLE_NAME}'; rmdir '${RELAY_DIR}' >/dev/null 2>&1 || true"
	RELAY_UNIT=""
}

if [ "${WITH_IMAGES}" = "1" ]; then
	transfer_images_via_relay
fi

REMOTE_SOURCE_BUNDLE="/tmp/npcink-ai-cloud-m4-source-${RUN_ID}.tgz"
log "uploading source snapshot to M4"
scp "${SCP_ARGS[@]}" "${SOURCE_BUNDLE}" "${M4_SSH_HOST}:${REMOTE_SOURCE_BUNDLE}"

log "syncing source, migrating database, and recreating preview services"
ssh "${SSH_ARGS[@]}" "${M4_SSH_HOST}" bash -s -- \
	"${M4_REMOTE_DIR}" "${REMOTE_SOURCE_BUNDLE}" "${M4_PROJECT_NAME}" \
	"${IMAGE_INPUT_SHA256}" "${SOURCE_REVISION}" "${SOURCE_BUNDLE_SHA256}" <<'REMOTE_DEPLOY'
set -euo pipefail
remote_dir="$1"
source_bundle="$2"
project_name="$3"
image_input_sha="$4"
source_revision="$5"
source_bundle_sha="$6"
staging="${remote_dir}.incoming.$$"
cache_dir="$HOME/.cache/npcink-ai-cloud-m4-preview"

cleanup() {
	rm -f "$source_bundle"
	if [ -d "$staging" ]; then
		find "$staging" -depth -delete
	fi
}
trap cleanup EXIT

mkdir -p "$staging" "$cache_dir"
tar -xzf "$source_bundle" -C "$staging"
test -f "$staging/docker-compose.dev.yml"
test -f "$staging/docker-compose.m4-preview.yml"
test -f "$staging/deploy/nginx.m4-preview.conf"

cp "$remote_dir/.env" "$staging/.env"
cp "$remote_dir/.env.local" "$staging/.env.local"
chmod 600 "$staging/.env" "$staging/.env.local"

cd "$staging"
docker compose -p "$project_name" --env-file .env --env-file .env.local \
	-f docker-compose.dev.yml -f docker-compose.m4-preview.yml config --quiet

mkdir -p "$remote_dir"
rsync -a --delete \
	--exclude '.env' \
	--exclude '.env.local' \
	--exclude '.env.deploy' \
	--exclude '.git' \
	--exclude '.docker-codex-preview' \
	--exclude '.runtime' \
	--exclude '.venv' \
	--exclude '.pytest_cache' \
	--exclude '__pycache__' \
	--exclude 'dist' \
	--exclude 'node_modules' \
	--exclude 'frontend/.next' \
	--exclude 'frontend/node_modules' \
	--exclude 'frontend/playwright-report' \
	--exclude 'frontend/test-results' \
	"$staging/" "$remote_dir/"

cd "$remote_dir"
compose=(docker compose -p "$project_name" --env-file .env --env-file .env.local -f docker-compose.dev.yml -f docker-compose.m4-preview.yml)
"${compose[@]}" up -d --pull never postgres redis
"${compose[@]}" run --interactive=false -T --rm --pull never api alembic upgrade head
"${compose[@]}" up -d --no-build --pull never --force-recreate api frontend proxy

home_code=""
for _ in $(seq 1 30); do
	home_code="$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/ || true)"
	if [ "$home_code" = "200" ] && curl -fsS http://127.0.0.1:8010/health/live >/dev/null; then
		break
	fi
	sleep 2
done
test "$home_code" = "200"
test "$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/docs)" = "404"
test "$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/health/ready)" = "404"
test "$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/internal/health)" = "404"

test "$(docker port "${project_name}-proxy-1" 8080/tcp)" = '127.0.0.1:8010'
test "$(docker port "${project_name}-postgres-1" 5432/tcp)" = '127.0.0.1:15433'
test "$(docker port "${project_name}-redis-1" 6379/tcp)" = '127.0.0.1:16380'

printf '%s\n' "$image_input_sha" > "$cache_dir/image-input.sha256"
{
	printf 'source_revision=%s\n' "$source_revision"
	printf 'source_bundle_sha256=%s\n' "$source_bundle_sha"
	printf 'deployed_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$cache_dir/last-deploy.txt"

"${compose[@]}" ps
REMOTE_DEPLOY

log "checking Cloudflare Access perimeter"
EXTERNAL_HEADERS="${TMP_DIR}/external-headers"
curl -sS -o /dev/null -D "${EXTERNAL_HEADERS}" --max-time 30 "${M4_EXTERNAL_URL}/"
EXTERNAL_STATUS="$(awk 'NR == 1 {print $2}' "${EXTERNAL_HEADERS}")"
EXTERNAL_LOCATION="$(awk 'tolower($1) == "location:" {print $2}' "${EXTERNAL_HEADERS}" | tr -d '\r' | head -n 1)"
if [ "${EXTERNAL_STATUS}" != "302" ] || [[ "${EXTERNAL_LOCATION}" != https://*.cloudflareaccess.com/* ]]; then
	fail "external preview is not protected by Cloudflare Access"
fi

if curl -fsS --connect-timeout 2 --max-time 4 "http://${M4_TAILSCALE_IP}:8010/" >/dev/null 2>&1; then
	fail "preview port 8010 is reachable directly over Tailscale"
fi

log "ok: ${M4_EXTERNAL_URL} is deployed and Access-protected"
