"""Tests for cloud auth helpers (app.api.auth).

Tests core token lifecycle functions without requiring a full FastAPI request context.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import jwt
import pytest

from app.api.auth import (
    PortalBearerTokenError,
    build_portal_session_token,
    decode_portal_bearer_claims,
    decode_portal_bearer_token,
    decode_portal_session_cookie_claims,
    resolve_portal_login_code_ttl_seconds,
    resolve_portal_remember_me_session_ttl_seconds,
    resolve_portal_session_ttl_seconds,
)
from app.core.config import Settings

MALFORMED_TEMPORAL_CLAIMS: tuple[tuple[str, object], ...] = (
    ("iat", True),
    ("iat", "1"),
    ("iat", 1.5),
    ("iat", []),
    ("iat", {}),
    ("iat", None),
    ("exp", True),
    ("exp", "1"),
    ("exp", 1.5),
    ("exp", []),
    ("exp", {}),
    ("exp", None),
    ("nbf", True),
    ("nbf", "1"),
    ("nbf", 1.5),
    ("nbf", []),
    ("nbf", {}),
    ("nbf", None),
)


def _test_settings(**overrides: object) -> Settings:
    kwargs: dict[str, object] = {
        "_env_file": None,
        "project_name": "Auth Test",
        "environment": "test",
        "database_url": "sqlite+pysqlite:///:memory:",
        "portal_jwt_secret": "test-portal-jwt-secret-at-least-32-bytes-long",
    }
    kwargs.update(overrides)
    return Settings(**kwargs)


def _resign_portal_session_token(
    settings: Settings,
    *,
    remove_claims: tuple[str, ...] = (),
    claim_updates: dict[str, object] | None = None,
) -> str:
    token = build_portal_session_token(
        settings,
        principal_id="principal:mutated@example.com",
    )
    payload = jwt.decode(token, options={"verify_signature": False})
    for claim_name in remove_claims:
        payload.pop(claim_name, None)
    payload.update(claim_updates or {})
    assert settings.portal_jwt_secret is not None
    return jwt.encode(
        payload,
        settings.portal_jwt_secret,
        algorithm="HS256",
    )


class TestBuildPortalSessionToken:
    def test_creates_valid_token_with_default_expiry(self) -> None:
        settings = _test_settings()
        token = build_portal_session_token(settings, principal_id="principal:abc@example.com")
        assert isinstance(token, str)
        assert len(token) > 0
        assert jwt.get_unverified_header(token)["alg"] == "HS256"

    @pytest.mark.parametrize("principal_id", ["", " principal:padded "])
    def test_rejects_invalid_principal_before_signing(self, principal_id: str) -> None:
        settings = _test_settings()

        with pytest.raises(ValueError, match="principal_id"):
            build_portal_session_token(settings, principal_id=principal_id)

    @pytest.mark.parametrize("site_id", ["site/invalid", " site_padded", "site_padded "])
    def test_rejects_invalid_site_before_signing(self, site_id: str) -> None:
        settings = _test_settings()

        with pytest.raises(ValueError, match="site_id"):
            build_portal_session_token(
                settings,
                principal_id="principal:site@example.com",
                site_id=site_id,
            )

    @pytest.mark.parametrize("session_version", [True, 0, -1, "1", [], {}])
    def test_rejects_invalid_session_version_before_signing(
        self,
        session_version: object,
    ) -> None:
        settings = _test_settings()

        with pytest.raises(ValueError, match="session_version"):
            build_portal_session_token(
                settings,
                principal_id="principal:version@example.com",
                session_version=cast(Any, session_version),
            )

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

    def test_rejects_expired_timestamp_before_signing(self) -> None:
        settings = _test_settings()

        with pytest.raises(ValueError, match="expires_at"):
            build_portal_session_token(
                settings,
                principal_id="principal:expired@example.com",
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )

    def test_decoded_token_contains_expected_claims(self) -> None:
        settings = _test_settings()
        token = build_portal_session_token(settings, principal_id="principal:xyz@example.com")
        payload = decode_portal_session_cookie_claims(settings, token)
        assert payload["sub"] == "principal:xyz@example.com"
        assert payload["purpose"] == "portal_session"
        assert payload["session_version"] == 1
        assert payload["iss"] == "npcink-ai-cloud"
        assert payload["aud"] == "npcink-ai-cloud-portal"
        assert isinstance(payload["iat"], int)
        assert isinstance(payload["exp"], int)

    def test_decoded_token_can_contain_selected_site_id(self) -> None:
        settings = _test_settings()
        token = build_portal_session_token(
            settings,
            principal_id="principal:xyz@example.com",
            site_id="site_portal_session",
        )
        payload = decode_portal_session_cookie_claims(settings, token)
        assert payload["site_id"] == "site_portal_session"

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

    def test_decodes_valid_token_with_selected_site_id(self) -> None:
        settings = _test_settings()
        token = build_portal_session_token(
            settings,
            principal_id="principal:site@example.com",
            site_id="site.valid:example-1",
        )

        payload = decode_portal_bearer_claims(settings, token)

        assert payload["site_id"] == "site.valid:example-1"

    @pytest.mark.parametrize(
        "claim_name",
        ["sub", "purpose", "session_version", "iat", "exp", "iss", "aud"],
    )
    def test_rejects_token_missing_required_claim(self, claim_name: str) -> None:
        settings = _test_settings()
        token = _resign_portal_session_token(
            settings,
            remove_claims=(claim_name,),
        )

        with pytest.raises(PortalBearerTokenError) as exc_info:
            decode_portal_bearer_claims(settings, token)

        assert exc_info.value.error_code == "auth.portal_token_invalid"

    def test_rejects_token_with_wrong_purpose(self) -> None:
        settings = _test_settings()
        token = _resign_portal_session_token(
            settings,
            claim_updates={"purpose": "other_purpose"},
        )

        with pytest.raises(PortalBearerTokenError) as exc_info:
            decode_portal_bearer_claims(settings, token)

        assert exc_info.value.error_code == "auth.portal_token_invalid"

    @pytest.mark.parametrize(("claim_name", "claim_value"), MALFORMED_TEMPORAL_CLAIMS)
    def test_rejects_malformed_temporal_claims_without_raising_raw_errors(
        self,
        claim_name: str,
        claim_value: object,
    ) -> None:
        settings = _test_settings()
        token = _resign_portal_session_token(
            settings,
            claim_updates={claim_name: claim_value},
        )

        with pytest.raises(PortalBearerTokenError) as exc_info:
            decode_portal_bearer_claims(settings, token)

        assert exc_info.value.error_code == "auth.portal_token_invalid"

    @pytest.mark.parametrize("claim_name", ["iat", "nbf"])
    def test_rejects_future_activation_claims(
        self,
        claim_name: str,
    ) -> None:
        settings = _test_settings()
        token = _resign_portal_session_token(
            settings,
            claim_updates={claim_name: int((datetime.now(UTC) + timedelta(hours=1)).timestamp())},
        )

        with pytest.raises(PortalBearerTokenError) as exc_info:
            decode_portal_bearer_claims(settings, token)

        assert exc_info.value.error_code == "auth.portal_token_invalid"

    @pytest.mark.parametrize(
        "site_id",
        [
            "site id with spaces",
            "site/with/slashes",
            "s" * 192,
            123,
        ],
    )
    def test_rejects_invalid_site_id(self, site_id: object) -> None:
        settings = _test_settings()
        token = _resign_portal_session_token(
            settings,
            claim_updates={"site_id": site_id},
        )

        with pytest.raises(PortalBearerTokenError) as exc_info:
            decode_portal_bearer_claims(settings, token)

        assert exc_info.value.error_code == "auth.portal_token_invalid"

    def test_rejects_expired_token(self) -> None:
        settings = _test_settings()
        now = datetime.now(UTC)
        token = _resign_portal_session_token(
            settings,
            claim_updates={
                "iat": int((now - timedelta(hours=2)).timestamp()),
                "exp": int((now - timedelta(hours=1)).timestamp()),
            },
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
        token = _resign_portal_session_token(
            settings,
            claim_updates={"sub": ""},
        )
        with pytest.raises(PortalBearerTokenError) as exc_info:
            decode_portal_bearer_token(settings, token)
        assert exc_info.value.error_code == "auth.portal_token_invalid"

    def test_rejects_token_missing_sub(self) -> None:
        settings = _test_settings()
        token = _resign_portal_session_token(settings, remove_claims=("sub",))
        with pytest.raises(PortalBearerTokenError) as exc_info:
            decode_portal_bearer_token(settings, token)
        assert exc_info.value.error_code == "auth.portal_token_invalid"


class TestDecodePortalSessionCookieClaims:
    @pytest.mark.parametrize(
        "claim_name",
        ["sub", "purpose", "session_version", "iat", "exp", "iss", "aud"],
    )
    def test_rejects_token_missing_required_claim(self, claim_name: str) -> None:
        settings = _test_settings()
        token = _resign_portal_session_token(
            settings,
            remove_claims=(claim_name,),
        )

        with pytest.raises(PortalBearerTokenError) as exc_info:
            decode_portal_session_cookie_claims(settings, token)

        assert exc_info.value.error_code == "auth.portal_session_invalid"

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

    @pytest.mark.parametrize(
        ("claim_name", "claim_value"),
        [
            ("iss", "npcink-ai-cloud-other"),
            ("aud", "npcink-ai-cloud-other"),
            ("sub", ""),
            ("session_version", True),
            ("session_version", 0),
            ("session_version", -1),
            ("session_version", "1"),
            ("session_version", []),
            ("session_version", {}),
            ("site_id", ""),
            ("site_id", "site/invalid"),
            ("site_id", 123),
        ],
    )
    def test_rejects_invalid_claim_value(
        self,
        claim_name: str,
        claim_value: object,
    ) -> None:
        settings = _test_settings()
        token = _resign_portal_session_token(
            settings,
            claim_updates={claim_name: claim_value},
        )

        with pytest.raises(PortalBearerTokenError) as exc_info:
            decode_portal_session_cookie_claims(settings, token)

        assert exc_info.value.error_code == "auth.portal_session_invalid"

    @pytest.mark.parametrize(("claim_name", "claim_value"), MALFORMED_TEMPORAL_CLAIMS)
    def test_rejects_malformed_temporal_claims_without_raising_raw_errors(
        self,
        claim_name: str,
        claim_value: object,
    ) -> None:
        settings = _test_settings()
        token = _resign_portal_session_token(
            settings,
            claim_updates={claim_name: claim_value},
        )

        with pytest.raises(PortalBearerTokenError) as exc_info:
            decode_portal_session_cookie_claims(settings, token)

        assert exc_info.value.error_code == "auth.portal_session_invalid"

    def test_rejects_expired_session_token(self) -> None:
        settings = _test_settings()
        now = datetime.now(UTC)
        token = _resign_portal_session_token(
            settings,
            claim_updates={
                "iat": int((now - timedelta(hours=2)).timestamp()),
                "exp": int((now - timedelta(hours=1)).timestamp()),
            },
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

    def test_resolve_remember_me_ttl_defaults_to_seven_days(self) -> None:
        settings = _test_settings(portal_session_ttl_seconds=3600)
        ttl = resolve_portal_remember_me_session_ttl_seconds(settings)
        assert ttl == 7 * 24 * 60 * 60

    def test_resolve_remember_me_ttl_never_shortens_base_session(self) -> None:
        settings = _test_settings(
            portal_session_ttl_seconds=3600,
            portal_remember_me_session_ttl_seconds=120,
        )
        ttl = resolve_portal_remember_me_session_ttl_seconds(settings)
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
