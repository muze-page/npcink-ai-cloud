from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.adapters.notifications.base import PortalEmailDeliveryError
from app.adapters.notifications.smtp import build_portal_email_sender
from app.adapters.providers.registry import resolve_live_provider_adapters
from app.adapters.repositories.catalog_repository import CatalogRepository
from app.api.auth import authorize_internal_request, get_cloud_services
from app.api.envelope import build_envelope
from app.core.db import get_session
from app.core.logging import get_logger
from app.core.models import ProviderConnection
from app.core.security import extract_trace_id
from app.domain.advisor.service import InternalAIAdvisorService
from app.domain.agent_feedback.service import AgentFeedbackService
from app.domain.agent_workflow_metadata import (
    MEDIA_DERIVATIVE_WORKFLOW_ID,
    get_agent_workflow_metadata_projection,
    get_workflow_metadata,
)
from app.domain.audio_generation.workbench import (
    AudioWorkbenchError,
    AudioWorkbenchService,
)
from app.domain.catalog.service import CatalogService
from app.domain.commercial.errors import CommercialServiceError
from app.domain.commercial.service import CommercialService, ServiceAuditContext
from app.domain.hosted_model_defaults import FREE_GPT55_MODEL_ID
from app.domain.image_sources.metrics import ImageSourceMetricsService
from app.domain.media_derivatives.metrics import MediaDerivativeObservabilityService
from app.domain.model_references import ModelReferenceError, ModelReferenceService
from app.domain.observability.plugin_events import PluginObservabilityService
from app.domain.observability.service import ObservabilityService
from app.domain.provider_connections.model_allowlist import (
    build_provider_model_allowlist,
)
from app.domain.provider_connections.runtime_settings import (
    apply_provider_connection_runtime_settings,
)
from app.domain.provider_connections.service import (
    ProviderConnectionAdminError,
    ProviderConnectionAdminService,
)
from app.domain.provider_resources import (
    build_admin_ability_model_runtime_projection,
    build_admin_ai_resource_projection,
)
from app.domain.runtime.models import (
    RUNTIME_BACKLOG_SCOPE_KIND_PATTERN,
    RUNTIME_DIAGNOSTIC_ISSUE_KIND_PATTERN,
)
from app.domain.runtime.service import RuntimeRunNotFoundError, RuntimeService
from app.domain.service_settings import (
    ServiceSettingsAdminError,
    ServiceSettingsAdminService,
    resolve_portal_public_base_url,
)
from app.domain.site_knowledge.metrics import SiteKnowledgeObservabilityService
from app.domain.wordpress_ai_connector.routing_profiles import (
    WP_AI_CONNECTOR_PROFILE_SPECS,
    WP_AI_CONNECTOR_PROFILE_SPECS_BY_ID,
)
from app.workers.ops_cadence import build_cadence_summary

router = APIRouter(prefix="/internal/service", tags=["service"])
logger = get_logger(__name__)


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


class PortalUserDisablePayload(BaseModel):
    reason: str = ""


class PortalUsersBatchDisablePayload(BaseModel):
    principal_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class AdminSupportRequestUpdatePayload(BaseModel):
    status: str = ""
    admin_note: str = ""


class AdminSupportRequestMessagePayload(BaseModel):
    body: str = Field(default="", max_length=4000)
    visibility: str = Field(default="public", max_length=32)


class AdminSupportRequestAttachmentPayload(BaseModel):
    filename: str = Field(default="", max_length=191)
    content_type: str = Field(default="", max_length=128)
    content_base64: str = ""
    visibility: str = Field(default="public", max_length=32)
    message_id: str = Field(default="", max_length=191)


class SiteProvisionPayload(BaseModel):
    site_id: str
    account_id: str
    name: str = ""
    status: str = "provisioning"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SiteStatusPayload(BaseModel):
    reason: str = ""


class AccountMemberAccessPayload(BaseModel):
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
    currency: str = "CNY"
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


class CreditPackCatalogItemPayload(BaseModel):
    pack_id: str
    label: str = ""
    ai_credits: int = 0
    amount: float = 0.0
    currency: str = "CNY"
    recommended_for_tiers: list[str] = Field(default_factory=list)
    validity_days: int = 365
    active: bool = True


class CreditPackCatalogPayload(BaseModel):
    items: list[CreditPackCatalogItemPayload] = Field(default_factory=list)


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


class AudioWorkbenchCreatePayload(BaseModel):
    intent: str = Field(default="article_narration", max_length=64)
    site_id: str = Field(default="", max_length=191)
    title: str = Field(default="", max_length=240)
    body: str = Field(min_length=1, max_length=25000)
    format: str = Field(default="mp3", max_length=16)
    preview_instance_id: str = Field(default="", max_length=191)


class ProviderConnectionPayload(BaseModel):
    connection_id: str | None = Field(default=None, max_length=64)
    provider_id: str | None = Field(default=None, max_length=64)
    provider_type: str | None = Field(default=None, max_length=64)
    kind: str | None = Field(default=None, max_length=64)
    display_name: str = Field(default="", max_length=191)
    enabled: bool = True
    base_url: str = Field(default="", max_length=500)
    note: str = Field(default="", max_length=512)
    priority: int = Field(default=100, ge=0, le=999)
    source_role: str = Field(default="execution_source", max_length=32)
    capability_ids: list[str] = Field(default_factory=list)
    runtime_profile_ids: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    credential: str | None = None
    secret: str | None = None
    secretless: bool = False


class PortalPublicServiceSettingsPayload(BaseModel):
    enabled: bool = True
    public_base_url: str = Field(max_length=500)


class QQLoginServiceSettingsPayload(BaseModel):
    enabled: bool = True
    client_id: str = Field(max_length=191)
    client_secret: str | None = Field(default=None, max_length=500)
    redirect_uri: str = Field(default="", max_length=500)
    scope: str = Field(default="get_user_info", max_length=128)
    timeout_seconds: float = Field(default=10.0, gt=0, le=60)


class PortalEmailServiceSettingsPayload(BaseModel):
    enabled: bool = True
    smtp_host: str = Field(max_length=191)
    smtp_port: int = Field(default=465, gt=0, le=65535)
    smtp_username: str = Field(default="", max_length=191)
    smtp_password: str | None = Field(default=None, max_length=500)
    smtp_use_ssl: bool = True
    smtp_use_starttls: bool = False
    smtp_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    from_email: str = Field(max_length=320)
    from_name: str = Field(default="", max_length=191)
    reply_to: str = Field(default="", max_length=320)


class AlipayPaymentServiceSettingsPayload(BaseModel):
    enabled: bool = True
    app_id: str = Field(default="", max_length=191)
    gateway_url: str = Field(default="https://openapi.alipay.com/gateway.do", max_length=500)
    notify_url: str = Field(default="", max_length=500)
    return_url: str = Field(default="", max_length=500)
    private_key: str | None = Field(default=None, max_length=20000)
    public_key: str | None = Field(default=None, max_length=20000)


