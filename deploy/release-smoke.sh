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
INTERNAL_AUTH_TOKEN="${NPCINK_CLOUD_INTERNAL_AUTH_TOKEN:-}"
ADMIN_KEY="${NPCINK_CLOUD_ADMIN_KEY:-}"
MEMBER_EMAIL="${NPCINK_CLOUD_RELEASE_MEMBER_EMAIL:-}"
LOGIN_CODE="${NPCINK_CLOUD_PORTAL_LOGIN_CODE:-}"
RUNTIME_SITE_ID="${NPCINK_CLOUD_RELEASE_SITE_ID:-}"
RUNTIME_KEY_ID="${NPCINK_CLOUD_RELEASE_KEY_ID:-}"
RUNTIME_SECRET="${NPCINK_CLOUD_RELEASE_KEY_SECRET:-}"
PERSISTED_PORTAL_COOKIE_JAR="${NPCINK_CLOUD_PORTAL_COOKIE_JAR:-}"
CREDENTIALS_FILE=""

while [ "$#" -gt 0 ]; do
	case "$1" in
		--base-url)
			BASE_URL="$2"
			shift 2
			;;
		--internal-auth-token)
			echo "[fail] --internal-auth-token is forbidden because process arguments are observable; use --credentials-file or NPCINK_CLOUD_INTERNAL_AUTH_TOKEN." >&2
			exit 1
			;;
		--admin-key)
			echo "[fail] --admin-key is forbidden because process arguments are observable; use --credentials-file or operator-only NPCINK_CLOUD_ADMIN_KEY." >&2
			exit 1
			;;
		--member-email)
			MEMBER_EMAIL="$2"
			shift 2
			;;
		--login-code)
			echo "[fail] --login-code is forbidden because process arguments are observable; use --credentials-file or NPCINK_CLOUD_PORTAL_LOGIN_CODE." >&2
			exit 1
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
			echo "[fail] --runtime-secret is forbidden because process arguments are observable; use --credentials-file or NPCINK_CLOUD_RELEASE_KEY_SECRET." >&2
			exit 1
			;;
		--credentials-file)
			CREDENTIALS_FILE="$2"
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

load_credentials_file() {
	local credentials_file="$1"
	local assignments=""
	if ! assignments="$(python3 - "${credentials_file}" <<'PY'
from __future__ import annotations

import json
import os
import shlex
import stat
import sys

path = sys.argv[1]
metadata = os.lstat(path)
if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
    raise SystemExit("[fail] Release smoke credentials must be a regular non-symlink file.")
if metadata.st_uid != os.geteuid():
    raise SystemExit("[fail] Release smoke credentials must be owned by the current account.")
if stat.S_IMODE(metadata.st_mode) != 0o600:
    raise SystemExit("[fail] Release smoke credentials must have mode 0600.")
with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)
if not isinstance(payload, dict):
    raise SystemExit("[fail] Release smoke credentials must be a JSON object.")
mapping = {
    "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN": "INTERNAL_AUTH_TOKEN",
    "NPCINK_CLOUD_ADMIN_KEY": "ADMIN_KEY",
    "NPCINK_CLOUD_RELEASE_MEMBER_EMAIL": "MEMBER_EMAIL",
    "NPCINK_CLOUD_PORTAL_LOGIN_CODE": "LOGIN_CODE",
    "NPCINK_CLOUD_RELEASE_SITE_ID": "RUNTIME_SITE_ID",
    "NPCINK_CLOUD_RELEASE_KEY_ID": "RUNTIME_KEY_ID",
    "NPCINK_CLOUD_RELEASE_KEY_SECRET": "RUNTIME_SECRET",
}
unknown = sorted(set(payload) - set(mapping))
if unknown:
    raise SystemExit("[fail] Release smoke credentials contain unsupported keys.")
for source, target in mapping.items():
    value = payload.get(source, "")
    if not isinstance(value, str):
        raise SystemExit(f"[fail] Release smoke credential {source} must be a string.")
    print(f"{target}={shlex.quote(value)}")
PY
)"; then
		return 1
	fi
	eval "${assignments}"
	unset assignments
}

if [ -n "${CREDENTIALS_FILE}" ]; then
	load_credentials_file "${CREDENTIALS_FILE}" || fail "Release smoke credentials could not be loaded"
fi

# Do not let the complete caller environment, including credentials supplied by
# GitHub Actions, flow into every curl/Python child process.
unset \
	NPCINK_CLOUD_INTERNAL_AUTH_TOKEN \
	NPCINK_CLOUD_ADMIN_KEY \
	NPCINK_CLOUD_PORTAL_LOGIN_CODE \
	NPCINK_CLOUD_RELEASE_KEY_SECRET

if [ -z "${INTERNAL_AUTH_TOKEN}" ]; then
	fail "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN is required through --credentials-file or the process environment"
fi
if [ -z "${ADMIN_KEY}" ]; then
	fail "operator-only NPCINK_CLOUD_ADMIN_KEY is required through --credentials-file or the process environment"
