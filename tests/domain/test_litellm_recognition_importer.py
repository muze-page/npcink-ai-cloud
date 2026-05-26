from __future__ import annotations

import httpx

from app.adapters.recognition.litellm import LiteLLMRecognitionEvidenceImporter


def test_litellm_importer_fetches_recognition_evidence_over_http() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/model/info")
        assert request.headers["Authorization"] == "Bearer litellm-test-key"
        return httpx.Response(
            200,
            headers={"etag": "litellm-rev-001"},
            json={
                "data": [
                    {
                        "model_name": "openai/gpt-4.1",
                        "litellm_params": {
                            "model": "openai/gpt-4.1",
                            "custom_llm_provider": "openai",
                        },
                        "model_info": {
                            "litellm_provider": "openai",
                            "mode": "chat",
                            "supports_vision": True,
                            "supports_function_calling": True,
                            "supports_response_schema": True,
                            "input_cost_per_token": 0.0000004,
                            "output_cost_per_token": 0.0000016,
                        },
                    },
                    {
                        "model_name": "text-embedding-3-small",
                        "litellm_params": {
                            "model": "text-embedding-3-small",
                            "custom_llm_provider": "openai",
                        },
                        "model_info": {
                            "litellm_provider": "openai",
                            "mode": "embedding",
                            "input_cost_per_token": 0.00000002,
                        },
                    },
                    {
                        "model_name": "openai/flux-dev",
                        "litellm_params": {
                            "model": "openai/flux-dev",
                            "custom_llm_provider": "openai",
                        },
                        "model_info": {
                            "litellm_provider": "openai",
                            "mode": "image_generation",
                            "input_cost_per_token": 0.000002,
                        },
                    },
                ]
            },
        )

    importer = LiteLLMRecognitionEvidenceImporter(
        base_url="https://litellm.example.test",
        api_key="litellm-test-key",
        transport=httpx.MockTransport(handler),
    )

    payload = importer.fetch_upstream_evidence_payload()

    gpt = payload["records"]["openai::gpt-4.1"]
    embed = payload["records"]["openai::text-embedding-3-small"]
    flux = payload["records"]["openai::flux-dev"]

    assert payload["version"] == "recognition_upstream_v1"
    assert payload["sources"]["litellm_revision"] == "litellm-rev-001"
    assert payload["sources"]["hf_snapshot"] == "unconfigured"

    assert gpt["model_type"] == "vision"
    assert gpt["preview_type"] == "text"
    assert gpt["price_input"] == 0.4
    assert gpt["price_output"] == 1.6
    assert gpt["capabilities"]["vision"] is True
    assert gpt["capabilities"]["tools"] is True
    assert gpt["capabilities"]["structured_output"] is True

    assert embed["model_type"] == "embedding"
    assert embed["preview_type"] == "embedding"
    assert embed["price_input"] == 0.02
    assert embed["price_output"] is None
    assert embed["output_modalities"] == ["embedding"]

    assert flux["model_type"] == "image_generation"
    assert flux["preview_type"] == "image"
    assert flux["price_input"] == 2.0
    assert flux["price_output"] is None
    assert flux["capabilities"]["image_output"] is True


def test_litellm_importer_raises_for_invalid_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"invalid": True})

    importer = LiteLLMRecognitionEvidenceImporter(
        base_url="https://litellm.example.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        importer.fetch_upstream_evidence_payload()
    except ValueError as error:
        assert "missing data list" in str(error)
    else:
        raise AssertionError("expected invalid payload to raise ValueError")