class ServiceSettingsEmailTestPayload(BaseModel):
    recipient_email: str = Field(min_length=3, max_length=320)


class ServiceSettingsEmailPreviewPayload(BaseModel):
    preview_type: str = Field(default="login", max_length=32)
    locale: str = Field(default="zh-CN", max_length=16)
    from_name: str = Field(default="", max_length=191)
    from_email: str = Field(default="", max_length=320)


class ModelReferenceSyncPayload(BaseModel):
    source_url: str = Field(default="", max_length=500)
    payload: dict[str, Any] | None = None


class WordPressAIRoutingProfilePayload(BaseModel):
    profile_id: str = Field(max_length=64)
    candidate_instance_ids: list[str] = Field(default_factory=list)
    timeout_ms: int = Field(default=30000, ge=1000, le=90000)
    allow_fallback: bool = True
    max_retries: int = Field(default=0, ge=0, le=1)
    note: str = Field(default="", max_length=512)


class WordPressAIRoutingSettingsPayload(BaseModel):
    profiles: list[WordPressAIRoutingProfilePayload] = Field(default_factory=list)


class AbilityModelRuntimeBindingPayload(BaseModel):
    ability_id: str = Field(max_length=64)
    instance_id: str = Field(max_length=191)
    note: str = Field(default="", max_length=512)


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


def _send_support_request_update_notification(
    request: Request,
    *,
    result: dict[str, object],
) -> dict[str, object]:
    request_payload = result.get("request") if isinstance(result.get("request"), dict) else {}
    message_payload = result.get("message") if isinstance(result.get("message"), dict) else {}
    if not isinstance(request_payload, dict) or not isinstance(message_payload, dict):
        return {"attempted": False, "delivered": False, "reason": "invalid_payload"}
    if str(message_payload.get("visibility") or "") != "public":
        return {"attempted": False, "delivered": False, "reason": "internal_message"}
    recipient_email = str(request_payload.get("email") or "").strip()
    if not recipient_email:
        return {"attempted": False, "delivered": False, "reason": "missing_recipient"}
    services = get_cloud_services(request)
    email_sender = services.portal_email_sender or build_portal_email_sender(
        services.settings,
        database_url=services.settings.database_url,
    )
    if email_sender is None:
        return {"attempted": False, "delivered": False, "reason": "email_not_configured"}
    try:
        portal_base_url = resolve_portal_public_base_url(
            services.settings.database_url,
            services.settings,
        ).rstrip("/")
        email_sender.send_support_request_update(
            recipient_email=recipient_email,
            request_id=str(request_payload.get("request_id") or ""),
            title=str(request_payload.get("title") or ""),
            status=str(request_payload.get("status") or ""),
            message_body=str(message_payload.get("body") or ""),
            project_name=services.settings.project_name,
            portal_url=(
                f"{portal_base_url}/portal/support/{request_payload.get('request_id') or ''}"
            ),
            locale=str(request.headers.get("accept-language") or "zh-CN"),
        )
    except (NotImplementedError, AttributeError):
        return {"attempted": False, "delivered": False, "reason": "sender_not_supported"}
    except PortalEmailDeliveryError:
        logger.exception(
            "support request update email delivery failed: request_id=%s trace_id=%s",
            str(request_payload.get("request_id") or ""),
            extract_trace_id(request.headers.get("traceparent", "")),
        )
        return {
            "attempted": True,
            "delivered": False,
            "reason": "delivery_failed",
        }
    return {"attempted": True, "delivered": True, "reason": ""}


def _record_provider_connection_audit(
    request: Request,
    *,
    event_kind: str,
    outcome: str,
    scope_id: str,
    request_payload: ProviderConnectionPayload | None = None,
    result: dict[str, Any] | None = None,
    error_code: str = "",
    message: str = "",
) -> dict[str, Any] | None:
    try:
        return _get_commercial_service(request).record_service_audit_event(
            audit_context=_build_audit_context(request),
            event_kind=event_kind,
            outcome=outcome,
            scope_kind="provider_connection",
            scope_id=scope_id,
            payload_json=_provider_connection_audit_payload(
                request_payload=request_payload,
                result=result,
                error_code=error_code,
                message=message,
            ),
        )
    except Exception:
        return None


def _record_service_setting_audit(
    request: Request,
    *,
    event_kind: str,
    outcome: str,
    setting_id: str,
    result: dict[str, Any] | None = None,
    error_code: str = "",
    message: str = "",
) -> None:
    try:
        _get_commercial_service(request).record_service_audit_event(
            audit_context=_build_audit_context(request),
            event_kind=event_kind,
            outcome=outcome,
            scope_kind="service_setting",
            scope_id=setting_id,
            payload_json={
                "surface": "admin_service_settings",
                "setting_id": setting_id,
                "result": _service_setting_audit_result(result or {}),
                "error_code": error_code,
                "message": message,
                "credential_value_exposure": "none",
            },
        )
    except Exception:
        return


def _service_setting_audit_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "setting_id": str(result.get("setting_id") or ""),
        "enabled": bool(result.get("enabled")),
        "configured": bool(result.get("configured")),
        "status": str(result.get("status") or ""),
        "last_error_code": str(result.get("last_error_code") or ""),
    }


def _provider_connection_audit_payload(
    *,
    request_payload: ProviderConnectionPayload | None,
    result: dict[str, Any] | None,
    error_code: str,
    message: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "surface": "admin_provider_connections",
        "credential_value_exposure": "presence_only",
        "content_exposed": False,
    }
    if request_payload is not None:
        raw = request_payload.model_dump(mode="json")
        payload["request"] = {
            "connection_id": str(raw.get("connection_id") or ""),
            "provider_id": str(raw.get("provider_id") or ""),
            "provider_type": str(raw.get("provider_type") or ""),
            "kind": str(raw.get("kind") or ""),
            "enabled": bool(raw.get("enabled", True)),
            "base_url_present": bool(str(raw.get("base_url") or "").strip()),
            "capability_ids": [str(item) for item in raw.get("capability_ids", []) if str(item)],
            "runtime_profile_ids": [
                str(item) for item in raw.get("runtime_profile_ids", []) if str(item)
            ],
            "credential_provided": bool(str(raw.get("credential") or "").strip()),
            "secret_provided": bool(str(raw.get("secret") or "").strip()),
            "config_present": bool(raw.get("config")),
            "metadata_present": bool(raw.get("metadata")),
        }
    if result:
        payload["result"] = _provider_connection_result_summary(result)
    if error_code:
        payload["error_code"] = error_code
    if message:
        payload["message"] = message[:360]
    return payload


