#!/usr/bin/env bash
set -euo pipefail
set +x

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"
npcink_ai_cloud_load_env_file "${ROOT_DIR}"

npcink_ai_cloud_require_cmd curl
npcink_ai_cloud_require_cmd python3
npcink_ai_cloud_require_cmd mktemp

BASE_URL="${NPCINK_CLOUD_BASE_URL:-http://127.0.0.1:${NPCINK_CLOUD_PORT:-8010}}"
SITE_ID="${NPCINK_CLOUD_SITE_ID:-}"
MEMBER_EMAIL="${NPCINK_CLOUD_MEMBER_EMAIL:-}"
MEMBER_EMAIL_NORMALIZED="$(printf '%s' "${MEMBER_EMAIL}" | tr '[:upper:]' '[:lower:]')"
MEMBER_REF="${NPCINK_CLOUD_MEMBER_REF:-}"
LOGIN_CODE="${NPCINK_CLOUD_PORTAL_LOGIN_CODE:-}"

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
		--member-email)
			MEMBER_EMAIL="$2"
			MEMBER_EMAIL_NORMALIZED="$(printf '%s' "${MEMBER_EMAIL}" | tr '[:upper:]' '[:lower:]')"
			MEMBER_REF="user:${MEMBER_EMAIL_NORMALIZED}"
			shift 2
			;;
		--member-ref)
			MEMBER_REF="$2"
			shift 2
			;;
		--login-code)
			echo "[fail] --login-code is forbidden because process arguments are observable; use NPCINK_CLOUD_PORTAL_LOGIN_CODE or a protected environment file." >&2
			exit 1
			;;
		*)
			echo "[fail] Unknown argument: $1" >&2
			exit 1
			;;
	esac
done

unset NPCINK_CLOUD_PORTAL_LOGIN_CODE

fail() {
	echo "[fail] $*" >&2
	exit 1
}

ok() {
	echo "[ok] $*"
}

if [ -z "${MEMBER_REF}" ] && [ -n "${MEMBER_EMAIL_NORMALIZED}" ]; then
	MEMBER_REF="user:${MEMBER_EMAIL_NORMALIZED}"
fi
if [ -z "${SITE_ID}" ]; then
	fail "--site-id or NPCINK_CLOUD_SITE_ID is required"
fi
if [ -z "${MEMBER_EMAIL}" ] && [ -z "${MEMBER_REF}" ]; then
	fail "--member-email, --member-ref, or NPCINK_CLOUD_MEMBER_EMAIL is required"
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

umask 077
TMP_DIR="$(mktemp -d)"
TMP_CLEANUP_ARMED=1
cleanup_tmp_dir() {
	local exit_status="$?"
	local cleanup_failed=0
	trap - EXIT
	set +e
	if [ "${TMP_CLEANUP_ARMED}" = "1" ]; then
		rm -rf -- "${TMP_DIR}" || cleanup_failed=1
		if [ -e "${TMP_DIR}" ] || [ -L "${TMP_DIR}" ]; then
			cleanup_failed=1
		fi
	fi
	if [ "${cleanup_failed}" -ne 0 ]; then
		echo "[fail] Portal smoke credential-file cleanup did not complete." >&2
		exit_status=1
	fi
	exit "${exit_status}"
}
trap cleanup_tmp_dir EXIT
chmod 0700 "${TMP_DIR}"
COOKIE_JAR="${TMP_DIR}/cookies.txt"

HTTP_STATUS=""
HTTP_BODY=""
HTTP_HEADERS=""

http_request() {
	local method="$1"
	local url="$2"
	local body=""
	if [ "$#" -ge 3 ]; then
		body="${3:-}"
		shift 3
	else
		shift "$#"
	fi

	local request_id="${RANDOM:-0}-$$"
	local tmp_body="${TMP_DIR}/body-${request_id}.txt"
	local tmp_headers="${TMP_DIR}/headers-${request_id}.txt"
	local request_headers="${TMP_DIR}/request-${request_id}.headers"
	local request_body="${TMP_DIR}/request-${request_id}.body"
	local status
	local curl_args=(
		-sS
		-c "${COOKIE_JAR}"
		-b "${COOKIE_JAR}"
		-D "${tmp_headers}"
		-o "${tmp_body}"
		-w "%{http_code}"
		-X "${method}"
		"${url}"
		--header "@${request_headers}"
	)
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

	status="$(curl "${curl_args[@]}")" || fail "HTTP request failed: ${method} ${url}"
	HTTP_STATUS="${status}"
	HTTP_BODY="$(cat "${tmp_body}")"
	HTTP_HEADERS="$(cat "${tmp_headers}")"
	if ! rm -f -- "${tmp_body}" "${tmp_headers}" "${request_headers}" "${request_body}"; then
		fail "Portal smoke request-file cleanup failed"
	fi
}

