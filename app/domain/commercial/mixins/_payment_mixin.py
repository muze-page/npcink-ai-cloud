from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
    ServiceSetting,
)
from app.domain.commercial.credit_packs import (
    CREDIT_PACK_CATALOG_VERSION,
    CREDIT_PACK_EXPIRY_POLICY,
    CREDIT_PACK_PERIOD_POLICY,
    DEFAULT_CREDIT_PACK_VALIDITY_DAYS,
    list_credit_packs,
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
    PaymentGatewayCloseRequest,
    PaymentGatewayOrderRequest,
    PaymentGatewayRefundRequest,
    get_payment_gateway_provider,
    normalize_payment_gateway_provider,
)
from app.domain.commercial.payment_subjects import build_credit_pack_payment_subject
from app.domain.service_settings import resolve_alipay_payment_runtime_config

SERVICE_SETTING_CREDIT_PACK_CATALOG = "commercial_credit_pack_catalog"
SERVICE_SETTING_KIND_COMMERCIAL = "commercial"
PAYMENT_ORDER_PENDING_TTL = timedelta(minutes=30)
PAYMENT_ORDER_PORTAL_CANCELED_VISIBILITY = timedelta(days=7)
PAYMENT_ORDER_STATUS_GROUPS: dict[str, tuple[str, ...] | None] = {
    "all": None,
    "pending": (PAYMENT_ORDER_STATUS_PENDING,),
    "paid": (PAYMENT_ORDER_STATUS_PAID,),
    "closed": (PAYMENT_ORDER_STATUS_CANCELED, PAYMENT_ORDER_STATUS_REFUNDED),
}


