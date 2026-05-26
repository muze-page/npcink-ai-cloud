"""add provider connection source role

Revision ID: 20260403_0020
Revises: 20260403_0019
Create Date: 2026-04-03 23:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260403_0020"
down_revision = "20260403_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_connections",
        sa.Column(
            "source_role",
            sa.String(length=32),
            nullable=False,
            server_default="execution_source",
        ),
    )
    op.create_index(
        "ix_provider_connections_source_role",
        "provider_connections",
        ["source_role"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_provider_connections_source_role", table_name="provider_connections")
    op.drop_column("provider_connections", "source_role")
