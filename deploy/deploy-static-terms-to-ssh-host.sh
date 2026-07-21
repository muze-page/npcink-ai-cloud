#!/usr/bin/env bash
set -euo pipefail
set +x

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"

npcink_ai_cloud_require_cmd curl
npcink_ai_cloud_require_cmd find
npcink_ai_cloud_require_cmd grep
npcink_ai_cloud_require_cmd python3
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

fail() {
	echo "[fail] $*" >&2
	exit 1
}

remote_shell_arg() {
	printf '%q' "$1"
}

[ -n "${SSH_HOST}" ] || fail "Missing NPCINK_CLOUD_DEPLOY_SSH_HOST"
[ "${SSH_USER}" = "root" ] || fail "Static terms production deployment requires the root SSH account"
[[ "${SSH_HOST}" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]*$ ]] || fail "SSH host contains unsupported characters"
[[ "${SSH_PORT}" =~ ^[0-9]+$ ]] &&
	[ "${SSH_PORT}" -ge 1 ] && [ "${SSH_PORT}" -le 65535 ] || fail "SSH port is invalid"
[[ "${SSH_CONNECT_TIMEOUT_SECONDS}" =~ ^[0-9]+$ ]] &&
	[ "${SSH_CONNECT_TIMEOUT_SECONDS}" -ge 1 ] || fail "SSH connect timeout is invalid"
[[ "${REMOTE_DIR}" =~ ^/[A-Za-z0-9._/-]+$ ]] || fail "Remote directory must be a safe absolute path"
case "${REMOTE_DIR}" in
	*/../*|*/..|*/./*|*/.|*//*|/) fail "Remote directory is not a canonical managed path" ;;
