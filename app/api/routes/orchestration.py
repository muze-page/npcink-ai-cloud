from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.adapters.queue.redis_runtime_queue import RedisRuntimeQueue
from app.api.auth import authorize_public_request, get_cloud_services
from app.api.envelope import build_envelope
from app.domain.orchestration.models import (
    OrchestrationStepDefinition,
    OrchestrationSubmission,
)
from app.domain.orchestration.service import (
    OrchestrationError,
    OrchestrationNotFoundError,
    OrchestrationService,
)

router = APIRouter(prefix="/v1/orchestration", tags=["orchestration"])


class StepDefinitionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = ""
    ability_name: str
    input_map: dict[str, Any] = Field(default_factory=dict)
    when: dict[str, Any] | None = None
    retry: int = 0
    timeout: int = 60
    foreach: str | None = None


class OrchestrationSubmitPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    workflow_version: int = 1
    steps: list[StepDefinitionPayload] = Field(..., min_length=1, max_length=50)
    initial_input: dict[str, Any] = Field(default_factory=dict)
    callback_url: str = ""
    max_duration_seconds: int = Field(default=3600, ge=1, le=86400)
    idempotency_key: str | None = None


def _get_orchestration_service(request: Request) -> OrchestrationService:
    services = get_cloud_services(request)
    from app.adapters.providers.registry import resolve_execution_provider_adapters
    from app.domain.runtime.service import RuntimeService

    runtime_queue = RedisRuntimeQueue(
        services.settings.redis_url,
        services.settings.runtime_queue_key + ":orchestration",
    )
    providers = resolve_execution_provider_adapters(services.settings)
    runtime_service = RuntimeService(
        services.settings.database_url,
        settings=services.settings,
        providers=providers,
        runtime_queue=runtime_queue,
    )
    return OrchestrationService(
        services.settings.database_url,
        settings=services.settings,
        runtime_service=runtime_service,
        runtime_queue=runtime_queue,
        callback_dispatcher=services.callback_dispatcher,
        callback_max_attempts=services.settings.runtime_callback_max_attempts,
        callback_retry_backoff_seconds=services.settings.runtime_callback_retry_backoff_seconds,
    )


def _orchestration_error_response(
    *,
    status_code: int,
    error_code: str,
    message: str,
    orchestration_run_id: str = "",
) -> JSONResponse:
    data: dict[str, Any] = {}
    if orchestration_run_id:
        data["orchestration_run_id"] = orchestration_run_id
    return JSONResponse(
        status_code=status_code,
        content=build_envelope(
            status="error",
            error_code=error_code,
            message=message,
            data=data,
            revision="m2",
        ),
    )


