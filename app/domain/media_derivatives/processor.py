from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from PIL import Image

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


@dataclass(slots=True)
class MediaDerivativeResult:
    output_bytes: bytes
    width: int
    height: int
    filesize_bytes: int
    checksum: str
    mime_type: str
    format: str
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
        raise MediaDerivativeFormatUnavailableError(target_format)


def process_media_derivative(
    *,
    source_bytes: bytes,
    source_media_type: str,
    target_format: str,
    max_width: int,
    quality: int,
) -> MediaDerivativeResult:
    if target_format != "original":
        _check_format_available(target_format)

    img: Image.Image | None = None
    try:
        try:
            img = Image.open(BytesIO(source_bytes))
            img.verify()
        except Exception:
            raise MediaDerivativeSourceDecodeFailedError()

        img = Image.open(BytesIO(source_bytes))
        img.load()

        if hasattr(img, "n_frames") and getattr(img, "n_frames", 1) > 1:
            raise MediaDerivativeAnimatedSourceUnavailableError()

        if img.width * img.height > MAX_PIXEL_COUNT:
            raise MediaDerivativeSourceTooLargeError()

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

        if target_format == "original":
            output_bytes = source_bytes
            result_width = img.width
            result_height = img.height
            fmt = img.format or "PNG"
            mime_type = MIME_TYPE_BY_FORMAT.get(fmt.lower(), "image/png")
        else:
            if img.width > max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.LANCZOS)

            pillow_format = PILLOW_FORMAT_BY_TARGET[target_format]
            mime_type = MIME_TYPE_BY_FORMAT[target_format]

            save_kwargs: dict[str, Any] = {}
            if target_format == "jpeg":
                if img.mode in ("RGBA", "LA", "P"):
                    img = img.convert("RGB")
                    warnings.append("source_alpha_flattened_for_jpeg")
                elif img.mode != "RGB":
                    img = img.convert("RGB")
                save_kwargs["quality"] = quality
                save_kwargs["optimize"] = True
            elif target_format == "webp":
                save_kwargs["quality"] = quality
            elif target_format == "avif":
                save_kwargs["quality"] = quality
            elif target_format == "png":
                save_kwargs["optimize"] = True
                if img.mode == "RGBA":
                    pass
                elif img.mode != "RGB":
                    img = img.convert("RGB")

            buf = BytesIO()
            img.save(buf, format=pillow_format, **save_kwargs)
            output_bytes = buf.getvalue()

            result_width = img.width
            result_height = img.height
            fmt = target_format

        checksum = hashlib.sha256(output_bytes).hexdigest()
        return MediaDerivativeResult(
            output_bytes=output_bytes,
            width=result_width,
            height=result_height,
            filesize_bytes=len(output_bytes),
            checksum=f"sha256:{checksum}",
            mime_type=mime_type,
            format=fmt,
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
