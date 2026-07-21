#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
CLOUD_REPO_ROOT="${ROOT_DIR}"
source "${ROOT_DIR}/scripts/mini-cloud-env.sh"
REMOTE_HOST="${REMOTE_HOST:-${MINI_CLOUD_REMOTE_HOST}}"
REMOTE_IP="${REMOTE_IP:-${MINI_CLOUD_REMOTE_IP}}"
REMOTE_ROOT="${REMOTE_ROOT:-${MINI_CLOUD_REMOTE_ROOT}}"
REMOTE_PROJECT_DIR="${REMOTE_PROJECT_DIR:-${MINI_CLOUD_REMOTE_PROJECT_DIR}}"
REMOTE_PROJECT_DIR_SUFFIX="${REMOTE_PROJECT_DIR#\~}"
REMOTE_PROJECT_DIR_SCRIPT="\$HOME${REMOTE_PROJECT_DIR#\~}"
REMOTE_CLOUD_DIR_SCRIPT="${REMOTE_PROJECT_DIR_SCRIPT}"
REMOTE_OVERRIDE_FILE_SCRIPT="${REMOTE_CLOUD_DIR_SCRIPT}/docker-compose.remote-preview.yml"
REMOTE_DOCKER_CONFIG_SCRIPT="${REMOTE_PROJECT_DIR_SCRIPT}/.docker-codex-preview"
PREVIEW_PORT="${PREVIEW_PORT:-8010}"
SERVICES="${SERVICES:-api worker callback-worker ops-worker frontend}"
PREVIEW_STACK_SERVICES="${PREVIEW_STACK_SERVICES:-proxy ${SERVICES}}"
DEPENDENCY_IMAGES=("postgres:16-alpine" "redis:7-alpine" "nginx:1.27-alpine")
PREVIEW_BASE_URL="http://${REMOTE_IP}:${PREVIEW_PORT}"
LIVE_URL="${PREVIEW_BASE_URL}/health/live"
DRY_RUN="${DRY_RUN:-0}"
IMAGE_BUILD_MODE="${IMAGE_BUILD_MODE:-remote}"
ENABLE_TRACE_SINK="${ENABLE_TRACE_SINK:-1}"
REMOTE_JAEGER_VERSION="${REMOTE_JAEGER_VERSION:-2.17.0}"
REMOTE_JAEGER_ARCHIVE_URL="${REMOTE_JAEGER_ARCHIVE_URL:-https://github.com/jaegertracing/jaeger/releases/download/v${REMOTE_JAEGER_VERSION}/jaeger-${REMOTE_JAEGER_VERSION}-darwin-arm64.tar.gz}"
TRACE_EXPORTER_ENDPOINT="${NPCINK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT:-http://host.docker.internal:4318/v1/traces}"
TRACE_QUERY_URL="${NPCINK_CLOUD_OTEL_TRACE_QUERY_URL:-http://${REMOTE_IP}:16686}"
REMOTE_COMPOSE_ENV_PREFIX=""
REMOTE_RUNTIME_ROOT_SCRIPT="\$HOME/.cache/npcink-ai-cloud-mini"
REMOTE_JAEGER_DIR_SCRIPT="${REMOTE_RUNTIME_ROOT_SCRIPT}/jaeger"
REMOTE_JAEGER_BINARY_SCRIPT="${REMOTE_JAEGER_DIR_SCRIPT}/jaeger-${REMOTE_JAEGER_VERSION}-darwin-arm64/jaeger"
REMOTE_JAEGER_LOG_SCRIPT="${REMOTE_JAEGER_DIR_SCRIPT}/jaeger.log"
REMOTE_JAEGER_PID_SCRIPT="${REMOTE_JAEGER_DIR_SCRIPT}/jaeger.pid"

read -r -a SERVICE_ARRAY <<< "${SERVICES}"

image_for_service() {
	case "$1" in
		api)
			printf '%s\n' 'npcink-ai-cloud-api:dev'
			;;
		worker)
			printf '%s\n' 'npcink-ai-cloud-worker:dev'
			;;
		callback-worker)
			printf '%s\n' 'npcink-ai-cloud-callback-worker:dev'
			;;
		ops-worker)
			printf '%s\n' 'npcink-ai-cloud-ops-worker:dev'
			;;
		frontend)
			printf '%s\n' 'npcink-ai-cloud-frontend:dev'
			;;
		proxy)
			printf '%s\n' 'nginx:1.27-alpine'
			;;
		postgres)
			printf '%s\n' 'postgres:16-alpine'
			;;
		redis)
			printf '%s\n' 'redis:7-alpine'
			;;
		*)
			return 1
			;;
	esac
}

