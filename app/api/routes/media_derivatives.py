from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.adapters.providers.registry import resolve_execution_provider_adapters
from app.api.auth import authorize_public_request, get_cloud_services
from app.api.envelope import build_envelope
from app.api.media_ingress import MediaIngressError, receive_media_ingress
from app.core.db import get_session
from app.core.logging import get_logger
from app.core.security import PUBLIC_REPLAY_POLICY_MEDIA_PULL, extract_trace_id
from app.domain.media_artifacts import (
    ArtifactStoreError,
    build_artifact_store,
)
from app.domain.media_artifacts.delivery import (
    MediaArtifactDeliveryAckRequest,
    MediaArtifactDeliveryError,
    acknowledge_media_artifact_delivery,
    discard_pristine_media_artifact_delivery_best_effort,
    iter_verified_delivery_chunks,
    prepare_media_artifact_delivery,
    revalidate_committed_media_artifact_delivery,
)
from app.domain.media_derivatives.artifacts import validate_image_upload_stream
from app.domain.media_derivatives.contracts import (
    MAX_UPLOAD_BYTES_IMAGE,
    MediaJobRequest,
    MediaUploadRequest,
)
from app.domain.media_derivatives.errors import MediaDerivativeErrorBase
from app.domain.runtime.errors import RuntimeErrorBase
from app.domain.runtime.service import RuntimeService

logger = get_logger(__name__)
_MEDIA_ARTIFACT_ID_PATTERN = re.compile(r"^art_[0-9a-f]{32}$")

router = APIRouter(prefix="/v1/runtime", tags=["media-runtime"])


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
    revision: str = "md1",
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content=build_envelope(
            status="error",
            error_code=error_code,
            message=message,
            data={},
            trace_id=trace_id,
            revision=revision,
        ),
    )


def _parse_request_json(request_str: str, model: Any) -> Any:
    return model.model_validate(json.loads(request_str))


def _stream_signed_delivery_response(
    prepared: Any,
    *,
    database_url: str,
    trace_id: str,
) -> StreamingResponse:
    artifact = prepared.artifact
    extension = "jpg" if artifact.format == "jpeg" else str(artifact.format or "bin")
    if extension not in {
        "avif",
        "bin",
        "flac",
        "gif",
        "jpg",
        "m4a",
        "mp3",
        "ogg",
        "png",
        "wav",
        "webp",
    }:
        extension = "bin"
    return StreamingResponse(
        iter_verified_delivery_chunks(
            prepared.stream,
            database_url=database_url,
            artifact_id=prepared.artifact.artifact_id,
            site_id=prepared.artifact.site_id,
            delivery_id=prepared.delivery.delivery_id,
            expected_byte_size=prepared.delivery.expected_byte_size,
            expected_checksum=prepared.delivery.expected_checksum,
            chunk_size=prepared.chunk_size,
        ),
        media_type=artifact.content_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{artifact.artifact_id}.{extension}"'
            ),
            "Content-Length": str(artifact.byte_size),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Accept-Ranges": "none",
            "X-Npcink-Artifact-Id": artifact.artifact_id,
            "X-Npcink-Artifact-Checksum": artifact.checksum,
            "X-Npcink-Delivery-Id": prepared.delivery.delivery_id,
            "X-Npcink-Delivery-Ack-Deadline": prepared.delivery.ack_deadline_at.isoformat(),
            "X-Npcink-Trace-Id": trace_id,
        },
    )


def _prepare_signed_delivery(
    *,
    database_url: str,
    artifact_store: Any,
    artifact_id: str,
    site_id: str,
    trace_id: str,
) -> Any:
    session_context = get_session(database_url)
    session = session_context.__enter__()
    prepared = None
    primary_error: BaseException | None = None
    try:
        prepared = prepare_media_artifact_delivery(
            session=session,
            artifact_store=artifact_store,
            artifact_id=artifact_id,
            site_id=site_id,
            trace_id=trace_id,
        )
        session.commit()
    except BaseException as error:
        primary_error = error
    try:
        session_context.__exit__(
            type(primary_error) if primary_error is not None else None,
            primary_error,
            primary_error.__traceback__ if primary_error is not None else None,
        )
    except BaseException as error:
        if primary_error is None:
            primary_error = error
    if primary_error is not None:
        if prepared is not None:
            try:
                prepared.stream.close()
            except BaseException:
                pass
        raise primary_error
    assert prepared is not None

    try:
        revalidate_committed_media_artifact_delivery(
            database_url=database_url,
            artifact_id=prepared.artifact.artifact_id,
            site_id=prepared.artifact.site_id,
            delivery_id=prepared.delivery.delivery_id,
        )
    except MediaArtifactDeliveryError as error:
        try:
            prepared.stream.close()
        except BaseException:
            pass
        try:
            discard_pristine_media_artifact_delivery_best_effort(
                database_url=database_url,
                artifact_id=prepared.artifact.artifact_id,
                site_id=prepared.artifact.site_id,
                delivery_id=prepared.delivery.delivery_id,
            )
        except BaseException:
            pass
        raise error
    except BaseException:
        try:
            prepared.stream.close()
        except BaseException:
            pass
        raise
    return prepared


