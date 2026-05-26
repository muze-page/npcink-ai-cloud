#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# Shared compose/env helpers for deploy scripts.
. "${ROOT_DIR}/deploy/common.sh"

SITE_ID="${MAGICK_CLOUD_SITE_ID:-site_smoke}"
KEY_ID="${MAGICK_CLOUD_KEY_ID:-key_default}"
SECRET="${MAGICK_CLOUD_SECRET:-magick-cloud-test-secret}"
SITE_NAME="${MAGICK_CLOUD_SITE_NAME:-}"
SCOPES="${MAGICK_CLOUD_SCOPES:-catalog:read,runtime:resolve,runtime:execute,runtime:read,stats:read}"
SKIP_CATALOG_REFRESH=0
SKIP_HEALTH_SCAN=0

while [ "$#" -gt 0 ]; do
	case "$1" in
		--site-id)
			SITE_ID="$2"
			shift 2
			;;
		--key-id)
			KEY_ID="$2"
			shift 2
			;;
		--secret)
			SECRET="$2"
			shift 2
			;;
		--site-name)
			SITE_NAME="$2"
			shift 2
			;;
		--scopes)
			SCOPES="$2"
			shift 2
			;;
		--skip-catalog-refresh)
			SKIP_CATALOG_REFRESH=1
			shift
			;;
		--skip-health-scan)
			SKIP_HEALTH_SCAN=1
			shift
			;;
		*)
			echo "[fail] Unknown argument: $1" >&2
			exit 1
			;;
	esac
done

magick_ai_cloud_require_cmd docker

SEED_ARGS=(
	python -m app.dev.seed_runtime
	--site-id "${SITE_ID}"
	--key-id "${KEY_ID}"
	--secret "${SECRET}"
	--scopes "${SCOPES}"
)

if [ -n "${SITE_NAME}" ]; then
	SEED_ARGS+=(--site-name "${SITE_NAME}")
fi
if [ "${SKIP_CATALOG_REFRESH}" -eq 1 ]; then
	SEED_ARGS+=(--skip-catalog-refresh)
fi
if [ "${SKIP_HEALTH_SCAN}" -eq 1 ]; then
	SEED_ARGS+=(--skip-health-scan)
fi

magick_ai_cloud_compose "${ROOT_DIR}" run --rm api "${SEED_ARGS[@]}"
