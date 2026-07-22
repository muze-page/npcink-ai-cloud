from __future__ import annotations

import asyncio
import hmac
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import Receive, Scope, Send

from app.api.envelope import build_envelope
from app.api.portal_idempotency_middleware import PortalIdempotencyMiddleware
from app.api.routes.agent_feedback import router as agent_feedback_router
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
from app.api.routes.setup import router as setup_router
from app.api.routes.stats import router as stats_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.redaction import safe_exception_type
from app.core.runtime_config import (
    RuntimeConfigError,
    config_dir_from_environment,
    production_runtime_enabled,
    read_internal_auth_token,
)
from app.core.services import CloudServices, create_default_services
from app.core.tracing import configure_tracing
from app.setup.errors import SetupError
from app.setup.service import SetupService
from app.setup.state import SetupConfigStore


def create_app(
    services: CloudServices | None = None,
    *,
    setup_service: SetupService | None = None,
) -> FastAPI:
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
    app.add_middleware(PortalIdempotencyMiddleware, settings=settings)

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
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            span.set_attribute("http.request.method", request.method)
            span.set_attribute("url.path", request.url.path)
            span.set_attribute("server.address", request.url.hostname or "")
            if request.url.scheme:
                span.set_attribute("url.scheme", request.url.scheme)

            try:
                response = await call_next(request)
            except Exception as exc:
                span.add_event(
                    "exception",
                    attributes={"exception.type": safe_exception_type(exc)},
                )
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
    if setup_service is not None:
        app.state.setup_service = setup_service
        app.include_router(setup_router)
    app.include_router(health_router)
    app.include_router(catalog_router)
    app.include_router(entitlements_router)
    app.include_router(internal_router)
    app.include_router(open_router)
    app.include_router(portal_router)
    app.include_router(service_router)
    app.include_router(observability_router)
    app.include_router(runtime_router)
    app.include_router(agent_feedback_router)
    app.include_router(media_derivatives_router)
    app.include_router(runs_router)
    app.include_router(stats_router)
    app.include_router(auth_router)

    return app


