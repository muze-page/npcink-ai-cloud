from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
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
from app.core.models import ProviderConnection, RunRecord
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from app.domain.wordpress_ai_connector.routing_profiles import (
    WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID,
    WP_AI_CONNECTOR_CLASSIFICATION_PROFILE_ID,
    WP_AI_CONNECTOR_EDITORIAL_PROFILE_ID,
    WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID,
    WP_AI_CONNECTOR_PROFILE_SPECS_BY_ID,
    WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
)
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_KEY_ID,
    TEST_PORTAL_JWT_SECRET,
    TEST_SECRET,
    build_auth_headers,
    build_internal_headers,
    merge_json_headers,
    seed_site_auth,
)


def test_wordpress_ai_connector_text_profiles_prefer_balanced_defaults() -> None:
    short_text_spec = WP_AI_CONNECTOR_PROFILE_SPECS_BY_ID[
        WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID
    ]
    classification_spec = WP_AI_CONNECTOR_PROFILE_SPECS_BY_ID[
        WP_AI_CONNECTOR_CLASSIFICATION_PROFILE_ID
    ]

    assert short_text_spec.ordered_tiers[0] == "balanced"
    assert classification_spec.ordered_tiers[0] == "balanced"


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
                ),
                CatalogModelSeed(
                    model_id="grok-imagine-wp-ai-test",
                    family="grok-imagine-test",
                    feature="image_generation",
                    status="available",
                    context_window=0,
                    price_input=0.0,
                    price_output=0.0,
                    raw_json={"surface": "wordpress_ai_connector_image_test"},
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="openai-wp-ai-image-test",
                            endpoint_variant="image_generations",
                            region="global",
                            capability_tags=[
                                "image_generation",
                                "z-image",
                                "quality",
                                "default",
                            ],
                            is_default=True,
                            weight=100,
                        )
                    ],
                ),
                CatalogModelSeed(
                    model_id="speech-wp-ai-connector-test",
                    family="speech-test",
                    feature="audio_generation",
                    status="available",
                    context_window=0,
                    price_input=0.0,
                    price_output=0.0,
                    raw_json={"surface": "wordpress_ai_connector_audio_test"},
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="openai-wp-ai-audio-test",
                            endpoint_variant="audio_generation",
                            region="global",
                            capability_tags=[
                                "audio_generation",
                                "default",
                                "balanced",
                                "narration",
                            ],
                            is_default=True,
                            weight=100,
                        )
                    ],
                ),
            ],
        )

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        self.requests.append(request)
        task = ""
        metadata = request.input_payload.get("metadata")
        if isinstance(metadata, dict):
            task = str(metadata.get("task") or "")
        output_text = "Npcink Cloud Addon: WordPress AI scene helper 说明：short title rationale"
        if task == "content_classification":
            output_text = "- WordPress AI\n- Cloud connector\n- Scene runtime"
        elif task == "content_summary":
            output_text = (
                "### **1. Fast editing support**\n"
                "Npcink Cloud Addon helps WordPress administrators generate useful "
                "scene-specific AI suggestions for titles, excerpts, summaries, SEO "
                "descriptions, and taxonomy classification without exposing chat or "
                "direct WordPress writes.\n\n### **2. Safe operations**"
            )
        elif task == "meta_description":
            output_text = (
                "**Npcink Cloud AI Connector: WordPress AI plugin scene runtime** "
                "Npcink Cloud Addon connects verified Cloud settings to fixed WordPress "
                "AI editing scenes without exposing chat or direct writes. ### Details"
            )
        if request.execution_kind == "image_generation":
            return ProviderExecutionResult(
                output={
                    "artifact_type": "image_generation_candidates",
                    "contract_version": "image_generation_result.v1",
                    "model_id": request.model_id,
                    "images": [
                        {
                            "index": 1,
                            "url": "https://example.invalid/wp-ai-generated.png",
                            "b64_json": "",
                            "mime_type": "image/png",
                        }
                    ],
                    "provider_response_format": "url",
                    "direct_wordpress_write": False,
                },
                latency_ms=25,
                tokens_in=14,
                tokens_out=0,
                cost=0.0,
            )
        return ProviderExecutionResult(
            output={
                "output_text": output_text,
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
    with get_session(database_url) as session:
        session.add(
            ProviderConnection(
                connection_id="openai",
                provider_type="openai_compatible",
                display_name="OpenAI",
                enabled=True,
                base_url="https://api.openai.test/v1",
                config_json={
                    "provider_id": "openai",
                    "kind": "openai_compatible",
                    "capability_ids": [
                        "text_generation",
                        "image_generation",
                        "audio_generation",
                    ],
                    "runtime_profile_ids": [
                        WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
                        WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID,
                        WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID,
                    ],
                    "model_ids": [
                        "gpt-wp-ai-connector-test",
                        "grok-imagine-wp-ai-test",
                        "speech-wp-ai-connector-test",
                    ],
                },
                secret_ciphertext="configured-in-test",
                status="ready",
                source_role="execution_source",
                metadata_json={},
            )
        )
        session.commit()
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


def _image_payload(input_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    input_payload: dict[str, Any] = {
        "contract_version": "image_generation_request.v1",
        "source_surface": "wordpress_ai_connector",
        "connector_id": "npcink-cloud",
        "task": "image_generation",
        "prompt": "A clean media-library illustration of a WordPress editor workspace.",
        "n": 1,
        "response_format": "url",
        "aspect_ratio": "16:9",
        "resolution": "medium",
    }
    input_payload.update(input_overrides or {})
    return {
        "ability_name": "npcink-cloud/generate-image",
        "contract_version": "image_generation_request.v1",
        "channel": "wordpress_ai_connector",
        "execution_kind": "image_generation",
        "execution_pattern": "inline",
        "storage_mode": "result_only",
        "data_classification": "internal",
        "timeout_seconds": 90,
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
    assert data["result"]["output_text"] == "Npcink Cloud Addon: WordPress AI scene helper"
    assert data["execution_context"]["contract_version"] == "wp_ai_connector_runtime.v1"
    assert data["execution_context"]["ability_family"] == "text"
    assert data["execution_context"]["data_classification"] == "public_site_content"
    assert provider.requests[0].ability_name == "npcink-cloud/wp-ai-connector"
    assert provider.requests[0].execution_kind == "text"
    assert provider.requests[0].profile_id == WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID
    assert provider.requests[0].timeout_ms == 45000
    provider_input = provider.requests[0].input_payload
    assert "messages" not in provider_input
    assert "tools" not in provider_input
    assert "Generate exactly one concise title" in provider_input["input"]
    assert "Suggest a concise title for this WordPress post." in provider_input["input"]
    assert provider_input["max_tokens"] == 48
    assert provider_input["max_output_tokens"] == 48
    assert provider_input["metadata"]["source_surface"] == "wordpress_ai_connector"
    assert provider_input["metadata"]["suggestion_only"] is True

    with get_session(database_url) as session:
        run = session.execute(select(RunRecord)).scalar_one()
        assert run.ability_name == "npcink-cloud/wp-ai-connector"
        assert run.channel == "wordpress_ai_connector"
        assert run.execution_kind == "text"
        assert run.profile_id == WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID
        assert run.policy_json["managed_surface"] == "wordpress_ai_connector"
        assert run.policy_json["task_group"] == "short_text"
        assert run.policy_json["routing_intent"] == "content.short_text"
        assert run.policy_json["timeout_ms"] == 45000
        assert run.policy_json["execution_contract"]["contract_version"] == (
            "wp_ai_connector_runtime.v1"
        )
        assert (
            run.policy_json["execution_contract"]["managed_surface"]
            == "wordpress_ai_connector"
        )
        assert run.policy_json["execution_contract"]["task_group"] == "short_text"
        assert (
            run.policy_json["execution_contract"]["routing_intent"]
            == "content.short_text"
        )


def test_wordpress_ai_connector_runtime_projects_classification_json_scene(
    tmp_path: Path,
) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "task": "content_classification",
            "request": {
                "prompt": "Classify this post into WordPress taxonomy suggestions.",
                "response_format": "json",
            },
        }
    )

    response = _execute(
        client,
        payload,
        idempotency_key="wp-ai-connector-classification",
    )

    assert response.status_code == 200
    provider_input = provider.requests[0].input_payload
    assert "Return strict JSON only" in provider_input["input"]
    assert "\"suggestions\"" in provider_input["input"]
    assert provider_input["max_tokens"] == 220
    assert provider_input["max_output_tokens"] == 220
    assert provider.requests[0].profile_id == WP_AI_CONNECTOR_CLASSIFICATION_PROFILE_ID
    result = json.loads(response.json()["data"]["result"]["output_text"])
    assert result["suggestions"]
    assert all("term" in suggestion for suggestion in result["suggestions"])
    assert any(
        suggestion["term"] in {"WordPress", "WordPress AI"}
        for suggestion in result["suggestions"]
    )


def test_wordpress_ai_connector_runtime_normalizes_meta_description_scene(
    tmp_path: Path,
) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "task": "meta_description",
            "request": {
                "prompt": (
                    "为这篇文章生成 SEO 描述：Npcink Cloud Addon 让 WordPress AI 插件"
                    "在固定能力场景中调用云端运行时，只提供建议式输出，不提供通用聊天入口。"
                ),
            },
        }
    )

    response = _execute(client, payload, idempotency_key="wp-ai-connector-meta")

    assert response.status_code == 200
    provider_input = provider.requests[0].input_payload
    assert "120 to 155 characters" in provider_input["input"]
    assert provider_input["max_tokens"] == 80
    result_text = response.json()["data"]["result"]["output_text"]
    assert "**" not in result_text
    assert "###" not in result_text
    assert len(result_text) <= 155
    assert "云端运行时" in result_text


