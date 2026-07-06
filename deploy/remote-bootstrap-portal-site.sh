#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"
npcink_ai_cloud_load_env_file "${ROOT_DIR}"

npcink_ai_cloud_require_cmd docker

BASE_URL="${NPCINK_CLOUD_BASE_URL:-http://127.0.0.1:${NPCINK_CLOUD_PORT:-8010}}"
SITE_ID="${NPCINK_CLOUD_SITE_ID:-}"
MEMBER_EMAIL="${NPCINK_CLOUD_MEMBER_EMAIL:-}"
MEMBER_ROLE="${NPCINK_CLOUD_MEMBER_ROLE:-user_admin}"
ISSUE_KEY=0
KEY_ID="${NPCINK_CLOUD_KEY_ID:-}"
SECRET="${NPCINK_CLOUD_SECRET:-}"
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
		--member-role)
			MEMBER_ROLE="$2"
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
			SECRET="$2"
			shift 2
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

BOOTSTRAP_ARGS=(
	python -m app.dev.bootstrap_portal_site
	--site-id "${SITE_ID}"
	--member-email "${MEMBER_EMAIL}"
	--member-role "${MEMBER_ROLE}"
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
if [ -n "${SECRET}" ]; then
	BOOTSTRAP_ARGS+=(--secret "${SECRET}")
fi

npcink_ai_cloud_compose "${ROOT_DIR}" run --rm api "${BOOTSTRAP_ARGS[@]}"
