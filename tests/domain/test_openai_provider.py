from __future__ import annotations

import json

import httpx

from app.adapters.providers.base import ProviderExecutionError, ProviderExecutionRequest
from app.adapters.providers.openai import OpenAIProviderAdapter


def test_openai_adapter_fetches_catalog_over_http() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        assert request.headers["Authorization"] == "Bearer test-api-key"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "gpt-4.1-mini",
                        "context_window": 128000,
                    },
                    {
                        "id": "gpt-4.1",
                        "context_window": 128000,
                        "input_modalities": ["text", "image"],
                    },
                    {
                        "id": "text-embedding-3-small",
                        "context_window": 8192,
                    },
                ]
            },
        )

    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    snapshot = adapter.fetch_catalog()

    assert snapshot.provider_id == "openai"
    assert [model.model_id for model in snapshot.models] == [
        "gpt-4.1-mini",
        "gpt-4.1",
        "text-embedding-3-small",
    ]
    assert snapshot.models[0].instances[0].endpoint_variant == "chat_completions"
    assert snapshot.models[0].instances[0].capability_tags == ["text", "balanced"]
    assert snapshot.models[1].feature == "vision"
    assert snapshot.models[1].instances[0].endpoint_variant == "responses"
    assert snapshot.models[2].feature == "embedding"
    assert snapshot.models[2].instances[0].endpoint_variant == "embeddings"


def test_openai_adapter_supports_recognition_sample_profile() -> None:
    adapter = OpenAIProviderAdapter(sample_catalog_profile="recognition_sample")

    snapshot = adapter.fetch_catalog()

    assert [model.model_id for model in snapshot.models] == [
        "gpt-4.1-mini",
        "gpt-4.1",
        "text-embedding-3-small",
        "flux-dev",
        "flux-schnell",
        "sdxl-turbo",
        "llava:13b",
        "qwen2.5-vl-7b-instruct",
        "minicpm-v-2.6",
        "bge-m3",
        "multilingual-e5-large",
        "gte-large-en-v1.5",
        "mistral-small-3.1",
        "gemma-3-27b-it",
        "deepseek-r1-distill-qwen-32b",
        "qwen2.5-72b-instruct",
        "jina-embeddings-v3",
    ]
    assert len(snapshot.models) == 17
    assert snapshot.models[3].instances[0].endpoint_variant == "images"
    assert snapshot.models[4].raw_json["pipeline_tag"] == "text-to-image"
    assert snapshot.models[6].feature == "text"
    assert snapshot.models[7].raw_json["pipeline_tag"] == "image-text-to-text"
    assert snapshot.models[9].feature == "embedding"
    assert snapshot.models[16].raw_json["pipeline_tag"] == "feature-extraction"


def test_openai_adapter_supports_recognition_review_60_sample_profile() -> None:
    adapter = OpenAIProviderAdapter(sample_catalog_profile="recognition_review_60")

    snapshot = adapter.fetch_catalog()

    assert len(snapshot.models) == 60
    assert snapshot.models[0].model_id == "gpt-4.1-mini"
    assert snapshot.models[16].model_id == "jina-embeddings-v3"
    assert snapshot.models[17].model_id == "sample-chat-balanced-001"
    assert snapshot.models[17].instances[0].instance_id == "openai-us-east-sample-chat-balanced-001"
    assert snapshot.models[17].raw_json["catalog_profile"] == "recognition_review_scaled"
    assert snapshot.models[17].raw_json["catalog_profile_variant_index"] == 1
    assert snapshot.models[-1].model_id == "sample-embed-bge-004"


def test_openai_adapter_supports_recognition_review_240_sample_profile() -> None:
    adapter = OpenAIProviderAdapter(sample_catalog_profile="recognition_review_240")

    snapshot = adapter.fetch_catalog()

    assert len(snapshot.models) == 240
    assert snapshot.models[0].model_id == "gpt-4.1-mini"
    assert snapshot.models[17].model_id == "sample-chat-balanced-001"
    assert snapshot.models[28].model_id == "sample-reranker-001"
    assert snapshot.models[-1].model_id == "sample-embed-bge-019"
    assert snapshot.models[-1].raw_json["catalog_profile_variant_index"] == 19


