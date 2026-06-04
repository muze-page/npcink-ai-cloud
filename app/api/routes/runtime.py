from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

from app.adapters.providers.registry import resolve_execution_provider_adapters
from app.api.auth import authorize_public_request, get_cloud_services
from app.api.envelope import build_envelope
from app.core.security import RequestAuthContext
from app.domain.routing.errors import RoutingError
from app.domain.runtime.errors import RuntimeErrorBase, RuntimeUnsupportedExecutionPatternError
from app.domain.runtime.models import (
    BLOCKED_RUNTIME_GOVERNANCE_POLICY_KEYS,
    RuntimeRequest,
    normalize_runtime_request_policy,
)
from app.domain.runtime.service import RuntimeService
from app.domain.site_knowledge.contracts import (
    SITE_KNOWLEDGE_ABILITIES,
    SITE_KNOWLEDGE_ABILITY_FAMILY,
    SITE_KNOWLEDGE_DATA_CLASSIFICATION,
    SITE_KNOWLEDGE_EXECUTION_KIND,
    SITE_KNOWLEDGE_PROFILE_ID,
    SITE_KNOWLEDGE_SYNC_ABILITY,
)

router = APIRouter(prefix="/v1/runtime", tags=["runtime"])


class RuntimePolicyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_fallback: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_local_governance_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        blocked_keys = sorted(
            key for key in value.keys() if key in BLOCKED_RUNTIME_GOVERNANCE_POLICY_KEYS
        )
        if blocked_keys:
            raise ValueError(
                "policy may not include local governance or final-write fields: "
                + ", ".join(blocked_keys)
            )

        return value

    def to_runtime_policy(self) -> dict[str, object]:
        return normalize_runtime_request_policy(self.model_dump(exclude_none=True))


class RuntimePayload(BaseModel):
    site_id: str | None = None
    ability_name: str
    ability_family: Literal[
        "text",
        "vision",
        "workflow",
        "automation",
        "mcp",
        "openclaw",
        "knowledge",
    ] = "text"
    canonical_run_id: str | None = None
    skill_id: str | None = None
    workflow_id: str | None = None
    contract_version: str = Field(default="v1", min_length=1)
    channel: str = "openapi"
    execution_kind: str = ""
    execution_tier: Literal["cloud"] = "cloud"
    execution_pattern: Literal["inline", "whole_run_offload"] = "inline"
    data_classification: Literal[
        "public",
        "internal",
        "pii",
        "secret",
        "public_site_content",
    ] = "internal"
    storage_mode: Literal["no_store", "result_only", "full_store_with_ttl"] = "result_only"
    timeout_seconds: int = 0
    retry_max: int = 0
    retention_ttl: int = 0
    callback_url: str = ""
    task_backend: dict[str, Any] = Field(default_factory=dict)
    profile_id: str = ""
    idempotency_key: str | None = None
    trace_id: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    policy: RuntimePolicyPayload = Field(default_factory=RuntimePolicyPayload)


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


def _build_runtime_request(
    request: Request,
    payload: RuntimePayload,
    auth: RequestAuthContext,
) -> RuntimeRequest:
    return RuntimeRequest(
        site_id=auth.site_id,
        ability_name=payload.ability_name,
        ability_family=_resolve_ability_family(payload),
        canonical_run_id=payload.canonical_run_id or "",
        skill_id=payload.skill_id or "",
        workflow_id=payload.workflow_id or "",
        contract_version=payload.contract_version or "v1",
        channel=payload.channel,
        execution_kind=_resolve_execution_kind(payload),
        execution_tier=payload.execution_tier,
        execution_pattern=_normalize_runtime_execution_pattern(payload.execution_pattern),
        data_classification=_resolve_data_classification(payload),
        storage_mode=payload.storage_mode,
        timeout_seconds=max(0, payload.timeout_seconds),
        retry_max=max(0, payload.retry_max),
        retention_ttl=max(0, payload.retention_ttl),
        callback_url=payload.callback_url or "",
        task_backend=_resolve_task_backend(payload),
        profile_id=_resolve_profile_id(payload),
        input_payload=payload.input,
        policy=payload.policy.to_runtime_policy(),
        idempotency_key=_resolve_idempotency_key(request, payload),
        trace_id=_resolve_trace_id(payload, auth),
        allow_legacy_callback_url=False,
    )


def _is_site_knowledge_payload(payload: RuntimePayload) -> bool:
    return payload.ability_name in SITE_KNOWLEDGE_ABILITIES


def _resolve_ability_family(payload: RuntimePayload) -> str:
    if _is_site_knowledge_payload(payload):
        return SITE_KNOWLEDGE_ABILITY_FAMILY
    return payload.ability_family


def _resolve_execution_kind(payload: RuntimePayload) -> str:
    if _is_site_knowledge_payload(payload) and not payload.execution_kind:
        return SITE_KNOWLEDGE_EXECUTION_KIND
    return payload.execution_kind


def _resolve_profile_id(payload: RuntimePayload) -> str:
    if _is_site_knowledge_payload(payload) and not payload.profile_id:
        return SITE_KNOWLEDGE_PROFILE_ID
    return payload.profile_id


def _resolve_data_classification(payload: RuntimePayload) -> str:
    if _is_site_knowledge_payload(payload):
        return SITE_KNOWLEDGE_DATA_CLASSIFICATION
    return payload.data_classification


