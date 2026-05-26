from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.secrets import resolve_provider_connection_secret


def test_provider_connection_secret_requires_explicit_value_by_default() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        admin_session_secret="a" * 32,
    )

    with pytest.raises(RuntimeError):
        resolve_provider_connection_secret(settings)


def test_provider_connection_secret_allows_dev_fallback_only_when_explicitly_enabled() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        admin_session_secret="a" * 32,
        allow_dev_provider_connection_secret_fallback=True,
    )

    assert resolve_provider_connection_secret(settings) == "a" * 32
