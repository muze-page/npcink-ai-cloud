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
from datetime import datetime

from sqlalchemy import func, select

from app.adapters.providers.registry import resolve_live_provider_adapters
from app.core.config import Settings
from app.core.db import get_session
from app.core.models import CatalogInstance, CatalogModel, CatalogProvider
from app.domain.provider_connections.runtime_settings import (
    apply_provider_connection_runtime_settings,
)
from app.domain.provider_connections.service import ProviderConnectionAdminService


def isoformat(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


settings = Settings()
runtime_projection = apply_provider_connection_runtime_settings(settings)
providers = resolve_live_provider_adapters(settings, include_enabled_connections=True)
provider_connections = ProviderConnectionAdminService(
    settings.database_url,
    settings,
).list_connections()["connections"]

provider_rows: dict[str, dict[str, object]] = {}
with get_session(settings.database_url) as session:
    catalog_rows = session.execute(
        select(
            CatalogProvider.provider_id,
            CatalogProvider.display_name,
            CatalogProvider.adapter_type,
            CatalogProvider.status,
            CatalogProvider.last_refreshed_at,
        )
    ).all()
    model_counts = dict(
        session.execute(
            select(CatalogModel.provider_id, func.count())
            .group_by(CatalogModel.provider_id)
        ).all()
    )
    instance_counts = dict(
        session.execute(
            select(CatalogInstance.provider_id, func.count())
            .group_by(CatalogInstance.provider_id)
        ).all()
    )

for provider_id, display_name, adapter_type, status, last_refreshed_at in catalog_rows:
    provider_rows[provider_id] = {
        "provider_id": provider_id,
        "display_name": display_name,
        "adapter_type": adapter_type,
        "catalog_status": status,
        "catalog_last_refreshed_at": isoformat(last_refreshed_at),
        "catalog_models_total": int(model_counts.get(provider_id, 0)),
        "catalog_instances_total": int(instance_counts.get(provider_id, 0)),
    }

connections_by_provider = {
    str(item.get("provider_id") or ""): item
    for item in provider_connections
    if str(item.get("provider_id") or "")
}


def connection_ready(provider_id: str) -> bool:
    item = connections_by_provider.get(provider_id) or {}
    return bool(item.get("enabled") and item.get("configured"))


configured = [
    {
        "provider_id": "openai",
        "configured": connection_ready("openai"),
        "registered": "openai" in providers,
        "base_url": (connections_by_provider.get("openai") or {}).get("base_url") or settings.openai_base_url,
        "timeout_seconds": settings.openai_timeout_seconds,
        "source": "provider_connections",
        "catalog": provider_rows.get("openai"),
    },
    {
        "provider_id": "anthropic",
        "configured": connection_ready("anthropic"),
        "registered": "anthropic" in providers,
        "base_url": (connections_by_provider.get("anthropic") or {}).get("base_url") or settings.anthropic_base_url,
        "timeout_seconds": settings.anthropic_timeout_seconds,
        "source": "provider_connections",
        "catalog": provider_rows.get("anthropic"),
    },
    {
        "provider_id": "litellm",
        "configured": connection_ready("litellm"),
        "registered": "litellm" in providers,
        "base_url": (connections_by_provider.get("litellm") or {}).get("base_url") or settings.litellm_base_url,
        "timeout_seconds": settings.litellm_timeout_seconds,
        "source": "provider_connections",
        "catalog": provider_rows.get("litellm"),
    },
    {
        "provider_id": "vllm",
        "configured": connection_ready("vllm"),
        "registered": "vllm" in providers,
        "base_url": (connections_by_provider.get("vllm") or {}).get("base_url") or settings.vllm_base_url,
        "timeout_seconds": settings.vllm_timeout_seconds,
        "source": "provider_connections",
        "catalog": provider_rows.get("vllm"),
    },
    {
        "provider_id": "tei",
        "configured": connection_ready("tei") or connection_ready("embedding_tei"),
        "registered": "tei" in providers,
        "base_url": (connections_by_provider.get("tei") or connections_by_provider.get("embedding_tei") or {}).get("base_url") or settings.tei_base_url,
        "timeout_seconds": settings.tei_timeout_seconds,
        "model_ids": [item.strip() for item in str(settings.tei_model_ids or "").split(",") if item.strip()],
        "source": "provider_connections",
        "catalog": provider_rows.get("tei"),
    },
    {
        "provider_id": "openrouter",
        "configured": connection_ready("openrouter"),
        "registered": "openrouter" in providers,
        "base_url": (connections_by_provider.get("openrouter") or {}).get("base_url") or settings.openrouter_base_url,
        "timeout_seconds": settings.openrouter_timeout_seconds,
        "source": "provider_connections",
        "catalog": provider_rows.get("openrouter"),
    },
]

payload = {
    "environment": settings.environment,
    "database": {
        "configured": bool(settings.database_url),
        "secret_exposure": "redacted",
    },
    "providers": configured,
    "provider_connections": [
        {
            "connection_id": item.get("connection_id"),
            "provider_id": item.get("provider_id"),
            "kind": item.get("kind"),
            "enabled": item.get("enabled"),
            "configured": item.get("configured"),
            "status": item.get("status"),
            "capability_ids": item.get("capability_ids"),
            "runtime_profile_ids": item.get("runtime_profile_ids"),
        }
        for item in provider_connections
    ],
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
}

print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
PY
