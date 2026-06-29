"""model reference metadata

Revision ID: 20260629_0049
Revises: 20260627_0048
Create Date: 2026-06-29 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260629_0049"
down_revision = "20260627_0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("model_reference_sources"):
        op.create_table(
            "model_reference_sources",
            sa.Column("source_id", sa.String(length=64), primary_key=True),
            sa.Column("display_name", sa.String(length=128), nullable=False),
            sa.Column("source_url", sa.String(length=500), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error_code", sa.String(length=64), nullable=True),
            sa.Column("last_error_message", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
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
        )
        op.create_index(
            "ix_model_reference_sources_status",
            "model_reference_sources",
            ["status"],
        )

    if not inspector.has_table("model_reference_models"):
        op.create_table(
            "model_reference_models",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("source_id", sa.String(length=64), nullable=False),
            sa.Column("provider_id", sa.String(length=64), nullable=False),
            sa.Column("model_id", sa.String(length=191), nullable=False),
            sa.Column("display_name", sa.String(length=191), nullable=False, server_default=""),
            sa.Column("family", sa.String(length=96), nullable=False, server_default=""),
            sa.Column("feature", sa.String(length=32), nullable=False, server_default="text"),
            sa.Column("modalities_json", sa.JSON(), nullable=True),
            sa.Column("capability_flags_json", sa.JSON(), nullable=True),
            sa.Column("context_window", sa.Integer(), nullable=True),
            sa.Column("output_limit", sa.Integer(), nullable=True),
            sa.Column("price_input", sa.Float(), nullable=True),
            sa.Column("price_output", sa.Float(), nullable=True),
            sa.Column("price_cache_read", sa.Float(), nullable=True),
            sa.Column("price_cache_write", sa.Float(), nullable=True),
            sa.Column(
                "price_unit",
                sa.String(length=64),
                nullable=False,
                server_default="usd_per_1m_tokens",
            ),
            sa.Column("release_date", sa.String(length=32), nullable=False, server_default=""),
            sa.Column(
                "source_updated_at",
                sa.String(length=32),
                nullable=False,
                server_default="",
            ),
            sa.Column("is_deprecated", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("raw_json", sa.JSON(), nullable=True),
            sa.Column(
                "synced_at",
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
            sa.ForeignKeyConstraint(["source_id"], ["model_reference_sources.source_id"]),
            sa.UniqueConstraint(
                "source_id",
                "provider_id",
                "model_id",
                name="uq_model_reference_models_source_provider_model",
            ),
        )
        op.create_index(
            "ix_model_reference_models_source_id",
            "model_reference_models",
            ["source_id"],
        )
        op.create_index(
            "ix_model_reference_models_provider_id",
            "model_reference_models",
            ["provider_id"],
        )
        op.create_index(
            "ix_model_reference_models_model_id",
            "model_reference_models",
            ["model_id"],
        )
        op.create_index(
            "ix_model_reference_models_feature",
            "model_reference_models",
            ["feature"],
        )
        op.create_index(
            "ix_model_reference_models_is_deprecated",
            "model_reference_models",
            ["is_deprecated"],
        )

    if not inspector.has_table("model_reference_overrides"):
        op.create_table(
            "model_reference_overrides",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("provider_id", sa.String(length=64), nullable=False),
            sa.Column("model_id", sa.String(length=191), nullable=False),
            sa.Column("feature_override", sa.String(length=32), nullable=True),
            sa.Column("status_override", sa.String(length=32), nullable=True),
            sa.Column("price_input_override", sa.Float(), nullable=True),
            sa.Column("price_output_override", sa.Float(), nullable=True),
            sa.Column("price_cache_read_override", sa.Float(), nullable=True),
            sa.Column("price_cache_write_override", sa.Float(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "provider_id",
                "model_id",
                name="uq_model_reference_overrides_provider_model",
            ),
        )
        op.create_index(
            "ix_model_reference_overrides_provider_id",
            "model_reference_overrides",
            ["provider_id"],
        )
        op.create_index(
            "ix_model_reference_overrides_model_id",
            "model_reference_overrides",
            ["model_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("model_reference_overrides"):
        op.drop_index(
            "ix_model_reference_overrides_model_id",
            table_name="model_reference_overrides",
        )
        op.drop_index(
            "ix_model_reference_overrides_provider_id",
            table_name="model_reference_overrides",
        )
        op.drop_table("model_reference_overrides")
    if inspector.has_table("model_reference_models"):
        op.drop_index(
            "ix_model_reference_models_is_deprecated",
            table_name="model_reference_models",
        )
        op.drop_index("ix_model_reference_models_feature", table_name="model_reference_models")
        op.drop_index("ix_model_reference_models_model_id", table_name="model_reference_models")
        op.drop_index(
            "ix_model_reference_models_provider_id",
            table_name="model_reference_models",
        )
        op.drop_index("ix_model_reference_models_source_id", table_name="model_reference_models")
        op.drop_table("model_reference_models")
    if inspector.has_table("model_reference_sources"):
        op.drop_index("ix_model_reference_sources_status", table_name="model_reference_sources")
        op.drop_table("model_reference_sources")
