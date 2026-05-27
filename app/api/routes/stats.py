from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.api.auth import authorize_public_request, get_cloud_services
from app.api.envelope import build_envelope
from app.domain.usage.rollup import UsageRollupService
from app.domain.usage.service import (
    UsageInstanceNotFoundError,
    UsageProfileNotFoundError,
    UsageService,
)

router = APIRouter(tags=["stats"])


def _get_usage_service(request: Request) -> UsageService:
    services = get_cloud_services(request)
    return UsageService(services.settings.database_url)


def _get_usage_rollup_service(request: Request) -> UsageRollupService:
    services = get_cloud_services(request)
    return UsageRollupService(services.settings.database_url)


def _parse_projection_gmt(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


def _get_logs_analytics_filters(
    log_type: str = Query(default="", max_length=64),
    status: str = Query(default="all", max_length=32),
    provider: str = Query(default="", max_length=191),
    model: str = Query(default="", max_length=191),
    user_id: int = Query(default=0, ge=0, le=2147483647),
    post_id: int = Query(default=0, ge=0, le=2147483647),
    trace_id: str = Query(default="", max_length=191),
    caller_id: str = Query(default="", max_length=191),
    app_id: str = Query(default="", max_length=191),
    ability_id: str = Query(default="", max_length=191),
    error_code: str = Query(default="", max_length=191),
    role_id: str = Query(default="", max_length=191),
    resource_id: str = Query(default="", max_length=191),
    mcp_server_id: str = Query(default="", max_length=191),
    mcp_method: str = Query(default="", max_length=191),
    range: str = Query(default="24h", max_length=16),
    start_gmt: str = Query(default="", max_length=32),
    end_gmt: str = Query(default="", max_length=32),
    limit: int = Query(default=25, ge=1, le=1000),
) -> dict[str, Any]:
    return {
        "log_type": log_type,
        "status": status,
        "provider": provider,
        "model": model,
        "user_id": user_id,
        "post_id": post_id,
        "trace_id": trace_id,
        "caller_id": caller_id,
        "app_id": app_id,
        "ability_id": ability_id,
        "error_code": error_code,
        "role_id": role_id,
        "resource_id": resource_id,
        "mcp_server_id": mcp_server_id,
        "mcp_method": mcp_method,
        "range": range,
        "start_gmt": start_gmt,
        "end_gmt": end_gmt,
        "limit": limit,
    }


@router.get("/v1/stats/instances/{instance_id}")
async def get_instance_stats(
    request: Request,
    instance_id: str,
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="stats:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    result = _get_usage_rollup_service(request).get_latency_probe_instance_batch(
        site_id=auth.site_id,
        instance_id=instance_id,
    )
    service = _get_usage_service(request)
    if result is None:
        try:
            result = service.build_empty_instance_stats(instance_id)
        except UsageInstanceNotFoundError as error:
            return JSONResponse(
                status_code=404,
                content=build_envelope(
                    status="error",
                    error_code=error.error_code,
                    message=error.message,
                    data={"instance_id": instance_id},
                    revision="m3",
                ),
            )

    return build_envelope(
        status="ok",
        message="instance stats loaded",
        data=result,
        revision="m3",
    )


@router.get("/v1/stats/profiles/{profile_id}")
async def get_profile_stats(
    request: Request,
    profile_id: str,
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="stats:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_usage_service(request)

    try:
        result = service.get_profile_stats(profile_id, site_id=auth.site_id)
    except UsageProfileNotFoundError as error:
        return JSONResponse(
            status_code=404,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                data={"profile_id": profile_id},
                revision="m3",
            ),
        )

    return build_envelope(
        status="ok",
        message="profile stats loaded",
        data=result,
        revision="m3",
    )


@router.get("/v1/stats/hosted/discovery")
async def get_hosted_discovery(
    request: Request,
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="stats:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    result = _get_usage_service(request).get_hosted_discovery(site_id=auth.site_id)

    return build_envelope(
        status="ok",
        message="hosted discovery loaded",
        data=result,
        revision="m3",
    )


@router.get("/v1/stats/hosted/profiles/{profile_id}/metadata")
async def get_hosted_profile_metadata(
    request: Request,
    profile_id: str,
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="stats:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_usage_service(request)

    try:
        result = service.get_hosted_profile_metadata(profile_id, site_id=auth.site_id)
    except UsageProfileNotFoundError as error:
        return JSONResponse(
            status_code=404,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                data={"profile_id": profile_id},
                revision="m3",
            ),
        )

    return build_envelope(
        status="ok",
        message="hosted profile metadata loaded",
        data=result,
        revision="m3",
    )


@router.get("/v1/stats/hosted/instances/{instance_id}/metadata")
async def get_hosted_instance_metadata(
    request: Request,
    instance_id: str,
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="stats:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_usage_service(request)

    try:
        result = service.get_hosted_instance_metadata(instance_id, site_id=auth.site_id)
    except UsageInstanceNotFoundError as error:
        return JSONResponse(
            status_code=404,
            content=build_envelope(
                status="error",
                error_code=error.error_code,
                message=error.message,
                data={"instance_id": instance_id},
                revision="m3",
            ),
        )

    return build_envelope(
        status="ok",
        message="hosted instance metadata loaded",
        data=result,
        revision="m3",
    )


@router.get("/v1/usage/summary")
async def get_usage_summary(request: Request) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="stats:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    service = _get_usage_service(request)
    result = service.get_usage_summary(site_id=auth.site_id)

    return build_envelope(
        status="ok",
        message="usage summary loaded",
        data=result,
        revision="m3",
    )


@router.get("/v1/router/performance-snapshot")
async def get_router_performance_snapshot_projection(
    request: Request,
    start_gmt: str = Query(min_length=19, max_length=19),
    end_gmt: str = Query(min_length=19, max_length=19),
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="stats:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    try:
        start_at = _parse_projection_gmt(start_gmt)
        end_at = _parse_projection_gmt(end_gmt)
        rollup_service = _get_usage_rollup_service(request)
        usage_service = _get_usage_service(request)
        result = rollup_service.get_router_performance_snapshot_batch(
            site_id=auth.site_id,
            start_at=start_at,
            end_at=end_at,
        )
        if result is None:
            result = usage_service.build_empty_router_performance_snapshot_projection(
                site_id=auth.site_id,
                start_at=start_at,
                end_at=end_at,
            )
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                status="error",
                error_code="stats.invalid_projection_window",
                message=str(error),
                data={"start_gmt": start_gmt, "end_gmt": end_gmt},
                revision="m3",
            ),
        )

    return build_envelope(
        status="ok",
        message="router performance snapshot projection loaded",
        data=result,
        revision="m3",
    )


@router.get("/v1/router/recommendation")
async def get_router_recommendation_summary(
    request: Request,
    filters: dict[str, Any] = Depends(_get_logs_analytics_filters),
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="stats:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    try:
        result = _get_usage_service(request).get_router_recommendation_summary(
            site_id=auth.site_id,
            filters=filters,
        )
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                status="error",
                error_code="stats.invalid_logs_window",
                message=str(error),
                data=filters,
                revision="m3",
            ),
        )

    return build_envelope(
        status="ok",
        message="router recommendation summary loaded",
        data=result,
        revision="m3",
    )


# Canonical public read surface for heavy logs analytics. Local/plugin paths may
# only consume these projections or degrade to cached snapshot / empty shape.
@router.get("/v1/logs/analytics/summary")
async def get_logs_analytics_summary(
    request: Request,
    filters: dict[str, Any] = Depends(_get_logs_analytics_filters),
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="stats:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    try:
        result = _get_usage_service(request).get_logs_analytics_summary(
            site_id=auth.site_id,
            filters=filters,
        )
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                status="error",
                error_code="stats.invalid_logs_window",
                message=str(error),
                data=filters,
                revision="m3",
            ),
        )

    return build_envelope(
        status="ok",
        message="logs analytics summary loaded",
        data=result,
        revision="m3",
    )


