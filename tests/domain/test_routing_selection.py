from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import CatalogModel, ProviderConnection
from app.domain.catalog.service import CatalogService
from app.domain.provider_connections.service import ProviderConnectionAdminService
from app.domain.routing.errors import RoutingNoCandidatesError
from app.domain.routing.service import RoutingService
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'routing-domain.sqlite3'}"


def _settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
    )


def test_routing_service_prefers_balanced_text_instance(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    with get_session(database_url) as session:
        session.add(
            ProviderConnection(
                connection_id="openai",
                provider_type="openai_compatible",
                display_name="OpenAI",
                enabled=True,
                base_url="https://api.openai.test/v1",
                config_json={
                    "provider_id": "openai",
                    "kind": "openai_compatible",
                    "capability_ids": ["text_generation"],
                    "runtime_profile_ids": ["text.balanced"],
                    "model_ids": ["gpt-4.1-mini"],
                },
                secret_ciphertext="configured-in-test",
                status="ready",
                source_role="execution_source",
                metadata_json={},
            )
        )
        session.commit()

    resolution = RoutingService(database_url).resolve(
        profile_id="text.balanced",
        execution_kind="text",
    )

    assert resolution.profile_id == "text.balanced"
    assert resolution.default_policy["timeout_ms"] == 30000
    assert resolution.selected_candidate.instance_id == "openai-us-east-text-balanced"
    assert [candidate.instance_id for candidate in resolution.candidates] == [
        "openai-us-east-text-balanced",
        "openai-us-east-text-economy",
        "openai-us-east-text-quality",
    ]

    dispose_engine(database_url)


def test_routing_service_requires_runtime_execution_provider_when_supplied(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    with get_session(database_url) as session:
        session.add(
            ProviderConnection(
                connection_id="openai",
                provider_type="openai_compatible",
                display_name="OpenAI",
                enabled=True,
                base_url="https://api.openai.test/v1",
                config_json={
                    "provider_id": "openai",
                    "kind": "openai_compatible",
                    "capability_ids": ["text_generation"],
                    "runtime_profile_ids": ["text.balanced"],
                    "model_ids": ["gpt-4.1-mini"],
                },
                secret_ciphertext="configured-in-test",
                status="ready",
                source_role="execution_source",
                metadata_json={},
            )
        )
        session.commit()

    with pytest.raises(RoutingNoCandidatesError):
        RoutingService(
            database_url,
            execution_provider_ids={"anthropic"},
        ).resolve(
            profile_id="text.balanced",
            execution_kind="text",
        )

    dispose_engine(database_url)


def test_routing_service_rejects_allowlisted_model_without_execution_adapter(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    CatalogService(database_url).refresh_catalog()
    with get_session(database_url) as session:
        session.add(
            ProviderConnection(
                connection_id="openai_metadata_only",
                provider_type="openai_compatible",
                display_name="OpenAI metadata only",
                enabled=True,
                base_url="https://api.openai.test/v1",
                config_json={
                    "provider_id": "openai",
                    "kind": "openai_compatible",
                    "capability_ids": ["text_generation"],
                    "runtime_profile_ids": ["text.balanced"],
                    "model_ids": ["gpt-4.1-mini"],
                },
                secret_ciphertext="configured-but-not-decryptable",
                status="ready",
                source_role="runtime_metadata",
                metadata_json={},
            )
        )
        session.commit()

    with pytest.raises(RoutingNoCandidatesError):
        RoutingService(database_url, settings=settings).resolve(
            profile_id="text.balanced",
            execution_kind="text",
        )

    dispose_engine(database_url)


def test_routing_service_accepts_allowlisted_model_with_saved_execution_credential(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    CatalogService(database_url).refresh_catalog()
    ProviderConnectionAdminService(database_url, settings).save_connection(
        {
            "connection_id": "openai_primary",
            "provider_id": "openai",
            "provider_type": "openai_compatible",
            "kind": "openai_compatible",
            "display_name": "OpenAI primary",
            "enabled": True,
            "base_url": "https://api.openai.test/v1",
            "capability_ids": ["text_generation"],
            "runtime_profile_ids": ["text.balanced"],
            "config": {"model_ids": ["gpt-4.1-mini"]},
            "credential": "openai-test-key",
        }
    )

    resolution = RoutingService(database_url, settings=settings).resolve(
        profile_id="text.balanced",
        execution_kind="text",
    )

    assert resolution.selected_candidate.provider_id == "openai"
    assert resolution.selected_candidate.model_id == "gpt-4.1-mini"

    dispose_engine(database_url)


def test_routing_service_rejects_binding_outside_provider_model_allowlist(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()

    with pytest.raises(RoutingNoCandidatesError):
        RoutingService(database_url).resolve(
            profile_id="text.balanced",
            execution_kind="text",
        )

    dispose_engine(database_url)


def test_routing_service_rejects_deprecated_models_even_when_allowlisted(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    with get_session(database_url) as session:
        model = session.get(CatalogModel, "gpt-4.1-mini")
        assert model is not None
        model.is_deprecated = True
        session.add(
            ProviderConnection(
                connection_id="openai",
                provider_type="openai_compatible",
                display_name="OpenAI",
                enabled=True,
                base_url="https://api.openai.test/v1",
                config_json={
                    "provider_id": "openai",
                    "kind": "openai_compatible",
                    "capability_ids": ["text_generation"],
                    "runtime_profile_ids": ["text.balanced"],
                    "model_ids": ["gpt-4.1-mini"],
                },
                secret_ciphertext="configured-in-test",
                status="ready",
                source_role="execution_source",
                metadata_json={},
            )
        )
        session.commit()

    with pytest.raises(RoutingNoCandidatesError):
        RoutingService(database_url).resolve(
            profile_id="text.balanced",
            execution_kind="text",
        )

    dispose_engine(database_url)
