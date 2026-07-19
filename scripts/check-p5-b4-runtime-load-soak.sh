#!/usr/bin/env bash
set -euo pipefail

umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.p5-b4-runtime-proof.yml"
HARNESS_FILE="${ROOT_DIR}/scripts/p5_b4_runtime_load_soak.py"
WRAPPER_FILE="${ROOT_DIR}/scripts/check-p5-b4-runtime-load-soak.sh"
MIGRATIONS_DIR="${ROOT_DIR}/migrations"
DISPOSABLE_CONFIRMATION="I_UNDERSTAND_THIS_DESTROYS_PROOF_DATA"
DATASET_ID="p5_b4_runtime_8_sites_v5"
DATASET_CONFIG='{"commercial":{"max_ai_credits_per_site_period":10000.0},"contract":"p5_b4_runtime_dataset.v5","formal":{"baselines":3,"concurrency":8,"queue_burst":64,"request_rate":8,"resource_idle_minimum_sample_count":12,"resource_idle_minimum_span_seconds":55,"resource_idle_recovery_seconds":60,"resource_process_scope":"pid1_service_trees_aggregate_stable_cohort_v3","rss_endpoint_window_min_span_seconds":55,"rss_endpoint_window_sample_count":12,"rss_growth_method":"steady_endpoint_window_median_v1","rss_growth_percent_max":10,"rss_idle_method":"four_block_budget_confirmation_v1","soak_seconds":600,"warmup_seconds":30},"provider_delay_ms":150,"quick":{"baselines":1,"concurrency":2,"queue_burst":8,"request_rate":2,"soak_seconds":5,"warmup_seconds":3},"sites":8,"worker":{"batch_size":8,"poll_seconds":5,"replicas":2}}'

MODE=""
OUTPUT_ARGUMENT=""
CONFIRMED=0
EVIDENCE_DIR=""
CURRENT_PROJECT=""
SAMPLER_PID=""
SAMPLER_STOP_FILE=""
P5_B4_PROOF_IMAGE=""
P5_B4_PROOF_IMAGE_ID=""
CLEANUP_COMPLETE=0
DOCKER_CLEANUP_REQUIRED=0
BASELINE_TOPOLOGY=""
PROJECTS=()

usage() {
	printf '%s\n' \
		'Usage:' \
		'  scripts/check-p5-b4-runtime-load-soak.sh --confirm-disposable --quick --output FILE' \
		'  scripts/check-p5-b4-runtime-load-soak.sh --confirm-disposable --formal --output FILE' \
		'' \
		'Quick is one reduced fresh baseline and can never be acceptance evidence.' \
		'Formal is exactly three independent fresh 30s warmup + 600s soak baselines.'
}

fail() {
	printf 'P5-B4 runtime proof: %s\n' "$1" >&2
	return 1
}

canonicalize_path() {
	local candidate="$1"

	python3 -c '
from pathlib import Path
import sys

print(Path(sys.argv[1]).resolve(strict=False))
' "${candidate}"
}

canonicalize_existing_directory() {
	local candidate="$1"

	[ -d "${candidate}" ] || return 1
	(
		cd "${candidate}" || exit 1
		pwd -P
	)
}