@router.get("/v1/logs/analytics/tool-latency")
async def get_logs_analytics_tool_latency(
    request: Request,
    filters: dict[str, Any] = Depends(_get_logs_analytics_filters),
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="stats:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    try:
        result = _get_usage_service(request).get_logs_analytics_tool_latency(
            site_id=auth.site_id,
            filters=filters,
        )
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                status="error",
                error_code="stats.invalid_logs_window",
                message=str(error),
                data=filters,
                revision="m3",
            ),
        )

    return build_envelope(
        status="ok",
        message="logs analytics tool latency loaded",
        data=result,
        revision="m3",
    )


@router.get("/v1/logs/analytics/mcp-zone")
async def get_logs_analytics_mcp_zone(
    request: Request,
    filters: dict[str, Any] = Depends(_get_logs_analytics_filters),
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="stats:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    try:
        result = _get_usage_service(request).get_logs_analytics_mcp_zone(
            site_id=auth.site_id,
            filters=filters,
        )
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                status="error",
                error_code="stats.invalid_logs_window",
                message=str(error),
                data=filters,
                revision="m3",
            ),
        )

    return build_envelope(
        status="ok",
        message="logs analytics mcp zone loaded",
        data=result,
        revision="m3",
    )


@router.get("/v1/logs/analytics/recommendations")
async def get_logs_analytics_recommendations(
    request: Request,
    filters: dict[str, Any] = Depends(_get_logs_analytics_filters),
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="stats:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    try:
        result = _get_usage_service(request).get_logs_analytics_recommendations(
            site_id=auth.site_id,
            filters=filters,
        )
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                status="error",
                error_code="stats.invalid_logs_window",
                message=str(error),
                data=filters,
                revision="m3",
            ),
        )

    return build_envelope(
        status="ok",
        message="logs analytics recommendations loaded",
        data=result,
        revision="m3",
    )


