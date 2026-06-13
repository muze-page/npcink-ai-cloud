from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.notifications.base import PortalEmailSender
from app.adapters.providers.base import (
    ProviderCatalogSnapshot,
    ProviderExecutionRequest,
    ProviderExecutionResult,
)
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    SITE_ADMIN_STATUS_ACTIVE,
    SiteAdminIdentity,
)
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from app.domain.hosted_model_defaults import FREE_GPT55_MODEL_ID
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
    build_internal_headers,
    build_portal_bearer_headers,
    build_portal_headers,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'portal-routes.sqlite3'}"


def _build_client(
    tmp_path: Path,
    *,
    settings_overrides: dict[str, object] | None = None,
    portal_email_sender: PortalEmailSender | None = None,
    providers: dict[str, Any] | None = None,
) -> tuple[str, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()

    settings_kwargs: dict[str, object] = {
        "project_name": "Magick AI Cloud Test",
        "environment": "test",
        "database_url": database_url,
        "redis_url": "redis://localhost:6379/0",
        "internal_auth_token": TEST_INTERNAL_AUTH_TOKEN,
        "admin_session_secret": TEST_ADMIN_SESSION_SECRET,
        "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
        "debug_local_origin_allowlist": (
            "http://127.0.0.1:8010,http://localhost:8010,http://testserver"
        ),
    }
    settings_kwargs.update(settings_overrides or {})
    settings = Settings(**settings_kwargs)
    client = TestClient(
        create_app(
            CloudServices(
                settings=settings,
                providers=providers or {},
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
        site_admin_ref: str,
        code: str,
        expires_in_seconds: int,
        project_name: str,
        locale: str = "zh-CN",
    ) -> None:
        self.messages.append(
            {
                "kind": "login_code",
                "recipient_email": recipient_email,
                "site_admin_ref": site_admin_ref,
                "code": code,
                "expires_in_seconds": expires_in_seconds,
                "project_name": project_name,
                "locale": locale,
            }
        )


class _PortalDraftProvider:
    provider_id = "fake_llm"
    display_name = "Fake LLM"
    adapter_type = "fake"

    def __init__(self) -> None:
        self.requests: list[ProviderExecutionRequest] = []

    def fetch_catalog(self) -> ProviderCatalogSnapshot:
        raise NotImplementedError

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        self.requests.append(request)
        return ProviderExecutionResult(
            output={
                "output_text": json.dumps(
                    {
                        "operator_summary": "LLM summarized operations and usage pressure.",
                        "support_draft": "Internal support draft is not shown in Portal.",
                        "operator_next_step": "inspect_usage_and_runtime_health",
                        "safety_note": "AI analysis only; no WordPress write is allowed.",
                    }
                )
            },
            latency_ms=15,
            tokens_in=42,
            tokens_out=21,
            cost=0.0025,
        )


def _decode_customer_key(value: str) -> dict[str, str]:
    assert value.startswith("mak1_")
    encoded = value[5:]
    padding = "=" * ((4 - len(encoded) % 4) % 4)
    decoded = base64.urlsafe_b64decode(f"{encoded}{padding}".encode("ascii")).decode("utf-8")
    payload = json.loads(decoded)
    assert isinstance(payload, dict)
    return payload


def _request_portal_login_code(
    client: TestClient,
    *,
    email: str,
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    request_headers = dict(headers or {})
    if (
        str(request_headers.get("x-magick-debug-portal-link") or "").strip() == "1"
        and "x-magick-dev-login-code" not in request_headers
    ):
        request_headers["x-magick-dev-login-code"] = "1"
    response = client.post(
        "/portal/v1/auth/code/request",
        json={"email": email},
        headers=request_headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _verify_portal_login_code(
    client: TestClient,
    *,
    email: str,
    code: str,
) -> dict[str, object]:
    response = client.post(
        "/portal/v1/auth/code/verify",
        json={"email": email, "code": code},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _grant_site_admin_access(
    client: TestClient,
    *,
    site_id: str,
    email: str,
    status: str = "active",
    idempotency_key: str = "portal-site-admin-access-001",
) -> None:
    response = client.post(
        f"/internal/service/sites/{site_id}/site-admin-access",
        json={"email": email, "status": status},
        headers=build_internal_headers(idempotency_key=idempotency_key),
    )
    assert response.status_code == 200, response.text


def test_portal_issue_rotate_list_and_revoke_site_key(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal", "name": "Portal Account"},
        headers=build_internal_headers(idempotency_key="portal-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal",
            "account_id": "acct_portal",
            "name": "Portal Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-site-001"),
    )
    _grant_site_admin_access(
        client,
        site_id="site_portal",
        email="portal-admin@example.com",
        idempotency_key="portal-site-admin-access-admin-001",
    )

    issue_response = client.post(
        "/portal/v1/sites/site_portal/api-keys",
        json={
            "label": "Production Key",
            "scopes": ["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
        },
        headers=build_portal_headers(idempotency_key="portal-issue-001"),
    )
    assert issue_response.status_code == 200
    issue_data = issue_response.json()["data"]
    assert issue_data["site_id"] == "site_portal"
    assert issue_data["status"] == "active"
    assert issue_data["cloud_api_key"].startswith("mak1_")
    decoded_issue_key = _decode_customer_key(issue_data["cloud_api_key"])
    assert decoded_issue_key["site_id"] == "site_portal"
    assert decoded_issue_key["key_id"] == issue_data["key_id"]
    assert isinstance(decoded_issue_key["secret"], str) and decoded_issue_key["secret"] != ""
    assert "secret" not in issue_data

    site_summary_response = client.get(
        "/portal/v1/sites/site_portal/summary",
        headers=build_portal_headers(),
    )
    assert site_summary_response.status_code == 200
    assert site_summary_response.json()["data"]["site"]["status"] == "active"

    list_response = client.get(
        "/portal/v1/sites/site_portal/api-keys",
        headers=build_portal_headers(),
    )
    assert list_response.status_code == 200
    list_items = list_response.json()["data"]["items"]
    assert len(list_items) == 1
    assert list_items[0]["key_id"] == issue_data["key_id"]
    assert "cloud_api_key" not in list_items[0]
    assert "secret" not in list_items[0]
    assert list_response.json()["data"]["pagination"] == {
        "limit": 20,
        "offset": 0,
        "total": 1,
        "has_more": False,
        "next_offset": None,
    }
    assert list_response.json()["data"]["sort"] == {
        "created_at": "desc",
        "key_id": "desc",
    }

    rotate_response = client.post(
        f"/portal/v1/sites/site_portal/api-keys/{issue_data['key_id']}/rotate",
        json={"label": "Production Key Rotated"},
        headers=build_portal_headers(idempotency_key="portal-rotate-001"),
    )
    assert rotate_response.status_code == 200
    rotate_data = rotate_response.json()["data"]
    assert rotate_data["previous"]["status"] == "revoked"
    assert rotate_data["current"]["status"] == "active"
    assert rotate_data["current"]["cloud_api_key"].startswith("mak1_")
    decoded_rotated_key = _decode_customer_key(rotate_data["current"]["cloud_api_key"])
    assert decoded_rotated_key["site_id"] == "site_portal"
    assert decoded_rotated_key["key_id"] == rotate_data["current"]["key_id"]
    assert decoded_rotated_key["key_id"] != rotate_data["previous"]["key_id"]
    assert "secret" not in rotate_data["current"]

    revoke_response = client.post(
        f"/portal/v1/sites/site_portal/api-keys/{rotate_data['current']['key_id']}/revoke",
        headers=build_portal_headers(idempotency_key="portal-revoke-001"),
    )
    assert revoke_response.status_code == 200
    assert revoke_response.json()["data"]["status"] == "revoked"
    assert "cloud_api_key" not in revoke_response.json()["data"]

    audit_response = client.get(
        "/internal/service/audit-events?site_id=site_portal&limit=20",
        headers=build_internal_headers(),
    )
    assert audit_response.status_code == 200
    audit_items = audit_response.json()["data"]["items"]
    portal_issue_audit = next(
        item for item in audit_items if item["event_kind"] == "site_key.issue"
    )
    portal_rotate_audit = next(
        item for item in audit_items if item["event_kind"] == "site_key.rotate"
    )
    portal_revoke_audit = next(
        item for item in audit_items if item["event_kind"] == "site_key.revoke"
    )
    assert portal_issue_audit["actor_kind"] == "site_admin"
    assert portal_rotate_audit["actor_kind"] == "site_admin"
    assert portal_revoke_audit["actor_kind"] == "site_admin"
    assert portal_issue_audit["actor_ref"] == "site_admin:portal-admin@example.com"

    dispose_engine(database_url)


def test_portal_site_keys_support_limit_offset_and_desc_sort(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_page", "name": "Portal Page Account"},
        headers=build_internal_headers(idempotency_key="portal-page-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_page",
            "account_id": "acct_portal_page",
            "name": "Portal Page Site",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="portal-page-site-001"),
    )
    _grant_site_admin_access(
        client,
        site_id="site_portal_page",
        email="portal-page@example.com",
        idempotency_key="portal-page-site-admin-access-001",
    )

    for index in range(3):
        client.post(
            "/internal/service/sites/site_portal_page/keys",
            json={
                "key_id": f"key_portal_page_{index}",
                "secret": f"portal-page-secret-{index}",
                "scopes": ["runtime:read"],
                "label": f"portal-page-{index}",
            },
            headers=build_internal_headers(idempotency_key=f"portal-page-key-{index:03d}"),
        )

    response = client.get(
        "/portal/v1/sites/site_portal_page/api-keys?limit=2&offset=0",
        headers=build_portal_headers(site_admin_ref="site_admin:portal-page@example.com"),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert [item["key_id"] for item in payload["items"]] == [
        "key_portal_page_2",
        "key_portal_page_1",
    ]
    assert payload["pagination"] == {
        "limit": 2,
        "offset": 0,
        "total": 3,
        "has_more": True,
        "next_offset": 2,
    }
    assert payload["sort"] == {"created_at": "desc", "key_id": "desc"}

    dispose_engine(database_url)


def test_portal_issue_site_key_normalizes_legacy_scope_aliases(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_alias", "name": "Portal Alias Account"},
        headers=build_internal_headers(idempotency_key="portal-alias-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_alias",
            "account_id": "acct_portal_alias",
            "name": "Portal Alias Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-alias-site-001"),
    )
    _grant_site_admin_access(
        client,
        site_id="site_portal_alias",
        email="portal-alias@example.com",
        idempotency_key="portal-alias-site-admin-access-001",
    )

    issue_response = client.post(
        "/portal/v1/sites/site_portal_alias/api-keys",
        json={"label": "Alias Key", "scopes": ["read", "execute"]},
        headers=build_portal_headers(
            site_admin_ref="site_admin:portal-alias@example.com",
            idempotency_key="portal-alias-issue-001",
        ),
    )

    assert issue_response.status_code == 200
    scopes = set(issue_response.json()["data"]["scopes"])
    assert scopes == {
        "catalog:read",
        "runtime:resolve",
        "runtime:execute",
        "runtime:read",
        "stats:read",
        "entitlement:read",
    }

    dispose_engine(database_url)


def test_portal_routes_fail_closed_without_portal_auth(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    response = client.get("/portal/v1/sites/site_portal/api-keys")

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.portal_session_required"

    dispose_engine(database_url)


def test_portal_routes_require_authenticated_session(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    response = client.get(
        "/portal/v1/sites/site_portal/api-keys",
        headers={"X-Magick-Portal-Site-Admin-Ref": "site_admin:portal-admin@example.com"},
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.portal_session_required"

    dispose_engine(database_url)


def test_portal_routes_require_portal_auth_configuration(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        portal_jwt_secret=None,
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    response = client.get(
        "/portal/v1/sites/site_portal/api-keys",
        headers=build_portal_headers(),
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "auth.portal_not_configured"

    dispose_engine(database_url)


def test_portal_ai_insights_are_manual_cached_and_redacted(tmp_path: Path) -> None:
    provider = _PortalDraftProvider()
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "internal_ops_summarizer_provider_allowlist": provider.provider_id,
        },
        providers={provider.provider_id: provider},
    )

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_ai", "name": "Portal AI Account"},
        headers=build_internal_headers(idempotency_key="portal-ai-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_ai",
            "account_id": "acct_portal_ai",
            "name": "Portal AI Site",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="portal-ai-site-001"),
    )
    _grant_site_admin_access(
        client,
        site_id="site_portal_ai",
        email="portal-admin@example.com",
        idempotency_key="portal-ai-site-admin-access-001",
    )

    initial_history = client.get(
        "/portal/v1/sites/site_portal_ai/ai-insights/history",
        headers=build_portal_headers(),
    )
    assert initial_history.status_code == 200
    assert initial_history.json()["data"]["items"] == []
    assert len(provider.requests) == 0

    first = client.post(
        "/portal/v1/sites/site_portal_ai/ai-insights/analyze",
        json={"force_refresh": False},
        headers=build_portal_headers(idempotency_key="portal-ai-analyze-001"),
    )
    assert first.status_code == 200, first.text
    first_data = first.json()["data"]
    analysis = first_data["analysis"]
    assert analysis["generation"]["mode"] == "llm"
    assert analysis["generation"]["cache_status"] == "miss"
    assert analysis["ai_disclosure"]["generated_by_ai"] is True
    assert analysis["ai_disclosure"]["brand_label"] == "Magick AI"
    assert analysis["agent_handoff"]["agent_id"] == "internal_ops_advisor_agent"
    assert analysis["agent_handoff"]["handoff_type"] == "operator_recommendation"
    assert analysis["agent_handoff"]["requires_operator_review"] is True
    assert analysis["agent_handoff"]["direct_wordpress_write"] is False
    assert "automatic_commercial_state_mutation" in analysis["agent_handoff"]["forbidden_actions"]
    assert analysis["agent_registry_metadata"]["agent_id"] == ("internal_ops_advisor_agent")
    assert (
        analysis["agent_registry_metadata"]["agent_role"] == analysis["agent_handoff"]["agent_role"]
    )
    assert analysis["agent_registry_metadata"]["direct_wordpress_write"] is False
    assert "cloud_workflow_truth" in analysis["agent_registry_metadata"]["forbidden_actions"]
    assert first_data["safety"] == {
        "manual_trigger_required": True,
        "prompt_saved": False,
        "raw_payload_saved": False,
        "wordpress_write_allowed": False,
        "provider_visible": False,
        "model_visible": False,
        "token_usage_visible": False,
        "cost_visible": False,
        "cache_key_visible": False,
        "customer_article_generation_allowed": False,
    }
    serialized = json.dumps(first_data)
    assert "provider_id" not in serialized
    assert "model_id" not in serialized
    assert "tokens_in" not in serialized
    assert "tokens_out" not in serialized
    assert '"cost":' not in serialized
    assert '"cache_key":' not in serialized
    assert "source_context" not in serialized
    assert len(provider.requests) == 1
    assert provider.requests[0].model_id == FREE_GPT55_MODEL_ID

    second = client.post(
        "/portal/v1/sites/site_portal_ai/ai-insights/analyze",
        json={"force_refresh": False},
        headers=build_portal_headers(idempotency_key="portal-ai-analyze-002"),
    )
    assert second.status_code == 200, second.text
    second_data = second.json()["data"]
    assert second_data["analysis"]["generation"]["mode"] == "llm_cached"
    assert second_data["analysis"]["generation"]["cache_status"] == "hit"
    assert second_data["analysis"]["generation"]["cache_hit"] is True
    assert len(provider.requests) == 1

    history = client.get(
        "/portal/v1/sites/site_portal_ai/ai-insights/history",
        headers=build_portal_headers(),
    )
    assert history.status_code == 200
    history_data = history.json()["data"]
    assert len(history_data["items"]) == 1
    assert history_data["items"][0]["ai_disclosure"]["generated_by_ai"] is True
    assert history_data["items"][0]["agent_handoff"]["agent_id"] == ("internal_ops_advisor_agent")
    assert history_data["items"][0]["agent_registry_metadata"]["agent_id"] == (
        "internal_ops_advisor_agent"
    )
    history_serialized = json.dumps(history_data)
    assert "provider_id" not in history_serialized
    assert "model_id" not in history_serialized
    assert "tokens_in" not in history_serialized
    assert "tokens_out" not in history_serialized
    assert '"cost":' not in history_serialized
    assert '"cache_key":' not in history_serialized

    dispose_engine(database_url)


def test_portal_ai_insights_reject_other_site(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_ai_private", "name": "Portal AI Private"},
        headers=build_internal_headers(idempotency_key="portal-ai-private-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_ai_private",
            "account_id": "acct_portal_ai_private",
            "name": "Portal AI Private Site",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="portal-ai-private-site-001"),
    )

    response = client.post(
        "/portal/v1/sites/site_portal_ai_private/ai-insights/analyze",
        json={"force_refresh": False},
        headers=build_portal_headers(site_admin_ref="site_admin:outsider@example.com"),
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "service.site_admin_access_required"

    dispose_engine(database_url)


def test_portal_unknown_site_admin_cannot_access_site_keys(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_private", "name": "Portal Account Private"},
        headers=build_internal_headers(idempotency_key="portal-private-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_private",
            "account_id": "acct_portal_private",
            "name": "Portal Site Private",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-private-site-001"),
    )
    client.post(
        "/internal/service/sites/site_portal_private/activate",
        headers=build_internal_headers(idempotency_key="portal-private-site-activate-001"),
    )

    response = client.get(
        "/portal/v1/sites/site_portal_private/api-keys",
        headers=build_portal_headers(site_admin_ref="site_admin:outsider@example.com"),
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "service.site_admin_access_required"

    dispose_engine(database_url)


def test_disabled_site_admin_cannot_read_or_write(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_disabled", "name": "Portal Disabled Account"},
        headers=build_internal_headers(idempotency_key="portal-disabled-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_disabled",
            "account_id": "acct_portal_disabled",
            "name": "Portal Disabled Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-disabled-site-001"),
    )
    client.post(
        "/internal/service/sites/site_portal_disabled/activate",
        headers=build_internal_headers(idempotency_key="portal-disabled-site-activate-001"),
    )
    _grant_site_admin_access(
        client,
        site_id="site_portal_disabled",
        email="portal-disabled@example.com",
        status="disabled",
        idempotency_key="portal-disabled-site-admin-access-001",
    )

    read_response = client.get(
        "/portal/v1/sites/site_portal_disabled/summary",
        headers=build_portal_headers(site_admin_ref="site_admin:portal-disabled@example.com"),
    )
    assert read_response.status_code == 403
    assert read_response.json()["error_code"] == "service.site_admin_access_required"

    write_response = client.post(
        "/portal/v1/sites/site_portal_disabled/api-keys",
        json={"label": "Disabled Write Attempt"},
        headers=build_portal_headers(
            site_admin_ref="site_admin:portal-disabled@example.com",
            idempotency_key="portal-disabled-write-denied-001",
        ),
    )
    assert write_response.status_code == 403
    assert write_response.json()["error_code"] == "service.site_admin_access_required"

    sites_response = client.get(
        "/portal/v1/sites",
        headers=build_portal_headers(site_admin_ref="site_admin:portal-disabled@example.com"),
    )
    assert sites_response.status_code == 200
    assert sites_response.json()["data"]["items"] == []

    dispose_engine(database_url)


def test_portal_jwt_allows_site_admin_access_without_dev_headers(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_jwt_issuer": "magick-cloud-portal",
            "portal_jwt_audience": "magick-cloud-customers",
        },
    )

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_jwt", "name": "Portal Account JWT"},
        headers=build_internal_headers(idempotency_key="portal-jwt-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_jwt",
            "account_id": "acct_portal_jwt",
            "name": "Portal Site JWT",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-jwt-site-001"),
    )
    client.post(
        "/internal/service/sites/site_portal_jwt/activate",
        headers=build_internal_headers(idempotency_key="portal-jwt-site-activate-001"),
    )
    _grant_site_admin_access(
        client,
        site_id="site_portal_jwt",
        email="portal-jwt@example.com",
        idempotency_key="portal-jwt-site-admin-access-001",
    )

    response = client.post(
        "/portal/v1/sites/site_portal_jwt/api-keys",
        json={"label": "JWT Key"},
        headers=build_portal_bearer_headers(
            site_admin_ref="site_admin:portal-jwt@example.com",
            issuer="magick-cloud-portal",
            audience="magick-cloud-customers",
            idempotency_key="portal-jwt-issue-001",
        ),
    )

    assert response.status_code == 200
    assert response.json()["data"]["cloud_api_key"].startswith("mak1_")

    dispose_engine(database_url)


def test_portal_jwt_bearer_request_for_unknown_site_returns_not_found(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
        },
    )

    response = client.get(
        "/portal/v1/sites/site_portal/api-keys",
        headers=build_portal_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "service.site_not_found"

    dispose_engine(database_url)


def test_portal_jwt_rejects_expired_token(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
        },
    )

    response = client.get(
        "/portal/v1/sites/site_portal/api-keys",
        headers=build_portal_bearer_headers(
            expires_at=datetime.now(UTC) - timedelta(minutes=5),
        ),
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.portal_token_expired"

    dispose_engine(database_url)


def test_portal_auth_login_code_request_and_verify_with_jwt(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_jwt_issuer": "magick-cloud-portal",
            "portal_jwt_audience": "magick-cloud-customers",
            "portal_session_ttl_seconds": 900,
            "portal_login_code_ttl_seconds": 300,
        },
    )

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_auth", "name": "Portal Auth Account"},
        headers=build_internal_headers(idempotency_key="portal-auth-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_auth",
            "account_id": "acct_portal_auth",
            "name": "Portal Auth Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-auth-site-001"),
    )
    client.post(
        "/internal/service/sites/site_portal_auth/activate",
        headers=build_internal_headers(idempotency_key="portal-auth-site-activate-001"),
    )
    client.post(
        "/internal/service/sites/site_portal_auth/site-admin-access",
        json={"email": "portal-auth@example.com"},
        headers=build_internal_headers(idempotency_key="portal-auth-site-admin-access-001"),
    )

    request_data = _request_portal_login_code(
        client,
        email="portal-auth@example.com",
        headers={"x-magick-debug-portal-link": "1"},
    )
    assert request_data["expires_in_seconds"] == 300
    assert request_data["code"] != ""

    consume_data = _verify_portal_login_code(
        client,
        email="portal-auth@example.com",
        code=str(request_data["code"]),
    )
    assert consume_data["site_admin_ref"] == "site_admin:portal-auth@example.com"
    assert consume_data["auth_mode"] == "jwt"
    assert consume_data["session"]["state"] == "active"
    assert consume_data["session"]["transport"] == "cookie"
    assert consume_data["session"]["expires_at"] != ""

    session_response = client.get("/portal/v1/session")
    assert session_response.status_code == 200
    assert session_response.json()["data"]["site_admin_ref"] == "site_admin:portal-auth@example.com"
    assert session_response.json()["data"]["session"]["revocable"] is True

    with get_session(database_url) as session:
        identity = session.scalar(
            select(SiteAdminIdentity).where(
                SiteAdminIdentity.site_admin_ref == "site_admin:portal-auth@example.com"
            )
        )
        assert identity is not None
        assert identity.status == SITE_ADMIN_STATUS_ACTIVE
        assert identity.last_login_at is not None


def test_portal_removed_obsolete_auth_routes_return_not_found(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    removed_code_request = client.post(
        "/portal/v1/auth/magic-link/request",
        json={"email": "portal-auth@example.com"},
    )
    assert removed_code_request.status_code == 404

    removed_token_consume = client.post(
        "/portal/v1/auth/magic-link/consume",
        json={"token": "obsolete-token"},
    )
    assert removed_token_consume.status_code == 404

    removed_provider_login = client.get("/portal/v1/auth/oidc/login")
    assert removed_provider_login.status_code == 404

    removed_provider_callback = client.get(
        "/portal/v1/auth/oidc/callback?code=oidc-code&state=oidc-state",
        follow_redirects=False,
    )
    assert removed_provider_callback.status_code == 404

    revoke_response = client.post("/portal/v1/session/revoke")
    assert revoke_response.status_code == 200

    revoked_session_response = client.get("/portal/v1/session")
    assert revoked_session_response.status_code == 401
    assert revoked_session_response.json()["error_code"] == "auth.portal_session_required"

    dispose_engine(database_url)


def test_portal_login_code_request_uses_real_sender_when_configured(
    tmp_path: Path,
) -> None:
    fake_sender = FakePortalEmailSender()
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_public_base_url": "https://cloud.example.com",
        },
        portal_email_sender=fake_sender,
    )

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_mail", "name": "Portal Mail Account"},
        headers=build_internal_headers(idempotency_key="portal-mail-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_mail",
            "account_id": "acct_portal_mail",
            "name": "Portal Mail Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-mail-site-001"),
    )
    client.post(
        "/internal/service/sites/site_portal_mail/activate",
        headers=build_internal_headers(idempotency_key="portal-mail-site-activate-001"),
    )
    _grant_site_admin_access(
        client,
        site_id="site_portal_mail",
        email="portal-mail@example.com",
        idempotency_key="portal-mail-site-admin-access-001",
    )

    response = client.post(
        "/portal/v1/auth/code/request",
        json={"email": "portal-mail@example.com", "locale": "zh-CN"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["delivery"] == "email"
    assert response.json()["data"]["code"] == ""
    assert len(fake_sender.messages) == 1
    assert fake_sender.messages[0]["kind"] == "login_code"
    assert fake_sender.messages[0]["locale"] == "zh-CN"
    assert len(str(fake_sender.messages[0]["code"])) == 6

    dispose_engine(database_url)


def test_portal_login_code_request_masks_missing_site_admin_access(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
        },
    )

    response = client.post(
        "/portal/v1/auth/code/request",
        json={"email": "outsider@example.com"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["delivery"] == "email"
    assert response.json()["data"]["code"] == ""

    dispose_engine(database_url)


def test_portal_login_code_request_accepts_forwarded_host_with_port(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_jwt_issuer": "magick-cloud-portal",
            "portal_jwt_audience": "magick-cloud-customers",
            "portal_login_code_ttl_seconds": 300,
            "portal_public_base_url": None,
        },
    )

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_forwarded", "name": "Portal Forwarded Account"},
        headers=build_internal_headers(idempotency_key="portal-forwarded-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_forwarded",
            "account_id": "acct_portal_forwarded",
            "name": "Portal Forwarded Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-forwarded-site-001"),
    )
    client.post(
        "/internal/service/sites/site_portal_forwarded/activate",
        headers=build_internal_headers(idempotency_key="portal-forwarded-site-activate-001"),
    )
    _grant_site_admin_access(
        client,
        site_id="site_portal_forwarded",
        email="portal-forwarded@example.com",
        idempotency_key="portal-forwarded-site-admin-access-001",
    )

    response = client.post(
        "/portal/v1/auth/code/request",
        json={"email": "portal-forwarded@example.com"},
        headers={
            "origin": "http://127.0.0.1:8010",
            "referer": "http://127.0.0.1:8010/",
            "host": "127.0.0.1",
            "x-forwarded-host": "127.0.0.1:8010",
            "x-forwarded-proto": "http",
            "x-magick-debug-portal-link": "1",
            "x-magick-dev-login-code": "1",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["delivery"] == "development_code"
    assert len(str(response.json()["data"]["code"])) == 6

    dispose_engine(database_url)


def test_portal_login_code_request_accepts_localhost_loopback_alias(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_jwt_issuer": "magick-cloud-portal",
            "portal_jwt_audience": "magick-cloud-customers",
            "portal_login_code_ttl_seconds": 300,
            "portal_public_base_url": "http://127.0.0.1:8010",
            "environment": "development",
        },
    )

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_localhost", "name": "Portal Localhost Account"},
        headers=build_internal_headers(idempotency_key="portal-localhost-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_localhost",
            "account_id": "acct_portal_localhost",
            "name": "Portal Localhost Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-localhost-site-001"),
    )
    client.post(
        "/internal/service/sites/site_portal_localhost/activate",
        headers=build_internal_headers(idempotency_key="portal-localhost-site-activate-001"),
    )
    _grant_site_admin_access(
        client,
        site_id="site_portal_localhost",
        email="portal-localhost@example.com",
        idempotency_key="portal-localhost-site-admin-access-001",
    )

    response = client.post(
        "/portal/v1/auth/code/request",
        json={"email": "portal-localhost@example.com"},
        headers={
            "origin": "http://localhost:8010",
            "referer": "http://localhost:8010/",
            "host": "localhost:8010",
            "x-forwarded-host": "localhost:8010",
            "x-forwarded-proto": "http",
            "x-magick-debug-portal-link": "1",
            "x-magick-dev-login-code": "1",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["delivery"] == "development_code"
    assert len(str(response.json()["data"]["code"])) == 6

    dispose_engine(database_url)


def test_portal_login_code_request_skips_rate_limit_for_local_debug_loopback(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_jwt_issuer": "magick-cloud-portal",
            "portal_jwt_audience": "magick-cloud-customers",
            "portal_login_code_ttl_seconds": 300,
            "portal_public_base_url": "http://127.0.0.1:8010",
            "environment": "development",
        },
    )

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_debug", "name": "Portal Debug Account"},
        headers=build_internal_headers(idempotency_key="portal-debug-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_debug",
            "account_id": "acct_portal_debug",
            "name": "Portal Debug Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-debug-site-001"),
    )
    client.post(
        "/internal/service/sites/site_portal_debug/activate",
        headers=build_internal_headers(idempotency_key="portal-debug-site-activate-001"),
    )
    _grant_site_admin_access(
        client,
        site_id="site_portal_debug",
        email="portal-debug@example.com",
        idempotency_key="portal-debug-site-admin-access-001",
    )

    debug_headers = {
        "origin": "http://127.0.0.1:8010",
        "referer": "http://127.0.0.1:8010/",
        "host": "127.0.0.1:8010",
        "x-forwarded-host": "127.0.0.1:8010",
        "x-forwarded-proto": "http",
        "x-magick-debug-portal-link": "1",
        "x-magick-dev-login-code": "1",
    }

    for _ in range(5):
        response = client.post(
            "/portal/v1/auth/code/request",
            json={"email": "portal-debug@example.com"},
            headers=debug_headers,
        )
        assert response.status_code == 200
        assert response.json()["data"]["delivery"] == "development_code"
        assert len(str(response.json()["data"]["code"])) == 6

    dispose_engine(database_url)


def test_portal_session_sites_selection_and_logout_support_cookie_session(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_jwt_issuer": "magick-cloud-portal",
            "portal_jwt_audience": "magick-cloud-customers",
        },
    )

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_session", "name": "Portal Session Account"},
        headers=build_internal_headers(idempotency_key="portal-session-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_session",
            "account_id": "acct_portal_session",
            "name": "Portal Session Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-session-site-001"),
    )
    client.post(
        "/internal/service/sites/site_portal_session/activate",
        headers=build_internal_headers(idempotency_key="portal-session-site-activate-001"),
    )
    _grant_site_admin_access(
        client,
        site_id="site_portal_session",
        email="portal-session@example.com",
        idempotency_key="portal-session-site-admin-access-001",
    )

    request_data = _request_portal_login_code(
        client,
        email="portal-session@example.com",
        headers={"x-magick-debug-portal-link": "1"},
    )
    _verify_portal_login_code(
        client,
        email="portal-session@example.com",
        code=str(request_data["code"]),
    )

    session_response = client.get("/portal/v1/session")
    assert session_response.status_code == 200
    session_data = session_response.json()["data"]
    assert session_data["site_admin_ref"] == "site_admin:portal-session@example.com"
    assert session_data["site_id"] == "site_portal_session"
    assert session_data["account_id"] == "acct_portal_session"
    assert session_data["identity_type"] == "site_admin"
    assert session_data["role"] == "site_admin"
    assert session_data["accounts"][0]["account_id"] == "acct_portal_session"
    assert session_data["site"]["site_id"] == "site_portal_session"

    sites_response = client.get("/portal/v1/sites")
    assert sites_response.status_code == 200
    assert len(sites_response.json()["data"]["items"]) == 1

    select_response = client.post(
        "/portal/v1/session/site",
        json={"site_id": "site_portal_session"},
    )
    assert select_response.status_code == 200
    assert select_response.json()["data"]["site_id"] == "site_portal_session"

    logout_response = client.post("/portal/v1/logout")
    assert logout_response.status_code == 200

    expired_session_response = client.get("/portal/v1/session")
    assert expired_session_response.status_code == 401
    assert expired_session_response.json()["error_code"] == "auth.portal_session_required"

    dispose_engine(database_url)


def test_portal_site_key_routes_allow_cookie_session_after_login_code_verification(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_jwt_issuer": "magick-cloud-portal",
            "portal_jwt_audience": "magick-cloud-customers",
            "portal_login_code_ttl_seconds": 300,
        },
    )

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_cookie_keys", "name": "Portal Cookie Keys Account"},
        headers=build_internal_headers(idempotency_key="portal-cookie-keys-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_cookie_keys",
            "account_id": "acct_portal_cookie_keys",
            "name": "Portal Cookie Keys Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-cookie-keys-site-001"),
    )
    client.post(
        "/internal/service/sites/site_portal_cookie_keys/activate",
        headers=build_internal_headers(idempotency_key="portal-cookie-keys-site-activate-001"),
    )
    _grant_site_admin_access(
        client,
        site_id="site_portal_cookie_keys",
        email="portal-cookie-keys@example.com",
        idempotency_key="portal-cookie-keys-site-admin-access-001",
    )

    request_data = _request_portal_login_code(
        client,
        email="portal-cookie-keys@example.com",
        headers={"x-magick-debug-portal-link": "1"},
    )
    _verify_portal_login_code(
        client,
        email="portal-cookie-keys@example.com",
        code=str(request_data["code"]),
    )

    issue_response = client.post(
        "/portal/v1/sites/site_portal_cookie_keys/api-keys",
        json={
            "label": "Cookie Key",
            "scopes": ["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
        },
        headers={"origin": "http://testserver", "referer": "http://testserver/"},
    )
    assert issue_response.status_code == 200
    issue_data = issue_response.json()["data"]
    assert issue_data["site_id"] == "site_portal_cookie_keys"
    assert issue_data["status"] == "active"

    list_response = client.get("/portal/v1/sites/site_portal_cookie_keys/api-keys")
    assert list_response.status_code == 200
    list_items = list_response.json()["data"]["items"]
    assert len(list_items) == 1
    assert list_items[0]["key_id"] == issue_data["key_id"]

    dispose_engine(database_url)


def test_portal_cookie_write_requires_same_origin(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
        },
    )

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_origin", "name": "Portal Origin Account"},
        headers=build_internal_headers(idempotency_key="portal-origin-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_origin",
            "account_id": "acct_portal_origin",
            "name": "Portal Origin Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-origin-site-001"),
    )
    client.post(
        "/internal/service/sites/site_portal_origin/activate",
        headers=build_internal_headers(idempotency_key="portal-origin-site-activate-001"),
    )
    _grant_site_admin_access(
        client,
        site_id="site_portal_origin",
        email="portal-origin@example.com",
        idempotency_key="portal-origin-site-admin-access-001",
    )

    request_response = client.post(
        "/portal/v1/auth/code/request",
        json={"email": "portal-origin@example.com"},
        headers={
            "x-magick-debug-portal-link": "1",
            "x-magick-dev-login-code": "1",
        },
    )
    code = request_response.json()["data"]["code"]
    consume_response = client.post(
        "/portal/v1/auth/code/verify",
        json={"email": "portal-origin@example.com", "code": code},
    )
    assert consume_response.status_code == 200

    response = client.post(
        "/portal/v1/session/site",
        json={"site_id": "site_portal_origin"},
        headers={"origin": "", "referer": ""},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "auth.origin_required"

    dispose_engine(database_url)


def test_portal_debug_bypass_is_disabled_in_production_even_with_allowlist(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "environment": "production",
            "portal_public_base_url": "https://cloud.example.com",
            "portal_email_smtp_host": "smtp.example.com",
            "portal_email_from_email": "noreply@example.com",
            "admin_bootstrap_token": "b" * 32,
            "trusted_host_allowlist": "testserver,cloud.example.com",
            "debug_local_origin_allowlist": "http://127.0.0.1:8010",
        },
    )

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_prod_origin", "name": "Portal Prod Origin Account"},
        headers=build_internal_headers(idempotency_key="portal-prod-origin-account-001"),
    )
    response = client.post(
        "/portal/v1/auth/code/request",
        json={"email": "portal-prod-origin@example.com"},
        headers={
            "origin": "http://127.0.0.1:8010",
            "referer": "http://127.0.0.1:8010/",
            "x-magick-debug-portal-link": "1",
        },
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "auth.origin_forbidden"

    dispose_engine(database_url)


def test_portal_header_authenticated_write_skips_same_origin_guard(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_header_origin", "name": "Portal Header Origin"},
        headers=build_internal_headers(idempotency_key="portal-header-origin-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_header_origin",
            "account_id": "acct_portal_header_origin",
            "name": "Portal Header Origin Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-header-origin-site-001"),
    )
    client.post(
        "/internal/service/sites/site_portal_header_origin/activate",
        headers=build_internal_headers(idempotency_key="portal-header-origin-site-activate-001"),
    )
    _grant_site_admin_access(
        client,
        site_id="site_portal_header_origin",
        email="portal-admin@example.com",
        idempotency_key="portal-header-origin-site-admin-access-001",
    )

    response = client.post(
        "/portal/v1/sites/site_portal_header_origin/api-keys",
        json={"label": "Header Auth Key", "scopes": ["runtime:execute"]},
        headers={
            **build_portal_headers(idempotency_key="portal-header-origin-key-001"),
            "origin": "",
            "referer": "",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["key_id"].startswith("key_")

    dispose_engine(database_url)


def test_portal_session_route_supports_jwt_with_session_cookies(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_jwt_issuer": "magick-cloud-portal",
            "portal_jwt_audience": "magick-cloud-customers",
        },
    )

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_session_jwt", "name": "Portal Session JWT"},
        headers=build_internal_headers(idempotency_key="portal-session-jwt-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_session_jwt",
            "account_id": "acct_portal_session_jwt",
            "name": "Portal Session JWT Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-session-jwt-site-001"),
    )
    client.post(
        "/internal/service/sites/site_portal_session_jwt/activate",
        headers=build_internal_headers(idempotency_key="portal-session-jwt-site-activate-001"),
    )
    _grant_site_admin_access(
        client,
        site_id="site_portal_session_jwt",
        email="portal-session-jwt@example.com",
        idempotency_key="portal-session-jwt-site-admin-access-001",
    )

    response = client.get(
        "/portal/v1/session",
        headers=build_portal_bearer_headers(
            site_admin_ref="site_admin:portal-session-jwt@example.com",
            issuer="magick-cloud-portal",
            audience="magick-cloud-customers",
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["site_admin_ref"] == "site_admin:portal-session-jwt@example.com"
    assert data["site_id"] == "site_portal_session_jwt"
    assert data["auth_mode"] == "jwt"
    assert len(data["sites"]) == 1
    assert data["session"]["transport"] == "header"
    assert data["session"]["revocable"] is False
    assert data["session"]["expires_at"] != ""

    dispose_engine(database_url)


def test_portal_summary_usage_entitlements_and_audit_routes(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_reads", "name": "Portal Reads Account"},
        headers=build_internal_headers(idempotency_key="portal-reads-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_reads",
            "account_id": "acct_portal_reads",
            "name": "Portal Reads Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-reads-site-001"),
    )
    client.post(
        "/internal/service/sites/site_portal_reads/activate",
        headers=build_internal_headers(idempotency_key="portal-reads-site-activate-001"),
    )
    _grant_site_admin_access(
        client,
        site_id="site_portal_reads",
        email="portal-reads@example.com",
        idempotency_key="portal-reads-site-admin-access-001",
    )
    client.post(
        "/internal/service/plans",
        json={"plan_id": "plan_portal_reads", "name": "Portal Reads Plan"},
        headers=build_internal_headers(idempotency_key="portal-reads-plan-001"),
    )
    client.post(
        "/internal/service/plans/plan_portal_reads/versions",
        json={
            "plan_version_id": "plan_portal_reads_v1",
            "version_label": "v1",
            "policy": {
                "reconciliation": {
                    "tolerance": {
                        "runs": 0,
                        "provider_calls": 0,
                        "tokens_total": 0,
                        "cost": 0,
                    }
                }
            },
        },
        headers=build_internal_headers(idempotency_key="portal-reads-plan-version-001"),
    )
    client.post(
        "/internal/service/admin/accounts/acct_portal_reads/subscription",
        json={
            "subscription_id": "sub_portal_reads",
            "account_id": "acct_portal_reads",
            "plan_id": "plan_portal_reads",
            "plan_version_id": "plan_portal_reads_v1",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="portal-reads-subscription-001"),
    )
    client.post(
        "/portal/v1/sites/site_portal_reads/api-keys",
        json={"label": "Portal Reads Key"},
        headers=build_portal_headers(
            site_admin_ref="site_admin:portal-reads@example.com",
            idempotency_key="portal-reads-key-001",
        ),
    )
    rebuild_response = client.post(
        "/internal/service/sites/site_portal_reads/billing-snapshots/rebuild",
        headers=build_internal_headers(idempotency_key="portal-reads-billing-rebuild-001"),
    )
    assert rebuild_response.status_code == 200

    summary_response = client.get(
        "/portal/v1/sites/site_portal_reads/summary",
        headers=build_portal_headers(site_admin_ref="site_admin:portal-reads@example.com"),
    )
    assert summary_response.status_code == 200
    assert summary_response.json()["data"]["site"]["site_id"] == "site_portal_reads"
    assert summary_response.json()["data"]["identity_type"] == "site_admin"
    assert summary_response.json()["data"]["role"] == "site_admin"

    usage_response = client.get(
        "/portal/v1/sites/site_portal_reads/usage-summary",
        headers=build_portal_headers(site_admin_ref="site_admin:portal-reads@example.com"),
    )
    assert usage_response.status_code == 200
    assert usage_response.json()["data"]["site_id"] == "site_portal_reads"
    assert usage_response.json()["data"]["identity_type"] == "site_admin"
    assert usage_response.json()["data"]["role"] == "site_admin"

    monitoring_response = client.get(
        "/portal/v1/sites/site_portal_reads/monitoring-overview?window_hours=24",
        headers=build_portal_headers(site_admin_ref="site_admin:portal-reads@example.com"),
    )
    assert monitoring_response.status_code == 200
    monitoring_data = monitoring_response.json()["data"]
    assert monitoring_data["contract_version"] == "magick-site-monitoring-overview-v1"
    assert monitoring_data["site_id"] == "site_portal_reads"
    assert monitoring_data["identity_type"] == "site_admin"
    assert monitoring_data["role"] == "site_admin"
    assert "health" in monitoring_data
    assert "action_required" in monitoring_data
    assert "quota" in monitoring_data

    entitlements_response = client.get(
        "/portal/v1/sites/site_portal_reads/entitlements",
        headers=build_portal_headers(site_admin_ref="site_admin:portal-reads@example.com"),
    )
    assert entitlements_response.status_code == 200
    entitlements_data = entitlements_response.json()["data"]
    assert entitlements_data["site"]["site_id"] == "site_portal_reads"
    assert entitlements_data["policy"]["subscription"]["grace_period_days"] == 0
    quota_summary = entitlements_data["quota_summary"]
    assert quota_summary["account_id"] == "acct_portal_reads"
    assert quota_summary["credit"]["key"] == "ai_credits"
    assert quota_summary["credit"]["estimated"] is True
    assert "internal_limits" not in quota_summary
    assert {item["key"] for item in quota_summary["resource_limits"]} >= {
        "bound_sites",
        "active_api_key_sites",
        "vector_documents",
    }

    audit_response = client.get(
        "/portal/v1/sites/site_portal_reads/audit-summary",
        headers=build_portal_headers(site_admin_ref="site_admin:portal-reads@example.com"),
    )
    assert audit_response.status_code == 200
    assert audit_response.json()["data"]["site_id"] == "site_portal_reads"
    assert audit_response.json()["data"]["totals"]["events"] >= 1

    audit_events_response = client.get(
        "/portal/v1/sites/site_portal_reads/audit-events?event_kind=site_key.issue&limit=10",
        headers=build_portal_headers(site_admin_ref="site_admin:portal-reads@example.com"),
    )
    assert audit_events_response.status_code == 200
    assert audit_events_response.json()["data"]["site_id"] == "site_portal_reads"
    assert audit_events_response.json()["data"]["filters"]["event_kind"] == "site_key.issue"
    assert len(audit_events_response.json()["data"]["items"]) >= 1

    billing_response = client.get(
        "/portal/v1/sites/site_portal_reads/billing-snapshots",
        headers=build_portal_headers(site_admin_ref="site_admin:portal-reads@example.com"),
    )
    assert billing_response.status_code == 200
    assert billing_response.json()["data"]["site_id"] == "site_portal_reads"
    assert len(billing_response.json()["data"]["items"]) >= 1

    reconciliation_response = client.get(
        "/portal/v1/sites/site_portal_reads/billing-snapshots/reconciliation",
        headers=build_portal_headers(site_admin_ref="site_admin:portal-reads@example.com"),
    )
    assert reconciliation_response.status_code == 200
    assert reconciliation_response.json()["data"]["site_id"] == "site_portal_reads"
    assert reconciliation_response.json()["data"]["reconciliation"]["snapshot_present"] is True

    denied_response = client.get(
        "/portal/v1/sites/site_portal_reads/summary",
        headers=build_portal_headers(site_admin_ref="site_admin:outsider@example.com"),
    )
    assert denied_response.status_code == 403
    assert denied_response.json()["error_code"] == "service.site_admin_access_required"
    assert denied_response.json()["meta"]["trace_id"] == "00112233445566778899aabbccddeeff"

    dispose_engine(database_url)
