from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse
from jwt import ExpiredSignatureError, InvalidTokenError

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.api.envelope import build_envelope
from app.core.config import Settings
from app.core.db import get_session
from app.core.models import PRINCIPAL_STATUS_ACTIVE
from app.core.security import (
    PUBLIC_RUNTIME_MAX_BODY_BYTES,
    REPLAY_SCOPE_INTERNAL,
    REPLAY_SCOPE_INTERNAL_POST,
    REPLAY_SCOPE_INTERNAL_POST_IP,
    RUNTIME_GUARD_SURFACE_INTERNAL,
    RequestAuthContext,
    RequestAuthError,
    _enforce_guard_cooldown,
    _enforce_short_window_rate_limit,
    _reserve_replay_receipt,
    _resolve_replay_receipt_ttl_seconds,
    _validate_idempotency_key,
    authorize_request,
    extract_trace_id,
    record_runtime_guard_rejection,
    resolve_client_scope_id,
)
from app.core.services import CloudServices

INTERNAL_TOKEN_HEADER = "X-Npcink-Internal-Token"
AUTHORIZATION_HEADER = "Authorization"
PORTAL_LOGIN_CODE_REQUEST_SCOPE_EMAIL = "portal_login_code_email"
PORTAL_LOGIN_CODE_REQUEST_SCOPE_CLIENT = "portal_login_code_client"
PORTAL_LOGIN_CODE_REQUEST_WINDOW_SECONDS = 15 * 60
PORTAL_LOGIN_CODE_MAX_REQUESTS_PER_EMAIL_WINDOW = 5
PORTAL_LOGIN_CODE_MAX_REQUESTS_PER_CLIENT_WINDOW = 10


@dataclass(slots=True)
class PortalAuthContext:
    principal_id: str
    site_id: str = ""


