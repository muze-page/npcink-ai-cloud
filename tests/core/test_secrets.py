from __future__ import annotations

import base64
import hashlib

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.core.config import Settings
from app.core.secrets import (
    decrypt_addon_connection_payload,
    decrypt_portal_idempotency_response,
    decrypt_provider_connection_secret,
    decrypt_runtime_data_plaintext,
    decrypt_runtime_execution_input,
    decrypt_runtime_terminal_callback_secret,
    decrypt_site_api_signing_secret,
    encrypt_addon_connection_payload,
    encrypt_portal_idempotency_response,
    encrypt_provider_connection_secret,
    encrypt_runtime_data_plaintext,
    encrypt_runtime_execution_input,
    encrypt_runtime_terminal_callback_secret,
    encrypt_site_api_signing_secret,
)


def _settings(
    *,
    service_secret: str = "service-settings-stable-secret-32b",
    session_suffix: str = "original",
    runtime_secret: str = "runtime-data-stable-secret-at-least-32b",
    runtime_key_id: str = "runtime-key-2026-07",
) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        service_settings_secret=service_secret,
        admin_session_secret=f"admin-session-{session_suffix}-secret-32b",
        portal_jwt_secret=f"portal-session-{session_suffix}-secret-32b",
        internal_auth_token=f"internal-auth-{session_suffix}-secret-32b",
        runtime_data_encryption_secret=runtime_secret,
        runtime_data_encryption_key_id=runtime_key_id,
    )


def test_provider_connection_secret_uses_only_service_settings_secret() -> None:
    original = _settings(
        service_secret="service-settings-stable-secret-32b",
        session_suffix="original",
    )
    ciphertext = encrypt_provider_connection_secret("provider-key", settings=original)

    rotated_sessions = _settings(
        service_secret="service-settings-stable-secret-32b",
        session_suffix="rotated",
    )
    assert (
        decrypt_provider_connection_secret(ciphertext, settings=rotated_sessions) == "provider-key"
    )

    wrong_service_secret = _settings(
        service_secret="different-service-settings-key-32b",
        session_suffix="original",
    )
    with pytest.raises(RuntimeError, match="could not be decrypted"):
        decrypt_provider_connection_secret(ciphertext, settings=wrong_service_secret)


def test_all_runtime_data_ciphertexts_use_the_active_envelope_and_root() -> None:
    settings = _settings()
    ciphertexts = {
        "callback": encrypt_runtime_terminal_callback_secret("callback-secret", settings=settings),
        "site_api": encrypt_site_api_signing_secret("site-api-secret", settings=settings),
        "addon": encrypt_addon_connection_payload({"key": "value"}, settings=settings),
        "idempotency": encrypt_portal_idempotency_response(b'{"ok":true}', settings=settings),
        "run_input": encrypt_runtime_execution_input({"prompt": "hello"}, settings=settings),
    }

    assert all(
        ciphertext.startswith("rde.v1.runtime-key-2026-07.") for ciphertext in ciphertexts.values()
    )
    assert (
        decrypt_runtime_terminal_callback_secret(ciphertexts["callback"], settings=settings)
        == "callback-secret"
    )
    assert decrypt_site_api_signing_secret(ciphertexts["site_api"], settings=settings) == (
        "site-api-secret"
    )
    assert decrypt_addon_connection_payload(ciphertexts["addon"], settings=settings) == {
        "key": "value"
    }
    assert (
        decrypt_portal_idempotency_response(ciphertexts["idempotency"], settings=settings)
        == b'{"ok":true}'
    )
    assert decrypt_runtime_execution_input(ciphertexts["run_input"], settings=settings) == {
        "prompt": "hello"
    }


def test_runtime_data_ciphertext_isolated_from_session_and_internal_secret_rotation() -> None:
    original = _settings(session_suffix="original")
    ciphertext = encrypt_site_api_signing_secret("site-api-secret", settings=original)

    rotated_unrelated_domains = _settings(session_suffix="rotated")
    assert (
        decrypt_site_api_signing_secret(ciphertext, settings=rotated_unrelated_domains)
        == "site-api-secret"
    )


