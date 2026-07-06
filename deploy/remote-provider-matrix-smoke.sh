#!/usr/bin/env bash
set -euo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
if [ -n "${SCRIPT_SOURCE}" ] && [ "${SCRIPT_SOURCE}" != "bash" ] && [ -e "${SCRIPT_SOURCE}" ]; then
	ROOT_DIR="$(cd "$(dirname "${SCRIPT_SOURCE}")/.." && pwd -P)"
else
	ROOT_DIR="$(pwd -P)"
fi
. "${ROOT_DIR}/deploy/common.sh"

npcink_ai_cloud_require_cmd docker

REQUIRED_CAPABILITIES="${NPCINK_CLOUD_REQUIRED_PROVIDER_CAPABILITIES:-text_generation,image_generation,web_search,image_source,embedding,vector_store}"
export REQUIRED_CAPABILITIES

npcink_ai_cloud_compose "${ROOT_DIR}" exec -T \
	-e "REQUIRED_CAPABILITIES=${REQUIRED_CAPABILITIES}" \
	api python - <<'PY'
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from typing import Any

from app.adapters.providers.registry import resolve_live_provider_adapters
from app.core.config import Settings
from app.domain.provider_connections.runtime_settings import (
    apply_provider_connection_runtime_settings,
)
from app.domain.provider_connections.service import (
    ProviderConnectionAdminError,
    ProviderConnectionAdminService,
)


def as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return []


def summarize_connection(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "connection_id": item.get("connection_id"),
        "provider_id": item.get("provider_id"),
        "kind": item.get("kind"),
        "enabled": item.get("enabled"),
        "configured": item.get("configured"),
        "status": item.get("status"),
        "capability_ids": as_list(item.get("capability_ids")),
        "runtime_profile_ids": as_list(item.get("runtime_profile_ids")),
    }


def summarize_test(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "connection_id": result.get("connection_id"),
        "provider_id": result.get("provider_id"),
        "kind": result.get("kind"),
        "ok": result.get("ok"),
        "status": result.get("status"),
        "stage": result.get("stage"),
        "error_code": result.get("error_code"),
        "catalog_model_count": (result.get("catalog") or {}).get("model_count"),
    }


settings = Settings()
service = ProviderConnectionAdminService(settings.database_url, settings)
connections = service.list_connections()["connections"]
runtime_projection = apply_provider_connection_runtime_settings(settings)
registered_provider_ids = sorted(
    resolve_live_provider_adapters(settings, include_enabled_connections=True).keys()
)

required_capabilities = [
    item.strip()
    for item in os.environ.get("REQUIRED_CAPABILITIES", "").split(",")
    if item.strip()
]

capability_matrix: dict[str, list[dict[str, Any]]] = defaultdict(list)
connection_tests: list[dict[str, Any]] = []
test_failures: list[dict[str, Any]] = []

for item in connections:
    summarized = summarize_connection(item)
    if bool(item.get("enabled")) and bool(item.get("configured")):
        for capability_id in summarized["capability_ids"]:
            capability_matrix[capability_id].append(summarized)
        try:
            test_result = service.test_connection(str(item.get("connection_id") or ""))
        except ProviderConnectionAdminError as error:
            result = {
                "connection_id": summarized["connection_id"],
                "provider_id": summarized["provider_id"],
                "kind": summarized["kind"],
                "ok": False,
                "status": "admin_error",
                "stage": "provider_connection_test",
                "error_code": error.code,
            }
        except Exception as error:
            result = {
                "connection_id": summarized["connection_id"],
                "provider_id": summarized["provider_id"],
                "kind": summarized["kind"],
                "ok": False,
                "status": "unexpected_error",
                "stage": "provider_connection_test",
                "error_code": error.__class__.__name__,
            }
        else:
            result = summarize_test(test_result)
        connection_tests.append(result)
        if not bool(result.get("ok")):
            test_failures.append(result)

missing_capabilities = [
    capability_id
    for capability_id in required_capabilities
    if not capability_matrix.get(capability_id)
]

payload = {
    "status": "ok" if not missing_capabilities and not test_failures else "failed",
    "required_capabilities": required_capabilities,
    "missing_capabilities": missing_capabilities,
    "capability_matrix": dict(sorted(capability_matrix.items())),
    "connection_tests": connection_tests,
    "test_failures": test_failures,
    "registered_provider_ids": registered_provider_ids,
    "runtime_provider_projection": {
        "applied_count": runtime_projection.applied_count,
        "web_search_count": runtime_projection.web_search_count,
        "image_source_count": runtime_projection.image_source_count,
        "embedding_count": runtime_projection.embedding_count,
        "rerank_count": runtime_projection.rerank_count,
        "vector_store_count": runtime_projection.vector_store_count,
    },
    "provider_truth": "db_managed_provider_connections",
    "secret_exposure": "none",
    "boundary": {
        "owner": "cloud_runtime",
        "direct_wordpress_write": False,
        "not_a_control_plane": True,
    },
}

print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))

if missing_capabilities or test_failures:
    sys.exit(1)
PY
