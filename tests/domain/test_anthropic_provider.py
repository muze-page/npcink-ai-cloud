from __future__ import annotations

import json

import httpx

from app.adapters.providers.anthropic import AnthropicProviderAdapter
from app.adapters.providers.base import ProviderExecutionError, ProviderExecutionRequest


def _build_request(
    *,
    model_id: str,
    input_payload: dict[str, object],
) -> ProviderExecutionRequest:
    return ProviderExecutionRequest(
        run_id="run_anthropic_provider_test",
        site_id="site_alpha",
        ability_name="magick-ai/workflows/generate-post-draft",
        profile_id="text.balanced",
        execution_kind="text",
        model_id=model_id,
        instance_id="anthropic-global-text-balanced",
        endpoint_variant="messages",
        trace_id="trace_anthropic_provider_test",
        input_payload=input_payload,
        policy={},
        timeout_ms=5_000,
    )


def test_anthropic_adapter_fetches_catalog_over_http() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v1/models")
        assert request.headers["x-api-key"] == "test-api-key"
        assert request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "claude-3-5-haiku-latest", "display_name": "Claude Haiku"},
                    {"id": "claude-3-7-sonnet-latest", "display_name": "Claude Sonnet"},
                    {"id": "claude-3-opus-latest", "display_name": "Claude Opus"},
                ]
            },
        )

    adapter = AnthropicProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    snapshot = adapter.fetch_catalog()

    assert snapshot.provider_id == "anthropic"
    assert [model.model_id for model in snapshot.models] == [
        "claude-3-5-haiku-latest",
        "claude-3-7-sonnet-latest",
        "claude-3-opus-latest",
    ]
    assert snapshot.models[0].instances[0].endpoint_variant == "messages"
    assert snapshot.models[0].instances[0].capability_tags == ["text", "economy"]
    assert snapshot.models[1].instances[0].capability_tags == ["text", "balanced"]
    assert snapshot.models[2].instances[0].capability_tags == ["text", "quality"]


def test_anthropic_adapter_executes_messages_over_http() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v1/messages")
        assert request.headers["x-api-key"] == "test-api-key"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "claude-3-7-sonnet-latest"
        assert payload["system"] == "be concise"
        assert payload["messages"][0]["content"] == "write a short draft"
        return httpx.Response(
            200,
            json={
                "model": "claude-3-7-sonnet-latest",
                "content": [{"type": "text", "text": "anthropic hosted response"}],
                "usage": {"input_tokens": 12, "output_tokens": 6},
                "stop_reason": "end_turn",
            },
        )

    adapter = AnthropicProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.execute(
        _build_request(
            model_id="claude-3-7-sonnet-latest",
            input_payload={
                "messages": [
                    {"role": "system", "content": "be concise"},
                    {"role": "user", "content": "write a short draft"},
                ],
                "max_tokens": 256,
            },
        )
    )

    assert result.output["output_text"] == "anthropic hosted response"
    assert result.output["model_id"] == "claude-3-7-sonnet-latest"
    assert result.tokens_in == 12
    assert result.tokens_out == 6
    assert result.finish_reason == "end_turn"


def test_anthropic_adapter_maps_http_errors_to_runtime_taxonomy() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            400,
            json={
                "error": {
                    "type": "invalid_request_error",
                    "message": "messages must not be empty",
                }
            },
        )

    adapter = AnthropicProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    try:
        adapter.execute(
            _build_request(
                model_id="claude-3-7-sonnet-latest",
                input_payload={"messages": []},
            )
        )
    except ProviderExecutionError as error:
        assert error.error_code == "provider.invalid_request"
        assert error.retryable is False
    else:
        raise AssertionError("expected provider execution error")


def test_anthropic_adapter_rejects_sample_execution_when_fallback_is_disabled() -> None:
    adapter = AnthropicProviderAdapter(
        allow_sample_catalog=False,
        allow_sample_execution=False,
    )

    try:
        adapter.execute(
            _build_request(
                model_id="claude-3-7-sonnet-latest",
                input_payload={"messages": [{"role": "user", "content": "hello"}]},
            )
        )
    except ProviderExecutionError as error:
        assert error.error_code == "provider.auth_invalid"
        assert error.retryable is False
    else:
        raise AssertionError("expected provider execution error")
