#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"

CONTRACT="npcink_cloud_certificate_renewal_readiness.v1"
MAX_EVIDENCE_AGE_SECONDS=$((7 * 24 * 60 * 60))
MINIMUM_CERTIFICATE_VALIDITY_DAYS=30
MINIMUM_CERTIFICATE_VALIDITY_SECONDS=$((MINIMUM_CERTIFICATE_VALIDITY_DAYS * 24 * 60 * 60))
CLEANUP_PATHS=()
GENERATION_IN_PROGRESS=0
GENERATION_SUCCEEDED=0

usage() {
	cat <<'EOF'
Usage:
  deploy/certificate-renewal-readiness.sh generate \
    --domain cloud.example.com \
    --certificate-path /etc/letsencrypt/live/cloud.example.com/fullchain.pem \
    --owner certbot \
    --timer certbot-renew.timer \
    --deploy-hook-path /etc/letsencrypt/renewal-hooks/deploy/reload-nginx \
    --evidence-path /var/lib/npcink-ai-cloud/edge/certificate-renewal-readiness.json

  deploy/certificate-renewal-readiness.sh verify \
    --domain cloud.example.com \
    --certificate-path /etc/letsencrypt/live/cloud.example.com/fullchain.pem \
    --owner certbot \
    --timer certbot-renew.timer \
    --deploy-hook-path /etc/letsencrypt/renewal-hooks/deploy/reload-nginx \
    --evidence-path /var/lib/npcink-ai-cloud/edge/certificate-renewal-readiness.json

Both modes are root-only and require the listed certificate, hook, evidence,
and timer values explicitly. Generate
atomically invalidates and fsyncs any prior receipt before checking the timer,
its triggered service, the resolved direct Certbot `renew` ExecStart of that service,
hook, certificate, or NGINX. It then performs a real Certbot renewal dry run,
directly executes the persistent deploy hook, reloads NGINX, and proves that
the leaf served by 127.0.0.1:443 matches the named PEM leaf. The certificate
must be a Certbot live-lineage fullchain.pem symlink; privkey.pem is derived
from that same lineage. Their final archive targets, key match, permissions,
and the actual ssl_certificate/ssl_certificate_key pair parsed from nginx -T
are bound into the receipt. Verify requires evidence no older than seven days,
rechecks all of those bindings plus the timer/service/ExecStart chain and hook
digest, directly executes the hook, and repeats the live certificate proof.
Evidence never contains certificate bytes, keys, tokens, command output, or
other secret material.
EOF
}

fail() {
	printf '[certificate-renewal:fail] %s\n' "$*" >&2
	exit 1
}

cleanup() {
	local path=""
	if [ "${MODE:-}" = "generate" ] && \
		[ "${GENERATION_IN_PROGRESS}" = "1" ] && \
		[ "${GENERATION_SUCCEEDED}" != "1" ] && \
		[ -n "${EVIDENCE_PATH:-}" ]; then
		rm -f -- "${EVIDENCE_PATH}" || true
		if [ -n "${RELEASE_TOOL_PYTHON:-}" ] && \
			[ -d "${EVIDENCE_PARENT:-}" ]; then
			"${RELEASE_TOOL_PYTHON}" - "${EVIDENCE_PARENT}" >/dev/null 2>&1 <<'PY' || true
import os
import sys

descriptor = os.open(sys.argv[1], os.O_RDONLY)
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY
		fi
	fi
	for path in "${CLEANUP_PATHS[@]-}"; do
		[ -n "${path}" ] && rm -f -- "${path}"
	done
	return 0
}
trap cleanup EXIT

mode_of() {
	stat -c '%a' "$1"
}

owner_uid_of() {
	stat -c '%u' "$1"
}

file_type_of() {
	stat -c '%F' "$1"
}

