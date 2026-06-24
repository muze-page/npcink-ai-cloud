from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.adapters.providers.base import ProviderExecutionError
from app.adapters.providers.registry import resolve_live_provider_adapters
from app.adapters.repositories.catalog_repository import CatalogRepository
from app.api.auth import authorize_internal_request, get_cloud_services
from app.api.envelope import build_envelope
from app.core.db import get_session
from app.core.security import extract_trace_id
from app.domain.advisor.service import InternalAIAdvisorService
from app.domain.agent_feedback.service import AgentFeedbackService
from app.domain.agent_workflow_metadata import (
    MEDIA_DERIVATIVE_WORKFLOW_ID,
    WEB_SEARCH_EVIDENCE_WORKFLOW_ID,
    get_agent_workflow_metadata_projection,
    get_workflow_metadata,
)
from app.domain.audio_generation.admin_config import (
    AudioProviderAdminConfigError,
    AudioProviderAdminConfigService,
)
from app.domain.audio_generation.workbench import (
    AudioWorkbenchError,
    AudioWorkbenchService,
)
from app.domain.catalog.service import CatalogService
from app.domain.commercial.errors import CommercialServiceError
from app.domain.commercial.service import CommercialService, ServiceAuditContext
from app.domain.hosted_model_defaults import FREE_GPT55_MODEL_ID
from app.domain.image_sources.admin_config import ImageSourceAdminConfigService
from app.domain.image_sources.metrics import ImageSourceMetricsService
from app.domain.media_derivatives.metrics import MediaDerivativeObservabilityService
from app.domain.observability.plugin_events import PluginObservabilityService
from app.domain.observability.service import ObservabilityService
from app.domain.provider_resources import (
    AIResourceProfilePreferenceError,
    AIResourceProfilePreferenceService,
    build_admin_ai_resource_projection,
)
from app.domain.runtime.models import (
    RUNTIME_BACKLOG_SCOPE_KIND_PATTERN,
    RUNTIME_DIAGNOSTIC_ISSUE_KIND_PATTERN,
)
from app.domain.runtime.service import RuntimeRunNotFoundError, RuntimeService
from app.domain.site_knowledge.metrics import SiteKnowledgeObservabilityService
from app.domain.usage.rollup import UsageRollupService
from app.domain.web_search.admin_config import WebSearchAdminConfigService
from app.domain.wordpress_ai_connector.routing_profiles import (
    WP_AI_CONNECTOR_PROFILE_SPECS,
    WP_AI_CONNECTOR_PROFILE_SPECS_BY_ID,
)
from app.workers.ops_cadence import build_cadence_summary

router = APIRouter(prefix="/internal/service", tags=["service"])


def _dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dict_list(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _coerce_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


class AccountPayload(BaseModel):
    account_id: str
    name: str
    status: str = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)
    bind_default_free: bool = False


class AccountStatusPayload(BaseModel):
    reason: str = ""


class SiteProvisionPayload(BaseModel):
    site_id: str
    account_id: str
    name: str = ""
    status: str = "provisioning"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SiteStatusPayload(BaseModel):
    reason: str = ""


class SiteAdminAccessPayload(BaseModel):
    email: str
    status: str = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SiteKeyPayload(BaseModel):
    key_id: str | None = None
    secret: str | None = None
    scopes: list[str] = Field(default_factory=list)
    label: str = ""
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KeyExpirePayload(BaseModel):
    expires_at: datetime


class PlanPayload(BaseModel):
    plan_id: str
    name: str
    status: str = "active"
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanVersionPayload(BaseModel):
    plan_version_id: str
    version_label: str
    status: str = "published"
    currency: str = "USD"
    entitlements: dict[str, Any] = Field(default_factory=dict)
    budgets: dict[str, Any] = Field(default_factory=dict)
    concurrency: dict[str, Any] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubscriptionPayload(BaseModel):
    subscription_id: str | None = None
    account_id: str
    plan_id: str
    plan_version_id: str
    status: str = "active"
    current_period_start_at: datetime | None = None
    current_period_end_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubscriptionTopUpPayload(BaseModel):
    target_period_start_at: datetime | None = None
    target_period_end_at: datetime | None = None
    ai_credits_increment: float = 0.0
    runs_increment: float = 0.0
    tokens_increment: float = 0.0
    cost_increment: float = 0.0
    reason: str = ""
    note: str = ""


class AccountCreditAdjustmentPayload(BaseModel):
    event_type: str = "adjustment"
    credit_delta: float
    reason: str = ""
    note: str = ""


class PaymentOrderPayload(BaseModel):
    account_id: str
    plan_id: str
    plan_version_id: str
    amount: float
    currency: str = "CNY"
    provider: str = "alipay"
    subject: str = ""
    site_id: str = ""
    refund_window_days: int = 14
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreditPackPaymentOrderPayload(BaseModel):
    account_id: str
    pack_id: str
    provider: str = "alipay"
    site_id: str = ""


class PaymentSucceededPayload(BaseModel):
    provider_trade_no: str = ""
    provider_event_id: str = ""
    paid_at: datetime | None = None
    amount: float | None = None
    raw_event: dict[str, Any] = Field(default_factory=dict)


class PaymentRefundPayload(BaseModel):
    amount: float | None = None
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class PaymentRefundSucceededPayload(BaseModel):
    provider_refund_no: str = ""
    provider_event_id: str = ""
    succeeded_at: datetime | None = None
    raw_event: dict[str, Any] = Field(default_factory=dict)


class PluginAttentionStatePayload(BaseModel):
    attention_key: str = Field(min_length=16, max_length=128)
    attention_code: str = Field(default="", max_length=128)
    action: str = Field(default="acknowledge", max_length=32)
    site_id: str = Field(default="", max_length=191)
    plugin_slug: str = Field(default="", max_length=64)
    event_kind: str = Field(default="", max_length=96)
    error_code: str = Field(default="", max_length=128)
    mute_hours: int = Field(default=24, ge=1, le=720)
    note: str = Field(default="", max_length=512)


class WebSearchProviderSettingsPayload(BaseModel):
    provider_mode: str = Field(default="disabled", max_length=32)
    providers: dict[str, Any] = Field(default_factory=dict)


class ImageSourceProviderSettingsPayload(BaseModel):
    provider_mode: str = Field(default="disabled", max_length=32)
    providers: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)


class AudioProviderSettingsPayload(BaseModel):
    provider_mode: str = Field(default="disabled", max_length=32)
    providers: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)


class AudioWorkbenchCreatePayload(BaseModel):
    intent: str = Field(default="article_narration", max_length=64)
    site_id: str = Field(default="site_smoke", max_length=191)
    title: str = Field(default="", max_length=240)
    body: str = Field(min_length=1, max_length=25000)
    format: str = Field(default="mp3", max_length=16)


class AIResourceProfilePreferencePayload(BaseModel):
    audio_summary_text_profile_id: str = Field(default="text.ai", max_length=64)
    audio_narration_profile_id: str = Field(
        default="audio.narration.default",
        max_length=64,
    )
    audio_summary_audio_profile_id: str = Field(
        default="audio.narration.default",
        max_length=64,
    )


class WordPressAIRoutingProfilePayload(BaseModel):
    profile_id: str = Field(max_length=64)
    candidate_instance_ids: list[str] = Field(default_factory=list)
    timeout_ms: int = Field(default=30000, ge=1000, le=60000)
    allow_fallback: bool = True
    max_retries: int = Field(default=0, ge=0, le=1)
    note: str = Field(default="", max_length=512)


class WordPressAIRoutingSettingsPayload(BaseModel):
    profiles: list[WordPressAIRoutingProfilePayload] = Field(default_factory=list)


class OpsSummaryDisclosureReviewPayload(BaseModel):
    cache_key: str = Field(min_length=16, max_length=128)
    review_status: str = Field(max_length=32)
    actor_ref: str = Field(default="internal", max_length=191)
    note: str = Field(default="", max_length=512)


def _get_commercial_service(request: Request) -> CommercialService:
    services = get_cloud_services(request)
    return CommercialService(services.settings.database_url, settings=services.settings)


def _get_catalog_service(request: Request) -> CatalogService:
    services = get_cloud_services(request)
    return CatalogService(
        services.settings.database_url,
        providers=resolve_live_provider_adapters(
            services.settings,
            base_providers=services.providers,
            include_enabled_connections=True,
        ),
    )


def _get_advisor_service(request: Request) -> InternalAIAdvisorService:
    services = get_cloud_services(request)
    return InternalAIAdvisorService(
        services.settings.database_url,
        providers=services.providers,
        allowed_summarizer_provider_ids=_csv_set(
            services.settings.internal_ops_summarizer_provider_allowlist
        ),
    )


def _csv_set(value: str) -> set[str]:
    return {item.strip() for item in str(value or "").split(",") if item.strip()}


def _advisor_range_to_hours(value: str) -> int:
    normalized = str(value or "").strip().lower()
    if normalized.endswith("h"):
        try:
            return min(168, max(1, int(normalized[:-1])))
        except ValueError:
            return 24
    if normalized.endswith("d"):
        try:
            return min(168, max(1, int(normalized[:-1]) * 24))
        except ValueError:
            return 24
    return 24


def _service_error_response(
    error: CommercialServiceError,
    *,
    request: Request | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=build_envelope(
            status="error",
            error_code=error.error_code,
            message=error.message,
            trace_id=(
                extract_trace_id(request.headers.get("traceparent", ""))
                if request is not None
                else ""
            ),
            revision="m6",
        ),
    )


def _build_audit_context(request: Request) -> ServiceAuditContext:
    return ServiceAuditContext(
        trace_id=extract_trace_id(request.headers.get("traceparent", "")),
        idempotency_key=request.headers.get("Idempotency-Key", "").strip(),
        method=request.method,
        path=request.url.path,
        actor_kind="internal_token",
        actor_ref="internal",
    )


