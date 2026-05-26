#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "${ROOT_DIR}/scripts/mini-cloud-env.sh"
REMOTE_HOST="${REMOTE_HOST:-${MINI_CLOUD_REMOTE_HOST}}"
REMOTE_ROOT="${REMOTE_ROOT:-${MINI_CLOUD_REMOTE_ROOT}}"
REMOTE_PROJECT_DIR="${REMOTE_PROJECT_DIR:-${MINI_CLOUD_REMOTE_PROJECT_DIR}}"
REMOTE_CLOUD_DIR_SCRIPT="\$HOME${REMOTE_PROJECT_DIR#\~}"

usage() {
	cat <<'EOF'
Usage: scripts/remote-preview-mini-restart.sh [service...]

Restart the remote cloud dev portal stack or selected services on the Mac mini.
Examples:
  scripts/remote-preview-mini-restart.sh
  scripts/remote-preview-mini-restart.sh frontend proxy
EOF
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
	usage
	exit 0
fi

if [ "${1:-}" = "--" ]; then
	shift
fi

SERVICES="${*:-}"

ssh "${REMOTE_HOST}" "bash -lc $(printf '%q' "
set -euo pipefail
cd ${REMOTE_CLOUD_DIR_SCRIPT}
if [ -n '${SERVICES}' ]; then
  docker compose -f docker-compose.dev.yml -f docker-compose.remote-preview.yml restart ${SERVICES}
else
  docker compose -f docker-compose.dev.yml -f docker-compose.remote-preview.yml restart
fi
docker compose -f docker-compose.dev.yml -f docker-compose.remote-preview.yml ps
")"
