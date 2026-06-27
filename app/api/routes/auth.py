from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import jwt
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from jwt import InvalidTokenError

from app.api.admin_ops import (
    ResolvedAdminSession,
    resolve_admin_login_identity,
)
from app.api.auth import (
    PortalBearerTokenError,
    get_cloud_services,
)
from app.api.browser_security import enforce_browser_same_origin
from app.api.envelope import build_envelope
from app.api.portal_session import (
    clear_portal_session_cookies as _clear_browser_session_cookies,
)
from app.api.portal_session import (
    portal_cookie_secure,
)
from app.core.models import PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN
from app.domain.commercial.errors import CommercialServiceError
from app.domain.commercial.identity import (
    IDENTITY_TYPE_PLATFORM_ADMIN,
    _platform_capability_flags,
)

COOKIE_ADMIN_TOKEN = "magick_admin_session_token"
ADMIN_SESSION_ALGORITHM = "HS256"

router = APIRouter(include_in_schema=False)


def _dict_value(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _resolve_admin_session_secret(request: Request) -> str:
    settings = get_cloud_services(request).settings
    secret = str(settings.admin_session_secret or "").strip()
    if not secret:
        environment = str(settings.environment or "").strip().lower()
        if environment == "test":
            secret = str(settings.internal_auth_token or "").strip()
        elif environment == "development" and settings.allow_dev_admin_internal_token_fallback:
            secret = str(settings.internal_auth_token or "").strip()
    if not secret:
        raise PortalBearerTokenError(
            503,
            "auth.admin_not_configured",
            "admin session secret is not configured",
        )
    return secret


def _build_admin_session_token(
    request: Request,
    *,
    principal_id: str,
    role: str,
    auth_mode: str,
    session_version: int = 1,
) -> str:
    settings = get_cloud_services(request).settings
    now = datetime.now(UTC)
    expires_at = now.timestamp() + max(60, int(settings.admin_session_ttl_seconds or 0))
    payload = {
        "sub": principal_id,
        "role": role,
        "auth_mode": auth_mode,
        "session_version": int(session_version or 1),
        "iat": int(now.timestamp()),
        "exp": int(expires_at),
    }
    return jwt.encode(
        payload,
        _resolve_admin_session_secret(request),
        algorithm=ADMIN_SESSION_ALGORITHM,
    )


def _resolve_admin_session_cookie_candidates(request: Request) -> list[str]:
    candidates: list[str] = []
    parsed_cookie = str(request.cookies.get(COOKIE_ADMIN_TOKEN, "") or "").strip()
    if parsed_cookie:
        candidates.append(parsed_cookie)

    raw_cookie_header = str(request.headers.get("cookie") or "").strip()
    if not raw_cookie_header:
        return candidates

    for chunk in raw_cookie_header.split(";"):
        name, separator, value = chunk.partition("=")
        if separator != "=":
            continue
        if name.strip() != COOKIE_ADMIN_TOKEN:
            continue
        token = value.strip()
        if token and token not in candidates:
            candidates.append(token)
    return candidates


def _current_admin_session(request: Request) -> dict[str, Any]:
    tokens = _resolve_admin_session_cookie_candidates(request)
    if not tokens:
        raise PortalBearerTokenError(
            401,
            "auth.admin_session_required",
            "admin session is required",
        )

    claims: dict[str, Any] | None = None
    decode_error: InvalidTokenError | None = None
    for token in tokens:
        try:
            payload = jwt.decode(
                token,
                _resolve_admin_session_secret(request),
                algorithms=[ADMIN_SESSION_ALGORITHM],
            )
            claims = payload if isinstance(payload, dict) else {}
            break
        except InvalidTokenError as error:
            decode_error = error
            continue

    if claims is None:
        raise PortalBearerTokenError(
            401,
            "auth.admin_session_invalid",
            "admin session is invalid",
        ) from decode_error

    principal_id = str(claims.get("sub") or "").strip()
    auth_mode = str(claims.get("auth_mode") or "admin_bootstrap_token").strip()
    settings = get_cloud_services(request).settings
    bootstrap_principal_id = str(
        settings.admin_bootstrap_principal_id or "platform:internal_root"
    ).strip()
    allow_bootstrap = auth_mode in {"admin_bootstrap_token", "dev_internal_autologin"} and (
        principal_id in {bootstrap_principal_id, "platform:internal_root"}
    )

    from app.api.routes.service import _get_commercial_service

    try:
        identity = _get_commercial_service(request).resolve_platform_admin_grant(
            principal_id=principal_id,
            bootstrap_role=PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
            allow_bootstrap=allow_bootstrap,
        )
    except CommercialServiceError as error:
        raise PortalBearerTokenError(
            401,
            "auth.admin_session_revoked",
            "admin session is no longer valid",
        ) from error
    token_session_version = int(claims.get("session_version") or 1)
    current_session_version = int(identity.get("session_version") or 1)
    if token_session_version != current_session_version:
        raise PortalBearerTokenError(
            401,
            "auth.admin_session_revoked",
            "admin session is no longer valid",
        )
    identity_metadata = identity.get("metadata")
    revocable = (
        not bool(identity_metadata.get("bootstrap"))
        if isinstance(identity_metadata, dict)
        else True
    )

    issued_at = ""
    expires_at = ""
    if claims.get("iat"):
        issued_at = (
            datetime.fromtimestamp(int(claims["iat"]), tz=UTC).isoformat().replace("+00:00", "Z")
        )
    if claims.get("exp"):
        expires_at = (
            datetime.fromtimestamp(int(claims["exp"]), tz=UTC).isoformat().replace("+00:00", "Z")
        )
    return {
        "principal_id": str(identity.get("principal_id") or principal_id),
        "identity_type": IDENTITY_TYPE_PLATFORM_ADMIN,
        "role": str(identity.get("role") or claims.get("role") or "").strip(),
        "capabilities": _dict_value(identity.get("capabilities"))
        or _platform_capability_flags(
            str(identity.get("role") or claims.get("role") or "").strip()
        ),
        "auth_mode": auth_mode,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "transport": "cookie",
        "revocable": revocable,
        "session_version": current_session_version,
    }


def _set_admin_session_cookie(response: Response, request: Request, token: str) -> None:
    secure = portal_cookie_secure(request)
    ttl_seconds = max(60, int(get_cloud_services(request).settings.admin_session_ttl_seconds or 0))
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    response.delete_cookie(COOKIE_ADMIN_TOKEN, path="/admin")
    response.set_cookie(
        COOKIE_ADMIN_TOKEN,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=ttl_seconds,
        expires=expires_at,
    )


def _clear_admin_session_cookie(response: RedirectResponse) -> None:
    response.delete_cookie(COOKIE_ADMIN_TOKEN, path="/")
    response.delete_cookie(COOKIE_ADMIN_TOKEN, path="/admin")


def _admin_session_json_error(
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
            revision="m6",
        ),
    )