path_is_equal_or_within() {
	local candidate="$1"
	local protected_root="$2"

	case "${candidate}" in
	"${protected_root}"|"${protected_root}"/*)
		return 0
		;;
	*)
		return 1
		;;
	esac
}

sha256_stream() {
	if command -v shasum >/dev/null 2>&1; then
		shasum -a 256 | awk '{print $1}'
	elif command -v sha256sum >/dev/null 2>&1; then
		sha256sum | awk '{print $1}'
	else
		fail 'neither shasum nor sha256sum is available'
	fi
}

sha256_file() {
	if command -v shasum >/dev/null 2>&1; then
		shasum -a 256 "$1" | awk '{print $1}'
	elif command -v sha256sum >/dev/null 2>&1; then
		sha256sum "$1" | awk '{print $1}'
	else
		fail 'neither shasum nor sha256sum is available'
	fi
}

migration_manifest_sha256() {
	local migration_files=""
	local migration_file=""
	local migration_hash=""
	local manifest=""

	if ! migration_files="$(
		find "${MIGRATIONS_DIR}" -type f -name '*.py' -print | LC_ALL=C sort
	)"; then
		return 1
	fi
	[ -n "${migration_files}" ] || return 1
	while IFS= read -r migration_file; do
		[ -f "${migration_file}" ] || return 1
		if ! migration_hash="$(sha256_file "${migration_file}")"; then
			return 1
		fi
		[[ "${migration_hash}" =~ ^[0-9a-f]{64}$ ]] || return 1
		printf -v manifest '%s%s\t%s\n' \
			"${manifest}" "${migration_file#${ROOT_DIR}/}" "${migration_hash}" || \
			return 1
	done <<EOF
${migration_files}
EOF
	printf '%s' "${manifest}" | sha256_stream
}

verify_source_snapshot() {
	local current_revision=""
	local current_git_status=""
	local current_git_status_sha256=""
	local current_harness_sha256=""
	local current_compose_sha256=""
	local current_wrapper_sha256=""
	local current_migration_manifest_sha256=""
	local final_revision=""
	local final_git_status=""

	if ! current_revision="$(git rev-parse HEAD)"; then
		return 1
	fi
	if ! current_git_status="$(git status --porcelain=v1 --untracked-files=all)"; then
		return 1
	fi
	if ! current_git_status_sha256="$(
		printf '%s' "${current_git_status}" | sha256_stream
	)"; then
		return 1
	fi
	if ! current_harness_sha256="$(sha256_file "${HARNESS_FILE}")"; then
		return 1
	fi
	if ! current_compose_sha256="$(sha256_file "${COMPOSE_FILE}")"; then
		return 1
	fi
	if ! current_wrapper_sha256="$(sha256_file "${WRAPPER_FILE}")"; then
		return 1
	fi
	if ! current_migration_manifest_sha256="$(migration_manifest_sha256)"; then
		return 1
	fi
	if ! final_revision="$(git rev-parse HEAD)"; then
		return 1
	fi
	if ! final_git_status="$(git status --porcelain=v1 --untracked-files=all)"; then
		return 1
	fi

	[ "${current_revision}" = "${P5_B4_REVISION}" ] || return 1
	[ "${final_revision}" = "${P5_B4_REVISION}" ] || return 1
	[ "${current_git_status}" = "${GIT_STATUS}" ] || return 1
	[ "${final_git_status}" = "${GIT_STATUS}" ] || return 1
	[ "${current_git_status_sha256}" = "${P5_B4_GIT_STATUS_SHA256}" ] || return 1
	[ "${current_harness_sha256}" = "${P5_B4_HARNESS_SHA256}" ] || return 1
	[ "${current_compose_sha256}" = "${P5_B4_COMPOSE_SHA256}" ] || return 1
	[ "${current_wrapper_sha256}" = "${P5_B4_WRAPPER_SHA256}" ] || return 1
	[ "${current_migration_manifest_sha256}" = \
		"${P5_B4_MIGRATION_MANIFEST_SHA256}" ] || return 1
	return 0
}

require_source_snapshot() {
	local checkpoint="$1"

	if ! verify_source_snapshot; then
		printf 'P5-B4 source snapshot drift or probe failure at: %s\n' \
			"${checkpoint}" >&2
		return 1
	fi
	return 0
}

publish_output() {
	local output_file="$1"
	python3 -c '
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

target = Path(sys.argv[1])
descriptor, temporary_name = tempfile.mkstemp(
    dir=str(target.parent),
    prefix=f".{target.name}.",
    suffix=".tmp",
)
try:
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(sys.stdin.buffer.read())
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary_name, 0o600)
    os.replace(temporary_name, target)
    directory = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
except BaseException:
    try:
        os.unlink(temporary_name)
    except FileNotFoundError:
        pass
    raise
' "${output_file}"
}

verify_project_absent() {
	local project="$1"
	local leftovers=""

	if ! leftovers="$(
		docker ps --all --quiet --filter "label=com.docker.compose.project=${project}"
	)"; then
		printf 'P5-B4 cleanup container probe failed: %s\n' "${project}" >&2
		return 1
	fi
	[ -z "${leftovers}" ] || return 1
	if ! leftovers="$(
		docker volume ls --quiet --filter "label=com.docker.compose.project=${project}"
	)"; then
		printf 'P5-B4 cleanup volume probe failed: %s\n' "${project}" >&2
		return 1
	fi
	[ -z "${leftovers}" ] || return 1
	if ! leftovers="$(
		docker network ls --quiet --filter "label=com.docker.compose.project=${project}"
	)"; then
		printf 'P5-B4 cleanup network probe failed: %s\n' "${project}" >&2
		return 1
	fi
	[ -z "${leftovers}" ] || return 1
	return 0
}

cleanup_project() {
	local project="$1"
	local status=0

	if ! COMPOSE_PROJECT_NAME="${project}" docker compose \
		-f "${COMPOSE_FILE}" --profile proof down \
		--volumes --remove-orphans --timeout 20 >&2; then
		status=1
	fi
	if ! verify_project_absent "${project}"; then
		printf 'P5-B4 cleanup left project resources: %s\n' "${project}" >&2
		status=1
	fi
	return "${status}"
}

remove_proof_image() {
	local status=0
	local all_image_ids=""
	local leftovers=""
	local leftover_image=""

	if ! all_image_ids="$(docker image ls --all --quiet --no-trunc)"; then
		printf 'P5-B4 cleanup image inventory probe failed\n' >&2
		status=1
	elif [ -n "${P5_B4_PROOF_IMAGE_ID}" ] && \
		image_id_present "${all_image_ids}" "${P5_B4_PROOF_IMAGE_ID}"; then
		if ! docker image rm "${P5_B4_PROOF_IMAGE_ID}" >&2; then
			status=1
		fi
	fi
	if ! all_image_ids="$(docker image ls --all --quiet --no-trunc)"; then
		printf 'P5-B4 cleanup image verification probe failed\n' >&2
		status=1
	elif [ -n "${P5_B4_PROOF_IMAGE_ID}" ] && \
		image_id_present "${all_image_ids}" "${P5_B4_PROOF_IMAGE_ID}"; then
		status=1
	fi
	if [ -n "${RUN_TOKEN:-}" ]; then
		if ! leftovers="$(docker image ls --all --quiet --no-trunc \
			--filter "label=org.npcink.p5-b4-proof-run=${RUN_TOKEN}")"; then
			printf 'P5-B4 cleanup task image probe failed\n' >&2
			status=1
		elif [ -n "${leftovers}" ]; then
			for leftover_image in ${leftovers}; do
				docker image rm "${leftover_image}" >&2 || status=1
			done
		fi
		if ! leftovers="$(docker image ls --all --quiet --no-trunc \
			--filter "label=org.npcink.p5-b4-proof-run=${RUN_TOKEN}")"; then
			printf 'P5-B4 cleanup task image verification probe failed\n' >&2
			status=1
		elif [ -n "${leftovers}" ]; then
			printf 'P5-B4 cleanup left task-owned image resources\n' >&2
			status=1
		fi
	fi
	return "${status}"
}

image_id_present() {
	local image_ids="$1"
	local expected_image_id="$2"
	local image_id=""

	while IFS= read -r image_id; do
		[ "${image_id}" = "${expected_image_id}" ] && return 0
	done <<EOF
${image_ids}
EOF
	return 1
}

sampler_job_is_active() {
	local sampler_pid="$1"
	local active_jobs=""
	local active_pid=""

	if ! active_jobs="$({ jobs -pr; jobs -ps; })"; then
		return 1
	fi
	while IFS= read -r active_pid; do
		[ "${active_pid}" = "${sampler_pid}" ] && return 0
	done <<EOF
${active_jobs}
EOF
	return 1
}

wait_for_sampler_exit() {
	local sampler_pid="$1"
	local maximum_attempts="$2"
	local attempts=0

	while [ "${attempts}" -lt "${maximum_attempts}" ]; do
		if ! sampler_job_is_active "${sampler_pid}"; then
			return 0
		fi
		sleep 0.1 || return 1
		attempts=$((attempts + 1))
	done
	! sampler_job_is_active "${sampler_pid}"
}

stop_sampler() {
	local status=0
	local sampler_pid="${SAMPLER_PID}"

	if [ -n "${sampler_pid}" ]; then
		if [ -z "${SAMPLER_STOP_FILE}" ] || ! : >"${SAMPLER_STOP_FILE}"; then
			printf 'P5-B4 sampler stop signal could not be created\n' >&2
			status=1
		fi
		if ! wait_for_sampler_exit "${sampler_pid}" 150; then
			printf 'P5-B4 sampler did not stop within 15 seconds; sending TERM\n' >&2
			status=1
			if sampler_job_is_active "${sampler_pid}"; then
				kill -TERM "${sampler_pid}" 2>/dev/null || status=1
			fi
			if ! wait_for_sampler_exit "${sampler_pid}" 50; then
				printf 'P5-B4 sampler ignored TERM; sending KILL\n' >&2
				status=1
				if sampler_job_is_active "${sampler_pid}"; then
					kill -KILL "${sampler_pid}" 2>/dev/null || status=1
				fi
				wait_for_sampler_exit "${sampler_pid}" 20 || status=1
			fi
		fi
		if sampler_job_is_active "${sampler_pid}"; then
			printf 'P5-B4 sampler could not be terminated within the bounded wait\n' >&2
			status=1
		else
			if ! wait "${sampler_pid}"; then
				status=1
			fi
			SAMPLER_PID=""
			SAMPLER_STOP_FILE=""
		fi
	fi
	return "${status}"
}

on_exit() {
	local original_status=$?
	local cleanup_status=0
	local project=""

	trap - EXIT INT TERM
	if [ "${CLEANUP_COMPLETE}" -ne 1 ]; then
		set +e
		stop_sampler || cleanup_status=1
		if [ "${DOCKER_CLEANUP_REQUIRED}" -eq 1 ]; then
			for project in "${PROJECTS[@]-}"; do
				[ -n "${project}" ] || continue
				cleanup_project "${project}" || cleanup_status=1
			done
			remove_proof_image || cleanup_status=1
		fi
		if [ -n "${EVIDENCE_DIR}" ] && [ -d "${EVIDENCE_DIR}" ]; then
			rm -rf -- "${EVIDENCE_DIR}" || cleanup_status=1
		fi
		set -e
	fi
	if [ "${cleanup_status}" -ne 0 ]; then
		printf 'P5-B4 emergency cleanup failed; no evidence was published.\n' >&2
		exit 1
	fi
	exit "${original_status}"
}

handle_interrupt() {
	exit 130
}

handle_terminate() {
	exit 143
}

trap on_exit EXIT
trap handle_interrupt INT
trap handle_terminate TERM

while [ "$#" -gt 0 ]; do
	case "$1" in
		--confirm-disposable)
			CONFIRMED=1
			shift
			;;
		--quick)
			[ -z "${MODE}" ] || fail 'choose exactly one of --quick or --formal'
			MODE="quick"
			shift
			;;
		--formal)
			[ -z "${MODE}" ] || fail 'choose exactly one of --quick or --formal'
			MODE="formal"
			shift
			;;
		--output)
			[ "$#" -ge 2 ] || fail '--output requires a file path'
			OUTPUT_ARGUMENT="$2"
			shift 2
			;;
		--help|-h)
			usage
			CLEANUP_COMPLETE=1
			exit 0
			;;
		*)
			usage >&2
			fail "unknown argument: $1"
			;;
	esac
done

[ "${CONFIRMED}" -eq 1 ] || fail '--confirm-disposable is required'
[ -n "${MODE}" ] || fail 'choose exactly one of --quick or --formal'
[ -n "${OUTPUT_ARGUMENT}" ] || fail '--output FILE is required'
[ -f "${COMPOSE_FILE}" ] || fail 'runtime proof Compose file is missing'
[ -f "${HARNESS_FILE}" ] || fail 'runtime proof harness is missing'
command -v python3 >/dev/null 2>&1 || fail 'python3 is required'
cd "${ROOT_DIR}" || fail 'repository root is unavailable'

if ! OUTPUT_PARENT="$(dirname -- "${OUTPUT_ARGUMENT}")"; then
	fail 'output parent path could not be derived'
fi
[ -d "${OUTPUT_PARENT}" ] || fail 'output parent directory must already exist'
if ! OUTPUT_PARENT="$(canonicalize_existing_directory "${OUTPUT_PARENT}")"; then
	fail 'output parent directory could not be canonicalized'
fi
if ! OUTPUT_BASENAME="$(basename -- "${OUTPUT_ARGUMENT}")"; then
	fail 'output filename could not be derived'
fi
OUTPUT_CANDIDATE="${OUTPUT_PARENT}/${OUTPUT_BASENAME}"
[ ! -L "${OUTPUT_CANDIDATE}" ] || fail 'output path must not be a symbolic link'
if ! OUTPUT_PATH="$(canonicalize_path "${OUTPUT_CANDIDATE}")"; then
	fail 'output path could not be canonicalized'
fi
[ -n "${OUTPUT_PATH}" ] || fail 'canonical output path is empty'
if [ -e "${OUTPUT_PATH}" ] && [ ! -f "${OUTPUT_PATH}" ]; then
	fail 'existing output path must be a regular file'
fi

if ! WORKTREE_GIT_DIR_RAW="$(git rev-parse --absolute-git-dir)"; then
	fail 'worktree git-dir probe failed'
fi
if ! GIT_COMMON_DIR_RAW="$(git rev-parse --git-common-dir)"; then
	fail 'git common-dir probe failed'
fi
if ! WORKTREE_GIT_DIR="$(
	canonicalize_existing_directory "${WORKTREE_GIT_DIR_RAW}"
)"; then
	fail 'worktree git-dir could not be canonicalized'
fi
if ! GIT_COMMON_DIR="$(canonicalize_existing_directory "${GIT_COMMON_DIR_RAW}")"; then
	fail 'git common-dir could not be canonicalized'
fi

if path_is_equal_or_within "${OUTPUT_PATH}" "${ROOT_DIR}"; then
	fail 'output path must be outside the repository worktree'
fi
if path_is_equal_or_within "${OUTPUT_PATH}" "${WORKTREE_GIT_DIR}"; then
	fail 'output path must be outside the worktree git-dir'
fi
if path_is_equal_or_within "${OUTPUT_PATH}" "${GIT_COMMON_DIR}"; then
	fail 'output path must be outside the git common-dir'
fi

command -v docker >/dev/null 2>&1 || fail 'docker is required'
docker info >/dev/null 2>&1 || fail 'Docker is unavailable'

if ! P5_B4_REVISION="$(git rev-parse HEAD)"; then
	fail 'source revision probe failed'
fi
if ! GIT_STATUS="$(git status --porcelain=v1 --untracked-files=all)"; then
	fail 'source status probe failed'
fi
if [ -n "${GIT_STATUS}" ]; then
	P5_B4_GIT_DIRTY="true"
	if ! P5_B4_GIT_DIRTY_COUNT="$(
		printf '%s\n' "${GIT_STATUS}" | awk 'NF {count += 1} END {print count + 0}'
	)"; then
		fail 'source dirty-count probe failed'
	fi
else
	P5_B4_GIT_DIRTY="false"
	P5_B4_GIT_DIRTY_COUNT="0"
fi
if ! P5_B4_GIT_STATUS_SHA256="$(
	printf '%s' "${GIT_STATUS}" | sha256_stream
)"; then
	fail 'source status hash failed'
fi
[[ "${P5_B4_REVISION}" =~ ^[0-9a-f]{40}$ ]] || fail 'source revision is invalid'
[[ "${P5_B4_GIT_DIRTY_COUNT}" =~ ^[0-9]+$ ]] || fail 'source dirty-count is invalid'
[[ "${P5_B4_GIT_STATUS_SHA256}" =~ ^[0-9a-f]{64}$ ]] || \
	fail 'source status hash is invalid'
if [ "${MODE}" = "formal" ] && [ "${P5_B4_GIT_DIRTY}" != "false" ]; then
	fail 'formal mode requires a fully clean tracked, staged, and untracked tree'
fi

if ! P5_B4_HARNESS_SHA256="$(sha256_file "${HARNESS_FILE}")"; then
	fail 'runtime proof harness hash failed'
fi
if ! P5_B4_COMPOSE_SHA256="$(sha256_file "${COMPOSE_FILE}")"; then
	fail 'runtime proof Compose hash failed'
fi
if ! P5_B4_WRAPPER_SHA256="$(sha256_file "${WRAPPER_FILE}")"; then
	fail 'runtime proof wrapper hash failed'
fi
P5_B4_DATASET_CONFIG="${DATASET_CONFIG}"
if ! P5_B4_DATASET_SHA256="$(
	printf '%s' "${P5_B4_DATASET_CONFIG}" | sha256_stream
)"; then
	fail 'runtime proof dataset hash failed'
fi
if ! P5_B4_MIGRATION_MANIFEST_SHA256="$(migration_manifest_sha256)"; then
	fail 'migration manifest hash failed'
fi
for source_hash in \
	"${P5_B4_HARNESS_SHA256}" "${P5_B4_COMPOSE_SHA256}" \
	"${P5_B4_WRAPPER_SHA256}" "${P5_B4_DATASET_SHA256}" \
	"${P5_B4_MIGRATION_MANIFEST_SHA256}"; do
	[[ "${source_hash}" =~ ^[0-9a-f]{64}$ ]] || fail 'source snapshot hash is invalid'
done
require_source_snapshot 'initial lock' || fail 'initial source snapshot verification failed'

printf 'P5-B4: resolving exact PostgreSQL 16 and Redis 7 proof images.\n' >&2
docker pull postgres:16-alpine >&2
docker pull redis:7-alpine >&2
P5_B4_POSTGRES_IMAGE_ID="$(docker image inspect postgres:16-alpine --format '{{.Id}}')"
P5_B4_REDIS_IMAGE_ID="$(docker image inspect redis:7-alpine --format '{{.Id}}')"
P5_B4_POSTGRES_IMAGE_REF="${P5_B4_POSTGRES_IMAGE_ID}"
P5_B4_REDIS_IMAGE_REF="${P5_B4_REDIS_IMAGE_ID}"

P5_B4_DOCKER_ARCH="$(docker version --format '{{.Server.Arch}}')"
P5_B4_DOCKER_CPU_COUNT="$(docker info --format '{{.NCPU}}')"
P5_B4_DOCKER_MEMORY_BYTES="$(docker info --format '{{.MemTotal}}')"
P5_B4_DOCKER_SERVER_VERSION="$(docker version --format '{{.Server.Version}}')"
P5_B4_DOCKER_COMPOSE_VERSION="$(docker compose version --short)"
P5_B4_DOCKER_BACKGROUND_CONTAINER_COUNT="$(docker ps --quiet | awk 'NF {count += 1} END {print count + 0}')"
P5_B4_ENVIRONMENT_FINGERPRINT="$(printf '%s\n' \
	"${P5_B4_DOCKER_ARCH}" \
	"${P5_B4_DOCKER_CPU_COUNT}" \
	"${P5_B4_DOCKER_MEMORY_BYTES}" \
	"${P5_B4_DOCKER_SERVER_VERSION}" \
	"${P5_B4_DOCKER_COMPOSE_VERSION}" \
	"${P5_B4_DOCKER_BACKGROUND_CONTAINER_COUNT}" \
	"${P5_B4_POSTGRES_IMAGE_ID}" \
	"${P5_B4_REDIS_IMAGE_ID}" | sha256_stream)"

RUN_TOKEN="$(date -u +%Y%m%d%H%M%S)_${RANDOM:-0}_$$"
P5_B4_PROOF_IMAGE="npcink-p5-b4-runtime-proof:${RUN_TOKEN}"
EVIDENCE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/npcink-p5-b4-runtime.XXXXXX")"
P5_B4_RUNNER_UID="$(id -u)"
P5_B4_RUNNER_GID="$(id -g)"
P5_B4_EVIDENCE_DIR="${EVIDENCE_DIR}"
P5_B4_DATASET_ID="${DATASET_ID}"

export P5_B4_PROOF_IMAGE P5_B4_EVIDENCE_DIR P5_B4_RUNNER_UID P5_B4_RUNNER_GID
export P5_B4_REVISION P5_B4_HARNESS_SHA256 P5_B4_COMPOSE_SHA256 P5_B4_WRAPPER_SHA256
export P5_B4_MIGRATION_MANIFEST_SHA256 P5_B4_ENVIRONMENT_FINGERPRINT
export P5_B4_DATASET_ID P5_B4_DATASET_CONFIG P5_B4_DATASET_SHA256
export P5_B4_GIT_DIRTY P5_B4_GIT_DIRTY_COUNT P5_B4_GIT_STATUS_SHA256
export P5_B4_POSTGRES_IMAGE_ID P5_B4_REDIS_IMAGE_ID
export P5_B4_POSTGRES_IMAGE_REF P5_B4_REDIS_IMAGE_REF
export P5_B4_DOCKER_ARCH P5_B4_DOCKER_CPU_COUNT P5_B4_DOCKER_MEMORY_BYTES
export P5_B4_DOCKER_SERVER_VERSION P5_B4_DOCKER_COMPOSE_VERSION
export P5_B4_DOCKER_BACKGROUND_CONTAINER_COUNT
export P5_B4_QUICK_DURATION_SECONDS=5
export P5_B4_QUICK_WARMUP_SECONDS=3
export P5_B4_QUICK_CONCURRENCY=2
export P5_B4_QUICK_REQUEST_RATE=2
export P5_B4_QUICK_QUEUE_BURST=8

printf 'P5-B4: building one disposable proof image (mode=%s).\n' "${MODE}" >&2
DOCKER_CLEANUP_REQUIRED=1
docker build \
	--label "org.npcink.p5-b4-proof-run=${RUN_TOKEN}" \
	--tag "${P5_B4_PROOF_IMAGE}" \
	"${ROOT_DIR}" >&2
P5_B4_PROOF_IMAGE_ID="$(docker image inspect "${P5_B4_PROOF_IMAGE}" --format '{{.Id}}')"
export P5_B4_PROOF_IMAGE_ID
require_source_snapshot 'after proof image build' || \
	fail 'source snapshot changed while building the proof image'

MIGRATION_HEADS="$({
	docker run --rm --network none --read-only --tmpfs /tmp:size=16m \
		--label "org.npcink.p5-b4-proof-run=${RUN_TOKEN}" \
		"${P5_B4_PROOF_IMAGE}" alembic heads
} 2>/dev/null)"
[ -n "${MIGRATION_HEADS}" ] || fail 'canonical Alembic head is unavailable'
P5_B4_MIGRATION_HEAD_SHA256="$(printf '%s' "${MIGRATION_HEADS}" | sha256_stream)"
P5_B4_MIGRATION_HEAD_SOURCE_SHA256="$({
	docker run --rm --network none --read-only --tmpfs /tmp:size=16m \
		--label "org.npcink.p5-b4-proof-run=${RUN_TOKEN}" \
		"${P5_B4_PROOF_IMAGE}" python -c \
		'from hashlib import sha256; from pathlib import Path; from alembic.config import Config; from alembic.script import ScriptDirectory; script=ScriptDirectory.from_config(Config("alembic.ini")); heads=script.get_heads(); assert len(heads) == 1; print(sha256(Path(script.get_revision(heads[0]).path).read_bytes()).hexdigest())'
} 2>/dev/null)"
[ -n "${P5_B4_MIGRATION_HEAD_SOURCE_SHA256}" ] || \
	fail 'canonical Alembic head source hash is unavailable'
P5_B4_CONTEXT_SHA256="$(printf '%s\n' \
	"${P5_B4_REVISION}" \
	"${P5_B4_HARNESS_SHA256}" \
	"${P5_B4_COMPOSE_SHA256}" \
	"${P5_B4_WRAPPER_SHA256}" \
	"${P5_B4_MIGRATION_MANIFEST_SHA256}" \
	"${P5_B4_MIGRATION_HEAD_SHA256}" \
	"${P5_B4_MIGRATION_HEAD_SOURCE_SHA256}" \
	"${P5_B4_PROOF_IMAGE_ID}" \
	"${P5_B4_ENVIRONMENT_FINGERPRINT}" \
	"${P5_B4_DATASET_ID}" \
	"${P5_B4_DATASET_SHA256}" \
	"${P5_B4_GIT_STATUS_SHA256}" \
	"${P5_B4_POSTGRES_IMAGE_ID}" \
	"${P5_B4_REDIS_IMAGE_ID}" | sha256_stream)"
export P5_B4_MIGRATION_HEAD_SHA256 P5_B4_MIGRATION_HEAD_SOURCE_SHA256
export P5_B4_CONTEXT_SHA256

container_process_metrics() {
	local container_id="$1"
	local expected_min_processes="$2"
	docker exec --user 0 "${container_id}" python -c '
import glob
import hashlib
import os
import sys
import time

MAX_ATTEMPTS = 5
own_pid = os.getpid()


class SnapshotRace(RuntimeError):
    pass


def process_identity(pid):
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            raw = handle.read().strip()
    except OSError as error:
        raise SnapshotRace("process identity unavailable") from error
    command_end = raw.rfind(")")
    fields = raw[command_end + 2 :].split() if command_end >= 0 else []
    if len(fields) <= 19:
        raise SnapshotRace("process identity malformed")
    try:
        parent_pid = int(fields[1])
        starttime = int(fields[19])
    except ValueError as error:
        raise SnapshotRace("process identity malformed") from error
    return parent_pid, starttime


def identity_snapshot():
    identities = {}
    for stat_path in glob.glob("/proc/[0-9]*/stat"):
        pid = int(stat_path.split("/")[2])
        if pid == own_pid:
            continue
        try:
            identities[pid] = process_identity(pid)
        except SnapshotRace:
            continue
    if 1 not in identities:
        raise SnapshotRace("pid 1 identity unavailable")
    return identities


def service_snapshot(identities):
    service = {1: identities[1]}
    while True:
        children = {
            pid: identity
            for pid, identity in identities.items()
            if pid not in service and identity[0] != 0 and identity[0] in service
        }
        if not children:
            return service
        service.update(children)


def process_metrics(pid):
    try:
        rss_bytes = None
        with open(f"/proc/{pid}/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    rss_bytes = int(line.split()[1]) * 1024
                    break
        fd_count = len(os.listdir(f"/proc/{pid}/fd"))
    except (OSError, ValueError) as error:
        raise SnapshotRace("process metrics unavailable") from error
    if rss_bytes is None:
        raise SnapshotRace("process rss unavailable")
    return rss_bytes, fd_count


def capture(expected_min_processes):
    before = service_snapshot(identity_snapshot())
    if len(before) < expected_min_processes:
        raise SnapshotRace("service process count below minimum")
    metrics = {}
    for pid, identity in before.items():
        if process_identity(pid) != identity:
            raise SnapshotRace("process identity changed before measurement")
        metrics[pid] = process_metrics(pid)
        if process_identity(pid) != identity:
            raise SnapshotRace("process identity changed during measurement")
    after = service_snapshot(identity_snapshot())
    if after != before:
        raise SnapshotRace("service process tree changed during measurement")
    rss_bytes = sum(metric[0] for metric in metrics.values())
    fd_count = sum(metric[1] for metric in metrics.values())
    if 1 not in metrics or len(metrics) < expected_min_processes:
        raise SnapshotRace("service process metrics incomplete")
    if rss_bytes <= 0 or fd_count <= 0:
        raise SnapshotRace("service process metrics invalid")
    process_count = len(metrics)
    cohort = "".join(
        f"{pid}\t{parent_pid}\t{starttime}\n"
        for pid, (parent_pid, starttime) in sorted(before.items())
    ).encode("ascii")
    cohort_sha256 = hashlib.sha256(cohort).hexdigest()
    return rss_bytes, fd_count, process_count, cohort_sha256


try:
    expected_min_processes = int(sys.argv[1])
except (IndexError, ValueError) as error:
    raise SystemExit("expected minimum process count is invalid") from error
if expected_min_processes < 1:
    raise SystemExit("expected minimum process count is invalid")

last_error = None
for attempt in range(MAX_ATTEMPTS):
    try:
        rss_bytes, fd_count, process_count, cohort_sha256 = capture(
            expected_min_processes
        )
        print(f"{rss_bytes}\t{fd_count}\t{process_count}\t{cohort_sha256}")
        break
    except SnapshotRace as error:
        last_error = error
        if attempt + 1 < MAX_ATTEMPTS:
            time.sleep(0.05)
else:
    raise SystemExit("stable service process metrics unavailable") from last_error
' "${expected_min_processes}"
}

container_is_running_and_unrestarted() {
	local container_id="$1"
	local state=""

	if ! state="$(container_state "${container_id}")"; then
		return 1
	fi
	[ "${state}" = "1 0" ] || return 1
	return 0
}

container_state() {
	local container_id="$1"
	docker inspect --format '{{if .State.Running}}1{{else}}0{{end}} {{.RestartCount}}' \
		"${container_id}"
}

container_health_status() {
	local container_id="$1"

	docker inspect --format \
		'{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' \
		"${container_id}"
}

project_container_inventory() {
	local project="$1"

	docker ps --all --no-trunc \
		--filter "label=com.docker.compose.project=${project}" \
		--format '{{.Label "com.docker.compose.service"}}\t{{.ID}}' | \
		LC_ALL=C sort
}

container_id_count() {
	printf '%s\n' "$1" | awk 'NF {count += 1} END {print count + 0}'
}

container_ids_have_count() {
	local container_ids="$1"
	local expected_count="$2"
	local actual_count=""

	if ! actual_count="$(container_id_count "${container_ids}")"; then
		return 1
	fi
	[ "${actual_count}" -eq "${expected_count}" ] || return 1
	return 0
}

capture_proof_topology() {
	local project="$1"
	local service=""
	local expected_count=""
	local inventory=""
	local container_ids=""
	local container_id=""

	if ! inventory="$(project_container_inventory "${project}")"; then
		return 1
	fi
	for service in \
		proof-api proof-worker proof-provider proof-postgres proof-redis; do
		case "${service}" in
		proof-worker)
			expected_count=2
			;;
		*)
			expected_count=1
			;;
		esac
		if ! container_ids="$(topology_service_ids "${inventory}" "${service}")"; then
			return 1
		fi
		container_ids_have_count "${container_ids}" "${expected_count}" || return 1
		while IFS= read -r container_id; do
			[[ "${container_id}" =~ ^[0-9a-f]{64}$ ]] || return 1
			printf '%s\t%s\n' "${service}" "${container_id}" || return 1
		done <<EOF
