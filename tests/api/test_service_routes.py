from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.callbacks.http import HttpRuntimeCallbackDispatcher
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    SUBSCRIPTION_STATUS_PAST_DUE,
    AccountEntitlementSnapshot,
    AccountSubscription,
    BillingSnapshot,
    ProviderCallRecord,
    ReplayReceipt,
    RunRecord,
    RuntimeGuardEvent,
)
from app.core.security import REPLAY_SCOPE_PUBLIC_POST_SITE
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from app.domain.commercial.service import CommercialService, ServiceAuditContext
from app.domain.runtime.service import RuntimeService
from app.workers.ops_cadence import run_due_tasks
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
    build_auth_headers,
    build_internal_headers,
    merge_json_headers,
    seed_site_auth,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'service-routes.sqlite3'}"


def _build_client(
    tmp_path: Path,
    *,
    settings_overrides: dict[str, object] | None = None,
) -> tuple[str, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()

    settings = Settings(
        _env_file=None,
        project_name="Magick AI Cloud Test",
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
        **(settings_overrides or {}),
    )
    return database_url, TestClient(create_app(CloudServices(settings=settings)))


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
            select(AccountSubscription).where(
                AccountSubscription.account_id == "acct_site_advisor"
            )
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

    assert unauthenticated.status_code == 401
    assert runtime_response.status_code == 200
    runtime_payload = runtime_response.json()["data"]
    assert runtime_payload["advisor_version"] == "internal-ai-advisor-v1"
    assert runtime_payload["scope"] == "runtime_operations"
    assert runtime_payload["status"] == "attention"
    assert runtime_payload["evidence"][0]["ref"] == (
        "/internal/service/runtime/diagnostics/summary"
    )
    assert {
        item["action"] for item in runtime_payload["recommended_actions"]
    } >= {"inspect_commercial_entitlement_and_runtime_guard"}
    assert any(
        signal["code"] == "runtime.guard_events"
        and signal["recent_rate_limit_exceeded"] == 1
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

    dispose_engine(database_url)


def test_service_routes_manage_account_site_and_keys(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    account_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_service", "name": "Service Account"},
        headers=build_internal_headers(idempotency_key="svc-account-001"),
    )
    membership_response = client.post(
        "/internal/service/accounts/acct_service/memberships",
        json={"member_ref": "user:admin@example.com", "role": "user_admin"},
        headers=build_internal_headers(idempotency_key="svc-membership-001"),
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
    assert membership_response.status_code == 200
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
    assert onboarding_payload["current_subscription"]["plan_id"] == "plan_free"
    assert onboarding_payload["current_subscription"]["plan_version_id"] == "plan_free_v1"
    assert onboarding_payload["current_subscription"]["package_alias"] == "Free"

    with get_session(database_url) as session:
        generic_subscription = session.scalar(
            select(AccountSubscription).where(
                AccountSubscription.account_id == "acct_ops_only"
            )
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
    assert free_subscription.plan_id == "plan_free"
    assert free_subscription.plan_version_id == "plan_free_v1"
    assert free_snapshot is not None
    assert free_snapshot.plan_version_id == "plan_free_v1"

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


def test_service_routes_admin_account_members_filters_and_detail(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_members", "name": "Members Account"},
        headers=build_internal_headers(idempotency_key="svc-members-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_members",
            "account_id": "acct_members",
            "name": "Members Site",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="svc-members-site-001"),
    )
    client.post(
        "/internal/service/accounts/acct_members/memberships",
        json={
            "member_ref": "user:pending@example.com",
            "role": "user_admin",
            "status": "pending_invite",
            "metadata": {
                "email": "pending@example.com",
                "invite_state": "pending",
                "invite_count": 1,
                "last_delivery_status": "sent",
                "last_invited_at": datetime.now(UTC).isoformat(),
            },
        },
        headers=build_internal_headers(idempotency_key="svc-membership-pending-001"),
    )
    client.post(
        "/internal/service/accounts/acct_members/memberships",
        json={
            "member_ref": "user:active@example.com",
            "role": "user_admin",
            "status": "active",
            "metadata": {
                "email": "active@example.com",
                "invite_state": "accepted",
                "invite_count": 1,
                "last_delivery_status": "sent",
                "last_login_at": datetime.now(UTC).isoformat(),
            },
        },
        headers=build_internal_headers(idempotency_key="svc-membership-active-001"),
    )

    list_response = client.get(
        "/internal/service/admin/accounts/acct_members/members?status=pending_invite",
        headers=build_internal_headers(),
    )
    assert list_response.status_code == 200
    items = list_response.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["member_ref"] == "user:pending@example.com"
    assert items[0]["invite_state"] == "pending"
    assert items[0]["last_delivery_status"] == "sent"
    assert items[0]["accessible_sites"][0]["site_id"] == "site_members"

    never_logged_in_response = client.get(
        "/internal/service/admin/accounts/acct_members/members?never_logged_in=true",
        headers=build_internal_headers(),
    )
    assert never_logged_in_response.status_code == 200
    never_logged_items = never_logged_in_response.json()["data"]["items"]
    assert {item["member_ref"] for item in never_logged_items} == {"user:pending@example.com"}

    detail_response = client.get(
        "/internal/service/admin/accounts/acct_members/members/user:active@example.com",
        headers=build_internal_headers(),
    )
    assert detail_response.status_code == 200
    membership = detail_response.json()["data"]["membership"]
    assert membership["member_ref"] == "user:active@example.com"
    assert membership["last_login_at"] != ""
    assert membership["invite_state"] == "accepted"

    dispose_engine(database_url)


def test_service_routes_admin_account_member_plan_coverage_summary(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_coverage", "name": "Coverage Account"},
        headers=build_internal_headers(idempotency_key="svc-coverage-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_covered",
            "account_id": "acct_coverage",
            "name": "Covered Site",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="svc-coverage-site-covered-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_uncovered",
            "account_id": "acct_coverage",
            "name": "Uncovered Site",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="svc-coverage-site-uncovered-001"),
    )
    client.post(
        "/internal/service/accounts/acct_coverage/memberships",
        json={"member_ref": "user:admin@example.com", "role": "user_admin", "metadata": {"email": "admin@example.com"}},
        headers=build_internal_headers(idempotency_key="svc-coverage-membership-admin-001"),
    )
    client.post(
        "/internal/service/accounts/acct_coverage/memberships",
        json={"member_ref": "user:member@example.com", "role": "user_admin", "metadata": {"email": "member@example.com"}},
        headers=build_internal_headers(idempotency_key="svc-coverage-membership-member-001"),
    )
    client.post(
        "/internal/service/plans",
        json={"plan_id": "plan_basic", "name": "Basic"},
        headers=build_internal_headers(idempotency_key="svc-coverage-plan-001"),
    )
    client.post(
        "/internal/service/plans/plan_basic/versions",
        json={
            "plan_version_id": "plan_basic_v1",
            "version_label": "v1",
            "status": "published",
            "budgets": {"max_runs_per_period": 1000},
        },
        headers=build_internal_headers(idempotency_key="svc-coverage-plan-version-001"),
    )
    client.post(
        "/internal/service/admin/accounts/acct_coverage/subscription",
        json={
            "subscription_id": "sub_covered",
            "account_id": "acct_coverage",
            "plan_id": "plan_basic",
            "plan_version_id": "plan_basic_v1",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="svc-coverage-bind-001"),
    )

    response = client.get(
        "/internal/service/admin/accounts/acct_coverage/member-plan-coverage",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["account"]["account_id"] == "acct_coverage"
    assert data["summary"]["member_count"] == 2
    assert data["summary"]["covered_member_count"] == 2
    assert data["summary"]["sites_needing_follow_up_count"] == 0

    admin_member = next(item for item in data["members"] if item["member_ref"] == "user:admin@example.com")
    assert admin_member["identity_type"] == "user_admin"
    assert admin_member["role"] == "user_admin"
    assert admin_member["covered_site_count"] == 2
    assert admin_member["sites_needing_follow_up_count"] == 0
    covered_site = next(site for site in admin_member["accessible_sites"] if site["site_id"] == "site_covered")
    assert covered_site["covered"] is True
    assert covered_site["plan_id"] == "plan_basic"
    assert covered_site["plan_version_id"] == "plan_basic_v1"
    assert covered_site["coverage"]["status"] == "active"

    dispose_engine(database_url)


def test_service_routes_bind_subscription_and_rebuild_billing_snapshot(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)

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
        json={"plan_id": "plan_growth", "name": "Growth"},
        headers=build_internal_headers(idempotency_key="svc-plan-101"),
    )
    version_response = client.post(
        "/internal/service/plans/plan_growth/versions",
        json={
            "plan_version_id": "plan_growth_v1",
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
            "subscription_id": "sub_growth",
            "account_id": "acct_billing",
            "plan_id": "plan_growth",
            "plan_version_id": "plan_growth_v1",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="svc-subscription-101"),
    )
    topup_response = client.post(
        "/internal/service/subscriptions/sub_growth/topup",
        json={
            "target_period_start_at": subscription_response.json()["data"]["subscription"]["current_period_start_at"],
            "target_period_end_at": subscription_response.json()["data"]["subscription"]["current_period_end_at"],
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
    assert (
        version_response.json()["data"]["receipt"]["event_kind"]
        == "plan_version.publish"
    )
    assert (
        version_response.json()["data"]["receipt"]["audit_filters"]["event_kind"]
        == "plan_version.publish"
    )
    assert subscription_response.status_code == 200
    assert subscription_response.json()["data"]["receipt"]["event_kind"] == "subscription.upsert"
    assert subscription_response.json()["data"]["receipt"]["audit_filters"]["account_id"] == "acct_billing"
    assert topup_response.status_code == 200
    topup_payload = topup_response.json()["data"]
    assert topup_payload["receipt"]["event_kind"] == "subscription.topup"
    assert topup_payload["topup"]["pack_id"] == ""
    assert topup_payload["topup"]["reason"] == "operator_overage_buffer"
    assert topup_payload["entitlement_snapshot"]["budgets"]["max_runs_per_period"] == 10010.0
    assert topup_payload["entitlement_snapshot"]["budgets"]["max_tokens_per_period"] == 2005000.0
    assert topup_payload["entitlement_snapshot"]["budgets"]["max_cost_per_period"] == 99.0
    assert topup_payload["topup_summary"]["current_period_count"] == 1
    assert topup_payload["topup_summary"]["current_period_totals"]["runs"] == 10000.0
    assert topup_payload["topup_summary"]["current_period_totals"]["tokens"] == 2000000.0
    assert topup_payload["topup_summary"]["current_period_totals"]["cost"] == 99.0
    assert topup_payload["billing_snapshot_refresh"]["status"] == "refreshed"
    assert topup_payload["billing_snapshot_refresh"]["site_count"] == 1
    assert topup_payload["billing_snapshot_refresh"]["snapshots"][0]["site_id"] == "site_billing"
    assert topup_payload["billing_snapshot_status"]["status"] == "fresh"
    assert topup_payload["billing_snapshot_status"]["next_action"] is None

    admin_subscription_response = client.get(
        "/internal/service/admin/subscriptions/sub_growth",
        headers=build_internal_headers(),
    )
    assert admin_subscription_response.status_code == 200
    admin_subscription = admin_subscription_response.json()["data"]
    assert admin_subscription["topup_summary"]["count"] == 1
    assert admin_subscription["topup_summary"]["latest"]["pack_id"] == ""
    assert admin_subscription["topup_summary"]["latest"]["reason"] == "operator_overage_buffer"
    assert admin_subscription["topup_summary"]["current_period_totals"]["cost"] == 99.0
    assert admin_subscription["budget_headroom"]["base_budget"]["runs"] == 10.0
    assert admin_subscription["budget_headroom"]["current_period_topup_delta"]["runs"] == 10000.0
    assert admin_subscription["budget_headroom"]["effective_budget"]["runs"] == 10010.0
    assert admin_subscription["billing_snapshot_status"]["status"] == "fresh"
    assert admin_subscription["billing_snapshot_status"]["fresh_site_count"] == 1
    assert admin_subscription["billing_snapshot_status"]["next_action"] is None

    rebuild_subscription_response = client.post(
        "/internal/service/admin/subscriptions/sub_growth/billing-snapshots/rebuild",
        headers=build_internal_headers(idempotency_key="svc-subscription-rebuild-101"),
    )
    assert rebuild_subscription_response.status_code == 200
    rebuild_payload = rebuild_subscription_response.json()["data"]
    assert rebuild_payload["billing_snapshot_refresh"]["status"] == "refreshed"
    assert rebuild_payload["billing_snapshot_refresh"]["site_count"] == 1
    assert rebuild_payload["billing_snapshot_status"]["status"] == "fresh"
    assert rebuild_payload["billing_snapshot_status"]["next_action"] is None

    execute_payload = {
        "site_id": "site_billing",
        "ability_name": "magick-ai/workflows/generate-post-draft",
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
    assert rebuild_response.json()["data"]["breakdown"]["ability_families"]["workflow"][
        "runs"
    ] == 1.0
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
        item["decision_code"] in {"commercial.subscription_inactive", "commercial.entitlement_denied"}
        for item in decision_items
    )

    dispose_engine(database_url)


def test_service_routes_admin_read_facade(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_admin", "name": "Admin Account"},
        headers=build_internal_headers(idempotency_key="svc-admin-account-001"),
    )
    client.post(
        "/internal/service/accounts/acct_admin/memberships",
        json={"member_ref": "user:admin@example.com", "role": "user_admin"},
        headers=build_internal_headers(idempotency_key="svc-admin-membership-001"),
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
        "ability_name": "magick-ai/workflows/generate-post-draft",
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
    filtered_accounts_response = client.get(
        "/internal/service/admin/accounts?member_ref=user:admin@example.com",
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
    assert overview["counts"]["memberships_active"] == 1
    assert overview["counts"]["sites_active"] == 1
    assert overview["counts"]["site_keys_active"] == 1
    assert overview["recent_usage"]["event_count"] >= 1
    assert "runtime_diagnostics" in overview
    assert overview["runtime_operator_explanations"]
    assert len(overview["expiring_subscriptions"]["items"]) >= 1
    assert any(
        item["subscription"]["account_id"] == "acct_admin"
        for item in overview["expiring_subscriptions"]["items"]
    )
    assert overview["expiring_subscriptions"]["within_30_days_expires_before"]
    assert overview["attention_subscriptions"] == []

    assert accounts_response.status_code == 200
    accounts = accounts_response.json()["data"]["items"]
    assert len(accounts) == 1
    assert accounts[0]["account"]["account_id"] == "acct_admin"
    assert accounts[0]["member_count"] == 1
    assert accounts[0]["site_count"] == 1
    assert accounts[0]["active_subscription_count"] >= 1
    assert accounts[0]["display_package_label"] == "Basic"
    assert accounts[0]["package_kind"] == "tier_package"
    assert accounts[0]["coverage_state"] == "covered"
    assert accounts[0]["primary_subscription_id"] == "sub_admin"
    assert filtered_accounts_response.status_code == 200
    assert filtered_accounts_response.json()["data"]["filters"]["member_ref"] == "user:admin@example.com"
    assert len(filtered_accounts_response.json()["data"]["items"]) == 1
    assert package_filtered_accounts_response.status_code == 200
    assert package_filtered_accounts_response.json()["data"]["filters"]["coverage_state"] == "covered"
    assert package_filtered_accounts_response.json()["data"]["filters"]["package_kind"] == "tier_package"
    assert package_filtered_accounts_response.json()["data"]["filters"]["top_plan_id"] == "plan_admin"
    assert len(package_filtered_accounts_response.json()["data"]["items"]) == 1

    assert account_detail_response.status_code == 200
    account_detail = account_detail_response.json()["data"]
    assert len(account_detail["memberships"]) == 1
    assert len(account_detail["sites"]) == 1
    assert len(account_detail["subscriptions"]) >= 1

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
    assert all(item["account"]["account_id"] == "acct_admin" for item in subscriptions if item.get("account"))
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
    assert [item["tier_id"] for item in tier_templates] == ["starter", "pro", "agency"]
    assert tier_templates[0]["package_alias"] == "Free"
    assert tier_templates[1]["monthly_included_points"] == 10000
    assert tier_templates[2]["concurrency_template"]["max_active_runs"] == 6
    assert tier_templates[0]["canonical_shell"]["entitlements"]["execution_tiers"] == ["cloud"]
    assert tier_templates[1]["canonical_shell"]["budgets"]["max_runs_per_period"] == 10000
    assert tier_templates[2]["canonical_shell"]["metadata"]["max_batch_items"] == 100
    admin_plan_summary = next(item for item in plans if item["plan"]["plan_id"] == "plan_admin")
    assert admin_plan_summary["tier_summary"]["tier_id"] == "pro"
    assert admin_plan_summary["tier_summary"]["label"] == "Pro"
    assert admin_plan_summary["tier_summary"]["package_alias"] == "Basic"
    assert admin_plan_summary["tier_summary"]["monthly_included_points"] == 10000
    assert admin_plan_summary["tier_summary"]["site_limit"] == 5
    assert admin_plan_summary["tier_summary"]["max_batch_items"] == 10
    assert admin_plan_summary["tier_summary"]["automation_enabled"] is True
    assert admin_plan_summary["tier_summary"]["api_enabled"] is True
    assert admin_plan_summary["tier_summary"]["openclaw_enabled"] is True
    assert "core capabilities stay available across packages" in admin_plan_summary["tier_summary"]["package_operator_note"].lower()
    assert admin_plan_summary["latest_version"]["plan_version_id"] == "plan_admin_v1"
    assert admin_plan_summary["published_version_count"] == 1
    assert plan_detail_response.status_code == 200
    plan_detail = plan_detail_response.json()["data"]
    assert plan_detail["plan"]["plan_id"] == "plan_admin"
    assert plan_detail["tier_summary"]["tier_id"] == "pro"
    assert plan_detail["tier_summary"]["package_alias"] == "Basic"
    assert plan_detail["tier_summary"]["monthly_included_points"] == 10000
    assert plan_detail["tier_summary"]["site_limit"] == 5
    assert plan_detail["tier_summary"]["max_batch_items"] == 10
    assert plan_detail["tier_summary"]["automation_enabled"] is True
    assert plan_detail["tier_summary"]["api_enabled"] is True
    assert plan_detail["tier_summary"]["openclaw_enabled"] is True
    assert plan_detail["tier_summary"]["concurrency_template"]["max_active_runs"] == 2
    assert plan_detail["latest_version"]["plan_version_id"] == "plan_admin_v1"
    assert plan_detail["package_fit_cues"]
    cue_codes = {item["code"] for item in plan_detail["package_fit_cues"]}
    assert "package_fit.cost_ceiling_missing" in cue_codes
    assert "package_fit.max_runs_per_period.too_conservative" in cue_codes
    assert "package_fit.max_tokens_per_period.too_conservative" in cue_codes
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
        filtered_subscriptions_response.json()["data"]["items"][0]["billing_snapshot_status"]["status"]
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
                "plan_id": "starter_ops",
                "name": "Starter Ops",
                "metadata": {"tier_id": "starter"},
            },
            headers=build_internal_headers(idempotency_key="svc-tier-plan-starter-001"),
        ),
        client.post(
            "/internal/service/plans",
            json={"plan_id": "plan_version_tier", "name": "Version Tier Plan"},
            headers=build_internal_headers(idempotency_key="svc-tier-plan-version-001"),
        ),
        client.post(
            "/internal/service/plans",
            json={"plan_id": "agency_growth", "name": "Agency Growth"},
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
            "/internal/service/plans/starter_ops/versions",
            json={
                "plan_version_id": "starter_ops_v1",
                "version_label": "v1",
                "budgets": {
                    "max_runs_per_period": 100,
                    "max_tokens_per_period": 50_000,
                },
                "concurrency": {"max_active_runs": 1},
                "metadata": {"tier_id": "agency"},
            },
            headers=build_internal_headers(idempotency_key="svc-tier-version-starter-001"),
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
            "/internal/service/plans/agency_growth/versions",
            json={
                "plan_version_id": "agency_growth_v1",
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
    starter_detail_response = client.get(
        "/internal/service/admin/plans/starter_ops",
        headers=build_internal_headers(),
    )
    version_tier_detail_response = client.get(
        "/internal/service/admin/plans/plan_version_tier",
        headers=build_internal_headers(),
    )
    name_tier_detail_response = client.get(
        "/internal/service/admin/plans/agency_growth",
        headers=build_internal_headers(),
    )
    default_tier_detail_response = client.get(
        "/internal/service/admin/plans/general_ops",
        headers=build_internal_headers(),
    )

    assert plans_response.status_code == 200
    plans = {
        item["plan"]["plan_id"]: item
        for item in plans_response.json()["data"]["items"]
    }
    assert plans["starter_ops"]["tier_summary"]["tier_id"] == "starter"
    assert plans["starter_ops"]["tier_summary"]["package_alias"] == "Free"
    assert plans["starter_ops"]["tier_summary"]["monthly_included_points"] == 500
    assert plans["starter_ops"]["tier_summary"]["max_batch_items"] == 0
    assert plans["starter_ops"]["tier_summary"]["automation_enabled"] is True
    assert plans["starter_ops"]["tier_summary"]["api_enabled"] is True
    assert plans["starter_ops"]["tier_summary"]["openclaw_enabled"] is True
    assert plans["plan_version_tier"]["tier_summary"]["tier_id"] == "agency"
    assert plans["plan_version_tier"]["tier_summary"]["package_alias"] == "Bulk"
    assert plans["plan_version_tier"]["tier_summary"]["monthly_included_points"] == 50000
    assert plans["plan_version_tier"]["tier_summary"]["max_batch_items"] == 100
    assert plans["plan_version_tier"]["tier_summary"]["openclaw_enabled"] is True
    assert plans["agency_growth"]["tier_summary"]["tier_id"] == "agency"
    assert plans["general_ops"]["tier_summary"]["tier_id"] == "pro"

    assert starter_detail_response.status_code == 200
    starter_detail = starter_detail_response.json()["data"]
    assert starter_detail["tier_summary"]["tier_id"] == "starter"
    assert starter_detail["tier_summary"]["package_alias"] == "Free"
    assert starter_detail["tier_summary"]["monthly_included_points"] == 500
    starter_cue_codes = {item["code"] for item in starter_detail["package_fit_cues"]}
    assert "package_fit.cost_ceiling_missing" in starter_cue_codes
    assert "package_fit.max_runs_per_period.too_conservative" in starter_cue_codes
    assert "package_fit.max_tokens_per_period.too_conservative" in starter_cue_codes

    assert version_tier_detail_response.status_code == 200
    version_tier_detail = version_tier_detail_response.json()["data"]
    assert version_tier_detail["tier_summary"]["tier_id"] == "agency"
    assert version_tier_detail["tier_summary"]["package_alias"] == "Bulk"
    assert version_tier_detail["tier_summary"]["openclaw_enabled"] is True

    assert name_tier_detail_response.status_code == 200
    name_tier_detail = name_tier_detail_response.json()["data"]
    assert name_tier_detail["tier_summary"]["tier_id"] == "agency"

    assert default_tier_detail_response.status_code == 200
    default_tier_detail = default_tier_detail_response.json()["data"]
    assert default_tier_detail["tier_summary"]["tier_id"] == "pro"
    assert default_tier_detail["tier_summary"]["package_alias"] == "Basic"
    assert default_tier_detail["tier_summary"]["automation_enabled"] is True
    assert default_tier_detail["tier_summary"]["api_enabled"] is True
    assert default_tier_detail["tier_summary"]["openclaw_enabled"] is True
    assert default_tier_detail["package_fit_cues"][0]["code"] == "package_fit.within_band"

    dispose_engine(database_url)


def test_service_routes_removed_platform_admin_identity_routes(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    response = client.post(
        "/internal/service/platform-admin-identities",
        json={
            "admin_ref": "platform:founder",
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


def test_service_routes_inspect_commercial_policy_and_reconciliation(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)

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
    assert (
        version_response.json()["data"]["policy"]["budgets"]["runs"]["grace_requests"] == 1
    )
    assert bind_response.status_code == 200

    execute_payload = {
        "site_id": "site_policy",
        "ability_name": "magick-ai/workflows/generate-post-draft",
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
    assert (
        policy_response.json()["data"]["policy"]["budgets"]["runs"]["grace_requests"] == 1
    )
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
    seed_site_auth(
        database_url,
        site_id="site_cleanup",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    payload = {
        "site_id": "site_cleanup",
        "ability_name": "magick-ai/workflows/generate-post-draft",
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
    assert payload["tracing"]["service_name"] == "magick-ai-cloud"
    assert isinstance(payload["tracing"]["trace_sink_configured"], bool)
    assert payload["feature_flags"]["summary"]["flags_total"] >= 1
    assert payload["feature_flags"]["summary"]["overridden_total"] == 0
    assert any(
        item["key"] == "admin.commercial_ops.enabled"
        for item in payload["feature_flags"]["items"]
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
        "ability_name": "magick-ai/workflows/generate-post-draft",
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
        "ability_name": "magick-ai/workflows/generate-post-draft",
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
    assert any(
        item["decision_code"] == "commercial.allowed" for item in decision_summary["groups"]
    )

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
) -> None:
    callback_requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        callback_requests.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(202)

    database_url, client = _build_client(tmp_path)
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
        "ability_name": "magick-ai/workflows/generate-post-draft",
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
    seed_site_auth(
        database_url,
        site_id="site_backlog_a",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )
    seed_site_auth(
        database_url,
        site_id="site_backlog_b",
        key_id="key_backlog_b",
        secret="magick-cloud-test-secret-backlog-b",
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
        "ability_name": "magick-ai/workflows/generate-post-draft",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-service-backlog-running-001",
        "input": {"messages": [{"role": "user", "content": "running backlog"}]},
    }
    other_payload = {
        "site_id": "site_backlog_b",
        "ability_name": "magick-ai/workflows/generate-post-draft",
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
                secret="magick-cloud-test-secret-backlog-b",
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
            session.scalars(
                select(RuntimeGuardEvent).order_by(RuntimeGuardEvent.id.asc())
            )
        )
    assert any(event.event_code == "auth.replay_blocked" for event in events)
    assert any(event.event_code == "auth.rate_limit_exceeded" for event in events)

    dispose_engine(database_url)
