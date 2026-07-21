#!/usr/bin/env bash
set -euo pipefail

# Local, disposable rehearsal only. This entry point delegates to existing
# proof gates instead of reproducing their deployment or recovery logic.

umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TARGET="local-staging"
MODE="full"
SKIP_CONFIG=0
SKIP_DEPLOY_BUNDLE=0
SKIP_ARTIFACT_ISOLATION=0
ALLOW_PARTIAL=0
CONFIRM_DISPOSABLE_LOCAL_DOCKER=0
PASSED_STAGES=0
SKIPPED_STAGES=0
REHEARSAL_SENTINEL="media-runtime-disposable-local-v1"

usage() {
	cat <<'EOF'
Usage: bash scripts/media-runtime-staging-rehearsal.sh [options]

Runs the existing Cloud release/configuration, exact deploy-bundle, and
isolated media artifact recovery gates in a disposable local environment.

Options:
  --target local-staging       Explicit rehearsal target (the only accepted value).
  --quick                      Run configuration gates; skip Docker-heavy proofs.
  --skip-config                Skip both configuration gates.
  --skip-deploy-bundle         Skip the exact deploy-bundle replay.
  --skip-artifact-isolation    Skip the isolated artifact recovery proof.
  --allow-partial              Allow a PARTIAL quick run to exit successfully.
  --confirm-disposable-local-docker
                               Required for full mode; confirms disposable local Docker.
  --help                       Show this help.

Any skipped stage makes the final status PARTIAL. PARTIAL exits 3 unless
--allow-partial is supplied; that flag is forbidden in full mode.
EOF
}

fail_closed() {
	printf '[rehearsal:fail] %s\n' "$1" >&2
	exit 2
}

while (($# > 0)); do
	case "$1" in
		--target)
			(($# >= 2)) || fail_closed "--target requires a value"
			TARGET="$2"
			shift 2
			;;
		--quick)
			MODE="quick"
			shift
			;;
		--skip-config)
			SKIP_CONFIG=1
			shift
			;;
		--skip-deploy-bundle)
			SKIP_DEPLOY_BUNDLE=1
			shift
			;;
		--skip-artifact-isolation)
			SKIP_ARTIFACT_ISOLATION=1
			shift
			;;
		--allow-partial)
			ALLOW_PARTIAL=1
			shift
			;;
		--confirm-disposable-local-docker)
			CONFIRM_DISPOSABLE_LOCAL_DOCKER=1
			shift
			;;
		--help|-h)
			usage
			exit 0
			;;
		*)
			fail_closed "unknown option"
			;;
	esac
done

if [[ "${TARGET}" != "local-staging" ]]; then
	fail_closed "only the local-staging target is allowed"
fi

if [[ "${MODE}" == "quick" ]]; then
	SKIP_DEPLOY_BUNDLE=1
	SKIP_ARTIFACT_ISOLATION=1
fi

if [[ "${MODE}" == "full" && "${ALLOW_PARTIAL}" == "1" ]]; then
	fail_closed "--allow-partial is forbidden in full mode"
fi

if [[ "${MODE}" == "full" && "${CONFIRM_DISPOSABLE_LOCAL_DOCKER}" != "1" ]]; then
	fail_closed "full mode requires --confirm-disposable-local-docker"
fi

reject_inherited_environment() {
	local variable_name="$1"
	if printenv "${variable_name}" >/dev/null 2>&1; then
		fail_closed "unsafe inherited environment variable is not allowed: ${variable_name}"
	fi
}

# These variables can redirect Compose, Docker, env loading, or smoke traffic.
# They must fail closed rather than be ignored, even when they appear harmless.
unsafe_control_environment=(
	"COMPOSE_PROJECT_NAME"
	"COMPOSE_FILE"
	"COMPOSE_ENV_FILES"
	"ENV_FILE"
	"DOCKER_HOST"
	"DOCKER_CONTEXT"
	"DOCKER_CONFIG"
	"NPCINK_CLOUD_COMPOSE_PROJECT_NAME"
	"NPCINK_CLOUD_COMPOSE_FILE"
	"NPCINK_CLOUD_ENV_FILE"
	"NPCINK_CLOUD_DEPLOY_SMOKE_BASE_URL"
	"NPCINK_CLOUD_DEPLOY_SMOKE_PORT"
	"NPCINK_CLOUD_BASE_URL"
	"NPCINK_CLOUD_PORT"
	"CLOUD_API_BASE_URL"
	"CLOUD_PUBLIC_BASE_URL"
	"NPCINK_CLOUD_ENVIRONMENT"
	"NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_ENABLED"
	"NPCINK_CLOUD_DEPLOY_SMOKE_KEEP"
	"NPCINK_CLOUD_DEPLOY_SMOKE_SKIP_BUILD"
	"NPCINK_CLOUD_SKIP_FRONTEND_IMAGE"
)
for variable_name in "${unsafe_control_environment[@]}"; do
	reject_inherited_environment "${variable_name}"
done

if [[ -z "${PATH:-}" ]]; then
	fail_closed "PATH is required for delegated local gates"
fi