assert_safe_directory() {
	local path="$1"
	local label="$2"
	local mode=""
	[ -d "${path}" ] && [ ! -L "${path}" ] || fail "${label} must be a real directory: ${path}"
	[ "$(owner_uid_of "${path}")" = "0" ] || fail "${label} must be owned by root: ${path}"
	mode="$(mode_of "${path}")"
	[[ "${mode}" =~ ^[0-7]{3,4}$ ]] || fail "${label} mode is invalid: ${path}"
	(( (8#${mode} & 0022) == 0 )) || fail "${label} must not be group/world writable: ${path}"
}

assert_safe_parent_chain() {
	local path="$1"
	local label="$2"
	while [ "${path}" != "/" ]; do
		assert_safe_directory "${path}" "${label}"
		path="$(dirname "${path}")"
	done
}

assert_safe_archive_parent_chain() {
	local path="$1"
	local label="$2"
	local mode=""
	while [ "${path}" != "/" ]; do
		[ "$(file_type_of "${path}")" = "directory" ] || \
			fail "${label} must be a real non-symlink directory: ${path}"
		[ "$(owner_uid_of "${path}")" = "0" ] || fail "${label} must be owned by root: ${path}"
		mode="$(mode_of "${path}")"
		[[ "${mode}" =~ ^[0-7]{3,4}$ ]] || fail "${label} mode is invalid: ${path}"
		(( (8#${mode} & 0022) == 0 )) || fail "${label} must not be group/world writable: ${path}"
		path="$(dirname "${path}")"
	done
}

assert_certbot_lineage_ready() {
	local certificate_mode=""
	local private_key_mode=""

	[ "$(file_type_of "${CERTIFICATE_PATH}")" = "symbolic link" ] || \
		fail "certificate path must be a Certbot live symlink"
	[ "$(file_type_of "${PRIVATE_KEY_PATH}")" = "symbolic link" ] || \
		fail "private-key path must be a Certbot live symlink"

	CERTIFICATE_REAL_PATH="$(readlink -f -- "${CERTIFICATE_PATH}")" || \
		fail "certificate path cannot be resolved"
	PRIVATE_KEY_REAL_PATH="$(readlink -f -- "${PRIVATE_KEY_PATH}")" || \
		fail "private-key path cannot be resolved"
	case "${CERTIFICATE_REAL_PATH}" in
		/etc/letsencrypt/archive/"${CERTBOT_LINEAGE_NAME}"/fullchain*.pem) ;;
		*) fail "certificate path must resolve within its Certbot archive lineage" ;;
	esac
	case "${PRIVATE_KEY_REAL_PATH}" in
		/etc/letsencrypt/archive/"${CERTBOT_LINEAGE_NAME}"/privkey*.pem) ;;
		*) fail "private-key path must resolve within its Certbot archive lineage" ;;
	esac
	[ "$(file_type_of "${CERTIFICATE_REAL_PATH}")" = "regular file" ] || \
		fail "certificate archive target must be a regular non-symlink file"
	[ "$(file_type_of "${PRIVATE_KEY_REAL_PATH}")" = "regular file" ] || \
		fail "private-key archive target must be a regular non-symlink file"
	[ "$(owner_uid_of "${CERTIFICATE_REAL_PATH}")" = "0" ] || \
		fail "certificate archive target must be owned by root"
	[ "$(owner_uid_of "${PRIVATE_KEY_REAL_PATH}")" = "0" ] || \
		fail "private-key archive target must be owned by root"
	certificate_mode="$(mode_of "${CERTIFICATE_REAL_PATH}")"
	private_key_mode="$(mode_of "${PRIVATE_KEY_REAL_PATH}")"
	[[ "${certificate_mode}" =~ ^[0-7]{3,4}$ ]] || fail "certificate archive target mode is invalid"
	[[ "${private_key_mode}" =~ ^[0-7]{3,4}$ ]] || fail "private-key archive target mode is invalid"
	(( (8#${certificate_mode} & 0022) == 0 )) || \
		fail "certificate archive target must not be group/world writable"
	(( (8#${private_key_mode} & 0077) == 0 )) || \
		fail "private-key archive target must not grant group or other permissions"
	assert_safe_archive_parent_chain "$(dirname "${CERTIFICATE_PATH}")" "certificate live parent"
	assert_safe_archive_parent_chain "$(dirname "${CERTIFICATE_REAL_PATH}")" "certificate archive parent"
}

assert_certificate_private_key_match() {
	local certificate_public_key=""
	local private_key_public_key=""
	openssl pkey -in "${PRIVATE_KEY_PATH}" -check -noout >/dev/null 2>&1 || \
		fail "private key is invalid"
	certificate_public_key="$(
		openssl x509 -in "${CERTIFICATE_PATH}" -pubkey -noout |
			openssl pkey -pubin -outform PEM 2>/dev/null
	)" || fail "certificate public key could not be read"
	private_key_public_key="$(
		openssl pkey -in "${PRIVATE_KEY_PATH}" -pubout -outform PEM 2>/dev/null
	)" || fail "private-key public key could not be read"
	[ -n "${certificate_public_key}" ] && \
		[ "${certificate_public_key}" = "${private_key_public_key}" ] || \
		fail "certificate and private key do not match"
}

assert_nginx_lineage_binding() {
	local nginx_dump=""
	local parsed_binding=""
	nginx_dump="$(mktemp)"
	CLEANUP_PATHS+=("${nginx_dump}")
	chmod 0600 "${nginx_dump}"
	nginx -T >"${nginx_dump}" 2>/dev/null || fail "NGINX configuration dump failed"
	parsed_binding="$(
		"${RELEASE_TOOL_PYTHON}" - \
			"${nginx_dump}" \
			"${DOMAIN}" \
			"${CERTIFICATE_PATH}" \
			"${PRIVATE_KEY_PATH}" <<'PY'
from __future__ import annotations

import hashlib
import json
import shlex
import sys
from pathlib import Path

dump_path, domain, expected_certificate, expected_private_key = sys.argv[1:]
lexer = shlex.shlex(
    Path(dump_path).read_text(encoding="utf-8"),
    posix=True,
    punctuation_chars="{};",
)
lexer.commenters = "#"
lexer.whitespace_split = True
tokens = list(lexer)


def server_blocks(values: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    index = 0
    while index + 1 < len(values):
        if values[index] != "server" or values[index + 1] != "{":
            index += 1
            continue
        depth = 1
        end = index + 2
        while end < len(values) and depth:
            if values[end] == "{":
                depth += 1
            elif values[end] == "}":
                depth -= 1
            end += 1
        if depth:
            raise SystemExit(1)
        blocks.append(values[index + 2 : end - 1])
        index = end
    return blocks


def direct_directives(block: list[str]) -> dict[str, list[list[str]]]:
    result: dict[str, list[list[str]]] = {}
    depth = 0
    current: list[str] = []
    for token in block:
        if token == "{":
            depth += 1
            current = []
        elif token == "}":
            depth -= 1
            if depth < 0:
                raise SystemExit(1)
            current = []
        elif depth == 0 and token == ";":
            if current:
                result.setdefault(current[0], []).append(current[1:])
            current = []
        elif depth == 0:
            current.append(token)
    if depth or current:
        raise SystemExit(1)
    return result


tls_bindings: list[tuple[str, str]] = []
for block in server_blocks(tokens):
    directives = direct_directives(block)
    server_names = [
        item
        for occurrence in directives.get("server_name", [])
        for item in occurrence
    ]
    if domain not in server_names:
        continue
    certificates = directives.get("ssl_certificate", [])
    private_keys = directives.get("ssl_certificate_key", [])
    if not certificates and not private_keys:
        continue
    if (
        len(certificates) != 1
        or len(certificates[0]) != 1
        or len(private_keys) != 1
        or len(private_keys[0]) != 1
    ):
        raise SystemExit(1)
    tls_bindings.append((certificates[0][0], private_keys[0][0]))

if tls_bindings != [(expected_certificate, expected_private_key)]:
    raise SystemExit(1)
binding = {
    "domain": domain,
    "ssl_certificate": expected_certificate,
    "ssl_certificate_key": expected_private_key,
}
digest = hashlib.sha256(
    json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()
print(expected_certificate)
print(expected_private_key)
print(digest)
PY
	)" || fail "NGINX TLS server must reference the configured Certbot live lineage"
	NGINX_SSL_CERTIFICATE_PATH="$(printf '%s\n' "${parsed_binding}" | sed -n '1p')"
	NGINX_SSL_CERTIFICATE_KEY_PATH="$(printf '%s\n' "${parsed_binding}" | sed -n '2p')"
	NGINX_TLS_BINDING_SHA256="$(printf '%s\n' "${parsed_binding}" | sed -n '3p')"
	[ "${NGINX_SSL_CERTIFICATE_PATH}" = "${CERTIFICATE_PATH}" ] && \
		[ "${NGINX_SSL_CERTIFICATE_KEY_PATH}" = "${PRIVATE_KEY_PATH}" ] && \
		[[ "${NGINX_TLS_BINDING_SHA256}" =~ ^[0-9a-f]{64}$ ]] || \
		fail "NGINX TLS server must reference the configured Certbot live lineage"
}

refresh_tls_binding_state() {
	assert_certbot_lineage_ready
	assert_certificate_private_key_match
	assert_nginx_lineage_binding
}

assert_safe_evidence_file() {
	local path="$1"
	[ -f "${path}" ] && [ ! -L "${path}" ] || fail "evidence must be a regular non-symlink file"
	[ "$(owner_uid_of "${path}")" = "0" ] || fail "evidence must be owned by root"
	[ "$(mode_of "${path}")" = "600" ] || fail "evidence must have mode 0600"
}

assert_safe_deploy_hook() {
	local mode=""
	local hook_parent=""
	local resolved_hook=""
	[ -f "${DEPLOY_HOOK_PATH}" ] && [ ! -L "${DEPLOY_HOOK_PATH}" ] || \
		fail "deploy hook must be a regular non-symlink file"
	resolved_hook="$(readlink -f -- "${DEPLOY_HOOK_PATH}")" || fail "deploy hook path cannot be resolved"
	[ "${resolved_hook}" = "${DEPLOY_HOOK_PATH}" ] || fail "deploy hook path must be canonical and contain no symlink"
	[ "$(owner_uid_of "${DEPLOY_HOOK_PATH}")" = "0" ] || fail "deploy hook must be owned by root"
	mode="$(mode_of "${DEPLOY_HOOK_PATH}")"
	[[ "${mode}" =~ ^[0-7]{3,4}$ ]] || fail "deploy hook mode is invalid"
	(( (8#${mode} & 0022) == 0 )) || fail "deploy hook must not be group/world writable"
	[ -x "${DEPLOY_HOOK_PATH}" ] || fail "deploy hook must be executable"
	hook_parent="$(dirname "${DEPLOY_HOOK_PATH}")"
	[[ "${hook_parent}" = */renewal-hooks/deploy ]] || \
		fail "deploy hook must be located directly in renewal-hooks/deploy"
	assert_safe_parent_chain "${hook_parent}" "deploy hook parent"
}

deploy_hook_sha256() {
	local digest=""
	digest="$(sha256sum -- "${DEPLOY_HOOK_PATH}" | awk '{print $1}')" || fail "deploy hook SHA256 could not be computed"
	[[ "${digest}" =~ ^[0-9a-f]{64}$ ]] || fail "deploy hook SHA256 is invalid"
	printf '%s' "${digest}"
}

assert_timer_ready() {
	local next_run=""
	systemctl is-enabled --quiet "${TIMER_NAME}" || fail "certificate renewal timer is not enabled"
	systemctl is-active --quiet "${TIMER_NAME}" || fail "certificate renewal timer is not active"
	next_run="$(systemctl show "${TIMER_NAME}" --property=NextElapseUSecRealtime --value)" || \
		fail "certificate renewal timer next run could not be read"
	next_run="${next_run#"${next_run%%[![:space:]]*}"}"
	next_run="${next_run%"${next_run##*[![:space:]]}"}"
	case "${next_run}" in
		""|n/a|N/A) fail "certificate renewal timer has no next run" ;;
	esac
	printf '%s' "${next_run}"
}

assert_safe_certbot_executable() {
	local mode=""
	local executable_parent=""
	[ -n "${CERTBOT_REAL_PATH}" ] && [ -f "${CERTBOT_REAL_PATH}" ] && \
		[ -x "${CERTBOT_REAL_PATH}" ] && [ ! -L "${CERTBOT_REAL_PATH}" ] || \
		fail "resolved Certbot executable must be a regular executable file"
	[ "$(owner_uid_of "${CERTBOT_REAL_PATH}")" = "0" ] || \
		fail "resolved Certbot executable must be owned by root"
	mode="$(mode_of "${CERTBOT_REAL_PATH}")"
	[[ "${mode}" =~ ^[0-7]{3,4}$ ]] || fail "resolved Certbot executable mode is invalid"
	(( (8#${mode} & 0022) == 0 )) || \
		fail "resolved Certbot executable must not be group/world writable"
	executable_parent="$(dirname "${CERTBOT_REAL_PATH}")"
	assert_safe_parent_chain "${executable_parent}" "Certbot executable parent"
}

resolve_timer_execution_chain() {
	local service_unit=""
	local exec_start=""
	local exec_start_sha256=""

	service_unit="$(systemctl show "${TIMER_NAME}" --property=Unit --value)" || \
		fail "certificate renewal timer triggered service could not be read"
	service_unit="${service_unit#"${service_unit%%[![:space:]]*}"}"
	service_unit="${service_unit%"${service_unit##*[![:space:]]}"}"
	[[ "${service_unit}" =~ ^[A-Za-z0-9][A-Za-z0-9_.@-]*\.service$ ]] || \
		fail "certificate renewal timer must trigger one explicit service unit"

	exec_start="$(systemctl show "${service_unit}" --property=ExecStart --value)" || \
		fail "certificate renewal service ExecStart could not be read"
	[ -n "${exec_start}" ] || fail "certificate renewal service ExecStart is empty"
	exec_start_sha256="$(
		"${RELEASE_TOOL_PYTHON}" - \
			"${exec_start}" "${CERTBOT_REAL_PATH}" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sys

raw_exec_start, expected_certbot_real_path = sys.argv[1:]
value = raw_exec_start.strip()
if not value or "\n" in value or value.count("{ path=") != 1:
    raise SystemExit(1)

# `systemctl show --property=ExecStart --value` renders the resolved command as
# one command record. Parse that record fail-closed instead of reading unit-file
# text, which would miss drop-ins and the final command resolution from systemd.
match = re.fullmatch(
    r"\{\s*path=(?P<path>[^;]+?)\s*;\s*"
    r"argv\[\]=(?P<argv>.*?)\s*;\s*"
    r"ignore_errors=(?P<ignore>[^;]+?)\s*;(?P<tail>.*)\}",
    value,
)
if match is None:
    raise SystemExit(1)
exec_path = match.group("path").strip()
ignore_errors = match.group("ignore").strip()
if not exec_path.startswith("/") or ignore_errors != "no":
    raise SystemExit(1)
if os.path.realpath(exec_path) != expected_certbot_real_path:
    # This rejects `/bin/sh -c`, `/usr/bin/env`, wrapper services, and unrelated
    # no-op commands even when their argument text mentions `certbot renew`.
    raise SystemExit(1)

try:
    argv = shlex.split(match.group("argv"), posix=True)
except ValueError as exc:
    raise SystemExit(1) from exc
if not argv:
    raise SystemExit(1)
argv0 = argv[0]
if argv0.startswith("/"):
    argv0_matches = os.path.realpath(argv0) == expected_certbot_real_path
else:
    argv0_matches = argv0 == os.path.basename(exec_path)
if not argv0_matches:
    raise SystemExit(1)
arguments = argv[1:]
if arguments.count("renew") != 1:
    raise SystemExit(1)
allowed_renewal_flags = {
    "--non-interactive",
    "--no-random-sleep-on-renew",
    "--no-self-upgrade",
    "--quiet",
    "-n",
    "-q",
}
if any(token != "renew" and token not in allowed_renewal_flags for token in arguments):
    raise SystemExit(1)

canonical = json.dumps(
    {
        "argv": [expected_certbot_real_path, *argv[1:]],
        "ignore_errors": False,
        "path": expected_certbot_real_path,
    },
    ensure_ascii=True,
    sort_keys=True,
    separators=(",", ":"),
)
print(hashlib.sha256(canonical.encode("utf-8")).hexdigest())
PY
	)" || fail "certificate renewal service must directly execute the resolved Certbot renew command"
	[[ "${exec_start_sha256}" =~ ^[0-9a-f]{64}$ ]] || \
		fail "certificate renewal service ExecStart digest is invalid"

	TIMER_SERVICE_UNIT="${service_unit}"
	RENEWAL_EXEC_START_SHA256="${exec_start_sha256}"
}

certificate_fingerprint() {
	local path="$1"
	local fingerprint=""
	fingerprint="$(openssl x509 -in "${path}" -noout -fingerprint -sha256)" || \
		fail "certificate SHA256 fingerprint could not be read"
	fingerprint="${fingerprint#*=}"
	fingerprint="$(printf '%s' "${fingerprint}" | tr -d ':[:space:]' | tr 'A-F' 'a-f')"
	[[ "${fingerprint}" =~ ^[0-9a-f]{64}$ ]] || fail "certificate SHA256 fingerprint is invalid"
	printf '%s' "${fingerprint}"
}

assert_certificate_and_served_leaf_ready() {
	local served_leaf=""
	local pem_fingerprint=""
	local served_fingerprint=""
	[ "$(file_type_of "${CERTIFICATE_REAL_PATH}")" = "regular file" ] || fail "certificate file is missing"
	openssl x509 -in "${CERTIFICATE_PATH}" -noout -checkhost "${DOMAIN}" >/dev/null 2>&1 || \
		fail "certificate does not match the requested domain"
	openssl x509 -in "${CERTIFICATE_PATH}" -noout \
		-checkend "${MINIMUM_CERTIFICATE_VALIDITY_SECONDS}" >/dev/null 2>&1 || \
		fail "certificate expires within ${MINIMUM_CERTIFICATE_VALIDITY_DAYS} days"

	served_leaf="$(mktemp)"
	CLEANUP_PATHS+=("${served_leaf}")
	chmod 0600 "${served_leaf}"
	if ! openssl s_client \
		-connect 127.0.0.1:443 \
		-servername "${DOMAIN}" \
		-showcerts </dev/null 2>/dev/null | \
		openssl x509 -outform PEM -out "${served_leaf}" >/dev/null 2>&1; then
		fail "served TLS leaf could not be read from 127.0.0.1:443"
	fi
	[ -s "${served_leaf}" ] || fail "served TLS leaf is empty"
	openssl x509 -in "${served_leaf}" -noout -checkhost "${DOMAIN}" >/dev/null 2>&1 || \
		fail "served TLS leaf does not match the requested domain"
	openssl x509 -in "${served_leaf}" -noout \
		-checkend "${MINIMUM_CERTIFICATE_VALIDITY_SECONDS}" >/dev/null 2>&1 || \
		fail "served TLS leaf expires within ${MINIMUM_CERTIFICATE_VALIDITY_DAYS} days"
	pem_fingerprint="$(certificate_fingerprint "${CERTIFICATE_PATH}")"
	served_fingerprint="$(certificate_fingerprint "${served_leaf}")"
	[ "${served_fingerprint}" = "${pem_fingerprint}" ] || \
		fail "served TLS leaf does not match the specified PEM leaf"
	printf '%s' "${pem_fingerprint}"
}

execute_deploy_hook_and_prove_reload() {
	local reload_before=""
	local reload_after=""
	reload_before="$(systemctl show nginx --property=ExecReload --value)" || \
		fail "NGINX reload execution state could not be read before deploy hook"
	"${DEPLOY_HOOK_PATH}" >/dev/null 2>&1 || fail "persistent certificate deploy hook execution failed"
	reload_after="$(systemctl show nginx --property=ExecReload --value)" || \
		fail "NGINX reload execution state could not be read after deploy hook"
	[ -n "${reload_after}" ] && [ "${reload_after}" != "${reload_before}" ] || \
		fail "persistent certificate deploy hook did not execute the NGINX reload action"
	nginx -t >/dev/null 2>&1 || fail "NGINX configuration validation failed after deploy hook"
	systemctl is-active --quiet nginx || fail "NGINX is not active after deploy hook"
}

fsync_directory() {
	"${RELEASE_TOOL_PYTHON}" - "$1" <<'PY'
import os
import sys

descriptor = os.open(sys.argv[1], os.O_RDONLY)
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY
}

invalidate_existing_evidence() {
	[ -e "${EVIDENCE_PATH}" ] || return 0
	assert_safe_evidence_file "${EVIDENCE_PATH}"
	"${RELEASE_TOOL_PYTHON}" - "${EVIDENCE_PATH}" "${EVIDENCE_PARENT}" <<'PY'
import os
import stat
import sys

path, parent = sys.argv[1:]
metadata = os.lstat(path)
if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
    raise SystemExit(1)
os.unlink(path)
descriptor = os.open(parent, os.O_RDONLY)
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY
}

MODE="${1:-}"
case "${MODE}" in
	generate|verify) shift ;;
	-h|--help|"") usage; exit 0 ;;
	*) fail "mode must be generate or verify" ;;
esac

DOMAIN=""
CERTIFICATE_PATH=""
RENEWAL_OWNER=""
TIMER_NAME=""
DEPLOY_HOOK_PATH=""
EVIDENCE_PATH=""

while [ "$#" -gt 0 ]; do
	case "$1" in
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
		--owner)
			[ "$#" -ge 2 ] || fail "--owner requires a value"
			RENEWAL_OWNER="$2"
			shift 2
			;;
		--timer)
			[ "$#" -ge 2 ] || fail "--timer requires a value"
			TIMER_NAME="$2"
			shift 2
			;;
		--deploy-hook-path)
			[ "$#" -ge 2 ] || fail "--deploy-hook-path requires a value"
			DEPLOY_HOOK_PATH="$2"
			shift 2
			;;
		--evidence-path)
			[ "$#" -ge 2 ] || fail "--evidence-path requires a value"
			EVIDENCE_PATH="$2"
			shift 2
			;;
		-h|--help)
			usage
			exit 0
			;;
		*) fail "unsupported argument: $1" ;;
	esac
done

[ "$(id -u)" = "0" ] || fail "certificate renewal readiness must run as root"
[[ "${EVIDENCE_PATH}" = /* ]] || fail "evidence path must be explicitly set and absolute"
[ ! -L "${EVIDENCE_PATH}" ] || fail "evidence path must not be a symlink"

for command_name in awk chmod date dirname id mktemp nginx openssl readlink rm sed sha256sum stat systemctl tr; do
	npcink_ai_cloud_require_cmd "${command_name}"
done
if [ "${MODE}" = "generate" ]; then
	npcink_ai_cloud_require_cmd install
	npcink_ai_cloud_require_cmd mv
fi

RELEASE_TOOL_PYTHON="$(npcink_ai_cloud_release_tool_python)"
npcink_ai_cloud_require_host_release_tool_python "${RELEASE_TOOL_PYTHON}" || \
	fail "host release-tool Python 3.11 or newer is required"

EVIDENCE_PARENT="$(dirname "${EVIDENCE_PATH}")"
if [ "${MODE}" = "generate" ] && [ ! -e "${EVIDENCE_PARENT}" ]; then
	install -d -o root -g root -m 0700 "${EVIDENCE_PARENT}"
fi
assert_safe_parent_chain "${EVIDENCE_PARENT}" "evidence parent"
if [ "${MODE}" = "generate" ]; then
	# Unlink and fsync the old receipt before any timer, hook, certificate, or
	# NGINX readiness check. A failed regeneration can therefore never leave a
	# previously passing receipt available to verify.
	GENERATION_IN_PROGRESS=1
	invalidate_existing_evidence
else
	assert_safe_evidence_file "${EVIDENCE_PATH}"
fi

npcink_ai_cloud_require_cmd certbot
CERTBOT_COMMAND="$(command -v certbot)" || fail "Certbot executable could not be resolved"
[[ "${CERTBOT_COMMAND}" = /* ]] || fail "Certbot executable path must be absolute"
CERTBOT_REAL_PATH="$(readlink -f -- "${CERTBOT_COMMAND}")" || \
	fail "Certbot executable path cannot be canonicalized"
assert_safe_certbot_executable
TIMER_SERVICE_UNIT=""
RENEWAL_EXEC_START_SHA256=""

[[ "${DOMAIN}" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]] || fail "domain is missing or invalid"
[ "${RENEWAL_OWNER}" = "certbot" ] || fail "renewal owner must be certbot"
[[ "${TIMER_NAME}" =~ ^[A-Za-z0-9][A-Za-z0-9_.@-]*\.timer$ ]] || \
	fail "renewal timer must be an explicitly named safe systemd timer unit"
[[ "${CERTIFICATE_PATH}" = /* ]] || fail "certificate path must be explicitly set and absolute"
[[ "${DEPLOY_HOOK_PATH}" = /* ]] || fail "deploy hook path must be explicitly set and absolute"
if [[ "${CERTIFICATE_PATH}" =~ ^/etc/letsencrypt/live/([A-Za-z0-9][A-Za-z0-9_.-]*)/fullchain\.pem$ ]]; then
	CERTBOT_LINEAGE_NAME="${BASH_REMATCH[1]}"
else
	fail "certificate path must name a Certbot live fullchain.pem lineage"
fi
PRIVATE_KEY_PATH="/etc/letsencrypt/live/${CERTBOT_LINEAGE_NAME}/privkey.pem"
CERTIFICATE_REAL_PATH=""
PRIVATE_KEY_REAL_PATH=""
NGINX_SSL_CERTIFICATE_PATH=""
NGINX_SSL_CERTIFICATE_KEY_PATH=""
NGINX_TLS_BINDING_SHA256=""
assert_safe_deploy_hook
CURRENT_DEPLOY_HOOK_SHA256="$(deploy_hook_sha256)"

if [ "${MODE}" = "verify" ]; then
	CURRENT_NEXT_RUN="$(assert_timer_ready)"
	[ -n "${CURRENT_NEXT_RUN}" ] || fail "certificate renewal timer next run is empty"
	resolve_timer_execution_chain
	refresh_tls_binding_state
	CURRENT_CERTIFICATE_FINGERPRINT="$(assert_certificate_and_served_leaf_ready)"
	PRE_HOOK_CERTIFICATE_REAL_PATH="${CERTIFICATE_REAL_PATH}"
	PRE_HOOK_PRIVATE_KEY_REAL_PATH="${PRIVATE_KEY_REAL_PATH}"
	PRE_HOOK_NGINX_TLS_BINDING_SHA256="${NGINX_TLS_BINDING_SHA256}"
	NOW_EPOCH="$(date -u +%s)"
	"${RELEASE_TOOL_PYTHON}" - \
		"${EVIDENCE_PATH}" \
		"${CONTRACT}" \
		"${DOMAIN}" \
		"${CERTIFICATE_PATH}" \
		"${CERTIFICATE_REAL_PATH}" \
		"${PRIVATE_KEY_PATH}" \
		"${PRIVATE_KEY_REAL_PATH}" \
		"${CERTBOT_LINEAGE_NAME}" \
		"${CURRENT_CERTIFICATE_FINGERPRINT}" \
		"${NGINX_SSL_CERTIFICATE_PATH}" \
		"${NGINX_SSL_CERTIFICATE_KEY_PATH}" \
		"${NGINX_TLS_BINDING_SHA256}" \
		"${RENEWAL_OWNER}" \
		"${TIMER_NAME}" \
		"${TIMER_SERVICE_UNIT}" \
		"${CERTBOT_REAL_PATH}" \
		"${RENEWAL_EXEC_START_SHA256}" \
		"${DEPLOY_HOOK_PATH}" \
		"${CURRENT_DEPLOY_HOOK_SHA256}" \
		"${MINIMUM_CERTIFICATE_VALIDITY_DAYS}" \
		"${MAX_EVIDENCE_AGE_SECONDS}" \
		"${NOW_EPOCH}" <<'PY' || fail "certificate renewal evidence is invalid or stale"
import datetime as dt
import json
import sys
from pathlib import Path

(
    evidence_path,
    contract,
    domain,
    certificate_path,
    certificate_real_path,
    private_key_path,
    private_key_real_path,
    certbot_lineage_name,
    certificate_fingerprint,
    nginx_ssl_certificate_path,
    nginx_ssl_certificate_key_path,
    nginx_tls_binding_sha256,
    owner,
    timer,
    renewal_service,
    certbot_real_path,
    renewal_exec_start_sha256,
    deploy_hook_path,
    deploy_hook_sha256,
    minimum_days,
    maximum_age,
    now_epoch,
) = sys.argv[1:]
payload = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
expected_keys = {
    "contract",
    "status",
    "domain",
    "certificate_path",
    "certificate_real_path",
    "private_key_path",
    "private_key_real_path",
    "certbot_lineage_name",
    "certificate_leaf_sha256_fingerprint",
    "certificate_private_key_match",
    "renewal_owner",
    "timer",
    "timer_enabled",
    "timer_active",
    "timer_next_run",
    "renewal_service",
    "certbot_real_path",
    "renewal_exec_start_sha256",
    "renewal_dry_run_passed",
    "deploy_hook_path",
    "deploy_hook_sha256",
    "deploy_hook_execution_passed",
    "nginx_config_valid",
    "nginx_ssl_certificate_path",
    "nginx_ssl_certificate_key_path",
    "nginx_tls_binding_sha256",
    "nginx_references_certbot_lineage",
    "nginx_reload_passed",
    "nginx_active",
    "certificate_domain_match",
    "certificate_validity_floor_passed",
    "served_certificate_domain_match",
    "served_certificate_validity_floor_passed",
    "served_leaf_matches_certificate",
    "minimum_validity_days",
    "generated_at",
    "generated_at_epoch",
}
if not isinstance(payload, dict) or set(payload) != expected_keys:
    raise SystemExit(1)
expected_values = {
    "contract": contract,
    "status": "passed",
    "domain": domain,
    "certificate_path": certificate_path,
    "certificate_real_path": certificate_real_path,
    "private_key_path": private_key_path,
    "private_key_real_path": private_key_real_path,
    "certbot_lineage_name": certbot_lineage_name,
    "certificate_leaf_sha256_fingerprint": certificate_fingerprint,
    "certificate_private_key_match": True,
    "renewal_owner": owner,
    "timer": timer,
    "timer_enabled": True,
    "timer_active": True,
    "renewal_service": renewal_service,
    "certbot_real_path": certbot_real_path,
    "renewal_exec_start_sha256": renewal_exec_start_sha256,
    "renewal_dry_run_passed": True,
    "deploy_hook_path": deploy_hook_path,
    "deploy_hook_sha256": deploy_hook_sha256,
    "deploy_hook_execution_passed": True,
    "nginx_config_valid": True,
    "nginx_ssl_certificate_path": nginx_ssl_certificate_path,
    "nginx_ssl_certificate_key_path": nginx_ssl_certificate_key_path,
    "nginx_tls_binding_sha256": nginx_tls_binding_sha256,
    "nginx_references_certbot_lineage": True,
    "nginx_reload_passed": True,
    "nginx_active": True,
    "certificate_domain_match": True,
    "certificate_validity_floor_passed": True,
    "served_certificate_domain_match": True,
    "served_certificate_validity_floor_passed": True,
    "served_leaf_matches_certificate": True,
    "minimum_validity_days": int(minimum_days),
}
for key, expected in expected_values.items():
    if payload.get(key) != expected:
        raise SystemExit(1)
fingerprint = payload.get("certificate_leaf_sha256_fingerprint")
if not isinstance(fingerprint, str) or len(fingerprint) != 64:
    raise SystemExit(1)
try:
    int(fingerprint, 16)
except ValueError as exc:
    raise SystemExit(1) from exc
binding_sha256 = payload.get("nginx_tls_binding_sha256")
if not isinstance(binding_sha256, str) or len(binding_sha256) != 64:
    raise SystemExit(1)
try:
    int(binding_sha256, 16)
except ValueError as exc:
    raise SystemExit(1) from exc
next_run = payload.get("timer_next_run")
if not isinstance(next_run, str) or not next_run.strip() or next_run.lower() == "n/a":
    raise SystemExit(1)
generated_epoch = payload.get("generated_at_epoch")
if not isinstance(generated_epoch, int):
    raise SystemExit(1)
age = int(now_epoch) - generated_epoch
if age < -300 or age > int(maximum_age):
    raise SystemExit(1)
generated_at = payload.get("generated_at")
if not isinstance(generated_at, str) or not generated_at.endswith("Z"):
    raise SystemExit(1)
parsed = dt.datetime.fromisoformat(generated_at[:-1] + "+00:00")
if abs(int(parsed.timestamp()) - generated_epoch) > 1:
    raise SystemExit(1)
PY
	execute_deploy_hook_and_prove_reload
	refresh_tls_binding_state
	POST_HOOK_CERTIFICATE_FINGERPRINT="$(assert_certificate_and_served_leaf_ready)"
	[ "${CERTIFICATE_REAL_PATH}" = "${PRE_HOOK_CERTIFICATE_REAL_PATH}" ] && \
		[ "${PRIVATE_KEY_REAL_PATH}" = "${PRE_HOOK_PRIVATE_KEY_REAL_PATH}" ] && \
		[ "${NGINX_TLS_BINDING_SHA256}" = "${PRE_HOOK_NGINX_TLS_BINDING_SHA256}" ] && \
		[ "${POST_HOOK_CERTIFICATE_FINGERPRINT}" = "${CURRENT_CERTIFICATE_FINGERPRINT}" ] || \
		fail "certificate or NGINX TLS binding changed during deploy-hook verification"
	printf '[certificate-renewal:ok] verified fresh readiness evidence: %s\n' "${EVIDENCE_PATH}"
	exit 0
fi

TIMER_NEXT_RUN="$(assert_timer_ready)"
resolve_timer_execution_chain
refresh_tls_binding_state
assert_certificate_and_served_leaf_ready >/dev/null
"${CERTBOT_REAL_PATH}" renew --dry-run --cert-name "${CERTBOT_LINEAGE_NAME}" --run-deploy-hooks >/dev/null 2>&1 || \
	fail "Certbot renewal dry run with deploy hooks failed"
execute_deploy_hook_and_prove_reload
refresh_tls_binding_state
CERTIFICATE_FINGERPRINT="$(assert_certificate_and_served_leaf_ready)"

GENERATED_AT_EPOCH="$(date -u +%s)"
GENERATED_AT="$(
	"${RELEASE_TOOL_PYTHON}" - "${GENERATED_AT_EPOCH}" <<'PY'
import datetime as dt
import sys

value = dt.datetime.fromtimestamp(int(sys.argv[1]), tz=dt.timezone.utc)
print(value.isoformat(timespec="seconds").replace("+00:00", "Z"))
PY
)"
EVIDENCE_TMP="$(mktemp "${EVIDENCE_PARENT}/.certificate-renewal-readiness.XXXXXX")"
CLEANUP_PATHS+=("${EVIDENCE_TMP}")
chmod 0600 "${EVIDENCE_TMP}"
"${RELEASE_TOOL_PYTHON}" - \
	"${EVIDENCE_TMP}" \
	"${CONTRACT}" \
	"${DOMAIN}" \
	"${CERTIFICATE_PATH}" \
	"${CERTIFICATE_REAL_PATH}" \
	"${PRIVATE_KEY_PATH}" \
	"${PRIVATE_KEY_REAL_PATH}" \
	"${CERTBOT_LINEAGE_NAME}" \
	"${CERTIFICATE_FINGERPRINT}" \
	"${NGINX_SSL_CERTIFICATE_PATH}" \
	"${NGINX_SSL_CERTIFICATE_KEY_PATH}" \
	"${NGINX_TLS_BINDING_SHA256}" \
	"${RENEWAL_OWNER}" \
	"${TIMER_NAME}" \
	"${TIMER_NEXT_RUN}" \
	"${TIMER_SERVICE_UNIT}" \
	"${CERTBOT_REAL_PATH}" \
	"${RENEWAL_EXEC_START_SHA256}" \
	"${DEPLOY_HOOK_PATH}" \
	"${CURRENT_DEPLOY_HOOK_SHA256}" \
	"${MINIMUM_CERTIFICATE_VALIDITY_DAYS}" \
	"${GENERATED_AT}" \
	"${GENERATED_AT_EPOCH}" <<'PY'
import json
import os
import sys

(
    path,
    contract,
    domain,
    certificate_path,
    certificate_real_path,
    private_key_path,
    private_key_real_path,
    certbot_lineage_name,
    certificate_fingerprint,
    nginx_ssl_certificate_path,
    nginx_ssl_certificate_key_path,
    nginx_tls_binding_sha256,
    owner,
    timer,
    timer_next_run,
    renewal_service,
    certbot_real_path,
    renewal_exec_start_sha256,
    deploy_hook_path,
    deploy_hook_sha256,
    minimum_days,
    generated_at,
    generated_at_epoch,
) = sys.argv[1:]
payload = {
    "contract": contract,
    "status": "passed",
    "domain": domain,
    "certificate_path": certificate_path,
    "certificate_real_path": certificate_real_path,
    "private_key_path": private_key_path,
    "private_key_real_path": private_key_real_path,
    "certbot_lineage_name": certbot_lineage_name,
    "certificate_leaf_sha256_fingerprint": certificate_fingerprint,
    "certificate_private_key_match": True,
    "renewal_owner": owner,
    "timer": timer,
    "timer_enabled": True,
    "timer_active": True,
    "timer_next_run": timer_next_run,
    "renewal_service": renewal_service,
    "certbot_real_path": certbot_real_path,
    "renewal_exec_start_sha256": renewal_exec_start_sha256,
    "renewal_dry_run_passed": True,
    "deploy_hook_path": deploy_hook_path,
    "deploy_hook_sha256": deploy_hook_sha256,
    "deploy_hook_execution_passed": True,
    "nginx_config_valid": True,
    "nginx_ssl_certificate_path": nginx_ssl_certificate_path,
    "nginx_ssl_certificate_key_path": nginx_ssl_certificate_key_path,
    "nginx_tls_binding_sha256": nginx_tls_binding_sha256,
    "nginx_references_certbot_lineage": True,
    "nginx_reload_passed": True,
    "nginx_active": True,
    "certificate_domain_match": True,
    "certificate_validity_floor_passed": True,
    "served_certificate_domain_match": True,
    "served_certificate_validity_floor_passed": True,
    "served_leaf_matches_certificate": True,
    "minimum_validity_days": int(minimum_days),
    "generated_at": generated_at,
    "generated_at_epoch": int(generated_at_epoch),
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.chmod(path, 0o600)
PY
mv -f "${EVIDENCE_TMP}" "${EVIDENCE_PATH}"
EVIDENCE_TMP=""
fsync_directory "${EVIDENCE_PARENT}"
assert_safe_evidence_file "${EVIDENCE_PATH}"
printf '[certificate-renewal:ok] generated readiness evidence: %s\n' "${EVIDENCE_PATH}"
GENERATION_SUCCEEDED=1
