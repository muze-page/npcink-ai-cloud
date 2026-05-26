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
        "hosted_metadata",
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
    assert set(model["hosted_metadata"].keys()) == {
        "recommended",
        "cost_tier",
        "visibility",
        "badges",
        "updated_at",
    }

    assert set(payload["data"]["recommended_sets"]["text.balanced"].keys()) == {
        "profile_id",
        "model_ids",
        "instance_ids",
    }

    dispose_engine(database_url)


def test_catalog_recognition_bundle_response_shape_is_stable(tmp_path: Path) -> None:
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
        "/v1/catalog/recognition/bundle",
        headers=build_auth_headers(
            "GET",
            "/v1/catalog/recognition/bundle",
            site_id="site_contract",
            trace_id="tracecatalogrecognition00000001",
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"status", "error_code", "message", "data", "meta"}
    assert set(payload["data"].keys()) == {
        "revision",
        "schema_version",
        "published_at",
        "checksum",
        "sources",
        "models",
        "pattern_rules",
    }
    assert set(payload["data"]["sources"].keys()) == {
        "catalog_revision",
        "recognition_derivation",
        "manual_curation_version",
        "hf_alias_bridge_version",
        "upstream_evidence_version",
        "litellm_revision",
        "openrouter_snapshot",
        "hf_snapshot",
        "ollama_snapshot",
    }

    model = payload["data"]["models"][0]
    assert set(model.keys()) == {
        "provider",
        "model_id",
        "match_keys",
        "aliases",
        "model_type",
        "preview_type",
        "input_modalities",
        "output_modalities",
        "capabilities",
        "confidence",
        "price_input",
        "price_output",
        "source",
        "evidence",
        "updated_at",
        "deprecated",
    }

    rule = payload["data"]["pattern_rules"][0]
    assert set(rule.keys()) == {
        "id",
        "pattern",
        "model_type",
        "preview_type",
        "capabilities",
        "confidence",
        "enabled",
        "updated_at",
    }

    dispose_engine(database_url)


def test_catalog_recognition_bundle_v1_freeze_stays_metadata_only(tmp_path: Path) -> None:
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
        "/v1/catalog/recognition/bundle",
        headers=build_auth_headers(
            "GET",
            "/v1/catalog/recognition/bundle",
            site_id="site_contract",
            trace_id="tracecatalogrecognitionfreeze0001",
        ),
    )

    assert response.status_code == 200
    bundle = response.json()["data"]
    assert "promotion" not in bundle
    assert "policies" not in bundle
    assert "user_overrides" not in bundle
    assert "adopt_actions" not in bundle

    model = bundle["models"][0]
    assert "promotion_score" not in model
    assert "recommended_action" not in model
    assert "stable_runs" not in model
    assert "user_override" not in model

    dispose_engine(database_url)


def test_internal_admin_models_contract_stays_hosted_metadata_only(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    response = client.get(
        "/internal/service/admin/models",
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            trace_id="traceadminmodelscontract000001",
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert set(payload.keys()) == {
        "filters",
        "total",
        "items",
        "pagination",
        "sort",
        "summary",
        "platform_models",
        "recognition_bundle",
    }

    model = payload["items"][0]
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
        "hosted_metadata",
        "annotation",
        "recognition",
        "recognition_review",
        "platform_model",
    }
    assert set(model["annotation"].keys()) == {
        "recommended",
        "cost_tier",
        "visibility",
        "badges",
        "operator_notes",
        "updated_at",
    }
    assert "execution_mode" not in model
    assert "hosted_profile_id" not in model
    assert "user_override" not in model
    assert "site_settings" not in model
    assert set(model["recognition_review"].keys()) == {
        "review_status",
        "manual_tags",
        "operator_notes",
        "updated_at",
    }


def test_internal_admin_recognition_contract_stays_review_only(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
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
  "records": {
    "openai::gpt-4.1-mini": {
      "evidence_source": "litellm_model_info",
      "model_type": "vision",
      "preview_type": "text",
      "price_input": 0.4,
      "price_output": 1.6,
      "input_modalities": ["text", "image"],
      "output_modalities": ["text"],
      "capabilities": {
        "text_input": true,
        "image_input": true,
        "vision": true
      },
      "confidence": 0.95
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        recognition_evidence_snapshot_path=str(snapshot_path),
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    response = client.get(
        "/internal/service/admin/recognition",
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            trace_id="traceadminrecognitioncontract001",
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert set(payload.keys()) == {
        "filters",
        "total",
        "items",
        "pagination",
        "sort",
        "summary",
        "pricing",
        "recognition_bundle",
    }

    model = payload["items"][0]
    assert {
        "provider_id",
        "model_id",
        "model_type",
        "preview_type",
        "confidence",
        "price_input",
        "price_output",
        "source",
        "aliases",
        "evidence_sources",
        "primary_evidence",
        "evidence_source_count",
        "updated_at",
        "in_hosted_catalog",
        "in_platform_models",
        "has_match_conflict",
        "match_conflict_keys",
        "why_not_in_hosted_catalog",
        "why_not_in_platform_models",
        "annotation",
    }.issubset(model.keys())
    assert set(model["annotation"].keys()) == {
        "review_status",
        "manual_tags",
        "operator_notes",
        "updated_at",
    }
    assert "recommended" not in model["annotation"]
    assert "cost_tier" not in model["annotation"]
    assert "visibility" not in model["annotation"]
    assert "execution_mode" not in model
    assert "hosted_profile_id" not in model
    assert "user_override" not in model
    assert {
        "hosted_catalog_total",
        "not_in_hosted_catalog_total",
        "platform_models_total",
        "not_in_platform_models_total",
        "candidate_not_in_hosted_total",
        "candidate_not_in_platform_models_total",
        "low_confidence_total",
        "conflict_total",
        "review_status_counts",
        "sources",
        "manual_tag_suggestions",
    }.issubset(payload["summary"].keys())
    assert set(payload["pricing"].keys()) == {
        "base_currency",
        "supported_currencies",
        "cny_per_usd",
        "unit",
    }
    assert payload["pricing"]["base_currency"] == "USD"
