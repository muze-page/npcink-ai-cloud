from __future__ import annotations

import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any, BinaryIO, Protocol
from uuid import uuid4

from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from app.core.models import MediaArtifact, RunRecord
from app.domain.image_generation.contracts import IMAGE_GENERATION_RESULT_CONTRACT
from app.domain.image_generation.provider_fetch import (
    PROVIDER_IMAGE_DEFAULT_MAX_BYTES,
    PROVIDER_IMAGE_DEFAULT_TIMEOUT_SECONDS,
    ProviderFetchedImage,
    ProviderImageFetchError,
    fetch_provider_image_url,
)
from app.domain.media_artifacts import (
    ArtifactStorageMetadata,
    ArtifactStore,
    ArtifactStoreError,
    ArtifactStorePublicationUncertainError,
)
from app.domain.media_artifacts.publication import (
    delete_tracked_artifact_publication,
    forget_artifact_publications,
    publish_and_track_artifact,
    quarantine_artifact_publications,
)
from app.domain.media_derivatives.contracts import (
    MAX_DECODED_IMAGE_BYTES,
    MAX_IMAGE_DIMENSION,
    MAX_PIXEL_COUNT,
    MIME_TYPE_BY_FORMAT,
    PILLOW_FORMAT_BY_TARGET,
)

IMAGE_GENERATION_OPERATION = "image.generate.v1"
IMAGE_GENERATION_ARTIFACT_TYPE = "image_generation_artifacts"
IMAGE_GENERATION_DEFAULT_TTL_MINUTES = 30
# Source bytes plus sanitized artifact bytes share this aggregate I/O budget.
IMAGE_GENERATION_DEFAULT_MAX_RUN_BYTES = 64 * 1024 * 1024
IMAGE_GENERATION_MAX_CANDIDATES = 4

_PILLOW_FORMATS = frozenset({"AVIF", "JPEG", "PNG", "WEBP"})
_BINARY_CONTENT_TYPES = frozenset({"", "application/octet-stream", "binary/octet-stream"})


class ProviderMediaCandidateLike(Protocol):
    @property
    def source_url(self) -> str | None: ...

    @property
    def content_bytes(self) -> bytes | None: ...

    @property
    def image_output_hosts(self) -> Sequence[str]: ...

    @property
    def index(self) -> int: ...

    @property
    def claimed_mime_type(self) -> str | None: ...

    @property
    def revised_prompt(self) -> str | None: ...

    @property
    def claimed_width(self) -> int | None: ...

    @property
    def claimed_height(self) -> int | None: ...


class ImageGenerationArtifactMaterializationError(RuntimeError):
    error_code = "image_generation.artifact_materialization_failed"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ImageGenerationArtifactCleanupUncertainError(
    ImageGenerationArtifactMaterializationError
):
    error_code = "image_generation.artifact_cleanup_uncertain"

    def __init__(self, storage_keys: Sequence[str]) -> None:
        super().__init__("generated image artifact cleanup is uncertain")
        self.storage_keys = tuple(storage_keys)


@dataclass(frozen=True, slots=True)
class ImageGenerationMaterializationConfig:
    ttl_minutes: int = IMAGE_GENERATION_DEFAULT_TTL_MINUTES
    max_image_bytes: int = PROVIDER_IMAGE_DEFAULT_MAX_BYTES
    max_run_bytes: int = IMAGE_GENERATION_DEFAULT_MAX_RUN_BYTES
    timeout_seconds: float = PROVIDER_IMAGE_DEFAULT_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class CleanedProviderImage:
    stream: BinaryIO
    byte_size: int
    content_type: str
    format: str
    width: int
    height: int

    def close(self) -> None:
        self.stream.close()


ProviderImageURLFetcher = Callable[..., ProviderFetchedImage]


