"""add AI credit ledger entries"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260612_0044"
down_revision = "20260612_0043"
branch_labels = None
depends_on = None

RATE_VERSION = "ai-credit-ledger-v1"


def upgrade() -> None:
    op.create_table(
        "credit_ledger_entries",
        sa.Column("ledger_entry_id", sa.String(length=191), nullable=False),
        sa.Column("account_id", sa.String(length=191), nullable=True),
        sa.Column("site_id", sa.String(length=191), nullable=True),
        sa.Column("subscription_id", sa.String(length=191), nullable=True),
        sa.Column("plan_version_id", sa.String(length=191), nullable=True),
        sa.Column("run_id", sa.String(length=191), nullable=True),
        sa.Column("provider_call_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False, server_default="consume"),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=191), nullable=False),
        sa.Column("credit_delta", sa.Float(), nullable=False, server_default="0"),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(length=32), nullable=False, server_default="credit"),
        sa.Column("rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("rate_unit", sa.String(length=64), nullable=True),
        sa.Column("rate_version", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("ledger_entry_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_credit_ledger_entries_idempotency"),
    )
    for index_name, columns in (
        ("ix_credit_ledger_entries_account_id", ["account_id"]),
        ("ix_credit_ledger_entries_site_id", ["site_id"]),
        ("ix_credit_ledger_entries_subscription_id", ["subscription_id"]),
        ("ix_credit_ledger_entries_plan_version_id", ["plan_version_id"]),
        ("ix_credit_ledger_entries_run_id", ["run_id"]),
        ("ix_credit_ledger_entries_provider_call_id", ["provider_call_id"]),
        ("ix_credit_ledger_entries_event_type", ["event_type"]),
        ("ix_credit_ledger_entries_source_type", ["source_type"]),
        ("ix_credit_ledger_entries_source_id", ["source_id"]),
        ("ix_credit_ledger_entries_rate_version", ["rate_version"]),
        ("ix_credit_ledger_entries_created_at", ["created_at"]),
    ):
        op.create_index(index_name, "credit_ledger_entries", columns)

    _backfill_usage_meter_entries()
    _backfill_site_knowledge_entries()


def downgrade() -> None:
    for index_name in (
        "ix_credit_ledger_entries_created_at",
        "ix_credit_ledger_entries_rate_version",
        "ix_credit_ledger_entries_source_id",
        "ix_credit_ledger_entries_source_type",
        "ix_credit_ledger_entries_event_type",
        "ix_credit_ledger_entries_provider_call_id",
        "ix_credit_ledger_entries_run_id",
        "ix_credit_ledger_entries_plan_version_id",
        "ix_credit_ledger_entries_subscription_id",
        "ix_credit_ledger_entries_site_id",
        "ix_credit_ledger_entries_account_id",
    ):
        op.drop_index(index_name, table_name="credit_ledger_entries")
    op.drop_table("credit_ledger_entries")


def _backfill_usage_meter_entries() -> None:
    op.execute(
        f"""
        WITH classified AS (
            SELECT
                id,
                account_id,
                site_id,
                subscription_id,
                plan_version_id,
                run_id,
                provider_call_id,
                meter_key,
                quantity,
                ability_family,
                execution_kind,
                event_kind,
                created_at,
                CASE
                    WHEN meter_key = 'runs' THEN 'runs'
                    WHEN meter_key = 'tokens_total' THEN 'tokens_total'
                    WHEN meter_key = 'provider_calls'
                        AND lower(coalesce(execution_kind, '')) LIKE '%search%'
                        THEN 'web_search'
                    WHEN meter_key = 'provider_calls'
                        AND (
                            lower(coalesce(execution_kind, '')) LIKE '%image%'
                            OR lower(coalesce(ability_family, '')) = 'vision'
                        )
                        THEN 'image_recommendation'
                    WHEN meter_key = 'provider_calls' THEN 'provider_calls_other'
                    ELSE ''
                END AS source_type,
                CASE
                    WHEN meter_key = 'runs' THEN 'run'
                    WHEN meter_key = 'tokens_total' THEN 'token'
                    WHEN meter_key = 'provider_calls' THEN 'call'
                    ELSE 'credit'
                END AS unit,
                CASE
                    WHEN meter_key = 'runs' THEN 1.0
                    WHEN meter_key = 'tokens_total' THEN 1.0
                    WHEN meter_key = 'provider_calls'
                        AND lower(coalesce(execution_kind, '')) LIKE '%search%'
                        THEN 5.0
                    WHEN meter_key = 'provider_calls'
                        AND (
                            lower(coalesce(execution_kind, '')) LIKE '%image%'
                            OR lower(coalesce(ability_family, '')) = 'vision'
                        )
                        THEN 3.0
                    WHEN meter_key = 'provider_calls' THEN 0.0
                    ELSE 0.0
                END AS rate,
                CASE
                    WHEN meter_key = 'tokens_total' THEN '1000_tokens'
                    ELSE NULL
                END AS rate_unit,
                CASE
                    WHEN meter_key = 'runs' THEN quantity
                    WHEN meter_key = 'tokens_total' THEN quantity / 1000.0
                    WHEN meter_key = 'provider_calls'
                        AND lower(coalesce(execution_kind, '')) LIKE '%search%'
                        THEN quantity * 5.0
                    WHEN meter_key = 'provider_calls'
                        AND (
                            lower(coalesce(execution_kind, '')) LIKE '%image%'
                            OR lower(coalesce(ability_family, '')) = 'vision'
                        )
                        THEN quantity * 3.0
                    WHEN meter_key = 'provider_calls' THEN 0.0
                    ELSE 0.0
                END AS credits
            FROM usage_meter_events
            WHERE meter_key IN ('runs', 'tokens_total', 'provider_calls')
        )
        INSERT INTO credit_ledger_entries (
            ledger_entry_id,
            account_id,
            site_id,
            subscription_id,
            plan_version_id,
            run_id,
            provider_call_id,
            event_type,
            source_type,
            source_id,
            credit_delta,
            quantity,
            unit,
            rate,
            rate_unit,
            rate_version,
            idempotency_key,
            metadata_json,
            created_at
        )
        SELECT
            'cle_usage_' || id::text,
            account_id,
            site_id,
            subscription_id,
            plan_version_id,
            run_id,
            provider_call_id,
            'consume',
            source_type,
            id::text,
            -credits,
            quantity,
            unit,
            rate,
            rate_unit,
            '{RATE_VERSION}',
            'usage_meter_event:' || id::text,
            json_build_object(
                'usage_meter_event_id', id,
                'meter_key', meter_key,
                'event_kind', event_kind,
                'ability_family', ability_family,
                'execution_kind', execution_kind
            ),
            created_at
        FROM classified
        WHERE source_type <> ''
        ON CONFLICT (idempotency_key) DO NOTHING
        """
    )


def _backfill_site_knowledge_entries() -> None:
    op.execute(
        f"""
        INSERT INTO credit_ledger_entries (
            ledger_entry_id,
            account_id,
            site_id,
            subscription_id,
            plan_version_id,
            run_id,
            provider_call_id,
            event_type,
            source_type,
            source_id,
            credit_delta,
            quantity,
            unit,
            rate,
            rate_unit,
            rate_version,
            idempotency_key,
            metadata_json,
            created_at
        )
        SELECT
            'cle_ski_doc_' || metric.id::text,
            coalesce(metric.account_id, run.account_id),
            metric.site_id,
            coalesce(metric.subscription_id, run.subscription_id),
            run.plan_version_id,
            metric.run_id,
            NULL,
            'consume',
            'vector_documents',
            metric.run_id,
            -(metric.indexed_documents * 2.0),
            metric.indexed_documents,
            'document',
            2.0,
            NULL,
            '{RATE_VERSION}',
            concat('site_knowledge_index', chr(58), metric.run_id, chr(58), 'vector_documents'),
            json_build_object(
                'site_knowledge_index_metric_id', metric.id,
                'sync_mode', metric.sync_mode,
                'status', metric.status
            ),
            coalesce(metric.finished_at, metric.created_at)
        FROM site_knowledge_index_job_metrics metric
        LEFT JOIN run_records run ON run.run_id = metric.run_id
        WHERE metric.indexed_documents > 0
        ON CONFLICT (idempotency_key) DO NOTHING
        """
    )
    op.execute(
        f"""
        INSERT INTO credit_ledger_entries (
            ledger_entry_id,
            account_id,
            site_id,
            subscription_id,
            plan_version_id,
            run_id,
            provider_call_id,
            event_type,
            source_type,
            source_id,
            credit_delta,
            quantity,
            unit,
            rate,
            rate_unit,
            rate_version,
            idempotency_key,
            metadata_json,
            created_at
        )
        SELECT
            'cle_ski_chunk_' || metric.id::text,
            coalesce(metric.account_id, run.account_id),
            metric.site_id,
            coalesce(metric.subscription_id, run.subscription_id),
            run.plan_version_id,
            metric.run_id,
            NULL,
            'consume',
            'vector_chunks',
            metric.run_id,
            -(metric.indexed_chunks * 0.1),
            metric.indexed_chunks,
            'chunk',
            0.1,
            NULL,
            '{RATE_VERSION}',
            concat('site_knowledge_index', chr(58), metric.run_id, chr(58), 'vector_chunks'),
            json_build_object(
                'site_knowledge_index_metric_id', metric.id,
                'sync_mode', metric.sync_mode,
                'status', metric.status
            ),
            coalesce(metric.finished_at, metric.created_at)
        FROM site_knowledge_index_job_metrics metric
        LEFT JOIN run_records run ON run.run_id = metric.run_id
        WHERE metric.indexed_chunks > 0
        ON CONFLICT (idempotency_key) DO NOTHING
        """
    )
