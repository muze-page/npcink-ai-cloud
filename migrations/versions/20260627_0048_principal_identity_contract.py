"""principal identity contract"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260627_0048"
down_revision = "20260626_0047"
branch_labels = None
depends_on = None


def _index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {str(index["name"]) for index in inspector.get_indexes(table_name)}


def _table_names() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {str(column["name"]) for column in inspector.get_columns(table_name)}


def _drop_table_if_exists(table_name: str) -> None:
    if table_name in _table_names():
        op.drop_table(table_name)


def upgrade() -> None:
    tables = _table_names()
    if "portal_login_codes" in tables:
        indexes = _index_names("portal_login_codes")
        if "ix_portal_login_codes_site_admin_ref" in indexes:
            op.drop_index("ix_portal_login_codes_site_admin_ref", table_name="portal_login_codes")
        columns = _column_names("portal_login_codes")
        if "principal_id" not in columns and "site_admin_ref" in columns:
            op.alter_column(
                "portal_login_codes",
                "site_admin_ref",
                new_column_name="principal_id",
                existing_type=sa.String(length=191),
                existing_nullable=False,
            )
        elif "principal_id" not in columns:
            op.add_column(
                "portal_login_codes",
                sa.Column("principal_id", sa.String(length=191), nullable=False),
            )
        if "ix_portal_login_codes_principal_id" not in _index_names("portal_login_codes"):
            op.create_index(
                "ix_portal_login_codes_principal_id",
                "portal_login_codes",
                ["principal_id"],
            )

    _drop_table_if_exists("platform_admin_identities")
    _drop_table_if_exists("site_admin_site_grants")
    _drop_table_if_exists("site_admin_identities")

    op.create_table(
        "principals",
        sa.Column("principal_id", sa.String(length=191), nullable=False),
        sa.Column("email", sa.String(length=191), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("session_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("principal_id"),
        sa.UniqueConstraint("email", name="uq_principals_email"),
    )
    op.create_index("ix_principals_email", "principals", ["email"])
    op.create_index("ix_principals_status", "principals", ["status"])
    op.create_index("ix_principals_last_login_at", "principals", ["last_login_at"])

    op.create_table(
        "site_user_grants",
        sa.Column("grant_id", sa.String(length=191), nullable=False),
        sa.Column("principal_id", sa.String(length=191), nullable=False),
        sa.Column("site_id", sa.String(length=191), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
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
        sa.ForeignKeyConstraint(["principal_id"], ["principals.principal_id"]),
        sa.ForeignKeyConstraint(["site_id"], ["sites.site_id"]),
        sa.PrimaryKeyConstraint("grant_id"),
        sa.UniqueConstraint(
            "principal_id",
            "site_id",
            name="uq_site_user_grants_principal_site",
        ),
    )
    op.create_index("ix_site_user_grants_principal_id", "site_user_grants", ["principal_id"])
    op.create_index("ix_site_user_grants_site_id", "site_user_grants", ["site_id"])
    op.create_index("ix_site_user_grants_status", "site_user_grants", ["status"])

    op.create_table(
        "account_user_memberships",
        sa.Column("membership_id", sa.String(length=191), nullable=False),
        sa.Column("principal_id", sa.String(length=191), nullable=False),
        sa.Column("account_id", sa.String(length=191), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False, server_default="user"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("allowed_actions_json", sa.JSON(), nullable=False),
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
        sa.ForeignKeyConstraint(["principal_id"], ["principals.principal_id"]),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"]),
        sa.CheckConstraint("role IN ('user')", name="ck_account_user_memberships_role"),
        sa.PrimaryKeyConstraint("membership_id"),
        sa.UniqueConstraint(
            "principal_id",
            "account_id",
            name="uq_account_user_memberships_principal_account",
        ),
    )
    op.create_index(
        "ix_account_user_memberships_principal_id",
        "account_user_memberships",
        ["principal_id"],
    )
    op.create_index(
        "ix_account_user_memberships_account_id",
        "account_user_memberships",
        ["account_id"],
    )
    op.create_index("ix_account_user_memberships_role", "account_user_memberships", ["role"])
    op.create_index("ix_account_user_memberships_status", "account_user_memberships", ["status"])

    op.create_table(
        "platform_admin_grants",
        sa.Column("grant_id", sa.String(length=191), nullable=False),
        sa.Column("principal_id", sa.String(length=191), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default="manual"),
        sa.Column("external_subject", sa.String(length=191), nullable=True),
        sa.Column("email", sa.String(length=191), nullable=True),
        sa.Column("role", sa.String(length=64), nullable=False, server_default="platform_admin"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
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
        sa.ForeignKeyConstraint(["principal_id"], ["principals.principal_id"]),
        sa.PrimaryKeyConstraint("grant_id"),
        sa.UniqueConstraint("principal_id", name="uq_platform_admin_grants_principal_id"),
    )
    op.create_index(
        "ix_platform_admin_grants_principal_id",
        "platform_admin_grants",
        ["principal_id"],
    )
    op.create_index("ix_platform_admin_grants_provider", "platform_admin_grants", ["provider"])
    op.create_index(
        "ix_platform_admin_grants_external_subject",
        "platform_admin_grants",
        ["external_subject"],
    )
    op.create_index("ix_platform_admin_grants_email", "platform_admin_grants", ["email"])
    op.create_index("ix_platform_admin_grants_role", "platform_admin_grants", ["role"])
    op.create_index("ix_platform_admin_grants_status", "platform_admin_grants", ["status"])

    op.create_table(
        "identity_provider_bindings",
        sa.Column("binding_id", sa.String(length=191), nullable=False),
        sa.Column("principal_id", sa.String(length=191), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("external_subject_hash", sa.String(length=191), nullable=False),
        sa.Column("unionid_hash", sa.String(length=191), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["principal_id"], ["principals.principal_id"]),
        sa.PrimaryKeyConstraint("binding_id"),
        sa.UniqueConstraint(
            "provider",
            "external_subject_hash",
            name="uq_identity_provider_bindings_provider_subject",
        ),
    )
    op.create_index(
        "ix_identity_provider_bindings_principal_id",
        "identity_provider_bindings",
        ["principal_id"],
    )
    op.create_index(
        "ix_identity_provider_bindings_provider",
        "identity_provider_bindings",
        ["provider"],
    )
    op.create_index(
        "ix_identity_provider_bindings_external_subject_hash",
        "identity_provider_bindings",
        ["external_subject_hash"],
    )
    op.create_index(
        "ix_identity_provider_bindings_unionid_hash",
        "identity_provider_bindings",
        ["unionid_hash"],
    )
    op.create_index(
        "ix_identity_provider_bindings_status",
        "identity_provider_bindings",
        ["status"],
    )
    op.create_index(
        "ix_identity_provider_bindings_last_login_at",
        "identity_provider_bindings",
        ["last_login_at"],
    )

    op.create_table(
        "portal_oauth_states",
        sa.Column("state_id", sa.String(length=191), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("state_hash", sa.String(length=191), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("return_to", sa.String(length=255), nullable=True),
        sa.Column("client_scope_id", sa.String(length=191), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("state_id"),
        sa.UniqueConstraint(
            "provider",
            "state_hash",
            name="uq_portal_oauth_states_provider_state",
        ),
    )
    op.create_index("ix_portal_oauth_states_provider", "portal_oauth_states", ["provider"])
    op.create_index("ix_portal_oauth_states_state_hash", "portal_oauth_states", ["state_hash"])
    op.create_index("ix_portal_oauth_states_status", "portal_oauth_states", ["status"])
    op.create_index(
        "ix_portal_oauth_states_client_scope_id",
        "portal_oauth_states",
        ["client_scope_id"],
    )
    op.create_index("ix_portal_oauth_states_expires_at", "portal_oauth_states", ["expires_at"])
    op.create_index("ix_portal_oauth_states_consumed_at", "portal_oauth_states", ["consumed_at"])


def downgrade() -> None:
    op.drop_index("ix_portal_oauth_states_consumed_at", table_name="portal_oauth_states")
    op.drop_index("ix_portal_oauth_states_expires_at", table_name="portal_oauth_states")
    op.drop_index("ix_portal_oauth_states_client_scope_id", table_name="portal_oauth_states")
    op.drop_index("ix_portal_oauth_states_status", table_name="portal_oauth_states")
    op.drop_index("ix_portal_oauth_states_state_hash", table_name="portal_oauth_states")
    op.drop_index("ix_portal_oauth_states_provider", table_name="portal_oauth_states")
    op.drop_table("portal_oauth_states")

    op.drop_index(
        "ix_identity_provider_bindings_last_login_at",
        table_name="identity_provider_bindings",
    )
    op.drop_index("ix_identity_provider_bindings_status", table_name="identity_provider_bindings")
    op.drop_index(
        "ix_identity_provider_bindings_unionid_hash",
        table_name="identity_provider_bindings",
    )
    op.drop_index(
        "ix_identity_provider_bindings_external_subject_hash",
        table_name="identity_provider_bindings",
    )
    op.drop_index("ix_identity_provider_bindings_provider", table_name="identity_provider_bindings")
    op.drop_index(
        "ix_identity_provider_bindings_principal_id",
        table_name="identity_provider_bindings",
    )
    op.drop_table("identity_provider_bindings")

    op.drop_index("ix_platform_admin_grants_status", table_name="platform_admin_grants")
    op.drop_index("ix_platform_admin_grants_role", table_name="platform_admin_grants")
    op.drop_index("ix_platform_admin_grants_email", table_name="platform_admin_grants")
    op.drop_index(
        "ix_platform_admin_grants_external_subject",
        table_name="platform_admin_grants",
    )
    op.drop_index("ix_platform_admin_grants_provider", table_name="platform_admin_grants")
    op.drop_index("ix_platform_admin_grants_principal_id", table_name="platform_admin_grants")
    op.drop_table("platform_admin_grants")

    op.drop_index("ix_account_user_memberships_status", table_name="account_user_memberships")
    op.drop_index("ix_account_user_memberships_role", table_name="account_user_memberships")
    op.drop_index("ix_account_user_memberships_account_id", table_name="account_user_memberships")
    op.drop_index(
        "ix_account_user_memberships_principal_id",
        table_name="account_user_memberships",
    )
    op.drop_table("account_user_memberships")

    op.drop_index("ix_site_user_grants_status", table_name="site_user_grants")
    op.drop_index("ix_site_user_grants_site_id", table_name="site_user_grants")
    op.drop_index("ix_site_user_grants_principal_id", table_name="site_user_grants")
    op.drop_table("site_user_grants")

    op.drop_index("ix_principals_last_login_at", table_name="principals")
    op.drop_index("ix_principals_status", table_name="principals")
    op.drop_index("ix_principals_email", table_name="principals")
    op.drop_table("principals")

    if "portal_login_codes" in _table_names():
        indexes = _index_names("portal_login_codes")
        if "ix_portal_login_codes_principal_id" in indexes:
            op.drop_index("ix_portal_login_codes_principal_id", table_name="portal_login_codes")
        columns = _column_names("portal_login_codes")
        if "site_admin_ref" not in columns and "principal_id" in columns:
            op.alter_column(
                "portal_login_codes",
                "principal_id",
                new_column_name="site_admin_ref",
                existing_type=sa.String(length=191),
                existing_nullable=False,
            )
        if "ix_portal_login_codes_site_admin_ref" not in _index_names("portal_login_codes"):
            op.create_index(
                "ix_portal_login_codes_site_admin_ref",
                "portal_login_codes",
                ["site_admin_ref"],
            )
