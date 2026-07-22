#!/usr/bin/env sh
set -eu

CONFIG_DIR="${NPCINK_CLOUD_CONFIG_DIR:-/run/npcink-config}"
STATE_FILE="${CONFIG_DIR%/}/install-state.json"
POLL_SECONDS="${NPCINK_CLOUD_INSTALL_WAIT_POLL_SECONDS:-2}"

case "${POLL_SECONDS}" in
	''|*[!0-9]*)
		echo "[fail] NPCINK_CLOUD_INSTALL_WAIT_POLL_SECONDS must be a positive integer." >&2
		exit 64
		;;
	0)
		echo "[fail] NPCINK_CLOUD_INSTALL_WAIT_POLL_SECONDS must be greater than zero." >&2
		exit 64
		;;
esac

if [ "$#" -eq 0 ]; then
	echo "[fail] Worker wait wrapper requires a command." >&2
	exit 64
fi

echo "[info] Worker is waiting for installation_state=complete."
while ! python - "${STATE_FILE}" <<'PY'
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("state path is not a regular file")
    with path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
except (OSError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)

raise SystemExit(0 if payload.get("installation_state") == "complete" else 1)
PY
do
	sleep "${POLL_SECONDS}"
done

echo "[ok] Installation is complete; starting worker."
exec "$@"
