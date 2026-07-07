from __future__ import annotations

import json

import httpx

from app.adapters.providers.base import ProviderExecutionError, ProviderExecutionRequest
from app.adapters.providers.openai import OpenAIProviderAdapter
from app.domain.hosted_model_defaults import GROK_IMAGINE_IMAGE_MODEL_ID


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
                    {
                        "id": GROK_IMAGINE_IMAGE_MODEL_ID,
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
        GROK_IMAGINE_IMAGE_MODEL_ID,
        "text-embedding-3-small",
    ]
    assert snapshot.models[0].instances[0].endpoint_variant == "chat_completions"
    assert snapshot.models[0].instances[0].capability_tags == ["text", "balanced"]
    assert snapshot.models[1].feature == "vision"
    assert snapshot.models[1].instances[0].endpoint_variant == "responses"
    assert snapshot.models[2].feature == "image_generation"
    assert snapshot.models[2].instances[0].endpoint_variant == "image_generations"
    assert snapshot.models[3].feature == "embedding"
    assert snapshot.models[3].instances[0].endpoint_variant == "embeddings"


def test_openai_adapter_classifies_bge_catalog_models_as_embeddings() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "BAAI/bge-m3",
                        "context_window": 8192,
                    }
                ]
            },
        )

    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    snapshot = adapter.fetch_catalog()

    assert snapshot.models[0].model_id == "BAAI/bge-m3"
    assert snapshot.models[0].feature == "embedding"
    assert snapshot.models[0].raw_json["tier"] == "default"
    assert snapshot.models[0].instances[0].endpoint_variant == "embeddings"
    assert snapshot.models[0].instances[0].capability_tags == ["embedding", "default"]


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


def test_openai_adapter_free_gpt55_sample_catalog_profile() -> None:
    adapter = OpenAIProviderAdapter(sample_catalog_profile="free-gpt55")

    snapshot = adapter.fetch_catalog()

    assert snapshot.models[0].model_id == "gpt-5.5"
    assert snapshot.models[0].price_input == 0.0
    assert snapshot.models[0].price_output == 0.0
    assert snapshot.models[0].instances[0].instance_id == "openai-global-free-gpt55"
    assert snapshot.models[0].instances[0].endpoint_variant == "responses"
    assert "free-gpt55" in snapshot.models[0].instances[0].capability_tags
    assert "hosted-free" in snapshot.models[0].instances[0].capability_tags


def test_openai_adapter_sample_catalog_includes_hosted_image_generation() -> None:
    adapter = OpenAIProviderAdapter()

    snapshot = adapter.fetch_catalog()
    model = next(item for item in snapshot.models if item.model_id == GROK_IMAGINE_IMAGE_MODEL_ID)

    assert model.feature == "image_generation"
    assert model.instances[0].endpoint_variant == "image_generations"
    assert "z-image" in model.instances[0].capability_tags


def test_openai_adapter_tags_free_gpt55_from_http_catalog() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "gpt-5.5",
                        "context_window": 256000,
                        "metadata": {"commercial_tier": "free"},
                    }
                ]
            },
        )

    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    snapshot = adapter.fetch_catalog()

    assert snapshot.models[0].model_id == "gpt-5.5"
    assert "free-gpt55" in snapshot.models[0].instances[0].capability_tags
    assert "hosted-free" in snapshot.models[0].instances[0].capability_tags


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
        ability_name="npcink-abilities-toolkit/build-article-block-plan",
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
            input_payload={"messages": [{"role": "user", "content": "write a short draft"}]},
        )
    )

    assert result.output["output_text"] == "real hosted response"
    assert result.tokens_in == 10
    assert result.tokens_out == 5
    assert result.cost == 0.000012


def test_openai_adapter_estimates_deepseek_cache_aware_pricing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "deepseek response",
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 3000,
                    "prompt_cache_hit_tokens": 1000,
                    "prompt_cache_miss_tokens": 2000,
                    "completion_tokens": 3000,
                },
            },
        )

    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    request = _build_request(
        execution_kind="text",
        endpoint_variant="chat_completions",
        model_id="deepseek-v4-flash",
        input_payload={"messages": [{"role": "user", "content": "ops summary"}]},
    )
    request.price_input = None
    request.price_output = None
    result = adapter.execute(request)

    assert result.tokens_in == 3000
    assert result.tokens_out == 3000
    assert result.cost == 0.001123
    assert result.output["usage"]["prompt_cache_hit_tokens"] == 1000


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
            input_payload={"messages": [{"role": "user", "content": "describe this image"}]},
        )
    )

    assert result.output["output_text"] == "vision summary"
    assert result.tokens_in == 21
    assert result.tokens_out == 9


