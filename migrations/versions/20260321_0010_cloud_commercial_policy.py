"""commercial policy freeze fields for plan versions and entitlement snapshots"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260321_0010"
down_revision = "20260321_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    plan_version_columns = {
        column["name"] for column in inspector.get_columns("plan_versions")
    }
    if "policy_json" not in plan_version_columns:
        op.add_column(
            "plan_versions",
            sa.Column("policy_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )

    entitlement_snapshot_columns = {
        column["name"] for column in inspector.get_columns("site_entitlement_snapshots")
    }
    if "policy_json" not in entitlement_snapshot_columns:
        op.add_column(
            "site_entitlement_snapshots",
            sa.Column("policy_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    plan_version_columns = {
        column["name"] for column in inspector.get_columns("plan_versions")
    }
    if "policy_json" in plan_version_columns:
        op.drop_column("plan_versions", "policy_json")

    entitlement_snapshot_columns = {
        column["name"] for column in inspector.get_columns("site_entitlement_snapshots")
    }
    if "policy_json" in entitlement_snapshot_columns:
        op.drop_column("site_entitlement_snapshots", "policy_json")
