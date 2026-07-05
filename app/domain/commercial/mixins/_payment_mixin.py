from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.db import get_session
from app.core.models import (
    CREDIT_LEDGER_EVENT_ADJUSTMENT,
    CREDIT_LEDGER_EVENT_GRANT,
    PAYMENT_EVENT_STATUS_PROCESSED,
    PAYMENT_ORDER_STATUS_CANCELED,
    PAYMENT_ORDER_STATUS_PAID,
    PAYMENT_ORDER_STATUS_PENDING,
    PAYMENT_ORDER_STATUS_REFUNDED,
    PAYMENT_REFUND_STATUS_REQUESTED,
    PAYMENT_REFUND_STATUS_SUCCEEDED,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_CANCELED,
    AccountSubscription,
    PaymentEvent,
    PaymentOrder,
    PaymentRefund,
)
from app.domain.commercial.credit_packs import (
    CREDIT_PACK_CATALOG_VERSION,
    get_credit_pack,
    list_credit_packs,
    serialize_credit_pack,
)
from app.domain.commercial.credits import AI_CREDIT_RATE_VERSION
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
    PaymentGatewayOrderRequest,
    PaymentGatewayRefundRequest,
    get_payment_gateway_provider,
    normalize_payment_gateway_provider,
)
from app.domain.commercial.service import PRO_MONTHLY_BILLING_CYCLE, PRO_MONTHLY_PRICE_CNY
from app.domain.service_settings import resolve_alipay_payment_runtime_config


