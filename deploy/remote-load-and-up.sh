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
RETIRED_BUNDLE_SERVICES=(postgres caddy jaeger otel-collector)
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
CONFIG_DIR_HOST="${NPCINK_CLOUD_CONFIG_DIR_HOST:-$(dirname "${ROOT_DIR}")/shared/config}"
PRESERVE_FIRST_INSTALL_POSTGRES="${NPCINK_CLOUD_PRESERVE_FIRST_INSTALL_POSTGRES:-0}"

if [ "${PRESERVE_FIRST_INSTALL_POSTGRES}" != "0" ] && \
	[ "${PRESERVE_FIRST_INSTALL_POSTGRES}" != "1" ]; then
	echo "[fail] NPCINK_CLOUD_PRESERVE_FIRST_INSTALL_POSTGRES must be 0 or 1." >&2
	exit 1
fi
if [ "${PRESERVE_FIRST_INSTALL_POSTGRES}" = "1" ] && [ "${LOAD_MODE}" != "traffic-only" ]; then
	echo "[fail] PostgreSQL rollback preservation is only valid during first-install traffic activation." >&2
	exit 1
fi

if [[ "${CONFIG_DIR_HOST}" != /* ]] || [ -L "${CONFIG_DIR_HOST}" ]; then
	echo "[fail] NPCINK_CLOUD_CONFIG_DIR_HOST must name a non-symlink absolute path." >&2
	exit 1
fi
case "${LOAD_MODE}" in
	api-only|workers-only|traffic-only)
		if [ ! -d "${CONFIG_DIR_HOST}" ]; then
			echo "[fail] NPCINK_CLOUD_CONFIG_DIR_HOST must name the prepared shared configuration directory." >&2
			exit 1
		fi
		;;
esac
export NPCINK_CLOUD_CONFIG_DIR_HOST="${CONFIG_DIR_HOST}"

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

is_runtime_compose_file() {
	[ "$(basename "${COMPOSE_FILE}")" = "docker-compose.runtime.yml" ]
}

RUNTIME_NETWORK_STATE_FILE=""

runtime_network_state_file() {
	local state_dir=""
	state_dir="$(npcink_ai_cloud_release_state_dir "${ROOT_DIR}")" || return 1
	printf '%s/runtime-network.env' "${state_dir}"
}

discover_runtime_network_contract() {
	local expected_proxy_ipv4="${1:-}"
	local network_ids=""
	local network_count=0
	local network_id=""
	local driver=""
	local internal=""
	local ipam_count=""
	local subnet=""
	local gateway=""
	local endpoints=""
	local container_id=""
	local endpoint_cidr=""
	local endpoint_ip=""
	local endpoint_project=""
	local endpoint_service=""
	local proxy_ips=""
	local occupied_ips=""

	network_ids="$(docker network ls --quiet \
		--filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
		--filter "label=com.docker.compose.network=default")" || return 1
	network_count="$(printf '%s\n' "${network_ids}" | awk 'NF {n += 1} END {print n + 0}')"
	if [ "${network_count}" -eq 0 ]; then
		subnet="172.28.0.0/24"
		gateway="172.28.0.1"
	elif [ "${network_count}" -ne 1 ]; then
		echo "[fail] Managed Compose default network is not unique." >&2
		return 1
	else
		network_id="$(printf '%s\n' "${network_ids}" | awk 'NF {print; exit}')"
		[[ "${network_id}" =~ ^[0-9a-f]{12,64}$ ]] || {
			echo "[fail] Managed Compose default network ID is invalid." >&2
			return 1
		}
		driver="$(docker network inspect --format '{{.Driver}}' "${network_id}")" || return 1
		internal="$(docker network inspect --format '{{.Internal}}' "${network_id}")" || return 1
		ipam_count="$(docker network inspect --format '{{len .IPAM.Config}}' "${network_id}")" || return 1
		if [ "${driver}" != "bridge" ] || [ "${internal}" != "false" ] || [ "${ipam_count}" != "1" ]; then
			echo "[fail] Managed Compose default network must be one non-internal bridge IPv4 network." >&2
			return 1
		fi
		subnet="$(docker network inspect \
			--format '{{(index .IPAM.Config 0).Subnet}}' "${network_id}")" || return 1
		gateway="$(docker network inspect \
			--format '{{(index .IPAM.Config 0).Gateway}}' "${network_id}")" || return 1
		endpoints="$(docker network inspect \
			--format '{{range $id, $container := .Containers}}{{$id}}|{{$container.IPv4Address}}{{println}}{{end}}' \
			"${network_id}")" || return 1
	fi
	while IFS='|' read -r container_id endpoint_cidr; do
		[ -n "${container_id}" ] || continue
		[[ "${container_id}" =~ ^[0-9a-f]{12,64}$ ]] || {
			echo "[fail] Managed network contains an invalid endpoint ID." >&2
			return 1
		}
		endpoint_project="$(docker inspect \
			--format '{{index .Config.Labels "com.docker.compose.project"}}' \
			"${container_id}")" || return 1
		endpoint_service="$(docker inspect \
			--format '{{index .Config.Labels "com.docker.compose.service"}}' \
			"${container_id}")" || return 1
		if [ "${endpoint_project}" != "${COMPOSE_PROJECT_NAME_EFFECTIVE}" ] || [ -z "${endpoint_service}" ]; then
			echo "[fail] Managed Compose network contains a foreign or unlabelled endpoint." >&2
			return 1
		fi
		endpoint_ip="${endpoint_cidr%%/*}"
		occupied_ips+="${endpoint_ip},"
		if [ "${endpoint_service}" = "proxy" ]; then
			proxy_ips+="${endpoint_ip},"
		fi
	done <<<"${endpoints}"

	"${RELEASE_TOOL_PYTHON}" - \
		"${subnet}" "${gateway}" "${proxy_ips}" "${occupied_ips}" \
		"${expected_proxy_ipv4}" <<'PY'
from __future__ import annotations

import ipaddress
import sys

subnet_text, gateway_text, proxy_text, occupied_text, expected_proxy_text = sys.argv[1:]
try:
    network = ipaddress.ip_network(subnet_text, strict=True)
    gateway = ipaddress.ip_address(gateway_text)
    proxy_values = [
        ipaddress.ip_address(value)
        for value in proxy_text.rstrip(",").split(",")
        if value
    ]
    proxy_ips = set(proxy_values)
    occupied = {
        ipaddress.ip_address(value)
        for value in occupied_text.rstrip(",").split(",")
        if value
    }
    expected_proxy = (
        ipaddress.ip_address(expected_proxy_text) if expected_proxy_text else None
    )
except ValueError as exc:
    raise SystemExit(f"[fail] Managed Compose network IPv4 contract is invalid: {exc}") from exc

if network.version != 4 or gateway.version != 4:
    raise SystemExit("[fail] Managed Compose runtime requires an IPv4 network.")
if gateway not in network or gateway in {network.network_address, network.broadcast_address}:
    raise SystemExit("[fail] Managed Compose network gateway is outside its usable subnet.")
for address in proxy_ips | occupied:
    if (
        address.version != 4
        or address not in network
        or address in {network.network_address, network.broadcast_address, gateway}
    ):
        raise SystemExit("[fail] Managed Compose endpoint is outside its usable IPv4 subnet.")
if len(proxy_values) > 1:
    raise SystemExit("[fail] Managed Compose network has multiple proxy endpoint addresses.")
if expected_proxy is not None and (
    expected_proxy.version != 4
    or expected_proxy not in network
    or expected_proxy in {network.network_address, network.broadcast_address, gateway}
):
    raise SystemExit("[fail] Frozen runtime proxy IPv4 address is outside the usable subnet.")

if proxy_ips:
    proxy = next(iter(proxy_ips))
    if expected_proxy is not None and proxy != expected_proxy:
        raise SystemExit("[fail] Managed proxy endpoint differs from the frozen runtime proxy IPv4 address.")
elif expected_proxy is not None:
    if expected_proxy in occupied:
        raise SystemExit("[fail] Frozen runtime proxy IPv4 address is occupied by a non-proxy endpoint.")
    proxy = expected_proxy
else:
    preferred = network.network_address + 10
    proxy = None
    if (
        preferred in network
        and preferred not in {network.network_address, network.broadcast_address, gateway}
        and preferred not in occupied
    ):
        proxy = preferred
    if proxy is None:
        # Docker allocates dynamic addresses from the low end. Search the high
        # end first so the frozen static proxy address remains collision-free
        # while data/API/worker candidates are created in later phases.
        upper = int(network.broadcast_address) - 1
        lower = int(network.network_address) + 1
        for value in range(upper, max(lower - 1, upper - 4096), -1):
            candidate = ipaddress.ip_address(value)
            if candidate != gateway and candidate not in occupied:
                proxy = candidate
                break
    if proxy is None:
        raise SystemExit("[fail] Managed Compose network has no free static proxy IPv4 address.")

print(f"{network.with_prefixlen}\t{gateway}\t{proxy}")
PY
}

load_runtime_network_contract() {
	local state_file="$1"
	local parsed=""
	local subnet=""
	local gateway=""
	local proxy_ipv4=""
	[ -f "${state_file}" ] && [ ! -L "${state_file}" ] && [ -O "${state_file}" ] &&
		[ "$(npcink_ai_cloud_mode_of "${state_file}" 2>/dev/null || true)" = "600" ] || {
		echo "[fail] Frozen runtime network state must be an owner-only mode-0600 regular file." >&2
		return 1
	}
	parsed="$("${RELEASE_TOOL_PYTHON}" - \
		"${state_file}" "${COMPOSE_PROJECT_NAME_EFFECTIVE}" <<'PY'
from __future__ import annotations

import ipaddress
import sys
from pathlib import Path

path = Path(sys.argv[1])
allowed = {
    "NPCINK_CLOUD_RUNTIME_NETWORK_PROJECT",
    "NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET",
    "NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY",
    "NPCINK_CLOUD_RUNTIME_PROXY_IPV4",
}
values: dict[str, str] = {}
for line in path.read_text(encoding="utf-8").splitlines():
    if not line or "=" not in line:
        raise SystemExit("[fail] Frozen runtime network state has an invalid assignment.")
    key, value = line.split("=", 1)
    if key not in allowed or key in values or not value:
        raise SystemExit("[fail] Frozen runtime network state has unexpected or duplicate keys.")
    values[key] = value
if set(values) != allowed:
    raise SystemExit("[fail] Frozen runtime network state is incomplete.")
if values["NPCINK_CLOUD_RUNTIME_NETWORK_PROJECT"] != sys.argv[2]:
    raise SystemExit("[fail] Frozen runtime network state belongs to another Compose project.")

network = ipaddress.ip_network(values["NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET"], strict=True)
gateway = ipaddress.ip_address(values["NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY"])
proxy = ipaddress.ip_address(values["NPCINK_CLOUD_RUNTIME_PROXY_IPV4"])
if network.version != 4 or gateway.version != 4 or proxy.version != 4:
    raise SystemExit("[fail] Frozen runtime network state must contain IPv4 values.")
if gateway not in network or proxy not in network:
    raise SystemExit("[fail] Frozen runtime network gateway/proxy is outside the subnet.")
if len({network.network_address, network.broadcast_address, gateway, proxy}) != 4:
    raise SystemExit("[fail] Frozen runtime network gateway/proxy is not a distinct usable host.")
print(f"{network.with_prefixlen}\t{gateway}\t{proxy}")
PY
)" || return 1
	IFS=$'\t' read -r subnet gateway proxy_ipv4 <<<"${parsed}"
	export NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET="${subnet}"
	export NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY="${gateway}"
	export NPCINK_CLOUD_RUNTIME_PROXY_IPV4="${proxy_ipv4}"
}

freeze_runtime_network_contract() {
	local state_file="$1"
	local state_dir=""
	local discovered=""
	local subnet=""
	local gateway=""
	local proxy_ipv4=""
	local temporary=""
	state_dir="$(dirname "${state_file}")"
	[ -d "${state_dir}" ] && [ ! -L "${state_dir}" ] && [ -O "${state_dir}" ] &&
		[ "$(npcink_ai_cloud_mode_of "${state_dir}" 2>/dev/null || true)" = "700" ] || {
		echo "[fail] Runtime network state requires the protected release-state directory." >&2
		return 1
	}
	if [ -e "${state_file}" ] || [ -L "${state_file}" ]; then
		load_runtime_network_contract "${state_file}" || return 1
		discovered="$(discover_runtime_network_contract \
			"${NPCINK_CLOUD_RUNTIME_PROXY_IPV4}")" || return 1
		IFS=$'\t' read -r subnet gateway proxy_ipv4 <<<"${discovered}"
		if [ "${NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET}" != "${subnet}" ] ||
			[ "${NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY}" != "${gateway}" ] ||
			[ "${NPCINK_CLOUD_RUNTIME_PROXY_IPV4}" != "${proxy_ipv4}" ]; then
			echo "[fail] Existing frozen runtime network state differs from current managed network facts." >&2
			return 1
		fi
		return 0
	fi
	discovered="$(discover_runtime_network_contract)" || return 1
	IFS=$'\t' read -r subnet gateway proxy_ipv4 <<<"${discovered}"
	temporary="$(mktemp "${state_dir}/.runtime-network.env.XXXXXX")" || return 1
	chmod 0600 "${temporary}" || {
		rm -f -- "${temporary}"
		return 1
	}
	if ! printf '%s\n' \
		"NPCINK_CLOUD_RUNTIME_NETWORK_PROJECT=${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
		"NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET=${subnet}" \
		"NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY=${gateway}" \
		"NPCINK_CLOUD_RUNTIME_PROXY_IPV4=${proxy_ipv4}" >"${temporary}"; then
		rm -f -- "${temporary}"
		return 1
	fi
	mv -f -- "${temporary}" "${state_file}" || {
		rm -f -- "${temporary}"
		return 1
	}
	"${RELEASE_TOOL_PYTHON}" - "${state_file}" <<'PY' || return 1
from __future__ import annotations

import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
with path.open("rb") as handle:
    os.fsync(handle.fileno())
directory_fd = os.open(path.parent, os.O_RDONLY)
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
	load_runtime_network_contract "${state_file}"
}

assert_runtime_network_contract() {
	local discovered=""
	local subnet=""
	local gateway=""
	local proxy_ipv4=""
	discovered="$(discover_runtime_network_contract \
		"${NPCINK_CLOUD_RUNTIME_PROXY_IPV4}")" || return 1
	IFS=$'\t' read -r subnet gateway proxy_ipv4 <<<"${discovered}"
	if [ "${NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET}" != "${subnet}" ] ||
		[ "${NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY}" != "${gateway}" ] ||
		[ "${NPCINK_CLOUD_RUNTIME_PROXY_IPV4}" != "${proxy_ipv4}" ]; then
		echo "[fail] Managed Compose network drifted from the frozen runtime network contract." >&2
		return 1
	fi
}

prepare_runtime_nginx_config() {
	local state_file="$1"
	local mode="verify"
	local rendered_path=""
	if [ "${LOAD_MODE}" = "prepare-only" ]; then
		mode="create"
	fi
	rendered_path="$("${RELEASE_TOOL_PYTHON}" - \
		"${ROOT_DIR}/deploy/nginx.prod.conf" \
		"$(dirname "${state_file}")/nginx.runtime.conf" \
		"${NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY}" "${mode}" <<'PY'
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
gateway = sys.argv[3]
mode = sys.argv[4]
parent_stat = target.parent.lstat()
if (
    not stat.S_ISDIR(parent_stat.st_mode)
    or parent_stat.st_uid != os.geteuid()
    or stat.S_IMODE(parent_stat.st_mode) != 0o700
):
    raise SystemExit("[fail] Runtime NGINX config requires the protected release-state directory.")
source_stat = source.lstat()
if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_uid != os.geteuid():
    raise SystemExit("[fail] Bundled NGINX config must be an owner-controlled regular file.")
source_text = source.read_text(encoding="utf-8")
default_trust = "    set_real_ip_from 172.28.0.1;"
if source_text.count(default_trust) != 1:
    raise SystemExit("[fail] Bundled NGINX gateway trust anchor is not unique.")
expected = source_text.replace(default_trust, f"    set_real_ip_from {gateway};", 1)

if target.exists() or target.is_symlink():
    target_stat = target.lstat()
    if (
        not stat.S_ISREG(target_stat.st_mode)
        or target_stat.st_uid != os.geteuid()
        or stat.S_IMODE(target_stat.st_mode) != 0o600
        or target.read_text(encoding="utf-8") != expected
    ):
        raise SystemExit("[fail] Frozen runtime NGINX config is unsafe or drifted.")
elif mode == "create":
    temporary = target.with_name(f".{target.name}.{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(expected)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()
else:
    raise SystemExit("[fail] Frozen runtime NGINX config is missing.")
print(target)
PY
)" || return 1
	export NPCINK_CLOUD_RUNTIME_NGINX_CONFIG_PATH="${rendered_path}"
}

prepare_runtime_network_contract() {
	is_runtime_compose_file || return 0
	RUNTIME_NETWORK_STATE_FILE="$(runtime_network_state_file)" || return 1
	if [ "${LOAD_MODE}" = "prepare-only" ]; then
		freeze_runtime_network_contract "${RUNTIME_NETWORK_STATE_FILE}" || return 1
	else
		load_runtime_network_contract "${RUNTIME_NETWORK_STATE_FILE}" || return 1
		assert_runtime_network_contract || return 1
	fi
	prepare_runtime_nginx_config "${RUNTIME_NETWORK_STATE_FILE}" || return 1
	printf '[ok] Runtime network contract is frozen: subnet=%s gateway=%s proxy=%s\n' \
		"${NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET}" \
		"${NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY}" \
		"${NPCINK_CLOUD_RUNTIME_PROXY_IPV4}"
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
		if [ "${PRESERVE_FIRST_INSTALL_POSTGRES}" = "1" ] && [ "${service_name}" = "postgres" ]; then
			continue
		fi
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

remove_non_database_retired_orphans() {
	local service_name=""
	local container_ids=""
	for service_name in caddy jaeger otel-collector; do
		container_ids="$(docker ps -aq \
			--filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
			--filter "label=com.docker.compose.service=${service_name}")"
		if [ -n "${container_ids}" ]; then
			docker rm -f ${container_ids} >/dev/null
		fi
	done
	assert_retired_bundle_services_absent
}

stop_retired_postgres_for_first_install_rollback() {
	local container_id=""
	local container_ids=""
	container_ids="$(docker ps -aq \
		--filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}" \
		--filter "label=com.docker.compose.service=postgres")"
	while IFS= read -r container_id; do
		[ -n "${container_id}" ] || continue
		docker stop --time 30 "${container_id}" >/dev/null
		if [ "$(docker inspect --format '{{.State.Running}}' "${container_id}")" != "false" ]; then
			echo "[fail] Retired PostgreSQL rollback container could not be proved stopped." >&2
			return 1
		fi
	done <<<"${container_ids}"
	echo "[ok] Retired local PostgreSQL container is stopped but retained for pre-install rollback."
}

prepare_runtime_network_contract
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
		redis) printf '%s' 'npcink-ai-cloud-external-redis:prod' ;;
		*) return 1 ;;
	esac
}

release_service_role() {
	case "$1" in
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
	if is_runtime_compose_file && ! assert_runtime_network_contract; then
		echo "[fail] Exact service candidates do not use the frozen runtime network contract." >&2
		remove_exact_candidate_services "${services[@]}" || true
		return 1
	fi

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
	SERVICES=(redis)
	REDIS_REFERENCE="$(data_service_reference redis)"
	echo "[info] Starting the release-bundled data substrate only: ${SERVICES[*]}"
	npcink_ai_cloud_run_timed "create, prove, and start exact bundled data substrate" \
		create_prove_and_start_exact_services 0 "${SERVICES[@]}"
	REDIS_IMAGE_ID="$(awk -F '\t' '$1 == "redis" {print $3}' <<<"${EXACT_SERVICE_CONTAINER_PLAN}")"
	REDIS_CONTAINER_ID="$(awk -F '\t' '$1 == "redis" {print $2}' <<<"${EXACT_SERVICE_CONTAINER_PLAN}")"
	wait_for_exact_data_service redis "${REDIS_REFERENCE}" "${REDIS_IMAGE_ID}" "${REDIS_CONTAINER_ID}" || {
		echo "[fail] Redis did not reach the frozen exact healthy generation." >&2
		exit 1
	}
	echo "[ok] Redis is ready; PostgreSQL remains an external runtime dependency."
	exit 0
fi

wait_for_internal_api_ready() {
	local installation_state=""
	installation_state="$("${RELEASE_TOOL_PYTHON}" - "${CONFIG_DIR_HOST}/install-state.json" <<'PY'
import json
import sys
from pathlib import Path

try:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    raise SystemExit(1)
state = payload.get("installation_state")
if state not in {"pending", "initializing", "complete"}:
    raise SystemExit(1)
print(state)
PY
	)" || {
		echo "[fail] Installation state could not be read before API readiness." >&2
		return 1
	}
	if [ "${installation_state}" = "complete" ]; then
		npcink_ai_cloud_wait_for_internal_endpoint \
			"${ROOT_DIR}" "/health/ready" "[ok] Installed API is internally ready."
		return
	fi
	npcink_ai_cloud_wait_for_internal_endpoint \
		"${ROOT_DIR}" "/health/live" "[ok] Setup-capable API is live."
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
	remove_orphans=1
	if [ "${PRESERVE_FIRST_INSTALL_POSTGRES}" = "1" ]; then
		remove_orphans=0
		remove_non_database_retired_orphans
		echo "[info] Preserving the retired local PostgreSQL container only until first-install finalize or rollback."
	fi
	npcink_ai_cloud_run_timed "create, prove, and start exact frontend and proxy" \
		create_prove_and_start_exact_services "${remove_orphans}" "${SERVICES[@]}"

	wait_for_public_health
	for service in "${SERVICES[@]}"; do
		assert_exact_started_service "${service}" || {
			echo "[fail] Public service container identity drifted after readiness: ${service}" >&2
			exit 1
		}
	done
	if [ "${PRESERVE_FIRST_INSTALL_POSTGRES}" = "1" ]; then
		# Stop only after the new public path is proved. Every earlier
		# pre-migration failure therefore leaves the previous PostgreSQL running;
		# explicit first-install rollback can later recreate/start it from the
		# preserved previous Compose release.
		stop_retired_postgres_for_first_install_rollback
	fi
	echo "[ok] Public traffic now serves the new Cloud release at ${BASE_URL}"
	exit 0
fi
