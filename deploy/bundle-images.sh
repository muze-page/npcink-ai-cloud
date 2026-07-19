#!/usr/bin/env bash
set -euo pipefail

CLOUD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
DIST_DIR="${CLOUD_DIR}/dist"
MANIFEST_HELPER="${CLOUD_DIR}/scripts/verify-release-bundle-manifest.py"
IMAGE_LOCK="deploy/image-lock/production-images.json"
IMAGE_ALLOWLIST="deploy/image-lock/cve-allowlist.json"
IMAGE_PLATFORM="${NPCINK_CLOUD_IMAGE_PLATFORM:-}"
PACKAGE_EXTRAS="${NPCINK_CLOUD_PACKAGE_EXTRAS:-}"
SKIP_FRONTEND_IMAGE="${NPCINK_CLOUD_SKIP_FRONTEND_IMAGE:-0}"
INCLUDE_EXTERNAL_IMAGES="${NPCINK_CLOUD_INCLUDE_EXTERNAL_IMAGES:-1}"
GZIP_LEVEL="${NPCINK_CLOUD_BUNDLE_GZIP_LEVEL:-1}"
BUILD_CACHE_SCOPE_PREFIX="${NPCINK_CLOUD_BUILD_CACHE_SCOPE_PREFIX:-npcink-ai-cloud}"

fail() {
	echo "[fail] $*" >&2
	exit 1
}

# A formal bundle is evidence for one committed tree. There is intentionally no
# bypass: ignored dist output is allowed, but every tracked/untracked source edit
# must be committed before any image build starts.
git -C "${CLOUD_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "bundle source is not a Git worktree"
if [ -n "$(git -C "${CLOUD_DIR}" status --porcelain=v1 --untracked-files=all)" ]; then
	fail "formal release bundle requires a clean Git worktree"
fi
REVISION="$(git -C "${CLOUD_DIR}" rev-parse HEAD)"
TREE="$(git -C "${CLOUD_DIR}" rev-parse HEAD^{tree})"
BRANCH="$(git -C "${CLOUD_DIR}" symbolic-ref --quiet --short HEAD || printf 'detached')"
COMMIT_EPOCH="$(git -C "${CLOUD_DIR}" show -s --format=%ct HEAD)"
git -C "${CLOUD_DIR}" ls-files --error-unmatch "${IMAGE_LOCK}" >/dev/null 2>&1 || fail "production image lock is not committed"
git -C "${CLOUD_DIR}" ls-files --error-unmatch "${IMAGE_ALLOWLIST}" >/dev/null 2>&1 || fail "production CVE allowlist is not committed"
git -C "${CLOUD_DIR}" ls-files --error-unmatch scripts/verify-release-bundle-manifest.py >/dev/null 2>&1 || fail "bundle manifest helper is not committed"

# Release scan evidence is valid only for the canonical repository policy and
# the local Unix Docker daemon. The finished verified bundle is what crosses
# the SSH boundary; a remote Docker build/scan mode is intentionally unsupported.
[ -z "${NPCINK_CLOUD_IMAGE_LOCK_FILE:-}" ] || fail "formal release bundles forbid NPCINK_CLOUD_IMAGE_LOCK_FILE overrides"
[ -z "${DOCKER_HOST:-}" ] || fail "formal release bundles forbid DOCKER_HOST overrides; build and scan locally, then deploy the verified bundle over SSH"
[ -z "${DOCKER_CONTEXT:-}" ] || fail "formal release bundles forbid DOCKER_CONTEXT overrides; use the canonical local Docker context"

case "${GZIP_LEVEL}" in
	[1-9]) ;;
	*) fail "NPCINK_CLOUD_BUNDLE_GZIP_LEVEL must be from 1 to 9" ;;
esac
case "${SKIP_FRONTEND_IMAGE}:${INCLUDE_EXTERNAL_IMAGES}" in
	[01]:[01]) ;;
	*) fail "bundle include flags must be 0 or 1" ;;
esac
case "${PACKAGE_EXTRAS}" in
	""|"[zilliz]") ;;
	*) fail "NPCINK_CLOUD_PACKAGE_EXTRAS must be empty or [zilliz] for a formal production bundle" ;;
