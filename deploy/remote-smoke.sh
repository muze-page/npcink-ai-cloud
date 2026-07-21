#!/usr/bin/env bash
set -euo pipefail
set +x

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# Shared compose/env helpers for deploy scripts.
. "${ROOT_DIR}/deploy/common.sh"
npcink_ai_cloud_load_env_file "${ROOT_DIR}"

npcink_ai_cloud_require_cmd curl
npcink_ai_cloud_require_cmd openssl
npcink_ai_cloud_require_cmd python3
npcink_ai_cloud_require_cmd mktemp

BASE_URL="${NPCINK_CLOUD_BASE_URL:-http://127.0.0.1:${NPCINK_CLOUD_PORT:-8010}}"
INTERNAL_AUTH_TOKEN="${NPCINK_CLOUD_INTERNAL_AUTH_TOKEN:-}"
SITE_ID="${NPCINK_CLOUD_SITE_ID:-site_smoke}"
KEY_ID="${NPCINK_CLOUD_KEY_ID:-key_default}"
SECRET="${NPCINK_CLOUD_SECRET:-}"
PROFILE_ID="${NPCINK_CLOUD_PROFILE_ID:-text.balanced}"
ABILITY_NAME="${NPCINK_CLOUD_ABILITY_NAME:-npcink-abilities-toolkit/build-article-block-plan}"
CHANNEL="${NPCINK_CLOUD_CHANNEL:-openapi}"
EXECUTION_KIND="${NPCINK_CLOUD_EXECUTION_KIND:-text}"
IDEMPOTENCY_SUFFIX="${NPCINK_CLOUD_IDEMPOTENCY_SUFFIX:-}"
PROMPT_TEXT="${NPCINK_CLOUD_PROMPT_TEXT:-remote deploy smoke request}"
EXPECTED_PROVIDER_ID="${NPCINK_CLOUD_EXPECTED_PROVIDER_ID:-}"
EXPECTED_MODEL_ID="${NPCINK_CLOUD_EXPECTED_MODEL_ID:-}"
EXPECTED_INSTANCE_ID="${NPCINK_CLOUD_EXPECTED_INSTANCE_ID:-}"
SKIP_TERMS_CHECKS="${NPCINK_CLOUD_SKIP_TERMS_CHECKS:-0}"

while [ "$#" -gt 0 ]; do
	case "$1" in
		--base-url)
			BASE_URL="$2"
			shift 2
			;;
		--site-id)
			SITE_ID="$2"
			shift 2
			;;
		--key-id)
			KEY_ID="$2"
			shift 2
			;;
		--secret)
			echo "[fail] --secret is forbidden because process arguments are observable; use NPCINK_CLOUD_SECRET from a protected process environment." >&2
			exit 1
			;;
		--profile-id)
			PROFILE_ID="$2"
			shift 2
			;;
		--ability-name)
			ABILITY_NAME="$2"
			shift 2
			;;
		--execution-kind)
			EXECUTION_KIND="$2"
			shift 2
			;;
		--idempotency-suffix)
			IDEMPOTENCY_SUFFIX="$2"
			shift 2
			;;
		--prompt-text)
			PROMPT_TEXT="$2"
			shift 2
			;;
		--expected-provider-id)
			EXPECTED_PROVIDER_ID="$2"
			shift 2
			;;
		--expected-model-id)
			EXPECTED_MODEL_ID="$2"
			shift 2
			;;
		--expected-instance-id)
			EXPECTED_INSTANCE_ID="$2"
			shift 2
			;;
		--skip-terms-checks)
			SKIP_TERMS_CHECKS=1
			shift
			;;
		*)
			echo "[fail] Unknown argument: $1" >&2
			exit 1
			;;
	esac
done

# Keep credentials in this shell only. Child processes receive a credential
# only through an explicit environment assignment or a protected request file.
unset NPCINK_CLOUD_INTERNAL_AUTH_TOKEN NPCINK_CLOUD_SECRET

fail() {
	echo "[fail] $*" >&2
	exit 1
}

ok() {
	echo "[ok] $*"
}

if [ -z "${INTERNAL_AUTH_TOKEN}" ]; then
	fail "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN for internal-only perimeter checks is required"
fi
if [ -z "${SECRET}" ]; then
	fail "NPCINK_CLOUD_SECRET is required for signed runtime smoke"