class CommercialServicePaymentMixin(CommercialServiceAuditMixin):
    def list_credit_packs(self) -> dict[str, object]:
        service = cast(Any, self)
        with get_session(service.database_url) as session:
            items = self._effective_credit_pack_items_from_session(
                session,
                include_inactive=False,
            )
        return {
            "catalog_version": CREDIT_PACK_CATALOG_VERSION,
            "period_policy": CREDIT_PACK_PERIOD_POLICY,
            "expiry_policy": CREDIT_PACK_EXPIRY_POLICY,
            "default_validity_days": DEFAULT_CREDIT_PACK_VALIDITY_DAYS,
            "grant_event_type": CREDIT_LEDGER_EVENT_GRANT,
            "items": items,
        }

    def get_admin_credit_pack_catalog(self) -> dict[str, object]:
        service = cast(Any, self)
        with get_session(service.database_url) as session:
            row = session.get(ServiceSetting, SERVICE_SETTING_CREDIT_PACK_CATALOG)
            items = self._effective_credit_pack_items_from_session(
                session,
                include_inactive=True,
            )
            return {
                "setting_id": SERVICE_SETTING_CREDIT_PACK_CATALOG,
                "catalog_version": CREDIT_PACK_CATALOG_VERSION,
                "period_policy": CREDIT_PACK_PERIOD_POLICY,
                "expiry_policy": CREDIT_PACK_EXPIRY_POLICY,
                "default_validity_days": DEFAULT_CREDIT_PACK_VALIDITY_DAYS,
                "grant_event_type": CREDIT_LEDGER_EVENT_GRANT,
                "items": items,
                "configured": row is not None,
                "updated_at": service._serialize_datetime(getattr(row, "updated_at", None)),
            }

    def update_admin_credit_pack_catalog(
        self,
        *,
        items: list[dict[str, object]],
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        service = cast(Any, self)
        now = service.now_factory()
        default_by_id = {
            str(item.get("pack_id") or ""): item
            for item in list_credit_packs(include_inactive=True)
        }
        normalized_items = [
            self._normalize_credit_pack_catalog_item(item, default_by_id=default_by_id)
            for item in items
        ]
        seen_pack_ids: set[str] = set()
        for item in normalized_items:
            pack_id = str(item.get("pack_id") or "")
            if pack_id in seen_pack_ids:
                raise CommercialValidationError(
                    "service.credit_pack_duplicate",
                    f"credit pack '{pack_id}' was provided more than once",
                )
            seen_pack_ids.add(pack_id)
        with get_session(service.database_url) as session:
            repository = CommercialRepository(session)
            row = session.get(ServiceSetting, SERVICE_SETTING_CREDIT_PACK_CATALOG)
            if row is None:
                row = ServiceSetting(
                    setting_id=SERVICE_SETTING_CREDIT_PACK_CATALOG,
                    setting_kind=SERVICE_SETTING_KIND_COMMERCIAL,
                    enabled=True,
                    config_json={},
                    secret_ciphertext_json={},
                    status="ready",
                    last_tested_at=None,
                    last_error_code=None,
                    last_error_message=None,
                    metadata_json={},
                )
                session.add(row)
            row.setting_kind = SERVICE_SETTING_KIND_COMMERCIAL
            row.enabled = True
            row.config_json = {
                "catalog_version": CREDIT_PACK_CATALOG_VERSION,
                "period_policy": CREDIT_PACK_PERIOD_POLICY,
                "expiry_policy": CREDIT_PACK_EXPIRY_POLICY,
                "default_validity_days": DEFAULT_CREDIT_PACK_VALIDITY_DAYS,
                "items": normalized_items,
            }
            row.status = "ready"
            row.last_error_code = None
            row.last_error_message = None
            row.metadata_json = {
                "source": "admin_credit_pack_catalog",
                "updated_by": audit_context.actor_ref if audit_context is not None else "",
            }
            row.updated_at = now
            session.flush()
            result = {
                "setting_id": SERVICE_SETTING_CREDIT_PACK_CATALOG,
                "catalog_version": CREDIT_PACK_CATALOG_VERSION,
                "period_policy": CREDIT_PACK_PERIOD_POLICY,
                "expiry_policy": CREDIT_PACK_EXPIRY_POLICY,
                "default_validity_days": DEFAULT_CREDIT_PACK_VALIDITY_DAYS,
                "grant_event_type": CREDIT_LEDGER_EVENT_GRANT,
                "items": self._effective_credit_pack_items_from_session(
                    session,
                    include_inactive=True,
                ),
                "configured": True,
                "updated_at": service._serialize_datetime(now),
            }
            service._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="payment.credit_pack_catalog.update",
                outcome="succeeded",
                scope_kind="service_setting",
                scope_id=SERVICE_SETTING_CREDIT_PACK_CATALOG,
                payload_json=result,
            )
            session.commit()
            return result

    def _effective_credit_pack_items_from_session(
        self,
        session: Any,
        *,
        include_inactive: bool,
    ) -> list[dict[str, object]]:
        default_items = list_credit_packs(include_inactive=True)
        default_by_id = {str(item.get("pack_id") or ""): item for item in default_items}
        row = session.get(ServiceSetting, SERVICE_SETTING_CREDIT_PACK_CATALOG)
        config = row.config_json if row is not None and isinstance(row.config_json, dict) else {}
        raw_items = config.get("items") if isinstance(config, dict) else None
        override_by_id: dict[str, dict[str, object]] = {}
        if isinstance(raw_items, list):
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    continue
                try:
                    normalized = self._normalize_credit_pack_catalog_item(
                        raw_item,
                        default_by_id=default_by_id,
                    )
                except CommercialValidationError:
                    continue
                override_by_id[str(normalized.get("pack_id") or "")] = normalized
        items = [
            {**default_item, **override_by_id.get(str(default_item.get("pack_id") or ""), {})}
            for default_item in default_items
        ]
        return [item for item in items if include_inactive or bool(item.get("active", True))]

    def _effective_credit_pack_from_session(
        self,
        session: Any,
        pack_id: str,
    ) -> dict[str, object] | None:
        normalized_pack_id = str(pack_id or "").strip()
        for item in self._effective_credit_pack_items_from_session(
            session,
            include_inactive=True,
        ):
            if str(item.get("pack_id") or "") == normalized_pack_id:
                return item
        return None

    def _normalize_credit_pack_catalog_item(
        self,
        item: dict[str, object],
        *,
        default_by_id: dict[str, dict[str, object]],
    ) -> dict[str, object]:
        pack_id = str(item.get("pack_id") or "").strip()
        default_item = default_by_id.get(pack_id)
        if default_item is None:
            raise CommercialValidationError(
                "service.credit_pack_unknown",
                f"credit pack '{pack_id}' is not part of the managed catalog",
            )
        label = str(item.get("label") or default_item.get("label") or pack_id).strip()[:96]
        ai_credits = self._normalize_credit_pack_positive_int(
            item.get("ai_credits", default_item.get("ai_credits")),
            field="ai_credits",
            maximum=10_000_000,
        )
        amount = self._normalize_payment_amount(item.get("amount", default_item.get("amount")))
        currency = self._normalize_payment_currency(
            str(item.get("currency") or default_item.get("currency") or "CNY")
        )
        raw_tiers = item.get("recommended_for_tiers", default_item.get("recommended_for_tiers"))
        raw_tier_values = raw_tiers if isinstance(raw_tiers, list) else []
        recommended_for_tiers = [
            tier
            for tier in [str(raw_tier or "").strip() for raw_tier in raw_tier_values]
            if tier in {"free", "pro", "plus", "agency"}
        ]
        if not recommended_for_tiers:
            default_raw_tiers = default_item.get("recommended_for_tiers")
            default_tier_values = default_raw_tiers if isinstance(default_raw_tiers, list) else []
            recommended_for_tiers = [
                str(raw_tier or "").strip()
                for raw_tier in default_tier_values
                if str(raw_tier or "").strip()
            ]
        validity_days = self._normalize_credit_pack_positive_int(
            item.get("validity_days", default_item.get("validity_days")),
            field="validity_days",
            maximum=1095,
        )
        return {
            "pack_id": pack_id,
            "label": label,
            "ai_credits": ai_credits,
            "amount": amount,
            "currency": currency,
            "recommended_for_tiers": recommended_for_tiers,
            "validity_days": validity_days,
            "active": bool(item.get("active", default_item.get("active", True))),
            "period_policy": CREDIT_PACK_PERIOD_POLICY,
            "expiry_policy": CREDIT_PACK_EXPIRY_POLICY,
            "grant_event_type": CREDIT_LEDGER_EVENT_GRANT,
            "catalog_version": CREDIT_PACK_CATALOG_VERSION,
        }

    def _normalize_credit_pack_positive_int(
        self,
        value: object,
        *,
        field: str,
        maximum: int,
    ) -> int:
        try:
            normalized = int(cast(Any, value) or 0)
        except (TypeError, ValueError):
            normalized = 0
        if normalized <= 0 or normalized > maximum:
            raise CommercialValidationError(
                f"service.credit_pack_{field}_invalid",
                f"credit pack {field} must be between 1 and {maximum}",
            )
        return normalized

    def list_account_payment_orders(
        self,
        account_id: str,
        *,
        site_id: str | None = None,
        status_group: str = "all",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, object]:
        service = cast(Any, self)
        normalized_limit = min(50, max(1, int(limit or 20)))
        normalized_offset = max(0, int(offset or 0))
        normalized_site_id = str(site_id or "").strip() or None
        normalized_status_group = str(status_group or "all").strip().lower()
        if normalized_status_group not in PAYMENT_ORDER_STATUS_GROUPS:
            raise CommercialValidationError(
                "service.payment_order_status_group_invalid",
                "payment order status group must be all, pending, paid, or closed",
            )
        with get_session(service.database_url) as session:
            repository = CommercialRepository(session)
            if repository.get_account(account_id) is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )
            current_time = service.now_factory()
            if self._cancel_expired_pending_payment_orders_in_session(
                repository,
                account_id=account_id,
                site_id=normalized_site_id,
                now=current_time,
            ):
                session.commit()
            canceled_visible_after = current_time - PAYMENT_ORDER_PORTAL_CANCELED_VISIBILITY
            statuses = PAYMENT_ORDER_STATUS_GROUPS[normalized_status_group]
            status_counts = repository.count_payment_orders_by_status(
                account_id=account_id,
                site_id=normalized_site_id,
                canceled_visible_after=canceled_visible_after,
            )
            counts = {
                "all": sum(status_counts.values()),
                "pending": status_counts.get(PAYMENT_ORDER_STATUS_PENDING, 0),
                "paid": status_counts.get(PAYMENT_ORDER_STATUS_PAID, 0),
                "closed": status_counts.get(PAYMENT_ORDER_STATUS_CANCELED, 0)
                + status_counts.get(PAYMENT_ORDER_STATUS_REFUNDED, 0),
            }
            total = counts[normalized_status_group]
            orders = repository.list_payment_orders(
                account_id=account_id,
                site_id=normalized_site_id,
                statuses=statuses,
                canceled_visible_after=canceled_visible_after,
                limit=normalized_limit,
                offset=normalized_offset,
            )
            return {
                "generated_at": service._serialize_datetime(service.now_factory()),
                "status_group": normalized_status_group,
                "counts": counts,
                "visibility": {
                    "canceled_orders_visible_days": int(
                        PAYMENT_ORDER_PORTAL_CANCELED_VISIBILITY.total_seconds() // 86400
                    ),
                    "database_records_deleted": False,
                },
                "pagination": {
                    "limit": normalized_limit,
                    "offset": normalized_offset,
                    "total": total,
                    "has_more": normalized_offset + len(orders) < total,
                },
                "items": [self._serialize_payment_order_for_kind(order) for order in orders],
            }

    def expire_pending_payment_orders(self) -> dict[str, object]:
        service = cast(Any, self)
        with get_session(service.database_url) as session:
            repository = CommercialRepository(session)
            expired_orders = self._cancel_expired_pending_payment_orders_in_session(
                repository,
                account_id=None,
                site_id=None,
                now=service.now_factory(),
            )
            session.commit()
            return {"expired_orders": expired_orders}

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
            if self._cancel_expired_pending_payment_order_in_session(
                order,
                now=cast(Any, self).now_factory(),
            ):
                session.commit()
            return self._serialize_payment_order_for_kind(order)

    def cancel_account_payment_order(
        self,
        *,
        account_id: str,
        order_id: str,
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
            order = repository.get_payment_order_for_update(order_id)
            if order is None or order.account_id != account_id:
                raise CommercialNotFoundError(
                    "service.payment_order_not_found",
                    f"payment order '{order_id}' was not found",
                )
            if self._cancel_expired_pending_payment_order_in_session(order, now=now):
                service._cancel_subscription_order_for_payment_in_session(
                    repository=repository,
                    payment_order_id=order.order_id,
                )
                session.commit()
                return {"order": self._serialize_payment_order_for_kind(order)}
            if order.status == PAYMENT_ORDER_STATUS_CANCELED:
                session.commit()
                return {"order": self._serialize_payment_order_for_kind(order)}
            if order.status != PAYMENT_ORDER_STATUS_PENDING:
                raise CommercialConflictError(
                    "service.payment_order_not_cancelable",
                    "Only unpaid payment orders can be canceled",
                )
            gateway_config = self._payment_gateway_runtime_config(order.provider)
            if order.checkout_url and not bool(gateway_config.get("configured")):
                raise CommercialConflictError(
                    "service.payment_order_gateway_close_unavailable",
                    "The payment provider is not configured to close this order safely",
                )
            gateway = get_payment_gateway_provider(order.provider, config=gateway_config)
            close_result = gateway.close_order(
                PaymentGatewayCloseRequest(
                    provider=order.provider,
                    order_id=order.order_id,
                    external_order_no=order.external_order_no,
                    metadata=dict(order.metadata_json or {}),
                )
            )
            metadata = dict(order.metadata_json or {})
            metadata.update(
                {
                    "cancellation_reason": "customer_canceled",
                    "canceled_at": service._serialize_datetime(now),
                    "payment_gateway_close": close_result.provider_payload,
                }
            )
            order.status = PAYMENT_ORDER_STATUS_CANCELED
            order.canceled_at = now
            order.checkout_url = None
            order.metadata_json = metadata
            service._cancel_subscription_order_for_payment_in_session(
                repository=repository,
                payment_order_id=order.order_id,
            )
            payload: dict[str, object] = {
                "order": self._serialize_payment_order_for_kind(order)
            }
            service._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="payment_order.cancel",
                outcome="succeeded",
                account_id=account_id,
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
            pack = self._effective_credit_pack_from_session(session, pack_id)
            if pack is None or not bool(pack.get("active", True)):
                raise CommercialValidationError(
                    "service.credit_pack_not_found",
                    f"credit pack '{pack_id}' was not found",
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
            pack_amount = cast(float, pack["amount"])
            pack_ai_credits = cast(int, pack["ai_credits"])
            pack_validity_days = cast(int, pack["validity_days"])
            metadata = {
                "source": "portal_credit_pack",
                "purchase_kind": "credit_pack",
                "credit_pack": pack,
                "credit_pack_catalog_version": CREDIT_PACK_CATALOG_VERSION,
                "target_subscription_id": primary_subscription.subscription_id,
                "subscription_period_at_order_start_at": service._serialize_datetime(
                    period_start_at
                ),
                "subscription_period_at_order_end_at": service._serialize_datetime(period_end_at),
                "validity_days": pack_validity_days,
                "credit_expiry_policy": CREDIT_PACK_EXPIRY_POLICY,
                "grant_policy": "payment_success_grants_paid_credit_until_expiry",
            }
            gateway = get_payment_gateway_provider(
                normalized_provider,
                config=self._payment_gateway_runtime_config(normalized_provider),
            )
            payment_subject = build_credit_pack_payment_subject(
                pack_id=str(pack.get("pack_id") or pack_id),
                ai_credits=pack_ai_credits,
            )
            gateway_order = gateway.create_order(
                PaymentGatewayOrderRequest(
                    provider=normalized_provider,
                    order_id=order_id,
                    amount=round(pack_amount, 6),
                    currency=str(pack.get("currency") or "CNY"),
                    subject=payment_subject,
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
                amount=round(pack_amount, 6),
                currency=str(pack.get("currency") or "CNY"),
                subject=payment_subject,
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
            order = repository.get_payment_order_for_update(order_id)
            if order is None:
                raise CommercialNotFoundError(
                    "service.payment_order_not_found",
                    f"payment order '{order_id}' was not found",
                )
            if self._cancel_expired_pending_payment_order_in_session(order, now=now):
                cast(Any, self)._cancel_subscription_order_for_payment_in_session(
                    repository=repository,
                    payment_order_id=order.order_id,
                )
                session.commit()
                raise CommercialConflictError(
                    "service.payment_order_expired",
                    "expired payment orders cannot be marked paid",
                )
            if order.status == PAYMENT_ORDER_STATUS_CANCELED:
                raise CommercialConflictError(
                    "service.payment_order_canceled",
                    "canceled payment orders cannot be marked paid",
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
            if self._payment_order_purchase_kind(order) == "subscription_plan" and str(
                (order.metadata_json or {}).get("subscription_order_id") or ""
            ):
                payload = cast(Any, self)._apply_subscription_order_payment_in_session(
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
                    "billing_cycle": str(metadata.get("billing_cycle") or "monthly"),
                    "refund_window_end_at": service._serialize_datetime(order.refund_window_end_at),
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
            order = repository.get_payment_order_for_update(order_id)
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
            cast(Any, self)._assert_subscription_order_refundable_in_session(
                repository=repository,
                payment_order=order,
            )
            refund_amount = self._normalize_payment_amount(
                order.amount if amount is None else float(amount)
            )
            if refund_amount > float(order.amount):
                raise CommercialValidationError(
                    "service.payment_refund_amount_invalid",
                    "refund amount cannot exceed the payment order amount",
                )
            committed_refund_amount = sum(
                float(item.amount)
                for item in repository.list_payment_refunds(order.order_id)
                if item.status in {PAYMENT_REFUND_STATUS_REQUESTED, PAYMENT_REFUND_STATUS_SUCCEEDED}
            )
            if round(committed_refund_amount + refund_amount, 6) > round(float(order.amount), 6):
                raise CommercialValidationError(
                    "service.payment_refund_amount_invalid",
                    "refund requests cannot exceed the remaining paid amount",
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
            order = repository.get_payment_order_for_update(refund.order_id)
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
            restored_subscription = None
            succeeded_refund_amount = sum(
                float(item.amount)
                for item in repository.list_payment_refunds(order.order_id)
                if item.status == PAYMENT_REFUND_STATUS_SUCCEEDED
            )
            full_refund = round(succeeded_refund_amount, 6) >= round(float(order.amount), 6)
            if full_refund and order.status != PAYMENT_ORDER_STATUS_REFUNDED:
                order.status = PAYMENT_ORDER_STATUS_REFUNDED
                order.refunded_at = refund.succeeded_at or now
                is_subscription_order = bool(
                    str((order.metadata_json or {}).get("subscription_order_id") or "")
                )
                if is_subscription_order:
                    revoked_subscription = (
                        repository.get_subscription(order.subscription_id)
                        if order.subscription_id
                        else None
                    )
                    restored_subscription = cast(
                        Any, self
                    )._restore_subscription_order_after_full_refund_in_session(
                        repository=repository,
                        order=order,
                        now=refund.succeeded_at or now,
                    )
                elif order.subscription_id:
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
                "restored_subscription": (
                    service._serialize_subscription(restored_subscription)
                    if restored_subscription is not None
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
        validity_days = cast(int, pack["validity_days"])
        grant_expires_at = (order.paid_at or paid_at) + timedelta(days=validity_days)
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
                "validity_days": validity_days,
                "expiry_policy": CREDIT_PACK_EXPIRY_POLICY,
                "grant_expires_at": service._serialize_datetime(grant_expires_at),
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
        ai_credits = int(cast(Any, pack.get("ai_credits")) or 0)
        if not pack_id or ai_credits <= 0:
            return None
        validity_days = int(
            cast(Any, pack.get("validity_days")) or DEFAULT_CREDIT_PACK_VALIDITY_DAYS
        )
        return {
            **pack,
            "pack_id": pack_id,
            "ai_credits": ai_credits,
            "validity_days": validity_days,
        }

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
        if normalized != "CNY":
            raise CommercialValidationError(
                "service.payment_currency_unsupported",
                "payment currency must be CNY",
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

    def _normalize_payment_amount(self, amount: object) -> float:
        try:
            normalized = round(float(cast(Any, amount)), 6)
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
        created_at = self._normalize_payment_order_datetime(order.created_at)
        expires_at = (
            created_at + PAYMENT_ORDER_PENDING_TTL
            if order.status == PAYMENT_ORDER_STATUS_PENDING and created_at is not None
            else None
        )
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
            "available_actions": self._payment_order_available_actions(order),
            "purchase_kind": purchase_kind,
            "status_detail": self._payment_order_status_detail(order),
            "refund_window_end_at": service._serialize_datetime(order.refund_window_end_at),
            "paid_at": service._serialize_datetime(order.paid_at),
            "canceled_at": service._serialize_datetime(order.canceled_at),
            "expires_at": service._serialize_datetime(expires_at),
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

    def _payment_order_available_actions(self, order: PaymentOrder) -> list[str]:
        if order.status != PAYMENT_ORDER_STATUS_PENDING:
            return []
        actions = ["cancel"]
        if order.checkout_url:
            actions.insert(0, "continue_payment")
        return actions

    def _normalize_payment_order_datetime(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def _cancel_expired_pending_payment_order_in_session(
        self,
        order: PaymentOrder,
        *,
        now: datetime,
    ) -> bool:
        if order.status != PAYMENT_ORDER_STATUS_PENDING:
            return False
        created_at = self._normalize_payment_order_datetime(order.created_at)
        current_time = self._normalize_payment_order_datetime(now) or datetime.now(UTC)
        if created_at is None or created_at + PAYMENT_ORDER_PENDING_TTL > current_time:
            return False
        metadata = dict(order.metadata_json or {})
        metadata["cancellation_reason"] = "unpaid_order_expired"
        metadata["payment_order_expires_after_seconds"] = int(
            PAYMENT_ORDER_PENDING_TTL.total_seconds()
        )
        metadata["expired_at"] = cast(Any, self)._serialize_datetime(current_time)
        order.status = PAYMENT_ORDER_STATUS_CANCELED
        order.canceled_at = current_time
        order.metadata_json = metadata
        return True

    def _cancel_expired_pending_payment_orders_in_session(
        self,
        repository: CommercialRepository,
        *,
        account_id: str | None,
        site_id: str | None,
        now: datetime,
    ) -> int:
        current_time = self._normalize_payment_order_datetime(now) or datetime.now(UTC)
        cutoff = current_time - PAYMENT_ORDER_PENDING_TTL
        expired_orders = repository.list_pending_payment_orders_before(
            cutoff=cutoff,
            account_id=account_id,
            site_id=site_id,
        )
        expired_count = 0
        for order in expired_orders:
            if self._cancel_expired_pending_payment_order_in_session(
                order,
                now=current_time,
            ):
                cast(Any, self)._cancel_subscription_order_for_payment_in_session(
                    repository=repository,
                    payment_order_id=order.order_id,
                )
                expired_count += 1
        return expired_count

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
                    "Payment has been confirmed and related entitlements or credits were applied."
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
            metadata = dict(order.metadata_json or {})
            if metadata.get("cancellation_reason") == "unpaid_order_expired":
                return {
                    "code": "expired_unpaid",
                    "label": "Expired",
                    "detail": "The payment order expired before provider confirmation.",
                    "next_action": "none",
                    "simulated_payment": False,
                }
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