@router.post("/submit")
async def submit_orchestration(
    request: Request,
    payload: OrchestrationSubmitPayload,
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="runtime:write",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_orchestration_service(request)

    steps = [
        OrchestrationStepDefinition(
            step_id=s.step_id or f"step_{uuid4().hex[:8]}",
            ability_name=s.ability_name,
            input_map=s.input_map,
            when=s.when,
            retry=s.retry,
            timeout=s.timeout,
            foreach=s.foreach,
        )
        for s in payload.steps
    ]

    submission = OrchestrationSubmission(
        workflow_id=payload.workflow_id,
        workflow_version=payload.workflow_version,
        steps=steps,
        initial_input=payload.initial_input,
        callback_url=payload.callback_url,
        max_duration_seconds=payload.max_duration_seconds,
        idempotency_key=payload.idempotency_key,
        trace_id=None,
    )

    try:
        result = service.submit(auth.site_id, submission)
        return JSONResponse(
            status_code=201,
            content=build_envelope(
                status="ok",
                error_code="",
                message="Orchestration submitted",
                data={
                    "orchestration_run_id": result.orchestration_run_id,
                    "status": result.status,
                    "workflow_id": result.workflow_id,
                    "workflow_version": result.workflow_version,
                    "step_count": result.step_count,
                    "submitted_at": result.submitted_at,
                },
                revision="m2",
            ),
        )
    except OrchestrationError as e:
        return _orchestration_error_response(
            status_code=400,
            error_code="orchestration.submit_failed",
            message=str(e),
        )


@router.get("/{orchestration_run_id}")
async def get_orchestration(
    request: Request,
    orchestration_run_id: str,
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="runtime:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_orchestration_service(request)

    try:
        result = service.get_run(orchestration_run_id)
        if result.status not in ("queued", "running", "succeeded", "failed", "canceled"):
            return _orchestration_error_response(
                status_code=403,
                error_code="orchestration.access_denied",
                message="Access denied",
                orchestration_run_id=orchestration_run_id,
            )
        return JSONResponse(
            status_code=200,
            content=build_envelope(
                status="ok",
                error_code="",
                message="Orchestration run details",
                data={
                    "orchestration_run_id": result.orchestration_run_id,
                    "status": result.status,
                    "workflow_id": result.workflow_id,
                    "workflow_version": result.workflow_version,
                    "submitted_at": result.submitted_at,
                    "completed_at": result.completed_at,
                    "callback_url": result.callback_url,
                    "result_summary": result.result_summary,
                    "error_code": result.error_code,
                    "error_message": result.error_message,
                    "failed_step_index": result.failed_step_index,
                    "step_count": result.step_count,
                    "succeeded_count": result.succeeded_count,
                    "failed_count": result.failed_count,
                    "skipped_count": result.skipped_count,
                },
                revision="m2",
            ),
        )
    except OrchestrationNotFoundError:
        return _orchestration_error_response(
            status_code=404,
            error_code="orchestration.not_found",
            message="Orchestration run not found",
            orchestration_run_id=orchestration_run_id,
        )


@router.get("/{orchestration_run_id}/steps")
async def get_orchestration_steps(
    request: Request,
    orchestration_run_id: str,
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="runtime:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_orchestration_service(request)

    try:
        steps = service.get_steps(orchestration_run_id)
        return JSONResponse(
            status_code=200,
            content=build_envelope(
                status="ok",
                error_code="",
                message="Orchestration steps",
                data={
                    "orchestration_run_id": orchestration_run_id,
                    "steps": [
                        {
                            "step_id": s.step_id,
                            "step_index": s.step_index,
                            "ability_name": s.ability_name,
                            "status": s.status,
                            "input_payload": s.input_payload,
                            "step_output": s.step_output,
                            "started_at": s.started_at,
                            "completed_at": s.completed_at,
                            "error_code": s.error_code,
                            "error_message": s.error_message,
                            "retry_count": s.retry_count,
                            "max_retries": s.max_retries,
                            "timeout_seconds": s.timeout_seconds,
                            "foreach_iteration_count": s.foreach_iteration_count,
                        }
                        for s in steps
                    ],
                },
                revision="m2",
            ),
        )
    except OrchestrationNotFoundError:
        return _orchestration_error_response(
            status_code=404,
            error_code="orchestration.not_found",
            message="Orchestration run not found",
            orchestration_run_id=orchestration_run_id,
        )


@router.post("/{orchestration_run_id}/cancel")
async def cancel_orchestration(
    request: Request,
    orchestration_run_id: str,
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="runtime:write",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_orchestration_service(request)

    try:
        result = service.cancel(orchestration_run_id)
        return JSONResponse(
            status_code=200,
            content=build_envelope(
                status="ok",
                error_code="",
                message="Orchestration canceled",
                data={
                    "orchestration_run_id": result.orchestration_run_id,
                    "status": result.status,
                    "completed_at": result.completed_at,
                    "error_code": result.error_code,
                    "error_message": result.error_message,
                },
                revision="m2",
            ),
        )
    except OrchestrationNotFoundError:
        return _orchestration_error_response(
            status_code=404,
            error_code="orchestration.not_found",
            message="Orchestration run not found",
            orchestration_run_id=orchestration_run_id,
        )
    except OrchestrationError as e:
        return _orchestration_error_response(
            status_code=400,
            error_code="orchestration.cancel_failed",
            message=str(e),
        )
