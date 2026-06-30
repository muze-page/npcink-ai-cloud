from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.callbacks.base import RuntimeCallbackDispatcher
from app.adapters.callbacks.http import HttpRuntimeCallbackDispatcher
from app.adapters.providers.anthropic import AnthropicProviderAdapter
from app.adapters.providers.base import (
    ProviderAdapter,
    ProviderExecutionError,
    ProviderExecutionRequest,
    ProviderExecutionResult,
)
from app.adapters.providers.minimax import MiniMaxProviderAdapter
from app.adapters.providers.openai import OpenAIProviderAdapter
from app.adapters.queue.in_memory import InMemoryRuntimeQueue
from app.api.main import create_app
from app.core import security as security_module
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    SITE_API_KEY_STATUS_REVOKED,
    AccountSubscription,
    AudioAsset,
    MediaDerivativeArtifact,
    PlanVersion,
    RunRecord,
    RuntimeGuardEvent,
    Site,
    SiteApiKey,
    UsageMeterEvent,
)
from app.core.secrets import encrypt_runtime_terminal_callback_secret
from app.core.security import (
    build_body_digest,
    build_canonical_request,
    build_hmac_signature,
)
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from app.domain.hosted_model_defaults import (
    AUDIO_NARRATION_MODEL_ID,
    AUDIO_NARRATION_PROFILE_ID,
    FREE_GPT55_MODEL_ID,
    FREE_GPT55_TEXT_PROFILE_ID,
    GROK_IMAGINE_IMAGE_MODEL_ID,
    GROK_IMAGINE_IMAGE_PROFILE_ID,
    TEXT_AI_PROFILE_ID,
)
from app.domain.runtime.models import RuntimeRequest
from app.domain.runtime.service import RuntimeService
from app.domain.web_search.service import (
    WebSearchExecutionResult,
    WebSearchProviderUsage,
    WebSearchService,
)
from tests.conftest import (
    build_auth_headers,
    merge_json_headers,
    seed_site_auth,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'runtime-api.sqlite3'}"


def _build_client(
    tmp_path: Path,
    *,
    providers: dict[str, ProviderAdapter] | None = None,
    runtime_queue: InMemoryRuntimeQueue | None = None,
    callback_dispatcher: RuntimeCallbackDispatcher | None = None,
    settings_overrides: dict[str, object] | None = None,
    bootstrap_catalog: bool = True,
) -> tuple[str, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    if bootstrap_catalog:
        CatalogService(database_url, providers=providers).refresh_catalog()
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )
    seed_site_auth(
        database_url,
        site_id="site_beta",
        key_id="key_beta",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        **(settings_overrides or {}),
    )
    return database_url, TestClient(
        create_app(
            CloudServices(
                settings=settings,
                providers=providers or {},
                runtime_queue=runtime_queue,
                callback_dispatcher=callback_dispatcher,
            )
        )
    )


def _runtime_service_settings(database_url: str) -> Settings:
    return Settings(
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )


def _runtime_callback_metadata(
    callback_url: str,
    *,
    callback_id: str = "runtime_terminal",
) -> dict[str, object]:
    settings = _runtime_service_settings("sqlite+pysqlite:///:memory:")
    return {
        "runtime_callbacks": {
            "terminal": {
                "enabled": True,
                "callback_url": callback_url,
                "key_id": "runtime_callback_key",
                "secret_ciphertext": encrypt_runtime_terminal_callback_secret(
                    "runtime-callback-secret-for-tests-32b",
                    settings=settings,
                ),
                "callback_id": callback_id,
            }
        }
    }


class SequencedProviderAdapter(OpenAIProviderAdapter):
    def __init__(self, outcomes_by_instance: dict[str, list[dict[str, object]]]) -> None:
        super().__init__()
        self.outcomes_by_instance = outcomes_by_instance
        self.attempts_by_instance: dict[str, int] = {}

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        outcomes = self.outcomes_by_instance.get(request.instance_id, [])
        attempt_index = self.attempts_by_instance.get(request.instance_id, 0)
        self.attempts_by_instance[request.instance_id] = attempt_index + 1
        if not outcomes:
            return super().execute(request)

        outcome = outcomes[min(attempt_index, len(outcomes) - 1)]
        if outcome["kind"] == "error":
            retryable = outcome.get("retryable")
            raise ProviderExecutionError(
                str(outcome["error_code"]),
                str(outcome["message"]),
                retryable=retryable if isinstance(retryable, bool) else None,
                tokens_in=int(outcome.get("tokens_in", 0)),
                tokens_out=int(outcome.get("tokens_out", 0)),
                cost=float(outcome.get("cost", 0.0)),
            )

        output_text = str(outcome.get("output_text", "sequenced success"))
        tokens_in = int(outcome.get("tokens_in", 6))
        tokens_out = int(outcome.get("tokens_out", 4))
        latency_ms = int(outcome.get("latency_ms", 90))
        return ProviderExecutionResult(
            output={
                "output_text": output_text,
                "messages": [{"role": "assistant", "content": output_text}],
                "model_id": request.model_id,
            },
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=0.0,
        )


class RecordingProviderAdapter(OpenAIProviderAdapter):
    def __init__(self) -> None:
        super().__init__(sample_catalog_profile="free-gpt55")
        self.requests: list[ProviderExecutionRequest] = []

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        self.requests.append(request)
        web_search_evidence = (
            request.input_payload.get("cloud_evidence", {})
            if isinstance(request.input_payload.get("cloud_evidence"), dict)
            else {}
        ).get("web_search")
        return ProviderExecutionResult(
            output={
                "output_text": "recording provider success",
                "received_automatic_web_search": isinstance(web_search_evidence, dict),
            },
            latency_ms=25,
            tokens_in=5,
            tokens_out=3,
            cost=0.0,
        )


def test_runtime_auto_web_search_enriches_provider_input(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url = _sqlite_url(tmp_path)
    provider = RecordingProviderAdapter()
    init_schema(database_url)
    CatalogService(database_url, providers={"openai": provider}).refresh_catalog()
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )
    settings = Settings(
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        web_search_provider="tavily",
        web_search_tavily_api_key="redacted-placeholder",
    )

    def fake_search(
        self: WebSearchService,
        *,
        site_id: str,
        ability_name: str,
        contract_version: str,
        input_payload: dict[str, Any],
        run_id: str,
    ) -> WebSearchExecutionResult:
        assert input_payload["query"] == "latest WordPress AI search trends"
        assert input_payload["intent"] == "news"
        return WebSearchExecutionResult(
            result_json={
                "artifact_type": "web_search_results",
                "composition_role": "external_web_evidence",
                "status": "ready",
                "provider": "tavily",
                "intent": "news",
                "query_hash": "hash-only",
                "query_chars": len(input_payload["query"]),
                "evidence_gate": {
                    "status": "passed",
                    "source_count": 1,
                    "allows_web_grounded_assertion": True,
                },
                "results": [
                    {
                        "title": "Search source",
                        "url": "https://example.com/source",
                        "snippet": "External source.",
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
                latency_ms=12,
                cost=0.002,
            ),
        )

    monkeypatch.setattr(WebSearchService, "execute", fake_search)

    response = RuntimeService(
        database_url,
        settings=settings,
        providers={"openai": provider},
    ).execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            ability_family="workflow",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            contract_version="v1",
            input_payload={
                "topic": "latest WordPress AI search trends",
                "search_policy": {
                    "mode": "auto",
                    "intent": "news",
                    "max_results": 2,
                    "recency_days": 7,
                },
            },
            policy={"allow_fallback": True},
        )
    )

    assert response.status == "succeeded"
    assert response.provider_call_count == 2
    assert response.result["received_automatic_web_search"] is True
    assert response.result["automatic_web_search"]["status"] == "ready"
    assert provider.requests
    evidence = provider.requests[0].input_payload["cloud_evidence"]["web_search"]
    assert evidence["report"]["status"] == "ready"
    assert evidence["result"]["results"][0]["url"] == "https://example.com/source"


def test_runtime_auto_web_search_dry_run_does_not_call_search(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url = _sqlite_url(tmp_path)
    provider = RecordingProviderAdapter()
    init_schema(database_url)
    CatalogService(database_url, providers={"openai": provider}).refresh_catalog()
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )
    settings = Settings(
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        web_search_provider="tavily",
        web_search_tavily_api_key="redacted-placeholder",
    )

    def unexpected_search(self: WebSearchService, **kwargs: Any) -> WebSearchExecutionResult:
        raise AssertionError("dry_run must not call WebSearchService")

    monkeypatch.setattr(WebSearchService, "execute", unexpected_search)

    response = RuntimeService(
        database_url,
        settings=settings,
        providers={"openai": provider},
    ).execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            ability_family="workflow",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            contract_version="v1",
            input_payload={
                "topic": "latest WordPress AI search trends",
                "search_policy": {
                    "mode": "dry_run",
                    "intent": "news",
                },
            },
            policy={"allow_fallback": True},
        )
    )

    assert response.status == "succeeded"
    assert response.provider_call_count == 1
    assert response.result["received_automatic_web_search"] is False
    assert response.result["automatic_web_search"]["status"] == "would_search"


def test_runtime_auto_web_search_uses_openclaw_external_evidence_hint(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url = _sqlite_url(tmp_path)
    provider = RecordingProviderAdapter()
    init_schema(database_url)
    CatalogService(database_url, providers={"openai": provider}).refresh_catalog()
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )
    settings = Settings(
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        web_search_provider="tavily",
        web_search_tavily_api_key="redacted-placeholder",
    )
    captured_input: dict[str, Any] = {}

    def fake_search(
        self: WebSearchService,
        *,
        site_id: str,
        ability_name: str,
        contract_version: str,
        input_payload: dict[str, Any],
        run_id: str,
    ) -> WebSearchExecutionResult:
        captured_input.update(input_payload)
        return WebSearchExecutionResult(
            result_json={
                "artifact_type": "web_search_results",
                "composition_role": "external_web_evidence",
                "status": "ready",
                "provider": "tavily",
                "intent": input_payload["intent"],
                "query_hash": "hash-only",
                "query_chars": len(input_payload["query"]),
                "evidence_gate": {
                    "status": "passed",
                    "source_count": 1,
                    "allows_web_grounded_assertion": True,
                },
                "results": [
                    {
                        "title": "Fact check source",
                        "url": "https://example.com/fact-check",
                        "snippet": "External source.",
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
                latency_ms=31,
                cost=0.002,
            ),
        )

    monkeypatch.setattr(WebSearchService, "execute", fake_search)

    response = RuntimeService(
        database_url,
        settings=settings,
        providers={"openai": provider},
    ).execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="openclaw.site_audit",
            ability_family="openclaw",
            channel="openclaw",
            execution_kind="text",
            profile_id="text.balanced",
            contract_version="v1",
            input_payload={
                "topic": "Verify latest WordPress AI search claims",
                "intent": "fact_check",
                "caller": {"caller_type": "openclaw_adapter"},
            },
            policy={"allow_fallback": True},
        )
    )

    assert response.status == "succeeded"
    assert response.provider_call_count == 2
    assert captured_input["max_results"] == 3
    assert captured_input["recency_days"] == 30
    assert captured_input["enhance_with_reader"] is False
    raw_result = response.result["_cloud_raw_result"]
    assert raw_result["automatic_web_search"]["trigger"] == "channel_external_evidence_hint"
    assert raw_result["automatic_web_search"]["usage_summary"]["provider_id"] == "tavily"
    assert raw_result["automatic_web_search"]["usage_summary"]["latency_ms"] == 31
    assert (
        provider.requests[0].input_payload["cloud_evidence"]["web_search"]["report"]["result_count"]
        == 1
    )


