#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
DIST_DIR="${ROOT_DIR}/dist"
BASE_URL="${NPCINK_CLOUD_BASE_URL:-http://127.0.0.1:${NPCINK_CLOUD_PORT:-8010}}"
SKIP_FRONTEND_IMAGE="${NPCINK_CLOUD_SKIP_FRONTEND_IMAGE:-0}"

# Shared compose/env helpers for deploy scripts.
. "${ROOT_DIR}/deploy/common.sh"
npcink_ai_cloud_load_env_file "${ROOT_DIR}"

npcink_ai_cloud_require_cmd docker
npcink_ai_cloud_require_cmd curl
npcink_ai_cloud_require_internal_token

configure_ready_origin_headers() {
	if [ -n "${NPCINK_CLOUD_HEALTH_HOST_HEADER:-}" ] ||
		[ -n "${NPCINK_CLOUD_HEALTH_FORWARDED_PROTO:-}" ]; then
		return
	fi

	local origin="${NPCINK_CLOUD_READY_ORIGIN:-}"
	local proto=""
	local without_scheme=""
	local host=""

	if [ -z "${origin}" ]; then
		origin="${NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST:-}"
		origin="${origin%%,*}"
	fi
	origin="${origin#"${origin%%[![:space:]]*}"}"
	origin="${origin%"${origin##*[![:space:]]}"}"

	case "${origin}" in
		http://*|https://*)
			proto="${origin%%://*}"
			without_scheme="${origin#*://}"
			host="${without_scheme%%/*}"
			;;
		*)
			return
			;;
	esac

	if [ -n "${host}" ]; then
		export NPCINK_CLOUD_HEALTH_HOST_HEADER="${host}"
	fi
	if [ -n "${proto}" ]; then
		export NPCINK_CLOUD_HEALTH_FORWARDED_PROTO="${proto}"
	fi
}

configure_ready_origin_headers

echo "[info] Using compose file: ${NPCINK_CLOUD_COMPOSE_FILE:-${ROOT_DIR}/docker-compose.prod.yml}"

service_exists() {
	local service_name="$1"
	npcink_ai_cloud_compose "${ROOT_DIR}" config --services | grep -qx "${service_name}"
}

if [ -f "${DIST_DIR}/api.tar.gz" ]; then
  gzip -dc "${DIST_DIR}/api.tar.gz" | docker load
fi

if docker image inspect npcink-ai-cloud-api:prod >/dev/null 2>&1; then
  docker tag npcink-ai-cloud-api:prod npcink-ai-cloud-worker:prod
  docker tag npcink-ai-cloud-api:prod npcink-ai-cloud-callback-worker:prod
  docker tag npcink-ai-cloud-api:prod npcink-ai-cloud-ops-worker:prod
fi

if [ -f "${DIST_DIR}/worker.tar.gz" ]; then
  gzip -dc "${DIST_DIR}/worker.tar.gz" | docker load
fi

if [ -f "${DIST_DIR}/callback-worker.tar.gz" ]; then
  gzip -dc "${DIST_DIR}/callback-worker.tar.gz" | docker load
fi

if [ -f "${DIST_DIR}/ops-worker.tar.gz" ]; then
  gzip -dc "${DIST_DIR}/ops-worker.tar.gz" | docker load
fi

for image_archive in \
  postgres.tar.gz \
  redis.tar.gz \
  nginx.tar.gz \
  otel-collector.tar.gz \
  jaeger.tar.gz
do
  if [ -f "${DIST_DIR}/${image_archive}" ]; then
    gzip -dc "${DIST_DIR}/${image_archive}" | docker load
  fi
done

if [ -f "${DIST_DIR}/frontend.tar.gz" ]; then
  gzip -dc "${DIST_DIR}/frontend.tar.gz" | docker load
fi

SERVICES=(postgres redis api)
if [ "${SKIP_FRONTEND_IMAGE}" != "1" ]; then
	SERVICES+=(frontend)
fi
SERVICES+=(proxy)
if service_exists caddy; then
	SERVICES+=(caddy)
fi

echo "[info] Starting services: ${SERVICES[*]}"
npcink_ai_cloud_compose "${ROOT_DIR}" up -d "${SERVICES[@]}"

if ! npcink_ai_cloud_wait_for_ready "${BASE_URL}" 20 2; then
	echo "[fail] Cloud API did not become ready at ${BASE_URL}" >&2
	exit 1
fi

echo "[ok] Cloud API is ready at ${BASE_URL}"
