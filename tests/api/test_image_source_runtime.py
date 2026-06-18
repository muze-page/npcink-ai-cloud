from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.providers.base import ProviderExecutionRequest, ProviderExecutionResult
from app.adapters.providers.openai import OpenAIProviderAdapter
from app.adapters.queue.in_memory import InMemoryRuntimeQueue
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import get_session, init_schema
from app.core.models import ProviderCallRecord, RunRecord, UsageMeterEvent
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from app.domain.image_sources import service as image_source_service
from app.domain.image_sources.service import (
    ImageSourceExecutionResult,
    ImageSourceProviderError,
    ImageSourceProviderUsage,
    ImageSourceService,
    PixabayImageSourceProvider,
    UnsplashImageSourceProvider,
)
from app.domain.site_knowledge.service import SiteKnowledgeService
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_PORTAL_JWT_SECRET,
    build_auth_headers,
    merge_json_headers,
    seed_site_auth,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'image-source.sqlite3'}"


def _build_client(
    tmp_path: Path,
    *,
    providers: dict[str, Any] | None = None,
) -> tuple[str, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    if providers:
        CatalogService(database_url, providers=providers).refresh_catalog()
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
                providers=providers or {},
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


class PromptPlannerProvider(OpenAIProviderAdapter):
    def __init__(self) -> None:
        super().__init__(sample_catalog_profile="free-gpt55")
        self.requests: list[ProviderExecutionRequest] = []

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        self.requests.append(request)
        return ProviderExecutionResult(
            output={
                "output_text": json.dumps(
                    {
                        "prompt_candidates": [
                            {
                                "id": "llm_editorial_scene",
                                "label": "LLM editorial scene",
                                "direction_type": "editorial_scene",
                                "visual_strategy": "Use related site evidence as context.",
                                "reason": "Fits the selected paragraph because it turns answer quality planning into a reviewable editorial scene.",
                                "prompt": (
                                    "Create an original editorial image about answer "
                                    "quality planning, using a desk with research notes "
                                    "and decision paths. No visible text, letters, "
                                    "numbers, logos, watermarks, screenshots, UI panels, "
                                    "or copied article wording."
                                ),
                            }
                        ]
                    }
                )
            },
            latency_ms=31,
            tokens_in=45,
            tokens_out=55,
            cost=0.0,
        )


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
    assert response.json()["error_code"] == "runtime.secret_input_detected"


def test_image_source_runtime_enriches_prompt_candidates_with_site_knowledge(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _, client = _build_client(tmp_path)

    def fake_site_knowledge_execute(
        self: SiteKnowledgeService,
        *,
        site_id: str,
        ability_name: str,
        contract_version: str,
        input_payload: dict[str, Any],
        run_id: str,
    ) -> dict[str, Any]:
        assert site_id == "site_alpha"
        assert ability_name == "magick-ai-cloud/site-knowledge-search"
        assert contract_version == "site_knowledge_search.v1"
        assert input_payload["intent"] == "image_context"
        assert input_payload["current_post_id"] == 99
        assert "AEO focuses on answer quality" in input_payload["query"]
        return {
            "artifact_type": "site_knowledge_results",
            "composition_role": "site_knowledge_context",
            "status": "ready",
            "intent": "image_context",
            "evidence_gate": {
                "status": "passed",
                "min_score": 0.2,
                "required_sources": 1,
            },
            "rerank": {"status": "disabled", "provider": "disabled"},
            "results": [
                {
                    "post_id": 42,
                    "source_type": "post",
                    "title": "Answer engine optimization guide",
                    "url": "https://example.test/aeo-guide",
                    "score": 0.88,
                    "match_context": (
                        "AEO planning should turn a user question into a direct "
                        "answer, then clarify conditions and constraints."
                    ),
                }
            ],
            "write_posture": "suggestion_only",
            "direct_wordpress_write": False,
        }

    def fake_search(
        self: UnsplashImageSourceProvider,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> ImageSourceExecutionResult:
        assert options["site_knowledge_context"]["status"] == "ready"
        assert options["site_knowledge_context"]["results"][0]["post_id"] == 42
        return image_source_service._build_result(
            provider_id="unsplash",
            auto_strategy="first_available",
            query=query,
            options=options,
            candidates=[
                {
                    "contract_version": "image_candidate.v1",
                    "id": "unsplash-photo-knowledge",
                    "provider": "unsplash",
                    "provider_origin": "cloud",
                    "source_type": "stock",
                    "download_url": "https://images.unsplash.com/photo-knowledge",
                    "thumbnail_url": "https://images.unsplash.com/photo-knowledge-thumb",
                    "source_url": "https://unsplash.com/photos/photo-knowledge",
                    "write_posture": "suggestion_only",
                    "direct_wordpress_write": False,
                }
            ],
            usage=ImageSourceProviderUsage(
                provider_id="unsplash",
                model_id="image-source-search",
                instance_id="cloud-managed",
                region="unspecified",
                latency_ms=5,
                cost=0.001,
            ),
        )

    monkeypatch.setattr(SiteKnowledgeService, "execute", fake_site_knowledge_execute)
    monkeypatch.setattr(UnsplashImageSourceProvider, "search", fake_search)

    response = _execute(
        client,
        _payload(
            {
                "visual_context": {
                    "contract_version": "image_visual_brief_request.v1",
                    "post_id": 99,
                    "image_use": "paragraph_image",
                    "selected_text": (
                        "AEO focuses on answer quality when a reader asks a clear question."
                    ),
                    "title": "SEO, AEO, and GEO for AI search",
                }
            }
        ),
        idempotency_key="image-source-site-knowledge",
    )

    assert response.status_code == 200
    result = response.json()["data"]["result"]
    assert result["visual_brief"]["site_context_status"] == "ready"
    assert result["visual_brief"]["site_context"]["evidence_refs"][0]["post_id"] == 42
    assert result["prompt_candidates"][0]["evidence_refs"][0]["title"] == (
        "Answer engine optimization guide"
    )
    assert "Answer engine optimization guide" in result["prompt_candidates"][0]["prompt"]


def test_image_source_zh_cn_returns_localized_display_fields(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _, client = _build_client(tmp_path)

    def fake_search(
        self: UnsplashImageSourceProvider,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> ImageSourceExecutionResult:
        assert options["locale"] == "zh_CN"
        return image_source_service._build_result(
            provider_id="unsplash",
            auto_strategy="first_available",
            query=query,
            options=options,
            candidates=[
                {
                    "contract_version": "image_candidate.v1",
                    "id": "unsplash-photo-zh-cn",
                    "provider": "unsplash",
                    "provider_origin": "cloud",
                    "source_type": "stock",
                    "download_url": "https://images.unsplash.com/photo-zh-cn",
                    "thumbnail_url": "https://images.unsplash.com/photo-zh-cn-thumb",
                    "source_url": "https://unsplash.com/photos/photo-zh-cn",
                    "write_posture": "suggestion_only",
                    "direct_wordpress_write": False,
                }
            ],
            usage=ImageSourceProviderUsage(
                provider_id="unsplash",
                model_id="image-source-search",
                instance_id="cloud-managed",
                region="unspecified",
                latency_ms=5,
                cost=0.001,
            ),
        )

    monkeypatch.setattr(UnsplashImageSourceProvider, "search", fake_search)

    response = _execute(
        client,
        _payload(
            {
                "locale": "zh_CN",
                "visual_context": {
                    "contract_version": "image_visual_brief_request.v1",
                    "post_id": 99,
                    "image_use": "paragraph_image",
                    "selected_text": "AEO focuses on answer quality planning.",
                    "title": "SEO, AEO, and GEO for AI search",
                },
            }
        ),
        idempotency_key="image-source-zh-cn-display",
    )

    assert response.status_code == 200, response.text
    envelope = response.json()
    assert envelope["message"] == "运行完成"

    result = envelope["data"]["result"]
    visual_brief = result["visual_brief"]
    assert visual_brief["localized_title"] == "可选配图方向"
    assert visual_brief["localized_summary"] == "已根据选中段落和文章上下文生成可审核的配图方向。"
    assert visual_brief["localized_intent"] == "把选中段落转译成编辑配图方向，不在图片中呈现原文。"
    assert visual_brief["site_context_status"] == "insufficient_evidence"
    assert visual_brief["rerank_status"] == "disabled"

    first_candidate = result["prompt_candidates"][0]
    assert first_candidate["label"] == "Editorial scene"
    assert first_candidate["reason"].startswith("Best when")
    assert first_candidate["prompt"].startswith("Create an original editorial image")
    assert first_candidate["localized_label"] == "特色图方向"
    assert first_candidate["localized_strategy"] == "用自然的编辑场景概括文章重点。"
    assert first_candidate["localized_reason"] == "适合需要一张可作为特色图的文章配图。"

    display_payload = {
        "visual_brief": {
            "title": visual_brief["localized_title"],
            "summary": visual_brief["localized_summary"],
            "intent": visual_brief["localized_intent"],
        },
        "prompt_candidates": [
            {
                "label": item["localized_label"],
                "strategy": item["localized_strategy"],
                "reason": item["localized_reason"],
            }
            for item in result["prompt_candidates"]
        ],
    }
    display_json = json.dumps(display_payload, ensure_ascii=False)
    assert "runtime executed" not in display_json
    assert "Workspace detail" not in display_json
    assert "Grounded workflow detail" not in display_json
    assert "Best when" not in display_json
    assert "insufficient_evidence" not in display_json
    assert "disabled" not in display_json


def test_image_source_fast_first_skips_heavy_enrichment_and_uses_short_query(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    planner_provider = PromptPlannerProvider()
    database_url, client = _build_client(
        tmp_path,
        providers={"openai": planner_provider},
    )

    def fail_site_knowledge_execute(
        self: SiteKnowledgeService,
        *,
        site_id: str,
        ability_name: str,
        contract_version: str,
        input_payload: dict[str, Any],
        run_id: str,
    ) -> dict[str, Any]:
        raise AssertionError("fast-first image source requests must defer site knowledge")

    def fake_search(
        self: UnsplashImageSourceProvider,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> ImageSourceExecutionResult:
        assert options["latency_mode"] == "fast_first"
        assert options["site_knowledge_context"]["status"] == "deferred"
        assert options["llm_prompt_plan"]["status"] == "deferred"
        assert "Somnia Pro是一款售价598元" not in query
        assert len(query) <= 180
        assert "search strategy workspace" in query
        return image_source_service._build_result(
            provider_id="unsplash",
            auto_strategy="first_available",
            query=query,
            options=options,
            candidates=[
                {
                    "contract_version": "image_candidate.v1",
                    "id": "unsplash-photo-fast-first",
                    "provider": "unsplash",
                    "provider_origin": "cloud",
                    "source_type": "stock",
                    "download_url": "https://images.unsplash.com/photo-fast-first",
                    "thumbnail_url": "https://images.unsplash.com/photo-fast-first-thumb",
                    "source_url": "https://unsplash.com/photos/photo-fast-first",
                    "write_posture": "suggestion_only",
                    "direct_wordpress_write": False,
                }
            ],
            usage=ImageSourceProviderUsage(
                provider_id="unsplash",
                model_id="image-source-search",
                instance_id="cloud-managed",
                region="unspecified",
                latency_ms=4,
                cost=0.001,
            ),
        )

    monkeypatch.setattr(SiteKnowledgeService, "execute", fail_site_knowledge_execute)
    monkeypatch.setattr(UnsplashImageSourceProvider, "search", fake_search)

    response = _execute(
        client,
        _payload(
            {
                "query": (
                    "Somnia Pro是一款售价598元的Linear风格博客主题，"
                    "提供专栏、会员、积分、搜索和瀑布流体验。"
                ),
                "latency_mode": "fast_first",
                "enhancement_mode": "deferred",
                "visual_context": {
                    "contract_version": "image_visual_brief_request.v1",
                    "latency_mode": "fast_first",
                    "post_id": 99,
                    "image_use": "featured_image",
                    "manual_query": "SEO AI article workflow",
                    "title": "SEO, AEO, and GEO for AI search",
                    "selected_text": (
                        "AEO focuses on answer quality when a reader asks a clear question."
                    ),
                    "candidate_limits": {"max_site_context_results": 0},
                    "cloud_ai_steps": ["visual_brief"],
                },
            }
        ),
        idempotency_key="image-source-fast-first",
    )

    assert response.status_code == 200, response.text
    result = response.json()["data"]["result"]
    assert result["visual_brief"]["site_context_status"] == "deferred"
    assert result["visual_brief"]["llm_prompt_planner_status"] == "deferred"
    assert result["visual_brief"]["source_context"]["latency_mode"] == "fast_first"
    assert result["visual_brief"]["evidence_policy"]["use_site_knowledge_vectors"] is False
    assert planner_provider.requests == []

    with get_session(database_url) as session:
        run_id = response.json()["data"]["run_id"]
        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord)
                .where(ProviderCallRecord.run_id == run_id)
                .order_by(ProviderCallRecord.id.asc())
            )
        )
        assert [call.provider_id for call in provider_calls] == ["unsplash"]


def test_image_source_runtime_uses_llm_prompt_planner_when_text_profile_is_available(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    planner_provider = PromptPlannerProvider()
    database_url, client = _build_client(
        tmp_path,
        providers={"openai": planner_provider},
    )

    def fake_site_knowledge_execute(
        self: SiteKnowledgeService,
        *,
        site_id: str,
        ability_name: str,
        contract_version: str,
        input_payload: dict[str, Any],
        run_id: str,
    ) -> dict[str, Any]:
        return {
            "artifact_type": "site_knowledge_results",
            "composition_role": "site_knowledge_context",
            "status": "ready",
            "intent": "image_context",
            "evidence_gate": {"status": "passed", "min_score": 0.2},
            "rerank": {"status": "disabled"},
            "results": [
                {
                    "post_id": 42,
                    "source_type": "post",
                    "title": "Answer quality planning",
                    "url": "https://example.test/answer-quality",
                    "score": 0.91,
                    "match_context": "Answer quality planning uses context, limits, and steps.",
                }
            ],
            "write_posture": "suggestion_only",
            "direct_wordpress_write": False,
        }

    def fake_search(
        self: UnsplashImageSourceProvider,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> ImageSourceExecutionResult:
        assert options["llm_prompt_plan"]["status"] == "ready"
        return image_source_service._build_result(
            provider_id="unsplash",
            auto_strategy="first_available",
            query=query,
            options=options,
            candidates=[
                {
                    "contract_version": "image_candidate.v1",
                    "id": "unsplash-photo-llm",
                    "provider": "unsplash",
                    "provider_origin": "cloud",
                    "source_type": "stock",
                    "download_url": "https://images.unsplash.com/photo-llm",
                    "thumbnail_url": "https://images.unsplash.com/photo-llm-thumb",
                    "source_url": "https://unsplash.com/photos/photo-llm",
                    "write_posture": "suggestion_only",
                    "direct_wordpress_write": False,
                }
            ],
            usage=ImageSourceProviderUsage(
                provider_id="unsplash",
                model_id="image-source-search",
                instance_id="cloud-managed",
                region="unspecified",
                latency_ms=5,
                cost=0.001,
            ),
        )

    monkeypatch.setattr(SiteKnowledgeService, "execute", fake_site_knowledge_execute)
    monkeypatch.setattr(UnsplashImageSourceProvider, "search", fake_search)

    response = _execute(
        client,
        _payload(
            {
                "locale": "zh_CN",
                "visual_context": {
                    "contract_version": "image_visual_brief_request.v1",
                    "post_id": 99,
                    "image_use": "paragraph_image",
                    "selected_text": "AEO focuses on answer quality planning.",
                    "title": "SEO, AEO, and GEO for AI search",
                },
            }
        ),
        idempotency_key="image-source-llm-planner",
    )

    assert response.status_code == 200, response.text
    envelope = response.json()
    assert envelope["message"] == "运行完成"
    result = envelope["data"]["result"]
    assert result["visual_brief"]["llm_prompt_planner"]["status"] == "ready"
    assert result["visual_brief"]["localized_title"] == "可选配图方向"
    assert result["prompt_candidates"][0]["source"] == "cloud_llm_prompt_planner"
    assert result["prompt_candidates"][0]["planner_profile_id"] == "text.free-gpt55"
    assert result["prompt_candidates"][0]["direction_type"] == "editorial_scene"
    assert "selected paragraph" in result["prompt_candidates"][0]["reason"]
    assert "answer quality planning" in result["prompt_candidates"][0]["prompt"]
    assert result["prompt_candidates"][0]["localized_label"] == "特色图方向"
    assert result["prompt_candidates"][0]["localized_reason"] == (
        "适合需要一张可作为特色图的文章配图。"
    )
    assert planner_provider.requests
    assert planner_provider.requests[0].profile_id == "text.free-gpt55"
    assert planner_provider.requests[0].execution_kind == "text"

    with get_session(database_url) as session:
        run_id = response.json()["data"]["run_id"]
        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord)
                .where(ProviderCallRecord.run_id == run_id)
                .order_by(ProviderCallRecord.id.asc())
            )
        )
        assert [call.provider_id for call in provider_calls] == ["openai", "unsplash"]
        assert provider_calls[0].model_id == "gpt-5.5"


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
    assert handoff["local_prompt_sources"][0] == "cloud_llm_prompt_planner.prompt_candidates"
    assert handoff["local_prompt_sources"][1] == "cloud_visual_brief.prompt_candidates"
    assert (
        execution.result_json["visual_brief"]["artifact_type"] == "paragraph_image_visual_brief.v1"
    )
    assert (
        execution.result_json["visual_brief"]["evidence_policy"]["use_site_knowledge_vectors"]
        is True
    )
    assert execution.result_json["prompt_candidates"][0]["requires_operator_review"] is True
    assert handoff["prompt_candidates"][0]["source"] == "cloud_visual_brief"
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


def test_image_source_rejects_oversized_provider_response(monkeypatch: Any) -> None:
    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout > 0

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def request(
            self,
            method: str,
            url: str,
            *,
            headers: dict[str, str],
            params: dict[str, Any],
        ) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-length": "2000001"},
                content=b"{}",
                request=httpx.Request(method, url),
            )

    monkeypatch.setattr("app.domain.image_sources.service.httpx.Client", FakeClient)
    provider = UnsplashImageSourceProvider(
        Settings(
            _env_file=None,
            environment="test",
            image_source_provider="unsplash",
            image_source_unsplash_access_key="placeholder-unsplash-key",
        )
    )

    with pytest.raises(ImageSourceProviderError) as error:
        provider._request_json(
            started=0.0,
            method="GET",
            url="https://api.unsplash.test/search/photos",
        )

    assert error.value.error_code == "provider.invalid_response"


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
    assert "Professional product photography" in prefill_plan["local_prompt_fields"][3]["default"]
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
