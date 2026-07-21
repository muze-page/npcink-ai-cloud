from __future__ import annotations


class MediaDerivativeErrorBase(Exception):
    def __init__(self, status_code: int, error_code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message


class MediaDerivativeFormatUnavailableError(MediaDerivativeErrorBase):
    def __init__(self, fmt: str) -> None:
        super().__init__(
            422,
            "media_derivative.format_unavailable",
            f"format '{fmt}' is not available in this runtime environment",
        )


class MediaUploadTooLargeError(MediaDerivativeErrorBase):
    def __init__(self) -> None:
        super().__init__(
            413,
            "media_upload.upload_too_large",
            "uploaded file exceeds the size limit",
        )


class MediaUploadContentTypeMismatchError(MediaDerivativeErrorBase):
    def __init__(self, declared: str, detected: str) -> None:
        super().__init__(
            422,
            "media_upload.content_type_mismatch",
            f"declared content type '{declared}' does not match detected type '{detected}'",
        )


class MediaUploadFormatUnavailableError(MediaDerivativeErrorBase):
    def __init__(self, fmt: str) -> None:
        super().__init__(
            422,
            "media_upload.format_unavailable",
            f"uploaded image format '{fmt}' is not supported",
        )


class MediaUploadReplayUnavailableError(MediaDerivativeErrorBase):
    def __init__(self) -> None:
        super().__init__(
            409,
            "media_upload.replay_unavailable",
            "the idempotent upload evidence exists but its artifact is unavailable",
        )


class MediaJobArtifactNotFoundError(MediaDerivativeErrorBase):
    def __init__(self, role: str) -> None:
        super().__init__(
            404,
            f"media_job.{role}_artifact_not_found",
            f"referenced {role} artifact was not found",
        )


class MediaJobArtifactExpiredError(MediaDerivativeErrorBase):
    def __init__(self, role: str) -> None:
        super().__init__(
            410,
            f"media_job.{role}_artifact_expired",
            f"referenced {role} artifact has expired",
        )


class MediaJobArtifactUnavailableError(MediaDerivativeErrorBase):
    def __init__(self, role: str) -> None:
        super().__init__(
            503,
            f"media_job.{role}_artifact_unavailable",
            f"referenced {role} artifact bytes are unavailable",
        )


class MediaJobQueueFullError(MediaDerivativeErrorBase):
    def __init__(self) -> None:
        super().__init__(
            429,
            "media_derivative.site_queue_full",
            "site media derivative queue is full; retry later",
        )


class MediaDerivativeSourceDecodeFailedError(MediaDerivativeErrorBase):
    def __init__(self) -> None:
        super().__init__(
            422,
            "media_derivative.source_decode_failed",
            "source image could not be decoded",
        )


class MediaDerivativeSourceTooLargeError(MediaDerivativeErrorBase):
    def __init__(self) -> None:
        super().__init__(
            422,
            "media_derivative.source_too_large",
            "source image exceeds pixel count safety limit",
        )


class MediaDerivativeOutputTooLargeError(MediaDerivativeErrorBase):
    def __init__(self) -> None:
        super().__init__(
            413,
            "media_derivative.output_too_large",
            "generated derivative exceeds the deliverable artifact size limit",
        )


class MediaDerivativeAnimatedSourceUnavailableError(MediaDerivativeErrorBase):
    def __init__(self) -> None:
        super().__init__(
            422,
            "media_derivative.animated_source_unavailable",
            "animated image input is not supported",
        )


class MediaDerivativeProcessingFailedError(MediaDerivativeErrorBase):
    def __init__(self, detail: str = "") -> None:
        message = (
            f"media derivative processing failed: {detail}"
            if detail
            else "media derivative processing failed"
        )
        super().__init__(422, "media_derivative.processing_failed", message)


class MediaArtifactExpiredError(MediaDerivativeErrorBase):
    def __init__(self, artifact_id: str) -> None:
        super().__init__(
            410,
            "media_derivative.artifact_expired",
            f"artifact '{artifact_id}' has expired and is no longer available",
        )