def test_openai_adapter_retries_responses_without_unsupported_metadata() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/responses")
        payload = json.loads(request.content.decode("utf-8"))
        seen_payloads.append(payload)
        if len(seen_payloads) == 1:
            assert payload["metadata"] == {"source_surface": "wordpress_ai_connector"}
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Unsupported parameter: metadata",
                        "param": "metadata",
                        "type": "invalid_request_error",
                    }
                },
            )
        assert "metadata" not in payload
        return httpx.Response(
            200,
            json={
                "model": "gpt-5.5",
                "output": [
                    {
                        "type": "message",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "routed title"}],
                    }
                ],
                "usage": {"input_tokens": 12, "output_tokens": 3},
            },
        )

    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.execute(
        _build_request(
            execution_kind="text",
            endpoint_variant="responses",
            model_id="gpt-5.5",
            input_payload={
                "input": "Generate exactly one concise title.",
                "metadata": {"source_surface": "wordpress_ai_connector"},
            },
        )
    )

    assert result.output["output_text"] == "routed title"
    assert len(seen_payloads) == 2


def test_openai_adapter_retries_responses_404_with_chat_completions_messages() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        payload = json.loads(request.content.decode("utf-8"))
        if request.url.path.endswith("/responses"):
            assert payload["model"] == "gpt-4.1"
            return httpx.Response(404, json={"error": {"message": "not found"}})
        assert request.url.path.endswith("/chat/completions")
        assert payload["messages"][0]["content"][0]["type"] == "text"
        assert payload["messages"][0]["content"][1]["type"] == "image_url"
        return httpx.Response(
            200,
            json={
                "model": "gpt-4.1",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Blue ceramic mug on a white table.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 18, "completion_tokens": 9},
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
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Write alt text."},
                            {"type": "input_image", "image_url": "https://example.com/mug.png"},
                        ],
                    }
                ],
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Write alt text."},
                            {
                                "type": "image_url",
                                "image_url": {"url": "https://example.com/mug.png"},
                            },
                        ],
                    }
                ],
            },
        )
    )

    assert seen_paths == ["/v1/responses", "/v1/chat/completions"]
    assert result.output["output_text"] == "Blue ceramic mug on a white table."
    assert result.tokens_in == 18
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


def test_openai_adapter_executes_image_generation_over_http() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/images/generations")
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == GROK_IMAGINE_IMAGE_MODEL_ID
        assert payload["prompt"] == "A clean product photo of a red running shoe"
        assert payload["aspect_ratio"] == "16:9"
        assert payload["resolution"] == "high"
        assert payload["response_format"] == "url"
        assert payload["n"] == 2
        return httpx.Response(
            200,
            json={
                "model": GROK_IMAGINE_IMAGE_MODEL_ID,
                "data": [
                    {
                        "url": "https://example.test/generated-one.png",
                        "revised_prompt": "A clean studio product photo",
                        "mime_type": "image/png",
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "cost_in_usd_ticks": 130000,
                },
            },
        )

    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.execute(
        _build_request(
            execution_kind="image_generation",
            endpoint_variant="image_generations",
            model_id=GROK_IMAGINE_IMAGE_MODEL_ID,
            input_payload={
                "prompt": "A clean product photo of a red running shoe",
                "aspect_ratio": "16:9",
                "resolution": "high",
                "response_format": "url",
                "n": 2,
            },
        )
    )

    assert result.output["artifact_type"] == "image_generation_candidates"
    assert result.output["direct_wordpress_write"] is False
    assert result.output["images"][0]["url"] == "https://example.test/generated-one.png"
    assert result.tokens_in == 12
    assert result.tokens_out == 0
    assert result.cost == 0.0013


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
                        "arguments": '{"query":"hello"}',
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
                "arguments": '{"query":"hello"}',
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
                input_payload={"messages": [{"role": "user", "content": "rate limit me"}]},
            )
        )
    except ProviderExecutionError as error:
        assert error.error_code == "provider.rate_limited"
        assert error.retryable is True
    else:
        raise AssertionError("expected provider execution error")


def test_openai_adapter_bounds_upstream_error_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(500, text="x" * 5000)

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
                input_payload={"messages": [{"role": "user", "content": "fail"}]},
            )
        )
    except ProviderExecutionError as error:
        assert error.error_code == "provider.upstream_error"
        assert len(error.message) < 4100
        assert error.message.endswith("...[truncated]")
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
