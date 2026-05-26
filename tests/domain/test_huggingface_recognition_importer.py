from __future__ import annotations

import httpx

from app.adapters.recognition.huggingface import HuggingFaceRecognitionEvidenceImporter


def test_huggingface_importer_fetches_recognition_evidence_for_allowlist() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/models/black-forest-labs/FLUX.1-dev"):
            return httpx.Response(
                200,
                json={
                    "id": "black-forest-labs/FLUX.1-dev",
                    "pipeline_tag": "text-to-image",
                    "tags": ["diffusers", "text-to-image"],
                },
            )
        if request.url.path.endswith("/api/models/llava-hf/llava-1.5-7b-hf"):
            return httpx.Response(
                200,
                json={
                    "id": "llava-hf/llava-1.5-7b-hf",
                    "pipeline_tag": "image-text-to-text",
                    "tags": ["vision", "multimodal"],
                },
            )
        raise AssertionError(f"unexpected request path: {request.url.path}")

    importer = HuggingFaceRecognitionEvidenceImporter(
        repo_ids=[
            "black-forest-labs/FLUX.1-dev",
            "llava-hf/llava-1.5-7b-hf",
        ],
        transport=httpx.MockTransport(handler),
    )

    payload = importer.fetch_upstream_evidence_payload()

    flux = payload["records"]["huggingface::black-forest-labs/FLUX.1-dev"]
    llava = payload["records"]["huggingface::llava-hf/llava-1.5-7b-hf"]

    assert payload["version"] == "recognition_upstream_v1"
    assert payload["sources"]["hf_snapshot"]
    assert flux["model_type"] == "image_generation"
    assert flux["preview_type"] == "image"
    assert flux["capabilities"]["image_output"] is True
    assert llava["model_type"] == "vision"
    assert llava["preview_type"] == "text"
    assert llava["capabilities"]["vision"] is True


def test_huggingface_importer_skips_unsupported_pipeline_tags() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "id": "facebook/musicgen-small",
                "pipeline_tag": "text-to-audio",
                "tags": ["audio"],
            },
        )

    importer = HuggingFaceRecognitionEvidenceImporter(
        repo_ids=["facebook/musicgen-small"],
        transport=httpx.MockTransport(handler),
    )

    payload = importer.fetch_upstream_evidence_payload()

    assert payload["records"] == {}
