from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    ENTITLEMENT_SNAPSHOT_STATUS_SUPERSEDED,
    PAYMENT_ORDER_STATUS_PAID,
    PAYMENT_ORDER_STATUS_PENDING,
    PAYMENT_ORDER_STATUS_REFUNDED,
    PAYMENT_REFUND_STATUS_REQUESTED,
    PAYMENT_REFUND_STATUS_SUCCEEDED,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_CANCELED,
    AccountEntitlementSnapshot,
    AccountSubscription,
    CreditLedgerEntry,
    PaymentEvent,
    PaymentOrder,
    PaymentRefund,
)
from app.domain.commercial.service import CommercialService, ServiceAuditContext
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'payment-service.sqlite3'}"


def _service(database_url: str) -> CommercialService:
    return CommercialService(
        database_url,
        settings=Settings(
            _env_file=None,
            environment="test",
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
            internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
            admin_session_secret=TEST_ADMIN_SESSION_SECRET,
            portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        ),
    )


def _seed_account_and_plan(service: CommercialService) -> None:
    service.upsert_account(account_id="acct_pay", name="Payment account")
    service.upsert_plan(plan_id="plan_pro", name="Pro")
    service.publish_plan_version(
        plan_id="plan_pro",
        plan_version_id="plan_pro_v1",
        version_label="v1",
        currency="CNY",
        budgets_json={
            "max_runs_per_period": 200,
            "max_tokens_per_period": 100000,
            "max_cost_per_period": 50.0,
        },
        concurrency_json={"max_active_runs": 4},
    )


def _audit(idempotency_key: str) -> ServiceAuditContext:
    return ServiceAuditContext(
        trace_id="tracepaymentservice0000000000000",
        idempotency_key=idempotency_key,
        method="POST",
        path="/internal/service/payments",
        actor_kind="internal_token",
        actor_ref="test",
    )


