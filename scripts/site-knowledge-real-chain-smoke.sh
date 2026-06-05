#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"

BASE_URL="${MAGICK_CLOUD_BASE_URL:-http://127.0.0.1:8010}"
COMPOSE_FILE="${MAGICK_CLOUD_COMPOSE_FILE:-${ROOT_DIR}/docker-compose.dev.yml}"
COMPOSE_PROJECT_NAME="${MAGICK_CLOUD_COMPOSE_PROJECT_NAME:-magick-ai-cloud}"
SMOKE_SUFFIX="${MAGICK_CLOUD_SITE_KNOWLEDGE_SMOKE_SUFFIX:-$(date -u '+%Y%m%d%H%M%S')}"
SITE_ID="${MAGICK_CLOUD_SITE_KNOWLEDGE_SMOKE_SITE_ID:-site_knowledge_smoke_${SMOKE_SUFFIX}}"
KEY_ID="${MAGICK_CLOUD_SITE_KNOWLEDGE_SMOKE_KEY_ID:-key_site_knowledge_smoke_${SMOKE_SUFFIX}}"
SECRET="${MAGICK_CLOUD_SITE_KNOWLEDGE_SMOKE_SECRET:-}"
EVIDENCE_DIR="${MAGICK_CLOUD_SITE_KNOWLEDGE_SMOKE_EVIDENCE_DIR:-${ROOT_DIR}/.tmp/site-knowledge-real-chain-smoke}"
RUN_COMPOSE_UP="${MAGICK_CLOUD_SITE_KNOWLEDGE_SMOKE_COMPOSE_UP:-true}"

fail() {
	echo "[fail] $*" >&2
	exit 1
}

ok() {
	echo "[ok] $*"
}

json_read_path() {
	local json_payload="$1"
	local json_path="$2"
	JSON_PAYLOAD="${json_payload}" JSON_PATH="${json_path}" python3 - <<'PY'
import json
import os
import sys

try:
    current = json.loads(os.environ.get("JSON_PAYLOAD", ""))
except json.JSONDecodeError:
    sys.exit(2)

for segment in os.environ.get("JSON_PATH", "").split("."):
    if not segment:
        continue
    if isinstance(current, list) and segment.isdigit():
        index = int(segment)
        if index >= len(current):
            sys.exit(3)
        current = current[index]
        continue
    if not isinstance(current, dict) or segment not in current:
        sys.exit(3)
    current = current[segment]

if current is None:
    print("null")
elif isinstance(current, bool):
    print("true" if current else "false")
elif isinstance(current, (dict, list)):
    print(json.dumps(current, ensure_ascii=True, separators=(",", ":")))
else:
    print(str(current))
PY
}

json_array_length() {
	local json_payload="$1"
	local json_path="$2"
	JSON_PAYLOAD="${json_payload}" JSON_PATH="${json_path}" python3 - <<'PY'
import json
import os
import sys

try:
    current = json.loads(os.environ.get("JSON_PAYLOAD", ""))
except json.JSONDecodeError:
    sys.exit(2)

for segment in os.environ.get("JSON_PATH", "").split("."):
    if not segment:
        continue
    if isinstance(current, list) and segment.isdigit():
        index = int(segment)
        if index >= len(current):
            sys.exit(3)
        current = current[index]
        continue
    if not isinstance(current, dict) or segment not in current:
        sys.exit(3)
    current = current[segment]

if not isinstance(current, list):
    sys.exit(4)
print(len(current))
PY
}

