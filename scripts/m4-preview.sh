#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

M4_SSH_HOST="${NPCINK_CLOUD_M4_SSH_HOST:-muze@100.102.170.79}"
M4_REMOTE_DIR="${NPCINK_CLOUD_M4_REMOTE_DIR:-/Users/muze/docker-workspaces/npcink-ai-cloud-m4-dev}"
M4_PROJECT_NAME="${NPCINK_CLOUD_M4_PROJECT_NAME:-npcink-ai-cloud-m4-dev}"
M4_PORT="${NPCINK_CLOUD_M4_PORT:-8010}"
M4_POSTGRES_PORT="${NPCINK_CLOUD_M4_POSTGRES_PORT:-15433}"
M4_REDIS_PORT="${NPCINK_CLOUD_M4_REDIS_PORT:-16380}"

DRY_RUN=0
TMP_DIR=""
REMOTE_SOURCE_BUNDLE=""
SOURCE_BUNDLE_PATH=""
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
SSH_ARGS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)
SCP_ARGS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)
ALLOWED_SERVICES="postgres redis api frontend proxy worker callback-worker ops-worker"

usage() {
	cat <<'EOF'
Usage:
  scripts/m4-preview.sh prepare [--dry-run]
  scripts/m4-preview.sh deploy [--dry-run]
  scripts/m4-preview.sh sync [--dry-run]
  scripts/m4-preview.sh status
  scripts/m4-preview.sh logs [--follow] [--tail N] <service> [...]
  scripts/m4-preview.sh test
  scripts/m4-preview.sh recover
  scripts/m4-preview.sh restart <service> [...]
  scripts/m4-preview.sh stop

The local worktree remains source and Git truth. Source is packaged on the
local machine, synchronized to the M4, and built/run only by M4 Docker.

Environment overrides:
  NPCINK_CLOUD_M4_SSH_HOST
  NPCINK_CLOUD_M4_REMOTE_DIR
  NPCINK_CLOUD_M4_PROJECT_NAME
  NPCINK_CLOUD_M4_PORT
  NPCINK_CLOUD_M4_POSTGRES_PORT
  NPCINK_CLOUD_M4_REDIS_PORT
EOF
}

log() {
	printf '[m4-preview] %s\n' "$*"
}

fail() {
	printf '[m4-preview] fail: %s\n' "$*" >&2
	exit 1
}

require_cmd() {
	command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

validate_number() {
	case "$2" in
		''|*[!0-9]*) fail "$1 must be numeric" ;;
	esac
}

validate_target() {
	case "${M4_PROJECT_NAME}" in
		npcink-ai-cloud-m4-preview)
			fail "legacy project name is forbidden"
			;;
		npcink-ai-cloud-m4-*)
			;;
		*)
			fail "project name must start with npcink-ai-cloud-m4-"
			;;
	esac
	case "${M4_PROJECT_NAME}" in
		*[!a-z0-9_-]*) fail "project name contains unsupported characters" ;;
	esac

	case "${M4_REMOTE_DIR}" in
		/Users/muze/docker-workspaces/npcink-ai-cloud-m4-*)
			;;
		*)
			fail "remote dir must stay under /Users/muze/docker-workspaces/npcink-ai-cloud-m4-*"
			;;
	esac
	case "${M4_REMOTE_DIR}" in
		*'/../'*|*'/./'*|*'//'*|*/..|*/.|*[!A-Za-z0-9._/-]*)
			fail "remote dir must be a canonical path"
			;;
	esac

	validate_number "M4 port" "${M4_PORT}"
	validate_number "M4 PostgreSQL port" "${M4_POSTGRES_PORT}"
	validate_number "M4 Redis port" "${M4_REDIS_PORT}"
}

cleanup() {
	local status=$?
	trap - EXIT INT TERM
	if [ -n "${REMOTE_SOURCE_BUNDLE}" ]; then
		ssh "${SSH_ARGS[@]}" "${M4_SSH_HOST}" \
			"rm -f $(printf '%q' "${REMOTE_SOURCE_BUNDLE}")" >/dev/null 2>&1 || true
	fi
	if [ -n "${TMP_DIR}" ] && [ -d "${TMP_DIR}" ]; then
		find "${TMP_DIR}" -depth -delete
	fi
	exit "${status}"
}

trap cleanup EXIT INT TERM

is_allowed_service() {
	local requested="$1"
	local service=""
	for service in ${ALLOWED_SERVICES}; do
		if [ "${requested}" = "${service}" ]; then
			return 0
		fi
	done
	return 1
}

validate_services() {
	local service=""
	[ "$#" -gt 0 ] || fail "at least one service is required"
	for service in "$@"; do
		is_allowed_service "${service}" || fail "unsupported service: ${service}"
	done
}

parse_dry_run() {
	local arg=""
	for arg in "$@"; do
		case "${arg}" in
			--dry-run)
				DRY_RUN=1
				;;
			--)
				;;
			*)
				fail "unknown argument: ${arg}"
				;;
		esac
	done
}

dependency_fingerprint() {
	local files=(
		Dockerfile
		pyproject.toml
		uv.lock
		frontend/Dockerfile.dev
		.dockerignore
		frontend/package.json
		package.json
		pnpm-lock.yaml
		pnpm-workspace.yaml
		scripts/m4-package-proxy.py
		scripts/m4-preview.sh
	)
	local file=""
	(
		cd "${ROOT_DIR}"
		for file in "${files[@]}"; do
			test -f "${file}" || fail "missing dependency input: ${file}"
			shasum -a 256 "${file}"
		done
	) | shasum -a 256 | awk '{print $1}'
}

config_fingerprint() {
	local files=(
		docker-compose.dev.yml
		docker-compose.m4-preview.yml
		deploy/nginx.m4-preview.conf
		scripts/redact-m4-preview-logs.py
	)
	local file=""
	(
		cd "${ROOT_DIR}"
		for file in "${files[@]}"; do
			test -f "${file}" || fail "missing preview config input: ${file}"
			shasum -a 256 "${file}"
		done
	) | shasum -a 256 | awk '{print $1}'
}

