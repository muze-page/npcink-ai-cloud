from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import uuid4

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse
from jwt import InvalidTokenError

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.api.envelope import build_envelope
from app.core.config import Settings
from app.core.db import get_session
from app.core.models import PRINCIPAL_STATUS_ACTIVE
from app.core.security import (
    PUBLIC_REPLAY_POLICY_METHOD_DEFAULT,
    PUBLIC_RUNTIME_MAX_BODY_BYTES,
    REPLAY_SCOPE_INTERNAL,
    REPLAY_SCOPE_INTERNAL_POST,
    REPLAY_SCOPE_INTERNAL_POST_IP,
    RUNTIME_GUARD_SURFACE_INTERNAL,
    RequestAuthContext,
    RequestAuthError,
    RequestBodyEvidenceLoader,
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
PORTAL_SITE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,191}$")
PORTAL_SESSION_ISSUER = "npcink-ai-cloud"
PORTAL_SESSION_AUDIENCE = "npcink-ai-cloud-portal"
PORTAL_SESSION_PURPOSE = "portal_session"
PORTAL_SESSION_ALGORITHM = "HS256"
PORTAL_SESSION_REQUIRED_CLAIMS = (
    "iss",
    "aud",
    "sub",
    "purpose",
    "session_version",
    "iat",
    "exp",
)


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


def normalize_portal_site_id(value: object) -> str:
    if not isinstance(value, str):
        return ""
    site_id = value.strip()
    return site_id if PORTAL_SITE_ID_PATTERN.fullmatch(site_id) else ""


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
    if (
        not isinstance(principal_id, str)
        or not principal_id.strip()
        or principal_id != principal_id.strip()
    ):
        raise ValueError("principal_id must be a non-empty canonical string")
    if (
        isinstance(session_version, bool)
        or not isinstance(session_version, int)
        or session_version < 1
    ):
        raise ValueError("session_version must be a positive integer")
    if site_id != "" and (
        not isinstance(site_id, str) or normalize_portal_site_id(site_id) != site_id
    ):
        raise ValueError("site_id must be a canonical portal site id")
    now = datetime.now(UTC)
    resolved_expires_at = expires_at or (
        now + timedelta(seconds=resolve_portal_session_ttl_seconds(settings))
    )
    issued_at_timestamp = int(now.timestamp())
    expires_at_timestamp = int(resolved_expires_at.timestamp())
    if expires_at_timestamp <= issued_at_timestamp:
        raise ValueError("expires_at must be later than the token issue time")
    payload: dict[str, Any] = {
        "iss": _resolve_portal_jwt_issuer(settings),
        "aud": _resolve_portal_jwt_audience(settings),
        "sub": principal_id,
        "purpose": PORTAL_SESSION_PURPOSE,
        "session_version": session_version,
        "iat": issued_at_timestamp,
        "exp": expires_at_timestamp,
    }
    if site_id:
        payload["site_id"] = site_id
    return jwt.encode(
        payload,
        _resolve_portal_link_signing_secret(settings),
        algorithm=PORTAL_SESSION_ALGORITHM,
    )


def _resolve_portal_link_signing_secret(settings: Settings) -> str:
    secret = settings.portal_jwt_secret
    if not secret:
        raise RuntimeError("Portal auth is not configured.")
    return secret


def _resolve_portal_jwt_issuer(settings: Settings) -> str:
    issuer = str(settings.portal_jwt_issuer or "").strip()
    return issuer or PORTAL_SESSION_ISSUER


def _resolve_portal_jwt_audience(settings: Settings) -> str:
    audience = str(settings.portal_jwt_audience or "").strip()
    return audience or PORTAL_SESSION_AUDIENCE


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


def _raise_invalid_portal_claims(*, error_code: str, message: str) -> None:
    raise PortalBearerTokenError(403, error_code, message)


