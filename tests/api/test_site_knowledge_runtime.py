from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from app.adapters.providers.base import (
    ProviderAdapter,
    ProviderCatalogSnapshot,
    ProviderExecutionRequest,
    ProviderExecutionResult,
)
from app.adapters.queue.in_memory import InMemoryRuntimeQueue
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import get_session, init_schema
from app.core.models import (
    ProviderCallRecord,
    SiteKnowledgeChunk,
    SiteKnowledgeIndexJobMetric,
    SiteKnowledgeIndexSnapshot,
    SiteKnowledgeSearchMetric,
    UsageMeterEvent,
)
from app.core.services import CloudServices
from app.domain.runtime.service import RuntimeService
from app.domain.site_knowledge.rerankers import (
    MAX_RERANK_DOCUMENT_CHARS,
    JinaSiteKnowledgeReranker,
    SiteKnowledgeRerankError,
)
from app.domain.site_knowledge.service import (
    MAX_FALLBACK_SEARCH_CHUNKS,
    MAX_SEARCH_QUERY_CHARS,
    MAX_SYNC_POST_IDS,
    SiteKnowledgeService,
    _apply_evidence_policy,
    _coerce_post_ids,
    _filter_string_list,
    _normalize_search_query,
    _rank_search_results_for_query,
    _resolve_evidence_policy,
)
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_PORTAL_JWT_SECRET,
    build_auth_headers,
    merge_json_headers,
    seed_site_auth,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'site-knowledge.sqlite3'}"


class _FakeEmbeddingProvider:
    display_name = "Fake Embedding"
    adapter_type = "embedding"

    def __init__(self, provider_id: str = "tei") -> None:
        self.provider_id = provider_id
        self.requests: list[ProviderExecutionRequest] = []

    def fetch_catalog(self) -> ProviderCatalogSnapshot:
        raise NotImplementedError

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        self.requests.append(request)
        return ProviderExecutionResult(
            output={
                "embedding": [0.25] * 1024,
                "dimensions": 1024,
                "model_id": "BAAI/bge-m3",
            },
            latency_ms=1,
            tokens_in=1,
            tokens_out=0,
            cost=0.0,
        )


def _build_client(
    tmp_path: Path,
    *,
    settings_overrides: dict[str, object] | None = None,
    providers: dict[str, ProviderAdapter] | None = None,
) -> tuple[str, Settings, InMemoryRuntimeQueue, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read"],
    )
    seed_site_auth(
        database_url,
        site_id="site_beta",
        key_id="key_beta",
        scopes=["runtime:execute", "runtime:read"],
    )
    settings_kwargs = {
        "project_name": "Npcink AI Cloud Site Knowledge Test",
        "environment": "test",
        "database_url": database_url,
        "redis_url": "redis://localhost:6379/0",
        "admin_session_secret": TEST_ADMIN_SESSION_SECRET,
        "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
        "site_knowledge_comments_enabled": False,
        "site_knowledge_embedding_provider": "deterministic",
        "site_knowledge_vector_backend": "postgres_json",
    }
    settings_kwargs.update(settings_overrides or {})
    settings = Settings(_env_file=None, **settings_kwargs)
    runtime_queue = InMemoryRuntimeQueue()
    client = TestClient(
        create_app(
            CloudServices(
                settings=settings,
                providers=providers or {},
                runtime_queue=runtime_queue,
            )
        )
    )
    return database_url, settings, runtime_queue, client


def _execute(
    client: TestClient,
    payload: dict[str, object],
    *,
    site_id: str = "site_alpha",
    key_id: str = "key_default",
    idempotency_key: str = "site-knowledge-idem",
) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id=site_id,
            key_id=key_id,
            idempotency_key=idempotency_key,
            nonce=f"nonce-{idempotency_key}",
            trace_id="siteknowledge000000000000000000",
            body=body,
        )
    )
    response = client.post("/v1/runtime/execute", content=body, headers=headers)
    return {
        "status_code": response.status_code,
        "json": response.json(),
    }


def _sync_payload() -> dict[str, object]:
    return {
        "ability_name": "npcink-cloud/site-knowledge-sync",
        "contract_version": "site_knowledge_sync.v1",
        "execution_pattern": "whole_run_offload",
        "data_classification": "public_site_content",
        "storage_mode": "result_only",
        "retention_ttl": 86400,
        "timeout_seconds": 60,
        "retry_max": 1,
        "policy": {"allow_fallback": True},
        "input": {
            "contract_version": "site_knowledge_sync.v1",
            "sync_mode": "refresh",
            "post_ids": [123],
            "max_posts": 20,
            "documents": [
                {
                    "post_id": 123,
                    "post_type": "post",
                    "post_status": "publish",
                    "title": "Cloud vector launch notes",
                    "url": "https://example.test/cloud-vector-launch",
                    "modified_gmt": "2026-06-03 02:00:00",
                    "excerpt": "Notes about Cloud managed site knowledge.",
                    "content_excerpt": (
                        "Cloud managed site knowledge indexes public WordPress content "
                        "for semantic search and internal link suggestions."
                    ),
                    "content_hash": "hash-cloud-vector-launch",
                }
            ],
            "write_posture": "suggestion_only",
        },
    }


def _search_payload(
    query: str,
    *,
    current_post_id: int = 0,
    intent: str = "internal_links",
    source_types: list[str] | None = None,
) -> dict[str, object]:
    filters: dict[str, object] = {
        "post_types": ["post", "page"],
        "status": ["publish"],
        "language": "zh-CN",
    }
    if source_types is not None:
        filters["source_types"] = source_types
    return {
        "ability_name": "npcink-cloud/site-knowledge-search",
        "contract_version": "site_knowledge_search.v1",
        "execution_pattern": "inline",
        "data_classification": "public_site_content",
        "storage_mode": "result_only",
        "retention_ttl": 86400,
        "timeout_seconds": 20,
        "retry_max": 0,
        "policy": {"allow_fallback": True},
        "input": {
            "contract_version": "site_knowledge_search.v1",
            "query": query,
            "intent": intent,
            "current_post_id": current_post_id,
            "max_results": 8,
            "filters": filters,
            "write_posture": "suggestion_only",
        },
    }


def test_site_knowledge_search_input_helpers_bound_user_controlled_lists() -> None:
    assert (
        _normalize_search_query("  AI   摘要  " + ("x" * 900))
        == ("AI 摘要 " + ("x" * 900))[:MAX_SEARCH_QUERY_CHARS]
    )
    post_ids = _coerce_post_ids([1, "2", 1, 0, -3, *range(3, MAX_SYNC_POST_IDS + 50)])
    assert post_ids[0:3] == [1, 2, 3]
    assert len(post_ids) == MAX_SYNC_POST_IDS
    assert len(post_ids) == len(set(post_ids))
    assert _filter_string_list(
        ["post", "page", "post", "attachment", "comment", "page"],
        allowed=frozenset({"post", "page", "comment"}),
    ) == ["post", "page", "comment"]


