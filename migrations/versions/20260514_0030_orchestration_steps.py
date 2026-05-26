"""orchestration_steps

Revision ID: 20260514_0030
Revises: 20260514_0029
Create Date: 2026-05-14

"""

from alembic import op
import sqlalchemy as sa


revision = "20260514_0030"
down_revision = "20260514_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orchestration_steps",
        sa.Column("step_id", sa.String(191), primary_key=True),
        sa.Column("orchestration_run_id", sa.String(191), nullable=False),
        sa.Column("step_index", sa.Integer, nullable=False),
        sa.Column("ability_name", sa.String(191), nullable=False),
        sa.Column("input_payload", sa.JSON, nullable=True),
        sa.Column("step_output", sa.JSON, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("max_retries", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("timeout_seconds", sa.Integer, nullable=False, server_default=sa.text("60")),
        sa.Column("when_condition", sa.JSON, nullable=True),
        sa.Column("foreach_path", sa.String(191), nullable=True),
        sa.Column("foreach_iteration_count", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["orchestration_run_id"], ["orchestration_runs.orchestration_run_id"], ondelete="CASCADE"),
        sa.Index("idx_orchestration_steps_run", "orchestration_run_id", "step_index"),
    )


def downgrade() -> None:
    op.drop_table("orchestration_steps")
