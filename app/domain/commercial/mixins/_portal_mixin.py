"""Commercial service: portal operations mixin."""
from __future__ import annotations

import secrets
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.db import get_session
from app.core.models import (
    ACCOUNT_MEMBERSHIP_STATUS_ACTIVE,
    PORTAL_LOGIN_CODE_STATUS_CONSUMED,
    PORTAL_LOGIN_CODE_STATUS_EXPIRED,
    PORTAL_LOGIN_CODE_STATUS_LOCKED,
    Site,
)
from app.core.security import build_secret_hash
from app.domain.commercial.errors import (
    CommercialPermissionError,
    CommercialValidationError,
)
from app.domain.commercial.mixins._audit_mixin import (
    PORTAL_MEMBER_ALLOWED_LOGIN_STATUSES,
    CommercialServiceAuditMixin,
    _normalize_portal_membership_metadata,
    _portal_membership_has_allowed_role,
)


class CommercialServicePortalMixin(CommercialServiceAuditMixin):

    def issue_portal_login_code(
        self,
        *,
        email: str,
        ttl_seconds: int,
    ) -> dict[str, object]:
        login = cast(Any, self).resolve_portal_member_login(email=email)
        normalized_email = str(login.get("email") or "").strip().lower()
        member_ref = str(login.get("member_ref") or "").strip()
        now = self.now_factory()
        expires_at = now + timedelta(seconds=max(60, int(ttl_seconds or 0)))
        code = f"{secrets.randbelow(1_000_000):06d}"
        code_hash = build_secret_hash(code)

        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            existing_codes = repository.list_portal_login_codes(
                email=normalized_email,
                member_ref=member_ref,
                active_only=True,
                now=now,
                limit=None,
            )
            for existing in existing_codes:
                existing.status = PORTAL_LOGIN_CODE_STATUS_EXPIRED
                existing.consumed_at = now
            repository.create_portal_login_code(
                code_id=f"plc_{uuid4().hex}",
                email=normalized_email,
                member_ref=member_ref,
                code_hash=code_hash,
                expires_at=expires_at,
                metadata_json={"accounts": login.get("accounts") or []},
            )
            session.commit()
        return {
            "email": normalized_email,
            "member_ref": member_ref,
            "code": code,
            "expires_at": self._serialize_datetime(expires_at),
            "expires_in_seconds": max(60, int(ttl_seconds or 0)),
            "accounts": login.get("accounts") or [],
        }


    def verify_portal_login_code(
        self,
        *,
        email: str,
        code: str,
        max_attempts: int,
        login_at: datetime | None = None,
    ) -> dict[str, object]:
        normalized_email = str(email or "").strip().lower()
        normalized_code = str(code or "").strip()
        if not normalized_email or "@" not in normalized_email or " " in normalized_email:
            raise CommercialPermissionError(
                "service.portal_email_invalid",
                "a valid portal email is required",
            )
        if not normalized_code or not normalized_code.isdigit():
            raise CommercialPermissionError(
                "service.portal_login_code_invalid",
                "portal login code is invalid",
            )

        now = login_at or self.now_factory()
        bounded_attempts = max(1, int(max_attempts or 0))
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            active_codes = repository.list_portal_login_codes(
                email=normalized_email,
                active_only=True,
                now=now,
                limit=1,
            )
            if not active_codes:
                raise CommercialPermissionError(
                    "service.portal_login_code_invalid",
                    "portal login code is invalid",
                )
            active_code = active_codes[0]
            if build_secret_hash(normalized_code) != str(active_code.code_hash or ""):
                active_code.attempt_count = int(active_code.attempt_count or 0) + 1
                if active_code.attempt_count >= bounded_attempts:
                    active_code.status = PORTAL_LOGIN_CODE_STATUS_LOCKED
                    active_code.consumed_at = now
                session.commit()
                raise CommercialPermissionError(
                    "service.portal_login_code_invalid",
                    "portal login code is invalid",
                )
            active_code.status = PORTAL_LOGIN_CODE_STATUS_CONSUMED
            active_code.consumed_at = now
            member_ref = str(active_code.member_ref or "").strip()
            memberships = repository.list_account_memberships(
                member_ref=member_ref,
                statuses=sorted(PORTAL_MEMBER_ALLOWED_LOGIN_STATUSES),
                limit=None,
            )
            if not memberships:
                raise CommercialPermissionError(
                    "service.portal_membership_required",
                    f"member '{member_ref}' is not active for any accessible account",
                )
            updated_items: list[dict[str, object]] = []
            for membership in memberships:
                metadata = dict(getattr(membership, "metadata_json", None) or {})
                metadata["last_login_at"] = self._serialize_datetime(now)
                metadata.setdefault("enabled_at", self._serialize_datetime(now))
                metadata["invite_state"] = "accepted"
                membership.status = ACCOUNT_MEMBERSHIP_STATUS_ACTIVE
                membership.metadata_json = _normalize_portal_membership_metadata(
                    member_ref=membership.member_ref,
                    status=membership.status,
                    metadata_json=metadata,
                )
                updated_items.append(
                    cast(Any, self)._serialize_account_membership(membership)
                )
            session.commit()
        return {
            "email": normalized_email,
            "member_ref": member_ref,
            "last_login_at": self._serialize_datetime(now),
            "memberships": updated_items,
        }


    def list_portal_accounts(
        self,
        *,
        member_ref: str,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            service = cast(Any, self)
            account_memberships = service._list_resolved_portal_account_memberships(
                repository,
                member_ref=member_ref,
            )
            candidate_sites = repository.list_sites_for_member(
                member_ref=member_ref,
                membership_statuses=sorted(PORTAL_MEMBER_ALLOWED_LOGIN_STATUSES),
            )
            sites_by_account: defaultdict[str, list[Site]] = defaultdict(list)
            for site, membership in candidate_sites:
                if not _portal_membership_has_allowed_role(membership):
                    continue
                if site.account_id:
                    sites_by_account[site.account_id].append(site)
            return {
                "member_ref": member_ref,
                "items": [
                    service._serialize_portal_account_context(
                        account,
                        membership,
                        accessible_sites=sites_by_account.get(
                            str(getattr(account, "account_id", "") or ""),
                            [],
                        ),
                    )
                    for account, membership in account_memberships
                ],
            }


    def _resolve_portal_target_package_tier_id(self, target_package: str) -> str:
        normalized = str(target_package or "").strip().lower()
        mapping = {
            "free": "starter",
            "basic": "pro",
            "bulk": "agency",
        }
        tier_id = mapping.get(normalized)
        if tier_id:
            return tier_id
        raise CommercialValidationError(
            "service.invalid_target_package",
            "target package must be Free, Basic, or Bulk",
        )

