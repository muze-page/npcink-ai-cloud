"""add site knowledge source fields"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260603_0038"
down_revision = "20260603_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "site_knowledge_documents",
        sa.Column("source_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "site_knowledge_documents",
        sa.Column("source_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "site_knowledge_documents",
        sa.Column("parent_post_id", sa.Integer(), nullable=True),
    )
    op.execute(
        "UPDATE site_knowledge_documents "
        "SET source_type = post_type, source_id = post_id, parent_post_id = post_id"
    )
    op.alter_column("site_knowledge_documents", "source_type", nullable=False)
    op.alter_column("site_knowledge_documents", "source_id", nullable=False)
    op.create_index(
        "ix_site_knowledge_documents_source_type",
        "site_knowledge_documents",
        ["source_type"],
    )
    op.create_index(
        "ix_site_knowledge_documents_source_id",
        "site_knowledge_documents",
        ["source_id"],
    )
    op.create_index(
        "ix_site_knowledge_documents_parent_post_id",
        "site_knowledge_documents",
        ["parent_post_id"],
    )
    op.drop_constraint(
        "uq_site_knowledge_documents_site_post",
        "site_knowledge_documents",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_site_knowledge_documents_site_source",
        "site_knowledge_documents",
        ["site_id", "source_type", "source_id"],
    )

    op.add_column(
        "site_knowledge_chunks",
        sa.Column("source_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "site_knowledge_chunks",
        sa.Column("source_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "site_knowledge_chunks",
        sa.Column("parent_post_id", sa.Integer(), nullable=True),
    )
    op.execute(
        "UPDATE site_knowledge_chunks "
        "SET source_type = post_type, source_id = post_id, parent_post_id = post_id"
    )
    op.alter_column("site_knowledge_chunks", "source_type", nullable=False)
    op.alter_column("site_knowledge_chunks", "source_id", nullable=False)
    op.create_index(
        "ix_site_knowledge_chunks_source_type",
        "site_knowledge_chunks",
        ["source_type"],
    )
    op.create_index("ix_site_knowledge_chunks_source_id", "site_knowledge_chunks", ["source_id"])
    op.create_index(
        "ix_site_knowledge_chunks_parent_post_id",
        "site_knowledge_chunks",
        ["parent_post_id"],
    )
    op.drop_constraint(
        "uq_site_knowledge_chunks_site_post_chunk",
        "site_knowledge_chunks",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_site_knowledge_chunks_site_source_chunk",
        "site_knowledge_chunks",
        ["site_id", "source_type", "source_id", "chunk_index"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_site_knowledge_chunks_site_source_chunk",
        "site_knowledge_chunks",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_site_knowledge_chunks_site_post_chunk",
        "site_knowledge_chunks",
        ["site_id", "post_id", "chunk_index"],
    )
    op.drop_index("ix_site_knowledge_chunks_parent_post_id", table_name="site_knowledge_chunks")
    op.drop_index("ix_site_knowledge_chunks_source_id", table_name="site_knowledge_chunks")
    op.drop_index("ix_site_knowledge_chunks_source_type", table_name="site_knowledge_chunks")
    op.drop_column("site_knowledge_chunks", "parent_post_id")
    op.drop_column("site_knowledge_chunks", "source_id")
    op.drop_column("site_knowledge_chunks", "source_type")

    op.drop_constraint(
        "uq_site_knowledge_documents_site_source",
        "site_knowledge_documents",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_site_knowledge_documents_site_post",
        "site_knowledge_documents",
        ["site_id", "post_id"],
    )
    op.drop_index(
        "ix_site_knowledge_documents_parent_post_id",
        table_name="site_knowledge_documents",
    )
    op.drop_index("ix_site_knowledge_documents_source_id", table_name="site_knowledge_documents")
    op.drop_index("ix_site_knowledge_documents_source_type", table_name="site_knowledge_documents")
    op.drop_column("site_knowledge_documents", "parent_post_id")
    op.drop_column("site_knowledge_documents", "source_id")
    op.drop_column("site_knowledge_documents", "source_type")
