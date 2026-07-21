#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CANONICAL_LOCK_FILE="${ROOT_DIR}/deploy/image-lock/production-images.json"
LOCK_FILE="${NPCINK_CLOUD_IMAGE_LOCK_FILE:-${CANONICAL_LOCK_FILE}}"
OUTPUT_DIR=""
APPLICATIONS_ONLY=0
RELEASE_SCOPE=1
RELEASE_PLATFORM="${NPCINK_CLOUD_RELEASE_PLATFORM:-}"
CUSTOM_KEYS=()
CUSTOM_REFS=()

fail() {
	echo "[fail] $*" >&2
	exit 1
}

usage() {
	cat <<'USAGE'
Usage: scripts/scan-production-images.sh [options]

Options:
  --output DIR          Empty output directory outside the Git worktree.
  --applications-only   Scan the API and frontend build outputs only.
  --image KEY=REF       Scan one exact local image reference; repeatable.
  --platform PLATFORM   Explicit linux/amd64 or linux/arm64 release platform.
  -h, --help            Show this help.

With no target option, the gate scans API/frontend plus every digest-locked
external production image. External inputs are pulled by exact digest. Every
target is inspected to an immutable local image ID before Syft and Grype run.
USAGE
}

while [ "$#" -gt 0 ]; do
	case "$1" in
		--output)
			[ "$#" -ge 2 ] || fail "--output requires a directory"
			OUTPUT_DIR="$2"
			shift
			;;
		--applications-only)
			APPLICATIONS_ONLY=1
			RELEASE_SCOPE=0
			;;
		--image)
			[ "$#" -ge 2 ] || fail "--image requires KEY=REF"
			case "$2" in
				*=*) ;;
				*) fail "--image must use KEY=REF" ;;
			esac
			CUSTOM_KEYS+=("${2%%=*}")
			CUSTOM_REFS+=("${2#*=}")
			RELEASE_SCOPE=0
			shift
			;;
		--platform)
			[ "$#" -ge 2 ] || fail "--platform requires linux/amd64 or linux/arm64"
			RELEASE_PLATFORM="$2"
			shift
			;;
		-h | --help)
			usage
			exit 0
			;;
		*)
			echo "[fail] unknown argument: $1" >&2
			usage >&2
			exit 64
			;;
	esac
	shift
done

if [ "${APPLICATIONS_ONLY}" = "1" ] && [ "${#CUSTOM_KEYS[@]}" -gt 0 ]; then
	fail "--applications-only and --image cannot be combined"
fi

if [ "${RELEASE_SCOPE}" = "1" ]; then
	[ -z "${NPCINK_CLOUD_IMAGE_LOCK_FILE:-}" ] \
		|| fail "release scans reject NPCINK_CLOUD_IMAGE_LOCK_FILE; use the canonical lock"
	[ -n "${RELEASE_PLATFORM}" ] \
		|| fail "release scans require --platform linux/amd64 or --platform linux/arm64"
fi
case "${RELEASE_PLATFORM}" in
	"" | linux/amd64 | linux/arm64) ;;
	*) fail "unsupported scan platform: ${RELEASE_PLATFORM}" ;;
esac

command -v docker >/dev/null 2>&1 || fail "docker is required"
command -v python3 >/dev/null 2>&1 || fail "python3 is required"
command -v tar >/dev/null 2>&1 || fail "tar is required"
[ -z "${DOCKER_HOST:-}" ] || fail "DOCKER_HOST is forbidden for production image scans"
DOCKER_CONTEXT_NAME="$(docker context show 2>/dev/null)" \
	|| fail "active Docker context cannot be determined"
DOCKER_ENDPOINT="$(
	docker context inspect "${DOCKER_CONTEXT_NAME}" \
		--format '{{(index .Endpoints "docker").Host}}' 2>/dev/null
)" || fail "active Docker context cannot be inspected"
case "${DOCKER_ENDPOINT}" in
	unix:///*) DOCKER_SOCKET_PATH="${DOCKER_ENDPOINT#unix://}" ;;
	*) fail "refusing non-local Docker context: only a local Unix socket is allowed" ;;
esac
[ -S "${DOCKER_SOCKET_PATH}" ] || fail "local Docker Unix socket is unavailable"
docker info >/dev/null 2>&1 || fail "local Docker daemon is unavailable"

