from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import get_session
from app.core.logging import get_logger
from app.core.models import (
    SITE_API_KEY_STATUS_ACTIVE,
    SITE_STATUS_ACTIVE,
    ReplayReceipt,
    RuntimeGuardEvent,
    Site,
    SiteApiKey,
)
from app.core.secrets import decrypt_site_api_signing_secret
from app.domain.commercial.customer_api_keys import expand_api_key_scopes

logger = get_logger(__name__)

PUBLIC_RUNTIME_MAX_BODY_BYTES = 1_048_576
PUBLIC_RUNTIME_MAX_IDEMPOTENCY_KEY_LENGTH = 128
PUBLIC_RUNTIME_MAX_NONCE_LENGTH = 128
NONCE_HEADER = "X-Npcink-Nonce"
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
NONCE_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
REPLAY_SCOPE_PUBLIC_POST_SITE = "public_post_site"
REPLAY_SCOPE_PUBLIC_POST_KEY = "public_post_key"
REPLAY_SCOPE_PUBLIC_POST_IP = "public_post_ip"
REPLAY_SCOPE_PUBLIC_POST = REPLAY_SCOPE_PUBLIC_POST_SITE
REPLAY_SCOPE_INTERNAL_POST_TOKEN = "internal_post_token"
REPLAY_SCOPE_INTERNAL_POST_IP = "internal_post_ip"
REPLAY_SCOPE_INTERNAL_POST = REPLAY_SCOPE_INTERNAL_POST_TOKEN
REPLAY_SCOPE_INTERNAL = "internal"
RUNTIME_GUARD_SURFACE_PUBLIC = "public"
RUNTIME_GUARD_SURFACE_INTERNAL = "internal"


@dataclass(slots=True)
class RequestAuthContext:
    site_id: str
    key_id: str
    trace_id: str
    traceparent: str
    nonce: str
    idempotency_key: str
    timestamp: str
    body_digest: str


