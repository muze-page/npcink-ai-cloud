"""runtime records and site auth tables"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260312_0002"
down_revision = "20260312_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sites",
        sa.Column("site_id", sa.String(length=191), primary_key=True),
        sa.Column("name", sa.String(length=191), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_sites_status", "sites", ["status"])

    op.create_table(
        "site_api_keys",
        sa.Column("key_id", sa.String(length=191), primary_key=True),
        sa.Column("site_id", sa.String(length=191), sa.ForeignKey("sites.site_id"), nullable=False),
        sa.Column("secret_hash", sa.String(length=191), nullable=False),
        sa.Column("scopes_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_site_api_keys_site_id", "site_api_keys", ["site_id"])
    op.create_index("ix_site_api_keys_status", "site_api_keys", ["status"])

    op.create_table(
        "run_records",
        sa.Column("run_id", sa.String(length=191), primary_key=True),
        sa.Column("site_id", sa.String(length=191), sa.ForeignKey("sites.site_id"), nullable=False),
        sa.Column("ability_name", sa.String(length=191), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("execution_kind", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=191), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=191), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=True),
        sa.Column("policy_json", sa.JSON(), nullable=True),
        sa.Column("result_ref", sa.String(length=64), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("selected_provider_id", sa.String(length=64), nullable=True),
        sa.Column("selected_model_id", sa.String(length=191), nullable=True),
        sa.Column("selected_instance_id", sa.String(length=191), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "site_id",
            "idempotency_key",
            name="uq_run_records_site_idempotency",
        ),
    )
    op.create_index("ix_run_records_site_id", "run_records", ["site_id"])
    op.create_index("ix_run_records_ability_name", "run_records", ["ability_name"])
    op.create_index("ix_run_records_channel", "run_records", ["channel"])
    op.create_index("ix_run_records_execution_kind", "run_records", ["execution_kind"])
    op.create_index("ix_run_records_profile_id", "run_records", ["profile_id"])
    op.create_index("ix_run_records_status", "run_records", ["status"])
    op.create_index("ix_run_records_trace_id", "run_records", ["trace_id"])

    op.create_table(
        "provider_call_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(length=191),
            sa.ForeignKey("run_records.run_id"),
            nullable=False,
        ),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=191), nullable=False),
        sa.Column("instance_id", sa.String(length=191), nullable=False),
        sa.Column("region", sa.String(length=64), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_provider_call_records_run_id", "provider_call_records", ["run_id"])
    op.create_index(
        "ix_provider_call_records_provider_id",
        "provider_call_records",
        ["provider_id"],
    )
    op.create_index(
        "ix_provider_call_records_model_id",
        "provider_call_records",
        ["model_id"],
    )
    op.create_index(
        "ix_provider_call_records_instance_id",
        "provider_call_records",
        ["instance_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_provider_call_records_instance_id", table_name="provider_call_records")
    op.drop_index("ix_provider_call_records_model_id", table_name="provider_call_records")
    op.drop_index("ix_provider_call_records_provider_id", table_name="provider_call_records")
    op.drop_index("ix_provider_call_records_run_id", table_name="provider_call_records")
    op.drop_table("provider_call_records")
    op.drop_index("ix_run_records_trace_id", table_name="run_records")
    op.drop_index("ix_run_records_status", table_name="run_records")
    op.drop_index("ix_run_records_profile_id", table_name="run_records")
    op.drop_index("ix_run_records_execution_kind", table_name="run_records")
    op.drop_index("ix_run_records_channel", table_name="run_records")
    op.drop_index("ix_run_records_ability_name", table_name="run_records")
    op.drop_index("ix_run_records_site_id", table_name="run_records")
    op.drop_table("run_records")
    op.drop_index("ix_site_api_keys_status", table_name="site_api_keys")
    op.drop_index("ix_site_api_keys_site_id", table_name="site_api_keys")
    op.drop_table("site_api_keys")
    op.drop_index("ix_sites_status", table_name="sites")
    op.drop_table("sites")
