"""runtime guard events and ops hardening schema"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260321_0009"
down_revision = "20260321_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "runtime_guard_events" not in existing_tables:
        op.create_table(
            "runtime_guard_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("auth_surface", sa.String(length=32), nullable=False),
            sa.Column("scope_kind", sa.String(length=32), nullable=False),
            sa.Column("scope_id", sa.String(length=191), nullable=False),
            sa.Column("site_id", sa.String(length=191), nullable=True),
            sa.Column("key_id", sa.String(length=191), nullable=True),
            sa.Column("client_ref", sa.String(length=191), nullable=True),
            sa.Column("event_code", sa.String(length=64), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=False),
            sa.Column("method", sa.String(length=16), nullable=True),
            sa.Column("path", sa.String(length=255), nullable=True),
            sa.Column("trace_id", sa.String(length=64), nullable=True),
            sa.Column("payload_json", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    existing_indexes = {
        index["name"] for index in inspector.get_indexes("runtime_guard_events")
    }
    index_specs = [
        ("ix_runtime_guard_events_auth_surface", ["auth_surface"]),
        ("ix_runtime_guard_events_scope_kind", ["scope_kind"]),
        ("ix_runtime_guard_events_scope_id", ["scope_id"]),
        ("ix_runtime_guard_events_site_id", ["site_id"]),
        ("ix_runtime_guard_events_key_id", ["key_id"]),
        ("ix_runtime_guard_events_client_ref", ["client_ref"]),
        ("ix_runtime_guard_events_event_code", ["event_code"]),
        ("ix_runtime_guard_events_status_code", ["status_code"]),
        ("ix_runtime_guard_events_trace_id", ["trace_id"]),
        ("ix_runtime_guard_events_created_at", ["created_at"]),
    ]
    for index_name, columns in index_specs:
        if index_name not in existing_indexes:
            op.create_index(index_name, "runtime_guard_events", columns)


def downgrade() -> None:
    op.drop_index("ix_runtime_guard_events_created_at", table_name="runtime_guard_events")
    op.drop_index("ix_runtime_guard_events_trace_id", table_name="runtime_guard_events")
    op.drop_index("ix_runtime_guard_events_status_code", table_name="runtime_guard_events")
    op.drop_index("ix_runtime_guard_events_event_code", table_name="runtime_guard_events")
    op.drop_index("ix_runtime_guard_events_client_ref", table_name="runtime_guard_events")
    op.drop_index("ix_runtime_guard_events_key_id", table_name="runtime_guard_events")
    op.drop_index("ix_runtime_guard_events_site_id", table_name="runtime_guard_events")
    op.drop_index("ix_runtime_guard_events_scope_id", table_name="runtime_guard_events")
    op.drop_index("ix_runtime_guard_events_scope_kind", table_name="runtime_guard_events")
    op.drop_index("ix_runtime_guard_events_auth_surface", table_name="runtime_guard_events")
    op.drop_table("runtime_guard_events")
