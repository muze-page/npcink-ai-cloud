from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.queue.in_memory import InMemoryRuntimeQueue
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import get_session, init_schema
from app.core.models import (
    AccountEntitlementSnapshot,
    CreditLedgerEntry,
    ProviderCallRecord,
    RunRecord,
    UsageMeterEvent,
)
from app.core.services import CloudServices
from app.domain.web_search.contracts import (
    WebSearchContractViolation,
    validate_public_source_url,
)
from app.domain.web_search.service import (
    _TAVILY_KEY_TOKENS,
    _TAVILY_POOL_CURSOR,
    _TAVILY_POOL_QUARANTINED_UNTIL,
    _ZHIHU_HOT_LIST_CACHE,
    ApifyWebSearchProvider,
    BochaWebSearchProvider,
    TavilyWebSearchProvider,
    WebSearchExecutionResult,
    WebSearchProviderError,
    WebSearchProviderUsage,
    ZhihuWebSearchProvider,
    _tavily_key_token,
)
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_PORTAL_JWT_SECRET,
    build_auth_headers,
    merge_json_headers,
    seed_site_auth,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'web-search.sqlite3'}"


def _build_client(
    tmp_path: Path,
    *,
    settings_overrides: dict[str, object] | None = None,
) -> tuple[str, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read"],
    )
    settings_kwargs: dict[str, object] = {
        "project_name": "Npcink AI Cloud Web Search Test",
        "environment": "test",
        "database_url": database_url,
        "redis_url": "redis://localhost:6379/0",
        "admin_session_secret": TEST_ADMIN_SESSION_SECRET,
        "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
        "web_search_provider": "tavily",
        "web_search_tavily_api_key": "placeholder-tavily-key",
        "web_search_bocha_api_key": "",
        "web_search_jina_reader_api_key": "",
        "web_search_apify_api_token": "",
        "web_search_tavily_cost_per_query": 0.002,
    }
    settings_kwargs.update(settings_overrides or {})
    settings = Settings(_env_file=None, **settings_kwargs)
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


def _payload(
    input_overrides: dict[str, Any] | None = None,
    *,
    ability_name: str = "npcink-cloud/web-search",
) -> dict[str, Any]:
    input_payload: dict[str, Any] = {
        "contract_version": "web_search.v1",
        "query": "latest WordPress AI search trends",
        "intent": "news",
        "max_results": 3,
        "recency_days": 7,
        "language": "en",
        "region": "US",
        "evidence_policy": {
            "min_score": 0,
            "required_sources": 1,
            "no_hit_policy": "abstain",
        },
        "write_posture": "suggestion_only",
    }
    input_payload.update(input_overrides or {})
    return {
        "ability_name": ability_name,
        "contract_version": "web_search.v1",
        "execution_pattern": "inline",
        "storage_mode": "result_only",
        "timeout_seconds": 20,
        "retry_max": 0,
        "input": input_payload,
        "policy": {"allow_fallback": True},
    }


def _execute(
    client: TestClient,
    payload: dict[str, Any],
    *,
    idempotency_key: str = "web-search-idem",
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
            trace_id="websearch0000000000000000000000",
            body=body,
        )
    )
    return client.post("/v1/runtime/execute", content=body, headers=headers)


def test_cloud_managed_web_search_executes_and_records_provider_usage(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url, client = _build_client(tmp_path)

    def fake_search(
        self: TavilyWebSearchProvider,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> WebSearchExecutionResult:
        assert query == "latest WordPress AI search trends"
        assert options["intent"] == "news"
        return WebSearchExecutionResult(
            result_json={
                "artifact_type": "web_search_results",
                "composition_role": "external_web_evidence",
                "status": "ready",
                "provider": "tavily",
                "intent": options["intent"],
                "query_hash": "hash-only",
                "query_chars": len(query),
                "result_count": 1,
                "evidence_gate": {
                    "status": "passed",
                    "allows_web_grounded_assertion": True,
                    "source_count": 1,
                },
                "atomic_outputs": {
                    "source_evidence": {
                        "contract_version": "source_evidence.v1",
                        "result_count": 1,
                    },
                    "topic_candidates": {
                        "contract_version": "topic_candidate.v1",
                        "status": "empty",
                    },
                    "grounded_answer": {
                        "contract_version": "grounded_answer.v1",
                        "status": "not_generated",
                    },
                },
                "results": [
                    {
                        "title": "WordPress AI search roundup",
                        "url": "https://example.com/wp-ai-search",
                        "snippet": "A current external source.",
                        "score": 0.91,
                        "source": "tavily",
                        "suggested_use": "time_sensitive_context",
                        "write_posture": "suggestion_only",
                        "direct_wordpress_write": False,
                    }
                ],
                "sources": [
                    {
                        "title": "WordPress AI search roundup",
                        "url": "https://example.com/wp-ai-search",
                        "source": "tavily",
                    }
                ],
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            },
            usage=WebSearchProviderUsage(
                provider_id="tavily",
                model_id="web-search",
                instance_id="cloud-managed",
                region="unspecified",
                latency_ms=12,
                cost=0.002,
            ),
        )

    monkeypatch.setattr(TavilyWebSearchProvider, "search", fake_search)

    response = _execute(client, _payload())

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    assert data["provider_id"] == "web_search"
    assert data["provider_call_count"] == 1
    assert data["profile_id"] == "web-search.managed"
    assert data["execution_context"]["ability_family"] == "knowledge"
    assert data["execution_context"]["execution_pattern"] == "inline"
    result = data["result"]
    assert result["artifact_type"] == "web_search_results"
    assert result["provider"] == "tavily"
    assert result["provider_mode"] == "tavily"
    assert result["result_count"] == 1
    assert result["direct_wordpress_write"] is False
    assert result["workflow_metadata"]["workflow_id"] == "external_web_evidence_preflight"
    assert result["workflow_metadata"]["workflow_version"] == "web_search_evidence_workflow.v1"
    assert result["workflow_metadata"]["workflow_kind"] == "fixed_evidence_workflow"
    assert result["workflow_metadata"]["triggering_ability"] == "npcink-cloud/web-search"
    assert result["workflow_metadata"]["triggering_contract"] == "web_search.v1"
    assert result["workflow_metadata"]["intent"] == "news"
    assert result["workflow_metadata"]["cloud_output"] == "external_web_evidence"
    assert result["workflow_metadata"]["output_contract"] == "search_evidence_pack.v1"
    assert result["workflow_metadata"]["handoff_owner"] == "wordpress_local"
    assert result["workflow_metadata"]["write_posture"] == "suggestion_only"
    assert result["workflow_metadata"]["direct_wordpress_write"] is False
    assert "apply_evidence_gate" in result["workflow_metadata"]["steps"]
    assert "insufficient_evidence" in result["workflow_metadata"]["stop_conditions"]
    assert result["evidence_gate"]["allows_web_grounded_assertion"] is True
    assert result["atomic_outputs"]["source_evidence"]["contract_version"] == "source_evidence.v1"
    assert result["atomic_outputs"]["source_evidence"]["result_count"] == 1
    assert result["atomic_outputs"]["topic_candidates"]["contract_version"] == "topic_candidate.v1"
    assert result["atomic_outputs"]["topic_candidates"]["status"] == "empty"
    assert result["atomic_outputs"]["grounded_answer"]["contract_version"] == "grounded_answer.v1"
    assert result["atomic_outputs"]["grounded_answer"]["status"] == "not_generated"
    assert result["results"][0]["url"] == "https://example.com/wp-ai-search"
    assert "latest WordPress AI search trends" not in json.dumps(result)

    with get_session(database_url) as session:
        run = session.get(RunRecord, data["run_id"])
        assert run is not None
        assert run.input_json == {}
        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord).where(ProviderCallRecord.run_id == run.run_id)
            )
        )
        assert provider_calls[0].provider_id == "tavily"
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