def test_toolbox_exact_sync_payload_queues_without_routing_fields(tmp_path: Path) -> None:
    _, _, _, client = _build_client(tmp_path)

    result = _execute(client, _sync_payload(), idempotency_key="sync-no-routing-fields")

    assert result["status_code"] == 200
    data = result["json"]["data"]
    assert data["status"] == "queued"
    assert data["provider_id"] == "site_knowledge"
    assert data["execution_context"]["ability_family"] == "knowledge"
    assert data["execution_context"]["execution_pattern"] == "whole_run_offload"
    assert data["execution_context"]["data_classification"] == "public_site_content"
    assert data["profile_id"] == "site-knowledge.managed"
    assert data["result"] == {}


def test_sync_then_search_and_status_coverage(tmp_path: Path) -> None:
    database_url, settings, runtime_queue, client = _build_client(tmp_path)
    sync_result = _execute(client, _sync_payload(), idempotency_key="sync-then-search")
    run_id = sync_result["json"]["data"]["run_id"]

    queued_status = _execute(
        client,
        {
            "ability_name": "npcink-cloud/site-knowledge-status",
            "contract_version": "site_knowledge_status.v1",
            "execution_pattern": "inline",
            "data_classification": "public_site_content",
            "storage_mode": "result_only",
            "input": {
                "contract_version": "site_knowledge_status.v1",
                "include_coverage": True,
                "write_posture": "suggestion_only",
            },
        },
        idempotency_key="status-while-sync-queued",
    )["json"]["data"]["result"]
    assert queued_status["status"] == "syncing"
    assert queued_status["contract_version"] == "site_knowledge_status.v1"
    assert queued_status["ownership"]["index_execution_owner"] == "cloud_service"
    assert queued_status["ownership"]["delivery_bridge_owner"] == "cloud_addon"
    assert queued_status["ownership"]["wordpress_write_owner"] == "local_wordpress_host"
    assert queued_status["truth_boundaries"]["cloud_is_index_truth"] is True
    assert queued_status["truth_boundaries"]["cloud_is_freshness_truth"] is True
    assert queued_status["truth_boundaries"]["cloud_is_diagnostics_truth"] is True
    assert queued_status["truth_boundaries"]["cloud_is_wordpress_control_plane"] is False
    assert queued_status["truth_boundaries"]["cloud_creates_wordpress_writes"] is False
    assert queued_status["active_run"]["run_id"] == run_id
    assert queued_status["progress"]["stage"] == "queued"

    worker = RuntimeService(
        database_url,
        settings=settings,
        providers={},
        runtime_queue=runtime_queue,
    )
    processed = worker.process_next_queued_run(timeout_seconds=0)

    assert processed == {
        "run_id": run_id,
        "status": "succeeded",
        "trace_id": sync_result["json"]["data"]["trace_id"],
    }
    worker_result = RuntimeService(
        database_url,
        settings=settings,
        providers={},
    ).get_run_result(run_id, site_id="site_alpha")
    assert worker_result["result"]["contract_version"] == "site_knowledge_sync.v1"
    assert worker_result["result"]["ownership"]["index_lifecycle_owner"] == "cloud_service"
    assert worker_result["result"]["ownership"]["freshness_policy_owner"] == "cloud_service"
    assert worker_result["result"]["ownership"]["approval_owner"] == "local_wordpress_host"
    assert worker_result["result"]["truth_boundaries"]["cloud_owns_ability_registry"] is False
    assert worker_result["result"]["truth_boundaries"]["cloud_owns_workflow_registry"] is False
    assert worker_result["result"]["progress"]["stage"] == "completed"
    assert worker_result["result"]["progress"]["percent"] == 100

    search_result = _execute(
        client,
        _search_payload("semantic search internal links"),
        idempotency_key="search-after-sync",
    )
    assert search_result["status_code"] == 200
    search_data = search_result["json"]["data"]["result"]
    assert search_data["artifact_type"] == "site_knowledge_results"
    assert search_data["write_posture"] == "suggestion_only"
    assert search_data["direct_wordpress_write"] is False
    assert search_data["rerank"]["status"] == "disabled"
    assert search_data["evidence_gate"]["status"] == "passed"
    assert search_data["evidence_gate"]["allows_site_grounded_assertion"] is True
    assert search_data["results"][0]["post_id"] == 123
    assert search_data["results"][0]["suggested_use"] == "internal_link"
    assert search_data["results"][0]["insert_mode"] == "wordpress_local_only"
    assert search_data["results"][0]["anchor_text_candidates"]

    status_result = _execute(
        client,
        {
            "ability_name": "npcink-cloud/site-knowledge-status",
            "contract_version": "site_knowledge_status.v1",
            "execution_pattern": "inline",
            "data_classification": "public_site_content",
            "storage_mode": "result_only",
            "input": {
                "contract_version": "site_knowledge_status.v1",
                "include_coverage": True,
                "write_posture": "suggestion_only",
            },
        },
        idempotency_key="status-after-sync",
    )
    status_data = status_result["json"]["data"]["result"]
    assert status_data["status"] == "ready"
    assert status_data["contract_version"] == "site_knowledge_status.v1"
    assert status_data["ownership"]["diagnostics_detail_owner"] == "cloud_service"
    assert status_data["ownership"]["final_write_owner"] == "local_wordpress_host"
    assert status_data["truth_boundaries"]["cloud_is_diagnostics_truth"] is True
    assert status_data["truth_boundaries"]["cloud_owns_local_approval"] is False
    assert status_data["coverage"]["indexed_posts"] == 1
    assert status_data["coverage"]["indexed_chunks"] >= 1
    assert status_data["coverage"]["post_type_coverage"] == {"post": 1.0}
    assert status_data["coverage"]["source_type_coverage"] == {"post": 1.0}
    assert status_data["progress"]["stage"] == "completed"
    assert status_data["progress"]["percent"] == 100
    with get_session(database_url) as session:
        index_metric = session.query(SiteKnowledgeIndexJobMetric).one()
        search_metric = session.query(SiteKnowledgeSearchMetric).one()
        snapshots = session.query(SiteKnowledgeIndexSnapshot).all()
    assert index_metric.run_id == run_id
    assert index_metric.status == "succeeded"
    assert index_metric.indexed_documents == 1
    assert index_metric.indexed_chunks >= 1
    assert search_metric.status == "succeeded"
    assert search_metric.result_count >= 1
    assert search_metric.no_hit is False
    assert search_metric.query_hash
    assert "semantic search internal links" not in json.dumps(search_metric.filter_json or {})
    assert snapshots
    assert snapshots[-1].document_count == 1
    assert snapshots[-1].chunk_count >= 1


