from __future__ import annotations

import io
import logging

import pytest
from uvicorn.logging import AccessFormatter

from app.core import logging as logging_module
from app.core import redaction as redaction_module
from app.core.logging import RedactingFilter, configure_logging, get_logger
from app.core.redaction import redact_sensitive, redact_text


class _UnsafeObject:
    def __str__(self) -> str:
        raise AssertionError("unsafe __str__ must not be called")

    def __repr__(self) -> str:
        raise AssertionError("unsafe __repr__ must not be called")


def test_redact_sensitive_recurses_and_preserves_bounded_runtime_ids() -> None:
    value = {
        "trace_id": "trace_safe_001",
        "run_id": "run_safe_001",
        "site_id": "site_safe_001",
        "tokens_in": 42,
        "authorization": "Bearer secret-token-value",
        "nested": {
            "smtp_password": "smtp-secret",
            "prompt": "private user prompt",
            "result": {"output_text": "private model output"},
        },
        "items": [{"cookie": "session=private"}],
    }

    redacted = redact_sensitive(value)

    assert redacted == {
        "trace_id": "trace_safe_001",
        "run_id": "run_safe_001",
        "site_id": "site_safe_001",
        "tokens_in": 42,
        "authorization": "[redacted]",
        "nested": {
            "smtp_password": "[redacted]",
            "prompt": "[redacted]",
            "result": "[redacted]",
        },
        "items": [{"cookie": "[redacted]"}],
    }


def test_redact_text_covers_credentials_urls_controls_and_length() -> None:
    jwt_value = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwcml2YXRlIn0.signaturevalue"
    source = (
        "Authorization: Bearer bearer-secret\r\n"
        f"jwt={jwt_value}\n"
        "cookie: session=private-cookie\n"
        "database=postgresql://db-user:db-pass@db.internal:5432/cloud\n"
        "callback=https://user:pass@example.com/hook?sig=query-secret&page=2#private"
    )

    redacted = redact_text(source, max_chars=320)

    for secret in (
        "bearer-secret",
        jwt_value,
        "private-cookie",
        "db-user",
        "db-pass",
        "query-secret",
        "user:pass",
        "#private",
    ):
        assert secret not in redacted
    assert "Bearer [redacted]" in redacted
    assert "postgresql://[redacted]" in redacted
    assert "page=2" in redacted
    assert "\r" not in redacted
    assert "\n" not in redacted

    bounded = redact_text("x" * 500, max_chars=40)
    assert len(bounded) <= 40
    assert bounded.endswith("[truncated]")


def test_redact_sensitive_unknown_objects_fail_safe_without_repr() -> None:
    assert redact_sensitive(_UnsafeObject()) == "[redacted]"
    assert redact_sensitive({"safe": _UnsafeObject()}) == {"safe": "[redacted]"}


def test_redact_sensitive_normalizes_camel_dotted_env_and_plural_keys() -> None:
    redacted = redact_sensitive(
        {
            "accessToken": "opaque-access-value",
            "client.secret": "opaque-client-value",
            "JWT_SECRET": "opaque-jwt-value",
            "OPENAI_API_KEY": "opaque-provider-value",
            "database.url": "opaque-database-value",
            "setCookie": "opaque-cookie-value",
            "credentials": "opaque-credential-value",
        }
    )

    assert redacted == {
        "accessToken": "[redacted]",
        "client.secret": "[redacted]",
        "JWT_SECRET": "[redacted]",
        "OPENAI_API_KEY": "[redacted]",
        "database.url": "[redacted]",
        "setCookie": "[redacted]",
        "credentials": "[redacted]",
    }


def test_redact_text_scrubs_env_assignments_and_relative_url_credentials() -> None:
    source = (
        "OPENAI_API_KEY=provider-secret CLIENT_SECRET=client-secret "
        "callback=/auth/qq/callback?code=oauth-code&state=oauth-state&token=oauth-token"
        "&auth=oauth-auth&signature=query-signature&page=2"
    )

    redacted = redact_text(source)

    for secret in (
        "provider-secret",
        "client-secret",
        "oauth-code",
        "oauth-state",
        "oauth-token",
        "oauth-auth",
        "query-signature",
    ):
        assert secret not in redacted
    assert "page=2" in redacted


