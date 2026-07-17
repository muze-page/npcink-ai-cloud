from __future__ import annotations

import json
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.envelope import build_envelope
from app.core.config import Settings
from app.core.logging import get_logger
from app.core.security import extract_trace_id
from app.domain.portal_idempotency import (
    PortalIdempotencyClaim,
    PortalIdempotencyError,
    complete_portal_mutation,
)

PORTAL_IDEMPOTENCY_CLAIM_STATE_KEY = "portal_idempotency_claim"
logger = get_logger(__name__)


class PortalIdempotencyMiddleware:
    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        method = str(scope.get("method") or "").upper()
        path = str(scope.get("path") or "")
        if (
            scope["type"] != "http"
            or method not in {"POST", "PUT", "PATCH", "DELETE"}
            or not path.startswith("/portal/v1/")
        ):
            await self.app(scope, receive, send)
            return

        messages: list[Message] = []
        captured_response_body_bytes = 0
        response_body_too_large = False
        capturing_idempotent_response: bool | None = None

        async def capture_send(message: Message) -> None:
            nonlocal captured_response_body_bytes
            nonlocal capturing_idempotent_response
            nonlocal response_body_too_large
            if capturing_idempotent_response is None:
                state = scope.get("state")
                claim = (
                    state.get(PORTAL_IDEMPOTENCY_CLAIM_STATE_KEY)
                    if isinstance(state, dict)
                    else None
                )
                capturing_idempotent_response = isinstance(
                    claim,
                    PortalIdempotencyClaim,
                )
            if not capturing_idempotent_response:
                await send(message)
                return
            if message["type"] == "http.response.body":
                response_chunk = bytes(message.get("body", b""))
                captured_response_body_bytes += len(response_chunk)
                if (
                    response_body_too_large
                    or captured_response_body_bytes
                    > self.settings.portal_idempotency_max_response_bytes
                ):
                    response_body_too_large = True
                    return
            messages.append(message)

        await self.app(scope, receive, capture_send)

        if not capturing_idempotent_response:
            return

        state = scope.get("state")
        claim = state.get(PORTAL_IDEMPOTENCY_CLAIM_STATE_KEY) if isinstance(state, dict) else None
        if not isinstance(claim, PortalIdempotencyClaim):
            await _send_messages(messages, send)
            return

        start = next(
            (message for message in messages if message["type"] == "http.response.start"),
            None,
        )
        if start is None:
            await self._send_persistence_error(
                scope,
                send,
                error_code="portal.idempotency_response_invalid",
            )
            return

        response_bytes = b"".join(
            bytes(message.get("body", b""))
            for message in messages
            if message["type"] == "http.response.body"
        )
        response_status = int(start.get("status", 500))
        response_body = _bounded_json_response(
            response_bytes,
            max_response_bytes=self.settings.portal_idempotency_max_response_bytes,
            size_limit_exceeded=response_body_too_large,
        )
        if isinstance(response_body, PortalIdempotencyError):
            fallback = _error_envelope(scope, error_code=response_body.error_code)
            fallback_response = JSONResponse(status_code=500, content=fallback)
            try:
                complete_portal_mutation(
                    database_url=self.settings.database_url,
                    claim=claim,
                    response_status=500,
                    response_body_bytes=fallback_response.body,
                    max_response_bytes=self.settings.portal_idempotency_max_response_bytes,
                    settings=self.settings,
                )
            except Exception:
                logger.exception(
                    "failed to persist bounded Portal idempotency error response",
                    extra={"receipt_id": claim.receipt_id},
                )
                await self._send_persistence_error(
                    scope,
                    send,
                    error_code="portal.idempotency_persist_failed",
                )
                return
            await fallback_response(scope, receive, send)
            return

        try:
            complete_portal_mutation(
                database_url=self.settings.database_url,
                claim=claim,
                response_status=response_status,
                response_body_bytes=response_bytes,
                max_response_bytes=self.settings.portal_idempotency_max_response_bytes,
                settings=self.settings,
            )
        except Exception:
            logger.exception(
                "failed to persist Portal idempotency response",
                extra={"receipt_id": claim.receipt_id},
            )
            await self._send_persistence_error(
                scope,
                send,
                error_code="portal.idempotency_persist_failed",
            )
            return

        await _send_messages(messages, send)

    async def _send_persistence_error(
        self,
        scope: Scope,
        send: Send,
        *,
        error_code: str,
    ) -> None:
        response = JSONResponse(
            status_code=503,
            content=_error_envelope(scope, error_code=error_code),
        )

        async def empty_receive() -> Message:
            return {"type": "http.request", "body": b"", "more_body": False}

        await response(scope, empty_receive, send)


def _bounded_json_response(
    response_bytes: bytes,
    *,
    max_response_bytes: int,
    size_limit_exceeded: bool = False,
) -> Any | PortalIdempotencyError:
    if size_limit_exceeded or len(response_bytes) > int(max_response_bytes):
        return PortalIdempotencyError(
            500,
            "portal.idempotency_response_too_large",
            "Portal mutation response exceeds the idempotency storage limit",
        )
    if not response_bytes:
        return PortalIdempotencyError(
            500,
            "portal.idempotency_response_invalid",
            "Portal mutation response must be bounded JSON",
        )
    try:
        return json.loads(response_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return PortalIdempotencyError(
            500,
            "portal.idempotency_response_invalid",
            "Portal mutation response must be bounded JSON",
        )


def _error_envelope(scope: Scope, *, error_code: str) -> dict[str, object]:
    headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }
    return build_envelope(
        status="error",
        error_code=error_code,
        message="portal request could not be recorded safely",
        trace_id=extract_trace_id(headers.get("traceparent", "")),
        revision="m7",
    )


async def _send_messages(messages: list[Message], send: Send) -> None:
    for message in messages:
        await send(message)
