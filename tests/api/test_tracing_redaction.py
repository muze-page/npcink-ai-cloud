from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.api import main as main_module


class _CapturedSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}
        self.events: list[tuple[str, dict[str, object]]] = []
        self.statuses: list[object] = []

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value

    def add_event(
        self,
        name: str,
        attributes: dict[str, object] | None = None,
    ) -> None:
        self.events.append((name, dict(attributes or {})))

    def set_status(self, status: object) -> None:
        self.statuses.append(status)

    def record_exception(self, exception: BaseException, **kwargs: object) -> None:
        raise AssertionError("raw exceptions must not be recorded in tracing")


class _CapturedTracer:
    def __init__(self, span: _CapturedSpan) -> None:
        self.span = span
        self.start_kwargs: dict[str, object] = {}

    @contextmanager
    def start_as_current_span(self, *args: object, **kwargs: object) -> Iterator[_CapturedSpan]:
        self.start_kwargs = dict(kwargs)
        yield self.span


def test_http_trace_records_only_stable_exception_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    span = _CapturedSpan()
    tracer = _CapturedTracer(span)
    monkeypatch.setattr(
        main_module.trace,
        "get_tracer",
        lambda _name: tracer,
    )
    app = main_module.create_app()
    secret = "Bearer tracing-secret-value"

    @app.get("/__test__/tracing-redaction")
    async def tracing_failure() -> None:
        raise RuntimeError(secret)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/__test__/tracing-redaction")

    assert response.status_code == 500
    assert span.events == [
        (
            "exception",
            {"exception.type": "RuntimeError"},
        )
    ]
    assert tracer.start_kwargs["record_exception"] is False
    assert tracer.start_kwargs["set_status_on_exception"] is False
    observed = f"{span.attributes!r} {span.events!r} {span.statuses!r}"
    assert secret not in observed
