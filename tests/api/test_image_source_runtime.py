from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.queue.in_memory import InMemoryRuntimeQueue
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import get_session, init_schema
from app.core.models import ProviderCallRecord, RunRecord, UsageMeterEvent
from app.core.services import CloudServices
from app.domain.image_sources import service as image_source_service
from app.domain.image_sources.service import (
    ImageSourceExecutionResult,
    ImageSourceProviderUsage,
    ImageSourceService,
    PixabayImageSourceProvider,
    UnsplashImageSourceProvider,
)
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_PORTAL_JWT_SECRET,
    build_auth_headers,
    merge_json_headers,
    seed_site_auth,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'image-source.sqlite3'}"


def _build_client(tmp_path: Path) -> tuple[str, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read"],
    )
    settings = Settings(
        _env_file=None,
        project_name="Magick AI Cloud Image Source Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        image_source_provider="unsplash",
        image_source_unsplash_access_key="placeholder-unsplash-key",
        image_source_cost_per_query=0.001,
    )
    client = TestClient(
        create_app(
            CloudServices(
                settings=settings,
                providers={},
                runtime_queue=InMemoryRuntimeQueue(),
            )
        )
    )
    return database_url, client


def _payload(input_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    input_payload: dict[str, Any] = {
        "contract_version": "image_source_cloud_request.v1",
        "query": "wordpress editorial hero image",
        "provider": "unsplash",
        "provider_origin": "cloud",
        "per_page": 2,
        "orientation": "landscape",
        "purpose": "featured_image_reference",
        "candidate_contract": "image_candidate.v1",
        "direct_wordpress_write": False,
    }
    input_payload.update(input_overrides or {})
    return {
        "ability_name": "magick-ai-toolbox/search-image-source",
        "contract_version": "image_source_cloud_request.v1",
        "execution_pattern": "step_offload",
        "data_classification": "public_reference_media",
        "storage_mode": "result_only",
        "timeout_seconds": 20,
        "retry_max": 0,
        "retention_ttl": 3600,
        "input": input_payload,
        "policy": {"allow_fallback": True},
    }


def _execute(
    client: TestClient,
    payload: dict[str, Any],
    *,
    idempotency_key: str = "image-source-idem",
) -> Any:
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            key_id="key_default",
            idempotency_key=idempotency_key,
            nonce=f"nonce-{idempotency_key}",
            trace_id="imagesource0000000000000000000",
            body=body,
        )
    )
    return client.post("/v1/runtime/execute", content=body, headers=headers)


