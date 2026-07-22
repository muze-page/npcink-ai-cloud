from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool

from app.core.models import Base
from app.core.runtime_config import (
    RuntimeConfigError,
    build_database_url,
    resolve_private_database_address,
)
from app.setup.errors import SetupError
from app.setup.models import DatabaseInput

INSTALL_MARKER_TABLE = "npcink_first_install_marker"


@dataclass(frozen=True, slots=True)
class DatabaseValidationResult:
    postgres_major_version: int
    ssl_mode: str
    database_empty: bool
    alembic_state: str
    latency_ms: int
    max_connections: int
    database_url: str

    def public_payload(self) -> dict[str, object]:
        return {
            "postgres_major_version": self.postgres_major_version,
            "ssl_mode": self.ssl_mode,
            "database_empty": self.database_empty,
            "alembic_state": self.alembic_state,
            "latency_ms": self.latency_ms,
            "max_connections": self.max_connections,
        }


class PostgreSQL18Validator:
    def validate(
        self,
        database: DatabaseInput,
        *,
        ca_path: Path,
        interrupted_attempt_id: str = "",
    ) -> DatabaseValidationResult:
        hostaddr = self._resolve_private_address(database.host, database.port)
        database_url = build_database_url(
            database.connection_components(),
            ca_path=ca_path,
            hostaddr=hostaddr,
        )
        engine = self._engine(database_url)
        started_at = time.monotonic()
        try:
            with engine.connect() as connection:
                transaction = connection.begin()
                try:
                    version_number = int(
                        connection.execute(text("SHOW server_version_num")).scalar_one()
                    )
                    major_version = version_number // 10000
                    if major_version != 18:
                        raise SetupError(
                            422,
                            "setup.database_version_unsupported",
                            "PostgreSQL 18 is required",
                        )
                    tls_active = bool(
                        connection.execute(
                            text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
                        ).scalar_one()
                    )
                    if not tls_active:
                        raise SetupError(
                            422,
                            "setup.database_tls_required",
                            "verified database TLS is required",
                        )
                    max_connections = int(
                        connection.execute(text("SHOW max_connections")).scalar_one()
                    )
                    relation_names = self._relation_names(connection)
                    database_empty, alembic_state = self._classify_database(
                        connection,
                        relation_names=relation_names,
                        interrupted_attempt_id=interrupted_attempt_id,
                    )
                    self._probe_ddl_permissions(connection)
                finally:
                    transaction.rollback()
        except SetupError:
            raise
        except Exception as error:
            raise SetupError(
                422,
                "setup.database_unreachable",
                "database validation failed",
            ) from error
        finally:
            engine.dispose()
        latency_ms = max(0, int((time.monotonic() - started_at) * 1000))
        return DatabaseValidationResult(
            postgres_major_version=18,
            ssl_mode="verify-full",
            database_empty=database_empty,
            alembic_state=alembic_state,
            latency_ms=latency_ms,
            max_connections=max_connections,
            database_url=database_url,
        )

    def ensure_attempt_marker(self, database_url: str, *, attempt_id: str) -> None:
        engine = self._engine(database_url)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        f"CREATE TABLE IF NOT EXISTS {INSTALL_MARKER_TABLE} "
                        "(attempt_id varchar(64) PRIMARY KEY)"
                    )
                )
                existing = connection.execute(
                    text(f"SELECT attempt_id FROM {INSTALL_MARKER_TABLE}")
                ).scalars().all()
                if existing and existing != [attempt_id]:
                    raise SetupError(
                        409,
                        "setup.database_not_empty",
                        "database belongs to another installation attempt",
                    )
                if not existing:
                    connection.execute(
                        text(
                            f"INSERT INTO {INSTALL_MARKER_TABLE} (attempt_id) "
                            "VALUES (:attempt_id)"
                        ),
                        {"attempt_id": attempt_id},
                    )
        finally:
            engine.dispose()

    def remove_attempt_marker(self, database_url: str) -> None:
        engine = self._engine(database_url)
        try:
            with engine.begin() as connection:
                connection.execute(text(f"DROP TABLE IF EXISTS {INSTALL_MARKER_TABLE}"))
        finally:
            engine.dispose()

    def run_migrations(self, database_url: str) -> None:
        engine = self._engine(database_url)
        try:
            with engine.connect() as connection:
                config = AlembicConfig(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
        except Exception as error:
            raise SetupError(500, "setup.migration_failed", "database migration failed") from error
        finally:
            engine.dispose()

    @staticmethod
    def _engine(database_url: str) -> Engine:
        return create_engine(
            database_url,
            future=True,
            hide_parameters=True,
            pool_pre_ping=True,
            poolclass=NullPool,
        )

    @staticmethod
    def _resolve_private_address(host: str, port: int) -> str:
        try:
            return resolve_private_database_address(host, port)
        except RuntimeConfigError as error:
            raise SetupError(
                422,
                "setup.database_unreachable",
                "database hostname must resolve only to private addresses",
            ) from error

    @staticmethod
    def _relation_names(connection: Connection) -> set[str]:
        rows = connection.execute(
            text(
                "SELECT c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' "
                "AND c.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')"
            )
        ).scalars()
        return {str(item) for item in rows}

    def _classify_database(
        self,
        connection: Connection,
        *,
        relation_names: set[str],
        interrupted_attempt_id: str,
    ) -> tuple[bool, str]:
        if not relation_names:
            return True, "empty"
        if not interrupted_attempt_id or INSTALL_MARKER_TABLE not in relation_names:
            raise SetupError(409, "setup.database_not_empty", "database must be empty")
        marker_attempts = connection.execute(
            text(f"SELECT attempt_id FROM {INSTALL_MARKER_TABLE}")
        ).scalars().all()
        if marker_attempts != [interrupted_attempt_id]:
            raise SetupError(409, "setup.database_not_empty", "database must be empty")
        model_tables = {table.name for table in Base.metadata.sorted_tables}
        allowed = model_tables | {"alembic_version", INSTALL_MARKER_TABLE}
        unexpected = {
            name
            for name in relation_names
            if name not in allowed
            and not any(
                name.startswith(f"{table_name}_") and name.endswith("_seq")
                for table_name in model_tables
            )
        }
        if unexpected:
            raise SetupError(409, "setup.database_not_empty", "database must be empty")
        alembic_state = "interrupted" if "alembic_version" in relation_names else "empty"
        return False, alembic_state

    @staticmethod
    def _probe_ddl_permissions(connection: Connection) -> None:
        suffix = str(int(time.time_ns()))
        table_name = f"npcink_setup_probe_{suffix}"
        sequence_name = f"npcink_setup_probe_seq_{suffix}"
        try:
            connection.execute(text(f"CREATE TABLE {table_name} (id bigint PRIMARY KEY)"))
            connection.execute(text(f"CREATE INDEX {table_name}_idx ON {table_name} (id)"))
            connection.execute(text(f"CREATE SEQUENCE {sequence_name}"))
        except Exception as error:
            raise SetupError(
                422,
                "setup.database_permissions_insufficient",
                "database account lacks required schema permissions",
            ) from error