def _build_audit_payload(payload: BaseModel | None = None) -> dict[str, Any]:
    if payload is None:
        return {}
    return payload.model_dump(mode="json")


def _build_audit_filters(
    *,
    account_id: str | None = None,
    site_id: str | None = None,
    event_kind: str | None = None,
    outcome: str | None = None,
) -> dict[str, str]:
    filters: dict[str, str] = {}
    if account_id:
        filters["account_id"] = str(account_id)
    if site_id:
        filters["site_id"] = str(site_id)
    if event_kind:
        filters["event_kind"] = str(event_kind)
    if outcome:
        filters["outcome"] = str(outcome)
    return filters


def _build_operator_receipt(
    *,
    event_kind: str,
    scope_kind: str,
    scope_id: str,
    outcome: str,
    effective_summary: str,
    audit_event: dict[str, Any] | None = None,
    account_id: str | None = None,
    site_id: str | None = None,
) -> dict[str, Any]:
    resolved_account_id = str((audit_event or {}).get("account_id") or account_id or "").strip()
    resolved_site_id = str((audit_event or {}).get("site_id") or site_id or "").strip()
    receipt: dict[str, Any] = {
        "event_kind": event_kind,
        "scope_kind": scope_kind,
        "scope_id": scope_id,
        "outcome": outcome,
        "effective_summary": effective_summary,
        "audit_filters": _build_audit_filters(
            account_id=resolved_account_id,
            site_id=resolved_site_id,
            event_kind=event_kind,
            outcome=outcome,
        ),
    }
    audit_event_id = int((audit_event or {}).get("event_id") or 0)
    if audit_event_id > 0:
        receipt["audit_event_id"] = audit_event_id
    return receipt


def _merge_receipt(data: Any, receipt: dict[str, Any]) -> Any:
    if isinstance(data, dict):
        return {**data, "receipt": receipt}
    return {"value": data, "receipt": receipt}


def _serialize_wordpress_ai_instance(instance: Any, model: Any) -> dict[str, Any]:
    return {
        "instance_id": str(instance.instance_id or ""),
        "provider_id": str(instance.provider_id or ""),
        "model_id": str(instance.model_id or ""),
        "endpoint_variant": str(instance.endpoint_variant or ""),
        "region": str(instance.region or ""),
        "health_status": str(instance.health_status or "unknown"),
        "weight": int(instance.weight or 0),
        "capability_tags": list(instance.capability_tags or []),
        "model_status": str(model.status or ""),
        "model_feature": str(model.feature or ""),
        "price_input": model.price_input,
        "price_output": model.price_output,
    }


def _build_wordpress_ai_routing_projection(database_url: str) -> dict[str, Any]:
    with get_session(database_url) as session:
        repository = CatalogRepository(session)
        instances = repository.list_instances_for_provider()
        models = repository.list_models_by_ids([instance.model_id for instance in instances])
        models_by_id = {model.model_id: model for model in models}
        instances_by_id = {instance.instance_id: instance for instance in instances}

        available_instances = [
            _serialize_wordpress_ai_instance(instance, models_by_id[instance.model_id])
            for instance in instances
            if instance.model_id in models_by_id
            and models_by_id[instance.model_id].feature == "text"
            and models_by_id[instance.model_id].status == "available"
        ]

        profiles: list[dict[str, Any]] = []
        for spec in WP_AI_CONNECTOR_PROFILE_SPECS:
            profile = repository.get_routing_profile(spec.profile_id)
            binding = repository.get_routing_binding(spec.profile_id)
            policy = profile.default_policy_json if profile is not None else {}
            if not isinstance(policy, dict):
                policy = {}
            selection_policy = binding.selection_policy_json if binding is not None else {}
            if not isinstance(selection_policy, dict):
                selection_policy = {}
            candidate_instance_ids = (
                list(binding.candidate_instance_ids or []) if binding is not None else []
            )
            candidate_items = []
            for instance_id in candidate_instance_ids:
                if instance_id not in instances_by_id:
                    continue
                instance = instances_by_id[instance_id]
                model = models_by_id.get(instance.model_id)
                if model is None:
                    continue
                candidate_items.append(_serialize_wordpress_ai_instance(instance, model))

            profiles.append(
                {
                    "profile_id": spec.profile_id,
                    "group_id": spec.group_id,
                    "label": spec.label,
                    "description": spec.description,
                    "tasks": list(spec.tasks),
                    "execution_kind": profile.execution_kind if profile is not None else "text",
                    "candidate_instance_ids": candidate_instance_ids,
                    "candidates": candidate_items,
                    "timeout_ms": int(policy.get("timeout_ms") or spec.timeout_ms),
                    "allow_fallback": bool(policy.get("allow_fallback", spec.allow_fallback)),
                    "max_retries": int(policy.get("max_retries") or spec.max_retries),
                    "revision": str(binding.revision if binding is not None else ""),
                    "updated_at": (
                        binding.updated_at.isoformat()
                        if binding is not None and binding.updated_at is not None
                        else ""
                    ),
                    "selection_policy": selection_policy,
                    "status": "configured" if candidate_instance_ids else "needs_candidates",
                }
            )

    return {
        "surface": "wordpress_ai_connector_routing",
        "owner": "cloud_runtime",
        "local_control_plane": "wordpress_plugin",
        "customer_model_selection": False,
        "direct_wordpress_write": False,
        "prompt_or_preset_editor": False,
        "available_text_instances": available_instances,
        "profiles": profiles,
        "boundary": {
            "public_runtime_accepts_raw_model_instance": False,
            "results_write_posture": "suggestion_only",
            "admin_surface": "platform_admin_only",
        },
    }


def _validate_wordpress_ai_routing_payload(
    database_url: str,
    payload: WordPressAIRoutingSettingsPayload,
) -> tuple[list[WordPressAIRoutingProfilePayload], str]:
    if not payload.profiles:
        return [], "at least one WordPress AI routing profile is required"

    known_profile_ids = set(WP_AI_CONNECTOR_PROFILE_SPECS_BY_ID)
    seen_profile_ids: set[str] = set()
    with get_session(database_url) as session:
        repository = CatalogRepository(session)
        for profile_payload in payload.profiles:
            profile_id = profile_payload.profile_id.strip()
            if profile_id not in known_profile_ids:
                return [], f"unsupported WordPress AI routing profile: {profile_id}"
            if profile_id in seen_profile_ids:
                return [], f"duplicate WordPress AI routing profile: {profile_id}"
            seen_profile_ids.add(profile_id)
            candidate_instance_ids = [
                str(instance_id or "").strip()
                for instance_id in profile_payload.candidate_instance_ids
                if str(instance_id or "").strip()
            ]
            if not candidate_instance_ids:
                return [], f"profile {profile_id} requires at least one candidate instance"
            if len(candidate_instance_ids) != len(set(candidate_instance_ids)):
                return [], f"profile {profile_id} includes duplicate candidate instances"

            instances = repository.list_instances_by_ids(candidate_instance_ids)
            instances_by_id = {instance.instance_id: instance for instance in instances}
            missing = [
                instance_id
                for instance_id in candidate_instance_ids
                if instance_id not in instances_by_id
            ]
            if missing:
                return [], f"profile {profile_id} references unknown instance: {missing[0]}"

            models = repository.list_models_by_ids([instance.model_id for instance in instances])
            models_by_id = {model.model_id: model for model in models}
            for instance in instances:
                model = models_by_id.get(instance.model_id)
                if model is None:
                    return [], f"profile {profile_id} references an instance without a model"
                if model.feature != "text" or model.status != "available":
                    return [], (
                        f"profile {profile_id} may only use available text instances"
                    )

    return payload.profiles, ""


def _build_runtime_explanations(
    runtime_diagnostics: dict[str, Any] | None,
    *,
    site_id: str | None = None,
    account_id: str | None = None,
    subscription_id: str | None = None,
) -> list[dict[str, str]]:
    diagnostics = runtime_diagnostics or {}
    queue = _dict_value(diagnostics.get("queue"))
    callback = _dict_value(diagnostics.get("callback"))
    guard = _dict_value(diagnostics.get("guard"))
    items: list[dict[str, str]] = []

    if _coerce_int(callback.get("failed"), default=0) > 0 or callback.get("pressure_state") in {
        "attention",
        "critical",
    }:
        items.append(
            {
                "state": "degraded",
                "explain_text": (
                    "Callback delivery is already degraded. Operator follow-up "
                    "should start from site runtime posture before widening "
                    "provider or customer support work."
                ),
                "next_step_kind": "site",
                "next_step_ref": str(site_id or ""),
            }
        )
    if _coerce_int(queue.get("queued_runs"), default=0) > 0 or queue.get("pressure_state") in {
        "attention",
        "critical",
    }:
        items.append(
            {
                "state": "queued",
                "explain_text": (
                    "Queued or backlogged runs are accumulating. Confirm the "
                    "affected site first, then inspect provider or model surfaces "
                    "only if the queue remains the leading blocker."
                ),
                "next_step_kind": "site",
                "next_step_ref": str(site_id or ""),
            }
        )
    if _coerce_int(guard.get("recent_events"), default=0) > 0:
        items.append(
            {
                "state": "policy_gated",
                "explain_text": (
                    "Recent guard events suggest a policy or throttle gate is "
                    "already affecting runtime behavior. Check commercial "
                    "entitlement and support visibility before treating this as a "
                    "pure execution-source failure."
                ),
                "next_step_kind": "subscription" if subscription_id else "account",
                "next_step_ref": str(subscription_id or account_id or ""),
            }
        )

    if not items:
        items.append(
            {
                "state": "ok",
                "explain_text": (
                    "Current runtime summary does not surface an immediate "
                    "operator-critical blocker."
                ),
                "next_step_kind": "site" if site_id else "account",
                "next_step_ref": str(site_id or account_id or ""),
            }
        )

    return items