fi

OBSERVABILITY_CADENCE_WAIT_ATTEMPTS="${NPCINK_CLOUD_OBSERVABILITY_CADENCE_WAIT_ATTEMPTS:-8}"
OBSERVABILITY_CADENCE_WAIT_DELAY_SECONDS="${NPCINK_CLOUD_OBSERVABILITY_CADENCE_WAIT_DELAY_SECONDS:-5}"
OBSERVABILITY_CADENCE_CONNECT_TIMEOUT_SECONDS=3
OBSERVABILITY_CADENCE_MAX_TIME_SECONDS=10
case "${OBSERVABILITY_CADENCE_WAIT_ATTEMPTS}" in
	[1-9]|1[0-9]|20)
		;;
	*)
		fail "NPCINK_CLOUD_OBSERVABILITY_CADENCE_WAIT_ATTEMPTS must be a canonical integer between 1 and 20"
		;;
esac
case "${OBSERVABILITY_CADENCE_WAIT_DELAY_SECONDS}" in
	[0-9]|10)
		;;
	*)
		fail "NPCINK_CLOUD_OBSERVABILITY_CADENCE_WAIT_DELAY_SECONDS must be a canonical integer between 0 and 10"
		;;
esac
OBSERVABILITY_CADENCE_WAIT_WINDOW_SECONDS="$((
	(OBSERVABILITY_CADENCE_WAIT_ATTEMPTS - 1) * OBSERVABILITY_CADENCE_WAIT_DELAY_SECONDS
))"
OBSERVABILITY_CADENCE_WALL_CLOCK_LIMIT_SECONDS="$((
	OBSERVABILITY_CADENCE_WAIT_ATTEMPTS * OBSERVABILITY_CADENCE_MAX_TIME_SECONDS +
		OBSERVABILITY_CADENCE_WAIT_WINDOW_SECONDS
))"
if [ "${NPCINK_CLOUD_ENVIRONMENT:-}" != "test" ] && \
	[ "${OBSERVABILITY_CADENCE_WAIT_WINDOW_SECONDS}" -lt 35 ]; then
	fail "Observability cadence wait window must cover at least 35 seconds outside test environments"
fi

json_read_path() {
	local json_payload="$1"
	local json_path="$2"
	printf '%s' "${json_payload}" | JSON_PATH="${json_path}" python3 -c '
import json
import os
import sys

payload = sys.stdin.read()
path = os.environ.get("JSON_PATH", "")

try:
    data = json.loads(payload)
except json.JSONDecodeError:
    sys.exit(2)

current = data
for segment in path.split("."):
    if not segment:
        continue
    if not isinstance(current, dict) or segment not in current:
        sys.exit(3)
    current = current[segment]

if current is None:
    print("null")
elif isinstance(current, bool):
    print("true" if current else "false")
elif isinstance(current, (dict, list)):
    print(json.dumps(current, ensure_ascii=True, separators=(",", ":")))
else:
    print(str(current))
'
}

assert_status() {
	local actual="$1"
	local expected="$2"
	local message="$3"
	if [ "${actual}" != "${expected}" ]; then
		fail "${message} (expected ${expected}, got ${actual})"
	fi
}

assert_json_equals() {
	local json_payload="$1"
	local json_path="$2"
	local expected="$3"
	local message="$4"
	local actual
	if ! actual="$(json_read_path "${json_payload}" "${json_path}")"; then
		fail "${message} (missing path ${json_path})"
	fi
	if [ "${actual}" != "${expected}" ]; then
		fail "${message} (expected ${json_path}=${expected}, got ${actual})"
	fi
}

assert_json_non_empty() {
	local json_payload="$1"
	local json_path="$2"
	local message="$3"
	local actual
	if ! actual="$(json_read_path "${json_payload}" "${json_path}")"; then
		fail "${message} (missing path ${json_path})"
	fi
	if [ -z "${actual}" ] || [ "${actual}" = "null" ] || [ "${actual}" = "[]" ] || [ "${actual}" = "{}" ]; then
		fail "${message} (empty ${json_path})"
	fi
}

assert_body_contains() {
	local body="$1"
	local needle="$2"
	local message="$3"
	if ! printf '%s' "${body}" | grep -Fq "${needle}"; then
		fail "${message} (missing '${needle}')"
	fi
}

