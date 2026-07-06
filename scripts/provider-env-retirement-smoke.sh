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

npcink_ai_cloud_compose "${ROOT_DIR}" exec -T api python - <<'PY'
from __future__ import annotations

import json
import os

from app.adapters.providers.registry import resolve_live_provider_adapters
from app.core.config import Settings
from app.domain.provider_connections.runtime_settings import (
    apply_provider_connection_runtime_settings,
)
from app.domain.provider_connections.service import ProviderConnectionAdminService

required_ids = [
    item.strip()
    for item in os.getenv(
        "NPCINK_CLOUD_PROVIDER_SMOKE_REQUIRED_IDS",
        "search_tavily,search_apify,search_zhihu,image_unsplash,image_pixabay,image_pexels,tei_env,vector_zilliz",
    ).split(",")
    if item.strip()
]

settings = Settings()
raw_provider_settings = {
    "web_search_provider": settings.web_search_provider,
    "image_source_provider": settings.image_source_provider,
    "site_knowledge_embedding_provider": settings.site_knowledge_embedding_provider,
    "site_knowledge_vector_backend": settings.site_knowledge_vector_backend,
}
expected_raw_defaults = {
    "web_search_provider": "disabled",
    "image_source_provider": "disabled",
    "site_knowledge_embedding_provider": "deterministic",
    "site_knowledge_vector_backend": "postgres_json",
}
unexpected_raw_settings = {
    key: value
    for key, value in raw_provider_settings.items()
    if value != expected_raw_defaults[key]
}

projection = apply_provider_connection_runtime_settings(settings)
registered_adapters = resolve_live_provider_adapters(
    settings,
    include_enabled_connections=True,
)
connections = ProviderConnectionAdminService(
    settings.database_url,
    settings,
).list_connections()["connections"]
connections_by_id = {
    str(item.get("connection_id") or ""): item
    for item in connections
}
missing_or_unready = [
    connection_id
    for connection_id in required_ids
    if not (
        (connections_by_id.get(connection_id) or {}).get("enabled")
        and (connections_by_id.get(connection_id) or {}).get("configured")
    )
]

summary = {
    "raw_provider_settings": raw_provider_settings,
    "required_connection_ids": required_ids,
    "missing_or_unready_connection_ids": missing_or_unready,
    "runtime_projection": {
        "applied_count": projection.applied_count,
        "web_search_count": projection.web_search_count,
        "image_source_count": projection.image_source_count,
        "embedding_count": projection.embedding_count,
        "rerank_count": projection.rerank_count,
        "vector_store_count": projection.vector_store_count,
    },
    "registered_adapter_ids": sorted(registered_adapters.keys()),
    "provider_truth": "db_managed_provider_connections",
    "secret_exposure": "none",
}

if unexpected_raw_settings or missing_or_unready:
    print(json.dumps(summary, indent=2, sort_keys=True))
    raise SystemExit(1)

print(json.dumps(summary, indent=2, sort_keys=True))
PY