def materialize_image_generation_candidates(
    *,
    session: Session,
    artifact_store: ArtifactStore,
    run: RunRecord,
    media_candidates: Sequence[ProviderMediaCandidateLike],
    provider_output: dict[str, Any],
    config: ImageGenerationMaterializationConfig | None = None,
    url_fetcher: ProviderImageURLFetcher | None = None,
) -> dict[str, Any]:
    """Publish sanitized provider images as one all-or-nothing artifact batch."""

    if not isinstance(provider_output, dict):
        raise ImageGenerationArtifactMaterializationError(
            "provider image output is invalid"
        )
    _validate_candidate_envelope(provider_output, media_candidates=media_candidates)

    resolved_config = config or ImageGenerationMaterializationConfig()
    max_image_bytes = max(1, int(resolved_config.max_image_bytes))
    max_run_bytes = max(1, int(resolved_config.max_run_bytes))
    ttl_minutes = max(1, int(resolved_config.ttl_minutes))
    fetch_url = url_fetcher or fetch_provider_image_url
    stored_batch: list[ArtifactStorageMetadata] = []
    artifacts: list[MediaArtifact] = []
    run_io_bytes = 0
    savepoint = session.begin_nested()

    try:
        for candidate in media_candidates:
            source_stream: BinaryIO | None = None
            fetched: ProviderFetchedImage | None = None
            try:
                content_bytes = getattr(candidate, "content_bytes", None)
                source_url = str(getattr(candidate, "source_url", None) or "").strip()
                if bool(content_bytes) == bool(source_url):
                    raise ImageGenerationArtifactMaterializationError(
                        "generated image candidate must have exactly one source"
                    )

                declared_mime_types = [
                    str(getattr(candidate, "claimed_mime_type", None) or "")
                ]
                if content_bytes:
                    if not isinstance(content_bytes, bytes):
                        raise ImageGenerationArtifactMaterializationError(
                            "generated image bytes are invalid"
                        )
                    source_byte_size = len(content_bytes)
                    source_stream = BytesIO(content_bytes)
                else:
                    remaining_source_bytes = max_run_bytes - run_io_bytes
                    if remaining_source_bytes <= 0:
                        raise ImageGenerationArtifactMaterializationError(
                            "generated images exceed the run byte limit"
                        )
                    fetched = fetch_url(
                        source_url,
                        allowed_hosts=tuple(getattr(candidate, "image_output_hosts", ())),
                        max_bytes=min(max_image_bytes, remaining_source_bytes),
                        timeout_seconds=max(
                            0.001,
                            float(resolved_config.timeout_seconds),
                        ),
                    )
                    source_stream = fetched.stream
                    source_byte_size = fetched.byte_size
                    declared_mime_types.append(fetched.declared_mime_type)

                if source_byte_size <= 0 or source_byte_size > max_image_bytes:
                    raise ImageGenerationArtifactMaterializationError(
                        "generated image exceeds the image byte limit"
                    )
                run_io_bytes += source_byte_size
                if run_io_bytes > max_run_bytes:
                    raise ImageGenerationArtifactMaterializationError(
                        "generated images exceed the run byte limit"
                    )
                assert source_stream is not None
                cleaned = clean_provider_image(
                    source_stream,
                    declared_mime_types=declared_mime_types,
                    max_output_bytes=max_image_bytes,
                )
                try:
                    _validate_claimed_dimensions(candidate, cleaned=cleaned)
                    run_io_bytes += cleaned.byte_size
                    if run_io_bytes > max_run_bytes:
                        raise ImageGenerationArtifactMaterializationError(
                            "generated artifacts exceed the run byte limit"
                        )
                    try:
                        stored = publish_and_track_artifact(
                            session,
                            store=artifact_store,
                            stream=cleaned.stream,
                            max_bytes=min(
                                max_image_bytes,
                                max_run_bytes - (run_io_bytes - cleaned.byte_size),
                            ),
                            metadata={"operation": IMAGE_GENERATION_OPERATION},
                            cleanup_error_factory=_cleanup_error,
                        )
                    except ArtifactStorePublicationUncertainError as error:
                        stored_batch.append(error.storage_metadata)
                        raise
                    stored_batch.append(stored)
                    if (
                        stored.byte_size != cleaned.byte_size
                        or stored.byte_size <= 0
                        or not str(stored.checksum).startswith("sha256:")
                        or len(str(stored.checksum)) != 71
                    ):
                        raise ImageGenerationArtifactMaterializationError(
                            "generated artifact storage metadata is invalid"
                        )
                    artifact = _create_image_generation_artifact(
                        session=session,
                        run=run,
                        stored=stored,
                        cleaned=cleaned,
                        ttl_minutes=ttl_minutes,
                    )
                    artifacts.append(artifact)
                finally:
                    cleaned.close()
            finally:
                if fetched is not None:
                    fetched.close()
                elif source_stream is not None:
                    source_stream.close()
        savepoint.commit()
    except Exception as error:
        if savepoint.is_active:
            savepoint.rollback()
        _cleanup_failed_batch(
            session=session,
            artifact_store=artifact_store,
            stored_batch=stored_batch,
        )
        if isinstance(error, ImageGenerationArtifactMaterializationError):
            raise
        if isinstance(error, ProviderImageFetchError):
            raise ImageGenerationArtifactMaterializationError(
                "provider image could not be materialized"
            ) from error
        if isinstance(error, ArtifactStoreError):
            raise ImageGenerationArtifactMaterializationError(
                "generated image artifact could not be stored"
            ) from error
        raise ImageGenerationArtifactMaterializationError(
            "generated image artifact materialization failed"
        ) from error

    return {
        "contract_version": IMAGE_GENERATION_RESULT_CONTRACT,
        "artifact_type": IMAGE_GENERATION_ARTIFACT_TYPE,
        "operation": IMAGE_GENERATION_OPERATION,
        "artifacts": [_artifact_result(artifact) for artifact in artifacts],
        "suggestion_only": True,
        "requires_local_review": True,
    }


