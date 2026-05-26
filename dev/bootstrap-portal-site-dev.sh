#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

ARGS=()
for arg in "$@"; do
	if [ "${arg}" = "--" ]; then
		continue
	fi
	ARGS+=("${arg}")
done

cd "${ROOT_DIR}/.."
docker compose -f cloud/docker-compose.dev.yml run --rm api \
	python -m app.dev.bootstrap_portal_site "${ARGS[@]}"
