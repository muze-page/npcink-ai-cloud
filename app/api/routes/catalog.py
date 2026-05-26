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
        recognition_evidence_snapshot_path=typed_services.settings.recognition_evidence_snapshot_path,
    )


def _serialize_public_recognition_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    allowed_source_keys = {
        "catalog_revision",
        "recognition_derivation",
        "manual_curation_version",
        "hf_alias_bridge_version",
        "upstream_evidence_version",
        "litellm_revision",
        "openrouter_snapshot",
        "hf_snapshot",
        "ollama_snapshot",
    }
    sanitized = {
        key: value
        for key, value in bundle.items()
        if key not in {"source_runs", "source_run_ids", "source_failures"}
    }
    sources = sanitized.get("sources")
    if isinstance(sources, dict):
        sanitized["sources"] = {
            key: value for key, value in sources.items() if key in allowed_source_keys
        }
    models = sanitized.get("models")
    if isinstance(models, list):
        allowed_model_keys = {
            "provider",
            "model_id",
            "match_keys",
            "aliases",
            "model_type",
            "preview_type",
            "input_modalities",
            "output_modalities",
            "capabilities",
            "confidence",
            "price_input",
            "price_output",
            "source",
            "evidence",
            "updated_at",
            "deprecated",
        }
        sanitized["models"] = [
            {
                key: value
                for key, value in item.items()
                if key in allowed_model_keys
            }
            for item in models
            if isinstance(item, dict)
        ]
        for item in sanitized["models"]:
            if not isinstance(item, dict):
                continue
            if str(item.get("source") or "").strip() == "cloud_intelligence":
                item["source"] = "cloud_published"
    return sanitized


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


@router.get("/recognition/revision")
async def get_recognition_revision(request: Request) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="catalog:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_catalog_service(request)
    revision = service.get_recognition_revision()

    return build_envelope(
        status="ok",
        message="recognition revision loaded",
        data=revision,
        revision=revision["revision"],
    )


@router.get("/recognition-intelligence/revision")
async def get_recognition_intelligence_revision(request: Request) -> Any:
    return await get_recognition_revision(request)


@router.get("/recognition/bundle")
async def get_recognition_bundle(request: Request) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="catalog:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_catalog_service(request)
    bundle = service.get_recognition_bundle()

    return build_envelope(
        status="ok",
        message="recognition bundle loaded",
        data=_serialize_public_recognition_bundle(bundle),
        revision=bundle["revision"],
    )


@router.get("/recognition-intelligence/bundle")
async def get_recognition_intelligence_bundle(request: Request) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="catalog:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_catalog_service(request)
    bundle = service.get_recognition_bundle()

    return build_envelope(
        status="ok",
        message="recognition intelligence bundle loaded",
        data={
            **bundle,
            "bundle_kind": "recognition_intelligence_bundle_v1",
        },
        revision=bundle["revision"],
    )


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