def test_wordpress_ai_connector_runtime_normalizes_summary_text_scene(
    tmp_path: Path,
) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "task": "content_summary",
            "request": {
                "prompt": "Summarize this post.",
            },
        }
    )

    response = _execute(client, payload, idempotency_key="wp-ai-connector-summary")

    assert response.status_code == 200
    provider_input = provider.requests[0].input_payload
    assert "Return only the summary" in provider_input["input"]
    assert provider_input["max_tokens"] == 160
    assert provider.requests[0].profile_id == WP_AI_CONNECTOR_EDITORIAL_PROFILE_ID
    result_text = response.json()["data"]["result"]["output_text"]
    assert "**" not in result_text
    assert "###" not in result_text
    assert not result_text.endswith("2.")
    assert len(result_text) <= 220


def test_wordpress_ai_connector_image_generation_uses_managed_image_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.runtime import service as runtime_service

    def materialize_provider_url(result_json: dict[str, Any], **_: object) -> dict[str, Any]:
        next_result = dict(result_json)
        next_result["provider_response_format"] = "b64_json"
        next_result["images"] = [
            {
                **dict(next_result["images"][0]),
                "b64_json": "aW1hZ2UtYnl0ZXM=",
            }
        ]
        return next_result

    monkeypatch.setattr(
        runtime_service,
        "materialize_inline_image_candidates_from_urls",
        materialize_provider_url,
    )

    database_url, client, provider = _build_client(tmp_path)

    response = _execute(
        client,
        _image_payload({"response_format": "b64_json"}),
        idempotency_key="wp-ai-image-generation",
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    assert data["profile_id"] == WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID
    assert data["result"]["artifact_type"] == "image_generation_candidates"
    assert data["result"]["provider_response_format"] == "b64_json"
    assert data["result"]["images"][0]["b64_json"] == "aW1hZ2UtYnl0ZXM="
    assert data["result"]["direct_wordpress_write"] is False
    assert provider.requests[0].execution_kind == "image_generation"
    assert provider.requests[0].profile_id == WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID
    assert provider.requests[0].timeout_ms == 90000
    assert provider.requests[0].input_payload["response_format"] == "b64_json"

    with get_session(database_url) as session:
        run = session.execute(select(RunRecord)).scalar_one()
        assert run.ability_name == "npcink-cloud/generate-image"
        assert run.channel == "wordpress_ai_connector"
        assert run.execution_kind == "image_generation"
        assert run.profile_id == WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID
        assert run.policy_json["managed_surface"] == "wordpress_ai_connector"
        assert run.policy_json["task_group"] == "image_generation"
        assert run.policy_json["routing_intent"] == "media.image_generation"
        assert run.policy_json["timeout_ms"] == 90000
        assert (
            run.policy_json["execution_contract"]["routing_intent"]
            == "media.image_generation"
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


def test_admin_wordpress_ai_routing_updates_platform_managed_candidates(
    tmp_path: Path,
) -> None:
    database_url, client, _ = _build_client(tmp_path)

    get_response = client.get(
        "/internal/service/admin/wordpress-ai-routing",
        headers=build_internal_headers(),
    )

    assert get_response.status_code == 200
    data = get_response.json()["data"]
    assert data["contract_version"] == "cloud-ability-model-routing.v1"
    assert data["projection_kind"] == "runtime_profile_binding"
    assert data["customer_model_selection"] is False
    assert data["direct_wordpress_write"] is False
    assert data["boundary"]["cloud_ability_registry"] is False
    assert data["boundary"]["wordpress_ability_truth"] == "local_plugin"
    assert len(data["profiles"]) == 5
    assert data["available_text_instances"][0]["instance_id"] == (
        "openai-wp-ai-connector-test"
    )
    assert data["available_image_instances"][0]["instance_id"] == "openai-wp-ai-image-test"
    assert data["available_audio_instances"][0]["instance_id"] == "openai-wp-ai-audio-test"
    short_text = next(
        profile
        for profile in data["profiles"]
        if profile["profile_id"] == WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID
    )
    assert short_text["tasks"] == [
        "alt_text_suggest",
        "excerpt_generation",
        "meta_description",
        "title_generation",
        "audio_summary_script",
    ]
    assert short_text["routing_intent"] == "content.short_text"
    image_generation = next(
        profile
        for profile in data["profiles"]
        if profile["profile_id"] == WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID
    )
    assert image_generation["execution_kind"] == "image_generation"
    assert image_generation["routing_intent"] == "media.image_generation"
    assert image_generation["tasks"] == ["image_generation"]
    assert image_generation["candidate_instance_ids"] == ["openai-wp-ai-image-test"]
    assert image_generation["timeout_ms"] == 90000
    audio_generation = next(
        profile
        for profile in data["profiles"]
        if profile["profile_id"] == WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID
    )
    assert audio_generation["execution_kind"] == "audio_generation"
    assert audio_generation["routing_intent"] == "audio.generation"
    assert audio_generation["tasks"] == [
        "article_narration",
        "article_audio_summary",
    ]
    assert audio_generation["candidate_instance_ids"] == ["openai-wp-ai-audio-test"]

    response = client.post(
        "/internal/service/admin/wordpress-ai-routing",
        headers=merge_json_headers(
            build_internal_headers(idempotency_key="wp-ai-routing-admin-save-001")
        ),
        json={
            "profiles": [
                {
                    "profile_id": WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
                    "candidate_instance_ids": ["openai-wp-ai-connector-test"],
                    "timeout_ms": 12000,
                    "allow_fallback": True,
                    "max_retries": 1,
                    "note": "short-text canary",
                },
                {
                    "profile_id": WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID,
                    "candidate_instance_ids": ["openai-wp-ai-image-test"],
                    "timeout_ms": 90000,
                    "allow_fallback": False,
                    "max_retries": 0,
                    "note": "image-generation canary",
                },
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["receipt"]["event_kind"] == "wordpress_ai_routing.update"
    updated = next(
        profile
        for profile in payload["profiles"]
        if profile["profile_id"] == WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID
    )
    assert updated["candidate_instance_ids"] == ["openai-wp-ai-connector-test"]
    assert updated["timeout_ms"] == 12000
    assert updated["max_retries"] == 1
    updated_image = next(
        profile
        for profile in payload["profiles"]
        if profile["profile_id"] == WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID
    )
    assert updated_image["candidate_instance_ids"] == ["openai-wp-ai-image-test"]
    assert updated_image["timeout_ms"] == 90000
    assert updated_image["allow_fallback"] is False

    run_response = _execute(
        client,
        _payload(),
        idempotency_key="wp-ai-routing-admin-run-after-save",
    )

    assert run_response.status_code == 200
    with get_session(database_url) as session:
        run = session.execute(
            select(RunRecord).where(RunRecord.run_id == run_response.json()["data"]["run_id"])
        ).scalar_one()
        assert run.profile_id == WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID
        assert run.policy_json["timeout_ms"] == 12000
        assert run.policy_json["max_retries"] == 1
        assert run.policy_json["routing_intent"] == "content.short_text"


def test_admin_wordpress_ai_routing_rejects_unknown_profile(tmp_path: Path) -> None:
    _, client, _ = _build_client(tmp_path)

    response = client.post(
        "/internal/service/admin/wordpress-ai-routing",
        headers=merge_json_headers(
            build_internal_headers(idempotency_key="wp-ai-routing-admin-save-unknown")
        ),
        json={
            "profiles": [
                {
                    "profile_id": "text.balanced",
                    "candidate_instance_ids": ["openai-wp-ai-connector-test"],
                    "timeout_ms": 12000,
                    "allow_fallback": True,
                    "max_retries": 0,
                }
            ]
        },
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "wordpress_ai_routing.invalid_profile"


def test_admin_wordpress_ai_routing_rejects_execution_kind_mismatch(
    tmp_path: Path,
) -> None:
    _, client, _ = _build_client(tmp_path)

    response = client.post(
        "/internal/service/admin/wordpress-ai-routing",
        headers=merge_json_headers(
            build_internal_headers(
                idempotency_key="wp-ai-routing-admin-save-kind-mismatch"
            )
        ),
        json={
            "profiles": [
                {
                    "profile_id": WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
                    "candidate_instance_ids": ["openai-wp-ai-image-test"],
                    "timeout_ms": 12000,
                    "allow_fallback": True,
                    "max_retries": 0,
                }
            ]
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "wordpress_ai_routing.invalid_profile"
    assert "may only use available text instances" in payload["message"]


def test_admin_wordpress_ai_routing_requires_enabled_provider_model(
    tmp_path: Path,
) -> None:
    database_url, client, _ = _build_client(tmp_path)
    with get_session(database_url) as session:
        row = session.get(ProviderConnection, "openai")
        assert row is not None
        config = dict(row.config_json or {})
        config["model_ids"] = [
            "gpt-wp-ai-connector-test",
            "grok-imagine-wp-ai-test",
        ]
        row.config_json = config
        session.commit()

    get_response = client.get(
        "/internal/service/admin/wordpress-ai-routing",
        headers=build_internal_headers(),
    )

    assert get_response.status_code == 200
    data = get_response.json()["data"]
    assert data["available_audio_instances"] == []
    audio_generation = next(
        profile
        for profile in data["profiles"]
        if profile["profile_id"] == WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID
    )
    assert audio_generation["candidate_instance_ids"] == []
    assert audio_generation["status"] == "needs_candidates"

    response = client.post(
        "/internal/service/admin/wordpress-ai-routing",
        headers=merge_json_headers(
            build_internal_headers(
                idempotency_key="wp-ai-routing-admin-save-model-allowlist"
            )
        ),
        json={
            "profiles": [
                {
                    "profile_id": WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID,
                    "candidate_instance_ids": ["openai-wp-ai-audio-test"],
                    "timeout_ms": 90000,
                    "allow_fallback": True,
                    "max_retries": 0,
                }
            ]
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "wordpress_ai_routing.invalid_profile"
    assert "may only use models enabled for provider openai" in payload["message"]
