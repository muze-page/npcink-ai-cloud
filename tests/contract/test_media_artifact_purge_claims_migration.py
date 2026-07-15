from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError

from app.core.models import MediaArtifact

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations/versions/20260715_0065_media_artifact_purge_claims.py"
RESET_ERROR = (
    "pre-GA reset required: media_artifacts contains duplicate storage_key values; "
    "repair/reset duplicate artifact ownership before retrying"
)
OLD_INDEXES = {
    "ix_media_artifacts_run_id",
    "ix_media_artifacts_site_id",
    "ix_media_artifacts_status",
    "ix_media_artifacts_expires_at",
    "ix_media_artifacts_purge_next_attempt_at",
}


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("media_artifact_purge_claims_0065", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_0064_schema(engine: sa.Engine) -> sa.Table:
    metadata = sa.MetaData()
    sa.Table(
        "run_records",
        metadata,
        sa.Column("run_id", sa.String(191), primary_key=True),
    )
    sa.Table(
        "alembic_version",
        metadata,
        sa.Column("version_num", sa.String(32), primary_key=True),
    )
    table = sa.Table(
        "media_artifacts",
        metadata,
        sa.Column("artifact_id", sa.String(191), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(191),
            sa.ForeignKey("run_records.run_id"),
            nullable=False,
        ),
        sa.Column("site_id", sa.String(191), nullable=False),
        sa.Column("media_kind", sa.String(16), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer, nullable=False),
        sa.Column("checksum", sa.String(128), nullable=False),
        sa.Column("storage_key", sa.String(191), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("width", sa.Integer, nullable=False, server_default="0"),
        sa.Column("height", sa.Integer, nullable=False, server_default="0"),
        sa.Column("processing_warnings_json", sa.JSON),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purged_at", sa.DateTime(timezone=True)),
        sa.Column("purge_attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("purge_last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("purge_next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("purge_last_error_code", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    for name, columns in (
        ("ix_media_artifacts_run_id", ["run_id"]),
        ("ix_media_artifacts_site_id", ["site_id"]),
        ("ix_media_artifacts_status", ["status"]),
        ("ix_media_artifacts_expires_at", ["expires_at"]),
        ("ix_media_artifacts_purge_next_attempt_at", ["purge_next_attempt_at"]),
    ):
        sa.Index(name, *(table.c[column] for column in columns))
    deliveries = sa.Table(
        "media_artifact_deliveries",
        metadata,
        sa.Column("delivery_id", sa.String(191), primary_key=True),
        sa.Column(
            "artifact_id",
            sa.String(191),
            sa.ForeignKey("media_artifacts.artifact_id"),
            nullable=False,
        ),
        sa.Column("site_id", sa.String(191), nullable=False),
        sa.Column("expected_byte_size", sa.Integer, nullable=False),
        sa.Column("expected_checksum", sa.String(128), nullable=False),
        sa.Column("pull_trace_id", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_byte_size", sa.Integer),
        sa.Column("completed_checksum", sa.String(128)),
        sa.Column("ack_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("acked_at", sa.DateTime(timezone=True)),
        sa.Column("ack_idempotency_key", sa.String(128)),
        sa.Column("ack_request_fingerprint", sa.String(64)),
        sa.Column("ack_trace_id", sa.String(64)),
        sa.Column("received_byte_size", sa.Integer),
        sa.Column("received_checksum", sa.String(128)),
        sa.Column("byte_size_verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("checksum_verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("retention_expires_at_before", sa.DateTime(timezone=True)),
        sa.Column("retention_expires_at_after", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "site_id",
            "ack_idempotency_key",
            name="uq_media_artifact_deliveries_site_ack_key",
        ),
    )
    for field in (
        "artifact_id",
        "site_id",
        "pull_trace_id",
        "started_at",
        "ack_deadline_at",
        "ack_trace_id",
    ):
        sa.Index(
            f"ix_media_artifact_deliveries_{field}",
            deliveries.c[field],
        )
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        metadata.create_all(connection)
    return table


def _delivery_row(*, artifact_id: str) -> dict[str, object]:
    now = datetime(2026, 7, 15, 5, 0, tzinfo=UTC)
    return {
        "delivery_id": "mdl_legacy",
        "artifact_id": artifact_id,
        "site_id": "site_alpha",
        "expected_byte_size": 417,
        "expected_checksum": "sha256:" + ("a" * 64),
        "pull_trace_id": "trace-legacy",
        "started_at": now - timedelta(minutes=4),
        "completed_at": now - timedelta(minutes=3),
        "completed_byte_size": 417,
        "completed_checksum": "sha256:" + ("a" * 64),
        "ack_deadline_at": now + timedelta(minutes=10),
        "revoked_at": None,
        "acked_at": now - timedelta(minutes=2),
        "ack_idempotency_key": "idem-legacy",
        "ack_request_fingerprint": "f" * 64,
        "ack_trace_id": "trace-ack-legacy",
        "received_byte_size": 417,
        "received_checksum": "sha256:" + ("a" * 64),
        "byte_size_verified": True,
        "checksum_verified": True,
        "retention_expires_at_before": now + timedelta(minutes=20),
        "retention_expires_at_after": now + timedelta(minutes=5),
        "created_at": now - timedelta(minutes=4),
    }


def _row(*, artifact_id: str, storage_key: str) -> dict[str, object]:
    now = datetime(2026, 7, 15, 5, 0, tzinfo=UTC)
    return {
        "artifact_id": artifact_id,
        "run_id": "run_legacy",
        "site_id": "site_alpha",
        "media_kind": "image",
        "operation": "image.transform.v1",
        "content_type": "image/webp",
        "byte_size": 417,
        "checksum": "sha256:" + ("a" * 64),
        "storage_key": storage_key,
        "status": "purge_pending",
        "format": "webp",
        "width": 41,
        "height": 31,
        "processing_warnings_json": {"warnings": ["legacy-warning"], "nested": {"kept": True}},
        "expires_at": now - timedelta(minutes=5),
        "purged_at": None,
        "purge_attempt_count": 3,
        "purge_last_attempt_at": now - timedelta(minutes=2),
        "purge_next_attempt_at": now + timedelta(minutes=1),
        "purge_last_error_code": "artifact_store.delete_failed",
        "created_at": now - timedelta(hours=1),
    }


def _reflected_row(connection: sa.Connection, artifact_id: str) -> dict[str, object]:
    table = sa.Table("media_artifacts", sa.MetaData(), autoload_with=connection)
    row = (
        connection.execute(sa.select(table).where(table.c.artifact_id == artifact_id))
        .mappings()
        .one()
    )
    return dict(row)


def _driver_in_transaction(connection: sa.Connection) -> bool:
    return bool(connection.connection.driver_connection.in_transaction)


def _configure_migration(connection: sa.Connection, migration: ModuleType) -> None:
    context = MigrationContext.configure(connection)
    assert context.impl.transactional_ddl is False
    migration.op = Operations(context)


def _seed_committed_0064_data(engine: sa.Engine, table: sa.Table) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO alembic_version (version_num) VALUES ('20260715_0064')"
            )
        )
        connection.execute(sa.text("INSERT INTO run_records (run_id) VALUES ('run_legacy')"))
        connection.execute(
            table.insert().values(
                **_row(
                    artifact_id="art_legacy",
                    storage_key="obj_11111111111111111111111111111111",
                )
            )
        )
        deliveries = sa.Table(
            "media_artifact_deliveries",
            sa.MetaData(),
            autoload_with=connection,
        )
        connection.execute(deliveries.insert().values(**_delivery_row(artifact_id="art_legacy")))


def _delivery_snapshot(connection: sa.Connection) -> dict[str, object]:
    deliveries = sa.Table(
        "media_artifact_deliveries",
        sa.MetaData(),
        autoload_with=connection,
    )
    return dict(
        connection.execute(
            sa.select(deliveries).where(deliveries.c.delivery_id == "mdl_legacy")
        )
        .mappings()
        .one()
    )


def _schema_version(connection: sa.Connection) -> str:
    return str(connection.scalar(sa.text("SELECT version_num FROM alembic_version")))


def _set_schema_version(connection: sa.Connection, version: str) -> None:
    connection.execute(
        sa.text("UPDATE alembic_version SET version_num = :version"),
        {"version": version},
    )


def _assert_committed_shape(
    connection: sa.Connection,
    *,
    artifact_before: dict[str, object],
    delivery_before: dict[str, object],
    delivery_indexes_before: set[str],
    upgraded: bool,
) -> None:
    inspector = sa.inspect(connection)
    columns = {column["name"]: column for column in inspector.get_columns("media_artifacts")}
    expected_columns = set(artifact_before)
    if upgraded:
        expected_columns |= {"purge_claim_id", "purge_claim_expires_at"}
    assert set(columns) == expected_columns
    artifact_after = _reflected_row(connection, "art_legacy")
    assert {key: artifact_after[key] for key in artifact_before} == artifact_before
    if upgraded:
        assert artifact_after["purge_claim_id"] is None
        assert artifact_after["purge_claim_expires_at"] is None

    unique_names = {
        constraint["name"] for constraint in inspector.get_unique_constraints("media_artifacts")
    }
    check_names = {
        constraint["name"] for constraint in inspector.get_check_constraints("media_artifacts")
    }
    artifact_indexes = {
        index["name"] for index in inspector.get_indexes("media_artifacts")
    }
    if upgraded:
        assert "uq_media_artifacts_storage_key" in unique_names
        assert "ck_media_artifacts_purge_claim_pair" in check_names
        assert OLD_INDEXES | {"ix_media_artifacts_purge_claim_expires_at"} <= artifact_indexes
    else:
        assert "uq_media_artifacts_storage_key" not in unique_names
        assert "ck_media_artifacts_purge_claim_pair" not in check_names
        assert artifact_indexes == OLD_INDEXES

    assert _delivery_snapshot(connection) == delivery_before
    assert {
        index["name"]
        for index in inspector.get_indexes("media_artifact_deliveries")
    } == delivery_indexes_before
    assert any(
        foreign_key["constrained_columns"] == ["artifact_id"]
        and foreign_key["referred_table"] == "media_artifacts"
        and foreign_key["referred_columns"] == ["artifact_id"]
        for foreign_key in inspector.get_foreign_keys("media_artifact_deliveries")
    )
    assert not any(name.startswith("_alembic_tmp_") for name in inspector.get_table_names())
    assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
    assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    assert connection.exec_driver_sql("PRAGMA defer_foreign_keys").scalar_one() == 0


def test_0065_model_declares_named_storage_and_claim_invariants() -> None:
    table = MediaArtifact.__table__
    assert table.c.purge_claim_id.type.length == 64
    assert table.c.purge_claim_id.nullable is True
    assert table.c.purge_claim_expires_at.nullable is True
    assert any(
        constraint.name == "uq_media_artifacts_storage_key"
        and tuple(constraint.columns.keys()) == ("storage_key",)
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    )
    assert any(
        constraint.name == "ck_media_artifacts_purge_claim_pair"
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    )
    assert "ix_media_artifacts_purge_claim_expires_at" in {index.name for index in table.indexes}


def test_0065_sqlite_upgrade_and_downgrade_preserve_full_0064_shape(
    tmp_path: Path,
) -> None:
    engine = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / 'migration-roundtrip.sqlite3'}")
    table = _create_0064_schema(engine)
    _seed_committed_0064_data(engine, table)
    migration = _load()
    assert migration.revision == "20260715_0065"
    assert migration.down_revision == "20260715_0064"

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        before = _reflected_row(connection, "art_legacy")
        delivery_before = _delivery_snapshot(connection)
        delivery_indexes_before = {
            index["name"]
            for index in sa.inspect(connection).get_indexes("media_artifact_deliveries")
        }
        connection.rollback()

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
        assert _driver_in_transaction(connection) is False
        _configure_migration(connection, migration)
        migration.upgrade()
        assert _driver_in_transaction(connection) is True
        connection.commit()
        assert _driver_in_transaction(connection) is False
        _assert_committed_shape(
            connection,
            artifact_before=before,
            delivery_before=delivery_before,
            delivery_indexes_before=delivery_indexes_before,
            upgraded=True,
        )

        reflected = sa.Table("media_artifacts", sa.MetaData(), autoload_with=connection)
        with pytest.raises(IntegrityError):
            connection.execute(
                reflected.insert().values(
                    **_row(
                        artifact_id="art_duplicate",
                        storage_key="obj_11111111111111111111111111111111",
                    )
                )
            )
        with pytest.raises(IntegrityError):
            connection.execute(
                reflected.insert().values(
                    **_row(
                        artifact_id="art_malformed_claim",
                        storage_key="obj_22222222222222222222222222222222",
                    ),
                    purge_claim_id="pcl_malformed",
                    purge_claim_expires_at=None,
                )
            )
        connection.rollback()

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
        assert _driver_in_transaction(connection) is False
        _configure_migration(connection, migration)
        migration.downgrade()
        assert _driver_in_transaction(connection) is True
        connection.commit()
        assert _driver_in_transaction(connection) is False
        _assert_committed_shape(
            connection,
            artifact_before=before,
            delivery_before=delivery_before,
            delivery_indexes_before=delivery_indexes_before,
            upgraded=False,
        )


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_0065_sqlite_migration_failure_rolls_back_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    direction: str,
) -> None:
    engine = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / f'migration-{direction}.sqlite3'}")
    table = _create_0064_schema(engine)
    _seed_committed_0064_data(engine, table)
    migration = _load()

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
        before = _reflected_row(connection, "art_legacy")
        delivery_before = _delivery_snapshot(connection)
        delivery_indexes_before = {
            index["name"]
            for index in sa.inspect(connection).get_indexes("media_artifact_deliveries")
        }
        connection.rollback()

    if direction == "downgrade":
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
            _configure_migration(connection, migration)
            migration.upgrade()
            connection.commit()

    injected_error = RuntimeError(f"injected {direction} batch failure")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
        assert _driver_in_transaction(connection) is False
        _configure_migration(connection, migration)
        original_batch_alter_table = migration.op.batch_alter_table

        @contextmanager
        def fail_after_batch(*args: object, **kwargs: object):
            with original_batch_alter_table(*args, **kwargs) as batch:
                yield batch
            raise injected_error

        monkeypatch.setattr(migration.op, "batch_alter_table", fail_after_batch)
        with pytest.raises(RuntimeError) as captured:
            getattr(migration, direction)()
        assert captured.value is injected_error
        assert _driver_in_transaction(connection) is True
        assert connection.exec_driver_sql("PRAGMA defer_foreign_keys").scalar_one() == 0
        connection.rollback()
        assert _driver_in_transaction(connection) is False
        _assert_committed_shape(
            connection,
            artifact_before=before,
            delivery_before=delivery_before,
            delivery_indexes_before=delivery_indexes_before,
            upgraded=direction == "downgrade",
        )
        monkeypatch.setattr(migration.op, "batch_alter_table", original_batch_alter_table)
        getattr(migration, direction)()
        assert _driver_in_transaction(connection) is True
        connection.commit()
        _assert_committed_shape(
            connection,
            artifact_before=before,
            delivery_before=delivery_before,
            delivery_indexes_before=delivery_indexes_before,
            upgraded=direction == "upgrade",
        )


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_0065_success_restore_interrupt_rolls_back_and_can_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    direction: str,
) -> None:
    engine = sa.create_engine(
        f"sqlite+pysqlite:///{tmp_path / f'migration-restore-{direction}.sqlite3'}"
    )
    table = _create_0064_schema(engine)
    _seed_committed_0064_data(engine, table)
    migration = _load()

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
        artifact_before = _reflected_row(connection, "art_legacy")
        delivery_before = _delivery_snapshot(connection)
        delivery_indexes_before = {
            index["name"]
            for index in sa.inspect(connection).get_indexes("media_artifact_deliveries")
        }
        connection.rollback()

    source_version = "20260715_0064"
    target_version = "20260715_0065"
    source_upgraded = False
    if direction == "downgrade":
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
            _configure_migration(connection, migration)
            migration.upgrade()
            _set_schema_version(connection, "20260715_0065")
            connection.commit()
        source_version = "20260715_0065"
        target_version = "20260715_0064"
        source_upgraded = True

    injected_error = KeyboardInterrupt(f"injected {direction} restore interrupt")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
        assert _driver_in_transaction(connection) is False
        assert _schema_version(connection) == source_version
        connection.rollback()
        _configure_migration(connection, migration)
        original_exec_driver_sql = connection.exec_driver_sql
        foreign_key_check_succeeded = False

        def interrupt_restore(
            statement: str,
            *args: object,
            **kwargs: object,
        ) -> Any:
            nonlocal foreign_key_check_succeeded
            if (
                foreign_key_check_succeeded
                and statement.strip() == "PRAGMA defer_foreign_keys=OFF"
            ):
                raise injected_error
            result = original_exec_driver_sql(statement, *args, **kwargs)
            if statement.strip() == "PRAGMA foreign_key_check":
                foreign_key_check_succeeded = True
            return result

        monkeypatch.setattr(connection, "exec_driver_sql", interrupt_restore)
        with pytest.raises(KeyboardInterrupt) as captured:
            getattr(migration, direction)()

        assert captured.value is injected_error
        assert foreign_key_check_succeeded is True
        assert _driver_in_transaction(connection) is True
        monkeypatch.setattr(connection, "exec_driver_sql", original_exec_driver_sql)
        connection.rollback()
        assert _driver_in_transaction(connection) is False
        assert connection.exec_driver_sql("PRAGMA defer_foreign_keys").scalar_one() == 0
        assert _schema_version(connection) == source_version
        _assert_committed_shape(
            connection,
            artifact_before=artifact_before,
            delivery_before=delivery_before,
            delivery_indexes_before=delivery_indexes_before,
            upgraded=source_upgraded,
        )

        _configure_migration(connection, migration)
        getattr(migration, direction)()
        _set_schema_version(connection, target_version)
        connection.commit()
        assert _schema_version(connection) == target_version
        _assert_committed_shape(
            connection,
            artifact_before=artifact_before,
            delivery_before=delivery_before,
            delivery_indexes_before=delivery_indexes_before,
            upgraded=direction == "upgrade",
        )


def test_0065_duplicate_storage_key_fails_before_any_ddl(tmp_path: Path) -> None:
    engine = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / 'migration-duplicates.sqlite3'}")
    table = _create_0064_schema(engine)
    migration = _load()
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.execute(sa.text("INSERT INTO run_records (run_id) VALUES ('run_legacy')"))
        duplicate_key = "obj_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        connection.execute(
            table.insert(),
            [
                _row(artifact_id="art_duplicate_a", storage_key=duplicate_key),
                _row(artifact_id="art_duplicate_b", storage_key=duplicate_key),
            ],
        )

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
        assert _driver_in_transaction(connection) is False
        before_columns = {
            column["name"] for column in sa.inspect(connection).get_columns(table.name)
        }
        before_indexes = {index["name"] for index in sa.inspect(connection).get_indexes(table.name)}
        connection.rollback()
        _configure_migration(connection, migration)

        with pytest.raises(RuntimeError) as error:
            migration.upgrade()

        assert str(error.value) == RESET_ERROR
        assert duplicate_key not in str(error.value)
        assert _driver_in_transaction(connection) is True
        connection.rollback()
        assert _driver_in_transaction(connection) is False
        inspector = sa.inspect(connection)
        assert {column["name"] for column in inspector.get_columns(table.name)} == before_columns
        assert {index["name"] for index in inspector.get_indexes(table.name)} == before_indexes
        assert inspector.get_unique_constraints(table.name) == []
        assert inspector.get_check_constraints(table.name) == []
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM media_artifacts")) == 2
