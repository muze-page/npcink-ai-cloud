#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
DIST_DIR="${ROOT_DIR}/dist"
BASE_URL="${NPCINK_CLOUD_BASE_URL:-http://127.0.0.1:${NPCINK_CLOUD_PORT:-8010}}"
SKIP_FRONTEND_IMAGE="${NPCINK_CLOUD_SKIP_FRONTEND_IMAGE:-0}"
MANIFEST_HELPER="${ROOT_DIR}/scripts/verify-release-bundle-manifest.py"
RELEASE_VERIFIER="${ROOT_DIR}/deploy/verify-release-bundle.sh"

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

[ -x "${RELEASE_VERIFIER}" ] || {
	echo "[fail] Exact release-bundle verifier is missing or not executable." >&2
	exit 1
}
[ -f "${MANIFEST_HELPER}" ] || {
	echo "[fail] Exact release-bundle manifest helper is missing." >&2
	exit 1
}

# This is deliberately before the first docker load and before compose up.
npcink_ai_cloud_run_timed "verify exact bundle before load" \
	bash "${RELEASE_VERIFIER}" --pre-load "${ROOT_DIR}"

while IFS=$'\t' read -r image_archive image_role image_reference; do
	[ -n "${image_archive}" ] || continue
	npcink_ai_cloud_run_timed "load ${image_role} image archive" \
		bash -c 'gzip -dc "$1" | docker load' _ "${ROOT_DIR}/${image_archive}"
done < <(python3 "${MANIFEST_HELPER}" load-plan --root "${ROOT_DIR}")

# Worker/callback/ops roles are aliases of the one API image archive. The
# manifest controls the aliases; no role may silently rebuild or load another
# archive.
while IFS=$'\t' read -r source_reference alias_reference; do
	[ -n "${source_reference}" ] || continue
	docker tag "${source_reference}" "${alias_reference}"
done < <(python3 "${MANIFEST_HELPER}" alias-plan --root "${ROOT_DIR}")

npcink_ai_cloud_run_timed "verify loaded image IDs" \
	bash "${RELEASE_VERIFIER}" --post-load "${ROOT_DIR}"

SERVICES=(postgres redis)
if service_exists otel-collector; then
	SERVICES+=(otel-collector)
fi
if service_exists jaeger; then
	SERVICES+=(jaeger)
fi
SERVICES+=(api)
if [ "${SKIP_FRONTEND_IMAGE}" != "1" ]; then
	SERVICES+=(frontend)
fi
SERVICES+=(proxy)
if service_exists caddy; then
	SERVICES+=(caddy)
fi

echo "[info] Starting services: ${SERVICES[*]}"
npcink_ai_cloud_run_timed "compose up services" \
	npcink_ai_cloud_compose "${ROOT_DIR}" up -d --pull never --no-build "${SERVICES[@]}"

if ! npcink_ai_cloud_run_timed "wait for live health" npcink_ai_cloud_wait_for_ready "${BASE_URL}" 20 2; then
	echo "[fail] Cloud API did not become ready at ${BASE_URL}" >&2
	exit 1
fi

echo "[ok] Cloud API is ready at ${BASE_URL}"