def _provider_connection_result_summary(result: dict[str, Any]) -> dict[str, Any]:
    connection = _dict_value(result.get("connection"))
    if not connection and str(result.get("connection_id") or ""):
        connection = result
    summary: dict[str, Any] = {}
    if connection:
        summary["connection"] = {
            "connection_id": str(connection.get("connection_id") or ""),
            "provider_id": str(connection.get("provider_id") or ""),
            "provider_type": str(connection.get("provider_type") or ""),
            "kind": str(connection.get("kind") or ""),
            "enabled": bool(connection.get("enabled")),
            "configured": bool(connection.get("configured")),
            "status": str(connection.get("status") or ""),
            "capability_ids": [
                str(item) for item in connection.get("capability_ids", []) if str(item)
            ],
            "runtime_profile_ids": [
                str(item) for item in connection.get("runtime_profile_ids", []) if str(item)
            ],
        }
    if "imported" in result or "skipped" in result:
        summary["imported_connection_ids"] = [
            str(_dict_value(item).get("connection_id") or "")
            for item in result.get("imported", [])
            if isinstance(item, dict)
        ]
        summary["skipped"] = [
            {
                "connection_id": str(_dict_value(item).get("connection_id") or ""),
                "reason": str(_dict_value(item).get("reason") or ""),
            }
            for item in result.get("skipped", [])
            if isinstance(item, dict)
        ]
    if "deleted" in result:
        summary["deleted"] = bool(result.get("deleted"))
    if "ok" in result:
        summary["test"] = {
            "ok": bool(result.get("ok")),
            "status": str(result.get("status") or ""),
            "stage": str(result.get("stage") or ""),
            "error_code": str(result.get("error_code") or ""),
            "catalog_model_count": int(_dict_value(result.get("catalog")).get("model_count") or 0),
        }
    return summary


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


