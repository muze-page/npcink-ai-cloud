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
from app.domain.provider_connections.model_allowlist import build_provider_model_allowlist
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
        admin_key_sha256="a" * 64,
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        browser_origin_allowlist="https://cloud.example.com",
        trusted_host_allowlist="cloud.example.com",
        openai_api_key="env-openai-key",
        openai_base_url="https://env-openai.example/v1",
    )


def test_provider_model_allowlist_does_not_block_catalog_when_no_execution_connections(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    allowlist = build_provider_model_allowlist(database_url, settings=_settings(database_url))

    assert allowlist.enforced is False
    assert allowlist.allows(provider_id="openai", model_id="gpt-4.1-mini") is False

    dispose_engine(database_url)


def test_provider_model_allowlist_allows_runtime_execution_provider_fallback(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    allowlist = build_provider_model_allowlist(
        database_url,
        settings=_settings(database_url),
        execution_provider_ids={"openai"},
    )

    assert allowlist.enforced is False
    assert allowlist.allows(provider_id="openai", model_id="gpt-4.1-mini") is True
    assert allowlist.allows(provider_id="anthropic", model_id="claude-3-5-sonnet") is False

    dispose_engine(database_url)


def test_provider_model_allowlist_enforces_enabled_execution_connection_models(
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
            "display_name": "OpenAI primary",
            "enabled": True,
            "base_url": "https://db-openai.example/v1",
            "capability_ids": ["text_generation"],
            "runtime_profile_ids": ["text.balanced"],
            "config": {"model_ids": ["gpt-4.1-mini"]},
            "credential": "db-openai-key",
        }
    )

    allowlist = build_provider_model_allowlist(database_url, settings=settings)

    assert allowlist.enforced is True
    assert allowlist.allows(provider_id="openai", model_id="gpt-4.1-mini") is True
    assert allowlist.allows(provider_id="openai", model_id="gpt-4o") is False

    dispose_engine(database_url)


def test_provider_model_allowlist_uses_declared_models_without_decrypting_secret(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
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
                    "model_ids": ["gpt-wp-ai-connector-test"],
                },
                secret_ciphertext="configured-in-test",
                status="ready",
                source_role="execution_source",
                metadata_json={},
            )
        )
        session.commit()

    allowlist = build_provider_model_allowlist(database_url, settings=_settings(database_url))

    assert allowlist.enforced is True
    assert allowlist.allows(
        provider_id="openai",
        model_id="gpt-wp-ai-connector-test",
    ) is True
    assert allowlist.allows(provider_id="openai", model_id="gpt-4o") is False

    dispose_engine(database_url)


def test_provider_model_allowlist_matches_custom_openai_catalog_namespace(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    with get_session(database_url) as session:
        session.add(
            ProviderConnection(
                connection_id="kimi",
                provider_type="openai_compatible",
                display_name="Kimi",
                enabled=True,
                base_url="https://api.moonshot.test/v1",
                config_json={
                    "provider_id": "kimi",
                    "kind": "openai_compatible",
                    "model_ids": ["kimi-k2.6"],
                },
                secret_ciphertext="configured-in-test",
                status="ready",
                source_role="execution_source",
                metadata_json={},
            )
        )
        session.commit()

    allowlist = build_provider_model_allowlist(database_url, settings=_settings(database_url))

    assert allowlist.allows(provider_id="kimi", model_id="kimi/kimi-k2.6") is True
    assert allowlist.allows(provider_id="kimi", model_id="kimi-k2.6") is False

    dispose_engine(database_url)


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
            "config": {
                "image_output_hosts": ["cdn.openai.example", "assets.openai.example"],
                "image_response_format": "b64_json",
            },
            "credential": "db-openai-key",
        }
    )

    providers = build_provider_adapters(settings, include_enabled_connections=True)
    openai = providers["openai"]

    assert isinstance(openai, OpenAIProviderAdapter)
    assert openai.display_name == "OpenAI primary from DB"
    assert openai.base_url == "https://db-openai.example/v1"
    assert openai.api_key == "db-openai-key"
    assert openai.image_output_hosts == (
        "cdn.openai.example",
        "assets.openai.example",
    )
    assert openai.image_response_format == "b64_json"

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