def test_execute_route_runs_and_supports_idempotency(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "skill_id": "content_summary_seo",
        "workflow_id": "content_summary_seo_completion",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "data_classification": "internal",
        "timeout_seconds": 1800,
        "retry_max": 2,
        "retention_ttl": 86400,
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "polling_preferred",
            "polling_interval_sec": 120,
        },
        "profile_id": "text.balanced",
        "idempotency_key": "idem-balanced-001",
        "trace_id": "trace-balanced-001",
        "input": {"messages": [{"role": "user", "content": "write a short draft"}]},
        "policy": {"allow_fallback": True},
    }
    body = json.dumps(payload).encode("utf-8")
    first_headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-balanced-001",
            nonce="nonce-balanced-001",
            trace_id="tracebalanced0010000000000000000",
            body=body,
        )
    )
    replay_headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-balanced-001",
            nonce="nonce-balanced-002",
            trace_id="tracebalanced0010000000000000001",
            body=body,
        )
    )

    first_response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=first_headers,
    )
    second_response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=replay_headers,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert "X-Npcink-Deprecated-Execution-Pattern" not in first_response.headers
    assert "X-Npcink-Canonical-Execution-Pattern" not in first_response.headers
    assert "X-Npcink-Deprecated-Execution-Pattern" not in second_response.headers
    assert "X-Npcink-Canonical-Execution-Pattern" not in second_response.headers

    first_data = first_response.json()["data"]
    second_data = second_response.json()["data"]
    assert first_data["run_id"] == second_data["run_id"]
    assert first_data["idempotent_replay"] is False
    assert second_data["idempotent_replay"] is True
    assert first_data["provider_call_count"] == 1
    assert first_data["error_code"] == ""
    assert first_data["execution_context"] == {
        "skill_id": "content_summary_seo",
        "workflow_id": "content_summary_seo_completion",
        "contract_version": "v1",
        "ability_family": "workflow",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "data_classification": "internal",
        "storage_mode": "result_only",
    }
    assert first_data["task_backend"] == {
        "enabled": True,
        "mode": "polling",
        "callback_mode": "polling_preferred",
        "polling_interval_sec": 120,
        "callback_url": "",
        "timeout_seconds": 1800,
        "retry_max": 2,
        "retention_ttl": 86400,
        "status": "completed",
    }
    assert first_data["run_lifecycle"]["phase"] == "terminal"
    assert first_data["run_lifecycle"]["queue_mode"] == "inline"
    assert first_data["run_lifecycle"]["terminal_status"] == "succeeded"
    assert first_data["run_lifecycle"]["retention"]["state"] == "retained"
    assert first_data["run_lifecycle"]["cancel"]["state"] == "not_available"

    run_headers = build_auth_headers(
        "GET",
        f"/v1/runs/{first_data['run_id']}",
        site_id="site_alpha",
        trace_id="tracebalanced0010000000000000001",
    )
    result_headers = build_auth_headers(
        "GET",
        f"/v1/runs/{first_data['run_id']}/result",
        site_id="site_alpha",
        trace_id="tracebalanced0010000000000000002",
    )
    run_response = client.get(f"/v1/runs/{first_data['run_id']}", headers=run_headers)
    result_response = client.get(
        f"/v1/runs/{first_data['run_id']}/result",
        headers=result_headers,
    )

    assert run_response.status_code == 200
    assert result_response.status_code == 200
    assert run_response.json()["data"]["provider_call_count"] == 1
    assert run_response.json()["data"]["skill_id"] == "content_summary_seo"
    assert run_response.json()["data"]["task_backend"]["status"] == "completed"
    assert run_response.json()["data"]["run_lifecycle"]["phase"] == "terminal"
    assert result_response.json()["data"]["result"]["output_text"].startswith("[hosted:")
    assert result_response.json()["data"]["execution_context"]["execution_pattern"] == "inline"
    assert result_response.json()["data"]["execution_context"]["ability_family"] == "workflow"
    assert result_response.json()["data"]["task_backend"]["retry_max"] == 2
    assert result_response.json()["data"]["run_lifecycle"]["retention"]["state"] == "retained"

    with get_session(database_url) as session:
        meter_events = list(
            session.scalars(
                select(UsageMeterEvent)
                .where(UsageMeterEvent.run_id == first_data["run_id"])
                .order_by(UsageMeterEvent.id.asc())
            )
        )
    assert [event.meter_key for event in meter_events] == [
        "runs",
        "provider_calls",
        "tokens_in",
        "tokens_out",
        "tokens_total",
        "cost",
    ]
    assert all(event.ability_family == "workflow" for event in meter_events)

    dispose_engine(database_url)


def test_execute_route_defaults_text_requests_to_free_gpt55(tmp_path: Path) -> None:
    provider = RecordingProviderAdapter()
    database_url, client = _build_client(tmp_path, providers={"openai": provider})
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "data_classification": "internal",
        "input": {"messages": [{"role": "user", "content": "write a short draft"}]},
        "policy": {"allow_fallback": False},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-free-gpt55-default-001",
            nonce="nonce-free-gpt55-default-001",
            trace_id="tracefreegpt55default0010000",
            body=body,
        )
    )

    response = client.post("/v1/runtime/execute", content=body, headers=headers)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["profile_id"] == FREE_GPT55_TEXT_PROFILE_ID
    assert data["model_id"] == FREE_GPT55_MODEL_ID
    assert provider.requests
    assert provider.requests[0].profile_id == FREE_GPT55_TEXT_PROFILE_ID
    assert provider.requests[0].model_id == FREE_GPT55_MODEL_ID

    dispose_engine(database_url)


def test_execute_route_accepts_text_ai_profile_alias(tmp_path: Path) -> None:
    provider = RecordingProviderAdapter()
    database_url, client = _build_client(tmp_path, providers={"openai": provider})
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/content-support",
        "ability_family": "text",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "profile_id": TEXT_AI_PROFILE_ID,
        "data_classification": "internal",
        "input": {"messages": [{"role": "user", "content": "summarize this draft"}]},
        "policy": {"allow_fallback": False},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-text-ai-profile-001",
            nonce="nonce-text-ai-profile-001",
            trace_id="tracetextaiprofile00100000000",
            body=body,
        )
    )

    response = client.post("/v1/runtime/execute", content=body, headers=headers)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["profile_id"] == TEXT_AI_PROFILE_ID
    assert data["model_id"]
    assert provider.requests
    assert provider.requests[0].profile_id == TEXT_AI_PROFILE_ID
    assert provider.requests[0].model_id == data["model_id"]

    dispose_engine(database_url)


def test_execute_route_defaults_image_generation_to_grok_imagine(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-cloud/generate-image",
        "contract_version": "image_generation_request.v1",
        "channel": "openapi",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "input": {
            "contract_version": "image_generation_request.v1",
            "prompt": "A clean product photo of a red running shoe",
            "aspect_ratio": "16:9",
            "resolution": "high",
            "response_format": "url",
        },
        "policy": {"allow_fallback": False},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-image-generation-default-001",
            nonce="nonce-image-generation-default-001",
            trace_id="1234567890abcdef1234567890abcd01",
            body=body,
        )
    )

    response = client.post("/v1/runtime/execute", content=body, headers=headers)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    assert data["profile_id"] == GROK_IMAGINE_IMAGE_PROFILE_ID
    assert data["model_id"] == GROK_IMAGINE_IMAGE_MODEL_ID
    assert data["execution_context"]["ability_family"] == "vision"
    assert data["execution_context"]["data_classification"] == "internal"
    assert data["result"]["artifact_type"] == "image_generation_candidates"
    assert data["result"]["direct_wordpress_write"] is False
    assert data["result"]["images"][0]["mime_type"] == "image/png"

    dispose_engine(database_url)


def test_execute_route_rejects_image_generation_write_controls(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-cloud/generate-image",
        "contract_version": "image_generation_request.v1",
        "channel": "openapi",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "input": {
            "contract_version": "image_generation_request.v1",
            "prompt": "A clean product photo of a red running shoe",
            "direct_wordpress_write": True,
        },
        "policy": {"allow_fallback": False},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-image-generation-reject-001",
            nonce="nonce-image-generation-reject-001",
            trace_id="1234567890abcdef1234567890abcd02",
            body=body,
        )
    )

    response = client.post("/v1/runtime/execute", content=body, headers=headers)

    assert response.status_code == 400, response.text
    assert response.json()["error_code"] == "image_generation.write_or_secret_field_forbidden"

    dispose_engine(database_url)


def test_execute_route_rejects_oversized_image_generation_inputs(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-cloud/generate-image",
        "contract_version": "image_generation_request.v1",
        "channel": "openapi",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "input": {
            "contract_version": "image_generation_request.v1",
            "prompt": "x" * 4001,
            "n": 1,
        },
        "policy": {"allow_fallback": False},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-image-generation-prompt-too-long",
            nonce="nonce-image-generation-prompt-too-long",
            trace_id="1234567890abcdef1234567890abcd03",
            body=body,
        )
    )

    response = client.post("/v1/runtime/execute", content=body, headers=headers)

    assert response.status_code == 400, response.text
    assert response.json()["error_code"] == "image_generation.prompt_too_long"

    payload["input"] = {
        "contract_version": "image_generation_request.v1",
        "prompt": "A clean product photo",
        "n": 5,
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-image-generation-too-many",
            nonce="nonce-image-generation-too-many",
            trace_id="1234567890abcdef1234567890abcd04",
            body=body,
        )
    )

    response = client.post("/v1/runtime/execute", content=body, headers=headers)

    assert response.status_code == 400, response.text
    assert response.json()["error_code"] == "image_generation.image_count_invalid"

    dispose_engine(database_url)


def test_execute_route_defaults_audio_generation_to_minimax_narration(
    tmp_path: Path,
) -> None:
    provider = MiniMaxProviderAdapter(
        allow_sample_catalog=True,
        allow_sample_execution=True,
    )
    database_url, client = _build_client(
        tmp_path,
        providers={"minimax": provider},
        settings_overrides={
            "audio_asset_playback_token_secret": "test-audio-playback-secret-00000000"
        },
    )
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-cloud/generate-audio",
        "contract_version": "audio_generation_request.v1",
        "channel": "openapi",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "input": {
            "contract_version": "audio_generation_request.v1",
            "intent": "article_narration",
            "text": "这是一段文章旁白。",
            "format": "mp3",
            "response_format": "url",
        },
        "policy": {"allow_fallback": False},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-audio-generation-default-001",
            nonce="nonce-audio-generation-default-001",
            trace_id="1234567890abcdef1234567890abcd06",
            body=body,
        )
    )

    response = client.post("/v1/runtime/execute", content=body, headers=headers)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    assert data["profile_id"] == AUDIO_NARRATION_PROFILE_ID
    assert data["model_id"] == AUDIO_NARRATION_MODEL_ID
    assert data["execution_context"]["ability_family"] == "audio"
    assert data["execution_context"]["data_classification"] == "internal"
    assert data["result"]["artifact_type"] == "audio_generation_candidates"
    assert data["result"]["direct_wordpress_write"] is False
    assert data["result"]["audios"][0]["mime_type"] == "audio/mpeg"
    audio_url = data["result"]["audios"][0]["url"]
    assert audio_url.startswith("/v1/runtime/artifacts/")
    assert "/public-download?token=" in audio_url
    assert data["result"]["audios"][0]["artifact"]["source_media_type"] == "audio"
    assert data["result"]["audios"][0]["artifact"]["download_url"] == audio_url
    assert data["result"]["audios"][0]["artifact"]["authenticated_download_url"].endswith(
        "/download"
    )
    assert data["result"]["audio_materialization"]["status"] == "materialized"

    with get_session(database_url) as session:
        artifact = session.query(MediaDerivativeArtifact).filter_by(site_id="site_alpha").one()
        assert artifact.source_media_type == "audio"
        assert artifact.blob_data
        assert artifact.mime_type == "audio/mpeg"
        artifact_id = artifact.artifact_id

    download_headers = build_auth_headers(
        "GET",
        f"/v1/runtime/artifacts/{artifact_id}/download",
        site_id="site_alpha",
    )
    download_response = client.get(
        f"/v1/runtime/artifacts/{artifact_id}/download",
        headers=download_headers,
    )
    assert download_response.status_code == 200
    assert download_response.headers["content-type"].startswith("audio/mpeg")
    assert int(download_response.headers["content-length"]) == len(download_response.content)
    assert download_response.content.startswith(b"ID3")

    public_download_response = client.get(audio_url)
    assert public_download_response.status_code == 200
    assert public_download_response.headers["content-type"].startswith("audio/mpeg")
    assert int(public_download_response.headers["content-length"]) == len(
        public_download_response.content
    )
    assert public_download_response.content.startswith(b"ID3")

    invalid_public_download_response = client.get(
        f"/v1/runtime/artifacts/{artifact_id}/public-download?token=bad"
    )
    assert invalid_public_download_response.status_code == 403

    promote_payload = {
        "artifact_id": artifact_id,
        "source_content_hash": "sha256:" + ("a" * 64),
        "metadata": {"post_id": 42, "post_type": "post", "title": "Audio article"},
        "playback_ttl_seconds": 120,
    }
    promote_body = json.dumps(promote_payload).encode("utf-8")
    promote_headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/audio-assets",
            site_id="site_alpha",
            idempotency_key="idem-audio-asset-promote-001",
            nonce="nonce-audio-asset-promote-001",
            trace_id="1234567890abcdef1234567890abcd17",
            body=promote_body,
        )
    )
    promote_response = client.post(
        "/v1/runtime/audio-assets",
        content=promote_body,
        headers=promote_headers,
    )
    assert promote_response.status_code == 200, promote_response.text
    promoted = promote_response.json()["data"]
    assert promoted["playback_mode"] == "cloud_hosted"
    assert promoted["direct_wordpress_write"] is False
    assert promoted["source_artifact_id"] == artifact_id
    assert promoted["source_content_hash"] == "sha256:" + ("a" * 64)
    assert promoted["playback_url"].startswith(
        f"/v1/runtime/audio-assets/{promoted['asset_id']}/playback?"
    )

    playback_response = client.get(promoted["playback_url"])
    assert playback_response.status_code == 200
    assert playback_response.headers["content-type"].startswith("audio/mpeg")
    assert playback_response.content.startswith(b"ID3")

    invalid_playback_response = client.get(
        f"/v1/runtime/audio-assets/{promoted['asset_id']}/playback?expires=1&token=bad"
    )
    assert invalid_playback_response.status_code == 410

    playback_url_headers = build_auth_headers(
        "GET",
        f"/v1/runtime/audio-assets/{promoted['asset_id']}/playback-url",
        site_id="site_alpha",
        query="ttl_seconds=180",
    )
    playback_url_response = client.get(
        f"/v1/runtime/audio-assets/{promoted['asset_id']}/playback-url?ttl_seconds=180",
        headers=playback_url_headers,
    )
    assert playback_url_response.status_code == 200, playback_url_response.text
    playback_url_data = playback_url_response.json()["data"]
    assert playback_url_data["asset_id"] == promoted["asset_id"]
    assert playback_url_data["playback_url_ttl_seconds"] == 180

    beta_playback_url_headers = build_auth_headers(
        "GET",
        f"/v1/runtime/audio-assets/{promoted['asset_id']}/playback-url",
        site_id="site_beta",
        key_id="key_beta",
        query="ttl_seconds=180",
    )
    beta_playback_url_response = client.get(
        f"/v1/runtime/audio-assets/{promoted['asset_id']}/playback-url?ttl_seconds=180",
        headers=beta_playback_url_headers,
    )
    assert beta_playback_url_response.status_code == 404

    with get_session(database_url) as session:
        asset = session.query(AudioAsset).filter_by(site_id="site_alpha").one()
        assert asset.asset_id == promoted["asset_id"]
        assert asset.source_artifact_id == artifact_id
        assert asset.source_run_id
        assert asset.blob_data.startswith(b"ID3")
        assert asset.metadata_json["playback_mode"] == "cloud_hosted"

    dispose_engine(database_url)


