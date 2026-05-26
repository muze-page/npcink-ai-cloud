"""portal member identity mapping for external auth providers"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260323_0011"
down_revision = "20260321_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_tables = set(inspector.get_table_names())
    if "portal_member_identities" in existing_tables:
        return

    op.create_table(
        "portal_member_identities",
        sa.Column("identity_id", sa.String(length=191), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("external_subject", sa.String(length=191), nullable=False),
        sa.Column("email", sa.String(length=191), nullable=True),
        sa.Column("member_ref", sa.String(length=191), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("identity_id"),
        sa.UniqueConstraint(
            "provider",
            "external_subject",
            name="uq_portal_member_identities_provider_subject",
        ),
    )
    op.create_index(
        "ix_portal_member_identities_provider",
        "portal_member_identities",
        ["provider"],
    )
    op.create_index(
        "ix_portal_member_identities_email",
        "portal_member_identities",
        ["email"],
    )
    op.create_index(
        "ix_portal_member_identities_member_ref",
        "portal_member_identities",
        ["member_ref"],
    )
    op.create_index(
        "ix_portal_member_identities_status",
        "portal_member_identities",
        ["status"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_tables = set(inspector.get_table_names())
    if "portal_member_identities" not in existing_tables:
        return

    op.drop_index("ix_portal_member_identities_status", table_name="portal_member_identities")
    op.drop_index("ix_portal_member_identities_member_ref", table_name="portal_member_identities")
    op.drop_index("ix_portal_member_identities_email", table_name="portal_member_identities")
    op.drop_index("ix_portal_member_identities_provider", table_name="portal_member_identities")
    op.drop_table("portal_member_identities")
