from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, init_schema
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from tests.conftest import build_auth_headers, seed_site_auth


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'addon-projection-contract.sqlite3'}"


def _build_client(tmp_path: Path) -> tuple[str, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    CatalogService(database_url).scan_provider_health()
    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    return database_url, TestClient(create_app(CloudServices(settings=settings)))


def test_addon_projection_surfaces_are_absent(tmp_path: Path) -> None:
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

    assert dashboard.status_code == 404
    assert provider.status_code == 404

    dispose_engine(database_url)


def test_release_smoke_does_not_depend_on_removed_addon_projection_surfaces() -> None:
    cloud_root = Path(__file__).resolve().parents[2]
    release_smoke_script = (cloud_root / "deploy" / "release-smoke.sh").read_text()

    assert "/v1/addon/dashboard" not in release_smoke_script
    assert "/v1/addon/providers/release-summary" not in release_smoke_script
    assert "deploy/remote-smoke.sh" in release_smoke_script
