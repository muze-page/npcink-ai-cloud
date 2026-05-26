from __future__ import annotations

from collections.abc import Mapping
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import Request

from app.api.auth import PortalBearerTokenError, get_cloud_services
from app.api.portal_session import (
    build_new_portal_session_metadata,
    get_commercial_service,
    serialize_portal_session,
)
from app.core.models import PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN


@dataclass(frozen=True)
class ResolvedAdminSession:
    platform_admin_ref: str
    role: str
    auth_mode: str
    revocable: bool

    @classmethod
    def from_identity(
        cls,
        identity: Mapping[str, object],
        *,
        auth_mode: str,
        fallback_admin_ref: str = "",
        fallback_role: str = PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
    ) -> ResolvedAdminSession:
        identity_metadata = identity.get("metadata")
        revocable = not bool(identity_metadata.get("bootstrap")) if isinstance(
            identity_metadata, dict
        ) else True
        return cls(
            platform_admin_ref=str(identity.get("admin_ref") or fallback_admin_ref),
            role=str(identity.get("role") or fallback_role),
            auth_mode=auth_mode,
            revocable=revocable,
        )

    def as_payload(
        self,
        *,
        impersonation: dict[str, object] | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "platform_admin_ref": self.platform_admin_ref,
            "role": self.role,
            "auth_mode": self.auth_mode,
            "transport": "cookie",
            "revocable": self.revocable,
            "issued_at": "",
            "expires_at": "",
        }
        if impersonation is not None:
            payload["impersonation"] = impersonation
        return payload


@dataclass(frozen=True)
class PlatformImpersonationSession:
    impersonation: dict[str, object]
    portal_session: dict[str, object]
    member_ref: str
    site_id: str
    expires_at: str
    max_age: int


def resolve_admin_login_identity(
    request: Request,
    *,
    token: str,
    admin_ref: str,
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
    bootstrap_admin_ref = str(
        settings.admin_bootstrap_admin_ref or "platform:internal_root"
    ).strip()
    requested_admin_ref = str(admin_ref or "").strip()
    platform_admin_ref = requested_admin_ref or bootstrap_admin_ref or "platform:internal_root"
    return get_commercial_service(request).resolve_platform_admin_identity(
        admin_ref=platform_admin_ref,
        bootstrap_role=PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
        allow_bootstrap=(platform_admin_ref == bootstrap_admin_ref),
    )


def start_platform_impersonation_session(
    request: Request,
    *,
    platform_admin_ref: str,
    platform_role: str,
    member_ref: str,
    site_id: str,
    reason_code: str,
    reason_text: str,
    audit_context: Any,
) -> PlatformImpersonationSession:
    impersonation = get_commercial_service(request).start_platform_impersonation(
        platform_admin_ref=platform_admin_ref,
        platform_role=platform_role,
        member_ref=member_ref,
        site_id=site_id,
        reason_code=reason_code,
        reason_text=reason_text,
        read_only=True,
        audit_context=audit_context,
    )
    session_metadata = build_new_portal_session_metadata(request)
    session_metadata["member_ref"] = member_ref
    portal_session = serialize_portal_session(
        request,
        member_ref=member_ref,
        site_id=site_id,
        strict_site=True,
        session_metadata=session_metadata,
    )
    portal_session["impersonation"] = impersonation

    expires_at = str(impersonation.get("expires_at") or "")
    max_age = 60
    if expires_at:
        try:
            expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            max_age = max(60, int((expires_dt - datetime.now(UTC)).total_seconds()))
        except ValueError:
            max_age = 60
    return PlatformImpersonationSession(
        impersonation=impersonation,
        portal_session=portal_session,
        member_ref=member_ref,
        site_id=site_id,
        expires_at=expires_at,
        max_age=max_age,
    )


def end_platform_impersonation(
    request: Request,
    *,
    impersonation_id: str,
    platform_admin_ref: str,
    ended_reason: str,
    audit_context: Any,
) -> dict[str, object]:
    return get_commercial_service(request).end_platform_impersonation(
        impersonation_id=impersonation_id,
        platform_admin_ref=platform_admin_ref,
        ended_reason=ended_reason,
        audit_context=audit_context,
    )
