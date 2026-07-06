from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.envelope import build_envelope
from app.api.routes.agent_feedback import router as agent_feedback_router
from app.api.routes.audio_assets import router as audio_assets_router
from app.api.routes.auth import router as auth_router
from app.api.routes.catalog import router as catalog_router
from app.api.routes.entitlements import router as entitlements_router
from app.api.routes.health import router as health_router
from app.api.routes.internal import router as internal_router
from app.api.routes.media_derivatives import router as media_derivatives_router
from app.api.routes.observability import router as observability_router
from app.api.routes.open import router as open_router
from app.api.routes.portal import router as portal_router
from app.api.routes.runs import router as runs_router
from app.api.routes.runtime import router as runtime_router
from app.api.routes.service import router as service_router
from app.api.routes.stats import router as stats_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.services import CloudServices, create_default_services
from app.core.tracing import configure_tracing


def create_app(services: CloudServices | None = None) -> FastAPI:
    settings: Settings = services.settings if services is not None else get_settings()

    configure_logging(settings.log_level)
    configure_tracing(settings)

    app = FastAPI(
        title=settings.project_name,
        version="0.1.0",
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url="/redoc" if settings.environment != "production" else None,
    )
    trusted_hosts = sorted(settings.trusted_hosts())
    if trusted_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)

    @app.middleware("http")
    async def trace_requests(request: Request, call_next):  # type: ignore[no-untyped-def]
        tracer = trace.get_tracer("npcink_ai_cloud.http")
        span_name = f"{request.method} {request.url.path}"
        carrier = {key: value for key, value in request.headers.items()}
        context = propagate.extract(carrier)

        with tracer.start_as_current_span(
            span_name,
            context=context,
            kind=SpanKind.SERVER,
        ) as span:
            span.set_attribute("http.request.method", request.method)
            span.set_attribute("url.path", request.url.path)
            span.set_attribute("server.address", request.url.hostname or "")
            if request.url.scheme:
                span.set_attribute("url.scheme", request.url.scheme)

            try:
                response = await call_next(request)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR))
                raise

            route = request.scope.get("route")
            route_path = getattr(route, "path", "")
            if isinstance(route_path, str) and route_path:
                span.set_attribute("http.route", route_path)
            span.set_attribute("http.response.status_code", response.status_code)
            if response.status_code >= 500:
                span.set_status(Status(StatusCode.ERROR))
            else:
                span.set_status(Status(StatusCode.OK))
            return response

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    @app.middleware("http")
    async def guard_forwarded_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        forwarded_host = (
            str(request.headers.get("x-forwarded-host") or "").split(",", 1)[0].strip().lower()
        )
        forwarded_proto = (
            str(request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip().lower()
        )
        origin = settings._normalize_origin(request.headers.get("origin") or "")
        referer = settings._normalize_origin(request.headers.get("referer") or "")
        trusted_hosts_local = settings.trusted_hosts()
        trusted_origins = settings.explicit_browser_origins()
        development_like = not settings.production_like_environment()
        trusted_browser_origin_seen = bool(
            trusted_origins and (origin in trusted_origins or referer in trusted_origins)
        )

        if forwarded_host and forwarded_host not in trusted_hosts_local:
            if not (development_like and trusted_browser_origin_seen):
                return JSONResponse(
                    status_code=400,
                    content=build_envelope(
                        status="error",
                        error_code="request.forwarded_host_invalid",
                        message="forwarded host is not trusted",
                        revision="m7",
                    ),
                )

        if forwarded_proto and forwarded_proto not in {"http", "https"}:
            return JSONResponse(
                status_code=400,
                content=build_envelope(
                    status="error",
                    error_code="request.forwarded_proto_invalid",
                    message="forwarded proto is invalid",
                    revision="m7",
                ),
            )

        if forwarded_host and forwarded_proto and settings.production_like_environment():
            forwarded_origin = f"{forwarded_proto}://{forwarded_host.lower()}"
            if trusted_origins and forwarded_origin not in trusted_origins:
                return JSONResponse(
                    status_code=400,
                    content=build_envelope(
                        status="error",
                        error_code="request.forwarded_origin_invalid",
                        message="forwarded origin is not trusted",
                        revision="m7",
                    ),
                )

        return await call_next(request)

    app.state.services = services or create_default_services(settings)
    app.include_router(health_router)
    app.include_router(catalog_router)
    app.include_router(entitlements_router)
    app.include_router(internal_router)
    app.include_router(open_router)
    app.include_router(portal_router)
    app.include_router(service_router)
    app.include_router(observability_router)
    app.include_router(runtime_router)
    app.include_router(audio_assets_router)
    app.include_router(agent_feedback_router)
    app.include_router(media_derivatives_router)
    app.include_router(runs_router)
    app.include_router(stats_router)
    app.include_router(auth_router)

    return app


app = create_app()