source_path_allowed() {
	local path="$1"
	case "${path}" in
		.env.example)
			return 0
			;;
		.env|.env.*|*/.env|*/.env.*)
			return 1
			;;
		.git|.git/*|*/.git|*/.git/*)
			return 1
			;;
		node_modules|node_modules/*|*/node_modules|*/node_modules/*)
			return 1
			;;
		.next|.next/*|*/.next|*/.next/*)
			return 1
			;;
		.venv|.venv/*|*/.venv|*/.venv/*)
			return 1
			;;
		.runtime|.runtime/*|*/.runtime|*/.runtime/*)
			return 1
			;;
		.pytest_cache|.pytest_cache/*|*/.pytest_cache|*/.pytest_cache/*)
			return 1
			;;
		.mypy_cache|.mypy_cache/*|*/.mypy_cache|*/.mypy_cache/*)
			return 1
			;;
		.ruff_cache|.ruff_cache/*|*/.ruff_cache|*/.ruff_cache/*)
			return 1
			;;
		__pycache__|__pycache__/*|*/__pycache__|*/__pycache__/*)
			return 1
			;;
		build|build/*|*/build|*/build/*)
			return 1
			;;
		dist|dist/*|*/dist|*/dist/*)
			return 1
			;;
		.tmp|.tmp/*|*/.tmp|*/.tmp/*)
			return 1
			;;
		.deploy-secrets|.deploy-secrets/*|*/.deploy-secrets|*/.deploy-secrets/*)
			return 1
			;;
		frontend/test-results|frontend/test-results/*)
			return 1
			;;
		frontend/playwright-report|frontend/playwright-report/*)
			return 1
			;;
	esac
	return 0
}

package_source() {
	require_cmd git
	require_cmd rsync
	require_cmd tar
	require_cmd shasum

	TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/npcink-m4-preview.XXXXXX")"
	local source_stage="${TMP_DIR}/source"
	local source_list="${TMP_DIR}/source-files"
	local source_bundle="${TMP_DIR}/source.tgz"
	local path=""
	mkdir -p "${source_stage}"

	log "packaging tracked files and allowed non-ignored files"
	while IFS= read -r -d '' path; do
		if ! source_path_allowed "${path}"; then
			continue
		fi
		if [ ! -e "${ROOT_DIR}/${path}" ] && [ ! -L "${ROOT_DIR}/${path}" ]; then
			continue
		fi
		printf '%s\0' "${path}"
	done < <(
		cd "${ROOT_DIR}"
		git ls-files -z --cached --others --exclude-standard
	) > "${source_list}"

	test -s "${source_list}" || fail "source file list is empty"
	rsync -a --from0 --files-from="${source_list}" "${ROOT_DIR}/" "${source_stage}/"
	COPYFILE_DISABLE=1 tar -czf "${source_bundle}" -C "${source_stage}" .
	SOURCE_BUNDLE_PATH="${source_bundle}"
}

source_dirty_state() {
	if git -C "${ROOT_DIR}" diff --quiet &&
		git -C "${ROOT_DIR}" diff --cached --quiet &&
		[ -z "$(git -C "${ROOT_DIR}" ls-files --others --exclude-standard)" ]; then
		printf 'false\n'
	else
		printf 'true\n'
	fi
}

source_dirty_count() {
	git -C "${ROOT_DIR}" status --porcelain=v1 --untracked-files=all | wc -l | tr -d ' '
}

upload_and_apply() {
	local mode="$1"
	local source_bundle=""
	local source_sha=""
	local source_revision=""
	local source_branch=""
	local source_dirty=""
	local dirty_count=""
	local image_input_sha=""
	local config_input_sha=""

	package_source
	source_bundle="${SOURCE_BUNDLE_PATH}"
	source_sha="$(shasum -a 256 "${source_bundle}" | awk '{print $1}')"
	source_revision="$(git -C "${ROOT_DIR}" rev-parse HEAD)"
	source_branch="$(git -C "${ROOT_DIR}" symbolic-ref --quiet --short HEAD || printf 'detached')"
	source_dirty="$(source_dirty_state)"
	dirty_count="$(source_dirty_count)"
	image_input_sha="$(dependency_fingerprint)"
	config_input_sha="$(config_fingerprint)"

	log "source revision: ${source_revision}"
	log "source branch: ${source_branch}"
	log "source dirty: ${source_dirty} (${dirty_count} paths)"
	log "source bundle SHA256: ${source_sha}"
	log "image input SHA256: ${image_input_sha}"
	log "config input SHA256: ${config_input_sha}"

	if [ "${DRY_RUN}" = "1" ]; then
		log "dry-run: would ${mode} ${M4_PROJECT_NAME} at ${M4_SSH_HOST}:${M4_REMOTE_DIR}"
		return 0
	fi

	require_cmd scp
	require_cmd ssh
	REMOTE_SOURCE_BUNDLE="/tmp/npcink-ai-cloud-m4-source-${RUN_ID}.tgz"
	log "uploading source bundle to M4"
	scp "${SCP_ARGS[@]}" "${source_bundle}" "${M4_SSH_HOST}:${REMOTE_SOURCE_BUNDLE}"

	log "applying source and ${mode} operation under the remote deployment lock"
	ssh "${SSH_ARGS[@]}" "${M4_SSH_HOST}" bash -s -- \
		"${M4_REMOTE_DIR}" \
		"${M4_PROJECT_NAME}" \
		"${REMOTE_SOURCE_BUNDLE}" \
		"${source_sha}" \
		"${source_revision}" \
		"${source_branch}" \
		"${source_dirty}" \
		"${dirty_count}" \
		"${image_input_sha}" \
		"${config_input_sha}" \
		"${mode}" \
		"${RUN_ID}" \
		"${M4_PORT}" \
		"${M4_POSTGRES_PORT}" \
		"${M4_REDIS_PORT}" <<'REMOTE_APPLY'
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

remote_dir="$1"
project_name="$2"
source_bundle="$3"
source_sha="$4"
source_revision="$5"
source_branch="$6"
source_dirty="$7"
dirty_count="$8"
image_input_sha="$9"
config_input_sha="${10}"
mode="${11}"
run_id="${12}"
preview_port="${13}"
postgres_port="${14}"
redis_port="${15}"

case "${project_name}" in
	npcink-ai-cloud-m4-preview)
		echo '[m4-preview] legacy project name is forbidden' >&2
		exit 64
		;;
	npcink-ai-cloud-m4-*)
		;;
	*)
		echo '[m4-preview] invalid project name' >&2
		exit 64
		;;
esac
case "${project_name}" in
	*[!a-z0-9_-]*)
		echo '[m4-preview] invalid project-name characters' >&2
		exit 64
		;;
esac

case "${remote_dir}" in
	/Users/muze/docker-workspaces/npcink-ai-cloud-m4-*)
		;;
	*)
		echo '[m4-preview] invalid remote directory' >&2
		exit 64
		;;
esac
case "${remote_dir}" in
	*'/../'*|*'/./'*|*'//'*|*/..|*/.|*[!A-Za-z0-9._/-]*)
		echo '[m4-preview] invalid remote-directory characters' >&2
		exit 64
		;;