def test_redact_text_scrubs_semicolon_delimited_relative_query_credentials() -> None:
    redacted = redact_text("callback=/oauth/callback?page=2;token=semicolon-secret;mode=safe")

    assert "semicolon-secret" not in redacted
    assert "page=2" in redacted
    assert "token=[redacted]" in redacted
    assert "mode=safe" in redacted


def test_redact_text_scrubs_credentials_embedded_in_absolute_url_paths() -> None:
    source = (
        "download=https://cdn.example.com/presigned/s3cr3t-token/image.png"
        "?X-Amz-Signature=query-secret&page=2 "
        "callback=https://api.example.com/token/opaqueBearer1234567890/result"
    )

    redacted = redact_text(source)

    assert "s3cr3t-token" not in redacted
    assert "opaqueBearer1234567890" not in redacted
    assert "query-secret" not in redacted
    assert "/presigned/[redacted]/image.png" in redacted
    assert "/token/[redacted]/result" in redacted
    assert "page=2" in redacted


def test_redact_text_bounds_input_before_regex_scanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_lengths: list[int] = []
    original_url_pattern = redaction_module._URL_RE

    class _ObservedUrlPattern:
        def sub(self, replacement: object, value: str) -> str:
            observed_lengths.append(len(value))
            return original_url_pattern.sub(replacement, value)

    monkeypatch.setattr(redaction_module, "_URL_RE", _ObservedUrlPattern())

    redacted = redact_text("prefix " + ("x" * 100_000), max_chars=1_000_000)

    scan_limit = getattr(redaction_module, "MAX_TEXT_SCAN_CHARS", 16_384)
    assert observed_lengths == []
    assert len(redacted) <= scan_limit
    assert redacted.startswith("[redacted]")
    assert redacted.endswith("[truncated]")


def test_configure_logging_filters_existing_handler_idempotently() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        logging.Formatter("%(message)s trace=%(trace_id)s run=%(run_id)s result=%(result)s")
    )
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    logger = get_logger("tests.logging_redaction.existing_handler")
    original_level = logger.level
    logger.setLevel(logging.ERROR)

    try:
        configure_logging("INFO")
        configure_logging("INFO")
        assert sum(isinstance(item, RedactingFilter) for item in handler.filters) == 1

        try:
            raise RuntimeError("smtp_password=exception-secret")
        except RuntimeError:
            logger.exception(
                "request failed Authorization=Bearer positional-secret",
                extra={
                    "trace_id": "trace_safe_002",
                    "run_id": "run_safe_002",
                    "result": {"output_text": "private result"},
                },
            )
    finally:
        logger.setLevel(original_level)
        root_logger.removeHandler(handler)
        handler.close()

    output = stream.getvalue()
    for secret in (
        "exception-secret",
        "positional-secret",
        "private result",
    ):
        assert secret not in output
    assert "trace_safe_002" in output
    assert "run_safe_002" in output
    assert "exception_type=RuntimeError" in output
    assert "[redacted]" in output


def test_logging_filter_fails_safe_for_unsafe_positional_argument() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("tests.logging_redaction.unsafe_argument")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    original_filters = list(logger.filters)

    try:
        logger.addFilter(RedactingFilter())
        logger.info("unsafe=%s", _UnsafeObject())
    finally:
        logger.filters = original_filters
        logger.handlers = []
        handler.close()

    assert stream.getvalue().strip() == "unsafe=[redacted]"


