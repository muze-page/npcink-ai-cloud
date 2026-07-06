#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"
npcink_ai_cloud_load_env_file "${ROOT_DIR}"

npcink_ai_cloud_require_cmd curl
npcink_ai_cloud_require_cmd mktemp

BASE_URL="${NPCINK_CLOUD_BASE_URL:-https://cloud.npc.ink}"
REQUIRE_SMOKE_ENV="0"
REQUIRE_ALIPAY_ENABLED="0"
RUN_RELEASE_SMOKE="0"

usage() {
	cat <<'USAGE'
Usage: bash deploy/small-customer-trial-preflight.sh [options]

Options:
  --base-url URL             Production base URL. Defaults to NPCINK_CLOUD_BASE_URL or https://cloud.npc.ink.
  --require-smoke-env        Fail if formal release-smoke credentials are missing.
  --require-alipay-enabled   Fail if Alipay public callbacks are not enabled.
  --run-release-smoke        Run deploy/release-smoke.sh after preflight passes.
  -h, --help                 Show this help.

This script never prints secret values. Pass secrets through NPCINK_CLOUD_ENV_FILE
or the process environment.
USAGE
}

while [ "$#" -gt 0 ]; do
	case "$1" in
		--base-url)
			BASE_URL="$2"
			shift 2
			;;
		--require-smoke-env)
			REQUIRE_SMOKE_ENV="1"
			shift
			;;
		--require-alipay-enabled)
			REQUIRE_ALIPAY_ENABLED="1"
			shift
			;;
		--run-release-smoke)
			RUN_RELEASE_SMOKE="1"
			REQUIRE_SMOKE_ENV="1"
			shift
			;;
		-h | --help)
			usage
			exit 0
			;;
		*)
			echo "[fail] Unknown argument: $1" >&2
			usage >&2
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

warn() {
	echo "[warn] $*" >&2
}

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

HTTP_STATUS=""
HTTP_BODY=""
HTTP_LOCATION=""

http_request() {
	local method="$1"
	local url="$2"
	local body="${3:-}"
	local tmp_body="${TMP_DIR}/body.txt"
	local tmp_headers="${TMP_DIR}/headers.txt"
	local status
	local curl_args=(
		-sS
		--connect-timeout 5
		--max-time 20
		-D "${tmp_headers}"
		-o "${tmp_body}"
		-w "%{http_code}"
		-X "${method}"
		"${url}"
		-H "Accept: application/json,text/html;q=0.9,*/*;q=0.8"
	)
	if [ -n "${body}" ]; then
		curl_args+=(-H "Content-Type: application/x-www-form-urlencoded" --data "${body}")
	fi
	status="$(curl "${curl_args[@]}")" || fail "HTTP request failed: ${method} ${url}"
	HTTP_STATUS="${status}"
	HTTP_BODY="$(cat "${tmp_body}")"
	HTTP_LOCATION="$(
		awk 'BEGIN{IGNORECASE=1} /^location:/ {print $2}' "${tmp_headers}" \
			| tr -d '\r' \
			| tail -n 1
	)"
}

assert_status() {
	local expected="$1"
	local message="$2"
	if [ "${HTTP_STATUS}" != "${expected}" ]; then
		fail "${message} (expected ${expected}, got ${HTTP_STATUS}; body=${HTTP_BODY})"
	fi
}

assert_status_in() {
	local allowed_csv="$1"
	local message="$2"
	case ",${allowed_csv}," in
		*",${HTTP_STATUS},"*) ;;
		*) fail "${message} (expected one of ${allowed_csv}, got ${HTTP_STATUS}; body=${HTTP_BODY})" ;;
	esac
}

assert_body_contains() {
	local needle="$1"
	local message="$2"
	if ! printf '%s' "${HTTP_BODY}" | grep -Fq -- "${needle}"; then
		fail "${message} (missing ${needle}; body=${HTTP_BODY})"
	fi
}

assert_location_contains() {
	local needle="$1"
	local message="$2"
	if ! printf '%s' "${HTTP_LOCATION}" | grep -Fq -- "${needle}"; then
		fail "${message} (missing ${needle}; location=${HTTP_LOCATION})"
	fi
}

