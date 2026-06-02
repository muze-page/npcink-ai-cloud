from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ALLOWED_TARGET_FORMATS = frozenset({"webp", "avif", "jpeg", "png", "original"})
ALLOWED_SOURCE_MEDIA_TYPES = frozenset({"image"})
MAX_UPLOAD_BYTES_IMAGE = 50 * 1024 * 1024
MAX_PIXEL_COUNT = 178_956_970
ARTIFACT_DEFAULT_TTL_MINUTES = 30
ARTIFACT_MIN_TTL_MINUTES = 15
ARTIFACT_MAX_TTL_MINUTES = 60

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


class CloudJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_type: Literal["generate_optimized_media_derivative"]
    target_format: str
    max_width: int = 1200
    quality: int = 82
    source_media_type: str = "image"


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str


class MediaDerivativeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_contract_version: Literal["media_derivative_cloud_request.v1"]
    cloud_job_payload: CloudJobPayload
    source: SourceRef | None = None
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
        if not (ARTIFACT_MIN_TTL_MINUTES <= self.ttl_minutes <= ARTIFACT_MAX_TTL_MINUTES):
            raise ValueError(f"ttl_minutes must be between {ARTIFACT_MIN_TTL_MINUTES} and {ARTIFACT_MAX_TTL_MINUTES}")
        return self


def validate_blocked_fields(data: dict[str, Any]) -> None:
    for key in BLOCKED_RESPONSE_FIELDS:
        if key in data:
            raise ValueError(f"response contains blocked field '{key}'")
