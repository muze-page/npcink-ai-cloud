from __future__ import annotations

import json

import httpx

from app.adapters.providers.base import ProviderExecutionRequest
from app.adapters.providers.minimax import (
    MINIMAX_OFFICIAL_SCHEMA_SOURCES,
    MiniMaxProviderAdapter,
)
from app.domain.hosted_model_defaults import AUDIO_NARRATION_MODEL_ID


def _schema_payload(model_ids: list[str]) -> dict[str, object]:
    return {
        "openapi": "3.1.0",
        "components": {
            "schemas": {
                "Request": {
                    "properties": {
                        "model": {
                            "type": "string",
                            "enum": model_ids,
                        }
                    }
                }
            }
        },
    }


def _build_catalog_transport(
    *,
    official_models: list[dict[str, object]],
    schema_models: dict[str, list[str]],
    assert_auth: bool = True,
) -> httpx.MockTransport:
    source_by_url = {source.url: source for source in MINIMAX_OFFICIAL_SCHEMA_SOURCES}

    def handler(request: httpx.Request) -> httpx.Response:
        request_url = str(request.url)
        if request.url.path.endswith("/v1/models"):
            if assert_auth:
                assert request.headers["Authorization"] == "Bearer test-api-key"
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": official_models,
                },
            )
        source = source_by_url.get(request_url)
        if source is not None:
            assert "Authorization" not in request.headers
            return httpx.Response(200, json=_schema_payload(schema_models.get(source.name, [])))
        return httpx.Response(404, json={"message": f"unexpected URL: {request_url}"})

    return httpx.MockTransport(handler)


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


def test_minimax_adapter_fetches_official_model_catalog_and_enriches_metadata() -> None:
    adapter = MiniMaxProviderAdapter(
        api_key="test-api-key",
        group_id="test-group",
        transport=_build_catalog_transport(
            official_models=[
                {"id": "speech-2.8-turbo", "object": "model", "owned_by": "minimax"},
                {"id": "MiniMax-M3", "object": "model", "owned_by": "minimax"},
                {"id": "image-01", "object": "model", "owned_by": "minimax"},
            ],
            schema_models={
                "speech_t2a_asyncapi": ["speech-2.8-turbo", "speech-2.8-hd"],
                "image_text_to_image_openapi": ["image-01"],
                "image_image_to_image_openapi": ["image-01", "image-01-live"],
                "video_text_to_video_openapi": ["MiniMax-Hailuo-2.3", "T2V-01"],
                "video_image_to_video_openapi": [
                    "MiniMax-Hailuo-2.3",
                    "MiniMax-Hailuo-2.3-Fast",
                    "I2V-01",
                ],
            },
        ),
    )

    snapshot = adapter.fetch_catalog()

    assert snapshot.provider_id == "minimax"
    assert snapshot.display_name == "MiniMax"
    models = {model.model_id: model for model in snapshot.models}
    assert list(models) == [
        "speech-2.8-turbo",
        "MiniMax-M3",
        "image-01",
        "speech-2.8-hd",
        "image-01-live",
        "MiniMax-Hailuo-2.3",
        "T2V-01",
        "MiniMax-Hailuo-2.3-Fast",
        "I2V-01",
    ]
    assert "speech-2.8-turbo" in models
    assert "speech-2.8-hd" in models
    assert "image-01" in models
    assert "image-01-live" in models
    assert "MiniMax-M3" in models
    assert "MiniMax-Hailuo-2.3" in models
    assert "MiniMax-Hailuo-2.3-Fast" in models
    assert "T2V-01" in models
    assert "I2V-01" in models
    assert models["speech-2.8-turbo"].feature == "audio_generation"
    assert models["speech-2.8-turbo"].status == "available"
    assert models["speech-2.8-turbo"].instances[0].endpoint_variant == "t2a_v2"
    assert models["speech-2.8-turbo"].raw_json["source"] == "official_models_endpoint"
    assert models["speech-2.8-hd"].feature == "audio_generation"
    assert models["speech-2.8-hd"].instances[0].endpoint_variant == "t2a_v2"
    assert models["speech-2.8-hd"].raw_json["source"] == "official_schema_model_enum"
    assert models["speech-2.8-hd"].raw_json["official_schema_source_names"] == [
        "speech_t2a_asyncapi"
    ]
    assert models["MiniMax-M3"].feature == "text"
    assert models["MiniMax-M3"].status == "available"
    assert models["MiniMax-M3"].instances[0].endpoint_variant == "chat_completions"
    assert models["image-01"].feature == "image_generation"
    assert models["image-01"].instances == []
    assert models["image-01-live"].feature == "image_generation"
    assert models["image-01-live"].raw_json["source"] == "official_schema_model_enum"
    assert models["MiniMax-Hailuo-2.3"].feature == "video_generation"
    assert models["MiniMax-Hailuo-2.3"].raw_json["source"] == "official_schema_model_enum"
    assert models["MiniMax-Hailuo-2.3"].raw_json["official_schema_source_names"] == [
        "video_text_to_video_openapi",
        "video_image_to_video_openapi",
    ]
    assert models["T2V-01"].feature == "video_generation"
    assert models["I2V-01"].feature == "video_generation"


