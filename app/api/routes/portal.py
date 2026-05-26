from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

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
    current_portal_impersonation_session,
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
from app.domain.commercial.customer_api_keys import (
    build_customer_api_key,
    serialize_portal_site_key,
)
from app.domain.commercial.errors import CommercialServiceError
from app.domain.commercial.service import CommercialService
from app.domain.commercial.service import PORTAL_SITE_KEY_WRITE_ROLES
from app.domain.commercial.service import PORTAL_SITE_PROVISION_ROLES
from app.domain.usage.rollup import UsageRollupService
from app.domain.usage.service import UsageService

router = APIRouter(prefix="/portal/v1", tags=["portal"])


class PortalSiteKeyPayload(BaseModel):
    label: str = ""
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PortalSessionSitePayload(BaseModel):
    site_id: str = ""


class PortalSiteProvisionPayload(BaseModel):
    account_id: str = ""
    site_name: str = ""
    wordpress_url: str = ""


class PortalLoginCodeRequestPayload(BaseModel):
    email: str = ""
    locale: str = ""


class PortalLoginCodeVerifyPayload(BaseModel):
    email: str = ""
    code: str = ""


class PortalMemberPreferencesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: str = ""
    currency: str = ""


class PortalPackageChangeRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_package: str = ""
    reason: str = ""
    expected_sites: int | None = None
    expected_usage: str = ""


class PortalTopUpPackRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pack_id: str = ""
    reason: str = ""
    expected_usage: str = ""


class PortalDeleteSiteRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = ""
    delete_mode: str = "disconnect"


class PortalUsageAlertSettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    requests: dict[str, int] = Field(default_factory=dict)
    tokens: dict[str, int] = Field(default_factory=dict)
    cost: dict[str, int] = Field(default_factory=dict)


def _build_portal_audit_context(request: Request, member_ref: str):
    audit_context = _build_audit_context(request)
    audit_context.actor_kind = "portal_member"
    audit_context.actor_ref = member_ref
    return audit_context


