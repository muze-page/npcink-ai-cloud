from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.providers.base import (
    CatalogInstanceSeed,
    CatalogModelSeed,
    ProviderCatalogSnapshot,
    ProviderExecutionRequest,
    ProviderExecutionResult,
)
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import get_session, init_schema
from app.core.models import RunRecord
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_KEY_ID,
    TEST_PORTAL_JWT_SECRET,
    TEST_SECRET,
    build_auth_headers,
    merge_json_headers,
    seed_site_auth,
)


class WordPressAIConnectorTextProvider:
    provider_id = "openai"
    display_name = "WordPress AI Connector Text Provider"
    adapter_type = "openai"

    def __init__(self) -> None:
        self.requests: list[ProviderExecutionRequest] = []

    def fetch_catalog(self) -> ProviderCatalogSnapshot:
        return ProviderCatalogSnapshot(
            provider_id=self.provider_id,
            display_name=self.display_name,
            adapter_type=self.adapter_type,
            models=[
                CatalogModelSeed(
                    model_id="gpt-wp-ai-connector-test",
                    family="gpt-test",
                    feature="text",
                    status="available",
                    context_window=128000,
                    price_input=0.0,
                    price_output=0.0,
                    raw_json={"surface": "wordpress_ai_connector_test"},
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="openai-wp-ai-connector-test",
                            endpoint_variant="responses",
                            region="global",
                            capability_tags=["text", "balanced", "hosted-free"],
                            is_default=True,
                            weight=100,
                        )
                    ],
                )
            ],
        )

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        self.requests.append(request)
        return ProviderExecutionResult(
            output={
                "output_text": "Suggested scene-bound title",
                "model_id": request.model_id,
            },
            latency_ms=12,
            tokens_in=24,
            tokens_out=8,
            cost=0.0,
        )


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'wp-ai-connector.sqlite3'}"


def _build_client(tmp_path: Path) -> tuple[str, TestClient, WordPressAIConnectorTextProvider]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read"],
    )
    provider = WordPressAIConnectorTextProvider()
    CatalogService(database_url, providers={"openai": provider}).refresh_catalog()
    settings = Settings(
        _env_file=None,
        project_name="Npcink AI Cloud WordPress AI Connector Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
    )
    client = TestClient(
        create_app(
            CloudServices(
                settings=settings,
                providers={"openai": provider},
            )
        )
    )
    return database_url, client, provider


def _payload(input_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    input_payload: dict[str, Any] = {
        "contract_version": "wp_ai_connector_runtime.v1",
        "source_surface": "wordpress_ai_connector",
        "connector_id": "npcink-cloud",
        "task": "title_generation",
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
        "no_conversation": True,
        "expected_response_contract": "wp_ai_connector_result.v1",
        "request": {
            "post_title": "Existing title",
            "post_excerpt": "Public excerpt",
            "prompt": "Suggest a concise title for this WordPress post.",
        },
    }
    input_payload.update(input_overrides or {})
    return {
        "ability_name": "npcink-cloud/wp-ai-connector",
        "contract_version": "wp_ai_connector_runtime.v1",
        "channel": "wordpress_ai_connector",
        "execution_kind": "wordpress_ai_connector",
        "profile_id": "text.balanced",
        "execution_pattern": "inline",
        "storage_mode": "result_only",
        "data_classification": "public_site_content",
        "timeout_seconds": 60,
        "retry_max": 0,
        "retention_ttl": 86400,
        "input": input_payload,
        "policy": {"allow_fallback": False},
    }


def _execute(
    client: TestClient,
    payload: dict[str, Any],
    *,
    idempotency_key: str = "wp-ai-connector-idem",
) -> Any:
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            body=body,
            site_id="site_alpha",
            key_id=TEST_KEY_ID,
            secret=TEST_SECRET,
            idempotency_key=idempotency_key,
            trace_id="tracewpai000000000000000000000001",
        )
    )
    return client.post("/v1/runtime/execute", content=body, headers=headers)


def test_wordpress_ai_connector_runtime_executes_scene_bound_text(tmp_path: Path) -> None:
    database_url, client, provider = _build_client(tmp_path)

    response = _execute(client, _payload())

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    assert data["execution_context"]["contract_version"] == "wp_ai_connector_runtime.v1"
    assert data["execution_context"]["ability_family"] == "text"
    assert data["execution_context"]["data_classification"] == "public_site_content"
    assert provider.requests[0].ability_name == "npcink-cloud/wp-ai-connector"
    assert provider.requests[0].execution_kind == "text"
    assert provider.requests[0].timeout_ms == 60000
    provider_input = provider.requests[0].input_payload
    assert "messages" not in provider_input
    assert "tools" not in provider_input
    assert "Generate exactly one concise title" in provider_input["input"]
    assert "Suggest a concise title for this WordPress post." in provider_input["input"]
    assert provider_input["metadata"]["source_surface"] == "wordpress_ai_connector"
    assert provider_input["metadata"]["suggestion_only"] is True

    with get_session(database_url) as session:
        run = session.execute(select(RunRecord)).scalar_one()
        assert run.ability_name == "npcink-cloud/wp-ai-connector"
        assert run.channel == "wordpress_ai_connector"
        assert run.execution_kind == "text"
        assert run.policy_json["execution_contract"]["contract_version"] == (
            "wp_ai_connector_runtime.v1"
        )


def test_wordpress_ai_connector_runtime_rejects_timeout_above_scene_limit(
    tmp_path: Path,
) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload()
    payload["timeout_seconds"] = 61

    response = _execute(client, payload, idempotency_key="wp-ai-connector-timeout")

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "wp_ai_connector.timeout_exceeded"
    assert provider.requests == []


def test_wordpress_ai_connector_runtime_rejects_generic_chat_shape(tmp_path: Path) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "request": {
                "messages": [
                    {
                        "role": "user",
                        "content": "Chat about anything.",
                    }
                ]
            }
        }
    )

    response = _execute(client, payload, idempotency_key="wp-ai-connector-chat-shape")

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "wp_ai_connector.chat_or_secret_field_forbidden"
    assert provider.requests == []