print_cadence_wait_diagnostics() {
	local json_payload="$1"
	printf '%s' "${json_payload}" | python3 -c '
import json
import sys

payload = sys.stdin.read()
try:
    data = json.loads(payload)
except json.JSONDecodeError:
    raise SystemExit(0)

if not isinstance(data, dict):
    raise SystemExit(0)
data_value = data.get("data")
if not isinstance(data_value, dict):
    raise SystemExit(0)
cadence = data_value.get("cadence")
if not isinstance(cadence, dict):
    raise SystemExit(0)
items = cadence.get("items", [])
if not isinstance(items, list):
    raise SystemExit(0)

task_id_values = {
    "retention_cleanup",
    "plugin_observability_cleanup",
    "usage_rollup",
    "router_diagnostics_summary",
    "latency_probe_summary",
    "alert_provider_degradation",
    "provider_health_scan",
    "artifact_cleanup",
    "artifact_inventory_reconciliation",
    "payment_order_expiration",
}
freshness_values = {"attention", "stale", "missing"}
last_outcome_values = {"succeeded", "error"}


def safe_task_id(value):
    if isinstance(value, str) and value in task_id_values:
        return value
    return "unknown"


def safe_enum(value, allowed_values):
    if isinstance(value, str) and value in allowed_values:
        return value
    return "unknown"


def safe_non_negative_integer(value):
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return -1


diagnostics = []
for item in items:
    if not isinstance(item, dict) or item.get("freshness") == "fresh":
        continue
    diagnostics.append(
        {
            "task_id": safe_task_id(item.get("task_id")),
            "freshness": safe_enum(item.get("freshness"), freshness_values),
            "age_seconds": safe_non_negative_integer(item.get("age_seconds")),
            "interval_seconds": safe_non_negative_integer(
                item.get("interval_seconds")
            ),
            "last_outcome": safe_enum(
                item.get("last_outcome"), last_outcome_values
            ),
        }
    )
    if len(diagnostics) >= 10:
        break

for diagnostic in sorted(diagnostics, key=lambda item: str(item.get("task_id") or "")):
    print(
        "cadence_diagnostic="
        + json.dumps(
            diagnostic,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ),
        file=sys.stderr,
    )
'
}

