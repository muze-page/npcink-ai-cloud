from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    ENTITLEMENT_SNAPSHOT_STATUS_SUPERSEDED,
    PAYMENT_ORDER_STATUS_CANCELED,
    PAYMENT_ORDER_STATUS_PAID,
    PAYMENT_ORDER_STATUS_PENDING,
    PAYMENT_ORDER_STATUS_REFUNDED,
    PAYMENT_REFUND_STATUS_REQUESTED,
    PAYMENT_REFUND_STATUS_SUCCEEDED,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_CANCELED,
    SUBSCRIPTION_STATUS_TRIALING,
    AccountEntitlementSnapshot,
    AccountSubscription,
    CreditLedgerEntry,
    PaymentEvent,
    PaymentOrder,
    PaymentRefund,
)
from app.domain.commercial.errors import CommercialConflictError, CommercialValidationError
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
    assert order["external_order_no"] == order["order_id"]
    assert order["metadata"]["payment_gateway"]["contract_version"] == (
        "payment-gateway-contract-v1"
    )
    assert order["metadata"]["payment_gateway"]["provider"] == "alipay"
    with get_session(database_url) as session:
        assert session.scalar(select(PaymentOrder)).status == PAYMENT_ORDER_STATUS_PENDING
        assert session.scalar(select(AccountSubscription)) is None
        assert session.scalar(select(AccountEntitlementSnapshot)) is None

    dispose_engine(database_url)


