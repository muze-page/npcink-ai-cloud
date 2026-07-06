#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
EVIDENCE_DIR="${NPCINK_CLOUD_PROVIDER_FAILURE_DRILL_EVIDENCE_DIR:-${ROOT_DIR}/.tmp/local-alpha-provider-failure-drill}"
SUFFIX="${NPCINK_CLOUD_PROVIDER_FAILURE_DRILL_SUFFIX:-$(date -u '+%Y%m%d%H%M%S')}"
EVIDENCE_FILE="${EVIDENCE_DIR}/evidence-${SUFFIX}.json"

mkdir -p "${EVIDENCE_DIR}"

docker compose -f "${ROOT_DIR}/docker-compose.dev.yml" run --rm \
	-e NPCINK_CLOUD_OPENAI_API_KEY= \
	-e NPCINK_CLOUD_OPENAI_COMPATIBLE_API_KEY= \
	api python -m app.dev.provider_failure_drill >"${EVIDENCE_FILE}"

python3 - "${EVIDENCE_FILE}" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    payload = json.load(fh)

run = payload.get("run", {})
failures = payload.get("diagnostics", {}).get("failures", {})
guidance = payload.get("diagnostics", {}).get("operator_guidance", {})
dominant = failures.get("dominant_error", {})
actions = guidance.get("suggested_actions", [])

assert run.get("status") == "failed", run
assert run.get("error_code") == "provider.auth_invalid", run
assert run.get("error_stage") == "provider", run
assert failures.get("failed_recent", 0) >= 1, failures
assert failures.get("provider_error_calls_recent", 0) >= 1, failures
assert dominant.get("error_stage") == "provider", dominant
assert guidance.get("primary_reason") == "provider_failures", guidance
assert any(
    item.get("action") == "inspect_provider_credentials_quota_and_health"
    for item in actions
), actions
print(path)
PY

echo "[ok] Provider failure drill passed"
echo "[ok] Evidence: ${EVIDENCE_FILE}"