def test_source_extraction_preview_reads_exact_url_without_search_provider(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={"web_search_provider": "disabled"},
    )
    captured: dict[str, Any] = {}

    class FakeReaderClient:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        def __enter__(self) -> FakeReaderClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, endpoint: str, *, headers: dict[str, str]) -> httpx.Response:
            captured["endpoint"] = endpoint
            captured["headers"] = headers
            content = (
                "Title: Reliable WordPress source\n"
                "URL Source: https://example.com/guides/source\n"
                "Published Time: 2026-07-12\n"
                "Markdown Content:\n"
                "This is the beginning of the extracted source.\n\n"
                "It includes enough bounded content for a review preview.\n\n"
                "This is the end of the extracted source."
            )
            return httpx.Response(
                200,
                text=content,
                request=httpx.Request("GET", endpoint),
            )

    monkeypatch.setattr("app.domain.web_search.service.httpx.Client", FakeReaderClient)
    source_url = "https://example.com/guides/source"
    response = _execute(
        client,
        _payload(
            {
                "query": source_url,
                "source_url": source_url,
                "intent": "source_extraction_preview",
                "max_results": 1,
                "recency_days": 0,
            }
        ),
        idempotency_key="source-extraction-preview",
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    assert data["provider_call_count"] == 1
    result = data["result"]
    assert result["artifact_type"] == "source_extraction_preview"
    assert result["contract_version"] == "source_extraction_preview.v1"
    assert result["output_contract"] == "source_extraction_preview.v1"
    assert result["status"] == "ready"
    assert result["requested_url"] == source_url
    assert result["resolved_url"] == source_url
    assert result["url_match"] == "matched"
    assert result["title"] == "Reliable WordPress source"
    assert result["coverage"]["level"] == "partial"
    assert result["coverage"]["reader_bounded"] is True
    assert result["coverage"]["complete_capture_claimed"] is False
    assert result["content_trust"] == "untrusted_external_source"
    assert result["prompt_injection_review_required"] is True
    assert result["preview_start"].startswith("This is the beginning")
    assert result["preview_end"].endswith("end of the extracted source.")
    assert result["content_hash"]
    assert result["results"][0]["reader_provider"] == "jina_reader"
    assert result["workflow_metadata"]["output_contract"] == (
        "source_extraction_preview.v1"
    )
    assert result["write_posture"] == "suggestion_only"
    assert result["direct_wordpress_write"] is False
    assert captured["endpoint"] == f"https://r.jina.ai/{source_url}"
    assert captured["headers"]["X-Return-Format"] == "markdown"

    with get_session(database_url) as session:
        run = session.get(RunRecord, data["run_id"])
        assert run is not None
        assert run.input_json == {}
        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord).where(ProviderCallRecord.run_id == run.run_id)
            )
        )
        assert provider_calls[0].provider_id == "jina_reader"


def test_source_extraction_preview_blocks_reader_url_mismatch(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _, client = _build_client(
        tmp_path,
        settings_overrides={"web_search_provider": "disabled"},
    )

    class FakeReaderClient:
        def __init__(self, *, timeout: float) -> None:
            pass

        def __enter__(self) -> FakeReaderClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, endpoint: str, *, headers: dict[str, str]) -> httpx.Response:
            return httpx.Response(
                200,
                text=(
                    "Title: Wrong article\n"
                    "URL Source: https://example.com/guides/different\n"
                    "Markdown Content:\nThis content must not be exposed."
                ),
                request=httpx.Request("GET", endpoint),
            )

    monkeypatch.setattr("app.domain.web_search.service.httpx.Client", FakeReaderClient)
    source_url = "https://example.com/guides/source"
    response = _execute(
        client,
        _payload(
            {
                "query": source_url,
                "source_url": source_url,
                "intent": "source_extraction_preview",
                "max_results": 1,
            }
        ),
        idempotency_key="source-extraction-mismatch",
    )

    assert response.status_code == 200
    result = response.json()["data"]["result"]
    assert result["status"] == "blocked"
    assert result["url_match"] == "mismatched"
    assert result["result_count"] == 0
    assert result["results"] == []
    assert result["preview_start"] == ""
    assert result["content_hash"] == ""
    assert result["title"] == ""
    assert "This content must not be exposed" not in json.dumps(result)


def test_source_extraction_preview_blocks_missing_reader_url_evidence(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _, client = _build_client(
        tmp_path,
        settings_overrides={"web_search_provider": "disabled"},
    )

    class FakeReaderClient:
        def __init__(self, *, timeout: float) -> None:
            pass

        def __enter__(self) -> FakeReaderClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, endpoint: str, *, headers: dict[str, str]) -> httpx.Response:
            return httpx.Response(
                200,
                text=(
                    "Title: Unverified article\n"
                    "Markdown Content:\nUnverified reader content."
                ),
                request=httpx.Request("GET", endpoint),
            )

    monkeypatch.setattr("app.domain.web_search.service.httpx.Client", FakeReaderClient)
    source_url = "https://example.com/guides/source"
    response = _execute(
        client,
        _payload(
            {
                "query": source_url,
                "source_url": source_url,
                "intent": "source_extraction_preview",
                "max_results": 1,
            }
        ),
        idempotency_key="source-extraction-missing-url-evidence",
    )

    assert response.status_code == 200
    result = response.json()["data"]["result"]
    assert result["status"] == "blocked"
    assert result["resolved_url"] == ""
    assert result["results"] == []
    assert result["title"] == ""
    assert "Unverified reader content" not in json.dumps(result)


@pytest.mark.parametrize(
    "source_url",
    [
        "http://127.0.0.1/private",
        "http://127.1/private",
        "http://169.254.169.254/latest/meta-data",
        "http://localhost/article",
        "https://user:password@example.com/article",
        "file:///etc/passwd",
    ],
)
def test_source_extraction_preview_rejects_non_public_urls(
    tmp_path: Path,
    source_url: str,
) -> None:
    _, client = _build_client(tmp_path)
    response = _execute(
        client,
        _payload(
            {
                "query": source_url,
                "source_url": source_url,
                "intent": "source_extraction_preview",
                "max_results": 1,
            }
        ),
        idempotency_key=f"source-extraction-block-{abs(hash(source_url))}",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] in {
        "runtime.pii_classification_required",
        "web_search.source_url_credentials_forbidden",
        "web_search.source_url_invalid",
        "web_search.source_url_not_public",
    }


def test_source_extraction_contract_rejects_credential_bearing_url() -> None:
    with pytest.raises(WebSearchContractViolation) as error:
        validate_public_source_url("https://user:password@example.com/article")

    assert error.value.error_code == "web_search.source_url_credentials_forbidden"


