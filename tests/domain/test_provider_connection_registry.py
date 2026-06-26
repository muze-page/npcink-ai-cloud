from __future__ import annotations

from pathlib import Path

from app.adapters.providers.openai import OpenAIProviderAdapter
from app.adapters.providers.registry import (
    build_provider_adapters,
    resolve_execution_provider_adapters,
)
from app.core.config import Settings
from app.core.db import dispose_engine, init_schema
from app.domain.provider_connections.service import ProviderConnectionAdminService
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'provider-connection-registry.sqlite3'}"


def _settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="production",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        admin_bootstrap_token="npcink-cloud-admin-bootstrap-token-32b",
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        portal_public_base_url="https://cloud.example.com",
        portal_email_smtp_host="smtp.example.com",
        portal_email_from_email="no-reply@example.com",
        openai_api_key="env-openai-key",
        openai_base_url="https://env-openai.example/v1",
    )


def test_provider_registry_loads_enabled_provider_connections_before_env_fallback(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)

    ProviderConnectionAdminService(database_url, settings).save_connection(
        {
            "connection_id": "openai_primary",
            "provider_id": "openai",
            "provider_type": "openai_compatible",
            "kind": "openai_compatible",
            "display_name": "OpenAI primary from DB",
            "enabled": True,
            "base_url": "https://db-openai.example/v1",
            "capability_ids": ["text_generation", "image_generation"],
            "runtime_profile_ids": ["text.ai", "image.generation.default"],
            "credential": "db-openai-key",
        }
    )

    providers = build_provider_adapters(settings, include_enabled_connections=True)
    openai = providers["openai"]

    assert isinstance(openai, OpenAIProviderAdapter)
    assert openai.display_name == "OpenAI primary from DB"
    assert openai.base_url == "https://db-openai.example/v1"
    assert openai.api_key == "db-openai-key"

    execution_providers = resolve_execution_provider_adapters(
        settings,
        base_providers={
            "openai": OpenAIProviderAdapter(
                base_url="https://base-openai.example/v1",
                api_key="base-openai-key",
            )
        },
    )
    execution_openai = execution_providers["openai"]

    assert isinstance(execution_openai, OpenAIProviderAdapter)
    assert execution_openai.base_url == "https://db-openai.example/v1"
    assert execution_openai.api_key == "db-openai-key"

    dispose_engine(database_url)


def test_provider_registry_namespaces_custom_openai_compatible_connections(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)

    ProviderConnectionAdminService(database_url, settings).save_connection(
        {
            "connection_id": "deepseek_primary",
            "provider_id": "deepseek",
            "provider_type": "openai_compatible",
            "kind": "openai_compatible",
            "display_name": "DeepSeek primary",
            "enabled": True,
            "base_url": "https://deepseek.example/v1",
            "capability_ids": ["text_generation"],
            "runtime_profile_ids": ["text.ai"],
            "credential": "deepseek-key",
        }
    )

    providers = build_provider_adapters(settings, include_enabled_connections=True)
    deepseek = providers["deepseek"]

    assert isinstance(deepseek, OpenAIProviderAdapter)
    assert deepseek.provider_id == "deepseek"
    assert deepseek.display_name == "DeepSeek primary"
    assert deepseek.model_namespace_prefix == "deepseek"
    assert deepseek.base_url == "https://deepseek.example/v1"
    assert deepseek.api_key == "deepseek-key"

    dispose_engine(database_url)
