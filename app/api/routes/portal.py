from __future__ import annotations

import json
import secrets
from datetime import datetime
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.adapters.notifications.base import PortalEmailDeliveryError
from app.adapters.notifications.smtp import build_portal_email_sender
from app.api.auth import (
    AUTHORIZATION_HEADER,
    PortalBearerTokenError,
    enforce_portal_login_code_request_rate_limit,
    get_cloud_services,
    resolve_portal_login_code_ttl_seconds,
)
from app.api.browser_security import enforce_browser_same_origin
from app.api.envelope import build_envelope
from app.api.portal_locale import resolve_portal_email_locale
from app.api.portal_session import (
    build_new_portal_session_metadata,
    clear_portal_session_cookies,
    portal_cookie_secure,
    portal_idempotency_replay_response,
    portal_json_error,
    project_portal_subscription,
    resolve_portal_login_session_ttl_seconds,
    resolve_portal_request_context,
    serialize_portal_session,
    set_portal_session_cookies,
)
from app.api.routes.service import (
    _build_audit_context,
    _get_commercial_service,
    _service_error_response,
)
from app.core.models import PLATFORM_KIND_WORDPRESS
from app.domain.advisor.service import InternalAIAdvisorService
from app.domain.agent_workflow_metadata import (
    MEDIA_DERIVATIVE_WORKFLOW_ID,
    get_agent_handoff_metadata,
    get_workflow_metadata,
)
from app.domain.commercial.audit_context import ServiceAuditContext
from app.domain.commercial.errors import CommercialPermissionError, CommercialServiceError
from app.domain.commercial.identity import (
    USER_ALLOWED_ACTION_PROVISION_SITES,
    USER_ALLOWED_ACTION_REMOVE_SITES,
    USER_ALLOWED_ACTION_VIEW_AUDIT,
    USER_ALLOWED_ACTION_VIEW_BILLING,
    USER_ALLOWED_ACTION_VIEW_USAGE,
)
from app.domain.hosted_model_defaults import FREE_GPT55_MODEL_ID
from app.domain.media_derivatives.metrics import MediaDerivativeObservabilityService
from app.domain.observability.plugin_events import PluginObservabilityService
from app.domain.observability.site_monitoring_overview import SiteMonitoringOverviewService
from app.domain.portal_idempotency import build_portal_business_idempotency_key
from app.domain.service_settings import (
    resolve_portal_qq_runtime_config,
)
from app.domain.site_knowledge.metrics import SiteKnowledgeObservabilityService
from app.domain.usage.service import UsageService

router = APIRouter(prefix="/portal/v1", tags=["portal"])
COOKIE_PORTAL_QQ_OAUTH_NONCE = "npcink_portal_qq_oauth_nonce"
COOKIE_PORTAL_QQ_OAUTH_NONCE_PATH = "/"


class PortalSessionSitePayload(BaseModel):
    site_id: str = ""


class PortalAddonConnectionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str = ""
    site_name: str = ""
    site_url: str = Field(default="", max_length=2048)
    return_url: str = ""
    state: str = ""


class PortalAddonConnectionExchangePayload(BaseModel):
    code: str = ""
    state: str = ""


class PortalLoginCodeRequestPayload(BaseModel):
    email: str = ""
    locale: str = ""


class PortalLoginCodeVerifyPayload(BaseModel):
    email: str = ""
    code: str = ""
    remember_me: bool = False


class PortalEmailChangeRequestPayload(BaseModel):
    new_email: str = ""
    locale: str = ""


class PortalEmailChangeVerifyPayload(BaseModel):
    new_email: str = ""
    code: str = ""


class PortalRegistrationCodeRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = ""
    site_url: str = Field(default="", max_length=2048)
    site_name: str = ""
    use_case: str = ""
    locale: str = ""


class PortalRegistrationVerifyPayload(BaseModel):
    email: str = ""
    code: str = ""


class PortalQQBindPayload(BaseModel):
    code: str = ""
    state: str = ""
    nonce: str = ""


class PortalQQUnbindPayload(BaseModel):
    provider: str = "qq"


class PortalAIInsightAnalyzePayload(BaseModel):
    force_refresh: bool = False


class PortalCreditPackOrderPayload(BaseModel):
    pack_id: str = ""
    provider: str = "alipay"


class PortalPlanTrialPayload(BaseModel):
    tier_id: str = Field(default="plus", pattern="^(plus|pro)$")


class PortalSubscriptionOrderPayload(BaseModel):
    offer_id: str = Field(min_length=1, max_length=191)
    provider: str = Field(default="alipay", pattern="^alipay$")


class PortalSupportRequestPayload(BaseModel):
    topic: str = Field(default="general", max_length=64)
    title: str = Field(default="", max_length=191)
    description: str = Field(default="", max_length=4000)
    site_id: str = Field(default="", max_length=191)
    source_path: str = Field(default="", max_length=191)
    context: dict[str, Any] = Field(default_factory=dict)


class PortalSupportRequestMessagePayload(BaseModel):
    body: str = Field(default="", max_length=4000)


class PortalSupportRequestAttachmentPayload(BaseModel):
    filename: str = Field(default="", max_length=191)
    content_type: str = Field(default="", max_length=128)
    content_base64: str = ""
    message_id: str = Field(default="", max_length=191)


class PortalSupportRequestFeedbackPayload(BaseModel):
    resolved: bool = True
    rating: int = Field(default=5, ge=1, le=5)
    comment: str = Field(default="", max_length=2000)


def _object_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _portal_site_response_data(value: object) -> dict[str, object]:
    data = dict(_dict_value(value))
    for field in ("account_id", "principal_id", "identity_type", "role", "allowed_actions"):
        data.pop(field, None)
    return data


def _portal_identity_binding_response_data(value: object) -> dict[str, object]:
    binding = _dict_value(value)
    return {
        "binding_id": str(binding.get("binding_id") or ""),
        "provider": str(binding.get("provider") or ""),
        "status": str(binding.get("status") or ""),
        "has_unionid": bool(binding.get("has_unionid")),
        "last_login_at": str(binding.get("last_login_at") or ""),
    }


def _portal_public_site_data(value: object) -> dict[str, object]:
    site = _dict_value(value)
    return {
        "site_id": str(site.get("site_id") or ""),
        "name": str(site.get("name") or ""),
        "site_url": str(site.get("site_url") or ""),
        "platform_kind": str(site.get("platform_kind") or ""),
        "status": str(site.get("status") or ""),
        "created_at": str(site.get("created_at") or ""),
    }


def _portal_public_plan_version_data(value: object) -> dict[str, object] | None:
    plan_version = _dict_value(value)
    if not plan_version:
        return None
    return {
        "plan_version_id": str(plan_version.get("plan_version_id") or ""),
        "plan_id": str(plan_version.get("plan_id") or ""),
        "version_label": str(plan_version.get("version_label") or ""),
        "status": str(plan_version.get("status") or ""),
        "currency": str(plan_version.get("currency") or ""),
        "entitlements": _dict_value(plan_version.get("entitlements")),
        "budgets": _dict_value(plan_version.get("budgets")),
    }


def _portal_public_entitlement_snapshot_data(value: object) -> dict[str, object] | None:
    snapshot = _dict_value(value)
    if not snapshot:
        return None
    return {
        "subscription_id": str(snapshot.get("subscription_id") or ""),
        "plan_version_id": str(snapshot.get("plan_version_id") or ""),
        "status": str(snapshot.get("status") or ""),
        "entitlements": _dict_value(snapshot.get("entitlements")),
        "budgets": _dict_value(snapshot.get("budgets")),
        "site_limit": int(snapshot.get("site_limit") or 0),
        "generated_at": str(snapshot.get("generated_at") or ""),
    }


def _portal_public_commercial_policy_data(value: object) -> dict[str, object]:
    policy = _dict_value(value)
    subscription = _dict_value(policy.get("subscription"))
    return {
        "subscription": {
            "grace_period_days": int(subscription.get("grace_period_days") or 0),
        }
    }


def _portal_public_usage_totals_data(value: object) -> dict[str, object]:
    totals = _dict_value(value)
    return {
        "runs": int(totals.get("runs") or 0),
        "requests": int(totals.get("requests") or 0),
        "provider_calls": int(totals.get("provider_calls") or 0),
        "tokens": int(totals.get("tokens") or 0),
        "tokens_total": int(totals.get("tokens_total") or 0),
        "cost": float(totals.get("cost") or 0),
    }


def _portal_public_subscription_grace_data(value: object) -> dict[str, object]:
    grace = _dict_value(value)
    return {
        "active": bool(grace.get("active")),
        "subscription_status": str(grace.get("subscription_status") or ""),
        "grace_period_days": int(grace.get("grace_period_days") or 0),
        "grace_until_at": str(grace.get("grace_until_at") or ""),
    }


def _portal_public_budget_state_data(value: object) -> dict[str, object]:
    budget_state = _dict_value(value)
    return {
        str(key): {
            "current_total": float(item.get("current_total") or 0),
            "limit": float(item.get("limit") or 0),
            "grace_requests": int(item.get("grace_requests") or 0),
            "used_grace_requests": int(item.get("used_grace_requests") or 0),
            "remaining_grace_requests": int(item.get("remaining_grace_requests") or 0),
            "over_limit": bool(item.get("over_limit")),
        }
        for key, item in budget_state.items()
        if isinstance(item, dict)
    }


def _portal_public_quota_summary_data(value: object) -> dict[str, object]:
    summary = _dict_value(value)
    return {
        "generated_at": str(summary.get("generated_at") or ""),
        "period_start_at": str(summary.get("period_start_at") or ""),
        "period_end_at": str(summary.get("period_end_at") or ""),
        "status": str(summary.get("status") or ""),
        "credit": _dict_value(summary.get("credit")),
        "credit_ledger_summary": _dict_value(summary.get("credit_ledger_summary")),
        "credit_policy": _dict_value(summary.get("credit_policy")),
        "resource_limits": _object_list(summary.get("resource_limits")),
        "breakdown": _object_list(summary.get("breakdown")),
        "credit_usage_detail": _dict_value(summary.get("credit_usage_detail")),
    }


def _portal_pagination_data(value: object) -> dict[str, object]:
    pagination = _dict_value(value)
    return {
        "limit": int(pagination.get("limit") or 0),
        "offset": int(pagination.get("offset") or 0),
        "total": int(pagination.get("total") or 0),
        "has_more": bool(pagination.get("has_more")),
    }


def _portal_credit_pack_data(value: object) -> dict[str, object]:
    pack = _dict_value(value)
    return {
        "pack_id": str(pack.get("pack_id") or ""),
        "label": str(pack.get("label") or ""),
        "ai_credits": int(pack.get("ai_credits") or 0),
        "amount": float(pack.get("amount") or 0),
        "currency": str(pack.get("currency") or ""),
        "validity_days": int(pack.get("validity_days") or 0),
        "recommended_for_tiers": [
            str(item) for item in _object_list(pack.get("recommended_for_tiers"))
        ],
        "active": bool(pack.get("active")),
        "period_policy": str(pack.get("period_policy") or ""),
        "grant_event_type": str(pack.get("grant_event_type") or ""),
        "catalog_version": str(pack.get("catalog_version") or ""),
    }


def _portal_credit_pack_catalog_data(
    value: object,
    *,
    site_id: str = "",
) -> dict[str, object]:
    catalog = _dict_value(value)
    data: dict[str, object] = {
        "catalog_version": str(catalog.get("catalog_version") or ""),
        "period_policy": str(catalog.get("period_policy") or ""),
        "expiry_policy": str(catalog.get("expiry_policy") or ""),
        "default_validity_days": int(catalog.get("default_validity_days") or 0),
        "grant_event_type": str(catalog.get("grant_event_type") or ""),
        "items": [
            _portal_credit_pack_data(item)
            for item in _object_list(catalog.get("items"))
        ],
    }
    if site_id:
        data["site_id"] = site_id
    return data


def _portal_plan_offer_data(value: object) -> dict[str, object]:
    offer = _dict_value(value)
    return {
        "offer_id": str(offer.get("offer_id") or ""),
        "plan_id": str(offer.get("plan_id") or ""),
        "plan_version_id": str(offer.get("plan_version_id") or ""),
        "tier_id": str(offer.get("tier_id") or ""),
        "billing_cycle": str(offer.get("billing_cycle") or ""),
        "amount": float(offer.get("amount") or 0),
        "currency": str(offer.get("currency") or ""),
        "purchase_mode": str(offer.get("purchase_mode") or ""),
        "status": str(offer.get("status") or ""),
        "trial_enabled": bool(offer.get("trial_enabled")),
        "trial_days": int(offer.get("trial_days") or 0),
        "trial_credit_limit": int(offer.get("trial_credit_limit") or 0),
        "trial_requires_approval": bool(offer.get("trial_requires_approval")),
        "valid_from_at": str(offer.get("valid_from_at") or ""),
        "valid_until_at": str(offer.get("valid_until_at") or ""),
    }


def _portal_plan_comparison_right_data(value: object) -> dict[str, object]:
    right = _dict_value(value)
    raw_value = right.get("value")
    return {
        "state": str(right.get("state") or ""),
        "value": int(raw_value) if isinstance(raw_value, (int, float)) else None,
    }


def _portal_plan_comparison_tier_data(value: object) -> dict[str, object]:
    tier = _dict_value(value)
    rights = _dict_value(tier.get("comparison_rights"))
    return {
        "tier_id": str(tier.get("tier_id") or ""),
        "label": str(tier.get("label") or ""),
        "plan_id": str(tier.get("plan_id") or ""),
        "plan_version_id": str(tier.get("plan_version_id") or ""),
        "monthly_points": tier.get("monthly_points"),
        "site_limit": tier.get("site_limit"),
        "knowledge_article_limit": tier.get("knowledge_article_limit"),
        "concurrency_limit": tier.get("concurrency_limit"),
        "batch_item_limit": tier.get("batch_item_limit"),
        "comparison_rights": {
            key: _portal_plan_comparison_right_data(rights.get(key))
            for key in (
                "monthly_points",
                "site_limit",
                "knowledge_article_limit",
                "concurrency_limit",
                "batch_item_limit",
            )
        },
        "amount": tier.get("amount"),
        "currency": str(tier.get("currency") or ""),
        "billing_cycle": tier.get("billing_cycle"),
        "purchase_mode": str(tier.get("purchase_mode") or ""),
    }


