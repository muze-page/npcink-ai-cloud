from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

RuntimeDataGuardKind = Literal["secret", "pii"]

SECRET_FIELD_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "auth_header",
        "authorization",
        "bearer_token",
        "callback_secret",
        "client_secret",
        "cloud_secret",
        "confirm_token",
        "password",
        "private_key",
        "provider_key",
        "provider_secret",
        "refresh_token",
        "secret",
        "token",
        "webhook_secret",
        "wordpress_password",
        "wordpress_secret",
    }
)
SECRET_FIELD_KEY_COMPACTS = frozenset(key.replace("_", "") for key in SECRET_FIELD_KEYS)

SECRET_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bmak1_[A-Za-z0-9_-]{16,}\b"),
)

PII_VALUE_PATTERNS = (
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"),
    re.compile(
        r"\b[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])"
        r"(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b"
    ),
)


@dataclass(frozen=True, slots=True)
class RuntimeDataGuardFinding:
    kind: RuntimeDataGuardKind
    path: str
    code: str


def find_runtime_data_guard_finding(
    value: Any,
    *,
    path: str = "input",
) -> RuntimeDataGuardFinding | None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key or "").strip()
            current_path = f"{path}.{key_text}" if key_text else path
            if _is_secret_field_key(key_text):
                return RuntimeDataGuardFinding(
                    kind="secret",
                    path=current_path,
                    code="secret_field",
                )
            nested = find_runtime_data_guard_finding(item, path=current_path)
            if nested is not None:
                return nested
        return None

    if isinstance(value, list):
        for index, item in enumerate(value):
            nested = find_runtime_data_guard_finding(item, path=f"{path}[{index}]")
            if nested is not None:
                return nested
        return None

    if isinstance(value, str):
        if _contains_secret_value(value):
            return RuntimeDataGuardFinding(kind="secret", path=path, code="secret_value")
        if _contains_pii_value(value):
            return RuntimeDataGuardFinding(kind="pii", path=path, code="pii_value")

    return None


def _is_secret_field_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
    compact = normalized.replace("_", "")
    return normalized in SECRET_FIELD_KEYS or compact in SECRET_FIELD_KEY_COMPACTS


def _contains_secret_value(value: str) -> bool:
    if not value:
        return False
    return any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS)


def _contains_pii_value(value: str) -> bool:
    if not value:
        return False
    return any(pattern.search(value) for pattern in PII_VALUE_PATTERNS)