def test_openai_adapter_rejects_sample_catalog_when_fallback_is_disabled() -> None:
    adapter = OpenAIProviderAdapter(
        allow_sample_catalog=False,
        allow_sample_execution=False,
    )

    try:
        adapter.fetch_catalog()
    except RuntimeError as error:
        assert "configured upstream credentials" in str(error)
    else:
        raise AssertionError("expected runtime error")


def test_openai_adapter_executes_chat_with_hosted_params_tools_and_thinking() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert request.url.path.endswith("/chat/completions")
        assert payload["temperature"] == 0.2
        assert payload["max_tokens"] == 123
        assert payload["top_p"] == 0.9
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["tools"][0]["function"]["name"] == "lookup_docs"
        assert payload["tool_choice"] == {
            "type": "function",
            "function": {"name": "lookup_docs"},
        }
        assert payload["metadata"] == {"purpose": "contract"}
        assert payload["parallel_tool_calls"] is False
        assert payload["reasoning"] == {"effort": "medium", "max_reasoning_tokens": 64}
        assert payload["max_reasoning_tokens"] == 64
        return httpx.Response(
            200,
            json={
                "model": "gpt-4.1-mini",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "ok"},
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 3},
            },
        )

    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.execute(
        _build_request(
            execution_kind="text",
            endpoint_variant="chat_completions",
            model_id="gpt-4.1-mini",
            input_payload={
                "messages": [{"role": "user", "content": "hello"}],
                "params": {
                    "temperature": 0.2,
                    "max_tokens": 123,
                    "top_p": 0.9,
                    "response_format": {"type": "json_object"},
                    "metadata": {"purpose": "contract"},
                    "parallel_tool_calls": False,
                },
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup_docs",
                            "description": "Look up docs",
                            "parameters": {"type": "object"},
                        },
                    }
                ],
                "tool_choice": {
                    "type": "function",
                    "function": {"name": "lookup_docs"},
                },
                "thinking": {"budget": "medium", "max_reasoning_tokens": 64},
            },
        )
    )

    assert result.output["output_text"] == "ok"


def _build_request(
    *,
    execution_kind: str,
    endpoint_variant: str,
    model_id: str,
    input_payload: dict[str, object],
) -> ProviderExecutionRequest:
    return ProviderExecutionRequest(
        run_id="run_http_provider_test",
        site_id="site_alpha",
        ability_name="magick-ai/workflows/generate-post-draft",
        profile_id="text.balanced",
        execution_kind=execution_kind,
        model_id=model_id,
        instance_id=f"{endpoint_variant}-instance",
        endpoint_variant=endpoint_variant,
        trace_id="trace_http_provider_test",
        input_payload=input_payload,
        policy={},
        timeout_ms=5_000,
        price_input=0.4,
        price_output=1.6,
    )


def test_openai_adapter_executes_chat_completions_over_http() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["Authorization"] == "Bearer test-api-key"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "gpt-4.1-mini"
        assert payload["messages"][0]["content"] == "write a short draft"
        return httpx.Response(
            200,
            json={
                "model": "gpt-4.1-mini",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "real hosted response",
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                },
            },
        )

    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.execute(
        _build_request(
            execution_kind="text",
            endpoint_variant="chat_completions",
            model_id="gpt-4.1-mini",
            input_payload={
                "messages": [{"role": "user", "content": "write a short draft"}]
            },
        )
    )

    assert result.output["output_text"] == "real hosted response"
    assert result.tokens_in == 10
    assert result.tokens_out == 5
    assert result.cost == 0.000012