def _require_admin_session_json(request: Request) -> dict[str, Any] | JSONResponse:
    try:
        return _current_admin_session(request)
    except PortalBearerTokenError as error:
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )


def _sanitize_console_return_to(value: object, *, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        return fallback
    if not parsed.path.startswith("/admin"):
        return fallback
    return urlunsplit(("", "", parsed.path, parsed.query, ""))


def _build_console_redirect_response(
    request: Request,
    *,
    fallback: str,
    redirect_to: object = None,
) -> RedirectResponse:
    target = _sanitize_console_return_to(redirect_to, fallback=fallback)
    return RedirectResponse(url=target, status_code=303)


def _issue_admin_session_cookie(
    request: Request,
    response: Response,
    *,
    session: ResolvedAdminSession,
) -> None:
    _set_admin_session_cookie(
        response,
        request,
        _build_admin_session_token(
            request,
            principal_id=session.principal_id,
            role=session.role,
            auth_mode=session.auth_mode,
            session_version=session.session_version,
        ),
    )


async def _request_payload(request: Request) -> dict[str, Any]:
    content_type = str(request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        payload = await request.json()
        return payload if isinstance(payload, dict) else {}
    if "application/x-www-form-urlencoded" in content_type:
        body = (await request.body()).decode("utf-8", errors="ignore")
        return {key: value for key, value in parse_qsl(body, keep_blank_values=True)}
    if "multipart/form-data" in content_type:
        form = await request.form()
        return {str(key): value for key, value in form.items()}
    return {}


def _request_wants_html_redirect(request: Request) -> bool:
    content_type = str(request.headers.get("content-type") or "").lower()
    return (
        "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type
    )


def _build_admin_login_url(
    request: Request,
    *,
    error_code: str | None = None,
    redirect_to: str | None = None,
) -> str:
    params: dict[str, str] = {}
    if error_code:
        params["error"] = error_code
    target = _sanitize_console_return_to(redirect_to, fallback="/admin")
    if target:
        params["redirect"] = target
    query = urlencode(params) if params else ""
    return f"/admin/login?{query}" if query else "/admin/login"


@router.post("/admin/auth/bootstrap")
async def web_admin_auth_bootstrap(request: Request) -> Any:
    payload = await _request_payload(request)
    wants_redirect = _request_wants_html_redirect(request)
    try:
        enforce_browser_same_origin(request)
    except PortalBearerTokenError as error:
        redirect_to = payload.get("redirect") or request.query_params.get("redirect")
        if wants_redirect:
            return RedirectResponse(
                url=_build_admin_login_url(
                    request,
                    error_code=error.error_code,
                    redirect_to=redirect_to,
                ),
                status_code=303,
            )
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    token = str(payload.get("token") or "").strip()
    principal_id = str(payload.get("principal_id") or "").strip()
    redirect_to = payload.get("redirect") or request.query_params.get("redirect")
    if not token:
        if wants_redirect:
            return RedirectResponse(
                url=_build_admin_login_url(
                    request,
                    error_code="auth.admin_bootstrap_token_required",
                    redirect_to=redirect_to,
                ),
                status_code=303,
            )
        return _admin_session_json_error(
            request,
            status_code=400,
            error_code="auth.admin_bootstrap_token_required",
            message="missing admin bootstrap token",
        )
    try:
        identity = resolve_admin_login_identity(
            request,
            token=token,
            principal_id=principal_id,
        )
        session = ResolvedAdminSession.from_identity(
            identity,
            auth_mode="admin_bootstrap_token",
            fallback_principal_id=principal_id
            or str(
                get_cloud_services(request).settings.admin_bootstrap_principal_id
                or "platform:internal_root"
            ),
        )
    except PortalBearerTokenError as error:
        if wants_redirect:
            return RedirectResponse(
                url=_build_admin_login_url(
                    request,
                    error_code=error.error_code,
                    redirect_to=redirect_to,
                ),
                status_code=303,
            )
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    except CommercialServiceError as error:
        if wants_redirect:
            return RedirectResponse(
                url=_build_admin_login_url(
                    request,
                    error_code=error.error_code,
                    redirect_to=redirect_to,
                ),
                status_code=303,
            )
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    try:
        response = _build_console_redirect_response(
            request,
            fallback="/admin",
            redirect_to=redirect_to,
        )
        _issue_admin_session_cookie(request, response, session=session)
        return response
    except PortalBearerTokenError as error:
        if wants_redirect:
            return RedirectResponse(
                url=_build_admin_login_url(
                    request,
                    error_code=error.error_code,
                    redirect_to=redirect_to,
                ),
                status_code=303,
            )
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )


@router.get("/admin/session")
async def web_admin_session(request: Request) -> Any:
    session = _require_admin_session_json(request)
    if isinstance(session, JSONResponse):
        return session
    return build_envelope(
        status="ok",
        message="admin session loaded",
        data=session,
        revision="m6",
    )


@router.get("/admin/logout")
async def web_admin_logout() -> RedirectResponse:
    response = RedirectResponse(url="/admin/login", status_code=303)
    _clear_admin_session_cookie(response)
    _clear_browser_session_cookies(response)
    return response