def test_source_extraction_contract_rejects_query_url_mismatch(tmp_path: Path) -> None:
    _, client = _build_client(tmp_path)
    response = _execute(
        client,
        _payload(
            {
                "query": "https://example.com/requested",
                "source_url": "https://example.com/different",
                "intent": "source_extraction_preview",
                "max_results": 1,
            }
        ),
        idempotency_key="source-extraction-query-mismatch",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "web_search.source_query_mismatch"


def test_zhihu_direct_answer_records_lane_credit_component(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "web_search_provider": "zhihu",
            "web_search_zhihu_access_secret": "test-zhihu-secret",
        },
    )

    def fake_search(
        self: ZhihuWebSearchProvider,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> WebSearchExecutionResult:
        assert options["source_type"] == "zhida_deep"
        return WebSearchExecutionResult(
            result_json={
                "artifact_type": "web_search_results",
                "composition_role": "grounded_answer_preview",
                "status": "ready",
                "provider": "zhihu",
                "provider_mode": "zhihu",
                "intent": "zhida_deep",
                "query_hash": "hash-only",
                "query_chars": len(query),
                "result_count": 1,
                "evidence_gate": {
                    "status": "passed",
                    "allows_web_grounded_assertion": True,
                    "source_count": 1,
                },
                "atomic_outputs": {
                    "source_evidence": {"contract_version": "source_evidence.v1"},
                    "topic_candidates": {"contract_version": "topic_candidate.v1"},
                    "grounded_answer": {
                        "contract_version": "grounded_answer.v1",
                        "status": "ready",
                    },
                },
                "results": [
                    {
                        "title": "Zhihu answer source",
                        "url": "https://www.zhihu.com/question/1/answer/2",
                        "snippet": "A reviewed Zhihu direct answer source.",
                        "source": "zhihu",
                        "write_posture": "suggestion_only",
                        "direct_wordpress_write": False,
                    }
                ],
                "sources": [
                    {
                        "title": "Zhihu answer source",
                        "url": "https://www.zhihu.com/question/1/answer/2",
                        "source": "zhihu",
                    }
                ],
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            },
            usage=WebSearchProviderUsage(
                provider_id="zhihu",
                model_id="zhihu-openapi-content",
                instance_id="cloud-managed",
                region="unspecified",
                latency_ms=16,
                cost=0.0,
            ),
        )

    monkeypatch.setattr(ZhihuWebSearchProvider, "search", fake_search)

    response = _execute(
        client,
        _payload(
            {
                "provider": "zhihu",
                "intent": "zhida_deep",
                "source_type": "zhida_deep",
                "query": "AI 写作如何做热点选题？",
                "max_results": 3,
            }
        ),
        idempotency_key="zhihu-direct-answer-credit",
    )

    assert response.status_code == 200
    data = response.json()["data"]
    result = data["result"]
    assert result["usage_summary"]["quota_owner"] == "cloud_runtime_entitlement"
    assert result["usage_summary"]["source_type"] == "zhihu_direct_answer_deep"
    assert result["usage_summary"]["provider_call_credits"] == 5.0
    assert result["usage_summary"]["estimated_total_ai_credits"] == 6.0

    with get_session(database_url) as session:
        run = session.get(RunRecord, data["run_id"])
        assert run is not None
        provider_event = session.scalar(
            select(UsageMeterEvent).where(
                UsageMeterEvent.run_id == run.run_id,
                UsageMeterEvent.meter_key == "provider_calls",
            )
        )
        assert provider_event is not None
        assert provider_event.payload_json["provider"] == "zhihu"
        assert provider_event.payload_json["source_type"] == "zhida_deep"
        assert provider_event.payload_json["intent"] == "zhida_deep"

        credit_entry = session.scalar(
            select(CreditLedgerEntry).where(
                CreditLedgerEntry.run_id == run.run_id,
                CreditLedgerEntry.source_type == "zhihu_direct_answer_deep",
            )
        )
        assert credit_entry is not None
        assert credit_entry.credit_delta == -5.0
        assert credit_entry.metadata_json["credit_component"] == "zhihu_direct_answer_deep"
        assert credit_entry.metadata_json["source_type"] == "zhida_deep"


def test_zhihu_direct_answer_rejects_when_ai_credit_budget_would_be_exceeded(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "web_search_provider": "zhihu",
            "web_search_zhihu_access_secret": "test-zhihu-secret",
        },
    )
    with get_session(database_url) as session:
        snapshot = session.scalar(select(AccountEntitlementSnapshot))
        assert snapshot is not None
        snapshot.budgets_json = {"max_ai_credits_per_period": 5}
        session.commit()

    def fake_search(*args: Any, **kwargs: Any) -> WebSearchExecutionResult:
        raise AssertionError("provider must not be called after Cloud quota rejection")

    monkeypatch.setattr(ZhihuWebSearchProvider, "search", fake_search)

    response = _execute(
        client,
        _payload(
            {
                "provider": "zhihu",
                "intent": "zhida_deep",
                "source_type": "zhida_deep",
                "query": "AI 写作如何做热点选题？",
            }
        ),
        idempotency_key="zhihu-direct-answer-credit-limit",
    )

    assert response.status_code == 429
    body = response.json()
    assert body["error_code"] == "commercial.quota_exceeded"
    assert "ai_credits" in body["message"]


def test_tavily_key_pool_rotates_without_exposing_keys(monkeypatch: Any) -> None:
    _TAVILY_POOL_CURSOR.clear()
    _TAVILY_POOL_QUARANTINED_UNTIL.clear()
    seen_keys: list[str] = []

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 15.0

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, endpoint: str, *, json: dict[str, Any]) -> httpx.Response:
            seen_keys.append(str(json["api_key"]))
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Rotated Tavily source",
                            "url": "https://example.com/rotated-tavily-source",
                            "content": "A source returned through a Tavily key pool.",
                        }
                    ]
                },
                request=httpx.Request("POST", endpoint),
            )

    monkeypatch.setattr("app.domain.web_search.service.httpx.Client", FakeClient)
    provider = TavilyWebSearchProvider(
        Settings(
            _env_file=None,
            environment="test",
            web_search_provider="tavily",
            web_search_tavily_api_key="",
            web_search_tavily_api_keys="tvly-pool-a\ntvly-pool-b",
            web_search_tavily_api_key_labels="account-a\naccount-b",
        )
    )

    first = provider.search(
        query="latest WordPress AI search trends",
        options={"intent": "news", "max_results": 3},
        site_id="site_alpha",
        run_id="run_tavily_pool_first",
    )
    second = provider.search(
        query="latest WordPress AI search trends",
        options={"intent": "news", "max_results": 3},
        site_id="site_alpha",
        run_id="run_tavily_pool_second",
    )

    assert seen_keys == ["tvly-pool-a", "tvly-pool-b"]
    assert first.result_json["provider_key_pool"]["key_count"] == 2
    assert first.result_json["provider_key_pool"]["selected_key_index"] == 1
    assert first.result_json["provider_key_pool"]["selected_key_label"] == "account-a"
    assert second.result_json["provider_key_pool"]["selected_key_index"] == 2
    assert second.result_json["provider_key_pool"]["selected_key_label"] == "account-b"
    serialized_results = json.dumps([first.result_json, second.result_json])
    assert "tvly-pool-a" not in serialized_results
    assert "tvly-pool-b" not in serialized_results


def test_tavily_key_tokens_are_opaque_stable_and_process_local() -> None:
    first_key = "tvly-process-local-fingerprint-a"
    second_key = "tvly-process-local-fingerprint-b"
    _TAVILY_KEY_TOKENS.clear()

    first_token = _tavily_key_token(first_key)

    assert first_token == _tavily_key_token(first_key)
    assert first_token != _tavily_key_token(second_key)
    assert first_key not in first_token
    assert second_key not in first_token

    _TAVILY_KEY_TOKENS.clear()
    assert first_token != _tavily_key_token(first_key)