def _record_service_failure(
    request: Request,
    *,
    event_kind: str,
    error: CommercialServiceError,
    payload_json: dict[str, Any] | None = None,
    account_id: str | None = None,
    site_id: str | None = None,
    key_id: str | None = None,
    subscription_id: str | None = None,
    plan_id: str | None = None,
    plan_version_id: str | None = None,
    scope_kind: str | None = None,
    scope_id: str | None = None,
) -> None:
    try:
        _get_commercial_service(request).record_service_audit_event(
            audit_context=_build_audit_context(request),
            event_kind=event_kind,
            outcome="error",
            account_id=account_id,
            site_id=site_id,
            key_id=key_id,
            subscription_id=subscription_id,
            plan_id=plan_id,
            plan_version_id=plan_version_id,
            scope_kind=scope_kind,
            scope_id=scope_id,
            payload_json={
                "error_code": error.error_code,
                "message": error.message,
                "request": payload_json or {},
            },
        )
    except Exception:
        return


@router.post("/accounts")
async def upsert_account(
    request: Request,
    payload: AccountPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.upsert_account(
            account_id=payload.account_id,
            name=payload.name,
            status=payload.status,
            metadata_json=payload.metadata,
            bind_default_free=payload.bind_default_free,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="account.upsert",
            error=error,
            account_id=payload.account_id,
            scope_kind="account",
            scope_id=payload.account_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(status="ok", message="account saved", data=result, revision="m6")


@router.post("/admin/accounts/{account_id}/suspend")
async def suspend_admin_account(
    request: Request,
    account_id: str,
    payload: AccountStatusPayload | None = None,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.set_account_status(
            account_id,
            status="suspended",
            reason=payload.reason if payload is not None else "",
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="account.suspend",
            error=error,
            account_id=account_id,
            scope_kind="account",
            scope_id=account_id,
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="admin account suspended",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="account.suspend",
                scope_kind="account",
                scope_id=account_id,
                outcome="succeeded",
                effective_summary=f"Account {account_id} is now suspended.",
                account_id=account_id,
            ),
        ),
        revision="m6",
    )


@router.post("/admin/accounts/{account_id}/restore")
async def restore_admin_account(
    request: Request,
    account_id: str,
    payload: AccountStatusPayload | None = None,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.set_account_status(
            account_id,
            status="active",
            reason=payload.reason if payload is not None else "",
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="account.restore",
            error=error,
            account_id=account_id,
            scope_kind="account",
            scope_id=account_id,
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="admin account restored",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="account.restore",
                scope_kind="account",
                scope_id=account_id,
                outcome="succeeded",
                effective_summary=f"Account {account_id} is now active.",
                account_id=account_id,
            ),
        ),
        revision="m6",
    )


