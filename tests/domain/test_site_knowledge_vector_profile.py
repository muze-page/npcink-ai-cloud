from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.providers.base import ProviderExecutionResult
from app.adapters.providers.siliconflow import SiliconFlowProviderAdapter
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    ProviderConnection,
    Site,
    SiteKnowledgeChunk,
    SiteKnowledgeDocument,
)
from app.core.secrets import encrypt_provider_connection_secret
from app.domain.provider_connections.runtime_settings import (
    apply_provider_connection_runtime_settings,
)
from app.domain.provider_connections.service import ProviderConnectionAdminService
from app.domain.site_knowledge import vector_profile as vector_profile_module
from app.domain.site_knowledge.backends import (
    SiteKnowledgeBackendError,
    ZillizCloudSiteKnowledgeBackend,
)
from app.domain.site_knowledge.vector_profile import (
    SiteKnowledgeVectorProfileAdminError,
    SiteKnowledgeVectorProfileAdminService,
)
from app.domain.site_knowledge.vector_profile_contract import (
    SITE_KNOWLEDGE_VECTOR_BASE_URL,
    SITE_KNOWLEDGE_VECTOR_CONNECTION_ID,
    SITE_KNOWLEDGE_VECTOR_DIMENSIONS,
    SITE_KNOWLEDGE_VECTOR_MODEL_ID,
    SITE_KNOWLEDGE_VECTOR_PROBE_REVISION,
    SITE_KNOWLEDGE_VECTOR_PROFILE_ID,
    SITE_KNOWLEDGE_VECTOR_PROVIDER_ID,
    SITE_KNOWLEDGE_VECTOR_STORE_COLLECTION,
    SITE_KNOWLEDGE_VECTOR_STORE_CONNECTION_ID,
)
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'site-knowledge-vector-profile.sqlite3'}"


def _settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        site_knowledge_embedding_provider="deterministic",
        siliconflow_provider_enabled=False,
        siliconflow_api_key="",
    )


def _probe_result(
    *,
    vector: object,
    model_id: str = SITE_KNOWLEDGE_VECTOR_MODEL_ID,
) -> ProviderExecutionResult:
    return ProviderExecutionResult(
        output={"embedding": vector, "model_id": model_id},
        latency_ms=24,
        tokens_in=8,
        tokens_out=0,
        cost=0.0,
    )


def test_fixed_vector_profile_saves_only_after_a_valid_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    service = SiteKnowledgeVectorProfileAdminService(database_url, settings)

    monkeypatch.setattr(
        SiliconFlowProviderAdapter,
        "execute",
        lambda _adapter, _request: _probe_result(
            vector=[0.01] * SITE_KNOWLEDGE_VECTOR_DIMENSIONS
        ),
    )

    initial = service.get_profile()
    assert initial["status"] == "not_configured"
    assert initial["profile_id"] == SITE_KNOWLEDGE_VECTOR_PROFILE_ID
    assert initial["model_id"] == SITE_KNOWLEDGE_VECTOR_MODEL_ID
    assert initial["dimensions"] == SITE_KNOWLEDGE_VECTOR_DIMENSIONS
    assert initial["editable_fields"] == [
        "credential",
        "zilliz_endpoint",
        "zilliz_token",
    ]

    result = service.save_and_verify("siliconflow-secret")

    assert result["status"] == "ready"
    assert result["probe"]["dimensions"] == SITE_KNOWLEDGE_VECTOR_DIMENSIONS
    assert result["provider"]["verified"] is True
    assert "siliconflow-secret" not in str(result)
    assert settings.site_knowledge_embedding_provider == "siliconflow"
    assert settings.site_knowledge_embedding_model == SITE_KNOWLEDGE_VECTOR_MODEL_ID
    assert settings.site_knowledge_embedding_dimensions == SITE_KNOWLEDGE_VECTOR_DIMENSIONS

    with get_session(database_url) as session:
        row = session.get(ProviderConnection, SITE_KNOWLEDGE_VECTOR_CONNECTION_ID)
        assert row is not None
        assert row.secret_ciphertext
        assert row.secret_ciphertext != "siliconflow-secret"
        assert row.status == "ready"
        assert row.config_json["site_knowledge_profile_id"] == (
            SITE_KNOWLEDGE_VECTOR_PROFILE_ID
        )

    dispose_engine(database_url)


