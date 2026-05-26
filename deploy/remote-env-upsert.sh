#!/usr/bin/env bash
set -euo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
if [ -n "${SCRIPT_SOURCE}" ] && [ "${SCRIPT_SOURCE}" != "bash" ] && [ -e "${SCRIPT_SOURCE}" ]; then
	ROOT_DIR="$(cd "$(dirname "${SCRIPT_SOURCE}")/.." && pwd -P)"
else
	ROOT_DIR="$(pwd -P)"
fi
. "${ROOT_DIR}/deploy/common.sh"

ENV_PATH=".env.deploy"
SHARED_ENV_PATH=""
BASE_URL="${MAGICK_CLOUD_BASE_URL:-http://127.0.0.1:${MAGICK_CLOUD_PORT:-8010}}"
RESTART_SERVICES="proxy,api,worker,callback-worker,ops-worker"
RESTART_AFTER_UPDATE=1
declare -a SET_ENTRIES=()
declare -a UNSET_KEYS=()

resolve_env_path() {
	local path="$1"
	if [ -z "${path}" ]; then
		echo ""
		return
	fi
	if [ "${path#/}" != "${path}" ]; then
		echo "${path}"
		return
	fi
	echo "${ROOT_DIR}/${path}"
}

validate_key() {
	local key="$1"
	case "${key}" in
		MAGICK_CLOUD_[A-Z0-9_]*)
			return 0
			;;
		*)
			echo "[fail] Invalid env key: ${key}" >&2
			exit 1
			;;
	esac
}

fail_if_internal_token_removed() {
	local key="$1"
	local value="${2:-__UNSET__}"
	if [ "${key}" != "MAGICK_CLOUD_INTERNAL_AUTH_TOKEN" ]; then
		return 0
	fi
	if [ "${value}" = "__UNSET__" ] || [ -z "${value}" ]; then
		echo "[fail] MAGICK_CLOUD_INTERNAL_AUTH_TOKEN must remain non-empty for production perimeter" >&2
		exit 1
	fi
}

assert_env_file_internal_token() {
	local file="$1"
	if [ ! -f "${file}" ]; then
		echo "[fail] Missing env file: ${file}" >&2
		exit 1
	fi
	local value
	value="$(awk -F= '$1=="MAGICK_CLOUD_INTERNAL_AUTH_TOKEN"{print substr($0, index($0,"=")+1)}' "${file}" | tail -n 1)"
	if [ -z "${value}" ]; then
		echo "[fail] MAGICK_CLOUD_INTERNAL_AUTH_TOKEN must remain non-empty in ${file}" >&2
		exit 1
	fi
}

contains_newline() {
	local value="$1"
	case "${value}" in
		*$'\n'*|*$'\r'*)
			return 0
			;;
		*)
			return 1
			;;
	esac
}

join_csv() {
	local result=""
	local value
	for value in "$@"; do
		if [ -n "${result}" ]; then
			result="${result},${value}"
		else
			result="${value}"
		fi
	done
	printf '%s' "${result}"
}

update_env_file() {
	local target="$1"
	local skip_csv="$2"
	shift 2

	local tmp_file
	local target_dir
	target_dir="$(dirname "${target}")"
	mkdir -p "${target_dir}"
	touch "${target}"
	chmod 600 "${target}"

	tmp_file="$(mktemp)"

	if [ -s "${target}" ]; then
		awk -v skip_csv="${skip_csv}" '
			BEGIN {
				count = split(skip_csv, raw_keys, ",");
				for (i = 1; i <= count; i++) {
					if (raw_keys[i] != "") {
						skip[raw_keys[i]] = 1;
					}
				}
			}
			{
				if ($0 ~ /^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*=/) {
					key = $0;
					sub(/^[[:space:]]*/, "", key);
					sub(/=.*/, "", key);
					if (key in skip) {
						next;
					}
				}
				print;
			}
		' "${target}" > "${tmp_file}"
	else
		: > "${tmp_file}"
	fi

	while [ "$#" -gt 0 ]; do
		printf '%s\n' "$1" >> "${tmp_file}"
		shift
	done

	mv "${tmp_file}" "${target}"
	chmod 600 "${target}"
}

