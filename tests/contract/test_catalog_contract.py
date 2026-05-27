from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, init_schema
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from tests.conftest import (
    TEST_INTERNAL_AUTH_TOKEN,
    build_auth_headers,
    build_internal_headers,
    seed_site_auth,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'catalog-contract.sqlite3'}"


def test_catalog_models_response_shape_is_stable(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_site_auth(database_url, site_id="site_contract", scopes=["catalog:read"])

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    response = client.get(
        "/v1/catalog/models",
        headers=build_auth_headers(
            "GET",
            "/v1/catalog/models",
            site_id="site_contract",
            trace_id="tracecatalogcontract001000000000",
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"status", "error_code", "message", "data", "meta"}
    assert set(payload["data"].keys()) == {
        "items",
        "total",
        "revision",
        "recommended_sets",
        "recommended_for",
        "platform_models",
    }

    model = payload["data"]["items"][0]
    assert set(model.keys()) == {
        "model_id",
        "provider_id",
        "family",
        "feature",
        "status",
        "context_window",
        "price_input",
        "price_output",
        "is_deprecated",
        "fallback_candidate",
        "revision",
        "recommended_profiles",
        "platform_model",
    }
    assert set(payload["data"]["platform_models"].keys()) == {
        "surface",
        "total",
        "recommended_for",
    }
    assert set(model["platform_model"].keys()) == {
        "surface",
        "provider_id",
        "model_id",
    }

    assert set(payload["data"]["recommended_sets"]["text.balanced"].keys()) == {
        "profile_id",
        "model_ids",
        "instance_ids",
    }

    dispose_engine(database_url)