def test_execute_route_fails_audio_generation_when_provider_url_cannot_materialize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "audio_url": "https://minimax.example.test/audio/signed.mp3",
                    "extra_info": {
                        "usage_characters": 9,
                        "audio_length": 2400,
                        "audio_format": "mp3",
                    },
                },
                "base_resp": {"status_code": 0, "status_msg": "success"},
            },
        )

    provider = MiniMaxProviderAdapter(
        api_key="test-minimax-key",
        allow_sample_catalog=True,
        transport=httpx.MockTransport(handler),
    )
    database_url, client = _build_client(tmp_path, providers={"minimax": provider})

    from app.domain.audio_generation import artifacts as audio_artifacts

    def fail_download(*args: object, **kwargs: object) -> bytes:
        raise audio_artifacts.AudioArtifactMaterializationError(
            "provider audio URL returned HTTP 403"
        )

    monkeypatch.setattr(audio_artifacts, "_download_audio_url", fail_download)

    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-cloud/generate-audio",
        "contract_version": "audio_generation_request.v1",
        "channel": "openapi",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "input": {
            "contract_version": "audio_generation_request.v1",
            "intent": "article_narration",
            "text": "这是一段文章旁白。",
            "format": "mp3",
            "response_format": "url",
        },
        "policy": {"allow_fallback": False},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-audio-generation-materialize-fail-001",
            nonce="nonce-audio-generation-materialize-fail-001",
            trace_id="1234567890abcdef1234567890abcd16",
            body=body,
        )
    )

    response = client.post("/v1/runtime/execute", content=body, headers=headers)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "failed"
    assert data["error_code"] == "audio_generation.artifact_materialization_failed"
    assert "HTTP 403" in data["error_message"]
    with get_session(database_url) as session:
        assert session.query(MediaDerivativeArtifact).count() == 0

    dispose_engine(database_url)


def test_execute_route_rejects_audio_generation_write_controls(
    tmp_path: Path,
) -> None:
    provider = MiniMaxProviderAdapter(
        allow_sample_catalog=True,
        allow_sample_execution=True,
    )
    database_url, client = _build_client(tmp_path, providers={"minimax": provider})
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-cloud/generate-audio",
        "contract_version": "audio_generation_request.v1",
        "channel": "openapi",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "input": {
            "contract_version": "audio_generation_request.v1",
            "intent": "article_narration",
            "text": "这是一段文章旁白。",
            "direct_wordpress_write": True,
        },
        "policy": {"allow_fallback": False},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-audio-generation-reject-001",
            nonce="nonce-audio-generation-reject-001",
            trace_id="1234567890abcdef1234567890abcd07",
            body=body,
        )
    )

    response = client.post("/v1/runtime/execute", content=body, headers=headers)

    assert response.status_code == 400, response.text
    assert response.json()["error_code"] == "audio_generation.write_or_secret_field_forbidden"

    dispose_engine(database_url)


def test_execute_route_rejects_step_offload_public_ingress(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "skill_id": "content_summary_seo",
        "workflow_id": "content_summary_seo_completion",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "step_offload",
        "data_classification": "internal",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-step-offload-001",
        "trace_id": "trace-step-offload-001",
        "input": {"messages": [{"role": "user", "content": "return one short line"}]},
        "policy": {"allow_fallback": True},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-step-offload-001",
            nonce="nonce-step-offload-001",
            trace_id="tracestepoffload001000000000",
            body=body,
        )
    )

    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=headers,
    )

    assert response.status_code == 422

    dispose_engine(database_url)


def test_execute_route_rejects_unknown_policy_keys(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-policy-unknown-001",
        "input": {"messages": [{"role": "user", "content": "unknown policy key"}]},
        "policy": {"allow_fallback": True, "router_preset_id": "preset.alpha"},
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-policy-unknown-001",
                trace_id="tracepolicyunknown001000000000",
                body=body,
            )
        ),
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(item["loc"][-1] == "router_preset_id" for item in detail)

    dispose_engine(database_url)


def test_execute_route_rejects_local_governance_policy_keys(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-policy-governance-001",
        "input": {"messages": [{"role": "user", "content": "blocked policy key"}]},
        "policy": {
            "allow_fallback": True,
            "requires_confirm": True,
            "required_scope": "post.write",
            "tool_policy": {"allow_write": True},
            "approval_policy": {"mode": "proposal_only"},
            "apply_policy": {"post_write": True},
            "final_write_policy": {"allow": False},
        },
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-policy-governance-001",
                trace_id="tracepolicygovernance00100000",
                body=body,
            )
        ),
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    detail_json = json.dumps(detail)
    assert "local governance or final-write fields" in detail_json
    assert "requires_confirm" in detail_json
    assert "required_scope" in detail_json
    assert "tool_policy" in detail_json
    assert "approval_policy" in detail_json
    assert "apply_policy" in detail_json
    assert "final_write_policy" in detail_json

    dispose_engine(database_url)


def test_execute_route_rejects_reused_nonce(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-reused-nonce-001",
        "input": {"messages": [{"role": "user", "content": "replay should fail"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-reused-nonce-001",
            nonce="nonce-reused-001",
            trace_id="tracereusednonce00100000000000",
            body=body,
        )
    )

    first_response = client.post("/v1/runtime/execute", content=body, headers=headers)
    second_response = client.post("/v1/runtime/execute", content=body, headers=headers)

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json()["error_code"] == "auth.replay_blocked"

    dispose_engine(database_url)


def test_resolve_route_enforces_public_short_window_rate_limit(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "public_post_rate_limit_window_seconds": 60,
            "public_post_max_requests_per_window": 1,
        },
    )
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "input": {"messages": [{"role": "user", "content": "resolve once"}]},
    }
    first_body = json.dumps(payload).encode("utf-8")
    second_body = json.dumps(
        {
            **payload,
            "input": {"messages": [{"role": "user", "content": "resolve twice"}]},
        }
    ).encode("utf-8")

    first_response = client.post(
        "/v1/runtime/resolve",
        content=first_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/resolve",
                site_id="site_alpha",
                nonce="nonce-rate-limit-001",
                trace_id="traceratelimit0010000000000000",
                body=first_body,
            )
        ),
    )
    second_response = client.post(
        "/v1/runtime/resolve",
        content=second_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/resolve",
                site_id="site_alpha",
                nonce="nonce-rate-limit-002",
                trace_id="traceratelimit0020000000000000",
                body=second_body,
            )
        ),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json()["error_code"] == "auth.rate_limit_exceeded"

    dispose_engine(database_url)


def test_resolve_route_enforces_public_key_short_window_rate_limit(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "public_post_rate_limit_window_seconds": 60,
            "public_post_max_requests_per_window": 10,
            "public_post_max_requests_per_key_window": 1,
            "public_post_max_requests_per_ip_window": 10,
        },
    )
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "input": {"messages": [{"role": "user", "content": "key limited"}]},
    }
    first_body = json.dumps(payload).encode("utf-8")
    second_body = json.dumps(
        {
            **payload,
            "input": {"messages": [{"role": "user", "content": "key limited again"}]},
        }
    ).encode("utf-8")

    first_response = client.post(
        "/v1/runtime/resolve",
        content=first_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/resolve",
                site_id="site_alpha",
                key_id="key_default",
                nonce="nonce-key-rate-limit-001",
                trace_id="tracekeyratelimit00100000000",
                body=first_body,
            )
        ),
    )
    second_response = client.post(
        "/v1/runtime/resolve",
        content=second_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/resolve",
                site_id="site_alpha",
                key_id="key_default",
                nonce="nonce-key-rate-limit-002",
                trace_id="tracekeyratelimit00200000000",
                body=second_body,
            )
        ),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json()["error_code"] == "auth.rate_limit_exceeded"

    dispose_engine(database_url)


def test_resolve_route_enforces_public_ip_short_window_rate_limit(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "public_post_rate_limit_window_seconds": 60,
            "public_post_max_requests_per_window": 10,
            "public_post_max_requests_per_key_window": 10,
            "public_post_max_requests_per_ip_window": 1,
        },
    )
    first_payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "input": {"messages": [{"role": "user", "content": "ip limited first"}]},
    }
    second_payload = {
        "site_id": "site_beta",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "input": {"messages": [{"role": "user", "content": "ip limited second"}]},
    }
    first_body = json.dumps(first_payload).encode("utf-8")
    second_body = json.dumps(second_payload).encode("utf-8")

    first_response = client.post(
        "/v1/runtime/resolve",
        content=first_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/resolve",
                site_id="site_alpha",
                key_id="key_default",
                nonce="nonce-ip-rate-limit-001",
                trace_id="traceipratelimit001000000000",
                body=first_body,
            )
        ),
    )
    second_response = client.post(
        "/v1/runtime/resolve",
        content=second_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/resolve",
                site_id="site_beta",
                key_id="key_beta",
                nonce="nonce-ip-rate-limit-002",
                trace_id="traceipratelimit002000000000",
                body=second_body,
            )
        ),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json()["error_code"] == "auth.rate_limit_exceeded"

    dispose_engine(database_url)


