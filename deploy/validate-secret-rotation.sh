#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"
npcink_ai_cloud_load_env_file "${ROOT_DIR}"

npcink_ai_cloud_require_cmd curl
npcink_ai_cloud_require_cmd python3
npcink_ai_cloud_require_cmd mktemp

BASE_URL="${NPCINK_CLOUD_BASE_URL:-http://127.0.0.1:${NPCINK_CLOUD_PORT:-8010}}"
UNKNOWN_EMAIL="${NPCINK_CLOUD_ROTATION_CHECK_EMAIL:-rotation-check@example.invalid}"
RUN_LOCAL_TESTS=0

while [ "$#" -gt 0 ]; do
	case "$1" in
		--base-url)
			BASE_URL="$2"
			shift 2
			;;
		--email)
			UNKNOWN_EMAIL="$2"
			shift 2
			;;
		--with-local-tests)
			RUN_LOCAL_TESTS=1
			shift
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

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

HTTP_STATUS=""
HTTP_BODY=""
HTTP_HEADERS=""

http_request() {
	local method="$1"
	local url="$2"
	local body="${3:-}"
	shift 3 || true

	local tmp_body="${TMP_DIR}/body.txt"
	local tmp_headers="${TMP_DIR}/headers.txt"
	local status
	local curl_args=(
		-sS
		-D "${tmp_headers}"
		-o "${tmp_body}"
		-w "%{http_code}"
		-X "${method}"
		"${url}"
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

assert_status() {
	local actual="$1"
	local expected="$2"
	local message="$3"
	if [ "${actual}" != "${expected}" ]; then
		fail "${message} (expected ${expected}, got ${actual}; body=${HTTP_BODY})"
	fi
}

json_get() {
	local payload="$1"
	local path="$2"
	JSON_PAYLOAD="${payload}" JSON_PATH="${path}" python3 - <<'PY'
import json
import os
import sys

payload = os.environ.get("JSON_PAYLOAD", "")
path = os.environ.get("JSON_PATH", "")

data = json.loads(payload)
current = data
for segment in path.split("."):
    if not segment:
        continue
    if isinstance(current, dict) and segment in current:
        current = current[segment]
    else:
        print("__missing__")
        sys.exit(0)

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

assert_json_equals() {
	local payload="$1"
	local path="$2"
	local expected="$3"
	local message="$4"
	local actual
	actual="$(json_get "${payload}" "${path}")"
	if [ "${actual}" != "${expected}" ]; then
		fail "${message} (expected ${path}=${expected}, got ${actual})"
	fi
}

assert_header_not_contains() {
	local headers="$1"
	local needle="$2"
	local message="$3"
	if printf '%s' "${headers}" | grep -Fqi "${needle}"; then
		fail "${message} (unexpected header fragment '${needle}')"
	fi
}

assert_header_contains() {
	local headers="$1"
	local needle="$2"
	local message="$3"
	if ! printf '%s' "${headers}" | grep -Fqi "${needle}"; then
		fail "${message} (missing header fragment '${needle}')"
	fi
}

npcink_ai_cloud_require_internal_token

if [ "${RUN_LOCAL_TESTS}" = "1" ] && [ -x "${ROOT_DIR}/.venv/bin/python" ]; then
	ok "Running local compile and targeted security tests"
	"${ROOT_DIR}/.venv/bin/python" -m py_compile \
		"${ROOT_DIR}/app/core/config.py" \
		"${ROOT_DIR}/app/api/portal_session.py" \
		"${ROOT_DIR}/app/api/routes/portal.py" \
		"${ROOT_DIR}/app/api/routes/web.py"
	"${ROOT_DIR}/.venv/bin/pytest" \
		"${ROOT_DIR}/tests/contract/test_security_config_contract.py" \
		"${ROOT_DIR}/tests/api/test_portal_routes.py" \
		"${ROOT_DIR}/tests/api/test_web_routes.py" -q
fi

ok "Waiting for cloud ready: ${BASE_URL}"
if ! npcink_ai_cloud_wait_for_ready "${BASE_URL}" 20 2; then
	fail "Cloud API did not become ready"
fi

http_request "GET" "${BASE_URL%/}/health/live" ""
assert_status "${HTTP_STATUS}" "200" "public liveness check should succeed"

http_request \
	"GET" \
	"${BASE_URL%/}/health/ready" \
	"" \
	"X-Npcink-Internal-Token: ${NPCINK_CLOUD_INTERNAL_AUTH_TOKEN}"
assert_status "${HTTP_STATUS}" "200" "internal readiness check should succeed"

http_request \
	"GET" \
	"${BASE_URL%/}/health/operational-ready" \
	"" \
	"X-Npcink-Internal-Token: ${NPCINK_CLOUD_INTERNAL_AUTH_TOKEN}"
assert_status "${HTTP_STATUS}" "200" "operational readiness should succeed with the rotated internal token"

http_request \
	"GET" \
	"${BASE_URL%/}/internal/service/observability/summary" \
	"" \
	"X-Npcink-Internal-Token: ${NPCINK_CLOUD_INTERNAL_AUTH_TOKEN}"
assert_status "${HTTP_STATUS}" "200" "observability summary should succeed with the rotated internal token"
assert_json_non_empty "${HTTP_BODY}" "data.tracing.trace_sink_otlp_endpoint" "observability summary should expose trace sink identity"

http_request "GET" "${BASE_URL%/}/portal/login" ""
assert_status "${HTTP_STATUS}" "200" "portal login page should load"

UNKNOWN_EMAIL_JSON="$(UNKNOWN_EMAIL_VALUE="${UNKNOWN_EMAIL}" python3 - <<'PY'
import json
import os
print(json.dumps({"email": os.environ["UNKNOWN_EMAIL_VALUE"]}, ensure_ascii=True))
PY
)"
http_request \
	"POST" \
	"${BASE_URL%/}/portal/v1/auth/code/request" \
	"${UNKNOWN_EMAIL_JSON}" \
	"Accept: application/json"
if [ "${HTTP_STATUS}" = "200" ]; then
	assert_json_equals "${HTTP_BODY}" "data.code" "" "login-code response should not expose verification code by default"
	ok "Portal login-code enumeration guard validated"
elif [ "${HTTP_STATUS}" = "503" ] && [ "$(json_get "${HTTP_BODY}" "error_code")" = "portal.email_delivery_unavailable" ]; then
	ok "Portal login-code enumeration guard skipped because portal email delivery is not configured"
else
	fail "login-code request produced unexpected response (status=${HTTP_STATUS}; body=${HTTP_BODY})"
fi

http_request \
	"GET" \
	"${BASE_URL%/}/admin/auth/bootstrap?redirect=%2Fadmin" \
	"" \
	"Accept: text/html"
assert_status "${HTTP_STATUS}" "303" "GET /admin/auth/bootstrap should redirect to admin login"
assert_header_contains "${HTTP_HEADERS}" "Location: /admin/login?redirect=%2Fadmin" "GET /admin/auth/bootstrap should redirect to admin login"

http_request \
	"POST" \
	"${BASE_URL%/}/admin/auth/bootstrap" \
	'token=wrong-token' \
	"Content-Type: application/x-www-form-urlencoded" \
	"Accept: text/html"
assert_status "${HTTP_STATUS}" "303" "invalid admin bootstrap should redirect with error"
assert_header_contains "${HTTP_HEADERS}" "auth.admin_bootstrap_token_invalid" "invalid admin bootstrap should surface token error"
assert_header_not_contains "${HTTP_HEADERS}" "npcink_admin_session_token=" "invalid admin bootstrap must not set ops session cookie"

ok "Secret rotation validation checks passed."
