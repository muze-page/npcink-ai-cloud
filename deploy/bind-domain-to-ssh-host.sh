#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

SSH_HOST="${NPCINK_CLOUD_DEPLOY_SSH_HOST:-}"
SSH_USER="${NPCINK_CLOUD_DEPLOY_SSH_USER:-}"
SSH_PORT="${NPCINK_CLOUD_DEPLOY_SSH_PORT:-22}"
SSH_IDENTITY_FILE="${NPCINK_CLOUD_DEPLOY_IDENTITY_FILE:-}"
DOMAIN="${NPCINK_CLOUD_DOMAIN_NAME:-}"
CERTIFICATE_PATH=""
PRIVATE_KEY_PATH=""
UPSTREAM_URL="${NPCINK_CLOUD_DOMAIN_UPSTREAM_URL:-http://127.0.0.1:8010}"
COMPOSE_PROJECT_NAME_EFFECTIVE="${NPCINK_CLOUD_COMPOSE_PROJECT_NAME:-${COMPOSE_PROJECT_NAME:-npcink-ai-cloud}}"
REMOTE_DIR="/opt/npcink-ai-cloud"
PREPARE_ONLY=0

usage() {
	cat <<'EOF'
Usage:
  deploy/bind-domain-to-ssh-host.sh \
    --ssh-host 203.0.113.10 \
    --ssh-user root \
    --domain cloud.example.com \
    [--certificate-path /etc/letsencrypt/live/cloud.example.com/fullchain.pem] \
    [--private-key-path /etc/letsencrypt/live/cloud.example.com/privkey.pem] \
    [--prepare-only]

The certificate and private key are remote Certbot live-lineage symlinks. This
helper never uploads or copies TLS material. Activation holds the shared
/opt/npcink-ai-cloud/.deploy-lock while it snapshots NGINX and the exact running
project Caddy IDs, stops those IDs, activates NGINX, and validates loopback HTTPS.
Any activation failure restores NGINX and restarts/verifies those exact Caddy IDs.
Prepare-only temporarily installs the candidate only for nginx -t, restores the
original files before returning, and never stops Caddy or switches traffic.
EOF
}

fail() {
	printf '[edge-bind:fail] %s\n' "$*" >&2
	exit 1
}

while [ "$#" -gt 0 ]; do
	case "$1" in
		--)
			shift
			;;
		--ssh-host)
			[ "$#" -ge 2 ] || fail "--ssh-host requires a value"
			SSH_HOST="$2"
			shift 2
			;;
		--ssh-user)
			[ "$#" -ge 2 ] || fail "--ssh-user requires a value"
			SSH_USER="$2"
			shift 2
			;;
		--ssh-port)
			[ "$#" -ge 2 ] || fail "--ssh-port requires a value"
			SSH_PORT="$2"
			shift 2
			;;
		--identity-file)
			[ "$#" -ge 2 ] || fail "--identity-file requires a value"
			SSH_IDENTITY_FILE="$2"
			shift 2
			;;
		--domain)
			[ "$#" -ge 2 ] || fail "--domain requires a value"
			DOMAIN="$2"
			shift 2
			;;
		--certificate-path)
			[ "$#" -ge 2 ] || fail "--certificate-path requires a value"
			CERTIFICATE_PATH="$2"
			shift 2
			;;
		--private-key-path)
			[ "$#" -ge 2 ] || fail "--private-key-path requires a value"
			PRIVATE_KEY_PATH="$2"
			shift 2
			;;
		--upstream-url)
			[ "$#" -ge 2 ] || fail "--upstream-url requires a value"
			UPSTREAM_URL="$2"
			shift 2
			;;
		--compose-project-name)
			[ "$#" -ge 2 ] || fail "--compose-project-name requires a value"
			COMPOSE_PROJECT_NAME_EFFECTIVE="$2"
			shift 2
			;;
		--prepare-only)
			PREPARE_ONLY=1
			shift
			;;
		-h|--help)
			usage
			exit 0
			;;
		*) fail "unknown argument: $1" ;;
	esac
done

