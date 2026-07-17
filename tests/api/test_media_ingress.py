from __future__ import annotations

import asyncio
import hashlib
import io
import json
import tempfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import starlette.formparsers as starlette_formparsers
from fastapi import Request
from fastapi.testclient import TestClient
from PIL import Image

import app.api.media_ingress as media_ingress_module
import app.api.routes.media_derivatives as media_routes
from app.adapters.queue.in_memory import InMemoryRuntimeQueue
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, init_schema
from app.core.security import build_canonical_request, build_hmac_signature
from app.core.services import CloudServices
from app.domain.media_derivatives.artifacts import ValidatedImageUpload
from app.domain.media_derivatives.contracts import MAX_UPLOAD_BYTES_IMAGE
from app.domain.runtime.service import RuntimeService
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
    TEST_SECRET,
    build_auth_headers,
    build_traceparent,
    seed_site_auth,
)

UPLOAD_PATH = "/v1/runtime/media/uploads"


def _build_client(
    tmp_path: Path,
    *,
    max_body_bytes: int | None = None,
) -> tuple[str, TestClient]:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'media-ingress.sqlite3'}"
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read"],
    )
    settings_kwargs: dict[str, object] = {}
    if max_body_bytes is not None:
        settings_kwargs["media_upload_max_body_bytes"] = max_body_bytes
    settings = Settings(
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        artifact_store_root=str(tmp_path / "artifacts"),
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        **settings_kwargs,
    )
    app = create_app(
        CloudServices(
            settings=settings,
            providers={},
            runtime_queue=InMemoryRuntimeQueue(),
        )
    )
    return database_url, TestClient(app)


def _png_bytes() -> bytes:
    image = Image.new("RGB", (32, 24), color="red")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _highly_compressed_png_bytes(width: int, height: int) -> bytes:
    image = Image.new("1", (width, height), color=0)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _upload_request() -> dict[str, object]:
    return {
        "request_contract_version": "media_upload_request.v1",
        "media_kind": "image",
        "ttl_minutes": 30,
    }


def _multipart(
    parts: list[tuple[str, bytes, str | None]],
    *,
    boundary: str,
    complete: bool = True,
) -> tuple[bytes, str]:
    body_parts: list[bytes] = []
    for name, value, filename in parts:
        body_parts.append(f"--{boundary}".encode())
        disposition = f'Content-Disposition: form-data; name="{name}"'
        if filename is not None:
            disposition += f'; filename="{filename}"'
        body_parts.append(disposition.encode())
        if filename is not None:
            body_parts.append(b"Content-Type: image/png")
        body_parts.extend((b"", value))
    if complete:
        body_parts.append(f"--{boundary}--".encode())
    return (
        b"\r\n".join(body_parts),
        f"multipart/form-data; boundary={boundary}",
    )


def _valid_multipart(
    *,
    payload: bytes | None = None,
    boundary: str = "media-boundary",
) -> tuple[bytes, str]:
    return _multipart(
        [
            ("request", json.dumps(_upload_request()).encode(), None),
            ("file", payload if payload is not None else _png_bytes(), "source.png"),
        ],
        boundary=boundary,
    )


def _signed_headers(
    body: bytes,
    content_type: str,
    *,
    key: str,
    nonce: str,
) -> dict[str, str]:
    headers = build_auth_headers(
        "POST",
        UPLOAD_PATH,
        site_id="site_alpha",
        body=body,
        idempotency_key=key,
        nonce=nonce,
    )
    headers["content-type"] = content_type
    return headers


def _headers_for_digest(digest: str, *, key: str, nonce: str) -> dict[str, str]:
    timestamp = str(int(datetime.now(UTC).timestamp()))
    traceparent = build_traceparent("fedcba9876543210fedcba9876543210")
    canonical = build_canonical_request(
        method="POST",
        path=UPLOAD_PATH,
        query="",
        site_id="site_alpha",
        key_id="key_default",
        timestamp=timestamp,
        nonce=nonce,
        idempotency_key=key,
        traceparent=traceparent,
        body_digest=digest,
    )
    return {
        "X-Npcink-Site-Id": "site_alpha",
        "X-Npcink-Key-Id": "key_default",
        "X-Npcink-Timestamp": timestamp,
        "X-Npcink-Signature": build_hmac_signature(TEST_SECRET, canonical),
        "X-Npcink-Nonce": nonce,
        "Idempotency-Key": key,
        "traceparent": traceparent,
    }