def test_tavily_rejects_oversized_provider_response(monkeypatch: Any) -> None:
    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 15.0

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, endpoint: str, *, json: dict[str, Any]) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-length": "2000001"},
                content=b"{}",
                request=httpx.Request("POST", endpoint),
            )

    monkeypatch.setattr("app.domain.web_search.service.httpx.Client", FakeClient)
    provider = TavilyWebSearchProvider(
        Settings(
            _env_file=None,
            environment="test",
            web_search_provider="tavily",
            web_search_tavily_api_key="tvly-test-key",
        )
    )

    with pytest.raises(WebSearchProviderError) as error:
        provider.search(
            query="latest WordPress AI search trends",
            options={"intent": "news", "max_results": 3},
            site_id="site_alpha",
            run_id="run_tavily_oversized_response",
        )

    assert error.value.error_code == "provider.response_too_large"


def test_tavily_prefers_authoritative_sources_for_review_intents(monkeypatch: Any) -> None:
    captured_queries: list[str] = []

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 15.0

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, endpoint: str, *, json: dict[str, Any]) -> httpx.Response:
            captured_queries.append(str(json["query"]))
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Official source",
                            "url": "https://example.com/official-source",
                            "content": "An official source returned through Tavily.",
                        }
                    ]
                },
                request=httpx.Request("POST", endpoint),
            )

    monkeypatch.setattr("app.domain.web_search.service.httpx.Client", FakeClient)
    provider = TavilyWebSearchProvider(
        Settings(
            _env_file=None,
            environment="test",
            web_search_provider="tavily",
            web_search_tavily_api_key="tvly-test-key",
        )
    )

    fact_check = provider.search(
        query="WordPress 6.9 AI built in",
        options={"intent": "fact_check", "max_results": 3},
        site_id="site_alpha",
        run_id="run_tavily_fact_check",
    )
    pricing = provider.search(
        query="Tavily API costs",
        options={"intent": "pricing_snapshot", "max_results": 3},
        site_id="site_alpha",
        run_id="run_tavily_pricing",
    )
    provider.search(
        query="latest WordPress AI search trends",
        options={"intent": "news", "max_results": 3},
        site_id="site_alpha",
        run_id="run_tavily_news",
    )

    assert captured_queries[0] == (
        "WordPress 6.9 AI built in official primary source documentation source of record"
    )
    assert captured_queries[1] == "Tavily API costs official pricing page pricing documentation"
    assert captured_queries[2] == "latest WordPress AI search trends"
    assert fact_check.result_json["source_priority"] == "official_or_primary_sources"
    assert fact_check.result_json["evidence_pack"]["source_priority"] == (
        "official_or_primary_sources"
    )
    assert "Prefer official" in fact_check.result_json["evidence_pack"]["source_requirements"][0]
    assert pricing.result_json["source_priority"] == "official_pricing_or_docs"
    assert pricing.result_json["evidence_pack"]["source_priority"] == "official_pricing_or_docs"


def test_tavily_key_pool_fails_over_after_rate_limit(monkeypatch: Any) -> None:
    _TAVILY_POOL_CURSOR.clear()
    _TAVILY_POOL_QUARANTINED_UNTIL.clear()
    seen_keys: list[str] = []

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 15.0

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, endpoint: str, *, json: dict[str, Any]) -> httpx.Response:
            seen_keys.append(str(json["api_key"]))
            if json["api_key"] == "tvly-limited":
                return httpx.Response(
                    429,
                    json={"message": "rate limited"},
                    request=httpx.Request("POST", endpoint),
                )
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Failover Tavily source",
                            "url": "https://example.com/failover-tavily-source",
                            "content": "A source returned after key failover.",
                        }
                    ]
                },
                request=httpx.Request("POST", endpoint),
            )

    monkeypatch.setattr("app.domain.web_search.service.httpx.Client", FakeClient)
    result = TavilyWebSearchProvider(
        Settings(
            _env_file=None,
            environment="test",
            web_search_provider="tavily",
            web_search_tavily_api_keys="tvly-limited,tvly-healthy",
            web_search_tavily_api_key_labels="limited-account,healthy-account",
        )
    ).search(
        query="latest WordPress AI search trends",
        options={"intent": "news", "max_results": 3},
        site_id="site_alpha",
        run_id="run_tavily_pool_failover",
    )

    assert seen_keys == ["tvly-limited", "tvly-healthy"]
    key_pool = result.result_json["provider_key_pool"]
    assert key_pool["key_count"] == 2
    assert key_pool["selected_key_index"] == 2
    assert key_pool["selected_key_label"] == "healthy-account"
    assert key_pool["attempt_count"] == 2
    assert key_pool["failover_count"] == 1
    assert key_pool["errors"][0]["error_code"] == "provider.rate_limited"
    assert "tvly-limited" not in json.dumps(result.result_json)
    assert result.result_json["results"][0]["url"] == "https://example.com/failover-tavily-source"


def test_tavily_key_pool_preserves_empty_label_alignment(monkeypatch: Any) -> None:
    _TAVILY_POOL_CURSOR.clear()
    _TAVILY_POOL_QUARANTINED_UNTIL.clear()
    seen_keys: list[str] = []

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 15.0

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, endpoint: str, *, json: dict[str, Any]) -> httpx.Response:
            seen_keys.append(str(json["api_key"]))
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Aligned Tavily source",
                            "url": "https://example.com/aligned-tavily-source",
                            "content": "A source returned through aligned labels.",
                        }
                    ]
                },
                request=httpx.Request("POST", endpoint),
            )

    monkeypatch.setattr("app.domain.web_search.service.httpx.Client", FakeClient)
    provider = TavilyWebSearchProvider(
        Settings(
            _env_file=None,
            environment="test",
            web_search_provider="tavily",
            web_search_tavily_api_keys="tvly-unlabeled,tvly-labeled",
            web_search_tavily_api_key_labels=",npc@example.test",
        )
    )

    first = provider.search(
        query="latest WordPress AI search trends",
        options={"intent": "news", "max_results": 3},
        site_id="site_alpha",
        run_id="run_tavily_label_alignment_first",
    )
    second = provider.search(
        query="latest WordPress AI search trends",
        options={"intent": "news", "max_results": 3},
        site_id="site_alpha",
        run_id="run_tavily_label_alignment_second",
    )

    assert seen_keys == ["tvly-unlabeled", "tvly-labeled"]
    assert "selected_key_label" not in first.result_json["provider_key_pool"]
    assert second.result_json["provider_key_pool"]["selected_key_label"] == "npc@example.test"