append_remote_compose_env() {
	local key="$1"
	local value="${!key-}"
	local quoted=""
	if [ -z "${value}" ]; then
		return 0
	fi
	printf -v quoted '%q' "${value}"
	REMOTE_COMPOSE_ENV_PREFIX+="${key}=${quoted} "
}

REMOTE_COMPOSE_CMD="${REMOTE_COMPOSE_ENV_PREFIX}docker compose -f docker-compose.dev.yml -f docker-compose.remote-preview.yml"

usage() {
	cat <<'EOF'
Usage: scripts/remote-preview-mini.sh [--dry-run] [--build-remote|--build-local]

Sync the local Cloud repo to a remote Mac mini, rebuild the remote dev stack,
and verify direct portal access.

Environment overrides:
  REMOTE_HOST         SSH target (default from scripts/mini-cloud.env)
  REMOTE_IP           Direct portal IP (default from scripts/mini-cloud.env)
  REMOTE_ROOT         Remote Cloud repo root (default: ~/gitee/npcink-ai-cloud)
  REMOTE_PROJECT_DIR  Remote workspace path (default: $REMOTE_ROOT)
  PREVIEW_PORT        Portal port (default: 8010)
  IMAGE_BUILD_MODE    Build mode: remote (default) or local
  SERVICES            Services to build (default: "api worker callback-worker ops-worker frontend")
  ENABLE_TRACE_SINK   Start host Jaeger and wire OTLP/query endpoints (default: 1)
  DRY_RUN             Print actions without changing anything (default: 0)
EOF
}

log() {
	printf '[remote-preview] %s\n' "$*"
}

require_cmd() {
	command -v "$1" >/dev/null 2>&1 || {
		printf '[remote-preview] missing required command: %s\n' "$1" >&2
		exit 1
	}
}

run_local() {
	if [ "${DRY_RUN}" = "1" ]; then
		log "dry-run local: $*"
		return 0
	fi
	"$@"
}

run_remote() {
	local script="$1"
	if [ "${DRY_RUN}" = "1" ]; then
		log "dry-run remote(${REMOTE_HOST}): ${script}"
		return 0
	fi
	ssh "${REMOTE_HOST}" "bash -lc $(printf '%q' "${script}")"
}

run_remote_cloud() {
	local script="$1"
	run_remote "
set -euo pipefail
mkdir -p ${REMOTE_DOCKER_CONFIG_SCRIPT}
if [ ! -e ${REMOTE_DOCKER_CONFIG_SCRIPT}/cli-plugins ] && [ -d \$HOME/.docker/cli-plugins ]; then
	ln -s \$HOME/.docker/cli-plugins ${REMOTE_DOCKER_CONFIG_SCRIPT}/cli-plugins
fi
if [ ! -f ${REMOTE_DOCKER_CONFIG_SCRIPT}/config.json ]; then
	cat > ${REMOTE_DOCKER_CONFIG_SCRIPT}/config.json <<'JSON'
{}
JSON
fi
export DOCKER_CONFIG=${REMOTE_DOCKER_CONFIG_SCRIPT}
cd ${REMOTE_CLOUD_DIR_SCRIPT}
${script}
"
}

is_keychain_credential_error() {
	printf '%s' "$1" | grep -Fq 'keychain cannot be accessed because the current session does not allow user interaction'
}

sync_repo() {
	log "syncing repo to ${REMOTE_HOST}:${REMOTE_PROJECT_DIR}"
	run_local rsync -az --delete \
		--exclude '.git' \
		--exclude 'node_modules' \
		--exclude '.next' \
		--exclude 'build' \
		--exclude 'dist' \
		--exclude '.pnpm-store' \
		--exclude '.pytest_cache' \
		--exclude 'frontend/test-results' \
		--exclude 'frontend/playwright-report' \
		"${CLOUD_REPO_ROOT}/" \
		"${REMOTE_HOST}:${REMOTE_PROJECT_DIR}/"

}