fi
if [ -z "${MEMBER_EMAIL}" ]; then
	fail "--member-email or NPCINK_CLOUD_RELEASE_MEMBER_EMAIL is required"
fi
if [ -z "${RUNTIME_SITE_ID}" ] || [ -z "${RUNTIME_KEY_ID}" ] || [ -z "${RUNTIME_SECRET}" ]; then
	fail "release smoke requires signed runtime credentials through --credentials-file or the process environment"
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
		fail "${message} (expected ${expected}, got ${actual})"
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
		echo "[fail] Release smoke credential-file cleanup did not complete." >&2
		exit_status=1
	fi
	exit "${exit_status}"
}
trap cleanup_tmp_dir EXIT
chmod 0700 "${TMP_DIR}"
if [ -n "${PERSISTED_PORTAL_COOKIE_JAR}" ]; then
	if [ -L "${PERSISTED_PORTAL_COOKIE_JAR}" ]; then
		fail "NPCINK_CLOUD_PORTAL_COOKIE_JAR must not be a symbolic link"
	fi
	if [ -e "${PERSISTED_PORTAL_COOKIE_JAR}" ] && [ ! -f "${PERSISTED_PORTAL_COOKIE_JAR}" ]; then
		fail "NPCINK_CLOUD_PORTAL_COOKIE_JAR must be a regular file"
	fi
	PORTAL_COOKIE_PARENT="$(dirname "${PERSISTED_PORTAL_COOKIE_JAR}")"
	if [ ! -d "${PORTAL_COOKIE_PARENT}" ]; then
		fail "NPCINK_CLOUD_PORTAL_COOKIE_JAR parent directory does not exist"
	fi
	umask 077
	touch "${PERSISTED_PORTAL_COOKIE_JAR}"
	chmod 600 "${PERSISTED_PORTAL_COOKIE_JAR}"
	PORTAL_COOKIE_JAR="${PERSISTED_PORTAL_COOKIE_JAR}"
else
	PORTAL_COOKIE_JAR="${TMP_DIR}/portal-cookies.txt"
fi
ADMIN_COOKIE_JAR="${TMP_DIR}/admin-cookies.txt"

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

	local request_id="${RANDOM:-0}-$$"
	local tmp_body="${TMP_DIR}/body-${request_id}.txt"
	local tmp_headers="${TMP_DIR}/headers-${request_id}.txt"
	local request_headers="${TMP_DIR}/request-${request_id}.headers"
	local request_body="${TMP_DIR}/request-${request_id}.body"
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
		fail "Release smoke request-file cleanup failed"
	fi
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
assert_json_non_empty "${HTTP_BODY}" "data.tracing.otlp_configured" "observability summary should expose the external exporter configuration fact"
assert_json_non_empty "${HTTP_BODY}" "data.tracing.trace_query_configured" "observability summary should expose the external query configuration fact"
case "${BASE_URL}" in
	https://*)
		assert_json_equals "${HTTP_BODY}" "data.tracing.otlp_configured" "true" "formal HTTPS release smoke requires an external OTLP exporter"
		assert_json_non_empty "${HTTP_BODY}" "data.tracing.otlp_endpoint" "formal HTTPS release smoke requires an external OTLP exporter endpoint"
		assert_json_equals "${HTTP_BODY}" "data.tracing.trace_query_configured" "true" "formal HTTPS release smoke requires an external trace query surface"
		assert_json_non_empty "${HTTP_BODY}" "data.tracing.trace_query_url" "formal HTTPS release smoke requires an external trace query URL"
		;;
esac

RUNTIME_IDEMPOTENCY_SUFFIX="${NPCINK_CLOUD_IDEMPOTENCY_SUFFIX:-release-smoke-$(date -u +%Y%m%d%H%M%S)}"
NPCINK_CLOUD_INTERNAL_AUTH_TOKEN="${INTERNAL_AUTH_TOKEN}" \
NPCINK_CLOUD_SECRET="${RUNTIME_SECRET}" \
NPCINK_CLOUD_IDEMPOTENCY_SUFFIX="${RUNTIME_IDEMPOTENCY_SUFFIX}" \
	bash "${ROOT_DIR}/deploy/remote-smoke.sh" \
		--base-url "${BASE_URL}" \
		--site-id "${RUNTIME_SITE_ID}" \
		--key-id "${RUNTIME_KEY_ID}"

http_request "GET" "${BASE_URL%/}/" "${PORTAL_COOKIE_JAR}"
assert_status "${HTTP_STATUS}" "200" "home page should load"

http_request "GET" "${BASE_URL%/}/portal/login" "${PORTAL_COOKIE_JAR}"
assert_status "${HTTP_STATUS}" "200" "portal login page should load"

PORTAL_SESSION_REUSED="0"
if [ -n "${PERSISTED_PORTAL_COOKIE_JAR}" ] && [ -s "${PORTAL_COOKIE_JAR}" ]; then
	http_request "GET" "${BASE_URL%/}/portal/v1/session" "${PORTAL_COOKIE_JAR}"
	if [ "${HTTP_STATUS}" = "200" ] \
		&& json_read_path "${HTTP_BODY}" "data.principal_id" >/dev/null 2>&1; then
		PORTAL_SESSION_REUSED="1"
		ok "Reusing persisted Portal session without requesting an email code"
	fi
