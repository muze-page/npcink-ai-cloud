from __future__ import annotations

import io
import logging
import threading
import time
from collections.abc import Iterator

import httpx
import pytest

from app.core.logging import configure_logging
from app.domain.image_generation import provider_fetch as provider_fetch_module
from app.domain.image_generation.provider_fetch import (
    ProviderFetchedImage,
    ProviderImageFetchError,
    fetch_provider_image_url,
)

_PUBLIC_ADDRESS = "93.184.216.34"


def _public_resolver(hostname: str, port: int) -> tuple[str, ...]:
    assert hostname == "images.provider.test"
    assert port == 443
    return (_PUBLIC_ADDRESS,)


def test_fetch_pins_approved_address_and_preserves_host_and_sni() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["host"] = request.headers["host"]
        captured["sni"] = request.extensions["sni_hostname"]
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=b"provider-image",
        )

    fetched = fetch_provider_image_url(
        "https://images.provider.test/generated/image.png?variant=1",
        allowed_hosts=("images.provider.test",),
        resolver=_public_resolver,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert fetched.stream.read() == b"provider-image"
        assert fetched.byte_size == len(b"provider-image")
        assert fetched.declared_mime_type == "image/png"
    finally:
        fetched.close()

    assert captured == {
        "url": f"https://{_PUBLIC_ADDRESS}/generated/image.png?variant=1",
        "host": "images.provider.test",
        "sni": "images.provider.test",
    }


def test_fetch_never_logs_signed_provider_url_at_application_info_level(
    caplog: pytest.LogCaptureFixture,
) -> None:
    source_url = (
        "https://images.provider.test/generated/image.png"
        "?sig=TOPSECRET&token=ABC"
    )
    dependency_loggers = [logging.getLogger(name) for name in ("httpx", "httpcore")]
    original_levels = [logger.level for logger in dependency_loggers]
    try:
        configure_logging("INFO")
        caplog.set_level(logging.INFO)
        fetched = fetch_provider_image_url(
            source_url,
            allowed_hosts=("images.provider.test",),
            resolver=_public_resolver,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    headers={"content-type": "image/png"},
                    content=b"provider-image",
                )
            ),
        )
        fetched.close()
    finally:
        for logger, original_level in zip(dependency_loggers, original_levels, strict=True):
            logger.setLevel(original_level)

    assert "TOPSECRET" not in caplog.text
    assert "token=ABC" not in caplog.text
    assert source_url not in caplog.text


@pytest.mark.parametrize(
    "source_url",
    [
        "http://images.provider.test/image.png",
        "https://user:secret@images.provider.test/image.png",
        "https://images.provider.test:444/image.png",
        "https://images.provider.test/image.png#fragment",
        "https://sub.images.provider.test/image.png",
    ],
)
def test_fetch_rejects_unsafe_or_non_allowlisted_urls(source_url: str) -> None:
    with pytest.raises(ProviderImageFetchError):
        fetch_provider_image_url(
            source_url,
            allowed_hosts=("images.provider.test",),
            resolver=_public_resolver,
            transport=httpx.MockTransport(lambda request: httpx.Response(200)),
        )


@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        ("10.0.0.2",),
        ("169.254.169.254",),
        ("::1",),
        (_PUBLIC_ADDRESS, "192.168.1.1"),
        ("192.0.2.10",),
    ],
)
def test_fetch_rejects_any_non_public_dns_answer(addresses: tuple[str, ...]) -> None:
    with pytest.raises(ProviderImageFetchError) as error:
        fetch_provider_image_url(
            "https://images.provider.test/image.png",
            allowed_hosts=("images.provider.test",),
            resolver=lambda hostname, port: addresses,
            transport=httpx.MockTransport(lambda request: httpx.Response(200)),
        )
    assert error.value.message == "provider image host is not publicly routable"


def test_fetch_rejects_redirects_and_streams_with_authoritative_limit() -> None:
    redirect_transport = httpx.MockTransport(
        lambda request: httpx.Response(
            302,
            headers={"location": "https://images.provider.test/other.png"},
        )
    )
    with pytest.raises(ProviderImageFetchError) as redirect_error:
        fetch_provider_image_url(
            "https://images.provider.test/image.png",
            allowed_hosts=("images.provider.test",),
            resolver=_public_resolver,
            transport=redirect_transport,
        )
    assert redirect_error.value.message == "provider image redirects are forbidden"

    class ChunkedStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield b"1234"
            yield b"5678"

    oversize_transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/octet-stream"},
            stream=ChunkedStream(),
        )
    )
    with pytest.raises(ProviderImageFetchError) as size_error:
        fetch_provider_image_url(
            "https://images.provider.test/image.png",
            allowed_hosts=("images.provider.test",),
            resolver=_public_resolver,
            transport=oversize_transport,
            max_bytes=7,
        )
    assert size_error.value.message == "provider image exceeds the byte limit"


