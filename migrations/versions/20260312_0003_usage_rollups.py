"""usage rollup snapshots"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260312_0003"
down_revision = "20260312_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_rollups",
        sa.Column("rollup_key", sa.String(length=255), primary_key=True),
        sa.Column("site_scope", sa.String(length=191), nullable=False),
        sa.Column("scope_kind", sa.String(length=32), nullable=False),
        sa.Column("scope_id", sa.String(length=191), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_usage_rollups_site_scope", "usage_rollups", ["site_scope"])
    op.create_index("ix_usage_rollups_scope_kind", "usage_rollups", ["scope_kind"])
    op.create_index("ix_usage_rollups_scope_id", "usage_rollups", ["scope_id"])


def downgrade() -> None:
    op.drop_index("ix_usage_rollups_scope_id", table_name="usage_rollups")
    op.drop_index("ix_usage_rollups_scope_kind", table_name="usage_rollups")
    op.drop_index("ix_usage_rollups_site_scope", table_name="usage_rollups")
    op.drop_table("usage_rollups")
