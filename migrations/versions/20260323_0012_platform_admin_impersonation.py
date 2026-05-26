"""platform admin identities and impersonation sessions

Revision ID: 20260323_0012
Revises: 20260323_0011
Create Date: 2026-03-23 15:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260323_0012"
down_revision = "20260323_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical migration snapshot: this revision originally created platform
    # admin records with legacy sub-role defaults. Current head later rewrites
    # stored roles to the canonical two-identity model, so these literals are
    # preserved only to keep the migration chain historically accurate.
    op.create_table(
        "platform_admin_identities",
        sa.Column("admin_id", sa.String(length=191), primary_key=True),
        sa.Column("admin_ref", sa.String(length=191), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default="manual"),
        sa.Column("external_subject", sa.String(length=191), nullable=True),
        sa.Column("email", sa.String(length=191), nullable=True),
        sa.Column(
            "role",
            sa.String(length=64),
            nullable=False,
            server_default="platform_support_admin",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("admin_ref", name="uq_platform_admin_identities_admin_ref"),
    )
    op.create_index(
        "ix_platform_admin_identities_admin_ref",
        "platform_admin_identities",
        ["admin_ref"],
    )
    op.create_index(
        "ix_platform_admin_identities_provider",
        "platform_admin_identities",
        ["provider"],
    )
    op.create_index(
        "ix_platform_admin_identities_external_subject",
        "platform_admin_identities",
        ["external_subject"],
    )
    op.create_index(
        "ix_platform_admin_identities_email",
        "platform_admin_identities",
        ["email"],
    )
    op.create_index(
        "ix_platform_admin_identities_role",
        "platform_admin_identities",
        ["role"],
    )
    op.create_index(
        "ix_platform_admin_identities_status",
        "platform_admin_identities",
        ["status"],
    )

    op.create_table(
        "platform_impersonation_sessions",
        sa.Column("impersonation_id", sa.String(length=191), primary_key=True),
        sa.Column("platform_admin_ref", sa.String(length=191), nullable=False),
        sa.Column("platform_role", sa.String(length=64), nullable=False),
        sa.Column("member_ref", sa.String(length=191), nullable=False),
        sa.Column("account_id", sa.String(length=191), nullable=True),
        sa.Column("site_id", sa.String(length=191), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("reason_text", sa.Text(), nullable=True),
        sa.Column("read_only", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_reason", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_platform_impersonation_sessions_platform_admin_ref",
        "platform_impersonation_sessions",
        ["platform_admin_ref"],
    )
    op.create_index(
        "ix_platform_impersonation_sessions_platform_role",
        "platform_impersonation_sessions",
        ["platform_role"],
    )
    op.create_index(
        "ix_platform_impersonation_sessions_member_ref",
        "platform_impersonation_sessions",
        ["member_ref"],
    )
    op.create_index(
        "ix_platform_impersonation_sessions_account_id",
        "platform_impersonation_sessions",
        ["account_id"],
    )
    op.create_index(
        "ix_platform_impersonation_sessions_site_id",
        "platform_impersonation_sessions",
        ["site_id"],
    )
    op.create_index(
        "ix_platform_impersonation_sessions_reason_code",
        "platform_impersonation_sessions",
        ["reason_code"],
    )
    op.create_index(
        "ix_platform_impersonation_sessions_status",
        "platform_impersonation_sessions",
        ["status"],
    )
    op.create_index(
        "ix_platform_impersonation_sessions_started_at",
        "platform_impersonation_sessions",
        ["started_at"],
    )
    op.create_index(
        "ix_platform_impersonation_sessions_expires_at",
        "platform_impersonation_sessions",
        ["expires_at"],
    )
    op.create_index(
        "ix_platform_impersonation_sessions_ended_at",
        "platform_impersonation_sessions",
        ["ended_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_platform_impersonation_sessions_ended_at", table_name="platform_impersonation_sessions")
    op.drop_index("ix_platform_impersonation_sessions_expires_at", table_name="platform_impersonation_sessions")
    op.drop_index("ix_platform_impersonation_sessions_started_at", table_name="platform_impersonation_sessions")
    op.drop_index("ix_platform_impersonation_sessions_status", table_name="platform_impersonation_sessions")
    op.drop_index("ix_platform_impersonation_sessions_reason_code", table_name="platform_impersonation_sessions")
    op.drop_index("ix_platform_impersonation_sessions_site_id", table_name="platform_impersonation_sessions")
    op.drop_index("ix_platform_impersonation_sessions_account_id", table_name="platform_impersonation_sessions")
    op.drop_index("ix_platform_impersonation_sessions_member_ref", table_name="platform_impersonation_sessions")
    op.drop_index("ix_platform_impersonation_sessions_platform_role", table_name="platform_impersonation_sessions")
    op.drop_index("ix_platform_impersonation_sessions_platform_admin_ref", table_name="platform_impersonation_sessions")
    op.drop_table("platform_impersonation_sessions")

    op.drop_index("ix_platform_admin_identities_status", table_name="platform_admin_identities")
    op.drop_index("ix_platform_admin_identities_role", table_name="platform_admin_identities")
    op.drop_index("ix_platform_admin_identities_email", table_name="platform_admin_identities")
    op.drop_index("ix_platform_admin_identities_external_subject", table_name="platform_admin_identities")
    op.drop_index("ix_platform_admin_identities_provider", table_name="platform_admin_identities")
    op.drop_index("ix_platform_admin_identities_admin_ref", table_name="platform_admin_identities")
    op.drop_table("platform_admin_identities")
