from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.core.db import dispose_engine, init_schema
from app.domain.commercial.service import CommercialService
from app.workers import recognition_evidence_daemon


def test_recognition_evidence_daemon_skips_refresh_when_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'daemon-disabled.sqlite3'}"
    init_schema(database_url)
    calls: list[dict[str, object]] = []
    publisher_calls: list[dict[str, object]] = []
    sleeps: list[float] = []

    def fake_run_once(settings):
        calls.append({"settings": settings})
        return {"status": "ok"}

    def fake_publisher_run_once(settings):
        publisher_calls.append({"settings": settings})
        return {"status": "ok"}

    monkeypatch.setattr(recognition_evidence_daemon, "run_once", fake_run_once)
    monkeypatch.setattr(
        recognition_evidence_daemon,
        "run_model_intelligence_publisher",
        fake_publisher_run_once,
    )

    recognition_evidence_daemon.run_forever(
        Settings(
            project_name="Magick AI Cloud Test",
            environment="test",
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
            recognition_evidence_worker_enabled=False,
            recognition_evidence_worker_poll_seconds=300,
        ),
        sleep_fn=lambda seconds: sleeps.append(seconds),
        max_cycles=1,
    )

    assert calls == []
    assert publisher_calls == []
    assert sleeps == []
    dispose_engine(database_url)


def test_recognition_evidence_daemon_runs_refresh_when_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'daemon-enabled.sqlite3'}"
    init_schema(database_url)
    calls: list[dict[str, object]] = []
    publisher_calls: list[dict[str, object]] = []
    sleeps: list[float] = []

    def fake_run_once(settings):
        calls.append({"settings": settings})
        return {"status": "ok", "records_total": 3}

    def fake_publisher_run_once(settings):
        publisher_calls.append({"settings": settings})
        return {"status": "ok", "records_total": 10}

    monkeypatch.setattr(recognition_evidence_daemon, "run_once", fake_run_once)
    monkeypatch.setattr(
        recognition_evidence_daemon,
        "run_model_intelligence_publisher",
        fake_publisher_run_once,
    )

    recognition_evidence_daemon.run_forever(
        Settings(
            project_name="Magick AI Cloud Test",
            environment="test",
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
            recognition_evidence_worker_enabled=True,
            recognition_evidence_worker_poll_seconds=300,
        ),
        sleep_fn=lambda seconds: sleeps.append(seconds),
        max_cycles=1,
    )

    assert len(calls) == 1
    assert publisher_calls == []
    assert sleeps == []
    dispose_engine(database_url)


def test_recognition_evidence_daemon_runs_publisher_when_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'daemon-publisher-enabled.sqlite3'}"
    init_schema(database_url)
    calls: list[dict[str, object]] = []
    publisher_calls: list[dict[str, object]] = []
    sleeps: list[float] = []

    def fake_run_once(settings):
        calls.append({"settings": settings})
        return {"status": "ok", "records_total": 3}

    def fake_publisher_run_once(settings):
        publisher_calls.append({"settings": settings})
        return {"status": "ok", "records_total": 10}

    monkeypatch.setattr(recognition_evidence_daemon, "run_once", fake_run_once)
    monkeypatch.setattr(
        recognition_evidence_daemon,
        "run_model_intelligence_publisher",
        fake_publisher_run_once,
    )

    recognition_evidence_daemon.run_forever(
        Settings(
            project_name="Magick AI Cloud Test",
            environment="test",
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
            recognition_evidence_worker_enabled=False,
            model_intelligence_publisher_enabled=True,
            recognition_evidence_worker_poll_seconds=300,
        ),
        sleep_fn=lambda seconds: sleeps.append(seconds),
        max_cycles=1,
    )

    assert calls == []
    assert len(publisher_calls) == 1
    assert sleeps == []
    dispose_engine(database_url)


def test_recognition_evidence_daemon_records_worker_heartbeat(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'recognition-daemon.sqlite3'}"
    init_schema(database_url)

    monkeypatch.setattr(
        recognition_evidence_daemon,
        "run_once",
        lambda settings: {"status": "ok", "records_total": 1},
    )
    monkeypatch.setattr(
        recognition_evidence_daemon,
        "run_model_intelligence_publisher",
        lambda settings: {"status": "ok", "published_total": 1},
    )

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        recognition_evidence_worker_enabled=True,
        model_intelligence_publisher_enabled=True,
        recognition_evidence_worker_poll_seconds=300,
        worker_heartbeat_interval_seconds=60,
    )
    recognition_evidence_daemon.run_forever(
        settings,
        sleep_fn=lambda seconds: None,
        max_cycles=1,
    )

    events = CommercialService(database_url, settings=settings).list_service_audit_events(
        event_kind="worker.heartbeat",
        limit=10,
    )["items"]
    assert any(item["scope_id"] == "recognition_evidence" for item in events)
    dispose_engine(database_url)
    database_url = f"sqlite+pysqlite:///{tmp_path / 'daemon-disabled.sqlite3'}"
    init_schema(database_url)

    database_url = f"sqlite+pysqlite:///{tmp_path / 'daemon-enabled.sqlite3'}"
    init_schema(database_url)

    database_url = f"sqlite+pysqlite:///{tmp_path / 'daemon-publisher-enabled.sqlite3'}"
    init_schema(database_url)
