#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
COMPOSE_FILE="${NPCINK_CLOUD_DEV_COMPOSE_FILE:-${ROOT_DIR}/docker-compose.dev.yml}"
compose_args=(compose)

for env_file in "${ROOT_DIR}/.env" "${ROOT_DIR}/.env.local"; do
	if [ -f "${env_file}" ]; then
		compose_args+=(--env-file "${env_file}")
	fi
done

cd "${ROOT_DIR}"
exec docker "${compose_args[@]}" -f "${COMPOSE_FILE}" "$@"
