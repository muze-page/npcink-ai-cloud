"""payment-order-backed expiring credit grants

Revision ID: 20260711_0059
Revises: 20260710_0058
Create Date: 2026-07-11 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260711_0059"
down_revision = "20260710_0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paid_credit_grants",
        sa.Column("grant_id", sa.String(length=191), nullable=False),
        sa.Column("account_id", sa.String(length=191), nullable=False),
        sa.Column("payment_order_id", sa.String(length=191), nullable=False),
        sa.Column("original_credits", sa.Float(), nullable=False),
        sa.Column("remaining_credits", sa.Float(), nullable=False),
        sa.Column("refunded_credits", sa.Float(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint(
            "original_credits >= 0 AND remaining_credits >= 0 AND refunded_credits >= 0",
            name="ck_paid_credit_grants_nonnegative",
        ),
        sa.CheckConstraint(
            "remaining_credits + refunded_credits <= original_credits",
            name="ck_paid_credit_grants_balance",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"]),
        sa.ForeignKeyConstraint(["payment_order_id"], ["payment_orders.order_id"]),
        sa.PrimaryKeyConstraint("grant_id"),
        sa.UniqueConstraint("payment_order_id", name="uq_paid_credit_grants_payment_order"),
    )
    for column in ("account_id", "payment_order_id", "expires_at", "created_at"):
        op.create_index(f"ix_paid_credit_grants_{column}", "paid_credit_grants", [column])


def downgrade() -> None:
    op.drop_table("paid_credit_grants")
