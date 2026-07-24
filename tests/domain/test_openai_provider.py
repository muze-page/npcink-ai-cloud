from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.adapters.providers import openai as openai_provider
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
    assert model.raw_json is not None
    assert "response_formats" not in model.raw_json


def test_openai_adapter_rejects_non_exact_image_output_hosts() -> None:
    with pytest.raises(ValueError, match="exact host names"):
        OpenAIProviderAdapter(image_output_hosts=["*.provider.example"])


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


def test_openai_adapter_applies_provider_default_reasoning_effort() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["reasoning_effort"] == "none"
        return httpx.Response(
            200,
            json={
                "model": "qwen3.5:9b",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "正文"},
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 2},
            },
        )

    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        default_reasoning_effort="none",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.execute(
        _build_request(
            execution_kind="text",
            endpoint_variant="chat_completions",
            model_id="qwen3.5:9b",
            input_payload={"messages": [{"role": "user", "content": "给出正文"}]},
        )
    )

    assert result.output["output_text"] == "正文"


def test_openai_adapter_request_extra_overrides_provider_default_reasoning_effort() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["reasoning_effort"] == "high"
        return httpx.Response(
            200,
            json={
                "model": "reasoning-model",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "ok"},
                    }
                ],
                "usage": {},
            },
        )

    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        default_reasoning_effort="none",
        transport=httpx.MockTransport(handler),
    )

    adapter.execute(
        _build_request(
            execution_kind="text",
            endpoint_variant="chat_completions",
            model_id="reasoning-model",
            input_payload={
                "messages": [{"role": "user", "content": "think"}],
                "params": {"extra": {"reasoning_effort": "high"}},
            },
        )
    )


def test_openai_adapter_rejects_unknown_default_reasoning_effort() -> None:
    with pytest.raises(ValueError, match="default_reasoning_effort"):
        OpenAIProviderAdapter(default_reasoning_effort="disabled")


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


def test_provider_execution_request_repr_hides_input_payload() -> None:
    request = _build_request(
        execution_kind="vision",
        endpoint_variant="responses",
        model_id="gpt-4.1",
        input_payload={
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": "data:image/png;base64,c2Vuc2l0aXZlLWltYWdl",
                        }
                    ],
                }
            ]
        },
    )

    serialized = repr(request)

    assert "input_payload" not in serialized
    assert "c2Vuc2l0aXZlLWltYWdl" not in serialized


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


def test_openai_adapter_normalizes_request_metadata_for_compatible_providers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["metadata"] == {
            "source_surface": "wordpress_ai_connector",
            "suggestion_only": "true",
            "reference_count": "2",
        }
        return httpx.Response(
            200,
            json={
                "model": "kimi-k2.6",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "normalized"},
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 2},
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
            model_id="kimi-k2.6",
            input_payload={
                "messages": [{"role": "user", "content": "hello"}],
                "metadata": {
                    "source_surface": " wordpress_ai_connector ",
                    "suggestion_only": True,
                    "reference_count": 2,
                    "nested": {"omit": True},
                },
            },
        )
    )

    assert result.output["output_text"] == "normalized"


def test_openai_adapter_retries_when_compatible_provider_requires_temperature_one() -> None:
    seen_temperatures: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        seen_temperatures.append(payload.get("temperature"))
        if len(seen_temperatures) == 1:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "invalid temperature: only 1 is allowed for this model",
                        "type": "invalid_request_error",
                    }
                },
            )
        assert payload["temperature"] == 1
        return httpx.Response(
            200,
            json={
                "model": "kimi-k2.6",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "compatible"},
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 2},
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
            model_id="kimi-k2.6",
            input_payload={
                "messages": [{"role": "user", "content": "hello"}],
                "temperature": 0.2,
            },
        )
    )

    assert result.output["output_text"] == "compatible"
    assert seen_temperatures == [0.2, 1]


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
        assert request.headers["accept-encoding"] == "identity"
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
                    "url": "https://provider.example/raw-usage",
                    "b64_json": "must-not-escape",
                    "provider_response_format": "url",
                },
            },
        )

    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        image_output_hosts=["EXAMPLE.test."],
        image_response_format="url",
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
                "n": 2,
            },
        )
    )

    assert result.output == {
        "model_id": GROK_IMAGINE_IMAGE_MODEL_ID,
        "candidate_count": 1,
        "usage": {"prompt_tokens": 12, "cost_in_usd_ticks": 130000},
    }
    assert len(result.media_candidates) == 1
    candidate = result.media_candidates[0]
    assert candidate.source_url == "https://example.test/generated-one.png"
    assert candidate.content_bytes is None
    assert candidate.image_output_hosts == ("example.test",)
    assert candidate.claimed_mime_type == "image/png"
    assert candidate.revised_prompt == "A clean studio product photo"
    assert "generated-one.png" not in repr(candidate)
    assert result.tokens_in == 12
    assert result.tokens_out == 0
    assert result.cost == 0.0013


