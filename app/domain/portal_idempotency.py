from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.config import Settings
from app.core.db import get_session
from app.core.models import (
    PORTAL_IDEMPOTENCY_STATE_COMPLETED,
    PORTAL_IDEMPOTENCY_STATE_PROCESSING,
    PortalMutationIdempotencyReceipt,
)
from app.core.secrets import (
    decrypt_portal_idempotency_response,
    encrypt_portal_idempotency_response,
)

PORTAL_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
PORTAL_IDEMPOTENCY_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PORTAL_IDEMPOTENCY_CLEANUP_BATCH_SIZE = 100
PORTAL_IDEMPOTENCY_DEFAULT_MAX_RESPONSE_BYTES = 256 * 1024
_CLAIM_RETRY_LIMIT = 4


@dataclass(frozen=True, slots=True)
class PortalIdempotencyClaim:
    receipt_id: str
    principal_id: str
    idempotency_key: str
    request_fingerprint: str
    claim_token: str
    lease_expires_at: datetime


@dataclass(frozen=True, slots=True)
class PortalIdempotencyReplay:
    status_code: int
    body: bytes


class PortalIdempotencyError(ValueError):
    def __init__(self, status_code: int, error_code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message


def validate_portal_idempotency_key(value: object) -> str:
    key = str(value or "")
    if not key:
        raise PortalIdempotencyError(
            401,
            "auth.idempotency_required",
            "Idempotency-Key header is required",
        )
    if key != key.strip() or not PORTAL_IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
        raise PortalIdempotencyError(
            400,
            "auth.invalid_idempotency_key",
            "Idempotency-Key header contains unsupported characters",
        )
    return key


def build_portal_request_fingerprint(
    *,
    method: str,
    route: str,
    body: object = b"",
    query_string: str = "",
    site_id: str = "",
) -> str:
    body_bytes = _canonical_json_body_bytes(body)
    body_sha256 = hashlib.sha256(body_bytes).hexdigest()
    canonical = json.dumps(
        {
            "body_sha256": body_sha256,
            "method": str(method or "").strip().upper(),
            "path": str(route or "").strip(),
            "query": str(query_string or ""),
            "site_id": str(site_id or "").strip(),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_portal_business_idempotency_key(
    *,
    principal_id: str,
    idempotency_key: str,
) -> str:
    principal = str(principal_id or "").strip()
    key = str(idempotency_key or "")
    if not principal:
        raise ValueError("Portal principal is required for business idempotency")
    if not key:
        raise ValueError("Portal idempotency key is required for business idempotency")
    digest = hashlib.sha256(f"{principal}\0{key}".encode()).hexdigest()
    return f"portal:{digest}"


def cleanup_expired_portal_mutation_receipts(
    *,
    database_url: str,
    now: datetime | None = None,
    batch_size: int = PORTAL_IDEMPOTENCY_CLEANUP_BATCH_SIZE,
) -> int:
    resolved_now = _utc_now(now)
    limit = max(1, min(int(batch_size), PORTAL_IDEMPOTENCY_CLEANUP_BATCH_SIZE))
    with get_session(database_url) as session:
        receipt_ids = list(
            session.scalars(
                select(PortalMutationIdempotencyReceipt.receipt_id)
                .where(
                    PortalMutationIdempotencyReceipt.state
                    == PORTAL_IDEMPOTENCY_STATE_COMPLETED,
                    PortalMutationIdempotencyReceipt.expires_at <= resolved_now,
                )
                .order_by(
                    PortalMutationIdempotencyReceipt.expires_at.asc(),
                    PortalMutationIdempotencyReceipt.receipt_id.asc(),
                )
                .limit(limit)
            )
        )
        if not receipt_ids:
            return 0
        result = session.execute(
            delete(PortalMutationIdempotencyReceipt).where(
                PortalMutationIdempotencyReceipt.receipt_id.in_(receipt_ids)
            )
        )
        session.commit()
        return int(getattr(result, "rowcount", 0) or 0)


def claim_portal_mutation(
    *,
    database_url: str,
    principal_id: str,
    idempotency_key: str,
    method: str,
    route: str,
    request_fingerprint: str,
    now: datetime | None = None,
    lease_seconds: int,
    ttl_seconds: int,
    settings: Settings,
) -> PortalIdempotencyClaim | PortalIdempotencyReplay:
    resolved_now = _utc_now(now)
    key = validate_portal_idempotency_key(idempotency_key)
    resolved_principal_id = str(principal_id or "").strip()
    if not resolved_principal_id:
        raise PortalIdempotencyError(
            401,
            "auth.portal_session_invalid",
            "Portal principal is required",
        )
    fingerprint = str(request_fingerprint or "").strip().lower()
    if not PORTAL_IDEMPOTENCY_FINGERPRINT_PATTERN.fullmatch(fingerprint):
        raise PortalIdempotencyError(
            400,
            "auth.invalid_idempotency_request",
            "Portal mutation request fingerprint is invalid",
        )
    resolved_method = str(method or "").strip().upper()
    resolved_route = str(route or "").strip()
    if (
        not resolved_method
        or len(resolved_method) > 16
        or not resolved_route
        or len(resolved_route) > 512
    ):
        raise PortalIdempotencyError(
            400,
            "auth.invalid_idempotency_request",
            "Portal mutation request target is invalid",
        )
    resolved_lease_seconds = int(lease_seconds)
    resolved_ttl_seconds = int(ttl_seconds)
    if resolved_lease_seconds < 1 or resolved_ttl_seconds <= resolved_lease_seconds:
        raise ValueError("Portal idempotency TTL must exceed the processing lease")

    cleanup_expired_portal_mutation_receipts(
        database_url=database_url,
        now=resolved_now,
    )

    for attempt in range(_CLAIM_RETRY_LIMIT):
        claim_token = uuid4().hex
        lease_expires_at = resolved_now + timedelta(seconds=resolved_lease_seconds)
        expires_at = resolved_now + timedelta(seconds=resolved_ttl_seconds)
        try:
            outcome = _claim_portal_mutation_once(
                database_url=database_url,
                principal_id=resolved_principal_id,
                idempotency_key=key,
                method=resolved_method,
                route=resolved_route,
                request_fingerprint=fingerprint,
                claim_token=claim_token,
                lease_expires_at=lease_expires_at,
                expires_at=expires_at,
                retention_ttl_seconds=resolved_ttl_seconds,
                now=resolved_now,
                settings=settings,
            )
        except OperationalError as error:
            if not _is_retryable_sqlite_lock(database_url, error):
                raise
            if attempt + 1 >= _CLAIM_RETRY_LIMIT:
                raise PortalIdempotencyError(
                    409,
                    "portal.idempotency_in_progress",
                    "A Portal request with this Idempotency-Key is still processing",
                ) from error
            time.sleep(0.01 * (attempt + 1))
            continue
        if outcome is not None:
            return outcome

    raise PortalIdempotencyError(
        409,
        "portal.idempotency_in_progress",
        "A Portal request with this Idempotency-Key is still processing",
    )


def _claim_portal_mutation_once(
    *,
    database_url: str,
    principal_id: str,
    idempotency_key: str,
    method: str,
    route: str,
    request_fingerprint: str,
    claim_token: str,
    lease_expires_at: datetime,
    expires_at: datetime,
    retention_ttl_seconds: int,
    now: datetime,
    settings: Settings,
) -> PortalIdempotencyClaim | PortalIdempotencyReplay | None:
    with get_session(database_url) as session:
        receipt = session.scalar(
            select(PortalMutationIdempotencyReceipt).where(
                PortalMutationIdempotencyReceipt.principal_id == principal_id,
                PortalMutationIdempotencyReceipt.idempotency_key == idempotency_key,
            )
        )
        if receipt is None:
            receipt = PortalMutationIdempotencyReceipt(
                receipt_id=f"pidem_{uuid4().hex}",
                principal_id=principal_id,
                idempotency_key=idempotency_key,
                request_method=method,
                request_path=route,
                request_fingerprint=request_fingerprint,
                state=PORTAL_IDEMPOTENCY_STATE_PROCESSING,
                claim_token=claim_token,
                lease_expires_at=lease_expires_at,
                response_status=None,
                response_body_ciphertext=None,
                retention_ttl_seconds=retention_ttl_seconds,
                expires_at=expires_at,
                completed_at=None,
                created_at=now,
                updated_at=now,
            )
            try:
                with session.begin_nested():
                    session.add(receipt)
                    session.flush()
            except IntegrityError:
                return None
            session.commit()
            return _claim_from_receipt(receipt)

        if receipt.request_fingerprint != request_fingerprint:
            raise PortalIdempotencyError(
                409,
                "portal.idempotency_conflict",
                "Idempotency-Key was already used for a different Portal request",
            )

        if (
            receipt.state == PORTAL_IDEMPOTENCY_STATE_COMPLETED
            and _utc_now(receipt.expires_at) <= now
        ):
            result = session.execute(
                delete(PortalMutationIdempotencyReceipt)
                .where(
                    PortalMutationIdempotencyReceipt.receipt_id == receipt.receipt_id,
                    PortalMutationIdempotencyReceipt.expires_at <= now,
                )
                .execution_options(synchronize_session=False)
            )
            if int(getattr(result, "rowcount", 0) or 0) != 1:
                session.rollback()
                return None
            session.commit()
            return None

        if receipt.state == PORTAL_IDEMPOTENCY_STATE_COMPLETED:
            try:
                response_body = decrypt_portal_idempotency_response(
                    receipt.response_body_ciphertext,
                    settings=settings,
                )
            except RuntimeError as error:
                raise PortalIdempotencyError(
                    503,
                    "portal.idempotency_receipt_unavailable",
                    "Portal idempotency receipt could not be read safely",
                ) from error
            return PortalIdempotencyReplay(
                status_code=int(receipt.response_status or 500),
                body=response_body,
            )

        lease_expiry = _utc_now(receipt.lease_expires_at)
        if lease_expiry > now:
            raise PortalIdempotencyError(
                409,
                "portal.idempotency_in_progress",
                "A Portal request with this Idempotency-Key is still processing",
            )

        raise PortalIdempotencyError(
            409,
            "portal.idempotency_indeterminate",
            "The original Portal request may have completed and requires reconciliation",
        )


def complete_portal_mutation(
    *,
    database_url: str,
    claim: PortalIdempotencyClaim,
    response_status: int,
    response_body_bytes: bytes,
    now: datetime | None = None,
    max_response_bytes: int = PORTAL_IDEMPOTENCY_DEFAULT_MAX_RESPONSE_BYTES,
    settings: Settings,
) -> None:
    status_code = int(response_status)
    if not 100 <= status_code <= 599:
        raise ValueError("Portal idempotency response status must be between 100 and 599")
    raw_response_body = bytes(response_body_bytes)
    if not raw_response_body:
        raise PortalIdempotencyError(
            500,
            "portal.idempotency_response_invalid",
            "Portal mutation response must be bounded JSON",
        )
    try:
        parsed_response_body = json.loads(raw_response_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PortalIdempotencyError(
            500,
            "portal.idempotency_response_invalid",
            "Portal mutation response is not valid JSON",
        ) from error
    if parsed_response_body is None:
        raise PortalIdempotencyError(
            500,
            "portal.idempotency_response_invalid",
            "Portal mutation response must be a non-null JSON value",
        )
    if len(raw_response_body) > int(max_response_bytes):
        raise PortalIdempotencyError(
            500,
            "portal.idempotency_response_too_large",
            "Portal mutation response exceeds the idempotency storage limit",
        )
    response_body_ciphertext = encrypt_portal_idempotency_response(
        raw_response_body,
        settings=settings,
    )

    resolved_now = _utc_now(now)
    with get_session(database_url) as session:
        receipt = session.scalar(
            select(PortalMutationIdempotencyReceipt).where(
                PortalMutationIdempotencyReceipt.receipt_id == claim.receipt_id
            )
        )
        if receipt is None:
            raise PortalIdempotencyError(
                409,
                "portal.idempotency_in_progress",
                "Portal idempotency claim is no longer available",
            )
        expires_at = resolved_now + timedelta(
            seconds=int(receipt.retention_ttl_seconds)
        )
        result = session.execute(
            update(PortalMutationIdempotencyReceipt)
            .where(
                PortalMutationIdempotencyReceipt.receipt_id == claim.receipt_id,
                PortalMutationIdempotencyReceipt.principal_id == claim.principal_id,
                PortalMutationIdempotencyReceipt.idempotency_key
                == claim.idempotency_key,
                PortalMutationIdempotencyReceipt.request_fingerprint
                == claim.request_fingerprint,
                PortalMutationIdempotencyReceipt.state
                == PORTAL_IDEMPOTENCY_STATE_PROCESSING,
                PortalMutationIdempotencyReceipt.claim_token == claim.claim_token,
            )
            .execution_options(synchronize_session=False)
            .values(
                state=PORTAL_IDEMPOTENCY_STATE_COMPLETED,
                claim_token=None,
                lease_expires_at=None,
                response_status=status_code,
                response_body_ciphertext=response_body_ciphertext,
                expires_at=expires_at,
                completed_at=resolved_now,
                updated_at=resolved_now,
            )
        )
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            session.rollback()
            raise PortalIdempotencyError(
                409,
                "portal.idempotency_in_progress",
                "Portal idempotency claim ownership changed before completion",
            )
        session.commit()


def _claim_from_receipt(
    receipt: PortalMutationIdempotencyReceipt,
) -> PortalIdempotencyClaim:
    return PortalIdempotencyClaim(
        receipt_id=receipt.receipt_id,
        principal_id=receipt.principal_id,
        idempotency_key=receipt.idempotency_key,
        request_fingerprint=receipt.request_fingerprint,
        claim_token=str(receipt.claim_token or ""),
        lease_expires_at=_utc_now(receipt.lease_expires_at),
    )


def _utc_now(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(UTC)
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=UTC)
    return resolved.astimezone(UTC)


def _canonical_json_body_bytes(body: object) -> bytes:
    candidate: object
    if isinstance(body, (bytes, bytearray)):
        raw = bytes(body)
        if not raw:
            return b""
        try:
            candidate = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PortalIdempotencyError(
                400,
                "auth.invalid_idempotency_request",
                "Portal mutation request body is not valid JSON",
            ) from error
    else:
        candidate = body
    try:
        return json.dumps(
            candidate,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise PortalIdempotencyError(
            400,
            "auth.invalid_idempotency_request",
            "Portal mutation request body is not valid JSON",
        ) from error


def _is_retryable_sqlite_lock(database_url: str, error: OperationalError) -> bool:
    return database_url.startswith("sqlite") and "database is locked" in str(error).lower()
