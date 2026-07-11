from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.secrets import (
    decrypt_provider_connection_secret,
    encrypt_provider_connection_secret,
)


def _settings(*, service_secret: str, session_suffix: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        service_settings_secret=service_secret,
        admin_session_secret=f"admin-session-{session_suffix}-secret-32b",
        portal_jwt_secret=f"portal-session-{session_suffix}-secret-32b",
        internal_auth_token=f"internal-auth-{session_suffix}-secret-32b",
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
        decrypt_provider_connection_secret(ciphertext, settings=rotated_sessions)
        == "provider-key"
    )

    wrong_service_secret = _settings(
        service_secret="different-service-settings-key-32b",
        session_suffix="original",
    )
    with pytest.raises(RuntimeError, match="could not be decrypted"):
        decrypt_provider_connection_secret(ciphertext, settings=wrong_service_secret)