def test_openai_adapter_records_direct_image_cost_in_usd() -> None:
    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "b64_json": base64.b64encode(
                                openai_provider.SAMPLE_IMAGE_PNG
                            ).decode("ascii")
                        }
                    ],
                    "usage": {"prompt_tokens": 11, "cost_in_usd": 0.004321},
                },
            )
        ),
    )

    result = adapter.execute(
        _build_request(
            execution_kind="image_generation",
            endpoint_variant="image_generations",
            model_id=GROK_IMAGINE_IMAGE_MODEL_ID,
            input_payload={"prompt": "A small web illustration"},
        )
    )

    assert result.tokens_in == 11
    assert result.cost == 0.004321
    assert result.output["usage"] == {
        "prompt_tokens": 11,
        "cost_in_usd": 0.004321,
    }


def test_openai_adapter_discards_non_finite_image_usage_and_dimensions() -> None:
    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=json.dumps(
                    {
                        "data": [
                            {
                                "b64_json": base64.b64encode(
                                    openai_provider.SAMPLE_IMAGE_PNG
                                ).decode("ascii"),
                                "width": float("inf"),
                                "height": float("nan"),
                            }
                        ],
                        "usage": {
                            "prompt_tokens": float("nan"),
                            "total_tokens": float("-inf"),
                            "cost_in_usd": float("inf"),
                        },
                    }
                ).encode("utf-8"),
            )
        ),
    )

    result = adapter.execute(
        _build_request(
            execution_kind="image_generation",
            endpoint_variant="image_generations",
            model_id=GROK_IMAGINE_IMAGE_MODEL_ID,
            input_payload={"prompt": "A small web illustration"},
        )
    )

    assert result.tokens_in == 0
    assert result.cost == 0.0
    assert result.output["usage"] == {}
    assert result.media_candidates[0].claimed_width is None
    assert result.media_candidates[0].claimed_height is None


@pytest.mark.parametrize(
    ("status_code", "expected_error_code", "expected_retryable"),
    [
        (400, "provider.invalid_request", False),
        (500, "provider.upstream_error", True),
    ],
)
def test_openai_adapter_never_exposes_image_generation_error_bodies(
    status_code: int,
    expected_error_code: str,
    expected_retryable: bool,
) -> None:
    leaked_body = {
        "error": {
            "message": (
                "private prompt https://images.provider.test/generated.png?sig=secret "
                'b64_json="c2Vuc2l0aXZlLWltYWdl"'
            )
        }
    }
    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(status_code, json=leaked_body)
        ),
    )

    with pytest.raises(ProviderExecutionError) as error:
        adapter.execute(
            _build_request(
                execution_kind="image_generation",
                endpoint_variant="image_generations",
                model_id=GROK_IMAGINE_IMAGE_MODEL_ID,
                input_payload={"prompt": "A private product concept"},
            )
        )

    assert error.value.error_code == expected_error_code
    assert error.value.message == openai_provider.IMAGE_GENERATION_PROVIDER_ERROR_MESSAGE
    assert error.value.retryable is expected_retryable
    serialized_error = repr(error.value.args)
    assert "images.provider.test" not in serialized_error
    assert "b64_json" not in serialized_error
    assert "private prompt" not in serialized_error


@pytest.mark.parametrize(
    ("status_code", "expected_error_code", "expected_retryable"),
    [
        (400, "provider.invalid_request", False),
        (500, "provider.upstream_error", True),
    ],
)
def test_openai_adapter_never_exposes_vision_error_bodies(
    status_code: int,
    expected_error_code: str,
    expected_retryable: bool,
) -> None:
    leaked_marker = "c2Vuc2l0aXZlLWltYWdl"
    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                status_code,
                json={
                    "error": {
                        "message": (
                            "private image echoed as "
                            f"data:image/png;base64,{leaked_marker}"
                        )
                    }
                },
            )
        ),
    )

    with pytest.raises(ProviderExecutionError) as error:
        adapter.execute(
            _build_request(
                execution_kind="vision",
                endpoint_variant="responses",
                model_id="gpt-4.1",
                input_payload={
                    "input": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_image",
                                    "image_url": f"data:image/png;base64,{leaked_marker}",
                                }
                            ],
                        }
                    ]
                },
            )
        )

    assert error.value.error_code == expected_error_code
    assert error.value.message == openai_provider.VISION_PROVIDER_ERROR_MESSAGE
    assert error.value.retryable is expected_retryable
    assert leaked_marker not in repr(error.value.args)


