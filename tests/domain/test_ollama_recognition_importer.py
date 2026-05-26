from __future__ import annotations

import httpx

from app.adapters.recognition.ollama import OllamaRecognitionEvidenceImporter


def test_ollama_importer_fetches_recognition_evidence_for_allowlist() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/api/show")
        body = request.read().decode("utf-8")
        if "llava:13b" in body:
            return httpx.Response(
                200,
                json={
                    "details": {
                        "family": "llava",
                        "families": ["llava", "clip"],
                    },
                    "capabilities": ["completion", "vision"],
                    "model_info": {"general.architecture": "llava"},
                    "modelfile": "FROM llava:13b\n",
                },
            )
        if "bge-m3:latest" in body:
            return httpx.Response(
                200,
                json={
                    "details": {
                        "family": "bert",
                        "families": ["bert"],
                    },
                    "capabilities": ["embedding"],
                    "model_info": {"general.architecture": "bert"},
                    "modelfile": "FROM bge-m3:latest\n",
                },
            )
        raise AssertionError(f"unexpected request body: {body}")

    importer = OllamaRecognitionEvidenceImporter(
        model_names=["llava:13b", "bge-m3:latest"],
        transport=httpx.MockTransport(handler),
    )

    payload = importer.fetch_upstream_evidence_payload()

    llava = payload["records"]["ollama::llava:13b"]
    embed = payload["records"]["ollama::bge-m3:latest"]

    assert payload["version"] == "recognition_upstream_v1"
    assert payload["sources"]["ollama_snapshot"]
    assert llava["model_type"] == "vision"
    assert llava["preview_type"] == "text"
    assert llava["capabilities"]["vision"] is True
    assert embed["model_type"] == "embedding"
    assert embed["preview_type"] == "embedding"
    assert embed["output_modalities"] == ["embedding"]


def test_ollama_importer_detects_image_generation_by_family_hint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "details": {
                    "family": "stable-diffusion",
                    "families": ["stable-diffusion"],
                },
                "capabilities": ["completion"],
                "model_info": {"general.architecture": "diffusion"},
                "modelfile": "FROM sdxl\n",
            },
        )

    importer = OllamaRecognitionEvidenceImporter(
        model_names=["sdxl"],
        transport=httpx.MockTransport(handler),
    )

    payload = importer.fetch_upstream_evidence_payload()
    record = payload["records"]["ollama::sdxl"]

    assert record["model_type"] == "image_generation"
    assert record["preview_type"] == "image"
    assert record["capabilities"]["image_output"] is True


def test_ollama_importer_can_fetch_official_catalog_via_tags_then_show() -> None:
    seen_show_models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.url.path.endswith("/api/tags")
            assert request.headers["Authorization"] == "Bearer ollama-cloud-key"
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "llama3.1:8b"},
                        {"name": "qwen2.5:14b"},
                    ]
                },
            )

        assert request.method == "POST"
        assert request.url.path.endswith("/api/show")
        body = request.read().decode("utf-8")
        if "llama3.1:8b" in body:
            seen_show_models.append("llama3.1:8b")
            return httpx.Response(
                200,
                json={
                    "details": {"family": "llama", "families": ["llama"]},
                    "capabilities": ["completion", "tools"],
                    "model_info": {"general.architecture": "llama"},
                    "modelfile": "FROM llama3.1:8b\n",
                },
            )
        if "qwen2.5:14b" in body:
            seen_show_models.append("qwen2.5:14b")
            return httpx.Response(
                200,
                json={
                    "details": {"family": "qwen", "families": ["qwen"]},
                    "capabilities": ["completion"],
                    "model_info": {"general.architecture": "qwen"},
                    "modelfile": "FROM qwen2.5:14b\n",
                },
            )
        raise AssertionError(f"unexpected request body: {body}")

    importer = OllamaRecognitionEvidenceImporter(
        base_url="https://ollama.com",
        api_key="ollama-cloud-key",
        catalog_enabled=True,
        catalog_limit=10,
        transport=httpx.MockTransport(handler),
    )

    payload = importer.fetch_upstream_evidence_payload()

    assert seen_show_models == ["llama3.1:8b", "qwen2.5:14b"]
    assert "ollama::llama3.1:8b" in payload["records"]
    assert "ollama::qwen2.5:14b" in payload["records"]
    assert payload["records"]["ollama::llama3.1:8b"]["evidence_source"] == "ollama_catalog_show"


def test_ollama_importer_prefers_explicit_multimodal_and_tool_capabilities_over_embedding_hints() -> None:
    responses = {
        "qwen3.5:9b": {
            "details": {"family": "qwen35", "families": ["qwen35"]},
            "capabilities": ["completion", "vision", "tools", "thinking"],
            "model_info": {
                "general.architecture": "qwen35",
                "qwen35.embedding_length": 4096,
                "qwen35.vision.embedding_length": 1152,
            },
            "modelfile": "FROM qwen3.5:9b\n",
        },
        "functiongemma:latest": {
            "details": {"family": "gemma3", "families": ["gemma3"]},
            "capabilities": ["completion", "tools"],
            "model_info": {
                "general.architecture": "gemma3",
                "gemma3.embedding_length": 640,
            },
            "modelfile": "FROM functiongemma:latest\n",
        },
        "x/z-image-turbo:latest": {
            "details": {"family": "ZImagePipeline", "families": ["ZImagePipeline"]},
            "capabilities": ["image"],
            "model_info": {},
            "modelfile": "FROM x/z-image-turbo:latest\n",
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode("utf-8")
        for model_name, payload in responses.items():
            if model_name in body:
                return httpx.Response(200, json=payload)
        raise AssertionError(f"unexpected request body: {body}")

    importer = OllamaRecognitionEvidenceImporter(
        model_names=list(responses.keys()),
        transport=httpx.MockTransport(handler),
    )

    payload = importer.fetch_upstream_evidence_payload()

    qwen = payload["records"]["ollama::qwen3.5:9b"]
    functiongemma = payload["records"]["ollama::functiongemma:latest"]
    image_model = payload["records"]["ollama::x/z-image-turbo:latest"]

    assert qwen["model_type"] == "vision"
    assert qwen["capabilities"]["vision"] is True
    assert qwen["capabilities"]["tools"] is True
    assert functiongemma["model_type"] == "chat"
    assert functiongemma["capabilities"]["tools"] is True
    assert image_model["model_type"] == "image_generation"
    assert image_model["preview_type"] == "image"
