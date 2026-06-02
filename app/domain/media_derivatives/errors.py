from __future__ import annotations


class MediaDerivativeErrorBase(Exception):
    def __init__(self, status_code: int, error_code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message


class MediaDerivativeInvalidSourceError(MediaDerivativeErrorBase):
    def __init__(self) -> None:
        super().__init__(
            400,
            "media_derivative.invalid_source",
            "exactly one source mode is required",
        )


class MediaDerivativeFormatUnavailableError(MediaDerivativeErrorBase):
    def __init__(self, fmt: str) -> None:
        super().__init__(
            422,
            "media_derivative.format_unavailable",
            f"format '{fmt}' is not available in this runtime environment",
        )


class MediaDerivativeInvalidFormatError(MediaDerivativeErrorBase):
    def __init__(self, fmt: str) -> None:
        super().__init__(
            422,
            "media_derivative.invalid_format",
            f"target_format '{fmt}' is not supported",
        )


class MediaDerivativeSourceMediaTypeUnavailableError(MediaDerivativeErrorBase):
    def __init__(self, media_type: str) -> None:
        super().__init__(
            422,
            "media_derivative.source_media_type_unavailable",
            f"source_media_type '{media_type}' is not supported",
        )


class MediaDerivativeUploadTooLargeError(MediaDerivativeErrorBase):
    def __init__(self) -> None:
        super().__init__(
            413,
            "media_derivative.upload_too_large",
            "uploaded file exceeds the size limit",
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


class MediaDerivativeSourceArtifactNotFoundError(MediaDerivativeErrorBase):
    def __init__(self) -> None:
        super().__init__(
            404,
            "media_derivative.source_artifact_not_found",
            "referenced source artifact not found",
        )


class MediaDerivativeArtifactExpiredError(MediaDerivativeErrorBase):
    def __init__(self, artifact_id: str) -> None:
        super().__init__(
            410,
            "media_derivative.artifact_expired",
            f"artifact '{artifact_id}' has expired and is no longer available",
        )
