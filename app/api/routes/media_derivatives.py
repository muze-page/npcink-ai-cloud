from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from python_multipart import FormParser
from starlette.concurrency import run_in_threadpool

from app.adapters.providers.registry import resolve_execution_provider_adapters
from app.api.auth import authorize_public_request, get_cloud_services
from app.api.envelope import build_envelope
from app.core.db import get_session
from app.core.logging import get_logger
from app.domain.media_derivatives.artifacts import (
    get_artifact,
    is_artifact_expired,
)
from app.domain.media_derivatives.contracts import (
    MAX_UPLOAD_BYTES_IMAGE,
    MediaDerivativeRequest,
)
from app.domain.media_derivatives.errors import MediaDerivativeErrorBase
from app.domain.media_derivatives.metrics import record_media_derivative_artifact_download
from app.domain.runtime.errors import RuntimeErrorBase
from app.domain.runtime.service import RuntimeService

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/runtime", tags=["media-derivatives"])


def _get_runtime_service(request: Request) -> RuntimeService:
    services = get_cloud_services(request)
    return RuntimeService(
        services.settings.database_url,
        settings=services.settings,
        providers=resolve_execution_provider_adapters(
            services.settings,
            base_providers=services.providers,
        ),
        runtime_queue=services.runtime_queue,
        callback_dispatcher=services.callback_dispatcher,
        callback_max_attempts=services.settings.runtime_callback_max_attempts,
        callback_retry_backoff_seconds=services.settings.runtime_callback_retry_backoff_seconds,
    )


def _media_error_response(
    *,
    status_code: int,
    error_code: str,
    message: str,
    trace_id: str = "",
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=build_envelope(
            status="error",
            error_code=error_code,
            message=message,
            data={},
            trace_id=trace_id,
            revision="md1",
        ),
    )


def _parse_request_json(request_str: str) -> MediaDerivativeRequest:
    data = json.loads(request_str)
    return MediaDerivativeRequest.model_validate(data)


def _remaining_artifact_seconds(artifact: Any) -> int:
    if not artifact.expires_at:
        return 0
    expires_at = artifact.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    remaining = expires_at - datetime.now(UTC)
    return max(0, int(remaining.total_seconds()))


def _stream_artifact_response(artifact: Any, *, cache_control: str) -> StreamingResponse:
    format_ext = artifact.format
    if format_ext == "jpeg":
        format_ext = "jpg"

    return StreamingResponse(
        iter([artifact.blob_data or b""]),
        media_type=artifact.mime_type,
        headers={
            "Content-Disposition": f'inline; filename="{artifact.artifact_id}.{format_ext}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": cache_control,
        },
    )


def _public_download_token_valid(artifact: Any, token: str) -> bool:
    if artifact.source_media_type != "audio":
        return False
    if not token:
        return False
    metadata = artifact.processing_warnings_json
    if not isinstance(metadata, dict):
        return False
    expected = str(metadata.get("public_download_token_sha256") or "")
    if not expected:
        return False
    actual = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(expected, actual)


