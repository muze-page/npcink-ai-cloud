#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOCAL_CONFIG="${SCRIPT_DIR}/remote-runtime.local.sh"

if [ -f "${LOCAL_CONFIG}" ]; then
	# shellcheck disable=SC1090
	source "${LOCAL_CONFIG}"
fi

usage() {
	cat <<'EOF'
Usage:
  bash scripts/remote-runtime.sh targets
  bash scripts/remote-runtime.sh config <target>
  bash scripts/remote-runtime.sh doctor <target>
  bash scripts/remote-runtime.sh sync <target>
  bash scripts/remote-runtime.sh up <target>
  bash scripts/remote-runtime.sh down <target>
  bash scripts/remote-runtime.sh ps <target>
  bash scripts/remote-runtime.sh logs <target> [services...]
  bash scripts/remote-runtime.sh restart <target> [services...]
  bash scripts/remote-runtime.sh ssh <target> [remote command...]
  bash scripts/remote-runtime.sh url <target>

Targets:
  mini
    Built-in company Mac mini runtime target.

  dorm
    Dorm runtime target. Configure it in:
      scripts/remote-runtime.local.sh

Purpose:
  Keep the local Cloud repo as the only source of truth.
  Remote machines only receive synced code and run temporary Docker previews.

Default remote workflow:
  1. sync  -> rsync local Cloud repo to the remote Cloud repo
  2. up    -> docker compose -f docker-compose.dev.yml up -d --build
  3. ps    -> inspect service state
  4. logs  -> inspect failures or readiness
  5. url   -> print the preview URL
EOF
}

log() {
	printf '[remote-runtime] %s\n' "$*"
}

fail() {
	printf '[remote-runtime] %s\n' "$*" >&2
	exit 1
}

require_cmd() {
	command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

target_upper() {
	printf '%s' "$1" | tr '[:lower:]-' '[:upper:]_'
}

target_builtin_host() {
	case "$1" in
	mini) printf '%s\n' 'muze@100.102.170.79' ;;
	dorm) printf '%s\n' '' ;;
	*) fail "Unknown target: $1" ;;
	esac
}

target_builtin_root() {
	case "$1" in
mini) printf '%s\n' '/Users/muze/gitee/npcink-ai-cloud' ;;
	dorm) printf '%s\n' '' ;;
	*) fail "Unknown target: $1" ;;
	esac
}

target_builtin_ip() {
	case "$1" in
	mini) printf '%s\n' '100.102.170.79' ;;
	dorm) printf '%s\n' '' ;;
	*) fail "Unknown target: $1" ;;
	esac
}

target_env_or_default() {
	local target="$1"
	local suffix="$2"
	local default_value="$3"
	local upper
	upper="$(target_upper "${target}")"
	local var_name="NPCINK_CLOUD_REMOTE_RUNTIME_${upper}_${suffix}"
	printf '%s\n' "${!var_name:-${default_value}}"
}

target_env_value() {
	local target="$1"
	local suffix="$2"
	local upper
	upper="$(target_upper "${target}")"
	local var_name="NPCINK_CLOUD_REMOTE_RUNTIME_${upper}_${suffix}"
	if [ -n "${!var_name+x}" ]; then
		printf '%s\n' "${!var_name}"
	fi
}

resolve_target() {
	local target="$1"
	case "${target}" in
	mini|dorm) ;;
	*) fail "Unknown target: ${target}" ;;
	esac

	TARGET_NAME="${target}"
	TARGET_HOST="$(target_env_or_default "${target}" HOST "$(target_builtin_host "${target}")")"
	TARGET_REMOTE_ROOT="$(target_env_or_default "${target}" REMOTE_ROOT "$(target_builtin_root "${target}")")"
	TARGET_REMOTE_IP="$(target_env_or_default "${target}" REMOTE_IP "$(target_builtin_ip "${target}")")"
	TARGET_PROJECT_DIR="$(target_env_or_default "${target}" REMOTE_PROJECT_DIR "${TARGET_REMOTE_ROOT}")"
	TARGET_REMOTE_CLOUD_DIR_OVERRIDE="$(target_env_value "${target}" REMOTE_CLOUD_DIR)"
	if [ -n "${TARGET_REMOTE_CLOUD_DIR_OVERRIDE}" ]; then
		TARGET_CLOUD_DIR="${TARGET_REMOTE_CLOUD_DIR_OVERRIDE}"
	else
		TARGET_CLOUD_DIR="${TARGET_REMOTE_ROOT}"
	fi
	TARGET_LOCAL_CLOUD_DIR="$(target_env_or_default "${target}" LOCAL_CLOUD_DIR "${WORKSPACE_ROOT}")"
	TARGET_BROWSER_PORT="$(target_env_or_default "${target}" BROWSER_PORT "8010")"
	TARGET_COMPOSE_FILE="$(target_env_or_default "${target}" COMPOSE_FILE "docker-compose.dev.yml")"
	TARGET_BROWSER_URL="$(target_env_or_default "${target}" BROWSER_BASE_URL "http://${TARGET_REMOTE_IP}:${TARGET_BROWSER_PORT}")"

	[ -n "${TARGET_HOST}" ] || fail "Target '${target}' is not configured. Fill scripts/remote-runtime.local.sh first."
	[ -n "${TARGET_REMOTE_ROOT}" ] || fail "Target '${target}' is missing REMOTE_ROOT."
	[ -n "${TARGET_REMOTE_IP}" ] || fail "Target '${target}' is missing REMOTE_IP."
}

