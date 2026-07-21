#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
DIST_DIR="${ROOT_DIR}/dist"
SKIP_FRONTEND_IMAGE="${NPCINK_CLOUD_SKIP_FRONTEND_IMAGE:-0}"
LOAD_MODE="${NPCINK_CLOUD_LOAD_MODE:-}"
ROLLBACK_IMAGE_MAP="${NPCINK_CLOUD_ROLLBACK_IMAGE_MAP:-}"
ROLLBACK_TAG_SUFFIX="${NPCINK_CLOUD_ROLLBACK_TAG_SUFFIX:-}"
MANIFEST_HELPER="${ROOT_DIR}/scripts/verify-release-bundle-manifest.py"
RELEASE_VERIFIER="${ROOT_DIR}/deploy/verify-release-bundle.sh"
RETIRED_BUNDLE_SERVICES=(caddy jaeger otel-collector)
CERTIFICATE_RENEWAL_READINESS="${ROOT_DIR}/deploy/certificate-renewal-readiness.sh"

# Shared compose/env helpers for deploy scripts.
. "${ROOT_DIR}/deploy/common.sh"
npcink_ai_cloud_require_deploy_lock_owner "${ROOT_DIR}"
npcink_ai_cloud_load_env_file "${ROOT_DIR}"
RELEASE_TOOL_PYTHON="$(npcink_ai_cloud_release_tool_python)"
npcink_ai_cloud_require_release_tool_python "${RELEASE_TOOL_PYTHON}"
BASE_URL="${NPCINK_CLOUD_BASE_URL:-http://127.0.0.1:${NPCINK_CLOUD_PORT:-8010}}"
COMPOSE_FILE="${NPCINK_CLOUD_COMPOSE_FILE:-${ROOT_DIR}/docker-compose.prod.yml}"
COMPOSE_PROJECT_NAME_EFFECTIVE="${NPCINK_CLOUD_COMPOSE_PROJECT_NAME:-${COMPOSE_PROJECT_NAME:-npcink-ai-cloud}}"

COMPOSE_FILE="$(
	"${RELEASE_TOOL_PYTHON}" - "${ROOT_DIR}" "${COMPOSE_FILE}" <<'PY'
from __future__ import annotations

import os
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve(strict=True)
requested = Path(sys.argv[2])
if not requested.is_absolute():
    requested = root / requested
requested = Path(os.path.abspath(requested))
allowed = {root / "docker-compose.prod.yml", root / "docker-compose.runtime.yml"}
if requested not in allowed or requested.is_symlink() or not requested.is_file():
    raise SystemExit("[fail] Exact release loader requires a canonical bundled Compose file.")
print(requested)
PY
)" || exit 1
# Every shared Compose helper must consume the exact path proved above. Leaving
# the caller's original relative value in the environment would let validation
# and execution resolve the same spelling against different working directories.
export NPCINK_CLOUD_COMPOSE_FILE="${COMPOSE_FILE}"

npcink_ai_cloud_require_cmd docker
npcink_ai_cloud_require_cmd curl
npcink_ai_cloud_require_internal_token

case "${LOAD_MODE}" in
	prepare-only|data-only|api-only|workers-only|traffic-only)
		;;
	*)
		echo "[fail] NPCINK_CLOUD_LOAD_MODE must select an explicit staged release phase." >&2
		exit 1
		;;
esac

if [ "${LOAD_MODE}" = "prepare-only" ]; then
	if [ -z "${ROLLBACK_IMAGE_MAP}" ]; then
		echo "[fail] prepare-only mode requires NPCINK_CLOUD_ROLLBACK_IMAGE_MAP." >&2
		exit 1
	fi
	if [[ ! "${ROLLBACK_TAG_SUFFIX}" =~ ^[A-Za-z0-9_.-]+$ ]]; then
		echo "[fail] prepare-only mode requires a safe NPCINK_CLOUD_ROLLBACK_TAG_SUFFIX." >&2
		exit 1
	fi
fi