esac
[[ "${BASE_URL}" =~ ^https://[A-Za-z0-9][A-Za-z0-9.-]*(:443)?/?$ ]] ||
	fail "Static terms production base URL must be an HTTPS origin"

if [ -n "${SSH_IDENTITY_FILE}" ] && [ ! -f "${SSH_IDENTITY_FILE}" ]; then
	fail "SSH identity file not found: ${SSH_IDENTITY_FILE}"
fi

[ -d "${ROOT_DIR}/site/terms" ] || fail "Missing site/terms directory"
if find "${ROOT_DIR}/site/terms" -type l -print -quit | grep -q .; then
	fail "Static terms source must not contain symbolic links"
fi

SSH_TARGET="${SSH_USER}@${SSH_HOST}"
SSH_ARGS=(
	-p "${SSH_PORT}"
	-o StrictHostKeyChecking=yes
	-o BatchMode=yes
	-o ConnectTimeout="${SSH_CONNECT_TIMEOUT_SECONDS}"
)
SCP_ARGS=(
	-P "${SSH_PORT}"
	-o StrictHostKeyChecking=yes
	-o BatchMode=yes
	-o ConnectTimeout="${SSH_CONNECT_TIMEOUT_SECONDS}"
)

if [ -n "${SSH_IDENTITY_FILE}" ]; then
	SSH_ARGS+=(-i "${SSH_IDENTITY_FILE}")
	SCP_ARGS+=(-i "${SSH_IDENTITY_FILE}")
fi

umask 077
TMP_DIR="$(mktemp -d)"
chmod 0700 "${TMP_DIR}"
TERMS_BUNDLE="${TMP_DIR}/static-terms.tgz"
REMOTE_UPLOAD_ARMED=0
REMOTE_TERMS_BUNDLE=""

cleanup_local_and_remote() {
	local exit_status="$?"
	local cleanup_failed=0
	local cleanup_command=""
	trap - EXIT
	set +e
	if [ "${REMOTE_UPLOAD_ARMED}" = "1" ] && [ -n "${REMOTE_TERMS_BUNDLE}" ]; then
		cleanup_command="bash -s -- $(remote_shell_arg "${REMOTE_DIR}") $(remote_shell_arg "${REMOTE_TERMS_BUNDLE}")"
		if ! ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "${cleanup_command}" <<'REMOTE_CLEANUP'
set -euo pipefail
set +x

REMOTE_DIR="$1"
REMOTE_TERMS_BUNDLE="$2"

[ "$(id -u)" = "0" ] || exit 1
[[ "${REMOTE_DIR}" =~ ^/[A-Za-z0-9._/-]+$ ]] || exit 1
case "${REMOTE_DIR}" in
	*/../*|*/..|*/./*|*/.|*//*|/) exit 1 ;;
esac
[ "$(dirname "${REMOTE_TERMS_BUNDLE}")" = "${REMOTE_DIR}/.incoming" ] || exit 1
[[ "$(basename "${REMOTE_TERMS_BUNDLE}")" =~ ^static-terms\.[0-9a-f]{32}\.tgz$ ]] || exit 1
if [ -L "${REMOTE_TERMS_BUNDLE}" ]; then
	exit 1
fi
if [ -e "${REMOTE_TERMS_BUNDLE}" ]; then
	[ -f "${REMOTE_TERMS_BUNDLE}" ] || exit 1
	[ "$(stat -c '%u' "${REMOTE_TERMS_BUNDLE}")" = "0" ] || exit 1
	rm -f -- "${REMOTE_TERMS_BUNDLE}"
fi
[ ! -e "${REMOTE_TERMS_BUNDLE}" ] && [ ! -L "${REMOTE_TERMS_BUNDLE}" ]
REMOTE_CLEANUP
		then
			cleanup_failed=1
		fi
	fi
	if ! rm -rf -- "${TMP_DIR}" || [ -e "${TMP_DIR}" ] || [ -L "${TMP_DIR}" ]; then
		cleanup_failed=1
	fi
	if [ "${cleanup_failed}" -ne 0 ]; then
		echo "[fail] Static terms local or protected-upload cleanup did not complete." >&2
		exit_status=1
	fi
	exit "${exit_status}"
}
trap cleanup_local_and_remote EXIT

tar czf "${TERMS_BUNDLE}" -C "${ROOT_DIR}/site" terms
chmod 0600 "${TERMS_BUNDLE}"

UPLOAD_TOKEN="$(python3 - <<'PY'
import secrets

print(secrets.token_hex(16))
PY
)"
[[ "${UPLOAD_TOKEN}" =~ ^[0-9a-f]{32}$ ]] || fail "Protected upload token generation failed"
REMOTE_TERMS_BUNDLE="${REMOTE_DIR}/.incoming/static-terms.${UPLOAD_TOKEN}.tgz"
REMOTE_UPLOAD_ARMED=1

PREPARE_COMMAND="bash -s -- $(remote_shell_arg "${REMOTE_DIR}") $(remote_shell_arg "${REMOTE_TERMS_BUNDLE}")"
ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "${PREPARE_COMMAND}" <<'REMOTE_PREPARE'
set -euo pipefail
set +x
umask 077

REMOTE_DIR="$1"
REMOTE_TERMS_BUNDLE="$2"

mode_of() {
	stat -c '%a' -- "$1"
}

[ "$(id -u)" = "0" ] || {
	echo "[fail] Static terms deployment must run as root." >&2
	exit 1
}
[[ "${REMOTE_DIR}" =~ ^/[A-Za-z0-9._/-]+$ ]] || exit 1
case "${REMOTE_DIR}" in
	*/../*|*/..|*/./*|*/.|*//*|/) exit 1 ;;
esac
[ -d "${REMOTE_DIR}" ] && [ ! -L "${REMOTE_DIR}" ] || exit 1
[ "$(cd "${REMOTE_DIR}" && pwd -P)" = "${REMOTE_DIR}" ] || exit 1
[ "$(stat -c '%u' "${REMOTE_DIR}")" = "0" ] || exit 1
REMOTE_MODE="$(mode_of "${REMOTE_DIR}")"
(( (8#${REMOTE_MODE} & 0022) == 0 )) || exit 1

INCOMING_DIR="${REMOTE_DIR}/.incoming"
if [ -e "${INCOMING_DIR}" ] || [ -L "${INCOMING_DIR}" ]; then
	[ -d "${INCOMING_DIR}" ] && [ ! -L "${INCOMING_DIR}" ] || exit 1
else
	install -d -o root -g root -m 0700 -- "${INCOMING_DIR}"
fi
[ "$(stat -c '%u' "${INCOMING_DIR}")" = "0" ] || exit 1
[ "$(mode_of "${INCOMING_DIR}")" = "700" ] || exit 1
[ "$(dirname "${REMOTE_TERMS_BUNDLE}")" = "${INCOMING_DIR}" ] || exit 1
[[ "$(basename "${REMOTE_TERMS_BUNDLE}")" =~ ^static-terms\.[0-9a-f]{32}\.tgz$ ]] || exit 1
[ ! -e "${REMOTE_TERMS_BUNDLE}" ] && [ ! -L "${REMOTE_TERMS_BUNDLE}" ] || exit 1
(set -o noclobber; : >"${REMOTE_TERMS_BUNDLE}")
chmod 0600 "${REMOTE_TERMS_BUNDLE}"
REMOTE_PREPARE

echo "[info] Uploading static terms bundle through a unique protected incoming path"
scp "${SCP_ARGS[@]}" "${TERMS_BUNDLE}" "${SSH_TARGET}:${REMOTE_TERMS_BUNDLE}"

echo "[info] Installing static terms into the frozen current release"
MUTATION_COMMAND="bash -s -- $(remote_shell_arg "${REMOTE_DIR}") $(remote_shell_arg "${REMOTE_TERMS_BUNDLE}") $(remote_shell_arg "${BASE_URL}")"
ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "${MUTATION_COMMAND}" <<'REMOTE_MUTATION'
set -euo pipefail
set +x
umask 077

REMOTE_DIR="$1"
REMOTE_TERMS_BUNDLE="$2"
BASE_URL="$3"
CURRENT_LINK="${REMOTE_DIR}/current"
DEPLOY_LOCK_DIR="${REMOTE_DIR}/.deploy-lock"
INCOMING_DIR="${REMOTE_DIR}/.incoming"
FAILURE_MARKER="${REMOTE_DIR}/.static-terms-failed"
WORK_DIR="${REMOTE_TERMS_BUNDLE%.tgz}.work"
WORK_CREATED=0
FROZEN_RELEASE=""
TERMS_TARGET=""
TERMS_PREVIOUS=""
ORIGINAL_TERMS_EXISTED=0
MUTATION_STARTED=0
TRANSACTION_COMMITTED=0
LOCK_HELD=0
CURRENT_PHASE="preflight"

fail() {
	echo "[fail] $*" >&2
	exit 1
}

mode_of() {
	stat -c '%a' -- "$1"
}

assert_root_private_directory() {
	local path="$1"
	local expected_mode="$2"
	[ -d "${path}" ] && [ ! -L "${path}" ] || return 1
	[ "$(stat -c '%u' "${path}")" = "0" ] || return 1
	[ "$(mode_of "${path}")" = "${expected_mode}" ] || return 1
}

assert_root_managed_directory() {
	local path="$1"
	local mode=""
	[ -d "${path}" ] && [ ! -L "${path}" ] || return 1
	[ "$(stat -c '%u' "${path}")" = "0" ] || return 1
	mode="$(mode_of "${path}")" || return 1
	[[ "${mode}" =~ ^[0-7]{3,4}$ ]] || return 1
	(( (8#${mode} & 0022) == 0 ))
}

assert_root_managed_tree() {
	local root="$1"
	local entry=""
	local mode=""
	assert_root_managed_directory "${root}" || return 1
	while IFS= read -r entry; do
		[ ! -L "${entry}" ] || return 1
		if [ ! -d "${entry}" ] && [ ! -f "${entry}" ]; then
			return 1
		fi
		[ "$(stat -c '%u' "${entry}")" = "0" ] || return 1
		mode="$(mode_of "${entry}")" || return 1
		[[ "${mode}" =~ ^[0-7]{3,4}$ ]] || return 1
		(( (8#${mode} & 0022) == 0 )) || return 1
	done < <(find "${root}" -mindepth 1 -print)
}

write_failure_marker() {
	local outcome="$1"
	local recovery="$2"
	local marker_tmp="${FAILURE_MARKER}.tmp.$$"
	{
		printf 'contract=npcink_cloud_static_terms_cutover.v1\n'
		printf 'status=failed\n'
		printf 'phase=%s\n' "${CURRENT_PHASE}"
		printf 'outcome=%s\n' "${outcome}"
		printf 'recovery=%s\n' "${recovery}"
		printf 'frozen_release=%s\n' "${FROZEN_RELEASE:-unavailable}"
	} >"${marker_tmp}" || return 1
	chmod 0600 "${marker_tmp}" || return 1
	mv -f -- "${marker_tmp}" "${FAILURE_MARKER}" || return 1
	[ -f "${FAILURE_MARKER}" ] && [ ! -L "${FAILURE_MARKER}" ] || return 1
	[ "$(stat -c '%u' "${FAILURE_MARKER}")" = "0" ] || return 1
	[ "$(mode_of "${FAILURE_MARKER}")" = "600" ]
}

cleanup_transaction_files() {
	local failed=0
	if [ "${WORK_CREATED}" = "1" ]; then
		rm -rf -- "${WORK_DIR}" || failed=1
		if [ -e "${WORK_DIR}" ] || [ -L "${WORK_DIR}" ]; then
			failed=1
		else
			WORK_CREATED=0
		fi
	fi
	if [ -L "${REMOTE_TERMS_BUNDLE}" ]; then
		failed=1
	elif [ -e "${REMOTE_TERMS_BUNDLE}" ]; then
		[ -f "${REMOTE_TERMS_BUNDLE}" ] || failed=1
		if [ "${failed}" -eq 0 ]; then
			rm -f -- "${REMOTE_TERMS_BUNDLE}" || failed=1
		fi
	fi
	if [ -e "${REMOTE_TERMS_BUNDLE}" ] || [ -L "${REMOTE_TERMS_BUNDLE}" ]; then
		failed=1
	fi
	return "${failed}"
}

rollback_terms() {
	local failed=0
	[ "${MUTATION_STARTED}" = "1" ] || return 0
	if [ "${ORIGINAL_TERMS_EXISTED}" = "1" ]; then
		if [ -d "${TERMS_PREVIOUS}" ] && [ ! -L "${TERMS_PREVIOUS}" ]; then
			if [ -e "${TERMS_TARGET}" ] || [ -L "${TERMS_TARGET}" ]; then
				rm -rf -- "${TERMS_TARGET}" || failed=1
			fi
			if [ ! -e "${TERMS_TARGET}" ] && [ ! -L "${TERMS_TARGET}" ]; then
				mv -- "${TERMS_PREVIOUS}" "${TERMS_TARGET}" || failed=1
			else
				failed=1
			fi
		elif [ -d "${TERMS_TARGET}" ] && [ ! -L "${TERMS_TARGET}" ]; then
			# The first rename failed before mutation; the original tree is still active.
			assert_root_managed_tree "${TERMS_TARGET}" || failed=1
		else
			failed=1
		fi
		[ -d "${TERMS_TARGET}" ] && [ ! -L "${TERMS_TARGET}" ] || failed=1
	else
		if [ -e "${TERMS_TARGET}" ] || [ -L "${TERMS_TARGET}" ]; then
			rm -rf -- "${TERMS_TARGET}" || failed=1
		fi
		[ ! -e "${TERMS_TARGET}" ] && [ ! -L "${TERMS_TARGET}" ] || failed=1
	fi
	if [ -n "${TERMS_PREVIOUS}" ] && { [ -e "${TERMS_PREVIOUS}" ] || [ -L "${TERMS_PREVIOUS}" ]; }; then
		failed=1
	fi
	return "${failed}"
}

release_deploy_lock() {
	[ "${LOCK_HELD}" = "1" ] || return 1
	rmdir -- "${DEPLOY_LOCK_DIR}" || return 1
	if [ -e "${DEPLOY_LOCK_DIR}" ] || [ -L "${DEPLOY_LOCK_DIR}" ]; then
		return 1
	fi
	LOCK_HELD=0
}

on_mutation_exit() {
	local exit_status="$?"
	local recovery_ok=1
	local cleanup_ok=1
	local marker_ok=1
	local outcome=""
	local recovery=""
	trap - EXIT HUP INT TERM
	set +e
	[ "${exit_status}" -ne 0 ] || exit_status=1

	if [ "${TRANSACTION_COMMITTED}" = "1" ]; then
		outcome="activation_committed_terminalization_incomplete"
		recovery="keep_new_terms_and_repair_cleanup_or_unlock"
		cleanup_transaction_files || cleanup_ok=0
	else
		rollback_terms || recovery_ok=0
		cleanup_transaction_files || cleanup_ok=0
		if [ "${recovery_ok}" = "1" ] && [ "${cleanup_ok}" = "1" ]; then
			outcome="rolled_back"
			recovery="previous_terms_restored_or_no_prior_terms_recreated"
		else
			outcome="recovery_incomplete"
			recovery="deployment_lock_retained_for_operator_recovery"
		fi
	fi

	write_failure_marker "${outcome}" "${recovery}" || marker_ok=0
	if [ "${TRANSACTION_COMMITTED}" != "1" ] &&
		[ "${recovery_ok}" = "1" ] && [ "${cleanup_ok}" = "1" ] && [ "${marker_ok}" = "1" ]; then
		if ! release_deploy_lock; then
			write_failure_marker "rolled_back_unlock_failed" \
				"deployment_lock_retained_after_rollback" >/dev/null 2>&1 || true
		fi
	fi
	if [ "${LOCK_HELD}" = "1" ]; then
		echo "[fail] Static terms deployment lock retained for operator recovery: ${DEPLOY_LOCK_DIR}" >&2
	fi
	exit "${exit_status}"
}

for required_command in basename chmod curl dirname find grep id install mkdir mv pwd readlink rm rmdir stat tar tr; do
	command -v "${required_command}" >/dev/null 2>&1 || fail "Remote command is missing: ${required_command}"
done
[ "$(id -u)" = "0" ] || fail "Static terms deployment must run as root"
[[ "${REMOTE_DIR}" =~ ^/[A-Za-z0-9._/-]+$ ]] || fail "Remote directory is unsafe"
case "${REMOTE_DIR}" in
	*/../*|*/..|*/./*|*/.|*//*|/) fail "Remote directory is not canonical" ;;
esac
[ -d "${REMOTE_DIR}" ] && [ ! -L "${REMOTE_DIR}" ] || fail "Managed remote directory is missing or linked"
REMOTE_DIR_CANONICAL="$(cd "${REMOTE_DIR}" && pwd -P)"
[ "${REMOTE_DIR_CANONICAL}" = "${REMOTE_DIR}" ] || fail "Managed remote directory changed after canonicalization"
assert_root_managed_directory "${REMOTE_DIR}" || fail "Managed remote directory ownership or mode is unsafe"
assert_root_private_directory "${INCOMING_DIR}" 700 || fail "Protected incoming directory is unsafe"
[ "$(dirname "${REMOTE_TERMS_BUNDLE}")" = "${INCOMING_DIR}" ] || fail "Static terms bundle is outside the protected incoming directory"
[[ "$(basename "${REMOTE_TERMS_BUNDLE}")" =~ ^static-terms\.[0-9a-f]{32}\.tgz$ ]] || fail "Static terms bundle name is unsafe"
[ -f "${REMOTE_TERMS_BUNDLE}" ] && [ ! -L "${REMOTE_TERMS_BUNDLE}" ] || fail "Static terms bundle is not a regular file"
[ "$(stat -c '%u' "${REMOTE_TERMS_BUNDLE}")" = "0" ] || fail "Static terms bundle owner is unsafe"
[ "$(mode_of "${REMOTE_TERMS_BUNDLE}")" = "600" ] || fail "Static terms bundle must have mode 0600"
[[ "${BASE_URL}" =~ ^https://[A-Za-z0-9][A-Za-z0-9.-]*(:443)?/?$ ]] || fail "Production base URL is unsafe"

CURRENT_PHASE="acquire-shared-deploy-lock"
if ! mkdir -- "${DEPLOY_LOCK_DIR}" 2>/dev/null; then
	rm -f -- "${REMOTE_TERMS_BUNDLE}" >/dev/null 2>&1 || true
	[ ! -e "${REMOTE_TERMS_BUNDLE}" ] && [ ! -L "${REMOTE_TERMS_BUNDLE}" ] ||
		echo "[fail] Protected upload cleanup failed while another host mutation held the lock." >&2
	fail "Production deploy or another mutating operation holds the shared lock"
fi
LOCK_HELD=1
trap on_mutation_exit EXIT
trap 'CURRENT_PHASE="signal-hup"; exit 129' HUP
trap 'CURRENT_PHASE="signal-int"; exit 130' INT
trap 'CURRENT_PHASE="signal-term"; exit 143' TERM
chmod 0700 "${DEPLOY_LOCK_DIR}"
assert_root_private_directory "${DEPLOY_LOCK_DIR}" 700 || fail "Shared deploy lock is not private"

CURRENT_PHASE="freeze-current-release"
[ -L "${CURRENT_LINK}" ] || fail "Current release link is missing"
FROZEN_RELEASE="$(readlink -f "${CURRENT_LINK}")"
[ -d "${FROZEN_RELEASE}" ] && [ ! -L "${FROZEN_RELEASE}" ] || fail "Current release target is missing"
[ "$(dirname "${FROZEN_RELEASE}")" = "${REMOTE_DIR_CANONICAL}" ] || fail "Current release is outside the managed root"
[[ "$(basename "${FROZEN_RELEASE}")" =~ ^release-[A-Za-z0-9._-]+$ ]] || fail "Current release name is unmanaged"
assert_root_managed_directory "${FROZEN_RELEASE}" || fail "Frozen release ownership or mode is unsafe"
[ -d "${FROZEN_RELEASE}/site" ] && [ ! -L "${FROZEN_RELEASE}/site" ] || fail "Frozen release site directory is unsafe"
assert_root_managed_directory "${FROZEN_RELEASE}/site" || fail "Frozen site directory ownership or mode is unsafe"
TERMS_TARGET="${FROZEN_RELEASE}/site/terms"
TERMS_PREVIOUS="${FROZEN_RELEASE}/site/terms.previous"
[ ! -e "${TERMS_PREVIOUS}" ] && [ ! -L "${TERMS_PREVIOUS}" ] || fail "A prior static terms recovery directory remains"

CURRENT_PHASE="extract-and-validate-staged-terms"
[ ! -e "${WORK_DIR}" ] && [ ! -L "${WORK_DIR}" ] || fail "Static terms work directory already exists"
mkdir -- "${WORK_DIR}"
WORK_CREATED=1
chmod 0700 "${WORK_DIR}"
assert_root_private_directory "${WORK_DIR}" 700 || fail "Static terms work directory is unsafe"
tar --no-same-owner --no-same-permissions -xzf "${REMOTE_TERMS_BUNDLE}" -C "${WORK_DIR}"
[ -d "${WORK_DIR}/terms" ] && [ ! -L "${WORK_DIR}/terms" ] || fail "Static terms archive root is invalid"
find "${WORK_DIR}/terms" -type d -exec chmod 0755 {} +
find "${WORK_DIR}/terms" -type f -exec chmod 0644 {} +
assert_root_managed_tree "${WORK_DIR}/terms" || fail "Static terms archive ownership, type, or mode is unsafe"
for required_file in \
	terms/index.html \
	terms/en/terms.html \
	terms/zh/terms.html \
	terms/styles.css; do
	[ -f "${WORK_DIR}/${required_file}" ] && [ ! -L "${WORK_DIR}/${required_file}" ] ||
		fail "Static terms archive is missing ${required_file}"
done

CURRENT_PHASE="activate-staged-terms"
if [ -e "${TERMS_TARGET}" ] || [ -L "${TERMS_TARGET}" ]; then
	[ -d "${TERMS_TARGET}" ] && [ ! -L "${TERMS_TARGET}" ] || fail "Existing static terms target is unsafe"
	assert_root_managed_tree "${TERMS_TARGET}" || fail "Existing static terms ownership, type, or mode is unsafe"
	ORIGINAL_TERMS_EXISTED=1
fi
MUTATION_STARTED=1
if [ "${ORIGINAL_TERMS_EXISTED}" = "1" ]; then
	mv -- "${TERMS_TARGET}" "${TERMS_PREVIOUS}"
fi
mv -- "${WORK_DIR}/terms" "${TERMS_TARGET}"

assert_remote_static_page() {
	local path="$1"
	local marker="$2"
	local body_file="${WORK_DIR}/response-$(printf '%s' "${path}" | tr '/.' '__').txt"
	curl -fsS --connect-timeout 5 --max-time 20 -o "${body_file}" -- "${BASE_URL%/}${path}" || return 1
	grep -Fq "${marker}" "${body_file}"
}

CURRENT_PHASE="validate-activated-static-terms"
assert_remote_static_page "/terms" "Npcink Cloud Legal Documents" || fail "Activated /terms validation failed"
assert_remote_static_page "/terms/en/terms.html" "Npcink Cloud Terms of Service" || fail "Activated English terms validation failed"
assert_remote_static_page "/terms/zh/terms.html" "Npcink Cloud 服务条款" || fail "Activated Chinese terms validation failed"
assert_remote_static_page "/terms/styles.css" "site-header" || fail "Activated terms stylesheet validation failed"
curl -fsS --connect-timeout 5 --max-time 20 -- "${BASE_URL%/}/health/live" >/dev/null || fail "Production health failed after static terms activation"
TRANSACTION_COMMITTED=1

CURRENT_PHASE="cleanup-transaction-files"
rm -rf -- "${WORK_DIR}"
[ ! -e "${WORK_DIR}" ] && [ ! -L "${WORK_DIR}" ] || fail "Static terms work directory cleanup failed"
WORK_CREATED=0
rm -f -- "${REMOTE_TERMS_BUNDLE}"
[ ! -e "${REMOTE_TERMS_BUNDLE}" ] && [ ! -L "${REMOTE_TERMS_BUNDLE}" ] || fail "Protected bundle cleanup failed"
if [ "${ORIGINAL_TERMS_EXISTED}" = "1" ]; then
	rm -rf -- "${TERMS_PREVIOUS}"
	[ ! -e "${TERMS_PREVIOUS}" ] && [ ! -L "${TERMS_PREVIOUS}" ] || fail "Previous terms cleanup failed"
fi

CURRENT_PHASE="clear-stale-static-terms-failure-evidence"
rm -f -- "${FAILURE_MARKER}"
[ ! -e "${FAILURE_MARKER}" ] && [ ! -L "${FAILURE_MARKER}" ] || fail "Stale static terms failure evidence could not be removed"

CURRENT_PHASE="release-shared-deploy-lock"
release_deploy_lock || fail "Shared deployment lock release could not be proved"
trap - EXIT HUP INT TERM
echo "[ok] Static terms updated in ${FROZEN_RELEASE}/site/terms"
REMOTE_MUTATION
REMOTE_UPLOAD_ARMED=0

assert_public_static_page() {
	local path="$1"
	local marker="$2"
	local body_file="${TMP_DIR}/public-$(printf '%s' "${path}" | tr '/.' '__').txt"
	if ! curl -fsS --max-time 20 -o "${body_file}" -- "${BASE_URL%/}${path}"; then
		echo "[fail] Static terms smoke failed for ${path}" >&2
		exit 1
	fi
	if ! grep -Fq "${marker}" "${body_file}"; then
		echo "[fail] Static terms smoke marker missing for ${path}: ${marker}" >&2
		exit 1
	fi
}

assert_public_static_page "/terms" "Npcink Cloud Legal Documents"
assert_public_static_page "/terms/en/terms.html" "Npcink Cloud Terms of Service"
assert_public_static_page "/terms/zh/terms.html" "Npcink Cloud 服务条款"
assert_public_static_page "/terms/styles.css" "site-header"

curl -fsS --max-time 20 -- "${BASE_URL%/}/health/live" >/dev/null
echo "[ok] Static terms deploy completed"
