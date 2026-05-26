"""catalog model annotations"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260330_0014"
down_revision = "20260327_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_model_annotations",
        sa.Column(
            "model_id",
            sa.String(length=191),
            sa.ForeignKey("catalog_models.model_id"),
            primary_key=True,
        ),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("recommended", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cost_tier", sa.String(length=32), nullable=True),
        sa.Column("visibility", sa.String(length=32), nullable=False, server_default="default"),
        sa.Column("badges_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("operator_notes", sa.Text(), nullable=True),
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
    )
    op.create_index(
        "ix_catalog_model_annotations_provider_id",
        "catalog_model_annotations",
        ["provider_id"],
    )
    op.create_index(
        "ix_catalog_model_annotations_recommended",
        "catalog_model_annotations",
        ["recommended"],
    )
    op.create_index(
        "ix_catalog_model_annotations_cost_tier",
        "catalog_model_annotations",
        ["cost_tier"],
    )
    op.create_index(
        "ix_catalog_model_annotations_visibility",
        "catalog_model_annotations",
        ["visibility"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_catalog_model_annotations_visibility",
        table_name="catalog_model_annotations",
    )
    op.drop_index(
        "ix_catalog_model_annotations_cost_tier",
        table_name="catalog_model_annotations",
    )
    op.drop_index(
        "ix_catalog_model_annotations_recommended",
        table_name="catalog_model_annotations",
    )
    op.drop_index(
        "ix_catalog_model_annotations_provider_id",
        table_name="catalog_model_annotations",
    )
    op.drop_table("catalog_model_annotations")