def _serialize_wordpress_ai_instance(
    instance: Any,
    model: Any,
    provider: Any | None = None,
) -> dict[str, Any]:
    return {
        "instance_id": str(instance.instance_id or ""),
        "provider_id": str(instance.provider_id or ""),
        "provider_display_name": str(getattr(provider, "display_name", "") or ""),
        "adapter_type": str(getattr(provider, "adapter_type", "") or ""),
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


def _build_ability_model_plugin_routing_projection(
    database_url: str,
    *,
    settings: Any | None = None,
) -> dict[str, Any]:
    provider_model_allowlist = build_provider_model_allowlist(database_url, settings=settings)
    with get_session(database_url) as session:
        repository = CatalogRepository(session)
        instances = repository.list_instances_for_provider()
        models = repository.list_models_by_ids([instance.model_id for instance in instances])
        models_by_id = {model.model_id: model for model in models}
        providers = repository.list_providers_by_ids(
            [instance.provider_id for instance in instances]
        )
        providers_by_id = {provider.provider_id: provider for provider in providers}
        instances_by_id = {instance.instance_id: instance for instance in instances}

        available_instances_by_kind: dict[str, list[dict[str, Any]]] = {
            "text": [],
            "vision": [],
            "image_generation": [],
            "audio_generation": [],
            "embedding": [],
        }
        for instance in instances:
            model = models_by_id.get(instance.model_id)
            if model is None or model.status != "available":
                continue
            if not provider_model_allowlist.allows(
                provider_id=instance.provider_id,
                model_id=instance.model_id,
            ):
                continue
            if model.feature not in available_instances_by_kind:
                continue
            available_instances_by_kind[model.feature].append(
                _serialize_wordpress_ai_instance(
                    instance,
                    model,
                    providers_by_id.get(instance.provider_id),
                )
            )

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
            effective_candidate_instance_ids = []
            for instance_id in candidate_instance_ids:
                if instance_id not in instances_by_id:
                    continue
                instance = instances_by_id[instance_id]
                model = models_by_id.get(instance.model_id)
                if model is None:
                    continue
                if not provider_model_allowlist.allows(
                    provider_id=instance.provider_id,
                    model_id=instance.model_id,
                ):
                    continue
                effective_candidate_instance_ids.append(instance_id)
                candidate_items.append(
                    _serialize_wordpress_ai_instance(
                        instance,
                        model,
                        providers_by_id.get(instance.provider_id),
                    )
                )

            profiles.append(
                {
                    "profile_id": spec.profile_id,
                    "group_id": spec.group_id,
                    "routing_intent": spec.routing_intent,
                    "label": spec.label,
                    "description": spec.description,
                    "tasks": list(spec.tasks),
                    "execution_kind": (
                        profile.execution_kind if profile is not None else spec.execution_kind
                    ),
                    "candidate_instance_ids": effective_candidate_instance_ids,
                    "candidates": candidate_items,
                    "timeout_ms": int(policy.get("timeout_ms") or spec.timeout_ms),
                    "max_timeout_ms": spec.max_timeout_ms,
                    "allow_fallback": bool(policy.get("allow_fallback", spec.allow_fallback)),
                    "max_retries": int(policy.get("max_retries") or spec.max_retries),
                    "revision": str(binding.revision if binding is not None else ""),
                    "updated_at": (
                        binding.updated_at.isoformat()
                        if binding is not None and binding.updated_at is not None
                        else ""
                    ),
                    "selection_policy": selection_policy,
                    "status": (
                        "configured" if effective_candidate_instance_ids else "needs_candidates"
                    ),
                }
            )

    return {
        "contract_version": "cloud-ability-model-routing.v1",
        "surface": "wordpress_ai_connector_routing",
        "projection_kind": "runtime_profile_binding",
        "owner": "cloud_runtime",
        "local_control_plane": "wordpress_plugin",
        "customer_model_selection": False,
        "direct_wordpress_write": False,
        "prompt_or_preset_editor": False,
        "available_text_instances": available_instances_by_kind["text"],
        "available_vision_instances": available_instances_by_kind["vision"],
        "available_image_instances": available_instances_by_kind["image_generation"],
        "available_audio_instances": available_instances_by_kind["audio_generation"],
        "available_embedding_instances": available_instances_by_kind["embedding"],
        "profiles": profiles,
        "boundary": {
            "public_runtime_accepts_raw_model_instance": False,
            "results_write_posture": "suggestion_only",
            "admin_surface": "platform_admin_only",
            "cloud_ability_registry": False,
            "wordpress_ability_truth": "local_plugin",
        },
    }


def _validate_ability_model_plugin_routing_payload(
    database_url: str,
    payload: WordPressAIRoutingSettingsPayload,
    *,
    settings: Any | None = None,
) -> tuple[list[WordPressAIRoutingProfilePayload], str]:
    if not payload.profiles:
        return [], "at least one plugin ability-model routing profile is required"

    known_profile_ids = set(WP_AI_CONNECTOR_PROFILE_SPECS_BY_ID)
    seen_profile_ids: set[str] = set()
    provider_model_allowlist = build_provider_model_allowlist(database_url, settings=settings)
    with get_session(database_url) as session:
        repository = CatalogRepository(session)
        for profile_payload in payload.profiles:
            profile_id = profile_payload.profile_id.strip()
            if profile_id not in known_profile_ids:
                return [], f"unsupported plugin ability-model routing profile: {profile_id}"
            if profile_id in seen_profile_ids:
                return [], f"duplicate plugin ability-model routing profile: {profile_id}"
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
            if (
                profile_payload.timeout_ms
                > WP_AI_CONNECTOR_PROFILE_SPECS_BY_ID[profile_id].max_timeout_ms
            ):
                return [], (
                    f"profile {profile_id} timeout_ms exceeds max "
                    f"{WP_AI_CONNECTOR_PROFILE_SPECS_BY_ID[profile_id].max_timeout_ms}"
                )

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
                spec = WP_AI_CONNECTOR_PROFILE_SPECS_BY_ID[profile_id]
                if model.feature != spec.execution_kind or model.status != "available":
                    return [], (
                        f"profile {profile_id} may only use available "
                        f"{spec.execution_kind} instances"
                    )
                if not provider_model_allowlist.allows(
                    provider_id=instance.provider_id,
                    model_id=instance.model_id,
                ):
                    return [], (
                        f"profile {profile_id} may only use models enabled "
                        f"for provider {instance.provider_id}: {instance.model_id}"
                    )

    return payload.profiles, ""


def _normalize_runtime_id_list(value: object) -> list[str]:
    if isinstance(value, str):
        raw_items: tuple[object, ...] = tuple(value.split(","))
    elif isinstance(value, list):
        raw_items = tuple(value)
    else:
        raw_items = ()
    normalized: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _merge_runtime_id_list(value: object, required_ids: list[str]) -> list[str]:
    merged = _normalize_runtime_id_list(value)
    for required_id in required_ids:
        if required_id and required_id not in merged:
            merged.append(required_id)
    return merged


def _provider_connection_supports_embedding(
    row: ProviderConnection,
    *,
    provider_id: str,
) -> bool:
    config = _dict_value(row.config_json)
    configured = bool(row.secret_ciphertext) or bool(config.get("secretless"))
    if not row.enabled or not configured:
        return False
    row_provider_id = str(config.get("provider_id") or row.connection_id or "").strip().lower()
    kind = str(config.get("kind") or row.provider_type or "").strip().lower()
    capability_ids = _normalize_runtime_id_list(config.get("capability_ids"))
    runtime_profile_ids = _normalize_runtime_id_list(config.get("runtime_profile_ids"))
    if row_provider_id != provider_id.lower():
        return False
    if kind == "embedding_provider":
        return True
    return "embedding" in capability_ids and "embed.default" in runtime_profile_ids


def _embedding_dimensions_for_model(model_id: str, config: dict[str, Any], default: int) -> int:
    configured = config.get("dimensions")
    if isinstance(configured, int) and configured > 0:
        return configured
    try:
        parsed = int(str(configured))
        if parsed > 0:
            return parsed
    except (TypeError, ValueError):
        pass
    normalized_model_id = model_id.lower()
    if "bge-m3" in normalized_model_id:
        return 1024
    if "text-embedding-3-large" in normalized_model_id:
        return 3072
    if "text-embedding-3-small" in normalized_model_id:
        return 1536
    return default


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


@router.post("/accounts/{account_id}/members")
async def upsert_account_member_access(
    request: Request,
    account_id: str,
    payload: AccountMemberAccessPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.upsert_account_member_access(
            account_id=account_id,
            email=payload.email,
            status=payload.status,
            metadata_json=payload.metadata,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="account_membership.upsert",
            error=error,
            account_id=account_id,
            scope_kind="account_membership",
            scope_id=account_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="account member access saved",
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
                    f"Plan version {payload.plan_version_id} is now published. "
                    "Existing subscriptions on this plan use the latest package values."
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


@router.get("/admin/credit-packs")
async def get_admin_credit_pack_catalog(request: Request) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    return build_envelope(
        status="ok",
        message="credit pack catalog loaded",
        data=_get_commercial_service(request).get_admin_credit_pack_catalog(),
        revision="m6",
    )


@router.patch("/admin/credit-packs")
async def update_admin_credit_pack_catalog(
    request: Request,
    payload: CreditPackCatalogPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    payload_items = [item.model_dump() for item in payload.items]
    try:
        result = service.update_admin_credit_pack_catalog(
            items=payload_items,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="payment.credit_pack_catalog.update",
            error=error,
            scope_kind="service_setting",
            scope_id="commercial_credit_pack_catalog",
            payload_json={"items": payload_items},
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="credit pack catalog updated",
        data=result,
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
    runtime_telemetry = runtime_service.get_runtime_telemetry_diagnostics(
        recent_minutes=hosted_model_recent_minutes,
        limit=10,
    )
    runtime_telemetry_projection = {
        "filters": runtime_telemetry.get("filters", {}),
        "generated_at": runtime_telemetry.get("generated_at", ""),
        "totals": runtime_telemetry.get("totals", {}),
        "alert_summary": runtime_telemetry.get("alert_summary", {}),
        "boundary": runtime_telemetry.get("boundary", {}),
    }
    result["runtime_telemetry"] = runtime_telemetry_projection
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


@router.get("/admin/coverage-work-queue")
async def get_admin_coverage_work_queue(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).get_admin_coverage_work_queue(limit=limit)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin coverage work queue loaded",
        data=result,
        revision="m1",
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
    q: str | None = Query(default=None, max_length=128),
    status: str | None = Query(default=None),
    expires_before: datetime | None = Query(default=None),  # noqa: B008
    coverage_state: str | None = Query(default=None),
    package_kind: str | None = Query(default=None),
    top_plan_id: str | None = Query(default=None),
    sort: str = Query(default="created_at", pattern="^(created_at|display_name)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).list_admin_accounts(
            q=q,
            status=status,
            expires_before=expires_before,
            coverage_state=coverage_state,
            package_kind=package_kind,
            top_plan_id=top_plan_id,
            sort=sort,
            offset=offset,
            limit=limit,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin accounts loaded",
        data=result,
        revision="m7",
    )


@router.get("/admin/support-requests")
async def list_admin_support_requests(
    request: Request,
    status: str = Query(default="", max_length=32),
    topic: str = Query(default="", max_length=64),
    q: str = Query(default="", max_length=191),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).list_admin_support_requests(
            status=status,
            topic=topic,
            query=q,
            limit=limit,
            offset=offset,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="support requests loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/support-requests/{request_id}")
async def get_admin_support_request(request: Request, request_id: str) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).get_admin_support_request(request_id=request_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="support request loaded",
        data=result,
        revision="m6",
    )


@router.post("/admin/support-requests/{request_id}/messages")
async def create_admin_support_request_message(
    request: Request,
    request_id: str,
    payload: AdminSupportRequestMessagePayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).create_admin_support_request_message(
            request_id=request_id,
            body=payload.body,
            visibility=payload.visibility,
            audit_context=_build_audit_context(request),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    notification = _send_support_request_update_notification(request, result=result)
    return build_envelope(
        status="ok",
        message="support request message created",
        data={**result, "notification": notification},
        revision="m6",
    )


@router.post("/admin/support-requests/{request_id}/attachments")
async def create_admin_support_request_attachment(
    request: Request,
    request_id: str,
    payload: AdminSupportRequestAttachmentPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).create_admin_support_request_attachment(
            request_id=request_id,
            filename=payload.filename,
            content_type=payload.content_type,
            content_base64=payload.content_base64,
            visibility=payload.visibility,
            message_id=payload.message_id,
            audit_context=_build_audit_context(request),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="support request attachment created",
        data=result,
        revision="m6",
    )


@router.get("/admin/support-requests/{request_id}/attachments/{attachment_id}")
async def get_admin_support_request_attachment(
    request: Request,
    request_id: str,
    attachment_id: str,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).get_admin_support_request_attachment(
            request_id=request_id,
            attachment_id=attachment_id,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="support request attachment loaded",
        data=result,
        revision="m6",
    )


@router.patch("/admin/support-requests/{request_id}")
async def update_admin_support_request(
    request: Request,
    request_id: str,
    payload: AdminSupportRequestUpdatePayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).update_admin_support_request(
            request_id=request_id,
            status=payload.status,
            admin_note=payload.admin_note,
            audit_context=_build_audit_context(request),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="support request updated",
        data={"request": result},
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


@router.get("/admin/portal-users")
async def list_admin_portal_users(
    request: Request,
    q: str | None = Query(default=None, max_length=191),
    source: str | None = Query(default="portal_self_registration", max_length=64),
    status: str | None = Query(default=None, max_length=32),
    package_alias: str | None = Query(default=None, max_length=64),
    qq_bound: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).list_admin_portal_users(
            q=q,
            source=source,
            status=status,
            package_alias=package_alias,
            qq_bound=qq_bound,
            limit=limit,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin portal users loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/portal-users/{principal_id}/audit")
async def get_admin_portal_user_audit(
    request: Request,
    principal_id: str,
    limit: int = Query(default=50, ge=1, le=100),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).get_admin_portal_user_audit(
            principal_id=principal_id,
            limit=limit,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin portal user audit loaded",
        data=result,
        revision="m6",
    )


@router.post("/admin/portal-users/batch-disable")
async def batch_disable_admin_portal_users(
    request: Request,
    payload: PortalUsersBatchDisablePayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.batch_disable_admin_portal_users(
            principal_ids=payload.principal_ids,
            reason=payload.reason,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="portal_user.batch_disable",
            error=error,
            scope_kind="portal_user_batch",
            scope_id=str(_build_audit_context(request).idempotency_key or ""),
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error, request=request)
    totals = _dict_value(result.get("totals")) if isinstance(result, dict) else {}
    return build_envelope(
        status="ok",
        message="admin portal users batch disabled",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="portal_user.batch_disable",
                scope_kind="portal_user_batch",
                scope_id=str(audit_context.idempotency_key or ""),
                outcome="succeeded" if int(totals.get("failed") or 0) == 0 else "partial",
                effective_summary=(
                    f"Batch disable processed {int(totals.get('attempted') or 0)} "
                    f"portal users with {int(totals.get('failed') or 0)} failures."
                ),
            ),
        ),
        revision="m6",
    )


@router.post("/admin/portal-users/{principal_id}/disable")
async def disable_admin_portal_user(
    request: Request,
    principal_id: str,
    payload: PortalUserDisablePayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.disable_admin_portal_user(
            principal_id=principal_id,
            reason=payload.reason,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="portal_user.disable",
            error=error,
            scope_kind="principal",
            scope_id=principal_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin portal user disabled",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="portal_user.disable",
                scope_kind="principal",
                scope_id=principal_id,
                outcome="succeeded",
                effective_summary=(
                    f"Principal {principal_id} was disabled and active portal access was revoked."
                ),
            ),
        ),
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
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="subscription.billing_snapshot.rebuild",
                scope_kind="subscription",
                scope_id=subscription_id,
                outcome="succeeded",
                effective_summary=(
                    f"Billing snapshots for subscription {subscription_id} were rebuilt "
                    "from usage records."
                ),
                account_id=str(_dict_value(result.get("subscription")).get("account_id") or ""),
            ),
        ),
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


@router.get("/admin/service-settings")
async def get_admin_service_settings(request: Request) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = ServiceSettingsAdminService(
        services.settings.database_url,
        services.settings,
    ).get_settings()
    return build_envelope(
        status="ok",
        message="service settings loaded",
        data=result,
        revision="m6",
    )


@router.patch("/admin/service-settings/portal-public")
async def update_admin_portal_public_settings(
    request: Request,
    payload: PortalPublicServiceSettingsPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    try:
        result = ServiceSettingsAdminService(
            services.settings.database_url,
            services.settings,
        ).save_portal_public(payload.model_dump(mode="json"))
    except ServiceSettingsAdminError as error:
        _record_service_setting_audit(
            request,
            event_kind="service_setting.save",
            outcome="error",
            setting_id="portal_public",
            error_code=error.error_code,
            message=error.message,
        )
        return JSONResponse(
            status_code=error.status_code,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                revision="m6",
            ),
        )
    _record_service_setting_audit(
        request,
        event_kind="service_setting.save",
        outcome="succeeded",
        setting_id="portal_public",
        result=result,
    )
    return build_envelope(
        status="ok",
        message="portal public settings saved",
        data=result,
        revision="m6",
    )


@router.patch("/admin/service-settings/qq-login")
async def update_admin_qq_login_settings(
    request: Request,
    payload: QQLoginServiceSettingsPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    try:
        result = ServiceSettingsAdminService(
            services.settings.database_url,
            services.settings,
        ).save_qq_login(payload.model_dump(mode="json"))
    except ServiceSettingsAdminError as error:
        _record_service_setting_audit(
            request,
            event_kind="service_setting.save",
            outcome="error",
            setting_id="portal_qq_login",
            error_code=error.error_code,
            message=error.message,
        )
        return JSONResponse(
            status_code=error.status_code,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                revision="m6",
            ),
        )
    _record_service_setting_audit(
        request,
        event_kind="service_setting.save",
        outcome="succeeded",
        setting_id="portal_qq_login",
        result=result,
    )
    return build_envelope(
        status="ok",
        message="QQ login settings saved",
        data=result,
        revision="m6",
    )


@router.post("/admin/service-settings/qq-login/test")
async def test_admin_qq_login_settings(request: Request) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = ServiceSettingsAdminService(
        services.settings.database_url,
        services.settings,
    ).test_qq_login()
    _record_service_setting_audit(
        request,
        event_kind="service_setting.test",
        outcome="succeeded" if result.get("status") == "ready" else "error",
        setting_id="portal_qq_login",
        result=result,
        error_code="" if result.get("status") == "ready" else "service_settings.qq_not_ready",
        message=str(result.get("message") or ""),
    )
    return build_envelope(
        status="ok",
        message="QQ login settings tested",
        data=result,
        revision="m6",
    )


@router.patch("/admin/service-settings/email")
async def update_admin_portal_email_settings(
    request: Request,
    payload: PortalEmailServiceSettingsPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    try:
        result = ServiceSettingsAdminService(
            services.settings.database_url,
            services.settings,
        ).save_email(payload.model_dump(mode="json"))
    except ServiceSettingsAdminError as error:
        _record_service_setting_audit(
            request,
            event_kind="service_setting.save",
            outcome="error",
            setting_id="portal_email",
            error_code=error.error_code,
            message=error.message,
        )
        return JSONResponse(
            status_code=error.status_code,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                revision="m6",
            ),
        )
    _record_service_setting_audit(
        request,
        event_kind="service_setting.save",
        outcome="succeeded",
        setting_id="portal_email",
        result=result,
    )
    return build_envelope(
        status="ok",
        message="portal email settings saved",
        data=result,
        revision="m6",
    )


@router.post("/admin/service-settings/email/test")
async def test_admin_portal_email_settings(
    request: Request,
    payload: ServiceSettingsEmailTestPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    try:
        result = ServiceSettingsAdminService(
            services.settings.database_url,
            services.settings,
        ).test_email(
            recipient_email=payload.recipient_email,
            project_name=services.settings.project_name,
        )
    except ServiceSettingsAdminError as error:
        _record_service_setting_audit(
            request,
            event_kind="service_setting.test",
            outcome="error",
            setting_id="portal_email",
            error_code=error.error_code,
            message=error.message,
        )
        return JSONResponse(
            status_code=error.status_code,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                revision="m6",
            ),
        )
    _record_service_setting_audit(
        request,
        event_kind="service_setting.test",
        outcome="succeeded",
        setting_id="portal_email",
        result=result,
    )
    return build_envelope(
        status="ok",
        message="portal email settings tested",
        data=result,
        revision="m6",
    )


@router.post("/admin/service-settings/email/preview")
async def preview_admin_portal_email_settings(
    request: Request,
    payload: ServiceSettingsEmailPreviewPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = ServiceSettingsAdminService(
        services.settings.database_url,
        services.settings,
    ).preview_email(
        preview_type=payload.preview_type,
        project_name=services.settings.project_name,
        locale=payload.locale,
        from_name=payload.from_name,
        from_email=payload.from_email,
    )
    return build_envelope(
        status="ok",
        message="portal email preview generated",
        data=result,
        revision="m6",
    )


@router.patch("/admin/service-settings/alipay-payment")
async def update_admin_alipay_payment_settings(
    request: Request,
    payload: AlipayPaymentServiceSettingsPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    try:
        result = ServiceSettingsAdminService(
            services.settings.database_url,
            services.settings,
        ).save_alipay_payment(payload.model_dump(mode="json"))
    except ServiceSettingsAdminError as error:
        _record_service_setting_audit(
            request,
            event_kind="service_setting.save",
            outcome="error",
            setting_id="payment_alipay",
            error_code=error.error_code,
            message=error.message,
        )
        return JSONResponse(
            status_code=error.status_code,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                revision="m6",
            ),
        )
    _record_service_setting_audit(
        request,
        event_kind="service_setting.save",
        outcome="succeeded",
        setting_id="payment_alipay",
        result=result,
    )
    return build_envelope(
        status="ok",
        message="Alipay payment settings saved",
        data=result,
        revision="m6",
    )


@router.post("/admin/service-settings/alipay-payment/test")
async def test_admin_alipay_payment_settings(request: Request) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    try:
        result = ServiceSettingsAdminService(
            services.settings.database_url,
            services.settings,
        ).test_alipay_payment()
    except ServiceSettingsAdminError as error:
        _record_service_setting_audit(
            request,
            event_kind="service_setting.test",
            outcome="error",
            setting_id="payment_alipay",
            error_code=error.error_code,
            message=error.message,
        )
        return JSONResponse(
            status_code=error.status_code,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                revision="m6",
            ),
        )
    _record_service_setting_audit(
        request,
        event_kind="service_setting.test",
        outcome="succeeded" if result.get("status") == "ready" else "error",
        setting_id="payment_alipay",
        result=result,
        error_code="" if result.get("status") == "ready" else "service_settings.alipay_not_ready",
        message=str(result.get("message") or ""),
    )
    return build_envelope(
        status="ok",
        message="Alipay payment settings tested",
        data=result,
        revision="m6",
    )


@router.get("/admin/provider-connections")
async def list_admin_provider_connections(request: Request) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = ProviderConnectionAdminService(
        services.settings.database_url,
        services.settings,
    ).list_connections()
    return build_envelope(
        status="ok",
        message="provider connections loaded",
        data=result,
        revision="m6",
    )


@router.post("/admin/provider-connections")
async def create_admin_provider_connection(
    request: Request,
    payload: ProviderConnectionPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    try:
        result = ProviderConnectionAdminService(
            services.settings.database_url,
            services.settings,
        ).save_connection(payload.model_dump(mode="json"))
    except ProviderConnectionAdminError as error:
        _record_provider_connection_audit(
            request,
            event_kind="provider_connection.save",
            outcome="error",
            scope_id=str(payload.connection_id or payload.provider_id or ""),
            request_payload=payload,
            error_code=error.error_code,
            message=error.message,
        )
        return JSONResponse(
            status_code=error.status_code,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                revision="m6",
            ),
        )
    audit_event = _record_provider_connection_audit(
        request,
        event_kind="provider_connection.save",
        outcome="succeeded",
        scope_id=str(result.get("connection_id") or ""),
        request_payload=payload,
        result=result,
    )
    return build_envelope(
        status="ok",
        message="provider connection saved",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="provider_connection.save",
                scope_kind="provider_connection",
                scope_id=str(result.get("connection_id") or ""),
                outcome="succeeded",
                effective_summary=(
                    f"Provider connection {str(result.get('connection_id') or '')} was saved."
                ),
                audit_event=audit_event,
            ),
        ),
        revision="m6",
    )


@router.patch("/admin/provider-connections/{connection_id}")
async def update_admin_provider_connection(
    request: Request,
    connection_id: str,
    payload: ProviderConnectionPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    try:
        result = ProviderConnectionAdminService(
            services.settings.database_url,
            services.settings,
        ).save_connection(payload.model_dump(mode="json"), connection_id=connection_id)
    except ProviderConnectionAdminError as error:
        _record_provider_connection_audit(
            request,
            event_kind="provider_connection.save",
            outcome="error",
            scope_id=connection_id,
            request_payload=payload,
            error_code=error.error_code,
            message=error.message,
        )
        return JSONResponse(
            status_code=error.status_code,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                revision="m6",
            ),
        )
    audit_event = _record_provider_connection_audit(
        request,
        event_kind="provider_connection.save",
        outcome="succeeded",
        scope_id=str(result.get("connection_id") or connection_id),
        request_payload=payload,
        result=result,
    )
    return build_envelope(
        status="ok",
        message="provider connection saved",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="provider_connection.save",
                scope_kind="provider_connection",
                scope_id=str(result.get("connection_id") or connection_id),
                outcome="succeeded",
                effective_summary=(
                    "Provider connection "
                    f"{str(result.get('connection_id') or connection_id)} was saved."
                ),
                audit_event=audit_event,
            ),
        ),
        revision="m6",
    )


