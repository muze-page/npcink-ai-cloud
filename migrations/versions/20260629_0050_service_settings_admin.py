"""service settings admin storage

Revision ID: 20260629_0050
Revises: 20260629_0049
Create Date: 2026-06-29 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260629_0050"
down_revision = "20260629_0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("service_settings"):
        return

    op.create_table(
        "service_settings",
        sa.Column("setting_id", sa.String(length=64), primary_key=True),
        sa.Column("setting_kind", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config_json", sa.JSON(), nullable=True),
        sa.Column("secret_ciphertext_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="missing_config"),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_service_settings_setting_kind", "service_settings", ["setting_kind"])
    op.create_index("ix_service_settings_enabled", "service_settings", ["enabled"])
    op.create_index("ix_service_settings_status", "service_settings", ["status"])


def downgrade() -> None:
    op.drop_index("ix_service_settings_status", table_name="service_settings")
    op.drop_index("ix_service_settings_enabled", table_name="service_settings")
    op.drop_index("ix_service_settings_setting_kind", table_name="service_settings")
    op.drop_table("service_settings")
