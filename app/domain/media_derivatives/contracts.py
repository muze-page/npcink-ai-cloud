from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ALLOWED_TARGET_FORMATS = frozenset({"webp", "avif", "jpeg", "png", "original"})
ALLOWED_SOURCE_MEDIA_TYPES = frozenset({"image"})
ALLOWED_WATERMARK_TYPES = frozenset({"image", "text"})
ALLOWED_WATERMARK_POSITIONS = frozenset(
    {
        "top_left",
        "top_right",
        "bottom_left",
        "bottom_right",
        "center",
    }
)
ALLOWED_CROP_TYPES = frozenset({"aspect_ratio"})
ALLOWED_CROP_POSITIONS = frozenset(
    {
        "top_left",
        "top",
        "top_right",
        "left",
        "center",
        "right",
        "bottom_left",
        "bottom",
        "bottom_right",
    }
)
MAX_UPLOAD_BYTES_IMAGE = 50 * 1024 * 1024
# Temporary derivative outputs must remain consumable by every current local
# connector. This is a platform-neutral delivery-envelope limit, not a
# WordPress storage limit; larger source uploads may still be accepted when the
# requested transform produces a bounded result.
MAX_DELIVERABLE_ARTIFACT_BYTES = 25 * 1024 * 1024
# A 16,777,216-pixel RGBA decode occupies 64 MiB before Pillow creates any
# crop, resize, watermark, or encoder buffers. Keep both the total area and a
# per-axis ceiling frozen so compressed images cannot force an unbounded decode
# in the current low-memory worker runtime.
MAX_DECODED_IMAGE_BYTES = 64 * 1024 * 1024
DECODED_RGBA_BYTES_PER_PIXEL = 4
MAX_PIXEL_COUNT = MAX_DECODED_IMAGE_BYTES // DECODED_RGBA_BYTES_PER_PIXEL
MAX_IMAGE_DIMENSION = 8_192
ARTIFACT_DEFAULT_TTL_MINUTES = 30
ARTIFACT_MIN_TTL_MINUTES = 15
ARTIFACT_MAX_TTL_MINUTES = 60
BATCH_CONTEXT_MAX_ITEMS = 1000
BATCH_CONTEXT_MAX_CHUNK_SIZE = 20

MEDIA_UPLOAD_ARTIFACT_TYPE = "media_upload_artifact"
MEDIA_UPLOAD_RESULT_CONTRACT = "media_upload_result.v1"
MEDIA_DERIVATIVE_ARTIFACT_TYPE = "media_derivative_artifact"
MEDIA_DERIVATIVE_RESULT_CONTRACT = "media_derivative_result.v1"

BLOCKED_RESPONSE_FIELDS = frozenset(
    {
        "wordpress_write_policy",
        "wordpress_write_target",
        "attachment_metadata",
        "metadata_patch",
        "replace_file",
        "apply_decision",
        "approval_decision",
        "target_attachment_id",
        "storage_key",
        "storage_ref",
        "blob" + "_data",
    }
)

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
    text: str = "AI"
    position: str = "bottom_right"
    opacity: float = 0.75
    scale_percent: int = 18
    font_size: int = 48
    color: str = "#FFFFFF"
    background: str = "rgba(0,0,0,0.35)"
    margin_px: int = 24


class CropPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["aspect_ratio"] = "aspect_ratio"
    aspect_ratio: str = "16:9"
    position: str = "center"


class ImageTransformPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_format: str
    max_width: int = 1200
    quality: int = 82
    source_media_type: str = "image"
    crop: CropPayload | None = None
    watermark: WatermarkPayload | None = None


class BatchContextPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str
    item_index: int = 1
    item_count: int = 1
    chunk_size: int = 10
    explicit_avif: bool = False


class MediaUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_contract_version: Literal["media_upload_request.v1"]
    media_kind: Literal["image"]
    ttl_minutes: int = ARTIFACT_DEFAULT_TTL_MINUTES

    @model_validator(mode="after")
    def validate_fields(self) -> MediaUploadRequest:
        if not (ARTIFACT_MIN_TTL_MINUTES <= self.ttl_minutes <= ARTIFACT_MAX_TTL_MINUTES):
            raise ValueError(
                f"ttl_minutes must be between "
                f"{ARTIFACT_MIN_TTL_MINUTES} and {ARTIFACT_MAX_TTL_MINUTES}"
            )
        return self


class MediaJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_contract_version: Literal["media_job_request.v1"]
    operation: Literal["image.transform.v1"]
    source_artifact_id: str = Field(min_length=1, max_length=191)
    watermark_artifact_id: str | None = Field(default=None, min_length=1, max_length=191)
    params: ImageTransformPayload
    batch_context: BatchContextPayload | None = None
    result_ttl_minutes: int = ARTIFACT_DEFAULT_TTL_MINUTES

    @model_validator(mode="after")
    def validate_fields(self) -> MediaJobRequest:
        payload = self.params
        if payload.target_format not in ALLOWED_TARGET_FORMATS:
            raise ValueError(f"target_format '{payload.target_format}' is not supported")
        if payload.source_media_type not in ALLOWED_SOURCE_MEDIA_TYPES:
            raise ValueError(f"source_media_type '{payload.source_media_type}' is not supported")
        if not (1 <= payload.quality <= 100):
            raise ValueError("quality must be between 1 and 100")
        if not (1 <= payload.max_width <= 10000):
            raise ValueError("max_width must be between 1 and 10000")
        if payload.crop is not None:
            crop = payload.crop
            if crop.type not in ALLOWED_CROP_TYPES:
                raise ValueError(f"crop.type '{crop.type}' is not supported")
            if crop.position not in ALLOWED_CROP_POSITIONS:
                raise ValueError(f"crop.position '{crop.position}' is not supported")
            ratio_parts = crop.aspect_ratio.split(":", 1)
            if len(ratio_parts) != 2 or not all(part.isdigit() for part in ratio_parts):
                raise ValueError("crop.aspect_ratio must use a W:H ratio")
            ratio_width = int(ratio_parts[0])
            ratio_height = int(ratio_parts[1])
            if not (1 <= ratio_width <= 100 and 1 <= ratio_height <= 100):
                raise ValueError("crop.aspect_ratio values must be between 1 and 100")
        if self.batch_context is not None:
            batch = self.batch_context
            if not batch.batch_id.strip():
                raise ValueError("batch_context.batch_id is required")
            if len(batch.batch_id) > 128:
                raise ValueError("batch_context.batch_id must be 128 characters or fewer")
            if not (1 <= batch.item_count <= BATCH_CONTEXT_MAX_ITEMS):
                raise ValueError(
                    f"batch_context.item_count must be between 1 and {BATCH_CONTEXT_MAX_ITEMS}"
                )
            if not (1 <= batch.item_index <= batch.item_count):
                raise ValueError("batch_context.item_index must be within item_count")
            if not (1 <= batch.chunk_size <= BATCH_CONTEXT_MAX_CHUNK_SIZE):
                raise ValueError(
                    f"batch_context.chunk_size must be between 1 and {BATCH_CONTEXT_MAX_CHUNK_SIZE}"
                )
            if payload.target_format == "avif" and batch.item_count > 1 and not batch.explicit_avif:
                raise ValueError(
                    "target_format 'avif' requires batch_context.explicit_avif=true "
                    "for batch requests"
                )
        if payload.watermark is not None:
            watermark = payload.watermark
            if watermark.type not in ALLOWED_WATERMARK_TYPES:
                raise ValueError(f"watermark.type '{watermark.type}' is not supported")
            if watermark.position not in ALLOWED_WATERMARK_POSITIONS:
                raise ValueError(f"watermark.position '{watermark.position}' is not supported")
            if not (0.0 <= watermark.opacity <= 1.0):
                raise ValueError("watermark.opacity must be between 0.0 and 1.0")
            if watermark.type == "image" and not (1 <= watermark.scale_percent <= 100):
                raise ValueError("watermark.scale_percent must be between 1 and 100")
            if watermark.type == "image" and not self.watermark_artifact_id:
                raise ValueError("watermark_artifact_id is required for an image watermark")
            if watermark.type == "text":
                if self.watermark_artifact_id:
                    raise ValueError("watermark_artifact_id is not allowed for a text watermark")
                if not watermark.text.strip():
                    raise ValueError("watermark.text is required")
                if len(watermark.text) > 64:
                    raise ValueError("watermark.text must be 64 characters or fewer")
                if not (8 <= watermark.font_size <= 256):
                    raise ValueError("watermark.font_size must be between 8 and 256")
            if not (0 <= watermark.margin_px <= 1000):
                raise ValueError("watermark.margin_px must be between 0 and 1000")
        elif self.watermark_artifact_id:
            raise ValueError("params.watermark is required when watermark_artifact_id is provided")
        if not (ARTIFACT_MIN_TTL_MINUTES <= self.result_ttl_minutes <= ARTIFACT_MAX_TTL_MINUTES):
            raise ValueError(
                f"result_ttl_minutes must be between "
                f"{ARTIFACT_MIN_TTL_MINUTES} and {ARTIFACT_MAX_TTL_MINUTES}"
            )
        return self
