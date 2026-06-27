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
from app.adapters.repositories.commercial_repository import CommercialRepository
from app.api.main import create_app
from app.api.routes import portal as portal_routes
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    ACCOUNT_USER_MEMBERSHIP_STATUS_REVOKED,
    PRINCIPAL_STATUS_ACTIVE,
    SITE_USER_GRANT_STATUS_REVOKED,
    AccountSubscription,
    AccountUserMembership,
    CreditLedgerEntry,
    IdentityProviderBinding,
    PluginObservabilityEvent,
    Principal,
    SiteUserGrant,
)
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from app.domain.hosted_model_defaults import FREE_GPT55_MODEL_ID
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
    build_internal_headers,
)
from tests.conftest import (
    build_portal_bearer_headers as _build_portal_bearer_headers,
)
from tests.conftest import (
    build_portal_headers as _build_portal_headers,
)

_GRANTS_BY_EMAIL: dict[str, dict[str, object]] = {}


def _normalize_test_email(value: str) -> str:
    return str(value or "").strip().lower()


def _resolve_test_principal(
    principal_id: str,
    session_version: int,
) -> tuple[str, int]:
    raw = str(principal_id or "").strip()
    if raw.startswith("principal:"):
        email = _normalize_test_email(raw.split(":", 1)[1])
        grant = _GRANTS_BY_EMAIL.get(email)
        if grant is not None:
            return str(grant["principal_id"]), int(grant.get("session_version") or 1)
    return raw, int(session_version or 1)


def build_portal_headers(**kwargs: Any) -> dict[str, str]:
    principal_id = str(kwargs.pop("principal_id", "principal:portal-admin@example.com"))
    session_version = int(kwargs.pop("session_version", 1))
    resolved_principal_id, resolved_session_version = _resolve_test_principal(
        principal_id,
        session_version,
    )
    return _build_portal_headers(
        principal_id=resolved_principal_id,
        session_version=resolved_session_version,
        **kwargs,
    )