def test_site_knowledge_postgres_fallback_search_uses_chunk_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, settings, _, _ = _build_client(tmp_path)
    captured: dict[str, object] = {}

    def _list_search_chunks(self: object, **kwargs: object) -> list[object]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        "app.domain.site_knowledge.repository.SiteKnowledgeRepository.list_search_chunks",
        _list_search_chunks,
    )

    with get_session(database_url) as session:
        service = SiteKnowledgeService(session, settings=settings)
        result = service.search(
            site_id="site_alpha",
            run_id="run-fallback-limit",
            input_payload={
                "contract_version": "site_knowledge_search.v1",
                "query": "AI 摘要" + ("x" * 800),
                "intent": "site_search",
                "max_results": 8,
                "filters": {"source_types": ["post", "post", "page"]},
                "write_posture": "suggestion_only",
            },
        )

    assert result["status"] == "ready"
    assert captured["limit"] == MAX_FALLBACK_SEARCH_CHUNKS
    assert captured["source_types"] == ["post", "page"]


def test_search_intents_return_product_workflow_metadata(tmp_path: Path) -> None:
    database_url, settings, runtime_queue, client = _build_client(tmp_path)
    _execute(client, _sync_payload(), idempotency_key="workflow-metadata-sync")
    RuntimeService(
        database_url,
        settings=settings,
        providers={},
        runtime_queue=runtime_queue,
    ).process_next_queued_run(timeout_seconds=0)

    writing_context = _execute(
        client,
        _search_payload("Cloud managed writing context", intent="writing_context"),
        idempotency_key="workflow-writing-context",
    )["json"]["data"]["result"]
    assert writing_context["intent"] == "writing_context"
    assert writing_context["workflow_support"]["workflow"] == "writer_context_enrichment"
    assert writing_context["workflow_support"]["wordpress_write_owner"] == "wordpress_local"
    assert writing_context["results"][0]["context_role"] == "site_reference"
    assert writing_context["results"][0]["citation"]["post_id"] == 123
    assert writing_context["results"][0]["suggested_use"] == "reference_snippet"

    refresh = _execute(
        client,
        _search_payload("Cloud managed site knowledge", intent="refresh_suggestions"),
        idempotency_key="workflow-refresh-suggestions",
    )["json"]["data"]["result"]
    assert refresh["intent"] == "refresh_suggestions"
    assert refresh["workflow_support"]["workflow"] == "content_refresh_review"
    assert refresh["results"][0]["refresh_action"] == "review_for_update_or_merge"
    assert refresh["results"][0]["update_mode"] == "wordpress_local_only"
    assert refresh["results"][0]["suggested_use"] == "refresh_candidate"
    assert refresh["results"][0]["duplicate_check"]["preflight_action"] == (
        "review_existing_content_before_drafting"
    )


def test_search_intents_support_copilot_duplicate_and_cluster_workflows(
    tmp_path: Path,
) -> None:
    database_url, settings, runtime_queue, client = _build_client(tmp_path)
    _execute(client, _sync_payload(), idempotency_key="high-value-workflows-sync")
    RuntimeService(
        database_url,
        settings=settings,
        providers={},
        runtime_queue=runtime_queue,
    ).process_next_queued_run(timeout_seconds=0)

    copilot = _execute(
        client,
        _search_payload("What has this site said about vector knowledge?", intent="site_search"),
        idempotency_key="site-content-copilot",
    )["json"]["data"]["result"]
    assert copilot["workflow_support"]["workflow"] == "site_content_copilot"
    assert copilot["workflow_support"]["cloud_output"] == "answer_sources"
    assert copilot["agent_handoff"]["handoff_type"] == "suggestion_only"
    assert copilot["agent_handoff"]["requires_local_approval"] is False
    assert copilot["agent_handoff"]["proposal_input"] == {}
    assert copilot["agent_handoff"]["direct_wordpress_write"] is False
    assert copilot["results"][0]["suggested_use"] == "answer_source"
    assert copilot["results"][0]["copilot_action"] == "answer_with_site_citation"
    assert copilot["results"][0]["answer_source"]["post_id"] == 123

    cluster = _execute(
        client,
        _search_payload("Cloud vector knowledge topic cluster", intent="related_content"),
        idempotency_key="topic-cluster-planning",
    )["json"]["data"]["result"]
    assert cluster["workflow_support"]["workflow"] == "topic_cluster_planning"
    assert cluster["workflow_support"]["cloud_output"] == "cluster_candidates"
    assert cluster["results"][0]["suggested_use"] == "topic_cluster_candidate"
    assert cluster["results"][0]["planning_mode"] == "wordpress_local_only"
    assert cluster["results"][0]["cluster_candidate"]["post_id"] == 123


