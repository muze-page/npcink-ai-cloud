from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.adapters.notifications.base import PortalEmailDeliveryError
from app.adapters.notifications.smtp import build_portal_email_sender
from app.adapters.providers.registry import resolve_live_provider_adapters
from app.api.auth import authorize_internal_request
from app.api.envelope import build_envelope
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from app.domain.service_settings import resolve_portal_public_base_url

router = APIRouter(prefix="/internal", tags=["internal"])


class ProviderSelection(BaseModel):
    providers: list[str] = Field(default_factory=list)


class PortalEmailTestRequest(BaseModel):
    recipient_email: str = Field(min_length=3, max_length=320)


def _get_catalog_service(request: Request) -> CatalogService:
    services = getattr(request.app.state, "services", None)
    if services is None:
        raise RuntimeError("Cloud services are not configured.")

    typed_services = cast(CloudServices, services)
    return CatalogService(
        typed_services.settings.database_url,
        providers=resolve_live_provider_adapters(
            typed_services.settings,
            base_providers=typed_services.providers,
            include_enabled_connections=True,
        ),
    )


def _get_cloud_services(request: Request) -> CloudServices:
    services = getattr(request.app.state, "services", None)
    if services is None:
        raise RuntimeError("Cloud services are not configured.")
    return cast(CloudServices, services)


@router.post("/catalog/refresh")
async def refresh_catalog(
    request: Request,
    payload: ProviderSelection | None = None,
) -> Any:
    auth = await authorize_internal_request(
        request,
        require_idempotency=True,
    )
    if auth is not None:
        return auth

    service = _get_catalog_service(request)
    providers = payload.providers if payload is not None else None
    try:
        result = service.refresh_catalog(provider_ids=providers or None)
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                status="error",
                error_code="catalog.provider_invalid",
                message=str(error),
                data={"providers": providers or []},
            ),
        )

    return build_envelope(
        status="ok",
        message="catalog refreshed",
        data=result,
        revision=result["revision"],
    )


@router.post("/health/providers/scan")
async def scan_provider_health(
    request: Request,
    payload: ProviderSelection | None = None,
) -> Any:
    auth = await authorize_internal_request(
        request,
        require_idempotency=True,
    )
    if auth is not None:
        return auth

    service = _get_catalog_service(request)
    providers = payload.providers if payload is not None else None
    try:
        result = service.scan_provider_health(provider_ids=providers or None)
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                status="error",
                error_code="catalog.provider_invalid",
                message=str(error),
                data={"providers": providers or []},
            ),
        )

    return build_envelope(
        status="ok",
        message="provider health scan completed",
        data=result,
    )


@router.post("/portal/email/test")
async def send_portal_email_test(
    request: Request,
    payload: PortalEmailTestRequest,
) -> Any:
    auth = await authorize_internal_request(
        request,
        require_idempotency=True,
    )
    if auth is not None:
        return auth

    services = _get_cloud_services(request)
    email_sender = services.portal_email_sender or build_portal_email_sender(
        services.settings,
        database_url=services.settings.database_url,
    )
    if email_sender is None:
        return JSONResponse(
            status_code=503,
            content=build_envelope(
                status="error",
                error_code="portal.email_not_configured",
                message="portal email delivery is not configured",
                data={},
                revision="m6",
            ),
        )

    recipient_email = payload.recipient_email.strip().lower()
    portal_base_url = resolve_portal_public_base_url(
        services.settings.database_url,
        services.settings,
    ).rstrip("/")
    portal_url = portal_base_url or str(request.base_url).rstrip("/")
    if portal_url:
        portal_url = f"{portal_url}/portal/login"
    else:
        portal_url = "/portal/login"

    try:
        email_sender.send_test_email(
            recipient_email=recipient_email,
            project_name=services.settings.project_name,
            portal_url=portal_url,
        )
    except PortalEmailDeliveryError as error:
        return JSONResponse(
            status_code=502,
            content=build_envelope(
                status="error",
                error_code="portal.email_delivery_failed",
                message=str(error),
                data={"recipient_email": recipient_email},
                revision="m6",
            ),
        )

    return build_envelope(
        status="ok",
        message="portal test email sent",
        data={
            "recipient_email": recipient_email,
            "delivery": "email",
            "portal_url": portal_url,
        },
        revision="m6",
    )