require_docker_platform_archive_support() {
	local inspect_help save_help server_api api_major api_minor
	inspect_help="$(docker image inspect --help 2>&1)" \
		|| fail "cannot inspect Docker image-inspect capabilities"
	save_help="$(docker image save --help 2>&1)" \
		|| fail "cannot inspect Docker image-save capabilities"
	case "${inspect_help}" in
		*--platform*) ;;
		*) fail "production image scanner requires docker image inspect --platform support" ;;
	esac
	case "${save_help}" in
		*--platform*) ;;
		*) fail "production image scanner requires docker image save --platform support" ;;
	esac
	server_api="$(docker version --format '{{.Server.APIVersion}}' 2>/dev/null)" \
		|| fail "cannot resolve Docker server API version"
	if [[ ! "${server_api}" =~ ^([0-9]+)\.([0-9]+)$ ]]; then
		fail "cannot parse Docker server API version: ${server_api}"
	fi
	api_major="${BASH_REMATCH[1]}"
	api_minor="${BASH_REMATCH[2]}"
	if ((api_major < 1 || (api_major == 1 && api_minor < 49))); then
		fail "production image scanner requires Docker server API 1.49 or newer; got ${server_api}"
	fi
}

require_docker_platform_archive_support

if [ -z "${RELEASE_PLATFORM}" ]; then
	RELEASE_PLATFORM="$(docker info --format '{{.OSType}}/{{.Architecture}}')"
	case "${RELEASE_PLATFORM}" in
		linux/aarch64) RELEASE_PLATFORM="linux/arm64" ;;
		linux/x86_64) RELEASE_PLATFORM="linux/amd64" ;;
	esac
	case "${RELEASE_PLATFORM}" in
		linux/amd64 | linux/arm64) ;;
		*) fail "unsupported local Docker platform: ${RELEASE_PLATFORM}" ;;
	esac
fi

python3 "${ROOT_DIR}/scripts/production-image-supply.py" verify --lock "${LOCK_FILE}" >/dev/null

SYFT_IMAGE=""
GRYPE_IMAGE=""
ALLOWLIST_FILE=""
TARGET_KEYS=()
TARGET_REFS=()
TARGET_PULL=()
TARGET_ARCHIVE_REFS=()
while IFS=$'\t' read -r record_type key value pull archive_reference; do
	case "${record_type}" in
		scanner)
			case "${key}" in
				syft) SYFT_IMAGE="${value}" ;;
				grype) GRYPE_IMAGE="${value}" ;;
			esac
			;;
		allowlist) ALLOWLIST_FILE="${value}" ;;
		target)
			TARGET_KEYS+=("${key}")
			TARGET_REFS+=("${value}")
			TARGET_PULL+=("${pull}")
			TARGET_ARCHIVE_REFS+=("${archive_reference}")
			;;
	esac
done < <(
	python3 - "${LOCK_FILE}" "${APPLICATIONS_ONLY}" <<'PY'
import json
import sys
from pathlib import Path

lock_path = Path(sys.argv[1]).resolve()
applications_only = sys.argv[2] == "1"
lock = json.loads(lock_path.read_text())
root = lock_path.parents[2]
for scanner in lock["scanner_images"]:
    print("scanner", scanner["key"], scanner["reference"], "0", sep="\t")
print("allowlist", "path", root / lock["scan_policy"]["allowlist_file"], "0", sep="\t")
for output in lock["application_outputs"]:
    if output.get("scan_by_default"):
        print("target", output["key"], output["reference"], "0", output["reference"], sep="\t")
if not applications_only:
    for image in lock["production_inputs"]:
        if image["kind"] == "compose_external":
            print(
                "target",
                image["key"],
                image["reference"],
                "1",
                image["release_reference"],
                sep="\t",
            )
PY
)

[ -n "${SYFT_IMAGE}" ] || fail "Syft image is missing from lock"
[ -n "${GRYPE_IMAGE}" ] || fail "Grype image is missing from lock"
[ -f "${ALLOWLIST_FILE}" ] || fail "CVE allowlist is missing: ${ALLOWLIST_FILE}"

if [ "${#CUSTOM_KEYS[@]}" -gt 0 ]; then
	TARGET_KEYS=("${CUSTOM_KEYS[@]}")
	TARGET_REFS=("${CUSTOM_REFS[@]}")
	TARGET_PULL=()
	TARGET_ARCHIVE_REFS=()
	for custom_index in "${!CUSTOM_REFS[@]}"; do
		custom_reference="${CUSTOM_REFS[${custom_index}]}"
		case "${custom_reference}" in
			*@sha256:*)
				TARGET_PULL+=("1")
				custom_digest="${custom_reference##*@sha256:}"
				TARGET_ARCHIVE_REFS+=(
					"npcink-ai-cloud-scan-${CUSTOM_KEYS[${custom_index}]}:${custom_digest:0:12}"
				)
				;;
			*)
				TARGET_PULL+=("0")
				TARGET_ARCHIVE_REFS+=("${custom_reference}")
				;;
		esac
	done