def test_resolve_route_enforces_public_guard_cooldown_after_rejects(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "public_post_rate_limit_window_seconds": 600,
            "public_post_max_requests_per_window": 10,
            "public_post_max_requests_per_key_window": 10,
            "public_post_max_requests_per_ip_window": 10,
            "public_guard_cooldown_window_seconds": 3600,
            "public_guard_max_reject_events_per_site_window": 1,
            "public_guard_max_reject_events_per_key_window": 1,
            "public_guard_max_reject_events_per_ip_window": 1,
        },
    )
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "input": {"messages": [{"role": "user", "content": "cooldown me"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/resolve",
            site_id="site_alpha",
            key_id="key_default",
            nonce="nonce-cooldown-001",
            trace_id="tracecooldown0010000000000000",
            body=body,
        )
    )
    fresh_headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/resolve",
            site_id="site_alpha",
            key_id="key_default",
            nonce="nonce-cooldown-002",
            trace_id="tracecooldown0020000000000000",
            body=body,
        )
    )

    first_response = client.post("/v1/runtime/resolve", content=body, headers=headers)
    replay_response = client.post("/v1/runtime/resolve", content=body, headers=headers)
    cooldown_response = client.post(
        "/v1/runtime/resolve",
        content=body,
        headers=fresh_headers,
    )

    assert first_response.status_code == 200
    assert replay_response.status_code == 409
    assert replay_response.json()["error_code"] == "auth.replay_blocked"
    assert cooldown_response.status_code == 429
    assert cooldown_response.json()["error_code"] == "auth.rate_limit_exceeded"

    with get_session(database_url) as session:
        events = list(
            session.scalars(
                select(RuntimeGuardEvent)
                .where(RuntimeGuardEvent.site_id == "site_alpha")
                .order_by(RuntimeGuardEvent.id.asc())
            )
        )
    assert any(event.event_code == "auth.replay_blocked" for event in events)
    assert any(event.event_code == "auth.rate_limit_exceeded" for event in events)

    dispose_engine(database_url)


def test_resolve_route_logs_guard_persistence_failure_without_relaxing_auth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "input": {"messages": [{"role": "user", "content": "fail guard persistence"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/resolve",
            site_id="site_alpha",
            key_id="key_default",
            nonce="nonce-guard-persist-001",
            trace_id="traceguardpersist0010000000000",
            body=body,
        )
    )

    def raise_guard_write_failure(*args: object, **kwargs: object) -> None:
        raise RuntimeError("guard write failed")

    monkeypatch.setattr(
        security_module,
        "_record_runtime_guard_events",
        raise_guard_write_failure,
    )
    caplog.set_level(logging.ERROR, logger="app.core.security")

    first_response = client.post("/v1/runtime/resolve", content=body, headers=headers)
    replay_response = client.post("/v1/runtime/resolve", content=body, headers=headers)

    assert first_response.status_code == 200
    assert replay_response.status_code == 409
    assert replay_response.json()["error_code"] == "auth.replay_blocked"
    assert any(
        "runtime guard rejection persistence failed" in record.message
        and record.exc_info is not None
        and "auth.replay_blocked" in record.message
        and "site_alpha" in record.message
        for record in caplog.records
    )

    with get_session(database_url) as session:
        events = list(
            session.scalars(
                select(RuntimeGuardEvent)
                .where(RuntimeGuardEvent.site_id == "site_alpha")
                .order_by(RuntimeGuardEvent.id.asc())
            )
        )
    assert events == []

    dispose_engine(database_url)


def test_execute_route_keeps_idempotency_conflict_for_payload_mismatch(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    first_payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-conflict-001",
        "input": {"messages": [{"role": "user", "content": "first body"}]},
    }
    second_payload = {
        **first_payload,
        "input": {"messages": [{"role": "user", "content": "second body"}]},
    }
    first_body = json.dumps(first_payload).encode("utf-8")
    second_body = json.dumps(second_payload).encode("utf-8")
    first_headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-conflict-001",
            nonce="nonce-conflict-001",
            trace_id="traceconflict0010000000000000",
            body=first_body,
        )
    )
    second_headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-conflict-001",
            nonce="nonce-conflict-002",
            trace_id="traceconflict0020000000000000",
            body=second_body,
        )
    )

    first_response = client.post(
        "/v1/runtime/execute",
        content=first_body,
        headers=first_headers,
    )
    second_response = client.post(
        "/v1/runtime/execute",
        content=second_body,
        headers=second_headers,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json()["error_code"] == "runtime.idempotency_conflict"

    dispose_engine(database_url)


def test_execute_route_rejects_unprovisioned_site(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_gamma",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-unprovisioned-001",
        "input": {"messages": [{"role": "user", "content": "should fail"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_gamma",
            idempotency_key="idem-unprovisioned-001",
            trace_id="traceunprovisioned0010000000000",
            body=body,
        )
    )

    response = client.post("/v1/runtime/execute", content=body, headers=headers)

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.invalid_site"

    dispose_engine(database_url)


def test_execute_route_rejects_revoked_key(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
        key_status=SITE_API_KEY_STATUS_REVOKED,
    )
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-revoked-key-001",
        "input": {"messages": [{"role": "user", "content": "should fail"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-revoked-key-001",
            trace_id="tracerevokedkey0010000000000000",
            body=body,
        )
    )

    response = client.post("/v1/runtime/execute", content=body, headers=headers)

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.invalid_key"

    dispose_engine(database_url)


def test_execute_route_rejects_expired_key(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-expired-key-001",
        "input": {"messages": [{"role": "user", "content": "should fail"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-expired-key-001",
            trace_id="traceexpiredkey0010000000000000",
            body=body,
        )
    )

    response = client.post("/v1/runtime/execute", content=body, headers=headers)

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.invalid_key"

    dispose_engine(database_url)


def test_execute_route_rejects_invalid_idempotency_key(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "input": {"messages": [{"role": "user", "content": "should fail"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    invalid_idempotency_key = "bad key with spaces"
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key=invalid_idempotency_key,
            trace_id="traceinvalididem001000000000000",
            body=body,
        )
    )

    response = client.post("/v1/runtime/execute", content=body, headers=headers)

    assert response.status_code == 400
    assert response.json()["error_code"] == "auth.invalid_idempotency_key"

    dispose_engine(database_url)


def test_runtime_routes_reject_inactive_subscription(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
        subscription_status="past_due",
    )
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "input": {"messages": [{"role": "user", "content": "should fail"}]},
    }
    body = json.dumps(payload).encode("utf-8")

    resolve_response = client.post(
        "/v1/runtime/resolve",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/resolve",
                site_id="site_alpha",
                trace_id="tracesubinactive0010000000000",
                body=body,
            )
        ),
    )
    execute_response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-subinactive-001",
                trace_id="tracesubinactive0020000000000",
                body=body,
            )
        ),
    )

    assert resolve_response.status_code == 403
    assert resolve_response.json()["error_code"] == "commercial.subscription_inactive"
    assert execute_response.status_code == 403
    assert execute_response.json()["error_code"] == "commercial.subscription_inactive"

    dispose_engine(database_url)


def test_execute_route_rejects_entitlement_miss(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
        entitlements={
            "ability_families": ["vision"],
            "channels": ["openapi"],
            "execution_kinds": ["text"],
            "execution_tiers": ["cloud"],
            "data_classifications": ["internal"],
        },
    )
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "canonical_run_id": "wp_run_callback_dispatch_001",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-entitlement-miss-001",
        "input": {"messages": [{"role": "user", "content": "should fail"}]},
    }
    body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-entitlement-miss-001",
                trace_id="traceentitlementmiss00100000",
                body=body,
            )
        ),
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "commercial.entitlement_denied"

    dispose_engine(database_url)


def test_execute_route_rejects_batch_over_plan_limit(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )
    with get_session(database_url) as session:
        site = session.get(Site, "site_alpha")
        assert site is not None
        subscription = session.scalar(
            select(AccountSubscription).where(AccountSubscription.account_id == site.account_id)
        )
        assert subscription is not None
        plan_version = session.get(PlanVersion, subscription.plan_version_id)
        assert plan_version is not None
        plan_metadata = (
            plan_version.metadata_json if isinstance(plan_version.metadata_json, dict) else {}
        )
        plan_version.metadata_json = {
            **plan_metadata,
            "max_batch_items": 2,
        }
        session.commit()

    payload = {
        "site_id": "site_alpha",
        "ability_name": "workflow/media_alt_completion",
        "ability_family": "workflow",
        "workflow_id": "media_alt_completion",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "whole_run_offload",
        "data_classification": "internal",
        "timeout_seconds": 900,
        "retry_max": 1,
        "retention_ttl": 86400,
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "polling_preferred",
            "polling_interval_sec": 120,
        },
        "profile_id": "text.balanced",
        "idempotency_key": "idem-batch-limit-001",
        "trace_id": "tracebatchlimit001000000000000",
        "input": {
            "items": [
                {"attachment_id": 101, "title": "One"},
                {"attachment_id": 102, "title": "Two"},
                {"attachment_id": 103, "title": "Three"},
            ]
        },
        "policy": {"allow_fallback": True},
    }
    body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-batch-limit-001",
                nonce="nonce-batch-limit-001",
                trace_id="tracebatchlimit001000000000001",
                body=body,
            )
        ),
    )

    assert response.status_code == 429
    assert response.json()["error_code"] == "commercial.batch_limit_exceeded"

    dispose_engine(database_url)


def test_runtime_routes_allow_subscription_grace_with_runtime_downgrade(
    tmp_path: Path,
) -> None:
    runtime_queue = InMemoryRuntimeQueue()
    database_url, client = _build_client(tmp_path, runtime_queue=runtime_queue)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
        subscription_status="past_due",
        policy={
            "subscription": {
                "grace_period_days": 3,
                "downgrade_policy": {
                    "retry_max": 0,
                    "allow_fallback": False,
                    "task_backend": {
                        "enabled": False,
                        "mode": "inline",
                        "callback_mode": "polling_only",
                        "polling_interval_sec": 0,
                    },
                },
            }
        },
    )
    with get_session(database_url) as session:
        site = session.get(Site, "site_alpha")
        assert site is not None
        subscription = session.scalar(
            select(AccountSubscription).where(AccountSubscription.account_id == site.account_id)
        )
        assert subscription is not None
        subscription.current_period_end_at = datetime.now(UTC) - timedelta(days=1)
        session.commit()

    payload = {
        "site_id": "site_alpha",
        "ability_name": "workflow/media_nightly_image_optimize",
        "ability_family": "automation",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_pattern": "whole_run_offload",
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "polling_preferred",
            "polling_interval_sec": 60,
        },
        "profile_id": "text.balanced",
        "idempotency_key": "idem-sub-grace-001",
        "input": {"messages": [{"role": "user", "content": "grace path"}]},
    }
    body = json.dumps(payload).encode("utf-8")

    resolve_response = client.post(
        "/v1/runtime/resolve",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/resolve",
                site_id="site_alpha",
                trace_id="tracesubgrace00100000000000000",
                body=body,
            )
        ),
    )
    execute_response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-sub-grace-001",
                trace_id="tracesubgrace00200000000000000",
                body=body,
            )
        ),
    )

    assert resolve_response.status_code == 200
    assert (
        resolve_response.json()["data"]["policy"]["commercial_policy"]["decision_code"]
        == "commercial.subscription_grace"
    )
    assert resolve_response.json()["data"]["task_backend"]["enabled"] is False
    assert resolve_response.json()["data"]["run_lifecycle"]["queue_mode"] == "inline"

    assert execute_response.status_code == 200
    assert execute_response.json()["data"]["status"] == "succeeded"
    assert execute_response.json()["data"]["task_backend"]["enabled"] is False
    assert execute_response.json()["data"]["run_lifecycle"]["queue_mode"] == "inline"

    dispose_engine(database_url)


def test_execute_route_rejects_budget_exhaustion(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
        budgets={"max_runs_per_period": 1},
    )
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "canonical_run_id": "wp_run_callback_dispatch_001",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-budget-001",
        "input": {"messages": [{"role": "user", "content": "first allowed"}]},
    }
    first_body = json.dumps(payload).encode("utf-8")
    second_payload = {**payload, "idempotency_key": "idem-budget-002"}
    second_body = json.dumps(second_payload).encode("utf-8")

    first_response = client.post(
        "/v1/runtime/execute",
        content=first_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-budget-001",
                trace_id="tracebudget001000000000000000",
                body=first_body,
            )
        ),
    )
    second_response = client.post(
        "/v1/runtime/execute",
        content=second_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-budget-002",
                trace_id="tracebudget002000000000000000",
                body=second_body,
            )
        ),
    )

    assert first_response.status_code == 200
    assert first_response.json()["data"]["status"] == "succeeded"
    assert second_response.status_code == 429
    assert second_response.json()["error_code"] == "commercial.quota_exceeded"

    dispose_engine(database_url)


