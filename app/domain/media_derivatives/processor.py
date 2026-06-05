from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from PIL import Image, ImageColor, ImageDraw, ImageFont

from app.domain.media_derivatives.contracts import (
    MAX_PIXEL_COUNT,
    MIME_TYPE_BY_FORMAT,
    PILLOW_FORMAT_BY_TARGET,
)
from app.domain.media_derivatives.errors import (
    MediaDerivativeAnimatedSourceUnavailableError,
    MediaDerivativeFormatUnavailableError,
    MediaDerivativeProcessingFailedError,
    MediaDerivativeSourceDecodeFailedError,
    MediaDerivativeSourceTooLargeError,
)

DEFAULT_ORIGINAL_FORMAT = "png"
RESAMPLE_LANCZOS = Image.Resampling.LANCZOS


@dataclass(slots=True)
class MediaDerivativeResult:
    output_bytes: bytes
    width: int
    height: int
    filesize_bytes: int
    checksum: str
    mime_type: str
    format: str
    source_width: int = 0
    source_height: int = 0
    processing_warnings: list[str] = field(default_factory=list)


def _check_format_available(target_format: str) -> None:
    pillow_format = PILLOW_FORMAT_BY_TARGET.get(target_format)
    if pillow_format is None:
        return
    try:
        Image.init()
        if pillow_format not in Image.SAVE:
            raise MediaDerivativeFormatUnavailableError(target_format)
    except MediaDerivativeFormatUnavailableError:
        raise
    except Exception:
        raise MediaDerivativeFormatUnavailableError(target_format) from None


def _open_static_image(image_bytes: bytes) -> Image.Image:
    try:
        img = Image.open(BytesIO(image_bytes))
        img.verify()
    except Exception:
        raise MediaDerivativeSourceDecodeFailedError() from None

    img = Image.open(BytesIO(image_bytes))
    if img.width * img.height > MAX_PIXEL_COUNT:
        raise MediaDerivativeSourceTooLargeError()
    img.load()
    if hasattr(img, "n_frames") and getattr(img, "n_frames", 1) > 1:
        raise MediaDerivativeAnimatedSourceUnavailableError()
    return img


def _resolve_watermark_position(
    *,
    base_width: int,
    base_height: int,
    watermark_width: int,
    watermark_height: int,
    position: str,
    margin_px: int,
) -> tuple[int, int]:
    margin = max(0, margin_px)
    if position == "top_left":
        return margin, margin
    if position == "top_right":
        return max(0, base_width - watermark_width - margin), margin
    if position == "bottom_left":
        return margin, max(0, base_height - watermark_height - margin)
    if position == "center":
        return (
            max(0, (base_width - watermark_width) // 2),
            max(0, (base_height - watermark_height) // 2),
        )
    return (
        max(0, base_width - watermark_width - margin),
        max(0, base_height - watermark_height - margin),
    )


def _apply_image_watermark(
    image: Image.Image,
    *,
    watermark_bytes: bytes,
    watermark_options: dict[str, Any],
) -> Image.Image:
    watermark = _open_static_image(watermark_bytes)
    try:
        base = image.convert("RGBA")
        mark = watermark.convert("RGBA")
        scale_percent = max(1, int(watermark_options.get("scale_percent") or 18))
        target_width = max(1, int(base.width * (scale_percent / 100)))
        if mark.width != target_width:
            ratio = target_width / max(1, mark.width)
            target_height = max(1, int(mark.height * ratio))
            mark = mark.resize((target_width, target_height), RESAMPLE_LANCZOS)

        opacity = max(0.0, min(1.0, float(watermark_options.get("opacity", 0.75))))
        if opacity < 1.0:
            alpha = mark.getchannel("A")
            alpha = alpha.point(lambda value: int(value * opacity))
            mark.putalpha(alpha)

        position = str(watermark_options.get("position") or "bottom_right")
        margin_px = max(0, int(watermark_options.get("margin_px") or 0))
        paste_at = _resolve_watermark_position(
            base_width=base.width,
            base_height=base.height,
            watermark_width=mark.width,
            watermark_height=mark.height,
            position=position,
            margin_px=margin_px,
        )
        base.alpha_composite(mark, dest=paste_at)
        return base
    finally:
        watermark.close()


def _parse_watermark_color(value: Any, default: str) -> tuple[int, int, int, int]:
    color = str(value or default).strip()
    if color.lower() == "transparent":
        return (0, 0, 0, 0)
    rgba_match = re.fullmatch(
        r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*(0|1|0?\.\d+))?\s*\)",
        color,
    )
    if rgba_match:
        red = max(0, min(255, int(rgba_match.group(1))))
        green = max(0, min(255, int(rgba_match.group(2))))
        blue = max(0, min(255, int(rgba_match.group(3))))
        alpha = 1.0 if rgba_match.group(4) is None else float(rgba_match.group(4))
        return (red, green, blue, int(max(0.0, min(1.0, alpha)) * 255))
    try:
        parsed = ImageColor.getcolor(color, "RGBA")
        if isinstance(parsed, int):
            return (parsed, parsed, parsed, 255)
        red, green, blue, alpha = tuple(parsed)[:4]
        return (int(red), int(green), int(blue), int(alpha))
    except Exception:
        return _parse_watermark_color(default, "#000000")


