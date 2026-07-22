#!/usr/bin/env bash

npcink_ai_cloud_require_cmd() {
	local cmd="$1"
	command -v "${cmd}" >/dev/null 2>&1 || {
		echo "[fail] Missing required command: ${cmd}" >&2
		exit 1
	}
}

npcink_ai_cloud_mode_of() {
	local mode=""
	if mode="$(stat -c '%a' -- "$1" 2>/dev/null)"; then
		:
	elif mode="$(stat -f '%Lp' "$1" 2>/dev/null)"; then
		:
	else
		return 1
	fi
	printf '%s' "${mode}"
}

npcink_ai_cloud_require_deploy_lock_owner() {
	local release_root="$1"
	local resolved_root=""
	local managed_root=""
	local deploy_lock_dir=""
	local owner_file=""
	local configured_owner="${NPCINK_CLOUD_DEPLOY_LOCK_OWNER:-}"
	local observed_owner=""

	resolved_root="$(cd "${release_root}" 2>/dev/null && pwd -P)" || {
		echo "[fail] Governed phase release root could not be resolved." >&2
		return 1
	}
	[[ "$(basename "${resolved_root}")" =~ ^release-[A-Za-z0-9._-]+$ ]] || {
		echo "[fail] Governed phase requires a managed release directory." >&2
		return 1
	}
	managed_root="$(dirname "${resolved_root}")"
	deploy_lock_dir="${managed_root}/.deploy-lock"
	owner_file="${deploy_lock_dir}/one-off-owner"
	if [[ ! "${configured_owner}" =~ ^[0-9a-f]{64}$ ]] || \
		[ ! -d "${deploy_lock_dir}" ] || [ -L "${deploy_lock_dir}" ] || \
		[ ! -O "${deploy_lock_dir}" ] || \
		[ "$(npcink_ai_cloud_mode_of "${deploy_lock_dir}" 2>/dev/null || true)" != "700" ] || \
		[ ! -f "${owner_file}" ] || [ -L "${owner_file}" ] || \
		[ ! -O "${owner_file}" ] || \
		[ "$(npcink_ai_cloud_mode_of "${owner_file}" 2>/dev/null || true)" != "600" ]; then
		echo "[fail] Governed phase requires a matching deployment-lock owner proof." >&2
		return 1
	fi
	IFS= read -r observed_owner <"${owner_file}" || return 1
	if [ "${observed_owner}" != "${configured_owner}" ]; then
		echo "[fail] Governed phase deployment-lock ownership proof failed." >&2
		return 1
	fi
}

npcink_ai_cloud_release_tool_python() {
	printf '%s' "${NPCINK_CLOUD_RELEASE_TOOL_PYTHON:-python3}"
}

npcink_ai_cloud_require_release_tool_python() {
	local python_command="${1:-$(npcink_ai_cloud_release_tool_python)}"

	if [[ "${python_command}" == */* ]]; then
		if [ ! -x "${python_command}" ]; then
			echo "[fail] Host release-tool Python is not executable: ${python_command}" >&2
			return 1
		fi
	elif ! command -v "${python_command}" >/dev/null 2>&1; then
		echo "[fail] Host release-tool Python is not available: ${python_command}" >&2
		return 1
	fi

	if ! "${python_command}" -c \
		'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
		echo "[fail] Release-tool Python 3.9 or newer is required: ${python_command}" >&2
		return 1
	fi
}

npcink_ai_cloud_require_host_release_tool_python() {
	local python_command="${1:-$(npcink_ai_cloud_release_tool_python)}"

	if ! npcink_ai_cloud_require_release_tool_python "${python_command}"; then
		return 1
	fi
	if ! "${python_command}" -c \
		'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
		echo "[fail] Host release-tool Python 3.11 or newer is required: ${python_command}" >&2
		return 1
	fi
}

npcink_ai_cloud_append_timing_summary() {
	local label="$1"
	local duration_seconds="$2"

	if [ -z "${GITHUB_STEP_SUMMARY:-}" ]; then
		return 0
	fi

	printf '| `%s` | %ss |\n' "${label}" "${duration_seconds}" >> "${GITHUB_STEP_SUMMARY}"
}

npcink_ai_cloud_start_timing_summary() {
	local title="${1:-Deploy Timing}"

	if [ -z "${GITHUB_STEP_SUMMARY:-}" ]; then
		return 0
	fi

	{
		printf '## %s\n\n' "${title}"
		printf '| Step | Duration |\n'
		printf '| --- | ---: |\n'
	} >> "${GITHUB_STEP_SUMMARY}"
}

npcink_ai_cloud_run_timed() {
	local label="$1"
	shift
	local started_at
	local completed_at
	local duration_seconds
	local status
	local restore_errexit=0

	case "$-" in
		*e*)
			restore_errexit=1
			;;
	esac

	started_at="$(date +%s)"
	echo "[timing] ${label}: start"
	set +e
	"$@"
	status=$?
	if [ "${restore_errexit}" -eq 1 ]; then
		set -e
	else
		set +e
	fi
	completed_at="$(date +%s)"
	duration_seconds=$((completed_at - started_at))
	if [ "${status}" -eq 0 ]; then
		echo "[timing] ${label}: ${duration_seconds}s"
	else
		echo "[timing] ${label}: ${duration_seconds}s (failed: ${status})" >&2
	fi
	npcink_ai_cloud_append_timing_summary "${label}" "${duration_seconds}"
	return "${status}"
}

npcink_ai_cloud_normalize_path() {
	local root_dir="$1"
	local path="$2"

	if [[ "${path}" = /* ]]; then
		printf '%s' "${path}"
	else
		printf '%s/%s' "${root_dir%/}" "${path#./}"
	fi
}

npcink_ai_cloud_release_state_dir() {
	local root_dir="$1"
	local resolved_root=""
	local release_name=""

	resolved_root="$(cd "${root_dir}" 2>/dev/null && pwd -P)" || return 1
	release_name="$(basename "${resolved_root}")"
	if [[ ! "${release_name}" =~ ^release-[A-Za-z0-9._-]+$ ]]; then
		return 1
	fi
	printf '%s/.release-state/%s' "$(dirname "${resolved_root}")" "${release_name}"
}

npcink_ai_cloud_managed_root_for_release() {
	local release_root="$1"
	local require_current="${2:-1}"
	local resolved_root=""
	local release_name=""
	local managed_root=""
	local current_link=""

	resolved_root="$(cd "${release_root}" 2>/dev/null && pwd -P)" || {
		echo "[fail] Managed release root could not be resolved." >&2
		return 1
	}
	release_name="${resolved_root##*/}"
	if [[ ! "${release_name}" =~ ^release-[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
		echo "[fail] Expected a direct managed release-* directory." >&2
		return 1
	fi
	managed_root="$(cd "${resolved_root}/.." 2>/dev/null && pwd -P)" || return 1
	if [ "${resolved_root}" != "${managed_root}/${release_name}" ]; then
		echo "[fail] Managed release layout is not canonical." >&2
		return 1
	fi
	case "${require_current}" in
		0) ;;
		1)
			current_link="${managed_root}/current"
			if [ ! -L "${current_link}" ] || \
				[ "$(readlink -f "${current_link}" 2>/dev/null || true)" != "${resolved_root}" ]; then
				echo "[fail] Helper must run from the active managed release." >&2
				return 1
			fi
			;;
		*)
			echo "[fail] Managed release current-link policy is invalid." >&2
			return 1
			;;
	esac
	printf '%s' "${managed_root}"
}

npcink_ai_cloud_start_install_lock_broker() {
	local release_root="$1"
	local lock_path="$2"
	local create_mode="${3:-0}"
	local release_tool_python=""
	local helper=""
	local proof=""
	local broker_dir=""
	local old_umask=""
	local -a create_arg=()
	local -a initial_command=()
	shift 3
	initial_command=("$@")

	if [ -n "${NPCINK_CLOUD_INSTALL_LOCK_BROKER_PID_VALUE:-}" ]; then
		echo "[fail] Setup/deploy lock broker is already active." >&2
		return 1
	fi
	release_tool_python="$(npcink_ai_cloud_release_tool_python)"
	npcink_ai_cloud_require_host_release_tool_python "${release_tool_python}" || return 1
	helper="${release_root}/deploy/install-lock.py"
	[ -f "${helper}" ] && [ ! -L "${helper}" ] || {
		echo "[fail] Setup/deploy lock helper is unavailable from the exact release." >&2
		return 1
	}
	case "${create_mode}" in
		0) ;;
		1) create_arg=(--create) ;;
		*)
			echo "[fail] Setup/deploy lock creation policy is invalid." >&2
			return 1
			;;
	esac

	old_umask="$(umask)"
	umask 077
	broker_dir="$(mktemp -d "${TMPDIR:-/tmp}/npcink-install-lock.XXXXXX")" || {
		umask "${old_umask}"
		return 1
	}
	umask "${old_umask}"
	if [ -L "${broker_dir}" ] || [ ! -d "${broker_dir}" ] || \
		[ ! -O "${broker_dir}" ] || \
		[ "$(npcink_ai_cloud_mode_of "${broker_dir}" 2>/dev/null || true)" != "700" ]; then
		rm -rf -- "${broker_dir}" >/dev/null 2>&1 || true
		echo "[fail] Setup/deploy lock broker control directory is unsafe." >&2
		return 1
	fi
	mkfifo "${broker_dir}/control" "${broker_dir}/status" || {
		rm -rf -- "${broker_dir}" >/dev/null 2>&1 || true
		return 1
	}
	chmod 0600 "${broker_dir}/control" "${broker_dir}/status"
	exec 6>&1
	"${release_tool_python}" "${helper}" \
		--path "${lock_path}" --uid 999 --gid 999 --mode 0600 \
		"${create_arg[@]}" --command-output-fd 6 hold -- \
		"${initial_command[@]}" \
		<"${broker_dir}/control" >"${broker_dir}/status" &
	NPCINK_CLOUD_INSTALL_LOCK_BROKER_PID_VALUE="$!"
	NPCINK_CLOUD_INSTALL_LOCK_BROKER_DIR="${broker_dir}"
	exec 6>&-
	# FD 7 is the broker lifetime capability. Closing it is the only normal
	# release path; the Python process owns the validated lock descriptor.
	exec 7>"${broker_dir}/control"
	if ! IFS= read -r proof <"${broker_dir}/status" || \
		[ "${proof}" != "install_lock_acquired.v1" ]; then
		exec 7>&- 2>/dev/null || true
		wait "${NPCINK_CLOUD_INSTALL_LOCK_BROKER_PID_VALUE}" 2>/dev/null || true
		rm -f -- "${broker_dir}/control" "${broker_dir}/status" >/dev/null 2>&1 || true
		rmdir -- "${broker_dir}" >/dev/null 2>&1 || true
		unset NPCINK_CLOUD_INSTALL_LOCK_BROKER_PID_VALUE \
			NPCINK_CLOUD_INSTALL_LOCK_BROKER_DIR
		echo "[fail] Setup/deploy lock could not be safely acquired." >&2
		return 1
	fi
	rm -f -- "${broker_dir}/status"
}