esac

cache_dir="$HOME/.cache/${project_name}"
lock_dir="${cache_dir}/operation.lock"
staging="${remote_dir}.incoming.${run_id}"
built_image_marker="${cache_dir}/built-image-input.sha256"
deployed_image_marker="${cache_dir}/deployed-image-input.sha256"
deployed_config_marker="${cache_dir}/deployed-config-input.sha256"
state_file="${cache_dir}/last-deploy.txt"
docker_config="${cache_dir}/docker-config"
frontend_volume_marker="${cache_dir}/frontend-volume-image.txt"
stack_touched=0
lock_acquired=0
prefetch_archive=""
package_proxy_pid=""
package_proxy_ready=""
package_proxy_port="18081"
pip_index_secret=""
pip_trusted_host_secret=""

cleanup_remote() {
	status=$?
	trap - EXIT INT TERM
	if [ -n "${package_proxy_pid}" ]; then
		kill "${package_proxy_pid}" >/dev/null 2>&1 || true
		wait "${package_proxy_pid}" >/dev/null 2>&1 || true
	fi
	rm -f "${source_bundle}"
	if [ -n "${prefetch_archive}" ]; then
		rm -f "${prefetch_archive}"
	fi
	for runtime_file in "${package_proxy_ready}" "${pip_index_secret}" "${pip_trusted_host_secret}"; do
		if [ -n "${runtime_file}" ]; then
			rm -f "${runtime_file}"
		fi
	done
	if [ -d "${staging}" ]; then
		find "${staging}" -depth -delete
	fi
	if [ "${lock_acquired}" = "1" ]; then
		rm -f "${lock_dir}/owner.txt"
		rmdir "${lock_dir}" >/dev/null 2>&1 || true
	fi
	if [ "${status}" -ne 0 ] && [ "${stack_touched}" = "1" ]; then
		for cleanup_service in api frontend proxy worker callback-worker ops-worker; do
			for container_id in $(
				docker ps -q \
					--filter "label=com.docker.compose.project=${project_name}" \
					--filter "label=com.docker.compose.service=${cleanup_service}"
			); do
				observed_project="$(
					docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' \
						"${container_id}" 2>/dev/null || true
				)"
				observed_service="$(
					docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' \
						"${container_id}" 2>/dev/null || true
				)"
				if [ "${observed_project}" = "${project_name}" ] &&
					[ "${observed_service}" = "${cleanup_service}" ]; then
					docker stop "${container_id}" >/dev/null 2>&1 || true
				fi
			done
		done
	fi
	exit "${status}"
}
trap cleanup_remote EXIT INT TERM

mkdir -p "${cache_dir}"
if ! mkdir "${lock_dir}" 2>/dev/null; then
	echo "[m4-preview] another operation holds ${lock_dir}" >&2
	if [ -f "${lock_dir}/owner.txt" ]; then
		cat "${lock_dir}/owner.txt" >&2
	fi
	exit 75
