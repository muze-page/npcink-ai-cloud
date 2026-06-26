"""runtime provider connections admin storage

Revision ID: 20260626_0047
Revises: 20260625_0046
Create Date: 2026-06-26 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260626_0047"
down_revision = "20260625_0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("provider_connections"):
        return

    op.create_table(
        "provider_connections",
        sa.Column("connection_id", sa.String(length=64), primary_key=True),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=191), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("base_url", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("config_json", sa.JSON(), nullable=True),
        sa.Column("secret_ciphertext", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="missing_secret"),
        sa.Column(
            "source_role",
            sa.String(length=32),
            nullable=False,
            server_default="execution_source",
        ),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
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
    op.create_index("ix_provider_connections_provider_type", "provider_connections", ["provider_type"])
    op.create_index("ix_provider_connections_enabled", "provider_connections", ["enabled"])
    op.create_index("ix_provider_connections_status", "provider_connections", ["status"])
    op.create_index("ix_provider_connections_source_role", "provider_connections", ["source_role"])


def downgrade() -> None:
    op.drop_index("ix_provider_connections_source_role", table_name="provider_connections")
    op.drop_index("ix_provider_connections_status", table_name="provider_connections")
    op.drop_index("ix_provider_connections_enabled", table_name="provider_connections")
    op.drop_index("ix_provider_connections_provider_type", table_name="provider_connections")
    op.drop_table("provider_connections")