ensure_remote_preview_config() {
	log "updating remote preview config for ${REMOTE_IP}"
run_remote "
set -euo pipefail
mkdir -p ${REMOTE_CLOUD_DIR_SCRIPT}
cat > ${REMOTE_OVERRIDE_FILE_SCRIPT} <<'YAML'
services:
  api:
    environment:
      NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST: ${REMOTE_IP},${REMOTE_IP}:${PREVIEW_PORT},127.0.0.1,127.0.0.1:${PREVIEW_PORT},127.0.0.1:8080,localhost,localhost:${PREVIEW_PORT},api,api:8000,proxy,proxy:8080
      NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST: http://${REMOTE_IP}:${PREVIEW_PORT},http://127.0.0.1:${PREVIEW_PORT},http://localhost:${PREVIEW_PORT}
      NPCINK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT: ${TRACE_EXPORTER_ENDPOINT}
      NPCINK_CLOUD_OTEL_TRACE_QUERY_URL: ${TRACE_QUERY_URL}

  worker:
    environment:
      NPCINK_CLOUD_WORKER_HEARTBEAT_INTERVAL_SECONDS: 60

  callback-worker:
    build:
      context: .
      dockerfile: Dockerfile
    image: npcink-ai-cloud-callback-worker:dev
    command: python -m app.workers.callback_dispatch
    env_file:
      - ./.env
      - ./.env.local
    environment:
      NPCINK_CLOUD_ENVIRONMENT: development
      NPCINK_CLOUD_LOG_LEVEL: DEBUG
      NPCINK_CLOUD_DATABASE_URL: postgresql+psycopg://npcink:npcink@postgres:5432/npcink_ai_cloud
      NPCINK_CLOUD_REDIS_URL: redis://redis:6379/0
      NPCINK_CLOUD_RUNTIME_CALLBACK_WORKER_POLL_SECONDS: 5
      NPCINK_CLOUD_WORKER_HEARTBEAT_INTERVAL_SECONDS: 60
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - .:/app

  ops-worker:
    build:
      context: .
      dockerfile: Dockerfile
    image: npcink-ai-cloud-ops-worker:dev
    command: python -m app.workers.ops_cadence
    env_file:
      - ./.env
      - ./.env.local
    environment:
      NPCINK_CLOUD_ENVIRONMENT: development
      NPCINK_CLOUD_LOG_LEVEL: DEBUG
      NPCINK_CLOUD_DATABASE_URL: postgresql+psycopg://npcink:npcink@postgres:5432/npcink_ai_cloud
      NPCINK_CLOUD_REDIS_URL: redis://redis:6379/0
      NPCINK_CLOUD_WORKER_HEARTBEAT_INTERVAL_SECONDS: 60
      NPCINK_CLOUD_OPS_CADENCE_POLL_SECONDS: 15
      NPCINK_CLOUD_RETENTION_CLEANUP_INTERVAL_SECONDS: 60
      NPCINK_CLOUD_USAGE_ROLLUP_INTERVAL_SECONDS: 60
      NPCINK_CLOUD_ROUTER_DIAGNOSTICS_INTERVAL_SECONDS: 60
      NPCINK_CLOUD_LATENCY_PROBE_INTERVAL_SECONDS: 60
      NPCINK_CLOUD_ALERT_PROVIDER_DEGRADATION_INTERVAL_SECONDS: 60
      NPCINK_CLOUD_PROVIDER_HEALTH_SCAN_INTERVAL_SECONDS: 60
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - .:/app

  frontend:
    environment:
      CLOUD_PUBLIC_BASE_URL: http://${REMOTE_IP}:${PREVIEW_PORT}
      NPCINK_CLOUD_LOCAL_DEBUG_DOCK_ALLOWED_HOSTS: ${REMOTE_IP}
      NPCINK_CLOUD_FRONTEND_DEV_HOST_ALLOWLIST: ${REMOTE_IP},127.0.0.1,localhost,0.0.0.0
YAML
"
}