def test_cloud_managed_image_source_executes_and_records_provider_usage(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url, client = _build_client(tmp_path)

    def fake_search(
        self: UnsplashImageSourceProvider,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> ImageSourceExecutionResult:
        assert query == "wordpress editorial hero image"
        assert options["orientation"] == "landscape"
        return ImageSourceExecutionResult(
            result_json={
                "artifact_type": "image_source_candidates",
                "composition_role": "image_source_candidates",
                "status": "ready",
                "provider": "magick_ai_cloud",
                "provider_mode": "unsplash",
                "candidate_contract_version": "image_candidate.v1",
                "query_hash": "hash-only",
                "query_chars": len(query),
                "active_sources": [{"provider": "unsplash", "count": 1}],
                "provider_errors": [],
                "images": [
                    {
                        "contract_version": "image_candidate.v1",
                        "id": "unsplash-photo-1",
                        "provider": "unsplash",
                        "provider_origin": "cloud",
                        "source_type": "stock",
                        "download_url": "https://images.unsplash.com/photo-1",
                        "thumbnail_url": "https://images.unsplash.com/photo-1-thumb",
                        "source_url": "https://unsplash.com/photos/photo-1",
                        "license_review_status": "required",
                        "requires_human_license_review": True,
                        "warnings": ["Review provider license before adoption."],
                        "provenance": {
                            "provider": "unsplash",
                            "provider_origin": "cloud",
                            "source_type": "stock",
                        },
                        "write_posture": "suggestion_only",
                        "direct_wordpress_write": False,
                    }
                ],
                "candidates": [],
                "handoff": {
                    "candidate_contract": "image_candidate.v1",
                    "final_writes": "core_proposal_required",
                    "direct_wordpress_write": False,
                },
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            },
            usage=ImageSourceProviderUsage(
                provider_id="unsplash",
                model_id="image-source-search",
                instance_id="cloud-managed",
                region="unspecified",
                latency_ms=9,
                cost=0.001,
            ),
        )

    monkeypatch.setattr(UnsplashImageSourceProvider, "search", fake_search)

    response = _execute(client, _payload())

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    assert data["provider_id"] == "image_source"
    assert data["provider_call_count"] == 1
    assert data["profile_id"] == "image-source.managed"
    assert data["execution_context"]["ability_family"] == "knowledge"
    assert data["execution_context"]["execution_pattern"] == "inline"
    assert data["execution_context"]["data_classification"] == "public_reference_media"
    result = data["result"]
    assert result["artifact_type"] == "image_source_candidates"
    assert result["candidate_contract_version"] == "image_candidate.v1"
    assert result["direct_wordpress_write"] is False
    assert result["handoff"]["final_writes"] == "core_proposal_required"
    candidate = result["images"][0]
    assert candidate["contract_version"] == "image_candidate.v1"
    assert candidate["source_type"] == "stock"
    assert candidate["provider_origin"] == "cloud"
    assert candidate["requires_human_license_review"] is True
    assert candidate["direct_wordpress_write"] is False
    assert "wordpress editorial hero image" not in json.dumps(result)

    with get_session(database_url) as session:
        run = session.get(RunRecord, data["run_id"])
        assert run is not None
        assert run.input_json == {}
        assert run.execution_pattern == "step_offload"
        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord).where(ProviderCallRecord.run_id == run.run_id)
            )
        )
        assert provider_calls[0].provider_id == "unsplash"
        meter_events = list(
            session.scalars(
                select(UsageMeterEvent)
                .where(UsageMeterEvent.run_id == run.run_id)
                .order_by(UsageMeterEvent.id.asc())
            )
        )
        assert [event.meter_key for event in meter_events] == [
            "runs",
            "provider_calls",
            "cost",
        ]
        assert all(event.ability_family == "knowledge" for event in meter_events)


def test_image_source_rejects_provider_keys_in_runtime_input(tmp_path: Path) -> None:
    _, client = _build_client(tmp_path)

    response = _execute(
        client,
        _payload({"provider_key": "user-supplied-provider-secret"}),
        idempotency_key="image-source-forbid-provider-key",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "image_source.write_or_secret_field_forbidden"


def test_image_source_candidate_suggested_filename_is_safe(monkeypatch: Any) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        image_source_provider="unsplash",
        image_source_unsplash_access_key="placeholder-unsplash-key",
    )

    def fake_request_json(
        self: UnsplashImageSourceProvider,
        *,
        started: float,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "results": [
                {
                    "id": "Photo Secret Prompt 123",
                    "description": "Do not leak prompt text into filename",
                    "urls": {
                        "regular": "https://images.unsplash.com/photo-abc.webp?secret=value",
                        "thumb": "https://images.unsplash.com/photo-abc-thumb.webp",
                    },
                    "links": {"html": "https://unsplash.com/photos/photo-abc"},
                    "user": {"name": "Photo Creator"},
                }
            ]
        }

    monkeypatch.setattr(UnsplashImageSourceProvider, "_request_json", fake_request_json)

    execution = ImageSourceService(settings).execute(
        site_id="site_alpha",
        ability_name="magick-ai-toolbox/search-image-source",
        contract_version="image_source_cloud_request.v1",
        input_payload={
            "contract_version": "image_source_cloud_request.v1",
            "query": "secret commercial launch prompt",
            "provider": "unsplash",
            "candidate_contract": "image_candidate.v1",
        },
        run_id="run_image_source_filename",
    )

    candidate = execution.result_json["images"][0]
    assert candidate["suggested_filename"].startswith("unsplash-image-")
    assert candidate["suggested_filename"].endswith(".webp")
    assert candidate["filename_basis"]["owner"] == "wordpress_write_ability_final"
    handoff = execution.result_json["ai_generation_handoff"]
    assert handoff["trigger"] == "manual_user_action"
    assert handoff["runtime"]["ability_name"] == "magick-ai-cloud/generate-image"
    assert handoff["runtime"]["profile_id"] == "grok-imagine-image-quality"
    assert handoff["runtime"]["execution_kind"] == "image_generation"
    assert handoff["input_defaults"]["aspect_ratio"] == "16:9"
    assert handoff["required_local_fields"] == ["prompt"]
    assert handoff["prompt_prefill_plan"]["mode"] == "local_context_prefill"
    assert handoff["prompt_prefill_plan"]["owner"] == "local_plugin_ui"
    assert handoff["prompt_prefill_plan"]["requires_user_review"] is True
    assert handoff["prompt_prefill_plan"]["safety"]["do_not_autorun"] is True
    assert handoff["batch_generation_plan"]["mode"] == "local_reviewed_batch_plan"
    assert handoff["batch_generation_plan"]["owner"] == "local_plugin_control_plane"
    assert handoff["batch_generation_plan"]["do_not_autorun"] is True
    assert handoff["direct_wordpress_write"] is False
    assert "prompt" not in candidate["suggested_filename"]
    assert "commercial" not in candidate["suggested_filename"]
    assert "secret" not in candidate["suggested_filename"]
    assert "secret=value" not in candidate["suggested_filename"]
    assert "secret commercial launch prompt" not in json.dumps(execution.result_json)