def _resolve_task_backend(payload: RuntimePayload) -> dict[str, Any]:
    task_backend = payload.task_backend or {}
    if (
        payload.ability_name == SITE_KNOWLEDGE_SYNC_ABILITY
        and payload.execution_pattern == "whole_run_offload"
        and not task_backend
    ):
        return {
            "enabled": True,
            "mode": "queue",
            "callback_mode": "polling_preferred",
            "polling_interval_sec": 5,
        }
    return task_backend


def _resolve_idempotency_key(request: Request, payload: RuntimePayload) -> str:
    return (
        request.headers.get("Idempotency-Key")
        or payload.idempotency_key
        or f"auto_{uuid4().hex}"
    )


def _resolve_trace_id(
    payload: RuntimePayload,
    auth: RequestAuthContext,
) -> str:
    if payload.trace_id:
        return payload.trace_id

    return auth.trace_id or uuid4().hex


def _normalize_runtime_execution_pattern(value: str) -> str:
    if value == "whole_run_offload":
        return "whole_run_offload"
    if value not in ("inline", "whole_run_offload"):
        raise RuntimeUnsupportedExecutionPatternError(value)
    return "inline"


def _public_runtime_execution_pattern(value: str) -> str:
    if value == "whole_run_offload":
        return "whole_run_offload"
    return "inline"


def _runtime_error_response(
    *,
    status_code: int,
    error_code: str,
    message: str,
    trace_id: str,
    data: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=build_envelope(
            status="error",
            error_code=error_code,
            message=message,
            data=data or {},
            trace_id=trace_id,
            revision="m2",
        ),
    )


@router.post("/resolve")
async def resolve_runtime(
    request: Request,
    payload: RuntimePayload,
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="runtime:resolve",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_runtime_service(request)
    if payload.site_id and payload.site_id != auth.site_id:
        return _runtime_error_response(
            status_code=400,
            error_code="auth.site_mismatch",
            message="payload site_id does not match authenticated site",
            trace_id=auth.trace_id,
        )

    runtime_request: RuntimeRequest | None = None
    try:
        runtime_request = _build_runtime_request(request, payload, auth)
        resolved = await run_in_threadpool(service.resolve, runtime_request)
    except RoutingError as error:
        return _runtime_error_response(
            status_code=400,
            error_code=error.error_code,
            message=error.message,
            trace_id=(runtime_request.trace_id if runtime_request else auth.trace_id) or "",
            data={"profile_id": payload.profile_id},
        )
    except RuntimeErrorBase as error:
        return _runtime_error_response(
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
            trace_id=(runtime_request.trace_id if runtime_request else auth.trace_id) or "",
            data={"profile_id": payload.profile_id},
        )

    return JSONResponse(
        content=build_envelope(
            status="ok",
            message="runtime resolved",
            data={
                **resolved,
                "execution_context": {
                    "skill_id": runtime_request.skill_id,
                    "workflow_id": runtime_request.workflow_id,
                    "contract_version": runtime_request.contract_version,
                    "ability_family": runtime_request.ability_family,
                    "execution_tier": runtime_request.execution_tier,
                    "execution_pattern": _public_runtime_execution_pattern(
                        runtime_request.execution_pattern
                    ),
                    "data_classification": runtime_request.data_classification,
                    "storage_mode": runtime_request.storage_mode,
                },
            },
            trace_id=runtime_request.trace_id or "",
            revision=str(resolved["revision"]),
        ),
    )


@router.post("/execute")
async def execute_runtime(
    request: Request,
    payload: RuntimePayload,
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=True,
        required_scope="runtime:execute",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_runtime_service(request)
    if payload.site_id and payload.site_id != auth.site_id:
        return _runtime_error_response(
            status_code=400,
            error_code="auth.site_mismatch",
            message="payload site_id does not match authenticated site",
            trace_id=auth.trace_id,
        )

    runtime_request: RuntimeRequest | None = None
    try:
        runtime_request = _build_runtime_request(request, payload, auth)
        result = await run_in_threadpool(service.execute, runtime_request)
    except RoutingError as error:
        return _runtime_error_response(
            status_code=400,
            error_code=error.error_code,
            message=error.message,
            trace_id=(runtime_request.trace_id if runtime_request else auth.trace_id) or "",
            data={"profile_id": payload.profile_id},
        )
    except RuntimeErrorBase as error:
        return _runtime_error_response(
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
            trace_id=(runtime_request.trace_id if runtime_request else auth.trace_id) or "",
            data={"profile_id": payload.profile_id},
        )

    success_statuses = {"queued", "running", "succeeded"}
    status = "ok" if result.status in success_statuses else "error"
    error_code = "" if result.status in success_statuses else result.error_code
    return JSONResponse(
        content=build_envelope(
            status=status,
            error_code=error_code,
            message=(
                "runtime queued"
                if result.status == "queued"
                else (
                    "runtime executing"
                    if result.status == "running"
                    else (
                        "runtime executed"
                        if result.status == "succeeded"
                        else result.error_message or "runtime execution failed"
                    )
                )
            ),
            data={
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
                    "execution_pattern": _public_runtime_execution_pattern(
                        result.execution_context.execution_pattern
                    ),
                    "data_classification": result.execution_context.data_classification,
                    "storage_mode": result.execution_context.storage_mode,
                },
                "task_backend": result.task_backend,
                "run_lifecycle": result.run_lifecycle,
                "result": result.result,
            },
            trace_id=result.trace_id,
            revision="m2",
        ),
    )