def test_admin_payment_and_credit_pack_currency_is_cny_only(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    _seed_account_and_plan(service)

    with pytest.raises(CommercialValidationError) as payment_error:
        service.create_payment_order(
            account_id="acct_pay",
            plan_id="plan_pro",
            plan_version_id="plan_pro_v1",
            amount=199.0,
            currency="USD",
            provider="alipay",
            subject="Pro monthly",
            audit_context=_audit("payment-order-usd"),
        )
    assert payment_error.value.error_code == "service.payment_currency_unsupported"

    with pytest.raises(CommercialValidationError) as catalog_error:
        service.update_admin_credit_pack_catalog(
            items=[
                {
                    "pack_id": "pack_small",
                    "label": "Starter annual pack",
                    "ai_credits": 12000,
                    "amount": 119.0,
                    "currency": "USD",
                    "recommended_for_tiers": ["free", "plus"],
                    "validity_days": 365,
                    "active": True,
                }
            ],
            audit_context=_audit("credit-pack-catalog-usd"),
        )
    assert catalog_error.value.error_code == "service.payment_currency_unsupported"

    dispose_engine(database_url)


def test_account_pro_trial_replaces_default_free_once(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    service.upsert_account(
        account_id="acct_trial",
        name="Trial account",
        bind_default_free=True,
    )

    trial = service.start_account_plan_trial(
        account_id="acct_trial",
        tier_id="pro",
        audit_context=_audit("pro-trial-start"),
    )

    assert trial["subscription"]["status"] == SUBSCRIPTION_STATUS_TRIALING
    assert trial["subscription"]["plan_id"] == "pro"
    assert trial["subscription"]["metadata"]["trial_for_tier"] == "pro"
    assert trial["trial"]["trial_days"] == 14
    with get_session(database_url) as session:
        subscriptions = list(session.scalars(select(AccountSubscription)))
        assert len(subscriptions) == 2
        statuses = {item.plan_id: item.status for item in subscriptions}
        assert statuses["free"] == SUBSCRIPTION_STATUS_CANCELED
        assert statuses["pro"] == SUBSCRIPTION_STATUS_TRIALING
        active_snapshots = list(session.scalars(select(AccountEntitlementSnapshot)))
        assert len(active_snapshots) == 2
        assert sum(1 for item in active_snapshots if item.status == "active") == 1

    repeat = service.start_account_plan_trial(
        account_id="acct_trial",
        tier_id="pro",
        audit_context=_audit("pro-trial-repeat"),
    )
    assert repeat["subscription"]["subscription_id"] == trial["subscription"]["subscription_id"]

    dispose_engine(database_url)


def test_expired_pro_trial_falls_back_to_default_free(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    service.upsert_account(
        account_id="acct_trial_expired",
        name="Expired trial account",
        bind_default_free=True,
    )
    service.start_account_plan_trial(
        account_id="acct_trial_expired",
        tier_id="pro",
        audit_context=_audit("pro-trial-expired-start"),
    )
    expired_at = datetime.now(UTC) - timedelta(days=1)
    with get_session(database_url) as session:
        trial_subscription = session.scalar(
            select(AccountSubscription).where(AccountSubscription.plan_id == "pro")
        )
        assert trial_subscription is not None
        trial_subscription.current_period_end_at = expired_at
        metadata = dict(trial_subscription.metadata_json or {})
        metadata["trial_ends_at"] = expired_at.isoformat()
        trial_subscription.metadata_json = metadata
        session.commit()

    account = service.get_admin_account("acct_trial_expired")

    assert account["subscriptions"][0]["subscription"]["plan_id"] == "free"
    assert account["subscriptions"][0]["subscription"]["status"] == SUBSCRIPTION_STATUS_ACTIVE
    with get_session(database_url) as session:
        subscriptions = list(session.scalars(select(AccountSubscription)))
        statuses = {item.plan_id: item.status for item in subscriptions}
        assert statuses["pro"] == SUBSCRIPTION_STATUS_CANCELED
        assert statuses["free"] == SUBSCRIPTION_STATUS_ACTIVE
        active_snapshots = list(
            session.scalars(
                select(AccountEntitlementSnapshot).where(
                    AccountEntitlementSnapshot.status == "active"
                )
            )
        )
        assert len(active_snapshots) == 1
        assert active_snapshots[0].subscription_id == "sub_acct_trial_expired_free"

    dispose_engine(database_url)


def test_payment_service_verifies_gateway_callbacks(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)

    payment = service.verify_payment_gateway_callback(
        provider="wechat",
        raw_event={
            "out_trade_no": "pay_callback_001",
            "transaction_id": "420000000020260623000002",
            "event_id": "notify-wechat-payment-002",
            "amount": {"total": 19900},
            "trade_state": "SUCCESS",
        },
    )
    refund = service.verify_payment_gateway_refund_callback(
        provider="alipay",
        raw_event={
            "out_biz_no": "ref_callback_001",
            "trade_no": "202606230000000002",
            "notify_id": "notify-alipay-refund-002",
            "refund_fee": "199.00",
            "refund_status": "REFUND_SUCCESS",
        },
    )

    assert payment["provider"] == "wechat_pay"
    assert payment["external_order_no"] == "pay_callback_001"
    assert payment["amount"] == 199.0
    assert payment["status"] == "succeeded"
    assert refund["provider"] == "alipay"
    assert refund["external_refund_no"] == "ref_callback_001"
    assert refund["status"] == "succeeded"

    dispose_engine(database_url)


def test_pro_monthly_payment_replaces_free_or_trial_subscription(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    service.upsert_account(
        account_id="acct_pro_monthly",
        name="Pro monthly account",
        bind_default_free=True,
    )
    trial = service.start_account_plan_trial(
        account_id="acct_pro_monthly",
        tier_id="pro",
        audit_context=_audit("pro-monthly-trial"),
    )
    order_result = service.create_account_subscription_payment_order(
        account_id="acct_pro_monthly",
        offer_id="pro_monthly_v1",
        audit_context=_audit("pro-monthly-order"),
    )
    order = order_result["order"]

    assert order["amount"] == 29.0
    assert order["currency"] == "CNY"
    assert order["provider"] == "alipay"
    assert order["metadata"]["billing_cycle"] == "monthly"
    assert order["subscription_id"] == trial["subscription"]["subscription_id"]

    paid = service.mark_payment_order_paid(
        order_id=str(order["order_id"]),
        provider_event_id="alipay-pro-monthly-paid-1",
        amount=29.0,
        audit_context=_audit("pro-monthly-paid"),
    )

    assert paid["subscription"]["status"] == "scheduled"
    assert paid["subscription"]["plan_id"] == "pro"
    assert paid["subscription"]["metadata"]["billing_cycle"] == "monthly"
    assert paid["subscription"]["metadata"]["payment_order_id"] == order["order_id"]
    with get_session(database_url) as session:
        subscriptions = list(session.scalars(select(AccountSubscription)))
        covered = [
            item
            for item in subscriptions
            if item.status in {SUBSCRIPTION_STATUS_ACTIVE, SUBSCRIPTION_STATUS_TRIALING}
        ]
        assert len(covered) == 1
        assert covered[0].plan_id == "pro"
        assert covered[0].status == SUBSCRIPTION_STATUS_TRIALING
        scheduled = [item for item in subscriptions if item.status == "scheduled"]
        assert len(scheduled) == 1
        assert scheduled[0].plan_id == "pro"

    dispose_engine(database_url)


def test_pro_monthly_order_after_trial_expiry_is_new_paid_subscription(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    service.upsert_account(
        account_id="acct_pro_after_expiry",
        name="Pro after expiry account",
        bind_default_free=True,
    )
    trial = service.start_account_plan_trial(
        account_id="acct_pro_after_expiry",
        tier_id="pro",
        audit_context=_audit("pro-after-expiry-trial"),
    )
    expired_at = datetime.now(UTC) - timedelta(seconds=1)
    with get_session(database_url) as session:
        trial_subscription = session.get(
            AccountSubscription,
            str(trial["subscription"]["subscription_id"]),
        )
        assert trial_subscription is not None
        trial_subscription.current_period_end_at = expired_at
        session.commit()

    order_result = service.create_account_subscription_payment_order(
        account_id="acct_pro_after_expiry",
        offer_id="pro_monthly_v1",
        audit_context=_audit("pro-after-expiry-order"),
    )
    order = order_result["order"]

    assert order["amount"] == 29.0
    assert order["subscription_id"].endswith("_free")
    with get_session(database_url) as session:
        subscriptions = list(session.scalars(select(AccountSubscription)))
        statuses = {item.plan_id: item.status for item in subscriptions}
        assert statuses["pro"] == SUBSCRIPTION_STATUS_CANCELED
        assert statuses["free"] == SUBSCRIPTION_STATUS_ACTIVE

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
        assert (
            session.scalar(select(PaymentOrder)).subscription_id
            == (paid["subscription"]["subscription_id"])
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
    assert refund["external_refund_no"] == refund["refund_id"]
    assert refund["metadata"]["payment_gateway"]["contract_version"] == (
        "payment-gateway-contract-v1"
    )
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
        provider="wechat",
        audit_context=_audit("credit-pack-order"),
    )
    pending_orders = service.list_account_payment_orders(
        "acct_pay",
        limit=10,
    )
    pending_credit_pack_order = next(
        item for item in pending_orders["items"] if item["order_id"] == order["order_id"]
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
    assert order["provider"] == "wechat_pay"
    assert order["subject"] == "Npcink AI Cloud 小积分包（10,000 AI 积分）"
    assert order["metadata"]["payment_gateway"]["provider"] == "wechat_pay"
    assert order["purchase_kind"] == "credit_pack"
    assert order["credit_pack"]["pack_id"] == "pack_small"
    assert order["credit_pack"]["validity_days"] == 365
    assert order["metadata"]["credit_expiry_policy"] == "paid_at_plus_validity_days"
    assert order["metadata"]["grant_policy"] == ("payment_success_grants_paid_credit_until_expiry")
    assert order["target_subscription_id"] == base_paid["subscription"]["subscription_id"]
    assert order["status_detail"]["code"] == "awaiting_payment_confirmation"
    assert order["status_detail"]["simulated_payment"] is True
    assert pending_credit_pack_order["status"] == PAYMENT_ORDER_STATUS_PENDING
    assert pending_credit_pack_order["status_detail"]["next_action"] == (
        "provider_payment_or_callback"
    )
    assert paid["order"]["status"] == PAYMENT_ORDER_STATUS_PAID
    assert paid["order"]["status_detail"]["code"] == "paid_and_granted"
    assert paid["credit_ledger_entry"]["event_type"] == "grant"
    assert paid["credit_ledger_entry"]["source_type"] == "credit_pack_purchase"
    assert paid["credit_ledger_entry"]["category"] == "credit_pack_purchase"
    assert paid["credit_ledger_entry"]["direction"] == "credit_in"
    assert "Credit pack payment added" in paid["credit_ledger_entry"]["explanation"]
    assert paid["credit_ledger_entry"]["credit_delta"] == 10000.0
    assert paid["credit_ledger_entry"]["metadata"]["validity_days"] == 365
    assert paid["credit_ledger_entry"]["metadata"]["expiry_policy"] == (
        "paid_at_plus_validity_days"
    )
    grant_expires_at = datetime.fromisoformat(
        str(paid["credit_ledger_entry"]["metadata"]["grant_expires_at"]).replace("Z", "+00:00")
    )
    ledger_created_at = datetime.fromisoformat(
        str(paid["credit_ledger_entry"]["created_at"]).replace("Z", "+00:00")
    )
    assert (
        timedelta(days=364, hours=23)
        <= grant_expires_at - ledger_created_at
        <= timedelta(
            days=365,
            minutes=1,
        )
    )
    assert (
        paid_again["credit_ledger_entry"]["ledger_entry_id"]
        == (paid["credit_ledger_entry"]["ledger_entry_id"])
    )
    paid_orders = service.list_account_payment_orders(
        "acct_pay",
        limit=10,
    )
    paid_credit_pack_order = next(
        item for item in paid_orders["items"] if item["order_id"] == order["order_id"]
    )
    assert paid_credit_pack_order["status"] == PAYMENT_ORDER_STATUS_PAID
    assert paid_credit_pack_order["status_detail"]["code"] == "paid_and_granted"
    with get_session(database_url) as session:
        assert len(list(session.scalars(select(AccountSubscription)))) == 1
        entries = list(session.scalars(select(CreditLedgerEntry)))
        assert len(entries) == 1
        assert entries[0].credit_delta == 10000.0

    dispose_engine(database_url)


def test_account_can_cancel_pending_credit_pack_payment_order(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    _seed_account_and_plan(service)
    package_order = service.create_payment_order(
        account_id="acct_pay",
        plan_id="plan_pro",
        plan_version_id="plan_pro_v1",
        amount=199.0,
        audit_context=_audit("credit-pack-cancel-base-order"),
    )
    service.mark_payment_order_paid(
        order_id=str(package_order["order_id"]),
        provider_event_id="alipay-credit-pack-cancel-base-paid",
        amount=199.0,
        audit_context=_audit("credit-pack-cancel-base-paid"),
    )
    order = service.create_credit_pack_payment_order(
        account_id="acct_pay",
        pack_id="pack_small",
        provider="alipay",
        audit_context=_audit("credit-pack-cancel-order"),
    )

    assert order["available_actions"] == ["cancel"]
    with get_session(database_url) as session:
        pending_record = session.get(PaymentOrder, str(order["order_id"]))
        assert pending_record is not None
        pending_record.checkout_url = "https://openapi.alipay.com/gateway.do?order=real"
        session.commit()
    with pytest.raises(CommercialConflictError) as unavailable_close_error:
        service.cancel_account_payment_order(
            account_id="acct_pay",
            order_id=str(order["order_id"]),
            audit_context=_audit("credit-pack-cancel-without-gateway"),
        )
    assert unavailable_close_error.value.error_code == (
        "service.payment_order_gateway_close_unavailable"
    )
    with get_session(database_url) as session:
        pending_record = session.get(PaymentOrder, str(order["order_id"]))
        assert pending_record is not None
        assert pending_record.status == PAYMENT_ORDER_STATUS_PENDING
        pending_record.checkout_url = None
        session.commit()
    canceled = service.cancel_account_payment_order(
        account_id="acct_pay",
        order_id=str(order["order_id"]),
        audit_context=_audit("credit-pack-cancel"),
    )
    canceled_again = service.cancel_account_payment_order(
        account_id="acct_pay",
        order_id=str(order["order_id"]),
        audit_context=_audit("credit-pack-cancel-again"),
    )

    assert canceled["order"]["status"] == PAYMENT_ORDER_STATUS_CANCELED
    assert canceled["order"]["available_actions"] == []
    assert canceled["order"]["checkout_url"] == ""
    assert canceled["order"]["metadata"]["cancellation_reason"] == "customer_canceled"
    assert canceled_again["order"]["status"] == PAYMENT_ORDER_STATUS_CANCELED
    with pytest.raises(CommercialConflictError) as paid_cancel_error:
        service.cancel_account_payment_order(
            account_id="acct_pay",
            order_id=str(package_order["order_id"]),
            audit_context=_audit("credit-pack-paid-order-cancel"),
        )
    assert paid_cancel_error.value.error_code == "service.payment_order_not_cancelable"
    with get_session(database_url) as session:
        canceled_record = session.get(PaymentOrder, str(order["order_id"]))
        assert canceled_record is not None
        assert canceled_record.status == PAYMENT_ORDER_STATUS_CANCELED
        assert list(session.scalars(select(CreditLedgerEntry))) == []

    dispose_engine(database_url)


def test_pending_payment_orders_expire_before_late_payment_confirmation(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    _seed_account_and_plan(service)
    order = service.create_payment_order(
        account_id="acct_pay",
        plan_id="plan_pro",
        plan_version_id="plan_pro_v1",
        amount=199.0,
        audit_context=_audit("payment-order-expire-create"),
    )
    expired_created_at = datetime.now(UTC) - timedelta(minutes=31)
    with get_session(database_url) as session:
        payment_order = session.get(PaymentOrder, str(order["order_id"]))
        assert payment_order is not None
        payment_order.created_at = expired_created_at
        session.commit()

    listed = service.list_account_payment_orders("acct_pay", limit=10)
    expired_order = next(item for item in listed["items"] if item["order_id"] == order["order_id"])
    assert expired_order["status"] == PAYMENT_ORDER_STATUS_CANCELED
    assert expired_order["status_detail"]["code"] == "expired_unpaid"
    assert expired_order["metadata"]["cancellation_reason"] == "unpaid_order_expired"
    assert expired_order["metadata"]["payment_order_expires_after_seconds"] == 1800
    assert expired_order["canceled_at"]

    with get_session(database_url) as session:
        payment_order = session.get(PaymentOrder, str(order["order_id"]))
        assert payment_order is not None
        assert payment_order.status == PAYMENT_ORDER_STATUS_CANCELED
        assert payment_order.canceled_at is not None

    with pytest.raises(CommercialConflictError) as exc_info:
        service.mark_payment_order_paid(
            order_id=str(order["order_id"]),
            provider_event_id="late-provider-confirmation",
            amount=199.0,
            audit_context=_audit("payment-order-expire-paid"),
        )
    assert exc_info.value.error_code == "service.payment_order_canceled"

    dispose_engine(database_url)


def test_portal_payment_order_groups_hide_old_canceled_orders_without_deleting(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    _seed_account_and_plan(service)

    created = [
        service.create_payment_order(
            account_id="acct_pay",
            plan_id="plan_pro",
            plan_version_id="plan_pro_v1",
            amount=15.0 + index,
            subject=f"Payment order {index}",
            audit_context=_audit(f"payment-order-group-{index}"),
        )
        for index in range(4)
    ]
    now = datetime.now(UTC)
    with get_session(database_url) as session:
        paid = session.get(PaymentOrder, str(created[1]["order_id"]))
        recent_canceled = session.get(PaymentOrder, str(created[2]["order_id"]))
        old_canceled = session.get(PaymentOrder, str(created[3]["order_id"]))
        assert paid is not None
        assert recent_canceled is not None
        assert old_canceled is not None
        paid.status = PAYMENT_ORDER_STATUS_PAID
        paid.paid_at = now
        recent_canceled.status = PAYMENT_ORDER_STATUS_CANCELED
        recent_canceled.canceled_at = now - timedelta(days=1)
        old_canceled.status = PAYMENT_ORDER_STATUS_CANCELED
        old_canceled.canceled_at = now - timedelta(days=8)
        session.commit()

    all_orders = service.list_account_payment_orders("acct_pay", status_group="all")
    pending_orders = service.list_account_payment_orders("acct_pay", status_group="pending")
    paid_orders = service.list_account_payment_orders("acct_pay", status_group="paid")
    closed_orders = service.list_account_payment_orders("acct_pay", status_group="closed")

    assert all_orders["counts"] == {"all": 3, "pending": 1, "paid": 1, "closed": 1}
    assert all_orders["pagination"]["total"] == 3
    assert all_orders["visibility"] == {
        "canceled_orders_visible_days": 7,
        "database_records_deleted": False,
    }
    assert [item["order_id"] for item in pending_orders["items"]] == [
        created[0]["order_id"]
    ]
    assert [item["order_id"] for item in paid_orders["items"]] == [created[1]["order_id"]]
    assert [item["order_id"] for item in closed_orders["items"]] == [
        created[2]["order_id"]
    ]
    with get_session(database_url) as session:
        assert len(list(session.scalars(select(PaymentOrder)))) == 4

    dispose_engine(database_url)


def test_payment_order_expiration_job_cancels_due_orders(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    _seed_account_and_plan(service)
    order = service.create_payment_order(
        account_id="acct_pay",
        plan_id="plan_pro",
        plan_version_id="plan_pro_v1",
        amount=199.0,
        audit_context=_audit("payment-expiration-job-create"),
    )
    with get_session(database_url) as session:
        payment_order = session.get(PaymentOrder, str(order["order_id"]))
        assert payment_order is not None
        payment_order.created_at = datetime.now(UTC) - timedelta(minutes=31)
        session.commit()

    assert service.expire_pending_payment_orders() == {"expired_orders": 1}
    with get_session(database_url) as session:
        payment_order = session.get(PaymentOrder, str(order["order_id"]))
        assert payment_order is not None
        assert payment_order.status == PAYMENT_ORDER_STATUS_CANCELED
    dispose_engine(database_url)


def test_admin_credit_pack_catalog_override_changes_future_orders(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    _seed_account_and_plan(service)
    package_order = service.create_payment_order(
        account_id="acct_pay",
        plan_id="plan_pro",
        plan_version_id="plan_pro_v1",
        amount=199.0,
        audit_context=_audit("credit-pack-admin-base-order"),
    )
    service.mark_payment_order_paid(
        order_id=str(package_order["order_id"]),
        provider_event_id="alipay-credit-pack-admin-base-paid",
        amount=199.0,
        audit_context=_audit("credit-pack-admin-base-paid"),
    )

    catalog = service.list_credit_packs()
    assert catalog["default_validity_days"] == 365
    assert catalog["period_policy"] == "paid_credit_validity_days"
    assert catalog["expiry_policy"] == "paid_at_plus_validity_days"
    assert next(item for item in catalog["items"] if item["pack_id"] == "pack_medium")[
        "recommended_for_tiers"
    ] == ["pro", "agency"]

    updated = service.update_admin_credit_pack_catalog(
        items=[
            {
                "pack_id": "pack_small",
                "label": "Starter annual pack",
                "ai_credits": 12000,
                "amount": 119.0,
                "currency": "CNY",
                "recommended_for_tiers": ["free", "plus"],
                "validity_days": 365,
                "active": True,
            }
        ],
        audit_context=_audit("credit-pack-catalog-update"),
    )
    pack_small = next(item for item in updated["items"] if item["pack_id"] == "pack_small")
    assert pack_small["label"] == "Starter annual pack"
    assert pack_small["ai_credits"] == 12000
    assert pack_small["recommended_for_tiers"] == ["free", "plus"]

    order = service.create_credit_pack_payment_order(
        account_id="acct_pay",
        pack_id="pack_small",
        audit_context=_audit("credit-pack-overridden-order"),
    )
    assert order["credit_pack"]["label"] == "Starter annual pack"
    assert order["credit_pack"]["ai_credits"] == 12000
    assert order["subject"] == "Npcink AI Cloud 小积分包（12,000 AI 积分）"
    assert order["amount"] == 119.0

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
    assert result["credit_ledger_entry"]["category"] == "refund_adjustment"
    assert result["credit_ledger_entry"]["direction"] == "credit_out"
    assert result["credit_ledger_entry"]["credit_delta"] == -10000.0
    with get_session(database_url) as session:
        subscription = session.scalar(select(AccountSubscription))
        assert subscription is not None
        assert subscription.status == SUBSCRIPTION_STATUS_ACTIVE
        entries = list(session.scalars(select(CreditLedgerEntry)))
        assert sorted(entry.credit_delta for entry in entries) == [-10000.0, 10000.0]

    dispose_engine(database_url)
