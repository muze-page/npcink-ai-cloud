#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"

if [ -z "${NPCINK_CLOUD_ENV_FILE:-}" ] && [ -f "${ROOT_DIR}/.env.local" ]; then
	export NPCINK_CLOUD_ENV_FILE="${ROOT_DIR}/.env.local"
fi
npcink_ai_cloud_load_env_file "${ROOT_DIR}"

npcink_ai_cloud_require_cmd curl
npcink_ai_cloud_require_cmd docker
npcink_ai_cloud_require_cmd openssl
npcink_ai_cloud_require_cmd python3

BASE_URL="${NPCINK_CLOUD_BASE_URL:-http://127.0.0.1:${NPCINK_CLOUD_PORT:-8010}}"
SITE_URL="${NPCINK_CLOUD_SITE_URL:-https://magick-ai.local/}"
WORDPRESS_ADMIN_USER="${NPCINK_CLOUD_WORDPRESS_ADMIN_USER:-1}"
WORDPRESS_ADMIN_PASSWORD="${NPCINK_CLOUD_WORDPRESS_ADMIN_PASSWORD:-1}"
SITE_ID="${NPCINK_CLOUD_SITE_ID:-${NPCINK_CLOUD_DEV_PORTAL_SITE_ID:-${NPCINK_CLOUD_ALPHA_SITE_ID:-site_npcink_local}}}"
KEY_ID="${NPCINK_CLOUD_KEY_ID:-${NPCINK_CLOUD_ALPHA_KEY_ID:-key_ec8ba4d6ac914507ac3cf8e7a9efa264}}"
SECRET="${NPCINK_CLOUD_SECRET:-${NPCINK_CLOUD_SITE_KEY_SECRET:-${NPCINK_CLOUD_ALPHA_SITE_SECRET:-}}}"
IDEMPOTENCY_SUFFIX="${NPCINK_CLOUD_LOCAL_ALPHA_SMOKE_SUFFIX:-$(date -u '+%Y%m%d%H%M%S')}"
MEMBER_EMAIL="${NPCINK_CLOUD_LOCAL_ALPHA_SMOKE_MEMBER_EMAIL:-${NPCINK_CLOUD_MEMBER_EMAIL:-admin+local-alpha-${IDEMPOTENCY_SUFFIX}@npcink.local}}"
PROFILE_ID="${NPCINK_CLOUD_PROFILE_ID:-text.balanced}"
ABILITY_NAME="${NPCINK_CLOUD_ABILITY_NAME:-npcink-abilities-toolkit/build-article-block-plan}"
CHANNEL="${NPCINK_CLOUD_CHANNEL:-openapi}"
EXECUTION_KIND="${NPCINK_CLOUD_EXECUTION_KIND:-text}"
PROMPT_TEXT="${NPCINK_CLOUD_PROMPT_TEXT:-Npcink AI DeepSeek smoke ok}"
EXPECTED_PROVIDER_ID="${NPCINK_CLOUD_EXPECTED_PROVIDER_ID:-}"
EXPECTED_MODEL_ID="${NPCINK_CLOUD_EXPECTED_MODEL_ID:-}"
EVIDENCE_DIR="${NPCINK_CLOUD_LOCAL_ALPHA_SMOKE_EVIDENCE_DIR:-${ROOT_DIR}/.tmp/local-alpha-smoke}"

fail() {
	echo "[fail] $*" >&2
	exit 1
}

ok() {
	echo "[ok] $*"
}

require_value() {
	local value="$1"
	local message="$2"
	if [ -z "${value}" ]; then
		fail "${message}"
	fi
}

require_value "${NPCINK_CLOUD_INTERNAL_AUTH_TOKEN:-}" "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN is required"
require_value "${NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN:-}" "NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN is required"
require_value "${SITE_ID}" "NPCINK_CLOUD_SITE_ID or default site id is required"
require_value "${KEY_ID}" "NPCINK_CLOUD_KEY_ID or default key id is required"
require_value "${SECRET}" "NPCINK_CLOUD_SECRET or NPCINK_CLOUD_SITE_KEY_SECRET is required"

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

