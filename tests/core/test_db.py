from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from app.core import db as db_module


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'db-core.sqlite3'}"


def test_get_engine_hides_sql_parameters(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    engine = db_module.get_engine(database_url)

    try:
        assert engine.hide_parameters is True
    finally:
        db_module.dispose_engine(database_url)


def test_database_connection_failure_returns_stable_non_sensitive_error_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "postgresql://db-user:db-password@private-db/cloud"

    class _FailingEngine:
        def connect(self) -> Any:
            raise OperationalError(
                "SELECT :private_value",
                {"private_value": secret},
                RuntimeError(f"could not connect to {secret}"),
            )

    monkeypatch.setattr(db_module, "get_engine", lambda _database_url: _FailingEngine())

    ok, detail = db_module.check_database_connection(secret)

    assert ok is False
    assert detail == "OperationalError"
    assert secret not in detail

    with pytest.raises(RuntimeError) as error_info:
        db_module.require_database_connection(secret)
    assert str(error_info.value) == "database is not reachable: OperationalError"
    assert secret not in str(error_info.value)


def test_database_engine_creation_failure_uses_stable_non_sensitive_error_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "postgresql://db-user:db-password@private-db:not-a-port/cloud"

    def fail_engine_creation(_database_url: str) -> Any:
        raise ValueError(f"invalid database URL: {secret}")

    monkeypatch.setattr(db_module, "get_engine", fail_engine_creation)

    ok, detail = db_module.check_database_connection(secret)

    assert ok is False
    assert detail == "ValueError"
    assert secret not in detail

    with pytest.raises(RuntimeError) as error_info:
        db_module.require_database_connection(secret)
    assert str(error_info.value) == "database is not reachable: ValueError"
    assert secret not in str(error_info.value)
