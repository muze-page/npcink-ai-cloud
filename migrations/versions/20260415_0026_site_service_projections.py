"""store addon service projections for projection-first reads"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260415_0026"
down_revision = "20260413_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_service_projections",
        sa.Column("projection_id", sa.String(length=255), primary_key=True, nullable=False),
        sa.Column("site_id", sa.String(length=191), nullable=False),
        sa.Column("projection_kind", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("fresh_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_revision", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("generation_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_site_service_projections_site_id",
        "site_service_projections",
        ["site_id"],
    )
    op.create_index(
        "ix_site_service_projections_projection_kind",
        "site_service_projections",
        ["projection_kind"],
    )
    op.create_index(
        "ix_site_service_projections_generated_at",
        "site_service_projections",
        ["generated_at"],
    )
    op.create_index(
        "ix_site_service_projections_fresh_until",
        "site_service_projections",
        ["fresh_until"],
    )
    op.create_index(
        "ix_site_service_projections_last_error_at",
        "site_service_projections",
        ["last_error_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_site_service_projections_last_error_at", table_name="site_service_projections")
    op.drop_index("ix_site_service_projections_fresh_until", table_name="site_service_projections")
    op.drop_index("ix_site_service_projections_generated_at", table_name="site_service_projections")
    op.drop_index("ix_site_service_projections_projection_kind", table_name="site_service_projections")
    op.drop_index("ix_site_service_projections_site_id", table_name="site_service_projections")
    op.drop_table("site_service_projections")
