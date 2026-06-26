from __future__ import annotations

import json

import httpx

from app.adapters.providers.base import ProviderExecutionRequest
from app.adapters.providers.litellm_gateway import LiteLLMGatewayProviderAdapter
from app.adapters.providers.openrouter import OpenRouterProviderAdapter
from app.adapters.providers.registry import build_provider_adapters
from app.adapters.providers.siliconflow import SiliconFlowProviderAdapter
from app.adapters.providers.tei import TEIProviderAdapter
from app.adapters.providers.vllm import VLLMProviderAdapter
from app.core.config import Settings


def _build_request(
    *,
    execution_kind: str,
    endpoint_variant: str,
    model_id: str,
    input_payload: dict[str, object],
) -> ProviderExecutionRequest:
    return ProviderExecutionRequest(
        run_id="run_hosted_upstream_provider_test",
        site_id="site_alpha",
        ability_name="npcink-abilities-toolkit/build-article-block-plan",
        profile_id="text.balanced",
        execution_kind=execution_kind,
        model_id=model_id,
        instance_id=f"{endpoint_variant}-instance",
        endpoint_variant=endpoint_variant,
        trace_id="trace_hosted_upstream_provider_test",
        input_payload=input_payload,
        policy={},
        timeout_ms=5_000,
        price_input=0.4,
        price_output=1.6,
    )


def test_litellm_provider_fetches_model_info_and_executes_with_raw_model_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.url.path.endswith("/model/info")
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "model_name": "openai/gpt-4.1-mini",
                            "litellm_params": {
                                "model": "openai/gpt-4.1-mini",
                                "custom_llm_provider": "openai",
                            },
                            "model_info": {
                                "mode": "chat",
                                "supports_function_calling": True,
                            },
                        }
                    ]
                },
            )

        assert request.url.path.endswith("/chat/completions")
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "gpt-4.1-mini"
        return httpx.Response(
            200,
            json={
                "model": "gpt-4.1-mini",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "gateway ok"},
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4},
            },
        )

    adapter = LiteLLMGatewayProviderAdapter(
        base_url="http://litellm.local",
        transport=httpx.MockTransport(handler),
    )

    snapshot = adapter.fetch_catalog()
    assert [model.model_id for model in snapshot.models] == ["litellm/gpt-4.1-mini"]
    assert snapshot.models[0].raw_json["upstream_model_id"] == "gpt-4.1-mini"

    result = adapter.execute(
        _build_request(
            execution_kind="text",
            endpoint_variant="chat_completions",
            model_id="litellm/gpt-4.1-mini",
            input_payload={"messages": [{"role": "user", "content": "hello"}]},
        )
    )
    assert result.output["output_text"] == "gateway ok"


def test_vllm_provider_works_without_api_key_and_namespaces_model_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in {key.lower(): value for key, value in request.headers.items()}
        if request.method == "GET":
            assert request.url.path.endswith("/models")
            return httpx.Response(
                200,
                json={"data": [{"id": "Qwen/Qwen2.5-7B-Instruct", "context_window": 32768}]},
            )

        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "Qwen/Qwen2.5-7B-Instruct"
        return httpx.Response(
            200,
            json={
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "vllm ok"},
                    }
                ],
                "usage": {"prompt_tokens": 6, "completion_tokens": 3},
            },
        )

    adapter = VLLMProviderAdapter(
        base_url="http://vllm.local/v1",
        transport=httpx.MockTransport(handler),
    )

    snapshot = adapter.fetch_catalog()
    assert [model.model_id for model in snapshot.models] == ["vllm/Qwen/Qwen2.5-7B-Instruct"]

    result = adapter.execute(
        _build_request(
            execution_kind="text",
            endpoint_variant="chat_completions",
            model_id="vllm/Qwen/Qwen2.5-7B-Instruct",
            input_payload={"messages": [{"role": "user", "content": "hello"}]},
        )
    )
    assert result.output["output_text"] == "vllm ok"