@router.post("/admin/provider-connections/preview-catalog")
async def preview_admin_provider_connection_catalog(
    request: Request,
    payload: ProviderConnectionPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    try:
        result = ProviderConnectionAdminService(
            services.settings.database_url,
            services.settings,
        ).preview_catalog(payload.model_dump(mode="json"))
    except ProviderConnectionAdminError as error:
        return JSONResponse(
            status_code=error.status_code,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                revision="m6",
            ),
        )
    return build_envelope(
        status="ok",
        message="provider catalog preview loaded",
        data=result,
        revision="m6",
    )


@router.delete("/admin/provider-connections/{connection_id}")
async def delete_admin_provider_connection(request: Request, connection_id: str) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    try:
        result = ProviderConnectionAdminService(
            services.settings.database_url,
            services.settings,
        ).delete_connection(connection_id)
    except ProviderConnectionAdminError as error:
        _record_provider_connection_audit(
            request,
            event_kind="provider_connection.delete",
            outcome="error",
            scope_id=connection_id,
            error_code=error.error_code,
            message=error.message,
        )
        return JSONResponse(
            status_code=error.status_code,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                revision="m6",
            ),
        )
    audit_event = _record_provider_connection_audit(
        request,
        event_kind="provider_connection.delete",
        outcome="succeeded",
        scope_id=connection_id,
        result=result,
    )
    return build_envelope(
        status="ok",
        message="provider connection deleted",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="provider_connection.delete",
                scope_kind="provider_connection",
                scope_id=connection_id,
                outcome="succeeded",
                effective_summary=f"Provider connection {connection_id} was deleted.",
                audit_event=audit_event,
            ),
        ),
        revision="m6",
    )