def test_payment_order_does_not_grant_entitlement_until_paid(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    _seed_account_and_plan(service)

    order = service.create_payment_order(
        account_id="acct_pay",
        plan_id="plan_pro",
        plan_version_id="plan_pro_v1",
        amount=199.0,
        currency="CNY",
        provider="alipay",
        subject="Pro monthly",
        audit_context=_audit("payment-order-create"),
    )

    assert order["status"] == PAYMENT_ORDER_STATUS_PENDING
    assert order["provider"] == "alipay"
    with get_session(database_url) as session:
        assert session.scalar(select(PaymentOrder)).status == PAYMENT_ORDER_STATUS_PENDING
        assert session.scalar(select(AccountSubscription)) is None
        assert session.scalar(select(AccountEntitlementSnapshot)) is None

    dispose_engine(database_url)


def test_payment_success_grants_subscription_and_is_idempotent(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    _seed_account_and_plan(service)
    order = service.create_payment_order(
        account_id="acct_pay",
        plan_id="plan_pro",
        plan_version_id="plan_pro_v1",
        amount=199.0,
        audit_context=_audit("payment-success-order"),
    )

    paid = service.mark_payment_order_paid(
        order_id=str(order["order_id"]),
        provider_trade_no="202606122200000001",
        provider_event_id="alipay-notify-paid-1",
        amount=199.0,
        raw_event={
            "trade_status": "TRADE_SUCCESS",
            "notify_token": "must-not-persist",
            "signature": "must-not-persist",
            "nested": {"api_key": "must-not-persist"},
        },
        audit_context=_audit("payment-success-event"),
    )
    paid_again = service.mark_payment_order_paid(
        order_id=str(order["order_id"]),
        provider_trade_no="202606122200000001",
        provider_event_id="alipay-notify-paid-1",
        amount=199.0,
        raw_event={"trade_status": "TRADE_SUCCESS"},
        audit_context=_audit("payment-success-event"),
    )

    assert paid["order"]["status"] == PAYMENT_ORDER_STATUS_PAID
    assert paid["subscription"]["status"] == SUBSCRIPTION_STATUS_ACTIVE
    assert paid_again["subscription"]["subscription_id"] == paid["subscription"]["subscription_id"]
    with get_session(database_url) as session:
        assert session.scalar(select(PaymentOrder)).subscription_id == (
            paid["subscription"]["subscription_id"]
        )
        assert len(list(session.scalars(select(AccountSubscription)))) == 1
        assert len(list(session.scalars(select(AccountEntitlementSnapshot)))) == 1
        events = list(session.scalars(select(PaymentEvent)))
        assert len(events) == 1
        assert events[0].payload_json == {
            "trade_status": "TRADE_SUCCESS",
            "notify_token": "[redacted]",
            "signature": "[redacted]",
            "nested": {"api_key": "[redacted]"},
        }

    dispose_engine(database_url)


def test_full_refund_success_cancels_subscription_and_supersedes_entitlement(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    _seed_account_and_plan(service)
    order = service.create_payment_order(
        account_id="acct_pay",
        plan_id="plan_pro",
        plan_version_id="plan_pro_v1",
        amount=199.0,
        audit_context=_audit("payment-refund-order"),
    )
    service.mark_payment_order_paid(
        order_id=str(order["order_id"]),
        provider_event_id="alipay-notify-paid-refund-flow",
        amount=199.0,
        audit_context=_audit("payment-refund-paid"),
    )

    refund = service.request_payment_refund(
        order_id=str(order["order_id"]),
        amount=199.0,
        reason="14-day refund",
        audit_context=_audit("payment-refund-request"),
    )
    result = service.mark_payment_refund_succeeded(
        refund_id=str(refund["refund_id"]),
        provider_refund_no="20260612REFUND0001",
        provider_event_id="alipay-refund-success-1",
        raw_event={"refund_status": "REFUND_SUCCESS"},
        audit_context=_audit("payment-refund-success"),
    )

    assert refund["status"] == PAYMENT_REFUND_STATUS_REQUESTED
    assert result["order"]["status"] == PAYMENT_ORDER_STATUS_REFUNDED
    assert result["refund"]["status"] == PAYMENT_REFUND_STATUS_SUCCEEDED
    assert result["revoked_subscription"]["status"] == SUBSCRIPTION_STATUS_CANCELED
    with get_session(database_url) as session:
        subscription = session.scalar(select(AccountSubscription))
        assert subscription is not None
        assert subscription.status == SUBSCRIPTION_STATUS_CANCELED
        snapshot = session.scalar(select(AccountEntitlementSnapshot))
        assert snapshot is not None
        assert snapshot.status == ENTITLEMENT_SNAPSHOT_STATUS_SUPERSEDED
        order_record = session.scalar(select(PaymentOrder))
        assert order_record is not None
        assert order_record.status == PAYMENT_ORDER_STATUS_REFUNDED
        refund_record = session.scalar(select(PaymentRefund))
        assert refund_record is not None
        assert refund_record.status == PAYMENT_REFUND_STATUS_SUCCEEDED

    dispose_engine(database_url)


def test_credit_pack_payment_success_grants_ai_credits_once(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    _seed_account_and_plan(service)
    package_order = service.create_payment_order(
        account_id="acct_pay",
        plan_id="plan_pro",
        plan_version_id="plan_pro_v1",
        amount=199.0,
        audit_context=_audit("credit-pack-base-order"),
    )
    base_paid = service.mark_payment_order_paid(
        order_id=str(package_order["order_id"]),
        provider_event_id="alipay-base-paid",
        amount=199.0,
        audit_context=_audit("credit-pack-base-paid"),
    )

    order = service.create_credit_pack_payment_order(
        account_id="acct_pay",
        pack_id="pack_small",
        provider="alipay",
        audit_context=_audit("credit-pack-order"),
    )
    paid = service.mark_payment_order_paid(
        order_id=str(order["order_id"]),
        provider_trade_no="202606230000000001",
        provider_event_id="alipay-credit-pack-paid",
        amount=99.0,
        raw_event={"trade_status": "TRADE_SUCCESS"},
        audit_context=_audit("credit-pack-paid"),
    )
    paid_again = service.mark_payment_order_paid(
        order_id=str(order["order_id"]),
        provider_trade_no="202606230000000001",
        provider_event_id="alipay-credit-pack-paid",
        amount=99.0,
        raw_event={"trade_status": "TRADE_SUCCESS"},
        audit_context=_audit("credit-pack-paid"),
    )

    assert order["status"] == PAYMENT_ORDER_STATUS_PENDING
    assert order["purchase_kind"] == "credit_pack"
    assert order["credit_pack"]["pack_id"] == "pack_small"
    assert order["target_subscription_id"] == base_paid["subscription"]["subscription_id"]
    assert paid["order"]["status"] == PAYMENT_ORDER_STATUS_PAID
    assert paid["credit_ledger_entry"]["event_type"] == "grant"
    assert paid["credit_ledger_entry"]["source_type"] == "credit_pack_purchase"
    assert paid["credit_ledger_entry"]["credit_delta"] == 10000.0
    assert paid_again["credit_ledger_entry"]["ledger_entry_id"] == (
        paid["credit_ledger_entry"]["ledger_entry_id"]
    )
    with get_session(database_url) as session:
        assert len(list(session.scalars(select(AccountSubscription)))) == 1
        entries = list(session.scalars(select(CreditLedgerEntry)))
        assert len(entries) == 1
        assert entries[0].credit_delta == 10000.0

    dispose_engine(database_url)


def test_credit_pack_refund_reverses_credit_grant_without_canceling_subscription(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    _seed_account_and_plan(service)
    package_order = service.create_payment_order(
        account_id="acct_pay",
        plan_id="plan_pro",
        plan_version_id="plan_pro_v1",
        amount=199.0,
        audit_context=_audit("credit-pack-refund-base-order"),
    )
    service.mark_payment_order_paid(
        order_id=str(package_order["order_id"]),
        provider_event_id="alipay-credit-pack-refund-base-paid",
        amount=199.0,
        audit_context=_audit("credit-pack-refund-base-paid"),
    )
    order = service.create_credit_pack_payment_order(
        account_id="acct_pay",
        pack_id="pack_small",
        audit_context=_audit("credit-pack-refund-order"),
    )
    service.mark_payment_order_paid(
        order_id=str(order["order_id"]),
        provider_event_id="alipay-credit-pack-refund-paid",
        amount=99.0,
        audit_context=_audit("credit-pack-refund-paid"),
    )
    refund = service.request_payment_refund(
        order_id=str(order["order_id"]),
        amount=99.0,
        reason="customer requested refund",
        audit_context=_audit("credit-pack-refund-request"),
    )
    result = service.mark_payment_refund_succeeded(
        refund_id=str(refund["refund_id"]),
        provider_refund_no="20260623REFUND0001",
        provider_event_id="alipay-credit-pack-refund-success",
        raw_event={"refund_status": "REFUND_SUCCESS"},
        audit_context=_audit("credit-pack-refund-success"),
    )

    assert result["order"]["status"] == PAYMENT_ORDER_STATUS_REFUNDED
    assert result["revoked_subscription"] == {}
    assert result["credit_ledger_entry"]["event_type"] == "adjustment"
    assert result["credit_ledger_entry"]["source_type"] == "credit_pack_refund"
    assert result["credit_ledger_entry"]["credit_delta"] == -10000.0
    with get_session(database_url) as session:
        subscription = session.scalar(select(AccountSubscription))
        assert subscription is not None
        assert subscription.status == SUBSCRIPTION_STATUS_ACTIVE
        entries = list(session.scalars(select(CreditLedgerEntry)))
        assert sorted(entry.credit_delta for entry in entries) == [-10000.0, 10000.0]

    dispose_engine(database_url)
