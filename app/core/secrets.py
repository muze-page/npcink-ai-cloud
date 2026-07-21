from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Iterable

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import Settings

RUNTIME_DATA_ENVELOPE_FAMILY = "rde"
RUNTIME_DATA_ENVELOPE_VERSION = "v1"
SERVICE_SECRET_ENVELOPE_FAMILY = "sse"
SERVICE_SECRET_ENVELOPE_VERSION = "v1"

_ENVELOPE_KEY_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
_ENCRYPTION_PURPOSE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_ENVELOPE_FAMILY_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_ENVELOPE_VERSION_PATTERN = re.compile(r"v[1-9][0-9]{0,9}")
_CANONICAL_32_BYTE_ROOT_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}=")
_KDF_SALT = b"npcink-ai-cloud:fernet-envelope-kdf:v1"
_KDF_CONTEXT = b"npcink-ai-cloud:fernet-envelope-context:v1"


def resolve_runtime_data_encryption_secret(settings: Settings) -> str:
    return _resolve_encryption_root(
        (settings.runtime_data_encryption_secret,),
        error_message="runtime data encryption secret is not configured",
        root_name="runtime data encryption secret",
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
    token = str(ciphertext or "")
    if not token.strip():
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
    token = str(ciphertext or "")
    if not token.strip():
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
    token = str(ciphertext or "")
    if not token.strip():
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
    token = str(ciphertext or "")
    if not token.strip():
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
    token = str(ciphertext or "")
    if not token.strip():
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
    return _encrypt_service_secret_plaintext(
        normalized.encode("utf-8"),
        purpose="provider_connection_secret",
        settings=settings,
        missing_root_message="provider connection secret is not configured",
    )


def decrypt_provider_connection_secret(ciphertext: str | None, *, settings: Settings) -> str:
    token = str(ciphertext or "")
    if not token.strip():
        return ""
    return _decrypt_service_secret_plaintext(
        token,
        purpose="provider_connection_secret",
        settings=settings,
        missing_root_message="provider connection secret is not configured",
        error_message="provider connection secret could not be decrypted",
    ).decode("utf-8")


def encrypt_service_setting_secret(secret: str, *, settings: Settings) -> str:
    normalized = str(secret or "")
    if not normalized:
        return ""
    return _encrypt_service_secret_plaintext(
        normalized.encode("utf-8"),
        purpose="service_setting_secret",
        settings=settings,
        missing_root_message="service setting secret is not configured",
    )


def decrypt_service_setting_secret(ciphertext: str | None, *, settings: Settings) -> str:
    token = str(ciphertext or "")
    if not token.strip():
        return ""
    return _decrypt_service_secret_plaintext(
        token,
        purpose="service_setting_secret",
        settings=settings,
        missing_root_message="service setting secret is not configured",
        error_message="service setting secret could not be decrypted",
    ).decode("utf-8")


def encrypt_runtime_data_plaintext(
    plaintext: bytes,
    *,
    purpose: str,
    settings: Settings,
) -> str:
    secret = resolve_runtime_data_encryption_secret(settings)
    key_id = _resolve_runtime_data_encryption_key_id(settings)
    token = (
        _build_fernet(
            secret,
            family=RUNTIME_DATA_ENVELOPE_FAMILY,
            version=RUNTIME_DATA_ENVELOPE_VERSION,
            purpose=purpose,
            key_id=key_id,
            root_name="runtime data encryption secret",
        )
        .encrypt(bytes(plaintext))
        .decode("utf-8")
    )
    return f"{RUNTIME_DATA_ENVELOPE_FAMILY}.{RUNTIME_DATA_ENVELOPE_VERSION}.{key_id}.{token}"


def decrypt_runtime_data_plaintext(
    ciphertext: str,
    *,
    purpose: str,
    settings: Settings,
    error_message: str = "runtime data ciphertext could not be decrypted",
) -> bytes:
    token = str(ciphertext or "")
    expected_key_id = _resolve_runtime_data_encryption_key_id(settings)
    parsed = _parse_envelope(
        token,
        family=RUNTIME_DATA_ENVELOPE_FAMILY,
        version=RUNTIME_DATA_ENVELOPE_VERSION,
    )
    if parsed is None or parsed[0] != expected_key_id:
        raise RuntimeError(error_message)
    key_id, fernet_token = parsed
    try:
        return _build_fernet(
            resolve_runtime_data_encryption_secret(settings),
            family=RUNTIME_DATA_ENVELOPE_FAMILY,
            version=RUNTIME_DATA_ENVELOPE_VERSION,
            purpose=purpose,
            key_id=key_id,
            root_name="runtime data encryption secret",
        ).decrypt(fernet_token.encode("utf-8"))
    except InvalidToken as error:
        raise RuntimeError(error_message) from error


def runtime_data_envelope_key_id(ciphertext: str | None) -> str | None:
    parsed = _parse_envelope(
        str(ciphertext or ""),
        family=RUNTIME_DATA_ENVELOPE_FAMILY,
        version=RUNTIME_DATA_ENVELOPE_VERSION,
    )
    return parsed[0] if parsed is not None else None


def service_secret_envelope_key_id(ciphertext: str | None) -> str | None:
    parsed = _parse_envelope(
        str(ciphertext or ""),
        family=SERVICE_SECRET_ENVELOPE_FAMILY,
        version=SERVICE_SECRET_ENVELOPE_VERSION,
    )
    return parsed[0] if parsed is not None else None


def _resolve_runtime_data_encryption_key_id(settings: Settings) -> str:
    return _resolve_encryption_key_id(
        settings.runtime_data_encryption_key_id,
        missing_message="runtime data encryption key id is not configured",
        invalid_message="runtime data encryption key id is invalid",
    )


def _resolve_service_settings_encryption_key_id(settings: Settings) -> str:
    return _resolve_encryption_key_id(
        settings.service_settings_encryption_key_id,
        missing_message="service settings encryption key id is not configured",
        invalid_message="service settings encryption key id is invalid",
    )


def _resolve_encryption_key_id(
    raw_key_id: str | None,
    *,
    missing_message: str,
    invalid_message: str,
) -> str:
    key_id = str(raw_key_id or "")
    if not key_id:
        raise RuntimeError(missing_message)
    if key_id != key_id.strip() or _ENVELOPE_KEY_ID_PATTERN.fullmatch(key_id) is None:
        raise RuntimeError(invalid_message)
    return key_id


def _resolve_encryption_secret(
    candidates: Iterable[str | None],
    *,
    error_message: str,
) -> str:
    for candidate in candidates:
        secret = str(candidate or "")
        if secret.strip():
            return secret
    raise RuntimeError(error_message)


def _resolve_encryption_root(
    candidates: Iterable[str | None],
    *,
    error_message: str,
    root_name: str,
) -> str:
    root_secret = _resolve_encryption_secret(candidates, error_message=error_message)
    _decode_encryption_root(root_secret, root_name=root_name)
    return root_secret


def _decode_encryption_root(root_secret: str, *, root_name: str) -> bytes:
    encoded = str(root_secret or "")
    if (
        encoded != encoded.strip()
        or _CANONICAL_32_BYTE_ROOT_PATTERN.fullmatch(encoded) is None
    ):
        raise RuntimeError(
            f"{root_name} must be canonical URL-safe Base64 encoding of exactly 32 bytes"
        )
    try:
        decoded = base64.b64decode(encoded.encode("ascii"), altchars=b"-_", validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as error:
        raise RuntimeError(
            f"{root_name} must be canonical URL-safe Base64 encoding of exactly 32 bytes"
        ) from error
    if len(decoded) != 32 or base64.urlsafe_b64encode(decoded).decode("ascii") != encoded:
        raise RuntimeError(
            f"{root_name} must be canonical URL-safe Base64 encoding of exactly 32 bytes"
        )
    return decoded


def _validate_kdf_component(value: str, *, component: str) -> str:
    normalized = str(value or "")
    patterns = {
        "family": _ENVELOPE_FAMILY_PATTERN,
        "version": _ENVELOPE_VERSION_PATTERN,
        "purpose": _ENCRYPTION_PURPOSE_PATTERN,
        "key id": _ENVELOPE_KEY_ID_PATTERN,
    }
    pattern = patterns[component]
    if normalized != normalized.strip() or pattern.fullmatch(normalized) is None:
        raise RuntimeError(f"encryption {component} is invalid")
    return normalized


def _derive_fernet_key(
    root_secret: str,
    *,
    family: str,
    version: str,
    purpose: str,
    key_id: str,
    root_name: str = "encryption root",
) -> bytes:
    root = _decode_encryption_root(root_secret, root_name=root_name)
    normalized_family = _validate_kdf_component(family, component="family")
    normalized_version = _validate_kdf_component(version, component="version")
    normalized_purpose = _validate_kdf_component(purpose, component="purpose")
    normalized_key_id = _validate_kdf_component(key_id, component="key id")
    info = b"\x00".join(
        (
            _KDF_CONTEXT,
            f"family={normalized_family}".encode("ascii"),
            f"version={normalized_version}".encode("ascii"),
            f"purpose={normalized_purpose}".encode("ascii"),
            f"key_id={normalized_key_id}".encode("ascii"),
        )
    )
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_KDF_SALT,
        info=info,
    ).derive(root)


def _build_fernet(
    root_secret: str,
    *,
    family: str,
    version: str,
    purpose: str,
    key_id: str,
    root_name: str,
) -> Fernet:
    derived_key = _derive_fernet_key(
        root_secret,
        family=family,
        version=version,
        purpose=purpose,
        key_id=key_id,
        root_name=root_name,
    )
    return Fernet(base64.urlsafe_b64encode(derived_key))


def _encrypt_service_secret_plaintext(
    plaintext: bytes,
    *,
    purpose: str,
    settings: Settings,
    missing_root_message: str,
) -> str:
    root_secret = _resolve_encryption_root(
        (settings.service_settings_secret,),
        error_message=missing_root_message,
        root_name="service settings encryption secret",
    )
    key_id = _resolve_service_settings_encryption_key_id(settings)
    token = (
        _build_fernet(
            root_secret,
            family=SERVICE_SECRET_ENVELOPE_FAMILY,
            version=SERVICE_SECRET_ENVELOPE_VERSION,
            purpose=purpose,
            key_id=key_id,
            root_name="service settings encryption secret",
        )
        .encrypt(bytes(plaintext))
        .decode("utf-8")
    )
    return f"{SERVICE_SECRET_ENVELOPE_FAMILY}.{SERVICE_SECRET_ENVELOPE_VERSION}.{key_id}.{token}"


def _decrypt_service_secret_plaintext(
    ciphertext: str,
    *,
    purpose: str,
    settings: Settings,
    missing_root_message: str,
    error_message: str,
) -> bytes:
    expected_key_id = _resolve_service_settings_encryption_key_id(settings)
    parsed = _parse_envelope(
        ciphertext,
        family=SERVICE_SECRET_ENVELOPE_FAMILY,
        version=SERVICE_SECRET_ENVELOPE_VERSION,
    )
    if parsed is None or parsed[0] != expected_key_id:
        raise RuntimeError(error_message)
    key_id, fernet_token = parsed
    root_secret = _resolve_encryption_root(
        (settings.service_settings_secret,),
        error_message=missing_root_message,
        root_name="service settings encryption secret",
    )
    try:
        return _build_fernet(
            root_secret,
            family=SERVICE_SECRET_ENVELOPE_FAMILY,
            version=SERVICE_SECRET_ENVELOPE_VERSION,
            purpose=purpose,
            key_id=key_id,
            root_name="service settings encryption secret",
        ).decrypt(fernet_token.encode("utf-8"))
    except InvalidToken as error:
        raise RuntimeError(error_message) from error


def _parse_envelope(
    ciphertext: str,
    *,
    family: str,
    version: str,
) -> tuple[str, str] | None:
    token = str(ciphertext or "")
    if token != token.strip():
        return None
    try:
        actual_family, actual_version, key_id, fernet_token = token.split(".", 3)
    except ValueError:
        return None
    if (
        actual_family != family
        or actual_version != version
        or _ENVELOPE_KEY_ID_PATTERN.fullmatch(key_id) is None
        or not fernet_token
    ):
        return None
    return key_id, fernet_token
