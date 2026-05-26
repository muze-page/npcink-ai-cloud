"""cloud skill execution contract fields on run records"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260312_0004"
down_revision = "20260312_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "run_records",
        sa.Column("skill_id", sa.String(length=191), nullable=True),
    )
    op.add_column(
        "run_records",
        sa.Column("workflow_id", sa.String(length=191), nullable=True),
    )
    op.add_column(
        "run_records",
        sa.Column("contract_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "run_records",
        sa.Column(
            "execution_tier",
            sa.String(length=32),
            nullable=False,
            server_default="cloud",
        ),
    )
    op.add_column(
        "run_records",
        sa.Column(
            "execution_pattern",
            sa.String(length=32),
            nullable=False,
            server_default="step_offload",
        ),
    )
    op.add_column(
        "run_records",
        sa.Column(
            "data_classification",
            sa.String(length=32),
            nullable=False,
            server_default="internal",
        ),
    )
    op.create_index("ix_run_records_execution_tier", "run_records", ["execution_tier"])


def downgrade() -> None:
    op.drop_index("ix_run_records_execution_tier", table_name="run_records")
    op.drop_column("run_records", "data_classification")
    op.drop_column("run_records", "execution_pattern")
    op.drop_column("run_records", "execution_tier")
    op.drop_column("run_records", "contract_version")
    op.drop_column("run_records", "workflow_id")
    op.drop_column("run_records", "skill_id")
