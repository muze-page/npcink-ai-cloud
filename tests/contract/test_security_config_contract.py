from __future__ import annotations

import base64
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

SERVICE_SETTINGS_ROOT = base64.urlsafe_b64encode(b"s" * 32).decode("ascii")
RUNTIME_DATA_ROOT = base64.urlsafe_b64encode(b"r" * 32).decode("ascii")


def _production_settings_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "_env_file": None,
        "environment": "production",
        "database_url": "sqlite+pysqlite:///:memory:",
        "redis_url": "redis://localhost:6379/0",
        "internal_auth_token": "npcink-cloud-internal-prod-token-32b",
        "admin_key_sha256": "a" * 64,
        "admin_session_secret": "npcink-cloud-ops-session-secret-prod-32b",
        "service_settings_secret": SERVICE_SETTINGS_ROOT,
        "service_settings_encryption_key_id": "service-settings-key-2026-07",
        "runtime_data_encryption_secret": RUNTIME_DATA_ROOT,
        "runtime_data_encryption_key_id": "runtime-data-key-2026-07",
        "portal_jwt_secret": "npcink-cloud-portal-jwt-secret-prod-32b",
        "browser_origin_allowlist": "https://cloud.example.com",
        "trusted_host_allowlist": "cloud.example.com",
    }
    payload.update(overrides)
    return payload


def test_portal_jwt_algorithm_is_fixed_and_not_configurable() -> None:
    env_example = (Path(__file__).resolve().parents[2] / ".env.example").read_text()

    assert "portal_jwt_algorithm" not in Settings.model_fields
    assert "NPCINK_CLOUD_PORTAL_JWT_ALGORITHM" not in env_example


@pytest.mark.parametrize("max_body_bytes", [0, 51 * 1024 * 1024 + 1])
def test_media_upload_max_body_bytes_stays_within_proxy_contract(
    max_body_bytes: int,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            environment="test",
            database_url="sqlite+pysqlite:///:memory:",
            redis_url="redis://localhost:6379/0",
            media_upload_max_body_bytes=max_body_bytes,
        )


def test_settings_require_long_security_tokens() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(
            _env_file=None,
            environment="test",
            database_url="sqlite+pysqlite:///:memory:",
            redis_url="redis://localhost:6379/0",
            internal_auth_token="too-short",
        )

    assert "internal_auth_token must be at least 32 bytes long" in str(error.value)


def test_settings_require_long_service_settings_secret_when_configured() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(
            _env_file=None,
            environment="test",
            database_url="sqlite+pysqlite:///:memory:",
            redis_url="redis://localhost:6379/0",
            service_settings_secret="too-short",
        )

    assert "service_settings_secret must be at least 32 bytes long" in str(error.value)


def test_settings_require_admin_session_secret_outside_dev_and_test() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(**_production_settings_payload(admin_session_secret=""))

    assert "admin_session_secret is required outside development/test environments" in str(
        error.value
    )


def test_settings_accept_hardened_production_auth_settings() -> None:
    settings = Settings(**_production_settings_payload())

    assert settings.environment == "production"
    assert settings.admin_session_secret == "npcink-cloud-ops-session-secret-prod-32b"
    assert settings.admin_key_sha256 == "a" * 64
    assert settings.admin_principal_id == "platform:internal_root"
    assert settings.service_settings_secret == SERVICE_SETTINGS_ROOT
    assert settings.service_settings_encryption_key_id == "service-settings-key-2026-07"
    assert settings.runtime_data_encryption_secret == RUNTIME_DATA_ROOT
    assert settings.runtime_data_encryption_key_id == "runtime-data-key-2026-07"
    assert settings.portal_jwt_issuer == "npcink-ai-cloud"
    assert settings.portal_jwt_audience == "npcink-ai-cloud-portal"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"portal_jwt_issuer": ""},
            "portal_jwt_issuer must not be blank",
        ),
        (
            {"portal_jwt_audience": "   "},
            "portal_jwt_audience must not be blank",
        ),
    ],
)
def test_settings_reject_blank_portal_token_identity(
    overrides: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(ValidationError) as error:
        Settings(**_production_settings_payload(**overrides))

    assert message in str(error.value)


def test_settings_reject_dev_fallback_flag_outside_dev_and_test() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(
            **_production_settings_payload(
                allow_dev_admin_internal_token_fallback=True,
            )
        )

    assert "allow_dev_admin_internal_token_fallback is only allowed in development/test" in str(
        error.value
    )


def test_settings_reject_openai_sample_catalog_profile_outside_dev_and_test() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(
            **_production_settings_payload(
                openai_sample_catalog_profile="legacy_dev_sample",
            )
        )

    assert "openai_sample_catalog_profile is only allowed in development/test" in str(error.value)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"service_settings_secret": ""},
            "service_settings_secret is required outside development/test environments",
        ),
        (
            {"service_settings_encryption_key_id": ""},
            "service_settings_encryption_key_id is required outside development/test environments",
        ),
        (
            {"runtime_data_encryption_secret": ""},
            "runtime_data_encryption_secret is required outside development/test environments",
        ),
        (
            {"runtime_data_encryption_key_id": ""},
            "runtime_data_encryption_key_id is required outside development/test environments",
        ),
        (
            {"internal_auth_token": ""},
            "internal_auth_token is required outside development/test environments",
        ),
        (
            {"admin_key_sha256": ""},
            "admin_key_sha256 is required outside development/test environments",
        ),
        (
            {
                "admin_key_sha256": "A" * 64,
            },
            "admin_key_sha256 must be a lowercase SHA-256 digest",
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
    with pytest.raises(ValidationError) as error:
        Settings(**_production_settings_payload(**overrides))

    assert message in str(error.value)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("service_settings_secret", "x" * 32),
        ("runtime_data_encryption_secret", "x" * 32),
        ("service_settings_secret", "!" * 44),
        ("runtime_data_encryption_secret", "!" * 44),
        (
            "service_settings_secret",
            base64.urlsafe_b64encode(b"s" * 31).decode("ascii"),
        ),
        (
            "runtime_data_encryption_secret",
            base64.urlsafe_b64encode(b"r" * 33).decode("ascii"),
        ),
        ("service_settings_secret", SERVICE_SETTINGS_ROOT.rstrip("=")),
        ("runtime_data_encryption_secret", f" {RUNTIME_DATA_ROOT}"),
    ],
)
def test_production_rejects_noncanonical_or_wrong_length_encryption_roots(
    field_name: str,
    value: str,
) -> None:
    with pytest.raises(ValidationError) as error:
        Settings(**_production_settings_payload(**{field_name: value}))

    assert f"{field_name} must be canonical URL-safe Base64" in str(error.value)


@pytest.mark.parametrize(
    "field_name",
    ["service_settings_encryption_key_id", "runtime_data_encryption_key_id"],
)
def test_settings_reject_illegal_encryption_key_ids(field_name: str) -> None:
    with pytest.raises(ValidationError) as error:
        Settings(**_production_settings_payload(**{field_name: "invalid.key"}))

    assert f"{field_name} must contain only letters" in str(error.value)
