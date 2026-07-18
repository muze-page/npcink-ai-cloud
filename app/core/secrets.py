from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterable

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings

RUNTIME_DATA_ENVELOPE_FAMILY = "rde"
RUNTIME_DATA_ENVELOPE_VERSION = "v1"


def resolve_runtime_data_encryption_secret(settings: Settings) -> str:
    return _resolve_encryption_secret(
        (settings.runtime_data_encryption_secret,),
        error_message="runtime data encryption secret is not configured",
    )


def encrypt_runtime_terminal_callback_secret(secret: str, *, settings: Settings) -> str:
    normalized = str(secret or "")
    if not normalized:
        return ""
    return encrypt_runtime_data_plaintext(
        normalized.encode("utf-8"),
        purpose="runtime_terminal_callback_secret",
        settings=settings,
    )


def decrypt_runtime_terminal_callback_secret(ciphertext: str | None, *, settings: Settings) -> str:
    token = str(ciphertext or "").strip()
    if not token:
        return ""
    return decrypt_runtime_data_plaintext(
        token,
        purpose="runtime_terminal_callback_secret",
        settings=settings,
        error_message="runtime terminal callback secret could not be decrypted",
    ).decode("utf-8")


def encrypt_site_api_signing_secret(secret: str, *, settings: Settings) -> str:
    normalized = str(secret or "")
    if not normalized:
        return ""
    return encrypt_runtime_data_plaintext(
        normalized.encode("utf-8"),
        purpose="site_api_key_signing_secret",
        settings=settings,
    )


def decrypt_site_api_signing_secret(ciphertext: str | None, *, settings: Settings) -> str:
    token = str(ciphertext or "").strip()
    if not token:
        return ""
    return decrypt_runtime_data_plaintext(
        token,
        purpose="site_api_key_signing_secret",
        settings=settings,
        error_message="site api signing secret could not be decrypted",
    ).decode("utf-8")


def encrypt_addon_connection_payload(
    payload: dict[str, object],
    *,
    settings: Settings,
) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return encrypt_runtime_data_plaintext(
        encoded.encode("utf-8"),
        purpose="wordpress_addon_connection_payload",
        settings=settings,
    )


def decrypt_addon_connection_payload(
    ciphertext: str | None,
    *,
    settings: Settings,
) -> dict[str, object]:
    token = str(ciphertext or "").strip()
    if not token:
        return {}
    decoded = decrypt_runtime_data_plaintext(
        token,
        purpose="wordpress_addon_connection_payload",
        settings=settings,
        error_message="addon connection payload could not be decrypted",
    ).decode("utf-8")
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError as error:
        raise RuntimeError("addon connection payload is not valid json") from error
    return payload if isinstance(payload, dict) else {}


def encrypt_portal_idempotency_response(
    response_body: bytes,
    *,
    settings: Settings,
) -> str:
    return encrypt_runtime_data_plaintext(
        bytes(response_body),
        purpose="portal_idempotency_response",
        settings=settings,
    )


def decrypt_portal_idempotency_response(
    ciphertext: str | None,
    *,
    settings: Settings,
) -> bytes:
    token = str(ciphertext or "").strip()
    if not token:
        raise RuntimeError("Portal idempotency response is missing")
    return decrypt_runtime_data_plaintext(
        token,
        purpose="portal_idempotency_response",
        settings=settings,
        error_message="Portal idempotency response could not be decrypted",
    )


def encrypt_runtime_execution_input(
    input_payload: dict[str, object],
    *,
    settings: Settings,
) -> str:
    payload = json.dumps(input_payload, separators=(",", ":"), sort_keys=True)
    return encrypt_runtime_data_plaintext(
        payload.encode("utf-8"),
        purpose="runtime_execution_input",
        settings=settings,
    )


def decrypt_runtime_execution_input(
    ciphertext: str | None,
    *,
    settings: Settings,
) -> dict[str, object]:
    token = str(ciphertext or "").strip()
    if not token:
        return {}
    payload = decrypt_runtime_data_plaintext(
        token,
        purpose="runtime_execution_input",
        settings=settings,
        error_message="runtime execution input could not be decrypted",
    )

    try:
        decoded = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError("runtime execution input is not valid json") from error
    return decoded if isinstance(decoded, dict) else {}


