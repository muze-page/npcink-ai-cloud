from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request

from app.api.auth import (
    PortalBearerTokenError,
    _debug_local_origin_allowed,
    get_cloud_services,
)


def _first_header_value(value: str) -> str:
    return value.split(",", 1)[0].strip()


def _normalize_origin(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _loopback_origin_aliases(origin: str) -> set[str]:
    normalized = _normalize_origin(origin)
    if not normalized:
        return set()
    parsed = urlsplit(normalized)
    host = parsed.hostname or ""
    if host not in {"127.0.0.1", "localhost"}:
        return set()
    port = f":{parsed.port}" if parsed.port is not None else ""
    scheme = parsed.scheme.lower()
    return {
        f"{scheme}://127.0.0.1{port}",
        f"{scheme}://localhost{port}",
    }


def _allow_local_debug_portal_same_origin_bypass(request: Request) -> bool:
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


def allowed_browser_origins(request: Request) -> set[str]:
    settings = get_cloud_services(request).settings
    origins = set(settings.explicit_browser_origins())

    if str(settings.environment or "").strip().lower() in {"development", "test"}:
        request_origin = _normalize_origin(str(request.base_url))
        if request_origin:
            origins.add(request_origin)
        loopback_aliases: set[str] = set()
        for origin in tuple(origins):
            loopback_aliases.update(_loopback_origin_aliases(origin))
        origins.update(loopback_aliases)

    return {origin for origin in origins if origin}


def enforce_browser_same_origin(
    request: Request,
    *,
    missing_error_code: str = "auth.origin_required",
    missing_message: str = "origin or referer header is required",
    forbidden_error_code: str = "auth.origin_forbidden",
    forbidden_message: str = "cross-site browser writes are not allowed",
) -> None:
    if _allow_local_debug_portal_same_origin_bypass(request):
        return

    origin = _normalize_origin(str(request.headers.get("origin") or ""))
    if not origin:
        origin = _normalize_origin(str(request.headers.get("referer") or ""))
    if not origin:
        raise PortalBearerTokenError(
            403,
            missing_error_code,
            missing_message,
        )
    if origin not in allowed_browser_origins(request):
        raise PortalBearerTokenError(
            403,
            forbidden_error_code,
            forbidden_message,
        )


def enforce_json_request(
    request: Request,
    *,
    error_code: str = "request.content_type_invalid",
    message: str = "application/json content-type is required",
) -> None:
    content_type = str(request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        return
    raise PortalBearerTokenError(415, error_code, message)