def test_cloud_managed_web_search_accepts_npcink_ability_alias(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _, client = _build_client(tmp_path)

    def fake_search(
        self: TavilyWebSearchProvider,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> WebSearchExecutionResult:
        return WebSearchExecutionResult(
            result_json={
                "artifact_type": "web_search_results",
                "composition_role": "external_web_evidence",
                "status": "ready",
                "provider": "tavily",
                "intent": options["intent"],
                "query_hash": "hash-only",
                "query_chars": len(query),
                "evidence_gate": {
                    "status": "passed",
                    "allows_web_grounded_assertion": True,
                    "source_count": 1,
                },
                "results": [
                    {
                        "title": "Current source",
                        "url": "https://example.com/source",
                        "snippet": "A source returned by Cloud web search.",
                        "score": 1.0,
                        "source": "tavily",
                        "write_posture": "suggestion_only",
                        "direct_wordpress_write": False,
                    }
                ],
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            },
            usage=WebSearchProviderUsage(
                provider_id="tavily",
                model_id="web-search",
                instance_id="cloud-managed",
                region="unspecified",
                latency_ms=11,
                cost=0.002,
            ),
        )

    monkeypatch.setattr(TavilyWebSearchProvider, "search", fake_search)

    response = _execute(
        client,
        _payload(
            {"intent": "article_background"},
            ability_name="npcink-cloud/web-search",
        ),
        idempotency_key="web-search-npcink-alias",
    )

    assert response.status_code == 200
    result = response.json()["data"]["result"]
    assert result["workflow_metadata"]["triggering_ability"] == "npcink-cloud/web-search"
    assert result["workflow_metadata"]["intent"] == "article_background"


def test_cloud_managed_web_search_uses_bocha_provider(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "web_search_provider": "bocha",
            "web_search_bocha_api_key": "placeholder-bocha-key",
        },
    )

    def fake_search(
        self: BochaWebSearchProvider,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> WebSearchExecutionResult:
        return WebSearchExecutionResult(
            result_json={
                "artifact_type": "web_search_results",
                "composition_role": "external_web_evidence",
                "status": "ready",
                "provider": "bocha",
                "intent": options["intent"],
                "query_hash": "hash-only",
                "query_chars": len(query),
                "evidence_gate": {
                    "status": "passed",
                    "allows_web_grounded_assertion": True,
                    "source_count": 1,
                },
                "results": [
                    {
                        "title": "Bocha source",
                        "url": "https://example.cn/source",
                        "snippet": "A source returned by Bocha.",
                        "score": 0.9,
                        "source": "bocha",
                        "write_posture": "suggestion_only",
                        "direct_wordpress_write": False,
                    }
                ],
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            },
            usage=WebSearchProviderUsage(
                provider_id="bocha",
                model_id="web-search",
                instance_id="cloud-managed",
                region="unspecified",
                latency_ms=9,
                cost=0.0,
            ),
        )

    monkeypatch.setattr(BochaWebSearchProvider, "search", fake_search)

    response = _execute(client, _payload(), idempotency_key="web-search-bocha")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["result"]["provider"] == "bocha"
    with get_session(database_url) as session:
        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord).where(ProviderCallRecord.run_id == data["run_id"])
            )
        )
        assert provider_calls[0].provider_id == "bocha"


def test_cloud_managed_web_search_uses_apify_provider(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "web_search_provider": "apify",
            "web_search_apify_api_token": "placeholder-apify-token",
            "web_search_apify_actor_id": "apify/google-search-scraper",
        },
    )

    def fake_search(
        self: ApifyWebSearchProvider,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> WebSearchExecutionResult:
        return WebSearchExecutionResult(
            result_json={
                "artifact_type": "web_search_results",
                "composition_role": "external_web_evidence",
                "status": "ready",
                "provider": "apify",
                "intent": options["intent"],
                "query_hash": "hash-only",
                "query_chars": len(query),
                "evidence_gate": {
                    "status": "passed",
                    "allows_web_grounded_assertion": True,
                    "source_count": 1,
                },
                "results": [
                    {
                        "title": "Apify source",
                        "url": "https://example.com/apify-source",
                        "snippet": "A source returned by Apify.",
                        "score": 1.0,
                        "source": "apify",
                        "write_posture": "suggestion_only",
                        "direct_wordpress_write": False,
                    }
                ],
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            },
            usage=WebSearchProviderUsage(
                provider_id="apify",
                model_id="web-search",
                instance_id="cloud-managed",
                region="unspecified",
                latency_ms=14,
                cost=0.0,
            ),
        )

    monkeypatch.setattr(ApifyWebSearchProvider, "search", fake_search)

    response = _execute(client, _payload(), idempotency_key="web-search-apify")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["result"]["provider"] == "apify"
    with get_session(database_url) as session:
        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord).where(ProviderCallRecord.run_id == data["run_id"])
            )
        )
        assert provider_calls[0].provider_id == "apify"


def test_cloud_managed_web_search_uses_zhihu_provider(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "web_search_provider": "zhihu",
            "web_search_zhihu_access_secret": "placeholder-zhihu-secret",
        },
    )

    def fake_search(
        self: ZhihuWebSearchProvider,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> WebSearchExecutionResult:
        assert options["intent"] == "zhihu_research"
        assert options["source_type"] == "zhihu_research"
        return WebSearchExecutionResult(
            result_json={
                "artifact_type": "web_search_results",
                "composition_role": "external_web_evidence",
                "status": "ready",
                "provider": "zhihu",
                "intent": options["intent"],
                "query_hash": "hash-only",
                "query_chars": len(query),
                "output_contract": "search_evidence_pack.v1",
                "evidence_gate": {
                    "status": "passed",
                    "allows_web_grounded_assertion": True,
                    "source_count": 1,
                },
                "evidence_pack": {
                    "artifact_type": "search_evidence_pack",
                    "contract_version": "search_evidence_pack.v1",
                    "pack_type": "zhihu_writing_research",
                    "source_cards": [],
                    "write_posture": "suggestion_only",
                    "direct_wordpress_write": False,
                },
                "results": [
                    {
                        "title": "Zhihu source",
                        "url": "https://www.zhihu.com/question/123",
                        "snippet": "A source returned by Zhihu.",
                        "score": 0.98,
                        "source": "zhihu",
                        "content_type": "Question",
                        "vote_up_count": 32,
                        "comment_count": 8,
                        "write_posture": "suggestion_only",
                        "direct_wordpress_write": False,
                    }
                ],
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            },
            usage=WebSearchProviderUsage(
                provider_id="zhihu",
                model_id="zhihu-openapi-content",
                instance_id="cloud-managed",
                region="unspecified",
                latency_ms=16,
                cost=0.0,
            ),
        )

    monkeypatch.setattr(ZhihuWebSearchProvider, "search", fake_search)

    response = _execute(
        client,
        _payload(
            {
                "intent": "zhihu_research",
                "source_type": "zhihu_research",
                "include_hot_list": True,
            }
        ),
        idempotency_key="web-search-zhihu",
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["result"]["provider"] == "zhihu"
    assert data["result"]["intent"] == "zhihu_research"
    assert data["result"]["results"][0]["source"] == "zhihu"
    assert data["result"]["direct_wordpress_write"] is False
    with get_session(database_url) as session:
        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord).where(ProviderCallRecord.run_id == data["run_id"])
            )
        )
        assert provider_calls[0].provider_id == "zhihu"