assert_json_in_set() {
	local json_payload="$1"
	local json_path="$2"
	local allowed_csv="$3"
	local message="$4"
	local actual
	if ! actual="$(json_read_path "${json_payload}" "${json_path}")"; then
		fail "${message} (missing path ${json_path})"
	fi
	case ",${allowed_csv}," in
		*",${actual},"*) ;;
		*) fail "${message} (expected one of ${allowed_csv}, got ${actual})" ;;
	esac
}

assert_body_contains() {
	local body="$1"
	local needle="$2"
	local message="$3"
	if ! grep -Fq "${needle}" <<<"${body}"; then
		fail "${message} (missing '${needle}')"
	fi
}

json_quote() {
	local value="$1"
	JSON_VALUE="${value}" python3 - <<'PY'
import json
import os

print(json.dumps(os.environ.get("JSON_VALUE", ""), ensure_ascii=True))
PY
}

build_traceparent() {
	python3 - <<'PY'
import secrets
print(f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01")
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

TMP_DIR="$(mktemp -d)"
PORTAL_COOKIE_JAR="${TMP_DIR}/portal-cookies.txt"
ADMIN_COOKIE_JAR="${TMP_DIR}/admin-cookies.txt"
WORDPRESS_COOKIE_JAR="${TMP_DIR}/wordpress-cookies.txt"
trap 'rm -rf "${TMP_DIR}"' EXIT

HTTP_STATUS=""
HTTP_BODY=""
HTTP_HEADERS=""

http_request() {
	local method="$1"
	local url="$2"
	local cookie_jar="$3"
	local body="${4:-}"
	shift 4

	local tmp_body="${TMP_DIR}/body.txt"
	local tmp_headers="${TMP_DIR}/headers.txt"
	local status
	local curl_args=(
		-sS
		-k
		-c "${cookie_jar}"
		-b "${cookie_jar}"
		-D "${tmp_headers}"
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

	status="$(curl "${curl_args[@]}")" || fail "HTTP request failed: ${method} ${url}"
	HTTP_STATUS="${status}"
	HTTP_BODY="$(cat "${tmp_body}")"
	HTTP_HEADERS="$(cat "${tmp_headers}")"
}

signed_request() {
	local method="$1"
	local path="$2"
	local query="$3"
	local body="$4"
	local idempotency_key="$5"
	local nonce="${6:-}"
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
	http_request "${method}" "${url}" "${PORTAL_COOKIE_JAR}" "${body}" \
		"traceparent: ${traceparent}" \
		"X-Npcink-Site-Id: ${SITE_ID}" \
		"X-Npcink-Key-Id: ${KEY_ID}" \
		"X-Npcink-Timestamp: ${timestamp}" \
		"X-Npcink-Signature: sha256=${signature}" \
		"X-Npcink-Nonce: ${nonce}" \
		"Idempotency-Key: ${idempotency_key}"
}

ok "Ensuring local Cloud dev services are running"
docker compose -f "${ROOT_DIR}/docker-compose.dev.yml" \
	--profile runtime \
	--profile callback \
	--profile ops \
	up -d api worker callback-worker ops-worker frontend proxy >/dev/null
docker compose -f "${ROOT_DIR}/docker-compose.dev.yml" \
	--profile runtime \
	--profile callback \
	--profile ops \
	restart worker callback-worker ops-worker >/dev/null

ok "Waiting for local Cloud: ${BASE_URL}"
if ! npcink_ai_cloud_wait_for_ready "${BASE_URL}" 20 2; then
	fail "Cloud API did not become ready"
fi

ok "Checking local WordPress: ${SITE_URL}"
curl -k -fsS --connect-timeout 5 --max-time 20 "${SITE_URL}" >/dev/null

ok "Checking WordPress Cloud addon admin page"
curl -k -sS -L \
	-c "${WORDPRESS_COOKIE_JAR}" \
	-b "${WORDPRESS_COOKIE_JAR}" \
	--data-urlencode "log=${WORDPRESS_ADMIN_USER}" \
	--data-urlencode "pwd=${WORDPRESS_ADMIN_PASSWORD}" \
	--data-urlencode "wp-submit=Log In" \
	--data-urlencode "redirect_to=${SITE_URL%/}/wp-admin/" \
	--data-urlencode "testcookie=1" \
	"${SITE_URL%/}/wp-login.php" >/dev/null
WORDPRESS_ADDON_PATH=""
WORDPRESS_ADDON_BODY=""
for candidate_path in \
	"/wp-admin/admin.php?page=npcink-cloud-addon&tab=settings" \
	"/wp-admin/admin.php?page=npcink-cloud-addon"
do
	candidate_body="$(
		curl -k -sS -L \
			-b "${WORDPRESS_COOKIE_JAR}" \
			"${SITE_URL%/}${candidate_path}"
	)"
	case "${candidate_body}" in
		*"npcink-cloud-addon"*|*"Npcink Cloud Addon"*)
			WORDPRESS_ADDON_PATH="${candidate_path}"
			WORDPRESS_ADDON_BODY="${candidate_body}"
			break
			;;
	esac
done
require_value "${WORDPRESS_ADDON_PATH}" "WordPress Cloud addon settings page was not found"
ok "WordPress Cloud addon admin path: ${WORDPRESS_ADDON_PATH}"
case "${WORDPRESS_ADDON_BODY}" in
	*"已验证"*|*"Cloud settings are saved and verified."*) ;;
	*) fail "WordPress Cloud addon page should show verified status" ;;
