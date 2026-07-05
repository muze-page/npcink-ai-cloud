from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.callbacks.http import HttpRuntimeCallbackDispatcher
from app.adapters.providers.base import (
    CatalogInstanceSeed,
    CatalogModelSeed,
    ProviderAdapter,
    ProviderCatalogSnapshot,
    ProviderExecutionError,
    ProviderExecutionRequest,
    ProviderExecutionResult,
)
from app.adapters.providers.minimax import MiniMaxProviderAdapter
from app.adapters.repositories.catalog_repository import CatalogRepository
from app.adapters.repositories.commercial_repository import CommercialRepository
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    ACCOUNT_USER_MEMBERSHIP_STATUS_REVOKED,
    PRINCIPAL_STATUS_DISABLED,
    SITE_STATUS_ARCHIVED,
    SITE_USER_GRANT_STATUS_REVOKED,
    SUBSCRIPTION_STATUS_PAST_DUE,
    AccountEntitlementSnapshot,
    AccountSubscription,
    AccountUserMembership,
    BillingSnapshot,
    ModelReferenceModel,
    ModelReferenceSource,
    PluginObservabilityEvent,
    Principal,
    ProviderCallRecord,
    ProviderConnection,
    ReplayReceipt,
    RunRecord,
    RuntimeGuardEvent,
    ServiceAuditEvent,
    ServiceSetting,
    SiteUserGrant,
    UsageMeterEvent,
)
from app.core.secrets import (
    decrypt_provider_connection_secret,
    decrypt_service_setting_secret,
    encrypt_provider_connection_secret,
)
from app.core.security import REPLAY_SCOPE_PUBLIC_POST_SITE
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from app.domain.commercial.service import CommercialService, ServiceAuditContext
from app.domain.hosted_model_defaults import (
    AUDIO_NARRATION_MODEL_ID,
    AUDIO_NARRATION_PROFILE_ID,
    TEXT_AI_PROFILE_ID,
)
from app.domain.provider_connections.service import ProviderConnectionAdminService
from app.domain.runtime.service import RuntimeService
from app.domain.web_search.service import (
    TavilyWebSearchProvider,
    WebSearchExecutionResult,
    WebSearchProviderUsage,
)
from app.domain.wordpress_ai_connector.routing_profiles import (
    WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID,
    WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
)
from app.workers.ops_cadence import run_due_tasks
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
    build_auth_headers,
    build_internal_headers,
    merge_json_headers,
    seed_provider_model_allowlist,
    seed_site_auth,
)


def _alipay_test_keys() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'service-routes.sqlite3'}"


def _build_client(
    tmp_path: Path,
    *,
    settings_overrides: dict[str, object] | None = None,
    providers: dict[str, ProviderAdapter] | None = None,
) -> tuple[str, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url, providers=providers).refresh_catalog()

    settings_kwargs = {
        "_env_file": None,
        "project_name": "Npcink AI Cloud Test",
        "environment": "test",
        "database_url": database_url,
        "redis_url": "redis://localhost:6379/0",
        "internal_auth_token": TEST_INTERNAL_AUTH_TOKEN,
        "admin_session_secret": TEST_ADMIN_SESSION_SECRET,
        "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
        "openai_api_key": "",
        "anthropic_api_key": "",
        "litellm_provider_enabled": False,
        "litellm_api_key": "",
        "vllm_provider_enabled": False,
        "vllm_api_key": "",
        "tei_provider_enabled": False,
        "tei_api_key": "",
        "openrouter_provider_enabled": False,
        "openrouter_api_key": "",
        "siliconflow_provider_enabled": False,
        "siliconflow_api_key": "",
        "minimax_provider_enabled": False,
        "minimax_api_key": "",
        "minimax_group_id": "",
        "web_search_provider": "disabled",
        "web_search_tavily_api_key": "",
        "web_search_bocha_api_key": "",
        "web_search_jina_reader_api_key": "",
        "web_search_apify_api_token": "",
        "image_source_provider": "disabled",
        "image_source_auto_strategy": "first_available",
        "image_source_unsplash_access_key": "",
        "image_source_pixabay_api_key": "",
        "image_source_pexels_api_key": "",
        "site_knowledge_embedding_provider": "deterministic",
    }
    settings_kwargs.update(settings_overrides or {})
    settings = Settings(**settings_kwargs)
    services = CloudServices(settings=settings, providers=providers or {})
    return database_url, TestClient(create_app(services))


def _runtime_service_settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        openai_api_key="",
        anthropic_api_key="",
        litellm_provider_enabled=False,
        litellm_api_key="",
        vllm_provider_enabled=False,
        vllm_api_key="",
        tei_provider_enabled=False,
        tei_api_key="",
        openrouter_provider_enabled=False,
        openrouter_api_key="",
        siliconflow_provider_enabled=False,
        siliconflow_api_key="",
        site_knowledge_embedding_provider="deterministic",
    )


def _request_portal_registration_code(
    client: TestClient,
    *,
    email: str,
    site_url: str,
    site_name: str = "",
) -> dict[str, object]:
    response = client.post(
        "/portal/v1/register/code/request",
        json={
            "email": email,
            "site_url": site_url,
            "site_name": site_name,
            "use_case": "content generation",
        },
        headers={
            "origin": "http://testserver",
            "referer": "http://testserver/",
            "x-npcink-debug-portal-link": "1",
            "x-npcink-dev-login-code": "1",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _verify_portal_registration_code(
    client: TestClient,
    *,
    email: str,
    code: str,
) -> dict[str, object]:
    response = client.post(
        "/portal/v1/register/verify",
        json={"email": email, "code": code},
        headers={
            "origin": "http://testserver",
            "referer": "http://testserver/",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


class FixedAudioSummaryScriptProvider:
    provider_id = "openai"
    display_name = "Fixed Text Provider"
    adapter_type = "openai"

    def __init__(self) -> None:
        self.requests: list[ProviderExecutionRequest] = []

    def fetch_catalog(self) -> ProviderCatalogSnapshot:
        return ProviderCatalogSnapshot(
            provider_id=self.provider_id,
            display_name=self.display_name,
            adapter_type=self.adapter_type,
            models=[
                CatalogModelSeed(
                    model_id="gpt-hosted-free-next",
                    family="gpt-hosted-free",
                    feature="text",
                    status="available",
                    context_window=256000,
                    price_input=0.0,
                    price_output=0.0,
                    raw_json={"tier": "quality", "surface": "hosted_free_tools"},
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="openai-global-hosted-free-next",
                            endpoint_variant="responses",
                            region="global",
                            capability_tags=["text", "quality", "hosted-free"],
                            is_default=True,
                            weight=140,
                        )
                    ],
                )
            ],
        )

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        self.requests.append(request)
        output_text = json.dumps(
            {
                "opening": "这是一段适合收听的长文摘要。",
                "key_points": [
                    "第一，文章先交代背景。",
                    "第二，文章说明关键问题。",
                    "第三，文章给出解决方案。",
                ],
                "closing": "如果你需要完整细节，再回到原文继续阅读。",
                "assumptions_to_verify": [],
            },
            ensure_ascii=False,
        )
        return ProviderExecutionResult(
            output={
                "output_text": output_text,
                "messages": [{"role": "assistant", "content": output_text}],
                "model_id": request.model_id,
            },
            latency_ms=25,
            tokens_in=80,
            tokens_out=60,
            cost=0.0,
        )


def _bind_audio_summary_script_profile(database_url: str, *, revision: str) -> None:
    with get_session(database_url) as session:
        CatalogRepository(session).upsert_routing_binding(
            profile_id=WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
            candidate_instance_ids=["openai-global-hosted-free-next"],
            selection_policy_json={
                "strategy": "ordered",
                "test_override": revision,
            },
            revision=revision,
        )
        session.commit()


def _seed_minimax_audio_model_allowlist(database_url: str) -> None:
    seed_provider_model_allowlist(
        database_url,
        provider_id="minimax",
        kind="minimax",
        model_ids=[AUDIO_NARRATION_MODEL_ID],
        capability_ids=["audio_generation"],
        runtime_profile_ids=[
            AUDIO_NARRATION_PROFILE_ID,
            WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID,
        ],
        base_url="https://api.minimaxi.com",
    )


def _seed_openai_text_model_allowlist(
    database_url: str,
    *,
    model_ids: list[str] | None = None,
) -> None:
    seed_provider_model_allowlist(
        database_url,
        provider_id="openai",
        kind="openai_compatible",
        model_ids=model_ids or ["gpt-4.1-mini", "gpt-hosted-free-next", "gpt-5.5"],
        capability_ids=["text_generation"],
        runtime_profile_ids=[TEXT_AI_PROFILE_ID, WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID],
        base_url="https://api.openai.test/v1",
    )


class FlakyAudioSummaryScriptProvider(FixedAudioSummaryScriptProvider):
    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        self.requests.append(request)
        if len(self.requests) == 1:
            raise ProviderExecutionError(
                "provider.upstream_error",
                "upstream error: temporary text provider failure",
                retryable=True,
            )
        output_text = json.dumps(
            {
                "opening": "重试后生成的长文音频摘要。",
                "key_points": ["模型第二次调用成功。"],
                "closing": "可以继续生成音频候选。",
                "assumptions_to_verify": [],
            },
            ensure_ascii=False,
        )
        return ProviderExecutionResult(
            output={
                "output_text": output_text,
                "messages": [{"role": "assistant", "content": output_text}],
                "model_id": request.model_id,
            },
            latency_ms=30,
            tokens_in=80,
            tokens_out=30,
            cost=0.0,
        )


class EmptyAudioSummaryScriptProvider(FixedAudioSummaryScriptProvider):
    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        self.requests.append(request)
        return ProviderExecutionResult(
            output={
                "output_text": "",
                "messages": [{"role": "assistant", "content": ""}],
                "model_id": request.model_id,
            },
            latency_ms=20,
            tokens_in=80,
            tokens_out=0,
            cost=0.0,
        )


def test_admin_portal_users_lists_self_registered_users_and_disables_access(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_login_code_ttl_seconds": 300,
            "debug_local_origin_allowlist": "http://testserver",
        },
    )

    email = "admin-portal-user@example.com"
    request_data = _request_portal_registration_code(
        client,
        email=email,
        site_url="https://admin-portal-user.example.com",
        site_name="Admin Portal User",
    )
    registration_data = _verify_portal_registration_code(
        client,
        email=email,
        code=str(request_data["code"]),
    )
    principal_id = str(registration_data["principal_id"])

    list_response = client.get(
        "/internal/service/admin/portal-users?q=admin-portal-user",
        headers=build_internal_headers(),
    )
    assert list_response.status_code == 200, list_response.text
    list_data = list_response.json()["data"]
    items = list_data["items"]
    assert list_data["total"] == 1
    assert items[0]["principal_id"] == principal_id
    assert items[0]["email"] == email
    assert items[0]["source"] == "portal_self_registration"
    assert items[0]["package_alias"] == "Free"
    assert items[0]["plan_id"] == "free"
    assert items[0]["qq_bound"] is False
    assert items[0]["site_id"] == "site_admin-portal-user-example-com"

    disable_response = client.post(
        f"/internal/service/admin/portal-users/{principal_id}/disable",
        json={"reason": "operator test disable"},
        headers=build_internal_headers(idempotency_key="admin-portal-user-disable-001"),
    )
    assert disable_response.status_code == 200, disable_response.text
    disable_data = disable_response.json()["data"]
    assert disable_data["status"] == PRINCIPAL_STATUS_DISABLED
    assert disable_data["revoked_site_grants"] == 1
    assert disable_data["revoked_account_memberships"] == 1

    revoked_session_response = client.get("/portal/v1/session")
    assert revoked_session_response.status_code == 401
    assert revoked_session_response.json()["error_code"] == "auth.portal_session_revoked"

    revoked_site_response = client.get(
        f"/portal/v1/sites/{registration_data['site_id']}/summary"
    )
    assert revoked_site_response.status_code == 401
    assert revoked_site_response.json()["error_code"] == "auth.portal_session_revoked"

    audit_response = client.get(
        f"/internal/service/admin/portal-users/{principal_id}/audit",
        headers=build_internal_headers(),
    )
    assert audit_response.status_code == 200, audit_response.text
    audit_data = audit_response.json()["data"]
    assert audit_data["principal"]["principal_id"] == principal_id
    assert audit_data["principal"]["email"] == email
    assert audit_data["summary"]["registration_events"] == 1
    assert audit_data["summary"]["disable_events"] == 1
    assert audit_data["summary"]["latest_disable_reason"] == "operator test disable"
    assert audit_data["summary"]["latest_disable_revoked_site_grants"] == 1
    assert audit_data["summary"]["latest_disable_revoked_account_memberships"] == 1
    event_kinds = {item["event_kind"] for item in audit_data["items"]}
    assert "portal.registration" in event_kinds
    assert "portal_user.disable" in event_kinds

    disabled_list_response = client.get(
        "/internal/service/admin/portal-users?status=disabled&q=admin-portal-user",
        headers=build_internal_headers(),
    )
    assert disabled_list_response.status_code == 200, disabled_list_response.text
    disabled_item = disabled_list_response.json()["data"]["items"][0]
    assert disabled_item["status"] == PRINCIPAL_STATUS_DISABLED
    assert disabled_item["membership_status"] == ACCOUNT_USER_MEMBERSHIP_STATUS_REVOKED
    assert disabled_item["grant_status"] == SITE_USER_GRANT_STATUS_REVOKED

    with get_session(database_url) as session:
        identity = session.scalar(
            select(Principal).where(Principal.principal_id == principal_id)
        )
        assert identity is not None
        assert identity.status == PRINCIPAL_STATUS_DISABLED
        assert int(identity.session_version or 0) > 1
        membership = session.scalar(
            select(AccountUserMembership).where(
                AccountUserMembership.principal_id == principal_id
            )
        )
        assert membership is not None
        assert membership.status == ACCOUNT_USER_MEMBERSHIP_STATUS_REVOKED
        grant = session.scalar(
            select(SiteUserGrant).where(SiteUserGrant.principal_id == principal_id)
        )
        assert grant is not None
        assert grant.status == SITE_USER_GRANT_STATUS_REVOKED

    dispose_engine(database_url)


def test_admin_portal_users_batch_disable_processes_each_principal(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
            "portal_login_code_ttl_seconds": 300,
            "debug_local_origin_allowlist": "http://testserver",
        },
    )

    principal_ids: list[str] = []
    for email, site_url in (
        ("batch-one@example.com", "https://batch-one.example.com"),
        ("batch-two@example.com", "https://batch-two.example.com"),
    ):
        request_data = _request_portal_registration_code(
            client,
            email=email,
            site_url=site_url,
            site_name=email.split("@")[0],
        )
        registration_data = _verify_portal_registration_code(
            client,
            email=email,
            code=str(request_data["code"]),
        )
        principal_ids.append(str(registration_data["principal_id"]))

    missing_principal_id = "prn_missing_batch_disable"
    blank_reason_response = client.post(
        "/internal/service/admin/portal-users/batch-disable",
        json={"principal_ids": [principal_ids[0]], "reason": ""},
        headers=build_internal_headers(idempotency_key="admin-portal-batch-disable-blank"),
    )
    assert blank_reason_response.status_code == 400
    assert (
        blank_reason_response.json()["error_code"]
        == "service.portal_user_batch_disable_reason_required"
    )

    batch_response = client.post(
        "/internal/service/admin/portal-users/batch-disable",
        json={
            "principal_ids": [*principal_ids, missing_principal_id],
            "reason": "abuse risk review",
        },
        headers=build_internal_headers(idempotency_key="admin-portal-batch-disable-001"),
    )
    assert batch_response.status_code == 200, batch_response.text
    batch_data = batch_response.json()["data"]
    assert batch_data["totals"]["attempted"] == 3
    assert batch_data["totals"]["disabled"] == 2
    assert batch_data["totals"]["failed"] == 1
    failed_items = [item for item in batch_data["items"] if item["outcome"] == "failed"]
    assert failed_items[0]["principal_id"] == missing_principal_id
    assert failed_items[0]["error_code"] == "service.principal_not_found"

    with get_session(database_url) as session:
        identities = list(
            session.scalars(
                select(Principal).where(Principal.principal_id.in_(principal_ids))
            )
        )
        assert {identity.status for identity in identities} == {PRINCIPAL_STATUS_DISABLED}
        memberships = list(
            session.scalars(
                select(AccountUserMembership).where(
                    AccountUserMembership.principal_id.in_(principal_ids)
                )
            )
        )
        assert {membership.status for membership in memberships} == {
            ACCOUNT_USER_MEMBERSHIP_STATUS_REVOKED
        }
        grants = list(
            session.scalars(
                select(SiteUserGrant).where(SiteUserGrant.principal_id.in_(principal_ids))
            )
        )
        assert {grant.status for grant in grants} == {SITE_USER_GRANT_STATUS_REVOKED}

    audit_response = client.get(
        f"/internal/service/admin/portal-users/{principal_ids[0]}/audit",
        headers=build_internal_headers(),
    )
    assert audit_response.status_code == 200, audit_response.text
    audit_data = audit_response.json()["data"]
    assert audit_data["summary"]["disable_events"] == 1
    assert audit_data["summary"]["latest_disable_reason"] == "abuse risk review"

    dispose_engine(database_url)


def test_admin_web_search_provider_env_settings_route_is_retired(
    tmp_path: Path,
) -> None:
    _, client = _build_client(tmp_path)

    get_response = client.get(
        "/internal/service/admin/web-search-providers",
        headers=build_internal_headers(),
    )
    post_response = client.post(
        "/internal/service/admin/web-search-providers",
        headers=build_internal_headers(idempotency_key="web-search-provider-save"),
        json={
            "provider_mode": "auto",
            "providers": {},
        },
    )

    assert get_response.status_code == 404
    assert post_response.status_code == 404


