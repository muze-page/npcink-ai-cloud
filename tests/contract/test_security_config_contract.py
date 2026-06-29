from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_require_long_security_tokens() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(
            environment="test",
            database_url="sqlite+pysqlite:///:memory:",
            redis_url="redis://localhost:6379/0",
            internal_auth_token="too-short",
        )

    assert "internal_auth_token must be at least 32 bytes long" in str(error.value)


def test_settings_require_admin_session_secret_outside_dev_and_test() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(
            environment="production",
            database_url="sqlite+pysqlite:///:memory:",
            redis_url="redis://localhost:6379/0",
            internal_auth_token="npcink-cloud-internal-prod-token-32b",
            admin_session_secret="",
        )

    assert "admin_session_secret is required outside development/test environments" in str(
        error.value
    )


def test_settings_accept_hardened_production_auth_settings() -> None:
    settings = Settings(
        environment="production",
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        internal_auth_token="npcink-cloud-internal-prod-token-32b",
        admin_bootstrap_token="npcink-cloud-admin-bootstrap-prod-token",
        admin_session_secret="npcink-cloud-ops-session-secret-prod-32b",
        portal_jwt_secret="npcink-cloud-portal-jwt-secret-prod-32b",
        browser_origin_allowlist="https://cloud.example.com",
        trusted_host_allowlist="cloud.example.com",
    )

    assert settings.environment == "production"
    assert settings.admin_session_secret == "npcink-cloud-ops-session-secret-prod-32b"
    assert settings.admin_bootstrap_token == "npcink-cloud-admin-bootstrap-prod-token"


def test_settings_reject_dev_fallback_flag_outside_dev_and_test() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(
            environment="production",
            database_url="sqlite+pysqlite:///:memory:",
            redis_url="redis://localhost:6379/0",
            internal_auth_token="npcink-cloud-internal-prod-token-32b",
            admin_session_secret="npcink-cloud-ops-session-secret-prod-32b",
            allow_dev_admin_internal_token_fallback=True,
        )

    assert "allow_dev_admin_internal_token_fallback is only allowed in development/test" in str(
        error.value
    )


def test_settings_reject_openai_sample_catalog_profile_outside_dev_and_test() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(
            environment="production",
            database_url="sqlite+pysqlite:///:memory:",
            redis_url="redis://localhost:6379/0",
            internal_auth_token="npcink-cloud-internal-prod-token-32b",
            admin_session_secret="npcink-cloud-ops-session-secret-prod-32b",
            portal_jwt_secret="npcink-cloud-portal-jwt-secret-prod-32b",
            browser_origin_allowlist="https://cloud.example.com",
            trusted_host_allowlist="cloud.example.com",
            openai_sample_catalog_profile="legacy_dev_sample",
        )

    assert "openai_sample_catalog_profile is only allowed in development/test" in str(error.value)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"internal_auth_token": ""},
            "internal_auth_token is required outside development/test environments",
        ),
        (
            {"admin_bootstrap_token": ""},
            "admin_bootstrap_token is required outside development/test environments",
        ),
        (
            {
                "admin_bootstrap_token": "npcink-cloud-internal-prod-token-32b",
            },
            "admin_bootstrap_token must differ from internal_auth_token outside development/test environments",
        ),
        (
            {"portal_jwt_secret": ""},
            "portal_jwt_secret is required outside development/test environments",
        ),
        (
            {"browser_origin_allowlist": ""},
            "browser_origin_allowlist is required outside development/test environments",
        ),
        (
            {"trusted_host_allowlist": ""},
            "trusted_host_allowlist is required outside development/test environments",
        ),
    ],
)
def test_settings_require_production_portal_and_secret_fields(
    overrides: dict[str, str],
    message: str,
) -> None:
    payload = {
        "environment": "production",
        "database_url": "sqlite+pysqlite:///:memory:",
        "redis_url": "redis://localhost:6379/0",
        "internal_auth_token": "npcink-cloud-internal-prod-token-32b",
        "admin_bootstrap_token": "npcink-cloud-admin-bootstrap-prod-token",
        "admin_session_secret": "npcink-cloud-ops-session-secret-prod-32b",
        "portal_jwt_secret": "npcink-cloud-portal-jwt-secret-prod-32b",
        "browser_origin_allowlist": "https://cloud.example.com",
        "trusted_host_allowlist": "cloud.example.com",
    }
    payload.update(overrides)
    with pytest.raises(ValidationError) as error:
        Settings(**payload)

    assert message in str(error.value)
