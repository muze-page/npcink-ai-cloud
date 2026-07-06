"""runtime hot path composite indexes

Revision ID: 20260706_0052
Revises: 20260703_0051
Create Date: 2026-07-06 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260706_0052"
down_revision = "20260703_0051"
branch_labels = None
depends_on = None


def _has_index(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def _create_index_once(index_name: str, table_name: str, columns: list[str]) -> None:
    if _has_index(table_name, index_name):
        return
    op.create_index(index_name, table_name, columns)


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    if not _has_index(table_name, index_name):
        return
    op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    _create_index_once(
        "ix_run_records_status_started_run",
        "run_records",
        ["status", "started_at", "run_id"],
    )
    _create_index_once(
        "ix_run_records_status_processing_started",
        "run_records",
        ["status", "processing_started_at", "run_id"],
    )
    _create_index_once(
        "ix_run_records_callback_due",
        "run_records",
        ["callback_status", "callback_next_attempt_at", "finished_at"],
    )
    _create_index_once(
        "ix_run_records_callback_dispatching_lease",
        "run_records",
        ["callback_status", "callback_last_attempt_at", "finished_at"],
    )


def downgrade() -> None:
    _drop_index_if_exists("ix_run_records_callback_dispatching_lease", "run_records")
    _drop_index_if_exists("ix_run_records_callback_due", "run_records")
    _drop_index_if_exists("ix_run_records_status_processing_started", "run_records")
    _drop_index_if_exists("ix_run_records_status_started_run", "run_records")