def test_logging_filter_renders_after_redacting_format_arguments() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("tests.logging_redaction.format_arguments")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    original_filters = list(logger.filters)

    try:
        logger.addFilter(RedactingFilter())
        logger.info(
            "secret=%s site_id=%s callback=%s",
            "private-secret-value",
            "site_safe_003",
            "https://example.com/hook?signature=query-secret&attempt=2",
        )
    finally:
        logger.filters = original_filters
        logger.handlers = []
        handler.close()

    output = stream.getvalue().strip()
    assert "private-secret-value" not in output
    assert "query-secret" not in output
    assert "secret=[redacted]" in output
    assert "site_id=site_safe_003" in output
    assert "attempt=2" in output


def test_logging_filter_preserves_real_uvicorn_access_formatter_contract(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        AccessFormatter(
            fmt='%(client_addr)s - "%(request_line)s" %(status_code)s',
            use_colors=False,
        )
    )
    redacting_filter = RedactingFilter()
    handler.addFilter(redacting_filter)
    logger = logging.getLogger("uvicorn.access")
    original_handlers = list(logger.handlers)
    original_filters = list(logger.filters)
    original_level = logger.level
    original_propagate = logger.propagate
    logger.handlers = [handler]
    logger.filters = [redacting_filter]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    try:
        logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:1234",
            "GET",
            (
                "/auth/qq/callback?code=oauth-code&state=oauth-state&token=oauth-token"
                "&auth=oauth-auth&signature=query-signature&page=2"
            ),
            "1.1",
            200,
        )
    finally:
        logger.handlers = original_handlers
        logger.filters = original_filters
        logger.setLevel(original_level)
        logger.propagate = original_propagate
        handler.close()

    captured = capsys.readouterr()
    assert captured.err == ""
    output = stream.getvalue()
    for secret in (
        "oauth-code",
        "oauth-state",
        "oauth-token",
        "oauth-auth",
        "query-signature",
    ):
        assert secret not in output
    assert "page=2" in output
    assert "[redacted]" in output


def test_logging_filter_does_not_trust_nonstandard_uvicorn_access_template() -> None:
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="secret=%s safe=%s extra=%s other=%s status=%s",
        args=("private-value", "safe", "one", "two", 200),
        exc_info=None,
    )

    assert RedactingFilter().filter(record) is True
    assert record.args == ()
    assert record.getMessage() == ("secret=[redacted] safe=safe extra=one other=two status=200")


def test_logging_filter_scrubs_arbitrary_npcink_prefixed_extra() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s secret=%(_npcink_secret)s"))
    logger = logging.getLogger("tests.logging_redaction.npcink_extra")
    original_handlers = list(logger.handlers)
    original_filters = list(logger.filters)
    original_level = logger.level
    original_propagate = logger.propagate
    logger.handlers = [handler]
    logger.filters = [RedactingFilter()]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    try:
        logger.info("request complete", extra={"_npcink_secret": "opaque-internal-value"})
    finally:
        logger.handlers = original_handlers
        logger.filters = original_filters
        logger.setLevel(original_level)
        logger.propagate = original_propagate
        handler.close()

    output = stream.getvalue()
    assert "opaque-internal-value" not in output
    assert "secret=[redacted]" in output


def test_logging_filter_processes_a_propagated_record_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original_redact_text = logging_module.redact_text

    def counted_redact_text(value: str, *, max_chars: int = 4096) -> str:
        nonlocal calls
        calls += 1
        return original_redact_text(value, max_chars=max_chars)

    monkeypatch.setattr(logging_module, "redact_text", counted_redact_text)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    redacting_filter = RedactingFilter()
    handler.addFilter(redacting_filter)
    logger = logging.getLogger("tests.logging_redaction.single_pass")
    original_handlers = list(logger.handlers)
    original_filters = list(logger.filters)
    original_level = logger.level
    original_propagate = logger.propagate
    logger.handlers = [handler]
    logger.filters = [redacting_filter]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    try:
        logger.info("request complete")
    finally:
        logger.handlers = original_handlers
        logger.filters = original_filters
        logger.setLevel(original_level)
        logger.propagate = original_propagate
        handler.close()

    assert calls == 1