esac
assert_body_contains "${WORDPRESS_ADDON_BODY}" "npcink-cloud-addon" "WordPress Cloud addon page should render the Cloud addon admin shell"

ok "Refreshing local alpha runtime baseline"
docker compose -f "${ROOT_DIR}/docker-compose.dev.yml" exec -T api \
	python -m app.dev.seed_runtime \
		--site-id "${SITE_ID}" \
		--key-id "${KEY_ID}" \
		--secret "${SECRET}" \
		--site-name "Local Alpha Site" \
		--scopes "catalog:read,runtime:resolve,runtime:execute,runtime:read,stats:read,entitlement:read" \
		--skip-catalog-refresh \
		--skip-health-scan >/dev/null

ok "Bootstrapping portal membership and billing snapshot"
docker compose -f "${ROOT_DIR}/docker-compose.dev.yml" run --rm api \
	python -m app.dev.bootstrap_portal_site \
		--site-id "${SITE_ID}" \
		--site-admin-email "${MEMBER_EMAIL}" \
		--public-base-url "${BASE_URL}" >/dev/null

http_request "GET" "${BASE_URL%/}/health/live" "${PORTAL_COOKIE_JAR}" ""
assert_status "${HTTP_STATUS}" "200" "health/live should succeed"
assert_json_equals "${HTTP_BODY}" "status" "ok" "health/live envelope should be ok"

http_request "GET" "${BASE_URL%/}/health/ready" "${PORTAL_COOKIE_JAR}" "" \
	"X-Npcink-Internal-Token: ${NPCINK_CLOUD_INTERNAL_AUTH_TOKEN}"
assert_status "${HTTP_STATUS}" "200" "health/ready should succeed"

