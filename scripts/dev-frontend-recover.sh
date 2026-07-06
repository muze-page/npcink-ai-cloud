#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${NPCINK_CLOUD_DEV_COMPOSE_FILE:-docker-compose.dev.yml}"

cd "${ROOT_DIR}"

project_name="$(
	docker compose -f "${COMPOSE_FILE}" config --format json \
		| python3 -c 'import json,sys; print(json.load(sys.stdin).get("name") or "")'
)"

echo "[frontend-recover] Recreating frontend and proxy with fresh container-owned frontend dependencies"
docker compose -f "${COMPOSE_FILE}" stop frontend proxy >/dev/null 2>&1 || true
docker compose -f "${COMPOSE_FILE}" rm -f frontend proxy >/dev/null 2>&1 || true
if [ -n "${project_name}" ]; then
	docker volume rm "${project_name}_cloud-frontend-node-modules-dev" >/dev/null 2>&1 || true
	docker volume rm "${project_name}_cloud-frontend-next-cache-dev" >/dev/null 2>&1 || true
fi
docker compose -f "${COMPOSE_FILE}" up -d --build --force-recreate frontend proxy
echo "[frontend-recover] Running frontend doctor"
bash scripts/dev-frontend-doctor.sh
