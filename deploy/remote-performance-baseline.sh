#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"
npcink_ai_cloud_load_env_file "${ROOT_DIR}"

npcink_ai_cloud_require_cmd docker

BASELINE_ARGS=(
	--format json
	--require-indexes
	--base-url "${NPCINK_CLOUD_BASE_URL:-http://127.0.0.1:${NPCINK_CLOUD_PORT:-8010}}"
	--site-id "${NPCINK_CLOUD_SITE_ID:-site_smoke}"
)

if [ "${NPCINK_CLOUD_PRODUCTION_PERF_ANALYZE:-0}" = "1" ]; then
	BASELINE_ARGS+=(--explain-analyze)
fi

if [ "${NPCINK_CLOUD_PRODUCTION_PERF_REQUIRE_PLAN_INDEX_USE:-0}" = "1" ]; then
	BASELINE_ARGS+=(--require-plan-index-use)
fi

if [ "${NPCINK_CLOUD_PRODUCTION_PERF_SKIP_HTTP:-0}" = "1" ]; then
	BASELINE_ARGS+=(--skip-http)
fi

npcink_ai_cloud_compose "${ROOT_DIR}" exec -T api \
	python scripts/production_performance_baseline.py "${BASELINE_ARGS[@]}"