fi

if [ "${PORTAL_SESSION_REUSED}" = "0" ] && [ -z "${LOGIN_CODE}" ]; then
	REQUEST_BODY="$(MEMBER_EMAIL_VALUE="${MEMBER_EMAIL}" python3 - <<'PY'
import json
import os
print(json.dumps({"email": os.environ["MEMBER_EMAIL_VALUE"]}, ensure_ascii=True))
PY
)"
	http_request \
		"POST" \
		"${BASE_URL%/}/portal/v1/auth/code/request" \
		"${PORTAL_COOKIE_JAR}" \
		"${REQUEST_BODY}" \
		"Origin: ${BASE_URL%/}"
	assert_status "${HTTP_STATUS}" "200" "portal login code request should succeed"

	DELIVERY_MODE="$(json_read_path "${HTTP_BODY}" "data.delivery" 2>/dev/null || true)"
	STUB_LOGIN_CODE="$(json_read_path "${HTTP_BODY}" "data.code" 2>/dev/null || true)"
	if [ -n "${STUB_LOGIN_CODE}" ] && [ "${STUB_LOGIN_CODE}" != "null" ]; then
		LOGIN_CODE="${STUB_LOGIN_CODE}"
	fi
	if [ -z "${LOGIN_CODE}" ]; then
		fail "portal login code is required to continue; request delivery=${DELIVERY_MODE:-unknown}. Supply it through --credentials-file or NPCINK_CLOUD_PORTAL_LOGIN_CODE when using real SMTP delivery."
	fi
else
	if [ "${PORTAL_SESSION_REUSED}" = "0" ]; then
		ok "Using pre-issued Portal login code without requesting a replacement"
	fi
fi

if [ "${PORTAL_SESSION_REUSED}" = "0" ]; then
	VERIFY_BODY="$(MEMBER_EMAIL_VALUE="${MEMBER_EMAIL}" LOGIN_CODE_VALUE="${LOGIN_CODE}" python3 - <<'PY'
import json
import os
print(json.dumps({"email": os.environ["MEMBER_EMAIL_VALUE"], "code": os.environ["LOGIN_CODE_VALUE"]}, ensure_ascii=True))
PY
)"
	http_request \
		"POST" \
		"${BASE_URL%/}/portal/v1/auth/code/verify" \
		"${PORTAL_COOKIE_JAR}" \
		"${VERIFY_BODY}" \
		"Origin: ${BASE_URL%/}"
	assert_status "${HTTP_STATUS}" "200" "portal login code verify should succeed"
	assert_json_non_empty "${HTTP_BODY}" "data.principal_id" "portal session should include principal_id"
fi

http_request "GET" "${BASE_URL%/}/portal/v1/session" "${PORTAL_COOKIE_JAR}"
assert_status "${HTTP_STATUS}" "200" "portal session should load"
assert_json_non_empty "${HTTP_BODY}" "data.principal_id" "portal session response should include principal_id"

http_request "GET" "${BASE_URL%/}/admin/login" "${ADMIN_COOKIE_JAR}"
assert_status "${HTTP_STATUS}" "200" "admin login page should load"

ADMIN_BODY="$(ADMIN_KEY_VALUE="${ADMIN_KEY}" python3 - <<'PY'
import json
import os
print(json.dumps({"admin_key": os.environ["ADMIN_KEY_VALUE"]}, ensure_ascii=True))
PY
)"
INTERNAL_AS_ADMIN_BODY="$(INTERNAL_TOKEN_VALUE="${INTERNAL_AUTH_TOKEN}" python3 - <<'PY'
import json
import os
print(json.dumps({"admin_key": os.environ["INTERNAL_TOKEN_VALUE"]}, ensure_ascii=True))
PY
)"
http_request "POST" "${BASE_URL%/}/admin/auth/login" "${ADMIN_COOKIE_JAR}" "${INTERNAL_AS_ADMIN_BODY}" "Origin: ${BASE_URL%/}"
if [ "${HTTP_STATUS}" = "200" ]; then
	fail "internal token must not authenticate an admin session"
fi
http_request "POST" "${BASE_URL%/}/admin/auth/login" "${ADMIN_COOKIE_JAR}" "${ADMIN_BODY}" "Origin: ${BASE_URL%/}"
case "${HTTP_STATUS}" in
	200 | 303) ;;
	*) fail "admin key login should succeed (expected 200 or 303, got ${HTTP_STATUS})" ;;
esac
assert_body_contains "${HTTP_HEADERS}" "npcink_admin_session_token" "admin key login should set ops session cookie"

http_request "GET" "${BASE_URL%/}/admin/session" "${ADMIN_COOKIE_JAR}"
assert_status "${HTTP_STATUS}" "200" "admin session should load"
assert_json_non_empty "${HTTP_BODY}" "data.principal_id" "admin session should include principal_id"

ok "Release smoke passed"
