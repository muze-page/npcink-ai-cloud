#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "${ROOT_DIR}/deploy/common.sh"

npcink_ai_cloud_require_cmd bash
npcink_ai_cloud_require_cmd ssh

SSH_HOST="${NPCINK_CLOUD_DEPLOY_SSH_HOST:-}"
SSH_USER="${NPCINK_CLOUD_DEPLOY_SSH_USER:-}"
SSH_PORT="${NPCINK_CLOUD_DEPLOY_SSH_PORT:-22}"
SSH_IDENTITY_FILE="${NPCINK_CLOUD_DEPLOY_IDENTITY_FILE:-}"
REMOTE_DIR="${NPCINK_CLOUD_DEPLOY_REMOTE_DIR:-/opt/npcink-ai-cloud}"
DEFAULT_BASE_URL="${NPCINK_CLOUD_BASE_URL:-}"
declare -a REMOTE_ARGS=()
HAS_BASE_URL_ARG=0

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
		--base-url)
			HAS_BASE_URL_ARG=1
			REMOTE_ARGS+=("$1" "$2")
			shift 2
			;;
		--secret)
			echo "[fail] --secret is forbidden because process arguments and the SSH command are observable." >&2
			exit 1
			;;
		--issue-key)
			echo "[fail] Remote portal bootstrap does not support --issue-key; provision keys through a governed local or release path." >&2
			exit 1
			;;
		*)
			REMOTE_ARGS+=("$1")
			shift
			;;
	esac
done

if [ -z "${SSH_HOST}" ]; then
	echo "[fail] Missing --ssh-host or NPCINK_CLOUD_DEPLOY_SSH_HOST" >&2
	exit 1
fi

if [ "${HAS_BASE_URL_ARG}" -eq 0 ] && [ -n "${DEFAULT_BASE_URL}" ]; then
	REMOTE_ARGS+=(--base-url "${DEFAULT_BASE_URL}")
fi

SSH_TARGET="${SSH_HOST}"
if [ -n "${SSH_USER}" ]; then
	SSH_TARGET="${SSH_USER}@${SSH_HOST}"
fi

SSH_ARGS=(
	-p "${SSH_PORT}"
	-o StrictHostKeyChecking=yes
)
if [ -n "${SSH_IDENTITY_FILE}" ]; then
	SSH_ARGS+=(-i "${SSH_IDENTITY_FILE}")
fi

REMOTE_CMD="cd $(printf '%q' "${REMOTE_DIR}/current") && bash deploy/remote-bootstrap-portal-site.sh"
if [ "${#REMOTE_ARGS[@]}" -gt 0 ]; then
	for value in "${REMOTE_ARGS[@]}"; do
		REMOTE_CMD+=" $(printf '%q' "${value}")"
	done
fi

echo "[info] Running remote real-site portal bootstrap on ${SSH_TARGET}:${REMOTE_DIR}/current"
ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "${REMOTE_CMD}"