build_traceparent() {
	python3 - <<'PY'
import secrets

print(f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01")
PY
}

build_signature() {
	local method="$1"
	local path="$2"
	local query="$3"
	local timestamp="$4"
	local nonce="$5"
	local idempotency_key="$6"
	local traceparent="$7"
	local body="$8"

	local body_digest
	body_digest="$(printf '%s' "${body}" | openssl dgst -sha256 -r | awk '{print $1}')"
	local path_with_query="${path}"
	if [ -n "${query}" ]; then
		path_with_query="${path}?${query}"
	fi
	local canonical_request
	canonical_request="$(printf '%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s' \
		"${method}" \
		"${path_with_query}" \
		"${SITE_ID}" \
		"${KEY_ID}" \
		"${timestamp}" \
		"${nonce}" \
		"${idempotency_key}" \
		"${traceparent}" \
		"${body_digest}")"
	printf '%s' "${canonical_request}" | openssl dgst -sha256 -hmac "${SECRET}" -r | awk '{print $1}'
}

HTTP_STATUS=""
HTTP_BODY=""

http_request() {
	local method="$1"
	local url="$2"
	local body="$3"
	shift 3

	local tmp_body="${TMP_DIR}/body.txt"
	local status
	local curl_args=(
		-sS
		-k
		-o "${tmp_body}"
		-w "%{http_code}"
		-X "${method}"
		"${url}"
		-H "Accept: application/json"
	)
	local header=""
	for header in "$@"; do
		if [ -n "${header}" ]; then
			curl_args+=(-H "${header}")
		fi
	done
	if [ -n "${body}" ]; then
		curl_args+=(-H "Content-Type: application/json" --data "${body}")
	fi

	status="$(curl "${curl_args[@]}")" || fail "HTTP request failed: ${method} ${url}"
	HTTP_STATUS="${status}"
	HTTP_BODY="$(cat "${tmp_body}")"
}

signed_request() {
	local method="$1"
	local path="$2"
	local query="$3"
	local body="$4"
	local idempotency_key="${5:-}"
	local nonce="${6:-}"
	local traceparent
	traceparent="$(build_traceparent)"
	local timestamp
	timestamp="$(date -u '+%s')"
	local signature
	signature="$(build_signature "${method}" "${path}" "${query}" "${timestamp}" "${nonce}" "${idempotency_key}" "${traceparent}" "${body}")"
	local url="${BASE_URL%/}${path}"
	if [ -n "${query}" ]; then
		url="${url}?${query}"
	fi

	local headers=(
		"traceparent: ${traceparent}"
		"X-Magick-Site-Id: ${SITE_ID}"
		"X-Magick-Key-Id: ${KEY_ID}"
		"X-Magick-Timestamp: ${timestamp}"
		"X-Magick-Signature: ${signature}"
	)
	if [ -n "${nonce}" ]; then
		headers+=("X-Magick-Nonce: ${nonce}")
	fi
	if [ -n "${idempotency_key}" ]; then
		headers+=("Idempotency-Key: ${idempotency_key}")
	fi

	http_request "${method}" "${url}" "${body}" "${headers[@]}"
}

assert_http_status() {
	local expected="$1"
	local message="$2"
	if [ "${HTTP_STATUS}" != "${expected}" ]; then
		fail "${message} (expected HTTP ${expected}, got ${HTTP_STATUS}; body=${HTTP_BODY})"
	fi
}

docker_compose() {
	COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose -f "${COMPOSE_FILE}" "$@"
}

magick_ai_cloud_require_cmd curl
magick_ai_cloud_require_cmd docker
magick_ai_cloud_require_cmd openssl
magick_ai_cloud_require_cmd python3

mkdir -p "${EVIDENCE_DIR}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

if [ -z "${SECRET}" ]; then
	SECRET="$(python3 - <<'PY'
import secrets

print("site-knowledge-smoke-" + secrets.token_urlsafe(32))
PY
)"
fi

if [ "${RUN_COMPOSE_UP}" = "true" ]; then
	ok "Ensuring dev API and runtime worker are running"
	docker_compose --profile runtime up -d --build api worker >/dev/null
fi

ok "Waiting for Cloud API at ${BASE_URL}"
if ! magick_ai_cloud_wait_for_ready "${BASE_URL}" 30 2; then
	fail "Cloud API did not become live"
fi

ok "Checking container Site Knowledge configuration"
CONFIG_JSON="$(
	docker_compose exec -T api python - <<'PY'
import json
import sys

from app.adapters.providers.registry import build_provider_adapters
from app.core.config import Settings

try:
    settings = Settings()
    providers = build_provider_adapters(settings)
except Exception as error:
    print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=True))
    sys.exit(0)

embedding_provider = str(settings.site_knowledge_embedding_provider or "")
errors = []
if settings.site_knowledge_vector_backend != "zilliz_cloud":
    errors.append("site knowledge vector backend must be zilliz_cloud")
if embedding_provider not in {"tei", "siliconflow"}:
    errors.append("site knowledge embedding provider must be tei or siliconflow")
if embedding_provider not in providers:
    errors.append(f"embedding provider {embedding_provider} is not registered")
if int(settings.site_knowledge_embedding_dimensions) != 1024:
    errors.append("site knowledge embedding dimensions must be 1024 for BAAI/bge-m3")

print(json.dumps(
    {
        "ok": not errors,
        "errors": errors,
        "vector_backend": settings.site_knowledge_vector_backend,
        "embedding_provider": embedding_provider,
        "embedding_model": settings.site_knowledge_embedding_model,
        "embedding_dimensions": settings.site_knowledge_embedding_dimensions,
        "comments_enabled": bool(settings.site_knowledge_comments_enabled),
        "zilliz_collection": settings.site_knowledge_zilliz_collection,
        "provider_registered": embedding_provider in providers,
    },
    ensure_ascii=True,
    sort_keys=True,
))
PY
)"
if [ "$(json_read_path "${CONFIG_JSON}" "ok")" != "true" ]; then
	fail "Site Knowledge Cloud config is not ready: ${CONFIG_JSON}"
