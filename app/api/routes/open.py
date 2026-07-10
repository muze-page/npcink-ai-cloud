from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse

from app.api.auth import get_cloud_services
from app.api.envelope import build_envelope
from app.api.routes.portal import finish_qq_login_callback
from app.api.routes.service import _get_commercial_service
from app.domain.commercial.errors import CommercialServiceError
from app.domain.service_settings import resolve_alipay_payment_runtime_config

router = APIRouter(prefix="/open", tags=["open"])


def _not_enabled(
    *,
    error_code: str,
    message: str,
    data: dict[str, Any],
) -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content=build_envelope(
            status="error",
            error_code=error_code,
            message=message,
            data={
                **data,
                "mutation_applied": False,
                "credential_value_exposure": "none",
            },
            revision="m7",
        ),
    )


@router.get("/auth/qq/callback")
async def finish_open_qq_login(
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
) -> Any:
    return await finish_qq_login_callback(request, code=code, state=state)


@router.get("/auth/wechat/callback")
async def finish_open_wechat_login(
    code: str = Query(default=""),
    state: str = Query(default=""),
) -> Any:
    return _not_enabled(
        error_code="open.wechat_login_not_enabled",
        message="WeChat login callback is reserved but not enabled",
        data={
            "surface": "open_auth_callback",
            "provider": "wechat",
            "callback_kind": "oauth_login",
            "code_received": bool(str(code or "").strip()),
            "state_received": bool(str(state or "").strip()),
        },
    )


@router.post("/payments/alipay/notify")
async def receive_open_alipay_payment_notify(request: Request) -> Any:
    services = get_cloud_services(request)
    alipay_config = resolve_alipay_payment_runtime_config(
        services.settings.database_url,
        services.settings,
    )
    if not alipay_config.get("configured"):
        return _not_enabled(
            error_code="open.alipay_payment_notify_not_enabled",
            message="Alipay payment notify callback is reserved but not enabled",
            data={
                "surface": "open_payment_notify",
                "provider": "alipay",
                "callback_kind": "payment_notify",
            },
        )
    form = await request.form()
    raw_event: dict[str, object] = {str(key): str(value) for key, value in form.multi_items()}
    if not raw_event:
        raw_event = {str(key): str(value) for key, value in request.query_params.items()}
    try:
        result = _get_commercial_service(request).process_payment_gateway_callback(
            provider="alipay",
            raw_event=raw_event,
        )
    except CommercialServiceError:
        return PlainTextResponse("fail", status_code=400)
    if result.get("status") != "succeeded":
        return PlainTextResponse("success")
    return PlainTextResponse("success")


@router.get("/payments/alipay/return")
async def receive_open_alipay_payment_return(request: Request) -> Any:
    services = get_cloud_services(request)
    alipay_config = resolve_alipay_payment_runtime_config(
        services.settings.database_url,
        services.settings,
    )
    if not alipay_config.get("configured"):
        return _not_enabled(
            error_code="open.alipay_payment_return_not_enabled",
            message="Alipay payment return callback is reserved but not enabled",
            data={
                "surface": "open_payment_return",
                "provider": "alipay",
                "callback_kind": "payment_return",
            },
        )
    query = {
        "payment_return": "alipay",
        "out_trade_no": str(request.query_params.get("out_trade_no") or ""),
        "trade_status": str(request.query_params.get("trade_status") or ""),
    }
    target = f"/portal/billing?{urlencode({key: value for key, value in query.items() if value})}"
    return RedirectResponse(target, status_code=303)


@router.post("/payments/wechat/notify")
async def receive_open_wechat_payment_notify() -> Any:
    return _not_enabled(
        error_code="open.wechat_payment_notify_not_enabled",
        message="WeChat Pay notify callback is reserved but not enabled",
        data={
            "surface": "open_payment_notify",
            "provider": "wechat_pay",
            "callback_kind": "payment_notify",
        },
    )