esac
[ "${SKIP_FRONTEND_IMAGE}" = "0" ] || fail "complete exact release bundles must include the frontend image"
[ "${INCLUDE_EXTERNAL_IMAGES}" = "1" ] || fail "complete exact release bundles must include every locked external image"

command -v docker >/dev/null 2>&1 || fail "docker is required"
command -v python3 >/dev/null 2>&1 || fail "python3 is required"
command -v tar >/dev/null 2>&1 || fail "tar is required"
docker buildx version >/dev/null 2>&1 || fail "docker buildx is required"

if [ -n "${IMAGE_PLATFORM}" ]; then
	case "${IMAGE_PLATFORM}" in
		linux/amd64|linux/arm64) MANIFEST_IMAGE_PLATFORM="${IMAGE_PLATFORM}" ;;
		*) fail "NPCINK_CLOUD_IMAGE_PLATFORM must be linux/amd64 or linux/arm64" ;;
	esac
else
	NATIVE_PLATFORM="$(docker info --format '{{.OSType}}/{{.Architecture}}')"
	case "${NATIVE_PLATFORM}" in
		linux/amd64|linux/x86_64) MANIFEST_IMAGE_PLATFORM="linux/amd64" ;;
		linux/arm64|linux/aarch64) MANIFEST_IMAGE_PLATFORM="linux/arm64" ;;
		*) fail "cannot resolve native Docker image platform: ${NATIVE_PLATFORM}" ;;
	esac
fi

mkdir -p "${DIST_DIR}"
LOCAL_STAGE="$(mktemp -d "${DIST_DIR}/.release-bundle-stage.XXXXXX")"
SOURCE_INPUTS="$(mktemp "${DIST_DIR}/.release-source-inputs.XXXXXX")"
IMAGE_RECORDS="$(mktemp "${DIST_DIR}/.release-image-records.XXXXXX")"
FINAL_IMAGE_RECORDS="$(mktemp "${DIST_DIR}/.release-final-image-records.XXXXXX")"
EXTERNAL_PLAN="$(mktemp "${DIST_DIR}/.release-external-plan.XXXXXX")"
APPLICATION_PLAN="$(mktemp "${DIST_DIR}/.release-application-plan.XXXXXX")"
LOCAL_SCAN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/npcink-release-image-scan.XXXXXX")"

cleanup() {
	local exit_status="$?"
	trap - EXIT
	if ! rm -rf "${LOCAL_STAGE}" "${SOURCE_INPUTS}" "${IMAGE_RECORDS}" "${FINAL_IMAGE_RECORDS}" "${EXTERNAL_PLAN}" "${APPLICATION_PLAN}" "${LOCAL_SCAN_DIR}"; then
		echo "[warn] Failed to remove one or more release-bundle temporary paths." >&2
		if [ "${exit_status}" -eq 0 ]; then
			exit_status=1
		fi
	fi
	exit "${exit_status}"
}
trap cleanup EXIT

mkdir -p "${LOCAL_STAGE}/dist"
python3 "${MANIFEST_HELPER}" application-plan \
	--image-lock "${CLOUD_DIR}/${IMAGE_LOCK}" \
	--output "${APPLICATION_PLAN}"
ARCHIVE_PATHS=(
	Dockerfile
	docker-compose.prod.yml
	docker-compose.runtime.yml
	deploy
	frontend/Dockerfile
	site
	scripts/production-image-supply.py
	scripts/scan-production-images.sh
	scripts/verify-release-bundle-manifest.py
)
while IFS=$'\t' read -r key _reference dockerfile _archive; do
	[ -n "${key}" ] || continue
	git -C "${CLOUD_DIR}" ls-files --error-unmatch "${dockerfile}" >/dev/null 2>&1 || fail "application Dockerfile is not committed: ${dockerfile}"
	ARCHIVE_PATHS+=("${dockerfile}")
done <"${APPLICATION_PLAN}"
git -C "${CLOUD_DIR}" archive HEAD -- "${ARCHIVE_PATHS[@]}" | tar -x -C "${LOCAL_STAGE}"
python3 "${MANIFEST_HELPER}" source-inputs --source-root "${CLOUD_DIR}" --output "${SOURCE_INPUTS}"
python3 "${MANIFEST_HELPER}" external-plan \
	--image-lock "${CLOUD_DIR}/${IMAGE_LOCK}" \
	--output "${EXTERNAL_PLAN}"