@router.get("/v1/alerts/provider-degradation")
async def get_alert_provider_degradation_projection(
    request: Request,
    window_minutes: int = Query(default=30, ge=5, le=1440),
    min_requests: int = Query(default=20, ge=1, le=100000),
    error_rate_threshold: float = Query(default=0.25, ge=0.01, le=1.0),
    latency_ms_threshold: int = Query(default=20000, ge=1, le=600000),
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="stats:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    result = _get_usage_rollup_service(request).get_alert_provider_degradation_batch(
        site_id=auth.site_id,
        window_minutes=window_minutes,
    )
    if result is None:
        result = _get_usage_service(request).get_alert_provider_degradation_projection(
            site_id=auth.site_id,
            window_minutes=window_minutes,
            min_requests=min_requests,
            error_rate_threshold=error_rate_threshold,
            latency_ms_threshold=latency_ms_threshold,
        )

    return build_envelope(
        status="ok",
        message="alert provider degradation projection loaded",
        data=result,
        revision="m3",
    )


@router.get("/v1/router/diagnostics")
@router.get("/v1/router/diagnostics-summary", include_in_schema=False)
async def get_router_diagnostics_projection(
    request: Request,
    config_revision: str = Query(default="", max_length=191),
    enabled_total: int = Query(default=0, ge=0, le=100000),
    tagless_enabled: bool = Query(default=False),
    high_risk_count: int = Query(default=0, ge=0, le=100000),
    has_warnings: bool = Query(default=False),
    recent_minutes: int = Query(default=60, ge=1, le=1440),
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="stats:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    rollup_service = _get_usage_rollup_service(request)
    usage_service = _get_usage_service(request)
    result = rollup_service.get_router_diagnostics_batch(
        site_id=auth.site_id,
        recent_minutes=recent_minutes,
    )
    if result is not None:
        result = dict(result)
        result["site_id"] = auth.site_id
        result["config_revision"] = config_revision
        report = dict(result.get("report") or {})
        validation = dict(report.get("validation") or {})
        validation["enabled_total"] = enabled_total
        validation["tagless_enabled"] = tagless_enabled
        validation["has_warnings"] = has_warnings
        report["validation"] = validation
        high_risk = dict(report.get("high_risk") or {})
        high_risk["count"] = high_risk_count
        report["high_risk"] = high_risk
        result["report"] = report
    else:
        result = usage_service.build_empty_router_diagnostics_projection(
            site_id=auth.site_id,
            config_revision=config_revision,
            enabled_total=enabled_total,
            tagless_enabled=tagless_enabled,
            high_risk_count=high_risk_count,
            has_warnings=has_warnings,
            recent_minutes=recent_minutes,
        )

    return build_envelope(
        status="ok",
        message="router diagnostics projection loaded",
        data=result,
        revision="m3",
    )
