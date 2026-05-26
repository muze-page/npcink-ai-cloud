#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"
magick_ai_cloud_load_env_file "${ROOT_DIR}"

magick_ai_cloud_require_cmd curl
magick_ai_cloud_require_cmd python3

BASE_URL="${MAGICK_CLOUD_BASE_URL:-http://127.0.0.1:${MAGICK_CLOUD_PORT:-8010}}"
SITE_ID="${MAGICK_CLOUD_SITE_ID:-}"
MEMBER_EMAIL="${MAGICK_CLOUD_MEMBER_EMAIL:-}"
LOGIN_CODE="${MAGICK_CLOUD_PORTAL_LOGIN_CODE:-}"

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
			LOGIN_CODE="$2"
			shift 2
			;;
		*)
			echo "[fail] Unknown argument: $1" >&2
			exit 1
			;;
	esac
done

if [ -z "${SITE_ID}" ]; then
	echo "[fail] --site-id or MAGICK_CLOUD_SITE_ID is required" >&2
	exit 1
fi

if [ -z "${MEMBER_EMAIL}" ]; then
	echo "[fail] --member-email or MAGICK_CLOUD_MEMBER_EMAIL is required" >&2
	exit 1
fi

if [ -z "${LOGIN_CODE}" ]; then
	REQUEST_BODY="$(MEMBER_EMAIL_VALUE="${MEMBER_EMAIL}" python3 - <<'PY'
import json
import os

print(json.dumps({"email": os.environ["MEMBER_EMAIL_VALUE"]}, ensure_ascii=True))
PY
)"
	HTTP_BODY="$(
		curl -sS \
			-X POST \
			-H "Accept: application/json" \
			-H "Content-Type: application/json" \
			--data "${REQUEST_BODY}" \
			"${BASE_URL%/}/portal/v1/auth/code/request"
	)"
	LOGIN_CODE="$(JSON_PAYLOAD="${HTTP_BODY}" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["JSON_PAYLOAD"])
print(payload.get("data", {}).get("code", "") or "")
PY
)"
fi

if [ -z "${LOGIN_CODE}" ]; then
	echo "[fail] dev smoke requires a development login code; pass --login-code or enable the development-code seam" >&2
	exit 1
fi

exec bash "${ROOT_DIR}/deploy/remote-portal-smoke.sh" \
	--base-url "${BASE_URL}" \
	--site-id "${SITE_ID}" \
	--member-email "${MEMBER_EMAIL}" \
	--login-code "${LOGIN_CODE}"
