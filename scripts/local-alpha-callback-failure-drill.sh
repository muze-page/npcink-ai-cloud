#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
EVIDENCE_DIR="${NPCINK_CLOUD_CALLBACK_FAILURE_DRILL_EVIDENCE_DIR:-${ROOT_DIR}/.tmp/local-alpha-callback-failure-drill}"
SUFFIX="${NPCINK_CLOUD_CALLBACK_FAILURE_DRILL_SUFFIX:-$(date -u '+%Y%m%d%H%M%S')}"
EVIDENCE_FILE="${EVIDENCE_DIR}/evidence-${SUFFIX}.json"

mkdir -p "${EVIDENCE_DIR}"

	docker compose -f "${ROOT_DIR}/docker-compose.dev.yml" run --rm \
	-e NPCINK_CLOUD_OPENAI_API_KEY= \
	api python -m app.dev.callback_failure_drill >"${EVIDENCE_FILE}"

python3 - "${EVIDENCE_FILE}" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    payload = json.load(fh)

run = payload.get("run", {})
callback = run.get("callback", {})
dispatch = payload.get("callback_dispatch", [])
diagnostic_callback = payload.get("diagnostics", {}).get("callback", {})
guidance = payload.get("diagnostics", {}).get("operator_guidance", {})
actions = guidance.get("suggested_actions", [])

assert run.get("status") == "succeeded", run
assert run.get("provider_call_count") == 1, run
assert callback.get("requested") is True, callback
assert callback.get("dispatch_status") == "failed", callback
assert callback.get("attempt_count") == 1, callback
assert callback.get("last_error_code") == "runtime.callback_delivery_failed", callback
assert len(dispatch) == 1, dispatch
assert dispatch[0].get("callback_status") == "failed", dispatch
assert diagnostic_callback.get("failed", 0) >= 1, diagnostic_callback
assert diagnostic_callback.get("pressure_state") in {"attention", "critical"}, diagnostic_callback
assert "callback.failed" in diagnostic_callback.get("pressure_reasons", []), diagnostic_callback
assert guidance.get("primary_reason") == "callback_delivery", guidance
assert any(
    item.get("action") == "inspect_callback_delivery_and_retry_buffer"
    for item in actions
), actions
print(path)
PY

echo "[ok] Callback failure drill passed"
echo "[ok] Evidence: ${EVIDENCE_FILE}"