@pytest.mark.parametrize(
    ("vector", "error_code"),
    [
        ([], "site_knowledge_vector_profile.embedding_invalid"),
        ([0.0] * 768, "site_knowledge_vector_profile.dimension_mismatch"),
        ([0.0] * 1536, "site_knowledge_vector_profile.dimension_mismatch"),
        ([0.0, "invalid"] + [0.0] * 1022, "site_knowledge_vector_profile.embedding_invalid"),
        ([0.0, float("nan")] + [0.0] * 1022, "site_knowledge_vector_profile.embedding_invalid"),
        ([0.0, float("inf")] + [0.0] * 1022, "site_knowledge_vector_profile.embedding_invalid"),
    ],
)
def test_fixed_vector_profile_rejects_invalid_vectors_before_persisting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    vector: object,
    error_code: str,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    service = SiteKnowledgeVectorProfileAdminService(database_url, settings)
    monkeypatch.setattr(
        SiliconFlowProviderAdapter,
        "execute",
        lambda _adapter, _request: _probe_result(vector=vector),
    )

    with pytest.raises(SiteKnowledgeVectorProfileAdminError) as caught:
        service.save_and_verify("siliconflow-secret")

    assert caught.value.error_code == error_code
    with get_session(database_url) as session:
        assert session.get(ProviderConnection, SITE_KNOWLEDGE_VECTOR_CONNECTION_ID) is None

    dispose_engine(database_url)


