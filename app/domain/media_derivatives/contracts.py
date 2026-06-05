from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

ALLOWED_TARGET_FORMATS = frozenset({"webp", "avif", "jpeg", "png", "original"})
ALLOWED_SOURCE_MEDIA_TYPES = frozenset({"image"})
ALLOWED_WATERMARK_TYPES = frozenset({"image", "text"})
ALLOWED_WATERMARK_POSITIONS = frozenset({
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
    "center",
})
MAX_UPLOAD_BYTES_IMAGE = 50 * 1024 * 1024
MAX_PIXEL_COUNT = 178_956_970
ARTIFACT_DEFAULT_TTL_MINUTES = 30
ARTIFACT_MIN_TTL_MINUTES = 15
ARTIFACT_MAX_TTL_MINUTES = 60
BATCH_CONTEXT_MAX_ITEMS = 1000
BATCH_CONTEXT_MAX_CHUNK_SIZE = 20

BLOCKED_RESPONSE_FIELDS = frozenset({
    "wordpress_write_policy",
    "wordpress_write_target",
    "attachment_metadata",
    "metadata_patch",
    "replace_file",
    "apply_decision",
    "approval_decision",
    "target_attachment_id",
})

MIME_TYPE_BY_FORMAT: dict[str, str] = {
    "webp": "image/webp",
    "avif": "image/avif",
    "jpeg": "image/jpeg",
    "png": "image/png",
}

PILLOW_FORMAT_BY_TARGET: dict[str, str] = {
    "webp": "WEBP",
    "avif": "AVIF",
    "jpeg": "JPEG",
    "png": "PNG",
}


class WatermarkPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["image", "text"]
    artifact_id: str | None = None
    text: str = "AI"
    position: str = "bottom_right"
    opacity: float = 0.75
    scale_percent: int = 18
    font_size: int = 48
    color: str = "#FFFFFF"
    background: str = "rgba(0,0,0,0.35)"
    margin_px: int = 24


class CloudJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_type: Literal["generate_optimized_media_derivative"]
    target_format: str
    max_width: int = 1200
    quality: int = 82
    source_media_type: str = "image"
    watermark: WatermarkPayload | None = None


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str


class BatchContextPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str
    item_index: int = 1
    item_count: int = 1
    chunk_size: int = 10
    explicit_avif: bool = False


class MediaDerivativeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_contract_version: Literal["media_derivative_cloud_request.v1"]
    cloud_job_payload: CloudJobPayload
    source: SourceRef | None = None
    batch_context: BatchContextPayload | None = None
    ttl_minutes: int = ARTIFACT_DEFAULT_TTL_MINUTES

    @model_validator(mode="after")
    def validate_fields(self) -> MediaDerivativeRequest:
        payload = self.cloud_job_payload
        if payload.target_format not in ALLOWED_TARGET_FORMATS:
            raise ValueError(f"target_format '{payload.target_format}' is not supported")
        if payload.source_media_type not in ALLOWED_SOURCE_MEDIA_TYPES:
            raise ValueError(f"source_media_type '{payload.source_media_type}' is not supported")
        if not (1 <= payload.quality <= 100):
            raise ValueError("quality must be between 1 and 100")
        if not (1 <= payload.max_width <= 10000):
            raise ValueError("max_width must be between 1 and 10000")
        if self.batch_context is not None:
            batch = self.batch_context
            if not batch.batch_id.strip():
                raise ValueError("batch_context.batch_id is required")
            if len(batch.batch_id) > 128:
                raise ValueError("batch_context.batch_id must be 128 characters or fewer")
            if not (1 <= batch.item_count <= BATCH_CONTEXT_MAX_ITEMS):
                raise ValueError(
                    f"batch_context.item_count must be between 1 and "
                    f"{BATCH_CONTEXT_MAX_ITEMS}"
                )
            if not (1 <= batch.item_index <= batch.item_count):
                raise ValueError("batch_context.item_index must be within item_count")
            if not (1 <= batch.chunk_size <= BATCH_CONTEXT_MAX_CHUNK_SIZE):
                raise ValueError(
                    f"batch_context.chunk_size must be between 1 and "
                    f"{BATCH_CONTEXT_MAX_CHUNK_SIZE}"
                )
            if (
                payload.target_format == "avif"
                and batch.item_count > 1
                and not batch.explicit_avif
            ):
                raise ValueError(
                    "target_format 'avif' requires batch_context.explicit_avif=true "
                    "for batch requests"
                )
        if payload.watermark is not None:
            watermark = payload.watermark
            if watermark.type not in ALLOWED_WATERMARK_TYPES:
                raise ValueError(f"watermark.type '{watermark.type}' is not supported")
            if watermark.position not in ALLOWED_WATERMARK_POSITIONS:
                raise ValueError(
                    f"watermark.position '{watermark.position}' is not supported"
                )
            if not (0.0 <= watermark.opacity <= 1.0):
                raise ValueError("watermark.opacity must be between 0.0 and 1.0")
            if watermark.type == "image" and not (1 <= watermark.scale_percent <= 100):
                raise ValueError("watermark.scale_percent must be between 1 and 100")
            if watermark.type == "text":
                if not watermark.text.strip():
                    raise ValueError("watermark.text is required")
                if len(watermark.text) > 64:
                    raise ValueError("watermark.text must be 64 characters or fewer")
                if not (8 <= watermark.font_size <= 256):
                    raise ValueError("watermark.font_size must be between 8 and 256")
            if not (0 <= watermark.margin_px <= 1000):
                raise ValueError("watermark.margin_px must be between 0 and 1000")
        if not (ARTIFACT_MIN_TTL_MINUTES <= self.ttl_minutes <= ARTIFACT_MAX_TTL_MINUTES):
            raise ValueError(
                f"ttl_minutes must be between "
                f"{ARTIFACT_MIN_TTL_MINUTES} and {ARTIFACT_MAX_TTL_MINUTES}"
            )
        return self


def validate_blocked_fields(data: dict[str, Any]) -> None:
    for key in BLOCKED_RESPONSE_FIELDS:
        if key in data:
            raise ValueError(f"response contains blocked field '{key}'")