def _portal_plan_offer_trial_data(value: object) -> dict[str, object]:
    trial = _dict_value(value)
    return {
        "available": bool(trial.get("available")),
        "status": str(trial.get("status") or ""),
        "state": str(trial.get("state") or ""),
        "reason_code": str(trial.get("reason_code") or ""),
        "allowed_tiers": [
            str(item) for item in _object_list(trial.get("allowed_tiers"))
        ],
        "tier_id": str(trial.get("tier_id") or ""),
        "highest_tier_id": str(trial.get("highest_tier_id") or ""),
        "trial_days": int(trial.get("trial_days") or 0),
        "credit_limit": int(trial.get("credit_limit") or 0),
        "trial_started_at": str(trial.get("trial_started_at") or ""),
        "trial_ends_at": str(trial.get("trial_ends_at") or ""),
    }


def _portal_started_trial_data(value: object) -> dict[str, object]:
    trial = _dict_value(value)
    return {
        "available": bool(trial.get("available")),
        "status": str(trial.get("status") or ""),
        "tier_id": str(trial.get("tier_id") or ""),
        "trial_days": int(trial.get("trial_days") or 0),
        "credit_limit": int(trial.get("credit_limit") or 0),
        "trial_started_at": str(trial.get("trial_started_at") or ""),
        "trial_ends_at": str(trial.get("trial_ends_at") or ""),
        "monthly_price_cny": float(trial.get("monthly_price_cny") or 0),
    }


def _portal_plan_offer_list_data(value: object) -> dict[str, object]:
    offers = _dict_value(value)
    return {
        "items": [
            _portal_plan_offer_data(item) for item in _object_list(offers.get("items"))
        ],
        "comparison_tiers": [
            _portal_plan_comparison_tier_data(item)
            for item in _object_list(offers.get("comparison_tiers"))
        ],
        "trial": _portal_plan_offer_trial_data(offers.get("trial")),
    }


def _portal_subscription_order_data(value: object) -> dict[str, object]:
    order = _dict_value(value)
    return {
        "subscription_order_id": str(order.get("subscription_order_id") or ""),
        "offer_id": str(order.get("offer_id") or ""),
        "payment_order_id": str(order.get("payment_order_id") or ""),
        "source_subscription_id": str(order.get("source_subscription_id") or ""),
        "target_plan_id": str(order.get("target_plan_id") or ""),
        "target_plan_version_id": str(order.get("target_plan_version_id") or ""),
        "order_kind": str(order.get("order_kind") or ""),
        "status": str(order.get("status") or ""),
        "list_amount": float(order.get("list_amount") or 0),
        "credit_amount": float(order.get("credit_amount") or 0),
        "payable_amount": float(order.get("payable_amount") or 0),
        "currency": str(order.get("currency") or ""),
        "effective_at": str(order.get("effective_at") or ""),
        "period_start_at": str(order.get("period_start_at") or ""),
        "period_end_at": str(order.get("period_end_at") or ""),
    }


def _portal_payment_order_data(value: object) -> dict[str, object]:
    order = _dict_value(value)
    metadata = _dict_value(order.get("metadata"))
    status_detail = _dict_value(order.get("status_detail"))
    credit_pack = order.get("credit_pack") or metadata.get("credit_pack")
    data: dict[str, object] = {
        "order_id": str(order.get("order_id") or ""),
        "site_id": str(order.get("site_id") or ""),
        "subscription_id": str(order.get("subscription_id") or ""),
        "target_subscription_id": str(
            order.get("target_subscription_id")
            or metadata.get("target_subscription_id")
            or ""
        ),
        "target_tier_id": str(
            order.get("target_tier_id") or metadata.get("target_tier_id") or ""
        ),
        "plan_id": str(order.get("plan_id") or ""),
        "plan_version_id": str(order.get("plan_version_id") or ""),
        "provider": str(order.get("provider") or ""),
        "status": str(order.get("status") or ""),
        "amount": float(order.get("amount") or 0),
        "currency": str(order.get("currency") or ""),
        "subject": str(order.get("subject") or ""),
        "checkout_url": str(order.get("checkout_url") or ""),
        "available_actions": [
            str(item) for item in _object_list(order.get("available_actions"))
        ],
        "purchase_kind": str(order.get("purchase_kind") or ""),
        "status_detail": {
            "code": str(status_detail.get("code") or ""),
            "label": str(status_detail.get("label") or ""),
            "detail": str(status_detail.get("detail") or ""),
            "next_action": str(status_detail.get("next_action") or ""),
            "simulated_payment": bool(status_detail.get("simulated_payment")),
        },
        "refund_window_end_at": str(order.get("refund_window_end_at") or ""),
        "paid_at": str(order.get("paid_at") or ""),
        "canceled_at": str(order.get("canceled_at") or ""),
        "expires_at": str(order.get("expires_at") or ""),
        "refunded_at": str(order.get("refunded_at") or ""),
        "created_at": str(order.get("created_at") or ""),
        "updated_at": str(order.get("updated_at") or ""),
    }
    if credit_pack:
        data["credit_pack"] = _portal_credit_pack_data(credit_pack)
    return data


def _portal_subscription_order_payload_data(value: object) -> dict[str, object]:
    payload = _dict_value(value)
    return {
        "order": _portal_payment_order_data(payload.get("order")),
        "subscription_order": _portal_subscription_order_data(
            payload.get("subscription_order")
        ),
    }


def _portal_payment_order_payload_data(
    value: object,
    *,
    site_id: str = "",
) -> dict[str, object]:
    payload = _dict_value(value)
    data: dict[str, object] = {
        "order": _portal_payment_order_data(payload.get("order")),
    }
    if site_id:
        data["site_id"] = site_id
    return data


def _portal_payment_order_list_data(
    value: object,
    *,
    site_id: str = "",
) -> dict[str, object]:
    payload = _dict_value(value)
    counts = _dict_value(payload.get("counts"))
    visibility = _dict_value(payload.get("visibility"))
    data: dict[str, object] = {
        "generated_at": str(payload.get("generated_at") or ""),
        "status_group": str(payload.get("status_group") or ""),
        "counts": {
            key: int(counts.get(key) or 0)
            for key in ("all", "pending", "paid", "closed")
        },
        "visibility": {
            "canceled_orders_visible_days": int(
                visibility.get("canceled_orders_visible_days") or 0
            ),
            "database_records_deleted": bool(
                visibility.get("database_records_deleted")
            ),
        },
        "pagination": _portal_pagination_data(payload.get("pagination")),
        "items": [
            _portal_payment_order_data(item)
            for item in _object_list(payload.get("items"))
        ],
    }
    if site_id:
        data["site_id"] = site_id
    return data


def _portal_credit_ledger_entry_data(value: object) -> dict[str, object]:
    entry = _dict_value(value)
    return {
        key: entry.get(key)
        for key in (
            "ledger_entry_id",
            "site_id",
            "event_type",
            "source_type",
            "category",
            "category_label",
            "feature_key",
            "feature_label",
            "feature_detail",
            "direction",
            "explanation",
            "source_id",
            "run_id",
            "credit_delta",
            "consumed_credits",
            "granted_credits",
            "net_credit_delta",
            "quantity",
            "unit",
            "rate",
            "rate_unit",
            "rate_version",
            "created_at",
        )
        if key in entry
    }


def _portal_credit_breakdown_item_data(value: object) -> dict[str, object]:
    item = _dict_value(value)
    return {
        key: item.get(key)
        for key in (
            "key",
            "label",
            "quantity",
            "unit",
            "rate",
            "rate_unit",
            "credits",
            "capability_group",
        )
    }


def _portal_credit_summary_data(value: object) -> dict[str, object]:
    summary = _dict_value(value)
    category_totals = _dict_value(summary.get("category_totals"))
    return {
        "total_credits": float(summary.get("total_credits") or 0),
        "consumed_credits": float(summary.get("consumed_credits") or 0),
        "granted_credits": float(summary.get("granted_credits") or 0),
        "adjustment_credits": float(summary.get("adjustment_credits") or 0),
        "refund_credits": float(summary.get("refund_credits") or 0),
        "net_credit_delta": float(summary.get("net_credit_delta") or 0),
        "net_used_credits": float(summary.get("net_used_credits") or 0),
        "entry_count": int(summary.get("entry_count") or 0),
        "category_totals": {
            str(key): {
                "label": str(_dict_value(item).get("label") or ""),
                "net_credit_delta": float(
                    _dict_value(item).get("net_credit_delta") or 0
                ),
            }
            for key, item in category_totals.items()
        },
        "breakdown": [
            _portal_credit_breakdown_item_data(item)
            for item in _object_list(summary.get("breakdown"))
        ],
    }


def _portal_credit_usage_detail_data(value: object) -> dict[str, object]:
    detail = _dict_value(value)
    period = _dict_value(detail.get("period"))
    summary = _dict_value(detail.get("summary"))
    copy = _dict_value(detail.get("copy"))
    paths = _dict_value(detail.get("portal_paths"))
    return {
        "surface": str(detail.get("surface") or ""),
        "default_visibility": str(detail.get("default_visibility") or ""),
        "local_addon_policy": str(detail.get("local_addon_policy") or ""),
        "generated_at": str(detail.get("generated_at") or ""),
        "period": {
            "start_at": str(period.get("start_at") or ""),
            "end_at": str(period.get("end_at") or ""),
        },
        "summary": {
            "used": float(summary.get("used") or 0),
            "limit": float(summary.get("limit") or 0),
            "remaining": summary.get("remaining"),
            "status": str(summary.get("status") or ""),
            "unit": str(summary.get("unit") or ""),
            "rate_version": str(summary.get("rate_version") or ""),
        },
        "breakdown": [
            _portal_credit_breakdown_item_data(item)
            for item in _object_list(detail.get("breakdown"))
        ],
        "recent_items": [
            _portal_credit_ledger_entry_data(item)
            for item in _object_list(detail.get("recent_items"))
        ],
        "copy": {
            "title": str(copy.get("title") or ""),
            "summary": str(copy.get("summary") or ""),
            "addon_summary": str(copy.get("addon_summary") or ""),
        },
        "legend": [
            {
                "category": str(_dict_value(item).get("category") or ""),
                "label": str(_dict_value(item).get("label") or ""),
            }
            for item in _object_list(detail.get("legend"))
        ],
        "portal_paths": {
            "credit_usage": str(paths.get("credit_usage") or ""),
            "credit_ledger": str(paths.get("credit_ledger") or ""),
        },
    }


def _portal_credit_ledger_data(
    value: object,
    *,
    site_id: str = "",
) -> dict[str, object]:
    ledger = _dict_value(value)
    data: dict[str, object] = {
        "generated_at": str(ledger.get("generated_at") or ""),
        "period_start_at": str(ledger.get("period_start_at") or ""),
        "period_end_at": str(ledger.get("period_end_at") or ""),
        "rate_version": str(ledger.get("rate_version") or ""),
        "pagination": _portal_pagination_data(ledger.get("pagination")),
        "summary": _portal_credit_summary_data(ledger.get("summary")),
        "usage_detail": _portal_credit_usage_detail_data(ledger.get("usage_detail")),
        "items": [
            _portal_credit_ledger_entry_data(item)
            for item in _object_list(ledger.get("items"))
        ],
    }
    if site_id:
        data["site_id"] = site_id
    return data


def _portal_credit_trend_data(value: object) -> dict[str, object]:
    trend = _dict_value(value)
    return {
        "contract_version": str(trend.get("contract_version") or ""),
        "generated_at": str(trend.get("generated_at") or ""),
        "site_id": str(trend.get("site_id") or ""),
        "window": str(trend.get("window") or ""),
        "bucket_seconds": int(trend.get("bucket_seconds") or 0),
        "start_at": str(trend.get("start_at") or ""),
        "end_at": str(trend.get("end_at") or ""),
        "total_credits": float(trend.get("total_credits") or 0),
        "entry_count": int(trend.get("entry_count") or 0),
        "points": [
            {
                "start_at": str(_dict_value(item).get("start_at") or ""),
                "end_at": str(_dict_value(item).get("end_at") or ""),
                "credits": float(_dict_value(item).get("credits") or 0),
                "entry_count": int(_dict_value(item).get("entry_count") or 0),
            }
            for item in _object_list(trend.get("points"))
        ],
    }


def _portal_credit_events_data(value: object) -> dict[str, object]:
    events = _dict_value(value)
    filters = _dict_value(events.get("filters"))
    summary = _dict_value(events.get("summary"))
    return {
        "contract_version": str(events.get("contract_version") or ""),
        "generated_at": str(events.get("generated_at") or ""),
        "period_start_at": str(events.get("period_start_at") or ""),
        "period_end_at": str(events.get("period_end_at") or ""),
        "filters": {
            "window": str(filters.get("window") or ""),
            "site_id": str(filters.get("site_id") or ""),
            "feature": str(filters.get("feature") or ""),
        },
        "summary": {
            "event_count": int(summary.get("event_count") or 0),
            "consumed_credits": float(summary.get("consumed_credits") or 0),
        },
        "pagination": _portal_pagination_data(events.get("pagination")),
        "items": [
            {
                key: _dict_value(item).get(key)
                for key in (
                    "event_id",
                    "support_reference",
                    "site_id",
                    "feature_key",
                    "feature_label",
                    "feature_detail",
                    "created_at",
                    "net_credit_delta",
                    "consumed_credits",
                    "direction",
                    "component_count",
                )
            }
            | {
                "components": [
                    {
                        "key": str(_dict_value(component).get("key") or ""),
                        "credits": float(_dict_value(component).get("credits") or 0),
                    }
                    for component in _object_list(_dict_value(item).get("components"))
                ]
            }
            for item in _object_list(events.get("items"))
        ],
    }


