"""add durable Portal mutation idempotency receipts"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260717_0067"
down_revision = "20260716_0066"
branch_labels = None
depends_on = None

_TABLE = "portal_mutation_idempotency_receipts"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("receipt_id", sa.String(length=64), primary_key=True),
        sa.Column("principal_id", sa.String(length=191), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_method", sa.String(length=16), nullable=False),
        sa.Column("request_path", sa.String(length=512), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("claim_token", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body_ciphertext", sa.Text(), nullable=True),
        sa.Column("retention_ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["principals.principal_id"],
            name="fk_portal_mutation_idempotency_principal",
        ),
        sa.UniqueConstraint(
            "principal_id",
            "idempotency_key",
            name="uq_portal_mutation_idempotency_principal_key",
        ),
        sa.CheckConstraint(
            "state IN ('processing', 'completed')",
            name="ck_portal_mutation_idempotency_state",
        ),
        sa.CheckConstraint(
            "retention_ttl_seconds > 0",
            name="ck_portal_mutation_idempotency_ttl_positive",
        ),
        sa.CheckConstraint(
            "response_status IS NULL OR "
            "(response_status >= 100 AND response_status <= 599)",
            name="ck_portal_mutation_idempotency_response_status",
        ),
        sa.CheckConstraint(
            "((state = 'processing' AND claim_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND response_status IS NULL "
            "AND response_body_ciphertext IS NULL AND completed_at IS NULL) OR "
            "(state = 'completed' AND claim_token IS NULL "
            "AND lease_expires_at IS NULL AND response_status IS NOT NULL "
            "AND response_body_ciphertext IS NOT NULL AND completed_at IS NOT NULL))",
            name="ck_portal_mutation_idempotency_lifecycle",
        ),
    )
    op.create_index(
        "ix_portal_mutation_idempotency_principal_id",
        _TABLE,
        ["principal_id"],
    )
    op.create_index(
        "ix_portal_mutation_idempotency_expiry",
        _TABLE,
        ["expires_at", "receipt_id"],
    )
    op.create_index(
        "ix_portal_mutation_idempotency_processing_lease",
        _TABLE,
        ["state", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_table(_TABLE)
