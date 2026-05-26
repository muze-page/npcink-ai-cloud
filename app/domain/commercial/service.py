from __future__ import annotations

import re
import secrets
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlsplit
from uuid import uuid4

from sqlalchemy.orm import Session

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.callback_security import (
    RuntimeCallbackTargetValidationError,
    validate_runtime_callback_target,
)
from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.models import (
    ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN,
    ACCOUNT_MEMBERSHIP_STATUS_ACTIVE,
    ACCOUNT_MEMBERSHIP_STATUS_DISABLED,
    ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE,
    ACCOUNT_STATUS_ACTIVE,
    ENTITLEMENT_SNAPSHOT_STATUS_ACTIVE,
    PLAN_STATUS_ACTIVE,
    PLAN_VERSION_STATUS_PUBLISHED,
    PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
    PLATFORM_ADMIN_STATUS_ACTIVE,
    PLATFORM_IMPERSONATION_STATUS_ACTIVE,
    PLATFORM_IMPERSONATION_STATUS_ENDED,
    PORTAL_ACTION_REQUEST_STATUS_ACKNOWLEDGED,
    PORTAL_ACTION_REQUEST_STATUS_CANCELED,
    PORTAL_ACTION_REQUEST_STATUS_OPEN,
    PORTAL_ACTION_REQUEST_STATUS_RESOLVED,
    PORTAL_LOGIN_CODE_STATUS_CONSUMED,
    PORTAL_LOGIN_CODE_STATUS_EXPIRED,
    PORTAL_LOGIN_CODE_STATUS_LOCKED,
    PORTAL_LOGIN_CODE_STATUS_PENDING,
    SITE_API_KEY_STATUS_ACTIVE,
    SITE_API_KEY_STATUS_EXPIRED,
    SITE_API_KEY_STATUS_REVOKED,
    SITE_STATUS_ACTIVE,
    SITE_STATUS_ARCHIVED,
    SITE_STATUS_PROVISIONING,
    SITE_STATUS_SUSPENDED,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_CANCELED,
    SUBSCRIPTION_STATUS_PAST_DUE,
    SUBSCRIPTION_STATUS_SUSPENDED,
    SUBSCRIPTION_STATUS_TRIALING,
    CommercialDecisionEvent,
    BillingSnapshot,
    PlatformImpersonationSession,
    PortalActionRequest,
    ProviderCallRecord,
    RunRecord,
    ServiceAuditEvent,
    Site,
    SiteApiKey,
    AccountEntitlementSnapshot,
    AccountSubscription,
)
from app.core.security import build_secret_hash
from app.core.secrets import (
    encrypt_runtime_terminal_callback_secret,
    encrypt_site_api_signing_secret,
)
from app.domain.commercial.customer_api_keys import expand_api_key_scopes
from app.domain.commercial.errors import (
    CommercialNotFoundError,
    CommercialPermissionError,
    CommercialValidationError,
)
from app.domain.runtime.errors import (
    RuntimeConcurrencyExceededError,
    RuntimeEntitlementDeniedError,
    RuntimeQuotaExceededError,
    RuntimeSiteInactiveError,
    RuntimeSiteNotProvisionedError,
    RuntimeSubscriptionInactiveError,
)

