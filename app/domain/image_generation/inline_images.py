from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

INLINE_IMAGE_DEFAULT_MAX_BYTES = 24 * 1024 * 1024
INLINE_IMAGE_DEFAULT_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True, slots=True)
class InlineImageMaterializationConfig:
    max_bytes: int = INLINE_IMAGE_DEFAULT_MAX_BYTES
    timeout_seconds: float = INLINE_IMAGE_DEFAULT_TIMEOUT_SECONDS


class InlineImageMaterializationError(Exception):
    error_code = "image_generation.inline_materialization_failed"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def materialize_inline_image_candidates_from_urls(
    result_json: dict[str, Any],
    *,
    config: InlineImageMaterializationConfig | None = None,
) -> dict[str, Any]:
    if str(result_json.get("artifact_type") or "") != "image_generation_candidates":
        return result_json

    images = result_json.get("images")
    if not isinstance(images, list):
        return result_json

    materialization_config = config or InlineImageMaterializationConfig()
    next_images: list[Any] = []
    materialized_count = 0

    for image in images:
        if not isinstance(image, dict):
            next_images.append(image)
            continue

        if str(image.get("b64_json") or "").strip():
            next_images.append(image)
            continue

        source_url = str(image.get("url") or "").strip()
        if not source_url:
            next_images.append(image)
            continue

        image_bytes, mime_type = _download_image_url(
            source_url,
            config=materialization_config,
        )
        next_image = dict(image)
        next_image["b64_json"] = base64.b64encode(image_bytes).decode("ascii")
        if mime_type:
            next_image["mime_type"] = mime_type
        next_images.append(next_image)
        materialized_count += 1

    if materialized_count == 0:
        return result_json

    next_result = dict(result_json)
    next_result["images"] = next_images
    next_result["provider_response_format"] = "b64_json"
    next_result["inline_materialized_from_url"] = True
    next_result["inline_materialized_count"] = materialized_count
    return next_result


def _download_image_url(
    source_url: str,
    *,
    config: InlineImageMaterializationConfig,
) -> tuple[bytes, str]:
    parsed = urlparse(source_url)
    if parsed.scheme != "https":
        raise InlineImageMaterializationError("provider image URL must use HTTPS")

    max_bytes = max(1, int(config.max_bytes))
    timeout_seconds = max(0.001, float(config.timeout_seconds))

    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=False) as client:
            with client.stream("GET", source_url) as response:
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length is not None and int(content_length or "0") > max_bytes:
                    raise InlineImageMaterializationError(
                        "provider image exceeds inline response size limit"
                    )

                content_type_header = response.headers.get("content-type", "")
                content_type = _normalize_image_content_type(content_type_header)
                if not content_type and not _is_sniffable_binary_content_type(
                    content_type_header
                ):
                    raise InlineImageMaterializationError(
                        "provider image response is not an image"
                    )

                chunks: list[bytes] = []
                total_bytes = 0
                for chunk in response.iter_bytes():
                    total_bytes += len(chunk)
                    if total_bytes > max_bytes:
                        raise InlineImageMaterializationError(
                            "provider image exceeds inline response size limit"
                        )
                    chunks.append(chunk)
    except InlineImageMaterializationError:
        raise
    except (httpx.HTTPError, ValueError) as error:
        raise InlineImageMaterializationError(
            "provider image URL could not be materialized for inline output"
        ) from error

    image_bytes = b"".join(chunks)
    if not image_bytes:
        raise InlineImageMaterializationError("provider image URL returned no bytes")

    content_type = content_type or _infer_image_content_type(image_bytes)
    if not content_type:
        raise InlineImageMaterializationError("provider image response is not an image")

    return image_bytes, content_type


def _normalize_image_content_type(value: str) -> str:
    content_type = value.split(";", 1)[0].strip().lower()
    if not content_type.startswith("image/"):
        return ""
    return content_type


def _is_sniffable_binary_content_type(value: str) -> bool:
    content_type = value.split(";", 1)[0].strip().lower()
    return content_type in {"", "application/octet-stream", "binary/octet-stream"}


def _infer_image_content_type(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
        return "image/gif"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return ""
