from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.db import get_session
from app.core.models import (
    PAYMENT_EVENT_STATUS_PROCESSED,
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
from app.domain.commercial.errors import (
    CommercialConflictError,
    CommercialNotFoundError,
    CommercialValidationError,
)
from app.domain.commercial.mixins._audit_mixin import ServiceAuditContext


class CommercialServicePaymentMixin:
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
        normalized_subject = str(subject or "").strip()[:191] or "Magick AI Cloud package"
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
            order = repository.create_payment_order(
                order_id=order_id,
                account_id=account_id,
                site_id=str(site_id or "").strip() or None,
                subscription_id=None,
                plan_id=plan.plan_id,
                plan_version_id=plan_version.plan_version_id,
                provider=normalized_provider,
                external_order_no=order_id,
                status=PAYMENT_ORDER_STATUS_PENDING,
                amount=normalized_amount,
                currency=normalized_currency,
                subject=normalized_subject,
                checkout_url=None,
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
                    "source": "payment_order",
                    "payment_order_id": order.order_id,
                    "payment_provider": order.provider,
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
            refund = repository.create_payment_refund(
                refund_id=refund_id,
                order_id=order.order_id,
                account_id=order.account_id,
                subscription_id=order.subscription_id,
                provider=order.provider,
                external_refund_no=refund_id,
                status=PAYMENT_REFUND_STATUS_REQUESTED,
                amount=refund_amount,
                currency=order.currency,
                reason=str(reason or "").strip() or None,
                requested_at=now,
                idempotency_key=idempotency_key or None,
                metadata_json=dict(metadata_json or {}),
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
        normalized = str(provider or "").strip().lower()
        if normalized not in {"alipay", "manual"}:
            raise CommercialValidationError(
                "service.payment_provider_unsupported",
                "payment provider must be alipay or manual",
            )
        return normalized

    def _normalize_payment_currency(self, currency: str) -> str:
        normalized = str(currency or "").strip().upper()
        if normalized not in {"CNY", "USD"}:
            raise CommercialValidationError(
                "service.payment_currency_unsupported",
                "payment currency must be CNY or USD",
            )
        return normalized

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
            "refund_window_end_at": service._serialize_datetime(order.refund_window_end_at),
            "paid_at": service._serialize_datetime(order.paid_at),
            "canceled_at": service._serialize_datetime(order.canceled_at),
            "refunded_at": service._serialize_datetime(order.refunded_at),
            "metadata": order.metadata_json or {},
            "created_at": service._serialize_datetime(order.created_at),
            "updated_at": service._serialize_datetime(order.updated_at),
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