fi
lock_acquired=1
{
	printf 'pid=%s\n' "$$"
	printf 'run_id=%s\n' "${run_id}"
	printf 'started_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "${lock_dir}/owner.txt"

command -v docker >/dev/null
command -v rsync >/dev/null
command -v shasum >/dev/null

actual_sha="$(shasum -a 256 "${source_bundle}" | awk '{print $1}')"
if [ "${actual_sha}" != "${source_sha}" ]; then
	echo '[m4-preview] source bundle checksum mismatch' >&2
	exit 65
fi

test -d "${remote_dir}" || {
	echo "[m4-preview] remote directory missing: ${remote_dir}" >&2
	exit 66
}
test ! -L "${remote_dir}" || {
	echo "[m4-preview] remote directory must not be a symlink: ${remote_dir}" >&2
	exit 66
}
resolved_remote_dir="$(cd "${remote_dir}" && pwd -P)"
test "${resolved_remote_dir}" = "${remote_dir}" || {
	echo "[m4-preview] remote directory is not canonical: ${remote_dir}" >&2
	exit 66
}
test -f "${remote_dir}/.env" || {
	echo "[m4-preview] protected ${remote_dir}/.env is missing" >&2
	exit 66
}
test -f "${remote_dir}/.env.local" || {
	echo "[m4-preview] protected ${remote_dir}/.env.local is missing" >&2
	exit 66
}
chmod 600 "${remote_dir}/.env" "${remote_dir}/.env.local"

if [ -e "${staging}" ] || [ -L "${staging}" ]; then
	echo "[m4-preview] staging path already exists: ${staging}" >&2
	exit 66
fi
mkdir -p "${staging}"
tar -xzf "${source_bundle}" -C "${staging}"
test -f "${staging}/docker-compose.dev.yml"
test -f "${staging}/docker-compose.m4-preview.yml"
test -f "${staging}/deploy/nginx.m4-preview.conf"
test -f "${staging}/scripts/m4-package-proxy.py"
test -f "${staging}/scripts/redact-m4-preview-logs.py"

if [ "${mode}" = "sync" ]; then
	if [ ! -f "${built_image_marker}" ] ||
		[ "$(cat "${built_image_marker}")" != "${image_input_sha}" ] ||
		[ ! -f "${deployed_image_marker}" ] ||
		[ "$(cat "${deployed_image_marker}")" != "${image_input_sha}" ]; then
		echo '[m4-preview] dependency inputs require m4:preview:deploy' >&2
		exit 42
	fi
	if [ ! -f "${deployed_config_marker}" ] ||
		[ "$(cat "${deployed_config_marker}")" != "${config_input_sha}" ]; then
		echo '[m4-preview] Compose or proxy inputs require m4:preview:deploy' >&2
		exit 43
	fi
fi

if [ "${mode}" = "prepare" ]; then
	ln -s "${remote_dir}/.env" "${staging}/.env"
	ln -s "${remote_dir}/.env.local" "${staging}/.env.local"
	work_dir="${staging}"
else
	stack_touched=1
	rsync -a --delete \
		--exclude '.env' \
		--exclude '.env.local' \
		--exclude '.env.deploy' \
		--exclude '.git' \
		--exclude '.runtime' \
		--exclude '.venv' \
		--exclude '.pytest_cache' \
		--exclude '.mypy_cache' \
		--exclude '.ruff_cache' \
		--exclude '__pycache__' \
		--exclude 'build' \
		--exclude 'dist' \
		--exclude 'node_modules' \
		--exclude 'frontend/.next' \
		--exclude 'frontend/node_modules' \
		--exclude 'frontend/playwright-report' \
		--exclude 'frontend/test-results' \
		"${staging}/" "${remote_dir}/"
	work_dir="${remote_dir}"
fi

mkdir -p "${docker_config}"
if [ ! -e "${docker_config}/cli-plugins" ] && [ -d "$HOME/.docker/cli-plugins" ]; then
	ln -s "$HOME/.docker/cli-plugins" "${docker_config}/cli-plugins"
fi
if [ ! -f "${docker_config}/config.json" ]; then
	printf '{}\n' > "${docker_config}/config.json"
fi
export DOCKER_CONFIG="${docker_config}"
export COMPOSE_PARALLEL_LIMIT=1
export NPCINK_CLOUD_M4_PORT="${preview_port}"
export NPCINK_CLOUD_M4_POSTGRES_PORT="${postgres_port}"
export NPCINK_CLOUD_M4_REDIS_PORT="${redis_port}"

cd "${work_dir}"
compose=(
	docker compose
	-p "${project_name}"
	--env-file .env
	--env-file .env.local
	--profile runtime
	--profile callback
	--profile ops
	-f docker-compose.dev.yml
	-f docker-compose.m4-preview.yml
)

"${compose[@]}" config --quiet

runtime_image='npcink-ai-cloud-runtime:m4-dev'
frontend_image='npcink-ai-cloud-frontend:m4-dev'
python_base_image='npcink-ai-cloud-base-python:m4-pinned'
uv_base_image='npcink-ai-cloud-base-uv:m4-pinned'
node_base_image='npcink-ai-cloud-base-node:m4-current'
base_cache_dir="${cache_dir}/base-images"
mkdir -p "${base_cache_dir}/layers"
package_proxy_url=""

start_package_proxy() {
	package_proxy_ready="${cache_dir}/package-proxy-${run_id}.port"
	rm -f "${package_proxy_ready}"
	python3 scripts/m4-package-proxy.py \
		--bind 127.0.0.1 \
		--port "${package_proxy_port}" \
		--ready-file "${package_proxy_ready}" &
	package_proxy_pid=$!

	proxy_port=""
	for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
		if ! kill -0 "${package_proxy_pid}" 2>/dev/null; then
			echo '[m4-preview] M4 package proxy exited before readiness' >&2
			return 1
		fi
		if [ -s "${package_proxy_ready}" ]; then
			proxy_port="$(cat "${package_proxy_ready}")"
			if curl -fsS "http://127.0.0.1:${proxy_port}/health" >/dev/null; then
				break
			fi
		fi
		sleep 0.2
	done
	case "${proxy_port}" in
		''|*[!0-9]*)
			echo '[m4-preview] M4 package proxy did not publish a valid port' >&2
			return 1
			;;
	esac

	package_proxy_url="http://host.docker.internal:${proxy_port}"
	docker run --rm --pull never "${python_base_image}" \
		python -c \
		"import urllib.request; assert urllib.request.urlopen('${package_proxy_url}/health', timeout=5).status == 200"

	pip_index_secret="${cache_dir}/pip-index-${run_id}.txt"
	pip_trusted_host_secret="${cache_dir}/pip-trusted-host-${run_id}.txt"
	printf '%s\n' "${package_proxy_url}/pypi/simple/" > "${pip_index_secret}"
	printf '%s\n' 'host.docker.internal' > "${pip_trusted_host_secret}"
	chmod 600 "${pip_index_secret}" "${pip_trusted_host_secret}"
	echo "[m4-preview] loopback package proxy ready on M4 (${proxy_port})"
}

stop_package_proxy() {
	if [ -n "${package_proxy_pid}" ]; then
		kill "${package_proxy_pid}" >/dev/null 2>&1 || true
		wait "${package_proxy_pid}" >/dev/null 2>&1 || true
		package_proxy_pid=""
	fi
	for runtime_file in "${package_proxy_ready}" "${pip_index_secret}" "${pip_trusted_host_secret}"; do
		if [ -n "${runtime_file}" ]; then
			rm -f "${runtime_file}"
		fi
	done
	package_proxy_ready=""
	pip_index_secret=""
	pip_trusted_host_secret=""
}