${container_ids}
EOF
	done
	return 0
}

topology_service_ids() {
	local topology="$1"
	local service="$2"

	printf '%s\n' "${topology}" | \
		awk -F '\t' -v expected_service="${service}" \
			'$1 == expected_service {print $2}' | LC_ALL=C sort
}

topology_is_running_and_unrestarted() {
	local topology="$1"
	local service=""
	local container_id=""
	local health_status=""

	while IFS=$'\t' read -r service container_id; do
		[ -n "${service}" ] || continue
		[ -n "${container_id}" ] || return 1
		container_is_running_and_unrestarted "${container_id}" || return 1
		case "${service}" in
		proof-worker)
			;;
		proof-api|proof-provider|proof-postgres|proof-redis)
			if ! health_status="$(container_health_status "${container_id}")"; then
				return 1
			fi
			[ "${health_status}" = "healthy" ] || return 1
			;;
		*)
			return 1
			;;
		esac
	done <<EOF
${topology}
EOF
	return 0
}

verify_topology_snapshot() {
	local project="$1"
	local expected_topology="$2"
	local current_topology=""

	if ! current_topology="$(capture_proof_topology "${project}")"; then
		return 1
	fi
	[ "${current_topology}" = "${expected_topology}" ] || return 1
	topology_is_running_and_unrestarted "${current_topology}" || return 1
	return 0
}

