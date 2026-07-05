"""backfill explicit production free plan objects and bindings"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "20260413_0024"
down_revision = "20260410_0022"
branch_labels = None
depends_on = None

DEFAULT_FREE_PLAN_ID = "free"
DEFAULT_FREE_PLAN_VERSION_ID = "free_v1"
DEFAULT_FREE_PLAN_KIND = "default_free"
DEFAULT_FREE_PLAN_SOURCE = "production_default_free_shell_v1"
LEGACY_DEFAULT_FREE_SOURCES = {
    "portal_default_free",
    "portal_default_free_shell_v1",
    "production_default_free_bind_v1",
}


def _merge_metadata(metadata: Any, **updates: object) -> dict[str, object]:
    result = dict(metadata or {}) if isinstance(metadata, dict) else {}
    result.update(updates)
    return result


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()

    plans = sa.Table(
        "plans",
        metadata,
        sa.Column("plan_id", sa.String(length=191)),
        sa.Column("name", sa.String(length=191)),
        sa.Column("status", sa.String(length=32)),
        sa.Column("description", sa.Text()),
        sa.Column("metadata_json", sa.JSON()),
    )
    plan_versions = sa.Table(
        "plan_versions",
        metadata,
        sa.Column("plan_version_id", sa.String(length=191)),
        sa.Column("plan_id", sa.String(length=191)),
        sa.Column("version_label", sa.String(length=64)),
        sa.Column("status", sa.String(length=32)),
        sa.Column("currency", sa.String(length=16)),
        sa.Column("entitlements_json", sa.JSON()),
        sa.Column("budgets_json", sa.JSON()),
        sa.Column("concurrency_json", sa.JSON()),
        sa.Column("policy_json", sa.JSON()),
        sa.Column("metadata_json", sa.JSON()),
    )
    account_subscriptions = sa.Table(
        "account_subscriptions",
        metadata,
        sa.Column("subscription_id", sa.String(length=191)),
        sa.Column("account_id", sa.String(length=191)),
        sa.Column("plan_id", sa.String(length=191)),
        sa.Column("plan_version_id", sa.String(length=191)),
        sa.Column("metadata_json", sa.JSON()),
    )
    account_entitlement_snapshots = sa.Table(
        "account_entitlement_snapshots",
        metadata,
        sa.Column("id", sa.Integer()),
        sa.Column("subscription_id", sa.String(length=191)),
        sa.Column("plan_version_id", sa.String(length=191)),
        sa.Column("metadata_json", sa.JSON()),
    )

    plan_metadata = {
        "tier_id": "free",
        "package_alias": "Free",
        "plan_kind": DEFAULT_FREE_PLAN_KIND,
        "source": DEFAULT_FREE_PLAN_SOURCE,
    }
    version_metadata = {
        **plan_metadata,
        "site_limit": 1,
        "monthly_included_points": 500,
        "max_batch_items": 0,
        "automation_enabled": True,
        "api_enabled": True,
        "openclaw_enabled": True,
    }

    existing_plan = (
        bind.execute(
            sa.select(plans.c.plan_id, plans.c.metadata_json).where(
                plans.c.plan_id == DEFAULT_FREE_PLAN_ID
            )
        )
        .mappings()
        .first()
    )
    if existing_plan is None:
        bind.execute(
            sa.insert(plans).values(
                plan_id=DEFAULT_FREE_PLAN_ID,
                name="Free",
                status="active",
                description="Baseline package for conservative hosted runs, lighter workflow usage, and operator-managed growth.",
                metadata_json=plan_metadata,
            )
        )
    else:
        bind.execute(
            sa.update(plans)
            .where(plans.c.plan_id == DEFAULT_FREE_PLAN_ID)
            .values(
                name="Free",
                status="active",
                description="Baseline package for conservative hosted runs, lighter workflow usage, and operator-managed growth.",
                metadata_json=_merge_metadata(existing_plan["metadata_json"], **plan_metadata),
            )
        )

    existing_version = (
        bind.execute(
            sa.select(plan_versions.c.plan_version_id, plan_versions.c.metadata_json).where(
                plan_versions.c.plan_version_id == DEFAULT_FREE_PLAN_VERSION_ID
            )
        )
        .mappings()
        .first()
    )
    version_values = dict(
        plan_version_id=DEFAULT_FREE_PLAN_VERSION_ID,
        plan_id=DEFAULT_FREE_PLAN_ID,
        version_label="v1",
        status="published",
        currency="USD",
        entitlements_json={
            "ability_families": ["*"],
            "channels": ["*"],
            "execution_kinds": ["*"],
            "execution_tiers": ["cloud"],
            "data_classifications": ["*"],
        },
        budgets_json={
            "max_runs_per_period": 500,
            "max_tokens_per_period": 200000,
            "max_cost_per_period": 5,
        },
        concurrency_json={"max_active_runs": 1},
        policy_json={"subscription": {"grace_period_days": 0}},
        metadata_json=version_metadata,
    )
    if existing_version is None:
        bind.execute(sa.insert(plan_versions).values(**version_values))
    else:
        bind.execute(
            sa.update(plan_versions)
            .where(plan_versions.c.plan_version_id == DEFAULT_FREE_PLAN_VERSION_ID)
            .values(
                **{
                    **version_values,
                    "metadata_json": _merge_metadata(
                        existing_version["metadata_json"], **version_metadata
                    ),
                }
            )
        )

    subscription_rows = (
        bind.execute(
            sa.select(
                account_subscriptions.c.subscription_id,
                account_subscriptions.c.plan_id,
                account_subscriptions.c.plan_version_id,
                account_subscriptions.c.metadata_json,
            ).where(
                sa.or_(
                    sa.and_(
                        account_subscriptions.c.plan_id == "starter",
                        account_subscriptions.c.plan_version_id == "starter_v1",
                    ),
                    sa.and_(
                        account_subscriptions.c.plan_id == "plan_dev_unlimited",
                        account_subscriptions.c.plan_version_id == "plan_dev_unlimited_v1",
                    ),
                )
            )
        )
        .mappings()
        .all()
    )
    for row in subscription_rows:
        metadata_json = row["metadata_json"] if isinstance(row["metadata_json"], dict) else {}
        source = str(metadata_json.get("source") or "").strip()
        tier_id = str(metadata_json.get("tier_id") or "").strip().lower()
        package_alias = str(metadata_json.get("package_alias") or "").strip()
        is_legacy_dev_unlimited = (
            row["plan_id"] == "plan_dev_unlimited"
            and row["plan_version_id"] == "plan_dev_unlimited_v1"
        )
        if (
            not is_legacy_dev_unlimited
            and source not in LEGACY_DEFAULT_FREE_SOURCES
            and not (
                tier_id == "starter"
                and package_alias == "Free"
                and str(row["subscription_id"] or "").endswith("_starter")
            )
        ):
            continue
        bind.execute(
            sa.update(account_subscriptions)
            .where(account_subscriptions.c.subscription_id == row["subscription_id"])
            .values(
                plan_id=DEFAULT_FREE_PLAN_ID,
                plan_version_id=DEFAULT_FREE_PLAN_VERSION_ID,
                metadata_json=_merge_metadata(
                    metadata_json,
                    source="migration_backfill_default_free_v1",
                    tier_id="free",
                    package_alias="Free",
                    plan_kind=DEFAULT_FREE_PLAN_KIND,
                    site_limit=1,
                ),
            )
        )
        snapshot_rows = (
            bind.execute(
                sa.select(
                    account_entitlement_snapshots.c.id,
                    account_entitlement_snapshots.c.metadata_json,
                ).where(
                    account_entitlement_snapshots.c.subscription_id == row["subscription_id"],
                    account_entitlement_snapshots.c.plan_version_id.in_(
                        ["starter_v1", "plan_dev_unlimited_v1"]
                    ),
                )
            )
            .mappings()
            .all()
        )
        for snapshot_row in snapshot_rows:
            bind.execute(
                sa.update(account_entitlement_snapshots)
                .where(account_entitlement_snapshots.c.id == snapshot_row["id"])
                .values(
                    plan_version_id=DEFAULT_FREE_PLAN_VERSION_ID,
                    metadata_json=_merge_metadata(
                        snapshot_row["metadata_json"],
                        source="migration_backfill_default_free_v1",
                        tier_id="free",
                        package_alias="Free",
                        plan_kind=DEFAULT_FREE_PLAN_KIND,
                        site_limit=1,
                    ),
                )
            )


def downgrade() -> None:
    raise RuntimeError("downgrade is intentionally unsupported for explicit free-plan backfill")
