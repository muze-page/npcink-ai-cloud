#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "${ROOT_DIR}/deploy/common.sh"

npcink_ai_cloud_require_cmd curl
npcink_ai_cloud_require_cmd grep
npcink_ai_cloud_require_cmd scp
npcink_ai_cloud_require_cmd ssh
npcink_ai_cloud_require_cmd tar

SSH_HOST="${NPCINK_CLOUD_DEPLOY_SSH_HOST:-}"
SSH_USER="${NPCINK_CLOUD_DEPLOY_SSH_USER:-}"
SSH_PORT="${NPCINK_CLOUD_DEPLOY_SSH_PORT:-22}"
SSH_IDENTITY_FILE="${NPCINK_CLOUD_DEPLOY_IDENTITY_FILE:-}"
SSH_CONNECT_TIMEOUT_SECONDS="${NPCINK_CLOUD_DEPLOY_SSH_CONNECT_TIMEOUT_SECONDS:-10}"
REMOTE_DIR="${NPCINK_CLOUD_DEPLOY_REMOTE_DIR:-/opt/npcink-ai-cloud}"
BASE_URL="${NPCINK_CLOUD_BASE_URL:-https://cloud.npc.ink}"

if [ -z "${SSH_HOST}" ]; then
	echo "[fail] Missing NPCINK_CLOUD_DEPLOY_SSH_HOST" >&2
	exit 1
fi

if [ -n "${SSH_IDENTITY_FILE}" ] && [ ! -f "${SSH_IDENTITY_FILE}" ]; then
	echo "[fail] SSH identity file not found: ${SSH_IDENTITY_FILE}" >&2
	exit 1
fi

if [ ! -d "${ROOT_DIR}/site/terms" ]; then
	echo "[fail] Missing site/terms directory" >&2
	exit 1
fi

SSH_TARGET="${SSH_HOST}"
if [ -n "${SSH_USER}" ]; then
	SSH_TARGET="${SSH_USER}@${SSH_HOST}"
fi

SSH_ARGS=(
	-p "${SSH_PORT}"
	-o StrictHostKeyChecking=accept-new
	-o BatchMode=yes
	-o ConnectTimeout="${SSH_CONNECT_TIMEOUT_SECONDS}"
)
SCP_ARGS=(
	-P "${SSH_PORT}"
	-o StrictHostKeyChecking=accept-new
	-o BatchMode=yes
	-o ConnectTimeout="${SSH_CONNECT_TIMEOUT_SECONDS}"
)

if [ -n "${SSH_IDENTITY_FILE}" ]; then
	SSH_ARGS+=(-i "${SSH_IDENTITY_FILE}")
	SCP_ARGS+=(-i "${SSH_IDENTITY_FILE}")
fi

TMP_DIR="$(mktemp -d)"
TERMS_BUNDLE="${TMP_DIR}/static-terms.tgz"
trap 'rm -rf "${TMP_DIR}"' EXIT

tar czf "${TERMS_BUNDLE}" -C "${ROOT_DIR}/site" terms

REMOTE_TERMS_BUNDLE="${REMOTE_DIR}/static-terms.tgz"
REMOTE_NEXT_DIR="${REMOTE_DIR}/static-terms-next-$(date -u +%Y%m%d%H%M%S)"

echo "[info] Uploading static terms bundle"
scp "${SCP_ARGS[@]}" "${TERMS_BUNDLE}" "${SSH_TARGET}:${REMOTE_TERMS_BUNDLE}"

echo "[info] Installing static terms into current release"
ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" bash -s -- \
	"${REMOTE_DIR}" \
	"${REMOTE_TERMS_BUNDLE}" \
	"${REMOTE_NEXT_DIR}" <<'EOF'
set -euo pipefail

REMOTE_DIR="$1"
REMOTE_TERMS_BUNDLE="$2"
REMOTE_NEXT_DIR="$3"
CURRENT_LINK="${REMOTE_DIR}/current"

if [ ! -d "${CURRENT_LINK}" ]; then
	echo "[fail] Current release link is missing: ${CURRENT_LINK}" >&2
	exit 1
fi

if [ ! -d "${CURRENT_LINK}/site" ]; then
	echo "[fail] Current release site directory is missing: ${CURRENT_LINK}/site" >&2
	exit 1
fi

rm -rf "${REMOTE_NEXT_DIR}"
mkdir -p "${REMOTE_NEXT_DIR}"
tar xzf "${REMOTE_TERMS_BUNDLE}" -C "${REMOTE_NEXT_DIR}"

test -f "${REMOTE_NEXT_DIR}/terms/index.html"
test -f "${REMOTE_NEXT_DIR}/terms/en/terms.html"
test -f "${REMOTE_NEXT_DIR}/terms/zh/terms.html"
test -f "${REMOTE_NEXT_DIR}/terms/styles.css"

rm -rf "${CURRENT_LINK}/site/terms.previous"
if [ -e "${CURRENT_LINK}/site/terms" ]; then
	mv "${CURRENT_LINK}/site/terms" "${CURRENT_LINK}/site/terms.previous"
fi
mv "${REMOTE_NEXT_DIR}/terms" "${CURRENT_LINK}/site/terms"

rm -rf "${CURRENT_LINK}/site/terms.previous" "${REMOTE_NEXT_DIR}" "${REMOTE_TERMS_BUNDLE}"
echo "[ok] Static terms updated in ${CURRENT_LINK}/site/terms"
EOF

assert_public_static_page() {
	local path="$1"
	local marker="$2"
	local body_file
	body_file="$(mktemp)"
	if ! curl -fsS --max-time 20 "${BASE_URL%/}${path}" -o "${body_file}"; then
		rm -f "${body_file}"
		echo "[fail] Static terms smoke failed for ${path}" >&2
		exit 1
	fi
	if ! grep -Fq "${marker}" "${body_file}"; then
		rm -f "${body_file}"
		echo "[fail] Static terms smoke marker missing for ${path}: ${marker}" >&2
		exit 1
	fi
	rm -f "${body_file}"
}

assert_public_static_page "/terms" "Npcink Cloud Legal Documents"
assert_public_static_page "/terms/en/terms.html" "Npcink Cloud Terms of Service"
assert_public_static_page "/terms/zh/terms.html" "Npcink Cloud 服务条款"
assert_public_static_page "/terms/styles.css" "site-header"

curl -fsS --max-time 20 "${BASE_URL%/}/health/live" >/dev/null
echo "[ok] Static terms deploy completed"