resource_sampler() {
	local project="$1"
	local resource_file="$2"
	local interval_seconds="$3"
	local stop_file="$4"
	local sync_request_file="$5"
	local sync_response_file="$6"
	local expected_topology="$7"
	local current_topology=""
	local api_container=""
	local worker_containers=""
	local worker_container=""
	local provider_container=""
	local postgres_container=""
	local api_metrics=""
	local api_rss=""
	local api_fds=""
	local api_process_count=""
	local api_process_identity_sha256=""
	local worker_rss=""
	local worker_fds=""
	local worker_process_count=""
	local worker_process_identity_sha256=""
	local expected_worker_process_identity_sha256=""
	local worker_identity_material=""
	local worker_container_metrics=""
	local worker_container_rss=""
	local worker_container_fds=""
	local worker_container_process_count=""
	local worker_container_process_identity_sha256=""
	local worker_container_state_before=""
	local worker_container_state_after=""
	local worker_container_running=""
	local worker_container_restarts=""
	local postgres_connections=""
	local numeric_metric=""
	local api_state=""
	local provider_state=""
	local api_running=""
	local api_restarts=""
	local worker_running=""
	local worker_restarts=""
	local started_at=""
	local current_time=""
	local elapsed=""

	verify_topology_snapshot "${project}" "${expected_topology}" || return 1
	if ! api_container="$(topology_service_ids "${expected_topology}" proof-api)"; then
		return 1
	fi
	if ! worker_containers="$(
		topology_service_ids "${expected_topology}" proof-worker
	)"; then
		return 1
	fi
	if ! provider_container="$(
		topology_service_ids "${expected_topology}" proof-provider
	)"; then
		return 1
	fi
	if ! postgres_container="$(
		topology_service_ids "${expected_topology}" proof-postgres
	)"; then
		return 1
	fi
	container_ids_have_count "${api_container}" 1 || return 1
	container_ids_have_count "${worker_containers}" 2 || return 1
	container_ids_have_count "${provider_container}" 1 || return 1
	container_ids_have_count "${postgres_container}" 1 || return 1

	printf 'elapsed_seconds\tapi_rss_bytes\tapi_fd_count\tworker_rss_bytes\tworker_fd_count\tpostgres_connections\tapi_restart_count\tworker_restart_count\tapi_running\tworker_running\tapi_process_count\tworker_process_count\tapi_process_identity_sha256\tworker_process_identity_sha256\n' \
		>"${resource_file}" || return 1
	if ! started_at="$(date +%s)"; then
		return 1
	fi
	[[ "${started_at}" =~ ^[0-9]+$ ]] || return 1
	while [ ! -e "${stop_file}" ]; do
		if ! current_topology="$(capture_proof_topology "${project}")"; then
			return 1
		fi
		[ "${current_topology}" = "${expected_topology}" ] || return 1
		topology_is_running_and_unrestarted "${current_topology}" || return 1
		if ! api_state="$(container_state "${api_container}")"; then
			return 1
		fi
		if ! provider_state="$(container_state "${provider_container}")"; then
			return 1
		fi
		[ "${api_state}" = "1 0" ] || return 1
		[ "${provider_state}" = "1 0" ] || return 1
		IFS=' ' read -r api_running api_restarts <<<"${api_state}" || return 1
		if ! api_metrics="$(container_process_metrics "${api_container}" 3)"; then
			return 1
		fi
		IFS=$'\t' read -r \
			api_rss api_fds api_process_count api_process_identity_sha256 \
			<<<"${api_metrics}" || return 1
		worker_rss=0
		worker_fds=0
		worker_process_count=0
		worker_restarts=0
		worker_running=0
		worker_identity_material=""
		while IFS= read -r worker_container; do
			[ -n "${worker_container}" ] || continue
			if ! worker_container_state_before="$(container_state "${worker_container}")"; then
				return 1
			fi
			IFS=' ' read -r worker_container_running worker_container_restarts \
				<<<"${worker_container_state_before}" || return 1
			[[ "${worker_container_running}" =~ ^[0-9]+$ ]] || return 1
			[[ "${worker_container_restarts}" =~ ^[0-9]+$ ]] || return 1
			[ "${worker_container_running}" -eq 1 ] || return 1
			[ "${worker_container_restarts}" -eq 0 ] || return 1
			if ! worker_container_metrics="$(
				container_process_metrics "${worker_container}" 1
			)"; then
				return 1
			fi
			IFS=$'\t' read -r \
				worker_container_rss worker_container_fds \
				worker_container_process_count \
				worker_container_process_identity_sha256 \
				<<<"${worker_container_metrics}" || return 1
			for numeric_metric in \
				"${worker_container_rss}" "${worker_container_fds}" \
				"${worker_container_process_count}"; do
				[[ "${numeric_metric}" =~ ^[0-9]+$ ]] || return 1
			done
			[[ "${worker_container_process_identity_sha256}" =~ ^[0-9a-f]{64}$ ]] || \
				return 1
			if ! worker_container_state_after="$(
				container_state "${worker_container}"
			)"; then
				return 1
			fi
			[ "${worker_container_state_after}" = "${worker_container_state_before}" ] || \
				return 1
			worker_rss=$((worker_rss + worker_container_rss))
			worker_fds=$((worker_fds + worker_container_fds))
			worker_process_count=$((worker_process_count + worker_container_process_count))
			worker_restarts=$((worker_restarts + worker_container_restarts))
			worker_running=$((worker_running + worker_container_running))
			printf -v worker_identity_material '%s%s\t%s\t%s\n' \
				"${worker_identity_material}" "${worker_container}" \
				"${worker_container_process_count}" \
				"${worker_container_process_identity_sha256}" || return 1
		done <<EOF