fi
[ "${#TARGET_KEYS[@]}" -gt 0 ] || fail "no image targets selected"

for index in "${!TARGET_KEYS[@]}"; do
	key="${TARGET_KEYS[${index}]}"
	case "${key}" in
		*[!A-Za-z0-9_.-]* | "") fail "unsafe image key: ${key}" ;;
	esac
	for previous in "${!TARGET_KEYS[@]}"; do
		if [ "${previous}" -lt "${index}" ] && [ "${TARGET_KEYS[${previous}]}" = "${key}" ]; then
			fail "duplicate image key: ${key}"
		fi
	done
done

if [ -z "${OUTPUT_DIR}" ]; then
	OUTPUT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/npcink-production-image-scan.XXXXXX")"
else
	mkdir -p "${OUTPUT_DIR}"
	if [ -n "$(ls -A "${OUTPUT_DIR}")" ]; then
		fail "--output directory must be empty: ${OUTPUT_DIR}"
	fi
fi
OUTPUT_DIR="$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' "${OUTPUT_DIR}")"
ROOT_REAL="$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' "${ROOT_DIR}")"
case "${OUTPUT_DIR}/" in
	"${ROOT_REAL}/"*) fail "scan output must stay outside the Git worktree" ;;
esac
chmod 0700 "${OUTPUT_DIR}"
umask 077

GRYPE_CACHE="$(mktemp -d "${TMPDIR:-/tmp}/npcink-grype-cache.XXXXXX")"
chmod 0700 "${GRYPE_CACHE}"
trap 'rm -rf "${GRYPE_CACHE}"' EXIT

echo "[scan] refreshing the pinned Grype database once for this scan set"
docker run --rm \
	-e GRYPE_DB_AUTO_UPDATE=true \
	-e GRYPE_DB_VALIDATE_BY_HASH_ON_START=true \
	-e GRYPE_CHECK_FOR_APP_UPDATE=false \
	-v "${GRYPE_CACHE}:/.cache/grype" \
	"${GRYPE_IMAGE}" db update >/dev/null

overall_status=0
RECEIPTS=()
EQUIVALENCE_ARGS=()
if [ "${RELEASE_SCOPE}" = "1" ]; then
	EQUIVALENCE_PATH="${OUTPUT_DIR}/application-image-equivalence.json"
	python3 "${ROOT_DIR}/scripts/production-image-supply.py" equivalence \
		--lock "${LOCK_FILE}" \
		--expected-platform "${RELEASE_PLATFORM}" \
		--output "${EQUIVALENCE_PATH}" || fail "application worker image IDs are not equivalent"
	EQUIVALENCE_ARGS=(--equivalence-json "${EQUIVALENCE_PATH}")
