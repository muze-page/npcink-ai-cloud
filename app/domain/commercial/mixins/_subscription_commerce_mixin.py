"""Paid package offers, subscription orders, and shared trial eligibility."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, cast
from urllib.parse import urlparse
from uuid import uuid4

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.db import get_session
from app.core.models import (
    PAYMENT_ORDER_STATUS_CANCELED,
    PAYMENT_ORDER_STATUS_PAID,
    PAYMENT_ORDER_STATUS_PENDING,
    PAYMENT_ORDER_STATUS_REFUNDED,
    PLAN_OFFER_PURCHASE_MODE_QUOTE,
    PLAN_OFFER_PURCHASE_MODE_SELF_SERVE,
    PLAN_OFFER_STATUS_ACTIVE,
    PLAN_OFFER_STATUS_RETIRED,
    SUBSCRIPTION_ORDER_KIND_DOWNGRADE,
    SUBSCRIPTION_ORDER_KIND_PURCHASE,
    SUBSCRIPTION_ORDER_KIND_RENEWAL,
    SUBSCRIPTION_ORDER_KIND_UPGRADE,
    SUBSCRIPTION_ORDER_STATUS_ACTIVATED,
    SUBSCRIPTION_ORDER_STATUS_CANCELED,
    SUBSCRIPTION_ORDER_STATUS_PAID,
    SUBSCRIPTION_ORDER_STATUS_PENDING_PAYMENT,
    SUBSCRIPTION_ORDER_STATUS_REFUNDED,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_CANCELED,
    SUBSCRIPTION_STATUS_SCHEDULED,
    SUBSCRIPTION_STATUS_TRIALING,
    TRIAL_CLAIM_STATUS_ACTIVE,
    TRIAL_CLAIM_STATUS_CONVERTED,
    TRIAL_CLAIM_STATUS_EXPIRED,
    AccountSubscription,
    PaymentEvent,
    PaymentOrder,
    PlanOffer,
    SubscriptionOrder,
)
from app.domain.commercial.errors import (
    CommercialConflictError,
    CommercialNotFoundError,
    CommercialValidationError,
)
from app.domain.commercial.mixins._audit_mixin import (
    CommercialServiceAuditMixin,
    ServiceAuditContext,
)
from app.domain.commercial.payment_gateways import (
    PaymentGatewayCloseRequest,
    PaymentGatewayOrderRequest,
    get_payment_gateway_provider,
)
from app.domain.commercial.payment_subjects import build_subscription_payment_subject

PAID_TIER_ORDER = {"free": 0, "plus": 1, "pro": 2, "agency": 3}
STANDARD_PLAN_OFFERS: dict[str, dict[str, object]] = {
    "plus": {
        "offer_id": "plus_monthly_v1",
        "amount": Decimal("15.00"),
        "trial_credit_limit": 3_000,
    },
    "pro": {
        "offer_id": "pro_monthly_v1",
        "amount": Decimal("29.00"),
        "trial_credit_limit": 5_000,
    },
}
SUBSCRIPTION_PERIOD_DAYS = 30
PAID_PACKAGE_TRIAL_DAYS = 14
AGENCY_TRIAL_CREDIT_LIMIT_MAX = 20_000
MONEY_QUANTUM = Decimal("0.01")
MAX_PENDING_SUBSCRIPTION_ORDERS = 5


class CommercialServiceSubscriptionCommerceMixin(CommercialServiceAuditMixin):
    def list_account_plan_offers(self, *, account_id: str) -> dict[str, object]:
        now = cast(Any, self).now_factory()
        with get_session(cast(Any, self).database_url) as session:
            repository = CommercialRepository(session)
            self._require_commerce_account(repository, account_id)
            self._ensure_standard_plan_offers_in_session(repository)
            offers = repository.list_plan_offers(
                account_id=account_id,
                status=PLAN_OFFER_STATUS_ACTIVE,
                now=now,
            )
            claim = repository.find_trial_claim(account_id=account_id)
            session.commit()
            return {
                "items": [self._serialize_plan_offer(offer) for offer in offers],
                "trial": (
                    self._serialize_trial_claim(claim)
                    if claim is not None
                    else {"available": True, "trial_days": PAID_PACKAGE_TRIAL_DAYS}
                ),
            }

    def create_account_agency_quote(
        self,
        *,
        account_id: str,
        amount_cny: float,
        valid_days: int = 7,
        trial_enabled: bool = True,
        trial_credit_limit: int = 20_000,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        service = cast(Any, self)
        now = service.now_factory()
        amount = self._money(amount_cny)
        if amount <= Decimal("0.00") or amount > Decimal("9999999999.99"):
            raise CommercialValidationError(
                "service.agency_quote_amount_invalid",
                "Agency quote amount must be between 0.01 and 9999999999.99",
            )
        if valid_days < 1 or valid_days > 30:
            raise CommercialValidationError(
                "service.agency_quote_validity_invalid",
                "Agency quote validity must be between 1 and 30 days",
            )
        if trial_credit_limit < 0 or trial_credit_limit > AGENCY_TRIAL_CREDIT_LIMIT_MAX:
            raise CommercialValidationError(
                "service.agency_trial_credit_limit_invalid",
                "Agency trial credit limit must be between 0 and 20000",
            )
        with get_session(service.database_url) as session:
            repository = CommercialRepository(session)
            if repository.get_account_for_update(account_id) is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )
            plan_id, plan_version_id = service._ensure_plan_tier_version_in_session(
                repository=repository,
                tier_id="agency",
            )
            for existing_offer in repository.list_plan_offers(account_id=account_id):
                if (
                    existing_offer.account_id == account_id
                    and existing_offer.tier_id == "agency"
                    and existing_offer.status == PLAN_OFFER_STATUS_ACTIVE
                ):
                    existing_offer.status = PLAN_OFFER_STATUS_RETIRED
            offer = repository.upsert_plan_offer(
                offer_id=f"agency_quote_{uuid4().hex[:20]}",
                plan_id=plan_id,
                plan_version_id=plan_version_id,
                account_id=account_id,
                tier_id="agency",
                billing_cycle="monthly",
                amount=amount,
                currency="CNY",
                purchase_mode=PLAN_OFFER_PURCHASE_MODE_QUOTE,
                status=PLAN_OFFER_STATUS_ACTIVE,
                trial_enabled=trial_enabled,
                trial_days=PAID_PACKAGE_TRIAL_DAYS if trial_enabled else 0,
                trial_credit_limit=trial_credit_limit if trial_enabled else 0,
                trial_requires_approval=True,
                valid_from_at=now,
                valid_until_at=now + timedelta(days=valid_days),
                metadata_json={"source": "admin_agency_quote"},
            )
            payload = self._serialize_plan_offer(offer)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="plan_offer.agency_quote.create",
                outcome="succeeded",
                account_id=account_id,
                plan_id=plan_id,
                plan_version_id=plan_version_id,
                scope_kind="plan_offer",
                scope_id=offer.offer_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def create_account_subscription_payment_order(
        self,
        *,
        account_id: str,
        offer_id: str,
        provider: str = "alipay",
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        service = cast(Any, self)
        now = service.now_factory()
        normalized_provider = service._normalize_payment_provider(provider)
        if normalized_provider != "alipay":
            raise CommercialValidationError(
                "service.subscription_payment_provider_invalid",
                "Paid package checkout currently uses Alipay",
            )
        idempotency_key = audit_context.idempotency_key if audit_context else ""
        with get_session(service.database_url) as session:
            repository = CommercialRepository(session)
            if repository.get_account_for_update(account_id) is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )
            self._ensure_standard_plan_offers_in_session(repository)
            if idempotency_key:
                existing_payment = repository.get_payment_order_by_idempotency_key(idempotency_key)
                if existing_payment is not None:
                    existing_subscription_order = (
                        repository.get_subscription_order_by_payment_order(
                            existing_payment.order_id
                        )
                    )
                    return {
                        "order": service._serialize_payment_order(existing_payment),
                        "subscription_order": self._serialize_subscription_order(
                            existing_subscription_order
                        ),
                    }

            service._reconcile_account_subscription_state_in_session(
                repository=repository,
                account_id=account_id,
                now=now,
                audit_context=audit_context,
            )
            self._reconcile_pending_subscription_orders_in_session(
                repository=repository,
                account_id=account_id,
                now=now,
            )
            offer = repository.get_plan_offer(offer_id)
            self._assert_offer_purchasable(offer, account_id=account_id, now=now)
            assert offer is not None
            current = service._select_primary_subscription(
                repository.list_account_subscriptions(account_id)
            )
            current_tier = self._subscription_tier(current)
            target_tier = offer.tier_id
            target_rank = PAID_TIER_ORDER.get(target_tier, -1)
            if target_rank <= 0:
                raise CommercialValidationError(
                    "service.subscription_order_not_upgrade",
                    "The selected offer is not a paid package",
                )
            if repository.count_subscription_orders(
                account_id=account_id,
                statuses={SUBSCRIPTION_ORDER_STATUS_PAID},
            ):
                raise CommercialConflictError(
                    "service.subscription_order_pending",
                    "This account already has a paid package change waiting to take effect",
                )
            pending_payment_count = repository.count_subscription_orders(
                account_id=account_id,
                statuses={SUBSCRIPTION_ORDER_STATUS_PENDING_PAYMENT},
            )
            if pending_payment_count >= MAX_PENDING_SUBSCRIPTION_ORDERS:
                raise CommercialConflictError(
                    "service.subscription_order_pending_limit",
                    "This account already has 5 unpaid package orders; "
                    "cancel one before creating another",
                )

            order_kind = self._resolve_subscription_order_kind(
                current=current,
                current_tier=current_tier,
                target_tier=target_tier,
            )
            list_amount = self._money(offer.amount)
            credit_amount = Decimal("0.00")
            payable_amount = list_amount
            if (
                current is not None
                and current.status == SUBSCRIPTION_STATUS_ACTIVE
                and order_kind == SUBSCRIPTION_ORDER_KIND_UPGRADE
            ):
                current_price = self._subscription_monthly_price(current)
                remaining_fraction = self._remaining_period_fraction(current, now=now)
                payable_amount = self._money(
                    max(Decimal("0.00"), list_amount - current_price) * remaining_fraction
                )
                credit_amount = self._money(list_amount - payable_amount)
                if payable_amount <= Decimal("0.00"):
                    raise CommercialValidationError(
                        "service.subscription_upgrade_price_invalid",
                        "The upgrade must have a positive prorated amount",
                    )

            period_start_at, period_end_at, effective_at = self._order_period(
                current=current,
                order_kind=order_kind,
                now=now,
            )
            subscription_order_id = f"sord_{uuid4().hex[:24]}"
            payment_order_id = f"pay_{uuid4().hex[:24]}"
            metadata: dict[str, object] = {
                "source": "portal_subscription_checkout",
                "purchase_kind": "subscription_plan",
                "subscription_order_id": subscription_order_id,
                "offer_id": offer.offer_id,
                "target_tier_id": target_tier,
                "billing_cycle": offer.billing_cycle,
                "monthly_price_cny": float(list_amount),
                "source_subscription": self._subscription_snapshot(current),
                "created_at": service._serialize_datetime(now),
            }
            gateway = get_payment_gateway_provider(
                normalized_provider,
                config=service._payment_gateway_runtime_config(normalized_provider),
            )
            subject = build_subscription_payment_subject(tier_id=target_tier)
            gateway_order = gateway.create_order(
                PaymentGatewayOrderRequest(
                    provider=normalized_provider,
                    order_id=payment_order_id,
                    amount=float(payable_amount),
                    currency="CNY",
                    subject=subject,
                    metadata=metadata,
                )
            )
            metadata["payment_gateway"] = gateway_order.provider_payload
            payment_order = repository.create_payment_order(
                order_id=payment_order_id,
                account_id=account_id,
                site_id=None,
                subscription_id=(current.subscription_id if current is not None else None),
                plan_id=offer.plan_id,
                plan_version_id=offer.plan_version_id,
                provider=normalized_provider,
                external_order_no=gateway_order.external_order_no,
                status=PAYMENT_ORDER_STATUS_PENDING,
                amount=float(payable_amount),
                currency="CNY",
                subject=subject,
                checkout_url=gateway_order.checkout_url or None,
                refund_window_end_at=now + timedelta(days=14),
                idempotency_key=idempotency_key or None,
                metadata_json=metadata,
            )
            subscription_order = repository.create_subscription_order(
                subscription_order_id=subscription_order_id,
                account_id=account_id,
                offer_id=offer.offer_id,
                payment_order_id=payment_order.order_id,
                source_subscription_id=(current.subscription_id if current is not None else None),
                target_plan_id=offer.plan_id,
                target_plan_version_id=offer.plan_version_id,
                order_kind=order_kind,
                status=SUBSCRIPTION_ORDER_STATUS_PENDING_PAYMENT,
                list_amount=list_amount,
                credit_amount=credit_amount,
                payable_amount=payable_amount,
                currency="CNY",
                effective_at=effective_at,
                period_start_at=period_start_at,
                period_end_at=period_end_at,
                metadata_json=metadata,
            )
            payload = {
                "order": service._serialize_payment_order(payment_order),
                "subscription_order": self._serialize_subscription_order(subscription_order),
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="subscription_order.create",
                outcome="succeeded",
                account_id=account_id,
                subscription_id=(current.subscription_id if current else None),
                plan_id=offer.plan_id,
                plan_version_id=offer.plan_version_id,
                scope_kind="subscription_order",
                scope_id=subscription_order.subscription_order_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def cancel_account_subscription_payment_order(
        self,
        *,
        account_id: str,
        subscription_order_id: str,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        service = cast(Any, self)
        now = service.now_factory()
        with get_session(service.database_url) as session:
            repository = CommercialRepository(session)
            if repository.get_account_for_update(account_id) is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )
            self._reconcile_pending_subscription_orders_in_session(
                repository=repository,
                account_id=account_id,
                now=now,
            )
            subscription_order = repository.get_subscription_order(subscription_order_id)
            if subscription_order is None or subscription_order.account_id != account_id:
                raise CommercialNotFoundError(
                    "service.subscription_order_not_found",
                    f"subscription order '{subscription_order_id}' was not found",
                )
            payment_order = (
                repository.get_payment_order_for_update(subscription_order.payment_order_id)
                if subscription_order.payment_order_id
                else None
            )
            if subscription_order.status == SUBSCRIPTION_ORDER_STATUS_CANCELED:
                payload = {
                    "order": service._serialize_payment_order(payment_order)
                    if payment_order is not None
                    else {},
                    "subscription_order": self._serialize_subscription_order(subscription_order),
                }
                session.commit()
                return payload
            if (
                subscription_order.status != SUBSCRIPTION_ORDER_STATUS_PENDING_PAYMENT
                or payment_order is None
                or payment_order.status != PAYMENT_ORDER_STATUS_PENDING
            ):
                raise CommercialConflictError(
                    "service.subscription_order_not_cancelable",
                    "Only unpaid package orders can be canceled",
                )
            gateway = get_payment_gateway_provider(
                payment_order.provider,
                config=service._payment_gateway_runtime_config(payment_order.provider),
            )
            close_result = gateway.close_order(
                PaymentGatewayCloseRequest(
                    provider=payment_order.provider,
                    order_id=payment_order.order_id,
                    external_order_no=payment_order.external_order_no,
                    metadata=dict(payment_order.metadata_json or {}),
                )
            )
            payment_metadata = dict(payment_order.metadata_json or {})
            payment_metadata.update(
                {
                    "cancellation_reason": "customer_canceled",
                    "canceled_at": service._serialize_datetime(now),
                    "payment_gateway_close": close_result.provider_payload,
                }
            )
            payment_order.status = PAYMENT_ORDER_STATUS_CANCELED
            payment_order.canceled_at = now
            payment_order.checkout_url = None
            payment_order.metadata_json = payment_metadata
            subscription_order.status = SUBSCRIPTION_ORDER_STATUS_CANCELED
            payload = {
                "order": service._serialize_payment_order(payment_order),
                "subscription_order": self._serialize_subscription_order(subscription_order),
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="subscription_order.cancel",
                outcome="succeeded",
                account_id=account_id,
                subscription_id=subscription_order.source_subscription_id,
                plan_id=subscription_order.target_plan_id,
                plan_version_id=subscription_order.target_plan_version_id,
                scope_kind="subscription_order",
                scope_id=subscription_order.subscription_order_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def start_account_plan_trial(
        self,
        *,
        account_id: str,
        tier_id: str,
        principal_id: str = "",
        site_domain: str = "",
        approved_by_principal_id: str = "",
        trial_credit_limit: int | None = None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        service = cast(Any, self)
        now = service.now_factory()
        normalized_tier = str(tier_id or "").strip().lower()
        if normalized_tier not in {"plus", "pro", "agency"}:
            raise CommercialValidationError(
                "service.trial_tier_invalid",
                "Paid package trial tier must be plus, pro, or agency",
            )
        if normalized_tier == "agency" and not approved_by_principal_id:
            raise CommercialValidationError(
                "service.agency_trial_approval_required",
                "Agency trials require platform administrator approval",
            )
        with get_session(service.database_url) as session:
            repository = CommercialRepository(session)
            if repository.get_account_for_update(account_id) is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )
            resolved_principal_id = str(principal_id or "").strip()
            if not resolved_principal_id:
                resolved_principal_id = next(
                    (
                        membership.principal_id
                        for membership in repository.list_account_user_memberships(
                            account_ids=[account_id],
                            statuses=["active"],
                        )
                    ),
                    "",
                )
            self._ensure_standard_plan_offers_in_session(repository)
            service._reconcile_account_subscription_state_in_session(
                repository=repository,
                account_id=account_id,
                now=now,
                audit_context=audit_context,
            )
            normalized_domain = self._resolve_trial_site_domain(
                repository,
                account_id=account_id,
                requested=site_domain,
            )
            claim = repository.find_trial_claim(
                account_id=account_id,
                principal_id=resolved_principal_id or None,
                site_domain=normalized_domain or None,
            )
            target_rank = PAID_TIER_ORDER[normalized_tier]
            if claim is not None:
                if claim.account_id != account_id:
                    raise CommercialValidationError(
                        "service.paid_trial_already_used",
                        "This customer has already used the paid package trial",
                    )
                if (
                    claim.status != TRIAL_CLAIM_STATUS_ACTIVE
                    or self._aware_datetime(claim.ends_at) <= now
                ):
                    if claim.status == TRIAL_CLAIM_STATUS_ACTIVE:
                        claim.status = TRIAL_CLAIM_STATUS_EXPIRED
                    raise CommercialValidationError(
                        "service.paid_trial_already_used",
                        "This customer has already used the paid package trial",
                    )
                current_rank = PAID_TIER_ORDER.get(claim.highest_tier_id, -1)
                if target_rank < current_rank:
                    raise CommercialValidationError(
                        "service.trial_downgrade_not_allowed",
                        "A paid package trial can only move to a higher tier",
                    )
                if target_rank == current_rank:
                    subscription = repository.get_subscription(f"sub_{account_id}_paid_trial")
                    return {
                        "subscription": service._serialize_subscription(subscription),
                        "trial": self._serialize_trial_claim(claim),
                    }

            plan_id, plan_version_id = service._ensure_plan_tier_version_in_session(
                repository=repository,
                tier_id=normalized_tier,
            )
            credit_limit = self._resolve_trial_credit_limit(
                tier_id=normalized_tier,
                requested=trial_credit_limit,
            )
            if claim is None:
                ends_at = now + timedelta(days=PAID_PACKAGE_TRIAL_DAYS)
                claim = repository.create_trial_claim(
                    claim_id=f"trial_{uuid4().hex[:24]}",
                    account_id=account_id,
                    principal_id=resolved_principal_id or None,
                    site_domain=normalized_domain or None,
                    plan_id=plan_id,
                    plan_version_id=plan_version_id,
                    tier_id=normalized_tier,
                    highest_tier_id=normalized_tier,
                    status=TRIAL_CLAIM_STATUS_ACTIVE,
                    credit_limit=credit_limit,
                    started_at=now,
                    ends_at=ends_at,
                    approved_by_principal_id=approved_by_principal_id or None,
                    metadata_json={"source": "paid_package_trial"},
                )
            else:
                claim.plan_id = plan_id
                claim.plan_version_id = plan_version_id
                claim.tier_id = normalized_tier
                claim.highest_tier_id = normalized_tier
                claim.credit_limit = max(claim.credit_limit, credit_limit)
                if approved_by_principal_id:
                    claim.approved_by_principal_id = approved_by_principal_id

            subscription_id = f"sub_{account_id}_paid_trial"
            service._cancel_covered_subscriptions_for_replacement(
                repository=repository,
                account_id=account_id,
                now=now,
                reason="paid_package_trial_started_or_upgraded",
                except_subscription_id=subscription_id,
            )
            subscription, snapshot = service._bind_subscription_in_session(
                repository=repository,
                subscription_id=subscription_id,
                account_id=account_id,
                plan_id=plan_id,
                plan_version_id=plan_version_id,
                status=SUBSCRIPTION_STATUS_TRIALING,
                current_period_start_at=claim.started_at,
                current_period_end_at=claim.ends_at,
                metadata_json={
                    "source": "paid_package_trial",
                    "trial_claim_id": claim.claim_id,
                    "trial_for_tier": normalized_tier,
                    "tier_id": normalized_tier,
                    "billing_mode": "trial",
                    "trial_days": PAID_PACKAGE_TRIAL_DAYS,
                    "trial_started_at": service._serialize_datetime(claim.started_at),
                    "trial_ends_at": service._serialize_datetime(claim.ends_at),
                    "trial_credit_limit": claim.credit_limit,
                    "fallback_tier_id": "free",
                },
            )
            budgets = dict(snapshot.budgets_json or {})
            budgets["max_ai_credits_per_period"] = claim.credit_limit
            snapshot.budgets_json = budgets
            payload = {
                "subscription": service._serialize_subscription(subscription),
                "entitlement_snapshot": service._serialize_entitlement_snapshot(snapshot),
                "trial": self._serialize_trial_claim(claim),
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="subscription.paid_trial.start_or_upgrade",
                outcome="succeeded",
                account_id=account_id,
                subscription_id=subscription.subscription_id,
                plan_id=plan_id,
                plan_version_id=plan_version_id,
                scope_kind="trial_claim",
                scope_id=claim.claim_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def schedule_account_free_downgrade(
        self,
        *,
        account_id: str,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        service = cast(Any, self)
        now = service.now_factory()
        with get_session(service.database_url) as session:
            repository = CommercialRepository(session)
            if repository.get_account_for_update(account_id) is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )
            service._reconcile_account_subscription_state_in_session(
                repository=repository,
                account_id=account_id,
                now=now,
                audit_context=audit_context,
            )
            self._reconcile_pending_subscription_orders_in_session(
                repository=repository,
                account_id=account_id,
                now=now,
            )
            current = service._select_primary_subscription(
                repository.list_account_subscriptions(account_id)
            )
            if current is None or self._subscription_tier(current) == "free":
                raise CommercialValidationError(
                    "service.free_downgrade_not_required",
                    "The account is already on Free",
                )
            if current.current_period_end_at is None:
                raise CommercialValidationError(
                    "service.free_downgrade_period_missing",
                    "The current paid package has no period end",
                )
            if any(
                order.status
                in {SUBSCRIPTION_ORDER_STATUS_PENDING_PAYMENT, SUBSCRIPTION_ORDER_STATUS_PAID}
                for order in repository.list_subscription_orders(
                    account_id=account_id,
                    limit=20,
                )
            ):
                raise CommercialConflictError(
                    "service.subscription_order_pending",
                    "Resolve the pending package order before scheduling Free",
                )
            free_plan_id, free_plan_version_id = service._ensure_plan_tier_version_in_session(
                repository=repository,
                tier_id="free",
            )
            current.scheduled_plan_id = free_plan_id
            current.scheduled_plan_version_id = free_plan_version_id
            current.scheduled_change_at = current.current_period_end_at
            metadata = dict(current.metadata_json or {})
            metadata["scheduled_change"] = {
                "target_tier_id": "free",
                "effective_at": service._serialize_datetime(current.current_period_end_at),
            }
            current.metadata_json = metadata
            payload = {
                "subscription": service._serialize_subscription(current),
                "scheduled_tier_id": "free",
                "scheduled_change_at": service._serialize_datetime(current.scheduled_change_at),
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="subscription.downgrade.schedule",
                outcome="succeeded",
                account_id=account_id,
                subscription_id=current.subscription_id,
                plan_id=current.plan_id,
                plan_version_id=current.plan_version_id,
                scope_kind="subscription",
                scope_id=current.subscription_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def _apply_due_free_downgrade_in_session(
        self,
        *,
        repository: CommercialRepository,
        account_id: str,
        now: datetime,
    ) -> object | None:
        service = cast(Any, self)
        for subscription in repository.list_account_subscriptions(account_id):
            if subscription.status not in {
                SUBSCRIPTION_STATUS_ACTIVE,
                SUBSCRIPTION_STATUS_TRIALING,
            }:
                continue
            if subscription.scheduled_plan_id != "free":
                continue
            if subscription.scheduled_change_at is None:
                continue
            if self._aware_datetime(subscription.scheduled_change_at) > now:
                continue
            subscription.status = SUBSCRIPTION_STATUS_CANCELED
            subscription.canceled_at = now
            subscription.scheduled_plan_id = None
            subscription.scheduled_plan_version_id = None
            subscription.scheduled_change_at = None
            repository.supersede_entitlement_snapshots(account_id)
            restored = service._restore_default_free_subscription_for_account_in_session(
                repository=repository,
                account_id=account_id,
                now=now,
                reason="scheduled_free_downgrade",
                audit_context=None,
            )
            restored_payload = cast(dict[str, object], restored.get("subscription") or {})
            restored_id = str(restored_payload.get("subscription_id") or "")
            return repository.get_subscription(restored_id)
        return None

    def _apply_subscription_order_payment_in_session(
        self,
        *,
        repository: CommercialRepository,
        order: PaymentOrder,
        event: PaymentEvent,
        provider_trade_no: str,
        paid_at: datetime,
        audit_context: ServiceAuditContext | None,
    ) -> dict[str, object]:
        service = cast(Any, self)
        subscription_order = repository.get_subscription_order_by_payment_order(order.order_id)
        if subscription_order is None:
            raise CommercialNotFoundError(
                "service.subscription_order_not_found",
                "The package payment is not linked to a subscription order",
            )
        if subscription_order.status == SUBSCRIPTION_ORDER_STATUS_ACTIVATED:
            subscription = repository.get_subscription(str(order.subscription_id or ""))
            return {
                "order": service._serialize_payment_order(order),
                "subscription_order": self._serialize_subscription_order(subscription_order),
                "subscription": service._serialize_subscription(subscription),
                "payment_event": service._serialize_payment_event(event),
            }

        self._close_other_pending_subscription_orders_in_session(
            repository=repository,
            account_id=order.account_id,
            paid_subscription_order_id=subscription_order.subscription_order_id,
            now=paid_at,
        )
        order.status = PAYMENT_ORDER_STATUS_PAID
        order.provider_trade_no = str(provider_trade_no or "").strip() or order.provider_trade_no
        order.paid_at = paid_at
        source = (
            repository.get_subscription(subscription_order.source_subscription_id)
            if subscription_order.source_subscription_id
            else None
        )
        if source is not None:
            source.scheduled_plan_id = None
            source.scheduled_plan_version_id = None
            source.scheduled_change_at = None
        if source is not None and (
            source.status == SUBSCRIPTION_STATUS_TRIALING
            or subscription_order.order_kind == SUBSCRIPTION_ORDER_KIND_DOWNGRADE
        ):
            scheduled_id = f"sub_{subscription_order.subscription_order_id}"
            scheduled = repository.upsert_account_subscription(
                subscription_id=scheduled_id,
                account_id=order.account_id,
                plan_id=subscription_order.target_plan_id,
                plan_version_id=subscription_order.target_plan_version_id,
                status=SUBSCRIPTION_STATUS_SCHEDULED,
                current_period_start_at=subscription_order.period_start_at,
                current_period_end_at=subscription_order.period_end_at,
                started_at=subscription_order.period_start_at,
                canceled_at=None,
                suspended_at=None,
                metadata_json={
                    **dict(subscription_order.metadata_json or {}),
                    "source": "paid_trial_conversion",
                    "subscription_order_id": subscription_order.subscription_order_id,
                    "payment_order_id": order.order_id,
                },
            )
            order.subscription_id = scheduled.subscription_id
            subscription_order.status = SUBSCRIPTION_ORDER_STATUS_PAID
            subscription_order.effective_at = source.current_period_end_at
            payload = {
                "order": service._serialize_payment_order(order),
                "subscription_order": self._serialize_subscription_order(subscription_order),
                "subscription": service._serialize_subscription(scheduled),
                "payment_event": service._serialize_payment_event(event),
            }
            return payload

        subscription = self._activate_subscription_order_in_session(
            repository=repository,
            subscription_order=subscription_order,
            payment_order=order,
            now=paid_at,
        )
        payload = {
            "order": service._serialize_payment_order(order),
            "subscription_order": self._serialize_subscription_order(subscription_order),
            "subscription": service._serialize_subscription(subscription),
            "payment_event": service._serialize_payment_event(event),
        }
        self._record_service_audit_in_session(
            repository=repository,
            audit_context=audit_context,
            event_kind="subscription_order.activate",
            outcome="succeeded",
            account_id=order.account_id,
            subscription_id=subscription.subscription_id,
            plan_id=subscription.plan_id,
            plan_version_id=subscription.plan_version_id,
            scope_kind="subscription_order",
            scope_id=subscription_order.subscription_order_id,
            payload_json=payload,
        )
        return payload

    def _close_other_pending_subscription_orders_in_session(
        self,
        *,
        repository: CommercialRepository,
        account_id: str,
        paid_subscription_order_id: str,
        now: datetime,
    ) -> None:
        service = cast(Any, self)
        for candidate in repository.list_subscription_orders(account_id=account_id):
            if (
                candidate.subscription_order_id == paid_subscription_order_id
                or candidate.status != SUBSCRIPTION_ORDER_STATUS_PENDING_PAYMENT
                or not candidate.payment_order_id
            ):
                continue
            payment_order = repository.get_payment_order_for_update(candidate.payment_order_id)
            if payment_order is None or payment_order.status != PAYMENT_ORDER_STATUS_PENDING:
                continue
            gateway = get_payment_gateway_provider(
                payment_order.provider,
                config=service._payment_gateway_runtime_config(payment_order.provider),
            )
            try:
                close_result = gateway.close_order(
                    PaymentGatewayCloseRequest(
                        provider=payment_order.provider,
                        order_id=payment_order.order_id,
                        external_order_no=payment_order.external_order_no,
                        metadata=dict(payment_order.metadata_json or {}),
                    )
                )
            except CommercialValidationError as error:
                metadata = dict(payment_order.metadata_json or {})
                metadata["superseded_close_error"] = error.error_code
                metadata["superseded_by_subscription_order_id"] = paid_subscription_order_id
                payment_order.metadata_json = metadata
                continue
            metadata = dict(payment_order.metadata_json or {})
            metadata.update(
                {
                    "cancellation_reason": "superseded_by_paid_package_order",
                    "canceled_at": service._serialize_datetime(now),
                    "superseded_by_subscription_order_id": paid_subscription_order_id,
                    "payment_gateway_close": close_result.provider_payload,
                }
            )
            payment_order.status = PAYMENT_ORDER_STATUS_CANCELED
            payment_order.canceled_at = now
            payment_order.checkout_url = None
            payment_order.metadata_json = metadata
            candidate.status = SUBSCRIPTION_ORDER_STATUS_CANCELED

    def _activate_due_subscription_orders_in_session(
        self,
        *,
        repository: CommercialRepository,
        account_id: str,
        now: datetime,
    ) -> list[object]:
        activated: list[object] = []
        for subscription_order in repository.list_subscription_orders(
            account_id=account_id,
            limit=20,
        ):
            if subscription_order.status != SUBSCRIPTION_ORDER_STATUS_PAID:
                continue
            if (
                subscription_order.effective_at
                and self._aware_datetime(subscription_order.effective_at) > now
            ):
                continue
            payment_order = (
                repository.get_payment_order(subscription_order.payment_order_id)
                if subscription_order.payment_order_id
                else None
            )
            if payment_order is None or payment_order.status != PAYMENT_ORDER_STATUS_PAID:
                continue
            activated.append(
                self._activate_subscription_order_in_session(
                    repository=repository,
                    subscription_order=subscription_order,
                    payment_order=payment_order,
                    now=now,
                )
            )
            claim = repository.find_trial_claim(account_id=account_id)
            if claim is not None and claim.status == TRIAL_CLAIM_STATUS_ACTIVE:
                claim.status = TRIAL_CLAIM_STATUS_CONVERTED
                claim.converted_at = now
        return activated

    def _reconcile_pending_subscription_orders_in_session(
        self,
        *,
        repository: CommercialRepository,
        account_id: str,
        now: datetime,
    ) -> None:
        service = cast(Any, self)
        service._cancel_expired_pending_payment_orders_in_session(
            repository,
            account_id=account_id,
            site_id=None,
            now=now,
        )
        for subscription_order in repository.list_subscription_orders(account_id=account_id):
            if subscription_order.status != SUBSCRIPTION_ORDER_STATUS_PENDING_PAYMENT:
                continue
            payment_order = (
                repository.get_payment_order(subscription_order.payment_order_id)
                if subscription_order.payment_order_id
                else None
            )
            if payment_order is None or payment_order.status in {
                PAYMENT_ORDER_STATUS_CANCELED,
                PAYMENT_ORDER_STATUS_REFUNDED,
            }:
                subscription_order.status = SUBSCRIPTION_ORDER_STATUS_CANCELED

    @staticmethod
    def _cancel_subscription_order_for_payment_in_session(
        *,
        repository: CommercialRepository,
        payment_order_id: str,
    ) -> None:
        subscription_order = repository.get_subscription_order_by_payment_order(payment_order_id)
        if (
            subscription_order is not None
            and subscription_order.status == SUBSCRIPTION_ORDER_STATUS_PENDING_PAYMENT
        ):
            subscription_order.status = SUBSCRIPTION_ORDER_STATUS_CANCELED

    @staticmethod
    def _assert_subscription_order_refundable_in_session(
        *,
        repository: CommercialRepository,
        payment_order: PaymentOrder,
    ) -> None:
        subscription_order = repository.get_subscription_order_by_payment_order(
            payment_order.order_id
        )
        if subscription_order is None:
            return
        for candidate in repository.list_subscription_orders(account_id=payment_order.account_id):
            if candidate.subscription_order_id == subscription_order.subscription_order_id:
                continue
            source_snapshot = dict((candidate.metadata_json or {}).get("source_subscription") or {})
            if (
                str(source_snapshot.get("subscription_order_id") or "")
                != subscription_order.subscription_order_id
            ):
                continue
            if candidate.status in {
                SUBSCRIPTION_ORDER_STATUS_PENDING_PAYMENT,
                SUBSCRIPTION_ORDER_STATUS_PAID,
                SUBSCRIPTION_ORDER_STATUS_ACTIVATED,
            }:
                raise CommercialConflictError(
                    "service.subscription_refund_has_later_order",
                    "Refund the latest package order before refunding an earlier order",
                )

    def _activate_subscription_order_in_session(
        self,
        *,
        repository: CommercialRepository,
        subscription_order: SubscriptionOrder,
        payment_order: PaymentOrder,
        now: datetime,
    ) -> AccountSubscription:
        service = cast(Any, self)
        source = (
            repository.get_subscription(subscription_order.source_subscription_id)
            if subscription_order.source_subscription_id
            else None
        )
        if subscription_order.order_kind == SUBSCRIPTION_ORDER_KIND_RENEWAL and source:
            subscription_id = source.subscription_id
            period_start_at = source.current_period_start_at or now
            period_end_at = subscription_order.period_end_at or now + timedelta(
                days=SUBSCRIPTION_PERIOD_DAYS
            )
        elif subscription_order.order_kind == SUBSCRIPTION_ORDER_KIND_UPGRADE and source:
            subscription_id = source.subscription_id
            period_start_at = source.current_period_start_at or now
            period_end_at = source.current_period_end_at or now + timedelta(
                days=SUBSCRIPTION_PERIOD_DAYS
            )
        else:
            subscription_id = f"sub_{subscription_order.subscription_order_id}"
            period_start_at = subscription_order.period_start_at or now
            period_end_at = subscription_order.period_end_at or period_start_at + timedelta(
                days=SUBSCRIPTION_PERIOD_DAYS
            )
        service._cancel_covered_subscriptions_for_replacement(
            repository=repository,
            account_id=subscription_order.account_id,
            now=now,
            reason="subscription_order_activated",
            except_subscription_id=subscription_id,
        )
        subscription, _snapshot = service._bind_subscription_in_session(
            repository=repository,
            subscription_id=subscription_id,
            account_id=subscription_order.account_id,
            plan_id=subscription_order.target_plan_id,
            plan_version_id=subscription_order.target_plan_version_id,
            status=SUBSCRIPTION_STATUS_ACTIVE,
            current_period_start_at=period_start_at,
            current_period_end_at=period_end_at,
            metadata_json={
                **dict(subscription_order.metadata_json or {}),
                "source": "subscription_order",
                "subscription_order_id": subscription_order.subscription_order_id,
                "payment_order_id": payment_order.order_id,
                "monthly_price_cny": float(subscription_order.list_amount),
                "billing_cycle": "monthly",
            },
        )
        payment_order.subscription_id = subscription.subscription_id
        subscription_order.status = SUBSCRIPTION_ORDER_STATUS_ACTIVATED
        subscription_order.effective_at = now
        scheduled_id = f"sub_{subscription_order.subscription_order_id}"
        scheduled = repository.get_subscription(scheduled_id)
        if scheduled is not None and scheduled.subscription_id != subscription.subscription_id:
            scheduled.status = SUBSCRIPTION_STATUS_CANCELED
            scheduled.canceled_at = now
        covered_sites = repository.list_sites(account_id=subscription.account_id, limit=None)
        service._refresh_subscription_billing_snapshots_in_session(
            repository=repository,
            subscription=subscription,
            covered_sites=covered_sites,
            period_start_at=period_start_at,
            period_end_at=period_end_at,
        )
        return subscription

    def _restore_subscription_order_after_full_refund_in_session(
        self,
        *,
        repository: CommercialRepository,
        order: PaymentOrder,
        now: datetime,
    ) -> object | None:
        service = cast(Any, self)
        subscription_order = repository.get_subscription_order_by_payment_order(order.order_id)
        if subscription_order is None:
            return None
        subscription_order.status = SUBSCRIPTION_ORDER_STATUS_REFUNDED
        active = repository.get_subscription(str(order.subscription_id or ""))
        source_data = dict(
            (subscription_order.metadata_json or {}).get("source_subscription") or {}
        )
        source_plan_id = str(source_data.get("plan_id") or "")
        source_plan_version_id = str(source_data.get("plan_version_id") or "")
        source_subscription_id = str(source_data.get("subscription_id") or "")
        source_status = str(source_data.get("status") or "")
        if active is not None:
            active.status = SUBSCRIPTION_STATUS_CANCELED
            active.canceled_at = now
            repository.supersede_entitlement_snapshots(
                order.account_id,
                subscription_id=active.subscription_id,
            )
        if source_status == SUBSCRIPTION_STATUS_TRIALING:
            source_trial = repository.get_subscription(source_subscription_id)
            if (
                source_trial is not None
                and source_trial.current_period_end_at is not None
                and self._aware_datetime(source_trial.current_period_end_at) > now
            ):
                source_trial.status = SUBSCRIPTION_STATUS_TRIALING
                source_trial.canceled_at = None
                return source_trial
            if source_trial is not None:
                source_trial.status = SUBSCRIPTION_STATUS_CANCELED
                source_trial.canceled_at = now
        elif source_plan_id and source_plan_id != "free" and source_plan_version_id:
            restored, _snapshot = service._bind_subscription_in_session(
                repository=repository,
                subscription_id=source_subscription_id or f"sub_refund_{order.order_id}",
                account_id=order.account_id,
                plan_id=source_plan_id,
                plan_version_id=source_plan_version_id,
                status=SUBSCRIPTION_STATUS_ACTIVE,
                current_period_start_at=self._parse_datetime(source_data.get("period_start_at")),
                current_period_end_at=self._parse_datetime(source_data.get("period_end_at")),
                metadata_json={"source": "subscription_order_full_refund_restore"},
            )
            return restored
        restored = service._restore_default_free_subscription_for_account_in_session(
            repository=repository,
            account_id=order.account_id,
            now=now,
            reason="subscription_order_full_refund",
            audit_context=None,
        )
        restored_payload = cast(dict[str, object], restored.get("subscription") or {})
        return repository.get_subscription(str(restored_payload.get("subscription_id") or ""))

    def _ensure_standard_plan_offers_in_session(self, repository: CommercialRepository) -> None:
        service = cast(Any, self)
        for tier_id, settings in STANDARD_PLAN_OFFERS.items():
            offer_id = str(settings["offer_id"])
            if repository.get_plan_offer(offer_id) is not None:
                continue
            plan_id, plan_version_id = service._ensure_plan_tier_version_in_session(
                repository=repository,
                tier_id=tier_id,
            )
            repository.upsert_plan_offer(
                offer_id=offer_id,
                plan_id=plan_id,
                plan_version_id=plan_version_id,
                account_id=None,
                tier_id=tier_id,
                billing_cycle="monthly",
                amount=cast(Decimal, settings["amount"]),
                currency="CNY",
                purchase_mode=PLAN_OFFER_PURCHASE_MODE_SELF_SERVE,
                status=PLAN_OFFER_STATUS_ACTIVE,
                trial_enabled=True,
                trial_days=PAID_PACKAGE_TRIAL_DAYS,
                trial_credit_limit=int(cast(int, settings["trial_credit_limit"])),
                trial_requires_approval=False,
                valid_from_at=None,
                valid_until_at=None,
                metadata_json={"source": "canonical_paid_offer_v1"},
            )

    def _assert_offer_purchasable(
        self,
        offer: PlanOffer | None,
        *,
        account_id: str,
        now: datetime,
    ) -> None:
        if offer is None or offer.status != PLAN_OFFER_STATUS_ACTIVE:
            raise CommercialNotFoundError(
                "service.plan_offer_not_found",
                "The selected package offer is not available",
            )
        if offer.account_id and offer.account_id != account_id:
            raise CommercialNotFoundError(
                "service.plan_offer_not_found",
                "The selected package offer is not available",
            )
        if offer.valid_from_at and self._aware_datetime(offer.valid_from_at) > now:
            raise CommercialValidationError(
                "service.plan_offer_not_started",
                "The selected package offer is not active yet",
            )
        if offer.valid_until_at and self._aware_datetime(offer.valid_until_at) <= now:
            raise CommercialValidationError(
                "service.plan_offer_expired",
                "The selected package offer has expired",
            )

    @staticmethod
    def _resolve_subscription_order_kind(
        *, current: object | None, current_tier: str, target_tier: str
    ) -> str:
        if (
            current is None
            or current_tier == "free"
            or getattr(current, "status", "") == SUBSCRIPTION_STATUS_TRIALING
        ):
            return SUBSCRIPTION_ORDER_KIND_PURCHASE
        if current_tier == target_tier:
            return SUBSCRIPTION_ORDER_KIND_RENEWAL
        if PAID_TIER_ORDER[target_tier] < PAID_TIER_ORDER[current_tier]:
            return SUBSCRIPTION_ORDER_KIND_DOWNGRADE
        return SUBSCRIPTION_ORDER_KIND_UPGRADE

    @staticmethod
    def _subscription_tier(subscription: object | None) -> str:
        if subscription is None:
            return "free"
        metadata = getattr(subscription, "metadata_json", None) or {}
        return str(metadata.get("tier_id") or getattr(subscription, "plan_id", "free")).lower()

    @staticmethod
    def _subscription_monthly_price(subscription: object) -> Decimal:
        metadata = getattr(subscription, "metadata_json", None) or {}
        tier_id = str(metadata.get("tier_id") or getattr(subscription, "plan_id", "")).lower()
        raw = metadata.get("monthly_price_cny")
        if raw is None and tier_id in STANDARD_PLAN_OFFERS:
            raw = STANDARD_PLAN_OFFERS[tier_id]["amount"]
        return CommercialServiceSubscriptionCommerceMixin._money(raw or 0)

    @staticmethod
    def _remaining_period_fraction(subscription: object, *, now: datetime) -> Decimal:
        period_end = getattr(subscription, "current_period_end_at", None)
        if period_end is None:
            return Decimal("0.00")
        normalized_period_end = CommercialServiceSubscriptionCommerceMixin._aware_datetime(
            period_end
        )
        if normalized_period_end <= now:
            return Decimal("0.00")
        seconds = Decimal(str((normalized_period_end - now).total_seconds()))
        period_seconds = Decimal(str(timedelta(days=SUBSCRIPTION_PERIOD_DAYS).total_seconds()))
        return min(Decimal("1.00"), max(Decimal("0.00"), seconds / period_seconds))

    @staticmethod
    def _order_period(
        *, current: object | None, order_kind: str, now: datetime
    ) -> tuple[datetime, datetime, datetime]:
        current_status = str(getattr(current, "status", "") or "")
        current_end = getattr(current, "current_period_end_at", None)
        current_start = getattr(current, "current_period_start_at", None)
        if current_status == SUBSCRIPTION_STATUS_TRIALING and current_end:
            return current_end, current_end + timedelta(days=SUBSCRIPTION_PERIOD_DAYS), current_end
        if (
            order_kind
            in {
                SUBSCRIPTION_ORDER_KIND_RENEWAL,
                SUBSCRIPTION_ORDER_KIND_DOWNGRADE,
            }
            and current_end
        ):
            return current_end, current_end + timedelta(days=SUBSCRIPTION_PERIOD_DAYS), current_end
        if order_kind == SUBSCRIPTION_ORDER_KIND_UPGRADE and current_end:
            return current_start or now, current_end, now
        return now, now + timedelta(days=SUBSCRIPTION_PERIOD_DAYS), now

    @staticmethod
    def _subscription_snapshot(subscription: object | None) -> dict[str, object]:
        if subscription is None:
            return {}
        metadata = getattr(subscription, "metadata_json", None) or {}
        return {
            "subscription_id": str(getattr(subscription, "subscription_id", "") or ""),
            "subscription_order_id": str(metadata.get("subscription_order_id") or ""),
            "plan_id": str(getattr(subscription, "plan_id", "") or ""),
            "plan_version_id": str(getattr(subscription, "plan_version_id", "") or ""),
            "status": str(getattr(subscription, "status", "") or ""),
            "tier_id": str(metadata.get("tier_id") or getattr(subscription, "plan_id", "")),
            "period_start_at": CommercialServiceSubscriptionCommerceMixin._datetime_text(
                getattr(subscription, "current_period_start_at", None)
            ),
            "period_end_at": CommercialServiceSubscriptionCommerceMixin._datetime_text(
                getattr(subscription, "current_period_end_at", None)
            ),
            "monthly_price_cny": float(
                CommercialServiceSubscriptionCommerceMixin._subscription_monthly_price(subscription)
            ),
        }

    def _resolve_trial_credit_limit(self, *, tier_id: str, requested: int | None) -> int:
        if tier_id == "agency":
            value = AGENCY_TRIAL_CREDIT_LIMIT_MAX if requested is None else int(requested)
            if value < 0 or value > AGENCY_TRIAL_CREDIT_LIMIT_MAX:
                raise CommercialValidationError(
                    "service.agency_trial_credit_limit_invalid",
                    "Agency trial credit limit must be between 0 and 20000",
                )
            return value
        return int(cast(int, STANDARD_PLAN_OFFERS[tier_id]["trial_credit_limit"]))

    @staticmethod
    def _resolve_trial_site_domain(
        repository: CommercialRepository,
        *,
        account_id: str,
        requested: str,
    ) -> str:
        candidate = str(requested or "").strip().lower()
        if not candidate:
            sites = repository.list_sites(account_id=account_id, limit=1)
            if sites:
                candidate = str(getattr(sites[0], "wordpress_url", "") or "")
        parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
        return str(parsed.hostname or "").strip().lower()

    @staticmethod
    def _require_commerce_account(repository: CommercialRepository, account_id: str) -> None:
        if repository.get_account(account_id) is None:
            raise CommercialNotFoundError(
                "service.account_not_found",
                f"account '{account_id}' was not found",
            )

    @staticmethod
    def _money(value: object) -> Decimal:
        return Decimal(str(value or 0)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)

    @staticmethod
    def _datetime_text(value: object) -> str:
        return value.isoformat() if isinstance(value, datetime) else ""

    @staticmethod
    def _aware_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        return datetime.fromisoformat(text.replace("Z", "+00:00"))

    def _serialize_plan_offer(self, offer: PlanOffer) -> dict[str, object]:
        return {
            "offer_id": offer.offer_id,
            "plan_id": offer.plan_id,
            "plan_version_id": offer.plan_version_id,
            "account_id": offer.account_id or "",
            "tier_id": offer.tier_id,
            "billing_cycle": offer.billing_cycle,
            "amount": float(offer.amount),
            "currency": offer.currency,
            "purchase_mode": offer.purchase_mode,
            "status": offer.status,
            "trial_enabled": offer.trial_enabled,
            "trial_days": offer.trial_days,
            "trial_credit_limit": offer.trial_credit_limit,
            "trial_requires_approval": offer.trial_requires_approval,
            "valid_from_at": cast(Any, self)._serialize_datetime(offer.valid_from_at),
            "valid_until_at": cast(Any, self)._serialize_datetime(offer.valid_until_at),
            "metadata": offer.metadata_json or {},
        }

    def _serialize_subscription_order(self, order: SubscriptionOrder | None) -> dict[str, object]:
        if order is None:
            return {}
        return {
            "subscription_order_id": order.subscription_order_id,
            "account_id": order.account_id,
            "offer_id": order.offer_id,
            "payment_order_id": order.payment_order_id or "",
            "source_subscription_id": order.source_subscription_id or "",
            "target_plan_id": order.target_plan_id,
            "target_plan_version_id": order.target_plan_version_id,
            "order_kind": order.order_kind,
            "status": order.status,
            "list_amount": float(order.list_amount),
            "credit_amount": float(order.credit_amount),
            "payable_amount": float(order.payable_amount),
            "currency": order.currency,
            "effective_at": cast(Any, self)._serialize_datetime(order.effective_at),
            "period_start_at": cast(Any, self)._serialize_datetime(order.period_start_at),
            "period_end_at": cast(Any, self)._serialize_datetime(order.period_end_at),
            "metadata": order.metadata_json or {},
        }

    def _serialize_trial_claim(self, claim: object) -> dict[str, object]:
        return {
            "claim_id": str(getattr(claim, "claim_id", "") or ""),
            "available": False,
            "status": str(getattr(claim, "status", "") or ""),
            "tier_id": str(getattr(claim, "tier_id", "") or ""),
            "highest_tier_id": str(getattr(claim, "highest_tier_id", "") or ""),
            "trial_days": PAID_PACKAGE_TRIAL_DAYS,
            "credit_limit": int(getattr(claim, "credit_limit", 0) or 0),
            "trial_started_at": cast(Any, self)._serialize_datetime(
                getattr(claim, "started_at", None)
            ),
            "trial_ends_at": cast(Any, self)._serialize_datetime(getattr(claim, "ends_at", None)),
        }