def test_execute_route_allows_budget_grace_with_runtime_downgrade(tmp_path: Path) -> None:
    runtime_queue = InMemoryRuntimeQueue()
    database_url, client = _build_client(tmp_path, runtime_queue=runtime_queue)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
        budgets={"max_runs_per_period": 1},
        concurrency={"max_active_runs": 2},
        policy={
            "budgets": {
                "runs": {
                    "grace_requests": 1,
                    "downgrade_policy": {
                        "retry_max": 0,
                        "allow_fallback": False,
                        "task_backend": {
                            "enabled": False,
                            "mode": "inline",
                            "callback_mode": "polling_only",
                            "polling_interval_sec": 0,
                        },
                    },
                }
            }
        },
    )
    request_payload = {
        "site_id": "site_alpha",
        "ability_name": "workflow/media_nightly_image_optimize",
        "ability_family": "automation",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_pattern": "whole_run_offload",
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "polling_preferred",
            "polling_interval_sec": 60,
        },
        "profile_id": "text.balanced",
        "input": {"messages": [{"role": "user", "content": "budget grace"}]},
    }
    first_body = json.dumps({**request_payload, "idempotency_key": "idem-budget-grace-001"}).encode(
        "utf-8"
    )
    second_body = json.dumps(
        {**request_payload, "idempotency_key": "idem-budget-grace-002"}
    ).encode("utf-8")
    third_body = json.dumps({**request_payload, "idempotency_key": "idem-budget-grace-003"}).encode(
        "utf-8"
    )

    first_response = client.post(
        "/v1/runtime/execute",
        content=first_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-budget-grace-001",
                trace_id="tracebudgetgrace001000000000",
                body=first_body,
            )
        ),
    )
    second_response = client.post(
        "/v1/runtime/execute",
        content=second_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-budget-grace-002",
                trace_id="tracebudgetgrace002000000000",
                body=second_body,
            )
        ),
    )
    third_response = client.post(
        "/v1/runtime/execute",
        content=third_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-budget-grace-003",
                trace_id="tracebudgetgrace003000000000",
                body=third_body,
            )
        ),
    )

    assert first_response.status_code == 200
    assert first_response.json()["data"]["status"] == "queued"
    assert first_response.json()["data"]["task_backend"]["enabled"] is True

    assert second_response.status_code == 200
    assert second_response.json()["data"]["status"] == "succeeded"
    assert second_response.json()["data"]["task_backend"]["enabled"] is False
    assert second_response.json()["data"]["run_lifecycle"]["queue_mode"] == "inline"

    assert third_response.status_code == 429
    assert third_response.json()["error_code"] == "commercial.quota_exceeded"

    dispose_engine(database_url)


def test_execute_route_rejects_concurrency_exhaustion(tmp_path: Path) -> None:
    runtime_queue = InMemoryRuntimeQueue()
    database_url, client = _build_client(tmp_path, runtime_queue=runtime_queue)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
        concurrency={"max_active_runs": 2},
    )
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
        concurrency={"max_active_runs": 1},
    )
    payload = {
        "site_id": "site_alpha",
        "ability_name": "workflow/media_nightly_image_optimize",
        "ability_family": "automation",
        "skill_id": "media_nightly_optimize",
        "workflow_id": "media_nightly_image_optimize",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "whole_run_offload",
        "data_classification": "internal",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-concurrency-001",
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "polling_preferred",
            "polling_interval_sec": 120,
        },
        "input": {"messages": [{"role": "user", "content": "queue first"}]},
    }
    first_body = json.dumps(payload).encode("utf-8")
    second_payload = {**payload, "idempotency_key": "idem-concurrency-002"}
    second_body = json.dumps(second_payload).encode("utf-8")

    first_response = client.post(
        "/v1/runtime/execute",
        content=first_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-concurrency-001",
                trace_id="traceconcurrency001000000000",
                body=first_body,
            )
        ),
    )
    second_response = client.post(
        "/v1/runtime/execute",
        content=second_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-concurrency-002",
                trace_id="traceconcurrency002000000000",
                body=second_body,
            )
        ),
    )

    assert first_response.status_code == 200
    assert first_response.json()["data"]["status"] == "queued"
    assert second_response.status_code == 429
    assert second_response.json()["error_code"] == "commercial.concurrency_exceeded"

    dispose_engine(database_url)


def test_execute_route_rejects_payloads_over_app_limit(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    oversized_content = "x" * (1_048_576 + 1)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-payload-too-large-001",
        "input": {"messages": [{"role": "user", "content": oversized_content}]},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-payload-too-large-001",
            trace_id="tracepayloadtoolarge001000000",
            body=body,
        )
    )

    response = client.post("/v1/runtime/execute", content=body, headers=headers)

    assert response.status_code == 413
    assert response.json()["error_code"] == "auth.payload_too_large"

    dispose_engine(database_url)


def test_execute_route_enqueues_whole_run_offload_and_worker_completes_it(
    tmp_path: Path,
) -> None:
    runtime_queue = InMemoryRuntimeQueue()
    database_url, client = _build_client(tmp_path, runtime_queue=runtime_queue)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "workflow/media_nightly_image_optimize",
        "skill_id": "media_nightly_optimize",
        "workflow_id": "media_nightly_image_optimize",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "whole_run_offload",
        "data_classification": "internal",
        "timeout_seconds": 1800,
        "retry_max": 2,
        "retention_ttl": 86400,
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "polling_preferred",
            "polling_interval_sec": 120,
        },
        "profile_id": "text.balanced",
        "idempotency_key": "idem-nightly-001",
        "trace_id": "trace-nightly-001",
        "input": {"messages": [{"role": "user", "content": "scan media and propose alt text"}]},
        "policy": {"allow_fallback": True},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-nightly-001",
            trace_id="tracenightly001000000000000000",
            body=body,
        )
    )

    execute_response = client.post("/v1/runtime/execute", content=body, headers=headers)
    assert execute_response.status_code == 200
    execute_payload = execute_response.json()["data"]
    assert execute_payload["status"] == "queued"
    assert execute_payload["provider_call_count"] == 0
    assert execute_payload["task_backend"]["status"] == "queued"
    assert execute_payload["run_lifecycle"]["phase"] == "queued"
    assert execute_payload["run_lifecycle"]["queue_mode"] == "queue_backed"
    assert execute_payload["result"] == {}

    run_id = str(execute_payload["run_id"])
    result_response = client.get(
        f"/v1/runs/{run_id}/result",
        headers=build_auth_headers(
            "GET",
            f"/v1/runs/{run_id}/result",
            site_id="site_alpha",
            trace_id="tracenightlyresult0010000000000",
        ),
    )
    assert result_response.status_code == 409
    assert result_response.json()["error_code"] == "runtime.result_not_ready"

    worker = RuntimeService(
        database_url,
        settings=_runtime_service_settings(database_url),
        runtime_queue=runtime_queue,
    )
    processed = worker.process_next_queued_run(timeout_seconds=1)
    assert processed == {
        "run_id": run_id,
        "status": "succeeded",
        "trace_id": "trace-nightly-001",
    }

    run_response = client.get(
        f"/v1/runs/{run_id}",
        headers=build_auth_headers(
            "GET",
            f"/v1/runs/{run_id}",
            site_id="site_alpha",
            trace_id="tracenightlystatus001000000000",
        ),
    )
    assert run_response.status_code == 200
    assert run_response.json()["data"]["status"] == "succeeded"
    assert run_response.json()["data"]["task_backend"]["status"] == "completed"
    assert run_response.json()["data"]["run_lifecycle"]["phase"] == "terminal"

    final_result_response = client.get(
        f"/v1/runs/{run_id}/result",
        headers=build_auth_headers(
            "GET",
            f"/v1/runs/{run_id}/result",
            site_id="site_alpha",
            trace_id="tracenightlyresult0020000000000",
        ),
    )
    assert final_result_response.status_code == 200
    assert (
        final_result_response.json()["data"]["execution_context"]["execution_pattern"]
        == "whole_run_offload"
    )
    assert final_result_response.json()["data"]["task_backend"]["status"] == "completed"
    assert final_result_response.json()["data"]["run_lifecycle"]["retention"]["state"] == (
        "retained"
    )
    assert final_result_response.json()["data"]["provider_calls"][0]["provider_id"] == ("openai")

    dispose_engine(database_url)


def test_cancel_route_cancels_queued_whole_run_before_worker_claim(tmp_path: Path) -> None:
    runtime_queue = InMemoryRuntimeQueue()
    database_url, client = _build_client(tmp_path, runtime_queue=runtime_queue)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "workflow/media_nightly_image_optimize",
        "ability_family": "automation",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "whole_run_offload",
        "data_classification": "internal",
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "polling_preferred",
            "polling_interval_sec": 120,
        },
        "profile_id": "text.balanced",
        "idempotency_key": "idem-nightly-cancel-001",
        "input": {"messages": [{"role": "user", "content": "queue then cancel"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    execute_response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-nightly-cancel-001",
                trace_id="tracequeuecancel0010000000000",
                body=body,
            )
        ),
    )

    assert execute_response.status_code == 200
    run_id = str(execute_response.json()["data"]["run_id"])
    assert execute_response.json()["data"]["run_lifecycle"]["cancel"] == {
        "supported": True,
        "state": "available",
        "requested_at": None,
        "canceled_at": None,
    }

    cancel_response = client.post(
        f"/v1/runs/{run_id}/cancel",
        content=b"",
        headers=build_auth_headers(
            "POST",
            f"/v1/runs/{run_id}/cancel",
            site_id="site_alpha",
            idempotency_key="idem-nightly-cancel-control-001",
            trace_id="tracequeuecancel0020000000000",
            body=b"",
        ),
    )

    assert cancel_response.status_code == 200
    cancel_payload = cancel_response.json()["data"]
    assert cancel_payload["status"] == "canceled"
    assert cancel_payload["error_code"] == "runtime.canceled"
    assert cancel_payload["task_backend"]["status"] == "canceled"
    assert cancel_payload["run_lifecycle"]["cancel"]["state"] == "canceled"
    assert cancel_payload["run_lifecycle"]["terminal_status"] == "canceled"

    worker = RuntimeService(
        database_url,
        settings=_runtime_service_settings(database_url),
        runtime_queue=runtime_queue,
    )
    assert worker.process_next_queued_run(timeout_seconds=1) is None

    run_response = client.get(
        f"/v1/runs/{run_id}",
        headers=build_auth_headers(
            "GET",
            f"/v1/runs/{run_id}",
            site_id="site_alpha",
            trace_id="tracequeuecancel0030000000000",
        ),
    )
    assert run_response.status_code == 200
    assert run_response.json()["data"]["status"] == "canceled"

    result_response = client.get(
        f"/v1/runs/{run_id}/result",
        headers=build_auth_headers(
            "GET",
            f"/v1/runs/{run_id}/result",
            site_id="site_alpha",
            trace_id="tracequeuecancel0040000000000",
        ),
    )
    assert result_response.status_code == 409
    assert result_response.json()["error_code"] == "runtime.result_not_ready"

    dispose_engine(database_url)


