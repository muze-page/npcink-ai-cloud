from __future__ import annotations

from pathlib import Path

from app.core.db import dispose_engine, init_schema
from app.domain.catalog.service import CatalogService
from app.domain.routing.service import RoutingService


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'routing-domain.sqlite3'}"


def test_routing_service_prefers_balanced_text_instance(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()

    resolution = RoutingService(database_url).resolve(
        profile_id="text.balanced",
        execution_kind="text",
    )

    assert resolution.profile_id == "text.balanced"
    assert resolution.default_policy["timeout_ms"] == 30000
    assert resolution.selected_candidate.instance_id == "openai-us-east-text-balanced"
    assert [candidate.instance_id for candidate in resolution.candidates] == [
        "openai-us-east-text-balanced",
        "openai-us-east-text-economy",
        "openai-us-east-text-quality",
    ]

    dispose_engine(database_url)
