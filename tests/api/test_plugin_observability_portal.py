from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import get_session, init_schema
from app.core.models import (
    PluginObservabilityEvent,
)
from app.core.services import CloudServices
from app.domain.commercial.service import CommercialService
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
    seed_site_auth,
)
from tests.conftest import (
    build_portal_headers as _build_portal_headers,
)

_PORTAL_GRANT: dict[str, object] = {}


def build_portal_headers(**kwargs: object) -> dict[str, str]:
    if "principal_id" not in kwargs and _PORTAL_GRANT:
        kwargs["principal_id"] = str(_PORTAL_GRANT["principal_id"])
        kwargs["session_version"] = int(_PORTAL_GRANT.get("session_version") or 1)
    return _build_portal_headers(**kwargs)


def _build_client(tmp_path: Path) -> tuple[str, TestClient]:
    _PORTAL_GRANT.clear()
    database_url = f"sqlite+pysqlite:///{tmp_path / 'plugin-obs-portal.sqlite3'}"
    init_schema(database_url)
    seed_site_auth(database_url, site_id="site-portal-001", scopes=["stats:read"])
    seed_site_auth(database_url, site_id="site-portal-002", scopes=["stats:read"])
    _PORTAL_GRANT.update(
        CommercialService(database_url).upsert_principal_access(
        site_id="site-portal-001",
        email="portal-admin@example.com",
        metadata_json={"source": "test"},
        )
    )
    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
    )
    return database_url, TestClient(create_app(CloudServices(settings=settings)))


def _seed_plugin_events(database_url: str) -> None:
    now = datetime.now(UTC)
    with get_session(database_url) as session:
        session.add_all(
            [
                PluginObservabilityEvent(
                    dedupe_key="dedupe-portal-001",
                    site_id="site-portal-001",
                    key_id="key_default",
                    schema_version="2026-06-01",
                    plugin_slug="npcink-governance-core",
                    plugin_version="0.1.0",
                    source="local",
                    event_kind="preflight.completed",
                    event_id="evt_portal_001",
                    status="ok",
                    latency_ms=25,
                    proposal_id="proposal-001",
                    captured_at=now - timedelta(minutes=5),
                    received_at=now - timedelta(minutes=5),
                ),
                PluginObservabilityEvent(
                    dedupe_key="dedupe-portal-002",
                    site_id="site-portal-001",
                    key_id="key_default",
                    schema_version="2026-06-01",
                    plugin_slug="npcink-ai-client-adapter",
                    plugin_version="0.1.0",
                    source="local",
                    event_kind="openclaw.dispatch.failed",
                    event_id="evt_portal_002",
                    status="error",
                    error_code="adapter.dispatch_failed",
                    route="/openclaw",
                    latency_ms=500,
                    payload_json={"sensitive": "excluded"},
                    captured_at=now - timedelta(minutes=3),
                    received_at=now - timedelta(minutes=3),
                ),
                PluginObservabilityEvent(
                    dedupe_key="dedupe-portal-003",
                    site_id="site-portal-002",
                    key_id="key_default",
                    schema_version="2026-06-01",
                    plugin_slug="npcink-abilities-toolkit",
                    plugin_version="0.1.0",
                    source="local",
                    event_kind="ability.callback.completed",
                    event_id="evt_portal_003",
                    status="ok",
                    latency_ms=15,
                    captured_at=now - timedelta(minutes=2),
                    received_at=now - timedelta(minutes=2),
                ),
            ]
        )
        session.commit()


def test_portal_plugin_observability_returns_current_site_summary(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    _seed_plugin_events(database_url)

    response = client.get(
        "/portal/v1/sites/site-portal-001/plugin-observability?window_hours=24",
        headers=build_portal_headers(),
    )

    assert response.status_code == 200
    envelope = response.json()
    assert envelope["status"] == "ok"
    data = envelope["data"]
    assert data["contract_version"] == "magick-plugin-observability-summary-v1"
    assert data["site_id"] == "site-portal-001"
    assert data["account_id"] == "acct_site-portal-001"
    assert data["totals"]["events_total"] == 2
    assert data["totals"]["error_total"] == 1
    assert data["health"]["status"] == "error"
    assert isinstance(data["attention"], list)
    assert "attention_workflow" in data
    assert all("attention_key" in item for item in data["attention"])
    assert all(item["workflow_status"] == "active" for item in data["attention"])
    assert any(item["code"] == "plugin_observability.plugin_error" for item in data["attention"])
    assert data["digest"]["period_label"] == "daily"
    assert data["digest"]["top_error_code"] == "adapter.dispatch_failed"
    assert {item["plugin_slug"] for item in data["plugins"]} == {
        "npcink-governance-core",
        "npcink-ai-client-adapter",
    }
    assert isinstance(data["timeline"], list)
    assert sum(item["events_total"] for item in data["timeline"]) == 2
    assert sum(item["error_total"] for item in data["timeline"]) == 1
    assert "sites" not in data
    assert data["errors"][0]["error_code"] == "adapter.dispatch_failed"
    assert "payload_json" not in data["recent_errors"][0]
    assert "payload" not in data["recent_errors"][0]


def test_portal_plugin_observability_rejects_other_site(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    _seed_plugin_events(database_url)

    response = client.get(
        "/portal/v1/sites/site-portal-002/plugin-observability?window_hours=24",
        headers=build_portal_headers(),
    )

    assert response.status_code == 403
    assert response.json()["status"] == "error"


def test_portal_plugin_observability_filters_plugin(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    _seed_plugin_events(database_url)

    response = client.get(
        "/portal/v1/sites/site-portal-001/plugin-observability"
        "?window_hours=24&plugin_slug=npcink-governance-core",
        headers=build_portal_headers(),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["totals"]["events_total"] == 1
    assert [item["plugin_slug"] for item in data["plugins"]] == ["npcink-governance-core"]
