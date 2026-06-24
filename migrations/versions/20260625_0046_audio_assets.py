"""add cloud-hosted audio assets"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260625_0046"
down_revision = "20260612_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("audio_assets"):
        return

    op.create_table(
        "audio_assets",
        sa.Column("asset_id", sa.String(length=191), nullable=False),
        sa.Column("site_id", sa.String(length=191), nullable=False),
        sa.Column("source_artifact_id", sa.String(length=191), nullable=True),
        sa.Column("source_run_id", sa.String(length=191), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("storage_ref", sa.String(length=512), nullable=False),
        sa.Column("blob_data", sa.LargeBinary(), nullable=False),
        sa.Column("mime_type", sa.String(length=64), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("filesize_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("source_content_hash", sa.String(length=128), nullable=True),
        sa.Column("provider_id", sa.String(length=64), nullable=True),
        sa.Column("model_id", sa.String(length=191), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["site_id"], ["sites.site_id"]),
        sa.PrimaryKeyConstraint("asset_id"),
    )
    for index_name, columns in (
        ("ix_audio_assets_site_id", ["site_id"]),
        ("ix_audio_assets_source_artifact_id", ["source_artifact_id"]),
        ("ix_audio_assets_source_run_id", ["source_run_id"]),
        ("ix_audio_assets_status", ["status"]),
        ("ix_audio_assets_checksum", ["checksum"]),
        ("ix_audio_assets_source_content_hash", ["source_content_hash"]),
        ("ix_audio_assets_provider_id", ["provider_id"]),
        ("ix_audio_assets_model_id", ["model_id"]),
        ("ix_audio_assets_trace_id", ["trace_id"]),
    ):
        op.create_index(index_name, "audio_assets", columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("audio_assets"):
        op.drop_table("audio_assets")
