from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from app.api.envelope import build_envelope
from app.core.security import extract_trace_id
from app.setup.errors import SetupError
from app.setup.models import DatabaseInput, InstallInput, SetupCodeInput
from app.setup.security import (
    SETUP_COOKIE_NAME,
    SETUP_SESSION_TTL_SECONDS,
    resolve_setup_source_ip,
)
from app.setup.service import SetupService

router = APIRouter(prefix="/setup/v1", tags=["setup"])
_MAX_SETUP_BODY_BYTES = 300 * 1024


def _service(request: Request) -> SetupService:
    service = getattr(request.app.state, "setup_service", None)
    if not isinstance(service, SetupService):
        raise SetupError(404, "setup.already_complete", "setup is no longer available")
    return service


def _no_store(response: JSONResponse) -> JSONResponse:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


def _error_response(request: Request, error: SetupError) -> JSONResponse:
    return _no_store(JSONResponse(
        status_code=error.status_code,
        content=build_envelope(
            status="error",
            error_code=error.error_code,
            message=error.message,
            trace_id=extract_trace_id(request.headers.get("traceparent", "")),
            revision="first-install-v1",
        ),
    ))


async def _validated_body[Model: BaseModel](
    request: Request,
    model: type[Model],
) -> Model:
    content_type = str(request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise SetupError(400, "setup.request_invalid", "setup request must use JSON")
    raw = await request.body()
    if len(raw) > _MAX_SETUP_BODY_BYTES:
        raise SetupError(413, "setup.request_invalid", "setup request is too large")
    try:
        payload = json.loads(raw)
        return model.model_validate(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        raise SetupError(422, "setup.request_invalid", "setup request is invalid") from error


def _setup_cookie(request: Request) -> str:
    return str(request.cookies.get(SETUP_COOKIE_NAME) or "").strip()


@router.get("/state")
async def setup_state(request: Request) -> JSONResponse:
    try:
        state = _service(request).state()
        return _no_store(JSONResponse(
            status_code=200,
            content=build_envelope(
                status="ok",
                message="installation state loaded",
                data=state.public_payload(),
                revision="first-install-v1",
            ),
        ))
    except SetupError as error:
        return _error_response(request, error)


@router.post("/session")
async def setup_session(request: Request) -> JSONResponse:
    try:
        payload = await _validated_body(request, SetupCodeInput)
        token = _service(request).create_session(
            setup_code=payload.setup_code.get_secret_value(),
            source_ip=resolve_setup_source_ip(request),
        )
        state = _service(request).state()
        response = _no_store(JSONResponse(
            status_code=200,
            content=build_envelope(
                status="ok",
                message="setup session created",
                data={
                    **state.public_payload(),
                    "expires_in_seconds": SETUP_SESSION_TTL_SECONDS,
                },
                revision="first-install-v1",
            ),
        ))
        response.set_cookie(
            SETUP_COOKIE_NAME,
            token,
            httponly=True,
            secure=True,
            samesite="strict",
            path="/",
            max_age=SETUP_SESSION_TTL_SECONDS,
        )
        return response
    except SetupError as error:
        return _error_response(request, error)


@router.post("/database/test")
async def setup_database_test(request: Request) -> JSONResponse:
    try:
        service = _service(request)
        service.require_session(_setup_cookie(request))
        payload = await _validated_body(request, DatabaseInput)
        result = await asyncio.to_thread(service.test_database, payload)
        return _no_store(JSONResponse(
            status_code=200,
            content=build_envelope(
                status="ok",
                message="database validation passed",
                data=result.public_payload(),
                revision="first-install-v1",
            ),
        ))
    except SetupError as error:
        return _error_response(request, error)


@router.post("/install")
async def setup_install(request: Request) -> JSONResponse:
    try:
        service = _service(request)
        service.require_session(_setup_cookie(request))
        payload = await _validated_body(request, InstallInput)
        result = await asyncio.to_thread(
            service.install,
            payload,
            idempotency_key=str(request.headers.get("idempotency-key") or "").strip(),
        )
        response = _no_store(JSONResponse(
            status_code=200,
            content=build_envelope(
                status="ok",
                message="installation completed",
                data=result,
                revision="first-install-v1",
            ),
        ))
        response.delete_cookie(
            SETUP_COOKIE_NAME,
            path="/",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return response
    except SetupError as error:
        return _error_response(request, error)