is_formal_runtime() {
	if [ "$(basename "${COMPOSE_FILE}")" != "docker-compose.runtime.yml" ] &&
		[[ "${BASE_URL}" != https://* ]]; then
		return 1
	fi
	return 0
}

require_external_edge_for_formal_runtime() {
	if [ "$(basename "${COMPOSE_FILE}")" != "docker-compose.runtime.yml" ] &&
		[[ "${BASE_URL}" != https://* ]]; then
		return 0
	fi

	if [ "${NPCINK_CLOUD_EXTERNAL_EDGE_READY:-false}" != "true" ]; then
		echo "[fail] docker-compose.runtime.yml requires NPCINK_CLOUD_EXTERNAL_EDGE_READY=true after the external TLS edge is ready." >&2
		exit 1
	fi
	if [ -z "${NPCINK_CLOUD_BASE_URL:-}" ]; then
		echo "[fail] docker-compose.runtime.yml requires an explicit NPCINK_CLOUD_BASE_URL." >&2
		exit 1
	fi
	if [ -z "${NPCINK_CLOUD_DOMAIN_NAME:-}" ]; then
		echo "[fail] docker-compose.runtime.yml requires NPCINK_CLOUD_DOMAIN_NAME for the external TLS edge." >&2
		exit 1
	fi

	"${RELEASE_TOOL_PYTHON}" - "${BASE_URL}" "${NPCINK_CLOUD_DOMAIN_NAME}" <<'PY'
from __future__ import annotations

import sys
from urllib.parse import urlsplit

base_url = sys.argv[1].strip()
expected_host = sys.argv[2].strip().lower().rstrip(".")
try:
    parsed = urlsplit(base_url)
    port = parsed.port
except ValueError as exc:
    raise SystemExit(f"[fail] NPCINK_CLOUD_BASE_URL is invalid: {exc}") from exc

actual_host = str(parsed.hostname or "").lower().rstrip(".")
if parsed.scheme.lower() != "https":
    raise SystemExit("[fail] Formal runtime requires an https:// NPCINK_CLOUD_BASE_URL.")
if not actual_host or actual_host != expected_host:
    raise SystemExit(
        "[fail] NPCINK_CLOUD_BASE_URL host must match NPCINK_CLOUD_DOMAIN_NAME."
    )
if parsed.username is not None or parsed.password is not None:
    raise SystemExit("[fail] NPCINK_CLOUD_BASE_URL must not contain userinfo.")
if port not in (None, 443):
    raise SystemExit("[fail] Formal runtime external edge must own HTTPS port 443.")
if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
    raise SystemExit("[fail] NPCINK_CLOUD_BASE_URL must be an origin without path, query, or fragment.")
PY

	echo "[ok] External TLS edge contract acknowledged for ${BASE_URL}"
}

verify_certificate_renewal_readiness() {
	local certificate_path="${NPCINK_CLOUD_CERTIFICATE_RENEWAL_CERT_PATH:-}"
	local evidence_path="${NPCINK_CLOUD_CERTIFICATE_RENEWAL_EVIDENCE_PATH:-}"
	local timer_name="${NPCINK_CLOUD_CERTIFICATE_RENEWAL_TIMER:-}"
	local deploy_hook_path="${NPCINK_CLOUD_CERTIFICATE_RENEWAL_HOOK_PATH:-}"
	[ -n "${certificate_path}" ] || {
		echo "[fail] Formal runtime requires NPCINK_CLOUD_CERTIFICATE_RENEWAL_CERT_PATH." >&2
		exit 1
	}
	[ -n "${evidence_path}" ] || {
		echo "[fail] Formal runtime requires NPCINK_CLOUD_CERTIFICATE_RENEWAL_EVIDENCE_PATH." >&2
		exit 1
	}
	[ -n "${timer_name}" ] || {
		echo "[fail] Formal runtime requires NPCINK_CLOUD_CERTIFICATE_RENEWAL_TIMER." >&2
		exit 1
	}
	[ -n "${deploy_hook_path}" ] || {
		echo "[fail] Formal runtime requires NPCINK_CLOUD_CERTIFICATE_RENEWAL_HOOK_PATH." >&2
		exit 1
	}
	[ -x "${CERTIFICATE_RENEWAL_READINESS}" ] || {
		echo "[fail] Certificate-renewal readiness verifier is missing or not executable." >&2
		exit 1
	}
	NPCINK_CLOUD_RELEASE_TOOL_PYTHON="${RELEASE_TOOL_PYTHON}" \
		bash "${CERTIFICATE_RENEWAL_READINESS}" verify \
		--domain "${NPCINK_CLOUD_DOMAIN_NAME}" \
		--certificate-path "${certificate_path}" \
		--owner certbot \
		--timer "${timer_name}" \
		--deploy-hook-path "${deploy_hook_path}" \
		--evidence-path "${evidence_path}"
}

assert_retired_bundle_services_absent() {
	local service_name=""
	local container_ids=""
	for service_name in "${RETIRED_BUNDLE_SERVICES[@]}"; do
		container_ids="$(docker ps -aq \
			--filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
			--filter "label=com.docker.compose.service=${service_name}")"
		if [ -n "${container_ids}" ]; then
			echo "[fail] Retired bundle service container still exists: ${service_name}" >&2
			exit 1
		fi
	done
	echo "[ok] Retired bundle services are absent: ${RETIRED_BUNDLE_SERVICES[*]}"
}

require_external_edge_for_formal_runtime

configure_ready_origin_headers() {
	if [ -n "${NPCINK_CLOUD_HEALTH_HOST_HEADER:-}" ] ||
		[ -n "${NPCINK_CLOUD_HEALTH_FORWARDED_PROTO:-}" ]; then
		return
	fi

	local origin="${NPCINK_CLOUD_READY_ORIGIN:-}"
	local proto=""
	local without_scheme=""
	local host=""

	if [ -z "${origin}" ]; then
		origin="${NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST:-}"
		origin="${origin%%,*}"
	fi
	origin="${origin#"${origin%%[![:space:]]*}"}"
	origin="${origin%"${origin##*[![:space:]]}"}"

	case "${origin}" in
		http://*|https://*)
			proto="${origin%%://*}"
			without_scheme="${origin#*://}"
			host="${without_scheme%%/*}"
			;;
		*)
			return
			;;
	esac

	if [ -n "${host}" ]; then
		export NPCINK_CLOUD_HEALTH_HOST_HEADER="${host}"
	fi
	if [ -n "${proto}" ]; then
		export NPCINK_CLOUD_HEALTH_FORWARDED_PROTO="${proto}"
	fi
}

configure_ready_origin_headers

echo "[info] Using compose file: ${COMPOSE_FILE}"

snapshot_existing_release_images() {
	local load_plan="$1"
	local alias_plan="$2"
	local map_dir=""
	local map_tmp=""
	local refs_tmp=""
	local sorted_references=""
	local target_reference=""
	local rollback_reference=""
	local image_id=""
	local index=0

	map_dir="$(dirname "${ROLLBACK_IMAGE_MAP}")"
	mkdir -p "${map_dir}"
	map_tmp="$(mktemp "${map_dir}/.rollback-images.XXXXXX")"
	refs_tmp="$(mktemp "${map_dir}/.rollback-refs.XXXXXX")"
	chmod 0600 "${map_tmp}" "${refs_tmp}"

	while IFS=$'\t' read -r _image_archive _image_role target_reference; do
		[ -n "${target_reference}" ] || continue
		printf '%s\n' "${target_reference}" >>"${refs_tmp}"
	done <<<"${load_plan}"
	while IFS=$'\t' read -r _source_reference target_reference; do
		[ -n "${target_reference}" ] || continue
		printf '%s\n' "${target_reference}" >>"${refs_tmp}"
	done <<<"${alias_plan}"
	if ! sorted_references="$(LC_ALL=C sort -u "${refs_tmp}")"; then
		echo "[fail] Release image references could not be sorted for recovery." >&2
		rm -f "${map_tmp}" "${refs_tmp}"
		return 1
	fi

	while IFS= read -r target_reference; do
		[ -n "${target_reference}" ] || continue
		index=$((index + 1))
		if image_id="$(docker image inspect --format '{{.Id}}' "${target_reference}" 2>/dev/null)"; then
			rollback_reference="npcink-ai-cloud-rollback:${ROLLBACK_TAG_SUFFIX}-${index}"
			docker tag "${image_id}" "${rollback_reference}"
			printf '%s\t%s\t%s\n' \
				"${target_reference}" "${rollback_reference}" "${image_id}" >>"${map_tmp}"
		else
			if ! docker info >/dev/null 2>&1; then
				echo "[fail] Docker daemon availability could not be proven while snapshotting ${target_reference}." >&2
				rm -f "${map_tmp}" "${refs_tmp}"
				exit 1
			fi
			# A missing prior reference must be removed again if a later load
			# partially introduces it and the cutover fails.
			printf '%s\t-\t-\n' "${target_reference}" >>"${map_tmp}"
		fi
	done <<<"${sorted_references}"

	rm -f "${refs_tmp}"
	mv -f "${map_tmp}" "${ROLLBACK_IMAGE_MAP}"
	chmod 0600 "${ROLLBACK_IMAGE_MAP}"
	echo "[ok] Snapshotted existing release image references for recovery."
}

prepare_release_images() {
	local load_plan=""
	local alias_plan=""
	[ -x "${RELEASE_VERIFIER}" ] || {
		echo "[fail] Exact release-bundle verifier is missing or not executable." >&2
		exit 1
	}
	[ -f "${MANIFEST_HELPER}" ] || {
		echo "[fail] Exact release-bundle manifest helper is missing." >&2
		exit 1
	}

	# This is deliberately before the first docker load and before compose up.
	npcink_ai_cloud_run_timed "verify exact bundle before load" \
		bash "${RELEASE_VERIFIER}" --pre-load "${ROOT_DIR}"
	if ! load_plan="$("${RELEASE_TOOL_PYTHON}" "${MANIFEST_HELPER}" load-plan --root "${ROOT_DIR}")"; then
		echo "[fail] Exact release image load plan could not be read." >&2
		return 1
	fi
	if ! alias_plan="$("${RELEASE_TOOL_PYTHON}" "${MANIFEST_HELPER}" alias-plan --root "${ROOT_DIR}")"; then
		echo "[fail] Exact release image alias plan could not be read." >&2
		return 1
	fi

	if [ "${LOAD_MODE}" = "prepare-only" ]; then
		snapshot_existing_release_images "${load_plan}" "${alias_plan}"
	fi

	while IFS=$'\t' read -r image_archive image_role image_reference; do
		[ -n "${image_archive}" ] || continue
		npcink_ai_cloud_run_timed "load ${image_role} image archive" \
			bash -c 'gzip -dc "$1" | docker load' _ "${ROOT_DIR}/${image_archive}"
	done <<<"${load_plan}"

	# Worker/callback/ops roles are aliases of the one API image archive. The
	# manifest controls the aliases; no role may silently rebuild or load another
	# archive.
	while IFS=$'\t' read -r source_reference alias_reference; do
		[ -n "${source_reference}" ] || continue
		docker tag "${source_reference}" "${alias_reference}"
	done <<<"${alias_plan}"

	npcink_ai_cloud_run_timed "verify loaded image IDs" \
		bash "${RELEASE_VERIFIER}" --post-load "${ROOT_DIR}"
}

if is_formal_runtime && [ "${LOAD_MODE}" = "prepare-only" ]; then
	# Renewal evidence is verified before snapshot/tag/load can mutate images.
	verify_certificate_renewal_readiness
fi

if [ "${LOAD_MODE}" = "prepare-only" ]; then
	prepare_release_images
fi

if [ "${LOAD_MODE}" = "prepare-only" ]; then
	echo "[ok] Exact release images are prepared; no service was started."
	exit 0
fi

data_service_reference() {
	case "$1" in
		postgres) printf '%s' 'npcink-ai-cloud-postgres:prod' ;;
		redis) printf '%s' 'npcink-ai-cloud-external-redis:prod' ;;
		*) return 1 ;;
	esac
}