ALLOWED_ABILITY_FAMILIES = {
    "text",
    "vision",
    "workflow",
    "automation",
    "mcp",
    "openclaw",
}
DEFAULT_RUNTIME_ENTITLEMENTS = {
    "ability_families": ["*"],
    "channels": ["*"],
    "execution_kinds": ["*"],
    "execution_tiers": ["cloud"],
    "data_classifications": ["*"],
}
DEFAULT_RUNTIME_BUDGETS: dict[str, object] = {
    "max_runs_per_period": 500,
    "max_tokens_per_period": 2_000_000,
    "max_cost_per_period": 50.0,
}
DEFAULT_RUNTIME_CONCURRENCY: dict[str, object] = {
    "max_active_runs": 10,
}
DEFAULT_RUNTIME_COMMERCIAL_POLICY = {
    "subscription": {
        "grace_period_days": 0,
        "downgrade_policy": {},
    },
    "budgets": {
        "runs": {
            "grace_requests": 0,
            "downgrade_policy": {},
        },
        "tokens": {
            "grace_requests": 0,
            "downgrade_policy": {},
        },
        "cost": {
            "grace_requests": 0,
            "downgrade_policy": {},
        },
    },
    "reconciliation": {
        "tolerance": {
            "runs": 0.0,
            "provider_calls": 0.0,
            "tokens_total": 0.0,
            "cost": 0.0,
        }
    },
}
SHADOW_PRICING_TARIFF_VERSION = "shadow-pricing-v1"
SHADOW_PRICING_TARIFF_REGISTRY: dict[str, dict[str, dict[str, float | str]]] = {
    "ability": {
        "magick-ai/workflows/generate-post-draft": {
            "tariff_class": "medium",
            "base_run_price": 0.08,
            "per_1k_tokens_price": 0.018,
        },
        "workflow/media_nightly_image_optimize": {
            "tariff_class": "high",
            "base_run_price": 0.16,
            "per_1k_tokens_price": 0.024,
        },
    },
    "ability_family": {
        "text": {
            "tariff_class": "medium",
            "base_run_price": 0.05,
            "per_1k_tokens_price": 0.014,
        },
        "vision": {
            "tariff_class": "high",
            "base_run_price": 0.18,
            "per_1k_tokens_price": 0.028,
        },
        "workflow": {
            "tariff_class": "medium",
            "base_run_price": 0.07,
            "per_1k_tokens_price": 0.016,
        },
        "automation": {
            "tariff_class": "low",
            "base_run_price": 0.03,
            "per_1k_tokens_price": 0.01,
        },
        "mcp": {
            "tariff_class": "medium",
            "base_run_price": 0.04,
            "per_1k_tokens_price": 0.012,
        },
        "openclaw": {
            "tariff_class": "high",
            "base_run_price": 0.12,
            "per_1k_tokens_price": 0.02,
        },
    },
}
PLAN_TIER_REGISTRY: dict[str, dict[str, object]] = {
    "starter": {
        "tier_id": "starter",
        "label": "Starter",
        "package_alias": "Free",
        "usage_band": "Low-volume single-site hosted usage.",
        "positioning": "Baseline package for conservative hosted runs, lighter workflow usage, and operator-managed growth.",
        "monthly_included_points": 500,
        "budgets_template": {
            "max_runs_per_period": 500,
            "max_tokens_per_period": 200_000,
            "max_cost_per_period": 5.0,
        },
        "concurrency_template": {"max_active_runs": 1},
        "site_limit": 1,
        "max_batch_items": 0,
        "automation_enabled": True,
        "api_enabled": True,
        "openclaw_enabled": True,
        "package_operator_note": "Core capabilities stay available across packages. Free remains the most conservative on points, concurrency, batch headroom, and over-limit handling.",
        "policy_baseline": {
            "grace_period_days": 0,
            "downgrade_policy": "Fail closed when cost or token pressure exceeds the period budget.",
        },
        "feature_groups": [
            "Hosted runtime baseline",
            "Portal usage visibility",
            "Operator-managed subscription changes",
        ],
    },
    "pro": {
        "tier_id": "pro",
        "label": "Pro",
        "package_alias": "Basic",
        "usage_band": "Mid-band workflow and automation usage.",
        "positioning": "General-purpose package for steadier workflow volume, fuller automation usage, and predictable hosted operations.",
        "monthly_included_points": 10_000,
        "budgets_template": {
            "max_runs_per_period": 10_000,
            "max_tokens_per_period": 2_000_000,
            "max_cost_per_period": 99.0,
        },
        "concurrency_template": {"max_active_runs": 2},
        "site_limit": 5,
        "max_batch_items": 10,
        "automation_enabled": True,
        "api_enabled": True,
        "openclaw_enabled": True,
        "package_operator_note": "Core capabilities stay available across packages. Basic expands points, concurrency, batch headroom, and grace before operator intervention.",
        "policy_baseline": {
            "grace_period_days": 3,
            "downgrade_policy": "Use short grace before downgrading queue-heavy or high-cost usage.",
        },
        "feature_groups": [
            "Hosted runtime + workflow coverage",
            "Automation-heavy usage",
            "Operator-led budget follow-up",
        ],
    },
    "agency": {
        "tier_id": "agency",
        "label": "Agency",
        "package_alias": "Bulk",
        "usage_band": "High-volume multi-site and sustained workflow usage.",
        "positioning": "High-headroom package for multi-site operators, continuous automation, and materially higher hosted workload.",
        "monthly_included_points": 50_000,
        "budgets_template": {
            "max_runs_per_period": 50_000,
            "max_tokens_per_period": 10_000_000,
            "max_cost_per_period": 499.0,
        },
        "concurrency_template": {"max_active_runs": 6},
        "site_limit": 25,
        "max_batch_items": 100,
        "automation_enabled": True,
        "api_enabled": True,
        "openclaw_enabled": True,
        "package_operator_note": "Core capabilities stay available across packages. Bulk provides the highest points budget, concurrency, batch headroom, and policy headroom.",
        "policy_baseline": {
            "grace_period_days": 7,
            "downgrade_policy": "Keep operator visibility high while allowing short-lived overage handling before intervention.",
        },
        "feature_groups": [
            "Higher hosted concurrency",
            "Multi-site commercial headroom",
            "Sustained workflow and automation operations",
        ],
    },
}
DEFAULT_PLAN_TIER_ID = "pro"
DEFAULT_FREE_PLAN_ID = "plan_free"
DEFAULT_FREE_PLAN_VERSION_ID = "plan_free_v1"
DEFAULT_FREE_PLAN_KIND = "default_free"
DEFAULT_FREE_PLAN_SOURCE = "production_default_free_shell_v1"
DEFAULT_FREE_SUBSCRIPTION_SOURCE = "production_default_free_bind_v1"
CANONICAL_TIER_PLAN_IDS = {
    tier_id: (tier_id, f"{tier_id}_v1") for tier_id in PLAN_TIER_REGISTRY
}
TOPUP_PACK_CATALOG_REQUEST_KIND = "topup_pack_catalog"
TOPUP_PACK_OVERLAY_DECISION_PREFIX = "topup_pack_catalog.overlay."
ALLOWED_TOPUP_PACK_TIERS = {"starter", "pro", "agency"}
TOPUP_PACK_EDITABLE_FIELDS = {
    "label",
    "points_label",
    "runs_increment",
    "tokens_increment",
    "cost_increment",
    "operator_note",
    "recommended_for_tiers",
    "display_order",
    "active",
}
OPERATOR_MANAGED_POINTS_PACK_REGISTRY: dict[str, dict[str, object]] = {
    "pack_small": {
        "pack_id": "pack_small",
        "label": "Small pack",
        "points_label": "10,000 points equivalent",
        "points_equivalent": 10_000,
        "display_order": 1,
        "recommended_for_tiers": ["starter", "pro"],
        "active": True,
        "runs_increment": 10_000,
        "tokens_increment": 2_000_000,
        "cost_increment": 99.0,
        "operator_note": "Use when the current billing period needs basic-tier-sized budget headroom without rebinding the subscription.",
    },
    "pack_medium": {
        "pack_id": "pack_medium",
        "label": "Medium pack",
        "points_label": "35,000 points equivalent",
        "points_equivalent": 35_000,
        "display_order": 2,
        "recommended_for_tiers": ["pro", "agency"],
        "active": True,
        "runs_increment": 35_000,
        "tokens_increment": 7_000_000,
        "cost_increment": 349.0,
        "operator_note": "Use when sustained workflow pressure needs materially higher current-period headroom before a package review.",
    },
    "pack_large": {
        "pack_id": "pack_large",
        "label": "Large pack",
        "points_label": "150,000 points equivalent",
        "points_equivalent": 150_000,
        "display_order": 3,
        "recommended_for_tiers": ["agency"],
        "active": True,
        "runs_increment": 150_000,
        "tokens_increment": 30_000_000,
        "cost_increment": 1_499.0,
        "operator_note": "Use when an operator needs a high-headroom current-period top-up without introducing a wallet or self-serve flow.",
    },
}


