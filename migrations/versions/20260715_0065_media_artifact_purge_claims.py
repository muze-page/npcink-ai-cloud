"""add fenced media artifact purge claims"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260715_0065"
down_revision = "20260715_0064"
branch_labels = None
depends_on = None

_TABLE = "media_artifacts"
_DUPLICATE_STORAGE_KEY_ERROR = (
    "pre-GA reset required: media_artifacts contains duplicate storage_key values; "
    "repair/reset duplicate artifact ownership before retrying"
)
_STORAGE_KEY_UNIQUE = "uq_media_artifacts_storage_key"
_CLAIM_PAIR_CHECK = "ck_media_artifacts_purge_claim_pair"
_CLAIM_EXPIRY_INDEX = "ix_media_artifacts_purge_claim_expires_at"
_FOREIGN_KEY_VALIDATION_ERROR = (
    "pre-GA reset required: media artifact foreign key validation failed; "
    "repair/reset media artifact references before retrying"
)
_SQLITE_TRANSACTION_ERROR = (
    "pre-GA reset required: SQLite media artifact migration transaction could not start; "
    "retry with an atomic migration connection"
)


def _sqlite_driver_in_transaction(bind: sa.Connection) -> bool:
    driver_connection = bind.connection.driver_connection
    return bool(getattr(driver_connection, "in_transaction", False))


def _ensure_sqlite_migration_transaction(bind: sa.Connection) -> None:
    if bind.dialect.name != "sqlite" or _sqlite_driver_in_transaction(bind):
        return
    bind.exec_driver_sql("BEGIN IMMEDIATE")
    if not _sqlite_driver_in_transaction(bind):
        raise RuntimeError(_SQLITE_TRANSACTION_ERROR)


def _enable_sqlite_deferred_foreign_keys(bind: sa.Connection) -> bool:
    if bind.dialect.name != "sqlite":
        return False
    if bind.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 1:
        return False
    bind.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
    if bind.exec_driver_sql("PRAGMA defer_foreign_keys").scalar_one() != 1:
        raise RuntimeError(_FOREIGN_KEY_VALIDATION_ERROR)
    return True


def _validate_and_restore_sqlite_foreign_keys(
    bind: sa.Connection,
    *,
    deferred: bool,
) -> None:
    if not deferred:
        return
    try:
        violation = bind.exec_driver_sql("PRAGMA foreign_key_check").first()
    except BaseException:
        _restore_sqlite_deferred_foreign_keys_best_effort(bind, deferred=True)
        raise
    _restore_sqlite_deferred_foreign_keys(bind, deferred=True)
    if violation is not None:
        raise RuntimeError(_FOREIGN_KEY_VALIDATION_ERROR)


def _restore_sqlite_deferred_foreign_keys(
    bind: sa.Connection,
    *,
    deferred: bool,
) -> None:
    if not deferred:
        return
    bind.exec_driver_sql("PRAGMA defer_foreign_keys=OFF")


def _restore_sqlite_deferred_foreign_keys_best_effort(
    bind: sa.Connection,
    *,
    deferred: bool,
) -> None:
    try:
        _restore_sqlite_deferred_foreign_keys(bind, deferred=deferred)
    except BaseException:
        pass


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return

    _ensure_sqlite_migration_transaction(bind)
    duplicate_exists = bind.execute(
        sa.text("SELECT 1 FROM media_artifacts GROUP BY storage_key HAVING COUNT(*) > 1 LIMIT 1")
    ).first()
    if duplicate_exists is not None:
        raise RuntimeError(_DUPLICATE_STORAGE_KEY_ERROR)

    deferred = _enable_sqlite_deferred_foreign_keys(bind)
    try:
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column("purge_claim_id", sa.String(64), nullable=True))
            batch.add_column(
                sa.Column(
                    "purge_claim_expires_at",
                    sa.DateTime(timezone=True),
                    nullable=True,
                )
            )
            batch.create_unique_constraint(_STORAGE_KEY_UNIQUE, ["storage_key"])
            batch.create_check_constraint(
                _CLAIM_PAIR_CHECK,
                "((purge_claim_id IS NULL AND purge_claim_expires_at IS NULL) OR "
                "(purge_claim_id IS NOT NULL AND purge_claim_expires_at IS NOT NULL))",
            )
        op.create_index(
            _CLAIM_EXPIRY_INDEX,
            _TABLE,
            ["purge_claim_expires_at"],
        )
    except BaseException:
        _restore_sqlite_deferred_foreign_keys_best_effort(bind, deferred=deferred)
        raise
    else:
        _validate_and_restore_sqlite_foreign_keys(bind, deferred=deferred)


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    _ensure_sqlite_migration_transaction(bind)
    deferred = _enable_sqlite_deferred_foreign_keys(bind)
    try:
        op.drop_index(_CLAIM_EXPIRY_INDEX, table_name=_TABLE)
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_constraint(_CLAIM_PAIR_CHECK, type_="check")
            batch.drop_constraint(_STORAGE_KEY_UNIQUE, type_="unique")
            batch.drop_column("purge_claim_expires_at")
            batch.drop_column("purge_claim_id")
    except BaseException:
        _restore_sqlite_deferred_foreign_keys_best_effort(bind, deferred=deferred)
        raise
    else:
        _validate_and_restore_sqlite_foreign_keys(bind, deferred=deferred)