fi

ok "Applying migrations"
docker_compose exec -T api alembic upgrade head >/dev/null

ok "Seeding isolated smoke site"
docker_compose exec -T api python -m app.dev.seed_runtime \
	--site-id "${SITE_ID}" \
	--key-id "${KEY_ID}" \
	--secret "${SECRET}" \
	--site-name "Site Knowledge Smoke" \
	--scopes "runtime:execute,runtime:read,stats:read" \
	--skip-catalog-refresh \
	--skip-health-scan >/dev/null

SYNC_BODY="$(
	python3 - <<'PY'
import json

payload = {
    "ability_name": "magick-ai-cloud/site-knowledge-sync",
    "contract_version": "site_knowledge_sync.v1",
    "execution_pattern": "whole_run_offload",
    "data_classification": "public_site_content",
    "storage_mode": "result_only",
    "timeout_seconds": 180,
    "retry_max": 0,
    "retention_ttl": 3600,
    "input": {
        "contract_version": "site_knowledge_sync.v1",
        "sync_mode": "rebuild",
        "max_posts": 20,
        "documents": [
            {
                "post_id": 901001,
                "post_type": "post",
                "post_status": "publish",
                "title": "Cloud Site Knowledge Smoke",
                "url": "https://example.test/cloud-site-knowledge-smoke",
                "modified_gmt": "2026-06-04 00:00:00",
                "excerpt": "A smoke article for Cloud-managed Site Knowledge.",
                "content_excerpt": (
                    "Magick AI Cloud indexes public WordPress content with BGE-M3 "
                    "embeddings and Zilliz Cloud to support source-grounded site "
                    "search, internal links, FAQ candidates, and anti-hallucination "
                    "evidence gates."
                ),
                "content_hash": "site-knowledge-smoke-post-901001-v1",
            },
            {
                "post_id": 901002,
                "post_type": "page",
                "post_status": "publish",
                "title": "Vector Evidence Gate",
                "url": "https://example.test/vector-evidence-gate",
                "modified_gmt": "2026-06-04 00:05:00",
                "excerpt": "A smoke page for evidence-gated search.",
                "content_excerpt": (
                    "The evidence gate requires enough site-owned search results "
                    "before an assistant can make a site-grounded assertion. Low "
                    "confidence searches should abstain instead of inventing facts."
                ),
                "content_hash": "site-knowledge-smoke-page-901002-v1",
            },
        ],
        "write_posture": "suggestion_only",
    },
}
print(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
PY
)"

ok "Submitting queued Site Knowledge rebuild"
signed_request \
	"POST" \
	"/v1/runtime/execute" \
	"" \
	"${SYNC_BODY}" \
	"site-knowledge-smoke-sync-${SMOKE_SUFFIX}" \
	"nonce-site-knowledge-sync-${SMOKE_SUFFIX}"
assert_http_status "200" "site knowledge sync request failed"
SYNC_RUN_ID="$(json_read_path "${HTTP_BODY}" "data.run_id")"
if [ -z "${SYNC_RUN_ID}" ] || [ "${SYNC_RUN_ID}" = "null" ]; then
	fail "sync response did not include run_id"
fi

ok "Polling queued sync result"
SYNC_RESULT_BODY=""
for _attempt in $(seq 1 60); do
	signed_request "GET" "/v1/runs/${SYNC_RUN_ID}/result" "" "" "" ""
	if [ "${HTTP_STATUS}" = "200" ]; then
		SYNC_RESULT_BODY="${HTTP_BODY}"
		break
	fi
	if [ "${HTTP_STATUS}" != "409" ]; then
		fail "sync result polling failed (HTTP ${HTTP_STATUS}; body=${HTTP_BODY})"
	fi
	sleep 2
done
if [ -z "${SYNC_RESULT_BODY}" ]; then
	fail "sync did not complete before timeout"
fi
asserted_sync_status="$(json_read_path "${SYNC_RESULT_BODY}" "data.result.status")"
if [ "${asserted_sync_status}" != "completed" ]; then
	fail "sync did not complete successfully: ${SYNC_RESULT_BODY}"
fi

SEARCH_BODY="$(
	python3 - <<'PY'
import json

