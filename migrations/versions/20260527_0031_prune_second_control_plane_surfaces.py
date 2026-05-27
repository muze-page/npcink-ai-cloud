"""prune_second_control_plane_surfaces

Revision ID: 20260527_0031
Revises: 20260514_0030
Create Date: 2026-05-27

"""

from alembic import op
import sqlalchemy as sa


revision = "20260527_0031"
down_revision = "20260514_0030"
branch_labels = None
depends_on = None


def _drop_table_if_exists(table_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table(table_name):
        op.drop_table(table_name)


def upgrade() -> None:
    _drop_table_if_exists("orchestration_steps")
    _drop_table_if_exists("orchestration_runs")
    _drop_table_if_exists("portal_action_requests")
    _drop_table_if_exists("platform_impersonation_sessions")
    _drop_table_if_exists("operator_managed_topup_pack_overlays")


def downgrade() -> None:
    pass