BUILD_ARGS=(--build-arg "PACKAGE_EXTRAS=${PACKAGE_EXTRAS}")
BUILDKIT_SECRET_IDS=()
if [ -n "${NPCINK_CLOUD_PIP_INDEX_URL:-}" ]; then
	BUILD_ARGS+=(--secret "id=pip_index_url,env=NPCINK_CLOUD_PIP_INDEX_URL")
	BUILDKIT_SECRET_IDS+=(pip_index_url)
fi
if [ -n "${NPCINK_CLOUD_PIP_EXTRA_INDEX_URL:-}" ]; then
	BUILD_ARGS+=(--secret "id=pip_extra_index_url,env=NPCINK_CLOUD_PIP_EXTRA_INDEX_URL")
	BUILDKIT_SECRET_IDS+=(pip_extra_index_url)
fi
if [ -n "${NPCINK_CLOUD_PIP_TRUSTED_HOST:-}" ]; then
	BUILD_ARGS+=(--secret "id=pip_trusted_host,env=NPCINK_CLOUD_PIP_TRUSTED_HOST")
	BUILDKIT_SECRET_IDS+=(pip_trusted_host)
fi
BUILDKIT_SECRET_ID_CSV="$(IFS=,; printf '%s' "${BUILDKIT_SECRET_IDS[*]:-}")"

BUILD_CACHE_ARGS=()
set_build_cache_args() {
	local cache_scope="$1"
	BUILD_CACHE_ARGS=()
	if [ -n "${GITHUB_ACTIONS:-}" ] && [ "${NPCINK_CLOUD_DISABLE_GHA_BUILD_CACHE:-0}" != "1" ]; then
		BUILD_CACHE_ARGS=(
			--cache-from "type=gha,scope=${BUILD_CACHE_SCOPE_PREFIX}-${cache_scope}"
			--cache-to "type=gha,scope=${BUILD_CACHE_SCOPE_PREFIX}-${cache_scope},mode=max,ignore-error=true"
		)
	fi
}

image_id() {
	docker image inspect --format '{{.Id}}' "$1"
}

image_platform() {
	docker image inspect --format '{{.Os}}/{{.Architecture}}' "$1"
}

require_image_platform() {
	local reference="$1" actual_platform
	actual_platform="$(image_platform "${reference}" 2>/dev/null || true)"
	[ "${actual_platform}" = "${MANIFEST_IMAGE_PLATFORM}" ] || fail "image platform mismatch for ${reference}: expected ${MANIFEST_IMAGE_PLATFORM}, got ${actual_platform:-missing}"
}

ensure_image() {
	local reference="$1" actual_platform
	actual_platform="$(image_platform "${reference}" 2>/dev/null || true)"
	if [ "${actual_platform}" != "${MANIFEST_IMAGE_PLATFORM}" ]; then
		echo "[info] Pulling ${reference} for ${MANIFEST_IMAGE_PLATFORM}; cached platform was ${actual_platform:-missing}"
		docker pull --platform "${MANIFEST_IMAGE_PLATFORM}" "${reference}"
	fi
	require_image_platform "${reference}"
}

echo "[info] Building API image exactly once for ${REVISION} on ${MANIFEST_IMAGE_PLATFORM}"
set_build_cache_args api
docker buildx build --platform "${MANIFEST_IMAGE_PLATFORM}" \
	${BUILD_CACHE_ARGS[@]+"${BUILD_CACHE_ARGS[@]}"} "${BUILD_ARGS[@]}" --load \
	-t npcink-ai-cloud-api:prod -f "${CLOUD_DIR}/Dockerfile" "${CLOUD_DIR}"
docker tag npcink-ai-cloud-api:prod npcink-ai-cloud-worker:prod
docker tag npcink-ai-cloud-api:prod npcink-ai-cloud-callback-worker:prod
docker tag npcink-ai-cloud-api:prod npcink-ai-cloud-ops-worker:prod
require_image_platform npcink-ai-cloud-api:prod

