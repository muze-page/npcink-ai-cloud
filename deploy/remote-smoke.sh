#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# Shared compose/env helpers for deploy scripts.
. "${ROOT_DIR}/deploy/common.sh"
npcink_ai_cloud_load_env_file "${ROOT_DIR}"

npcink_ai_cloud_require_cmd curl
npcink_ai_cloud_require_cmd openssl
npcink_ai_cloud_require_cmd python3

BASE_URL="${NPCINK_CLOUD_BASE_URL:-http://127.0.0.1:${NPCINK_CLOUD_PORT:-8010}}"
INTERNAL_AUTH_TOKEN="${NPCINK_CLOUD_INTERNAL_AUTH_TOKEN:-}"
SITE_ID="${NPCINK_CLOUD_SITE_ID:-site_smoke}"
KEY_ID="${NPCINK_CLOUD_KEY_ID:-key_default}"
SECRET="${NPCINK_CLOUD_SECRET:-npcink-cloud-test-secret}"
PROFILE_ID="${NPCINK_CLOUD_PROFILE_ID:-text.balanced}"
ABILITY_NAME="${NPCINK_CLOUD_ABILITY_NAME:-npcink-abilities-toolkit/build-article-block-plan}"
CHANNEL="${NPCINK_CLOUD_CHANNEL:-openapi}"
EXECUTION_KIND="${NPCINK_CLOUD_EXECUTION_KIND:-text}"
IDEMPOTENCY_SUFFIX="${NPCINK_CLOUD_IDEMPOTENCY_SUFFIX:-}"
PROMPT_TEXT="${NPCINK_CLOUD_PROMPT_TEXT:-remote deploy smoke request}"
EXPECTED_PROVIDER_ID="${NPCINK_CLOUD_EXPECTED_PROVIDER_ID:-}"
EXPECTED_MODEL_ID="${NPCINK_CLOUD_EXPECTED_MODEL_ID:-}"
EXPECTED_INSTANCE_ID="${NPCINK_CLOUD_EXPECTED_INSTANCE_ID:-}"

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
			SECRET="$2"
			shift 2
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
		*)
			echo "[fail] Unknown argument: $1" >&2
			exit 1
			;;
	esac
done

fail() {
	echo "[fail] $*" >&2
	exit 1
}

ok() {
	echo "[ok] $*"
}

json_read_path() {
	local json_payload="$1"
	local json_path="$2"
	JSON_PAYLOAD="${json_payload}" JSON_PATH="${json_path}" python3 - <<'PY'
import json
import os
import sys

payload = os.environ.get("JSON_PAYLOAD", "")
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
PY
}

assert_status() {
	local actual="$1"
	local expected="$2"
	local message="$3"
	if [ "${actual}" != "${expected}" ]; then
		fail "${message} (expected ${expected}, got ${actual}; body=${HTTP_BODY})"
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
	printf '%s' "${canonical_request}" | openssl dgst -sha256 -hmac "${SECRET}" -r | awk '{print $1}'
}

HTTP_STATUS=""
HTTP_BODY=""

http_request() {
	local method="$1"
	local url="$2"
	local body="${3:-}"
	shift 3

	local tmp_body
	tmp_body="$(mktemp)"
	local status
	local curl_args=(
		-sS
		-o "${tmp_body}"
		-w "%{http_code}"
		-X "${method}"
		"${url}"
		-H "Accept: application/json"
	)
	local header=""
	for header in "$@"; do
		if [ -n "${header}" ]; then
			curl_args+=(-H "${header}")
		fi
	done
	if [ -n "${body}" ]; then
		curl_args+=(-H "Content-Type: application/json" --data "${body}")
	fi

	status="$(curl "${curl_args[@]}")" || {
		rm -f "${tmp_body}"
		fail "HTTP request failed: ${method} ${url}"
	}
	HTTP_STATUS="${status}"
	HTTP_BODY="$(cat "${tmp_body}")"
	rm -f "${tmp_body}"
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
npcink_ai_cloud_require_internal_token

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

http_request "GET" "${BASE_URL%/}/terms" ""
assert_status "${HTTP_STATUS}" "200" "terms index should be served by the production static path without exposing internal proxy redirects"
assert_body_contains "${HTTP_BODY}" "Npcink Cloud legal documents" "terms index should include the expected title"

http_request "GET" "${BASE_URL%/}/terms/en/terms.html" ""
assert_status "${HTTP_STATUS}" "200" "English terms page should be served by the production static path"
assert_body_contains "${HTTP_BODY}" "Npcink Cloud Terms of Service" "English terms page should include the expected title"

http_request "GET" "${BASE_URL%/}/terms/zh/terms.html" ""
assert_status "${HTTP_STATUS}" "200" "Chinese terms page should be served by the production static path"
assert_body_contains "${HTTP_BODY}" "Npcink Cloud 服务条款" "Chinese terms page should include the expected title"

http_request "GET" "${BASE_URL%/}/terms/styles.css" ""
assert_status "${HTTP_STATUS}" "200" "terms stylesheet should be served by the production static path"
assert_body_contains "${HTTP_BODY}" "site-header" "terms stylesheet should include the expected layout selectors"

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

http_request "GET" "${BASE_URL%/}/internal/service/observability/summary" "" \
	"X-Npcink-Internal-Token: ${INTERNAL_AUTH_TOKEN}"
assert_status "${HTTP_STATUS}" "200" "observability summary with internal token should succeed"
assert_json_equals "${HTTP_BODY}" "data.workers.totals.missing_total" "0" "observability summary should not report missing workers"
assert_json_equals "${HTTP_BODY}" "data.cadence.totals.non_fresh_total" "0" "observability summary should not report non-fresh cadence tasks"
assert_json_equals "${HTTP_BODY}" "data.providers.freshness" "fresh" "provider freshness should be fresh"
assert_json_equals "${HTTP_BODY}" "data.runtime.summary.callback.pressure_state" "healthy" "callback backlog should be healthy"
assert_json_non_empty "${HTTP_BODY}" "data.tracing.trace_sink_otlp_endpoint" "observability summary should expose trace sink"

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
	fail "runtime/execute envelope status should be ok (body=${HTTP_BODY})"
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
assert_json_non_empty "${HTTP_BODY}" "data.result.output_text" "run result should include output_text"

signed_request "GET" "/v1/stats/profiles/${PROFILE_ID}" "" "" "idem-deploy-smoke-stats-001${IDEMPOTENCY_SUFFIX_NORMALIZED}" ""
assert_status "${HTTP_STATUS}" "200" "stats/profiles should succeed"
assert_json_equals "${HTTP_BODY}" "data.profile_id" "${PROFILE_ID}" "profile stats should match requested profile"

signed_request "GET" "/v1/usage/summary" "" "" "idem-deploy-smoke-usage-001${IDEMPOTENCY_SUFFIX_NORMALIZED}" ""
assert_status "${HTTP_STATUS}" "200" "usage/summary should succeed"
assert_json_non_empty "${HTTP_BODY}" "data.windows.rolling_24h.provider_calls_total" "usage summary should expose provider_calls_total"

ok "Remote deploy smoke completed successfully."