release_service_role() {
	case "$1" in
		postgres) printf '%s' 'postgres' ;;
		redis) printf '%s' 'external_redis' ;;
		api) printf '%s' 'api' ;;
		worker) printf '%s' 'worker' ;;
		callback-worker) printf '%s' 'callback_worker' ;;
		ops-worker) printf '%s' 'ops_worker' ;;
		frontend) printf '%s' 'frontend' ;;
		proxy) printf '%s' 'external_nginx' ;;
		*) return 1 ;;
	esac
}

release_service_reference() {
	case "$1" in
		postgres) printf '%s' 'npcink-ai-cloud-postgres:prod' ;;
		redis) printf '%s' 'npcink-ai-cloud-external-redis:prod' ;;
		api) printf '%s' 'npcink-ai-cloud-api:prod' ;;
		worker) printf '%s' 'npcink-ai-cloud-worker:prod' ;;
		callback-worker) printf '%s' 'npcink-ai-cloud-callback-worker:prod' ;;
		ops-worker) printf '%s' 'npcink-ai-cloud-ops-worker:prod' ;;
		frontend) printf '%s' 'npcink-ai-cloud-frontend:prod' ;;
		proxy) printf '%s' 'npcink-ai-cloud-external-nginx:prod' ;;
		*) return 1 ;;
	esac
}

