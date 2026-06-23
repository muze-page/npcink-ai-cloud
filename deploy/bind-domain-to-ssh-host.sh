#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SSH_HOST="${NPCINK_CLOUD_DEPLOY_SSH_HOST:-}"
SSH_USER="${NPCINK_CLOUD_DEPLOY_SSH_USER:-}"
SSH_PORT="${NPCINK_CLOUD_DEPLOY_SSH_PORT:-22}"
SSH_IDENTITY_FILE="${NPCINK_CLOUD_DEPLOY_IDENTITY_FILE:-}"
DOMAIN="${NPCINK_CLOUD_DOMAIN_NAME:-}"
LOCAL_CERT_PATH="${NPCINK_CLOUD_DOMAIN_CERT_PATH:-}"
LOCAL_KEY_PATH="${NPCINK_CLOUD_DOMAIN_KEY_PATH:-}"
REMOTE_CERT_DIR="${NPCINK_CLOUD_DOMAIN_REMOTE_CERT_DIR:-}"
UPSTREAM_URL="${NPCINK_CLOUD_DOMAIN_UPSTREAM_URL:-http://127.0.0.1:8010}"

while [ "$#" -gt 0 ]; do
	case "$1" in
		--)
			shift
			;;
		--ssh-host)
			SSH_HOST="$2"
			shift 2
			;;
		--ssh-user)
			SSH_USER="$2"
			shift 2
			;;
		--ssh-port)
			SSH_PORT="$2"
			shift 2
			;;
		--identity-file)
			SSH_IDENTITY_FILE="$2"
			shift 2
			;;
		--domain)
			DOMAIN="$2"
			shift 2
			;;
		--cert-path)
			LOCAL_CERT_PATH="$2"
			shift 2
			;;
		--key-path)
			LOCAL_KEY_PATH="$2"
			shift 2
			;;
		--remote-cert-dir)
			REMOTE_CERT_DIR="$2"
			shift 2
			;;
		--upstream-url)
			UPSTREAM_URL="$2"
			shift 2
			;;
		*)
			echo "[fail] Unknown argument: $1" >&2
			exit 1
			;;
	esac
done

require_cmd() {
	command -v "$1" >/dev/null 2>&1 || {
		echo "[fail] Missing required command: $1" >&2
		exit 1
	}
}

require_cmd ssh
require_cmd scp
require_cmd python3

[ -n "${SSH_HOST}" ] || { echo "[fail] Missing SSH host" >&2; exit 1; }
[ -n "${DOMAIN}" ] || { echo "[fail] Missing domain" >&2; exit 1; }
[ -n "${LOCAL_CERT_PATH}" ] || { echo "[fail] Missing cert path" >&2; exit 1; }
[ -n "${LOCAL_KEY_PATH}" ] || { echo "[fail] Missing key path" >&2; exit 1; }
[ -f "${LOCAL_CERT_PATH}" ] || { echo "[fail] Cert file not found: ${LOCAL_CERT_PATH}" >&2; exit 1; }
[ -f "${LOCAL_KEY_PATH}" ] || { echo "[fail] Key file not found: ${LOCAL_KEY_PATH}" >&2; exit 1; }

if [ -z "${REMOTE_CERT_DIR}" ]; then
	REMOTE_CERT_DIR="/etc/nginx/ssl/${DOMAIN}"
fi

TEMPLATE_PATH="${ROOT_DIR}/deploy/magick-domain-nginx.conf.template"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT
TMP_CONF="${TMP_DIR}/${DOMAIN}.conf"

SSL_CERT_REMOTE="${REMOTE_CERT_DIR}/$(basename "${LOCAL_CERT_PATH}")"
SSL_KEY_REMOTE="${REMOTE_CERT_DIR}/$(basename "${LOCAL_KEY_PATH}")"

python3 - "${TEMPLATE_PATH}" "${TMP_CONF}" "${DOMAIN}" "${SSL_CERT_REMOTE}" "${SSL_KEY_REMOTE}" "${UPSTREAM_URL}" <<'PY'
from __future__ import annotations
import pathlib
import sys

template = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
target = pathlib.Path(sys.argv[2])
domain = sys.argv[3]
ssl_cert = sys.argv[4]
ssl_key = sys.argv[5]
upstream = sys.argv[6]

rendered = (
    template.replace("__DOMAIN__", domain)
    .replace("__SSL_CERT__", ssl_cert)
    .replace("__SSL_KEY__", ssl_key)
    .replace("__UPSTREAM__", upstream)
)
target.write_text(rendered, encoding="utf-8")
PY

SSH_TARGET="${SSH_HOST}"
if [ -n "${SSH_USER}" ]; then
	SSH_TARGET="${SSH_USER}@${SSH_HOST}"
fi

SSH_ARGS=(-p "${SSH_PORT}" -o StrictHostKeyChecking=accept-new)
SCP_ARGS=(-P "${SSH_PORT}" -o StrictHostKeyChecking=accept-new)
if [ -n "${SSH_IDENTITY_FILE}" ]; then
	SSH_ARGS+=(-i "${SSH_IDENTITY_FILE}")
	SCP_ARGS+=(-i "${SSH_IDENTITY_FILE}")
fi

REMOTE_TMP_CONF="/tmp/${DOMAIN}.conf"
REMOTE_TMP_CERT="/tmp/$(basename "${LOCAL_CERT_PATH}")"
REMOTE_TMP_KEY="/tmp/$(basename "${LOCAL_KEY_PATH}")"

echo "[info] Uploading certs and nginx config to ${SSH_TARGET}"
scp "${SCP_ARGS[@]}" "${LOCAL_CERT_PATH}" "${SSH_TARGET}:${REMOTE_TMP_CERT}"
scp "${SCP_ARGS[@]}" "${LOCAL_KEY_PATH}" "${SSH_TARGET}:${REMOTE_TMP_KEY}"
scp "${SCP_ARGS[@]}" "${TMP_CONF}" "${SSH_TARGET}:${REMOTE_TMP_CONF}"

ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" bash -s -- \
	"${DOMAIN}" \
	"${REMOTE_CERT_DIR}" \
	"${REMOTE_TMP_CERT}" \
	"${REMOTE_TMP_KEY}" \
	"${REMOTE_TMP_CONF}" <<'EOF'
set -euo pipefail

DOMAIN="$1"
REMOTE_CERT_DIR="$2"
REMOTE_TMP_CERT="$3"
REMOTE_TMP_KEY="$4"
REMOTE_TMP_CONF="$5"

export DEBIAN_FRONTEND=noninteractive

if ! command -v nginx >/dev/null 2>&1; then
	apt-get update
	apt-get install -y nginx
fi

mkdir -p "${REMOTE_CERT_DIR}"
install -m 644 "${REMOTE_TMP_CERT}" "${REMOTE_CERT_DIR}/$(basename "${REMOTE_TMP_CERT}")"
install -m 600 "${REMOTE_TMP_KEY}" "${REMOTE_CERT_DIR}/$(basename "${REMOTE_TMP_KEY}")"
install -m 644 "${REMOTE_TMP_CONF}" "/etc/nginx/sites-available/${DOMAIN}.conf"
ln -sfn "/etc/nginx/sites-available/${DOMAIN}.conf" "/etc/nginx/sites-enabled/${DOMAIN}.conf"
rm -f /etc/nginx/sites-enabled/default
rm -f "${REMOTE_TMP_CERT}" "${REMOTE_TMP_KEY}" "${REMOTE_TMP_CONF}"

nginx -t
systemctl enable nginx
systemctl restart nginx
EOF

echo "[ok] Domain binding applied for https://${DOMAIN}"