require_cmd() {
	command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

for command_name in python3 scp ssh; do
	require_cmd "${command_name}"
done

[ -n "${SSH_HOST}" ] || fail "missing SSH host"
[ -n "${DOMAIN}" ] || fail "missing domain"
if [ -z "${CERTIFICATE_PATH}" ]; then
	CERTIFICATE_PATH="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
fi
if [ -z "${PRIVATE_KEY_PATH}" ]; then
	PRIVATE_KEY_PATH="/etc/letsencrypt/live/${DOMAIN}/privkey.pem"
fi

python3 - \
	"${SSH_HOST}" \
	"${SSH_USER}" \
	"${SSH_PORT}" \
	"${DOMAIN}" \
	"${CERTIFICATE_PATH}" \
	"${PRIVATE_KEY_PATH}" \
	"${UPSTREAM_URL}" \
	"${COMPOSE_PROJECT_NAME_EFFECTIVE}" <<'PY'
from __future__ import annotations

import re
import sys
from urllib.parse import urlsplit

(
    ssh_host,
    ssh_user,
    ssh_port,
    domain,
    certificate_path,
    private_key_path,
    upstream,
    compose_project,
) = sys.argv[1:]

if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", ssh_host):
    raise SystemExit("[edge-bind:fail] SSH host contains unsupported characters")
if ssh_user and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", ssh_user):
    raise SystemExit("[edge-bind:fail] SSH user contains unsupported characters")
if not ssh_port.isdigit() or not 1 <= int(ssh_port) <= 65535:
    raise SystemExit("[edge-bind:fail] SSH port must be between 1 and 65535")

domain = domain.strip().lower().rstrip(".")
if len(domain) > 253 or not re.fullmatch(
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+",
    domain,
):
    raise SystemExit("[edge-bind:fail] domain must be a valid lowercase-compatible DNS hostname")

certificate_match = re.fullmatch(
    r"/etc/letsencrypt/live/([A-Za-z0-9][A-Za-z0-9_.-]*)/fullchain\.pem",
    certificate_path,
)
if certificate_match is None:
    raise SystemExit("[edge-bind:fail] certificate path must name a Certbot live fullchain.pem")
expected_key = f"/etc/letsencrypt/live/{certificate_match.group(1)}/privkey.pem"
if private_key_path != expected_key:
    raise SystemExit("[edge-bind:fail] private-key path must name privkey.pem in the same Certbot live lineage")

try:
    parsed = urlsplit(upstream)
    port = parsed.port
except ValueError as exc:
    raise SystemExit(f"[edge-bind:fail] invalid upstream URL: {exc}") from exc
if parsed.scheme.lower() != "http" or parsed.hostname != "127.0.0.1" or port != 8010:
    raise SystemExit("[edge-bind:fail] external edge upstream must be exactly loopback HTTP on 127.0.0.1:8010")
if parsed.username is not None or parsed.password is not None:
    raise SystemExit("[edge-bind:fail] external edge upstream must not contain userinfo")
if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
    raise SystemExit("[edge-bind:fail] external edge upstream must be an origin without path, query, or fragment")
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", compose_project):
    raise SystemExit("[edge-bind:fail] Compose project name contains unsupported characters")
PY

TEMPLATE_PATH="${ROOT_DIR}/deploy/magick-domain-nginx.conf.template"
[ -f "${TEMPLATE_PATH}" ] || fail "NGINX template is missing: ${TEMPLATE_PATH}"
TMP_DIR="$(mktemp -d)"
TMP_CONF="${TMP_DIR}/${DOMAIN}.conf"
REMOTE_CLEANUP_ARMED=0
SSH_TARGET=""
REMOTE_TMP_DIR=""

remote_shell_arg() {
	python3 - "$1" <<'PY'
import shlex
import sys

print(shlex.quote(sys.argv[1]), end="")
PY
}

cleanup() {
	local remote_command=""
	rm -rf -- "${TMP_DIR}"
	if [ "${REMOTE_CLEANUP_ARMED}" = "1" ] && \
		[ -n "${SSH_TARGET}" ] && [ -n "${REMOTE_TMP_DIR}" ]; then
		remote_command="bash -s -- $(remote_shell_arg "${REMOTE_TMP_DIR}")"
		ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "${remote_command}" \
			>/dev/null 2>&1 <<'EOF' || true
set -Eeuo pipefail
REMOTE_TMP_DIR="$1"
case "${REMOTE_TMP_DIR}" in
	/tmp/npcink-edge-[0-9a-f]*) ;;
	*) exit 1 ;;
esac
if [ -e "${REMOTE_TMP_DIR}/RETAIN_ROLLBACK_EVIDENCE" ]; then
	exit 0
fi
if [ -d "${REMOTE_TMP_DIR}" ]; then
	find "${REMOTE_TMP_DIR}" -depth -delete
fi
EOF
	fi
}
trap cleanup EXIT

python3 - \
	"${TEMPLATE_PATH}" \
	"${TMP_CONF}" \
	"${DOMAIN}" \
	"${CERTIFICATE_PATH}" \
	"${PRIVATE_KEY_PATH}" \
	"${UPSTREAM_URL}" <<'PY'
from __future__ import annotations

import pathlib
import sys

template_path, target_path, domain, certificate_path, private_key_path, upstream = sys.argv[1:]
template = pathlib.Path(template_path).read_text(encoding="utf-8")
rendered = (
    template.replace("__DOMAIN__", domain)
    .replace("__SSL_CERT__", certificate_path)
    .replace("__SSL_KEY__", private_key_path)
    .replace("__UPSTREAM__", upstream)
)
if any(marker in rendered for marker in ("__DOMAIN__", "__SSL_CERT__", "__SSL_KEY__", "__UPSTREAM__")):
    raise SystemExit("[edge-bind:fail] NGINX template rendering left an unresolved marker")