def test_openai_adapter_strictly_decodes_provider_base64_without_serializing_it() -> None:
    image_bytes = b"provider-image-bytes"

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["response_format"] == "b64_json"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "b64_json": base64.b64encode(image_bytes).decode("ascii"),
                        "mime_type": "image/webp",
                        "width": 512,
                        "height": 256,
                    }
                ]
            },
        )

    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        image_response_format="b64_json",
        transport=httpx.MockTransport(handler),
    )
    result = adapter.execute(
        _build_request(
            execution_kind="image_generation",
            endpoint_variant="image_generations",
            model_id=GROK_IMAGINE_IMAGE_MODEL_ID,
            input_payload={"prompt": "A small web illustration"},
        )
    )

    assert result.output == {
        "model_id": GROK_IMAGINE_IMAGE_MODEL_ID,
        "candidate_count": 1,
        "usage": {},
    }
    assert "b64_json" not in json.dumps(result.output)
    candidate = result.media_candidates[0]
    assert candidate.content_bytes == image_bytes
    assert candidate.source_url is None
    assert candidate.claimed_mime_type == "image/webp"
    assert candidate.claimed_width == 512
    assert candidate.claimed_height == 256
    assert "provider-image-bytes" not in repr(candidate)


@pytest.mark.parametrize(
    "candidate_payload",
    [
        {"b64_json": "not strict base64"},
        {
            "b64_json": base64.b64encode(b"image").decode("ascii"),
            "url": "https://cdn.example.test/image.png",
        },
    ],
)
def test_openai_adapter_rejects_invalid_or_ambiguous_image_sources(
    candidate_payload: dict[str, str],
) -> None:
    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "data": [candidate_payload],
                    "usage": {"prompt_tokens": 7, "cost_in_usd_ticks": 230000},
                },
            )
        ),
    )

    with pytest.raises(ProviderExecutionError) as error:
        adapter.execute(
            _build_request(
                execution_kind="image_generation",
                endpoint_variant="image_generations",
                model_id=GROK_IMAGINE_IMAGE_MODEL_ID,
                input_payload={"prompt": "A small web illustration"},
            )
        )

    assert error.value.error_code == "provider.output_contract_invalid"
    assert error.value.tokens_in == 7
    assert error.value.cost == 0.0023


def test_openai_adapter_enforces_decoded_image_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(openai_provider, "MAX_PROVIDER_IMAGE_BYTES", 4)
    monkeypatch.setattr(openai_provider, "MAX_PROVIDER_IMAGE_BASE64_CHARS", 8)
    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"data": [{"b64_json": base64.b64encode(b"12345").decode("ascii")}]},
            )
        ),
    )

    with pytest.raises(ProviderExecutionError) as error:
        adapter.execute(
            _build_request(
                execution_kind="image_generation",
                endpoint_variant="image_generations",
                model_id=GROK_IMAGINE_IMAGE_MODEL_ID,
                input_payload={"prompt": "A small web illustration"},
            )
        )

    assert error.value.error_code == "provider.output_contract_invalid"
    assert "decoded byte limit" in error.value.message


def test_openai_adapter_enforces_candidate_count_and_aggregate_image_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded_image = base64.b64encode(b"1234").decode("ascii")
    responses = iter(
        [
            {"data": [{"b64_json": encoded_image}] * 5},
            {"data": [{"b64_json": encoded_image}, {"b64_json": encoded_image}]},
        ]
    )
    monkeypatch.setattr(openai_provider, "MAX_PROVIDER_IMAGE_TOTAL_BYTES", 7)
    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=next(responses))),
    )
    request = _build_request(
        execution_kind="image_generation",
        endpoint_variant="image_generations",
        model_id=GROK_IMAGINE_IMAGE_MODEL_ID,
        input_payload={"prompt": "A small web illustration"},
    )

    with pytest.raises(ProviderExecutionError, match="exceeds 4 candidates"):
        adapter.execute(request)
    with pytest.raises(ProviderExecutionError, match="aggregate decoded byte limit"):
        adapter.execute(request)


def test_openai_adapter_rejects_oversized_image_response_before_json_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(openai_provider, "MAX_PROVIDER_IMAGE_RESPONSE_BYTES", 16)
    adapter = OpenAIProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=b"x" * 17)),
    )

    with pytest.raises(ProviderExecutionError) as error:
        adapter.execute(
            _build_request(
                execution_kind="image_generation",
                endpoint_variant="image_generations",
                model_id=GROK_IMAGINE_IMAGE_MODEL_ID,
                input_payload={"prompt": "A small web illustration"},
            )
        )

    assert error.value.error_code == "provider.output_contract_invalid"
    assert "encoded response byte limit" in error.value.message


def test_openai_adapter_sample_image_uses_typed_static_bytes() -> None:
    adapter = OpenAIProviderAdapter()

    result = adapter.execute(
        _build_request(
            execution_kind="image_generation",
            endpoint_variant="image_generations",
            model_id=GROK_IMAGINE_IMAGE_MODEL_ID,
            input_payload={"prompt": "A sample image"},
        )
    )

    assert result.output == {
        "model_id": GROK_IMAGINE_IMAGE_MODEL_ID,
        "candidate_count": 1,
    }
    assert result.media_candidates[0].content_bytes == openai_provider.SAMPLE_IMAGE_PNG
    assert result.media_candidates[0].source_url is None


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
