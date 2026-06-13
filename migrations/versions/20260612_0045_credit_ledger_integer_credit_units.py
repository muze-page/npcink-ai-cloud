"""round AI credit ledger consumption to integer units"""

from __future__ import annotations

from alembic import op

revision = "20260612_0045"
down_revision = "20260612_0044"
branch_labels = None
depends_on = None

RATE_VERSION_V1 = "ai-credit-ledger-v1"
RATE_VERSION_V2 = "ai-credit-ledger-v2"


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE credit_ledger_entries
        SET
            credit_delta = -greatest(0.0, ceil(coalesce(quantity, 0.0) / 1000.0)),
            rate = 1.0,
            rate_unit = '1000_tokens_rounded_up',
            rate_version = '{RATE_VERSION_V2}'
        WHERE event_type = 'consume'
            AND source_type = 'tokens_total'
        """
    )
    op.execute(
        f"""
        UPDATE credit_ledger_entries
        SET
            credit_delta = -greatest(0.0, ceil(coalesce(quantity, 0.0) / 10.0)),
            rate = 1.0,
            rate_unit = '10_chunks',
            rate_version = '{RATE_VERSION_V2}'
        WHERE event_type = 'consume'
            AND source_type = 'vector_chunks'
        """
    )
    op.execute(
        f"""
        UPDATE credit_ledger_entries
        SET rate_version = '{RATE_VERSION_V2}'
        WHERE rate_version = '{RATE_VERSION_V1}'
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE credit_ledger_entries
        SET
            credit_delta = -(coalesce(quantity, 0.0) / 1000.0),
            rate = 1.0,
            rate_unit = '1000_tokens',
            rate_version = '{RATE_VERSION_V1}'
        WHERE event_type = 'consume'
            AND source_type = 'tokens_total'
        """
    )
    op.execute(
        f"""
        UPDATE credit_ledger_entries
        SET
            credit_delta = -(coalesce(quantity, 0.0) * 0.1),
            rate = 0.1,
            rate_unit = NULL,
            rate_version = '{RATE_VERSION_V1}'
        WHERE event_type = 'consume'
            AND source_type = 'vector_chunks'
        """
    )
    op.execute(
        f"""
        UPDATE credit_ledger_entries
        SET rate_version = '{RATE_VERSION_V1}'
        WHERE rate_version = '{RATE_VERSION_V2}'
        """
    )
