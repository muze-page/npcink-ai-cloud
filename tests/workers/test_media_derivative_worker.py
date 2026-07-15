from __future__ import annotations

import hashlib
import io
from unittest.mock import patch

import pytest
from PIL import ExifTags, Image
from PIL.TiffImagePlugin import IFDRational

from app.domain.media_derivatives.errors import (
    MediaDerivativeAnimatedSourceUnavailableError,
    MediaDerivativeFormatUnavailableError,
    MediaDerivativeSourceDecodeFailedError,
    MediaDerivativeSourceTooLargeError,
)
from app.domain.media_derivatives.processor import process_media_derivative


def _make_png_bytes(width: int = 100, height: int = 80, mode: str = "RGB") -> bytes:
    color = (255, 0, 0, 128) if mode == "RGBA" else "red"
    img = Image.new(mode, (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_cmyk_jpeg_bytes(width: int = 80, height: int = 60) -> bytes:
    img = Image.new("CMYK", (width, height), color=(0, 128, 128, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_oriented_jpeg_bytes(width: int = 40, height: int = 20) -> bytes:
    img = Image.new("RGB", (width, height), color="blue")
    exif = img.getexif()
    exif[274] = 6
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def _make_animated_gif_bytes() -> bytes:
    frames = [Image.new("RGB", (10, 10), color=c) for c in ("red", "green")]
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return buf.getvalue()


def _make_private_metadata_png_bytes(width: int = 32, height: int = 24) -> bytes:
    image = Image.new("RGB", (width, height), color="blue")
    exif = image.getexif()
    exif[270] = "private description"
    exif[int(ExifTags.IFD.GPSInfo)] = {
        1: "N",
        2: (IFDRational(1), IFDRational(2), IFDRational(3)),
    }
    output = io.BytesIO()
    image.save(
        output,
        format="PNG",
        exif=exif.tobytes(),
        icc_profile=b"private-icc-profile",
    )
    return output.getvalue()


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


def test_process_cmyk_jpeg_to_webp_converts_color_mode() -> None:
    source = _make_cmyk_jpeg_bytes()
    result = process_media_derivative(
        source_bytes=source,
        source_media_type="image",
        target_format="webp",
        max_width=80,
        quality=80,
    )
    assert result.format == "webp"
    assert result.mime_type == "image/webp"
    assert result.width == 80
    assert result.height == 60
    assert "source_color_mode_converted_for_webp" in result.processing_warnings


def test_process_applies_exif_orientation_before_output() -> None:
    source = _make_oriented_jpeg_bytes()
    result = process_media_derivative(
        source_bytes=source,
        source_media_type="image",
        target_format="png",
        max_width=100,
        quality=80,
    )
    assert result.source_width == 40
    assert result.source_height == 20
    assert result.width == 20
    assert result.height == 40


def test_process_original_returns_valid_same_format() -> None:
    source = _make_png_bytes(50, 50)
    result = process_media_derivative(
        source_bytes=source,
        source_media_type="image",
        target_format="original",
        max_width=100,
        quality=80,
    )
    assert result.format == "png"
    assert result.width == 50
    assert result.height == 50
    with Image.open(io.BytesIO(result.output_bytes)) as output:
        output.verify()


def test_process_original_strips_exif_metadata() -> None:
    image = Image.new("RGB", (40, 20), color="blue")
    exif = image.getexif()
    exif[270] = "private description"
    exif[315] = "private author"
    source = io.BytesIO()
    image.save(source, format="JPEG", exif=exif.tobytes())

    result = process_media_derivative(
        source_bytes=source.getvalue(),
        source_media_type="image",
        target_format="original",
        max_width=100,
        quality=80,
    )

    with Image.open(io.BytesIO(result.output_bytes)) as output:
        assert not output.getexif()
        assert "exif" not in output.info


@pytest.mark.parametrize(
    ("target_format", "max_width"),
    [("original", 64), ("png", 64), ("png", 16)],
)
def test_process_png_strips_private_icc_exif_and_gps_metadata(
    target_format: str,
    max_width: int,
) -> None:
    source = _make_private_metadata_png_bytes()

    result = process_media_derivative(
        source_bytes=source,
        source_media_type="image",
        target_format=target_format,
        max_width=max_width,
        quality=80,
    )

    with Image.open(io.BytesIO(result.output_bytes)) as output:
        assert "icc_profile" not in output.info
        assert "exif" not in output.info
        assert not output.getexif()
        assert not output.getexif().get_ifd(ExifTags.IFD.GPSInfo)


def test_process_png_applies_image_watermark() -> None:
    source = Image.new("RGB", (100, 100), color="white")
    source_buf = io.BytesIO()
    source.save(source_buf, format="PNG")
    watermark = _make_png_bytes(10, 10)

    result = process_media_derivative(
        source_bytes=source_buf.getvalue(),
        source_media_type="image",
        target_format="png",
        max_width=100,
        quality=80,
        watermark_bytes=watermark,
        watermark_options={
            "position": "bottom_right",
            "opacity": 1.0,
            "scale_percent": 20,
            "margin_px": 0,
        },
    )

    output = Image.open(io.BytesIO(result.output_bytes))
    assert output.getpixel((95, 95))[:3] == (255, 0, 0)


def test_process_png_applies_text_watermark() -> None:
    source = Image.new("RGB", (100, 100), color="white")
    source_buf = io.BytesIO()
    source.save(source_buf, format="PNG")

    result = process_media_derivative(
        source_bytes=source_buf.getvalue(),
        source_media_type="image",
        target_format="png",
        max_width=100,
        quality=80,
        watermark_options={
            "type": "text",
            "text": "AI",
            "position": "top_right",
            "opacity": 1.0,
            "font_size": 24,
            "color": "#000000",
            "background": "transparent",
            "margin_px": 0,
        },
    )

    output = Image.open(io.BytesIO(result.output_bytes)).convert("RGB")
    top_right_pixels = [output.getpixel((x, y)) for x in range(50, 100) for y in range(0, 40)]
    assert any(pixel != (255, 255, 255) for pixel in top_right_pixels)


def test_process_jpeg_watermark_records_alpha_flatten_warning() -> None:
    source = _make_png_bytes(50, 50)
    watermark = _make_png_bytes(10, 10, mode="RGBA")

    result = process_media_derivative(
        source_bytes=source,
        source_media_type="image",
        target_format="jpeg",
        max_width=50,
        quality=80,
        watermark_bytes=watermark,
        watermark_options={
            "position": "center",
            "opacity": 0.5,
            "scale_percent": 20,
            "margin_px": 0,
        },
    )

    assert result.format == "jpeg"
    assert "watermark_alpha_flattened_for_jpeg" in result.processing_warnings


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


def test_process_crops_to_aspect_ratio_before_resize() -> None:
    source = _make_png_bytes(200, 100)
    result = process_media_derivative(
        source_bytes=source,
        source_media_type="image",
        target_format="png",
        max_width=50,
        quality=80,
        crop_options={
            "type": "aspect_ratio",
            "aspect_ratio": "1:1",
            "position": "center",
        },
    )
    assert result.width == 50
    assert result.height == 50
    assert "source_cropped_to_aspect_ratio_1_1" in result.processing_warnings


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

    with patch("app.domain.media_derivatives.processor.MAX_PIXEL_COUNT", 1):
        with pytest.raises(MediaDerivativeSourceTooLargeError):
            process_media_derivative(
                source_bytes=source,
                source_media_type="image",
                target_format="webp",
                max_width=100,
                quality=80,
            )


def test_pixel_bomb_rejected_before_full_load() -> None:
    source = _make_png_bytes(2, 2)

    with (
        patch("app.domain.media_derivatives.processor.MAX_PIXEL_COUNT", 1),
        patch("PIL.Image.Image.load") as load_mock,
    ):
        with pytest.raises(MediaDerivativeSourceTooLargeError):
            process_media_derivative(
                source_bytes=source,
                source_media_type="image",
                target_format="webp",
                max_width=100,
                quality=80,
            )

    assert not load_mock.called


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
    assert (
        "avif" in str(exc_info.value.error_code).lower()
        or "avif" in str(exc_info.value.message).lower()
    )


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
