from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.queue.in_memory import InMemoryRuntimeQueue
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import get_session, init_schema
from app.core.models import ProviderCallRecord, RunRecord, UsageMeterEvent
from app.core.services import CloudServices
from app.domain.web_search.service import (
    ApifyWebSearchProvider,
    BochaWebSearchProvider,
    TavilyWebSearchProvider,
    WebSearchExecutionResult,
    WebSearchProviderUsage,
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
        "project_name": "Magick AI Cloud Web Search Test",
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


def _payload(input_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
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
        "ability_name": "magick-ai-cloud/web-search",
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
                "evidence_gate": {
                    "status": "passed",
                    "allows_web_grounded_assertion": True,
                    "source_count": 1,
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
    assert result["direct_wordpress_write"] is False
    assert result["workflow_metadata"] == {
        "workflow_id": "external_web_evidence_preflight",
        "workflow_version": "web_search_evidence_workflow.v1",
        "workflow_kind": "fixed_evidence_workflow",
        "triggering_ability": "magick-ai-cloud/web-search",
        "triggering_contract": "web_search.v1",
        "intent": "news",
        "cloud_output": "external_web_evidence",
        "handoff_owner": "wordpress_local",
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
        "steps": [
            "validate_runtime_contract",
            "select_cloud_managed_search_provider",
            "normalize_and_score_sources",
            "apply_evidence_gate",
            "return_suggestion_only_evidence",
        ],
        "stop_conditions": [
            "provider_not_configured",
            "provider_fallback_exhausted",
            "insufficient_evidence",
        ],
    }
    assert result["evidence_gate"]["allows_web_grounded_assertion"] is True
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
    assert response.json()["error_code"] == "web_search.write_or_secret_field_forbidden"