ok "Waiting for cloud ready: ${BASE_URL}"
if ! npcink_ai_cloud_wait_for_ready "${BASE_URL}" 20 2; then
	fail "Cloud API did not become ready"
fi

http_request "GET" "${BASE_URL%/}/"
assert_status "${HTTP_STATUS}" "200" "buyer-facing home page should load"

http_request "GET" "${BASE_URL%/}/portal/login"
assert_status "${HTTP_STATUS}" "200" "portal login page should load"

LOGIN_BODY="$(printf '{"email":%s}' "$(MEMBER_EMAIL_VALUE="${MEMBER_EMAIL}" python3 - <<'PY'
import json
import os
print(json.dumps(os.environ["MEMBER_EMAIL_VALUE"], ensure_ascii=True))
PY
)")"
http_request "POST" "${BASE_URL%/}/portal/v1/auth/code/request" "${LOGIN_BODY}"
assert_status "${HTTP_STATUS}" "200" "portal login code request should succeed"
REQUESTED_MEMBER_REF="$(json_read_path "${HTTP_BODY}" "data.member_ref")"
if [ -n "${REQUESTED_MEMBER_REF}" ] && [ "${REQUESTED_MEMBER_REF}" != "null" ]; then
	MEMBER_REF="${REQUESTED_MEMBER_REF}"
fi
if [ -n "${LOGIN_CODE}" ]; then
	LOGIN_VERIFY_BODY="$(MEMBER_EMAIL_VALUE="${MEMBER_EMAIL}" LOGIN_CODE_VALUE="${LOGIN_CODE}" python3 - <<'PY'
import json
import os
print(json.dumps({"email": os.environ["MEMBER_EMAIL_VALUE"], "code": os.environ["LOGIN_CODE_VALUE"]}, ensure_ascii=True))
PY
)"
	http_request "POST" "${BASE_URL%/}/portal/v1/auth/code/verify" "${LOGIN_VERIFY_BODY}"
	assert_status "${HTTP_STATUS}" "200" "portal login code verification should succeed"
else
	fail "portal login code is required to continue; supply NPCINK_CLOUD_PORTAL_LOGIN_CODE through a protected environment file."
fi

http_request "GET" "${BASE_URL%/}/portal/v1/session"
assert_status "${HTTP_STATUS}" "200" "portal session should load"
assert_json_equals "${HTTP_BODY}" "data.member_ref" "${MEMBER_REF}" "portal session should match member_ref"

SELECT_SITE_BODY="{\"site_id\":\"${SITE_ID}\"}"
http_request "POST" "${BASE_URL%/}/portal/v1/session/site" "${SELECT_SITE_BODY}"
assert_status "${HTTP_STATUS}" "200" "portal site selection should succeed"

http_request "GET" "${BASE_URL%/}/portal/v1/session"
assert_status "${HTTP_STATUS}" "200" "portal session should load"
assert_json_equals "${HTTP_BODY}" "data.member_ref" "${MEMBER_REF}" "portal session should match member_ref"
assert_json_equals "${HTTP_BODY}" "data.site_id" "${SITE_ID}" "portal session should match selected site"

http_request "GET" "${BASE_URL%/}/portal/v1/sites/${SITE_ID}/summary"
assert_status "${HTTP_STATUS}" "200" "portal summary should load"
assert_json_equals "${HTTP_BODY}" "data.site_id" "${SITE_ID}" "portal summary should match site"

http_request "GET" "${BASE_URL%/}/portal/v1/sites/${SITE_ID}/usage-summary"
assert_status "${HTTP_STATUS}" "200" "portal usage summary should load"
assert_json_non_empty "${HTTP_BODY}" "data.windows.today.runs_total" "portal usage summary should expose runs_total"

http_request "GET" "${BASE_URL%/}/portal/v1/sites/${SITE_ID}/entitlements"
assert_status "${HTTP_STATUS}" "200" "portal entitlements should load"
assert_json_equals "${HTTP_BODY}" "data.site.site_id" "${SITE_ID}" "portal entitlements should match site"

http_request "GET" "${BASE_URL%/}/portal/v1/sites/${SITE_ID}/billing-snapshots/reconciliation"
assert_status "${HTTP_STATUS}" "200" "portal billing reconciliation should load"
assert_json_non_empty "${HTTP_BODY}" "data.snapshot.totals.runs" "portal billing snapshot should expose runs totals"

http_request "GET" "${BASE_URL%/}/portal/v1/sites/${SITE_ID}/api-keys"
assert_status "${HTTP_STATUS}" "200" "portal key list should load"
assert_json_non_empty "${HTTP_BODY}" "data.items" "portal key list should not be empty"

http_request "GET" "${BASE_URL%/}/portal/overview"
assert_status "${HTTP_STATUS}" "200" "portal overview page should render"

http_request "GET" "${BASE_URL%/}/portal/keys"
assert_status "${HTTP_STATUS}" "200" "portal key manager page should render"

ok "Remote portal smoke completed successfully."
