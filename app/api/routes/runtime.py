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
from app.core.security import PUBLIC_RUNTIME_MAX_BODY_BYTES, RequestAuthContext
from app.domain.audio_generation.contracts import (
    AUDIO_GENERATION_ABILITIES,
    AUDIO_GENERATION_ABILITY_FAMILY,
    AUDIO_GENERATION_DATA_CLASSIFICATION,
    AUDIO_GENERATION_EXECUTION_KIND,
    AUDIO_GENERATION_PROFILE_ID,
)
from app.domain.cloud_batch_runtime.contracts import (
    CLOUD_BATCH_RUNTIME_ABILITIES,
    CLOUD_BATCH_RUNTIME_ABILITY_FAMILY,
    CLOUD_BATCH_RUNTIME_DATA_CLASSIFICATION,
    CLOUD_BATCH_RUNTIME_EXECUTION_KIND,
    CLOUD_BATCH_RUNTIME_PROFILE_ID,
)
from app.domain.hosted_model_defaults import FREE_GPT55_TEXT_PROFILE_ID
from app.domain.image_context_evidence.contracts import (
    IMAGE_CONTEXT_EVIDENCE_ABILITIES,
    IMAGE_CONTEXT_EVIDENCE_ABILITY_FAMILY,
    IMAGE_CONTEXT_EVIDENCE_DATA_CLASSIFICATION,
    IMAGE_CONTEXT_EVIDENCE_EXECUTION_KIND,
    IMAGE_CONTEXT_EVIDENCE_PROFILE_ID,
)
from app.domain.image_generation.contracts import (
    IMAGE_GENERATION_ABILITIES,
    IMAGE_GENERATION_ABILITY_FAMILY,
    IMAGE_GENERATION_DATA_CLASSIFICATION,
    IMAGE_GENERATION_EXECUTION_KIND,
    IMAGE_GENERATION_PROFILE_ID,
)
from app.domain.image_sources.contracts import (
    IMAGE_SOURCE_ABILITIES,
    IMAGE_SOURCE_ABILITY_FAMILY,
    IMAGE_SOURCE_DATA_CLASSIFICATION,
    IMAGE_SOURCE_EXECUTION_KIND,
    IMAGE_SOURCE_PROFILE_ID,
)
from app.domain.media_batch_plans.contracts import (
    MEDIA_BATCH_PLAN_ABILITIES,
    MEDIA_BATCH_PLAN_ABILITY_FAMILY,
    MEDIA_BATCH_PLAN_DATA_CLASSIFICATION,
    MEDIA_BATCH_PLAN_EXECUTION_KIND,
    MEDIA_BATCH_PLAN_PROFILE_ID,
)
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
from app.domain.site_ops_analysis.contracts import (
    SITE_OPS_ANALYSIS_ABILITIES,
    SITE_OPS_ANALYSIS_ABILITY_FAMILY,
    SITE_OPS_ANALYSIS_DATA_CLASSIFICATION,
    SITE_OPS_ANALYSIS_EXECUTION_KIND,
    SITE_OPS_ANALYSIS_PROFILE_ID,
)
from app.domain.web_search.contracts import (
    WEB_SEARCH_ABILITIES,
    WEB_SEARCH_ABILITY_FAMILY,
    WEB_SEARCH_DATA_CLASSIFICATION,
    WEB_SEARCH_EXECUTION_KIND,
    WEB_SEARCH_PROFILE_ID,
)
from app.domain.wordpress_ai_connector.contracts import (
    WP_AI_CONNECTOR_ABILITIES,
    WP_AI_CONNECTOR_ABILITY_FAMILY,
    WP_AI_CONNECTOR_DATA_CLASSIFICATION,
    WP_AI_CONNECTOR_EXECUTION_KIND,
)
from app.domain.wordpress_ai_connector.routing_profiles import (
    WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID,
    resolve_wordpress_ai_connector_profile_id,
)

router = APIRouter(prefix="/v1/runtime", tags=["runtime"])