class RequestAuthError(ValueError):
    def __init__(self, status_code: int, error_code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message


def build_body_digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def build_secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def build_canonical_request(
    *,
    method: str,
    path: str,
    query: str,
    site_id: str,
    key_id: str,
    timestamp: str,
    nonce: str,
    idempotency_key: str,
    traceparent: str,
    body_digest: str,
) -> str:
    path_with_query = path if not query else f"{path}?{query}"
    return "\n".join(
        [
            method.upper(),
            path_with_query,
            site_id,
            key_id,
            timestamp,
            nonce,
            idempotency_key,
            traceparent,
            body_digest,
        ]
    )


def build_hmac_signature(signing_key: str, canonical_request: str) -> str:
    return hmac.new(
        signing_key.encode("utf-8"),
        canonical_request.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_hmac_signature(secret: str, payload: bytes, signature: str) -> bool:
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def extract_trace_id(traceparent: str) -> str:
    parts = traceparent.split("-")
    if len(parts) == 4 and len(parts[1]) == 32:
        return parts[1]
    return ""


def normalize_signature(signature: str) -> str:
    normalized = signature.strip()
    if normalized.startswith("sha256="):
        normalized = normalized[7:]
    return normalized.lower()


def parse_request_timestamp(timestamp: str) -> datetime:
    stripped = timestamp.strip()
    if stripped.isdigit():
        return datetime.fromtimestamp(int(stripped), tz=UTC)

    normalized = stripped.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _require_header(request: Request, header_name: str, error_code: str) -> str:
    value = request.headers.get(header_name, "").strip()
    if value:
        return value

    raise RequestAuthError(
        401,
        error_code,
        f"{header_name} header is required",
    )


def _validate_timestamp(
    timestamp: str,
    *,
    now: datetime,
    tolerance_seconds: int,
) -> None:
    try:
        parsed = parse_request_timestamp(timestamp)
    except ValueError as error:
        raise RequestAuthError(
            401,
            "auth.invalid_timestamp",
            "X-Npcink-Timestamp header is invalid",
        ) from error

    age_seconds = abs((now - parsed).total_seconds())
    if age_seconds > tolerance_seconds:
        raise RequestAuthError(
            401,
            "auth.stale_timestamp",
            "X-Npcink-Timestamp header is outside the accepted time window",
        )


def _validate_idempotency_key(
    idempotency_key: str,
    *,
    required: bool,
) -> None:
    if required and not idempotency_key:
        raise RequestAuthError(
            401,
            "auth.idempotency_required",
            "Idempotency-Key header is required",
        )
    if not idempotency_key:
        return
    if len(idempotency_key) > PUBLIC_RUNTIME_MAX_IDEMPOTENCY_KEY_LENGTH:
        raise RequestAuthError(
            400,
            "auth.invalid_idempotency_key",
            "Idempotency-Key header exceeds the accepted length",
        )
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise RequestAuthError(
            400,
            "auth.invalid_idempotency_key",
            "Idempotency-Key header contains unsupported characters",
        )


def _validate_nonce(
    nonce: str,
    *,
    required: bool,
) -> None:
    if required and not nonce:
        raise RequestAuthError(
            401,
            "auth.nonce_required",
            f"{NONCE_HEADER} header is required",
        )
    if not nonce:
        return
    if len(nonce) > PUBLIC_RUNTIME_MAX_NONCE_LENGTH:
        raise RequestAuthError(
            400,
            "auth.invalid_nonce",
            f"{NONCE_HEADER} header exceeds the accepted length",
        )
    if not NONCE_PATTERN.fullmatch(nonce):
        raise RequestAuthError(
            400,
            "auth.invalid_nonce",
            f"{NONCE_HEADER} header contains unsupported characters",
        )


def _validate_payload_size(
    body: bytes,
    *,
    max_body_bytes: int = PUBLIC_RUNTIME_MAX_BODY_BYTES,
) -> None:
    if len(body) > max_body_bytes:
        raise RequestAuthError(
            413,
            "auth.payload_too_large",
            "request payload exceeds the accepted size limit",
        )


def _validate_site_and_key(
    *,
    site: Site | None,
    api_key: SiteApiKey | None,
    site_id: str,
    key_id: str,
    required_scope: str | None,
    now: datetime,
) -> SiteApiKey:
    if site is None or site.status != SITE_STATUS_ACTIVE:
        raise RequestAuthError(401, "auth.invalid_site", "site is not authorized")

    if api_key is None or api_key.site_id != site_id:
        raise RequestAuthError(401, "auth.invalid_key", "API key is not authorized")

    expires_at = api_key.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    if (
        api_key.status != SITE_API_KEY_STATUS_ACTIVE
        or api_key.revoked_at is not None
        or (expires_at is not None and expires_at <= now)
    ):
        raise RequestAuthError(401, "auth.invalid_key", "API key is not authorized")

    scopes = expand_api_key_scopes(list(api_key.scopes_json or []))
    if required_scope and scopes and required_scope not in scopes:
        raise RequestAuthError(
            403,
            "auth.scope_denied",
            "API key scope does not permit this request",
        )

    return api_key


def _log_auth_rejection(
    request: Request,
    *,
    error: RequestAuthError,
    site_id: str,
    key_id: str,
    trace_id: str,
    required_scope: str | None,
) -> None:
    client_host = request.client.host if request.client is not None else ""
    logger.warning(
        (
            "request_auth_rejected error_code=%s method=%s path=%s site_id=%s "
            "key_id=%s trace_id=%s required_scope=%s client_ip=%s"
        ),
        error.error_code,
        request.method,
        request.url.path,
        site_id or "-",
        key_id or "-",
        trace_id or "-",
        required_scope or "-",
        client_host or "-",
    )


def resolve_client_scope_id(request: Request) -> str:
    if request.client is None or not request.client.host:
        return ""
    return request.client.host.strip()


def _resolve_replay_receipt_ttl_seconds(timestamp_tolerance_seconds: int) -> int:
    return max(60, timestamp_tolerance_seconds * 2)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _reserve_replay_receipt(
    *,
    session: Session,
    scope_kind: str,
    scope_id: str,
    replay_key: str,
    method: str,
    path: str,
    trace_id: str,
    now: datetime,
    ttl_seconds: int,
) -> None:
    receipt = session.scalar(
        select(ReplayReceipt).where(
            ReplayReceipt.scope_kind == scope_kind,
            ReplayReceipt.scope_id == scope_id,
            ReplayReceipt.replay_key == replay_key,
        )
    )
    expires_at = now + timedelta(seconds=max(1, ttl_seconds))
    if receipt is None:
        session.add(
            ReplayReceipt(
                scope_kind=scope_kind,
                scope_id=scope_id,
                replay_key=replay_key,
                method=method.upper(),
                path=path,
                trace_id=trace_id,
                created_at=now,
                expires_at=expires_at,
            )
        )
        session.flush()
        return

    if _normalize_datetime(receipt.expires_at) > now:
        raise RequestAuthError(
            409,
            "auth.replay_blocked",
            "request replay marker has already been consumed",
        )

    receipt.method = method.upper()
    receipt.path = path
    receipt.trace_id = trace_id
    receipt.created_at = now
    receipt.expires_at = expires_at
    session.flush()


def _enforce_short_window_rate_limit(
    *,
    session: Session,
    scope_kind: str,
    scope_id: str,
    now: datetime,
    window_seconds: int,
    max_requests: int,
) -> None:
    if max_requests <= 0 or window_seconds <= 0 or not scope_id:
        return

    window_start = now - timedelta(seconds=window_seconds)
    recent_count = int(
        session.scalar(
            select(func.count())
            .select_from(ReplayReceipt)
            .where(
                ReplayReceipt.scope_kind == scope_kind,
                ReplayReceipt.scope_id == scope_id,
                ReplayReceipt.created_at >= window_start,
            )
        )
        or 0
    )
    if recent_count < max_requests:
        return

    raise RequestAuthError(
        429,
        "auth.rate_limit_exceeded",
        "request rate limit exceeded for the current short window",
    )


def _enforce_guard_cooldown(
    *,
    session: Session,
    scope_kind: str,
    scope_id: str,
    now: datetime,
    window_seconds: int,
    max_events: int,
) -> None:
    if max_events <= 0 or window_seconds <= 0 or not scope_id:
        return

    window_start = now - timedelta(seconds=window_seconds)
    recent_count = int(
        session.scalar(
            select(func.count())
            .select_from(RuntimeGuardEvent)
            .where(
                RuntimeGuardEvent.scope_kind == scope_kind,
                RuntimeGuardEvent.scope_id == scope_id,
                RuntimeGuardEvent.created_at >= window_start,
            )
        )
        or 0
    )
    if recent_count < max_events:
        return

    raise RequestAuthError(
        429,
        "auth.rate_limit_exceeded",
        "request rate limit exceeded for the current cooldown window",
    )


def _normalize_guard_scope_pairs(
    scope_pairs: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    normalized: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for scope_kind, scope_id in scope_pairs:
        normalized_scope_id = scope_id.strip()
        if not scope_kind or not normalized_scope_id:
            continue
        key = (scope_kind, normalized_scope_id)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return normalized


def _build_runtime_guard_scope_pairs(
    *,
    auth_surface: str,
    site_id: str,
    key_id: str,
    client_ref: str,
) -> list[tuple[str, str]]:
    if auth_surface == RUNTIME_GUARD_SURFACE_INTERNAL:
        return _normalize_guard_scope_pairs(
            [
                (REPLAY_SCOPE_INTERNAL_POST, REPLAY_SCOPE_INTERNAL),
                (REPLAY_SCOPE_INTERNAL_POST_IP, client_ref),
            ]
        )

    return _normalize_guard_scope_pairs(
        [
            (REPLAY_SCOPE_PUBLIC_POST_SITE, site_id),
            (REPLAY_SCOPE_PUBLIC_POST_KEY, key_id),
            (REPLAY_SCOPE_PUBLIC_POST_IP, client_ref),
        ]
    )


def _record_runtime_guard_events(
    *,
    session: Session,
    auth_surface: str,
    scope_pairs: list[tuple[str, str]],
    site_id: str,
    key_id: str,
    client_ref: str,
    error: RequestAuthError,
    method: str,
    path: str,
    trace_id: str,
    payload_json: dict[str, object] | None = None,
) -> None:
    for scope_kind, scope_id in _normalize_guard_scope_pairs(scope_pairs):
        session.add(
            RuntimeGuardEvent(
                auth_surface=auth_surface,
                scope_kind=scope_kind,
                scope_id=scope_id,
                site_id=site_id or None,
                key_id=key_id or None,
                client_ref=client_ref or None,
                event_code=error.error_code,
                status_code=error.status_code,
                method=method.upper() if method else None,
                path=path or None,
                trace_id=trace_id or None,
                payload_json=payload_json or None,
                created_at=datetime.now(UTC),
            )
        )
    session.flush()


def record_runtime_guard_rejection(
    *,
    database_url: str,
    request: Request,
    auth_surface: str,
    error: RequestAuthError,
    site_id: str = "",
    key_id: str = "",
    trace_id: str = "",
    required_scope: str | None = None,
) -> None:
    client_ref = resolve_client_scope_id(request)
    scope_pairs = _build_runtime_guard_scope_pairs(
        auth_surface=auth_surface,
        site_id=site_id,
        key_id=key_id,
        client_ref=client_ref,
    )
    if not scope_pairs:
        return

    payload_json: dict[str, object] = {
        "message": error.message,
        "required_scope": required_scope or "",
        "query": request.url.query,
        "has_nonce": bool(request.headers.get(NONCE_HEADER, "").strip()),
        "has_idempotency_key": bool(request.headers.get("Idempotency-Key", "").strip()),
    }
    try:
        with get_session(database_url) as session:
            _record_runtime_guard_events(
                session=session,
                auth_surface=auth_surface,
                scope_pairs=scope_pairs,
                site_id=site_id,
                key_id=key_id,
                client_ref=client_ref,
                error=error,
                method=request.method,
                path=request.url.path,
                trace_id=trace_id,
                payload_json=payload_json,
            )
            session.commit()
    except Exception:
        logger.exception(
            "runtime guard rejection persistence failed: operation=%s auth_surface=%s "
            "site_id=%s key_id=%s trace_id=%s error_code=%s",
            "record_runtime_guard_rejection",
            auth_surface,
            site_id,
            key_id,
            trace_id,
            error.error_code,
        )


async def authorize_request(
    request: Request,
    *,
    settings: Settings,
    database_url: str,
    timestamp_tolerance_seconds: int,
    public_post_rate_limit_window_seconds: int,
    public_post_max_requests_per_window: int,
    public_post_max_requests_per_key_window: int,
    public_post_max_requests_per_ip_window: int,
    public_guard_cooldown_window_seconds: int,
    public_guard_max_reject_events_per_site_window: int,
    public_guard_max_reject_events_per_key_window: int,
    public_guard_max_reject_events_per_ip_window: int,
    require_idempotency: bool,
    required_scope: str | None = None,
    max_body_bytes: int = PUBLIC_RUNTIME_MAX_BODY_BYTES,
) -> RequestAuthContext:
    site_id = ""
    key_id = ""
    timestamp = ""
    traceparent = ""
    trace_id = ""
    nonce = ""
    idempotency_key = ""
    body_digest = ""
    client_scope_id = ""

    try:
        site_id = _require_header(request, "X-Npcink-Site-Id", "auth.site_id_required")
        key_id = _require_header(request, "X-Npcink-Key-Id", "auth.key_id_required")
        timestamp = _require_header(
            request,
            "X-Npcink-Timestamp",
            "auth.timestamp_required",
        )
        traceparent = _require_header(request, "traceparent", "auth.traceparent_required")
        trace_id = extract_trace_id(traceparent)
        if not trace_id:
            raise RequestAuthError(401, "auth.invalid_traceparent", "traceparent header is invalid")

        nonce = request.headers.get(NONCE_HEADER, "").strip()
        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        require_nonce = request.method.upper() == "POST"
        _validate_nonce(nonce, required=require_nonce)
        _validate_idempotency_key(idempotency_key, required=require_idempotency)

        signature = normalize_signature(
            _require_header(request, "X-Npcink-Signature", "auth.signature_required")
        )
        body = await request.body()
        _validate_payload_size(body, max_body_bytes=max_body_bytes)
        body_digest = build_body_digest(body)
        canonical_request = build_canonical_request(
            method=request.method,
            path=request.url.path,
            query=request.url.query,
            site_id=site_id,
            key_id=key_id,
            timestamp=timestamp,
            nonce=nonce,
            idempotency_key=idempotency_key,
            traceparent=traceparent,
            body_digest=body_digest,
        )
        now = datetime.now(UTC)
        _validate_timestamp(
            timestamp,
            now=now,
            tolerance_seconds=timestamp_tolerance_seconds,
        )

        with get_session(database_url) as session:
            site = session.get(Site, site_id)
            api_key = session.get(SiteApiKey, key_id)
            authorized_key = _validate_site_and_key(
                site=site,
                api_key=api_key,
                site_id=site_id,
                key_id=key_id,
                required_scope=required_scope,
                now=now,
            )
            signing_secret = _resolve_site_api_signing_secret(
                authorized_key,
                settings=settings,
            )

            expected_signature = build_hmac_signature(
                signing_secret,
                canonical_request,
            )
            if not hmac.compare_digest(expected_signature, signature):
                raise RequestAuthError(
                    401,
                    "auth.invalid_signature",
                    "request signature is invalid",
                )

            if require_nonce:
                client_scope_id = resolve_client_scope_id(request)
                replay_ttl_seconds = _resolve_replay_receipt_ttl_seconds(
                    timestamp_tolerance_seconds
                )
                cooldown_scopes = [
                    (
                        REPLAY_SCOPE_PUBLIC_POST_SITE,
                        site_id,
                        public_guard_max_reject_events_per_site_window,
                    ),
                    (
                        REPLAY_SCOPE_PUBLIC_POST_KEY,
                        key_id,
                        public_guard_max_reject_events_per_key_window,
                    ),
                    (
                        REPLAY_SCOPE_PUBLIC_POST_IP,
                        client_scope_id,
                        public_guard_max_reject_events_per_ip_window,
                    ),
                ]
                replay_scopes = [
                    (
                        REPLAY_SCOPE_PUBLIC_POST_SITE,
                        site_id,
                        public_post_max_requests_per_window,
                    ),
                    (
                        REPLAY_SCOPE_PUBLIC_POST_KEY,
                        key_id,
                        public_post_max_requests_per_key_window,
                    ),
                    (
                        REPLAY_SCOPE_PUBLIC_POST_IP,
                        client_scope_id,
                        public_post_max_requests_per_ip_window,
                    ),
                ]
                for scope_kind, scope_id, max_events in cooldown_scopes:
                    _enforce_guard_cooldown(
                        session=session,
                        scope_kind=scope_kind,
                        scope_id=scope_id,
                        now=now,
                        window_seconds=public_guard_cooldown_window_seconds,
                        max_events=max_events,
                    )
                for scope_kind, scope_id, max_requests in replay_scopes:
                    _enforce_short_window_rate_limit(
                        session=session,
                        scope_kind=scope_kind,
                        scope_id=scope_id,
                        now=now,
                        window_seconds=public_post_rate_limit_window_seconds,
                        max_requests=max_requests,
                    )
                for scope_kind, scope_id, _ in replay_scopes:
                    if not scope_id:
                        continue
                    _reserve_replay_receipt(
                        session=session,
                        scope_kind=scope_kind,
                        scope_id=scope_id,
                        replay_key=nonce,
                        method=request.method,
                        path=request.url.path,
                        trace_id=trace_id,
                        now=now,
                        ttl_seconds=replay_ttl_seconds,
                    )

            authorized_key.last_used_at = now
            session.commit()
    except RequestAuthError as error:
        _log_auth_rejection(
            request,
            error=error,
            site_id=site_id,
            key_id=key_id,
            trace_id=trace_id,
            required_scope=required_scope,
        )
        record_runtime_guard_rejection(
            database_url=database_url,
            request=request,
            auth_surface=RUNTIME_GUARD_SURFACE_PUBLIC,
            error=error,
            site_id=site_id,
            key_id=key_id,
            trace_id=trace_id,
            required_scope=required_scope,
        )
        raise

    return RequestAuthContext(
        site_id=site_id,
        key_id=key_id,
        trace_id=trace_id,
        traceparent=traceparent,
        nonce=nonce,
        idempotency_key=idempotency_key,
        timestamp=timestamp,
        body_digest=body_digest,
    )


def _resolve_site_api_signing_secret(
    api_key: SiteApiKey,
    *,
    settings: Settings,
) -> str:
    try:
        signing_secret = decrypt_site_api_signing_secret(
            api_key.signing_secret_ciphertext,
            settings=settings,
        )
    except RuntimeError as error:
        raise RequestAuthError(
            401,
            "auth.invalid_key",
            "site api signing secret is unavailable",
        ) from error
    if not signing_secret:
        raise RequestAuthError(
            401,
            "auth.invalid_key",
            "site api signing secret is unavailable",
        )
    return signing_secret