def test_cancel_route_rejects_inline_runs(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-inline-cancel-001",
        "input": {"messages": [{"role": "user", "content": "inline run"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    execute_response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-inline-cancel-001",
                trace_id="traceinlinecancel00100000000",
                body=body,
            )
        ),
    )

    assert execute_response.status_code == 200
    run_id = str(execute_response.json()["data"]["run_id"])

    cancel_response = client.post(
        f"/v1/runs/{run_id}/cancel",
        content=b"",
        headers=build_auth_headers(
            "POST",
            f"/v1/runs/{run_id}/cancel",
            site_id="site_alpha",
            idempotency_key="idem-inline-cancel-control-001",
            trace_id="traceinlinecancel00200000000",
            body=b"",
        ),
    )

    assert cancel_response.status_code == 409
    assert cancel_response.json()["error_code"] == "runtime.cancel_not_allowed"

    dispose_engine(database_url)


def test_execute_route_worker_can_drain_multiple_queued_runs_in_one_poll_cycle(
    tmp_path: Path,
) -> None:
    runtime_queue = InMemoryRuntimeQueue()
    database_url, client = _build_client(tmp_path, runtime_queue=runtime_queue)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
        concurrency={"max_active_runs": 2},
    )

    def queue_request(idempotency_key: str, trace_id: str, prompt: str) -> str:
        payload = {
            "site_id": "site_alpha",
            "ability_name": "workflow/media_nightly_image_optimize",
            "skill_id": "media_nightly_optimize",
            "workflow_id": "media_nightly_image_optimize",
            "contract_version": "v1",
            "channel": "openapi",
            "execution_kind": "text",
            "execution_tier": "cloud",
            "execution_pattern": "whole_run_offload",
            "data_classification": "internal",
            "timeout_seconds": 1800,
            "retry_max": 2,
            "retention_ttl": 86400,
            "task_backend": {
                "enabled": True,
                "mode": "polling",
                "callback_mode": "polling_preferred",
                "polling_interval_sec": 120,
            },
            "profile_id": "text.balanced",
            "idempotency_key": idempotency_key,
            "trace_id": trace_id,
            "input": {"messages": [{"role": "user", "content": prompt}]},
            "policy": {"allow_fallback": True},
        }
        body = json.dumps(payload).encode("utf-8")
        response = client.post(
            "/v1/runtime/execute",
            content=body,
            headers=merge_json_headers(
                build_auth_headers(
                    "POST",
                    "/v1/runtime/execute",
                    site_id="site_alpha",
                    idempotency_key=idempotency_key,
                    trace_id=f"{trace_id}000000000000000000",
                    body=body,
                )
            ),
        )

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "queued"
        return str(response.json()["data"]["run_id"])

    first_run_id = queue_request(
        "idem-nightly-batch-001",
        "trace-nightly-batch-001",
        "first queued batch run",
    )
    second_run_id = queue_request(
        "idem-nightly-batch-002",
        "trace-nightly-batch-002",
        "second queued batch run",
    )

    worker = RuntimeService(
        database_url,
        settings=_runtime_service_settings(database_url),
        runtime_queue=runtime_queue,
    )
    processed = worker.process_queued_runs(max_runs=2, timeout_seconds=1)
    assert processed == [
        {
            "run_id": first_run_id,
            "status": "succeeded",
            "trace_id": "trace-nightly-batch-001",
        },
        {
            "run_id": second_run_id,
            "status": "succeeded",
            "trace_id": "trace-nightly-batch-002",
        },
    ]

    for run_id in (first_run_id, second_run_id):
        run_response = client.get(
            f"/v1/runs/{run_id}",
            headers=build_auth_headers(
                "GET",
                f"/v1/runs/{run_id}",
                site_id="site_alpha",
                trace_id=f"trace-status-{run_id[-8:]}",
            ),
        )
        result_response = client.get(
            f"/v1/runs/{run_id}/result",
            headers=build_auth_headers(
                "GET",
                f"/v1/runs/{run_id}/result",
                site_id="site_alpha",
                trace_id=f"trace-result-{run_id[-8:]}",
            ),
        )
        assert run_response.status_code == 200
        assert result_response.status_code == 200
        assert run_response.json()["data"]["task_backend"]["status"] == "completed"
        assert result_response.json()["data"]["task_backend"]["status"] == "completed"

    dispose_engine(database_url)


def test_callback_delivery_worker_dispatches_terminal_run_payload(
    tmp_path: Path,
    allow_example_callback_dns: None,
) -> None:
    callback_requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        callback_requests.append(
            {
                "url": str(request.url),
                "headers": dict(request.headers),
                "payload": json.loads(request.content.decode("utf-8")),
            }
        )
        return httpx.Response(204)

    callback_dispatcher = HttpRuntimeCallbackDispatcher(
        transport=httpx.MockTransport(handler),
    )
    database_url, client = _build_client(
        tmp_path,
        callback_dispatcher=callback_dispatcher,
    )
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
        site_metadata=_runtime_callback_metadata(
            "https://example.com/runtime",
            callback_id="runtime-terminal-dispatch",
        ),
    )
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "canonical_run_id": "wp_run_callback_dispatch_001",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "polling_preferred",
        },
        "idempotency_key": "idem-callback-dispatch-001",
        "input": {"messages": [{"role": "user", "content": "send callback later"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    execute_response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-callback-dispatch-001",
                trace_id="tracecallbackdispatch0010000",
                body=body,
            )
        ),
    )

    assert execute_response.status_code == 200
    run_id = str(execute_response.json()["data"]["run_id"])
    assert execute_response.json()["data"]["canonical_run_id"] == "wp_run_callback_dispatch_001"
    assert execute_response.json()["data"]["run_lifecycle"]["callback"]["dispatch_status"] == (
        "pending"
    )
    assert callback_requests == []

    worker = RuntimeService(
        database_url,
        settings=_runtime_service_settings(database_url),
        callback_dispatcher=callback_dispatcher,
        callback_max_attempts=3,
        callback_retry_backoff_seconds=0,
    )
    dispatched = worker.dispatch_pending_callbacks(max_callbacks=1)

    assert dispatched == [
        {
            "run_id": run_id,
            "callback_status": "delivered",
            "trace_id": execute_response.json()["data"]["trace_id"],
            "status_code": 204,
        }
    ]
    assert len(callback_requests) == 1
    assert callback_requests[0]["url"] == "https://example.com/runtime"
    assert callback_requests[0]["headers"]["x-npcink-cloud-event"] == "runtime.run.terminal"
    assert callback_requests[0]["headers"]["x-npcink-callback-id"] == "runtime-terminal-dispatch"
    assert callback_requests[0]["headers"]["x-npcink-signature"] != ""
    assert callback_requests[0]["headers"]["x-npcink-timestamp"] != ""
    assert callback_requests[0]["payload"]["run_id"] == run_id
    assert callback_requests[0]["payload"]["canonical_run_id"] == "wp_run_callback_dispatch_001"
    assert callback_requests[0]["payload"]["status"] == "succeeded"

    run_response = client.get(
        f"/v1/runs/{run_id}",
        headers=build_auth_headers(
            "GET",
            f"/v1/runs/{run_id}",
            site_id="site_alpha",
            trace_id="tracecallbackdispatch0020000",
        ),
    )
    assert run_response.status_code == 200
    assert run_response.json()["data"]["canonical_run_id"] == "wp_run_callback_dispatch_001"
    assert run_response.json()["data"]["run_lifecycle"]["callback"]["dispatch_status"] == (
        "delivered"
    )
    assert run_response.json()["data"]["run_lifecycle"]["callback"]["attempt_count"] == 1
    assert run_response.json()["data"]["run_lifecycle"]["callback"]["delivered_at"] is not None

    dispose_engine(database_url)


def test_callback_delivery_worker_retries_retryable_failures(
    tmp_path: Path,
    allow_example_callback_dns: None,
) -> None:
    attempt_counter = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        attempt_counter["count"] += 1
        if attempt_counter["count"] == 1:
            return httpx.Response(500)
        return httpx.Response(202)

    callback_dispatcher = HttpRuntimeCallbackDispatcher(
        transport=httpx.MockTransport(handler),
    )
    database_url, client = _build_client(
        tmp_path,
        callback_dispatcher=callback_dispatcher,
        settings_overrides={
            "runtime_callback_max_attempts": 2,
            "runtime_callback_retry_backoff_seconds": 0,
        },
    )
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
        site_metadata=_runtime_callback_metadata(
            "https://example.com/retry",
            callback_id="runtime-terminal-retry",
        ),
    )
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "polling_preferred",
        },
        "idempotency_key": "idem-callback-retry-001",
        "input": {"messages": [{"role": "user", "content": "retry callback"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    execute_response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-callback-retry-001",
                trace_id="tracecallbackretry001000000",
                body=body,
            )
        ),
    )
    assert execute_response.status_code == 200
    run_id = str(execute_response.json()["data"]["run_id"])

    worker = RuntimeService(
        database_url,
        settings=_runtime_service_settings(database_url),
        callback_dispatcher=callback_dispatcher,
        callback_max_attempts=2,
        callback_retry_backoff_seconds=0,
    )
    first_attempt = worker.dispatch_pending_callbacks(max_callbacks=1)
    second_attempt = worker.dispatch_pending_callbacks(max_callbacks=1)

    assert first_attempt == [
        {
            "run_id": run_id,
            "callback_status": "pending",
            "trace_id": execute_response.json()["data"]["trace_id"],
        }
    ]
    assert second_attempt == [
        {
            "run_id": run_id,
            "callback_status": "delivered",
            "trace_id": execute_response.json()["data"]["trace_id"],
            "status_code": 202,
        }
    ]
    assert attempt_counter["count"] == 2

    run_response = client.get(
        f"/v1/runs/{run_id}",
        headers=build_auth_headers(
            "GET",
            f"/v1/runs/{run_id}",
            site_id="site_alpha",
            trace_id="tracecallbackretry002000000",
        ),
    )
    assert run_response.status_code == 200
    assert run_response.json()["data"]["run_lifecycle"]["callback"]["dispatch_status"] == (
        "delivered"
    )
    assert run_response.json()["data"]["run_lifecycle"]["callback"]["attempt_count"] == 2
    assert run_response.json()["data"]["run_lifecycle"]["callback"]["last_error_code"] == ""

    dispose_engine(database_url)


def test_execute_route_rejects_public_callback_url_override_without_registration(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "callback_url": "https://example.com/runtime",
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "terminal_callback_required",
        },
        "idempotency_key": "idem-callback-contract-001",
        "input": {"messages": [{"role": "user", "content": "require registration"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-callback-contract-001",
                trace_id="tracecallbackcontract0010000",
                body=body,
            )
        ),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "runtime.callback_not_registered"

    dispose_engine(database_url)


def test_execute_route_rejects_contract_timeout_above_cloud_ceiling(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "timeout_seconds": 3601,
        "idempotency_key": "idem-timeout-contract-001",
        "input": {"messages": [{"role": "user", "content": "too much time"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-timeout-contract-001",
                trace_id="tracetimeoutcontract001000",
                body=body,
            )
        ),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "runtime.contract_timeout_exceeded"

    dispose_engine(database_url)


def test_execute_route_rejects_sensitive_data_without_no_store(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "data_classification": "pii",
        "storage_mode": "result_only",
        "idempotency_key": "idem-sensitive-result-only-001",
        "input": {"messages": [{"role": "user", "content": "private customer note"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-sensitive-result-only-001",
                trace_id="tracesensitive0010000000000000",
                body=body,
            )
        ),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "runtime.sensitive_data_requires_no_store"

    dispose_engine(database_url)


def test_execute_route_rejects_secret_like_runtime_input(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-secret-detected-001",
        "input": {
            "messages": [{"role": "user", "content": "summarize this draft"}],
            "provider_key": "sk-testtesttesttesttesttesttest",
        },
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-secret-detected-001",
                trace_id="tracesecretdetected00100000",
                body=body,
            )
        ),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "runtime.secret_input_detected"

    dispose_engine(database_url)


def test_execute_route_rejects_unclassified_personal_data(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-pii-detected-001",
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": "Draft a reply for customer alice@example.com",
                }
            ]
        },
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-pii-detected-001",
                trace_id="tracepiidetected0010000000",
                body=body,
            )
        ),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "runtime.pii_classification_required"

    dispose_engine(database_url)


def test_resolve_route_rejects_sensitive_data_without_no_store(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "data_classification": "pii",
        "storage_mode": "result_only",
        "input": {"messages": [{"role": "user", "content": "private customer note"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/resolve",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/resolve",
                site_id="site_alpha",
                trace_id="tracesensitiveresolve00100000",
                body=body,
            )
        ),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "runtime.sensitive_data_requires_no_store"

    dispose_engine(database_url)


def test_execute_route_pii_no_store_omits_persisted_payloads(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "data_classification": "pii",
        "storage_mode": "no_store",
        "idempotency_key": "idem-sensitive-no-store-001",
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": "private customer note from alice@example.com",
                }
            ]
        },
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-sensitive-no-store-001",
                trace_id="tracesensitive0020000000000000",
                body=body,
            )
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["result"]["output_text"].startswith("[hosted:")
    run_id = response.json()["data"]["run_id"]
    with get_session(database_url) as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        assert run.data_classification == "pii"
        assert run.input_json == {}
        assert run.result_json == {"stored": False, "status": "omitted"}

    dispose_engine(database_url)


