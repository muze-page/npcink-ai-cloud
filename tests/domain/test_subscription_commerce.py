from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    PAYMENT_ORDER_STATUS_PENDING,
    PAYMENT_ORDER_STATUS_REFUNDED,
    SUBSCRIPTION_ORDER_STATUS_ACTIVATED,
    SUBSCRIPTION_ORDER_STATUS_CANCELED,
    SUBSCRIPTION_ORDER_STATUS_PENDING_PAYMENT,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_SCHEDULED,
    AccountSubscription,
    PaymentOrder,
    SubscriptionOrder,
    TrialClaim,
)
from app.domain.commercial.errors import (
    CommercialConflictError,
    CommercialNotFoundError,
    CommercialValidationError,
)
from app.domain.commercial.service import CommercialService, ServiceAuditContext
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
)


def _database_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'subscription-commerce.sqlite3'}"


def _service(database_url: str, clock: list[datetime] | None = None) -> CommercialService:
    return CommercialService(
        database_url,
        now_factory=(lambda: clock[0]) if clock is not None else None,
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


def _audit(key: str) -> ServiceAuditContext:
    return ServiceAuditContext(
        trace_id="tracesubscriptioncommerce00000000",
        idempotency_key=key,
        method="POST",
        path="/portal/v1/account/subscription-orders",
        actor_kind="portal_user",
        actor_ref="principal_customer",
    )


def _account(service: CommercialService, account_id: str) -> None:
    service.upsert_account(
        account_id=account_id,
        name=account_id,
        bind_default_free=True,
    )


def _pay(
    service: CommercialService,
    *,
    account_id: str,
    offer_id: str,
    key: str,
) -> dict[str, object]:
    created = service.create_account_subscription_payment_order(
        account_id=account_id,
        offer_id=offer_id,
        audit_context=_audit(f"{key}-create"),
    )
    order = created["order"]
    expected_tier = "Plus" if offer_id.startswith("plus_") else "Pro"
    assert order["subject"] == f"Npcink AI Cloud {expected_tier} 月度套餐"
    return service.mark_payment_order_paid(
        order_id=str(order["order_id"]),
        provider_event_id=f"{key}-paid",
        amount=float(order["amount"]),
        audit_context=_audit(f"{key}-paid"),
    )


def test_paid_trial_is_shared_and_only_moves_upward(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    _account(service, "acct_trial_shared")

    plus = service.start_account_plan_trial(
        account_id="acct_trial_shared",
        tier_id="plus",
        principal_id="",
        audit_context=_audit("trial-plus"),
    )
    pro = service.start_account_plan_trial(
        account_id="acct_trial_shared",
        tier_id="pro",
        principal_id="",
        audit_context=_audit("trial-pro"),
    )

    assert pro["subscription"]["subscription_id"] == plus["subscription"]["subscription_id"]
    assert pro["trial"]["trial_ends_at"] == plus["trial"]["trial_ends_at"]
    assert pro["trial"]["credit_limit"] == 5_000
    with pytest.raises(CommercialValidationError) as downgrade:
        service.start_account_plan_trial(
            account_id="acct_trial_shared",
            tier_id="plus",
            audit_context=_audit("trial-downgrade"),
        )
    assert downgrade.value.error_code == "service.trial_downgrade_not_allowed"
    with pytest.raises(CommercialValidationError) as unapproved_agency:
        service.start_account_plan_trial(
            account_id="acct_trial_shared",
            tier_id="agency",
            audit_context=_audit("trial-agency-unapproved"),
        )
    assert unapproved_agency.value.error_code == "service.agency_trial_approval_required"

    with get_session(database_url) as session:
        claims = list(session.scalars(select(TrialClaim)))
        assert len(claims) == 1
        assert claims[0].highest_tier_id == "pro"
    dispose_engine(database_url)


def test_paid_trial_domain_cannot_be_reused_by_another_account(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    _account(service, "acct_trial_domain_owner")
    _account(service, "acct_trial_domain_other")
    service.start_account_plan_trial(
        account_id="acct_trial_domain_owner",
        tier_id="plus",
        site_domain="https://shared.example.com",
        audit_context=_audit("trial-domain-owner"),
    )

    with pytest.raises(CommercialValidationError) as reused:
        service.start_account_plan_trial(
            account_id="acct_trial_domain_other",
            tier_id="pro",
            site_domain="shared.example.com",
            audit_context=_audit("trial-domain-other"),
        )
    assert reused.value.error_code == "service.paid_trial_already_used"
    dispose_engine(database_url)


def test_free_plus_pro_purchase_upgrade_renewal_and_refund(tmp_path: Path) -> None:
    now = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
    clock = [now]
    database_url = _database_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url, clock)
    _account(service, "acct_upgrade")

    plus_paid = _pay(
        service,
        account_id="acct_upgrade",
        offer_id="plus_monthly_v1",
        key="plus",
    )
    plus_subscription = plus_paid["subscription"]
    assert plus_subscription["status"] == SUBSCRIPTION_STATUS_ACTIVE
    assert plus_subscription["plan_id"] == "plus"
    plus_end = datetime.fromisoformat(str(plus_subscription["current_period_end_at"]))

    with get_session(database_url) as session:
        current = session.get(
            AccountSubscription,
            str(plus_subscription["subscription_id"]),
        )
        assert current is not None
        current.current_period_start_at = now - timedelta(days=10)
        current.current_period_end_at = now + timedelta(days=20)
        session.commit()
    plus_end = now + timedelta(days=20)
    pro_created = service.create_account_subscription_payment_order(
        account_id="acct_upgrade",
        offer_id="pro_monthly_v1",
        audit_context=_audit("pro-upgrade-create"),
    )
    assert pro_created["subscription_order"]["order_kind"] == "upgrade"
    assert pro_created["subscription_order"]["list_amount"] == 29.0
    assert pro_created["subscription_order"]["payable_amount"] == 9.33
    pro_paid = service.mark_payment_order_paid(
        order_id=str(pro_created["order"]["order_id"]),
        amount=float(pro_created["order"]["amount"]),
        provider_event_id="pro-upgrade-paid",
        audit_context=_audit("pro-upgrade-paid"),
    )
    assert pro_paid["subscription"]["plan_id"] == "pro"
    assert (
        datetime.fromisoformat(str(pro_paid["subscription"]["current_period_end_at"])) == plus_end
    )

    refund = service.request_payment_refund(
        order_id=str(pro_created["order"]["order_id"]),
        audit_context=_audit("pro-upgrade-refund-request"),
    )
    refunded = service.mark_payment_refund_succeeded(
        refund_id=str(refund["refund_id"]),
        provider_event_id="pro-upgrade-refunded",
        audit_context=_audit("pro-upgrade-refunded"),
    )
    assert refunded["restored_subscription"]["plan_id"] == "plus"

    pro_again = _pay(
        service,
        account_id="acct_upgrade",
        offer_id="pro_monthly_v1",
        key="pro-upgrade-again",
    )
    renewal = service.create_account_subscription_payment_order(
        account_id="acct_upgrade",
        offer_id="pro_monthly_v1",
        audit_context=_audit("pro-renew-create"),
    )
    assert renewal["subscription_order"]["order_kind"] == "renewal"
    renewed = service.mark_payment_order_paid(
        order_id=str(renewal["order"]["order_id"]),
        amount=29.0,
        provider_event_id="pro-renew-paid",
        audit_context=_audit("pro-renew-paid"),
    )
    pro_again_end = datetime.fromisoformat(str(pro_again["subscription"]["current_period_end_at"]))
    assert datetime.fromisoformat(
        str(renewed["subscription"]["current_period_end_at"])
    ) == pro_again_end + timedelta(days=30)
    with pytest.raises(CommercialConflictError) as stale_refund:
        service.request_payment_refund(
            order_id=str(pro_again["order"]["order_id"]),
            audit_context=_audit("pro-stale-refund"),
        )
    assert stale_refund.value.error_code == "service.subscription_refund_has_later_order"
    dispose_engine(database_url)


def test_paid_and_free_downgrades_apply_at_period_end(tmp_path: Path) -> None:
    now = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
    clock = [now]
    database_url = _database_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url, clock)
    _account(service, "acct_downgrade")
    pro = _pay(
        service,
        account_id="acct_downgrade",
        offer_id="pro_monthly_v1",
        key="downgrade-pro",
    )
    pro_end = datetime.fromisoformat(str(pro["subscription"]["current_period_end_at"]))

    plus_order = service.create_account_subscription_payment_order(
        account_id="acct_downgrade",
        offer_id="plus_monthly_v1",
        audit_context=_audit("downgrade-plus-create"),
    )
    assert plus_order["subscription_order"]["order_kind"] == "downgrade"
    plus_paid = service.mark_payment_order_paid(
        order_id=str(plus_order["order"]["order_id"]),
        amount=15.0,
        provider_event_id="downgrade-plus-paid",
        audit_context=_audit("downgrade-plus-paid"),
    )
    assert plus_paid["subscription"]["status"] == SUBSCRIPTION_STATUS_SCHEDULED

    clock[0] = pro_end + timedelta(seconds=1)
    account = service.get_admin_account("acct_downgrade")
    assert account["subscriptions"][0]["subscription"]["plan_id"] == "plus"
    with get_session(database_url) as session:
        order = session.scalar(
            select(SubscriptionOrder).where(SubscriptionOrder.order_kind == "downgrade")
        )
        assert order is not None
        assert order.status == SUBSCRIPTION_ORDER_STATUS_ACTIVATED

    plus_current = account["subscriptions"][0]["subscription"]
    plus_end = datetime.fromisoformat(str(plus_current["current_period_end_at"]))
    service.schedule_account_free_downgrade(
        account_id="acct_downgrade",
        audit_context=_audit("downgrade-free"),
    )
    clock[0] = plus_end + timedelta(seconds=1)
    free_account = service.get_admin_account("acct_downgrade")
    assert free_account["subscriptions"][0]["subscription"]["plan_id"] == "free"
    dispose_engine(database_url)


def test_agency_requires_account_quote_and_approved_trial(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    _account(service, "acct_agency")
    _account(service, "acct_other")

    quote = service.create_account_agency_quote(
        account_id="acct_agency",
        amount_cny=499,
        valid_days=7,
        trial_credit_limit=12_000,
        audit_context=_audit("agency-quote"),
    )
    offers = service.list_account_plan_offers(account_id="acct_agency")
    assert any(item["offer_id"] == quote["offer_id"] for item in offers["items"])
    with pytest.raises(CommercialNotFoundError):
        service.create_account_subscription_payment_order(
            account_id="acct_other",
            offer_id=str(quote["offer_id"]),
            audit_context=_audit("agency-wrong-account"),
        )

    trial = service.start_account_plan_trial(
        account_id="acct_agency",
        tier_id="agency",
        approved_by_principal_id="platform_admin",
        trial_credit_limit=12_000,
        audit_context=_audit("agency-trial-approved"),
    )
    assert trial["subscription"]["plan_id"] == "agency"
    assert trial["trial"]["credit_limit"] == 12_000
    dispose_engine(database_url)


def test_trial_payment_refund_restores_trial_instead_of_paid_coverage(
    tmp_path: Path,
) -> None:
    database_url = _database_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    _account(service, "acct_trial_refund")
    trial = service.start_account_plan_trial(
        account_id="acct_trial_refund",
        tier_id="pro",
        audit_context=_audit("trial-refund-start"),
    )
    paid = _pay(
        service,
        account_id="acct_trial_refund",
        offer_id="pro_monthly_v1",
        key="trial-refund-order",
    )
    assert paid["subscription"]["status"] == SUBSCRIPTION_STATUS_SCHEDULED
    refund = service.request_payment_refund(
        order_id=str(paid["order"]["order_id"]),
        audit_context=_audit("trial-refund-request"),
    )
    refunded = service.mark_payment_refund_succeeded(
        refund_id=str(refund["refund_id"]),
        provider_event_id="trial-refund-succeeded",
        audit_context=_audit("trial-refund-succeeded"),
    )
    assert (
        refunded["restored_subscription"]["subscription_id"]
        == (trial["subscription"]["subscription_id"])
    )
    assert refunded["restored_subscription"]["status"] == "trialing"
    dispose_engine(database_url)


def test_paid_order_cancels_earlier_free_downgrade_and_refunds_are_bounded(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
    clock = [now]
    database_url = _database_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url, clock)
    _account(service, "acct_downgrade_override")
    plus = _pay(
        service,
        account_id="acct_downgrade_override",
        offer_id="plus_monthly_v1",
        key="downgrade-override-plus",
    )
    original_end = datetime.fromisoformat(str(plus["subscription"]["current_period_end_at"]))
    service.schedule_account_free_downgrade(
        account_id="acct_downgrade_override",
        audit_context=_audit("downgrade-override-free"),
    )
    renewed = _pay(
        service,
        account_id="acct_downgrade_override",
        offer_id="plus_monthly_v1",
        key="downgrade-override-renew",
    )
    assert renewed["subscription"]["scheduled_plan_id"] == ""
    assert datetime.fromisoformat(
        str(renewed["subscription"]["current_period_end_at"])
    ) == original_end + timedelta(days=30)

    first_refund = service.request_payment_refund(
        order_id=str(renewed["order"]["order_id"]),
        amount=10,
        audit_context=_audit("bounded-refund-first"),
    )
    assert first_refund["amount"] == 10
    with pytest.raises(CommercialValidationError) as excessive:
        service.request_payment_refund(
            order_id=str(renewed["order"]["order_id"]),
            amount=10,
            audit_context=_audit("bounded-refund-second"),
        )
    assert excessive.value.error_code == "service.payment_refund_amount_invalid"

    clock[0] = original_end + timedelta(seconds=1)
    account = service.get_admin_account("acct_downgrade_override")
    assert account["subscriptions"][0]["subscription"]["plan_id"] == "plus"
    dispose_engine(database_url)


def test_expired_checkout_is_canceled_and_does_not_block_reorder(tmp_path: Path) -> None:
    now = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
    clock = [now]
    database_url = _database_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url, clock)
    _account(service, "acct_expired_checkout")
    first = service.create_account_subscription_payment_order(
        account_id="acct_expired_checkout",
        offer_id="plus_monthly_v1",
        audit_context=_audit("expired-checkout-first"),
    )
    with get_session(database_url) as session:
        payment = session.get(PaymentOrder, str(first["order"]["order_id"]))
        assert payment is not None
        payment.created_at = now - timedelta(minutes=31)
        session.commit()

    second = service.create_account_subscription_payment_order(
        account_id="acct_expired_checkout",
        offer_id="plus_monthly_v1",
        audit_context=_audit("expired-checkout-second"),
    )
    assert second["order"]["order_id"] != first["order"]["order_id"]
    with get_session(database_url) as session:
        first_subscription_order = session.scalar(
            select(SubscriptionOrder).where(
                SubscriptionOrder.payment_order_id == first["order"]["order_id"]
            )
        )
        assert first_subscription_order is not None
        assert first_subscription_order.status == SUBSCRIPTION_ORDER_STATUS_CANCELED
    dispose_engine(database_url)


def test_account_can_keep_five_unpaid_package_orders_and_cancel_one(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    _account(service, "acct_pending_limit")

    created = [
        service.create_account_subscription_payment_order(
            account_id="acct_pending_limit",
            offer_id="plus_monthly_v1",
            audit_context=_audit(f"pending-limit-{index}"),
        )
        for index in range(5)
    ]
    with pytest.raises(CommercialConflictError) as limit_error:
        service.create_account_subscription_payment_order(
            account_id="acct_pending_limit",
            offer_id="pro_monthly_v1",
            audit_context=_audit("pending-limit-sixth"),
        )
    assert limit_error.value.error_code == "service.subscription_order_pending_limit"

    canceled = service.cancel_account_subscription_payment_order(
        account_id="acct_pending_limit",
        subscription_order_id=str(created[0]["subscription_order"]["subscription_order_id"]),
        audit_context=_audit("pending-limit-cancel"),
    )
    assert canceled["order"]["status"] == "canceled"
    assert canceled["order"]["metadata"]["cancellation_reason"] == "customer_canceled"
    assert canceled["subscription_order"]["status"] == SUBSCRIPTION_ORDER_STATUS_CANCELED
    with pytest.raises(CommercialConflictError) as late_payment:
        service.mark_payment_order_paid(
            order_id=str(created[0]["order"]["order_id"]),
            provider_event_id="pending-limit-late-payment",
            amount=float(created[0]["order"]["amount"]),
            audit_context=_audit("pending-limit-late-payment"),
        )
    assert late_payment.value.error_code == "service.payment_order_canceled"

    replacement = service.create_account_subscription_payment_order(
        account_id="acct_pending_limit",
        offer_id="pro_monthly_v1",
        audit_context=_audit("pending-limit-replacement"),
    )
    assert replacement["order"]["status"] == "pending"
    dispose_engine(database_url)


def test_provider_close_failure_keeps_package_order_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _database_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    _account(service, "acct_close_failure")
    created = service.create_account_subscription_payment_order(
        account_id="acct_close_failure",
        offer_id="plus_monthly_v1",
        audit_context=_audit("close-failure-create"),
    )

    class _FailingGateway:
        def close_order(self, request: object) -> object:
            raise CommercialValidationError(
                "service.alipay_order_close_failed",
                "Alipay did not confirm that the unpaid order was closed",
            )

    monkeypatch.setattr(
        "app.domain.commercial.mixins._subscription_commerce_mixin.get_payment_gateway_provider",
        lambda *args, **kwargs: _FailingGateway(),
    )
    with pytest.raises(CommercialValidationError) as close_error:
        service.cancel_account_subscription_payment_order(
            account_id="acct_close_failure",
            subscription_order_id=str(
                created["subscription_order"]["subscription_order_id"]
            ),
            audit_context=_audit("close-failure-cancel"),
        )
    assert close_error.value.error_code == "service.alipay_order_close_failed"
    with get_session(database_url) as session:
        payment_order = session.get(PaymentOrder, str(created["order"]["order_id"]))
        subscription_order = session.get(
            SubscriptionOrder,
            str(created["subscription_order"]["subscription_order_id"]),
        )
        assert payment_order is not None
        assert payment_order.status == PAYMENT_ORDER_STATUS_PENDING
        assert subscription_order is not None
        assert subscription_order.status == SUBSCRIPTION_ORDER_STATUS_PENDING_PAYMENT
    dispose_engine(database_url)


def test_paid_package_order_closes_other_unpaid_package_orders(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    _account(service, "acct_close_siblings")
    plus = service.create_account_subscription_payment_order(
        account_id="acct_close_siblings",
        offer_id="plus_monthly_v1",
        audit_context=_audit("close-siblings-plus"),
    )
    pro = service.create_account_subscription_payment_order(
        account_id="acct_close_siblings",
        offer_id="pro_monthly_v1",
        audit_context=_audit("close-siblings-pro"),
    )

    service.mark_payment_order_paid(
        order_id=str(pro["order"]["order_id"]),
        provider_event_id="close-siblings-pro-paid",
        amount=float(pro["order"]["amount"]),
        audit_context=_audit("close-siblings-pro-paid"),
    )
    with get_session(database_url) as session:
        plus_payment = session.get(PaymentOrder, str(plus["order"]["order_id"]))
        plus_subscription_order = session.get(
            SubscriptionOrder,
            str(plus["subscription_order"]["subscription_order_id"]),
        )
        assert plus_payment is not None
        assert plus_payment.status == "canceled"
        assert plus_payment.metadata_json is not None
        assert (
            plus_payment.metadata_json["cancellation_reason"]
            == "superseded_by_paid_package_order"
        )
        assert plus_subscription_order is not None
        assert plus_subscription_order.status == SUBSCRIPTION_ORDER_STATUS_CANCELED
    dispose_engine(database_url)


def test_partial_refunds_revoke_subscription_when_total_reaches_full_amount(
    tmp_path: Path,
) -> None:
    database_url = _database_url(tmp_path)
    init_schema(database_url)
    service = _service(database_url)
    _account(service, "acct_aggregate_refund")
    paid = _pay(
        service,
        account_id="acct_aggregate_refund",
        offer_id="plus_monthly_v1",
        key="aggregate-refund-plus",
    )
    first = service.request_payment_refund(
        order_id=str(paid["order"]["order_id"]),
        amount=5,
        audit_context=_audit("aggregate-refund-first-request"),
    )
    first_succeeded = service.mark_payment_refund_succeeded(
        refund_id=str(first["refund_id"]),
        provider_event_id="aggregate-refund-first-succeeded",
        audit_context=_audit("aggregate-refund-first-succeeded"),
    )
    assert first_succeeded["order"]["status"] != PAYMENT_ORDER_STATUS_REFUNDED

    second = service.request_payment_refund(
        order_id=str(paid["order"]["order_id"]),
        amount=10,
        audit_context=_audit("aggregate-refund-second-request"),
    )
    second_succeeded = service.mark_payment_refund_succeeded(
        refund_id=str(second["refund_id"]),
        provider_event_id="aggregate-refund-second-succeeded",
        audit_context=_audit("aggregate-refund-second-succeeded"),
    )
    assert second_succeeded["order"]["status"] == PAYMENT_ORDER_STATUS_REFUNDED
    assert second_succeeded["restored_subscription"]["plan_id"] == "free"
    dispose_engine(database_url)
