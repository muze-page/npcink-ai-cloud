#!/usr/bin/env bash
set -euo pipefail
set +x

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"
npcink_ai_cloud_load_env_file "${ROOT_DIR}"
RELEASE_TOOL_PYTHON="$(npcink_ai_cloud_release_tool_python)"

BASE_URL="${NPCINK_CLOUD_BASE_URL:-http://127.0.0.1:${NPCINK_CLOUD_PORT:-8010}}"
WORKER_CUTOFF="${NPCINK_CLOUD_WORKER_CUTOFF:-}"

while [ "$#" -gt 0 ]; do
	case "$1" in
		--base-url)
			BASE_URL="$2"
			shift 2
			;;
		--worker-cutoff)
			WORKER_CUTOFF="$2"
			shift 2
			;;
		*)
			echo "[fail] Unknown argument: $1" >&2
			exit 1
			;;
	esac
done

if [ "${NPCINK_CLOUD_OPERATIONAL_READY_INTERNAL:-0}" = "1" ]; then
	npcink_ai_cloud_require_cmd docker
	npcink_ai_cloud_require_release_tool_python "${RELEASE_TOOL_PYTHON}"
	if [ -z "${WORKER_CUTOFF}" ]; then
		echo "[fail] Cutover operational readiness requires --worker-cutoff." >&2
		exit 1
	fi
	"${RELEASE_TOOL_PYTHON}" - "${WORKER_CUTOFF}" <<'PY'
from __future__ import annotations

from datetime import datetime
import sys

value = sys.argv[1].strip().replace("Z", "+00:00")
try:
    parsed = datetime.fromisoformat(value)
except ValueError as exc:
    raise SystemExit(f"[fail] Worker cutoff is not an ISO-8601 timestamp: {exc}") from exc
if parsed.tzinfo is None:
    raise SystemExit("[fail] Worker cutoff must include a UTC offset.")
PY

	WORKER_SERVICES=(worker callback-worker ops-worker)
	WORKER_CONTAINER_IDS=()

	worker_container_id() {
		local service_name="$1"
		local ids=""
		local count=0
		ids="$(npcink_ai_cloud_compose "${ROOT_DIR}" ps -q "${service_name}")"
		count="$(printf '%s\n' "${ids}" | awk 'NF { count += 1 } END { print count + 0 }')"
		if [ "${count}" -ne 1 ]; then
			echo "[fail] Expected exactly one ${service_name} container, found ${count}." >&2
			return 1
		fi
		printf '%s' "${ids}"
	}

	assert_worker_container_state() {
		local service_name="$1"
		local container_id="$2"
		local running=""
		local restarting=""
		local restart_count=""
		local started_at=""
		running="$(docker inspect --format '{{.State.Running}}' "${container_id}")"
		restarting="$(docker inspect --format '{{.State.Restarting}}' "${container_id}")"
		restart_count="$(docker inspect --format '{{.RestartCount}}' "${container_id}")"
		started_at="$(docker inspect --format '{{.State.StartedAt}}' "${container_id}")"
		"${RELEASE_TOOL_PYTHON}" - "${service_name}" "${container_id}" "${WORKER_CUTOFF}" \
			"${running}" "${restarting}" "${restart_count}" "${started_at}" <<'PY'
from __future__ import annotations

from datetime import datetime
import sys

(
    service_name,
    container_id,
    cutoff_raw,
    running,
    restarting,
    restart_count,
    started_at_raw,
) = sys.argv[1:]

def parse_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)

try:
    cutoff = parse_timestamp(cutoff_raw)
    started_at = parse_timestamp(started_at_raw)
    restart_count_value = int(restart_count)
except (TypeError, ValueError) as exc:
    raise SystemExit(
        f"[fail] Invalid Docker state timestamp/count for {service_name}: {exc}"
    ) from exc
if running != "true" or restarting != "false" or restart_count_value != 0:
    raise SystemExit(
        f"[fail] Worker {service_name} is not stable: "
        f"running={running} restarting={restarting} restart_count={restart_count_value}."
    )
if started_at <= cutoff:
    raise SystemExit(
        f"[fail] Worker {service_name} did not start after the cutover cutoff."
    )
PY
	}

	for worker_index in "${!WORKER_SERVICES[@]}"; do
		service_name="${WORKER_SERVICES[${worker_index}]}"
		container_id="$(worker_container_id "${service_name}")"
		WORKER_CONTAINER_IDS[${worker_index}]="${container_id}"
		assert_worker_container_state "${service_name}" "${container_id}"
	done

	npcink_ai_cloud_compose "${ROOT_DIR}" exec -T api python - \
		"${WORKER_CUTOFF}" \
		"${NPCINK_CLOUD_WORKER_READINESS_ATTEMPTS:-30}" \
		"${NPCINK_CLOUD_WORKER_READINESS_SLEEP_SECONDS:-2}" <<'PY'
from __future__ import annotations

from datetime import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from app.core.runtime_config import production_runtime_enabled, read_internal_auth_token

cutoff_raw, attempts_raw, sleep_raw = sys.argv[1:]
required_workers = {"runtime_queue", "callback_dispatch", "ops_cadence"}

def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))

try:
    cutoff = parse_timestamp(cutoff_raw)
    attempts = int(attempts_raw)
    sleep_seconds = float(sleep_raw)
except (TypeError, ValueError) as exc:
    raise SystemExit(f"[fail] Invalid worker readiness timing configuration: {exc}") from exc
