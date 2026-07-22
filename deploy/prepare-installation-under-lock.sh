#!/usr/bin/env bash
set -euo pipefail
set +x

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"
RELEASE_TOOL_PYTHON="${NPCINK_CLOUD_RELEASE_TOOL_PYTHON:-/usr/bin/python3.11}"
npcink_ai_cloud_require_host_release_tool_python "${RELEASE_TOOL_PYTHON}"
MANAGED_ROOT="$(npcink_ai_cloud_managed_root_for_release "${ROOT_DIR}" 0)" || exit 1
npcink_ai_cloud_require_deploy_lock_owner "${ROOT_DIR}"
CONFIG_DIR="${NPCINK_CLOUD_CONFIG_DIR_HOST:-${MANAGED_ROOT}/shared/config}"
STATE_FILE="${CONFIG_DIR}/install-state.json"

if [ "$(id -u)" != "0" ]; then
	echo "[fail] Deployment installation preparation requires root." >&2
	exit 1
fi
if [ "${NPCINK_CLOUD_INSTALL_LOCK_HELD:-0}" != "1" ] || \
	[[ ! "${NPCINK_CLOUD_INSTALL_LOCK_FD:-}" =~ ^[0-9]+$ ]]; then
	echo "[fail] Deployment installation preparation requires an inherited validated lock fd." >&2
	exit 1
fi

installation_state="$("${RELEASE_TOOL_PYTHON}" - "${STATE_FILE}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists():
    print("missing")
    raise SystemExit(0)
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit("[fail] Shared install-state.json is invalid.") from exc
state = payload.get("installation_state") if isinstance(payload, dict) else None
if state not in {"pending", "initializing", "complete"}:
    raise SystemExit("[fail] Shared installation state is unsupported.")
print(state)
PY
)"
case "${installation_state}" in
	missing|pending)
		bash "${ROOT_DIR}/deploy/prepare-first-install.sh"
		;;
	initializing)
		echo "[fail] A first-install operation is already initializing; deployment will not race it." >&2
		exit 1
		;;
	complete)
		;;
esac
