"""support requests

Revision ID: 20260709_0053
Revises: 20260706_0052
Create Date: 2026-07-09 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260709_0053"
down_revision = "20260706_0052"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if _has_table("support_requests"):
        return
    op.create_table(
        "support_requests",
        sa.Column("request_id", sa.String(length=191), nullable=False),
        sa.Column("account_id", sa.String(length=191), nullable=False),
        sa.Column("site_id", sa.String(length=191), nullable=True),
        sa.Column("principal_id", sa.String(length=191), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("topic", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=191), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("source_path", sa.String(length=191), nullable=False),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("context_json", sa.JSON(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('open', 'in_progress', 'resolved', 'closed')",
            name="ck_support_requests_status",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"]),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.principal_id"]),
        sa.ForeignKeyConstraint(["site_id"], ["sites.site_id"]),
        sa.PrimaryKeyConstraint("request_id"),
    )
    op.create_index("ix_support_requests_account_id", "support_requests", ["account_id"])
    op.create_index("ix_support_requests_closed_at", "support_requests", ["closed_at"])
    op.create_index("ix_support_requests_created_at", "support_requests", ["created_at"])
    op.create_index("ix_support_requests_email", "support_requests", ["email"])
    op.create_index("ix_support_requests_principal_id", "support_requests", ["principal_id"])
    op.create_index("ix_support_requests_priority", "support_requests", ["priority"])
    op.create_index("ix_support_requests_resolved_at", "support_requests", ["resolved_at"])
    op.create_index("ix_support_requests_site_id", "support_requests", ["site_id"])
    op.create_index("ix_support_requests_status", "support_requests", ["status"])
    op.create_index("ix_support_requests_topic", "support_requests", ["topic"])
    op.create_index("ix_support_requests_updated_at", "support_requests", ["updated_at"])


def downgrade() -> None:
    if not _has_table("support_requests"):
        return
    op.drop_table("support_requests")
