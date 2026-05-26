"""commercial core schema and entitlement gate runtime fields"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260321_0006"
down_revision = "20260320_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical migration snapshot: the original schema introduced legacy
    # multi-role defaults here. Current head collapses product identity to
    # `user_admin` / `platform_admin` via later migrations, so do not treat
    # these literals as the current role contract.
    op.create_table(
        "accounts",
        sa.Column("account_id", sa.String(length=191), primary_key=True),
        sa.Column("name", sa.String(length=191), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
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
    op.create_index("ix_accounts_status", "accounts", ["status"])

    op.create_table(
        "account_memberships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.String(length=191),
            sa.ForeignKey("accounts.account_id"),
            nullable=False,
        ),
        sa.Column("member_ref", sa.String(length=191), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="viewer"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
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
        sa.UniqueConstraint(
            "account_id",
            "member_ref",
            name="uq_account_memberships_account_member",
        ),
    )
    op.create_index("ix_account_memberships_account_id", "account_memberships", ["account_id"])
    op.create_index("ix_account_memberships_role", "account_memberships", ["role"])
    op.create_index("ix_account_memberships_status", "account_memberships", ["status"])

    op.create_table(
        "plans",
        sa.Column("plan_id", sa.String(length=191), primary_key=True),
        sa.Column("name", sa.String(length=191), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("description", sa.Text(), nullable=True),
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
    op.create_index("ix_plans_status", "plans", ["status"])

    op.create_table(
        "plan_versions",
        sa.Column("plan_version_id", sa.String(length=191), primary_key=True),
        sa.Column(
            "plan_id",
            sa.String(length=191),
            sa.ForeignKey("plans.plan_id"),
            nullable=False,
        ),
        sa.Column("version_label", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="published"),
        sa.Column("currency", sa.String(length=16), nullable=False, server_default="USD"),
        sa.Column("entitlements_json", sa.JSON(), nullable=False),
        sa.Column("budgets_json", sa.JSON(), nullable=False),
        sa.Column("concurrency_json", sa.JSON(), nullable=False),
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
        sa.UniqueConstraint("plan_id", "version_label", name="uq_plan_versions_plan_label"),
    )
    op.create_index("ix_plan_versions_plan_id", "plan_versions", ["plan_id"])
    op.create_index("ix_plan_versions_status", "plan_versions", ["status"])

    op.create_table(
        "site_subscriptions",
        sa.Column("subscription_id", sa.String(length=191), primary_key=True),
        sa.Column(
            "site_id",
            sa.String(length=191),
            sa.ForeignKey("sites.site_id"),
            nullable=False,
        ),
        sa.Column("account_id", sa.String(length=191), nullable=False),
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
    op.create_index("ix_site_subscriptions_site_id", "site_subscriptions", ["site_id"])
    op.create_index("ix_site_subscriptions_account_id", "site_subscriptions", ["account_id"])
    op.create_index("ix_site_subscriptions_plan_id", "site_subscriptions", ["plan_id"])
    op.create_index(
        "ix_site_subscriptions_plan_version_id",
        "site_subscriptions",
        ["plan_version_id"],
    )
    op.create_index("ix_site_subscriptions_status", "site_subscriptions", ["status"])

    op.create_table(
        "site_entitlement_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "site_id",
            sa.String(length=191),
            sa.ForeignKey("sites.site_id"),
            nullable=False,
        ),
        sa.Column("subscription_id", sa.String(length=191), nullable=False),
        sa.Column("plan_version_id", sa.String(length=191), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("entitlements_json", sa.JSON(), nullable=False),
        sa.Column("budgets_json", sa.JSON(), nullable=False),
        sa.Column("concurrency_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_site_entitlement_snapshots_site_id",
        "site_entitlement_snapshots",
        ["site_id"],
    )
    op.create_index(
        "ix_site_entitlement_snapshots_subscription_id",
        "site_entitlement_snapshots",
        ["subscription_id"],
    )
    op.create_index(
        "ix_site_entitlement_snapshots_plan_version_id",
        "site_entitlement_snapshots",
        ["plan_version_id"],
    )
    op.create_index(
        "ix_site_entitlement_snapshots_status",
        "site_entitlement_snapshots",
        ["status"],
    )

    op.create_table(
        "usage_meter_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.String(length=191), nullable=True),
        sa.Column(
            "site_id",
            sa.String(length=191),
            sa.ForeignKey("sites.site_id"),
            nullable=False,
        ),
        sa.Column("subscription_id", sa.String(length=191), nullable=True),
        sa.Column("plan_version_id", sa.String(length=191), nullable=True),
        sa.Column("run_id", sa.String(length=191), nullable=True),
        sa.Column("provider_call_id", sa.Integer(), nullable=True),
        sa.Column("event_kind", sa.String(length=32), nullable=False),
        sa.Column("meter_key", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ability_family", sa.String(length=32), nullable=True),
        sa.Column("channel", sa.String(length=64), nullable=True),
        sa.Column("execution_kind", sa.String(length=32), nullable=True),
        sa.Column("execution_tier", sa.String(length=32), nullable=True),
        sa.Column("data_classification", sa.String(length=32), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("dedupe_key", name="uq_usage_meter_events_dedupe"),
    )
    op.create_index("ix_usage_meter_events_account_id", "usage_meter_events", ["account_id"])
    op.create_index("ix_usage_meter_events_site_id", "usage_meter_events", ["site_id"])
    op.create_index(
        "ix_usage_meter_events_subscription_id",
        "usage_meter_events",
        ["subscription_id"],
    )
    op.create_index(
        "ix_usage_meter_events_plan_version_id",
        "usage_meter_events",
        ["plan_version_id"],
    )
    op.create_index("ix_usage_meter_events_run_id", "usage_meter_events", ["run_id"])
    op.create_index(
        "ix_usage_meter_events_provider_call_id",
        "usage_meter_events",
        ["provider_call_id"],
    )
    op.create_index("ix_usage_meter_events_event_kind", "usage_meter_events", ["event_kind"])
    op.create_index("ix_usage_meter_events_meter_key", "usage_meter_events", ["meter_key"])
    op.create_index(
        "ix_usage_meter_events_ability_family",
        "usage_meter_events",
        ["ability_family"],
    )
    op.create_index("ix_usage_meter_events_channel", "usage_meter_events", ["channel"])
    op.create_index(
        "ix_usage_meter_events_execution_kind",
        "usage_meter_events",
        ["execution_kind"],
    )
    op.create_index(
        "ix_usage_meter_events_execution_tier",
        "usage_meter_events",
        ["execution_tier"],
    )
    op.create_index(
        "ix_usage_meter_events_data_classification",
        "usage_meter_events",
        ["data_classification"],
    )

    op.create_table(
        "billing_snapshots",
        sa.Column("snapshot_id", sa.String(length=191), primary_key=True),
        sa.Column("account_id", sa.String(length=191), nullable=True),
        sa.Column("site_id", sa.String(length=191), nullable=True),
        sa.Column("subscription_id", sa.String(length=191), nullable=True),
        sa.Column("plan_version_id", sa.String(length=191), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=False, server_default="USD"),
        sa.Column("period_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("totals_json", sa.JSON(), nullable=False),
        sa.Column("breakdown_json", sa.JSON(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_billing_snapshots_account_id", "billing_snapshots", ["account_id"])
    op.create_index("ix_billing_snapshots_site_id", "billing_snapshots", ["site_id"])
    op.create_index(
        "ix_billing_snapshots_subscription_id",
        "billing_snapshots",
        ["subscription_id"],
    )
    op.create_index(
        "ix_billing_snapshots_plan_version_id",
        "billing_snapshots",
        ["plan_version_id"],
    )
    op.create_index(
        "ix_billing_snapshots_period_start_at",
        "billing_snapshots",
        ["period_start_at"],
    )
    op.create_index(
        "ix_billing_snapshots_period_end_at",
        "billing_snapshots",
        ["period_end_at"],
    )

    with op.batch_alter_table("sites") as batch_op:
        batch_op.add_column(sa.Column("account_id", sa.String(length=191), nullable=True))
        batch_op.add_column(sa.Column("metadata_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("provisioned_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("suspension_reason", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )
        batch_op.create_index("ix_sites_account_id", ["account_id"])

    with op.batch_alter_table("site_api_keys") as batch_op:
        batch_op.add_column(sa.Column("label", sa.String(length=191), nullable=True))
        batch_op.add_column(sa.Column("metadata_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("rotated_from_key_id", sa.String(length=191), nullable=True))
        batch_op.add_column(sa.Column("replaced_by_key_id", sa.String(length=191), nullable=True))
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )

    with op.batch_alter_table("run_records") as batch_op:
        batch_op.add_column(sa.Column("account_id", sa.String(length=191), nullable=True))
        batch_op.add_column(sa.Column("subscription_id", sa.String(length=191), nullable=True))
        batch_op.add_column(sa.Column("plan_version_id", sa.String(length=191), nullable=True))
        batch_op.add_column(
            sa.Column(
                "ability_family",
                sa.String(length=32),
                nullable=False,
                server_default="text",
            )
        )
        batch_op.create_index("ix_run_records_account_id", ["account_id"])
        batch_op.create_index("ix_run_records_subscription_id", ["subscription_id"])
        batch_op.create_index("ix_run_records_plan_version_id", ["plan_version_id"])
        batch_op.create_index("ix_run_records_ability_family", ["ability_family"])


def downgrade() -> None:
    with op.batch_alter_table("run_records") as batch_op:
        batch_op.drop_index("ix_run_records_ability_family")
        batch_op.drop_index("ix_run_records_plan_version_id")
        batch_op.drop_index("ix_run_records_subscription_id")
        batch_op.drop_index("ix_run_records_account_id")
        batch_op.drop_column("ability_family")
        batch_op.drop_column("plan_version_id")
        batch_op.drop_column("subscription_id")
        batch_op.drop_column("account_id")

    with op.batch_alter_table("site_api_keys") as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("replaced_by_key_id")
        batch_op.drop_column("rotated_from_key_id")
        batch_op.drop_column("metadata_json")
        batch_op.drop_column("label")

    with op.batch_alter_table("sites") as batch_op:
        batch_op.drop_index("ix_sites_account_id")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("suspension_reason")
        batch_op.drop_column("suspended_at")
        batch_op.drop_column("activated_at")
        batch_op.drop_column("provisioned_at")
        batch_op.drop_column("metadata_json")
        batch_op.drop_column("account_id")

    op.drop_index("ix_billing_snapshots_period_end_at", table_name="billing_snapshots")
    op.drop_index("ix_billing_snapshots_period_start_at", table_name="billing_snapshots")
    op.drop_index("ix_billing_snapshots_plan_version_id", table_name="billing_snapshots")
    op.drop_index("ix_billing_snapshots_subscription_id", table_name="billing_snapshots")
    op.drop_index("ix_billing_snapshots_site_id", table_name="billing_snapshots")
    op.drop_index("ix_billing_snapshots_account_id", table_name="billing_snapshots")
    op.drop_table("billing_snapshots")

    op.drop_index(
        "ix_usage_meter_events_data_classification",
        table_name="usage_meter_events",
    )
    op.drop_index("ix_usage_meter_events_execution_tier", table_name="usage_meter_events")
    op.drop_index("ix_usage_meter_events_execution_kind", table_name="usage_meter_events")
    op.drop_index("ix_usage_meter_events_channel", table_name="usage_meter_events")
    op.drop_index("ix_usage_meter_events_ability_family", table_name="usage_meter_events")
    op.drop_index("ix_usage_meter_events_meter_key", table_name="usage_meter_events")
    op.drop_index("ix_usage_meter_events_event_kind", table_name="usage_meter_events")
    op.drop_index("ix_usage_meter_events_provider_call_id", table_name="usage_meter_events")
    op.drop_index("ix_usage_meter_events_run_id", table_name="usage_meter_events")
    op.drop_index("ix_usage_meter_events_plan_version_id", table_name="usage_meter_events")
    op.drop_index("ix_usage_meter_events_subscription_id", table_name="usage_meter_events")
    op.drop_index("ix_usage_meter_events_site_id", table_name="usage_meter_events")
    op.drop_index("ix_usage_meter_events_account_id", table_name="usage_meter_events")
    op.drop_table("usage_meter_events")

    op.drop_index(
        "ix_site_entitlement_snapshots_status",
        table_name="site_entitlement_snapshots",
    )
    op.drop_index(
        "ix_site_entitlement_snapshots_plan_version_id",
        table_name="site_entitlement_snapshots",
    )
    op.drop_index(
        "ix_site_entitlement_snapshots_subscription_id",
        table_name="site_entitlement_snapshots",
    )
    op.drop_index(
        "ix_site_entitlement_snapshots_site_id",
        table_name="site_entitlement_snapshots",
    )
    op.drop_table("site_entitlement_snapshots")

    op.drop_index("ix_site_subscriptions_status", table_name="site_subscriptions")
    op.drop_index("ix_site_subscriptions_plan_version_id", table_name="site_subscriptions")
    op.drop_index("ix_site_subscriptions_plan_id", table_name="site_subscriptions")
    op.drop_index("ix_site_subscriptions_account_id", table_name="site_subscriptions")
    op.drop_index("ix_site_subscriptions_site_id", table_name="site_subscriptions")
    op.drop_table("site_subscriptions")

    op.drop_index("ix_plan_versions_status", table_name="plan_versions")
    op.drop_index("ix_plan_versions_plan_id", table_name="plan_versions")
    op.drop_table("plan_versions")

    op.drop_index("ix_plans_status", table_name="plans")
    op.drop_table("plans")

    op.drop_index("ix_account_memberships_status", table_name="account_memberships")
    op.drop_index("ix_account_memberships_role", table_name="account_memberships")
    op.drop_index("ix_account_memberships_account_id", table_name="account_memberships")
    op.drop_table("account_memberships")

    op.drop_index("ix_accounts_status", table_name="accounts")
    op.drop_table("accounts")