@router.post("/media-derivatives")
async def create_media_derivative(request: Request) -> Any:
    services = get_cloud_services(request)
    auth = await authorize_public_request(
        request,
        require_idempotency=True,
        required_scope="runtime:execute",
        max_body_bytes=services.settings.media_derivative_max_body_bytes,
    )
    if isinstance(auth, JSONResponse):
        return auth

    body = await request.body()
    content_type = request.headers.get("content-type", "")

    request_json_str: str | None = None
    source_bytes: bytes | None = None
    watermark_bytes: bytes | None = None

    if "multipart/form-data" in content_type:
        fields: dict[str, str] = {}
        files: dict[str, bytes] = {}

        def _on_field(field: Any) -> None:
            name = (
                field.field_name.decode()
                if isinstance(field.field_name, bytes)
                else field.field_name
            )
            fields[name] = field.value

        def _on_file(file: Any) -> None:
            name = (
                file.field_name.decode() if isinstance(file.field_name, bytes) else file.field_name
            )
            file.file_object.seek(0)
            files[name] = file.file_object.read()

        boundary = None
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[9:].strip('"')
                break

        parser = FormParser("multipart/form-data", _on_field, _on_file, boundary=boundary)
        parser.write(body)
        parser.finalize()

        request_json_str = fields.get("request")
        source_bytes = files.get("source_file")
        watermark_bytes = files.get("watermark_file")
    else:
        request_json_str = body.decode("utf-8")

    if not request_json_str:
        return _media_error_response(
            status_code=400,
            error_code="media_derivative.invalid_request",
            message="request JSON is missing",
            trace_id=auth.trace_id,
        )

    try:
        derivative_request = _parse_request_json(request_json_str)
    except json.JSONDecodeError:
        return _media_error_response(
            status_code=400,
            error_code="media_derivative.invalid_request",
            message="request JSON is invalid",
            trace_id=auth.trace_id,
        )
    except ValueError as exc:
        error_message = str(exc)
        status_code = 422
        error_code = "media_derivative.validation_error"

        if "target_format" in error_message:
            error_code = "media_derivative.invalid_format"
        elif "source_media_type" in error_message:
            error_code = "media_derivative.source_media_type_unavailable"
        elif "watermark" in error_message:
            error_code = "media_derivative.invalid_watermark"
        elif "crop" in error_message:
            error_code = "media_derivative.invalid_crop"
        elif "ttl_minutes" in error_message:
            error_code = "media_derivative.validation_error"
        elif "quality" in error_message or "max_width" in error_message:
            error_code = "media_derivative.validation_error"

        return _media_error_response(
            status_code=status_code,
            error_code=error_code,
            message=error_message,
            trace_id=auth.trace_id,
        )

    source_artifact_id: str | None = None
    watermark_artifact_id: str | None = None

    if source_bytes is not None:
        if len(source_bytes) > MAX_UPLOAD_BYTES_IMAGE:
            return _media_error_response(
                status_code=413,
                error_code="media_derivative.upload_too_large",
                message="uploaded file exceeds the size limit",
                trace_id=auth.trace_id,
            )
    elif derivative_request.source is not None and derivative_request.source.artifact_id:
        source_artifact_id = derivative_request.source.artifact_id
    else:
        return _media_error_response(
            status_code=400,
            error_code="media_derivative.invalid_source",
            message="exactly one source mode is required",
            trace_id=auth.trace_id,
        )

    watermark = derivative_request.cloud_job_payload.watermark
    if watermark is None:
        if watermark_bytes is not None:
            return _media_error_response(
                status_code=400,
                error_code="media_derivative.invalid_watermark",
                message="watermark options are required when watermark_file is provided",
                trace_id=auth.trace_id,
            )
    elif watermark.type == "text":
        if watermark_bytes is not None or watermark.artifact_id:
            return _media_error_response(
                status_code=400,
                error_code="media_derivative.invalid_watermark",
                message="text watermark must not include watermark_file or watermark.artifact_id",
                trace_id=auth.trace_id,
            )
    elif watermark_bytes is not None:
        if watermark.artifact_id:
            return _media_error_response(
                status_code=400,
                error_code="media_derivative.invalid_watermark",
                message="exactly one watermark source mode is required",
                trace_id=auth.trace_id,
            )
        if len(watermark_bytes) > MAX_UPLOAD_BYTES_IMAGE:
            return _media_error_response(
                status_code=413,
                error_code="media_derivative.upload_too_large",
                message="uploaded watermark file exceeds the size limit",
                trace_id=auth.trace_id,
            )
    elif watermark is not None and watermark.artifact_id:
        watermark_artifact_id = watermark.artifact_id
    elif watermark is not None:
        return _media_error_response(
            status_code=400,
            error_code="media_derivative.invalid_watermark",
            message="watermark requires watermark_file or watermark.artifact_id",
            trace_id=auth.trace_id,
        )

    if source_artifact_id:
        with get_session(services.settings.database_url) as session:
            artifact = get_artifact(
                session,
                source_artifact_id,
                site_id=auth.site_id,
            )
            if artifact is None or is_artifact_expired(artifact):
                return _media_error_response(
                    status_code=404,
                    error_code="media_derivative.source_artifact_not_found",
                    message="referenced source artifact not found",
                    trace_id=auth.trace_id,
                )
            source_bytes = artifact.blob_data
            session.commit()

    if watermark_artifact_id:
        with get_session(services.settings.database_url) as session:
            artifact = get_artifact(
                session,
                watermark_artifact_id,
                site_id=auth.site_id,
            )
            if artifact is None or is_artifact_expired(artifact):
                return _media_error_response(
                    status_code=404,
                    error_code="media_derivative.watermark_artifact_not_found",
                    message="referenced watermark artifact not found",
                    trace_id=auth.trace_id,
                )
            watermark_bytes = artifact.blob_data
            session.commit()

    if not source_bytes:
        return _media_error_response(
            status_code=400,
            error_code="media_derivative.invalid_source",
            message="no source data available",
            trace_id=auth.trace_id,
        )

    input_payload = {
        "cloud_job_payload": derivative_request.cloud_job_payload.model_dump(),
        "source_media_type": derivative_request.cloud_job_payload.source_media_type,
        "ttl_minutes": derivative_request.ttl_minutes,
    }
    if derivative_request.batch_context is not None:
        input_payload["batch_context"] = derivative_request.batch_context.model_dump()

    service = _get_runtime_service(request)
    queue_pressure_before = service.get_media_derivative_queue_pressure(site_id=auth.site_id)
    if str(queue_pressure_before.get("pressure_state") or "") == "rejecting":
        return _media_error_response(
            status_code=429,
            error_code="media_derivative.site_queue_full",
            message="site media derivative queue is full; retry after current chunks finish",
            trace_id=auth.trace_id,
        )

    try:
        result = await run_in_threadpool(
            service.enqueue_media_derivative_run,
            site_id=auth.site_id,
            input_payload=input_payload,
            source_bytes=source_bytes,
            watermark_bytes=watermark_bytes,
            ttl_minutes=derivative_request.ttl_minutes,
            idempotency_key=auth.idempotency_key,
            trace_id=auth.trace_id,
        )
    except MediaDerivativeErrorBase as error:
        return _media_error_response(
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
            trace_id=auth.trace_id,
        )
    except RuntimeErrorBase as error:
        return _media_error_response(
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
            trace_id=auth.trace_id,
        )

    success_statuses = {"queued", "running", "succeeded"}
    status = "ok" if result.status in success_statuses else "error"
    error_code = "" if result.status in success_statuses else result.error_code
    queue_pressure_after = service.get_media_derivative_queue_pressure(site_id=auth.site_id)
    batch_context = (
        derivative_request.batch_context.model_dump()
        if derivative_request.batch_context is not None
        else {}
    )
    return JSONResponse(
        content=build_envelope(
            status=status,
            error_code=error_code,
            message=(
                "media derivative queued"
                if result.status == "queued"
                else "media derivative processed"
            ),
            data={
                "run_id": result.run_id,
                "status": result.status,
                "trace_id": result.trace_id,
                "execution_context": {
                    "skill_id": result.execution_context.skill_id,
                    "ability_family": result.execution_context.ability_family,
                    "execution_pattern": result.execution_context.execution_pattern,
                },
                "result": result.result,
                "batch": {
                    "context": batch_context,
                    "chunking": {
                        "recommended_chunk_size": queue_pressure_after.get(
                            "recommended_chunk_size",
                            services.settings.media_derivative_batch_default_chunk_size,
                        ),
                        "max_chunk_size": services.settings.media_derivative_batch_max_chunk_size,
                    },
                    "avif_policy": {
                        "batch_requires_explicit_opt_in": True,
                    },
                },
                "queue_pressure": queue_pressure_after,
            },
            trace_id=result.trace_id,
            revision="md1",
        ),
    )