def test_cloud_managed_web_search_requested_zhihu_overrides_default_provider(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "web_search_provider": "tavily",
            "web_search_tavily_api_key": "placeholder-tavily-key",
            "web_search_zhihu_access_secret": "placeholder-zhihu-secret",
        },
    )

    def fail_tavily_search(
        self: TavilyWebSearchProvider,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> WebSearchExecutionResult:
        raise AssertionError("explicit provider=zhihu must not call Tavily")

    def fake_zhihu_search(
        self: ZhihuWebSearchProvider,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> WebSearchExecutionResult:
        assert query == "AI writing research"
        assert options["provider"] == "zhihu"
        assert options["provider_mode"] == "zhihu"
        assert options["requested_provider"] == "zhihu"
        assert options["intent"] == "zhida_deep"
        assert options["source_type"] == "zhida_deep"
        return WebSearchExecutionResult(
            result_json={
                "artifact_type": "web_search_results",
                "composition_role": "grounded_answer_preview",
                "status": "ready",
                "provider": "zhihu",
                "provider_mode": options["provider_mode"],
                "requested_provider": options["requested_provider"],
                "intent": options["intent"],
                "query_hash": "hash-only",
                "query_chars": len(query),
                "result_count": 1,
                "source_priority": "zhihu_direct_answer_preview",
                "output_contract": "grounded_answer.v1",
                "evidence_gate": {
                    "status": "passed",
                    "allows_web_grounded_assertion": True,
                    "source_count": 1,
                },
                "atomic_outputs": {
                    "grounded_answer": {
                        "contract_version": "grounded_answer.v1",
                        "status": "ready",
                        "answer_text": "先明确读者问题，再收集证据。",
                        "direct_wordpress_write": False,
                    },
                    "source_evidence": {
                        "contract_version": "source_evidence.v1",
                        "status": "passed",
                        "result_count": 1,
                    },
                    "topic_candidates": {
                        "contract_version": "topic_candidate.v1",
                        "status": "empty",
                    },
                },
                "results": [],
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            },
            usage=WebSearchProviderUsage(
                provider_id="zhihu",
                model_id="zhihu-openapi-content",
                instance_id="cloud-managed",
                region="unspecified",
                latency_ms=15,
                cost=0.0,
            ),
        )

    monkeypatch.setattr(TavilyWebSearchProvider, "search", fail_tavily_search)
    monkeypatch.setattr(ZhihuWebSearchProvider, "search", fake_zhihu_search)

    response = _execute(
        client,
        _payload(
            {
                "query": "AI writing research",
                "intent": "zhida_deep",
                "provider": "zhihu",
                "source_type": "zhida_deep",
                "max_results": 5,
            }
        ),
        idempotency_key="web-search-requested-zhihu",
    )

    assert response.status_code == 200
    data = response.json()["data"]
    result = data["result"]
    assert result["provider"] == "zhihu"
    assert result["provider_mode"] == "zhihu"
    assert result["requested_provider"] == "zhihu"
    assert result["intent"] == "zhida_deep"
    assert result["output_contract"] == "grounded_answer.v1"
    assert result["atomic_outputs"]["grounded_answer"]["contract_version"] == "grounded_answer.v1"
    with get_session(database_url) as session:
        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord).where(ProviderCallRecord.run_id == data["run_id"])
            )
        )
        assert provider_calls[0].provider_id == "zhihu"


def test_cloud_managed_web_search_zhida_intent_implies_zhihu_direct_answer(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "web_search_provider": "tavily",
            "web_search_tavily_api_key": "placeholder-tavily-key",
            "web_search_zhihu_access_secret": "placeholder-zhihu-secret",
        },
    )

    def fail_tavily_search(
        self: TavilyWebSearchProvider,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> WebSearchExecutionResult:
        raise AssertionError("zhida intent must not fall back to Tavily")

    def fake_zhihu_search(
        self: ZhihuWebSearchProvider,
        *,
        query: str,
        options: dict[str, Any],
        site_id: str,
        run_id: str,
    ) -> WebSearchExecutionResult:
        assert options["provider"] == "zhihu"
        assert options["provider_mode"] == "zhihu"
        assert options["requested_provider"] == "zhihu"
        assert options["intent"] == "zhida_deep"
        assert options["source_type"] == "zhida_deep"
        return WebSearchExecutionResult(
            result_json={
                "artifact_type": "web_search_results",
                "composition_role": "grounded_answer_preview",
                "status": "ready",
                "provider": "zhihu",
                "provider_mode": options["provider_mode"],
                "requested_provider": options["requested_provider"],
                "intent": options["intent"],
                "query_hash": "hash-only",
                "query_chars": len(query),
                "result_count": 0,
                "source_priority": "zhihu_direct_answer_preview",
                "output_contract": "grounded_answer.v1",
                "evidence_gate": {
                    "status": "insufficient_evidence",
                    "allows_web_grounded_assertion": False,
                    "source_count": 0,
                },
                "atomic_outputs": {
                    "grounded_answer": {
                        "contract_version": "grounded_answer.v1",
                        "status": "ready",
                        "answer_text": "先明确问题。",
                        "direct_wordpress_write": False,
                    }
                },
                "results": [],
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            },
            usage=WebSearchProviderUsage(
                provider_id="zhihu",
                model_id="zhihu-openapi-content",
                instance_id="cloud-managed",
                region="unspecified",
                latency_ms=15,
                cost=0.0,
            ),
        )

    monkeypatch.setattr(TavilyWebSearchProvider, "search", fail_tavily_search)
    monkeypatch.setattr(ZhihuWebSearchProvider, "search", fake_zhihu_search)

    response = _execute(
        client,
        _payload(
            {
                "query": "AI writing research",
                "intent": "zhida_deep",
                "provider": "auto",
                "max_results": 5,
            }
        ),
        idempotency_key="web-search-zhida-intent",
    )

    assert response.status_code == 200
    data = response.json()["data"]
    result = data["result"]
    assert result["provider"] == "zhihu"
    assert result["provider_mode"] == "zhihu"
    assert result["requested_provider"] == "zhihu"
    assert result["intent"] == "zhida_deep"
    assert result["output_contract"] == "grounded_answer.v1"
    with get_session(database_url) as session:
        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord).where(ProviderCallRecord.run_id == data["run_id"])
            )
        )
        assert provider_calls[0].provider_id == "zhihu"


def test_zhihu_provider_uses_bearer_secret_and_merges_hot_list(monkeypatch: Any) -> None:
    captured: list[dict[str, Any]] = []

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            captured.append({"timeout": timeout})

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(
            self,
            endpoint: str,
            *,
            params: dict[str, str],
            headers: dict[str, str],
        ) -> httpx.Response:
            captured.append({"endpoint": endpoint, "params": params, "headers": headers})
            if endpoint.endswith("/zhihu_search"):
                payload = {
                    "Code": 0,
                    "Message": "success",
                    "Data": {
                        "Items": [
                            {
                                "Title": "AI 写作应该如何准备资料？",
                                "ContentType": "Answer",
                                "ContentID": "answer-1",
                                "ContentText": "先收集真实问题和反方观点。",
                                "Url": "https://www.zhihu.com/answer/answer-1",
                                "CommentCount": 2,
                                "VoteUpCount": 9,
                                "AuthorName": "知乎用户",
                                "EditTime": 1750000000,
                                "AuthorityLevel": "2",
                                "RankingScore": 0.98,
                            }
                        ]
                    },
                }
            else:
                payload = {
                    "Code": 0,
                    "Message": "success",
                    "Data": {
                        "Items": [
                            {
                                "Title": "热榜上的 AI 写作讨论",
                                "Url": "https://www.zhihu.com/question/456",
                                "Summary": "关于写作准备的热点问题。",
                                "ThumbnailUrl": "",
                            }
                        ]
                    },
                }
            return httpx.Response(200, json=payload, request=httpx.Request("GET", endpoint))

    monkeypatch.setattr("app.domain.web_search.service.httpx.Client", FakeClient)

    result = ZhihuWebSearchProvider(
        Settings(
            _env_file=None,
            environment="test",
            web_search_provider="zhihu",
            web_search_zhihu_access_secret="zhihu-secret",
            web_search_zhihu_search_path="/api/v1/content/zhihu_search",
            web_search_zhihu_hot_list_path="/api/v1/content/hot_list",
        )
    ).search(
        query="AI 写作准备",
        options={
            "intent": "zhihu_research",
            "provider": "zhihu",
            "max_results": 5,
            "source_type": "zhihu_research",
            "include_hot_list": True,
            "evidence_policy": {"required_sources": 1, "no_hit_policy": "abstain"},
        },
        site_id="site_alpha",
        run_id="run_zhihu_shape",
    )

    requests = [item for item in captured if "endpoint" in item]
    assert len(requests) == 2
    assert requests[0]["endpoint"].endswith("/api/v1/content/zhihu_search")
    assert requests[0]["params"] == {"Query": "AI 写作准备", "Count": "5"}
    assert requests[0]["headers"]["Authorization"] == "Bearer zhihu-secret"
    assert "X-Request-Timestamp" in requests[0]["headers"]
    assert requests[1]["endpoint"].endswith("/api/v1/content/hot_list")
    assert result.result_json["provider"] == "zhihu"
    assert result.result_json["evidence_pack"]["pack_type"] == "zhihu_writing_research"
    assert result.result_json["result_count"] == 2
    assert result.result_json["results"][0]["content_type"] == "Answer"
    assert result.result_json["results"][0]["vote_up_count"] == 9
    assert result.result_json["results"][1]["source"] == "zhihu_hot_list"
    assert result.result_json["direct_wordpress_write"] is False


