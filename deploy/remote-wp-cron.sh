#!/usr/bin/env bash
set -euo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_SOURCE}")" >/dev/null 2>&1 && pwd -P || true)"
ROOT_DIR="$(pwd -P)"
if [ -n "${SCRIPT_DIR}" ] && [ -f "${SCRIPT_DIR}/../deploy/common.sh" ]; then
	ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
fi

. "${ROOT_DIR}/deploy/common.sh"
npcink_ai_cloud_load_env_file "${ROOT_DIR}"

ACTION="status"
CRONTAB_FILE=""
DRY_RUN=0
SITE_URL="${NPCINK_CLOUD_WP_CRON_SITE_BASE_URL:-}"
SCHEDULE="${NPCINK_CLOUD_WP_CRON_SCHEDULE:-*/5 * * * *}"
CURL_TIMEOUT_SECONDS="${NPCINK_CLOUD_WP_CRON_CURL_TIMEOUT_SECONDS:-90}"
CONNECT_TIMEOUT_SECONDS="${NPCINK_CLOUD_WP_CRON_CONNECT_TIMEOUT_SECONDS:-10}"
DOING_WP_CRON="${NPCINK_CLOUD_WP_CRON_DOING_WP_CRON:-cloud}"
LOCK_FILE="${NPCINK_CLOUD_WP_CRON_LOCK_FILE:-/tmp/npcink-wordpress-cron.lock}"
COMMENT_TAG="${NPCINK_CLOUD_WP_CRON_COMMENT_TAG:-npcink-wordpress-cron}"
USER_AGENT="${NPCINK_CLOUD_WP_CRON_USER_AGENT:-NpcinkCloudWordPressCron/1.0}"
CURL_BIN_OVERRIDE="${NPCINK_CLOUD_WP_CRON_CURL_BIN:-}"
FLOCK_BIN_OVERRIDE="${NPCINK_CLOUD_WP_CRON_FLOCK_BIN:-}"

while [ "$#" -gt 0 ]; do
	case "$1" in
		install|remove|status)
			ACTION="$1"
			shift
			;;
		--)
			shift
			;;
		--file)
			CRONTAB_FILE="$2"
			shift 2
			;;
		--site-url)
			SITE_URL="$2"
			shift 2
			;;
		--schedule)
			SCHEDULE="$2"
			shift 2
			;;
		--curl-timeout)
			CURL_TIMEOUT_SECONDS="$2"
			shift 2
			;;
		--connect-timeout)
			CONNECT_TIMEOUT_SECONDS="$2"
			shift 2
			;;
		--doing-wp-cron)
			DOING_WP_CRON="$2"
			shift 2
			;;
		--lock-file)
			LOCK_FILE="$2"
			shift 2
			;;
		--comment-tag)
			COMMENT_TAG="$2"
			shift 2
			;;
		--user-agent)
			USER_AGENT="$2"
			shift 2
			;;
		--curl-bin)
			CURL_BIN_OVERRIDE="$2"
			shift 2
			;;
		--flock-bin)
			FLOCK_BIN_OVERRIDE="$2"
			shift 2
			;;
		--dry-run)
			DRY_RUN=1
			shift
			;;
		*)
			echo "[fail] Unknown argument: $1" >&2
			exit 1
			;;
	esac
done

BEGIN_MARKER="# BEGIN ${COMMENT_TAG}"
END_MARKER="# END ${COMMENT_TAG}"

fail() {
	echo "[fail] $*" >&2
	exit 1
}

ok() {
	echo "[ok] $*"
}

posture_note() {
	echo "[info] Customer default remains standard WP-Cron; use this helper only when the site intentionally disables automatic WP-Cron and production should drive wp-cron.php from server cron."
}

ensure_render_dependencies() {
	if [ -z "${CURL_BIN_OVERRIDE}" ]; then
		npcink_ai_cloud_require_cmd curl
	fi
	if [ -z "${FLOCK_BIN_OVERRIDE}" ]; then
		npcink_ai_cloud_require_cmd flock
	fi
}

ensure_status_dependencies() {
	if [ -z "${CRONTAB_FILE}" ]; then
		npcink_ai_cloud_require_cmd crontab
	fi
}

read_crontab_contents() {
	if [ -n "${CRONTAB_FILE}" ]; then
		if [ -f "${CRONTAB_FILE}" ]; then
			cat "${CRONTAB_FILE}"
		fi
		return 0
	fi

	crontab -l 2>/dev/null || true
}

write_crontab_file() {
	local source_file="$1"
	if [ "${DRY_RUN}" -eq 1 ]; then
		cat "${source_file}"
		return 0
	fi

	if [ -n "${CRONTAB_FILE}" ]; then
		cp "${source_file}" "${CRONTAB_FILE}"
		return 0
	fi

	crontab "${source_file}"
}

