from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import Request

import app.core.security as security_module
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import SITE_API_KEY_STATUS_REVOKED, SiteApiKey
from app.core.security import (
    PrehashedRequestBody,
    RequestAuthContext,
    RequestAuthError,
    authorize_request,
)
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
    build_auth_headers,
    seed_site_auth,
)


def _build_request(headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/v1/runtime/media/uploads",
        "raw_path": b"/v1/runtime/media/uploads",
        "query_string": b"",
        "headers": [
            (name.lower().encode("latin-1"), value.encode("latin-1"))
            for name, value in headers.items()
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 443),
    }
    return Request(scope)


def _settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
    )


async def _authorize(
    request: Request,
    settings: Settings,
    loader: Callable[[], Awaitable[PrehashedRequestBody]],
    *,
    max_body_bytes: int = 1024,
) -> RequestAuthContext:
    return await authorize_request(
        request,
        settings=settings,
        database_url=settings.database_url,
        timestamp_tolerance_seconds=300,
        public_post_rate_limit_window_seconds=60,
        public_post_max_requests_per_window=100,
        public_post_max_requests_per_key_window=100,
        public_post_max_requests_per_ip_window=100,
        public_guard_cooldown_window_seconds=60,
        public_guard_max_reject_events_per_site_window=100,
        public_guard_max_reject_events_per_key_window=100,
        public_guard_max_reject_events_per_ip_window=100,
        require_idempotency=True,
        required_scope="runtime:execute",
        max_body_bytes=max_body_bytes,
        body_evidence_loader=loader,
    )


@pytest.mark.asyncio
async def test_body_evidence_loader_bypasses_request_body_and_preserves_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'evidence-valid.sqlite3'}"
    init_schema(database_url)
    seed_site_auth(database_url, site_id="site_alpha", scopes=["runtime:execute"])
    payload = b"sealed-media-body"
    headers = build_auth_headers(
        "POST",
        "/v1/runtime/media/uploads",
        site_id="site_alpha",
        body=payload,
        idempotency_key="evidence-valid",
        nonce="evidence-valid-nonce",
    )
    request = _build_request(headers)

    async def forbidden_body() -> bytes:
        raise AssertionError("request.body() must not be called for body evidence")

    async def loader() -> PrehashedRequestBody:
        return PrehashedRequestBody(
            sha256_hex=hashlib.sha256(payload).hexdigest(),
            byte_size=len(payload),
        )

    monkeypatch.setattr(request, "body", forbidden_body)
    try:
        auth = await _authorize(request, _settings(database_url), loader)
        assert auth.body_digest == hashlib.sha256(payload).hexdigest()
    finally:
        dispose_engine(database_url)


@pytest.mark.asyncio
async def test_body_evidence_rejects_invalid_digest_without_calling_request_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'evidence-invalid.sqlite3'}"
    init_schema(database_url)
    seed_site_auth(database_url, site_id="site_alpha", scopes=["runtime:execute"])
    headers = build_auth_headers(
        "POST",
        "/v1/runtime/media/uploads",
        site_id="site_alpha",
        body=b"payload",
        idempotency_key="evidence-invalid",
        nonce="evidence-invalid-nonce",
    )
    request = _build_request(headers)

    async def forbidden_body() -> bytes:
        raise AssertionError("request.body() must not be called for body evidence")

    async def loader() -> PrehashedRequestBody:
        return PrehashedRequestBody(sha256_hex="not-a-digest", byte_size=7)

    monkeypatch.setattr(request, "body", forbidden_body)
    try:
        with pytest.raises(RequestAuthError) as exc_info:
            await _authorize(request, _settings(database_url), loader)
        assert exc_info.value.status_code == 400
        assert exc_info.value.error_code == "auth.invalid_body_digest"
    finally:
        dispose_engine(database_url)


@pytest.mark.asyncio
async def test_body_evidence_validates_oversize_before_digest_format(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'evidence-oversize.sqlite3'}"
    init_schema(database_url)
    seed_site_auth(database_url, site_id="site_alpha", scopes=["runtime:execute"])
    headers = build_auth_headers(
        "POST",
        "/v1/runtime/media/uploads",
        site_id="site_alpha",
        body=b"payload",
        idempotency_key="evidence-oversize",
        nonce="evidence-oversize-nonce",
    )
    request = _build_request(headers)

    async def loader() -> PrehashedRequestBody:
        return PrehashedRequestBody(sha256_hex="not-a-digest", byte_size=9)

    try:
        with pytest.raises(RequestAuthError) as exc_info:
            await _authorize(request, _settings(database_url), loader, max_body_bytes=8)
        assert exc_info.value.status_code == 413
        assert exc_info.value.error_code == "auth.payload_too_large"
    finally:
        dispose_engine(database_url)


