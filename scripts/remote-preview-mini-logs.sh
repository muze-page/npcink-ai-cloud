#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "${ROOT_DIR}/scripts/mini-cloud-env.sh"
REMOTE_HOST="${REMOTE_HOST:-${MINI_CLOUD_REMOTE_HOST}}"
REMOTE_ROOT="${REMOTE_ROOT:-${MINI_CLOUD_REMOTE_ROOT}}"
REMOTE_PROJECT_DIR="${REMOTE_PROJECT_DIR:-${MINI_CLOUD_REMOTE_PROJECT_DIR}}"
REMOTE_CLOUD_DIR_SCRIPT="\$HOME${REMOTE_PROJECT_DIR#\~}"
TAIL_LINES="${TAIL_LINES:-200}"
FOLLOW=0

usage() {
	cat <<'EOF'
Usage: scripts/remote-preview-mini-logs.sh [--follow] [--tail N] [service...]

Show logs from the remote cloud dev portal stack on the Mac mini.
Examples:
  scripts/remote-preview-mini-logs.sh
  scripts/remote-preview-mini-logs.sh --tail 80 frontend
  scripts/remote-preview-mini-logs.sh --follow api worker
EOF
}

SERVICES=()
while [ "$#" -gt 0 ]; do
	case "$1" in
		--)
			shift
			;;
		--help|-h)
			usage
			exit 0
			;;
		--follow|-f)
			FOLLOW=1
			shift
			;;
		--tail)
			TAIL_LINES="$2"
			shift 2
			;;
		*)
			SERVICES+=("$1")
			shift
			;;
	esac
done

FOLLOW_FLAG=""
if [ "${FOLLOW}" = "1" ]; then
	FOLLOW_FLAG="-f"
fi

SERVICE_ARGS="${SERVICES[*]:-}"

ssh "${REMOTE_HOST}" "bash -lc $(printf '%q' "
set -euo pipefail
cd ${REMOTE_CLOUD_DIR_SCRIPT}
docker compose -f docker-compose.dev.yml -f docker-compose.remote-preview.yml logs ${FOLLOW_FLAG} --tail ${TAIL_LINES} ${SERVICE_ARGS}
")"