fi
for index in "${!TARGET_KEYS[@]}"; do
	key="${TARGET_KEYS[${index}]}"
	reference="${TARGET_REFS[${index}]}"
	pull="${TARGET_PULL[${index}]}"
	archive_reference="${TARGET_ARCHIVE_REFS[${index}]}"
	echo "[scan] ${key}: ${reference}"
	if [ "${pull}" = "1" ]; then
		docker pull --platform "${RELEASE_PLATFORM}" "${reference}" >/dev/null
	fi
	if ! image_id="$(docker image inspect --platform "${RELEASE_PLATFORM}" \
		"${reference}" --format '{{.Id}}')"; then
		fail "image is not available locally: ${reference}"
	fi
	case "${image_id}" in
		sha256:????????????????????????????????????????????????????????????????) ;;
		*) fail "Docker returned a non-sha256 image ID for ${reference}: ${image_id}" ;;
	esac
	actual_platform="$(docker image inspect --platform "${RELEASE_PLATFORM}" \
		"${reference}" --format '{{.Os}}/{{.Architecture}}')"
	case "${actual_platform}" in
		linux/aarch64) actual_platform="linux/arm64" ;;
		linux/x86_64) actual_platform="linux/amd64" ;;
	esac
	[ "${actual_platform}" = "${RELEASE_PLATFORM}" ] \
		|| fail "image platform mismatch for ${key}: expected ${RELEASE_PLATFORM}, got ${actual_platform}"

	inspect_path="${OUTPUT_DIR}/${key}.image-inspect.json"
	sbom_path="${OUTPUT_DIR}/${key}.sbom.cdx.json"
	report_path="${OUTPUT_DIR}/${key}.grype.json"
	receipt_path="${OUTPUT_DIR}/${key}.receipt.json"
	docker image inspect --platform "${RELEASE_PLATFORM}" "${reference}" >"${inspect_path}"
	if [ "${archive_reference}" != "${reference}" ]; then
		docker image tag "${reference}" "${archive_reference}"
	fi
	archive_image_id="$(docker image inspect --platform "${RELEASE_PLATFORM}" \
		"${archive_reference}" --format '{{.Id}}')"
	[ "${archive_image_id}" = "${image_id}" ] \
		|| fail "archive reference does not resolve to the scanned daemon image for ${key}"
	archive_path="${OUTPUT_DIR}/${key}.image.tar"
	docker image save --platform "${RELEASE_PLATFORM}" \
		--output "${archive_path}" "${archive_reference}"
	chmod 0600 "${archive_path}"

	docker run --rm \
		-v "${OUTPUT_DIR}:/input:ro" \
		-v "${OUTPUT_DIR}:/output" \
		"${SYFT_IMAGE}" \
		"docker-archive:/input/${key}.image.tar" \
		-o "cyclonedx-json=/output/${key}.sbom.cdx.json" \
		-o "syft-json=/output/${key}.syft.json"
	[ -s "${sbom_path}" ] || fail "Syft did not create ${sbom_path}"
	[ -s "${OUTPUT_DIR}/${key}.syft.json" ] \
		|| fail "Syft did not create ${OUTPUT_DIR}/${key}.syft.json"

	report_tmp="${report_path}.tmp"
	if ! docker run --rm \
		-e GRYPE_DB_AUTO_UPDATE=false \
		-e GRYPE_DB_VALIDATE_BY_HASH_ON_START=true \
		-e GRYPE_CHECK_FOR_APP_UPDATE=false \
		-v "${OUTPUT_DIR}:/output:ro" \
		-v "${GRYPE_CACHE}:/.cache/grype" \
		"${GRYPE_IMAGE}" \
		"sbom:/output/${key}.sbom.cdx.json" \
		-o json >"${report_tmp}"; then
		rm -f "${report_tmp}"
		fail "Grype failed closed while scanning ${key}"
	fi
	mv "${report_tmp}" "${report_path}"
	[ -s "${report_path}" ] || fail "Grype did not create ${report_path}"

	if ! python3 "${ROOT_DIR}/scripts/production-image-supply.py" evaluate \
		--lock "${LOCK_FILE}" \
		--allowlist "${ALLOWLIST_FILE}" \
		--image-key "${key}" \
		--source-daemon-image-id "${image_id}" \
		--requested-reference "${reference}" \
		--archive-reference "${archive_reference}" \
		--scope "$([ "${RELEASE_SCOPE}" = "1" ] && printf release || printf focused)" \
		--expected-platform "${RELEASE_PLATFORM}" \
		--docker-context "${DOCKER_CONTEXT_NAME}" \
		--inspect-json "${inspect_path}" \
		--archive "${archive_path}" \
		--syft-json "${OUTPUT_DIR}/${key}.syft.json" \
		--sbom "${sbom_path}" \
		--report "${report_path}" \
		--receipt "${receipt_path}"; then
		overall_status=1
	fi
	[ -s "${receipt_path}" ] || fail "scan evaluator did not create ${receipt_path}"
	RECEIPTS+=("${receipt_path}")
done

INDEX_SCOPE="focused"
if [ "${RELEASE_SCOPE}" = "1" ]; then
	INDEX_SCOPE="release"
fi
if [ "${RELEASE_SCOPE}" = "1" ]; then
	if ! python3 "${ROOT_DIR}/scripts/production-image-supply.py" index \
		--lock "${LOCK_FILE}" \
		--scope "${INDEX_SCOPE}" \
		--expected-platform "${RELEASE_PLATFORM}" \
		--output "${OUTPUT_DIR}/scan-index.json" \
		"${EQUIVALENCE_ARGS[@]}" \
		"${RECEIPTS[@]}"; then
		overall_status=1
	fi
else
	if ! python3 "${ROOT_DIR}/scripts/production-image-supply.py" index \
		--lock "${LOCK_FILE}" \
		--scope "${INDEX_SCOPE}" \
		--expected-platform "${RELEASE_PLATFORM}" \
		--output "${OUTPUT_DIR}/scan-index.json" \
		"${RECEIPTS[@]}"; then
		overall_status=1
	fi
fi

echo "[scan] reports: ${OUTPUT_DIR}"
exit "${overall_status}"