while [ "$#" -gt 0 ]; do
	case "$1" in
		--env-path)
			ENV_PATH="$2"
			shift 2
			;;
		--shared-env-path)
			SHARED_ENV_PATH="$2"
			shift 2
			;;
		--base-url)
			BASE_URL="$2"
			shift 2
			;;
		--set)
			SET_ENTRIES+=("$2")
			shift 2
			;;
		--unset)
			UNSET_KEYS+=("$2")
			shift 2
			;;
		--restart-services)
			RESTART_SERVICES="$2"
			shift 2
			;;
		--no-restart)
			RESTART_AFTER_UPDATE=0
			shift
			;;
		*)
			echo "[fail] Unknown argument: $1" >&2
			exit 1
			;;
	esac
done

if [ "${#SET_ENTRIES[@]}" -eq 0 ] && [ "${#UNSET_KEYS[@]}" -eq 0 ]; then
	echo "[fail] Nothing to update; pass --set and/or --unset" >&2
	exit 1
fi

ENV_FILE="$(resolve_env_path "${ENV_PATH}")"
SHARED_FILE="$(resolve_env_path "${SHARED_ENV_PATH}")"

SET_LINES=()
TOUCH_KEYS=()
if [ "${#SET_ENTRIES[@]}" -gt 0 ]; then
	for entry in "${SET_ENTRIES[@]}"; do
		case "${entry}" in
			*=*)
				key="${entry%%=*}"
				value="${entry#*=}"
				;;
			*)
				echo "[fail] Invalid --set entry: ${entry}" >&2
				exit 1
				;;
		esac
		validate_key "${key}"
		fail_if_internal_token_removed "${key}" "${value}"
		if contains_newline "${value}"; then
			echo "[fail] Multiline values are not supported for ${key}" >&2
			exit 1
		fi
		TOUCH_KEYS+=("${key}")
		SET_LINES+=("${key}=${value}")
	done
fi

if [ "${#UNSET_KEYS[@]}" -gt 0 ]; then
	for key in "${UNSET_KEYS[@]}"; do
		validate_key "${key}"
		fail_if_internal_token_removed "${key}"
		TOUCH_KEYS+=("${key}")
	done
fi

SKIP_CSV="$(join_csv "${TOUCH_KEYS[@]}")"

update_env_file "${ENV_FILE}" "${SKIP_CSV}" "${SET_LINES[@]}"
if [ -n "${SHARED_FILE}" ] && [ "${SHARED_FILE}" != "${ENV_FILE}" ]; then
	update_env_file "${SHARED_FILE}" "${SKIP_CSV}" "${SET_LINES[@]}"
fi

assert_env_file_internal_token "${ENV_FILE}"
if [ -n "${SHARED_FILE}" ] && [ "${SHARED_FILE}" != "${ENV_FILE}" ]; then
	assert_env_file_internal_token "${SHARED_FILE}"
fi

echo "[ok] Updated remote env keys: ${SKIP_CSV}"
echo "[ok] Primary env file: ${ENV_FILE}"
if [ -n "${SHARED_FILE}" ] && [ "${SHARED_FILE}" != "${ENV_FILE}" ]; then
	echo "[ok] Shared env file: ${SHARED_FILE}"
fi

if [ "${RESTART_AFTER_UPDATE}" -eq 1 ]; then
	magick_ai_cloud_require_cmd docker
	OLD_IFS="${IFS}"
	IFS=','
	read -r -a restart_service_array <<< "${RESTART_SERVICES}"
	IFS="${OLD_IFS}"
	magick_ai_cloud_compose "${ROOT_DIR}" up -d "${restart_service_array[@]}"

	case ",${RESTART_SERVICES}," in
		*,api,*)
			if ! magick_ai_cloud_wait_for_ready "${BASE_URL}" 20 2; then
				echo "[fail] Cloud API did not become ready at ${BASE_URL}" >&2
				exit 1
			fi
			;;
	esac
	echo "[ok] Restarted services: ${RESTART_SERVICES}"
fi