pathlib.Path(target_path).write_text(rendered, encoding="utf-8")
PY

SSH_TARGET="${SSH_HOST}"
if [ -n "${SSH_USER}" ]; then
	SSH_TARGET="${SSH_USER}@${SSH_HOST}"
fi
SSH_ARGS=(-p "${SSH_PORT}" -o StrictHostKeyChecking=yes)
SCP_ARGS=(-P "${SSH_PORT}" -o StrictHostKeyChecking=yes)
if [ -n "${SSH_IDENTITY_FILE}" ]; then
	SSH_ARGS+=(-i "${SSH_IDENTITY_FILE}")
	SCP_ARGS+=(-i "${SSH_IDENTITY_FILE}")
fi

REMOTE_TMP_TOKEN="$(python3 - <<'PY'
import secrets

print(secrets.token_hex(16))
PY
)"
REMOTE_TMP_DIR="/tmp/npcink-edge-${REMOTE_TMP_TOKEN}"
REMOTE_TMP_CONF="${REMOTE_TMP_DIR}/edge.conf"

remote_command="bash -s -- $(remote_shell_arg "${REMOTE_TMP_DIR}")"
ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "${remote_command}" <<'EOF'
set -Eeuo pipefail
umask 077
REMOTE_TMP_DIR="$1"
case "${REMOTE_TMP_DIR}" in
	/tmp/npcink-edge-[0-9a-f]*) ;;
	*) exit 1 ;;
esac
install -d -m 700 -- "${REMOTE_TMP_DIR}"
EOF
REMOTE_CLEANUP_ARMED=1

printf '[edge-bind:info] uploading candidate NGINX config to %s\n' "${SSH_TARGET}"
scp "${SCP_ARGS[@]}" "${TMP_CONF}" "${SSH_TARGET}:${REMOTE_TMP_CONF}"

remote_command="bash -s --"
for remote_arg in \
	"${DOMAIN}" \
	"${CERTIFICATE_PATH}" \
	"${PRIVATE_KEY_PATH}" \
	"${REMOTE_TMP_CONF}" \
	"${UPSTREAM_URL}" \
	"${REMOTE_TMP_DIR}" \
	"${PREPARE_ONLY}" \
	"${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
	"${REMOTE_DIR}"; do
	remote_command+=" $(remote_shell_arg "${remote_arg}")"
done

ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "${remote_command}" <<'EOF'
set -Eeuo pipefail
umask 077

DOMAIN="$1"
CERTIFICATE_PATH="$2"
PRIVATE_KEY_PATH="$3"
REMOTE_TMP_CONF="$4"
UPSTREAM_URL="$5"
REMOTE_TMP_DIR="$6"
PREPARE_ONLY="$7"
COMPOSE_PROJECT_NAME_EFFECTIVE="$8"
REMOTE_DIR="$9"

[ "$(id -u)" = "0" ] || {
	echo "[edge-bind:fail] the remote Edge transaction must run as root" >&2
	exit 1
}
[ "${REMOTE_DIR}" = "/opt/npcink-ai-cloud" ] || {
	echo "[edge-bind:fail] managed remote root must be /opt/npcink-ai-cloud" >&2
	exit 1
}
case "${REMOTE_TMP_DIR}" in
	/tmp/npcink-edge-[0-9a-f]*) ;;
	*) echo "[edge-bind:fail] invalid remote temporary directory" >&2; exit 1 ;;
esac

SITE_AVAILABLE="/etc/nginx/sites-available/${DOMAIN}.conf"
SITE_ENABLED="/etc/nginx/sites-enabled/${DOMAIN}.conf"
DEFAULT_ENABLED="/etc/nginx/sites-enabled/default"
ROLLBACK_DIR="${REMOTE_TMP_DIR}/rollback"
DEPLOY_LOCK_DIR="${REMOTE_DIR}/.deploy-lock"
TRANSACTION_COMMITTED=0
ROLLBACK_REQUIRED=0
LOCK_HELD=0
PRESERVE_ROLLBACK_EVIDENCE=0
EDGE_SERVICE_MUTATION_STARTED=0
NGINX_WAS_ACTIVE=0
NGINX_WAS_ENABLED=0
NGINX_ACTIVE_STATE=""
NGINX_ENABLEMENT_STATE=""
SITE_AVAILABLE_EXISTED=0
SITE_ENABLED_EXISTED=0
DEFAULT_ENABLED_EXISTED=0
ORIGINAL_CADDY_IDS=()

fail_remote() {
	printf '[edge-bind:fail] %s\n' "$*" >&2
	exit 1
}

mode_of() {
	stat -c '%a' -- "$1"
}

