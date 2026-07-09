"""admin commercial cny pricing

Revision ID: 20260709_0056
Revises: 20260709_0055
Create Date: 2026-07-09 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260709_0056"
down_revision = "20260709_0055"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    if _has_table("plan_versions"):
        bind.execute(
            sa.text("UPDATE plan_versions SET currency = 'CNY' WHERE currency = 'USD'")
        )
        with op.batch_alter_table("plan_versions") as batch:
            batch.alter_column(
                "currency",
                existing_type=sa.String(length=16),
                server_default="CNY",
                existing_nullable=False,
            )
    if _has_table("billing_snapshots"):
        bind.execute(
            sa.text("UPDATE billing_snapshots SET currency = 'CNY' WHERE currency = 'USD'")
        )
        with op.batch_alter_table("billing_snapshots") as batch:
            batch.alter_column(
                "currency",
                existing_type=sa.String(length=16),
                server_default="CNY",
                existing_nullable=False,
            )


def downgrade() -> None:
    if _has_table("plan_versions"):
        with op.batch_alter_table("plan_versions") as batch:
            batch.alter_column(
                "currency",
                existing_type=sa.String(length=16),
                server_default="USD",
                existing_nullable=False,
            )
    if _has_table("billing_snapshots"):
        with op.batch_alter_table("billing_snapshots") as batch:
            batch.alter_column(
                "currency",
                existing_type=sa.String(length=16),
                server_default="USD",
                existing_nullable=False,
            )