ensure_remote_trace_sink() {
	if [ "${ENABLE_TRACE_SINK}" != "1" ]; then
		log "trace sink setup disabled"
		return 0
	fi
	log "ensuring remote host Jaeger trace sink"
	run_remote "
set -euo pipefail
mkdir -p ${REMOTE_JAEGER_DIR_SCRIPT}

if [ ! -x ${REMOTE_JAEGER_BINARY_SCRIPT} ]; then
	tmp_archive=${REMOTE_JAEGER_DIR_SCRIPT}/jaeger-${REMOTE_JAEGER_VERSION}.tar.gz
	curl -fsSL ${REMOTE_JAEGER_ARCHIVE_URL} -o \${tmp_archive}
	rm -rf ${REMOTE_JAEGER_DIR_SCRIPT}/jaeger-${REMOTE_JAEGER_VERSION}-darwin-arm64
	tar -xzf \${tmp_archive} -C ${REMOTE_JAEGER_DIR_SCRIPT}
	rm -f \${tmp_archive}
fi

if [ -f ${REMOTE_JAEGER_PID_SCRIPT} ]; then
	kill \$(cat ${REMOTE_JAEGER_PID_SCRIPT}) >/dev/null 2>&1 || true
	rm -f ${REMOTE_JAEGER_PID_SCRIPT}
fi
pkill -x jaeger >/dev/null 2>&1 || true
pkill -f '${REMOTE_JAEGER_BINARY_SCRIPT}' >/dev/null 2>&1 || true
for _ in \$(seq 1 10); do
	if ! lsof -nP -iTCP:8888 -sTCP:LISTEN >/dev/null 2>&1 \
		&& ! lsof -nP -iTCP:4318 -sTCP:LISTEN >/dev/null 2>&1; then
		break
	fi
	sleep 1
done
nohup ${REMOTE_JAEGER_BINARY_SCRIPT} \
	--set=receivers.otlp.protocols.http.endpoint=0.0.0.0:4318 \
	> ${REMOTE_JAEGER_LOG_SCRIPT} 2>&1 &
echo \$! > ${REMOTE_JAEGER_PID_SCRIPT}

for _ in \$(seq 1 30); do
	if lsof -nP -iTCP:4318 -sTCP:LISTEN | grep -q '0.0.0.0:4318\\|\\*:4318' \
		&& lsof -nP -iTCP:16686 -sTCP:LISTEN >/dev/null 2>&1; then
		exit 0
	fi
	sleep 1
done

echo '[remote-preview] host Jaeger failed to expose public OTLP/query listeners' >&2
tail -n 80 ${REMOTE_JAEGER_LOG_SCRIPT} >&2 || true
exit 1
"
}

build_local_images() {
	log "building local dev images: ${SERVICES}"
	run_local docker compose -f "${CLOUD_REPO_ROOT}/docker-compose.dev.yml" build ${SERVICES}
}

ensure_local_image_available() {
	local image="$1"
	if docker image inspect "${image}" >/dev/null 2>&1; then
		return 0
	fi
	log "pulling local image for remote transfer: ${image}"
	run_local docker pull "${image}"
}

transfer_dependency_images() {
	local images=()
	local image=""
	for image in "${DEPENDENCY_IMAGES[@]}"; do
		ensure_local_image_available "${image}"
		images+=("${image}")
	done
	log "streaming dependency images to ${REMOTE_HOST}"
	if [ "${DRY_RUN}" = "1" ]; then
		log "dry-run local: docker save ${images[*]} | ssh ${REMOTE_HOST} 'docker load'"
		return 0
	fi
	docker save "${images[@]}" | ssh "${REMOTE_HOST}" 'docker load'
}

transfer_images() {
	local images=()
	local service=""
	local image=""
	for service in "${SERVICE_ARRAY[@]}"; do
		if ! image="$(image_for_service "${service}")"; then
			printf '[remote-preview] unsupported service for local image transfer: %s\n' "${service}" >&2
			exit 1
		fi
		images+=("${image}")
	done
	log "streaming docker images to ${REMOTE_HOST}"
	if [ "${DRY_RUN}" = "1" ]; then
		log "dry-run local: docker save ${images[*]} | ssh ${REMOTE_HOST} 'docker load'"
		return 0
	fi
	docker save "${images[@]}" | ssh "${REMOTE_HOST}" 'docker load'
}

start_remote_stack() {
	log "starting remote cloud dev stack"
	run_remote_cloud "${REMOTE_COMPOSE_CMD} up -d --no-build --pull never ${PREVIEW_STACK_SERVICES}"
}

