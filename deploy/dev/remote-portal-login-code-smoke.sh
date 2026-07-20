#!/usr/bin/env bash
set -euo pipefail
set +x

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"
npcink_ai_cloud_load_env_file "${ROOT_DIR}"

npcink_ai_cloud_require_cmd curl
npcink_ai_cloud_require_cmd python3
npcink_ai_cloud_require_cmd mktemp

BASE_URL="${NPCINK_CLOUD_BASE_URL:-http://127.0.0.1:${NPCINK_CLOUD_PORT:-8010}}"
SITE_ID="${NPCINK_CLOUD_SITE_ID:-}"
MEMBER_EMAIL="${NPCINK_CLOUD_MEMBER_EMAIL:-}"
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
			shift 2
			;;
		--login-code)
			echo "[fail] --login-code is forbidden because process arguments are observable; use NPCINK_CLOUD_PORTAL_LOGIN_CODE or the development-code seam." >&2
			exit 1
			;;
		*)
			echo "[fail] Unknown argument: $1" >&2
			exit 1
			;;
	esac
done

unset NPCINK_CLOUD_PORTAL_LOGIN_CODE

if [ -z "${SITE_ID}" ]; then
	echo "[fail] --site-id or NPCINK_CLOUD_SITE_ID is required" >&2
	exit 1
fi

if [ -z "${MEMBER_EMAIL}" ]; then
	echo "[fail] --member-email or NPCINK_CLOUD_MEMBER_EMAIL is required" >&2
	exit 1
fi

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
		echo "[fail] Development login-code credential-file cleanup did not complete." >&2
		exit_status=1
	fi
	exit "${exit_status}"
}
trap cleanup_tmp_dir EXIT
chmod 0700 "${TMP_DIR}"

if [ -z "${LOGIN_CODE}" ]; then
	REQUEST_BODY_FILE="${TMP_DIR}/login-code-request.body"
	REQUEST_HEADERS_FILE="${TMP_DIR}/login-code-request.headers"
	RESPONSE_BODY_FILE="${TMP_DIR}/login-code-response.body"
	REQUEST_BODY_PATH="${REQUEST_BODY_FILE}" MEMBER_EMAIL_VALUE="${MEMBER_EMAIL}" python3 - <<'PY'
import json
import os

path = os.environ["REQUEST_BODY_PATH"]
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump({"email": os.environ["MEMBER_EMAIL_VALUE"]}, handle, ensure_ascii=True)
PY
	printf '%s\n' \
		"Accept: application/json" \
		"Content-Type: application/json" \
		"X-Npcink-Dev-Login-Code: 1" >"${REQUEST_HEADERS_FILE}"
	chmod 0600 "${REQUEST_HEADERS_FILE}"
	curl -sS \
		-X POST \
		--header "@${REQUEST_HEADERS_FILE}" \
		--data-binary "@${REQUEST_BODY_FILE}" \
		-o "${RESPONSE_BODY_FILE}" \
		"${BASE_URL%/}/portal/v1/auth/code/request"
	chmod 0600 "${RESPONSE_BODY_FILE}"
	LOGIN_CODE="$(python3 - "${RESPONSE_BODY_FILE}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)
print(payload.get("data", {}).get("code", "") or "")
PY
)"
	if ! rm -f -- "${REQUEST_BODY_FILE}" "${REQUEST_HEADERS_FILE}" "${RESPONSE_BODY_FILE}"; then
		echo "[fail] Development login-code request-file cleanup did not complete." >&2
		exit 1
	fi
fi

if [ -z "${LOGIN_CODE}" ]; then
	echo "[fail] dev smoke requires a development login code; use NPCINK_CLOUD_PORTAL_LOGIN_CODE or enable the development-code seam" >&2
	exit 1
fi

NPCINK_CLOUD_PORTAL_LOGIN_CODE="${LOGIN_CODE}" \
bash "${ROOT_DIR}/deploy/remote-portal-smoke.sh" \
	--base-url "${BASE_URL}" \
	--site-id "${SITE_ID}" \
	--member-email "${MEMBER_EMAIL}"
