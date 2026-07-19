#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
HELPER="${ROOT_DIR}/scripts/verify-release-bundle-manifest.py"
MODE="pre-load"
TARGET="${ROOT_DIR}"
CHECKSUM=""

usage() {
	cat <<'EOF'
Usage:
  verify-release-bundle.sh --pre-load [bundle-directory]
  verify-release-bundle.sh --post-load [bundle-directory]
  verify-release-bundle.sh --archive <deploy-bundle.tgz> [checksum-file]

The archive mode validates the outer checksum, tar member paths/types, schema,
complete file set, hashes, sizes, and required archives before extraction.
The post-load mode additionally verifies every loaded Docker image ID.
EOF
}

case "${1:-}" in
	--pre-load)
		MODE="pre-load"
		TARGET="${2:-${ROOT_DIR}}"
		[ "$#" -le 2 ] || { usage >&2; exit 64; }
		;;
	--post-load)
		MODE="post-load"
		TARGET="${2:-${ROOT_DIR}}"
		[ "$#" -le 2 ] || { usage >&2; exit 64; }
		;;
	--archive)
		MODE="archive"
		TARGET="${2:-}"
		CHECKSUM="${3:-${TARGET}.sha256}"
		[ -n "${TARGET}" ] && [ "$#" -le 3 ] || { usage >&2; exit 64; }
		;;
	-h|--help)
		usage
		exit 0
		;;
	*)
		usage >&2
		exit 64
		;;
esac

command -v python3 >/dev/null 2>&1 || {
	echo "[fail] python3 is required for exact release-bundle verification" >&2
	exit 1
}
[ -f "${HELPER}" ] || {
	echo "[fail] release-bundle verifier helper is missing: ${HELPER}" >&2
	exit 1
}

case "${MODE}" in
	archive)
		[ -f "${TARGET}" ] || { echo "[fail] bundle archive not found: ${TARGET}" >&2; exit 1; }
		[ -f "${CHECKSUM}" ] || { echo "[fail] bundle checksum not found: ${CHECKSUM}" >&2; exit 1; }
		python3 "${HELPER}" verify-archive --bundle "${TARGET}" --checksum "${CHECKSUM}"
		;;
	pre-load)
		python3 "${HELPER}" verify-directory --root "${TARGET}"
		;;
	post-load)
		command -v docker >/dev/null 2>&1 || {
			echo "[fail] docker is required for post-load image-ID verification" >&2
			exit 1
		}
		python3 "${HELPER}" verify-directory --root "${TARGET}" --post-load
		;;
esac

echo "[ok] Exact release bundle verified (${MODE})."