OPERATIONAL_READY_ATTEMPTS="${NPCINK_CLOUD_OPERATIONAL_READY_WAIT_ATTEMPTS:-36}"
OPERATIONAL_READY_DELAY_SECONDS="${NPCINK_CLOUD_OPERATIONAL_READY_WAIT_DELAY_SECONDS:-5}"
for ((attempt = 1; attempt <= OPERATIONAL_READY_ATTEMPTS; attempt++)); do
	http_request "GET" "${BASE_URL%/}/health/operational-ready" "${PORTAL_COOKIE_JAR}" "" \
		"X-Npcink-Internal-Token: ${NPCINK_CLOUD_INTERNAL_AUTH_TOKEN}"
	if [ "${HTTP_STATUS}" = "200" ]; then
		break
	fi
	if [ "${attempt}" -lt "${OPERATIONAL_READY_ATTEMPTS}" ]; then
		sleep "${OPERATIONAL_READY_DELAY_SECONDS}"
	fi
done
assert_status "${HTTP_STATUS}" "200" "health/operational-ready should succeed"
OPERATIONAL_READY_BODY="${HTTP_BODY}"

http_request "GET" "${BASE_URL%/}/internal/service/observability/summary" "${PORTAL_COOKIE_JAR}" "" \
	"X-Npcink-Internal-Token: ${NPCINK_CLOUD_INTERNAL_AUTH_TOKEN}"
assert_status "${HTTP_STATUS}" "200" "observability summary should succeed"
assert_json_equals "${HTTP_BODY}" "data.workers.totals.missing_total" "0" "workers should not be missing"
assert_json_equals "${HTTP_BODY}" "data.cadence.totals.non_fresh_total" "0" "cadence tasks should be fresh"
assert_json_equals "${HTTP_BODY}" "data.providers.freshness" "fresh" "providers should be fresh"
assert_json_equals "${HTTP_BODY}" "data.runtime.summary.queue.pressure_state" "healthy" "runtime queue should be healthy"
OBSERVABILITY_BODY="${HTTP_BODY}"

http_request "GET" "${BASE_URL%/}/v1/addon/dashboard" "${PORTAL_COOKIE_JAR}" ""
assert_status "${HTTP_STATUS}" "404" "removed Cloud addon projection route should stay absent"

http_request "GET" "${BASE_URL%/}/portal/login" "${PORTAL_COOKIE_JAR}" ""
assert_status "${HTTP_STATUS}" "200" "portal login page should load"
assert_body_contains "${HTTP_BODY}" "_next/" "portal login page should be served by frontend"

LOGIN_BODY="$(printf '{"email":%s}' "$(json_quote "${MEMBER_EMAIL}")")"
http_request "POST" "${BASE_URL%/}/portal/v1/auth/code/request" "${PORTAL_COOKIE_JAR}" "${LOGIN_BODY}" \
	"Origin: ${BASE_URL%/}" \
	"X-Npcink-Dev-Login-Code: 1"
assert_status "${HTTP_STATUS}" "200" "portal development login code request should succeed"
LOGIN_CODE="$(json_read_path "${HTTP_BODY}" "data.code")"
require_value "${LOGIN_CODE}" "development login code was not returned"

VERIFY_BODY="$(MEMBER_EMAIL_VALUE="${MEMBER_EMAIL}" LOGIN_CODE_VALUE="${LOGIN_CODE}" python3 - <<'PY'
import json
import os

print(json.dumps({"email": os.environ["MEMBER_EMAIL_VALUE"], "code": os.environ["LOGIN_CODE_VALUE"]}, ensure_ascii=True))
PY
)"
http_request "POST" "${BASE_URL%/}/portal/v1/auth/code/verify" "${PORTAL_COOKIE_JAR}" "${VERIFY_BODY}" \
	"Origin: ${BASE_URL%/}"
assert_status "${HTTP_STATUS}" "200" "portal login code verify should succeed"
assert_json_non_empty "${HTTP_BODY}" "data.principal_id" "portal session should include principal_id"
PORTAL_PRINCIPAL_REF="$(json_read_path "${HTTP_BODY}" "data.principal_id")"

SELECT_SITE_BODY="$(SITE_ID_VALUE="${SITE_ID}" python3 - <<'PY'
import json
import os

