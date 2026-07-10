"""subscription commerce offers, orders, and trial claims

Revision ID: 20260710_0058
Revises: 20260710_0057
Create Date: 2026-07-10 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260710_0058"
down_revision = "20260710_0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("account_subscriptions") as batch:
        batch.add_column(sa.Column("scheduled_plan_id", sa.String(length=191), nullable=True))
        batch.add_column(
            sa.Column("scheduled_plan_version_id", sa.String(length=191), nullable=True)
        )
        batch.add_column(
            sa.Column("scheduled_change_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_index(
            "ix_account_subscriptions_scheduled_plan_id",
            ["scheduled_plan_id"],
        )
        batch.create_index(
            "ix_account_subscriptions_scheduled_change_at",
            ["scheduled_change_at"],
        )

    op.create_table(
        "plan_offers",
        sa.Column("offer_id", sa.String(length=191), nullable=False),
        sa.Column("plan_id", sa.String(length=191), nullable=False),
        sa.Column("plan_version_id", sa.String(length=191), nullable=False),
        sa.Column("account_id", sa.String(length=191), nullable=True),
        sa.Column("tier_id", sa.String(length=32), nullable=False),
        sa.Column("billing_cycle", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("purchase_mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("trial_enabled", sa.Boolean(), nullable=False),
        sa.Column("trial_days", sa.Integer(), nullable=False),
        sa.Column("trial_credit_limit", sa.Integer(), nullable=False),
        sa.Column("trial_requires_approval", sa.Boolean(), nullable=False),
        sa.Column("valid_from_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.plan_id"]),
        sa.ForeignKeyConstraint(["plan_version_id"], ["plan_versions.plan_version_id"]),
        sa.PrimaryKeyConstraint("offer_id"),
    )
    for column in (
        "plan_id",
        "plan_version_id",
        "account_id",
        "tier_id",
        "purchase_mode",
        "status",
        "valid_until_at",
    ):
        op.create_index(f"ix_plan_offers_{column}", "plan_offers", [column])

    op.create_table(
        "subscription_orders",
        sa.Column("subscription_order_id", sa.String(length=191), nullable=False),
        sa.Column("account_id", sa.String(length=191), nullable=False),
        sa.Column("offer_id", sa.String(length=191), nullable=False),
        sa.Column("payment_order_id", sa.String(length=191), nullable=True),
        sa.Column("source_subscription_id", sa.String(length=191), nullable=True),
        sa.Column("target_plan_id", sa.String(length=191), nullable=False),
        sa.Column("target_plan_version_id", sa.String(length=191), nullable=False),
        sa.Column("order_kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("list_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("credit_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("payable_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"]),
        sa.ForeignKeyConstraint(["offer_id"], ["plan_offers.offer_id"]),
        sa.ForeignKeyConstraint(["payment_order_id"], ["payment_orders.order_id"]),
        sa.PrimaryKeyConstraint("subscription_order_id"),
        sa.UniqueConstraint("payment_order_id", name="uq_subscription_orders_payment_order"),
    )
    for column in (
        "account_id",
        "offer_id",
        "payment_order_id",
        "source_subscription_id",
        "target_plan_id",
        "target_plan_version_id",
        "order_kind",
        "status",
    ):
        op.create_index(f"ix_subscription_orders_{column}", "subscription_orders", [column])

    op.create_table(
        "trial_claims",
        sa.Column("claim_id", sa.String(length=191), nullable=False),
        sa.Column("account_id", sa.String(length=191), nullable=False),
        sa.Column("principal_id", sa.String(length=191), nullable=True),
        sa.Column("site_domain", sa.String(length=255), nullable=True),
        sa.Column("plan_id", sa.String(length=191), nullable=False),
        sa.Column("plan_version_id", sa.String(length=191), nullable=False),
        sa.Column("tier_id", sa.String(length=32), nullable=False),
        sa.Column("highest_tier_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("credit_limit", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by_principal_id", sa.String(length=191), nullable=True),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"]),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.principal_id"]),
        sa.PrimaryKeyConstraint("claim_id"),
        sa.UniqueConstraint("account_id", name="uq_trial_claims_account"),
        sa.UniqueConstraint("principal_id", name="uq_trial_claims_principal"),
        sa.UniqueConstraint("site_domain", name="uq_trial_claims_site_domain"),
    )
    for column in (
        "account_id",
        "principal_id",
        "site_domain",
        "plan_id",
        "plan_version_id",
        "tier_id",
        "status",
        "ends_at",
    ):
        op.create_index(f"ix_trial_claims_{column}", "trial_claims", [column])


def downgrade() -> None:
    op.drop_table("trial_claims")
    op.drop_table("subscription_orders")
    op.drop_table("plan_offers")
    with op.batch_alter_table("account_subscriptions") as batch:
        batch.drop_index("ix_account_subscriptions_scheduled_change_at")
        batch.drop_index("ix_account_subscriptions_scheduled_plan_id")
        batch.drop_column("scheduled_change_at")
        batch.drop_column("scheduled_plan_version_id")
        batch.drop_column("scheduled_plan_id")
