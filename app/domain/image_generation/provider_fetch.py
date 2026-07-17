from __future__ import annotations

import ipaddress
import math
import socket
import tempfile
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import BinaryIO
from urllib.parse import SplitResult, urlsplit, urlunsplit

import httpx

PROVIDER_IMAGE_DEFAULT_MAX_BYTES = 24 * 1024 * 1024
PROVIDER_IMAGE_DEFAULT_TIMEOUT_SECONDS = 20.0
PROVIDER_IMAGE_MAX_CONCURRENT_FETCHES = 8

ProviderHostResolver = Callable[[str, int], Iterable[str]]
MonotonicClock = Callable[[], float]

_PROVIDER_IMAGE_TIMEOUT_MESSAGE = "provider image download exceeded the time limit"
_PROVIDER_IMAGE_FETCH_SLOTS = threading.BoundedSemaphore(
    PROVIDER_IMAGE_MAX_CONCURRENT_FETCHES
)


class ProviderImageFetchError(RuntimeError):
    error_code = "image_generation.provider_fetch_failed"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True, slots=True)
class ProviderFetchedImage:
    stream: BinaryIO
    byte_size: int
    declared_mime_type: str

    def close(self) -> None:
        self.stream.close()


def fetch_provider_image_url(
    source_url: str,
    *,
    allowed_hosts: Iterable[str],
    max_bytes: int = PROVIDER_IMAGE_DEFAULT_MAX_BYTES,
    timeout_seconds: float = PROVIDER_IMAGE_DEFAULT_TIMEOUT_SECONDS,
    resolver: ProviderHostResolver | None = None,
    transport: httpx.BaseTransport | None = None,
    clock: MonotonicClock = time.monotonic,
) -> ProviderFetchedImage:
    """Fetch one provider-owned image URL without opening an SSRF seam.

    Every address returned by DNS must be globally routable. The request then
    connects to one of those already-approved addresses while retaining the
    original provider hostname for HTTP Host and TLS SNI. Redirects are never
    followed or accepted. The blocking fetch runs in a daemon worker so the
    caller has one hard wall-clock budget that also covers platform DNS calls.
    Cooperative cancellation stops the worker at every blocking-operation
    boundary, and a late successful result is closed instead of published.
    """

    timeout = _normalized_timeout(timeout_seconds)
    hard_deadline = time.monotonic() + timeout
    operation_deadline = clock() + timeout
    fetch_slots = _PROVIDER_IMAGE_FETCH_SLOTS
    if not fetch_slots.acquire(blocking=False):
        raise ProviderImageFetchError("provider image fetch capacity is exhausted")
    job = _ProviderImageFetchJob()
    try:
        worker = threading.Thread(
            target=_run_provider_image_fetch_job,
            kwargs={
                "job": job,
                "source_url": source_url,
                "allowed_hosts": tuple(allowed_hosts),
                "max_bytes": max_bytes,
                "deadline": operation_deadline,
                "resolver": resolver,
                "transport": transport,
                "clock": clock,
                "release_slot": fetch_slots.release,
            },
            name="provider-image-fetch",
            daemon=True,
        )
        worker.start()
    except Exception:
        fetch_slots.release()
        raise

    remaining = max(0.0, hard_deadline - time.monotonic())
    completed_before_wait_timeout = job.done.wait(remaining)
    return job.take_result_before(
        hard_deadline,
        completed_before_wait_timeout=completed_before_wait_timeout,
    )