def clean_provider_image(
    stream: BinaryIO,
    *,
    declared_mime_types: Sequence[str],
    max_output_bytes: int,
) -> CleanedProviderImage:
    output: BinaryIO | None = None
    try:
        detected_format = _verified_source_format(stream)
        detected_content_type = MIME_TYPE_BY_FORMAT[detected_format]
        _validate_declared_mime_types(
            declared_mime_types,
            detected_content_type=detected_content_type,
        )

        stream.seek(0)
        with Image.open(stream) as decoded:
            _validate_image_bounds(decoded)
            if int(getattr(decoded, "n_frames", 1)) != 1:
                raise ImageGenerationArtifactMaterializationError(
                    "animated generated images are not supported"
                )
            decoded.load()
            transposed = ImageOps.exif_transpose(decoded)
            _validate_image_bounds(transposed)
            normalized = _normalized_image(transposed, detected_format)
            try:
                normalized.info.clear()
                output = tempfile.TemporaryFile(mode="w+b")
                normalized.save(
                    output,
                    format=PILLOW_FORMAT_BY_TARGET[detected_format],
                    **_save_options(detected_format),
                )
            finally:
                normalized.close()
                if transposed is not decoded:
                    transposed.close()

        output.seek(0, 2)
        byte_size = output.tell()
        if byte_size <= 0 or byte_size > max(1, int(max_output_bytes)):
            raise ImageGenerationArtifactMaterializationError(
                "generated artifact exceeds the image byte limit"
            )
        output.seek(0)
        with Image.open(output) as verified:
            _validate_image_bounds(verified)
            if int(getattr(verified, "n_frames", 1)) != 1:
                raise ImageGenerationArtifactMaterializationError(
                    "generated artifact is not a static image"
                )
            verified_format = str(verified.format or "").upper()
            if verified_format != PILLOW_FORMAT_BY_TARGET[detected_format]:
                raise ImageGenerationArtifactMaterializationError(
                    "generated artifact format is invalid"
                )
            verified.verify()
            width = int(verified.width)
            height = int(verified.height)
        output.seek(0)
        return CleanedProviderImage(
            stream=output,
            byte_size=byte_size,
            content_type=detected_content_type,
            format=detected_format,
            width=width,
            height=height,
        )
    except ImageGenerationArtifactMaterializationError:
        if output is not None:
            output.close()
        raise
    except Image.DecompressionBombError as error:
        if output is not None:
            output.close()
        raise ImageGenerationArtifactMaterializationError(
            "generated image exceeds the decode limit"
        ) from error
    except (KeyError, OSError, SyntaxError, ValueError) as error:
        if output is not None:
            output.close()
        raise ImageGenerationArtifactMaterializationError(
            "generated image could not be decoded"
        ) from error