def _portal_credit_event_buckets_data(value: object) -> dict[str, object]:
    buckets = _dict_value(value)
    filters = _dict_value(buckets.get("filters"))
    summary = _dict_value(buckets.get("summary"))
    return {
        "contract_version": str(buckets.get("contract_version") or ""),
        "generated_at": str(buckets.get("generated_at") or ""),
        "period_start_at": str(buckets.get("period_start_at") or ""),
        "period_end_at": str(buckets.get("period_end_at") or ""),
        "bucket": str(buckets.get("bucket") or ""),
        "bucket_seconds": int(buckets.get("bucket_seconds") or 0),
        "timezone": str(buckets.get("timezone") or ""),
        "filters": {
            "window": str(filters.get("window") or ""),
            "site_id": str(filters.get("site_id") or ""),
            "feature": str(filters.get("feature") or ""),
        },
        "summary": {
            "bucket_count": int(summary.get("bucket_count") or 0),
            "consumed_credits": float(summary.get("consumed_credits") or 0),
        },
        "pagination": _portal_pagination_data(buckets.get("pagination")),
        "items": [
            {
                key: _dict_value(item).get(key)
                for key in (
                    "bucket_id",
                    "start_at",
                    "end_at",
                    "consumed_credits",
                    "event_count",
                    "site_count",
                    "top_feature_key",
                )
            }
            | {
                "feature_totals": [
                    {
                        "feature_key": str(
                            _dict_value(total).get("feature_key") or ""
                        ),
                        "consumed_credits": float(
                            _dict_value(total).get("consumed_credits") or 0
                        ),
                        "event_count": int(
                            _dict_value(total).get("event_count") or 0
                        ),
                    }
                    for total in _object_list(
                        _dict_value(item).get("feature_totals")
                    )
                ]
            }
            for item in _object_list(buckets.get("items"))
        ],
    }


def _portal_billing_totals_data(value: object) -> dict[str, object]:
    totals = _dict_value(value)
    return {
        "runs": int(totals.get("runs") or 0),
        "provider_calls": int(totals.get("provider_calls") or 0),
        "tokens_in": int(totals.get("tokens_in") or 0),
        "tokens_out": int(totals.get("tokens_out") or 0),
        "tokens_total": int(totals.get("tokens_total") or 0),
        "cost": float(totals.get("cost") or 0),
    }


def _portal_billing_delta_data(value: object) -> dict[str, object]:
    deltas = _dict_value(value)
    return {
        "runs": float(deltas.get("runs") or 0),
        "provider_calls": float(deltas.get("provider_calls") or 0),
        "tokens_total": float(deltas.get("tokens_total") or 0),
        "cost": float(deltas.get("cost") or 0),
    }


def _portal_billing_snapshot_data(value: object) -> dict[str, object] | None:
    snapshot = _dict_value(value)
    if not snapshot:
        return None
    return {
        "snapshot_id": str(snapshot.get("snapshot_id") or ""),
        "site_id": str(snapshot.get("site_id") or ""),
        "subscription_id": str(snapshot.get("subscription_id") or ""),
        "plan_version_id": str(snapshot.get("plan_version_id") or ""),
        "currency": str(snapshot.get("currency") or ""),
        "period_start_at": str(snapshot.get("period_start_at") or ""),
        "period_end_at": str(snapshot.get("period_end_at") or ""),
        "totals": _portal_billing_totals_data(snapshot.get("totals")),
        "breakdown": _dict_value(snapshot.get("breakdown")),
        "generated_at": str(snapshot.get("generated_at") or ""),
    }


def _portal_billing_snapshot_list_data(
    value: object,
    *,
    site_id: str,
) -> dict[str, object]:
    snapshots = _dict_value(value)
    return {
        "site_id": site_id,
        "items": [
            projected
            for item in _object_list(snapshots.get("items"))
            if (projected := _portal_billing_snapshot_data(item)) is not None
        ],
    }


def _portal_billing_reconciliation_data(
    value: object,
    *,
    site_id: str,
) -> dict[str, object]:
    payload = _dict_value(value)
    reconciliation = _dict_value(payload.get("reconciliation"))
    deltas = _dict_value(reconciliation.get("deltas"))
    return {
        "site_id": site_id,
        "ledger_totals": _portal_billing_delta_data(payload.get("ledger_totals")),
        "snapshot": _portal_billing_snapshot_data(payload.get("snapshot")),
        "reconciliation": {
            "in_sync": bool(reconciliation.get("in_sync")),
            "deltas": _portal_billing_delta_data(deltas),
        },
    }


def _portal_plan_trial_response_data(
    value: object,
    *,
    session: dict[str, object],
) -> dict[str, object]:
    result = _dict_value(value)
    subscription = _dict_value(result.get("subscription"))
    return {
        "subscription": project_portal_subscription(subscription),
        "entitlement_snapshot": _portal_public_entitlement_snapshot_data(
            result.get("entitlement_snapshot")
        ),
        "trial": _portal_started_trial_data(result.get("trial")),
        "session": session,
    }


def _portal_free_downgrade_data(value: object) -> dict[str, object]:
    result = _dict_value(value)
    return {
        "scheduled_tier_id": str(result.get("scheduled_tier_id") or ""),
        "scheduled_change_at": str(result.get("scheduled_change_at") or ""),
    }


def _portal_remove_site_data(value: object) -> dict[str, object]:
    result = _dict_value(value)
    return {
        "site": _portal_public_site_data(result.get("site")),
        "revoked_key_ids": [
            str(item) for item in _object_list(result.get("revoked_key_ids"))
        ],
    }


def _portal_site_summary_response_data(value: object) -> dict[str, object]:
    summary = _dict_value(value)
    coverage = _dict_value(summary.get("coverage"))
    subscription = _dict_value(coverage.get("subscription"))
    public_subscription = (
        project_portal_subscription(subscription) if subscription else {}
    )
    plan_version = _dict_value(coverage.get("plan_version"))
    customer_status = _dict_value(summary.get("customer_status"))
    return {
        "site_id": str(summary.get("site_id") or ""),
        "site": _portal_public_site_data(summary.get("site")),
        "covered_by_subscription_id": str(
            summary.get("covered_by_subscription_id") or ""
        ),
        "subscription_status": str(summary.get("subscription_status") or ""),
        "package_alias": str(summary.get("package_alias") or ""),
        "coverage": {
            "subscription_id": str(public_subscription.get("subscription_id") or ""),
            "status": str(public_subscription.get("status") or ""),
            "plan_id": str(public_subscription.get("plan_id") or ""),
            "plan_version_id": str(
                public_subscription.get("plan_version_id")
                or plan_version.get("plan_version_id")
                or ""
            ),
            "package_alias": str(public_subscription.get("package_alias") or ""),
            "current_period_start": str(
                subscription.get("current_period_start")
                or public_subscription.get("current_period_start_at")
                or ""
            ),
            "current_period_end": str(
                subscription.get("current_period_end")
                or public_subscription.get("current_period_end_at")
                or ""
            ),
            "current_period_start_at": str(
                public_subscription.get("current_period_start_at") or ""
            ),
            "current_period_end_at": str(
                public_subscription.get("current_period_end_at") or ""
            ),
        },
        "entitlement_snapshot": _portal_public_entitlement_snapshot_data(
            coverage.get("entitlement_snapshot")
        ),
        "customer_status": {
            "status": str(customer_status.get("status") or ""),
            "needs_attention": bool(customer_status.get("needs_attention")),
            "issue_count": int(customer_status.get("issue_count") or 0),
            "generated_at": str(customer_status.get("generated_at") or ""),
        },
        "generated_at": str(summary.get("generated_at") or ""),
    }


def _portal_site_entitlements_response_data(value: object) -> dict[str, object]:
    entitlements = _dict_value(value)
    subscription = _dict_value(entitlements.get("subscription"))
    return {
        "site_id": str(entitlements.get("site_id") or ""),
        "site": _portal_public_site_data(entitlements.get("site")),
        "subscription": project_portal_subscription(subscription) if subscription else None,
        "plan_version": _portal_public_plan_version_data(entitlements.get("plan_version")),
        "entitlement_snapshot": _portal_public_entitlement_snapshot_data(
            entitlements.get("entitlement_snapshot")
        ),
        "policy": _portal_public_commercial_policy_data(entitlements.get("policy")),
        "period_start_at": str(entitlements.get("period_start_at") or ""),
        "period_end_at": str(entitlements.get("period_end_at") or ""),
        "usage_totals": _portal_public_usage_totals_data(entitlements.get("usage_totals")),
        "subscription_grace": _portal_public_subscription_grace_data(
            entitlements.get("subscription_grace")
        ),
        "budget_state": _portal_public_budget_state_data(entitlements.get("budget_state")),
        "quota_summary": _portal_public_quota_summary_data(
            entitlements.get("quota_summary")
        ),
        "generated_at": str(entitlements.get("generated_at") or ""),
    }


def _portal_audit_group_data(value: object) -> dict[str, object]:
    group = _dict_value(value)
    return {
        "event_kind": str(group.get("event_kind") or ""),
        "outcome": str(group.get("outcome") or ""),
        "count": int(group.get("count") or 0),
        "first_seen_at": str(group.get("first_seen_at") or ""),
        "last_seen_at": str(group.get("last_seen_at") or ""),
    }


def _portal_audit_summary_response_data(
    value: object,
    *,
    site_id: str = "",
) -> dict[str, object]:
    summary = _dict_value(value)
    totals = _dict_value(summary.get("totals"))
    data: dict[str, object] = {
        "generated_at": str(summary.get("generated_at") or ""),
        "totals": {str(key): int(count or 0) for key, count in totals.items()},
        "groups": [
            _portal_audit_group_data(item) for item in _object_list(summary.get("groups"))
        ],
    }
    if site_id:
        data["site_id"] = site_id
    return data


def _portal_audit_event_data(value: object) -> dict[str, object]:
    event = _dict_value(value)
    return {
        "event_id": int(event.get("event_id") or 0),
        "event_kind": str(event.get("event_kind") or ""),
        "outcome": str(event.get("outcome") or ""),
        "trace_id": str(event.get("trace_id") or ""),
        "created_at": str(event.get("created_at") or ""),
    }


def _portal_audit_events_response_data(
    value: object,
    *,
    site_id: str = "",
) -> dict[str, object]:
    events = _dict_value(value)
    filters = _dict_value(events.get("filters"))
    data: dict[str, object] = {
        "total": int(events.get("total") or 0),
        "filters": {
            "event_kind": str(filters.get("event_kind") or ""),
            "outcome": str(filters.get("outcome") or ""),
        },
        "items": [
            _portal_audit_event_data(item) for item in _object_list(events.get("items"))
        ],
    }
    if site_id:
        data["site_id"] = site_id
    return data


def _build_portal_audit_context(request: Request, principal_id: str) -> ServiceAuditContext:
    audit_context = _build_audit_context(request)
    audit_context.actor_kind = "principal"
    audit_context.actor_ref = principal_id
    raw_idempotency_key = request.headers.get("Idempotency-Key", "")
    if raw_idempotency_key:
        audit_context.idempotency_key = build_portal_business_idempotency_key(
            principal_id=principal_id,
            idempotency_key=raw_idempotency_key,
        )
    return audit_context


