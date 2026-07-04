from __future__ import annotations

from pathlib import Path

from app.adapters.providers.openai import OpenAIProviderAdapter
from app.adapters.providers.registry import (
    build_provider_adapters,
    resolve_execution_provider_adapters,
)
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import ProviderConnection
from app.domain.provider_connections.runtime_settings import (
    apply_provider_connection_runtime_settings,
)
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
        browser_origin_allowlist="https://cloud.example.com",
        trusted_host_allowlist="cloud.example.com",
        openai_api_key="env-openai-key",
        openai_base_url="https://env-openai.example/v1",
    )


def test_provider_registry_uses_enabled_provider_connections_instead_of_env_fallback(
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

    env_only_providers = build_provider_adapters(settings, include_enabled_connections=False)
    assert "openai" not in env_only_providers

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


def test_runtime_settings_project_capability_provider_connections(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    settings.web_search_provider = "disabled"
    settings.image_source_provider = "disabled"
    settings.site_knowledge_embedding_provider = "deterministic"
    settings.site_knowledge_rerank_provider = "disabled"
    settings.site_knowledge_vector_backend = "postgres_json"
    service = ProviderConnectionAdminService(database_url, settings)

    service.save_connection(
        {
            "connection_id": "search_tavily",
            "provider_id": "tavily",
            "provider_type": "web_search_provider",
            "kind": "web_search_provider",
            "display_name": "Tavily",
            "enabled": True,
            "base_url": "https://api.tavily.example",
            "capability_ids": ["web_search"],
            "runtime_profile_ids": ["web-search.managed"],
            "config": {
                "provider_mode": "auto",
                "timeout_seconds": 9,
                "api_key_labels": "primary",
            },
            "credential": "tavily-secret",
        }
    )
    service.save_connection(
        {
            "connection_id": "search_zhihu",
            "provider_id": "zhihu",
            "provider_type": "web_search_provider",
            "kind": "web_search_provider",
            "display_name": "Zhihu Search",
            "enabled": True,
            "base_url": "https://developer.zhihu.example",
            "capability_ids": ["web_search"],
            "runtime_profile_ids": ["web-search.managed"],
            "config": {
                "provider_mode": "auto",
                "search_path": "/api/v1/content/zhihu_search",
                "global_search_path": "/api/v1/content/global_search",
                "hot_list_path": "/api/v1/content/hot_list",
                "direct_answer_path": "/v1/chat/completions",
                "hot_list_cache_ttl_seconds": 120,
            },
            "credential": "zhihu-secret",
        }
    )
    service.save_connection(
        {
            "connection_id": "image_unsplash",
            "provider_id": "unsplash",
            "provider_type": "image_source_provider",
            "kind": "image_source_provider",
            "display_name": "Unsplash",
            "enabled": True,
            "base_url": "https://api.unsplash.example",
            "capability_ids": ["image_source"],
            "runtime_profile_ids": ["image-source.managed"],
            "credential": "unsplash-secret",
        }
    )
    service.save_connection(
        {
            "connection_id": "embedding_siliconflow",
            "provider_id": "siliconflow",
            "provider_type": "embedding_provider",
            "kind": "embedding_provider",
            "display_name": "SiliconFlow Embedding",
            "enabled": True,
            "base_url": "https://siliconflow.example/v1",
            "capability_ids": ["embedding"],
            "runtime_profile_ids": ["embed.default"],
            "config": {"model_id": "BAAI/bge-m3", "dimensions": 1024},
            "credential": "siliconflow-secret",
        }
    )
    service.save_connection(
        {
            "connection_id": "embedding_tei",
            "provider_id": "tei",
            "provider_type": "embedding_provider",
            "kind": "embedding_provider",
            "display_name": "TEI Embedding",
            "enabled": True,
            "base_url": "http://tei.example",
            "capability_ids": ["embedding"],
            "runtime_profile_ids": ["embed.default"],
            "config": {
                "model_id": "BAAI/bge-m3",
                "model_ids": "BAAI/bge-m3,jinaai/jina-embeddings-v3",
                "timeout_seconds": 12,
                "region": "self-hosted-test",
                "context_window": 4096,
            },
            "secretless": True,
        }
    )
    service.save_connection(
        {
            "connection_id": "rerank_jina",
            "provider_id": "jina",
            "provider_type": "rerank_provider",
            "kind": "rerank_provider",
            "display_name": "Jina Rerank",
            "enabled": True,
            "base_url": "https://api.jina.example",
            "capability_ids": ["site_knowledge_rerank"],
            "runtime_profile_ids": ["site-knowledge.rerank"],
            "config": {"model_id": "jina-reranker-v3", "top_k": 20},
            "credential": "jina-secret",
        }
    )
    service.save_connection(
        {
            "connection_id": "vector_zilliz",
            "provider_id": "zilliz",
            "provider_type": "vector_store_provider",
            "kind": "vector_store_provider",
            "display_name": "Zilliz",
            "enabled": True,
            "base_url": "https://zilliz.example",
            "capability_ids": ["vector_store"],
            "runtime_profile_ids": ["site-knowledge.vector-store"],
            "config": {"database": "npcink", "collection": "site_chunks"},
            "credential": "zilliz-token",
        }
    )

    projection = apply_provider_connection_runtime_settings(settings)

    assert projection.applied_count == 7
    assert settings.web_search_provider == "auto"
    assert settings.web_search_tavily_base_url == "https://api.tavily.example"
    assert settings.web_search_tavily_api_key == "tavily-secret"
    assert settings.web_search_tavily_api_key_labels == "primary"
    assert settings.web_search_zhihu_base_url == "https://developer.zhihu.example"
    assert settings.web_search_zhihu_access_secret == "zhihu-secret"
    assert settings.web_search_zhihu_hot_list_cache_ttl_seconds == 120
    assert settings.image_source_provider == "auto"
    assert settings.image_source_unsplash_access_key == "unsplash-secret"
    assert settings.site_knowledge_embedding_provider == "tei"
    assert settings.tei_base_url == "http://tei.example"
    assert settings.tei_model_ids == "BAAI/bge-m3,jinaai/jina-embeddings-v3"
    assert settings.tei_timeout_seconds == 12
    assert settings.tei_region == "self-hosted-test"
    assert settings.tei_context_window == 4096
    assert settings.site_knowledge_rerank_provider == "jina"
    assert settings.site_knowledge_jina_api_key == "jina-secret"
    assert settings.site_knowledge_vector_backend == "zilliz_cloud"
    assert settings.site_knowledge_zilliz_token == "zilliz-token"

    serialized = service.list_connections()
    serialized_text = str(serialized)
    assert "tavily-secret" not in serialized_text
    assert "zhihu-secret" not in serialized_text
    assert "unsplash-secret" not in serialized_text
    assert "siliconflow-secret" not in serialized_text
    assert "jina-secret" not in serialized_text
    assert "zilliz-token" not in serialized_text

    dispose_engine(database_url)


def test_provider_connection_priority_selects_primary_capability_channel(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    service = ProviderConnectionAdminService(database_url, settings)

    service.save_connection(
        {
            "connection_id": "image_pexels_backup",
            "provider_id": "pexels",
            "provider_type": "image_source_provider",
            "kind": "image_source_provider",
            "display_name": "Pexels backup",
            "enabled": True,
            "base_url": "https://api.pexels.com/v1",
            "capability_ids": ["image_source"],
            "runtime_profile_ids": ["image-source.managed"],
            "credential": "pexels-backup-key",
            "note": "Backup key",
            "priority": 200,
        }
    )
    service.save_connection(
        {
            "connection_id": "image_pexels_primary",
            "provider_id": "pexels",
            "provider_type": "image_source_provider",
            "kind": "image_source_provider",
            "display_name": "Pexels primary",
            "enabled": True,
            "base_url": "https://api.pexels.com/v1",
            "capability_ids": ["image_source"],
            "runtime_profile_ids": ["image-source.managed"],
            "credential": "pexels-primary-key",
            "note": "Primary key",
            "priority": 10,
        }
    )

    connections = [
        item
        for item in service.list_connections()["connections"]
        if item["provider_id"] == "pexels"
    ]
    assert [item["connection_id"] for item in connections] == [
        "image_pexels_primary",
        "image_pexels_backup",
    ]
    assert connections[0]["note"] == "Primary key"
    assert connections[0]["priority"] == 10
    assert connections[1]["priority"] == 200

    projection = apply_provider_connection_runtime_settings(settings)

    assert projection.image_source_count == 1
    assert settings.image_source_pexels_api_key == "pexels-primary-key"

    dispose_engine(database_url)


def test_runtime_projection_skips_unreadable_provider_connection_secret(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    settings.web_search_provider = "disabled"
    service = ProviderConnectionAdminService(database_url, settings)

    service.save_connection(
        {
            "connection_id": "search_zhihu",
            "provider_id": "zhihu",
            "provider_type": "web_search_provider",
            "kind": "web_search_provider",
            "display_name": "Zhihu Search",
            "enabled": True,
            "base_url": "https://developer.zhihu.example",
            "capability_ids": ["web_search"],
            "runtime_profile_ids": ["web-search.managed"],
            "credential": "zhihu-secret",
        }
    )
    with get_session(database_url) as session:
        row = session.get(ProviderConnection, "search_zhihu")
        assert row is not None
        row.secret_ciphertext = "not-a-valid-fernet-token"
        session.commit()

    projection = apply_provider_connection_runtime_settings(settings)

    assert projection.applied_count == 0
    assert projection.web_search_count == 0
    assert settings.web_search_provider == "disabled"
    assert not settings.web_search_zhihu_access_secret

    connections = {
        item["connection_id"]: item for item in service.list_connections()["connections"]
    }
    assert connections["search_zhihu"]["configured"] is False
    assert connections["search_zhihu"]["status"] == "saved_credential_unreadable"
    assert connections["search_zhihu"]["secrets"]["credential"]["display"] == "unreadable"

    dispose_engine(database_url)
