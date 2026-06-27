"""Commercial service: portal operations mixin."""

from __future__ import annotations

import secrets
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.db import get_session
from app.core.models import (
    ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE,
    ACCOUNT_USER_MEMBERSHIP_STATUS_REVOKED,
    IDENTITY_PROVIDER_BINDING_STATUS_ACTIVE,
    IDENTITY_PROVIDER_BINDING_STATUS_REVOKED,
    PORTAL_LOGIN_CODE_STATUS_CONSUMED,
    PORTAL_LOGIN_CODE_STATUS_EXPIRED,
    PORTAL_LOGIN_CODE_STATUS_LOCKED,
    PORTAL_OAUTH_STATE_STATUS_CONSUMED,
    PORTAL_OAUTH_STATE_STATUS_EXPIRED,
    PORTAL_OAUTH_STATE_STATUS_PENDING,
    PRINCIPAL_STATUS_ACTIVE,
    PRINCIPAL_STATUS_DISABLED,
    SITE_USER_GRANT_STATUS_ACTIVE,
    SITE_USER_GRANT_STATUS_REVOKED,
    Site,
)
from app.core.security import build_secret_hash
from app.domain.commercial.audit_context import ServiceAuditContext
from app.domain.commercial.errors import (
    CommercialPermissionError,
    CommercialValidationError,
)
from app.domain.commercial.identity import (
    IDENTITY_TYPE_USER,
    USER_ROLE_USER,
    _new_principal_id,
    _normalize_principal_email,
    normalize_user_role,
    resolve_principal_allowed_actions,
)
from app.domain.commercial.mixins._audit_mixin import CommercialServiceAuditMixin