def _authorize_portal_site_access(
    request: Request,
    *,
    site_id: str,
    principal_id: str,
    required_roles: set[str] | None = None,
    required_action: str | None = None,
) -> dict[str, object] | JSONResponse:
    try:
        access = _get_commercial_service(request).resolve_portal_site_access(
            site_id=site_id,
            principal_id=principal_id,
            required_roles=required_roles,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    normalized_action = str(required_action or "").strip()
    if normalized_action:
        allowed_actions = {
            str(action).strip()
            for action in _object_list(access.get("allowed_actions"))
            if str(action).strip()
        }
        if normalized_action not in allowed_actions:
            return portal_json_error(
                request,
                status_code=403,
                error_code="service.portal_action_forbidden",
                message=f"principal '{principal_id}' lacks required action '{normalized_action}'",
            )
    return access


def _portal_route_envelope(
    *,
    message: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    return build_envelope(
        status="ok",
        message=message,
        data=data,
        revision="m6",
    )

def _portal_session_cleared_response() -> JSONResponse:
    response = JSONResponse(
        status_code=200,
        content=_portal_route_envelope(
            message="portal session cleared",
            data={},
        ),
    )
    clear_portal_session_cookies(response)
    return response


def _portal_qq_config_error(request: Request) -> JSONResponse | None:
    config = _portal_qq_config(request)
    if not str(config.get("client_id") or "").strip():
        return portal_json_error(
            request,
            status_code=503,
            error_code="portal.qq_login_not_configured",
            message="QQ login is not configured",
        )
    if not str(config.get("client_secret") or "").strip():
        return portal_json_error(
            request,
            status_code=503,
            error_code="portal.qq_login_not_configured",
            message="QQ login is not configured",
        )
    if not str(config.get("redirect_uri") or "").strip():
        return portal_json_error(
            request,
            status_code=503,
            error_code="portal.qq_login_not_configured",
            message="QQ login redirect uri is not configured",
        )
    return None


def _portal_qq_config(request: Request) -> dict[str, Any]:
    settings = get_cloud_services(request).settings
    return resolve_portal_qq_runtime_config(settings.database_url, settings)


def _portal_qq_redirect_uri(request: Request) -> str:
    return str(_portal_qq_config(request).get("redirect_uri") or "").strip()


def _portal_qq_oauth_nonce(request: Request, payload_nonce: str = "") -> str:
    return str(payload_nonce or request.cookies.get(COOKIE_PORTAL_QQ_OAUTH_NONCE) or "").strip()


def _set_portal_qq_oauth_nonce_cookie(
    request: Request,
    response: JSONResponse,
    *,
    nonce: str,
    max_age: int,
) -> None:
    _clear_portal_qq_oauth_nonce_cookie(response)
    response.set_cookie(
        COOKIE_PORTAL_QQ_OAUTH_NONCE,
        nonce,
        httponly=True,
        secure=portal_cookie_secure(request),
        samesite="lax",
        path=COOKIE_PORTAL_QQ_OAUTH_NONCE_PATH,
        max_age=max(60, int(max_age or 0)),
    )


def _clear_portal_qq_oauth_nonce_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_PORTAL_QQ_OAUTH_NONCE, path=COOKIE_PORTAL_QQ_OAUTH_NONCE_PATH)


def _build_qq_authorization_url(request: Request, *, state: str) -> str:
    config = _portal_qq_config(request)
    query = urlencode(
        {
            "response_type": "code",
            "client_id": str(config.get("client_id") or "").strip(),
            "redirect_uri": str(config.get("redirect_uri") or "").strip(),
            "state": state,
            "scope": str(config.get("scope") or "get_user_info").strip(),
        }
    )
    return f"https://graph.qq.com/oauth2.0/authorize?{query}"


def _portal_prefers_html(request: Request) -> bool:
    accept = str(request.headers.get("accept") or "").lower()
    return "text/html" in accept and "application/json" not in accept


def _portal_oauth_return_response(
    request: Request,
    *,
    return_to: str,
    status: str,
) -> RedirectResponse | None:
    if not _portal_prefers_html(request):
        return None
    safe_return_to = return_to if return_to.startswith("/portal") else "/portal"
    separator = "&" if "?" in safe_return_to else "?"
    return RedirectResponse(f"{safe_return_to}{separator}qq={status}", status_code=303)


def _parse_qq_query_response(value: str) -> dict[str, str]:
    return {key: item for key, item in parse_qsl(str(value or ""), keep_blank_values=True)}


def _parse_qq_me_response(value: str) -> dict[str, object]:
    raw = str(value or "").strip()
    if raw.startswith("callback(") and raw.endswith(");"):
        raw = raw[len("callback(") : -2].strip()
    payload = json.loads(raw)
    return payload if isinstance(payload, dict) else {}


def _exchange_qq_code(request: Request, *, code: str) -> dict[str, str]:
    config = _portal_qq_config(request)
    with httpx.Client(timeout=float(config.get("timeout_seconds") or 10.0)) as client:
        response = client.get(
            "https://graph.qq.com/oauth2.0/token",
            params={
                "grant_type": "authorization_code",
                "client_id": str(config.get("client_id") or "").strip(),
                "client_secret": str(config.get("client_secret") or "").strip(),
                "code": code,
                "redirect_uri": str(config.get("redirect_uri") or "").strip(),
                "fmt": "xhtml",
            },
        )
        response.raise_for_status()
    payload = _parse_qq_query_response(response.text)
    if not str(payload.get("access_token") or "").strip():
        raise CommercialServiceError(
            502,
            "portal.qq_token_exchange_failed",
            "QQ token exchange failed",
        )
    return payload


def _fetch_qq_openid(request: Request, *, access_token: str) -> dict[str, str]:
    config = _portal_qq_config(request)
    with httpx.Client(timeout=float(config.get("timeout_seconds") or 10.0)) as client:
        response = client.get(
            "https://graph.qq.com/oauth2.0/me",
            params={
                "access_token": access_token,
                "unionid": "1",
                "fmt": "json",
            },
        )
        response.raise_for_status()
    payload = _parse_qq_me_response(response.text)
    openid = str(payload.get("openid") or "").strip()
    if not openid:
        raise CommercialServiceError(
            502,
            "portal.qq_openid_fetch_failed",
            "QQ openid fetch failed",
        )
    return {
        "openid": openid,
        "unionid": str(payload.get("unionid") or "").strip(),
    }


def _portal_write_guard(request: Request) -> JSONResponse | None:
    return None


def _portal_same_origin_guard(
    request: Request,
    *,
    always: bool = False,
) -> JSONResponse | None:
    settings = get_cloud_services(request).settings
    if (
        settings.production_like_environment()
        and str(request.headers.get("x-npcink-debug-portal-link") or "").strip() == "1"
    ):
        return portal_json_error(
            request,
            status_code=403,
            error_code="auth.origin_forbidden",
            message="cross-site browser writes are not allowed",
        )
    if not always:
        has_header_auth = any(
            [
                str(request.headers.get(AUTHORIZATION_HEADER) or "").strip(),
            ]
        )
        if has_header_auth:
            return None
    try:
        enforce_browser_same_origin(request)
    except PortalBearerTokenError as error:
        return portal_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    return None


def _csv_set(value: str) -> set[str]:
    return {item.strip() for item in str(value or "").split(",") if item.strip()}


def _allow_development_login_code(request: Request) -> bool:
    services = get_cloud_services(request)
    environment = str(services.settings.environment or "").strip().lower()
    return environment in {"development", "test"} and (
        str(request.headers.get("x-npcink-dev-login-code") or "").strip() == "1"
        or str(request.headers.get("x-npcink-debug-portal-link") or "").strip() == "1"
    )


def _get_portal_advisor_service(request: Request) -> InternalAIAdvisorService:
    services = get_cloud_services(request)
    return InternalAIAdvisorService(
        services.settings.database_url,
        providers=services.providers,
        allowed_summarizer_provider_ids=_csv_set(
            services.settings.internal_ops_summarizer_provider_allowlist
        ),
    )


def _resolve_portal_ai_provider_id(request: Request) -> str:
    services = get_cloud_services(request)
    allowed_provider_ids = [
        provider_id
        for provider_id in _csv_set(services.settings.internal_ops_summarizer_provider_allowlist)
        if provider_id in services.providers
    ]
    return sorted(allowed_provider_ids)[0] if allowed_provider_ids else ""


@router.get("/auth/qq/start")
async def start_portal_qq_login(
    request: Request,
    return_to: str = Query(default="/portal"),
    intent: str = Query(default="login"),
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    config_error = _portal_qq_config_error(request)
    if config_error is not None:
        return config_error
    nonce = secrets.token_urlsafe(32)
    issued = _get_commercial_service(request).issue_portal_oauth_state(
        provider="qq",
        return_to=return_to,
        client_scope_id=str(request.client.host if request.client else ""),
        ttl_seconds=int(get_cloud_services(request).settings.portal_oauth_state_ttl_seconds or 0),
        nonce=nonce,
        intent=intent,
    )
    authorization_url = _build_qq_authorization_url(
        request,
        state=str(issued.get("state") or ""),
    )
    expires_in_seconds_value: Any = issued.get("expires_in_seconds") or 0
    expires_in_seconds = int(expires_in_seconds_value)
    response = JSONResponse(
        status_code=200,
        content=_portal_route_envelope(
            message="portal QQ login started",
            data={
                "provider": "qq",
                "authorization_url": authorization_url,
                "state": str(issued.get("state") or ""),
                "expires_in_seconds": expires_in_seconds,
                "return_to": str(issued.get("return_to") or "/portal"),
                "intent": str(issued.get("intent") or "login"),
            },
        ),
    )
    _set_portal_qq_oauth_nonce_cookie(
        request,
        response,
        nonce=nonce,
        max_age=expires_in_seconds,
    )
    return response


async def finish_qq_login_callback(
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
) -> Any:
    if not code.strip() or not state.strip():
        return portal_json_error(
            request,
            status_code=400,
            error_code="portal.qq_callback_required",
            message="QQ authorization code and state are required",
        )
    config_error = _portal_qq_config_error(request)
    if config_error is not None:
        return config_error
    try:
        consumed_state = _get_commercial_service(request).consume_portal_oauth_state(
            provider="qq",
            state=state,
            nonce=_portal_qq_oauth_nonce(request),
        )
        token = _exchange_qq_code(request, code=code.strip())
        subject = _fetch_qq_openid(
            request,
            access_token=str(token.get("access_token") or ""),
        )
        return_to = str(consumed_state.get("return_to") or "/portal")
        if str(consumed_state.get("intent") or "") == "bind":
            auth = await resolve_portal_request_context(
                request,
                require_idempotency=False,
                allow_session_cookies=True,
            )
            if isinstance(auth, JSONResponse):
                return auth
            binding = _get_commercial_service(request).bind_portal_identity_provider(
                principal_id=auth.principal_id,
                provider="qq",
                external_subject=str(subject.get("openid") or ""),
                unionid=str(subject.get("unionid") or ""),
                metadata_json={"source": "portal_qq_callback_bind"},
            )
            redirect = _portal_oauth_return_response(
                request,
                return_to=return_to,
                status="bound",
            )
            if redirect is not None:
                _clear_portal_qq_oauth_nonce_cookie(redirect)
                return redirect
            response = JSONResponse(
                status_code=200,
                content=_portal_route_envelope(
                    message="portal QQ login bound",
                    data={
                        "status": "bound",
                        "provider": "qq",
                        "return_to": return_to,
                        "binding": _portal_identity_binding_response_data(binding),
                    },
                ),
            )
            _clear_portal_qq_oauth_nonce_cookie(response)
            return response
        login = _get_commercial_service(request).resolve_portal_identity_provider_login(
            provider="qq",
            external_subject=str(subject.get("openid") or ""),
            unionid=str(subject.get("unionid") or ""),
        )
        if str(login.get("status") or "") == "binding_required":
            redirect = _portal_oauth_return_response(
                request,
                return_to=return_to,
                status="binding_required",
            )
            if redirect is not None:
                _clear_portal_qq_oauth_nonce_cookie(redirect)
                return redirect
            response = JSONResponse(
                status_code=200,
                content=_portal_route_envelope(
                    message="portal QQ binding required",
                    data={
                        "status": "binding_required",
                        "provider": str(login.get("provider") or "qq"),
                        "return_to": return_to,
                    },
                ),
            )
            _clear_portal_qq_oauth_nonce_cookie(response)
            return response
        principal_id = str(login.get("principal_id") or "")
        data = serialize_portal_session(
            request,
            principal_id=principal_id,
            site_id="",
            strict_site=False,
            session_metadata=build_new_portal_session_metadata(request),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    except httpx.HTTPError as error:
        return portal_json_error(
            request,
            status_code=502,
            error_code="portal.qq_provider_unavailable",
            message=str(error),
        )

    response = JSONResponse(
        status_code=200,
        content=_portal_route_envelope(
            message="portal session created",
            data=data,
        ),
    )
    set_portal_session_cookies(
        request,
        response,
        principal_id=principal_id,
        site_id=str(data.get("site_id") or ""),
    )
    _clear_portal_qq_oauth_nonce_cookie(response)
    return response


@router.get("/auth/identity-providers")
async def list_portal_identity_providers(request: Request) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    try:
        result = _get_commercial_service(request).list_portal_identity_provider_bindings(
            principal_id=auth.principal_id,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    raw_items = result.get("items", [])
    items = (
        [item for item in raw_items if isinstance(item, dict)]
        if isinstance(raw_items, list)
        else []
    )
    qq_binding = next(
        (item for item in items if str(item.get("provider") or "") == "qq"),
        None,
    )
    qq_config = _portal_qq_config(request)
    qq_configured = all(
        str(qq_config.get(key) or "").strip()
        for key in ("client_id", "client_secret", "redirect_uri")
    )
    return _portal_route_envelope(
        message="portal identity providers listed",
        data={
            "providers": [
                {
                    "provider": "qq",
                    "display_name": "QQ",
                    "configured": qq_configured,
                    "bound": qq_binding is not None,
                    "binding": (
                        _portal_identity_binding_response_data(qq_binding)
                        if qq_binding is not None
                        else None
                    ),
                    "bind_start_path": (
                        "/portal/v1/auth/qq/start?intent=bind&return_to=/portal/account"
                    ),
                }
            ],
        },
    )


@router.post("/auth/qq/bind")
async def bind_portal_qq_login(
    request: Request,
    payload: PortalQQBindPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    config_error = _portal_qq_config_error(request)
    if config_error is not None:
        return config_error
    code = payload.code.strip()
    state = payload.state.strip()
    if not code or not state:
        return portal_json_error(
            request,
            status_code=400,
            error_code="portal.qq_bind_required",
            message="QQ authorization code and state are required",
        )
    try:
        _get_commercial_service(request).consume_portal_oauth_state(
            provider="qq",
            state=state,
            nonce=_portal_qq_oauth_nonce(request, payload.nonce),
        )
        token = _exchange_qq_code(request, code=code)
        subject = _fetch_qq_openid(
            request,
            access_token=str(token.get("access_token") or ""),
        )
        binding = _get_commercial_service(request).bind_portal_identity_provider(
            principal_id=auth.principal_id,
            provider="qq",
            external_subject=str(subject.get("openid") or ""),
            unionid=str(subject.get("unionid") or ""),
            metadata_json={"source": "portal_qq_bind"},
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    except httpx.HTTPError as error:
        return portal_json_error(
            request,
            status_code=502,
            error_code="portal.qq_provider_unavailable",
            message=str(error),
        )
    response = JSONResponse(
        status_code=200,
        content=_portal_route_envelope(
            message="portal QQ login bound",
            data={"binding": _portal_identity_binding_response_data(binding)},
        ),
    )
    _clear_portal_qq_oauth_nonce_cookie(response)
    return response


@router.post("/auth/qq/unbind")
async def unbind_portal_qq_login(
    request: Request,
    payload: PortalQQUnbindPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    try:
        result = _get_commercial_service(request).revoke_portal_identity_provider(
            principal_id=auth.principal_id,
            provider=payload.provider,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal QQ login unbound",
        data={
            "provider": str(result.get("provider") or ""),
            "revoked": int(str(result.get("revoked") or 0)),
        },
    )


def _portal_ai_disclosure(disclosure: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": str(disclosure.get("version") or ""),
        "content_origin": str(disclosure.get("content_origin") or ""),
        "generated_by_ai": bool(disclosure.get("generated_by_ai")),
        "ai_assisted": bool(disclosure.get("ai_assisted")),
        "visible_label_required": bool(disclosure.get("visible_label_required")),
        "visible_label": str(disclosure.get("visible_label") or ""),
        "brand_label": str(disclosure.get("brand_label") or "Npcink AI"),
        "visible_notice": str(disclosure.get("visible_notice") or ""),
        "review_status": str(disclosure.get("review_status") or ""),
        "reviewed_at": str(disclosure.get("reviewed_at") or ""),
        "source_generation_mode": str(disclosure.get("source_generation_mode") or ""),
    }


def _portal_ai_generation(generation: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": str(generation.get("mode") or ""),
        "error_code": str(generation.get("error_code") or ""),
        "cache_status": str(generation.get("cache_status") or ""),
        "cache_hit": bool(generation.get("cache_hit")),
        "cache_generated_at": str(generation.get("cache_generated_at") or ""),
        "cache_expires_at": str(generation.get("cache_expires_at") or ""),
    }


def _portal_ai_summary(summary: dict[str, Any]) -> dict[str, Any]:
    generation = summary.get("generation") if isinstance(summary.get("generation"), dict) else {}
    disclosure = (
        summary.get("ai_disclosure") if isinstance(summary.get("ai_disclosure"), dict) else {}
    )
    return {
        "summary_version": str(summary.get("summarizer_version") or "internal-ops-summarizer-v1"),
        "scope": str(summary.get("scope") or ""),
        "status": str(summary.get("status") or ""),
        "severity": str(summary.get("severity") or ""),
        "headline": str(summary.get("headline") or ""),
        "operator_summary": str(summary.get("operator_summary") or ""),
        "operator_next_step": str(summary.get("operator_next_step") or ""),
        "safety_note": str(summary.get("safety_note") or ""),
        "generated_at": str(
            summary.get("generated_at")
            or (disclosure or {}).get("generated_at")
            or (generation or {}).get("cache_generated_at")
            or ""
        ),
        "generation": _portal_ai_generation(generation or {}),
        "ai_disclosure": _portal_ai_disclosure(disclosure or {}),
        "agent_handoff": _portal_ai_agent_handoff(summary.get("agent_handoff")),
        **_portal_ai_agent_metadata_projection_fields(summary.get("agent_handoff")),
    }


def _portal_ai_history_item(item: dict[str, Any]) -> dict[str, Any]:
    generation = item.get("generation") if isinstance(item.get("generation"), dict) else {}
    disclosure = item.get("ai_disclosure") if isinstance(item.get("ai_disclosure"), dict) else {}
    return {
        "site_id": str(item.get("site_id") or ""),
        "scope": str(item.get("scope") or ""),
        "status": str(item.get("status") or ""),
        "severity": str(item.get("severity") or ""),
        "headline": str(item.get("headline") or ""),
        "operator_summary": str(item.get("operator_summary") or ""),
        "operator_next_step": str(item.get("operator_next_step") or ""),
        "generated_at": str(item.get("generated_at") or ""),
        "fresh_until": str(item.get("fresh_until") or ""),
        "is_stale": bool(item.get("is_stale")),
        "generation": _portal_ai_generation(generation or {}),
        "ai_disclosure": _portal_ai_disclosure(disclosure or {}),
        "agent_handoff": _portal_ai_agent_handoff(item.get("agent_handoff")),
        **_portal_ai_agent_metadata_projection_fields(item.get("agent_handoff")),
    }


def _portal_ai_agent_metadata_projection_fields(value: Any) -> dict[str, Any]:
    projection = _portal_ai_agent_metadata_projection(value)
    return {
        "agent_metadata_projection": projection,
    }


def _portal_ai_agent_metadata_projection(value: Any) -> dict[str, Any]:
    handoff = _portal_ai_agent_handoff(value)
    agent_id = handoff.get("agent_id", "")
    if not agent_id:
        return {}
    return _portal_ai_agent_handoff(
        get_agent_handoff_metadata(
            agent_id,
            agent_role=handoff.get("agent_role") or None,
        )
    )


def _portal_ai_agent_handoff(value: Any) -> dict[str, Any]:
    handoff = value if isinstance(value, dict) else {}
    return {
        "agent_id": str(handoff.get("agent_id") or ""),
        "agent_version": str(handoff.get("agent_version") or ""),
        "agent_role": str(handoff.get("agent_role") or ""),
        "handoff_type": str(handoff.get("handoff_type") or ""),
        "handoff_owner": str(handoff.get("handoff_owner") or ""),
        "requires_operator_review": bool(handoff.get("requires_operator_review")),
        "direct_wordpress_write": bool(handoff.get("direct_wordpress_write")),
        "execution_pattern": str(handoff.get("execution_pattern") or ""),
        "storage_mode": str(handoff.get("storage_mode") or ""),
        "allowed_actions": [
            str(item)
            for item in _object_list(handoff.get("allowed_actions"))[:6]
            if str(item).strip()
        ],
        "stop_conditions": [
            str(item)
            for item in _object_list(handoff.get("stop_conditions"))[:6]
            if str(item).strip()
        ],
        "forbidden_actions": [
            str(item)
            for item in _object_list(handoff.get("forbidden_actions"))[:8]
            if str(item).strip()
        ],
        "fail_closed_behavior": str(handoff.get("fail_closed_behavior") or ""),
    }


def _portal_ai_safety_contract() -> dict[str, bool]:
    return {
        "manual_trigger_required": True,
        "prompt_saved": False,
        "raw_payload_saved": False,
        "wordpress_write_allowed": False,
        "provider_visible": False,
        "model_visible": False,
        "token_usage_visible": False,
        "cost_visible": False,
        "cache_key_visible": False,
        "customer_article_generation_allowed": False,
    }


def _resolve_selected_portal_account_access(
    request: Request,
    *,
    principal_id: str,
    site_id: str,
    required_action: str | None,
) -> dict[str, object] | JSONResponse:
    normalized_site_id = str(site_id or "").strip()
    if not normalized_site_id:
        return portal_json_error(
            request,
            status_code=409,
            error_code="portal.site_selection_required",
            message="portal site selection is required",
        )
    access = _authorize_portal_site_access(
        request,
        site_id=normalized_site_id,
        principal_id=principal_id,
        required_action=required_action,
    )
    if isinstance(access, JSONResponse):
        return access
    site = _dict_value(access.get("site"))
    site_status = str(site.get("status") or "").strip()
    if site_status == "archived":
        return portal_json_error(
            request,
            status_code=403,
            error_code="service.portal_site_removed",
            message="removed portal sites cannot establish account context",
        )
    if site_status != "active":
        return portal_json_error(
            request,
            status_code=403,
            error_code="service.portal_site_inactive",
            message="inactive portal sites cannot establish account context",
        )
    if not str(access.get("account_id") or "").strip():
        return portal_json_error(
            request,
            status_code=403,
            error_code="service.portal_account_required",
            message="portal account access is required",
        )
    return access


def _resolve_portal_addon_account_access(
    request: Request,
    *,
    principal_id: str,
    account_id: str,
) -> dict[str, object] | JSONResponse:
    try:
        accounts = _get_commercial_service(request).list_portal_accounts(
            principal_id=principal_id,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    normalized_account_id = str(account_id or "").strip()
    for raw_item in _object_list(accounts.get("items")):
        item = _dict_value(raw_item)
        allowed_actions = {
            str(action).strip()
            for action in _object_list(item.get("allowed_actions"))
            if str(action).strip()
        }
        if (
            str(item.get("account_id") or "").strip() == normalized_account_id
            and str(item.get("status") or "").strip() == "active"
            and str(item.get("membership_status") or "").strip() == "active"
            and USER_ALLOWED_ACTION_PROVISION_SITES in allowed_actions
        ):
            return item
    return _service_error_response(
        CommercialPermissionError(
            "service.principal_access_required",
            "portal account access is required",
        ),
        request=request,
    )


def _portal_account_site_ids(
    request: Request,
    *,
    principal_id: str,
    account_id: str,
) -> list[str] | JSONResponse:
    try:
        result = _get_commercial_service(request).list_portal_sites(principal_id=principal_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    sites = [
        _dict_value(item.get("site"))
        for item in _object_list(result.get("items"))
        if isinstance(item, dict)
    ]
    return [
        str(site.get("site_id") or "").strip()
        for site in sites
        if str(site.get("site_id") or "").strip()
        and str(site.get("account_id") or "").strip() == account_id
        and str(site.get("status") or "").strip().lower() != "archived"
    ]


def _validate_portal_account_site_filter(
    request: Request,
    *,
    principal_id: str,
    account_id: str,
    site_id: str,
    required_action: str,
) -> str | JSONResponse:
    normalized_site_id = str(site_id or "").strip()
    if not normalized_site_id:
        return ""
    access = _authorize_portal_site_access(
        request,
        site_id=normalized_site_id,
        principal_id=principal_id,
        required_action=required_action,
    )
    if isinstance(access, JSONResponse):
        return access
    if str(access.get("account_id") or "").strip() != account_id:
        return portal_json_error(
            request,
            status_code=403,
            error_code="service.portal_site_account_mismatch",
            message="portal site is outside the selected account context",
        )
    return normalized_site_id


def _resolve_portal_support_request_for_account(
    request: Request,
    *,
    principal_id: str,
    account_id: str,
    request_id: str,
) -> dict[str, object] | JSONResponse:
    try:
        result = _get_commercial_service(request).get_portal_support_request(
            principal_id=principal_id,
            account_id=account_id,
            request_id=request_id,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return result


def _resolve_portal_site_summary(
    request: Request,
    *,
    site_id: str,
    principal_id: str,
) -> dict[str, object] | JSONResponse:
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=principal_id,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        service = _get_commercial_service(request)
        policy = service.inspect_commercial_policy(site_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    subscription = _dict_value(policy.get("subscription"))
    subscription_metadata = _dict_value(subscription.get("metadata"))
    monitoring = SiteMonitoringOverviewService(service.database_url).get_summary(
        site_id=site_id,
        commercial_policy=policy,
        window_hours=24,
    )
    monitoring_health = _dict_value(monitoring.get("health"))
    monitoring_quota = _dict_value(monitoring.get("quota"))
    monitoring_actions = _object_list(monitoring.get("action_required"))
    monitoring_status = str(monitoring_health.get("status") or "inactive")
    needs_attention = (
        monitoring_status != "ok"
        or bool(monitoring_actions)
        or str(monitoring_quota.get("top_pressure") or "none") != "none"
    )
    return {
        "site_id": site_id,
        "site": policy.get("site"),
        "covered_by_subscription_id": str(subscription.get("subscription_id") or ""),
        "subscription_status": str(subscription.get("status") or ""),
        "package_alias": str(subscription_metadata.get("package_alias") or ""),
        "coverage": {
            "subscription": policy.get("subscription"),
            "plan_version": policy.get("plan_version"),
            "entitlement_snapshot": policy.get("entitlement_snapshot"),
        },
        "customer_status": {
            "status": monitoring_status,
            "needs_attention": needs_attention,
            "issue_count": len(monitoring_actions),
            "generated_at": monitoring.get("generated_at"),
        },
        "generated_at": policy.get("generated_at"),
    }


@router.post("/auth/code/request")
async def request_portal_login_code(
    request: Request,
    payload: PortalLoginCodeRequestPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    email = payload.email.strip()
    locale = resolve_portal_email_locale(request, payload.locale)
    if not email:
        return portal_json_error(
            request,
            status_code=400,
            error_code="portal.login_invalid",
            message="email is required",
        )
    try:
        enforce_portal_login_code_request_rate_limit(request, email=email)
    except PortalBearerTokenError as error:
        return portal_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    services = get_cloud_services(request)
    ttl_seconds = resolve_portal_login_code_ttl_seconds(services.settings)
    email_sender = services.portal_email_sender or build_portal_email_sender(
        services.settings,
        database_url=services.settings.database_url,
    )
    allow_development_code = _allow_development_login_code(request)
    if email_sender is None and not allow_development_code:
        return portal_json_error(
            request,
            status_code=503,
            error_code="portal.email_not_configured",
            message="Portal email delivery is not configured",
        )
    try:
        issued = _get_commercial_service(request).issue_portal_login_code(
            email=email,
            ttl_seconds=ttl_seconds,
        )
    except CommercialServiceError as error:
        if error.error_code in {
            "service.portal_email_not_found",
            "service.principal_email_not_found",
        }:
            return _portal_route_envelope(
                message="portal login code request accepted",
                data={
                    "email": email.strip().lower(),
                    "delivery": "email",
                    "expires_in_seconds": ttl_seconds,
                    "code": "",
                },
            )
        return _service_error_response(error, request=request)
    if email_sender is not None:
        try:
            email_sender.send_login_code(
                recipient_email=str(issued.get("email") or ""),
                principal_id=str(issued.get("principal_id") or ""),
                code=str(issued.get("code") or ""),
                expires_in_seconds=ttl_seconds,
                project_name=services.settings.project_name,
                locale=locale,
            )
        except PortalEmailDeliveryError as error:
            return portal_json_error(
                request,
                status_code=502,
                error_code="portal.email_delivery_failed",
                message=str(error),
            )
    return _portal_route_envelope(
        message="portal login code issued",
        data={
            "email": str(issued.get("email") or ""),
            "delivery": ("development_code" if allow_development_code else "email"),
            "expires_in_seconds": ttl_seconds,
            "code": (str(issued.get("code") or "") if allow_development_code else ""),
        },
    )


@router.post("/auth/code/verify")
async def verify_portal_login_code(
    request: Request,
    payload: PortalLoginCodeVerifyPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    email = payload.email.strip()
    code = payload.code.strip()
    if not email or not code:
        return portal_json_error(
            request,
            status_code=400,
            error_code="auth.portal_login_code_required",
            message="portal login code and email are required",
        )
    try:
        verified = _get_commercial_service(request).verify_portal_login_code(
            email=email,
            code=code,
            max_attempts=max(
                1,
                int(get_cloud_services(request).settings.portal_login_code_max_attempts or 0),
            ),
        )
        principal_id = str(verified.get("principal_id") or "")
        session_ttl_seconds = resolve_portal_login_session_ttl_seconds(
            request,
            remember_me=bool(payload.remember_me),
        )
        data = serialize_portal_session(
            request,
            principal_id=principal_id,
            site_id="",
            strict_site=False,
            session_metadata=build_new_portal_session_metadata(
                request,
                ttl_seconds=session_ttl_seconds,
            ),
        )
    except CommercialServiceError as error:
        if error.error_code == "service.portal_login_code_invalid":
            return portal_json_error(
                request,
                status_code=401,
                error_code="auth.portal_login_code_invalid",
                message="portal login code is invalid or expired",
            )
        return _service_error_response(error, request=request)

    response = JSONResponse(
        status_code=200,
        content=_portal_route_envelope(
            message="portal session created",
            data=data,
        ),
    )
    set_portal_session_cookies(
        request,
        response,
        principal_id=principal_id,
        site_id=str(data.get("site_id") or ""),
        ttl_seconds=session_ttl_seconds,
    )
    return response


@router.post("/account/email-change/request")
async def request_portal_email_change_code(
    request: Request,
    payload: PortalEmailChangeRequestPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    replay = portal_idempotency_replay_response(request)
    if replay is not None:
        return replay
    new_email = payload.new_email.strip()
    locale = resolve_portal_email_locale(request, payload.locale)
    if not new_email:
        return portal_json_error(
            request,
            status_code=400,
            error_code="portal.email_change_invalid",
            message="new email is required",
        )
    services = get_cloud_services(request)
    ttl_seconds = resolve_portal_login_code_ttl_seconds(services.settings)
    email_sender = services.portal_email_sender or build_portal_email_sender(
        services.settings,
        database_url=services.settings.database_url,
    )
    allow_development_code = _allow_development_login_code(request)
    if email_sender is None and not allow_development_code:
        return portal_json_error(
            request,
            status_code=503,
            error_code="portal.email_not_configured",
            message="Portal email delivery is not configured",
        )
    try:
        issued = _get_commercial_service(request).issue_portal_email_change_code(
            principal_id=auth.principal_id,
            new_email=new_email,
            ttl_seconds=ttl_seconds,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    if email_sender is not None:
        try:
            email_sender.send_email_change_code(
                recipient_email=str(issued.get("new_email") or ""),
                old_email=str(issued.get("old_email") or ""),
                principal_id=str(issued.get("principal_id") or ""),
                code=str(issued.get("code") or ""),
                expires_in_seconds=ttl_seconds,
                project_name=services.settings.project_name,
                locale=locale,
            )
        except PortalEmailDeliveryError as error:
            return portal_json_error(
                request,
                status_code=502,
                error_code="portal.email_delivery_failed",
                message=str(error),
            )
    return _portal_route_envelope(
        message="portal email change code issued",
        data={
            "old_email": str(issued.get("old_email") or ""),
            "new_email": str(issued.get("new_email") or ""),
            "delivery": ("development_code" if allow_development_code else "email"),
            "expires_in_seconds": ttl_seconds,
            "code": (str(issued.get("code") or "") if allow_development_code else ""),
        },
    )


@router.post("/account/email-change/verify")
async def verify_portal_email_change_code(
    request: Request,
    payload: PortalEmailChangeVerifyPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    replay = portal_idempotency_replay_response(request)
    if replay is not None:
        return replay
    new_email = payload.new_email.strip()
    code = payload.code.strip()
    if not new_email or not code:
        return portal_json_error(
            request,
            status_code=400,
            error_code="auth.portal_email_change_code_required",
            message="portal email change code and new email are required",
        )
    services = get_cloud_services(request)
    try:
        changed = _get_commercial_service(request).verify_portal_email_change_code(
            principal_id=auth.principal_id,
            new_email=new_email,
            code=code,
            max_attempts=max(
                1,
                int(services.settings.portal_login_code_max_attempts or 0),
            ),
            audit_context=_build_portal_audit_context(request, auth.principal_id),
        )
        data = serialize_portal_session(
            request,
            principal_id=auth.principal_id,
            site_id=auth.site_id,
            strict_site=False,
        )
    except CommercialServiceError as error:
        if error.error_code == "service.portal_email_change_code_invalid":
            return portal_json_error(
                request,
                status_code=401,
                error_code="auth.portal_email_change_code_invalid",
                message="portal email change code is invalid or expired",
            )
        return _service_error_response(error, request=request)

    email_sender = services.portal_email_sender or build_portal_email_sender(
        services.settings,
        database_url=services.settings.database_url,
    )
    if email_sender is not None:
        try:
            email_sender.send_email_changed_notice(
                recipient_email=str(changed.get("old_email") or ""),
                new_email=str(changed.get("new_email") or ""),
                principal_id=auth.principal_id,
                project_name=services.settings.project_name,
                locale=resolve_portal_email_locale(request, ""),
            )
        except PortalEmailDeliveryError:
            pass
    return _portal_route_envelope(
        message="portal email changed",
        data={
            **data,
            "old_email": str(changed.get("old_email") or ""),
            "new_email": str(changed.get("new_email") or ""),
        },
    )


@router.post("/register/code/request")
async def request_portal_registration_code(
    request: Request,
    payload: PortalRegistrationCodeRequestPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    email = payload.email.strip()
    site_url = payload.site_url.strip()
    locale = resolve_portal_email_locale(request, payload.locale)
    if not email:
        return portal_json_error(
            request,
            status_code=400,
            error_code="portal.registration_required",
            message="email is required",
        )
    try:
        enforce_portal_login_code_request_rate_limit(request, email=email)
    except PortalBearerTokenError as error:
        return portal_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    services = get_cloud_services(request)
    ttl_seconds = resolve_portal_login_code_ttl_seconds(services.settings)
    allow_development_code = _allow_development_login_code(request)
    email_sender = services.portal_email_sender or build_portal_email_sender(
        services.settings,
        database_url=services.settings.database_url,
    )
    if email_sender is None and not allow_development_code:
        return portal_json_error(
            request,
            status_code=503,
            error_code="portal.email_not_configured",
            message="Portal email delivery is not configured",
        )
    try:
        issued = _get_commercial_service(request).issue_portal_registration_code(
            email=email,
            site_url=site_url,
            site_name=payload.site_name,
            use_case=payload.use_case,
            ttl_seconds=ttl_seconds,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    if email_sender is not None:
        try:
            email_sender.send_registration_code(
                recipient_email=str(issued.get("email") or ""),
                principal_id=str(issued.get("principal_id") or ""),
                code=str(issued.get("code") or ""),
                expires_in_seconds=ttl_seconds,
                project_name=services.settings.project_name,
                site_name=str(issued.get("site_name") or ""),
                site_url=str(issued.get("site_url") or ""),
                locale=locale,
            )
        except PortalEmailDeliveryError as error:
            return portal_json_error(
                request,
                status_code=502,
                error_code="portal.email_delivery_failed",
                message=str(error),
            )
    return _portal_route_envelope(
        message="portal registration code issued",
        data={
            "email": str(issued.get("email") or ""),
            "delivery": ("development_code" if allow_development_code else "email"),
            "expires_in_seconds": ttl_seconds,
            "code": (str(issued.get("code") or "") if allow_development_code else ""),
            "site": {
                "site_id": str(issued.get("site_id") or ""),
                "site_name": str(issued.get("site_name") or ""),
                "site_url": str(issued.get("site_url") or ""),
                "platform_kind": PLATFORM_KIND_WORDPRESS,
            },
        },
    )


@router.post("/register/verify")
async def verify_portal_registration_code(
    request: Request,
    payload: PortalRegistrationVerifyPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    email = payload.email.strip()
    code = payload.code.strip()
    if not email or not code:
        return portal_json_error(
            request,
            status_code=400,
            error_code="auth.portal_registration_code_required",
            message="portal registration code and email are required",
        )
    try:
        registration = _get_commercial_service(request).verify_portal_registration_code(
            email=email,
            code=code,
            max_attempts=max(
                1,
                int(get_cloud_services(request).settings.portal_login_code_max_attempts or 0),
            ),
            audit_context=_build_portal_audit_context(request, "portal_registration"),
        )
        principal_id = str(registration.get("principal_id") or "")
        site_id = str(registration.get("site_id") or "")
        session_data = serialize_portal_session(
            request,
            principal_id=principal_id,
            site_id=site_id,
            strict_site=False,
            session_metadata=build_new_portal_session_metadata(request),
        )
        data = session_data
    except CommercialServiceError as error:
        if error.error_code == "service.portal_registration_code_invalid":
            return portal_json_error(
                request,
                status_code=401,
                error_code="auth.portal_registration_code_invalid",
                message="portal registration code is invalid or expired",
            )
        return _service_error_response(error, request=request)
    response = JSONResponse(
        status_code=200,
        content=_portal_route_envelope(
            message="portal registration completed",
            data=data,
        ),
    )
    set_portal_session_cookies(
        request,
        response,
        principal_id=principal_id,
        site_id=site_id,
    )
    return response


@router.get("/session")
async def get_portal_session(request: Request) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    selected_site_id = str(auth.site_id or "").strip()
    try:
        data = serialize_portal_session(
            request,
            principal_id=auth.principal_id,
            site_id=selected_site_id,
            strict_site=False,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal session loaded",
        data=data,
    )


@router.post("/session/site")
async def select_portal_session_site(
    request: Request,
    payload: PortalSessionSitePayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    site_id = payload.site_id.strip()
    if not site_id:
        return portal_json_error(
            request,
            status_code=400,
            error_code="portal.site_invalid",
            message="site id is required",
        )
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    try:
        data = serialize_portal_session(
            request,
            principal_id=auth.principal_id,
            site_id=site_id,
            strict_site=True,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    response = JSONResponse(
        status_code=200,
        content=_portal_route_envelope(
            message="portal site selected",
            data=data,
        ),
    )
    set_portal_session_cookies(
        request,
        response,
        principal_id=auth.principal_id,
        site_id=site_id,
    )
    return response


@router.post("/logout")
async def logout_portal_session(request: Request) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    return _portal_session_cleared_response()


@router.post("/session/revoke")
async def revoke_portal_session(request: Request) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    return _portal_session_cleared_response()


@router.get("/account/plan-offers")
async def list_portal_account_plan_offers(request: Request) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    account_id = str(account_access.get("account_id") or "")
    try:
        offers = _get_commercial_service(request).list_account_plan_offers(account_id=account_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal package offers listed",
        data=_portal_plan_offer_list_data(offers),
    )


@router.post("/account/plan-trials")
async def start_portal_account_plan_trial(
    request: Request,
    payload: PortalPlanTrialPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    write_guard = _portal_write_guard(request)
    if write_guard is not None:
        return write_guard
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    replay = portal_idempotency_replay_response(request)
    if replay is not None:
        return replay
    account_id = str(account_access.get("account_id") or "")
    try:
        result = _get_commercial_service(request).start_account_plan_trial(
            account_id=account_id,
            tier_id=payload.tier_id,
            principal_id=auth.principal_id,
            audit_context=_build_portal_audit_context(request, auth.principal_id),
        )
        session_data = serialize_portal_session(
            request,
            principal_id=auth.principal_id,
            site_id=auth.site_id,
            strict_site=False,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal paid package trial started",
        data=_portal_plan_trial_response_data(result, session=session_data),
    )


@router.post("/account/subscription-orders")
async def create_portal_account_subscription_order(
    request: Request,
    payload: PortalSubscriptionOrderPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    write_guard = _portal_write_guard(request)
    if write_guard is not None:
        return write_guard
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    replay = portal_idempotency_replay_response(request)
    if replay is not None:
        return replay
    account_id = str(account_access.get("account_id") or "")
    try:
        result = _get_commercial_service(request).create_account_subscription_payment_order(
            account_id=account_id,
            offer_id=payload.offer_id,
            provider=payload.provider,
            audit_context=_build_portal_audit_context(request, auth.principal_id),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal subscription order created",
        data=_portal_subscription_order_payload_data(result),
    )


@router.delete("/account/subscription-orders/{subscription_order_id}")
async def cancel_portal_account_subscription_order(
    request: Request,
    subscription_order_id: str,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    write_guard = _portal_write_guard(request)
    if write_guard is not None:
        return write_guard
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    replay = portal_idempotency_replay_response(request)
    if replay is not None:
        return replay
    account_id = str(account_access.get("account_id") or "")
    try:
        result = _get_commercial_service(request).cancel_account_subscription_payment_order(
            account_id=account_id,
            subscription_order_id=subscription_order_id,
            audit_context=_build_portal_audit_context(request, auth.principal_id),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal subscription order canceled",
        data=_portal_subscription_order_payload_data(result),
    )


@router.post("/account/free-downgrade")
async def schedule_portal_account_free_downgrade(request: Request) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    write_guard = _portal_write_guard(request)
    if write_guard is not None:
        return write_guard
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    replay = portal_idempotency_replay_response(request)
    if replay is not None:
        return replay
    account_id = str(account_access.get("account_id") or "")
    try:
        result = _get_commercial_service(request).schedule_account_free_downgrade(
            account_id=account_id,
            audit_context=_build_portal_audit_context(request, auth.principal_id),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal Free downgrade scheduled",
        data=_portal_free_downgrade_data(result),
    )


@router.get("/account/entitlements")
async def get_portal_account_entitlements(request: Request) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    account_id = str(account_access.get("account_id") or "")
    try:
        quota_summary = _get_commercial_service(request).get_portal_account_quota_summary(
            account_id
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal account entitlements loaded",
        data={
            "period_start_at": quota_summary.get("period_start_at") or "",
            "period_end_at": quota_summary.get("period_end_at") or "",
            "usage_totals": {},
            "subscription_grace": {},
            "budget_state": {},
            "quota_summary": _portal_public_quota_summary_data(quota_summary),
            "generated_at": quota_summary.get("generated_at") or "",
        },
    )


@router.get("/account/usage-summary")
async def get_portal_account_usage_summary(request: Request) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_USAGE,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    account_id = str(account_access.get("account_id") or "")
    site_ids = _portal_account_site_ids(
        request,
        principal_id=auth.principal_id,
        account_id=account_id,
    )
    if isinstance(site_ids, JSONResponse):
        return site_ids
    result = UsageService(_get_commercial_service(request).database_url).get_usage_summary(
        site_ids=site_ids
    )
    result["site_ids"] = site_ids
    return _portal_route_envelope(
        message="portal account usage summary loaded",
        data=result,
    )


@router.get("/account/credit-ledger")
async def get_portal_account_credit_ledger(
    request: Request,
    limit: int = Query(default=25, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    account_id = str(account_access.get("account_id") or "")
    try:
        ledger = _get_commercial_service(request).get_portal_account_credit_ledger(
            account_id,
            limit=limit,
            offset=offset,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal account credit ledger loaded",
        data=_portal_credit_ledger_data(ledger),
    )


@router.get("/account/credit-trend")
async def get_portal_account_credit_trend(
    request: Request,
    window: Literal["1h", "24h", "7d", "30d"] = Query(default="24h"),  # noqa: B008
    site_id: str = Query(default="", max_length=191),  # noqa: B008
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    account_id = str(account_access.get("account_id") or "")
    resolved_site_id = _validate_portal_account_site_filter(
        request,
        principal_id=auth.principal_id,
        account_id=account_id,
        site_id=site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(resolved_site_id, JSONResponse):
        return resolved_site_id
    try:
        trend = _get_commercial_service(request).get_portal_account_credit_trend(
            account_id,
            window=window,
            site_id=resolved_site_id,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal account credit trend loaded",
        data=_portal_credit_trend_data(trend),
    )


@router.get("/account/credit-events")
async def get_portal_account_credit_events(
    request: Request,
    window: Literal["24h", "7d", "30d", "period"] = Query(default="period"),  # noqa: B008
    site_id: str = Query(default="", max_length=191),  # noqa: B008
    feature: str = Query(default="", max_length=64),  # noqa: B008
    start_at: datetime | None = Query(default=None),  # noqa: B008
    end_at: datetime | None = Query(default=None),  # noqa: B008
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    account_id = str(account_access.get("account_id") or "")
    resolved_site_id = _validate_portal_account_site_filter(
        request,
        principal_id=auth.principal_id,
        account_id=account_id,
        site_id=site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(resolved_site_id, JSONResponse):
        return resolved_site_id
    try:
        events = _get_commercial_service(request).get_portal_account_credit_events(
            account_id,
            window=window,
            site_id=resolved_site_id,
            feature=feature,
            range_start_at=start_at,
            range_end_at=end_at,
            limit=limit,
            offset=offset,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal account credit events loaded",
        data=_portal_credit_events_data(events),
    )


@router.get("/account/credit-event-buckets")
async def get_portal_account_credit_event_buckets(
    request: Request,
    bucket: Literal["10m", "30m", "60m"] = Query(default="30m"),  # noqa: B008
    window: Literal["24h", "7d", "30d", "period"] = Query(default="7d"),  # noqa: B008
    site_id: str = Query(default="", max_length=191),  # noqa: B008
    feature: str = Query(default="", max_length=64),  # noqa: B008
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    account_id = str(account_access.get("account_id") or "")
    resolved_site_id = _validate_portal_account_site_filter(
        request,
        principal_id=auth.principal_id,
        account_id=account_id,
        site_id=site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(resolved_site_id, JSONResponse):
        return resolved_site_id
    try:
        buckets = _get_commercial_service(request).get_portal_account_credit_event_buckets(
            account_id,
            bucket=bucket,
            window=window,
            site_id=resolved_site_id,
            feature=feature,
            limit=limit,
            offset=offset,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal account credit event buckets loaded",
        data=_portal_credit_event_buckets_data(buckets),
    )


@router.get("/account/credit-packs")
async def list_portal_account_credit_packs(request: Request) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    result = _get_commercial_service(request).list_credit_packs()
    return _portal_route_envelope(
        message="portal account credit packs loaded",
        data=_portal_credit_pack_catalog_data(result),
    )


@router.post("/account/credit-pack-orders")
async def create_portal_account_credit_pack_order(
    request: Request,
    payload: PortalCreditPackOrderPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    write_guard = _portal_write_guard(request)
    if write_guard is not None:
        return write_guard
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    replay = portal_idempotency_replay_response(request)
    if replay is not None:
        return replay
    account_id = str(account_access.get("account_id") or "")
    try:
        order = _get_commercial_service(request).create_credit_pack_payment_order(
            account_id=account_id,
            pack_id=payload.pack_id,
            provider=payload.provider,
            audit_context=_build_portal_audit_context(request, auth.principal_id),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal account credit pack payment order created",
        data={"order": _portal_payment_order_data(order)},
    )


@router.get("/account/payment-orders")
async def list_portal_account_payment_orders(
    request: Request,
    status_group: Literal["all", "pending", "paid", "closed"] = Query(  # noqa: B008
        default="all"
    ),
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    account_id = str(account_access.get("account_id") or "")
    try:
        result = _get_commercial_service(request).list_account_payment_orders(
            account_id,
            status_group=status_group,
            limit=limit,
            offset=offset,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal account payment orders loaded",
        data=_portal_payment_order_list_data(result),
    )


@router.get("/account/payment-orders/{order_id}")
async def get_portal_account_payment_order(request: Request, order_id: str) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    account_id = str(account_access.get("account_id") or "")
    try:
        order = _get_commercial_service(request).get_account_payment_order(
            account_id=account_id,
            order_id=order_id,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal account payment order loaded",
        data={"order": _portal_payment_order_data(order)},
    )


@router.post("/account/payment-orders/{order_id}/cancellation")
async def cancel_portal_account_payment_order(
    request: Request,
    order_id: str,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    write_guard = _portal_write_guard(request)
    if write_guard is not None:
        return write_guard
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    replay = portal_idempotency_replay_response(request)
    if replay is not None:
        return replay
    account_id = str(account_access.get("account_id") or "")
    try:
        result = _get_commercial_service(request).cancel_account_payment_order(
            account_id=account_id,
            order_id=order_id,
            audit_context=_build_portal_audit_context(request, auth.principal_id),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal account payment order canceled",
        data=_portal_payment_order_payload_data(result),
    )


@router.get("/support-requests")
async def list_portal_support_requests(
    request: Request,
    status: str = Query(default="", max_length=32),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=None,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    account_id = str(account_access.get("account_id") or "")
    try:
        result = _get_commercial_service(request).list_portal_support_requests(
            principal_id=auth.principal_id,
            account_id=account_id,
            status=status,
            limit=limit,
            offset=offset,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    result.pop("account_id", None)
    result.pop("principal_id", None)
    return _portal_route_envelope(
        message="portal support requests loaded",
        data=result,
    )


@router.post("/support-requests")
async def create_portal_support_request(
    request: Request,
    payload: PortalSupportRequestPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    write_guard = _portal_write_guard(request)
    if write_guard is not None:
        return write_guard
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=None,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    account_id = str(account_access.get("account_id") or "")
    target_site_id = str(payload.site_id or auth.site_id or "").strip()
    target_access = _authorize_portal_site_access(
        request,
        site_id=target_site_id,
        principal_id=auth.principal_id,
    )
    if isinstance(target_access, JSONResponse):
        return target_access
    if str(target_access.get("account_id") or "").strip() != account_id:
        return portal_json_error(
            request,
            status_code=403,
            error_code="service.portal_site_account_mismatch",
            message="support request site is outside the selected account context",
        )
    replay = portal_idempotency_replay_response(request)
    if replay is not None:
        return replay
    try:
        result = _get_commercial_service(request).create_portal_support_request(
            principal_id=auth.principal_id,
            account_id=account_id,
            site_id=target_site_id,
            topic=payload.topic,
            title=payload.title,
            description=payload.description,
            source_path=payload.source_path,
            context_json=payload.context,
            audit_context=_build_portal_audit_context(request, auth.principal_id),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal support request created",
        data={"request": result},
    )


@router.get("/support-requests/{request_id}")
async def get_portal_support_request(request: Request, request_id: str) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=None,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    result = _resolve_portal_support_request_for_account(
        request,
        principal_id=auth.principal_id,
        account_id=str(account_access.get("account_id") or ""),
        request_id=request_id,
    )
    if isinstance(result, JSONResponse):
        return result
    return _portal_route_envelope(
        message="portal support request loaded",
        data=result,
    )


@router.post("/support-requests/{request_id}/messages")
async def create_portal_support_request_message(
    request: Request,
    request_id: str,
    payload: PortalSupportRequestMessagePayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    write_guard = _portal_write_guard(request)
    if write_guard is not None:
        return write_guard
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=None,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    request_access = _resolve_portal_support_request_for_account(
        request,
        principal_id=auth.principal_id,
        account_id=str(account_access.get("account_id") or ""),
        request_id=request_id,
    )
    if isinstance(request_access, JSONResponse):
        return request_access
    replay = portal_idempotency_replay_response(request)
    if replay is not None:
        return replay
    try:
        result = _get_commercial_service(request).create_portal_support_request_message(
            principal_id=auth.principal_id,
            request_id=request_id,
            body=payload.body,
            audit_context=_build_portal_audit_context(request, auth.principal_id),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal support request message created",
        data=result,
    )


@router.post("/support-requests/{request_id}/attachments")
async def create_portal_support_request_attachment(
    request: Request,
    request_id: str,
    payload: PortalSupportRequestAttachmentPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    write_guard = _portal_write_guard(request)
    if write_guard is not None:
        return write_guard
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=None,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    request_access = _resolve_portal_support_request_for_account(
        request,
        principal_id=auth.principal_id,
        account_id=str(account_access.get("account_id") or ""),
        request_id=request_id,
    )
    if isinstance(request_access, JSONResponse):
        return request_access
    replay = portal_idempotency_replay_response(request)
    if replay is not None:
        return replay
    try:
        result = _get_commercial_service(request).create_portal_support_request_attachment(
            principal_id=auth.principal_id,
            request_id=request_id,
            filename=payload.filename,
            content_type=payload.content_type,
            content_base64=payload.content_base64,
            message_id=payload.message_id,
            audit_context=_build_portal_audit_context(request, auth.principal_id),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal support request attachment created",
        data=result,
    )


@router.get("/support-requests/{request_id}/attachments/{attachment_id}")
async def get_portal_support_request_attachment(
    request: Request,
    request_id: str,
    attachment_id: str,
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=None,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    request_access = _resolve_portal_support_request_for_account(
        request,
        principal_id=auth.principal_id,
        account_id=str(account_access.get("account_id") or ""),
        request_id=request_id,
    )
    if isinstance(request_access, JSONResponse):
        return request_access
    try:
        result = _get_commercial_service(request).get_portal_support_request_attachment(
            principal_id=auth.principal_id,
            request_id=request_id,
            attachment_id=attachment_id,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal support request attachment loaded",
        data=result,
    )


@router.post("/support-requests/{request_id}/feedback")
async def submit_portal_support_request_feedback(
    request: Request,
    request_id: str,
    payload: PortalSupportRequestFeedbackPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    write_guard = _portal_write_guard(request)
    if write_guard is not None:
        return write_guard
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=None,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    request_access = _resolve_portal_support_request_for_account(
        request,
        principal_id=auth.principal_id,
        account_id=str(account_access.get("account_id") or ""),
        request_id=request_id,
    )
    if isinstance(request_access, JSONResponse):
        return request_access
    replay = portal_idempotency_replay_response(request)
    if replay is not None:
        return replay
    try:
        result = _get_commercial_service(request).submit_portal_support_request_feedback(
            principal_id=auth.principal_id,
            request_id=request_id,
            resolved=payload.resolved,
            rating=payload.rating,
            comment=payload.comment,
            audit_context=_build_portal_audit_context(request, auth.principal_id),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal support request feedback submitted",
        data=result,
    )


@router.get("/addon-connection-accounts")
async def list_portal_addon_connection_accounts(request: Request) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    try:
        result = _get_commercial_service(request).list_portal_accounts(
            principal_id=auth.principal_id,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    items = []
    for raw_item in _object_list(result.get("items")):
        item = _dict_value(raw_item)
        allowed_actions = {
            str(action).strip()
            for action in _object_list(item.get("allowed_actions"))
            if str(action).strip()
        }
        if (
            str(item.get("status") or "").strip() != "active"
            or str(item.get("membership_status") or "").strip() != "active"
            or USER_ALLOWED_ACTION_PROVISION_SITES not in allowed_actions
        ):
            continue
        items.append(
            {
                "account_id": str(item.get("account_id") or ""),
                "name": str(item.get("name") or ""),
                "site_count": int(item.get("site_count") or 0),
            }
        )
    return _portal_route_envelope(
        message="portal addon connection accounts loaded",
        data={"items": items},
    )


@router.post("/addon-connections")
async def create_portal_addon_connection(
    request: Request,
    payload: PortalAddonConnectionPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request)
    if same_origin is not None:
        return same_origin
    write_guard = _portal_write_guard(request)
    if write_guard is not None:
        return write_guard
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_commercial_service(request)
    account_access = _resolve_portal_addon_account_access(
        request,
        principal_id=auth.principal_id,
        account_id=payload.account_id,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    replay = portal_idempotency_replay_response(request)
    if replay is not None:
        return replay
    audit_context = _build_portal_audit_context(request, auth.principal_id)
    try:
        result = service.create_wordpress_addon_connection(
            account_id=payload.account_id,
            principal_id=auth.principal_id,
            site_url=payload.site_url,
            site_name=payload.site_name,
            return_url=payload.return_url,
            addon_state=payload.state,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)

    return _portal_route_envelope(
        message="wordpress addon connection issued",
        data=result,
    )


@router.post("/addon-connections/exchange")
async def exchange_portal_addon_connection(
    request: Request,
    payload: PortalAddonConnectionExchangePayload,
) -> Any:
    try:
        result = _get_commercial_service(request).consume_wordpress_addon_connection(
            code=payload.code,
            addon_state=payload.state,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)

    return _portal_route_envelope(
        message="wordpress addon connection exchanged",
        data=result,
    )


@router.post("/sites/{site_id}/remove")
async def remove_portal_site(request: Request, site_id: str) -> Any:
    same_origin = _portal_same_origin_guard(request)
    if same_origin is not None:
        return same_origin
    write_guard = _portal_write_guard(request)
    if write_guard is not None:
        return write_guard
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=auth.principal_id,
        required_action=USER_ALLOWED_ACTION_REMOVE_SITES,
    )
    if isinstance(access, JSONResponse):
        return access
    replay = portal_idempotency_replay_response(request)
    if replay is not None:
        return replay
    try:
        result = _get_commercial_service(request).remove_portal_site(
            site_id,
            audit_context=_build_portal_audit_context(request, auth.principal_id),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal site removed",
        data=_portal_remove_site_data(result),
    )


@router.get("/sites/{site_id}/summary")
async def get_portal_site_summary(request: Request, site_id: str) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    result = _resolve_portal_site_summary(
        request,
        site_id=site_id,
        principal_id=auth.principal_id,
    )
    if isinstance(result, JSONResponse):
        return result
    return _portal_route_envelope(
        message="portal site summary loaded",
        data=_portal_site_summary_response_data(result),
    )


@router.get("/sites/{site_id}/usage-summary")
async def get_portal_site_usage_summary(request: Request, site_id: str) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=auth.principal_id,
        required_action=USER_ALLOWED_ACTION_VIEW_USAGE,
    )
    if isinstance(access, JSONResponse):
        return access
    result = UsageService(_get_commercial_service(request).database_url).get_usage_summary(
        site_id=site_id
    )
    result["site_id"] = site_id
    return _portal_route_envelope(
        message="portal usage summary loaded",
        data=_portal_site_response_data(result),
    )


@router.get("/sites/{site_id}/monitoring-overview")
async def get_portal_site_monitoring_overview(
    request: Request,
    site_id: str,
    window_hours: int = Query(default=24, ge=1, le=168),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=auth.principal_id,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        service = _get_commercial_service(request)
        policy = service.inspect_commercial_policy(site_id)
        result = SiteMonitoringOverviewService(service.database_url).get_summary(
            site_id=site_id,
            commercial_policy=policy,
            window_hours=window_hours,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal monitoring overview loaded",
        data=_portal_site_response_data(result),
    )


@router.get("/sites/{site_id}/diagnostic-advisor")
async def get_portal_site_diagnostic_advisor(
    request: Request,
    site_id: str,
    window_hours: int = Query(default=24, ge=1, le=168),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=auth.principal_id,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        result = _get_portal_advisor_service(request).get_site_diagnostic_advisor(
            site_id=site_id,
            window_hours=window_hours,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    result["site_id"] = site_id
    return _portal_route_envelope(
        message="portal diagnostic advisor loaded",
        data=_portal_site_response_data(result),
    )


@router.get("/sites/{site_id}/diagnostics")
async def get_portal_site_diagnostics(
    request: Request,
    site_id: str,
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=auth.principal_id,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        result = _get_commercial_service(request).get_portal_site_diagnostics(site_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal site diagnostics loaded",
        data=_portal_site_response_data(result),
    )


@router.get("/sites/{site_id}/plugin-observability")
async def get_portal_site_plugin_observability(
    request: Request,
    site_id: str,
    window_hours: int = Query(default=24, ge=1, le=168),
    plugin_slug: str = Query(default="", max_length=64),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=auth.principal_id,
    )
    if isinstance(access, JSONResponse):
        return access
    result = PluginObservabilityService(_get_commercial_service(request).database_url).get_summary(
        site_id=site_id,
        window_hours=window_hours,
        plugin_slug=plugin_slug.strip(),
    )
    result["site_id"] = site_id
    return _portal_route_envelope(
        message="portal plugin observability loaded",
        data=_portal_site_response_data(result),
    )


@router.get("/sites/{site_id}/media-observability")
async def get_portal_site_media_observability(
    request: Request,
    site_id: str,
    window_hours: int = Query(default=24, ge=1, le=168),
    target_format: str = Query(default="", max_length=16),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=auth.principal_id,
    )
    if isinstance(access, JSONResponse):
        return access
    services = get_cloud_services(request)
    result = MediaDerivativeObservabilityService(
        services.settings.database_url,
        site_queued_limit=services.settings.media_derivative_site_queued_limit,
        site_running_limit=services.settings.media_derivative_site_running_limit,
        default_chunk_size=services.settings.media_derivative_batch_default_chunk_size,
    ).get_summary(
        site_id=site_id,
        window_hours=window_hours,
        target_format=target_format.strip(),
    )
    result.pop("sites", None)
    result["workflow_metadata"] = get_workflow_metadata(MEDIA_DERIVATIVE_WORKFLOW_ID)
    result["site_id"] = site_id
    return _portal_route_envelope(
        message="portal media observability loaded",
        data=_portal_site_response_data(result),
    )


@router.get("/sites/{site_id}/vector-observability")
async def get_portal_site_vector_observability(
    request: Request,
    site_id: str,
    window_hours: int = Query(default=24, ge=1, le=168),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=auth.principal_id,
    )
    if isinstance(access, JSONResponse):
        return access
    result = SiteKnowledgeObservabilityService(
        _get_commercial_service(request).database_url
    ).get_summary(
        site_id=site_id,
        window_hours=window_hours,
    )
    result.pop("sites", None)
    result["site_id"] = site_id
    return _portal_route_envelope(
        message="portal vector observability loaded",
        data=_portal_site_response_data(result),
    )


@router.get("/sites/{site_id}/ai-insights/history")
async def list_portal_site_ai_insight_history(
    request: Request,
    site_id: str,
    limit: int = Query(default=10, ge=1, le=50),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=auth.principal_id,
    )
    if isinstance(access, JSONResponse):
        return access
    history = _get_portal_advisor_service(request).list_ops_summary_history(
        site_id=site_id,
        scope="operations_analysis",
        limit=limit,
    )
    return _portal_route_envelope(
        message="portal ai insight history loaded",
        data=_portal_site_response_data(
            {
                "portal_ai_insight_version": "portal-ai-insight-v1",
                "site_id": site_id,
                "items": [
                    _portal_ai_history_item(item)
                    for item in _object_list(history.get("items"))
                    if isinstance(item, dict)
                ],
                "safety": _portal_ai_safety_contract(),
            }
        ),
    )


@router.post("/sites/{site_id}/ai-insights/analyze")
async def analyze_portal_site_ai_insight(
    request: Request,
    site_id: str,
    payload: PortalAIInsightAnalyzePayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request)
    if same_origin is not None:
        return same_origin
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=auth.principal_id,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        summary = _get_portal_advisor_service(request).get_ops_summary(
            scope="operations",
            site_id=site_id,
            draft_kind="operator_analysis",
            recent_minutes=120,
            usage_window_days=7,
            audit_window_minutes=1440,
            range_filter="24h",
            limit=25,
            provider_id=_resolve_portal_ai_provider_id(request),
            model_id=FREE_GPT55_MODEL_ID,
            force_refresh=payload.force_refresh,
            cache_ttl_seconds=1800,
        )
    except ValueError as error:
        return portal_json_error(
            request,
            status_code=400,
            error_code="portal.ai_insight_invalid",
            message=str(error),
        )
    return _portal_route_envelope(
        message="portal ai insight analyzed",
        data=_portal_site_response_data(
            {
                "portal_ai_insight_version": "portal-ai-insight-v1",
                "site_id": site_id,
                "analysis": _portal_ai_summary(summary),
                "safety": _portal_ai_safety_contract(),
            }
        ),
    )


@router.get("/sites/{site_id}/entitlements")
async def get_portal_site_entitlements(request: Request, site_id: str) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=auth.principal_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        commercial_service = _get_commercial_service(request)
        policy = commercial_service.inspect_commercial_policy(site_id)
        quota_summary = commercial_service.get_portal_account_quota_summary(
            str(access.get("account_id") or "")
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal entitlements loaded",
        data=_portal_site_entitlements_response_data(
            {
                "site_id": site_id,
                "site": policy.get("site"),
                "subscription": policy.get("subscription"),
                "plan_version": policy.get("plan_version"),
                "entitlement_snapshot": policy.get("entitlement_snapshot"),
                "policy": policy.get("policy"),
                "period_start_at": policy.get("period_start_at"),
                "period_end_at": policy.get("period_end_at"),
                "usage_totals": policy.get("usage_totals"),
                "subscription_grace": policy.get("subscription_grace"),
                "budget_state": policy.get("budget_state"),
                "quota_summary": quota_summary,
                "generated_at": policy.get("generated_at"),
            }
        ),
    )


@router.get("/sites/{site_id}/credit-ledger")
async def get_portal_site_credit_ledger(
    request: Request,
    site_id: str,
    limit: int = Query(default=25, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=auth.principal_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        ledger = _get_commercial_service(request).get_portal_account_credit_ledger(
            str(access.get("account_id") or ""),
            limit=limit,
            offset=offset,
            site_id=site_id,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal credit ledger loaded",
        data=_portal_credit_ledger_data(ledger, site_id=site_id),
    )


@router.get("/sites/{site_id}/credit-packs")
async def list_portal_site_credit_packs(request: Request, site_id: str) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=auth.principal_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(access, JSONResponse):
        return access
    result = _get_commercial_service(request).list_credit_packs()
    return _portal_route_envelope(
        message="portal credit packs loaded",
        data=_portal_credit_pack_catalog_data(result, site_id=site_id),
    )


@router.get("/sites/{site_id}/payment-orders")
async def list_portal_site_payment_orders(
    request: Request,
    site_id: str,
    status_group: Literal["all", "pending", "paid", "closed"] = Query(  # noqa: B008
        default="all"
    ),
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=auth.principal_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        result = _get_commercial_service(request).list_account_payment_orders(
            str(access.get("account_id") or ""),
            site_id=site_id,
            status_group=status_group,
            limit=limit,
            offset=offset,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal payment orders loaded",
        data=_portal_payment_order_list_data(result, site_id=site_id),
    )


@router.post("/sites/{site_id}/credit-pack-orders")
async def create_portal_site_credit_pack_order(
    request: Request,
    site_id: str,
    payload: PortalCreditPackOrderPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request)
    if same_origin is not None:
        return same_origin
    write_guard = _portal_write_guard(request)
    if write_guard is not None:
        return write_guard
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=auth.principal_id,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(access, JSONResponse):
        return access
    replay = portal_idempotency_replay_response(request)
    if replay is not None:
        return replay
    try:
        order = _get_commercial_service(request).create_credit_pack_payment_order(
            account_id=str(access.get("account_id") or ""),
            site_id=site_id,
            pack_id=payload.pack_id,
            provider=payload.provider,
            audit_context=_build_portal_audit_context(request, auth.principal_id),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal credit pack payment order created",
        data={"site_id": site_id, "order": _portal_payment_order_data(order)},
    )


@router.get("/account/audit-summary")
async def get_portal_account_audit_summary(request: Request) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_AUDIT,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    account_id = str(account_access.get("account_id") or "")
    site_ids = _portal_account_site_ids(
        request,
        principal_id=auth.principal_id,
        account_id=account_id,
    )
    if isinstance(site_ids, JSONResponse):
        return site_ids
    try:
        summary = _get_commercial_service(request).summarize_service_audit_events(
            account_id=account_id,
            site_ids=site_ids,
            limit=200,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal account audit summary loaded",
        data=_portal_audit_summary_response_data(summary),
    )


@router.get("/account/audit-events")
async def list_portal_account_audit_events(
    request: Request,
    event_kind: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_access = _resolve_selected_portal_account_access(
        request,
        principal_id=auth.principal_id,
        site_id=auth.site_id,
        required_action=USER_ALLOWED_ACTION_VIEW_AUDIT,
    )
    if isinstance(account_access, JSONResponse):
        return account_access
    account_id = str(account_access.get("account_id") or "")
    site_ids = _portal_account_site_ids(
        request,
        principal_id=auth.principal_id,
        account_id=account_id,
    )
    if isinstance(site_ids, JSONResponse):
        return site_ids
    try:
        events = _get_commercial_service(request).list_service_audit_events(
            account_id=account_id,
            site_ids=site_ids,
            event_kind=event_kind,
            outcome=outcome,
            limit=limit,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal account audit events loaded",
        data=_portal_audit_events_response_data(events),
    )


@router.get("/sites/{site_id}/audit-summary")
async def get_portal_site_audit_summary(request: Request, site_id: str) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=auth.principal_id,
        required_action=USER_ALLOWED_ACTION_VIEW_AUDIT,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        summary = _get_commercial_service(request).summarize_service_audit_events(
            site_id=site_id,
            limit=200,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal audit summary loaded",
        data=_portal_audit_summary_response_data(summary, site_id=site_id),
    )


@router.get("/sites/{site_id}/audit-events")
async def list_portal_site_audit_events(
    request: Request,
    site_id: str,
    event_kind: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=auth.principal_id,
        required_action=USER_ALLOWED_ACTION_VIEW_AUDIT,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        events = _get_commercial_service(request).list_service_audit_events(
            site_id=site_id,
            event_kind=event_kind,
            outcome=outcome,
            limit=limit,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal audit events loaded",
        data=_portal_audit_events_response_data(events, site_id=site_id),
    )


@router.get("/sites/{site_id}/billing-snapshots")
async def list_portal_site_billing_snapshots(request: Request, site_id: str) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=auth.principal_id,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        snapshots = _get_commercial_service(request).list_billing_snapshots(site_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal billing snapshots loaded",
        data=_portal_billing_snapshot_list_data(snapshots, site_id=site_id),
    )


@router.get("/sites/{site_id}/billing-snapshots/reconciliation")
async def get_portal_site_billing_reconciliation(request: Request, site_id: str) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=auth.principal_id,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        reconciliation = _get_commercial_service(request).reconcile_billing_snapshot(site_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal billing reconciliation loaded",
        data=_portal_billing_reconciliation_data(reconciliation, site_id=site_id),
    )