@router.post("/sites")
async def provision_site(
    request: Request,
    payload: SiteProvisionPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.provision_site(
            site_id=payload.site_id,
            account_id=payload.account_id,
            name=payload.name,
            status=payload.status,
            metadata_json=payload.metadata,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="site.provision",
            error=error,
            account_id=payload.account_id,
            site_id=payload.site_id,
            scope_kind="site",
            scope_id=payload.site_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(status="ok", message="site provisioned", data=result, revision="m6")


@router.post("/sites/{site_id}/site-admin-access")
async def upsert_site_admin_access(
    request: Request,
    site_id: str,
    payload: SiteAdminAccessPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.upsert_site_admin_access(
            site_id=site_id,
            email=payload.email,
            status=payload.status,
            metadata_json=payload.metadata,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="site_admin_access.upsert",
            error=error,
            site_id=site_id,
            scope_kind="site_admin_access",
            scope_id=site_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="site admin access saved",
        data=result,
        revision="m6",
    )


@router.post("/sites/{site_id}/activate")
async def activate_site(request: Request, site_id: str) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.activate_site(site_id, audit_context=audit_context)
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="site.activate",
            error=error,
            site_id=site_id,
            scope_kind="site",
            scope_id=site_id,
        )
        return _service_error_response(error)
    return build_envelope(status="ok", message="site activated", data=result, revision="m6")


@router.post("/sites/{site_id}/suspend")
async def suspend_site(
    request: Request,
    site_id: str,
    payload: SiteStatusPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.suspend_site(
            site_id,
            reason=payload.reason,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="site.suspend",
            error=error,
            site_id=site_id,
            scope_kind="site",
            scope_id=site_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(status="ok", message="site suspended", data=result, revision="m6")


@router.get("/sites/{site_id}/keys")
async def list_site_keys(
    request: Request,
    site_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).list_site_keys(
            site_id,
            limit=limit,
            offset=offset,
        )
    except CommercialServiceError as error:
        return _service_error_response(error)
    return build_envelope(status="ok", message="site keys loaded", data=result, revision="m6")


@router.post("/sites/{site_id}/keys")
async def issue_site_key(
    request: Request,
    site_id: str,
    payload: SiteKeyPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.issue_site_key(
            site_id=site_id,
            key_id=payload.key_id,
            secret=payload.secret,
            scopes=payload.scopes,
            label=payload.label,
            expires_at=payload.expires_at,
            metadata_json=payload.metadata,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="site_key.issue",
            error=error,
            site_id=site_id,
            key_id=payload.key_id,
            scope_kind="site_key",
            scope_id=payload.key_id or "",
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(status="ok", message="site key issued", data=result, revision="m6")


@router.post("/sites/{site_id}/keys/{key_id}/rotate")
async def rotate_site_key(
    request: Request,
    site_id: str,
    key_id: str,
    payload: SiteKeyPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.rotate_site_key(
            site_id=site_id,
            key_id=key_id,
            next_key_id=payload.key_id,
            secret=payload.secret,
            scopes=payload.scopes if payload.scopes else None,
            label=payload.label,
            expires_at=payload.expires_at,
            metadata_json=payload.metadata,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="site_key.rotate",
            error=error,
            site_id=site_id,
            key_id=key_id,
            scope_kind="site_key",
            scope_id=key_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(status="ok", message="site key rotated", data=result, revision="m6")


@router.post("/sites/{site_id}/keys/{key_id}/revoke")
async def revoke_site_key(
    request: Request,
    site_id: str,
    key_id: str,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.revoke_site_key(
            site_id=site_id,
            key_id=key_id,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="site_key.revoke",
            error=error,
            site_id=site_id,
            key_id=key_id,
            scope_kind="site_key",
            scope_id=key_id,
        )
        return _service_error_response(error)
    return build_envelope(status="ok", message="site key revoked", data=result, revision="m6")


@router.post("/sites/{site_id}/keys/{key_id}/expire")
async def expire_site_key(
    request: Request,
    site_id: str,
    key_id: str,
    payload: KeyExpirePayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.expire_site_key(
            site_id=site_id,
            key_id=key_id,
            expires_at=payload.expires_at,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="site_key.expire",
            error=error,
            site_id=site_id,
            key_id=key_id,
            scope_kind="site_key",
            scope_id=key_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(status="ok", message="site key expired", data=result, revision="m6")


@router.post("/plans")
async def upsert_plan(
    request: Request,
    payload: PlanPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.upsert_plan(
            plan_id=payload.plan_id,
            name=payload.name,
            status=payload.status,
            description=payload.description,
            metadata_json=payload.metadata,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="plan.upsert",
            error=error,
            plan_id=payload.plan_id,
            scope_kind="plan",
            scope_id=payload.plan_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="plan saved",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="plan.upsert",
                scope_kind="plan",
                scope_id=payload.plan_id,
                outcome="succeeded",
                effective_summary=(
                    f"Plan {payload.plan_id} is now saved on the commercial truth plane."
                ),
            ),
        ),
        revision="m6",
    )


@router.post("/plans/{plan_id}/versions")
async def publish_plan_version(
    request: Request,
    plan_id: str,
    payload: PlanVersionPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.publish_plan_version(
            plan_id=plan_id,
            plan_version_id=payload.plan_version_id,
            version_label=payload.version_label,
            status=payload.status,
            currency=payload.currency,
            entitlements_json=payload.entitlements,
            budgets_json=payload.budgets,
            concurrency_json=payload.concurrency,
            policy_json=payload.policy,
            metadata_json=payload.metadata,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="plan_version.publish",
            error=error,
            plan_id=plan_id,
            plan_version_id=payload.plan_version_id,
            scope_kind="plan_version",
            scope_id=payload.plan_version_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="plan version published",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="plan_version.publish",
                scope_kind="plan_version",
                scope_id=payload.plan_version_id,
                outcome="succeeded",
                effective_summary=(
                    f"Plan version {payload.plan_version_id} is now published "
                    "and ready for subscription binding."
                ),
            ),
        ),
        revision="m6",
    )


@router.post("/admin/accounts/{account_id}/subscription")
@router.patch("/admin/accounts/{account_id}/subscription")
async def upsert_account_subscription(
    request: Request,
    account_id: str,
    payload: SubscriptionPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.upsert_account_subscription(
            subscription_id=payload.subscription_id,
            account_id=account_id,
            plan_id=payload.plan_id,
            plan_version_id=payload.plan_version_id,
            status=payload.status,
            current_period_start_at=payload.current_period_start_at,
            current_period_end_at=payload.current_period_end_at,
            metadata_json=payload.metadata,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="subscription.upsert",
            error=error,
            account_id=account_id,
            subscription_id=payload.subscription_id,
            plan_id=payload.plan_id,
            plan_version_id=payload.plan_version_id,
            scope_kind="subscription",
            scope_id=payload.subscription_id or "",
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="account subscription saved",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="subscription.upsert",
                scope_kind="subscription",
                scope_id=str(
                    result.get("subscription_id") or payload.subscription_id or account_id
                ),
                outcome="succeeded",
                effective_summary=(
                    f"Account {account_id} now resolves to subscription "
                    f"{result.get('subscription_id') or payload.subscription_id or account_id}."
                ),
                account_id=account_id,
            ),
        ),
        revision="m6",
    )


@router.post("/admin/accounts/{account_id}/subscription/suspend")
async def suspend_account_subscription(request: Request, account_id: str) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.suspend_account_subscription(account_id, audit_context=audit_context)
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="subscription.suspend",
            error=error,
            account_id=account_id,
            scope_kind="subscription",
            scope_id=account_id,
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="account subscription suspended",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="subscription.suspend",
                scope_kind="subscription",
                scope_id=str(result.get("subscription_id") or account_id),
                outcome="succeeded",
                effective_summary=(
                    f"Current subscription coverage for account {account_id} is now suspended."
                ),
                account_id=str(result.get("account_id") or ""),
            ),
        ),
        revision="m6",
    )


@router.post("/subscriptions/{subscription_id}/topup")
async def apply_subscription_topup(
    request: Request,
    subscription_id: str,
    payload: SubscriptionTopUpPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.apply_operator_managed_subscription_topup(
            subscription_id=subscription_id,
            pack_id="",
            ai_credits_increment=payload.ai_credits_increment,
            runs_increment=payload.runs_increment,
            tokens_increment=payload.tokens_increment,
            cost_increment=payload.cost_increment,
            reason=payload.reason,
            note=payload.note,
            target_period_start_at=payload.target_period_start_at,
            target_period_end_at=payload.target_period_end_at,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="subscription.topup",
            error=error,
            subscription_id=subscription_id,
            scope_kind="subscription",
            scope_id=subscription_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="subscription top-up applied",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="subscription.topup",
                scope_kind="subscription",
                scope_id=subscription_id,
                outcome="succeeded",
                effective_summary=(
                    f"Subscription {subscription_id} now has operator-managed "
                    "budget headroom added "
                    f"for the current billing period"
                    + (
                        f" via pack {_dict_value(result.get('topup')).get('pack_id')}."
                        if str(_dict_value(result.get("topup")).get("pack_id") or "").strip()
                        else "."
                    )
                ),
            ),
        ),
        revision="m6",
    )


@router.post("/payments/orders")
async def create_payment_order(request: Request, payload: PaymentOrderPayload) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.create_payment_order(
            account_id=payload.account_id,
            plan_id=payload.plan_id,
            plan_version_id=payload.plan_version_id,
            amount=payload.amount,
            currency=payload.currency,
            provider=payload.provider,
            subject=payload.subject,
            site_id=payload.site_id,
            refund_window_days=payload.refund_window_days,
            metadata_json=payload.metadata,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="payment.order.create",
            error=error,
            account_id=payload.account_id,
            plan_id=payload.plan_id,
            plan_version_id=payload.plan_version_id,
            scope_kind="payment_order",
            scope_id=payload.account_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="payment order created",
        data=result,
        revision="m6",
    )


@router.get("/payments/credit-packs")
async def list_credit_packs(request: Request) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    return build_envelope(
        status="ok",
        message="credit packs loaded",
        data=_get_commercial_service(request).list_credit_packs(),
        revision="m6",
    )


@router.post("/payments/credit-pack-orders")
async def create_credit_pack_payment_order(
    request: Request,
    payload: CreditPackPaymentOrderPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.create_credit_pack_payment_order(
            account_id=payload.account_id,
            pack_id=payload.pack_id,
            provider=payload.provider,
            site_id=payload.site_id,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="payment.credit_pack_order.create",
            error=error,
            account_id=payload.account_id,
            scope_kind="payment_order",
            scope_id=payload.account_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="credit pack payment order created",
        data=result,
        revision="m6",
    )


@router.post("/payments/orders/{order_id}/mark-paid")
async def mark_payment_order_paid(
    request: Request,
    order_id: str,
    payload: PaymentSucceededPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.mark_payment_order_paid(
            order_id=order_id,
            provider_trade_no=payload.provider_trade_no,
            provider_event_id=payload.provider_event_id,
            paid_at=payload.paid_at,
            amount=payload.amount,
            raw_event=payload.raw_event,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="payment.order.paid",
            error=error,
            scope_kind="payment_order",
            scope_id=order_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="payment order marked paid",
        data=result,
        revision="m6",
    )


@router.post("/payments/orders/{order_id}/refunds")
async def request_payment_refund(
    request: Request,
    order_id: str,
    payload: PaymentRefundPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.request_payment_refund(
            order_id=order_id,
            amount=payload.amount,
            reason=payload.reason,
            metadata_json=payload.metadata,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="payment.refund.request",
            error=error,
            scope_kind="payment_order",
            scope_id=order_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="payment refund requested",
        data=result,
        revision="m6",
    )


@router.post("/payments/refunds/{refund_id}/mark-succeeded")
async def mark_payment_refund_succeeded(
    request: Request,
    refund_id: str,
    payload: PaymentRefundSucceededPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.mark_payment_refund_succeeded(
            refund_id=refund_id,
            provider_refund_no=payload.provider_refund_no,
            provider_event_id=payload.provider_event_id,
            succeeded_at=payload.succeeded_at,
            raw_event=payload.raw_event,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="payment.refund.succeeded",
            error=error,
            scope_kind="payment_refund",
            scope_id=refund_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="payment refund marked succeeded",
        data=result,
        revision="m6",
    )


@router.post("/admin/accounts/{account_id}/subscription/cancel")
async def cancel_account_subscription(request: Request, account_id: str) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.cancel_account_subscription(account_id, audit_context=audit_context)
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="subscription.cancel",
            error=error,
            account_id=account_id,
            scope_kind="subscription",
            scope_id=account_id,
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="account subscription canceled",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="subscription.cancel",
                scope_kind="subscription",
                scope_id=str(result.get("subscription_id") or account_id),
                outcome="succeeded",
                effective_summary=(
                    f"Current subscription coverage for account {account_id} is now canceled."
                ),
                account_id=str(result.get("account_id") or ""),
            ),
        ),
        revision="m6",
    )


@router.get("/sites/{site_id}/usage-meter")
async def inspect_usage_meter(
    request: Request,
    site_id: str,
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).inspect_usage_meter(site_id, limit=limit)
    except CommercialServiceError as error:
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="usage meter loaded",
        data=result,
        revision="m6",
    )


@router.get("/sites/{site_id}/billing-snapshots")
async def list_billing_snapshots(request: Request, site_id: str) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).list_billing_snapshots(site_id)
    except CommercialServiceError as error:
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="billing snapshots loaded",
        data=result,
        revision="m6",
    )


@router.get("/sites/{site_id}/billing-snapshots/reconciliation")
async def reconcile_billing_snapshot(request: Request, site_id: str) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).reconcile_billing_snapshot(site_id)
    except CommercialServiceError as error:
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="billing snapshot reconciliation loaded",
        data=result,
        revision="m6",
    )


@router.post("/sites/{site_id}/billing-snapshots/rebuild")
async def rebuild_billing_snapshot(request: Request, site_id: str) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.rebuild_billing_snapshot(site_id, audit_context=audit_context)
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="billing_snapshot.rebuild",
            error=error,
            site_id=site_id,
            scope_kind="billing_snapshot",
            scope_id=site_id,
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="billing snapshot rebuilt",
        data=result,
        revision="m6",
    )


