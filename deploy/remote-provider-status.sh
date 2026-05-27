#!/usr/bin/env bash
set -euo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
if [ -n "${SCRIPT_SOURCE}" ] && [ "${SCRIPT_SOURCE}" != "bash" ] && [ -e "${SCRIPT_SOURCE}" ]; then
	ROOT_DIR="$(cd "$(dirname "${SCRIPT_SOURCE}")/.." && pwd -P)"
else
	ROOT_DIR="$(pwd -P)"
fi
. "${ROOT_DIR}/deploy/common.sh"

magick_ai_cloud_require_cmd docker

magick_ai_cloud_compose "${ROOT_DIR}" exec -T api python - <<'PY'
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, select

from app.adapters.providers.registry import build_provider_adapters
from app.core.config import Settings
from app.core.db import get_session
from app.core.models import CatalogInstance, CatalogModel, CatalogProvider


def isoformat(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


settings = Settings()
providers = build_provider_adapters(settings)

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

configured = [
    {
        "provider_id": "openai",
        "configured": bool(settings.openai_api_key),
        "registered": "openai" in providers,
        "base_url": settings.openai_base_url,
        "timeout_seconds": settings.openai_timeout_seconds,
        "organization_configured": bool(settings.openai_organization),
        "catalog": provider_rows.get("openai"),
    },
    {
        "provider_id": "anthropic",
        "configured": bool(settings.anthropic_api_key),
        "registered": "anthropic" in providers,
        "base_url": settings.anthropic_base_url,
        "timeout_seconds": settings.anthropic_timeout_seconds,
        "api_version": settings.anthropic_version,
        "catalog": provider_rows.get("anthropic"),
    },
    {
        "provider_id": "litellm",
        "configured": bool(settings.litellm_provider_enabled and settings.litellm_base_url),
        "registered": "litellm" in providers,
        "base_url": settings.litellm_base_url,
        "timeout_seconds": settings.litellm_timeout_seconds,
        "catalog": provider_rows.get("litellm"),
    },
    {
        "provider_id": "vllm",
        "configured": bool(settings.vllm_provider_enabled and settings.vllm_base_url),
        "registered": "vllm" in providers,
        "base_url": settings.vllm_base_url,
        "timeout_seconds": settings.vllm_timeout_seconds,
        "api_key_configured": bool(settings.vllm_api_key),
        "catalog": provider_rows.get("vllm"),
    },
    {
        "provider_id": "tei",
        "configured": bool(settings.tei_provider_enabled and settings.tei_base_url and settings.tei_model_ids),
        "registered": "tei" in providers,
        "base_url": settings.tei_base_url,
        "timeout_seconds": settings.tei_timeout_seconds,
        "api_key_configured": bool(settings.tei_api_key),
        "model_ids": [item.strip() for item in str(settings.tei_model_ids or "").split(",") if item.strip()],
        "catalog": provider_rows.get("tei"),
    },
    {
        "provider_id": "openrouter",
        "configured": bool(settings.openrouter_provider_enabled and settings.openrouter_api_key),
        "registered": "openrouter" in providers,
        "base_url": settings.openrouter_base_url,
        "timeout_seconds": settings.openrouter_timeout_seconds,
        "site_url": settings.openrouter_site_url,
        "catalog": provider_rows.get("openrouter"),
    },
]

payload = {
    "environment": settings.environment,
    "database_url": settings.database_url,
    "providers": configured,
}

print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
PY