def test_execute_route_secret_data_is_excluded_from_hosted_runtime(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "data_classification": "secret",
        "storage_mode": "no_store",
        "idempotency_key": "idem-secret-no-store-001",
        "input": {"messages": [{"role": "user", "content": "rotate api secret"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-secret-no-store-001",
                trace_id="tracesecret001000000000000000",
                body=body,
            )
        ),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "runtime.secret_data_forbidden"

    dispose_engine(database_url)


def test_execute_route_result_only_storage_omits_persisted_input_payload(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "storage_mode": "result_only",
        "idempotency_key": "idem-storage-result-only-001",
        "input": {"messages": [{"role": "user", "content": "keep only result"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-storage-result-only-001",
                trace_id="tracestorageresultonly001",
                body=body,
            )
        ),
    )

    assert response.status_code == 200
    run_id = response.json()["data"]["run_id"]
    with get_session(database_url) as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        assert run.input_json == {}
        assert isinstance(run.result_json, dict)

    dispose_engine(database_url)


def test_execute_route_no_store_omits_persisted_input_payload(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "storage_mode": "no_store",
        "idempotency_key": "idem-storage-no-store-001",
        "input": {"messages": [{"role": "user", "content": "store nothing"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-storage-no-store-001",
                trace_id="tracestoragenostore0010000",
                body=body,
            )
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["result"]["output_text"].startswith("[hosted:")
    run_id = response.json()["data"]["run_id"]
    with get_session(database_url) as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        assert run.input_json == {}
        assert run.result_json == {"stored": False, "status": "omitted"}

    dispose_engine(database_url)


def test_execute_route_rejects_plaintext_registered_callback_secret_without_ciphertext(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
        site_metadata={
            "runtime_callbacks": {
                "terminal": {
                    "enabled": True,
                    "callback_url": "https://example.com/runtime",
                    "key_id": "runtime_callback_key",
                    "secret": "legacy-plaintext-secret",
                    "callback_id": "runtime_terminal",
                }
            }
        },
    )
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "terminal_callback_required",
        },
        "idempotency_key": "idem-callback-plaintext-001",
        "input": {"messages": [{"role": "user", "content": "require ciphertext"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-callback-plaintext-001",
                trace_id="tracecallbackplaintext001000",
                body=body,
            )
        ),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "runtime.callback_not_registered"
    assert "re-saved as ciphertext" in response.json()["message"]

    dispose_engine(database_url)


def test_resolve_route_returns_execution_context(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "skill_id": "content_summary_seo",
        "workflow_id": "content_summary_seo_completion",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "data_classification": "internal",
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "polling_preferred",
            "polling_interval_sec": 120,
        },
        "profile_id": "text.balanced",
        "input": {"messages": [{"role": "user", "content": "resolve me"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/resolve",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/resolve",
                site_id="site_alpha",
                trace_id="traceresolve00100000000000000000",
                body=body,
            )
        ),
    )

    assert response.status_code == 200
    assert response.json()["data"]["execution_context"] == {
        "skill_id": "content_summary_seo",
        "workflow_id": "content_summary_seo_completion",
        "contract_version": "v1",
        "ability_family": "workflow",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "data_classification": "internal",
        "storage_mode": "result_only",
    }
    assert response.json()["data"]["task_backend"] == {
        "enabled": True,
        "mode": "polling",
        "callback_mode": "polling_preferred",
        "polling_interval_sec": 120,
        "callback_url": "",
        "timeout_seconds": 0,
        "retry_max": 0,
        "retention_ttl": 0,
        "status": "running",
    }
    assert response.json()["data"]["run_lifecycle"] == {
        "phase": "requested",
        "next_phase": "processing",
        "queue_mode": "inline",
        "cancel": {
            "supported": False,
            "state": "not_available",
            "requested_at": None,
            "canceled_at": None,
        },
        "callback": {
            "requested": False,
            "mode": "polling_preferred",
            "url_present": False,
            "dispatch_status": "not_requested",
            "attempt_count": 0,
            "last_attempt_at": None,
            "delivered_at": None,
            "next_attempt_at": None,
            "last_error_code": "",
        },
        "retention": {
            "ttl_seconds": 0,
            "state": "disabled",
        },
    }

    dispose_engine(database_url)


def test_execute_route_falls_back_to_next_candidate(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-balanced-002",
        "input": {
            "messages": [{"role": "user", "content": "fallback request"}],
            "simulate_error_for_instances": ["openai-us-east-text-balanced"],
        },
        "policy": {"allow_fallback": True},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-balanced-002",
            trace_id="tracebalanced0020000000000000000",
            body=body,
        )
    )
    response = client.post("/v1/runtime/execute", content=body, headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["fallback_used"] is True
    assert payload["data"]["instance_id"] == "openai-us-east-text-economy"
    assert payload["data"]["provider_call_count"] == 2

    result_response = client.get(
        f"/v1/runs/{payload['data']['run_id']}/result",
        headers=build_auth_headers(
            "GET",
            f"/v1/runs/{payload['data']['run_id']}/result",
            site_id="site_alpha",
            trace_id="tracebalanced0020000000000000001",
        ),
    )
    provider_calls = result_response.json()["data"]["provider_calls"]
    assert len(provider_calls) == 2
    assert provider_calls[0]["error_code"] == "provider.simulated_error"
    assert provider_calls[1]["fallback_used"] is True

    dispose_engine(database_url)


def test_run_result_route_returns_expired_after_retention_window(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-retention-expired-001",
        "retention_ttl": 60,
        "input": {"messages": [{"role": "user", "content": "expire result"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    execute_response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-retention-expired-001",
                trace_id="traceretentionexpired0010000000",
                body=body,
            )
        ),
    )
    run_id = str(execute_response.json()["data"]["run_id"])

    with get_session(database_url) as session:
        run = session.scalar(select(RunRecord).where(RunRecord.run_id == run_id))
        assert run is not None
        run.retention_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        session.commit()

    run_response = client.get(
        f"/v1/runs/{run_id}",
        headers=build_auth_headers(
            "GET",
            f"/v1/runs/{run_id}",
            site_id="site_alpha",
            trace_id="traceretentionexpired0020000000",
        ),
    )
    result_response = client.get(
        f"/v1/runs/{run_id}/result",
        headers=build_auth_headers(
            "GET",
            f"/v1/runs/{run_id}/result",
            site_id="site_alpha",
            trace_id="traceretentionexpired0030000000",
        ),
    )

    assert run_response.status_code == 200
    assert run_response.json()["data"]["run_lifecycle"]["retention"]["state"] == "expired"
    assert result_response.status_code == 410
    assert result_response.json()["error_code"] == "runtime.result_expired"

    dispose_engine(database_url)


def test_execute_route_rejects_invalid_signature(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "input": {"messages": [{"role": "user", "content": "bad sig"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-invalid-signature",
            trace_id="traceinvalidsig00000000000000000",
            body=body,
        ),
        extra_headers={"X-Npcink-Signature": "deadbeef"},
    )

    response = client.post("/v1/runtime/execute", content=body, headers=headers)

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.invalid_signature"

    dispose_engine(database_url)


def test_execute_route_rejects_signature_signed_with_stored_secret_hash(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "input": {"messages": [{"role": "user", "content": "hash forgery"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    timestamp = str(int(datetime.now(UTC).timestamp()))
    nonce = "nonce-stolen-hash-signature"
    idempotency_key = "idem-stolen-hash-signature"
    traceparent = build_auth_headers(
        "POST",
        "/v1/runtime/execute",
        site_id="site_alpha",
        trace_id="tracestolenhash00000000000000000",
        body=body,
    )["traceparent"]
    with get_session(database_url) as session:
        api_key = session.get(SiteApiKey, "key_default")
        assert api_key is not None
        stolen_hash = str(api_key.secret_hash)
    canonical_request = build_canonical_request(
        method="POST",
        path="/v1/runtime/execute",
        query="",
        site_id="site_alpha",
        key_id="key_default",
        timestamp=timestamp,
        nonce=nonce,
        idempotency_key=idempotency_key,
        traceparent=traceparent,
        body_digest=build_body_digest(body),
    )

    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            {
                "X-Npcink-Site-Id": "site_alpha",
                "X-Npcink-Key-Id": "key_default",
                "X-Npcink-Timestamp": timestamp,
                "X-Npcink-Nonce": nonce,
                "X-Npcink-Signature": build_hmac_signature(stolen_hash, canonical_request),
                "Idempotency-Key": idempotency_key,
                "traceparent": traceparent,
            }
        ),
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.invalid_signature"

    dispose_engine(database_url)


def test_execute_route_rejects_key_without_signing_secret_ciphertext(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    with get_session(database_url) as session:
        api_key = session.get(SiteApiKey, "key_default")
        assert api_key is not None
        api_key.signing_secret_ciphertext = None
        session.commit()
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "input": {"messages": [{"role": "user", "content": "missing signing secret"}]},
    }
    body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-missing-signing-secret",
                trace_id="tracemissingsigningsecret0000000",
                body=body,
            )
        ),
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.invalid_key"

    dispose_engine(database_url)


def test_run_route_is_scoped_to_authenticated_site(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-site-scope-001",
        "input": {"messages": [{"role": "user", "content": "scoped read"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-site-scope-001",
                trace_id="tracesitescope001000000000000000",
                body=body,
            )
        ),
    )
    run_id = response.json()["data"]["run_id"]

    run_response = client.get(
        f"/v1/runs/{run_id}",
        headers=build_auth_headers(
            "GET",
            f"/v1/runs/{run_id}",
            site_id="site_beta",
            key_id="key_beta",
            trace_id="tracesitescope002000000000000000",
        ),
    )

    assert run_response.status_code == 404
    assert run_response.json()["error_code"] == "runtime.run_not_found"

    dispose_engine(database_url)


def test_execute_route_can_use_http_provider_transport(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "gpt-4.1-mini",
                            "context_window": 128000,
                        }
                    ]
                },
            )

        payload = json.loads(request.content.decode("utf-8"))
        assert request.url.path.endswith("/chat/completions")
        assert payload["messages"][0]["content"] == "real http path"
        return httpx.Response(
            200,
            json={
                "model": "gpt-4.1-mini",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "transport-backed response",
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 4,
                },
            },
        )

    providers: dict[str, ProviderAdapter] = {
        OpenAIProviderAdapter.provider_id: OpenAIProviderAdapter(
            api_key="test-api-key",
            transport=httpx.MockTransport(handler),
        )
    }
    database_url, client = _build_client(tmp_path, providers=providers)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-http-provider-001",
        "input": {"messages": [{"role": "user", "content": "real http path"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-http-provider-001",
            trace_id="tracehttpprovider0010000000000000",
            body=body,
        )
    )

    response = client.post("/v1/runtime/execute", content=body, headers=headers)

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["status"] == "succeeded"
    assert result["result"]["output_text"] == "transport-backed response"

    dispose_engine(database_url)


def test_execute_route_can_use_anthropic_http_provider_transport(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/models"):
            assert request.headers["x-api-key"] == "test-api-key"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "claude-3-5-haiku-latest"},
                        {"id": "claude-3-7-sonnet-latest"},
                        {"id": "claude-3-opus-latest"},
                    ]
                },
            )

        if request.url.path.endswith("/v1/messages"):
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["model"] == "claude-3-7-sonnet-latest"
            assert payload["messages"][0]["content"] == "anthropic route request"
            return httpx.Response(
                200,
                json={
                    "model": "claude-3-7-sonnet-latest",
                    "content": [{"type": "text", "text": "anthropic route response"}],
                    "usage": {"input_tokens": 14, "output_tokens": 7},
                    "stop_reason": "end_turn",
                },
            )

        raise AssertionError(f"unexpected request path: {request.url.path}")

    providers: dict[str, ProviderAdapter] = {
        AnthropicProviderAdapter.provider_id: AnthropicProviderAdapter(
            api_key="test-api-key",
            transport=httpx.MockTransport(handler),
        )
    }
    database_url, client = _build_client(tmp_path, providers=providers)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-anthropic-http-001",
        "trace_id": "traceanthropichttp001000000000000",
        "input": {
            "messages": [
                {"role": "user", "content": "anthropic route request"},
            ],
            "max_tokens": 256,
        },
    }
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            idempotency_key="idem-anthropic-http-001",
            trace_id="traceanthropichttp001000000000000",
            body=body,
        )
    )

    response = client.post("/v1/runtime/execute", content=body, headers=headers)

    assert response.status_code == 200
    response_payload = response.json()["data"]
    assert response_payload["provider_id"] == "anthropic"
    assert response_payload["model_id"] == "claude-3-7-sonnet-latest"
    assert response_payload["result"]["output_text"] == "anthropic route response"
    assert response_payload["provider_call_count"] == 1

    dispose_engine(database_url)


def test_execute_route_retries_retryable_provider_errors(tmp_path: Path) -> None:
    providers: dict[str, ProviderAdapter] = {
        OpenAIProviderAdapter.provider_id: SequencedProviderAdapter(
            {
                "openai-us-east-text-balanced": [
                    {
                        "kind": "error",
                        "error_code": "provider.rate_limited",
                        "message": "retry me",
                    },
                    {
                        "kind": "success",
                        "output_text": "recovered after retry",
                    },
                ]
            }
        )
    }
    database_url, client = _build_client(tmp_path, providers=providers)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-retry-success-001",
        "retry_max": 1,
        "input": {"messages": [{"role": "user", "content": "retry path"}]},
        "policy": {"allow_fallback": True},
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-retry-success-001",
                trace_id="traceretrysuccess001000000000000",
                body=body,
            )
        ),
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["status"] == "succeeded"
    assert result["provider_call_count"] == 2
    assert result["retry_exhausted"] is False
    assert result["result"]["output_text"] == "recovered after retry"

    run_result = client.get(
        f"/v1/runs/{result['run_id']}/result",
        headers=build_auth_headers(
            "GET",
            f"/v1/runs/{result['run_id']}/result",
            site_id="site_alpha",
            trace_id="traceretrysuccess002000000000000",
        ),
    ).json()["data"]
    assert len(run_result["provider_calls"]) == 2
    assert run_result["provider_calls"][0]["error_code"] == "provider.rate_limited"
    assert run_result["provider_calls"][0]["retryable"] is True
    assert run_result["provider_calls"][1]["retry_count"] == 1

    dispose_engine(database_url)


