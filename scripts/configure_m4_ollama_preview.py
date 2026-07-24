from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.adapters.repositories.catalog_repository import CatalogRepository
from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.models import CatalogInstance, RoutingBinding
from app.domain.provider_connections.service import ProviderConnectionAdminService
from app.domain.wordpress_ai_connector.routing_profiles import (
    WP_AI_CONNECTOR_CLASSIFICATION_PROFILE_ID,
    WP_AI_CONNECTOR_EDITORIAL_PROFILE_ID,
    WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
)

CONNECTION_ID = "ollama_m4"
PROVIDER_ID = "ollama-m4"
MODEL_ID = "qwen3.5:9b"
CATALOG_MODEL_ID = f"{PROVIDER_ID}/{MODEL_ID}"
BASE_URL = "http://host.docker.internal:11434/v1"
PROFILE_IDS = (
    WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
    WP_AI_CONNECTOR_EDITORIAL_PROFILE_ID,
    WP_AI_CONNECTOR_CLASSIFICATION_PROFILE_ID,
)
ALLOWED_ENVIRONMENTS = frozenset({"development", "dev", "test"})


def _connection_payload() -> dict[str, object]:
    return {
        "connection_id": CONNECTION_ID,
        "provider_id": PROVIDER_ID,
        "provider_type": "openai_compatible",
        "kind": "openai_compatible",
        "display_name": "Ollama M4",
        "enabled": True,
        "base_url": BASE_URL,
        "source_role": "execution_source",
        "capability_ids": ["text_generation"],
        "runtime_profile_ids": list(PROFILE_IDS),
        "config": {
            "model_ids": [MODEL_ID],
            "timeout_seconds": 60,
            "default_reasoning_effort": "none",
        },
        "metadata": {"operator_surface": "m4_preview"},
        "secretless": True,
    }


def _validate_environment(settings: Settings) -> None:
    environment = str(settings.environment or "").strip().lower()
    if environment not in ALLOWED_ENVIRONMENTS:
        raise RuntimeError("M4 Ollama preview configuration is development-only")


def configure(settings: Settings) -> dict[str, object]:
    _validate_environment(settings)
    service = ProviderConnectionAdminService(settings.database_url, settings)
    service.save_connection(_connection_payload())
    test_result = service.test_connection(CONNECTION_ID)
    if test_result.get("status") != "ready":
        raise RuntimeError("M4 Ollama provider catalog test did not become ready")

    revision = f"m4-preview-ollama-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    with get_session(settings.database_url) as session:
        instances = list(
            session.scalars(
                select(CatalogInstance).where(
                    CatalogInstance.provider_id == PROVIDER_ID,
                    CatalogInstance.model_id == CATALOG_MODEL_ID,
                    CatalogInstance.endpoint_variant == "chat_completions",
                )
            )
        )
        if len(instances) != 1:
            raise RuntimeError("M4 Ollama qwen3.5:9b catalog instance is not unique")
        instance_id = instances[0].instance_id
        repository = CatalogRepository(session)
        for profile_id in PROFILE_IDS:
            existing = session.get(RoutingBinding, profile_id)
            repository.upsert_routing_binding(
                profile_id=profile_id,
                candidate_instance_ids=[instance_id],
                selection_policy_json=(
                    dict(existing.selection_policy_json or {}) if existing is not None else {}
                ),
                revision=revision,
            )
        session.commit()

    return {
        "status": "configured",
        "provider_id": PROVIDER_ID,
        "model_id": MODEL_ID,
        "reasoning_effort": "none",
        "profile_ids": list(PROFILE_IDS),
        "revision": revision,
        "secretless": True,
    }


def main() -> int:
    print(json.dumps(configure(get_settings()), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
