from __future__ import annotations

import json
import secrets
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from app.adapters.notifications.base import PortalEmailDeliveryError
from app.adapters.notifications.smtp import build_portal_email_sender
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
    build_new_portal_session_metadata,
    clear_portal_session_cookies,
    portal_cookie_secure,
    portal_json_error,
    resolve_portal_login_session_ttl_seconds,
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
from app.domain.commercial.identity import (
    USER_ALLOWED_ACTION_MANAGE_SITE_KEYS,
    USER_ALLOWED_ACTION_REMOVE_SITES,
    USER_ALLOWED_ACTION_VIEW_AUDIT,
    USER_ALLOWED_ACTION_VIEW_BILLING,
    USER_ALLOWED_ACTION_VIEW_USAGE,
    USER_SITE_KEY_WRITE_ROLES,
)
from app.domain.hosted_model_defaults import FREE_GPT55_MODEL_ID
from app.domain.media_derivatives.metrics import MediaDerivativeObservabilityService
from app.domain.observability.plugin_events import PluginObservabilityService
from app.domain.observability.site_monitoring_overview import SiteMonitoringOverviewService
from app.domain.service_settings import (
    resolve_portal_qq_runtime_config,
)
from app.domain.site_knowledge.metrics import SiteKnowledgeObservabilityService
from app.domain.usage.service import UsageService

router = APIRouter(prefix="/portal/v1", tags=["portal"])
COOKIE_PORTAL_QQ_OAUTH_NONCE = "npcink_portal_qq_oauth_nonce"
COOKIE_PORTAL_QQ_OAUTH_NONCE_LEGACY = "magick_portal_qq_oauth_nonce"
COOKIE_PORTAL_QQ_OAUTH_NONCE_PATH = "/"
COOKIE_PORTAL_QQ_OAUTH_NONCE_LEGACY_PATH = "/portal/v1/auth/qq"


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


class PortalAddonConnectionPayload(BaseModel):
    account_id: str = ""
    site_name: str = ""
    wordpress_url: str = ""
    return_url: str = ""
    state: str = ""


class PortalAddonConnectionExchangePayload(BaseModel):
    code: str = ""
    state: str = ""


class PortalLoginCodeRequestPayload(BaseModel):
    email: str = ""
    locale: str = ""


class PortalLoginCodeVerifyPayload(BaseModel):
    email: str = ""
    code: str = ""
    remember_me: bool = False


class PortalEmailChangeRequestPayload(BaseModel):
    new_email: str = ""
    locale: str = ""


class PortalEmailChangeVerifyPayload(BaseModel):
    new_email: str = ""
    code: str = ""


class PortalRegistrationCodeRequestPayload(BaseModel):
    email: str = ""
    site_url: str = ""
    site_name: str = ""
    use_case: str = ""
    locale: str = ""


class PortalRegistrationVerifyPayload(BaseModel):
    email: str = ""
    code: str = ""


class PortalQQBindPayload(BaseModel):
    code: str = ""
    state: str = ""
    nonce: str = ""


class PortalQQUnbindPayload(BaseModel):
    provider: str = "qq"


class PortalAIInsightAnalyzePayload(BaseModel):
    force_refresh: bool = False


class PortalCreditPackOrderPayload(BaseModel):
    pack_id: str = ""
    provider: str = "alipay"


class PortalProMonthlyOrderPayload(BaseModel):
    provider: str = "alipay"


