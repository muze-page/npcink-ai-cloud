from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.core.config import get_settings


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'identity-role-migration.sqlite3'}"


def _alembic_config(database_url: str) -> Config:
    root_dir = Path(__file__).resolve().parents[2]
    config = Config(str(root_dir / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.set_main_option("script_location", str(root_dir / "migrations"))
    return config


def test_identity_role_collapse_migration_rewrites_historical_values(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    previous_database_url = os.environ.get("MAGICK_CLOUD_DATABASE_URL")
    os.environ["MAGICK_CLOUD_DATABASE_URL"] = database_url

    # Clear cached settings so migrations/env.py sees the updated env var.
    get_settings.cache_clear()
    if "migrations.env" in sys.modules:
        del sys.modules["migrations.env"]

    try:
        config = _alembic_config(database_url)
        command.upgrade(config, "20260410_0022")

        engine = create_engine(database_url, future=True)
        now = datetime.now(UTC)

        with engine.begin() as connection:
            # Seed pre-collapse legacy role values on purpose so this test
            # proves that upgrading to head rewrites them into the canonical
            # two-identity model. These literals are test fixtures, not the
            # current runtime contract.
            connection.execute(
                text(
                    """
                    INSERT INTO accounts (account_id, name, status)
                    VALUES ('acct_legacy_identity', 'Legacy Identity Account', 'active')
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO account_memberships (account_id, member_ref, role, status, metadata_json)
                    VALUES (:account_id, :member_ref, :role, 'active', '{}')
                    """
                ),
                {
                    "account_id": "acct_legacy_identity",
                    "member_ref": "user:legacy@example.com",
                    "role": "viewer",
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO platform_admin_identities (
                        admin_id, admin_ref, provider, external_subject, email, role, status, metadata_json
                    )
                    VALUES (:admin_id, :admin_ref, 'manual', NULL, 'legacy-admin@example.com', :role, 'active', '{}')
                    """
                ),
                {
                    "admin_id": "pad_legacy_identity",
                    "admin_ref": "platform:legacy",
                    "role": "platform_support_admin",
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO platform_impersonation_sessions (
                        impersonation_id,
                        platform_admin_ref,
                        platform_role,
                        member_ref,
                        account_id,
                        site_id,
                        reason_code,
                        reason_text,
                        read_only,
                        status,
                        started_at,
                        expires_at,
                        ended_at,
                        ended_reason,
                        metadata_json
                    )
                    VALUES (
                        :impersonation_id,
                        :platform_admin_ref,
                        :platform_role,
                        :member_ref,
                        :account_id,
                        :site_id,
                        'support_debug',
                        'legacy role test',
                        1,
                        'active',
                        :started_at,
                        :expires_at,
                        NULL,
                        '',
                        '{}'
                    )
                    """
                ),
                {
                    "impersonation_id": "imp_legacy_identity",
                    "platform_admin_ref": "platform:legacy",
                    "platform_role": "platform_support_admin",
                    "member_ref": "user:legacy@example.com",
                    "account_id": "acct_legacy_identity",
                    "site_id": "site_legacy_identity",
                    "started_at": now,
                    "expires_at": now + timedelta(minutes=30),
                },
            )

        command.upgrade(config, "20260412_0023")

        with engine.connect() as connection:
            membership_role = connection.execute(
                text("SELECT role FROM account_memberships WHERE member_ref = 'user:legacy@example.com'")
            ).scalar_one()
            platform_role = connection.execute(
                text("SELECT role FROM platform_admin_identities WHERE admin_ref = 'platform:legacy'")
            ).scalar_one()
            impersonation_role = connection.execute(
                text(
                    "SELECT platform_role FROM platform_impersonation_sessions WHERE impersonation_id = 'imp_legacy_identity'"
                )
            ).scalar_one()

        assert membership_role == "user_admin"
        assert platform_role == "platform_admin"
        assert impersonation_role == "platform_admin"
    finally:
        if previous_database_url is None:
            os.environ.pop("MAGICK_CLOUD_DATABASE_URL", None)
        else:
            os.environ["MAGICK_CLOUD_DATABASE_URL"] = previous_database_url
