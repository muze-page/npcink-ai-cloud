"""recognition snapshot publications"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260403_0019"
down_revision = "20260403_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recognition_snapshot_publications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("revision", sa.String(length=191), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("records_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_keys_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source_run_ids_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("record_keys_json", sa.JSON(), nullable=False, server_default="[]"),
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
        sa.UniqueConstraint("revision", name="uq_recognition_snapshot_publications_revision"),
    )
    op.create_index(
        "ix_recognition_snapshot_publications_revision",
        "recognition_snapshot_publications",
        ["revision"],
    )
    op.create_index(
        "ix_recognition_snapshot_publications_checksum",
        "recognition_snapshot_publications",
        ["checksum"],
    )
    op.create_index(
        "ix_recognition_snapshot_publications_generated_at",
        "recognition_snapshot_publications",
        ["generated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recognition_snapshot_publications_generated_at",
        table_name="recognition_snapshot_publications",
    )
    op.drop_index(
        "ix_recognition_snapshot_publications_checksum",
        table_name="recognition_snapshot_publications",
    )
    op.drop_index(
        "ix_recognition_snapshot_publications_revision",
        table_name="recognition_snapshot_publications",
    )
    op.drop_table("recognition_snapshot_publications")
