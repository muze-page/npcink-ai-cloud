from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.adapters.providers.registry import resolve_execution_provider_adapters
from app.api.auth import authorize_public_request, get_cloud_services
from app.api.envelope import build_envelope
from app.domain.commercial.service import ServiceAuditContext
from app.domain.runtime.errors import (
    RuntimeCancelNotAllowedError,
    RuntimeErrorBase,
    RuntimeResultExpiredError,
    RuntimeResultNotReadyError,
    RuntimeRunNotFoundError,
)
from app.domain.runtime.service import RuntimeService


class RuntimeRepairPayload(BaseModel):
    action: str = Field(min_length=1, max_length=64)
    operator_reason: str = Field(default="", max_length=512)
    operator_evidence: str = Field(default="", max_length=4000)


class RuntimeRetryPayload(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)


router = APIRouter(prefix="/v1/runs", tags=["runs"])


def _dict_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


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


def _run_error_response(
    *,
    status_code: int,
    error_code: str,
    message: str,
    run_id: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=build_envelope(
            status="error",
            error_code=error_code,
            message=message,
            data={"run_id": run_id},
            revision="m2",
        ),
    )


def _runtime_execution_response_payload(result: Any) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "canonical_run_id": result.canonical_run_id,
        "status": result.status,
        "trace_id": result.trace_id,
        "profile_id": result.profile_id,
        "provider_id": result.provider_id,
        "model_id": result.model_id,
        "instance_id": result.instance_id,
        "fallback_used": result.fallback_used,
        "idempotent_replay": result.idempotent_replay,
        "error_code": result.error_code,
        "error_message": result.error_message,
        "error_stage": result.error_stage,
        "retryable": result.retryable,
        "retry_exhausted": result.retry_exhausted,
        "provider_call_count": result.provider_call_count,
        "execution_context": {
            "skill_id": result.execution_context.skill_id,
            "workflow_id": result.execution_context.workflow_id,
            "contract_version": result.execution_context.contract_version,
            "ability_family": result.execution_context.ability_family,
            "execution_tier": result.execution_context.execution_tier,
            "execution_pattern": result.execution_context.execution_pattern,
            "data_classification": result.execution_context.data_classification,
            "storage_mode": result.execution_context.storage_mode,
        },
        "task_backend": result.task_backend,
        "run_lifecycle": result.run_lifecycle,
        "run_state": result.run_state,
        "result": result.result,
    }


@router.get("/nightly-inspection/recent")
async def list_recent_nightly_inspection_runs(
    request: Request,
    limit: int = 10,
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="runtime:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_runtime_service(request)
    result = await run_in_threadpool(
        service.list_recent_nightly_inspection_runs,
        site_id=auth.site_id,
        limit=limit,
    )
    return build_envelope(
        status="ok",
        message="nightly inspection recent runs loaded",
        data=result,
        revision="m1",
        trace_id=auth.trace_id,
    )


@router.get("/{run_id}")
async def get_run(
    request: Request,
    run_id: str,
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="runtime:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_runtime_service(request)

    try:
        run = await run_in_threadpool(service.get_run, run_id, site_id=auth.site_id)
    except RuntimeRunNotFoundError as error:
        return _run_error_response(
            status_code=404,
            error_code=error.error_code,
            message=error.message,
            run_id=run_id,
        )

    return build_envelope(
        status="ok",
        data=run,
        revision="m2",
        trace_id=str(run["trace_id"]),
    )


@router.post("/{run_id}/retry")
async def retry_run(
    request: Request,
    run_id: str,
    payload: RuntimeRetryPayload,
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=True,
        required_scope="runtime:execute",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_runtime_service(request)
    try:
        result = await run_in_threadpool(
            service.retry_nightly_inspection_run,
            run_id=run_id,
            site_id=auth.site_id,
            idempotency_key=auth.idempotency_key,
            trace_id=auth.trace_id,
            input_payload=payload.input,
        )
    except RuntimeErrorBase as error:
        return _run_error_response(
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
            run_id=run_id,
        )

    return build_envelope(
        status="ok",
        message="nightly inspection retry queued",
        data={
            "source_run_id": run_id,
            "retry_run": _runtime_execution_response_payload(result),
            "boundary": {
                "cloud_role": "runtime_detail",
                "cloud_scheduler_truth": False,
                "direct_wordpress_write": False,
            },
        },
        revision="m1",
        trace_id=result.trace_id,
    )


@router.get("/{run_id}/result")
async def get_run_result(
    request: Request,
    run_id: str,
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="runtime:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_runtime_service(request)

    try:
        result = await run_in_threadpool(service.get_run_result, run_id, site_id=auth.site_id)
    except RuntimeRunNotFoundError as error:
        return _run_error_response(
            status_code=404,
            error_code=error.error_code,
            message=error.message,
            run_id=run_id,
        )
    except RuntimeResultNotReadyError as error:
        return _run_error_response(
            status_code=409,
            error_code=error.error_code,
            message=error.message,
            run_id=run_id,
        )
    except RuntimeResultExpiredError as error:
        return _run_error_response(
            status_code=410,
            error_code=error.error_code,
            message=error.message,
            run_id=run_id,
        )

    return build_envelope(
        status="ok",
        data=result,
        revision="m2",
    )


@router.post("/{run_id}/cancel")
async def cancel_run(
    request: Request,
    run_id: str,
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=True,
        required_scope="runtime:execute",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_runtime_service(request)

    try:
        run = await run_in_threadpool(service.cancel_run, run_id, site_id=auth.site_id)
    except RuntimeRunNotFoundError as error:
        return _run_error_response(
            status_code=404,
            error_code=error.error_code,
            message=error.message,
            run_id=run_id,
        )
    except RuntimeCancelNotAllowedError as error:
        return _run_error_response(
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
            run_id=run_id,
        )

    run_lifecycle = _dict_value(run.get("run_lifecycle"))
    cancel = _dict_value(run_lifecycle.get("cancel"))
    cancel_state = str(cancel.get("state") or "")
    message = "run canceled" if cancel_state == "canceled" else "run cancel requested"
    return build_envelope(
        status="ok",
        message=message,
        data=run,
        revision="m2",
        trace_id=str(run["trace_id"]),
    )


@router.post("/{run_id}/repair")
async def repair_run(
    request: Request,
    run_id: str,
    payload: RuntimeRepairPayload,
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=True,
        required_scope="runtime:execute",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_runtime_service(request)

    try:
        result = await run_in_threadpool(
            service.repair_run,
            run_id=run_id,
            action=str(payload.action or ""),
            audit_context=ServiceAuditContext(
                trace_id=auth.trace_id,
                idempotency_key=auth.idempotency_key,
                method=request.method.upper(),
                path=request.url.path,
                actor_kind="site_key_operator",
                actor_ref=auth.key_id,
            ),
            site_id=auth.site_id,
            operator_reason=str(payload.operator_reason or ""),
            operator_evidence=str(payload.operator_evidence or ""),
        )
    except RuntimeErrorBase as error:
        return JSONResponse(
            status_code=error.status_code,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                data={"run_id": run_id},
                revision="m2",
            ),
        )

    return build_envelope(
        status="ok",
        message="已执行受限 repair。",
        data=result,
        revision="m2",
        trace_id=auth.trace_id,
    )
