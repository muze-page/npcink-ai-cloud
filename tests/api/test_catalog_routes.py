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
    TEST_INTERNAL_AUTH_TOKEN,
    build_auth_headers,
    build_internal_headers,
    merge_json_headers,
    seed_site_auth,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'catalog-api.sqlite3'}"


class FakePortalEmailSender(PortalEmailSender):
    def __init__(self) -> None:
        self.test_messages: list[dict[str, str]] = []

    def send_test_email(
        self,
        *,
        recipient_email: str,
        project_name: str,
        portal_url: str,
    ) -> None:
        self.test_messages.append(
            {
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
        return None

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
        return None

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
        return None

    def send_email_changed_notice(
        self,
        *,
        recipient_email: str,
        new_email: str,
        principal_id: str,
        project_name: str,
        locale: str = "zh-CN",
    ) -> None:
        return None

def test_catalog_routes_return_seeded_models(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_site_auth(database_url, site_id="site_catalog", scopes=["catalog:read"])

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    response = client.get(
        "/v1/catalog/models",
        headers=build_auth_headers(
            "GET",
            "/v1/catalog/models",
            site_id="site_catalog",
            trace_id="tracecatalog0010000000000000000",
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["total"] == 4
    assert "recommended_sets" in payload["data"]
    assert payload["data"]["platform_models"]["surface"] == "platform_models"
    assert payload["message"] == "platform models loaded"

    dispose_engine(database_url)


def test_catalog_routes_support_recommended_profile_filter(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_site_auth(database_url, site_id="site_catalog", scopes=["catalog:read"])

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    response = client.get(
        "/v1/catalog/models",
        params={"recommended_for": "text.balanced"},
        headers=build_auth_headers(
            "GET",
            "/v1/catalog/models",
            site_id="site_catalog",
            trace_id="tracecatalog0020000000000000000",
            query="recommended_for=text.balanced",
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["recommended_for"] == "text.balanced"
    assert payload["data"]["platform_models"]["recommended_for"] == "text.balanced"
    assert payload["data"]["total"] == 1
    assert payload["data"]["items"][0]["model_id"] == "gpt-4.1-mini"
    assert payload["data"]["items"][0]["recommended_rank"] == 1

    dispose_engine(database_url)


def test_catalog_platform_model_alias_routes_match_models_surface(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_site_auth(database_url, site_id="site_catalog", scopes=["catalog:read"])

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    list_response = client.get(
        "/v1/catalog/platform-models",
        headers=build_auth_headers(
            "GET",
            "/v1/catalog/platform-models",
            site_id="site_catalog",
            trace_id="tracecatalogplatform001000000",
        ),
    )
    detail_response = client.get(
        "/v1/catalog/platform-models/gpt-4.1-mini",
        headers=build_auth_headers(
            "GET",
            "/v1/catalog/platform-models/gpt-4.1-mini",
            site_id="site_catalog",
            trace_id="tracecatalogplatform002000000",
        ),
    )
    revision_response = client.get(
        "/v1/catalog/platform-models/revision",
        headers=build_auth_headers(
            "GET",
            "/v1/catalog/platform-models/revision",
            site_id="site_catalog",
            trace_id="tracecatalogplatform003000000",
        ),
    )

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    assert revision_response.status_code == 200
    assert list_response.json()["message"] == "platform models loaded"
    assert detail_response.json()["message"] == "platform model loaded"
    assert revision_response.json()["message"] == "platform models revision loaded"
    assert list_response.json()["data"]["platform_models"]["surface"] == "platform_models"
    assert detail_response.json()["data"]["platform_model"]["surface"] == "platform_models"

    dispose_engine(database_url)


def test_internal_refresh_rejects_replayed_idempotency_marker(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    body = b'{"providers":["openai"]}'
    headers = merge_json_headers(
        build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            idempotency_key="catalog-refresh-replay-001",
            trace_id="tracecatalogreplay0010000000000",
        )
    )

    first_response = client.post(
        "/internal/catalog/refresh",
        content=body,
        headers=headers,
    )
    second_response = client.post(
        "/internal/catalog/refresh",
        content=body,
        headers=headers,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json()["error_code"] == "auth.replay_blocked"

    dispose_engine(database_url)


def test_catalog_routes_require_signed_headers(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    response = client.get("/v1/catalog/models")

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.site_id_required"

    dispose_engine(database_url)


def test_internal_refresh_requires_idempotency_header(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    body = b'{"providers":["openai"]}'
    response = client.post(
        "/internal/catalog/refresh",
        content=body,
        headers=merge_json_headers(
            build_internal_headers(
                internal_token=TEST_INTERNAL_AUTH_TOKEN,
                trace_id="tracecatalog0040000000000000000",
            )
        ),
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.idempotency_required"

    dispose_engine(database_url)


def test_internal_refresh_rejects_public_runtime_hmac_headers(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_catalog",
        scopes=["catalog:refresh", "health:scan"],
    )

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    body = b'{"providers":["openai"]}'
    response = client.post(
        "/internal/catalog/refresh",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/internal/catalog/refresh",
                site_id="site_catalog",
                idempotency_key="catalog-refresh-002",
                trace_id="tracecatalog0050000000000000000",
                body=body,
            )
        ),
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.internal_token_required"

    dispose_engine(database_url)


def test_internal_refresh_requires_internal_auth_configuration(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token="",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    body = b'{"providers":["openai"]}'
    response = client.post(
        "/internal/catalog/refresh",
        content=body,
        headers=merge_json_headers(
            build_internal_headers(
                internal_token=TEST_INTERNAL_AUTH_TOKEN,
                idempotency_key="catalog-refresh-003",
                trace_id="tracecatalog0060000000000000000",
            )
        ),
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "auth.internal_not_configured"

    dispose_engine(database_url)


def test_catalog_routes_do_not_accept_internal_token_only(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    response = client.get(
        "/v1/catalog/models",
        headers=build_internal_headers(internal_token=TEST_INTERNAL_AUTH_TOKEN),
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.site_id_required"

    dispose_engine(database_url)


def test_internal_portal_email_test_sends_message(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    fake_sender = FakePortalEmailSender()

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
    )
    client = TestClient(
        create_app(
            CloudServices(
                settings=settings,
                portal_email_sender=fake_sender,
            )
        )
    )
    public_response = client.patch(
        "/internal/service/admin/service-settings/portal-public",
        json={"public_base_url": "https://cloud.example.com"},
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            idempotency_key="portal-email-public-settings-001",
        ),
    )
    assert public_response.status_code == 200, public_response.text

    response = client.post(
        "/internal/portal/email/test",
        json={"recipient_email": "admin@example.com"},
        headers=merge_json_headers(
            build_internal_headers(
                internal_token=TEST_INTERNAL_AUTH_TOKEN,
                idempotency_key="portal-email-test-001",
                trace_id="tracecatalog0070000000000000000",
            )
        ),
    )

    assert response.status_code == 200
    assert response.json()["data"]["recipient_email"] == "admin@example.com"
    assert response.json()["data"]["portal_url"] == "https://cloud.example.com/portal/login"
    assert fake_sender.test_messages == [
        {
            "recipient_email": "admin@example.com",
            "project_name": "Npcink AI Cloud Test",
            "portal_url": "https://cloud.example.com/portal/login",
        }
    ]

    dispose_engine(database_url)


def test_internal_portal_email_test_requires_configured_sender(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    response = client.post(
        "/internal/portal/email/test",
        json={"recipient_email": "admin@example.com"},
        headers=merge_json_headers(
            build_internal_headers(
                internal_token=TEST_INTERNAL_AUTH_TOKEN,
                idempotency_key="portal-email-test-002",
                trace_id="tracecatalog0080000000000000000",
            )
        ),
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "portal.email_not_configured"

    dispose_engine(database_url)
