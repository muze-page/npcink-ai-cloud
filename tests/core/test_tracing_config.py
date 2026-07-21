from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_tracing_urls_are_disabled_by_default_and_normalize_blank_values() -> None:
    settings = Settings(
        _env_file=None,
        otel_exporter_otlp_endpoint="  ",
        otel_trace_query_url="",
    )

    assert settings.otel_exporter_otlp_endpoint is None
    assert settings.otel_trace_query_url is None


def test_tracing_urls_accept_explicit_http_endpoints() -> None:
    settings = Settings(
        _env_file=None,
        otel_exporter_otlp_endpoint="https://collector.example:4318/v1/traces",
        otel_trace_query_url="http://traces.example:16686/search",
    )

    assert settings.otel_exporter_otlp_endpoint == (
        "https://collector.example:4318/v1/traces"
    )
    assert settings.otel_trace_query_url == "http://traces.example:16686/search"


@pytest.mark.parametrize(
    ("field_name", "value", "error_message"),
    [
        ("otel_exporter_otlp_endpoint", "grpc://collector.example:4317", "must use http"),
        ("otel_exporter_otlp_endpoint", "http:///v1/traces", "must include a valid host"),
        ("otel_exporter_otlp_endpoint", "http://user@collector.example/v1/traces", "userinfo"),
        ("otel_exporter_otlp_endpoint", "http://collector.example/v1/traces?tenant=x", "query"),
        ("otel_exporter_otlp_endpoint", "http://collector.example/v1/tra ces", "whitespace"),
        ("otel_trace_query_url", "https://traces.example/search#recent", "fragment"),
        ("otel_trace_query_url", "https://traces.example:invalid", "valid HTTP"),
    ],
)
def test_tracing_urls_reject_unsafe_or_malformed_values(
    field_name: str,
    value: str,
    error_message: str,
) -> None:
    with pytest.raises(ValidationError, match=error_message):
        Settings(_env_file=None, **{field_name: value})
