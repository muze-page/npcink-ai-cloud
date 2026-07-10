"""make account membership the only portal authorization source

Revision ID: 20260710_0057
Revises: 20260709_0056
Create Date: 2026-07-10 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260710_0057"
down_revision = "20260709_0056"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if _has_table("site_user_grants"):
        grant_count = int(
            bind.execute(sa.text("SELECT COUNT(*) FROM site_user_grants")).scalar_one()
        )
        if grant_count:
            raise RuntimeError(
                "site_user_grants must be empty before the account-membership authorization cutover"
            )
        op.drop_table("site_user_grants")

    membership_index = "ix_account_user_memberships_principal_status_account"
    if _has_table("account_user_memberships") and not _has_index(
        "account_user_memberships", membership_index
    ):
        op.create_index(
            membership_index,
            "account_user_memberships",
            ["principal_id", "status", "account_id"],
        )


def downgrade() -> None:
    membership_index = "ix_account_user_memberships_principal_status_account"
    if _has_table("account_user_memberships") and _has_index(
        "account_user_memberships", membership_index
    ):
        op.drop_index(membership_index, table_name="account_user_memberships")

    if not _has_table("site_user_grants"):
        op.create_table(
            "site_user_grants",
            sa.Column("grant_id", sa.String(length=191), nullable=False),
            sa.Column("principal_id", sa.String(length=191), nullable=False),
            sa.Column("site_id", sa.String(length=191), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
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
            sa.ForeignKeyConstraint(["principal_id"], ["principals.principal_id"]),
            sa.ForeignKeyConstraint(["site_id"], ["sites.site_id"]),
            sa.PrimaryKeyConstraint("grant_id"),
            sa.UniqueConstraint(
                "principal_id",
                "site_id",
                name="uq_site_user_grants_principal_site",
            ),
        )
        op.create_index(
            "ix_site_user_grants_principal_id",
            "site_user_grants",
            ["principal_id"],
        )
        op.create_index("ix_site_user_grants_site_id", "site_user_grants", ["site_id"])
        op.create_index("ix_site_user_grants_status", "site_user_grants", ["status"])