build_traceparent() {
	python3 - <<'PY'
import secrets
print(f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01")
PY
}

json_quote() {
	local value="$1"
	JSON_VALUE="${value}" python3 - <<'PY'
import json
import os

print(json.dumps(os.environ.get("JSON_VALUE", ""), ensure_ascii=True))
PY
}

build_signature() {
	local method="$1"
	local path="$2"
	local query="$3"
	local timestamp="$4"
	local nonce="$5"
	local idempotency_key="$6"
	local traceparent="$7"
	local body="$8"

	local body_digest
	body_digest="$(printf '%s' "${body}" | openssl dgst -sha256 -r | awk '{print $1}')"
	local path_with_query="${path}"
	if [ -n "${query}" ]; then
		path_with_query="${path}?${query}"
	fi
	local canonical_request
	canonical_request="$(printf '%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s' \
		"${method}" \
		"${path_with_query}" \
		"${SITE_ID}" \
		"${KEY_ID}" \
		"${timestamp}" \
		"${nonce}" \
		"${idempotency_key}" \
		"${traceparent}" \
		"${body_digest}")"
	printf '%s' "${canonical_request}" | NPCINK_CLOUD_HMAC_SECRET="${SECRET}" python3 -c '
import hashlib
import hmac
import os
import sys

secret = os.environ.pop("NPCINK_CLOUD_HMAC_SECRET", "")
if not secret:
    raise SystemExit("[fail] Runtime signing secret is missing.")
payload = sys.stdin.buffer.read()
print(hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest())
'
}

HTTP_STATUS=""
HTTP_BODY=""
umask 077
TMP_DIR="$(mktemp -d)"

cleanup_tmp_dir() {
	local exit_status="$?"
	local cleanup_failed=0
	trap - EXIT
	set +e
	rm -rf -- "${TMP_DIR}" || cleanup_failed=1
	if [ -e "${TMP_DIR}" ] || [ -L "${TMP_DIR}" ]; then
		cleanup_failed=1
	fi
	if [ "${cleanup_failed}" -ne 0 ]; then
		echo "[fail] Remote smoke credential-file cleanup did not complete." >&2
		exit_status=1
	fi
	exit "${exit_status}"
}
trap cleanup_tmp_dir EXIT
chmod 0700 "${TMP_DIR}"

_http_request() {
	local connect_timeout="$1"
	local max_time="$2"
	local method="$3"
	local url="$4"
	local body="${5:-}"
	shift 5

	local request_id="${RANDOM:-0}-$$"
	local tmp_body="${TMP_DIR}/response-${request_id}.txt"
	local request_headers="${TMP_DIR}/request-${request_id}.headers"
	local request_body="${TMP_DIR}/request-${request_id}.body"
	local status
	local curl_args=(
		-sS
		-o "${tmp_body}"
		-w "%{http_code}"
		-X "${method}"
	)
	if [ -n "${connect_timeout}" ]; then
		curl_args+=(--connect-timeout "${connect_timeout}")
	fi
	if [ -n "${max_time}" ]; then
		curl_args+=(--max-time "${max_time}")
	fi
	curl_args+=("${url}" --header "@${request_headers}")
	local header=""
	(
		umask 077
		printf '%s\n' "Accept: application/json" >"${request_headers}"
		for header in "$@"; do
			if [ -n "${header}" ]; then
				printf '%s\n' "${header}" >>"${request_headers}"
			fi
		done
		if [ -n "${body}" ]; then
			printf '%s\n' "Content-Type: application/json" >>"${request_headers}"
			printf '%s' "${body}" >"${request_body}"
		fi
	)
	chmod 0600 "${request_headers}"
	if [ -n "${body}" ]; then
		chmod 0600 "${request_body}"
		curl_args+=(--data-binary "@${request_body}")
	fi

	status="$(curl "${curl_args[@]}")" || {
		rm -f -- "${tmp_body}" "${request_headers}" "${request_body}"
		fail "HTTP request failed: ${method} ${url}"
	}
	HTTP_STATUS="${status}"
	HTTP_BODY="$(cat "${tmp_body}")"
	if ! rm -f -- "${tmp_body}" "${request_headers}" "${request_body}"; then
		fail "Remote smoke request-file cleanup failed"
	fi
}

http_request() {
	_http_request "" "" "$@"
}

observability_summary_request() {
	_http_request \
		"${OBSERVABILITY_CADENCE_CONNECT_TIMEOUT_SECONDS}" \
		"${OBSERVABILITY_CADENCE_MAX_TIME_SECONDS}" \
		"GET" \
		"${BASE_URL%/}/internal/service/observability/summary" \
		"" \
		"X-Npcink-Internal-Token: ${INTERNAL_AUTH_TOKEN}"
}

signed_request() {
	local method="$1"
	local path="$2"
	local query="$3"
	local body="$4"
	local idempotency_key="$5"
	local nonce="$6"
	local traceparent
	traceparent="$(build_traceparent)"
	local timestamp
	timestamp="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
	local signature
	signature="$(build_signature "${method}" "${path}" "${query}" "${timestamp}" "${nonce}" "${idempotency_key}" "${traceparent}" "${body}")"
	local url="${BASE_URL%/}${path}"
	if [ -n "${query}" ]; then
		url="${url}?${query}"
	fi
	http_request "${method}" "${url}" "${body}" \
		"traceparent: ${traceparent}" \
		"X-Npcink-Site-Id: ${SITE_ID}" \
		"X-Npcink-Key-Id: ${KEY_ID}" \
		"X-Npcink-Timestamp: ${timestamp}" \
		"X-Npcink-Signature: sha256=${signature}" \
		"X-Npcink-Nonce: ${nonce}" \
		"Idempotency-Key: ${idempotency_key}"
}

ok "Waiting for cloud ready: ${BASE_URL}"
if ! npcink_ai_cloud_wait_for_ready "${BASE_URL}" 20 2; then
	fail "Cloud API did not become ready"
fi

IDEMPOTENCY_SUFFIX_NORMALIZED=""
if [ -n "${IDEMPOTENCY_SUFFIX}" ]; then
	IDEMPOTENCY_SUFFIX_NORMALIZED="-${IDEMPOTENCY_SUFFIX}"
fi

http_request "GET" "${BASE_URL%/}/health/live" ""
assert_status "${HTTP_STATUS}" "200" "health/live should succeed"
assert_json_equals "${HTTP_BODY}" "status" "ok" "health/live envelope status should be ok"

if [ "${NPCINK_CLOUD_SKIP_FRONTEND_IMAGE:-0}" = "1" ]; then
	ok "Skipping frontend page checks because NPCINK_CLOUD_SKIP_FRONTEND_IMAGE=1"
else
	http_request "GET" "${BASE_URL%/}/" ""
	assert_status "${HTTP_STATUS}" "200" "buyer-facing home page should succeed"
	assert_body_contains "${HTTP_BODY}" "_next/" "buyer-facing home page should be served by Next frontend"

	http_request "GET" "${BASE_URL%/}/portal/login" ""
	assert_status "${HTTP_STATUS}" "200" "portal login page should succeed"
	assert_body_contains "${HTTP_BODY}" "_next/" "portal login page should be served by Next frontend"
fi

if [ "${SKIP_TERMS_CHECKS}" = "1" ]; then
	ok "Skipping static terms checks because --skip-terms-checks was set"
else
	http_request "GET" "${BASE_URL%/}/terms" ""
	assert_status "${HTTP_STATUS}" "200" "terms index should be served by the production static path without exposing internal proxy redirects"
	assert_body_contains "${HTTP_BODY}" "Npcink Cloud Legal Documents" "terms index should include the expected title"

	http_request "GET" "${BASE_URL%/}/terms/en/terms.html" ""
	assert_status "${HTTP_STATUS}" "200" "English terms page should be served by the production static path"
	assert_body_contains "${HTTP_BODY}" "Npcink Cloud Terms of Service" "English terms page should include the expected title"

	http_request "GET" "${BASE_URL%/}/terms/zh/terms.html" ""
	assert_status "${HTTP_STATUS}" "200" "Chinese terms page should be served by the production static path"
	assert_body_contains "${HTTP_BODY}" "Npcink Cloud 服务条款" "Chinese terms page should include the expected title"

	http_request "GET" "${BASE_URL%/}/terms/styles.css" ""
	assert_status "${HTTP_STATUS}" "200" "terms stylesheet should be served by the production static path"
	assert_body_contains "${HTTP_BODY}" "site-header" "terms stylesheet should include the expected layout selectors"
fi

http_request "GET" "${BASE_URL%/}/docs" ""
assert_status "${HTTP_STATUS}" "404" "docs should stay disabled in production perimeter"

http_request "GET" "${BASE_URL%/}/redoc" ""
assert_status "${HTTP_STATUS}" "404" "redoc should stay disabled in production perimeter"

http_request "GET" "${BASE_URL%/}/health/ready" ""
assert_status "${HTTP_STATUS}" "401" "health/ready without token should fail closed"

http_request "POST" "${BASE_URL%/}/internal/catalog/refresh" '{"providers":[]}' \
	"Idempotency-Key: idem-internal-refresh-001${IDEMPOTENCY_SUFFIX_NORMALIZED}"
assert_status "${HTTP_STATUS}" "401" "internal/catalog/refresh without token should fail closed"

http_request "GET" "${BASE_URL%/}/health/ready" "" \
	"X-Npcink-Internal-Token: ${INTERNAL_AUTH_TOKEN}"
assert_status "${HTTP_STATUS}" "200" "health/ready with internal token should succeed"

OPERATIONAL_READY_ATTEMPTS="${NPCINK_CLOUD_OPERATIONAL_READY_WAIT_ATTEMPTS:-36}"
OPERATIONAL_READY_DELAY_SECONDS="${NPCINK_CLOUD_OPERATIONAL_READY_WAIT_DELAY_SECONDS:-5}"
for ((attempt = 1; attempt <= OPERATIONAL_READY_ATTEMPTS; attempt++)); do
	http_request "GET" "${BASE_URL%/}/health/operational-ready" "" \
		"X-Npcink-Internal-Token: ${INTERNAL_AUTH_TOKEN}"
	if [ "${HTTP_STATUS}" = "200" ]; then
		break
	fi
	if [ "${attempt}" -lt "${OPERATIONAL_READY_ATTEMPTS}" ]; then
		sleep "${OPERATIONAL_READY_DELAY_SECONDS}"
	fi
done
assert_status "${HTTP_STATUS}" "200" "health/operational-ready with internal token should succeed"
assert_json_non_empty "${HTTP_BODY}" "data.required_workers" "operational readiness should expose required workers"

OBSERVABILITY_CADENCE_FRESH=0
for ((attempt = 1; attempt <= OBSERVABILITY_CADENCE_WAIT_ATTEMPTS; attempt++)); do
	observability_summary_request
	assert_status "${HTTP_STATUS}" "200" "observability summary with internal token should succeed"
	if ! CADENCE_NON_FRESH_TOTAL="$(
		json_read_path "${HTTP_BODY}" "data.cadence.totals.non_fresh_total"
	)"; then
		fail "observability summary should expose cadence non-fresh total"
	fi
	case "${CADENCE_NON_FRESH_TOTAL}" in
		''|*[!0-9]*)
			fail "observability cadence non-fresh total must be a non-negative integer"
			;;
	esac
	if [ "${CADENCE_NON_FRESH_TOTAL}" = "0" ]; then
		OBSERVABILITY_CADENCE_FRESH=1
		break
	fi
	if [ "${attempt}" -lt "${OBSERVABILITY_CADENCE_WAIT_ATTEMPTS}" ]; then
		sleep "${OBSERVABILITY_CADENCE_WAIT_DELAY_SECONDS}"
	fi