def build_portal_bearer_headers(**kwargs: Any) -> dict[str, str]:
    principal_id = str(kwargs.pop("principal_id", "principal:portal-admin@example.com"))
    session_version = int(kwargs.pop("session_version", 1))
    resolved_principal_id, resolved_session_version = _resolve_test_principal(
        principal_id,
        session_version,
    )
    return _build_portal_bearer_headers(
        principal_id=resolved_principal_id,
        session_version=resolved_session_version,
        **kwargs,
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
    _GRANTS_BY_EMAIL.clear()
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()

    settings_kwargs: dict[str, object] = {
        "project_name": "Npcink AI Cloud Test",
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
        str(request_headers.get("x-npcink-debug-portal-link") or "").strip() == "1"
        and "x-npcink-dev-login-code" not in request_headers
    ):
        request_headers["x-npcink-dev-login-code"] = "1"
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
    data = response.json()["data"]
    _GRANTS_BY_EMAIL[_normalize_test_email(email)] = data
    return data


def _grant_principal_access(
    client: TestClient,
    *,
    site_id: str,
    email: str,
    status: str = "active",
    idempotency_key: str = "portal-user-grants-001",
) -> dict[str, object]:
    response = client.post(
        f"/internal/service/sites/{site_id}/user-grants",
        json={"email": email, "status": status},
        headers=build_internal_headers(idempotency_key=idempotency_key),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    _GRANTS_BY_EMAIL[_normalize_test_email(email)] = data
    return data


def _portal_headers_for_grant(
    grant: dict[str, object],
    **kwargs: object,
) -> dict[str, str]:
    return build_portal_headers(
        principal_id=str(grant["principal_id"]),
        session_version=int(grant.get("session_version") or 1),
        **kwargs,
    )


def _portal_bearer_headers_for_grant(
    grant: dict[str, object],
    **kwargs: object,
) -> dict[str, str]:
    return build_portal_bearer_headers(
        principal_id=str(grant["principal_id"]),
        session_version=int(grant.get("session_version") or 1),
        **kwargs,
    )


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
    _grant_principal_access(
        client,
        site_id="site_portal",
        email="portal-admin@example.com",
        idempotency_key="portal-user-grants-admin-001",
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
    assert portal_issue_audit["actor_kind"] == "principal"
    assert portal_rotate_audit["actor_kind"] == "principal"
    assert portal_revoke_audit["actor_kind"] == "principal"
    assert portal_issue_audit["actor_ref"] == _GRANTS_BY_EMAIL["portal-admin@example.com"][
        "principal_id"
    ]

    dispose_engine(database_url)


def test_portal_site_key_write_requires_manage_site_keys_action(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_action", "name": "Portal Action Account"},
        headers=build_internal_headers(idempotency_key="portal-action-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_action",
            "account_id": "acct_portal_action",
            "name": "Portal Action Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-action-site-001"),
    )
    grant = _grant_principal_access(
        client,
        site_id="site_portal_action",
        email="portal-action@example.com",
        idempotency_key="portal-action-user-grants-001",
    )
    with get_session(database_url) as session:
        membership = session.scalar(
            select(AccountUserMembership).where(
                AccountUserMembership.principal_id == str(grant["principal_id"]),
                AccountUserMembership.account_id == "acct_portal_action",
            )
        )
        assert membership is not None
        membership.allowed_actions_json = ["view_usage"]
        session.commit()

    response = client.post(
        "/portal/v1/sites/site_portal_action/api-keys",
        json={"label": "Denied Key"},
        headers=_portal_headers_for_grant(
            grant,
            idempotency_key="portal-action-key-001",
        ),
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "service.portal_action_forbidden"

    dispose_engine(database_url)


def test_portal_revoked_account_membership_blocks_site_access(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_revoked_member", "name": "Portal Member Account"},
        headers=build_internal_headers(idempotency_key="portal-revoked-member-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_revoked_member",
            "account_id": "acct_portal_revoked_member",
            "name": "Portal Member Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-revoked-member-site-001"),
    )
    grant = _grant_principal_access(
        client,
        site_id="site_portal_revoked_member",
        email="portal-revoked-member@example.com",
        idempotency_key="portal-revoked-member-user-grants-001",
    )
    with get_session(database_url) as session:
        membership = session.scalar(
            select(AccountUserMembership).where(
                AccountUserMembership.principal_id == str(grant["principal_id"]),
                AccountUserMembership.account_id == "acct_portal_revoked_member",
            )
        )
        assert membership is not None
        membership.status = ACCOUNT_USER_MEMBERSHIP_STATUS_REVOKED
        session.commit()

    response = client.get(
        "/portal/v1/sites/site_portal_revoked_member/summary",
        headers=_portal_headers_for_grant(grant),
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "service.principal_access_required"

    dispose_engine(database_url)


def test_portal_revoked_site_grant_blocks_site_access(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_revoked_grant", "name": "Portal Grant Account"},
        headers=build_internal_headers(idempotency_key="portal-revoked-grant-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_revoked_grant",
            "account_id": "acct_portal_revoked_grant",
            "name": "Portal Grant Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-revoked-grant-site-001"),
    )
    grant = _grant_principal_access(
        client,
        site_id="site_portal_revoked_grant",
        email="portal-revoked-grant@example.com",
        idempotency_key="portal-revoked-grant-user-grants-001",
    )
    with get_session(database_url) as session:
        site_grant = session.scalar(
            select(SiteUserGrant).where(
                SiteUserGrant.principal_id == str(grant["principal_id"]),
                SiteUserGrant.site_id == "site_portal_revoked_grant",
            )
        )
        assert site_grant is not None
        site_grant.status = SITE_USER_GRANT_STATUS_REVOKED
        session.commit()

    response = client.get(
        "/portal/v1/sites/site_portal_revoked_grant/summary",
        headers=_portal_headers_for_grant(grant),
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "service.principal_access_required"

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
    _grant_principal_access(
        client,
        site_id="site_portal_page",
        email="portal-page@example.com",
        idempotency_key="portal-page-user-grants-001",
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
        headers=build_portal_headers(principal_id="principal:portal-page@example.com"),
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
    _grant_principal_access(
        client,
        site_id="site_portal_alias",
        email="portal-alias@example.com",
        idempotency_key="portal-alias-user-grants-001",
    )

    issue_response = client.post(
        "/portal/v1/sites/site_portal_alias/api-keys",
        json={"label": "Alias Key", "scopes": ["read", "execute"]},
        headers=build_portal_headers(
            principal_id="principal:portal-alias@example.com",
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
        headers={"X-Npcink-Portal-Site-Admin-Ref": "principal:portal-admin@example.com"},
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.portal_session_required"

    dispose_engine(database_url)


def test_portal_routes_require_portal_auth_configuration(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()

    settings = Settings(
        project_name="Npcink AI Cloud Test",
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
    _grant_principal_access(
        client,
        site_id="site_portal_ai",
        email="portal-admin@example.com",
        idempotency_key="portal-ai-user-grants-001",
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
        headers=build_portal_headers(principal_id="principal:outsider@example.com"),
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.portal_session_revoked"

    dispose_engine(database_url)


def test_portal_site_diagnostic_advisor_is_scoped_and_read_only(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_diag", "name": "Portal Diagnostics"},
        headers=build_internal_headers(idempotency_key="portal-diag-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_diag",
            "account_id": "acct_portal_diag",
            "name": "Portal Diagnostics Site",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="portal-diag-site-001"),
    )
    _grant_principal_access(
        client,
        site_id="site_portal_diag",
        email="portal-diag@example.com",
        idempotency_key="portal-diag-user-grants-001",
    )
    key_response = client.post(
        "/portal/v1/sites/site_portal_diag/api-keys",
        json={"label": "Portal Diagnostics Key"},
        headers=build_portal_headers(
            principal_id="principal:portal-diag@example.com",
            idempotency_key="portal-diag-key-001",
        ),
    )
    assert key_response.status_code == 200, key_response.text

    now = datetime.now(UTC)
    with get_session(database_url) as session:
        session.add(
            PluginObservabilityEvent(
                dedupe_key="portal-diag-plugin-error-001",
                site_id="site_portal_diag",
                key_id="key_default",
                schema_version="2026-06-01",
                plugin_slug="npcink-ai-client-adapter",
                plugin_version="0.1.0",
                source="local",
                event_kind="adapter.runtime.failed",
                event_id="portal-diag-plugin-error-event-001",
                status="error",
                error_code="wordpress.fatal_error",
                latency_ms=3900,
                ability_id="npcink-abilities-toolkit/create-draft",
                payload_json={"raw": "portal raw payload must not leak"},
                captured_at=now - timedelta(minutes=4),
                received_at=now - timedelta(minutes=4),
            )
        )
        session.commit()

    response = client.get(
        "/portal/v1/sites/site_portal_diag/diagnostic-advisor?window_hours=24",
        headers=build_portal_headers(principal_id="principal:portal-diag@example.com"),
    )
    outsider = client.get(
        "/portal/v1/sites/site_portal_diag/diagnostic-advisor?window_hours=24",
        headers=build_portal_headers(principal_id="principal:outsider@example.com"),
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["scope"] == "site_diagnostics"
    assert data["site_id"] == "site_portal_diag"
    assert data["identity_type"] == "user"
    assert data["role"] == "user"
    assert data["safety"]["write_posture"] == "suggestion_only"
    assert data["safety"]["direct_wordpress_write"] is False
    assert data["safety"]["automatic_repair_allowed"] is False
    assert data["diagnostic_items"]
    assert any(item["source"] == "plugins" for item in data["diagnostic_items"])
    assert data["diagnostic_workflow"]["new"] >= 1
    assert data["diagnostic_workflow"]["needs_attention"] >= 1
    assert data["evidence_window"]["hours"] == 24
    first_item = data["diagnostic_items"][0]
    assert first_item["workflow_status"] == "new"
    assert first_item["status_detail"]["allowed_statuses"] == [
        "new",
        "acknowledged",
        "muted",
        "resolved",
    ]
    serialized = json.dumps(data)
    assert "portal raw payload must not leak" not in serialized
    assert "payload_json" not in serialized
    assert outsider.status_code == 401

    dispose_engine(database_url)


def test_portal_unknown_principal_cannot_access_site_keys(tmp_path: Path) -> None:
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
        headers=build_portal_headers(principal_id="principal:outsider@example.com"),
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.portal_session_revoked"

    dispose_engine(database_url)


def test_disabled_principal_cannot_read_or_write(tmp_path: Path) -> None:
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
    _grant_principal_access(
        client,
        site_id="site_portal_disabled",
        email="portal-disabled@example.com",
        status="disabled",
        idempotency_key="portal-disabled-user-grants-001",
    )

    read_response = client.get(
        "/portal/v1/sites/site_portal_disabled/summary",
        headers=build_portal_headers(principal_id="principal:portal-disabled@example.com"),
    )
    assert read_response.status_code == 401
    assert read_response.json()["error_code"] == "auth.portal_session_revoked"

    write_response = client.post(
        "/portal/v1/sites/site_portal_disabled/api-keys",
        json={"label": "Disabled Write Attempt"},
        headers=build_portal_headers(
            principal_id="principal:portal-disabled@example.com",
            idempotency_key="portal-disabled-write-denied-001",
        ),
    )
    assert write_response.status_code == 401
    assert write_response.json()["error_code"] == "auth.portal_session_revoked"

    sites_response = client.get(
        "/portal/v1/sites",
        headers=build_portal_headers(principal_id="principal:portal-disabled@example.com"),
    )
    assert sites_response.status_code == 401
    assert sites_response.json()["error_code"] == "auth.portal_session_revoked"

    dispose_engine(database_url)


def test_portal_jwt_allows_principal_access_without_dev_headers(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_jwt_issuer": "npcink-cloud-portal",
            "portal_jwt_audience": "npcink-cloud-customers",
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
    _grant_principal_access(
        client,
        site_id="site_portal_jwt",
        email="portal-jwt@example.com",
        idempotency_key="portal-jwt-user-grants-001",
    )

    response = client.post(
        "/portal/v1/sites/site_portal_jwt/api-keys",
        json={"label": "JWT Key"},
        headers=build_portal_bearer_headers(
            principal_id="principal:portal-jwt@example.com",
            issuer="npcink-cloud-portal",
            audience="npcink-cloud-customers",
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
    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_unknown_auth", "name": "Portal Unknown Auth"},
        headers=build_internal_headers(idempotency_key="portal-unknown-auth-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_unknown_auth",
            "account_id": "acct_portal_unknown_auth",
            "name": "Portal Unknown Auth Site",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="portal-unknown-auth-site-001"),
    )
    _grant_principal_access(
        client,
        site_id="site_portal_unknown_auth",
        email="portal-admin@example.com",
        idempotency_key="portal-unknown-auth-user-grants-001",
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
            "portal_jwt_issuer": "npcink-cloud-portal",
            "portal_jwt_audience": "npcink-cloud-customers",
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
        "/internal/service/sites/site_portal_auth/user-grants",
        json={"email": "portal-auth@example.com"},
        headers=build_internal_headers(idempotency_key="portal-auth-user-grants-001"),
    )

    request_data = _request_portal_login_code(
        client,
        email="portal-auth@example.com",
        headers={"x-npcink-debug-portal-link": "1"},
    )
    assert request_data["expires_in_seconds"] == 300
    assert request_data["code"] != ""

    consume_data = _verify_portal_login_code(
        client,
        email="portal-auth@example.com",
        code=str(request_data["code"]),
    )
    assert str(consume_data["principal_id"]).startswith("prn_")
    assert consume_data["auth_mode"] == "jwt"
    assert consume_data["session"]["state"] == "active"
    assert consume_data["session"]["transport"] == "cookie"
    assert consume_data["session"]["expires_at"] != ""

    session_response = client.get("/portal/v1/session")
    assert session_response.status_code == 200
    assert session_response.json()["data"]["principal_id"] == consume_data["principal_id"]
    assert session_response.json()["data"]["session"]["revocable"] is True

    with get_session(database_url) as session:
        identity = session.scalar(
            select(Principal).where(
                Principal.principal_id == str(consume_data["principal_id"])
            )
        )
        assert identity is not None
        assert identity.status == PRINCIPAL_STATUS_ACTIVE
        assert identity.last_login_at is not None


def test_portal_qq_bind_and_callback_login_reuse_user_session(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_public_base_url": "https://cloud.example.com",
            "portal_qq_client_id": "qq-client-id",
            "portal_qq_client_secret": "qq-client-secret",
            "portal_qq_redirect_uri": "https://cloud.example.com/portal/v1/auth/qq/callback",
        },
    )

    def fake_exchange_qq_code(request: object, *, code: str) -> dict[str, str]:
        return {"access_token": f"token-{code}"}

    def fake_fetch_qq_openid(request: object, *, access_token: str) -> dict[str, str]:
        return {"openid": "qq-openid-001", "unionid": "qq-union-001"}

    monkeypatch.setattr(portal_routes, "_exchange_qq_code", fake_exchange_qq_code)
    monkeypatch.setattr(portal_routes, "_fetch_qq_openid", fake_fetch_qq_openid)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_qq", "name": "Portal QQ Account"},
        headers=build_internal_headers(idempotency_key="portal-qq-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_qq",
            "account_id": "acct_portal_qq",
            "name": "Portal QQ Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-qq-site-001"),
    )
    client.post(
        "/internal/service/sites/site_portal_qq/activate",
        headers=build_internal_headers(idempotency_key="portal-qq-site-activate-001"),
    )
    _grant_principal_access(
        client,
        site_id="site_portal_qq",
        email="portal-qq@example.com",
        idempotency_key="portal-qq-user-grants-001",
    )
    request_data = _request_portal_login_code(
        client,
        email="portal-qq@example.com",
        headers={"x-npcink-debug-portal-link": "1"},
    )
    _verify_portal_login_code(
        client,
        email="portal-qq@example.com",
        code=str(request_data["code"]),
    )

    start_response = client.get("/portal/v1/auth/qq/start?return_to=/portal/sites")
    assert start_response.status_code == 200
    start_data = start_response.json()["data"]
    assert start_data["provider"] == "qq"
    assert "graph.qq.com/oauth2.0/authorize" in start_data["authorization_url"]

    bind_response = client.post(
        "/portal/v1/auth/qq/bind",
        json={"code": "bind-code", "state": start_data["state"]},
    )
    assert bind_response.status_code == 200, bind_response.text
    assert bind_response.json()["data"]["binding"]["identity_type"] == "user"
    assert bind_response.json()["data"]["binding"]["role"] == "user"

    with get_session(database_url) as session:
        binding = session.scalar(select(IdentityProviderBinding))
        assert binding is not None
        assert binding.provider == "qq"
        assert binding.external_subject_hash != "qq-openid-001"
        assert binding.unionid_hash != "qq-union-001"

    logout_response = client.post("/portal/v1/logout")
    assert logout_response.status_code == 200

    login_start_response = client.get("/portal/v1/auth/qq/start?return_to=/portal/usage")
    assert login_start_response.status_code == 200
    login_state = login_start_response.json()["data"]["state"]

    callback_response = client.get(
        f"/portal/v1/auth/qq/callback?code=login-code&state={login_state}",
    )
    assert callback_response.status_code == 200, callback_response.text
    callback_data = callback_response.json()["data"]
    assert callback_data["principal_id"] == _GRANTS_BY_EMAIL["portal-qq@example.com"][
        "principal_id"
    ]
    assert callback_data["identity_type"] == "user"
    assert callback_data["role"] == "user"
    assert callback_data["auth_provider"] == "qq"
    assert callback_data["return_to"] == "/portal/usage"
    assert callback_data["session"]["transport"] == "cookie"

    dispose_engine(database_url)


def test_portal_qq_start_rejects_redirect_uri_outside_allowlist(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_public_base_url": "https://cloud.example.com",
            "portal_qq_client_id": "qq-client-id",
            "portal_qq_client_secret": "qq-client-secret",
            "portal_qq_redirect_uri": "https://evil.example.com/portal/v1/auth/qq/callback",
        },
    )

    start_response = client.get("/portal/v1/auth/qq/start")
    assert start_response.status_code == 503
    assert start_response.json()["error_code"] == "portal.qq_login_not_configured"

    dispose_engine(database_url)


def test_portal_qq_bind_rejects_nonce_mismatch(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_public_base_url": "https://cloud.example.com",
            "portal_qq_client_id": "qq-client-id",
            "portal_qq_client_secret": "qq-client-secret",
            "portal_qq_redirect_uri": "https://cloud.example.com/portal/v1/auth/qq/callback",
        },
    )

    monkeypatch.setattr(
        portal_routes,
        "_exchange_qq_code",
        lambda request, *, code: {"access_token": f"token-{code}"},
    )
    monkeypatch.setattr(
        portal_routes,
        "_fetch_qq_openid",
        lambda request, *, access_token: {"openid": "qq-openid-nonce", "unionid": ""},
    )

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_qq_nonce", "name": "Portal QQ Nonce Account"},
        headers=build_internal_headers(idempotency_key="portal-qq-nonce-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_qq_nonce",
            "account_id": "acct_portal_qq_nonce",
            "name": "Portal QQ Nonce Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-qq-nonce-site-001"),
    )
    _grant_principal_access(
        client,
        site_id="site_portal_qq_nonce",
        email="portal-qq-nonce@example.com",
        idempotency_key="portal-qq-nonce-user-grants-001",
    )
    request_data = _request_portal_login_code(
        client,
        email="portal-qq-nonce@example.com",
        headers={"x-npcink-debug-portal-link": "1"},
    )
    _verify_portal_login_code(
        client,
        email="portal-qq-nonce@example.com",
        code=str(request_data["code"]),
    )

    start_response = client.get("/portal/v1/auth/qq/start")
    assert start_response.status_code == 200
    bind_response = client.post(
        "/portal/v1/auth/qq/bind",
        json={
            "code": "bind-code",
            "state": start_response.json()["data"]["state"],
            "nonce": "wrong-nonce",
        },
    )
    assert bind_response.status_code == 403
    assert bind_response.json()["error_code"] == "service.portal_oauth_nonce_invalid"

    dispose_engine(database_url)


def test_portal_qq_bind_rejects_account_bound_to_other_principal(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_public_base_url": "https://cloud.example.com",
            "portal_qq_client_id": "qq-client-id",
            "portal_qq_client_secret": "qq-client-secret",
            "portal_qq_redirect_uri": "https://cloud.example.com/portal/v1/auth/qq/callback",
        },
    )

    monkeypatch.setattr(
        portal_routes,
        "_exchange_qq_code",
        lambda request, *, code: {"access_token": f"token-{code}"},
    )
    monkeypatch.setattr(
        portal_routes,
        "_fetch_qq_openid",
        lambda request, *, access_token: {
            "openid": "qq-openid-conflict",
            "unionid": "qq-union-conflict",
        },
    )

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_qq_conflict", "name": "Portal QQ Conflict"},
        headers=build_internal_headers(idempotency_key="portal-qq-conflict-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_qq_conflict_a",
            "account_id": "acct_portal_qq_conflict",
            "name": "Portal QQ Conflict A",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-qq-conflict-site-a-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_qq_conflict_b",
            "account_id": "acct_portal_qq_conflict",
            "name": "Portal QQ Conflict B",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-qq-conflict-site-b-001"),
    )
    _grant_principal_access(
        client,
        site_id="site_portal_qq_conflict_a",
        email="portal-qq-conflict-a@example.com",
        idempotency_key="portal-qq-conflict-user-grants-a-001",
    )
    first_code = _request_portal_login_code(
        client,
        email="portal-qq-conflict-a@example.com",
        headers={"x-npcink-debug-portal-link": "1"},
    )
    _verify_portal_login_code(
        client,
        email="portal-qq-conflict-a@example.com",
        code=str(first_code["code"]),
    )
    first_start = client.get("/portal/v1/auth/qq/start")
    assert first_start.status_code == 200
    first_bind = client.post(
        "/portal/v1/auth/qq/bind",
        json={"code": "first-bind-code", "state": first_start.json()["data"]["state"]},
    )
    assert first_bind.status_code == 200, first_bind.text

    logout_response = client.post("/portal/v1/logout")
    assert logout_response.status_code == 200

    _grant_principal_access(
        client,
        site_id="site_portal_qq_conflict_b",
        email="portal-qq-conflict-b@example.com",
        idempotency_key="portal-qq-conflict-user-grants-b-001",
    )
    second_code = _request_portal_login_code(
        client,
        email="portal-qq-conflict-b@example.com",
        headers={"x-npcink-debug-portal-link": "1"},
    )
    _verify_portal_login_code(
        client,
        email="portal-qq-conflict-b@example.com",
        code=str(second_code["code"]),
    )
    second_start = client.get("/portal/v1/auth/qq/start")
    assert second_start.status_code == 200
    second_bind = client.post(
        "/portal/v1/auth/qq/bind",
        json={"code": "second-bind-code", "state": second_start.json()["data"]["state"]},
    )
    assert second_bind.status_code == 403
    assert second_bind.json()["error_code"] == "service.identity_provider_binding_conflict"

    dispose_engine(database_url)


def test_portal_qq_unbind_revokes_current_session(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_public_base_url": "https://cloud.example.com",
            "portal_qq_client_id": "qq-client-id",
            "portal_qq_client_secret": "qq-client-secret",
            "portal_qq_redirect_uri": "https://cloud.example.com/portal/v1/auth/qq/callback",
        },
    )

    monkeypatch.setattr(
        portal_routes,
        "_exchange_qq_code",
        lambda request, *, code: {"access_token": f"token-{code}"},
    )
    monkeypatch.setattr(
        portal_routes,
        "_fetch_qq_openid",
        lambda request, *, access_token: {"openid": "qq-openid-unbind", "unionid": ""},
    )

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_qq_unbind", "name": "Portal QQ Unbind Account"},
        headers=build_internal_headers(idempotency_key="portal-qq-unbind-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_qq_unbind",
            "account_id": "acct_portal_qq_unbind",
            "name": "Portal QQ Unbind Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-qq-unbind-site-001"),
    )
    _grant_principal_access(
        client,
        site_id="site_portal_qq_unbind",
        email="portal-qq-unbind@example.com",
        idempotency_key="portal-qq-unbind-user-grants-001",
    )
    request_data = _request_portal_login_code(
        client,
        email="portal-qq-unbind@example.com",
        headers={"x-npcink-debug-portal-link": "1"},
    )
    _verify_portal_login_code(
        client,
        email="portal-qq-unbind@example.com",
        code=str(request_data["code"]),
    )
    start_response = client.get("/portal/v1/auth/qq/start")
    assert start_response.status_code == 200
    bind_response = client.post(
        "/portal/v1/auth/qq/bind",
        json={"code": "bind-code", "state": start_response.json()["data"]["state"]},
    )
    assert bind_response.status_code == 200, bind_response.text

    unbind_response = client.post("/portal/v1/auth/qq/unbind", json={"provider": "qq"})
    assert unbind_response.status_code == 200
    assert unbind_response.json()["data"]["revoked"] == 1

    session_response = client.get("/portal/v1/session")
    assert session_response.status_code == 401
    assert session_response.json()["error_code"] == "auth.portal_session_revoked"

    dispose_engine(database_url)


def test_portal_qq_callback_requires_existing_binding(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_public_base_url": "https://cloud.example.com",
            "portal_qq_client_id": "qq-client-id",
            "portal_qq_client_secret": "qq-client-secret",
        },
    )

    monkeypatch.setattr(
        portal_routes,
        "_exchange_qq_code",
        lambda request, *, code: {"access_token": "token-unbound"},
    )
    monkeypatch.setattr(
        portal_routes,
        "_fetch_qq_openid",
        lambda request, *, access_token: {"openid": "qq-openid-unbound", "unionid": ""},
    )

    start_response = client.get("/portal/v1/auth/qq/start")
    assert start_response.status_code == 200
    state = start_response.json()["data"]["state"]

    callback_response = client.get(f"/portal/v1/auth/qq/callback?code=qq-code&state={state}")
    assert callback_response.status_code == 200, callback_response.text
    data = callback_response.json()["data"]
    assert data["status"] == "binding_required"
    assert data["provider"] == "qq"
    assert data["identity_type"] == "user"
    assert data["role"] == "user"

    dispose_engine(database_url)


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
    _grant_principal_access(
        client,
        site_id="site_portal_mail",
        email="portal-mail@example.com",
        idempotency_key="portal-mail-user-grants-001",
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


def test_portal_login_code_request_masks_missing_principal_access(
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
            "portal_jwt_issuer": "npcink-cloud-portal",
            "portal_jwt_audience": "npcink-cloud-customers",
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
    _grant_principal_access(
        client,
        site_id="site_portal_forwarded",
        email="portal-forwarded@example.com",
        idempotency_key="portal-forwarded-user-grants-001",
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
            "x-npcink-debug-portal-link": "1",
            "x-npcink-dev-login-code": "1",
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
            "portal_jwt_issuer": "npcink-cloud-portal",
            "portal_jwt_audience": "npcink-cloud-customers",
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
    _grant_principal_access(
        client,
        site_id="site_portal_localhost",
        email="portal-localhost@example.com",
        idempotency_key="portal-localhost-user-grants-001",
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
            "x-npcink-debug-portal-link": "1",
            "x-npcink-dev-login-code": "1",
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
            "portal_jwt_issuer": "npcink-cloud-portal",
            "portal_jwt_audience": "npcink-cloud-customers",
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
    _grant_principal_access(
        client,
        site_id="site_portal_debug",
        email="portal-debug@example.com",
        idempotency_key="portal-debug-user-grants-001",
    )

    debug_headers = {
        "origin": "http://127.0.0.1:8010",
        "referer": "http://127.0.0.1:8010/",
        "host": "127.0.0.1:8010",
        "x-forwarded-host": "127.0.0.1:8010",
        "x-forwarded-proto": "http",
        "x-npcink-debug-portal-link": "1",
        "x-npcink-dev-login-code": "1",
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
            "portal_jwt_issuer": "npcink-cloud-portal",
            "portal_jwt_audience": "npcink-cloud-customers",
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
    _grant_principal_access(
        client,
        site_id="site_portal_session",
        email="portal-session@example.com",
        idempotency_key="portal-session-user-grants-001",
    )

    request_data = _request_portal_login_code(
        client,
        email="portal-session@example.com",
        headers={"x-npcink-debug-portal-link": "1"},
    )
    _verify_portal_login_code(
        client,
        email="portal-session@example.com",
        code=str(request_data["code"]),
    )

    session_response = client.get("/portal/v1/session")
    assert session_response.status_code == 200
    session_data = session_response.json()["data"]
    assert session_data["principal_id"] == _GRANTS_BY_EMAIL[
        "portal-session@example.com"
    ]["principal_id"]
    assert session_data["site_id"] == "site_portal_session"
    assert session_data["account_id"] == "acct_portal_session"
    assert session_data["identity_type"] == "user"
    assert session_data["role"] == "user"
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
            "portal_jwt_issuer": "npcink-cloud-portal",
            "portal_jwt_audience": "npcink-cloud-customers",
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
    _grant_principal_access(
        client,
        site_id="site_portal_cookie_keys",
        email="portal-cookie-keys@example.com",
        idempotency_key="portal-cookie-keys-user-grants-001",
    )

    request_data = _request_portal_login_code(
        client,
        email="portal-cookie-keys@example.com",
        headers={"x-npcink-debug-portal-link": "1"},
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
    _grant_principal_access(
        client,
        site_id="site_portal_origin",
        email="portal-origin@example.com",
        idempotency_key="portal-origin-user-grants-001",
    )

    request_response = client.post(
        "/portal/v1/auth/code/request",
        json={"email": "portal-origin@example.com"},
        headers={
            "x-npcink-debug-portal-link": "1",
            "x-npcink-dev-login-code": "1",
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
            "x-npcink-debug-portal-link": "1",
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
    _grant_principal_access(
        client,
        site_id="site_portal_header_origin",
        email="portal-admin@example.com",
        idempotency_key="portal-header-origin-user-grants-001",
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
            "portal_jwt_issuer": "npcink-cloud-portal",
            "portal_jwt_audience": "npcink-cloud-customers",
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
    _grant_principal_access(
        client,
        site_id="site_portal_session_jwt",
        email="portal-session-jwt@example.com",
        idempotency_key="portal-session-jwt-user-grants-001",
    )

    response = client.get(
        "/portal/v1/session",
        headers=build_portal_bearer_headers(
            principal_id="principal:portal-session-jwt@example.com",
            issuer="npcink-cloud-portal",
            audience="npcink-cloud-customers",
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["principal_id"] == _GRANTS_BY_EMAIL[
        "portal-session-jwt@example.com"
    ]["principal_id"]
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
    _grant_principal_access(
        client,
        site_id="site_portal_reads",
        email="portal-reads@example.com",
        idempotency_key="portal-reads-user-grants-001",
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
    with get_session(database_url) as session:
        subscription = session.scalar(
            select(AccountSubscription)
            .where(AccountSubscription.account_id == "acct_portal_reads")
            .order_by(AccountSubscription.created_at.desc())
        )
        assert subscription is not None
        repository = CommercialRepository(session)
        repository.record_credit_ledger_entry(
            account_id="acct_portal_reads",
            site_id="site_portal_reads",
            subscription_id=subscription.subscription_id,
            plan_version_id=subscription.plan_version_id,
            run_id="run-portal-ledger-1",
            provider_call_id=None,
            source_type="tokens_total",
            source_id="run-portal-ledger-1:tokens",
            credit_delta=-2,
            quantity=1500,
            unit="token",
            rate=1,
            rate_unit="1000_tokens_rounded_up",
            rate_version="ai-credit-ledger-v2",
            idempotency_key="portal-credit-ledger-001",
        )
        repository.record_credit_ledger_entry(
            account_id="acct_portal_reads",
            site_id="site_portal_reads",
            subscription_id=subscription.subscription_id,
            plan_version_id=subscription.plan_version_id,
            run_id="run-portal-ledger-zhihu-hot",
            provider_call_id=None,
            source_type="zhihu_hot_topics",
            source_id="run-portal-ledger-zhihu-hot:provider-call",
            credit_delta=-1,
            quantity=1,
            unit="call",
            rate=1,
            rate_unit=None,
            rate_version="ai-credit-ledger-v2",
            idempotency_key="portal-credit-ledger-zhihu-hot-001",
            metadata_json={
                "provider": "zhihu",
                "intent": "zhihu_hot_topics",
                "managed_source": "zhihu_hot_topics",
            },
        )
        session.commit()
    client.post(
        "/portal/v1/sites/site_portal_reads/api-keys",
        json={"label": "Portal Reads Key"},
        headers=build_portal_headers(
            principal_id="principal:portal-reads@example.com",
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
        headers=build_portal_headers(principal_id="principal:portal-reads@example.com"),
    )
    assert summary_response.status_code == 200
    assert summary_response.json()["data"]["site"]["site_id"] == "site_portal_reads"
    assert summary_response.json()["data"]["identity_type"] == "user"
    assert summary_response.json()["data"]["role"] == "user"

    usage_response = client.get(
        "/portal/v1/sites/site_portal_reads/usage-summary",
        headers=build_portal_headers(principal_id="principal:portal-reads@example.com"),
    )
    assert usage_response.status_code == 200
    assert usage_response.json()["data"]["site_id"] == "site_portal_reads"
    assert usage_response.json()["data"]["identity_type"] == "user"
    assert usage_response.json()["data"]["role"] == "user"

    monitoring_response = client.get(
        "/portal/v1/sites/site_portal_reads/monitoring-overview?window_hours=24",
        headers=build_portal_headers(principal_id="principal:portal-reads@example.com"),
    )
    assert monitoring_response.status_code == 200
    monitoring_data = monitoring_response.json()["data"]
    assert monitoring_data["contract_version"] == "magick-site-monitoring-overview-v1"
    assert monitoring_data["site_id"] == "site_portal_reads"
    assert monitoring_data["identity_type"] == "user"
    assert monitoring_data["role"] == "user"
    assert "health" in monitoring_data
    assert "action_required" in monitoring_data
    assert "quota" in monitoring_data

    entitlements_response = client.get(
        "/portal/v1/sites/site_portal_reads/entitlements",
        headers=build_portal_headers(principal_id="principal:portal-reads@example.com"),
    )
    assert entitlements_response.status_code == 200
    entitlements_data = entitlements_response.json()["data"]
    assert entitlements_data["site"]["site_id"] == "site_portal_reads"
    assert entitlements_data["policy"]["subscription"]["grace_period_days"] == 0
    quota_summary = entitlements_data["quota_summary"]
    assert quota_summary["account_id"] == "acct_portal_reads"
    assert quota_summary["credit"]["key"] == "ai_credits"
    assert quota_summary["credit"]["estimated"] is False
    assert quota_summary["credit_policy"]["rate_version"] == "ai-credit-ledger-v2"
    assert quota_summary["credit_policy"]["topup_policy"] == (
        "operator_topups_apply_to_target_period_only"
    )
    credit_usage_detail = quota_summary["credit_usage_detail"]
    assert credit_usage_detail["default_visibility"] == "cloud_portal_only"
    assert credit_usage_detail["local_addon_policy"] == "summary_and_link_only"
    assert credit_usage_detail["portal_paths"]["credit_ledger"] == "/portal/usage/credits"
    assert {item["key"] for item in credit_usage_detail["breakdown"]} >= {
        "tokens_total",
        "zhihu_hot_topics",
    }
    assert next(
        item
        for item in credit_usage_detail["breakdown"]
        if item["key"] == "zhihu_hot_topics"
    )["capability_group"] == "zhihu_open_platform"
    assert "internal_limits" not in quota_summary
    assert {item["key"] for item in quota_summary["resource_limits"]} >= {
        "bound_sites",
        "active_api_key_sites",
        "vector_documents",
    }

    credit_ledger_response = client.get(
        "/portal/v1/sites/site_portal_reads/credit-ledger?limit=10",
        headers=build_portal_headers(principal_id="principal:portal-reads@example.com"),
    )
    assert credit_ledger_response.status_code == 200
    credit_ledger_data = credit_ledger_response.json()["data"]
    assert credit_ledger_data["site_id"] == "site_portal_reads"
    assert credit_ledger_data["account_id"] == "acct_portal_reads"
    assert credit_ledger_data["summary"]["total_credits"] == 3.0
    assert credit_ledger_data["pagination"]["total"] == 2
    assert {item["source_type"] for item in credit_ledger_data["items"]} == {
        "tokens_total",
        "zhihu_hot_topics",
    }
    assert {item["category"] for item in credit_ledger_data["items"]} == {"ai_usage"}
    assert credit_ledger_data["summary"]["category_totals"]["ai_usage"][
        "net_credit_delta"
    ] == -3.0
    assert credit_ledger_data["usage_detail"]["surface"] == "portal_personal_credit_usage"
    assert {
        item["category"] for item in credit_ledger_data["usage_detail"]["legend"]
    } >= {"ai_usage", "credit_pack_purchase", "refund_adjustment", "operator_adjustment"}
    assert {item["key"] for item in credit_ledger_data["usage_detail"]["breakdown"]} >= {
        "tokens_total",
        "zhihu_hot_topics",
    }
    assert len(credit_ledger_data["usage_detail"]["recent_items"]) == 2

    credit_packs_response = client.get(
        "/portal/v1/sites/site_portal_reads/credit-packs",
        headers=build_portal_headers(principal_id="principal:portal-reads@example.com"),
    )
    assert credit_packs_response.status_code == 200
    credit_packs_data = credit_packs_response.json()["data"]
    assert credit_packs_data["catalog_version"] == "ai-credit-packs-v1"
    assert {item["pack_id"] for item in credit_packs_data["items"]} >= {
        "pack_small",
        "pack_medium",
        "pack_large",
    }

    credit_pack_order_response = client.post(
        "/portal/v1/sites/site_portal_reads/credit-pack-orders",
        json={"pack_id": "pack_small"},
        headers=build_portal_headers(
            principal_id="principal:portal-reads@example.com",
            idempotency_key="portal-credit-pack-order-001",
        ),
    )
    assert credit_pack_order_response.status_code == 200, credit_pack_order_response.text
    credit_pack_order = credit_pack_order_response.json()["data"]["order"]
    assert credit_pack_order["purchase_kind"] == "credit_pack"
    assert credit_pack_order["credit_pack"]["ai_credits"] == 10000
    assert credit_pack_order["target_subscription_id"] == "sub_portal_reads"
    assert credit_pack_order["status_detail"]["code"] == "awaiting_payment_confirmation"

    payment_orders_response = client.get(
        "/portal/v1/sites/site_portal_reads/payment-orders?limit=10",
        headers=build_portal_headers(principal_id="principal:portal-reads@example.com"),
    )
    assert payment_orders_response.status_code == 200
    payment_orders = payment_orders_response.json()["data"]
    assert payment_orders["pagination"]["total"] == 1
    assert payment_orders["items"][0]["order_id"] == credit_pack_order["order_id"]
    assert payment_orders["items"][0]["status"] == "pending"
    assert payment_orders["items"][0]["status_detail"]["next_action"] == (
        "provider_payment_or_callback"
    )

    mark_paid_response = client.post(
        f"/internal/service/payments/orders/{credit_pack_order['order_id']}/mark-paid",
        json={
            "provider_trade_no": "202606230000000002",
            "provider_event_id": "portal-credit-pack-paid",
            "amount": 99.0,
        },
        headers=build_internal_headers(idempotency_key="portal-credit-pack-paid-001"),
    )
    assert mark_paid_response.status_code == 200, mark_paid_response.text
    assert mark_paid_response.json()["data"]["credit_ledger_entry"]["credit_delta"] == 10000.0
    assert mark_paid_response.json()["data"]["credit_ledger_entry"]["category"] == (
        "credit_pack_purchase"
    )

    paid_payment_orders_response = client.get(
        "/portal/v1/sites/site_portal_reads/payment-orders?limit=10",
        headers=build_portal_headers(principal_id="principal:portal-reads@example.com"),
    )
    assert paid_payment_orders_response.status_code == 200
    paid_payment_order = paid_payment_orders_response.json()["data"]["items"][0]
    assert paid_payment_order["status"] == "paid"
    assert paid_payment_order["status_detail"]["code"] == "paid_and_granted"

    refreshed_credit_ledger_response = client.get(
        "/portal/v1/sites/site_portal_reads/credit-ledger?limit=10",
        headers=build_portal_headers(principal_id="principal:portal-reads@example.com"),
    )
    assert refreshed_credit_ledger_response.status_code == 200
    refreshed_ledger = refreshed_credit_ledger_response.json()["data"]
    assert refreshed_ledger["summary"]["granted_credits"] == 10000.0
    assert refreshed_ledger["summary"]["net_used_credits"] == 0.0
    assert refreshed_ledger["summary"]["category_totals"]["credit_pack_purchase"][
        "net_credit_delta"
    ] == 10000.0
    assert "credit_pack_purchase" in {
        item["source_type"] for item in refreshed_ledger["items"]
    }
    with get_session(database_url) as session:
        credit_pack_entries = list(
            session.scalars(
                select(CreditLedgerEntry).where(
                    CreditLedgerEntry.source_type == "credit_pack_purchase"
                )
            )
        )
        assert len(credit_pack_entries) == 1

    audit_response = client.get(
        "/portal/v1/sites/site_portal_reads/audit-summary",
        headers=build_portal_headers(principal_id="principal:portal-reads@example.com"),
    )
    assert audit_response.status_code == 200
    assert audit_response.json()["data"]["site_id"] == "site_portal_reads"
    assert audit_response.json()["data"]["totals"]["events"] >= 1

    audit_events_response = client.get(
        "/portal/v1/sites/site_portal_reads/audit-events?event_kind=site_key.issue&limit=10",
        headers=build_portal_headers(principal_id="principal:portal-reads@example.com"),
    )
    assert audit_events_response.status_code == 200
    assert audit_events_response.json()["data"]["site_id"] == "site_portal_reads"
    assert audit_events_response.json()["data"]["filters"]["event_kind"] == "site_key.issue"
    assert len(audit_events_response.json()["data"]["items"]) >= 1

    billing_response = client.get(
        "/portal/v1/sites/site_portal_reads/billing-snapshots",
        headers=build_portal_headers(principal_id="principal:portal-reads@example.com"),
    )
    assert billing_response.status_code == 200
    assert billing_response.json()["data"]["site_id"] == "site_portal_reads"
    assert len(billing_response.json()["data"]["items"]) >= 1

    reconciliation_response = client.get(
        "/portal/v1/sites/site_portal_reads/billing-snapshots/reconciliation",
        headers=build_portal_headers(principal_id="principal:portal-reads@example.com"),
    )
    assert reconciliation_response.status_code == 200
    assert reconciliation_response.json()["data"]["site_id"] == "site_portal_reads"
    assert reconciliation_response.json()["data"]["reconciliation"]["snapshot_present"] is True

    denied_response = client.get(
        "/portal/v1/sites/site_portal_reads/summary",
        headers=build_portal_headers(principal_id="principal:outsider@example.com"),
    )
    assert denied_response.status_code == 401
    assert denied_response.json()["error_code"] == "auth.portal_session_revoked"
    assert denied_response.json()["meta"]["trace_id"] == "00112233445566778899aabbccddeeff"

    dispose_engine(database_url)