def test_fetch_enforces_total_wall_clock_budget_during_streaming() -> None:
    class ChunkedStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield b"first"
            yield b"second"

    ticks = iter((0.0, 0.0, 0.0, 0.0, 1.5, 2.1, 2.1))
    with pytest.raises(ProviderImageFetchError) as error:
        fetch_provider_image_url(
            "https://images.provider.test/image.png",
            allowed_hosts=("images.provider.test",),
            resolver=_public_resolver,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, stream=ChunkedStream())
            ),
            timeout_seconds=2.0,
            clock=lambda: next(ticks),
        )
    assert error.value.message == "provider image download exceeded the time limit"


def test_fetch_hard_deadline_includes_slow_dns_and_cancels_before_http() -> None:
    resolver_started = threading.Event()
    resolver_release = threading.Event()
    resolver_finished = threading.Event()
    transport_called = threading.Event()

    def slow_resolver(hostname: str, port: int) -> tuple[str, ...]:
        assert hostname == "images.provider.test"
        assert port == 443
        resolver_started.set()
        try:
            assert resolver_release.wait(1.0)
            return (_PUBLIC_ADDRESS,)
        finally:
            resolver_finished.set()

    def handler(request: httpx.Request) -> httpx.Response:
        transport_called.set()
        return httpx.Response(200, content=b"too-late")

    started_at = time.monotonic()
    try:
        with pytest.raises(ProviderImageFetchError) as error:
            fetch_provider_image_url(
                "https://images.provider.test/image.png",
                allowed_hosts=("images.provider.test",),
                resolver=slow_resolver,
                transport=httpx.MockTransport(handler),
                timeout_seconds=0.05,
            )
        elapsed = time.monotonic() - started_at
        assert error.value.message == "provider image download exceeded the time limit"
        assert resolver_started.is_set()
        assert elapsed < 0.3
    finally:
        resolver_release.set()

    assert resolver_finished.wait(1.0)
    assert not transport_called.wait(0.05)


def test_fetch_hard_deadline_includes_slow_response_headers_and_closes_late_response() -> None:
    handler_started = threading.Event()
    handler_release = threading.Event()
    response_closed = threading.Event()

    class CloseTrackingStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield b"too-late"

        def close(self) -> None:
            response_closed.set()

    def slow_handler(request: httpx.Request) -> httpx.Response:
        handler_started.set()
        assert handler_release.wait(1.0)
        return httpx.Response(200, stream=CloseTrackingStream())

    started_at = time.monotonic()
    try:
        with pytest.raises(ProviderImageFetchError) as error:
            fetch_provider_image_url(
                "https://images.provider.test/image.png",
                allowed_hosts=("images.provider.test",),
                resolver=_public_resolver,
                transport=httpx.MockTransport(slow_handler),
                timeout_seconds=0.05,
            )
        elapsed = time.monotonic() - started_at
        assert error.value.message == "provider image download exceeded the time limit"
        assert handler_started.is_set()
        assert elapsed < 0.3
    finally:
        handler_release.set()

    assert response_closed.wait(1.0)


def test_fetch_hard_deadline_is_cumulative_across_stream_reads_and_closes_spool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream_closed = threading.Event()
    spool_created = threading.Event()
    spool_closed = threading.Event()

    class CloseTrackingSpool(io.BytesIO):
        def close(self) -> None:
            spool_closed.set()
            super().close()

    spool = CloseTrackingSpool()

    class SlowChunkedStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            for _ in range(10):
                time.sleep(0.02)
                yield b"chunk"

        def close(self) -> None:
            stream_closed.set()

    def temporary_file(*, mode: str) -> io.BytesIO:
        assert mode == "w+b"
        spool_created.set()
        return spool

    monkeypatch.setattr(provider_fetch_module.tempfile, "TemporaryFile", temporary_file)

    started_at = time.monotonic()
    with pytest.raises(ProviderImageFetchError) as error:
        fetch_provider_image_url(
            "https://images.provider.test/image.png",
            allowed_hosts=("images.provider.test",),
            resolver=_public_resolver,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, stream=SlowChunkedStream())
            ),
            timeout_seconds=0.1,
        )
    elapsed = time.monotonic() - started_at

    assert error.value.message == "provider image download exceeded the time limit"
    assert spool_created.is_set()
    assert elapsed < 0.4
    assert stream_closed.wait(1.0)
    assert spool_closed.wait(1.0)
    assert spool.closed


