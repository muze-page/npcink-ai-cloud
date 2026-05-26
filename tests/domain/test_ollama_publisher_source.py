from __future__ import annotations

from app.model_intelligence.publisher.sources.ollama import derive_shape


def test_ollama_publisher_shape_prefers_multimodal_and_image_capabilities() -> None:
    qwen = derive_shape(
        "qwen3.5:9b",
        ["completion", "vision", "tools", "thinking"],
        "qwen35",
        ["qwen35"],
        {
            "general.architecture": "qwen35",
            "qwen35.embedding_length": 4096,
            "qwen35.vision.embedding_length": 1152,
        },
    )
    functiongemma = derive_shape(
        "functiongemma:latest",
        ["completion", "tools"],
        "gemma3",
        ["gemma3"],
        {
            "general.architecture": "gemma3",
            "gemma3.embedding_length": 640,
        },
    )
    image_model = derive_shape(
        "x/z-image-turbo:latest",
        ["image"],
        "zimagepipeline",
        ["zimagepipeline"],
        {},
    )

    assert qwen["model_type"] == "vision"
    assert "vision" in qwen["supports"]
    assert "tools" in qwen["supports"]
    assert functiongemma["model_type"] == "chat"
    assert "tools" in functiongemma["supports"]
    assert image_model["model_type"] == "image_generation"
    assert image_model["preview_type"] == "image"