def test_zhihu_research_does_not_mix_hot_list_by_default(monkeypatch: Any) -> None:
    captured: list[dict[str, Any]] = []

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            captured.append({"timeout": timeout})

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(
            self,
            endpoint: str,
            *,
            params: dict[str, str],
            headers: dict[str, str],
        ) -> httpx.Response:
            captured.append({"endpoint": endpoint, "params": params, "headers": headers})
            payload = {
                "Code": 0,
                "Message": "success",
                "Data": {
                    "Items": [
                        {
                            "Title": "AI 写作应该如何准备资料？",
                            "ContentType": "Answer",
                            "ContentText": "先收集真实问题和反方观点。",
                            "Url": "https://www.zhihu.com/answer/answer-1",
                            "RankingScore": 0.98,
                        }
                    ]
                },
            }
            return httpx.Response(200, json=payload, request=httpx.Request("GET", endpoint))

    monkeypatch.setattr("app.domain.web_search.service.httpx.Client", FakeClient)

    result = ZhihuWebSearchProvider(
        Settings(
            _env_file=None,
            environment="test",
            web_search_provider="zhihu",
            web_search_zhihu_access_secret="zhihu-secret",
            web_search_zhihu_search_path="/api/v1/content/zhihu_search",
        )
    ).search(
        query="AI 写作准备",
        options={
            "intent": "zhihu_research",
            "provider": "zhihu",
            "max_results": 5,
            "source_type": "zhihu_research",
            "evidence_policy": {"required_sources": 1, "no_hit_policy": "abstain"},
        },
        site_id="site_alpha",
        run_id="run_zhihu_no_hot_list",
    )

    requests = [item for item in captured if "endpoint" in item]
    assert len(requests) == 1
    assert requests[0]["endpoint"].endswith("/api/v1/content/zhihu_search")
    assert result.result_json["result_count"] == 1
    assert result.result_json["results"][0]["source"] == "zhihu"


def test_zhihu_hot_topics_uses_cached_hot_list_without_search(monkeypatch: Any) -> None:
    captured: list[dict[str, Any]] = []
    _ZHIHU_HOT_LIST_CACHE.clear()

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            captured.append({"timeout": timeout})

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(
            self,
            endpoint: str,
            *,
            params: dict[str, str],
            headers: dict[str, str],
        ) -> httpx.Response:
            captured.append({"endpoint": endpoint, "params": params, "headers": headers})
            payload = {
                "Code": 0,
                "Message": "success",
                "Data": {
                    "Items": [
                        {
                            "Title": "今天的 AI 写作热议",
                            "Url": "https://www.zhihu.com/question/hot-1",
                            "Summary": "热榜上的写作选题信号。",
                            "ThumbnailUrl": "",
                        }
                    ]
                },
            }
            return httpx.Response(200, json=payload, request=httpx.Request("GET", endpoint))

    monkeypatch.setattr("app.domain.web_search.service.httpx.Client", FakeClient)

    settings = Settings(
        _env_file=None,
        environment="test",
        web_search_provider="zhihu",
        web_search_zhihu_access_secret="zhihu-secret",
        web_search_zhihu_hot_list_path="/api/v1/content/hot_list",
        web_search_zhihu_hot_list_cache_ttl_seconds=3600,
    )
    provider = ZhihuWebSearchProvider(settings)
    options = {
        "intent": "zhihu_hot_topics",
        "provider": "zhihu",
        "max_results": 5,
        "source_type": "zhihu_hot_list",
        "evidence_policy": {"required_sources": 1, "no_hit_policy": "abstain"},
    }

    first = provider.search(
        query="知乎热榜",
        options=options,
        site_id="site_alpha",
        run_id="run_zhihu_hot_topics_first",
    )
    second = provider.search(
        query="知乎热榜",
        options=options,
        site_id="site_alpha",
        run_id="run_zhihu_hot_topics_second",
    )

    requests = [item for item in captured if "endpoint" in item]
    assert len(requests) == 1
    assert requests[0]["endpoint"].endswith("/api/v1/content/hot_list")
    assert "zhihu_search" not in requests[0]["endpoint"]
    assert first.result_json["intent"] == "zhihu_hot_topics"
    assert first.result_json["evidence_pack"]["pack_type"] == "zhihu_hot_topic_pool"
    assert first.result_json["results"][0]["source"] == "zhihu_hot_list"
    assert (
        first.result_json["atomic_outputs"]["topic_candidates"]["contract_version"]
        == "topic_candidate.v1"
    )
    assert first.result_json["atomic_outputs"]["topic_candidates"]["result_count"] == 1
    assert (
        first.result_json["atomic_outputs"]["topic_candidates"]["items"][0]["next_action"]
        == "manual_topic_selection_then_focused_research"
    )
    assert first.result_json["atomic_outputs"]["grounded_answer"]["status"] == "not_generated"
    assert second.result_json["results"][0]["title"] == "今天的 AI 写作热议"
    _ZHIHU_HOT_LIST_CACHE.clear()


def test_zhihu_global_search_uses_official_content_endpoint(monkeypatch: Any) -> None:
    captured: list[dict[str, Any]] = []

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            captured.append({"timeout": timeout})

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(
            self,
            endpoint: str,
            *,
            params: dict[str, str],
            headers: dict[str, str],
        ) -> httpx.Response:
            captured.append({"endpoint": endpoint, "params": params, "headers": headers})
            return httpx.Response(
                200,
                json={
                    "Code": 0,
                    "Message": "success",
                    "Data": {
                        "Items": [
                            {
                                "Title": "权威来源中的 AI 写作事实",
                                "Url": "https://example.com/ai-writing-source",
                                "Summary": "全网可信来源摘要。",
                                "RankingScore": 0.96,
                            }
                        ]
                    },
                },
                request=httpx.Request("GET", endpoint),
            )

    monkeypatch.setattr("app.domain.web_search.service.httpx.Client", FakeClient)

    result = ZhihuWebSearchProvider(
        Settings(
            _env_file=None,
            environment="test",
            web_search_provider="zhihu",
            web_search_zhihu_access_secret="zhihu-secret",
        )
    ).search(
        query="AI 写作事实核查",
        options={
            "intent": "zhihu_global_search",
            "provider": "zhihu",
            "max_results": 5,
            "source_type": "zhihu_global_search",
            "evidence_policy": {"required_sources": 1, "no_hit_policy": "abstain"},
        },
        site_id="site_alpha",
        run_id="run_zhihu_global_search",
    )

    requests = [item for item in captured if "endpoint" in item]
    assert requests[0]["endpoint"].endswith("/api/v1/content/global_search")
    assert requests[0]["params"] == {"Query": "AI 写作事实核查", "Count": "5"}
    assert requests[0]["headers"]["Authorization"] == "Bearer zhihu-secret"
    assert "X-Request-Timestamp" in requests[0]["headers"]
    assert result.result_json["intent"] == "zhihu_global_search"
    assert result.result_json["results"][0]["source"] == "zhihu_global_search"
    assert (
        result.result_json["atomic_outputs"]["source_evidence"]["contract_version"]
        == "source_evidence.v1"
    )


