from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.providers.base import (
    ProviderExecutionRequest,
    ProviderExecutionResult,
)
from app.adapters.providers.openai import OpenAIProviderAdapter
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import ServiceAuditEvent, UsageMeterEvent
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
    build_auth_headers,
    build_internal_headers,
    merge_json_headers,
)


class AlphaProviderAdapter(OpenAIProviderAdapter):
    def __init__(self) -> None:
        super().__init__(sample_catalog_profile="free-gpt55")
        self.requests: list[ProviderExecutionRequest] = []

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        self.requests.append(request)
        return ProviderExecutionResult(
            output={
                "output_text": "internal alpha onboarding smoke ok",
                "model_id": request.model_id,
            },
            latency_ms=30,
            tokens_in=7,
            tokens_out=5,
            cost=0.0,
        )


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'internal-alpha-onboarding.sqlite3'}"


def _build_client(tmp_path: Path) -> tuple[str, TestClient, AlphaProviderAdapter]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    provider = AlphaProviderAdapter()
    CatalogService(database_url, providers={"openai": provider}).refresh_catalog()
    settings = Settings(
        _env_file=None,
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        openai_api_key="",
        anthropic_api_key="",
        litellm_provider_enabled=False,
        vllm_provider_enabled=False,
        tei_provider_enabled=False,
        openrouter_provider_enabled=False,
        siliconflow_provider_enabled=False,
        web_search_provider="disabled",
        image_source_provider="disabled",
        site_knowledge_embedding_provider="deterministic",
    )
    return (
        database_url,
        TestClient(create_app(CloudServices(settings=settings, providers={"openai": provider}))),
        provider,
    )