prefetch_base_image() {
	remote_ref="$1"
	local_ref="$2"
	marker_name="$3"
	expected_digest="$4"
	marker_file="${base_cache_dir}/${marker_name}.txt"

	command -v crane >/dev/null 2>&1 || {
		echo '[m4-preview] crane is required on M4; install it with: HOMEBREW_NO_AUTO_UPDATE=1 brew install crane' >&2
		return 1
	}

	remote_digest="$(crane digest "${remote_ref}")"
	if [ -n "${expected_digest}" ] && [ "${remote_digest}" != "${expected_digest}" ]; then
		echo "[m4-preview] base-image digest mismatch: ${marker_name}" >&2
		return 1
	fi
	remote_config_digest="$(
		crane manifest --platform linux/arm64 "${remote_ref}" |
			python3 -c 'import json, sys; print(json.load(sys.stdin)["config"]["digest"])'
	)"

	local_descriptor_current=""
	if docker image inspect "${local_ref}" >/dev/null 2>&1; then
		local_descriptor_current="$(docker image inspect -f '{{.Id}}' "${local_ref}")"
	fi
	if [ -n "${local_descriptor_current}" ] &&
		[ -f "${marker_file}" ] &&
		grep -Fqx "remote_digest=${remote_digest}" "${marker_file}" &&
		grep -Fqx "local_descriptor=${local_descriptor_current}" "${marker_file}"; then
		echo "[m4-preview] base image cached: ${marker_name} (${remote_digest})"
		return 0
	fi

	prefetch_archive="$(mktemp "${base_cache_dir}/${marker_name}.XXXXXX")"
	echo "[m4-preview] prefetching base image on M4: ${marker_name} (${remote_digest})"
	crane pull \
		--platform linux/arm64 \
		--format tarball \
		--cache_path "${base_cache_dir}/layers" \
		"${remote_ref}" \
		"${prefetch_archive}" 2>&1 |
		python3 -u scripts/redact-m4-preview-logs.py --env-file .env --env-file .env.local
	archive_config_file="$(
		tar -xOf "${prefetch_archive}" manifest.json |
			python3 -c 'import json, sys; print(json.load(sys.stdin)[0]["Config"])'
	)"
	archive_config_digest="sha256:$(
		tar -xOf "${prefetch_archive}" "${archive_config_file}" |
			shasum -a 256 |
			awk '{print $1}'
	)"
	if [ "${archive_config_digest}" != "${remote_config_digest}" ]; then
		echo "[m4-preview] prefetched base-image config mismatch: ${marker_name}" >&2
		return 1
	fi

	docker load --input "${prefetch_archive}" 2>&1 |
		python3 -u scripts/redact-m4-preview-logs.py --env-file .env --env-file .env.local
	rm -f "${prefetch_archive}"
	prefetch_archive=""

	loaded_ref="${remote_ref}"
	if ! docker image inspect "${loaded_ref}" >/dev/null 2>&1; then
		without_digest="${remote_ref%@*}"
		repository="${without_digest%:*}"
		loaded_ref="${repository}:i-was-a-digest"
	fi
	test "$(docker image inspect -f '{{.Os}}/{{.Architecture}}' "${loaded_ref}")" = 'linux/arm64'
	docker tag "${loaded_ref}" "${local_ref}"
	local_descriptor="$(docker image inspect -f '{{.Id}}' "${local_ref}")"
	{
		printf 'remote_ref=%s\n' "${remote_ref}"
		printf 'remote_digest=%s\n' "${remote_digest}"
		printf 'config_digest=%s\n' "${remote_config_digest}"
		printf 'local_descriptor=%s\n' "${local_descriptor}"
	} > "${marker_file}"
	echo "[m4-preview] base image ready: ${marker_name} (${remote_digest})"
}

prefetch_base_images() {
	prefetch_base_image \
		'm.daocloud.io/docker.io/library/python:3.14-alpine@sha256:26730869004e2b9c4b9ad09cab8625e81d256d1ce97e72df5520e806b1709f92' \
		"${python_base_image}" \
		python \
		'sha256:26730869004e2b9c4b9ad09cab8625e81d256d1ce97e72df5520e806b1709f92'
	prefetch_base_image \
		'ghcr.nju.edu.cn/astral-sh/uv:0.11.29@sha256:eb2843a1e56fd9e30c7276ce1a52cba86e64c7b385f5e3279a0e08e02dd058fc' \
		"${uv_base_image}" \
		uv \
		'sha256:eb2843a1e56fd9e30c7276ce1a52cba86e64c7b385f5e3279a0e08e02dd058fc'
	prefetch_base_image \
		'm.daocloud.io/docker.io/library/node:22-alpine' \
		"${node_base_image}" \
		node \
		''
}

build_runtime_image() {
	first_line="$(sed -n '1p' Dockerfile)"
	case "${first_line}" in
		'# syntax=docker/dockerfile:'*)
			;;
		*)
			echo '[m4-preview] unexpected Dockerfile frontend declaration' >&2
			return 1
			;;
	esac
	grep -Fq 'FROM ghcr.io/astral-sh/uv:0.11.29@sha256:eb2843a1e56fd9e30c7276ce1a52cba86e64c7b385f5e3279a0e08e02dd058fc AS uv' Dockerfile
	grep -Fq 'FROM python:3.14-alpine@sha256:26730869004e2b9c4b9ad09cab8625e81d256d1ce97e72df5520e806b1709f92 AS builder' Dockerfile
	grep -Fq 'FROM python:3.14-alpine@sha256:26730869004e2b9c4b9ad09cab8625e81d256d1ce97e72df5520e806b1709f92 AS runtime' Dockerfile
	echo '[m4-preview] using verified M4-local base aliases; pinned source digests remain unchanged'
	tail -n +2 Dockerfile |
		sed \
			-e "s#ghcr.io/astral-sh/uv:0.11.29@sha256:eb2843a1e56fd9e30c7276ce1a52cba86e64c7b385f5e3279a0e08e02dd058fc#${uv_base_image}#" \
			-e "s#python:3.14-alpine@sha256:26730869004e2b9c4b9ad09cab8625e81d256d1ce97e72df5520e806b1709f92#${python_base_image}#" |
		docker build \
			--pull=false \
			--target development \
			--build-arg 'PACKAGE_EXTRAS=[dev,zilliz]' \
			--secret "id=pip_index_url,src=${pip_index_secret}" \
			--secret "id=pip_trusted_host,src=${pip_trusted_host_secret}" \
			--tag "${runtime_image}" \
			--file - \
		. 2>&1 |
		python3 -u scripts/redact-m4-preview-logs.py --env-file .env --env-file .env.local
}
build_frontend_image() {
	first_line="$(sed -n '1p' frontend/Dockerfile.dev)"
	test "${first_line}" = 'FROM node:22-alpine' || {
		echo '[m4-preview] unexpected frontend base-image declaration' >&2
		return 1
	}
	grep -Fqx 'RUN corepack enable && corepack install' frontend/Dockerfile.dev
	grep -Fqx 'RUN pnpm install --frozen-lockfile --filter frontend...' frontend/Dockerfile.dev
	{
		printf 'FROM %s\n' "${node_base_image}"
		printf 'ARG NPCINK_CLOUD_M4_NPM_REGISTRY\n'
		tail -n +2 frontend/Dockerfile.dev |
			awk '
				$0 == "RUN corepack enable && corepack install" {
					print "RUN corepack enable && COREPACK_NPM_REGISTRY=\"${NPCINK_CLOUD_M4_NPM_REGISTRY}\" corepack install"
					next
				}
				$0 == "RUN pnpm install --frozen-lockfile --filter frontend..." {
					print "RUN npm_config_registry=\"${NPCINK_CLOUD_M4_NPM_REGISTRY}\" pnpm install --frozen-lockfile --filter frontend..."
					next
				}
				{ print }
			'
	} |
		docker build \
			--pull=false \
			--build-arg "NPCINK_CLOUD_M4_NPM_REGISTRY=${package_proxy_url}/npm" \
			--tag "${frontend_image}" \
			--file - \
			. 2>&1 |
		python3 -u scripts/redact-m4-preview-logs.py --env-file .env --env-file .env.local
}
needs_build=0
if [ ! -f "${built_image_marker}" ] ||
	[ "$(cat "${built_image_marker}")" != "${image_input_sha}" ]; then
	needs_build=1
