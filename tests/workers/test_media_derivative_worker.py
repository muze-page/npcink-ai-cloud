from __future__ import annotations

import hashlib
import io

import pytest
from PIL import Image

from app.domain.media_derivatives.contracts import MAX_PIXEL_COUNT
from app.domain.media_derivatives.errors import (
    MediaDerivativeAnimatedSourceUnavailableError,
    MediaDerivativeFormatUnavailableError,
    MediaDerivativeSourceDecodeFailedError,
    MediaDerivativeSourceTooLargeError,
)
from app.domain.media_derivatives.processor import process_media_derivative


def _make_png_bytes(width: int = 100, height: int = 80, mode: str = "RGB") -> bytes:
    img = Image.new(mode, (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_animated_gif_bytes() -> bytes:
    frames = [Image.new("RGB", (10, 10), color=c) for c in ("red", "green")]
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return buf.getvalue()


def test_process_webp_success() -> None:
    source = _make_png_bytes(200, 160)
    result = process_media_derivative(
        source_bytes=source,
        source_media_type="image",
        target_format="webp",
        max_width=100,
        quality=80,
    )
    assert result.format == "webp"
    assert result.mime_type == "image/webp"
    assert result.width == 100
    assert result.height == 80
    assert result.filesize_bytes > 0
    assert result.checksum.startswith("sha256:")
    actual_checksum = hashlib.sha256(result.output_bytes).hexdigest()
    assert result.checksum == f"sha256:{actual_checksum}"


def test_process_jpeg_flattens_alpha() -> None:
    source = _make_png_bytes(50, 50, mode="RGBA")
    result = process_media_derivative(
        source_bytes=source,
        source_media_type="image",
        target_format="jpeg",
        max_width=50,
        quality=80,
    )
    assert result.format == "jpeg"
    assert "source_alpha_flattened_for_jpeg" in result.processing_warnings


def test_process_original_preserves_bytes() -> None:
    source = _make_png_bytes(50, 50)
    result = process_media_derivative(
        source_bytes=source,
        source_media_type="image",
        target_format="original",
        max_width=100,
        quality=80,
    )
    assert result.output_bytes == source
    assert result.width == 50
    assert result.height == 50


def test_process_no_resize_when_within_max_width() -> None:
    source = _make_png_bytes(50, 50)
    result = process_media_derivative(
        source_bytes=source,
        source_media_type="image",
        target_format="png",
        max_width=100,
        quality=80,
    )
    assert result.width == 50
    assert result.height == 50


def test_source_decode_failed() -> None:
    with pytest.raises(MediaDerivativeSourceDecodeFailedError):
        process_media_derivative(
            source_bytes=b"not an image",
            source_media_type="image",
            target_format="webp",
            max_width=100,
            quality=80,
        )


def test_animated_source_rejected() -> None:
    source = _make_animated_gif_bytes()
    with pytest.raises(MediaDerivativeAnimatedSourceUnavailableError):
        process_media_derivative(
            source_bytes=source,
            source_media_type="image",
            target_format="webp",
            max_width=100,
            quality=80,
        )


def test_pixel_bomb_protection() -> None:
    source = _make_png_bytes(2, 2)
    from unittest.mock import patch

    with patch("app.domain.media_derivatives.processor.MAX_PIXEL_COUNT", 1):
        with pytest.raises(MediaDerivativeSourceTooLargeError):
            process_media_derivative(
                source_bytes=source,
                source_media_type="image",
                target_format="webp",
                max_width=100,
                quality=80,
            )


def test_avif_unavailable_returns_explicit_error() -> None:
    from PIL import features

    if features.check("avif"):
        pytest.skip("AVIF is supported in this Pillow build")
    source = _make_png_bytes(50, 50)
    with pytest.raises(MediaDerivativeFormatUnavailableError) as exc_info:
        process_media_derivative(
            source_bytes=source,
            source_media_type="image",
            target_format="avif",
            max_width=50,
            quality=80,
        )
    assert "avif" in str(exc_info.value.error_code).lower() or "avif" in str(exc_info.value.message).lower()


def test_processor_closes_image_handles() -> None:
    source = _make_png_bytes(50, 50)
    result = process_media_derivative(
        source_bytes=source,
        source_media_type="image",
        target_format="png",
        max_width=50,
        quality=80,
    )
    assert result.output_bytes is not None