def _verified_source_format(stream: BinaryIO) -> str:
    try:
        stream.seek(0)
        header = stream.read(64)
        stream.seek(0)
    except OSError as error:
        raise ImageGenerationArtifactMaterializationError(
            "generated image source is unavailable"
        ) from error
    magic_format = _magic_format(header)
    if not magic_format:
        raise ImageGenerationArtifactMaterializationError(
            "generated image format is not supported"
        )
    try:
        with Image.open(stream) as probe:
            _validate_image_bounds(probe)
            if int(getattr(probe, "n_frames", 1)) != 1:
                raise ImageGenerationArtifactMaterializationError(
                    "animated generated images are not supported"
                )
            pillow_format = str(probe.format or "").upper()
            if pillow_format not in _PILLOW_FORMATS or pillow_format != magic_format:
                raise ImageGenerationArtifactMaterializationError(
                    "generated image format is not supported"
                )
            probe.verify()
    finally:
        stream.seek(0)
    return magic_format.lower()


def _magic_format(header: bytes) -> str:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if header.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "WEBP"
    if len(header) >= 16 and header[4:8] == b"ftyp":
        brands = {header[8:12]}
        brands.update(header[offset : offset + 4] for offset in range(16, len(header), 4))
        if b"avif" in brands or b"avis" in brands:
            return "AVIF"
    return ""


def _validate_image_bounds(image: Image.Image) -> None:
    width = int(image.width)
    height = int(image.height)
    if (
        width < 1
        or height < 1
        or width > MAX_IMAGE_DIMENSION
        or height > MAX_IMAGE_DIMENSION
        or width * height > MAX_PIXEL_COUNT
        or width * height * 4 > MAX_DECODED_IMAGE_BYTES
    ):
        raise ImageGenerationArtifactMaterializationError(
            "generated image exceeds the decode limit"
        )


def _validate_declared_mime_types(
    values: Sequence[str],
    *,
    detected_content_type: str,
) -> None:
    for value in values:
        content_type = str(value or "").split(";", 1)[0].strip().lower()
        if content_type in _BINARY_CONTENT_TYPES:
            continue
        if content_type == "image/jpg":
            content_type = "image/jpeg"
        if content_type != detected_content_type:
            raise ImageGenerationArtifactMaterializationError(
                "generated image MIME type does not match its content"
            )


def _validate_candidate_envelope(
    provider_output: dict[str, Any],
    *,
    media_candidates: Sequence[ProviderMediaCandidateLike],
) -> None:
    candidate_count = provider_output.get("candidate_count")
    if (
        isinstance(candidate_count, bool)
        or not isinstance(candidate_count, int)
        or candidate_count != len(media_candidates)
        or not (1 <= candidate_count <= IMAGE_GENERATION_MAX_CANDIDATES)
    ):
        raise ImageGenerationArtifactMaterializationError(
            "provider image candidate count is invalid"
        )
    indices = [getattr(candidate, "index", None) for candidate in media_candidates]
    if indices != list(range(1, candidate_count + 1)):
        raise ImageGenerationArtifactMaterializationError(
            "provider image candidate indices are invalid"
        )


