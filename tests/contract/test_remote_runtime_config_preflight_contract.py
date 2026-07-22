from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT = ROOT / "deploy/remote-runtime-config-preflight.sh"


def _payload() -> str:
    source = PREFLIGHT.read_text(encoding="utf-8")
    start = source.index("from alembic.config import Config")
    end = source.index("\nPY' >/dev/null 2>&1", start)
    return source[start:end]


class _Result:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def scalar_one(self) -> object:
        assert len(self._rows) == 1 and len(self._rows[0]) == 1
        return self._rows[0][0]

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._rows)


class _Connection:
    def __init__(self, *, server_version_num: int, revisions: set[str]) -> None:
        self.server_version_num = server_version_num
        self.revisions = revisions

    def execute(self, statement: object) -> _Result:
        sql = str(statement)
        if "SHOW server_version_num" in sql:
            return _Result([(self.server_version_num,)])
        if "SELECT version_num FROM alembic_version" in sql:
            return _Result([(revision,) for revision in sorted(self.revisions)])
        raise AssertionError(f"unexpected preflight SQL: {sql}")


class _Engine:
    def __init__(self, connection: _Connection) -> None:
        self._connection = connection

    def connect(self):  # type: ignore[no-untyped-def]
        return nullcontext(self._connection)


def _execute_payload(
    monkeypatch: pytest.MonkeyPatch,
    *,
    server_version_num: int = 180000,
    revisions: set[str] | None = None,
    connection_error: Exception | None = None,
) -> dict[str, Any]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from app.core import config as config_module
    from app.core import db as db_module

    head = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_heads()[0]
    settings = SimpleNamespace(
        database_url=(
            "postgresql+psycopg://app:redacted@db.internal:5432/cloud"
            "?sslmode=verify-full&sslrootcert=/run/npcink-config/rds-ca.pem"
        ),
        database_pool_size=2,
        database_max_overflow=1,
        database_pool_timeout_seconds=10,
        database_pool_recycle_seconds=1800,
        database_connect_timeout_seconds=5,
    )
    observed: dict[str, Any] = {}

    def fake_get_engine(database_url: str, **kwargs: object) -> _Engine:
        observed["database_url"] = database_url
        observed["engine_kwargs"] = kwargs
        if connection_error is not None:
            raise connection_error
        return _Engine(
            _Connection(
                server_version_num=server_version_num,
                revisions=revisions if revisions is not None else {head},
            )
        )

    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    monkeypatch.setattr(db_module, "get_engine", fake_get_engine)
    monkeypatch.chdir(ROOT)
    exec(compile(_payload(), str(PREFLIGHT), "exec"), {"__name__": "__main__"})
    return observed


def test_real_candidate_preflight_payload_accepts_pg18_tls_and_known_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = _execute_payload(monkeypatch)

    assert "sslmode=verify-full" in observed["database_url"]
    assert "sslrootcert=/run/npcink-config/rds-ca.pem" in observed["database_url"]
    assert observed["engine_kwargs"] == {
        "pool_size": 2,
        "max_overflow": 1,
        "pool_timeout_seconds": 10,
        "pool_recycle_seconds": 1800,
        "connect_timeout_seconds": 5,
    }


def test_real_candidate_preflight_payload_rejects_pg17(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(SystemExit) as caught:
        _execute_payload(monkeypatch, server_version_num=170006)

    assert caught.value.code == 2


@pytest.mark.parametrize("revisions", [set(), {"unknown_revision"}, {"a", "b"}])
def test_real_candidate_preflight_payload_rejects_unupgradeable_revision_state(
    monkeypatch: pytest.MonkeyPatch,
    revisions: set[str],
) -> None:
    with pytest.raises(SystemExit) as caught:
        _execute_payload(monkeypatch, revisions=revisions)

    assert caught.value.code == 3


def test_real_candidate_preflight_payload_fails_closed_on_tls_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ConnectionError, match="certificate verify failed"):
        _execute_payload(
            monkeypatch,
            connection_error=ConnectionError("certificate verify failed"),
        )


def test_preflight_shell_binds_real_payload_to_exact_candidate_image_and_redacts_errors() -> None:
    source = PREFLIGHT.read_text(encoding="utf-8")

    assert "loaded-role-daemon-id" in source
    assert '--root "${ROOT_DIR}" --role api' in source
    assert "npcink_ai_cloud_compose_run_with_image_proof" in source
    assert 'api npcink-ai-cloud-api:prod "${EXPECTED_API_IMAGE_ID}"' in source
    assert "from app.core.config import get_settings" in _payload()
    assert "from app.core.db import get_engine" in _payload()
    assert "require_upgradeable_revisions" in _payload()
    assert "PY' >/dev/null 2>&1" in source
    assert "Candidate image could not prove protected runtime config" in source
