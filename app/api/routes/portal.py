from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.adapters.notifications.base import PortalEmailDeliveryError
from app.api.auth import (
    AUTHORIZATION_HEADER,
    PortalBearerTokenError,
    enforce_portal_login_code_request_rate_limit,
    get_cloud_services,
    resolve_portal_login_code_ttl_seconds,
)
from app.api.browser_security import enforce_browser_same_origin
from app.api.envelope import build_envelope
from app.api.portal_locale import resolve_portal_email_locale
from app.api.portal_session import (
    COOKIE_SITE_ID,
    build_new_portal_session_metadata,
    clear_portal_session_cookies,
    portal_cookie_secure,
    portal_json_error,
    resolve_portal_request_context,
    serialize_portal_session,
    set_portal_session_cookies,
)
from app.api.routes.service import (
    _build_audit_context,
    _get_commercial_service,
    _service_error_response,
)
from app.domain.advisor.service import InternalAIAdvisorService
from app.domain.agent_workflow_metadata import (
    MEDIA_DERIVATIVE_WORKFLOW_ID,
    get_agent_handoff_metadata,
    get_workflow_metadata,
)
from app.domain.commercial.audit_context import ServiceAuditContext
from app.domain.commercial.customer_api_keys import (
    build_customer_api_key,
    serialize_portal_site_key,
)
from app.domain.commercial.errors import CommercialServiceError
from app.domain.commercial.identity import SITE_ADMIN_SITE_KEY_WRITE_ROLES
from app.domain.hosted_model_defaults import FREE_GPT55_MODEL_ID
from app.domain.media_derivatives.metrics import MediaDerivativeObservabilityService
from app.domain.observability.plugin_events import PluginObservabilityService
from app.domain.observability.site_monitoring_overview import SiteMonitoringOverviewService
from app.domain.site_knowledge.metrics import SiteKnowledgeObservabilityService
from app.domain.usage.service import UsageService

router = APIRouter(prefix="/portal/v1", tags=["portal"])


class PortalSiteKeyPayload(BaseModel):
    label: str = ""
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PortalSessionSitePayload(BaseModel):
    site_id: str = ""


class PortalCreateSitePayload(BaseModel):
    account_id: str = ""
    site_name: str = ""
    wordpress_url: str = ""


class PortalLoginCodeRequestPayload(BaseModel):
    email: str = ""
    locale: str = ""


class PortalLoginCodeVerifyPayload(BaseModel):
    email: str = ""
    code: str = ""


class PortalAIInsightAnalyzePayload(BaseModel):
    force_refresh: bool = False