def _acknowledge_signed_delivery(
    *,
    database_url: str,
    artifact_id: str,
    site_id: str,
    idempotency_key: str,
    trace_id: str,
    payload: MediaArtifactDeliveryAckRequest,
) -> dict[str, object]:
    with get_session(database_url) as session:
        data = acknowledge_media_artifact_delivery(
            session=session,
            artifact_id=artifact_id,
            site_id=site_id,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            payload=payload,
        )
        session.commit()
        return data


def _execution_response(result: Any, *, message: str) -> JSONResponse:
    success = result.status in {"queued", "running", "succeeded"}
    return JSONResponse(
        content=build_envelope(
            status="ok" if success else "error",
            error_code="" if success else result.error_code,
            message=message,
            data={
                "run_id": result.run_id,
                "status": result.status,
                "trace_id": result.trace_id,
                "idempotent_replay": result.idempotent_replay,
                "result": result.result,
            },
            trace_id=result.trace_id,
            revision="media1",
        )
    )


@router.post("/media/uploads")
async def create_media_upload(request: Request) -> Any:
    services = get_cloud_services(request)
    try:
        ingress = await receive_media_ingress(
            request,
            max_body_bytes=services.settings.media_upload_max_body_bytes,
        )
    except MediaIngressError as error:
        return _media_error_response(
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
            trace_id=extract_trace_id(request.headers.get("traceparent", "")),
        )

    if isinstance(ingress, JSONResponse):
        return ingress
    try:
        if not ingress.request_json or ingress.file is None:
            return _media_error_response(
                status_code=400,
                error_code="media_upload.invalid_request",
                message="multipart request and file parts are required",
                trace_id=ingress.auth.trace_id,
            )
        try:
            upload_request = _parse_request_json(
                ingress.request_json,
                MediaUploadRequest,
            )
            if ingress.file.size is not None and ingress.file.size > MAX_UPLOAD_BYTES_IMAGE:
                return _media_error_response(
                    status_code=413,
                    error_code="media_upload.upload_too_large",
                    message="uploaded file exceeds the size limit",
                    trace_id=ingress.auth.trace_id,
                )
            upload = await run_in_threadpool(
                validate_image_upload_stream,
                ingress.file.file,
                declared_content_type=ingress.file.content_type or "",
            )
            result = await run_in_threadpool(
                _get_runtime_service(request).create_media_upload,
                site_id=ingress.auth.site_id,
                request_payload=upload_request.model_dump(),
                stream=ingress.file.file,
                upload=upload,
                ttl_minutes=upload_request.ttl_minutes,
                idempotency_key=ingress.auth.idempotency_key,
                trace_id=ingress.auth.trace_id,
            )
            return _execution_response(result, message="media upload accepted")
        except (json.JSONDecodeError, ValueError):
            return _media_error_response(
                status_code=422,
                error_code="media_upload.validation_error",
                message="media upload request is invalid",
                trace_id=ingress.auth.trace_id,
            )
        except (MediaDerivativeErrorBase, RuntimeErrorBase) as error:
            return _media_error_response(
                status_code=error.status_code,
                error_code=error.error_code,
                message=error.message,
                trace_id=ingress.auth.trace_id,
            )
        except ArtifactStoreError:
            return _media_error_response(
                status_code=503,
                error_code="media_upload.storage_unavailable",
                message="media artifact storage is unavailable",
                trace_id=ingress.auth.trace_id,
            )
    finally:
        await ingress.close()


