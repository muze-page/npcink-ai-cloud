from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.adapters.notifications.base import PortalEmailSender
from app.api.routes import internal as internal_routes
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import ServiceAuditEvent
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from tests.conftest import (
    TEST_INTERNAL_AUTH_TOKEN,
    build_auth_headers,
    build_internal_headers,
    merge_json_headers,
    seed_site_auth,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'catalog-api.sqlite3'}"


class FakePortalEmailSender(PortalEmailSender):
    def __init__(self) -> None:
        self.test_messages: list[dict[str, str]] = []

    def send_test_email(
        self,
        *,
        recipient_email: str,
        project_name: str,
        portal_url: str,
    ) -> None:
        self.test_messages.append(
            {
                "recipient_email": recipient_email,
                "project_name": project_name,
                "portal_url": portal_url,
            }
        )

    def send_login_code(
        self,
        *,
        recipient_email: str,
        member_ref: str,
        code: str,
        expires_in_seconds: int,
        project_name: str,
        locale: str = "zh-CN",
    ) -> None:
        return None

    def send_invite_notice(
        self,
        *,
        recipient_email: str,
        member_ref: str,
        portal_url: str,
        project_name: str,
        locale: str = "zh-CN",
    ) -> None:
        return None


def test_catalog_routes_return_seeded_models(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_site_auth(database_url, site_id="site_catalog", scopes=["catalog:read"])

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token="",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    response = client.get(
        "/v1/catalog/models",
        headers=build_auth_headers(
            "GET",
            "/v1/catalog/models",
            site_id="site_catalog",
            trace_id="tracecatalog0010000000000000000",
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["total"] == 3
    assert "recommended_sets" in payload["data"]
    assert payload["data"]["platform_models"]["surface"] == "platform_models"
    assert payload["message"] == "platform models loaded"

    dispose_engine(database_url)


def test_catalog_routes_support_recommended_profile_filter(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_site_auth(database_url, site_id="site_catalog", scopes=["catalog:read"])

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token="",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    response = client.get(
        "/v1/catalog/models",
        params={"recommended_for": "text.balanced"},
        headers=build_auth_headers(
            "GET",
            "/v1/catalog/models",
            site_id="site_catalog",
            trace_id="tracecatalog0020000000000000000",
            query="recommended_for=text.balanced",
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["recommended_for"] == "text.balanced"
    assert payload["data"]["platform_models"]["recommended_for"] == "text.balanced"
    assert payload["data"]["total"] == 1
    assert payload["data"]["items"][0]["model_id"] == "gpt-4.1-mini"
    assert payload["data"]["items"][0]["recommended_rank"] == 1

    dispose_engine(database_url)


def test_catalog_routes_expose_public_hosted_metadata_summary(tmp_path: Path) -> None:
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
    seed_site_auth(database_url, site_id="site_catalog", scopes=["catalog:read"])

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    list_response = client.get(
        "/v1/catalog/models",
        headers=build_auth_headers(
            "GET",
            "/v1/catalog/models",
            site_id="site_catalog",
            trace_id="tracecataloghostedmeta00100000",
        ),
    )
    detail_response = client.get(
        "/v1/catalog/models/gpt-4.1-mini",
        headers=build_auth_headers(
            "GET",
            "/v1/catalog/models/gpt-4.1-mini",
            site_id="site_catalog",
            trace_id="tracecataloghostedmeta00200000",
        ),
    )

    assert list_response.status_code == 200
    assert detail_response.status_code == 200

    list_payload = list_response.json()["data"]
    row = next(item for item in list_payload["items"] if item["model_id"] == "gpt-4.1-mini")
    assert row["hosted_metadata"]["recommended"] is True
    assert row["hosted_metadata"]["cost_tier"] == "budget"
    assert row["platform_model"]["surface"] == "platform_models"
    assert "operator_notes" not in row["hosted_metadata"]

    detail_payload = detail_response.json()["data"]
    assert detail_payload["hosted_metadata"]["visibility"] == "advanced"
    assert detail_payload["hosted_metadata"]["badges"] == ["recommended", "cheap"]
    assert detail_payload["platform_model"]["model_id"] == "gpt-4.1-mini"
    assert "operator_notes" not in detail_payload["hosted_metadata"]

    dispose_engine(database_url)


def test_catalog_platform_model_alias_routes_match_models_surface(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_site_auth(database_url, site_id="site_catalog", scopes=["catalog:read"])

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    list_response = client.get(
        "/v1/catalog/platform-models",
        headers=build_auth_headers(
            "GET",
            "/v1/catalog/platform-models",
            site_id="site_catalog",
            trace_id="tracecatalogplatform001000000",
        ),
    )
    detail_response = client.get(
        "/v1/catalog/platform-models/gpt-4.1-mini",
        headers=build_auth_headers(
            "GET",
            "/v1/catalog/platform-models/gpt-4.1-mini",
            site_id="site_catalog",
            trace_id="tracecatalogplatform002000000",
        ),
    )
    revision_response = client.get(
        "/v1/catalog/platform-models/revision",
        headers=build_auth_headers(
            "GET",
            "/v1/catalog/platform-models/revision",
            site_id="site_catalog",
            trace_id="tracecatalogplatform003000000",
        ),
    )

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    assert revision_response.status_code == 200
    assert list_response.json()["message"] == "platform models loaded"
    assert detail_response.json()["message"] == "platform model loaded"
    assert revision_response.json()["message"] == "platform models revision loaded"
    assert list_response.json()["data"]["platform_models"]["surface"] == "platform_models"
    assert detail_response.json()["data"]["platform_model"]["surface"] == "platform_models"

    dispose_engine(database_url)


def test_catalog_recognition_routes_return_bundle_and_revision(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_site_auth(database_url, site_id="site_catalog", scopes=["catalog:read"])

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    revision_response = client.get(
        "/v1/catalog/recognition/revision",
        headers=build_auth_headers(
            "GET",
            "/v1/catalog/recognition/revision",
            site_id="site_catalog",
            trace_id="tracecatalogrecognition0010000",
        ),
    )
    bundle_response = client.get(
        "/v1/catalog/recognition/bundle",
        headers=build_auth_headers(
            "GET",
            "/v1/catalog/recognition/bundle",
            site_id="site_catalog",
            trace_id="tracecatalogrecognition0020000",
        ),
    )
    intelligence_revision_response = client.get(
        "/v1/catalog/recognition-intelligence/revision",
        headers=build_auth_headers(
            "GET",
            "/v1/catalog/recognition-intelligence/revision",
            site_id="site_catalog",
            trace_id="tracecatalogrecognition0030000",
        ),
    )
    intelligence_bundle_response = client.get(
        "/v1/catalog/recognition-intelligence/bundle",
        headers=build_auth_headers(
            "GET",
            "/v1/catalog/recognition-intelligence/bundle",
            site_id="site_catalog",
            trace_id="tracecatalogrecognition0040000",
        ),
    )

    assert revision_response.status_code == 200
    assert bundle_response.status_code == 200
    assert intelligence_revision_response.status_code == 200
    assert intelligence_bundle_response.status_code == 200

    revision_payload = revision_response.json()
    bundle_payload = bundle_response.json()
    intelligence_revision_payload = intelligence_revision_response.json()
    intelligence_bundle_payload = intelligence_bundle_response.json()

    assert revision_payload["data"]["schema_version"] == "recognition_bundle_v1"
    assert revision_payload["data"]["checksum"]
    assert bundle_payload["data"]["schema_version"] == "recognition_bundle_v1"
    assert bundle_payload["data"]["revision"] == revision_payload["data"]["revision"]
    assert bundle_payload["data"]["checksum"] == revision_payload["data"]["checksum"]
    assert bundle_payload["data"]["models"][0]["source"] == "cloud_published"
    assert bundle_payload["data"]["pattern_rules"][0]["enabled"] is True
    assert intelligence_revision_payload["data"]["revision"] == revision_payload["data"]["revision"]
    assert intelligence_bundle_payload["data"]["bundle_kind"] == "recognition_intelligence_bundle_v1"
    assert intelligence_bundle_payload["data"]["checksum"] == revision_payload["data"]["checksum"]

    dispose_engine(database_url)


def test_catalog_recognition_intelligence_bundle_prefers_snapshot_payload(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_site_auth(database_url, site_id="site_catalog", scopes=["catalog:read"])

    snapshot_path = tmp_path / "recognition-public-snapshot.json"
    snapshot_path.write_text(
        """
{
  "version": "recognition_upstream_snapshot_v1",
  "generated_at": "2026-04-03T08:00:00Z",
  "sources": {
    "openrouter_snapshot": "openrouter-snapshot-001",
    "ollama_snapshot": "ollama-catalog-001"
  },
  "source_runs": [
    {
      "source": "openrouter",
      "run_id": "openrouter:2026-04-03T08:00:00Z",
      "status": "ok",
      "generated_at": "2026-04-03T08:00:00Z",
      "records_fetched": 350,
      "records_accepted": 350,
      "duration_ms": 120
    }
  ],
  "source_run_ids": ["openrouter:2026-04-03T08:00:00Z"],
  "source_failures": [],
  "records": {
    "ollama::qwen3-vl:2b": {
      "evidence_source": "ollama_catalog",
      "model_type": "vision",
      "preview_type": "text",
      "input_modalities": ["text", "image"],
      "output_modalities": ["text"],
      "capabilities": {
        "text_input": true,
        "image_input": true,
        "vision": true
      },
      "confidence": 0.91,
      "source_details": {
        "ollama_catalog": {
          "provider": "ollama",
          "model_id": "qwen3-vl:2b",
          "model_type": "vision",
          "preview_type": "text",
          "confidence": 0.91
        }
      }
    },
    "ollama::qwen3.5:9b": {
      "evidence_source": "ollama_catalog",
      "model_type": "chat",
      "preview_type": "text",
      "input_modalities": ["text"],
      "output_modalities": ["text"],
      "capabilities": {
        "text_input": true
      },
      "confidence": 0.88,
      "source_details": {
        "ollama_catalog": {
          "provider": "ollama",
          "model_id": "qwen3.5:9b",
          "model_type": "chat",
          "preview_type": "text",
          "confidence": 0.88
        }
      }
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
        recognition_evidence_snapshot_path=str(snapshot_path),
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    response = client.get(
        "/v1/catalog/recognition-intelligence/bundle",
        headers=build_auth_headers(
            "GET",
            "/v1/catalog/recognition-intelligence/bundle",
            site_id="site_catalog",
            trace_id="tracecatalogrecognition0050000",
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["bundle_kind"] == "recognition_intelligence_bundle_v1"
    assert payload["sources"]["openrouter_snapshot"] == "openrouter-snapshot-001"
    assert payload["sources"]["ollama_snapshot"] == "ollama-catalog-001"
    assert payload["source_runs"][0]["source"] == "openrouter"
    assert len(payload["models"]) == 2
    assert payload["models"][0]["source"] == "cloud_intelligence"
    assert {item["model_id"] for item in payload["models"]} == {
        "qwen3-vl:2b",
        "qwen3.5:9b",
    }

    dispose_engine(database_url)


def test_internal_admin_provider_connections_can_save_test_and_sync(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        admin_session_secret="x" * 32,
        provider_connection_secret="p" * 32,
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    save_response = client.post(
        "/internal/service/admin/providers/openai-main",
        json={
            "connection_id": "openai-main",
            "provider_type": "openai",
            "source_role": "execution_source",
            "display_name": "OpenAI Main",
            "enabled": True,
            "base_url": "https://api.openai.com/v1",
            "config": {"timeout_seconds": 30},
            "api_key": "",
        },
        headers=build_internal_headers(idempotency_key="provider-save-001"),
    )
    list_response = client.get(
        "/internal/service/admin/providers",
        headers=build_internal_headers(),
    )
    test_response = client.post(
        "/internal/service/admin/providers/openai-main/test",
        json={},
        headers=build_internal_headers(idempotency_key="provider-test-001"),
    )
    sync_response = client.post(
        "/internal/service/admin/providers/openai-main/sync",
        json={},
        headers=build_internal_headers(idempotency_key="provider-sync-001"),
    )
    promote_response = client.post(
        "/internal/service/admin/providers/openai-main/promote",
        json={},
        headers=build_internal_headers(idempotency_key="provider-promote-001"),
    )

    assert save_response.status_code == 200
    assert save_response.json()["data"]["receipt"]["event_kind"] == "provider_connection.upsert"
    assert save_response.json()["data"]["receipt"]["audit_filters"]["event_kind"] == "provider_connection.upsert"
    assert list_response.status_code == 200
    assert test_response.status_code == 200
    assert test_response.json()["data"]["receipt"]["event_kind"] == "provider_connection.test"
    assert test_response.json()["data"]["receipt"]["audit_filters"]["event_kind"] == "provider_connection.test"
    assert sync_response.status_code == 200
    assert sync_response.json()["data"]["receipt"]["event_kind"] == "provider_connection.sync"
    assert sync_response.json()["data"]["receipt"]["audit_filters"]["event_kind"] == "provider_connection.sync"
    assert promote_response.status_code == 200
    assert promote_response.json()["data"]["receipt"]["event_kind"] == "provider_connection.promote"
    assert promote_response.json()["data"]["receipt"]["audit_filters"]["event_kind"] == "provider_connection.promote"
    assert list_response.json()["data"]["items"][0]["connection_id"] == "openai-main"
    assert list_response.json()["data"]["items"][0]["source_role"] == "execution_source"
    assert test_response.json()["data"]["test_result"]["models_total"] == 3
    assert len(test_response.json()["data"]["test_result"]["inspected_models"]) == 3
    assert sync_response.json()["data"]["sync_result"]["provider_id"] == "openai-main"
    assert sync_response.json()["data"]["sync_result"]["added_total"] == 3
    assert sync_response.json()["data"]["sync_result"]["updated_total"] == 0
    assert sync_response.json()["data"]["sync_result"]["removed_total"] == 0
    assert promote_response.json()["data"]["promote_result"]["ok"] is True
    assert (
        promote_response.json()["data"]["connection"]["active_execution_revision"]
        == promote_response.json()["data"]["connection"]["last_sync_revision"]
    )

    dispose_engine(database_url)


def test_internal_refresh_endpoint_refreshes_catalog(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        recognition_evidence_snapshot_path="",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    body = b'{"providers":["openai"]}'
    response = client.post(
        "/internal/catalog/refresh",
        content=body,
        headers=merge_json_headers(
            build_internal_headers(
                internal_token=TEST_INTERNAL_AUTH_TOKEN,
                idempotency_key="catalog-refresh-001",
                trace_id="tracecatalog0030000000000000000",
            )
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["refreshed_count"] == 1

    dispose_engine(database_url)


def test_internal_refresh_endpoint_refreshes_recognition_evidence(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    source_path = tmp_path / "recognition-source.json"
    snapshot_path = tmp_path / "recognition-snapshot.json"
    source_path.write_text(
        """
{
  "version": "recognition_upstream_api_v1",
  "sources": {
    "litellm_revision": "api-litellm-001",
    "hf_snapshot": "api-hf-001"
  },
  "records": {
    "custom_provider::fixture-model": {
      "evidence_source": "litellm_api_seed",
      "model_type": "vision",
      "preview_type": "text",
      "input_modalities": ["text", "image"],
      "output_modalities": ["text"],
      "capabilities": {
        "text_input": true,
        "image_input": true,
        "vision": true
      },
      "confidence": 0.92
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
        recognition_evidence_source_path=str(source_path),
        recognition_evidence_snapshot_path=str(snapshot_path),
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    response = client.post(
        "/internal/catalog/recognition/evidence/refresh",
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            idempotency_key="catalog-recognition-refresh-001",
            trace_id="tracecatalogrecognitionrefresh001",
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["status"] == "ok"
    assert payload["data"]["records_total"] == 1
    assert payload["data"]["snapshot_path"] == str(snapshot_path)
    assert snapshot_path.exists()

    dispose_engine(database_url)


def test_internal_model_intelligence_publisher_routes_refresh_and_inspect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    bundle_path = tmp_path / "output" / "model-intelligence.bundle.json"
    summary_path = tmp_path / "output" / "run-summary.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        json.dumps(
            {
                "bundle_kind": "model_intelligence_bundle_v1",
                "schema_version": "model_intelligence_bundle_v1",
                "generated_at": "2026-04-06T09:00:00Z",
                "checksum": "publisherchecksum001",
                "sources": [
                    {
                        "source_id": "openrouter",
                        "status": "ok",
                        "fetched_at": "2026-04-06T08:59:00Z",
                    }
                ],
                "models": [],
            }
        ),
        encoding="utf-8",
    )
    summary_path.write_text(json.dumps({"status": "success"}), encoding="utf-8")

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        model_intelligence_publisher_enabled=True,
        model_intelligence_bundle_path=str(bundle_path),
        model_intelligence_run_summary_path=str(summary_path),
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    monkeypatch.setattr(
        internal_routes,
        "run_model_intelligence_publisher",
        lambda current_settings: {
            "source": "model_intelligence_publisher_worker",
            "status": "ok",
            "revision": "publisher-2026-04-06T09:00:00Z-publisherchec",
            "bundle_path": str(bundle_path),
            "run_summary_path": str(summary_path),
            "records_total": 0,
            "source_keys": ["openrouter"],
        },
    )

    refresh_response = client.post(
        "/internal/catalog/intelligence/publisher/refresh",
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            idempotency_key="catalog-intelligence-publisher-refresh-001",
            trace_id="tracecatalogpublisherrefresh001",
        ),
    )

    assert refresh_response.status_code == 200
    refresh_payload = refresh_response.json()
    assert refresh_payload["status"] == "ok"
    assert refresh_payload["data"]["status"] == "ok"
    assert refresh_payload["data"]["source"] == "model_intelligence_publisher_worker"

    inspect_response = client.get(
        "/internal/catalog/intelligence/publisher",
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            trace_id="tracecatalogpublisherinspect001",
        ),
    )

    assert inspect_response.status_code == 200
    inspect_payload = inspect_response.json()
    assert inspect_payload["status"] == "ok"
    assert inspect_payload["data"]["configured"] is True
    assert inspect_payload["data"]["enabled"] is True
    assert inspect_payload["data"]["script_exists"] is False
    assert inspect_payload["data"]["bundle_exists"] is True
    assert inspect_payload["data"]["source_keys"] == ["openrouter"]

    dispose_engine(database_url)


def test_internal_admin_models_routes_load_and_save_annotations(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        recognition_evidence_snapshot_path="",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    list_response = client.get(
        "/internal/service/admin/models",
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            trace_id="tracecatalogadminmodels001000",
        ),
    )

    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["data"]["total"] == 3
    assert list_payload["data"]["platform_models"]["surface"] == "platform_models"
    assert list_payload["data"]["recognition_bundle"]["revision"].startswith("recognition-catalog-")

    update_response = client.post(
        "/internal/service/admin/models/gpt-4.1-mini/annotation",
        headers=merge_json_headers(
            build_internal_headers(
                internal_token=TEST_INTERNAL_AUTH_TOKEN,
                idempotency_key="catalog-admin-model-annotation-001",
                trace_id="tracecatalogadminmodels002000",
            )
        ),
        json={
            "recommended": True,
            "cost_tier": "budget",
            "visibility": "advanced",
            "badges": ["recommended", "cheap"],
            "operator_notes": "Prefer this for hosted drafts",
        },
    )

    assert update_response.status_code == 200
    update_payload = update_response.json()
    assert update_payload["data"]["annotation"]["recommended"] is True
    assert update_payload["data"]["annotation"]["cost_tier"] == "budget"
    assert update_payload["data"]["receipt"]["event_kind"] == "catalog_model_annotation.upsert"
    assert (
        update_payload["data"]["receipt"]["audit_filters"]["event_kind"]
        == "catalog_model_annotation.upsert"
    )

    detail_response = client.get(
        "/internal/service/admin/models/gpt-4.1-mini",
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            trace_id="tracecatalogadminmodels003000",
        ),
    )

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["data"]["annotation"]["visibility"] == "advanced"
    assert detail_payload["data"]["annotation"]["badges"] == ["recommended", "cheap"]
    assert detail_payload["data"]["recognition"]["model_type"]
    assert detail_payload["data"]["platform_model"]["surface"] == "platform_models"

    dispose_engine(database_url)


def test_internal_admin_models_routes_support_pagination_and_sort(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        recognition_evidence_snapshot_path="",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    response = client.get(
        "/internal/service/admin/models?page=1&per_page=2&sort_by=model_id&sort_dir=desc",
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            trace_id="tracecatalogadminmodels004000",
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["pagination"]["page"] == 1
    assert payload["pagination"]["per_page"] == 2
    assert payload["sort"] == {"sort_by": "model_id", "sort_dir": "desc"}
    assert len(payload["items"]) == 2
    assert payload["items"][0]["model_id"] >= payload["items"][1]["model_id"]

    dispose_engine(database_url)


def test_internal_admin_recognition_routes_load_and_save_annotations(tmp_path: Path) -> None:
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

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        openai_recognition_review_sample_catalog_profile="",
        recognition_evidence_snapshot_path=str(snapshot_path),
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    list_response = client.get(
        "/internal/service/admin/recognition",
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            trace_id="tracecatalogadminrecognition001",
        ),
    )

    assert list_response.status_code == 200
    list_payload = list_response.json()["data"]
    assert list_payload["total"] == 2
    assert list_payload["summary"]["hosted_catalog_total"] == 1
    assert list_payload["summary"]["platform_models_total"] == 1
    assert set(list_payload["summary"]["review_status_counts"].keys()) == {
        "candidate",
        "pending",
        "reviewed",
        "suppressed",
    }
    assert list_payload["summary"]["manual_tag_suggestions"] == [
        "candidate",
        "vision",
        "image",
        "embedding",
        "oss",
        "needs_followup",
    ]
    assert list_payload["pricing"]["base_currency"] == "USD"
    assert list_payload["pricing"]["supported_currencies"] == ["USD", "CNY"]
    assert list_payload["pricing"]["unit"] == "per_1m_tokens"

    paged_response = client.get(
        "/internal/service/admin/recognition?page=1&per_page=2&sort_by=review_status&sort_dir=desc&quick_filter=low_confidence",
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            trace_id="tracecatalogadminrecognition001b",
        ),
    )

    assert paged_response.status_code == 200
    paged_payload = paged_response.json()["data"]
    assert paged_payload["pagination"]["per_page"] == 2
    assert paged_payload["sort"]["sort_by"] == "review_status"
    assert paged_payload["filters"]["quick_filter"] == "low_confidence"

    update_response = client.post(
        "/internal/service/admin/recognition/openai/gpt-4.1-mini/annotation",
        headers=merge_json_headers(
            build_internal_headers(
                internal_token=TEST_INTERNAL_AUTH_TOKEN,
                idempotency_key="catalog-admin-recognition-annotation-001",
                trace_id="tracecatalogadminrecognition002",
            )
        ),
        json={
            "review_status": "candidate",
            "manual_tags": ["vision", "needs_followup"],
            "operator_notes": "Review looks consistent with hosted curation",
            "recommended": True,
            "cost_tier_override": "balanced",
            "visibility": "advanced",
            "badges": ["reviewed", "publisher"],
        },
    )

    assert update_response.status_code == 200
    update_payload = update_response.json()["data"]
    assert update_payload["annotation"]["review_status"] == "candidate"
    assert update_payload["annotation"]["manual_tags"] == ["vision", "needs_followup"]
    assert update_payload["annotation"]["recommended"] is True
    assert update_payload["annotation"]["cost_tier_override"] == "balanced"
    assert update_payload["annotation"]["visibility"] == "advanced"
    assert update_payload["annotation"]["badges"] == ["reviewed", "publisher"]
    assert update_payload["receipt"]["event_kind"] == "recognition_model_annotation.upsert"
    assert (
        update_payload["receipt"]["audit_filters"]["event_kind"]
        == "recognition_model_annotation.upsert"
    )

    invalid_response = client.post(
        "/internal/service/admin/recognition/openai/gpt-4.1-mini/annotation",
        headers=merge_json_headers(
            build_internal_headers(
                internal_token=TEST_INTERNAL_AUTH_TOKEN,
                idempotency_key="catalog-admin-recognition-annotation-002",
                trace_id="tracecatalogadminrecognition002b",
            )
        ),
        json={
            "review_status": "published",
            "manual_tags": ["vision"],
            "operator_notes": "",
            "recommended": False,
            "cost_tier_override": "",
            "visibility": "default",
            "badges": [],
        },
    )

    assert invalid_response.status_code == 400

    detail_response = client.get(
        "/internal/service/admin/recognition/openai/gpt-4.1-mini",
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            trace_id="tracecatalogadminrecognition003",
        ),
    )

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()["data"]
    assert detail_payload["annotation"]["operator_notes"] == "Review looks consistent with hosted curation"
    assert detail_payload["annotation"]["recommended"] is True
    assert detail_payload["annotation"]["cost_tier_override"] == "balanced"
    assert detail_payload["annotation"]["visibility"] == "advanced"
    assert detail_payload["annotation"]["badges"] == ["reviewed", "publisher"]
    assert detail_payload["in_hosted_catalog"] is True
    assert detail_payload["in_platform_models"] is True
    assert detail_payload["hosted_metadata"]["recommended"] is False
    assert detail_payload["platform_model_metadata"]["recommended"] is False
    assert detail_payload["why_not_in_hosted_catalog"] == ""
    assert detail_payload["why_not_in_platform_models"] == ""
    assert detail_payload["primary_evidence"]["source"]
    assert detail_payload["pricing"]["base_currency"] == "USD"

    with get_session(database_url) as session:
        event = session.scalar(
            select(ServiceAuditEvent)
            .where(ServiceAuditEvent.event_kind == "recognition_model_annotation.upsert")
            .order_by(ServiceAuditEvent.id.desc())
        )

    assert event is not None
    assert event.scope_kind == "recognition_model"
    assert event.scope_id == "openai:gpt-4.1-mini"

    dispose_engine(database_url)


def test_internal_admin_recognition_routes_use_publisher_bundle_annotations(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    bundle_path = tmp_path / "output" / "model-intelligence.bundle.json"
    summary_path = tmp_path / "output" / "run-summary.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    bundle_path.write_text(
        json.dumps(
            {
                "bundle_kind": "model_intelligence_bundle_v1",
                "schema_version": "model_intelligence_bundle_v1",
                "generated_at": generated_at,
                "checksum": "publisher-bundle-recognition-001",
                "sources": [
                    {
                        "source_id": "openrouter",
                        "status": "ok",
                        "fetched_at": "2026-04-06T09:58:00Z",
                    },
                    {
                        "source_id": "ollama",
                        "status": "ok",
                        "fetched_at": "2026-04-06T09:58:10Z",
                    },
                ],
                "models": [
                    {
                        "provider": "openai",
                        "model_id": "gpt-4.1-mini",
                        "display_name": "gpt-4.1-mini",
                        "model_type": "vision",
                        "preview_type": "text",
                        "supports": ["text", "vision"],
                        "capability_profile": "vision",
                        "aliases": ["gpt-4.1-mini"],
                        "source_ids": ["openrouter"],
                        "price_reference_kind": "exact",
                        "price_input": 0.4,
                        "price_output": 1.6,
                        "price_tier": "low",
                        "price_summary": "输入 $0.4000 / 输出 $1.6000（每 1M tokens）",
                        "short_description": "适合轻量视觉理解和多模态问答。",
                        "best_for": "视觉问答",
                        "why_recommended": "来自 publisher bundle。",
                            "updated_at": generated_at,
                    },
                    {
                        "provider": "ollama",
                        "model_id": "bge-m3:latest",
                        "display_name": "bge-m3",
                        "model_type": "embedding",
                        "preview_type": "embedding",
                        "supports": ["embedding"],
                        "capability_profile": "embedding",
                        "aliases": ["bge-m3"],
                        "source_ids": ["ollama"],
                        "price_reference_kind": "estimated",
                        "price_input": None,
                        "price_output": None,
                        "price_tier": "low",
                        "price_summary": "近似参考价，当前为低价",
                        "short_description": "适合本地向量检索。",
                        "best_for": "语义搜索",
                        "why_recommended": "来自 publisher bundle。",
                            "updated_at": generated_at,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(
            {
                "status": "success",
                "failed_sources": [],
            }
        ),
        encoding="utf-8",
    )

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        model_intelligence_publisher_enabled=True,
        model_intelligence_bundle_path=str(bundle_path),
        model_intelligence_run_summary_path=str(summary_path),
        recognition_evidence_snapshot_path="",
        openai_recognition_review_sample_catalog_profile="",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    list_response = client.get(
        "/internal/service/admin/recognition",
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            trace_id="tracecatalogadminrecognitionpublisher001",
        ),
    )

    assert list_response.status_code == 200
    list_payload = list_response.json()["data"]
    assert list_payload["total"] == 2
    assert list_payload["summary"]["source_counts"] == {"publisher_bundle": 2}
    assert list_payload["summary"]["source_runs"][0]["source"] == "openrouter"
    assert list_payload["items"][0]["source"] == "publisher_bundle"
    assert list_payload["recognition_bundle"]["admin_source"]["health_status"] == "ok"
    assert list_payload["recognition_bundle"]["admin_source"]["health_issues"] == []
    assert list_payload["recognition_bundle"]["admin_source"]["operator_alerts"] == []
    assert list_payload["recognition_bundle"]["admin_source"]["fallback"]["previous_bundle_used"] is False
    assert list_payload["recognition_bundle"]["admin_source"]["recent_publications"] == []

    update_response = client.post(
        "/internal/service/admin/recognition/openai/gpt-4.1-mini/annotation",
        headers=merge_json_headers(
            build_internal_headers(
                internal_token=TEST_INTERNAL_AUTH_TOKEN,
                idempotency_key="catalog-admin-recognition-publisher-annotation-001",
                trace_id="tracecatalogadminrecognitionpublisher002",
            )
        ),
        json={
            "review_status": "reviewed",
            "manual_tags": ["vision", "publisher"],
            "operator_notes": "Publisher bundle item reviewed.",
            "recommended": True,
            "cost_tier_override": "premium",
            "visibility": "advanced",
            "badges": ["curated", "preferred"],
        },
    )

    assert update_response.status_code == 200
    update_payload = update_response.json()["data"]
    assert update_payload["annotation"]["review_status"] == "reviewed"
    assert update_payload["annotation"]["manual_tags"] == ["vision", "publisher"]
    assert update_payload["annotation"]["recommended"] is True
    assert update_payload["annotation"]["cost_tier_override"] == "premium"
    assert update_payload["annotation"]["visibility"] == "advanced"
    assert update_payload["annotation"]["badges"] == ["curated", "preferred"]
    assert update_payload["receipt"]["event_kind"] == "recognition_model_annotation.upsert"

    detail_response = client.get(
        "/internal/service/admin/recognition/openai/gpt-4.1-mini",
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            trace_id="tracecatalogadminrecognitionpublisher003",
        ),
    )

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()["data"]
    assert detail_payload["source"] == "publisher_bundle"
    assert detail_payload["short_description"] == "适合轻量视觉理解和多模态问答。"
    assert detail_payload["annotation"]["operator_notes"] == "Publisher bundle item reviewed."
    assert detail_payload["annotation"]["recommended"] is True
    assert detail_payload["annotation"]["cost_tier_override"] == "premium"
    assert detail_payload["annotation"]["visibility"] == "advanced"
    assert detail_payload["annotation"]["badges"] == ["curated", "preferred"]
    assert detail_payload["source_coverage_sources"] == ["openrouter"]

    dispose_engine(database_url)


def test_internal_route_reads_recognition_evidence_snapshot_summary(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    snapshot_path = tmp_path / "recognition-snapshot.json"
    snapshot_path.write_text(
        """
{
  "version": "recognition_upstream_snapshot_v1",
  "generated_at": "2026-03-29T12:00:00Z",
  "sources": {
    "litellm_revision": "inspect-litellm-001",
    "hf_snapshot": "inspect-hf-001",
    "ollama_snapshot": "unconfigured"
  },
  "records": {
    "openai::gpt-4.1": {
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
        "/internal/catalog/recognition/evidence",
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            trace_id="tracecatalogrecognitioninspect001",
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["configured"] is True
    assert payload["data"]["snapshot_exists"] is True
    assert payload["data"]["snapshot_path"] == str(snapshot_path)
    assert payload["data"]["version"] == "recognition_upstream_snapshot_v1"
    assert payload["data"]["generated_at"] == "2026-03-29T12:00:00Z"
    assert payload["data"]["records_total"] == 2
    assert payload["data"]["source_keys"] == [
        "hf_snapshot",
        "litellm_revision",
        "ollama_snapshot",
        "openrouter_snapshot",
        "siliconflow_snapshot",
    ]
    assert payload["data"]["sample_record_keys"] == [
        "huggingface::black-forest-labs/FLUX.1-dev",
        "openai::gpt-4.1",
    ]

    dispose_engine(database_url)


def test_internal_route_returns_empty_recognition_evidence_summary_when_unconfigured(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        recognition_evidence_snapshot_path="",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    response = client.get(
        "/internal/catalog/recognition/evidence",
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            trace_id="tracecatalogrecognitioninspect002",
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"] == {
        "configured": False,
        "snapshot_exists": False,
        "snapshot_path": "",
        "version": "",
        "generated_at": "",
        "records_total": 0,
        "source_keys": [],
        "sources": {},
        "sample_record_keys": [],
        "source_runs": [],
        "source_run_ids": [],
        "source_failures": [],
    }

    dispose_engine(database_url)


def test_internal_refresh_rejects_replayed_idempotency_marker(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    body = b'{"providers":["openai"]}'
    headers = merge_json_headers(
        build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            idempotency_key="catalog-refresh-replay-001",
            trace_id="tracecatalogreplay0010000000000",
        )
    )

    first_response = client.post(
        "/internal/catalog/refresh",
        content=body,
        headers=headers,
    )
    second_response = client.post(
        "/internal/catalog/refresh",
        content=body,
        headers=headers,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json()["error_code"] == "auth.replay_blocked"

    dispose_engine(database_url)


def test_catalog_routes_require_signed_headers(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    response = client.get("/v1/catalog/models")

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.site_id_required"

    dispose_engine(database_url)


def test_internal_refresh_requires_idempotency_header(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    body = b'{"providers":["openai"]}'
    response = client.post(
        "/internal/catalog/refresh",
        content=body,
        headers=merge_json_headers(
            build_internal_headers(
                internal_token=TEST_INTERNAL_AUTH_TOKEN,
                trace_id="tracecatalog0040000000000000000",
            )
        ),
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.idempotency_required"

    dispose_engine(database_url)


def test_internal_refresh_rejects_public_runtime_hmac_headers(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_catalog",
        scopes=["catalog:refresh", "health:scan"],
    )

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    body = b'{"providers":["openai"]}'
    response = client.post(
        "/internal/catalog/refresh",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/internal/catalog/refresh",
                site_id="site_catalog",
                idempotency_key="catalog-refresh-002",
                trace_id="tracecatalog0050000000000000000",
                body=body,
            )
        ),
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.internal_token_required"

    dispose_engine(database_url)


def test_internal_refresh_requires_internal_auth_configuration(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token="",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    body = b'{"providers":["openai"]}'
    response = client.post(
        "/internal/catalog/refresh",
        content=body,
        headers=merge_json_headers(
            build_internal_headers(
                internal_token=TEST_INTERNAL_AUTH_TOKEN,
                idempotency_key="catalog-refresh-003",
                trace_id="tracecatalog0060000000000000000",
            )
        ),
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "auth.internal_not_configured"

    dispose_engine(database_url)


def test_catalog_routes_do_not_accept_internal_token_only(tmp_path: Path) -> None:
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
        "/v1/catalog/models",
        headers=build_internal_headers(internal_token=TEST_INTERNAL_AUTH_TOKEN),
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.site_id_required"

    dispose_engine(database_url)


def test_internal_portal_email_test_sends_message(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    fake_sender = FakePortalEmailSender()

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        portal_public_base_url="https://cloud.example.com",
    )
    client = TestClient(
        create_app(
            CloudServices(
                settings=settings,
                portal_email_sender=fake_sender,
            )
        )
    )

    response = client.post(
        "/internal/portal/email/test",
        json={"recipient_email": "admin@example.com"},
        headers=merge_json_headers(
            build_internal_headers(
                internal_token=TEST_INTERNAL_AUTH_TOKEN,
                idempotency_key="portal-email-test-001",
                trace_id="tracecatalog0070000000000000000",
            )
        ),
    )

    assert response.status_code == 200
    assert response.json()["data"]["recipient_email"] == "admin@example.com"
    assert response.json()["data"]["portal_url"] == "https://cloud.example.com/portal/login"
    assert fake_sender.test_messages == [
        {
            "recipient_email": "admin@example.com",
            "project_name": "Magick AI Cloud Test",
            "portal_url": "https://cloud.example.com/portal/login",
        }
    ]

    dispose_engine(database_url)


def test_internal_portal_email_test_requires_configured_sender(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    response = client.post(
        "/internal/portal/email/test",
        json={"recipient_email": "admin@example.com"},
        headers=merge_json_headers(
            build_internal_headers(
                internal_token=TEST_INTERNAL_AUTH_TOKEN,
                idempotency_key="portal-email-test-002",
                trace_id="tracecatalog0080000000000000000",
            )
        ),
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "portal.email_not_configured"

    dispose_engine(database_url)
