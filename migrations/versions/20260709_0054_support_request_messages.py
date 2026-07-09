"""support request messages

Revision ID: 20260709_0054
Revises: 20260709_0053
Create Date: 2026-07-09 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260709_0054"
down_revision = "20260709_0053"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if _has_table("support_request_messages"):
        return
    op.create_table(
        "support_request_messages",
        sa.Column("message_id", sa.String(length=191), nullable=False),
        sa.Column("request_id", sa.String(length=191), nullable=False),
        sa.Column("account_id", sa.String(length=191), nullable=False),
        sa.Column("site_id", sa.String(length=191), nullable=True),
        sa.Column("principal_id", sa.String(length=191), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("author_kind", sa.String(length=32), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "author_kind IN ('customer', 'operator', 'system')",
            name="ck_support_request_messages_author_kind",
        ),
        sa.CheckConstraint(
            "visibility IN ('public', 'internal')",
            name="ck_support_request_messages_visibility",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"]),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.principal_id"]),
        sa.ForeignKeyConstraint(["request_id"], ["support_requests.request_id"]),
        sa.ForeignKeyConstraint(["site_id"], ["sites.site_id"]),
        sa.PrimaryKeyConstraint("message_id"),
    )
    op.create_index(
        "ix_support_request_messages_account_id",
        "support_request_messages",
        ["account_id"],
    )
    op.create_index(
        "ix_support_request_messages_author_kind",
        "support_request_messages",
        ["author_kind"],
    )
    op.create_index(
        "ix_support_request_messages_created_at",
        "support_request_messages",
        ["created_at"],
    )
    op.create_index(
        "ix_support_request_messages_email",
        "support_request_messages",
        ["email"],
    )
    op.create_index(
        "ix_support_request_messages_principal_id",
        "support_request_messages",
        ["principal_id"],
    )
    op.create_index(
        "ix_support_request_messages_request_id",
        "support_request_messages",
        ["request_id"],
    )
    op.create_index(
        "ix_support_request_messages_site_id",
        "support_request_messages",
        ["site_id"],
    )
    op.create_index(
        "ix_support_request_messages_visibility",
        "support_request_messages",
        ["visibility"],
    )


def downgrade() -> None:
    if not _has_table("support_request_messages"):
        return
    op.drop_table("support_request_messages")