npcink_ai_cloud_stop_install_lock_broker() {
	local status=0
	if [ -z "${NPCINK_CLOUD_INSTALL_LOCK_BROKER_PID_VALUE:-}" ]; then
		return 0
	fi
	exec 7>&- 2>/dev/null || status=1
	wait "${NPCINK_CLOUD_INSTALL_LOCK_BROKER_PID_VALUE}" 2>/dev/null || status=1
	if [ -n "${NPCINK_CLOUD_INSTALL_LOCK_BROKER_DIR:-}" ]; then
		rm -f -- "${NPCINK_CLOUD_INSTALL_LOCK_BROKER_DIR}/control" \
			"${NPCINK_CLOUD_INSTALL_LOCK_BROKER_DIR}/status" >/dev/null 2>&1 || status=1
		rmdir -- "${NPCINK_CLOUD_INSTALL_LOCK_BROKER_DIR}" >/dev/null 2>&1 || status=1
	fi
	unset NPCINK_CLOUD_INSTALL_LOCK_BROKER_PID_VALUE \
		NPCINK_CLOUD_INSTALL_LOCK_BROKER_DIR
	return "${status}"
}

npcink_ai_cloud_release_state_env_file() {
	local state_dir=""
	state_dir="$(npcink_ai_cloud_release_state_dir "$1")" || return 1
	printf '%s/env.deploy' "${state_dir}"
}

npcink_ai_cloud_read_env_value() {
	local env_file="$1"
	local requested_key="$2"

	[ -f "${env_file}" ] || return 1
	awk -v requested_key="${requested_key}" '
		$0 ~ "^[[:space:]]*" requested_key "[[:space:]]*=" {
			value = $0
			sub("^[[:space:]]*" requested_key "[[:space:]]*=[[:space:]]*", "", value)
			sub("[[:space:]]+$", "", value)
			if (value ~ /^\047.*\047$/ || value ~ /^\".*\"$/) {
				value = substr(value, 2, length(value) - 2)
			}
			found = value
		}
		END {
			if (found != "") {
				print found
			}
		}
	' "${env_file}"
}

npcink_ai_cloud_compose_project_name_from_env() {
	local env_file="$1"
	local project_name=""

	project_name="$(npcink_ai_cloud_read_env_value "${env_file}" NPCINK_CLOUD_COMPOSE_PROJECT_NAME || true)"
	if [ -z "${project_name}" ]; then
		project_name="$(npcink_ai_cloud_read_env_value "${env_file}" COMPOSE_PROJECT_NAME || true)"
	fi
	project_name="${project_name:-npcink-ai-cloud}"
	if [[ ! "${project_name}" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
		echo "[fail] Invalid Compose project name in ${env_file}: ${project_name}" >&2
		return 1
	fi
	printf '%s' "${project_name}"
}

npcink_ai_cloud_require_env_value() {
	local key="$1"
	local description="${2:-${key}}"
	local value="${!key:-}"
	if [ -z "${value}" ]; then
		echo "[fail] ${description} is required" >&2
		exit 1
	fi
}

npcink_ai_cloud_require_internal_token() {
	npcink_ai_cloud_require_env_value \
		"NPCINK_CLOUD_INTERNAL_AUTH_TOKEN" \
		"NPCINK_CLOUD_INTERNAL_AUTH_TOKEN for internal-only perimeter checks"
}

npcink_ai_cloud_read_internal_token_projection() {
	local root_dir="$1"
	local config_dir="${NPCINK_CLOUD_CONFIG_DIR_HOST:-$(dirname "${root_dir}")/shared/config}"
	local token_file="${config_dir}/frontend/internal-auth-token"
	local release_tool_python=""
	release_tool_python="$(npcink_ai_cloud_release_tool_python)"
	npcink_ai_cloud_require_release_tool_python "${release_tool_python}" || return 1
	"${release_tool_python}" - "${token_file}" <<'PY'
import os
import stat
import sys

path = sys.argv[1]
metadata = os.lstat(path)
if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
    raise SystemExit("[fail] Internal-token projection must be a regular non-symlink file.")
if stat.S_IMODE(metadata.st_mode) != 0o640 or (metadata.st_uid, metadata.st_gid) != (999, 999):
    raise SystemExit("[fail] Internal-token projection ownership or mode is unsafe.")
descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
    value = stream.read().strip()
if len(value.encode("utf-8")) < 32 or "\n" in value or "\r" in value:
    raise SystemExit("[fail] Internal-token projection payload is invalid.")
print(value)
PY
}

npcink_ai_cloud_resolve_env_file() {
	local root_dir="$1"
	local env_file="${NPCINK_CLOUD_ENV_FILE:-}"
	local state_env_file=""

	if [ -n "${env_file}" ]; then
		npcink_ai_cloud_normalize_path "${root_dir}" "${env_file}"
		return 0
	fi
	state_env_file="$(npcink_ai_cloud_release_state_env_file "${root_dir}" 2>/dev/null || true)"
	if [ -n "${state_env_file}" ] && [ -f "${state_env_file}" ]; then
		env_file="${state_env_file}"
	elif [ -f "${root_dir}/.env.deploy" ]; then
		env_file="${root_dir}/.env.deploy"
	fi
	printf '%s' "${env_file}"
}

npcink_ai_cloud_env_key_is_runtime_config() {
	local key="$1"
	case "${key}" in
		NPCINK_CLOUD_*|POSTGRES_DB|POSTGRES_USER|POSTGRES_PASSWORD|COMPOSE_PROJECT_NAME) ;;
		*) return 1 ;;
	esac
	case "${key}" in
		NPCINK_CLOUD_DEPLOY_*|NPCINK_CLOUD_DEPLOY_LOCK_OWNER|\
		NPCINK_CLOUD_RELEASE_TOOL_PYTHON|NPCINK_CLOUD_COMPOSE_FILE|\
		NPCINK_CLOUD_ENV_FILE|NPCINK_CLOUD_BACKEND_ENV_FILE|\
		NPCINK_CLOUD_ADMIN_KEY|NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN|\
		NPCINK_CLOUD_LOAD_MODE|NPCINK_CLOUD_ROLLBACK_IMAGE_MAP|\
		NPCINK_CLOUD_ROLLBACK_TAG_SUFFIX|\
		NPCINK_CLOUD_TARGET_DAEMON_MAP|NPCINK_CLOUD_REFRESH_PROVIDERS_ONE_OFF|\
		NPCINK_CLOUD_API_WORKERS|NPCINK_CLOUD_SKIP_FRONTEND_IMAGE|NPCINK_CLOUD_SECRET|\
		NPCINK_CLOUD_*_RELEASE_IMAGE)
			return 1
			;;
	esac
	return 0
}