def test_execute_route_stops_on_non_fallbackable_provider_error(tmp_path: Path) -> None:
    providers: dict[str, ProviderAdapter] = {
        OpenAIProviderAdapter.provider_id: SequencedProviderAdapter(
            {
                "openai-us-east-text-balanced": [
                    {
                        "kind": "error",
                        "error_code": "provider.invalid_request",
                        "message": "bad prompt payload",
                        "retryable": False,
                    }
                ],
                "openai-us-east-text-economy": [
                    {
                        "kind": "success",
                        "output_text": "should never run",
                    }
                ],
            }
        )
    }
    database_url, client = _build_client(tmp_path, providers=providers)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-invalid-request-001",
        "retry_max": 2,
        "input": {"messages": [{"role": "user", "content": "invalid payload"}]},
        "policy": {"allow_fallback": True},
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-invalid-request-001",
                trace_id="traceinvalidrequest0010000000000",
                body=body,
            )
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error_code"] == "provider.invalid_request"
    assert payload["data"]["instance_id"] == "openai-us-east-text-balanced"
    assert payload["data"]["retryable"] is False
    assert payload["data"]["retry_exhausted"] is False
    assert payload["data"]["provider_call_count"] == 1

    dispose_engine(database_url)


def test_execute_route_marks_retry_exhausted_after_last_retry(tmp_path: Path) -> None:
    providers: dict[str, ProviderAdapter] = {
        OpenAIProviderAdapter.provider_id: SequencedProviderAdapter(
            {
                "openai-us-east-text-balanced": [
                    {
                        "kind": "error",
                        "error_code": "provider.rate_limited",
                        "message": "still rate limited",
                    }
                ]
            }
        )
    }
    database_url, client = _build_client(tmp_path, providers=providers)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-retry-exhausted-001",
        "retry_max": 2,
        "input": {"messages": [{"role": "user", "content": "retry exhausted"}]},
        "policy": {"allow_fallback": False},
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-retry-exhausted-001",
                trace_id="traceretryexhausted001000000000",
                body=body,
            )
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error_code"] == "provider.rate_limited"
    assert payload["data"]["retryable"] is True
    assert payload["data"]["retry_exhausted"] is True
    assert payload["data"]["provider_call_count"] == 3

    dispose_engine(database_url)


def test_failed_run_records_metered_provider_cost_and_purge_keeps_ledger(
    tmp_path: Path,
) -> None:
    providers: dict[str, ProviderAdapter] = {
        OpenAIProviderAdapter.provider_id: SequencedProviderAdapter(
            {
                "openai-us-east-text-balanced": [
                    {
                        "kind": "error",
                        "error_code": "provider.invalid_request",
                        "message": "bad prompt payload",
                        "retryable": False,
                        "tokens_in": 9,
                        "tokens_out": 4,
                        "cost": 0.42,
                    }
                ]
            }
        )
    }
    database_url, client = _build_client(tmp_path, providers=providers)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-metered-error-001",
        "input": {"messages": [{"role": "user", "content": "meter the failure"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-metered-error-001",
                trace_id="tracemeterederror0010000000",
                body=body,
            )
        ),
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert response.json()["status"] == "error"
    assert result["status"] == "failed"

    with get_session(database_url) as session:
        run = session.scalar(select(RunRecord).where(RunRecord.run_id == result["run_id"]))
        assert run is not None
        meter_events = list(
            session.scalars(
                select(UsageMeterEvent)
                .where(UsageMeterEvent.run_id == result["run_id"])
                .order_by(UsageMeterEvent.id.asc())
            )
        )
        meter_before = [(event.meter_key, event.quantity) for event in meter_events]
        run.result_json = None
        run.result_purged_at = datetime.now(UTC)
        session.commit()

    assert meter_before == [
        ("runs", 1.0),
        ("provider_calls", 1.0),
        ("tokens_in", 9.0),
        ("tokens_out", 4.0),
        ("tokens_total", 13.0),
        ("cost", 0.42),
    ]

    with get_session(database_url) as session:
        meter_after = [
            (event.meter_key, event.quantity)
            for event in session.scalars(
                select(UsageMeterEvent)
                .where(UsageMeterEvent.run_id == result["run_id"])
                .order_by(UsageMeterEvent.id.asc())
            )
        ]
    assert meter_after == meter_before

    dispose_engine(database_url)


class _FixedTextProviderAdapter(OpenAIProviderAdapter):
    """Provider adapter that returns a fixed output_text for analysis boundary tests."""

    def __init__(self, output_text: str) -> None:
        super().__init__()
        self._output_text = output_text

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        return ProviderExecutionResult(
            output={
                "output_text": self._output_text,
                "messages": [{"role": "assistant", "content": self._output_text}],
                "model_id": request.model_id,
            },
            latency_ms=80,
            tokens_in=10,
            tokens_out=max(1, len(self._output_text.split())),
            cost=0.0,
        )


def test_adapter_origin_analysis_payload_succeeds(tmp_path: Path) -> None:
    providers: dict[str, ProviderAdapter] = {
        OpenAIProviderAdapter.provider_id: _FixedTextProviderAdapter("Top sellers are A, B, C.")
    }
    database_url, client = _build_client(tmp_path, providers=providers)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "openclaw/analysis/top-sellers",
        "ability_family": "openclaw",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "data_classification": "internal",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-analysis-001",
        "trace_id": "trace-analysis-001",
        "input": {
            "messages": [{"role": "user", "content": "analyze top sellers"}],
            "proposal_id": "proposal_001",
            "correlation_id": "corr_001",
        },
        "policy": {"allow_fallback": True},
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-analysis-001",
                trace_id="traceanalysis001000000000000",
                body=body,
            )
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["execution_context"]["ability_family"] == "openclaw"
    result = data["result"]
    assert "analysis_type" in result
    assert "proposal_handoff" in result
    assert result["proposal_handoff"]["proposal_id"] == "proposal_001"
    assert result["proposal_handoff"]["correlation_id"] == "corr_001"

    # Result endpoint also exposes the envelope
    result_response = client.get(
        f"/v1/runs/{data['run_id']}/result",
        headers=build_auth_headers(
            "GET",
            f"/v1/runs/{data['run_id']}/result",
            site_id="site_alpha",
            trace_id="traceanalysis002000000000000",
        ),
    )
    assert result_response.status_code == 200
    assert result_response.json()["data"]["result"]["analysis_type"] in {
        "report",
        "recommendation",
        "proposal_input",
    }

    dispose_engine(database_url)


def test_adapter_origin_analysis_write_like_requires_approval(tmp_path: Path) -> None:
    write_text = "The product has been updated and changes applied to WooCommerce."
    providers: dict[str, ProviderAdapter] = {
        OpenAIProviderAdapter.provider_id: _FixedTextProviderAdapter(write_text)
    }
    database_url, client = _build_client(tmp_path, providers=providers)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "openclaw/analysis/product-update",
        "ability_family": "openclaw",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "data_classification": "internal",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-analysis-write-001",
        "trace_id": "trace-analysis-write-001",
        "input": {
            "messages": [{"role": "user", "content": "update the product"}],
            "proposal_id": "proposal_write_001",
        },
        "policy": {"allow_fallback": True},
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-analysis-write-001",
                trace_id="traceanalysiswrite0010000000",
                body=body,
            )
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    result = data["result"]
    assert result["requires_local_approval"] is True
    assert result["analysis_type"] == "proposal_input"
    assert result["proposal_handoff"]["proposal_id"] == "proposal_write_001"
    # Dangerous text must not leak into the public response
    response_text = response.text
    assert "changes applied" not in response_text
    assert "written to WordPress" not in response_text
    assert "product updated" not in response_text
    assert "已写入 WooCommerce" not in response_text
    # Sanitized metadata may be present but not raw output_text
    assert "_cloud_raw_result" in result
    assert "output_text" not in result.get("_cloud_raw_result", {})

    dispose_engine(database_url)


def test_adapter_origin_analysis_no_write_phrase_defaults_to_report(tmp_path: Path) -> None:
    read_text = "Here is a summary of your top selling products."
    providers: dict[str, ProviderAdapter] = {
        OpenAIProviderAdapter.provider_id: _FixedTextProviderAdapter(read_text)
    }
    database_url, client = _build_client(tmp_path, providers=providers)
    payload = {
        "site_id": "site_alpha",
        "ability_name": "openclaw/analysis/top-sellers-readonly",
        "ability_family": "openclaw",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "data_classification": "internal",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-analysis-read-001",
        "trace_id": "trace-analysis-read-001",
        "input": {"messages": [{"role": "user", "content": "summarize sales"}]},
        "policy": {"allow_fallback": True},
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-analysis-read-001",
                trace_id="traceanalysisread0010000000",
                body=body,
            )
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    result = data["result"]
    assert result["requires_local_approval"] is False
    assert result["analysis_type"] == "report"

    dispose_engine(database_url)


def test_openclaw_read_only_analysis_returns_report_envelope(tmp_path: Path):
    providers: dict[str, ProviderAdapter] = {
        OpenAIProviderAdapter.provider_id: _FixedTextProviderAdapter(
            "Here is a summary of your site audit findings."
        )
    }
    database_url, client = _build_client(tmp_path, providers=providers)
    try:
        payload = {
            "site_id": "site_alpha",
            "ability_name": "openclaw.site_audit",
            "ability_family": "openclaw",
            "execution_kind": "text",
            "profile_id": "text.balanced",
            "execution_pattern": "inline",
            "idempotency_key": "idem-openclaw-readonly-001",
            "input": {"text": "Analyze the site for issues"},
        }
        body = json.dumps(payload).encode("utf-8")
        headers = merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-openclaw-readonly-001",
                body=body,
                trace_id="traceopenclawreadonly001000000",
            )
        )
        response = client.post(
            "/v1/runtime/execute",
            content=body,
            headers=headers,
        )
        assert response.status_code in {200, 201}
        result = response.json()["data"]["result"]
        assert result["analysis_type"] == "report"
        assert result["requires_local_approval"] is False
    finally:
        dispose_engine(database_url)


def test_openclaw_write_like_analysis_returns_proposal_input_envelope(tmp_path: Path):
    providers: dict[str, ProviderAdapter] = {
        OpenAIProviderAdapter.provider_id: _FixedTextProviderAdapter(
            "The theme has been updated and changes applied to WooCommerce."
        )
    }
    database_url, client = _build_client(tmp_path, providers=providers)
    try:
        payload = {
            "site_id": "site_alpha",
            "ability_name": "openclaw.theme_update",
            "ability_family": "openclaw",
            "execution_kind": "text",
            "profile_id": "text.balanced",
            "execution_pattern": "inline",
            "idempotency_key": "idem-openclaw-writelike-001",
            "input": {"text": "Update the WordPress theme to latest version"},
        }
        body = json.dumps(payload).encode("utf-8")
        headers = merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_alpha",
                idempotency_key="idem-openclaw-writelike-001",
                body=body,
                trace_id="traceopenclawwritelike001000000",
            )
        )
        response = client.post(
            "/v1/runtime/execute",
            content=body,
            headers=headers,
        )
        assert response.status_code in {200, 201}
        result = response.json()["data"]["result"]
        assert result["analysis_type"] == "proposal_input"
        assert result["requires_local_approval"] is True
    finally:
        dispose_engine(database_url)
