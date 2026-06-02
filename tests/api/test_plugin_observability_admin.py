from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import get_session, init_schema
from app.core.models import PluginObservabilityEvent
from app.core.services import CloudServices
from tests.conftest import build_internal_headers, seed_site_auth


def _build_client(tmp_path: Path) -> tuple[str, TestClient]:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'plugin-obs-admin.sqlite3'}"
    init_schema(database_url)
    seed_site_auth(database_url, site_id="site-001", scopes=["stats:read"])
    seed_site_auth(database_url, site_id="site-002", scopes=["stats:read"])
    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    return database_url, TestClient(create_app(CloudServices(settings=settings)))


def _seed_plugin_events(database_url: str) -> None:
    now = datetime.now(UTC)
    events = [
        PluginObservabilityEvent(
            dedupe_key="dedupe-admin-001",
            site_id="site-001",
            key_id="key_default",
            schema_version="2026-06-01",
            plugin_slug="magick-ai-abilities",
            plugin_version="0.1.0",
            source="local",
            event_kind="abilities.callback.completed",
            event_id="evt_admin_001",
            status="ok",
            latency_ms=15,
            ability_id="magick-ai/create-draft",
            captured_at=now - timedelta(minutes=5),
            received_at=now - timedelta(minutes=5),
        ),
        PluginObservabilityEvent(
            dedupe_key="dedupe-admin-002",
            site_id="site-001",
            key_id="key_default",
            schema_version="2026-06-01",
            plugin_slug="magick-ai-abilities",
            plugin_version="0.1.0",
            source="local",
            event_kind="abilities.callback.failed",
            event_id="evt_admin_002",
            status="error",
            error_code="abilities.callback_timeout",
            latency_ms=5000,
            ability_id="magick-ai/create-draft",
            payload_json={"sensitive": "data"},
            captured_at=now - timedelta(minutes=3),
            received_at=now - timedelta(minutes=3),
        ),
        PluginObservabilityEvent(
            dedupe_key="dedupe-admin-003",
            site_id="site-002",
            key_id="key_default",
            schema_version="2026-06-01",
            plugin_slug="magick-ai-core",
            plugin_version="0.1.0",
            source="local",
            event_kind="core.proposal.create",
            event_id="evt_admin_003",
            status="ok",
            latency_ms=10,
            ability_id="magick-ai/generate",
            captured_at=now - timedelta(minutes=10),
            received_at=now - timedelta(minutes=10),
        ),
        PluginObservabilityEvent(
            dedupe_key="dedupe-admin-004",
            site_id="site-002",
            key_id="key_default",
            schema_version="2026-06-01",
            plugin_slug="magick-ai-core",
            plugin_version="0.1.0",
            source="local",
            event_kind="core.proposal.create",
            event_id="evt_admin_004",
            status="ok",
            latency_ms=25,
            ability_id="magick-ai/generate",
            payload_json={"extra": "info"},
            captured_at=now - timedelta(minutes=8),
            received_at=now - timedelta(minutes=8),
        ),
    ]
    with get_session(database_url) as session:
        session.add_all(events)
        session.commit()


def test_admin_plugin_observability_returns_cross_site_aggregation(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    _seed_plugin_events(database_url)
    response = client.get(
        "/internal/service/admin/plugin-observability?window_hours=24",
        headers=build_internal_headers(trace_id="traceadmin0010000000000000000000"),
    )
    assert response.status_code == 200
    envelope = response.json()
    assert envelope["status"] == "ok"
    data = envelope["data"]
    assert data["contract_version"] == "magick-plugin-observability-admin-summary-v1"
    assert "generated_at" in data
    assert "window" in data
    assert "hours" in data["window"]
    assert "start_at" in data["window"]
    assert "end_at" in data["window"]
    totals = data["totals"]
    assert totals["events_total"] == 4
    assert totals["ok_total"] == 3
    assert totals["error_total"] == 1
    assert "success_rate" in totals
    assert "avg_latency_ms" in totals
    assert "last_seen_at" in totals
    assert totals["active_site_count"] == 2
    assert totals["active_plugin_count"] == 2
    assert isinstance(data["plugins"], list)
    assert isinstance(data["sites"], list)
    assert isinstance(data["errors"], list)
    assert isinstance(data["recent_errors"], list)


def test_admin_plugin_observability_rejects_without_internal_token(tmp_path: Path) -> None:
    _, client = _build_client(tmp_path)
    response = client.get(
        "/internal/service/admin/plugin-observability?window_hours=24",
        headers={},
    )
    assert response.status_code in (401, 403)
    assert response.json()["status"] == "error"


def test_admin_plugin_observability_site_id_filter(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    _seed_plugin_events(database_url)
    response = client.get(
        "/internal/service/admin/plugin-observability?window_hours=24&site_id=site-001",
        headers=build_internal_headers(trace_id="traceadmin0020000000000000000000"),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    for site in data["sites"]:
        assert site["site_id"] == "site-001"


def test_admin_plugin_observability_plugin_slug_filter(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    _seed_plugin_events(database_url)
    response = client.get(
        "/internal/service/admin/plugin-observability?window_hours=24&plugin_slug=magick-ai-abilities",
        headers=build_internal_headers(trace_id="traceadmin0030000000000000000000"),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    for plugin in data["plugins"]:
        assert plugin["plugin_slug"] == "magick-ai-abilities"


def test_admin_plugin_observability_errors_exclude_payload_json(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    _seed_plugin_events(database_url)
    response = client.get(
        "/internal/service/admin/plugin-observability?window_hours=24",
        headers=build_internal_headers(trace_id="traceadmin0040000000000000000000"),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    for error_item in data["errors"]:
        assert "payload_json" not in error_item
        assert "payload" not in error_item
    assert data["recent_errors"][0]["site_id"] == "site-001"
    for recent_error in data["recent_errors"]:
        assert "payload_json" not in recent_error
        assert "payload" not in recent_error


def test_admin_plugin_observability_empty_data_returns_zero_counts(tmp_path: Path) -> None:
    _, client = _build_client(tmp_path)
    response = client.get(
        "/internal/service/admin/plugin-observability?window_hours=24",
        headers=build_internal_headers(trace_id="traceadmin0050000000000000000000"),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["totals"]["events_total"] == 0
    assert data["totals"]["ok_total"] == 0
    assert data["totals"]["error_total"] == 0
    assert data["plugins"] == []
    assert data["sites"] == []
    assert data["errors"] == []
    assert data["recent_errors"] == []


def test_admin_plugin_observability_invalid_window_hours(tmp_path: Path) -> None:
    _, client = _build_client(tmp_path)
    response = client.get(
        "/internal/service/admin/plugin-observability?window_hours=999",
        headers=build_internal_headers(trace_id="traceadmin0060000000000000000000"),
    )
    assert response.status_code == 422