npcink_ai_cloud_env_key_is_shell_importable() {
	local key="$1"
	# Keep the protected dotenv file as the complete container-runtime input,
	# but import only the values that an existing host helper reads directly.
	# New NPCINK_CLOUD_* settings therefore remain container-only until this
	# allowlist is intentionally reviewed, instead of silently becoming root
	# shell controls through the broad runtime namespace.
	case "${key}" in
		COMPOSE_PROJECT_NAME|\
		NPCINK_CLOUD_ABILITY_NAME|\
		NPCINK_CLOUD_ALPHA_KEY_ID|\
		NPCINK_CLOUD_ALPHA_SITE_ID|\
		NPCINK_CLOUD_ALPHA_SITE_SECRET|\
		NPCINK_CLOUD_BASE_URL|\
		NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST|\
		NPCINK_CLOUD_CERTIFICATE_RENEWAL_CERT_PATH|\
		NPCINK_CLOUD_CERTIFICATE_RENEWAL_EVIDENCE_PATH|\
		NPCINK_CLOUD_CERTIFICATE_RENEWAL_HOOK_PATH|\
		NPCINK_CLOUD_CERTIFICATE_RENEWAL_TIMER|\
		NPCINK_CLOUD_CHANNEL|\
		NPCINK_CLOUD_COMPOSE_PROJECT_NAME|\
		NPCINK_CLOUD_DEV_PORTAL_SITE_ID|\
		NPCINK_CLOUD_DOMAIN_NAME|\
		NPCINK_CLOUD_EXECUTION_KIND|\
		NPCINK_CLOUD_EXPECTED_INSTANCE_ID|\
		NPCINK_CLOUD_EXPECTED_MODEL_ID|\
		NPCINK_CLOUD_EXPECTED_PROVIDER_ID|\
		NPCINK_CLOUD_EXTERNAL_EDGE_READY|\
		NPCINK_CLOUD_HEALTH_FORWARDED_PROTO|\
		NPCINK_CLOUD_HEALTH_HOST_HEADER|\
		NPCINK_CLOUD_IDEMPOTENCY_SUFFIX|\
		NPCINK_CLOUD_INTERNAL_AUTH_TOKEN|\
		NPCINK_CLOUD_KEY_ID|\
		NPCINK_CLOUD_LOCAL_ALPHA_SMOKE_EVIDENCE_DIR|\
		NPCINK_CLOUD_LOCAL_ALPHA_SMOKE_MEMBER_EMAIL|\
		NPCINK_CLOUD_LOCAL_ALPHA_SMOKE_SUFFIX|\
		NPCINK_CLOUD_MEMBER_EMAIL|\
		NPCINK_CLOUD_MEMBER_REF|\
		NPCINK_CLOUD_OPERATIONAL_READY_INTERNAL|\
		NPCINK_CLOUD_OPERATIONAL_READY_WAIT_ATTEMPTS|\
		NPCINK_CLOUD_OPERATIONAL_READY_WAIT_DELAY_SECONDS|\
		NPCINK_CLOUD_PORT|\
		NPCINK_CLOUD_PORTAL_COOKIE_JAR|\
		NPCINK_CLOUD_PORTAL_LOGIN_CODE|\
		NPCINK_CLOUD_PRODUCTION_PERF_ANALYZE|\
		NPCINK_CLOUD_PRODUCTION_PERF_REQUIRE_PLAN_INDEX_USE|\
		NPCINK_CLOUD_PRODUCTION_PERF_SKIP_HTTP|\
		NPCINK_CLOUD_PROFILE_ID|\
		NPCINK_CLOUD_PROMPT_TEXT|\
		NPCINK_CLOUD_READY_ORIGIN|\
		NPCINK_CLOUD_RELEASE_KEY_ID|\
		NPCINK_CLOUD_RELEASE_KEY_SECRET|\
		NPCINK_CLOUD_RELEASE_MEMBER_EMAIL|\
		NPCINK_CLOUD_RELEASE_SITE_ID|\
		NPCINK_CLOUD_ROTATION_CHECK_EMAIL|\
		NPCINK_CLOUD_SCOPES|\
		NPCINK_CLOUD_SITE_ID|\
		NPCINK_CLOUD_SITE_KEY_SECRET|\
		NPCINK_CLOUD_SITE_URL|\
		NPCINK_CLOUD_SKIP_TERMS_CHECKS|\
		NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST|\
		NPCINK_CLOUD_WORDPRESS_ADMIN_PASSWORD|\
		NPCINK_CLOUD_WORDPRESS_ADMIN_USER|\
		NPCINK_CLOUD_WORKER_CUTOFF|\
		NPCINK_CLOUD_WORKER_READINESS_ATTEMPTS|\
		NPCINK_CLOUD_WORKER_READINESS_SLEEP_SECONDS|\
		NPCINK_CLOUD_WORKER_STABILITY_SECONDS|\
		NPCINK_CLOUD_WP_CRON_COMMENT_TAG|\
		NPCINK_CLOUD_WP_CRON_CONNECT_TIMEOUT_SECONDS|\
		NPCINK_CLOUD_WP_CRON_CURL_BIN|\
		NPCINK_CLOUD_WP_CRON_CURL_TIMEOUT_SECONDS|\
		NPCINK_CLOUD_WP_CRON_DOING_WP_CRON|\
		NPCINK_CLOUD_WP_CRON_FLOCK_BIN|\
		NPCINK_CLOUD_WP_CRON_LOCK_FILE|\
		NPCINK_CLOUD_WP_CRON_SCHEDULE|\
		NPCINK_CLOUD_WP_CRON_SITE_BASE_URL|\
		NPCINK_CLOUD_WP_CRON_USER_AGENT)
			return 0
			;;
		*)
			return 1
			;;
	esac
}

