from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import app.domain.catalog.service as catalog_service_module
from app.adapters.repositories.catalog_repository import CatalogRepository
from app.adapters.providers.base import (
    CatalogInstanceSeed,
    CatalogModelSeed,
    ProviderCatalogSnapshot,
)
from app.adapters.providers.openai import OpenAIProviderAdapter
from app.core.db import dispose_engine, get_session, init_schema
from app.domain.catalog.service import CatalogService
from app.domain.runtime.models import RuntimeRequest
from app.domain.runtime.service import RuntimeService
from tests.conftest import seed_site_auth


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'catalog-domain.sqlite3'}"


class SequenceCatalogProvider:
    provider_id = "openai"
    display_name = "OpenAI Compatible"
    adapter_type = "openai"

    def __init__(self, snapshots: list[ProviderCatalogSnapshot]) -> None:
        self.snapshots = snapshots
        self.index = 0

    def fetch_catalog(self) -> ProviderCatalogSnapshot:
        snapshot = self.snapshots[min(self.index, len(self.snapshots) - 1)]
        self.index += 1
        return snapshot


def test_refresh_catalog_creates_revision_and_models(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    service = CatalogService(database_url)
    refresh_result = service.refresh_catalog()
    models = service.list_models()

    assert refresh_result["refreshed_count"] == 1
    assert refresh_result["revision"].startswith("catalog-")
    assert models["total"] == 3

    dispose_engine(database_url)


def test_list_models_supports_feature_filter(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    service = CatalogService(database_url)
    service.refresh_catalog()
    embedding_models = service.list_models(feature="embedding")

    assert embedding_models["total"] == 1
    assert embedding_models["items"][0]["model_id"] == "text-embedding-3-small"

    dispose_engine(database_url)


def test_list_models_returns_recommended_sets_and_profile_filter(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    service = CatalogService(database_url)
    service.refresh_catalog()

    all_models = service.list_models()
    balanced_models = service.list_models(recommended_for="text.balanced")

    assert "recommended_sets" in all_models
    assert all_models["platform_models"]["surface"] == "platform_models"
    assert all_models["platform_models"]["total"] == 3
    assert all_models["recommended_sets"]["text.balanced"]["model_ids"] == [
        "gpt-4.1-mini"
    ]
    assert balanced_models["recommended_for"] == "text.balanced"
    assert balanced_models["platform_models"]["recommended_for"] == "text.balanced"
    assert balanced_models["total"] == 1
    assert balanced_models["items"][0]["model_id"] == "gpt-4.1-mini"
    assert balanced_models["items"][0]["recommended_profiles"] == [
        "text.economy",
        "text.balanced",
        "text.quality",
    ]
    assert balanced_models["items"][0]["recommended_rank"] == 1

    dispose_engine(database_url)


def test_get_model_exposes_platform_model_alias(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    service = CatalogService(database_url)
    service.refresh_catalog()

    model = service.get_model("gpt-4.1-mini")

    assert model is not None
    assert model["platform_model"] == {
        "surface": "platform_models",
        "provider_id": "openai",
        "model_id": "gpt-4.1-mini",
    }

    dispose_engine(database_url)


def test_scan_provider_health_degrades_instance_after_failures(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    catalog_service = CatalogService(database_url)
    catalog_service.refresh_catalog()
    seed_site_auth(database_url, site_id="site_alpha")
    runtime_service = RuntimeService(database_url)
    runtime_service.execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="magick-ai/workflows/generate-post-draft",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            input_payload={
                "messages": [{"role": "user", "content": "degrade me"}],
                "simulate_error_for_instances": [
                    "openai-us-east-text-balanced",
                ],
            },
            policy={"allow_fallback": True},
            idempotency_key="catalog-health-001",
            trace_id="catalog-health-trace-001",
        )
    )

    result = catalog_service.scan_provider_health()
    model = catalog_service.get_model("gpt-4.1-mini")
    assert model is not None

    balanced_instance = next(
        instance
        for instance in model["instances"]
        if instance["instance_id"] == "openai-us-east-text-balanced"
    )
    assert balanced_instance["health_status"] == "degraded"
    assert result["status_counts"]["degraded"] >= 1

    dispose_engine(database_url)


def test_refresh_catalog_replaces_stale_provider_models_and_bindings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    first_snapshot = ProviderCatalogSnapshot(
        provider_id="openai",
        display_name="OpenAI Compatible",
        adapter_type="openai",
        models=[
            CatalogModelSeed(
                model_id="gpt-4.1-mini",
                family="gpt-4.1",
                feature="text",
                status="available",
                fallback_candidate=True,
                instances=[
                    CatalogInstanceSeed(
                        instance_id="openai-us-east-text-economy",
                        endpoint_variant="chat_completions",
                        region="us-east",
                        capability_tags=["text", "economy"],
                        weight=80,
                    ),
                    CatalogInstanceSeed(
                        instance_id="openai-us-east-text-balanced",
                        endpoint_variant="chat_completions",
                        region="us-east",
                        capability_tags=["text", "balanced"],
                        is_default=True,
                        weight=100,
                    ),
                ],
            )
        ],
    )
    second_snapshot = ProviderCatalogSnapshot(
        provider_id="openai",
        display_name="OpenAI Compatible",
        adapter_type="openai",
        models=[
            CatalogModelSeed(
                model_id="deepseek-chat",
                family="deepseek",
                feature="text",
                status="available",
                fallback_candidate=True,
                instances=[
                    CatalogInstanceSeed(
                        instance_id="deepseek-us-east-text-balanced",
                        endpoint_variant="chat_completions",
                        region="us-east",
                        capability_tags=["text", "balanced"],
                        is_default=True,
                        weight=100,
                    )
                ],
            ),
            CatalogModelSeed(
                model_id="deepseek-reasoner",
                family="deepseek",
                feature="text",
                status="available",
                fallback_candidate=True,
                instances=[
                    CatalogInstanceSeed(
                        instance_id="deepseek-us-east-text-quality",
                        endpoint_variant="chat_completions",
                        region="us-east",
                        capability_tags=["text", "quality"],
                        is_default=True,
                        weight=120,
                    )
                ],
            ),
        ],
    )

    provider = SequenceCatalogProvider([first_snapshot, second_snapshot])
    service = CatalogService(
        database_url,
        providers={"openai": provider},
    )

    class SequencedDateTime:
        values = iter(
            [
                datetime(2026, 3, 13, 2, 47, 23, tzinfo=UTC),
                datetime(2026, 3, 13, 2, 47, 24, tzinfo=UTC),
            ]
        )

        @classmethod
        def now(cls, tz=None):
            value = next(cls.values)
            if tz is None:
                return value.replace(tzinfo=None)
            return value.astimezone(tz)

    monkeypatch.setattr(catalog_service_module, "datetime", SequencedDateTime)

    service.refresh_catalog()
    service.refresh_catalog()

    all_models = service.list_models()
    balanced_models = service.list_models(recommended_for="text.balanced")

    assert [item["model_id"] for item in all_models["items"]] == [
        "deepseek-chat",
        "deepseek-reasoner",
    ]
    assert all_models["total"] == 2
    assert balanced_models["recommended_sets"]["text.balanced"]["model_ids"] == [
        "deepseek-chat",
        "deepseek-reasoner",
    ]
    assert balanced_models["recommended_sets"]["text.balanced"]["instance_ids"] == [
        "deepseek-us-east-text-balanced",
        "deepseek-us-east-text-quality",
    ]
    assert "gpt-4.1-mini" not in balanced_models["recommended_sets"]["text.balanced"]["model_ids"]

    dispose_engine(database_url)
