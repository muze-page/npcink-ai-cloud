"""collapse commercial identity roles to platform_admin and user_admin

Revision ID: 20260412_0023
Revises: 20260410_0022
Create Date: 2026-04-12 18:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260412_0023"
down_revision = "20260410_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()

    connection.execute(
        sa.text(
            """
            UPDATE account_memberships
            SET role = :new_role
            WHERE role IS NULL OR role <> :new_role
            """
        ),
        {"new_role": "user_admin"},
    )
    connection.execute(
        sa.text(
            """
            UPDATE platform_admin_identities
            SET role = :new_role
            WHERE role IS NULL OR role <> :new_role
            """
        ),
        {"new_role": "platform_admin"},
    )
    connection.execute(
        sa.text(
            """
            UPDATE platform_impersonation_sessions
            SET platform_role = :new_role
            WHERE platform_role IS NULL OR platform_role <> :new_role
            """
        ),
        {"new_role": "platform_admin"},
    )

    with op.batch_alter_table("account_memberships") as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=sa.String(length=32),
            nullable=False,
            server_default="user_admin",
        )

    with op.batch_alter_table("platform_admin_identities") as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=sa.String(length=64),
            nullable=False,
            server_default="platform_admin",
        )


def downgrade() -> None:
    raise RuntimeError("downgrade is intentionally unsupported for the identity role collapse")