def test_fetch_closes_a_successful_result_published_after_caller_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_started = threading.Event()
    worker_release = threading.Event()
    result_closed = threading.Event()

    class CloseTrackingSpool(io.BytesIO):
        def close(self) -> None:
            result_closed.set()
            super().close()

    def delayed_success(*args: object, **kwargs: object) -> ProviderFetchedImage:
        worker_started.set()
        assert worker_release.wait(1.0)
        return ProviderFetchedImage(
            stream=CloseTrackingSpool(b"late-success"),
            byte_size=len(b"late-success"),
            declared_mime_type="image/png",
        )

    monkeypatch.setattr(
        provider_fetch_module,
        "_fetch_provider_image_url_sync",
        delayed_success,
    )

    try:
        with pytest.raises(ProviderImageFetchError) as error:
            fetch_provider_image_url(
                "https://images.provider.test/image.png",
                allowed_hosts=("images.provider.test",),
                resolver=_public_resolver,
                transport=httpx.MockTransport(lambda request: httpx.Response(200)),
                timeout_seconds=0.05,
            )
        assert error.value.message == "provider image download exceeded the time limit"
        assert worker_started.is_set()
    finally:
        worker_release.set()

    assert result_closed.wait(1.0)


def test_job_discards_result_published_after_wait_deadline_before_caller_lock() -> None:
    result_closed = threading.Event()

    class CloseTrackingSpool(io.BytesIO):
        def close(self) -> None:
            result_closed.set()
            super().close()

    job = provider_fetch_module._ProviderImageFetchJob()
    hard_deadline = time.monotonic() + 1.0
    job.publish_result(
        ProviderFetchedImage(
            stream=CloseTrackingSpool(b"lost-deadline-race"),
            byte_size=len(b"lost-deadline-race"),
            declared_mime_type="image/png",
        )
    )

    with pytest.raises(ProviderImageFetchError) as error:
        job.take_result_before(
            hard_deadline,
            completed_before_wait_timeout=False,
        )

    assert error.value.message == "provider image download exceeded the time limit"
    assert result_closed.is_set()


def test_job_discards_early_result_when_caller_resumes_after_hard_deadline() -> None:
    result_closed = threading.Event()

    class CloseTrackingSpool(io.BytesIO):
        def close(self) -> None:
            result_closed.set()
            super().close()

    job = provider_fetch_module._ProviderImageFetchJob()
    hard_deadline = time.monotonic() + 0.02
    job.publish_result(
        ProviderFetchedImage(
            stream=CloseTrackingSpool(b"finished-before-deadline"),
            byte_size=len(b"finished-before-deadline"),
            declared_mime_type="image/png",
        )
    )
    assert job.done.is_set()
    time.sleep(0.03)

    with pytest.raises(ProviderImageFetchError) as error:
        job.take_result_before(
            hard_deadline,
            completed_before_wait_timeout=True,
        )

    assert error.value.message == "provider image download exceeded the time limit"
    assert result_closed.is_set()


def test_fetch_rejects_immediately_when_bounded_worker_capacity_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saturated_slots = threading.BoundedSemaphore(0)
    resolver_called = threading.Event()

    def resolver(hostname: str, port: int) -> tuple[str, ...]:
        resolver_called.set()
        return (_PUBLIC_ADDRESS,)

    monkeypatch.setattr(
        provider_fetch_module,
        "_PROVIDER_IMAGE_FETCH_SLOTS",
        saturated_slots,
    )

    started_at = time.monotonic()
    with pytest.raises(ProviderImageFetchError) as error:
        fetch_provider_image_url(
            "https://images.provider.test/image.png",
            allowed_hosts=("images.provider.test",),
            resolver=resolver,
            transport=httpx.MockTransport(lambda request: httpx.Response(200)),
            timeout_seconds=0.1,
        )
    elapsed = time.monotonic() - started_at

    assert error.value.message == "provider image fetch capacity is exhausted"
    assert elapsed < 0.05
    assert not resolver_called.is_set()