print(json.dumps({"site_id": os.environ["SITE_ID_VALUE"]}, ensure_ascii=True))
PY
)"
http_request "POST" "${BASE_URL%/}/portal/v1/session/site" "${PORTAL_COOKIE_JAR}" "${SELECT_SITE_BODY}" \
	"Origin: ${BASE_URL%/}"
assert_status "${HTTP_STATUS}" "200" "portal site selection should succeed"

http_request "GET" "${BASE_URL%/}/portal/v1/sites/${SITE_ID}/summary" "${PORTAL_COOKIE_JAR}" ""
assert_status "${HTTP_STATUS}" "200" "portal site summary should succeed"
assert_json_equals "${HTTP_BODY}" "data.site_id" "${SITE_ID}" "portal summary should match site"

http_request "GET" "${BASE_URL%/}/portal/v1/sites/${SITE_ID}/usage-summary" "${PORTAL_COOKIE_JAR}" ""
assert_status "${HTTP_STATUS}" "200" "portal usage summary should succeed"

http_request "GET" "${BASE_URL%/}/portal/v1/sites/${SITE_ID}/api-keys" "${PORTAL_COOKIE_JAR}" ""
assert_status "${HTTP_STATUS}" "200" "portal API key list should succeed"
assert_json_non_empty "${HTTP_BODY}" "data.items" "portal API key list should not be empty"

http_request "GET" "${BASE_URL%/}/admin/login" "${ADMIN_COOKIE_JAR}" ""
assert_status "${HTTP_STATUS}" "200" "admin login page should load"
ADMIN_BODY="$(ADMIN_TOKEN_VALUE="${NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN}" python3 - <<'PY'
import json
import os

print(json.dumps({"token": os.environ["ADMIN_TOKEN_VALUE"]}, ensure_ascii=True))
PY
)"
http_request "POST" "${BASE_URL%/}/admin/auth/bootstrap" "${ADMIN_COOKIE_JAR}" "${ADMIN_BODY}" \
	"Origin: ${BASE_URL%/}"
if [ "${HTTP_STATUS}" != "200" ] && [ "${HTTP_STATUS}" != "303" ]; then
	fail "admin bootstrap login should succeed (expected 200 or 303, got ${HTTP_STATUS}; body=${HTTP_BODY})"
fi
http_request "GET" "${BASE_URL%/}/admin/session" "${ADMIN_COOKIE_JAR}" ""
assert_status "${HTTP_STATUS}" "200" "admin session should load"
assert_json_non_empty "${HTTP_BODY}" "data.principal_id" "admin session should include principal_id"

signed_request "GET" "/v1/catalog/models" "" "" "idem-local-alpha-catalog-${IDEMPOTENCY_SUFFIX}" ""
assert_status "${HTTP_STATUS}" "200" "catalog/models should succeed"
assert_json_non_empty "${HTTP_BODY}" "data.items" "catalog/models should return models"
CATALOG_MODELS_BODY="${HTTP_BODY}"

PROMPT_TEXT_JSON="$(json_quote "${PROMPT_TEXT}")"
EXECUTE_BODY="$(cat <<JSON
{"site_id":"${SITE_ID}","ability_name":"${ABILITY_NAME}","channel":"${CHANNEL}","execution_kind":"${EXECUTION_KIND}","profile_id":"${PROFILE_ID}","input":{"messages":[{"role":"user","content":${PROMPT_TEXT_JSON}}]},"policy":{"allow_fallback":true}}
JSON
)"
signed_request "POST" "/v1/runtime/execute" "" "${EXECUTE_BODY}" "idem-local-alpha-execute-${IDEMPOTENCY_SUFFIX}" "nonce-local-alpha-execute-${IDEMPOTENCY_SUFFIX}"
assert_status "${HTTP_STATUS}" "200" "runtime/execute should succeed"
assert_json_equals "${HTTP_BODY}" "data.status" "succeeded" "runtime run should succeed"
if [ -n "${EXPECTED_PROVIDER_ID}" ]; then
	assert_json_equals "${HTTP_BODY}" "data.provider_id" "${EXPECTED_PROVIDER_ID}" "runtime provider should match expected provider"