def test_provider_registry_reuses_openai_transport_for_compatible_text_providers(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    service = ProviderConnectionAdminService(database_url, settings)

    for provider_id, base_url in (
        ("kimi", "https://api.moonshot.cn/v1"),
        ("doubao", "https://ark.cn-beijing.volces.com/api/v3"),
        ("xiaomi_mimo", "https://api.xiaomimimo.com/v1"),
        ("longcat", "https://api.longcat.chat/openai/v1"),
        ("qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        ("hunyuan", "https://tokenhub.tencentmaas.com/v1"),
        ("zhipu_glm", "https://open.bigmodel.cn/api/paas/v4"),
    ):
        service.save_connection(
            {
                "connection_id": f"{provider_id}_primary",
                "provider_id": provider_id,
                "provider_type": "openai_compatible",
                "kind": "openai_compatible",
                "display_name": f"{provider_id.title()} primary",
                "enabled": True,
                "base_url": base_url,
                "capability_ids": ["text_generation"],
                "runtime_profile_ids": ["text.ai"],
                "credential": f"{provider_id}-key",
            }
        )

    providers = build_provider_adapters(settings, include_enabled_connections=True)

    for provider_id, base_url in (
        ("kimi", "https://api.moonshot.cn/v1"),
        ("doubao", "https://ark.cn-beijing.volces.com/api/v3"),
        ("xiaomi_mimo", "https://api.xiaomimimo.com/v1"),
        ("longcat", "https://api.longcat.chat/openai/v1"),
        ("qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        ("hunyuan", "https://tokenhub.tencentmaas.com/v1"),
        ("zhipu_glm", "https://open.bigmodel.cn/api/paas/v4"),
    ):
        adapter = providers[provider_id]
        assert isinstance(adapter, OpenAIProviderAdapter)
        assert adapter.provider_id == provider_id
        assert adapter.model_namespace_prefix == provider_id
        assert adapter.base_url == base_url
        assert adapter.api_key == f"{provider_id}-key"

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

    assert projection.applied_count == 3
    assert settings.web_search_provider == "auto"
    assert settings.web_search_zhihu_base_url == "https://developer.zhihu.example"
    assert settings.web_search_zhihu_access_secret == "zhihu-secret"
    assert settings.web_search_zhihu_hot_list_cache_ttl_seconds == 120
    assert settings.image_source_provider == "auto"
    assert settings.image_source_unsplash_access_key == "unsplash-secret"
    assert projection.embedding_count == 0
    assert settings.site_knowledge_embedding_provider == "deterministic"
    assert settings.site_knowledge_rerank_provider == "jina"
    assert settings.site_knowledge_jina_api_key == "jina-secret"
    assert projection.vector_store_count == 0
    assert settings.site_knowledge_vector_backend == "postgres_json"

    serialized = service.list_connections()
    serialized_connections = {
        item["connection_id"]: item for item in serialized["connections"]
    }
    assert serialized_connections["search_tavily"]["enabled"] is False
    assert serialized_connections["search_zhihu"]["enabled"] is True
    assert serialized_connections["embedding_siliconflow"]["enabled"] is False
    assert serialized_connections["embedding_tei"]["enabled"] is True
    serialized_text = str(serialized)
    assert "tavily-secret" not in serialized_text
    assert "zhihu-secret" not in serialized_text
    assert "unsplash-secret" not in serialized_text
    assert "siliconflow-secret" not in serialized_text
    assert "jina-secret" not in serialized_text
    assert "zilliz-token" not in serialized_text

    dispose_engine(database_url)


def test_runtime_settings_reject_generic_embedding_connection_without_profile_probe(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    settings.site_knowledge_embedding_provider = "deterministic"
    service = ProviderConnectionAdminService(database_url, settings)
    service.save_connection(
        {
            "connection_id": "openai_embedding",
            "provider_id": "openai",
            "provider_type": "openai_compatible",
            "kind": "openai_compatible",
            "display_name": "OpenAI-compatible embedding",
            "enabled": True,
            "base_url": "https://embedding.example/v1",
            "capability_ids": ["embedding"],
            "runtime_profile_ids": ["embed.default"],
            "config": {
                "model_id": "BAAI/bge-large-en-v1.5",
                "model_ids": ["BAAI/bge-large-en-v1.5", "BAAI/bge-m3"],
                "site_knowledge_model_id": "BAAI/bge-m3",
                "dimensions": 1024,
            },
            "credential": "embedding-secret",
        }
    )

    projection = apply_provider_connection_runtime_settings(settings)

    assert projection.embedding_count == 0
    assert settings.site_knowledge_embedding_provider == "deterministic"
    assert settings.site_knowledge_embedding_model == "BAAI/bge-m3"
    assert settings.site_knowledge_embedding_dimensions == 1024

    dispose_engine(database_url)


def test_runtime_settings_reject_undeclared_site_knowledge_model(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    settings.site_knowledge_embedding_provider = "deterministic"
    service = ProviderConnectionAdminService(database_url, settings)
    service.save_connection(
        {
            "connection_id": "openai_embedding",
            "provider_id": "openai",
            "provider_type": "openai_compatible",
            "kind": "openai_compatible",
            "display_name": "OpenAI-compatible embedding",
            "enabled": True,
            "base_url": "https://embedding.example/v1",
            "capability_ids": ["embedding"],
            "runtime_profile_ids": ["embed.default"],
            "config": {
                "model_id": "BAAI/bge-large-en-v1.5",
                "model_ids": ["BAAI/bge-large-en-v1.5"],
                "site_knowledge_model_id": "BAAI/bge-m3",
                "dimensions": 1024,
            },
            "credential": "embedding-secret",
        }
    )

    projection = apply_provider_connection_runtime_settings(settings)

    assert projection.embedding_count == 0
    assert settings.site_knowledge_embedding_provider == "deterministic"

    dispose_engine(database_url)


def test_provider_connection_runtime_selection_uses_fixed_slots_without_priority(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    service = ProviderConnectionAdminService(database_url, settings)

    service.save_connection(
        {
            "connection_id": "search_tavily",
            "provider_id": "tavily",
            "provider_type": "web_search_provider",
            "kind": "web_search_provider",
            "display_name": "Tavily",
            "enabled": True,
            "base_url": "https://api.tavily.com",
            "capability_ids": ["web_search"],
            "runtime_profile_ids": ["web-search.managed"],
            "credential": "tavily-key",
        }
    )
    bocha_payload = {
        "connection_id": "search_bocha",
        "provider_id": "bocha",
        "provider_type": "web_search_provider",
        "kind": "web_search_provider",
        "display_name": "Bocha",
        "enabled": True,
        "base_url": "https://api.bochaai.com/v1",
        "capability_ids": ["web_search"],
        "runtime_profile_ids": ["web-search.managed"],
    }
    service.save_connection(bocha_payload)

    pending_connections = {
        item["connection_id"]: item for item in service.list_connections()["connections"]
    }
    assert pending_connections["search_tavily"]["enabled"] is True
    assert pending_connections["search_bocha"]["status"] == "missing_secret"

    service.save_connection({**bocha_payload, "credential": "bocha-key"})

    connections = {
        item["connection_id"]: item for item in service.list_connections()["connections"]
    }
    assert connections["search_tavily"]["enabled"] is False
    assert connections["search_bocha"]["enabled"] is True
    assert "note" not in connections["search_bocha"]
    assert "priority" not in connections["search_bocha"]

    projection = apply_provider_connection_runtime_settings(settings)

    assert projection.web_search_count == 1
    assert settings.web_search_bocha_api_key == "bocha-key"

    dispose_engine(database_url)


def test_image_source_connections_remain_parallel_without_priority(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    settings.image_source_provider = "disabled"
    service = ProviderConnectionAdminService(database_url, settings)

    for provider_id, base_url, credential in (
        ("unsplash", "https://api.unsplash.com", "unsplash-key"),
        ("pexels", "https://api.pexels.com/v1", "pexels-key"),
    ):
        service.save_connection(
            {
                "connection_id": f"image_{provider_id}",
                "provider_id": provider_id,
                "provider_type": "image_source_provider",
                "kind": "image_source_provider",
                "display_name": provider_id.title(),
                "enabled": True,
                "base_url": base_url,
                "capability_ids": ["image_source"],
                "runtime_profile_ids": ["image-source.managed"],
                "credential": credential,
            }
        )

    connections = {
        item["connection_id"]: item for item in service.list_connections()["connections"]
    }
    assert connections["image_unsplash"]["enabled"] is True
    assert connections["image_pexels"]["enabled"] is True

    projection = apply_provider_connection_runtime_settings(settings)

    assert projection.image_source_count == 2
    assert settings.image_source_provider == "auto"
    assert settings.image_source_unsplash_access_key == "unsplash-key"
    assert settings.image_source_pexels_api_key == "pexels-key"

    dispose_engine(database_url)


def test_jina_reader_remains_independent_when_primary_search_changes(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    service = ProviderConnectionAdminService(database_url, settings)

    for connection_id, provider_id, base_url, runtime_profile_ids, credential in (
        (
            "search_tavily",
            "tavily",
            "https://api.tavily.com",
            ["web-search.managed"],
            "tavily-key",
        ),
        (
            "search_jina_reader",
            "jina_reader",
            "https://r.jina.ai",
            ["web-search.reader"],
            None,
        ),
        (
            "search_bocha",
            "bocha",
            "https://api.bochaai.com/v1",
            ["web-search.managed"],
            "bocha-key",
        ),
    ):
        service.save_connection(
            {
                "connection_id": connection_id,
                "provider_id": provider_id,
                "provider_type": "web_search_provider",
                "kind": "web_search_provider",
                "display_name": provider_id,
                "enabled": True,
                "base_url": base_url,
                "capability_ids": ["web_search"],
                "runtime_profile_ids": runtime_profile_ids,
                "credential": credential,
            }
        )

    connections = {
        item["connection_id"]: item for item in service.list_connections()["connections"]
    }
    assert connections["search_tavily"]["enabled"] is False
    assert connections["search_bocha"]["enabled"] is True
    assert connections["search_jina_reader"]["enabled"] is True
    assert connections["search_jina_reader"]["configured"] is True

    projection = apply_provider_connection_runtime_settings(settings)

    assert projection.web_search_count == 2
    assert settings.web_search_provider == "auto"
    assert settings.web_search_bocha_api_key == "bocha-key"
    assert settings.web_search_jina_reader_enabled is True

    dispose_engine(database_url)


def test_clearing_external_service_credential_persists_disabled_runtime_state(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    service = ProviderConnectionAdminService(database_url, settings)
    payload = {
        "connection_id": "image_unsplash",
        "provider_id": "unsplash",
        "provider_type": "image_source_provider",
        "kind": "image_source_provider",
        "display_name": "Unsplash",
        "enabled": True,
        "base_url": "https://api.unsplash.com",
        "capability_ids": ["image_source"],
        "runtime_profile_ids": ["image-source.managed"],
    }

    service.save_connection({**payload, "credential": "unsplash-key"})
    assert apply_provider_connection_runtime_settings(settings).image_source_count == 1
    assert settings.image_source_provider == "auto"

    service.save_connection(
        {**payload, "enabled": False, "credential": ""},
        connection_id="image_unsplash",
    )

    stored = {
        item["connection_id"]: item for item in service.list_connections()["connections"]
    }["image_unsplash"]
    assert stored["enabled"] is False
    assert stored["configured"] is False
    assert stored["status"] == "disabled"

    reloaded_settings = _settings(database_url)
    projection = apply_provider_connection_runtime_settings(reloaded_settings)

    assert projection.image_source_count == 0
    assert reloaded_settings.image_source_provider == "disabled"
    assert not reloaded_settings.image_source_unsplash_access_key

    dispose_engine(database_url)


def test_generic_vector_connection_cannot_override_fixed_profile(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    service = ProviderConnectionAdminService(database_url, settings)

    vector_payload = {
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
    rerank_payload = {
        "connection_id": "rerank_jina",
        "provider_id": "jina",
        "provider_type": "rerank_provider",
        "kind": "rerank_provider",
        "display_name": "Jina Rerank",
        "enabled": True,
        "base_url": "https://api.jina.ai",
        "capability_ids": ["site_knowledge_rerank"],
        "runtime_profile_ids": ["site-knowledge.rerank"],
        "config": {"model_id": "jina-reranker-v3"},
        "credential": "jina-token",
    }
    service.save_connection(vector_payload)
    service.save_connection(rerank_payload)

    initial_projection = apply_provider_connection_runtime_settings(settings)
    assert initial_projection.vector_store_count == 0
    assert settings.site_knowledge_vector_backend == "postgres_json"
    assert settings.site_knowledge_rerank_provider == "jina"

    service.save_connection({**vector_payload, "enabled": False}, connection_id="vector_zilliz")
    service.save_connection({**rerank_payload, "enabled": False}, connection_id="rerank_jina")
    apply_provider_connection_runtime_settings(settings)

    assert settings.site_knowledge_vector_backend == "postgres_json"
    assert settings.site_knowledge_rerank_provider == "disabled"

    dispose_engine(database_url)


def test_empty_provider_connection_registry_preserves_explicit_runtime_settings(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    settings.image_source_provider = "unsplash"
    settings.site_knowledge_embedding_provider = "tei"
    settings.site_knowledge_embedding_model = "tei/BAAI/bge-m3"

    projection = apply_provider_connection_runtime_settings(settings)

    assert projection.applied_count == 0
    assert settings.image_source_provider == "unsplash"
    assert settings.site_knowledge_embedding_provider == "tei"
    assert settings.site_knowledge_embedding_model == "tei/BAAI/bge-m3"

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
