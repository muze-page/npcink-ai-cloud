"""canonicalize package plan slugs

Revision ID: 20260703_0051
Revises: 20260629_0050
Create Date: 2026-07-03 00:00:00.000000
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "20260703_0051"
down_revision = "20260629_0050"
branch_labels = None
depends_on = None

OLD_FREE_PLAN_ID = "plan_free"
OLD_FREE_PLAN_VERSION_ID = "plan_free_v1"
NEW_FREE_PLAN_ID = "free"
NEW_FREE_PLAN_VERSION_ID = "free_v1"


def _merge_metadata(metadata: Any, **updates: object) -> dict[str, object]:
    result = dict(metadata or {}) if isinstance(metadata, dict) else {}
    result.update(updates)
    return result


def _update_value(
    bind: sa.Connection,
    table: sa.Table,
    column: sa.Column[str],
    old_value: str,
    new_value: str,
) -> None:
    bind.execute(sa.update(table).where(column == old_value).values({column.name: new_value}))


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
        sa.Column("plan_id", sa.String(length=191)),
        sa.Column("plan_version_id", sa.String(length=191)),
    )
    account_entitlement_snapshots = sa.Table(
        "account_entitlement_snapshots",
        metadata,
        sa.Column("plan_version_id", sa.String(length=191)),
    )
    payment_orders = sa.Table(
        "payment_orders",
        metadata,
        sa.Column("plan_id", sa.String(length=191)),
        sa.Column("plan_version_id", sa.String(length=191)),
    )
    run_records = sa.Table(
        "run_records",
        metadata,
        sa.Column("plan_version_id", sa.String(length=191)),
    )
    usage_meter_events = sa.Table(
        "usage_meter_events",
        metadata,
        sa.Column("plan_version_id", sa.String(length=191)),
    )
    credit_ledger_entries = sa.Table(
        "credit_ledger_entries",
        metadata,
        sa.Column("plan_version_id", sa.String(length=191)),
    )
    billing_snapshots = sa.Table(
        "billing_snapshots",
        metadata,
        sa.Column("plan_version_id", sa.String(length=191)),
    )
    service_audit_events = sa.Table(
        "service_audit_events",
        metadata,
        sa.Column("plan_id", sa.String(length=191)),
        sa.Column("plan_version_id", sa.String(length=191)),
    )
    commercial_decision_events = sa.Table(
        "commercial_decision_events",
        metadata,
        sa.Column("plan_version_id", sa.String(length=191)),
    )

    new_plan = (
        bind.execute(
            sa.select(plans.c.plan_id, plans.c.metadata_json).where(
                plans.c.plan_id == NEW_FREE_PLAN_ID
            )
        )
        .mappings()
        .first()
    )
    old_plan = (
        bind.execute(
            sa.select(plans.c.plan_id, plans.c.metadata_json).where(
                plans.c.plan_id == OLD_FREE_PLAN_ID
            )
        )
        .mappings()
        .first()
    )
    plan_metadata = {
        "tier_id": "free",
        "package_alias": "Free",
        "plan_kind": "default_free",
        "source": "canonical_plan_slug_migration_v1",
    }
    if new_plan is None:
        bind.execute(
            sa.insert(plans).values(
                plan_id=NEW_FREE_PLAN_ID,
                name="Free",
                status="active",
                description=(
                    "Baseline package for conservative hosted runs, lighter workflow usage, "
                    "and operator-managed growth."
                ),
                metadata_json=_merge_metadata(
                    old_plan["metadata_json"] if old_plan else None,
                    **plan_metadata,
                ),
            )
        )
    else:
        bind.execute(
            sa.update(plans)
            .where(plans.c.plan_id == NEW_FREE_PLAN_ID)
            .values(
                name="Free",
                status="active",
                metadata_json=_merge_metadata(new_plan["metadata_json"], **plan_metadata),
            )
        )

    new_version = (
        bind.execute(
            sa.select(plan_versions.c.plan_version_id).where(
                plan_versions.c.plan_version_id == NEW_FREE_PLAN_VERSION_ID
            )
        )
        .mappings()
        .first()
    )
    old_version = (
        bind.execute(
            sa.select(plan_versions.c.plan_version_id, plan_versions.c.metadata_json).where(
                plan_versions.c.plan_version_id == OLD_FREE_PLAN_VERSION_ID
            )
        )
        .mappings()
        .first()
    )
    version_metadata = {
        **plan_metadata,
        "site_limit": 1,
        "monthly_included_points": 500,
        "max_batch_items": 0,
    }
    if old_version is not None and new_version is None:
        bind.execute(
            sa.update(plan_versions)
            .where(plan_versions.c.plan_version_id == OLD_FREE_PLAN_VERSION_ID)
            .values(
                plan_version_id=NEW_FREE_PLAN_VERSION_ID,
                plan_id=NEW_FREE_PLAN_ID,
                version_label="v1",
                status="published",
                metadata_json=_merge_metadata(old_version["metadata_json"], **version_metadata),
            )
        )
    elif new_version is None:
        bind.execute(
            sa.insert(plan_versions).values(
                plan_version_id=NEW_FREE_PLAN_VERSION_ID,
                plan_id=NEW_FREE_PLAN_ID,
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
        )
    else:
        bind.execute(
            sa.update(plan_versions)
            .where(plan_versions.c.plan_version_id == NEW_FREE_PLAN_VERSION_ID)
            .values(plan_id=NEW_FREE_PLAN_ID, version_label="v1", status="published")
        )

    for table in (
        account_subscriptions,
        payment_orders,
        service_audit_events,
    ):
        _update_value(bind, table, table.c.plan_id, OLD_FREE_PLAN_ID, NEW_FREE_PLAN_ID)

    for table in (
        account_subscriptions,
        account_entitlement_snapshots,
        payment_orders,
        run_records,
        usage_meter_events,
        credit_ledger_entries,
        billing_snapshots,
        service_audit_events,
        commercial_decision_events,
    ):
        _update_value(
            bind,
            table,
            table.c.plan_version_id,
            OLD_FREE_PLAN_VERSION_ID,
            NEW_FREE_PLAN_VERSION_ID,
        )

    bind.execute(
        sa.delete(plan_versions).where(
            plan_versions.c.plan_version_id == OLD_FREE_PLAN_VERSION_ID
        )
    )
    leftover_versions = bind.execute(
        sa.select(sa.func.count()).select_from(plan_versions).where(
            plan_versions.c.plan_id == OLD_FREE_PLAN_ID
        )
    ).scalar_one()
    if int(leftover_versions or 0) == 0:
        bind.execute(sa.delete(plans).where(plans.c.plan_id == OLD_FREE_PLAN_ID))


def downgrade() -> None:
    # Data canonicalization is intentionally one-way.
    return None