reload_remote_proxy() {
	log "reloading remote proxy config"
	run_remote_cloud "
proxy_container=\$(${REMOTE_COMPOSE_CMD} ps -q proxy)
if [ -n \"\${proxy_container}\" ]; then
	${REMOTE_COMPOSE_CMD} exec -T proxy nginx -s reload >/dev/null 2>&1 || ${REMOTE_COMPOSE_CMD} restart proxy
fi
"
}

build_remote_images() {
	log "building remote dev images: ${SERVICES}"
	run_remote_cloud "${REMOTE_COMPOSE_CMD} build ${SERVICES}"
}

ensure_remote_dependencies() {
	log "starting remote preview dependencies"
	local output=""
	if output="$(run_remote_cloud "${REMOTE_COMPOSE_CMD} up -d --pull never postgres redis" 2>&1)"; then
		printf '%s\n' "${output}"
		return 0
	fi
	printf '%s\n' "${output}" >&2
	if ! is_keychain_credential_error "${output}"; then
		return 1
	fi
	log "remote dependency startup hit Docker keychain auth; falling back to local dependency image transfer"
	transfer_dependency_images
	run_remote_cloud "${REMOTE_COMPOSE_CMD} up -d --pull never postgres redis"
}

build_or_transfer_service_images() {
	if [ "${IMAGE_BUILD_MODE}" = "local" ]; then
		build_local_images
		transfer_images
		return 0
	fi

	local output=""
	if output="$(run_remote_cloud "${REMOTE_COMPOSE_CMD} build ${SERVICES}" 2>&1)"; then
		printf '%s\n' "${output}"
		return 0
	fi
	printf '%s\n' "${output}" >&2
	if ! is_keychain_credential_error "${output}"; then
		return 1
	fi
	log "remote image build hit Docker keychain auth; falling back to local build + image transfer"
	build_local_images
	transfer_images
}

run_remote_migrations() {
	log "running remote alembic upgrade head before preview start"
	run_remote_cloud "${REMOTE_COMPOSE_CMD} run --rm api alembic upgrade head"
}

verify_preview_http() {
	log "verifying preview live endpoint at ${LIVE_URL}"
	if [ "${DRY_RUN}" = "1" ]; then
		log "dry-run local: curl ${LIVE_URL}"
		return 0
	fi
	local attempt=0
	local max_attempts=15
	while [ "${attempt}" -lt "${max_attempts}" ]; do
		if [ "$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "${LIVE_URL}")" = "200" ]; then
			return 0
		fi
		attempt=$((attempt + 1))
		sleep 2
	done
	return 1
}

verify_remote_services_running() {
	log "verifying remote service runtime state"
	run_remote_cloud "
for service in ${SERVICES}; do
	container_id=\"\$(${REMOTE_COMPOSE_CMD} ps -q \"\${service}\")\"
	if [ -z \"\${container_id}\" ]; then
		echo \"[remote-preview] service missing from compose ps: \${service}\" >&2
		exit 1
	fi
	state=\"\$(docker inspect -f '{{.State.Status}}' \"\${container_id}\")\"
	if [ \"\${state}\" != 'running' ]; then
		echo \"[remote-preview] service not running: \${service} state=\${state}\" >&2
		exit 1
	fi
done
"
}

verify_remote_database_head() {
	log "verifying remote database schema is at Alembic head"
	run_remote_cloud "${REMOTE_COMPOSE_CMD} exec -T api python -m app.dev.baseline_status --skip-internal-auth-token >/tmp/magick-ai-preview-baseline.json && cat /tmp/magick-ai-preview-baseline.json"
}

verify_remote_operational_readiness() {
	log "verifying direct operational readiness inside api container"
	run_remote_cloud "
internal_token=\"\$(${REMOTE_COMPOSE_CMD} exec -T api sh -lc 'printf %s \"\${NPCINK_CLOUD_INTERNAL_AUTH_TOKEN:-}\"')\"
if [ -z \"\${internal_token}\" ]; then
	echo '[remote-preview] operational readiness failed: NPCINK_CLOUD_INTERNAL_AUTH_TOKEN missing' >&2
	exit 1
fi

${REMOTE_COMPOSE_CMD} exec -T api python - <<'PY'
import os
import time
import urllib.error
import urllib.request

token = os.environ.get('NPCINK_CLOUD_INTERNAL_AUTH_TOKEN', '')
headers = {
    'X-Npcink-Internal-Token': token,
    'traceparent': '00-99999999999999999999999999999999-aaaaaaaaaaaaaaaa-01',
}

last_status = None
last_body = ''
for _ in range(24):
    request = urllib.request.Request(
        'http://127.0.0.1:8000/health/operational-ready',
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode('utf-8')
            if response.status == 200:
                print(body)
                raise SystemExit(0)
            last_status = response.status
            last_body = body
    except urllib.error.HTTPError as exc:
        last_status = exc.code
        last_body = exc.read().decode('utf-8')
    time.sleep(5)

raise SystemExit(
    f'operational readiness never became green: status={last_status} body={last_body}'
)
PY
"
}

verify_remote_trace_sink() {
	if [ "${ENABLE_TRACE_SINK}" != "1" ]; then
		log "trace sink verification skipped"
		return 0
	fi
	log "verifying trace sink receives npcink-ai-cloud spans"
	run_remote_cloud "
service_name=\"\$(${REMOTE_COMPOSE_CMD} exec -T api sh -lc 'printf %s \"\${NPCINK_CLOUD_OTEL_SERVICE_NAME:-npcink-ai-cloud}\"')\"
trace_query_url=\"\$(${REMOTE_COMPOSE_CMD} exec -T api sh -lc 'printf %s \"\${NPCINK_CLOUD_OTEL_TRACE_QUERY_URL:-}\"')\"
trace_exporter=\"\$(${REMOTE_COMPOSE_CMD} exec -T api sh -lc 'printf %s \"\${NPCINK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT:-}\"')\"
if [ -z \"\${trace_query_url}\" ] || [ -z \"\${trace_exporter}\" ]; then
	echo '[remote-preview] trace verification failed: exporter/query env missing from api container' >&2
	exit 1
fi

${REMOTE_COMPOSE_CMD} exec -T api python -c \"from app.core.config import Settings; from app.core.tracing import configure_tracing; from opentelemetry import trace; settings=Settings(_env_file=None); configure_tracing(settings); tracer=trace.get_tracer('mini.preview.smoke'); span=tracer.start_span('mini-preview-smoke-span'); span.set_attribute('smoke.kind', 'mini-preview'); span.end(); trace.get_tracer_provider().force_flush(); print('manual-span-flushed')\"

services_json=''
for _ in \$(seq 1 24); do
	services_json=\"\$(curl -fsS http://127.0.0.1:16686/api/services || true)\"
	if printf '%s' \"\${services_json}\" | grep -Fq \"\${service_name}\"; then
		printf '%s\n' \"\${services_json}\"
		exit 0
	fi
	sleep 2
done

echo \"[remote-preview] trace sink never observed service \${service_name}; query_url=\${trace_query_url} exporter=\${trace_exporter}\" >&2
printf '%s\n' \"\${services_json}\" >&2
exit 1
"
}

verify_remote_logs_clean() {
	log "checking recent remote logs for startup fatals"
	run_remote_cloud "
for service in ${SERVICES}; do
	logs=\"\$(${REMOTE_COMPOSE_CMD} logs --since 120s --no-color \"\${service}\" 2>&1 || true)\"
	if printf '%s' \"\${logs}\" | grep -Eiq 'Traceback \\(most recent call last\\)|sqlalchemy\\.exc\\.|alembic\\.util\\.exc\\.|ModuleNotFoundError|ProgrammingError|OperationalError'; then
		echo \"[remote-preview] fatal startup log detected in \${service}\" >&2
		printf '%s\n' \"\${logs}\" >&2
		exit 1
	fi
done
"
}

show_remote_status() {
	log "remote compose status"
	run_remote_cloud "${REMOTE_COMPOSE_CMD} ps"
}

main() {
	while [ "$#" -gt 0 ]; do
		case "$1" in
			--)
				;;
			--help|-h)
				usage
				exit 0
				;;
			--dry-run)
				DRY_RUN=1
				;;
			--build-local)
				IMAGE_BUILD_MODE="local"
				;;
			--build-remote)
				IMAGE_BUILD_MODE="remote"
				;;
			*)
				printf '[remote-preview] unknown argument: %s\n' "$1" >&2
				usage >&2
				exit 1
				;;
		esac
		shift
	done

	require_cmd rsync
	require_cmd ssh
	require_cmd curl
	if [ "${IMAGE_BUILD_MODE}" != "local" ] && [ "${IMAGE_BUILD_MODE}" != "remote" ]; then
		printf '[remote-preview] unsupported IMAGE_BUILD_MODE: %s\n' "${IMAGE_BUILD_MODE}" >&2
		exit 1
	fi

	sync_repo
	run_remote "command -v python3 >/dev/null 2>&1"
	ensure_remote_trace_sink
	ensure_remote_preview_config
	ensure_remote_dependencies
	build_or_transfer_service_images
	run_remote_migrations
	start_remote_stack
	reload_remote_proxy
	verify_preview_http
	verify_remote_services_running
	verify_remote_database_head
	verify_remote_operational_readiness
	verify_remote_trace_sink
	verify_remote_logs_clean
	show_remote_status

	log "preview ready: ${PREVIEW_BASE_URL} (build mode: ${IMAGE_BUILD_MODE})"
}

	main "$@"
