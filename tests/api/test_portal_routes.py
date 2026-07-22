from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.notifications.base import PortalEmailDeliveryError, PortalEmailSender
from app.adapters.providers.base import (
    ProviderCatalogSnapshot,
    ProviderExecutionRequest,
    ProviderExecutionResult,
)
from app.adapters.repositories.commercial_repository import CommercialRepository
from app.api.auth import build_portal_session_token
from app.api.main import create_app
from app.api.portal_session import COOKIE_PORTAL_SESSION_TOKEN
from app.api.routes import portal as portal_routes
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    ACCOUNT_USER_MEMBERSHIP_STATUS_REVOKED,
    CREDIT_LEDGER_EVENT_GRANT,
    PRINCIPAL_STATUS_ACTIVE,
    AccountEntitlementSnapshot,
    AccountSubscription,
    AccountUserMembership,
    CreditLedgerEntry,
    IdentityProviderBinding,
    PaymentOrder,
    PlanVersion,
    PluginObservabilityEvent,
    PortalOAuthState,
    Principal,
    RunRecord,
    ServiceAuditEvent,
    Site,
    SiteApiKey,
    SupportRequestAttachment,
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

_ACCESS_BY_EMAIL: dict[str, dict[str, object]] = {}
PORTAL_INTERNAL_IDENTITY_FIELDS = {
    "account_id",
    "principal_id",
    "identity_type",
    "role",
    "allowed_actions",
}
PORTAL_QQ_INTERNAL_IDENTITY_FIELDS = (
    PORTAL_INTERNAL_IDENTITY_FIELDS - {"allowed_actions"}
) | {
    "member_ref",
    "member_refs",
    "site_admin_ref",
}
PORTAL_SUPPORT_INTERNAL_FIELDS = {
    "account_id",
    "principal_id",
    "email",
    "admin_note",
    "metadata",
    "visibility",
}
PORTAL_BOUNDED_PROJECTION_INTERNAL_FIELDS = {
    "account_id",
    "principal_id",
    "actor_ref",
    "idempotency_key",
    "payload",
    "metadata",
    "metadata_json",
}
PORTAL_COMMERCIAL_INTERNAL_FIELDS = PORTAL_BOUNDED_PROJECTION_INTERNAL_FIELDS | {
    "identity_type",
    "role",
    "allowed_actions",
    "site_admin_ref",
    "member_ref",
    "admin_note",
    "claim_id",
    "external_order_no",
    "provider_trade_no",
    "concurrency",
}
STRICT_PORTAL_SUBSCRIPTION_FIELDS = {
    "subscription_id",
    "plan_id",
    "plan_version_id",
    "status",
    "tier_id",
    "plan_kind",
    "package_kind",
    "package_alias",
    "display_package_label",
    "coverage_state",
    "current_period_start_at",
    "current_period_end_at",
    "scheduled_plan_id",
    "scheduled_plan_version_id",
    "scheduled_change_at",
}


