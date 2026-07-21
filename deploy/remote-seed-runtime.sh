#!/usr/bin/env bash
set -euo pipefail
set +x

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# Shared compose/env helpers for deploy scripts.
. "${ROOT_DIR}/deploy/common.sh"

SITE_ID="${NPCINK_CLOUD_SITE_ID:-site_smoke}"
KEY_ID="${NPCINK_CLOUD_KEY_ID:-key_default}"
SECRET="${NPCINK_CLOUD_SECRET:-}"
export -n SECRET
SITE_NAME="${NPCINK_CLOUD_SITE_NAME:-}"
SCOPES="${NPCINK_CLOUD_SCOPES:-catalog:read,runtime:resolve,runtime:execute,runtime:read,stats:read}"
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
			echo "[fail] --secret is forbidden because process arguments are observable; use NPCINK_CLOUD_SECRET from a protected process environment." >&2
			exit 1
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

if [ -z "${SECRET}" ]; then
	echo "[fail] NPCINK_CLOUD_SECRET is required for runtime seeding." >&2
	exit 1
fi

# Keep the original production secret out of child environments while the
# release manifest is verified. The purpose-specific value is exported only
# when the governed one-off helper is ready to consume its variable name.
unset NPCINK_CLOUD_SECRET
npcink_ai_cloud_require_cmd docker
RELEASE_TOOL_PYTHON="$(npcink_ai_cloud_release_tool_python)"
MANIFEST_HELPER="${ROOT_DIR}/scripts/verify-release-bundle-manifest.py"
npcink_ai_cloud_require_release_tool_python "${RELEASE_TOOL_PYTHON}"
EXPECTED_API_IMAGE_ID="$(
	"${RELEASE_TOOL_PYTHON}" "${MANIFEST_HELPER}" loaded-role-daemon-id \
		--root "${ROOT_DIR}" --role api
)"

# The host-side value is copied to a short-lived, purpose-specific container
# environment variable. Docker and Python argv contain only its variable name.
export NPCINK_CLOUD_SEED_RUNTIME_SECRET="${SECRET}"
unset SECRET

SEED_ARGS=(
	python -
	--site-id "${SITE_ID}"
	--key-id "${KEY_ID}"
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

seed_status=0
npcink_ai_cloud_compose_run_with_image_proof \
	"${ROOT_DIR}" api npcink-ai-cloud-api:prod "${EXPECTED_API_IMAGE_ID}" \
	--exec-env NPCINK_CLOUD_SEED_RUNTIME_SECRET -- \
	"${SEED_ARGS[@]}" <<'PY' || seed_status=$?
from __future__ import annotations

import os
import sys

from app.dev.seed_runtime import main

secret = os.environ.pop("NPCINK_CLOUD_SEED_RUNTIME_SECRET", "")
if not secret:
    raise SystemExit("[fail] Runtime seed secret is missing.")
sys.argv.extend(("--secret", secret))
main()
PY
if ! unset NPCINK_CLOUD_SEED_RUNTIME_SECRET; then
	echo "[fail] Runtime seed secret cleanup failed." >&2
	exit 1
fi
exit "${seed_status}"