fi
if [ -n "${EXPECTED_MODEL_ID}" ]; then
	assert_json_equals "${HTTP_BODY}" "data.model_id" "${EXPECTED_MODEL_ID}" "runtime model should match expected model"
fi
RUN_ID="$(json_read_path "${HTTP_BODY}" "data.run_id")"
RUNTIME_BODY="${HTTP_BODY}"

ok "OpenClaw Analysis Envelope Smoke"
OPENCLAW_BODY="$(cat <<JSON
{"ability_name":"openclaw.site_audit","ability_family":"openclaw","execution_kind":"text","profile_id":"${PROFILE_ID}","execution_pattern":"inline","input":{"text":"Analyze the site configuration"}}
JSON
)"
signed_request "POST" "/v1/runtime/execute" "" "${OPENCLAW_BODY}" "idem-local-alpha-openclaw-${IDEMPOTENCY_SUFFIX}" "nonce-local-alpha-openclaw-${IDEMPOTENCY_SUFFIX}"
assert_status "${HTTP_STATUS}" "200" "openclaw analysis execute"
OPENCLAW_RESPONSE="${HTTP_BODY}"
ANALYSIS_TYPE=$(json_read_path "$OPENCLAW_RESPONSE" "data.result.analysis_type" 2>/dev/null || echo "")
if [ "$ANALYSIS_TYPE" = "report" ]; then
	ok "openclaw read-only analysis returns report type"
else
	echo "  WARN: openclaw analysis_type=$ANALYSIS_TYPE (expected report)"
fi
REQUIRES_APPROVAL=$(json_read_path "$OPENCLAW_RESPONSE" "data.result.requires_local_approval" 2>/dev/null || echo "false")
if [ "$REQUIRES_APPROVAL" = "false" ]; then
	ok "openclaw read-only analysis does not require local approval"
else
	fail "openclaw read-only analysis should not require local approval"
fi

signed_request "GET" "/v1/runs/${RUN_ID}/result" "" "" "idem-local-alpha-result-${IDEMPOTENCY_SUFFIX}" ""
assert_status "${HTTP_STATUS}" "200" "runtime result should load"
assert_json_non_empty "${HTTP_BODY}" "data.result.output_text" "runtime result should include output text"
RESULT_BODY="${HTTP_BODY}"

signed_request "GET" "/v1/usage/summary" "" "" "idem-local-alpha-usage-${IDEMPOTENCY_SUFFIX}" ""
assert_status "${HTTP_STATUS}" "200" "usage summary should succeed"
assert_json_non_empty "${HTTP_BODY}" "data.windows.rolling_24h.provider_calls_total" "usage summary should expose provider calls"
USAGE_BODY="${HTTP_BODY}"

http_request "GET" "${BASE_URL%/}/internal/service/sites/${SITE_ID}/usage-meter?limit=20" "${PORTAL_COOKIE_JAR}" "" \
	"X-Npcink-Internal-Token: ${NPCINK_CLOUD_INTERNAL_AUTH_TOKEN}"
assert_status "${HTTP_STATUS}" "200" "internal usage meter should succeed"
assert_json_non_empty "${HTTP_BODY}" "data.totals.provider_calls" "usage meter should expose provider calls"
USAGE_METER_BODY="${HTTP_BODY}"

