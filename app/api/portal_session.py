from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.auth import (
    AUTHORIZATION_HEADER,
    PortalAuthContext,
    PortalBearerTokenError,
    authorize_portal_request,
    build_portal_session_token,
    decode_portal_bearer_claims,
    decode_portal_session_cookie_claims,
    get_cloud_services,
    resolve_portal_session_ttl_seconds,
)
from app.api.envelope import build_envelope
from app.core.models import SITE_STATUS_ARCHIVED
from app.core.security import extract_trace_id
from app.domain.commercial.errors import CommercialServiceError
from app.domain.commercial.service import CommercialService

COOKIE_SITE_ID = "magick_portal_site_id"
COOKIE_MEMBER_REF = "magick_portal_member_ref"
COOKIE_PORTAL_SESSION_TOKEN = "magick_portal_session_token"
COOKIE_BEARER_TOKEN = COOKIE_PORTAL_SESSION_TOKEN
COOKIE_SESSION_ISSUED_AT = "magick_portal_session_issued_at"
COOKIE_SESSION_EXPIRES_AT = "magick_portal_session_expires_at"



def get_commercial_service(request: Request) -> CommercialService:
    services = get_cloud_services(request)
    return CommercialService(services.settings.database_url, settings=services.settings)


def portal_auth_mode(request: Request) -> str:
    settings = get_cloud_services(request).settings
    if settings.portal_jwt_secret:
        return "jwt"
    return "disabled"


def portal_json_error(
    request: Request,
    *,
    status_code: int,
    error_code: str,
    message: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=build_envelope(
            status="error",
            error_code=error_code,
            message=message,
            trace_id=extract_trace_id(request.headers.get("traceparent", "")),
            revision="m6",
        ),
    )