owner_uid_of() {
	stat -c '%u' -- "$1"
}

metadata_of() {
	stat -c '%u:%g:%a' -- "$1"
}

file_type_of() {
	stat -c '%F' -- "$1"
}

assert_safe_directory() {
	local path="$1"
	local label="$2"
	local mode=""
	[ -d "${path}" ] && [ ! -L "${path}" ] || fail_remote "${label} must be a real directory: ${path}"
	[ "$(owner_uid_of "${path}")" = "0" ] || fail_remote "${label} must be owned by root: ${path}"
	mode="$(mode_of "${path}")"
	[[ "${mode}" =~ ^[0-7]{3,4}$ ]] || fail_remote "${label} mode is invalid: ${path}"
	(( (8#${mode} & 0022) == 0 )) || fail_remote "${label} must not be group/world writable: ${path}"
}

assert_safe_parent_chain() {
	local path="$1"
	local label="$2"
	while [ "${path}" != "/" ]; do
		assert_safe_directory "${path}" "${label}"
		path="$(dirname "${path}")"
	done
}

assert_certbot_lineage_ready() {
	local lineage_dir="${CERTIFICATE_PATH%/fullchain.pem}"
	local lineage_name="${lineage_dir##*/}"
	local certificate_real_path=""
	local private_key_real_path=""
	local certificate_mode=""
	local private_key_mode=""

	[ "${CERTIFICATE_PATH}" = "/etc/letsencrypt/live/${lineage_name}/fullchain.pem" ] || \
		fail_remote "certificate path must name fullchain.pem in one Certbot live lineage"
	[ "${PRIVATE_KEY_PATH}" = "/etc/letsencrypt/live/${lineage_name}/privkey.pem" ] || \
		fail_remote "private-key path must name privkey.pem in the same Certbot live lineage"
	[ "$(file_type_of "${CERTIFICATE_PATH}")" = "symbolic link" ] || \
		fail_remote "certificate path must be a Certbot live symlink"
	[ "$(file_type_of "${PRIVATE_KEY_PATH}")" = "symbolic link" ] || \
		fail_remote "private-key path must be a Certbot live symlink"

	certificate_real_path="$(readlink -f -- "${CERTIFICATE_PATH}")" || \
		fail_remote "certificate path cannot be resolved"
	private_key_real_path="$(readlink -f -- "${PRIVATE_KEY_PATH}")" || \
		fail_remote "private-key path cannot be resolved"
	case "${certificate_real_path}" in
		/etc/letsencrypt/archive/"${lineage_name}"/fullchain*.pem) ;;
		*) fail_remote "certificate path must resolve within its Certbot archive lineage" ;;
	esac
	case "${private_key_real_path}" in
		/etc/letsencrypt/archive/"${lineage_name}"/privkey*.pem) ;;
		*) fail_remote "private-key path must resolve within its Certbot archive lineage" ;;
	esac
	[ "$(file_type_of "${certificate_real_path}")" = "regular file" ] || \
		fail_remote "certificate archive target must be a regular non-symlink file"
	[ "$(file_type_of "${private_key_real_path}")" = "regular file" ] || \
		fail_remote "private-key archive target must be a regular non-symlink file"
	[ "$(owner_uid_of "${certificate_real_path}")" = "0" ] || \
		fail_remote "certificate archive target must be owned by root"
	[ "$(owner_uid_of "${private_key_real_path}")" = "0" ] || \
		fail_remote "private-key archive target must be owned by root"
	certificate_mode="$(mode_of "${certificate_real_path}")"
	private_key_mode="$(mode_of "${private_key_real_path}")"
	[[ "${certificate_mode}" =~ ^[0-7]{3,4}$ ]] || fail_remote "certificate archive target mode is invalid"
	[[ "${private_key_mode}" =~ ^[0-7]{3,4}$ ]] || fail_remote "private-key archive target mode is invalid"
	(( (8#${certificate_mode} & 0022) == 0 )) || \
		fail_remote "certificate archive target must not be group/world writable"
	(( (8#${private_key_mode} & 0077) == 0 )) || \
		fail_remote "private-key archive target must not grant group or other permissions"
	assert_safe_parent_chain "${lineage_dir}" "certificate live parent"
	assert_safe_parent_chain "$(dirname "${certificate_real_path}")" "certificate archive parent"

	openssl x509 -in "${CERTIFICATE_PATH}" -noout -checkhost "${DOMAIN}" >/dev/null 2>&1 || \
		fail_remote "certificate does not match the requested domain"
	openssl x509 -in "${CERTIFICATE_PATH}" -checkend 2592000 -noout >/dev/null 2>&1 || \
		fail_remote "certificate expires within 30 days"
	openssl pkey -in "${PRIVATE_KEY_PATH}" -check -noout >/dev/null 2>&1 || \
		fail_remote "private key is invalid"
	local certificate_public_key_sha256=""
	local private_key_public_key_sha256=""
	certificate_public_key_sha256="$(
		openssl x509 -in "${CERTIFICATE_PATH}" -pubkey -noout |
			openssl pkey -pubin -outform DER 2>/dev/null |
			openssl dgst -sha256 -r |
			awk '{print $1}'
	)"
	private_key_public_key_sha256="$(
		openssl pkey -in "${PRIVATE_KEY_PATH}" -pubout -outform DER 2>/dev/null |
			openssl dgst -sha256 -r |
			awk '{print $1}'
	)"
	[ -n "${certificate_public_key_sha256}" ] && \
		[ "${certificate_public_key_sha256}" = "${private_key_public_key_sha256}" ] || \
		fail_remote "certificate and private key do not match"
}

backup_target() {
	local source="$1"
	local backup_name="$2"
	local marker_name="$3"
	if [ -e "${source}" ] || [ -L "${source}" ]; then
		[ ! -d "${source}" ] || fail_remote "refusing to replace unexpected directory: ${source}"
		cp -a -- "${source}" "${ROLLBACK_DIR}/${backup_name}"
		printf -v "${marker_name}" '%s' 1
	fi
}

restore_target() {
	local target="$1"
	local backup_name="$2"
	local existed="$3"
	rm -f -- "${target}" || return 1
	if [ "${existed}" = "1" ]; then
		cp -a -- "${ROLLBACK_DIR}/${backup_name}" "${target}" || return 1
	fi
}

restore_nginx_files() {
	local restore_failed=0
	restore_target "${SITE_AVAILABLE}" site-available "${SITE_AVAILABLE_EXISTED}" || restore_failed=1
	restore_target "${SITE_ENABLED}" site-enabled "${SITE_ENABLED_EXISTED}" || restore_failed=1
	restore_target "${DEFAULT_ENABLED}" default-enabled "${DEFAULT_ENABLED_EXISTED}" || restore_failed=1
	return "${restore_failed}"
}

restored_target_matches_snapshot() {
	local label="$1"
	local target="$2"
	local backup_name="$3"
	local existed="$4"
	local backup="${ROLLBACK_DIR}/${backup_name}"
	local target_type=""
	local backup_type=""
	local target_metadata=""
	local backup_metadata=""
	local target_link=""
	local backup_link=""

	if [ "${existed}" = "0" ]; then
		if [ -e "${target}" ] || [ -L "${target}" ]; then
			echo "[edge-bind:fail] rollback postcondition failed: ${label} should be absent" >&2
			return 1
		fi
		return 0
	fi
	if { [ ! -e "${backup}" ] && [ ! -L "${backup}" ]; } || \
		{ [ ! -e "${target}" ] && [ ! -L "${target}" ]; }; then
		echo "[edge-bind:fail] rollback postcondition failed: ${label} snapshot or target is missing" >&2
		return 1
	fi
	target_type="$(file_type_of "${target}")" || return 1
	backup_type="$(file_type_of "${backup}")" || return 1
	target_metadata="$(metadata_of "${target}")" || return 1
	backup_metadata="$(metadata_of "${backup}")" || return 1
	if [ "${target_type}" != "${backup_type}" ] || \
		[ "${target_metadata}" != "${backup_metadata}" ]; then
		echo "[edge-bind:fail] rollback postcondition failed: ${label} type or metadata differs" >&2
		return 1
	fi
	case "${backup_type}" in
		"regular file")
			cmp -s -- "${backup}" "${target}" || {
				echo "[edge-bind:fail] rollback postcondition failed: ${label} content differs" >&2
				return 1
			}
			;;
		"symbolic link")
			target_link="$(readlink -- "${target}")" || return 1
			backup_link="$(readlink -- "${backup}")" || return 1
			[ "${target_link}" = "${backup_link}" ] || {
				echo "[edge-bind:fail] rollback postcondition failed: ${label} link target differs" >&2
				return 1
			}
			;;
		*)
			echo "[edge-bind:fail] rollback postcondition failed: ${label} has unsupported type" >&2
			return 1
			;;
	esac
}