done
if [ "${OBSERVABILITY_CADENCE_FRESH}" -ne 1 ]; then
	print_cadence_wait_diagnostics "${HTTP_BODY}"
	fail "observability cadence did not become fresh before the bounded wait expired (wall-clock ceiling ${OBSERVABILITY_CADENCE_WALL_CLOCK_LIMIT_SECONDS}s)"
fi

# Revalidate every requirement against the same final response that proved
# aggregate cadence freshness. A prior non-fresh response is never accepted.
assert_status "${HTTP_STATUS}" "200" "observability summary with internal token should succeed"
assert_json_equals "${HTTP_BODY}" "data.workers.totals.missing_total" "0" "observability summary should not report missing workers"
assert_json_equals "${HTTP_BODY}" "data.cadence.totals.non_fresh_total" "0" "observability summary should not report non-fresh cadence tasks"
assert_json_equals "${HTTP_BODY}" "data.providers.freshness" "fresh" "provider freshness should be fresh"
assert_json_equals "${HTTP_BODY}" "data.runtime.summary.callback.pressure_state" "healthy" "callback backlog should be healthy"
assert_json_non_empty "${HTTP_BODY}" "data.tracing.otlp_configured" "observability summary should expose the external exporter configuration fact"
assert_json_non_empty "${HTTP_BODY}" "data.tracing.trace_query_configured" "observability summary should expose the external query configuration fact"
case "${BASE_URL}" in
	https://*)
		assert_json_equals "${HTTP_BODY}" "data.tracing.otlp_configured" "true" "formal HTTPS smoke requires an external OTLP exporter"
		assert_json_non_empty "${HTTP_BODY}" "data.tracing.otlp_endpoint" "formal HTTPS smoke requires an external OTLP exporter endpoint"
		assert_json_equals "${HTTP_BODY}" "data.tracing.trace_query_configured" "true" "formal HTTPS smoke requires an external trace query surface"
		assert_json_non_empty "${HTTP_BODY}" "data.tracing.trace_query_url" "formal HTTPS smoke requires an external trace query URL"
		;;