def _track_tempfiles(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[object], list[object]]:
    original_temporary_file = tempfile.TemporaryFile
    original_spooled_file = tempfile.SpooledTemporaryFile
    raw_files: list[object] = []
    upload_files: list[object] = []

    def track_raw(*args: object, **kwargs: object) -> object:
        file_object = original_temporary_file(*args, **kwargs)
        raw_files.append(file_object)
        return file_object

    def track_upload(*args: object, **kwargs: object) -> object:
        file_object = original_spooled_file(*args, **kwargs)
        upload_files.append(file_object)
        return file_object

    monkeypatch.setattr(media_ingress_module.tempfile, "TemporaryFile", track_raw)
    monkeypatch.setattr(starlette_formparsers, "SpooledTemporaryFile", track_upload)
    return raw_files, upload_files


def _assert_closed(files: list[object]) -> None:
    assert files
    assert all(file_object.closed for file_object in files)


def test_authentication_precedes_multipart_parse_and_declared_size(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path, max_body_bytes=64)
    try:
        response = client.post(
            UPLOAD_PATH,
            content=b"truncated",
            headers={
                "content-type": "multipart/form-data; boundary=missing",
                "content-length": "65",
            },
        )
        assert response.status_code == 401
        assert response.json()["error_code"] == "auth.site_id_required"
    finally:
        dispose_engine(database_url)


@pytest.mark.parametrize("dimensions", [(4097, 4097), (8193, 1)])
def test_highly_compressed_image_over_decode_budget_is_rejected_before_load(
    tmp_path: Path,
    dimensions: tuple[int, int],
) -> None:
    database_url, client = _build_client(tmp_path)
    payload = _highly_compressed_png_bytes(*dimensions)
    assert len(payload) < 64 * 1024
    body, content_type = _valid_multipart(payload=payload, boundary="decode-budget")
    headers = _signed_headers(
        body,
        content_type,
        key="decode-budget",
        nonce="decode-budget",
    )
    try:
        with patch("PIL.Image.Image.load") as load_mock:
            response = client.post(UPLOAD_PATH, content=body, headers=headers)
        assert response.status_code == 422
        assert response.json()["error_code"] == "media_derivative.source_too_large"
        assert not load_mock.called
    finally:
        dispose_engine(database_url)


@pytest.mark.asyncio
async def test_actual_byte_count_and_content_length_caps_are_authoritative(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path, max_body_bytes=64)
    body = b"x" * 65
    headers = _signed_headers(body, "application/json", key="actual-cap", nonce="actual-cap")

    async def chunks() -> AsyncIterator[bytes]:
        yield body[:32]
        yield body[32:]

    try:
        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as async_client:
            actual = await async_client.post(UPLOAD_PATH, content=chunks(), headers=headers)
        assert actual.status_code == 413
        assert actual.json()["error_code"] == "auth.payload_too_large"

        declared_headers = _signed_headers(
            b"{}",
            "application/json",
            key="declared-cap",
            nonce="declared-cap",
        )
        declared_headers["content-length"] = "65"
        declared = client.post(UPLOAD_PATH, content=b"{}", headers=declared_headers)
        assert declared.status_code == 413
        assert declared.json()["error_code"] == "auth.payload_too_large"
    finally:
        dispose_engine(database_url)


@pytest.mark.parametrize(
    "case",
    [
        "unknown",
        "duplicate_request",
        "duplicate_file",
        "incomplete",
        "request_as_file",
        "file_as_field",
        "oversize_request",
        "oversize_part_header",
    ],
)
def test_multipart_shape_and_bounds_are_rejected(tmp_path: Path, case: str) -> None:
    database_url, client = _build_client(tmp_path)
    request_json = json.dumps(_upload_request()).encode()
    parts: list[tuple[str, bytes, str | None]]
    complete = True
    if case == "unknown":
        parts = [("request", request_json, None), ("unexpected", b"x", "x.bin")]
    elif case == "duplicate_request":
        parts = [("request", request_json, None), ("request", request_json, None)]
    elif case == "duplicate_file":
        parts = [
            ("request", request_json, None),
            ("file", b"one", "one.png"),
            ("file", b"two", "two.png"),
        ]
    elif case == "incomplete":
        parts = [("request", request_json, None), ("file", b"partial", "partial.png")]
        complete = False
    elif case == "request_as_file":
        parts = [("request", request_json, "request.json")]
    elif case == "file_as_field":
        parts = [("request", request_json, None), ("file", b"not-file", None)]
    elif case == "oversize_request":
        parts = [("request", b"x" * (64 * 1024 + 1), None)]
    else:
        parts = [("x" * (16 * 1024 + 1), b"value", None)]
    body, content_type = _multipart(parts, boundary=f"boundary-{case}", complete=complete)
    headers = _signed_headers(body, content_type, key=f"shape-{case}", nonce=f"shape-{case}")
    try:
        response = client.post(UPLOAD_PATH, content=body, headers=headers)
        assert response.status_code == 400
        assert response.json()["error_code"] == "media_upload.invalid_request"
    finally:
        dispose_engine(database_url)


