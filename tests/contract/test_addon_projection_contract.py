from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, init_schema
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from tests.conftest import TEST_PROVIDER_CONNECTION_SECRET, build_auth_headers, seed_site_auth


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'addon-projection-contract.sqlite3'}"


def _build_client(tmp_path: Path) -> tuple[str, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    CatalogService(database_url).scan_provider_health()
    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        provider_connection_secret=TEST_PROVIDER_CONNECTION_SECRET,
    )
    return database_url, TestClient(create_app(CloudServices(settings=settings)))


def test_addon_projection_contract_exposes_freshness_semantics(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(database_url, site_id="site_alpha", scopes=["stats:read"])

    dashboard = client.get(
        "/v1/addon/dashboard",
        headers=build_auth_headers(
            "GET",
            "/v1/addon/dashboard",
            site_id="site_alpha",
            trace_id="addonprojectioncontractdashboard",
        ),
    )
    provider = client.get(
        "/v1/addon/providers/release-summary",
        headers=build_auth_headers(
            "GET",
            "/v1/addon/providers/release-summary",
            site_id="site_alpha",
            trace_id="addonprojectioncontractprovider0",
        ),
    )

    assert dashboard.status_code == 200
    assert provider.status_code == 200

    dashboard_data = dashboard.json()["data"]
    provider_data = provider.json()["data"]

    for payload in (dashboard_data, provider_data):
        assert set(("source", "generated_at", "fresh_until", "stale", "generation_ms")) <= set(
            payload.keys()
        )
        assert payload["source"] in {"projection", "live_fallback"}
        assert isinstance(payload["generated_at"], str) and payload["generated_at"]
        assert isinstance(payload["fresh_until"], str) and payload["fresh_until"]
        assert isinstance(payload["stale"], bool)
        assert isinstance(payload["generation_ms"], int)
        if payload["source"] == "live_fallback":
            assert isinstance(payload.get("fallback_reason"), str)
            assert payload["fallback_reason"] in {
                "projection_missing",
                "projection_stale",
                "projection_error",
            }

    dispose_engine(database_url)
