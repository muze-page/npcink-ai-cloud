from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import dataclass

from fastapi import Request

from app.api.auth import PortalBearerTokenError, get_cloud_services
from app.api.portal_session import (
    get_commercial_service,
)
from app.core.models import PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN


@dataclass(frozen=True)
class ResolvedAdminSession:
    grant_id: str
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
    ) -> ResolvedAdminSession:
        grant_id = identity.get("grant_id")
        principal_id = identity.get("principal_id")
        role = identity.get("role")
        is_persisted = identity.get("is_persisted")
        session_version = identity.get("session_version")
        if (
            not isinstance(grant_id, str)
            or grant_id != grant_id.strip()
            or not isinstance(principal_id, str)
            or not principal_id
            or principal_id != principal_id.strip()
            or not isinstance(role, str)
            or not role
            or role != role.strip()
            or not isinstance(is_persisted, bool)
            or (is_persisted and not grant_id)
            or (not is_persisted and bool(grant_id))
            or isinstance(session_version, bool)
            or not isinstance(session_version, int)
            or session_version < 1
        ):
            raise PortalBearerTokenError(
                401,
                "auth.admin_session_invalid",
                "admin session is invalid",
            )
        return cls(
            grant_id=grant_id,
            principal_id=principal_id,
            role=role,
            auth_mode=auth_mode,
            revocable=is_persisted,
            session_version=session_version,
        )

    def as_payload(self) -> dict[str, object]:
        return {
            "grant_id": self.grant_id,
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
