"""portal login codes

Revision ID: 20260331_0017
Revises: 20260330_0016
Create Date: 2026-03-31 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260331_0017"
down_revision = "20260330_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portal_login_codes",
        sa.Column("code_id", sa.String(length=191), primary_key=True),
        sa.Column("email", sa.String(length=191), nullable=False),
        sa.Column("member_ref", sa.String(length=191), nullable=False),
        sa.Column("code_hash", sa.String(length=191), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_portal_login_codes_email", "portal_login_codes", ["email"])
    op.create_index("ix_portal_login_codes_member_ref", "portal_login_codes", ["member_ref"])
    op.create_index("ix_portal_login_codes_status", "portal_login_codes", ["status"])
    op.create_index("ix_portal_login_codes_expires_at", "portal_login_codes", ["expires_at"])
    op.create_index("ix_portal_login_codes_consumed_at", "portal_login_codes", ["consumed_at"])


def downgrade() -> None:
    op.drop_index("ix_portal_login_codes_consumed_at", table_name="portal_login_codes")
    op.drop_index("ix_portal_login_codes_expires_at", table_name="portal_login_codes")
    op.drop_index("ix_portal_login_codes_status", table_name="portal_login_codes")
    op.drop_index("ix_portal_login_codes_member_ref", table_name="portal_login_codes")
    op.drop_index("ix_portal_login_codes_email", table_name="portal_login_codes")
    op.drop_table("portal_login_codes")
