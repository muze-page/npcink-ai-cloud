from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.api.auth import (
    AUTHORIZATION_HEADER,
    PortalAuthContext,
    PortalBearerTokenError,
    authorize_portal_request,
    build_portal_session_token,
    decode_portal_bearer_claims,
    decode_portal_session_cookie_claims,
    get_cloud_services,
    normalize_portal_site_id,
    resolve_portal_remember_me_session_ttl_seconds,
    resolve_portal_session_ttl_seconds,
    validate_portal_principal_session,
)
from app.api.envelope import build_envelope
from app.core.db import get_session
from app.core.models import PRINCIPAL_STATUS_ACTIVE, SITE_STATUS_ACTIVE, SITE_STATUS_ARCHIVED
from app.core.security import extract_trace_id
from app.domain.commercial.errors import CommercialServiceError
from app.domain.commercial.service import CommercialService
from app.domain.portal_idempotency import (
    PortalIdempotencyClaim,
    PortalIdempotencyError,
    PortalIdempotencyReplay,
    build_portal_request_fingerprint,
    claim_portal_mutation,
)

COOKIE_PORTAL_SESSION_TOKEN = "npcink_portal_session_token"


def _dict_value(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _dict_list(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _object_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def get_commercial_service(request: Request) -> CommercialService:
    services = get_cloud_services(request)
    return CommercialService(services.settings.database_url, settings=services.settings)


def portal_auth_mode(request: Request) -> str:
    settings = get_cloud_services(request).settings
    if settings.portal_jwt_secret:
        return "jwt"
    return "disabled"


def _safe_portal_error_message(error_code: str) -> str:
    messages = {
        "auth.portal_session_required": "portal session is required",
        "auth.portal_session_revoked": "portal session is no longer valid",
        "auth.portal_session_invalid": "portal session is invalid",
        "auth.portal_login_code_invalid": "portal login code is invalid",
        "auth.portal_oauth_failed": "portal OAuth request failed",
        "portal.site_selection_required": "portal site selection is required",
        "auth.idempotency_required": "Idempotency-Key header is required",
        "auth.invalid_idempotency_key": "Idempotency-Key header is invalid",
        "auth.invalid_idempotency_request": "portal idempotency request is invalid",
        "portal.idempotency_conflict": "Idempotency-Key was used for a different request",
        "portal.idempotency_in_progress": "a request with this Idempotency-Key is processing",
        "portal.idempotency_indeterminate": "the original request result requires reconciliation",
        "portal.idempotency_receipt_unavailable": "portal idempotency receipt is unavailable",
    }
    return messages.get(str(error_code or ""), "portal request failed")


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
            message=_safe_portal_error_message(error_code),
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
    if settings.portal_jwt_secret:
        token = request.cookies.get(COOKIE_PORTAL_SESSION_TOKEN, "").strip()
        if not token:
            raise PortalBearerTokenError(
                401,
                session_required_error_code,
                session_required_message,
            )
        claims = decode_portal_session_cookie_claims(settings, token)
        principal_id = claims["sub"]
        validate_portal_principal_session(
            settings,
            principal_id=principal_id,
            session_version=claims["session_version"],
        )
        token_expires_at = (
            datetime.fromtimestamp(claims["exp"], tz=UTC).isoformat().replace("+00:00", "Z")
        )
        token_issued_at = (
            datetime.fromtimestamp(claims["iat"], tz=UTC).isoformat().replace("+00:00", "Z")
        )
        return {
            "principal_id": principal_id,
            "site_id": claims.get("site_id", ""),
            "auth_mode": "jwt",
            "issued_at": token_issued_at,
            "expires_at": token_expires_at,
        }

    raise PortalBearerTokenError(
        503,
        "auth.portal_not_configured",
        "portal auth is not configured",
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
    site_id = session["site_id"]
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
    principal_id: str,
    site_id: str = "",
    strict_site: bool = True,
    session_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    service = get_commercial_service(request)
    sites = service.list_portal_sites(principal_id=principal_id)
    principal_profile = service.get_portal_principal_profile(principal_id=principal_id)
    site_items = [
        _portal_site_projection(_dict_value(item.get("site")))
        for item in _dict_list(sites.get("items"))
    ]
    selected_context: dict[str, object] | None = None
    session = session_metadata or _resolve_portal_session_metadata(
        request,
        principal_id=principal_id,
    )
    if site_id:
        try:
            access = service.resolve_portal_site_access(
                site_id=site_id,
                principal_id=principal_id,
            )
        except CommercialServiceError:
            if strict_site:
                raise
        else:
            selected_site = _dict_value(access.get("site"))
            selected_status = str(selected_site.get("status") or "").strip()
            if selected_status == SITE_STATUS_ARCHIVED:
                if strict_site:
                    raise CommercialServiceError(
                        403,
                        "service.portal_site_removed",
                        "removed portal sites cannot be selected as the current site",
                    )
            elif selected_status != SITE_STATUS_ACTIVE:
                if strict_site:
                    raise CommercialServiceError(
                        403,
                        "service.portal_site_inactive",
                        "inactive portal sites cannot be selected as the current site",
                    )
            else:
                account_id = str(access.get("account_id") or "").strip()
                current_subscription = (
                    service.get_portal_current_subscription(account_id=account_id)
                    if account_id
                    else None
                )
                selected_context = {
                    "site": _portal_site_projection(selected_site),
                    "allowed_actions": sorted(
                        {
                            str(action).strip()
                            for action in _object_list(access.get("allowed_actions"))
                            if str(action).strip()
                        }
                    ),
                    "current_subscription": project_portal_subscription(
                        _dict_value(current_subscription)
                    )
                    if current_subscription
                    else None,
                }
    return {
        "email": str(principal_profile.get("email") or ""),
        "sites": site_items,
        "selected_context": selected_context,
        "auth_mode": portal_auth_mode(request),
        "session": {
            "state": "active",
            "transport": str(session.get("transport") or "cookie"),
            "issued_at": session.get("issued_at", ""),
            "expires_at": session.get("expires_at", ""),
            "revocable": bool(session.get("revocable")),
        },
    }


def _portal_site_projection(site: dict[str, object]) -> dict[str, object]:
    return {
        "site_id": str(site.get("site_id") or ""),
        "name": str(site.get("name") or ""),
        "site_url": str(site.get("site_url") or ""),
        "platform_kind": str(site.get("platform_kind") or ""),
        "status": str(site.get("status") or ""),
    }


def project_portal_subscription(subscription: dict[str, object]) -> dict[str, object]:
    return {
        "subscription_id": str(subscription.get("subscription_id") or ""),
        "plan_id": str(subscription.get("plan_id") or ""),
        "plan_version_id": str(subscription.get("plan_version_id") or ""),
        "status": str(subscription.get("status") or ""),
        "tier_id": str(subscription.get("tier_id") or ""),
        "plan_kind": str(subscription.get("plan_kind") or ""),
        "package_kind": str(subscription.get("package_kind") or ""),
        "package_alias": str(subscription.get("package_alias") or ""),
        "display_package_label": str(subscription.get("display_package_label") or ""),
        "coverage_state": str(subscription.get("coverage_state") or ""),
        "current_period_start_at": str(subscription.get("current_period_start_at") or ""),
        "current_period_end_at": str(subscription.get("current_period_end_at") or ""),
        "scheduled_plan_id": str(subscription.get("scheduled_plan_id") or ""),
        "scheduled_plan_version_id": str(
            subscription.get("scheduled_plan_version_id") or ""
        ),
        "scheduled_change_at": str(subscription.get("scheduled_change_at") or ""),
    }


def build_new_portal_session_metadata(
    request: Request,
    *,
    ttl_seconds: int | None = None,
) -> dict[str, object]:
    settings = get_cloud_services(request).settings
    now = datetime.now(UTC)
    resolved_ttl_seconds = (
        max(60, int(ttl_seconds or 0))
        if ttl_seconds is not None
        else resolve_portal_session_ttl_seconds(settings)
    )
    return {
        "principal_id": "",
        "issued_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(seconds=resolved_ttl_seconds))
        .isoformat()
        .replace("+00:00", "Z"),
        "transport": "cookie",
        "revocable": True,
    }


def set_portal_session_cookies(
    request: Request,
    response: JSONResponse,
    *,
    principal_id: str,
    site_id: str = "",
    session_version: int | None = None,
    ttl_seconds: int | None = None,
) -> None:
    settings = get_cloud_services(request).settings
    now = datetime.now(UTC)
    resolved_ttl_seconds = (
        max(60, int(ttl_seconds or 0))
        if ttl_seconds is not None
        else resolve_portal_session_ttl_seconds(settings)
    )
    secure = portal_cookie_secure(request)
    if (
        not isinstance(principal_id, str)
        or not principal_id.strip()
        or principal_id != principal_id.strip()
    ):
        raise PortalBearerTokenError(
            403,
            "auth.portal_session_invalid",
            "invalid portal session principal",
        )
    if site_id != "" and (
        not isinstance(site_id, str) or normalize_portal_site_id(site_id) != site_id
    ):
        raise PortalBearerTokenError(
            403,
            "auth.portal_session_invalid",
            "invalid portal session site",
        )
    if session_version is not None and (
        isinstance(session_version, bool)
        or not isinstance(session_version, int)
        or session_version < 1
    ):
        raise PortalBearerTokenError(
            403,
            "auth.portal_session_invalid",
            "invalid portal session version",
        )
    current_session_version = _resolve_portal_principal_session_version(
        request,
        principal_id=principal_id,
    )
    if session_version is not None and session_version != current_session_version:
        raise PortalBearerTokenError(
            401,
            "auth.portal_session_revoked",
            "portal session is no longer valid",
        )
    response.set_cookie(
        COOKIE_PORTAL_SESSION_TOKEN,
        build_portal_session_token(
            settings,
            principal_id=principal_id,
            site_id=site_id,
            session_version=current_session_version,
            expires_at=now + timedelta(seconds=resolved_ttl_seconds),
        ),
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=resolved_ttl_seconds,
    )


def resolve_portal_login_session_ttl_seconds(request: Request, *, remember_me: bool) -> int:
    settings = get_cloud_services(request).settings
    if remember_me:
        return resolve_portal_remember_me_session_ttl_seconds(settings)
    return resolve_portal_session_ttl_seconds(settings)


def _resolve_portal_principal_session_version(
    request: Request,
    *,
    principal_id: str,
) -> int:
    settings = get_cloud_services(request).settings
    with get_session(settings.database_url) as session:
        repository = CommercialRepository(session)
        identity = repository.get_principal_identity_by_ref(principal_id=principal_id)
        session_version = getattr(identity, "session_version", None)
        if (
            identity is None
            or identity.status != PRINCIPAL_STATUS_ACTIVE
            or isinstance(session_version, bool)
            or not isinstance(session_version, int)
            or session_version < 1
        ):
            raise PortalBearerTokenError(
                401,
                "auth.portal_session_revoked",
                "portal session is no longer valid",
            )
        return session_version


def clear_portal_session_cookies(response: JSONResponse | RedirectResponse) -> None:
    response.delete_cookie(COOKIE_PORTAL_SESSION_TOKEN)


def _has_portal_request_headers(request: Request) -> bool:
    return any(
        [
            request.headers.get(AUTHORIZATION_HEADER, "").strip(),
        ]
    )


def portal_idempotency_replay_response(request: Request) -> Response | None:
    replay = getattr(request.state, "portal_idempotency_replay", None)
    if not isinstance(replay, PortalIdempotencyReplay):
        return None
    return Response(
        status_code=replay.status_code,
        content=replay.body,
        media_type="application/json",
        headers={"Idempotency-Replayed": "true"},
    )


def _resolve_portal_session_metadata(request: Request, *, principal_id: str) -> dict[str, object]:
    if _has_portal_request_headers(request):
        auth_header = request.headers.get(AUTHORIZATION_HEADER, "").strip()
        if auth_header.lower().startswith("bearer "):
            claims = decode_portal_bearer_claims(
                get_cloud_services(request).settings,
                auth_header[7:].strip(),
            )
            expires_at = (
                datetime.fromtimestamp(claims["exp"], tz=UTC).isoformat().replace("+00:00", "Z")
            )
            issued_at = (
                datetime.fromtimestamp(claims["iat"], tz=UTC).isoformat().replace("+00:00", "Z")
            )
            return {
                "principal_id": principal_id,
                "issued_at": issued_at,
                "expires_at": expires_at,
                "transport": "header",
                "revocable": False,
            }
        return {
            "principal_id": principal_id,
            "issued_at": "",
            "expires_at": "",
            "transport": "header",
            "revocable": False,
        }

    session = current_portal_browser_session(request)
    return {
        "principal_id": principal_id,
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
        auth = await authorize_portal_request(
            request,
            require_idempotency=require_idempotency,
        )
    elif allow_session_cookies:
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
        auth = PortalAuthContext(
            principal_id=session["principal_id"],
            site_id=str(session.get("site_id") or ""),
        )
    else:
        auth = await authorize_portal_request(
            request,
            require_idempotency=require_idempotency,
        )

    if isinstance(auth, JSONResponse) or not require_idempotency:
        return auth
    try:
        fingerprint = build_portal_request_fingerprint(
            method=request.method,
            route=request.url.path,
            query_string=request.url.query,
            body=await request.body(),
            site_id=auth.site_id,
        )
        outcome = claim_portal_mutation(
            database_url=get_cloud_services(request).settings.database_url,
            principal_id=auth.principal_id,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
            method=request.method,
            route=request.url.path,
            request_fingerprint=fingerprint,
            lease_seconds=get_cloud_services(
                request
            ).settings.portal_idempotency_processing_lease_seconds,
            ttl_seconds=get_cloud_services(request).settings.portal_idempotency_ttl_seconds,
            settings=get_cloud_services(request).settings,
        )
    except PortalIdempotencyError as error:
        return portal_json_error(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
        )
    if isinstance(outcome, PortalIdempotencyReplay):
        request.state.portal_idempotency_replay = outcome
        return auth
    if not isinstance(outcome, PortalIdempotencyClaim):
        raise RuntimeError("unexpected Portal idempotency outcome")
    request.state.portal_idempotency_claim = outcome
    return auth