def test_openai_adapter_executes_responses_over_http() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/responses")
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "gpt-4.1"
        assert payload["input"][0]["content"] == "describe this image"
        return httpx.Response(
            200,
            json={
                "model": "gpt-4.1",
                "output": [
                    {
                        "type": "message",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "vision summary",
                            }
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 21,
                    "output_tokens": 9,
                },
            },
        )

    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.execute(
        _build_request(
            execution_kind="vision",
            endpoint_variant="responses",
            model_id="gpt-4.1",
            input_payload={
                "messages": [{"role": "user", "content": "describe this image"}]
            },
        )
    )

    assert result.output["output_text"] == "vision summary"
    assert result.tokens_in == 21
    assert result.tokens_out == 9


def test_openai_adapter_executes_embeddings_over_http() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "text-embedding-3-small"
        assert payload["input"] == "hello embeddings"
        return httpx.Response(
            200,
            json={
                "model": "text-embedding-3-small",
                "data": [{"embedding": [0.1, 0.2, 0.3, 0.4]}],
                "usage": {"prompt_tokens": 4},
            },
        )

    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.execute(
        _build_request(
            execution_kind="embedding",
            endpoint_variant="embeddings",
            model_id="text-embedding-3-small",
            input_payload={"text": "hello embeddings"},
        )
    )

    assert result.output["embedding"] == [0.1, 0.2, 0.3, 0.4]
    assert result.output["dimensions"] == 4
    assert result.tokens_in == 4
    assert result.tokens_out == 0


def test_openai_adapter_executes_responses_with_hosted_params_tools_and_text_format() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert request.url.path.endswith("/responses")
        assert payload["max_output_tokens"] == 256
        assert payload["text"]["format"] == {
            "type": "json_schema",
            "json_schema": {"name": "vision_payload", "schema": {"type": "object"}},
        }
        assert payload["tools"] == [
            {
                "type": "function",
                "name": "lookup_docs",
                "description": "Look up docs",
                "parameters": {"type": "object"},
            }
        ]
        assert payload["tool_choice"] == {"type": "function", "name": "lookup_docs"}
        return httpx.Response(
            200,
            json={
                "model": "gpt-4.1",
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc_123",
                        "call_id": "call_123",
                        "name": "lookup_docs",
                        "arguments": "{\"query\":\"hello\"}",
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 4},
            },
        )

    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.execute(
        _build_request(
            execution_kind="vision",
            endpoint_variant="responses",
            model_id="gpt-4.1",
            input_payload={
                "messages": [{"role": "user", "content": "describe this image"}],
                "params": {
                    "max_output_tokens": 256,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "vision_payload",
                            "schema": {"type": "object"},
                        },
                    },
                },
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup_docs",
                            "description": "Look up docs",
                            "parameters": {"type": "object"},
                        },
                    }
                ],
                "tool_choice": {
                    "type": "function",
                    "function": {"name": "lookup_docs"},
                },
            },
        )
    )

    assert result.output["tool_calls"] == [
        {
            "id": "fc_123",
            "type": "function",
            "function": {
                "name": "lookup_docs",
                "arguments": "{\"query\":\"hello\"}",
            },
        }
    ]


def test_openai_adapter_maps_http_errors_to_runtime_taxonomy() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            429,
            json={"error": {"message": "too many requests"}},
        )

    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    try:
        adapter.execute(
            _build_request(
                execution_kind="text",
                endpoint_variant="chat_completions",
                model_id="gpt-4.1-mini",
                input_payload={
                    "messages": [{"role": "user", "content": "rate limit me"}]
                },
            )
        )
    except ProviderExecutionError as error:
        assert error.error_code == "provider.rate_limited"
        assert error.retryable is True
    else:
        raise AssertionError("expected provider execution error")


def test_openai_adapter_rejects_sample_execution_when_fallback_is_disabled() -> None:
    adapter = OpenAIProviderAdapter(
        allow_sample_catalog=False,
        allow_sample_execution=False,
    )

    try:
        adapter.execute(
            _build_request(
                execution_kind="text",
                endpoint_variant="chat_completions",
                model_id="gpt-4.1-mini",
                input_payload={"messages": [{"role": "user", "content": "hello"}]},
            )
        )
    except ProviderExecutionError as error:
        assert error.error_code == "provider.auth_invalid"
        assert error.retryable is False
    else:
        raise AssertionError("expected provider execution error")
