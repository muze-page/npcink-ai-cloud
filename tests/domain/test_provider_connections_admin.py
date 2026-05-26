from __future__ import annotations

from pathlib import Path

from app.adapters.providers.registry import (
    build_provider_adapters,
    resolve_execution_provider_adapters,
)
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import ProviderConnection
from app.domain.catalog.service import CatalogService


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'provider-connections.sqlite3'}"


def _build_settings(database_url: str) -> Settings:
    return Settings(
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        admin_session_secret="x" * 32,
        provider_connection_secret="p" * 32,
    )


def _build_production_settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="production",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        openai_api_key="sk-env-should-be-ignored",
        internal_auth_token="i" * 32,
        admin_bootstrap_token="b" * 32,
        admin_session_secret="a" * 32,
        provider_connection_secret="p" * 32,
        portal_public_base_url="https://cloud.example.com",
        portal_jwt_secret="j" * 32,
        portal_email_smtp_host="smtp.example.com",
        portal_email_from_email="no-reply@example.com",
    )


def test_provider_connection_can_be_saved_and_listed(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = CatalogService(database_url, settings=_build_settings(database_url))

    saved = service.upsert_admin_provider_connection(
        connection_id="openai-main",
        provider_type="openai",
        source_role="execution_source",
        display_name="OpenAI Main",
        enabled=True,
        base_url="https://api.openai.com/v1",
        config={"timeout_seconds": 45, "organization": "org_demo"},
        api_key="sk-test-123",
    )
    listed = service.list_admin_provider_connections()

    assert saved["connection_id"] == "openai-main"
    assert saved["has_secret"] is True
    assert listed["total"] == 1
    assert listed["items"][0]["provider_type"] == "openai"
    assert listed["items"][0]["source_role"] == "execution_source"
    assert listed["items"][0]["config"]["organization"] == "org_demo"
    assert listed["items"][0]["last_sync_revision"] == ""
    assert listed["items"][0]["active_execution_revision"] == ""
    assert listed["items"][0]["execution_release_state"] == "draft"
    assert listed["summary"]["source_role_counts"]["execution_source"] == 1
    assert listed["summary"]["source_role_counts"]["intelligence_source"] == 0
    assert listed["summary"]["source_role_counts"]["dual_source"] == 0
    assert saved["credential_origin"] == "cloud_local"
    assert saved["credential_scope"] == "cloud_only"
    assert listed["items"][0]["credential_origin"] == "cloud_local"
    assert listed["items"][0]["credential_scope"] == "cloud_only"

    dispose_engine(database_url)


def test_provider_connection_test_and_sync_use_namespaced_catalog_models(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = CatalogService(database_url, settings=_build_settings(database_url))
    service.upsert_admin_provider_connection(
        connection_id="openai-main",
        provider_type="openai",
        source_role="execution_source",
        display_name="OpenAI Main",
        enabled=True,
        base_url="https://api.openai.com/v1",
        config={"timeout_seconds": 30},
        api_key="",
    )

    tested = service.test_admin_provider_connection("openai-main")
    synced = service.sync_admin_provider_connection_catalog("openai-main")
    models = service.list_admin_models()

    assert tested is not None
    assert tested["test_result"]["ok"] is True
    assert tested["test_result"]["models_total"] == 3
    assert len(tested["test_result"]["inspected_models"]) == 3

    assert synced is not None
    assert synced["sync_result"]["ok"] is True
    assert synced["sync_result"]["models_total"] == 3
    assert synced["sync_result"]["added_total"] == 3
    assert synced["sync_result"]["updated_total"] == 0
    assert synced["sync_result"]["removed_total"] == 0
    assert len(synced["sync_result"]["inspected_models"]) == 3

    assert models["total"] == 3
    assert {item["provider_id"] for item in models["items"]} == {"openai-main"}
    assert all(item["model_id"].startswith("openai-main/") for item in models["items"])

    promoted = service.promote_admin_provider_connection_execution_revision("openai-main")
    assert promoted is not None
    assert promoted["promote_result"]["ok"] is True
    assert (
        promoted["connection"]["active_execution_revision"]
        == promoted["connection"]["last_sync_revision"]
    )
    assert promoted["connection"]["execution_release_test_state"] == "passed"
    assert promoted["connection"]["execution_release_smoke_state"] == "passed"
    assert (
        promoted["connection"]["last_release_smoke_revision"]
        == promoted["connection"]["last_sync_revision"]
    )
    assert promoted["connection"]["last_release_preflight_ok_at"]

    dispose_engine(database_url)


def test_provider_connection_sync_reports_added_updated_and_removed_counts(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = CatalogService(database_url, settings=_build_settings(database_url))
    service.upsert_admin_provider_connection(
        connection_id="openai-main",
        provider_type="openai",
        source_role="execution_source",
        display_name="OpenAI Main",
        enabled=True,
        base_url="https://api.openai.com/v1",
        config={"timeout_seconds": 30},
        api_key="",
    )

    service.test_admin_provider_connection("openai-main")
    first_sync = service.sync_admin_provider_connection_catalog("openai-main")
    second_sync = service.sync_admin_provider_connection_catalog("openai-main")

    assert first_sync is not None
    assert second_sync is not None
    assert first_sync["sync_result"]["added_total"] == 3
    assert first_sync["sync_result"]["updated_total"] == 0
    assert first_sync["sync_result"]["removed_total"] == 0
    assert second_sync["sync_result"]["added_total"] == 0
    assert second_sync["sync_result"]["updated_total"] == 3
    assert second_sync["sync_result"]["removed_total"] == 0

    connection = service.get_admin_provider_connection("openai-main")
    assert connection is not None
    assert connection["last_sync_models_total"] == 3
    assert connection["last_sync_revision"]
    assert connection["candidate_execution_revision"] == connection["last_sync_revision"]
    assert connection["active_execution_revision"] == ""

    promoted = service.promote_admin_provider_connection_execution_revision("openai-main")
    assert promoted is not None
    assert (
        promoted["connection"]["active_execution_revision"]
        == promoted["connection"]["last_sync_revision"]
    )
    assert promoted["connection"]["execution_release_state"] == "active"

    dispose_engine(database_url)


def test_provider_connection_promote_requires_green_test_and_smoke_evidence(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = CatalogService(database_url, settings=_build_settings(database_url))
    service.upsert_admin_provider_connection(
        connection_id="openai-main",
        provider_type="openai",
        source_role="execution_source",
        display_name="OpenAI Main",
        enabled=True,
        base_url="https://api.openai.com/v1",
        config={"timeout_seconds": 30},
        api_key="",
    )

    service.sync_admin_provider_connection_catalog("openai-main")

    try:
        service.promote_admin_provider_connection_execution_revision("openai-main")
    except ValueError as error:
        assert str(error) == "provider connection must pass test before promote"
    else:
        raise AssertionError("expected promote to require prior test evidence")

    dispose_engine(database_url)


def test_provider_connection_promote_requires_green_release_preflight(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = Settings(
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        admin_session_secret="x" * 32,
        provider_connection_secret="",
    )
    service = CatalogService(database_url, settings=settings)
    service.upsert_admin_provider_connection(
        connection_id="openai-main",
        provider_type="openai",
        source_role="execution_source",
        display_name="OpenAI Main",
        enabled=True,
        base_url="https://api.openai.com/v1",
        config={"timeout_seconds": 30},
        api_key="",
    )
    service.test_admin_provider_connection("openai-main")
    service.sync_admin_provider_connection_catalog("openai-main")

    try:
        service.promote_admin_provider_connection_execution_revision("openai-main")
    except ValueError as error:
        assert str(error).startswith(
            "provider connection promote blocked by release preflight:"
        )
        assert "provider_connection_secret_present" in str(error)
    else:
        raise AssertionError("expected promote to require green release preflight")

    dispose_engine(database_url)


def test_enabled_provider_connection_is_available_to_runtime_provider_registry(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _build_settings(database_url)
    service = CatalogService(database_url, settings=settings)
    service.upsert_admin_provider_connection(
        connection_id="openai-main",
        provider_type="openai",
        source_role="execution_source",
        display_name="OpenAI Main",
        enabled=True,
        base_url="https://api.openai.com/v1",
        config={"timeout_seconds": 30},
        api_key="",
    )
    service.sync_admin_provider_connection_catalog("openai-main")

    providers = build_provider_adapters(
        settings,
        include_enabled_connections=True,
    )

    assert "openai-main" in providers
    assert getattr(providers["openai-main"], "provider_id", "") == "openai-main"

    dispose_engine(database_url)


def test_execution_provider_registry_ignores_env_providers_in_production_like_runtime(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = CatalogService(database_url, settings=_build_settings(database_url))
    service.upsert_admin_provider_connection(
        connection_id="openai-main",
        provider_type="openai",
        source_role="execution_source",
        display_name="OpenAI Main",
        enabled=True,
        base_url="https://api.openai.com/v1",
        config={"timeout_seconds": 30},
        api_key="",
    )
    service.test_admin_provider_connection("openai-main")
    service.sync_admin_provider_connection_catalog("openai-main")

    settings = _build_production_settings(database_url)
    providers = resolve_execution_provider_adapters(settings)

    assert "openai" not in providers
    assert "openai-main" not in providers

    promoted = service.promote_admin_provider_connection_execution_revision("openai-main")
    assert promoted is not None

    promoted_providers = resolve_execution_provider_adapters(settings)
    assert "openai-main" in promoted_providers

    dispose_engine(database_url)


def test_execution_provider_registry_rejects_non_cloud_local_connections_in_production(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _build_production_settings(database_url)

    with get_session(database_url) as session:
        session.add(
            ProviderConnection(
                connection_id="legacy-main",
                provider_type="openai",
                source_role="execution_source",
                display_name="Legacy Main",
                enabled=True,
                base_url="https://api.openai.com/v1",
                secret_ciphertext="ciphertext",
                metadata_json={
                    "credential_origin": "plugin_local",
                },
            )
        )
        session.commit()

    providers = resolve_execution_provider_adapters(settings)

    assert "legacy-main" not in providers

    dispose_engine(database_url)
