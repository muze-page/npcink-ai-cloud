from __future__ import annotations

from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import ProviderConnection
from app.core.secrets import decrypt_provider_connection_secret
from app.dev.import_provider_connections_from_env import (
    import_provider_connections_from_env,
    remove_imported_provider_env_keys,
)


def _sqlite_url(tmp_path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'provider-env-import.sqlite3'}"


def _settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token="npcink-cloud-internal-test-token-32b",
        admin_session_secret="npcink-cloud-admin-session-secret-32b",
        portal_jwt_secret="npcink-cloud-portal-jwt-secret-32b",
    )


def test_import_provider_connections_from_env_stores_connections_without_secret_output(
    tmp_path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    env = {
        "NPCINK_CLOUD_WEB_SEARCH_PROVIDER": "zhihu",
        "NPCINK_CLOUD_WEB_SEARCH_BOCHA_API_KEY": "bocha-secret",
        "NPCINK_CLOUD_WEB_SEARCH_BOCHA_BASE_URL": "https://api.bochaai.test/v1",
        "NPCINK_CLOUD_WEB_SEARCH_APIFY_API_TOKEN": "apify-token",
        "NPCINK_CLOUD_WEB_SEARCH_APIFY_ACTOR_ID": "apify/test-search-scraper",
        "NPCINK_CLOUD_WEB_SEARCH_JINA_READER_ENABLED": "1",
        "NPCINK_CLOUD_WEB_SEARCH_ZHIHU_ACCESS_SECRET": "zhihu-secret",
        "NPCINK_CLOUD_WEB_SEARCH_ZHIHU_BASE_URL": "https://developer.zhihu.test",
        "NPCINK_CLOUD_IMAGE_SOURCE_UNSPLASH_ACCESS_KEY": "unsplash-secret",
        "NPCINK_CLOUD_SITE_KNOWLEDGE_EMBEDDING_PROVIDER": "tei",
        "NPCINK_CLOUD_SITE_KNOWLEDGE_EMBEDDING_MODEL": "BAAI/bge-m3",
        "NPCINK_CLOUD_TEI_BASE_URL": "http://tei.local",
        "NPCINK_CLOUD_TEI_MODEL_IDS": "BAAI/bge-m3",
        "NPCINK_CLOUD_SITE_KNOWLEDGE_VECTOR_BACKEND": "zilliz_cloud",
        "NPCINK_CLOUD_SITE_KNOWLEDGE_ZILLIZ_URI": "https://zilliz.example",
        "NPCINK_CLOUD_SITE_KNOWLEDGE_ZILLIZ_TOKEN": "zilliz-token",
        "NPCINK_CLOUD_SITE_KNOWLEDGE_ZILLIZ_COLLECTION": "site_chunks",
    }

    dry_run = import_provider_connections_from_env(
        settings=settings,
        env=env,
        apply=False,
    )

    assert dry_run["mode"] == "dry_run"
    assert dry_run["imported"] == []
    assert "zhihu-secret" not in str(dry_run)
    assert "unsplash-secret" not in str(dry_run)
    assert "zilliz-token" not in str(dry_run)

    result = import_provider_connections_from_env(
        settings=settings,
        env=env,
        apply=True,
    )

    assert result["mode"] == "apply"
    assert set(result["imported"]) == {
        "search_bocha",
        "search_apify",
        "search_jina_reader",
        "search_zhihu",
        "image_unsplash",
        "embedding_tei",
        "vector_zilliz",
    }
    assert result["credential_value_exposure"] == "none"
    assert "zhihu-secret" not in str(result)
    assert "bocha-secret" not in str(result)
    assert "apify-token" not in str(result)
    assert "unsplash-secret" not in str(result)
    assert "zilliz-token" not in str(result)

    with get_session(database_url) as session:
        zhihu = session.get(ProviderConnection, "search_zhihu")
        bocha = session.get(ProviderConnection, "search_bocha")
        apify = session.get(ProviderConnection, "search_apify")
        jina_reader = session.get(ProviderConnection, "search_jina_reader")
        image = session.get(ProviderConnection, "image_unsplash")
        vector = session.get(ProviderConnection, "vector_zilliz")
        assert zhihu is not None
        assert bocha is not None
        assert apify is not None
        assert jina_reader is not None
        assert image is not None
        assert vector is not None
        assert zhihu.config_json["provider_id"] == "zhihu"
        assert zhihu.config_json["provider_mode"] == "zhihu"
        assert bocha.config_json["provider_id"] == "bocha"
        assert apify.config_json["provider_id"] == "apify"
        assert apify.config_json["actor_id"] == "apify/test-search-scraper"
        assert jina_reader.config_json["provider_id"] == "jina_reader"
        assert jina_reader.config_json["secretless"] is True
        assert image.config_json["provider_id"] == "unsplash"
        assert vector.config_json["collection"] == "site_chunks"
        assert (
            decrypt_provider_connection_secret(zhihu.secret_ciphertext, settings=settings)
            == "zhihu-secret"
        )
        assert (
            decrypt_provider_connection_secret(bocha.secret_ciphertext, settings=settings)
            == "bocha-secret"
        )
        assert (
            decrypt_provider_connection_secret(apify.secret_ciphertext, settings=settings)
            == "apify-token"
        )

    dispose_engine(database_url)


def test_remove_imported_provider_env_keys_only_removes_selected_keys(tmp_path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "NPCINK_CLOUD_WEB_SEARCH_ZHIHU_ACCESS_SECRET=zhihu-secret",
                "NPCINK_CLOUD_SITE_KNOWLEDGE_MAX_SYNC_DOCUMENTS_PER_RUN=500",
                "NPCINK_CLOUD_IMAGE_SOURCE_UNSPLASH_ACCESS_KEY=unsplash-secret",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = remove_imported_provider_env_keys(
        env_files=[str(env_file)],
        keys={
            "NPCINK_CLOUD_WEB_SEARCH_ZHIHU_ACCESS_SECRET",
            "NPCINK_CLOUD_IMAGE_SOURCE_UNSPLASH_ACCESS_KEY",
        },
    )

    text = env_file.read_text(encoding="utf-8")
    assert result["changed_files"] == [str(env_file)]
    assert "WEB_SEARCH_ZHIHU_ACCESS_SECRET" not in text
    assert "IMAGE_SOURCE_UNSPLASH_ACCESS_KEY" not in text
    assert "SITE_KNOWLEDGE_MAX_SYNC_DOCUMENTS_PER_RUN=500" in text
