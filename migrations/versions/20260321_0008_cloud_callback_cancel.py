"""runtime callback delivery and cancel lifecycle schema"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260321_0008"
down_revision = "20260321_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "run_records",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "run_records",
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "run_records",
        sa.Column(
            "callback_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_requested",
        ),
    )
    op.add_column(
        "run_records",
        sa.Column(
            "callback_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "run_records",
        sa.Column("callback_last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "run_records",
        sa.Column("callback_delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "run_records",
        sa.Column("callback_next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "run_records",
        sa.Column("callback_last_error_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "run_records",
        sa.Column("callback_last_error_message", sa.Text(), nullable=True),
    )

    op.create_index("ix_run_records_cancel_requested_at", "run_records", ["cancel_requested_at"])
    op.create_index("ix_run_records_canceled_at", "run_records", ["canceled_at"])
    op.create_index("ix_run_records_callback_status", "run_records", ["callback_status"])
    op.create_index(
        "ix_run_records_callback_next_attempt_at",
        "run_records",
        ["callback_next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_run_records_callback_next_attempt_at", table_name="run_records")
    op.drop_index("ix_run_records_callback_status", table_name="run_records")
    op.drop_index("ix_run_records_canceled_at", table_name="run_records")
    op.drop_index("ix_run_records_cancel_requested_at", table_name="run_records")

    op.drop_column("run_records", "callback_last_error_message")
    op.drop_column("run_records", "callback_last_error_code")
    op.drop_column("run_records", "callback_next_attempt_at")
    op.drop_column("run_records", "callback_delivered_at")
    op.drop_column("run_records", "callback_last_attempt_at")
    op.drop_column("run_records", "callback_attempt_count")
    op.drop_column("run_records", "callback_status")
    op.drop_column("run_records", "canceled_at")
    op.drop_column("run_records", "cancel_requested_at")