verify_restored_nginx_state() {
	local verification_failed=0
	restored_target_matches_snapshot \
		"sites-available config" "${SITE_AVAILABLE}" site-available "${SITE_AVAILABLE_EXISTED}" || \
		verification_failed=1
	restored_target_matches_snapshot \
		"sites-enabled config" "${SITE_ENABLED}" site-enabled "${SITE_ENABLED_EXISTED}" || \
		verification_failed=1
	restored_target_matches_snapshot \
		"default site config" "${DEFAULT_ENABLED}" default-enabled "${DEFAULT_ENABLED_EXISTED}" || \
		verification_failed=1
	if ! nginx -t >/dev/null 2>&1; then
		echo "[edge-bind:fail] rollback postcondition failed: restored NGINX configuration is invalid" >&2
		verification_failed=1
	fi
	return "${verification_failed}"
}

verify_original_nginx_service_state() {
	local active_state=""
	local active_status=0
	local enablement_state=""
	if active_state="$(systemctl is-active nginx 2>/dev/null)"; then
		active_status=0
	else
		active_status=$?
	fi
	case "${active_state}:${active_status}" in
		active:0|inactive:3) ;;
		*)
			echo "[edge-bind:fail] rollback postcondition failed: NGINX active state is unreadable" >&2
			return 1
			;;
	esac
	if [ "${active_state}" != "${NGINX_ACTIVE_STATE}" ]; then
		echo "[edge-bind:fail] rollback postcondition failed: NGINX service state differs" >&2
		return 1
	fi
	enablement_state="$(systemctl is-enabled nginx 2>/dev/null || true)"
	case "${enablement_state}" in
		enabled|disabled|masked|static|indirect|generated) ;;
		*)
			echo "[edge-bind:fail] rollback postcondition failed: NGINX enablement state is unreadable" >&2
			return 1
			;;
	esac
	if [ "${enablement_state}" != "${NGINX_ENABLEMENT_STATE}" ]; then
		echo "[edge-bind:fail] rollback postcondition failed: NGINX service state differs" >&2
		return 1
	fi
}

