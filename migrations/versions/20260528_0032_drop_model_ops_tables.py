"""drop_model_ops_tables

Revision ID: 20260528_0032
Revises: 20260527_0031
Create Date: 2026-05-28

"""

from alembic import op
import sqlalchemy as sa


revision = "20260528_0032"
down_revision = "20260527_0031"
branch_labels = None
depends_on = None


def _drop_table_if_exists(table_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table(table_name):
        op.drop_table(table_name)


def upgrade() -> None:
    _drop_table_if_exists("recognition_model_annotations")
    _drop_table_if_exists("recognition_source_runs")
    _drop_table_if_exists("recognition_snapshot_publications")
    _drop_table_if_exists("catalog_model_annotations")
    _drop_table_if_exists("provider_connections")


def downgrade() -> None:
    pass