@router.post("/admin/provider-connections/{connection_id}/test")
async def test_admin_provider_connection(request: Request, connection_id: str) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    try:
        result = ProviderConnectionAdminService(
            services.settings.database_url,
            services.settings,
        ).test_connection(connection_id)
    except ProviderConnectionAdminError as error:
        _record_provider_connection_audit(
            request,
            event_kind="provider_connection.test",
            outcome="error",
            scope_id=connection_id,
            error_code=error.error_code,
            message=error.message,
        )
        return JSONResponse(
            status_code=error.status_code,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                revision="m6",
            ),
        )
    audit_event = _record_provider_connection_audit(
        request,
        event_kind="provider_connection.test",
        outcome="succeeded" if result.get("ok") else "error",
        scope_id=connection_id,
        result=result,
        error_code=str(result.get("error_code") or ""),
        message=str(result.get("message") or ""),
    )
    return build_envelope(
        status="ok" if result.get("ok") else "error",
        message=str(result.get("message") or "provider connection tested"),
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="provider_connection.test",
                scope_kind="provider_connection",
                scope_id=connection_id,
                outcome="succeeded" if result.get("ok") else "error",
                effective_summary=str(result.get("message") or "Provider connection was tested."),
                audit_event=audit_event,
            ),
        ),
        revision="m6",
    )