ssh_exec() {
	local script="$1"
	ssh -o BatchMode=yes -o ConnectTimeout=8 "${TARGET_HOST}" "bash -lc $(printf '%q' "${script}")"
}

ensure_target_remote_cloud_dir() {
	if [ -n "${TARGET_REMOTE_CLOUD_DIR_OVERRIDE:-}" ]; then
		TARGET_CLOUD_DIR="${TARGET_REMOTE_CLOUD_DIR_OVERRIDE}"
		return 0
	fi

	TARGET_CLOUD_DIR="${TARGET_REMOTE_ROOT}"
}

remote_cloud_exec() {
	local script="$1"
	ensure_target_remote_cloud_dir
	ssh_exec "
set -euo pipefail
cd $(printf '%q' "${TARGET_CLOUD_DIR}")
${script}
"
}

doctor_target() {
	require_cmd ssh
	require_cmd rsync
	require_cmd tailscale
	log "Checking ${TARGET_NAME} via Tailscale and SSH"
	tailscale ping -c 1 "${TARGET_REMOTE_IP}" || fail "Tailscale ping failed: ${TARGET_REMOTE_IP}"
	ssh -o BatchMode=yes -o ConnectTimeout=8 "${TARGET_HOST}" "printf 'host=%s\npwd=%s\n' \"\$(hostname)\" \"\$(pwd)\"" \
		|| fail "SSH unavailable: ${TARGET_HOST}"
}

sync_target() {
	require_cmd rsync
	require_cmd ssh
	ensure_target_remote_cloud_dir
	log "Syncing local Cloud repo to ${TARGET_HOST}:${TARGET_CLOUD_DIR}"
	rsync -az \
		--delete \
		--exclude '.env' \
		--exclude '.env.local' \
		--exclude '.next' \
		--exclude 'frontend/.next' \
		--exclude 'frontend/node_modules' \
		--exclude 'node_modules' \
		--exclude '.pytest_cache' \
		--exclude '.runtime' \
		--exclude '__pycache__' \
		"${TARGET_LOCAL_CLOUD_DIR}/" \
		"${TARGET_HOST}:${TARGET_CLOUD_DIR}/"
}

up_target() {
	log "Starting remote cloud stack on ${TARGET_NAME}"
	remote_cloud_exec "docker compose -f ${TARGET_COMPOSE_FILE} up -d --build"
}

down_target() {
	log "Stopping remote cloud stack on ${TARGET_NAME}"
	remote_cloud_exec "docker compose -f ${TARGET_COMPOSE_FILE} down"
}

ps_target() {
	remote_cloud_exec "docker compose -f ${TARGET_COMPOSE_FILE} ps"
}

logs_target() {
	local services=("$@")
	local service_args=""
	if [ "${#services[@]}" -gt 0 ]; then
		service_args=" ${services[*]}"
	fi
	remote_cloud_exec "docker compose -f ${TARGET_COMPOSE_FILE} logs --tail=120${service_args}"
}

restart_target() {
	local services=("$@")
	[ "${#services[@]}" -gt 0 ] || fail "restart requires at least one service name"
	remote_cloud_exec "docker compose -f ${TARGET_COMPOSE_FILE} restart ${services[*]}"
}

config_target() {
	if command -v ssh >/dev/null 2>&1; then
		ensure_target_remote_cloud_dir
	fi

	cat <<EOF
target=${TARGET_NAME}
host=${TARGET_HOST}
remote_ip=${TARGET_REMOTE_IP}
remote_root=${TARGET_REMOTE_ROOT}
remote_project_dir=${TARGET_PROJECT_DIR}
remote_cloud_dir=${TARGET_CLOUD_DIR}
local_cloud_dir=${TARGET_LOCAL_CLOUD_DIR}
compose_file=${TARGET_COMPOSE_FILE}
browser_url=${TARGET_BROWSER_URL}
EOF
}

COMMAND="${1:-}"
case "${COMMAND}" in
targets)
		printf '%s\n' 'mini'
		printf '%s\n' 'dorm'
		exit 0
		;;
	config|doctor|sync|up|down|ps|logs|restart|ssh|url)
		;;
	''|-h|--help|help)
		usage
		exit 0
		;;
	*)
		usage >&2
		exit 2
		;;
esac

TARGET="${2:-}"
[ -n "${TARGET}" ] || fail "Missing target"
resolve_target "${TARGET}"

case "${COMMAND}" in
config)
		config_target
		;;
	doctor)
		doctor_target
		;;
	sync)
		sync_target
		;;
	up)
		up_target
		;;
	down)
		down_target
		;;
	ps)
		ps_target
		;;
	logs)
		shift 2
		logs_target "$@"
		;;
	restart)
		shift 2
		restart_target "$@"
		;;
	ssh)
		shift 2
		if [ "$#" -eq 0 ]; then
			exec ssh "${TARGET_HOST}"
		fi
		exec ssh "${TARGET_HOST}" "$@"
		;;
	url)
		printf '%s\n' "${TARGET_BROWSER_URL}"
		;;
esac