MAX_RUNTIME_JSON_DEPTH = 8
MAX_RUNTIME_DICT_KEYS = 100
MAX_RUNTIME_LIST_ITEMS = 200
# Keep per-field shape validation above the total request limit so public
# auth consistently owns 413 payload-size responses.
MAX_RUNTIME_STRING_CHARS = PUBLIC_RUNTIME_MAX_BODY_BYTES * 2
MAX_RUNTIME_DICT_KEY_CHARS = 191


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
    site_id: str | None = Field(default=None, max_length=191)
    ability_name: str = Field(min_length=1, max_length=191)
    ability_family: Literal[
        "text",
        "vision",
        "workflow",
        "automation",
        "mcp",
        "openclaw",
        "knowledge",
        "audio",
    ] = "text"
    canonical_run_id: str | None = Field(default=None, max_length=191)
    skill_id: str | None = Field(default=None, max_length=191)
    workflow_id: str | None = Field(default=None, max_length=191)
    contract_version: str = Field(default="v1", min_length=1, max_length=64)
    channel: str = Field(default="openapi", max_length=64)
    execution_kind: str = Field(default="", max_length=64)
    execution_tier: Literal["cloud"] = "cloud"
    execution_pattern: Literal["inline", "step_offload", "whole_run_offload"] = "inline"
    data_classification: Literal[
        "public",
        "internal",
        "pii",
        "secret",
        "public_site_content",
        "public_reference_media",
        "public_site_media_metadata",
        "public_site_aggregate",
    ] = "internal"
    storage_mode: Literal["no_store", "result_only", "full_store_with_ttl"] = "result_only"
    timeout_seconds: int = 0
    retry_max: int = 0
    retention_ttl: int = 0
    callback_url: str = Field(default="", max_length=2048)
    task_backend: dict[str, Any] = Field(default_factory=dict)
    profile_id: str = Field(default="", max_length=191)
    idempotency_key: str | None = Field(default=None, max_length=128)
    trace_id: str | None = Field(default=None, max_length=64)
    input: dict[str, Any] = Field(default_factory=dict)
    policy: RuntimePolicyPayload = Field(default_factory=RuntimePolicyPayload)

    @model_validator(mode="after")
    def validate_runtime_payload_bounds(self) -> RuntimePayload:
        if (
            self.execution_pattern == "step_offload"
            and self.ability_name not in IMAGE_SOURCE_ABILITIES
        ):
            raise ValueError(
                "execution_pattern=step_offload is only supported for managed "
                "image-source runtime abilities"
            )
        _validate_runtime_json_shape(self.input, field_name="input")
        _validate_runtime_json_shape(self.task_backend, field_name="task_backend")
        return self


def _validate_runtime_json_shape(value: Any, *, field_name: str, depth: int = 0) -> None:
    if depth >= MAX_RUNTIME_JSON_DEPTH:
        raise ValueError(f"{field_name} exceeds the accepted nesting depth")
    if isinstance(value, dict):
        if len(value) > MAX_RUNTIME_DICT_KEYS:
            raise ValueError(f"{field_name} contains too many keys")
        for key, item in value.items():
            if len(str(key)) > MAX_RUNTIME_DICT_KEY_CHARS:
                raise ValueError(f"{field_name} contains an oversized key")
            _validate_runtime_json_shape(item, field_name=field_name, depth=depth + 1)
        return
    if isinstance(value, list):
        if len(value) > MAX_RUNTIME_LIST_ITEMS:
            raise ValueError(f"{field_name} contains too many items")
        for item in value:
            _validate_runtime_json_shape(item, field_name=field_name, depth=depth + 1)
        return
    if isinstance(value, str) and len(value) > MAX_RUNTIME_STRING_CHARS:
        raise ValueError(f"{field_name} contains an oversized string")


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
        execution_pattern=_normalize_runtime_execution_pattern(
            payload.execution_pattern,
            ability_name=payload.ability_name,
        ),
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


def _is_web_search_payload(payload: RuntimePayload) -> bool:
    return payload.ability_name in WEB_SEARCH_ABILITIES


def _is_wordpress_ai_connector_payload(payload: RuntimePayload) -> bool:
    return payload.ability_name in WP_AI_CONNECTOR_ABILITIES


def _is_wordpress_ai_image_generation_payload(payload: RuntimePayload) -> bool:
    input_payload = payload.input if isinstance(payload.input, dict) else {}
    return (
        _is_image_generation_payload(payload)
        and (
            payload.channel == "wordpress_ai_connector"
            or str(input_payload.get("source_surface") or "") == "wordpress_ai_connector"
        )
        and str(input_payload.get("connector_id") or "") == "npcink-cloud"
        and str(input_payload.get("task") or "") == "image_generation"
    )


def _is_image_source_payload(payload: RuntimePayload) -> bool:
    return payload.ability_name in IMAGE_SOURCE_ABILITIES


def _is_zh_cn_runtime_payload(payload: RuntimePayload) -> bool:
    input_payload = payload.input if isinstance(payload.input, dict) else {}
    visual_context = input_payload.get("visual_context")
    if not isinstance(visual_context, dict):
        visual_context = {}
    locale = str(input_payload.get("locale") or visual_context.get("locale") or "")
    return locale.strip().replace("-", "_").lower() == "zh_cn"


