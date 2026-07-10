#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"
npcink_ai_cloud_load_env_file "${ROOT_DIR}"

npcink_ai_cloud_require_cmd curl
npcink_ai_cloud_require_cmd python3
npcink_ai_cloud_require_cmd mktemp

BASE_URL="${NPCINK_CLOUD_BASE_URL:-http://127.0.0.1:${NPCINK_CLOUD_PORT:-8010}}"
INTERNAL_AUTH_TOKEN="${NPCINK_CLOUD_INTERNAL_AUTH_TOKEN:-}"
ADMIN_TOKEN="${NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN:-}"
MEMBER_EMAIL="${NPCINK_CLOUD_RELEASE_MEMBER_EMAIL:-}"
LOGIN_CODE="${NPCINK_CLOUD_PORTAL_LOGIN_CODE:-}"
RUNTIME_SITE_ID="${NPCINK_CLOUD_RELEASE_SITE_ID:-}"
RUNTIME_KEY_ID="${NPCINK_CLOUD_RELEASE_KEY_ID:-}"
RUNTIME_SECRET="${NPCINK_CLOUD_RELEASE_KEY_SECRET:-}"

while [ "$#" -gt 0 ]; do
	case "$1" in
		--base-url)
			BASE_URL="$2"
			shift 2
			;;
		--internal-auth-token)
			INTERNAL_AUTH_TOKEN="$2"
			shift 2
			;;
		--admin-token)
			ADMIN_TOKEN="$2"
			shift 2
			;;
		--member-email)
			MEMBER_EMAIL="$2"
			shift 2
			;;
		--login-code)
			LOGIN_CODE="$2"
			shift 2
			;;
		--runtime-site-id)
			RUNTIME_SITE_ID="$2"
			shift 2
			;;
		--runtime-key-id)
			RUNTIME_KEY_ID="$2"
			shift 2
			;;
		--runtime-secret)
			RUNTIME_SECRET="$2"
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

if [ -z "${INTERNAL_AUTH_TOKEN}" ]; then
	fail "--internal-auth-token or NPCINK_CLOUD_INTERNAL_AUTH_TOKEN is required"
fi
if [ -z "${ADMIN_TOKEN}" ]; then
	fail "--admin-token or NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN is required"
fi
if [ -z "${MEMBER_EMAIL}" ]; then
	fail "--member-email or NPCINK_CLOUD_RELEASE_MEMBER_EMAIL is required"
fi
if [ -z "${RUNTIME_SITE_ID}" ] || [ -z "${RUNTIME_KEY_ID}" ] || [ -z "${RUNTIME_SECRET}" ]; then
	fail "release smoke requires signed runtime credentials: pass --runtime-site-id, --runtime-key-id, and --runtime-secret (or set NPCINK_CLOUD_RELEASE_SITE_ID, NPCINK_CLOUD_RELEASE_KEY_ID, and NPCINK_CLOUD_RELEASE_KEY_SECRET)"
fi

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
		fail "${message} (expected ${expected}, got ${actual}; body=${json_payload})"
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

TMP_DIR="$(mktemp -d)"
PORTAL_COOKIE_JAR="${TMP_DIR}/portal-cookies.txt"
ADMIN_COOKIE_JAR="${TMP_DIR}/admin-cookies.txt"
trap 'rm -rf "${TMP_DIR}"' EXIT

HTTP_STATUS=""
HTTP_BODY=""
HTTP_HEADERS=""