def _origin_headers(*, idempotency_key: str = "") -> dict[str, str]:
    headers = {
        "Origin": "http://testserver",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _internal_headers(idempotency_key: str = "") -> dict[str, str]:
    return build_internal_headers(idempotency_key=idempotency_key)


def _decode_customer_api_key(cloud_api_key: str) -> dict[str, str]:
    assert cloud_api_key.startswith("mak1_")
    encoded = cloud_api_key[len("mak1_") :]
    padded = encoded + ("=" * (-len(encoded) % 4))
    payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    return {
        "site_id": str(payload.get("site_id") or ""),
        "key_id": str(payload.get("key_id") or ""),
        "secret": str(payload.get("secret") or ""),
    }


def _post_internal(
    client: TestClient,
    path: str,
    *,
    json_payload: dict[str, Any] | None = None,
    idempotency_key: str,
) -> dict[str, Any]:
    response = client.post(
        path,
        json=json_payload or {},
        headers=_internal_headers(idempotency_key),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_internal_alpha_onboarding_flow_closes_admin_user_site_key_usage_audit(
    tmp_path: Path,
) -> None:
    database_url, client, provider = _build_client(tmp_path)

    _post_internal(
        client,
        "/internal/service/accounts",
        json_payload={"account_id": "acct_alpha_flow", "name": "Alpha Flow Account"},
        idempotency_key="alpha-account-001",
    )
    _post_internal(
        client,
        "/internal/service/plans",
        json_payload={"plan_id": "plan_pro", "name": "Pro"},
        idempotency_key="alpha-plan-001",
    )
    _post_internal(
        client,
        "/internal/service/plans/plan_pro/versions",
        json_payload={
            "plan_version_id": "plan_pro_v1",
            "version_label": "v1",
            "status": "published",
            "entitlements": {
                "ability_families": ["workflow"],
                "channels": ["openapi"],
                "execution_kinds": ["text"],
                "execution_tiers": ["cloud"],
                "data_classifications": ["internal"],
            },
            "budgets": {
                "max_runs_per_period": 0,
                "max_tokens_per_period": 0,
                "max_cost_per_period": 0,
            },
            "concurrency": {"max_active_runs": 0},
            "metadata": {"package_alias": "pro"},
        },
        idempotency_key="alpha-plan-version-001",
    )
    _post_internal(
        client,
        "/internal/service/admin/accounts/acct_alpha_flow/subscription",
        json_payload={
            "subscription_id": "sub_alpha_flow",
            "account_id": "acct_alpha_flow",
            "plan_id": "plan_pro",
            "plan_version_id": "plan_pro_v1",
            "status": "active",
            "metadata": {"package_alias": "pro"},
        },
        idempotency_key="alpha-subscription-001",
    )
    site_data = _post_internal(
        client,
        "/internal/service/sites",
        json_payload={
            "site_id": "site_alpha_flow",
            "account_id": "acct_alpha_flow",
            "name": "Alpha WordPress Site",
            "status": "provisioning",
            "wordpress_url": "https://alpha.example.test",
        },
        idempotency_key="alpha-site-001",
    )
    site_id = str(site_data["site_id"])
    _post_internal(
        client,
        f"/internal/service/sites/{site_id}/activate",
        idempotency_key="alpha-site-activate-001",
    )
    _post_internal(
        client,
        "/internal/service/accounts/acct_alpha_flow/members",
        json_payload={"email": "alpha@example.com"},
        idempotency_key="alpha-account-members-001",
    )

    login_code_response = client.post(
        "/portal/v1/auth/code/request",
        json={"email": "alpha@example.com"},
        headers={
            **_origin_headers(),
            "X-Npcink-Dev-Login-Code": "1",
        },
    )
    assert login_code_response.status_code == 200, login_code_response.text
    login_code = login_code_response.json()["data"]["code"]
    assert login_code
    verify_response = client.post(
        "/portal/v1/auth/code/verify",
        json={"email": "alpha@example.com", "code": login_code},
        headers=_origin_headers(),
    )
    assert verify_response.status_code == 200, verify_response.text
    portal_session = verify_response.json()["data"]
    assert portal_session["principal_id"].startswith("prn_")
    assert portal_session["identity_type"] == "user"
    assert portal_session["role"] == "user"
    assert portal_session["account_id"] == "acct_alpha_flow"
    assert portal_session["site_id"] == ""
    assert portal_session["sites"][0]["site"]["site_id"] == site_id

    select_response = client.post(
        "/portal/v1/session/site",
        json={"site_id": site_id},
        headers=_origin_headers(),
    )
    assert select_response.status_code == 200, select_response.text
    assert select_response.json()["data"]["site_id"] == site_id

    key_response = client.post(
        f"/portal/v1/sites/{site_id}/api-keys",
        json={
            "label": "Alpha smoke key",
            "scopes": ["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
            "metadata": {"source": "internal_alpha_onboarding_flow"},
        },
        headers=_origin_headers(idempotency_key="alpha-portal-key-001"),
    )
    assert key_response.status_code == 200, key_response.text
    key_data = key_response.json()["data"]
    assert key_data["site_id"] == site_id
    decoded_key = _decode_customer_api_key(str(key_data["cloud_api_key"]))
    assert decoded_key["site_id"] == site_id
    key_id = decoded_key["key_id"]
    secret = decoded_key["secret"]

    execute_payload = {
        "site_id": site_id,
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "data_classification": "internal",
        "input": {"messages": [{"role": "user", "content": "alpha smoke"}]},
        "policy": {"allow_fallback": False},
    }
    body = json.dumps(execute_payload).encode("utf-8")
    execute_response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id=site_id,
                key_id=key_id,
                secret=secret,
                idempotency_key="alpha-runtime-execute-001",
                nonce="alpha-runtime-execute-nonce-001",
                trace_id="alphaexecute00100000000000000",
                body=body,
            )
        ),
    )
    assert execute_response.status_code == 200, execute_response.text
    execute_data = execute_response.json()["data"]
    assert execute_data["status"] == "succeeded"
    assert execute_data["provider_id"] == "openai"
    assert provider.requests
    run_id = execute_data["run_id"]

    admin_account_response = client.get(
        "/internal/service/admin/accounts/acct_alpha_flow",
        headers=_internal_headers(),
    )
    assert admin_account_response.status_code == 200, admin_account_response.text
    admin_account = admin_account_response.json()["data"]
    assert admin_account["trial_readiness"]["status"] == "ready"
    assert admin_account["trial_readiness"]["blocking_codes"] == []
    assert admin_account["trial_readiness"]["summary"]["active_key_site_count"] == 1

    portal_usage_response = client.get(f"/portal/v1/sites/{site_id}/usage-summary")
    assert portal_usage_response.status_code == 200, portal_usage_response.text
    portal_usage = portal_usage_response.json()["data"]
    assert portal_usage["windows"]["rolling_24h"]["runs_total"] == 1
    assert portal_usage["windows"]["rolling_24h"]["provider_calls_total"] == 1

    portal_audit_response = client.get(f"/portal/v1/sites/{site_id}/audit-events")
    assert portal_audit_response.status_code == 200, portal_audit_response.text
    portal_audit_items = portal_audit_response.json()["data"]["items"]
    assert {item["event_kind"] for item in portal_audit_items} >= {
        "site.provision",
        "site_key.issue",
    }

    admin_audit_response = client.get(
        f"/internal/service/audit-events?site_id={site_id}&limit=20",
        headers=_internal_headers(),
    )
    assert admin_audit_response.status_code == 200, admin_audit_response.text
    admin_audit_items = admin_audit_response.json()["data"]["items"]
    assert any(item["actor_kind"] == "principal" for item in admin_audit_items)
    assert any(item["event_kind"] == "site_key.issue" for item in admin_audit_items)

    with get_session(database_url) as session:
        meter_events = list(
            session.scalars(
                select(UsageMeterEvent)
                .where(UsageMeterEvent.run_id == run_id)
                .order_by(UsageMeterEvent.id.asc())
            )
        )
        audit_events = list(
            session.scalars(
                select(ServiceAuditEvent)
                .where(ServiceAuditEvent.site_id == site_id)
                .order_by(ServiceAuditEvent.id.asc())
            )
        )

    assert {event.meter_key for event in meter_events} >= {"runs", "provider_calls"}
    assert {event.event_kind for event in audit_events} >= {"site.provision", "site_key.issue"}

    dispose_engine(database_url)