esac

signed_request "GET" "/v1/catalog/models" "" "" "idem-deploy-smoke-catalog-001${IDEMPOTENCY_SUFFIX_NORMALIZED}" ""
assert_status "${HTTP_STATUS}" "200" "catalog/models should succeed"
assert_json_non_empty "${HTTP_BODY}" "data.items" "catalog/models should return model list"

PROMPT_TEXT_JSON="$(json_quote "${PROMPT_TEXT}")"
EXECUTE_BODY="$(cat <<JSON
{"site_id":"${SITE_ID}","ability_name":"${ABILITY_NAME}","channel":"${CHANNEL}","execution_kind":"${EXECUTION_KIND}","profile_id":"${PROFILE_ID}","input":{"messages":[{"role":"user","content":${PROMPT_TEXT_JSON}}]},"policy":{"allow_fallback":true}}
JSON
)"

signed_request "POST" "/v1/runtime/execute" "" "${EXECUTE_BODY}" "idem-deploy-smoke-execute-001${IDEMPOTENCY_SUFFIX_NORMALIZED}" "nonce-deploy-smoke-execute-001${IDEMPOTENCY_SUFFIX_NORMALIZED}"
assert_status "${HTTP_STATUS}" "200" "runtime/execute should succeed"
EXECUTE_ENVELOPE_STATUS="$(json_read_path "${HTTP_BODY}" "status" 2>/dev/null || true)"
if [ "${EXECUTE_ENVELOPE_STATUS}" != "ok" ]; then
	fail "runtime/execute envelope status should be ok"
