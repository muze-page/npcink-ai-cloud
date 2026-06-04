"""site knowledge index tables"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260603_0037"
down_revision = "20260603_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_knowledge_documents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("site_id", sa.String(length=191), sa.ForeignKey("sites.site_id"), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("post_type", sa.String(length=64), nullable=False),
        sa.Column("post_status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("modified_gmt", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("last_sync_run_id", sa.String(length=191), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "last_indexed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("site_id", "post_id", name="uq_site_knowledge_documents_site_post"),
    )
    op.create_index("ix_site_knowledge_documents_site_id", "site_knowledge_documents", ["site_id"])
    op.create_index("ix_site_knowledge_documents_post_id", "site_knowledge_documents", ["post_id"])
    op.create_index(
        "ix_site_knowledge_documents_post_type",
        "site_knowledge_documents",
        ["post_type"],
    )
    op.create_index(
        "ix_site_knowledge_documents_post_status",
        "site_knowledge_documents",
        ["post_status"],
    )
    op.create_index(
        "ix_site_knowledge_documents_content_hash",
        "site_knowledge_documents",
        ["content_hash"],
    )
    op.create_index(
        "ix_site_knowledge_documents_last_sync_run_id",
        "site_knowledge_documents",
        ["last_sync_run_id"],
    )
    op.create_index(
        "ix_site_knowledge_documents_last_indexed_at",
        "site_knowledge_documents",
        ["last_indexed_at"],
    )

    op.create_table(
        "site_knowledge_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("site_id", sa.String(length=191), sa.ForeignKey("sites.site_id"), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("post_type", sa.String(length=64), nullable=False),
        sa.Column("post_status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding_json", sa.JSON(), nullable=False),
        sa.Column("embedding_model", sa.String(length=191), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "site_id",
            "post_id",
            "chunk_index",
            name="uq_site_knowledge_chunks_site_post_chunk",
        ),
    )
    op.create_index("ix_site_knowledge_chunks_site_id", "site_knowledge_chunks", ["site_id"])
    op.create_index("ix_site_knowledge_chunks_post_id", "site_knowledge_chunks", ["post_id"])
    op.create_index("ix_site_knowledge_chunks_post_type", "site_knowledge_chunks", ["post_type"])
    op.create_index(
        "ix_site_knowledge_chunks_post_status",
        "site_knowledge_chunks",
        ["post_status"],
    )
    op.create_index(
        "ix_site_knowledge_chunks_content_hash",
        "site_knowledge_chunks",
        ["content_hash"],
    )
    op.create_index("ix_site_knowledge_chunks_indexed_at", "site_knowledge_chunks", ["indexed_at"])


def downgrade() -> None:
    op.drop_index("ix_site_knowledge_chunks_indexed_at", table_name="site_knowledge_chunks")
    op.drop_index("ix_site_knowledge_chunks_content_hash", table_name="site_knowledge_chunks")
    op.drop_index("ix_site_knowledge_chunks_post_status", table_name="site_knowledge_chunks")
    op.drop_index("ix_site_knowledge_chunks_post_type", table_name="site_knowledge_chunks")
    op.drop_index("ix_site_knowledge_chunks_post_id", table_name="site_knowledge_chunks")
    op.drop_index("ix_site_knowledge_chunks_site_id", table_name="site_knowledge_chunks")
    op.drop_table("site_knowledge_chunks")

    op.drop_index(
        "ix_site_knowledge_documents_last_indexed_at",
        table_name="site_knowledge_documents",
    )
    op.drop_index(
        "ix_site_knowledge_documents_last_sync_run_id",
        table_name="site_knowledge_documents",
    )
    op.drop_index("ix_site_knowledge_documents_content_hash", table_name="site_knowledge_documents")
    op.drop_index("ix_site_knowledge_documents_post_status", table_name="site_knowledge_documents")
    op.drop_index("ix_site_knowledge_documents_post_type", table_name="site_knowledge_documents")
    op.drop_index("ix_site_knowledge_documents_post_id", table_name="site_knowledge_documents")
    op.drop_index("ix_site_knowledge_documents_site_id", table_name="site_knowledge_documents")
    op.drop_table("site_knowledge_documents")
