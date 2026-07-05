from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select

import app.domain.catalog.service as catalog_service_module
from app.adapters.providers.base import (
    CatalogInstanceSeed,
    CatalogModelSeed,
    ProviderCatalogSnapshot,
)
from app.adapters.providers.minimax import (
    MINIMAX_OFFICIAL_SCHEMA_SOURCES,
    MiniMaxProviderAdapter,
)
from app.adapters.providers.openai import OpenAIProviderAdapter
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import CatalogRevision
from app.domain.catalog.service import CatalogService
from app.domain.hosted_model_defaults import (
    AUDIO_NARRATION_MODEL_ID,
    AUDIO_NARRATION_PROFILE_ID,
    GROK_IMAGINE_IMAGE_MODEL_ID,
    GROK_IMAGINE_IMAGE_PROFILE_ID,
    TEXT_AI_PROFILE_ID,
    VISION_AI_PROFILE_ID,
)
from app.domain.runtime.models import RuntimeRequest
from app.domain.runtime.service import RuntimeService
from tests.conftest import seed_openai_model_allowlist, seed_site_auth


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

    service = CatalogService(database_url, providers={"openai": OpenAIProviderAdapter()})
    refresh_result = service.refresh_catalog()
    models = service.list_models()

    assert refresh_result["refreshed_count"] == 1
    assert refresh_result["revision"].startswith("catalog-")
    assert models["total"] == 4

    dispose_engine(database_url)


def test_refresh_catalog_uses_one_unique_revision_for_multi_provider_batch(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    snapshots = {
        "openai": ProviderCatalogSnapshot(
            provider_id="openai",
            display_name="OpenAI Compatible",
            adapter_type="openai",
            models=[
                CatalogModelSeed(
                    model_id="gpt-4.1-mini",
                    family="gpt-4.1",
                    feature="text",
                    status="available",
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="openai-us-east-text-balanced",
                            endpoint_variant="chat_completions",
                            region="us-east",
                            capability_tags=["text", "balanced"],
                            weight=100,
                        )
                    ],
                )
            ],
        ),
        "tei": ProviderCatalogSnapshot(
            provider_id="tei",
            display_name="TEI",
            adapter_type="tei",
            models=[
                CatalogModelSeed(
                    model_id="BAAI/bge-m3",
                    family="bge",
                    feature="embedding",
                    status="available",
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="tei-cn-embedding-default",
                            endpoint_variant="embeddings",
                            region="cn",
                            capability_tags=["embedding", "default"],
                            weight=100,
                        )
                    ],
                )
            ],
        ),
    }
    service = CatalogService(
        database_url,
        providers={
            provider_id: SequenceCatalogProvider([snapshot])
            for provider_id, snapshot in snapshots.items()
        },
    )

    refresh_result = service.refresh_catalog(provider_ids=["openai", "tei"])

    assert refresh_result["refreshed_count"] == 2
    assert refresh_result["revision"].startswith("catalog-")
    assert len(refresh_result["revision"]) <= 64
    with get_session(database_url) as session:
        revisions = list(session.scalars(select(CatalogRevision)))
    assert [revision.revision for revision in revisions] == [refresh_result["revision"]]
    assert revisions[0].provider_id is None
    assert revisions[0].notes == "providers=openai,tei"

    dispose_engine(database_url)