${worker_containers}
EOF
		if ! worker_process_identity_sha256="$(
			printf '%s' "${worker_identity_material}" | sha256_stream
		)"; then
			return 1
		fi
		if [ -z "${expected_worker_process_identity_sha256}" ]; then
			expected_worker_process_identity_sha256="${worker_process_identity_sha256}"
		fi
		[ "${worker_process_identity_sha256}" = \
			"${expected_worker_process_identity_sha256}" ] || return 1
		if ! postgres_connections="$(docker exec "${postgres_container}" \
			psql -U npcink_p5_b4 -d npcink_p5_b4_proof -Atqc \
			"SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")"; then
			return 1
		fi
		for numeric_metric in \
			"${api_rss}" "${api_fds}" "${worker_rss}" "${worker_fds}" \
			"${postgres_connections}" "${api_restarts}" "${worker_restarts}" \
			"${api_running}" "${worker_running}" \
			"${api_process_count}" "${worker_process_count}"; do
			[[ "${numeric_metric}" =~ ^[0-9]+$ ]] || return 1
		done
		[[ "${api_process_identity_sha256}" =~ ^[0-9a-f]{64}$ ]] || return 1
		[[ "${worker_process_identity_sha256}" =~ ^[0-9a-f]{64}$ ]] || return 1
		if ! current_time="$(date +%s)"; then
			return 1
		fi
		[[ "${current_time}" =~ ^[0-9]+$ ]] || return 1
		elapsed="$((current_time - started_at))"
		printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
			"${elapsed}" "${api_rss}" "${api_fds}" \
			"${worker_rss}" "${worker_fds}" "${postgres_connections}" \
			"${api_restarts}" "${worker_restarts}" "${api_running}" "${worker_running}" \
			"${api_process_count}" "${worker_process_count}" \
			"${api_process_identity_sha256}" "${worker_process_identity_sha256}" \
			>>"${resource_file}" || return 1
		if [ -e "${sync_request_file}" ] && [ ! -e "${sync_response_file}" ]; then
			printf '%s\n' "${elapsed}" >"${sync_response_file}" || return 1
		fi
		sleep "${interval_seconds}" || return 1
	done
	return 0
}

