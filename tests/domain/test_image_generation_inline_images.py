from __future__ import annotations

from typing import Any

import pytest

from app.domain.image_generation import inline_images


def test_materialize_inline_image_candidates_converts_provider_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_download(
        source_url: str,
        *,
        config: inline_images.InlineImageMaterializationConfig,
    ) -> tuple[bytes, str]:
        assert source_url == "https://provider.example.test/generated.png"
        assert config.max_bytes > 0
        return b"image-bytes", "image/png"

    monkeypatch.setattr(inline_images, "_download_image_url", fake_download)

    result = inline_images.materialize_inline_image_candidates_from_urls(
        {
            "artifact_type": "image_generation_candidates",
            "images": [
                {
                    "url": "https://provider.example.test/generated.png",
                    "b64_json": "",
                    "mime_type": "image/png",
                }
            ],
            "provider_response_format": "url",
        }
    )

    assert result["provider_response_format"] == "b64_json"
    assert result["inline_materialized_from_url"] is True
    assert result["inline_materialized_count"] == 1
    assert result["images"][0]["b64_json"] == "aW1hZ2UtYnl0ZXM="


def test_download_image_url_rejects_non_https_provider_url() -> None:
    with pytest.raises(inline_images.InlineImageMaterializationError) as error:
        inline_images._download_image_url(
            "http://provider.example.test/generated.png",
            config=inline_images.InlineImageMaterializationConfig(),
        )

    assert "HTTPS" in str(error.value)


def test_infer_image_content_type_accepts_octet_stream_png_bytes() -> None:
    assert inline_images._normalize_image_content_type("application/octet-stream") == ""
    assert inline_images._is_sniffable_binary_content_type("application/octet-stream")
    assert inline_images._infer_image_content_type(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    ) == "image/png"


def test_materialize_inline_image_candidates_leaves_existing_base64() -> None:
    result: dict[str, Any] = {
        "artifact_type": "image_generation_candidates",
        "images": [
            {
                "url": "https://provider.example.test/generated.png",
                "b64_json": "already-inline",
                "mime_type": "image/png",
            }
        ],
        "provider_response_format": "b64_json",
    }

    assert inline_images.materialize_inline_image_candidates_from_urls(result) == result
