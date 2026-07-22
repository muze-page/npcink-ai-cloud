from __future__ import annotations

import base64

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.core.config import Settings
from app.core.secrets import (
    _derive_fernet_key,
    decrypt_addon_connection_payload,
    decrypt_portal_idempotency_response,
    decrypt_provider_connection_secret,
    decrypt_runtime_data_plaintext,
    decrypt_runtime_execution_input,
    decrypt_runtime_terminal_callback_secret,
    decrypt_service_setting_secret,
    decrypt_site_api_signing_secret,
    encrypt_addon_connection_payload,
    encrypt_portal_idempotency_response,
    encrypt_provider_connection_secret,
    encrypt_runtime_data_plaintext,
    encrypt_runtime_execution_input,
    encrypt_runtime_terminal_callback_secret,
    encrypt_service_setting_secret,
    encrypt_site_api_signing_secret,
    service_secret_envelope_key_id,
)

SERVICE_ROOT = base64.urlsafe_b64encode(b"s" * 32).decode("ascii")
OTHER_SERVICE_ROOT = base64.urlsafe_b64encode(b"t" * 32).decode("ascii")
RUNTIME_ROOT = base64.urlsafe_b64encode(b"r" * 32).decode("ascii")
OTHER_RUNTIME_ROOT = base64.urlsafe_b64encode(b"q" * 32).decode("ascii")


def _settings(
    *,
    service_secret: str = SERVICE_ROOT,
    service_key_id: str = "service-key-2026-07",
    session_suffix: str = "original",
    runtime_secret: str = RUNTIME_ROOT,
    runtime_key_id: str = "runtime-key-2026-07",
) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        service_settings_secret=service_secret,
        service_settings_encryption_key_id=service_key_id,
        admin_session_secret=f"admin-session-{session_suffix}-secret-32b",
        portal_jwt_secret=f"portal-session-{session_suffix}-secret-32b",
        internal_auth_token=f"internal-auth-{session_suffix}-secret-32b",
        runtime_data_encryption_secret=runtime_secret,
        runtime_data_encryption_key_id=runtime_key_id,
    )


def test_provider_connection_secret_uses_only_service_settings_secret() -> None:
    original = _settings(
        service_secret=SERVICE_ROOT,
        session_suffix="original",
    )
    ciphertext = encrypt_provider_connection_secret("provider-key", settings=original)
    assert ciphertext.startswith("sse.v1.service-key-2026-07.")
    assert service_secret_envelope_key_id(ciphertext) == "service-key-2026-07"

    rotated_sessions = _settings(
        service_secret=SERVICE_ROOT,
        session_suffix="rotated",
    )
    assert (
        decrypt_provider_connection_secret(ciphertext, settings=rotated_sessions) == "provider-key"
    )

    wrong_service_secret = _settings(
        service_secret=OTHER_SERVICE_ROOT,
        session_suffix="original",
    )
    with pytest.raises(RuntimeError, match="could not be decrypted"):
        decrypt_provider_connection_secret(ciphertext, settings=wrong_service_secret)

    wrong_key_id = _settings(service_key_id="service-key-2026-08")
    with pytest.raises(RuntimeError, match="could not be decrypted"):
        decrypt_provider_connection_secret(ciphertext, settings=wrong_key_id)


def test_service_setting_secret_uses_versioned_service_envelope_and_purpose_isolation() -> None:
    settings = _settings()
    ciphertext = encrypt_service_setting_secret("smtp-password", settings=settings)

    assert ciphertext.startswith("sse.v1.service-key-2026-07.")
    assert decrypt_service_setting_secret(ciphertext, settings=settings) == "smtp-password"
    with pytest.raises(RuntimeError, match="provider connection secret could not be decrypted"):
        decrypt_provider_connection_secret(ciphertext, settings=settings)


@pytest.mark.parametrize(
    "ciphertext",
    [
        "raw-fernet-token",
        "unknown.v1.service-key-2026-07.invalid",
        "sse.v2.service-key-2026-07.invalid",
        "sse.v1.unknown-key.invalid",
        "sse.v1.service-key-2026-07.invalid",
    ],
)
def test_service_secret_ciphertext_fails_closed_for_invalid_envelope(ciphertext: str) -> None:
    with pytest.raises(RuntimeError, match="could not be decrypted"):
        decrypt_service_setting_secret(ciphertext, settings=_settings())


def test_service_secret_ciphertext_rejects_legacy_raw_fernet() -> None:
    # Precomputed from the retired purpose-bound SHA contract; do not rebuild
    # legacy keys from a root secret outside the one-time maintenance reader.
    derived_key = bytes.fromhex(
        "364efa77fda7e4a5831e15b043fec4264ec7776ea7764ae13eb5d78ada80aac2"
    )
    legacy_ciphertext = (
        Fernet(base64.urlsafe_b64encode(derived_key)).encrypt(b"smtp-password").decode("utf-8")
    )

    assert service_secret_envelope_key_id(legacy_ciphertext) is None
    with pytest.raises(RuntimeError, match="could not be decrypted"):
        decrypt_service_setting_secret(legacy_ciphertext, settings=_settings())


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
            _settings(runtime_secret=OTHER_RUNTIME_ROOT),
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