npcink_ai_cloud_load_env_file() {
	local root_dir="$1"
	local env_file
	env_file="$(npcink_ai_cloud_resolve_env_file "${root_dir}")"
	if [ -z "${env_file}" ] || [ ! -f "${env_file}" ]; then
		return 0
	fi
	export NPCINK_CLOUD_ENV_FILE="${env_file}"
	if [ -z "${NPCINK_CLOUD_BACKEND_ENV_FILE:-}" ]; then
		export NPCINK_CLOUD_BACKEND_ENV_FILE="${env_file}"
	fi
	local line=""
	local key=""
	local value=""
	while IFS= read -r line || [ -n "${line}" ]; do
		case "${line}" in
			'' | '#'*)
				continue
				;;
		esac
		if [[ "${line}" != *=* ]]; then
			echo "[fail] Invalid dotenv assignment in ${env_file}." >&2
			return 1
		fi
		key="${line%%=*}"
		if [[ ! "${key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
			echo "[fail] Invalid dotenv key in ${env_file}." >&2
			return 1
		fi
		if ! npcink_ai_cloud_env_key_is_runtime_config "${key}"; then
			echo "[fail] Dotenv key is not an allowed runtime setting: ${key}" >&2
			return 1
		fi
		value="${line#*=}"
		if [[ "${value}" == \'*\' ]] || [[ "${value}" == \"*\" ]]; then
			value="${value:1:${#value}-2}"
		elif [[ "${value}" == \'* ]] || [[ "${value}" == *\' ]] || \
			[[ "${value}" == \"* ]] || [[ "${value}" == *\" ]]; then
			echo "[fail] Unbalanced dotenv quoting in ${env_file}." >&2
			return 1
		fi
		if ! npcink_ai_cloud_env_key_is_shell_importable "${key}"; then
			continue
		fi
		if [ -n "${!key+x}" ]; then
			continue
		fi
		# Assign the parsed bytes literally. Never eval dotenv content: production
		# values may legitimately contain shell metacharacters, and none may turn
		# into code when a root-owned release helper loads the file.
		printf -v "${key}" '%s' "${value}" || return 1
		export "${key}"
	done < "${env_file}"
}

npcink_ai_cloud_expected_rollback_image_id() {
	local rollback_image_map="$1"
	local target_reference="$2"
	local mapped_reference=""
	local _rollback_reference=""
	local mapped_image_id=""
	local expected_image_id=""
	local matches=0

	[ -f "${rollback_image_map}" ] || return 1
	[ ! -L "${rollback_image_map}" ] || return 1
	while IFS=$'\t' read -r mapped_reference _rollback_reference mapped_image_id; do
		[ "${mapped_reference}" = "${target_reference}" ] || continue
		matches=$((matches + 1))
		expected_image_id="${mapped_image_id}"
	done < "${rollback_image_map}"
	[ "${matches}" -eq 1 ] || return 1
	[[ "${expected_image_id}" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
	printf '%s' "${expected_image_id}"
}

npcink_ai_cloud_compose_service_image_reference() {
	local host_python="$1"
	local service_name="$2"
	"${host_python}" -c '
import json
import sys

service_name = sys.argv[1]
payload = json.load(sys.stdin)
services = payload.get("services")
if not isinstance(services, dict):
    raise SystemExit(1)
service = services.get(service_name)
if not isinstance(service, dict):
    raise SystemExit(1)
image = service.get("image")
if not isinstance(image, str) or not image.strip() or image != image.strip():
    raise SystemExit(1)
print(image)
' "${service_name}"
}

npcink_ai_cloud_assert_container_matches_rollback_image() {
	local rollback_image_map="$1"
	local container_id="$2"
	local service_name="$3"
	local expected_reference="$4"
	local configured_reference=""
	local actual_image_id=""
	local expected_image_id=""

	configured_reference="$(
		docker inspect --format '{{.Config.Image}}' "${container_id}" 2>/dev/null
	)" || {
		echo "[fail] Could not inspect recovered ${service_name} image reference." >&2
		return 1
	}
	if [ "${configured_reference}" != "${expected_reference}" ]; then
		echo "[fail] Recovered ${service_name} container image reference differs from previous Compose." >&2
		return 1
	fi
	actual_image_id="$(
		docker inspect --format '{{.Image}}' "${container_id}" 2>/dev/null
	)" || {
		echo "[fail] Could not inspect recovered ${service_name} image ID." >&2
		return 1
	}
	expected_image_id="$(
		npcink_ai_cloud_expected_rollback_image_id \
			"${rollback_image_map}" "${expected_reference}"
	)" || {
		echo "[fail] Rollback image map has no unique valid prior image for recovered ${service_name}: ${expected_reference}" >&2
		return 1
	}
	if [ "${actual_image_id}" != "${expected_image_id}" ]; then
		echo "[fail] Recovered ${service_name} container does not use its snapshotted rollback image." >&2
		return 1
	fi
}

npcink_ai_cloud_prepare_runtime_compose_environment() {
	local root_dir="$1"
	local compose_file="$2"
	local compose_project_name="$3"
	local release_tool_python=""
	local state_dir=""
	local parsed=""
	local subnet=""
	local gateway=""
	local proxy_ipv4=""
	local nginx_config_path=""
	local line=""
	local parameterized=0

	# Runtime interpolation must never inherit caller-controlled values. A
	# parameterized release is reconstructed only from its protected per-release
	# state, while a legacy Compose file without these markers remains usable.
	unset NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET \
		NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY \
		NPCINK_CLOUD_RUNTIME_PROXY_IPV4 \
		NPCINK_CLOUD_RUNTIME_NGINX_CONFIG_PATH

	if [ ! -e "${compose_file}" ] && [ ! -L "${compose_file}" ]; then
		# Preserve the generic helper's historical delegation for a missing
		# non-runtime Compose path. Formal runtime callers always require the
		# canonical bundled runtime file and must fail before Docker.
		if [ "$(basename "${compose_file}")" != "docker-compose.runtime.yml" ]; then
			return 0
		fi
	fi
	[ -f "${compose_file}" ] && [ ! -L "${compose_file}" ] && [ -O "${compose_file}" ] || {
		echo "[fail] Runtime Compose authority must be an owner-controlled regular file." >&2
		return 1
	}
	while IFS= read -r line || [ -n "${line}" ]; do
		case "${line}" in
			*'NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET'*|\
			*'NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY'*|\
			*'NPCINK_CLOUD_RUNTIME_PROXY_IPV4'*|\
			*'NPCINK_CLOUD_RUNTIME_NGINX_CONFIG_PATH'*)
				parameterized=1
				break
				;;
		esac
	done <"${compose_file}"
	if [ "${parameterized}" -eq 0 ]; then
		return 0
	fi

	root_dir="$(cd "${root_dir}" 2>/dev/null && pwd -P)" || {
		echo "[fail] Parameterized runtime Compose release root could not be resolved." >&2
		return 1
	}
	state_dir="$(npcink_ai_cloud_release_state_dir "${root_dir}")" || {
		echo "[fail] Parameterized runtime Compose requires a managed release root." >&2
		return 1
	}
	release_tool_python="$(npcink_ai_cloud_release_tool_python)"
	npcink_ai_cloud_require_release_tool_python "${release_tool_python}" || return 1

	parsed="$("${release_tool_python}" - \
		"${root_dir}" "${compose_file}" "${state_dir}" "${compose_project_name}" <<'PY'
from __future__ import annotations

import ipaddress
import os
import re
import stat
import sys
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"[fail] {message}")


def read_owned_regular(path: Path, expected_mode=None) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        fail(f"Protected runtime Compose file could not be opened: {path}: {exc}")
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            fail(f"Protected runtime Compose file is not owner-controlled: {path}")
        if expected_mode is not None and stat.S_IMODE(metadata.st_mode) != expected_mode:
            fail(f"Protected runtime Compose file has an unsafe mode: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    try:
        return b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError as exc:
        fail(f"Protected runtime Compose file is not UTF-8: {path}: {exc}")


root = Path(sys.argv[1])
compose = Path(sys.argv[2])
state_dir = Path(sys.argv[3])
expected_project = sys.argv[4]
if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", expected_project):
    fail("Runtime Compose project name is invalid.")
if root != Path(os.path.abspath(root)) or compose != root / "docker-compose.runtime.yml":
    fail("Parameterized runtime Compose must be the canonical bundled runtime file.")

for directory, mode, label in (
    (root.parent / ".release-state", 0o700, "release-state root"),
    (state_dir, 0o700, "per-release state directory"),
):
    try:
        metadata = directory.lstat()
    except OSError as exc:
        fail(f"Runtime Compose {label} is missing: {exc}")
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != mode
    ):
        fail(f"Runtime Compose {label} must be owner-controlled mode {mode:04o}.")
if state_dir != root.parent / ".release-state" / root.name:
    fail("Runtime Compose state does not belong to the requested release.")

compose_text = read_owned_regular(compose)
runtime_markers = {
    "${NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET:-172.28.0.0/24}": 1,
    "${NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY:-172.28.0.1}": 1,
    "${NPCINK_CLOUD_RUNTIME_PROXY_IPV4:-172.28.0.10}": 2,
    "${NPCINK_CLOUD_RUNTIME_NGINX_CONFIG_PATH:-./deploy/nginx.prod.conf}": 1,
}
if any(compose_text.count(marker) != count for marker, count in runtime_markers.items()):
    fail("Parameterized runtime Compose interpolation structure is incomplete or ambiguous.")

