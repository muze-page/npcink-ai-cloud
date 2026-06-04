"""site knowledge observability metrics"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260603_0039"
down_revision = "20260603_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_knowledge_index_job_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=191), nullable=False),
        sa.Column("site_id", sa.String(length=191), nullable=False),
        sa.Column("account_id", sa.String(length=191), nullable=True),
        sa.Column("subscription_id", sa.String(length=191), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("sync_mode", sa.String(length=32), nullable=False),
        sa.Column("accepted_documents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indexed_documents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indexed_chunks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_documents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_entries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding_provider", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=191), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("vector_backend", sa.String(length=64), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["run_records.run_id"]),
        sa.ForeignKeyConstraint(["site_id"], ["sites.site_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_site_knowledge_index_job_metrics_run"),
    )
    for index_name, columns in (
        ("ix_ski_jobs_run_id", ["run_id"]),
        ("ix_ski_jobs_site_id", ["site_id"]),
        ("ix_ski_jobs_account_id", ["account_id"]),
        ("ix_ski_jobs_subscription_id", ["subscription_id"]),
        ("ix_ski_jobs_status", ["status"]),
        ("ix_ski_jobs_error_code", ["error_code"]),
        ("ix_ski_jobs_sync_mode", ["sync_mode"]),
        ("ix_ski_jobs_embedding_provider", ["embedding_provider"]),
        ("ix_ski_jobs_embedding_model", ["embedding_model"]),
        ("ix_ski_jobs_vector_backend", ["vector_backend"]),
        ("ix_ski_jobs_created_at", ["created_at"]),
        ("ix_ski_jobs_finished_at", ["finished_at"]),
    ):
        op.create_index(index_name, "site_knowledge_index_job_metrics", columns)

    op.create_table(
        "site_knowledge_search_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=191), nullable=False),
        sa.Column("site_id", sa.String(length=191), nullable=False),
        sa.Column("account_id", sa.String(length=191), nullable=True),
        sa.Column("subscription_id", sa.String(length=191), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("intent", sa.String(length=64), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("no_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("top1_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("query_hash", sa.String(length=128), nullable=True),
        sa.Column("query_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_results", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("filter_json", sa.JSON(), nullable=True),
        sa.Column("embedding_provider", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=191), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("vector_backend", sa.String(length=64), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["run_records.run_id"]),
        sa.ForeignKeyConstraint(["site_id"], ["sites.site_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_site_knowledge_search_metrics_run"),
    )
    for index_name, columns in (
        ("ix_sks_metrics_run_id", ["run_id"]),
        ("ix_sks_metrics_site_id", ["site_id"]),
        ("ix_sks_metrics_account_id", ["account_id"]),
        ("ix_sks_metrics_subscription_id", ["subscription_id"]),
        ("ix_sks_metrics_status", ["status"]),
        ("ix_sks_metrics_error_code", ["error_code"]),
        ("ix_sks_metrics_intent", ["intent"]),
        ("ix_sks_metrics_no_hit", ["no_hit"]),
        ("ix_sks_metrics_query_hash", ["query_hash"]),
        ("ix_sks_metrics_embedding_provider", ["embedding_provider"]),
        ("ix_sks_metrics_embedding_model", ["embedding_model"]),
        ("ix_sks_metrics_vector_backend", ["vector_backend"]),
        ("ix_sks_metrics_created_at", ["created_at"]),
        ("ix_sks_metrics_finished_at", ["finished_at"]),
    ):
        op.create_index(index_name, "site_knowledge_search_metrics", columns)

    op.create_table(
        "site_knowledge_index_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("site_id", sa.String(length=191), nullable=False),
        sa.Column("run_id", sa.String(length=191), nullable=True),
        sa.Column("document_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("post_type_counts_json", sa.JSON(), nullable=True),
        sa.Column("source_type_counts_json", sa.JSON(), nullable=True),
        sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding_provider", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=191), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("vector_backend", sa.String(length=64), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["site_id"], ["sites.site_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for index_name, columns in (
        ("ix_ski_snapshots_site_id", ["site_id"]),
        ("ix_ski_snapshots_run_id", ["run_id"]),
        ("ix_ski_snapshots_last_indexed_at", ["last_indexed_at"]),
        ("ix_ski_snapshots_embedding_provider", ["embedding_provider"]),
        ("ix_ski_snapshots_embedding_model", ["embedding_model"]),
        ("ix_ski_snapshots_vector_backend", ["vector_backend"]),
        ("ix_ski_snapshots_captured_at", ["captured_at"]),
    ):
        op.create_index(index_name, "site_knowledge_index_snapshots", columns)


def downgrade() -> None:
    op.drop_table("site_knowledge_index_snapshots")
    op.drop_table("site_knowledge_search_metrics")
    op.drop_table("site_knowledge_index_job_metrics")
