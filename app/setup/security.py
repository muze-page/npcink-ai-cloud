from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Request
from jwt import InvalidTokenError

from app.setup.errors import SetupError
from app.setup.state import SetupAuth

SETUP_COOKIE_NAME = "npcink_setup_session"
SETUP_SESSION_ALGORITHM = "HS256"
SETUP_SESSION_ISSUER = "npcink-ai-cloud"
SETUP_SESSION_AUDIENCE = "npcink-ai-cloud-setup"
SETUP_SESSION_PURPOSE = "first_install"
SETUP_SESSION_TTL_SECONDS = 15 * 60
SETUP_RATE_LIMIT_WINDOW_SECONDS = 15 * 60
SETUP_RATE_LIMIT_MAX_FAILURES = 5


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_prefixed_secret(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


def generate_root_secret() -> str:
    import base64

    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")


def resolve_setup_source_ip(request: Request) -> str:
    real_ip = str(request.headers.get("x-real-ip") or "").strip()
    if real_ip:
        try:
            return ipaddress.ip_address(real_ip).compressed
        except ValueError:
            pass
    client_host = str(request.client.host if request.client is not None else "").strip()
    try:
        return ipaddress.ip_address(client_host).compressed
    except ValueError:
        return "unknown"


class SetupAttemptLimiter:
    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def ensure_allowed(self, source_ip: str, *, now: float | None = None) -> None:
        timestamp = time.monotonic() if now is None else now
        with self._lock:
            failures = self._failures[source_ip]
            self._discard_expired(failures, timestamp)
            if len(failures) >= SETUP_RATE_LIMIT_MAX_FAILURES:
                raise SetupError(429, "setup.rate_limited", "too many setup attempts")

    def record_failure(self, source_ip: str, *, now: float | None = None) -> None:
        timestamp = time.monotonic() if now is None else now
        with self._lock:
            failures = self._failures[source_ip]
            self._discard_expired(failures, timestamp)
            failures.append(timestamp)

    def clear(self, source_ip: str) -> None:
        with self._lock:
            self._failures.pop(source_ip, None)

    @staticmethod
    def _discard_expired(failures: deque[float], now: float) -> None:
        cutoff = now - SETUP_RATE_LIMIT_WINDOW_SECONDS
        while failures and failures[0] <= cutoff:
            failures.popleft()


def verify_setup_code(auth: SetupAuth, setup_code: str) -> bool:
    return hmac.compare_digest(sha256_text(setup_code), auth.setup_code_sha256)


def build_setup_session_token(auth: SetupAuth) -> str:
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=SETUP_SESSION_TTL_SECONDS)
    return jwt.encode(
        {
            "iss": SETUP_SESSION_ISSUER,
            "aud": SETUP_SESSION_AUDIENCE,
            "purpose": SETUP_SESSION_PURPOSE,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        },
        auth.session_secret,
        algorithm=SETUP_SESSION_ALGORITHM,
    )


def verify_setup_session_token(auth: SetupAuth, token: str) -> None:
    try:
        payload = jwt.decode(
            token,
            auth.session_secret,
            algorithms=[SETUP_SESSION_ALGORITHM],
            issuer=SETUP_SESSION_ISSUER,
            audience=SETUP_SESSION_AUDIENCE,
            options={"require": ["iss", "aud", "purpose", "iat", "exp"]},
        )
    except (InvalidTokenError, TypeError, ValueError) as error:
        raise SetupError(401, "setup.session_required", "setup session is required") from error
    if payload.get("purpose") != SETUP_SESSION_PURPOSE:
        raise SetupError(401, "setup.session_required", "setup session is required")
