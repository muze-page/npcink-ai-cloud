#!/usr/bin/env bash
set -euo pipefail

CLOUD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${CLOUD_DIR}/dist"
IMAGE_PLATFORM="${NPCINK_CLOUD_IMAGE_PLATFORM:-}"
PIP_INDEX_URL="${NPCINK_CLOUD_PIP_INDEX_URL:-}"
PIP_EXTRA_INDEX_URL="${NPCINK_CLOUD_PIP_EXTRA_INDEX_URL:-}"
PIP_TRUSTED_HOST="${NPCINK_CLOUD_PIP_TRUSTED_HOST:-}"
SKIP_FRONTEND_IMAGE="${NPCINK_CLOUD_SKIP_FRONTEND_IMAGE:-0}"
REMOTE_BUNDLE_ONLY="${NPCINK_CLOUD_REMOTE_BUNDLE_ONLY:-0}"
REMOTE_DOCKER_HOST=""
if [[ "${DOCKER_HOST:-}" == ssh://* ]]; then
	REMOTE_DOCKER_HOST="${DOCKER_HOST#ssh://}"
fi

mkdir -p "${DIST_DIR}"

if [ -n "${REMOTE_DOCKER_HOST}" ]; then
	command -v ssh >/dev/null 2>&1 || {
		echo "Missing required command for remote Docker bundle export: ssh" >&2
		exit 1
	}
	command -v rsync >/dev/null 2>&1 || {
		echo "Missing required command for remote Docker bundle export: rsync" >&2
		exit 1
	}
fi

BUILD_ARGS=()
if [ -n "${PIP_INDEX_URL}" ]; then
	BUILD_ARGS+=(--build-arg "PIP_INDEX_URL=${PIP_INDEX_URL}")
fi
if [ -n "${PIP_EXTRA_INDEX_URL}" ]; then
	BUILD_ARGS+=(--build-arg "PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL}")
fi
if [ -n "${PIP_TRUSTED_HOST}" ]; then
	BUILD_ARGS+=(--build-arg "PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}")
fi

if [ -n "${IMAGE_PLATFORM}" ]; then
	echo "[info] Building cloud images for platform ${IMAGE_PLATFORM}"
	if [ "${#BUILD_ARGS[@]}" -gt 0 ]; then
		docker buildx build \
			--platform "${IMAGE_PLATFORM}" \
			"${BUILD_ARGS[@]}" \
			--load \
			-t npcink-ai-cloud-api:prod \
			-f "${CLOUD_DIR}/Dockerfile" \
			"${CLOUD_DIR}"
	else
		docker buildx build \
			--platform "${IMAGE_PLATFORM}" \
			--load \
			-t npcink-ai-cloud-api:prod \
			-f "${CLOUD_DIR}/Dockerfile" \
			"${CLOUD_DIR}"
	fi
	docker tag npcink-ai-cloud-api:prod npcink-ai-cloud-worker:prod
	if [ "${SKIP_FRONTEND_IMAGE}" != "1" ]; then
		docker buildx build \
			--platform "${IMAGE_PLATFORM}" \
			--load \
			-t npcink-ai-cloud-frontend:prod \
			-f "${CLOUD_DIR}/frontend/Dockerfile" \
			"${CLOUD_DIR}"
	fi
else
	if [ "${#BUILD_ARGS[@]}" -gt 0 ]; then
		if [ "${SKIP_FRONTEND_IMAGE}" = "1" ]; then
			docker compose -f "${CLOUD_DIR}/docker-compose.prod.yml" build "${BUILD_ARGS[@]}" api worker callback-worker ops-worker
		else
			docker compose -f "${CLOUD_DIR}/docker-compose.prod.yml" build "${BUILD_ARGS[@]}" api worker callback-worker ops-worker frontend
		fi
	else
		if [ "${SKIP_FRONTEND_IMAGE}" = "1" ]; then
			docker compose -f "${CLOUD_DIR}/docker-compose.prod.yml" build api worker callback-worker ops-worker
		else
			docker compose -f "${CLOUD_DIR}/docker-compose.prod.yml" build api worker callback-worker ops-worker frontend
		fi
	fi
fi

save_image() {
	local image="$1"
	local output="$2"

	if [ -z "${REMOTE_DOCKER_HOST}" ]; then
		echo "[info] Saving ${image} to ${output}"
		docker save "${image}" | gzip > "${output}"
		return 0
	fi

	# With DOCKER_HOST=ssh://..., streaming large docker save output through the
	# Docker CLI transport can time out. Save on the remote host, then rsync.
	echo "[info] Saving ${image} on ${REMOTE_DOCKER_HOST}"
	ssh "${REMOTE_DOCKER_HOST}" "mkdir -p $(printf '%q' "${DIST_DIR}") && docker save $(printf '%q' "${image}") | gzip > $(printf '%q' "${output}")"
	if [ "${REMOTE_BUNDLE_ONLY}" = "1" ]; then
		return 0
	fi
	echo "[info] Copying ${output} from ${REMOTE_DOCKER_HOST}"
	rsync -a -e "ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=10" "${REMOTE_DOCKER_HOST}:${output}" "${output}"
}

save_image npcink-ai-cloud-api:prod "${DIST_DIR}/api.tar.gz"
save_image npcink-ai-cloud-worker:prod "${DIST_DIR}/worker.tar.gz"
save_image npcink-ai-cloud-callback-worker:prod "${DIST_DIR}/callback-worker.tar.gz"
save_image npcink-ai-cloud-ops-worker:prod "${DIST_DIR}/ops-worker.tar.gz"
if [ "${SKIP_FRONTEND_IMAGE}" != "1" ]; then
	save_image npcink-ai-cloud-frontend:prod "${DIST_DIR}/frontend.tar.gz"
else
	rm -f "${DIST_DIR}/frontend.tar.gz"
fi

if [ -n "${REMOTE_DOCKER_HOST}" ] && [ "${REMOTE_BUNDLE_ONLY}" = "1" ]; then
	REMOTE_TAR_ARGS=(
		-C "${CLOUD_DIR}" docker-compose.prod.yml
		-C "${CLOUD_DIR}" docker-compose.runtime.yml
		-C "${CLOUD_DIR}" deploy
		-C "${CLOUD_DIR}" site
		-C "${CLOUD_DIR}" dist/api.tar.gz
		-C "${CLOUD_DIR}" dist/worker.tar.gz
		-C "${CLOUD_DIR}" dist/callback-worker.tar.gz
		-C "${CLOUD_DIR}" dist/ops-worker.tar.gz
	)
	if [ "${SKIP_FRONTEND_IMAGE}" != "1" ]; then
		REMOTE_TAR_ARGS+=(-C "${CLOUD_DIR}" dist/frontend.tar.gz)
	fi

	printf -v REMOTE_TAR_COMMAND ' %q' "${REMOTE_TAR_ARGS[@]}"
	ssh "${REMOTE_DOCKER_HOST}" "tar czf $(printf '%q' "${DIST_DIR}/deploy-bundle.tgz")${REMOTE_TAR_COMMAND}"
	echo "Cloud deploy bundle ready on ${REMOTE_DOCKER_HOST}: ${DIST_DIR}/deploy-bundle.tgz"
	exit 0
fi

TAR_ARGS=(
	-C "${CLOUD_DIR}" docker-compose.prod.yml
	-C "${CLOUD_DIR}" docker-compose.runtime.yml
	-C "${CLOUD_DIR}" deploy
	-C "${CLOUD_DIR}" site
	-C "${CLOUD_DIR}" dist/api.tar.gz
	-C "${CLOUD_DIR}" dist/worker.tar.gz
	-C "${CLOUD_DIR}" dist/callback-worker.tar.gz
	-C "${CLOUD_DIR}" dist/ops-worker.tar.gz
)
if [ "${SKIP_FRONTEND_IMAGE}" != "1" ]; then
	TAR_ARGS+=(-C "${CLOUD_DIR}" dist/frontend.tar.gz)
fi
tar czf "${DIST_DIR}/deploy-bundle.tgz" "${TAR_ARGS[@]}"

if [ -n "${IMAGE_PLATFORM}" ]; then
	echo "Cloud deploy bundle ready: ${DIST_DIR}/deploy-bundle.tgz (${IMAGE_PLATFORM})"
else
	echo "Cloud deploy bundle ready: ${DIST_DIR}/deploy-bundle.tgz"
fi
