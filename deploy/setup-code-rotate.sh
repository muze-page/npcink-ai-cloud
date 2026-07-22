#!/usr/bin/env bash
set -euo pipefail
set +x

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [ "$(id -u)" != "0" ]; then
	echo "[fail] Setup-code rotation requires the root production operator." >&2
	exit 1
fi
if [ ! -t 1 ]; then
	echo "[fail] Setup-code rotation requires an interactive TTY; refusing to expose plaintext to captured output." >&2
	exit 1
fi
exec bash "${ROOT_DIR}/deploy/prepare-first-install.sh" --rotate