@pytest.mark.asyncio
async def test_body_evidence_rejects_negative_byte_size(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'evidence-negative.sqlite3'}"
    init_schema(database_url)
    seed_site_auth(database_url, site_id="site_alpha", scopes=["runtime:execute"])
    headers = build_auth_headers(
        "POST",
        "/v1/runtime/media/uploads",
        site_id="site_alpha",
        body=b"",
        idempotency_key="evidence-negative",
        nonce="evidence-negative-nonce",
    )
    request = _build_request(headers)

    async def loader() -> PrehashedRequestBody:
        return PrehashedRequestBody(sha256_hex=hashlib.sha256(b"").hexdigest(), byte_size=-1)

    try:
        with pytest.raises(RequestAuthError) as exc_info:
            await _authorize(request, _settings(database_url), loader)
        assert exc_info.value.status_code == 400
        assert exc_info.value.error_code == "auth.invalid_body_digest"
    finally:
        dispose_engine(database_url)


@pytest.mark.asyncio
async def test_signature_prefix_is_accepted_with_body_evidence(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'evidence-prefix.sqlite3'}"
    init_schema(database_url)
    seed_site_auth(database_url, site_id="site_alpha", scopes=["runtime:execute"])
    payload = b"payload"
    headers = build_auth_headers(
        "POST",
        "/v1/runtime/media/uploads",
        site_id="site_alpha",
        body=payload,
        idempotency_key="evidence-prefix",
        nonce="evidence-prefix-nonce",
    )
    headers["X-Npcink-Signature"] = f"sha256={headers['X-Npcink-Signature']}"
    request = _build_request(headers)

    async def loader() -> PrehashedRequestBody:
        return PrehashedRequestBody(
            sha256_hex=hashlib.sha256(payload).hexdigest(),
            byte_size=len(payload),
        )

    try:
        auth = await _authorize(request, _settings(database_url), loader)
        assert auth.site_id == "site_alpha"
    finally:
        dispose_engine(database_url)


@pytest.mark.asyncio
async def test_malformed_signature_is_rejected_before_body_evidence_loader(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'evidence-signature.sqlite3'}"
    init_schema(database_url)
    seed_site_auth(database_url, site_id="site_alpha", scopes=["runtime:execute"])
    headers = build_auth_headers(
        "POST",
        "/v1/runtime/media/uploads",
        site_id="site_alpha",
        body=b"payload",
        idempotency_key="evidence-signature",
        nonce="evidence-signature-nonce",
    )
    headers["X-Npcink-Signature"] = "deadbeef"
    request = _build_request(headers)
    loader_called = False

    async def loader() -> PrehashedRequestBody:
        nonlocal loader_called
        loader_called = True
        return PrehashedRequestBody(sha256_hex="0" * 64, byte_size=7)

    try:
        with pytest.raises(RequestAuthError) as exc_info:
            await _authorize(request, _settings(database_url), loader)
        assert exc_info.value.status_code == 401
        assert exc_info.value.error_code == "auth.invalid_signature"
        assert loader_called is False
    finally:
        dispose_engine(database_url)


@pytest.mark.asyncio
async def test_stale_timestamp_is_rejected_before_body_evidence_loader(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'evidence-stale.sqlite3'}"
    init_schema(database_url)
    seed_site_auth(database_url, site_id="site_alpha", scopes=["runtime:execute"])
    payload = b"payload"
    headers = build_auth_headers(
        "POST",
        "/v1/runtime/media/uploads",
        site_id="site_alpha",
        body=payload,
        idempotency_key="evidence-stale",
        nonce="evidence-stale-nonce",
        timestamp=str(int((datetime.now(UTC) - timedelta(minutes=10)).timestamp())),
    )
    loader_called = False

    async def loader() -> PrehashedRequestBody:
        nonlocal loader_called
        loader_called = True
        return PrehashedRequestBody(
            sha256_hex=hashlib.sha256(payload).hexdigest(),
            byte_size=len(payload),
        )

    try:
        with pytest.raises(RequestAuthError) as exc_info:
            await _authorize(_build_request(headers), _settings(database_url), loader)
        assert exc_info.value.error_code == "auth.stale_timestamp"
        assert loader_called is False
    finally:
        dispose_engine(database_url)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("site_id", "key_id", "scopes", "expected_error"),
    [
        ("site_missing", "key_default", ["runtime:execute"], "auth.invalid_site"),
        ("site_alpha", "key_missing", ["runtime:execute"], "auth.invalid_key"),
        ("site_alpha", "key_default", ["runtime:read"], "auth.scope_denied"),
    ],
)
async def test_invalid_site_key_or_scope_is_rejected_before_body_evidence_loader(
    tmp_path: Path,
    site_id: str,
    key_id: str,
    scopes: list[str],
    expected_error: str,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / f'evidence-preflight-{expected_error}.sqlite3'}"
    init_schema(database_url)
    seed_site_auth(database_url, site_id="site_alpha", scopes=scopes)
    payload = b"payload"
    headers = build_auth_headers(
        "POST",
        "/v1/runtime/media/uploads",
        site_id=site_id,
        key_id=key_id,
        body=payload,
        idempotency_key=f"evidence-preflight-{expected_error}",
        nonce=f"evidence-preflight-{expected_error}-nonce",
    )
    loader_called = False

    async def loader() -> PrehashedRequestBody:
        nonlocal loader_called
        loader_called = True
        return PrehashedRequestBody(
            sha256_hex=hashlib.sha256(payload).hexdigest(),
            byte_size=len(payload),
        )

    try:
        with pytest.raises(RequestAuthError) as exc_info:
            await _authorize(_build_request(headers), _settings(database_url), loader)
        assert exc_info.value.error_code == expected_error
        assert loader_called is False
    finally:
        dispose_engine(database_url)