# Every delegated command receives only this explicit environment. Provider,
# service, telemetry, database, site, proxy, and credential variables from the
# caller are absent by construction. Tests require the fixed sentinel.
clean_environment=(
	env -i
	"PATH=${PATH}"
	"HOME=${HOME:-}"
	"TMPDIR=/tmp"
	"LANG=C"
	"LC_ALL=C"
	"MEDIA_RUNTIME_REHEARSAL_ENV_SENTINEL=${REHEARSAL_SENTINEL}"
	"NPCINK_CLOUD_ENVIRONMENT=test"
	"NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_ENABLED=false"
	"NPCINK_CLOUD_DEPLOY_SMOKE_KEEP=0"
	"NPCINK_CLOUD_DEPLOY_SMOKE_SKIP_BUILD=0"
	"NPCINK_CLOUD_SKIP_FRONTEND_IMAGE=0"
)

required_files=(
	"package.json"
	"scripts/check-release-policy.sh"
	"scripts/check-cloud-anti-drift.js"
	"scripts/check-provider-env-retirement.js"
	"scripts/cloud-deploy-bundle-smoke-flow.sh"
	"scripts/check-artifact-orphan-isolation-proof.sh"
)
for relative_path in "${required_files[@]}"; do
	[[ -f "${ROOT_DIR}/${relative_path}" ]] || fail_closed "required delegated gate is missing"
done

bash -n "${ROOT_DIR}/scripts/check-release-policy.sh"
bash -n "${ROOT_DIR}/scripts/cloud-deploy-bundle-smoke-flow.sh"
bash -n "${ROOT_DIR}/scripts/check-artifact-orphan-isolation-proof.sh"

if ((
	SKIP_CONFIG == 0 \
		|| SKIP_DEPLOY_BUNDLE == 0 \
		|| SKIP_ARTIFACT_ISOLATION == 0
)); then
	command -v pnpm >/dev/null 2>&1 || fail_closed "pnpm is required for delegated gates"
fi

if ((SKIP_DEPLOY_BUNDLE == 0 || SKIP_ARTIFACT_ISOLATION == 0)); then
	command -v docker >/dev/null 2>&1 || fail_closed "Docker is required for full rehearsal"
	DOCKER_CONTEXT_NAME="$(
		"${clean_environment[@]}" docker context show 2>/dev/null
	)" || fail_closed "Docker context is unavailable"
	DOCKER_ENDPOINT="$(
		"${clean_environment[@]}" docker context inspect "${DOCKER_CONTEXT_NAME}" \
			--format '{{(index .Endpoints "docker").Host}}' 2>/dev/null
	)" || fail_closed "Docker endpoint cannot be inspected"
	case "${DOCKER_ENDPOINT}" in
		unix://*|npipe://*) ;;
		*) fail_closed "active Docker context is not local" ;;
	esac
	"${clean_environment[@]}" docker info >/dev/null 2>&1 \
		|| fail_closed "local Docker daemon is unavailable"
fi

cd "${ROOT_DIR}"

run_stage() {
	local stage_name="$1"
	shift
	printf '[rehearsal:start] %s\n' "${stage_name}"
	if "${clean_environment[@]}" "$@"; then
		PASSED_STAGES=$((PASSED_STAGES + 1))
		printf '[rehearsal:pass] %s\n' "${stage_name}"
		return 0
	else
		local exit_code="$?"
		printf '[rehearsal:fail] %s exit=%s\n' "${stage_name}" "${exit_code}" >&2
		exit "${exit_code}"
	fi
}

skip_stage() {
	local stage_name="$1"
	SKIPPED_STAGES=$((SKIPPED_STAGES + 1))
	printf '[rehearsal:skip] %s\n' "${stage_name}"
}

if ((SKIP_CONFIG)); then
	skip_stage "configuration/release-policy"
	skip_stage "configuration/anti-drift"
else
	run_stage "configuration/release-policy" pnpm run check:release-policy
	run_stage "configuration/anti-drift" pnpm run check:anti-drift
fi

if ((SKIP_DEPLOY_BUNDLE)); then
	skip_stage "runtime/exact-deploy-bundle"
else
	run_stage "runtime/exact-deploy-bundle" pnpm run check:e2e:deploy-bundle:smoke
fi

if ((SKIP_ARTIFACT_ISOLATION)); then
	skip_stage "media/isolated-artifact-recovery"
else
	run_stage \
		"media/isolated-artifact-recovery" \
		pnpm run check:artifact-orphan-isolation-proof
fi

FINAL_STATUS="PASS"
if ((SKIPPED_STAGES > 0)); then
	FINAL_STATUS="PARTIAL"
fi
printf 'MEDIA_RUNTIME_STAGING_REHEARSAL %s target=%s mode=%s passed=%s skipped=%s\n' \
	"${FINAL_STATUS}" \
	"${TARGET}" \
	"${MODE}" \
	"${PASSED_STAGES}" \
	"${SKIPPED_STAGES}"

if [[ "${FINAL_STATUS}" == "PARTIAL" && "${ALLOW_PARTIAL}" != "1" ]]; then
	exit 3
fi