@router.get("/admin/model-references")
async def list_admin_model_references(
    request: Request,
    provider_id: str = "",
    model_ids: str = "",
    feature: str = "",
    include_deprecated: bool = True,
    search: str = "",
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = ModelReferenceService(services.settings.database_url).list_references(
        provider_id=provider_id,
        model_ids=[item.strip() for item in model_ids.split(",") if item.strip()],
        feature=feature,
        include_deprecated=include_deprecated,
        search=search,
        limit=limit,
        offset=offset,
    )
    return build_envelope(
        status="ok",
        message="model references loaded",
        data=result,
        revision="m6",
    )


@router.post("/admin/model-references/sync")
async def sync_admin_model_references(
    request: Request,
    payload: ModelReferenceSyncPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    try:
        result = ModelReferenceService(services.settings.database_url).sync_models_dev(
            payload=payload.payload,
            source_url=payload.source_url,
        )
    except ModelReferenceError as error:
        return JSONResponse(
            status_code=error.status_code,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                revision="m6",
            ),
        )
    return build_envelope(
        status="ok",
        message="model references synced",
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
            providers=resolve_live_provider_adapters(
                services.settings,
                base_providers=services.providers,
                include_enabled_connections=True,
            ),
            database_url=services.settings.database_url,
        ),
        revision="m6",
    )


@router.get("/admin/ability-models/runtime-projection")
async def get_admin_ability_model_runtime_projection(request: Request) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    return build_envelope(
        status="ok",
        message="Ability model runtime projection loaded",
        data=build_admin_ability_model_runtime_projection(
            services.settings,
            providers=resolve_live_provider_adapters(
                services.settings,
                base_providers=services.providers,
                include_enabled_connections=True,
            ),
            database_url=services.settings.database_url,
        ),
        revision="m6",
    )


