#!/usr/bin/env bash
set -euo pipefail
set +x

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"
npcink_ai_cloud_load_env_file "${ROOT_DIR}"

BASE_URL="${NPCINK_CLOUD_BASE_URL:-http://127.0.0.1:${NPCINK_CLOUD_PORT:-8010}}"
SITE_ID="${NPCINK_CLOUD_SITE_ID:-}"
MEMBER_EMAIL="${NPCINK_CLOUD_MEMBER_EMAIL:-}"
ISSUE_KEY=0
KEY_ID="${NPCINK_CLOUD_KEY_ID:-}"
SECRET="${NPCINK_CLOUD_SECRET:-}"
export -n SECRET
KEY_LABEL="Portal bootstrap key"
SCOPES="${NPCINK_CLOUD_SCOPES:-catalog:read,runtime:resolve,runtime:execute,runtime:read,stats:read}"
SKIP_BILLING_REBUILD=0

while [ "$#" -gt 0 ]; do
	case "$1" in
		--base-url)
			BASE_URL="$2"
			shift 2
			;;
		--site-id)
			SITE_ID="$2"
			shift 2
			;;
		--member-email)
			MEMBER_EMAIL="$2"
			shift 2
			;;
		--issue-key)
			ISSUE_KEY=1
			shift
			;;
		--key-id)
			KEY_ID="$2"
			shift 2
			;;
		--secret)
			echo "[fail] --secret is forbidden because process arguments are observable; use NPCINK_CLOUD_SECRET from a protected process environment." >&2
			exit 1
			;;
		--key-label)
			KEY_LABEL="$2"
			shift 2
			;;
		--scopes)
			SCOPES="$2"
			shift 2
			;;
		--skip-billing-rebuild)
			SKIP_BILLING_REBUILD=1
			shift
			;;
		*)
			echo "[fail] Unknown argument: $1" >&2
			exit 1
			;;
	esac
done

if [ -z "${SITE_ID}" ]; then
	echo "[fail] --site-id or NPCINK_CLOUD_SITE_ID is required" >&2
	exit 1
fi

if [ -z "${MEMBER_EMAIL}" ]; then
	echo "[fail] --member-email or NPCINK_CLOUD_MEMBER_EMAIL is required" >&2
	exit 1
fi
if [ "${ISSUE_KEY}" -eq 1 ] && [ -z "${SECRET}" ]; then
	echo "[fail] NPCINK_CLOUD_SECRET is required with --issue-key so the issued key is recoverable." >&2
	exit 1
fi

# Resolve the immutable API identity without leaking an optional bootstrap
# secret into the manifest verifier's environment.
unset NPCINK_CLOUD_SECRET
npcink_ai_cloud_require_cmd docker
RELEASE_TOOL_PYTHON="$(npcink_ai_cloud_release_tool_python)"
MANIFEST_HELPER="${ROOT_DIR}/scripts/verify-release-bundle-manifest.py"
npcink_ai_cloud_require_release_tool_python "${RELEASE_TOOL_PYTHON}"
EXPECTED_API_IMAGE_ID="$(
	"${RELEASE_TOOL_PYTHON}" "${MANIFEST_HELPER}" loaded-role-daemon-id \
		--root "${ROOT_DIR}" --role api
)"

BOOTSTRAP_ARGS=(
	python -
	--site-id "${SITE_ID}"
	--site-admin-email "${MEMBER_EMAIL}"
	--public-base-url "${BASE_URL}"
	--key-label "${KEY_LABEL}"
	--scopes "${SCOPES}"
)

if [ "${SKIP_BILLING_REBUILD}" -eq 1 ]; then
	BOOTSTRAP_ARGS+=(--skip-billing-rebuild)
fi
if [ "${ISSUE_KEY}" -eq 1 ]; then
	BOOTSTRAP_ARGS+=(--issue-key)
fi
if [ -n "${KEY_ID}" ]; then
	BOOTSTRAP_ARGS+=(--key-id "${KEY_ID}")
fi
HAS_BOOTSTRAP_SECRET=0
unset NPCINK_CLOUD_BOOTSTRAP_SITE_SECRET
if [ -n "${SECRET}" ]; then
	export NPCINK_CLOUD_BOOTSTRAP_SITE_SECRET="${SECRET}"
	HAS_BOOTSTRAP_SECRET=1
fi
unset SECRET

bootstrap_status=0
if [ "${HAS_BOOTSTRAP_SECRET}" -eq 1 ]; then
	npcink_ai_cloud_compose_run_with_image_proof \
		"${ROOT_DIR}" api npcink-ai-cloud-api:prod "${EXPECTED_API_IMAGE_ID}" \
		--exec-env NPCINK_CLOUD_BOOTSTRAP_SITE_SECRET -- \
		"${BOOTSTRAP_ARGS[@]}" <<'PY' || bootstrap_status=$?
from __future__ import annotations

import os
import sys

from app.dev.bootstrap_portal_site import main

secret = os.environ.pop("NPCINK_CLOUD_BOOTSTRAP_SITE_SECRET", "")
if secret:
    sys.argv.extend(("--secret", secret))
main()
PY
else
	npcink_ai_cloud_compose_run_with_image_proof \
		"${ROOT_DIR}" api npcink-ai-cloud-api:prod "${EXPECTED_API_IMAGE_ID}" \
		-- "${BOOTSTRAP_ARGS[@]}" <<'PY' || bootstrap_status=$?
from __future__ import annotations

from app.dev.bootstrap_portal_site import main

main()
PY
fi
if ! unset NPCINK_CLOUD_BOOTSTRAP_SITE_SECRET; then
	echo "[fail] Portal bootstrap secret cleanup failed." >&2
	exit 1
fi
exit "${bootstrap_status}"