def test_file_above_one_mib_spools_and_all_tempfiles_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, client = _build_client(tmp_path)
    raw_files, upload_files = _track_tempfiles(monkeypatch)
    observed: dict[str, object] = {}

    def inspect_upload(stream: object, **kwargs: object) -> ValidatedImageUpload:
        observed["rolled"] = getattr(stream, "_rolled", False)
        observed["file"] = stream
        return ValidatedImageUpload(
            byte_size=1024 * 1024 + 1,
            checksum="sha256:synthetic",
            content_type="image/png",
            format="png",
            width=32,
            height=24,
        )

    def fail_service(self: RuntimeService, **kwargs: object) -> object:
        raise RuntimeError("stop after ingress inspection")

    monkeypatch.setattr(media_routes, "validate_image_upload_stream", inspect_upload)
    monkeypatch.setattr(RuntimeService, "create_media_upload", fail_service)
    body, content_type = _valid_multipart(payload=b"x" * (1024 * 1024 + 1), boundary="spool-disk")
    headers = _signed_headers(body, content_type, key="spool-disk", nonce="spool-disk")
    error_client = TestClient(client.app, raise_server_exceptions=False)
    try:
        response = error_client.post(UPLOAD_PATH, content=body, headers=headers)
        assert response.status_code == 500
        assert observed["rolled"] is True
        assert observed["file"].closed is True
        _assert_closed(raw_files)
        _assert_closed(upload_files)
    finally:
        error_client.close()
        dispose_engine(database_url)


def test_auth_parse_and_service_failures_close_ingress_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, client = _build_client(tmp_path)
    raw_files, upload_files = _track_tempfiles(monkeypatch)
    valid_body, content_type = _valid_multipart()
    invalid_headers = _signed_headers(valid_body, content_type, key="bad-auth", nonce="bad-auth")
    invalid_headers["X-Npcink-Signature"] = "0" * 64
    try:
        auth = client.post(UPLOAD_PATH, content=valid_body, headers=invalid_headers)
        assert auth.status_code == 401
        _assert_closed(raw_files)

        partial_body, partial_type = _multipart(
            [
                ("request", json.dumps(_upload_request()).encode(), None),
                ("file", b"partial", "partial.png"),
            ],
            boundary="partial-cleanup",
            complete=False,
        )
        partial_headers = _signed_headers(
            partial_body,
            partial_type,
            key="partial",
            nonce="partial",
        )
        parse = client.post(UPLOAD_PATH, content=partial_body, headers=partial_headers)
        assert parse.status_code == 400
        assert parse.json()["error_code"] == "media_upload.invalid_request"

        def fail_service(self: RuntimeService, **kwargs: object) -> object:
            raise RuntimeError("synthetic service failure")

        monkeypatch.setattr(RuntimeService, "create_media_upload", fail_service)
        service_headers = _signed_headers(valid_body, content_type, key="service", nonce="service")
        error_client = TestClient(client.app, raise_server_exceptions=False)
        try:
            service = error_client.post(UPLOAD_PATH, content=valid_body, headers=service_headers)
            assert service.status_code == 500
        finally:
            error_client.close()
        assert all(file_object.closed for file_object in raw_files)
        assert all(file_object.closed for file_object in upload_files)
    finally:
        dispose_engine(database_url)


@pytest.mark.asyncio
async def test_cancellation_closes_all_ingress_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, client = _build_client(tmp_path)
    raw_files, upload_files = _track_tempfiles(monkeypatch)

    def cancel_service(self: RuntimeService, **kwargs: object) -> object:
        raise asyncio.CancelledError

    monkeypatch.setattr(RuntimeService, "create_media_upload", cancel_service)
    body, content_type = _valid_multipart(boundary="cancel-cleanup")
    headers = _signed_headers(body, content_type, key="cancel", nonce="cancel")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": UPLOAD_PATH,
        "raw_path": UPLOAD_PATH.encode(),
        "query_string": b"",
        "headers": [(name.lower().encode(), value.encode()) for name, value in headers.items()],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "app": client.app,
    }
    consumed = False

    async def receive() -> dict[str, object]:
        nonlocal consumed
        if consumed:
            return {"type": "http.disconnect"}
        consumed = True
        return {"type": "http.request", "body": body, "more_body": False}

    try:
        with pytest.raises(asyncio.CancelledError):
            await media_routes.create_media_upload(Request(scope, receive))
        _assert_closed(raw_files)
        _assert_closed(upload_files)
    finally:
        dispose_engine(database_url)


