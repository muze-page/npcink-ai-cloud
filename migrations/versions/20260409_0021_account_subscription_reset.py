"""reset commercial truth to account scoped subscriptions"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260409_0021"
down_revision = "20260403_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_site_entitlement_snapshots_status", table_name="site_entitlement_snapshots")
    op.drop_index("ix_site_entitlement_snapshots_plan_version_id", table_name="site_entitlement_snapshots")
    op.drop_index("ix_site_entitlement_snapshots_subscription_id", table_name="site_entitlement_snapshots")
    op.drop_index("ix_site_entitlement_snapshots_site_id", table_name="site_entitlement_snapshots")
    op.drop_table("site_entitlement_snapshots")

    op.drop_index("ix_site_subscriptions_status", table_name="site_subscriptions")
    op.drop_index("ix_site_subscriptions_plan_version_id", table_name="site_subscriptions")
    op.drop_index("ix_site_subscriptions_plan_id", table_name="site_subscriptions")
    op.drop_index("ix_site_subscriptions_account_id", table_name="site_subscriptions")
    op.drop_index("ix_site_subscriptions_site_id", table_name="site_subscriptions")
    op.drop_table("site_subscriptions")

    op.create_table(
        "account_subscriptions",
        sa.Column("subscription_id", sa.String(length=191), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(length=191),
            sa.ForeignKey("accounts.account_id"),
            nullable=False,
        ),
        sa.Column("plan_id", sa.String(length=191), nullable=False),
        sa.Column("plan_version_id", sa.String(length=191), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("current_period_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_account_subscriptions_account_id", "account_subscriptions", ["account_id"])
    op.create_index("ix_account_subscriptions_plan_id", "account_subscriptions", ["plan_id"])
    op.create_index("ix_account_subscriptions_plan_version_id", "account_subscriptions", ["plan_version_id"])
    op.create_index("ix_account_subscriptions_status", "account_subscriptions", ["status"])
    op.create_index(
        "uq_account_subscriptions_one_active_per_account",
        "account_subscriptions",
        ["account_id"],
        unique=True,
        postgresql_where=sa.text("status in ('active','trialing')"),
        sqlite_where=sa.text("status in ('active','trialing')"),
    )

    op.create_table(
        "account_entitlement_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.String(length=191),
            sa.ForeignKey("accounts.account_id"),
            nullable=False,
        ),
        sa.Column("subscription_id", sa.String(length=191), nullable=False),
        sa.Column("plan_version_id", sa.String(length=191), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("entitlements_json", sa.JSON(), nullable=False),
        sa.Column("budgets_json", sa.JSON(), nullable=False),
        sa.Column("concurrency_json", sa.JSON(), nullable=False),
        sa.Column("policy_json", sa.JSON(), nullable=False),
        sa.Column("site_limit", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_account_entitlement_snapshots_account_id",
        "account_entitlement_snapshots",
        ["account_id"],
    )
    op.create_index(
        "ix_account_entitlement_snapshots_subscription_id",
        "account_entitlement_snapshots",
        ["subscription_id"],
    )
    op.create_index(
        "ix_account_entitlement_snapshots_plan_version_id",
        "account_entitlement_snapshots",
        ["plan_version_id"],
    )
    op.create_index(
        "ix_account_entitlement_snapshots_status",
        "account_entitlement_snapshots",
        ["status"],
    )


def downgrade() -> None:
    raise RuntimeError("downgrade is intentionally unsupported for the commercial v2 reset")