@router.post("/admin/ability-models/runtime-binding")
async def update_admin_ability_model_runtime_binding(
    request: Request,
    payload: AbilityModelRuntimeBindingPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    ability_id = payload.ability_id.strip()
    instance_id = payload.instance_id.strip()
    if ability_id != "site_knowledge_embedding":
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                status="error",
                error_code="ability_model_runtime_binding.unsupported_ability",
                message="Only Site Knowledge embedding runtime binding is supported.",
                revision="m6",
            ),
        )
    if not instance_id:
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                status="error",
                error_code="ability_model_runtime_binding.invalid_instance",
                message="A runtime model instance is required.",
                revision="m6",
            ),
        )

    connection_id = ""
    provider_id = ""
    model_id = ""
    with get_session(services.settings.database_url) as session:
        repository = CatalogRepository(session)
        instances = repository.list_instances_by_ids([instance_id])
        instance = instances[0] if instances else None
        if instance is None:
            return JSONResponse(
                status_code=400,
                content=build_envelope(
                    status="error",
                    error_code="ability_model_runtime_binding.unknown_instance",
                    message="The selected runtime model instance does not exist.",
                    revision="m6",
                ),
            )
        model = repository.get_model(instance.model_id)
        if model is None or model.status != "available" or model.feature != "embedding":
            return JSONResponse(
                status_code=400,
                content=build_envelope(
                    status="error",
                    error_code="ability_model_runtime_binding.invalid_model",
                    message="Site Knowledge can only use available embedding model instances.",
                    revision="m6",
                ),
            )

        provider_id = str(instance.provider_id or "").strip()
        model_id = str(instance.model_id or "").strip()
        connections = list(
            session.scalars(
                select(ProviderConnection)
                .where(ProviderConnection.enabled.is_(True))
                .order_by(ProviderConnection.connection_id.asc())
            )
        )
        connection = next(
            (
                row
                for row in connections
                if _provider_connection_supports_embedding(row, provider_id=provider_id)
            ),
            None,
        )
        if connection is None:
            return JSONResponse(
                status_code=400,
                content=build_envelope(
                    status="error",
                    error_code="ability_model_runtime_binding.missing_provider_connection",
                    message=(
                        "The selected embedding model requires an enabled provider "
                        "connection with embedding capability."
                    ),
                    revision="m6",
                ),
            )

        config = dict(_dict_value(connection.config_json))
        config["provider_id"] = provider_id
        config["kind"] = str(config.get("kind") or connection.provider_type or provider_id)
        config["model_id"] = model_id
        config["capability_ids"] = _merge_runtime_id_list(
            config.get("capability_ids"),
            ["embedding"],
        )
        config["runtime_profile_ids"] = _merge_runtime_id_list(
            config.get("runtime_profile_ids"),
            ["embed.default"],
        )
        config["dimensions"] = _embedding_dimensions_for_model(
            model_id,
            config,
            services.settings.site_knowledge_embedding_dimensions,
        )
        config["managed_surface"] = "admin_ability_model_runtime_binding"
        if payload.note.strip():
            config["operator_note"] = payload.note.strip()
        connection.config_json = config
        connection.status = "configured"
        connection.updated_at = datetime.now(UTC)
        connection_id = str(connection.connection_id or "").strip()
        session.commit()

    apply_provider_connection_runtime_settings(services.settings)
    audit_event = None
    try:
        audit_event = _get_commercial_service(request).record_service_audit_event(
            audit_context=_build_audit_context(request),
            event_kind="ability_model_runtime_binding.update",
            outcome="succeeded",
            scope_kind="runtime_profile",
            scope_id="embed.default",
            payload_json={
                "surface": "admin_ability_model_runtime_projection",
                "ability_id": ability_id,
                "provider_id": provider_id,
                "model_id": model_id,
                "instance_id": instance_id,
                "connection_id": connection_id,
                "credential_value_exposure": "none",
                "content_exposed": False,
            },
        )
    except Exception:
        audit_event = None

    result = build_admin_ability_model_runtime_projection(
        services.settings,
        providers=resolve_live_provider_adapters(
            services.settings,
            base_providers=services.providers,
            include_enabled_connections=True,
        ),
        database_url=services.settings.database_url,
    )
    return build_envelope(
        status="ok",
        message="Ability model runtime binding saved",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="ability_model_runtime_binding.update",
                scope_kind="runtime_profile",
                scope_id="embed.default",
                outcome="succeeded",
                effective_summary="Site Knowledge embedding runtime model was updated.",
                audit_event=audit_event,
            ),
        ),
        revision="m6",
    )


@router.get("/admin/ability-models/plugin-routing")
async def get_admin_ability_model_plugin_routing(request: Request) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    return build_envelope(
        status="ok",
        message="Plugin ability-model routing loaded",
        data=_build_ability_model_plugin_routing_projection(
            services.settings.database_url,
            settings=services.settings,
        ),
        revision="m6",
    )


@router.post("/admin/ability-models/plugin-routing")
async def update_admin_ability_model_plugin_routing(
    request: Request,
    payload: WordPressAIRoutingSettingsPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    profiles, error_message = _validate_ability_model_plugin_routing_payload(
        services.settings.database_url,
        payload,
        settings=services.settings,
    )
    if error_message:
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                status="error",
                error_code="ability_model_plugin_routing.invalid_profile",
                message=error_message,
                revision="m6",
            ),
        )

    revision = f"ability-model-routing-admin-{int(datetime.now(UTC).timestamp())}"
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
                execution_kind=spec.execution_kind,
                default_policy_json={
                    "allow_fallback": profile_payload.allow_fallback,
                    "max_retries": profile_payload.max_retries,
                    "timeout_ms": profile_payload.timeout_ms,
                    "managed_surface": "wordpress_ai_connector",
                    "task_group": spec.group_id,
                    "routing_intent": spec.routing_intent,
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
                    "routing_intent": spec.routing_intent,
                    "operator_note": profile_payload.note.strip(),
                },
                revision=revision,
            )
        session.commit()

    audit_event = None
    try:
        audit_event = _get_commercial_service(request).record_service_audit_event(
            audit_context=_build_audit_context(request),
            event_kind="ability_model_plugin_routing.update",
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

    result = _build_ability_model_plugin_routing_projection(
        services.settings.database_url,
        settings=services.settings,
    )
    return build_envelope(
        status="ok",
        message="Plugin ability-model routing saved",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="ability_model_plugin_routing.update",
                scope_kind="runtime_profile",
                scope_id="wordpress_ai_connector",
                outcome="succeeded",
                effective_summary="Plugin ability-model routing was updated.",
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


@router.get("/admin/runtime-telemetry")
@router.get("/runtime/diagnostics/runtime-telemetry")
async def get_runtime_telemetry_diagnostics(
    request: Request,
    site_id: str | None = Query(default=None),
    recent_minutes: int = Query(default=60, ge=1, le=10080),
    limit: int = Query(default=20, ge=1, le=100),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = RuntimeService(services.settings.database_url).get_runtime_telemetry_diagnostics(
        site_id=site_id,
        recent_minutes=recent_minutes,
        limit=limit,
    )
    return build_envelope(
        status="ok",
        message="runtime telemetry diagnostics loaded",
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
