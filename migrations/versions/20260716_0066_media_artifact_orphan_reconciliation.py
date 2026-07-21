"""add durable media artifact orphan reconciliation"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260716_0066"
down_revision = "20260715_0065"
branch_labels = None
depends_on = None

_PASSES = "media_artifact_reconciliation_passes"
_CANDIDATES = "media_artifact_orphan_candidates"


def upgrade() -> None:
    op.create_table(
        _PASSES,
        sa.Column("pass_id", sa.String(64), primary_key=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("active_slot", sa.String(16), nullable=True),
        sa.Column("head_slot", sa.String(16), nullable=True),
        sa.Column("scan_claim_id", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("previous_completed_pass_id", sa.String(64), nullable=True),
        sa.Column("store_generation", sa.String(64), nullable=False),
        sa.Column("next_cursor", sa.String(191), nullable=True),
        sa.Column("last_storage_key", sa.String(191), nullable=True),
        sa.Column("store_examined", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("referenced_present", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("orphan_observed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("orphan_deferred", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("orphan_eligible", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("db_available_examined", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("referenced_missing", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["previous_completed_pass_id"],
            [f"{_PASSES}.pass_id"],
            name="fk_media_artifact_reconciliation_passes_previous",
        ),
        sa.UniqueConstraint(
            "active_slot",
            name="uq_media_artifact_reconciliation_passes_active_slot",
        ),
        sa.UniqueConstraint(
            "head_slot",
            name="uq_media_artifact_reconciliation_passes_head_slot",
        ),
        sa.CheckConstraint(
            "state IN ('running', 'completed', 'abandoned')",
            name="ck_media_artifact_reconciliation_passes_state",
        ),
        sa.CheckConstraint(
            "active_slot IS NULL OR active_slot = 'active'",
            name="ck_media_artifact_reconciliation_passes_active_slot_value",
        ),
        sa.CheckConstraint(
            "head_slot IS NULL OR head_slot = 'head'",
            name="ck_media_artifact_reconciliation_passes_head_slot_value",
        ),
        sa.CheckConstraint(
            "((scan_claim_id IS NULL AND lease_expires_at IS NULL) OR "
            "(scan_claim_id IS NOT NULL AND lease_expires_at IS NOT NULL))",
            name="ck_media_artifact_reconciliation_passes_claim_pair",
        ),
        sa.CheckConstraint(
            "((state = 'running' AND active_slot = 'active' AND head_slot IS NULL "
            "AND scan_claim_id IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND completed_at IS NULL) OR "
            "(state = 'completed' AND active_slot IS NULL AND scan_claim_id IS NULL "
            "AND lease_expires_at IS NULL AND completed_at IS NOT NULL) OR "
            "(state = 'abandoned' AND active_slot IS NULL AND head_slot IS NULL "
            "AND scan_claim_id IS NULL AND lease_expires_at IS NULL "
            "AND completed_at IS NULL))",
            name="ck_media_artifact_reconciliation_passes_lifecycle",
        ),
    )
    op.create_index(
        "ix_media_artifact_reconciliation_passes_state",
        _PASSES,
        ["state"],
    )
    op.create_index(
        "ix_media_artifact_reconciliation_passes_lease_expires_at",
        _PASSES,
        ["lease_expires_at"],
    )
    op.create_index(
        "ix_media_artifact_recon_passes_previous_id",
        _PASSES,
        ["previous_completed_pass_id"],
    )
    op.create_index(
        "ix_media_artifact_reconciliation_passes_store_generation",
        _PASSES,
        ["store_generation"],
    )
    op.create_index(
        "ix_media_artifact_reconciliation_passes_started_at",
        _PASSES,
        ["started_at"],
    )
    op.create_index(
        "ix_media_artifact_reconciliation_passes_completed_at",
        _PASSES,
        ["completed_at"],
    )

    op.create_table(
        _CANDIDATES,
        sa.Column("storage_key", sa.String(191), primary_key=True),
        sa.Column("object_version", sa.String(64), nullable=False),
        sa.Column("store_generation", sa.String(64), nullable=False),
        sa.Column("first_pass_id", sa.String(64), nullable=False),
        sa.Column("last_pass_id", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("claim_id", sa.String(64), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["first_pass_id"],
            [f"{_PASSES}.pass_id"],
            name="fk_media_artifact_orphan_candidates_first_pass",
        ),
        sa.ForeignKeyConstraint(
            ["last_pass_id"],
            [f"{_PASSES}.pass_id"],
            name="fk_media_artifact_orphan_candidates_last_pass",
        ),
        sa.CheckConstraint(
            "state IN ('observed', 'eligible', 'claimed', 'retry_wait', "
            "'deleted', 'invalidated')",
            name="ck_media_artifact_orphan_candidates_state",
        ),
        sa.CheckConstraint(
            "((claim_id IS NULL AND claim_expires_at IS NULL) OR "
            "(claim_id IS NOT NULL AND claim_expires_at IS NOT NULL))",
            name="ck_media_artifact_orphan_candidates_claim_pair",
        ),
        sa.CheckConstraint(
            "((state = 'claimed' AND claim_id IS NOT NULL AND claim_expires_at IS NOT NULL) "
            "OR (state <> 'claimed' AND claim_id IS NULL AND claim_expires_at IS NULL))",
            name="ck_media_artifact_orphan_candidates_claim_state",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_media_artifact_orphan_candidates_attempt_count",
        ),
        sa.CheckConstraint(
            "((state = 'retry_wait' AND retry_at IS NOT NULL "
            "AND last_error_code IS NOT NULL) OR "
            "(state <> 'retry_wait' AND retry_at IS NULL "
            "AND last_error_code IS NULL))",
            name="ck_media_artifact_orphan_candidates_retry_state",
        ),
        sa.CheckConstraint(
            "((state IN ('deleted', 'invalidated') AND resolved_at IS NOT NULL) OR "
            "(state NOT IN ('deleted', 'invalidated') AND resolved_at IS NULL))",
            name="ck_media_artifact_orphan_candidates_resolution",
        ),
    )
    op.create_index(
        "ix_media_artifact_orphan_candidates_store_generation",
        _CANDIDATES,
        ["store_generation"],
    )
    op.create_index(
        "ix_media_artifact_orphan_candidates_first_pass_id",
        _CANDIDATES,
        ["first_pass_id"],
    )
    op.create_index(
        "ix_media_artifact_orphan_candidates_last_pass_id",
        _CANDIDATES,
        ["last_pass_id"],
    )
    op.create_index(
        "ix_media_artifact_orphan_candidates_state",
        _CANDIDATES,
        ["state"],
    )
    op.create_index(
        "ix_media_artifact_orphan_candidates_claim_expires_at",
        _CANDIDATES,
        ["claim_expires_at"],
    )
    op.create_index(
        "ix_media_artifact_orphan_candidates_retry_at",
        _CANDIDATES,
        ["retry_at"],
    )
    op.create_index(
        "ix_media_artifact_orphan_candidates_cleanup",
        _CANDIDATES,
        ["state", "retry_at", "claim_expires_at"],
    )


def downgrade() -> None:
    op.drop_table(_CANDIDATES)
    op.drop_table(_PASSES)