@dataclass(slots=True)
class ServiceAuditContext:
    trace_id: str
    idempotency_key: str
    method: str
    path: str
    actor_kind: str = "internal_token"
    actor_ref: str = "internal"


PORTAL_SITE_KEY_WRITE_ROLES = {
    ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN,
}
PORTAL_SITE_PROVISION_ROLES = {
    ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN,
}
PORTAL_SITE_READ_ROLES = {
    ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN,
}
PORTAL_MEMBERSHIP_ALLOWED_ROLES = PORTAL_SITE_READ_ROLES
ACCOUNT_MEMBERSHIP_ALLOWED_ROLES = PORTAL_MEMBERSHIP_ALLOWED_ROLES
PLATFORM_ADMIN_ALLOWED_ROLES = {
    PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
}
PLATFORM_ADMIN_ACCOUNT_WRITE_ROLES = {
    PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
}
PLATFORM_ADMIN_CATALOG_WRITE_ROLES = {
    PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
}
PLATFORM_IMPERSONATION_ALLOWED_ROLES = {
    PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
}
PLATFORM_IMPERSONATION_MAX_TTL_SECONDS = 30 * 60
PORTAL_MEMBER_ALLOWED_LOGIN_STATUSES = {
    ACCOUNT_MEMBERSHIP_STATUS_ACTIVE,
    ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE,
}
COMMERCIAL_COVERED_SUBSCRIPTION_STATUSES = {
    SUBSCRIPTION_STATUS_TRIALING,
    SUBSCRIPTION_STATUS_ACTIVE,
}
PORTAL_INVITE_DELIVERY_QUEUED = "queued"
PORTAL_INVITE_DELIVERY_SENT = "sent"
PORTAL_INVITE_DELIVERY_FAILED = "failed"
PORTAL_INVITE_DELIVERY_SKIPPED = "skipped"
PORTAL_MEMBER_PREFERENCE_LOCALES = {"en", "zh-CN", "zh-TW"}
PORTAL_MEMBER_PREFERENCE_CURRENCIES = {"USD", "CNY", "HKD"}
PORTAL_MEMBER_IDENTITY_PROVIDER = "email_magic_link"
IDENTITY_TYPE_PLATFORM_ADMIN = "platform_admin"
IDENTITY_TYPE_USER_ADMIN = "user_admin"
USER_ALLOWED_ACTION_VIEW_SITES = "view_sites"
USER_ALLOWED_ACTION_VIEW_USAGE = "view_usage"
USER_ALLOWED_ACTION_VIEW_BILLING = "view_billing"
USER_ALLOWED_ACTION_VIEW_AUDIT = "view_audit"
USER_ALLOWED_ACTION_PROVISION_SITES = "provision_sites"
USER_ALLOWED_ACTION_MANAGE_SITE_KEYS = "manage_site_keys"
USER_ALLOWED_ACTION_ARCHIVE_SITES = "archive_sites"


