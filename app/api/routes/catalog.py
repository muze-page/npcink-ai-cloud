from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.adapters.providers.registry import resolve_live_provider_adapters
from app.api.auth import authorize_public_request
from app.api.envelope import build_envelope
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService

router = APIRouter(prefix="/v1/catalog", tags=["catalog"])


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


@router.get("/revision")
async def get_catalog_revision(request: Request) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="catalog:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_catalog_service(request)
    revision = service.get_revision()

    return build_envelope(
        status="ok",
        message="platform models revision loaded",
        data=revision,
        revision=revision["revision"],
    )


@router.get("/platform-models/revision")
async def get_platform_models_revision(request: Request) -> Any:
    return await get_catalog_revision(request)


@router.get("/models")
async def list_catalog_models(
    request: Request,
    provider_id: str | None = None,
    feature: str | None = None,
    status: str | None = None,
    search: str | None = None,
    fallback_candidate: bool | None = None,
    recommended_for: str | None = None,
    deprecated_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="catalog:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_catalog_service(request)
    result = service.list_models(
        provider_id=provider_id,
        feature=feature,
        status=status,
        search=search,
        fallback_candidate=fallback_candidate,
        recommended_for=recommended_for,
        deprecated_only=deprecated_only,
        limit=limit,
        offset=offset,
    )

    return build_envelope(
        status="ok",
        message="platform models loaded",
        data=result,
        revision=result["revision"],
    )


@router.get("/platform-models")
async def list_platform_models(
    request: Request,
    provider_id: str | None = None,
    feature: str | None = None,
    status: str | None = None,
    search: str | None = None,
    fallback_candidate: bool | None = None,
    recommended_for: str | None = None,
    deprecated_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    return await list_catalog_models(
        request=request,
        provider_id=provider_id,
        feature=feature,
        status=status,
        search=search,
        fallback_candidate=fallback_candidate,
        recommended_for=recommended_for,
        deprecated_only=deprecated_only,
        limit=limit,
        offset=offset,
    )


@router.get("/models/{model_id}")
async def get_catalog_model(request: Request, model_id: str) -> JSONResponse:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="catalog:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_catalog_service(request)
    result = service.get_model(model_id)

    if result is None:
        return JSONResponse(
            status_code=404,
            content=build_envelope(
                status="error",
                error_code="catalog.model_not_found",
                message="catalog model not found",
                data={"model_id": model_id},
            ),
        )

    return JSONResponse(
        status_code=200,
        content=build_envelope(
            status="ok",
            message="platform model loaded",
            data=result,
            revision=str(result["revision"]),
        ),
    )


@router.get("/platform-models/{model_id}")
async def get_platform_model(request: Request, model_id: str) -> JSONResponse:
    return await get_catalog_model(request, model_id)
