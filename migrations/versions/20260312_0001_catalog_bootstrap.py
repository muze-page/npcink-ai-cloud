"""catalog bootstrap tables"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260312_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_providers",
        sa.Column("provider_id", sa.String(length=64), primary_key=True),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("adapter_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
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

    op.create_table(
        "catalog_revisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("revision", sa.String(length=64), nullable=False, unique=True),
        sa.Column("provider_id", sa.String(length=64), nullable=True),
        sa.Column(
            "source",
            sa.String(length=64),
            nullable=False,
            server_default="provider_refresh",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_catalog_revisions_revision", "catalog_revisions", ["revision"])

    op.create_table(
        "catalog_models",
        sa.Column("model_id", sa.String(length=191), primary_key=True),
        sa.Column(
            "provider_id",
            sa.String(length=64),
            sa.ForeignKey("catalog_providers.provider_id"),
            nullable=False,
        ),
        sa.Column("family", sa.String(length=64), nullable=False),
        sa.Column("feature", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("price_input", sa.Float(), nullable=True),
        sa.Column("price_output", sa.Float(), nullable=True),
        sa.Column("is_deprecated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fallback_candidate", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revision", sa.String(length=64), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_catalog_models_provider_id", "catalog_models", ["provider_id"])
    op.create_index("ix_catalog_models_feature", "catalog_models", ["feature"])
    op.create_index("ix_catalog_models_status", "catalog_models", ["status"])
    op.create_index("ix_catalog_models_revision", "catalog_models", ["revision"])

    op.create_table(
        "catalog_instances",
        sa.Column("instance_id", sa.String(length=191), primary_key=True),
        sa.Column(
            "model_id",
            sa.String(length=191),
            sa.ForeignKey("catalog_models.model_id"),
            nullable=False,
        ),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("endpoint_variant", sa.String(length=64), nullable=False),
        sa.Column("region", sa.String(length=64), nullable=False),
        sa.Column("capability_tags", sa.JSON(), nullable=False),
        sa.Column("health_status", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="100"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_catalog_instances_model_id", "catalog_instances", ["model_id"])
    op.create_index("ix_catalog_instances_provider_id", "catalog_instances", ["provider_id"])
    op.create_index("ix_catalog_instances_health_status", "catalog_instances", ["health_status"])

    op.create_table(
        "routing_profiles",
        sa.Column("profile_id", sa.String(length=64), primary_key=True),
        sa.Column("execution_kind", sa.String(length=32), nullable=False),
        sa.Column("default_policy_json", sa.JSON(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "routing_bindings",
        sa.Column("profile_id", sa.String(length=64), primary_key=True),
        sa.Column("candidate_instance_ids", sa.JSON(), nullable=False),
        sa.Column("selection_policy_json", sa.JSON(), nullable=True),
        sa.Column("revision", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "health_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("instance_id", sa.String(length=191), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "measured_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_health_snapshots_provider_id", "health_snapshots", ["provider_id"])
    op.create_index("ix_health_snapshots_instance_id", "health_snapshots", ["instance_id"])
    op.create_index("ix_health_snapshots_status", "health_snapshots", ["status"])


def downgrade() -> None:
    op.drop_index("ix_health_snapshots_status", table_name="health_snapshots")
    op.drop_index("ix_health_snapshots_instance_id", table_name="health_snapshots")
    op.drop_index("ix_health_snapshots_provider_id", table_name="health_snapshots")
    op.drop_table("health_snapshots")
    op.drop_table("routing_bindings")
    op.drop_table("routing_profiles")
    op.drop_index("ix_catalog_instances_health_status", table_name="catalog_instances")
    op.drop_index("ix_catalog_instances_provider_id", table_name="catalog_instances")
    op.drop_index("ix_catalog_instances_model_id", table_name="catalog_instances")
    op.drop_table("catalog_instances")
    op.drop_index("ix_catalog_models_revision", table_name="catalog_models")
    op.drop_index("ix_catalog_models_status", table_name="catalog_models")
    op.drop_index("ix_catalog_models_feature", table_name="catalog_models")
    op.drop_index("ix_catalog_models_provider_id", table_name="catalog_models")
    op.drop_table("catalog_models")
    op.drop_index("ix_catalog_revisions_revision", table_name="catalog_revisions")
    op.drop_table("catalog_revisions")
    op.drop_table("catalog_providers")