EXACT_SERVICE_IMAGE_PLAN=""
EXACT_SERVICE_CONTAINER_PLAN=""

freeze_exact_service_images() {
	local service=""
	local role=""
	local reference=""
	local expected_image_id=""
	local plan=""
	for service in "$@"; do
		role="$(release_service_role "${service}")" || return 1
		reference="$(release_service_reference "${service}")" || return 1
		expected_image_id="$(
			"${RELEASE_TOOL_PYTHON}" "${MANIFEST_HELPER}" loaded-role-daemon-id \
				--root "${ROOT_DIR}" --role "${role}"
		)" || return 1
		[[ "${expected_image_id}" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
		npcink_ai_cloud_pin_compose_service_image "${service}" "${expected_image_id}" || return 1
		plan+="${service}"$'\t'"${role}"$'\t'"${reference}"$'\t'"${expected_image_id}"$'\n'
	done
	EXACT_SERVICE_IMAGE_PLAN="${plan}"
}

remove_exact_candidate_services() {
	local -a services=("$@")
	local service=""
	local _service=""
	local container_id=""
	local _expected_image_id=""
	local container_ids=""
	local captured_ids=""
	local unique_ids=""
	local remaining_ids=""
	local failed=0
	local attempt=0

	while IFS=$'\t' read -r _service container_id _expected_image_id; do
		[ -n "${container_id}" ] || continue
		captured_ids+="${container_id}"$'\n'
	done <<<"${EXACT_SERVICE_CONTAINER_PLAN}"
	for service in "${services[@]}"; do
		container_ids="$(npcink_ai_cloud_compose "${ROOT_DIR}" ps --all -q "${service}" 2>/dev/null)" || failed=1
		captured_ids+="${container_ids}"$'\n'
	done
	unique_ids="$(printf '%s' "${captured_ids}" | awk 'NF && !seen[$0]++ {print}')"

	npcink_ai_cloud_compose "${ROOT_DIR}" rm -f -s "${services[@]}" >/dev/null 2>&1 || true
	if [ -n "${unique_ids}" ]; then
		while [ "${attempt}" -lt 2 ]; do
			while IFS= read -r container_id; do
				[ -n "${container_id}" ] || continue
				docker rm -f "${container_id}" >/dev/null 2>&1 || true
			done <<<"${unique_ids}"
			attempt=$((attempt + 1))
		done
		while IFS= read -r container_id; do
			[ -n "${container_id}" ] || continue
			remaining_ids="$(
				docker container ls -aq --no-trunc \
					--filter "id=${container_id}" 2>/dev/null
			)" || {
				failed=1
				continue
			}
			[ -z "${remaining_ids}" ] || failed=1
		done <<<"${unique_ids}"
	fi
	for service in "${services[@]}"; do
		container_ids="$(npcink_ai_cloud_compose "${ROOT_DIR}" ps --all -q "${service}" 2>/dev/null)" || failed=1
		[ -z "${container_ids}" ] || failed=1
	done
	if [ "${failed}" -ne 0 ]; then
		echo "[fail] Exact candidate cleanup could not be proved; operator recovery is required." >&2
		return 1
	fi
}

