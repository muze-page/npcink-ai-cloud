#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
EVIDENCE_DIR="${NPCINK_CLOUD_AUTH_FAILURE_DRILL_EVIDENCE_DIR:-${ROOT_DIR}/.tmp/local-alpha-auth-failure-drill}"
SUFFIX="${NPCINK_CLOUD_AUTH_FAILURE_DRILL_SUFFIX:-$(date -u '+%Y%m%d%H%M%S')}"
EVIDENCE_FILE="${EVIDENCE_DIR}/evidence-${SUFFIX}.json"

mkdir -p "${EVIDENCE_DIR}"

	docker compose -f "${ROOT_DIR}/docker-compose.dev.yml" run --rm \
	-e NPCINK_CLOUD_OPENAI_API_KEY= \
	api python -m app.dev.auth_failure_drill >"${EVIDENCE_FILE}"

python3 - "${EVIDENCE_FILE}" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    payload = json.load(fh)

auth_response = payload.get("auth_response", {})
guard_summary = payload.get("diagnostics", {}).get("guard_summary", {})
guidance = payload.get("diagnostics", {}).get("operator_guidance", {})
event_codes = guard_summary.get("event_codes", [])

assert auth_response.get("status_code") == 401, auth_response
assert auth_response.get("error_code") == "auth.invalid_signature", auth_response
assert any(
    item.get("event_code") == "auth.invalid_signature"
    for item in event_codes
), event_codes
assert guard_summary.get("recent_events", 0) >= 1, guard_summary
print(path)
PY

echo "[ok] Auth failure drill passed"
echo "[ok] Evidence: ${EVIDENCE_FILE}"