def test_zhihu_direct_answer_uses_chat_completions_contract(monkeypatch: Any) -> None:
    captured: list[dict[str, Any]] = []

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            captured.append({"timeout": timeout})

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(
            self,
            endpoint: str,
            *,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> httpx.Response:
            captured.append({"endpoint": endpoint, "json": json, "headers": headers})
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "model": "zhida-thinking-1p5",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "先明确读者问题，再收集证据和反方观点。",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                },
                request=httpx.Request("POST", endpoint),
            )

    monkeypatch.setattr("app.domain.web_search.service.httpx.Client", FakeClient)

    result = ZhihuWebSearchProvider(
        Settings(
            _env_file=None,
            environment="test",
            web_search_provider="zhihu",
            web_search_zhihu_access_secret="zhihu-secret",
        )
    ).search(
        query="AI 写作前应该准备什么？",
        options={
            "intent": "zhida_deep",
            "provider": "zhihu",
            "max_results": 5,
            "source_type": "zhida_deep",
            "evidence_policy": {"required_sources": 1, "no_hit_policy": "abstain"},
        },
        site_id="site_alpha",
        run_id="run_zhihu_direct_answer",
    )

    requests = [item for item in captured if "endpoint" in item]
    assert requests[0]["endpoint"].endswith("/v1/chat/completions")
    assert requests[0]["json"] == {
        "model": "zhida-thinking-1p5",
        "messages": [{"role": "user", "content": "AI 写作前应该准备什么？"}],
        "stream": False,
    }
    assert result.result_json["output_contract"] == "grounded_answer.v1"
    assert result.result_json["composition_role"] == "grounded_answer_preview"
    grounded_answer = result.result_json["atomic_outputs"]["grounded_answer"]
    assert grounded_answer["contract_version"] == "grounded_answer.v1"
    assert grounded_answer["status"] == "ready"
    assert grounded_answer["mode"] == "deep"
    assert "先明确读者问题" in grounded_answer["answer_text"]
    assert "反方观点" in grounded_answer["answer_text"]
    assert grounded_answer["direct_wordpress_write"] is False


def test_zhihu_direct_answer_provider_unavailable_returns_degraded_atom(
    monkeypatch: Any,
) -> None:
    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            pass

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(
            self,
            endpoint: str,
            *,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> httpx.Response:
            return httpx.Response(
                554,
                request=httpx.Request("POST", endpoint),
            )

    monkeypatch.setattr("app.domain.web_search.service.httpx.Client", FakeClient)

    result = ZhihuWebSearchProvider(
        Settings(
            _env_file=None,
            environment="test",
            web_search_provider="zhihu",
            web_search_zhihu_access_secret="zhihu-secret",
        )
    ).search(
        query="AI 写作前应该准备什么？",
        options={
            "intent": "zhida_deep",
            "provider": "zhihu",
            "max_results": 5,
            "source_type": "zhida_deep",
        },
        site_id="site_alpha",
        run_id="run_zhihu_direct_answer_degraded",
    )

    assert result.usage.error_code == "provider.unavailable"
    assert result.result_json["output_contract"] == "grounded_answer.v1"
    assert result.result_json["status"] == "provider_unavailable"
    assert result.result_json["provider_error"]["provider"] == "zhihu"
    assert (
        "Zhihu web search failed with HTTP 554"
        in result.result_json["provider_error"]["message"]
    )
    grounded_answer = result.result_json["atomic_outputs"]["grounded_answer"]
    assert grounded_answer["contract_version"] == "grounded_answer.v1"
    assert grounded_answer["status"] == "provider_unavailable"
    assert grounded_answer["direct_wordpress_write"] is False
    assert grounded_answer["answer_text"] == ""


def test_zhihu_direct_answer_requires_configured_endpoint() -> None:
    provider = ZhihuWebSearchProvider(
        Settings(
            _env_file=None,
            environment="test",
            web_search_provider="zhihu",
            web_search_zhihu_access_secret="zhihu-secret",
            web_search_zhihu_direct_answer_path="",
        )
    )

    with pytest.raises(WebSearchProviderError) as error:
        provider.search(
            query="AI 写作前应该准备什么？",
            options={
                "intent": "zhida_simple",
                "provider": "zhihu",
                "max_results": 5,
                "source_type": "zhida_simple",
            },
            site_id="site_alpha",
            run_id="run_zhihu_direct_answer_missing_endpoint",
        )

    assert error.value.error_code == "web_search.zhihu_endpoint_missing"


def test_apify_provider_uses_actor_query_string_and_bearer_auth(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(
            self,
            endpoint: str,
            *,
            headers: dict[str, str],
            json: dict[str, Any],
        ) -> httpx.Response:
            captured["endpoint"] = endpoint
            captured["headers"] = headers
            captured["json"] = json
            return httpx.Response(
                200,
                json=[
                    {
                        "searchQuery": {
                            "term": "latest WordPress AI search trends",
                            "url": "https://www.google.com/search?q=latest+WordPress+AI+search+trends",
                        },
                        "url": "https://www.google.com/search?q=latest+WordPress+AI+search+trends",
                        "organicResults": [
                            {
                                "title": "Apify source",
                                "url": "https://example.com/apify-source",
                                "description": "A source returned by Apify.",
                            }
                        ],
                    }
                ],
                request=httpx.Request("POST", endpoint),
            )

    monkeypatch.setattr("app.domain.web_search.service.httpx.Client", FakeClient)

    result = ApifyWebSearchProvider(
        Settings(
            _env_file=None,
            environment="test",
            web_search_provider="apify",
            web_search_apify_api_token="redacted-placeholder",
            web_search_apify_actor_id="apify/google-search-scraper",
        )
    ).search(
        query="latest WordPress AI search trends",
        options={
            "intent": "news",
            "provider": "apify",
            "max_results": 3,
            "language": "en",
            "region": "US",
            "evidence_policy": {"required_sources": 1, "no_hit_policy": "abstain"},
        },
        site_id="site_alpha",
        run_id="run_apify_shape",
    )

    assert captured["json"]["queries"] == "latest WordPress AI search trends"
    assert captured["json"]["maxResults"] == 3
    assert captured["json"]["resultsPerPage"] == 3
    assert captured["json"]["maxPagesPerQuery"] == 1
    assert captured["json"]["language"] == "en"
    assert captured["json"]["countryCode"] == "US"
    assert captured["headers"]["Authorization"] == "Bearer redacted-placeholder"
    assert "token=" not in captured["endpoint"]
    assert result.result_json["provider"] == "apify"
    assert result.result_json["provider_mode"] == "apify"
    assert result.result_json["output_contract"] == "search_evidence_pack.v1"
    assert result.result_json["evidence_pack"]["artifact_type"] == "search_evidence_pack"
    assert result.result_json["evidence_pack"]["contract_version"] == "search_evidence_pack.v1"
    assert result.result_json["evidence_pack"]["pack_type"] == "external_research"
    assert result.result_json["evidence_pack"]["citation_candidates"][0]["url"] == (
        "https://example.com/apify-source"
    )
    assert len(result.result_json["results"]) == 1
    assert result.result_json["evidence_gate"]["source_count"] == 1
    assert result.result_json["results"][0]["url"] == "https://example.com/apify-source"


def test_web_search_rejects_provider_keys_in_runtime_input(tmp_path: Path) -> None:
    _, client = _build_client(tmp_path)

    response = _execute(
        client,
        _payload({"provider_key": "tvly-user-secret"}),
        idempotency_key="web-search-forbid-provider-key",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "runtime.secret_input_detected"
