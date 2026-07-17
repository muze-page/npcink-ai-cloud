"""add site-scoped media artifact delivery evidence"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260715_0062"
down_revision = "20260714_0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_artifact_deliveries",
        sa.Column("delivery_id", sa.String(191), primary_key=True),
        sa.Column(
            "artifact_id",
            sa.String(191),
            sa.ForeignKey("media_artifacts.artifact_id"),
            nullable=False,
        ),
        sa.Column("site_id", sa.String(191), nullable=False),
        sa.Column("expected_byte_size", sa.Integer, nullable=False),
        sa.Column("expected_checksum", sa.String(128), nullable=False),
        sa.Column("pull_trace_id", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_byte_size", sa.Integer),
        sa.Column("completed_checksum", sa.String(128)),
        sa.Column("ack_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("acked_at", sa.DateTime(timezone=True)),
        sa.Column("ack_idempotency_key", sa.String(128)),
        sa.Column("ack_request_fingerprint", sa.String(64)),
        sa.Column("ack_trace_id", sa.String(64)),
        sa.Column("received_byte_size", sa.Integer),
        sa.Column("received_checksum", sa.String(128)),
        sa.Column("byte_size_verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("checksum_verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("retention_expires_at_before", sa.DateTime(timezone=True)),
        sa.Column("retention_expires_at_after", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "site_id",
            "ack_idempotency_key",
            name="uq_media_artifact_deliveries_site_ack_key",
        ),
    )
    for field in (
        "artifact_id",
        "site_id",
        "pull_trace_id",
        "started_at",
        "ack_deadline_at",
        "ack_trace_id",
    ):
        op.create_index(
            f"ix_media_artifact_deliveries_{field}",
            "media_artifact_deliveries",
            [field],
        )


def downgrade() -> None:
    op.drop_table("media_artifact_deliveries")