def test_tei_provider_uses_configured_catalog_and_embeddings_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "BAAI/bge-m3"
        assert payload["input"] == "hello embeddings"
        return httpx.Response(
            200,
            json={
                "model": "BAAI/bge-m3",
                "data": [{"embedding": [0.1, 0.2, 0.3]}],
                "usage": {"prompt_tokens": 3},
            },
        )

    adapter = TEIProviderAdapter(
        base_url="http://tei.local",
        model_ids=["BAAI/bge-m3"],
        transport=httpx.MockTransport(handler),
    )

    snapshot = adapter.fetch_catalog()
    assert [model.model_id for model in snapshot.models] == ["tei/BAAI/bge-m3"]
    assert snapshot.models[0].feature == "embedding"

    result = adapter.execute(
        _build_request(
            execution_kind="embedding",
            endpoint_variant="embeddings",
            model_id="tei/BAAI/bge-m3",
            input_payload={"text": "hello embeddings"},
        )
    )
    assert result.output["dimensions"] == 3


def test_siliconflow_provider_executes_openai_compatible_embeddings() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        assert request.headers["Authorization"] == "Bearer sf-key"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "BAAI/bge-m3"
        assert payload["input"] == "hello embeddings"
        return httpx.Response(
            200,
            json={
                "model": "BAAI/bge-m3",
                "data": [{"embedding": [0.1, 0.2, 0.3]}],
                "usage": {"prompt_tokens": 3},
            },
        )

    adapter = SiliconFlowProviderAdapter(
        api_key="sf-key",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.execute(
        _build_request(
            execution_kind="embedding",
            endpoint_variant="embeddings",
            model_id="siliconflow/BAAI/bge-m3",
            input_payload={"text": "hello embeddings"},
        )
    )
    assert result.output["dimensions"] == 3


def test_openrouter_provider_sets_router_headers_and_namespaces_model_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer or-key"
        assert request.headers["HTTP-Referer"] == "https://magick.example.com"
        assert request.headers["X-Title"] == "Npcink AI Cloud"
        return httpx.Response(
            200,
            json={"data": [{"id": "openai/gpt-4.1-mini"}]},
        )

    adapter = OpenRouterProviderAdapter(
        api_key="or-key",
        site_url="https://magick.example.com",
        transport=httpx.MockTransport(handler),
    )

    snapshot = adapter.fetch_catalog()
    assert [model.model_id for model in snapshot.models] == ["openrouter/openai/gpt-4.1-mini"]


def test_provider_registry_does_not_register_optional_upstreams_from_env_flags() -> None:
    settings = Settings(
        _env_file=None,
        environment="development",
        litellm_provider_enabled=True,
        litellm_base_url="http://litellm.local",
        vllm_provider_enabled=True,
        vllm_base_url="http://vllm.local/v1",
        tei_provider_enabled=True,
        tei_base_url="http://tei.local",
        tei_model_ids="BAAI/bge-m3, jinaai/jina-embeddings-v3",
        openrouter_provider_enabled=True,
        openrouter_api_key="or-key",
        siliconflow_provider_enabled=True,
        siliconflow_api_key="sf-key",
    )

    providers = build_provider_adapters(settings)

    assert "litellm" not in providers
    assert "vllm" not in providers
    assert "tei" not in providers
    assert "openrouter" not in providers
    assert "siliconflow" not in providers


def test_provider_registry_omits_default_openai_without_credentials_outside_dev_test() -> None:
    production_settings = Settings(
        _env_file=None,
        environment="production",
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        internal_auth_token="npcink-cloud-internal-prod-token-32b",
        admin_bootstrap_token="npcink-cloud-admin-bootstrap-token-32b",
        admin_session_secret="npcink-cloud-ops-session-secret-prod-32b",
        portal_jwt_secret="npcink-cloud-portal-jwt-secret-prod-32b",
        portal_public_base_url="https://cloud.example.com",
        portal_email_smtp_host="smtp.example.com",
        portal_email_from_email="no-reply@example.com",
    )

    providers = build_provider_adapters(production_settings)

    assert "openai" not in providers