@router.get("/sites/{site_id}/commercial-policy")
async def inspect_commercial_policy(request: Request, site_id: str) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).inspect_commercial_policy(site_id)
    except CommercialServiceError as error:
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="commercial policy loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/overview")
async def get_admin_overview(
    request: Request,
    usage_window_days: int = Query(default=7, ge=1, le=90),
    audit_window_minutes: int = Query(default=1440, ge=1, le=10080),
    runtime_recent_minutes: int = Query(default=60, ge=1, le=1440),
    hosted_model_recent_minutes: int = Query(default=1440, ge=1, le=10080),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    service = _get_commercial_service(request)
    try:
        result = service.get_admin_overview(
            usage_window_days=usage_window_days,
            audit_window_minutes=audit_window_minutes,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    runtime_service = RuntimeService(services.settings.database_url)
    result["runtime_diagnostics"] = runtime_service.get_runtime_diagnostics_summary(
        recent_minutes=runtime_recent_minutes,
    )
    hosted_model_governance = runtime_service.get_hosted_model_governance_diagnostics(
        recent_minutes=hosted_model_recent_minutes,
        limit=10,
    )
    result["hosted_model_governance"] = {
        "filters": hosted_model_governance.get("filters", {}),
        "generated_at": hosted_model_governance.get("generated_at", ""),
        "totals": hosted_model_governance.get("totals", {}),
        "alert_summary": hosted_model_governance.get("alert_summary", {}),
        "boundary": hosted_model_governance.get("boundary", {}),
    }
    attention_subscriptions = _dict_list(result.get("attention_subscriptions"))
    first_attention = attention_subscriptions[0] if attention_subscriptions else {}
    first_attention_account_id = ""
    first_attention_site_id = ""
    first_attention_subscription_id = ""
    if isinstance(first_attention, dict):
        first_attention_account_id = str(
            _dict_value(first_attention.get("account")).get("account_id")
            or first_attention.get("account_id")
            or ""
        )
        first_attention_site_id = str(
            _dict_value(first_attention.get("site")).get("site_id")
            or first_attention.get("site_id")
            or ""
        )
        first_attention_subscription_id = str(
            _dict_value(first_attention.get("subscription")).get("subscription_id")
            or first_attention.get("subscription_id")
            or ""
        )
    result["runtime_operator_explanations"] = _build_runtime_explanations(
        _dict_value(result.get("runtime_diagnostics")),
        site_id=first_attention_site_id,
        account_id=first_attention_account_id,
        subscription_id=first_attention_subscription_id,
    )
    return build_envelope(
        status="ok",
        message="admin overview loaded",
        data=result,
        revision="m6",
    )


@router.get("/advisor/runtime")
async def get_runtime_advisor(
    request: Request,
    site_id: str | None = Query(default=None, max_length=191),
    recent_minutes: int = Query(default=60, ge=1, le=1440),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    result = _get_advisor_service(request).get_runtime_advisor(
        site_id=site_id,
        recent_minutes=recent_minutes,
    )
    return build_envelope(
        status="ok",
        message="runtime advisor loaded",
        data=result,
        revision="m1",
    )


@router.get("/advisor/commercial")
async def get_commercial_advisor(
    request: Request,
    usage_window_days: int = Query(default=7, ge=1, le=90),
    audit_window_minutes: int = Query(default=1440, ge=1, le=10080),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    result = _get_advisor_service(request).get_commercial_advisor(
        usage_window_days=usage_window_days,
        audit_window_minutes=audit_window_minutes,
    )
    return build_envelope(
        status="ok",
        message="commercial advisor loaded",
        data=result,
        revision="m1",
    )


@router.get("/advisor/routing")
async def get_routing_advisor(
    request: Request,
    site_id: str = Query(min_length=1, max_length=191),
    range_filter: str = Query(default="24h", alias="range", max_length=16),
    limit: int = Query(default=25, ge=1, le=1000),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_advisor_service(request).get_routing_advisor(
            site_id=site_id,
            filters={"range": range_filter, "limit": limit},
        )
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                status="error",
                error_code="advisor.invalid_routing_window",
                message=str(error),
                data={"site_id": site_id, "range": range_filter, "limit": limit},
                revision="m1",
            ),
        )
    return build_envelope(
        status="ok",
        message="routing advisor loaded",
        data=result,
        revision="m1",
    )


@router.get("/advisor/site-diagnostics")
async def get_site_diagnostic_advisor(
    request: Request,
    site_id: str = Query(min_length=1, max_length=191),
    window_hours: int = Query(default=24, ge=1, le=168),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    result = _get_advisor_service(request).get_site_diagnostic_advisor(
        site_id=site_id,
        window_hours=window_hours,
    )
    return build_envelope(
        status="ok",
        message="site diagnostic advisor loaded",
        data=result,
        revision="m1",
    )


@router.get("/advisor/operations")
async def get_operations_advisor(
    request: Request,
    site_id: str | None = Query(default=None, max_length=191),
    range_filter: str = Query(default="24h", alias="range", max_length=16),
    usage_window_days: int = Query(default=7, ge=1, le=90),
    audit_window_minutes: int = Query(default=1440, ge=1, le=10080),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    result = _get_advisor_service(request).get_operations_advisor(
        site_id=site_id,
        window_hours=_advisor_range_to_hours(range_filter),
        usage_window_days=usage_window_days,
        audit_window_minutes=audit_window_minutes,
    )
    return build_envelope(
        status="ok",
        message="operations advisor loaded",
        data=result,
        revision="m1",
    )


@router.get("/advisor/ops-summary")
async def get_ops_summary_advisor(
    request: Request,
    scope: str = Query(default="runtime", max_length=32),
    site_id: str | None = Query(default=None, max_length=191),
    draft_kind: str = Query(default="support_reply", max_length=32),
    recent_minutes: int = Query(default=60, ge=1, le=1440),
    usage_window_days: int = Query(default=7, ge=1, le=90),
    audit_window_minutes: int = Query(default=1440, ge=1, le=10080),
    range_filter: str = Query(default="24h", alias="range", max_length=16),
    limit: int = Query(default=25, ge=1, le=1000),
    provider_id: str = Query(default="", max_length=64),
    model_id: str = Query(default=FREE_GPT55_MODEL_ID, max_length=191),
    force_refresh: bool = Query(default=False),
    cache_ttl_seconds: int = Query(default=1800, ge=0, le=86400),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_advisor_service(request).get_ops_summary(
            scope=scope,
            site_id=site_id,
            draft_kind=draft_kind,
            recent_minutes=recent_minutes,
            usage_window_days=usage_window_days,
            audit_window_minutes=audit_window_minutes,
            range_filter=range_filter,
            limit=limit,
            provider_id=provider_id,
            model_id=model_id,
            force_refresh=force_refresh,
            cache_ttl_seconds=cache_ttl_seconds,
        )
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                status="error",
                error_code="advisor.invalid_ops_summary_request",
                message=str(error),
                data={"scope": scope, "site_id": site_id or ""},
                revision="m1",
            ),
        )
    return build_envelope(
        status="ok",
        message="ops summary advisor loaded",
        data=result,
        revision="m1",
    )


@router.get("/advisor/ops-summary-preview")
async def get_ops_summary_preview_advisor(
    request: Request,
    scope: str = Query(default="runtime", max_length=32),
    site_id: str | None = Query(default=None, max_length=191),
    draft_kind: str = Query(default="support_reply", max_length=32),
    recent_minutes: int = Query(default=60, ge=1, le=1440),
    usage_window_days: int = Query(default=7, ge=1, le=90),
    audit_window_minutes: int = Query(default=1440, ge=1, le=10080),
    range_filter: str = Query(default="24h", alias="range", max_length=16),
    limit: int = Query(default=25, ge=1, le=1000),
    provider_id: str = Query(default="", max_length=64),
    model_id: str = Query(default=FREE_GPT55_MODEL_ID, max_length=191),
    force_refresh: bool = Query(default=False),
    cache_ttl_seconds: int = Query(default=1800, ge=0, le=86400),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_advisor_service(request).get_ops_summary_preview(
            scope=scope,
            site_id=site_id,
            draft_kind=draft_kind,
            recent_minutes=recent_minutes,
            usage_window_days=usage_window_days,
            audit_window_minutes=audit_window_minutes,
            range_filter=range_filter,
            limit=limit,
            provider_id=provider_id,
            model_id=model_id,
            force_refresh=force_refresh,
            cache_ttl_seconds=cache_ttl_seconds,
        )
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                status="error",
                error_code="advisor.invalid_ops_summary_preview_request",
                message=str(error),
                data={"scope": scope, "site_id": site_id or ""},
                revision="m1",
            ),
        )
    return build_envelope(
        status="ok",
        message="ops summary preview loaded",
        data=result,
        revision="m1",
    )


@router.post("/advisor/ops-summary-review")
async def review_ops_summary_disclosure(
    request: Request,
    payload: OpsSummaryDisclosureReviewPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_advisor_service(request).review_ops_summary_disclosure(
            cache_key=payload.cache_key,
            review_status=payload.review_status,
            actor_ref=payload.actor_ref,
            note=payload.note,
        )
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                status="error",
                error_code="advisor.invalid_ops_summary_review_request",
                message=str(error),
                data={"cache_key": payload.cache_key},
                revision="m1",
            ),
        )
    return build_envelope(
        status="ok",
        message="ops summary disclosure review saved",
        data=result,
        revision="m1",
    )


@router.get("/advisor/ops-summary-history")
async def list_ops_summary_history(
    request: Request,
    site_id: str | None = Query(default=None, max_length=191),
    scope: str = Query(default="", max_length=64),
    limit: int = Query(default=20, ge=1, le=100),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    result = _get_advisor_service(request).list_ops_summary_history(
        site_id=site_id,
        scope=scope,
        limit=limit,
    )
    return build_envelope(
        status="ok",
        message="ops summary history loaded",
        data=result,
        revision="m1",
    )


@router.get("/advisor/ops-summary-value")
async def get_ops_summary_value_metrics(
    request: Request,
    site_id: str | None = Query(default=None, max_length=191),
    scope: str = Query(default="", max_length=64),
    window_days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=10, ge=1, le=50),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    result = _get_advisor_service(request).get_ops_summary_value_metrics(
        site_id=site_id,
        scope=scope,
        window_days=window_days,
        limit=limit,
    )
    return build_envelope(
        status="ok",
        message="ops summary value metrics loaded",
        data=result,
        revision="m1",
    )


@router.get("/admin/accounts")
async def list_admin_accounts(
    request: Request,
    status: str | None = Query(default=None),
    expires_before: datetime | None = Query(default=None),  # noqa: B008
    coverage_state: str | None = Query(default=None),
    package_kind: str | None = Query(default=None),
    top_plan_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).list_admin_accounts(
            status=status,
            expires_before=expires_before,
            coverage_state=coverage_state,
            package_kind=package_kind,
            top_plan_id=top_plan_id,
            limit=limit,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin accounts loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/accounts/{account_id}")
async def get_admin_account(
    request: Request,
    account_id: str,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).get_admin_account(account_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin account loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/accounts/{account_id}/quota-summary")
async def get_admin_account_quota_summary(
    request: Request,
    account_id: str,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).get_admin_account_quota_summary(account_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin account quota summary loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/accounts/{account_id}/credit-ledger")
async def get_admin_account_credit_ledger(
    request: Request,
    account_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source_type: str | None = Query(default=None),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).get_admin_account_credit_ledger(
            account_id,
            limit=limit,
            offset=offset,
            source_type=source_type,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin account credit ledger loaded",
        data=result,
        revision="m6",
    )


@router.post("/admin/accounts/{account_id}/credit-ledger/adjustments")
async def apply_admin_account_credit_adjustment(
    request: Request,
    account_id: str,
    payload: AccountCreditAdjustmentPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.apply_admin_account_credit_adjustment(
            account_id=account_id,
            event_type=payload.event_type,
            credit_delta=payload.credit_delta,
            reason=payload.reason,
            note=payload.note,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="credit_ledger.adjustment",
            error=error,
            account_id=account_id,
            scope_kind="account",
            scope_id=account_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    entry = _dict_value(result.get("entry")) if isinstance(result, dict) else {}
    return build_envelope(
        status="ok",
        message="admin account credit adjustment applied",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="credit_ledger.adjustment",
                scope_kind="account",
                scope_id=account_id,
                outcome="succeeded",
                effective_summary=(
                    f"Account {account_id} AI credit ledger received "
                    f"{entry.get('event_type') or payload.event_type} "
                    f"delta {entry.get('credit_delta') or payload.credit_delta}."
                ),
                account_id=account_id,
            ),
        ),
        revision="m6",
    )


@router.get("/admin/accounts/{account_id}/subscription")
async def get_admin_account_subscription(
    request: Request,
    account_id: str,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        account = _get_commercial_service(request).get_admin_account(account_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    subscriptions = _dict_list(account.get("subscriptions"))
    current = subscriptions[0] if subscriptions else None
    return build_envelope(
        status="ok",
        message="admin account subscription loaded",
        data={
            "account": account.get("account"),
            "current_subscription": current,
            "subscriptions": subscriptions,
        },
        revision="m6",
    )


@router.get("/admin/sites")
async def list_admin_sites(
    request: Request,
    status: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    subscription_status: str | None = Query(default=None),
    expires_before: datetime | None = Query(default=None),  # noqa: B008
    limit: int = Query(default=100, ge=1, le=500),
    usage_window_days: int = Query(default=7, ge=1, le=90),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).list_admin_sites(
            status=status,
            account_id=account_id,
            subscription_status=subscription_status,
            expires_before=expires_before,
            limit=limit,
            usage_window_days=usage_window_days,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin sites loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/sites/{site_id}")
async def get_admin_site(
    request: Request,
    site_id: str,
    runtime_recent_minutes: int = Query(default=60, ge=1, le=1440),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    try:
        result = _get_commercial_service(request).get_admin_site(site_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    result["runtime_diagnostics"] = RuntimeService(
        services.settings.database_url
    ).get_runtime_diagnostics_summary(
        site_id=site_id,
        recent_minutes=runtime_recent_minutes,
    )
    result["runtime_operator_explanations"] = _build_runtime_explanations(
        _dict_value(result.get("runtime_diagnostics")),
        site_id=site_id,
        account_id=str(_dict_value(result.get("account")).get("account_id") or ""),
        subscription_id=str(_dict_value(result.get("subscription")).get("subscription_id") or ""),
    )
    related_account_id = str(_dict_value(result.get("account")).get("account_id") or "")
    related_subscription_id = str(
        _dict_value(result.get("subscription")).get("subscription_id") or ""
    )
    result["related_surfaces"] = {
        "account_href": f"/admin/accounts/{related_account_id}" if related_account_id else "",
        "subscription_href": (
            f"/admin/subscriptions/{related_subscription_id}" if related_subscription_id else ""
        ),
        "audit_href": f"/api/admin/audit-events?site_id={site_id}&limit=20",
    }
    result["commercial_follow_up"] = {
        "entitlement_summary": (
            "Use the linked plan and version snapshot as the current commercial "
            "entitlement boundary for this site."
        ),
        "budget_headroom_summary": (
            "Budget headroom should be read before widening runtime "
            "troubleshooting, because over-limit posture can be the real blocker."
        ),
        "runtime_gating_summary": (
            "If runtime posture is degraded or policy-gated, confirm whether "
            "subscription state, grace, or downgrade policy is already "
            "constraining this site."
        ),
        "next_operator_follow_up": (
            "Open the current customer subscription when commercial coverage is "
            "the blocker; stay on site detail when runtime posture is the blocker."
        ),
    }
    return build_envelope(
        status="ok",
        message="admin site loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/subscriptions")
async def list_admin_subscriptions(
    request: Request,
    status: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    plan_id: str | None = Query(default=None),
    expires_before: datetime | None = Query(default=None),  # noqa: B008
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).list_admin_subscriptions(
            status=status,
            account_id=account_id,
            plan_id=plan_id,
            expires_before=expires_before,
            limit=limit,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin subscriptions loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/subscriptions/{subscription_id}")
async def get_admin_subscription(
    request: Request,
    subscription_id: str,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).get_admin_subscription(subscription_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    site_id = str(_dict_value(result.get("site")).get("site_id") or "")
    account_id = str(_dict_value(result.get("account")).get("account_id") or "")
    result["related_surfaces"] = {
        "site_href": f"/admin/sites/{site_id}" if site_id else "",
        "account_href": f"/admin/accounts/{account_id}" if account_id else "",
        "audit_href": (
            f"/api/admin/audit-events?site_id={site_id}&account_id={account_id}&limit=20"
            if site_id or account_id
            else ""
        ),
    }
    result["commercial_follow_up"] = {
        "lifecycle_posture": (
            "Read current status and grace posture first; commercial follow-up "
            "should lead before runtime debugging when the subscription is degraded."
        ),
        "snapshot_reconciliation_summary": (
            "Use site detail and filtered audit evidence to confirm whether "
            "snapshot posture and current operational impact are still aligned."
        ),
        "next_operator_follow_up": (
            "Open site detail for runtime and entitlement impact, or customer "
            "detail for support scope."
        ),
    }
    return build_envelope(
        status="ok",
        message="admin subscription loaded",
        data=result,
        revision="m6",
    )


@router.post("/admin/subscriptions/{subscription_id}/billing-snapshots/rebuild")
async def rebuild_admin_subscription_billing_snapshots(
    request: Request,
    subscription_id: str,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.rebuild_subscription_billing_snapshots(
            subscription_id,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="subscription.billing_snapshot.rebuild",
            error=error,
            subscription_id=subscription_id,
            scope_kind="subscription",
            scope_id=subscription_id,
        )
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="subscription billing snapshots rebuilt",
        data=result,
        revision="m6",
    )


@router.get("/admin/plans")
async def list_admin_plans(
    request: Request,
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).list_admin_plans(
            status=status,
            limit=limit,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin plans loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/plans/{plan_id}")
async def get_admin_plan(
    request: Request,
    plan_id: str,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).get_admin_plan(plan_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin plan loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/plugin-observability")
async def get_admin_plugin_observability(
    request: Request,
    window_hours: int = Query(default=24, ge=1, le=168),
    site_id: str = Query(default=""),
    plugin_slug: str = Query(default=""),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    service = PluginObservabilityService(services.settings.database_url)
    result = service.get_admin_summary(
        window_hours=window_hours,
        site_id=site_id,
        plugin_slug=plugin_slug,
    )
    return build_envelope(
        status="ok",
        message="plugin observability admin summary loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/media-observability")
async def get_admin_media_observability(
    request: Request,
    window_hours: int = Query(default=24, ge=1, le=168),
    site_id: str = Query(default=""),
    target_format: str = Query(default=""),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    service = MediaDerivativeObservabilityService(
        services.settings.database_url,
        site_queued_limit=services.settings.media_derivative_site_queued_limit,
        site_running_limit=services.settings.media_derivative_site_running_limit,
        default_chunk_size=services.settings.media_derivative_batch_default_chunk_size,
    )
    result = service.get_summary(
        window_hours=window_hours,
        site_id=site_id.strip(),
        target_format=target_format.strip(),
    )
    result["workflow_metadata"] = get_workflow_metadata(MEDIA_DERIVATIVE_WORKFLOW_ID)
    return build_envelope(
        status="ok",
        message="media observability admin summary loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/vector-observability")
async def get_admin_vector_observability(
    request: Request,
    window_hours: int = Query(default=24, ge=1, le=168),
    site_id: str = Query(default=""),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    service = SiteKnowledgeObservabilityService(services.settings.database_url)
    result = service.get_summary(
        window_hours=window_hours,
        site_id=site_id.strip(),
    )
    return build_envelope(
        status="ok",
        message="vector observability admin summary loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/agent-feedback")
async def get_admin_agent_feedback(
    request: Request,
    window_hours: int = Query(default=24, ge=1, le=168),
    site_id: str = Query(default=""),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    service = AgentFeedbackService(services.settings.database_url)
    result = service.get_summary(
        site_id=site_id.strip() or None,
        window_hours=window_hours,
    )
    result["read_only"] = True
    result["surface"] = "internal_admin_quality_feedback"
    result["boundary"] = {
        "production_mutation": False,
        "approval_truth": "wordpress_local",
        "preflight_truth": "wordpress_local",
        "final_write_truth": "wordpress_local",
        "control_plane": "wordpress_local",
    }
    return build_envelope(
        status="ok",
        message="agent feedback admin summary loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/web-search-providers")
async def get_admin_web_search_providers(request: Request) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = WebSearchAdminConfigService(services.settings).get_config()
    result["workflow_metadata"] = get_workflow_metadata(WEB_SEARCH_EVIDENCE_WORKFLOW_ID)
    return build_envelope(
        status="ok",
        message="web search provider settings loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/agent-workflow-metadata")
async def get_admin_agent_workflow_metadata(request: Request) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    return build_envelope(
        status="ok",
        message="agent workflow metadata projection loaded",
        data=get_agent_workflow_metadata_projection(),
        revision="m6",
    )


@router.post("/admin/web-search-providers")
async def update_admin_web_search_providers(
    request: Request,
    payload: WebSearchProviderSettingsPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = WebSearchAdminConfigService(services.settings).save_config(
        payload.model_dump(mode="json")
    )
    result["workflow_metadata"] = get_workflow_metadata(WEB_SEARCH_EVIDENCE_WORKFLOW_ID)
    return build_envelope(
        status="ok",
        message="web search provider settings saved",
        data=result,
        revision="m6",
    )


@router.get("/admin/image-source-providers")
async def get_admin_image_source_providers(request: Request) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    return build_envelope(
        status="ok",
        message="image source provider settings loaded",
        data=ImageSourceAdminConfigService(services.settings).get_config(),
        revision="m6",
    )


@router.post("/admin/image-source-providers")
async def update_admin_image_source_providers(
    request: Request,
    payload: ImageSourceProviderSettingsPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = ImageSourceAdminConfigService(services.settings).save_config(
        payload.model_dump(mode="json")
    )
    return build_envelope(
        status="ok",
        message="image source provider settings saved",
        data=result,
        revision="m6",
    )


@router.get("/admin/audio-providers")
async def get_admin_audio_providers(request: Request) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    return build_envelope(
        status="ok",
        message="audio provider settings loaded",
        data=AudioProviderAdminConfigService(services.settings).get_config(),
        revision="m6",
    )


@router.post("/admin/audio-providers")
async def update_admin_audio_providers(
    request: Request,
    payload: AudioProviderSettingsPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = AudioProviderAdminConfigService(services.settings).save_config(
        payload.model_dump(mode="json")
    )
    return build_envelope(
        status="ok",
        message="audio provider settings saved",
        data=result,
        revision="m6",
    )


@router.post("/admin/audio-providers/minimax/test")
async def test_admin_audio_provider_minimax(request: Request) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    try:
        result = AudioProviderAdminConfigService(services.settings).test_minimax_connection()
    except AudioProviderAdminConfigError as error:
        return JSONResponse(
            status_code=409,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                revision="m6",
            ),
        )
    except ProviderExecutionError as error:
        return JSONResponse(
            status_code=502,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                revision="m6",
            ),
        )
    return build_envelope(
        status="ok",
        message="MiniMax sample audio generated",
        data=result,
        revision="m6",
    )


@router.get("/admin/ai-resources")
async def get_admin_ai_resources(request: Request) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    return build_envelope(
        status="ok",
        message="AI resource projection loaded",
        data=build_admin_ai_resource_projection(
            services.settings,
            providers=services.providers,
            database_url=services.settings.database_url,
        ),
        revision="m6",
    )


@router.post("/admin/ai-resources/profile-preferences")
async def update_admin_ai_resource_profile_preferences(
    request: Request,
    payload: AIResourceProfilePreferencePayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    try:
        result = AIResourceProfilePreferenceService(services.settings).save(
            payload.model_dump(mode="json")
        )
    except AIResourceProfilePreferenceError as error:
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                revision="m6",
            ),
        )
    return build_envelope(
        status="ok",
        message="AI resource profile preferences saved",
        data=result,
        revision="m6",
    )


@router.get("/admin/wordpress-ai-routing")
async def get_admin_wordpress_ai_routing(request: Request) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    return build_envelope(
        status="ok",
        message="WordPress AI connector routing loaded",
        data=_build_wordpress_ai_routing_projection(services.settings.database_url),
        revision="m6",
    )


@router.post("/admin/wordpress-ai-routing")
async def update_admin_wordpress_ai_routing(
    request: Request,
    payload: WordPressAIRoutingSettingsPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    profiles, error_message = _validate_wordpress_ai_routing_payload(
        services.settings.database_url,
        payload,
    )
    if error_message:
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                status="error",
                error_code="wordpress_ai_routing.invalid_profile",
                message=error_message,
                revision="m6",
            ),
        )

    revision = f"wp-ai-admin-{int(datetime.now(UTC).timestamp())}"
    with get_session(services.settings.database_url) as session:
        repository = CatalogRepository(session)
        for profile_payload in profiles:
            profile_id = profile_payload.profile_id.strip()
            spec = WP_AI_CONNECTOR_PROFILE_SPECS_BY_ID[profile_id]
            candidate_instance_ids = [
                str(instance_id or "").strip()
                for instance_id in profile_payload.candidate_instance_ids
                if str(instance_id or "").strip()
            ]
            repository.upsert_routing_profile(
                profile_id=profile_id,
                execution_kind="text",
                default_policy_json={
                    "allow_fallback": profile_payload.allow_fallback,
                    "max_retries": profile_payload.max_retries,
                    "timeout_ms": profile_payload.timeout_ms,
                    "managed_surface": "wordpress_ai_connector",
                    "task_group": spec.group_id,
                    "tasks": list(spec.tasks),
                    "operator_note": profile_payload.note.strip(),
                },
            )
            repository.upsert_routing_binding(
                profile_id=profile_id,
                candidate_instance_ids=candidate_instance_ids,
                selection_policy_json={
                    "strategy": "ordered",
                    "managed_surface": "wordpress_ai_connector",
                    "task_group": spec.group_id,
                    "operator_note": profile_payload.note.strip(),
                },
                revision=revision,
            )
        session.commit()

    audit_event = None
    try:
        audit_event = _get_commercial_service(request).record_service_audit_event(
            audit_context=_build_audit_context(request),
            event_kind="wordpress_ai_routing.update",
            outcome="succeeded",
            scope_kind="runtime_profile",
            scope_id="wordpress_ai_connector",
            payload_json={
                "profile_ids": [profile.profile_id for profile in profiles],
                "revision": revision,
            },
        )
    except Exception:
        audit_event = None

    result = _build_wordpress_ai_routing_projection(services.settings.database_url)
    return build_envelope(
        status="ok",
        message="WordPress AI connector routing saved",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="wordpress_ai_routing.update",
                scope_kind="runtime_profile",
                scope_id="wordpress_ai_connector",
                outcome="succeeded",
                effective_summary="WordPress AI connector task routing was updated.",
                audit_event=audit_event,
            ),
        ),
        revision="m6",
    )


def _audio_workbench_service(request: Request) -> AudioWorkbenchService:
    services = get_cloud_services(request)
    return AudioWorkbenchService(
        services.settings.database_url,
        settings=services.settings,
        providers=services.providers,
        runtime_queue=services.runtime_queue,
        callback_dispatcher=services.callback_dispatcher,
    )


@router.post("/admin/audio-jobs")
async def create_admin_audio_job(
    request: Request,
    payload: AudioWorkbenchCreatePayload,
    background_tasks: BackgroundTasks,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _audio_workbench_service(request)
    try:
        result = service.create_job(payload.model_dump(mode="json"))
    except AudioWorkbenchError as error:
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                data=error.to_payload(),
                revision="m6",
            ),
        )
    if str(result.get("status") or "") == "queued":
        background_tasks.add_task(service.process_one_queued_job)
    return build_envelope(
        status="ok",
        message="audio job created",
        data=result,
        revision="m6",
    )


@router.get("/admin/audio-jobs/recent")
async def list_admin_audio_jobs_recent(request: Request, limit: int = Query(default=10)) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    result = _audio_workbench_service(request).list_recent_jobs(limit=limit)
    return build_envelope(
        status="ok",
        message="recent audio jobs loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/audio-jobs/{run_id}")
async def get_admin_audio_job(request: Request, run_id: str) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _audio_workbench_service(request).get_job(run_id)
    except RuntimeRunNotFoundError as error:
        return JSONResponse(
            status_code=404,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                revision="m6",
            ),
        )
    return build_envelope(
        status="ok",
        message="audio job loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/image-source-metrics")
async def get_admin_image_source_metrics(
    request: Request,
    window_hours: int = Query(default=24, ge=1, le=168),
    site_id: str = Query(default=""),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = ImageSourceMetricsService(services.settings.database_url).get_summary(
        site_id=site_id.strip() or None,
        window_hours=window_hours,
    )
    return build_envelope(
        status="ok",
        message="image source readonly metrics loaded",
        data=result,
        revision="m6",
    )


@router.post("/admin/plugin-observability/attention-state")
async def update_admin_plugin_observability_attention_state(
    request: Request,
    payload: PluginAttentionStatePayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    service = PluginObservabilityService(services.settings.database_url)
    try:
        result = service.update_attention_state(
            attention_key=payload.attention_key.strip(),
            attention_code=payload.attention_code.strip(),
            action=payload.action.strip(),
            site_id=payload.site_id.strip(),
            plugin_slug=payload.plugin_slug.strip(),
            event_kind=payload.event_kind.strip(),
            error_code=payload.error_code.strip(),
            mute_hours=payload.mute_hours,
            operator_note=payload.note.strip(),
            actor_ref="internal",
        )
    except ValueError as error:
        return JSONResponse(
            status_code=422,
            content=build_envelope(
                status="error",
                error_code="plugin_observability.attention_action_invalid",
                message=str(error),
                trace_id=extract_trace_id(request.headers.get("traceparent", "")),
                revision="m6",
            ),
        )
    return build_envelope(
        status="ok",
        message="plugin observability attention state updated",
        data=result,
        revision="m6",
    )


@router.get("/audit-events")
async def list_service_audit_events(
    request: Request,
    site_id: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    event_kind: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    result = _get_commercial_service(request).list_service_audit_events(
        site_id=site_id,
        account_id=account_id,
        event_kind=event_kind,
        outcome=outcome,
        limit=limit,
    )
    return build_envelope(
        status="ok",
        message="service audit events loaded",
        data=result,
        revision="m6",
    )


@router.get("/audit-events/summary")
async def summarize_service_audit_events(
    request: Request,
    site_id: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    window_minutes: int = Query(default=1440, ge=1, le=10080),
    limit: int = Query(default=20, ge=1, le=100),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    result = _get_commercial_service(request).summarize_service_audit_events(
        site_id=site_id,
        account_id=account_id,
        window_minutes=window_minutes,
        limit=limit,
    )
    return build_envelope(
        status="ok",
        message="service audit summary loaded",
        data=result,
        revision="m6",
    )


@router.get("/ops/cadence")
async def get_ops_cadence_summary(request: Request) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    result = build_cadence_summary(get_cloud_services(request).settings)
    return build_envelope(
        status="ok",
        message="ops cadence summary loaded",
        data=result,
        revision="m7",
    )


@router.get("/observability/summary")
async def get_observability_summary(
    request: Request,
    recent_minutes: int = Query(default=60, ge=1, le=1440),
    backlog_limit: int = Query(default=10, ge=1, le=50),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    ready_report = await services.get_ready_report()
    result = ObservabilityService(services.settings).build_summary(
        ready_report=ready_report,
        recent_minutes=recent_minutes,
        backlog_limit=backlog_limit,
    )
    return build_envelope(
        status="ok",
        message="observability summary loaded",
        data=result,
        revision="m1",
    )


@router.get("/commercial-decisions")
async def list_commercial_decision_events(
    request: Request,
    site_id: str | None = Query(default=None),
    decision: str | None = Query(default=None),
    request_kind: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    result = _get_commercial_service(request).list_commercial_decision_events(
        site_id=site_id,
        decision=decision,
        request_kind=request_kind,
        limit=limit,
    )
    return build_envelope(
        status="ok",
        message="commercial decision events loaded",
        data=result,
        revision="m6",
    )


@router.get("/commercial-decisions/summary")
async def summarize_commercial_decision_events(
    request: Request,
    site_id: str | None = Query(default=None),
    request_kind: str | None = Query(default=None),
    window_minutes: int = Query(default=1440, ge=1, le=10080),
    limit: int = Query(default=20, ge=1, le=100),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    result = _get_commercial_service(request).summarize_commercial_decision_events(
        site_id=site_id,
        request_kind=request_kind,
        window_minutes=window_minutes,
        limit=limit,
    )
    return build_envelope(
        status="ok",
        message="commercial decision summary loaded",
        data=result,
        revision="m6",
    )


@router.get("/runtime/diagnostics/summary")
async def get_runtime_diagnostics_summary(
    request: Request,
    site_id: str | None = Query(default=None),
    recent_minutes: int = Query(default=60, ge=1, le=1440),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = RuntimeService(services.settings.database_url).get_runtime_diagnostics_summary(
        site_id=site_id,
        recent_minutes=recent_minutes,
    )
    return build_envelope(
        status="ok",
        message="runtime diagnostics summary loaded",
        data=result,
        revision="m8",
    )


@router.get("/runtime/diagnostics/nightly-inspection")
async def get_nightly_inspection_observability(
    request: Request,
    site_id: str | None = Query(default=None),
    recent_minutes: int = Query(default=1440, ge=1, le=10080),
    limit: int = Query(default=20, ge=1, le=100),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = RuntimeService(
        services.settings.database_url,
        settings=services.settings,
    ).get_nightly_inspection_observability(
        site_id=site_id,
        recent_minutes=recent_minutes,
        limit=limit,
    )
    return build_envelope(
        status="ok",
        message="nightly inspection observability loaded",
        data=result,
        revision="m1",
    )


@router.get("/admin/hosted-model-governance")
@router.get("/runtime/diagnostics/hosted-model-governance")
async def get_hosted_model_governance_diagnostics(
    request: Request,
    site_id: str | None = Query(default=None),
    recent_minutes: int = Query(default=60, ge=1, le=10080),
    limit: int = Query(default=20, ge=1, le=100),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = RuntimeService(services.settings.database_url).get_hosted_model_governance_diagnostics(
        site_id=site_id,
        recent_minutes=recent_minutes,
        limit=limit,
    )
    return build_envelope(
        status="ok",
        message="hosted model governance diagnostics loaded",
        data=result,
        revision="m1",
    )


@router.get("/admin/hosted-model-governance-cadence")
async def get_hosted_model_governance_cadence(
    request: Request,
    recent_minutes: int = Query(default=1440, ge=1, le=10080),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = UsageRollupService(services.settings.database_url).get_hosted_model_governance_batch(
        window_minutes=recent_minutes,
    )
    if result is None:
        result = {
            "available": False,
            "source": "cloud_hosted_model_governance_empty",
            "filters": {
                "site_id": "",
                "recent_minutes": recent_minutes,
            },
            "generated_at": "",
            "alert_summary": {
                "status": "inactive",
                "summary": "No hosted model governance cadence record is available yet.",
                "alert_count": 0,
                "alerts": [],
                "daily_digest": {
                    "runs": 0,
                    "provider_calls": 0,
                    "meter_events": 0,
                    "metered_run_coverage_rate": 0,
                    "provider_call_run_coverage_rate": 0,
                    "unmetered_run_count": 0,
                    "runs_without_provider_call_count": 0,
                },
            },
            "delivery": {
                "owner": "internal_admin_readonly",
                "buffer_kind": "usage_rollup",
                "scope_kind": "hosted_model_governance_batch",
            },
            "boundary": {
                "surface": "internal_admin_summary",
                "cloud_role": "hosted_runtime_detail",
                "local_control_plane": "wordpress_plugin",
                "direct_wordpress_write": False,
                "contains_prompt_or_result_payloads": False,
            },
        }
    else:
        result = {**result, "available": True}
    return build_envelope(
        status="ok",
        message="hosted model governance cadence loaded",
        data=result,
        revision="m1",
    )


@router.get("/runtime/diagnostics/backlog")
async def get_runtime_backlog_diagnostics(
    request: Request,
    scope_kind: str = Query(default="site_id", pattern=RUNTIME_BACKLOG_SCOPE_KIND_PATTERN),
    site_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = RuntimeService(services.settings.database_url).get_runtime_backlog_diagnostics(
        scope_kind=scope_kind,
        site_id=site_id,
        limit=limit,
    )
    return build_envelope(
        status="ok",
        message="runtime backlog diagnostics loaded",
        data=result,
        revision="m1",
    )


@router.get("/runtime/diagnostics/runs")
async def list_runtime_diagnostic_runs(
    request: Request,
    issue_kind: str = Query(
        default="callback_failed",
        pattern=RUNTIME_DIAGNOSTIC_ISSUE_KIND_PATTERN,
    ),
    site_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = RuntimeService(services.settings.database_url).list_runtime_diagnostic_runs(
        issue_kind=issue_kind,
        site_id=site_id,
        limit=limit,
    )
    return build_envelope(
        status="ok",
        message="runtime diagnostic runs loaded",
        data=result,
        revision="m7",
    )


@router.get("/runtime/diagnostics/guard-events")
async def list_runtime_guard_events(
    request: Request,
    site_id: str | None = Query(default=None),
    scope_kind: str | None = Query(default=None),
    event_code: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = RuntimeService(services.settings.database_url).list_runtime_guard_events(
        site_id=site_id,
        scope_kind=scope_kind,
        event_code=event_code,
        limit=limit,
    )
    return build_envelope(
        status="ok",
        message="runtime guard events loaded",
        data=result,
        revision="m6",
    )


@router.get("/runtime/diagnostics/abuse-guard")
async def get_runtime_abuse_guard_diagnostics(
    request: Request,
    window_seconds: int = Query(default=60, ge=1, le=3600),
    cooldown_window_seconds: int = Query(default=1800, ge=60, le=86400),
    limit_per_scope: int = Query(default=10, ge=1, le=50),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = RuntimeService(services.settings.database_url).get_abuse_guard_diagnostics(
        window_seconds=window_seconds,
        cooldown_window_seconds=cooldown_window_seconds,
        limit_per_scope=limit_per_scope,
        public_post_site_limit=services.settings.public_post_max_requests_per_window,
        public_post_key_limit=services.settings.public_post_max_requests_per_key_window,
        public_post_ip_limit=services.settings.public_post_max_requests_per_ip_window,
        public_guard_site_cooldown_limit=(
            services.settings.public_guard_max_reject_events_per_site_window
        ),
        public_guard_key_cooldown_limit=(
            services.settings.public_guard_max_reject_events_per_key_window
        ),
        public_guard_ip_cooldown_limit=(
            services.settings.public_guard_max_reject_events_per_ip_window
        ),
        internal_post_token_limit=services.settings.internal_post_max_requests_per_window,
        internal_post_ip_limit=services.settings.internal_post_max_requests_per_ip_window,
        internal_guard_token_cooldown_limit=(
            services.settings.internal_guard_max_reject_events_per_token_window
        ),
        internal_guard_ip_cooldown_limit=(
            services.settings.internal_guard_max_reject_events_per_ip_window
        ),
    )
    return build_envelope(
        status="ok",
        message="runtime abuse guard diagnostics loaded",
        data=result,
        revision="m7",
    )


@router.post("/runtime/retention/cleanup")
async def cleanup_runtime_retention(request: Request) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth

    audit_context = _build_audit_context(request)
    try:
        services = get_cloud_services(request)
        purged = RuntimeService(services.settings.database_url).cleanup_expired_run_results()
        _get_commercial_service(request).record_service_audit_event(
            audit_context=audit_context,
            event_kind="runtime.retention_cleanup",
            outcome="succeeded",
            scope_kind="runtime",
            scope_id="retention_cleanup",
            payload_json={"purged_runs": purged},
        )
    except Exception as error:
        _get_commercial_service(request).record_service_audit_event(
            audit_context=audit_context,
            event_kind="runtime.retention_cleanup",
            outcome="error",
            scope_kind="runtime",
            scope_id="retention_cleanup",
            payload_json={"message": str(error)},
        )
        return JSONResponse(
            status_code=500,
            content=build_envelope(
                status="error",
                error_code="service.retention_cleanup_failed",
                message="runtime retention cleanup failed",
                revision="m6",
            ),
        )

    return build_envelope(
        status="ok",
        message="runtime retention cleanup completed",
        data={"purged_runs": purged},
        revision="m6",
    )
