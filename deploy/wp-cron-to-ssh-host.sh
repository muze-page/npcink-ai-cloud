#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "${ROOT_DIR}/deploy/common.sh"

magick_ai_cloud_require_cmd ssh

SSH_HOST="${MAGICK_CLOUD_DEPLOY_SSH_HOST:-}"
SSH_USER="${MAGICK_CLOUD_DEPLOY_SSH_USER:-}"
SSH_PORT="${MAGICK_CLOUD_DEPLOY_SSH_PORT:-22}"
SSH_IDENTITY_FILE="${MAGICK_CLOUD_DEPLOY_IDENTITY_FILE:-}"
REMOTE_DIR="${MAGICK_CLOUD_DEPLOY_REMOTE_DIR:-/opt/magick-ai-cloud}"
DEFAULT_SITE_URL="${MAGICK_CLOUD_WP_CRON_SITE_BASE_URL:-}"
declare -a REMOTE_ARGS=()
HAS_SITE_URL_ARG=0

while [ "$#" -gt 0 ]; do
	case "$1" in
		--)
			shift
			;;
		--ssh-host)
			SSH_HOST="$2"
			shift 2
			;;
		--ssh-user)
			SSH_USER="$2"
			shift 2
			;;
		--ssh-port)
			SSH_PORT="$2"
			shift 2
			;;
		--identity-file)
			SSH_IDENTITY_FILE="$2"
			shift 2
			;;
		--remote-dir)
			REMOTE_DIR="$2"
			shift 2
			;;
		--site-url)
			HAS_SITE_URL_ARG=1
			REMOTE_ARGS+=("$1" "$2")
			shift 2
			;;
		*)
			REMOTE_ARGS+=("$1")
			shift
			;;
	esac
done

if [ -z "${SSH_HOST}" ]; then
	echo "[fail] Missing --ssh-host or MAGICK_CLOUD_DEPLOY_SSH_HOST" >&2
	exit 1
fi

if [ "${HAS_SITE_URL_ARG}" -eq 0 ] && [ -n "${DEFAULT_SITE_URL}" ]; then
	REMOTE_ARGS+=(--site-url "${DEFAULT_SITE_URL}")
fi

SSH_TARGET="${SSH_HOST}"
if [ -n "${SSH_USER}" ]; then
	SSH_TARGET="${SSH_USER}@${SSH_HOST}"
fi

SSH_ARGS=(
	-p "${SSH_PORT}"
	-o StrictHostKeyChecking=accept-new
)
if [ -n "${SSH_IDENTITY_FILE}" ]; then
	SSH_ARGS+=(-i "${SSH_IDENTITY_FILE}")
fi

REMOTE_CMD="cd $(printf '%q' "${REMOTE_DIR}/current") && bash -s --"
if [ "${#REMOTE_ARGS[@]}" -gt 0 ]; then
	for value in "${REMOTE_ARGS[@]}"; do
		REMOTE_CMD+=" $(printf '%q' "${value}")"
	done
fi

echo "[info] Running remote WordPress cron helper on ${SSH_TARGET}:${REMOTE_DIR}/current"
ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "${REMOTE_CMD}" < "${ROOT_DIR}/deploy/remote-wp-cron.sh"