state_file = state_dir / "runtime-network.env"
state_text = read_owned_regular(state_file, 0o600)
allowed = {
    "NPCINK_CLOUD_RUNTIME_NETWORK_PROJECT",
    "NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET",
    "NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY",
    "NPCINK_CLOUD_RUNTIME_PROXY_IPV4",
}
values: dict[str, str] = {}
for line in state_text.splitlines():
    if not line or "=" not in line:
        fail("Frozen runtime network state has an invalid assignment.")
    key, value = line.split("=", 1)
    if key not in allowed or key in values or not value:
        fail("Frozen runtime network state has unexpected or duplicate keys.")
    values[key] = value
if set(values) != allowed:
    fail("Frozen runtime network state is incomplete.")
if values["NPCINK_CLOUD_RUNTIME_NETWORK_PROJECT"] != expected_project:
    fail("Frozen runtime network state belongs to another Compose project.")

try:
    network = ipaddress.ip_network(
        values["NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET"], strict=True
    )
    gateway = ipaddress.ip_address(values["NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY"])
    proxy = ipaddress.ip_address(values["NPCINK_CLOUD_RUNTIME_PROXY_IPV4"])
except ValueError as exc:
    fail(f"Frozen runtime network state is invalid: {exc}")
if network.version != 4 or gateway.version != 4 or proxy.version != 4:
    fail("Frozen runtime network state must contain IPv4 values.")
if gateway not in network or proxy not in network:
    fail("Frozen runtime network gateway/proxy is outside the subnet.")
if len({network.network_address, network.broadcast_address, gateway, proxy}) != 4:
    fail("Frozen runtime network gateway/proxy is not a distinct usable host.")

source = root / "deploy" / "nginx.prod.conf"
target = state_dir / "nginx.runtime.conf"
source_text = read_owned_regular(source)
target_text = read_owned_regular(target, 0o600)
default_trust = "    set_real_ip_from 172.28.0.1;"
if source_text.count(default_trust) != 1:
    fail("Bundled NGINX gateway trust anchor is not unique.")
expected_target = source_text.replace(
    default_trust,
    f"    set_real_ip_from {gateway};",
    1,
)
if target_text != expected_target:
    fail("Frozen runtime NGINX config differs from the bundled gateway contract.")
if any(character in str(target) for character in "\r\n\t"):
    fail("Frozen runtime NGINX config path is unsafe.")

print(f"{network.with_prefixlen}\t{gateway}\t{proxy}\t{target}")
PY
	)" || return 1
	IFS=$'\t' read -r subnet gateway proxy_ipv4 nginx_config_path <<<"${parsed}"
	if [ -z "${subnet}" ] || [ -z "${gateway}" ] || [ -z "${proxy_ipv4}" ] || \
		[ -z "${nginx_config_path}" ]; then
		echo "[fail] Protected runtime Compose state could not be parsed." >&2
		return 1
	fi
	export NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET="${subnet}"
	export NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY="${gateway}"
	export NPCINK_CLOUD_RUNTIME_PROXY_IPV4="${proxy_ipv4}"
	export NPCINK_CLOUD_RUNTIME_NGINX_CONFIG_PATH="${nginx_config_path}"
}

npcink_ai_cloud_compose() {
	local root_dir="$1"
	shift

	local compose_file="${NPCINK_CLOUD_COMPOSE_FILE:-${root_dir}/docker-compose.prod.yml}"
	local env_file=""
	local backend_env_file="${NPCINK_CLOUD_BACKEND_ENV_FILE:-}"
	local compose_project_name="${NPCINK_CLOUD_COMPOSE_PROJECT_NAME:-${COMPOSE_PROJECT_NAME:-}}"
	local compose_status=0
	root_dir="$(cd "${root_dir}" 2>/dev/null && pwd -P)" || {
		echo "[fail] Compose release root could not be resolved." >&2
		return 1
	}
	compose_file="$(npcink_ai_cloud_normalize_path "${root_dir}" "${compose_file}")"

	env_file="$(npcink_ai_cloud_resolve_env_file "${root_dir}")"
	if [ -n "${backend_env_file}" ]; then
		backend_env_file="$(npcink_ai_cloud_normalize_path "${root_dir}" "${backend_env_file}")"
	elif [ -n "${env_file}" ]; then
		backend_env_file="${env_file}"
	fi
	if [ -z "${compose_project_name}" ] && [ -n "${env_file}" ]; then
		compose_project_name="$(npcink_ai_cloud_compose_project_name_from_env "${env_file}")"
	fi
	compose_project_name="${compose_project_name:-npcink-ai-cloud}"
	if [[ ! "${compose_project_name}" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
		echo "[fail] Invalid Compose project name: ${compose_project_name}" >&2
		return 1
	fi
	npcink_ai_cloud_prepare_runtime_compose_environment \
		"${root_dir}" "${compose_file}" "${compose_project_name}" || return 1

	if [ -n "${env_file}" ]; then
		COMPOSE_PROJECT_NAME="${compose_project_name}" \
			NPCINK_CLOUD_BACKEND_ENV_FILE="${backend_env_file}" \
			docker compose --env-file "${env_file}" -f "${compose_file}" "$@" || \
			compose_status=$?
		return "${compose_status}"
	fi

	COMPOSE_PROJECT_NAME="${compose_project_name}" \
		NPCINK_CLOUD_BACKEND_ENV_FILE="${backend_env_file}" \
		docker compose -f "${compose_file}" "$@" || compose_status=$?
	return "${compose_status}"
}

npcink_ai_cloud_pin_compose_service_image() {
	local service="$1"
	local image_id="$2"
	[[ "${image_id}" =~ ^sha256:[0-9a-f]{64}$ ]] || {
		echo "[fail] Compose service image pin is not a target-daemon image ID." >&2
		return 1
	}
	case "${service}" in
		postgres) export NPCINK_CLOUD_POSTGRES_RELEASE_IMAGE="${image_id}" ;;
		redis) export NPCINK_CLOUD_REDIS_RELEASE_IMAGE="${image_id}" ;;
		api) export NPCINK_CLOUD_API_RELEASE_IMAGE="${image_id}" ;;
		frontend) export NPCINK_CLOUD_FRONTEND_RELEASE_IMAGE="${image_id}" ;;
		worker) export NPCINK_CLOUD_WORKER_RELEASE_IMAGE="${image_id}" ;;
		callback-worker) export NPCINK_CLOUD_CALLBACK_WORKER_RELEASE_IMAGE="${image_id}" ;;
		ops-worker) export NPCINK_CLOUD_OPS_WORKER_RELEASE_IMAGE="${image_id}" ;;
		proxy) export NPCINK_CLOUD_PROXY_RELEASE_IMAGE="${image_id}" ;;
		*)
			echo "[fail] Unknown Compose service image pin target: ${service}" >&2
			return 1
			;;
	esac
}