def _object_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _dict_value(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _build_portal_audit_context(request: Request, site_admin_ref: str) -> ServiceAuditContext:
    audit_context = _build_audit_context(request)
    audit_context.actor_kind = "site_admin"
    audit_context.actor_ref = site_admin_ref
    return audit_context


def _authorize_portal_site_access(
    request: Request,
    *,
    site_id: str,
    site_admin_ref: str,
    required_roles: set[str] | None = None,
) -> dict[str, object] | JSONResponse:
    try:
        return _get_commercial_service(request).resolve_portal_site_access(
            site_id=site_id,
            site_admin_ref=site_admin_ref,
            required_roles=required_roles,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)


def _portal_route_envelope(
    *,
    message: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    return build_envelope(
        status="ok",
        message=message,
        data=data,
        revision="m6",
    )


def _portal_session_cleared_response() -> JSONResponse:
    response = JSONResponse(
        status_code=200,
        content=_portal_route_envelope(
            message="portal session cleared",
            data={},
        ),
    )
    clear_portal_session_cookies(response)
    return response


def _portal_write_guard(request: Request) -> JSONResponse | None:
    return None


def _portal_same_origin_guard(
    request: Request,
    *,
    always: bool = False,
) -> JSONResponse | None:
    if not always:
        has_header_auth = any(
            [
                str(request.headers.get(AUTHORIZATION_HEADER) or "").strip(),
            ]
        )
        if has_header_auth:
            return None
    try:
        enforce_browser_same_origin(request)
    except PortalBearerTokenError as error:
        return portal_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    return None


def _csv_set(value: str) -> set[str]:
    return {item.strip() for item in str(value or "").split(",") if item.strip()}


def _get_portal_advisor_service(request: Request) -> InternalAIAdvisorService:
    services = get_cloud_services(request)
    return InternalAIAdvisorService(
        services.settings.database_url,
        providers=services.providers,
        allowed_summarizer_provider_ids=_csv_set(
            services.settings.internal_ops_summarizer_provider_allowlist
        ),
    )


def _resolve_portal_ai_provider_id(request: Request) -> str:
    services = get_cloud_services(request)
    allowed_provider_ids = [
        provider_id
        for provider_id in _csv_set(services.settings.internal_ops_summarizer_provider_allowlist)
        if provider_id in services.providers
    ]
    return sorted(allowed_provider_ids)[0] if allowed_provider_ids else ""


def _portal_ai_disclosure(disclosure: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": str(disclosure.get("version") or ""),
        "content_origin": str(disclosure.get("content_origin") or ""),
        "generated_by_ai": bool(disclosure.get("generated_by_ai")),
        "ai_assisted": bool(disclosure.get("ai_assisted")),
        "visible_label_required": bool(disclosure.get("visible_label_required")),
        "visible_label": str(disclosure.get("visible_label") or ""),
        "brand_label": str(disclosure.get("brand_label") or "Magick AI"),
        "visible_notice": str(disclosure.get("visible_notice") or ""),
        "review_status": str(disclosure.get("review_status") or ""),
        "reviewed_at": str(disclosure.get("reviewed_at") or ""),
        "source_generation_mode": str(disclosure.get("source_generation_mode") or ""),
    }


def _portal_ai_generation(generation: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": str(generation.get("mode") or ""),
        "error_code": str(generation.get("error_code") or ""),
        "cache_status": str(generation.get("cache_status") or ""),
        "cache_hit": bool(generation.get("cache_hit")),
        "cache_generated_at": str(generation.get("cache_generated_at") or ""),
        "cache_expires_at": str(generation.get("cache_expires_at") or ""),
    }


def _portal_ai_summary(summary: dict[str, Any]) -> dict[str, Any]:
    generation = summary.get("generation") if isinstance(summary.get("generation"), dict) else {}
    disclosure = (
        summary.get("ai_disclosure") if isinstance(summary.get("ai_disclosure"), dict) else {}
    )
    return {
        "summary_version": str(summary.get("summarizer_version") or "internal-ops-summarizer-v1"),
        "scope": str(summary.get("scope") or ""),
        "status": str(summary.get("status") or ""),
        "severity": str(summary.get("severity") or ""),
        "headline": str(summary.get("headline") or ""),
        "operator_summary": str(summary.get("operator_summary") or ""),
        "operator_next_step": str(summary.get("operator_next_step") or ""),
        "safety_note": str(summary.get("safety_note") or ""),
        "generated_at": str(
            summary.get("generated_at")
            or (disclosure or {}).get("generated_at")
            or (generation or {}).get("cache_generated_at")
            or ""
        ),
        "generation": _portal_ai_generation(generation or {}),
        "ai_disclosure": _portal_ai_disclosure(disclosure or {}),
        "agent_handoff": _portal_ai_agent_handoff(summary.get("agent_handoff")),
        "agent_registry_metadata": _portal_ai_agent_registry_metadata(summary.get("agent_handoff")),
    }


def _portal_ai_history_item(item: dict[str, Any]) -> dict[str, Any]:
    generation = item.get("generation") if isinstance(item.get("generation"), dict) else {}
    disclosure = item.get("ai_disclosure") if isinstance(item.get("ai_disclosure"), dict) else {}
    return {
        "site_id": str(item.get("site_id") or ""),
        "scope": str(item.get("scope") or ""),
        "status": str(item.get("status") or ""),
        "severity": str(item.get("severity") or ""),
        "headline": str(item.get("headline") or ""),
        "operator_summary": str(item.get("operator_summary") or ""),
        "operator_next_step": str(item.get("operator_next_step") or ""),
        "generated_at": str(item.get("generated_at") or ""),
        "fresh_until": str(item.get("fresh_until") or ""),
        "is_stale": bool(item.get("is_stale")),
        "generation": _portal_ai_generation(generation or {}),
        "ai_disclosure": _portal_ai_disclosure(disclosure or {}),
        "agent_handoff": _portal_ai_agent_handoff(item.get("agent_handoff")),
        "agent_registry_metadata": _portal_ai_agent_registry_metadata(item.get("agent_handoff")),
    }


def _portal_ai_agent_registry_metadata(value: Any) -> dict[str, Any]:
    handoff = _portal_ai_agent_handoff(value)
    agent_id = handoff.get("agent_id", "")
    if not agent_id:
        return {}
    return _portal_ai_agent_handoff(
        get_agent_handoff_metadata(
            agent_id,
            agent_role=handoff.get("agent_role") or None,
        )
    )


def _portal_ai_agent_handoff(value: Any) -> dict[str, Any]:
    handoff = value if isinstance(value, dict) else {}
    return {
        "agent_id": str(handoff.get("agent_id") or ""),
        "agent_version": str(handoff.get("agent_version") or ""),
        "agent_role": str(handoff.get("agent_role") or ""),
        "handoff_type": str(handoff.get("handoff_type") or ""),
        "handoff_owner": str(handoff.get("handoff_owner") or ""),
        "requires_operator_review": bool(handoff.get("requires_operator_review")),
        "direct_wordpress_write": bool(handoff.get("direct_wordpress_write")),
        "execution_pattern": str(handoff.get("execution_pattern") or ""),
        "storage_mode": str(handoff.get("storage_mode") or ""),
        "allowed_actions": [
            str(item)
            for item in _object_list(handoff.get("allowed_actions"))[:6]
            if str(item).strip()
        ],
        "stop_conditions": [
            str(item)
            for item in _object_list(handoff.get("stop_conditions"))[:6]
            if str(item).strip()
        ],
        "forbidden_actions": [
            str(item)
            for item in _object_list(handoff.get("forbidden_actions"))[:8]
            if str(item).strip()
        ],
        "fail_closed_behavior": str(handoff.get("fail_closed_behavior") or ""),
    }


def _portal_ai_safety_contract() -> dict[str, bool]:
    return {
        "manual_trigger_required": True,
        "prompt_saved": False,
        "raw_payload_saved": False,
        "wordpress_write_allowed": False,
        "provider_visible": False,
        "model_visible": False,
        "token_usage_visible": False,
        "cost_visible": False,
        "cache_key_visible": False,
        "customer_article_generation_allowed": False,
    }


def _resolve_portal_site_summary(
    request: Request,
    *,
    site_id: str,
    site_admin_ref: str,
) -> dict[str, object] | JSONResponse:
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        site_admin_ref=site_admin_ref,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        service = _get_commercial_service(request)
        policy = service.inspect_commercial_policy(site_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    subscription = _dict_value(policy.get("subscription"))
    subscription_metadata = _dict_value(subscription.get("metadata"))
    return {
        "site_id": site_id,
        "account_id": str(access.get("account_id") or ""),
        "site_admin_ref": site_admin_ref,
        "identity_type": str(access.get("identity_type") or ""),
        "allowed_actions": [
            str(action)
            for action in _object_list(access.get("allowed_actions"))
            if str(action).strip()
        ],
        "role": str(access.get("role") or ""),
        "site": policy.get("site"),
        "covered_by_subscription_id": str(subscription.get("subscription_id") or ""),
        "subscription_status": str(subscription.get("status") or ""),
        "package_alias": str(subscription_metadata.get("package_alias") or ""),
        "coverage": {
            "subscription": policy.get("subscription"),
            "plan_version": policy.get("plan_version"),
            "entitlement_snapshot": policy.get("entitlement_snapshot"),
        },
        "generated_at": policy.get("generated_at"),
    }


@router.post("/auth/code/request")
async def request_portal_login_code(
    request: Request,
    payload: PortalLoginCodeRequestPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    email = payload.email.strip()
    locale = resolve_portal_email_locale(request, payload.locale)
    if not email:
        return portal_json_error(
            request,
            status_code=400,
            error_code="portal.login_invalid",
            message="email is required",
        )
    try:
        enforce_portal_login_code_request_rate_limit(request, email=email)
    except PortalBearerTokenError as error:
        return portal_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    ttl_seconds = resolve_portal_login_code_ttl_seconds(get_cloud_services(request).settings)
    email_sender = get_cloud_services(request).portal_email_sender
    environment = str(get_cloud_services(request).settings.environment or "").strip().lower()
    allow_development_code = environment in {"development", "test"} and (
        str(request.headers.get("x-magick-dev-login-code") or "").strip() == "1"
        or str(request.headers.get("x-magick-debug-portal-link") or "").strip() == "1"
    )
    try:
        issued = _get_commercial_service(request).issue_portal_login_code(
            email=email,
            ttl_seconds=ttl_seconds,
        )
    except CommercialServiceError as error:
        if error.error_code in {
            "service.portal_email_not_found",
            "service.site_admin_email_not_found",
        }:
            return _portal_route_envelope(
                message="portal login code request accepted",
                data={
                    "email": email.strip().lower(),
                    "delivery": "email",
                    "expires_in_seconds": ttl_seconds,
                    "code": "",
                },
            )
        return _service_error_response(error, request=request)
    if email_sender is not None:
        try:
            email_sender.send_login_code(
                recipient_email=str(issued.get("email") or ""),
                site_admin_ref=str(issued.get("site_admin_ref") or ""),
                code=str(issued.get("code") or ""),
                expires_in_seconds=ttl_seconds,
                project_name=get_cloud_services(request).settings.project_name,
                locale=locale,
            )
        except PortalEmailDeliveryError as error:
            return portal_json_error(
                request,
                status_code=502,
                error_code="portal.email_delivery_failed",
                message=str(error),
            )
    return _portal_route_envelope(
        message="portal login code issued",
        data={
            "email": str(issued.get("email") or ""),
            "delivery": ("development_code" if allow_development_code else "email"),
            "expires_in_seconds": ttl_seconds,
            "code": (str(issued.get("code") or "") if allow_development_code else ""),
        },
    )


@router.post("/auth/code/verify")
async def verify_portal_login_code(
    request: Request,
    payload: PortalLoginCodeVerifyPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    email = payload.email.strip()
    code = payload.code.strip()
    if not email or not code:
        return portal_json_error(
            request,
            status_code=400,
            error_code="auth.portal_login_code_required",
            message="portal login code and email are required",
        )
    try:
        verified = _get_commercial_service(request).verify_portal_login_code(
            email=email,
            code=code,
            max_attempts=max(
                1,
                int(get_cloud_services(request).settings.portal_login_code_max_attempts or 0),
            ),
        )
        site_admin_ref = str(verified.get("site_admin_ref") or "")
        data = serialize_portal_session(
            request,
            site_admin_ref=site_admin_ref,
            site_id="",
            strict_site=False,
            session_metadata=build_new_portal_session_metadata(request),
        )
    except CommercialServiceError as error:
        if error.error_code == "service.portal_login_code_invalid":
            return portal_json_error(
                request,
                status_code=401,
                error_code="auth.portal_login_code_invalid",
                message="portal login code is invalid or expired",
            )
        return _service_error_response(error, request=request)

    response = JSONResponse(
        status_code=200,
        content=_portal_route_envelope(
            message="portal session created",
            data=data,
        ),
    )
    set_portal_session_cookies(
        request,
        response,
        site_admin_ref=site_admin_ref,
        site_id="",
    )
    return response


@router.get("/session")
async def get_portal_session(request: Request) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    selected_site_id = request.cookies.get(COOKIE_SITE_ID, "").strip()
    try:
        data = serialize_portal_session(
            request,
            site_admin_ref=auth.site_admin_ref,
            site_id=selected_site_id,
            strict_site=False,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal session loaded",
        data=data,
    )


@router.post("/session/site")
async def select_portal_session_site(
    request: Request,
    payload: PortalSessionSitePayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    site_id = payload.site_id.strip()
    if not site_id:
        return portal_json_error(
            request,
            status_code=400,
            error_code="portal.site_invalid",
            message="site id is required",
        )
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    try:
        data = serialize_portal_session(
            request,
            site_admin_ref=auth.site_admin_ref,
            site_id=site_id,
            strict_site=True,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    response = JSONResponse(
        status_code=200,
        content=_portal_route_envelope(
            message="portal site selected",
            data=data,
        ),
    )
    response.set_cookie(
        COOKIE_SITE_ID,
        site_id,
        httponly=True,
        secure=portal_cookie_secure(request),
        samesite="lax",
    )
    return response


@router.post("/logout")
async def logout_portal_session(request: Request) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    return _portal_session_cleared_response()


@router.post("/session/revoke")
async def revoke_portal_session(request: Request) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    return _portal_session_cleared_response()


@router.get("/sites")
async def list_portal_sites(request: Request) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    try:
        result = _get_commercial_service(request).list_portal_sites(
            site_admin_ref=auth.site_admin_ref,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal sites loaded",
        data=result,
    )


@router.post("/sites")
async def create_portal_site(
    request: Request,
    payload: PortalCreateSitePayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request)
    if same_origin is not None:
        return same_origin
    write_guard = _portal_write_guard(request)
    if write_guard is not None:
        return write_guard
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_commercial_service(request)
    audit_context = _build_portal_audit_context(request, auth.site_admin_ref)
    try:
        result = service.provision_portal_site(
            account_id=payload.account_id,
            site_admin_ref=auth.site_admin_ref,
            wordpress_url=payload.wordpress_url,
            site_name=payload.site_name,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)

    return _portal_route_envelope(
        message="portal site created",
        data=result,
    )


@router.get("/sites/{site_id}/summary")
async def get_portal_site_summary(request: Request, site_id: str) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    result = _resolve_portal_site_summary(
        request,
        site_id=site_id,
        site_admin_ref=auth.site_admin_ref,
    )
    if isinstance(result, JSONResponse):
        return result
    return _portal_route_envelope(
        message="portal site summary loaded",
        data=result,
    )


@router.get("/sites/{site_id}/usage-summary")
async def get_portal_site_usage_summary(request: Request, site_id: str) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        site_admin_ref=auth.site_admin_ref,
        required_roles=SITE_ADMIN_SITE_KEY_WRITE_ROLES,
    )
    if isinstance(access, JSONResponse):
        return access
    result = UsageService(_get_commercial_service(request).database_url).get_usage_summary(
        site_id=site_id
    )
    result["site_id"] = site_id
    result["account_id"] = str(access.get("account_id") or "")
    result["site_admin_ref"] = auth.site_admin_ref
    result["identity_type"] = str(access.get("identity_type") or "")
    result["allowed_actions"] = [
        str(action) for action in _object_list(access.get("allowed_actions")) if str(action).strip()
    ]
    result["role"] = str(access.get("role") or "")
    return _portal_route_envelope(
        message="portal usage summary loaded",
        data=result,
    )


@router.get("/sites/{site_id}/monitoring-overview")
async def get_portal_site_monitoring_overview(
    request: Request,
    site_id: str,
    window_hours: int = Query(default=24, ge=1, le=168),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        site_admin_ref=auth.site_admin_ref,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        service = _get_commercial_service(request)
        policy = service.inspect_commercial_policy(site_id)
        result = SiteMonitoringOverviewService(service.database_url).get_summary(
            site_id=site_id,
            commercial_policy=policy,
            window_hours=window_hours,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    result["account_id"] = str(access.get("account_id") or "")
    result["site_admin_ref"] = auth.site_admin_ref
    result["identity_type"] = str(access.get("identity_type") or "")
    result["allowed_actions"] = [
        str(action) for action in _object_list(access.get("allowed_actions")) if str(action).strip()
    ]
    result["role"] = str(access.get("role") or "")
    return _portal_route_envelope(
        message="portal monitoring overview loaded",
        data=result,
    )


@router.get("/sites/{site_id}/plugin-observability")
async def get_portal_site_plugin_observability(
    request: Request,
    site_id: str,
    window_hours: int = Query(default=24, ge=1, le=168),
    plugin_slug: str = Query(default="", max_length=64),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        site_admin_ref=auth.site_admin_ref,
    )
    if isinstance(access, JSONResponse):
        return access
    result = PluginObservabilityService(_get_commercial_service(request).database_url).get_summary(
        site_id=site_id,
        window_hours=window_hours,
        plugin_slug=plugin_slug.strip(),
    )
    result["site_id"] = site_id
    result["account_id"] = str(access.get("account_id") or "")
    result["site_admin_ref"] = auth.site_admin_ref
    result["identity_type"] = str(access.get("identity_type") or "")
    result["allowed_actions"] = [
        str(action) for action in _object_list(access.get("allowed_actions")) if str(action).strip()
    ]
    result["role"] = str(access.get("role") or "")
    return _portal_route_envelope(
        message="portal plugin observability loaded",
        data=result,
    )


@router.get("/sites/{site_id}/media-observability")
async def get_portal_site_media_observability(
    request: Request,
    site_id: str,
    window_hours: int = Query(default=24, ge=1, le=168),
    target_format: str = Query(default="", max_length=16),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        site_admin_ref=auth.site_admin_ref,
    )
    if isinstance(access, JSONResponse):
        return access
    services = get_cloud_services(request)
    result = MediaDerivativeObservabilityService(
        services.settings.database_url,
        site_queued_limit=services.settings.media_derivative_site_queued_limit,
        site_running_limit=services.settings.media_derivative_site_running_limit,
        default_chunk_size=services.settings.media_derivative_batch_default_chunk_size,
    ).get_summary(
        site_id=site_id,
        window_hours=window_hours,
        target_format=target_format.strip(),
    )
    result.pop("sites", None)
    result["workflow_metadata"] = get_workflow_metadata(MEDIA_DERIVATIVE_WORKFLOW_ID)
    result["site_id"] = site_id
    result["account_id"] = str(access.get("account_id") or "")
    result["site_admin_ref"] = auth.site_admin_ref
    result["identity_type"] = str(access.get("identity_type") or "")
    result["allowed_actions"] = [
        str(action) for action in _object_list(access.get("allowed_actions")) if str(action).strip()
    ]
    result["role"] = str(access.get("role") or "")
    return _portal_route_envelope(
        message="portal media observability loaded",
        data=result,
    )


@router.get("/sites/{site_id}/vector-observability")
async def get_portal_site_vector_observability(
    request: Request,
    site_id: str,
    window_hours: int = Query(default=24, ge=1, le=168),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        site_admin_ref=auth.site_admin_ref,
    )
    if isinstance(access, JSONResponse):
        return access
    result = SiteKnowledgeObservabilityService(
        _get_commercial_service(request).database_url
    ).get_summary(
        site_id=site_id,
        window_hours=window_hours,
    )
    result.pop("sites", None)
    result["site_id"] = site_id
    result["account_id"] = str(access.get("account_id") or "")
    result["site_admin_ref"] = auth.site_admin_ref
    result["identity_type"] = str(access.get("identity_type") or "")
    result["allowed_actions"] = [
        str(action) for action in _object_list(access.get("allowed_actions")) if str(action).strip()
    ]
    result["role"] = str(access.get("role") or "")
    return _portal_route_envelope(
        message="portal vector observability loaded",
        data=result,
    )


@router.get("/sites/{site_id}/ai-insights/history")
async def list_portal_site_ai_insight_history(
    request: Request,
    site_id: str,
    limit: int = Query(default=10, ge=1, le=50),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        site_admin_ref=auth.site_admin_ref,
    )
    if isinstance(access, JSONResponse):
        return access
    history = _get_portal_advisor_service(request).list_ops_summary_history(
        site_id=site_id,
        scope="operations_analysis",
        limit=limit,
    )
    return _portal_route_envelope(
        message="portal ai insight history loaded",
        data={
            "portal_ai_insight_version": "portal-ai-insight-v1",
            "site_id": site_id,
            "account_id": str(access.get("account_id") or ""),
            "site_admin_ref": auth.site_admin_ref,
            "identity_type": str(access.get("identity_type") or ""),
            "role": str(access.get("role") or ""),
            "items": [
                _portal_ai_history_item(item)
                for item in _object_list(history.get("items"))
                if isinstance(item, dict)
            ],
            "safety": _portal_ai_safety_contract(),
        },
    )


@router.post("/sites/{site_id}/ai-insights/analyze")
async def analyze_portal_site_ai_insight(
    request: Request,
    site_id: str,
    payload: PortalAIInsightAnalyzePayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request)
    if same_origin is not None:
        return same_origin
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        site_admin_ref=auth.site_admin_ref,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        summary = _get_portal_advisor_service(request).get_ops_summary(
            scope="operations",
            site_id=site_id,
            draft_kind="operator_analysis",
            recent_minutes=120,
            usage_window_days=7,
            audit_window_minutes=1440,
            range_filter="24h",
            limit=25,
            provider_id=_resolve_portal_ai_provider_id(request),
            model_id=FREE_GPT55_MODEL_ID,
            force_refresh=payload.force_refresh,
            cache_ttl_seconds=1800,
        )
    except ValueError as error:
        return portal_json_error(
            request,
            status_code=400,
            error_code="portal.ai_insight_invalid",
            message=str(error),
        )
    return _portal_route_envelope(
        message="portal ai insight analyzed",
        data={
            "portal_ai_insight_version": "portal-ai-insight-v1",
            "site_id": site_id,
            "account_id": str(access.get("account_id") or ""),
            "site_admin_ref": auth.site_admin_ref,
            "identity_type": str(access.get("identity_type") or ""),
            "role": str(access.get("role") or ""),
            "analysis": _portal_ai_summary(summary),
            "safety": _portal_ai_safety_contract(),
        },
    )


@router.get("/sites/{site_id}/entitlements")
async def get_portal_site_entitlements(request: Request, site_id: str) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        site_admin_ref=auth.site_admin_ref,
        required_roles=SITE_ADMIN_SITE_KEY_WRITE_ROLES,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        commercial_service = _get_commercial_service(request)
        policy = commercial_service.inspect_commercial_policy(site_id)
        quota_summary = commercial_service.get_portal_account_quota_summary(
            str(access.get("account_id") or "")
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal entitlements loaded",
        data={
            "site_id": site_id,
            "account_id": str(access.get("account_id") or ""),
            "site_admin_ref": auth.site_admin_ref,
            "identity_type": str(access.get("identity_type") or ""),
            "allowed_actions": [
                str(action)
                for action in _object_list(access.get("allowed_actions"))
                if str(action).strip()
            ],
            "role": str(access.get("role") or ""),
            "site": policy.get("site"),
            "subscription": policy.get("subscription"),
            "plan_version": policy.get("plan_version"),
            "entitlement_snapshot": policy.get("entitlement_snapshot"),
            "policy": policy.get("policy"),
            "period_start_at": policy.get("period_start_at"),
            "period_end_at": policy.get("period_end_at"),
            "usage_totals": policy.get("usage_totals"),
            "subscription_grace": policy.get("subscription_grace"),
            "budget_state": policy.get("budget_state"),
            "quota_summary": quota_summary,
            "generated_at": policy.get("generated_at"),
        },
    )


@router.get("/sites/{site_id}/audit-summary")
async def get_portal_site_audit_summary(request: Request, site_id: str) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        site_admin_ref=auth.site_admin_ref,
        required_roles=SITE_ADMIN_SITE_KEY_WRITE_ROLES,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        summary = _get_commercial_service(request).summarize_service_audit_events(
            site_id=site_id,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal audit summary loaded",
        data={
            "site_id": site_id,
            "account_id": str(access.get("account_id") or ""),
            "site_admin_ref": auth.site_admin_ref,
            "identity_type": str(access.get("identity_type") or ""),
            "allowed_actions": [
                str(action)
                for action in _object_list(access.get("allowed_actions"))
                if str(action).strip()
            ],
            "role": str(access.get("role") or ""),
            **summary,
        },
    )


@router.get("/sites/{site_id}/audit-events")
async def list_portal_site_audit_events(
    request: Request,
    site_id: str,
    event_kind: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        site_admin_ref=auth.site_admin_ref,
        required_roles=SITE_ADMIN_SITE_KEY_WRITE_ROLES,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        events = _get_commercial_service(request).list_service_audit_events(
            site_id=site_id,
            event_kind=event_kind,
            outcome=outcome,
            limit=limit,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal audit events loaded",
        data={
            "site_id": site_id,
            "account_id": str(access.get("account_id") or ""),
            "site_admin_ref": auth.site_admin_ref,
            "identity_type": str(access.get("identity_type") or ""),
            "allowed_actions": [
                str(action)
                for action in _object_list(access.get("allowed_actions"))
                if str(action).strip()
            ],
            "role": str(access.get("role") or ""),
            **events,
        },
    )


@router.get("/sites/{site_id}/billing-snapshots")
async def list_portal_site_billing_snapshots(request: Request, site_id: str) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        site_admin_ref=auth.site_admin_ref,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        snapshots = _get_commercial_service(request).list_billing_snapshots(site_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal billing snapshots loaded",
        data={
            "site_id": site_id,
            "account_id": str(access.get("account_id") or ""),
            "site_admin_ref": auth.site_admin_ref,
            "identity_type": str(access.get("identity_type") or ""),
            "allowed_actions": [
                str(action)
                for action in _object_list(access.get("allowed_actions"))
                if str(action).strip()
            ],
            "role": str(access.get("role") or ""),
            **snapshots,
        },
    )


@router.get("/sites/{site_id}/billing-snapshots/reconciliation")
async def get_portal_site_billing_reconciliation(request: Request, site_id: str) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        site_admin_ref=auth.site_admin_ref,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        reconciliation = _get_commercial_service(request).reconcile_billing_snapshot(site_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal billing reconciliation loaded",
        data={
            "site_id": site_id,
            "account_id": str(access.get("account_id") or ""),
            "site_admin_ref": auth.site_admin_ref,
            "identity_type": str(access.get("identity_type") or ""),
            "role": str(access.get("role") or ""),
            **reconciliation,
        },
    )


@router.get("/sites/{site_id}/api-keys")
async def list_portal_site_keys(
    request: Request,
    site_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        site_admin_ref=auth.site_admin_ref,
        required_roles=SITE_ADMIN_SITE_KEY_WRITE_ROLES,
    )
    if isinstance(access, JSONResponse):
        return access

    try:
        result = _get_commercial_service(request).list_site_keys(
            site_id,
            limit=limit,
            offset=offset,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)

    items = [
        serialize_portal_site_key(item)
        for item in _object_list(result.get("items"))
        if isinstance(item, dict)
    ]

    return build_envelope(
        status="ok",
        message="portal api keys loaded",
        data={
            "site_id": site_id,
            "items": items,
            "pagination": result.get("pagination") or {},
            "sort": result.get("sort") or {},
        },
        revision="m6",
    )


@router.post("/sites/{site_id}/api-keys")
async def issue_portal_site_key(
    request: Request,
    site_id: str,
    payload: PortalSiteKeyPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request)
    if same_origin is not None:
        return same_origin
    write_guard = _portal_write_guard(request)
    if write_guard is not None:
        return write_guard
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        site_admin_ref=auth.site_admin_ref,
        required_roles=SITE_ADMIN_SITE_KEY_WRITE_ROLES,
    )
    if isinstance(access, JSONResponse):
        return access

    service = _get_commercial_service(request)
    audit_context = _build_portal_audit_context(request, auth.site_admin_ref)

    try:
        result = service.issue_site_key(
            site_id=site_id,
            key_id=None,
            secret=None,
            scopes=payload.scopes,
            label=payload.label,
            expires_at=payload.expires_at,
            metadata_json=payload.metadata,
            audit_context=audit_context,
            activate_site_on_issue=True,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)

    cloud_api_key = build_customer_api_key(
        site_id=str(result.get("site_id") or ""),
        key_id=str(result.get("key_id") or ""),
        secret=str(result.get("secret") or ""),
    )

    return build_envelope(
        status="ok",
        message="portal api key issued",
        data=serialize_portal_site_key(result, cloud_api_key=cloud_api_key),
        revision="m6",
    )


@router.post("/sites/{site_id}/api-keys/{key_id}/rotate")
async def rotate_portal_site_key(
    request: Request,
    site_id: str,
    key_id: str,
    payload: PortalSiteKeyPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request)
    if same_origin is not None:
        return same_origin
    write_guard = _portal_write_guard(request)
    if write_guard is not None:
        return write_guard
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        site_admin_ref=auth.site_admin_ref,
        required_roles=SITE_ADMIN_SITE_KEY_WRITE_ROLES,
    )
    if isinstance(access, JSONResponse):
        return access

    service = _get_commercial_service(request)
    audit_context = _build_portal_audit_context(request, auth.site_admin_ref)

    try:
        result = service.rotate_site_key(
            site_id=site_id,
            key_id=key_id,
            next_key_id=None,
            secret=None,
            scopes=payload.scopes if payload.scopes else None,
            label=payload.label,
            expires_at=payload.expires_at,
            metadata_json=payload.metadata,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)

    previous = _dict_value(result.get("previous"))
    current = _dict_value(result.get("current"))
    cloud_api_key = build_customer_api_key(
        site_id=str(current.get("site_id") or ""),
        key_id=str(current.get("key_id") or ""),
        secret=str(current.get("secret") or ""),
    )

    return build_envelope(
        status="ok",
        message="portal api key rotated",
        data={
            "previous": serialize_portal_site_key(previous),
            "current": serialize_portal_site_key(current, cloud_api_key=cloud_api_key),
        },
        revision="m6",
    )


@router.post("/sites/{site_id}/api-keys/{key_id}/revoke")
async def revoke_portal_site_key(
    request: Request,
    site_id: str,
    key_id: str,
) -> Any:
    same_origin = _portal_same_origin_guard(request)
    if same_origin is not None:
        return same_origin
    write_guard = _portal_write_guard(request)
    if write_guard is not None:
        return write_guard
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        site_admin_ref=auth.site_admin_ref,
        required_roles=SITE_ADMIN_SITE_KEY_WRITE_ROLES,
    )
    if isinstance(access, JSONResponse):
        return access

    service = _get_commercial_service(request)
    audit_context = _build_portal_audit_context(request, auth.site_admin_ref)

    try:
        result = service.revoke_site_key(
            site_id=site_id,
            key_id=key_id,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)

    return build_envelope(
        status="ok",
        message="portal api key revoked",
        data=serialize_portal_site_key(result),
        revision="m6",
    )