fi
if ! docker image inspect "${runtime_image}" >/dev/null 2>&1 ||
	! docker image inspect "${frontend_image}" >/dev/null 2>&1; then
	needs_build=1
fi

if [ "${mode}" = "sync" ]; then
	if [ "${needs_build}" = "1" ]; then
		echo '[m4-preview] dependency inputs changed; run m4:preview:deploy' >&2
		exit 42
	fi
	if [ ! -f "${deployed_image_marker}" ] ||
		[ "$(cat "${deployed_image_marker}")" != "${image_input_sha}" ]; then
		echo '[m4-preview] prepared image inputs are not deployed; run m4:preview:deploy' >&2
		exit 42
	fi
	if [ ! -f "${deployed_config_marker}" ] ||
		[ "$(cat "${deployed_config_marker}")" != "${config_input_sha}" ]; then
		echo '[m4-preview] Compose or proxy inputs changed; run m4:preview:deploy' >&2
		exit 43
	fi
else
	if [ "${needs_build}" = "1" ]; then
		prefetch_base_images
		start_package_proxy
		echo '[m4-preview] building runtime image on M4'
		build_runtime_image
		echo '[m4-preview] building frontend image on M4'
		build_frontend_image
		stop_package_proxy
		printf '%s\n' "${image_input_sha}" > "${built_image_marker}"
	fi
fi

refresh_frontend_dependency_volume() {
	current_frontend_descriptor="$(docker image inspect -f '{{.Id}}' "${frontend_image}")"
	previous_frontend_descriptor=""
	if [ -f "${frontend_volume_marker}" ]; then
		previous_frontend_descriptor="$(cat "${frontend_volume_marker}")"
	fi
	if [ "${current_frontend_descriptor}" = "${previous_frontend_descriptor}" ]; then
		return 0
	fi

	"${compose[@]}" stop frontend >/dev/null 2>&1 || true
	"${compose[@]}" rm -f frontend >/dev/null 2>&1 || true
	frontend_volume="${project_name}_cloud-frontend-node-modules-dev"
	if docker volume inspect "${frontend_volume}" >/dev/null 2>&1; then
		volume_project="$(
			docker volume inspect -f '{{index .Labels "com.docker.compose.project"}}' "${frontend_volume}"
		)"
		volume_key="$(
			docker volume inspect -f '{{index .Labels "com.docker.compose.volume"}}' "${frontend_volume}"
		)"
		test "${volume_project}" = "${project_name}"
		test "${volume_key}" = 'cloud-frontend-node-modules-dev'
		docker volume rm "${frontend_volume}" >/dev/null
	fi
	echo '[m4-preview] frontend dependency volume is ready for image copy-up'
}

if [ "${mode}" = "prepare" ]; then
	echo "[m4-preview] prepare complete: images and Compose config are ready; no containers were changed"
	stack_touched=0
	exit 0
elif [ "${mode}" = "deploy" ]; then
	refresh_frontend_dependency_volume
	"${compose[@]}" up -d --pull never postgres redis
	"${compose[@]}" run --interactive=false -T --rm --pull never api alembic upgrade head
	"${compose[@]}" up -d --no-build --pull never \
		postgres redis api frontend proxy worker callback-worker ops-worker
else
	"${compose[@]}" run --interactive=false -T --rm --no-deps api alembic upgrade head
	"${compose[@]}" restart worker callback-worker ops-worker
	proxy_id="$("${compose[@]}" ps -q proxy)"
	if [ -n "${proxy_id}" ]; then
		"${compose[@]}" exec --interactive=false -T proxy nginx -s reload >/dev/null 2>&1 ||
			"${compose[@]}" restart proxy
	fi
fi

wait_for_http() {
	url="$1"
	expected="$2"
	attempt=0
	while [ "${attempt}" -lt 60 ]; do
		code="$(curl -sS -o /dev/null -w '%{http_code}' "${url}" || true)"
		if [ "${code}" = "${expected}" ]; then
			return 0
		fi
		attempt=$((attempt + 1))
		sleep 2
	done
	echo "[m4-preview] ${url} did not return ${expected}" >&2
	return 1
}

wait_for_http "http://127.0.0.1:${preview_port}/health/live" 200
wait_for_http "http://127.0.0.1:${preview_port}/" 200

for service in postgres redis api frontend proxy worker callback-worker ops-worker; do
	container_id="$("${compose[@]}" ps -q "${service}")"
	test -n "${container_id}" || {
		echo "[m4-preview] missing service: ${service}" >&2
		exit 1
	}
	state="$(docker inspect -f '{{.State.Status}}' "${container_id}")"
	test "${state}" = "running" || {
		echo "[m4-preview] service is not running: ${service} (${state})" >&2
		exit 1
	}
	restart_policy="$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "${container_id}")"
	test "${restart_policy}" = "unless-stopped" || {
		echo "[m4-preview] invalid restart policy: ${service} (${restart_policy})" >&2
		exit 1
	}
done

verify_port() {
	service="$1"
	container_port="$2"
	expected="$3"
	container_id="$("${compose[@]}" ps -q "${service}")"
	actual="$(docker port "${container_id}" "${container_port}")"
	test "${actual}" = "${expected}" || {
		echo "[m4-preview] invalid ${service} binding: ${actual}" >&2
		exit 1
	}
}

verify_port proxy 8080/tcp "127.0.0.1:${preview_port}"
verify_port postgres 5432/tcp "127.0.0.1:${postgres_port}"
verify_port redis 6379/tcp "127.0.0.1:${redis_port}"