require_env_key() {
	local key="$1"
	local value="${!key:-}"
	if [ -n "${value}" ]; then
		ok "${key} is set"
		return 0
	fi
	warn "${key} is missing"
	return 1
}

ok "Checking small-customer trial preflight: ${BASE_URL}"

http_request "GET" "${BASE_URL%/}/health/live"
assert_status "200" "health/live should be public and healthy"
assert_body_contains '"status":"ok"' "health/live should return ok envelope"
ok "health/live is healthy"

http_request "GET" "${BASE_URL%/}/health/ready"
assert_status "401" "health/ready should fail closed without internal token"
assert_body_contains "auth.internal_token_required" "health/ready should require internal token"
ok "health/ready fails closed without internal token"

http_request "GET" "${BASE_URL%/}/"
assert_status "200" "home page should load"
ok "home page loads"

http_request "GET" "${BASE_URL%/}/portal/login"
assert_status "200" "portal login page should load"
ok "portal login page loads"

http_request "GET" "${BASE_URL%/}/admin/login"
assert_status "200" "admin login page should load"
ok "admin login page loads"

http_request "GET" "${BASE_URL%/}/admin/service-settings"
assert_status_in "302,303,307" "admin service settings should redirect anonymous users to login"
assert_location_contains "/admin/login" "admin service settings should redirect to admin login"
ok "admin service settings is protected"

http_request "GET" "${BASE_URL%/}/open/payments/alipay/return?out_trade_no=preflight&trade_status=TRADE_SUCCESS"
case "${HTTP_STATUS}" in
	303)
		assert_location_contains "/portal/billing" "enabled Alipay return should redirect to Portal billing"
		assert_location_contains "payment_return=alipay" "enabled Alipay return should mark provider in redirect"
		ok "Alipay return callback is enabled"
		;;
	501)
		if [ "${REQUIRE_ALIPAY_ENABLED}" = "1" ]; then
			fail "Alipay return callback is not enabled; configure /admin/service-settings before paid Pro trial"
		fi
		warn "Alipay return callback is not enabled yet"
		;;
	*)
		fail "Alipay return callback returned unexpected status ${HTTP_STATUS}; body=${HTTP_BODY}"
		;;
esac

http_request "POST" "${BASE_URL%/}/open/payments/alipay/notify" ""
case "${HTTP_STATUS}" in
	400)
		ok "Alipay notify rejects unsigned/empty callback while enabled"
		;;
	501)
		if [ "${REQUIRE_ALIPAY_ENABLED}" = "1" ]; then
			fail "Alipay notify callback is not enabled; configure /admin/service-settings before paid Pro trial"
		fi
		warn "Alipay notify callback is not enabled yet"
		;;
	200)
		if [ "${HTTP_BODY}" = "success" ]; then
			fail "Alipay notify accepted an empty callback; payment activation would be unsafe"
		fi
		fail "Alipay notify returned unexpected 200 response; body=${HTTP_BODY}"
		;;
	*)
		fail "Alipay notify callback returned unexpected status ${HTTP_STATUS}; body=${HTTP_BODY}"
		;;
esac

missing_env="0"
for key in \
	NPCINK_CLOUD_INTERNAL_AUTH_TOKEN \
	NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN \
	NPCINK_CLOUD_RELEASE_MEMBER_EMAIL \
	NPCINK_CLOUD_PORTAL_LOGIN_CODE \
	NPCINK_CLOUD_RELEASE_SITE_ID \
	NPCINK_CLOUD_RELEASE_KEY_ID \
	NPCINK_CLOUD_RELEASE_KEY_SECRET
do
	if ! require_env_key "${key}"; then
		missing_env="1"
	fi
done

if [ "${missing_env}" = "1" ]; then
	if [ "${REQUIRE_SMOKE_ENV}" = "1" ]; then
		fail "formal release smoke credentials are incomplete"
	fi
	warn "Formal deploy/release-smoke.sh is not runnable until the missing values are supplied."
else
	ok "formal release smoke credentials are present"
fi

if [ "${RUN_RELEASE_SMOKE}" = "1" ]; then
	ok "Running formal release smoke"
	bash "${ROOT_DIR}/deploy/release-smoke.sh" --base-url "${BASE_URL}"
fi

ok "Small-customer trial preflight completed"