def _validate_claimed_dimensions(
    candidate: ProviderMediaCandidateLike,
    *,
    cleaned: CleanedProviderImage,
) -> None:
    claimed_width = getattr(candidate, "claimed_width", None)
    claimed_height = getattr(candidate, "claimed_height", None)
    if claimed_width is not None and int(claimed_width) != cleaned.width:
        raise ImageGenerationArtifactMaterializationError(
            "generated image width does not match provider metadata"
        )
    if claimed_height is not None and int(claimed_height) != cleaned.height:
        raise ImageGenerationArtifactMaterializationError(
            "generated image height does not match provider metadata"
        )


def _normalized_image(image: Image.Image, image_format: str) -> Image.Image:
    has_alpha = image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    )
    if image_format == "jpeg":
        if has_alpha:
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            rgba.close()
            return background
        return image.convert("RGB")
    if image_format in {"webp", "avif"}:
        return image.convert("RGBA" if has_alpha else "RGB")
    if image.mode in {"1", "L", "LA", "RGB", "RGBA"}:
        return image.copy()
    return image.convert("RGBA" if has_alpha else "RGB")


def _save_options(image_format: str) -> dict[str, Any]:
    options: dict[str, Any] = {"exif": b"", "icc_profile": None}
    if image_format == "jpeg":
        options.update({"quality": 90, "optimize": True, "progressive": False})
    elif image_format == "png":
        options["optimize"] = True
    elif image_format == "webp":
        options.update({"quality": 90, "method": 4, "xmp": b""})
    elif image_format == "avif":
        options.update({"quality": 80, "xmp": b""})
    return options


def _create_image_generation_artifact(
    *,
    session: Session,
    run: RunRecord,
    stored: ArtifactStorageMetadata,
    cleaned: CleanedProviderImage,
    ttl_minutes: int,
) -> MediaArtifact:
    artifact = MediaArtifact(
        artifact_id=f"art_{uuid4().hex}",
        run_id=run.run_id,
        site_id=run.site_id,
        media_kind="image",
        operation=IMAGE_GENERATION_OPERATION,
        content_type=cleaned.content_type,
        byte_size=stored.byte_size,
        storage_key=stored.storage_key,
        status="available",
        format=cleaned.format,
        width=cleaned.width,
        height=cleaned.height,
        checksum=stored.checksum,
        processing_warnings_json={"warnings": []},
        expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes),
    )
    session.add(artifact)
    session.flush()
    return artifact


def _artifact_result(artifact: MediaArtifact) -> dict[str, Any]:
    return {
        "artifact_id": artifact.artifact_id,
        "artifact_reference": {"artifact_id": artifact.artifact_id},
        "status": artifact.status,
        "media_kind": artifact.media_kind,
        "operation": artifact.operation,
        "content_type": artifact.content_type,
        "format": artifact.format,
        "width": artifact.width,
        "height": artifact.height,
        "filesize_bytes": artifact.byte_size,
        "checksum": artifact.checksum,
        "expires_at": artifact.expires_at.isoformat(),
    }


def _cleanup_failed_batch(
    *,
    session: Session,
    artifact_store: ArtifactStore,
    stored_batch: Sequence[ArtifactStorageMetadata],
) -> None:
    deleted: list[str] = []
    failed: list[str] = []
    for stored in reversed(stored_batch):
        try:
            if not delete_tracked_artifact_publication(
                session,
                store=artifact_store,
                storage_key=stored.storage_key,
            ):
                raise ArtifactStoreError("artifact publication tracker is unavailable")
            deleted.append(stored.storage_key)
        except Exception:
            failed.append(stored.storage_key)
    forget_artifact_publications(
        session,
        store=artifact_store,
        storage_keys=deleted,
    )
    if failed:
        quarantine_artifact_publications(
            session,
            store=artifact_store,
            storage_keys=failed,
        )
        raise ImageGenerationArtifactCleanupUncertainError(tuple(failed))


def _cleanup_error(storage_keys: tuple[str, ...]) -> BaseException:
    return ImageGenerationArtifactCleanupUncertainError(storage_keys)