assert_safe_existing_site_available() {
	local mode=""
	if [ ! -e "${SITE_AVAILABLE}" ] && [ ! -L "${SITE_AVAILABLE}" ]; then
		return 0
	fi
	[ ! -L "${SITE_AVAILABLE}" ] || \
		fail_remote "existing sites-available config must not be a symlink"
	[ "$(file_type_of "${SITE_AVAILABLE}")" = "regular file" ] || \
		fail_remote "existing sites-available config must be a regular file"
	[ "$(owner_uid_of "${SITE_AVAILABLE}")" = "0" ] || \
		fail_remote "existing sites-available config must be owned by root"
	mode="$(mode_of "${SITE_AVAILABLE}")"
	[[ "${mode}" =~ ^[0-7]{3,4}$ ]] || fail_remote "existing sites-available config mode is invalid"
	(( (8#${mode} & 0022) == 0 )) || \
		fail_remote "existing sites-available config must not be group/world writable"
}

verify_original_caddy_running() {
	local container_id=""
	local running=""
	for container_id in "${ORIGINAL_CADDY_IDS[@]}"; do
		if ! running="$(docker inspect --format '{{.State.Running}}' "${container_id}")" || \
			[ "${running}" != "true" ]; then
			echo "[edge-bind:fail] rollback postcondition failed: original Caddy container is not verifiably running (${container_id})" >&2
			return 1
		fi
	done
}

verify_original_caddy_stopped() {
	local container_id=""
	local running=""
	for container_id in "${ORIGINAL_CADDY_IDS[@]}"; do
		running="$(docker inspect --format '{{.State.Running}}' "${container_id}")" || return 1
		[ "${running}" = "false" ] || return 1
	done
}

snapshot_original_caddy_ids() {
	local snapshot_path="${ROLLBACK_DIR}/original-caddy-ids"
	ORIGINAL_CADDY_IDS=()
	if ! docker ps -q \
		--filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
		--filter "label=com.docker.compose.service=caddy" >"${snapshot_path}"; then
		echo "[edge-bind:fail] could not snapshot the running project Caddy containers" >&2
		return 1
	fi
	chmod 0600 "${snapshot_path}" || return 1
	while IFS= read -r container_id; do
		[ -n "${container_id}" ] || continue
		if [[ ! "${container_id}" =~ ^[0-9a-f]{12,64}$ ]]; then
			echo "[edge-bind:fail] Docker returned an invalid Caddy container ID" >&2
			return 1
		fi
		ORIGINAL_CADDY_IDS+=("${container_id}")
	done <"${snapshot_path}"
}

rollback_edge_transaction() {
	local rollback_failed=0
	if [ "${EDGE_SERVICE_MUTATION_STARTED}" != "1" ]; then
		if ! restore_nginx_files; then
			echo "[edge-bind:warn] one or more NGINX restore commands returned non-zero; checking final state" >&2
		fi
		verify_restored_nginx_state || rollback_failed=1
		verify_original_nginx_service_state || rollback_failed=1
		verify_original_caddy_running || rollback_failed=1
		return "${rollback_failed}"
	fi
	# Free public ports before restoring the exact pre-transaction services.
	systemctl stop nginx >/dev/null 2>&1 || true
	if ! restore_nginx_files; then
		echo "[edge-bind:warn] one or more NGINX restore commands returned non-zero; checking final state" >&2
	fi
	case "${NGINX_ENABLEMENT_STATE}" in
		enabled)
			systemctl unmask nginx >/dev/null 2>&1 || true
			systemctl enable nginx >/dev/null 2>&1 || true
			;;
		disabled)
			systemctl unmask nginx >/dev/null 2>&1 || true
			systemctl disable nginx >/dev/null 2>&1 || true
			;;
		masked)
			systemctl stop nginx >/dev/null 2>&1 || true
			systemctl mask nginx >/dev/null 2>&1 || true
			;;
		static|indirect|generated) ;;
		*) rollback_failed=1 ;;
	esac
	if [ "${NGINX_WAS_ACTIVE}" = "1" ]; then
		nginx -t >/dev/null 2>&1 || true
		systemctl restart nginx >/dev/null 2>&1 || true
	else
		systemctl stop nginx >/dev/null 2>&1 || true
	fi
	if [ "${#ORIGINAL_CADDY_IDS[@]}" -gt 0 ]; then
		docker start "${ORIGINAL_CADDY_IDS[@]}" >/dev/null 2>&1 || true
	fi
	verify_restored_nginx_state || rollback_failed=1
	verify_original_nginx_service_state || rollback_failed=1
	verify_original_caddy_running || rollback_failed=1
	return "${rollback_failed}"
}

