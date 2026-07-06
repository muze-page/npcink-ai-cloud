from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.adapters.notifications.base import PortalEmailSender
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, init_schema
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
    build_internal_headers,
)

TEST_ADMIN_BOOTSTRAP_TOKEN = "npcink-cloud-admin-bootstrap-test-32"


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
        "admin_bootstrap_token": TEST_ADMIN_BOOTSTRAP_TOKEN,
        "admin_session_secret": TEST_ADMIN_SESSION_SECRET,
        "allow_dev_admin_internal_token_fallback": False,
        "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
        "admin_bootstrap_principal_id": "platform:founder",
        "admin_bootstrap_platform_admin_role": "platform_admin",
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
        wordpress_url: str = "",
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
                "wordpress_url": wordpress_url,
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
    response = client.post(
        "/admin/auth/bootstrap",
        data={
            "token": TEST_ADMIN_BOOTSTRAP_TOKEN,
            "principal_id": principal_id,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert response.headers["location"].startswith("/admin"), response.headers["location"]
    set_cookie_header = response.headers.get("set-cookie", "")
    assert "npcink_admin_session_token" in set_cookie_header
    assert "magick_admin_session_token" in set_cookie_header
    assert "Max-Age=0" in set_cookie_header
    return client


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


def _grant_principal_access(client: TestClient, *, site_id: str, email: str) -> None:
    safe_email = email.replace("@", "-").replace(".", "-")
    response = client.post(
        f"/internal/service/sites/{site_id}/user-grants",
        json={"email": email},
        headers=build_internal_headers(idempotency_key=f"{site_id}-{safe_email}-user-grants"),
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
    removed_logout = client.get("/ops/logout", follow_redirects=False)
    invalid_login = client.post(
        "/admin/auth/bootstrap",
        data={"token": "wrong-token", "principal_id": "platform:founder"},
        follow_redirects=False,
    )

    assert removed_login.status_code == 404
    assert removed_bootstrap.status_code == 404
    assert removed_logout.status_code == 404
    assert invalid_login.status_code == 303
    assert "auth.admin_bootstrap_token_invalid" in invalid_login.headers["location"]

    dispose_engine(database_url)


def test_web_admin_bootstrap_issues_cookie_session(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    _login_platform_admin(client, principal_id="platform:founder")

    session_response = client.get("/admin/session")

    assert session_response.status_code == 200
    assert session_response.json()["data"]["principal_id"] == "platform:founder"
    assert session_response.json()["data"]["identity_type"] == "platform_admin"
    assert session_response.json()["data"]["role"] == "platform_admin"
    assert session_response.json()["data"]["auth_mode"] == "admin_bootstrap_token"

    dispose_engine(database_url)


def test_web_admin_bootstrap_token_is_separate_from_internal_service_token(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    response = client.post(
        "/admin/auth/bootstrap",
        data={
            "token": TEST_INTERNAL_AUTH_TOKEN,
            "principal_id": "platform:founder",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "auth.admin_bootstrap_token_invalid" in response.headers["location"]

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


def test_web_portal_email_code_and_key_actions_with_jwt(tmp_path: Path) -> None:
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

    _seed_account(
        client,
        account_id="acct_web",
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_web",
            "account_id": "acct_web",
            "name": "Web Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="web-site-001"),
    )
    client.post(
        "/internal/service/sites/site_web/activate",
        headers=build_internal_headers(idempotency_key="web-site-activate-001"),
    )
    _grant_principal_access(client, site_id="site_web", email="web@example.com")

    login_request_response = client.post(
        "/portal/v1/auth/code/request",
        json={"email": "web@example.com"},
    )
    assert login_request_response.status_code == 200
    assert login_request_response.json()["data"]["delivery"] == "email"
    assert login_request_response.json()["data"]["code"] == ""
    assert len(fake_sender.messages) == 1

    login_verify_response = client.post(
        "/portal/v1/auth/code/verify",
        json={"email": "web@example.com", "code": str(fake_sender.messages[0]["code"])},
    )
    assert login_verify_response.status_code == 200
    assert login_verify_response.json()["data"]["principal_id"].startswith("prn_")

    issue_response = client.post(
        "/portal/v1/sites/site_web/api-keys",
        json={"label": "Web Key"},
        headers={"origin": "http://testserver", "referer": "http://testserver/"},
    )
    assert issue_response.status_code == 200
    assert issue_response.json()["data"]["cloud_api_key"].startswith("mak1_")

    dispose_engine(database_url)