@pytest.mark.parametrize(
    ("settings", "match"),
    [
        (
            _settings(runtime_secret="different-runtime-root-secret-32b"),
            "could not be decrypted",
        ),
        (
            _settings(runtime_key_id="different-key-id"),
            "could not be decrypted",
        ),
    ],
)
def test_runtime_data_ciphertext_fails_closed_for_wrong_active_key(
    settings: Settings,
    match: str,
) -> None:
    ciphertext = encrypt_site_api_signing_secret("site-api-secret", settings=_settings())
    with pytest.raises(RuntimeError, match=match):
        decrypt_site_api_signing_secret(ciphertext, settings=settings)


@pytest.mark.parametrize(
    "ciphertext",
    [
        "not-an-envelope",
        "rde.v2.runtime-key-2026-07.invalid",
        "rde.v1.unknown-key.invalid",
        "rde.v1.runtime-key-2026-07.invalid",
    ],
)
def test_runtime_data_ciphertext_fails_closed_for_invalid_envelope(ciphertext: str) -> None:
    with pytest.raises(RuntimeError, match="could not be decrypted"):
        decrypt_site_api_signing_secret(ciphertext, settings=_settings())


def test_runtime_data_ciphertext_rejects_legacy_raw_fernet() -> None:
    legacy_root = "admin-session-original-secret-32b"
    derived_key = hashlib.sha256(f"site_api_key_signing_secret:{legacy_root}".encode()).digest()
    legacy_ciphertext = (
        Fernet(base64.urlsafe_b64encode(derived_key)).encrypt(b"site-api-secret").decode("utf-8")
    )

    with pytest.raises(RuntimeError, match="could not be decrypted"):
        decrypt_site_api_signing_secret(legacy_ciphertext, settings=_settings())


def test_runtime_data_encryption_does_not_fallback_when_runtime_domain_is_missing() -> None:
    settings = _settings(runtime_secret="", runtime_key_id="runtime-key-2026-07")
    with pytest.raises(RuntimeError, match="runtime data encryption secret is not configured"):
        encrypt_site_api_signing_secret("site-api-secret", settings=settings)

    settings = _settings(runtime_key_id="")
    with pytest.raises(RuntimeError, match="runtime data encryption key id is not configured"):
        encrypt_site_api_signing_secret("site-api-secret", settings=settings)


def test_runtime_data_ciphertext_is_bound_to_purpose() -> None:
    settings = _settings()
    ciphertext = encrypt_runtime_data_plaintext(
        b"secret",
        purpose="site_api_key_signing_secret",
        settings=settings,
    )
    with pytest.raises(RuntimeError, match="could not be decrypted"):
        decrypt_runtime_data_plaintext(
            ciphertext,
            purpose="runtime_execution_input",
            settings=settings,
        )


def test_production_requires_runtime_data_secret_and_key_id() -> None:
    common = {
        "_env_file": None,
        "environment": "production",
        "internal_auth_token": "internal-production-secret-value-32b",
        "admin_bootstrap_token": "bootstrap-production-secret-value-32b",
        "admin_session_secret": "admin-production-secret-value-32bytes",
        "service_settings_secret": "settings-production-secret-value-32b",
        "portal_jwt_secret": "portal-production-secret-value-32bytes",
        "browser_origin_allowlist": "https://cloud.example.com",
        "trusted_host_allowlist": "cloud.example.com",
    }
    with pytest.raises(ValidationError, match="runtime_data_encryption_secret is required"):
        Settings(
            **common,
            runtime_data_encryption_secret="",
            runtime_data_encryption_key_id="",
        )

    with pytest.raises(ValidationError, match="runtime_data_encryption_key_id is required"):
        Settings(
            **common,
            runtime_data_encryption_secret="runtime-production-secret-value-32b",
            runtime_data_encryption_key_id="",
        )


def test_production_rejects_shared_security_domain_secrets() -> None:
    shared = "shared-production-secret-value-at-least-32b"
    with pytest.raises(ValidationError, match="must differ from"):
        Settings(
            _env_file=None,
            environment="production",
            internal_auth_token="internal-production-secret-value-32b",
            admin_bootstrap_token="bootstrap-production-secret-value-32b",
            admin_session_secret=shared,
            service_settings_secret="settings-production-secret-value-32b",
            portal_jwt_secret="portal-production-secret-value-32bytes",
            runtime_data_encryption_secret=shared,
            runtime_data_encryption_key_id="runtime-key-2026-07",
            browser_origin_allowlist="https://cloud.example.com",
            trusted_host_allowlist="cloud.example.com",
        )
