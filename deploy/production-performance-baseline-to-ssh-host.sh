#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"

npcink_ai_cloud_require_cmd ssh

SSH_HOST="${NPCINK_CLOUD_DEPLOY_SSH_HOST:-}"
SSH_USER="${NPCINK_CLOUD_DEPLOY_SSH_USER:-}"
SSH_PORT="${NPCINK_CLOUD_DEPLOY_SSH_PORT:-22}"
SSH_IDENTITY_FILE="${NPCINK_CLOUD_DEPLOY_IDENTITY_FILE:-}"
SSH_CONNECT_TIMEOUT_SECONDS="${NPCINK_CLOUD_DEPLOY_SSH_CONNECT_TIMEOUT_SECONDS:-10}"
REMOTE_DIR="${NPCINK_CLOUD_DEPLOY_REMOTE_DIR:-/opt/npcink-ai-cloud}"

while [ "$#" -gt 0 ]; do
	case "$1" in
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
		*)
			echo "[fail] Unknown argument: $1" >&2
			exit 1
			;;
	esac
done

if [ -z "${SSH_HOST}" ]; then
	echo "[fail] Missing --ssh-host or NPCINK_CLOUD_DEPLOY_SSH_HOST" >&2
	exit 1
fi

if [ -n "${SSH_IDENTITY_FILE}" ] && [ ! -f "${SSH_IDENTITY_FILE}" ]; then
	echo "[fail] SSH identity file not found: ${SSH_IDENTITY_FILE}" >&2
	exit 1
fi

SSH_TARGET="${SSH_HOST}"
if [ -n "${SSH_USER}" ]; then
	SSH_TARGET="${SSH_USER}@${SSH_HOST}"
fi

SSH_ARGS=(
	-p "${SSH_PORT}"
	-o StrictHostKeyChecking=yes
	-o BatchMode=yes
	-o ConnectTimeout="${SSH_CONNECT_TIMEOUT_SECONDS}"
)

if [ -n "${SSH_IDENTITY_FILE}" ]; then
	SSH_ARGS+=(-i "${SSH_IDENTITY_FILE}")
fi

run_remote() {
	local command="$1"
	ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "cd $(printf '%q' "${REMOTE_DIR}/current") && ${command}"
}

echo "[info] Running read-only production performance baseline on ${SSH_TARGET}:${REMOTE_DIR}/current"
run_remote "bash deploy/remote-performance-baseline.sh"