@pytest.mark.asyncio
async def test_key_revoked_during_body_load_is_rejected_by_final_revalidation(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'evidence-revoked-during-load.sqlite3'}"
    init_schema(database_url)
    seed_site_auth(database_url, site_id="site_alpha", scopes=["runtime:execute"])
    payload = b"payload"
    headers = build_auth_headers(
        "POST",
        "/v1/runtime/media/uploads",
        site_id="site_alpha",
        body=payload,
        idempotency_key="evidence-revoked-during-load",
        nonce="evidence-revoked-during-load-nonce",
    )

    async def loader() -> PrehashedRequestBody:
        with get_session(database_url) as session:
            api_key = session.get(SiteApiKey, "key_default")
            assert api_key is not None
            api_key.status = SITE_API_KEY_STATUS_REVOKED
            api_key.revoked_at = datetime.now(UTC)
            session.commit()
        return PrehashedRequestBody(
            sha256_hex=hashlib.sha256(payload).hexdigest(),
            byte_size=len(payload),
        )

    try:
        with pytest.raises(RequestAuthError) as exc_info:
            await _authorize(_build_request(headers), _settings(database_url), loader)
        assert exc_info.value.error_code == "auth.invalid_key"
    finally:
        dispose_engine(database_url)


@pytest.mark.asyncio
async def test_valid_format_invalid_hmac_loads_body_before_rejection(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'evidence-invalid-hmac.sqlite3'}"
    init_schema(database_url)
    seed_site_auth(database_url, site_id="site_alpha", scopes=["runtime:execute"])
    payload = b"payload"
    headers = build_auth_headers(
        "POST",
        "/v1/runtime/media/uploads",
        site_id="site_alpha",
        body=payload,
        idempotency_key="evidence-invalid-hmac",
        nonce="evidence-invalid-hmac-nonce",
    )
    headers["X-Npcink-Signature"] = "0" * 64
    loader_called = False

    async def loader() -> PrehashedRequestBody:
        nonlocal loader_called
        loader_called = True
        return PrehashedRequestBody(
            sha256_hex=hashlib.sha256(payload).hexdigest(),
            byte_size=len(payload),
        )

    try:
        with pytest.raises(RequestAuthError) as exc_info:
            await _authorize(_build_request(headers), _settings(database_url), loader)
        assert exc_info.value.error_code == "auth.invalid_signature"
        assert loader_called is True
    finally:
        dispose_engine(database_url)


@pytest.mark.asyncio
async def test_timestamp_is_revalidated_after_body_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'evidence-final-timestamp.sqlite3'}"
    init_schema(database_url)
    seed_site_auth(database_url, site_id="site_alpha", scopes=["runtime:execute"])
    payload = b"payload"
    sent_at = datetime.now(UTC).replace(microsecond=0)
    headers = build_auth_headers(
        "POST",
        "/v1/runtime/media/uploads",
        site_id="site_alpha",
        body=payload,
        idempotency_key="evidence-final-timestamp",
        nonce="evidence-final-timestamp-nonce",
        timestamp=str(int(sent_at.timestamp())),
    )
    now_call_count = 0

    class AdvancingDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            nonlocal now_call_count
            now_call_count += 1
            current = sent_at if now_call_count == 1 else sent_at + timedelta(minutes=10)
            return current if tz is not None else current.replace(tzinfo=None)

    async def loader() -> PrehashedRequestBody:
        return PrehashedRequestBody(
            sha256_hex=hashlib.sha256(payload).hexdigest(),
            byte_size=len(payload),
        )

    monkeypatch.setattr(security_module, "datetime", AdvancingDateTime)
    try:
        with pytest.raises(RequestAuthError) as exc_info:
            await _authorize(_build_request(headers), _settings(database_url), loader)
        assert exc_info.value.error_code == "auth.stale_timestamp"
        assert now_call_count >= 2
    finally:
        dispose_engine(database_url)