def test_high_value_intents_return_advisory_product_metadata(tmp_path: Path) -> None:
    payload = _sync_payload()
    input_payload = payload["input"]
    assert isinstance(input_payload, dict)
    input_payload["comments"] = [
        {
            "comment_id": 987,
            "post_id": 123,
            "comment_status": "approved",
            "created_gmt": "2026-06-03 03:00:00",
            "url": "https://example.test/cloud-vector-launch#comment-987",
            "content_excerpt": "Can BGE-M3 improve Chinese and English semantic search?",
            "content_hash": "comment-faq-hash-987",
        }
    ]
    database_url, settings, runtime_queue, client = _build_client(
        tmp_path,
        settings_overrides={"site_knowledge_comments_enabled": True},
    )
    _execute(client, payload, idempotency_key="high-value-intents-sync")
    RuntimeService(
        database_url,
        settings=settings,
        providers={},
        runtime_queue=runtime_queue,
    ).process_next_queued_run(timeout_seconds=0)

    faq = _execute(
        client,
        _search_payload(
            "Chinese English semantic search questions",
            intent="faq_candidates",
            source_types=["comment"],
        ),
        idempotency_key="faq-candidates-search",
    )["json"]["data"]["result"]
    assert faq["workflow_support"]["workflow"] == "faq_candidate_mining"
    assert faq["results"][0]["source_type"] == "comment"
    assert faq["results"][0]["suggested_use"] == "faq_candidate"
    assert faq["results"][0]["faq_candidate"]["source_signal"] == ("approved_comment_question")
    assert faq["results"][0]["faq_mode"] == "wordpress_local_only"

    gap = _execute(
        client,
        _search_payload(
            "What content is missing for vector indexing?",
            intent="content_gap_analysis",
        ),
        idempotency_key="content-gap-search",
    )["json"]["data"]["result"]
    assert gap["workflow_support"]["workflow"] == "content_gap_analysis"
    assert gap["workflow_support"]["cloud_output"] == "gap_evidence"
    assert gap["agent_handoff"]["agent_id"] == "site_knowledge_suggestion_agent"
    assert gap["agent_handoff"]["triggering_ability"] == ("npcink-cloud/site-knowledge-search")
    assert gap["agent_handoff"]["triggering_contract"] == "site_knowledge_search.v1"
    assert gap["agent_handoff"]["handoff_type"] == "proposal_input"
    assert gap["agent_handoff"]["handoff_owner"] == "wordpress_local"
    assert gap["agent_handoff"]["local_handoff_owner"] == "wordpress_local"
    assert gap["agent_handoff"]["requires_local_approval"] is True
    assert gap["agent_handoff"]["direct_wordpress_write"] is False
    assert gap["agent_handoff"]["execution_pattern"] == "inline"
    assert gap["agent_handoff"]["storage_mode"] == "result_only"
    assert gap["agent_handoff"]["evidence_requirements"]["no_hit_policy"] == "abstain"
    assert "local_approval_required" in gap["agent_handoff"]["stop_conditions"]
    assert "article_write_plan_generation" in gap["agent_handoff"]["forbidden_actions"]
    assert gap["agent_handoff"]["fail_closed_behavior"] == (
        "return_suggestion_only_without_wordpress_write"
    )
    assert gap["agent_handoff"]["proposal_input"]["workflow"] == "content_gap_analysis"
    assert gap["agent_handoff"]["proposal_input"]["local_next_action"] == (
        "review_content_gap_before_local_plan"
    )
    assert gap["agent_handoff"]["proposal_input"]["evidence_refs"][0]["post_id"] == 123
    assert gap["results"][0]["suggested_use"] == "gap_evidence"
    assert gap["results"][0]["gap_signal"]["signals"] == [
        "semantic_near_match",
        "coverage_review_needed",
    ]
    assert gap["results"][0]["planning_mode"] == "wordpress_local_only"

    duplicate = _execute(
        client,
        _search_payload("Cloud vector launch notes draft", intent="duplicate_check"),
        idempotency_key="duplicate-check-search",
    )["json"]["data"]["result"]
    assert duplicate["workflow_support"]["workflow"] == "publish_preflight_duplicate_check"
    assert duplicate["workflow_support"]["cloud_output"] == ("duplicate_or_conflict_candidates")
    assert duplicate["results"][0]["suggested_use"] == "duplicate_or_conflict_candidate"
    assert duplicate["results"][0]["duplicate_check"]["review_mode"] == ("wordpress_local_only")
    assert duplicate["direct_wordpress_write"] is False


def test_writing_support_plan_returns_pre_draft_assistance_without_article_generation(
    tmp_path: Path,
) -> None:
    database_url, settings, runtime_queue, client = _build_client(tmp_path)
    _execute(client, _sync_payload(), idempotency_key="writing-support-plan-sync")
    RuntimeService(
        database_url,
        settings=settings,
        providers={},
        runtime_queue=runtime_queue,
    ).process_next_queued_run(timeout_seconds=0)

    support = _execute(
        client,
        _search_payload(
            "How should I prepare a useful article about Cloud vector knowledge?",
            intent="writing_support_plan",
        ),
        idempotency_key="writing-support-plan-search",
    )["json"]["data"]["result"]

    assert support["intent"] == "writing_support_plan"
    assert support["workflow_support"] == {
        "workflow": "writer_preparation_support",
        "wordpress_write_owner": "wordpress_local",
        "cloud_output": "pre_draft_support_plan",
        "writing_assistance_owner": "wordpress_local_writer",
    }
    assert support["direct_wordpress_write"] is False
    assert support["write_posture"] == "suggestion_only"
    assert support["results"][0]["suggested_use"] == "writing_support_evidence"
    assert support["results"][0]["planning_mode"] == "wordpress_local_only"
    writing_support = support["results"][0]["writing_support"]
    assert writing_support["evidence_source"]["post_id"] == 123
    assert writing_support["writer_next_action"] == "use_as_preparation_material_before_drafting"
    assert writing_support["pre_draft_tasks"] == [
        "verify_facts_against_source",
        "decide_expand_existing_or_write_new_coverage",
        "collect_internal_link_and_media_candidates",
    ]
    assert writing_support["blocked_outputs"] == [
        "article_body",
        "article_title",
        "seo_copy",
        "article_write_plan",
        "full_article_draft",
        "ready_to_publish_content",
        "auto_publish_instruction",
        "direct_wordpress_write",
    ]


def test_empty_index_search_returns_ready_empty_results(tmp_path: Path) -> None:
    database_url, _, _, client = _build_client(tmp_path)

    result = _execute(client, _search_payload("nothing indexed"), idempotency_key="empty-search")

    assert result["status_code"] == 200
    data = result["json"]["data"]["result"]
    assert data["status"] == "ready"
    assert data["results"] == []
    assert data["evidence_gate"]["status"] == "insufficient_evidence"
    assert data["evidence_gate"]["no_hit_policy"] == "abstain"
    assert data["evidence_gate"]["allows_site_grounded_assertion"] is False
    assert "do not invent site-specific facts" in data["evidence_gate"]["guidance"]
    assert data["direct_wordpress_write"] is False
    with get_session(database_url) as session:
        metric = session.query(SiteKnowledgeSearchMetric).one()
    assert metric.no_hit is True
    assert metric.result_count == 0
    assert metric.query_hash
    assert metric.query_chars == len("nothing indexed")


def test_site_knowledge_index_is_isolated_by_site_id(tmp_path: Path) -> None:
    database_url, settings, runtime_queue, client = _build_client(tmp_path)
    _execute(client, _sync_payload(), idempotency_key="isolation-sync-alpha")
    RuntimeService(
        database_url,
        settings=settings,
        providers={},
        runtime_queue=runtime_queue,
    ).process_next_queued_run(timeout_seconds=0)

    beta_result = _execute(
        client,
        _search_payload("Cloud managed site knowledge"),
        site_id="site_beta",
        key_id="key_beta",
        idempotency_key="isolation-search-beta",
    )

    assert beta_result["status_code"] == 200
    assert beta_result["json"]["data"]["result"]["results"] == []


