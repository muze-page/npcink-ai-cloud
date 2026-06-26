#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${NPCINK_CLOUD_DEV_COMPOSE_FILE:-docker-compose.dev.yml}"
BASE_URL="${NPCINK_CLOUD_FRONTEND_BASE_URL:-http://127.0.0.1:8010}"
RECOVER_CMD="bash scripts/dev-frontend-recover.sh"

cd "${ROOT_DIR}"

fail() {
	echo "[frontend-doctor] ERROR: $*" >&2
	echo "[frontend-doctor] Recovery: ${RECOVER_CMD}" >&2
	exit 1
}

info() {
	echo "[frontend-doctor] $*"
}

wait_for_health() {
	local url="$1"
	local attempt
	for attempt in $(seq 1 30); do
		if curl -fsS --max-time 10 "${url}" >/dev/null 2>&1; then
			return 0
		fi
		sleep 2
	done
	return 1
}

wait_for_home() {
	local url="$1"
	local attempt
	for attempt in $(seq 1 30); do
		home_body="$(curl -fsS --max-time 20 "${url}" 2>/dev/null || true)"
		if printf '%s' "${home_body}" | grep -q "Npcink AI Cloud"; then
			return 0
		fi
		sleep 2
	done
	return 1
}

wait_for_admin_route() {
	local url="$1"
	local status
	local attempt
	for attempt in $(seq 1 30); do
		status="$(curl -sS -o /dev/null -w "%{http_code}" --max-time 20 "${url}" 2>/dev/null || true)"
		case "${status}" in
			200|301|302|303|307|308) return 0 ;;
		esac
		sleep 2
	done
	echo "${status:-unknown}"
	return 1
}

command -v docker >/dev/null 2>&1 || fail "docker is not installed or not on PATH"
docker compose -f "${COMPOSE_FILE}" ps >/dev/null 2>&1 || fail "dev compose stack is unavailable"

frontend_status="$(
	docker compose -f "${COMPOSE_FILE}" ps --format json frontend 2>/dev/null \
		| python3 -c 'import json,sys; rows=[json.loads(line) for line in sys.stdin if line.strip()]; print(rows[0].get("State","") if rows else "")'
)"
if [ "${frontend_status}" != "running" ]; then
	fail "frontend container is not running"
fi

proxy_status="$(
	docker compose -f "${COMPOSE_FILE}" ps --format json proxy 2>/dev/null \
		| python3 -c 'import json,sys; rows=[json.loads(line) for line in sys.stdin if line.strip()]; print(rows[0].get("State","") if rows else "")'
)"
if [ "${proxy_status}" != "running" ]; then
	fail "proxy container is not running"
fi

info "checking frontend container dependencies"
docker compose -f "${COMPOSE_FILE}" exec -T frontend sh -lc '
	set -eu
	test -d /app/node_modules || { echo "/app/node_modules is missing"; exit 1; }
	test -d /app/node_modules/.pnpm || { echo "/app/node_modules/.pnpm is missing"; exit 1; }
	count="$(find /app/node_modules/.pnpm -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d " ")"
	[ "${count}" -gt 20 ] || { echo "/app/node_modules/.pnpm has too few packages: ${count}"; exit 1; }
	node - <<'"'"'NODE'"'"'
const required = [
  "@swc/helpers/package.json",
  "next/package.json",
  "next/dist/build/webpack/loaders/next-flight-client-entry-loader",
  "next/dist/build/webpack/loaders/next-app-loader",
  "next/dist/build/webpack/loaders/next-middleware-loader",
];
for (const id of required) {
  require.resolve(id);
}
NODE
' || fail "frontend container dependencies are incomplete"

info "checking API live health through proxy"
wait_for_health "${BASE_URL}/health/live" \
	|| fail "health endpoint is not reachable at ${BASE_URL}/health/live"

info "checking frontend home page through proxy"
if ! wait_for_home "${BASE_URL}/"; then
	fail "home page did not render expected frontend content"
fi

info "checking admin route reaches frontend"
admin_status="$(wait_for_admin_route "${BASE_URL}/admin/ai-resources")" \
	|| fail "admin route returned unexpected HTTP status ${admin_status}"

info "ok"