assert_exact_started_service() {
	local expected_service="$1"
	local service=""
	local container_id=""
	local expected_image_id=""
	local actual_image_id=""
	local running=""
	while IFS=$'\t' read -r service container_id expected_image_id; do
		[ "${service}" = "${expected_service}" ] || continue
		actual_image_id="$(docker inspect --format '{{.Image}}' "${container_id}" 2>/dev/null)" || return 1
		running="$(docker inspect --format '{{.State.Running}}' "${container_id}" 2>/dev/null)" || return 1
		[ "${actual_image_id}" = "${expected_image_id}" ] && [ "${running}" = "true" ]
		return
	done <<<"${EXACT_SERVICE_CONTAINER_PLAN}"
	return 1
}

create_prove_and_start_exact_services() {
	local remove_orphans="$1"
	shift
	local -a services=("$@")
	local -a compose_args=(
		up --no-start --pull never --no-build --no-deps --force-recreate
	)
	local -a container_ids_to_start=()
	local service=""
	local role=""
	local _reference=""
	local expected_image_id=""
	local observed_image_id=""
	local observed_created_state=""
	local reproved_image_id=""
	local container_ids=""
	local container_id=""
	local container_count=0
	local plan=""

	freeze_exact_service_images "${services[@]}" || {
		echo "[fail] Complete target-daemon image proof could not be frozen for this phase." >&2
		return 1
	}
	if [ "${remove_orphans}" = "1" ]; then
		compose_args+=(--remove-orphans)
	fi
	compose_args+=("${services[@]}")
	if ! npcink_ai_cloud_compose "${ROOT_DIR}" "${compose_args[@]}"; then
		echo "[fail] Exact service candidates could not be created without starting." >&2
		EXACT_SERVICE_CONTAINER_PLAN=""
		remove_exact_candidate_services "${services[@]}" || true
		return 1
	fi
	EXACT_SERVICE_CONTAINER_PLAN=""

	while IFS=$'\t' read -r service role _reference expected_image_id; do
		[ -n "${service}" ] || continue
		container_ids="$(npcink_ai_cloud_compose "${ROOT_DIR}" ps --all -q "${service}" 2>/dev/null)" || {
			EXACT_SERVICE_CONTAINER_PLAN="${plan}"
			remove_exact_candidate_services "${services[@]}"
			return 1
		}
		container_count="$(printf '%s\n' "${container_ids}" | awk 'NF {n += 1} END {print n + 0}')"
		if [ "${container_count}" -ne 1 ]; then
			echo "[fail] Exact service candidate count is not one for ${service}." >&2
			EXACT_SERVICE_CONTAINER_PLAN="${plan}"
			remove_exact_candidate_services "${services[@]}"
			return 1
		fi
		container_id="$(printf '%s\n' "${container_ids}" | awk 'NF {print; exit}')"
		observed_image_id="$(docker inspect --format '{{.Image}}' "${container_id}" 2>/dev/null)" || {
			EXACT_SERVICE_CONTAINER_PLAN="${plan}${service}"$'\t'"${container_id}"$'\t'"${expected_image_id}"$'\n'
			remove_exact_candidate_services "${services[@]}"
			return 1
		}
		observed_created_state="$(
			docker inspect --format '{{.State.Status}} {{.RestartCount}}' "${container_id}" 2>/dev/null
		)" || {
			EXACT_SERVICE_CONTAINER_PLAN="${plan}${service}"$'\t'"${container_id}"$'\t'"${expected_image_id}"$'\n'
			remove_exact_candidate_services "${services[@]}" || true
			return 1
		}
		if [ "${observed_image_id}" != "${expected_image_id}" ]; then
			echo "[fail] Stopped ${service} candidate does not use the proved target-daemon image ID." >&2
			EXACT_SERVICE_CONTAINER_PLAN="${plan}${service}"$'\t'"${container_id}"$'\t'"${expected_image_id}"$'\n'
			remove_exact_candidate_services "${services[@]}"
			return 1
		fi
		if [ "${observed_created_state}" != "created 0" ]; then
			echo "[fail] ${service} candidate was not proved never-started." >&2
			EXACT_SERVICE_CONTAINER_PLAN="${plan}${service}"$'\t'"${container_id}"$'\t'"${expected_image_id}"$'\n'
			remove_exact_candidate_services "${services[@]}" || true
			return 1
		fi
		plan+="${service}"$'\t'"${container_id}"$'\t'"${expected_image_id}"$'\n'
		container_ids_to_start+=("${container_id}")
	done <<<"${EXACT_SERVICE_IMAGE_PLAN}"
	EXACT_SERVICE_CONTAINER_PLAN="${plan}"

	while IFS=$'\t' read -r service role _reference expected_image_id; do
		[ -n "${service}" ] || continue
		reproved_image_id="$(
			"${RELEASE_TOOL_PYTHON}" "${MANIFEST_HELPER}" loaded-role-daemon-id \
				--root "${ROOT_DIR}" --role "${role}"
		)" || {
			remove_exact_candidate_services "${services[@]}"
			return 1
		}
		if [ "${reproved_image_id}" != "${expected_image_id}" ]; then
			echo "[fail] Release image tag changed after stopped candidate proof for ${service}." >&2
			remove_exact_candidate_services "${services[@]}"
			return 1
		fi
	done <<<"${EXACT_SERVICE_IMAGE_PLAN}"

	if ! docker start "${container_ids_to_start[@]}" >/dev/null; then
		docker stop "${container_ids_to_start[@]}" >/dev/null 2>&1 || true
		remove_exact_candidate_services "${services[@]}"
		return 1
	fi
	for service in "${services[@]}"; do
		assert_exact_started_service "${service}" || {
			docker stop "${container_ids_to_start[@]}" >/dev/null 2>&1 || true
			remove_exact_candidate_services "${services[@]}"
			return 1
		}
	done
	printf '[ok] Started exact stopped candidates by immutable container ID: %s\n' "${services[*]}"
}