def encrypt_provider_connection_secret(secret: str, *, settings: Settings) -> str:
    normalized = str(secret or "")
    if not normalized:
        return ""
    return (
        _build_fernet(
            _resolve_encryption_secret(
                (settings.service_settings_secret,),
                error_message="provider connection secret is not configured",
            ),
            purpose="provider_connection_secret",
        )
        .encrypt(normalized.encode("utf-8"))
        .decode("utf-8")
    )


def decrypt_provider_connection_secret(ciphertext: str | None, *, settings: Settings) -> str:
    token = str(ciphertext or "").strip()
    if not token:
        return ""
    try:
        return (
            _build_fernet(
                _resolve_encryption_secret(
                    (settings.service_settings_secret,),
                    error_message="provider connection secret is not configured",
                ),
                purpose="provider_connection_secret",
            )
            .decrypt(token.encode("utf-8"))
            .decode("utf-8")
        )
    except InvalidToken as error:
        raise RuntimeError("provider connection secret could not be decrypted") from error


def encrypt_service_setting_secret(secret: str, *, settings: Settings) -> str:
    normalized = str(secret or "")
    if not normalized:
        return ""
    return (
        _build_fernet(
            _resolve_encryption_secret(
                (settings.service_settings_secret,),
                error_message="service setting secret is not configured",
            ),
            purpose="service_setting_secret",
        )
        .encrypt(normalized.encode("utf-8"))
        .decode("utf-8")
    )


def decrypt_service_setting_secret(ciphertext: str | None, *, settings: Settings) -> str:
    token = str(ciphertext or "").strip()
    if not token:
        return ""
    secret = _resolve_encryption_secret(
        (settings.service_settings_secret,),
        error_message="service setting secret is not configured",
    )
    try:
        return (
            _build_fernet(secret, purpose="service_setting_secret")
            .decrypt(token.encode("utf-8"))
            .decode("utf-8")
        )
    except InvalidToken as error:
        raise RuntimeError("service setting secret could not be decrypted") from error


def encrypt_runtime_data_plaintext(
    plaintext: bytes,
    *,
    purpose: str,
    settings: Settings,
) -> str:
    secret = resolve_runtime_data_encryption_secret(settings)
    key_id = _resolve_runtime_data_encryption_key_id(settings)
    token = _build_fernet(secret, purpose=purpose).encrypt(bytes(plaintext)).decode("utf-8")
    return f"{RUNTIME_DATA_ENVELOPE_FAMILY}.{RUNTIME_DATA_ENVELOPE_VERSION}.{key_id}.{token}"


def decrypt_runtime_data_plaintext(
    ciphertext: str,
    *,
    purpose: str,
    settings: Settings,
    error_message: str = "runtime data ciphertext could not be decrypted",
) -> bytes:
    token = str(ciphertext or "").strip()
    expected_key_id = _resolve_runtime_data_encryption_key_id(settings)
    try:
        family, version, key_id, fernet_token = token.split(".", 3)
    except ValueError as error:
        raise RuntimeError(error_message) from error
    if (
        family != RUNTIME_DATA_ENVELOPE_FAMILY
        or version != RUNTIME_DATA_ENVELOPE_VERSION
        or key_id != expected_key_id
        or not fernet_token
    ):
        raise RuntimeError(error_message)
    try:
        return _build_fernet(
            resolve_runtime_data_encryption_secret(settings),
            purpose=purpose,
        ).decrypt(fernet_token.encode("utf-8"))
    except InvalidToken as error:
        raise RuntimeError(error_message) from error


def runtime_data_envelope_key_id(ciphertext: str | None) -> str | None:
    token = str(ciphertext or "").strip()
    try:
        family, version, key_id, fernet_token = token.split(".", 3)
    except ValueError:
        return None
    if (
        family != RUNTIME_DATA_ENVELOPE_FAMILY
        or version != RUNTIME_DATA_ENVELOPE_VERSION
        or not key_id
        or not fernet_token
    ):
        return None
    return key_id


def _resolve_runtime_data_encryption_key_id(settings: Settings) -> str:
    key_id = str(settings.runtime_data_encryption_key_id or "").strip()
    if not key_id:
        raise RuntimeError("runtime data encryption key id is not configured")
    return key_id


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


def _build_fernet(signing_secret: str, *, purpose: str) -> Fernet:
    derived_key = hashlib.sha256(f"{purpose}:{signing_secret}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived_key))