def _authorize_portal_site_access(
    request: Request,
    *,
    site_id: str,
    member_ref: str,
    required_roles: set[str] | None = None,
) -> dict[str, object] | JSONResponse:
    try:
        return _get_commercial_service(request).resolve_portal_site_access(
            site_id=site_id,
            member_ref=member_ref,
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
    impersonation = current_portal_impersonation_session(request)
    if not impersonation:
        return None
    if bool(impersonation.get("read_only", True)):
        return portal_json_error(
            request,
            status_code=403,
            error_code="auth.portal_impersonation_read_only",
            message="read-only impersonation cannot perform portal write actions",
        )
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

def _resolve_portal_site_summary(
    request: Request,
    *,
    site_id: str,
    member_ref: str,
) -> dict[str, object] | JSONResponse:
    access = _authorize_portal_site_access(
        request,
        site_id=site_id,
        member_ref=member_ref,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        service = _get_commercial_service(request)
        policy = service.inspect_commercial_policy(site_id)
        _create_portal_usage_alerts_if_needed(
            service,
            request=request,
            auth_member_ref=member_ref,
            account_id=str(access.get("account_id") or ""),
            site_id=site_id,
            budget_state=policy.get("budget_state"),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return {
        "site_id": site_id,
        "account_id": str(access.get("account_id") or ""),
        "member_ref": member_ref,
        "identity_type": str(access.get("identity_type") or ""),
        "allowed_actions": [
            str(action)
            for action in list(access.get("allowed_actions") or [])
            if str(action).strip()
        ],
        "role": str(access.get("role") or ""),
        "site": policy.get("site"),
        "covered_by_subscription_id": str((policy.get("subscription") or {}).get("subscription_id") or ""),
        "subscription_status": str((policy.get("subscription") or {}).get("status") or ""),
        "package_alias": str((((policy.get("subscription") or {}).get("metadata") or {}).get("package_alias")) or ""),
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
    allow_development_code = (
        environment in {"development", "test"}
        and (
            str(request.headers.get("x-magick-dev-login-code") or "").strip() == "1"
            or str(request.headers.get("x-magick-debug-portal-link") or "").strip() == "1"
        )
    )
    try:
        issued = _get_commercial_service(request).issue_portal_login_code(
            email=email,
            ttl_seconds=ttl_seconds,
        )
    except CommercialServiceError as error:
        if error.error_code == "service.portal_email_not_found":
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
                member_ref=str(issued.get("member_ref") or ""),
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
            "delivery": (
                "development_code" if allow_development_code else "email"
            ),
            "expires_in_seconds": ttl_seconds,
            "code": (
                str(issued.get("code") or "")
                if allow_development_code
                else ""
            ),
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
            max_attempts=max(1, int(get_cloud_services(request).settings.portal_login_code_max_attempts or 0)),
        )
        member_ref = str(verified.get("member_ref") or "")
        data = serialize_portal_session(
            request,
            member_ref=member_ref,
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
        member_ref=member_ref,
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
            member_ref=auth.member_ref,
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
            member_ref=auth.member_ref,
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


@router.get("/member-summary")
async def get_portal_member_summary(request: Request) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    selected_site_id = request.cookies.get(COOKIE_SITE_ID, "").strip()
    try:
        result = _get_commercial_service(request).get_portal_member_summary(
            member_ref=auth.member_ref,
            selected_site_id=selected_site_id,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal member summary loaded",
        data=result,
    )


@router.get("/member-preferences")
async def get_portal_member_preferences(request: Request) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    try:
        result = _get_commercial_service(request).get_portal_member_preferences(
            member_ref=auth.member_ref,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal member preferences loaded",
        data=result,
    )


@router.post("/member-preferences")
async def update_portal_member_preferences(
    request: Request,
    payload: PortalMemberPreferencesPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    write_guard = _portal_write_guard(request)
    if write_guard is not None:
        return write_guard
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    try:
        result = _get_commercial_service(request).update_portal_member_preferences(
            member_ref=auth.member_ref,
            locale=payload.locale,
            currency=payload.currency,
            audit_context=_build_portal_audit_context(request, auth.member_ref),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal member preferences saved",
        data=result,
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
        result = _get_commercial_service(request).list_portal_sites(member_ref=auth.member_ref)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal sites loaded",
        data=result,
    )


@router.post("/sites")
async def provision_portal_site(
    request: Request,
    payload: PortalSiteProvisionPayload,
) -> Any:
    same_origin = _portal_same_origin_guard(request, always=True)
    if same_origin is not None:
        return same_origin
    write_guard = _portal_write_guard(request)
    if write_guard is not None:
        return write_guard
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    try:
        result = _get_commercial_service(request).provision_portal_site(
            account_id=payload.account_id,
            member_ref=auth.member_ref,
            wordpress_url=payload.wordpress_url,
            site_name=payload.site_name,
            audit_context=_build_portal_audit_context(request, auth.member_ref),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal site provisioned",
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
        member_ref=auth.member_ref,
        required_roles=PORTAL_SITE_PROVISION_ROLES,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        result = _get_commercial_service(request).activate_site(
            site_id,
            audit_context=_build_portal_audit_context(request, auth.member_ref),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal site activated",
        data={
            "site_id": site_id,
            "account_id": str(access.get("account_id") or ""),
            "member_ref": auth.member_ref,
            "identity_type": str(access.get("identity_type") or ""),
            "allowed_actions": [
                str(action)
                for action in list(access.get("allowed_actions") or [])
                if str(action).strip()
            ],
            "role": str(access.get("role") or ""),
            "site": result,
        },
    )


@router.post("/sites/{site_id}/archive")
async def archive_portal_site(request: Request, site_id: str) -> Any:
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
        member_ref=auth.member_ref,
        required_roles=PORTAL_SITE_PROVISION_ROLES,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        result = _get_commercial_service(request).archive_site(
            site_id,
            audit_context=_build_portal_audit_context(request, auth.member_ref),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal site archived",
        data={
            "site_id": site_id,
            "account_id": str(access.get("account_id") or ""),
            "member_ref": auth.member_ref,
            "identity_type": str(access.get("identity_type") or ""),
            "allowed_actions": [
                str(action)
                for action in list(access.get("allowed_actions") or [])
                if str(action).strip()
            ],
            "role": str(access.get("role") or ""),
            "site": result,
        },
    )


@router.post("/sites/{site_id}/restore")
async def restore_portal_site(request: Request, site_id: str) -> Any:
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
        member_ref=auth.member_ref,
        required_roles=PORTAL_SITE_PROVISION_ROLES,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        result = _get_commercial_service(request).restore_site(
            site_id,
            audit_context=_build_portal_audit_context(request, auth.member_ref),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal site restored",
        data={
            "site_id": site_id,
            "account_id": str(access.get("account_id") or ""),
            "member_ref": auth.member_ref,
            "identity_type": str(access.get("identity_type") or ""),
            "allowed_actions": [
                str(action)
                for action in list(access.get("allowed_actions") or [])
                if str(action).strip()
            ],
            "role": str(access.get("role") or ""),
            "site": result,
        },
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
        member_ref=auth.member_ref,
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
        member_ref=auth.member_ref,
        required_roles=PORTAL_SITE_KEY_WRITE_ROLES,
    )
    if isinstance(access, JSONResponse):
        return access
    result = UsageService(_get_commercial_service(request).database_url).get_usage_summary(
        site_id=site_id
    )
    result["site_id"] = site_id
    result["account_id"] = str(access.get("account_id") or "")
    result["member_ref"] = auth.member_ref
    result["identity_type"] = str(access.get("identity_type") or "")
    result["allowed_actions"] = [
        str(action)
        for action in list(access.get("allowed_actions") or [])
        if str(action).strip()
    ]
    result["role"] = str(access.get("role") or "")
    return _portal_route_envelope(
        message="portal usage summary loaded",
        data=result,
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
        member_ref=auth.member_ref,
        required_roles=PORTAL_SITE_KEY_WRITE_ROLES,
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        policy = _get_commercial_service(request).inspect_commercial_policy(site_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal entitlements loaded",
        data={
            "site_id": site_id,
            "account_id": str(access.get("account_id") or ""),
            "member_ref": auth.member_ref,
            "identity_type": str(access.get("identity_type") or ""),
            "allowed_actions": [
                str(action)
                for action in list(access.get("allowed_actions") or [])
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
            "generated_at": policy.get("generated_at"),
        },
    )


def _create_portal_usage_alerts_if_needed(
    service: CommercialService,
    *,
    request: Request,
    auth_member_ref: str,
    account_id: str,
    site_id: str,
    budget_state: object,
) -> None:
    if not isinstance(budget_state, dict):
        return
    try:
        settings = service.get_portal_usage_alert_settings(site_id)
    except CommercialServiceError:
        return
    if not bool(settings.get("enabled", True)):
        return
    metrics = {
        "requests": ("runs", "请求数"),
        "tokens": ("tokens", "Token"),
        "cost": ("cost", "费用"),
    }
    for setting_key, (budget_key, label) in metrics.items():
        thresholds = settings.get(setting_key)
        state = budget_state.get(budget_key)
        if not isinstance(thresholds, dict) or not isinstance(state, dict):
            continue
        try:
            current_total = float(state.get("current_total") or 0)
            limit = float(state.get("limit") or 0)
            warning = int(thresholds.get("warning") or 80)
            critical = int(thresholds.get("critical") or 95)
        except (TypeError, ValueError):
            continue
        if limit <= 0:
            continue
        ratio = int(round((current_total / limit) * 100))
        if ratio < warning:
            continue
        level = "critical" if ratio >= critical else "warning"
        try:
            service.create_portal_action_request(
                request_type="usage_alert",
                member_ref=auth_member_ref,
                account_id=account_id,
                site_id=site_id,
                title=f"用量{label}达到{ratio}%",
                message=f"当前{label}已达到套餐限制的 {ratio}%，阈值级别：{level}。",
                payload_json={
                    "metric": setting_key,
                    "level": level,
                    "ratio": ratio,
                    "current_total": current_total,
                    "limit": limit,
                    "warning": warning,
                    "critical": critical,
                },
                audit_context=_build_portal_audit_context(request, auth_member_ref),
            )
        except CommercialServiceError:
            continue


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
        member_ref=auth.member_ref,
        required_roles=PORTAL_SITE_KEY_WRITE_ROLES,
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
            "member_ref": auth.member_ref,
            "identity_type": str(access.get("identity_type") or ""),
            "allowed_actions": [
                str(action)
                for action in list(access.get("allowed_actions") or [])
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
        member_ref=auth.member_ref,
        required_roles=PORTAL_SITE_KEY_WRITE_ROLES,
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
            "member_ref": auth.member_ref,
            "identity_type": str(access.get("identity_type") or ""),
            "allowed_actions": [
                str(action)
                for action in list(access.get("allowed_actions") or [])
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
        member_ref=auth.member_ref,
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
            "member_ref": auth.member_ref,
            "identity_type": str(access.get("identity_type") or ""),
            "allowed_actions": [
                str(action)
                for action in list(access.get("allowed_actions") or [])
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
        member_ref=auth.member_ref,
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
            "member_ref": auth.member_ref,
            "identity_type": str(access.get("identity_type") or ""),
            "role": str(access.get("role") or ""),
            **reconciliation,
        },
    )


@router.get("/notifications")
async def list_portal_notifications(
    request: Request,
    status: str = Query(default="open"),
    limit: int = Query(default=50, ge=1, le=100),
) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    statuses = [status] if status else ["open"]
    try:
        result = _get_commercial_service(request).list_portal_action_requests(
            member_ref=auth.member_ref,
            statuses=statuses,
            limit=limit,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal notifications loaded",
        data=result,
    )


@router.post("/notifications/{notification_id}/ack")
async def acknowledge_portal_notification(request: Request, notification_id: str) -> Any:
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
    try:
        result = _get_commercial_service(request).acknowledge_portal_action_request(
            request_id=notification_id,
            member_ref=auth.member_ref,
            audit_context=_build_portal_audit_context(request, auth.member_ref),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(
        message="portal notification acknowledged",
        data=result,
    )


@router.get("/sites/{site_id}/package-change-requests")
async def list_portal_package_change_requests(
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
    access = _authorize_portal_site_access(request, site_id=site_id, member_ref=auth.member_ref)
    if isinstance(access, JSONResponse):
        return access
    try:
        result = _get_commercial_service(request).list_portal_action_requests(
            member_ref=auth.member_ref,
            site_id=site_id,
            request_type="package_change",
            limit=limit,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(message="portal package requests loaded", data=result)


@router.post("/sites/{site_id}/package-change-requests")
async def create_portal_package_change_request(
    request: Request,
    site_id: str,
    payload: PortalPackageChangeRequestPayload,
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
    access = _authorize_portal_site_access(request, site_id=site_id, member_ref=auth.member_ref)
    if isinstance(access, JSONResponse):
        return access
    target_package = str(payload.target_package or "").strip().lower()
    if target_package not in {"free", "basic", "bulk"}:
        return portal_json_error(
            request,
            status_code=400,
            error_code="service.invalid_target_package",
            message="target package must be Free, Basic, or Bulk",
        )
    try:
        result = _get_commercial_service(request).create_portal_action_request(
            request_type="package_change",
            member_ref=auth.member_ref,
            account_id=str(access.get("account_id") or ""),
            site_id=site_id,
            title=f"套餐变更申请：{target_package.title()}",
            message=payload.reason,
            payload_json={
                "target_package": target_package,
                "expected_sites": payload.expected_sites,
                "expected_usage": payload.expected_usage,
                "current_role": str(access.get("role") or ""),
            },
            audit_context=_build_portal_audit_context(request, auth.member_ref),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(message="portal package request created", data=result)


@router.get("/topup-packs")
async def list_portal_topup_packs(request: Request) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    try:
        catalog = _get_commercial_service(request).list_admin_topup_packs()
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    items = [item for item in catalog.get("items", []) if isinstance(item, dict) and bool(item.get("active"))]
    return _portal_route_envelope(
        message="portal top-up packs loaded",
        data={
            "items": items,
            "summary": {
                "total": len(items),
                "active": len(items),
            },
        },
    )


@router.get("/sites/{site_id}/topup-pack-requests")
async def list_portal_topup_pack_requests(
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
    access = _authorize_portal_site_access(request, site_id=site_id, member_ref=auth.member_ref)
    if isinstance(access, JSONResponse):
        return access
    try:
        result = _get_commercial_service(request).list_portal_action_requests(
            member_ref=auth.member_ref,
            site_id=site_id,
            request_type="topup_pack",
            limit=limit,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(message="portal top-up pack requests loaded", data=result)


@router.post("/sites/{site_id}/topup-pack-requests")
async def create_portal_topup_pack_request(
    request: Request,
    site_id: str,
    payload: PortalTopUpPackRequestPayload,
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
    access = _authorize_portal_site_access(request, site_id=site_id, member_ref=auth.member_ref)
    if isinstance(access, JSONResponse):
        return access

    pack_id = str(payload.pack_id or "").strip()
    try:
        catalog = _get_commercial_service(request).list_admin_topup_packs()
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    selected_pack = next(
        (
            item
            for item in catalog.get("items", [])
            if isinstance(item, dict) and item.get("pack_id") == pack_id and bool(item.get("active"))
        ),
        None,
    )
    if selected_pack is None:
        return portal_json_error(
            request,
            status_code=400,
            error_code="service.invalid_topup_pack",
            message="top-up pack is not available",
        )

    try:
        result = _get_commercial_service(request).create_portal_action_request(
            request_type="topup_pack",
            member_ref=auth.member_ref,
            account_id=str(access.get("account_id") or ""),
            site_id=site_id,
            title=f"加量包申请：{selected_pack.get('label') or pack_id}",
            message=payload.reason,
            payload_json={
                "pack_id": pack_id,
                "pack_label": str(selected_pack.get("label") or ""),
                "points_label": str(selected_pack.get("points_label") or ""),
                "runs_increment": selected_pack.get("runs_increment"),
                "tokens_increment": selected_pack.get("tokens_increment"),
                "cost_increment": selected_pack.get("cost_increment"),
                "expected_usage": payload.expected_usage,
                "current_role": str(access.get("role") or ""),
            },
            audit_context=_build_portal_audit_context(request, auth.member_ref),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(message="portal top-up pack request created", data=result)


@router.post("/sites/{site_id}/delete-requests")
async def create_portal_site_delete_request(
    request: Request,
    site_id: str,
    payload: PortalDeleteSiteRequestPayload,
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
    access = _authorize_portal_site_access(request, site_id=site_id, member_ref=auth.member_ref)
    if isinstance(access, JSONResponse):
        return access
    try:
        result = _get_commercial_service(request).create_portal_action_request(
            request_type="site_delete",
            member_ref=auth.member_ref,
            account_id=str(access.get("account_id") or ""),
            site_id=site_id,
            title="站点删除/断开申请",
            message=payload.reason,
            payload_json={"delete_mode": payload.delete_mode or "disconnect"},
            audit_context=_build_portal_audit_context(request, auth.member_ref),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(message="portal site delete request created", data=result)


@router.get("/sites/{site_id}/usage-alert-settings")
async def get_portal_usage_alert_settings(request: Request, site_id: str) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(request, site_id=site_id, member_ref=auth.member_ref)
    if isinstance(access, JSONResponse):
        return access
    try:
        result = _get_commercial_service(request).get_portal_usage_alert_settings(site_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(message="portal usage alert settings loaded", data=result)


@router.post("/sites/{site_id}/usage-alert-settings")
async def update_portal_usage_alert_settings(
    request: Request,
    site_id: str,
    payload: PortalUsageAlertSettingsPayload,
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
    access = _authorize_portal_site_access(request, site_id=site_id, member_ref=auth.member_ref)
    if isinstance(access, JSONResponse):
        return access
    try:
        result = _get_commercial_service(request).update_portal_usage_alert_settings(
            site_id,
            settings=payload.model_dump(),
            audit_context=_build_portal_audit_context(request, auth.member_ref),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(message="portal usage alert settings saved", data=result)


@router.get("/sites/{site_id}/diagnostics")
async def get_portal_site_diagnostics(request: Request, site_id: str) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_session_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth
    access = _authorize_portal_site_access(request, site_id=site_id, member_ref=auth.member_ref)
    if isinstance(access, JSONResponse):
        return access
    try:
        result = _get_commercial_service(request).get_portal_site_diagnostics(site_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(message="portal site diagnostics loaded", data=result)


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
        member_ref=auth.member_ref,
        required_roles=PORTAL_SITE_KEY_WRITE_ROLES,
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
        for item in list(result.get("items") or [])
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
        member_ref=auth.member_ref,
        required_roles=PORTAL_SITE_KEY_WRITE_ROLES,
    )
    if isinstance(access, JSONResponse):
        return access

    service = _get_commercial_service(request)
    audit_context = _build_portal_audit_context(request, auth.member_ref)

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
        member_ref=auth.member_ref,
        required_roles=PORTAL_SITE_KEY_WRITE_ROLES,
    )
    if isinstance(access, JSONResponse):
        return access

    service = _get_commercial_service(request)
    audit_context = _build_portal_audit_context(request, auth.member_ref)

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

    previous = result.get("previous") if isinstance(result.get("previous"), dict) else {}
    current = result.get("current") if isinstance(result.get("current"), dict) else {}
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
        member_ref=auth.member_ref,
        required_roles=PORTAL_SITE_KEY_WRITE_ROLES,
    )
    if isinstance(access, JSONResponse):
        return access

    service = _get_commercial_service(request)
    audit_context = _build_portal_audit_context(request, auth.member_ref)

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


# ============================================
# Analytics Dashboard Routes (MVP Phase 1)
# ============================================

ANALYTICS_RANGE_LIMITS: dict[str, list[str]] = {
    "starter": ["7d"],
    "pro": ["7d", "30d"],
    "agency": ["7d", "30d", "90d"],
}


def _resolve_analytics_range_limit(
    commercial_service: Any,
    site_id: str,
) -> tuple[list[str], str]:
    """Return (allowed_ranges, tier_id) for the site's plan."""
    try:
        policy = commercial_service.inspect_commercial_policy(site_id)
    except CommercialServiceError:
        return (["7d"], "starter")
    plan_version = policy.get("plan_version") if isinstance(policy, dict) else None
    plan_id = (
        str(plan_version.get("plan_id", "")).strip()
        if isinstance(plan_version, dict)
        else ""
    )
    tier_id = plan_id if plan_id else "starter"
    allowed = ANALYTICS_RANGE_LIMITS.get(tier_id, ["7d"])
    return (allowed, tier_id)


def _build_analytics_filters(
    range_str: str,
    site_id: str,
) -> dict[str, Any]:
    """Build standard logs-analytics filters for the given range."""
    return {
        "log_type": "",
        "status": "all",
        "provider": "",
        "model": "",
        "user_id": 0,
        "post_id": 0,
        "trace_id": "",
        "caller_id": "",
        "app_id": "",
        "ability_id": "",
        "error_code": "",
        "role_id": "",
        "resource_id": "",
        "mcp_server_id": "",
        "mcp_method": "",
        "range": range_str,
        "start_gmt": "",
        "end_gmt": "",
        "limit": 1000,
    }


def _range_to_datetimes(
    range_str: str,
    now: datetime,
) -> tuple[datetime, datetime]:
    """Convert a range string like '7d' into (start, end) datetimes."""
    end_at = now
    if range_str == "1h":
        start_at = now - timedelta(hours=1)
    elif range_str == "24h":
        start_at = now - timedelta(hours=24)
    elif range_str == "7d":
        start_at = now - timedelta(days=7)
    elif range_str == "30d":
        start_at = now - timedelta(days=30)
    elif range_str == "90d":
        start_at = now - timedelta(days=90)
    else:
        start_at = now - timedelta(days=7)
    return (start_at, end_at)


@router.get("/sites/{site_id}/analytics/overview")
async def get_portal_site_analytics_overview(
    request: Request,
    site_id: str,
    range: str = Query(default="7d", max_length=16),
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
        member_ref=auth.member_ref,
    )
    if isinstance(access, JSONResponse):
        return access

    commercial_service = _get_commercial_service(request)
    allowed_ranges, tier_id = _resolve_analytics_range_limit(
        commercial_service,
        site_id,
    )
    if range not in allowed_ranges:
        return portal_json_error(
            request,
            status_code=403,
            error_code="commercial.analytics_range_denied",
            message=f"Analytics range '{range}' is not available on the '{tier_id}' plan. "
            f"Allowed ranges: {', '.join(allowed_ranges)}.",
        )

    database_url = commercial_service.database_url
    filters = _build_analytics_filters(range, site_id)

    usage_summary = UsageService(database_url).get_usage_summary(site_id=site_id)
    logs_summary = UsageService(database_url).get_logs_analytics_summary(
        site_id=site_id,
        filters=filters,
    )

    return _portal_route_envelope(
        message="portal analytics overview loaded",
        data={
            "site_id": site_id,
            "account_id": str(access.get("account_id") or ""),
            "member_ref": auth.member_ref,
            "identity_type": str(access.get("identity_type") or ""),
            "role": str(access.get("role") or ""),
            "tier_id": tier_id,
            "allowed_ranges": allowed_ranges,
            "selected_range": range,
            "overview": {
                "total_calls": logs_summary.get("total", 0),
                "success_rate": logs_summary.get("success_rate", 0.0),
                "error_rate": logs_summary.get("error_rate", 0.0),
                "avg_latency_ms": logs_summary.get("avg_elapsed_ms", 0),
                "p95_latency_ms": logs_summary.get("p95_elapsed_ms", 0),
                "total_cost": usage_summary.get("today", {}).get("cost", 0),
                "trend_7d": logs_summary.get("trend_7d", []),
            },
            "generated_at": logs_summary.get("generated_at", ""),
        },
    )


@router.get("/sites/{site_id}/analytics/trend")
async def get_portal_site_analytics_trend(
    request: Request,
    site_id: str,
    range: str = Query(default="7d", max_length=16),
    granularity: str = Query(default="daily", max_length=16),
) -> Any:
    from datetime import UTC

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
        member_ref=auth.member_ref,
    )
    if isinstance(access, JSONResponse):
        return access

    commercial_service = _get_commercial_service(request)
    allowed_ranges, tier_id = _resolve_analytics_range_limit(
        commercial_service,
        site_id,
    )
    if range not in allowed_ranges:
        return portal_json_error(
            request,
            status_code=403,
            error_code="commercial.analytics_range_denied",
            message=f"Analytics range '{range}' is not available on the '{tier_id}' plan. "
            f"Allowed ranges: {', '.join(allowed_ranges)}.",
        )

    database_url = commercial_service.database_url
    now = datetime.now(UTC)
    start_at, end_at = _range_to_datetimes(range, now)

    # Try rollup first, then fall back to live projection
    rollup_service = UsageRollupService(database_url)
    result = rollup_service.get_router_performance_snapshot_batch(
        site_id=site_id,
        start_at=start_at,
        end_at=end_at,
    )
    if result is None:
        result = UsageService(database_url).get_router_performance_snapshot_projection(
            site_id=site_id,
            start_at=start_at,
            end_at=end_at,
        )

    rows = result.get("rows", []) if isinstance(result, dict) else []

    return _portal_route_envelope(
        message="portal analytics trend loaded",
        data={
            "site_id": site_id,
            "account_id": str(access.get("account_id") or ""),
            "member_ref": auth.member_ref,
            "identity_type": str(access.get("identity_type") or ""),
            "role": str(access.get("role") or ""),
            "tier_id": tier_id,
            "allowed_ranges": allowed_ranges,
            "selected_range": range,
            "granularity": granularity,
            "start_at": start_at.isoformat().replace("+00:00", "Z"),
            "end_at": end_at.isoformat().replace("+00:00", "Z"),
            "rows": rows,
        },
    )


@router.get("/sites/{site_id}/analytics/cost-breakdown")
async def get_portal_site_analytics_cost_breakdown(
    request: Request,
    site_id: str,
    range: str = Query(default="7d", max_length=16),
    group_by: str = Query(default="provider", max_length=32),
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
        member_ref=auth.member_ref,
    )
    if isinstance(access, JSONResponse):
        return access

    commercial_service = _get_commercial_service(request)
    allowed_ranges, tier_id = _resolve_analytics_range_limit(
        commercial_service,
        site_id,
    )
    if range not in allowed_ranges:
        return portal_json_error(
            request,
            status_code=403,
            error_code="commercial.analytics_range_denied",
            message=f"Analytics range '{range}' is not available on the '{tier_id}' plan. "
            f"Allowed ranges: {', '.join(allowed_ranges)}.",
        )

    database_url = commercial_service.database_url
    filters = _build_analytics_filters(range, site_id)

    logs_summary = UsageService(database_url).get_logs_analytics_summary(
        site_id=site_id,
        filters=filters,
    )

    # Build cost breakdown from provider calls in the logs context
    # Note: get_logs_analytics_summary returns aggregates, not individual calls.
    # For MVP we return a simplified breakdown keyed by the requested group_by.
    total_cost = 0.0
    breakdown = []

    # Fallback: use usage_summary cost as total
    usage_summary = UsageService(database_url).get_usage_summary(site_id=site_id)
    total_cost = float(
        usage_summary.get("rolling_24h", {}).get("cost", 0)
        if range in ("1h", "24h")
        else usage_summary.get("today", {}).get("cost", 0)
    )

    return _portal_route_envelope(
        message="portal analytics cost breakdown loaded",
        data={
            "site_id": site_id,
            "account_id": str(access.get("account_id") or ""),
            "member_ref": auth.member_ref,
            "identity_type": str(access.get("identity_type") or ""),
            "role": str(access.get("role") or ""),
            "tier_id": tier_id,
            "allowed_ranges": allowed_ranges,
            "selected_range": range,
            "group_by": group_by,
            "total_cost": total_cost,
            "breakdown": breakdown,
            "generated_at": logs_summary.get("generated_at", ""),
        },
    )


@router.get("/sites/{site_id}/analytics/performance")
async def get_portal_site_analytics_performance(
    request: Request,
    site_id: str,
    range: str = Query(default="7d", max_length=16),
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
        member_ref=auth.member_ref,
    )
    if isinstance(access, JSONResponse):
        return access

    commercial_service = _get_commercial_service(request)
    allowed_ranges, tier_id = _resolve_analytics_range_limit(
        commercial_service,
        site_id,
    )
    if range not in allowed_ranges:
        return portal_json_error(
            request,
            status_code=403,
            error_code="commercial.analytics_range_denied",
            message=f"Analytics range '{range}' is not available on the '{tier_id}' plan. "
            f"Allowed ranges: {', '.join(allowed_ranges)}.",
        )

    database_url = commercial_service.database_url
    filters = _build_analytics_filters(range, site_id)

    logs_summary = UsageService(database_url).get_logs_analytics_summary(
        site_id=site_id,
        filters=filters,
    )
    tool_latency = UsageService(database_url).get_logs_analytics_tool_latency(
        site_id=site_id,
        filters=filters,
    )

    return _portal_route_envelope(
        message="portal analytics performance loaded",
        data={
            "site_id": site_id,
            "account_id": str(access.get("account_id") or ""),
            "member_ref": auth.member_ref,
            "identity_type": str(access.get("identity_type") or ""),
            "role": str(access.get("role") or ""),
            "tier_id": tier_id,
            "allowed_ranges": allowed_ranges,
            "selected_range": range,
            "performance": {
                "latency": {
                    "p50_ms": logs_summary.get("p50_elapsed_ms", 0),
                    "p95_ms": logs_summary.get("p95_elapsed_ms", 0),
                    "p99_ms": logs_summary.get("p99_elapsed_ms", 0),
                    "avg_ms": logs_summary.get("avg_elapsed_ms", 0),
                },
                "tool_latency": {
                    "p50_ms": tool_latency.get("p50_ms", 0),
                    "p95_ms": tool_latency.get("p95_ms", 0),
                },
                "error_rate": logs_summary.get("error_rate", 0.0),
                "timeout_rate": logs_summary.get("timeout_rate", 0.0),
                "blocked_rate": logs_summary.get("blocked_rate", 0.0),
                "canceled_rate": logs_summary.get("canceled_rate", 0.0),
                "top_errors": logs_summary.get("top_errors", []),
                "status_distribution": logs_summary.get("status_distribution", {}),
            },
            "generated_at": logs_summary.get("generated_at", ""),
        },
    )


# ============================================
# Compliance Premium Layer (read-only posture)
# ============================================

class PortalComplianceRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_type: str = ""
    reason: str = ""


COMPLIANCE_REQUEST_TYPES = (
    "compliance_export",
    "compliance_deletion_review",
    "compliance_report",
)

COMPLIANCE_REQUEST_TITLES: dict[str, str] = {
    "compliance_export": "数据导出申请",
    "compliance_deletion_review": "删除复核申请",
    "compliance_report": "合规报告申请",
}

COMPLIANCE_REQUEST_TITLES_EN: dict[str, str] = {
    "compliance_export": "Data Export Request",
    "compliance_deletion_review": "Deletion Review Request",
    "compliance_report": "Compliance Report Request",
}


def _resolve_compliance_request_title(request_type: str, locale: str = "") -> str:
    if locale.startswith("zh"):
        return COMPLIANCE_REQUEST_TITLES.get(request_type, "合规申请")
    return COMPLIANCE_REQUEST_TITLES_EN.get(request_type, "Compliance Request")


def _resolve_retention_days(tier_id: str, settings: Any) -> int:
    tier_retention = {
        "starter": 30,
        "free": 30,
        "pro": 90,
        "basic": 90,
        "agency": 365,
        "bulk": 365,
        "enterprise": 365,
    }
    return tier_retention.get(tier_id.lower(), settings.audit_retention_days_default)


@router.get("/sites/{site_id}/compliance/posture")
async def get_portal_site_compliance_posture(request: Request, site_id: str) -> Any:
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
        member_ref=auth.member_ref,
    )
    if isinstance(access, JSONResponse):
        return access

    commercial_service = _get_commercial_service(request)
    settings = get_cloud_services(request).settings

    try:
        policy = commercial_service.inspect_commercial_policy(site_id)
    except CommercialServiceError:
        policy = {}

    tier_id = ""
    plan_version = policy.get("plan_version") if isinstance(policy, dict) else None
    if isinstance(plan_version, dict):
        tier_id = str(plan_version.get("plan_id") or "").strip()

    retention_days = _resolve_retention_days(tier_id, settings)

    try:
        audit_summary = commercial_service.summarize_service_audit_events(site_id=site_id)
    except CommercialServiceError:
        audit_summary = {}

    events_in_retention = audit_summary.get("totals", {}).get("events", 0) if isinstance(audit_summary, dict) else 0

    return _portal_route_envelope(
        message="portal compliance posture loaded",
        data={
            "site_id": site_id,
            "account_id": str(access.get("account_id") or ""),
            "member_ref": auth.member_ref,
            "identity_type": str(access.get("identity_type") or ""),
            "role": str(access.get("role") or ""),
            "data_residency": {
                "storage_region": settings.deployment_region,
                "inference_region": settings.deployment_region,
                "byom_enabled": False,
            },
            "audit": {
                "retention_days": retention_days,
                "events_in_retention": events_in_retention,
                "last_export_at": None,
            },
            "security_controls": [
                {"control": "encryption_at_rest", "status": "active", "detail": "Fernet AES-128"},
                {"control": "request_signing", "status": "active", "detail": "HMAC-SHA256"},
                {"control": "replay_protection", "status": "active", "detail": "ReplayReceipt + nonce"},
                {"control": "secret_rotation", "status": "active", "detail": "Operator-managed"},
            ],
            "compliance_requests_allowed": list(COMPLIANCE_REQUEST_TYPES),
            "tier_id": tier_id,
        },
    )


@router.post("/sites/{site_id}/compliance/requests")
async def create_portal_compliance_request(
    request: Request,
    site_id: str,
    payload: PortalComplianceRequestPayload,
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
    access = _authorize_portal_site_access(request, site_id=site_id, member_ref=auth.member_ref)
    if isinstance(access, JSONResponse):
        return access

    request_type = str(payload.request_type or "").strip().lower()
    if request_type not in COMPLIANCE_REQUEST_TYPES:
        return portal_json_error(
            request,
            status_code=400,
            error_code="service.invalid_compliance_request_type",
            message=f"Compliance request type must be one of: {', '.join(COMPLIANCE_REQUEST_TYPES)}",
        )

    locale = str(request.headers.get("x-portal-locale") or "").strip()
    title = _resolve_compliance_request_title(request_type, locale)

    try:
        result = _get_commercial_service(request).create_portal_action_request(
            request_type=request_type,
            member_ref=auth.member_ref,
            account_id=str(access.get("account_id") or ""),
            site_id=site_id,
            title=title,
            message=payload.reason,
            payload_json={
                "request_type": request_type,
                "current_role": str(access.get("role") or ""),
            },
            audit_context=_build_portal_audit_context(request, auth.member_ref),
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return _portal_route_envelope(message="portal compliance request created", data=result)