wait_for_exact_data_service() {
	local service="$1"
	local expected_reference="$2"
	local expected_image_id="$3"
	local expected_container_id="$4"
	local attempt=0
	local container_id=""
	local container_count=0
	local observed_image_id=""
	local observed_reference_id=""
	local state=""

	while [ "${attempt}" -lt 30 ]; do
		observed_reference_id="$(
			docker image inspect --format '{{.Id}}' "${expected_reference}" 2>/dev/null
		)" || return 1
		[ "${observed_reference_id}" = "${expected_image_id}" ] || return 1
		container_id="$(npcink_ai_cloud_compose "${ROOT_DIR}" ps -q "${service}" 2>/dev/null)" || return 1
		container_count="$(printf '%s\n' "${container_id}" | awk 'NF {n += 1} END {print n + 0}')"
		if [ "${container_count}" -eq 1 ] && [ "${container_id}" = "${expected_container_id}" ]; then
			observed_image_id="$(docker inspect --format '{{.Image}}' "${container_id}" 2>/dev/null || true)"
			state="$(docker inspect --format '{{.State.Running}} {{.State.Restarting}} {{.RestartCount}} {{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "${container_id}" 2>/dev/null || true)"
			if [ "${observed_image_id}" = "${expected_image_id}" ] && \
				[ "${state}" = "true false 0 healthy" ]; then
				printf '[ok] Data service %s uses the frozen exact image ID and is healthy.\n' "${service}"
				return 0
			fi
		fi
		attempt=$((attempt + 1))
		sleep 2
	done
	return 1
}

