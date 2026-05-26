"""recognition model annotations"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260330_0015"
down_revision = "20260330_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recognition_model_annotations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=191), nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("manual_tags_json", sa.JSON(), nullable=False, server_default="[]"),
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
        sa.UniqueConstraint(
            "provider_id",
            "model_id",
            name="uq_recognition_model_annotations_provider_model",
        ),
    )
    op.create_index(
        "ix_recognition_model_annotations_provider_id",
        "recognition_model_annotations",
        ["provider_id"],
    )
    op.create_index(
        "ix_recognition_model_annotations_model_id",
        "recognition_model_annotations",
        ["model_id"],
    )
    op.create_index(
        "ix_recognition_model_annotations_review_status",
        "recognition_model_annotations",
        ["review_status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recognition_model_annotations_review_status",
        table_name="recognition_model_annotations",
    )
    op.drop_index(
        "ix_recognition_model_annotations_model_id",
        table_name="recognition_model_annotations",
    )
    op.drop_index(
        "ix_recognition_model_annotations_provider_id",
        table_name="recognition_model_annotations",
    )
    op.drop_table("recognition_model_annotations")