echo "[info] Building frontend image exactly once for ${MANIFEST_IMAGE_PLATFORM}"
set_build_cache_args frontend
docker buildx build --platform "${MANIFEST_IMAGE_PLATFORM}" \
	${BUILD_CACHE_ARGS[@]+"${BUILD_CACHE_ARGS[@]}"} --load -t npcink-ai-cloud-frontend:prod \
	-f "${CLOUD_DIR}/frontend/Dockerfile" "${CLOUD_DIR}"
require_image_platform npcink-ai-cloud-frontend:prod

while IFS=$'\t' read -r key reference dockerfile _archive; do
	[ -n "${key}" ] || continue
	echo "[info] Building ${key} image exactly once for ${MANIFEST_IMAGE_PLATFORM}"
	set_build_cache_args "${key}"
	docker buildx build --platform "${MANIFEST_IMAGE_PLATFORM}" \
		${BUILD_CACHE_ARGS[@]+"${BUILD_CACHE_ARGS[@]}"} --load -t "${reference}" \
		-f "${CLOUD_DIR}/${dockerfile}" "${CLOUD_DIR}"
	require_image_platform "${reference}"
done <"${APPLICATION_PLAN}"

append_image_record() {
	local archive="$1" role="$2" reference="$3" source_reference="$4" source_id="$5" primary="$6"
	printf '%s\t%s\t%s\t%s\t%s\t%s\t1\t%s\n' \
		"${archive}" "${role}" "${reference}" "${source_reference}" \
		"${source_id}" "${source_id}" "${primary}" >>"${IMAGE_RECORDS}"
}

package_scanned_image() {
	local key="$1" relative_output="$2" archive_path
	archive_path="${LOCAL_SCAN_DIR}/${key}.image.tar"
	[ -f "${archive_path}" ] || fail "release scanner did not retain the governed archive for ${key}"
	echo "[info] Packaging the exact scanned ${key} archive as ${relative_output}"
	gzip -n "-${GZIP_LEVEL}" -c "${archive_path}" >"${LOCAL_STAGE}/${relative_output}"
}

API_IMAGE_ID="$(image_id npcink-ai-cloud-api:prod)"
append_image_record dist/api.tar.gz api npcink-ai-cloud-api:prod npcink-ai-cloud-api:prod "${API_IMAGE_ID}" 1
append_image_record dist/api.tar.gz worker npcink-ai-cloud-worker:prod npcink-ai-cloud-worker:prod "${API_IMAGE_ID}" 0
append_image_record dist/api.tar.gz callback_worker npcink-ai-cloud-callback-worker:prod npcink-ai-cloud-callback-worker:prod "${API_IMAGE_ID}" 0
append_image_record dist/api.tar.gz ops_worker npcink-ai-cloud-ops-worker:prod npcink-ai-cloud-ops-worker:prod "${API_IMAGE_ID}" 0

FRONTEND_IMAGE_ID="$(image_id npcink-ai-cloud-frontend:prod)"
append_image_record dist/frontend.tar.gz frontend npcink-ai-cloud-frontend:prod npcink-ai-cloud-frontend:prod "${FRONTEND_IMAGE_ID}" 1

while IFS=$'\t' read -r key reference _dockerfile archive; do
	[ -n "${key}" ] || continue
	APPLICATION_IMAGE_ID="$(image_id "${reference}")"
	append_image_record "${archive}" "${key}" "${reference}" "${reference}" "${APPLICATION_IMAGE_ID}" 1
done <"${APPLICATION_PLAN}"

while IFS=$'\t' read -r key source_reference release_reference archive; do
	[ -n "${key}" ] || continue
	ensure_image "${source_reference}"
	docker tag "${source_reference}" "${release_reference}"
	EXTERNAL_IMAGE_ID="$(image_id "${source_reference}")"
	append_image_record "${archive}" "external_${key}" "${release_reference}" "${source_reference}" "${EXTERNAL_IMAGE_ID}" 1
done <"${EXTERNAL_PLAN}"

