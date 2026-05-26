from __future__ import annotations

import socket

import httpx
import pytest

from app.adapters.callbacks.base import RuntimeCallbackDispatchError
from app.adapters.callbacks.base import RuntimeCallbackDispatchRequest
from app.adapters.callbacks.http import HttpRuntimeCallbackDispatcher
from app.core.callback_security import (
    RuntimeCallbackTargetValidationError,
    validate_runtime_callback_target,
)


def test_callback_target_requires_https() -> None:
    with pytest.raises(RuntimeCallbackTargetValidationError):
        validate_runtime_callback_target("http://callbacks.magick.test/runtime")


def test_callback_target_rejects_private_ip_literal() -> None:
    with pytest.raises(RuntimeCallbackTargetValidationError):
        validate_runtime_callback_target("https://127.0.0.1/runtime")


def test_callback_target_rejects_domain_resolving_to_private_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.8", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(RuntimeCallbackTargetValidationError):
        validate_runtime_callback_target("https://callbacks.magick.test/runtime")


def test_http_callback_dispatcher_rejects_invalid_target_before_dispatch() -> None:
    dispatcher = HttpRuntimeCallbackDispatcher(
        transport=httpx.MockTransport(lambda request: httpx.Response(204)),
    )

    with pytest.raises(RuntimeCallbackDispatchError) as error:
        dispatcher.dispatch(
            RuntimeCallbackDispatchRequest(
                callback_url="http://callbacks.magick.test/runtime",
                event="runtime.run.terminal",
                run_id="run_test",
                trace_id="trace-test",
                site_id="site_test",
                payload={"status": "succeeded"},
                key_id="",
                secret="",
            )
        )

    assert error.value.error_code == "runtime.callback_target_invalid"
    assert "callback_url must use https" in str(error.value)