start_sampler() {
	local project="$1"
	local resource_file="$2"
	local interval_seconds="$3"
	local expected_topology="$4"
	local attempts=0
	local resource_line_count=0
	local sync_request_file="${resource_file}.sync-request"
	local sync_response_file="${resource_file}.sync-response"

	SAMPLER_STOP_FILE="${EVIDENCE_DIR}/sampler-stop-${project}"
	rm -f -- "${SAMPLER_STOP_FILE}" "${sync_request_file}" "${sync_response_file}" || \
		return 1
	resource_sampler "${project}" "${resource_file}" "${interval_seconds}" \
		"${SAMPLER_STOP_FILE}" "${sync_request_file}" "${sync_response_file}" \
		"${expected_topology}" &
	SAMPLER_PID=$!
	[[ "${SAMPLER_PID}" =~ ^[0-9]+$ ]] || return 1
	while [ "${attempts}" -lt 100 ]; do
		if [ -f "${resource_file}" ]; then
			if ! resource_line_count="$(
				awk 'END {print NR + 0}' "${resource_file}" 2>/dev/null
			)"; then
				return 1
			fi
			[[ "${resource_line_count}" =~ ^[0-9]+$ ]] || return 1
			if [ "${resource_line_count}" -ge 2 ]; then
				return 0
			fi
		fi
		sampler_job_is_active "${SAMPLER_PID}" || return 1
		sleep 0.1 || return 1
		attempts=$((attempts + 1))
	done
	return 1
}