def _normalize_identity_provider(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized != "qq":
        raise CommercialValidationError(
            "service.portal_identity_provider_unsupported",
            "portal identity provider must be qq",
        )
    return normalized


def _sanitize_portal_return_to(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "/portal"
    if not raw.startswith("/portal"):
        return "/portal"
    if raw.startswith("//") or "://" in raw:
        return "/portal"
    return raw[:255]


def _hash_provider_subject(provider: str, value: str) -> str:
    normalized_value = str(value or "").strip()
    if not normalized_value:
        raise CommercialValidationError(
            "service.portal_identity_subject_required",
            "identity provider subject is required",
        )
    return build_secret_hash(f"{provider}:{normalized_value}")


def _hash_external_identity(provider: str, value: str, *, kind: str = "subject") -> str:
    normalized_value = str(value or "").strip()
    if not normalized_value:
        raise CommercialValidationError(
            "service.portal_identity_subject_required",
            "identity provider subject is required",
        )
    return build_secret_hash(f"{provider}:{kind}:{normalized_value}")


def _serialize_identity_provider_binding(
    binding: Any,
    *,
    principal_id: str,
) -> dict[str, object]:
    return {
        "binding_id": str(getattr(binding, "binding_id", "") or ""),
        "provider": str(getattr(binding, "provider", "") or ""),
        "principal_id": principal_id,
        "identity_type": IDENTITY_TYPE_USER,
        "role": USER_ROLE_USER,
        "status": str(getattr(binding, "status", "") or ""),
        "has_unionid": bool(getattr(binding, "unionid_hash", None)),
        "last_login_at": (
            binding.last_login_at.isoformat().replace("+00:00", "Z")
            if getattr(binding, "last_login_at", None)
            else ""
        ),
    }


def _as_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _resolve_membership_allowed_actions(value: object) -> list[str]:
    if isinstance(value, list):
        actions = [str(action).strip() for action in value if str(action).strip()]
        if actions:
            return actions
    return resolve_principal_allowed_actions()


class CommercialServicePortalMixin(CommercialServiceAuditMixin):
    def issue_portal_oauth_state(
        self,
        *,
        provider: str,
        return_to: str,
        client_scope_id: str,
        ttl_seconds: int,
        nonce: str = "",
    ) -> dict[str, object]:
        normalized_provider = _normalize_identity_provider(provider)
        safe_return_to = _sanitize_portal_return_to(return_to)
        normalized_nonce = str(nonce or "").strip()
        state = secrets.token_urlsafe(32)
        now = self.now_factory()
        expires_at = now + timedelta(seconds=max(60, int(ttl_seconds or 0)))
        metadata_json: dict[str, object] = {"source": "portal_oauth_start"}
        if normalized_nonce:
            metadata_json["nonce_hash"] = _hash_provider_subject(
                normalized_provider,
                f"nonce:{normalized_nonce}",
            )
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            repository.create_portal_oauth_state(
                state_id=f"poas_{uuid4().hex}",
                provider=normalized_provider,
                state_hash=_hash_provider_subject(normalized_provider, state),
                return_to=safe_return_to,
                client_scope_id=client_scope_id,
                expires_at=expires_at,
                metadata_json=metadata_json,
            )
            session.commit()
        return {
            "provider": normalized_provider,
            "state": state,
            "return_to": safe_return_to,
            "expires_at": self._serialize_datetime(expires_at),
            "expires_in_seconds": max(60, int(ttl_seconds or 0)),
        }

    def consume_portal_oauth_state(
        self,
        *,
        provider: str,
        state: str,
        nonce: str = "",
    ) -> dict[str, object]:
        normalized_provider = _normalize_identity_provider(provider)
        normalized_state = str(state or "").strip()
        if not normalized_state:
            raise CommercialPermissionError(
                "service.portal_oauth_state_required",
                "portal OAuth state is required",
            )
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            row = repository.get_portal_oauth_state(
                provider=normalized_provider,
                state_hash=_hash_provider_subject(normalized_provider, normalized_state),
            )
            if row is None:
                raise CommercialPermissionError(
                    "service.portal_oauth_state_invalid",
                    "portal OAuth state is invalid",
                )
            if row.status != PORTAL_OAUTH_STATE_STATUS_PENDING or row.consumed_at is not None:
                raise CommercialPermissionError(
                    "service.portal_oauth_state_invalid",
                    "portal OAuth state is invalid",
                )
            metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
            nonce_hash = str(metadata.get("nonce_hash") or "").strip()
            if nonce_hash:
                normalized_nonce = str(nonce or "").strip()
                if not normalized_nonce or nonce_hash != _hash_provider_subject(
                    normalized_provider,
                    f"nonce:{normalized_nonce}",
                ):
                    raise CommercialPermissionError(
                        "service.portal_oauth_nonce_invalid",
                        "portal OAuth nonce is invalid",
                    )
            if _as_utc_datetime(row.expires_at) <= now:
                row.status = PORTAL_OAUTH_STATE_STATUS_EXPIRED
                row.consumed_at = now
                session.commit()
                raise CommercialPermissionError(
                    "service.portal_oauth_state_expired",
                    "portal OAuth state has expired",
                )
            row.status = PORTAL_OAUTH_STATE_STATUS_CONSUMED
            row.consumed_at = now
            payload = {
                "provider": row.provider,
                "return_to": row.return_to or "/portal",
                "client_scope_id": row.client_scope_id or "",
            }
            session.commit()
            return payload

    def bind_portal_identity_provider(
        self,
        *,
        principal_id: str,
        provider: str,
        external_subject: str,
        unionid: str = "",
        metadata_json: dict[str, object] | None = None,
    ) -> dict[str, object]:
        normalized_provider = _normalize_identity_provider(provider)
        subject_hash = _hash_external_identity(normalized_provider, external_subject)
        unionid_hash = (
            _hash_external_identity(normalized_provider, unionid, kind="unionid") if unionid else ""
        )
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            identity = repository.get_principal_identity_by_ref(principal_id=principal_id)
            if identity is None or identity.status != PRINCIPAL_STATUS_ACTIVE:
                raise CommercialPermissionError(
                    "service.principal_access_required",
                    f"principal '{principal_id}' is not active",
                )
            existing = repository.get_identity_provider_binding(
                provider=normalized_provider,
                external_subject_hash=subject_hash,
            )
            if existing is not None and existing.principal_id != identity.principal_id:
                raise CommercialPermissionError(
                    "service.identity_provider_binding_conflict",
                    "this identity provider account is already bound to another user",
                )
            if unionid_hash:
                union_binding = repository.get_identity_provider_binding_by_unionid(
                    provider=normalized_provider,
                    unionid_hash=unionid_hash,
                )
                if (
                    union_binding is not None
                    and union_binding.principal_id != identity.principal_id
                ):
                    raise CommercialPermissionError(
                        "service.identity_provider_binding_conflict",
                        "this identity provider account is already bound to another user",
                    )
            binding = repository.upsert_identity_provider_binding(
                binding_id=f"pib_{uuid4().hex}",
                principal_id=identity.principal_id,
                provider=normalized_provider,
                external_subject_hash=subject_hash,
                unionid_hash=unionid_hash or None,
                status=IDENTITY_PROVIDER_BINDING_STATUS_ACTIVE,
                metadata_json={
                    "source": "identity_provider_binding",
                    **dict(metadata_json or {}),
                },
                last_login_at=now,
            )
            session.commit()
            return _serialize_identity_provider_binding(binding, principal_id=principal_id)

    def revoke_portal_identity_provider(
        self,
        *,
        principal_id: str,
        provider: str,
    ) -> dict[str, object]:
        normalized_provider = _normalize_identity_provider(provider)
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            identity = repository.get_principal_identity_by_ref(principal_id=principal_id)
            if identity is None:
                raise CommercialPermissionError(
                    "service.principal_access_required",
                    f"principal '{principal_id}' is not active",
                )
            bindings = repository.list_identity_provider_bindings_for_principal(
                principal_id=identity.principal_id,
                provider=normalized_provider,
                status=IDENTITY_PROVIDER_BINDING_STATUS_ACTIVE,
            )
            for binding in bindings:
                binding.status = IDENTITY_PROVIDER_BINDING_STATUS_REVOKED
            if bindings:
                repository.increment_principal_session_version(
                    principal_id=identity.principal_id,
                )
            session.commit()
            return {
                "provider": normalized_provider,
                "principal_id": principal_id,
                "revoked": len(bindings),
            }

    def resolve_portal_identity_provider_login(
        self,
        *,
        provider: str,
        external_subject: str,
        unionid: str = "",
    ) -> dict[str, object]:
        normalized_provider = _normalize_identity_provider(provider)
        subject_hash = _hash_external_identity(normalized_provider, external_subject)
        unionid_hash = (
            _hash_external_identity(normalized_provider, unionid, kind="unionid") if unionid else ""
        )
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            binding = repository.get_identity_provider_binding(
                provider=normalized_provider,
                external_subject_hash=subject_hash,
            )
            if binding is None and unionid_hash:
                binding = repository.get_identity_provider_binding_by_unionid(
                    provider=normalized_provider,
                    unionid_hash=unionid_hash,
                )
            if binding is None:
                return {
                    "status": "binding_required",
                    "provider": normalized_provider,
                    "identity_type": IDENTITY_TYPE_USER,
                    "role": USER_ROLE_USER,
                }
            if binding.status != IDENTITY_PROVIDER_BINDING_STATUS_ACTIVE:
                raise CommercialPermissionError(
                    "service.identity_provider_binding_revoked",
                    "this identity provider binding is not active",
                )
            identity = repository.get_principal_identity(binding.principal_id)
            if identity is None or identity.status != PRINCIPAL_STATUS_ACTIVE:
                raise CommercialPermissionError(
                    "service.principal_access_required",
                    "bound user is not active",
                )
            grants = repository.list_sites_for_principal(
                principal_id=identity.principal_id,
                grant_statuses=[SITE_USER_GRANT_STATUS_ACTIVE],
            )
            memberships = repository.list_accounts_for_principal(
                principal_id=identity.principal_id,
                membership_statuses=[ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE],
            )
            if not grants and not memberships:
                raise CommercialPermissionError(
                    "service.principal_access_required",
                    f"principal '{identity.principal_id}' is not active for any accessible site",
                )
            binding.last_login_at = now
            identity.last_login_at = now
            session.commit()
            return {
                "status": "authenticated",
                "provider": normalized_provider,
                "principal_id": identity.principal_id,
                "session_version": int(identity.session_version or 1),
                "identity_type": IDENTITY_TYPE_USER,
                "role": USER_ROLE_USER,
                "binding": _serialize_identity_provider_binding(
                    binding,
                    principal_id=identity.principal_id,
                ),
            }

    def issue_portal_login_code(
        self,
        *,
        email: str,
        ttl_seconds: int,
    ) -> dict[str, object]:
        login = self.resolve_principal_login(email=email)
        normalized_email = str(login.get("email") or "").strip().lower()
        principal_id = str(login.get("principal_id") or "").strip()
        now = self.now_factory()
        expires_at = now + timedelta(seconds=max(60, int(ttl_seconds or 0)))
        code = f"{secrets.randbelow(1_000_000):06d}"
        code_hash = build_secret_hash(code)

        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            existing_codes = repository.list_portal_login_codes(
                email=normalized_email,
                principal_id=principal_id,
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
                principal_id=principal_id,
                code_hash=code_hash,
                expires_at=expires_at,
                metadata_json={"accounts": login.get("accounts") or []},
            )
            session.commit()
        return {
            "email": normalized_email,
            "principal_id": principal_id,
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
            principal_id = str(active_code.principal_id or "").strip()
            identity = repository.get_principal_identity_by_ref(
                principal_id=principal_id,
            )
            grants = repository.list_sites_for_principal(
                principal_id=principal_id,
                grant_statuses=[SITE_USER_GRANT_STATUS_ACTIVE],
            )
            memberships = repository.list_accounts_for_principal(
                principal_id=principal_id,
                membership_statuses=[ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE],
            )
            if identity is None or (not grants and not memberships):
                raise CommercialPermissionError(
                    "service.principal_access_required",
                    f"principal '{principal_id}' is not active for any accessible site",
                )
            identity.last_login_at = now
            session.commit()
        return {
            "email": normalized_email,
            "principal_id": principal_id,
            "session_version": int(getattr(identity, "session_version", 1) or 1),
            "last_login_at": self._serialize_datetime(now),
            "site_grants": [
                {
                    "site_id": site.site_id,
                    "grant_id": grant.grant_id,
                    "status": grant.status,
                }
                for site, _identity, grant in grants
            ],
        }

    def list_portal_accounts(
        self,
        *,
        principal_id: str,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            candidate_sites = repository.list_sites_for_principal(
                principal_id=principal_id,
                grant_statuses=[SITE_USER_GRANT_STATUS_ACTIVE],
            )
            sites_by_account: defaultdict[str, list[Site]] = defaultdict(list)
            for site, _identity, _grant in candidate_sites:
                if site.account_id:
                    sites_by_account[site.account_id].append(site)
            memberships = repository.list_accounts_for_principal(
                principal_id=principal_id,
                membership_statuses=[ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE],
            )
            account_items: list[dict[str, object]] = []
            seen_account_ids: set[str] = set()
            for account, _identity, membership in memberships:
                account_id = str(getattr(account, "account_id", "") or "")
                seen_account_ids.add(account_id)
                account_items.append(
                    {
                        "account_id": account_id,
                        "name": str(getattr(account, "name", "") or ""),
                        "status": str(getattr(account, "status", "") or ""),
                        "principal_id": principal_id,
                        "identity_type": IDENTITY_TYPE_USER,
                        "allowed_actions": _resolve_membership_allowed_actions(
                            getattr(membership, "allowed_actions_json", None)
                        ),
                        "role": str(getattr(membership, "role", "") or USER_ROLE_USER),
                        "membership_id": str(getattr(membership, "membership_id", "") or ""),
                        "membership_status": str(getattr(membership, "status", "") or ""),
                        "site_count": len(sites_by_account.get(account_id, [])),
                        "sites": [
                            cast(Any, self)._serialize_site(site)
                            for site in sites_by_account.get(account_id, [])
                        ],
                    }
                )
            for account_id, sites in sites_by_account.items():
                if account_id in seen_account_ids:
                    continue
                account = repository.get_account(account_id)
                if account is None:
                    continue
                account_items.append(
                    {
                        "account_id": account_id,
                        "name": str(getattr(account, "name", "") or ""),
                        "status": str(getattr(account, "status", "") or ""),
                        "principal_id": principal_id,
                        "identity_type": IDENTITY_TYPE_USER,
                        "allowed_actions": resolve_principal_allowed_actions(),
                        "role": USER_ROLE_USER,
                        "membership_id": "",
                        "membership_status": "",
                        "site_count": len(sites),
                        "sites": [cast(Any, self)._serialize_site(site) for site in sites],
                    }
                )
            return {
                "principal_id": principal_id,
                "items": account_items,
            }

    def upsert_principal_access(
        self,
        *,
        site_id: str,
        email: str,
        status: str = PRINCIPAL_STATUS_ACTIVE,
        metadata_json: dict[str, object] | None = None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_email = _normalize_principal_email(email)
        normalized_status = str(status or PRINCIPAL_STATUS_ACTIVE).strip().lower()
        if normalized_status not in {PRINCIPAL_STATUS_ACTIVE, PRINCIPAL_STATUS_DISABLED}:
            raise CommercialValidationError(
                "service.principal_status_invalid",
                "principal status must be active or disabled",
            )
        grant_status = (
            SITE_USER_GRANT_STATUS_ACTIVE
            if normalized_status == PRINCIPAL_STATUS_ACTIVE
            else SITE_USER_GRANT_STATUS_REVOKED
        )
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            site = repository.get_site(site_id)
            if site is None:
                raise CommercialPermissionError(
                    "service.site_not_found",
                    f"site '{site_id}' was not found",
                )
            existing_identity = repository.get_principal_identity_by_email(
                email=normalized_email,
            )
            principal_id = (
                str(existing_identity.principal_id)
                if existing_identity is not None
                else _new_principal_id()
            )
            identity = repository.upsert_principal_identity(
                principal_id=principal_id,
                email=normalized_email,
                status=normalized_status,
                metadata_json=metadata_json,
            )
            if normalized_status == PRINCIPAL_STATUS_DISABLED:
                identity = repository.increment_principal_session_version(
                    principal_id=identity.principal_id,
                ) or identity
            grant = repository.upsert_principal_site_grant(
                grant_id=f"sadmg_{uuid4().hex}",
                principal_id=identity.principal_id,
                site_id=site_id,
                status=grant_status,
                metadata_json={
                    **dict(metadata_json or {}),
                    "source": str((metadata_json or {}).get("source") or "principal_access"),
                },
            )
            membership = None
            account_id = str(getattr(site, "account_id", "") or "")
            if account_id:
                membership = repository.upsert_account_user_membership(
                    membership_id=f"aum_{uuid4().hex}",
                    principal_id=identity.principal_id,
                    account_id=account_id,
                    role=normalize_user_role(USER_ROLE_USER),
                    status=(
                        ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE
                        if normalized_status == PRINCIPAL_STATUS_ACTIVE
                        else ACCOUNT_USER_MEMBERSHIP_STATUS_REVOKED
                    ),
                    allowed_actions_json=resolve_principal_allowed_actions(),
                    metadata_json={
                        **dict(metadata_json or {}),
                        "source": str(
                            (metadata_json or {}).get("source") or "principal_access"
                        ),
                    },
                )
            payload: dict[str, object] = {
                "principal_id": identity.principal_id,
                "email": identity.email,
                "status": identity.status,
                "session_version": int(identity.session_version or 1),
                "account_id": account_id,
                "site_id": site_id,
                "grant_id": grant.grant_id,
                "grant_status": grant.status,
                "membership_id": str(getattr(membership, "membership_id", "") or ""),
                "membership_status": str(getattr(membership, "status", "") or ""),
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="principal_access.upsert",
                outcome="succeeded",
                account_id=str(getattr(site, "account_id", "") or ""),
                site_id=site_id,
                scope_kind="principal_access",
                scope_id=f"{site_id}:{principal_id}",
                payload_json=payload,
            )
            session.commit()
        return payload

    def resolve_principal_login(self, *, email: str) -> dict[str, object]:
        normalized_email = _normalize_principal_email(email)
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            identity = repository.get_principal_identity_by_email(email=normalized_email)
            principal_id = str(identity.principal_id) if identity is not None else ""
            candidate_sites = repository.list_sites_for_principal(
                principal_id=principal_id,
                grant_statuses=[SITE_USER_GRANT_STATUS_ACTIVE],
            ) if principal_id else []
            memberships = repository.list_accounts_for_principal(
                principal_id=principal_id,
                membership_statuses=[ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE],
            ) if principal_id else []
        if identity is None or (not candidate_sites and not memberships):
            raise CommercialPermissionError(
                "service.principal_email_not_found",
                f"no user site grant was found for '{normalized_email}'",
            )
        site_items = [
            {
                "principal_id": principal_id,
                "identity_type": IDENTITY_TYPE_USER,
                "allowed_actions": resolve_principal_allowed_actions(),
                "role": USER_ROLE_USER,
                "status": grant.status,
                "site": cast(Any, self)._serialize_site(site),
            }
            for site, _identity, grant in candidate_sites
        ]
        account_ids = {
            str(getattr(site, "account_id", "") or "")
            for site, _identity, _grant in candidate_sites
            if str(getattr(site, "account_id", "") or "").strip()
        }
        portal_accounts = self.list_portal_accounts(principal_id=principal_id)
        portal_account_items = portal_accounts.get("items")
        if not isinstance(portal_account_items, list):
            portal_account_items = []
        return {
            "email": normalized_email,
            "principal_id": principal_id,
            "session_version": int(getattr(identity, "session_version", 1) or 1),
            "sites": site_items,
            "accounts": [
                item
                for item in portal_account_items
                if isinstance(item, dict) and (
                    not account_ids or str(item.get("account_id") or "") in account_ids
                )
            ],
        }

    def _resolve_portal_target_package_tier_id(self, target_package: str) -> str:
        normalized = str(target_package or "").strip().lower()
        mapping = {
            "free": "free",
            "pro": "pro",
            "agency": "agency",
        }
        tier_id = mapping.get(normalized)
        if tier_id:
            return tier_id
        raise CommercialValidationError(
            "service.invalid_target_package",
            "target package must be Free, Pro, or Agency",
        )