def test_runtime_data_ciphertext_rejects_legacy_direct_sha_fernet() -> None:
    # A static known answer keeps the test independent without adding a second
    # root-secret SHA derivation sink for CodeQL to flag.
    derived_key = bytes.fromhex(
        "38970b856278427688fc2f45230f1685ecc3fdb76fef8b56f0119a2a65a0f6c8"
    )
    legacy_ciphertext = (
        Fernet(base64.urlsafe_b64encode(derived_key)).encrypt(b"site-api-secret").decode("utf-8")
    )

    for ciphertext in (
        legacy_ciphertext,
        f"rde.v1.runtime-key-2026-07.{legacy_ciphertext}",
    ):
        with pytest.raises(RuntimeError, match="could not be decrypted"):
            decrypt_site_api_signing_secret(ciphertext, settings=_settings())


def test_runtime_data_encryption_does_not_fallback_when_runtime_domain_is_missing() -> None:
    settings = _settings(runtime_secret="", runtime_key_id="runtime-key-2026-07")
    with pytest.raises(RuntimeError, match="runtime data encryption secret is not configured"):
        encrypt_site_api_signing_secret("site-api-secret", settings=settings)

    settings = _settings(runtime_key_id="")
    with pytest.raises(RuntimeError, match="runtime data encryption key id is not configured"):
        encrypt_site_api_signing_secret("site-api-secret", settings=settings)


def test_service_secret_encryption_does_not_fallback_when_domain_is_missing() -> None:
    settings = _settings(service_secret="")
    with pytest.raises(RuntimeError, match="service setting secret is not configured"):
        encrypt_service_setting_secret("smtp-password", settings=settings)

    settings = _settings(service_key_id="")
    with pytest.raises(RuntimeError, match="service settings encryption key id is not configured"):
        encrypt_service_setting_secret("smtp-password", settings=settings)


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


def test_hkdf_sha256_derivation_has_a_stable_known_answer_and_domain_isolation() -> None:
    root = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")
    runtime_key = _derive_fernet_key(
        root,
        family="rde",
        version="v1",
        purpose="runtime_execution_input",
        key_id="runtime-key-2026-07",
    )

    assert runtime_key.hex() == "21ddb04d0b581858a1cbc3b1ae59223d5870d9c84048950441999fd1f9e7b650"
    assert runtime_key != _derive_fernet_key(
        root,
        family="rde",
        version="v1",
        purpose="site_api_key_signing_secret",
        key_id="runtime-key-2026-07",
    )
    assert runtime_key != _derive_fernet_key(
        root,
        family="rde",
        version="v1",
        purpose="runtime_execution_input",
        key_id="runtime-key-2026-08",
    )
    assert runtime_key != _derive_fernet_key(
        root,
        family="sse",
        version="v1",
        purpose="runtime_execution_input",
        key_id="runtime-key-2026-07",
    )


@pytest.mark.parametrize(
    "invalid_root",
    [
        "x" * 32,
        "!" * 44,
        base64.urlsafe_b64encode(b"r" * 31).decode("ascii"),
        RUNTIME_ROOT.rstrip("="),
        f" {RUNTIME_ROOT}",
    ],
)
def test_runtime_builder_rejects_noncanonical_or_wrong_length_root(invalid_root: str) -> None:
    with pytest.raises(RuntimeError, match="canonical URL-safe Base64"):
        encrypt_runtime_data_plaintext(
            b"secret",
            purpose="runtime_execution_input",
            settings=_settings(runtime_secret=invalid_root),
        )


def test_service_builder_rejects_noncanonical_root() -> None:
    with pytest.raises(RuntimeError, match="canonical URL-safe Base64"):
        encrypt_service_setting_secret(
            "secret",
            settings=_settings(service_secret="plain-service-root-that-is-long-enough"),
        )


def test_builders_reject_invalid_purpose_and_key_id() -> None:
    with pytest.raises(RuntimeError, match="encryption purpose is invalid"):
        encrypt_runtime_data_plaintext(b"secret", purpose="", settings=_settings())

    runtime_settings = _settings()
    runtime_settings.runtime_data_encryption_key_id = "invalid.key"
    with pytest.raises(RuntimeError, match="runtime data encryption key id is invalid"):
        encrypt_runtime_data_plaintext(
            b"secret",
            purpose="runtime_execution_input",
            settings=runtime_settings,
        )

    service_settings = _settings()
    service_settings.service_settings_encryption_key_id = " invalid-key"
    with pytest.raises(RuntimeError, match="service settings encryption key id is invalid"):
        encrypt_service_setting_secret("secret", settings=service_settings)


def test_production_requires_runtime_data_secret_and_key_id() -> None:
    common = {
        "_env_file": None,
        "environment": "production",
        "internal_auth_token": "internal-production-secret-value-32b",
        "admin_key_sha256": "a" * 64,
        "admin_session_secret": "admin-production-secret-value-32bytes",
        "service_settings_secret": SERVICE_ROOT,
        "service_settings_encryption_key_id": "service-key-2026-07",
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
            runtime_data_encryption_secret=RUNTIME_ROOT,
            runtime_data_encryption_key_id="",
        )


def test_production_rejects_shared_security_domain_secrets() -> None:
    shared = RUNTIME_ROOT
    with pytest.raises(ValidationError, match="must differ from"):
        Settings(
            _env_file=None,
            environment="production",
            internal_auth_token="internal-production-secret-value-32b",
            admin_key_sha256="a" * 64,
            admin_session_secret=shared,
            service_settings_secret=SERVICE_ROOT,
            service_settings_encryption_key_id="service-key-2026-07",
            portal_jwt_secret="portal-production-secret-value-32bytes",
            runtime_data_encryption_secret=shared,
            runtime_data_encryption_key_id="runtime-key-2026-07",
            browser_origin_allowlist="https://cloud.example.com",
            trusted_host_allowlist="cloud.example.com",
        )
