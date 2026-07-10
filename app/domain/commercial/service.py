from __future__ import annotations

from app.domain.commercial.audit_context import ServiceAuditContext

ALLOWED_ABILITY_FAMILIES = {
    "text",
    "vision",
    "workflow",
    "automation",
    "mcp",
    "openclaw",
    "knowledge",
}
DEFAULT_RUNTIME_ENTITLEMENTS = {
    "ability_families": ["*"],
    "channels": ["*"],
    "execution_kinds": ["*"],
    "execution_tiers": ["cloud"],
    "data_classifications": ["*"],
}
DEFAULT_RUNTIME_BUDGETS: dict[str, object] = {
    "max_ai_credits_per_period": 0.0,
    "max_runs_per_period": 0,
    "max_tokens_per_period": 0,
    "max_cost_per_period": 0.0,
}
DEFAULT_RUNTIME_CONCURRENCY: dict[str, object] = {
    "max_active_runs": 0,
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
        "npcink-abilities-toolkit/build-article-block-plan": {
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
        "knowledge": {
            "tariff_class": "low",
            "base_run_price": 0.02,
            "per_1k_tokens_price": 0.0,
        },
    },
}
PLAN_TIER_REGISTRY: dict[str, dict[str, object]] = {
    "free": {
        "tier_id": "free",
        "label": "Free",
        "package_alias": "Free",
        "usage_band": "300 AI credits per month.",
        "positioning": "Conservative single-site package with a small monthly AI credit grant and separate resource boundaries.",
        "monthly_included_points": 300,
        "budgets_template": {
            "max_ai_credits_per_period": 300,
            "max_runs_per_period": 0,
            "max_tokens_per_period": 0,
            "max_cost_per_period": 0.0,
        },
        "concurrency_template": {"max_active_runs": 1},
        "site_limit": 1,
        "max_batch_items": 5,
        "nightly_inspection_runs_per_period": 0,
        "nightly_inspection_retention_days": 14,
        "nightly_inspection_payload_modes": ["metadata_only"],
        "automation_enabled": True,
        "api_enabled": True,
        "openclaw_enabled": True,
        "package_operator_note": "Free limits high-cost AI consumption through monthly AI credits while keeping ordinary Cloud service usage reviewable.",
        "policy_baseline": {
            "grace_period_days": 0,
            "downgrade_policy": "No package-limit downgrade while the unreleased product is in internal development.",
        },
        "feature_groups": [
            "Hosted runtime baseline",
            "Portal usage visibility",
            "Operator-managed subscription changes",
        ],
    },
    "plus": {
        "tier_id": "plus",
        "label": "Plus",
        "package_alias": "Plus",
        "usage_band": "3,000 AI credits per month.",
        "positioning": "Entry paid Plus package for accounts that have outgrown Free but do not yet need full Pro monthly AI credit headroom.",
        "monthly_included_points": 3_000,
        "budgets_template": {
            "max_ai_credits_per_period": 3_000,
            "max_runs_per_period": 0,
            "max_tokens_per_period": 0,
            "max_cost_per_period": 0.0,
        },
        "concurrency_template": {"max_active_runs": 2},
        "site_limit": 3,
        "max_batch_items": 15,
        "nightly_inspection_runs_per_period": 0,
        "nightly_inspection_retention_days": 14,
        "nightly_inspection_payload_modes": ["metadata_only", "excerpt"],
        "automation_enabled": True,
        "api_enabled": True,
        "openclaw_enabled": True,
        "package_operator_note": "Plus gives early paid accounts a controlled step up from Free while keeping Pro as the normal hosted AI package.",
        "policy_baseline": {
            "grace_period_days": 3,
            "downgrade_policy": "No package-limit downgrade while the unreleased product is in internal development.",
        },
        "feature_groups": [
            "Hosted runtime + workflow coverage",
            "Starter paid usage headroom",
            "Operator-managed subscription changes",
        ],
    },
    "pro": {
        "tier_id": "pro",
        "label": "Pro",
        "package_alias": "Pro",
        "usage_band": "10,000 AI credits per month.",
        "positioning": "Commercial Pro package with normal hosted AI consumption controlled by monthly AI credits and separate resource boundaries.",
        "monthly_included_points": 10_000,
        "budgets_template": {
            "max_ai_credits_per_period": 10_000,
            "max_runs_per_period": 0,
            "max_tokens_per_period": 0,
            "max_cost_per_period": 0.0,
        },
        "concurrency_template": {"max_active_runs": 3},
        "site_limit": 5,
        "max_batch_items": 25,
        "nightly_inspection_runs_per_period": 0,
        "nightly_inspection_retention_days": 14,
        "nightly_inspection_payload_modes": ["metadata_only", "excerpt"],
        "automation_enabled": True,
        "api_enabled": True,
        "openclaw_enabled": True,
        "package_operator_note": "Pro keeps ordinary usage broadly available while high-cost AI search, query, and generation paths spend AI credits.",
        "policy_baseline": {
            "grace_period_days": 3,
            "downgrade_policy": "No package-limit downgrade while the unreleased product is in internal development.",
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
        "package_alias": "Agency",
        "usage_band": "150,000 AI credits per month.",
        "positioning": "Commercial Agency package for custom or multi-site Cloud runtime detail with higher AI credit, batch, and resource headroom.",
        "monthly_included_points": 150_000,
        "budgets_template": {
            "max_ai_credits_per_period": 150_000,
            "max_runs_per_period": 0,
            "max_tokens_per_period": 0,
            "max_cost_per_period": 0.0,
        },
        "concurrency_template": {"max_active_runs": 10},
        "site_limit": 25,
        "max_batch_items": 100,
        "nightly_inspection_runs_per_period": 0,
        "nightly_inspection_retention_days": 30,
        "nightly_inspection_payload_modes": ["metadata_only", "excerpt"],
        "automation_enabled": True,
        "api_enabled": True,
        "openclaw_enabled": True,
        "package_operator_note": "Agency represents custom/high-volume coverage; AI credits remain the primary high-cost consumption control.",
        "policy_baseline": {
            "grace_period_days": 7,
            "downgrade_policy": "No package-limit downgrade while the unreleased product is in internal development.",
        },
        "feature_groups": [
            "Higher hosted concurrency",
            "Multi-site commercial headroom",
            "Sustained workflow and automation operations",
        ],
    },
}
DEFAULT_PLAN_TIER_ID = "pro"
DEFAULT_FREE_PLAN_ID = "free"
DEFAULT_FREE_PLAN_VERSION_ID = "free_v1"
DEFAULT_FREE_PLAN_KIND = "default_free"
DEFAULT_FREE_PLAN_SOURCE = "production_default_free_shell_v1"
DEFAULT_FREE_SUBSCRIPTION_SOURCE = "production_default_free_bind_v1"
PRO_TRIAL_DAYS = 14
PRO_MONTHLY_PRICE_CNY = 29.0
PRO_MONTHLY_BILLING_CYCLE = "monthly"
CANONICAL_TIER_PLAN_IDS = {tier_id: (tier_id, f"{tier_id}_v1") for tier_id in PLAN_TIER_REGISTRY}
OPERATOR_MANAGED_POINTS_PACK_REGISTRY: dict[str, dict[str, object]] = {
    "pack_small": {
        "pack_id": "pack_small",
        "label": "Small pack",
        "points_label": "10,000 points equivalent",
        "points_equivalent": 10_000,
        "ai_credits_increment": 10_000,
        "display_order": 1,
        "recommended_for_tiers": ["free", "plus"],
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
        "ai_credits_increment": 35_000,
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
        "ai_credits_increment": 150_000,
        "display_order": 3,
        "recommended_for_tiers": ["agency"],
        "active": True,
        "runs_increment": 150_000,
        "tokens_increment": 30_000_000,
        "cost_increment": 1_499.0,
        "operator_note": "Use when an operator needs a high-headroom current-period top-up without introducing a wallet or self-serve flow.",
    },
}


from app.domain.commercial.mixins import (
    CommercialServiceAccountMixin,
    CommercialServiceAdminMixin,
    CommercialServiceAuditMixin,
    CommercialServiceBillingMixin,
    CommercialServicePaymentMixin,
    CommercialServicePortalMixin,
    CommercialServiceRuntimeMixin,
    CommercialServiceSiteMixin,
    CommercialServiceSupportMixin,
)


class CommercialService(
    CommercialServiceAccountMixin,
    CommercialServiceSiteMixin,
    CommercialServiceBillingMixin,
    CommercialServicePaymentMixin,
    CommercialServicePortalMixin,
    CommercialServiceSupportMixin,
    CommercialServiceAdminMixin,
    CommercialServiceRuntimeMixin,
    CommercialServiceAuditMixin,
):
    """Commercial service facade composed from domain-specific mixins."""

    pass


__all__ = [
    "CommercialService",
    "ServiceAuditContext",
]
