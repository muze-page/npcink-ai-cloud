from __future__ import annotations

import json
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

COOKIE_ADMIN_TOKEN = "npcink_admin_session_token"
ADMIN_SESSION_ALGORITHM = "HS256"
ADMIN_SESSION_ISSUER = "npcink-ai-cloud"
ADMIN_SESSION_AUDIENCE = "npcink-ai-cloud-admin"
ADMIN_SESSION_PURPOSE = "admin_session"
ADMIN_SESSION_AUTH_MODE = "admin_key"
ADMIN_SESSION_REQUIRED_CLAIMS = (
    "iss",
    "aud",
    "sub",
    "purpose",
    "auth_mode",
    "grant_id",
    "is_persisted",
    "session_version",
    "iat",
    "exp",
)

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
    grant_id: str,
    principal_id: str,
    is_persisted: bool,
    session_version: int = 1,
) -> str:
    if (
        not isinstance(grant_id, str)
        or grant_id != grant_id.strip()
        or not isinstance(principal_id, str)
        or not principal_id
        or principal_id != principal_id.strip()
        or not isinstance(is_persisted, bool)
        or (is_persisted and not grant_id)
        or (not is_persisted and bool(grant_id))
        or isinstance(session_version, bool)
        or not isinstance(session_version, int)
        or session_version < 1
    ):
        raise PortalBearerTokenError(
            401,
            "auth.admin_session_invalid",
            "admin session is invalid",
        )
    settings = get_cloud_services(request).settings
    now = datetime.now(UTC)
    expires_at = now.timestamp() + max(60, int(settings.admin_session_ttl_seconds or 0))
    payload = {
        "iss": ADMIN_SESSION_ISSUER,
        "aud": ADMIN_SESSION_AUDIENCE,
        "sub": principal_id,
        "purpose": ADMIN_SESSION_PURPOSE,
        "auth_mode": ADMIN_SESSION_AUTH_MODE,
        "grant_id": grant_id,
        "is_persisted": is_persisted,
        "session_version": session_version,
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


def _validate_admin_session_claims(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise InvalidTokenError("admin session claims must be an object")
    claims: dict[str, Any] = payload
    principal_id = claims.get("sub")
    grant_id = claims.get("grant_id")
    is_persisted = claims.get("is_persisted")
    session_version = claims.get("session_version")
    issued_at = claims.get("iat")
    expires_at = claims.get("exp")
    not_before = claims.get("nbf")
    if (
        claims.get("iss") != ADMIN_SESSION_ISSUER
        or claims.get("aud") != ADMIN_SESSION_AUDIENCE
        or claims.get("purpose") != ADMIN_SESSION_PURPOSE
        or claims.get("auth_mode") != ADMIN_SESSION_AUTH_MODE
        or "role" in claims
        or not isinstance(grant_id, str)
        or grant_id != grant_id.strip()
        or not isinstance(principal_id, str)
        or not principal_id.strip()
        or principal_id != principal_id.strip()
        or not isinstance(is_persisted, bool)
        or (is_persisted and not grant_id)
        or (not is_persisted and bool(grant_id))
        or isinstance(session_version, bool)
        or not isinstance(session_version, int)
        or session_version < 1
        or isinstance(issued_at, bool)
        or not isinstance(issued_at, int)
        or issued_at < 0
        or isinstance(expires_at, bool)
        or not isinstance(expires_at, int)
        or expires_at <= issued_at
        or (
            "nbf" in claims
            and (isinstance(not_before, bool) or not isinstance(not_before, int) or not_before < 0)
        )
    ):
        raise InvalidTokenError("admin session claims are invalid")
    try:
        datetime.fromtimestamp(issued_at, tz=UTC)
        datetime.fromtimestamp(expires_at, tz=UTC)
        if not_before is not None:
            datetime.fromtimestamp(not_before, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise InvalidTokenError("admin session timestamps are invalid") from error
    now_timestamp = datetime.now(UTC).timestamp()
    if (
        issued_at > now_timestamp
        or expires_at <= now_timestamp
        or (not_before is not None and (not_before > now_timestamp or not_before > expires_at))
    ):
        raise InvalidTokenError("admin session timestamps are invalid")
    return claims


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
                issuer=ADMIN_SESSION_ISSUER,
                audience=ADMIN_SESSION_AUDIENCE,
                options={
                    "require": list(ADMIN_SESSION_REQUIRED_CLAIMS),
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
            claims = _validate_admin_session_claims(payload)
            break
        except (InvalidTokenError, TypeError, ValueError, OverflowError) as error:
            decode_error = InvalidTokenError("admin session claims are invalid")
            decode_error.__cause__ = error
            continue

    if claims is None:
        raise PortalBearerTokenError(
            401,
            "auth.admin_session_invalid",
            "admin session is invalid",
        ) from decode_error

    principal_id = claims["sub"]
    auth_mode = claims["auth_mode"]
    settings = get_cloud_services(request).settings
    admin_principal_id = str(settings.admin_principal_id or "platform:internal_root").strip()
    token_is_persisted = claims["is_persisted"]
    allow_bootstrap = not token_is_persisted and principal_id == admin_principal_id

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
    is_persisted = identity.get("is_persisted")
    token_grant_id = claims["grant_id"]
    current_grant_id = identity.get("grant_id")
    token_session_version = claims["session_version"]
    current_session_version = identity.get("session_version")
    if (
        not isinstance(is_persisted, bool)
        or is_persisted != token_is_persisted
        or not isinstance(current_grant_id, str)
        or current_grant_id != token_grant_id
        or isinstance(current_session_version, bool)
        or not isinstance(current_session_version, int)
        or current_session_version < 1
        or token_session_version != current_session_version
    ):
        raise PortalBearerTokenError(
            401,
            "auth.admin_session_revoked",
            "admin session is no longer valid",
        )
    revocable = is_persisted

    issued_at = datetime.fromtimestamp(claims["iat"], tz=UTC).isoformat().replace("+00:00", "Z")
    expires_at = datetime.fromtimestamp(claims["exp"], tz=UTC).isoformat().replace("+00:00", "Z")
    identity_role = str(identity.get("role") or "").strip()
    return {
        "principal_id": str(identity.get("principal_id") or principal_id),
        "identity_type": IDENTITY_TYPE_PLATFORM_ADMIN,
        "role": identity_role,
        "capabilities": _dict_value(identity.get("capabilities"))
        or _platform_capability_flags(identity_role),
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
    response = JSONResponse(
        status_code=status_code,
        content=build_envelope(
            status="error",
            error_code=error_code,
            message=message,
            revision="m6",
        ),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


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
            grant_id=session.grant_id,
            principal_id=session.principal_id,
            is_persisted=session.revocable,
            session_version=session.session_version,
        ),
    )


async def _request_payload(request: Request) -> dict[str, Any]:
    content_type = str(request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PortalBearerTokenError(
                422,
                "auth.admin_login_request_invalid",
                "admin login request is invalid",
            ) from error
        if not isinstance(payload, dict):
            raise PortalBearerTokenError(
                422,
                "auth.admin_login_request_invalid",
                "admin login request is invalid",
            )
        return payload
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


@router.post("/admin/auth/login")
async def web_admin_auth_login(request: Request) -> Any:
    try:
        payload = await _request_payload(request)
    except PortalBearerTokenError as error:
        return _admin_session_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
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
    unsupported_fields = sorted(set(payload) - {"admin_key", "redirect"})
    if unsupported_fields:
        redirect_to = payload.get("redirect") or request.query_params.get("redirect")
        if wants_redirect:
            return RedirectResponse(
                url=_build_admin_login_url(
                    request,
                    error_code="auth.admin_login_request_invalid",
                    redirect_to=redirect_to,
                ),
                status_code=303,
            )
        return _admin_session_json_error(
            request,
            status_code=422,
            error_code="auth.admin_login_request_invalid",
            message="admin login request is invalid",
        )
    admin_key = str(payload.get("admin_key") or "").strip()
    redirect_to = payload.get("redirect") or request.query_params.get("redirect")
    if not admin_key:
        if wants_redirect:
            return RedirectResponse(
                url=_build_admin_login_url(
                    request,
                    error_code="auth.admin_key_required",
                    redirect_to=redirect_to,
                ),
                status_code=303,
            )
        return _admin_session_json_error(
            request,
            status_code=400,
            error_code="auth.admin_key_required",
            message="admin key is required",
        )
    try:
        identity = resolve_admin_login_identity(
            request,
            admin_key=admin_key,
        )
        session = ResolvedAdminSession.from_identity(
            identity,
            auth_mode="admin_key",
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
        response: Response
        if wants_redirect:
            response = _build_console_redirect_response(
                request,
                fallback="/admin",
                redirect_to=redirect_to,
            )
        else:
            response = JSONResponse(
                status_code=200,
                content=build_envelope(
                    status="ok",
                    message="admin session created",
                    data=session.as_payload(),
                    revision="m8",
                ),
            )
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
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
