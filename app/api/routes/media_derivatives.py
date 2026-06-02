from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.adapters.providers.registry import resolve_execution_provider_adapters
from app.api.auth import authorize_public_request, get_cloud_services
from app.api.envelope import build_envelope
from app.core.config import Settings
from app.core.db import get_session
from app.core.logging import get_logger
from app.domain.media_derivatives.artifacts import (
    get_artifact,
    is_artifact_expired,
)
from app.domain.media_derivatives.contracts import (
    MAX_UPLOAD_BYTES_IMAGE,
    BLOCKED_RESPONSE_FIELDS,
    MediaDerivativeRequest,
)
from app.domain.media_derivatives.errors import MediaDerivativeErrorBase
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


@router.post("/media-derivatives")
async def create_media_derivative(
    request: Request,
    request_form: str = Form(..., alias="request"),
    source_file: UploadFile | None = File(None),
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=True,
        required_scope="runtime:execute",
    )
    if isinstance(auth, JSONResponse):
        return auth

    try:
        derivative_request = _parse_request_json(request_form)
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

    source_bytes: bytes | None = None
    source_artifact_id: str | None = None

    if source_file is not None:
        source_bytes = await source_file.read()
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

    if source_artifact_id:
        services = get_cloud_services(request)
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

    service = _get_runtime_service(request)

    try:
        result = await run_in_threadpool(
            service.enqueue_media_derivative_run,
            site_id=auth.site_id,
            input_payload=input_payload,
            source_bytes=source_bytes,
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

    success_statuses = {"queued", "running", "succeeded"}
    status = "ok" if result.status in success_statuses else "error"
    error_code = "" if result.status in success_statuses else result.error_code
    return JSONResponse(
        content=build_envelope(
            status=status,
            error_code=error_code,
            message="media derivative queued" if result.status == "queued" else "media derivative processed",
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

        remaining_seconds = 0
        if artifact.expires_at:
            expires_at = artifact.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            remaining = expires_at - datetime.now(UTC)
            remaining_seconds = max(0, int(remaining.total_seconds()))

        blob_data = artifact.blob_data or b""
        session.commit()

    format_ext = artifact.format
    if format_ext == "jpeg":
        format_ext = "jpg"

    return StreamingResponse(
        iter([blob_data]),
        media_type=artifact.mime_type,
        headers={
            "Content-Disposition": f'inline; filename="{artifact.artifact_id}.{format_ext}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": f"private, max-age={remaining_seconds}",
        },
    )