def test_search_evidence_policy_can_filter_low_confidence_results(tmp_path: Path) -> None:
    database_url, settings, runtime_queue, client = _build_client(tmp_path)
    _execute(client, _sync_payload(), idempotency_key="evidence-policy-sync")
    RuntimeService(
        database_url,
        settings=settings,
        providers={},
        runtime_queue=runtime_queue,
    ).process_next_queued_run(timeout_seconds=0)

    payload = _search_payload("Cloud managed site knowledge")
    input_payload = payload["input"]
    assert isinstance(input_payload, dict)
    input_payload["evidence_policy"] = {
        "min_score": 1.0,
        "required_sources": 1,
        "no_hit_policy": "abstain",
    }

    result = _execute(client, payload, idempotency_key="evidence-policy-search")

    assert result["status_code"] == 200
    data = result["json"]["data"]["result"]
    assert data["results"] == []
    assert data["evidence_gate"]["status"] == "insufficient_evidence"
    assert data["evidence_gate"]["min_score"] == 1.0
    assert data["evidence_gate"]["required_sources"] == 1
    assert data["evidence_gate"]["source_count"] == 0
    assert data["evidence_gate"]["allows_site_grounded_assertion"] is False
    assert data["write_posture"] == "suggestion_only"
    assert data["direct_wordpress_write"] is False


def test_default_search_evidence_policy_filters_weak_matches() -> None:
    policy = _resolve_evidence_policy(None)

    filtered = _apply_evidence_policy(
        [
            {"post_id": 109, "score": 0.3761},
            {"post_id": 4312, "score": 0.5107},
        ],
        policy,
    )

    assert policy["min_score"] == 0.45
    assert [result["post_id"] for result in filtered] == [4312]


def test_search_ranking_prioritizes_exact_query_matches() -> None:
    ranked = _rank_search_results_for_query(
        "AI 摘要",
        [
            {
                "post_id": 4312,
                "score": 0.5114,
                "match_type": "semantic",
                "exact_query_match": False,
                "match_count": 0,
            },
            {
                "post_id": 4312,
                "score": 0.5099,
                "match_type": "exact",
                "exact_query_match": True,
                "match_count": 1,
            },
        ],
    )

    assert ranked[0]["exact_query_match"] is True
    assert ranked[0]["match_type"] == "exact"


def test_site_knowledge_jina_rerank_requires_cloud_managed_key(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            project_name="Npcink AI Cloud Site Knowledge Test",
            environment="test",
            database_url=_sqlite_url(tmp_path),
            redis_url="redis://localhost:6379/0",
            admin_session_secret=TEST_ADMIN_SESSION_SECRET,
            portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
            site_knowledge_rerank_provider="jina",
            site_knowledge_jina_api_key="",
        )

    settings = Settings(
        _env_file=None,
        project_name="Npcink AI Cloud Site Knowledge Test",
        environment="test",
        database_url=_sqlite_url(tmp_path),
        redis_url="redis://localhost:6379/0",
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        site_knowledge_rerank_provider="jina",
        site_knowledge_jina_api_key="unit-test-redacted",
    )

    assert settings.site_knowledge_rerank_provider == "jina"
    assert settings.site_knowledge_jina_rerank_model == "jina-reranker-v3"
    assert settings.site_knowledge_rerank_top_k == 30


def test_jina_reranker_reorders_candidates_without_exposing_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        project_name="Npcink AI Cloud Site Knowledge Test",
        environment="test",
        database_url=_sqlite_url(tmp_path),
        redis_url="redis://localhost:6379/0",
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        site_knowledge_rerank_provider="jina",
        site_knowledge_jina_api_key="unit-test-redacted",
    )
    captured: dict[str, object] = {}

    class _Response:
        headers: dict[str, str] = {}
        content = b'{"results":[]}'

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "results": [
                    {"index": 1, "relevance_score": 0.91},
                    {"index": 0, "relevance_score": 0.21},
                ]
            }

    def _post(*args: object, **kwargs: object) -> _Response:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _Response()

    monkeypatch.setattr("app.domain.site_knowledge.rerankers.httpx.post", _post)

    outcome = JinaSiteKnowledgeReranker(settings).rerank(
        query="AI 摘要",
        results=[
            {
                "post_id": 1,
                "title": "Weak",
                "chunk": "General AI content.",
                "score": 0.7,
            },
            {
                "post_id": 2,
                "title": "Strong",
                "chunk": "AI 摘要 is discussed here." + ("x" * 3000),
                "score": 0.6,
            },
        ],
    )

    assert [result["post_id"] for result in outcome.results] == [2, 1]
    assert outcome.results[0]["rerank_provider"] == "jina"
    assert outcome.results[0]["rerank_score"] == 0.91
    assert outcome.metadata == {
        "status": "succeeded",
        "provider": "jina",
        "model": "jina-reranker-v3",
        "candidate_count": 2,
        "reranked_count": 2,
    }
    assert "unit-test-redacted" not in json.dumps(outcome.metadata)
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["json"]["model"] == "jina-reranker-v3"
    assert kwargs["json"]["query"] == "AI 摘要"
    assert kwargs["json"]["return_documents"] is False
    assert (
        max(len(document) for document in kwargs["json"]["documents"]) <= MAX_RERANK_DOCUMENT_CHARS
    )
    assert kwargs["headers"]["Authorization"] == "Bearer unit-test-redacted"


def test_jina_reranker_rejects_oversized_provider_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        project_name="Npcink AI Cloud Site Knowledge Test",
        environment="test",
        database_url=_sqlite_url(tmp_path),
        redis_url="redis://localhost:6379/0",
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        site_knowledge_rerank_provider="jina",
        site_knowledge_jina_api_key="unit-test-redacted",
    )

    class _Response:
        headers = {"content-length": "2000001"}
        content = b"{}"

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            raise AssertionError("oversized response must not be parsed")

    def _post(*args: object, **kwargs: object) -> _Response:
        return _Response()

    monkeypatch.setattr("app.domain.site_knowledge.rerankers.httpx.post", _post)

    with pytest.raises(SiteKnowledgeRerankError) as error:
        JinaSiteKnowledgeReranker(settings).rerank(
            query="AI 摘要",
            results=[
                {"post_id": 1, "title": "Weak", "chunk": "General AI content.", "score": 0.7},
                {"post_id": 2, "title": "Strong", "chunk": "Relevant AI summary.", "score": 0.6},
            ],
        )

    assert error.value.error_code == "site_knowledge.jina_rerank_failed"