fi
assert_json_equals "${HTTP_BODY}" "data.status" "succeeded" "runtime/execute data.status should be succeeded"
assert_json_non_empty "${HTTP_BODY}" "data.run_id" "runtime/execute should return run_id"
if [ -n "${EXPECTED_PROVIDER_ID}" ]; then
	assert_json_equals "${HTTP_BODY}" "data.provider_id" "${EXPECTED_PROVIDER_ID}" "runtime/execute should match expected provider_id"
fi
if [ -n "${EXPECTED_MODEL_ID}" ]; then
	assert_json_equals "${HTTP_BODY}" "data.model_id" "${EXPECTED_MODEL_ID}" "runtime/execute should match expected model_id"
fi
if [ -n "${EXPECTED_INSTANCE_ID}" ]; then
	assert_json_equals "${HTTP_BODY}" "data.instance_id" "${EXPECTED_INSTANCE_ID}" "runtime/execute should match expected instance_id"
fi
RUN_ID="$(json_read_path "${HTTP_BODY}" "data.run_id")"

signed_request "GET" "/v1/runs/${RUN_ID}" "" "" "idem-deploy-smoke-run-001${IDEMPOTENCY_SUFFIX_NORMALIZED}" ""
assert_status "${HTTP_STATUS}" "200" "runs/{run_id} should succeed"
assert_json_equals "${HTTP_BODY}" "data.run_id" "${RUN_ID}" "run lookup should return the same run_id"
if [ -n "${EXPECTED_PROVIDER_ID}" ]; then
	assert_json_equals "${HTTP_BODY}" "data.provider_id" "${EXPECTED_PROVIDER_ID}" "run lookup should match expected provider_id"
fi
if [ -n "${EXPECTED_MODEL_ID}" ]; then
	assert_json_equals "${HTTP_BODY}" "data.model_id" "${EXPECTED_MODEL_ID}" "run lookup should match expected model_id"
fi
if [ -n "${EXPECTED_INSTANCE_ID}" ]; then
	assert_json_equals "${HTTP_BODY}" "data.instance_id" "${EXPECTED_INSTANCE_ID}" "run lookup should match expected instance_id"
fi

signed_request "GET" "/v1/runs/${RUN_ID}/result" "" "" "idem-deploy-smoke-result-001${IDEMPOTENCY_SUFFIX_NORMALIZED}" ""
assert_status "${HTTP_STATUS}" "200" "runs/{run_id}/result should succeed"
if [ "${EXECUTION_KIND}" = "image_generation" ]; then
	assert_json_non_empty "${HTTP_BODY}" "data.result.images" "image generation result should include images"
else
	assert_json_non_empty "${HTTP_BODY}" "data.result.output_text" "run result should include output_text"
fi

signed_request "GET" "/v1/stats/profiles/${PROFILE_ID}" "" "" "idem-deploy-smoke-stats-001${IDEMPOTENCY_SUFFIX_NORMALIZED}" ""
assert_status "${HTTP_STATUS}" "200" "stats/profiles should succeed"
assert_json_equals "${HTTP_BODY}" "data.profile_id" "${PROFILE_ID}" "profile stats should match requested profile"

signed_request "GET" "/v1/usage/summary" "" "" "idem-deploy-smoke-usage-001${IDEMPOTENCY_SUFFIX_NORMALIZED}" ""
assert_status "${HTTP_STATUS}" "200" "usage/summary should succeed"
assert_json_non_empty "${HTTP_BODY}" "data.windows.rolling_24h.provider_calls_total" "usage summary should expose provider_calls_total"

ok "Remote deploy smoke completed successfully."