def _load_text_watermark_font(font_size: int) -> Any:
    bounded_size = max(8, min(256, int(font_size or 48)))
    for font_name in (
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(font_name, bounded_size)
        except Exception:
            continue
    return ImageFont.load_default()


def _apply_text_watermark(
    image: Image.Image,
    *,
    watermark_options: dict[str, Any],
) -> Image.Image:
    base = image.convert("RGBA")
    text = str(watermark_options.get("text") or "AI").strip()[:64] or "AI"
    font_size = max(8, min(256, int(watermark_options.get("font_size") or 48)))
    font = _load_text_watermark_font(font_size)
    padding = max(4, int(font_size * 0.3))

    measuring_image = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    measuring_draw = ImageDraw.Draw(measuring_image)
    bbox = measuring_draw.textbbox((0, 0), text, font=font)
    text_width = int(max(1, bbox[2] - bbox[0]))
    text_height = int(max(1, bbox[3] - bbox[1]))

    mark = Image.new(
        "RGBA",
        (text_width + padding * 2, text_height + padding * 2),
        (0, 0, 0, 0),
    )
    draw = ImageDraw.Draw(mark)
    background = _parse_watermark_color(
        watermark_options.get("background"),
        "rgba(0,0,0,0.35)",
    )
    if background[3] > 0:
        draw.rounded_rectangle(
            (0, 0, mark.width, mark.height),
            radius=max(2, padding // 2),
            fill=background,
        )

    color = _parse_watermark_color(watermark_options.get("color"), "#FFFFFF")
    draw.text((padding - bbox[0], padding - bbox[1]), text, font=font, fill=color)

    opacity = max(0.0, min(1.0, float(watermark_options.get("opacity", 0.75))))
    if opacity < 1.0:
        alpha = mark.getchannel("A")
        alpha = alpha.point(lambda value: int(value * opacity))
        mark.putalpha(alpha)

    position = str(watermark_options.get("position") or "bottom_right")
    margin_px = max(0, int(watermark_options.get("margin_px") or 0))
    paste_at = _resolve_watermark_position(
        base_width=base.width,
        base_height=base.height,
        watermark_width=mark.width,
        watermark_height=mark.height,
        position=position,
        margin_px=margin_px,
    )
    base.alpha_composite(mark, dest=paste_at)
    return base


def _save_image(
    image: Image.Image,
    *,
    target_format: str,
    quality: int,
    warnings: list[str],
    watermark_applied: bool,
) -> tuple[bytes, str, str]:
    if target_format == "original":
        source_format = str(image.format or "").lower()
        resolved_format = (
            source_format
            if source_format in MIME_TYPE_BY_FORMAT
            else DEFAULT_ORIGINAL_FORMAT
        )
        pillow_format = PILLOW_FORMAT_BY_TARGET[resolved_format]
        if not source_format or source_format not in MIME_TYPE_BY_FORMAT:
            warnings.append("original_format_fallback_png")
    else:
        resolved_format = target_format
        pillow_format = PILLOW_FORMAT_BY_TARGET[target_format]

    mime_type = MIME_TYPE_BY_FORMAT[resolved_format]
    save_kwargs: dict[str, Any] = {}
    output_image = image

    if resolved_format == "jpeg":
        if watermark_applied and output_image.mode in ("RGBA", "LA", "P"):
            warnings.append("watermark_alpha_flattened_for_jpeg")
        elif output_image.mode in ("RGBA", "LA", "P"):
            warnings.append("source_alpha_flattened_for_jpeg")
        if output_image.mode != "RGB":
            output_image = output_image.convert("RGB")
        save_kwargs["quality"] = quality
        save_kwargs["optimize"] = True
    elif resolved_format == "webp":
        if output_image.mode not in ("RGB", "RGBA"):
            warnings.append("source_color_mode_converted_for_webp")
            output_image = output_image.convert("RGB")
        save_kwargs["quality"] = quality
    elif resolved_format == "avif":
        if output_image.mode not in ("RGB", "RGBA"):
            warnings.append("source_color_mode_converted_for_avif")
            output_image = output_image.convert("RGB")
        save_kwargs["quality"] = quality
    elif resolved_format == "png":
        save_kwargs["optimize"] = True
        if output_image.mode not in ("RGB", "RGBA"):
            output_image = output_image.convert("RGB")

    buf = BytesIO()
    output_image.save(buf, format=pillow_format, **save_kwargs)
    return buf.getvalue(), mime_type, resolved_format


def process_media_derivative(
    *,
    source_bytes: bytes,
    source_media_type: str,
    target_format: str,
    max_width: int,
    quality: int,
    watermark_bytes: bytes | None = None,
    watermark_options: dict[str, Any] | None = None,
) -> MediaDerivativeResult:
    if target_format != "original":
        _check_format_available(target_format)

    img: Image.Image | None = None
    try:
        img = _open_static_image(source_bytes)
        source_width = img.width
        source_height = img.height

        try:
            from PIL import ExifTags

            img_exif = img.getexif()
            if img_exif:
                orientation = img_exif.get(ExifTags.Base.Orientation, None)
                if orientation == 3:
                    img = img.rotate(180, expand=True)
                elif orientation == 6:
                    img = img.rotate(270, expand=True)
                elif orientation == 8:
                    img = img.rotate(90, expand=True)
        except Exception:
            pass

        warnings: list[str] = []
        watermark_applied = False

        watermark_type = str((watermark_options or {}).get("type") or "image")
        text_watermark_requested = watermark_type == "text" and bool(
            str((watermark_options or {}).get("text") or "AI").strip()
        )

        if target_format == "original" and not watermark_bytes and not text_watermark_requested:
            output_bytes = source_bytes
            result_width = img.width
            result_height = img.height
            fmt = img.format or "PNG"
            mime_type = MIME_TYPE_BY_FORMAT.get(fmt.lower(), "image/png")
        else:
            if img.width > max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), RESAMPLE_LANCZOS)

            if watermark_bytes:
                img = _apply_image_watermark(
                    img,
                    watermark_bytes=watermark_bytes,
                    watermark_options=watermark_options or {},
                )
                watermark_applied = True
            elif text_watermark_requested:
                img = _apply_text_watermark(
                    img,
                    watermark_options=watermark_options or {},
                )
                watermark_applied = True

            output_bytes, mime_type, fmt = _save_image(
                img,
                target_format=target_format,
                quality=quality,
                warnings=warnings,
                watermark_applied=watermark_applied,
            )
            result_width = img.width
            result_height = img.height

        checksum = hashlib.sha256(output_bytes).hexdigest()
        return MediaDerivativeResult(
            output_bytes=output_bytes,
            width=result_width,
            height=result_height,
            filesize_bytes=len(output_bytes),
            checksum=f"sha256:{checksum}",
            mime_type=mime_type,
            format=fmt,
            source_width=source_width,
            source_height=source_height,
            processing_warnings=warnings,
        )
    except (
        MediaDerivativeSourceDecodeFailedError,
        MediaDerivativeFormatUnavailableError,
        MediaDerivativeSourceTooLargeError,
        MediaDerivativeAnimatedSourceUnavailableError,
    ):
        raise
    except Exception as exc:
        raise MediaDerivativeProcessingFailedError(str(exc)) from exc
    finally:
        if img is not None:
            img.close()
