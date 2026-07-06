from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from app.api.auth import PortalBearerTokenError, get_cloud_services
from app.api.portal_session import (
    get_commercial_service,
)
from app.core.models import PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN


@dataclass(frozen=True)
class ResolvedAdminSession:
    principal_id: str
    role: str
    auth_mode: str
    revocable: bool
    session_version: int

    @classmethod
    def from_identity(
        cls,
        identity: Mapping[str, object],
        *,
        auth_mode: str,
        fallback_principal_id: str = "",
        fallback_role: str = PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
    ) -> ResolvedAdminSession:
        identity_metadata = identity.get("metadata")
        revocable = (
            not bool(identity_metadata.get("bootstrap"))
            if isinstance(identity_metadata, dict)
            else True
        )
        session_version_value: Any = identity.get("session_version") or 1
        return cls(
            principal_id=str(identity.get("principal_id") or fallback_principal_id),
            role=str(identity.get("role") or fallback_role),
            auth_mode=auth_mode,
            revocable=revocable,
            session_version=int(session_version_value),
        )

    def as_payload(self) -> dict[str, object]:
        return {
            "principal_id": self.principal_id,
            "role": self.role,
            "auth_mode": self.auth_mode,
            "transport": "cookie",
            "revocable": self.revocable,
            "session_version": self.session_version,
            "issued_at": "",
            "expires_at": "",
        }


def resolve_admin_login_identity(
    request: Request,
    *,
    token: str,
    principal_id: str,
) -> dict[str, object]:
    settings = get_cloud_services(request).settings
    expected_token = str(settings.admin_bootstrap_token or "").strip()
    environment = str(settings.environment or "").strip().lower()
    if not expected_token and environment in {"development", "test"}:
        expected_token = str(settings.internal_auth_token or "").strip()
    if not expected_token:
        raise PortalBearerTokenError(
            503,
            "auth.admin_bootstrap_not_configured",
            "admin bootstrap auth is not configured",
        )
    if not hmac.compare_digest(token, expected_token):
        raise PortalBearerTokenError(
            401,
            "auth.admin_bootstrap_token_invalid",
            "invalid admin bootstrap token",
        )
    bootstrap_principal_id = str(
        settings.admin_bootstrap_principal_id or "platform:internal_root"
    ).strip()
    requested_principal_id = str(principal_id or "").strip()
    principal_id = requested_principal_id or bootstrap_principal_id or "platform:internal_root"
    return get_commercial_service(request).resolve_platform_admin_grant(
        principal_id=principal_id,
        bootstrap_role=PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
        allow_bootstrap=(principal_id == bootstrap_principal_id),
    )