@router.get("/artifacts/{artifact_id}/download")
async def download_artifact(
    request: Request,
    artifact_id: str,
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="runtime:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    services = get_cloud_services(request)
    with get_session(services.settings.database_url) as session:
        artifact = get_artifact(session, artifact_id, site_id=auth.site_id)
        if artifact is None:
            return _media_error_response(
                status_code=404,
                error_code="media_derivative.artifact_not_found",
                message="artifact not found",
                trace_id=auth.trace_id,
            )

        if is_artifact_expired(artifact):
            return _media_error_response(
                status_code=410,
                error_code="media_derivative.artifact_expired",
                message=f"artifact '{artifact_id}' has expired",
                trace_id=auth.trace_id,
            )

        remaining_seconds = _remaining_artifact_seconds(artifact)
        record_media_derivative_artifact_download(
            session=session,
            artifact_id=artifact.artifact_id,
        )
        session.commit()

    return _stream_artifact_response(
        artifact,
        cache_control=f"private, max-age={remaining_seconds}",
    )


@router.get("/artifacts/{artifact_id}/public-download")
async def public_download_artifact(
    request: Request,
    artifact_id: str,
    token: str = "",
) -> Any:
    services = get_cloud_services(request)
    with get_session(services.settings.database_url) as session:
        artifact = get_artifact(session, artifact_id)
        if artifact is None:
            return _media_error_response(
                status_code=404,
                error_code="media_derivative.artifact_not_found",
                message="artifact not found",
            )

        if is_artifact_expired(artifact):
            return _media_error_response(
                status_code=410,
                error_code="media_derivative.artifact_expired",
                message=f"artifact '{artifact_id}' has expired",
            )

        if not _public_download_token_valid(artifact, token):
            return _media_error_response(
                status_code=403,
                error_code="media_derivative.public_artifact_token_invalid",
                message="artifact download token is invalid",
            )

        remaining_seconds = _remaining_artifact_seconds(artifact)
        record_media_derivative_artifact_download(
            session=session,
            artifact_id=artifact.artifact_id,
        )
        session.commit()

    return _stream_artifact_response(
        artifact,
        cache_control=f"public, max-age={remaining_seconds}",
    )
