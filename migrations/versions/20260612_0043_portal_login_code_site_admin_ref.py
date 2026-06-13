"""repair portal login code site admin reference column"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260612_0043"
down_revision = "20260612_0042"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _column_names(table_name: str) -> set[str]:
    return {str(column["name"]) for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    return {str(index["name"]) for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    table_name = "portal_login_codes"
    if not _table_exists(table_name):
        return

    indexes = _index_names(table_name)
    if "ix_portal_login_codes_member_ref" in indexes:
        op.drop_index("ix_portal_login_codes_member_ref", table_name=table_name)

    columns = _column_names(table_name)
    if "site_admin_ref" not in columns and "member_ref" in columns:
        op.alter_column(
            table_name,
            "member_ref",
            new_column_name="site_admin_ref",
            existing_type=sa.String(length=191),
            existing_nullable=False,
        )
    elif "site_admin_ref" not in columns:
        op.add_column(table_name, sa.Column("site_admin_ref", sa.String(length=191), nullable=True))
        op.execute(
            """
            UPDATE portal_login_codes
            SET site_admin_ref = 'site_admin:' || lower(email)
            WHERE site_admin_ref IS NULL OR site_admin_ref = ''
            """
        )
        op.alter_column(
            table_name,
            "site_admin_ref",
            existing_type=sa.String(length=191),
            nullable=False,
        )

    if "ix_portal_login_codes_site_admin_ref" not in _index_names(table_name):
        op.create_index(
            "ix_portal_login_codes_site_admin_ref",
            table_name,
            ["site_admin_ref"],
        )


def downgrade() -> None:
    table_name = "portal_login_codes"
    if not _table_exists(table_name):
        return

    indexes = _index_names(table_name)
    if "ix_portal_login_codes_site_admin_ref" in indexes:
        op.drop_index("ix_portal_login_codes_site_admin_ref", table_name=table_name)

    columns = _column_names(table_name)
    if "member_ref" not in columns and "site_admin_ref" in columns:
        op.alter_column(
            table_name,
            "site_admin_ref",
            new_column_name="member_ref",
            existing_type=sa.String(length=191),
            existing_nullable=False,
        )

    if "ix_portal_login_codes_member_ref" not in _index_names(table_name):
        op.create_index("ix_portal_login_codes_member_ref", table_name, ["member_ref"])
