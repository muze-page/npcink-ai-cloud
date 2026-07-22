from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.adapters.notifications.base import PortalEmailSender
from app.adapters.repositories.commercial_repository import CommercialRepository
from app.api.admin_ops import ResolvedAdminSession
from app.api.auth import PortalBearerTokenError
from app.api.main import create_app
from app.api.portal_session import set_portal_session_cookies
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import Site
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from app.domain.commercial.service import CommercialService
from app.setup.security import sha256_text
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
    build_internal_headers,
)

TEST_ADMIN_KEY = "nca_admin_npcink-cloud-admin-key-test-32"
TEST_ADMIN_SESSION_ISSUER = "npcink-ai-cloud"
TEST_ADMIN_SESSION_AUDIENCE = "npcink-ai-cloud-admin"
TEST_ADMIN_SESSION_PURPOSE = "admin_session"


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'web-routes.sqlite3'}"


def _build_client(
    tmp_path: Path,
    *,
    settings_overrides: dict[str, object] | None = None,
    portal_email_sender: PortalEmailSender | None = None,
) -> tuple[str, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()

    settings_kwargs: dict[str, object] = {
        "_env_file": None,
        "project_name": "Npcink AI Cloud Test",
        "environment": "test",
        "database_url": database_url,
        "redis_url": "redis://localhost:6379/0",
        "internal_auth_token": TEST_INTERNAL_AUTH_TOKEN,
        "admin_key_sha256": sha256_text(TEST_ADMIN_KEY),
        "admin_session_secret": TEST_ADMIN_SESSION_SECRET,
        "allow_dev_admin_internal_token_fallback": False,
        "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
        "admin_principal_id": "platform:founder",
    }
    settings_kwargs.update(settings_overrides or {})
    settings = Settings(**settings_kwargs)
    client = TestClient(
        create_app(
            CloudServices(
                settings=settings,
                portal_email_sender=portal_email_sender,
            )
        )
    )
    client.headers.update(
        {
            "origin": "http://testserver",
            "referer": "http://testserver/",
        }
    )
    return database_url, client


class FakePortalEmailSender(PortalEmailSender):
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def send_test_email(
        self,
        *,
        recipient_email: str,
        project_name: str,
        portal_url: str,
    ) -> None:
        self.messages.append(
            {
                "kind": "test",
                "recipient_email": recipient_email,
                "project_name": project_name,
                "portal_url": portal_url,
            }
        )

    def send_login_code(
        self,
        *,
        recipient_email: str,
        principal_id: str,
        code: str,
        expires_in_seconds: int,
        project_name: str,
        locale: str = "zh-CN",
    ) -> None:
        self.messages.append(
            {
                "kind": "login_code",
                "recipient_email": recipient_email,
                "principal_id": principal_id,
                "code": code,
                "expires_in_seconds": expires_in_seconds,
                "project_name": project_name,
                "locale": locale,
            }
        )

    def send_registration_code(
        self,
        *,
        recipient_email: str,
        principal_id: str,
        code: str,
        expires_in_seconds: int,
        project_name: str,
        site_name: str = "",
        site_url: str = "",
        locale: str = "zh-CN",
    ) -> None:
        self.messages.append(
            {
                "kind": "registration_code",
                "recipient_email": recipient_email,
                "principal_id": principal_id,
                "code": code,
                "expires_in_seconds": expires_in_seconds,
                "project_name": project_name,
                "site_name": site_name,
                "site_url": site_url,
                "locale": locale,
            }
        )

    def send_email_change_code(
        self,
        *,
        recipient_email: str,
        old_email: str,
        principal_id: str,
        code: str,
        expires_in_seconds: int,
        project_name: str,
        locale: str = "zh-CN",
    ) -> None:
        self.messages.append(
            {
                "kind": "email_change_code",
                "recipient_email": recipient_email,
                "old_email": old_email,
                "principal_id": principal_id,
                "code": code,
                "expires_in_seconds": expires_in_seconds,
                "project_name": project_name,
                "locale": locale,
            }
        )

    def send_email_changed_notice(
        self,
        *,
        recipient_email: str,
        new_email: str,
        principal_id: str,
        project_name: str,
        locale: str = "zh-CN",
    ) -> None:
        self.messages.append(
            {
                "kind": "email_changed_notice",
                "recipient_email": recipient_email,
                "new_email": new_email,
                "principal_id": principal_id,
                "project_name": project_name,
                "locale": locale,
            }
        )


def _login_platform_admin(
    client: TestClient,
    *,
    principal_id: str = "platform:founder",
) -> TestClient:
    client.app.state.services.settings.admin_principal_id = principal_id
    response = client.post(
        "/admin/auth/login",
        data={
            "admin_key": TEST_ADMIN_KEY,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert response.headers["location"].startswith("/admin"), response.headers["location"]
    set_cookie_header = response.headers.get("set-cookie", "")
    assert "npcink_admin_session_token" in set_cookie_header
    assert "Max-Age=0" in set_cookie_header
    return client


def _admin_session_token(
    *,
    remove_claims: tuple[str, ...] = (),
    claim_updates: dict[str, object] | None = None,
    legacy_shape: bool = False,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": "platform:founder",
        "auth_mode": "admin_key",
        "grant_id": "",
        "is_persisted": False,
        "session_version": 1,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    if legacy_shape:
        payload["role"] = "platform_admin"
    else:
        payload.update(
            {
                "iss": TEST_ADMIN_SESSION_ISSUER,
                "aud": TEST_ADMIN_SESSION_AUDIENCE,
                "purpose": TEST_ADMIN_SESSION_PURPOSE,
            }
        )
    for claim_name in remove_claims:
        payload.pop(claim_name, None)
    payload.update(claim_updates or {})
    return jwt.encode(payload, TEST_ADMIN_SESSION_SECRET, algorithm="HS256")


def _portal_session_token(
    *,
    principal_id: str = "principal:portal-probe@example.com",
    claim_updates: dict[str, object] | None = None,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "iss": "npcink-ai-cloud",
        "aud": "npcink-ai-cloud-portal",
        "sub": principal_id,
        "purpose": "portal_session",
        "session_version": 1,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    payload.update(claim_updates or {})
    return jwt.encode(payload, TEST_PORTAL_JWT_SECRET, algorithm="HS256")


def _request_for_client(client: TestClient, *, cookie_header: str = "") -> Request:
    headers = [(b"cookie", cookie_header.encode())] if cookie_header else []
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/portal/v1/session",
            "raw_path": b"/portal/v1/session",
            "query_string": b"",
            "headers": headers,
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "app": client.app,
        }
    )


def _seed_account(
    client: TestClient,
    *,
    account_id: str,
) -> None:
    response = client.post(
        "/internal/service/accounts",
        json={"account_id": account_id, "name": f"Account {account_id}"},
        headers=build_internal_headers(idempotency_key=f"{account_id}-account-seed"),
    )
    assert response.status_code == 200, response.text


def _grant_account_member_access(client: TestClient, *, site_id: str, email: str) -> None:
    safe_email = email.replace("@", "-").replace(".", "-")
    services = client.app.state.services
    with get_session(services.settings.database_url) as session:
        site = session.get(Site, site_id)
        assert site is not None
        account_id = str(site.account_id or "")
    assert account_id
    response = client.post(
        f"/internal/service/accounts/{account_id}/members",
        json={"email": email},
        headers=build_internal_headers(idempotency_key=f"{site_id}-{safe_email}-account-members"),
    )
    assert response.status_code == 200, response.text


def test_web_removed_obsolete_admin_auth_routes_return_not_found(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    removed_login_response = client.get("/admin/auth/oidc/login", follow_redirects=False)
    removed_callback_response = client.get(
        "/admin/auth/oidc/callback?code=oidc-code&state=oidc-state",
        follow_redirects=False,
    )

    assert removed_login_response.status_code == 404
    assert removed_callback_response.status_code == 404

    dispose_engine(database_url)


def test_web_removed_ops_routes_and_bad_admin_token(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    removed_login = client.get("/ops/login", follow_redirects=False)
    removed_bootstrap = client.post("/ops/auth/bootstrap", follow_redirects=False)
    removed_admin_bootstrap = client.post("/admin/auth/bootstrap", follow_redirects=False)
    removed_logout = client.get("/ops/logout", follow_redirects=False)
    invalid_login = client.post(
        "/admin/auth/login",
        data={"admin_key": "wrong-token"},
        follow_redirects=False,
    )

    assert removed_login.status_code == 404
    assert removed_bootstrap.status_code == 404
    assert removed_admin_bootstrap.status_code == 404
    assert removed_logout.status_code == 404
    assert invalid_login.status_code == 303
    assert "auth.admin_key_invalid" in invalid_login.headers["location"]

    dispose_engine(database_url)


def test_web_admin_key_issues_cookie_session(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    _login_platform_admin(client, principal_id="platform:founder")

    session_response = client.get("/admin/session")

    assert session_response.status_code == 200
    assert session_response.json()["data"]["principal_id"] == "platform:founder"
    assert session_response.json()["data"]["identity_type"] == "platform_admin"
    assert session_response.json()["data"]["role"] == "platform_admin"
    assert session_response.json()["data"]["auth_mode"] == "admin_key"
    token = client.cookies.get("npcink_admin_session_token")
    assert token
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["iss"] == TEST_ADMIN_SESSION_ISSUER
    assert claims["aud"] == TEST_ADMIN_SESSION_AUDIENCE
    assert claims["purpose"] == TEST_ADMIN_SESSION_PURPOSE
    assert claims["sub"] == "platform:founder"
    assert claims["auth_mode"] == "admin_key"
    assert claims["grant_id"] == ""
    assert claims["is_persisted"] is False
    assert claims["session_version"] == 1
    assert isinstance(claims["iat"], int)
    assert isinstance(claims["exp"], int)
    assert "role" not in claims

    dispose_engine(database_url)


def test_web_admin_key_json_login_is_fixed_to_server_principal(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    rejected = client.post(
        "/admin/auth/login",
        json={
            "admin_key": TEST_ADMIN_KEY,
            "principal_id": "platform:attacker-selected",
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["error_code"] == "auth.admin_login_request_invalid"
    assert rejected.headers["cache-control"] == "no-store"
    assert rejected.headers["pragma"] == "no-cache"

    response = client.post(
        "/admin/auth/login",
        json={"admin_key": TEST_ADMIN_KEY, "redirect": "/admin/sites"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["principal_id"] == "platform:founder"
    assert response.json()["data"]["auth_mode"] == "admin_key"
    assert "npcink_admin_session_token" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"

    dispose_engine(database_url)


def test_web_admin_json_login_rejects_malformed_json_without_server_error(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)

    response = client.post(
        "/admin/auth/login",
        content='{"admin_key":',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "auth.admin_login_request_invalid"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"

    dispose_engine(database_url)


def test_web_admin_rejects_sub_only_legacy_session(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    client.cookies.set(
        "npcink_admin_session_token",
        jwt.encode(
            {"sub": "platform:founder"},
            TEST_ADMIN_SESSION_SECRET,
            algorithm="HS256",
        ),
    )

    response = client.get("/admin/session")

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.admin_session_invalid"
    dispose_engine(database_url)


@pytest.mark.parametrize(
    "claim_name",
    [
        "iss",
        "aud",
        "sub",
        "purpose",
        "auth_mode",
        "grant_id",
        "is_persisted",
        "session_version",
        "iat",
        "exp",
    ],
)
def test_web_admin_rejects_session_missing_required_claim(
    tmp_path: Path,
    claim_name: str,
) -> None:
    database_url, client = _build_client(tmp_path)
    client.cookies.set(
        "npcink_admin_session_token",
        _admin_session_token(remove_claims=(claim_name,)),
    )

    response = client.get("/admin/session")

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.admin_session_invalid"
    dispose_engine(database_url)


@pytest.mark.parametrize(
    ("claim_name", "claim_value"),
    [
        ("iss", "npcink-ai-cloud-other"),
        ("aud", "npcink-ai-cloud-other"),
        ("purpose", "other_session"),
        ("auth_mode", "dev_internal_autologin"),
        ("auth_mode", "other_auth_mode"),
        ("sub", ""),
        ("grant_id", "unexpected-for-synthetic"),
        ("is_persisted", "false"),
        ("session_version", True),
        ("session_version", 0),
        ("session_version", -1),
        ("session_version", "1"),
        ("session_version", []),
        ("session_version", {}),
        ("iat", True),
        ("iat", "1"),
        ("iat", 1.5),
        ("iat", []),
        ("iat", {}),
        ("exp", True),
        ("exp", "1"),
        ("exp", 1.5),
        ("exp", []),
        ("exp", {}),
        ("nbf", True),
        ("nbf", "1"),
        ("nbf", 1.5),
        ("nbf", []),
        ("nbf", {}),
    ],
)
def test_web_admin_rejects_invalid_session_claim(
    tmp_path: Path,
    claim_name: str,
    claim_value: object,
) -> None:
    database_url, client = _build_client(tmp_path)
    client.cookies.set(
        "npcink_admin_session_token",
        _admin_session_token(claim_updates={claim_name: claim_value}),
    )

    response = client.get("/admin/session")

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.admin_session_invalid"
    dispose_engine(database_url)


def test_web_admin_rejects_retired_dev_internal_autologin_session(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    client.cookies.set(
        "npcink_admin_session_token",
        _admin_session_token(
            legacy_shape=True,
            claim_updates={"auth_mode": "dev_internal_autologin"},
        ),
    )

    response = client.get("/admin/session")

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.admin_session_invalid"
    dispose_engine(database_url)


def test_web_admin_persisted_identity_metadata_cannot_bypass_session_revocation(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    service = CommercialService(database_url)
    synthetic = service.resolve_platform_admin_grant(
        principal_id="platform:founder",
        allow_bootstrap=True,
    )
    assert synthetic["is_persisted"] is False
    assert synthetic["session_version"] == 1

    principal_id = "platform:persisted-bootstrap-metadata"
    persisted = service.upsert_platform_admin_grant(
        principal_id=principal_id,
        metadata_json={"bootstrap": True},
    )
    assert persisted["is_persisted"] is True
    _login_platform_admin(client, principal_id=principal_id)
    assert client.get("/admin/session").status_code == 200

    with get_session(database_url) as session:
        repository = CommercialRepository(session)
        repository.increment_principal_session_version(principal_id=principal_id)
        session.commit()

    response = client.get("/admin/session")

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.admin_session_revoked"
    dispose_engine(database_url)


def test_web_admin_deleted_bootstrap_grant_cannot_downgrade_to_synthetic(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    service = CommercialService(database_url)
    persisted = service.upsert_platform_admin_grant(principal_id="platform:founder")
    _login_platform_admin(client, principal_id="platform:founder")
    token = client.cookies.get("npcink_admin_session_token")
    assert token
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["grant_id"] == persisted["grant_id"]
    assert claims["is_persisted"] is True

    service.delete_platform_admin_grant(principal_id="platform:founder")
    response = client.get("/admin/session")

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.admin_session_revoked"

    recreated = service.upsert_platform_admin_grant(principal_id="platform:founder")
    assert recreated["grant_id"] != persisted["grant_id"]
    response = client.get("/admin/session")

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.admin_session_revoked"
    dispose_engine(database_url)


def test_resolved_admin_session_trusts_explicit_persistence_not_metadata() -> None:
    resolved = ResolvedAdminSession.from_identity(
        {
            "grant_id": "pad_persisted",
            "principal_id": "platform:persisted",
            "role": "platform_admin",
            "session_version": 7,
            "is_persisted": True,
            "metadata": {"bootstrap": True},
        },
        auth_mode="admin_key",
    )

    assert resolved.revocable is True
    assert resolved.session_version == 7


@pytest.mark.parametrize("session_version", [None, 0, True, "1"])
def test_resolved_admin_session_rejects_invalid_version_without_fallback(
    session_version: object,
) -> None:
    with pytest.raises(PortalBearerTokenError) as exc_info:
        ResolvedAdminSession.from_identity(
            {
                "grant_id": "pad_persisted",
                "principal_id": "platform:persisted",
                "role": "platform_admin",
                "session_version": session_version,
                "is_persisted": True,
            },
            auth_mode="admin_key",
        )

    assert exc_info.value.error_code == "auth.admin_session_invalid"


def test_web_admin_does_not_synthetically_bootstrap_unconfigured_internal_root(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    client.cookies.set(
        "npcink_admin_session_token",
        _admin_session_token(claim_updates={"sub": "platform:internal_root"}),
    )

    response = client.get("/admin/session")

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.admin_session_revoked"
    dispose_engine(database_url)


@pytest.mark.parametrize(
    ("transport", "claim_name", "claim_value", "error_code"),
    [
        ("bearer", "iat", [], "auth.portal_token_invalid"),
        ("bearer", "exp", {}, "auth.portal_token_invalid"),
        ("bearer", "nbf", [], "auth.portal_token_invalid"),
        ("cookie", "iat", [], "auth.portal_session_invalid"),
        ("cookie", "exp", {}, "auth.portal_session_invalid"),
        ("cookie", "nbf", [], "auth.portal_session_invalid"),
    ],
)
def test_web_portal_rejects_malicious_temporal_claims_without_500(
    tmp_path: Path,
    transport: str,
    claim_name: str,
    claim_value: object,
    error_code: str,
) -> None:
    database_url, client = _build_client(tmp_path)
    token = _portal_session_token(claim_updates={claim_name: claim_value})
    if transport == "bearer":
        response = client.get(
            "/portal/v1/session",
            headers={"Authorization": f"Bearer {token}"},
        )
    else:
        client.cookies.set("npcink_portal_session_token", token)
        response = client.get("/portal/v1/session")

    assert response.status_code == 403
    assert response.json()["error_code"] == error_code
    dispose_engine(database_url)


@pytest.mark.parametrize(
    ("kwargs", "error_code"),
    [
        ({"principal_id": "principal:missing"}, "auth.portal_session_revoked"),
        (
            {"principal_id": "principal:missing", "session_version": 0},
            "auth.portal_session_invalid",
        ),
        (
            {"principal_id": "principal:missing", "site_id": "site/invalid"},
            "auth.portal_session_invalid",
        ),
    ],
)
def test_portal_cookie_signing_fails_closed_without_identity_or_valid_claims(
    tmp_path: Path,
    kwargs: dict[str, object],
    error_code: str,
) -> None:
    database_url, client = _build_client(tmp_path)
    request = _request_for_client(client)
    principal_id = kwargs.get("principal_id")
    site_id = kwargs.get("site_id", "")
    session_version = kwargs.get("session_version")
    assert isinstance(principal_id, str)
    assert isinstance(site_id, str)
    assert session_version is None or isinstance(session_version, int)

    with pytest.raises(PortalBearerTokenError) as exc_info:
        set_portal_session_cookies(
            request,
            JSONResponse({}),
            principal_id=principal_id,
            site_id=site_id,
            session_version=session_version,
        )

    assert exc_info.value.error_code == error_code
    dispose_engine(database_url)


def test_portal_cookie_signing_failure_does_not_emit_session_cookie(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, client = _build_client(tmp_path)
    principal_id = "principal:signing-failure"
    CommercialService(database_url).upsert_platform_admin_grant(principal_id=principal_id)
    response = JSONResponse({})

    def fail_signing(*args: object, **kwargs: object) -> str:
        raise RuntimeError("signing failed")

    monkeypatch.setattr(
        "app.api.portal_session.build_portal_session_token",
        fail_signing,
    )
    with pytest.raises(RuntimeError, match="signing failed"):
        set_portal_session_cookies(
            _request_for_client(client),
            response,
            principal_id=principal_id,
        )

    assert response.headers.getlist("set-cookie") == []
    dispose_engine(database_url)


def test_web_portal_session_evidence_comes_only_from_signed_claims(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    principal_id = "principal:signed-session-evidence"
    CommercialService(database_url).upsert_platform_admin_grant(principal_id=principal_id)
    issued_at = int((datetime.now(UTC) - timedelta(minutes=5)).timestamp())
    expires_at = int((datetime.now(UTC) + timedelta(hours=1)).timestamp())
    token = _portal_session_token(
        principal_id=principal_id,
        claim_updates={"iat": issued_at, "exp": expires_at},
    )
    client.cookies.set("npcink_portal_session_token", token)
    client.cookies.set("npcink_portal_session_issued_at", "2099-01-01T00:00:00Z")
    client.cookies.set("npcink_portal_session_expires_at", "2000-01-01T00:00:00Z")
    client.cookies.set("npcink_portal_site_id", "site_unsigned_fallback")

    response = client.get("/portal/v1/session")

    assert response.status_code == 200, response.text
    session = response.json()["data"]["session"]
    assert session["issued_at"] == (
        datetime.fromtimestamp(issued_at, tz=UTC).isoformat().replace("+00:00", "Z")
    )
    assert session["expires_at"] == (
        datetime.fromtimestamp(expires_at, tz=UTC).isoformat().replace("+00:00", "Z")
    )
    assert "site_id" not in response.json()["data"]
    dispose_engine(database_url)


def test_web_admin_key_is_separate_from_internal_service_token(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    response = client.post(
        "/admin/auth/login",
        data={
            "admin_key": TEST_INTERNAL_AUTH_TOKEN,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "auth.admin_key_invalid" in response.headers["location"]

    dispose_engine(database_url)


def test_web_admin_and_portal_sessions_do_not_substitute_for_each_other(tmp_path: Path) -> None:
    fake_sender = FakePortalEmailSender()
    database_url, portal_client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_jwt_issuer": "npcink-cloud-portal",
            "portal_jwt_audience": "npcink-cloud-customers",
        },
        portal_email_sender=fake_sender,
    )
    _seed_account(portal_client, account_id="acct_identity_boundary")
    site_response = portal_client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_identity_boundary",
            "account_id": "acct_identity_boundary",
            "name": "Identity Boundary Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="identity-boundary-site"),
    )
    assert site_response.status_code == 200, site_response.text
    activate_response = portal_client.post(
        "/internal/service/sites/site_identity_boundary/activate",
        headers=build_internal_headers(idempotency_key="identity-boundary-activate"),
    )
    assert activate_response.status_code == 200, activate_response.text
    _grant_account_member_access(
        portal_client,
        site_id="site_identity_boundary",
        email="identity-boundary@example.com",
    )

    request_response = portal_client.post(
        "/portal/v1/auth/code/request",
        json={"email": "identity-boundary@example.com"},
    )
    assert request_response.status_code == 200, request_response.text
    verify_response = portal_client.post(
        "/portal/v1/auth/code/verify",
        json={
            "email": "identity-boundary@example.com",
            "code": str(fake_sender.messages[0]["code"]),
        },
    )
    assert verify_response.status_code == 200, verify_response.text
    assert verify_response.json()["data"]["email"] == "identity-boundary@example.com"
    assert "identity_type" not in verify_response.json()["data"]
    assert portal_client.get("/admin/session").status_code == 401

    admin_client = TestClient(portal_client.app)
    admin_client.headers.update(
        {
            "origin": "http://testserver",
            "referer": "http://testserver/",
        }
    )
    _login_platform_admin(admin_client)
    admin_session_response = admin_client.get("/admin/session")
    assert admin_session_response.status_code == 200
    assert admin_session_response.json()["data"]["identity_type"] == "platform_admin"
    assert admin_client.get("/portal/v1/session").status_code == 401

    dispose_engine(database_url)


def test_web_removed_rendered_pages_return_not_found(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    for path in (
        "/",
        "/features",
        "/getting-started",
        "/portal/login",
        "/portal",
        "/portal/overview",
        "/portal/keys",
        "/admin/login",
        "/admin",
        "/admin/accounts",
        "/admin/sites",
        "/admin/subscriptions",
    ):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 404, path

    dispose_engine(database_url)


def test_web_rejects_untrusted_forwarded_host_in_production(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "environment": "production",
            "browser_origin_allowlist": "https://cloud.example.com",
            "trusted_host_allowlist": "cloud.example.com",
        },
    )

    response = client.get(
        "/admin/session",
        headers={
            "host": "cloud.example.com",
            "x-forwarded-host": "evil.example.com",
            "x-forwarded-proto": "https",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "request.forwarded_host_invalid"

    dispose_engine(database_url)


def test_web_allows_untrusted_forwarded_host_in_development_when_browser_origin_is_trusted(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "environment": "development",
            "browser_origin_allowlist": "http://100.102.170.79:8010",
        },
    )

    response = client.get(
        "/health/live",
        headers={
            "host": "testserver",
            "x-forwarded-host": "frontend:3000",
            "x-forwarded-proto": "http",
            "origin": "http://100.102.170.79:8010",
            "referer": "http://100.102.170.79:8010/",
        },
        follow_redirects=False,
    )

    assert response.status_code == 200

    dispose_engine(database_url)


def test_web_rejects_untrusted_forwarded_origin_in_production(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "environment": "production",
            "browser_origin_allowlist": "https://cloud.example.com",
            "trusted_host_allowlist": "cloud.example.com",
        },
    )

    response = client.get(
        "/admin/session",
        headers={
            "host": "cloud.example.com",
            "x-forwarded-host": "cloud.example.com",
            "x-forwarded-proto": "http",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "request.forwarded_origin_invalid"

    dispose_engine(database_url)


def test_web_removed_multi_admin_pages_return_not_found(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    _login_platform_admin(client, principal_id="platform:founder")

    platform_admins_page = client.get("/admin/platform-admins", follow_redirects=False)
    identities_page = client.get("/admin/identities", follow_redirects=False)

    assert platform_admins_page.status_code == 404
    assert identities_page.status_code == 404

    dispose_engine(database_url)


def test_internal_platform_admin_directory_routes_are_removed(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    list_response = client.get(
        "/internal/service/admin/platform-admins",
        headers=build_internal_headers(),
    )
    create_response = client.post(
        "/internal/service/platform-admin-identities",
        json={
            "principal_id": "platform:anything",
            "role": "platform_admin",
            "email": "founder@example.com",
        },
        headers=build_internal_headers(idempotency_key="platform-admin-create-disabled"),
    )
    delete_response = client.delete(
        "/internal/service/platform-admin-identities/platform:anything",
        headers=build_internal_headers(idempotency_key="platform-admin-delete-disabled"),
    )

    assert list_response.status_code == 404
    assert create_response.status_code == 404
    assert delete_response.status_code == 404

    dispose_engine(database_url)


def test_web_portal_preview_surface_is_removed(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    response = client.post(
        "/portal/preview/email-login/request", json={"email": "outsider@example.com"}
    )

    assert response.status_code == 404

    dispose_engine(database_url)


def test_web_portal_email_code_and_addon_connection_with_jwt(tmp_path: Path) -> None:
    fake_sender = FakePortalEmailSender()
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_jwt_issuer": "npcink-cloud-portal",
            "portal_jwt_audience": "npcink-cloud-customers",
        },
        portal_email_sender=fake_sender,
    )

    registration_request = client.post(
        "/portal/v1/register/code/request",
        json={
            "email": "web@example.com",
            "site_name": "Web Site",
            "site_url": "https://web.example.test",
        },
    )
    assert registration_request.status_code == 200, registration_request.text
    registration_response = client.post(
        "/portal/v1/register/verify",
        json={"email": "web@example.com", "code": str(fake_sender.messages[0]["code"])},
    )
    assert registration_response.status_code == 200, registration_response.text
    registration_data = registration_response.json()["data"]
    site_id = str(registration_data["selected_context"]["site"]["site_id"])
    addon_accounts_response = client.get("/portal/v1/addon-connection-accounts")
    assert addon_accounts_response.status_code == 200
    account_id = str(addon_accounts_response.json()["data"]["items"][0]["account_id"])
    assert client.post("/portal/v1/logout").status_code == 200

    login_request_response = client.post(
        "/portal/v1/auth/code/request",
        json={"email": "web@example.com"},
    )
    assert login_request_response.status_code == 200
    assert login_request_response.json()["data"]["delivery"] == "email"
    assert login_request_response.json()["data"]["code"] == ""
    assert len(fake_sender.messages) == 2

    login_verify_response = client.post(
        "/portal/v1/auth/code/verify",
        json={"email": "web@example.com", "code": str(fake_sender.messages[-1]["code"])},
    )
    assert login_verify_response.status_code == 200
    assert login_verify_response.json()["data"]["email"] == "web@example.com"
    assert login_verify_response.json()["data"]["selected_context"] is None

    addon_state = "web-addon-state"
    connection_response = client.post(
        "/portal/v1/addon-connections",
        headers={"Idempotency-Key": "web-addon-connection"},
        json={
            "account_id": account_id,
            "site_url": "https://web.example.test",
            "site_name": "Web Site",
            "return_url": (
                "https://web.example.test/wp-admin/admin-post.php"
                f"?action=npcink_cloud_addon_complete_auth&state={addon_state}"
            ),
            "state": addon_state,
        },
    )
    assert connection_response.status_code == 200, connection_response.text
    connection_data = connection_response.json()["data"]
    assert connection_data["site_id"] == site_id
    assert "cloud_api_key" not in connection_data
    redirect_query = parse_qs(urlsplit(str(connection_data["redirect_url"])).query)

    exchange_response = client.post(
        "/portal/v1/addon-connections/exchange",
        json={"code": redirect_query["code"][0], "state": addon_state},
    )
    assert exchange_response.status_code == 200, exchange_response.text
    assert exchange_response.json()["data"]["cloud_api_key"].startswith("mak1_")

    dispose_engine(database_url)
