"""add canonical run backlink to hosted runtime records

Revision ID: 20260327_0013
Revises: 20260323_0012
Create Date: 2026-03-27 12:40:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260327_0013"
down_revision = "20260323_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    column_names = {column["name"] for column in inspector.get_columns("run_records")}
    index_names = {index["name"] for index in inspector.get_indexes("run_records")}

    if "canonical_run_id" not in column_names:
        op.add_column(
            "run_records",
            sa.Column("canonical_run_id", sa.String(length=191), nullable=True),
        )

    if "ix_run_records_canonical_run_id" not in index_names:
        op.create_index(
            "ix_run_records_canonical_run_id",
            "run_records",
            ["canonical_run_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    column_names = {column["name"] for column in inspector.get_columns("run_records")}
    index_names = {index["name"] for index in inspector.get_indexes("run_records")}

    if "ix_run_records_canonical_run_id" in index_names:
        op.drop_index("ix_run_records_canonical_run_id", table_name="run_records")

    if "canonical_run_id" in column_names:
        op.drop_column("run_records", "canonical_run_id")