if [ "${LOAD_MODE}" = "data-only" ]; then
	SERVICES=(postgres redis)
	POSTGRES_REFERENCE="$(data_service_reference postgres)"
	REDIS_REFERENCE="$(data_service_reference redis)"
	echo "[info] Starting data services only: ${SERVICES[*]}"
	npcink_ai_cloud_run_timed "create, prove, and start exact data services" \
		create_prove_and_start_exact_services 0 "${SERVICES[@]}"
	POSTGRES_IMAGE_ID="$(awk -F '\t' '$1 == "postgres" {print $3}' <<<"${EXACT_SERVICE_CONTAINER_PLAN}")"
	REDIS_IMAGE_ID="$(awk -F '\t' '$1 == "redis" {print $3}' <<<"${EXACT_SERVICE_CONTAINER_PLAN}")"
	POSTGRES_CONTAINER_ID="$(awk -F '\t' '$1 == "postgres" {print $2}' <<<"${EXACT_SERVICE_CONTAINER_PLAN}")"
	REDIS_CONTAINER_ID="$(awk -F '\t' '$1 == "redis" {print $2}' <<<"${EXACT_SERVICE_CONTAINER_PLAN}")"
	wait_for_exact_data_service postgres "${POSTGRES_REFERENCE}" "${POSTGRES_IMAGE_ID}" "${POSTGRES_CONTAINER_ID}" || {
		echo "[fail] PostgreSQL did not reach the frozen exact healthy generation." >&2
		exit 1
	}
	wait_for_exact_data_service redis "${REDIS_REFERENCE}" "${REDIS_IMAGE_ID}" "${REDIS_CONTAINER_ID}" || {
		echo "[fail] Redis did not reach the frozen exact healthy generation." >&2
		exit 1
	}
	echo "[ok] Data services are ready for one-off migration."
	exit 0