build_target_url() {
	if [ -z "${SITE_URL}" ]; then
		fail "--site-url or NPCINK_CLOUD_WP_CRON_SITE_BASE_URL is required for install"
	fi

	local normalized_url="${SITE_URL%/}"
	printf '%s/wp-cron.php?doing_wp_cron=%s' "${normalized_url}" "${DOING_WP_CRON}"
}

build_cron_line() {
	ensure_render_dependencies

	local curl_bin
	local flock_bin
	local target_url
	curl_bin="${CURL_BIN_OVERRIDE}"
	flock_bin="${FLOCK_BIN_OVERRIDE}"
	if [ -z "${curl_bin}" ]; then
		curl_bin="$(command -v curl)"
	fi
	if [ -z "${flock_bin}" ]; then
		flock_bin="$(command -v flock)"
	fi
	target_url="$(build_target_url)"

	printf '%s %q -n %q %q -fsS --connect-timeout %q --max-time %q -A %q %q >/dev/null 2>&1' \
		"${SCHEDULE}" \
		"${flock_bin}" \
		"${LOCK_FILE}" \
		"${curl_bin}" \
		"${CONNECT_TIMEOUT_SECONDS}" \
		"${CURL_TIMEOUT_SECONDS}" \
		"${USER_AGENT}" \
		"${target_url}"
}

extract_managed_block() {
	local source_file="$1"
	awk -v begin="${BEGIN_MARKER}" -v end="${END_MARKER}" '
		$0 == begin { print; inside = 1; next }
		inside { print; if ( $0 == end ) { exit } }
	' "${source_file}"
}

strip_managed_block() {
	local source_file="$1"
	local target_file="$2"
	awk -v begin="${BEGIN_MARKER}" -v end="${END_MARKER}" '
		$0 == begin { inside = 1; next }
		$0 == end { inside = 0; next }
		! inside { print }
	' "${source_file}" > "${target_file}"
}

prepare_existing_file() {
	local target_file="$1"
	: > "${target_file}"
	read_crontab_contents > "${target_file}"
}

install_entry() {
	local existing_file
	local stripped_file
	local output_file
	local cron_line

	existing_file="$(mktemp)"
	stripped_file="$(mktemp)"
	output_file="$(mktemp)"
	trap "rm -f '${existing_file}' '${stripped_file}' '${output_file}'" RETURN

	prepare_existing_file "${existing_file}"
	strip_managed_block "${existing_file}" "${stripped_file}"
	cron_line="$(build_cron_line)"

	cat "${stripped_file}" > "${output_file}"
	if [ -s "${output_file}" ]; then
		printf '\n' >> "${output_file}"
	fi
	printf '%s\n' "${BEGIN_MARKER}" >> "${output_file}"
	printf '%s\n' "${cron_line}" >> "${output_file}"
	printf '%s\n' "${END_MARKER}" >> "${output_file}"

	write_crontab_file "${output_file}"
	if [ "${DRY_RUN}" -eq 1 ]; then
		ok "Rendered managed WordPress cron block."
		posture_note
		return 0
	fi

	ok "Installed managed WordPress cron entry."
	posture_note
}

remove_entry() {
	local existing_file
	local stripped_file

	existing_file="$(mktemp)"
	stripped_file="$(mktemp)"
	trap "rm -f '${existing_file}' '${stripped_file}'" RETURN

	prepare_existing_file "${existing_file}"
	strip_managed_block "${existing_file}" "${stripped_file}"
	write_crontab_file "${stripped_file}"

	if [ "${DRY_RUN}" -eq 1 ]; then
		ok "Rendered crontab without managed WordPress cron block."
		posture_note
		return 0
	fi

	ok "Removed managed WordPress cron entry."
	posture_note
}

status_entry() {
	local existing_file
	local block_file

	existing_file="$(mktemp)"
	block_file="$(mktemp)"
	trap "rm -f '${existing_file}' '${block_file}'" RETURN

	ensure_status_dependencies
	prepare_existing_file "${existing_file}"
	extract_managed_block "${existing_file}" > "${block_file}"

	if [ ! -s "${block_file}" ]; then
		echo "[info] No managed WordPress cron entry found."
		posture_note
		return 0
	fi

	cat "${block_file}"
	ok "Managed WordPress cron entry present."
	posture_note
}

case "${ACTION}" in
	install)
		install_entry
		;;
	remove)
		remove_entry
		;;
	status)
		status_entry
		;;
	*)
		fail "Unsupported action: ${ACTION}"
		;;
esac
