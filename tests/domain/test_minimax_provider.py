from __future__ import annotations

import json

import httpx

from app.adapters.providers.base import ProviderExecutionRequest
from app.adapters.providers.minimax import MiniMaxProviderAdapter
from app.domain.hosted_model_defaults import AUDIO_NARRATION_MODEL_ID


def _build_request(
    *,
    input_payload: dict[str, object] | None = None,
) -> ProviderExecutionRequest:
    return ProviderExecutionRequest(
        run_id="run_audio_provider_test",
        site_id="site_alpha",
        ability_name="npcink-cloud/generate-audio",
        profile_id="audio.narration.default",
        execution_kind="audio_generation",
        model_id=AUDIO_NARRATION_MODEL_ID,
        instance_id="minimax-global-speech-28-turbo",
        endpoint_variant="t2a_v2",
        trace_id="trace-audio-provider",
        input_payload=input_payload
        or {
            "contract_version": "audio_generation_request.v1",
            "intent": "article_narration",
            "text": "这是一段文章旁白。",
            "voice_id": "male-qn-qingse",
            "format": "mp3",
            "response_format": "url",
        },
        policy={"allow_fallback": False},
        timeout_ms=30000,
    )


def test_minimax_adapter_fetches_audio_catalog() -> None:
    adapter = MiniMaxProviderAdapter(
        api_key="test-api-key",
        group_id="test-group",
    )

    snapshot = adapter.fetch_catalog()

    assert snapshot.provider_id == "minimax"
    assert snapshot.display_name == "MiniMax"
    models = {model.model_id: model for model in snapshot.models}
    assert "speech-2.8-turbo" in models
    assert "speech-2.8-hd" in models
    assert "speech-2.6-turbo" in models
    assert "image-01" in models
    assert "MiniMax-Hailuo-02" in models
    assert "MiniMax-M3" in models
    assert models["speech-2.8-turbo"].feature == "audio_generation"
    assert models["speech-2.8-turbo"].status == "available"
    assert models["speech-2.8-turbo"].instances[0].endpoint_variant == "t2a_v2"
    assert models["MiniMax-M3"].feature == "text"
    assert models["MiniMax-M3"].status == "available"
    assert models["MiniMax-M3"].instances[0].endpoint_variant == "chat_completions"
    assert models["speech-2.6-turbo"].status == "catalog_only"
    assert models["speech-2.6-turbo"].instances == []


def test_minimax_adapter_executes_text_over_openai_compatible_chat() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v1/chat/completions")
        assert request.headers["Authorization"] == "Bearer test-api-key"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "MiniMax-M3"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "MiniMax text result",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 8,
                    "completion_tokens": 4,
                    "total_tokens": 12,
                },
            },
        )

    adapter = MiniMaxProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.execute(
        ProviderExecutionRequest(
            run_id="run_minimax_text_provider_test",
            site_id="site_alpha",
            ability_name="npcink-cloud/wp-ai-connector",
            profile_id="wp-ai.short-text",
            execution_kind="text",
            model_id="MiniMax-M3",
            instance_id="minimax-global-minimax-m3",
            endpoint_variant="chat_completions",
            trace_id="trace-minimax-text-provider",
            input_payload={"messages": [{"role": "user", "content": "Say hi"}]},
            policy={"allow_fallback": False},
            timeout_ms=30000,
        )
    )

    assert result.output["output_text"] == "MiniMax text result"
    assert result.tokens_in == 8
    assert result.tokens_out == 4


def test_minimax_adapter_executes_t2a_over_http() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v1/t2a_v2")
        assert "GroupId" not in request.url.params
        assert request.headers["Authorization"] == "Bearer test-api-key"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == AUDIO_NARRATION_MODEL_ID
        assert payload["text"] == "这是一段文章旁白。"
        assert payload["stream"] is False
        assert payload["voice_setting"]["voice_id"] == "male-qn-qingse"
        assert payload["voice_setting"]["speed"] == 1
        assert payload["voice_setting"]["vol"] == 1
        assert payload["voice_setting"]["pitch"] == 0
        assert payload["audio_setting"]["format"] == "mp3"
        return httpx.Response(
            200,
            json={
                "trace_id": "trace-from-minimax",
                "data": {
                    "audio_url": "https://example.test/audio/run.mp3",
                    "extra_info": {
                        "usage_characters": 9,
                        "audio_length": 2400,
                        "audio_format": "mp3",
                    },
                },
                "base_resp": {"status_code": 0, "status_msg": "success"},
            },
        )

    adapter = MiniMaxProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.execute(_build_request())

    assert result.output["artifact_type"] == "audio_generation_candidates"
    assert result.output["direct_wordpress_write"] is False
    assert result.output["provider_response_format"] == "url"
    assert result.output["audios"][0]["url"] == "https://example.test/audio/run.mp3"
    assert result.output["audios"][0]["duration_seconds"] == 2.4
    assert result.tokens_in == 9
    assert result.tokens_out == 0


def test_minimax_adapter_preserves_optional_group_id_for_legacy_accounts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v1/t2a_v2")
        assert request.url.params["GroupId"] == "test-group"
        return httpx.Response(
            200,
            json={
                "data": {
                    "audio": "000102",
                    "extra_info": {
                        "usage_characters": 9,
                        "audio_length": 2400,
                        "audio_format": "mp3",
                    },
                },
                "base_resp": {"status_code": 0, "status_msg": "success"},
            },
        )

    adapter = MiniMaxProviderAdapter(
        api_key="test-api-key",
        group_id="test-group",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.execute(_build_request())

    assert result.output["provider_response_format"] == "b64_json"
    assert result.output["audios"][0]["b64_json"]


def test_minimax_adapter_reads_top_level_extra_info() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {"audio": "000102"},
                "extra_info": {
                    "usage_characters": 11,
                    "audio_length": 3200,
                    "audio_format": "mp3",
                },
                "base_resp": {"status_code": 0, "status_msg": "success"},
            },
        )

    adapter = MiniMaxProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.execute(_build_request())

    assert result.tokens_in == 11
    assert result.output["audios"][0]["duration_seconds"] == 3.2


def test_minimax_adapter_reads_domestic_audio_url_from_audio_field() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "audio": "https://minimax.example/audio/run.mp3",
                    "status": 1,
                    "ced": "",
                },
                "extra_info": {
                    "usage_characters": 11,
                    "audio_length": 3200,
                    "audio_format": "mp3",
                },
                "base_resp": {"status_code": 0, "status_msg": "success"},
            },
        )

    adapter = MiniMaxProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.execute(_build_request())

    assert result.output["provider_response_format"] == "url"
    assert result.output["audios"][0]["url"] == "https://minimax.example/audio/run.mp3"
    assert result.output["audios"][0]["b64_json"] == ""