verify_live_topology() {
	local project="$1"
	local expected_topology="$2"

	verify_topology_snapshot "${project}" "${expected_topology}" || return 1
	return 0
}

if [ "${MODE}" = "formal" ]; then
	BASELINE_COUNT=3
	SAMPLE_INTERVAL=5
	printf 'P5-B4 formal proof: 3 independent fresh baselines, each 30s warmup + 600s soak.\n' >&2
else
	BASELINE_COUNT=1
	SAMPLE_INTERVAL=1
	printf 'P5-B4 quick proof is NON-ACCEPTANCE evidence.\n' >&2
fi

BASELINES_COMPLETED=0
LOAD_STATUS=0
baseline_index=1
while [ "${baseline_index}" -le "${BASELINE_COUNT}" ]; do
	require_source_snapshot "before baseline ${baseline_index}" || \
		fail "source snapshot changed before baseline ${baseline_index}"
	CURRENT_PROJECT="npcink_p5_b4_${RUN_TOKEN}_b${baseline_index}"
	PROJECTS+=("${CURRENT_PROJECT}")
	export COMPOSE_PROJECT_NAME="${CURRENT_PROJECT}"
	RESOURCE_HOST_FILE="${EVIDENCE_DIR}/resources-${baseline_index}.tsv"
	RESOURCE_CONTAINER_FILE="/proof-evidence/resources-${baseline_index}.tsv"
	BASELINE_CONTAINER_FILE="/proof-evidence/baseline-${baseline_index}.json"

	printf 'P5-B4 baseline %s/%s: fresh PostgreSQL/Redis/provider setup.\n' \
		"${baseline_index}" "${BASELINE_COUNT}" >&2
	docker compose -f "${COMPOSE_FILE}" --profile proof up --detach --wait \
		proof-postgres proof-redis proof-provider >&2
	set +e
	docker compose -f "${COMPOSE_FILE}" --profile proof run --rm --no-deps proof-runner \
		python scripts/p5_b4_runtime_load_soak.py --confirm-disposable \
		prepare --baseline-index "${baseline_index}" \
		>"${EVIDENCE_DIR}/prepare-${baseline_index}.stdout.json"
	PREPARE_STATUS=$?
	set -e
	if [ "${PREPARE_STATUS}" -ne 0 ]; then
		printf 'P5-B4 prepare failure evidence:\n' >&2
		cat "${EVIDENCE_DIR}/prepare-${baseline_index}.stdout.json" >&2
		fail "baseline ${baseline_index} prepare failed"
	fi
	docker compose -f "${COMPOSE_FILE}" --profile proof up --detach --wait \
		proof-api proof-worker >&2
	if ! BASELINE_TOPOLOGY="$(capture_proof_topology "${CURRENT_PROJECT}")"; then
		fail 'proof topology invalid; proof-worker topology does not contain exactly two containers'
	fi
	verify_live_topology "${CURRENT_PROJECT}" "${BASELINE_TOPOLOGY}" || \
		fail 'real API/two-worker/provider/Postgres/Redis topology is not healthy'
	set +e
	docker compose -f "${COMPOSE_FILE}" --profile proof run --rm --no-deps proof-runner \
		python scripts/p5_b4_runtime_load_soak.py --confirm-disposable probe-api \
		>"${EVIDENCE_DIR}/runner-api-preflight-${baseline_index}.stdout.json"
	PREFLIGHT_STATUS=$?
	set -e
	if [ "${PREFLIGHT_STATUS}" -ne 0 ]; then
		printf 'P5-B4 runner-network API preflight failure evidence:\n' >&2
		cat "${EVIDENCE_DIR}/runner-api-preflight-${baseline_index}.stdout.json" >&2
		fail "baseline ${baseline_index} runner-network API preflight failed"
	fi
	start_sampler "${CURRENT_PROJECT}" "${RESOURCE_HOST_FILE}" "${SAMPLE_INTERVAL}" \
		"${BASELINE_TOPOLOGY}" || \
		fail 'resource sampler did not produce its first valid sample'

	set +e
	docker compose -f "${COMPOSE_FILE}" --profile proof run --rm --no-deps proof-runner \
		python scripts/p5_b4_runtime_load_soak.py --confirm-disposable \
		run --mode "${MODE}" --baseline-index "${baseline_index}" \
		--output "${BASELINE_CONTAINER_FILE}" \
		--resource-file "${RESOURCE_CONTAINER_FILE}" \
		>"${EVIDENCE_DIR}/runner-${baseline_index}.stdout.json"
	RUN_STATUS=$?
	set -e
	if ! stop_sampler; then
		fail 'resource sampler failed; cleanup will run and no evidence will be published'
	fi
	verify_live_topology "${CURRENT_PROJECT}" "${BASELINE_TOPOLOGY}" || \
		fail 'API/two-worker/provider/Postgres/Redis stopped, restarted, or changed during the baseline'
	if ! cleanup_project "${CURRENT_PROJECT}"; then
		fail 'baseline teardown or cleanup verification failed'
	fi
	require_source_snapshot "after baseline ${baseline_index}" || \
		fail "source snapshot changed during baseline ${baseline_index}"
	CURRENT_PROJECT=""
	BASELINES_COMPLETED=$((BASELINES_COMPLETED + 1))
	if [ "${RUN_STATUS}" -ne 0 ]; then
		LOAD_STATUS="${RUN_STATUS}"
		break
	fi
	baseline_index=$((baseline_index + 1))