class _ProviderImageFetchJob:
    """Own one worker result until the caller or cancellation takes ownership."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.cancel_requested = threading.Event()
        self._lock = threading.Lock()
        self._cancelled = False
        self._result: ProviderFetchedImage | None = None
        self._error: Exception | None = None

    def publish_result(self, result: ProviderFetchedImage) -> None:
        close_result = False
        with self._lock:
            if self._cancelled:
                close_result = True
            else:
                self._result = result
            self.done.set()
        if close_result:
            _close_fetched_result(result)

    def publish_error(self, error: Exception) -> None:
        with self._lock:
            if not self._cancelled:
                self._error = error
            self.done.set()

    def take_result_before(
        self,
        hard_deadline: float,
        *,
        completed_before_wait_timeout: bool,
    ) -> ProviderFetchedImage:
        expired_result: ProviderFetchedImage | None = None
        timed_out = False
        with self._lock:
            if not completed_before_wait_timeout or time.monotonic() >= hard_deadline:
                self._cancelled = True
                self.cancel_requested.set()
                expired_result = self._result
                self._result = None
                self._error = None
                self.done.set()
                timed_out = True
            else:
                if self._error is not None:
                    raise self._error
                if self._result is None:
                    raise ProviderImageFetchError("provider image fetch did not complete")
                result = self._result
                self._result = None
                return result

        if expired_result is not None:
            _close_fetched_result(expired_result)
        if timed_out:
            raise ProviderImageFetchError(_PROVIDER_IMAGE_TIMEOUT_MESSAGE)
        raise ProviderImageFetchError("provider image fetch did not complete")


def _run_provider_image_fetch_job(
    *,
    job: _ProviderImageFetchJob,
    source_url: str,
    allowed_hosts: tuple[str, ...],
    max_bytes: int,
    deadline: float,
    resolver: ProviderHostResolver | None,
    transport: httpx.BaseTransport | None,
    clock: MonotonicClock,
    release_slot: Callable[[], None],
) -> None:
    try:
        try:
            result = _fetch_provider_image_url_sync(
                source_url,
                allowed_hosts=allowed_hosts,
                max_bytes=max_bytes,
                deadline=deadline,
                resolver=resolver,
                transport=transport,
                clock=clock,
                cancel_requested=job.cancel_requested,
            )
        except Exception as error:
            job.publish_error(error)
        else:
            job.publish_result(result)
    finally:
        release_slot()


def _fetch_provider_image_url_sync(
    source_url: str,
    *,
    allowed_hosts: Iterable[str],
    max_bytes: int,
    deadline: float,
    resolver: ProviderHostResolver | None,
    transport: httpx.BaseTransport | None,
    clock: MonotonicClock,
    cancel_requested: threading.Event,
) -> ProviderFetchedImage:
    _ensure_fetch_active(cancel_requested, clock, deadline)

    parsed, hostname = _validate_provider_url(source_url, allowed_hosts=allowed_hosts)
    resolve = resolver or _resolve_host_addresses
    try:
        _ensure_fetch_active(cancel_requested, clock, deadline)
        addresses = _validate_resolved_addresses(resolve(hostname, 443))
        _ensure_fetch_active(cancel_requested, clock, deadline)
    except ProviderImageFetchError:
        raise
    except (OSError, UnicodeError, ValueError) as error:
        raise ProviderImageFetchError("provider image host could not be resolved") from error

    pinned_url = _pinned_url(parsed, addresses[0])
    byte_limit = max(1, int(max_bytes))
    spool: BinaryIO | None = None
    try:
        request_timeout = _remaining_timeout(cancel_requested, clock, deadline)
        with httpx.Client(
            timeout=httpx.Timeout(request_timeout),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client:
            request = client.build_request(
                "GET",
                pinned_url,
                headers={
                    "Accept": "image/avif,image/webp,image/png,image/jpeg",
                    "Host": _host_header(hostname),
                },
                extensions={"sni_hostname": hostname},
            )
            response: httpx.Response | None = None
            try:
                _ensure_fetch_active(cancel_requested, clock, deadline)
                response = client.send(request, stream=True)
                _ensure_fetch_active(cancel_requested, clock, deadline)
                if 300 <= response.status_code < 400:
                    raise ProviderImageFetchError("provider image redirects are forbidden")
                if response.status_code < 200 or response.status_code >= 300:
                    raise ProviderImageFetchError("provider image request was unsuccessful")
                content_length = _content_length(response.headers.get("content-length"))
                if content_length is not None and content_length > byte_limit:
                    raise ProviderImageFetchError("provider image exceeds the byte limit")

                spool = tempfile.TemporaryFile(mode="w+b")
                total_bytes = 0
                _ensure_fetch_active(cancel_requested, clock, deadline)
                for chunk in response.iter_bytes():
                    _ensure_fetch_active(cancel_requested, clock, deadline)
                    if not chunk:
                        continue
                    total_bytes += len(chunk)
                    if total_bytes > byte_limit:
                        raise ProviderImageFetchError("provider image exceeds the byte limit")
                    spool.write(chunk)
                    _ensure_fetch_active(cancel_requested, clock, deadline)
                if total_bytes == 0:
                    raise ProviderImageFetchError("provider image response was empty")
                _ensure_fetch_active(cancel_requested, clock, deadline)
                spool.seek(0)
                declared_mime_type = _normalized_content_type(
                    response.headers.get("content-type", "")
                )
            finally:
                if response is not None:
                    response.close()
    except ProviderImageFetchError:
        if spool is not None:
            spool.close()
        raise
    except (httpx.HTTPError, OSError, ValueError) as error:
        if spool is not None:
            spool.close()
        raise ProviderImageFetchError("provider image could not be fetched") from error

    assert spool is not None
    return ProviderFetchedImage(
        stream=spool,
        byte_size=total_bytes,
        declared_mime_type=declared_mime_type,
    )


def _normalized_timeout(value: float) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as error:
        raise ProviderImageFetchError("provider image timeout is invalid") from error
    if not math.isfinite(timeout):
        raise ProviderImageFetchError("provider image timeout is invalid")
    return max(0.001, timeout)


def _close_fetched_result(result: ProviderFetchedImage) -> None:
    try:
        result.close()
    except OSError:
        pass


def _remaining_timeout(
    cancel_requested: threading.Event,
    clock: MonotonicClock,
    deadline: float,
) -> float:
    _ensure_fetch_active(cancel_requested, clock, deadline)
    return max(0.001, deadline - clock())


def _validate_provider_url(
    source_url: str,
    *,
    allowed_hosts: Iterable[str],
) -> tuple[SplitResult, str]:
    normalized_url = str(source_url or "").strip()
    if not normalized_url or len(normalized_url) > 2048:
        raise ProviderImageFetchError("provider image URL is invalid")
    try:
        parsed = urlsplit(normalized_url)
        port = parsed.port
    except ValueError as error:
        raise ProviderImageFetchError("provider image URL is invalid") from error
    if parsed.scheme.lower() != "https" or not parsed.netloc or not parsed.hostname:
        raise ProviderImageFetchError("provider image URL must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ProviderImageFetchError("provider image URL credentials are forbidden")
    if port not in (None, 443):
        raise ProviderImageFetchError("provider image URL must use port 443")
    if parsed.fragment:
        raise ProviderImageFetchError("provider image URL fragments are forbidden")

    hostname = _normalized_hostname(parsed.hostname)
    normalized_allowed_hosts = {
        _normalized_hostname(host) for host in allowed_hosts if str(host or "").strip()
    }
    if not normalized_allowed_hosts or hostname not in normalized_allowed_hosts:
        raise ProviderImageFetchError("provider image host is not allowlisted")
    return parsed, hostname


def _normalized_hostname(value: str) -> str:
    hostname = str(value or "").strip().rstrip(".").lower()
    if not hostname or "%" in hostname:
        raise ProviderImageFetchError("provider image host is invalid")
    try:
        return hostname.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise ProviderImageFetchError("provider image host is invalid") from error


def _resolve_host_addresses(hostname: str, port: int) -> Iterable[str]:
    records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    return [str(record[4][0]) for record in records]


def _validate_resolved_addresses(values: Iterable[str]) -> tuple[str, ...]:
    addresses: list[str] = []
    for value in values:
        try:
            address = ipaddress.ip_address(str(value))
        except ValueError as error:
            raise ProviderImageFetchError("provider image host resolved unexpectedly") from error
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        if not address.is_global:
            raise ProviderImageFetchError("provider image host is not publicly routable")
        normalized = address.compressed
        if normalized not in addresses:
            addresses.append(normalized)
    if not addresses:
        raise ProviderImageFetchError("provider image host did not resolve")
    return tuple(addresses)


def _pinned_url(parsed: SplitResult, address: str) -> str:
    ip = ipaddress.ip_address(address)
    authority = f"[{ip.compressed}]" if isinstance(ip, ipaddress.IPv6Address) else ip.compressed
    return urlunsplit(("https", authority, parsed.path or "/", parsed.query, ""))


def _host_header(hostname: str) -> str:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return hostname
    if isinstance(address, ipaddress.IPv6Address):
        return f"[{address.compressed}]"
    return address.compressed


def _content_length(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        length = int(value)
    except ValueError as error:
        raise ProviderImageFetchError("provider image content length is invalid") from error
    if length < 0:
        raise ProviderImageFetchError("provider image content length is invalid")
    return length


def _normalized_content_type(value: str) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()


def _ensure_fetch_active(
    cancel_requested: threading.Event,
    clock: MonotonicClock,
    deadline: float,
) -> None:
    if cancel_requested.is_set() or clock() >= deadline:
        raise ProviderImageFetchError(_PROVIDER_IMAGE_TIMEOUT_MESSAGE)