fi

wait_for_internal_api_ready() {
	npcink_ai_cloud_wait_for_internal_endpoint \
		"${ROOT_DIR}" "/health/ready" "[ok] Staged API is internally ready."
}

wait_for_public_health() {
	# A stale retired ingress container could otherwise make the public probe
	# succeed against the wrong release.
	assert_retired_bundle_services_absent
	if ! npcink_ai_cloud_run_timed "wait for live health" npcink_ai_cloud_wait_for_ready "${BASE_URL}" 20 2; then
		echo "[fail] Cloud API did not become ready at ${BASE_URL}" >&2
		return 1
	fi
}

if [ "${LOAD_MODE}" = "api-only" ]; then
	echo "[info] Starting staged API without workers or public traffic."
	npcink_ai_cloud_run_timed "create, prove, and start exact staged API" \
		create_prove_and_start_exact_services 0 api
	npcink_ai_cloud_run_timed "wait for staged API internal readiness" wait_for_internal_api_ready
	assert_exact_started_service api || {
		echo "[fail] Staged API container identity drifted after readiness." >&2
		exit 1
	}
	echo "[ok] Staged API is internally ready."
	exit 0
fi

if [ "${LOAD_MODE}" = "workers-only" ]; then
	SERVICES=(worker callback-worker ops-worker)
	echo "[info] Starting workers after staged API readiness: ${SERVICES[*]}"
	npcink_ai_cloud_run_timed "create, prove, and start exact workers" \
		create_prove_and_start_exact_services 0 "${SERVICES[@]}"
	exit 0
fi

if [ "${LOAD_MODE}" = "traffic-only" ]; then
	SERVICES=()
	if [ "${SKIP_FRONTEND_IMAGE}" != "1" ]; then
		SERVICES+=(frontend)
	fi
	SERVICES+=(proxy)
	echo "[info] Restoring public traffic last: ${SERVICES[*]}"
	npcink_ai_cloud_run_timed "create, prove, and start exact frontend and proxy" \
		create_prove_and_start_exact_services 1 "${SERVICES[@]}"

	wait_for_public_health
	for service in "${SERVICES[@]}"; do
		assert_exact_started_service "${service}" || {
			echo "[fail] Public service container identity drifted after readiness: ${service}" >&2
			exit 1
		}
	done
	echo "[ok] Public traffic now serves the new Cloud release at ${BASE_URL}"
	exit 0
fi