done

require_source_snapshot 'before aggregate' || \
	fail 'source snapshot changed before aggregate'
P5_B4_TOPOLOGY_VERIFIED="true"
export P5_B4_TOPOLOGY_VERIFIED
AGGREGATE_FILE="${EVIDENCE_DIR}/aggregate.tmp.json"
AGGREGATE_PROJECT="npcink_p5_b4_${RUN_TOKEN}_aggregate"
set +e
docker run --rm --network none --read-only --tmpfs /tmp:size=32m \
	--user "${P5_B4_RUNNER_UID}:${P5_B4_RUNNER_GID}" \
	--label "org.npcink.p5-b4-proof-run=${RUN_TOKEN}" \
	-e P5_B4_DISPOSABLE_PROOF="${DISPOSABLE_CONFIRMATION}" \
	-e P5_B4_PROOF_PROJECT="${AGGREGATE_PROJECT}" \
	-e P5_B4_PROOF_IMAGE_ID \
	-e P5_B4_REVISION -e P5_B4_CONTEXT_SHA256 \
	-e P5_B4_HARNESS_SHA256 -e P5_B4_COMPOSE_SHA256 -e P5_B4_WRAPPER_SHA256 \
	-e P5_B4_MIGRATION_MANIFEST_SHA256 -e P5_B4_MIGRATION_HEAD_SHA256 \
	-e P5_B4_MIGRATION_HEAD_SOURCE_SHA256 \
	-e P5_B4_ENVIRONMENT_FINGERPRINT \
	-e P5_B4_DATASET_ID -e P5_B4_DATASET_CONFIG -e P5_B4_DATASET_SHA256 \
	-e P5_B4_GIT_DIRTY -e P5_B4_GIT_DIRTY_COUNT -e P5_B4_GIT_STATUS_SHA256 \
	-e P5_B4_POSTGRES_IMAGE_ID -e P5_B4_REDIS_IMAGE_ID \
	-e P5_B4_TOPOLOGY_VERIFIED \
	-e P5_B4_DOCKER_ARCH -e P5_B4_DOCKER_CPU_COUNT -e P5_B4_DOCKER_MEMORY_BYTES \
	-e P5_B4_DOCKER_SERVER_VERSION -e P5_B4_DOCKER_COMPOSE_VERSION \
	-e P5_B4_DOCKER_BACKGROUND_CONTAINER_COUNT \
	-v "${EVIDENCE_DIR}:/proof-evidence" \
	"${P5_B4_PROOF_IMAGE}" \
	python scripts/p5_b4_runtime_load_soak.py --confirm-disposable \
	aggregate --mode "${MODE}" --input-dir /proof-evidence \
	--baseline-count "${BASELINES_COMPLETED}" --output /proof-evidence/aggregate.tmp.json \
	>"${EVIDENCE_DIR}/aggregate.stdout.json"
AGGREGATE_STATUS=$?
set -e
require_source_snapshot 'after aggregate' || \
	fail 'source snapshot changed during aggregate'
[ -s "${AGGREGATE_FILE}" ] || fail 'aggregate evidence was not produced'

for project in "${PROJECTS[@]}"; do
	verify_project_absent "${project}" || fail 'task-owned Compose resources remain after teardown'
done
if ! remove_proof_image; then
	fail 'task-owned proof image cleanup failed; no evidence was published'
fi
P5_B4_PROOF_IMAGE_ID=""

python3 -c 'import json,sys; json.load(open(sys.argv[1], encoding="utf-8"))' \
	"${AGGREGATE_FILE}" || fail 'aggregate evidence is not valid JSON'
require_source_snapshot 'immediately before publish_output' || \
	fail 'source snapshot changed before evidence publication'
publish_output "${OUTPUT_PATH}" <"${AGGREGATE_FILE}"

rm -rf -- "${EVIDENCE_DIR}"
EVIDENCE_DIR=""
CLEANUP_COMPLETE=1

cat "${OUTPUT_PATH}"
printf '\n' >&2

if [ "${LOAD_STATUS}" -ne 0 ] || [ "${AGGREGATE_STATUS}" -ne 0 ]; then
	exit 1
fi
exit 0
