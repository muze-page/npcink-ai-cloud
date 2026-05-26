"""generic replay receipt store for public/internal post surfaces"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260320_0005"
down_revision = "20260312_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "replay_receipts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scope_kind", sa.String(length=32), nullable=False),
        sa.Column("scope_id", sa.String(length=191), nullable=False),
        sa.Column("replay_key", sa.String(length=191), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "scope_kind",
            "scope_id",
            "replay_key",
            name="uq_replay_receipts_scope_marker",
        ),
    )
    op.create_index(
        "ix_replay_receipts_scope_kind",
        "replay_receipts",
        ["scope_kind"],
    )
    op.create_index(
        "ix_replay_receipts_scope_id",
        "replay_receipts",
        ["scope_id"],
    )
    op.create_index(
        "ix_replay_receipts_expires_at",
        "replay_receipts",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_replay_receipts_expires_at", table_name="replay_receipts")
    op.drop_index("ix_replay_receipts_scope_id", table_name="replay_receipts")
    op.drop_index("ix_replay_receipts_scope_kind", table_name="replay_receipts")
    op.drop_table("replay_receipts")