"${compose[@]}" exec --interactive=false -T proxy nginx -t >/dev/null
alembic_revision="$(
	"${compose[@]}" exec --interactive=false -T api alembic current 2>/dev/null |
		tail -n 1
)"
runtime_image_id="$(docker image inspect -f '{{.Id}}' "${runtime_image}")"
runtime_image_created="$(docker image inspect -f '{{.Created}}' "${runtime_image}")"
frontend_image_id="$(docker image inspect -f '{{.Id}}' "${frontend_image}")"
frontend_image_created="$(docker image inspect -f '{{.Created}}' "${frontend_image}")"
printf '%s\n' "$(docker image inspect -f '{{.Id}}' "${frontend_image}")" > "${frontend_volume_marker}"
printf '%s\n' "${image_input_sha}" > "${deployed_image_marker}"
printf '%s\n' "${config_input_sha}" > "${deployed_config_marker}"

{
	printf 'source_revision=%s\n' "${source_revision}"
	printf 'source_branch=%s\n' "${source_branch}"
	printf 'source_dirty=%s\n' "${source_dirty}"
	printf 'source_dirty_paths=%s\n' "${dirty_count}"
	printf 'source_bundle_sha256=%s\n' "${source_sha}"
	printf 'image_input_sha256=%s\n' "${image_input_sha}"
	printf 'config_input_sha256=%s\n' "${config_input_sha}"
	printf 'runtime_image_id=%s\n' "${runtime_image_id}"
	printf 'runtime_image_created=%s\n' "${runtime_image_created}"
	printf 'frontend_image_id=%s\n' "${frontend_image_id}"
	printf 'frontend_image_created=%s\n' "${frontend_image_created}"
	printf 'alembic_revision=%s\n' "${alembic_revision}"
	printf 'deployed_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "${state_file}"

"${compose[@]}" ps
stack_touched=0
REMOTE_APPLY
	REMOTE_SOURCE_BUNDLE=""
}

remote_status() {
	require_cmd ssh
	ssh "${SSH_ARGS[@]}" "${M4_SSH_HOST}" bash -s -- \
		"${M4_REMOTE_DIR}" \
		"${M4_PROJECT_NAME}" \
		"${M4_PORT}" \
		"${M4_POSTGRES_PORT}" \
		"${M4_REDIS_PORT}" <<'REMOTE_STATUS'
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

remote_dir="$1"
project_name="$2"
preview_port="$3"
postgres_port="$4"
redis_port="$5"
state_file="$HOME/.cache/${project_name}/last-deploy.txt"
docker_config="$HOME/.cache/${project_name}/docker-config"

test -d "${remote_dir}" || {
	echo "[m4-preview] remote directory is not initialized: ${remote_dir}" >&2
	exit 66
}
export DOCKER_CONFIG="${docker_config}"
export NPCINK_CLOUD_M4_PORT="${preview_port}"
export NPCINK_CLOUD_M4_POSTGRES_PORT="${postgres_port}"
export NPCINK_CLOUD_M4_REDIS_PORT="${redis_port}"
cd "${remote_dir}"
compose=(
	docker compose
	-p "${project_name}"
	--env-file .env
	--env-file .env.local
	--profile runtime
	--profile callback
	--profile ops
	-f docker-compose.dev.yml
	-f docker-compose.m4-preview.yml
)

echo '[m4-preview] deployment state'
if [ -f "${state_file}" ]; then
	cat "${state_file}"
else
	echo 'state=not_deployed'
fi

echo '[m4-preview] compose services'
"${compose[@]}" ps

echo '[m4-preview] container runtime'
for service in postgres redis api frontend proxy worker callback-worker ops-worker; do
	container_id="$("${compose[@]}" ps -a -q "${service}")"
	if [ -z "${container_id}" ]; then
		printf '%s|missing\n' "${service}"
		continue
	fi
	docker inspect "${container_id}" \
		--format "${service}|status={{.State.Status}}|health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|restart={{.HostConfig.RestartPolicy.Name}}|started={{.State.StartedAt}}|finished={{.State.FinishedAt}}"
done

echo '[m4-preview] published ports'
for service in proxy postgres redis; do
	container_id="$("${compose[@]}" ps -a -q "${service}")"
	if [ -n "${container_id}" ]; then
		docker port "${container_id}"
	fi
done

echo '[m4-preview] HTTP'
for endpoint in / /health/live /docs /health/ready /internal/health; do
	code="$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:${preview_port}${endpoint}" || true)"
	printf '%s=%s\n' "${endpoint}" "${code}"
done

api_id="$("${compose[@]}" ps -a -q api)"
if [ -n "${api_id}" ] &&
	[ "$(docker inspect -f '{{.State.Status}}' "${api_id}")" = "running" ]; then
	echo '[m4-preview] Alembic'
	"${compose[@]}" exec --interactive=false -T api alembic current
fi
REMOTE_STATUS
}

remote_logs() {
	local follow="$1"
	local tail_lines="$2"
	shift 2
	validate_services "$@"
	require_cmd ssh
	ssh "${SSH_ARGS[@]}" "${M4_SSH_HOST}" bash -s -- \
		"${M4_REMOTE_DIR}" \
		"${M4_PROJECT_NAME}" \
		"${M4_PORT}" \
		"${M4_POSTGRES_PORT}" \
		"${M4_REDIS_PORT}" \
		"${follow}" \
		"${tail_lines}" \
		"$@" <<'REMOTE_LOGS'
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
remote_dir="$1"
project_name="$2"
preview_port="$3"
postgres_port="$4"
redis_port="$5"
follow="$6"
tail_lines="$7"
shift 7
docker_config="$HOME/.cache/${project_name}/docker-config"
export DOCKER_CONFIG="${docker_config}"
export NPCINK_CLOUD_M4_PORT="${preview_port}"
export NPCINK_CLOUD_M4_POSTGRES_PORT="${postgres_port}"
export NPCINK_CLOUD_M4_REDIS_PORT="${redis_port}"
cd "${remote_dir}"
compose=(
	docker compose
	-p "${project_name}"
	--env-file .env
	--env-file .env.local
	--profile runtime
	--profile callback
	--profile ops
	-f docker-compose.dev.yml
	-f docker-compose.m4-preview.yml
)
log_args=(logs --no-color --tail "${tail_lines}")
if [ "${follow}" = "1" ]; then
	log_args+=(-f)
fi
"${compose[@]}" "${log_args[@]}" "$@" 2>&1 |
	python3 -u scripts/redact-m4-preview-logs.py --env-file .env --env-file .env.local
REMOTE_LOGS
}