http_request() {
	local method="$1"
	local url="$2"
	local cookie_jar="$3"
	local body=""
	if [ "$#" -ge 4 ]; then
		body="${4:-}"
		shift 4
	else
		shift "$#"
	fi

	local tmp_body="${TMP_DIR}/body.txt"
	local tmp_headers="${TMP_DIR}/headers.txt"
	local status
	local curl_args=(
		-sS
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

ok "Waiting for cloud ready: ${BASE_URL}"
if ! npcink_ai_cloud_wait_for_ready "${BASE_URL}" 20 2; then
	fail "Cloud API did not become ready"
fi

http_request "GET" "${BASE_URL%/}/health/live" "${PORTAL_COOKIE_JAR}"
assert_status "${HTTP_STATUS}" "200" "live health should load"

http_request \
	"GET" \
	"${BASE_URL%/}/health/ready" \
	"${PORTAL_COOKIE_JAR}" \
	"" \
	"X-Npcink-Internal-Token: ${INTERNAL_AUTH_TOKEN}"
assert_status "${HTTP_STATUS}" "200" "ready health should load"

http_request \
	"GET" \
	"${BASE_URL%/}/health/operational-ready" \
	"${PORTAL_COOKIE_JAR}" \
	"" \
	"X-Npcink-Internal-Token: ${INTERNAL_AUTH_TOKEN}"
assert_status "${HTTP_STATUS}" "200" "operational readiness should load"
assert_json_non_empty "${HTTP_BODY}" "data.required_workers" "operational readiness should expose required workers"

http_request \
	"GET" \
	"${BASE_URL%/}/internal/service/observability/summary" \
	"${PORTAL_COOKIE_JAR}" \
	"" \
	"X-Npcink-Internal-Token: ${INTERNAL_AUTH_TOKEN}"
assert_status "${HTTP_STATUS}" "200" "observability summary should load"
assert_json_non_empty "${HTTP_BODY}" "data.cadence.totals.tasks_total" "observability summary should expose cadence totals"
assert_json_equals "${HTTP_BODY}" "data.workers.totals.missing_total" "0" "observability summary should not report missing workers"
assert_json_equals "${HTTP_BODY}" "data.cadence.totals.non_fresh_total" "0" "observability summary should not report stale cadence tasks"
assert_json_equals "${HTTP_BODY}" "data.providers.freshness" "fresh" "provider freshness should be fresh"
assert_json_equals "${HTTP_BODY}" "data.runtime.summary.callback.pressure_state" "healthy" "callback backlog should be healthy"
assert_json_non_empty "${HTTP_BODY}" "data.tracing.trace_sink_otlp_endpoint" "trace sink should be configured"

RUNTIME_IDEMPOTENCY_SUFFIX="${NPCINK_CLOUD_IDEMPOTENCY_SUFFIX:-release-smoke-$(date -u +%Y%m%d%H%M%S)}"
NPCINK_CLOUD_INTERNAL_AUTH_TOKEN="${INTERNAL_AUTH_TOKEN}" \
NPCINK_CLOUD_IDEMPOTENCY_SUFFIX="${RUNTIME_IDEMPOTENCY_SUFFIX}" \
	bash "${ROOT_DIR}/deploy/remote-smoke.sh" \
		--base-url "${BASE_URL}" \
		--site-id "${RUNTIME_SITE_ID}" \
		--key-id "${RUNTIME_KEY_ID}" \
		--secret "${RUNTIME_SECRET}"

http_request "GET" "${BASE_URL%/}/" "${PORTAL_COOKIE_JAR}"
assert_status "${HTTP_STATUS}" "200" "home page should load"

http_request "GET" "${BASE_URL%/}/portal/login" "${PORTAL_COOKIE_JAR}"
assert_status "${HTTP_STATUS}" "200" "portal login page should load"

if [ -z "${LOGIN_CODE}" ]; then
	REQUEST_BODY="$(MEMBER_EMAIL_VALUE="${MEMBER_EMAIL}" python3 - <<'PY'
import json
import os
print(json.dumps({"email": os.environ["MEMBER_EMAIL_VALUE"]}, ensure_ascii=True))
PY
)"
	http_request "POST" "${BASE_URL%/}/portal/v1/auth/code/request" "${PORTAL_COOKIE_JAR}" "${REQUEST_BODY}"
	assert_status "${HTTP_STATUS}" "200" "portal login code request should succeed"

	DELIVERY_MODE="$(json_read_path "${HTTP_BODY}" "data.delivery" 2>/dev/null || true)"
	STUB_LOGIN_CODE="$(json_read_path "${HTTP_BODY}" "data.code" 2>/dev/null || true)"
	if [ -n "${STUB_LOGIN_CODE}" ] && [ "${STUB_LOGIN_CODE}" != "null" ]; then
		LOGIN_CODE="${STUB_LOGIN_CODE}"
	fi
	if [ -z "${LOGIN_CODE}" ]; then
		fail "portal login code is required to continue; request delivery=${DELIVERY_MODE:-unknown}. Pass --login-code when using real SMTP delivery."
	fi
else
	ok "Using pre-issued Portal login code without requesting a replacement"
fi

VERIFY_BODY="$(MEMBER_EMAIL_VALUE="${MEMBER_EMAIL}" LOGIN_CODE_VALUE="${LOGIN_CODE}" python3 - <<'PY'
import json
import os
print(json.dumps({"email": os.environ["MEMBER_EMAIL_VALUE"], "code": os.environ["LOGIN_CODE_VALUE"]}, ensure_ascii=True))
PY
)"
http_request "POST" "${BASE_URL%/}/portal/v1/auth/code/verify" "${PORTAL_COOKIE_JAR}" "${VERIFY_BODY}"
assert_status "${HTTP_STATUS}" "200" "portal login code verify should succeed"
assert_json_non_empty "${HTTP_BODY}" "data.member_ref" "portal session should include member_ref"

http_request "GET" "${BASE_URL%/}/portal/v1/session" "${PORTAL_COOKIE_JAR}"
assert_status "${HTTP_STATUS}" "200" "portal session should load"
assert_json_non_empty "${HTTP_BODY}" "data.member_ref" "portal session response should include member_ref"

http_request "GET" "${BASE_URL%/}/admin/login" "${ADMIN_COOKIE_JAR}"
assert_status "${HTTP_STATUS}" "200" "admin login page should load"

ADMIN_BODY="$(ADMIN_TOKEN_VALUE="${ADMIN_TOKEN}" python3 - <<'PY'
import json
import os
print(json.dumps({"token": os.environ["ADMIN_TOKEN_VALUE"]}, ensure_ascii=True))
PY
)"
INTERNAL_AS_ADMIN_BODY="$(INTERNAL_TOKEN_VALUE="${INTERNAL_AUTH_TOKEN}" python3 - <<'PY'
import json
import os
print(json.dumps({"token": os.environ["INTERNAL_TOKEN_VALUE"]}, ensure_ascii=True))
PY
)"
http_request "POST" "${BASE_URL%/}/admin/auth/bootstrap" "${ADMIN_COOKIE_JAR}" "${INTERNAL_AS_ADMIN_BODY}" "Origin: ${BASE_URL%/}"
if [ "${HTTP_STATUS}" = "200" ]; then
	fail "internal token must not bootstrap an admin session"
fi
http_request "POST" "${BASE_URL%/}/admin/auth/bootstrap" "${ADMIN_COOKIE_JAR}" "${ADMIN_BODY}" "Origin: ${BASE_URL%/}"
assert_status "${HTTP_STATUS}" "200" "admin bootstrap login should succeed"
assert_body_contains "${HTTP_HEADERS}" "npcink_admin_session_token" "admin bootstrap should set ops session cookie"

http_request "GET" "${BASE_URL%/}/admin/session" "${ADMIN_COOKIE_JAR}"
assert_status "${HTTP_STATUS}" "200" "admin session should load"
assert_json_non_empty "${HTTP_BODY}" "data.platform_admin_ref" "admin session should include platform admin ref"

ok "Release smoke passed"