def _normalize_portal_member_email(member_ref: str, metadata_json: dict[str, object] | None) -> str:
    metadata = metadata_json or {}
    email = str(metadata.get("email") or "").strip().lower()
    if email:
        return email
    normalized_member_ref = str(member_ref or "").strip()
    if normalized_member_ref.startswith("user:"):
        return normalized_member_ref[len("user:") :].strip().lower()
    return ""


def _normalize_portal_member_locale(value: object) -> str:
    locale = str(value or "").strip()
    if locale in PORTAL_MEMBER_PREFERENCE_LOCALES:
        return locale
    return ""


def _normalize_portal_member_currency(value: object) -> str:
    currency = str(value or "").strip().upper()
    if currency in PORTAL_MEMBER_PREFERENCE_CURRENCIES:
        return currency
    return "CNY"


def _subscription_counts_as_covered(subscription: object | None) -> bool:
    if subscription is None:
        return False
    status = str(getattr(subscription, "status", "") or "").strip()
    plan_id = str(getattr(subscription, "plan_id", "") or "").strip()
    plan_version_id = str(getattr(subscription, "plan_version_id", "") or "").strip()
    return (
        status in COMMERCIAL_COVERED_SUBSCRIPTION_STATUSES
        and bool(plan_id)
        and bool(plan_version_id)
    )