def _validate_portal_session_claims(
    settings: Settings,
    payload: object,
    *,
    expired_error_code: str,
    expired_message: str,
    invalid_error_code: str,
    invalid_message: str,
) -> dict[str, Any]:
    claims = _jwt_payload_dict(payload)
    principal_id = claims.get("sub")
    session_version = claims.get("session_version")
    issued_at = claims.get("iat")
    expires_at = claims.get("exp")
    not_before = claims.get("nbf")
    if (
        claims.get("iss") != _resolve_portal_jwt_issuer(settings)
        or claims.get("aud") != _resolve_portal_jwt_audience(settings)
        or claims.get("purpose") != PORTAL_SESSION_PURPOSE
        or not isinstance(principal_id, str)
        or not principal_id.strip()
        or principal_id != principal_id.strip()
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
        _raise_invalid_portal_claims(
            error_code=invalid_error_code,
            message=invalid_message,
        )
    issued_at_timestamp = cast(int, issued_at)
    expires_at_timestamp = cast(int, expires_at)
    not_before_timestamp = cast(int | None, not_before)
    try:
        datetime.fromtimestamp(issued_at_timestamp, tz=UTC)
        datetime.fromtimestamp(expires_at_timestamp, tz=UTC)
        if not_before_timestamp is not None:
            datetime.fromtimestamp(not_before_timestamp, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise PortalBearerTokenError(403, invalid_error_code, invalid_message) from error

    now_timestamp = datetime.now(UTC).timestamp()
    if issued_at_timestamp > now_timestamp or (
        not_before_timestamp is not None
        and (not_before_timestamp > now_timestamp or not_before_timestamp > expires_at_timestamp)
    ):
        _raise_invalid_portal_claims(
            error_code=invalid_error_code,
            message=invalid_message,
        )
    if expires_at_timestamp <= now_timestamp:
        raise PortalBearerTokenError(401, expired_error_code, expired_message)

    if "site_id" in claims:
        site_id = claims["site_id"]
        if (
            not isinstance(site_id, str)
            or not site_id
            or normalize_portal_site_id(site_id) != site_id
        ):
            _raise_invalid_portal_claims(
                error_code=invalid_error_code,
                message=invalid_message,
            )
    return claims


def _decode_portal_session_claims(
    settings: Settings,
    token: str,
    *,
    signing_secret: str,
    expired_error_code: str,
    expired_message: str,
    invalid_error_code: str,
    invalid_message: str,
) -> dict[str, Any]:
    decode_kwargs: dict[str, Any] = {
        "jwt": token,
        "key": signing_secret,
        "algorithms": [PORTAL_SESSION_ALGORITHM],
        "options": {
            "require": list(PORTAL_SESSION_REQUIRED_CLAIMS),
            "verify_exp": False,
            "verify_iat": False,
            "verify_nbf": False,
        },
        "issuer": _resolve_portal_jwt_issuer(settings),
        "audience": _resolve_portal_jwt_audience(settings),
    }

    try:
        payload = jwt.decode(**decode_kwargs)
    except (InvalidTokenError, TypeError, ValueError, OverflowError) as error:
        raise PortalBearerTokenError(
            403,
            invalid_error_code,
            invalid_message,
        ) from error

    return _validate_portal_session_claims(
        settings,
        payload,
        expired_error_code=expired_error_code,
        expired_message=expired_message,
        invalid_error_code=invalid_error_code,
        invalid_message=invalid_message,
    )


def decode_portal_bearer_claims(settings: Settings, token: str) -> dict[str, Any]:
    if not settings.portal_jwt_secret:
        raise PortalBearerTokenError(
            503,
            "auth.portal_not_configured",
            "portal auth is not configured",
        )
    return _decode_portal_session_claims(
        settings,
        token,
        signing_secret=settings.portal_jwt_secret,
        expired_error_code="auth.portal_token_expired",
        expired_message="portal token has expired",
        invalid_error_code="auth.portal_token_invalid",
        invalid_message="invalid portal bearer token",
    )


def decode_portal_session_cookie_claims(settings: Settings, token: str) -> dict[str, Any]:
    return _decode_portal_session_claims(
        settings,
        token,
        signing_secret=_resolve_portal_link_signing_secret(settings),
        expired_error_code="auth.portal_session_expired",
        expired_message="portal session has expired",
        invalid_error_code="auth.portal_session_invalid",
        invalid_message="invalid portal session token",
    )


def decode_portal_bearer_token(settings: Settings, token: str) -> str:
    payload = decode_portal_bearer_claims(settings, token)

    return _extract_portal_principal_id(payload)


def _extract_portal_principal_id(payload: dict[str, Any]) -> str:
    principal_id = payload.get("sub")
    if (
        not isinstance(principal_id, str)
        or not principal_id.strip()
        or principal_id != principal_id.strip()
    ):
        raise PortalBearerTokenError(
            403,
            "auth.portal_token_invalid",
            "invalid portal bearer token",
        )
    return principal_id


def _extract_portal_session_version(payload: dict[str, Any]) -> int:
    session_version = payload.get("session_version")
    if (
        isinstance(session_version, bool)
        or not isinstance(session_version, int)
        or session_version < 1
    ):
        raise PortalBearerTokenError(
            403,
            "auth.portal_token_invalid",
            "invalid portal bearer token",
        )
    return session_version


def _extract_portal_site_id(payload: dict[str, Any]) -> str:
    if "site_id" not in payload:
        return ""
    raw_site_id = payload["site_id"]
    if not isinstance(raw_site_id, str):
        raise PortalBearerTokenError(
            403,
            "auth.portal_token_invalid",
            "invalid portal bearer token",
        )
    site_id = normalize_portal_site_id(raw_site_id)
    if not site_id or site_id != raw_site_id:
        raise PortalBearerTokenError(
            403,
            "auth.portal_token_invalid",
            "invalid portal bearer token",
        )
    return site_id


def validate_portal_principal_session(
    settings: Settings,
    *,
    principal_id: str,
    session_version: int,
) -> None:
    if (
        isinstance(session_version, bool)
        or not isinstance(session_version, int)
        or session_version < 1
    ):
        raise PortalBearerTokenError(
            403,
            "auth.portal_token_invalid",
            "invalid portal bearer token",
        )
    with get_session(settings.database_url) as session:
        repository = CommercialRepository(session)
        identity = repository.get_principal_identity_by_ref(principal_id=principal_id)
        current_session_version = getattr(identity, "session_version", None)
        if (
            identity is None
            or identity.status != PRINCIPAL_STATUS_ACTIVE
            or isinstance(current_session_version, bool)
            or not isinstance(current_session_version, int)
            or current_session_version < 1
            or current_session_version != session_version
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
    body_evidence_loader: RequestBodyEvidenceLoader | None = None,
    replay_policy: str = PUBLIC_REPLAY_POLICY_METHOD_DEFAULT,
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
            max_body_bytes=(
                max_body_bytes if max_body_bytes is not None else PUBLIC_RUNTIME_MAX_BODY_BYTES
            ),
            body_evidence_loader=body_evidence_loader,
            replay_policy=replay_policy,
            public_pull_rate_limit_window_seconds=(
                services.settings.public_pull_rate_limit_window_seconds
            ),
            public_pull_max_requests_per_window=(
                services.settings.public_pull_max_requests_per_window
            ),
            public_pull_max_requests_per_key_window=(
                services.settings.public_pull_max_requests_per_key_window
            ),
            public_pull_max_requests_per_ip_window=(
                services.settings.public_pull_max_requests_per_ip_window
            ),
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

    if request.method.upper() in {"POST", "PUT"} and idempotency_key:
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
    return PortalAuthContext(
        principal_id=principal_id,
        site_id=_extract_portal_site_id(claims),
    )