class PortalBearerTokenError(ValueError):
    def __init__(self, status_code: int, error_code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message


def _normalize_local_debug_origin(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if not parsed.scheme or not parsed.netloc:
        return ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    host = (parsed.hostname or "").strip().lower()
    return f"{parsed.scheme.lower()}://{host}{port}"


def _debug_local_origin_allowed(settings: Settings, value: str) -> bool:
    normalized = _normalize_local_debug_origin(value)
    if not normalized:
        return False
    allowlist = {
        _normalize_local_debug_origin(item)
        for item in str(settings.debug_local_origin_allowlist or "").split(",")
    }
    return normalized in {item for item in allowlist if item}


def _portal_local_debug_login_code_request(request: Request) -> bool:
    settings = get_cloud_services(request).settings
    environment = str(settings.environment or "").strip().lower()
    if environment not in {"development", "test"}:
        return False
    if str(request.headers.get("x-npcink-debug-portal-link") or "").strip() != "1":
        return False
    candidates = (
        str(request.headers.get("origin") or ""),
        str(request.headers.get("referer") or ""),
        str(request.base_url),
    )
    return any(_debug_local_origin_allowed(settings, value) for value in candidates)


def get_cloud_services(request: Request) -> CloudServices:
    services = getattr(request.app.state, "services", None)
    if services is None:
        raise RuntimeError("Cloud services are not configured.")
    return services if isinstance(services, CloudServices) else services


def _build_auth_error_response(
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
            revision="m5",
        ),
    )


def build_portal_session_token(
    settings: Settings,
    *,
    principal_id: str,
    site_id: str = "",
    session_version: int = 1,
    expires_at: datetime | None = None,
) -> str:
    now = datetime.now(UTC)
    resolved_expires_at = expires_at or (
        now + timedelta(seconds=resolve_portal_session_ttl_seconds(settings))
    )
    payload: dict[str, Any] = {
        "sub": principal_id,
        "purpose": "portal_session",
        "session_version": int(session_version or 1),
        "iat": int(now.timestamp()),
        "exp": int(resolved_expires_at.timestamp()),
    }
    if settings.portal_jwt_issuer:
        payload["iss"] = settings.portal_jwt_issuer
    if settings.portal_jwt_audience:
        payload["aud"] = settings.portal_jwt_audience
    if site_id:
        payload["site_id"] = site_id
    return jwt.encode(
        payload,
        _resolve_portal_link_signing_secret(settings),
        algorithm=settings.portal_jwt_algorithm,
    )


def _resolve_portal_link_signing_secret(settings: Settings) -> str:
    secret = settings.portal_jwt_secret
    if not secret:
        raise RuntimeError("Portal auth is not configured.")
    return secret


def resolve_portal_session_ttl_seconds(settings: Settings) -> int:
    return max(60, int(settings.portal_session_ttl_seconds or 0))


def resolve_portal_remember_me_session_ttl_seconds(settings: Settings) -> int:
    return max(
        resolve_portal_session_ttl_seconds(settings),
        int(settings.portal_remember_me_session_ttl_seconds or 0),
        60,
    )


def resolve_portal_login_code_ttl_seconds(settings: Settings) -> int:
    return max(60, int(settings.portal_login_code_ttl_seconds or 0))


def _jwt_payload_dict(payload: object) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def decode_portal_bearer_claims(settings: Settings, token: str) -> dict[str, Any]:
    if not settings.portal_jwt_secret:
        raise PortalBearerTokenError(
            503,
            "auth.portal_not_configured",
            "portal auth is not configured",
        )
    decode_kwargs: dict[str, Any] = {
        "jwt": token,
        "key": settings.portal_jwt_secret,
        "algorithms": [settings.portal_jwt_algorithm],
    }
    if settings.portal_jwt_issuer:
        decode_kwargs["issuer"] = settings.portal_jwt_issuer
    if settings.portal_jwt_audience:
        decode_kwargs["audience"] = settings.portal_jwt_audience

    try:
        payload = jwt.decode(**decode_kwargs)
    except ExpiredSignatureError as error:
        raise PortalBearerTokenError(
            401,
            "auth.portal_token_expired",
            "portal token has expired",
        ) from error
    except InvalidTokenError as error:
        raise PortalBearerTokenError(
            403,
            "auth.portal_token_invalid",
            "invalid portal bearer token",
        ) from error

    return _jwt_payload_dict(payload)


def decode_portal_session_cookie_claims(settings: Settings, token: str) -> dict[str, Any]:
    decode_kwargs: dict[str, Any] = {
        "jwt": token,
        "key": _resolve_portal_link_signing_secret(settings),
        "algorithms": [settings.portal_jwt_algorithm],
    }
    if settings.portal_jwt_issuer:
        decode_kwargs["issuer"] = settings.portal_jwt_issuer
    if settings.portal_jwt_audience:
        decode_kwargs["audience"] = settings.portal_jwt_audience

    try:
        payload = jwt.decode(**decode_kwargs)
    except ExpiredSignatureError as error:
        raise PortalBearerTokenError(
            401,
            "auth.portal_session_expired",
            "portal session has expired",
        ) from error
    except InvalidTokenError as error:
        raise PortalBearerTokenError(
            403,
            "auth.portal_session_invalid",
            "invalid portal session token",
        ) from error

    payload = _jwt_payload_dict(payload)
    purpose = str(payload.get("purpose") or "").strip()
    if purpose != "portal_session":
        raise PortalBearerTokenError(
            403,
            "auth.portal_session_invalid",
            "invalid portal session token",
        )
    return payload


def decode_portal_bearer_token(settings: Settings, token: str) -> str:
    payload = decode_portal_bearer_claims(settings, token)

    return _extract_portal_principal_id(payload)


def _extract_portal_principal_id(payload: dict[str, Any]) -> str:
    principal_id = str(payload.get("sub") or "").strip()
    if not principal_id:
        raise PortalBearerTokenError(
            401,
            "auth.principal_id_required",
            "missing portal principal id",
        )
    return principal_id


def _extract_portal_session_version(payload: dict[str, Any]) -> int:
    try:
        return int(payload.get("session_version") or 1)
    except (TypeError, ValueError) as error:
        raise PortalBearerTokenError(
            403,
            "auth.portal_session_invalid",
            "invalid portal session token",
        ) from error


def validate_portal_principal_session(
    settings: Settings,
    *,
    principal_id: str,
    session_version: int,
) -> None:
    with get_session(settings.database_url) as session:
        repository = CommercialRepository(session)
        identity = repository.get_principal_identity_by_ref(principal_id=principal_id)
        if (
            identity is None
            or identity.status != PRINCIPAL_STATUS_ACTIVE
            or int(identity.session_version or 1) != int(session_version or 1)
        ):
            raise PortalBearerTokenError(
                401,
                "auth.portal_session_revoked",
                "portal session is no longer valid",
            )


def enforce_portal_login_code_request_rate_limit(
    request: Request,
    *,
    email: str,
) -> None:
    if _portal_local_debug_login_code_request(request):
        return
    services = get_cloud_services(request)
    normalized_email = email.strip().lower()
    if not normalized_email:
        return

    now = datetime.now(UTC)
    trace_id = extract_trace_id(request.headers.get("traceparent", ""))
    client_scope_id = resolve_client_scope_id(request)
    request_marker = f"req_{uuid4().hex}"
    try:
        with get_session(services.settings.database_url) as session:
            _enforce_short_window_rate_limit(
                session=session,
                scope_kind=PORTAL_LOGIN_CODE_REQUEST_SCOPE_EMAIL,
                scope_id=normalized_email,
                now=now,
                window_seconds=PORTAL_LOGIN_CODE_REQUEST_WINDOW_SECONDS,
                max_requests=PORTAL_LOGIN_CODE_MAX_REQUESTS_PER_EMAIL_WINDOW,
            )
            _enforce_short_window_rate_limit(
                session=session,
                scope_kind=PORTAL_LOGIN_CODE_REQUEST_SCOPE_CLIENT,
                scope_id=client_scope_id,
                now=now,
                window_seconds=PORTAL_LOGIN_CODE_REQUEST_WINDOW_SECONDS,
                max_requests=PORTAL_LOGIN_CODE_MAX_REQUESTS_PER_CLIENT_WINDOW,
            )
            _reserve_replay_receipt(
                session=session,
                scope_kind=PORTAL_LOGIN_CODE_REQUEST_SCOPE_EMAIL,
                scope_id=normalized_email,
                replay_key=request_marker,
                method=request.method,
                path=request.url.path,
                trace_id=trace_id,
                now=now,
                ttl_seconds=PORTAL_LOGIN_CODE_REQUEST_WINDOW_SECONDS,
            )
            if client_scope_id:
                _reserve_replay_receipt(
                    session=session,
                    scope_kind=PORTAL_LOGIN_CODE_REQUEST_SCOPE_CLIENT,
                    scope_id=client_scope_id,
                    replay_key=request_marker,
                    method=request.method,
                    path=request.url.path,
                    trace_id=trace_id,
                    now=now,
                    ttl_seconds=PORTAL_LOGIN_CODE_REQUEST_WINDOW_SECONDS,
                )
            session.commit()
    except RequestAuthError as error:
        raise PortalBearerTokenError(
            429,
            "portal.login_code_rate_limited",
            error.message,
        ) from error


async def authorize_public_request(
    request: Request,
    *,
    require_idempotency: bool,
    required_scope: str | None = None,
    max_body_bytes: int | None = None,
) -> RequestAuthContext | JSONResponse:
    services = get_cloud_services(request)

    try:
        return await authorize_request(
            request,
            settings=services.settings,
            database_url=services.settings.database_url,
            timestamp_tolerance_seconds=services.settings.auth_timestamp_tolerance_seconds,
            public_post_rate_limit_window_seconds=(
                services.settings.public_post_rate_limit_window_seconds
            ),
            public_post_max_requests_per_window=(
                services.settings.public_post_max_requests_per_window
            ),
            public_post_max_requests_per_key_window=(
                services.settings.public_post_max_requests_per_key_window
            ),
            public_post_max_requests_per_ip_window=(
                services.settings.public_post_max_requests_per_ip_window
            ),
            public_guard_cooldown_window_seconds=(
                services.settings.public_guard_cooldown_window_seconds
            ),
            public_guard_max_reject_events_per_site_window=(
                services.settings.public_guard_max_reject_events_per_site_window
            ),
            public_guard_max_reject_events_per_key_window=(
                services.settings.public_guard_max_reject_events_per_key_window
            ),
            public_guard_max_reject_events_per_ip_window=(
                services.settings.public_guard_max_reject_events_per_ip_window
            ),
            require_idempotency=require_idempotency,
            required_scope=required_scope,
            max_body_bytes=max_body_bytes or PUBLIC_RUNTIME_MAX_BODY_BYTES,
        )
    except RequestAuthError as error:
        return _build_auth_error_response(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )


async def authorize_internal_request(
    request: Request,
    *,
    require_idempotency: bool,
) -> JSONResponse | None:
    return await _authorize_static_token_request(
        request,
        require_idempotency=require_idempotency,
        expected_token=get_cloud_services(request).settings.internal_auth_token,
        token_header=INTERNAL_TOKEN_HEADER,
        not_configured_error_code="auth.internal_not_configured",
        not_configured_message="internal auth is not configured",
        token_required_error_code="auth.internal_token_required",
        token_required_message="missing internal auth token",
        token_invalid_error_code="auth.internal_token_invalid",
        token_invalid_message="invalid internal auth token",
    )


async def _authorize_static_token_request(
    request: Request,
    *,
    require_idempotency: bool,
    expected_token: str | None,
    token_header: str,
    not_configured_error_code: str,
    not_configured_message: str,
    token_required_error_code: str,
    token_required_message: str,
    token_invalid_error_code: str,
    token_invalid_message: str,
) -> JSONResponse | None:
    services = get_cloud_services(request)
    provided_token = request.headers.get(token_header, "")
    trace_id = extract_trace_id(request.headers.get("traceparent", ""))
    client_scope_id = resolve_client_scope_id(request)

    def _token_error_response(error: RequestAuthError) -> JSONResponse:
        record_runtime_guard_rejection(
            database_url=services.settings.database_url,
            request=request,
            auth_surface=RUNTIME_GUARD_SURFACE_INTERNAL,
            error=error,
            trace_id=trace_id,
        )
        return _build_auth_error_response(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )

    if not expected_token:
        return _build_auth_error_response(
            request,
            status_code=503,
            error_code=not_configured_error_code,
            message=not_configured_message,
        )

    if not provided_token:
        return _token_error_response(
            RequestAuthError(
                401,
                token_required_error_code,
                token_required_message,
            )
        )

    if not hmac.compare_digest(provided_token, expected_token):
        return _token_error_response(
            RequestAuthError(
                403,
                token_invalid_error_code,
                token_invalid_message,
            )
        )

    idempotency_key = request.headers.get("Idempotency-Key", "").strip()

    try:
        _validate_idempotency_key(idempotency_key, required=require_idempotency)
    except RequestAuthError as error:
        return _token_error_response(error)

    if request.method.upper() == "POST" and idempotency_key:
        now = datetime.now(UTC)
        replay_ttl_seconds = _resolve_replay_receipt_ttl_seconds(
            services.settings.auth_timestamp_tolerance_seconds
        )
        try:
            with get_session(services.settings.database_url) as session:
                cooldown_scopes = [
                    (
                        REPLAY_SCOPE_INTERNAL_POST,
                        REPLAY_SCOPE_INTERNAL,
                        services.settings.internal_guard_max_reject_events_per_token_window,
                    ),
                    (
                        REPLAY_SCOPE_INTERNAL_POST_IP,
                        client_scope_id,
                        services.settings.internal_guard_max_reject_events_per_ip_window,
                    ),
                ]
                replay_scopes = [
                    (
                        REPLAY_SCOPE_INTERNAL_POST,
                        REPLAY_SCOPE_INTERNAL,
                        services.settings.internal_post_max_requests_per_window,
                    ),
                    (
                        REPLAY_SCOPE_INTERNAL_POST_IP,
                        client_scope_id,
                        services.settings.internal_post_max_requests_per_ip_window,
                    ),
                ]
                for scope_kind, scope_id, max_events in cooldown_scopes:
                    _enforce_guard_cooldown(
                        session=session,
                        scope_kind=scope_kind,
                        scope_id=scope_id,
                        now=now,
                        window_seconds=services.settings.internal_guard_cooldown_window_seconds,
                        max_events=max_events,
                    )
                for scope_kind, scope_id, max_requests in replay_scopes:
                    _enforce_short_window_rate_limit(
                        session=session,
                        scope_kind=scope_kind,
                        scope_id=scope_id,
                        now=now,
                        window_seconds=services.settings.internal_post_rate_limit_window_seconds,
                        max_requests=max_requests,
                    )
                for scope_kind, scope_id, _ in replay_scopes:
                    if not scope_id:
                        continue
                    _reserve_replay_receipt(
                        session=session,
                        scope_kind=scope_kind,
                        scope_id=scope_id,
                        replay_key=idempotency_key,
                        method=request.method,
                        path=request.url.path,
                        trace_id=extract_trace_id(request.headers.get("traceparent", "")),
                        now=now,
                        ttl_seconds=replay_ttl_seconds,
                    )
                session.commit()
        except RequestAuthError as error:
            return _token_error_response(error)

    return None


async def authorize_portal_request(
    request: Request,
    *,
    require_idempotency: bool,
) -> PortalAuthContext | JSONResponse:
    _ = require_idempotency
    return _authorize_portal_bearer_jwt_request(request)


def _authorize_portal_bearer_jwt_request(
    request: Request,
) -> PortalAuthContext | JSONResponse:
    services = get_cloud_services(request)
    auth_header = request.headers.get(AUTHORIZATION_HEADER, "").strip()
    if not auth_header.lower().startswith("bearer "):
        return _build_auth_error_response(
            request,
            status_code=401,
            error_code="auth.portal_bearer_required",
            message="missing bearer token",
        )
    token = auth_header[7:].strip()
    if not token:
        return _build_auth_error_response(
            request,
            status_code=401,
            error_code="auth.portal_bearer_required",
            message="missing bearer token",
        )

    try:
        claims = decode_portal_bearer_claims(services.settings, token)
        principal_id = _extract_portal_principal_id(claims)
        validate_portal_principal_session(
            services.settings,
            principal_id=principal_id,
            session_version=_extract_portal_session_version(claims),
        )
    except PortalBearerTokenError as error:
        return _build_auth_error_response(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    return PortalAuthContext(principal_id=principal_id)
