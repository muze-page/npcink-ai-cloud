"""remove the pre-GA permanent audio asset surface"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260715_0063"
down_revision = "20260715_0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("audio_assets"):
        return
    row_exists = bind.execute(sa.text("SELECT 1 FROM audio_assets LIMIT 1")).first()
    if row_exists is not None:
        raise RuntimeError(
            "pre-GA reset required: audio_assets contains rows; explicitly clear the "
            "legacy audio asset data and reset its orphaned artifact volume before retrying"
        )
    op.drop_table("audio_assets")


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("audio_assets"):
        return
    # Destructive pre-GA reset: this restores schema shape only, never discarded data.
    op.create_table(
        "audio_assets",
        sa.Column("asset_id", sa.String(191), primary_key=True),
        sa.Column("site_id", sa.String(191), sa.ForeignKey("sites.site_id"), nullable=False),
        sa.Column("source_artifact_id", sa.String(191)),
        sa.Column("source_run_id", sa.String(191)),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("storage_key", sa.String(191), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("duration_seconds", sa.Float, nullable=False, server_default="0"),
        sa.Column("byte_size", sa.Integer, nullable=False, server_default="0"),
        sa.Column("checksum", sa.String(128), nullable=False),
        sa.Column("source_content_hash", sa.String(128)),
        sa.Column("provider_id", sa.String(64)),
        sa.Column("model_id", sa.String(191)),
        sa.Column("trace_id", sa.String(64)),
        sa.Column("metadata_json", sa.JSON),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
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
    )
    for field in (
        "site_id",
        "source_artifact_id",
        "source_run_id",
        "status",
        "checksum",
        "source_content_hash",
        "provider_id",
        "model_id",
        "trace_id",
    ):
        op.create_index(f"ix_audio_assets_{field}", "audio_assets", [field])
