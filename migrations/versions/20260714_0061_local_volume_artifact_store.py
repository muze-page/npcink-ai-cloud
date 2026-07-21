"""reset media artifacts and audio assets for local-volume byte storage"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260714_0061"
down_revision = "20260714_0060"
branch_labels = None
depends_on = None


def _drop(name: str) -> None:
    if sa.inspect(op.get_bind()).has_table(name):
        op.drop_table(name)


def upgrade() -> None:
    _drop("media_derivative_artifacts")
    _drop("media_artifacts")
    _drop("audio_assets")
    op.create_table(
        "media_artifacts",
        sa.Column("artifact_id", sa.String(191), primary_key=True),
        sa.Column("run_id", sa.String(191), sa.ForeignKey("run_records.run_id"), nullable=False),
        sa.Column("site_id", sa.String(191), nullable=False),
        sa.Column("media_kind", sa.String(16), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer, nullable=False),
        sa.Column("checksum", sa.String(128), nullable=False),
        sa.Column("storage_key", sa.String(191), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("width", sa.Integer, nullable=False, server_default="0"),
        sa.Column("height", sa.Integer, nullable=False, server_default="0"),
        sa.Column("processing_warnings_json", sa.JSON),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purged_at", sa.DateTime(timezone=True)),
        sa.Column("purge_attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("purge_last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("purge_next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("purge_last_error_code", sa.String(64)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    for name, cols in (
        ("ix_media_artifacts_run_id", ["run_id"]),
        ("ix_media_artifacts_site_id", ["site_id"]),
        ("ix_media_artifacts_status", ["status"]),
        ("ix_media_artifacts_expires_at", ["expires_at"]),
        ("ix_media_artifacts_purge_next_attempt_at", ["purge_next_attempt_at"]),
    ):
        op.create_index(name, "media_artifacts", cols)
    _create_audio_assets(new=True)


def _create_audio_assets(*, new: bool) -> None:
    columns: list[sa.Column] = [
        sa.Column("asset_id", sa.String(191), primary_key=True),
        sa.Column("site_id", sa.String(191), sa.ForeignKey("sites.site_id"), nullable=False),
        sa.Column("source_artifact_id", sa.String(191)),
        sa.Column("source_run_id", sa.String(191)),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
    ]
    if new:
        columns += [
            sa.Column("storage_key", sa.String(191), nullable=False),
            sa.Column("content_type", sa.String(64), nullable=False),
        ]
    else:
        columns += [
            sa.Column("storage_ref", sa.String(512), nullable=False),
            sa.Column("blob_data", sa.LargeBinary, nullable=False),
            sa.Column("mime_type", sa.String(64), nullable=False),
        ]
    columns += [
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("duration_seconds", sa.Float, nullable=False, server_default="0"),
        sa.Column(
            "byte_size" if new else "filesize_bytes", sa.Integer, nullable=False, server_default="0"
        ),
        sa.Column("checksum", sa.String(128), nullable=False),
        sa.Column("source_content_hash", sa.String(128)),
        sa.Column("provider_id", sa.String(64)),
        sa.Column("model_id", sa.String(191)),
        sa.Column("trace_id", sa.String(64)),
        sa.Column("metadata_json", sa.JSON),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]
    op.create_table("audio_assets", *columns)
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


def downgrade() -> None:
    _drop("media_artifacts")
    _drop("audio_assets")
    # Destructive pre-GA reset: downgrade restores legacy shape, never discarded bytes.
    op.create_table(
        "media_derivative_artifacts",
        sa.Column("artifact_id", sa.String(191), primary_key=True),
        sa.Column("run_id", sa.String(191), sa.ForeignKey("run_records.run_id"), nullable=False),
        sa.Column("site_id", sa.String(191), nullable=False),
        sa.Column("storage_ref", sa.String(512), nullable=False),
        sa.Column("blob_data", sa.LargeBinary, nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=False),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("width", sa.Integer, nullable=False, server_default="0"),
        sa.Column("height", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filesize_bytes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("checksum", sa.String(128), nullable=False),
        sa.Column("source_media_type", sa.String(16), nullable=False, server_default="image"),
        sa.Column("processing_warnings_json", sa.JSON),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purged_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_mda_run_id", "media_derivative_artifacts", ["run_id"])
    op.create_index("ix_mda_site_id", "media_derivative_artifacts", ["site_id"])
    op.create_index(
        "ix_mda_expires_at",
        "media_derivative_artifacts",
        ["expires_at"],
        postgresql_where=sa.text("purged_at IS NULL"),
    )
    _create_audio_assets(new=False)