def test_pixabay_provider_preserves_api_endpoint_trailing_slash(monkeypatch: Any) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        image_source_provider="pixabay",
        image_source_auto_strategy="first_available",
        image_source_pixabay_base_url="https://pixabay.com/api",
        image_source_pixabay_api_key="placeholder-pixabay-key",
    )
    captured: dict[str, Any] = {}

    def fake_request_json(
        self: PixabayImageSourceProvider,
        *,
        started: float,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        captured["url"] = url
        captured["params"] = params or {}
        return {
            "hits": [
                {
                    "id": 123,
                    "tags": "wordpress, editorial",
                    "largeImageURL": "https://cdn.pixabay.com/photo.jpg",
                    "previewURL": "https://cdn.pixabay.com/photo-thumb.jpg",
                    "pageURL": "https://pixabay.com/photos/wordpress-123/",
                    "user": "Pixabay Creator",
                }
            ]
        }

    monkeypatch.setattr(PixabayImageSourceProvider, "_request_json", fake_request_json)

    execution = ImageSourceService(settings).execute(
        site_id="site_alpha",
        ability_name="magick-ai-toolbox/search-image-source",
        contract_version="image_source_cloud_request.v1",
        input_payload={
            "contract_version": "image_source_cloud_request.v1",
            "query": "wordpress hero image",
            "provider": "pixabay",
            "orientation": "landscape",
            "candidate_contract": "image_candidate.v1",
        },
        run_id="run_image_source_pixabay",
    )

    assert captured["url"] == "https://pixabay.com/api/"
    assert captured["params"]["orientation"] == "horizontal"
    assert execution.result_json["requested_provider_mode"] == "pixabay"
    assert execution.result_json["resolved_provider"] == "pixabay"
    assert execution.result_json["auto_strategy"] == "first_available"
    assert execution.result_json["handoff"]["available_actions"][0]["action_id"] == (
        "ai_generate_image"
    )
    candidate = execution.result_json["images"][0]
    assert candidate["provider"] == "pixabay"
    assert candidate["thumbnail_url"] == "https://cdn.pixabay.com/photo-thumb.jpg"


def test_image_source_ai_generation_handoff_uses_orientation_defaults() -> None:
    result = image_source_service._build_result(
        provider_id="unsplash",
        auto_strategy="first_available",
        query="private product prompt",
        options={
            "per_page": 1,
            "provider": "unsplash",
            "orientation": "portrait",
            "purpose": "featured_image_reference",
        },
        candidates=[],
        usage=ImageSourceProviderUsage(
            provider_id="unsplash",
            model_id="image-source-search",
            instance_id="cloud-managed",
            region="unspecified",
            latency_ms=0,
        ),
    )

    handoff = result.result_json["ai_generation_handoff"]
    assert handoff["input_defaults"]["aspect_ratio"] == "3:4"
    assert handoff["runtime"]["policy"] == {"allow_fallback": False}
    assert handoff["source_context"]["query_hash"]
    prefill_plan = handoff["prompt_prefill_plan"]
    assert prefill_plan["source_priority"][0] == "user_edited_prompt"
    assert prefill_plan["local_prompt_fields"][2]["field"] == "composition"
    assert "Portrait composition" in prefill_plan["local_prompt_fields"][2]["default"]
    assert prefill_plan["safety"]["must_review_before_execute"] is True
    assert prefill_plan["safety"]["direct_wordpress_write"] is False
    assert "private product prompt" not in json.dumps(result.result_json)


def test_image_source_ai_generation_prefill_plan_tracks_product_purpose() -> None:
    result = image_source_service._build_result(
        provider_id="unsplash",
        auto_strategy="first_available",
        query="product lifestyle image",
        options={
            "per_page": 1,
            "provider": "unsplash",
            "orientation": "square",
            "purpose": "product_gallery_image",
        },
        candidates=[],
        usage=ImageSourceProviderUsage(
            provider_id="unsplash",
            model_id="image-source-search",
            instance_id="cloud-managed",
            region="unspecified",
            latency_ms=0,
        ),
    )

    handoff = result.result_json["ai_generation_handoff"]
    prefill_plan = handoff["prompt_prefill_plan"]
    assert handoff["input_defaults"]["aspect_ratio"] == "1:1"
    assert "Professional product photography" in prefill_plan["local_prompt_fields"][3][
        "default"
    ]
    assert prefill_plan["assembly"]["section_order"] == [
        "subject",
        "context",
        "composition",
        "style",
        "constraints",
    ]
    assert "product lifestyle image" not in json.dumps(result.result_json)


def test_image_source_ai_generation_batch_plan_is_bounded_and_local_owned() -> None:
    result = image_source_service._build_result(
        provider_id="unsplash",
        auto_strategy="first_available",
        query="article image set",
        options={
            "per_page": 25,
            "provider": "unsplash",
            "orientation": "landscape",
            "purpose": "article_media_set",
        },
        candidates=[],
        usage=ImageSourceProviderUsage(
            provider_id="unsplash",
            model_id="image-source-search",
            instance_id="cloud-managed",
            region="unspecified",
            latency_ms=0,
        ),
    )

    batch_plan = result.result_json["ai_generation_handoff"]["batch_generation_plan"]
    assert batch_plan["status"] == "available_with_local_orchestration"
    assert batch_plan["requires_entitlement"] is True
    assert batch_plan["requires_user_review"] is True
    assert batch_plan["requires_per_item_prompt_review"] is True
    assert batch_plan["max_items_per_user_action"] == 10
    assert batch_plan["recommended_execution_pattern"] == "inline"
    assert batch_plan["future_execution_pattern"] == "whole_run_offload"
    assert batch_plan["write_owner"] == "local_wordpress_approval_flow"
    assert batch_plan["direct_wordpress_write"] is False
    assert batch_plan["failure_policy"]["partial_results_allowed"] is True


def test_image_source_auto_random_selects_configured_provider(monkeypatch: Any) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        image_source_provider="auto",
        image_source_auto_strategy="random",
        image_source_unsplash_access_key="",
        image_source_pixabay_api_key="placeholder-pixabay-key",
        image_source_pexels_api_key="placeholder-pexels-key",
    )
    choices: list[tuple[str, ...]] = []

    def fake_choice(provider_ids: list[str]) -> str:
        choices.append(tuple(provider_ids))
        return "pexels"

    monkeypatch.setattr(image_source_service.random, "choice", fake_choice)

    assert image_source_service._resolve_provider(settings, "auto") == "pexels"
    assert choices == [("pixabay", "pexels")]
    assert image_source_service._resolve_provider(settings, "pixabay") == "pixabay"
    assert choices == [("pixabay", "pexels")]
