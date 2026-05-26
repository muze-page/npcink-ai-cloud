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


def test_get_recognition_bundle_applies_manual_curation_overrides(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    service = CatalogService(database_url)
    service.refresh_catalog()
    bundle = service.get_recognition_bundle()

    model = next(item for item in bundle["models"] if item["model_id"] == "gpt-4.1")

    assert bundle["sources"]["recognition_derivation"] == "catalog_service_v2"
    assert bundle["schema_version"] == "recognition_bundle_v1"
    assert bundle["sources"]["upstream_evidence_version"] == "recognition_upstream_v1"
    assert bundle["sources"]["litellm_revision"] == "seed-2026-03-29"
    assert bundle["sources"]["hf_snapshot"] == "seed-2026-03-29"
    assert bundle["sources"]["ollama_snapshot"] == "unconfigured"
    assert "openai:gpt-4.1" in model["match_keys"]
    assert model["model_type"] == "vision"
    assert model["preview_type"] == "text"
    assert model["capabilities"]["image_input"] is True
    assert model["capabilities"]["vision"] is True
    assert model["confidence"] == 0.99
    assert any(evidence["source"] == "litellm_seed" for evidence in model["evidence"])
    assert any(
        evidence["source"] == "manual_curation" for evidence in model["evidence"]
    )

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


def test_get_recognition_bundle_applies_family_and_raw_metadata_hints(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    provider = SequenceCatalogProvider(
        [
            ProviderCatalogSnapshot(
                provider_id="openai",
                display_name="OpenAI Compatible",
                adapter_type="openai",
                models=[
                    CatalogModelSeed(
                        model_id="llava:13b",
                        family="llava",
                        feature="text",
                        status="available",
                        fallback_candidate=True,
                        raw_json={"catalog_source": "sample"},
                        instances=[
                            CatalogInstanceSeed(
                                instance_id="llava-us-east-text-balanced",
                                endpoint_variant="chat_completions",
                                region="us-east",
                                capability_tags=["vision"],
                                is_default=True,
                            )
                        ],
                    ),
                    CatalogModelSeed(
                        model_id="flux-dev",
                        family="flux",
                        feature="text",
                        status="available",
                        fallback_candidate=False,
                        raw_json={"pipeline_tag": "text-to-image"},
                        instances=[
                            CatalogInstanceSeed(
                                instance_id="flux-us-east-image-default",
                                endpoint_variant="images",
                                region="us-east",
                                capability_tags=["image"],
                                is_default=True,
                            )
                        ],
                    ),
                    CatalogModelSeed(
                        model_id="bge-m3",
                        family="bge",
                        feature="embedding",
                        status="available",
                        fallback_candidate=True,
                        raw_json={"catalog_source": "sample"},
                        instances=[
                            CatalogInstanceSeed(
                                instance_id="bge-us-east-embedding-default",
                                endpoint_variant="embeddings",
                                region="us-east",
                                capability_tags=["embedding"],
                                is_default=True,
                            )
                        ],
                    ),
                ],
            )
        ]
    )
    service = CatalogService(
        database_url,
        providers={"openai": provider},
    )
    service.refresh_catalog()
    bundle = service.get_recognition_bundle()

    llava = next(item for item in bundle["models"] if item["model_id"] == "llava:13b")
    flux = next(item for item in bundle["models"] if item["model_id"] == "flux-dev")
    bge = next(item for item in bundle["models"] if item["model_id"] == "bge-m3")

    assert llava["model_type"] == "vision"
    assert llava["preview_type"] == "text"
    assert llava["capabilities"]["image_input"] is True
    assert any(evidence["source"] == "family_hint" for evidence in llava["evidence"])
    assert any(
        evidence["source"] == "huggingface_alias_bridge_family_match"
        for evidence in llava["evidence"]
    )

    assert flux["model_type"] == "image_generation"
    assert flux["preview_type"] == "image"
    assert flux["output_modalities"] == ["image"]
    assert flux["capabilities"]["image_output"] is True
    assert any(
        evidence["source"] == "provider_raw_json" for evidence in flux["evidence"]
    )
    assert any(
        evidence["source"] == "huggingface_alias_bridge_name_match"
        for evidence in flux["evidence"]
    )
    assert any(
        evidence["source"] == "huggingface_alias_bridge_exact_repo"
        for evidence in bge["evidence"]
    )

    dispose_engine(database_url)


def test_get_recognition_bundle_prefers_configured_upstream_snapshot(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    snapshot_path = tmp_path / "recognition-upstream-snapshot.json"
    snapshot_path.write_text(
        """
{
  "version": "snapshot-v1",
  "generated_at": "2026-03-29T09:00:00Z",
  "sources": {
    "litellm_revision": "snapshot-litellm-001",
    "hf_snapshot": "snapshot-hf-001"
  },
  "records": {
    "custom_provider::custom-model": {
      "evidence_source": "hf_snapshot_seed",
      "model_type": "image_generation",
      "preview_type": "image",
      "input_modalities": ["text"],
      "output_modalities": ["image"],
      "capabilities": {
        "text_input": true,
        "image_output": true
      },
      "confidence": 0.93
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    provider = SequenceCatalogProvider(
        [
            ProviderCatalogSnapshot(
                provider_id="custom_provider",
                display_name="Custom Provider",
                adapter_type="openai",
                models=[
                    CatalogModelSeed(
                        model_id="custom-model",
                        family="custom-family",
                        feature="text",
                        status="available",
                        fallback_candidate=True,
                        raw_json={"catalog_source": "sample"},
                        instances=[
                            CatalogInstanceSeed(
                                instance_id="custom-provider-text-default",
                                endpoint_variant="chat_completions",
                                region="us-east",
                                capability_tags=["text"],
                                is_default=True,
                            )
                        ],
                    )
                ],
            )
        ]
    )
    service = CatalogService(
        database_url,
        providers={"custom_provider": provider},
        recognition_evidence_snapshot_path=str(snapshot_path),
    )
    service.refresh_catalog()
    bundle = service.get_recognition_bundle()

    model = next(item for item in bundle["models"] if item["model_id"] == "custom-model")

    assert bundle["sources"]["upstream_evidence_version"] == "snapshot-v1"
    assert bundle["sources"]["litellm_revision"] == "snapshot-litellm-001"
    assert bundle["sources"]["hf_snapshot"] == "snapshot-hf-001"
    assert bundle["sources"]["ollama_snapshot"] == "unconfigured"
    assert len(bundle["models"]) == 1
    assert bundle["models"][0]["source"] == "cloud_intelligence"
    assert bundle["source_runs"] == []
    assert model["model_type"] == "image_generation"
    assert model["preview_type"] == "image"
    assert model["output_modalities"] == ["image"]
    assert model["capabilities"]["image_output"] is True
    assert any(
        evidence["source"] == "hf_snapshot_seed" for evidence in model["evidence"]
    )

    dispose_engine(database_url)


def test_get_recognition_bundle_prefers_publisher_bundle_over_snapshot(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    snapshot_path = tmp_path / "recognition-upstream-snapshot.json"
    snapshot_path.write_text(
        """
{
  "version": "snapshot-v1",
  "generated_at": "2026-03-29T09:00:00Z",
  "sources": {
    "hf_snapshot": "snapshot-hf-001"
  },
  "records": {
    "huggingface::BAAI/bge-m3": {
      "provider": "huggingface",
      "model_id": "BAAI/bge-m3",
      "evidence_source": "huggingface_model_info",
      "model_type": "embedding",
      "preview_type": "embedding",
      "input_modalities": ["text"],
      "output_modalities": ["embedding"],
      "capabilities": {
        "text_input": true,
        "image_input": false,
        "image_output": false,
        "vision": false,
        "tools": false,
        "structured_output": false
      },
      "confidence": 0.9
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    bundle_path = tmp_path / "output" / "model-intelligence.bundle.json"
    summary_path = tmp_path / "output" / "run-summary.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        """
{
  "bundle_kind": "model_intelligence_bundle_v1",
  "schema_version": "model_intelligence_bundle_v1",
  "generated_at": "2026-04-09T02:42:53Z",
  "checksum": "publisher-bundle-checksum-001",
  "sources": [
    {
      "source_id": "openrouter",
      "status": "success",
      "fetched_at": "2026-04-09T02:42:53Z",
      "records_total": 1
    }
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
      "aliases": ["openai/gpt-4.1-mini", "gpt-4.1-mini"],
      "source_ids": ["openrouter"],
      "price_reference_kind": "exact",
      "price_input": 0.4,
      "price_output": 1.6,
      "price_tier": "low",
      "price_summary": "输入 $0.4000 / 输出 $1.6000（每 1M tokens）",
      "short_description": "适合通用文本对话、写作和推理任务。",
      "best_for": "通用问答、写作与推理",
      "why_recommended": "来自 publisher bundle。",
      "updated_at": "2026-04-09T02:42:53Z"
    }
  ]
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps({"status": "success", "failed_sources": []}),
        encoding="utf-8",
    )

    service = CatalogService(
        database_url,
        settings=catalog_service_module.Settings(
            _env_file=None,
            project_name="Magick AI Cloud Test",
            environment="test",
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
            model_intelligence_bundle_path=str(bundle_path),
            model_intelligence_run_summary_path=str(summary_path),
        ),
        recognition_evidence_snapshot_path=str(snapshot_path),
    )
    service.refresh_catalog()
    bundle = service.get_recognition_bundle()

    assert bundle["sources"]["recognition_derivation"] == "publisher_bundle"
    assert len(bundle["models"]) == 1
    assert bundle["models"][0]["provider"] == "openrouter"
    assert bundle["models"][0]["source"] == "publisher_bundle"

    dispose_engine(database_url)


def test_admin_models_include_annotations_and_allow_updates(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    service = CatalogService(database_url)
    service.refresh_catalog()

    initial = service.list_admin_models()
    target = next(item for item in initial["items"] if item["model_id"] == "gpt-4.1-mini")

    assert initial["platform_models"]["surface"] == "platform_models"
    assert target["platform_model"]["surface"] == "platform_models"
    assert target["annotation"]["recommended"] is False
    assert target["recognition"]["matched"] is True
    assert target["recognition_review"]["review_status"] == "pending"

    updated = service.upsert_admin_model_annotation(
        model_id="gpt-4.1-mini",
        recommended=True,
        cost_tier="budget",
        visibility="advanced",
        badges=["recommended", "cheap"],
        operator_notes="Default hosted draft pick",
    )

    assert updated is not None
    assert updated["annotation"]["recommended"] is True
    assert updated["annotation"]["cost_tier"] == "budget"
    assert updated["annotation"]["visibility"] == "advanced"
    assert updated["annotation"]["badges"] == ["recommended", "cheap"]

    refreshed = service.get_admin_model("gpt-4.1-mini")

    assert refreshed is not None
    assert refreshed["annotation"]["recommended"] is True
    assert refreshed["annotation"]["operator_notes"] == "Default hosted draft pick"
    assert refreshed["recognition_bundle"]["revision"]
    assert refreshed["recognition_review"]["review_status"] == "pending"

    dispose_engine(database_url)


def test_admin_recognition_models_include_annotations_and_hosted_catalog_presence(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    snapshot_path = tmp_path / "recognition-snapshot.json"
    snapshot_path.write_text(
        """
{
  "version": "recognition_upstream_snapshot_v1",
  "generated_at": "2026-03-30T12:00:00Z",
  "sources": {
    "litellm_revision": "snapshot-litellm-001",
    "hf_snapshot": "snapshot-hf-001",
    "ollama_snapshot": "unconfigured"
  },
  "source_runs": [
    {
      "source": "litellm",
      "run_id": "litellm:2026-03-30T12:00:00Z",
      "status": "ok",
      "generated_at": "2026-03-30T12:00:00Z",
      "records_fetched": 1,
      "records_accepted": 1,
      "duration_ms": 12
    },
    {
      "source": "huggingface",
      "run_id": "huggingface:2026-03-30T12:00:00Z",
      "status": "ok",
      "generated_at": "2026-03-30T12:00:00Z",
      "records_fetched": 1,
      "records_accepted": 1,
      "duration_ms": 9
    }
  ],
  "source_run_ids": [
    "litellm:2026-03-30T12:00:00Z",
    "huggingface:2026-03-30T12:00:00Z"
  ],
  "source_failures": [],
  "records": {
    "openai::gpt-4.1-mini": {
      "evidence_source": "litellm_model_info",
      "model_type": "vision",
      "preview_type": "text",
      "input_modalities": ["text", "image"],
      "output_modalities": ["text"],
      "capabilities": {
        "text_input": true,
        "image_input": true,
        "vision": true
      },
      "confidence": 0.95
    },
    "huggingface::black-forest-labs/FLUX.1-dev": {
      "evidence_source": "huggingface_model_info",
      "model_type": "image_generation",
      "preview_type": "image",
      "input_modalities": ["text"],
      "output_modalities": ["image"],
      "capabilities": {
        "text_input": true,
        "image_output": true
      },
      "confidence": 0.9
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    service = CatalogService(
        database_url,
        recognition_evidence_snapshot_path=str(snapshot_path),
    )
    service.refresh_catalog()
    with get_session(database_url) as session:
        repository = CatalogRepository(session)
        repository.upsert_recognition_snapshot_publication(
            revision="recognition-intelligence-20260330115500",
            checksum="checksum-prev",
            generated_at=datetime(2026, 3, 30, 11, 55, tzinfo=UTC),
            records_total=1,
            source_keys_json=["hf_snapshot"],
            source_run_ids_json=["huggingface:2026-03-30T11:55:00Z"],
            record_keys_json=["huggingface::black-forest-labs/FLUX.1-dev"],
            metadata_json=None,
        )
        repository.upsert_recognition_snapshot_publication(
            revision="recognition-intelligence-20260330120000",
            checksum="checksum-current",
            generated_at=datetime(2026, 3, 30, 12, 0, tzinfo=UTC),
            records_total=2,
            source_keys_json=["hf_snapshot", "litellm_revision"],
            source_run_ids_json=[
                "litellm:2026-03-30T12:00:00Z",
                "huggingface:2026-03-30T12:00:00Z",
            ],
            record_keys_json=[
                "openai::gpt-4.1-mini",
                "huggingface::black-forest-labs/FLUX.1-dev",
            ],
            metadata_json=None,
        )
        repository.upsert_recognition_source_run(
            run_id="openrouter:2026-03-30T12:05:00Z",
            source_name="openrouter",
            snapshot_generated_at=datetime(2026, 3, 30, 12, 5, tzinfo=UTC),
            started_at=datetime(2026, 3, 30, 12, 4, 59, tzinfo=UTC),
            finished_at=datetime(2026, 3, 30, 12, 5, tzinfo=UTC),
            status="ok",
            duration_ms=1000,
            records_fetched=350,
            records_accepted=350,
            error_message=None,
            metadata_json={"source_kind": "openrouter_importer"},
        )
        session.commit()

    initial = service.list_admin_recognition_models()
    target = next(item for item in initial["items"] if item["model_id"] == "gpt-4.1-mini")

    assert target["in_hosted_catalog"] is True
    assert target["annotation"]["review_status"] == "pending"
    assert target["source"]
    assert initial["total"] == 2
    assert initial["summary"]["not_in_hosted_catalog_total"] == 1
    assert initial["summary"]["new_models_total"] == 1
    assert initial["summary"]["disappeared_models_total"] == 0
    assert initial["summary"]["source_runs"][0]["source"] == "openrouter"
    assert initial["summary"]["source_runs"][0]["records_fetched"] == 350
    assert target["is_new_since_previous_snapshot"] is True
    assert initial["recognition_bundle"]["admin_source"]["source_run_ids"] == [
        "litellm:2026-03-30T12:00:00Z",
        "huggingface:2026-03-30T12:00:00Z",
    ]
    assert initial["recognition_bundle"]["admin_source"]["sources"]["hf_snapshot"] == "snapshot-hf-001"
    assert initial["recognition_bundle"]["snapshot_delta"]["new_models_total"] == 1
    assert initial["recognition_bundle"]["snapshot_delta"]["previous_revision"] == "recognition-intelligence-20260330115500"

    updated = service.upsert_admin_recognition_annotation(
        provider_id="openai",
        model_id="gpt-4.1-mini",
        review_status="candidate",
        manual_tags=["recommended", "needs_followup"],
        operator_notes="Looks ready for hosted curation",
    )

    assert updated is not None
    assert updated["annotation"]["review_status"] == "candidate"
    assert updated["annotation"]["manual_tags"] == ["recommended", "needs_followup"]

    refreshed = service.get_admin_recognition_model(
        provider_id="openai",
        model_id="gpt-4.1-mini",
    )

    assert refreshed is not None
    assert refreshed["annotation"]["operator_notes"] == "Looks ready for hosted curation"
    assert refreshed["recognition_bundle"]["revision"]

    dispose_engine(database_url)


def test_admin_recognition_models_can_use_review_only_sample_catalog_without_expanding_hosted_catalog(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    service = CatalogService(
        database_url,
        recognition_review_providers={
            "openai": OpenAIProviderAdapter(
                sample_catalog_profile="recognition_review_60"
            )
        },
    )
    service.refresh_catalog()

    admin_models = service.list_admin_models()
    recognition_rows = service.list_admin_recognition_models(page=1, per_page=10)

    assert admin_models["total"] == 3
    assert admin_models["platform_models"]["total"] == 3
    assert recognition_rows["total"] == 60
    assert recognition_rows["summary"]["hosted_catalog_total"] == 3
    assert recognition_rows["summary"]["not_in_hosted_catalog_total"] == 57
    assert recognition_rows["summary"]["platform_models_total"] == 3
    assert recognition_rows["summary"]["not_in_platform_models_total"] == 57
    assert recognition_rows["pricing"]["base_currency"] == "USD"
    assert recognition_rows["pricing"]["supported_currencies"] == ["USD", "CNY"]
    assert recognition_rows["recognition_bundle"]["revision"].startswith(
        "recognition-admin-review-recognition_review_60-"
    )
    assert any(item["in_hosted_catalog"] is False for item in recognition_rows["items"])

    dispose_engine(database_url)


def test_admin_recognition_models_return_empty_when_no_snapshot_or_review_source(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    service = CatalogService(database_url)
    service.refresh_catalog()

    recognition_rows = service.list_admin_recognition_models()

    assert recognition_rows["total"] == 0
    assert recognition_rows["summary"]["hosted_catalog_total"] == 0
    assert recognition_rows["pricing"]["base_currency"] == "USD"
    assert recognition_rows["recognition_bundle"]["admin_source"]["kind"] == "unconfigured"

    dispose_engine(database_url)


def test_admin_recognition_models_support_quick_filters_conflicts_and_hosted_metadata(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    service = CatalogService(database_url)
    service.refresh_catalog()
    service.upsert_admin_model_annotation(
        model_id="gpt-4.1-mini",
        recommended=True,
        cost_tier="budget",
        visibility="advanced",
        badges=["cheap"],
        operator_notes="internal only",
    )
    service.recognition_admin.bundle_loader = lambda: {
        "revision": "recognition-catalog-test",
        "checksum": "checksum-001",
        "published_at": "2026-03-30T12:00:00Z",
        "models": [
            {
                "provider": "openai",
                "model_id": "gpt-4.1-mini",
                "model_type": "chat",
                "preview_type": "text",
                "confidence": 0.98,
                "source": "cloud_published",
                "aliases": ["gpt-4.1-mini"],
                "match_keys": ["gpt-4.1-mini", "shared-key"],
                "input_modalities": ["text"],
                "output_modalities": ["text"],
                "capabilities": {"text_input": True},
                "evidence": [
                    {"source": "manual_curation", "confidence": 0.99},
                    {"source": "provider_raw_json", "confidence": 0.8},
                ],
                "updated_at": "2026-03-30T12:00:00Z",
                "deprecated": False,
            },
            {
                "provider": "huggingface",
                "model_id": "llava-hf/llava-1.5-7b-hf",
                "model_type": "vision",
                "preview_type": "text",
                "confidence": 0.84,
                "source": "cloud_published",
                "aliases": ["llava-hf/llava-1.5-7b-hf"],
                "match_keys": ["shared-key", "llava-hf/llava-1.5-7b-hf"],
                "input_modalities": ["text", "image"],
                "output_modalities": ["text"],
                "capabilities": {"vision": True},
                "evidence": [
                    {"source": "huggingface_model_info", "confidence": 0.84},
                ],
                "updated_at": "2026-03-30T12:00:00Z",
                "deprecated": False,
            },
        ],
        "pattern_rules": [],
    }

    updated = service.upsert_admin_recognition_annotation(
        provider_id="huggingface",
        model_id="llava-hf/llava-1.5-7b-hf",
        review_status="candidate",
        manual_tags=["Vision", "needs_followup", "vision"],
        operator_notes="needs hosted decision",
    )

    assert updated is not None
    assert updated["annotation"]["manual_tags"] == ["vision", "needs_followup"]

    conflict_rows = service.list_admin_recognition_models(quick_filter="conflicts")
    assert conflict_rows["summary"]["conflict_total"] == 2
    assert conflict_rows["total"] == 2

    candidate_rows = service.list_admin_recognition_models(
        quick_filter="candidate_not_in_hosted",
        sort_by="confidence",
        sort_dir="desc",
    )
    assert candidate_rows["total"] == 1
    assert candidate_rows["items"][0]["provider_id"] == "huggingface"
    assert candidate_rows["items"][0]["in_hosted_catalog"] is False
    assert candidate_rows["items"][0]["in_platform_models"] is False
    assert candidate_rows["items"][0]["why_not_in_hosted_catalog"] == "match_conflict"
    assert candidate_rows["items"][0]["why_not_in_platform_models"] == "match_conflict"

    hosted_detail = service.get_admin_recognition_model(
        provider_id="openai",
        model_id="gpt-4.1-mini",
    )
    review_detail = service.get_admin_recognition_model(
        provider_id="huggingface",
        model_id="llava-hf/llava-1.5-7b-hf",
    )

    assert hosted_detail is not None
    assert hosted_detail["hosted_metadata"]["recommended"] is True
    assert hosted_detail["platform_model_metadata"]["recommended"] is True
    assert hosted_detail["hosted_metadata"]["cost_tier"] == "budget"
    assert hosted_detail["primary_evidence"]["source"] == "manual_curation"
    assert hosted_detail["has_match_conflict"] is True
    assert review_detail is not None
    assert review_detail["annotation"]["review_status"] == "candidate"
    assert review_detail["why_not_in_hosted_catalog"] == "match_conflict"
    assert review_detail["why_not_in_platform_models"] == "match_conflict"
    assert review_detail["evidence_source_count"] == 1

    dispose_engine(database_url)


def test_public_catalog_models_include_public_hosted_metadata_only(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    service = CatalogService(database_url)
    service.refresh_catalog()
    service.upsert_admin_model_annotation(
        model_id="gpt-4.1-mini",
        recommended=True,
        cost_tier="budget",
        visibility="advanced",
        badges=["recommended", "cheap"],
        operator_notes="internal only note",
    )

    models = service.list_models()
    detail = service.get_model("gpt-4.1-mini")
    row = next(item for item in models["items"] if item["model_id"] == "gpt-4.1-mini")

    assert row["hosted_metadata"]["recommended"] is True
    assert row["hosted_metadata"]["cost_tier"] == "budget"
    assert row["hosted_metadata"]["visibility"] == "advanced"
    assert row["hosted_metadata"]["badges"] == ["recommended", "cheap"]
    assert "operator_notes" not in row["hosted_metadata"]
    assert detail is not None
    assert detail["hosted_metadata"]["recommended"] is True
    assert "operator_notes" not in detail["hosted_metadata"]

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
