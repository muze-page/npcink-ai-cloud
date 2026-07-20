#!/usr/bin/env bash

npcink_ai_cloud_require_cmd() {
	local cmd="$1"
	command -v "${cmd}" >/dev/null 2>&1 || {
		echo "[fail] Missing required command: ${cmd}" >&2
		exit 1
	}
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
	while IFS= read -r line || [ -n "${line}" ]; do
		case "${line}" in
			'' | '#'*)
				continue
				;;
		esac
		if [[ "${line}" != *=* ]]; then
			continue
		fi
		key="${line%%=*}"
		if [[ ! "${key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
			continue
		fi
		if [ -n "${!key+x}" ]; then
			continue
		fi
		eval "export ${line}"
	done < "${env_file}"
}

npcink_ai_cloud_compose() {
	local root_dir="$1"
	shift

	local compose_file="${NPCINK_CLOUD_COMPOSE_FILE:-${root_dir}/docker-compose.prod.yml}"
	local env_file=""
	local backend_env_file="${NPCINK_CLOUD_BACKEND_ENV_FILE:-}"
	local compose_project_name="${NPCINK_CLOUD_COMPOSE_PROJECT_NAME:-${COMPOSE_PROJECT_NAME:-}}"

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

	if [ -n "${env_file}" ]; then
		COMPOSE_PROJECT_NAME="${compose_project_name}" \
			NPCINK_CLOUD_BACKEND_ENV_FILE="${backend_env_file}" \
			docker compose --env-file "${env_file}" -f "${compose_file}" "$@"
		return
	fi

	COMPOSE_PROJECT_NAME="${compose_project_name}" \
		NPCINK_CLOUD_BACKEND_ENV_FILE="${backend_env_file}" \
		docker compose -f "${compose_file}" "$@"
}

npcink_ai_cloud_compose_run_with_image_proof() {
	local root_dir="$1"
	local service="$2"
	local expected_reference="$3"
	local expected_image_id="$4"
	shift 4

	local observed_image_id=""
	local observed_reference_id=""
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
	local container_name="npcink-release-proof-${service}-$$-${RANDOM}"

	one_off_remove_container() {
		local attempt=0
		[ "${cleanup_armed}" -eq 1 ] || return 0
		while [ "${attempt}" -lt 2 ]; do
			if docker rm -f "${container_name}" >/dev/null 2>&1; then
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
	one_off_cleanup() {
		local failed=0
		one_off_remove_container || failed=1
		one_off_remove_stdin || failed=1
		return "${failed}"
	}
	one_off_signal() {
		local status="$1"
		trap - EXIT HUP INT TERM
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
	if [[ ! "${expected_reference}" =~ ^[A-Za-z0-9._/-]+(:[A-Za-z0-9._-]+)?$ ]]; then
		echo "[fail] Invalid one-off expected image reference." >&2
		return 1
	fi
	if [[ ! "${expected_image_id}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
		echo "[fail] Manifest-frozen one-off image ID is invalid." >&2
		return 1
	fi

	stdin_cleanup_armed=1
	trap 'one_off_signal 129' HUP
	trap 'one_off_signal 130' INT
	trap 'one_off_signal 143' TERM
	if ! stdin_dir="$(mktemp -d "${TMPDIR:-/tmp}/npcink-release-proof-stdin.XXXXXX")"; then
		stdin_cleanup_armed=0
		trap - HUP INT TERM
		echo "[fail] Protected one-off stdin directory could not be created." >&2
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
		[ "${observed_reference_id}" != "${expected_image_id}" ]; then
		echo "[fail] One-off image tag drifted from the bundle manifest before container creation." >&2
		proof_failed=1
	fi

	# Start the real Compose service shape with an inert process first. The
	# migration/provider payload is not allowed to execute until the created
	# container's immutable .Image matches the frozen exact tag.
	if [ "${proof_failed}" -eq 0 ]; then
		cleanup_armed=1
		if npcink_ai_cloud_compose "${root_dir}" run -d \
			--name "${container_name}" --no-deps --rm --entrypoint python "${service}" \
			-c 'import time; time.sleep(900)' >/dev/null; then
			container_created=1
		else
			run_status=$?
			proof_failed=1
		fi
	fi

	if [ "${container_created}" -eq 1 ]; then
		observed_image_id="$(
			docker inspect --format '{{.Image}}' "${container_name}" 2>/dev/null
		)" || proof_failed=1
		observed_reference_id="$(
			docker image inspect --format '{{.Id}}' "${expected_reference}" 2>/dev/null
		)" || proof_failed=1
		if [ "${observed_image_id}" != "${expected_image_id}" ] || \
			[ "${observed_reference_id}" != "${expected_image_id}" ]; then
			proof_failed=1
		fi
	fi

	if [ "${proof_failed}" -eq 0 ]; then
		# Bash gives an asynchronous command /dev/null as stdin unless the
		# redirection is explicit. Freeze the caller's stdin above, then feed that
		# exact protected file to the background Docker client. Neither its path
		# nor its contents enter process argv or ordinary logs.
		docker exec -i "${container_name}" "$@" <"${stdin_path}" &
		payload_pid="$!"
		if wait "${payload_pid}"; then
			run_status=0
		else
			run_status=$?
		fi
		payload_pid=""
		observed_reference_id="$(
			docker image inspect --format '{{.Id}}' "${expected_reference}" 2>/dev/null
		)" || proof_failed=1
		[ "${observed_reference_id}" = "${expected_image_id}" ] || proof_failed=1
	fi
	if ! one_off_cleanup; then
		cleanup_failed=1
	fi
	trap - HUP INT TERM

	if [ "${proof_failed}" -ne 0 ]; then
		if [ "${stdin_capture_failed}" -ne 0 ]; then
			echo "[fail] One-off ${service} payload was blocked because protected stdin was unavailable." >&2
			return 1
		fi
		echo "[fail] One-off ${service} payload was blocked because the frozen exact image ID was not proved." >&2
		return 1
	fi
	if [ "${run_status}" -ne 0 ]; then
		echo "[fail] One-off ${service} command failed after exact image proof." >&2
		return "${run_status}"
	fi
	if [ "${cleanup_failed}" -ne 0 ]; then
		echo "[fail] One-off ${service} proof container could not be removed or protected stdin cleanup failed." >&2
		return 1
	fi
	printf '[ok] One-off %s container used the frozen exact image ID.\n' "${service}"
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

request = urllib.request.Request(
    f"http://127.0.0.1:8000{endpoint_path}",
    headers={
        "Host": host,
        "X-Npcink-Internal-Token": os.environ["NPCINK_CLOUD_INTERNAL_AUTH_TOKEN"],
    },
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
