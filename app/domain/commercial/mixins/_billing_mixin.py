"""Commercial service: billing, subscription, and plan operations mixin."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.db import get_session
from app.core.models import (
    PLAN_STATUS_ACTIVE,
    PLAN_VERSION_STATUS_PUBLISHED,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_PAST_DUE,
    SUBSCRIPTION_STATUS_SUSPENDED,
    SUBSCRIPTION_STATUS_TRIALING,
    AccountEntitlementSnapshot,
    AccountSubscription,
    BillingSnapshot,
    PlanVersion,
    Site,
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
        "max_vector_documents": 100,
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
        "max_vector_documents": 800,
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
        "max_vector_documents": 2000,
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
        "max_vector_documents": 10000,
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

COMMERCIAL_COVERED_SUBSCRIPTION_STATUSES = {
    SUBSCRIPTION_STATUS_TRIALING,
    SUBSCRIPTION_STATUS_ACTIVE,
}


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


class CommercialServiceBillingMixin(CommercialServiceAuditMixin):
    def upsert_plan(
        self,
        *,
        plan_id: str,
        name: str,
        status: str = PLAN_STATUS_ACTIVE,
        description: str = "",
        metadata_json: dict[str, object] | None = None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            plan = repository.upsert_plan(
                plan_id=plan_id,
                name=name,
                status=status,
                description=description,
                metadata_json=metadata_json,
            )
            payload = self._serialize_plan(plan)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="plan.upsert",
                outcome="succeeded",
                plan_id=plan.plan_id,
                scope_kind="plan",
                scope_id=plan.plan_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def publish_plan_version(
        self,
        *,
        plan_id: str,
        plan_version_id: str,
        version_label: str,
        status: str = PLAN_VERSION_STATUS_PUBLISHED,
        currency: str = "CNY",
        entitlements_json: dict[str, object] | None = None,
        budgets_json: dict[str, object] | None = None,
        concurrency_json: dict[str, object] | None = None,
        policy_json: dict[str, object] | None = None,
        metadata_json: dict[str, object] | None = None,
        sales_price_cny: float | None = None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            if repository.get_plan(plan_id) is None:
                raise CommercialNotFoundError(
                    "service.plan_not_found",
                    f"plan '{plan_id}' was not found",
                )
            label_conflict = next(
                (
                    version
                    for version in repository.list_plan_versions(plan_id=plan_id, limit=None)
                    if version.version_label == version_label
                    and version.plan_version_id != plan_version_id
                ),
                None,
            )
            if label_conflict is not None:
                raise CommercialConflictError(
                    "service.plan_version_label_conflict",
                    (
                        f"plan '{plan_id}' already has version label '{version_label}' "
                        f"on plan version '{label_conflict.plan_version_id}'"
                    ),
                )
            plan_version = repository.upsert_plan_version(
                plan_version_id=plan_version_id,
                plan_id=plan_id,
                version_label=version_label,
                status=status,
                currency=self._normalize_plan_currency(currency),
                entitlements_json=self._normalize_entitlements(entitlements_json),
                budgets_json=self._normalize_budgets(budgets_json),
                concurrency_json=self._normalize_concurrency(concurrency_json),
                policy_json=self._normalize_commercial_policy(policy_json),
                metadata_json=metadata_json,
            )
            tier_id = self._infer_plan_tier_id(
                repository.get_plan(plan_id),
                [self._serialize_plan_version(plan_version)],
            )
            if status == PLAN_VERSION_STATUS_PUBLISHED and tier_id in {"plus", "pro"}:
                cast(Any, self)._sync_standard_plan_offer_in_session(
                    repository,
                    tier_id=tier_id,
                    plan_id=plan_id,
                    plan_version_id=plan_version.plan_version_id,
                    sales_price_cny=sales_price_cny,
                )
            payload = self._serialize_plan_version(plan_version)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="plan_version.publish",
                outcome="succeeded",
                plan_id=plan_id,
                plan_version_id=plan_version.plan_version_id,
                scope_kind="plan_version",
                scope_id=plan_version.plan_version_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def rebuild_billing_snapshot(
        self,
        site_id: str,
        *,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            site = repository.get_site(site_id)
            if site is None:
                raise CommercialNotFoundError(
                    "service.site_not_found",
                    f"site '{site_id}' was not found",
                )
            subscription = repository.get_latest_account_subscription(site.account_id or "")
            if subscription is None:
                raise CommercialNotFoundError(
                    "service.subscription_not_found",
                    f"no subscription was found for site '{site_id}'",
                )
            period_start_at, period_end_at = self._resolve_period(subscription, self.now_factory())
            snapshot = self._upsert_current_period_billing_snapshot_in_session(
                repository=repository,
                site_id=site_id,
                subscription=subscription,
                period_start_at=period_start_at,
                period_end_at=period_end_at,
            )
            payload = self._serialize_billing_snapshot(snapshot)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="billing_snapshot.rebuild",
                outcome="succeeded",
                account_id=subscription.account_id,
                site_id=site_id,
                subscription_id=subscription.subscription_id,
                plan_version_id=subscription.plan_version_id,
                scope_kind="billing_snapshot",
                scope_id=snapshot.snapshot_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def list_billing_snapshots(self, site_id: str) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            if repository.get_site(site_id) is None:
                raise CommercialNotFoundError(
                    "service.site_not_found",
                    f"site '{site_id}' was not found",
                )
            snapshots = repository.list_billing_snapshots(site_id)
            return {
                "site_id": site_id,
                "items": [self._serialize_billing_snapshot(item) for item in snapshots],
            }

    def inspect_commercial_policy(self, site_id: str) -> dict[str, object]:
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            site = repository.get_site(site_id)
            if site is None:
                raise CommercialNotFoundError(
                    "service.site_not_found",
                    f"site '{site_id}' was not found",
                )

            subscription = repository.get_latest_account_subscription(site.account_id or "")
            snapshot = repository.get_active_entitlement_snapshot(
                site.account_id or "",
                subscription_id=subscription.subscription_id if subscription else None,
            )
            plan_version = self._resolve_current_subscription_plan_version(
                repository,
                subscription,
            )
            policy = self._normalize_commercial_policy(getattr(plan_version, "policy_json", None))
            period_start_at, period_end_at = self._resolve_period(subscription, now)
            meter_events = repository.list_usage_meter_events(
                site_id,
                subscription_id=subscription.subscription_id if subscription else None,
                period_start_at=period_start_at,
                period_end_at=period_end_at,
                limit=None,
            )
            totals = self._aggregate_meter_events(meter_events)
            budgets = self._resolve_effective_subscription_budgets(
                plan_version=plan_version,
                subscription=subscription,
            )
            budget_state = self._build_budget_policy_state(
                repository=repository,
                subscription=subscription,
                policy=policy,
                budgets=budgets,
                totals=totals,
                period_start_at=period_start_at,
            )
            batch_limits = self._resolve_runtime_batch_limits(
                snapshot=None,
                plan_version=plan_version,
            )
            pro_cloud_runtime = self._build_pro_cloud_runtime_state(
                meter_events,
                batch_limits=batch_limits,
            )

            return {
                "site_id": site_id,
                "generated_at": self._serialize_datetime(now),
                "site": cast(Any, self)._serialize_site(site),
                "subscription": (
                    self._serialize_subscription(subscription) if subscription else None
                ),
                "plan_version": (
                    self._serialize_plan_version(plan_version) if plan_version else None
                ),
                "entitlement_snapshot": (
                    self._serialize_entitlement_snapshot(snapshot) if snapshot else None
                ),
                "policy": policy,
                "period_start_at": self._serialize_datetime(period_start_at),
                "period_end_at": self._serialize_datetime(period_end_at),
                "usage_totals": totals,
                "batch_limits": batch_limits,
                "pro_cloud_runtime": pro_cloud_runtime,
                "subscription_grace": self._build_subscription_grace_state(
                    subscription=subscription,
                    policy=policy,
                    period_end_at=period_end_at,
                    now=now,
                ),
                "budget_state": budget_state,
            }

    def reconcile_billing_snapshot(self, site_id: str) -> dict[str, object]:
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            site = repository.get_site(site_id)
            if site is None:
                raise CommercialNotFoundError(
                    "service.site_not_found",
                    f"site '{site_id}' was not found",
                )

            subscription = repository.get_latest_account_subscription(site.account_id or "")
            if subscription is None:
                raise CommercialNotFoundError(
                    "service.subscription_not_found",
                    f"no subscription was found for site '{site_id}'",
                )

            period_start_at, period_end_at = self._resolve_period(subscription, now)
            meter_events = repository.list_usage_meter_events(
                site_id,
                subscription_id=subscription.subscription_id,
                period_start_at=period_start_at,
                period_end_at=period_end_at,
                limit=None,
            )
            ledger_totals = self._aggregate_meter_events(meter_events)
            snapshots = repository.list_billing_snapshots(site_id)
            current_snapshot = next(
                (
                    item
                    for item in snapshots
                    if item.subscription_id == subscription.subscription_id
                    and self._normalize_datetime(item.period_start_at) == period_start_at
                    and self._normalize_datetime(item.period_end_at) == period_end_at
                ),
                None,
            )
            snapshot_payload = (
                self._serialize_billing_snapshot(current_snapshot) if current_snapshot else None
            )
            snapshot_totals = current_snapshot.totals_json if current_snapshot is not None else {}
            plan_version = self._resolve_current_subscription_plan_version(
                repository,
                subscription,
            )
            policy = self._normalize_commercial_policy(getattr(plan_version, "policy_json", None))
            tolerance = self._normalize_reconciliation_tolerance(
                policy.get("reconciliation") if isinstance(policy, dict) else None
            )
            mismatch = self._build_billing_mismatch(
                ledger_totals=ledger_totals,
                snapshot_totals=snapshot_totals if isinstance(snapshot_totals, dict) else {},
                tolerance=tolerance,
                snapshot_present=current_snapshot is not None,
            )
            return {
                "site_id": site_id,
                "subscription_id": subscription.subscription_id,
                "plan_version_id": subscription.plan_version_id,
                "period_start_at": self._serialize_datetime(period_start_at),
                "period_end_at": self._serialize_datetime(period_end_at),
                "ledger_totals": ledger_totals,
                "snapshot": snapshot_payload,
                "reconciliation": mismatch,
            }

    def list_operator_managed_points_packs(
        self,
        *,
        repository: CommercialRepository | None = None,
    ) -> list[dict[str, object]]:
        def _normalize_recommended_tiers(value: object) -> list[str]:
            if not isinstance(value, (list, tuple, set)):
                return []
            return [str(item).strip() for item in value if str(item).strip()]

        def _serialize_pack(
            template: dict[str, object],
            overlay: dict[str, object] | None,
        ) -> dict[str, object]:
            merged = dict(template)
            if overlay:
                merged.update(overlay)
            return {
                "pack_id": str(merged.get("pack_id") or ""),
                "label": str(merged.get("label") or ""),
                "points_label": str(merged.get("points_label") or ""),
                "points_equivalent": self._coerce_int(merged.get("points_equivalent")),
                "ai_credits_increment": round(
                    float(self._coerce_float(merged.get("ai_credits_increment"))),
                    6,
                ),
                "display_order": self._coerce_int(merged.get("display_order")),
                "recommended_for_tiers": _normalize_recommended_tiers(
                    merged.get("recommended_for_tiers")
                ),
                "runs_increment": round(
                    float(self._coerce_float(merged.get("runs_increment"))),
                    6,
                ),
                "tokens_increment": round(
                    float(self._coerce_float(merged.get("tokens_increment"))),
                    6,
                ),
                "cost_increment": round(
                    float(self._coerce_float(merged.get("cost_increment"))),
                    6,
                ),
                "operator_note": str(merged.get("operator_note") or ""),
                "active": bool(merged.get("active", True)),
                "has_operator_overlay": bool(overlay),
                "overlay_updated_at": (
                    str(overlay.get("overlay_updated_at") or "")
                    if isinstance(overlay, dict)
                    else ""
                ),
            }

        def _build_items(active_repository: CommercialRepository) -> list[dict[str, object]]:
            overlays = self._load_operator_managed_points_pack_overlays(active_repository)
            items = [
                _serialize_pack(
                    template,
                    overlays.get(str(template.get("pack_id") or "")),
                )
                for template in OPERATOR_MANAGED_POINTS_PACK_REGISTRY.values()
            ]
            return sorted(
                items,
                key=lambda item: (
                    self._coerce_int(item.get("display_order")),
                    str(item.get("pack_id") or ""),
                ),
            )

        if repository is not None:
            return _build_items(repository)
        with get_session(self.database_url) as session:
            return _build_items(CommercialRepository(session))

    def apply_operator_managed_subscription_topup(
        self,
        *,
        subscription_id: str,
        pack_id: str = "",
        ai_credits_increment: float = 0.0,
        runs_increment: float = 0.0,
        tokens_increment: float = 0.0,
        cost_increment: float = 0.0,
        reason: str = "",
        note: str = "",
        target_period_start_at: datetime | None = None,
        target_period_end_at: datetime | None = None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_reason = str(reason or "").strip()
        normalized_note = str(note or "").strip()
        if not normalized_reason:
            raise CommercialValidationError(
                "service.subscription_topup_reason_required",
                "operator-managed top-up requires an operator reason",
            )

        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            payload = self._apply_operator_managed_subscription_topup_in_session(
                repository=repository,
                subscription_id=subscription_id,
                pack_id=pack_id,
                ai_credits_increment=ai_credits_increment,
                runs_increment=runs_increment,
                tokens_increment=tokens_increment,
                cost_increment=cost_increment,
                reason=normalized_reason,
                note=normalized_note,
                target_period_start_at=target_period_start_at,
                target_period_end_at=target_period_end_at,
                audit_context=audit_context,
            )
            session.commit()
            return payload

    def rebuild_subscription_billing_snapshots(
        self,
        subscription_id: str,
        *,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            subscription = repository.get_subscription(subscription_id)
            if subscription is None:
                raise CommercialNotFoundError(
                    "service.subscription_not_found",
                    f"subscription '{subscription_id}' was not found",
                )
            covered_sites = repository.list_sites(account_id=subscription.account_id, limit=None)
            period_start_at, period_end_at = self._resolve_period(subscription, self.now_factory())
            refresh = self._refresh_subscription_billing_snapshots_in_session(
                repository=repository,
                subscription=subscription,
                covered_sites=covered_sites,
                period_start_at=period_start_at,
                period_end_at=period_end_at,
            )
            latest_billing_snapshots = repository.get_latest_billing_snapshots_by_site(
                site_ids=[
                    str(site.site_id or "")
                    for site in covered_sites
                    if str(site.site_id or "").strip()
                ]
            )
            payload: dict[str, object] = {
                "subscription": self._serialize_subscription(subscription),
                "billing_snapshot_refresh": refresh,
                "billing_snapshot_status": self._build_subscription_billing_snapshot_status(
                    subscription=subscription,
                    sites=covered_sites,
                    latest_billing_snapshots=latest_billing_snapshots,
                    period_start_at=period_start_at,
                    period_end_at=period_end_at,
                ),
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="subscription.billing_snapshot.rebuild",
                outcome="succeeded",
                account_id=subscription.account_id,
                subscription_id=subscription.subscription_id,
                plan_id=subscription.plan_id,
                plan_version_id=subscription.plan_version_id,
                scope_kind="subscription",
                scope_id=subscription.subscription_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def list_admin_plans(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            plans = repository.list_plans(status=status, limit=limit)
            versions = repository.list_plan_versions(limit=None)
            versions_by_plan: dict[str, list[object]] = defaultdict(list)
            for version in versions:
                versions_by_plan[str(version.plan_id or "")].append(version)
            subscriptions = repository.list_subscriptions(limit=None)
        subscription_counts = Counter(
            subscription.plan_id for subscription in subscriptions if subscription.plan_id
        )
        active_subscription_counts = Counter(
            subscription.plan_id
            for subscription in subscriptions
            if subscription.plan_id
            and subscription.status
            in {
                SUBSCRIPTION_STATUS_TRIALING,
                SUBSCRIPTION_STATUS_ACTIVE,
                SUBSCRIPTION_STATUS_PAST_DUE,
                SUBSCRIPTION_STATUS_SUSPENDED,
            }
        )
        items = []
        for plan in plans:
            plan_id = str(plan.plan_id or "")
            serialized_versions = [
                self._serialize_plan_version(version)
                for version in versions_by_plan.get(plan_id, [])
            ]
            tier_summary = self._build_plan_tier_summary(plan, serialized_versions)
            latest_version = self._select_latest_plan_version(serialized_versions)
            items.append(
                {
                    "plan": self._serialize_plan(plan),
                    "versions": serialized_versions,
                    "tier_summary": tier_summary,
                    "latest_version": latest_version,
                    "published_version_count": sum(
                        1
                        for version in serialized_versions
                        if str(version.get("status") or "") == PLAN_VERSION_STATUS_PUBLISHED
                    ),
                    "subscription_counts": {
                        "total": int(subscription_counts.get(plan_id, 0)),
                        "active": int(active_subscription_counts.get(plan_id, 0)),
                    },
                }
            )
        return {
            "filters": {"status": status or "", "limit": limit},
            "tier_templates": self._list_plan_tier_templates(),
            "items": items,
        }

    def get_admin_plan(self, plan_id: str) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            plan = repository.get_plan(plan_id)
            if plan is None:
                raise CommercialNotFoundError(
                    "service.plan_not_found",
                    f"plan '{plan_id}' was not found",
                )
            versions = repository.list_plan_versions(plan_id=plan_id, limit=None)
            offers = repository.list_plan_offers()
            subscriptions = repository.list_subscriptions(plan_id=plan_id, limit=None)
            account_ids = [
                subscription.account_id for subscription in subscriptions if subscription.account_id
            ]
            sites = repository.list_sites(account_ids=account_ids, limit=None)
            sites_by_account: dict[str, list[Site]] = defaultdict(list)
            for site in sites:
                if site.account_id:
                    sites_by_account[site.account_id].append(site)
            accounts = {
                account.account_id: account
                for account in repository.list_accounts(account_ids=account_ids, limit=None)
            }
        serialized_versions = [self._serialize_plan_version(version) for version in versions]
        tier_summary = self._build_plan_tier_summary(plan, serialized_versions)
        latest_version = self._select_latest_plan_version(serialized_versions)
        sales_offer = next(
            (
                cast(Any, self)._serialize_plan_offer(offer)
                for offer in offers
                if str(getattr(offer, "plan_id", "") or "") == plan_id
                and getattr(offer, "account_id", None) is None
                and str(getattr(offer, "purchase_mode", "") or "") == "self_serve"
                and str(getattr(offer, "status", "") or "") == "active"
            ),
            None,
        )
        return {
            "plan": self._serialize_plan(plan),
            "versions": serialized_versions,
            "tier_summary": tier_summary,
            "latest_version": latest_version,
            "sales_offer": sales_offer,
            "package_fit_cues": self._build_plan_package_fit_cues(
                tier_summary=tier_summary,
                latest_version=latest_version,
            ),
            "subscriptions": [
                {
                    "subscription": self._serialize_subscription(subscription),
                    "account": (
                        cast(Any, self)._serialize_account(accounts[subscription.account_id])
                        if subscription.account_id in accounts
                        else None
                    ),
                    "sites": [
                        cast(Any, self)._serialize_site(site)
                        for site in sites_by_account.get(subscription.account_id, [])
                    ],
                    "expiry": self._serialize_expiry_state(subscription),
                }
                for subscription in subscriptions
            ],
        }

    def list_admin_subscriptions(
        self,
        *,
        status: str | None = None,
        account_id: str | None = None,
        plan_id: str | None = None,
        expires_before: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, object]:
        normalized_offset = max(0, int(offset or 0))
        resolved_limit = max(1, int(limit or 100))
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            total = repository.count_subscriptions(
                status=status,
                account_id=account_id,
                plan_id=plan_id,
                current_period_end_before=expires_before,
            )
            subscriptions = repository.list_subscriptions(
                status=status,
                account_id=account_id,
                plan_id=plan_id,
                current_period_end_before=expires_before,
                offset=normalized_offset,
                limit=resolved_limit,
            )
            account_ids = [subscription.account_id for subscription in subscriptions]
            accounts = {
                account.account_id: account
                for account in repository.list_accounts(account_ids=account_ids, limit=None)
            }
            sites = repository.list_sites(account_ids=account_ids, limit=None)
            sites_by_account: dict[str, list[Site]] = defaultdict(list)
            for site in sites:
                if site.account_id:
                    sites_by_account[site.account_id].append(site)
            latest_billing_by_site = repository.get_latest_billing_snapshots_by_site(
                site_ids=[site.site_id for site in sites],
            )

        items = []
        now = self.now_factory()
        for subscription in subscriptions:
            account_sites = sites_by_account.get(subscription.account_id, [])
            period_start_at, period_end_at = self._resolve_period(subscription, now)
            items.append(
                {
                    "subscription": self._serialize_subscription(subscription),
                    "account": cast(Any, self)._serialize_account(accounts[subscription.account_id])
                    if subscription.account_id in accounts
                    else None,
                    "covered_sites": [
                        cast(Any, self)._serialize_site(site) for site in account_sites
                    ],
                    "coverage": self._build_subscription_coverage_summary(
                        subscription,
                        site_count=len(account_sites),
                    ),
                    "expiry": self._serialize_expiry_state(subscription),
                    "latest_billing_snapshots": [
                        self._serialize_billing_snapshot(latest_billing_by_site[site.site_id])
                        for site in account_sites
                        if site.site_id in latest_billing_by_site
                    ],
                    "billing_snapshot_status": self._build_subscription_billing_snapshot_status(
                        subscription=subscription,
                        sites=account_sites,
                        latest_billing_snapshots=latest_billing_by_site,
                        period_start_at=period_start_at,
                        period_end_at=period_end_at,
                    ),
                }
            )
        return {
            "filters": {
                "status": status or "",
                "account_id": account_id or "",
                "plan_id": plan_id or "",
                "expires_before": self._serialize_datetime(expires_before),
                "offset": normalized_offset,
                "limit": resolved_limit,
            },
            "items": items,
            "total": total,
            "pagination": {
                "offset": normalized_offset,
                "limit": resolved_limit,
                "total": total,
                "has_more": normalized_offset + len(items) < total,
            },
        }

    def get_admin_subscription(self, subscription_id: str) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            subscription = repository.get_subscription(subscription_id)
            if subscription is None:
                raise CommercialNotFoundError(
                    "service.subscription_not_found",
                    f"subscription '{subscription_id}' was not found",
                )
            account = (
                repository.get_account(subscription.account_id) if subscription.account_id else None
            )
            plan = repository.get_plan(subscription.plan_id) if subscription.plan_id else None
            plan_version = self._resolve_current_subscription_plan_version(
                repository,
                subscription,
            )
            sites = repository.list_sites(account_id=subscription.account_id, limit=None)
            billing_snapshots = repository.get_latest_billing_snapshots_by_site(
                site_ids=[site.site_id for site in sites]
            )
            policy = self._normalize_commercial_policy(getattr(plan_version, "policy_json", None))
            budgets = self._resolve_effective_subscription_budgets(
                plan_version=plan_version,
                subscription=subscription,
            )
            now = self.now_factory()
            period_start_at, period_end_at = self._resolve_period(subscription, now)
            meter_events = [
                event
                for event in repository.list_usage_meter_events_for_admin(
                    account_ids=[subscription.account_id],
                    since=period_start_at,
                    limit=None,
                )
                if str(getattr(event, "subscription_id", "") or "") == subscription.subscription_id
                and (
                    period_end_at is None
                    or (
                        (event_created_at := getattr(event, "created_at", None)) is not None
                        and self._normalize_datetime(event_created_at) <= period_end_at
                    )
                )
            ]
            usage_totals = self._aggregate_meter_events(meter_events)
            budget_state = self._build_budget_policy_state(
                repository=repository,
                subscription=subscription,
                policy=policy,
                budgets=budgets,
                totals=usage_totals,
                period_start_at=period_start_at,
            )
            topup_summary = self._build_subscription_topup_summary(
                subscription, repository=repository
            )
            site_count = repository.count_sites_by_account(
                account_ids=[subscription.account_id]
            ).get(subscription.account_id or "", 0)
        return {
            "subscription": self._serialize_subscription(subscription),
            "expiry": self._serialize_expiry_state(subscription),
            "account": cast(Any, self)._serialize_account(account) if account is not None else None,
            "covered_sites": [cast(Any, self)._serialize_site(site) for site in sites],
            "plan": self._serialize_plan(plan) if plan is not None else None,
            "plan_version": (
                self._serialize_plan_version(plan_version) if plan_version is not None else None
            ),
            "latest_billing_snapshots": [
                self._serialize_billing_snapshot(snapshot)
                for snapshot in billing_snapshots.values()
            ],
            "billing_snapshot_status": self._build_subscription_billing_snapshot_status(
                subscription=subscription,
                sites=sites,
                latest_billing_snapshots=billing_snapshots,
                period_start_at=period_start_at,
                period_end_at=period_end_at,
            ),
            "coverage": self._build_subscription_coverage_summary(
                subscription,
                site_count=site_count,
                site_limit=cast(Any, self)._resolve_site_limit(
                    plan_version=plan_version,
                    subscription=subscription,
                ),
            ),
            "commercial_policy": policy,
            "budget_headroom": self._build_subscription_budget_headroom(
                plan_version=plan_version,
                effective_budgets=budgets,
                topup_summary=topup_summary,
            ),
            "budget_state": budget_state,
            "subscription_grace": self._build_subscription_grace_state(
                subscription=subscription,
                policy=policy,
                period_end_at=period_end_at,
                now=now,
            ),
            "usage_totals": usage_totals,
            "topup_summary": topup_summary,
        }

    def inspect_usage_meter(self, site_id: str, *, limit: int = 50) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            site = repository.get_site(site_id)
            if site is None:
                raise CommercialNotFoundError(
                    "service.site_not_found",
                    f"site '{site_id}' was not found",
                )
            subscription = repository.get_latest_account_subscription(site.account_id or "")
            period_start_at, period_end_at = self._resolve_period(subscription, self.now_factory())
            events = repository.list_usage_meter_events(
                site_id,
                subscription_id=subscription.subscription_id if subscription else None,
                period_start_at=period_start_at,
                period_end_at=period_end_at,
                limit=limit,
            )
            totals = self._aggregate_meter_events(events)
            return {
                "site_id": site_id,
                "subscription_id": subscription.subscription_id if subscription else "",
                "period_start_at": self._serialize_datetime(period_start_at),
                "period_end_at": self._serialize_datetime(period_end_at),
                "totals": totals,
                "items": [self._serialize_meter_event(event) for event in events],
            }

    def _ensure_free_version_in_session(
        self,
        *,
        repository: CommercialRepository,
    ) -> tuple[str, str]:
        tier_id = "free"
        baseline = PLAN_TIER_REGISTRY[tier_id]
        plan_id = DEFAULT_FREE_PLAN_ID
        plan_version_id = DEFAULT_FREE_PLAN_VERSION_ID

        repository.upsert_plan(
            plan_id=plan_id,
            name=str(baseline.get("package_alias") or "Free"),
            status=PLAN_STATUS_ACTIVE,
            description=str(baseline.get("positioning") or ""),
            metadata_json={
                "tier_id": tier_id,
                "package_alias": str(baseline.get("package_alias") or "Free"),
                "plan_kind": DEFAULT_FREE_PLAN_KIND,
                "source": DEFAULT_FREE_PLAN_SOURCE,
            },
        )

        policy_baseline = self._sanitize_payload_dict(baseline.get("policy_baseline")) or {}
        budgets_template = self._sanitize_payload_dict(baseline.get("budgets_template")) or {}
        concurrency_template = (
            self._sanitize_payload_dict(baseline.get("concurrency_template")) or {}
        )
        repository.upsert_plan_version(
            plan_version_id=plan_version_id,
            plan_id=plan_id,
            version_label="v1",
            status=PLAN_VERSION_STATUS_PUBLISHED,
            currency="CNY",
            entitlements_json=cast(dict[str, object], DEFAULT_RUNTIME_ENTITLEMENTS),
            budgets_json=budgets_template,
            concurrency_json=concurrency_template,
            policy_json={
                "subscription": {
                    "grace_period_days": self._coerce_int(policy_baseline.get("grace_period_days")),
                },
            },
            metadata_json={
                "tier_id": tier_id,
                "package_alias": str(baseline.get("package_alias") or "Free"),
                "plan_kind": DEFAULT_FREE_PLAN_KIND,
                "site_limit": self._coerce_int(baseline.get("site_limit")),
                "max_vector_documents": self._coerce_int(baseline.get("max_vector_documents")),
                "monthly_included_points": self._coerce_int(
                    baseline.get("monthly_included_points")
                ),
                "max_batch_items": self._coerce_int(baseline.get("max_batch_items")),
                "nightly_inspection_runs_per_period": self._coerce_int(
                    baseline.get("nightly_inspection_runs_per_period")
                ),
                "nightly_inspection_retention_days": max(
                    1,
                    self._coerce_int(baseline.get("nightly_inspection_retention_days") or 14),
                ),
                "nightly_inspection_payload_modes": self._normalize_list(
                    baseline.get("nightly_inspection_payload_modes"),
                    default=["metadata_only"],
                ),
                "automation_enabled": bool(baseline.get("automation_enabled")),
                "api_enabled": bool(baseline.get("api_enabled")),
                "openclaw_enabled": bool(baseline.get("openclaw_enabled")),
                "source": DEFAULT_FREE_PLAN_SOURCE,
            },
        )
        return plan_id, plan_version_id

    def _ensure_plan_tier_version_in_session(
        self,
        *,
        repository: CommercialRepository,
        tier_id: str,
    ) -> tuple[str, str]:
        if tier_id == "free":
            return self._ensure_free_version_in_session(repository=repository)

        baseline = PLAN_TIER_REGISTRY.get(tier_id)
        if baseline is None:
            raise CommercialNotFoundError(
                "service.plan_tier_not_found",
                f"plan tier '{tier_id}' was not found",
            )

        plan_id, plan_version_id = CANONICAL_TIER_PLAN_IDS[tier_id]
        existing_versions = repository.list_plan_versions(
            plan_id=plan_id,
            status=PLAN_VERSION_STATUS_PUBLISHED,
            limit=1,
        )
        if repository.get_plan(plan_id) is not None and existing_versions:
            return plan_id, existing_versions[0].plan_version_id
        policy_baseline = self._sanitize_payload_dict(baseline.get("policy_baseline")) or {}
        budgets_template = self._sanitize_payload_dict(baseline.get("budgets_template")) or {}
        concurrency_template = (
            self._sanitize_payload_dict(baseline.get("concurrency_template")) or {}
        )
        package_alias = str(
            baseline.get("package_alias") or baseline.get("label") or tier_id.title()
        )

        repository.upsert_plan(
            plan_id=plan_id,
            name=package_alias,
            status=PLAN_STATUS_ACTIVE,
            description=str(baseline.get("positioning") or ""),
            metadata_json={
                "tier_id": tier_id,
                "package_alias": package_alias,
                "source": "canonical_package_shell_v1",
            },
        )
        repository.upsert_plan_version(
            plan_version_id=plan_version_id,
            plan_id=plan_id,
            version_label="v1",
            status=PLAN_VERSION_STATUS_PUBLISHED,
            currency="CNY",
            entitlements_json=cast(dict[str, object], DEFAULT_RUNTIME_ENTITLEMENTS),
            budgets_json=budgets_template,
            concurrency_json=concurrency_template,
            policy_json={
                "subscription": {
                    "grace_period_days": self._coerce_int(policy_baseline.get("grace_period_days")),
                },
            },
            metadata_json={
                "tier_id": tier_id,
                "package_alias": package_alias,
                "monthly_included_points": self._coerce_int(
                    baseline.get("monthly_included_points")
                ),
                "site_limit": self._coerce_int(baseline.get("site_limit")),
                "max_vector_documents": self._coerce_int(baseline.get("max_vector_documents")),
                "max_batch_items": self._coerce_int(baseline.get("max_batch_items")),
                "nightly_inspection_runs_per_period": self._coerce_int(
                    baseline.get("nightly_inspection_runs_per_period")
                ),
                "nightly_inspection_retention_days": max(
                    1,
                    self._coerce_int(baseline.get("nightly_inspection_retention_days") or 14),
                ),
                "nightly_inspection_payload_modes": self._normalize_list(
                    baseline.get("nightly_inspection_payload_modes"),
                    default=["metadata_only"],
                ),
                "automation_enabled": bool(baseline.get("automation_enabled")),
                "api_enabled": bool(baseline.get("api_enabled")),
                "openclaw_enabled": bool(baseline.get("openclaw_enabled")),
                "source": "canonical_package_shell_v1",
            },
        )
        return plan_id, plan_version_id

    def _apply_operator_managed_subscription_topup_in_session(
        self,
        *,
        repository: CommercialRepository,
        subscription_id: str,
        pack_id: str = "",
        ai_credits_increment: float = 0.0,
        runs_increment: float = 0.0,
        tokens_increment: float = 0.0,
        cost_increment: float = 0.0,
        reason: str,
        note: str = "",
        target_period_start_at: datetime | None = None,
        target_period_end_at: datetime | None = None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        now = self.now_factory()
        selected_pack = self._resolve_operator_managed_points_pack(pack_id, repository=repository)
        pack_ai_credits_increment = (
            self._coerce_float(selected_pack.get("ai_credits_increment")) if selected_pack else 0.0
        )
        pack_runs_increment = (
            self._coerce_float(selected_pack.get("runs_increment")) if selected_pack else 0.0
        )
        pack_tokens_increment = (
            self._coerce_float(selected_pack.get("tokens_increment")) if selected_pack else 0.0
        )
        pack_cost_increment = (
            self._coerce_float(selected_pack.get("cost_increment")) if selected_pack else 0.0
        )
        normalized_ai_credits = max(
            0.0,
            pack_ai_credits_increment + self._coerce_float(ai_credits_increment),
        )
        normalized_runs = max(0.0, pack_runs_increment + self._coerce_float(runs_increment))
        normalized_tokens = max(0.0, pack_tokens_increment + self._coerce_float(tokens_increment))
        normalized_cost = max(0.0, pack_cost_increment + self._coerce_float(cost_increment))
        if (
            normalized_ai_credits <= 0
            and normalized_runs <= 0
            and normalized_tokens <= 0
            and normalized_cost <= 0
        ):
            raise CommercialValidationError(
                "service.subscription_topup_invalid",
                "operator-managed top-up requires either a standard pack or at least one positive budget increment",
            )
        subscription = repository.get_subscription(subscription_id)
        if subscription is None:
            raise CommercialNotFoundError(
                "service.subscription_not_found",
                f"subscription '{subscription_id}' was not found",
            )
        plan_version = self._resolve_current_subscription_plan_version(repository, subscription)
        if plan_version is None:
            raise CommercialNotFoundError(
                "service.plan_version_not_found",
                f"plan version '{subscription.plan_version_id}' was not found",
            )

        period_start_at, period_end_at = self._resolve_period(subscription, now)
        expected_period_start = self._serialize_datetime(period_start_at)
        expected_period_end = self._serialize_datetime(period_end_at)
        requested_period_start = self._serialize_datetime(target_period_start_at)
        requested_period_end = self._serialize_datetime(target_period_end_at)
        if target_period_start_at is not None and requested_period_start != expected_period_start:
            raise CommercialValidationError(
                "service.subscription_topup_period_mismatch",
                "operator-managed top-up target period does not match the active subscription period",
            )
        if target_period_end_at is not None and requested_period_end != expected_period_end:
            raise CommercialValidationError(
                "service.subscription_topup_period_mismatch",
                "operator-managed top-up target period does not match the active subscription period",
            )

        base_entitlements = self._normalize_entitlements(plan_version.entitlements_json)
        base_budgets = self._resolve_effective_subscription_budgets(
            plan_version=plan_version,
            subscription=subscription,
        )
        base_concurrency = self._normalize_concurrency(plan_version.concurrency_json)
        base_policy = self._normalize_commercial_policy(plan_version.policy_json)

        topup_id = f"topup_{uuid4().hex[:12]}"
        increment_payload = {
            "ai_credits": round(normalized_ai_credits, 6),
            "runs": round(normalized_runs, 6),
            "tokens": round(normalized_tokens, 6),
            "cost": round(normalized_cost, 6),
        }
        updated_budgets = {
            "max_ai_credits_per_period": round(
                self._coerce_float(base_budgets.get("max_ai_credits_per_period"))
                + normalized_ai_credits,
                6,
            ),
            "max_runs_per_period": round(
                self._coerce_float(base_budgets.get("max_runs_per_period")) + normalized_runs,
                6,
            ),
            "max_tokens_per_period": round(
                self._coerce_float(base_budgets.get("max_tokens_per_period")) + normalized_tokens,
                6,
            ),
            "max_cost_per_period": round(
                self._coerce_float(base_budgets.get("max_cost_per_period")) + normalized_cost,
                6,
            ),
        }

        subscription_metadata = dict(subscription.metadata_json or {})
        topup_history = subscription_metadata.get("operator_managed_topups")
        topup_items = list(topup_history) if isinstance(topup_history, list) else []
        topup_record = {
            "topup_id": topup_id,
            "applied_at": self._serialize_datetime(now),
            "target_period_start_at": expected_period_start,
            "target_period_end_at": expected_period_end,
            "pack_id": str(selected_pack.get("pack_id") or "") if selected_pack else "",
            "pack_label": str(selected_pack.get("label") or "") if selected_pack else "",
            "points_label": str(selected_pack.get("points_label") or "") if selected_pack else "",
            "increments": increment_payload,
            "reason": reason,
            "note": note,
            "actor_kind": audit_context.actor_kind if audit_context else "",
            "actor_ref": audit_context.actor_ref if audit_context else "",
        }
        topup_items.append(topup_record)
        subscription_metadata["operator_managed_topups"] = topup_items[-20:]
        subscription_metadata["current_period_topup_totals"] = {
            "ai_credits": round(
                sum(
                    self._coerce_float(
                        item.get("increments", {}).get("ai_credits")
                        if isinstance(item.get("increments"), dict)
                        else 0.0
                    )
                    for item in topup_items
                    if isinstance(item, dict)
                    and str(item.get("target_period_start_at") or "") == expected_period_start
                    and str(item.get("target_period_end_at") or "") == expected_period_end
                ),
                6,
            ),
            "runs": round(
                sum(
                    self._coerce_float(
                        item.get("increments", {}).get("runs")
                        if isinstance(item.get("increments"), dict)
                        else 0.0
                    )
                    for item in topup_items
                    if isinstance(item, dict)
                    and str(item.get("target_period_start_at") or "") == expected_period_start
                    and str(item.get("target_period_end_at") or "") == expected_period_end
                ),
                6,
            ),
            "tokens": round(
                sum(
                    self._coerce_float(
                        item.get("increments", {}).get("tokens")
                        if isinstance(item.get("increments"), dict)
                        else 0.0
                    )
                    for item in topup_items
                    if isinstance(item, dict)
                    and str(item.get("target_period_start_at") or "") == expected_period_start
                    and str(item.get("target_period_end_at") or "") == expected_period_end
                ),
                6,
            ),
            "cost": round(
                sum(
                    self._coerce_float(
                        item.get("increments", {}).get("cost")
                        if isinstance(item.get("increments"), dict)
                        else 0.0
                    )
                    for item in topup_items
                    if isinstance(item, dict)
                    and str(item.get("target_period_start_at") or "") == expected_period_start
                    and str(item.get("target_period_end_at") or "") == expected_period_end
                ),
                6,
            ),
        }

        subscription.metadata_json = subscription_metadata
        repository.supersede_entitlement_snapshots(subscription.account_id)
        snapshot = repository.create_entitlement_snapshot(
            account_id=subscription.account_id,
            subscription_id=subscription.subscription_id,
            plan_version_id=plan_version.plan_version_id,
            entitlements_json=base_entitlements,
            budgets_json=cast(dict[str, object], updated_budgets),
            concurrency_json=base_concurrency,
            policy_json=base_policy,
            site_limit=cast(Any, self)._resolve_site_limit(
                plan_version=plan_version,
                subscription=subscription,
            ),
            metadata_json={
                "source": "subscription_topup",
                "topup_id": topup_id,
                "target_period_start_at": expected_period_start,
                "target_period_end_at": expected_period_end,
                "pack_id": str(selected_pack.get("pack_id") or "") if selected_pack else "",
                "pack_label": str(selected_pack.get("label") or "") if selected_pack else "",
                "points_label": str(selected_pack.get("points_label") or "")
                if selected_pack
                else "",
                "increments": increment_payload,
                "reason": reason,
            },
        )
        covered_sites = repository.list_sites(account_id=subscription.account_id, limit=None)
        billing_snapshot_refresh = self._refresh_subscription_billing_snapshots_in_session(
            repository=repository,
            subscription=subscription,
            covered_sites=covered_sites,
            period_start_at=period_start_at,
            period_end_at=period_end_at,
        )
        latest_billing_snapshots = repository.get_latest_billing_snapshots_by_site(
            site_ids=[
                str(site.site_id or "") for site in covered_sites if str(site.site_id or "").strip()
            ]
        )
        payload: dict[str, object] = {
            "subscription": self._serialize_subscription(subscription),
            "entitlement_snapshot": self._serialize_entitlement_snapshot(snapshot),
            "topup": topup_record,
            "topup_summary": self._build_subscription_topup_summary(
                subscription, repository=repository
            ),
            "billing_snapshot_refresh": billing_snapshot_refresh,
            "billing_snapshot_status": self._build_subscription_billing_snapshot_status(
                subscription=subscription,
                sites=covered_sites,
                latest_billing_snapshots=latest_billing_snapshots,
                period_start_at=period_start_at,
                period_end_at=period_end_at,
            ),
        }
        self._record_service_audit_in_session(
            repository=repository,
            audit_context=audit_context,
            event_kind="subscription.topup",
            outcome="succeeded",
            account_id=subscription.account_id,
            subscription_id=subscription.subscription_id,
            plan_id=subscription.plan_id,
            plan_version_id=subscription.plan_version_id,
            scope_kind="subscription",
            scope_id=subscription.subscription_id,
            payload_json=payload,
        )
        return payload

    def _bind_subscription_in_session(
        self,
        *,
        repository: CommercialRepository,
        subscription_id: str,
        account_id: str,
        plan_id: str,
        plan_version_id: str,
        status: str,
        current_period_start_at: datetime,
        current_period_end_at: datetime,
        metadata_json: dict[str, object] | None,
    ) -> tuple[AccountSubscription, AccountEntitlementSnapshot]:
        subscription = repository.upsert_account_subscription(
            subscription_id=subscription_id,
            account_id=account_id,
            plan_id=plan_id,
            plan_version_id=plan_version_id,
            status=status,
            current_period_start_at=current_period_start_at,
            current_period_end_at=current_period_end_at,
            started_at=current_period_start_at,
            canceled_at=None,
            suspended_at=None,
            metadata_json=metadata_json,
        )
        plan_version = repository.get_plan_version(plan_version_id)
        if plan_version is None:
            raise CommercialNotFoundError(
                "service.plan_version_not_found",
                f"plan version '{plan_version_id}' was not found",
            )
        repository.supersede_entitlement_snapshots(account_id)
        snapshot_site_limit = cast(Any, self)._resolve_site_limit(
            plan_version=plan_version,
            subscription=subscription,
        )
        snapshot = repository.create_entitlement_snapshot(
            account_id=account_id,
            subscription_id=subscription.subscription_id,
            plan_version_id=plan_version.plan_version_id,
            entitlements_json=self._normalize_entitlements(plan_version.entitlements_json),
            budgets_json=self._normalize_budgets(plan_version.budgets_json),
            concurrency_json=self._normalize_concurrency(plan_version.concurrency_json),
            policy_json=self._normalize_commercial_policy(plan_version.policy_json),
            site_limit=snapshot_site_limit,
            metadata_json={"source": "subscription_bind"},
        )
        return subscription, snapshot

    def _normalize_entitlements(
        self,
        raw: dict[str, object] | None,
    ) -> dict[str, object]:
        raw = raw if isinstance(raw, dict) else {}
        return {
            "ability_families": self._normalize_list(raw.get("ability_families"), default=["*"]),
            "channels": self._normalize_list(raw.get("channels"), default=["*"]),
            "execution_kinds": self._normalize_list(raw.get("execution_kinds"), default=["*"]),
            "execution_tiers": self._normalize_list(raw.get("execution_tiers"), default=["cloud"]),
            "data_classifications": self._normalize_list(
                raw.get("data_classifications"),
                default=["*"],
            ),
        }

    def _normalize_budgets(self, raw: dict[str, object] | None) -> dict[str, object]:
        raw = raw if isinstance(raw, dict) else {}
        return {
            "max_ai_credits_per_period": self._coerce_float(raw.get("max_ai_credits_per_period")),
            "max_runs_per_period": self._coerce_float(raw.get("max_runs_per_period")),
            "max_tokens_per_period": self._coerce_float(raw.get("max_tokens_per_period")),
            "max_cost_per_period": self._coerce_float(raw.get("max_cost_per_period")),
        }

    def _normalize_concurrency(self, raw: dict[str, object] | None) -> dict[str, object]:
        raw = raw if isinstance(raw, dict) else {}
        return {
            "max_active_runs": self._coerce_int(raw.get("max_active_runs")),
        }

    def _normalize_plan_currency(self, currency: object) -> str:
        normalized = str(currency or "").strip().upper() or "CNY"
        if normalized != "CNY":
            raise CommercialValidationError(
                "service.plan_currency_unsupported",
                "package pricing currency must be CNY",
            )
        return normalized

    def _normalize_runtime_policy_overrides(
        self,
        raw: object,
    ) -> dict[str, object]:
        raw = raw if isinstance(raw, dict) else {}
        overrides: dict[str, object] = {}
        if "allow_fallback" in raw:
            overrides["allow_fallback"] = self._coerce_bool(raw.get("allow_fallback"))
        retry_max = self._coerce_int(raw.get("retry_max"))
        if retry_max > 0 or raw.get("retry_max") == 0:
            overrides["retry_max"] = max(0, retry_max)
            overrides["max_retries"] = max(0, retry_max)
        task_backend_raw = raw.get("task_backend")
        if isinstance(task_backend_raw, dict):
            task_backend: dict[str, object] = {}
            if "enabled" in task_backend_raw:
                task_backend["enabled"] = self._coerce_bool(task_backend_raw.get("enabled"))
            if "mode" in task_backend_raw:
                task_backend["mode"] = str(task_backend_raw.get("mode") or "")
            if "callback_mode" in task_backend_raw:
                task_backend["callback_mode"] = str(task_backend_raw.get("callback_mode") or "")
            if "polling_interval_sec" in task_backend_raw:
                task_backend["polling_interval_sec"] = max(
                    0,
                    self._coerce_int(task_backend_raw.get("polling_interval_sec")),
                )
            if task_backend:
                overrides["task_backend"] = task_backend
        return overrides

    def _normalize_budget_policy(self, raw: object) -> dict[str, object]:
        raw = raw if isinstance(raw, dict) else {}
        return {
            "grace_requests": max(0, self._coerce_int(raw.get("grace_requests"))),
            "downgrade_policy": self._normalize_runtime_policy_overrides(
                raw.get("downgrade_policy")
            ),
        }

    def _normalize_reconciliation_tolerance(self, raw: object) -> dict[str, float]:
        raw = raw if isinstance(raw, dict) else {}
        tolerance_candidate = raw.get("tolerance")
        tolerance_raw = tolerance_candidate if isinstance(tolerance_candidate, dict) else raw
        return {
            "runs": max(0.0, self._coerce_float(tolerance_raw.get("runs"))),
            "provider_calls": max(0.0, self._coerce_float(tolerance_raw.get("provider_calls"))),
            "tokens_total": max(0.0, self._coerce_float(tolerance_raw.get("tokens_total"))),
            "cost": max(0.0, self._coerce_float(tolerance_raw.get("cost"))),
        }

    def _normalize_commercial_policy(self, raw: object) -> dict[str, object]:
        raw = raw if isinstance(raw, dict) else {}
        subscription_raw = raw.get("subscription")
        subscription_raw = subscription_raw if isinstance(subscription_raw, dict) else {}
        budgets_raw = raw.get("budgets")
        budgets_raw = budgets_raw if isinstance(budgets_raw, dict) else {}
        reconciliation_raw = raw.get("reconciliation")
        reconciliation_raw = reconciliation_raw if isinstance(reconciliation_raw, dict) else {}
        return {
            "subscription": {
                "grace_period_days": max(
                    0,
                    self._coerce_int(subscription_raw.get("grace_period_days")),
                ),
                "downgrade_policy": self._normalize_runtime_policy_overrides(
                    subscription_raw.get("downgrade_policy")
                ),
            },
            "budgets": {
                "ai_credits": self._normalize_budget_policy(budgets_raw.get("ai_credits")),
                "runs": self._normalize_budget_policy(budgets_raw.get("runs")),
                "tokens": self._normalize_budget_policy(budgets_raw.get("tokens")),
                "cost": self._normalize_budget_policy(budgets_raw.get("cost")),
            },
            "reconciliation": {
                "tolerance": self._normalize_reconciliation_tolerance(reconciliation_raw),
            },
        }

    def _normalize_list(self, raw: object, *, default: list[str]) -> list[str]:
        if not isinstance(raw, list):
            return list(default)
        values = [str(item).strip() for item in raw if str(item).strip()]
        return values or list(default)

    def _resolve_period(
        self,
        subscription: AccountSubscription | None,
        now: datetime,
    ) -> tuple[datetime, datetime]:
        if subscription is None:
            return now - timedelta(days=30), now
        start_at = self._normalize_datetime(
            subscription.current_period_start_at or subscription.started_at or now
        )
        end_at = self._normalize_datetime(
            subscription.current_period_end_at or (start_at + timedelta(days=30))
        )
        return start_at, end_at

    def _ensure_current_subscription_period_in_session(
        self,
        *,
        repository: CommercialRepository,
        subscription: AccountSubscription,
        now: datetime,
    ) -> tuple[AccountSubscription, AccountEntitlementSnapshot | None, bool]:
        start_at, end_at = self._resolve_period(subscription, now)
        if end_at >= now:
            snapshot = repository.get_active_entitlement_snapshot(
                subscription.account_id,
                subscription_id=subscription.subscription_id,
            )
            return subscription, snapshot, False

        if subscription.status == SUBSCRIPTION_STATUS_TRIALING:
            cast(Any, self)._reconcile_account_subscription_state_in_session(
                repository=repository,
                account_id=subscription.account_id,
                now=now,
            )
            fallback_subscription = repository.get_runtime_subscription(subscription.account_id)
            if fallback_subscription is None:
                return subscription, None, True
            fallback_snapshot = repository.get_active_entitlement_snapshot(
                fallback_subscription.account_id,
                subscription_id=fallback_subscription.subscription_id,
            )
            return fallback_subscription, fallback_snapshot, True

        plan_version = self._resolve_current_subscription_plan_version(repository, subscription)
        if plan_version is None:
            return subscription, None, False

        next_start = end_at if end_at > start_at else now
        next_end = next_start + timedelta(days=30)
        while next_end <= now:
            next_start = next_end
            next_end = next_start + timedelta(days=30)

        metadata_json = dict(subscription.metadata_json or {})
        metadata_json["last_period_renewed_at"] = self._serialize_datetime(now)
        metadata_json["previous_period_start_at"] = self._serialize_datetime(start_at)
        metadata_json["previous_period_end_at"] = self._serialize_datetime(end_at)
        metadata_json["current_period_topup_totals"] = {
            "ai_credits": 0.0,
            "runs": 0.0,
            "tokens": 0.0,
            "cost": 0.0,
        }

        renewed, snapshot = self._bind_subscription_in_session(
            repository=repository,
            subscription_id=subscription.subscription_id,
            account_id=subscription.account_id,
            plan_id=subscription.plan_id,
            plan_version_id=subscription.plan_version_id,
            status=subscription.status,
            current_period_start_at=next_start,
            current_period_end_at=next_end,
            metadata_json=metadata_json,
        )
        snapshot.metadata_json = {
            **(snapshot.metadata_json or {}),
            "source": "subscription_period_renewal",
            "previous_period_start_at": self._serialize_datetime(start_at),
            "previous_period_end_at": self._serialize_datetime(end_at),
        }
        return renewed, snapshot, True

    def _aggregate_meter_events(self, events: Sequence[object]) -> dict[str, float]:
        totals: dict[str, float] = defaultdict(float)
        for event in events:
            meter_key = str(getattr(event, "meter_key", "") or "")
            if not meter_key:
                continue
            totals[meter_key] += float(getattr(event, "quantity", 0.0) or 0.0)
        return {key: round(value, 6) for key, value in sorted(totals.items())}

    def _aggregate_meter_breakdown(self, events: Sequence[object]) -> dict[str, object]:
        by_family: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for event in events:
            family = str(getattr(event, "ability_family", "") or "unclassified")
            meter_key = str(getattr(event, "meter_key", "") or "")
            if not meter_key:
                continue
            by_family[family][meter_key] += float(getattr(event, "quantity", 0.0) or 0.0)
        return {
            "ability_families": {
                family: {key: round(value, 6) for key, value in sorted(values.items())}
                for family, values in sorted(by_family.items())
            }
        }

    def _build_pro_cloud_runtime_state(
        self,
        events: Sequence[object],
        *,
        batch_limits: dict[str, object],
    ) -> dict[str, object]:
        max_runs = max(
            0,
            self._coerce_int(batch_limits.get("nightly_inspection_runs_per_period")),
        )
        used_runs = 0
        for event in events:
            if str(getattr(event, "meter_key", "") or "") != "runs":
                continue
            if str(getattr(event, "ability_family", "") or "") != "automation":
                continue
            if str(getattr(event, "execution_kind", "") or "") != "nightly_site_inspection":
                continue
            used_runs += int(float(getattr(event, "quantity", 0.0) or 0.0))

        return {
            "contract_version": "pro-cloud-runtime-entitlement-v1",
            "feature_id": "nightly_site_inspection",
            "execution_pattern": "whole_run_offload",
            "meter_key": "ai_credits",
            "limit_enforced": False,
            "max_nightly_inspection_runs_per_period": max_runs,
            "used_nightly_inspection_runs": used_runs,
            "remaining_nightly_inspection_runs": 0,
            "max_batch_items": max(0, self._coerce_int(batch_limits.get("max_batch_items"))),
            "result_retention_days": max(
                0,
                self._coerce_int(batch_limits.get("nightly_inspection_retention_days")),
            ),
            "payload_modes": self._normalize_list(
                batch_limits.get("nightly_inspection_payload_modes"),
                default=["metadata_only", "excerpt"],
            ),
            "quota_exhausted": False,
        }

    def _build_billing_snapshot_id(
        self,
        site_id: str,
        subscription_id: str,
        period_start_at: datetime,
        period_end_at: datetime,
    ) -> str:
        return (
            f"bill_{site_id}_{subscription_id}_"
            f"{int(period_start_at.timestamp())}_{int(period_end_at.timestamp())}"
        )

    def _serialize_subscription(self, subscription: AccountSubscription) -> dict[str, object]:
        metadata = subscription.metadata_json or {}
        package_summary = self._build_subscription_package_summary(subscription)
        package_alias = str(package_summary.get("package_alias") or "").strip()
        return {
            "subscription_id": subscription.subscription_id,
            "account_id": subscription.account_id,
            "plan_id": subscription.plan_id,
            "plan_version_id": subscription.plan_version_id,
            "status": subscription.status,
            "tier_id": str(metadata.get("tier_id") or "").strip(),
            "plan_kind": str(metadata.get("plan_kind") or "").strip(),
            "package_kind": str(package_summary.get("package_kind") or ""),
            "package_alias": package_alias,
            "display_package_label": str(package_summary.get("display_package_label") or ""),
            "coverage_state": str(package_summary.get("coverage_state") or ""),
            "current_period_start_at": self._serialize_datetime(
                subscription.current_period_start_at
            ),
            "current_period_end_at": self._serialize_datetime(subscription.current_period_end_at),
            "started_at": self._serialize_datetime(subscription.started_at),
            "canceled_at": self._serialize_datetime(subscription.canceled_at),
            "suspended_at": self._serialize_datetime(subscription.suspended_at),
            "scheduled_plan_id": subscription.scheduled_plan_id or "",
            "scheduled_plan_version_id": subscription.scheduled_plan_version_id or "",
            "scheduled_change_at": self._serialize_datetime(subscription.scheduled_change_at),
            "metadata": metadata,
            "created_at": self._serialize_datetime(subscription.created_at),
            "updated_at": self._serialize_datetime(subscription.updated_at),
        }

    def _serialize_plan(self, plan: object) -> dict[str, object]:
        return {
            "plan_id": str(getattr(plan, "plan_id", "") or ""),
            "name": str(getattr(plan, "name", "") or ""),
            "status": str(getattr(plan, "status", "") or ""),
            "description": str(getattr(plan, "description", "") or ""),
            "metadata": getattr(plan, "metadata_json", None) or {},
            "created_at": self._serialize_datetime(getattr(plan, "created_at", None)),
            "updated_at": self._serialize_datetime(getattr(plan, "updated_at", None)),
        }

    def _serialize_plan_version(self, plan_version: object) -> dict[str, object]:
        return {
            "plan_version_id": str(getattr(plan_version, "plan_version_id", "") or ""),
            "plan_id": str(getattr(plan_version, "plan_id", "") or ""),
            "version_label": str(getattr(plan_version, "version_label", "") or ""),
            "status": str(getattr(plan_version, "status", "") or ""),
            "currency": str(getattr(plan_version, "currency", "CNY") or "CNY"),
            "entitlements": self._normalize_entitlements(
                getattr(plan_version, "entitlements_json", None)
            ),
            "budgets": self._normalize_budgets(getattr(plan_version, "budgets_json", None)),
            "concurrency": self._normalize_concurrency(
                getattr(plan_version, "concurrency_json", None)
            ),
            "policy": self._normalize_commercial_policy(getattr(plan_version, "policy_json", None)),
            "metadata": getattr(plan_version, "metadata_json", None) or {},
            "created_at": self._serialize_datetime(getattr(plan_version, "created_at", None)),
            "updated_at": self._serialize_datetime(getattr(plan_version, "updated_at", None)),
        }

    def _serialize_entitlement_snapshot(
        self,
        snapshot: AccountEntitlementSnapshot,
    ) -> dict[str, object]:
        return {
            "account_id": snapshot.account_id,
            "subscription_id": snapshot.subscription_id,
            "plan_version_id": snapshot.plan_version_id,
            "status": snapshot.status,
            "entitlements": self._normalize_entitlements(snapshot.entitlements_json),
            "budgets": self._normalize_budgets(snapshot.budgets_json),
            "concurrency": self._normalize_concurrency(snapshot.concurrency_json),
            "policy": self._normalize_commercial_policy(snapshot.policy_json),
            "site_limit": self._coerce_int(getattr(snapshot, "site_limit", 0)),
            "metadata": snapshot.metadata_json or {},
            "generated_at": self._serialize_datetime(snapshot.generated_at),
        }

    def _serialize_billing_snapshot(self, snapshot: object) -> dict[str, object]:
        return {
            "snapshot_id": str(getattr(snapshot, "snapshot_id", "") or ""),
            "account_id": str(getattr(snapshot, "account_id", "") or ""),
            "site_id": str(getattr(snapshot, "site_id", "") or ""),
            "subscription_id": str(getattr(snapshot, "subscription_id", "") or ""),
            "plan_version_id": str(getattr(snapshot, "plan_version_id", "") or ""),
            "currency": str(getattr(snapshot, "currency", "CNY") or "CNY"),
            "period_start_at": self._serialize_datetime(getattr(snapshot, "period_start_at", None)),
            "period_end_at": self._serialize_datetime(getattr(snapshot, "period_end_at", None)),
            "totals": getattr(snapshot, "totals_json", None) or {},
            "breakdown": getattr(snapshot, "breakdown_json", None) or {},
            "generated_at": self._serialize_datetime(getattr(snapshot, "generated_at", None)),
        }

    def _serialize_meter_event(self, event: object) -> dict[str, object]:
        return {
            "event_id": int(getattr(event, "id", 0) or 0),
            "site_id": str(getattr(event, "site_id", "") or ""),
            "subscription_id": str(getattr(event, "subscription_id", "") or ""),
            "run_id": str(getattr(event, "run_id", "") or ""),
            "provider_call_id": int(getattr(event, "provider_call_id", 0) or 0),
            "event_kind": str(getattr(event, "event_kind", "") or ""),
            "meter_key": str(getattr(event, "meter_key", "") or ""),
            "quantity": round(float(getattr(event, "quantity", 0.0) or 0.0), 6),
            "ability_family": str(getattr(event, "ability_family", "") or ""),
            "channel": str(getattr(event, "channel", "") or ""),
            "execution_kind": str(getattr(event, "execution_kind", "") or ""),
            "execution_tier": str(getattr(event, "execution_tier", "") or ""),
            "data_classification": str(getattr(event, "data_classification", "") or ""),
            "currency": str(getattr(event, "currency", "") or ""),
            "dedupe_key": str(getattr(event, "dedupe_key", "") or ""),
            "payload": getattr(event, "payload_json", None) or {},
            "created_at": self._serialize_datetime(getattr(event, "created_at", None)),
        }

    def _serialize_expiry_state(
        self,
        subscription: AccountSubscription | None,
    ) -> dict[str, object] | None:
        if subscription is None:
            return None
        now = self.now_factory()
        period_end_at = subscription.current_period_end_at
        days_until_end: int | None = None
        if period_end_at is not None:
            normalized_end = self._normalize_datetime(period_end_at)
            days_until_end = int((normalized_end - now).total_seconds() // 86400)
        return {
            "current_period_end_at": self._serialize_datetime(period_end_at),
            "days_until_end": days_until_end,
            "is_expired": bool(days_until_end is not None and days_until_end < 0),
        }

    def _latest_subscription_map(
        self,
        subscriptions: list[AccountSubscription],
    ) -> dict[str, AccountSubscription]:
        items: dict[str, AccountSubscription] = {}
        for subscription in subscriptions:
            current = items.get(subscription.account_id)
            if current is None:
                items[subscription.account_id] = subscription
                continue
            current_created_at = self._normalize_datetime(current.created_at)
            next_created_at = self._normalize_datetime(subscription.created_at)
            if next_created_at >= current_created_at:
                items[subscription.account_id] = subscription
        return items

    def _find_nearest_subscription_expiry(
        self,
        subscriptions: list[AccountSubscription],
    ) -> datetime | None:
        candidates = [
            self._normalize_datetime(subscription.current_period_end_at)
            for subscription in subscriptions
            if subscription.current_period_end_at is not None
        ]
        return min(candidates) if candidates else None

    def _resolve_runtime_batch_limits(
        self,
        *,
        snapshot: object | None,
        plan_version: object | None,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {}
        snapshot_metadata = getattr(snapshot, "metadata_json", None)
        if isinstance(snapshot_metadata, dict):
            metadata.update(snapshot_metadata)
        plan_metadata = getattr(plan_version, "metadata_json", None)
        if isinstance(plan_metadata, dict):
            metadata.update(plan_metadata)

        return {
            "max_batch_items": max(0, self._coerce_int(metadata.get("max_batch_items"))),
            "nightly_inspection_runs_per_period": max(
                0,
                self._coerce_int(
                    metadata.get("nightly_inspection_runs_per_period")
                    or metadata.get("max_nightly_inspection_runs_per_period")
                ),
            ),
            "nightly_inspection_retention_days": max(
                1,
                self._coerce_int(metadata.get("nightly_inspection_retention_days") or 14),
            ),
            "nightly_inspection_payload_modes": self._normalize_list(
                metadata.get("nightly_inspection_payload_modes"),
                default=["metadata_only", "excerpt"],
            ),
        }

    def _resolve_account_vector_documents_limit(
        self,
        *,
        snapshot: object | None,
        plan_version: object | None,
    ) -> int:
        metadata: dict[str, object] = {}
        plan_metadata = getattr(plan_version, "metadata_json", None)
        if isinstance(plan_metadata, dict):
            metadata.update(plan_metadata)
        snapshot_metadata = getattr(snapshot, "metadata_json", None)
        if isinstance(snapshot_metadata, dict):
            metadata.update(snapshot_metadata)
        return max(0, self._coerce_int(metadata.get("max_vector_documents")))

    def _resolve_effective_subscription_budgets(
        self,
        *,
        plan_version: PlanVersion | None,
        subscription: AccountSubscription | None,
        snapshot: AccountEntitlementSnapshot | None = None,
    ) -> dict[str, object]:
        budget_source = snapshot if snapshot is not None else plan_version
        budgets = self._normalize_budgets(getattr(budget_source, "budgets_json", None))
        metadata = getattr(subscription, "metadata_json", None)
        topup_totals = (
            metadata.get("current_period_topup_totals") if isinstance(metadata, dict) else None
        )
        topup_totals = topup_totals if isinstance(topup_totals, dict) else {}
        return {
            "max_ai_credits_per_period": round(
                self._coerce_float(budgets.get("max_ai_credits_per_period"))
                + self._coerce_float(topup_totals.get("ai_credits")),
                6,
            ),
            "max_runs_per_period": round(
                self._coerce_float(budgets.get("max_runs_per_period"))
                + self._coerce_float(topup_totals.get("runs")),
                6,
            ),
            "max_tokens_per_period": round(
                self._coerce_float(budgets.get("max_tokens_per_period"))
                + self._coerce_float(topup_totals.get("tokens")),
                6,
            ),
            "max_cost_per_period": round(
                self._coerce_float(budgets.get("max_cost_per_period"))
                + self._coerce_float(topup_totals.get("cost")),
                6,
            ),
        }

    def _resolve_current_subscription_plan_version(
        self,
        repository: CommercialRepository,
        subscription: AccountSubscription | None,
    ) -> PlanVersion | None:
        if subscription is None:
            return None
        plan_id = str(getattr(subscription, "plan_id", "") or "").strip()
        if plan_id:
            published_versions = repository.list_plan_versions(
                plan_id=plan_id,
                status=PLAN_VERSION_STATUS_PUBLISHED,
                limit=1,
            )
            if published_versions:
                return published_versions[0]
            versions = repository.list_plan_versions(plan_id=plan_id, limit=1)
            if versions:
                return versions[0]
        plan_version_id = str(getattr(subscription, "plan_version_id", "") or "").strip()
        return repository.get_plan_version(plan_version_id) if plan_version_id else None

    def _select_latest_plan_version(
        self, versions: list[dict[str, object]]
    ) -> dict[str, object] | None:
        if not versions:
            return None
        published = [
            version
            for version in versions
            if str(version.get("status") or "") == PLAN_VERSION_STATUS_PUBLISHED
        ]
        return published[0] if published else versions[0]

    def _infer_plan_tier_id(
        self,
        plan: object | dict[str, object],
        versions: list[dict[str, object]],
    ) -> str:
        if isinstance(plan, dict):
            plan_id = str(plan.get("plan_id") or "")
            name = str(plan.get("name") or "")
            metadata = plan.get("metadata") or {}
        else:
            plan_id = str(getattr(plan, "plan_id", "") or "")
            name = str(getattr(plan, "name", "") or "")
            metadata = getattr(plan, "metadata_json", None) or {}
        metadata_dict = metadata if isinstance(metadata, dict) else {}
        tier_id = str(metadata_dict.get("tier_id") or "").strip().lower()
        if tier_id in PLAN_TIER_REGISTRY:
            return tier_id
        for version in versions:
            version_metadata = version.get("metadata") or {}
            if isinstance(version_metadata, dict):
                candidate = str(version_metadata.get("tier_id") or "").strip().lower()
                if candidate in PLAN_TIER_REGISTRY:
                    return candidate
        fingerprint = f"{plan_id} {name}".lower()
        for candidate in PLAN_TIER_REGISTRY:
            if candidate in fingerprint:
                return candidate
        return DEFAULT_PLAN_TIER_ID

    def _build_plan_tier_summary(
        self,
        plan: object | dict[str, object],
        versions: list[dict[str, object]],
    ) -> dict[str, object]:
        tier_id = self._infer_plan_tier_id(plan, versions)
        baseline = PLAN_TIER_REGISTRY.get(tier_id, PLAN_TIER_REGISTRY[DEFAULT_PLAN_TIER_ID])
        return self._serialize_plan_tier_template(baseline, tier_id=tier_id)

    def _list_plan_tier_templates(self) -> list[dict[str, object]]:
        return [
            self._serialize_plan_tier_template(PLAN_TIER_REGISTRY[tier_id], tier_id=tier_id)
            for tier_id in PLAN_TIER_REGISTRY
        ]

    def _serialize_plan_tier_template(
        self,
        baseline: dict[str, object],
        *,
        tier_id: str,
    ) -> dict[str, object]:
        budgets_template = self._sanitize_payload_dict(baseline.get("budgets_template")) or {}
        concurrency_template = (
            self._sanitize_payload_dict(baseline.get("concurrency_template")) or {}
        )
        policy_baseline = self._sanitize_payload_dict(baseline.get("policy_baseline")) or {}
        feature_groups = (
            baseline.get("feature_groups")
            if isinstance(baseline.get("feature_groups"), list)
            else []
        )
        return {
            "tier_id": tier_id,
            "label": str(baseline.get("label") or tier_id.title()),
            "package_alias": str(baseline.get("package_alias") or ""),
            "usage_band": str(baseline.get("usage_band") or ""),
            "positioning": str(baseline.get("positioning") or ""),
            "monthly_included_points": self._coerce_int(baseline.get("monthly_included_points")),
            "site_limit": self._coerce_int(baseline.get("site_limit")),
            "max_vector_documents": self._coerce_int(baseline.get("max_vector_documents")),
            "budgets_template": budgets_template,
            "concurrency_template": concurrency_template,
            "max_batch_items": self._coerce_int(baseline.get("max_batch_items")),
            "nightly_inspection_runs_per_period": self._coerce_int(
                baseline.get("nightly_inspection_runs_per_period")
            ),
            "nightly_inspection_retention_days": max(
                1,
                self._coerce_int(baseline.get("nightly_inspection_retention_days") or 14),
            ),
            "nightly_inspection_payload_modes": self._normalize_list(
                baseline.get("nightly_inspection_payload_modes"),
                default=["metadata_only"],
            ),
            "automation_enabled": bool(baseline.get("automation_enabled")),
            "api_enabled": bool(baseline.get("api_enabled")),
            "openclaw_enabled": bool(baseline.get("openclaw_enabled")),
            "package_operator_note": str(baseline.get("package_operator_note") or ""),
            "policy_baseline": policy_baseline,
            "canonical_shell": {
                "entitlements": self._normalize_entitlements(
                    cast(dict[str, object], DEFAULT_RUNTIME_ENTITLEMENTS)
                ),
                "budgets": budgets_template,
                "concurrency": concurrency_template,
                "policy": self._normalize_commercial_policy({"subscription": policy_baseline}),
                "metadata": {
                    "tier_id": tier_id,
                    "package_alias": str(baseline.get("package_alias") or ""),
                    "monthly_included_points": self._coerce_int(
                        baseline.get("monthly_included_points")
                    ),
                    "site_limit": self._coerce_int(baseline.get("site_limit")),
                    "max_vector_documents": self._coerce_int(baseline.get("max_vector_documents")),
                    "max_batch_items": self._coerce_int(baseline.get("max_batch_items")),
                    "nightly_inspection_runs_per_period": self._coerce_int(
                        baseline.get("nightly_inspection_runs_per_period")
                    ),
                    "nightly_inspection_retention_days": max(
                        1,
                        self._coerce_int(baseline.get("nightly_inspection_retention_days") or 14),
                    ),
                    "nightly_inspection_payload_modes": self._normalize_list(
                        baseline.get("nightly_inspection_payload_modes"),
                        default=["metadata_only"],
                    ),
                    "automation_enabled": bool(baseline.get("automation_enabled")),
                    "api_enabled": bool(baseline.get("api_enabled")),
                    "openclaw_enabled": bool(baseline.get("openclaw_enabled")),
                },
            },
            "feature_groups": feature_groups,
        }

    def _build_plan_package_fit_cues(
        self,
        *,
        tier_summary: dict[str, object],
        latest_version: dict[str, object] | None,
    ) -> list[dict[str, object]]:
        cues: list[dict[str, object]] = []
        if latest_version is None:
            return [
                {
                    "code": "package_fit.no_published_version",
                    "severity": "warning",
                    "title": "No published version yet",
                    "detail": "Freeze one published plan version before using this tier as an operator package template.",
                }
            ]

        tier_budgets = self._sanitize_payload_dict(tier_summary.get("budgets_template")) or {}
        latest_budgets = self._sanitize_payload_dict(latest_version.get("budgets")) or {}
        tier_concurrency = (
            self._sanitize_payload_dict(tier_summary.get("concurrency_template")) or {}
        )
        latest_concurrency = self._sanitize_payload_dict(latest_version.get("concurrency")) or {}

        max_cost = self._coerce_float(latest_budgets.get("max_cost_per_period"))
        if max_cost <= 0:
            cues.append(
                {
                    "code": "package_fit.cost_ceiling_missing",
                    "severity": "warning",
                    "title": "Cost ceiling is not frozen",
                    "detail": "This plan version still lacks `max_cost_per_period`, so operator package review remains too manual.",
                }
            )

        for key, label in (
            ("max_runs_per_period", "runs"),
            ("max_tokens_per_period", "tokens"),
            ("max_cost_per_period", "cost"),
        ):
            template_value = self._coerce_float(tier_budgets.get(key))
            current_value = self._coerce_float(latest_budgets.get(key))
            if template_value <= 0 or current_value <= 0:
                continue
            if current_value < template_value * 0.5:
                cues.append(
                    {
                        "code": f"package_fit.{key}.too_conservative",
                        "severity": "warning",
                        "title": f"{label.title()} budget is tighter than the tier baseline",
                        "detail": f"The latest version freezes {label} well below the {tier_summary.get('label')} template. Confirm that the plan should remain this conservative.",
                    }
                )
            elif current_value > template_value * 2.0:
                cues.append(
                    {
                        "code": f"package_fit.{key}.too_wide",
                        "severity": "warning",
                        "title": f"{label.title()} budget is wider than the tier baseline",
                        "detail": f"The latest version stretches {label} materially beyond the {tier_summary.get('label')} template. Consider whether this belongs in a higher tier.",
                    }
                )

        template_parallel = self._coerce_int(tier_concurrency.get("max_active_runs"))
        current_parallel = self._coerce_int(latest_concurrency.get("max_active_runs"))
        if template_parallel > 0 and current_parallel > template_parallel * 2:
            cues.append(
                {
                    "code": "package_fit.concurrency_too_wide",
                    "severity": "warning",
                    "title": "Concurrency is wider than the tier baseline",
                    "detail": f"The latest version allows materially more active runs than the {tier_summary.get('label')} template.",
                }
            )

        shadow_summary = cast(Any, self).get_commercial_shadow_pricing_summary(
            window_days=30,
            limit=3,
        )
        top_family = (
            shadow_summary.get("top_families", [])[0]
            if isinstance(shadow_summary.get("top_families"), list)
            and shadow_summary.get("top_families")
            else None
        )
        if isinstance(top_family, dict):
            observed_cost = self._coerce_float(top_family.get("provider_cost"))
            observed_tokens = self._coerce_float(top_family.get("tokens_total"))
            observed_runs = self._coerce_int(top_family.get("runs"))
            top_family_name = str(top_family.get("ability_family") or "unknown")
            if max_cost > 0 and observed_cost > max_cost:
                cues.append(
                    {
                        "code": "package_fit.shadow_cost_over_budget",
                        "severity": "warning",
                        "title": "Recent high-cost family already exceeds this template",
                        "detail": f"The top 30-day family `{top_family_name}` consumed more provider cost than this package ceiling. Treat this tier as too narrow for recent usage.",
                    }
                )
            elif max_cost > 0 and observed_cost < max_cost * 0.15:
                cues.append(
                    {
                        "code": "package_fit.shadow_cost_headroom_high",
                        "severity": "info",
                        "title": "Recent high-cost family still sits far below the ceiling",
                        "detail": f"The top 30-day family `{top_family_name}` remains well under this template cost ceiling, so this tier may be wider than current observed usage.",
                    }
                )
            max_tokens = self._coerce_float(latest_budgets.get("max_tokens_per_period"))
            if max_tokens > 0 and observed_tokens > max_tokens:
                cues.append(
                    {
                        "code": "package_fit.shadow_tokens_over_budget",
                        "severity": "warning",
                        "title": "Recent token load exceeds the template",
                        "detail": f"The top 30-day family `{top_family_name}` already exceeds the frozen token ceiling for this package.",
                    }
                )
            max_runs = self._coerce_float(latest_budgets.get("max_runs_per_period"))
            if max_runs > 0 and float(observed_runs) > max_runs:
                cues.append(
                    {
                        "code": "package_fit.shadow_runs_over_budget",
                        "severity": "warning",
                        "title": "Recent run volume exceeds the template",
                        "detail": f"The top 30-day family `{top_family_name}` already runs above the frozen run ceiling for this package.",
                    }
                )

        if not cues:
            cues.append(
                {
                    "code": "package_fit.within_band",
                    "severity": "ok",
                    "title": "Template still reads as internally consistent",
                    "detail": "Tier baseline, latest version budgets, and recent shadow pricing do not currently show an obvious mismatch.",
                }
            )
        return cues

    def _resolve_subscription_policy_action(
        self,
        *,
        subscription: AccountSubscription,
        policy: dict[str, object],
        period_end_at: datetime,
        now: datetime,
        reason: str,
    ) -> dict[str, object] | None:
        subscription_policy = policy.get("subscription")
        subscription_policy = subscription_policy if isinstance(subscription_policy, dict) else {}
        grace_period_days = max(
            0,
            self._coerce_int(subscription_policy.get("grace_period_days")),
        )
        if grace_period_days <= 0:
            return None
        grace_until_at = period_end_at + timedelta(days=grace_period_days)
        if now > grace_until_at:
            return None
        return {
            "kind": "subscription_grace",
            "decision_code": "commercial.subscription_grace",
            "reason": reason,
            "subscription_status": subscription.status,
            "grace_period_days": grace_period_days,
            "grace_until_at": self._serialize_datetime(grace_until_at),
            "runtime_policy_overrides": self._normalize_runtime_policy_overrides(
                subscription_policy.get("downgrade_policy")
            ),
        }

    def _load_operator_managed_points_pack_overlays(
        self,
        repository: CommercialRepository,
    ) -> dict[str, dict[str, object]]:
        return {}

    def _resolve_operator_managed_points_pack(
        self,
        pack_id: str | None,
        *,
        repository: CommercialRepository | None = None,
    ) -> dict[str, object] | None:
        normalized_pack_id = str(pack_id or "").strip()
        if not normalized_pack_id:
            return None
        pack = next(
            (
                item
                for item in self.list_operator_managed_points_packs(repository=repository)
                if str(item.get("pack_id") or "") == normalized_pack_id
            ),
            None,
        )
        if pack is None:
            return None
        return dict(pack)

    def _build_subscription_coverage_summary(
        self,
        subscription: AccountSubscription | None,
        *,
        site_count: int | None = None,
        site_limit: int | None = None,
    ) -> dict[str, object]:
        package_summary = self._build_subscription_package_summary(
            subscription,
            site_count=site_count,
        )
        if subscription is None:
            return {
                "covered_by_subscription_id": "",
                "subscription_status": "missing",
                "plan_id": "",
                "plan_version_id": "",
                "current_period_end_at": None,
                "site_count": int(site_count or 0),
                "site_limit": int(site_limit or 0),
                **package_summary,
            }
        return {
            "covered_by_subscription_id": subscription.subscription_id,
            "subscription_status": subscription.status,
            "plan_id": subscription.plan_id,
            "plan_version_id": subscription.plan_version_id,
            "current_period_end_at": self._serialize_datetime(subscription.current_period_end_at),
            "site_count": int(site_count or 0),
            "site_limit": int(site_limit or 0),
            **package_summary,
        }

    def _select_primary_subscription(
        self,
        subscriptions: list[AccountSubscription],
    ) -> AccountSubscription | None:
        if not subscriptions:
            return None
        covered = [item for item in subscriptions if _subscription_counts_as_covered(item)]
        candidates = covered if covered else subscriptions
        return candidates[0]

    def _resolve_subscription_package_kind(
        self,
        subscription: AccountSubscription | None,
        *,
        site_count: int | None = None,
    ) -> str:
        if subscription is None:
            return "uncovered" if int(site_count or 0) > 0 else "unknown"
        plan_id = str(getattr(subscription, "plan_id", "") or "").strip()
        metadata = getattr(subscription, "metadata_json", None) or {}
        plan_kind = str(metadata.get("plan_kind") or "").strip()
        if plan_id == DEFAULT_FREE_PLAN_ID or plan_kind == DEFAULT_FREE_PLAN_KIND:
            return "formal_free"
        if plan_id:
            return "tier_package"
        return "unknown"

    def _resolve_subscription_display_package_label(
        self,
        subscription: AccountSubscription | None,
        *,
        site_count: int | None = None,
    ) -> str:
        package_kind = self._resolve_subscription_package_kind(subscription, site_count=site_count)
        if package_kind == "uncovered":
            return "Uncovered"
        if package_kind == "unknown":
            return "Unknown"
        if subscription is None:
            return "Unknown"
        metadata = getattr(subscription, "metadata_json", None) or {}
        package_alias = str(metadata.get("package_alias") or "").strip()
        if package_alias:
            return package_alias
        plan_id = str(getattr(subscription, "plan_id", "") or "").strip()
        if package_kind == "formal_free":
            return "Free"
        tier_package_alias = str(
            self._build_plan_tier_summary(
                {"plan_id": plan_id, "metadata": metadata},
                [],
            ).get("package_alias")
            or ""
        ).strip()
        if tier_package_alias:
            return tier_package_alias
        return plan_id or "Unknown"

    def _build_subscription_package_summary(
        self,
        subscription: AccountSubscription | None,
        *,
        site_count: int | None = None,
    ) -> dict[str, object]:
        package_kind = self._resolve_subscription_package_kind(subscription, site_count=site_count)
        coverage_state = "covered" if _subscription_counts_as_covered(subscription) else "uncovered"
        package_alias = ""
        plan_id = ""
        plan_version_id = ""
        if subscription is not None:
            package_alias = str(
                (getattr(subscription, "metadata_json", None) or {}).get("package_alias") or ""
            ).strip()
            plan_id = str(getattr(subscription, "plan_id", "") or "").strip()
            plan_version_id = str(getattr(subscription, "plan_version_id", "") or "").strip()
        return {
            "display_package_label": self._resolve_subscription_display_package_label(
                subscription,
                site_count=site_count,
            ),
            "package_kind": package_kind,
            "coverage_state": coverage_state,
            "package_alias": package_alias,
            "plan_id": plan_id,
            "plan_version_id": plan_version_id,
        }

    def _build_subscription_topup_summary(
        self,
        subscription: AccountSubscription | None,
        *,
        repository: CommercialRepository | None = None,
    ) -> dict[str, object] | None:
        if subscription is None:
            return None
        metadata = subscription.metadata_json or {}
        raw_topups = metadata.get("operator_managed_topups")
        topups = (
            [item for item in raw_topups if isinstance(item, dict)]
            if isinstance(raw_topups, list)
            else []
        )
        latest = topups[-1] if topups else None
        current_period_start = self._serialize_datetime(subscription.current_period_start_at)
        current_period_end = self._serialize_datetime(subscription.current_period_end_at)
        current_period_topups = [
            item
            for item in topups
            if str(item.get("target_period_start_at") or "") == current_period_start
            and str(item.get("target_period_end_at") or "") == current_period_end
        ]
        current_period_totals = metadata.get("current_period_topup_totals")
        latest_pack_id = str((latest or {}).get("pack_id") or "").strip()
        latest_pack_template = self._resolve_operator_managed_points_pack(
            latest_pack_id,
            repository=repository,
        )
        return {
            "count": len(topups),
            "latest": latest,
            "latest_pack": (
                {
                    "pack_id": latest_pack_id,
                    "label": str(
                        (latest or {}).get("pack_label")
                        or (latest_pack_template or {}).get("label")
                        or ""
                    ),
                    "points_label": str(
                        (latest or {}).get("points_label")
                        or (latest_pack_template or {}).get("points_label")
                        or ""
                    ),
                }
                if latest
                else None
            ),
            "current_period_count": len(current_period_topups),
            "current_period_totals": current_period_totals
            if isinstance(current_period_totals, dict)
            else {},
        }

    def _build_subscription_budget_headroom(
        self,
        *,
        plan_version: object | None,
        effective_budgets: dict[str, object],
        topup_summary: dict[str, object] | None,
    ) -> dict[str, object]:
        base_budgets = self._normalize_budgets(
            getattr(plan_version, "budgets_json", None) if plan_version is not None else None
        )
        effective = self._normalize_budgets(effective_budgets)
        topup_totals = (
            self._sanitize_payload_dict(
                topup_summary.get("current_period_totals")
                if isinstance(topup_summary, dict)
                else None
            )
            or {}
        )
        current_period_delta = {
            "ai_credits": round(self._coerce_float(topup_totals.get("ai_credits")), 6),
            "runs": round(self._coerce_float(topup_totals.get("runs")), 6),
            "tokens": round(self._coerce_float(topup_totals.get("tokens")), 6),
            "cost": round(self._coerce_float(topup_totals.get("cost")), 6),
        }
        return {
            "base_budget": {
                "ai_credits": round(
                    self._coerce_float(base_budgets.get("max_ai_credits_per_period")),
                    6,
                ),
                "runs": round(self._coerce_float(base_budgets.get("max_runs_per_period")), 6),
                "tokens": round(self._coerce_float(base_budgets.get("max_tokens_per_period")), 6),
                "cost": round(self._coerce_float(base_budgets.get("max_cost_per_period")), 6),
            },
            "current_period_topup_delta": current_period_delta,
            "effective_budget": {
                "ai_credits": round(
                    self._coerce_float(effective.get("max_ai_credits_per_period")),
                    6,
                ),
                "runs": round(self._coerce_float(effective.get("max_runs_per_period")), 6),
                "tokens": round(self._coerce_float(effective.get("max_tokens_per_period")), 6),
                "cost": round(self._coerce_float(effective.get("max_cost_per_period")), 6),
            },
        }

    def _build_billing_mismatch(
        self,
        *,
        ledger_totals: dict[str, float],
        snapshot_totals: dict[str, object],
        tolerance: dict[str, float],
        snapshot_present: bool,
    ) -> dict[str, object]:
        comparable_keys = ("runs", "provider_calls", "tokens_total", "cost")
        deltas: dict[str, float] = {}
        mismatches: dict[str, dict[str, float]] = {}
        for key in comparable_keys:
            ledger_value = round(float(ledger_totals.get(key, 0.0) or 0.0), 6)
            snapshot_value = round(float(self._coerce_float(snapshot_totals.get(key))), 6)
            delta = round(abs(ledger_value - snapshot_value), 6)
            deltas[key] = delta
            allowed_delta = round(float(tolerance.get(key, 0.0) or 0.0), 6)
            if delta > allowed_delta:
                mismatches[key] = {
                    "ledger": ledger_value,
                    "snapshot": snapshot_value,
                    "delta": delta,
                    "tolerance": allowed_delta,
                }
        return {
            "snapshot_present": snapshot_present,
            "in_sync": snapshot_present and not mismatches,
            "deltas": deltas,
            "tolerance": tolerance,
            "mismatches": mismatches,
            "recommended_action": "" if snapshot_present and not mismatches else "rebuild_snapshot",
        }

    def _upsert_current_period_billing_snapshot_in_session(
        self,
        *,
        repository: CommercialRepository,
        site_id: str,
        subscription: AccountSubscription,
        period_start_at: datetime,
        period_end_at: datetime,
    ) -> BillingSnapshot:
        events = repository.list_usage_meter_events(
            site_id,
            subscription_id=subscription.subscription_id,
            period_start_at=period_start_at,
            period_end_at=period_end_at,
            limit=None,
        )
        totals = self._aggregate_meter_events(events)
        breakdown = self._aggregate_meter_breakdown(events)
        return repository.upsert_billing_snapshot(
            snapshot_id=self._build_billing_snapshot_id(
                site_id,
                subscription.subscription_id,
                period_start_at,
                period_end_at,
            ),
            account_id=subscription.account_id,
            site_id=site_id,
            subscription_id=subscription.subscription_id,
            plan_version_id=subscription.plan_version_id,
            currency="CNY",
            period_start_at=period_start_at,
            period_end_at=period_end_at,
            totals_json=cast(dict[str, object], totals),
            breakdown_json=breakdown,
        )

    def _build_subscription_billing_snapshot_status(
        self,
        *,
        subscription: AccountSubscription,
        sites: list[Site],
        latest_billing_snapshots: dict[str, BillingSnapshot],
        period_start_at: datetime,
        period_end_at: datetime,
    ) -> dict[str, object]:
        raw_subscription_updated_at = getattr(subscription, "updated_at", None)
        subscription_updated_at = (
            self._normalize_datetime(raw_subscription_updated_at)
            if raw_subscription_updated_at is not None
            else None
        )
        items: list[dict[str, object]] = []
        fresh_site_count = 0
        stale_site_count = 0
        missing_site_count = 0

        for site in sites:
            site_id = str(site.site_id or "").strip()
            if not site_id:
                continue
            snapshot = latest_billing_snapshots.get(site_id)
            raw_snapshot_generated_at = getattr(snapshot, "generated_at", None)
            snapshot_generated_at = (
                self._normalize_datetime(raw_snapshot_generated_at)
                if raw_snapshot_generated_at is not None
                else None
            )
            raw_snapshot_period_start_at = getattr(snapshot, "period_start_at", None)
            raw_snapshot_period_end_at = getattr(snapshot, "period_end_at", None)
            snapshot_matches_period = (
                snapshot is not None
                and str(getattr(snapshot, "subscription_id", "") or "")
                == subscription.subscription_id
                and raw_snapshot_period_start_at is not None
                and raw_snapshot_period_end_at is not None
                and self._normalize_datetime(raw_snapshot_period_start_at) == period_start_at
                and self._normalize_datetime(raw_snapshot_period_end_at) == period_end_at
            )
            is_fresh = bool(
                snapshot_matches_period
                and snapshot_generated_at is not None
                and subscription_updated_at is not None
                and snapshot_generated_at >= subscription_updated_at
            )
            if snapshot is None:
                status = "missing"
                missing_site_count += 1
            elif is_fresh:
                status = "fresh"
                fresh_site_count += 1
            else:
                status = "stale"
                stale_site_count += 1
            items.append(
                {
                    "site_id": site_id,
                    "status": status,
                    "snapshot": self._serialize_billing_snapshot(snapshot)
                    if snapshot is not None
                    else None,
                }
            )

        if stale_site_count > 0:
            aggregate_status = "stale"
            summary = "Current-period billing snapshots need rebuild to match the latest subscription posture."
        elif missing_site_count > 0:
            aggregate_status = "missing"
            summary = (
                "Current-period billing snapshots are still missing for at least one covered site."
            )
        else:
            aggregate_status = "fresh"
            summary = "Current-period billing snapshots are fresh for every covered site."

        next_action: dict[str, object] | None = None
        if aggregate_status in {"stale", "missing"} and items:
            next_action = {
                "action": "rebuild_current_period_billing_snapshots",
                "label": "Rebuild current-period billing snapshots",
                "detail": "Refresh current-period billing snapshots for every covered site before treating billing posture as reconciled.",
            }

        return {
            "status": aggregate_status,
            "summary": summary,
            "site_count": len(items),
            "fresh_site_count": fresh_site_count,
            "stale_site_count": stale_site_count,
            "missing_site_count": missing_site_count,
            "next_action": next_action,
            "items": items,
        }

    def _refresh_subscription_billing_snapshots_in_session(
        self,
        *,
        repository: CommercialRepository,
        subscription: AccountSubscription,
        covered_sites: list[Site],
        period_start_at: datetime,
        period_end_at: datetime,
    ) -> dict[str, object]:
        refreshed_billing_snapshots = [
            self._serialize_billing_snapshot(
                self._upsert_current_period_billing_snapshot_in_session(
                    repository=repository,
                    site_id=str(site.site_id or ""),
                    subscription=subscription,
                    period_start_at=period_start_at,
                    period_end_at=period_end_at,
                )
            )
            for site in covered_sites
            if str(site.site_id or "").strip()
        ]
        if refreshed_billing_snapshots:
            status = "refreshed"
            summary = "Current-period billing snapshots were rebuilt for every covered site."
        else:
            status = "no_covered_sites"
            summary = "No covered sites are currently attached to this subscription, so there were no billing snapshots to rebuild."
        return {
            "status": status,
            "summary": summary,
            "site_count": len(refreshed_billing_snapshots),
            "snapshots": refreshed_billing_snapshots,
        }
