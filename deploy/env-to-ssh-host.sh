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
BASE_URL="${NPCINK_CLOUD_BASE_URL:-http://127.0.0.1:${NPCINK_CLOUD_PORT:-8010}}"
RESTART_AFTER_UPDATE=1
RESTART_SERVICES="proxy,api,worker,callback-worker,ops-worker"
declare -a SET_ENTRIES=()
declare -a UNSET_KEYS=()
declare -a FROM_ENV_KEYS=()

validate_key() {
	local key="$1"
	case "${key}" in
		NPCINK_CLOUD_[A-Z0-9_]*)
			return 0
			;;
		*)
			echo "[fail] Invalid env key: ${key}" >&2
			exit 1
			;;
	esac
}

append_remote_quoted_arg() {
	local value="$1"
	printf ' %q' "${value}"
}

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
		--base-url)
			BASE_URL="$2"
			shift 2
			;;
		--set)
			SET_ENTRIES+=("$2")
			shift 2
			;;
		--unset)
			UNSET_KEYS+=("$2")
			shift 2
			;;
		--from-env)
			FROM_ENV_KEYS+=("$2")
			shift 2
			;;
		--restart-services)
			RESTART_SERVICES="$2"
			shift 2
			;;
		--no-restart)
			RESTART_AFTER_UPDATE=0
			shift
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

if [ "${#FROM_ENV_KEYS[@]}" -gt 0 ]; then
	for key in "${FROM_ENV_KEYS[@]}"; do
		validate_key "${key}"
		if [ -z "${!key+x}" ]; then
			echo "[fail] Local environment variable is unset: ${key}" >&2
			exit 1
		fi
		SET_ENTRIES+=("${key}=${!key}")
	done
fi

if [ "${#SET_ENTRIES[@]}" -eq 0 ] && [ "${#UNSET_KEYS[@]}" -eq 0 ]; then
	echo "[fail] Nothing to update; pass --set, --unset, or --from-env" >&2
	exit 1
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

REMOTE_CMD="cd $(printf '%q' "${REMOTE_DIR}/current") && bash -s --"
REMOTE_ARGS=(
	--shared-env-path "${REMOTE_DIR}/.env.deploy"
	--base-url "${BASE_URL}"
)
if [ "${RESTART_AFTER_UPDATE}" -eq 0 ]; then
	REMOTE_ARGS+=(--no-restart)
else
	REMOTE_ARGS+=(--restart-services "${RESTART_SERVICES}")
fi

if [ "${#SET_ENTRIES[@]}" -gt 0 ]; then
	for entry in "${SET_ENTRIES[@]}"; do
		key="${entry%%=*}"
		validate_key "${key}"
		REMOTE_ARGS+=(--set "${entry}")
	done
fi
if [ "${#UNSET_KEYS[@]}" -gt 0 ]; then
	for key in "${UNSET_KEYS[@]}"; do
		validate_key "${key}"
		REMOTE_ARGS+=(--unset "${key}")
	done
fi

for value in "${REMOTE_ARGS[@]}"; do
	REMOTE_CMD+=$(append_remote_quoted_arg "${value}")
done

echo "[info] Updating remote env on ${SSH_TARGET}:${REMOTE_DIR}"
ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "${REMOTE_CMD}" < "${ROOT_DIR}/deploy/remote-env-upsert.sh"