def test_generic_provider_connection_write_cannot_forge_profile_verification(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    ProviderConnectionAdminService(database_url, settings).save_connection(
        {
            "connection_id": SITE_KNOWLEDGE_VECTOR_CONNECTION_ID,
            "provider_id": "siliconflow",
            "provider_type": "siliconflow",
            "kind": "siliconflow",
            "display_name": "Forged profile",
            "enabled": True,
            "base_url": "https://example.invalid/v1",
            "capability_ids": ["embedding"],
            "runtime_profile_ids": ["embed.default"],
            "config": {
                "model_id": SITE_KNOWLEDGE_VECTOR_MODEL_ID,
                "dimensions": SITE_KNOWLEDGE_VECTOR_DIMENSIONS,
                "metric": "COSINE",
                "site_knowledge_profile_id": SITE_KNOWLEDGE_VECTOR_PROFILE_ID,
                "site_knowledge_probe_revision": "site-knowledge-vector-probe.v1",
            },
            "credential": "unverified-secret",
        }
    )

    projection = apply_provider_connection_runtime_settings(settings)
    profile = SiteKnowledgeVectorProfileAdminService(database_url, settings).get_profile()

    assert projection.embedding_count == 0
    assert settings.site_knowledge_embedding_provider == "deterministic"
    assert profile["status"] == "probe_required"
    assert profile["provider"]["verified"] is False

    dispose_engine(database_url)


def test_fixed_vector_profile_rejects_unexpected_reported_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = SiteKnowledgeVectorProfileAdminService(
        database_url,
        _settings(database_url),
    )
    monkeypatch.setattr(
        SiliconFlowProviderAdapter,
        "execute",
        lambda _adapter, _request: _probe_result(
            vector=[0.0] * SITE_KNOWLEDGE_VECTOR_DIMENSIONS,
            model_id="BAAI/bge-large-zh-v1.5",
        ),
    )

    with pytest.raises(SiteKnowledgeVectorProfileAdminError) as caught:
        service.save_and_verify("siliconflow-secret")

    assert caught.value.error_code == "site_knowledge_vector_profile.model_mismatch"
    dispose_engine(database_url)


def test_fixed_vector_store_verifies_and_persists_encrypted_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    observed: dict[str, object] = {}

    def fake_backend(probe_settings: Settings) -> object:
        observed["uri"] = probe_settings.site_knowledge_zilliz_uri
        observed["token"] = probe_settings.site_knowledge_zilliz_token
        observed["collection"] = probe_settings.site_knowledge_zilliz_collection
        observed["dimensions"] = probe_settings.site_knowledge_embedding_dimensions
        observed["metric"] = probe_settings.site_knowledge_vector_metric_type
        return object()

    monkeypatch.setattr(
        vector_profile_module,
        "ZillizCloudSiteKnowledgeBackend",
        fake_backend,
    )
    service = SiteKnowledgeVectorProfileAdminService(database_url, settings)

    result = service.save_and_verify_vector_store(
        "https://cluster.example.zillizcloud.com/",
        "zilliz-secret",
    )

    assert result["vector_store"]["verified"] is True
    assert result["vector_store"]["endpoint"] == (
        "https://cluster.example.zillizcloud.com"
    )
    assert result["vector_store"]["collection"] == SITE_KNOWLEDGE_VECTOR_STORE_COLLECTION
    assert result["vector_store_probe"]["dimensions"] == 1024
    assert "zilliz-secret" not in str(result)
    assert observed == {
        "uri": "https://cluster.example.zillizcloud.com",
        "token": "zilliz-secret",
        "collection": SITE_KNOWLEDGE_VECTOR_STORE_COLLECTION,
        "dimensions": 1024,
        "metric": "COSINE",
    }
    assert settings.site_knowledge_vector_backend == "zilliz_cloud"
    assert settings.site_knowledge_zilliz_collection == SITE_KNOWLEDGE_VECTOR_STORE_COLLECTION

    with get_session(database_url) as session:
        row = session.get(ProviderConnection, SITE_KNOWLEDGE_VECTOR_STORE_CONNECTION_ID)
        assert row is not None
        assert row.status == "ready"
        assert row.secret_ciphertext
        assert row.secret_ciphertext != "zilliz-secret"
        assert row.config_json["site_knowledge_vector_store_dimensions"] == 1024
        assert row.config_json["site_knowledge_vector_store_metric"] == "COSINE"

    dispose_engine(database_url)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://in03-example.cn-beijing.vectordb.zilliz.com.cn:19530/",
        "https://in03-example.serverless.ali-cn-hangzhou.cloud.zilliz.com.cn/",
    ],
)
def test_fixed_vector_store_accepts_china_public_endpoints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    monkeypatch.setattr(
        vector_profile_module,
        "ZillizCloudSiteKnowledgeBackend",
        lambda _settings: object(),
    )
    service = SiteKnowledgeVectorProfileAdminService(
        database_url,
        _settings(database_url),
    )

    result = service.save_and_verify_vector_store(
        endpoint,
        "zilliz-secret",
    )

    assert result["vector_store"]["verified"] is True
    assert result["vector_store"]["endpoint"] == endpoint.rstrip("/")
    dispose_engine(database_url)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://cluster.example.zillizcloud.com",
        "https://vector.example.com",
        "https://api.cloud.zilliz.com.cn",
        "https://user:pass@cluster.example.zillizcloud.com",
        "https://cluster.example.zillizcloud.com/private",
        "https://cluster.example.zillizcloud.com?token=secret",
    ],
)
def test_fixed_vector_store_rejects_unsafe_endpoints(
    tmp_path: Path,
    endpoint: str,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = SiteKnowledgeVectorProfileAdminService(
        database_url,
        _settings(database_url),
    )

    with pytest.raises(SiteKnowledgeVectorProfileAdminError) as caught:
        service.save_and_verify_vector_store(endpoint, "zilliz-secret")

    assert caught.value.error_code == (
        "site_knowledge_vector_profile.zilliz_endpoint_invalid"
    )
    with get_session(database_url) as session:
        assert session.get(ProviderConnection, SITE_KNOWLEDGE_VECTOR_STORE_CONNECTION_ID) is None
    dispose_engine(database_url)


def test_production_profile_requires_a_verified_vector_store(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    settings.environment = "production"
    service = SiteKnowledgeVectorProfileAdminService(database_url, settings)

    with get_session(database_url) as session:
        session.add(
            ProviderConnection(
                connection_id=SITE_KNOWLEDGE_VECTOR_CONNECTION_ID,
                provider_type=SITE_KNOWLEDGE_VECTOR_PROVIDER_ID,
                display_name="Verified embedding",
                enabled=True,
                base_url=SITE_KNOWLEDGE_VECTOR_BASE_URL,
                config_json={
                    "site_knowledge_profile_id": SITE_KNOWLEDGE_VECTOR_PROFILE_ID,
                    "site_knowledge_probe_revision": SITE_KNOWLEDGE_VECTOR_PROBE_REVISION,
                    "site_knowledge_model_id": SITE_KNOWLEDGE_VECTOR_MODEL_ID,
                    "dimensions": SITE_KNOWLEDGE_VECTOR_DIMENSIONS,
                    "metric": "COSINE",
                },
                secret_ciphertext=encrypt_provider_connection_secret(
                    "embedding-secret",
                    settings=settings,
                ),
                status="ready",
                source_role="execution_source",
                metadata_json={},
            )
        )
        session.add(
            ProviderConnection(
                connection_id=SITE_KNOWLEDGE_VECTOR_STORE_CONNECTION_ID,
                provider_type="vector_store_provider",
                display_name="Unverified Zilliz",
                enabled=True,
                base_url="https://cluster.example.zillizcloud.com",
                config_json={
                    "uri": "https://cluster.example.zillizcloud.com",
                    "collection": SITE_KNOWLEDGE_VECTOR_STORE_COLLECTION,
                },
                secret_ciphertext=encrypt_provider_connection_secret(
                    "zilliz-secret",
                    settings=settings,
                ),
                status="ready",
                source_role="execution_source",
                metadata_json={},
            )
        )
        session.commit()

    profile = service.get_profile()

    assert profile["provider"]["verified"] is True
    assert profile["vector_store"]["configured"] is True
    assert profile["vector_store"]["verified"] is False
    assert profile["status"] == "vector_store_pending"
    dispose_engine(database_url)


def test_fixed_vector_store_fails_closed_on_incompatible_collection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    def incompatible_backend(_settings: Settings) -> object:
        raise SiteKnowledgeBackendError(
            "site_knowledge.zilliz_schema_incompatible",
            "incompatible schema detail",
        )

    monkeypatch.setattr(
        vector_profile_module,
        "ZillizCloudSiteKnowledgeBackend",
        incompatible_backend,
    )
    service = SiteKnowledgeVectorProfileAdminService(
        database_url,
        _settings(database_url),
    )

    with pytest.raises(SiteKnowledgeVectorProfileAdminError) as caught:
        service.save_and_verify_vector_store(
            "https://cluster.example.zillizcloud.com",
            "zilliz-secret",
        )

    assert caught.value.error_code == (
        "site_knowledge_vector_profile.zilliz_schema_incompatible"
    )
    assert "incompatible schema detail" not in caught.value.message
    with get_session(database_url) as session:
        assert session.get(ProviderConnection, SITE_KNOWLEDGE_VECTOR_STORE_CONNECTION_ID) is None
    dispose_engine(database_url)


def test_fixed_vector_store_reports_missing_runtime_sdk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    def missing_sdk_backend(_settings: Settings) -> object:
        raise SiteKnowledgeBackendError(
            "site_knowledge.zilliz_sdk_missing",
            "internal dependency detail",
        )

    monkeypatch.setattr(
        vector_profile_module,
        "ZillizCloudSiteKnowledgeBackend",
        missing_sdk_backend,
    )
    service = SiteKnowledgeVectorProfileAdminService(
        database_url,
        _settings(database_url),
    )

    with pytest.raises(SiteKnowledgeVectorProfileAdminError) as caught:
        service.save_and_verify_vector_store(
            "https://cluster.example.zillizcloud.com",
            "zilliz-secret",
        )

    assert caught.value.error_code == (
        "site_knowledge_vector_profile.zilliz_sdk_unavailable"
    )
    assert caught.value.status_code == 503
    assert "internal dependency detail" not in caught.value.message
    with get_session(database_url) as session:
        assert session.get(ProviderConnection, SITE_KNOWLEDGE_VECTOR_STORE_CONNECTION_ID) is None
    dispose_engine(database_url)


def test_generic_vector_store_write_cannot_forge_profile_verification(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    ProviderConnectionAdminService(database_url, settings).save_connection(
        {
            "connection_id": SITE_KNOWLEDGE_VECTOR_STORE_CONNECTION_ID,
            "provider_id": "zilliz",
            "provider_type": "vector_store_provider",
            "kind": "vector_store_provider",
            "display_name": "Forged Zilliz profile",
            "enabled": True,
            "base_url": "https://cluster.example.zillizcloud.com",
            "capability_ids": ["vector_store"],
            "runtime_profile_ids": ["site-knowledge.vector-store"],
            "config": {
                "collection": SITE_KNOWLEDGE_VECTOR_STORE_COLLECTION,
                "site_knowledge_vector_store_profile_id": SITE_KNOWLEDGE_VECTOR_PROFILE_ID,
                "site_knowledge_vector_store_probe_revision": (
                    "site-knowledge-vector-store-probe.v1"
                ),
                "site_knowledge_vector_store_dimensions": 1024,
                "site_knowledge_vector_store_metric": "COSINE",
            },
            "credential": "unverified-secret",
        }
    )

    projection = apply_provider_connection_runtime_settings(settings)
    profile = SiteKnowledgeVectorProfileAdminService(database_url, settings).get_profile()

    assert projection.vector_store_count == 0
    assert settings.site_knowledge_vector_backend == "postgres_json"
    assert profile["vector_store"]["verified"] is False
    dispose_engine(database_url)


def test_vector_store_requires_reindex_and_rebuilds_compatible_cloud_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    service = SiteKnowledgeVectorProfileAdminService(database_url, settings)
    expected_space = f"{SITE_KNOWLEDGE_VECTOR_PROVIDER_ID}:{SITE_KNOWLEDGE_VECTOR_MODEL_ID}"

    with get_session(database_url) as session:
        session.add(Site(site_id="site-1", name="Site 1", metadata_json={}))
        session.add(
            SiteKnowledgeDocument(
                site_id="site-1",
                post_id=10,
                source_type="post",
                source_id=10,
                parent_post_id=None,
                post_type="post",
                post_status="publish",
                title="Vector lifecycle",
                url="https://example.com/vector-lifecycle",
                modified_gmt="2026-07-14 10:00:00",
                content_hash="document-hash",
                last_sync_run_id=None,
                metadata_json={},
            )
        )
        session.add(
            SiteKnowledgeChunk(
                site_id="site-1",
                post_id=10,
                source_type="post",
                source_id=10,
                parent_post_id=None,
                chunk_index=0,
                post_type="post",
                post_status="publish",
                title="Vector lifecycle",
                url="https://example.com/vector-lifecycle",
                chunk_text="A compatible Site Knowledge chunk.",
                embedding_json=[0.01] * SITE_KNOWLEDGE_VECTOR_DIMENSIONS,
                embedding_model=expected_space,
                content_hash="chunk-hash",
                metadata_json={},
            )
        )
        session.commit()

    monkeypatch.setattr(
        SiliconFlowProviderAdapter,
        "execute",
        lambda _adapter, _request: _probe_result(
            vector=[0.01] * SITE_KNOWLEDGE_VECTOR_DIMENSIONS
        ),
    )

    class FakeBackend:
        def __init__(self) -> None:
            self.deleted_sites: list[str] = []
            self.upserted: list[dict[str, object]] = []

        def delete_site_index(self, site_id: str) -> None:
            self.deleted_sites.append(site_id)

        def upsert_chunks(self, *, site_id: str, chunks: list[dict[str, object]]) -> None:
            self.upserted.extend({"site_id": site_id, **chunk} for chunk in chunks)

        def search(self, **_kwargs: object) -> list[object]:
            return [object()]

    backend = FakeBackend()
    monkeypatch.setattr(
        vector_profile_module,
        "ZillizCloudSiteKnowledgeBackend",
        lambda _settings: backend,
    )

    service.save_and_verify("siliconflow-secret")
    saved = service.save_and_verify_vector_store(
        "https://cluster.example.zillizcloud.com",
        "zilliz-secret",
    )

    assert saved["status"] == "reindex_required"
    assert saved["validation"]["index"]["source_document_count"] == 1
    assert saved["validation"]["index"]["source_chunk_count"] == 1
    assert saved["active_backend"] == "postgres_json"
    assert settings.site_knowledge_vector_backend == "postgres_json"

    rebuilt = service.rebuild_index()

    assert rebuilt["status"] == "ready"
    assert rebuilt["validation"]["index"]["status"] == "ready"
    assert rebuilt["validation"]["index"]["indexed_chunk_count"] == 1
    assert rebuilt["validation"]["index"]["roundtrip_status"] == "passed"
    assert rebuilt["validation"]["retrieval"]["status"] == "pending"
    assert rebuilt["active_backend"] == "zilliz_cloud"
    assert settings.site_knowledge_vector_backend == "zilliz_cloud"
    assert backend.deleted_sites == ["site-1"]
    assert len(backend.upserted) == 1
    assert len(backend.upserted[0]["embedding"]) == 1024
    dispose_engine(database_url)


def test_vector_rebuild_fails_before_zilliz_write_for_wrong_embedding_space(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    service = SiteKnowledgeVectorProfileAdminService(database_url, settings)

    with get_session(database_url) as session:
        session.add(Site(site_id="site-1", name="Site 1", metadata_json={}))
        session.add(
            SiteKnowledgeChunk(
                site_id="site-1",
                post_id=10,
                source_type="post",
                source_id=10,
                parent_post_id=None,
                chunk_index=0,
                post_type="post",
                post_status="publish",
                title="Old space",
                url="https://example.com/old-space",
                chunk_text="An incompatible chunk.",
                embedding_json=[0.01] * SITE_KNOWLEDGE_VECTOR_DIMENSIONS,
                embedding_model="deterministic:old-model",
                content_hash="old-space-hash",
                metadata_json={},
            )
        )
        session.commit()

    monkeypatch.setattr(
        SiliconFlowProviderAdapter,
        "execute",
        lambda _adapter, _request: _probe_result(
            vector=[0.01] * SITE_KNOWLEDGE_VECTOR_DIMENSIONS
        ),
    )
    backend_calls: list[str] = []

    class FakeBackend:
        def delete_site_index(self, _site_id: str) -> None:
            backend_calls.append("delete")

    monkeypatch.setattr(
        vector_profile_module,
        "ZillizCloudSiteKnowledgeBackend",
        lambda _settings: FakeBackend(),
    )
    service.save_and_verify("siliconflow-secret")
    service.save_and_verify_vector_store(
        "https://cluster.example.zillizcloud.com",
        "zilliz-secret",
    )

    with pytest.raises(SiteKnowledgeVectorProfileAdminError) as caught:
        service.rebuild_index()

    assert caught.value.error_code == (
        "site_knowledge_vector_profile.embedding_space_mismatch"
    )
    assert backend_calls == []
    assert service.get_profile()["validation"]["index"]["status"] == (
        "reindex_required"
    )
    dispose_engine(database_url)


def test_zilliz_collection_validation_rejects_wrong_metric() -> None:
    class FakeDataType:
        VARCHAR = "VARCHAR"
        FLOAT_VECTOR = "FLOAT_VECTOR"

    class FakeClient:
        def describe_collection(self, _collection: str) -> dict[str, object]:
            return {
                "fields": [
                    {"name": "id", "type": "VARCHAR"},
                    {"name": "vector", "type": "FLOAT_VECTOR", "params": {"dim": 1024}},
                    {"name": "site_id", "type": "VARCHAR"},
                    {"name": "post_id", "type": "INT64"},
                    {"name": "source_type", "type": "VARCHAR"},
                    {"name": "source_id", "type": "INT64"},
                    {"name": "parent_post_id", "type": "INT64"},
                    {"name": "chunk_index", "type": "INT64"},
                    {"name": "post_type", "type": "VARCHAR"},
                    {"name": "post_status", "type": "VARCHAR"},
                    {"name": "title", "type": "VARCHAR"},
                    {"name": "url", "type": "VARCHAR"},
                    {"name": "chunk_text", "type": "VARCHAR"},
                    {"name": "content_hash", "type": "VARCHAR"},
                    {"name": "indexed_at", "type": "VARCHAR"},
                ]
            }

        def list_indexes(self, **_kwargs: object) -> list[str]:
            return ["vector"]

        def describe_index(self, **_kwargs: object) -> dict[str, str]:
            return {"metric_type": "L2"}

    backend = object.__new__(ZillizCloudSiteKnowledgeBackend)
    backend.client = FakeClient()
    backend.data_type = FakeDataType()
    backend.collection = SITE_KNOWLEDGE_VECTOR_STORE_COLLECTION
    backend.dimension = 1024
    backend.metric_type = "COSINE"

    with pytest.raises(SiteKnowledgeBackendError) as caught:
        backend._validate_collection_schema()

    assert caught.value.error_code == "site_knowledge.zilliz_schema_incompatible"
