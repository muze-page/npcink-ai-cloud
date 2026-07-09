#!/usr/bin/env bash

npcink_ai_cloud_require_cmd() {
	local cmd="$1"
	command -v "${cmd}" >/dev/null 2>&1 || {
		echo "[fail] Missing required command: ${cmd}" >&2
		exit 1
	}
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

	started_at="$(date +%s)"
	echo "[timing] ${label}: start"
	set +e
	"$@"
	status=$?
	set -e
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
	if [ -z "${env_file}" ] && [ -f "${root_dir}/.env.deploy" ]; then
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
	local env_file="${NPCINK_CLOUD_ENV_FILE:-}"
	if [ -z "${env_file}" ] && [ -f "${root_dir}/.env.deploy" ]; then
		env_file="${root_dir}/.env.deploy"
	fi
	local compose_project_name="${NPCINK_CLOUD_COMPOSE_PROJECT_NAME:-${COMPOSE_PROJECT_NAME:-npcink-ai-cloud}}"

	if [ -n "${env_file}" ]; then
		COMPOSE_PROJECT_NAME="${compose_project_name}" \
			docker compose --env-file "${env_file}" -f "${compose_file}" "$@"
		return
	fi

	COMPOSE_PROJECT_NAME="${compose_project_name}" \
		docker compose -f "${compose_file}" "$@"
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