def test_site_knowledge_rerank_failure_falls_back_to_vector_order(tmp_path: Path) -> None:
    database_url, settings, _, _ = _build_client(
        tmp_path,
        settings_overrides={
            "site_knowledge_rerank_provider": "jina",
            "site_knowledge_jina_api_key": "unit-test-redacted",
        },
    )

    class _FailingReranker:
        def rerank(
            self,
            *,
            query: str,
            results: list[dict[str, object]],
        ) -> object:
            raise SiteKnowledgeRerankError("site_knowledge.jina_rerank_failed", "failed")

    with get_session(database_url) as session:
        service = SiteKnowledgeService(session, settings=settings)
        service.reranker = _FailingReranker()
        results, rerank = service._maybe_rerank_results(
            query="AI 摘要",
            results=[
                {"post_id": 1, "score": 0.7, "exact_query_match": False},
                {"post_id": 2, "score": 0.6, "exact_query_match": False},
            ],
        )

    assert [result["post_id"] for result in results] == [1, 2]
    assert rerank == {
        "status": "failed",
        "provider": "jina",
        "error_code": "site_knowledge.jina_rerank_failed",
        "candidate_count": 2,
        "fallback": "vector_order",
    }


def test_forbidden_write_fields_fail_closed(tmp_path: Path) -> None:
    _, _, _, client = _build_client(tmp_path)
    payload = _search_payload("publish this")
    input_payload = payload["input"]
    assert isinstance(input_payload, dict)
    input_payload["direct_wordpress_write"] = True

    result = _execute(client, payload, idempotency_key="forbidden-write-field")

    assert result["status_code"] == 400
    assert result["json"]["error_code"] == "site_knowledge.write_field_forbidden"


def test_sync_ignores_non_publish_documents(tmp_path: Path) -> None:
    database_url, settings, runtime_queue, client = _build_client(tmp_path)
    payload = _sync_payload()
    input_payload = payload["input"]
    assert isinstance(input_payload, dict)
    documents = input_payload["documents"]
    assert isinstance(documents, list)
    documents.append(
        {
            "post_id": 456,
            "post_type": "post",
            "post_status": "draft",
            "title": "Draft secret",
            "url": "https://example.test/draft",
            "content_excerpt": "This draft must not be indexed.",
            "content_hash": "draft-hash",
        }
    )

    sync_result = _execute(client, payload, idempotency_key="non-publish-sync")
    RuntimeService(
        database_url,
        settings=settings,
        providers={},
        runtime_queue=runtime_queue,
    ).process_next_queued_run(timeout_seconds=0)
    worker_result = RuntimeService(
        database_url,
        settings=settings,
        providers={},
    ).get_run_result(sync_result["json"]["data"]["run_id"], site_id="site_alpha")

    assert worker_result["result"]["sync"]["accepted_documents"] == 1
    assert worker_result["result"]["sync"]["failed_documents"] == 1
    with get_session(database_url) as session:
        chunks = list(session.query(SiteKnowledgeChunk).all())
    assert {chunk.post_id for chunk in chunks} == {123}


def test_sync_strips_style_script_noise_before_indexing(tmp_path: Path) -> None:
    database_url, settings, runtime_queue, client = _build_client(tmp_path)
    payload = _sync_payload()
    input_payload = payload["input"]
    assert isinstance(input_payload, dict)
    documents = input_payload["documents"]
    assert isinstance(documents, list)
    documents[0] = {
        "post_id": 321,
        "post_type": "page",
        "post_status": "publish",
        "title": "AI 摘要 &#8211; 页面",
        "url": "https://example.test/ai-summary",
        "modified_gmt": "2026-06-03 02:00:00",
        "excerpt": "<style>.hero { opacity: 0; }</style>AI 摘要页面说明",
        "content_excerpt": (
            "<script>alert('secret')</script>"
            "@keyframes fadeInUp { from { opacity: 0; transform: translateY(40px); } "
            "to { opacity: 1; transform: translateY(0); } } "
            "AI 摘要用于给文章提供站内上下文。"
        ),
        "content_hash": "hash-ai-summary-noisy-page",
    }

    _execute(client, payload, idempotency_key="strip-noise-sync")
    RuntimeService(
        database_url,
        settings=settings,
        providers={},
        runtime_queue=runtime_queue,
    ).process_next_queued_run(timeout_seconds=0)

    with get_session(database_url) as session:
        chunk = session.query(SiteKnowledgeChunk).one()
    assert "AI 摘要" in chunk.chunk_text
    assert "&#8211;" not in chunk.chunk_text
    assert "@keyframes" not in chunk.chunk_text
    assert "opacity" not in chunk.chunk_text
    assert "alert" not in chunk.chunk_text


def test_sync_caps_long_documents_and_reports_truncation(tmp_path: Path) -> None:
    database_url, settings, runtime_queue, client = _build_client(tmp_path)
    payload = _sync_payload()
    input_payload = payload["input"]
    assert isinstance(input_payload, dict)
    documents = input_payload["documents"]
    assert isinstance(documents, list)
    documents[0] = {
        "post_id": 654,
        "post_type": "post",
        "post_status": "publish",
        "title": "Long AI 摘要 guide",
        "url": "https://example.test/long-ai-summary",
        "modified_gmt": "2026-06-03 02:00:00",
        "excerpt": "Long public article.",
        "content_excerpt": "AI 摘要 " * 12000,
        "content_hash": "hash-long-ai-summary",
    }

    sync_result = _execute(client, payload, idempotency_key="long-doc-truncation-sync")
    RuntimeService(
        database_url,
        settings=settings,
        providers={},
        runtime_queue=runtime_queue,
    ).process_next_queued_run(timeout_seconds=0)
    worker_result = RuntimeService(
        database_url,
        settings=settings,
        providers={},
    ).get_run_result(sync_result["json"]["data"]["run_id"], site_id="site_alpha")

    assert worker_result["result"]["sync"]["truncated_documents"] == 1
    assert worker_result["result"]["sync"]["indexed_chunks"] <= 64
    assert worker_result["result"]["sync"]["indexed_chunks"] > 1
    status_result = _execute(
        client,
        {
            "ability_name": "npcink-cloud/site-knowledge-status",
            "contract_version": "site_knowledge_status.v1",
            "execution_pattern": "inline",
            "data_classification": "public_site_content",
            "storage_mode": "result_only",
            "input": {
                "contract_version": "site_knowledge_status.v1",
                "include_coverage": True,
                "write_posture": "suggestion_only",
            },
        },
        idempotency_key="long-doc-truncation-status",
    )
    assert status_result["json"]["data"]["result"]["coverage"]["truncated_documents"] == 1
    with get_session(database_url) as session:
        chunks = list(session.query(SiteKnowledgeChunk).all())
        metadata = chunks[0].metadata_json
    assert len(chunks) <= 64
    assert isinstance(metadata, dict)
    assert metadata["max_chunks"] == 64


