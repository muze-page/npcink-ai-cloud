from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterable

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings


def resolve_provider_connection_secret(settings: Settings) -> str:
    secret = str(settings.provider_connection_secret or "").strip()
    if secret:
        return secret

    environment = str(settings.environment or "").strip().lower()
    if environment in {"development", "test"} and settings.allow_dev_provider_connection_secret_fallback:
        return _resolve_encryption_secret(
            (
                settings.admin_session_secret,
                settings.portal_jwt_secret,
                settings.internal_auth_token,
            ),
            error_message="provider connection secret is not configured",
        )

    raise RuntimeError("provider connection secret is not configured")


def resolve_runtime_terminal_callback_secret(settings: Settings) -> str:
    return _resolve_encryption_secret(
        (
            settings.provider_connection_secret,
            settings.admin_session_secret,
            settings.portal_jwt_secret,
            settings.internal_auth_token,
        ),
        error_message="runtime terminal callback secret is not configured",
    )


def encrypt_runtime_terminal_callback_secret(secret: str, *, settings: Settings) -> str:
    normalized = str(secret or "")
    if not normalized:
        return ""
    return _build_fernet(
        resolve_runtime_terminal_callback_secret(settings),
        purpose="runtime_terminal_callback_secret",
    ).encrypt(normalized.encode("utf-8")).decode("utf-8")


def decrypt_runtime_terminal_callback_secret(ciphertext: str | None, *, settings: Settings) -> str:
    token = str(ciphertext or "").strip()
    if not token:
        return ""
    try:
        return _build_fernet(
            resolve_runtime_terminal_callback_secret(settings),
            purpose="runtime_terminal_callback_secret",
        ).decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as error:
        raise RuntimeError("runtime terminal callback secret could not be decrypted") from error


def encrypt_site_api_signing_secret(secret: str, *, settings: Settings) -> str:
    normalized = str(secret or "")
    if not normalized:
        return ""
    return _build_fernet(
        resolve_provider_connection_secret(settings),
        purpose="site_api_key_signing_secret",
    ).encrypt(normalized.encode("utf-8")).decode("utf-8")


def decrypt_site_api_signing_secret(ciphertext: str | None, *, settings: Settings) -> str:
    token = str(ciphertext or "").strip()
    if not token:
        return ""
    try:
        return _build_fernet(
            resolve_provider_connection_secret(settings),
            purpose="site_api_key_signing_secret",
        ).decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as error:
        raise RuntimeError("site api signing secret could not be decrypted") from error


def encrypt_runtime_execution_input(
    input_payload: dict[str, object],
    *,
    settings: Settings,
) -> str:
    payload = json.dumps(input_payload, separators=(",", ":"), sort_keys=True)
    return _build_fernet(
        resolve_runtime_terminal_callback_secret(settings),
        purpose="runtime_execution_input",
    ).encrypt(payload.encode("utf-8")).decode("utf-8")


def decrypt_runtime_execution_input(
    ciphertext: str | None,
    *,
    settings: Settings,
) -> dict[str, object]:
    token = str(ciphertext or "").strip()
    if not token:
        return {}
    try:
        payload = _build_fernet(
            resolve_runtime_terminal_callback_secret(settings),
            purpose="runtime_execution_input",
        ).decrypt(token.encode("utf-8"))
    except InvalidToken as error:
        raise RuntimeError("runtime execution input could not be decrypted") from error

    try:
        decoded = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError("runtime execution input is not valid json") from error
    return decoded if isinstance(decoded, dict) else {}


def resolve_provider_connection_secret_strict(settings: Settings) -> str:
    secret = str(settings.provider_connection_secret or "").strip()
    if secret:
        return secret
    raise RuntimeError("provider connection secret is not configured")


def _resolve_encryption_secret(
    candidates: Iterable[str | None],
    *,
    error_message: str,
) -> str:
    for candidate in candidates:
        secret = str(candidate or "").strip()
        if secret:
            return secret
    raise RuntimeError(error_message)


def encrypt_provider_connection_secret(secret: str, *, settings: Settings) -> str:
    normalized = str(secret or "")
    if not normalized:
        return ""
    return _build_provider_fernet(settings).encrypt(normalized.encode("utf-8")).decode("utf-8")


def decrypt_provider_connection_secret(ciphertext: str | None, *, settings: Settings) -> str:
    token = str(ciphertext or "").strip()
    if not token:
        return ""
    try:
        return _build_provider_fernet(settings).decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as error:
        raise RuntimeError("provider connection secret could not be decrypted") from error


def _build_provider_fernet(settings: Settings) -> Fernet:
    signing_secret = resolve_provider_connection_secret(settings)
    return _build_fernet(signing_secret, purpose="provider_connection_secret")


def _build_fernet(signing_secret: str, *, purpose: str) -> Fernet:
    derived_key = hashlib.sha256(f"{purpose}:{signing_secret}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived_key))