def _object_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _dict_value(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _build_portal_audit_context(request: Request, principal_id: str) -> ServiceAuditContext:
    audit_context = _build_audit_context(request)
    audit_context.actor_kind = "principal"
    audit_context.actor_ref = principal_id
    return audit_context


def _authorize_portal_site_access(
    request: Request,
    *,
    site_id: str,
    principal_id: str,
    required_roles: set[str] | None = None,
    required_action: str | None = None,
) -> dict[str, object] | JSONResponse:
    try:
        access = _get_commercial_service(request).resolve_portal_site_access(
            site_id=site_id,
            principal_id=principal_id,
            required_roles=required_roles,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    normalized_action = str(required_action or "").strip()
    if normalized_action:
        allowed_actions = {
            str(action).strip()
            for action in _object_list(access.get("allowed_actions"))
            if str(action).strip()
        }
        if normalized_action not in allowed_actions:
            return portal_json_error(
                request,
                status_code=403,
                error_code="service.portal_action_forbidden",
                message=f"principal '{principal_id}' lacks required action '{normalized_action}'",
            )
    return access


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


def _portal_qq_config_error(request: Request) -> JSONResponse | None:
    config = _portal_qq_config(request)
    if not str(config.get("client_id") or "").strip():
        return portal_json_error(
            request,
            status_code=503,
            error_code="portal.qq_login_not_configured",
            message="QQ login is not configured",
        )
    if not str(config.get("client_secret") or "").strip():
        return portal_json_error(
            request,
            status_code=503,
            error_code="portal.qq_login_not_configured",
            message="QQ login is not configured",
        )
    if not str(config.get("redirect_uri") or "").strip():
        return portal_json_error(
            request,
            status_code=503,
            error_code="portal.qq_login_not_configured",
            message="QQ login redirect uri is not configured",
        )
    return None


def _portal_qq_config(request: Request) -> dict[str, Any]:
    settings = get_cloud_services(request).settings
    return resolve_portal_qq_runtime_config(settings.database_url, settings)


def _portal_qq_redirect_uri(request: Request) -> str:
    return str(_portal_qq_config(request).get("redirect_uri") or "").strip()


def _portal_qq_oauth_nonce(request: Request, payload_nonce: str = "") -> str:
    return str(payload_nonce or request.cookies.get(COOKIE_PORTAL_QQ_OAUTH_NONCE) or "").strip()


def _set_portal_qq_oauth_nonce_cookie(
    request: Request,
    response: JSONResponse,
    *,
    nonce: str,
    max_age: int,
) -> None:
    _clear_portal_qq_oauth_nonce_cookie(response)
    response.set_cookie(
        COOKIE_PORTAL_QQ_OAUTH_NONCE,
        nonce,
        httponly=True,
        secure=portal_cookie_secure(request),
        samesite="lax",
        path=COOKIE_PORTAL_QQ_OAUTH_NONCE_PATH,
        max_age=max(60, int(max_age or 0)),
    )


def _clear_portal_qq_oauth_nonce_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_PORTAL_QQ_OAUTH_NONCE, path=COOKIE_PORTAL_QQ_OAUTH_NONCE_PATH)
    response.delete_cookie(
        COOKIE_PORTAL_QQ_OAUTH_NONCE,
        path=COOKIE_PORTAL_QQ_OAUTH_NONCE_LEGACY_PATH,
    )
    response.delete_cookie(
        COOKIE_PORTAL_QQ_OAUTH_NONCE_LEGACY,
        path=COOKIE_PORTAL_QQ_OAUTH_NONCE_PATH,
    )
    response.delete_cookie(
        COOKIE_PORTAL_QQ_OAUTH_NONCE_LEGACY,
        path=COOKIE_PORTAL_QQ_OAUTH_NONCE_LEGACY_PATH,
    )


def _build_qq_authorization_url(request: Request, *, state: str) -> str:
    config = _portal_qq_config(request)
    query = urlencode(
        {
            "response_type": "code",
            "client_id": str(config.get("client_id") or "").strip(),
            "redirect_uri": str(config.get("redirect_uri") or "").strip(),
            "state": state,
            "scope": str(config.get("scope") or "get_user_info").strip(),
        }
    )
    return f"https://graph.qq.com/oauth2.0/authorize?{query}"


def _portal_prefers_html(request: Request) -> bool:
    accept = str(request.headers.get("accept") or "").lower()
    return "text/html" in accept and "application/json" not in accept


def _portal_oauth_return_response(
    request: Request,
    *,
    return_to: str,
    status: str,
) -> RedirectResponse | None:
    if not _portal_prefers_html(request):
        return None
    safe_return_to = return_to if return_to.startswith("/portal") else "/portal"
    separator = "&" if "?" in safe_return_to else "?"
    return RedirectResponse(f"{safe_return_to}{separator}qq={status}", status_code=303)


def _parse_qq_query_response(value: str) -> dict[str, str]:
    return {key: item for key, item in parse_qsl(str(value or ""), keep_blank_values=True)}


def _parse_qq_me_response(value: str) -> dict[str, object]:
    raw = str(value or "").strip()
    if raw.startswith("callback(") and raw.endswith(");"):
        raw = raw[len("callback(") : -2].strip()
    payload = json.loads(raw)
    return payload if isinstance(payload, dict) else {}


def _exchange_qq_code(request: Request, *, code: str) -> dict[str, str]:
    config = _portal_qq_config(request)
    with httpx.Client(timeout=float(config.get("timeout_seconds") or 10.0)) as client:
        response = client.get(
            "https://graph.qq.com/oauth2.0/token",
            params={
                "grant_type": "authorization_code",
                "client_id": str(config.get("client_id") or "").strip(),
                "client_secret": str(config.get("client_secret") or "").strip(),
                "code": code,
                "redirect_uri": str(config.get("redirect_uri") or "").strip(),
                "fmt": "xhtml",
            },
        )
        response.raise_for_status()
    payload = _parse_qq_query_response(response.text)
    if not str(payload.get("access_token") or "").strip():
        raise CommercialServiceError(
            502,
            "portal.qq_token_exchange_failed",
            "QQ token exchange failed",
        )
    return payload


def _fetch_qq_openid(request: Request, *, access_token: str) -> dict[str, str]:
    config = _portal_qq_config(request)
    with httpx.Client(timeout=float(config.get("timeout_seconds") or 10.0)) as client:
        response = client.get(
            "https://graph.qq.com/oauth2.0/me",
            params={
                "access_token": access_token,
                "unionid": "1",
                "fmt": "json",
            },
        )
        response.raise_for_status()
    payload = _parse_qq_me_response(response.text)
    openid = str(payload.get("openid") or "").strip()
    if not openid:
        raise CommercialServiceError(
            502,
            "portal.qq_openid_fetch_failed",
            "QQ openid fetch failed",
        )
    return {
        "openid": openid,
        "unionid": str(payload.get("unionid") or "").strip(),
    }


def _portal_write_guard(request: Request) -> JSONResponse | None:
    return None


def _portal_same_origin_guard(
    request: Request,
    *,
    always: bool = False,
) -> JSONResponse | None:
    settings = get_cloud_services(request).settings
    if (
        settings.production_like_environment()
        and str(request.headers.get("x-npcink-debug-portal-link") or "").strip() == "1"
    ):
        return portal_json_error(
            request,
            status_code=403,
            error_code="auth.origin_forbidden",
            message="cross-site browser writes are not allowed",
        )
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


def _allow_development_login_code(request: Request) -> bool:
    services = get_cloud_services(request)
    environment = str(services.settings.environment or "").strip().lower()
    return environment in {"development", "test"} and (
        str(request.headers.get("x-npcink-dev-login-code") or "").strip() == "1"
        or str(request.headers.get("x-npcink-debug-portal-link") or "").strip() == "1"
    )


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


@router.get("/auth/qq/start")
async def start_portal_qq_login(
    request: Request,
    return_to: str = Query(default="/portal"),
    intent: str = Query(default="login"),
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    config_error = _portal_qq_config_error(request)
    if config_error is not None:
        return config_error
    nonce = secrets.token_urlsafe(32)
    issued = _get_commercial_service(request).issue_portal_oauth_state(
        provider="qq",
        return_to=return_to,
        client_scope_id=str(request.client.host if request.client else ""),
        ttl_seconds=int(get_cloud_services(request).settings.portal_oauth_state_ttl_seconds or 0),
        nonce=nonce,
        intent=intent,
    )
    authorization_url = _build_qq_authorization_url(
        request,
        state=str(issued.get("state") or ""),
    )
    expires_in_seconds_value: Any = issued.get("expires_in_seconds") or 0
    expires_in_seconds = int(expires_in_seconds_value)
    response = JSONResponse(
        status_code=200,
        content=_portal_route_envelope(
            message="portal QQ login started",
            data={
                "provider": "qq",
                "authorization_url": authorization_url,
                "state": str(issued.get("state") or ""),
                "expires_in_seconds": expires_in_seconds,
                "return_to": str(issued.get("return_to") or "/portal"),
                "intent": str(issued.get("intent") or "login"),
            },
        ),
    )
    _set_portal_qq_oauth_nonce_cookie(
        request,
        response,
        nonce=nonce,
        max_age=expires_in_seconds,
    )
    return response


@router.get("/auth/qq/callback")
async def finish_portal_qq_login(
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
) -> Any:
    if not code.strip() or not state.strip():
        return portal_json_error(
            request,
            status_code=400,
            error_code="portal.qq_callback_required",
            message="QQ authorization code and state are required",
        )
    config_error = _portal_qq_config_error(request)
    if config_error is not None:
        return config_error
    try:
        consumed_state = _get_commercial_service(request).consume_portal_oauth_state(
            provider="qq",
            state=state,
            nonce=_portal_qq_oauth_nonce(request),
        )
        token = _exchange_qq_code(request, code=code.strip())
        subject = _fetch_qq_openid(
            request,
            access_token=str(token.get("access_token") or ""),
        )
        return_to = str(consumed_state.get("return_to") or "/portal")
        if str(consumed_state.get("intent") or "") == "bind":
            auth = await resolve_portal_request_context(
                request,
                require_idempotency=False,
                allow_session_cookies=True,
            )
            if isinstance(auth, JSONResponse):
                return auth
            binding = _get_commercial_service(request).bind_portal_identity_provider(
                principal_id=auth.principal_id,
                provider="qq",
                external_subject=str(subject.get("openid") or ""),
                unionid=str(subject.get("unionid") or ""),
                metadata_json={"source": "portal_qq_callback_bind"},
            )
            redirect = _portal_oauth_return_response(
                request,
                return_to=return_to,
                status="bound",
            )
            if redirect is not None:
                _clear_portal_qq_oauth_nonce_cookie(redirect)
                return redirect
            response = JSONResponse(
                status_code=200,
                content=_portal_route_envelope(
                    message="portal QQ login bound",
                    data={
                        "status": "bound",
                        "provider": "qq",
                        "return_to": return_to,
                        "binding": binding,
                    },
                ),
            )
            _clear_portal_qq_oauth_nonce_cookie(response)
            return response
        login = _get_commercial_service(request).resolve_portal_identity_provider_login(
            provider="qq",
            external_subject=str(subject.get("openid") or ""),
            unionid=str(subject.get("unionid") or ""),
        )
        if str(login.get("status") or "") == "binding_required":
            redirect = _portal_oauth_return_response(
                request,
                return_to=return_to,
                status="binding_required",
            )
            if redirect is not None:
                _clear_portal_qq_oauth_nonce_cookie(redirect)
                return redirect
            response = JSONResponse(
                status_code=200,
                content=_portal_route_envelope(
                    message="portal QQ binding required",
                    data={
                        **login,
                        "return_to": return_to,
                    },
                ),
            )
            _clear_portal_qq_oauth_nonce_cookie(response)
            return response
        principal_id = str(login.get("principal_id") or "")
        data = serialize_portal_session(
            request,
            principal_id=principal_id,
            site_id="",
            strict_site=False,
            session_metadata=build_new_portal_session_metadata(request),
        )
        data["auth_provider"] = "qq"
        data["return_to"] = return_to
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    except httpx.HTTPError as error:
        return portal_json_error(
            request,
            status_code=502,
            error_code="portal.qq_provider_unavailable",
            message=str(error),
        )

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
        principal_id=principal_id,
        site_id=str(data.get("site_id") or ""),
    )
    _clear_portal_qq_oauth_nonce_cookie(response)
    return response


@router.get("/auth/identity-providers")
async def list_portal_identity_providers(request: Request) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    try:
        result = _get_commercial_service(request).list_portal_identity_provider_bindings(
            principal_id=auth.principal_id,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    raw_items = result.get("items", [])
    items = (
        [item for item in raw_items if isinstance(item, dict)]
        if isinstance(raw_items, list)
        else []
    )
    qq_binding = next(
        (item for item in items if str(item.get("provider") or "") == "qq"),
        None,
    )
    qq_config = _portal_qq_config(request)
    qq_configured = all(
        str(qq_config.get(key) or "").strip()
        for key in ("client_id", "client_secret", "redirect_uri")
    )
    return _portal_route_envelope(
        message="portal identity providers listed",
        data={
            "principal_id": auth.principal_id,
            "providers": [
                {
                    "provider": "qq",
                    "display_name": "QQ",
                    "configured": qq_configured,
                    "bound": qq_binding is not None,
                    "binding": qq_binding,
                    "bind_start_path": (
                        "/portal/v1/auth/qq/start?intent=bind&return_to=/portal/account"
                    ),
                }
            ],
        },
    )


@router.post("/auth/qq/bind")
async def bind_portal_qq_login(
    request: Request,
    payload: PortalQQBindPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    config_error = _portal_qq_config_error(request)
    if config_error is not None:
        return config_error
    code = payload.code.strip()
    state = payload.state.strip()
    if not code or not state:
        return portal_json_error(
            request,
            status_code=400,
            error_code="portal.qq_bind_required",
            message="QQ authorization code and state are required",
        )
    try:
        _get_commercial_service(request).consume_portal_oauth_state(
            provider="qq",
            state=state,
            nonce=_portal_qq_oauth_nonce(request, payload.nonce),
        )
        token = _exchange_qq_code(request, code=code)
        subject = _fetch_qq_openid(
            request,
            access_token=str(token.get("access_token") or ""),
        )
        binding = _get_commercial_service(request).bind_portal_identity_provider(
            principal_id=auth.principal_id,
            provider="qq",
            external_subject=str(subject.get("openid") or ""),
            unionid=str(subject.get("unionid") or ""),
            metadata_json={"source": "portal_qq_bind"},
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    except httpx.HTTPError as error:
        return portal_json_error(
            request,
            status_code=502,
            error_code="portal.qq_provider_unavailable",
            message=str(error),
        )
    response = JSONResponse(
        status_code=200,
        content=_portal_route_envelope(
            message="portal QQ login bound",
            data={"binding": binding},
        ),
    )
    _clear_portal_qq_oauth_nonce_cookie(response)
    return response


@router.post("/auth/qq/unbind")
async def unbind_portal_qq_login(
    request: Request,
    payload: PortalQQUnbindPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    try:
        result = _get_commercial_service(request).revoke_portal_identity_provider(
            principal_id=auth.principal_id,
            provider=payload.provider,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal QQ login unbound",
        data=result,
    )


def _portal_ai_disclosure(disclosure: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": str(disclosure.get("version") or ""),
        "content_origin": str(disclosure.get("content_origin") or ""),
        "generated_by_ai": bool(disclosure.get("generated_by_ai")),
        "ai_assisted": bool(disclosure.get("ai_assisted")),
        "visible_label_required": bool(disclosure.get("visible_label_required")),
        "visible_label": str(disclosure.get("visible_label") or ""),
        "brand_label": str(disclosure.get("brand_label") or "Npcink AI"),
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
        **_portal_ai_agent_metadata_projection_fields(summary.get("agent_handoff")),
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
        **_portal_ai_agent_metadata_projection_fields(item.get("agent_handoff")),
    }


def _portal_ai_agent_metadata_projection_fields(value: Any) -> dict[str, Any]:
    projection = _portal_ai_agent_metadata_projection(value)
    return {
        "agent_metadata_projection": projection,
    }


def _portal_ai_agent_metadata_projection(value: Any) -> dict[str, Any]:
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


def _resolve_primary_portal_account_id(
    request: Request,
    *,
    principal_id: str,
) -> str | JSONResponse:
    try:
        accounts = _get_commercial_service(request).list_portal_accounts(
            principal_id=principal_id
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    for item in _object_list(accounts.get("items")):
        account = item if isinstance(item, dict) else {}
        account_id = str(account.get("account_id") or "").strip()
        if account_id:
            return account_id
    return portal_json_error(
        request,
        status_code=403,
        error_code="portal.account_required",
        message="portal account access is required",
    )


def _resolve_portal_site_summary(
    request: Request,
    *,
    site_id: str,
    principal_id: str,
) -> dict[str, object] | JSONResponse:
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        principal_id=principal_id,
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
        "principal_id": principal_id,
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
    services = get_cloud_services(request)
    ttl_seconds = resolve_portal_login_code_ttl_seconds(services.settings)
    email_sender = services.portal_email_sender or build_portal_email_sender(
        services.settings,
        database_url=services.settings.database_url,
    )
    allow_development_code = _allow_development_login_code(request)
    try:
        issued = _get_commercial_service(request).issue_portal_login_code(
            email=email,
            ttl_seconds=ttl_seconds,
        )
    except CommercialServiceError as error:
        if error.error_code in {
            "service.portal_email_not_found",
            "service.principal_email_not_found",
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
                principal_id=str(issued.get("principal_id") or ""),
                code=str(issued.get("code") or ""),
                expires_in_seconds=ttl_seconds,
                project_name=services.settings.project_name,
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
        principal_id = str(verified.get("principal_id") or "")
        session_ttl_seconds = resolve_portal_login_session_ttl_seconds(
            request,
            remember_me=bool(payload.remember_me),
        )
        data = serialize_portal_session(
            request,
            principal_id=principal_id,
            site_id="",
            strict_site=False,
            session_metadata=build_new_portal_session_metadata(
                request,
                ttl_seconds=session_ttl_seconds,
            ),
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
        principal_id=principal_id,
        site_id=str(data.get("site_id") or ""),
        ttl_seconds=session_ttl_seconds,
    )
    return response


@router.post("/account/email-change/request")
async def request_portal_email_change_code(
    request: Request,
    payload: PortalEmailChangeRequestPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    new_email = payload.new_email.strip()
    locale = resolve_portal_email_locale(request, payload.locale)
    if not new_email:
        return portal_json_error(
            request,
            status_code=400,
            error_code="portal.email_change_invalid",
            message="new email is required",
        )
    services = get_cloud_services(request)
    ttl_seconds = resolve_portal_login_code_ttl_seconds(services.settings)
    email_sender = services.portal_email_sender or build_portal_email_sender(
        services.settings,
        database_url=services.settings.database_url,
    )
    allow_development_code = _allow_development_login_code(request)
    if email_sender is None and not allow_development_code:
        return portal_json_error(
            request,
            status_code=503,
            error_code="portal.email_not_configured",
            message="Portal email delivery is not configured",
        )
    try:
        issued = _get_commercial_service(request).issue_portal_email_change_code(
            principal_id=auth.principal_id,
            new_email=new_email,
            ttl_seconds=ttl_seconds,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    if email_sender is not None:
        try:
            email_sender.send_email_change_code(
                recipient_email=str(issued.get("new_email") or ""),
                old_email=str(issued.get("old_email") or ""),
                principal_id=str(issued.get("principal_id") or ""),
                code=str(issued.get("code") or ""),
                expires_in_seconds=ttl_seconds,
                project_name=services.settings.project_name,
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
        message="portal email change code issued",
        data={
            "old_email": str(issued.get("old_email") or ""),
            "new_email": str(issued.get("new_email") or ""),
            "delivery": ("development_code" if allow_development_code else "email"),
            "expires_in_seconds": ttl_seconds,
            "code": (str(issued.get("code") or "") if allow_development_code else ""),
        },
    )


@router.post("/account/email-change/verify")
async def verify_portal_email_change_code(
    request: Request,
    payload: PortalEmailChangeVerifyPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    new_email = payload.new_email.strip()
    code = payload.code.strip()
    if not new_email or not code:
        return portal_json_error(
            request,
            status_code=400,
            error_code="auth.portal_email_change_code_required",
            message="portal email change code and new email are required",
        )
    services = get_cloud_services(request)
    try:
        changed = _get_commercial_service(request).verify_portal_email_change_code(
            principal_id=auth.principal_id,
            new_email=new_email,
            code=code,
            max_attempts=max(
                1,
                int(services.settings.portal_login_code_max_attempts or 0),
            ),
            audit_context=_build_portal_audit_context(request, auth.principal_id),
        )
        data = serialize_portal_session(
            request,
            principal_id=auth.principal_id,
            site_id=auth.site_id,
            strict_site=False,
        )
    except CommercialServiceError as error:
        if error.error_code == "service.portal_email_change_code_invalid":
            return portal_json_error(
                request,
                status_code=401,
                error_code="auth.portal_email_change_code_invalid",
                message="portal email change code is invalid or expired",
            )
        return _service_error_response(error, request=request)

    email_sender = services.portal_email_sender or build_portal_email_sender(
        services.settings,
        database_url=services.settings.database_url,
    )
    if email_sender is not None:
        try:
            email_sender.send_email_changed_notice(
                recipient_email=str(changed.get("old_email") or ""),
                new_email=str(changed.get("new_email") or ""),
                principal_id=auth.principal_id,
                project_name=services.settings.project_name,
                locale=resolve_portal_email_locale(request, ""),
            )
        except PortalEmailDeliveryError:
            pass
    return _portal_route_envelope(
        message="portal email changed",
        data={
            **data,
            "old_email": str(changed.get("old_email") or ""),
            "new_email": str(changed.get("new_email") or ""),
        },
    )


@router.post("/register/code/request")
async def request_portal_registration_code(
    request: Request,
    payload: PortalRegistrationCodeRequestPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    email = payload.email.strip()
    site_url = payload.site_url.strip()
    locale = resolve_portal_email_locale(request, payload.locale)
    if not email:
        return portal_json_error(
            request,
            status_code=400,
            error_code="portal.registration_required",
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
    services = get_cloud_services(request)
    ttl_seconds = resolve_portal_login_code_ttl_seconds(services.settings)
    allow_development_code = _allow_development_login_code(request)
    email_sender = services.portal_email_sender or build_portal_email_sender(
        services.settings,
        database_url=services.settings.database_url,
    )
    if email_sender is None and not allow_development_code:
        return portal_json_error(
            request,
            status_code=503,
            error_code="portal.email_not_configured",
            message="Portal email delivery is not configured",
        )
    try:
        issued = _get_commercial_service(request).issue_portal_registration_code(
            email=email,
            wordpress_url=site_url,
            site_name=payload.site_name,
            use_case=payload.use_case,
            ttl_seconds=ttl_seconds,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    if email_sender is not None:
        try:
            email_sender.send_registration_code(
                recipient_email=str(issued.get("email") or ""),
                principal_id=str(issued.get("principal_id") or ""),
                code=str(issued.get("code") or ""),
                expires_in_seconds=ttl_seconds,
                project_name=services.settings.project_name,
                site_name=str(issued.get("site_name") or ""),
                wordpress_url=str(issued.get("wordpress_url") or ""),
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
        message="portal registration code issued",
        data={
            "email": str(issued.get("email") or ""),
            "delivery": ("development_code" if allow_development_code else "email"),
            "expires_in_seconds": ttl_seconds,
            "code": (str(issued.get("code") or "") if allow_development_code else ""),
            "site": {
                "site_id": str(issued.get("site_id") or ""),
                "site_name": str(issued.get("site_name") or ""),
                "wordpress_url": str(issued.get("wordpress_url") or ""),
            },
        },
    )


@router.post("/register/verify")
async def verify_portal_registration_code(
    request: Request,
    payload: PortalRegistrationVerifyPayload,
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
            error_code="auth.portal_registration_code_required",
            message="portal registration code and email are required",
        )
    try:
        registration = _get_commercial_service(request).verify_portal_registration_code(
            email=email,
            code=code,
            max_attempts=max(
                1,
                int(get_cloud_services(request).settings.portal_login_code_max_attempts or 0),
            ),
            audit_context=_build_portal_audit_context(request, "portal_registration"),
        )
        principal_id = str(registration.get("principal_id") or "")
        site_id = str(registration.get("site_id") or "")
        session_data = serialize_portal_session(
            request,
            principal_id=principal_id,
            site_id=site_id,
            strict_site=False,
            session_metadata=build_new_portal_session_metadata(request),
        )
        data = {
            **registration,
            "session": session_data.get("session"),
            "sites": session_data.get("sites") or [],
            "accounts": session_data.get("accounts") or [],
        }
    except CommercialServiceError as error:
        if error.error_code == "service.portal_registration_code_invalid":
            return portal_json_error(
                request,
                status_code=401,
                error_code="auth.portal_registration_code_invalid",
                message="portal registration code is invalid or expired",
            )
        return _service_error_response(error, request=request)
    response = JSONResponse(
        status_code=200,
        content=_portal_route_envelope(
            message="portal registration completed",
            data=data,
        ),
    )
    set_portal_session_cookies(
        request,
        response,
        principal_id=principal_id,
        site_id=site_id,
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
    selected_site_id = str(auth.site_id or "").strip()
    try:
        data = serialize_portal_session(
            request,
            principal_id=auth.principal_id,
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
            principal_id=auth.principal_id,
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
    set_portal_session_cookies(
        request,
        response,
        principal_id=auth.principal_id,
        site_id=site_id,
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


@router.post("/account/pro-trial")
async def start_portal_account_pro_trial(request: Request) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
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
    account_id = _resolve_primary_portal_account_id(
        request,
        principal_id=auth.principal_id,
    )
    if isinstance(account_id, JSONResponse):
        return account_id
    try:
        result = _get_commercial_service(request).start_account_pro_trial(
            account_id=account_id,
            audit_context=_build_portal_audit_context(request, auth.principal_id),
        )
        session_data = serialize_portal_session(
            request,
            principal_id=auth.principal_id,
            site_id=auth.site_id,
            strict_site=False,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal Pro trial started",
        data={
            "account_id": account_id,
            "principal_id": auth.principal_id,
            **result,
            "session": session_data,
        },
    )


@router.post("/account/pro-monthly-order")
async def create_portal_account_pro_monthly_order(
    request: Request,
    payload: PortalProMonthlyOrderPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
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
    account_id = _resolve_primary_portal_account_id(
        request,
        principal_id=auth.principal_id,
    )
    if isinstance(account_id, JSONResponse):
        return account_id
    try:
        order = _get_commercial_service(request).create_account_pro_monthly_payment_order(
            account_id=account_id,
            provider=payload.provider,
            audit_context=_build_portal_audit_context(request, auth.principal_id),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal Pro monthly payment order created",
        data={
            "account_id": account_id,
            "principal_id": auth.principal_id,
            "order": order,
        },
    )


@router.get("/account/payment-orders")
async def list_portal_account_payment_orders(
    request: Request,
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    account_id = _resolve_primary_portal_account_id(
        request,
        principal_id=auth.principal_id,
    )
    if isinstance(account_id, JSONResponse):
        return account_id
    try:
        result = _get_commercial_service(request).list_account_payment_orders(
            account_id,
            limit=limit,
            offset=offset,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal account payment orders loaded",
        data={
            **result,
            "account_id": account_id,
            "principal_id": auth.principal_id,
        },
    )


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
            principal_id=auth.principal_id,
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
    audit_context = _build_portal_audit_context(request, auth.principal_id)
    try:
        result = service.provision_portal_site(
            account_id=payload.account_id,
            principal_id=auth.principal_id,
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


@router.post("/addon-connections")
async def create_portal_addon_connection(
    request: Request,
    payload: PortalAddonConnectionPayload,
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
    audit_context = _build_portal_audit_context(request, auth.principal_id)
    try:
        result = service.create_wordpress_addon_connection(
            account_id=payload.account_id,
            principal_id=auth.principal_id,
            wordpress_url=payload.wordpress_url,
            site_name=payload.site_name,
            return_url=payload.return_url,
            addon_state=payload.state,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)

    return _portal_route_envelope(
        message="wordpress addon connection issued",
        data=result,
    )


@router.post("/addon-connections/exchange")
async def exchange_portal_addon_connection(
    request: Request,
    payload: PortalAddonConnectionExchangePayload,
) -> Any:
    try:
        result = _get_commercial_service(request).consume_wordpress_addon_connection(
            code=payload.code,
            addon_state=payload.state,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)

    return _portal_route_envelope(
        message="wordpress addon connection exchanged",
        data=result,
    )


@router.post("/sites/{site_id}/activate")
async def activate_portal_site(request: Request, site_id: str) -> Any:
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
        principal_id=auth.principal_id,
        required_action=USER_ALLOWED_ACTION_REMOVE_SITES,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        result = _get_commercial_service(request).activate_portal_site(
            site_id,
            audit_context=_build_portal_audit_context(request, auth.principal_id),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal site activated",
        data=result,
    )


@router.post("/sites/{site_id}/deactivate")
async def deactivate_portal_site(request: Request, site_id: str) -> Any:
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
        principal_id=auth.principal_id,
        required_action=USER_ALLOWED_ACTION_REMOVE_SITES,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        site = _get_commercial_service(request).deactivate_portal_site(
            site_id,
            audit_context=_build_portal_audit_context(request, auth.principal_id),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal site deactivated",
        data={"site": site},
    )


@router.post("/sites/{site_id}/remove")
async def remove_portal_site(request: Request, site_id: str) -> Any:
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
        principal_id=auth.principal_id,
        required_action=USER_ALLOWED_ACTION_REMOVE_SITES,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        result = _get_commercial_service(request).remove_portal_site(
            site_id,
            audit_context=_build_portal_audit_context(request, auth.principal_id),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal site removed",
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
        principal_id=auth.principal_id,
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
        principal_id=auth.principal_id,
        required_roles=USER_SITE_KEY_WRITE_ROLES,
        required_action=USER_ALLOWED_ACTION_VIEW_USAGE,
    )
    if isinstance(access, JSONResponse):
        return access
    result = UsageService(_get_commercial_service(request).database_url).get_usage_summary(
        site_id=site_id
    )
    result["site_id"] = site_id
    result["account_id"] = str(access.get("account_id") or "")
    result["principal_id"] = auth.principal_id
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
        principal_id=auth.principal_id,
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
    result["principal_id"] = auth.principal_id
    result["identity_type"] = str(access.get("identity_type") or "")
    result["allowed_actions"] = [
        str(action) for action in _object_list(access.get("allowed_actions")) if str(action).strip()
    ]
    result["role"] = str(access.get("role") or "")
    return _portal_route_envelope(
        message="portal monitoring overview loaded",
        data=result,
    )


@router.get("/sites/{site_id}/diagnostic-advisor")
async def get_portal_site_diagnostic_advisor(
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
        principal_id=auth.principal_id,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        result = _get_portal_advisor_service(request).get_site_diagnostic_advisor(
            site_id=site_id,
            window_hours=window_hours,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    result["site_id"] = site_id
    result["account_id"] = str(access.get("account_id") or "")
    result["principal_id"] = auth.principal_id
    result["identity_type"] = str(access.get("identity_type") or "")
    result["allowed_actions"] = [
        str(action) for action in _object_list(access.get("allowed_actions")) if str(action).strip()
    ]
    result["role"] = str(access.get("role") or "")
    return _portal_route_envelope(
        message="portal diagnostic advisor loaded",
        data=result,
    )


@router.get("/sites/{site_id}/diagnostics")
async def get_portal_site_diagnostics(
    request: Request,
    site_id: str,
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
        principal_id=auth.principal_id,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        result = _get_commercial_service(request).get_portal_site_diagnostics(site_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    result["account_id"] = str(access.get("account_id") or "")
    result["principal_id"] = auth.principal_id
    result["identity_type"] = str(access.get("identity_type") or "")
    result["allowed_actions"] = [
        str(action) for action in _object_list(access.get("allowed_actions")) if str(action).strip()
    ]
    result["role"] = str(access.get("role") or "")
    return _portal_route_envelope(
        message="portal site diagnostics loaded",
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
        principal_id=auth.principal_id,
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
    result["principal_id"] = auth.principal_id
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
        principal_id=auth.principal_id,
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
    result["principal_id"] = auth.principal_id
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
        principal_id=auth.principal_id,
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
    result["principal_id"] = auth.principal_id
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
        principal_id=auth.principal_id,
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
            "principal_id": auth.principal_id,
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
        principal_id=auth.principal_id,
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
            "principal_id": auth.principal_id,
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
        principal_id=auth.principal_id,
        required_roles=USER_SITE_KEY_WRITE_ROLES,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
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
            "principal_id": auth.principal_id,
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


@router.get("/sites/{site_id}/credit-ledger")
async def get_portal_site_credit_ledger(
    request: Request,
    site_id: str,
    limit: int = Query(default=25, ge=1, le=50),
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
        principal_id=auth.principal_id,
        required_roles=USER_SITE_KEY_WRITE_ROLES,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        ledger = _get_commercial_service(request).get_portal_account_credit_ledger(
            str(access.get("account_id") or ""),
            limit=limit,
            offset=offset,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal credit ledger loaded",
        data={
            "site_id": site_id,
            "account_id": str(access.get("account_id") or ""),
            "principal_id": auth.principal_id,
            "identity_type": str(access.get("identity_type") or ""),
            "allowed_actions": [
                str(action)
                for action in _object_list(access.get("allowed_actions"))
                if str(action).strip()
            ],
            "role": str(access.get("role") or ""),
            **ledger,
        },
    )


@router.get("/sites/{site_id}/credit-packs")
async def list_portal_site_credit_packs(request: Request, site_id: str) -> Any:
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
        principal_id=auth.principal_id,
        required_roles=USER_SITE_KEY_WRITE_ROLES,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(access, JSONResponse):
        return access
    result = _get_commercial_service(request).list_credit_packs()
    return _portal_route_envelope(
        message="portal credit packs loaded",
        data={
            **result,
            "site_id": site_id,
            "account_id": str(access.get("account_id") or ""),
            "principal_id": auth.principal_id,
            "identity_type": str(access.get("identity_type") or ""),
            "role": str(access.get("role") or ""),
        },
    )


@router.get("/sites/{site_id}/payment-orders")
async def list_portal_site_payment_orders(
    request: Request,
    site_id: str,
    limit: int = Query(default=10, ge=1, le=50),
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
        principal_id=auth.principal_id,
        required_roles=USER_SITE_KEY_WRITE_ROLES,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        result = _get_commercial_service(request).list_account_payment_orders(
            str(access.get("account_id") or ""),
            site_id=site_id,
            limit=limit,
            offset=offset,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal payment orders loaded",
        data={
            **result,
            "site_id": site_id,
            "account_id": str(access.get("account_id") or ""),
            "principal_id": auth.principal_id,
            "identity_type": str(access.get("identity_type") or ""),
            "role": str(access.get("role") or ""),
        },
    )


@router.post("/sites/{site_id}/credit-pack-orders")
async def create_portal_site_credit_pack_order(
    request: Request,
    site_id: str,
    payload: PortalCreditPackOrderPayload,
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
        principal_id=auth.principal_id,
        required_roles=USER_SITE_KEY_WRITE_ROLES,
        required_action=USER_ALLOWED_ACTION_VIEW_BILLING,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        order = _get_commercial_service(request).create_credit_pack_payment_order(
            account_id=str(access.get("account_id") or ""),
            site_id=site_id,
            pack_id=payload.pack_id,
            provider=payload.provider,
            audit_context=_build_portal_audit_context(request, auth.principal_id),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal credit pack payment order created",
        data={
            "site_id": site_id,
            "account_id": str(access.get("account_id") or ""),
            "principal_id": auth.principal_id,
            "identity_type": str(access.get("identity_type") or ""),
            "role": str(access.get("role") or ""),
            "order": order,
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
        principal_id=auth.principal_id,
        required_roles=USER_SITE_KEY_WRITE_ROLES,
        required_action=USER_ALLOWED_ACTION_VIEW_AUDIT,
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
            "principal_id": auth.principal_id,
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
        principal_id=auth.principal_id,
        required_roles=USER_SITE_KEY_WRITE_ROLES,
        required_action=USER_ALLOWED_ACTION_VIEW_AUDIT,
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
            "principal_id": auth.principal_id,
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
        principal_id=auth.principal_id,
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
            "principal_id": auth.principal_id,
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
        principal_id=auth.principal_id,
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
            "principal_id": auth.principal_id,
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
        principal_id=auth.principal_id,
        required_roles=USER_SITE_KEY_WRITE_ROLES,
        required_action=USER_ALLOWED_ACTION_MANAGE_SITE_KEYS,
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
        principal_id=auth.principal_id,
        required_roles=USER_SITE_KEY_WRITE_ROLES,
        required_action=USER_ALLOWED_ACTION_MANAGE_SITE_KEYS,
    )
    if isinstance(access, JSONResponse):
        return access

    service = _get_commercial_service(request)
    audit_context = _build_portal_audit_context(request, auth.principal_id)

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
        principal_id=auth.principal_id,
        required_roles=USER_SITE_KEY_WRITE_ROLES,
        required_action=USER_ALLOWED_ACTION_MANAGE_SITE_KEYS,
    )
    if isinstance(access, JSONResponse):
        return access

    service = _get_commercial_service(request)
    audit_context = _build_portal_audit_context(request, auth.principal_id)

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
        principal_id=auth.principal_id,
        required_roles=USER_SITE_KEY_WRITE_ROLES,
        required_action=USER_ALLOWED_ACTION_MANAGE_SITE_KEYS,
    )
    if isinstance(access, JSONResponse):
        return access

    service = _get_commercial_service(request)
    audit_context = _build_portal_audit_context(request, auth.principal_id)

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