# Scan the exact IDs after the single application build and exact external
# pulls, then archive those same IDs without any intervening build/pull. The
# child environment cannot redirect the release scan to an alternate policy.
(
	unset NPCINK_CLOUD_IMAGE_LOCK_FILE DOCKER_HOST DOCKER_CONTEXT
	export DOCKER_DEFAULT_PLATFORM="${MANIFEST_IMAGE_PLATFORM}"
	bash "${CLOUD_DIR}/scripts/scan-production-images.sh" \
		--platform "${MANIFEST_IMAGE_PLATFORM}" \
		--output "${LOCAL_SCAN_DIR}"
)
mkdir -p "${LOCAL_STAGE}/release/image-scan"
for scan_evidence in "${LOCAL_SCAN_DIR}"/*; do
	case "${scan_evidence}" in
		*.image.tar) continue ;;
	esac
	cp "${scan_evidence}" "${LOCAL_STAGE}/release/image-scan/"
done
python3 "${MANIFEST_HELPER}" finalize-image-records \
	--image-lock "${CLOUD_DIR}/${IMAGE_LOCK}" \
	--scan-index "${LOCAL_SCAN_DIR}/scan-index.json" \
	--input "${IMAGE_RECORDS}" \
	--output "${FINAL_IMAGE_RECORDS}"

verify_scanned_image() {
	local reference="$1" expected_id="$2" actual_id actual_platform
	actual_id="$(image_id "${reference}")"
	actual_platform="$(image_platform "${reference}")"
	[ "${actual_id}" = "${expected_id}" ] || fail "image ID changed after scan for ${reference}"
	[ "${actual_platform}" = "${MANIFEST_IMAGE_PLATFORM}" ] || fail "image platform changed after scan for ${reference}"
}
while IFS=$'\t' read -r _archive _role reference _source_reference source_id _portable_id _required primary; do
	[ "${primary}" = "1" ] || continue
	verify_scanned_image "${reference}" "${source_id}"
done <"${FINAL_IMAGE_RECORDS}"

package_scanned_image api dist/api.tar.gz
package_scanned_image frontend dist/frontend.tar.gz
while IFS=$'\t' read -r key reference _dockerfile archive; do
	[ -n "${key}" ] || continue
	package_scanned_image "${key}" "${archive}"
done <"${APPLICATION_PLAN}"
while IFS=$'\t' read -r key _source_reference release_reference archive; do
	[ -n "${key}" ] || continue
	package_scanned_image "${key}" "${archive}"
done <"${EXTERNAL_PLAN}"

python3 "${MANIFEST_HELPER}" create \
	--source-root "${LOCAL_STAGE}" \
	--source-inputs-file "${SOURCE_INPUTS}" \
	--bundle-root "${LOCAL_STAGE}" \
	--revision "${REVISION}" \
	--tree "${TREE}" \
	--branch "${BRANCH}" \
	--image-platform "${MANIFEST_IMAGE_PLATFORM}" \
	--package-extras "${PACKAGE_EXTRAS}" \
	--gzip-level "${GZIP_LEVEL}" \
	--frontend-included "1" \
	--external-images-included "1" \
	--buildkit-secret-ids "${BUILDKIT_SECRET_ID_CSV}" \
	--image-lock "${IMAGE_LOCK}" \
	--image-records "${FINAL_IMAGE_RECORDS}"
bash "${LOCAL_STAGE}/deploy/verify-release-bundle.sh" --pre-load "${LOCAL_STAGE}"
python3 "${MANIFEST_HELPER}" pack --root "${LOCAL_STAGE}" \
	--output "${DIST_DIR}/deploy-bundle.tgz" --gzip-level "${GZIP_LEVEL}" --mtime "${COMMIT_EPOCH}"
python3 "${MANIFEST_HELPER}" checksum --bundle "${DIST_DIR}/deploy-bundle.tgz" \
	--output "${DIST_DIR}/deploy-bundle.tgz.sha256"
bash "${CLOUD_DIR}/deploy/verify-release-bundle.sh" --archive \
	"${DIST_DIR}/deploy-bundle.tgz" "${DIST_DIR}/deploy-bundle.tgz.sha256"
echo "Cloud exact deploy bundle ready: ${DIST_DIR}/deploy-bundle.tgz (${MANIFEST_IMAGE_PLATFORM})"