def _create_setup_app(setup_service: SetupService) -> FastAPI:
    setup_app = FastAPI(
        title="Npcink AI Cloud Setup",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    setup_app.state.setup_service = setup_service
    def safe_normalize_host(value: object) -> str:
        try:
            return Settings._normalize_host(value)
        except ValueError:
            return ""

    def safe_normalize_origin(value: object) -> str:
        try:
            return Settings._normalize_origin(value)
        except ValueError:
            return ""

    trusted_hosts = {
        normalized
        for item in str(os.environ.get("NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST") or "").split(",")
        if (normalized := safe_normalize_host(item))
    }
    trusted_hosts.update({"127.0.0.1", "localhost", "api"})
    trusted_origins = {
        normalized
        for item in str(os.environ.get("NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST") or "").split(",")
        if (normalized := safe_normalize_origin(item))
    }
    setup_app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=sorted(trusted_hosts),
    )

    @setup_app.middleware("http")
    async def setup_security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if request.url.path.startswith("/setup/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @setup_app.middleware("http")
    async def setup_forwarded_guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        forwarded_host = (
            str(request.headers.get("x-forwarded-host") or "").split(",", 1)[0].strip().lower()
        )
        forwarded_proto = (
            str(request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip().lower()
        )
        if forwarded_host and safe_normalize_host(forwarded_host) not in trusted_hosts:
            return JSONResponse(
                status_code=400,
                content=build_envelope(
                    status="error",
                    error_code="request.forwarded_host_invalid",
                    message="forwarded host is not trusted",
                    revision="first-install-v1",
                ),
                headers={"Cache-Control": "no-store"},
            )
        if forwarded_proto and forwarded_proto not in {"http", "https"}:
            return JSONResponse(
                status_code=400,
                content=build_envelope(
                    status="error",
                    error_code="request.forwarded_proto_invalid",
                    message="forwarded proto is invalid",
                    revision="first-install-v1",
                ),
                headers={"Cache-Control": "no-store"},
            )
        for header_name in ("origin", "referer"):
            raw_origin = str(request.headers.get(header_name) or "").strip()
            if not raw_origin:
                continue
            normalized_origin = safe_normalize_origin(raw_origin)
            if not normalized_origin or normalized_origin not in trusted_origins:
                return JSONResponse(
                    status_code=403,
                    content=build_envelope(
                        status="error",
                        error_code="request.browser_origin_invalid",
                        message="browser origin is not trusted",
                        revision="first-install-v1",
                    ),
                    headers={"Cache-Control": "no-store"},
                )
        return await call_next(request)

    setup_app.include_router(setup_router)

    @setup_app.get("/health/live", include_in_schema=False)
    async def setup_live() -> dict[str, object]:
        return build_envelope(
            status="ok",
            message="service is live",
            data={"service": "Npcink AI Cloud", "environment": "setup"},
            revision="first-install-v1",
        )

    @setup_app.get("/health/ready", include_in_schema=False)
    async def setup_ready() -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content=build_envelope(
                status="error",
                error_code="setup.installation_required",
                message="installation is required",
                revision="first-install-v1",
            ),
        )

    async def installation_required(request: Request) -> JSONResponse:
        if request.url.path.startswith("/setup/v1/"):
            return JSONResponse(
                status_code=404,
                content=build_envelope(
                    status="error",
                    error_code="setup.route_not_found",
                    message="setup route was not found",
                    revision="first-install-v1",
                ),
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse(
            status_code=503,
            content=build_envelope(
                status="error",
                error_code="setup.installation_required",
                message="installation is required",
                revision="first-install-v1",
            ),
            headers={"Cache-Control": "no-store"},
        )

    setup_app.add_api_route("/", installation_required, methods=["GET"], include_in_schema=False)
    setup_app.add_api_route(
        "/{path:path}",
        installation_required,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        include_in_schema=False,
    )
    return setup_app


class InstallAwareApplication:
    """Dispatch production traffic to bootstrap or the full runtime without DB startup coupling."""

    def __init__(self, setup_service: SetupService) -> None:
        self.setup_service = setup_service
        self.setup_app = _create_setup_app(setup_service)
        self.runtime_app: FastAPI | None = None
        self._activation_lock = asyncio.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            state = self.setup_service.state()
        except SetupError:
            await self.setup_app(scope, receive, send)
            return
        if state.installation_state != "complete":
            await self.setup_app(scope, receive, send)
            return
        if self._is_http_path(scope, "/health/live") and not self._is_http_get(scope):
            await self._method_not_allowed_response()(scope, receive, send)
            return
        if self._is_http_path(scope, "/health/ready") and not self._is_http_get(scope):
            await self._method_not_allowed_response()(scope, receive, send)
            return
        if self._is_http_path(scope, "/health/live"):
            await self._complete_live_response()(scope, receive, send)
            return
        if self._is_http_path(scope, "/health/ready"):
            auth_response = self._ready_auth_response(scope)
            if auth_response is not None:
                await auth_response(scope, receive, send)
                return
        try:
            runtime_app = await self._runtime_application()
        except Exception:
            response = self._runtime_unavailable_response()
            await response(scope, receive, send)
            return
        await runtime_app(scope, receive, send)

    @staticmethod
    def _is_http_path(scope: Scope, path: str) -> bool:
        return scope.get("type") == "http" and scope.get("path") == path

    @staticmethod
    def _is_http_get(scope: Scope) -> bool:
        return str(scope.get("method") or "").upper() == "GET"

    @staticmethod
    def _response_headers() -> dict[str, str]:
        return {
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
        }

    def _complete_live_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=200,
            content=build_envelope(
                status="ok",
                message="service is live",
                data={"service": "Npcink AI Cloud", "environment": "production"},
                revision="first-install-v1",
            ),
            headers=self._response_headers(),
        )

    def _method_not_allowed_response(self) -> JSONResponse:
        headers = self._response_headers()
        headers["Allow"] = "GET"
        return JSONResponse(
            status_code=405,
            content=build_envelope(
                status="error",
                error_code="request.method_not_allowed",
                message="method is not allowed",
                revision="first-install-v1",
            ),
            headers=headers,
        )

    def _ready_auth_response(self, scope: Scope) -> JSONResponse | None:
        provided_token = self._scope_header(scope, "x-npcink-internal-token")
        try:
            expected_token = read_internal_auth_token(self.setup_service.store.config_dir)
        except RuntimeConfigError:
            return JSONResponse(
                status_code=503,
                content=build_envelope(
                    status="error",
                    error_code="auth.internal_not_configured",
                    message="internal auth is not configured",
                    revision="first-install-v1",
                ),
                headers=self._response_headers(),
            )
        if not provided_token:
            return JSONResponse(
                status_code=401,
                content=build_envelope(
                    status="error",
                    error_code="auth.internal_token_required",
                    message="missing internal auth token",
                    revision="first-install-v1",
                ),
                headers=self._response_headers(),
            )
        if not hmac.compare_digest(provided_token, expected_token):
            return JSONResponse(
                status_code=401,
                content=build_envelope(
                    status="error",
                    error_code="auth.internal_token_invalid",
                    message="invalid internal auth token",
                    revision="first-install-v1",
                ),
                headers=self._response_headers(),
            )
        return None

    @staticmethod
    def _scope_header(scope: Scope, name: str) -> str:
        expected = name.lower().encode("latin-1")
        for raw_name, raw_value in scope.get("headers", []):
            if raw_name.lower() == expected:
                return raw_value.decode("latin-1").strip()
        return ""

    def _runtime_unavailable_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content=build_envelope(
                status="error",
                error_code="health.dependency_unavailable",
                message="runtime configuration is unavailable",
                revision="first-install-v1",
            ),
            headers=self._response_headers(),
        )

    async def _runtime_application(self) -> FastAPI:
        if self.runtime_app is not None:
            return self.runtime_app
        async with self._activation_lock:
            if self.runtime_app is None:
                self.runtime_app = await asyncio.to_thread(self._build_runtime_application)
        return self.runtime_app

    def _build_runtime_application(self) -> FastAPI:
        get_settings.cache_clear()
        settings = get_settings()
        return create_app(
            create_default_services(settings),
            setup_service=self.setup_service,
        )


def create_deployment_app() -> FastAPI | InstallAwareApplication:
    if not production_runtime_enabled():
        return create_app()
    public_origins = {
        normalized
        for item in str(os.environ.get("NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST") or "").split(",")
        if (normalized := Settings._normalize_origin(item))
    }
    setup_service = SetupService(
        SetupConfigStore(config_dir_from_environment()),
        public_origin_allowlist=public_origins,
    )
    return InstallAwareApplication(setup_service)


app = create_deployment_app()