def test_minimax_adapter_adds_schema_models_without_inventing_text_models() -> None:
    adapter = MiniMaxProviderAdapter(
        api_key="test-api-key",
        transport=_build_catalog_transport(
            official_models=[{"id": "MiniMax-M2"}],
            schema_models={
                "speech_t2a_asyncapi": ["speech-2.8-turbo", "speech-2.8-hd"],
                "image_image_to_image_openapi": ["image-01", "image-01-live"],
                "video_image_to_video_openapi": [
                    "MiniMax-Hailuo-2.3",
                    "MiniMax-Hailuo-2.3-Fast",
                ],
            },
        ),
    )

    snapshot = adapter.fetch_catalog()

    model_ids = [model.model_id for model in snapshot.models]
    assert model_ids == [
        "MiniMax-M2",
        "speech-2.8-turbo",
        "speech-2.8-hd",
        "image-01",
        "image-01-live",
        "MiniMax-Hailuo-2.3",
        "MiniMax-Hailuo-2.3-Fast",
    ]
    assert "MiniMax-M3" not in model_ids
    models = {model.model_id: model for model in snapshot.models}
    assert models["MiniMax-M2"].raw_json["source"] == "official_models_endpoint"
    assert models["image-01-live"].raw_json["source"] == "official_schema_model_enum"


def test_minimax_adapter_sample_catalog_is_only_for_unconfigured_dev_fallback() -> None:
    adapter = MiniMaxProviderAdapter(allow_sample_catalog=True)

    snapshot = adapter.fetch_catalog()

    assert {model.model_id for model in snapshot.models} >= {
        "speech-2.8-turbo",
        "speech-2.8-hd",
        "MiniMax-M3",
    }
    assert all(
        model.raw_json and model.raw_json["source"] == "official_models_endpoint"
        for model in snapshot.models
    )


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


def test_minimax_adapter_does_not_forward_chat_metadata() -> None:
    original_input = {
        "input": "Say hi",
        "text": "Say hi",
        "metadata": {
            "source_surface": "wordpress_ai_connector",
            "suggestion_only": True,
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "MiniMax-M2.1"
        assert payload["messages"] == [{"role": "user", "content": "Say hi"}]
        assert "metadata" not in payload
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "MiniMax metadata-safe result",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 4,
                    "total_tokens": 7,
                },
            },
        )

    adapter = MiniMaxProviderAdapter(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.execute(
        ProviderExecutionRequest(
            run_id="run_minimax_metadata_test",
            site_id="site_alpha",
            ability_name="npcink-cloud/wp-ai-connector",
            profile_id="wp-ai.short-text",
            execution_kind="text",
            model_id="MiniMax-M2.1",
            instance_id="minimax-global-minimax-m2-1",
            endpoint_variant="chat_completions",
            trace_id="trace-minimax-metadata-test",
            input_payload=original_input,
            policy={"allow_fallback": False},
            timeout_ms=30000,
        )
    )

    assert original_input["metadata"]["suggestion_only"] is True
    assert result.output["output_text"] == "MiniMax metadata-safe result"


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
