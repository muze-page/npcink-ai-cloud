"""orchestration_runs

Revision ID: 20260514_0029
Revises: 20260428_0028
Create Date: 2026-05-14

"""

from alembic import op
import sqlalchemy as sa


revision = "20260514_0029"
down_revision = "20260428_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orchestration_runs",
        sa.Column("orchestration_run_id", sa.String(191), primary_key=True),
        sa.Column("site_id", sa.String(191), nullable=False),
        sa.Column("workflow_id", sa.String(191), nullable=False),
        sa.Column("workflow_version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("submitted_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column("callback_url", sa.Text, nullable=True),
        sa.Column("result_summary", sa.JSON, nullable=True),
        sa.Column("max_duration_seconds", sa.Integer, nullable=False, server_default=sa.text("3600")),
        sa.Column("cancel_requested_at", sa.DateTime, nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("failed_step_index", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["site_id"], ["sites.site_id"]),
        sa.Index("idx_orchestration_runs_site", "site_id"),
        sa.Index("idx_orchestration_runs_status", "status"),
        sa.Index("idx_orchestration_runs_submitted", "submitted_at"),
    )


def downgrade() -> None:
    op.drop_table("orchestration_runs")