npcink_ai_cloud_compose_run_with_image_proof() {
	local root_dir="$1"
	local service="$2"
	local expected_reference="$3"
	local expected_daemon_id="$4"
	shift 4

	local requested_compose_file=""
	local resolved_root_dir=""
	local resolved_compose_file=""
	local exec_env_name=""
	local exec_env_names_seen=":"
	local exec_env_args=()
	local observed_image_id=""
	local observed_reference_id=""
	local observed_created_state=""
	local resolved_compose_image=""
	local release_tool_python=""
	local proof_service="release-one-off"
	local container_ids=""
	local container_count=0
	local run_status=0
	local proof_failed=0
	local cleanup_failed=0
	local container_created=0
	local cleanup_armed=0
	local stdin_cleanup_armed=0
	local stdin_capture_failed=0
	local stdin_dir=""
	local stdin_path=""
	local payload_pid=""
	local container_name=""
	local one_off_lock_dir=""
	local deploy_lock_dir=""
	local deploy_lock_owner_file=""
	local configured_deploy_lock_owner="${NPCINK_CLOUD_DEPLOY_LOCK_OWNER:-}"
	local observed_deploy_lock_owner=""
	local one_off_compose_project_name=""
	local one_off_env_file=""
	local preexisting_compose_ids=""
	local preexisting_label_ids=""
	local one_off_lock_armed=0
	local saved_hup_trap=""
	local saved_int_trap=""
	local saved_term_trap=""

	while [ "$#" -gt 0 ] && [ "$1" = "--exec-env" ]; do
		[ "$#" -ge 2 ] || {
			echo "[fail] One-off exec environment option requires a variable name." >&2
			return 1
		}
		exec_env_name="$2"
		if [[ ! "${exec_env_name}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
			echo "[fail] Invalid one-off exec environment variable name." >&2
			return 1
		fi
		case "${exec_env_names_seen}" in
			*":${exec_env_name}:"*)
				echo "[fail] Duplicate one-off exec environment variable name." >&2
				return 1
				;;
		esac
		if [ -z "${!exec_env_name+x}" ]; then
			echo "[fail] One-off exec environment variable is not set: ${exec_env_name}" >&2
			return 1
		fi
		exec_env_names_seen="${exec_env_names_seen}${exec_env_name}:"
		exec_env_args+=(--env "${exec_env_name}")
		shift 2
	done
	if [ "$#" -gt 0 ] && [ "$1" = "--" ]; then
		shift
	elif [ "${#exec_env_args[@]}" -gt 0 ]; then
		echo "[fail] One-off exec environment options require a payload delimiter." >&2
		return 1
	fi
	[ "$#" -gt 0 ] || {
		echo "[fail] One-off command payload is empty." >&2
		return 1
	}

	resolved_root_dir="$(cd "${root_dir}" 2>/dev/null && pwd -P)" || {
		echo "[fail] One-off release root could not be resolved." >&2
		return 1
	}
	requested_compose_file="${NPCINK_CLOUD_COMPOSE_FILE:-${resolved_root_dir}/docker-compose.prod.yml}"
	if [[ "${requested_compose_file}" != /* ]]; then
		requested_compose_file="${resolved_root_dir}/${requested_compose_file#./}"
	fi
	if [ ! -f "${requested_compose_file}" ] || [ -L "${requested_compose_file}" ]; then
		echo "[fail] One-off Compose file must be a regular non-symlink release file." >&2
		return 1
	fi
	resolved_compose_file="$(
		cd "$(dirname "${requested_compose_file}")" 2>/dev/null &&
			printf '%s/%s' "$(pwd -P)" "$(basename "${requested_compose_file}")"
	)" || {
		echo "[fail] One-off Compose file could not be resolved." >&2
		return 1
	}
	case "${resolved_compose_file}" in
		"${resolved_root_dir}/docker-compose.prod.yml"|"${resolved_root_dir}/docker-compose.runtime.yml") ;;
		*)
			echo "[fail] One-off execution requires a canonical bundled Compose file." >&2
			return 1
			;;
	esac
	root_dir="${resolved_root_dir}"
	local NPCINK_CLOUD_COMPOSE_FILE="${resolved_compose_file}"
	export NPCINK_CLOUD_COMPOSE_FILE
	saved_hup_trap="$(trap -p HUP || true)"
	saved_int_trap="$(trap -p INT || true)"
	saved_term_trap="$(trap -p TERM || true)"

	one_off_restore_signal_traps() {
		trap - HUP INT TERM
		[ -z "${saved_hup_trap}" ] || eval "${saved_hup_trap}"
		[ -z "${saved_int_trap}" ] || eval "${saved_int_trap}"
		[ -z "${saved_term_trap}" ] || eval "${saved_term_trap}"
	}

	one_off_remove_container() {
		local attempt=0
		local captured_remaining=""
		local compose_remaining=""
		local labelled_remaining=""
		[ "${cleanup_armed}" -eq 1 ] || return 0
		while [ "${attempt}" -lt 2 ]; do
			if [ -n "${container_name}" ]; then
				docker rm -f "${container_name}" >/dev/null 2>&1 || true
			fi
			npcink_ai_cloud_compose "${root_dir}" rm -f -s \
				"${proof_service}" >/dev/null 2>&1 || true
			if [ -n "${container_name}" ]; then
				captured_remaining="$(
					docker container ls -aq --no-trunc \
						--filter "id=${container_name}" 2>/dev/null
				)" || captured_remaining="__query_failed__"
			else
				captured_remaining=""
			fi
			compose_remaining="$(
				npcink_ai_cloud_compose "${root_dir}" ps --all -q \
					"${proof_service}" 2>/dev/null
			)" || compose_remaining="__query_failed__"
			labelled_remaining="$(
				docker container ls -aq --no-trunc \
					--filter "label=com.docker.compose.service=${proof_service}" 2>/dev/null
			)" || labelled_remaining="__query_failed__"
			if [ -z "${captured_remaining}" ] && \
				[ -z "${compose_remaining}" ] && \
				[ -z "${labelled_remaining}" ]; then
				cleanup_armed=0
				return 0
			fi
			attempt=$((attempt + 1))
			sleep 1
		done
		return 1
	}
	one_off_remove_stdin() {
		local failed=0
		[ "${stdin_cleanup_armed}" -eq 1 ] || return 0
		if [ -n "${stdin_path}" ]; then
			rm -f -- "${stdin_path}" || failed=1
			if [ -e "${stdin_path}" ] || [ -L "${stdin_path}" ]; then
				failed=1
			fi
		fi
		if [ -n "${stdin_dir}" ]; then
			rmdir -- "${stdin_dir}" >/dev/null 2>&1 || failed=1
			if [ -e "${stdin_dir}" ] || [ -L "${stdin_dir}" ]; then
				failed=1
			fi
		fi
		if [ "${failed}" -eq 0 ]; then
			stdin_cleanup_armed=0
		fi
		return "${failed}"
	}
	one_off_remove_lock() {
		[ "${one_off_lock_armed}" -eq 1 ] || return 0
		if ! rmdir -- "${one_off_lock_dir}" >/dev/null 2>&1 || \
			[ -e "${one_off_lock_dir}" ] || [ -L "${one_off_lock_dir}" ]; then
			return 1
		fi
		one_off_lock_armed=0
	}
	one_off_mode_of() {
		local mode=""
		if mode="$(stat -c '%a' -- "$1" 2>/dev/null)"; then
			:
		elif mode="$(stat -f '%Lp' "$1" 2>/dev/null)"; then
			:
		else
			return 1
		fi
		printf '%s' "${mode}"
	}
	one_off_deploy_lock_authorized() {
		observed_deploy_lock_owner=""
		if [ -e "${deploy_lock_dir}" ] || [ -L "${deploy_lock_dir}" ]; then
			if [ ! -d "${deploy_lock_dir}" ] || [ -L "${deploy_lock_dir}" ] || \
				[ ! -O "${deploy_lock_dir}" ] || \
				[ "$(one_off_mode_of "${deploy_lock_dir}" 2>/dev/null || true)" != "700" ] || \
				[[ ! "${configured_deploy_lock_owner}" =~ ^[0-9a-f]{64}$ ]] || \
				[ ! -f "${deploy_lock_owner_file}" ] || [ -L "${deploy_lock_owner_file}" ] || \
				[ ! -O "${deploy_lock_owner_file}" ] || \
				[ "$(one_off_mode_of "${deploy_lock_owner_file}" 2>/dev/null || true)" != "600" ]; then
				echo "[fail] Governed one-off execution is blocked by an unowned deployment lock." >&2
				return 1
			fi
			IFS= read -r observed_deploy_lock_owner <"${deploy_lock_owner_file}" || return 1
			if [ "${observed_deploy_lock_owner}" != "${configured_deploy_lock_owner}" ]; then
				echo "[fail] Governed one-off deployment-lock ownership proof failed." >&2
				return 1
			fi
		elif [ -n "${configured_deploy_lock_owner}" ]; then
			echo "[fail] Governed one-off deployment-lock owner is stale." >&2
			return 1
		fi
	}
	one_off_assert_preexisting_container_absent() {
		preexisting_compose_ids="$(
			npcink_ai_cloud_compose "${root_dir}" ps --all -q \
				"${proof_service}" 2>/dev/null
		)" || {
			echo "[fail] Compose could not prove pre-existing one-off containers absent." >&2
			return 1
		}
		preexisting_label_ids="$(
			docker container ls -aq --no-trunc \
				--filter "label=com.docker.compose.service=${proof_service}" 2>/dev/null
		)" || {
			echo "[fail] Docker could not prove pre-existing one-off containers absent." >&2
			return 1
		}
		if [ -n "${preexisting_compose_ids}" ] || [ -n "${preexisting_label_ids}" ]; then
			echo "[fail] A pre-existing governed one-off container requires operator recovery." >&2
			return 1
		fi
	}
	one_off_acquire_lock() {
		local resolved_root=""
		local state_root=""
		resolved_root="$(cd "${root_dir}" && pwd -P)" || return 1
		state_root="$(dirname "${resolved_root}")/.release-state"
		if [ ! -d "${state_root}" ] || [ -L "${state_root}" ] || \
			[ ! -O "${state_root}" ] || \
			[ "$(one_off_mode_of "${state_root}" 2>/dev/null || true)" != "700" ]; then
			echo "[fail] Global release state is missing or unsafe for one-off locking." >&2
			return 1
		fi
		deploy_lock_dir="$(dirname "${state_root}")/.deploy-lock"
		deploy_lock_owner_file="${deploy_lock_dir}/one-off-owner"
		one_off_lock_dir="${state_root}/.release-one-off.lock"
		# Acquire the one-off side of the two-lock handshake before observing the
		# deployment lock. A deployment acquires those locks in the opposite
		# order, so either participant must observe and reject the other.
		if ! (umask 077; mkdir -- "${one_off_lock_dir}"); then
			echo "[fail] Another governed release one-off is already active." >&2
			return 1
		fi
		one_off_lock_armed=1
		if ! chmod 0700 "${one_off_lock_dir}" || \
			[ ! -d "${one_off_lock_dir}" ] || [ -L "${one_off_lock_dir}" ] || \
			[ ! -O "${one_off_lock_dir}" ] || \
			[ "$(one_off_mode_of "${one_off_lock_dir}" 2>/dev/null || true)" != "700" ]; then
			echo "[fail] Governed release one-off lock is unsafe." >&2
			return 1
		fi
		if ! one_off_deploy_lock_authorized; then
			if ! one_off_remove_lock; then
				echo "[fail] One-off lock cleanup failed after deployment-lock rejection." >&2
			fi
			return 1
		fi
		one_off_compose_project_name="${NPCINK_CLOUD_COMPOSE_PROJECT_NAME:-${COMPOSE_PROJECT_NAME:-}}"
		if [ -z "${one_off_compose_project_name}" ]; then
			one_off_env_file="$(npcink_ai_cloud_resolve_env_file "${root_dir}")"
			if [ -n "${one_off_env_file}" ]; then
				one_off_compose_project_name="$(
					npcink_ai_cloud_compose_project_name_from_env "${one_off_env_file}"
				)" || return 1
			fi
		fi
		one_off_compose_project_name="${one_off_compose_project_name:-npcink-ai-cloud}"
		if [[ ! "${one_off_compose_project_name}" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
			echo "[fail] Governed one-off Compose project name is invalid." >&2
			return 1
		fi
		if ! one_off_assert_preexisting_container_absent; then
			# The lock is now recovery evidence. Do not let the caller's generic
			# acquisition cleanup erase it while an orphan/query ambiguity remains.
			one_off_lock_armed=0
			echo "[fail] Governed release one-off lock retained for operator recovery." >&2
			return 1
		fi
	}
	one_off_cleanup() {
		local failed=0
		one_off_remove_container || failed=1
		one_off_remove_stdin || failed=1
		# Retain the cross-release lock whenever container or protected-stdin
		# cleanup is incomplete. A later helper must not race or erase evidence.
		if [ "${failed}" -eq 0 ]; then
			one_off_remove_lock || failed=1
		fi
		return "${failed}"
	}
	one_off_signal() {
		local status="$1"
		trap - HUP INT TERM
		set +e
		if [ -n "${payload_pid}" ]; then
			kill "${payload_pid}" >/dev/null 2>&1 || true
			wait "${payload_pid}" >/dev/null 2>&1 || true
		fi
		if ! one_off_cleanup; then
			echo "[fail] One-off ${service} proof container could not be removed or protected stdin cleanup failed during signal cleanup." >&2
			status=1
		fi
		exit "${status}"
	}

	if [[ ! "${service}" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
		echo "[fail] Invalid one-off Compose service name." >&2
		return 1
	fi
	if [ "${service}" != "api" ]; then
		echo "[fail] Governed release one-off execution is restricted to the API image." >&2
		return 1
	fi
	if [[ ! "${expected_reference}" =~ ^[A-Za-z0-9._/-]+(:[A-Za-z0-9._-]+)?$ ]]; then
		echo "[fail] Invalid one-off expected image reference." >&2
		return 1
	fi
	if [[ ! "${expected_daemon_id}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
		echo "[fail] Proved target-daemon one-off image ID is invalid." >&2
		return 1
	fi
	if ! npcink_ai_cloud_pin_compose_service_image "${service}" "${expected_daemon_id}"; then
		return 1
	fi
	release_tool_python="$(npcink_ai_cloud_release_tool_python)"
	npcink_ai_cloud_require_release_tool_python "${release_tool_python}" || return 1
	resolved_compose_image="$(
		npcink_ai_cloud_compose "${root_dir}" config --format json "${proof_service}" 2>/dev/null |
			"${release_tool_python}" -c \
			'import json,sys; service=sys.argv[1]; print(json.load(sys.stdin)["services"][service]["image"])' \
			"${proof_service}"
	)" || {
		echo "[fail] One-off Compose service image could not be resolved." >&2
		return 1
	}
	if [ "${resolved_compose_image}" != "${expected_daemon_id}" ]; then
		echo "[fail] One-off Compose service is not pinned to the proved target-daemon image ID." >&2
		return 1
	fi
	if ! one_off_acquire_lock; then
		one_off_cleanup || true
		one_off_restore_signal_traps
		return 1
	fi

	stdin_cleanup_armed=1
	trap 'one_off_signal 129' HUP
	trap 'one_off_signal 130' INT
	trap 'one_off_signal 143' TERM
	if ! stdin_dir="$(mktemp -d "${TMPDIR:-/tmp}/npcink-release-proof-stdin.XXXXXX")"; then
		stdin_cleanup_armed=0
		one_off_restore_signal_traps
		echo "[fail] Protected one-off stdin directory could not be created." >&2
		one_off_cleanup || \
			echo "[fail] One-off lock cleanup failed after protected stdin setup failed." >&2
		return 1
	fi
	stdin_path="${stdin_dir}/payload.stdin"
	if ! chmod 0700 "${stdin_dir}" || \
		[ ! -d "${stdin_dir}" ] || [ -L "${stdin_dir}" ] || \
		[ ! -O "${stdin_dir}" ] || \
		[ "$(one_off_mode_of "${stdin_dir}" 2>/dev/null || true)" != "700" ]; then
		echo "[fail] One-off ${service} stdin directory is not private." >&2
		proof_failed=1
		stdin_capture_failed=1
	fi
	if [ "${proof_failed}" -eq 0 ]; then
		if ! (umask 077; set -o noclobber; : >"${stdin_path}") 2>/dev/null || \
			! chmod 0600 "${stdin_path}" || \
			[ ! -f "${stdin_path}" ] || [ -L "${stdin_path}" ] || \
			[ ! -O "${stdin_path}" ] || \
			[ "$(one_off_mode_of "${stdin_path}" 2>/dev/null || true)" != "600" ]; then
			echo "[fail] One-off ${service} stdin file is not private." >&2
			proof_failed=1
			stdin_capture_failed=1
		fi
	fi
	# A terminal is not a finite payload and must not make a no-stdin migration
	# wait for an interactive EOF. Non-interactive callers (including heredocs)
	# are captured byte-for-byte. The explicit stdin duplication preserves the
	# caller stream for the asynchronous process; running it in the background
	# lets the signal trap interrupt a blocked/slow caller stream and clean up.
	if [ "${proof_failed}" -eq 0 ] && [ ! -t 0 ]; then
		cat <&0 >"${stdin_path}" &
		payload_pid="$!"
		if ! wait "${payload_pid}"; then
			echo "[fail] One-off ${service} stdin could not be captured safely." >&2
			proof_failed=1
			stdin_capture_failed=1
		fi
		payload_pid=""
	fi

	if [ "${proof_failed}" -eq 0 ]; then
		observed_reference_id="$(
			docker image inspect --format '{{.Id}}' "${expected_reference}" 2>/dev/null
		)" || {
			echo "[fail] Expected one-off image reference is unavailable." >&2
			proof_failed=1
		}
	fi
	if [ "${proof_failed}" -eq 0 ] && \
		[ "${observed_reference_id}" != "${expected_daemon_id}" ]; then
		echo "[fail] One-off image tag drifted from the bundle manifest before container creation." >&2
		proof_failed=1
	fi

	# Create the real Compose service shape without starting it. No image code,
	# including Python startup hooks, may execute before the stopped candidate's
	# immutable .Image and the governed tag are both re-proved.
	if [ "${proof_failed}" -eq 0 ]; then
		cleanup_armed=1
		if npcink_ai_cloud_compose "${root_dir}" up --no-start --pull never \
			--no-build --no-deps --force-recreate "${proof_service}" >/dev/null; then
			container_ids="$(
				npcink_ai_cloud_compose "${root_dir}" ps --all -q "${proof_service}" 2>/dev/null
			)" || proof_failed=1
			container_count="$(printf '%s\n' "${container_ids}" | awk 'NF {n += 1} END {print n + 0}')"
			if [ "${proof_failed}" -eq 0 ] && [ "${container_count}" -eq 1 ]; then
				container_name="$(printf '%s\n' "${container_ids}" | awk 'NF {print; exit}')"
				container_created=1
			else
				proof_failed=1
			fi
		else
			run_status=$?
			proof_failed=1
		fi
	fi

	if [ "${container_created}" -eq 1 ]; then
		observed_image_id="$(
			docker inspect --format '{{.Image}}' "${container_name}" 2>/dev/null
		)" || proof_failed=1
		observed_created_state="$(
			docker inspect --format '{{.State.Status}} {{.RestartCount}}' \
				"${container_name}" 2>/dev/null
		)" || proof_failed=1
		observed_reference_id="$(
			docker image inspect --format '{{.Id}}' "${expected_reference}" 2>/dev/null
		)" || proof_failed=1
		if [ "${observed_image_id}" != "${expected_daemon_id}" ] || \
			[ "${observed_created_state}" != "created 0" ] || \
			[ "${observed_reference_id}" != "${expected_daemon_id}" ]; then
			proof_failed=1
		fi
	fi

	if [ "${proof_failed}" -eq 0 ]; then
		if ! docker start "${container_name}" >/dev/null; then
			proof_failed=1
		fi
	fi
	if [ "${proof_failed}" -eq 0 ]; then
		observed_image_id="$(
			docker inspect --format '{{.Image}}' "${container_name}" 2>/dev/null
		)" || proof_failed=1
		observed_reference_id="$(
			docker image inspect --format '{{.Id}}' "${expected_reference}" 2>/dev/null
		)" || proof_failed=1
		[ "${observed_image_id}" = "${expected_daemon_id}" ] || proof_failed=1
		[ "${observed_reference_id}" = "${expected_daemon_id}" ] || proof_failed=1
		[ "$(docker inspect --format '{{.State.Running}}' "${container_name}" 2>/dev/null || true)" = "true" ] || proof_failed=1
	fi

	if [ "${proof_failed}" -eq 0 ]; then
		# Bash gives an asynchronous command /dev/null as stdin unless the
		# redirection is explicit. Freeze the caller's stdin above, then feed that
		# exact protected file to the background Docker client. Neither its path
		# nor its contents enter process argv or ordinary logs.
		# Bash 3.2 treats an empty-array expansion as unbound under `set -u`.
		# Keep the direct Docker child as the tracked PID in both branches so the
		# signal trap can still interrupt the actual client without a shell layer.
		if [ "${#exec_env_args[@]}" -gt 0 ]; then
			docker exec -i "${exec_env_args[@]}" "${container_name}" "$@" \
				<"${stdin_path}" &
			payload_pid="$!"
		else
			docker exec -i "${container_name}" "$@" <"${stdin_path}" &
			payload_pid="$!"
		fi
		if wait "${payload_pid}"; then
			run_status=0
		else
			run_status=$?
		fi
		payload_pid=""
		observed_reference_id="$(
			docker image inspect --format '{{.Id}}' "${expected_reference}" 2>/dev/null
		)" || proof_failed=1
		[ "${observed_reference_id}" = "${expected_daemon_id}" ] || proof_failed=1
	fi
	if ! one_off_cleanup; then
		cleanup_failed=1
	fi
	one_off_restore_signal_traps

	if [ "${proof_failed}" -ne 0 ]; then
		if [ "${stdin_capture_failed}" -ne 0 ]; then
			echo "[fail] One-off ${service} payload was blocked because protected stdin was unavailable." >&2
		else
			echo "[fail] One-off ${service} payload was blocked because the frozen exact image ID was not proved." >&2
		fi
	fi
	if [ "${run_status}" -ne 0 ]; then
		echo "[fail] One-off ${service} command failed after exact image proof." >&2
	fi
	if [ "${cleanup_failed}" -ne 0 ]; then
		echo "[fail] One-off ${service} cleanup was incomplete; the global one-off lock was retained." >&2
		return 1
	fi
	if [ "${proof_failed}" -ne 0 ]; then
		return 1
	fi
	if [ "${run_status}" -ne 0 ]; then
		return "${run_status}"
	fi
	printf '[ok] One-off %s container used the proved target-daemon image ID.\n' \
		"${service}" >&2
}

npcink_ai_cloud_wait_for_ready() {
	local base_url="$1"
	local attempts="${2:-20}"
	local sleep_seconds="${3:-2}"
	local health_url="${base_url%/}/health/live"
	local attempt=0
	local curl_args=(
		-fsS
		--connect-timeout 3
		--max-time 10
	)

	if [ -n "${NPCINK_CLOUD_HEALTH_HOST_HEADER:-}" ]; then
		curl_args+=(-H "Host: ${NPCINK_CLOUD_HEALTH_HOST_HEADER}")
	fi
	if [ -n "${NPCINK_CLOUD_HEALTH_FORWARDED_PROTO:-}" ]; then
		curl_args+=(-H "X-Forwarded-Proto: ${NPCINK_CLOUD_HEALTH_FORWARDED_PROTO}")
	fi

	while [ "${attempt}" -lt "${attempts}" ]; do
		if curl "${curl_args[@]}" "${health_url}" >/dev/null 2>&1; then
			return 0
		fi
		attempt=$((attempt + 1))
		sleep "${sleep_seconds}"
	done

	return 1
}

npcink_ai_cloud_wait_for_internal_endpoint() {
	local root_dir="$1"
	local endpoint_path="$2"
	local success_message="$3"

	npcink_ai_cloud_compose "${root_dir}" exec -T api python - \
		"${endpoint_path}" "${success_message}" <<'PY'
from __future__ import annotations

import os
import re
import sys
import time
import urllib.error
import urllib.request

endpoint_path = sys.argv[1]
success_message = sys.argv[2]
domain_name = os.getenv("NPCINK_CLOUD_DOMAIN_NAME", "").strip()
trusted_hosts = os.getenv("NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST", "")
trusted_host = next((item.strip() for item in trusted_hosts.split(",") if item.strip()), "")
host = domain_name or trusted_host or "127.0.0.1"
if host.startswith("*."):
    host = host[2:]
if not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]+)?", host):
    print("[fail] Internal readiness Host is invalid.", file=sys.stderr)
    raise SystemExit(1)

headers = {"Host": host}
if endpoint_path != "/health/live":
    token = os.getenv("NPCINK_CLOUD_INTERNAL_AUTH_TOKEN", "").strip()
    if not token:
        try:
            from app.core.runtime_config import read_internal_auth_token

            token = read_internal_auth_token().strip()
        except (ImportError, OSError, RuntimeError, ValueError):
            token = ""
    if not token:
        print("[fail] Internal readiness credential is unavailable.", file=sys.stderr)
        raise SystemExit(1)
    headers["X-Npcink-Internal-Token"] = token

request = urllib.request.Request(
    f"http://127.0.0.1:8000{endpoint_path}",
    headers=headers,
)
last_error: Exception | None = None
for _ in range(30):
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.status == 200:
                print(success_message)
                raise SystemExit(0)
    except (OSError, urllib.error.URLError) as exc:
        last_error = exc
    time.sleep(2)

print(f"[fail] Internal readiness probe did not pass: {last_error}", file=sys.stderr)
raise SystemExit(1)
PY
}
