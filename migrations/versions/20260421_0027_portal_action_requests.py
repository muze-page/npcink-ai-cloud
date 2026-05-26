"""add portal action requests

Revision ID: 20260421_0027
Revises: 20260415_0026
Create Date: 2026-04-21 18:45:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260421_0027"
down_revision = "20260415_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "portal_action_requests" in inspector.get_table_names():
        return

    op.create_table(
        "portal_action_requests",
        sa.Column("request_id", sa.String(length=191), nullable=False),
        sa.Column("request_type", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=191), nullable=True),
        sa.Column("site_id", sa.String(length=191), nullable=True),
        sa.Column("member_ref", sa.String(length=191), nullable=False),
        sa.Column("title", sa.String(length=191), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("request_id"),
    )
    op.create_index("ix_portal_action_requests_request_type", "portal_action_requests", ["request_type"])
    op.create_index("ix_portal_action_requests_account_id", "portal_action_requests", ["account_id"])
    op.create_index("ix_portal_action_requests_site_id", "portal_action_requests", ["site_id"])
    op.create_index("ix_portal_action_requests_member_ref", "portal_action_requests", ["member_ref"])
    op.create_index("ix_portal_action_requests_status", "portal_action_requests", ["status"])
    op.create_index("ix_portal_action_requests_created_at", "portal_action_requests", ["created_at"])
    op.create_index("ix_portal_action_requests_acknowledged_at", "portal_action_requests", ["acknowledged_at"])
    op.create_index("ix_portal_action_requests_resolved_at", "portal_action_requests", ["resolved_at"])
    op.create_index("ix_portal_action_requests_canceled_at", "portal_action_requests", ["canceled_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "portal_action_requests" not in inspector.get_table_names():
        return

    op.drop_index("ix_portal_action_requests_canceled_at", table_name="portal_action_requests")
    op.drop_index("ix_portal_action_requests_resolved_at", table_name="portal_action_requests")
    op.drop_index("ix_portal_action_requests_acknowledged_at", table_name="portal_action_requests")
    op.drop_index("ix_portal_action_requests_created_at", table_name="portal_action_requests")
    op.drop_index("ix_portal_action_requests_status", table_name="portal_action_requests")
    op.drop_index("ix_portal_action_requests_member_ref", table_name="portal_action_requests")
    op.drop_index("ix_portal_action_requests_site_id", table_name="portal_action_requests")
    op.drop_index("ix_portal_action_requests_account_id", table_name="portal_action_requests")
    op.drop_index("ix_portal_action_requests_request_type", table_name="portal_action_requests")
    op.drop_table("portal_action_requests")