cleanup_remote_tmp() {
	if [ "${PRESERVE_ROLLBACK_EVIDENCE}" = "1" ]; then
		: >"${REMOTE_TMP_DIR}/RETAIN_ROLLBACK_EVIDENCE"
		chmod 0600 "${REMOTE_TMP_DIR}/RETAIN_ROLLBACK_EVIDENCE" || true
		return 0
	fi
	if [ -d "${REMOTE_TMP_DIR}" ]; then
		find "${REMOTE_TMP_DIR}" -depth -delete
	fi
}

release_deploy_lock() {
	[ "${LOCK_HELD}" = "1" ] || return 0
	if ! rmdir -- "${DEPLOY_LOCK_DIR}"; then
		echo "[edge-bind:fail] deploy lock could not be released; preserving healthy state and rollback evidence" >&2
		PRESERVE_ROLLBACK_EVIDENCE=1
		return 1
	fi
	LOCK_HELD=0
}

on_exit() {
	local status="$?"
	trap - EXIT
	if [ "${status}" -ne 0 ] && [ "${TRANSACTION_COMMITTED}" != "1" ] && \
		[ "${ROLLBACK_REQUIRED}" = "1" ]; then
		echo "[edge-bind:warn] restoring the previous host NGINX state and exact retired Caddy containers" >&2
		if ! rollback_edge_transaction; then
			echo "[edge-bind:fail] rollback verification failed; preserving rollback evidence and deploy lock" >&2
			PRESERVE_ROLLBACK_EVIDENCE=1
			status=1
		fi
	fi
	if [ "${LOCK_HELD}" = "1" ] && [ "${PRESERVE_ROLLBACK_EVIDENCE}" != "1" ]; then
		if ! release_deploy_lock; then
			status=1
		fi
	fi
	cleanup_remote_tmp
	exit "${status}"
}
trap on_exit EXIT

[ -d "${REMOTE_DIR}" ] || fail_remote "managed remote root is missing: ${REMOTE_DIR}"
[ "$(owner_uid_of "${REMOTE_DIR}")" = "0" ] || fail_remote "managed remote root must be owned by root"
[ -f "${REMOTE_TMP_CONF}" ] && [ ! -L "${REMOTE_TMP_CONF}" ] || fail_remote "candidate NGINX config is missing or unsafe"
[ "$(owner_uid_of "${REMOTE_TMP_CONF}")" = "0" ] || fail_remote "candidate NGINX config must be owned by root"
CANDIDATE_CONFIG_MODE="$(mode_of "${REMOTE_TMP_CONF}")"
[[ "${CANDIDATE_CONFIG_MODE}" =~ ^[0-7]{3,4}$ ]] || fail_remote "candidate NGINX config mode is invalid"
(( (8#${CANDIDATE_CONFIG_MODE} & 0022) == 0 )) || fail_remote "candidate NGINX config must not be group/world writable"
test "$(stat -c '%a' "${REMOTE_TMP_DIR}")" = "700" || fail_remote "remote temporary directory must have mode 0700"

for required_command in awk cmp cp curl dirname docker find install nginx openssl readlink rm stat systemctl; do
	command -v "${required_command}" >/dev/null 2>&1 || \
		fail_remote "Host prerequisite is missing: ${required_command}. Install prerequisites before running the migration helper."
done

assert_certbot_lineage_ready
curl -fsS --connect-timeout 3 --max-time 10 \
	-H "Host: ${DOMAIN}" \
	-H "X-Forwarded-Host: ${DOMAIN}" \
	-H "X-Forwarded-Proto: https" \
	-H "X-Forwarded-Port: 443" \
	"${UPSTREAM_URL%/}/health/live" >/dev/null

mkdir -- "${DEPLOY_LOCK_DIR}" || fail_remote "another production host mutation holds ${DEPLOY_LOCK_DIR}"
LOCK_HELD=1
install -d -m 700 -- "${ROLLBACK_DIR}"
assert_safe_directory "/etc/nginx/sites-available" "NGINX sites-available directory"
assert_safe_directory "/etc/nginx/sites-enabled" "NGINX sites-enabled directory"
assert_safe_existing_site_available
NGINX_ACTIVE_STATUS=0
if NGINX_ACTIVE_STATE="$(systemctl is-active nginx 2>/dev/null)"; then
	NGINX_ACTIVE_STATUS=0
else
	NGINX_ACTIVE_STATUS=$?
fi
case "${NGINX_ACTIVE_STATE}:${NGINX_ACTIVE_STATUS}" in
	active:0) NGINX_WAS_ACTIVE=1 ;;
	inactive:3) ;;
	*) fail_remote "unsupported pre-transaction NGINX active state" ;;