payload = {
    "ability_name": "magick-ai-cloud/site-knowledge-search",
    "contract_version": "site_knowledge_search.v1",
    "execution_pattern": "inline",
    "data_classification": "public_site_content",
    "storage_mode": "result_only",
    "input": {
        "contract_version": "site_knowledge_search.v1",
        "query": "BGE-M3 Zilliz evidence gate anti hallucination",
        "intent": "site_search",
        "max_results": 5,
        "filters": {
            "source_types": ["post", "page"],
            "post_types": ["post", "page"],
            "status": ["publish"],
        },
        "evidence_policy": {
            "min_score": 0.2,
            "required_sources": 1,
            "no_hit_policy": "abstain",
        },
        "write_posture": "suggestion_only",
    },
}
print(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
PY
)"

ok "Running grounded Site Knowledge search"
signed_request \
	"POST" \
	"/v1/runtime/execute" \
	"" \
	"${SEARCH_BODY}" \
	"site-knowledge-smoke-search-${SMOKE_SUFFIX}" \
	"nonce-site-knowledge-search-${SMOKE_SUFFIX}"
assert_http_status "200" "site knowledge search request failed"
SEARCH_RESULT_BODY="${HTTP_BODY}"

RESULT_COUNT="$(json_array_length "${SEARCH_RESULT_BODY}" "data.result.results")"
EVIDENCE_STATUS="$(json_read_path "${SEARCH_RESULT_BODY}" "data.result.evidence_gate.status")"
DIRECT_WRITE="$(json_read_path "${SEARCH_RESULT_BODY}" "data.result.direct_wordpress_write")"
WRITE_POSTURE="$(json_read_path "${SEARCH_RESULT_BODY}" "data.result.write_posture")"
if [ "${RESULT_COUNT}" -lt 1 ]; then
	fail "site knowledge search returned no results"
fi
if [ "${EVIDENCE_STATUS}" != "passed" ]; then
	fail "evidence gate did not pass: ${SEARCH_RESULT_BODY}"
fi
if [ "${DIRECT_WRITE}" != "false" ] || [ "${WRITE_POSTURE}" != "suggestion_only" ]; then
	fail "write boundary was not preserved"
fi

STATUS_BODY="$(
	python3 - <<'PY'
import json

payload = {
    "ability_name": "magick-ai-cloud/site-knowledge-status",
    "contract_version": "site_knowledge_status.v1",
    "execution_pattern": "inline",
    "data_classification": "public_site_content",
    "storage_mode": "result_only",
    "input": {
        "contract_version": "site_knowledge_status.v1",
        "include_coverage": True,
        "write_posture": "suggestion_only",
    },
}
print(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
PY
)"

ok "Checking Site Knowledge status"
signed_request \
	"POST" \
	"/v1/runtime/execute" \
	"" \
	"${STATUS_BODY}" \
	"site-knowledge-smoke-status-${SMOKE_SUFFIX}" \
	"nonce-site-knowledge-status-${SMOKE_SUFFIX}"
assert_http_status "200" "site knowledge status request failed"
STATUS_RESULT_BODY="${HTTP_BODY}"
INDEXED_CHUNKS="$(json_read_path "${STATUS_RESULT_BODY}" "data.result.coverage.indexed_chunks")"
if [ "${INDEXED_CHUNKS}" = "0" ] || [ "${INDEXED_CHUNKS}" = "null" ]; then
	fail "status did not report indexed chunks"
fi

EVIDENCE_FILE="${EVIDENCE_DIR}/evidence-${SMOKE_SUFFIX}.json"
CONFIG_JSON="${CONFIG_JSON}" \
SYNC_RUN_ID="${SYNC_RUN_ID}" \
RESULT_COUNT="${RESULT_COUNT}" \
EVIDENCE_STATUS="${EVIDENCE_STATUS}" \
INDEXED_CHUNKS="${INDEXED_CHUNKS}" \
SITE_ID="${SITE_ID}" \
python3 - <<'PY' >"${EVIDENCE_FILE}"
import json
import os

config = json.loads(os.environ["CONFIG_JSON"])
evidence = {
    "contract_version": "site_knowledge_real_chain_smoke.v1",
    "status": "passed",
    "site_id": os.environ["SITE_ID"],
    "sync_run_id": os.environ["SYNC_RUN_ID"],
    "config": config,
    "checks": {
        "sync_completed": True,
        "search_result_count": int(os.environ["RESULT_COUNT"]),
        "evidence_gate_status": os.environ["EVIDENCE_STATUS"],
        "indexed_chunks": int(os.environ["INDEXED_CHUNKS"]),
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
    },
}
print(json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True))
PY

ok "Site Knowledge real-chain smoke passed"
ok "Evidence: ${EVIDENCE_FILE}"
