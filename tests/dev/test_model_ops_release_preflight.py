from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.core.db import dispose_engine, init_schema, get_session
from app.core.models import CatalogModel, CatalogModelAnnotation, CatalogProvider, CatalogRevision, ProviderConnection
from app.dev.model_ops_release_preflight import evaluate_model_admin_release_preflight


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'model-ops-preflight.sqlite3'}"


def _base_settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="production",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token="i" * 32,
        admin_bootstrap_token="b" * 32,
        admin_session_secret="o" * 32,
        provider_connection_secret="p" * 32,
        portal_public_base_url="https://portal.example.com",
        portal_jwt_secret="j" * 32,
        portal_email_smtp_host="smtp.example.com",
        portal_email_from_email="noreply@example.com",
    )


def test_release_preflight_reports_blockers_for_dev_flags_and_sample_profiles(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = Settings(
        _env_file=None,
        environment="development",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        admin_session_secret="o" * 32,
        provider_connection_secret="p" * 32,
        allow_dev_admin_internal_token_fallback=True,
        openai_sample_catalog_profile="recognition_sample",
        openai_recognition_review_sample_catalog_profile="recognition_review_240",
    )

    report = evaluate_model_admin_release_preflight(settings)
    codes = {item["code"]: item["status"] for item in report["checks"]}

    assert report["ok"] is False
    assert codes["openai_sample_catalog_profile_disabled"] == "blocker"
    assert codes["recognition_review_sample_profile_disabled"] == "blocker"
    assert codes["dev_internal_token_fallback_disabled"] == "blocker"
    assert codes["feature_flag_overrides_parseable"] == "ok"

    dispose_engine(database_url)


def test_release_preflight_blocks_invalid_feature_flag_json(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _base_settings(database_url).model_copy(
        update={
            "feature_flags_json": '{"portal.billing.readonly.enabled":"maybe"}',
        }
    )

    report = evaluate_model_admin_release_preflight(settings)
    codes = {item["code"]: item["status"] for item in report["checks"]}

    assert report["ok"] is False
    assert codes["feature_flag_overrides_parseable"] == "blocker"

    dispose_engine(database_url)


def test_release_preflight_accepts_realish_catalog_without_sample_rows(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _base_settings(database_url)

    with get_session(database_url) as session:
        session.add(
            CatalogProvider(
                provider_id="openai-main",
                display_name="OpenAI Main",
                adapter_type="openai",
                status="active",
            )
        )
        session.add(
            CatalogRevision(
                revision="catalog-20260331090000000000",
                provider_id="openai-main",
                source="admin_provider_connection_sync",
                notes="openai-main",
            )
        )
        session.add(
            ProviderConnection(
                connection_id="openai-main",
                provider_type="openai",
                display_name="OpenAI Main",
                enabled=True,
                base_url="https://api.openai.com/v1",
                secret_ciphertext="ciphertext",
                status="ok",
                metadata_json={
                    "source": "admin_provider_connections_console_v1",
                    "credential_origin": "cloud_local",
                    "credential_scope": "cloud_only",
                },
            )
        )
        session.add(
            CatalogModel(
                model_id="openai-main/gpt-4.1-mini",
                provider_id="openai-main",
                family="gpt-4.1",
                feature="text",
                status="available",
                context_window=128000,
                price_input=0.0,
                price_output=0.0,
                is_deprecated=False,
                fallback_candidate=True,
                revision="catalog-20260331090000000000",
                raw_json={"upstream": "provider_connection"},
            )
        )
        session.add(
            CatalogModelAnnotation(
                model_id="openai-main/gpt-4.1-mini",
                provider_id="openai-main",
                recommended=True,
                cost_tier="balanced",
                visibility="default",
                badges_json=["recommended"],
                operator_notes="Launch curated",
                metadata_json={},
            )
        )
        session.commit()

    report = evaluate_model_admin_release_preflight(settings)
    codes = {item["code"]: item["status"] for item in report["checks"]}

    assert report["ok"] is True
    assert codes["provider_source_present"] == "ok"
    assert codes["provider_connection_credentials_cloud_local"] == "ok"
    assert codes["hosted_catalog_non_empty"] == "ok"
    assert codes["hosted_catalog_not_sample_seeded"] == "ok"
    assert report["counts"]["hosted_models_total"] == 1
    assert report["counts"]["recommended_models_total"] == 1

    dispose_engine(database_url)


def test_release_preflight_flags_sample_seeded_hosted_rows(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _base_settings(database_url)

    with get_session(database_url) as session:
        session.add(
            CatalogProvider(
                provider_id="openai",
                display_name="OpenAI Compatible",
                adapter_type="openai",
                status="active",
            )
        )
        session.add(
            CatalogRevision(
                revision="catalog-20260331090100000000",
                provider_id="openai",
                source="provider_refresh",
                notes="sample",
            )
        )
        session.add(
            CatalogModel(
                model_id="flux-dev",
                provider_id="openai",
                family="flux",
                feature="image_generation",
                status="available",
                context_window=0,
                price_input=0.0,
                price_output=0.0,
                is_deprecated=False,
                fallback_candidate=False,
                revision="catalog-20260331090100000000",
                raw_json={"catalog_profile": "recognition_review_240"},
            )
        )
        session.commit()

    report = evaluate_model_admin_release_preflight(settings)
    codes = {item["code"]: item["status"] for item in report["checks"]}

    assert report["ok"] is False
    assert codes["hosted_catalog_not_sample_seeded"] == "blocker"
    assert report["counts"]["sample_seeded_hosted_models_total"] == 1

    dispose_engine(database_url)


def test_release_preflight_flags_non_cloud_local_provider_credentials(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _base_settings(database_url)

    with get_session(database_url) as session:
        session.add(
            ProviderConnection(
                connection_id="deepseek-main",
                provider_type="openai",
                display_name="DeepSeek Main",
                enabled=True,
                base_url="https://api.deepseek.com/v1",
                secret_ciphertext="ciphertext",
                status="ok",
                metadata_json={
                    "source": "manual_backfill",
                    "credential_origin": "plugin_local",
                },
            )
        )
        session.commit()

    report = evaluate_model_admin_release_preflight(settings)
    codes = {item["code"]: item["status"] for item in report["checks"]}

    assert report["ok"] is False
    assert codes["provider_connection_credentials_cloud_local"] == "blocker"

    dispose_engine(database_url)
