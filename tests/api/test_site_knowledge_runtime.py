from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

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
    SiteKnowledgeChunk,
    SiteKnowledgeIndexJobMetric,
    SiteKnowledgeIndexSnapshot,
    SiteKnowledgeSearchMetric,
)
from app.core.services import CloudServices
from app.domain.runtime.service import RuntimeService
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
    settings = Settings(
        _env_file=None,
        project_name="Magick AI Cloud Site Knowledge Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        **(settings_overrides or {}),
    )
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
        "ability_name": "magick-ai-cloud/site-knowledge-sync",
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
        "ability_name": "magick-ai-cloud/site-knowledge-search",
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
    assert search_data["evidence_gate"]["status"] == "passed"
    assert search_data["evidence_gate"]["allows_site_grounded_assertion"] is True
    assert search_data["results"][0]["post_id"] == 123
    assert search_data["results"][0]["suggested_use"] == "internal_link"
    assert search_data["results"][0]["insert_mode"] == "wordpress_local_only"
    assert search_data["results"][0]["anchor_text_candidates"]

    status_result = _execute(
        client,
        {
            "ability_name": "magick-ai-cloud/site-knowledge-status",
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
    assert status_data["coverage"]["indexed_posts"] == 1
    assert status_data["coverage"]["indexed_chunks"] >= 1
    assert status_data["coverage"]["post_type_coverage"] == {"post": 1.0}
    assert status_data["coverage"]["source_type_coverage"] == {"post": 1.0}
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
    assert writing_context["workflow_support"]["workflow"] == "generation_context_enrichment"
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
    assert faq["results"][0]["faq_candidate"]["source_signal"] == (
        "approved_comment_question"
    )
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
    assert duplicate["workflow_support"]["cloud_output"] == (
        "duplicate_or_conflict_candidates"
    )
    assert duplicate["results"][0]["suggested_use"] == "duplicate_or_conflict_candidate"
    assert duplicate["results"][0]["duplicate_check"]["review_mode"] == (
        "wordpress_local_only"
    )
    assert duplicate["direct_wordpress_write"] is False


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
            project_name="Magick AI Cloud Site Knowledge Test",
            environment="test",
            database_url=_sqlite_url(tmp_path),
            redis_url="redis://localhost:6379/0",
            site_knowledge_vector_backend="zilliz_cloud",
        )

    settings = Settings(
        _env_file=None,
        project_name="Magick AI Cloud Site Knowledge Test",
        environment="test",
        database_url=_sqlite_url(tmp_path),
        redis_url="redis://localhost:6379/0",
        site_knowledge_vector_backend="zilliz_cloud",
        site_knowledge_zilliz_uri="https://example.zillizcloud.com",
        site_knowledge_zilliz_token="placeholder-value",
        site_knowledge_zilliz_collection="magick_site_knowledge_chunks",
    )

    assert settings.site_knowledge_vector_backend == "zilliz_cloud"
    assert settings.site_knowledge_embedding_model == "BAAI/bge-m3"
    assert settings.site_knowledge_embedding_dimensions == 1024
    assert settings.site_knowledge_vector_metric_type == "COSINE"


def test_site_knowledge_tei_embedding_requires_configured_model(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            project_name="Magick AI Cloud Site Knowledge Test",
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
            project_name="Magick AI Cloud Site Knowledge Test",
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
    assert provider.requests
    assert provider.requests[0].execution_kind == "embedding"
    assert provider.requests[0].model_id == "tei/BAAI/bge-m3"
    assert provider.requests[0].input_payload["text"]
    with get_session(database_url) as session:
        chunk = session.query(SiteKnowledgeChunk).one()
    assert chunk.embedding_model == "BAAI/bge-m3"
    assert chunk.embedding_json == [0.25] * 1024


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