def _runtime_execute_success_message(payload: RuntimePayload, result_status: str) -> str:
    if _is_image_source_payload(payload) and _is_zh_cn_runtime_payload(payload):
        if result_status == "queued":
            return "运行已排队"
        if result_status == "running":
            return "运行中"
        if result_status == "succeeded":
            return "运行完成"
    return (
        "runtime queued"
        if result_status == "queued"
        else ("runtime executing" if result_status == "running" else "runtime executed")
    )


def _is_image_generation_payload(payload: RuntimePayload) -> bool:
    return payload.ability_name in IMAGE_GENERATION_ABILITIES


def _is_audio_generation_payload(payload: RuntimePayload) -> bool:
    return payload.ability_name in AUDIO_GENERATION_ABILITIES


def _is_image_context_evidence_payload(payload: RuntimePayload) -> bool:
    return payload.ability_name in IMAGE_CONTEXT_EVIDENCE_ABILITIES


def _is_media_batch_plan_payload(payload: RuntimePayload) -> bool:
    return payload.ability_name in MEDIA_BATCH_PLAN_ABILITIES


def _is_cloud_batch_runtime_payload(payload: RuntimePayload) -> bool:
    return payload.ability_name in CLOUD_BATCH_RUNTIME_ABILITIES


def _is_site_ops_analysis_payload(payload: RuntimePayload) -> bool:
    return payload.ability_name in SITE_OPS_ANALYSIS_ABILITIES


def _resolve_ability_family(payload: RuntimePayload) -> str:
    if _is_site_ops_analysis_payload(payload):
        return SITE_OPS_ANALYSIS_ABILITY_FAMILY
    if _is_cloud_batch_runtime_payload(payload):
        return CLOUD_BATCH_RUNTIME_ABILITY_FAMILY
    if _is_media_batch_plan_payload(payload):
        return MEDIA_BATCH_PLAN_ABILITY_FAMILY
    if _is_image_context_evidence_payload(payload):
        return IMAGE_CONTEXT_EVIDENCE_ABILITY_FAMILY
    if _is_audio_generation_payload(payload):
        return AUDIO_GENERATION_ABILITY_FAMILY
    if _is_image_generation_payload(payload):
        return IMAGE_GENERATION_ABILITY_FAMILY
    if _is_image_source_payload(payload):
        return IMAGE_SOURCE_ABILITY_FAMILY
    if _is_site_knowledge_payload(payload):
        return SITE_KNOWLEDGE_ABILITY_FAMILY
    if _is_web_search_payload(payload):
        return WEB_SEARCH_ABILITY_FAMILY
    if _is_wordpress_ai_connector_payload(payload):
        return WP_AI_CONNECTOR_ABILITY_FAMILY
    return payload.ability_family


def _resolve_execution_kind(payload: RuntimePayload) -> str:
    if _is_site_ops_analysis_payload(payload) and not payload.execution_kind:
        return SITE_OPS_ANALYSIS_EXECUTION_KIND
    if _is_cloud_batch_runtime_payload(payload) and not payload.execution_kind:
        return CLOUD_BATCH_RUNTIME_EXECUTION_KIND
    if _is_media_batch_plan_payload(payload) and not payload.execution_kind:
        return MEDIA_BATCH_PLAN_EXECUTION_KIND
    if _is_image_context_evidence_payload(payload) and not payload.execution_kind:
        return IMAGE_CONTEXT_EVIDENCE_EXECUTION_KIND
    if _is_audio_generation_payload(payload) and not payload.execution_kind:
        return AUDIO_GENERATION_EXECUTION_KIND
    if _is_image_generation_payload(payload) and not payload.execution_kind:
        return IMAGE_GENERATION_EXECUTION_KIND
    if _is_image_source_payload(payload) and not payload.execution_kind:
        return IMAGE_SOURCE_EXECUTION_KIND
    if _is_site_knowledge_payload(payload) and not payload.execution_kind:
        return SITE_KNOWLEDGE_EXECUTION_KIND
    if _is_web_search_payload(payload) and not payload.execution_kind:
        return WEB_SEARCH_EXECUTION_KIND
    if _is_wordpress_ai_connector_payload(payload):
        return WP_AI_CONNECTOR_EXECUTION_KIND
    return payload.execution_kind