def portal_cookie_secure(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    forwarded_proto = str(request.headers.get("x-forwarded-proto") or "").lower()
    if any(part.strip() == "https" for part in forwarded_proto.split(",")):
        return True
    forwarded_ssl = str(request.headers.get("x-forwarded-ssl") or "").lower().strip()
    return forwarded_ssl in {"on", "1", "true"}


def current_portal_browser_session(
    request: Request,
    *,
    session_required_error_code: str = "portal.session_required",
    session_required_message: str = "portal browser session is required",
) -> dict[str, str]:
    settings = get_cloud_services(request).settings
    now = datetime.now(UTC)
    issued_at = request.cookies.get(COOKIE_SESSION_ISSUED_AT, "").strip()
    expires_at = request.cookies.get(COOKIE_SESSION_EXPIRES_AT, "").strip()
    if expires_at:
        try:
            expires_at_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            expires_at_dt = None
        if expires_at_dt is not None and expires_at_dt <= now:
            raise PortalBearerTokenError(
                401,
                "auth.portal_session_expired",
                "portal session has expired",
            )
    if settings.portal_jwt_secret:
        token = request.cookies.get(COOKIE_PORTAL_SESSION_TOKEN, "").strip()
        if not token:
            raise PortalBearerTokenError(
                401,
                session_required_error_code,
                session_required_message,
            )
        claims = decode_portal_session_cookie_claims(settings, token)
        member_ref = str(claims.get("sub") or claims.get("member_ref") or "").strip()
        if not member_ref:
            raise PortalBearerTokenError(
                401,
                session_required_error_code,
                session_required_message,
            )
        token_expires_at = ""
        if claims.get("exp"):
            token_expires_at = (
                datetime.fromtimestamp(int(claims["exp"]), tz=UTC)
                .isoformat()
                .replace("+00:00", "Z")
            )
        return {
            "member_ref": member_ref,
            "auth_mode": "jwt",
            "issued_at": issued_at,
            "expires_at": token_expires_at or expires_at,
        }

    raise PortalBearerTokenError(
        503,
        "auth.portal_not_configured",
        "portal auth is not configured",
    )


def current_portal_member_session(
    request: Request,
    *,
    session_required_error_code: str = "portal.session_required",
    session_required_message: str = "portal browser session is required",
) -> dict[str, str]:
    return current_portal_browser_session(
        request,
        session_required_error_code=session_required_error_code,
        session_required_message=session_required_message,
    )


def current_portal_site_session(
    request: Request,
    *,
    session_required_error_code: str = "portal.session_required",
    session_required_message: str = "portal session is required",
    site_selection_error_code: str = "portal.site_selection_required",
    site_selection_message: str = "portal site selection is required",
) -> dict[str, str]:
    session = current_portal_browser_session(
        request,
        session_required_error_code=session_required_error_code,
        session_required_message=session_required_message,
    )
    site_id = request.cookies.get(COOKIE_SITE_ID, "").strip()
    if not site_id:
        raise PortalBearerTokenError(
            401,
            site_selection_error_code,
            site_selection_message,
        )
    return {
        **session,
        "site_id": site_id,
    }


def serialize_portal_session(
    request: Request,
    *,
    member_ref: str,
    site_id: str = "",
    strict_site: bool = True,
    session_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    service = get_commercial_service(request)
    sites = service.list_portal_sites(member_ref=member_ref)
    accounts = service.list_portal_accounts(member_ref=member_ref)
    site_items = list(sites.get("items") or [])
    visible_site_items = [
        item
        for item in site_items
        if str(((item.get("site") or {}).get("status") or "")).strip() != SITE_STATUS_ARCHIVED
    ]
    selected_site: dict[str, object] | None = None
    selected_role = ""
    selected_account_id = ""
    current_subscription: dict[str, object] | None = None
    resolved_site_id = site_id
    session = session_metadata or _resolve_portal_session_metadata(request, member_ref=member_ref)
    if site_id:
        try:
            access = service.resolve_portal_site_access(
                site_id=site_id,
                member_ref=member_ref,
            )
        except CommercialServiceError:
            if strict_site:
                raise
            resolved_site_id = ""
        else:
            selected_site = access["site"] if isinstance(access.get("site"), dict) else None
            selected_role = str(access.get("role") or "")
            selected_account_id = str(access.get("account_id") or "")
            if str((selected_site or {}).get("status") or "").strip() == SITE_STATUS_ARCHIVED:
                if strict_site:
                    raise CommercialServiceError(
                        "service.portal_site_archived",
                        "archived portal sites cannot be selected as the current site",
                    )
                selected_site = None
                selected_role = ""
                selected_account_id = ""
                resolved_site_id = ""
    if not resolved_site_id and visible_site_items:
        fallback_item = visible_site_items[0]
        fallback_site = fallback_item.get("site") if isinstance(fallback_item, dict) else {}
        if isinstance(fallback_site, dict):
            selected_site = fallback_site
            resolved_site_id = str(fallback_site.get("site_id") or "")
            selected_account_id = str(fallback_site.get("account_id") or "")
        selected_role = str(fallback_item.get("role") or selected_role or "")
    account_items = list(accounts.get("items") or [])
    if not selected_account_id and account_items:
        selected_account_id = str(account_items[0].get("account_id") or "")
        selected_role = str(account_items[0].get("role") or "")
    if selected_account_id:
        try:
            account_detail = service.get_admin_account(selected_account_id)
        except CommercialServiceError:
            account_detail = {}
        subscriptions = list(account_detail.get("subscriptions") or [])
        current_subscription = subscriptions[0] if subscriptions else None
    return {
        "site_id": resolved_site_id,
        "member_ref": member_ref,
        "account_id": selected_account_id,
        "identity_type": (
            str(account_items[0].get("identity_type") or "")
            if account_items
            else ""
        ),
        "allowed_actions": sorted(
            {
                str(action).strip()
                for item in account_items
                for action in list(item.get("allowed_actions") or [])
                if str(action).strip()
            }
        ),
        "role": selected_role,
        "current_subscription": current_subscription,
        "site": selected_site,
        "sites": site_items,
        "accounts": account_items,
        "auth_mode": portal_auth_mode(request),
        "session": {
            "state": "active",
            "transport": str(session.get("transport") or "cookie"),
            "issued_at": session.get("issued_at", ""),
            "expires_at": session.get("expires_at", ""),
            "revocable": bool(session.get("revocable")),
        },
    }


def build_new_portal_session_metadata(request: Request) -> dict[str, object]:
    settings = get_cloud_services(request).settings
    now = datetime.now(UTC)
    ttl_seconds = resolve_portal_session_ttl_seconds(settings)
    return {
        "member_ref": "",
        "issued_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00", "Z"),
        "transport": "cookie",
        "revocable": True,
    }


def set_portal_session_cookies(
    request: Request,
    response: JSONResponse,
    *,
    member_ref: str,
    site_id: str = "",
) -> None:
    settings = get_cloud_services(request).settings
    now = datetime.now(UTC)
    ttl_seconds = resolve_portal_session_ttl_seconds(settings)
    secure = portal_cookie_secure(request)
    issued_at = now.isoformat().replace("+00:00", "Z")
    expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00", "Z")
    if site_id:
        response.set_cookie(
            COOKIE_SITE_ID,
            site_id,
            httponly=True,
            secure=secure,
            samesite="lax",
            max_age=ttl_seconds,
        )
    else:
        response.delete_cookie(COOKIE_SITE_ID)
    response.set_cookie(
        COOKIE_PORTAL_SESSION_TOKEN,
        build_portal_session_token(
            settings,
            member_ref=member_ref,
            expires_at=now + timedelta(seconds=ttl_seconds),
        ),
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=ttl_seconds,
    )
    response.delete_cookie(COOKIE_MEMBER_REF)
    response.set_cookie(
        COOKIE_SESSION_ISSUED_AT,
        issued_at,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=ttl_seconds,
    )
    response.set_cookie(
        COOKIE_SESSION_EXPIRES_AT,
        expires_at,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=ttl_seconds,
    )


def clear_portal_session_cookies(response: JSONResponse | RedirectResponse) -> None:
    response.delete_cookie(COOKIE_SITE_ID)
    response.delete_cookie(COOKIE_MEMBER_REF)
    response.delete_cookie(COOKIE_PORTAL_SESSION_TOKEN)
    response.delete_cookie(COOKIE_SESSION_ISSUED_AT)
    response.delete_cookie(COOKIE_SESSION_EXPIRES_AT)


def _has_portal_request_headers(request: Request) -> bool:
    return any(
        [
            request.headers.get(AUTHORIZATION_HEADER, "").strip(),
        ]
    )


def _resolve_portal_session_metadata(request: Request, *, member_ref: str) -> dict[str, object]:
    if _has_portal_request_headers(request):
        auth_header = request.headers.get(AUTHORIZATION_HEADER, "").strip()
        if auth_header.lower().startswith("bearer "):
            claims = decode_portal_bearer_claims(
                get_cloud_services(request).settings,
                auth_header[7:].strip(),
            )
            expires_at = ""
            issued_at = ""
            if claims.get("exp"):
                expires_at = (
                    datetime.fromtimestamp(int(claims["exp"]), tz=UTC)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
            if claims.get("iat"):
                issued_at = (
                    datetime.fromtimestamp(int(claims["iat"]), tz=UTC)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
            return {
                "member_ref": member_ref,
                "issued_at": issued_at,
                "expires_at": expires_at,
                "transport": "header",
                "revocable": False,
            }
        return {
            "member_ref": member_ref,
            "issued_at": "",
            "expires_at": "",
            "transport": "header",
            "revocable": False,
        }

    session = current_portal_browser_session(request)
    return {
        "member_ref": member_ref,
        "issued_at": session.get("issued_at", ""),
        "expires_at": session.get("expires_at", ""),
        "transport": "cookie",
        "revocable": True,
    }


async def resolve_portal_request_context(
    request: Request,
    *,
    require_idempotency: bool,
    allow_session_cookies: bool = False,
    session_required_error_code: str = "auth.portal_session_required",
    session_required_message: str = "portal session is required",
) -> PortalAuthContext | JSONResponse:
    if _has_portal_request_headers(request):
        return await authorize_portal_request(
            request,
            require_idempotency=require_idempotency,
        )

    if allow_session_cookies:
        try:
            session = current_portal_browser_session(
                request,
                session_required_error_code=session_required_error_code,
                session_required_message=session_required_message,
            )
        except PortalBearerTokenError as error:
            return portal_json_error(
                request,
                status_code=error.status_code,
                error_code=error.error_code,
                message=error.message,
            )
        return PortalAuthContext(member_ref=session["member_ref"])

    return await authorize_portal_request(
        request,
        require_idempotency=require_idempotency,
    )