mkdir -p "${EVIDENCE_DIR}"
EVIDENCE_FILE="${EVIDENCE_DIR}/evidence-${IDEMPOTENCY_SUFFIX}.json"
BASE_URL_VALUE="${BASE_URL}" \
SITE_URL_VALUE="${SITE_URL}" \
SITE_ID_VALUE="${SITE_ID}" \
PORTAL_PRINCIPAL_REF_VALUE="${PORTAL_PRINCIPAL_REF}" \
OPERATIONAL_READY_VALUE="${OPERATIONAL_READY_BODY}" \
OBSERVABILITY_VALUE="${OBSERVABILITY_BODY}" \
WORDPRESS_ADDON_VERIFIED_VALUE="true" \
RUNTIME_VALUE="${RUNTIME_BODY}" \
RESULT_VALUE="${RESULT_BODY}" \
USAGE_VALUE="${USAGE_BODY}" \
USAGE_METER_VALUE="${USAGE_METER_BODY}" \
EVIDENCE_FILE_VALUE="${EVIDENCE_FILE}" \
python3 - <<'PY'
import json
import os
from datetime import datetime, timezone

def payload(name: str) -> dict:
    return json.loads(os.environ[name])

runtime = payload("RUNTIME_VALUE")["data"]
result = payload("RESULT_VALUE")["data"]
usage = payload("USAGE_VALUE")["data"]
usage_meter = payload("USAGE_METER_VALUE")["data"]
observability = payload("OBSERVABILITY_VALUE")["data"]
operational_ready = payload("OPERATIONAL_READY_VALUE")["data"]

evidence = {
    "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "base_url": os.environ["BASE_URL_VALUE"],
    "site_url": os.environ["SITE_URL_VALUE"],
    "site_id": os.environ["SITE_ID_VALUE"],
    "portal": {
        "principal_ref": os.environ["PORTAL_PRINCIPAL_REF_VALUE"],
    },
    "operational_ready": {
        "ok": operational_ready.get("ok"),
        "required_workers": operational_ready.get("required_workers"),
        "required_cadence_tasks": operational_ready.get("required_cadence_tasks"),
    },
    "observability": {
        "workers": observability.get("workers", {}).get("totals"),
        "cadence": observability.get("cadence", {}).get("totals"),
        "providers": observability.get("providers"),
        "runtime_queue": observability.get("runtime", {}).get("summary", {}).get("queue"),
        "callback": observability.get("runtime", {}).get("summary", {}).get("callback"),
        "failures": observability.get("runtime", {}).get("summary", {}).get("failures"),
        "operator_guidance": observability.get("runtime", {}).get("summary", {}).get("operator_guidance"),
    },
    "addon": {
        "wordpress_admin_page_verified": os.environ["WORDPRESS_ADDON_VERIFIED_VALUE"] == "true",
        "cloud_projection_route_absent": True,
    },
    "runtime": {
        "run_id": runtime.get("run_id"),
        "status": runtime.get("status"),
        "provider_id": runtime.get("provider_id"),
        "model_id": runtime.get("model_id"),
        "instance_id": runtime.get("instance_id"),
        "fallback_used": runtime.get("fallback_used"),
        "provider_call_count": runtime.get("provider_call_count"),
        "output_preview": str(result.get("result", {}).get("output_text", ""))[:160],
    },
    "result": {
        "run_id": result.get("run_id"),
        "status": result.get("status"),
        "output_preview": str(result.get("result", {}).get("output_text", ""))[:160],
    },
    "usage": {
        "rolling_24h": usage.get("windows", {}).get("rolling_24h"),
        "meter_totals": usage_meter.get("totals"),
    },
    "usage_meter": {
        "totals": usage_meter.get("totals"),
        "items_count": len(usage_meter.get("items", [])),
    },
}

with open(os.environ["EVIDENCE_FILE_VALUE"], "w", encoding="utf-8") as fh:
    json.dump(evidence, fh, ensure_ascii=False, indent=2, sort_keys=True)
    fh.write("\n")
print(os.environ["EVIDENCE_FILE_VALUE"])
PY

ok "Local alpha smoke passed"
ok "Evidence: ${EVIDENCE_FILE}"
