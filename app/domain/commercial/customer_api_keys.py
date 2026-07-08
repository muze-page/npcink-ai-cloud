from __future__ import annotations

import base64
import json

from app.domain.commercial.errors import CommercialValidationError

DEFAULT_PORTAL_RUNTIME_SCOPES: list[str] = [
    "catalog:read",
    "runtime:resolve",
    "runtime:execute",
    "runtime:read",
    "stats:read",
    "entitlement:read",
]

ALLOWED_PORTAL_RUNTIME_SCOPES: frozenset[str] = frozenset(DEFAULT_PORTAL_RUNTIME_SCOPES)


def build_customer_api_key(*, site_id: str, key_id: str, secret: str) -> str:
    payload = {
        "site_id": str(site_id or ""),
        "key_id": str(key_id or ""),
        "secret": str(secret or ""),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return f"mak1_{encoded.rstrip('=')}"


def serialize_portal_site_key(
    key_payload: dict[str, object],
    *,
    cloud_api_key: str | None = None,
) -> dict[str, object]:
    return {
        "site_id": str(key_payload.get("site_id") or ""),
        "key_id": str(key_payload.get("key_id") or ""),
        "label": str(key_payload.get("label") or ""),
        "status": str(key_payload.get("status") or ""),
        "scopes": _string_list(key_payload.get("scopes")),
        "last_four": _last_four(str(key_payload.get("key_id") or "")),
        "issued_at": str(key_payload.get("created_at") or ""),
        "created_at": str(key_payload.get("created_at") or ""),
        "expires_at": key_payload.get("expires_at"),
        "last_used_at": key_payload.get("last_used_at"),
        **({"cloud_api_key": cloud_api_key} if cloud_api_key else {}),
    }


def _last_four(value: str) -> str:
    normalized = str(value or "")
    return normalized[-4:] if normalized else ""


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def expand_api_key_scopes(scopes: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_scope in list(scopes or []):
        scope = str(raw_scope or "").strip()
        if not scope:
            continue
        if scope in seen:
            continue
        seen.add(scope)
        normalized.append(scope)
    return normalized


def validate_api_key_scopes_for_issue(scopes: list[str] | None) -> list[str]:
    normalized = expand_api_key_scopes(scopes)
    for scope in normalized:
        if scope not in ALLOWED_PORTAL_RUNTIME_SCOPES:
            raise CommercialValidationError(
                "service.site_key_scope_invalid",
                f"site key scope '{scope}' is not allowed",
            )
    return normalized
