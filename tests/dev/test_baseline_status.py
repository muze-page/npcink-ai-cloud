from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.core.db import dispose_engine, init_schema
from app.dev.baseline_status import evaluate_remote_baseline_status, load_remote_baseline_status


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'baseline-status.sqlite3'}"


def test_baseline_status_reports_missing_alembic_version_table(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    report = evaluate_remote_baseline_status(
        Settings(
            _env_file=None,
            environment="production",
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
            internal_auth_token="i" * 32,
            admin_bootstrap_token="b" * 32,
            admin_session_secret="a" * 32,
            portal_jwt_secret="j" * 32,
            browser_origin_allowlist="https://cloud.example.com",
            trusted_host_allowlist="cloud.example.com",
        )
    )

    assert report["status"] == "fail"
    assert report["alembic"]["version_table_present"] is False
    assert "alembic_version_missing" in report["failures"]

    dispose_engine(database_url)


def test_baseline_status_returns_structured_config_failure_for_missing_prod_secret() -> None:
    def _load_invalid_settings() -> Settings:
        return Settings(
            _env_file=None,
            environment="production",
            database_url="sqlite+pysqlite:///:memory:",
            redis_url="redis://localhost:6379/0",
            internal_auth_token="i" * 32,
            admin_session_secret="",
        )

    report = load_remote_baseline_status(settings_loader=_load_invalid_settings)

    assert report["status"] == "fail"
    assert report["failures"] == ["settings_validation_error"]
    assert report["config_errors"]
    assert any(
        "admin_session_secret is required" in item["message"] for item in report["config_errors"]
    )
    assert report["schema"]["missing_tables"] == []
    assert report["alembic"]["expected_heads"]