def _aggregate_membership_status(statuses: set[str]) -> str:
    if ACCOUNT_MEMBERSHIP_STATUS_DISABLED in statuses:
        return ACCOUNT_MEMBERSHIP_STATUS_DISABLED
    if ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE in statuses:
        return ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE
    if ACCOUNT_MEMBERSHIP_STATUS_ACTIVE in statuses:
        return ACCOUNT_MEMBERSHIP_STATUS_ACTIVE
    return next(iter(statuses), "")


def _normalize_portal_membership_metadata(
    *,
    member_ref: str,
    status: str,
    metadata_json: dict[str, object] | None,
) -> dict[str, object]:
    normalized_status = str(status or "").strip() or ACCOUNT_MEMBERSHIP_STATUS_ACTIVE
    metadata: dict[str, object] = dict(metadata_json or {})
    email = _normalize_portal_member_email(member_ref, metadata)
    if email:
        metadata["email"] = email

    invite_state = str(metadata.get("invite_state") or "").strip().lower()
    last_delivery_status = str(metadata.get("last_delivery_status") or "").strip().lower()

    if normalized_status == ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE:
        metadata["invite_state"] = invite_state or "pending"
    elif normalized_status == ACCOUNT_MEMBERSHIP_STATUS_ACTIVE:
        if invite_state in {"pending", "sent"} and metadata.get("last_login_at"):
            metadata["invite_state"] = "accepted"
        elif invite_state:
            metadata["invite_state"] = invite_state
        elif metadata.get("last_login_at"):
            metadata["invite_state"] = "accepted"
        else:
            metadata["invite_state"] = "active"
    elif normalized_status == ACCOUNT_MEMBERSHIP_STATUS_DISABLED:
        metadata["invite_state"] = "disabled"

    if last_delivery_status in {
        PORTAL_INVITE_DELIVERY_QUEUED,
        PORTAL_INVITE_DELIVERY_SENT,
        PORTAL_INVITE_DELIVERY_FAILED,
        PORTAL_INVITE_DELIVERY_SKIPPED,
    }:
        metadata["last_delivery_status"] = last_delivery_status

    return metadata


def _portal_membership_is_active(membership: object | None) -> bool:
    return bool(
        membership is not None
        and getattr(membership, "status", "") == ACCOUNT_MEMBERSHIP_STATUS_ACTIVE
    )


def _portal_membership_has_allowed_role(
    membership: object | None,
    *,
    required_roles: set[str] | None = None,
) -> bool:
    if membership is None:
        return False
    role = str(getattr(membership, "role", "") or "")
    if role not in PORTAL_MEMBERSHIP_ALLOWED_ROLES:
        return False
    normalized_role = _normalize_customer_membership_role(role)
    if required_roles is not None and normalized_role not in required_roles:
        return False
    return True


def _normalize_customer_membership_role(role: str) -> str:
    normalized_role = str(role or "").strip()
    if normalized_role == ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN:
        return ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN
    return ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN


def _resolve_identity_type(role: str) -> str:
    normalized_role = str(role or "").strip()
    if normalized_role in PLATFORM_ADMIN_ALLOWED_ROLES:
        return IDENTITY_TYPE_PLATFORM_ADMIN
    return IDENTITY_TYPE_USER_ADMIN


def _portal_membership_role_priority(role: str) -> int:
    return 0


def _normalize_platform_admin_role(role: str) -> str:
    return str(role or "").strip()


def _canonicalize_customer_membership_role_for_write(role: str) -> str:
    normalized_role = str(role or "").strip()
    if normalized_role in ACCOUNT_MEMBERSHIP_ALLOWED_ROLES:
        return ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN
    return ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN


def _canonicalize_platform_admin_role_for_write(role: str) -> str:
    normalized_role = str(role or "").strip()
    if normalized_role in PLATFORM_ADMIN_ALLOWED_ROLES:
        return PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN
    return PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN


def _resolve_portal_allowed_actions(role: str) -> list[str]:
    normalized_role = _normalize_customer_membership_role(role)
    actions = [
        USER_ALLOWED_ACTION_VIEW_SITES,
        USER_ALLOWED_ACTION_VIEW_USAGE,
        USER_ALLOWED_ACTION_VIEW_BILLING,
        USER_ALLOWED_ACTION_VIEW_AUDIT,
        USER_ALLOWED_ACTION_PROVISION_SITES,
        USER_ALLOWED_ACTION_MANAGE_SITE_KEYS,
        USER_ALLOWED_ACTION_ARCHIVE_SITES,
    ]
    return actions


def _platform_capability_flags(role: str) -> dict[str, bool]:
    normalized_role = _normalize_platform_admin_role(role)
    return {
        "can_manage_accounts": normalized_role in PLATFORM_ADMIN_ACCOUNT_WRITE_ROLES,
        "can_manage_catalog": normalized_role in PLATFORM_ADMIN_CATALOG_WRITE_ROLES,
        "can_impersonate": normalized_role in PLATFORM_IMPERSONATION_ALLOWED_ROLES,
        "can_manage_billing": normalized_role in PLATFORM_ADMIN_ALLOWED_ROLES,
        "can_review_diagnostics": normalized_role in PLATFORM_ADMIN_ALLOWED_ROLES,
    }


def _slugify_portal_site_segment(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized


def _normalize_portal_site_url(value: str) -> tuple[str, str]:
    raw = str(value or "").strip()
    if not raw:
        raise CommercialPermissionError(
            "service.portal_site_url_required",
            "wordpress site url is required",
        )
    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlsplit(candidate)
    hostname = str(parsed.hostname or "").strip().lower()
    if not hostname:
        raise CommercialPermissionError(
            "service.portal_site_url_invalid",
            "wordpress site url is invalid",
        )
    path = re.sub(r"/+", "/", str(parsed.path or "/").strip())
    path = "/" if not path or path == "." else path
    canonical = f"{parsed.scheme.lower() or 'https'}://{hostname}"
    if path not in {"", "/"}:
        canonical = f"{canonical}{path.rstrip('/')}"
    return canonical, hostname + (f"{path.rstrip('/').replace('/', '-')}" if path not in {"", "/"} else "")


def _extract_site_wordpress_url(site: Site) -> str:
    metadata = site.metadata_json if isinstance(site.metadata_json, dict) else {}
    raw_value = metadata.get("wordpress_url", "")
    return str(raw_value).strip() if raw_value is not None else ""


def assert_platform_admin_role_allowed(
    *,
    role: str,
    allowed_roles: set[str],
    error_code: str,
    message: str,
) -> str:
    normalized_role = _normalize_platform_admin_role(role)
    if normalized_role not in PLATFORM_ADMIN_ALLOWED_ROLES:
        raise CommercialPermissionError(
            "service.platform_admin_role_invalid",
            f"unsupported platform admin role '{normalized_role}'",
        )
    if normalized_role not in allowed_roles:
        raise CommercialPermissionError(error_code, message)
    return normalized_role


def assert_platform_admin_capability(
    *,
    role: str,
    capability: str,
    error_code: str,
    message: str,
) -> str:
    normalized_role = _normalize_platform_admin_role(role)
    if normalized_role not in PLATFORM_ADMIN_ALLOWED_ROLES:
        raise CommercialPermissionError(
            "service.platform_admin_role_invalid",
            f"unsupported platform admin role '{normalized_role}'",
        )
    capabilities = _platform_capability_flags(normalized_role)
    if not bool(capabilities.get(capability)):
        raise CommercialPermissionError(error_code, message)
    return normalized_role



from app.domain.commercial.mixins import (
    CommercialServiceAuditMixin,
    CommercialServiceAccountMixin,
    CommercialServiceSiteMixin,
    CommercialServiceBillingMixin,
    CommercialServicePortalMixin,
    CommercialServiceAdminMixin,
    CommercialServiceRuntimeMixin,
)


class CommercialService(
    CommercialServiceAccountMixin,
    CommercialServiceSiteMixin,
    CommercialServiceBillingMixin,
    CommercialServicePortalMixin,
    CommercialServiceAdminMixin,
    CommercialServiceRuntimeMixin,
    CommercialServiceAuditMixin,
):
    """Commercial service facade composed from domain-specific mixins."""
    pass
