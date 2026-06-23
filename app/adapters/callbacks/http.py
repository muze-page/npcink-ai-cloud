from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from app.adapters.callbacks.base import (
    RuntimeCallbackDispatchError,
    RuntimeCallbackDispatchRequest,
    RuntimeCallbackDispatchResult,
)
from app.core.callback_security import (
    RuntimeCallbackTargetValidationError,
    validate_runtime_callback_target,
)
from app.core.security import build_hmac_signature, build_secret_hash


class HttpRuntimeCallbackDispatcher:
    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self._client = client
        self._owns_client = client is None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.timeout_seconds,
                transport=self.transport,
                follow_redirects=False,
            )
        return self._client

    def dispatch(
        self,
        request: RuntimeCallbackDispatchRequest,
    ) -> RuntimeCallbackDispatchResult:
        try:
            validate_runtime_callback_target(request.callback_url)
        except RuntimeCallbackTargetValidationError as error:
            raise RuntimeCallbackDispatchError(
                "runtime.callback_target_invalid",
                str(error),
                retryable=False,
            ) from error
        body = json.dumps(
            request.payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        headers = self._build_headers(request, body=body)
        try:
            response = self._get_client().post(
                request.callback_url,
                content=body,
                headers=headers,
            )
        except httpx.TimeoutException as error:
            raise RuntimeCallbackDispatchError(
                "runtime.callback_timeout",
                f"callback delivery timed out: {error}",
                retryable=True,
            ) from error
        except httpx.HTTPError as error:
            raise RuntimeCallbackDispatchError(
                "runtime.callback_transport_error",
                f"callback delivery transport error: {error}",
                retryable=True,
            ) from error

        if 200 <= response.status_code < 300:
            return RuntimeCallbackDispatchResult(status_code=response.status_code)

        raise RuntimeCallbackDispatchError(
            "runtime.callback_delivery_failed",
            f"callback endpoint returned HTTP {response.status_code}",
            retryable=response.status_code >= 500 or response.status_code in {408, 409, 429},
            status_code=response.status_code,
        )

    def close(self) -> None:
        if self._client is None or not self._owns_client:
            return
        self._client.close()
        self._client = None

    def _build_headers(
        self,
        request: RuntimeCallbackDispatchRequest,
        *,
        body: bytes,
    ) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "X-Npcink-Cloud-Event": request.event,
            "X-Npcink-Run-Id": request.run_id,
            "X-Npcink-Trace-Id": request.trace_id,
        }
        if not request.key_id or not request.secret:
            return headers

        timestamp = request.timestamp or str(int(datetime.now(UTC).timestamp()))
        traceparent = request.traceparent or self._build_traceparent(request.trace_id)
        callback_id = request.callback_id or request.run_id
        canonical = self._build_callback_canonical(
            callback_url=request.callback_url,
            site_id=request.site_id,
            key_id=request.key_id,
            timestamp=timestamp,
            event=request.event,
            callback_id=callback_id,
            traceparent=traceparent,
            body=body,
        )
        headers.update(
            {
                "X-Npcink-Site-Id": request.site_id,
                "X-Npcink-Key-Id": request.key_id,
                "X-Npcink-Timestamp": timestamp,
                "X-Npcink-Signature": build_hmac_signature(
                    build_secret_hash(request.secret),
                    canonical,
                ),
                "X-Npcink-Callback-Id": callback_id,
                "traceparent": traceparent,
            }
        )
        return headers

    def _build_callback_canonical(
        self,
        *,
        callback_url: str,
        site_id: str,
        key_id: str,
        timestamp: str,
        event: str,
        callback_id: str,
        traceparent: str,
        body: bytes,
    ) -> str:
        parsed = urlsplit(callback_url)
        path = parsed.path or "/"
        route = path if not parsed.query else f"{path}?{parsed.query}"
        return "\n".join(
            [
                "POST",
                route,
                site_id,
                key_id,
                timestamp,
                event,
                callback_id,
                traceparent,
                hashlib.sha256(body).hexdigest(),
            ]
        )

    def _build_traceparent(self, trace_id: str) -> str:
        normalized = str(trace_id or "").lower().replace("-", "")
        normalized = normalized.ljust(32, "0")[:32]
        parent_id = hashlib.sha256(f"{normalized}|runtime-callback".encode()).hexdigest()[:16]
        return f"00-{normalized}-{parent_id}-01"
