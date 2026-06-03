"""media_derivative_job_metrics

Revision ID: 20260603_0036
Revises: 20260602_0035
Create Date: 2026-06-03

"""

import sqlalchemy as sa
from alembic import op

revision = "20260603_0036"
down_revision = "20260602_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("media_derivative_job_metrics"):
        return

    op.create_table(
        "media_derivative_job_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=191), nullable=False),
        sa.Column("site_id", sa.String(length=191), nullable=False),
        sa.Column("account_id", sa.String(length=191), nullable=True),
        sa.Column("subscription_id", sa.String(length=191), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("target_format", sa.String(length=16), nullable=False),
        sa.Column("output_format", sa.String(length=16), nullable=True),
        sa.Column(
            "source_media_type",
            sa.String(length=16),
            nullable=False,
            server_default="image",
        ),
        sa.Column("source_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_width", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_height", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_width", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_height", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("compression_ratio", sa.Float(), nullable=False, server_default="0"),
        sa.Column("queue_wait_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processing_duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("watermark_applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("warnings_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("artifact_id", sa.String(length=191), nullable=True),
        sa.Column("artifact_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("artifact_download_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("artifact_last_downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["run_records.run_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_media_derivative_job_metrics_run"),
    )
    for index_name, columns in (
        ("ix_mdjm_run_id", ["run_id"]),
        ("ix_mdjm_site_id", ["site_id"]),
        ("ix_mdjm_account_id", ["account_id"]),
        ("ix_mdjm_subscription_id", ["subscription_id"]),
        ("ix_mdjm_status", ["status"]),
        ("ix_mdjm_error_code", ["error_code"]),
        ("ix_mdjm_target_format", ["target_format"]),
        ("ix_mdjm_output_format", ["output_format"]),
        ("ix_mdjm_source_media_type", ["source_media_type"]),
        ("ix_mdjm_watermark_applied", ["watermark_applied"]),
        ("ix_mdjm_artifact_id", ["artifact_id"]),
        ("ix_mdjm_created_at", ["created_at"]),
        ("ix_mdjm_finished_at", ["finished_at"]),
    ):
        op.create_index(index_name, "media_derivative_job_metrics", columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("media_derivative_job_metrics"):
        op.drop_table("media_derivative_job_metrics")
