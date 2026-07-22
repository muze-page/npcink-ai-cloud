from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.setup.database import PostgreSQL18Validator
from app.setup.errors import SetupError
from app.setup.models import DatabaseInput


class _FakeResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one(self) -> object:
        return self.value

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[object]:
        assert isinstance(self.value, list)
        return self.value

    def __iter__(self) -> Iterator[object]:
        assert isinstance(self.value, list)
        return iter(self.value)


class _FakeTransaction:
    def __init__(self) -> None:
        self.rolled_back = False

    def rollback(self) -> None:
        self.rolled_back = True


class _FakeConnection:
    def __init__(
        self,
        *,
        version_number: int = 180000,
        tls_active: bool = True,
        relation_names: set[str] | None = None,
        marker_attempts: list[str] | None = None,
        fail_ddl: bool = False,
    ) -> None:
        self.version_number = version_number
        self.tls_active = tls_active
        self.relation_names = relation_names or set()
        self.marker_attempts = marker_attempts or []
        self.fail_ddl = fail_ddl
        self.transaction = _FakeTransaction()

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def begin(self) -> _FakeTransaction:
        return self.transaction

    def execute(self, statement: object, _parameters: object = None) -> _FakeResult:
        sql = str(statement)
        if sql == "SHOW server_version_num":
            return _FakeResult(self.version_number)
        if "FROM pg_stat_ssl" in sql:
            return _FakeResult(self.tls_active)
        if sql == "SHOW max_connections":
            return _FakeResult(100)
        if "FROM pg_class" in sql:
            return _FakeResult(sorted(self.relation_names))
        if "SELECT attempt_id" in sql:
            return _FakeResult(self.marker_attempts)
        if self.fail_ddl and sql.startswith("CREATE TABLE npcink_setup_probe_"):
            raise RuntimeError("permission denied and secret=db-password")
        return _FakeResult(None)


class _FakeEngine:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection
        self.disposed = False

    def connect(self) -> _FakeConnection:
        return self.connection

    def dispose(self) -> None:
        self.disposed = True


class _ValidatorWithFakeEngine(PostgreSQL18Validator):
    def __init__(self, engine: _FakeEngine) -> None:
        self.fake_engine = engine

    @staticmethod
    def _resolve_private_address(host: str, port: int) -> str:
        assert host.endswith(".rds.aliyuncs.com")
        assert port == 5432
        return "10.0.0.10"

    def _engine(self, database_url: str) -> Any:
        assert "sslmode=verify-full" in database_url
        assert "hostaddr=10.0.0.10" in database_url
        return self.fake_engine


def _database_input() -> DatabaseInput:
    return DatabaseInput.model_construct(
        host="rm-test.pg.rds.aliyuncs.com",
        port=5432,
        database="npcink",
        username="npcink",
        password=SecretStr("database-password"),
        ssl_mode="verify-full",
        ca_pem="unused-by-validator",
    )


def _validation_error_code(
    tmp_path: Path,
    connection: _FakeConnection,
    *,
    interrupted_attempt_id: str = "",
) -> str:
    engine = _FakeEngine(connection)
    validator = _ValidatorWithFakeEngine(engine)
    with pytest.raises(SetupError) as captured:
        validator.validate(
            _database_input(),
            ca_path=tmp_path / "rds-ca.pem",
            interrupted_attempt_id=interrupted_attempt_id,
        )
    assert engine.disposed is True
    assert connection.transaction.rolled_back is True
    assert "database-password" not in str(captured.value)
    return captured.value.error_code


def test_database_model_rejects_non_aliyun_rds_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.setup.models.ssl.create_default_context",
        lambda **_kwargs: object(),
    )

    with pytest.raises(ValidationError) as captured:
        DatabaseInput.model_validate(
            {
                "host": "postgres.internal.example.com",
                "port": 5432,
                "database": "npcink",
                "username": "npcink",
                "password": "database-password",
                "ssl_mode": "verify-full",
                "ca_pem": (
                    "-----BEGIN CERTIFICATE-----\nunused\n"
                    "-----END CERTIFICATE-----\n"
                ),
            }
        )

    assert any(error["loc"] == ("host",) for error in captured.value.errors())


@pytest.mark.parametrize("unsafe_address", ["8.8.8.8", "127.0.0.1"])
def test_database_dns_rejects_any_public_or_loopback_address(
    monkeypatch: pytest.MonkeyPatch,
    unsafe_address: str,
) -> None:
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.10", 5432)),
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (unsafe_address, 5432),
        ),
    ]
    monkeypatch.setattr(
        "app.core.runtime_config.socket.getaddrinfo",
        lambda *_args, **_kw: answers,
    )

    with pytest.raises(SetupError) as captured:
        PostgreSQL18Validator._resolve_private_address("rm-test.rds.aliyuncs.com", 5432)

    assert captured.value.error_code == "setup.database_unreachable"


def test_database_validator_rejects_postgresql_17(tmp_path: Path) -> None:
    assert _validation_error_code(
        tmp_path,
        _FakeConnection(version_number=170006),
    ) == "setup.database_version_unsupported"


def test_database_validator_rejects_connection_without_tls(tmp_path: Path) -> None:
    assert _validation_error_code(
        tmp_path,
        _FakeConnection(tls_active=False),
    ) == "setup.database_tls_required"


def test_database_validator_rejects_nonempty_database(tmp_path: Path) -> None:
    assert _validation_error_code(
        tmp_path,
        _FakeConnection(relation_names={"existing_business_table"}),
    ) == "setup.database_not_empty"


def test_database_validator_maps_ddl_permission_failure_without_leaking_details(
    tmp_path: Path,
) -> None:
    assert _validation_error_code(
        tmp_path,
        _FakeConnection(fail_ddl=True),
    ) == "setup.database_permissions_insufficient"