def test_list_models_supports_feature_filter(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    service = CatalogService(database_url, providers={"openai": OpenAIProviderAdapter()})
    service.refresh_catalog()
    embedding_models = service.list_models(feature="embedding")

    assert embedding_models["total"] == 1
    assert embedding_models["items"][0]["model_id"] == "text-embedding-3-small"

    dispose_engine(database_url)


def test_list_models_returns_recommended_sets_and_profile_filter(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    service = CatalogService(database_url, providers={"openai": OpenAIProviderAdapter()})
    service.refresh_catalog()

    all_models = service.list_models()
    balanced_models = service.list_models(recommended_for="text.balanced")

    assert "recommended_sets" in all_models
    assert all_models["platform_models"]["surface"] == "platform_models"
    assert all_models["platform_models"]["total"] == 4
    assert all_models["recommended_sets"]["text.balanced"]["model_ids"] == ["gpt-4.1-mini"]
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
    assert all_models["recommended_sets"][GROK_IMAGINE_IMAGE_PROFILE_ID]["model_ids"] == [
        GROK_IMAGINE_IMAGE_MODEL_ID
    ]
    assert all_models["recommended_sets"][VISION_AI_PROFILE_ID]["model_ids"] == ["gpt-4.1"]

    dispose_engine(database_url)


def test_free_gpt55_profile_filters_to_free_hosted_model(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    service = CatalogService(
        database_url,
        providers={"openai": OpenAIProviderAdapter(sample_catalog_profile="free-gpt55")},
    )
    service.refresh_catalog()

    models = service.list_models(recommended_for="text.free-gpt55")

    assert models["recommended_sets"]["text.free-gpt55"]["model_ids"] == ["gpt-5.5"]
    assert models["recommended_sets"]["text.free-gpt55"]["instance_ids"] == [
        "openai-global-free-gpt55"
    ]
    assert models["total"] == 1
    assert models["items"][0]["model_id"] == "gpt-5.5"
    assert "text.free-gpt55" in models["items"][0]["recommended_profiles"]

    dispose_engine(database_url)


def test_text_ai_profile_filters_to_hosted_free_model_without_exact_model_pin(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    snapshot = ProviderCatalogSnapshot(
        provider_id="openai",
        display_name="OpenAI Compatible",
        adapter_type="openai",
        models=[
            CatalogModelSeed(
                model_id="gpt-hosted-free-next",
                family="gpt-hosted-free",
                feature="text",
                status="available",
                context_window=256000,
                price_input=0.0,
                price_output=0.0,
                fallback_candidate=True,
                raw_json={"tier": "quality", "surface": "hosted_free_tools"},
                instances=[
                    CatalogInstanceSeed(
                        instance_id="openai-global-hosted-free-next",
                        endpoint_variant="responses",
                        region="global",
                        capability_tags=["text", "quality", "hosted-free"],
                        is_default=True,
                        weight=140,
                    )
                ],
            )
        ],
    )
    service = CatalogService(
        database_url,
        providers={"openai": SequenceCatalogProvider([snapshot])},
    )
    service.refresh_catalog()

    models = service.list_models(recommended_for=TEXT_AI_PROFILE_ID)

    assert models["recommended_sets"][TEXT_AI_PROFILE_ID]["model_ids"] == [
        "gpt-hosted-free-next"
    ]
    assert models["recommended_sets"][TEXT_AI_PROFILE_ID]["instance_ids"] == [
        "openai-global-hosted-free-next"
    ]
    assert models["total"] == 1
    assert models["items"][0]["model_id"] == "gpt-hosted-free-next"
    assert TEXT_AI_PROFILE_ID in models["items"][0]["recommended_profiles"]

    dispose_engine(database_url)


def test_grok_image_quality_profile_filters_to_exact_image_model(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    snapshot = ProviderCatalogSnapshot(
        provider_id="openai",
        display_name="OpenAI Compatible",
        adapter_type="openai",
        models=[
            CatalogModelSeed(
                model_id="Qwen/Qwen-Image",
                family="qwen-image",
                feature="image_generation",
                status="available",
                instances=[
                    CatalogInstanceSeed(
                        instance_id="openai-global-qwen-qwen-image",
                        endpoint_variant="image_generations",
                        region="global",
                        capability_tags=["image_generation", "default", "quality"],
                        weight=100,
                    )
                ],
            ),
            CatalogModelSeed(
                model_id=GROK_IMAGINE_IMAGE_MODEL_ID,
                family="z-image",
                feature="image_generation",
                status="available",
                instances=[
                    CatalogInstanceSeed(
                        instance_id="openai-global-tongyi-mai-z-image-turbo",
                        endpoint_variant="image_generations",
                        region="global",
                        capability_tags=["image_generation", "default", "quality"],
                        weight=100,
                    )
                ],
            ),
            CatalogModelSeed(
                model_id="gpt-image-2",
                family="gpt-image",
                feature="image_generation",
                status="available",
                instances=[
                    CatalogInstanceSeed(
                        instance_id="openai-global-gpt-image-2",
                        endpoint_variant="image_generations",
                        region="global",
                        capability_tags=["image_generation", "default", "quality"],
                        weight=100,
                    )
                ],
            ),
        ],
    )
    service = CatalogService(
        database_url,
        providers={"openai": SequenceCatalogProvider([snapshot])},
    )

    service.refresh_catalog()
    models = service.list_models(recommended_for=GROK_IMAGINE_IMAGE_PROFILE_ID)

    recommended_set = models["recommended_sets"][GROK_IMAGINE_IMAGE_PROFILE_ID]
    assert recommended_set["model_ids"] == [GROK_IMAGINE_IMAGE_MODEL_ID]
    assert recommended_set["instance_ids"] == ["openai-global-tongyi-mai-z-image-turbo"]
    assert models["total"] == 1
    assert models["items"][0]["model_id"] == GROK_IMAGINE_IMAGE_MODEL_ID

    dispose_engine(database_url)


def test_audio_narration_profile_filters_to_minimax_audio_model(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    source_urls = {source.url for source in MINIMAX_OFFICIAL_SCHEMA_SOURCES}

    def minimax_handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) in source_urls:
            return httpx.Response(
                200,
                json={
                    "openapi": "3.1.0",
                    "components": {
                        "schemas": {
                            "Request": {
                                "properties": {"model": {"type": "string", "enum": []}}
                            }
                        }
                    },
                },
            )
        assert request.url.path.endswith("/v1/models")
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": AUDIO_NARRATION_MODEL_ID},
                    {"id": "MiniMax-M3"},
                ]
            },
        )

    service = CatalogService(
        database_url,
        providers={
            "minimax": MiniMaxProviderAdapter(
                api_key="test-api-key",
                group_id="test-group",
                transport=httpx.MockTransport(minimax_handler),
            )
        },
    )
    service.refresh_catalog()

    models = service.list_models(recommended_for=AUDIO_NARRATION_PROFILE_ID)

    recommended_set = models["recommended_sets"][AUDIO_NARRATION_PROFILE_ID]
    assert recommended_set["model_ids"] == [AUDIO_NARRATION_MODEL_ID]
    assert recommended_set["instance_ids"] == ["minimax-global-speech-28-turbo"]
    assert models["total"] == 1
    assert models["items"][0]["model_id"] == AUDIO_NARRATION_MODEL_ID
    assert AUDIO_NARRATION_PROFILE_ID in models["items"][0]["recommended_profiles"]

    dispose_engine(database_url)


def test_vision_ai_profile_filters_to_vision_model(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    service = CatalogService(database_url)
    service.refresh_catalog()

    models = service.list_models(recommended_for=VISION_AI_PROFILE_ID)

    recommended_set = models["recommended_sets"][VISION_AI_PROFILE_ID]
    assert recommended_set["model_ids"] == ["gpt-4.1"]
    assert recommended_set["instance_ids"] == ["openai-us-east-vision-default"]
    assert models["total"] == 1
    assert models["items"][0]["model_id"] == "gpt-4.1"
    assert VISION_AI_PROFILE_ID in models["items"][0]["recommended_profiles"]

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
    seed_openai_model_allowlist(database_url)
    seed_site_auth(database_url, site_id="site_alpha")
    runtime_service = RuntimeService(database_url)
    runtime_service.execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
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