remote_locked_operation() {
	local operation="$1"
	shift
	require_cmd ssh
	ssh "${SSH_ARGS[@]}" "${M4_SSH_HOST}" bash -s -- \
		"${M4_REMOTE_DIR}" \
		"${M4_PROJECT_NAME}" \
		"${M4_PORT}" \
		"${M4_POSTGRES_PORT}" \
		"${M4_REDIS_PORT}" \
		"${operation}" \
		"$@" <<'REMOTE_OPERATION'
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
remote_dir="$1"
project_name="$2"
preview_port="$3"
postgres_port="$4"
redis_port="$5"
operation="$6"
shift 6
cache_dir="$HOME/.cache/${project_name}"
lock_dir="${cache_dir}/operation.lock"
docker_config="${cache_dir}/docker-config"
mkdir -p "${cache_dir}"
if ! mkdir "${lock_dir}" 2>/dev/null; then
	echo "[m4-preview] another operation holds ${lock_dir}" >&2
	exit 75
fi
trap 'rmdir "${lock_dir}" >/dev/null 2>&1 || true' EXIT INT TERM
export DOCKER_CONFIG="${docker_config}"
export NPCINK_CLOUD_M4_PORT="${preview_port}"
export NPCINK_CLOUD_M4_POSTGRES_PORT="${postgres_port}"
export NPCINK_CLOUD_M4_REDIS_PORT="${redis_port}"
cd "${remote_dir}"
compose=(
	docker compose
	-p "${project_name}"
	--env-file .env
	--env-file .env.local
	--profile runtime
	--profile callback
	--profile ops
	-f docker-compose.dev.yml
	-f docker-compose.m4-preview.yml
)

case "${operation}" in
	test)
		echo '[m4-preview] equivalent_gate=pnpm run check:fast'
		test_runner='
import os
import sys

import pytest

for key in tuple(os.environ):
    if key.startswith("NPCINK_CLOUD_"):
        os.environ.pop(key, None)

raise SystemExit(pytest.main(sys.argv[1:]))
'
		"${compose[@]}" run --interactive=false -T --rm --no-deps \
			api python -c "${test_runner}" tests/contract
		"${compose[@]}" run --interactive=false -T --rm --no-deps \
			api python -c "${test_runner}" tests/domain
		;;
	recover)
		all_services=(postgres redis api frontend proxy worker callback-worker ops-worker)
		for service in "${all_services[@]}"; do
			container_id="$("${compose[@]}" ps -a -q "${service}")"
			[ -n "${container_id}" ] || {
				echo "[m4-preview] recovery requires existing container: ${service}; run m4:preview:deploy" >&2
				exit 66
			}
		done

		"${compose[@]}" start postgres redis
		for service in postgres redis; do
			attempt=0
			while [ "${attempt}" -lt 60 ]; do
				container_id="$("${compose[@]}" ps -a -q "${service}")"
				state="$(docker inspect -f '{{.State.Status}}' "${container_id}")"
				health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${container_id}")"
				if [ "${state}" = "running" ] && [ "${health}" = "healthy" ]; then
					break
				fi
				attempt=$((attempt + 1))
				sleep 2
			done
			[ "${attempt}" -lt 60 ] || {
				echo "[m4-preview] recovery timed out waiting for ${service}" >&2
				exit 1
			}
		done

		"${compose[@]}" start api frontend proxy worker callback-worker ops-worker
		for endpoint in /health/live /; do
			attempt=0
			while [ "${attempt}" -lt 60 ]; do
				code="$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:${preview_port}${endpoint}" || true)"
				if [ "${code}" = "200" ]; then
					break
				fi
				attempt=$((attempt + 1))
				sleep 2
			done
			[ "${attempt}" -lt 60 ] || {
				echo "[m4-preview] recovery timed out waiting for ${endpoint}" >&2
				exit 1
			}
		done

		for service in "${all_services[@]}"; do
			container_id="$("${compose[@]}" ps -a -q "${service}")"
			state="$(docker inspect -f '{{.State.Status}}' "${container_id}")"
			restart_policy="$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "${container_id}")"
			[ "${state}" = "running" ] || {
				echo "[m4-preview] recovery left ${service} in ${state}" >&2
				exit 1
			}
			[ "${restart_policy}" = "unless-stopped" ] || {
				echo "[m4-preview] recovery found invalid restart policy for ${service}: ${restart_policy}" >&2
				exit 1
			}
		done
		echo '[m4-preview] recovery complete'
		"${compose[@]}" ps
		;;
	restart)
		[ "$#" -gt 0 ] || {
			echo '[m4-preview] restart requires at least one service' >&2
			exit 64
		}
		"${compose[@]}" restart "$@"
		"${compose[@]}" ps "$@"
		;;
	stop)
		"${compose[@]}" stop
		"${compose[@]}" ps
		;;
	*)
		echo "[m4-preview] unsupported operation: ${operation}" >&2
		exit 64
		;;
esac
REMOTE_OPERATION
}

main() {
	validate_target
	local command="${1:-}"
	if [ -z "${command}" ]; then
		usage
		exit 64
	fi
	shift

	case "${command}" in
		--help|-h|help)
			usage
			;;
		prepare|deploy|sync)
			parse_dry_run "$@"
			upload_and_apply "${command}"
			;;
		status)
			[ "$#" -eq 0 ] || fail "status does not accept arguments"
			remote_status
			;;
		logs)
			local follow=0
			local tail_lines=200
			local services=()
			while [ "$#" -gt 0 ]; do
				case "$1" in
					--)
						shift
						;;
					--follow|-f)
						follow=1
						shift
						;;
					--tail)
						[ "$#" -ge 2 ] || fail "--tail requires a value"
						tail_lines="$2"
						shift 2
						;;
					*)
						services+=("$1")
						shift
						;;
				esac
			done
			validate_number "tail lines" "${tail_lines}"
			remote_logs "${follow}" "${tail_lines}" "${services[@]}"
			;;
		test)
			[ "$#" -eq 0 ] || fail "test does not accept arguments"
			remote_locked_operation test
			;;
		recover)
			[ "$#" -eq 0 ] || fail "recover does not accept arguments"
			remote_locked_operation recover
			;;
		restart)
			if [ "${1:-}" = "--" ]; then
				shift
			fi
			validate_services "$@"
			remote_locked_operation restart "$@"
			;;
		stop)
			[ "$#" -eq 0 ] || fail "stop does not accept arguments"
			remote_locked_operation stop
			;;
		*)
			fail "unknown command: ${command}"
			;;
	esac
}

main "$@"
