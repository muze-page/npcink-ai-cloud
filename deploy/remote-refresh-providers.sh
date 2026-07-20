#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"

npcink_ai_cloud_require_cmd docker

RELEASE_TOOL_PYTHON="$(npcink_ai_cloud_release_tool_python)"
MANIFEST_HELPER="${ROOT_DIR}/scripts/verify-release-bundle-manifest.py"
npcink_ai_cloud_require_release_tool_python "${RELEASE_TOOL_PYTHON}"

PYTHON_COMMAND=(npcink_ai_cloud_compose "${ROOT_DIR}" exec -T api python -)
if [ "${NPCINK_CLOUD_REFRESH_PROVIDERS_ONE_OFF:-0}" = "1" ]; then
	# Atomic cutover refreshes provider projections before the public API is
	# started, so it must use the staged API image without starting dependencies.
	PYTHON_COMMAND=(
		npcink_ai_cloud_compose_run_with_image_proof
		"${ROOT_DIR}"
		api
		npcink-ai-cloud-api:prod
		"$("${RELEASE_TOOL_PYTHON}" "${MANIFEST_HELPER}" role-image-id --root "${ROOT_DIR}" --role api)"
		python -
	)
fi

"${PYTHON_COMMAND[@]}" <<'PY'
from __future__ import annotations

import json

from app.adapters.providers.registry import resolve_live_provider_adapters
from app.core.config import Settings
from app.domain.catalog.service import CatalogService

settings = Settings()
providers = resolve_live_provider_adapters(settings, include_enabled_connections=True)
service = CatalogService(settings.database_url, providers=providers, settings=settings)

catalog = service.refresh_catalog()
health = service.scan_provider_health()

print(
    json.dumps(
        {
            "configured_provider_ids": sorted(providers.keys()),
            "catalog": {
                "providers": catalog.get("providers", []),
                "refreshed_count": catalog.get("refreshed_count", 0),
                "revision": catalog.get("revision", ""),
            },
            "health": health,
        },
        ensure_ascii=True,
        sort_keys=True,
    )
)
PY