@router.post("/media/jobs")
async def create_media_job(request: Request) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=True,
        required_scope="runtime:execute",
    )
    if isinstance(auth, JSONResponse):
        return auth
    try:
        payload = MediaJobRequest.model_validate(await request.json())
    except (json.JSONDecodeError, ValueError):
        return _media_error_response(
            status_code=422,
            error_code="media_job.validation_error",
            message="media job request is invalid",
            trace_id=auth.trace_id,
        )
    service = _get_runtime_service(request)
    try:
        result = await run_in_threadpool(
            service.enqueue_media_job_run,
            site_id=auth.site_id,
            input_payload=payload.model_dump(),
            idempotency_key=auth.idempotency_key,
            trace_id=auth.trace_id,
        )
    except (MediaDerivativeErrorBase, RuntimeErrorBase) as error:
        return _media_error_response(
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
            trace_id=auth.trace_id,
        )
    return _execution_response(result, message="media job queued")


@router.get("/media/artifacts/{artifact_id}/download")
async def download_media_artifact(request: Request, artifact_id: str) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="runtime:read",
        replay_policy=PUBLIC_REPLAY_POLICY_MEDIA_PULL,
    )
    if isinstance(auth, JSONResponse):
        return auth
    if request.url.query:
        return _media_error_response(
            status_code=400,
            error_code="media_artifact.query_not_allowed",
            message="media artifact download does not accept query parameters",
            trace_id=auth.trace_id,
            revision="media2",
        )
    if auth.idempotency_key:
        return _media_error_response(
            status_code=400,
            error_code="media_artifact.idempotency_key_not_allowed",
            message="Idempotency-Key is not allowed for media artifact download",
            trace_id=auth.trace_id,
            revision="media2",
        )
    if not _MEDIA_ARTIFACT_ID_PATTERN.fullmatch(artifact_id):
        return _media_error_response(
            status_code=404,
            error_code="media_artifact.not_found",
            message="media artifact was not found",
            trace_id=auth.trace_id,
            revision="media2",
        )
    if request.headers.get("range", "").strip():
        return _media_error_response(
            status_code=416,
            error_code="media_artifact.range_not_supported",
            message="media artifact download does not support byte ranges",
            trace_id=auth.trace_id,
            revision="media2",
            headers={"Accept-Ranges": "none"},
        )

    services = get_cloud_services(request)
    artifact_store = build_artifact_store(services.settings)
    try:
        prepared = await run_in_threadpool(
            _prepare_signed_delivery,
            database_url=services.settings.database_url,
            artifact_store=artifact_store,
            artifact_id=artifact_id,
            site_id=auth.site_id,
            trace_id=auth.trace_id,
        )
    except MediaArtifactDeliveryError as error:
        return _media_error_response(
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
            trace_id=auth.trace_id,
            revision="media2",
        )
    return _stream_signed_delivery_response(
        prepared,
        database_url=services.settings.database_url,
        trace_id=auth.trace_id,
    )


@router.post("/media/artifacts/{artifact_id}/delivery-ack")
async def acknowledge_media_artifact(request: Request, artifact_id: str) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=True,
        required_scope="runtime:execute",
    )
    if isinstance(auth, JSONResponse):
        return auth
    if request.url.query:
        return _media_error_response(
            status_code=400,
            error_code="media_artifact.query_not_allowed",
            message="query parameters are not allowed for media artifact acknowledgement",
            trace_id=auth.trace_id,
            revision="media2",
        )
    if not _MEDIA_ARTIFACT_ID_PATTERN.fullmatch(artifact_id):
        return _media_error_response(
            status_code=404,
            error_code="media_artifact.not_found",
            message="media artifact was not found",
            trace_id=auth.trace_id,
            revision="media2",
        )
    try:
        payload = MediaArtifactDeliveryAckRequest.model_validate(await request.json())
    except (json.JSONDecodeError, ValidationError):
        return _media_error_response(
            status_code=422,
            error_code="media_artifact.delivery_ack_validation_error",
            message="media artifact delivery acknowledgement request is invalid",
            trace_id=auth.trace_id,
            revision="media2",
        )
    services = get_cloud_services(request)
    try:
        data = await run_in_threadpool(
            _acknowledge_signed_delivery,
            database_url=services.settings.database_url,
            artifact_id=artifact_id,
            site_id=auth.site_id,
            idempotency_key=auth.idempotency_key,
            trace_id=auth.trace_id,
            payload=payload,
        )
    except MediaArtifactDeliveryError as error:
        return _media_error_response(
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
            trace_id=auth.trace_id,
            revision="media2",
        )
    return JSONResponse(
        content=build_envelope(
            status="ok",
            message="media artifact delivery acknowledged",
            data=data,
            trace_id=auth.trace_id,
            revision="media2",
        )
    )