esac
NGINX_ENABLEMENT_STATE="$(systemctl is-enabled nginx 2>/dev/null || true)"
case "${NGINX_ENABLEMENT_STATE}" in
	enabled) NGINX_WAS_ENABLED=1 ;;
	disabled|masked|static|indirect|generated) ;;
	*) fail_remote "unsupported or unreadable pre-transaction NGINX enablement state" ;;
esac
backup_target "${SITE_AVAILABLE}" site-available SITE_AVAILABLE_EXISTED
backup_target "${SITE_ENABLED}" site-enabled SITE_ENABLED_EXISTED
backup_target "${DEFAULT_ENABLED}" default-enabled DEFAULT_ENABLED_EXISTED
printf 'active=%s\nactive_state=%s\nenabled=%s\nenablement_state=%s\n' \
	"${NGINX_WAS_ACTIVE}" "${NGINX_ACTIVE_STATE}" \
	"${NGINX_WAS_ENABLED}" "${NGINX_ENABLEMENT_STATE}" \
	>"${ROLLBACK_DIR}/nginx-state"
chmod 0600 "${ROLLBACK_DIR}/nginx-state"

snapshot_original_caddy_ids || fail_remote "could not create the exact Caddy rollback snapshot"

ROLLBACK_REQUIRED=1
rm -f -- "${SITE_AVAILABLE}" "${SITE_ENABLED}"
install -m 644 -- "${REMOTE_TMP_CONF}" "${SITE_AVAILABLE}"
ln -sfn -- "${SITE_AVAILABLE}" "${SITE_ENABLED}"
nginx -t

if [ "${PREPARE_ONLY}" = "1" ]; then
	if ! restore_nginx_files; then
		echo "[edge-bind:warn] one or more NGINX restore commands returned non-zero; checking final state" >&2
	fi
	verify_restored_nginx_state || fail_remote "prepare-only did not restore the exact prior NGINX state"
	verify_original_nginx_service_state || fail_remote "prepare-only changed the NGINX service state"
	verify_original_caddy_running || fail_remote "prepare-only changed the exact prior Caddy state"
	ROLLBACK_REQUIRED=0
	TRANSACTION_COMMITTED=1
	release_deploy_lock
	echo "[edge-bind:ok] candidate NGINX config passed; prepare-only restored the exact prior files and did not switch traffic"
	exit 0
fi

[ "${#ORIGINAL_CADDY_IDS[@]}" -gt 0 ] || \
	fail_remote "activation requires at least one running project Caddy container to freeze for rollback"
EDGE_SERVICE_MUTATION_STARTED=1
docker stop "${ORIGINAL_CADDY_IDS[@]}" >/dev/null
verify_original_caddy_stopped || fail_remote "the exact original Caddy containers did not all stop"

rm -f -- "${DEFAULT_ENABLED}"
systemctl unmask nginx >/dev/null
systemctl enable nginx >/dev/null
systemctl restart nginx
curl -fsS --connect-timeout 3 --max-time 10 \
	--resolve "${DOMAIN}:443:127.0.0.1" \
	"https://${DOMAIN}/health/live" >/dev/null

ROLLBACK_REQUIRED=0
TRANSACTION_COMMITTED=1
release_deploy_lock
echo "[edge-bind:ok] external Edge activation committed under the shared deploy lock"
EOF

REMOTE_CLEANUP_ARMED=0
if [ "${PREPARE_ONLY}" = "1" ]; then
	printf '[edge-bind:ok] candidate validated for https://%s; prior NGINX files and Caddy state are unchanged\n' "${DOMAIN}"
else
	printf '[edge-bind:ok] domain binding applied for https://%s\n' "${DOMAIN}"
	echo "[edge-bind:ok] external edge is healthy; set NPCINK_CLOUD_EXTERNAL_EDGE_READY=true in the formal deploy env"
fi