if attempts < 1 or sleep_seconds < 0:
    raise SystemExit("[fail] Worker readiness attempts must be positive and sleep non-negative.")

domain_name = os.getenv("NPCINK_CLOUD_DOMAIN_NAME", "").strip()
trusted_hosts = os.getenv("NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST", "")
trusted_host = next((item.strip() for item in trusted_hosts.split(",") if item.strip()), "")
host = domain_name or trusted_host or "127.0.0.1"
if host.startswith("*."):
    host = host[2:]
if not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]+)?", host):
    raise SystemExit("[fail] Internal readiness Host is invalid.")

try:
    internal_token = read_internal_auth_token()
except (OSError, RuntimeError, ValueError):
    if production_runtime_enabled():
        raise
    # Focused dev/test harnesses may retain the explicit environment seam;
    # production internal readiness must always consume the projection.
    internal_token = os.environ.get("NPCINK_CLOUD_INTERNAL_AUTH_TOKEN", "").strip()
if not internal_token:
    raise SystemExit("[fail] Internal readiness credential is unavailable.")

request = urllib.request.Request(
    "http://127.0.0.1:8000/internal/service/observability/summary",
    headers={
        "Host": host,
        "X-Npcink-Internal-Token": internal_token,
    },
)
last_error = "no response"
for attempt in range(attempts):
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.load(response)
        items = payload.get("data", {}).get("workers", {}).get("items", [])
        observed: dict[str, datetime] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            worker_id = str(item.get("worker_id") or "")
            last_seen_at = str(item.get("last_seen_at") or "")
            if worker_id not in required_workers or not last_seen_at:
                continue
            observed[worker_id] = parse_timestamp(last_seen_at)
        missing_or_old = sorted(
            worker_id
            for worker_id in required_workers
            if worker_id not in observed or observed[worker_id] <= cutoff
        )
        if response.status == 200 and not missing_or_old:
            print("[ok] All required worker heartbeats are newer than the cutover cutoff.")
            raise SystemExit(0)
        last_error = f"missing or not newer than cutoff: {','.join(missing_or_old)}"
    except (AttributeError, KeyError, TypeError, ValueError, OSError, urllib.error.URLError) as exc:
        last_error = str(exc)
    if attempt + 1 < attempts:
        time.sleep(sleep_seconds)

raise SystemExit(f"[fail] New worker heartbeat proof did not pass: {last_error}")
PY

	STABILITY_SECONDS="${NPCINK_CLOUD_WORKER_STABILITY_SECONDS:-3}"
	if [[ ! "${STABILITY_SECONDS}" =~ ^[0-9]+$ ]] || [ "${STABILITY_SECONDS}" -gt 30 ]; then
		echo "[fail] NPCINK_CLOUD_WORKER_STABILITY_SECONDS must be an integer from 0 to 30." >&2
		exit 1
	fi
	sleep "${STABILITY_SECONDS}"
	for worker_index in "${!WORKER_SERVICES[@]}"; do
		service_name="${WORKER_SERVICES[${worker_index}]}"
		container_id="$(worker_container_id "${service_name}")"
		if [ "${container_id}" != "${WORKER_CONTAINER_IDS[${worker_index}]}" ]; then
			echo "[fail] Worker container changed during the stability window: ${service_name}" >&2
			exit 1
		fi
		assert_worker_container_state "${service_name}" "${container_id}"
	done

	npcink_ai_cloud_wait_for_internal_endpoint \
		"${ROOT_DIR}" "/health/operational-ready" \
		"[ok] New workers are stable and operationally ready before public traffic is restored."
	exit 0
fi

npcink_ai_cloud_require_internal_token
INTERNAL_AUTH_TOKEN="${NPCINK_CLOUD_INTERNAL_AUTH_TOKEN}"
npcink_ai_cloud_require_cmd curl
npcink_ai_cloud_require_cmd mktemp
unset NPCINK_CLOUD_INTERNAL_AUTH_TOKEN
umask 077
REQUEST_DIR="$(mktemp -d)"
REQUEST_HEADERS="${REQUEST_DIR}/headers"
cleanup_request_dir() {
	local exit_status="$?"
	local cleanup_failed=0
	trap - EXIT
	set +e
	rm -rf -- "${REQUEST_DIR}" || cleanup_failed=1
	if [ -e "${REQUEST_DIR}" ] || [ -L "${REQUEST_DIR}" ]; then
		cleanup_failed=1
	fi
	if [ "${cleanup_failed}" -ne 0 ]; then
		echo "[fail] Operational-readiness credential-file cleanup did not complete." >&2
		exit_status=1
	fi
	exit "${exit_status}"
}
trap cleanup_request_dir EXIT
chmod 0700 "${REQUEST_DIR}"
printf '%s\n' "X-Npcink-Internal-Token: ${INTERNAL_AUTH_TOKEN}" >"${REQUEST_HEADERS}"
chmod 0600 "${REQUEST_HEADERS}"
unset INTERNAL_AUTH_TOKEN
curl -fsS \
	--header "@${REQUEST_HEADERS}" \
	"${BASE_URL%/}/health/operational-ready" >/dev/null
if ! rm -f -- "${REQUEST_HEADERS}"; then
	echo "[fail] Operational-readiness credential-file cleanup failed." >&2
	exit 1
fi

echo "[ok] Cloud service is operationally ready at ${BASE_URL}"
