from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.adapters.repositories.catalog_repository import CatalogRepository
from app.core.config import Settings
from app.core.db import get_session, init_schema
from app.workers.model_intelligence_publisher import inspect_publisher_state_at, run_once


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'publisher-worker.sqlite3'}"


def test_model_intelligence_publisher_worker_persists_bundle_publication(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    bundle_path = tmp_path / "output" / "model-intelligence.bundle.json"
    summary_path = tmp_path / "output" / "run-summary.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        json.dumps(
            {
                "bundle_kind": "model_intelligence_bundle_v1",
                "schema_version": "model_intelligence_bundle_v1",
                "generated_at": "2026-04-06T08:00:00Z",
                "checksum": "abc123def4567890",
                "sources": [
                    {
                        "source_id": "openrouter",
                        "status": "ok",
                        "fetched_at": "2026-04-06T07:59:00Z",
                    },
                    {
                        "source_id": "ollama",
                        "status": "ok",
                        "fetched_at": "2026-04-06T07:59:10Z",
                    },
                ],
                "models": [
                    {
                        "provider": "openrouter",
                        "model_id": "openai/gpt-4.1-mini",
                        "display_name": "gpt-4.1-mini",
                        "model_type": "chat",
                        "preview_type": "text",
                        "supports": ["text"],
                        "capability_profile": "chat",
                        "price_reference_kind": "exact",
                        "price_input": 0.4,
                        "price_output": 1.6,
                        "price_tier": "low",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(
            {
                "status": "success",
                "started_at": "2026-04-06T07:58:00Z",
                "generated_at": "2026-04-06T08:00:00Z",
                "sources": [
                    {
                        "source_id": "openrouter",
                        "records_total": 350,
                        "checksum": "s1",
                        "cached_fallback_used": False,
                    },
                    {
                        "source_id": "ollama",
                        "records_total": 34,
                        "checksum": "s2",
                        "cached_fallback_used": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    def publisher_runner(*args: object, **kwargs: object) -> None:
        return None

    result = run_once(
        Settings(
            _env_file=None,
            project_name="Magick AI Cloud Test",
            environment="test",
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
            model_intelligence_bundle_path=str(bundle_path),
            model_intelligence_run_summary_path=str(summary_path),
        ),
        publisher_runner=publisher_runner,
    )

    assert result["source"] == "model_intelligence_publisher_worker"
    assert result["status"] == "ok"
    assert result["records_total"] == 1
    assert result["source_keys"] == ["openrouter", "ollama"]
    assert result["revision"].startswith("publisher-2026-04-06T08:00:00Z-abc123def456")

    with get_session(database_url) as session:
        repository = CatalogRepository(session)
        publications = repository.list_recent_recognition_snapshot_publications(limit=5)
        source_runs = repository.list_recent_recognition_source_runs(limit=5)

    assert len(publications) == 1
    assert publications[0].records_total == 1
    assert publications[0].source_keys_json == ["openrouter", "ollama"]
    assert publications[0].record_keys_json == ["openrouter::openai/gpt-4.1-mini"]
    assert publications[0].metadata_json["source_kind"] == "publisher_bundle"
    assert len(source_runs) == 2
    assert {row.source_name for row in source_runs} == {"openrouter", "ollama"}


def test_model_intelligence_publisher_state_reads_bundle_and_latest_publication(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    bundle_path = tmp_path / "output" / "model-intelligence.bundle.json"
    summary_path = tmp_path / "output" / "run-summary.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        json.dumps(
            {
                "bundle_kind": "model_intelligence_bundle_v1",
                "schema_version": "model_intelligence_bundle_v1",
                "generated_at": "2026-04-06T08:00:00Z",
                "checksum": "abc123def4567890",
                "sources": [{"source_id": "openrouter", "status": "ok", "fetched_at": "2026-04-06T07:59:00Z"}],
                "models": [],
            }
        ),
        encoding="utf-8",
    )
    summary_path.write_text(json.dumps({"status": "success"}), encoding="utf-8")

    run_once(
        Settings(
            _env_file=None,
            project_name="Magick AI Cloud Test",
            environment="test",
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
            model_intelligence_bundle_path=str(bundle_path),
            model_intelligence_run_summary_path=str(summary_path),
        ),
        publisher_runner=lambda *args, **kwargs: None,
    )

    state = inspect_publisher_state_at(
        Settings(
            _env_file=None,
            project_name="Magick AI Cloud Test",
            environment="test",
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
            model_intelligence_publisher_enabled=True,
            model_intelligence_bundle_path=str(bundle_path),
            model_intelligence_run_summary_path=str(summary_path),
        ),
        now_factory=lambda: datetime(2026, 4, 6, 10, 0, tzinfo=UTC),
    )

    assert state["configured"] is True
    assert state["enabled"] is True
    assert state["bundle_exists"] is True
    assert state["run_summary_exists"] is True
    assert state["source_keys"] == ["openrouter"]
    assert state["failed_sources"] == []
    assert state["freshness_status"] == "fresh"
    assert state["hours_old"] == 2.0
    assert state["health_status"] == "ok"
    assert state["health_issues"] == []
    assert state["fallback"]["previous_bundle_used"] is False
    assert state["latest_publication"]["metadata"]["source_kind"] == "publisher_bundle"
    assert state["latest_publication"]["freshness_status"] == "fresh"
    assert len(state["recent_publications"]) == 1


def test_model_intelligence_publisher_state_marks_stale_and_failed_sources(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    bundle_path = tmp_path / "output" / "model-intelligence.bundle.json"
    summary_path = tmp_path / "output" / "run-summary.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        json.dumps(
            {
                "bundle_kind": "model_intelligence_bundle_v1",
                "schema_version": "model_intelligence_bundle_v1",
                "generated_at": "2026-04-04T00:00:00Z",
                "checksum": "abc123def4567890",
                "sources": [
                    {"source_id": "openrouter", "status": "ok", "fetched_at": "2026-04-04T00:00:00Z"},
                    {"source_id": "huggingface", "status": "error", "fetched_at": "2026-04-04T00:00:00Z"},
                ],
                "models": [],
            }
        ),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(
            {
                "status": "partial",
                "failed_sources": [{"source_id": "huggingface", "error": "timeout"}],
            }
        ),
        encoding="utf-8",
    )

    state = inspect_publisher_state_at(
        Settings(
            _env_file=None,
            project_name="Magick AI Cloud Test",
            environment="test",
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
            model_intelligence_publisher_enabled=True,
            model_intelligence_bundle_path=str(bundle_path),
            model_intelligence_run_summary_path=str(summary_path),
        ),
        now_factory=lambda: datetime(2026, 4, 6, 13, 0, tzinfo=UTC),
    )

    assert state["freshness_status"] == "expired"
    assert state["hours_old"] == 61.0
    assert state["failed_sources"] == ["huggingface"]
    assert state["health_status"] == "error"
    assert "bundle_expired" in state["health_issues"]
    assert "source_failures_present" in state["health_issues"]