class CommercialServicePaymentMixin(CommercialServiceAuditMixin):
    def list_credit_packs(self) -> dict[str, object]:
        return {
            "catalog_version": CREDIT_PACK_CATALOG_VERSION,
            "period_policy": "current_subscription_period",
            "grant_event_type": CREDIT_LEDGER_EVENT_GRANT,
            "items": list_credit_packs(),
        }

    def list_account_payment_orders(
        self,
        account_id: str,
        *,
        site_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, object]:
        service = cast(Any, self)
        normalized_limit = min(50, max(1, int(limit or 20)))
        normalized_offset = max(0, int(offset or 0))
        normalized_site_id = str(site_id or "").strip() or None
        with get_session(service.database_url) as session:
            repository = CommercialRepository(session)
            if repository.get_account(account_id) is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )
            total = repository.count_payment_orders(
                account_id=account_id,
                site_id=normalized_site_id,
            )
            orders = repository.list_payment_orders(
                account_id=account_id,
                site_id=normalized_site_id,
                limit=normalized_limit,
                offset=normalized_offset,
            )
            return {
                "generated_at": service._serialize_datetime(service.now_factory()),
                "pagination": {
                    "limit": normalized_limit,
                    "offset": normalized_offset,
                    "total": total,
                    "has_more": normalized_offset + len(orders) < total,
                },
                "items": [self._serialize_payment_order_for_kind(order) for order in orders],
            }

    def get_account_payment_order(
        self,
        *,
        account_id: str,
        order_id: str,
        site_id: str | None = None,
    ) -> dict[str, object]:
        with get_session(cast(Any, self).database_url) as session:
            repository = CommercialRepository(session)
            order = repository.get_payment_order(order_id)
            if order is None:
                raise CommercialNotFoundError(
                    "service.payment_order_not_found",
                    f"payment order '{order_id}' was not found",
                )
            if order.account_id != account_id or (
                site_id and order.site_id and order.site_id != site_id
            ):
                raise CommercialNotFoundError(
                    "service.payment_order_not_found",
                    f"payment order '{order_id}' was not found",
                )
            return self._serialize_payment_order_for_kind(order)

    def create_credit_pack_payment_order(
        self,
        *,
        account_id: str,
        pack_id: str,
        provider: str = "alipay",
        site_id: str | None = None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        service = cast(Any, self)
        pack = get_credit_pack(pack_id)
        if pack is None or not pack.active:
            raise CommercialValidationError(
                "service.credit_pack_not_found",
                f"credit pack '{pack_id}' was not found",
            )
        normalized_provider = self._normalize_payment_provider(provider)
        now = service.now_factory()
        idempotency_key = audit_context.idempotency_key if audit_context is not None else ""
        with get_session(service.database_url) as session:
            repository = CommercialRepository(session)
            if idempotency_key:
                existing = repository.get_payment_order_by_idempotency_key(idempotency_key)
                if existing is not None:
                    return self._serialize_credit_pack_payment_order(existing)
            if repository.get_account(account_id) is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )
            subscriptions = repository.list_subscriptions(account_id=account_id, limit=None)
            primary_subscription = service._select_primary_subscription(subscriptions)
            if primary_subscription is None:
                raise CommercialValidationError(
                    "service.credit_pack_subscription_required",
                    "credit pack purchase requires a current account subscription",
                )
            period_start_at, period_end_at = service._resolve_period(primary_subscription, now)
            order_id = f"pay_{uuid4().hex[:24]}"
            metadata = {
                "source": "portal_credit_pack",
                "purchase_kind": "credit_pack",
                "credit_pack": serialize_credit_pack(pack),
                "credit_pack_catalog_version": CREDIT_PACK_CATALOG_VERSION,
                "target_subscription_id": primary_subscription.subscription_id,
                "target_period_start_at": service._serialize_datetime(period_start_at),
                "target_period_end_at": service._serialize_datetime(period_end_at),
                "grant_policy": "payment_success_grants_current_period_ai_credits",
            }
            gateway = get_payment_gateway_provider(
                normalized_provider,
                config=self._payment_gateway_runtime_config(normalized_provider),
            )
            gateway_order = gateway.create_order(
                PaymentGatewayOrderRequest(
                    provider=normalized_provider,
                    order_id=order_id,
                    amount=round(float(pack.amount), 6),
                    currency=pack.currency,
                    subject=f"{pack.label} ({pack.ai_credits} AI credits)",
                    metadata=metadata,
                )
            )
            metadata["payment_gateway"] = gateway_order.provider_payload
            order = repository.create_payment_order(
                order_id=order_id,
                account_id=account_id,
                site_id=str(site_id or "").strip() or None,
                subscription_id=primary_subscription.subscription_id,
                plan_id=primary_subscription.plan_id,
                plan_version_id=primary_subscription.plan_version_id,
                provider=normalized_provider,
                external_order_no=gateway_order.external_order_no,
                status=PAYMENT_ORDER_STATUS_PENDING,
                amount=round(float(pack.amount), 6),
                currency=pack.currency,
                subject=f"{pack.label} ({pack.ai_credits} AI credits)",
                checkout_url=gateway_order.checkout_url or None,
                refund_window_end_at=now + timedelta(days=14),
                idempotency_key=idempotency_key or None,
                metadata_json=metadata,
            )
            payload = self._serialize_credit_pack_payment_order(order)
            service._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="payment.credit_pack_order.create",
                outcome="succeeded",
                account_id=order.account_id,
                site_id=order.site_id,
                subscription_id=order.subscription_id,
                plan_id=order.plan_id,
                plan_version_id=order.plan_version_id,
                scope_kind="payment_order",
                scope_id=order.order_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def create_payment_order(
        self,
        *,
        account_id: str,
        plan_id: str,
        plan_version_id: str,
        amount: float,
        currency: str = "CNY",
        provider: str = "alipay",
        subject: str = "",
        site_id: str | None = None,
        refund_window_days: int = 14,
        metadata_json: dict[str, object] | None = None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        service = cast(Any, self)
        normalized_provider = self._normalize_payment_provider(provider)
        normalized_currency = self._normalize_payment_currency(currency)
        normalized_amount = self._normalize_payment_amount(amount)
        normalized_subject = str(subject or "").strip()[:191] or "Npcink AI Cloud package"
        now = service.now_factory()
        idempotency_key = audit_context.idempotency_key if audit_context is not None else ""
        with get_session(service.database_url) as session:
            repository = CommercialRepository(session)
            if idempotency_key:
                existing = repository.get_payment_order_by_idempotency_key(idempotency_key)
                if existing is not None:
                    return self._serialize_payment_order(existing)
            if repository.get_account(account_id) is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )
            plan = repository.get_plan(plan_id)
            if plan is None:
                raise CommercialNotFoundError(
                    "service.plan_not_found",
                    f"plan '{plan_id}' was not found",
                )
            plan_version = repository.get_plan_version(plan_version_id)
            if plan_version is None or plan_version.plan_id != plan.plan_id:
                raise CommercialNotFoundError(
                    "service.plan_version_not_found",
                    f"plan version '{plan_version_id}' was not found for plan '{plan_id}'",
                )
            order_id = f"pay_{uuid4().hex[:24]}"
            metadata = dict(metadata_json or {})
            metadata.setdefault("source", "payment_order")
            metadata.setdefault("refund_policy", "customer_requested_full_refund")
            gateway = get_payment_gateway_provider(
                normalized_provider,
                config=self._payment_gateway_runtime_config(normalized_provider),
            )
            gateway_order = gateway.create_order(
                PaymentGatewayOrderRequest(
                    provider=normalized_provider,
                    order_id=order_id,
                    amount=normalized_amount,
                    currency=normalized_currency,
                    subject=normalized_subject,
                    metadata=metadata,
                )
            )
            metadata["payment_gateway"] = gateway_order.provider_payload
            order = repository.create_payment_order(
                order_id=order_id,
                account_id=account_id,
                site_id=str(site_id or "").strip() or None,
                subscription_id=None,
                plan_id=plan.plan_id,
                plan_version_id=plan_version.plan_version_id,
                provider=normalized_provider,
                external_order_no=gateway_order.external_order_no,
                status=PAYMENT_ORDER_STATUS_PENDING,
                amount=normalized_amount,
                currency=normalized_currency,
                subject=normalized_subject,
                checkout_url=gateway_order.checkout_url or None,
                refund_window_end_at=now + timedelta(days=max(0, int(refund_window_days))),
                idempotency_key=idempotency_key or None,
                metadata_json=metadata,
            )
            payload = self._serialize_payment_order(order)
            service._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="payment.order.create",
                outcome="succeeded",
                account_id=order.account_id,
                site_id=order.site_id,
                plan_id=order.plan_id,
                plan_version_id=order.plan_version_id,
                scope_kind="payment_order",
                scope_id=order.order_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def create_account_pro_monthly_payment_order(
        self,
        *,
        account_id: str,
        provider: str = "alipay",
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        service = cast(Any, self)
        normalized_provider = self._normalize_payment_provider(provider)
        if normalized_provider != "alipay":
            raise CommercialValidationError(
                "service.pro_payment_provider_invalid",
                "Pro monthly checkout uses Alipay in the current trial phase",
            )
        now = service.now_factory()
        idempotency_key = audit_context.idempotency_key if audit_context is not None else ""
        with get_session(service.database_url) as session:
            repository = CommercialRepository(session)
            if idempotency_key:
                existing = repository.get_payment_order_by_idempotency_key(idempotency_key)
                if existing is not None:
                    return self._serialize_payment_order(existing)
            if repository.get_account(account_id) is None:
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
            plan_id, plan_version_id = service._ensure_plan_tier_version_in_session(
                repository=repository,
                tier_id="pro",
            )
            current_subscription = service._select_primary_subscription(
                repository.list_account_subscriptions(account_id)
            )
            target_subscription_id = ""
            if (
                current_subscription is not None
                and current_subscription.plan_id == plan_id
                and current_subscription.status == "trialing"
            ):
                target_subscription_id = current_subscription.subscription_id
            order_id = f"pay_{uuid4().hex[:24]}"
            metadata: dict[str, object] = {
                "source": "portal_pro_monthly_checkout",
                "purchase_kind": "subscription_plan",
                "target_tier_id": "pro",
                "billing_cycle": PRO_MONTHLY_BILLING_CYCLE,
                "monthly_price_cny": PRO_MONTHLY_PRICE_CNY,
                "trial_conversion": bool(target_subscription_id),
                "created_at": service._serialize_datetime(now),
            }
            gateway = get_payment_gateway_provider(
                normalized_provider,
                config=self._payment_gateway_runtime_config(normalized_provider),
            )
            gateway_order = gateway.create_order(
                PaymentGatewayOrderRequest(
                    provider=normalized_provider,
                    order_id=order_id,
                    amount=PRO_MONTHLY_PRICE_CNY,
                    currency="CNY",
                    subject="Npcink AI Cloud Pro monthly",
                    metadata=metadata,
                )
            )
            metadata["payment_gateway"] = gateway_order.provider_payload
            order = repository.create_payment_order(
                order_id=order_id,
                account_id=account_id,
                site_id=None,
                subscription_id=target_subscription_id or None,
                plan_id=plan_id,
                plan_version_id=plan_version_id,
                provider=normalized_provider,
                external_order_no=gateway_order.external_order_no,
                status=PAYMENT_ORDER_STATUS_PENDING,
                amount=PRO_MONTHLY_PRICE_CNY,
                currency="CNY",
                subject="Npcink AI Cloud Pro monthly",
                checkout_url=gateway_order.checkout_url or None,
                refund_window_end_at=now + timedelta(days=14),
                idempotency_key=idempotency_key or None,
                metadata_json=metadata,
            )
            payload = self._serialize_payment_order(order)
            service._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="payment.pro_monthly_order.create",
                outcome="succeeded",
                account_id=order.account_id,
                subscription_id=order.subscription_id,
                plan_id=order.plan_id,
                plan_version_id=order.plan_version_id,
                scope_kind="payment_order",
                scope_id=order.order_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def mark_payment_order_paid(
        self,
        *,
        order_id: str,
        provider_trade_no: str = "",
        provider_event_id: str = "",
        paid_at: datetime | None = None,
        amount: float | None = None,
        raw_event: dict[str, object] | None = None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        service = cast(Any, self)
        now = service.now_factory()
        idempotency_key = audit_context.idempotency_key if audit_context is not None else ""
        with get_session(service.database_url) as session:
            repository = CommercialRepository(session)
            order = repository.get_payment_order(order_id)
            if order is None:
                raise CommercialNotFoundError(
                    "service.payment_order_not_found",
                    f"payment order '{order_id}' was not found",
                )
            if order.status == PAYMENT_ORDER_STATUS_REFUNDED:
                raise CommercialConflictError(
                    "service.payment_order_already_refunded",
                    "refunded payment orders cannot be marked paid",
                )
            if amount is not None and round(float(amount), 6) != round(float(order.amount), 6):
                raise CommercialValidationError(
                    "service.payment_amount_mismatch",
                    "paid amount does not match the payment order amount",
                )
            event = self._record_payment_event_once(
                repository=repository,
                provider=order.provider,
                event_kind="payment.succeeded",
                order_id=order.order_id,
                refund_id=None,
                provider_event_id=provider_event_id,
                idempotency_key=idempotency_key,
                payload_json=self._sanitize_payload_dict(raw_event or {}) or {},
                processed_at=now,
            )
            if self._payment_order_purchase_kind(order) == "credit_pack":
                payload = self._mark_credit_pack_payment_order_paid_in_session(
                    repository=repository,
                    order=order,
                    event=event,
                    provider_trade_no=provider_trade_no,
                    paid_at=paid_at or now,
                    audit_context=audit_context,
                )
                session.commit()
                return payload
            if order.status == PAYMENT_ORDER_STATUS_PAID and order.subscription_id:
                payload = {
                    "order": self._serialize_payment_order(order),
                    "subscription": service._serialize_subscription(
                        self._require_subscription(repository, order.subscription_id)
                    ),
                    "payment_event": self._serialize_payment_event(event),
                }
                session.commit()
                return payload

            order.status = PAYMENT_ORDER_STATUS_PAID
            order.provider_trade_no = (
                str(provider_trade_no or "").strip() or order.provider_trade_no
            )
            order.paid_at = paid_at or now
            subscription_id = order.subscription_id or f"sub_{order.order_id}"
            service._cancel_covered_subscriptions_for_replacement(
                repository=repository,
                account_id=order.account_id,
                now=order.paid_at,
                reason="payment_order_paid",
                except_subscription_id=subscription_id,
            )
            metadata = dict(order.metadata_json or {})
            subscription, snapshot = service._bind_subscription_in_session(
                repository=repository,
                subscription_id=subscription_id,
                account_id=order.account_id,
                plan_id=order.plan_id,
                plan_version_id=order.plan_version_id,
                status=SUBSCRIPTION_STATUS_ACTIVE,
                current_period_start_at=order.paid_at,
                current_period_end_at=order.paid_at + timedelta(days=30),
                metadata_json={
                    **metadata,
                    "source": "payment_order",
                    "payment_order_id": order.order_id,
                    "payment_provider": order.provider,
                    "billing_cycle": str(
                        metadata.get("billing_cycle") or PRO_MONTHLY_BILLING_CYCLE
                    ),
                    "refund_window_end_at": service._serialize_datetime(
                        order.refund_window_end_at
                    ),
                },
            )
            order.subscription_id = subscription.subscription_id
            covered_sites = repository.list_sites(account_id=subscription.account_id, limit=None)
            period_start_at, period_end_at = service._resolve_period(subscription, now)
            service._refresh_subscription_billing_snapshots_in_session(
                repository=repository,
                subscription=subscription,
                covered_sites=covered_sites,
                period_start_at=period_start_at,
                period_end_at=period_end_at,
            )
            payload = {
                "order": self._serialize_payment_order(order),
                "subscription": service._serialize_subscription(subscription),
                "entitlement_snapshot": self._serialize_payment_entitlement_snapshot(snapshot),
                "payment_event": self._serialize_payment_event(event),
            }
            service._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="payment.order.paid",
                outcome="succeeded",
                account_id=order.account_id,
                site_id=order.site_id,
                subscription_id=subscription.subscription_id,
                plan_id=order.plan_id,
                plan_version_id=order.plan_version_id,
                scope_kind="payment_order",
                scope_id=order.order_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def request_payment_refund(
        self,
        *,
        order_id: str,
        amount: float | None = None,
        reason: str = "",
        metadata_json: dict[str, object] | None = None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        service = cast(Any, self)
        now = service.now_factory()
        idempotency_key = audit_context.idempotency_key if audit_context is not None else ""
        with get_session(service.database_url) as session:
            repository = CommercialRepository(session)
            if idempotency_key:
                existing = repository.get_payment_refund_by_idempotency_key(idempotency_key)
                if existing is not None:
                    return self._serialize_payment_refund(existing)
            order = repository.get_payment_order(order_id)
            if order is None:
                raise CommercialNotFoundError(
                    "service.payment_order_not_found",
                    f"payment order '{order_id}' was not found",
                )
            if order.status != PAYMENT_ORDER_STATUS_PAID:
                raise CommercialConflictError(
                    "service.payment_order_not_paid",
                    "only paid orders can request refunds",
                )
            refund_amount = self._normalize_payment_amount(
                order.amount if amount is None else float(amount)
            )
            if refund_amount > float(order.amount):
                raise CommercialValidationError(
                    "service.payment_refund_amount_invalid",
                    "refund amount cannot exceed the payment order amount",
                )
            refund_id = f"ref_{uuid4().hex[:24]}"
            refund_metadata = dict(metadata_json or {})
            gateway = get_payment_gateway_provider(
                order.provider,
                config=self._payment_gateway_runtime_config(order.provider),
            )
            gateway_refund = gateway.create_refund(
                PaymentGatewayRefundRequest(
                    provider=order.provider,
                    refund_id=refund_id,
                    order_id=order.order_id,
                    amount=refund_amount,
                    currency=order.currency,
                    reason=str(reason or "").strip(),
                    metadata=refund_metadata,
                )
            )
            refund_metadata["payment_gateway"] = gateway_refund.provider_payload
            refund = repository.create_payment_refund(
                refund_id=refund_id,
                order_id=order.order_id,
                account_id=order.account_id,
                subscription_id=order.subscription_id,
                provider=order.provider,
                external_refund_no=gateway_refund.external_refund_no,
                status=PAYMENT_REFUND_STATUS_REQUESTED,
                amount=refund_amount,
                currency=order.currency,
                reason=str(reason or "").strip() or None,
                requested_at=now,
                idempotency_key=idempotency_key or None,
                metadata_json=refund_metadata,
            )
            payload = self._serialize_payment_refund(refund)
            service._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="payment.refund.request",
                outcome="succeeded",
                account_id=order.account_id,
                site_id=order.site_id,
                subscription_id=order.subscription_id,
                plan_id=order.plan_id,
                plan_version_id=order.plan_version_id,
                scope_kind="payment_refund",
                scope_id=refund.refund_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def mark_payment_refund_succeeded(
        self,
        *,
        refund_id: str,
        provider_refund_no: str = "",
        provider_event_id: str = "",
        succeeded_at: datetime | None = None,
        raw_event: dict[str, object] | None = None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        service = cast(Any, self)
        now = service.now_factory()
        idempotency_key = audit_context.idempotency_key if audit_context is not None else ""
        with get_session(service.database_url) as session:
            repository = CommercialRepository(session)
            refund = repository.get_payment_refund(refund_id)
            if refund is None:
                raise CommercialNotFoundError(
                    "service.payment_refund_not_found",
                    f"payment refund '{refund_id}' was not found",
                )
            order = repository.get_payment_order(refund.order_id)
            if order is None:
                raise CommercialNotFoundError(
                    "service.payment_order_not_found",
                    f"payment order '{refund.order_id}' was not found",
                )
            event = self._record_payment_event_once(
                repository=repository,
                provider=refund.provider,
                event_kind="refund.succeeded",
                order_id=refund.order_id,
                refund_id=refund.refund_id,
                provider_event_id=provider_event_id,
                idempotency_key=idempotency_key,
                payload_json=self._sanitize_payload_dict(raw_event or {}) or {},
                processed_at=now,
            )
            if self._payment_order_purchase_kind(order) == "credit_pack":
                payload = self._mark_credit_pack_refund_succeeded_in_session(
                    repository=repository,
                    order=order,
                    refund=refund,
                    event=event,
                    provider_refund_no=provider_refund_no,
                    succeeded_at=succeeded_at or now,
                    audit_context=audit_context,
                )
                session.commit()
                return payload
            if refund.status != PAYMENT_REFUND_STATUS_SUCCEEDED:
                refund.status = PAYMENT_REFUND_STATUS_SUCCEEDED
                refund.provider_refund_no = (
                    str(provider_refund_no or "").strip() or refund.provider_refund_no
                )
                refund.succeeded_at = succeeded_at or now
            revoked_subscription = None
            full_refund = round(float(refund.amount), 6) >= round(float(order.amount), 6)
            if full_refund and order.status != PAYMENT_ORDER_STATUS_REFUNDED:
                order.status = PAYMENT_ORDER_STATUS_REFUNDED
                order.refunded_at = refund.succeeded_at or now
                if order.subscription_id:
                    subscription = self._require_subscription(repository, order.subscription_id)
                    subscription.status = SUBSCRIPTION_STATUS_CANCELED
                    subscription.canceled_at = refund.succeeded_at or now
                    repository.supersede_entitlement_snapshots(
                        order.account_id,
                        subscription_id=subscription.subscription_id,
                    )
                    revoked_subscription = subscription
            payload = {
                "order": self._serialize_payment_order(order),
                "refund": self._serialize_payment_refund(refund),
                "payment_event": self._serialize_payment_event(event),
                "revoked_subscription": (
                    service._serialize_subscription(revoked_subscription)
                    if revoked_subscription is not None
                    else {}
                ),
            }
            service._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="payment.refund.succeeded",
                outcome="succeeded",
                account_id=order.account_id,
                site_id=order.site_id,
                subscription_id=order.subscription_id,
                plan_id=order.plan_id,
                plan_version_id=order.plan_version_id,
                scope_kind="payment_refund",
                scope_id=refund.refund_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def verify_payment_gateway_callback(
        self,
        *,
        provider: str,
        raw_event: dict[str, object],
    ) -> dict[str, object]:
        normalized_provider = self._normalize_payment_provider(provider)
        gateway = get_payment_gateway_provider(
            normalized_provider,
            config=self._payment_gateway_runtime_config(normalized_provider),
        )
        return gateway.verify_payment_callback(dict(raw_event or {})).to_payload()

    def verify_payment_gateway_refund_callback(
        self,
        *,
        provider: str,
        raw_event: dict[str, object],
    ) -> dict[str, object]:
        normalized_provider = self._normalize_payment_provider(provider)
        gateway = get_payment_gateway_provider(
            normalized_provider,
            config=self._payment_gateway_runtime_config(normalized_provider),
        )
        return gateway.verify_refund_callback(dict(raw_event or {})).to_payload()

    def process_payment_gateway_callback(
        self,
        *,
        provider: str,
        raw_event: dict[str, object],
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        service = cast(Any, self)
        normalized_provider = self._normalize_payment_provider(provider)
        gateway = get_payment_gateway_provider(
            normalized_provider,
            config=self._payment_gateway_runtime_config(normalized_provider),
        )
        callback = gateway.verify_payment_callback(dict(raw_event or {}))
        if callback.status != "succeeded":
            return {
                "status": callback.status,
                "mutation_applied": False,
                "callback": callback.to_payload(),
            }
        with get_session(service.database_url) as session:
            repository = CommercialRepository(session)
            order = repository.get_payment_order_by_provider_external_order(
                provider=normalized_provider,
                external_order_no=callback.external_order_no,
            )
            if order is None:
                raise CommercialNotFoundError(
                    "service.payment_order_not_found",
                    "payment order for provider callback was not found",
                )
        paid = self.mark_payment_order_paid(
            order_id=order.order_id,
            provider_trade_no=callback.provider_trade_no,
            provider_event_id=callback.provider_event_id,
            paid_at=callback.occurred_at,
            amount=callback.amount,
            raw_event=callback.raw_event,
            audit_context=audit_context,
        )
        return {
            "status": "succeeded",
            "mutation_applied": True,
            "callback": callback.to_payload(),
            "payment": paid,
        }

    def _mark_credit_pack_payment_order_paid_in_session(
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
        if order.status == PAYMENT_ORDER_STATUS_REFUNDED:
            raise CommercialConflictError(
                "service.payment_order_already_refunded",
                "refunded payment orders cannot be marked paid",
            )
        metadata = order.metadata_json or {}
        pack = self._credit_pack_from_order_metadata(metadata)
        if pack is None:
            raise CommercialValidationError(
                "service.credit_pack_metadata_invalid",
                "credit pack payment order metadata is invalid",
            )
        ai_credits = float(cast(int, pack["ai_credits"]))
        subscription_id = str(
            order.subscription_id or metadata.get("target_subscription_id") or ""
        ).strip()
        if not subscription_id:
            raise CommercialValidationError(
                "service.credit_pack_subscription_required",
                "credit pack payment order requires a target subscription",
            )
        subscription = self._require_subscription(repository, subscription_id)
        if subscription.account_id != order.account_id:
            raise CommercialValidationError(
                "service.credit_pack_subscription_mismatch",
                "credit pack target subscription does not belong to the order account",
            )
        if order.status != PAYMENT_ORDER_STATUS_PAID:
            order.status = PAYMENT_ORDER_STATUS_PAID
            order.provider_trade_no = (
                str(provider_trade_no or "").strip() or order.provider_trade_no
            )
            order.paid_at = paid_at
            order.subscription_id = subscription.subscription_id
        period_start_at, period_end_at = service._resolve_period(subscription, paid_at)
        ledger_entry = repository.record_credit_ledger_entry(
            account_id=order.account_id,
            site_id=order.site_id,
            subscription_id=subscription.subscription_id,
            plan_version_id=subscription.plan_version_id,
            run_id=None,
            provider_call_id=None,
            event_type=CREDIT_LEDGER_EVENT_GRANT,
            source_type="credit_pack_purchase",
            source_id=order.order_id,
            credit_delta=ai_credits,
            quantity=ai_credits,
            unit="credit",
            rate=round(float(order.amount or 0.0) / max(1.0, ai_credits), 8),
            rate_unit="payment_amount_per_credit",
            rate_version=AI_CREDIT_RATE_VERSION,
            idempotency_key=f"credit_pack_grant:{order.order_id}",
            metadata_json={
                "payment_order_id": order.order_id,
                "payment_provider": order.provider,
                "provider_trade_no": order.provider_trade_no or "",
                "pack_id": str(pack["pack_id"]),
                "credit_pack_catalog_version": CREDIT_PACK_CATALOG_VERSION,
                "paid_amount": round(float(order.amount or 0.0), 6),
                "currency": order.currency,
                "period_start_at": service._serialize_datetime(period_start_at),
                "period_end_at": service._serialize_datetime(period_end_at),
            },
            created_at=order.paid_at or paid_at,
        )
        payload = {
            "order": self._serialize_credit_pack_payment_order(order),
            "credit_ledger_entry": service._serialize_credit_ledger_entry(
                ledger_entry,
                include_internal=True,
            ),
            "payment_event": self._serialize_payment_event(event),
        }
        service._record_service_audit_in_session(
            repository=repository,
            audit_context=audit_context,
            event_kind="payment.credit_pack_order.paid",
            outcome="succeeded",
            account_id=order.account_id,
            site_id=order.site_id,
            subscription_id=subscription.subscription_id,
            plan_id=order.plan_id,
            plan_version_id=order.plan_version_id,
            scope_kind="payment_order",
            scope_id=order.order_id,
            payload_json=payload,
        )
        return payload

    def _mark_credit_pack_refund_succeeded_in_session(
        self,
        *,
        repository: CommercialRepository,
        order: PaymentOrder,
        refund: PaymentRefund,
        event: PaymentEvent,
        provider_refund_no: str,
        succeeded_at: datetime,
        audit_context: ServiceAuditContext | None,
    ) -> dict[str, object]:
        service = cast(Any, self)
        metadata = order.metadata_json or {}
        pack = self._credit_pack_from_order_metadata(metadata)
        if pack is None:
            raise CommercialValidationError(
                "service.credit_pack_metadata_invalid",
                "credit pack payment order metadata is invalid",
            )
        ai_credits = float(cast(int, pack["ai_credits"]))
        if refund.status != PAYMENT_REFUND_STATUS_SUCCEEDED:
            refund.status = PAYMENT_REFUND_STATUS_SUCCEEDED
            refund.provider_refund_no = (
                str(provider_refund_no or "").strip() or refund.provider_refund_no
            )
            refund.succeeded_at = succeeded_at
        full_refund = round(float(refund.amount), 6) >= round(float(order.amount), 6)
        if full_refund:
            order.status = PAYMENT_ORDER_STATUS_REFUNDED
            order.refunded_at = refund.succeeded_at or succeeded_at
        subscription_id = str(
            order.subscription_id or metadata.get("target_subscription_id") or ""
        ).strip()
        subscription = self._require_subscription(repository, subscription_id)
        refunded_ratio = min(
            1.0,
            max(0.0, round(float(refund.amount or 0.0), 6) / round(float(order.amount), 6)),
        )
        refunded_credits = round(ai_credits * refunded_ratio, 6)
        ledger_entry = repository.record_credit_ledger_entry(
            account_id=order.account_id,
            site_id=order.site_id,
            subscription_id=subscription.subscription_id,
            plan_version_id=subscription.plan_version_id,
            run_id=None,
            provider_call_id=None,
            event_type=CREDIT_LEDGER_EVENT_ADJUSTMENT,
            source_type="credit_pack_refund",
            source_id=refund.refund_id,
            credit_delta=-refunded_credits,
            quantity=refunded_credits,
            unit="credit",
            rate=round(float(refund.amount or 0.0) / max(1.0, refunded_credits), 8),
            rate_unit="payment_refund_amount_per_credit",
            rate_version=AI_CREDIT_RATE_VERSION,
            idempotency_key=f"credit_pack_refund:{refund.refund_id}",
            metadata_json={
                "payment_order_id": order.order_id,
                "payment_refund_id": refund.refund_id,
                "pack_id": str(pack["pack_id"]),
                "credit_pack_catalog_version": CREDIT_PACK_CATALOG_VERSION,
                "refund_amount": round(float(refund.amount or 0.0), 6),
                "currency": refund.currency,
                "full_refund": full_refund,
            },
            created_at=refund.succeeded_at or succeeded_at,
        )
        payload = {
            "order": self._serialize_credit_pack_payment_order(order),
            "refund": self._serialize_payment_refund(refund),
            "payment_event": self._serialize_payment_event(event),
            "credit_ledger_entry": service._serialize_credit_ledger_entry(
                ledger_entry,
                include_internal=True,
            ),
            "revoked_subscription": {},
        }
        service._record_service_audit_in_session(
            repository=repository,
            audit_context=audit_context,
            event_kind="payment.credit_pack_refund.succeeded",
            outcome="succeeded",
            account_id=order.account_id,
            site_id=order.site_id,
            subscription_id=subscription.subscription_id,
            plan_id=order.plan_id,
            plan_version_id=order.plan_version_id,
            scope_kind="payment_refund",
            scope_id=refund.refund_id,
            payload_json=payload,
        )
        return payload

    def _record_payment_event_once(
        self,
        *,
        repository: CommercialRepository,
        provider: str,
        event_kind: str,
        order_id: str | None,
        refund_id: str | None,
        provider_event_id: str,
        idempotency_key: str,
        payload_json: dict[str, object],
        processed_at: datetime,
    ) -> PaymentEvent:
        existing = repository.get_payment_event_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing
        existing = repository.get_payment_event_by_provider_event(
            provider=provider,
            provider_event_id=provider_event_id,
        )
        if existing is not None:
            return existing
        return repository.create_payment_event(
            event_id=f"pevt_{uuid4().hex[:24]}",
            provider=provider,
            event_kind=event_kind,
            status=PAYMENT_EVENT_STATUS_PROCESSED,
            order_id=order_id,
            refund_id=refund_id,
            provider_event_id=str(provider_event_id or "").strip() or None,
            idempotency_key=str(idempotency_key or "").strip() or None,
            payload_json=dict(payload_json or {}),
            processed_at=processed_at,
        )

    def _payment_order_purchase_kind(self, order: PaymentOrder) -> str:
        metadata = order.metadata_json or {}
        return str(metadata.get("purchase_kind") or "").strip()

    def _credit_pack_from_order_metadata(
        self,
        metadata: dict[str, object],
    ) -> dict[str, object] | None:
        pack = metadata.get("credit_pack")
        if not isinstance(pack, dict):
            return None
        pack_id = str(pack.get("pack_id") or "").strip()
        ai_credits = int(pack.get("ai_credits") or 0)
        if not pack_id or ai_credits <= 0:
            return None
        return {**pack, "pack_id": pack_id, "ai_credits": ai_credits}

    def _require_subscription(
        self,
        repository: CommercialRepository,
        subscription_id: str,
    ) -> AccountSubscription:
        subscription = repository.get_subscription(subscription_id)
        if subscription is None:
            raise CommercialNotFoundError(
                "service.subscription_not_found",
                f"subscription '{subscription_id}' was not found",
            )
        return subscription

    def _normalize_payment_provider(self, provider: str) -> str:
        return normalize_payment_gateway_provider(provider)

    def _normalize_payment_currency(self, currency: str) -> str:
        normalized = str(currency or "").strip().upper()
        if normalized not in {"CNY", "USD"}:
            raise CommercialValidationError(
                "service.payment_currency_unsupported",
                "payment currency must be CNY or USD",
            )
        return normalized

    def _payment_gateway_runtime_config(self, provider: str) -> dict[str, object]:
        normalized_provider = normalize_payment_gateway_provider(provider)
        if normalized_provider == "alipay":
            service = cast(Any, self)
            return resolve_alipay_payment_runtime_config(
                service.database_url,
                service.settings,
            )
        return {}

    def _normalize_payment_amount(self, amount: float) -> float:
        try:
            normalized = round(float(amount), 6)
        except (TypeError, ValueError):
            normalized = 0.0
        if normalized <= 0:
            raise CommercialValidationError(
                "service.payment_amount_invalid",
                "payment amount must be greater than zero",
            )
        return normalized

    def _serialize_payment_order(self, order: PaymentOrder) -> dict[str, object]:
        service = cast(Any, self)
        purchase_kind = self._payment_order_purchase_kind(order)
        return {
            "order_id": order.order_id,
            "account_id": order.account_id,
            "site_id": order.site_id or "",
            "subscription_id": order.subscription_id or "",
            "plan_id": order.plan_id,
            "plan_version_id": order.plan_version_id,
            "provider": order.provider,
            "external_order_no": order.external_order_no,
            "provider_trade_no": order.provider_trade_no or "",
            "status": order.status,
            "amount": round(float(order.amount or 0.0), 6),
            "currency": order.currency,
            "subject": order.subject,
            "checkout_url": order.checkout_url or "",
            "purchase_kind": purchase_kind,
            "status_detail": self._payment_order_status_detail(order),
            "refund_window_end_at": service._serialize_datetime(order.refund_window_end_at),
            "paid_at": service._serialize_datetime(order.paid_at),
            "canceled_at": service._serialize_datetime(order.canceled_at),
            "refunded_at": service._serialize_datetime(order.refunded_at),
            "metadata": order.metadata_json or {},
            "created_at": service._serialize_datetime(order.created_at),
            "updated_at": service._serialize_datetime(order.updated_at),
        }

    def _serialize_payment_order_for_kind(self, order: PaymentOrder) -> dict[str, object]:
        if self._payment_order_purchase_kind(order) == "credit_pack":
            return self._serialize_credit_pack_payment_order(order)
        return self._serialize_payment_order(order)

    def _serialize_credit_pack_payment_order(self, order: PaymentOrder) -> dict[str, object]:
        payload = self._serialize_payment_order(order)
        raw_metadata = payload.get("metadata")
        metadata = cast(dict[str, object], raw_metadata) if isinstance(raw_metadata, dict) else {}
        credit_pack = metadata.get("credit_pack")
        payload["purchase_kind"] = "credit_pack"
        payload["credit_pack"] = credit_pack if isinstance(credit_pack, dict) else {}
        payload["target_subscription_id"] = str(
            metadata.get("target_subscription_id") or payload.get("subscription_id") or ""
        )
        return payload

    def _payment_order_status_detail(self, order: PaymentOrder) -> dict[str, object]:
        provider_label = {
            "alipay": "Alipay",
            "wechat_pay": "WeChat Pay",
            "manual": "manual confirmation",
        }.get(str(order.provider or ""), str(order.provider or "payment provider"))
        if order.status == PAYMENT_ORDER_STATUS_PENDING:
            return {
                "code": "awaiting_payment_confirmation",
                "label": "Waiting for payment confirmation",
                "detail": (
                    f"This order is created for {provider_label}. Credits are granted only "
                    "after the provider success event is confirmed."
                ),
                "next_action": "provider_payment_or_callback",
                "simulated_payment": not bool(order.checkout_url),
            }
        if order.status == PAYMENT_ORDER_STATUS_PAID:
            return {
                "code": "paid_and_granted",
                "label": "Paid",
                "detail": (
                    "Payment has been confirmed and related entitlements or credits "
                    "were applied."
                ),
                "next_action": "none",
                "simulated_payment": False,
            }
        if order.status == PAYMENT_ORDER_STATUS_REFUNDED:
            return {
                "code": "refunded_and_adjusted",
                "label": "Refunded",
                "detail": "Refund has been confirmed and related credits were adjusted.",
                "next_action": "none",
                "simulated_payment": False,
            }
        if order.status == PAYMENT_ORDER_STATUS_CANCELED:
            return {
                "code": "canceled",
                "label": "Canceled",
                "detail": "The payment order was canceled before confirmation.",
                "next_action": "none",
                "simulated_payment": False,
            }
        return {
            "code": str(order.status or "unknown"),
            "label": str(order.status or "Unknown"),
            "detail": "Payment order status is recorded by the Cloud payment ledger.",
            "next_action": "review_status",
            "simulated_payment": not bool(order.checkout_url),
        }

    def _serialize_payment_refund(self, refund: PaymentRefund) -> dict[str, object]:
        service = cast(Any, self)
        return {
            "refund_id": refund.refund_id,
            "order_id": refund.order_id,
            "account_id": refund.account_id,
            "subscription_id": refund.subscription_id or "",
            "provider": refund.provider,
            "external_refund_no": refund.external_refund_no,
            "provider_refund_no": refund.provider_refund_no or "",
            "status": refund.status,
            "amount": round(float(refund.amount or 0.0), 6),
            "currency": refund.currency,
            "reason": refund.reason or "",
            "requested_at": service._serialize_datetime(refund.requested_at),
            "succeeded_at": service._serialize_datetime(refund.succeeded_at),
            "failed_at": service._serialize_datetime(refund.failed_at),
            "metadata": refund.metadata_json or {},
            "created_at": service._serialize_datetime(refund.created_at),
            "updated_at": service._serialize_datetime(refund.updated_at),
        }

    def _serialize_payment_event(self, event: PaymentEvent) -> dict[str, object]:
        service = cast(Any, self)
        return {
            "event_id": event.event_id,
            "provider": event.provider,
            "event_kind": event.event_kind,
            "status": event.status,
            "order_id": event.order_id or "",
            "refund_id": event.refund_id or "",
            "provider_event_id": event.provider_event_id or "",
            "payload": event.payload_json or {},
            "processed_at": service._serialize_datetime(event.processed_at),
            "created_at": service._serialize_datetime(event.created_at),
        }

    def _serialize_payment_entitlement_snapshot(self, snapshot: object) -> dict[str, object]:
        service = cast(Any, self)
        return {
            "account_id": str(getattr(snapshot, "account_id", "") or ""),
            "subscription_id": str(getattr(snapshot, "subscription_id", "") or ""),
            "plan_version_id": str(getattr(snapshot, "plan_version_id", "") or ""),
            "status": str(getattr(snapshot, "status", "") or ""),
            "site_limit": int(getattr(snapshot, "site_limit", 0) or 0),
            "metadata": getattr(snapshot, "metadata_json", None) or {},
            "generated_at": service._serialize_datetime(getattr(snapshot, "generated_at", None)),
        }
