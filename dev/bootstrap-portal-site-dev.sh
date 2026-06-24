#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

ARGS=()
for arg in "$@"; do
	if [ "${arg}" = "--" ]; then
		continue
	fi
	if [ "${arg}" = "--member-email" ]; then
		ARGS+=("--site-admin-email")
		continue
	fi
	ARGS+=("${arg}")
done

cd "${ROOT_DIR}"
COMPOSE_PROJECT_NAME="${NPCINK_CLOUD_COMPOSE_PROJECT_NAME:-${COMPOSE_PROJECT_NAME:-npcink-ai-cloud}}" \
	docker compose -f docker-compose.dev.yml run --rm api \
	python -m app.dev.bootstrap_portal_site "${ARGS[@]}"