def _alipay_test_keys() -> tuple[Any, str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_key, private_pem, public_pem


def _sign_alipay_payload(private_key: Any, payload: dict[str, str]) -> str:
    canonical = "&".join(
        f"{key}={value}"
        for key, value in sorted(payload.items())
        if key not in {"sign", "sign_type"} and value
    )
    signature = private_key.sign(
        canonical.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def _normalize_test_email(value: str) -> str:
    return str(value or "").strip().lower()


def _resolve_test_principal(
    principal_id: str,
    session_version: int,
) -> tuple[str, int]:
    raw = str(principal_id or "").strip()
    if raw.startswith("principal:"):
        email = _normalize_test_email(raw.split(":", 1)[1])
        grant = _ACCESS_BY_EMAIL.get(email)
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
    _ACCESS_BY_EMAIL.clear()
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
        self.support_update_error = ""

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

    def send_support_request_update(
        self,
        *,
        recipient_email: str,
        request_id: str,
        title: str,
        status: str,
        message_body: str,
        project_name: str,
        portal_url: str,
        locale: str = "zh-CN",
    ) -> None:
        if self.support_update_error:
            raise PortalEmailDeliveryError(self.support_update_error)
        self.messages.append(
            {
                "kind": "support_request_update",
                "recipient_email": recipient_email,
                "request_id": request_id,
                "title": title,
                "status": status,
                "message_body": message_body,
                "project_name": project_name,
                "portal_url": portal_url,
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
    remember_me: bool | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"email": email, "code": code}
    if remember_me is not None:
        payload["remember_me"] = remember_me
    response = client.post(
        "/portal/v1/auth/code/verify",
        json=payload,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    normalized_email = _normalize_test_email(email)
    access = {
        **_ACCESS_BY_EMAIL.get(normalized_email, {}),
        **data,
    }
    if not str(access.get("principal_id") or ""):
        services = client.app.state.services
        with get_session(services.settings.database_url) as session:
            identity = session.scalar(select(Principal).where(Principal.email == normalized_email))
            assert identity is not None
            access["principal_id"] = str(identity.principal_id)
            access["session_version"] = int(identity.session_version or 1)
            account_ids = list(
                session.scalars(
                    select(AccountUserMembership.account_id).where(
                        AccountUserMembership.principal_id == identity.principal_id,
                        AccountUserMembership.status == "active",
                    )
                )
            )
            site_ids = list(
                session.scalars(select(Site.site_id).where(Site.account_id.in_(account_ids)))
            )
            if len(site_ids) == 1:
                access["portal_site_id"] = str(site_ids[0])
    _ACCESS_BY_EMAIL[normalized_email] = access
    return access


def _request_portal_registration_code(
    client: TestClient,
    *,
    email: str,
    site_url: str = "",
    site_name: str = "",
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    request_headers = dict(headers or {})
    if (
        str(request_headers.get("x-npcink-debug-portal-link") or "").strip() == "1"
        and "x-npcink-dev-login-code" not in request_headers
    ):
        request_headers["x-npcink-dev-login-code"] = "1"
    payload: dict[str, object] = {"email": email}
    if site_url:
        payload["site_url"] = site_url
    if site_name:
        payload["site_name"] = site_name
    response = client.post(
        "/portal/v1/register/code/request",
        json=payload,
        headers=request_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    _ACCESS_BY_EMAIL[_normalize_test_email(email)] = {
        **_ACCESS_BY_EMAIL.get(_normalize_test_email(email), {}),
        "principal_id": data.get("principal_id") or "",
        "account_id": data.get("account_id") or "",
        "portal_site_id": data.get("site_id") or "",
    }
    return data


def _verify_portal_registration_code(
    client: TestClient,
    *,
    email: str,
    code: str,
) -> dict[str, object]:
    response = client.post(
        "/portal/v1/register/verify",
        json={"email": email, "code": code},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    normalized_email = _normalize_test_email(email)
    services = client.app.state.services
    with get_session(services.settings.database_url) as session:
        identity = session.scalar(select(Principal).where(Principal.email == normalized_email))
        assert identity is not None
        principal_id = str(identity.principal_id)
        session_version = int(identity.session_version or 1)
    addon_accounts_response = client.get("/portal/v1/addon-connection-accounts")
    assert addon_accounts_response.status_code == 200, addon_accounts_response.text
    addon_accounts = addon_accounts_response.json()["data"]["items"]
    assert all(set(item) == {"account_id", "name", "site_count"} for item in addon_accounts)
    access = {
        **_ACCESS_BY_EMAIL.get(normalized_email, {}),
        **data,
        "principal_id": principal_id,
        "session_version": session_version,
    }
    if len(addon_accounts) == 1:
        access["account_id"] = str(addon_accounts[0]["account_id"])
    selected_context = data.get("selected_context") or {}
    selected_site = selected_context.get("site") or {}
    if str(selected_site.get("site_id") or ""):
        access["portal_site_id"] = str(selected_site["site_id"])
    _ACCESS_BY_EMAIL[normalized_email] = access
    return data


def _grant_account_member_access(
    client: TestClient,
    *,
    site_id: str,
    email: str,
    status: str = "active",
    idempotency_key: str = "portal-account-members-001",
) -> dict[str, object]:
    services = client.app.state.services
    with get_session(services.settings.database_url) as session:
        site = session.get(Site, site_id)
        assert site is not None
        account_id = str(site.account_id or "")
    assert account_id
    response = client.post(
        f"/internal/service/accounts/{account_id}/members",
        json={"email": email, "status": status},
        headers=build_internal_headers(idempotency_key=idempotency_key),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    data["portal_site_id"] = site_id
    _ACCESS_BY_EMAIL[_normalize_test_email(email)] = data
    return data


def _portal_headers_for_access(
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


def _set_portal_cookie_session(
    client: TestClient,
    *,
    principal_id: str,
    site_id: str,
    session_version: int = 1,
) -> None:
    settings = client.app.state.services.settings
    client.cookies.set(
        COOKIE_PORTAL_SESSION_TOKEN,
        build_portal_session_token(
            settings,
            principal_id=principal_id,
            site_id=site_id,
            session_version=session_version,
        ),
    )


def _portal_cookie_headers(*, idempotency_key: str = "") -> dict[str, str]:
    return {"Idempotency-Key": idempotency_key} if idempotency_key else {}


def _assert_no_portal_identity_wrapper(data: dict[str, object]) -> None:
    assert PORTAL_INTERNAL_IDENTITY_FIELDS.isdisjoint(data)


def _assert_no_portal_qq_internal_identity_fields(value: object) -> None:
    if isinstance(value, dict):
        assert PORTAL_QQ_INTERNAL_IDENTITY_FIELDS.isdisjoint(value)
        for item in value.values():
            _assert_no_portal_qq_internal_identity_fields(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_portal_qq_internal_identity_fields(item)


def _assert_strict_portal_session(data: dict[str, object]) -> None:
    _assert_no_portal_qq_internal_identity_fields(data)
    assert set(data) == {
        "email",
        "sites",
        "selected_context",
        "auth_mode",
        "session",
    }


def _assert_no_portal_support_internal_fields(value: object) -> None:
    if isinstance(value, dict):
        assert PORTAL_SUPPORT_INTERNAL_FIELDS.isdisjoint(value)
        for item in value.values():
            _assert_no_portal_support_internal_fields(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_portal_support_internal_fields(item)


def _assert_no_bounded_portal_internal_fields(value: object) -> None:
    if isinstance(value, dict):
        assert PORTAL_BOUNDED_PROJECTION_INTERNAL_FIELDS.isdisjoint(value)
        for item in value.values():
            _assert_no_bounded_portal_internal_fields(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_bounded_portal_internal_fields(item)


def _assert_no_portal_commercial_internal_fields(value: object) -> None:
    if isinstance(value, dict):
        assert PORTAL_COMMERCIAL_INTERNAL_FIELDS.isdisjoint(value)
        for item in value.values():
            _assert_no_portal_commercial_internal_fields(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_portal_commercial_internal_fields(item)


def _configure_portal_public_settings(
    client: TestClient,
    *,
    public_base_url: str = "https://cloud.example.com",
    idempotency_prefix: str = "portal-service-settings",
) -> None:
    response = client.patch(
        "/internal/service/admin/service-settings/portal-public",
        json={"public_base_url": public_base_url},
        headers=build_internal_headers(idempotency_key=f"{idempotency_prefix}-public"),
    )
    assert response.status_code == 200, response.text


def _configure_portal_qq_settings(
    client: TestClient,
    *,
    public_base_url: str = "https://cloud.example.com",
    redirect_uri: str | None = None,
    idempotency_prefix: str = "portal-service-settings",
) -> None:
    _configure_portal_public_settings(
        client,
        public_base_url=public_base_url,
        idempotency_prefix=idempotency_prefix,
    )
    response = client.patch(
        "/internal/service/admin/service-settings/qq-login",
        json={
            "client_id": "qq-client-id",
            "client_secret": "qq-client-secret",
            "redirect_uri": redirect_uri
            if redirect_uri is not None
            else f"{public_base_url}/open/auth/qq/callback",
            "scope": "get_user_info",
            "timeout_seconds": 10,
        },
        headers=build_internal_headers(idempotency_key=f"{idempotency_prefix}-qq"),
    )
    assert response.status_code == 200, response.text


def test_portal_support_requests_flow_to_admin_queue(tmp_path: Path) -> None:
    fake_sender = FakePortalEmailSender()
    database_url, client = _build_client(tmp_path, portal_email_sender=fake_sender)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_support", "name": "Portal Support Account"},
        headers=build_internal_headers(idempotency_key="portal-support-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_support",
            "account_id": "acct_portal_support",
            "name": "Portal Support Site",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="portal-support-site-001"),
    )
    grant = _grant_account_member_access(
        client,
        site_id="site_portal_support",
        email="portal-support@example.com",
        idempotency_key="portal-support-account-members-001",
    )
    _set_portal_cookie_session(
        client,
        principal_id=str(grant["principal_id"]),
        site_id="site_portal_support",
        session_version=int(grant.get("session_version") or 1),
    )

    create_response = client.post(
        "/portal/v1/support-requests",
        json={
            "topic": "billing",
            "title": "Payment order needs review",
            "description": "The latest payment order still shows pending after provider return.",
            "site_id": "site_portal_support",
            "source_path": "/portal/billing",
        },
        headers=_portal_cookie_headers(idempotency_key="portal-support-create-001"),
    )
    assert create_response.status_code == 200, create_response.text
    create_data = create_response.json()["data"]
    _assert_no_portal_support_internal_fields(create_data)
    request_item = create_data["request"]
    request_id = request_item["request_id"]
    assert request_item["site_id"] == "site_portal_support"
    assert request_item["topic"] == "billing"
    assert request_item["status"] == "open"

    portal_list_response = client.get(
        "/portal/v1/support-requests?status=open",
    )
    assert portal_list_response.status_code == 200, portal_list_response.text
    portal_list_data = portal_list_response.json()["data"]
    _assert_no_portal_support_internal_fields(portal_list_data)
    portal_items = portal_list_data["items"]
    assert [item["request_id"] for item in portal_items] == [request_id]

    portal_message_response = client.post(
        f"/portal/v1/support-requests/{request_id}/messages",
        json={"body": "Adding the provider reference: alipay-trade-10001."},
        headers=_portal_cookie_headers(idempotency_key="portal-support-message-001"),
    )
    assert portal_message_response.status_code == 200, portal_message_response.text
    portal_message_data = portal_message_response.json()["data"]
    _assert_no_portal_support_internal_fields(portal_message_data)
    assert portal_message_data["message"]["author_kind"] == "customer"

    second_create_response = client.post(
        "/portal/v1/support-requests",
        json={
            "topic": "billing",
            "title": "Separate payment order",
            "description": "This separate payment order is used to verify attachment isolation.",
            "site_id": "site_portal_support",
            "source_path": "/portal/billing",
        },
        headers=_portal_cookie_headers(idempotency_key="portal-support-create-002"),
    )
    assert second_create_response.status_code == 200, second_create_response.text
    second_request_id = second_create_response.json()["data"]["request"]["request_id"]
    cross_request_attachment_response = client.post(
        f"/portal/v1/support-requests/{second_request_id}/attachments",
        json={
            "filename": "cross-request.txt",
            "content_type": "text/plain",
            "content_base64": "Y3Jvc3MgcmVxdWVzdA==",
            "message_id": portal_message_data["message"]["message_id"],
        },
        headers=_portal_cookie_headers(idempotency_key="portal-support-cross-attachment-001"),
    )
    assert cross_request_attachment_response.status_code == 404
    assert (
        cross_request_attachment_response.json()["error_code"]
        == "service.support_request_message_not_found"
    )
    with get_session(database_url) as session:
        assert list(
            session.scalars(
                select(SupportRequestAttachment).where(
                    SupportRequestAttachment.request_id == second_request_id
                )
            )
        ) == []

    admin_update_response = client.patch(
        f"/internal/service/admin/support-requests/{request_id}",
        json={"status": "in_progress", "admin_note": "Checking payment provider event."},
        headers=build_internal_headers(idempotency_key="portal-support-admin-update-001"),
    )
    assert admin_update_response.status_code == 200, admin_update_response.text
    assert admin_update_response.json()["data"]["request"]["status"] == "in_progress"

    admin_public_reply_response = client.post(
        f"/internal/service/admin/support-requests/{request_id}/messages",
        json={
            "body": "We found the provider confirmation and are updating the order.",
            "visibility": "public",
        },
        headers=build_internal_headers(idempotency_key="portal-support-admin-public-001"),
    )
    assert admin_public_reply_response.status_code == 200, admin_public_reply_response.text
    admin_public_payload = admin_public_reply_response.json()["data"]
    assert admin_public_payload["message"]["visibility"] == "public"
    assert admin_public_payload["notification"]["delivered"] is True
    assert fake_sender.messages[-1]["kind"] == "support_request_update"
    assert fake_sender.messages[-1]["recipient_email"] == "portal-support@example.com"

    admin_internal_note_response = client.post(
        f"/internal/service/admin/support-requests/{request_id}/messages",
        json={
            "body": "Internal: payment event arrived after webhook retry.",
            "visibility": "internal",
        },
        headers=build_internal_headers(idempotency_key="portal-support-admin-internal-001"),
    )
    assert admin_internal_note_response.status_code == 200, admin_internal_note_response.text
    assert admin_internal_note_response.json()["data"]["message"]["visibility"] == "internal"

    portal_detail_response = client.get(
        f"/portal/v1/support-requests/{request_id}",
    )
    assert portal_detail_response.status_code == 200, portal_detail_response.text
    portal_detail_data = portal_detail_response.json()["data"]
    _assert_no_portal_support_internal_fields(portal_detail_data)
    portal_messages = portal_detail_data["messages"]
    assert len(portal_messages) == 3
    assert "Internal:" not in "\n".join(message["body"] for message in portal_messages)
    assert "Checking payment provider event." not in portal_detail_response.text

    portal_attachment_response = client.post(
        f"/portal/v1/support-requests/{request_id}/attachments",
        json={
            "filename": "payment-note.txt",
            "content_type": "text/plain",
            "content_base64": "cGF5bWVudCBub3Rl",
        },
        headers=_portal_cookie_headers(idempotency_key="portal-support-attachment-001"),
    )
    assert portal_attachment_response.status_code == 200, portal_attachment_response.text
    portal_attachment_data = portal_attachment_response.json()["data"]
    _assert_no_portal_support_internal_fields(portal_attachment_data)
    portal_attachment = portal_attachment_data["attachment"]

    admin_attachment_response = client.post(
        f"/internal/service/admin/support-requests/{request_id}/attachments",
        json={
            "filename": "operator-note.txt",
            "content_type": "text/plain",
            "content_base64": "aW50ZXJuYWwgbm90ZQ==",
            "visibility": "internal",
        },
        headers=build_internal_headers(idempotency_key="portal-support-admin-attachment-001"),
    )
    assert admin_attachment_response.status_code == 200, admin_attachment_response.text
    admin_attachment = admin_attachment_response.json()["data"]["attachment"]
    assert admin_attachment["visibility"] == "internal"

    portal_attachment_download_response = client.get(
        f"/portal/v1/support-requests/{request_id}/attachments/{portal_attachment['attachment_id']}",
    )
    assert portal_attachment_download_response.status_code == 200
    _assert_no_portal_support_internal_fields(
        portal_attachment_download_response.json()["data"]
    )
    assert (
        portal_attachment_download_response.json()["data"]["attachment"]["content_base64"]
        == "cGF5bWVudCBub3Rl"
    )

    portal_internal_attachment_response = client.get(
        f"/portal/v1/support-requests/{request_id}/attachments/{admin_attachment['attachment_id']}",
    )
    assert portal_internal_attachment_response.status_code == 404

    admin_detail_response = client.get(
        f"/internal/service/admin/support-requests/{request_id}",
        headers=build_internal_headers(),
    )
    assert admin_detail_response.status_code == 200, admin_detail_response.text
    admin_messages = admin_detail_response.json()["data"]["messages"]
    assert [message["visibility"] for message in admin_messages].count("internal") == 2
    admin_attachments = admin_detail_response.json()["data"]["attachments"]
    assert sorted(attachment["visibility"] for attachment in admin_attachments) == [
        "internal",
        "public",
    ]

    admin_list_response = client.get(
        "/internal/service/admin/support-requests?status=in_progress",
        headers=build_internal_headers(),
    )
    assert admin_list_response.status_code == 200, admin_list_response.text
    admin_items = admin_list_response.json()["data"]["items"]
    assert [item["request_id"] for item in admin_items] == [request_id]

    admin_resolve_response = client.patch(
        f"/internal/service/admin/support-requests/{request_id}",
        json={"status": "resolved", "admin_note": ""},
        headers=build_internal_headers(idempotency_key="portal-support-admin-resolve-001"),
    )
    assert admin_resolve_response.status_code == 200, admin_resolve_response.text
    assert admin_resolve_response.json()["data"]["request"]["status"] == "resolved"

    portal_feedback_response = client.post(
        f"/portal/v1/support-requests/{request_id}/feedback",
        json={"resolved": True, "rating": 5, "comment": "Handled clearly."},
        headers=_portal_cookie_headers(idempotency_key="portal-support-feedback-001"),
    )
    assert portal_feedback_response.status_code == 200, portal_feedback_response.text
    portal_feedback_data = portal_feedback_response.json()["data"]
    _assert_no_portal_support_internal_fields(portal_feedback_data)
    assert portal_feedback_data["request"]["status"] == "closed"
    assert portal_feedback_data["feedback"]["rating"] == 5

    portal_reopen_feedback_response = client.post(
        f"/portal/v1/support-requests/{request_id}/feedback",
        json={"resolved": False, "rating": 2, "comment": "The order still needs review."},
        headers=_portal_cookie_headers(idempotency_key="portal-support-feedback-002"),
    )
    assert portal_reopen_feedback_response.status_code == 200, portal_reopen_feedback_response.text
    portal_reopen_feedback_data = portal_reopen_feedback_response.json()["data"]
    _assert_no_portal_support_internal_fields(portal_reopen_feedback_data)
    assert portal_reopen_feedback_data["request"]["status"] == "open"

    fake_sender.support_update_error = "SMTP authentication failed at smtp.internal:465"
    failed_notification_response = client.post(
        f"/internal/service/admin/support-requests/{request_id}/messages",
        json={
            "body": "We are retrying the payment-provider confirmation.",
            "visibility": "public",
        },
        headers=build_internal_headers(
            idempotency_key="portal-support-admin-notification-failure-001"
        ),
    )
    assert failed_notification_response.status_code == 200, failed_notification_response.text
    failed_notification = failed_notification_response.json()["data"]["notification"]
    assert failed_notification == {
        "attempted": True,
        "delivered": False,
        "reason": "delivery_failed",
    }
    assert "smtp.internal" not in failed_notification_response.text

    with get_session(database_url) as session:
        audit_kinds = {
            event.event_kind
            for event in session.scalars(
                select(ServiceAuditEvent).where(
                    ServiceAuditEvent.scope_kind == "support_request",
                    ServiceAuditEvent.scope_id == request_id,
                )
            )
        }
    assert audit_kinds == {
        "support_request.attachment_created",
        "support_request.created",
        "support_request.feedback_submitted",
        "support_request.message_created",
        "support_request.updated",
    }

    dispose_engine(database_url)


def test_portal_remove_site_soft_removes_record_and_revokes_active_keys(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_remove", "name": "Portal Account"},
        headers=build_internal_headers(idempotency_key="portal-remove-account"),
    )
    response = client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_remove",
            "account_id": "acct_portal_remove",
            "name": "Remove Site",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="site-portal-remove-provision"),
    )
    assert response.status_code == 200, response.text
    _grant_account_member_access(
        client,
        site_id="site_portal_remove",
        email="portal-admin@example.com",
        idempotency_key="site-portal-remove-grant",
    )
    key_id = "key_portal_remove"
    issue_response = client.post(
        "/internal/service/sites/site_portal_remove/keys",
        json={
            "key_id": key_id,
            "secret": "portal-remove-secret",
            "label": "Remove Key",
            "scopes": ["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
        },
        headers=build_internal_headers(idempotency_key="portal-remove-issue-key"),
    )
    assert issue_response.status_code == 200, issue_response.text

    remove_response = client.post(
        "/portal/v1/sites/site_portal_remove/remove",
        headers=build_portal_headers(idempotency_key="portal-remove-site"),
    )
    assert remove_response.status_code == 200, remove_response.text
    remove_data = remove_response.json()["data"]
    assert remove_data["site"]["status"] == "archived"
    assert remove_data["revoked_key_ids"] == [key_id]
    _assert_no_portal_commercial_internal_fields(remove_data)

    with get_session(database_url) as session:
        site = session.get(Site, "site_portal_remove")
        assert site is not None
        assert site.status == "archived"
        key = session.get(SiteApiKey, key_id)
        assert key is not None
        assert key.status == "revoked"
        assert key.revoked_at is not None

    audit_response = client.get(
        "/internal/service/audit-events?site_id=site_portal_remove&limit=20",
        headers=build_internal_headers(),
    )
    assert audit_response.status_code == 200
    audit_items = audit_response.json()["data"]["items"]
    assert any(item["event_kind"] == "site.remove" for item in audit_items)
    assert any(item["event_kind"] == "site_key.revoke" for item in audit_items)

    idempotent_response = client.post(
        "/portal/v1/sites/site_portal_remove/remove",
        headers=build_portal_headers(idempotency_key="portal-remove-site-again"),
    )
    assert idempotent_response.status_code == 200, idempotent_response.text
    assert idempotent_response.json()["data"]["site"]["status"] == "archived"
    assert idempotent_response.json()["data"]["revoked_key_ids"] == []

    dispose_engine(database_url)


def test_portal_remove_suspended_site_is_denied(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_remove_suspended", "name": "Portal Account"},
        headers=build_internal_headers(idempotency_key="portal-remove-suspended-account"),
    )
    response = client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_remove_suspended",
            "account_id": "acct_portal_remove_suspended",
            "name": "Remove Suspended",
            "status": "suspended",
        },
        headers=build_internal_headers(idempotency_key="site-remove-suspended-provision"),
    )
    assert response.status_code == 200, response.text
    _grant_account_member_access(
        client,
        site_id="site_remove_suspended",
        email="portal-admin@example.com",
        idempotency_key="site-remove-suspended-grant",
    )

    remove_response = client.post(
        "/portal/v1/sites/site_remove_suspended/remove",
        headers=build_portal_headers(idempotency_key="portal-remove-suspended"),
    )
    assert remove_response.status_code == 403

    with get_session(database_url) as session:
        site = session.get(Site, "site_remove_suspended")
        assert site is not None
        assert site.status == "suspended"

    dispose_engine(database_url)


def test_portal_wordpress_addon_connection_issues_one_time_exchange_code(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)

    registration_request = _request_portal_registration_code(
        client,
        email="addon-connect@example.com",
        site_url="https://primary.example.com",
        site_name="Primary Site",
        headers={
            "x-npcink-debug-portal-link": "1",
            "x-npcink-dev-login-code": "1",
        },
    )
    registration = _verify_portal_registration_code(
        client,
        email="addon-connect@example.com",
        code=str(registration_request["code"]),
    )
    _assert_strict_portal_session(registration)
    addon_accounts_response = client.get("/portal/v1/addon-connection-accounts")
    assert addon_accounts_response.status_code == 200, addon_accounts_response.text
    addon_accounts = addon_accounts_response.json()["data"]["items"]
    assert len(addon_accounts) == 1
    account_id = str(addon_accounts[0]["account_id"])
    assert account_id.startswith("acct_")

    return_url = (
        "https://primary.example.com/wp-admin/admin-post.php"
        "?action=npcink_cloud_addon_complete_auth&state=addon-state-001"
    )
    create_response = client.post(
        "/portal/v1/addon-connections",
        json={
            "account_id": account_id,
            "site_url": "https://primary.example.com",
            "site_name": "Primary Site",
            "return_url": return_url,
            "state": "addon-state-001",
        },
        headers={"Idempotency-Key": "portal-addon-connect-001"},
    )
    assert create_response.status_code == 200, create_response.text
    create_data = create_response.json()["data"]
    assert create_data["site_id"] == "site_primary-example-com"
    assert create_data["site_url"] == "https://primary.example.com"
    assert create_data["platform_kind"] == "wordpress"
    assert create_data["site_created"] is False
    assert create_data["redirect_url"].startswith(
        "https://primary.example.com/wp-admin/admin-post.php?"
    )
    assert "mak1_" not in create_data["redirect_url"]
    assert "sk_" not in create_data["redirect_url"]

    redirect_query = parse_qs(urlsplit(str(create_data["redirect_url"])).query)
    code = redirect_query["code"][0]
    assert redirect_query["state"][0] == "addon-state-001"
    assert code

    exchange_response = client.post(
        "/portal/v1/addon-connections/exchange",
        json={"code": code, "state": "addon-state-001"},
    )
    assert exchange_response.status_code == 200, exchange_response.text
    exchange_data = exchange_response.json()["data"]
    assert exchange_data["site_id"] == "site_primary-example-com"
    assert exchange_data["key_id"] == create_data["key_id"]
    assert exchange_data["cloud_api_key"].startswith("mak1_")
    decoded_key = _decode_customer_key(exchange_data["cloud_api_key"])
    assert decoded_key["site_id"] == "site_primary-example-com"
    assert decoded_key["key_id"] == create_data["key_id"]
    assert decoded_key["secret"].startswith("sk_")

    replay_response = client.post(
        "/portal/v1/addon-connections/exchange",
        json={"code": code, "state": "addon-state-001"},
    )
    assert replay_response.status_code != 200

    with get_session(database_url) as session:
        site = session.get(Site, "site_primary-example-com")
        assert site is not None
        assert site.status == "active"
        assert site.site_url == "https://primary.example.com"
        assert site.platform_kind == "wordpress"
        assert "site_url" not in (site.metadata_json or {})
        assert "url" not in (site.metadata_json or {})

    audit_response = client.get(
        "/internal/service/audit-events?site_id=site_primary-example-com&limit=20",
        headers=build_internal_headers(),
    )
    assert audit_response.status_code == 200
    audit_items = audit_response.json()["data"]["items"]
    assert any(item["event_kind"] == "wordpress_addon_connection.issue" for item in audit_items)

    dispose_engine(database_url)


def test_portal_addon_connection_rejects_cross_account_membership_escalation(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    registration_headers = {
        "x-npcink-debug-portal-link": "1",
        "x-npcink-dev-login-code": "1",
    }
    attacker_request = _request_portal_registration_code(
        client,
        email="cross-account-attacker@example.com",
        site_url="https://cross-account-attacker.example.com",
        site_name="Cross Account Attacker",
        headers=registration_headers,
    )
    attacker = _verify_portal_registration_code(
        client,
        email="cross-account-attacker@example.com",
        code=str(attacker_request["code"]),
    )
    target_request = _request_portal_registration_code(
        client,
        email="cross-account-target@example.com",
        site_url="https://cross-account-target.example.com",
        site_name="Cross Account Target",
        headers=registration_headers,
    )
    target = _verify_portal_registration_code(
        client,
        email="cross-account-target@example.com",
        code=str(target_request["code"]),
    )
    _assert_strict_portal_session(attacker)
    _assert_strict_portal_session(target)
    target_access = _ACCESS_BY_EMAIL["cross-account-target@example.com"]
    attacker_access = _ACCESS_BY_EMAIL["cross-account-attacker@example.com"]
    target_account_id = str(target_access["account_id"])
    attacker_principal_id = str(attacker_access["principal_id"])

    addon_response = client.post(
        "/portal/v1/addon-connections",
        json={
            "account_id": target_account_id,
            "site_url": "https://cross-account-addon.example.com",
            "site_name": "Cross Account Addon",
            "return_url": (
                "https://cross-account-addon.example.com/wp-admin/admin-post.php"
                "?action=npcink_cloud_addon_complete_auth&state=cross-account-state"
            ),
            "state": "cross-account-state",
        },
        headers=_portal_headers_for_access(
            attacker_access,
            idempotency_key="cross-account-addon-denied",
        ),
    )
    assert addon_response.status_code == 403
    assert addon_response.json()["error_code"] == "service.principal_access_required"
    assert addon_response.json()["message"] == "portal account access is required"

    with get_session(database_url) as session:
        membership = session.scalar(
            select(AccountUserMembership).where(
                AccountUserMembership.principal_id == attacker_principal_id,
                AccountUserMembership.account_id == target_account_id,
            )
        )
        assert membership is None
        assert session.get(Site, "site_cross-account-addon-example-com") is None
        assert list(
            session.scalars(
                select(SiteApiKey).where(
                    SiteApiKey.site_id == "site_cross-account-addon-example-com"
                )
            )
        ) == []
        assert list(
            session.scalars(
                select(PortalOAuthState).where(
                    PortalOAuthState.provider == "wordpress_addon_connection"
                )
            )
        ) == []

    dispose_engine(database_url)


def test_portal_addon_connection_requires_provision_sites_action(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    registration_request = _request_portal_registration_code(
        client,
        email="provision-action@example.com",
        site_url="https://provision-action-primary.example.com",
        site_name="Provision Action Primary",
        headers={
            "x-npcink-debug-portal-link": "1",
            "x-npcink-dev-login-code": "1",
        },
    )
    registration = _verify_portal_registration_code(
        client,
        email="provision-action@example.com",
        code=str(registration_request["code"]),
    )
    _assert_strict_portal_session(registration)
    registration_access = _ACCESS_BY_EMAIL["provision-action@example.com"]
    account_id = str(registration_access["account_id"])
    principal_id = str(registration_access["principal_id"])
    with get_session(database_url) as session:
        membership = session.scalar(
            select(AccountUserMembership).where(
                AccountUserMembership.principal_id == principal_id,
                AccountUserMembership.account_id == account_id,
            )
        )
        assert membership is not None
        membership.allowed_actions_json = ["view_sites"]
        session.commit()

    addon_response = client.post(
        "/portal/v1/addon-connections",
        json={
            "account_id": account_id,
            "site_url": "https://provision-action-addon.example.com",
            "site_name": "Provision Action Addon",
            "return_url": (
                "https://provision-action-addon.example.com/wp-admin/admin-post.php"
                "?action=npcink_cloud_addon_complete_auth&state=provision-action-state"
            ),
            "state": "provision-action-state",
        },
        headers=_portal_headers_for_access(
            registration_access,
            idempotency_key="provision-action-addon-denied",
        ),
    )
    assert addon_response.status_code == 403
    assert addon_response.json()["error_code"] == "service.principal_access_required"

    with get_session(database_url) as session:
        assert session.get(Site, "site_provision-action-addon-example-com") is None
        assert list(
            session.scalars(
                select(SiteApiKey).where(
                    SiteApiKey.site_id == "site_provision-action-addon-example-com"
                )
            )
        ) == []
        assert list(
            session.scalars(
                select(PortalOAuthState).where(
                    PortalOAuthState.provider == "wordpress_addon_connection"
                )
            )
        ) == []

    dispose_engine(database_url)


def test_portal_addon_connection_accepts_loopback_alias_and_rejects_other_host(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    registration_request = _request_portal_registration_code(
        client,
        email="addon-loopback@example.com",
        site_url="http://localhost:8080",
        site_name="Loopback Site",
        headers={
            "x-npcink-debug-portal-link": "1",
            "x-npcink-dev-login-code": "1",
        },
    )
    registration = _verify_portal_registration_code(
        client,
        email="addon-loopback@example.com",
        code=str(registration_request["code"]),
    )
    _assert_strict_portal_session(registration)
    account_id = str(_ACCESS_BY_EMAIL["addon-loopback@example.com"]["account_id"])
    payload = {
        "account_id": account_id,
        "site_url": "http://localhost:8080",
        "site_name": "Loopback Site",
        "return_url": (
            "http://127.0.0.1:8080/wp-admin/admin-post.php"
            "?action=npcink_cloud_addon_complete_auth&state=loopback-state"
        ),
        "state": "loopback-state",
    }
    accepted = client.post(
        "/portal/v1/addon-connections",
        json=payload,
        headers={"Idempotency-Key": "portal-addon-loopback-accepted"},
    )
    assert accepted.status_code == 200, accepted.text

    rejected = client.post(
        "/portal/v1/addon-connections",
        json={
            **payload,
            "return_url": "https://other.example.com/wp-admin/admin-post.php",
            "state": "host-mismatch-state",
        },
        headers={"Idempotency-Key": "portal-addon-loopback-rejected"},
    )
    assert rejected.status_code == 400
    assert rejected.json()["error_code"] == "service.wordpress_addon_return_host_mismatch"

    dispose_engine(database_url)


def test_portal_addon_connection_allows_new_site_after_inactive_site_releases_capacity(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)

    registration_request = _request_portal_registration_code(
        client,
        email="addon-capacity@example.com",
        site_url="https://primary.example.com",
        site_name="Primary Site",
        headers={
            "x-npcink-debug-portal-link": "1",
            "x-npcink-dev-login-code": "1",
        },
    )
    registration = _verify_portal_registration_code(
        client,
        email="addon-capacity@example.com",
        code=str(registration_request["code"]),
    )
    _assert_strict_portal_session(registration)
    account_id = str(_ACCESS_BY_EMAIL["addon-capacity@example.com"]["account_id"])

    with get_session(database_url) as session:
        primary_site = session.get(Site, "site_primary-example-com")
        assert primary_site is not None
        primary_site.status = "inactive"
        session.commit()

    return_url = (
        "https://secondary.example.com/wp-admin/admin-post.php"
        "?action=npcink_cloud_addon_complete_auth&state=addon-state-capacity"
    )
    create_response = client.post(
        "/portal/v1/addon-connections",
        json={
            "account_id": account_id,
            "site_url": "https://secondary.example.com",
            "site_name": "Secondary Site",
            "return_url": return_url,
            "state": "addon-state-capacity",
        },
        headers={"Idempotency-Key": "portal-addon-capacity-connect"},
    )
    assert create_response.status_code == 200, create_response.text
    create_data = create_response.json()["data"]
    assert create_data["site_id"] == "site_secondary-example-com"
    assert create_data["site_created"] is True

    with get_session(database_url) as session:
        primary_site = session.get(Site, "site_primary-example-com")
        secondary_site = session.get(Site, "site_secondary-example-com")
        assert primary_site is not None
        assert secondary_site is not None
        assert primary_site.status == "inactive"
        assert secondary_site.status == "active"

    dispose_engine(database_url)


def test_portal_addon_connection_reactivates_existing_inactive_site(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)

    registration_request = _request_portal_registration_code(
        client,
        email="addon-reactivate@example.com",
        site_url="https://primary.example.com",
        site_name="Primary Site",
        headers={
            "x-npcink-debug-portal-link": "1",
            "x-npcink-dev-login-code": "1",
        },
    )
    registration = _verify_portal_registration_code(
        client,
        email="addon-reactivate@example.com",
        code=str(registration_request["code"]),
    )
    _assert_strict_portal_session(registration)
    account_id = str(_ACCESS_BY_EMAIL["addon-reactivate@example.com"]["account_id"])
    with get_session(database_url) as session:
        site = session.get(Site, "site_primary-example-com")
        assert site is not None
        site.status = "inactive"
        site.site_url = ""
        session.commit()
    old_key_response = client.post(
        "/internal/service/sites/site_primary-example-com/keys",
        json={
            "key_id": "key_addon_reconnect_old",
            "secret": "old-addon-reconnect-secret",
            "scopes": ["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
            "label": "Old addon key",
        },
        headers=build_internal_headers(idempotency_key="portal-addon-reactivate-old-key"),
    )
    assert old_key_response.status_code == 200, old_key_response.text

    return_url = (
        "https://primary.example.com/wp-admin/admin-post.php"
        "?action=npcink_cloud_addon_complete_auth&state=addon-state-reactivate"
    )
    create_response = client.post(
        "/portal/v1/addon-connections",
        json={
            "account_id": account_id,
            "site_url": "https://primary.example.com",
            "site_name": "Primary Site",
            "return_url": return_url,
            "state": "addon-state-reactivate",
        },
        headers={"Idempotency-Key": "portal-addon-reactivate-connect"},
    )
    assert create_response.status_code == 200, create_response.text
    create_data = create_response.json()["data"]
    assert create_data["site_id"] == "site_primary-example-com"
    assert create_data["site_created"] is False
    assert create_data["revoked_key_ids"] == ["key_addon_reconnect_old"]

    with get_session(database_url) as session:
        site = session.get(Site, "site_primary-example-com")
        assert site is not None
        assert site.status == "active"
        assert site.site_url == "https://primary.example.com"
        assert site.platform_kind == "wordpress"
        old_key = session.get(SiteApiKey, "key_addon_reconnect_old")
        assert old_key is not None
        assert old_key.status == "revoked"
        active_keys = [
            item
            for item in session.scalars(
                select(SiteApiKey).where(SiteApiKey.site_id == "site_primary-example-com")
            )
            if item.status == "active"
        ]
        assert [item.key_id for item in active_keys] == [create_data["key_id"]]

    dispose_engine(database_url)


def test_portal_addon_connection_reactivates_existing_archived_site(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)

    registration_request = _request_portal_registration_code(
        client,
        email="addon-archived-reactivate@example.com",
        site_url="https://primary.example.com",
        site_name="Primary Site",
        headers={
            "x-npcink-debug-portal-link": "1",
            "x-npcink-dev-login-code": "1",
        },
    )
    registration = _verify_portal_registration_code(
        client,
        email="addon-archived-reactivate@example.com",
        code=str(registration_request["code"]),
    )
    _assert_strict_portal_session(registration)
    account_id = str(
        _ACCESS_BY_EMAIL["addon-archived-reactivate@example.com"]["account_id"]
    )
    with get_session(database_url) as session:
        site = session.get(Site, "site_primary-example-com")
        assert site is not None
        site.status = "archived"
        site.metadata_json = {
            **(site.metadata_json or {}),
            "portal_lifecycle": {
                "previous_status": "active",
                "removed": True,
                "removed_at": "2026-07-09T04:44:35Z",
            },
        }
        session.commit()

    return_url = (
        "https://primary.example.com/wp-admin/admin-post.php"
        "?action=npcink_cloud_addon_complete_auth&state=addon-state-archived-reactivate"
    )
    create_response = client.post(
        "/portal/v1/addon-connections",
        json={
            "account_id": account_id,
            "site_url": "https://primary.example.com",
            "site_name": "Primary Site",
            "return_url": return_url,
            "state": "addon-state-archived-reactivate",
        },
        headers={"Idempotency-Key": "portal-addon-archived-reactivate-connect"},
    )
    assert create_response.status_code == 200, create_response.text
    create_data = create_response.json()["data"]
    assert create_data["site_id"] == "site_primary-example-com"
    assert create_data["site_created"] is False

    with get_session(database_url) as session:
        site = session.get(Site, "site_primary-example-com")
        assert site is not None
        assert site.status == "active"
        lifecycle = (site.metadata_json or {}).get("portal_lifecycle") or {}
        assert lifecycle.get("removed") is None
        assert lifecycle.get("removed_at") is None
        assert lifecycle.get("reconnected_at")
        active_keys = [
            item
            for item in session.scalars(
                select(SiteApiKey).where(SiteApiKey.site_id == "site_primary-example-com")
            )
            if item.status == "active"
        ]
        assert [item.key_id for item in active_keys] == [create_data["key_id"]]

    dispose_engine(database_url)


def test_portal_site_access_rejects_principal_without_account_membership(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_legacy_grant", "name": "Portal Legacy Account"},
        headers=build_internal_headers(idempotency_key="portal-legacy-grant-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_legacy_grant",
            "account_id": "acct_portal_legacy_grant",
            "name": "Portal Legacy Site",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="portal-legacy-grant-site-001"),
    )
    grant = _grant_account_member_access(
        client,
        site_id="site_portal_legacy_grant",
        email="portal-legacy-grant@example.com",
        idempotency_key="portal-legacy-grant-account-members-001",
    )
    with get_session(database_url) as session:
        membership = session.scalar(
            select(AccountUserMembership).where(
                AccountUserMembership.principal_id == str(grant["principal_id"]),
                AccountUserMembership.account_id == "acct_portal_legacy_grant",
            )
        )
        assert membership is not None
        session.delete(membership)
        session.commit()

    response = client.get(
        "/portal/v1/sites/site_portal_legacy_grant/summary",
        headers=_portal_headers_for_access(grant),
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "service.principal_access_required"

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
    grant = _grant_account_member_access(
        client,
        site_id="site_portal_revoked_member",
        email="portal-revoked-member@example.com",
        idempotency_key="portal-revoked-member-account-members-001",
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
        headers=_portal_headers_for_access(grant),
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "service.principal_access_required"

    dispose_engine(database_url)


def test_portal_account_member_can_access_every_site_in_account(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_shared", "name": "Portal Shared Account"},
        headers=build_internal_headers(idempotency_key="portal-revoked-grant-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_shared_primary",
            "account_id": "acct_portal_shared",
            "name": "Portal Shared Primary",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-revoked-grant-site-001"),
    )
    grant = _grant_account_member_access(
        client,
        site_id="site_portal_shared_primary",
        email="portal-shared@example.com",
        idempotency_key="portal-revoked-grant-account-members-001",
    )
    second_site_response = client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_shared_secondary",
            "account_id": "acct_portal_shared",
            "name": "Portal Shared Secondary",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="portal-shared-secondary-site-001"),
    )
    assert second_site_response.status_code == 200

    response = client.get(
        "/portal/v1/sites/site_portal_shared_secondary/summary",
        headers=_portal_headers_for_access(grant),
    )
    assert response.status_code == 200
    sites_response = client.get("/portal/v1/sites", headers=_portal_headers_for_access(grant))
    assert sites_response.status_code == 404

    dispose_engine(database_url)


def test_portal_routes_fail_closed_without_portal_auth(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    response = client.get("/portal/v1/sites/site_portal/summary")

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.portal_session_required"

    dispose_engine(database_url)


def test_portal_routes_require_authenticated_session(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    response = client.get(
        "/portal/v1/sites/site_portal/summary",
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
        "/portal/v1/sites/site_portal/summary",
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
    _grant_account_member_access(
        client,
        site_id="site_portal_ai",
        email="portal-admin@example.com",
        idempotency_key="portal-ai-account-members-001",
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
    assert analysis["ai_disclosure"]["brand_label"] == "Npcink AI"
    assert analysis["agent_handoff"]["agent_id"] == "internal_ops_advisor_agent"
    assert analysis["agent_handoff"]["handoff_type"] == "operator_recommendation"
    assert analysis["agent_handoff"]["requires_operator_review"] is True
    assert analysis["agent_handoff"]["direct_wordpress_write"] is False
    assert "automatic_commercial_state_mutation" in analysis["agent_handoff"]["forbidden_actions"]
    assert "agent_registry_metadata" not in analysis
    assert analysis["agent_metadata_projection"]["agent_id"] == ("internal_ops_advisor_agent")
    assert (
        analysis["agent_metadata_projection"]["agent_role"]
        == analysis["agent_handoff"]["agent_role"]
    )
    assert analysis["agent_metadata_projection"]["direct_wordpress_write"] is False
    assert "cloud_workflow_truth" in analysis["agent_metadata_projection"]["forbidden_actions"]
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
    assert "agent_registry_metadata" not in history_data["items"][0]
    assert history_data["items"][0]["agent_metadata_projection"]["agent_id"] == (
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
    _grant_account_member_access(
        client,
        site_id="site_portal_diag",
        email="portal-diag@example.com",
        idempotency_key="portal-diag-account-members-001",
    )
    key_response = client.post(
        "/internal/service/sites/site_portal_diag/keys",
        json={
            "key_id": "key_portal_diag",
            "secret": "portal-diag-secret",
            "label": "Portal Diagnostics Key",
            "scopes": ["runtime:read"],
        },
        headers=build_internal_headers(idempotency_key="portal-diag-key-001"),
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
    _assert_no_portal_identity_wrapper(data)
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


def test_portal_site_diagnostics_is_scoped_and_available(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_diag_read", "name": "Portal Diagnostics Read"},
        headers=build_internal_headers(idempotency_key="portal-diag-read-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_diag_read",
            "account_id": "acct_portal_diag_read",
            "name": "Portal Diagnostics Read Site",
            "status": "active",
            "site_url": "https://diag-read.example.test",
        },
        headers=build_internal_headers(idempotency_key="portal-diag-read-site-001"),
    )
    _grant_account_member_access(
        client,
        site_id="site_portal_diag_read",
        email="portal-diag-read@example.com",
        idempotency_key="portal-diag-read-account-members-001",
    )
    key_response = client.post(
        "/internal/service/sites/site_portal_diag_read/keys",
        json={
            "key_id": "key_portal_diag_read",
            "secret": "portal-diag-read-secret",
            "label": "Portal Diagnostics Read Key",
            "scopes": ["runtime:read"],
        },
        headers=build_internal_headers(idempotency_key="portal-diag-read-key-001"),
    )
    assert key_response.status_code == 200, key_response.text

    response = client.get(
        "/portal/v1/sites/site_portal_diag_read/diagnostics",
        headers=build_portal_headers(principal_id="principal:portal-diag-read@example.com"),
    )
    outsider = client.get(
        "/portal/v1/sites/site_portal_diag_read/diagnostics",
        headers=build_portal_headers(principal_id="principal:outsider@example.com"),
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["site_id"] == "site_portal_diag_read"
    _assert_no_portal_identity_wrapper(data)
    assert data["site_status"] == "active"
    assert data["site_url"] == "https://diag-read.example.test"
    assert data["active_key_count"] == 1
    assert data["key_summary"]["active"] == 1
    assert data["recent_failures"] == []
    assert {item["code"] for item in data["checks"]} == {
        "site_status",
        "active_key",
        "site_url",
        "recent_failures",
    }
    assert all(item["ok"] for item in data["checks"])
    assert outsider.status_code == 401
    assert outsider.json()["error_code"] == "auth.portal_session_revoked"

    dispose_engine(database_url)


def test_portal_unknown_principal_cannot_access_site_summary(tmp_path: Path) -> None:
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
        "/portal/v1/sites/site_portal_private/summary",
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
    _grant_account_member_access(
        client,
        site_id="site_portal_disabled",
        email="portal-disabled@example.com",
        status="disabled",
        idempotency_key="portal-disabled-account-members-001",
    )

    read_response = client.get(
        "/portal/v1/sites/site_portal_disabled/summary",
        headers=build_portal_headers(principal_id="principal:portal-disabled@example.com"),
    )
    assert read_response.status_code == 401
    assert read_response.json()["error_code"] == "auth.portal_session_revoked"

    write_response = client.post(
        "/portal/v1/sites/site_portal_disabled/remove",
        headers=build_portal_headers(
            principal_id="principal:portal-disabled@example.com",
            idempotency_key="portal-disabled-write-denied-001",
        ),
    )
    assert write_response.status_code == 401
    assert write_response.json()["error_code"] == "auth.portal_session_revoked"

    sites_response = client.get("/portal/v1/sites")
    assert sites_response.status_code == 404

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
    _grant_account_member_access(
        client,
        site_id="site_portal_jwt",
        email="portal-jwt@example.com",
        idempotency_key="portal-jwt-account-members-001",
    )

    response = client.get(
        "/portal/v1/sites/site_portal_jwt/summary",
        headers=build_portal_bearer_headers(
            principal_id="principal:portal-jwt@example.com",
            issuer="npcink-cloud-portal",
            audience="npcink-cloud-customers",
        ),
    )

    assert response.status_code == 200
    assert response.json()["data"]["site"]["site_id"] == "site_portal_jwt"

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
    _grant_account_member_access(
        client,
        site_id="site_portal_unknown_auth",
        email="portal-admin@example.com",
        idempotency_key="portal-unknown-auth-account-members-001",
    )

    response = client.get(
        "/portal/v1/sites/site_portal/summary",
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
        "/portal/v1/sites/site_portal/summary",
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
        "/internal/service/accounts/acct_portal_auth/members",
        json={"email": "portal-auth@example.com"},
        headers=build_internal_headers(idempotency_key="portal-auth-account-members-001"),
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
    assert session_response.json()["data"]["email"] == "portal-auth@example.com"
    assert session_response.json()["data"]["selected_context"] is None
    assert session_response.json()["data"]["session"]["revocable"] is True

    with get_session(database_url) as session:
        identity = session.scalar(
            select(Principal).where(Principal.principal_id == str(consume_data["principal_id"]))
        )
        assert identity is not None
        assert identity.status == PRINCIPAL_STATUS_ACTIVE
        assert identity.last_login_at is not None


def test_one_principal_can_hold_memberships_in_multiple_accounts(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={"portal_jwt_secret": TEST_PORTAL_JWT_SECRET},
    )
    email = "multi-account-principal@example.com"
    principal_ids: list[str] = []

    for suffix in ("alpha", "beta"):
        account_id = f"acct_multi_principal_{suffix}"
        account_response = client.post(
            "/internal/service/accounts",
            json={"account_id": account_id, "name": f"Multi Principal {suffix}"},
            headers=build_internal_headers(
                idempotency_key=f"multi-principal-account-{suffix}"
            ),
        )
        assert account_response.status_code == 200, account_response.text
        membership_response = client.post(
            f"/internal/service/accounts/{account_id}/members",
            json={"email": email},
            headers=build_internal_headers(
                idempotency_key=f"multi-principal-membership-{suffix}"
            ),
        )
        assert membership_response.status_code == 200, membership_response.text
        principal_ids.append(str(membership_response.json()["data"]["principal_id"]))

    assert len(set(principal_ids)) == 1
    principal_id = principal_ids[0]
    login_code = _request_portal_login_code(
        client,
        email=email,
        headers={"x-npcink-debug-portal-link": "1"},
    )
    login_data = _verify_portal_login_code(
        client,
        email=email,
        code=str(login_code["code"]),
    )
    assert login_data["principal_id"] == principal_id

    session_response = client.get("/portal/v1/session")
    assert session_response.status_code == 200, session_response.text
    session_data = session_response.json()["data"]
    assert set(session_data) == {"email", "auth_mode", "session", "sites", "selected_context"}
    assert session_data["sites"] == []
    assert session_data["selected_context"] is None

    addon_accounts_response = client.get("/portal/v1/addon-connection-accounts")
    assert addon_accounts_response.status_code == 200
    addon_accounts = addon_accounts_response.json()["data"]["items"]
    assert all(set(item) == {"account_id", "name", "site_count"} for item in addon_accounts)
    assert {
        item["account_id"] for item in addon_accounts
    } == {"acct_multi_principal_alpha", "acct_multi_principal_beta"}

    with get_session(database_url) as session:
        principals = list(session.scalars(select(Principal).where(Principal.email == email)))
        memberships = list(
            session.scalars(
                select(AccountUserMembership).where(
                    AccountUserMembership.principal_id == principal_id
                )
            )
        )
        assert len(principals) == 1
        assert principals[0].principal_id == principal_id
        assert {membership.account_id for membership in memberships} == {
            "acct_multi_principal_alpha",
            "acct_multi_principal_beta",
        }

    dispose_engine(database_url)


def test_portal_account_email_change_verifies_new_email_before_switching(
    tmp_path: Path,
) -> None:
    fake_sender = FakePortalEmailSender()
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_login_code_ttl_seconds": 300,
        },
        portal_email_sender=fake_sender,
    )
    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_email_change", "name": "Email Change Account"},
        headers=build_internal_headers(idempotency_key="email-change-account"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_email_change",
            "account_id": "acct_email_change",
            "name": "Email Change Site",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="email-change-site"),
    )
    _grant_account_member_access(
        client,
        site_id="site_email_change",
        email="old-email@example.com",
        idempotency_key="email-change-grant",
    )
    login_code = _request_portal_login_code(
        client,
        email="old-email@example.com",
        headers={"x-npcink-debug-portal-link": "1"},
    )
    _verify_portal_login_code(
        client,
        email="old-email@example.com",
        code=str(login_code["code"]),
    )

    request_response = client.post(
        "/portal/v1/account/email-change/request",
        json={"new_email": "new-email@example.com", "locale": "zh-CN"},
        headers={
            "Idempotency-Key": "email-change-request",
            "x-npcink-dev-login-code": "1",
        },
    )

    assert request_response.status_code == 200, request_response.text
    request_data = request_response.json()["data"]
    assert request_data["old_email"] == "old-email@example.com"
    assert request_data["new_email"] == "new-email@example.com"
    assert request_data["delivery"] == "development_code"
    assert request_data["code"] != ""
    assert fake_sender.messages[-1]["kind"] == "email_change_code"
    assert fake_sender.messages[-1]["recipient_email"] == "new-email@example.com"

    with get_session(database_url) as session:
        identity = session.scalar(
            select(Principal).where(Principal.email == "old-email@example.com")
        )
        assert identity is not None
        original_principal_id = identity.principal_id

    verify_response = client.post(
        "/portal/v1/account/email-change/verify",
        json={"new_email": "new-email@example.com", "code": request_data["code"]},
        headers={"Idempotency-Key": "email-change-verify"},
    )

    assert verify_response.status_code == 200, verify_response.text
    verify_data = verify_response.json()["data"]
    assert verify_data["email"] == "new-email@example.com"
    assert verify_data["old_email"] == "old-email@example.com"
    assert verify_data["new_email"] == "new-email@example.com"
    assert "principal_id" not in verify_data
    assert fake_sender.messages[-1]["kind"] == "email_changed_notice"
    assert fake_sender.messages[-1]["recipient_email"] == "old-email@example.com"

    with get_session(database_url) as session:
        assert (
            session.scalar(select(Principal).where(Principal.email == "old-email@example.com"))
            is None
        )
        identity = session.scalar(
            select(Principal).where(Principal.email == "new-email@example.com")
        )
        assert identity is not None
        assert identity.principal_id == original_principal_id
        audit_event = session.scalar(
            select(ServiceAuditEvent)
            .where(ServiceAuditEvent.event_kind == "principal.email_change")
            .order_by(ServiceAuditEvent.id.desc())
        )
        assert audit_event is not None
        assert audit_event.actor_kind == "principal"
        assert audit_event.actor_ref == identity.principal_id
        assert audit_event.scope_kind == "principal"
        assert audit_event.scope_id == identity.principal_id
        assert audit_event.payload_json == {
            "principal_id": identity.principal_id,
            "old_email": "old-email@example.com",
            "new_email": "new-email@example.com",
        }

    old_login_response = client.post(
        "/portal/v1/auth/code/request",
        json={"email": "old-email@example.com"},
        headers={"x-npcink-debug-portal-link": "1"},
    )
    assert old_login_response.status_code == 200
    assert old_login_response.json()["data"]["code"] == ""

    new_login_data = _request_portal_login_code(
        client,
        email="new-email@example.com",
        headers={"x-npcink-debug-portal-link": "1"},
    )
    assert new_login_data["code"] != ""


def test_portal_auth_login_code_remember_me_extends_cookie_session(tmp_path: Path) -> None:
    _database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_jwt_issuer": "npcink-cloud-portal",
            "portal_jwt_audience": "npcink-cloud-customers",
            "portal_session_ttl_seconds": 900,
            "portal_remember_me_session_ttl_seconds": 7 * 24 * 60 * 60,
            "portal_login_code_ttl_seconds": 300,
        },
    )

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_remember", "name": "Portal Remember Account"},
        headers=build_internal_headers(idempotency_key="portal-remember-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_remember",
            "account_id": "acct_portal_remember",
            "name": "Portal Remember Site",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="portal-remember-site-001"),
    )
    client.post(
        "/internal/service/accounts/acct_portal_remember/members",
        json={"email": "portal-remember@example.com"},
        headers=build_internal_headers(idempotency_key="portal-remember-account-members-001"),
    )

    request_data = _request_portal_login_code(
        client,
        email="portal-remember@example.com",
        headers={"x-npcink-debug-portal-link": "1"},
    )
    verified_at = datetime.now(UTC)
    consume_data = _verify_portal_login_code(
        client,
        email="portal-remember@example.com",
        code=str(request_data["code"]),
        remember_me=True,
    )

    expires_at = datetime.fromisoformat(
        str(consume_data["session"]["expires_at"]).replace("Z", "+00:00")
    )
    assert (
        timedelta(days=6, hours=23)
        <= expires_at - verified_at
        <= timedelta(
            days=7,
            minutes=1,
        )
    )


def test_portal_qq_bind_and_callback_login_reuse_user_session(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
        },
    )
    _configure_portal_qq_settings(client, idempotency_prefix="portal-qq-settings")

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
    _grant_account_member_access(
        client,
        site_id="site_portal_qq",
        email="portal-qq@example.com",
        idempotency_key="portal-qq-account-members-001",
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
    principal_id = str(_ACCESS_BY_EMAIL["portal-qq@example.com"]["principal_id"])
    initial_provider_response = client.get("/portal/v1/auth/identity-providers")
    assert initial_provider_response.status_code == 200, initial_provider_response.text
    initial_provider_payload = initial_provider_response.json()["data"]
    _assert_no_portal_qq_internal_identity_fields(initial_provider_payload)
    assert set(initial_provider_payload) == {"providers"}
    initial_provider_data = initial_provider_payload["providers"][0]
    assert initial_provider_data["provider"] == "qq"
    assert initial_provider_data["configured"] is True
    assert initial_provider_data["bound"] is False
    assert initial_provider_data["binding"] is None

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
    bind_data = bind_response.json()["data"]
    _assert_no_portal_qq_internal_identity_fields(bind_data)
    assert set(bind_data) == {"binding"}
    assert set(bind_data["binding"]) == {
        "binding_id",
        "provider",
        "status",
        "has_unionid",
        "last_login_at",
    }
    assert bind_data["binding"]["provider"] == "qq"
    assert bind_data["binding"]["status"] == "active"
    assert bind_data["binding"]["has_unionid"] is True
    bound_provider_response = client.get("/portal/v1/auth/identity-providers")
    assert bound_provider_response.status_code == 200, bound_provider_response.text
    bound_provider_payload = bound_provider_response.json()["data"]
    _assert_no_portal_qq_internal_identity_fields(bound_provider_payload)
    bound_provider_data = bound_provider_payload["providers"][0]
    assert bound_provider_data["bound"] is True
    assert bound_provider_data["binding"]["provider"] == "qq"
    assert bound_provider_data["binding"]["status"] == "active"

    with get_session(database_url) as session:
        binding = session.scalar(select(IdentityProviderBinding))
        assert binding is not None
        assert binding.principal_id == principal_id
        assert binding.provider == "qq"
        assert binding.external_subject_hash != "qq-openid-001"
        assert binding.unionid_hash != "qq-union-001"

    logout_response = client.post("/portal/v1/logout")
    assert logout_response.status_code == 200

    login_start_response = client.get("/portal/v1/auth/qq/start?return_to=/portal/usage")
    assert login_start_response.status_code == 200
    login_state = login_start_response.json()["data"]["state"]

    callback_response = client.get(
        f"/open/auth/qq/callback?code=login-code&state={login_state}",
    )
    assert callback_response.status_code == 200, callback_response.text
    callback_data = callback_response.json()["data"]
    _assert_strict_portal_session(callback_data)
    assert callback_data["email"] == "portal-qq@example.com"
    assert callback_data["session"]["transport"] == "cookie"

    dispose_engine(database_url)


def test_portal_qq_callback_bind_intent_binds_current_session(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
        },
    )
    _configure_portal_qq_settings(client, idempotency_prefix="portal-qq-callback-bind")

    monkeypatch.setattr(
        portal_routes,
        "_exchange_qq_code",
        lambda request, *, code: {"access_token": f"token-{code}"},
    )
    monkeypatch.setattr(
        portal_routes,
        "_fetch_qq_openid",
        lambda request, *, access_token: {
            "openid": "qq-openid-callback-bind",
            "unionid": "qq-union-callback-bind",
        },
    )

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_qq_callback_bind", "name": "Portal QQ Bind"},
        headers=build_internal_headers(idempotency_key="portal-qq-callback-bind-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_qq_callback_bind",
            "account_id": "acct_portal_qq_callback_bind",
            "name": "Portal QQ Bind Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-qq-callback-bind-site-001"),
    )
    _grant_account_member_access(
        client,
        site_id="site_portal_qq_callback_bind",
        email="portal-qq-callback-bind@example.com",
        idempotency_key="portal-qq-callback-bind-account-members-001",
    )
    request_data = _request_portal_login_code(
        client,
        email="portal-qq-callback-bind@example.com",
        headers={"x-npcink-debug-portal-link": "1"},
    )
    _verify_portal_login_code(
        client,
        email="portal-qq-callback-bind@example.com",
        code=str(request_data["code"]),
    )
    principal_id = str(
        _ACCESS_BY_EMAIL["portal-qq-callback-bind@example.com"]["principal_id"]
    )

    start_response = client.get("/portal/v1/auth/qq/start?intent=bind&return_to=/portal/account")
    assert start_response.status_code == 200
    start_data = start_response.json()["data"]
    assert start_data["intent"] == "bind"

    callback_response = client.get(
        f"/open/auth/qq/callback?code=bind-code&state={start_data['state']}",
    )
    assert callback_response.status_code == 200, callback_response.text
    callback_data = callback_response.json()["data"]
    _assert_no_portal_qq_internal_identity_fields(callback_data)
    assert set(callback_data) == {"status", "provider", "return_to", "binding"}
    assert callback_data["status"] == "bound"
    assert callback_data["provider"] == "qq"
    assert callback_data["return_to"] == "/portal/account"
    assert callback_data["binding"]["provider"] == "qq"

    provider_response = client.get("/portal/v1/auth/identity-providers")
    assert provider_response.status_code == 200, provider_response.text
    provider_payload = provider_response.json()["data"]
    _assert_no_portal_qq_internal_identity_fields(provider_payload)
    provider_data = provider_payload["providers"][0]
    assert provider_data["bound"] is True
    assert provider_data["binding"]["has_unionid"] is True

    with get_session(database_url) as session:
        binding = session.scalar(select(IdentityProviderBinding))
        assert binding is not None
        assert binding.principal_id == principal_id
        assert binding.provider == "qq"

    dispose_engine(database_url)


def test_portal_qq_start_rejects_redirect_uri_outside_allowlist(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
    )
    _configure_portal_public_settings(
        client,
        public_base_url="https://cloud.example.com",
        idempotency_prefix="portal-qq-bad-redirect-settings",
    )
    bad_redirect_response = client.patch(
        "/internal/service/admin/service-settings/qq-login",
        json={
            "client_id": "qq-client-id",
            "client_secret": "qq-client-secret",
            "redirect_uri": "https://evil.example.com/open/auth/qq/callback",
            "scope": "get_user_info",
            "timeout_seconds": 10,
        },
        headers=build_internal_headers(idempotency_key="portal-qq-bad-redirect-settings-qq"),
    )
    assert bad_redirect_response.status_code == 400

    start_response = client.get("/portal/v1/auth/qq/start")
    assert start_response.status_code == 503
    assert start_response.json()["error_code"] == "portal.qq_login_not_configured"

    dispose_engine(database_url)


def test_open_reserved_callbacks_fail_closed(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    wechat_login_response = client.get("/open/auth/wechat/callback?code=abc&state=xyz")
    assert wechat_login_response.status_code == 501
    wechat_login_data = wechat_login_response.json()
    assert wechat_login_data["error_code"] == "open.wechat_login_not_enabled"
    assert wechat_login_data["data"]["mutation_applied"] is False

    alipay_notify_response = client.post(
        "/open/payments/alipay/notify",
        json={"out_trade_no": "pay_001"},
    )
    assert alipay_notify_response.status_code == 501
    assert alipay_notify_response.json()["error_code"] == ("open.alipay_payment_notify_not_enabled")

    alipay_return_response = client.get("/open/payments/alipay/return")
    assert alipay_return_response.status_code == 501
    assert alipay_return_response.json()["data"]["callback_kind"] == "payment_return"

    wechat_notify_response = client.post(
        "/open/payments/wechat/notify",
        json={"out_trade_no": "pay_002"},
    )
    assert wechat_notify_response.status_code == 501
    assert wechat_notify_response.json()["error_code"] == ("open.wechat_payment_notify_not_enabled")

    dispose_engine(database_url)


def test_portal_qq_bind_rejects_nonce_mismatch(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
        },
    )
    _configure_portal_qq_settings(client, idempotency_prefix="portal-qq-nonce-settings")

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
    _grant_account_member_access(
        client,
        site_id="site_portal_qq_nonce",
        email="portal-qq-nonce@example.com",
        idempotency_key="portal-qq-nonce-account-members-001",
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
        },
    )
    _configure_portal_qq_settings(client, idempotency_prefix="portal-qq-conflict-settings")

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
    _grant_account_member_access(
        client,
        site_id="site_portal_qq_conflict_a",
        email="portal-qq-conflict-a@example.com",
        idempotency_key="portal-qq-conflict-account-members-a-001",
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

    _grant_account_member_access(
        client,
        site_id="site_portal_qq_conflict_b",
        email="portal-qq-conflict-b@example.com",
        idempotency_key="portal-qq-conflict-account-members-b-001",
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
        },
    )
    _configure_portal_qq_settings(client, idempotency_prefix="portal-qq-unbind-settings")

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
    _grant_account_member_access(
        client,
        site_id="site_portal_qq_unbind",
        email="portal-qq-unbind@example.com",
        idempotency_key="portal-qq-unbind-account-members-001",
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
    principal_id = str(_ACCESS_BY_EMAIL["portal-qq-unbind@example.com"]["principal_id"])
    start_response = client.get("/portal/v1/auth/qq/start")
    assert start_response.status_code == 200
    bind_response = client.post(
        "/portal/v1/auth/qq/bind",
        json={"code": "bind-code", "state": start_response.json()["data"]["state"]},
    )
    assert bind_response.status_code == 200, bind_response.text

    unbind_response = client.post("/portal/v1/auth/qq/unbind", json={"provider": "qq"})
    assert unbind_response.status_code == 200
    unbind_data = unbind_response.json()["data"]
    _assert_no_portal_qq_internal_identity_fields(unbind_data)
    assert unbind_data == {"provider": "qq", "revoked": 1}

    with get_session(database_url) as session:
        identity = session.get(Principal, principal_id)
        binding = session.scalar(select(IdentityProviderBinding))
        assert identity is not None
        assert identity.principal_id == principal_id
        assert binding is not None
        assert binding.principal_id == principal_id

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
        },
    )
    _configure_portal_qq_settings(client, idempotency_prefix="portal-qq-unbound-settings")

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

    callback_response = client.get(f"/open/auth/qq/callback?code=qq-code&state={state}")
    assert callback_response.status_code == 200, callback_response.text
    data = callback_response.json()["data"]
    _assert_no_portal_qq_internal_identity_fields(data)
    assert set(data) == {"status", "provider", "return_to"}
    assert data["status"] == "binding_required"
    assert data["provider"] == "qq"
    assert data["return_to"] == "/portal"

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
    _grant_account_member_access(
        client,
        site_id="site_portal_mail",
        email="portal-mail@example.com",
        idempotency_key="portal-mail-account-members-001",
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


def test_portal_login_code_request_fails_when_email_delivery_not_configured(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
        },
    )

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_mail_missing", "name": "Portal Mail Missing"},
        headers=build_internal_headers(idempotency_key="portal-mail-missing-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_mail_missing",
            "account_id": "acct_portal_mail_missing",
            "name": "Portal Mail Missing Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-mail-missing-site-001"),
    )
    client.post(
        "/internal/service/sites/site_portal_mail_missing/activate",
        headers=build_internal_headers(idempotency_key="portal-mail-missing-site-activate-001"),
    )
    _grant_account_member_access(
        client,
        site_id="site_portal_mail_missing",
        email="portal-mail-missing@example.com",
        idempotency_key="portal-mail-missing-account-members-001",
    )

    response = client.post(
        "/portal/v1/auth/code/request",
        json={"email": "portal-mail-missing@example.com", "locale": "zh-CN"},
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "portal.email_not_configured"

    dispose_engine(database_url)


def test_portal_registration_code_request_uses_registration_sender(
    tmp_path: Path,
) -> None:
    fake_sender = FakePortalEmailSender()
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_login_code_ttl_seconds": 300,
        },
        portal_email_sender=fake_sender,
    )

    request_data = _request_portal_registration_code(
        client,
        email="registration-mail@example.com",
        site_url="https://registration.example.com",
        site_name="Registration Demo Site",
    )

    assert request_data["delivery"] == "email"
    assert request_data["code"] == ""
    assert len(fake_sender.messages) == 1
    assert fake_sender.messages[0]["kind"] == "registration_code"
    assert fake_sender.messages[0]["recipient_email"] == "registration-mail@example.com"
    assert fake_sender.messages[0]["site_name"] == "Registration Demo Site"
    assert fake_sender.messages[0]["site_url"] == "https://registration.example.com"

    dispose_engine(database_url)


def test_portal_site_payloads_fail_closed_on_superseded_url_field(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    superseded_field = "wordpress" + "_url"

    responses = [
        client.post(
            "/portal/v1/register/code/request",
            json={"email": "legacy@example.com", superseded_field: "https://legacy.test"},
        ),
        client.post(
            "/portal/v1/addon-connections",
            json={
                "account_id": "acct_legacy",
                superseded_field: "https://legacy.test",
                "return_url": "https://legacy.test/wp-admin/admin-post.php",
                "state": "legacy-state",
            },
        ),
    ]

    assert [response.status_code for response in responses] == [422, 422]
    dispose_engine(database_url)


def test_portal_login_code_request_masks_missing_principal_access(
    tmp_path: Path,
) -> None:
    fake_sender = FakePortalEmailSender()
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
        },
        portal_email_sender=fake_sender,
    )

    response = client.post(
        "/portal/v1/auth/code/request",
        json={"email": "outsider@example.com"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["delivery"] == "email"
    assert response.json()["data"]["code"] == ""
    assert fake_sender.messages == []

    dispose_engine(database_url)


def test_portal_self_registration_opens_free_account_and_session(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_login_code_ttl_seconds": 300,
        },
    )

    request_data = _request_portal_registration_code(
        client,
        email="new-portal-user@example.com",
        headers={"x-npcink-debug-portal-link": "1"},
    )

    assert request_data["delivery"] == "development_code"
    assert request_data["expires_in_seconds"] == 300
    assert request_data["code"] != ""
    assert request_data["site"]["site_id"] == ""
    assert request_data["site"]["site_url"] == ""
    assert request_data["site"]["platform_kind"] == "wordpress"

    registration_data = _verify_portal_registration_code(
        client,
        email="new-portal-user@example.com",
        code=str(request_data["code"]),
    )

    _assert_strict_portal_session(registration_data)
    assert registration_data["email"] == "new-portal-user@example.com"
    assert registration_data["sites"] == []
    assert registration_data["selected_context"] is None
    assert registration_data["session"]["state"] == "active"
    assert registration_data["session"]["transport"] == "cookie"

    session_response = client.get("/portal/v1/session")
    assert session_response.status_code == 200
    session_data = session_response.json()["data"]
    _assert_strict_portal_session(session_data)
    assert session_data["email"] == registration_data["email"]
    assert session_data["sites"] == []
    assert session_data["selected_context"] is None

    with get_session(database_url) as session:
        identity = session.scalar(
            select(Principal).where(
                Principal.email == "new-portal-user@example.com"
            )
        )
        assert identity is not None
        assert identity.status == PRINCIPAL_STATUS_ACTIVE
        assert identity.email == "new-portal-user@example.com"
        assert identity.principal_id.startswith("prn_")
        account_membership = session.scalar(
            select(AccountUserMembership).where(
                AccountUserMembership.principal_id == identity.principal_id
            )
        )
        assert account_membership is not None
        assert account_membership.status == "active"
        account_id = account_membership.account_id
        assert account_id.startswith("acct_")
        site_count = len(list(session.scalars(select(Site))))
        assert site_count == 0
        subscription = session.scalar(
            select(AccountSubscription).where(
                AccountSubscription.account_id == account_id
            )
        )
        assert subscription is not None
        assert subscription.plan_id == "free"
        assert subscription.plan_version_id == "free_v1"
        assert subscription.status == "active"
        assert (subscription.metadata_json or {})["source"] == "production_default_free_bind_v1"
        entitlement_snapshot = session.scalar(
            select(AccountEntitlementSnapshot).where(
                AccountEntitlementSnapshot.account_id == account_id,
                AccountEntitlementSnapshot.status == "active",
            )
        )
        assert entitlement_snapshot is not None
        assert entitlement_snapshot.subscription_id == subscription.subscription_id
        assert entitlement_snapshot.plan_version_id == "free_v1"
        assert entitlement_snapshot.site_limit == 1
        assert entitlement_snapshot.budgets_json["max_ai_credits_per_period"] == 300
        assert entitlement_snapshot.concurrency_json["max_active_runs"] == 1

    second_request_data = _request_portal_registration_code(
        client,
        email="new-portal-user@example.com",
        headers={"x-npcink-debug-portal-link": "1"},
    )
    second_registration_data = _verify_portal_registration_code(
        client,
        email="new-portal-user@example.com",
        code=str(second_request_data["code"]),
    )
    _assert_strict_portal_session(second_registration_data)
    assert second_registration_data["email"] == registration_data["email"]
    assert second_registration_data["sites"] == []
    assert second_registration_data["selected_context"] is None
    with get_session(database_url) as session:
        site_count = len(list(session.scalars(select(Site))))
        subscription_count = len(list(session.scalars(select(AccountSubscription))))
    assert site_count == 0
    assert subscription_count == 1

    dispose_engine(database_url)


def test_portal_user_can_start_pro_trial_and_create_monthly_order(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_login_code_ttl_seconds": 300,
        },
    )
    request_data = _request_portal_registration_code(
        client,
        email="pro-trial-user@example.com",
        headers={"x-npcink-debug-portal-link": "1"},
    )
    registration = _verify_portal_registration_code(
        client,
        email="pro-trial-user@example.com",
        code=str(request_data["code"]),
    )
    _assert_strict_portal_session(registration)
    registration_access = _ACCESS_BY_EMAIL["pro-trial-user@example.com"]
    account_id = str(registration_access["account_id"])
    principal_id = str(registration_access["principal_id"])
    site_id = "site_portal_pro_trial_user"
    site_response = client.post(
        "/internal/service/sites",
        json={
            "site_id": site_id,
            "account_id": account_id,
            "name": "Pro Trial User Site",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="portal-pro-trial-site-001"),
    )
    assert site_response.status_code == 200, site_response.text

    offers_response = client.get(
        "/portal/v1/account/plan-offers",
        headers=build_portal_headers(principal_id=principal_id, site_id=site_id),
    )
    assert offers_response.status_code == 200, offers_response.text
    _assert_no_portal_commercial_internal_fields(offers_response.json()["data"])
    assert [item["tier_id"] for item in offers_response.json()["data"]["items"]] == [
        "plus",
        "pro",
    ]
    comparison_tiers = offers_response.json()["data"]["comparison_tiers"]
    assert [item["tier_id"] for item in comparison_tiers] == ["free", "plus", "pro"]
    assert comparison_tiers[0]["monthly_points"] == 300
    assert comparison_tiers[1]["site_limit"] == 3
    assert comparison_tiers[2]["knowledge_article_limit"] == 2000
    assert comparison_tiers[0]["comparison_rights"]["monthly_points"]["state"] == "limited"
    assert comparison_tiers[1]["comparison_rights"]["site_limit"] == {
        "state": "limited",
        "value": 3,
    }
    eligible_trial = offers_response.json()["data"]["trial"]
    assert eligible_trial["available"] is True
    assert eligible_trial["trial_days"] == 14
    assert eligible_trial["state"] == "eligible"
    assert eligible_trial["reason_code"] == "trial_available"
    assert eligible_trial["allowed_tiers"] == ["plus", "pro"]

    trial_response = client.post(
        "/portal/v1/account/plan-trials",
        json={"tier_id": "pro"},
        headers=build_portal_headers(
            principal_id=principal_id,
            site_id=site_id,
            idempotency_key="portal-pro-trial-start-001",
        ),
    )
    assert trial_response.status_code == 200, trial_response.text
    trial_data = trial_response.json()["data"]
    assert trial_data["subscription"]["plan_id"] == "pro"
    assert trial_data["subscription"]["status"] == "trialing"
    assert trial_data["trial"]["tier_id"] == "pro"
    assert trial_data["trial"]["trial_days"] == 14
    _assert_no_portal_commercial_internal_fields(
        {key: value for key, value in trial_data.items() if key != "session"}
    )
    trial_session = trial_data["session"]
    _assert_strict_portal_session(trial_session)
    assert trial_session["selected_context"]["site"]["site_id"] == site_id
    assert trial_session["selected_context"]["current_subscription"]["plan_id"] == "pro"

    active_offers_response = client.get(
        "/portal/v1/account/plan-offers",
        headers=build_portal_headers(principal_id=principal_id, site_id=site_id),
    )
    assert active_offers_response.status_code == 200, active_offers_response.text
    active_trial = active_offers_response.json()["data"]["trial"]
    assert active_trial["state"] == "active"
    assert active_trial["reason_code"] == "trial_active"
    assert active_trial["allowed_tiers"] == []
    assert active_trial["trial_ends_at"]

    order_response = client.post(
        "/portal/v1/account/subscription-orders",
        json={"offer_id": "pro_monthly_v1", "provider": "alipay"},
        headers=build_portal_headers(
            principal_id=principal_id,
            site_id=site_id,
            idempotency_key="portal-pro-monthly-order-001",
        ),
    )
    assert order_response.status_code == 200, order_response.text
    order_payload = order_response.json()["data"]
    order = order_payload["order"]
    assert order["amount"] == 29.0
    assert order["currency"] == "CNY"
    assert order["provider"] == "alipay"
    assert order["purchase_kind"] == "subscription_plan"
    assert order["subscription_id"] == trial_data["subscription"]["subscription_id"]
    assert order["target_tier_id"] == "pro"
    _assert_no_portal_commercial_internal_fields(order_payload)

    payment_orders_response = client.get(
        "/portal/v1/account/payment-orders?limit=10",
        headers=build_portal_headers(principal_id=principal_id, site_id=site_id),
    )
    assert payment_orders_response.status_code == 200, payment_orders_response.text
    payment_orders_data = payment_orders_response.json()["data"]
    _assert_no_portal_identity_wrapper(payment_orders_data)
    _assert_no_portal_commercial_internal_fields(payment_orders_data)
    assert payment_orders_data["status_group"] == "all"
    assert payment_orders_data["counts"] == {
        "all": 1,
        "pending": 1,
        "paid": 0,
        "closed": 0,
    }
    assert payment_orders_data["visibility"] == {
        "canceled_orders_visible_days": 7,
        "database_records_deleted": False,
    }
    assert payment_orders_data["pagination"]["total"] == 1
    listed_order = payment_orders_data["items"][0]
    assert listed_order["order_id"] == order["order_id"]
    assert listed_order["amount"] == 29.0
    assert listed_order["currency"] == "CNY"
    assert listed_order["purchase_kind"] == "subscription_plan"
    assert listed_order["site_id"] == ""
    assert listed_order["status"] == "pending"
    assert listed_order["target_tier_id"] == "pro"
    assert listed_order["expires_at"]

    order_detail_response = client.get(
        f"/portal/v1/account/payment-orders/{order['order_id']}",
        headers=build_portal_headers(principal_id=principal_id, site_id=site_id),
    )
    assert order_detail_response.status_code == 200, order_detail_response.text
    order_detail = order_detail_response.json()["data"]
    _assert_no_portal_identity_wrapper(order_detail)
    _assert_no_portal_commercial_internal_fields(order_detail)
    assert order_detail["order"]["order_id"] == order["order_id"]
    assert order_detail["order"]["status"] == "pending"

    cancel_response = client.delete(
        "/portal/v1/account/subscription-orders/"
        f"{order_payload['subscription_order']['subscription_order_id']}",
        headers=build_portal_headers(
            principal_id=principal_id,
            site_id=site_id,
            idempotency_key="portal-pro-monthly-order-cancel-001",
        ),
    )
    assert cancel_response.status_code == 200, cancel_response.text
    canceled_order = cancel_response.json()["data"]["order"]
    assert canceled_order["status"] == "canceled"
    assert canceled_order["checkout_url"] == ""
    _assert_no_portal_commercial_internal_fields(cancel_response.json()["data"])

    closed_orders_response = client.get(
        "/portal/v1/account/payment-orders?status_group=closed&limit=10",
        headers=build_portal_headers(principal_id=principal_id, site_id=site_id),
    )
    assert closed_orders_response.status_code == 200, closed_orders_response.text
    closed_orders_data = closed_orders_response.json()["data"]
    assert closed_orders_data["status_group"] == "closed"
    assert closed_orders_data["pagination"]["total"] == 1
    assert closed_orders_data["counts"] == {
        "all": 1,
        "pending": 0,
        "paid": 0,
        "closed": 1,
    }
    assert closed_orders_data["items"][0]["order_id"] == order["order_id"]

    downgrade_response = client.post(
        "/portal/v1/account/free-downgrade",
        headers=build_portal_headers(
            principal_id=principal_id,
            site_id=site_id,
            idempotency_key="portal-pro-free-downgrade-001",
        ),
    )
    assert downgrade_response.status_code == 200, downgrade_response.text
    downgrade_data = downgrade_response.json()["data"]
    assert set(downgrade_data) == {"scheduled_tier_id", "scheduled_change_at"}
    assert downgrade_data["scheduled_tier_id"] == "free"
    assert downgrade_data["scheduled_change_at"]
    _assert_no_portal_commercial_internal_fields(downgrade_data)

    with get_session(database_url) as session:
        subscriptions = list(
            session.scalars(
                select(AccountSubscription).where(AccountSubscription.account_id == account_id)
            )
        )
        assert {item.plan_id: item.status for item in subscriptions} == {
            "free": "canceled",
            "pro": "trialing",
        }
        payment_order = session.scalar(
            select(PaymentOrder).where(PaymentOrder.order_id == order["order_id"])
        )
        assert payment_order is not None
        assert payment_order.amount == 29.0
        assert payment_order.currency == "CNY"

    dispose_engine(database_url)


def test_portal_shared_trial_and_admin_agency_quote_contract(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_login_code_ttl_seconds": 300,
        },
    )
    request_data = _request_portal_registration_code(
        client,
        email="shared-paid-trial@example.com",
        headers={"x-npcink-debug-portal-link": "1"},
    )
    registration = _verify_portal_registration_code(
        client,
        email="shared-paid-trial@example.com",
        code=str(request_data["code"]),
    )
    _assert_strict_portal_session(registration)
    registration_access = _ACCESS_BY_EMAIL["shared-paid-trial@example.com"]
    account_id = str(registration_access["account_id"])
    principal_id = str(registration_access["principal_id"])
    site_id = "site_portal_shared_paid_trial"
    site_response = client.post(
        "/internal/service/sites",
        json={
            "site_id": site_id,
            "account_id": account_id,
            "name": "Shared Paid Trial Site",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="portal-shared-trial-site-001"),
    )
    assert site_response.status_code == 200, site_response.text

    plus_trial = client.post(
        "/portal/v1/account/plan-trials",
        json={"tier_id": "plus"},
        headers=build_portal_headers(
            principal_id=principal_id,
            site_id=site_id,
            idempotency_key="portal-shared-plus-trial-001",
        ),
    )
    assert plus_trial.status_code == 200, plus_trial.text
    pro_trial = client.post(
        "/portal/v1/account/plan-trials",
        json={"tier_id": "pro"},
        headers=build_portal_headers(
            principal_id=principal_id,
            site_id=site_id,
            idempotency_key="portal-shared-pro-trial-001",
        ),
    )
    assert pro_trial.status_code == 200, pro_trial.text
    assert (
        pro_trial.json()["data"]["trial"]["trial_ends_at"]
        == (plus_trial.json()["data"]["trial"]["trial_ends_at"])
    )
    assert pro_trial.json()["data"]["trial"]["credit_limit"] == 5_000

    agency_denied = client.post(
        "/portal/v1/account/plan-trials",
        json={"tier_id": "agency"},
        headers=build_portal_headers(
            principal_id=principal_id,
            site_id=site_id,
            idempotency_key="portal-shared-agency-denied-001",
        ),
    )
    assert agency_denied.status_code == 422, agency_denied.text

    quote = client.post(
        f"/internal/service/admin/accounts/{account_id}/agency-quotes",
        json={
            "amount_cny": 499,
            "valid_days": 7,
            "trial_enabled": True,
            "trial_credit_limit": 12_000,
        },
        headers=build_internal_headers(idempotency_key="admin-agency-quote-001"),
    )
    assert quote.status_code == 200, quote.text
    offer_id = str(quote.json()["data"]["offer"]["offer_id"])

    agency_trial = client.post(
        f"/internal/service/admin/accounts/{account_id}/agency-trial",
        json={"principal_id": principal_id, "trial_credit_limit": 12_000},
        headers=build_internal_headers(idempotency_key="admin-agency-trial-001"),
    )
    assert agency_trial.status_code == 200, agency_trial.text
    assert agency_trial.json()["data"]["subscription"]["plan_id"] == "agency"
    assert (
        agency_trial.json()["data"]["trial"]["trial_ends_at"]
        == (plus_trial.json()["data"]["trial"]["trial_ends_at"])
    )

    offers = client.get(
        "/portal/v1/account/plan-offers",
        headers=build_portal_headers(principal_id=principal_id, site_id=site_id),
    )
    assert offers.status_code == 200, offers.text
    agency_offer = next(
        item for item in offers.json()["data"]["items"] if item["offer_id"] == offer_id
    )
    assert agency_offer["purchase_mode"] == "quote"
    assert agency_offer["amount"] == 499.0
    dispose_engine(database_url)


def test_open_alipay_notify_marks_pro_monthly_order_paid(
    tmp_path: Path,
) -> None:
    private_key, private_pem, public_pem = _alipay_test_keys()
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_login_code_ttl_seconds": 300,
        },
    )
    public_settings_response = client.patch(
        "/internal/service/admin/service-settings/portal-public",
        json={"public_base_url": "http://testserver"},
        headers=build_internal_headers(idempotency_key="portal-real-alipay-public-001"),
    )
    assert public_settings_response.status_code == 200, public_settings_response.text
    alipay_settings_response = client.patch(
        "/internal/service/admin/service-settings/alipay-payment",
        json={
            "enabled": True,
            "app_id": "2026000000000099",
            "gateway_url": "https://openapi.alipay.com/gateway.do",
            "notify_url": "http://testserver/open/payments/alipay/notify",
            "return_url": "http://testserver/open/payments/alipay/return",
            "private_key": private_pem,
            "public_key": public_pem,
        },
        headers=build_internal_headers(idempotency_key="portal-real-alipay-settings-001"),
    )
    assert alipay_settings_response.status_code == 200, alipay_settings_response.text
    request_data = _request_portal_registration_code(
        client,
        email="alipay-paid-pro-user@example.com",
        headers={"x-npcink-debug-portal-link": "1"},
    )
    registration = _verify_portal_registration_code(
        client,
        email="alipay-paid-pro-user@example.com",
        code=str(request_data["code"]),
    )
    _assert_strict_portal_session(registration)
    registration_access = _ACCESS_BY_EMAIL["alipay-paid-pro-user@example.com"]
    account_id = str(registration_access["account_id"])
    principal_id = str(registration_access["principal_id"])
    site_id = "site_portal_alipay_paid_pro"
    site_response = client.post(
        "/internal/service/sites",
        json={
            "site_id": site_id,
            "account_id": account_id,
            "name": "Alipay Paid Pro Site",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="portal-real-alipay-site-001"),
    )
    assert site_response.status_code == 200, site_response.text
    trial_response = client.post(
        "/portal/v1/account/plan-trials",
        json={"tier_id": "pro"},
        headers=build_portal_headers(
            principal_id=principal_id,
            site_id=site_id,
            idempotency_key="portal-real-alipay-pro-trial-001",
        ),
    )
    assert trial_response.status_code == 200, trial_response.text
    order_response = client.post(
        "/portal/v1/account/subscription-orders",
        json={"offer_id": "pro_monthly_v1", "provider": "alipay"},
        headers=build_portal_headers(
            principal_id=principal_id,
            site_id=site_id,
            idempotency_key="portal-real-alipay-pro-order-001",
        ),
    )
    assert order_response.status_code == 200, order_response.text
    order = order_response.json()["data"]["order"]
    assert order["checkout_url"]
    with get_session(database_url) as session:
        stored_order = session.get(PaymentOrder, str(order["order_id"]))
        assert stored_order is not None
        external_order_no = str(stored_order.external_order_no or "")
    assert external_order_no
    _assert_no_portal_commercial_internal_fields(order_response.json()["data"])

    return_response = client.get(
        "/open/payments/alipay/return",
        params={
            "out_trade_no": external_order_no,
            "trade_status": "TRADE_SUCCESS",
        },
        follow_redirects=False,
    )
    assert return_response.status_code == 303
    assert return_response.headers["location"] == (
        f"/portal/billing?payment_return=alipay&out_trade_no={external_order_no}"
        "&trade_status=TRADE_SUCCESS"
    )
    with get_session(database_url) as session:
        payment_order = session.get(PaymentOrder, str(order["order_id"]))
        assert payment_order is not None
        assert payment_order.status == "pending"

    callback = {
        "app_id": "2026000000000099",
        "out_trade_no": external_order_no,
        "trade_no": "202607040000000099",
        "notify_id": "notify-real-alipay-route-001",
        "total_amount": "29.00",
        "trade_status": "TRADE_SUCCESS",
        "gmt_payment": "2026-07-04 10:20:30",
        "sign_type": "RSA2",
    }
    callback["sign"] = _sign_alipay_payload(private_key, callback)

    notify_response = client.post("/open/payments/alipay/notify", data=callback)

    assert notify_response.status_code == 200, notify_response.text
    assert notify_response.text == "success"
    with get_session(database_url) as session:
        payment_order = session.get(PaymentOrder, str(order["order_id"]))
        assert payment_order is not None
        assert payment_order.status == "paid"
        assert payment_order.provider_trade_no == "202607040000000099"
        scheduled = session.get(AccountSubscription, str(payment_order.subscription_id))
        assert scheduled is not None
        assert scheduled.status == "scheduled"
        assert scheduled.plan_id == "pro"

    dispose_engine(database_url)


def test_portal_session_falls_back_to_free_after_pro_trial_expires(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_login_code_ttl_seconds": 300,
        },
    )
    request_data = _request_portal_registration_code(
        client,
        email="expired-pro-trial-user@example.com",
        headers={"x-npcink-debug-portal-link": "1"},
    )
    registration = _verify_portal_registration_code(
        client,
        email="expired-pro-trial-user@example.com",
        code=str(request_data["code"]),
    )
    _assert_strict_portal_session(registration)
    registration_access = _ACCESS_BY_EMAIL["expired-pro-trial-user@example.com"]
    account_id = str(registration_access["account_id"])
    principal_id = str(registration_access["principal_id"])
    site_id = "site_portal_expired_pro_trial"
    site_response = client.post(
        "/internal/service/sites",
        json={
            "site_id": site_id,
            "account_id": account_id,
            "name": "Expired Pro Trial Site",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="portal-pro-trial-expiry-site-001"),
    )
    assert site_response.status_code == 200, site_response.text

    trial_response = client.post(
        "/portal/v1/account/plan-trials",
        json={"tier_id": "pro"},
        headers=build_portal_headers(
            principal_id=principal_id,
            site_id=site_id,
            idempotency_key="portal-pro-trial-expiry-start-001",
        ),
    )
    assert trial_response.status_code == 200, trial_response.text
    trial_subscription_id = str(trial_response.json()["data"]["subscription"]["subscription_id"])
    with get_session(database_url) as session:
        trial_subscription = session.get(AccountSubscription, trial_subscription_id)
        assert trial_subscription is not None
        trial_subscription.current_period_end_at = datetime.now(UTC) - timedelta(days=1)
        session.commit()

    session_response = client.get(
        "/portal/v1/session",
        headers=build_portal_headers(principal_id=principal_id, site_id=site_id),
    )

    assert session_response.status_code == 200, session_response.text
    session_data = session_response.json()["data"]
    _assert_strict_portal_session(session_data)
    current_subscription = session_data["selected_context"]["current_subscription"]
    assert current_subscription["plan_id"] == "free"
    assert current_subscription["status"] == "active"
    with get_session(database_url) as session:
        subscriptions = list(
            session.scalars(
                select(AccountSubscription).where(AccountSubscription.account_id == account_id)
            )
        )
        assert {item.plan_id: item.status for item in subscriptions} == {
            "free": "active",
            "pro": "canceled",
        }

    dispose_engine(database_url)


def test_portal_registration_code_request_is_rate_limited(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_login_code_ttl_seconds": 300,
        },
        portal_email_sender=FakePortalEmailSender(),
    )

    for _index in range(5):
        response = client.post(
            "/portal/v1/register/code/request",
            json={
                "email": "limited-register@example.com",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["delivery"] == "email"
        assert response.json()["data"]["code"] == ""

    limited_response = client.post(
        "/portal/v1/register/code/request",
        json={
            "email": "limited-register@example.com",
        },
    )
    assert limited_response.status_code == 429
    assert limited_response.json()["error_code"] == "portal.login_code_rate_limited"

    missing_payload_response = client.post(
        "/portal/v1/register/verify",
        json={"email": "limited-register@example.com", "code": ""},
    )
    assert missing_payload_response.status_code == 400
    assert missing_payload_response.json()["error_code"] == "auth.portal_registration_code_required"

    dispose_engine(database_url)


def test_portal_registration_and_login_code_requests_share_email_rate_limit_with_first_login_buffer(
    tmp_path: Path,
) -> None:
    fake_sender = FakePortalEmailSender()
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_login_code_ttl_seconds": 300,
        },
        portal_email_sender=fake_sender,
    )
    email = "first-login-buffer@example.com"

    registration_response = client.post(
        "/portal/v1/register/code/request",
        json={"email": email},
    )
    assert registration_response.status_code == 200, registration_response.text
    assert fake_sender.messages[-1]["kind"] == "registration_code"

    registration_verify_response = client.post(
        "/portal/v1/register/verify",
        json={"email": email, "code": fake_sender.messages[-1]["code"]},
    )
    assert registration_verify_response.status_code == 200, registration_verify_response.text

    for _index in range(4):
        login_response = client.post(
            "/portal/v1/auth/code/request",
            json={"email": email},
        )
        assert login_response.status_code == 200, login_response.text
        assert login_response.json()["data"]["delivery"] == "email"
        assert login_response.json()["data"]["code"] == ""

    limited_response = client.post(
        "/portal/v1/auth/code/request",
        json={"email": email},
    )
    assert limited_response.status_code == 429
    assert limited_response.json()["error_code"] == "portal.login_code_rate_limited"

    assert [message["kind"] for message in fake_sender.messages].count("registration_code") == 1
    assert [message["kind"] for message in fake_sender.messages].count("login_code") == 4

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
    _grant_account_member_access(
        client,
        site_id="site_portal_forwarded",
        email="portal-forwarded@example.com",
        idempotency_key="portal-forwarded-account-members-001",
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
    _grant_account_member_access(
        client,
        site_id="site_portal_localhost",
        email="portal-localhost@example.com",
        idempotency_key="portal-localhost-account-members-001",
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
    _grant_account_member_access(
        client,
        site_id="site_portal_debug",
        email="portal-debug@example.com",
        idempotency_key="portal-debug-account-members-001",
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
    _grant_account_member_access(
        client,
        site_id="site_portal_session",
        email="portal-session@example.com",
        idempotency_key="portal-session-account-members-001",
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
    assert set(session_data) == {
        "email",
        "sites",
        "selected_context",
        "auth_mode",
        "session",
    }
    assert session_data["email"] == "portal-session@example.com"
    assert session_data["selected_context"] is None
    assert session_data["sites"] == [
        {
            "site_id": "site_portal_session",
            "name": "Portal Session Site",
            "site_url": "",
            "platform_kind": "wordpress",
            "status": "active",
        }
    ]

    sites_response = client.get("/portal/v1/sites")
    assert sites_response.status_code == 404

    select_response = client.post(
        "/portal/v1/session/site",
        json={"site_id": "site_portal_session"},
    )
    assert select_response.status_code == 200
    selected_context = select_response.json()["data"]["selected_context"]
    assert selected_context["site"]["site_id"] == "site_portal_session"
    assert "view_billing" in selected_context["allowed_actions"]
    assert selected_context["current_subscription"] is None

    logout_response = client.post("/portal/v1/logout")
    assert logout_response.status_code == 200

    expired_session_response = client.get("/portal/v1/session")
    assert expired_session_response.status_code == 401
    assert expired_session_response.json()["error_code"] == "auth.portal_session_required"

    dispose_engine(database_url)


def test_portal_session_persists_site_id_longer_than_128_characters(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={"portal_jwt_secret": TEST_PORTAL_JWT_SECRET},
    )
    site_id = f"site_{'x' * 155}"
    assert 129 <= len(site_id) <= 191

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_portal_long_site", "name": "Long Site Account"},
        headers=build_internal_headers(idempotency_key="portal-long-site-account-001"),
    )
    site_response = client.post(
        "/internal/service/sites",
        json={
            "site_id": site_id,
            "account_id": "acct_portal_long_site",
            "name": "Long Site ID",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="portal-long-site-create-001"),
    )
    assert site_response.status_code == 200, site_response.text
    grant = _grant_account_member_access(
        client,
        site_id=site_id,
        email="portal-long-site@example.com",
        idempotency_key="portal-long-site-member-001",
    )
    _set_portal_cookie_session(
        client,
        principal_id=str(grant["principal_id"]),
        site_id="",
        session_version=int(grant.get("session_version") or 1),
    )

    select_response = client.post(
        "/portal/v1/session/site",
        json={"site_id": site_id},
    )
    assert select_response.status_code == 200, select_response.text
    assert select_response.json()["data"]["selected_context"]["site"]["site_id"] == site_id

    persisted_response = client.get("/portal/v1/session")
    assert persisted_response.status_code == 200, persisted_response.text
    assert persisted_response.json()["data"]["selected_context"]["site"]["site_id"] == site_id

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
    _grant_account_member_access(
        client,
        site_id="site_portal_origin",
        email="portal-origin@example.com",
        idempotency_key="portal-origin-account-members-001",
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
            "admin_key_sha256": "b" * 64,
            "browser_origin_allowlist": "https://cloud.example.com",
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
    _grant_account_member_access(
        client,
        site_id="site_portal_header_origin",
        email="portal-admin@example.com",
        idempotency_key="portal-header-origin-account-members-001",
    )

    response = client.post(
        "/portal/v1/sites/site_portal_header_origin/remove",
        headers={
            **build_portal_headers(idempotency_key="portal-header-origin-remove-001"),
            "origin": "",
            "referer": "",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["site"]["status"] == "archived"

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
    _grant_account_member_access(
        client,
        site_id="site_portal_session_jwt",
        email="portal-session-jwt@example.com",
        idempotency_key="portal-session-jwt-account-members-001",
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
    assert data["auth_mode"] == "jwt"
    assert len(data["sites"]) == 1
    assert data["selected_context"] is None
    assert data["session"]["transport"] == "header"
    assert data["session"]["revocable"] is False
    assert data["session"]["expires_at"] != ""

    dispose_engine(database_url)


def test_portal_selected_site_context_is_order_independent_and_fail_closed(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    email = "portal-multi-context@example.com"
    grants: dict[str, dict[str, object]] = {}

    # Create beta first to prove repository order never selects the commercial scope.
    for suffix in ("beta", "alpha"):
        account_id = f"acct_portal_context_{suffix}"
        site_id = f"site_portal_context_{suffix}"
        assert client.post(
            "/internal/service/accounts",
            json={"account_id": account_id, "name": f"Context {suffix}"},
            headers=build_internal_headers(idempotency_key=f"context-account-{suffix}"),
        ).status_code == 200
        assert client.post(
            "/internal/service/sites",
            json={
                "site_id": site_id,
                "account_id": account_id,
                "name": f"Context {suffix}",
                "status": "active",
            },
            headers=build_internal_headers(idempotency_key=f"context-site-{suffix}"),
        ).status_code == 200
        grants[suffix] = _grant_account_member_access(
            client,
            site_id=site_id,
            email=email,
            idempotency_key=f"context-member-{suffix}",
        )

    principal_id = str(grants["alpha"]["principal_id"])
    _set_portal_cookie_session(client, principal_id=principal_id, site_id="")
    session_data = client.get("/portal/v1/session").json()["data"]
    assert session_data["selected_context"] is None
    assert {item["site_id"] for item in session_data["sites"]} == {
        "site_portal_context_alpha",
        "site_portal_context_beta",
    }
    assert not {
        "principal_id",
        "account_id",
        "identity_type",
        "role",
        "member_ref",
        "site_admin_ref",
        "accounts",
    }.intersection(session_data)
    assert all(
        "account_id" not in item and "metadata" not in item
        for item in session_data["sites"]
    )

    before_orders = 0
    with get_session(database_url) as session:
        before_orders = len(list(session.scalars(select(PaymentOrder))))
    missing_context = client.post(
        "/portal/v1/account/credit-pack-orders",
        json={"pack_id": "pack_small"},
        headers=_portal_cookie_headers(idempotency_key="context-missing-order"),
    )
    assert missing_context.status_code == 409
    assert missing_context.json()["error_code"] == "portal.site_selection_required"
    with get_session(database_url) as session:
        assert len(list(session.scalars(select(PaymentOrder)))) == before_orders

    with get_session(database_url) as session:
        repository = CommercialRepository(session)
        for suffix, credits in (("alpha", -11), ("beta", -22)):
            repository.record_credit_ledger_entry(
                account_id=f"acct_portal_context_{suffix}",
                site_id=f"site_portal_context_{suffix}",
                subscription_id=None,
                plan_version_id=None,
                run_id=None,
                provider_call_id=None,
                source_type="runs",
                source_id=f"context-{suffix}",
                credit_delta=credits,
                quantity=1,
                unit="run",
                rate=abs(credits),
                rate_unit=None,
                rate_version="context-v1",
                idempotency_key=f"context-ledger-{suffix}",
            )
        session.commit()

    for suffix, expected in (("alpha", 11.0), ("beta", 22.0)):
        _set_portal_cookie_session(
            client,
            principal_id=principal_id,
            site_id=f"site_portal_context_{suffix}",
        )
        ledger_response = client.get("/portal/v1/account/credit-ledger")
        assert ledger_response.status_code == 200, ledger_response.text
        assert ledger_response.json()["data"]["summary"]["consumed_credits"] == expected

    _set_portal_cookie_session(
        client,
        principal_id=principal_id,
        site_id="site_portal_context_alpha",
    )
    cross_account_filter = client.get(
        "/portal/v1/account/credit-trend?site_id=site_portal_context_beta"
    )
    assert cross_account_filter.status_code == 403
    assert cross_account_filter.json()["error_code"] == "service.portal_site_account_mismatch"

    addon_accounts = client.get("/portal/v1/addon-connection-accounts")
    assert addon_accounts.status_code == 200
    assert addon_accounts.json()["data"]["items"] == [
        {
            "account_id": item["account_id"],
            "name": item["name"],
            "site_count": 1,
        }
        for item in addon_accounts.json()["data"]["items"]
    ]
    assert {item["account_id"] for item in addon_accounts.json()["data"]["items"]} == {
        "acct_portal_context_alpha",
        "acct_portal_context_beta",
    }

    with get_session(database_url) as session:
        membership = session.scalar(
            select(AccountUserMembership).where(
                AccountUserMembership.principal_id == principal_id,
                AccountUserMembership.account_id == "acct_portal_context_alpha",
            )
        )
        assert membership is not None
        membership.allowed_actions_json = []
        session.commit()
    denied = client.get("/portal/v1/account/entitlements")
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "service.portal_action_forbidden"

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
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_portal_reads_archived",
            "account_id": "acct_portal_reads",
            "name": "Archived Portal Reads Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="portal-reads-archived-site-001"),
    )
    with get_session(database_url) as session:
        archived_site = session.get(Site, "site_portal_reads_archived")
        assert archived_site is not None
        archived_site.status = "archived"
        session.commit()
    _grant_account_member_access(
        client,
        site_id="site_portal_reads",
        email="portal-reads@example.com",
        idempotency_key="portal-reads-account-members-001",
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
            "metadata": {
                "max_vector_documents": 100,
            },
            "policy": {
                "reconciliation": {
                    "tolerance": {
                        "runs": 0,
                        "provider_calls": 0,
                        "tokens_total": 0,
                        "cost": 0,
                    }
                },
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
        entitlement_snapshot = session.scalar(
            select(AccountEntitlementSnapshot).where(
                AccountEntitlementSnapshot.account_id == "acct_portal_reads",
                AccountEntitlementSnapshot.status == "active",
            )
        )
        assert entitlement_snapshot is not None
        entitlement_snapshot.budgets_json = {
            **(entitlement_snapshot.budgets_json or {}),
            "max_ai_credits_per_period": 300,
            "max_runs_per_period": 10,
            "max_tokens_per_period": 10000,
        }
        entitlement_snapshot.concurrency_json = {
            **(entitlement_snapshot.concurrency_json or {}),
            "max_active_runs": 1,
        }
        assert entitlement_snapshot.budgets_json["max_ai_credits_per_period"] == 300
        assert entitlement_snapshot.concurrency_json["max_active_runs"] == 1
        plan_version = session.scalar(
            select(PlanVersion).where(PlanVersion.plan_version_id == subscription.plan_version_id)
        )
        assert plan_version is not None
        plan_version.budgets_json = {
            **(plan_version.budgets_json or {}),
            "max_ai_credits_per_period": 2000,
            "max_runs_per_period": 0,
            "max_tokens_per_period": 0,
        }
        plan_version.concurrency_json = {
            **(plan_version.concurrency_json or {}),
            "max_active_runs": 5,
        }
        plan_version.metadata_json = {
            **(plan_version.metadata_json or {}),
            "max_batch_items": 5,
            "max_vector_documents": 100,
            "site_limit": 1,
        }
        repository = CommercialRepository(session)
        session.add_all(
            [
                RunRecord(
                    run_id="run-portal-ledger-1",
                    site_id="site_portal_reads",
                    account_id="acct_portal_reads",
                    subscription_id=subscription.subscription_id,
                    plan_version_id=subscription.plan_version_id,
                    ability_name="npcink-abilities-toolkit/build-article-block-plan",
                    ability_family="workflow",
                    skill_id="",
                    workflow_id="",
                    contract_version="hosted_ai_content_support.v1",
                    channel="wordpress",
                    execution_kind="text",
                    execution_tier="cloud",
                    execution_pattern="step_offload",
                    data_classification="public_site_content",
                    profile_id="text.default",
                    canonical_run_id=None,
                    status="succeeded",
                    idempotency_key="portal-ledger-run-content-001",
                    request_fingerprint="portal-ledger-run-content",
                    trace_id="trace-portal-ledger-run-content",
                    cancel_requested_at=None,
                    canceled_at=None,
                    input_json={},
                    policy_json={},
                    result_ref=None,
                    result_json={},
                ),
                RunRecord(
                    run_id="run-portal-ledger-zhihu-hot",
                    site_id="site_portal_reads",
                    account_id="acct_portal_reads",
                    subscription_id=subscription.subscription_id,
                    plan_version_id=subscription.plan_version_id,
                    ability_name="npcink-cloud/web-search",
                    ability_family="web_search",
                    skill_id="",
                    workflow_id="",
                    contract_version="web_search.v1",
                    channel="wordpress",
                    execution_kind="web_search",
                    execution_tier="cloud",
                    execution_pattern="step_offload",
                    data_classification="public_web",
                    profile_id="web-search.default",
                    canonical_run_id=None,
                    status="succeeded",
                    idempotency_key="portal-ledger-run-zhihu-001",
                    request_fingerprint="portal-ledger-run-zhihu",
                    trace_id="trace-portal-ledger-run-zhihu",
                    cancel_requested_at=None,
                    canceled_at=None,
                    input_json={},
                    policy_json={},
                    result_ref=None,
                    result_json={},
                ),
            ]
        )
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
        repository.record_credit_ledger_entry(
            account_id="acct_portal_reads",
            site_id="site_portal_reads",
            subscription_id=subscription.subscription_id,
            plan_version_id=subscription.plan_version_id,
            run_id="run-portal-ledger-component-only",
            provider_call_id=None,
            source_type="runs",
            source_id="run-portal-ledger-component-only:run",
            credit_delta=-1,
            quantity=1,
            unit="run",
            rate=1,
            rate_unit=None,
            rate_version="ai-credit-ledger-v2",
            idempotency_key="portal-credit-ledger-component-only-001",
        )
        repository.record_credit_ledger_entry(
            account_id="acct_portal_reads",
            site_id="site_other_portal_reads",
            subscription_id=subscription.subscription_id,
            plan_version_id=subscription.plan_version_id,
            run_id=None,
            provider_call_id=None,
            source_type="runs",
            source_id="site-other-portal-ledger-run",
            credit_delta=-1,
            quantity=1,
            unit="run",
            rate=1,
            rate_unit=None,
            rate_version="ai-credit-ledger-v2",
            idempotency_key="portal-credit-ledger-other-site-001",
        )
        session.commit()
    key_response = client.post(
        "/internal/service/sites/site_portal_reads/keys",
        json={
            "key_id": "key_portal_reads",
            "secret": "portal-reads-secret",
            "label": "Portal Reads Key",
            "scopes": ["runtime:read"],
        },
        headers=build_internal_headers(idempotency_key="portal-reads-key-001"),
    )
    assert key_response.status_code == 200, key_response.text
    rebuild_response = client.post(
        "/internal/service/sites/site_portal_reads/billing-snapshots/rebuild",
        headers=build_internal_headers(idempotency_key="portal-reads-billing-rebuild-001"),
    )
    assert rebuild_response.status_code == 200

    def portal_reads_headers(*, idempotency_key: str = "") -> dict[str, str]:
        return build_portal_headers(
            principal_id="principal:portal-reads@example.com",
            site_id="site_portal_reads",
            idempotency_key=idempotency_key,
        )

    summary_response = client.get(
        "/portal/v1/sites/site_portal_reads/summary",
        headers=portal_reads_headers(),
    )
    assert summary_response.status_code == 200
    summary_data = summary_response.json()["data"]
    assert summary_data["site"]["site_id"] == "site_portal_reads"
    assert set(summary_data) == {
        "site_id",
        "site",
        "covered_by_subscription_id",
        "subscription_status",
        "package_alias",
        "coverage",
        "entitlement_snapshot",
        "customer_status",
        "generated_at",
    }
    assert set(summary_data["site"]) == {
        "site_id",
        "name",
        "site_url",
        "platform_kind",
        "status",
        "created_at",
    }
    assert set(summary_data["coverage"]) == {
        "subscription_id",
        "status",
        "plan_id",
        "plan_version_id",
        "package_alias",
        "current_period_start",
        "current_period_end",
        "current_period_start_at",
        "current_period_end_at",
    }
    _assert_no_bounded_portal_internal_fields(summary_data)

    usage_response = client.get(
        "/portal/v1/sites/site_portal_reads/usage-summary",
        headers=portal_reads_headers(),
    )
    assert usage_response.status_code == 200
    usage_data = usage_response.json()["data"]
    assert usage_data["site_id"] == "site_portal_reads"
    _assert_no_portal_identity_wrapper(usage_data)

    account_usage_response = client.get(
        "/portal/v1/account/usage-summary",
        headers=portal_reads_headers(),
    )
    assert account_usage_response.status_code == 200
    account_usage_data = account_usage_response.json()["data"]
    _assert_no_portal_identity_wrapper(account_usage_data)
    assert account_usage_data["site_ids"] == ["site_portal_reads"]
    assert account_usage_data["totals"]["sites_total"] == 1

    monitoring_response = client.get(
        "/portal/v1/sites/site_portal_reads/monitoring-overview?window_hours=24",
        headers=portal_reads_headers(),
    )
    assert monitoring_response.status_code == 200
    monitoring_data = monitoring_response.json()["data"]
    assert monitoring_data["contract_version"] == "magick-site-monitoring-overview-v1"
    assert monitoring_data["site_id"] == "site_portal_reads"
    _assert_no_portal_identity_wrapper(monitoring_data)
    assert "health" in monitoring_data
    assert "action_required" in monitoring_data
    assert "quota" in monitoring_data

    entitlements_response = client.get(
        "/portal/v1/sites/site_portal_reads/entitlements",
        headers=portal_reads_headers(),
    )
    assert entitlements_response.status_code == 200
    entitlements_data = entitlements_response.json()["data"]
    assert entitlements_data["site"]["site_id"] == "site_portal_reads"
    assert set(entitlements_data["subscription"]) == STRICT_PORTAL_SUBSCRIPTION_FIELDS
    assert set(entitlements_data["site"]) == {
        "site_id",
        "name",
        "site_url",
        "platform_kind",
        "status",
        "created_at",
    }
    assert set(entitlements_data["plan_version"]) == {
        "plan_version_id",
        "plan_id",
        "version_label",
        "status",
        "currency",
        "entitlements",
        "budgets",
    }
    assert set(entitlements_data["entitlement_snapshot"]) == {
        "subscription_id",
        "plan_version_id",
        "status",
        "entitlements",
        "budgets",
        "site_limit",
        "generated_at",
    }
    _assert_no_bounded_portal_internal_fields(entitlements_data)
    assert entitlements_data["policy"]["subscription"]["grace_period_days"] == 0
    quota_summary = entitlements_data["quota_summary"]
    assert quota_summary["credit"]["key"] == "ai_credits"
    assert quota_summary["credit"]["limit"] == 2000.0
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
    assert (
        next(
            item for item in credit_usage_detail["breakdown"] if item["key"] == "zhihu_hot_topics"
        )["capability_group"]
        == "zhihu_open_platform"
    )
    assert "internal_limits" not in quota_summary
    assert {item["key"] for item in quota_summary["resource_limits"]} == {
        "bound_sites",
        "vector_documents",
    }
    bound_sites = next(
        item for item in quota_summary["resource_limits"] if item["key"] == "bound_sites"
    )
    assert bound_sites["used"] == 1.0
    vector_documents = next(
        item for item in quota_summary["resource_limits"] if item["key"] == "vector_documents"
    )
    assert vector_documents["limit"] == 100.0

    account_entitlements_response = client.get(
        "/portal/v1/account/entitlements",
        headers=portal_reads_headers(),
    )
    assert account_entitlements_response.status_code == 200
    account_entitlements_data = account_entitlements_response.json()["data"]
    _assert_no_portal_identity_wrapper(account_entitlements_data)
    _assert_no_portal_commercial_internal_fields(account_entitlements_data)
    assert account_entitlements_data["quota_summary"]["credit"]["key"] == "ai_credits"
    assert account_entitlements_data["quota_summary"]["credit"]["limit"] == 2000.0
    assert (
        account_entitlements_data["quota_summary"]["credit_ledger_summary"][
            "consumed_credits"
        ]
        == 5.0
    )

    credit_ledger_response = client.get(
        "/portal/v1/sites/site_portal_reads/credit-ledger?limit=10",
        headers=portal_reads_headers(),
    )
    assert credit_ledger_response.status_code == 200
    credit_ledger_data = credit_ledger_response.json()["data"]
    assert credit_ledger_data["site_id"] == "site_portal_reads"
    _assert_no_portal_identity_wrapper(credit_ledger_data)
    assert credit_ledger_data["summary"]["total_credits"] == 4.0
    assert credit_ledger_data["pagination"]["total"] == 3
    assert {item["source_type"] for item in credit_ledger_data["items"]} == {
        "runs",
        "tokens_total",
        "zhihu_hot_topics",
    }
    assert {item["category"] for item in credit_ledger_data["items"]} == {"ai_usage"}
    credit_ledger_items_by_source = {
        item["source_type"]: item for item in credit_ledger_data["items"]
    }
    assert credit_ledger_items_by_source["tokens_total"]["feature_key"] == ("content_generation")
    assert credit_ledger_items_by_source["tokens_total"]["feature_label"] == ("Content writing")
    assert credit_ledger_items_by_source["runs"]["feature_key"] == "content_generation"
    assert credit_ledger_items_by_source["runs"]["feature_label"] == "Content writing"
    assert credit_ledger_items_by_source["zhihu_hot_topics"]["feature_key"] == "topic_research"
    assert credit_ledger_items_by_source["zhihu_hot_topics"]["feature_label"] == ("Topic research")
    assert "ai_assistance" not in {
        str(item.get("feature_key") or "") for item in credit_ledger_data["items"]
    }
    assert credit_ledger_data["summary"]["category_totals"]["ai_usage"]["net_credit_delta"] == -4.0
    assert credit_ledger_data["usage_detail"]["surface"] == "portal_personal_credit_usage"
    assert {item["category"] for item in credit_ledger_data["usage_detail"]["legend"]} >= {
        "ai_usage",
        "credit_pack_purchase",
        "refund_adjustment",
        "operator_adjustment",
    }
    assert {item["key"] for item in credit_ledger_data["usage_detail"]["breakdown"]} >= {
        "runs",
        "tokens_total",
        "zhihu_hot_topics",
    }
    assert len(credit_ledger_data["usage_detail"]["recent_items"]) == 3

    account_credit_ledger_response = client.get(
        "/portal/v1/account/credit-ledger?limit=10",
        headers=portal_reads_headers(),
    )
    assert account_credit_ledger_response.status_code == 200
    account_credit_ledger_data = account_credit_ledger_response.json()["data"]
    _assert_no_portal_commercial_internal_fields(account_credit_ledger_data)
    assert account_credit_ledger_data["summary"]["total_credits"] == 5.0
    assert account_credit_ledger_data["pagination"]["total"] == 4
    assert {item["site_id"] for item in account_credit_ledger_data["items"]} == {
        "site_portal_reads",
        "site_other_portal_reads",
    }

    with get_session(database_url) as session:
        CommercialRepository(session).record_credit_ledger_entry(
            account_id="acct_portal_reads",
            site_id="site_other_portal_reads",
            subscription_id=None,
            plan_version_id=None,
            run_id=None,
            provider_call_id=None,
            source_type="runs",
            source_id="historical-other-site-run",
            credit_delta=-2,
            quantity=1,
            unit="run",
            rate=2,
            rate_unit=None,
            rate_version="ai-credit-ledger-v2",
            idempotency_key="portal-credit-ledger-historical-001",
            created_at=datetime.now(UTC) - timedelta(days=2),
        )
        session.commit()

    expected_trends = {
        "1h": {"points": 12, "credits": 5.0, "entries": 4},
        "24h": {"points": 24, "credits": 5.0, "entries": 4},
        "7d": {"points": 7, "credits": 7.0, "entries": 5},
        "30d": {"points": 30, "credits": 7.0, "entries": 5},
    }
    for trend_window, expectation in expected_trends.items():
        trend_response = client.get(
            f"/portal/v1/account/credit-trend?window={trend_window}",
            headers=portal_reads_headers(),
        )
        assert trend_response.status_code == 200
        trend_data = trend_response.json()["data"]
        _assert_no_portal_commercial_internal_fields(trend_data)
        assert trend_data["contract_version"] == "portal-credit-trend-v1"
        assert trend_data["generated_at"] == trend_data["end_at"]
        assert trend_data["window"] == trend_window
        assert len(trend_data["points"]) == expectation["points"]
        assert trend_data["total_credits"] == expectation["credits"]
        assert trend_data["entry_count"] == expectation["entries"]

    site_trend_response = client.get(
        "/portal/v1/account/credit-trend?window=24h&site_id=site_portal_reads",
        headers=portal_reads_headers(),
    )
    assert site_trend_response.status_code == 200
    site_trend_data = site_trend_response.json()["data"]
    assert site_trend_data["site_id"] == "site_portal_reads"
    assert site_trend_data["total_credits"] == 4.0
    assert site_trend_data["entry_count"] == 3

    invalid_trend_response = client.get(
        "/portal/v1/account/credit-trend?window=90d",
        headers=portal_reads_headers(),
    )
    assert invalid_trend_response.status_code == 422

    with get_session(database_url) as session:
        CommercialRepository(session).record_credit_ledger_entry(
            account_id="acct_portal_reads",
            site_id="site_portal_reads",
            subscription_id=subscription.subscription_id,
            plan_version_id=subscription.plan_version_id,
            run_id="run-portal-ledger-1",
            provider_call_id=None,
            source_type="runs",
            source_id="run-portal-ledger-1:request",
            credit_delta=-3,
            quantity=1,
            unit="run",
            rate=3,
            rate_unit=None,
            rate_version="ai-credit-ledger-v2",
            idempotency_key="portal-credit-ledger-grouped-event-001",
        )
        CommercialRepository(session).record_credit_ledger_entry(
            account_id="acct_portal_reads",
            site_id="site_portal_reads",
            subscription_id=subscription.subscription_id,
            plan_version_id=subscription.plan_version_id,
            run_id="run-portal-ledger-1",
            provider_call_id=None,
            event_type=CREDIT_LEDGER_EVENT_GRANT,
            source_type="credit_pack",
            source_id="grant-not-a-service-event",
            credit_delta=100,
            quantity=100,
            unit="credit",
            rate=1,
            rate_unit=None,
            rate_version="ai-credit-ledger-v2",
            idempotency_key="portal-credit-ledger-grant-excluded-001",
        )
        session.commit()

    credit_events_response = client.get(
        "/portal/v1/account/credit-events?window=period&limit=20",
        headers=portal_reads_headers(),
    )
    assert credit_events_response.status_code == 200
    credit_events_data = credit_events_response.json()["data"]
    _assert_no_portal_commercial_internal_fields(credit_events_data)
    assert credit_events_data["contract_version"] == "portal-credit-events-v1"
    assert credit_events_data["pagination"]["total"] == 4
    assert all(item["direction"] == "consumed" for item in credit_events_data["items"])
    grouped_event = next(
        item
        for item in credit_events_data["items"]
        if item["support_reference"] == "run-portal-ledger-1"
    )
    assert grouped_event["component_count"] == 2
    assert grouped_event["consumed_credits"] == 5.0
    assert {item["key"] for item in grouped_event["components"]} == {
        "model_processing",
        "request",
    }

    topic_events_response = client.get(
        "/portal/v1/account/credit-events?window=period&feature=topic_research",
        headers=portal_reads_headers(),
    )
    assert topic_events_response.status_code == 200
    topic_events_data = topic_events_response.json()["data"]
    assert topic_events_data["pagination"]["total"] == 1
    assert topic_events_data["items"][0]["feature_key"] == "topic_research"

    bucket_response = client.get(
        "/portal/v1/account/credit-event-buckets",
        params={"bucket": "30m", "window": "period"},
        headers=portal_reads_headers(),
    )
    assert bucket_response.status_code == 200
    bucket_data = bucket_response.json()["data"]
    _assert_no_portal_commercial_internal_fields(bucket_data)
    assert bucket_data["contract_version"] == "portal-credit-event-buckets-v1"
    assert bucket_data["bucket"] == "30m"
    assert bucket_data["bucket_seconds"] == 1800
    assert bucket_data["pagination"]["total"] >= 1
    assert all(item["start_at"] < item["end_at"] for item in bucket_data["items"])
    latest_bucket = bucket_data["items"][0]
    assert latest_bucket["event_count"] >= 1
    assert latest_bucket["consumed_credits"] >= 1
    assert latest_bucket["top_feature_key"]

    bucket_detail_response = client.get(
        "/portal/v1/account/credit-events",
        params={
            "window": "period",
            "start_at": latest_bucket["start_at"],
            "end_at": latest_bucket["end_at"],
        },
        headers=portal_reads_headers(),
    )
    assert bucket_detail_response.status_code == 200
    assert bucket_detail_response.json()["data"]["pagination"]["total"] >= 1

    recent_bucket_response = client.get(
        "/portal/v1/account/credit-event-buckets",
        params={"bucket": "30m", "window": "7d"},
        headers=portal_reads_headers(),
    )
    assert recent_bucket_response.status_code == 200
    recent_bucket_data = recent_bucket_response.json()["data"]
    assert recent_bucket_data["summary"]["consumed_credits"] == (
        bucket_data["summary"]["consumed_credits"] + 2.0
    )
    assert all(item["start_at"] < item["end_at"] for item in recent_bucket_data["items"])

    # Keep the remainder of this long scenario focused on the payment grant it creates below.
    with get_session(database_url) as session:
        excluded_grant = session.scalar(
            select(CreditLedgerEntry).where(
                CreditLedgerEntry.idempotency_key
                == "portal-credit-ledger-grant-excluded-001"
            )
        )
        assert excluded_grant is not None
        session.delete(excluded_grant)
        session.commit()

    credit_packs_response = client.get(
        "/portal/v1/sites/site_portal_reads/credit-packs",
        headers=portal_reads_headers(),
    )
    assert credit_packs_response.status_code == 200
    credit_packs_data = credit_packs_response.json()["data"]
    _assert_no_portal_commercial_internal_fields(credit_packs_data)
    assert credit_packs_data["catalog_version"] == "ai-credit-packs-v1"
    assert {item["pack_id"] for item in credit_packs_data["items"]} >= {
        "pack_small",
        "pack_medium",
        "pack_large",
    }
    assert all(int(item["validity_days"]) > 0 for item in credit_packs_data["items"])

    account_credit_packs_response = client.get(
        "/portal/v1/account/credit-packs",
        headers=portal_reads_headers(),
    )
    assert account_credit_packs_response.status_code == 200
    account_credit_packs_data = account_credit_packs_response.json()["data"]
    _assert_no_portal_identity_wrapper(account_credit_packs_data)
    assert {item["pack_id"] for item in account_credit_packs_data["items"]} >= {
        "pack_small",
        "pack_medium",
        "pack_large",
    }
    assert all(int(item["validity_days"]) > 0 for item in account_credit_packs_data["items"])

    credit_pack_order_response = client.post(
        "/portal/v1/sites/site_portal_reads/credit-pack-orders",
        json={"pack_id": "pack_small"},
        headers=portal_reads_headers(
            idempotency_key="portal-credit-pack-order-001",
        ),
    )
    assert credit_pack_order_response.status_code == 200, credit_pack_order_response.text
    credit_pack_order = credit_pack_order_response.json()["data"]["order"]
    _assert_no_portal_commercial_internal_fields(
        credit_pack_order_response.json()["data"]
    )
    assert credit_pack_order["purchase_kind"] == "credit_pack"
    assert credit_pack_order["credit_pack"]["ai_credits"] == 10000
    assert credit_pack_order["target_subscription_id"] == "sub_portal_reads"
    assert credit_pack_order["status_detail"]["code"] == "awaiting_payment_confirmation"

    payment_orders_response = client.get(
        "/portal/v1/sites/site_portal_reads/payment-orders?limit=10",
        headers=portal_reads_headers(),
    )
    assert payment_orders_response.status_code == 200
    payment_orders = payment_orders_response.json()["data"]
    _assert_no_portal_commercial_internal_fields(payment_orders)
    assert payment_orders["pagination"]["total"] == 1
    assert payment_orders["items"][0]["order_id"] == credit_pack_order["order_id"]
    assert payment_orders["items"][0]["status"] == "pending"
    assert payment_orders["items"][0]["status_detail"]["next_action"] == (
        "provider_payment_or_callback"
    )
    assert payment_orders["items"][0]["available_actions"] == ["cancel"]

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
        headers=portal_reads_headers(),
    )
    assert paid_payment_orders_response.status_code == 200
    paid_payment_order = paid_payment_orders_response.json()["data"]["items"][0]
    assert paid_payment_order["status"] == "paid"
    assert paid_payment_order["status_detail"]["code"] == "paid_and_granted"

    refreshed_credit_ledger_response = client.get(
        "/portal/v1/sites/site_portal_reads/credit-ledger?limit=10",
        headers=portal_reads_headers(),
    )
    assert refreshed_credit_ledger_response.status_code == 200
    refreshed_ledger = refreshed_credit_ledger_response.json()["data"]
    assert refreshed_ledger["summary"]["granted_credits"] == 10000.0
    assert refreshed_ledger["summary"]["net_used_credits"] == 0.0
    assert (
        refreshed_ledger["summary"]["category_totals"]["credit_pack_purchase"]["net_credit_delta"]
        == 10000.0
    )
    assert "credit_pack_purchase" in {item["source_type"] for item in refreshed_ledger["items"]}
    credit_pack_ledger_item = next(
        item for item in refreshed_ledger["items"] if item["source_type"] == "credit_pack_purchase"
    )
    assert "feature_key" not in credit_pack_ledger_item
    with get_session(database_url) as session:
        credit_pack_entries = list(
            session.scalars(
                select(CreditLedgerEntry).where(
                    CreditLedgerEntry.source_type == "credit_pack_purchase"
                )
            )
        )
        assert len(credit_pack_entries) == 1

    account_credit_pack_order_response = client.post(
        "/portal/v1/account/credit-pack-orders",
        json={"pack_id": "pack_medium"},
        headers=portal_reads_headers(
            idempotency_key="portal-account-credit-pack-order-001",
        ),
    )
    assert account_credit_pack_order_response.status_code == 200
    account_credit_pack_order_data = account_credit_pack_order_response.json()["data"]
    _assert_no_portal_identity_wrapper(account_credit_pack_order_data)
    _assert_no_portal_commercial_internal_fields(account_credit_pack_order_data)
    assert account_credit_pack_order_data["order"]["purchase_kind"] == "credit_pack"
    assert account_credit_pack_order_data["order"]["credit_pack"]["pack_id"] == "pack_medium"
    assert account_credit_pack_order_data["order"]["available_actions"] == ["cancel"]

    cancel_account_credit_pack_order_response = client.post(
        (
            "/portal/v1/account/payment-orders/"
            f"{account_credit_pack_order_data['order']['order_id']}/cancellation"
        ),
        json={},
        headers=portal_reads_headers(
            idempotency_key="portal-account-credit-pack-order-cancel-001",
        ),
    )
    assert cancel_account_credit_pack_order_response.status_code == 200
    canceled_account_credit_pack_order = cancel_account_credit_pack_order_response.json()["data"][
        "order"
    ]
    assert canceled_account_credit_pack_order["status"] == "canceled"
    assert canceled_account_credit_pack_order["available_actions"] == []
    assert canceled_account_credit_pack_order["checkout_url"] == ""
    _assert_no_portal_commercial_internal_fields(
        cancel_account_credit_pack_order_response.json()["data"]
    )

    audit_response = client.get(
        "/portal/v1/sites/site_portal_reads/audit-summary",
        headers=portal_reads_headers(),
    )
    assert audit_response.status_code == 200
    audit_data = audit_response.json()["data"]
    assert audit_data["site_id"] == "site_portal_reads"
    assert audit_data["generated_at"]
    assert audit_data["totals"]["events"] >= 1
    _assert_no_bounded_portal_internal_fields(audit_data)

    account_audit_response = client.get(
        "/portal/v1/account/audit-summary",
        headers=portal_reads_headers(),
    )
    assert account_audit_response.status_code == 200
    account_audit_data = account_audit_response.json()["data"]
    assert set(account_audit_data) == {"generated_at", "totals", "groups"}
    assert account_audit_data["generated_at"]
    assert account_audit_data["totals"]["events"] >= 1
    _assert_no_bounded_portal_internal_fields(account_audit_data)

    audit_events_response = client.get(
        "/portal/v1/sites/site_portal_reads/audit-events?event_kind=site_key.issue&limit=10",
        headers=portal_reads_headers(),
    )
    assert audit_events_response.status_code == 200
    audit_events_data = audit_events_response.json()["data"]
    assert audit_events_data["site_id"] == "site_portal_reads"
    assert audit_events_data["filters"]["event_kind"] == "site_key.issue"
    assert len(audit_events_data["items"]) >= 1
    assert set(audit_events_data["items"][0]) == {
        "event_id",
        "event_kind",
        "outcome",
        "trace_id",
        "created_at",
    }
    _assert_no_bounded_portal_internal_fields(audit_events_data)

    account_audit_events_response = client.get(
        "/portal/v1/account/audit-events?event_kind=site_key.issue&limit=10",
        headers=portal_reads_headers(),
    )
    assert account_audit_events_response.status_code == 200
    account_audit_events_data = account_audit_events_response.json()["data"]
    assert account_audit_events_data["filters"]["event_kind"] == "site_key.issue"
    assert len(account_audit_events_data["items"]) >= 1
    _assert_no_bounded_portal_internal_fields(account_audit_events_data)

    billing_response = client.get(
        "/portal/v1/sites/site_portal_reads/billing-snapshots",
        headers=portal_reads_headers(),
    )
    assert billing_response.status_code == 200
    billing_data = billing_response.json()["data"]
    assert billing_data["site_id"] == "site_portal_reads"
    assert len(billing_data["items"]) >= 1
    _assert_no_portal_commercial_internal_fields(billing_data)

    reconciliation_response = client.get(
        "/portal/v1/sites/site_portal_reads/billing-snapshots/reconciliation",
        headers=portal_reads_headers(),
    )
    assert reconciliation_response.status_code == 200
    reconciliation_data = reconciliation_response.json()["data"]
    assert reconciliation_data["site_id"] == "site_portal_reads"
    assert reconciliation_data["snapshot"] is not None
    _assert_no_portal_commercial_internal_fields(reconciliation_data)

    denied_response = client.get(
        "/portal/v1/sites/site_portal_reads/summary",
        headers=build_portal_headers(principal_id="principal:outsider@example.com"),
    )
    assert denied_response.status_code == 401
    assert denied_response.json()["error_code"] == "auth.portal_session_revoked"
    assert denied_response.json()["meta"]["trace_id"] == "00112233445566778899aabbccddeeff"

    dispose_engine(database_url)
