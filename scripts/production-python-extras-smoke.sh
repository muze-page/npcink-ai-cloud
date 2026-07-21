#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_TAG="${NPCINK_CLOUD_PROD_EXTRAS_DEFAULT_TAG:-npcink-ai-cloud-api:prod-extra-smoke-default}"
ZILLIZ_TAG="${NPCINK_CLOUD_PROD_EXTRAS_ZILLIZ_TAG:-npcink-ai-cloud-api:prod-extra-smoke-zilliz}"
UV_VERSION="0.11.29"
PYTHON_VERSION="3.14"
UVX_BIN="${UVX_BIN:-uvx}"
LOCK_ROOT="/usr/local/share/npcink-ai-cloud"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/npcink-python-lock-smoke.XXXXXX")"
EXPECTED_REQUIREMENTS="${TMP_DIR}/expected-requirements.txt"
trap 'rm -rf "${TMP_DIR}"' EXIT

fail() {
	echo "[fail] $*" >&2
	exit 1
}

ok() {
	echo "[ok] $*"
}

require_cmd() {
	local cmd="$1"
	command -v "${cmd}" >/dev/null 2>&1 || fail "Missing required command: ${cmd}"
}

verify_pinned_uv() {
	local version_output
	local tool_name
	local tool_version
	version_output="$("${UVX_BIN}" --from "uv==${UV_VERSION}" uv --version)"
	read -r tool_name tool_version _ <<<"${version_output}"
	[ "${tool_name}" = "uv" ] || fail "Unexpected uv tool output: ${version_output}"
	[ "${tool_version}" = "${UV_VERSION}" ] || fail "Expected uv ${UV_VERSION}, got: ${version_output}"
}

export_locked_requirements() {
	local package_extras="$1"
	local output_file="$2"
	local -a export_args=(
		export
		--quiet
		--python "${PYTHON_VERSION}"
		--locked
		--no-dev
		--no-emit-project
		--no-header
		--format requirements.txt
		--output-file "${output_file}"
	)

	case "${package_extras}" in
		"") ;;
		"[dev]") export_args+=(--extra dev) ;;
		"[zilliz]") export_args+=(--extra zilliz) ;;
		"[dev,zilliz]") export_args+=(--extra dev --extra zilliz) ;;
		*) fail "Unsupported PACKAGE_EXTRAS for independent export: ${package_extras}" ;;
	esac

	if [ -e "${output_file}" ]; then
		chmod 0644 "${output_file}"
	fi
	(
		cd "${ROOT_DIR}"
		"${UVX_BIN}" --from "uv==${UV_VERSION}" uv "${export_args[@]}"
	)
	chmod 0444 "${output_file}"
}

docker_build() {
	local tag="$1"
	local package_extras="$2"
	docker build \
		--build-arg "PACKAGE_EXTRAS=${package_extras}" \
		-t "${tag}" \
		"${ROOT_DIR}"
}

verify_image() {
	local tag="$1"
	local expected_package_extras="$2"
	local expected_pymilvus_installed="$3"
	local expected_requirements="$4"
	local -a distribution_assertion

	case "${expected_pymilvus_installed}" in
		expect) distribution_assertion=(--expect-distribution pymilvus) ;;
		forbid) distribution_assertion=(--forbid-distribution pymilvus) ;;
		*) fail "Unknown pymilvus expectation: ${expected_pymilvus_installed}" ;;
	esac

	ok "Verifying ${tag} against an independent uv.lock export for PACKAGE_EXTRAS=${expected_package_extras:-<empty>}"
	[ "$(docker image inspect --format '{{.Config.User}}' "${tag}")" = "app" ] || \
		fail "${tag} must run as the named app user"
	docker run --rm "${tag}" sh -eu -c '
		[ "$(id -u)" = "999" ]
		[ "$(id -g)" = "999" ]
		[ "$(getent passwd app | cut -d: -f3-4)" = "999:999" ]
		[ "$(getent group app | cut -d: -f3)" = "999" ]
		[ "$(stat -c "%u:%g" /var/lib/npcink-ai-cloud/artifacts)" = "999:999" ]
	'
	docker run --rm -i \
		--env PYTHONPATH=/app \
		-v "${expected_requirements}:/tmp/expected-requirements.txt:ro" \
		"${tag}" \
		python scripts/verify-production-python-lock.py \
		--requirements /tmp/expected-requirements.txt \
		--uv-lock /app/uv.lock \
		--package-extras "${expected_package_extras}" \
		--uv-version "${UV_VERSION}" \
		--check-manifest "${LOCK_ROOT}/production-python-lock.json" \
		--import-app \
		"${distribution_assertion[@]}"
}

require_cmd docker
require_cmd "${UVX_BIN}"
verify_pinned_uv

ok "Exporting the independent default dependency graph with uv ${UV_VERSION}"
export_locked_requirements "" "${EXPECTED_REQUIREMENTS}"
ok "Building default production Python image from uv.lock"
docker_build "${DEFAULT_TAG}" ""
verify_image "${DEFAULT_TAG}" "" "forbid" "${EXPECTED_REQUIREMENTS}"

if [ "${NPCINK_CLOUD_PROD_EXTRAS_SKIP_ZILLIZ:-0}" = "1" ]; then
	ok "Skipping zilliz locked image build because NPCINK_CLOUD_PROD_EXTRAS_SKIP_ZILLIZ=1"
	exit 0
fi

ok "Exporting the independent zilliz dependency graph with uv ${UV_VERSION}"
export_locked_requirements "[zilliz]" "${EXPECTED_REQUIREMENTS}"
ok "Building zilliz production Python image from uv.lock"
docker_build "${ZILLIZ_TAG}" "[zilliz]"
verify_image "${ZILLIZ_TAG}" "[zilliz]" "expect" "${EXPECTED_REQUIREMENTS}"

ok "Production Python locked dependency smoke completed successfully."