def test_sync_enforces_per_run_document_quota(tmp_path: Path) -> None:
    database_url, settings, runtime_queue, client = _build_client(
        tmp_path,
        settings_overrides={"site_knowledge_max_sync_documents_per_run": 1},
    )
    payload = _sync_payload()
    input_payload = payload["input"]
    assert isinstance(input_payload, dict)
    documents = input_payload["documents"]
    assert isinstance(documents, list)
    documents.append(
        {
            "post_id": 456,
            "post_type": "page",
            "post_status": "publish",
            "title": "Skipped due to per-run quota",
            "url": "https://example.test/quota-skipped",
            "modified_gmt": "2026-06-03 04:00:00",
            "excerpt": "This public page should wait for a later batch.",
            "content_excerpt": "Cloud site knowledge quota protection.",
            "content_hash": "quota-skipped-page",
        }
    )

    sync_result = _execute(client, payload, idempotency_key="per-run-document-quota")
    RuntimeService(
        database_url,
        settings=settings,
        providers={},
        runtime_queue=runtime_queue,
    ).process_next_queued_run(timeout_seconds=0)
    worker_result = RuntimeService(
        database_url,
        settings=settings,
        providers={},
    ).get_run_result(sync_result["json"]["data"]["run_id"], site_id="site_alpha")

    result = worker_result["result"]
    assert result["sync"]["accepted_documents"] == 1
    assert result["sync"]["indexed_documents"] == 1
    assert result["sync"]["skipped_documents"] == 1
    assert result["sync"]["skipped_due_to_quota"] == 1
    assert result["quota"]["status"] == "limited"
    assert result["quota"]["max_sync_documents_per_run"] == 1
    assert result["progress"]["stage"] == "limited"
    with get_session(database_url) as session:
        assert {chunk.post_id for chunk in session.query(SiteKnowledgeChunk).all()} == {123}


def test_status_reports_site_knowledge_quota_limits(tmp_path: Path) -> None:
    database_url, settings, runtime_queue, client = _build_client(
        tmp_path,
        settings_overrides={
            "site_knowledge_max_indexed_documents_per_site": 1,
            "site_knowledge_max_indexed_chunks_per_site": 4,
            "site_knowledge_quota_warning_ratio": 0.5,
        },
    )
    _execute(client, _sync_payload(), idempotency_key="status-quota-sync")
    RuntimeService(
        database_url,
        settings=settings,
        providers={},
        runtime_queue=runtime_queue,
    ).process_next_queued_run(timeout_seconds=0)

    status_result = _execute(
        client,
        {
            "ability_name": "npcink-cloud/site-knowledge-status",
            "contract_version": "site_knowledge_status.v1",
            "execution_pattern": "inline",
            "data_classification": "public_site_content",
            "storage_mode": "result_only",
            "input": {
                "contract_version": "site_knowledge_status.v1",
                "include_coverage": True,
                "write_posture": "suggestion_only",
            },
        },
        idempotency_key="status-quota-limits",
    )

    quota = status_result["json"]["data"]["result"]["coverage"]["quota"]
    assert quota["status"] == "limited"
    assert quota["indexed_documents"] == 1
    assert quota["max_indexed_documents_per_site"] == 1
    assert quota["max_indexed_chunks_per_site"] == 4
    assert quota["max_sync_documents_per_run"] == 500
    assert quota["document_utilization"] == 1.0


def test_site_knowledge_quota_settings_validate_positive_values(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            project_name="Npcink AI Cloud Site Knowledge Test",
            environment="test",
            database_url=_sqlite_url(tmp_path),
            redis_url="redis://localhost:6379/0",
            admin_session_secret=TEST_ADMIN_SESSION_SECRET,
            portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
            site_knowledge_max_sync_documents_per_run=0,
        )


def test_targeted_refresh_prunes_missing_public_document(tmp_path: Path) -> None:
    database_url, settings, runtime_queue, client = _build_client(tmp_path)

    initial_result = _execute(client, _sync_payload(), idempotency_key="targeted-prune-initial")
    RuntimeService(
        database_url,
        settings=settings,
        providers={},
        runtime_queue=runtime_queue,
    ).process_next_queued_run(timeout_seconds=0)
    assert initial_result["status_code"] == 200
    with get_session(database_url) as session:
        assert {chunk.post_id for chunk in session.query(SiteKnowledgeChunk).all()} == {123}

    refresh_payload = _sync_payload()
    input_payload = refresh_payload["input"]
    assert isinstance(input_payload, dict)
    input_payload["post_ids"] = [123]
    input_payload["documents"] = []

    refresh_result = _execute(
        client,
        refresh_payload,
        idempotency_key="targeted-prune-refresh",
    )
    RuntimeService(
        database_url,
        settings=settings,
        providers={},
        runtime_queue=runtime_queue,
    ).process_next_queued_run(timeout_seconds=0)
    worker_result = RuntimeService(
        database_url,
        settings=settings,
        providers={},
    ).get_run_result(refresh_result["json"]["data"]["run_id"], site_id="site_alpha")

    assert worker_result["result"]["sync"]["deleted_entries"] > 0
    assert worker_result["result"]["sync"]["indexed_documents"] == 0
    with get_session(database_url) as session:
        assert list(session.query(SiteKnowledgeChunk).all()) == []


def test_comments_are_opt_in_and_source_filtered(tmp_path: Path) -> None:
    database_url, settings, runtime_queue, client = _build_client(tmp_path)
    payload = _sync_payload()
    input_payload = payload["input"]
    assert isinstance(input_payload, dict)
    input_payload["comments"] = [
        {
            "comment_id": 987,
            "post_id": 123,
            "comment_status": "approved",
            "created_gmt": "2026-06-03 03:00:00",
            "url": "https://example.test/cloud-vector-launch#comment-987",
            "content_excerpt": "Reader asks whether BGE-M3 improves semantic search.",
            "content_hash": "comment-hash-987",
        }
    ]

    _execute(client, payload, idempotency_key="comments-disabled-sync")
    RuntimeService(
        database_url,
        settings=settings,
        providers={},
        runtime_queue=runtime_queue,
    ).process_next_queued_run(timeout_seconds=0)
    with get_session(database_url) as session:
        chunks = list(session.query(SiteKnowledgeChunk).all())
    assert {chunk.source_type for chunk in chunks} == {"post"}

    enabled_path = tmp_path / "comments-enabled"
    enabled_path.mkdir()
    database_url, settings, runtime_queue, client = _build_client(
        enabled_path,
        settings_overrides={"site_knowledge_comments_enabled": True},
    )
    _execute(client, payload, idempotency_key="comments-enabled-sync")
    RuntimeService(
        database_url,
        settings=settings,
        providers={},
        runtime_queue=runtime_queue,
    ).process_next_queued_run(timeout_seconds=0)

    comment_search = _execute(
        client,
        _search_payload(
            "BGE-M3 semantic search question",
            intent="site_search",
            source_types=["comment"],
        ),
        idempotency_key="comments-search",
    )
    data = comment_search["json"]["data"]["result"]
    assert data["results"][0]["source_type"] == "comment"
    assert data["results"][0]["source_id"] == 987
    assert data["results"][0]["parent_post_id"] == 123


