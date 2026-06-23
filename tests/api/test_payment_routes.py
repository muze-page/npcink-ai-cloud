from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    PAYMENT_ORDER_STATUS_PAID,
    PAYMENT_ORDER_STATUS_REFUNDED,
    PAYMENT_REFUND_STATUS_SUCCEEDED,
    CreditLedgerEntry,
)
from app.core.services import CloudServices
from app.domain.commercial.service import CommercialService
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
    build_internal_headers,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'payment-routes.sqlite3'}"


def _settings(database_url: str) -> Settings:
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
        web_search_provider="disabled",
        site_knowledge_embedding_provider="deterministic",
    )


def _client(tmp_path: Path) -> tuple[str, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)
    service = CommercialService(database_url, settings=settings)
    service.upsert_account(account_id="acct_route_pay", name="Route payment account")
    service.upsert_plan(plan_id="plan_route_pro", name="Route Pro")
    service.publish_plan_version(
        plan_id="plan_route_pro",
        plan_version_id="plan_route_pro_v1",
        version_label="v1",
        currency="CNY",
    )
    return database_url, TestClient(create_app(CloudServices(settings=settings)))


def test_internal_payment_routes_open_and_revoke_entitlement(tmp_path: Path) -> None:
    database_url, client = _client(tmp_path)

    order_response = client.post(
        "/internal/service/payments/orders",
        headers=build_internal_headers(idempotency_key="route-payment-order"),
        json={
            "account_id": "acct_route_pay",
            "plan_id": "plan_route_pro",
            "plan_version_id": "plan_route_pro_v1",
            "amount": 199.0,
            "currency": "CNY",
            "provider": "alipay",
            "subject": "Route Pro monthly",
        },
    )
    assert order_response.status_code == 200
    order = order_response.json()["data"]

    paid_response = client.post(
        f"/internal/service/payments/orders/{order['order_id']}/mark-paid",
        headers=build_internal_headers(idempotency_key="route-payment-paid"),
        json={
            "provider_trade_no": "202606122200000009",
            "provider_event_id": "route-paid-event",
            "amount": 199.0,
            "raw_event": {"trade_status": "TRADE_SUCCESS"},
        },
    )
    assert paid_response.status_code == 200
    assert paid_response.json()["data"]["order"]["status"] == PAYMENT_ORDER_STATUS_PAID
    assert paid_response.json()["data"]["subscription"]["subscription_id"]

    credit_packs_response = client.get(
        "/internal/service/payments/credit-packs",
        headers=build_internal_headers(),
    )
    assert credit_packs_response.status_code == 200
    assert {item["pack_id"] for item in credit_packs_response.json()["data"]["items"]} >= {
        "pack_small",
        "pack_medium",
        "pack_large",
    }

    credit_pack_order_response = client.post(
        "/internal/service/payments/credit-pack-orders",
        headers=build_internal_headers(idempotency_key="route-credit-pack-order"),
        json={
            "account_id": "acct_route_pay",
            "pack_id": "pack_small",
            "provider": "alipay",
        },
    )
    assert credit_pack_order_response.status_code == 200, credit_pack_order_response.text
    credit_pack_order = credit_pack_order_response.json()["data"]
    assert credit_pack_order["purchase_kind"] == "credit_pack"
    assert credit_pack_order["credit_pack"]["ai_credits"] == 10000

    credit_pack_paid_response = client.post(
        f"/internal/service/payments/orders/{credit_pack_order['order_id']}/mark-paid",
        headers=build_internal_headers(idempotency_key="route-credit-pack-paid"),
        json={
            "provider_trade_no": "202606230000000003",
            "provider_event_id": "route-credit-pack-paid-event",
            "amount": 99.0,
        },
    )
    assert credit_pack_paid_response.status_code == 200, credit_pack_paid_response.text
    assert (
        credit_pack_paid_response.json()["data"]["credit_ledger_entry"]["credit_delta"]
        == 10000.0
    )
    with get_session(database_url) as session:
        assert session.scalar(
            select(CreditLedgerEntry).where(
                CreditLedgerEntry.source_type == "credit_pack_purchase"
            )
        ) is not None

    refund_response = client.post(
        f"/internal/service/payments/orders/{order['order_id']}/refunds",
        headers=build_internal_headers(idempotency_key="route-payment-refund"),
        json={"amount": 199.0, "reason": "14-day refund"},
    )
    assert refund_response.status_code == 200
    refund = refund_response.json()["data"]

    refund_success_response = client.post(
        f"/internal/service/payments/refunds/{refund['refund_id']}/mark-succeeded",
        headers=build_internal_headers(idempotency_key="route-refund-succeeded"),
        json={
            "provider_refund_no": "20260612REFUND009",
            "provider_event_id": "route-refund-event",
            "raw_event": {"refund_status": "REFUND_SUCCESS"},
        },
    )
    assert refund_success_response.status_code == 200
    data = refund_success_response.json()["data"]
    assert data["order"]["status"] == PAYMENT_ORDER_STATUS_REFUNDED
    assert data["refund"]["status"] == PAYMENT_REFUND_STATUS_SUCCEEDED
    assert data["revoked_subscription"]["subscription_id"]

    dispose_engine(database_url)
