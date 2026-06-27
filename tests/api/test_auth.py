"""Tests for cloud auth helpers (app.api.auth).

Tests core token lifecycle functions without requiring a full FastAPI request context.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.api.auth import (
    PortalBearerTokenError,
    build_portal_session_token,
    decode_portal_bearer_claims,
    decode_portal_bearer_token,
    decode_portal_session_cookie_claims,
    resolve_portal_login_code_ttl_seconds,
    resolve_portal_session_ttl_seconds,
)
from app.core.config import Settings


def _test_settings(**overrides: object) -> Settings:
    kwargs: dict[str, object] = {
        "_env_file": None,
        "project_name": "Auth Test",
        "environment": "test",
        "database_url": "sqlite+pysqlite:///:memory:",
        "portal_jwt_secret": "test-portal-jwt-secret-at-least-32-bytes-long",
        "portal_jwt_algorithm": "HS256",
    }
    kwargs.update(overrides)
    return Settings(**kwargs)


class TestBuildPortalSessionToken:
    def test_creates_valid_token_with_default_expiry(self) -> None:
        settings = _test_settings()
        token = build_portal_session_token(settings, principal_id="principal:abc@example.com")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_creates_valid_token_with_explicit_expiry(self) -> None:
        settings = _test_settings()
        expires_at = datetime.now(UTC) + timedelta(hours=2)
        token = build_portal_session_token(
            settings,
            principal_id="principal:def@example.com",
            expires_at=expires_at,
        )
        assert isinstance(token, str)
        assert len(token) > 0

    def test_decoded_token_contains_expected_claims(self) -> None:
        settings = _test_settings()
        token = build_portal_session_token(settings, principal_id="principal:xyz@example.com")
        payload = decode_portal_session_cookie_claims(settings, token)
        assert payload["sub"] == "principal:xyz@example.com"
        assert payload["purpose"] == "portal_session"

    def test_includes_issuer_when_configured(self) -> None:
        settings = _test_settings(portal_jwt_issuer="https://cloud.example.com")
        token = build_portal_session_token(settings, principal_id="principal:iss@example.com")
        payload = decode_portal_session_cookie_claims(settings, token)
        assert payload["iss"] == "https://cloud.example.com"

    def test_includes_audience_when_configured(self) -> None:
        settings = _test_settings(portal_jwt_audience="npcink-cloud")
        token = build_portal_session_token(settings, principal_id="principal:aud@example.com")
        payload = decode_portal_session_cookie_claims(settings, token)
        assert payload["aud"] == "npcink-cloud"

    def test_raises_when_portal_not_configured(self) -> None:
        settings = _test_settings(portal_jwt_secret="")
        with pytest.raises(RuntimeError, match="Portal auth is not configured"):
            build_portal_session_token(settings, principal_id="principal:fail@example.com")


class TestDecodePortalBearerClaims:
    def test_decodes_valid_token(self) -> None:
        settings = _test_settings()
        token = build_portal_session_token(settings, principal_id="principal:test@example.com")
        payload = decode_portal_bearer_claims(settings, token)
        assert payload["sub"] == "principal:test@example.com"

    def test_rejects_expired_token(self) -> None:
        settings = _test_settings()
        expires_at = datetime.now(UTC) - timedelta(seconds=1)
        token = build_portal_session_token(
            settings, principal_id="expired_principal", expires_at=expires_at
        )
        with pytest.raises(PortalBearerTokenError) as exc_info:
            decode_portal_bearer_claims(settings, token)
        assert exc_info.value.error_code == "auth.portal_token_expired"

    def test_rejects_invalid_token(self) -> None:
        settings = _test_settings()
        with pytest.raises(PortalBearerTokenError) as exc_info:
            decode_portal_bearer_claims(settings, "not-a-valid-jwt-token")
        assert exc_info.value.error_code == "auth.portal_token_invalid"

    def test_raises_when_not_configured(self) -> None:
        settings = _test_settings(portal_jwt_secret="")
        with pytest.raises(PortalBearerTokenError) as exc_info:
            decode_portal_bearer_claims(settings, "any-token")
        assert exc_info.value.error_code == "auth.portal_not_configured"


class TestDecodePortalBearerToken:
    def test_extracts_principal_id_from_valid_token(self) -> None:
        settings = _test_settings()
        token = build_portal_session_token(
            settings,
            principal_id="principal:extract@example.com",
        )
        principal_id = decode_portal_bearer_token(settings, token)
        assert principal_id == "principal:extract@example.com"

    def test_rejects_token_without_sub(self) -> None:
        settings = _test_settings()
        token = build_portal_session_token(settings, principal_id="")
        with pytest.raises(PortalBearerTokenError) as exc_info:
            decode_portal_bearer_token(settings, token)
        assert exc_info.value.error_code == "auth.principal_id_required"

    def test_rejects_token_with_empty_sub(self) -> None:
        import jwt as _jwt

        from app.api.auth import PortalBearerTokenError

        settings = _test_settings()
        now = datetime.now(UTC)
        payload = {"purpose": "portal_session", "iat": int(now.timestamp())}
        token = _jwt.encode(payload, settings.portal_jwt_secret, algorithm="HS256")
        with pytest.raises(PortalBearerTokenError) as exc_info:
            decode_portal_bearer_token(settings, token)
        assert exc_info.value.error_code == "auth.principal_id_required"


class TestDecodePortalSessionCookieClaims:
    def test_rejects_token_with_wrong_purpose(self) -> None:
        import jwt as _jwt

        settings = _test_settings()
        now = datetime.now(UTC)
        payload = {
            "sub": "principal:x@example.com",
            "purpose": "other_purpose",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        }
        token = _jwt.encode(payload, settings.portal_jwt_secret, algorithm="HS256")
        with pytest.raises(PortalBearerTokenError) as exc_info:
            decode_portal_session_cookie_claims(settings, token)
        assert exc_info.value.error_code == "auth.portal_session_invalid"

    def test_rejects_expired_session_token(self) -> None:
        settings = _test_settings()
        expires_at = datetime.now(UTC) - timedelta(seconds=10)
        token = build_portal_session_token(
            settings, principal_id="expired_session", expires_at=expires_at
        )
        with pytest.raises(PortalBearerTokenError) as exc_info:
            decode_portal_session_cookie_claims(settings, token)
        assert exc_info.value.error_code == "auth.portal_session_expired"


class TestResolveTtl:
    def test_resolve_session_ttl_returns_minimum_60_seconds(self) -> None:
        settings = _test_settings(portal_session_ttl_seconds=10)
        ttl = resolve_portal_session_ttl_seconds(settings)
        assert ttl == 60

    def test_resolve_session_ttl_honors_configured_value(self) -> None:
        settings = _test_settings(portal_session_ttl_seconds=3600)
        ttl = resolve_portal_session_ttl_seconds(settings)
        assert ttl == 3600

    def test_resolve_login_code_ttl_returns_minimum_60_seconds(self) -> None:
        settings = _test_settings(portal_login_code_ttl_seconds=5)
        ttl = resolve_portal_login_code_ttl_seconds(settings)
        assert ttl == 60

    def test_resolve_login_code_ttl_honors_configured_value(self) -> None:
        settings = _test_settings(portal_login_code_ttl_seconds=600)
        ttl = resolve_portal_login_code_ttl_seconds(settings)
        assert ttl == 600


class TestPortalBearerTokenError:
    def test_error_has_expected_attributes(self) -> None:
        error = PortalBearerTokenError(401, "auth.test_error", "test message")
        assert error.status_code == 401
        assert error.error_code == "auth.test_error"
        assert error.message == "test message"
        assert str(error) == "test message"