def test_zilliz_backend_requires_cloud_managed_credentials(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            project_name="Npcink AI Cloud Site Knowledge Test",
            environment="test",
            database_url=_sqlite_url(tmp_path),
            redis_url="redis://localhost:6379/0",
            site_knowledge_vector_backend="zilliz_cloud",
            site_knowledge_zilliz_uri="",
            site_knowledge_zilliz_token="",
            site_knowledge_zilliz_collection="",
        )

    settings = Settings(
        _env_file=None,
        project_name="Npcink AI Cloud Site Knowledge Test",
        environment="test",
        database_url=_sqlite_url(tmp_path),
        redis_url="redis://localhost:6379/0",
        site_knowledge_vector_backend="zilliz_cloud",
        site_knowledge_zilliz_uri="https://example.zillizcloud.com",
        site_knowledge_zilliz_token="unit-test-redacted",
        site_knowledge_zilliz_collection="npcink_site_knowledge_chunks",
    )

    assert settings.site_knowledge_vector_backend == "zilliz_cloud"
    assert settings.site_knowledge_embedding_model == "BAAI/bge-m3"
    assert settings.site_knowledge_embedding_dimensions == 1024
    assert settings.site_knowledge_vector_metric_type == "COSINE"


def test_site_knowledge_tei_embedding_requires_configured_model(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            project_name="Npcink AI Cloud Site Knowledge Test",
            environment="test",
            database_url=_sqlite_url(tmp_path),
            redis_url="redis://localhost:6379/0",
            site_knowledge_embedding_provider="tei",
            site_knowledge_embedding_model="BAAI/bge-m3",
            tei_provider_enabled=True,
            tei_base_url="http://tei.local",
            tei_model_ids="jinaai/jina-embeddings-v3",
        )


def test_site_knowledge_siliconflow_embedding_requires_cloud_managed_key(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            project_name="Npcink AI Cloud Site Knowledge Test",
            environment="test",
            database_url=_sqlite_url(tmp_path),
            redis_url="redis://localhost:6379/0",
            site_knowledge_embedding_provider="siliconflow",
            site_knowledge_embedding_model="BAAI/bge-m3",
            siliconflow_provider_enabled=True,
        )


def test_sync_uses_cloud_managed_tei_embedding_provider(tmp_path: Path) -> None:
    provider = _FakeEmbeddingProvider()
    database_url, settings, runtime_queue, client = _build_client(
        tmp_path,
        settings_overrides={
            "site_knowledge_embedding_provider": "tei",
            "site_knowledge_embedding_model": "BAAI/bge-m3",
            "site_knowledge_embedding_dimensions": 1024,
            "tei_provider_enabled": True,
            "tei_base_url": "http://tei.local",
            "tei_model_ids": "BAAI/bge-m3",
        },
        providers={"tei": provider},
    )
    sync_result = _execute(client, _sync_payload(), idempotency_key="tei-sync")

    RuntimeService(
        database_url,
        settings=settings,
        providers={"tei": provider},
        runtime_queue=runtime_queue,
    ).process_next_queued_run(timeout_seconds=0)

    assert sync_result["status_code"] == 200
    run_id = sync_result["json"]["data"]["run_id"]
    assert provider.requests
    assert provider.requests[0].execution_kind == "embedding"
    assert provider.requests[0].model_id == "tei/BAAI/bge-m3"
    assert provider.requests[0].input_payload["text"]
    with get_session(database_url) as session:
        chunk = session.query(SiteKnowledgeChunk).one()
        provider_calls = list(
            session.scalars(select(ProviderCallRecord).where(ProviderCallRecord.run_id == run_id))
        )
        meter_events = list(
            session.scalars(
                select(UsageMeterEvent)
                .where(UsageMeterEvent.run_id == run_id)
                .order_by(UsageMeterEvent.id.asc())
            )
        )
    assert chunk.embedding_model == "BAAI/bge-m3"
    assert chunk.embedding_json == [0.25] * 1024
    assert provider_calls
    assert provider_calls[0].provider_id == "tei"
    assert provider_calls[0].model_id == "tei/BAAI/bge-m3"
    assert provider_calls[0].tokens_in == 1
    assert [event.meter_key for event in meter_events] == [
        "runs",
        "provider_calls",
        "tokens_in",
        "tokens_total",
    ]
    assert all(event.ability_family == "knowledge" for event in meter_events)


def test_sync_uses_cloud_managed_siliconflow_embedding_provider(tmp_path: Path) -> None:
    provider = _FakeEmbeddingProvider(provider_id="siliconflow")
    database_url, settings, runtime_queue, client = _build_client(
        tmp_path,
        settings_overrides={
            "site_knowledge_embedding_provider": "siliconflow",
            "site_knowledge_embedding_model": "BAAI/bge-m3",
            "site_knowledge_embedding_dimensions": 1024,
            "siliconflow_provider_enabled": True,
            "siliconflow_api_key": "placeholder-siliconflow-key",
        },
        providers={"siliconflow": provider},
    )
    sync_result = _execute(client, _sync_payload(), idempotency_key="siliconflow-sync")

    RuntimeService(
        database_url,
        settings=settings,
        providers={"siliconflow": provider},
        runtime_queue=runtime_queue,
    ).process_next_queued_run(timeout_seconds=0)

    assert sync_result["status_code"] == 200
    assert provider.requests
    assert provider.requests[0].execution_kind == "embedding"
    assert provider.requests[0].model_id == "BAAI/bge-m3"
    assert provider.requests[0].input_payload["text"]
    with get_session(database_url) as session:
        chunk = session.query(SiteKnowledgeChunk).one()
    assert chunk.embedding_model == "BAAI/bge-m3"
    assert chunk.embedding_json == [0.25] * 1024
