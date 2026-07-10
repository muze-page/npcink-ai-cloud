"""support request attachments and feedback

Revision ID: 20260709_0055
Revises: 20260709_0054
Create Date: 2026-07-09 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260709_0055"
down_revision = "20260709_0054"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if not _has_table("support_request_attachments"):
        op.create_table(
            "support_request_attachments",
            sa.Column("attachment_id", sa.String(length=191), nullable=False),
            sa.Column("request_id", sa.String(length=191), nullable=False),
            sa.Column("message_id", sa.String(length=191), nullable=True),
            sa.Column("account_id", sa.String(length=191), nullable=False),
            sa.Column("site_id", sa.String(length=191), nullable=True),
            sa.Column("principal_id", sa.String(length=191), nullable=True),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("uploader_kind", sa.String(length=32), nullable=False),
            sa.Column("visibility", sa.String(length=32), nullable=False),
            sa.Column("filename", sa.String(length=191), nullable=False),
            sa.Column("content_type", sa.String(length=128), nullable=False),
            sa.Column("byte_size", sa.Integer(), nullable=False),
            sa.Column("content_bytes", sa.LargeBinary(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.CheckConstraint(
                "uploader_kind IN ('customer', 'operator')",
                name="ck_support_request_attachments_uploader_kind",
            ),
            sa.CheckConstraint(
                "visibility IN ('public', 'internal')",
                name="ck_support_request_attachments_visibility",
            ),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"]),
            sa.ForeignKeyConstraint(["message_id"], ["support_request_messages.message_id"]),
            sa.ForeignKeyConstraint(["principal_id"], ["principals.principal_id"]),
            sa.ForeignKeyConstraint(["request_id"], ["support_requests.request_id"]),
            sa.ForeignKeyConstraint(["site_id"], ["sites.site_id"]),
            sa.PrimaryKeyConstraint("attachment_id"),
        )
        for column in (
            "account_id",
            "created_at",
            "email",
            "message_id",
            "principal_id",
            "request_id",
            "site_id",
            "uploader_kind",
            "visibility",
        ):
            op.create_index(
                f"ix_support_request_attachments_{column}",
                "support_request_attachments",
                [column],
            )

    if not _has_table("support_request_feedback"):
        op.create_table(
            "support_request_feedback",
            sa.Column("feedback_id", sa.String(length=191), nullable=False),
            sa.Column("request_id", sa.String(length=191), nullable=False),
            sa.Column("account_id", sa.String(length=191), nullable=False),
            sa.Column("site_id", sa.String(length=191), nullable=True),
            sa.Column("principal_id", sa.String(length=191), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("resolved", sa.Boolean(), nullable=False),
            sa.Column("rating", sa.Integer(), nullable=False),
            sa.Column("comment", sa.Text(), nullable=False),
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
                "rating >= 1 AND rating <= 5",
                name="ck_support_request_feedback_rating",
            ),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"]),
            sa.ForeignKeyConstraint(["principal_id"], ["principals.principal_id"]),
            sa.ForeignKeyConstraint(["request_id"], ["support_requests.request_id"]),
            sa.ForeignKeyConstraint(["site_id"], ["sites.site_id"]),
            sa.PrimaryKeyConstraint("feedback_id"),
            sa.UniqueConstraint("request_id", name="uq_support_request_feedback_request_id"),
        )
        for column in (
            "account_id",
            "created_at",
            "email",
            "principal_id",
            "rating",
            "request_id",
            "resolved",
            "site_id",
            "updated_at",
        ):
            op.create_index(
                f"ix_support_request_feedback_{column}",
                "support_request_feedback",
                [column],
            )


def downgrade() -> None:
    if _has_table("support_request_feedback"):
        op.drop_table("support_request_feedback")
    if _has_table("support_request_attachments"):
        op.drop_table("support_request_attachments")