def _resolve_profile_id(payload: RuntimePayload) -> str:
    if _is_site_ops_analysis_payload(payload) and not payload.profile_id:
        return SITE_OPS_ANALYSIS_PROFILE_ID
    if _is_cloud_batch_runtime_payload(payload) and not payload.profile_id:
        return CLOUD_BATCH_RUNTIME_PROFILE_ID
    if _is_media_batch_plan_payload(payload) and not payload.profile_id:
        return MEDIA_BATCH_PLAN_PROFILE_ID
    if _is_image_context_evidence_payload(payload) and not payload.profile_id:
        return IMAGE_CONTEXT_EVIDENCE_PROFILE_ID
    if _is_audio_generation_payload(payload) and not payload.profile_id:
        return AUDIO_GENERATION_PROFILE_ID
    if _is_wordpress_ai_image_generation_payload(payload) and not payload.profile_id:
        return WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID
    if _is_image_generation_payload(payload) and not payload.profile_id:
        return IMAGE_GENERATION_PROFILE_ID
    if _is_image_source_payload(payload) and not payload.profile_id:
        return IMAGE_SOURCE_PROFILE_ID
    if _is_site_knowledge_payload(payload) and not payload.profile_id:
        return SITE_KNOWLEDGE_PROFILE_ID
    if _is_web_search_payload(payload) and not payload.profile_id:
        return WEB_SEARCH_PROFILE_ID
    if _is_wordpress_ai_connector_payload(payload):
        input_payload = payload.input if isinstance(payload.input, dict) else {}
        return resolve_wordpress_ai_connector_profile_id(input_payload)
    if not payload.profile_id and payload.ability_family in {
        "text",
        "openclaw",
        "workflow",
        "automation",
        "mcp",
    }:
        return FREE_GPT55_TEXT_PROFILE_ID
    return payload.profile_id


def _resolve_data_classification(payload: RuntimePayload) -> str:
    if _is_site_ops_analysis_payload(payload):
        return SITE_OPS_ANALYSIS_DATA_CLASSIFICATION
    if _is_cloud_batch_runtime_payload(payload):
        return CLOUD_BATCH_RUNTIME_DATA_CLASSIFICATION
    if _is_media_batch_plan_payload(payload):
        return MEDIA_BATCH_PLAN_DATA_CLASSIFICATION
    if _is_image_context_evidence_payload(payload):
        return IMAGE_CONTEXT_EVIDENCE_DATA_CLASSIFICATION
    if _is_audio_generation_payload(payload):
        return _resolve_feature_data_classification(payload, AUDIO_GENERATION_DATA_CLASSIFICATION)
    if _is_image_generation_payload(payload):
        return _resolve_feature_data_classification(payload, IMAGE_GENERATION_DATA_CLASSIFICATION)
    if _is_image_source_payload(payload):
        return _resolve_feature_data_classification(payload, IMAGE_SOURCE_DATA_CLASSIFICATION)
    if _is_site_knowledge_payload(payload):
        return SITE_KNOWLEDGE_DATA_CLASSIFICATION
    if _is_web_search_payload(payload):
        return WEB_SEARCH_DATA_CLASSIFICATION
    if _is_wordpress_ai_connector_payload(payload):
        return WP_AI_CONNECTOR_DATA_CLASSIFICATION
    return payload.data_classification


def _resolve_feature_data_classification(
    payload: RuntimePayload, default_classification: str
) -> str:
    requested = str(payload.data_classification or "").strip().lower()
    if requested in {"pii", "secret"}:
        return requested
    return default_classification


def _resolve_task_backend(payload: RuntimePayload) -> dict[str, Any]:
    task_backend = payload.task_backend or {}
    if (
        _is_cloud_batch_runtime_payload(payload)
        and payload.execution_pattern == "whole_run_offload"
        and not task_backend
    ):
        return {
            "enabled": True,
            "mode": "queue",
            "callback_mode": "polling_preferred",
            "polling_interval_sec": 10,
        }
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
        request.headers.get("Idempotency-Key") or payload.idempotency_key or f"auto_{uuid4().hex}"
    )


def _resolve_trace_id(
    payload: RuntimePayload,
    auth: RequestAuthContext,
) -> str:
    if payload.trace_id:
        return payload.trace_id

    return auth.trace_id or uuid4().hex


def _normalize_runtime_execution_pattern(value: str, *, ability_name: str = "") -> str:
    if value == "whole_run_offload":
        return "whole_run_offload"
    if value == "step_offload" and ability_name in IMAGE_SOURCE_ABILITIES:
        return "step_offload"
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
                _runtime_execute_success_message(payload, result.status)
                if result.status in success_statuses
                else result.error_message or "runtime execution failed"
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
