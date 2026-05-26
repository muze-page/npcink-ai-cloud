"""cloud ops closure schema for audit, decision trace, and retention ops"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260321_0007"
down_revision = "20260321_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.String(length=191), nullable=True),
        sa.Column("site_id", sa.String(length=191), nullable=True),
        sa.Column("key_id", sa.String(length=191), nullable=True),
        sa.Column("subscription_id", sa.String(length=191), nullable=True),
        sa.Column("plan_id", sa.String(length=191), nullable=True),
        sa.Column("plan_version_id", sa.String(length=191), nullable=True),
        sa.Column("scope_kind", sa.String(length=32), nullable=True),
        sa.Column("scope_id", sa.String(length=191), nullable=True),
        sa.Column("event_kind", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=True),
        sa.Column("path", sa.String(length=255), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=191), nullable=True),
        sa.Column(
            "actor_kind",
            sa.String(length=32),
            nullable=False,
            server_default="internal_token",
        ),
        sa.Column("actor_ref", sa.String(length=191), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_service_audit_events_account_id", "service_audit_events", ["account_id"])
    op.create_index("ix_service_audit_events_site_id", "service_audit_events", ["site_id"])
    op.create_index("ix_service_audit_events_key_id", "service_audit_events", ["key_id"])
    op.create_index(
        "ix_service_audit_events_subscription_id",
        "service_audit_events",
        ["subscription_id"],
    )
    op.create_index("ix_service_audit_events_plan_id", "service_audit_events", ["plan_id"])
    op.create_index(
        "ix_service_audit_events_plan_version_id",
        "service_audit_events",
        ["plan_version_id"],
    )
    op.create_index(
        "ix_service_audit_events_scope_kind",
        "service_audit_events",
        ["scope_kind"],
    )
    op.create_index("ix_service_audit_events_scope_id", "service_audit_events", ["scope_id"])
    op.create_index(
        "ix_service_audit_events_event_kind",
        "service_audit_events",
        ["event_kind"],
    )
    op.create_index("ix_service_audit_events_outcome", "service_audit_events", ["outcome"])
    op.create_index("ix_service_audit_events_trace_id", "service_audit_events", ["trace_id"])
    op.create_index("ix_service_audit_events_created_at", "service_audit_events", ["created_at"])

    op.create_table(
        "commercial_decision_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.String(length=191), nullable=True),
        sa.Column("site_id", sa.String(length=191), nullable=True),
        sa.Column("subscription_id", sa.String(length=191), nullable=True),
        sa.Column("plan_version_id", sa.String(length=191), nullable=True),
        sa.Column("run_id", sa.String(length=191), nullable=True),
        sa.Column("request_kind", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("decision_code", sa.String(length=64), nullable=False),
        sa.Column("ability_family", sa.String(length=32), nullable=True),
        sa.Column("channel", sa.String(length=64), nullable=True),
        sa.Column("execution_kind", sa.String(length=32), nullable=True),
        sa.Column("execution_tier", sa.String(length=32), nullable=True),
        sa.Column("data_classification", sa.String(length=32), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=191), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_commercial_decision_events_account_id",
        "commercial_decision_events",
        ["account_id"],
    )
    op.create_index(
        "ix_commercial_decision_events_site_id",
        "commercial_decision_events",
        ["site_id"],
    )
    op.create_index(
        "ix_commercial_decision_events_subscription_id",
        "commercial_decision_events",
        ["subscription_id"],
    )
    op.create_index(
        "ix_commercial_decision_events_plan_version_id",
        "commercial_decision_events",
        ["plan_version_id"],
    )
    op.create_index(
        "ix_commercial_decision_events_run_id",
        "commercial_decision_events",
        ["run_id"],
    )
    op.create_index(
        "ix_commercial_decision_events_request_kind",
        "commercial_decision_events",
        ["request_kind"],
    )
    op.create_index(
        "ix_commercial_decision_events_decision",
        "commercial_decision_events",
        ["decision"],
    )
    op.create_index(
        "ix_commercial_decision_events_decision_code",
        "commercial_decision_events",
        ["decision_code"],
    )
    op.create_index(
        "ix_commercial_decision_events_ability_family",
        "commercial_decision_events",
        ["ability_family"],
    )
    op.create_index(
        "ix_commercial_decision_events_channel",
        "commercial_decision_events",
        ["channel"],
    )
    op.create_index(
        "ix_commercial_decision_events_execution_kind",
        "commercial_decision_events",
        ["execution_kind"],
    )
    op.create_index(
        "ix_commercial_decision_events_execution_tier",
        "commercial_decision_events",
        ["execution_tier"],
    )
    op.create_index(
        "ix_commercial_decision_events_data_classification",
        "commercial_decision_events",
        ["data_classification"],
    )
    op.create_index(
        "ix_commercial_decision_events_trace_id",
        "commercial_decision_events",
        ["trace_id"],
    )
    op.create_index(
        "ix_commercial_decision_events_created_at",
        "commercial_decision_events",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_commercial_decision_events_created_at", table_name="commercial_decision_events")
    op.drop_index("ix_commercial_decision_events_trace_id", table_name="commercial_decision_events")
    op.drop_index(
        "ix_commercial_decision_events_data_classification",
        table_name="commercial_decision_events",
    )
    op.drop_index(
        "ix_commercial_decision_events_execution_tier",
        table_name="commercial_decision_events",
    )
    op.drop_index(
        "ix_commercial_decision_events_execution_kind",
        table_name="commercial_decision_events",
    )
    op.drop_index("ix_commercial_decision_events_channel", table_name="commercial_decision_events")
    op.drop_index(
        "ix_commercial_decision_events_ability_family",
        table_name="commercial_decision_events",
    )
    op.drop_index(
        "ix_commercial_decision_events_decision_code",
        table_name="commercial_decision_events",
    )
    op.drop_index("ix_commercial_decision_events_decision", table_name="commercial_decision_events")
    op.drop_index(
        "ix_commercial_decision_events_request_kind",
        table_name="commercial_decision_events",
    )
    op.drop_index("ix_commercial_decision_events_run_id", table_name="commercial_decision_events")
    op.drop_index(
        "ix_commercial_decision_events_plan_version_id",
        table_name="commercial_decision_events",
    )
    op.drop_index(
        "ix_commercial_decision_events_subscription_id",
        table_name="commercial_decision_events",
    )
    op.drop_index("ix_commercial_decision_events_site_id", table_name="commercial_decision_events")
    op.drop_index(
        "ix_commercial_decision_events_account_id",
        table_name="commercial_decision_events",
    )
    op.drop_table("commercial_decision_events")

    op.drop_index("ix_service_audit_events_created_at", table_name="service_audit_events")
    op.drop_index("ix_service_audit_events_trace_id", table_name="service_audit_events")
    op.drop_index("ix_service_audit_events_outcome", table_name="service_audit_events")
    op.drop_index("ix_service_audit_events_event_kind", table_name="service_audit_events")
    op.drop_index("ix_service_audit_events_scope_id", table_name="service_audit_events")
    op.drop_index("ix_service_audit_events_scope_kind", table_name="service_audit_events")
    op.drop_index(
        "ix_service_audit_events_plan_version_id",
        table_name="service_audit_events",
    )
    op.drop_index("ix_service_audit_events_plan_id", table_name="service_audit_events")
    op.drop_index(
        "ix_service_audit_events_subscription_id",
        table_name="service_audit_events",
    )
    op.drop_index("ix_service_audit_events_key_id", table_name="service_audit_events")
    op.drop_index("ix_service_audit_events_site_id", table_name="service_audit_events")
    op.drop_index("ix_service_audit_events_account_id", table_name="service_audit_events")
    op.drop_table("service_audit_events")