def test_admin_agent_workflow_metadata_projection_is_read_only(tmp_path: Path) -> None:
    _, client = _build_client(tmp_path)

    response = client.get(
        "/internal/service/admin/agent-workflow-metadata",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["projection_version"] == "cloud-agent-workflow-metadata.v1"
    assert data["projection_kind"] == "read_only_runtime_metadata"
    assert data["registry_version"] == "cloud-agent-workflow-metadata.v1"
    agents = {item["agent_id"]: item for item in data["agents"]}
    assert "internal_ops_advisor_agent" in agents
    assert agents["site_knowledge_suggestion_agent"]["handoff_owner"] == ("wordpress_local")
    assert agents["site_knowledge_suggestion_agent"]["direct_wordpress_write"] is False
    workflows = {item["workflow_id"]: item for item in data["workflows"]}
    assert workflows["external_web_evidence_preflight"]["handoff_owner"] == ("wordpress_local")
    assert workflows["media_derivative_artifact_generation"]["direct_wordpress_write"] is False

    unauthorized = client.get("/internal/service/admin/agent-workflow-metadata")
    assert unauthorized.status_code in (401, 403)


def test_admin_service_settings_store_masked_cloud_runtime_config(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    alipay_private_key, alipay_public_key = _alipay_test_keys()

    initial_response = client.get(
        "/internal/service/admin/service-settings",
        headers=build_internal_headers(),
    )
    assert initial_response.status_code == 200
    assert initial_response.json()["data"]["env_fallback"] == "disabled"
    assert (
        initial_response.json()["data"]["settings"]["portal_email"]["status"]
        == "missing_config"
    )
    assert (
        initial_response.json()["data"]["settings"]["alipay_payment"]["status"]
        == "missing_config"
    )

    public_response = client.patch(
        "/internal/service/admin/service-settings/portal-public",
        json={"public_base_url": "https://cloud.example.com"},
        headers=build_internal_headers(idempotency_key="service-settings-public-001"),
    )
    assert public_response.status_code == 200, public_response.text
    assert public_response.json()["data"]["config"]["public_base_url"] == (
        "https://cloud.example.com"
    )

    qq_response = client.patch(
        "/internal/service/admin/service-settings/qq-login",
        json={
            "client_id": "qq-client-id",
            "client_secret": "qq-client-secret",
            "redirect_uri": "https://cloud.example.com/open/auth/qq/callback",
            "scope": "get_user_info",
            "timeout_seconds": 10,
        },
        headers=build_internal_headers(idempotency_key="service-settings-qq-001"),
    )
    assert qq_response.status_code == 200, qq_response.text
    assert qq_response.json()["data"]["status"] == "ready"
    assert qq_response.json()["data"]["secrets"]["client_secret"]["configured"] is True
    assert "qq-client-secret" not in json.dumps(qq_response.json())

    email_response = client.patch(
        "/internal/service/admin/service-settings/email",
        json={
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "smtp_username": "smtp-user",
            "smtp_password": "smtp-password",
            "smtp_use_ssl": True,
            "smtp_use_starttls": False,
            "smtp_timeout_seconds": 20,
            "from_email": "noreply@example.com",
            "from_name": "Npcink AI Cloud",
            "reply_to": "support@example.com",
        },
        headers=build_internal_headers(idempotency_key="service-settings-email-001"),
    )
    assert email_response.status_code == 200, email_response.text
    assert email_response.json()["data"]["secrets"]["smtp_password"]["display"] == (
        "configured"
    )
    assert "smtp-password" not in json.dumps(email_response.json())

    alipay_response = client.patch(
        "/internal/service/admin/service-settings/alipay-payment",
        json={
            "enabled": True,
            "app_id": "2026000000000099",
            "gateway_url": "https://openapi.alipay.com/gateway.do",
            "notify_url": "https://cloud.example.com/open/payments/alipay/notify",
            "return_url": "https://cloud.example.com/open/payments/alipay/return",
            "private_key": alipay_private_key,
            "public_key": alipay_public_key,
        },
        headers=build_internal_headers(idempotency_key="service-settings-alipay-001"),
    )
    assert alipay_response.status_code == 200, alipay_response.text
    assert alipay_response.json()["data"]["status"] == "ready"
    assert (
        alipay_response.json()["data"]["secrets"]["private_key"]["display"]
        == "configured"
    )
    assert (
        alipay_response.json()["data"]["secrets"]["public_key"]["display"]
        == "configured"
    )
    assert alipay_private_key not in json.dumps(alipay_response.json())
    assert alipay_public_key not in json.dumps(alipay_response.json())

    alipay_test_response = client.post(
        "/internal/service/admin/service-settings/alipay-payment/test",
        headers=build_internal_headers(idempotency_key="service-settings-alipay-test-001"),
    )
    assert alipay_test_response.status_code == 200, alipay_test_response.text
    assert alipay_test_response.json()["data"]["status"] == "ready"

    with get_session(database_url) as session:
        qq_row = session.get(ServiceSetting, "portal_qq_login")
        email_row = session.get(ServiceSetting, "portal_email")
        alipay_row = session.get(ServiceSetting, "payment_alipay")
        assert qq_row is not None
        assert email_row is not None
        assert alipay_row is not None
        assert decrypt_service_setting_secret(
            str((qq_row.secret_ciphertext_json or {})["client_secret"]),
            settings=_runtime_service_settings(database_url),
        ) == "qq-client-secret"
        assert decrypt_service_setting_secret(
            str((email_row.secret_ciphertext_json or {})["smtp_password"]),
            settings=_runtime_service_settings(database_url),
        ) == "smtp-password"
        assert decrypt_service_setting_secret(
            str((alipay_row.secret_ciphertext_json or {})["private_key"]),
            settings=_runtime_service_settings(database_url),
        ) == alipay_private_key.strip()
        assert decrypt_service_setting_secret(
            str((alipay_row.secret_ciphertext_json or {})["public_key"]),
            settings=_runtime_service_settings(database_url),
        ) == alipay_public_key.strip()

    list_response = client.get(
        "/internal/service/admin/service-settings",
        headers=build_internal_headers(),
    )
    assert list_response.status_code == 200
    data = list_response.json()["data"]
    assert data["settings"]["qq_login"]["configured"] is True
    assert data["settings"]["portal_email"]["configured"] is True
    assert data["settings"]["alipay_payment"]["configured"] is True
    assert data["boundary"]["wordpress_control_plane"] is False
    assert "smtp-password" not in json.dumps(data)
    assert alipay_private_key not in json.dumps(data)
    assert alipay_public_key not in json.dumps(data)

    dispose_engine(database_url)


def test_admin_service_settings_reject_qq_redirect_outside_public_base(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    public_response = client.patch(
        "/internal/service/admin/service-settings/portal-public",
        json={"public_base_url": "https://cloud.example.com"},
        headers=build_internal_headers(idempotency_key="service-settings-bad-public-001"),
    )
    assert public_response.status_code == 200

    response = client.patch(
        "/internal/service/admin/service-settings/qq-login",
        json={
            "client_id": "qq-client-id",
            "client_secret": "qq-client-secret",
            "redirect_uri": "https://evil.example.com/open/auth/qq/callback",
            "scope": "get_user_info",
            "timeout_seconds": 10,
        },
        headers=build_internal_headers(idempotency_key="service-settings-bad-qq-001"),
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "service_settings.qq_redirect_uri_invalid"

    dispose_engine(database_url)


def test_admin_service_settings_allow_legacy_qq_redirect_path(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    public_response = client.patch(
        "/internal/service/admin/service-settings/portal-public",
        json={"public_base_url": "https://cloud.example.com"},
        headers=build_internal_headers(idempotency_key="service-settings-legacy-public-001"),
    )
    assert public_response.status_code == 200

    response = client.patch(
        "/internal/service/admin/service-settings/qq-login",
        json={
            "client_id": "qq-client-id",
            "client_secret": "qq-client-secret",
            "redirect_uri": "https://cloud.example.com/portal/v1/auth/qq/callback",
            "scope": "get_user_info",
            "timeout_seconds": 10,
        },
        headers=build_internal_headers(idempotency_key="service-settings-legacy-qq-001"),
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "ready"

    dispose_engine(database_url)


def test_admin_service_settings_reject_email_ssl_and_starttls(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)

    response = client.patch(
        "/internal/service/admin/service-settings/email",
        json={
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "smtp_username": "smtp-user",
            "smtp_password": "smtp-password",
            "smtp_use_ssl": True,
            "smtp_use_starttls": True,
            "smtp_timeout_seconds": 20,
            "from_email": "noreply@example.com",
            "from_name": "Npcink AI Cloud",
            "reply_to": "support@example.com",
        },
        headers=build_internal_headers(idempotency_key="service-settings-bad-email-tls-001"),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "service_settings.email_tls_mode_invalid"

    dispose_engine(database_url)


def test_admin_image_source_provider_env_settings_route_is_retired(
    tmp_path: Path,
) -> None:
    _, client = _build_client(
        tmp_path,
        settings_overrides={
            "image_source_provider": "disabled",
        },
    )

    get_response = client.get(
        "/internal/service/admin/image-source-providers",
        headers=build_internal_headers(),
    )
    post_response = client.post(
        "/internal/service/admin/image-source-providers",
        headers=build_internal_headers(idempotency_key="image-source-provider-save"),
        json={
            "provider_mode": "auto",
            "providers": {},
            "runtime": {},
        },
    )

    assert get_response.status_code == 404
    assert post_response.status_code == 404


def test_admin_audio_provider_env_settings_routes_are_retired(
    tmp_path: Path,
) -> None:
    _, client = _build_client(tmp_path)

    get_response = client.get(
        "/internal/service/admin/audio-providers",
        headers=build_internal_headers(),
    )
    post_response = client.post(
        "/internal/service/admin/audio-providers",
        headers=build_internal_headers(idempotency_key="audio-provider-save-retired"),
        json={"provider_mode": "minimax"},
    )
    test_response = client.post(
        "/internal/service/admin/audio-providers/minimax/test",
        headers=build_internal_headers(idempotency_key="audio-provider-test-retired"),
        json={},
    )

    assert get_response.status_code == 404
    assert post_response.status_code == 404
    assert test_response.status_code == 404


def test_admin_ai_resources_projects_connections_capabilities_and_profiles(
    tmp_path: Path,
) -> None:
    _, client = _build_client(
        tmp_path,
        settings_overrides={
            "openai_api_key": "openai-test-secret",
            "openai_provider_label": "GPT 5.5 hosted",
            "minimax_provider_enabled": True,
            "minimax_api_key": "minimax-test-secret",
            "minimax_group_id": "group-test-secret",
        },
    )

    response = client.get(
        "/internal/service/admin/ai-resources",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["surface"] == "admin_ai_resources"
    connection_ids = {item["connection_id"] for item in data["connections"]}
    capability_ids = {item["capability_id"] for item in data["capabilities"]}
    matrix_ids = {item["capability_id"] for item in data["capability_matrix"]}
    profile_ids = {item["profile_id"] for item in data["runtime_profiles"]}
    assert "web_search_tavily" not in connection_ids
    assert "image_source_unsplash" not in connection_ids
    assert "embedding_deterministic" not in connection_ids
    assert {"text_generation", "audio_generation", "image_generation", "embedding"}.issubset(
        capability_ids
    )
    assert {"text_generation", "audio_generation", "image_generation", "embedding"}.issubset(
        matrix_ids
    )
    feature_ids = {item["feature_id"] for item in data["feature_model_usage"]}
    assert {
        "content_support",
        "audio_summary_script",
        "article_narration",
        "article_audio_summary",
        "generated_image_candidates",
        "site_knowledge_embedding",
    }.issubset(feature_ids)
    assert data["provider_model_health"]["source"] == "provider_call_records"
    assert data["provider_model_health"]["content_exposed"] is False
    assert data["provider_model_health"]["boundary"]["not_a_control_plane"] is True
    assert {
        TEXT_AI_PROFILE_ID,
        "audio.narration.default",
        "audio.summary.default",
        "grok-imagine-image-quality",
        "embed.default",
    }.issubset(profile_ids)
    matrix = {item["capability_id"]: item for item in data["capability_matrix"]}
    assert matrix["text_generation"]["selection_owner"] == "cloud_runtime_metadata"
    assert matrix["text_generation"]["direct_wordpress_write"] is False
    assert matrix["image_generation"]["write_posture"] == "candidate_artifact_only"
    assert matrix["embedding"]["default_profile_id"] == "embed.default"
    assert data["boundary"]["direct_wordpress_write"] is False
    assert data["boundary"]["not_a_control_plane"] is True
    serialized = json.dumps(data)
    assert "openai-test-secret" not in serialized
    assert "minimax-test-secret" not in serialized
    assert "group-test-secret" not in serialized


def test_admin_ability_model_runtime_projection_is_bounded_and_feature_backed(
    tmp_path: Path,
) -> None:
    _, client = _build_client(
        tmp_path,
        settings_overrides={
            "openai_api_key": "openai-test-secret",
            "openai_provider_label": "GPT 5.5 hosted",
            "minimax_provider_enabled": True,
            "minimax_api_key": "minimax-test-secret",
            "minimax_group_id": "group-test-secret",
        },
    )

    response = client.get(
        "/internal/service/admin/ability-models/runtime-projection",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["surface"] == "admin_ability_model_runtime_projection"
    assert data["projection_version"] == "admin-ability-model-runtime-projection.v1"
    assert data["source_surface"] == "admin_ai_resources"
    assert data["boundary"]["read_only"] is False
    assert data["boundary"]["runtime_binding_only"] is True
    assert data["boundary"]["configurable_runtime_bindings"] == ["site_knowledge_embedding"]
    assert data["boundary"]["direct_wordpress_write"] is False
    assert data["boundary"]["not_a_control_plane"] is True
    assert "plugin_specific_overrides" in data["boundary"]["does_not_own"]

    rows = {item["ability_id"]: item for item in data["rows"]}
    assert {
        "site_knowledge_embedding",
        "evidence_preflight",
        "image_source_candidates",
    }.issubset(rows)
    assert {
        "content_support",
        "generated_image_candidates",
        "audio_summary_script",
        "article_narration",
        "article_audio_summary",
    }.isdisjoint(rows)
    assert rows["site_knowledge_embedding"]["media"] == "vector"
    assert rows["site_knowledge_embedding"]["model_kind"] == "embedding_model"
    assert rows["site_knowledge_embedding"]["can_configure"] is True
    assert rows["site_knowledge_embedding"]["action"] == "configure_runtime_model"
    assert rows["site_knowledge_embedding"]["boundary"]["runtime_binding_only"] is True
    assert rows["evidence_preflight"]["model_kind"] == "search_text_model"

    media_groups = {item["media"]: item for item in data["media_groups"]}
    assert {"text", "image", "vector", "audio", "video"}.issubset(media_groups)
    assert media_groups["text"]["count"] >= 1
    assert media_groups["image"]["count"] >= 1
    assert media_groups["vector"]["count"] >= 1
    assert media_groups["audio"]["count"] == 0
    assert media_groups["video"]["count"] == 0

    serialized = json.dumps(data)
    assert "openai-test-secret" not in serialized
    assert "minimax-test-secret" not in serialized
    assert "group-test-secret" not in serialized

    unauthorized = client.get("/internal/service/admin/ability-models/runtime-projection")
    assert unauthorized.status_code == 401


class FixedSiliconFlowEmbeddingProvider:
    provider_id = "siliconflow"
    display_name = "SiliconFlow"
    adapter_type = "siliconflow"

    def fetch_catalog(self) -> ProviderCatalogSnapshot:
        return ProviderCatalogSnapshot(
            provider_id=self.provider_id,
            display_name=self.display_name,
            adapter_type=self.adapter_type,
            models=[
                CatalogModelSeed(
                    model_id="siliconflow/BAAI/bge-m3",
                    family="bge",
                    feature="embedding",
                    status="available",
                    context_window=8192,
                    price_input=0.0,
                    price_output=0.0,
                    raw_json={"dimensions": 1024},
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="siliconflow-bge-m3-embed",
                            endpoint_variant="embeddings",
                            region="global",
                            capability_tags=["embedding", "site-knowledge"],
                            is_default=True,
                            weight=100,
                        )
                    ],
                )
            ],
        )

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        raise ProviderExecutionError("provider.not_executed", "not used by this test")


def test_admin_ability_model_runtime_binding_updates_site_knowledge_embedding(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        providers={"siliconflow": FixedSiliconFlowEmbeddingProvider()},
    )
    services = client.app.state.services
    with get_session(database_url) as session:
        session.add(
            ProviderConnection(
                connection_id="model_siliconflow",
                provider_type="siliconflow",
                display_name="SiliconFlow",
                enabled=True,
                base_url="https://api.siliconflow.cn/v1",
                config_json={
                    "provider_id": "siliconflow",
                    "kind": "siliconflow",
                    "capability_ids": ["text_generation", "embedding"],
                    "runtime_profile_ids": ["text.ai", "embed.default"],
                    "model_id": "siliconflow/Qwen/Qwen3-8B",
                },
                secret_ciphertext=encrypt_provider_connection_secret(
                    "configured-in-test",
                    settings=services.settings,
                ),
                status="configured",
                source_role="execution_source",
                metadata_json={},
            )
        )
        session.commit()

    response = client.post(
        "/internal/service/admin/ability-models/runtime-binding",
        headers=build_internal_headers(idempotency_key="ability-binding-save"),
        json={
            "ability_id": "site_knowledge_embedding",
            "instance_id": "siliconflow-bge-m3-embed",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    row = {item["ability_id"]: item for item in data["rows"]}["site_knowledge_embedding"]
    assert row["media"] == "vector"
    assert row["can_configure"] is True
    assert row["provider_id"] == "siliconflow"
    assert row["model_id"] == "siliconflow/BAAI/bge-m3"
    assert data["boundary"]["runtime_binding_only"] is True
    assert data["boundary"]["direct_wordpress_write"] is False
    assert data["receipt"]["event_kind"] == "ability_model_runtime_binding.update"

    with get_session(database_url) as session:
        connection = session.get(ProviderConnection, "model_siliconflow")
        assert connection is not None
        config = connection.config_json or {}
        assert config["provider_id"] == "siliconflow"
        assert config["model_id"] == "siliconflow/BAAI/bge-m3"
        assert "embedding" in config["capability_ids"]
        assert "embed.default" in config["runtime_profile_ids"]
        assert config["dimensions"] == 1024

    serialized = json.dumps(data)
    assert "configured-in-test" not in serialized


def test_admin_provider_connections_store_encrypted_credentials_and_project_to_ai_resources(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)

    response = client.post(
        "/internal/service/admin/provider-connections",
        headers=build_internal_headers(idempotency_key="provider-connection-save"),
        json={
            "connection_id": "openai_primary",
            "provider_id": "openai",
            "provider_type": "openai_compatible",
            "kind": "openai_compatible",
            "display_name": "OpenAI primary",
            "enabled": True,
            "base_url": "https://api.openai.test/v1",
            "capability_ids": ["text_generation", "image_generation"],
            "runtime_profile_ids": [TEXT_AI_PROFILE_ID, "grok-imagine-image-quality"],
            "config": {
                "model_ids": ["gpt-5.5", "gpt-4o-mini"],
                "model_id": "gpt-5.5",
            },
            "credential": "provider-connection-test-secret",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["connection_id"] == "openai_primary"
    assert data["status"] == "ready"
    assert data["configured"] is True
    assert data["receipt"]["event_kind"] == "provider_connection.save"
    assert data["receipt"]["scope_kind"] == "provider_connection"
    assert data["receipt"]["scope_id"] == "openai_primary"
    assert data["receipt"]["audit_filters"]["event_kind"] == "provider_connection.save"
    assert data["model_ids"] == ["gpt-5.5", "gpt-4o-mini"]
    assert data["secrets"]["credential"]["display"] == "configured"
    serialized = json.dumps(response.json())
    assert "provider-connection-test-secret" not in serialized

    with get_session(database_url) as session:
        row = session.get(ProviderConnection, "openai_primary")
        assert row is not None
        assert row.secret_ciphertext
        assert "provider-connection-test-secret" not in row.secret_ciphertext
        services = client.app.state.services
        assert (
            decrypt_provider_connection_secret(
                row.secret_ciphertext,
                settings=services.settings,
            )
            == "provider-connection-test-secret"
        )
        audit_event = session.scalar(
            select(ServiceAuditEvent)
            .where(ServiceAuditEvent.event_kind == "provider_connection.save")
            .order_by(ServiceAuditEvent.id.desc())
        )
        assert audit_event is not None
        assert audit_event.outcome == "succeeded"
        assert audit_event.scope_kind == "provider_connection"
        assert audit_event.scope_id == "openai_primary"
        audit_payload = audit_event.payload_json or {}
        assert audit_payload["request"]["credential_provided"] is True
        assert audit_payload["credential_value_exposure"] == "presence_only"
        assert "provider-connection-test-secret" not in json.dumps(audit_payload)

    projection_response = client.get(
        "/internal/service/admin/ai-resources",
        headers=build_internal_headers(),
    )
    assert projection_response.status_code == 200, projection_response.text
    projection = projection_response.json()["data"]
    connections = {item["connection_id"]: item for item in projection["connections"]}
    assert connections["openai_primary"]["managed_by"] == "cloud_provider_connections"
    assert connections["openai_primary"]["model_ids"] == ["gpt-5.5", "gpt-4o-mini"]
    capabilities = {item["capability_id"]: item for item in projection["capabilities"]}
    assert "openai_primary" in capabilities["text_generation"]["connection_ids"]
    assert "openai_primary" in capabilities["image_generation"]["connection_ids"]
    assert projection["runtime_resolution"]
    assert "env_migration" not in projection
    assert "provider-connection-test-secret" not in json.dumps(projection)


def test_admin_provider_connection_catalog_preview_fetches_models_without_persisting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, client = _build_client(tmp_path)

    def fake_fetch_catalog(self: object) -> ProviderCatalogSnapshot:
        return ProviderCatalogSnapshot(
            provider_id="mqzj",
            display_name="MQZJ",
            adapter_type="openai",
            models=[
                CatalogModelSeed(
                    model_id="gpt-5.5",
                    family="gpt-5.5",
                    feature="text",
                    status="available",
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="mqzj-gpt55",
                            endpoint_variant="chat_completions",
                            region="test",
                        )
                    ],
                ),
                CatalogModelSeed(
                    model_id="gpt-4o-mini",
                    family="gpt-4o",
                    feature="text",
                    status="available",
                    instances=[],
                ),
            ],
        )

    monkeypatch.setattr(
        "app.adapters.providers.openai.OpenAIProviderAdapter.fetch_catalog",
        fake_fetch_catalog,
    )

    response = client.post(
        "/internal/service/admin/provider-connections/preview-catalog",
        headers=build_internal_headers(idempotency_key="provider-connection-preview-catalog"),
        json={
            "connection_id": "mqzj_preview",
            "provider_id": "mqzj",
            "provider_type": "openai_compatible",
            "kind": "openai_compatible",
            "display_name": "MQZJ",
            "enabled": True,
            "base_url": "https://api.mqzj.top/v1",
            "capability_ids": ["text_generation"],
            "runtime_profile_ids": [TEXT_AI_PROFILE_ID],
            "credential": "preview-secret-value",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["surface"] == "admin_provider_connection_catalog_preview"
    assert data["model_count"] == 2
    assert data["model_ids"] == ["gpt-5.5", "gpt-4o-mini"]
    assert data["truncated"] is False
    assert data["models"][0] == {
        "model_id": "gpt-5.5",
        "family": "gpt-5.5",
        "feature": "text",
        "status": "available",
        "is_deprecated": False,
        "runtime_supported": True,
        "verified": True,
        "capability_tags": [],
    }
    assert data["models"][1]["runtime_supported"] is False
    assert data["credential_value_exposure"] == "none"
    assert data["boundary"]["secret_exposure"] == "masked_status_only"
    assert "preview-secret-value" not in json.dumps(response.json())
    with get_session(database_url) as session:
        assert session.get(ProviderConnection, "mqzj_preview") is None


def test_admin_provider_connection_test_syncs_catalog_for_openai_compatible_supplier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = _build_client(tmp_path)

    def fake_fetch_catalog(self: Any) -> ProviderCatalogSnapshot:
        provider_id = str(getattr(self, "provider_id", "") or "")
        display_name = str(getattr(self, "display_name", "") or "")
        return ProviderCatalogSnapshot(
            provider_id=provider_id,
            display_name=display_name,
            adapter_type="openai",
            models=[
                CatalogModelSeed(
                    model_id="deepseek-chat",
                    family="deepseek",
                    feature="text",
                    status="available",
                    instances=[
                        CatalogInstanceSeed(
                            instance_id=f"{provider_id}-global-deepseek-chat",
                            endpoint_variant="chat_completions",
                            region="global",
                            capability_tags=["text", "balanced"],
                            is_default=True,
                            weight=100,
                        )
                    ],
                )
            ],
        )

    monkeypatch.setattr(
        "app.adapters.providers.openai.OpenAIProviderAdapter.fetch_catalog",
        fake_fetch_catalog,
    )

    create_response = client.post(
        "/internal/service/admin/provider-connections",
        headers=build_internal_headers(idempotency_key="provider-connection-deepseek-save"),
        json={
            "connection_id": "deepseek",
            "provider_id": "deepseek",
            "provider_type": "openai_compatible",
            "kind": "openai_compatible",
            "display_name": "DeepSeek",
            "enabled": True,
            "base_url": "https://api.deepseek.com/v1",
            "capability_ids": ["text_generation"],
            "runtime_profile_ids": [TEXT_AI_PROFILE_ID],
            "config": {"model_ids": ["deepseek-chat"], "model_id": "deepseek-chat"},
            "credential": "deepseek-secret-value",
        },
    )
    assert create_response.status_code == 200, create_response.text

    test_response = client.post(
        "/internal/service/admin/provider-connections/deepseek/test",
        headers=build_internal_headers(idempotency_key="provider-connection-deepseek-test"),
    )

    assert test_response.status_code == 200, test_response.text
    test_data = test_response.json()["data"]
    assert test_data["catalog"]["provider_id"] == "deepseek"
    assert test_data["catalog"]["display_name"] == "DeepSeek"
    assert test_data["catalog"]["adapter_type"] == "openai"
    assert test_data["catalog"]["sync"]["status"] == "synced"
    assert test_data["receipt"]["event_kind"] == "provider_connection.test"
    assert test_data["receipt"]["scope_id"] == "deepseek"
    assert test_data["receipt"]["audit_filters"]["event_kind"] == "provider_connection.test"
    assert "deepseek-secret-value" not in json.dumps(test_response.json())

    routing_response = client.get(
        "/internal/service/admin/wordpress-ai-routing",
        headers=build_internal_headers(),
    )

    assert routing_response.status_code == 200, routing_response.text
    routing_data = routing_response.json()["data"]
    deepseek_instances = [
        item
        for item in routing_data["available_text_instances"]
        if item["provider_id"] == "deepseek"
    ]
    assert deepseek_instances
    assert deepseek_instances[0]["provider_display_name"] == "DeepSeek"
    assert deepseek_instances[0]["adapter_type"] == "openai"
    assert deepseek_instances[0]["model_id"] == "deepseek-chat"


def test_admin_provider_connection_catalog_preview_returns_all_upstream_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, client = _build_client(tmp_path)

    def fake_fetch_catalog(self: Any) -> ProviderCatalogSnapshot:
        return ProviderCatalogSnapshot(
            provider_id="minimax",
            display_name="MiniMax",
            adapter_type="minimax",
            models=[
                CatalogModelSeed(
                    model_id=f"minimax-model-{index:03d}",
                    family="minimax",
                    feature="text" if index % 2 else "audio",
                    status="available",
                    instances=[
                        CatalogInstanceSeed(
                            instance_id=f"minimax-model-{index:03d}",
                            endpoint_variant="runtime",
                            region="global",
                        )
                    ],
                )
                for index in range(1, 110)
            ],
        )

    monkeypatch.setattr(
        "app.adapters.providers.minimax.MiniMaxProviderAdapter.fetch_catalog",
        fake_fetch_catalog,
    )

    response = client.post(
        "/internal/service/admin/provider-connections/preview-catalog",
        headers=build_internal_headers(idempotency_key="provider-connection-preview-full-catalog"),
        json={
            "connection_id": "minimax_preview",
            "provider_id": "minimax",
            "provider_type": "minimax",
            "kind": "minimax",
            "display_name": "MiniMax",
            "enabled": True,
            "base_url": "https://api.minimaxi.com",
            "capability_ids": [
                "text_generation",
                "image_generation",
                "audio_generation",
                "video_generation",
            ],
            "runtime_profile_ids": [],
            "credential": "preview-secret-value",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["model_count"] == 109
    assert len(data["model_ids"]) == 109
    assert len(data["models"]) == 109
    assert data["model_ids"][-1] == "minimax-model-109"
    assert data["models"][-1]["model_id"] == "minimax-model-109"
    assert data["truncated"] is False


def test_admin_provider_connection_catalog_preview_uses_saved_secret_without_exposing_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, client = _build_client(tmp_path)
    create_response = client.post(
        "/internal/service/admin/provider-connections",
        headers=build_internal_headers(idempotency_key="provider-connection-preview-saved-create"),
        json={
            "connection_id": "mqzj_saved",
            "provider_id": "mqzj",
            "provider_type": "openai_compatible",
            "kind": "openai_compatible",
            "display_name": "MQZJ",
            "enabled": True,
            "base_url": "https://api.mqzj.top/v1",
            "capability_ids": ["text_generation"],
            "runtime_profile_ids": [TEXT_AI_PROFILE_ID],
            "credential": "saved-preview-secret",
        },
    )
    assert create_response.status_code == 200, create_response.text

    def fake_fetch_catalog(self: object) -> ProviderCatalogSnapshot:
        return ProviderCatalogSnapshot(
            provider_id="mqzj",
            display_name="MQZJ",
            adapter_type="openai",
            models=[
                CatalogModelSeed(
                    model_id="gpt-5.5",
                    family="gpt-5.5",
                    feature="text",
                    status="available",
                    instances=[],
                )
            ],
        )

    monkeypatch.setattr(
        "app.adapters.providers.openai.OpenAIProviderAdapter.fetch_catalog",
        fake_fetch_catalog,
    )

    response = client.post(
        "/internal/service/admin/provider-connections/preview-catalog",
        headers=build_internal_headers(idempotency_key="provider-connection-preview-saved"),
        json={
            "connection_id": "mqzj_saved",
            "provider_id": "mqzj",
            "provider_type": "openai_compatible",
            "kind": "openai_compatible",
            "display_name": "MQZJ",
            "enabled": True,
            "base_url": "https://api.mqzj.top/v1",
            "capability_ids": ["text_generation"],
            "runtime_profile_ids": [TEXT_AI_PROFILE_ID],
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["model_ids"] == ["gpt-5.5"]
    assert "saved-preview-secret" not in json.dumps(response.json())
    with get_session(database_url) as session:
        assert session.get(ProviderConnection, "mqzj_saved") is not None


def test_admin_provider_connection_catalog_preview_reports_unreadable_saved_secret(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    create_response = client.post(
        "/internal/service/admin/provider-connections",
        headers=build_internal_headers(
            idempotency_key="provider-connection-preview-unreadable-create"
        ),
        json={
            "connection_id": "minimax_unreadable",
            "provider_id": "minimax",
            "provider_type": "minimax",
            "kind": "minimax",
            "display_name": "MiniMax",
            "enabled": True,
            "base_url": "https://api.minimaxi.com",
            "capability_ids": ["audio_generation"],
            "runtime_profile_ids": [AUDIO_NARRATION_PROFILE_ID],
            "credential": "saved-preview-secret",
        },
    )
    assert create_response.status_code == 200, create_response.text
    with get_session(database_url) as session:
        row = session.get(ProviderConnection, "minimax_unreadable")
        assert row is not None
        row.secret_ciphertext = "not-a-valid-fernet-token"
        session.commit()

    response = client.post(
        "/internal/service/admin/provider-connections/preview-catalog",
        headers=build_internal_headers(
            idempotency_key="provider-connection-preview-unreadable"
        ),
        json={
            "connection_id": "minimax_unreadable",
            "provider_id": "minimax",
            "provider_type": "minimax",
            "kind": "minimax",
            "display_name": "MiniMax",
            "enabled": True,
            "base_url": "https://api.minimaxi.com",
            "capability_ids": ["audio_generation"],
            "runtime_profile_ids": [AUDIO_NARRATION_PROFILE_ID],
        },
    )

    assert response.status_code == 400, response.text
    payload = response.json()
    assert payload["error_code"] == "provider_connection.saved_credential_unreadable"
    assert payload["message"] == (
        "saved provider credential cannot be decrypted; enter the API key again and save"
    )
    assert "saved-preview-secret" not in json.dumps(payload)


def test_admin_provider_connection_catalog_preview_error_hides_upstream_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = _build_client(tmp_path)

    def fake_fetch_catalog(self: object) -> ProviderCatalogSnapshot:
        raise RuntimeError("traceback with preview-secret-value and provider stack frame")

    monkeypatch.setattr(
        "app.adapters.providers.openai.OpenAIProviderAdapter.fetch_catalog",
        fake_fetch_catalog,
    )

    response = client.post(
        "/internal/service/admin/provider-connections/preview-catalog",
        headers=build_internal_headers(idempotency_key="provider-connection-preview-error"),
        json={
            "connection_id": "mqzj_preview_error",
            "provider_id": "mqzj",
            "provider_type": "openai_compatible",
            "kind": "openai_compatible",
            "display_name": "MQZJ",
            "enabled": True,
            "base_url": "https://api.mqzj.top/v1",
            "capability_ids": ["text_generation"],
            "runtime_profile_ids": [TEXT_AI_PROFILE_ID],
            "credential": "preview-secret-value",
        },
    )

    assert response.status_code == 502, response.text
    payload = response.json()
    assert payload["error_code"] == "provider_connection.test_failed"
    assert payload["message"] == "provider connection catalog preview failed"
    serialized = json.dumps(payload)
    assert "preview-secret-value" not in serialized
    assert "traceback" not in serialized
    assert "provider stack frame" not in serialized


def test_admin_model_references_syncs_models_dev_payload_as_reference_only(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    response = client.post(
        "/internal/service/admin/model-references/sync",
        headers=build_internal_headers(idempotency_key="model-references-sync"),
        json={
            "payload": {
                "providers": {
                    "openai": {
                        "id": "openai",
                        "name": "OpenAI",
                        "doc": "https://platform.openai.com/docs",
                        "models": {
                            "gpt-5.5": {
                                "id": "gpt-5.5",
                                "name": "GPT-5.5",
                                "family": "gpt",
                                "reasoning": True,
                                "tool_call": True,
                                "structured_output": True,
                                "release_date": "2026-06-01",
                                "last_updated": "2026-06-18",
                                "modalities": {
                                    "input": ["text", "image"],
                                    "output": ["text"],
                                },
                                "limit": {"context": 256000, "output": 64000},
                                "cost": {
                                    "input": 1.25,
                                    "output": 10.0,
                                    "cache_read": 0.125,
                                },
                            },
                            "gpt-image-2": {
                                "id": "gpt-image-2",
                                "name": "GPT Image 2",
                                "family": "gpt-image",
                                "deprecated": True,
                                "modalities": {
                                    "input": ["text", "image"],
                                    "output": ["image"],
                                },
                                "limit": {"context": 32000, "output": 1},
                                "cost": {
                                    "input": 2.0,
                                    "output": 12.0,
                                },
                            },
                        },
                    },
                    "deepseek": {
                        "id": "deepseek",
                        "name": "DeepSeek",
                        "doc": "https://api-docs.deepseek.com",
                        "models": {
                            "deepseek-v4-flash": {
                                "id": "deepseek-v4-flash",
                                "name": "DeepSeek V4 Flash",
                                "family": "deepseek",
                                "reasoning": True,
                                "modalities": {
                                    "input": ["text"],
                                    "output": ["text"],
                                },
                                "limit": {"context": 128000, "output": 8000},
                                "cost": {
                                    "input": 0.14,
                                    "output": 0.28,
                                    "cache_read": 0.0028,
                                },
                            },
                            "deepseek-v4-pro": {
                                "id": "deepseek-v4-pro",
                                "name": "DeepSeek V4 Pro",
                                "family": "deepseek",
                                "reasoning": True,
                                "modalities": {
                                    "input": ["text"],
                                    "output": ["text"],
                                },
                                "limit": {"context": 128000, "output": 8000},
                                "cost": {
                                    "input": 0.435,
                                    "output": 0.87,
                                    "cache_read": 0.003625,
                                },
                            },
                        },
                    },
                }
            }
        },
    )

    assert response.status_code == 200, response.text
    sync_data = response.json()["data"]
    assert sync_data["surface"] == "admin_model_reference_sync"
    assert sync_data["source_id"] == "models.dev"
    assert sync_data["model_count"] == 4
    assert sync_data["price_unit"] == "usd_per_1m_tokens"
    assert sync_data["billing_truth"] is False
    assert sync_data["boundary"]["reference_only"] is True
    assert sync_data["boundary"]["routing_truth"] is False

    with get_session(database_url) as session:
        source = session.get(ModelReferenceSource, "models.dev")
        assert source is not None
        assert source.status == "active"

    list_response = client.get(
        "/internal/service/admin/model-references?provider_id=openai",
        headers=build_internal_headers(),
    )
    assert list_response.status_code == 200, list_response.text
    data = list_response.json()["data"]
    assert data["surface"] == "admin_model_references"
    assert data["boundary"]["billing_truth"] is False
    assert data["total"] == 2
    assert data["items"][0]["model_id"] == "gpt-5.5"
    assert data["items"][0]["feature"] == "text"
    assert data["items"][0]["capability_flags"]["reasoning"] is True
    assert data["items"][0]["price"] == {
        "input": 1.25,
        "output": 10.0,
        "cache_read": 0.125,
        "cache_write": None,
        "unit": "usd_per_1m_tokens",
        "billing_truth": False,
    }
    assert "OpenAI" in json.dumps(data)

    image_response = client.get(
        "/internal/service/admin/model-references?provider_id=openai&feature=image",
        headers=build_internal_headers(),
    )
    assert image_response.status_code == 200, image_response.text
    image_data = image_response.json()["data"]
    assert image_data["total"] == 1
    assert image_data["items"][0]["model_id"] == "gpt-image-2"
    assert image_data["items"][0]["feature"] == "image"
    assert image_data["items"][0]["is_deprecated"] is True

    deepseek_response = client.get(
        "/internal/service/admin/model-references?provider_id=deepseek",
        headers=build_internal_headers(),
    )
    assert deepseek_response.status_code == 200, deepseek_response.text
    deepseek_data = deepseek_response.json()["data"]
    assert deepseek_data["total"] == 2
    assert deepseek_data["items"][0]["model_id"] == "deepseek-v4-flash"
    assert deepseek_data["items"][0]["feature"] == "text"
    assert deepseek_data["items"][0]["context_window"] == 128000
    assert deepseek_data["items"][0]["price"]["cache_read"] == 0.0028
    assert deepseek_data["items"][1]["model_id"] == "deepseek-v4-pro"

    active_response = client.get(
        "/internal/service/admin/model-references?provider_id=openai&include_deprecated=false&search=image",
        headers=build_internal_headers(),
    )
    assert active_response.status_code == 200, active_response.text
    active_data = active_response.json()["data"]
    assert active_data["total"] == 0

    with get_session(database_url) as session:
        row = session.scalar(
            select(ModelReferenceModel).where(
                ModelReferenceModel.provider_id == "openai",
                ModelReferenceModel.model_id == "gpt-5.5",
            )
        )
        assert row is not None
        assert row.context_window == 256000


def test_admin_ai_resources_lists_only_added_capability_provider_connections(
    tmp_path: Path,
) -> None:
    _, client = _build_client(tmp_path)

    initial_response = client.get(
        "/internal/service/admin/ai-resources",
        headers=build_internal_headers(),
    )
    assert initial_response.status_code == 200, initial_response.text
    initial_connections = {
        item["connection_id"]: item
        for item in initial_response.json()["data"]["connections"]
    }
    assert "search_apify" not in initial_connections
    assert "web_search_tavily" not in initial_connections

    create_response = client.post(
        "/internal/service/admin/provider-connections",
        headers=build_internal_headers(idempotency_key="provider-connection-apify-save"),
        json={
            "connection_id": "search_apify",
            "provider_id": "apify",
            "provider_type": "web_search_provider",
            "kind": "web_search_provider",
            "display_name": "Apify",
            "enabled": True,
            "base_url": "https://api.apify.com/v2",
            "capability_ids": ["web_search"],
            "runtime_profile_ids": ["web-search.managed"],
            "credential": "apify-provider-secret",
        },
    )
    assert create_response.status_code == 200, create_response.text

    projection_response = client.get(
        "/internal/service/admin/ai-resources",
        headers=build_internal_headers(),
    )
    assert projection_response.status_code == 200, projection_response.text
    projection = projection_response.json()["data"]
    connections = {item["connection_id"]: item for item in projection["connections"]}
    web_search_connections = [
        item
        for item in projection["connections"]
        if item.get("kind") == "web_search_provider"
    ]

    assert list(connections.keys()).count("search_apify") == 1
    assert connections["search_apify"]["provider_id"] == "apify"
    assert connections["search_apify"]["status"] == "ready"
    assert [item["connection_id"] for item in web_search_connections] == ["search_apify"]
    capabilities = {item["capability_id"]: item for item in projection["capabilities"]}
    assert capabilities["web_search"]["connection_ids"] == ["search_apify"]
    assert "apify-provider-secret" not in json.dumps(projection)


def test_admin_provider_connection_test_updates_masked_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, client = _build_client(tmp_path)
    client.post(
        "/internal/service/admin/provider-connections",
        headers=build_internal_headers(idempotency_key="provider-connection-test-create"),
        json={
            "connection_id": "openai_testable",
            "provider_id": "openai",
            "provider_type": "openai_compatible",
            "kind": "openai_compatible",
            "display_name": "OpenAI testable",
            "enabled": True,
            "base_url": "https://api.openai.test/v1",
            "capability_ids": ["text_generation"],
            "runtime_profile_ids": [TEXT_AI_PROFILE_ID],
            "credential": "provider-connection-test-secret",
        },
    )

    def fake_fetch_catalog(self: object) -> ProviderCatalogSnapshot:
        return ProviderCatalogSnapshot(
            provider_id="openai",
            display_name="OpenAI testable",
            adapter_type="openai",
            models=[
                CatalogModelSeed(
                    model_id="gpt-test",
                    family="gpt-test",
                    feature="text",
                    status="available",
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="openai-test-text",
                            endpoint_variant="responses",
                            region="test",
                        )
                    ],
                )
            ],
        )

    monkeypatch.setattr(
        "app.adapters.providers.openai.OpenAIProviderAdapter.fetch_catalog",
        fake_fetch_catalog,
    )

    response = client.post(
        "/internal/service/admin/provider-connections/openai_testable/test",
        headers=build_internal_headers(idempotency_key="provider-connection-test-run"),
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["ok"] is True
    assert data["status"] == "ready"
    assert data["catalog"]["model_count"] == 1
    assert data["catalog"]["sample_model_ids"] == ["gpt-test"]
    assert "provider-connection-test-secret" not in json.dumps(response.json())
    with get_session(database_url) as session:
        row = session.get(ProviderConnection, "openai_testable")
        assert row is not None
        assert row.last_tested_at is not None
        assert row.last_error_code in {None, ""}


def test_admin_provider_connection_test_runs_web_search_probe_without_result_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, client = _build_client(tmp_path)
    client.post(
        "/internal/service/admin/provider-connections",
        headers=build_internal_headers(idempotency_key="provider-connection-web-search-create"),
        json={
            "connection_id": "search_tavily_probe",
            "provider_id": "tavily",
            "provider_type": "web_search_provider",
            "kind": "web_search_provider",
            "display_name": "Tavily probe",
            "enabled": True,
            "base_url": "https://api.tavily.test",
            "capability_ids": ["web_search"],
            "runtime_profile_ids": ["web-search.managed"],
            "credential": "tavily-provider-secret",
        },
    )

    def fake_search(
        self: TavilyWebSearchProvider,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> WebSearchExecutionResult:
        assert query == "WordPress AI provider connection smoke test"
        assert options["provider"] == "tavily"
        assert site_id == "admin_provider_connection_test"
        assert run_id.startswith("provider-connection-test-search_tavily_probe-")
        return WebSearchExecutionResult(
            result_json={
                "artifact_type": "web_search_results",
                "provider": "tavily",
                "result_count": 1,
                "results": [
                    {
                        "title": "Do not expose this result title",
                        "url": "https://example.com/source",
                        "snippet": "Do not expose this snippet",
                    }
                ],
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            },
            usage=WebSearchProviderUsage(
                provider_id="tavily",
                model_id="web-search",
                instance_id="cloud-managed",
                region="unspecified",
                latency_ms=17,
            ),
        )

    monkeypatch.setattr(TavilyWebSearchProvider, "search", fake_search)

    response = client.post(
        "/internal/service/admin/provider-connections/search_tavily_probe/test",
        headers=build_internal_headers(idempotency_key="provider-connection-web-search-test"),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    data = payload["data"]
    assert data["ok"] is True
    assert data["stage"] == "web_search_probe"
    assert data["probe"] == {
        "provider_id": "tavily",
        "result_count": 1,
        "latency_ms": 17,
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
    }
    serialized = json.dumps(payload)
    assert "tavily-provider-secret" not in serialized
    assert "Do not expose this result title" not in serialized
    with get_session(database_url) as session:
        row = session.get(ProviderConnection, "search_tavily_probe")
        assert row is not None
        assert row.status == "ready"
        assert row.last_tested_at is not None
        assert row.last_error_code in {None, ""}


def test_admin_provider_connection_test_runs_jina_reader_probe_as_secretless_enhancement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, client = _build_client(tmp_path)
    create_response = client.post(
        "/internal/service/admin/provider-connections",
        headers=build_internal_headers(idempotency_key="provider-connection-jina-reader-create"),
        json={
            "connection_id": "search_jina_reader_probe",
            "provider_id": "jina_reader",
            "provider_type": "web_search_provider",
            "kind": "web_search_provider",
            "display_name": "Jina Reader probe",
            "enabled": True,
            "base_url": "https://r.jina.test",
            "capability_ids": ["web_search"],
            "runtime_profile_ids": ["web-search.reader"],
        },
    )
    assert create_response.status_code == 200, create_response.text
    created = create_response.json()["data"]
    assert created["configured"] is True
    assert created["status"] == "ready"

    def fail_web_search_execute(*args: object, **kwargs: object) -> None:
        raise AssertionError("Jina Reader probe must not run the primary web search service")

    class FakeReaderClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout > 0

        def __enter__(self) -> FakeReaderClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str, *, headers: dict[str, str]) -> httpx.Response:
            assert url == "https://r.jina.test/https://example.com/"
            assert headers == {"Accept": "text/plain"}
            return httpx.Response(
                200,
                content=b"Readable source text that must not leak.",
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(
        "app.domain.provider_connections.service.WebSearchService.execute",
        fail_web_search_execute,
    )
    monkeypatch.setattr("app.domain.provider_connections.service.httpx.Client", FakeReaderClient)

    response = client.post(
        "/internal/service/admin/provider-connections/search_jina_reader_probe/test",
        headers=build_internal_headers(idempotency_key="provider-connection-jina-reader-test"),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    data = payload["data"]
    assert data["ok"] is True
    assert data["stage"] == "web_search_reader_probe"
    assert data["probe"] == {
        "provider_id": "jina_reader",
        "result_count": 1,
        "latency_ms": data["probe"]["latency_ms"],
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
    }
    assert isinstance(data["probe"]["latency_ms"], int)
    assert data["probe"]["latency_ms"] >= 0
    serialized = json.dumps(payload)
    assert "Readable source text" not in serialized
    with get_session(database_url) as session:
        row = session.get(ProviderConnection, "search_jina_reader_probe")
        assert row is not None
        assert row.status == "ready"
        assert (row.config_json or {})["secretless"] is True
        assert row.last_tested_at is not None
        assert row.last_error_code in {None, ""}


def test_admin_provider_connection_test_reports_missing_secret_without_leaking(
    tmp_path: Path,
) -> None:
    _, client = _build_client(tmp_path)
    create_response = client.post(
        "/internal/service/admin/provider-connections",
        headers=build_internal_headers(idempotency_key="provider-connection-test-missing-create"),
        json={
            "connection_id": "missing_secret_provider",
            "provider_id": "missing_secret",
            "provider_type": "openai_compatible",
            "kind": "openai_compatible",
            "display_name": "Missing secret",
            "enabled": True,
            "capability_ids": ["text_generation"],
            "runtime_profile_ids": [TEXT_AI_PROFILE_ID],
        },
    )
    assert create_response.status_code == 200, create_response.text

    response = client.post(
        "/internal/service/admin/provider-connections/missing_secret_provider/test",
        headers=build_internal_headers(idempotency_key="provider-connection-test-missing"),
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["ok"] is False
    assert data["status"] == "missing_secret"
    assert data["error_code"] == "provider_connection.missing_secret"
    assert data["boundary"]["secret_exposure"] == "masked_status_only"
    with get_session(_sqlite_url(tmp_path)) as session:
        audit_event = session.scalar(
            select(ServiceAuditEvent)
            .where(ServiceAuditEvent.event_kind == "provider_connection.test")
            .order_by(ServiceAuditEvent.id.desc())
        )
        assert audit_event is not None
        assert audit_event.outcome == "error"
        assert audit_event.scope_id == "missing_secret_provider"
        assert (audit_event.payload_json or {})["result"]["test"]["error_code"] == (
            "provider_connection.missing_secret"
        )


def test_admin_provider_connections_env_import_route_is_retired(
    tmp_path: Path,
) -> None:
    _, client = _build_client(
        tmp_path,
        settings_overrides={
            "openai_api_key": "openai-env-secret",
            "openai_base_url": "https://env-openai.test/v1",
            "minimax_provider_enabled": True,
            "minimax_api_key": "minimax-env-secret",
            "minimax_group_id": "minimax-env-group",
        },
    )

    response = client.post(
        "/internal/service/admin/provider-connections/import-env",
        headers=build_internal_headers(idempotency_key="provider-connection-import-env"),
    )

    assert response.status_code in {404, 405}, response.text
    with get_session(_sqlite_url(tmp_path)) as session:
        audit_event = session.scalar(
            select(ServiceAuditEvent)
            .where(ServiceAuditEvent.event_kind == "provider_connection.import_env")
            .order_by(ServiceAuditEvent.id.desc())
        )
        assert audit_event is None

    projection_response = client.get(
        "/internal/service/admin/ai-resources",
        headers=build_internal_headers(),
    )
    assert projection_response.status_code == 200, projection_response.text
    projection = projection_response.json()["data"]
    assert "env_migration" not in projection
    assert "openai-env-secret" not in json.dumps(projection)
    assert "minimax-env-secret" not in json.dumps(projection)


def test_admin_provider_connections_can_be_deleted(
    tmp_path: Path,
) -> None:
    _, client = _build_client(tmp_path)
    create_response = client.post(
        "/internal/service/admin/provider-connections",
        headers=build_internal_headers(idempotency_key="provider-connection-create-delete"),
        json={
            "connection_id": "delete_me_provider",
            "provider_id": "delete_me",
            "provider_type": "web_search_provider",
            "display_name": "Delete me",
            "enabled": True,
            "capability_ids": ["web_search"],
            "runtime_profile_ids": ["web-search.managed"],
            "credential": "delete-me-secret",
        },
    )
    assert create_response.status_code == 200, create_response.text

    delete_response = client.delete(
        "/internal/service/admin/provider-connections/delete_me_provider",
        headers=build_internal_headers(idempotency_key="provider-connection-delete"),
    )
    assert delete_response.status_code == 200, delete_response.text
    delete_data = delete_response.json()["data"]
    assert delete_data["deleted"] is True
    assert delete_data["receipt"]["event_kind"] == "provider_connection.delete"
    assert delete_data["receipt"]["scope_id"] == "delete_me_provider"
    assert delete_data["receipt"]["audit_filters"]["event_kind"] == "provider_connection.delete"
    with get_session(_sqlite_url(tmp_path)) as session:
        audit_event = session.scalar(
            select(ServiceAuditEvent)
            .where(ServiceAuditEvent.event_kind == "provider_connection.delete")
            .order_by(ServiceAuditEvent.id.desc())
        )
        assert audit_event is not None
        assert audit_event.outcome == "succeeded"
        assert audit_event.scope_id == "delete_me_provider"
        assert "delete-me-secret" not in json.dumps(audit_event.payload_json or {})

    list_response = client.get(
        "/internal/service/admin/provider-connections",
        headers=build_internal_headers(),
    )
    assert list_response.status_code == 200, list_response.text
    assert list_response.json()["data"]["connections"] == []


def test_admin_ai_resources_reads_injected_runtime_provider_adapters(
    tmp_path: Path,
) -> None:
    script_provider = FixedAudioSummaryScriptProvider()
    audio_provider = MiniMaxProviderAdapter(
        allow_sample_catalog=True,
        allow_sample_execution=True,
    )
    _, client = _build_client(
        tmp_path,
        providers={"openai": script_provider, "minimax": audio_provider},
        settings_overrides={
            "openai_api_key": "",
            "minimax_provider_enabled": False,
            "minimax_api_key": "",
        },
    )

    response = client.get(
        "/internal/service/admin/ai-resources",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    profiles = {item["profile_id"]: item for item in data["runtime_profiles"]}
    assert profiles[TEXT_AI_PROFILE_ID]["status"] == "ready"
    assert profiles["audio.narration.default"]["status"] == "ready"
    assert profiles["audio.summary.default"]["status"] == "ready"
    assert profiles["grok-imagine-image-quality"]["status"] == "ready"


def test_admin_ai_resources_exposes_recent_runtime_evidence_without_content(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_ai_resources",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )
    now = datetime.now(UTC)
    with get_session(database_url) as session:
        session.add(
            RunRecord(
                run_id="run_ai_resources_text_recent",
                site_id="site_ai_resources",
                account_id="acct_site_ai_resources",
                subscription_id=None,
                plan_version_id=None,
                ability_name="npcink-toolbox/ai-content-support",
                ability_family="text",
                skill_id="",
                workflow_id="",
                contract_version="hosted_ai_content_support.v1",
                channel="admin",
                execution_kind="text",
                execution_tier="cloud",
                execution_pattern="inline",
                data_classification="public_site_content",
                profile_id=TEXT_AI_PROFILE_ID,
                canonical_run_id=None,
                status="succeeded",
                idempotency_key="idem-ai-resources-text-recent",
                request_fingerprint="fingerprint-ai-resources-text-recent",
                trace_id="trace-ai-resources-text-recent",
                cancel_requested_at=None,
                canceled_at=None,
                input_json={"prompt": "sensitive draft body should not appear"},
                execution_input_ciphertext=None,
                policy_json={},
                result_ref="inline",
                result_json={"output_text": "generated text should not appear"},
                error_code=None,
                error_message=None,
                callback_status="not_requested",
                callback_attempt_count=0,
                callback_last_attempt_at=None,
                callback_delivered_at=None,
                callback_next_attempt_at=None,
                callback_last_error_code=None,
                callback_last_error_message=None,
                selected_provider_id="openai",
                selected_model_id="gpt-5.5",
                selected_instance_id="openai-global-gpt-5-5",
                fallback_used=False,
                started_at=now,
                processing_started_at=now,
                finished_at=now,
                retention_expires_at=now + timedelta(days=1),
                result_purged_at=None,
            )
        )
        session.add(
            ProviderCallRecord(
                run_id="run_ai_resources_text_recent",
                provider_id="openai",
                model_id="gpt-5.5",
                instance_id="openai-global-gpt-5-5",
                region="global",
                latency_ms=1234,
                tokens_in=12,
                tokens_out=34,
                cost=0.0042,
                retry_count=0,
                fallback_used=False,
                error_code=None,
                created_at=now,
            )
        )
        session.add(
            ProviderCallRecord(
                run_id="run_ai_resources_text_recent",
                provider_id="openai",
                model_id="gpt-5.5",
                instance_id="openai-global-gpt-5-5",
                region="global",
                latency_ms=25_000,
                tokens_in=10,
                tokens_out=0,
                cost=0.0,
                retry_count=1,
                fallback_used=True,
                error_code="provider.timeout",
                created_at=now - timedelta(days=2),
            )
        )
        session.commit()

    response = client.get(
        "/internal/service/admin/ai-resources",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    evidence = data["recent_runtime_evidence"]["profiles"][TEXT_AI_PROFILE_ID]
    assert evidence["run_id"] == "run_ai_resources_text_recent"
    assert evidence["status"] == "succeeded"
    assert evidence["provider_id"] == "openai"
    usage = {item["feature_id"]: item for item in data["feature_model_usage"]}
    assert usage["content_support"]["last_run"]["run_id"] == "run_ai_resources_text_recent"
    assert usage["content_support"]["last_provider_call"]["latency_ms"] == 1234
    assert usage["content_support"]["last_provider_call"]["cost"] == 0.0042
    assert usage["content_support"]["evidence"]["content_exposed"] is False
    assert usage["content_support"]["boundary"]["direct_wordpress_write"] is False
    health_rows = {
        (item["provider_id"], item["model_id"]): item
        for item in data["provider_model_health"]["rows"]
    }
    health = health_rows[("openai", "gpt-5.5")]
    assert health["status"] == "healthy"
    assert health["call_count"] == 1
    assert health["success_count"] == 1
    assert health["error_count"] == 0
    assert health["success_rate"] == 1.0
    assert health["avg_latency_ms"] == 1234
    assert health["p95_latency_ms"] == 1234
    assert health["tokens_in"] == 12
    assert health["tokens_out"] == 34
    assert health["cost"] == 0.0042
    assert health["evidence"]["content_exposed"] is False
    assert health["boundary"]["direct_wordpress_write"] is False
    windows = {item["window_id"]: item for item in data["provider_model_health"]["windows"]}
    assert {"last_24h", "last_7d"}.issubset(windows)
    assert windows["last_24h"]["rows"][0]["status"] == "healthy"
    assert windows["last_24h"]["alert_summary"]["alert_count"] == 0
    seven_day_rows = {
        (item["provider_id"], item["model_id"]): item
        for item in windows["last_7d"]["rows"]
    }
    assert seven_day_rows[("openai", "gpt-5.5")]["status"] == "degraded"
    assert windows["last_7d"]["alert_summary"]["alert_count"] >= 2
    assert {
        alert["code"] for alert in windows["last_7d"]["alert_summary"]["alerts"]
    }.issuperset({"provider_model.degraded", "provider_model.fallback_used"})
    assert data["provider_model_health"]["alert_summary"]["boundary"][
        "automatic_routing_change"
    ] is False
    serialized = json.dumps(data)
    assert "sensitive draft body" not in serialized
    assert "generated text should not appear" not in serialized


def test_admin_audio_workbench_creates_narration_job_and_exposes_result(
    tmp_path: Path,
) -> None:
    provider = MiniMaxProviderAdapter(
        allow_sample_catalog=True,
        allow_sample_execution=True,
    )
    database_url, client = _build_client(
        tmp_path,
        providers={"minimax": provider},
        settings_overrides={
            "minimax_provider_enabled": True,
            "minimax_api_key": "minimax-test-secret",
        },
    )
    _seed_minimax_audio_model_allowlist(database_url)
    seed_site_auth(
        database_url,
        site_id="site_audio_admin",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )
    response = client.post(
        "/internal/service/admin/audio-jobs",
        headers=build_internal_headers(idempotency_key="audio-workbench-narration"),
        json={
            "site_id": "site_audio_admin",
            "intent": "article_narration",
            "title": "Audio test",
            "body": "这是一段文章正文，用于生成旁白音频。",
            "format": "mp3",
            "preview_instance_id": "minimax-global-speech-28-turbo",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "queued"
    assert data["instance_id"] == "minimax-global-speech-28-turbo"
    assert data["script"]["source"] == "full_article"
    assert data["boundary"]["direct_wordpress_write"] is False

    status_response = client.get(
        f"/internal/service/admin/audio-jobs/{data['run_id']}",
        headers=build_internal_headers(),
    )

    assert status_response.status_code == 200, status_response.text
    status_data = status_response.json()["data"]
    assert status_data["status"] == "succeeded"
    assert status_data["result_ready"] is True
    assert status_data["result"]["artifact_type"] == "audio_generation_candidates"
    assert status_data["result"]["direct_wordpress_write"] is False
    assert status_data["result"]["audios"][0]["mime_type"] == "audio/mpeg"

    dispose_engine(database_url)


def test_admin_audio_workbench_uses_saved_minimax_execution_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, client = _build_client(tmp_path)
    CatalogService(
        database_url,
        providers={"minimax": MiniMaxProviderAdapter(allow_sample_catalog=True)},
    ).refresh_catalog()
    services = client.app.state.services
    ProviderConnectionAdminService(database_url, services.settings).save_connection(
        {
            "connection_id": "minimax",
            "provider_id": "minimax",
            "provider_type": "minimax",
            "kind": "minimax",
            "display_name": "MiniMax",
            "enabled": True,
            "base_url": "https://api.minimaxi.com",
            "capability_ids": ["audio_generation"],
            "runtime_profile_ids": [
                AUDIO_NARRATION_PROFILE_ID,
                WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID,
            ],
            "config": {"model_ids": [AUDIO_NARRATION_MODEL_ID]},
            "credential": "saved-minimax-secret",
        }
    )
    _seed_minimax_audio_model_allowlist(database_url)
    seed_site_auth(
        database_url,
        site_id="site_audio_admin",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    def fake_execute_http(
        self: MiniMaxProviderAdapter,
        request: ProviderExecutionRequest,
    ) -> ProviderExecutionResult:
        return self._execute_sample(request)

    monkeypatch.setattr(MiniMaxProviderAdapter, "_execute_http", fake_execute_http)

    response = client.post(
        "/internal/service/admin/audio-jobs",
        headers=build_internal_headers(
            idempotency_key="audio-workbench-saved-minimax-connection"
        ),
        json={
            "site_id": "site_audio_admin",
            "intent": "article_narration",
            "title": "Audio test",
            "body": "这是一段文章正文，用于验证已保存的 MiniMax 凭据连接会进入运行时。",
            "format": "mp3",
            "preview_instance_id": "minimax-global-speech-28-turbo",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "queued"
    assert data["provider_id"] == "minimax"
    assert data["instance_id"] == "minimax-global-speech-28-turbo"

    status_response = client.get(
        f"/internal/service/admin/audio-jobs/{data['run_id']}",
        headers=build_internal_headers(),
    )
    assert status_response.status_code == 200, status_response.text
    status_data = status_response.json()["data"]
    assert status_data["status"] == "succeeded"
    assert status_data["error_code"] in ("", None)

    dispose_engine(database_url)


def test_admin_audio_workbench_rejects_minimax_route_without_execution_connection(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    CatalogService(
        database_url,
        providers={"minimax": MiniMaxProviderAdapter(allow_sample_catalog=True)},
    ).refresh_catalog()
    _seed_minimax_audio_model_allowlist(database_url)
    seed_site_auth(
        database_url,
        site_id="site_audio_admin",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    response = client.post(
        "/internal/service/admin/audio-jobs",
        headers=build_internal_headers(
            idempotency_key="audio-workbench-minimax-not-executable"
        ),
        json={
            "site_id": "site_audio_admin",
            "intent": "article_narration",
            "title": "Audio test",
            "body": "这是一段文章正文，用于验证不可执行连接不会进入试听候选。",
            "format": "mp3",
            "preview_instance_id": "minimax-global-speech-28-turbo",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "audio_workbench.preview_route_unavailable"

    dispose_engine(database_url)


def test_admin_audio_workbench_without_site_uses_active_preview_site(
    tmp_path: Path,
) -> None:
    provider = MiniMaxProviderAdapter(
        allow_sample_catalog=True,
        allow_sample_execution=True,
    )
    database_url, client = _build_client(
        tmp_path,
        providers={"minimax": provider},
        settings_overrides={
            "minimax_provider_enabled": True,
            "minimax_api_key": "minimax-test-secret",
        },
    )
    _seed_minimax_audio_model_allowlist(database_url)
    seed_site_auth(
        database_url,
        site_id="site_smoke",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
        site_status=SITE_STATUS_ARCHIVED,
    )
    seed_site_auth(
        database_url,
        site_id="site_audio_admin",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    response = client.post(
        "/internal/service/admin/audio-jobs",
        headers=build_internal_headers(idempotency_key="audio-workbench-default-site"),
        json={
            "intent": "article_narration",
            "title": "Audio test",
            "body": "这是一段文章正文，用于验证管理员试听自动选择可用站点。",
            "format": "mp3",
            "preview_instance_id": "minimax-global-speech-28-turbo",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["site_id"] == "site_audio_admin"
    assert data["status"] == "queued"

    dispose_engine(database_url)


def test_admin_audio_workbench_without_active_site_returns_friendly_error(
    tmp_path: Path,
) -> None:
    provider = MiniMaxProviderAdapter(
        allow_sample_catalog=True,
        allow_sample_execution=True,
    )
    database_url, client = _build_client(
        tmp_path,
        providers={"minimax": provider},
        settings_overrides={
            "minimax_provider_enabled": True,
            "minimax_api_key": "minimax-test-secret",
        },
    )
    seed_site_auth(
        database_url,
        site_id="site_smoke",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
        site_status=SITE_STATUS_ARCHIVED,
    )

    response = client.post(
        "/internal/service/admin/audio-jobs",
        headers=build_internal_headers(idempotency_key="audio-workbench-no-active-site"),
        json={
            "intent": "article_narration",
            "title": "Audio test",
            "body": "这是一段文章正文，用于验证没有可用站点时的错误提示。",
            "format": "mp3",
            "preview_instance_id": "minimax-global-speech-28-turbo",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "audio_workbench.preview_site_unavailable"
    assert payload["data"]["site_status"] == "none_active"
    assert payload["data"]["action"] == "connect_or_activate_site"

    dispose_engine(database_url)


def test_admin_audio_workbench_rejects_unknown_preview_instance(
    tmp_path: Path,
) -> None:
    provider = MiniMaxProviderAdapter(
        allow_sample_catalog=True,
        allow_sample_execution=True,
    )
    database_url, client = _build_client(
        tmp_path,
        providers={"minimax": provider},
        settings_overrides={
            "minimax_provider_enabled": True,
            "minimax_api_key": "minimax-test-secret",
        },
    )
    _seed_minimax_audio_model_allowlist(database_url)
    seed_site_auth(
        database_url,
        site_id="site_audio_admin",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    response = client.post(
        "/internal/service/admin/audio-jobs",
        headers=build_internal_headers(idempotency_key="audio-workbench-preview-invalid"),
        json={
            "site_id": "site_audio_admin",
            "intent": "article_narration",
            "title": "Audio test",
            "body": "这是一段文章正文，用于生成旁白音频。",
            "format": "mp3",
            "preview_instance_id": "not-an-audio-candidate",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "audio_workbench.preview_instance_invalid"

    dispose_engine(database_url)


def test_admin_audio_workbench_recent_runs_are_lightweight_runtime_evidence(
    tmp_path: Path,
) -> None:
    provider = MiniMaxProviderAdapter(
        allow_sample_catalog=True,
        allow_sample_execution=True,
    )
    database_url, client = _build_client(
        tmp_path,
        providers={"minimax": provider},
        settings_overrides={
            "minimax_provider_enabled": True,
            "minimax_api_key": "minimax-test-secret",
        },
    )
    _seed_minimax_audio_model_allowlist(database_url)
    seed_site_auth(
        database_url,
        site_id="site_audio_admin",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    create_response = client.post(
        "/internal/service/admin/audio-jobs",
        headers=build_internal_headers(idempotency_key="audio-workbench-recent-create"),
        json={
            "site_id": "site_audio_admin",
            "intent": "article_narration",
            "title": "Recent audio test",
            "body": "这是一段文章正文，用于验证最近音频任务摘要。",
            "format": "mp3",
        },
    )

    assert create_response.status_code == 200, create_response.text
    run_id = create_response.json()["data"]["run_id"]

    recent_response = client.get(
        "/internal/service/admin/audio-jobs/recent?limit=5",
        headers=build_internal_headers(),
    )

    assert recent_response.status_code == 200, recent_response.text
    data = recent_response.json()["data"]
    assert data["contract_version"] == "admin_audio_workbench_recent_runs.v1"
    assert data["boundary"]["direct_wordpress_write"] is False
    assert data["items"][0]["run_id"] == run_id
    assert data["items"][0]["intent"] in {"article_narration", "audio_generation"}
    assert data["items"][0]["audio_ready"] is True
    assert data["items"][0]["mime_type"] == "audio/mpeg"
    serialized = json.dumps(data, ensure_ascii=False)
    assert "audios" not in serialized
    assert "url" not in serialized
    assert "transcript" not in serialized
    assert "这是一段文章正文" not in serialized

    dispose_engine(database_url)


def test_admin_audio_workbench_builds_summary_script_before_audio_job(
    tmp_path: Path,
) -> None:
    audio_provider = MiniMaxProviderAdapter(
        allow_sample_catalog=True,
        allow_sample_execution=True,
    )
    script_provider = FixedAudioSummaryScriptProvider()
    database_url, client = _build_client(
        tmp_path,
        providers={"minimax": audio_provider, "openai": script_provider},
        settings_overrides={
            "minimax_provider_enabled": True,
            "minimax_api_key": "minimax-test-secret",
        },
    )
    _seed_minimax_audio_model_allowlist(database_url)
    _seed_openai_text_model_allowlist(database_url, model_ids=["gpt-hosted-free-next"])
    seed_site_auth(
        database_url,
        site_id="site_audio_admin",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )
    _bind_audio_summary_script_profile(
        database_url,
        revision="audio-summary-script-test",
    )

    response = client.post(
        "/internal/service/admin/audio-jobs",
        headers=build_internal_headers(idempotency_key="audio-workbench-summary"),
        json={
            "site_id": "site_audio_admin",
            "intent": "article_audio_summary",
            "title": "长文主题",
            "body": "第一段介绍背景。第二段说明关键问题。第三段给出解决方案。第四段补充风险。",
            "format": "mp3",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["script"]["source"] == "audio_summary_script"
    assert data["script"]["intent"] == "audio_summary_script"
    assert data["script"]["generation"]["mode"] == "hosted_ai_content_support"
    assert data["script"]["generation"]["ability_name"] == "npcink-toolbox/ai-content-support"
    assert data["script"]["generation"]["contract_version"] == "hosted_ai_content_support.v1"
    assert data["script"]["generation"]["profile_id"] == (
        WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID
    )
    assert data["script"]["output_json"]["opening"] == "这是一段适合收听的长文摘要。"
    assert "适合收听的长文摘要" in data["script"]["text"]
    assert data["script"]["characters"] <= 4800
    assert len(script_provider.requests) == 1
    assert script_provider.requests[0].input_payload["intent"] == "audio_summary_script"

    status_response = client.get(
        f"/internal/service/admin/audio-jobs/{data['run_id']}",
        headers=build_internal_headers(),
    )

    assert status_response.status_code == 200, status_response.text
    status_data = status_response.json()["data"]
    assert status_data["status"] == "succeeded"
    assert status_data["result"]["audios"][0]["duration_seconds"] > 0

    dispose_engine(database_url)


def test_admin_audio_workbench_retries_transient_summary_script_failure(
    tmp_path: Path,
) -> None:
    audio_provider = MiniMaxProviderAdapter(
        allow_sample_catalog=True,
        allow_sample_execution=True,
    )
    script_provider = FlakyAudioSummaryScriptProvider()
    database_url, client = _build_client(
        tmp_path,
        providers={"minimax": audio_provider, "openai": script_provider},
        settings_overrides={
            "minimax_provider_enabled": True,
            "minimax_api_key": "minimax-test-secret",
        },
    )
    _seed_minimax_audio_model_allowlist(database_url)
    _seed_openai_text_model_allowlist(database_url, model_ids=["gpt-hosted-free-next"])
    seed_site_auth(
        database_url,
        site_id="site_audio_admin",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )
    _bind_audio_summary_script_profile(
        database_url,
        revision="audio-summary-script-retry-test",
    )

    response = client.post(
        "/internal/service/admin/audio-jobs",
        headers=build_internal_headers(idempotency_key="audio-workbench-summary-retry"),
        json={
            "site_id": "site_audio_admin",
            "intent": "article_audio_summary",
            "title": "重试主题",
            "body": "第一段介绍背景。第二段说明关键问题。",
            "format": "mp3",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert len(script_provider.requests) == 2
    assert script_provider.requests[0].input_payload["workbench_retry"]["attempt"] == 1
    assert script_provider.requests[1].input_payload["workbench_retry"]["attempt"] == 2
    assert data["script"]["generation"]["attempts"] == 2
    assert data["script"]["generation"]["retry_attempted"] is True
    assert "重试后生成的长文音频摘要" in data["script"]["text"]

    dispose_engine(database_url)


def test_admin_audio_workbench_returns_friendly_empty_summary_script_error(
    tmp_path: Path,
) -> None:
    audio_provider = MiniMaxProviderAdapter(
        allow_sample_catalog=True,
        allow_sample_execution=True,
    )
    script_provider = EmptyAudioSummaryScriptProvider()
    database_url, client = _build_client(
        tmp_path,
        providers={"minimax": audio_provider, "openai": script_provider},
        settings_overrides={
            "minimax_provider_enabled": True,
            "minimax_api_key": "minimax-test-secret",
        },
    )
    _seed_minimax_audio_model_allowlist(database_url)
    _seed_openai_text_model_allowlist(database_url, model_ids=["gpt-hosted-free-next"])
    seed_site_auth(
        database_url,
        site_id="site_audio_admin",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )
    _bind_audio_summary_script_profile(
        database_url,
        revision="audio-summary-script-empty-test",
    )

    response = client.post(
        "/internal/service/admin/audio-jobs",
        headers=build_internal_headers(idempotency_key="audio-workbench-empty-summary"),
        json={
            "site_id": "site_audio_admin",
            "intent": "article_audio_summary",
            "title": "空脚本主题",
            "body": "第一段介绍背景。第二段说明关键问题。",
            "format": "mp3",
        },
    )

    assert response.status_code == 400, response.text
    payload = response.json()
    assert payload["error_code"] == "audio_workbench.summary_script_empty"
    assert "returned an empty audio summary script" in payload["message"]
    assert "audio summary script generation returned no usable script" not in payload["message"]
    assert payload["data"]["retryable"] is True
    assert payload["data"]["retry_attempted"] is True
    assert payload["data"]["action"] == "retry_or_use_narration"
    assert payload["data"]["stage"] == "audio_summary_script"
    assert len(script_provider.requests) == 2

    dispose_engine(database_url)


def test_admin_audio_workbench_uses_wordpress_audio_routing_profile(
    tmp_path: Path,
) -> None:
    provider = MiniMaxProviderAdapter(
        allow_sample_catalog=True,
        allow_sample_execution=True,
    )
    database_url, client = _build_client(
        tmp_path,
        providers={"minimax": provider},
        settings_overrides={
            "minimax_provider_enabled": True,
            "minimax_api_key": "minimax-test-secret",
        },
    )
    _seed_minimax_audio_model_allowlist(database_url)
    seed_site_auth(
        database_url,
        site_id="site_audio_admin",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    response = client.post(
        "/internal/service/admin/audio-jobs",
        headers=build_internal_headers(idempotency_key="audio-workbench-quality-profile"),
        json={
            "site_id": "site_audio_admin",
            "intent": "article_narration",
            "title": "Audio quality test",
            "body": "这是一段文章正文，用于验证音频模型路由。",
            "format": "mp3",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["profile_id"] == WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID
    assert data["script"]["generation"]["audio_profile_id"] == (
        WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID
    )

    dispose_engine(database_url)


def test_image_source_readonly_metrics_summarizes_fast_first_runtime(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    site_id = "site_image_metrics"
    seed_site_auth(
        database_url,
        site_id=site_id,
        scopes=["runtime:execute", "runtime:read"],
    )
    now = datetime.now(UTC)
    with get_session(database_url) as session:
        subscription = session.scalar(
            select(AccountSubscription)
            .where(AccountSubscription.account_id == f"acct_{site_id}")
            .order_by(AccountSubscription.created_at.desc())
        )
        assert subscription is not None

        def add_image_source_run(
            *,
            run_id: str,
            latency_mode: str,
            status: str = "succeeded",
            provider_error: str = "",
        ) -> None:
            deferred = latency_mode == "fast_first"
            session.add(
                RunRecord(
                    run_id=run_id,
                    site_id=site_id,
                    account_id=subscription.account_id,
                    subscription_id=subscription.subscription_id,
                    plan_version_id=subscription.plan_version_id,
                    ability_name="npcink-toolbox/search-image-source",
                    ability_family="knowledge",
                    skill_id="",
                    workflow_id="",
                    contract_version="image_source_cloud_request.v1",
                    channel="toolbox",
                    execution_kind="image_source",
                    execution_tier="cloud",
                    execution_pattern="step_offload",
                    data_classification="public_reference_media",
                    profile_id="image-source.managed",
                    canonical_run_id=None,
                    status=status,
                    idempotency_key=f"idem-{run_id}",
                    request_fingerprint=f"fingerprint-{run_id}",
                    trace_id=f"trace-{run_id}",
                    cancel_requested_at=None,
                    canceled_at=None,
                    input_json={
                        "latency_mode": latency_mode,
                        "enhancement_mode": "deferred" if deferred else "complete",
                        "query": "sensitive operator query should not appear",
                        "visual_context": {"latency_mode": latency_mode},
                    },
                    execution_input_ciphertext=None,
                    policy_json={},
                    result_ref="inline",
                    result_json={
                        "resolved_provider": "unsplash",
                        "query_chars": 42,
                        "active_sources": [{"provider": "unsplash", "count": 2}],
                        "visual_brief": {
                            "site_context_status": "deferred" if deferred else "ready",
                            "llm_prompt_planner_status": "deferred" if deferred else "ready",
                            "source_context": {"latency_mode": latency_mode},
                        },
                    },
                    error_code=provider_error or None,
                    error_message=None,
                    callback_status="not_requested",
                    callback_attempt_count=0,
                    callback_last_attempt_at=None,
                    callback_delivered_at=None,
                    callback_next_attempt_at=None,
                    callback_last_error_code=None,
                    callback_last_error_message=None,
                    selected_provider_id="unsplash",
                    selected_model_id="image-source-search",
                    selected_instance_id="cloud-managed",
                    fallback_used=False,
                    started_at=now - timedelta(minutes=5),
                    processing_started_at=now - timedelta(minutes=5),
                    finished_at=now - timedelta(minutes=4),
                    retention_expires_at=now + timedelta(days=1),
                    result_purged_at=None,
                )
            )
            session.flush()
            session.add(
                ProviderCallRecord(
                    run_id=run_id,
                    provider_id="unsplash",
                    model_id="image-source-search",
                    instance_id="cloud-managed",
                    region="unspecified",
                    latency_ms=80 if not provider_error else 120,
                    tokens_in=0,
                    tokens_out=0,
                    cost=0.001,
                    retry_count=0,
                    fallback_used=False,
                    error_code=provider_error or None,
                    created_at=now - timedelta(minutes=4),
                )
            )

        add_image_source_run(run_id="run-image-fast", latency_mode="fast_first")
        add_image_source_run(run_id="run-image-complete", latency_mode="complete")
        add_image_source_run(
            run_id="run-image-error",
            latency_mode="fast_first",
            status="failed",
            provider_error="provider.timeout",
        )
        session.commit()

    unauthorized = client.get("/internal/service/admin/image-source-metrics")
    assert unauthorized.status_code == 401

    response = client.get(
        f"/internal/service/admin/image-source-metrics?site_id={site_id}&window_hours=24",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["contract_version"] == "image-source-readonly-metrics.v1"
    assert data["filters"]["site_id"] == site_id
    assert data["totals"]["runs"] == 3
    assert data["totals"]["fast_first_runs"] == 2
    assert data["totals"]["complete_runs"] == 1
    assert data["totals"]["deferred_enrichment_runs"] == 2
    assert data["totals"]["provider_calls"] == 3
    assert data["totals"]["provider_errors"] == 1
    assert data["rates"]["fast_first_rate"] == 0.6667
    assert data["rates"]["provider_error_rate"] == 0.3333
    assert data["providers"][0]["provider_id"] == "unsplash"
    assert data["providers"][0]["calls"] == 3
    assert data["providers"][0]["errors"] == 1
    assert data["boundary"]["direct_wordpress_write"] is False
    assert data["boundary"]["contains_prompt_or_result_payloads"] is False
    payload_text = json.dumps(data, ensure_ascii=False)
    assert "sensitive operator query should not appear" not in payload_text


def test_runtime_telemetry_diagnostics_summarizes_runtime_families(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    site_id = "site_model_gov"
    seed_site_auth(
        database_url,
        site_id=site_id,
        scopes=["runtime:execute", "runtime:read"],
    )
    now = datetime.now(UTC)
    with get_session(database_url) as session:
        subscription = session.scalar(
            select(AccountSubscription)
            .where(AccountSubscription.account_id == f"acct_{site_id}")
            .order_by(AccountSubscription.created_at.desc())
        )
        assert subscription is not None

        def add_run(
            *,
            run_id: str,
            ability_family: str,
            execution_kind: str,
            profile_id: str,
            provider_id: str,
            model_id: str,
            instance_id: str,
        ) -> None:
            session.add(
                RunRecord(
                    run_id=run_id,
                    site_id=site_id,
                    account_id=subscription.account_id,
                    subscription_id=subscription.subscription_id,
                    plan_version_id=subscription.plan_version_id,
                    ability_name=f"npcink-cloud/{execution_kind}",
                    ability_family=ability_family,
                    skill_id="",
                    workflow_id="",
                    contract_version="test.v1",
                    channel="openapi",
                    execution_kind=execution_kind,
                    execution_tier="cloud",
                    execution_pattern="inline",
                    data_classification=(
                        "public_site_content" if ability_family == "knowledge" else "internal"
                    ),
                    profile_id=profile_id,
                    canonical_run_id=None,
                    status="succeeded",
                    idempotency_key=f"idem-{run_id}",
                    request_fingerprint=f"fingerprint-{run_id}",
                    trace_id=f"trace-{run_id}",
                    cancel_requested_at=None,
                    canceled_at=None,
                    input_json={},
                    execution_input_ciphertext=None,
                    policy_json={},
                    result_ref="inline",
                    result_json={"status": "ready"},
                    error_code=None,
                    error_message=None,
                    callback_status="not_requested",
                    callback_attempt_count=0,
                    callback_last_attempt_at=None,
                    callback_delivered_at=None,
                    callback_next_attempt_at=None,
                    callback_last_error_code=None,
                    callback_last_error_message=None,
                    selected_provider_id=provider_id,
                    selected_model_id=model_id,
                    selected_instance_id=instance_id,
                    fallback_used=False,
                    started_at=now - timedelta(minutes=5),
                    processing_started_at=now - timedelta(minutes=5),
                    finished_at=now - timedelta(minutes=4),
                    retention_expires_at=now + timedelta(days=1),
                    result_purged_at=None,
                )
            )

        add_run(
            run_id="run-model-gov-text",
            ability_family="text",
            execution_kind="text",
            profile_id="text.free-gpt55",
            provider_id="openai-global-gpt-5-5",
            model_id="gpt-5.5",
            instance_id="openai-global-gpt-5-5-text",
        )
        add_run(
            run_id="run-model-gov-knowledge",
            ability_family="knowledge",
            execution_kind="embedding",
            profile_id="site-knowledge.managed",
            provider_id="tei",
            model_id="tei/BAAI/bge-m3",
            instance_id="tei-site-knowledge-embedding",
        )
        add_run(
            run_id="run-model-gov-vision",
            ability_family="vision",
            execution_kind="media_derivative",
            profile_id="media_derivative.worker",
            provider_id="media_derivative",
            model_id="pillow",
            instance_id="cloud-worker",
        )
        session.flush()
        session.add_all(
            [
                ProviderCallRecord(
                    run_id="run-model-gov-text",
                    provider_id="openai-global-gpt-5-5",
                    model_id="gpt-5.5",
                    instance_id="openai-global-gpt-5-5-text",
                    region="global",
                    latency_ms=180,
                    tokens_in=20,
                    tokens_out=40,
                    cost=0.0,
                    retry_count=0,
                    fallback_used=False,
                    error_code=None,
                    created_at=now - timedelta(minutes=4),
                ),
                ProviderCallRecord(
                    run_id="run-model-gov-knowledge",
                    provider_id="tei",
                    model_id="tei/BAAI/bge-m3",
                    instance_id="tei-site-knowledge-embedding",
                    region="unspecified",
                    latency_ms=45,
                    tokens_in=5,
                    tokens_out=0,
                    cost=0.0,
                    retry_count=0,
                    fallback_used=False,
                    error_code=None,
                    created_at=now - timedelta(minutes=4),
                ),
            ]
        )
        for run_id, ability_family, execution_kind, meter_key, quantity in [
            ("run-model-gov-text", "text", "text", "runs", 1),
            ("run-model-gov-text", "text", "text", "tokens_total", 60),
            ("run-model-gov-knowledge", "knowledge", "embedding", "runs", 1),
            ("run-model-gov-knowledge", "knowledge", "embedding", "tokens_total", 5),
            ("run-model-gov-vision", "vision", "media_derivative", "runs", 1),
        ]:
            session.add(
                UsageMeterEvent(
                    account_id=subscription.account_id,
                    site_id=site_id,
                    subscription_id=subscription.subscription_id,
                    plan_version_id=subscription.plan_version_id,
                    run_id=run_id,
                    provider_call_id=None,
                    event_kind="meter",
                    meter_key=meter_key,
                    quantity=quantity,
                    ability_family=ability_family,
                    channel="openapi",
                    execution_kind=execution_kind,
                    execution_tier="cloud",
                    data_classification=(
                        "public_site_content" if ability_family == "knowledge" else "internal"
                    ),
                    currency="USD",
                    dedupe_key=f"model-gov-{run_id}-{meter_key}",
                    payload_json={},
                    created_at=now - timedelta(minutes=4),
                )
            )
        session.commit()

    unauthenticated = client.get("/internal/service/runtime/diagnostics/runtime-telemetry")
    assert unauthenticated.status_code == 401

    response = client.get(
        "/internal/service/runtime/diagnostics/runtime-telemetry"
        f"?site_id={site_id}&recent_minutes=60&limit=10",
        headers=build_internal_headers(),
    )
    admin_alias_response = client.get(
        "/internal/service/admin/runtime-telemetry"
        f"?site_id={site_id}&recent_minutes=10080&limit=10",
        headers=build_internal_headers(),
    )
    assert response.status_code == 200
    assert admin_alias_response.status_code == 200
    legacy_response = client.get(
        "/internal/service/runtime/diagnostics/hosted-model-governance"
        f"?site_id={site_id}&recent_minutes=60&limit=10",
        headers=build_internal_headers(),
    )
    legacy_admin_alias_response = client.get(
        "/internal/service/admin/hosted-model-governance"
        f"?site_id={site_id}&recent_minutes=10080&limit=10",
        headers=build_internal_headers(),
    )
    assert legacy_response.status_code == 404
    assert legacy_admin_alias_response.status_code == 404
    data = response.json()["data"]
    assert admin_alias_response.json()["data"]["totals"]["runs"] == 3
    assert admin_alias_response.json()["data"]["filters"]["recent_minutes"] == 10080
    assert data["totals"]["runs"] == 3
    assert data["totals"]["provider_calls"] == 2
    assert data["boundary"]["direct_wordpress_write"] is False
    assert data["boundary"]["contains_prompt_or_result_payloads"] is False
    capability_by_id = {item["group_id"]: item for item in data["capability_groups"]}
    assert capability_by_id["text"]["tokens_total"] == 60
    assert capability_by_id["knowledge"]["tokens_total"] == 5
    assert capability_by_id["knowledge"]["provider_calls"] == 1
    assert "site-knowledge.managed" in capability_by_id["knowledge"]["profile_ids"]
    assert capability_by_id["vision"]["provider_calls"] == 0
    assert data["governance_gaps"]["unmetered_capabilities"] == []
    assert data["alert_summary"]["status"] == "warning"
    assert any(
        alert["code"] == "hosted_model.provider_call_gap"
        and alert["count"] == 1
        and "vision" in alert["capabilities"]
        for alert in data["alert_summary"]["alerts"]
    )
    assert data["alert_summary"]["boundary"]["direct_wordpress_write"] is False


def test_internal_ai_advisor_routes_are_internal_and_evidence_backed(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_advisor",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
    )
    now = datetime.now(UTC)
    with get_session(database_url) as session:
        subscription = session.scalar(
            select(AccountSubscription).where(AccountSubscription.account_id == "acct_site_advisor")
        )
        assert subscription is not None
        subscription.status = SUBSCRIPTION_STATUS_PAST_DUE
        session.add(
            RuntimeGuardEvent(
                auth_surface="public",
                scope_kind="site",
                scope_id="site_advisor",
                site_id="site_advisor",
                key_id="key_default",
                client_ref="127.0.0.1",
                event_code="auth.rate_limit_exceeded",
                status_code=429,
                method="POST",
                path="/v1/runtime/execute",
                trace_id="advisor-runtime-trace",
                payload_json={"reason": "test"},
                created_at=now,
            )
        )
        session.add(
            RunRecord(
                run_id="run_advisor",
                site_id="site_advisor",
                account_id="acct_site_advisor",
                subscription_id=subscription.subscription_id,
                plan_version_id=subscription.plan_version_id,
                ability_name="advisor-test",
                ability_family="text",
                skill_id=None,
                workflow_id=None,
                contract_version="test",
                channel="api",
                execution_kind="text",
                execution_tier="cloud",
                execution_pattern="step_offload",
                data_classification="internal",
                profile_id="text.balanced",
                canonical_run_id=None,
                status="succeeded",
                idempotency_key="advisor-run",
                request_fingerprint="advisor-fingerprint",
                trace_id="advisor-routing-trace",
                cancel_requested_at=None,
                canceled_at=None,
                input_json={},
                execution_input_ciphertext=None,
                policy_json={},
                result_ref="inline",
                result_json={"ok": True},
                error_code=None,
                error_message=None,
                callback_status="not_requested",
                callback_attempt_count=0,
                callback_last_attempt_at=None,
                callback_delivered_at=None,
                callback_next_attempt_at=None,
                callback_last_error_code=None,
                callback_last_error_message=None,
                selected_provider_id="openai",
                selected_model_id="gpt-4o-mini",
                selected_instance_id="openai-us-east-text-balanced",
                fallback_used=False,
                started_at=now,
                processing_started_at=now,
                finished_at=now,
                retention_expires_at=now + timedelta(days=1),
                result_purged_at=None,
            )
        )
        session.flush()
        session.add(
            ProviderCallRecord(
                run_id="run_advisor",
                provider_id="openai",
                model_id="gpt-4o-mini",
                instance_id="openai-us-east-text-balanced",
                region="us-east",
                latency_ms=250,
                tokens_in=10,
                tokens_out=20,
                cost=0.001,
                retry_count=0,
                fallback_used=False,
                error_code=None,
                created_at=now,
            )
        )
        session.commit()

    unauthenticated = client.get("/internal/service/advisor/runtime")
    runtime_response = client.get(
        "/internal/service/advisor/runtime?site_id=site_advisor&recent_minutes=60",
        headers=build_internal_headers(),
    )
    commercial_response = client.get(
        "/internal/service/advisor/commercial",
        headers=build_internal_headers(),
    )
    routing_response = client.get(
        "/internal/service/advisor/routing?site_id=site_advisor",
        headers=build_internal_headers(),
    )
    operations_response = client.get(
        "/internal/service/advisor/operations?site_id=site_advisor&range=24h",
        headers=build_internal_headers(),
    )
    ops_summary_response = client.get(
        "/internal/service/advisor/ops-summary?scope=runtime&site_id=site_advisor",
        headers=build_internal_headers(),
    )
    ops_summary_preview_response = client.get(
        "/internal/service/advisor/ops-summary-preview?scope=runtime&site_id=site_advisor",
        headers=build_internal_headers(),
    )
    ops_summary_value_response = client.get(
        "/internal/service/advisor/ops-summary-value?scope=runtime&site_id=site_advisor",
        headers=build_internal_headers(),
    )

    assert unauthenticated.status_code == 401
    assert runtime_response.status_code == 200
    runtime_payload = runtime_response.json()["data"]
    assert runtime_payload["advisor_version"] == "internal-ai-advisor-v1"
    assert runtime_payload["scope"] == "runtime_operations"
    assert runtime_payload["agent_handoff"]["agent_id"] == "internal_ops_advisor_agent"
    assert runtime_payload["agent_handoff"]["handoff_type"] == "operator_recommendation"
    assert runtime_payload["agent_handoff"]["requires_operator_review"] is True
    assert runtime_payload["agent_handoff"]["direct_wordpress_write"] is False
    assert runtime_payload["agent_handoff"]["execution_pattern"] == "inline"
    assert (
        "automatic_commercial_state_mutation"
        in runtime_payload["agent_handoff"]["forbidden_actions"]
    )
    assert runtime_payload["status"] == "attention"
    assert runtime_payload["evidence"][0]["ref"] == (
        "/internal/service/runtime/diagnostics/summary"
    )
    assert {item["action"] for item in runtime_payload["recommended_actions"]} >= {
        "inspect_commercial_entitlement_and_runtime_guard"
    }
    assert any(
        signal["code"] == "runtime.guard_events" and signal["recent_rate_limit_exceeded"] == 1
        for signal in runtime_payload["signals"]
    )

    assert commercial_response.status_code == 200
    commercial_payload = commercial_response.json()["data"]
    assert commercial_payload["scope"] == "commercial_operations"
    assert commercial_payload["status"] == "attention"
    assert any(
        signal["code"] == "commercial.subscription_attention"
        for signal in commercial_payload["signals"]
    )
    assert commercial_payload["recommended_actions"][0]["requires_operator"] is True

    assert routing_response.status_code == 200
    routing_payload = routing_response.json()["data"]
    assert routing_payload["scope"] == "routing_operations"
    assert routing_payload["status"] == "ready"
    assert "text.balanced" in routing_payload["signals"][0]["recommended_profile_ids"]
    assert routing_payload["evidence"][0]["kind"] == "router_recommendation_summary"

    assert operations_response.status_code == 200
    operations_payload = operations_response.json()["data"]
    assert operations_payload["scope"] == "operations_analysis"
    assert operations_payload["agent_handoff"]["agent_role"] == "operations_analysis"
    assert operations_payload["agent_handoff"]["handoff_owner"] == "cloud_internal_operator"
    assert operations_payload["agent_handoff"]["fail_closed_behavior"] == (
        "return_deterministic_advisory_summary"
    )
    assert operations_payload["evidence"][0]["kind"] == "admin_overview"
    assert any(signal["code"] == "ops.runtime_quality" for signal in operations_payload["signals"])
    assert any(signal["code"] == "ops.provider_quality" for signal in operations_payload["signals"])
    assert operations_payload["recommended_actions"][0]["requires_operator"] is True

    assert ops_summary_response.status_code == 200
    ops_summary_payload = ops_summary_response.json()["data"]
    assert ops_summary_payload["summarizer_version"] == "internal-ops-summarizer-v1"
    assert ops_summary_payload["generation"]["mode"] == "deterministic_fallback"
    assert ops_summary_payload["source_context"]["advisor"]["agent_handoff"]["agent_id"] == (
        "internal_ops_advisor_agent"
    )
    assert (
        ops_summary_payload["source_context"]["advisor"]["agent_handoff"]["direct_wordpress_write"]
        is False
    )
    assert ops_summary_payload["agent_registry_metadata"]["agent_id"] == (
        "internal_ops_advisor_agent"
    )
    assert (
        ops_summary_payload["agent_registry_metadata"]["agent_role"]
        == (ops_summary_payload["source_context"]["advisor"]["agent_handoff"]["agent_role"])
    )
    assert ops_summary_payload["agent_registry_metadata"]["direct_wordpress_write"] is False
    assert (
        "cloud_workflow_truth"
        in ops_summary_payload["agent_registry_metadata"]["forbidden_actions"]
    )
    assert ops_summary_payload["support_draft"]
    assert "article" not in ops_summary_payload["support_draft"].lower()
    assert "write WordPress" in ops_summary_payload["safety_note"]

    assert ops_summary_preview_response.status_code == 200
    preview_payload = ops_summary_preview_response.json()["data"]
    assert preview_payload["preview_version"] == "internal-ops-summarizer-preview-v1"
    assert preview_payload["baseline"]["generation"]["mode"] == "deterministic_fallback"
    assert preview_payload["ai"]["generation"]["mode"] == "deterministic_fallback"
    assert preview_payload["comparison"]["ai_called"] is False
    assert preview_payload["comparison"]["value_check"] == "pass_provider_id_to_test_llm"
    assert preview_payload["safety"]["wordpress_write_allowed"] is False

    assert ops_summary_value_response.status_code == 200
    value_payload = ops_summary_value_response.json()["data"]
    assert value_payload["value_metrics_version"] == "internal-ops-summary-value-v1"
    assert value_payload["filters"]["scope"] == "runtime_operations"
    assert value_payload["totals"]["analysis_requests"] >= 1
    assert value_payload["totals"]["deterministic_fallbacks"] >= 1
    assert value_payload["value_signal"]["status"] in {
        "not_using_ai",
        "monitor",
        "insufficient_data",
    }

    dispose_engine(database_url)


def test_internal_site_diagnostic_advisor_uses_monitoring_actions(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_diag",
        scopes=["runtime:execute", "runtime:read", "stats:read"],
    )
    now = datetime.now(UTC)
    with get_session(database_url) as session:
        session.add(
            PluginObservabilityEvent(
                dedupe_key="diag-plugin-error-001",
                site_id="site_diag",
                key_id="key_default",
                schema_version="2026-06-01",
                plugin_slug="npcink-ai-client-adapter",
                plugin_version="0.1.0",
                source="local",
                event_kind="adapter.runtime.failed",
                event_id="diag-plugin-error-event-001",
                status="error",
                error_code="wordpress.fatal_error",
                latency_ms=4200,
                ability_id="npcink-abilities-toolkit/create-draft",
                payload_json={"raw": "must stay out of advisor response"},
                captured_at=now - timedelta(minutes=5),
                received_at=now - timedelta(minutes=5),
            )
        )
        session.commit()

    unauthenticated = client.get(
        "/internal/service/advisor/site-diagnostics?site_id=site_diag"
    )
    response = client.get(
        "/internal/service/advisor/site-diagnostics?site_id=site_diag&window_hours=24",
        headers=build_internal_headers(),
    )

    assert unauthenticated.status_code == 401
    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["advisor_version"] == "internal-ai-advisor-v1"
    assert payload["scope"] == "site_diagnostics"
    assert payload["status"] == "attention"
    assert payload["severity"] in {"warning", "error"}
    assert payload["agent_handoff"]["requires_operator_review"] is True
    assert payload["agent_handoff"]["direct_wordpress_write"] is False
    assert payload["safety"] == {
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
        "operator_review_required": True,
        "automatic_repair_allowed": False,
        "raw_payload_exposed": False,
    }
    assert payload["diagnostic_items"]
    first_item = payload["diagnostic_items"][0]
    assert first_item["diagnostic_key"]
    assert first_item["source"] == "plugins"
    assert first_item["workflow_status"] == "new"
    assert first_item["status_detail"]["workflow_status"] == "new"
    assert first_item["status_detail"]["status_source"] in {
        "monitoring_signal",
        "operator_state",
    }
    assert first_item["evidence_window"]["hours"] == 24
    assert first_item["last_updated_at"]
    assert first_item["operator_review_required"] is True
    assert first_item["direct_wordpress_write"] is False
    assert first_item["recommended_action_id"] == "inspect_plugin_observability_attention"
    assert payload["diagnostic_workflow"]["new"] >= 1
    assert payload["diagnostic_workflow"]["needs_attention"] >= 1
    assert payload["evidence_window"]["hours"] == 24
    assert any(
        action["action"] == "inspect_plugin_observability_attention"
        and action["requires_operator"] is True
        for action in payload["recommended_actions"]
    )
    serialized = json.dumps(payload)
    assert "must stay out of advisor response" not in serialized
    assert "payload_json" not in serialized

    attention_key = first_item["diagnostic_key"].replace("plugin_attention:", "", 1)
    acknowledge_response = client.post(
        "/internal/service/admin/plugin-observability/attention-state",
        headers=build_internal_headers(idempotency_key="diag-attention-ack-001"),
        json={
            "attention_key": attention_key,
            "attention_code": first_item["code"],
            "action": "acknowledge",
            "site_id": "site_diag",
            "note": "Operator is reviewing the plugin error.",
        },
    )
    follow_up_response = client.get(
        "/internal/service/advisor/site-diagnostics?site_id=site_diag&window_hours=24",
        headers=build_internal_headers(),
    )

    assert acknowledge_response.status_code == 200, acknowledge_response.text
    assert follow_up_response.status_code == 200, follow_up_response.text
    follow_up_item = follow_up_response.json()["data"]["diagnostic_items"][0]
    assert follow_up_item["workflow_status"] == "acknowledged"
    assert follow_up_item["status_detail"]["status_source"] == "operator_state"
    assert follow_up_item["status_detail"]["operator_note"] == (
        "Operator is reviewing the plugin error."
    )

    dispose_engine(database_url)


def test_service_routes_manage_account_site_and_keys(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    account_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_service", "name": "Service Account"},
        headers=build_internal_headers(idempotency_key="svc-account-001"),
    )
    site_response = client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_service",
            "account_id": "acct_service",
            "name": "Service Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="svc-site-001"),
    )
    activate_response = client.post(
        "/internal/service/sites/site_service/activate",
        headers=build_internal_headers(idempotency_key="svc-site-activate-001"),
    )
    issue_key_response = client.post(
        "/internal/service/sites/site_service/keys",
        json={
            "key_id": "key_service_primary",
            "secret": "svc-primary-secret",
            "scopes": ["runtime:execute", "runtime:read", "runtime:resolve"],
            "label": "primary",
        },
        headers=build_internal_headers(idempotency_key="svc-key-issue-001"),
    )
    list_keys_response = client.get(
        "/internal/service/sites/site_service/keys",
        headers=build_internal_headers(),
    )
    rotate_key_response = client.post(
        "/internal/service/sites/site_service/keys/key_service_primary/rotate",
        json={
            "key_id": "key_service_rotated",
            "secret": "svc-rotated-secret",
            "label": "rotated",
        },
        headers=build_internal_headers(idempotency_key="svc-key-rotate-001"),
    )
    expire_at = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    expire_key_response = client.post(
        "/internal/service/sites/site_service/keys/key_service_rotated/expire",
        json={"expires_at": expire_at},
        headers=build_internal_headers(idempotency_key="svc-key-expire-001"),
    )
    revoke_key_response = client.post(
        "/internal/service/sites/site_service/keys/key_service_rotated/revoke",
        headers=build_internal_headers(idempotency_key="svc-key-revoke-001"),
    )
    suspend_response = client.post(
        "/internal/service/sites/site_service/suspend",
        json={"reason": "manual hold"},
        headers=build_internal_headers(idempotency_key="svc-site-suspend-001"),
    )
    audit_response = client.get(
        "/internal/service/audit-events?site_id=site_service&limit=20",
        headers=build_internal_headers(),
    )
    missing_activate_response = client.post(
        "/internal/service/sites/site_missing/activate",
        headers=build_internal_headers(idempotency_key="svc-site-activate-missing-001"),
    )
    error_audit_response = client.get(
        "/internal/service/audit-events?event_kind=site.activate&outcome=error&limit=5",
        headers=build_internal_headers(),
    )

    assert account_response.status_code == 200
    assert "current_subscription" not in account_response.json()["data"]
    assert site_response.status_code == 200
    assert site_response.json()["data"]["status"] == "provisioning"
    assert activate_response.status_code == 200
    assert activate_response.json()["data"]["status"] == "active"
    assert issue_key_response.status_code == 200
    assert issue_key_response.json()["data"]["secret"] == "svc-primary-secret"
    assert list_keys_response.status_code == 200
    assert len(list_keys_response.json()["data"]["items"]) == 1
    assert list_keys_response.json()["data"]["pagination"] == {
        "limit": 20,
        "offset": 0,
        "total": 1,
        "has_more": False,
        "next_offset": None,
    }
    assert list_keys_response.json()["data"]["sort"] == {
        "created_at": "desc",
        "key_id": "desc",
    }
    assert rotate_key_response.status_code == 200
    assert rotate_key_response.json()["data"]["previous"]["status"] == "revoked"
    assert rotate_key_response.json()["data"]["current"]["key_id"] == "key_service_rotated"
    assert expire_key_response.status_code == 200
    assert expire_key_response.json()["data"]["status"] == "expired"
    assert revoke_key_response.status_code == 200
    assert revoke_key_response.json()["data"]["status"] == "revoked"
    assert suspend_response.status_code == 200
    assert suspend_response.json()["data"]["status"] == "suspended"
    assert suspend_response.json()["data"]["suspension_reason"] == "manual hold"
    assert audit_response.status_code == 200
    audit_items = audit_response.json()["data"]["items"]
    assert {item["event_kind"] for item in audit_items} >= {
        "site.provision",
        "site.activate",
        "site_key.issue",
        "site_key.rotate",
        "site_key.expire",
        "site_key.revoke",
        "site.suspend",
    }
    issue_audit = next(item for item in audit_items if item["event_kind"] == "site_key.issue")
    rotate_audit = next(item for item in audit_items if item["event_kind"] == "site_key.rotate")
    assert issue_audit["payload"]["secret"] == "[redacted]"
    assert rotate_audit["payload"]["current"]["secret"] == "[redacted]"
    assert missing_activate_response.status_code == 404
    assert error_audit_response.status_code == 200
    error_items = error_audit_response.json()["data"]["items"]
    assert any(
        item["payload"]["error_code"] == "service.site_not_found"
        and item["payload"]["request"] == {}
        for item in error_items
    )

    dispose_engine(database_url)


def test_service_routes_account_default_free_binding_is_explicit(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    generic_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_ops_only", "name": "Ops Only Account"},
        headers=build_internal_headers(idempotency_key="svc-account-explicit-001"),
    )
    onboarding_response = client.post(
        "/internal/service/accounts",
        json={
            "account_id": "acct_customer_free",
            "name": "Customer Free Account",
            "bind_default_free": True,
        },
        headers=build_internal_headers(idempotency_key="svc-account-explicit-002"),
    )

    assert generic_response.status_code == 200
    assert "current_subscription" not in generic_response.json()["data"]
    assert onboarding_response.status_code == 200
    onboarding_payload = onboarding_response.json()["data"]
    assert onboarding_payload["current_subscription"]["plan_id"] == "free"
    assert onboarding_payload["current_subscription"]["plan_version_id"] == "free_v1"
    assert onboarding_payload["current_subscription"]["package_alias"] == "Free"

    with get_session(database_url) as session:
        generic_subscription = session.scalar(
            select(AccountSubscription).where(AccountSubscription.account_id == "acct_ops_only")
        )
        free_subscription = session.scalar(
            select(AccountSubscription).where(
                AccountSubscription.account_id == "acct_customer_free"
            )
        )
        free_snapshot = session.scalar(
            select(AccountEntitlementSnapshot).where(
                AccountEntitlementSnapshot.account_id == "acct_customer_free",
                AccountEntitlementSnapshot.status == "active",
            )
        )

    assert generic_subscription is None
    assert free_subscription is not None
    assert free_subscription.plan_id == "free"
    assert free_subscription.plan_version_id == "free_v1"
    assert free_snapshot is not None
    assert free_snapshot.plan_version_id == "free_v1"

    dispose_engine(database_url)


def test_service_site_keys_support_limit_offset_and_desc_sort(tmp_path: Path) -> None:
    _, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_keys_page", "name": "Paged Keys Account"},
        headers=build_internal_headers(idempotency_key="svc-page-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_keys_page",
            "account_id": "acct_keys_page",
            "name": "Paged Keys Site",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="svc-page-site-001"),
    )

    for index in range(3):
        client.post(
            "/internal/service/sites/site_keys_page/keys",
            json={
                "key_id": f"key_page_{index}",
                "secret": f"svc-page-secret-{index}",
                "scopes": ["runtime:read"],
                "label": f"page-{index}",
            },
            headers=build_internal_headers(idempotency_key=f"svc-page-key-{index:03d}"),
        )

    response = client.get(
        "/internal/service/sites/site_keys_page/keys?limit=2&offset=0",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert [item["key_id"] for item in payload["items"]] == [
        "key_page_2",
        "key_page_1",
    ]
    assert payload["pagination"] == {
        "limit": 2,
        "offset": 0,
        "total": 3,
        "has_more": True,
        "next_offset": 2,
    }
    assert payload["sort"] == {"created_at": "desc", "key_id": "desc"}


def test_service_routes_bind_subscription_and_rebuild_billing_snapshot(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    _seed_openai_text_model_allowlist(database_url)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_billing", "name": "Billing Account"},
        headers=build_internal_headers(idempotency_key="svc-account-101"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_billing",
            "account_id": "acct_billing",
            "name": "Billing Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="svc-site-101"),
    )
    client.post(
        "/internal/service/sites/site_billing/activate",
        headers=build_internal_headers(idempotency_key="svc-site-activate-101"),
    )
    key_response = client.post(
        "/internal/service/sites/site_billing/keys",
        json={
            "key_id": "key_billing_primary",
            "secret": "billing-secret",
            "scopes": ["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
            "label": "billing-primary",
        },
        headers=build_internal_headers(idempotency_key="svc-key-101"),
    )
    plan_response = client.post(
        "/internal/service/plans",
        json={"plan_id": "plan_pro_topup", "name": "Pro"},
        headers=build_internal_headers(idempotency_key="svc-plan-101"),
    )
    version_response = client.post(
        "/internal/service/plans/plan_pro_topup/versions",
        json={
            "plan_version_id": "plan_pro_topup_v1",
            "version_label": "v1",
            "entitlements": {
                "ability_families": ["workflow"],
                "channels": ["openapi"],
                "execution_kinds": ["text"],
                "execution_tiers": ["cloud"],
                "data_classifications": ["internal"],
            },
            "budgets": {"max_runs_per_period": 10, "max_tokens_per_period": 5000},
            "concurrency": {"max_active_runs": 2},
        },
        headers=build_internal_headers(idempotency_key="svc-plan-version-101"),
    )
    subscription_response = client.post(
        "/internal/service/admin/accounts/acct_billing/subscription",
        json={
            "subscription_id": "sub_pro_topup",
            "account_id": "acct_billing",
            "plan_id": "plan_pro_topup",
            "plan_version_id": "plan_pro_topup_v1",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="svc-subscription-101"),
    )
    topup_response = client.post(
        "/internal/service/subscriptions/sub_pro_topup/topup",
        json={
            "target_period_start_at": subscription_response.json()["data"]["subscription"][
                "current_period_start_at"
            ],
            "target_period_end_at": subscription_response.json()["data"]["subscription"][
                "current_period_end_at"
            ],
            "ai_credits_increment": 10000,
            "runs_increment": 10000,
            "tokens_increment": 2000000,
            "cost_increment": 99,
            "reason": "operator_overage_buffer",
            "note": "Customer needs temporary headroom before tier review.",
        },
        headers=build_internal_headers(idempotency_key="svc-subscription-topup-101"),
    )

    assert key_response.status_code == 200
    assert plan_response.status_code == 200
    assert plan_response.json()["data"]["receipt"]["event_kind"] == "plan.upsert"
    assert plan_response.json()["data"]["receipt"]["audit_filters"]["event_kind"] == "plan.upsert"
    assert plan_response.json()["data"]["receipt"]["audit_filters"]["outcome"] == "succeeded"
    assert version_response.status_code == 200
    assert version_response.json()["data"]["receipt"]["event_kind"] == "plan_version.publish"
    assert (
        version_response.json()["data"]["receipt"]["audit_filters"]["event_kind"]
        == "plan_version.publish"
    )
    assert subscription_response.status_code == 200
    assert subscription_response.json()["data"]["receipt"]["event_kind"] == "subscription.upsert"
    assert (
        subscription_response.json()["data"]["receipt"]["audit_filters"]["account_id"]
        == "acct_billing"
    )
    assert topup_response.status_code == 200
    topup_payload = topup_response.json()["data"]
    assert topup_payload["receipt"]["event_kind"] == "subscription.topup"
    assert topup_payload["topup"]["pack_id"] == ""
    assert topup_payload["topup"]["reason"] == "operator_overage_buffer"
    assert topup_payload["entitlement_snapshot"]["budgets"]["max_ai_credits_per_period"] == 10000.0
    assert topup_payload["entitlement_snapshot"]["budgets"]["max_runs_per_period"] == 10010.0
    assert topup_payload["entitlement_snapshot"]["budgets"]["max_tokens_per_period"] == 2005000.0
    assert topup_payload["entitlement_snapshot"]["budgets"]["max_cost_per_period"] == 99.0
    assert topup_payload["topup_summary"]["current_period_count"] == 1
    assert topup_payload["topup_summary"]["current_period_totals"]["ai_credits"] == 10000.0
    assert topup_payload["topup_summary"]["current_period_totals"]["runs"] == 10000.0
    assert topup_payload["topup_summary"]["current_period_totals"]["tokens"] == 2000000.0
    assert topup_payload["topup_summary"]["current_period_totals"]["cost"] == 99.0
    assert topup_payload["billing_snapshot_refresh"]["status"] == "refreshed"
    assert topup_payload["billing_snapshot_refresh"]["site_count"] == 1
    assert topup_payload["billing_snapshot_refresh"]["snapshots"][0]["site_id"] == "site_billing"
    assert topup_payload["billing_snapshot_status"]["status"] == "fresh"
    assert topup_payload["billing_snapshot_status"]["next_action"] is None

    admin_subscription_response = client.get(
        "/internal/service/admin/subscriptions/sub_pro_topup",
        headers=build_internal_headers(),
    )
    assert admin_subscription_response.status_code == 200
    admin_subscription = admin_subscription_response.json()["data"]
    assert admin_subscription["topup_summary"]["count"] == 1
    assert admin_subscription["topup_summary"]["latest"]["pack_id"] == ""
    assert admin_subscription["topup_summary"]["latest"]["reason"] == "operator_overage_buffer"
    assert admin_subscription["topup_summary"]["current_period_totals"]["ai_credits"] == 10000.0
    assert admin_subscription["topup_summary"]["current_period_totals"]["cost"] == 99.0
    assert admin_subscription["budget_headroom"]["base_budget"]["ai_credits"] == 0.0
    assert admin_subscription["budget_headroom"]["base_budget"]["runs"] == 10.0
    assert (
        admin_subscription["budget_headroom"]["current_period_topup_delta"]["ai_credits"]
        == 10000.0
    )
    assert admin_subscription["budget_headroom"]["current_period_topup_delta"]["runs"] == 10000.0
    assert admin_subscription["budget_headroom"]["effective_budget"]["ai_credits"] == 10000.0
    assert admin_subscription["budget_headroom"]["effective_budget"]["runs"] == 10010.0
    assert admin_subscription["billing_snapshot_status"]["status"] == "fresh"
    assert admin_subscription["billing_snapshot_status"]["fresh_site_count"] == 1
    assert admin_subscription["billing_snapshot_status"]["next_action"] is None

    rebuild_subscription_response = client.post(
        "/internal/service/admin/subscriptions/sub_pro_topup/billing-snapshots/rebuild",
        headers=build_internal_headers(idempotency_key="svc-subscription-rebuild-101"),
    )
    assert rebuild_subscription_response.status_code == 200
    rebuild_payload = rebuild_subscription_response.json()["data"]
    assert rebuild_payload["receipt"]["event_kind"] == "subscription.billing_snapshot.rebuild"
    assert rebuild_payload["receipt"]["scope_kind"] == "subscription"
    assert rebuild_payload["receipt"]["scope_id"] == "sub_pro_topup"
    assert (
        rebuild_payload["receipt"]["audit_filters"]["event_kind"]
        == "subscription.billing_snapshot.rebuild"
    )
    assert rebuild_payload["billing_snapshot_refresh"]["status"] == "refreshed"
    assert rebuild_payload["billing_snapshot_refresh"]["site_count"] == 1
    assert rebuild_payload["billing_snapshot_status"]["status"] == "fresh"
    assert rebuild_payload["billing_snapshot_status"]["next_action"] is None

    execute_payload = {
        "site_id": "site_billing",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-service-billing-001",
        "input": {"messages": [{"role": "user", "content": "meter this run"}]},
    }
    body = json.dumps(execute_payload).encode("utf-8")
    execute_response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_billing",
                key_id="key_billing_primary",
                secret="billing-secret",
                idempotency_key="idem-service-billing-001",
                trace_id="traceservicebilling001000000",
                body=body,
            )
        ),
    )
    usage_response = client.get(
        "/internal/service/sites/site_billing/usage-meter?limit=20",
        headers=build_internal_headers(),
    )
    rebuild_response = client.post(
        "/internal/service/sites/site_billing/billing-snapshots/rebuild",
        headers=build_internal_headers(idempotency_key="svc-billing-rebuild-101"),
    )
    list_billing_response = client.get(
        "/internal/service/sites/site_billing/billing-snapshots",
        headers=build_internal_headers(),
    )
    suspend_subscription_response = client.post(
        "/internal/service/admin/accounts/acct_billing/subscription/suspend",
        headers=build_internal_headers(idempotency_key="svc-subscription-suspend-101"),
    )
    cancel_subscription_response = client.post(
        "/internal/service/admin/accounts/acct_billing/subscription/cancel",
        headers=build_internal_headers(idempotency_key="svc-subscription-cancel-101"),
    )
    denied_resolve_response = client.post(
        "/v1/runtime/resolve",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/resolve",
                site_id="site_billing",
                key_id="key_billing_primary",
                secret="billing-secret",
                nonce="svc-billing-deny-nonce-001",
                trace_id="traceservicebillingdeny00100",
                body=body,
            )
        ),
    )
    commercial_decisions_response = client.get(
        "/internal/service/commercial-decisions?site_id=site_billing&limit=10",
        headers=build_internal_headers(),
    )

    assert execute_response.status_code == 200
    assert execute_response.json()["data"]["status"] == "succeeded"
    assert usage_response.status_code == 200
    assert usage_response.json()["data"]["totals"]["runs"] == 1.0
    assert usage_response.json()["data"]["totals"]["provider_calls"] == 1.0
    assert usage_response.json()["data"]["totals"]["tokens_total"] > 0
    assert rebuild_response.status_code == 200
    assert rebuild_response.json()["data"]["totals"]["runs"] == 1.0
    assert (
        rebuild_response.json()["data"]["breakdown"]["ability_families"]["workflow"]["runs"] == 1.0
    )
    assert list_billing_response.status_code == 200
    assert len(list_billing_response.json()["data"]["items"]) == 1
    assert suspend_subscription_response.status_code == 200
    assert suspend_subscription_response.json()["data"]["status"] == "suspended"
    assert (
        suspend_subscription_response.json()["data"]["receipt"]["event_kind"]
        == "subscription.suspend"
    )
    assert (
        suspend_subscription_response.json()["data"]["receipt"]["audit_filters"]["event_kind"]
        == "subscription.suspend"
    )
    assert denied_resolve_response.status_code == 403
    assert denied_resolve_response.json()["error_code"] in {
        "commercial.subscription_inactive",
        "commercial.entitlement_denied",
    }
    assert cancel_subscription_response.status_code == 200
    assert cancel_subscription_response.json()["data"]["status"] == "canceled"
    assert (
        cancel_subscription_response.json()["data"]["receipt"]["event_kind"]
        == "subscription.cancel"
    )
    assert (
        cancel_subscription_response.json()["data"]["receipt"]["audit_filters"]["event_kind"]
        == "subscription.cancel"
    )
    assert commercial_decisions_response.status_code == 200
    decision_items = commercial_decisions_response.json()["data"]["items"]
    assert {item["decision"] for item in decision_items} >= {"allow", "deny"}
    assert {item["request_kind"] for item in decision_items} >= {"execute", "resolve"}
    assert any(item["decision_code"] == "commercial.allowed" for item in decision_items)
    assert any(
        item["decision_code"]
        in {"commercial.subscription_inactive", "commercial.entitlement_denied"}
        for item in decision_items
    )

    dispose_engine(database_url)


def test_service_routes_plan_version_label_conflict_is_readable(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    plan_response = client.post(
        "/internal/service/plans",
        json={"plan_id": "free_conflict", "name": "Free Conflict"},
        headers=build_internal_headers(idempotency_key="svc-plan-conflict-001"),
    )
    first_version_response = client.post(
        "/internal/service/plans/free_conflict/versions",
        json={
            "plan_version_id": "free_conflict_v1",
            "version_label": "v1",
            "budgets": {"max_runs_per_period": 10},
            "concurrency": {"max_active_runs": 1},
        },
        headers=build_internal_headers(idempotency_key="svc-plan-conflict-version-001"),
    )
    conflict_response = client.post(
        "/internal/service/plans/free_conflict/versions",
        json={
            "plan_version_id": "free_conflict_v2",
            "version_label": "v1",
            "budgets": {"max_runs_per_period": 20},
            "concurrency": {"max_active_runs": 2},
        },
        headers=build_internal_headers(idempotency_key="svc-plan-conflict-version-002"),
    )

    assert plan_response.status_code == 200
    assert first_version_response.status_code == 200
    assert conflict_response.status_code == 409
    conflict_payload = conflict_response.json()
    assert conflict_payload["error_code"] == "service.plan_version_label_conflict"
    assert "already has version label 'v1'" in conflict_payload["message"]
    assert "free_conflict_v1" in conflict_payload["message"]

    dispose_engine(database_url)


def test_service_routes_admin_read_facade(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    _seed_openai_text_model_allowlist(database_url)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_admin", "name": "Admin Account"},
        headers=build_internal_headers(idempotency_key="svc-admin-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_primary",
            "account_id": "acct_admin",
            "name": "Admin Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="svc-admin-site-001"),
    )
    client.post(
        "/internal/service/sites/site_primary/activate",
        headers=build_internal_headers(idempotency_key="svc-admin-site-activate-001"),
    )
    client.post(
        "/internal/service/sites/site_primary/user-grants",
        json={"email": "admin@example.com"},
        headers=build_internal_headers(idempotency_key="svc-admin-user-grants-001"),
    )
    client.post(
        "/internal/service/sites/site_primary/keys",
        json={
            "key_id": "key_admin_primary",
            "secret": "admin-secret",
            "scopes": ["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
            "label": "admin-primary",
        },
        headers=build_internal_headers(idempotency_key="svc-admin-key-001"),
    )
    client.post(
        "/internal/service/plans",
        json={"plan_id": "plan_admin", "name": "Admin Plan"},
        headers=build_internal_headers(idempotency_key="svc-admin-plan-001"),
    )
    client.post(
        "/internal/service/plans/plan_admin/versions",
        json={
            "plan_version_id": "plan_admin_v1",
            "version_label": "v1",
            "entitlements": {
                "ability_families": ["workflow"],
                "channels": ["openapi"],
                "execution_kinds": ["text"],
                "execution_tiers": ["cloud"],
                "data_classifications": ["internal"],
            },
            "budgets": {"max_runs_per_period": 25, "max_tokens_per_period": 12000},
            "concurrency": {"max_active_runs": 3},
        },
        headers=build_internal_headers(idempotency_key="svc-admin-version-001"),
    )
    client.post(
        "/internal/service/admin/accounts/acct_admin/subscription",
        json={
            "subscription_id": "sub_admin",
            "account_id": "acct_admin",
            "plan_id": "plan_admin",
            "plan_version_id": "plan_admin_v1",
            "status": "active",
            "current_period_end_at": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
        },
        headers=build_internal_headers(idempotency_key="svc-admin-subscription-001"),
    )

    execute_payload = {
        "site_id": "site_primary",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-admin-facade-001",
        "input": {"messages": [{"role": "user", "content": "exercise admin overview"}]},
    }
    body = json.dumps(execute_payload).encode("utf-8")
    execute_response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_primary",
                key_id="key_admin_primary",
                secret="admin-secret",
                idempotency_key="idem-admin-facade-001",
                trace_id="traceadminfacade001000000",
                body=body,
            )
        ),
    )
    assert execute_response.status_code == 200

    client.post(
        "/internal/service/sites/site_primary/billing-snapshots/rebuild",
        headers=build_internal_headers(idempotency_key="svc-admin-billing-001"),
    )

    overview_response = client.get(
        "/internal/service/admin/overview",
        headers=build_internal_headers(),
    )
    coverage_work_queue_response = client.get(
        "/internal/service/admin/coverage-work-queue",
        headers=build_internal_headers(),
    )
    accounts_response = client.get(
        "/internal/service/admin/accounts",
        headers=build_internal_headers(),
    )
    account_detail_response = client.get(
        "/internal/service/admin/accounts/acct_admin",
        headers=build_internal_headers(),
    )
    sites_response = client.get(
        "/internal/service/admin/sites",
        headers=build_internal_headers(),
    )
    site_detail_response = client.get(
        "/internal/service/admin/sites/site_primary",
        headers=build_internal_headers(),
    )
    subscriptions_response = client.get(
        "/internal/service/admin/subscriptions",
        headers=build_internal_headers(),
    )
    plans_response = client.get(
        "/internal/service/admin/plans",
        headers=build_internal_headers(),
    )
    plan_detail_response = client.get(
        "/internal/service/admin/plans/plan_admin",
        headers=build_internal_headers(),
    )
    subscription_detail_response = client.get(
        "/internal/service/admin/subscriptions/sub_admin",
        headers=build_internal_headers(),
    )
    package_filtered_accounts_response = client.get(
        "/internal/service/admin/accounts?coverage_state=covered&package_kind=tier_package&top_plan_id=plan_admin",
        headers=build_internal_headers(),
    )
    filtered_sites_response = client.get(
        "/internal/service/admin/sites?account_id=acct_admin&subscription_status=active",
        headers=build_internal_headers(),
    )
    filtered_subscriptions_response = client.get(
        "/internal/service/admin/subscriptions?plan_id=plan_admin",
        headers=build_internal_headers(),
    )
    expiring_accounts_response = client.get(
        "/internal/service/admin/accounts",
        params={"expires_before": (datetime.now(UTC) + timedelta(days=30)).isoformat()},
        headers=build_internal_headers(),
    )
    unauthorized_response = client.get("/internal/service/admin/overview")

    assert overview_response.status_code == 200
    overview = overview_response.json()["data"]
    assert overview["counts"]["accounts_total"] == 1
    assert overview["counts"]["principals_active"] == 1
    assert overview["counts"]["sites_active"] == 1
    assert overview["counts"]["site_keys_active"] == 1
    assert overview["recent_usage"]["event_count"] >= 1
    platform_credit = overview["platform_credit_summary"]
    assert platform_credit["previous_period_start_at"]
    assert platform_credit["previous_period_end_at"]
    assert platform_credit["trend"]["current_used"] >= 0
    assert platform_credit["trend"]["previous_used"] >= 0
    assert platform_credit["trend"]["status"] in {"new_activity", "flat", "up", "down"}
    assert isinstance(platform_credit["watch_items"], list)
    assert "runtime_diagnostics" in overview
    assert overview["runtime_telemetry"]["filters"]["recent_minutes"] == 1440
    assert overview["runtime_telemetry"]["alert_summary"]["status"] in {
        "ok",
        "warning",
        "error",
        "inactive",
    }
    assert (
        overview["runtime_telemetry"]["alert_summary"]["boundary"]["direct_wordpress_write"]
        is False
    )
    assert "hosted_model_governance" not in overview
    assert overview["runtime_operator_explanations"]
    assert len(overview["expiring_subscriptions"]["items"]) >= 1
    assert any(
        item["subscription"]["account_id"] == "acct_admin"
        for item in overview["expiring_subscriptions"]["items"]
    )
    assert overview["expiring_subscriptions"]["within_30_days_expires_before"]
    assert overview["attention_subscriptions"] == []

    assert coverage_work_queue_response.status_code == 200
    coverage_queue = coverage_work_queue_response.json()["data"]
    assert coverage_queue["summary"]["total"] == 1
    assert coverage_queue["summary"]["needs_action"] == 1
    coverage_item = coverage_queue["items"][0]
    assert coverage_item["account"]["account_id"] == "acct_admin"
    assert coverage_item["primary_subscription"]["subscription_id"] == "sub_admin"
    assert coverage_item["package"]["display_package_label"] == "Pro"
    assert coverage_item["severity"] == "warning"
    assert coverage_item["reason_code"] == "subscription_expiring_soon"
    assert coverage_item["recommended_action"] == "review_renewal"
    assert coverage_item["action_href"] == "/admin/subscriptions/sub_admin"
    assert coverage_item["evidence"]["site_count"] == 1
    assert coverage_item["evidence"]["active_key_site_count"] == 1
    assert coverage_item["evidence"]["billing_snapshot_status"]["status"] == "fresh"

    assert accounts_response.status_code == 200
    accounts = accounts_response.json()["data"]["items"]
    assert len(accounts) == 1
    assert accounts[0]["account"]["account_id"] == "acct_admin"
    assert accounts[0]["site_count"] == 1
    assert accounts[0]["active_subscription_count"] >= 1
    assert accounts[0]["display_package_label"] == "Pro"
    assert accounts[0]["package_kind"] == "tier_package"
    assert accounts[0]["coverage_state"] == "covered"
    assert accounts[0]["primary_subscription_id"] == "sub_admin"
    assert package_filtered_accounts_response.status_code == 200
    assert (
        package_filtered_accounts_response.json()["data"]["filters"]["coverage_state"] == "covered"
    )
    assert (
        package_filtered_accounts_response.json()["data"]["filters"]["package_kind"]
        == "tier_package"
    )
    assert (
        package_filtered_accounts_response.json()["data"]["filters"]["top_plan_id"] == "plan_admin"
    )
    assert len(package_filtered_accounts_response.json()["data"]["items"]) == 1

    assert account_detail_response.status_code == 200
    account_detail = account_detail_response.json()["data"]
    assert len(account_detail["sites"]) == 1
    assert len(account_detail["subscriptions"]) >= 1

    suspend_account_response = client.post(
        "/internal/service/admin/accounts/acct_admin/suspend",
        json={"reason": "billing review"},
        headers=build_internal_headers(idempotency_key="svc-admin-account-suspend-001"),
    )
    assert suspend_account_response.status_code == 200
    assert suspend_account_response.json()["data"]["status"] == "suspended"
    assert (
        suspend_account_response.json()["data"]["metadata"]["account_status_note"]
        == "billing review"
    )
    assert suspend_account_response.json()["data"]["receipt"]["event_kind"] == "account.suspend"

    suspended_account_detail_response = client.get(
        "/internal/service/admin/accounts/acct_admin",
        headers=build_internal_headers(),
    )
    assert suspended_account_detail_response.status_code == 200
    assert suspended_account_detail_response.json()["data"]["account"]["status"] == "suspended"
    assert (
        suspended_account_detail_response.json()["data"]["account"]["metadata"][
            "account_status_note"
        ]
        == "billing review"
    )

    restore_account_response = client.post(
        "/internal/service/admin/accounts/acct_admin/restore",
        headers=build_internal_headers(idempotency_key="svc-admin-account-restore-001"),
    )
    assert restore_account_response.status_code == 200
    assert restore_account_response.json()["data"]["status"] == "active"
    assert restore_account_response.json()["data"]["receipt"]["event_kind"] == "account.restore"

    assert sites_response.status_code == 200
    sites = sites_response.json()["data"]["items"]
    assert len(sites) == 1
    assert sites[0]["site"]["site_id"] == "site_primary"
    assert sites[0]["active_key_count"] == 1
    assert sites[0]["coverage"]["covered_by_subscription_id"]
    assert sites[0]["coverage"]["subscription_status"] == "active"
    assert filtered_sites_response.status_code == 200
    assert filtered_sites_response.json()["data"]["filters"]["account_id"] == "acct_admin"
    assert filtered_sites_response.json()["data"]["filters"]["subscription_status"] == "active"
    assert len(filtered_sites_response.json()["data"]["items"]) == 1

    assert site_detail_response.status_code == 200
    site_detail = site_detail_response.json()["data"]
    assert site_detail["site"]["site_id"] == "site_primary"
    assert len(site_detail["site_keys"]) == 1
    assert site_detail["subscription"]["account_id"] == "acct_admin"
    assert site_detail["usage_meter"]["totals"]["runs"] >= 1
    assert site_detail["billing_reconciliation"]["site_id"] == "site_primary"
    assert site_detail["commercial_policy"]["policy"]["subscription"]["grace_period_days"] == 0
    assert "runtime_diagnostics" in site_detail
    assert site_detail["related_surfaces"]["account_href"] == "/admin/accounts/acct_admin"
    assert "/admin/subscriptions/" in site_detail["related_surfaces"]["subscription_href"]
    assert site_detail["commercial_follow_up"]["next_operator_follow_up"]
    assert site_detail["runtime_operator_explanations"]

    assert subscriptions_response.status_code == 200
    subscriptions = subscriptions_response.json()["data"]["items"]
    assert len(subscriptions) >= 1
    assert any(item["subscription"]["subscription_id"] == "sub_admin" for item in subscriptions)
    assert all(
        item["account"]["account_id"] == "acct_admin"
        for item in subscriptions
        if item.get("account")
    )
    assert any(
        any(site["site_id"] == "site_primary" for site in item.get("covered_sites") or [])
        for item in subscriptions
    )
    subscription_summary = next(
        item for item in subscriptions if item["subscription"]["subscription_id"] == "sub_admin"
    )
    assert subscription_summary["billing_snapshot_status"]["status"] == "fresh"
    assert subscription_summary["billing_snapshot_status"]["fresh_site_count"] == 1
    assert subscription_summary["billing_snapshot_status"]["stale_site_count"] == 0
    assert subscription_summary["billing_snapshot_status"]["missing_site_count"] == 0
    assert plans_response.status_code == 200
    plans = plans_response.json()["data"]["items"]
    tier_templates = plans_response.json()["data"]["tier_templates"]
    assert len(plans) >= 1
    assert [item["tier_id"] for item in tier_templates] == ["free", "pro", "agency"]
    assert tier_templates[0]["package_alias"] == "Free"
    assert tier_templates[0]["monthly_included_points"] == 300
    assert tier_templates[1]["monthly_included_points"] == 10000
    assert tier_templates[2]["monthly_included_points"] == 150000
    assert tier_templates[0]["site_limit"] == 1
    assert tier_templates[1]["site_limit"] == 5
    assert tier_templates[2]["site_limit"] == 25
    assert tier_templates[2]["concurrency_template"]["max_active_runs"] == 10
    assert tier_templates[0]["canonical_shell"]["entitlements"]["execution_tiers"] == ["cloud"]
    assert tier_templates[1]["canonical_shell"]["budgets"]["max_ai_credits_per_period"] == 10000
    assert tier_templates[1]["canonical_shell"]["budgets"]["max_runs_per_period"] == 0
    assert tier_templates[1]["canonical_shell"]["metadata"]["max_batch_items"] == 25
    assert (
        tier_templates[1]["canonical_shell"]["metadata"][
            "nightly_inspection_runs_per_period"
        ]
        == 30
    )
    assert tier_templates[2]["canonical_shell"]["metadata"]["max_batch_items"] == 100
    assert (
        tier_templates[2]["canonical_shell"]["metadata"][
            "nightly_inspection_runs_per_period"
        ]
        == 150
    )
    admin_plan_summary = next(item for item in plans if item["plan"]["plan_id"] == "plan_admin")
    assert admin_plan_summary["tier_summary"]["tier_id"] == "pro"
    assert admin_plan_summary["tier_summary"]["label"] == "Pro"
    assert admin_plan_summary["tier_summary"]["package_alias"] == "Pro"
    assert admin_plan_summary["tier_summary"]["monthly_included_points"] == 10000
    assert admin_plan_summary["tier_summary"]["site_limit"] == 5
    assert admin_plan_summary["tier_summary"]["max_batch_items"] == 25
    assert admin_plan_summary["tier_summary"]["nightly_inspection_runs_per_period"] == 30
    assert admin_plan_summary["tier_summary"]["nightly_inspection_retention_days"] == 14
    assert admin_plan_summary["tier_summary"]["automation_enabled"] is True
    assert admin_plan_summary["tier_summary"]["api_enabled"] is True
    assert admin_plan_summary["tier_summary"]["openclaw_enabled"] is True
    assert "ai credits" in admin_plan_summary["tier_summary"]["package_operator_note"].lower()
    assert admin_plan_summary["latest_version"]["plan_version_id"] == "plan_admin_v1"
    assert admin_plan_summary["published_version_count"] == 1
    assert plan_detail_response.status_code == 200
    plan_detail = plan_detail_response.json()["data"]
    assert plan_detail["plan"]["plan_id"] == "plan_admin"
    assert plan_detail["tier_summary"]["tier_id"] == "pro"
    assert plan_detail["tier_summary"]["package_alias"] == "Pro"
    assert plan_detail["tier_summary"]["monthly_included_points"] == 10000
    assert plan_detail["tier_summary"]["site_limit"] == 5
    assert plan_detail["tier_summary"]["max_batch_items"] == 25
    assert plan_detail["tier_summary"]["nightly_inspection_runs_per_period"] == 30
    assert plan_detail["tier_summary"]["nightly_inspection_retention_days"] == 14
    assert plan_detail["tier_summary"]["automation_enabled"] is True
    assert plan_detail["tier_summary"]["api_enabled"] is True
    assert plan_detail["tier_summary"]["openclaw_enabled"] is True
    assert plan_detail["tier_summary"]["concurrency_template"]["max_active_runs"] == 3
    assert plan_detail["latest_version"]["plan_version_id"] == "plan_admin_v1"
    assert plan_detail["package_fit_cues"]
    cue_codes = {item["code"] for item in plan_detail["package_fit_cues"]}
    assert "package_fit.cost_ceiling_missing" in cue_codes
    assert subscription_detail_response.status_code == 200
    subscription_detail = subscription_detail_response.json()["data"]
    assert subscription_detail["subscription"]["subscription_id"] == "sub_admin"
    assert subscription_detail["account"]["account_id"] == "acct_admin"
    assert subscription_detail["covered_sites"][0]["site_id"] == "site_primary"
    assert subscription_detail["plan"]["plan_id"] == "plan_admin"
    assert subscription_detail["plan_version"]["plan_version_id"] == "plan_admin_v1"
    assert subscription_detail["commercial_policy"]["subscription"]["grace_period_days"] == 0
    assert "runs" in subscription_detail["budget_state"]
    assert "tokens" in subscription_detail["budget_state"]
    assert "cost" in subscription_detail["budget_state"]
    assert subscription_detail["subscription_grace"]["subscription_status"] == "active"
    assert subscription_detail["usage_totals"]["runs"] >= 1
    assert subscription_detail["related_surfaces"]["site_href"] in {"", "/admin/sites/site_primary"}
    assert subscription_detail["related_surfaces"]["account_href"] == "/admin/accounts/acct_admin"
    assert subscription_detail["commercial_follow_up"]["next_operator_follow_up"]
    assert filtered_subscriptions_response.status_code == 200
    assert filtered_subscriptions_response.json()["data"]["filters"]["plan_id"] == "plan_admin"
    assert len(filtered_subscriptions_response.json()["data"]["items"]) == 1
    assert (
        filtered_subscriptions_response.json()["data"]["items"][0]["billing_snapshot_status"][
            "status"
        ]
        == "fresh"
    )
    assert expiring_accounts_response.status_code == 200
    assert len(expiring_accounts_response.json()["data"]["items"]) == 1

    assert unauthorized_response.status_code == 401
    assert unauthorized_response.json()["error_code"] == "auth.internal_token_required"

    dispose_engine(database_url)


def test_service_routes_plan_tier_fallback_and_package_fit_cues(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    create_plan_responses = [
        client.post(
            "/internal/service/plans",
            json={
                "plan_id": "free_ops",
                "name": "Free Ops",
                "metadata": {"tier_id": "free"},
            },
            headers=build_internal_headers(idempotency_key="svc-tier-plan-free-001"),
        ),
        client.post(
            "/internal/service/plans",
            json={"plan_id": "plan_version_tier", "name": "Version Tier Plan"},
            headers=build_internal_headers(idempotency_key="svc-tier-plan-version-001"),
        ),
        client.post(
            "/internal/service/plans",
            json={"plan_id": "agency_ops", "name": "Agency Operations"},
            headers=build_internal_headers(idempotency_key="svc-tier-plan-name-001"),
        ),
        client.post(
            "/internal/service/plans",
            json={"plan_id": "general_ops", "name": "General Operations"},
            headers=build_internal_headers(idempotency_key="svc-tier-plan-default-001"),
        ),
    ]
    assert all(response.status_code == 200 for response in create_plan_responses)

    create_version_responses = [
        client.post(
            "/internal/service/plans/free_ops/versions",
            json={
                "plan_version_id": "free_ops_v1",
                "version_label": "v1",
                "budgets": {
                    "max_runs_per_period": 100,
                    "max_tokens_per_period": 50_000,
                },
                "concurrency": {"max_active_runs": 1},
                "metadata": {"tier_id": "agency"},
            },
            headers=build_internal_headers(idempotency_key="svc-tier-version-free-001"),
        ),
        client.post(
            "/internal/service/plans/plan_version_tier/versions",
            json={
                "plan_version_id": "plan_version_tier_v1",
                "version_label": "v1",
                "budgets": {
                    "max_runs_per_period": 8_000,
                    "max_tokens_per_period": 6_000_000,
                    "max_cost_per_period": 220,
                },
                "concurrency": {"max_active_runs": 12},
                "metadata": {"tier_id": "agency"},
            },
            headers=build_internal_headers(idempotency_key="svc-tier-version-agency-001"),
        ),
        client.post(
            "/internal/service/plans/agency_ops/versions",
            json={
                "plan_version_id": "agency_ops_v1",
                "version_label": "v1",
                "budgets": {
                    "max_runs_per_period": 12_000,
                    "max_tokens_per_period": 9_000_000,
                    "max_cost_per_period": 260,
                },
                "concurrency": {"max_active_runs": 18},
            },
            headers=build_internal_headers(idempotency_key="svc-tier-version-name-001"),
        ),
        client.post(
            "/internal/service/plans/general_ops/versions",
            json={
                "plan_version_id": "general_ops_v1",
                "version_label": "v1",
                "budgets": {
                    "max_runs_per_period": 10_000,
                    "max_tokens_per_period": 2_000_000,
                    "max_cost_per_period": 99,
                },
                "concurrency": {"max_active_runs": 2},
            },
            headers=build_internal_headers(idempotency_key="svc-tier-version-default-001"),
        ),
    ]
    assert all(response.status_code == 200 for response in create_version_responses)

    plans_response = client.get(
        "/internal/service/admin/plans",
        headers=build_internal_headers(),
    )
    free_detail_response = client.get(
        "/internal/service/admin/plans/free_ops",
        headers=build_internal_headers(),
    )
    version_tier_detail_response = client.get(
        "/internal/service/admin/plans/plan_version_tier",
        headers=build_internal_headers(),
    )
    name_tier_detail_response = client.get(
        "/internal/service/admin/plans/agency_ops",
        headers=build_internal_headers(),
    )
    default_tier_detail_response = client.get(
        "/internal/service/admin/plans/general_ops",
        headers=build_internal_headers(),
    )

    assert plans_response.status_code == 200
    plans = {item["plan"]["plan_id"]: item for item in plans_response.json()["data"]["items"]}
    assert plans["free_ops"]["tier_summary"]["tier_id"] == "free"
    assert plans["free_ops"]["tier_summary"]["package_alias"] == "Free"
    assert plans["free_ops"]["tier_summary"]["monthly_included_points"] == 300
    assert plans["free_ops"]["tier_summary"]["site_limit"] == 1
    assert plans["free_ops"]["tier_summary"]["max_batch_items"] == 5
    assert plans["free_ops"]["tier_summary"]["automation_enabled"] is True
    assert plans["free_ops"]["tier_summary"]["api_enabled"] is True
    assert plans["free_ops"]["tier_summary"]["openclaw_enabled"] is True
    assert plans["plan_version_tier"]["tier_summary"]["tier_id"] == "agency"
    assert plans["plan_version_tier"]["tier_summary"]["package_alias"] == "Agency"
    assert plans["plan_version_tier"]["tier_summary"]["monthly_included_points"] == 150000
    assert plans["plan_version_tier"]["tier_summary"]["max_batch_items"] == 100
    assert (
        plans["plan_version_tier"]["tier_summary"][
            "nightly_inspection_runs_per_period"
        ]
        == 150
    )
    assert plans["plan_version_tier"]["tier_summary"]["openclaw_enabled"] is True
    assert plans["agency_ops"]["tier_summary"]["tier_id"] == "agency"
    assert plans["general_ops"]["tier_summary"]["tier_id"] == "pro"
    assert plans["general_ops"]["tier_summary"]["max_batch_items"] == 25
    assert plans["general_ops"]["tier_summary"]["nightly_inspection_runs_per_period"] == 30

    assert free_detail_response.status_code == 200
    free_detail = free_detail_response.json()["data"]
    assert free_detail["tier_summary"]["tier_id"] == "free"
    assert free_detail["tier_summary"]["package_alias"] == "Free"
    assert free_detail["tier_summary"]["monthly_included_points"] == 300
    assert free_detail["tier_summary"]["budgets_template"]["max_ai_credits_per_period"] == 300
    free_cue_codes = {item["code"] for item in free_detail["package_fit_cues"]}
    assert "package_fit.cost_ceiling_missing" in free_cue_codes

    assert version_tier_detail_response.status_code == 200
    version_tier_detail = version_tier_detail_response.json()["data"]
    assert version_tier_detail["tier_summary"]["tier_id"] == "agency"
    assert version_tier_detail["tier_summary"]["package_alias"] == "Agency"
    assert version_tier_detail["tier_summary"]["openclaw_enabled"] is True

    assert name_tier_detail_response.status_code == 200
    name_tier_detail = name_tier_detail_response.json()["data"]
    assert name_tier_detail["tier_summary"]["tier_id"] == "agency"

    assert default_tier_detail_response.status_code == 200
    default_tier_detail = default_tier_detail_response.json()["data"]
    assert default_tier_detail["tier_summary"]["tier_id"] == "pro"
    assert default_tier_detail["tier_summary"]["package_alias"] == "Pro"
    assert default_tier_detail["tier_summary"]["automation_enabled"] is True
    assert default_tier_detail["tier_summary"]["api_enabled"] is True
    assert default_tier_detail["tier_summary"]["openclaw_enabled"] is True
    assert default_tier_detail["package_fit_cues"][0]["code"] == "package_fit.within_band"

    dispose_engine(database_url)


def test_service_routes_removed_platform_admin_grant_routes(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    response = client.post(
        "/internal/service/platform-admin-identities",
        json={
            "principal_id": "platform:founder",
            "role": "platform_admin",
            "email": "founder@example.com",
            "provider": "manual",
        },
        headers=build_internal_headers(idempotency_key="svc-platform-admin-001"),
    )

    assert response.status_code == 404

    delete_response = client.delete(
        "/internal/service/platform-admin-identities/platform:founder",
        headers=build_internal_headers(idempotency_key="svc-platform-admin-delete-001"),
    )

    assert delete_response.status_code == 404

    missing_response = client.delete(
        "/internal/service/platform-admin-identities/platform:founder",
        headers=build_internal_headers(idempotency_key="svc-platform-admin-delete-002"),
    )

    assert missing_response.status_code == 404

    dispose_engine(database_url)


def test_admin_account_quota_summary_reports_ai_credits_and_resource_limits(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_quota",
        scopes=["runtime:execute", "runtime:read", "stats:read"],
        budgets={
            "max_ai_credits_per_period": 20,
            "max_runs_per_period": 10,
            "max_tokens_per_period": 5000,
        },
    )
    now = datetime.now(UTC)
    with get_session(database_url) as session:
        subscription = session.scalar(
            select(AccountSubscription)
            .where(AccountSubscription.account_id == "acct_site_quota")
            .order_by(AccountSubscription.created_at.desc())
        )
        assert subscription is not None
        events = [
            UsageMeterEvent(
                account_id="acct_site_quota",
                site_id="site_quota",
                subscription_id=subscription.subscription_id,
                plan_version_id=subscription.plan_version_id,
                run_id="run-quota-1",
                provider_call_id=None,
                event_kind="runtime.run",
                meter_key="runs",
                quantity=2,
                ability_family="text",
                channel="api",
                execution_kind="text",
                execution_tier="cloud",
                data_classification="internal",
                currency=None,
                dedupe_key="quota-summary-runs",
                payload_json={},
                created_at=now,
            ),
            UsageMeterEvent(
                account_id="acct_site_quota",
                site_id="site_quota",
                subscription_id=subscription.subscription_id,
                plan_version_id=subscription.plan_version_id,
                run_id="run-quota-1",
                provider_call_id=None,
                event_kind="runtime.tokens",
                meter_key="tokens_total",
                quantity=1500,
                ability_family="text",
                channel="api",
                execution_kind="text",
                execution_tier="cloud",
                data_classification="internal",
                currency=None,
                dedupe_key="quota-summary-tokens",
                payload_json={},
                created_at=now,
            ),
            UsageMeterEvent(
                account_id="acct_site_quota",
                site_id="site_quota",
                subscription_id=subscription.subscription_id,
                plan_version_id=subscription.plan_version_id,
                run_id="run-quota-1",
                provider_call_id=None,
                event_kind="provider.call",
                meter_key="provider_calls",
                quantity=1,
                ability_family="tool",
                channel="api",
                execution_kind="web_search",
                execution_tier="cloud",
                data_classification="internal",
                currency=None,
                dedupe_key="quota-summary-search",
                payload_json={},
                created_at=now,
            ),
        ]
        session.add_all(events)
        session.commit()

    response = client.get(
        "/internal/service/admin/accounts/acct_site_quota/quota-summary",
        headers=build_internal_headers(),
    )
    unauthenticated = client.get(
        "/internal/service/admin/accounts/acct_site_quota/quota-summary",
    )

    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["account_id"] == "acct_site_quota"
    assert data["credit"]["key"] == "ai_credits"
    assert data["credit"]["used"] == 9.0
    assert data["credit"]["limit"] == 20.0
    assert data["credit"]["remaining"] == 11.0
    assert data["credit"]["status"] == "ok"
    assert data["credit"]["estimated"] is True
    assert data["credit"]["rate_version"] == "ai-credit-estimate-v2"
    assert data["credit_policy"]["rate_version"] == "ai-credit-ledger-v2"
    assert data["credit_policy"]["renewal_policy"] == "monthly_plan_grant_resets_each_period"
    assert {item["key"]: item["credits"] for item in data["breakdown"]} == {
        "runs": 2.0,
        "tokens_total": 2,
        "web_search": 5.0,
    }
    resource_limits = {item["key"]: item for item in data["resource_limits"]}
    assert resource_limits["bound_sites"]["used"] == 1.0
    assert resource_limits["active_api_key_sites"]["used"] == 1.0
    assert resource_limits["vector_documents"]["unit"] == "document"
    assert data["coverage"]["active_key_site_count"] == 1


def test_admin_account_credit_ledger_lists_current_period_entries(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_credit_ledger",
        scopes=["runtime:execute", "runtime:read", "stats:read"],
        budgets={"max_ai_credits_per_period": 20},
    )
    now = datetime.now(UTC)
    with get_session(database_url) as session:
        subscription = session.scalar(
            select(AccountSubscription)
            .where(AccountSubscription.account_id == "acct_site_credit_ledger")
            .order_by(AccountSubscription.created_at.desc())
        )
        assert subscription is not None
        repository = CommercialRepository(session)
        repository.record_credit_ledger_entry(
            account_id="acct_site_credit_ledger",
            site_id="site_credit_ledger",
            subscription_id=subscription.subscription_id,
            plan_version_id=subscription.plan_version_id,
            run_id="run-credit-ledger-1",
            provider_call_id=None,
            source_type="tokens_total",
            source_id="run-credit-ledger-1:tokens",
            credit_delta=-2,
            quantity=1500,
            unit="token",
            rate=1,
            rate_unit="1000_tokens_rounded_up",
            rate_version="ai-credit-ledger-v2",
            idempotency_key="credit-ledger-tokens-001",
            created_at=now,
        )
        repository.record_credit_ledger_entry(
            account_id="acct_site_credit_ledger",
            site_id="site_credit_ledger",
            subscription_id=subscription.subscription_id,
            plan_version_id=subscription.plan_version_id,
            run_id="run-credit-ledger-1",
            provider_call_id=None,
            source_type="vector_chunks",
            source_id="run-credit-ledger-1:chunks",
            credit_delta=-2,
            quantity=11,
            unit="chunk",
            rate=1,
            rate_unit="10_chunks_rounded_up",
            rate_version="ai-credit-ledger-v2",
            idempotency_key="credit-ledger-chunks-001",
            created_at=now + timedelta(seconds=1),
        )
        session.commit()

    unauthenticated = client.get(
        "/internal/service/admin/accounts/acct_site_credit_ledger/credit-ledger"
    )
    response = client.get(
        "/internal/service/admin/accounts/acct_site_credit_ledger/credit-ledger?limit=1",
        headers=build_internal_headers(),
    )

    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["account_id"] == "acct_site_credit_ledger"
    assert data["rate_version"] == "ai-credit-ledger-v2"
    assert data["summary"]["total_credits"] == 4.0
    assert data["summary"]["entry_count"] == 2
    assert {item["key"]: item["credits"] for item in data["summary"]["breakdown"]} == {
        "tokens_total": 2.0,
        "vector_chunks": 2.0,
    }
    assert data["pagination"] == {
        "limit": 1,
        "offset": 0,
        "total": 2,
        "has_more": True,
    }
    assert len(data["items"]) == 1
    assert data["items"][0]["source_type"] == "vector_chunks"
    assert data["items"][0]["credit_delta"] == -2.0
    assert data["items"][0]["consumed_credits"] == 2.0

    dispose_engine(database_url)


def test_admin_account_credit_adjustment_updates_ledger_and_quota_summary(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_credit_adjustment",
        scopes=["runtime:execute", "runtime:read", "stats:read"],
        budgets={"max_ai_credits_per_period": 20},
    )
    now = datetime.now(UTC)
    with get_session(database_url) as session:
        subscription = session.scalar(
            select(AccountSubscription)
            .where(AccountSubscription.account_id == "acct_site_credit_adjustment")
            .order_by(AccountSubscription.created_at.desc())
        )
        assert subscription is not None
        repository = CommercialRepository(session)
        repository.record_credit_ledger_entry(
            account_id="acct_site_credit_adjustment",
            site_id="site_credit_adjustment",
            subscription_id=subscription.subscription_id,
            plan_version_id=subscription.plan_version_id,
            run_id="run-credit-adjustment-1",
            provider_call_id=None,
            source_type="tokens_total",
            source_id="run-credit-adjustment-1:tokens",
            credit_delta=-12,
            quantity=12000,
            unit="token",
            rate=1,
            rate_unit="1000_tokens_rounded_up",
            rate_version="ai-credit-ledger-v2",
            idempotency_key="credit-adjustment-consume-001",
            created_at=now,
        )
        session.commit()

    response = client.post(
        "/internal/service/admin/accounts/acct_site_credit_adjustment/credit-ledger/adjustments",
        headers=build_internal_headers(idempotency_key="svc-credit-adjustment-001"),
        json={
            "event_type": "grant",
            "credit_delta": 5,
            "reason": "billing_correction",
            "note": "restore manually purchased credits",
        },
    )
    missing_reason = client.post(
        "/internal/service/admin/accounts/acct_site_credit_adjustment/credit-ledger/adjustments",
        headers=build_internal_headers(idempotency_key="svc-credit-adjustment-002"),
        json={"event_type": "grant", "credit_delta": 1, "reason": ""},
    )
    quota_response = client.get(
        "/internal/service/admin/accounts/acct_site_credit_adjustment/quota-summary",
        headers=build_internal_headers(),
    )
    ledger_response = client.get(
        "/internal/service/admin/accounts/acct_site_credit_adjustment/credit-ledger",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["receipt"]["event_kind"] == "credit_ledger.adjustment"
    assert payload["entry"]["event_type"] == "grant"
    assert payload["entry"]["credit_delta"] == 5.0
    assert payload["entry"]["granted_credits"] == 5.0
    assert payload["entry"]["metadata"]["reason"] == "billing_correction"
    assert payload["summary"]["consumed_credits"] == 12.0
    assert payload["summary"]["granted_credits"] == 5.0
    assert payload["summary"]["net_credit_delta"] == -7.0
    assert payload["summary"]["net_used_credits"] == 7.0
    assert missing_reason.status_code == 400

    assert quota_response.status_code == 200
    quota = quota_response.json()["data"]
    assert quota["credit"]["used"] == 7.0
    assert quota["credit"]["remaining"] == 13.0
    assert quota["credit"]["estimated"] is False
    assert quota["credit_ledger_summary"]["net_used_credits"] == 7.0

    assert ledger_response.status_code == 200
    ledger = ledger_response.json()["data"]
    assert ledger["summary"]["entry_count"] == 2
    assert ledger["summary"]["consumed_credits"] == 12.0
    assert ledger["summary"]["granted_credits"] == 5.0
    assert ledger["summary"]["net_used_credits"] == 7.0
    assert {item["event_type"] for item in ledger["items"]} == {"consume", "grant"}

    dispose_engine(database_url)


def test_credit_ledger_consume_credit_delta_must_be_integer(
    tmp_path: Path,
) -> None:
    database_url, _client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_credit_integer",
        scopes=["runtime:execute", "runtime:read", "stats:read"],
    )
    with get_session(database_url) as session:
        subscription = session.scalar(
            select(AccountSubscription)
            .where(AccountSubscription.account_id == "acct_site_credit_integer")
            .order_by(AccountSubscription.created_at.desc())
        )
        assert subscription is not None
        repository = CommercialRepository(session)
        try:
            repository.record_credit_ledger_entry(
                account_id="acct_site_credit_integer",
                site_id="site_credit_integer",
                subscription_id=subscription.subscription_id,
                plan_version_id=subscription.plan_version_id,
                run_id="run-credit-integer-1",
                provider_call_id=None,
                source_type="tokens_total",
                source_id="run-credit-integer-1:tokens",
                credit_delta=-1.25,
                quantity=1250,
                unit="token",
                rate=1,
                rate_unit="1000_tokens_rounded_up",
                rate_version="ai-credit-ledger-v2",
                idempotency_key="credit-integer-invalid-001",
            )
        except ValueError as error:
            assert "integer credit unit" in str(error)
        else:
            raise AssertionError("non-integer consume credit_delta should be rejected")
        session.rollback()

        entry = repository.record_credit_ledger_entry(
            account_id="acct_site_credit_integer",
            site_id="site_credit_integer",
            subscription_id=subscription.subscription_id,
            plan_version_id=subscription.plan_version_id,
            run_id="run-credit-integer-2",
            provider_call_id=None,
            source_type="vector_chunks",
            source_id="run-credit-integer-2:chunks",
            credit_delta=-2.0,
            quantity=11,
            unit="chunk",
            rate=1,
            rate_unit="10_chunks_rounded_up",
            rate_version="ai-credit-ledger-v2",
            idempotency_key="credit-integer-valid-001",
        )
        assert entry.credit_delta == -2.0
        session.commit()

    dispose_engine(database_url)


def test_service_routes_inspect_commercial_policy_and_reconciliation(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    _seed_openai_text_model_allowlist(database_url)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_policy", "name": "Policy Account"},
        headers=build_internal_headers(idempotency_key="svc-policy-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_policy",
            "account_id": "acct_policy",
            "name": "Policy Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="svc-policy-site-001"),
    )
    client.post(
        "/internal/service/sites/site_policy/activate",
        headers=build_internal_headers(idempotency_key="svc-policy-site-activate-001"),
    )
    client.post(
        "/internal/service/sites/site_policy/keys",
        json={
            "key_id": "key_policy_primary",
            "secret": "policy-secret",
            "scopes": ["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
            "label": "policy-primary",
        },
        headers=build_internal_headers(idempotency_key="svc-policy-key-001"),
    )
    client.post(
        "/internal/service/plans",
        json={"plan_id": "plan_policy", "name": "Policy"},
        headers=build_internal_headers(idempotency_key="svc-policy-plan-001"),
    )
    version_response = client.post(
        "/internal/service/plans/plan_policy/versions",
        json={
            "plan_version_id": "plan_policy_v1",
            "version_label": "v1",
            "entitlements": {
                "ability_families": ["workflow", "automation"],
                "channels": ["openapi"],
                "execution_kinds": ["text"],
                "execution_tiers": ["cloud"],
                "data_classifications": ["internal"],
            },
            "budgets": {"max_runs_per_period": 1},
            "concurrency": {"max_active_runs": 2},
            "policy": {
                "subscription": {
                    "grace_period_days": 2,
                    "downgrade_policy": {
                        "retry_max": 0,
                        "task_backend": {
                            "enabled": False,
                            "mode": "inline",
                            "callback_mode": "polling_only",
                        },
                    },
                },
                "budgets": {
                    "runs": {
                        "grace_requests": 1,
                        "downgrade_policy": {
                            "retry_max": 0,
                            "task_backend": {
                                "enabled": False,
                                "mode": "inline",
                                "callback_mode": "polling_only",
                            },
                        },
                    }
                },
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
        headers=build_internal_headers(idempotency_key="svc-policy-plan-version-001"),
    )
    bind_response = client.post(
        "/internal/service/admin/accounts/acct_policy/subscription",
        json={
            "subscription_id": "sub_policy",
            "account_id": "acct_policy",
            "plan_id": "plan_policy",
            "plan_version_id": "plan_policy_v1",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="svc-policy-subscription-001"),
    )

    assert version_response.status_code == 200
    assert version_response.json()["data"]["policy"]["budgets"]["runs"]["grace_requests"] == 1
    assert bind_response.status_code == 200

    execute_payload = {
        "site_id": "site_policy",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-policy-run-001",
        "input": {"messages": [{"role": "user", "content": "policy run"}]},
    }
    execute_body = json.dumps(execute_payload).encode("utf-8")
    execute_response = client.post(
        "/v1/runtime/execute",
        content=execute_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_policy",
                key_id="key_policy_primary",
                secret="policy-secret",
                idempotency_key="idem-policy-run-001",
                trace_id="tracepolicyrun0010000000000",
                body=execute_body,
            )
        ),
    )
    policy_response = client.get(
        "/internal/service/sites/site_policy/commercial-policy",
        headers=build_internal_headers(),
    )
    reconciliation_before_response = client.get(
        "/internal/service/sites/site_policy/billing-snapshots/reconciliation",
        headers=build_internal_headers(),
    )
    rebuild_response = client.post(
        "/internal/service/sites/site_policy/billing-snapshots/rebuild",
        headers=build_internal_headers(idempotency_key="svc-policy-rebuild-001"),
    )

    assert execute_response.status_code == 200
    assert policy_response.status_code == 200
    assert policy_response.json()["data"]["policy"]["budgets"]["runs"]["grace_requests"] == 1
    assert policy_response.json()["data"]["budget_state"]["runs"]["limit"] == 1.0
    assert reconciliation_before_response.status_code == 200
    assert "snapshot_present" in reconciliation_before_response.json()["data"]["reconciliation"]
    assert rebuild_response.status_code == 200

    with get_session(database_url) as session:
        snapshot = session.scalar(
            select(BillingSnapshot)
            .where(BillingSnapshot.site_id == "site_policy")
            .order_by(BillingSnapshot.generated_at.desc())
        )
        assert snapshot is not None
        snapshot.totals_json = {
            **(snapshot.totals_json or {}),
            "runs": 0.0,
        }
        session.commit()

    reconciliation_after_response = client.get(
        "/internal/service/sites/site_policy/billing-snapshots/reconciliation",
        headers=build_internal_headers(),
    )

    assert reconciliation_after_response.status_code == 200
    mismatch = reconciliation_after_response.json()["data"]["reconciliation"]
    assert mismatch["snapshot_present"] is True
    assert mismatch["in_sync"] is False
    assert mismatch["recommended_action"] == "rebuild_snapshot"
    assert mismatch["mismatches"]["runs"]["delta"] == 1.0

    dispose_engine(database_url)


def test_service_routes_cleanup_retention_and_record_audit(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    _seed_openai_text_model_allowlist(database_url)
    seed_site_auth(
        database_url,
        site_id="site_cleanup",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    payload = {
        "site_id": "site_cleanup",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-cleanup-001",
        "retention_ttl": 60,
        "input": {"messages": [{"role": "user", "content": "expire this result"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    execute_response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_cleanup",
                idempotency_key="idem-cleanup-001",
                trace_id="tracecleanup0010000000000000000",
                body=body,
            )
        ),
    )
    assert execute_response.status_code == 200
    run_id = execute_response.json()["data"]["run_id"]

    with get_session(database_url) as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        run.completed_at = datetime.now(UTC) - timedelta(hours=2)
        run.retention_expires_at = datetime.now(UTC) - timedelta(minutes=10)
        session.commit()

    cleanup_response = client.post(
        "/internal/service/runtime/retention/cleanup",
        headers=build_internal_headers(idempotency_key="svc-retention-cleanup-001"),
    )
    assert cleanup_response.status_code == 200
    assert cleanup_response.json()["data"]["purged_runs"] == 1

    with get_session(database_url) as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        assert run.result_json is None

    audit_response = client.get(
        "/internal/service/audit-events?event_kind=runtime.retention_cleanup&limit=5",
        headers=build_internal_headers(),
    )
    assert audit_response.status_code == 200
    assert audit_response.json()["data"]["items"][0]["payload"]["purged_runs"] == 1

    dispose_engine(database_url)


def test_service_routes_expose_ops_cadence_summary(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "retention_cleanup_interval_seconds": 60,
            "plugin_observability_cleanup_interval_seconds": 60,
            "usage_rollup_interval_seconds": 60,
            "router_diagnostics_interval_seconds": 60,
            "latency_probe_interval_seconds": 60,
            "alert_provider_degradation_interval_seconds": 60,
            "provider_health_scan_interval_seconds": 60,
        },
    )

    service = CommercialService(database_url)
    now = datetime(2026, 4, 12, 12, 0, tzinfo=UTC)
    audit_context = ServiceAuditContext(
        trace_id="",
        idempotency_key="",
        method="POST",
        path="/internal/workers/test",
        actor_kind="system_worker",
        actor_ref="ops_cadence_test",
    )
    service.record_service_audit_event(
        audit_context=audit_context,
        event_kind="runtime.retention_cleanup.cadence",
        outcome="succeeded",
        scope_kind="ops_cadence",
        scope_id="retention_cleanup",
        payload_json={"purged_runs": 1},
    )
    run_due_tasks(_runtime_service_settings(database_url), now=now + timedelta(seconds=1))
    response = client.get(
        "/internal/service/ops/cadence",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["totals"]["tasks_total"] == 8
    assert any(item["task_id"] == "retention_cleanup" for item in payload["items"])
    assert all(item["task_id"] != "hosted_model_governance" for item in payload["items"])
    retention_item = next(
        item for item in payload["items"] if item["task_id"] == "retention_cleanup"
    )
    assert retention_item["last_run_at"] != ""
    assert retention_item["freshness"] in {"fresh", "attention"}

    dispose_engine(database_url)


def test_service_routes_expose_observability_summary(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "worker_heartbeat_interval_seconds": 60,
            "provider_health_scan_interval_seconds": 60,
        },
    )
    settings = _runtime_service_settings(database_url)
    now = datetime(2026, 4, 12, 12, 0, tzinfo=UTC)
    run_due_tasks(settings, now=now)
    CommercialService(database_url, settings=settings).record_service_audit_event(
        audit_context=ServiceAuditContext(
            trace_id="",
            idempotency_key="",
            method="POST",
            path="/internal/workers/runtime_queue/heartbeat",
            actor_kind="system_worker",
            actor_ref="runtime_queue",
        ),
        event_kind="worker.heartbeat",
        outcome="succeeded",
        scope_kind="worker",
        scope_id="runtime_queue",
        payload_json={
            "worker_id": "runtime_queue",
            "status": "idle",
            "recorded_at": now.isoformat().replace("+00:00", "Z"),
        },
    )

    response = client.get(
        "/internal/service/observability/summary?recent_minutes=60&backlog_limit=10",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["ready"]["status"] == "error"
    assert payload["tracing"]["service_name"] == "npcink-ai-cloud"
    assert isinstance(payload["tracing"]["trace_sink_configured"], bool)
    assert payload["feature_flags"]["summary"]["flags_total"] >= 1
    assert payload["feature_flags"]["summary"]["overridden_total"] == 0
    assert any(
        item["key"] == "admin.commercial_ops.enabled" for item in payload["feature_flags"]["items"]
    )
    assert payload["workers"]["totals"]["workers_total"] == 3
    assert any(item["worker_id"] == "runtime_queue" for item in payload["workers"]["items"])
    assert payload["cadence"]["totals"]["tasks_total"] == 8
    assert "status_counts" in payload["providers"]
    assert "summary" in payload["runtime"]
    assert "backlog" in payload["runtime"]

    dispose_engine(database_url)


def test_service_routes_observability_summary_marks_trace_sink_configured_when_present(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "otel_exporter_otlp_endpoint": "http://host.docker.internal:4318/v1/traces",
            "otel_trace_sink_otlp_endpoint": "host.docker.internal:4318",
            "otel_trace_query_url": "http://mini.example:16686",
        },
    )

    response = client.get(
        "/internal/service/observability/summary",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["tracing"]["otlp_configured"] is True
    assert payload["tracing"]["trace_sink_configured"] is True
    assert payload["tracing"]["otlp_endpoint"] == "http://host.docker.internal:4318/v1/traces"
    assert payload["tracing"]["trace_sink_otlp_endpoint"] == "host.docker.internal:4318"
    assert payload["tracing"]["trace_sink_query_url"] == "http://mini.example:16686"

    dispose_engine(database_url)


def test_service_routes_observability_summary_surfaces_feature_flag_overrides(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "feature_flags_json": (
                '{"portal.billing.readonly.enabled": false,'
                ' "runtime.experimental_probe.enabled": true}'
            ),
        },
    )

    response = client.get(
        "/internal/service/observability/summary",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["feature_flags"]["parse_error"] == ""
    assert payload["feature_flags"]["summary"]["overridden_total"] == 2
    assert any(
        item["key"] == "portal.billing.readonly.enabled"
        and item["enabled"] is False
        and item["source"] == "env_override"
        for item in payload["feature_flags"]["items"]
    )
    assert any(
        item["key"] == "runtime.experimental_probe.enabled"
        and item["enabled"] is True
        and item["source"] == "env_override"
        for item in payload["feature_flags"]["items"]
    )

    dispose_engine(database_url)


def test_service_routes_runtime_diagnostics_summaries_and_abuse_guard(
    tmp_path: Path,
    allow_example_callback_dns: None,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "public_post_rate_limit_window_seconds": 600,
            "public_post_max_requests_per_window": 10,
            "public_post_max_requests_per_key_window": 10,
            "public_post_max_requests_per_ip_window": 10,
            "public_guard_max_reject_events_per_site_window": 3,
            "internal_post_rate_limit_window_seconds": 600,
            "internal_post_max_requests_per_window": 10,
            "internal_post_max_requests_per_ip_window": 10,
            },
        )
    _seed_openai_text_model_allowlist(database_url)
    seed_site_auth(
        database_url,
        site_id="site_diag",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    account_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_diag", "name": "Diagnostics Account"},
        headers=build_internal_headers(idempotency_key="svc-diag-account-001"),
    )
    internal_replay_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_diag_replay", "name": "Diagnostics Account Replay"},
        headers=build_internal_headers(idempotency_key="svc-diag-account-001"),
    )
    missing_activate_response = client.post(
        "/internal/service/sites/site_missing/activate",
        headers=build_internal_headers(idempotency_key="svc-diag-activate-missing-001"),
    )

    CommercialService(
        database_url,
        settings=_runtime_service_settings(database_url),
    ).update_site_runtime_callbacks(
        site_id="site_diag",
        terminal_callback={
            "enabled": True,
            "callback_url": "https://example.com/diag",
            "key_id": "runtime_callback_key",
            "secret": "runtime-callback-secret-for-tests-32b",
            "callback_id": "runtime_terminal",
        },
    )

    callback_payload = {
        "site_id": "site_diag",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-diag-callback-001",
        "retention_ttl": 60,
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "terminal_callback_required",
            "polling_interval_sec": 60,
        },
        "input": {"messages": [{"role": "user", "content": "diag callback"}]},
    }
    callback_body = json.dumps(callback_payload).encode("utf-8")
    callback_response = client.post(
        "/v1/runtime/execute",
        content=callback_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_diag",
                idempotency_key="idem-diag-callback-001",
                trace_id="tracediagcallback001000000000",
                body=callback_body,
            )
        ),
    )
    callback_replay_response = client.post(
        "/v1/runtime/execute",
        content=callback_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_diag",
                idempotency_key="idem-diag-callback-001",
                trace_id="tracediagcallback001000000000",
                body=callback_body,
            )
        ),
    )
    queued_payload = {
        "site_id": "site_diag",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "input": {"messages": [{"role": "user", "content": "diag queue"}]},
    }
    queued_body = json.dumps({**queued_payload, "idempotency_key": "idem-diag-queued-001"}).encode(
        "utf-8"
    )
    running_body = json.dumps(
        {**queued_payload, "idempotency_key": "idem-diag-running-001"}
    ).encode("utf-8")
    queued_response = client.post(
        "/v1/runtime/execute",
        content=queued_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_diag",
                idempotency_key="idem-diag-queued-001",
                trace_id="tracediagqueued0010000000000",
                body=queued_body,
            )
        ),
    )
    running_response = client.post(
        "/v1/runtime/execute",
        content=running_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_diag",
                idempotency_key="idem-diag-running-001",
                trace_id="tracediagrunning001000000000",
                body=running_body,
            )
        ),
    )
    dispatching_payload = {
        **callback_payload,
        "idempotency_key": "idem-diag-dispatching-001",
    }
    overdue_payload = {
        **callback_payload,
        "idempotency_key": "idem-diag-overdue-001",
    }
    dispatching_body = json.dumps(dispatching_payload).encode("utf-8")
    overdue_body = json.dumps(overdue_payload).encode("utf-8")
    dispatching_response = client.post(
        "/v1/runtime/execute",
        content=dispatching_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_diag",
                idempotency_key="idem-diag-dispatching-001",
                trace_id="tracediagdispatch00100000000",
                body=dispatching_body,
            )
        ),
    )
    overdue_response = client.post(
        "/v1/runtime/execute",
        content=overdue_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_diag",
                idempotency_key="idem-diag-overdue-001",
                trace_id="tracediagoverdue001000000000",
                body=overdue_body,
            )
        ),
    )

    assert account_response.status_code == 200
    assert internal_replay_response.status_code == 409
    assert missing_activate_response.status_code == 404
    assert callback_response.status_code == 200
    assert callback_replay_response.status_code == 409
    assert queued_response.status_code == 200
    assert running_response.status_code == 200
    assert dispatching_response.status_code == 200
    assert overdue_response.status_code == 200

    callback_run_id = callback_response.json()["data"]["run_id"]
    queued_run_id = queued_response.json()["data"]["run_id"]
    running_run_id = running_response.json()["data"]["run_id"]
    dispatching_run_id = dispatching_response.json()["data"]["run_id"]
    overdue_run_id = overdue_response.json()["data"]["run_id"]

    with get_session(database_url) as session:
        callback_run = session.get(RunRecord, callback_run_id)
        queued_run = session.get(RunRecord, queued_run_id)
        running_run = session.get(RunRecord, running_run_id)
        dispatching_run = session.get(RunRecord, dispatching_run_id)
        overdue_run = session.get(RunRecord, overdue_run_id)
        assert callback_run is not None
        assert queued_run is not None
        assert running_run is not None
        assert dispatching_run is not None
        assert overdue_run is not None

        callback_run.callback_status = "failed"
        callback_run.callback_last_attempt_at = datetime.now(UTC) - timedelta(minutes=15)
        callback_run.callback_last_error_code = "runtime.callback_delivery_failed"
        callback_run.retention_expires_at = datetime.now(UTC) - timedelta(minutes=5)

        queued_run.status = "queued"
        queued_run.started_at = datetime.now(UTC) - timedelta(minutes=11)
        queued_run.processing_started_at = None
        queued_run.finished_at = None

        dispatching_run.callback_status = "dispatching"
        dispatching_run.callback_last_attempt_at = datetime.now(UTC) - timedelta(minutes=6)

        running_run.status = "running"
        running_run.processing_started_at = datetime.now(UTC) - timedelta(minutes=7)
        running_run.cancel_requested_at = datetime.now(UTC) - timedelta(minutes=7)

        overdue_run.callback_status = "pending"
        overdue_run.callback_next_attempt_at = datetime.now(UTC) - timedelta(minutes=12)

        for index in range(12):
            session.add(
                ReplayReceipt(
                    scope_kind=REPLAY_SCOPE_PUBLIC_POST_SITE,
                    scope_id="site_diag",
                    replay_key=f"manual-burst-{index}",
                    method="POST",
                    path="/v1/runtime/execute",
                    trace_id=f"manualburst{index:02d}",
                    created_at=datetime.now(UTC) - timedelta(minutes=2),
                    expires_at=datetime.now(UTC) + timedelta(minutes=8),
                )
            )

        for index in range(4):
            session.add(
                RuntimeGuardEvent(
                    auth_surface="public_runtime",
                    scope_kind=REPLAY_SCOPE_PUBLIC_POST_SITE,
                    scope_id="site_diag",
                    site_id="site_diag",
                    key_id="key_default",
                    client_ref="127.0.0.1",
                    event_code="auth.rate_limit_exceeded" if index < 3 else "auth.replay_blocked",
                    status_code=429 if index < 3 else 409,
                    method="POST",
                    path="/v1/runtime/execute",
                    trace_id=f"manualguard{index:02d}",
                    payload_json={"source": "test_seed"},
                    created_at=datetime.now(UTC) - timedelta(minutes=3),
                )
            )

        session.commit()

    runtime_summary_response = client.get(
        "/internal/service/runtime/diagnostics/summary?site_id=site_diag&recent_minutes=120",
        headers=build_internal_headers(),
    )
    callback_runs_response = client.get(
        "/internal/service/runtime/diagnostics/runs?issue_kind=callback_failed&site_id=site_diag&limit=5",
        headers=build_internal_headers(),
    )
    cancel_runs_response = client.get(
        "/internal/service/runtime/diagnostics/runs?issue_kind=cancel_requested&site_id=site_diag&limit=5",
        headers=build_internal_headers(),
    )
    dispatching_runs_response = client.get(
        "/internal/service/runtime/diagnostics/runs?issue_kind=callback_dispatching&site_id=site_diag&limit=5",
        headers=build_internal_headers(),
    )
    queued_stale_runs_response = client.get(
        "/internal/service/runtime/diagnostics/runs?issue_kind=queued_stale&site_id=site_diag&limit=5",
        headers=build_internal_headers(),
    )
    cancel_stuck_runs_response = client.get(
        "/internal/service/runtime/diagnostics/runs?issue_kind=cancel_stuck&site_id=site_diag&limit=5",
        headers=build_internal_headers(),
    )
    callback_overdue_runs_response = client.get(
        "/internal/service/runtime/diagnostics/runs?issue_kind=callback_overdue&site_id=site_diag&limit=5",
        headers=build_internal_headers(),
    )
    guard_events_response = client.get(
        "/internal/service/runtime/diagnostics/guard-events?site_id=site_diag&limit=20",
        headers=build_internal_headers(),
    )
    audit_summary_response = client.get(
        "/internal/service/audit-events/summary?window_minutes=120&limit=10",
        headers=build_internal_headers(),
    )
    decision_summary_response = client.get(
        "/internal/service/commercial-decisions/summary?site_id=site_diag&window_minutes=120&limit=10",
        headers=build_internal_headers(),
    )
    abuse_guard_response = client.get(
        "/internal/service/runtime/diagnostics/abuse-guard?window_seconds=600&limit_per_scope=5",
        headers=build_internal_headers(),
    )

    assert runtime_summary_response.status_code == 200
    runtime_summary = runtime_summary_response.json()["data"]
    assert runtime_summary["queue"]["queued_runs"] == 1
    assert runtime_summary["queue"]["running_runs"] == 1
    assert runtime_summary["queue"]["pressure_state"] == "attention"
    assert "queue.queued_stale" in runtime_summary["queue"]["pressure_reasons"]
    assert runtime_summary["queue"]["queued_oldest_age_seconds"] >= 600
    assert runtime_summary["cancel"]["active_requests"] == 1
    assert runtime_summary["cancel"]["pressure_state"] == "attention"
    assert "cancel.request_stuck" in runtime_summary["cancel"]["pressure_reasons"]
    assert runtime_summary["cancel"]["oldest_request_age_seconds"] >= 300
    assert runtime_summary["callback"]["failed"] == 1
    assert runtime_summary["callback"]["recoverable_dispatching"] == 1
    assert runtime_summary["callback"]["recovery_action"] == (
        "requeue_pending_after_stale_dispatch_lease"
    )
    assert runtime_summary["callback"]["pressure_state"] == "attention"
    assert "callback.failed" in runtime_summary["callback"]["pressure_reasons"]
    assert "callback.overdue" in runtime_summary["callback"]["pressure_reasons"]
    assert "callback.dispatching_stale" in runtime_summary["callback"]["pressure_reasons"]
    assert runtime_summary["callback"]["pending_not_due"] == 0
    assert runtime_summary["callback"]["oldest_due_age_seconds"] >= 600
    assert runtime_summary["retention"]["due_purge"] == 1

    assert callback_runs_response.status_code == 200
    callback_items = callback_runs_response.json()["data"]["items"]
    assert any(
        item["run_id"] == callback_run_id
        and item["callback_last_error_code"] == "runtime.callback_delivery_failed"
        for item in callback_items
    )

    assert cancel_runs_response.status_code == 200
    cancel_items = cancel_runs_response.json()["data"]["items"]
    assert any(item["run_id"] == running_run_id for item in cancel_items)
    assert all(item["run_id"] != queued_run_id for item in cancel_items)

    assert dispatching_runs_response.status_code == 200
    dispatching_items = dispatching_runs_response.json()["data"]["items"]
    assert any(item["run_id"] == dispatching_run_id for item in dispatching_items)

    assert queued_stale_runs_response.status_code == 200
    queued_stale_items = queued_stale_runs_response.json()["data"]["items"]
    assert any(
        item["run_id"] == queued_run_id
        and item["suggested_actions"][0]["action"] == "requeue_stale_queued"
        and item["suggested_actions"][0]["mode"] == "worker_auto"
        for item in queued_stale_items
    )

    assert cancel_stuck_runs_response.status_code == 200
    cancel_stuck_items = cancel_stuck_runs_response.json()["data"]["items"]
    assert any(item["run_id"] == running_run_id for item in cancel_stuck_items)

    assert callback_overdue_runs_response.status_code == 200
    callback_overdue_items = callback_overdue_runs_response.json()["data"]["items"]
    assert any(
        item["run_id"] == overdue_run_id
        and item["suggested_actions"][0]["action"] == "redeliver_failed_callback"
        and item["suggested_actions"][0]["mode"] == "worker_auto"
        for item in callback_overdue_items
    )

    assert guard_events_response.status_code == 200
    guard_items = guard_events_response.json()["data"]["items"]
    assert any(item["event_code"] == "auth.replay_blocked" for item in guard_items)

    assert audit_summary_response.status_code == 200
    audit_summary = audit_summary_response.json()["data"]
    assert audit_summary["totals"]["succeeded"] >= 1
    assert audit_summary["totals"]["error"] >= 1
    assert any(
        item["event_kind"] == "account.upsert" and item["outcome"] == "succeeded"
        for item in audit_summary["groups"]
    )
    assert any(
        item["event_kind"] == "site.activate" and item["outcome"] == "error"
        for item in audit_summary["groups"]
    )

    assert decision_summary_response.status_code == 200
    decision_summary = decision_summary_response.json()["data"]
    assert decision_summary["totals"]["events"] >= 3
    assert decision_summary["totals"]["allow"] >= 3
    assert any(item["decision_code"] == "commercial.allowed" for item in decision_summary["groups"])

    assert abuse_guard_response.status_code == 200
    abuse_guard_payload = abuse_guard_response.json()["data"]
    abuse_guard = abuse_guard_payload["scopes"]
    assert abuse_guard["public_post_site"]["max_requests_per_window"] == 10
    assert any(item["scope_id"] == "site_diag" for item in abuse_guard["public_post_site"]["items"])
    assert abuse_guard["internal_post_token"]["items"][0]["scope_id"] == "internal"
    assert abuse_guard_payload["watchlist_summary"]["highest_severity"] == "critical"
    assert abuse_guard_payload["watchlist_summary"]["request_burst_count"] >= 1
    assert abuse_guard_payload["watchlist_summary"]["reject_storm_count"] >= 1
    public_site_request_item = next(
        item for item in abuse_guard["public_post_site"]["items"] if item["scope_id"] == "site_diag"
    )
    assert public_site_request_item["severity"] == "critical"
    assert public_site_request_item["signal_kind"] == "request_burst"
    assert "request_burst_limit_exceeded" in public_site_request_item["reason_codes"]
    assert public_site_request_item["limit_ratio"] > 1.0
    public_site_cooldown_item = next(
        item
        for item in abuse_guard["public_post_site"]["cooldown_items"]
        if item["scope_id"] == "site_diag"
    )
    assert public_site_cooldown_item["severity"] == "critical"
    assert public_site_cooldown_item["signal_kind"] == "reject_storm"
    assert "reject_storm_limit_exceeded" in public_site_cooldown_item["reason_codes"]
    assert "rejects_include_rate_limits" in public_site_cooldown_item["reason_codes"]
    assert any(
        item["event_code"] == "auth.rate_limit_exceeded"
        for item in public_site_cooldown_item["event_code_breakdown"]
    )
    assert any(
        item["scope_kind"] == REPLAY_SCOPE_PUBLIC_POST_SITE
        and item["scope_id"] == "site_diag"
        and item["signal_kind"] == "reject_storm"
        for item in abuse_guard_payload["watchlist"]
    )
    assert any(
        item["event_code"] == "auth.replay_blocked"
        for item in abuse_guard_payload["guard_event_codes"]
    )
    assert any(
        item["scope_id"] == "site_diag"
        for item in abuse_guard["public_post_site"]["cooldown_items"]
    )

    with get_session(database_url) as session:
        guard_events = list(
            session.scalars(
                select(RuntimeGuardEvent)
                .where(RuntimeGuardEvent.site_id == "site_diag")
                .order_by(RuntimeGuardEvent.id.asc())
            )
        )
    assert any(event.event_code == "auth.replay_blocked" for event in guard_events)

    with get_session(database_url) as session:
        running_run = session.get(RunRecord, running_run_id)
        assert running_run is not None
        running_run.status = "canceled"
        running_run.canceled_at = datetime.now(UTC)
        session.commit()

    canceled_runs_response = client.get(
        "/internal/service/runtime/diagnostics/runs?issue_kind=canceled_recent&site_id=site_diag&limit=5",
        headers=build_internal_headers(),
    )
    assert canceled_runs_response.status_code == 200
    canceled_items = canceled_runs_response.json()["data"]["items"]
    assert any(item["run_id"] == running_run_id for item in canceled_items)

    dispose_engine(database_url)


def test_service_routes_runtime_callback_dispatch_recovery_is_operator_visible(
    tmp_path: Path,
    allow_example_callback_dns: None,
) -> None:
    callback_requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        callback_requests.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(202)

    database_url, client = _build_client(tmp_path)
    _seed_openai_text_model_allowlist(database_url)
    seed_site_auth(
        database_url,
        site_id="site_recovery",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    CommercialService(
        database_url,
        settings=_runtime_service_settings(database_url),
    ).update_site_runtime_callbacks(
        site_id="site_recovery",
        terminal_callback={
            "enabled": True,
            "callback_url": "https://example.com/recover",
            "key_id": "runtime_callback_key",
            "secret": "runtime-callback-secret-for-tests-32b",
            "callback_id": "runtime_terminal",
        },
    )

    payload = {
        "site_id": "site_recovery",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-service-recover-001",
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "terminal_callback_required",
            "polling_interval_sec": 60,
        },
        "input": {"messages": [{"role": "user", "content": "recover callback dispatch"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    execute_response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_recovery",
                idempotency_key="idem-service-recover-001",
                trace_id="traceservicerecover001000000",
                body=body,
            )
        ),
    )

    assert execute_response.status_code == 200
    run_id = str(execute_response.json()["data"]["run_id"])
    trace_id = str(execute_response.json()["data"]["trace_id"])

    with get_session(database_url) as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        run.callback_status = "dispatching"
        run.callback_attempt_count = 1
        run.callback_last_attempt_at = datetime.now(UTC) - timedelta(minutes=6)
        run.callback_next_attempt_at = None
        session.commit()

    summary_before_response = client.get(
        "/internal/service/runtime/diagnostics/summary?site_id=site_recovery&recent_minutes=120",
        headers=build_internal_headers(),
    )
    assert summary_before_response.status_code == 200
    summary_before = summary_before_response.json()
    assert summary_before["meta"]["revision"] == "m8"
    assert summary_before["data"]["callback"]["recoverable_dispatching"] == 1

    worker = RuntimeService(
        database_url,
        settings=_runtime_service_settings(database_url),
        callback_dispatcher=HttpRuntimeCallbackDispatcher(
            transport=httpx.MockTransport(handler),
        ),
        callback_max_attempts=3,
        callback_retry_backoff_seconds=0,
    )
    dispatched = worker.dispatch_pending_callbacks(max_callbacks=1)

    assert dispatched == [
        {
            "run_id": run_id,
            "callback_status": "delivered",
            "trace_id": trace_id,
            "status_code": 202,
        }
    ]
    assert callback_requests[0]["run_id"] == run_id

    audit_response = client.get(
        "/internal/service/audit-events?event_kind=runtime.callback_dispatch_recovered&site_id=site_recovery&limit=5",
        headers=build_internal_headers(),
    )
    assert audit_response.status_code == 200
    audit_items = audit_response.json()["data"]["items"]
    assert any(
        item["scope_id"] == run_id
        and item["payload"]["recovery_action"] == "requeue_pending_after_stale_dispatch_lease"
        for item in audit_items
    )

    dispose_engine(database_url)


def test_service_routes_runtime_backlog_diagnostics_exposes_scope_and_stale_layers(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    _seed_openai_text_model_allowlist(database_url)
    seed_site_auth(
        database_url,
        site_id="site_backlog_a",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )
    seed_site_auth(
        database_url,
        site_id="site_backlog_b",
        key_id="key_backlog_b",
        secret="npcink-cloud-test-secret-backlog-b",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    queued_payload = {
        "site_id": "site_backlog_a",
        "ability_name": "workflow/media_nightly_image_optimize",
        "ability_family": "automation",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-service-backlog-queued-001",
        "input": {"messages": [{"role": "user", "content": "queued backlog"}]},
    }
    running_payload = {
        "site_id": "site_backlog_a",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-service-backlog-running-001",
        "input": {"messages": [{"role": "user", "content": "running backlog"}]},
    }
    other_payload = {
        "site_id": "site_backlog_b",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-service-backlog-other-001",
        "input": {"messages": [{"role": "user", "content": "fresh second scope"}]},
    }

    queued_body = json.dumps(queued_payload).encode("utf-8")
    running_body = json.dumps(running_payload).encode("utf-8")
    other_body = json.dumps(other_payload).encode("utf-8")
    queued_response = client.post(
        "/v1/runtime/execute",
        content=queued_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_backlog_a",
                idempotency_key="idem-service-backlog-queued-001",
                trace_id="traceservicebacklogqueued0001",
                body=queued_body,
            )
        ),
    )
    running_response = client.post(
        "/v1/runtime/execute",
        content=running_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_backlog_a",
                idempotency_key="idem-service-backlog-running-001",
                trace_id="traceservicebacklogrunning001",
                body=running_body,
            )
        ),
    )
    other_response = client.post(
        "/v1/runtime/execute",
        content=other_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_backlog_b",
                key_id="key_backlog_b",
                secret="npcink-cloud-test-secret-backlog-b",
                idempotency_key="idem-service-backlog-other-001",
                trace_id="traceservicebacklogother0001",
                body=other_body,
            )
        ),
    )

    assert queued_response.status_code == 200
    assert running_response.status_code == 200
    assert other_response.status_code == 200

    queued_run_id = str(queued_response.json()["data"]["run_id"])
    running_run_id = str(running_response.json()["data"]["run_id"])
    other_run_id = str(other_response.json()["data"]["run_id"])

    with get_session(database_url) as session:
        queued_run = session.get(RunRecord, queued_run_id)
        running_run = session.get(RunRecord, running_run_id)
        other_run = session.get(RunRecord, other_run_id)
        assert queued_run is not None
        assert running_run is not None
        assert other_run is not None
        queued_run.status = "queued"
        queued_run.started_at = datetime.now(UTC) - timedelta(minutes=9)
        running_run.status = "running"
        running_run.processing_started_at = datetime.now(UTC) - timedelta(minutes=18)
        other_run.status = "queued"
        other_run.started_at = datetime.now(UTC) - timedelta(seconds=45)
        session.commit()

    site_backlog_response = client.get(
        "/internal/service/runtime/diagnostics/backlog?scope_kind=site_id&limit=10",
        headers=build_internal_headers(),
    )
    family_backlog_response = client.get(
        "/internal/service/runtime/diagnostics/backlog?scope_kind=ability_family&limit=10",
        headers=build_internal_headers(),
    )

    assert site_backlog_response.status_code == 200
    site_payload = site_backlog_response.json()
    assert site_payload["meta"]["revision"] == "m1"
    assert site_payload["data"]["totals"]["queued"]["state"] == "stale"
    assert site_payload["data"]["totals"]["running"]["state"] == "stale"
    assert site_payload["data"]["totals"]["bottleneck_state"] == "mixed"
    assert site_payload["data"]["totals"]["lease_recovery_inputs"]["queued_stale_runs"] == 1
    assert site_payload["data"]["totals"]["lease_recovery_inputs"]["running_stale_runs"] == 1
    assert site_payload["data"]["scope_pressure"]["spread_state"] == "isolated"
    assert site_payload["data"]["scope_pressure"]["stale_scope_count"] == 1
    first_site_item = site_payload["data"]["items"][0]
    assert first_site_item["scope_kind"] == "site_id"
    assert first_site_item["scope_id"] == "site_backlog_a"
    assert first_site_item["queued"]["state"] == "stale"
    assert first_site_item["running"]["state"] == "stale"
    assert first_site_item["bottleneck_state"] == "mixed"
    assert "queue.stale" in first_site_item["pressure_reasons"]
    assert "worker.stale" in first_site_item["pressure_reasons"]

    assert family_backlog_response.status_code == 200
    family_payload = family_backlog_response.json()["data"]
    assert family_payload["scope_pressure"]["scope_kind"] == "ability_family"
    assert any(item["scope_id"] == "automation" for item in family_payload["items"])
    assert any(item["scope_id"] == "workflow" for item in family_payload["items"])

    dispose_engine(database_url)


def test_service_routes_enforce_internal_short_window_rate_limit(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "internal_post_rate_limit_window_seconds": 60,
            "internal_post_max_requests_per_window": 1,
        },
    )

    first_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_limit_1", "name": "Limit One"},
        headers=build_internal_headers(idempotency_key="svc-limit-001"),
    )
    second_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_limit_2", "name": "Limit Two"},
        headers=build_internal_headers(idempotency_key="svc-limit-002"),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json()["error_code"] == "auth.rate_limit_exceeded"

    dispose_engine(database_url)


def test_service_routes_enforce_internal_ip_short_window_rate_limit(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "internal_post_rate_limit_window_seconds": 60,
            "internal_post_max_requests_per_window": 10,
            "internal_post_max_requests_per_ip_window": 1,
        },
    )

    first_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_ip_limit_1", "name": "IP Limit One"},
        headers=build_internal_headers(idempotency_key="svc-ip-limit-001"),
    )
    second_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_ip_limit_2", "name": "IP Limit Two"},
        headers=build_internal_headers(idempotency_key="svc-ip-limit-002"),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json()["error_code"] == "auth.rate_limit_exceeded"

    dispose_engine(database_url)


def test_service_routes_enforce_internal_guard_cooldown_after_rejects(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "internal_post_rate_limit_window_seconds": 600,
            "internal_post_max_requests_per_window": 10,
            "internal_post_max_requests_per_ip_window": 10,
            "internal_guard_cooldown_window_seconds": 3600,
            "internal_guard_max_reject_events_per_token_window": 1,
            "internal_guard_max_reject_events_per_ip_window": 1,
        },
    )

    first_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_cooldown_1", "name": "Cooldown One"},
        headers=build_internal_headers(idempotency_key="svc-cooldown-001"),
    )
    replay_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_cooldown_replay", "name": "Cooldown Replay"},
        headers=build_internal_headers(idempotency_key="svc-cooldown-001"),
    )
    cooldown_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_cooldown_2", "name": "Cooldown Two"},
        headers=build_internal_headers(idempotency_key="svc-cooldown-002"),
    )

    assert first_response.status_code == 200
    assert replay_response.status_code == 409
    assert replay_response.json()["error_code"] == "auth.replay_blocked"
    assert cooldown_response.status_code == 429
    assert cooldown_response.json()["error_code"] == "auth.rate_limit_exceeded"

    with get_session(database_url) as session:
        events = list(
            session.scalars(select(RuntimeGuardEvent).order_by(RuntimeGuardEvent.id.asc()))
        )
    assert any(event.event_code == "auth.replay_blocked" for event in events)
    assert any(event.event_code == "auth.rate_limit_exceeded" for event in events)

    dispose_engine(database_url)