@pytest.mark.parametrize("failure_mode", ["create", "write", "short_write"])
def test_raw_capture_storage_failures_return_stable_503_and_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    database_url, client = _build_client(tmp_path)
    original_temporary_file = tempfile.TemporaryFile
    backing_files: list[object] = []

    class FailingWriteFile:
        def __init__(self) -> None:
            self.backing = original_temporary_file("w+b")
            backing_files.append(self.backing)

        def write(self, payload: bytes) -> int:
            if failure_mode == "short_write":
                return max(0, len(payload) - 1)
            raise OSError("synthetic ENOSPC")

        def close(self) -> None:
            self.backing.close()

    def fail_tempfile(*args: object, **kwargs: object) -> object:
        if failure_mode == "create":
            raise OSError("synthetic ENOSPC")
        return FailingWriteFile()

    monkeypatch.setattr(media_ingress_module.tempfile, "TemporaryFile", fail_tempfile)
    body, content_type = _valid_multipart()
    headers = _signed_headers(
        body,
        content_type,
        key=f"raw-{failure_mode}",
        nonce=f"raw-{failure_mode}",
    )
    try:
        response = client.post(UPLOAD_PATH, content=body, headers=headers)
        assert response.status_code == 503
        assert response.json()["error_code"] == "media_upload.ingress_unavailable"
        assert all(file_object.closed for file_object in backing_files)
    finally:
        dispose_engine(database_url)


def test_capture_read_and_spool_enospc_return_stable_503(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, client = _build_client(tmp_path)
    original_temporary_file = tempfile.TemporaryFile
    backing_files: list[object] = []

    class FailingReadFile:
        def __init__(self) -> None:
            self.backing = original_temporary_file("w+b")
            backing_files.append(self.backing)

        def write(self, payload: bytes) -> int:
            return self.backing.write(payload)

        def flush(self) -> None:
            self.backing.flush()

        def seek(self, offset: int) -> int:
            return self.backing.seek(offset)

        def read(self, size: int = -1) -> bytes:
            raise OSError("synthetic ingress read failure")

        def close(self) -> None:
            self.backing.close()

    monkeypatch.setattr(
        media_ingress_module.tempfile,
        "TemporaryFile",
        lambda *args, **kwargs: FailingReadFile(),
    )
    body, content_type = _valid_multipart()
    headers = _signed_headers(body, content_type, key="raw-read", nonce="raw-read")
    try:
        read_failure = client.post(UPLOAD_PATH, content=body, headers=headers)
        assert read_failure.status_code == 503
        assert read_failure.json()["error_code"] == "media_upload.ingress_unavailable"
        assert all(file_object.closed for file_object in backing_files)

        monkeypatch.setattr(media_ingress_module.tempfile, "TemporaryFile", original_temporary_file)
        monkeypatch.setattr(
            starlette_formparsers,
            "SpooledTemporaryFile",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("synthetic spool ENOSPC")),
        )
        spool_headers = _signed_headers(
            body,
            content_type,
            key="spool-enospc",
            nonce="spool-enospc",
        )
        spool_failure = client.post(UPLOAD_PATH, content=body, headers=spool_headers)
        assert spool_failure.status_code == 503
        assert spool_failure.json()["error_code"] == "media_upload.ingress_unavailable"
    finally:
        dispose_engine(database_url)


@pytest.mark.asyncio
async def test_file_over_fifty_mib_is_rejected_before_validation_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, client = _build_client(tmp_path)
    boundary = "file-over-fifty-mib"
    request_json = json.dumps(_upload_request()).encode()
    prefix = (
        b"\r\n".join(
            [
                f"--{boundary}".encode(),
                b'Content-Disposition: form-data; name="request"',
                b"",
                request_json,
                f"--{boundary}".encode(),
                b'Content-Disposition: form-data; name="file"; filename="large.bin"',
                b"Content-Type: application/octet-stream",
                b"",
            ]
        )
        + b"\r\n"
    )
    suffix = b"\r\n" + f"--{boundary}--".encode()
    chunk = b"x" * (64 * 1024)
    full_chunks = MAX_UPLOAD_BYTES_IMAGE // len(chunk)
    digest = hashlib.sha256(prefix)
    for _ in range(full_chunks):
        digest.update(chunk)
    digest.update(b"x")
    digest.update(suffix)
    headers = _headers_for_digest(digest.hexdigest(), key="file-cap", nonce="file-cap")
    headers["content-type"] = f"multipart/form-data; boundary={boundary}"

    def forbidden_validate(*args: object, **kwargs: object) -> object:
        raise AssertionError("oversize upload must be rejected before validation read")

    monkeypatch.setattr(media_routes, "validate_image_upload_stream", forbidden_validate)

    async def chunks() -> AsyncIterator[bytes]:
        yield prefix
        for _ in range(full_chunks):
            yield chunk
        yield b"x"
        yield suffix

    try:
        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as async_client:
            response = await async_client.post(UPLOAD_PATH, content=chunks(), headers=headers)
        assert response.status_code == 413
        assert response.json()["error_code"] == "media_upload.upload_too_large"
    finally:
        dispose_engine(database_url)
