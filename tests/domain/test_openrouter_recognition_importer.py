from __future__ import annotations

import httpx

from app.adapters.recognition.openrouter import OpenRouterRecognitionEvidenceImporter


def test_openrouter_importer_fetches_recognition_evidence_over_http() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        assert request.headers["HTTP-Referer"] == "https://magick.example.com"
        assert request.headers["X-Title"] == "Magick AI Cloud"
        return httpx.Response(
            200,
            headers={"etag": "openrouter-models-rev-001"},
            json={
                "data": [
                    {
                        "id": "openai/gpt-4.1-mini",
                        "canonical_slug": "openai/gpt-4.1-mini-2026-03-01",
                        "name": "OpenAI: GPT-4.1 mini",
                        "architecture": {
                            "modality": "text->text",
                            "input_modalities": ["text"],
                            "output_modalities": ["text"],
                        },
                        "pricing": {"prompt": "0.0000004", "completion": "0.0000016"},
                        "supported_parameters": ["tools", "tool_choice", "response_format"],
                    },
                    {
                        "id": "z-ai/glm-5v-turbo",
                        "name": "Z.ai: GLM 5V Turbo",
                        "architecture": {
                            "modality": "text+image+video->text",
                            "input_modalities": ["image", "text", "video"],
                            "output_modalities": ["text"],
                        },
                        "pricing": {"prompt": "0.0000012", "completion": "0.000004"},
                        "supported_parameters": ["response_format", "tools"],
                    },
                    {
                        "id": "black-forest-labs/flux-1-schnell",
                        "name": "FLUX.1 Schnell",
                        "architecture": {
                            "modality": "text->image",
                            "input_modalities": ["text"],
                            "output_modalities": ["image"],
                        },
                        "pricing": {"prompt": "0.000002"},
                        "supported_parameters": [],
                    },
                ]
            },
        )

    importer = OpenRouterRecognitionEvidenceImporter(
        base_url="https://openrouter.ai/api/v1",
        site_url="https://magick.example.com",
        app_name="Magick AI Cloud",
        transport=httpx.MockTransport(handler),
    )

    payload = importer.fetch_upstream_evidence_payload()

    chat = payload["records"]["openrouter::openai/gpt-4.1-mini"]
    vision = payload["records"]["openrouter::z-ai/glm-5v-turbo"]
    image = payload["records"]["openrouter::black-forest-labs/flux-1-schnell"]

    assert payload["version"] == "recognition_upstream_v1"
    assert payload["sources"]["openrouter_snapshot"] == "openrouter-models-rev-001"
    assert chat["model_type"] == "chat"
    assert chat["price_input"] == 0.4
    assert chat["price_output"] == 1.6
    assert chat["capabilities"]["tools"] is True
    assert chat["capabilities"]["structured_output"] is True
    assert vision["model_type"] == "vision"
    assert vision["price_input"] == 1.2
    assert vision["price_output"] == 4.0
    assert vision["capabilities"]["vision"] is True
    assert image["model_type"] == "image_generation"
    assert image["price_input"] == 2.0
    assert image["price_output"] is None
    assert image["capabilities"]["image_output"] is True


def test_openrouter_importer_raises_for_invalid_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"models": []})

    importer = OpenRouterRecognitionEvidenceImporter(
        transport=httpx.MockTransport(handler),
    )

    try:
        importer.fetch_upstream_evidence_payload()
    except ValueError as error:
        assert "missing data list" in str(error)
    else:
        raise AssertionError("expected invalid payload to raise ValueError")
