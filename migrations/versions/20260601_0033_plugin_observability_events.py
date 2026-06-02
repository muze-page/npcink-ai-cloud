"""plugin_observability_events

Revision ID: 20260601_0033
Revises: 20260528_0032
Create Date: 2026-06-01

"""

from alembic import op
import sqlalchemy as sa


revision = "20260601_0033"
down_revision = "20260528_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("plugin_observability_events"):
        return

    op.create_table(
        "plugin_observability_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("site_id", sa.String(length=191), nullable=False),
        sa.Column("key_id", sa.String(length=191), nullable=True),
        sa.Column("schema_version", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("plugin_slug", sa.String(length=64), nullable=False),
        sa.Column("plugin_version", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="local"),
        sa.Column("event_kind", sa.String(length=96), nullable=False),
        sa.Column("event_id", sa.String(length=96), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("status_detail", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("ability_id", sa.String(length=191), nullable=True),
        sa.Column("proposal_id", sa.String(length=191), nullable=True),
        sa.Column("correlation_id", sa.String(length=191), nullable=True),
        sa.Column("adapter_request_id", sa.String(length=191), nullable=True),
        sa.Column("method", sa.String(length=16), nullable=True),
        sa.Column("route", sa.String(length=255), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("emitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["sites.site_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_plugin_observability_events_dedupe"),
    )
    for index_name, columns in (
        ("ix_plugin_observability_events_site_id", ["site_id"]),
        ("ix_plugin_observability_events_key_id", ["key_id"]),
        ("ix_plugin_observability_events_plugin_slug", ["plugin_slug"]),
        ("ix_plugin_observability_events_source", ["source"]),
        ("ix_plugin_observability_events_event_kind", ["event_kind"]),
        ("ix_plugin_observability_events_event_id", ["event_id"]),
        ("ix_plugin_observability_events_status", ["status"]),
        ("ix_plugin_observability_events_error_code", ["error_code"]),
        ("ix_plugin_observability_events_ability_id", ["ability_id"]),
        ("ix_plugin_observability_events_proposal_id", ["proposal_id"]),
        ("ix_plugin_observability_events_correlation_id", ["correlation_id"]),
        ("ix_plugin_observability_events_adapter_request_id", ["adapter_request_id"]),
        ("ix_plugin_observability_events_route", ["route"]),
        ("ix_plugin_observability_events_emitted_at", ["emitted_at"]),
        ("ix_plugin_observability_events_captured_at", ["captured_at"]),
        ("ix_plugin_observability_events_received_at", ["received_at"]),
    ):
        op.create_index(index_name, "plugin_observability_events", columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("plugin_observability_events"):
        op.drop_table("plugin_observability_events")
