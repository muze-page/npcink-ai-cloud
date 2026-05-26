"""recognition source runs"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260403_0018"
down_revision = "20260331_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recognition_source_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=191), nullable=False),
        sa.Column("source_name", sa.String(length=64), nullable=False),
        sa.Column("snapshot_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_accepted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("run_id", name="uq_recognition_source_runs_run_id"),
    )
    op.create_index(
        "ix_recognition_source_runs_run_id",
        "recognition_source_runs",
        ["run_id"],
    )
    op.create_index(
        "ix_recognition_source_runs_source_name",
        "recognition_source_runs",
        ["source_name"],
    )
    op.create_index(
        "ix_recognition_source_runs_snapshot_generated_at",
        "recognition_source_runs",
        ["snapshot_generated_at"],
    )
    op.create_index(
        "ix_recognition_source_runs_started_at",
        "recognition_source_runs",
        ["started_at"],
    )
    op.create_index(
        "ix_recognition_source_runs_finished_at",
        "recognition_source_runs",
        ["finished_at"],
    )
    op.create_index(
        "ix_recognition_source_runs_status",
        "recognition_source_runs",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_recognition_source_runs_status", table_name="recognition_source_runs")
    op.drop_index("ix_recognition_source_runs_finished_at", table_name="recognition_source_runs")
    op.drop_index("ix_recognition_source_runs_started_at", table_name="recognition_source_runs")
    op.drop_index(
        "ix_recognition_source_runs_snapshot_generated_at",
        table_name="recognition_source_runs",
    )
    op.drop_index("ix_recognition_source_runs_source_name", table_name="recognition_source_runs")
    op.drop_index("ix_recognition_source_runs_run_id", table_name="recognition_source_runs")
    op.drop_table("recognition_source_runs")
