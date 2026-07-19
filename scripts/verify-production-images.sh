#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_FILE="${NPCINK_CLOUD_IMAGE_LOCK_FILE:-${ROOT_DIR}/deploy/image-lock/production-images.json}"
ONLINE=0

usage() {
	cat <<'USAGE'
Usage: scripts/verify-production-images.sh [--online]

Verify that every production Dockerfile/Compose image input matches the single
machine-readable lock. --online also proves every exact digest and required
linux/amd64 + linux/arm64 manifest still resolves from its registry.
USAGE
}

while [ "$#" -gt 0 ]; do
	case "$1" in
		--online) ONLINE=1 ;;
		-h | --help)
			usage
			exit 0
			;;
		*)
			echo "[fail] unknown argument: $1" >&2
			usage >&2
			exit 64
			;;
	esac
	shift
done

ARGS=(verify --lock "${LOCK_FILE}")
if [ "${ONLINE}" = "1" ]; then
	ARGS+=(--online)
fi

exec python3 "${ROOT_DIR}/scripts/production-image-supply.py" "${ARGS[@]}"
