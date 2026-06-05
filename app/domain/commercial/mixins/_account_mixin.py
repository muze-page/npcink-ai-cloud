"""Commercial service: account and membership operations mixin."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.db import get_session
from app.core.models import (
    ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN,
    ACCOUNT_MEMBERSHIP_STATUS_ACTIVE,
    ACCOUNT_MEMBERSHIP_STATUS_DISABLED,
    ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE,
    ACCOUNT_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_CANCELED,
    SUBSCRIPTION_STATUS_SUSPENDED,
    Site,
)
from app.domain.commercial.errors import (
    CommercialNotFoundError,
    CommercialPermissionError,
)
from app.domain.commercial.mixins._audit_mixin import CommercialServiceAuditMixin
from app.domain.commercial.service import (
    DEFAULT_FREE_PLAN_KIND,
    DEFAULT_FREE_SUBSCRIPTION_SOURCE,
    IDENTITY_TYPE_USER_ADMIN,
    PLAN_TIER_REGISTRY,
    PORTAL_INVITE_DELIVERY_FAILED,
    PORTAL_INVITE_DELIVERY_QUEUED,
    PORTAL_INVITE_DELIVERY_SENT,
    PORTAL_MEMBER_ALLOWED_LOGIN_STATUSES,
    ServiceAuditContext,
    _canonicalize_customer_membership_role_for_write,
    _normalize_customer_membership_role,
    _normalize_portal_member_email,
    _normalize_portal_membership_metadata,
    _portal_membership_has_allowed_role,
    _portal_membership_role_priority,
    _resolve_identity_type,
    _resolve_portal_allowed_actions,
    assert_platform_admin_capability,
)


class CommercialServiceAccountMixin(CommercialServiceAuditMixin):

    def upsert_account(
        self,
        *,
        account_id: str,
        name: str,
        status: str = ACCOUNT_STATUS_ACTIVE,
        metadata_json: dict[str, object] | None = None,
        bind_default_free: bool = False,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            account = repository.upsert_account(
                account_id=account_id,
                name=name,
                status=status,
                metadata_json=metadata_json,
            )
            subscription_payload = None
            if bind_default_free:
                subscription_payload = self._bind_default_free_subscription_for_account_in_session(
                    repository=repository,
                    account_id=account.account_id,
                    audit_context=audit_context,
                )
            payload = self._serialize_account(account)
            if subscription_payload is not None:
                payload["current_subscription"] = subscription_payload["subscription"]
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="account.upsert",
                outcome="succeeded",
                account_id=account.account_id,
                scope_kind="account",
                scope_id=account.account_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def upsert_account_membership(
        self,
        *,
        account_id: str,
        member_ref: str,
        role: str = ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN,
        status: str = "active",
        metadata_json: dict[str, object] | None = None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_status = str(status or "").strip() or ACCOUNT_MEMBERSHIP_STATUS_ACTIVE
        normalized_metadata = _normalize_portal_membership_metadata(
            member_ref=member_ref,
            status=normalized_status,
            metadata_json=metadata_json,
        )
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            account = repository.get_account(account_id)
            if account is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )
            membership = repository.upsert_account_membership(
                account_id=account_id,
                member_ref=member_ref,
                role=role,
                status=normalized_status,
                metadata_json=normalized_metadata,
            )
            payload = self._serialize_account_membership(membership)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="account_membership.upsert",
                outcome="succeeded",
                account_id=account_id,
                scope_kind="account",
                scope_id=account_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def invite_admin_account_member(
        self,
        *,
        account_id: str,
        email: str,
        role: str = ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN,
        locale: str = "",
        platform_role: str,
        audit_context: ServiceAuditContext | None = None,
        send_invite: Callable[[str, str, str], dict[str, object]],
    ) -> dict[str, object]:
        assert_platform_admin_capability(
            role=platform_role,
            capability="can_manage_accounts",
            error_code="service.platform_admin_role_forbidden",
            message="platform admin cannot invite portal members",
        )
        normalized_email = str(email or "").strip().lower()
        if not normalized_email or "@" not in normalized_email or " " in normalized_email:
            raise CommercialPermissionError(
                "service.portal_email_invalid",
                "a valid portal email is required",
            )
        requested_role = ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN

        member_ref = f"user:{normalized_email}"
        invited_at_dt = self.now_factory()
        invited_at = self._serialize_datetime(invited_at_dt)
        invite_expires_at = self._serialize_datetime(invited_at_dt + timedelta(minutes=15))

        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            account = repository.get_account(account_id)
            if account is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )

            membership = repository.get_account_membership(account_id=account_id, member_ref=member_ref)
            existing_metadata = dict(getattr(membership, "metadata_json", None) or {})
            invite_count = int(existing_metadata.get("invite_count") or 0)
            member_role = _canonicalize_customer_membership_role_for_write(
                requested_role
            )
            pending_metadata = {
                **existing_metadata,
                "source": existing_metadata.get("source") or "admin_invite_member",
                "email": normalized_email,
                "invited_via": "admin_accounts_detail",
                "invite_state": "pending",
                "invite_count": invite_count + 1,
                "invited_at": existing_metadata.get("invited_at") or invited_at,
                "last_invited_at": invited_at,
                "invite_expires_at": invite_expires_at,
                "last_delivery_status": PORTAL_INVITE_DELIVERY_QUEUED,
                "last_delivery_error_code": "",
                "last_delivery_error_message": "",
            }
            membership = repository.upsert_account_membership(
                account_id=account_id,
                member_ref=member_ref,
                role=member_role,
                status=ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE,
                metadata_json=_normalize_portal_membership_metadata(
                    member_ref=member_ref,
                    status=ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE,
                    metadata_json=pending_metadata,
                ),
            )

            try:
                delivery = send_invite(member_ref, normalized_email, locale)
            except Exception as error:
                failed_metadata = {
                    **existing_metadata,
                    "source": existing_metadata.get("source") or "admin_invite_member",
                    "email": normalized_email,
                    "invited_via": "admin_accounts_detail",
                    "invite_state": "pending",
                    "invite_count": invite_count + 1,
                    "invited_at": existing_metadata.get("invited_at") or invited_at,
                    "last_invited_at": invited_at,
                    "invite_expires_at": invite_expires_at,
                    "last_delivery_status": PORTAL_INVITE_DELIVERY_FAILED,
                    "last_delivery_error_code": str(getattr(error, "error_code", "") or "portal.email_delivery_failed"),
                    "last_delivery_error_message": str(
                        getattr(error, "message", "") or str(error) or "portal invite delivery failed"
                    ),
                }
                repository.upsert_account_membership(
                    account_id=account_id,
                    member_ref=member_ref,
                    role=member_role,
                    status=ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE,
                    metadata_json=_normalize_portal_membership_metadata(
                        member_ref=member_ref,
                        status=ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE,
                        metadata_json=failed_metadata,
                    ),
                )
                session.commit()
                raise

            delivery_mode = str(delivery.get("delivery") or "email")
            delivery_status = (
                PORTAL_INVITE_DELIVERY_SENT if delivery_mode else PORTAL_INVITE_DELIVERY_QUEUED
            )
            sent_metadata = {
                **existing_metadata,
                "source": existing_metadata.get("source") or "admin_invite_member",
                "email": normalized_email,
                "invited_via": "admin_accounts_detail",
                "invite_state": "sent",
                "invite_count": invite_count + 1,
                "invited_at": existing_metadata.get("invited_at") or invited_at,
                "last_invited_at": invited_at,
                "invite_expires_at": invite_expires_at,
                "last_delivery_status": delivery_status,
                "last_delivery_error_code": "",
                "last_delivery_error_message": "",
            }
            membership = repository.upsert_account_membership(
                account_id=account_id,
                member_ref=member_ref,
                role=member_role,
                status=ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE,
                metadata_json=_normalize_portal_membership_metadata(
                    member_ref=member_ref,
                    status=ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE,
                    metadata_json=sent_metadata,
                ),
            )
            payload: dict[str, object] = {
                "account_id": account_id,
                "email": normalized_email,
                "member_ref": member_ref,
                "role": member_role,
                "identity_type": IDENTITY_TYPE_USER_ADMIN,
                "status": ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE,
                "delivery": delivery_mode,
                "delivery_status": delivery_status,
                "invited_at": invited_at,
                "invite_expires_at": invite_expires_at,
                "invite_count": invite_count + 1,
                "membership": self._serialize_account_membership(membership),
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="account_membership.invite",
                outcome="succeeded",
                account_id=account_id,
                scope_kind="account_membership",
                scope_id=f"{account_id}:{member_ref}",
                payload_json=payload,
            )
            session.commit()
            return payload

    def resend_admin_account_member_invite(
        self,
        *,
        account_id: str,
        member_ref: str,
        locale: str,
        platform_role: str,
        audit_context: ServiceAuditContext | None = None,
        send_invite: Callable[[str, str, str], dict[str, object]],
    ) -> dict[str, object]:
        assert_platform_admin_capability(
            role=platform_role,
            capability="can_manage_accounts",
            error_code="service.platform_admin_role_forbidden",
            message="platform admin cannot resend portal invites",
        )
        normalized_member_ref = str(member_ref or "").strip()
        if not normalized_member_ref:
            raise CommercialPermissionError(
                "service.portal_member_ref_required",
                "portal member ref is required",
            )

        now_dt = self.now_factory()
        now_value = self._serialize_datetime(now_dt)
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            account = repository.get_account(account_id)
            if account is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )
            membership = repository.get_account_membership(
                account_id=account_id,
                member_ref=normalized_member_ref,
            )
            if membership is None:
                raise CommercialNotFoundError(
                    "service.account_membership_not_found",
                    f"member '{normalized_member_ref}' was not found in account '{account_id}'",
                )
            if str(membership.status or "") == ACCOUNT_MEMBERSHIP_STATUS_DISABLED:
                raise CommercialPermissionError(
                    "service.account_membership_disabled",
                    "disabled members cannot receive invites",
                )
            if str(membership.status or "") not in {
                ACCOUNT_MEMBERSHIP_STATUS_ACTIVE,
                ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE,
            }:
                raise CommercialPermissionError(
                    "service.account_membership_status_invalid",
                    "member is not eligible for invite delivery",
                )

            metadata = dict(getattr(membership, "metadata_json", None) or {})
            last_invited_at = str(metadata.get("last_invited_at") or "").strip()
            if last_invited_at:
                try:
                    previous_invited_at = datetime.fromisoformat(last_invited_at.replace("Z", "+00:00"))
                except ValueError:
                    previous_invited_at = None
                if previous_invited_at is not None and int((now_dt - previous_invited_at).total_seconds()) < 60:
                    raise CommercialPermissionError(
                        "service.account_membership_invite_rate_limited",
                        "invite was sent too recently; wait before resending",
                    )

            normalized_email = _normalize_portal_member_email(normalized_member_ref, metadata)
            if not normalized_email:
                raise CommercialPermissionError(
                    "service.portal_email_required",
                    "member email is required",
                )

            invite_count = int(metadata.get("invite_count") or 0) + 1
            try:
                delivery = send_invite(normalized_member_ref, normalized_email, locale)
            except Exception as error:
                failed_metadata = {
                    **metadata,
                    "email": normalized_email,
                    "source": metadata.get("source") or "admin_invite_member",
                    "invited_via": "admin_accounts_detail",
                    "invite_state": "pending",
                    "invite_count": invite_count,
                    "last_invited_at": now_value,
                    "last_delivery_status": PORTAL_INVITE_DELIVERY_FAILED,
                    "last_delivery_error_code": str(getattr(error, "error_code", "") or "portal.email_delivery_failed"),
                    "last_delivery_error_message": str(
                        getattr(error, "message", "") or str(error) or "portal invite delivery failed"
                    ),
                }
                repository.upsert_account_membership(
                    account_id=account_id,
                    member_ref=normalized_member_ref,
                    role=ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN,
                    status=ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE,
                    metadata_json=_normalize_portal_membership_metadata(
                        member_ref=normalized_member_ref,
                        status=ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE,
                        metadata_json=failed_metadata,
                    ),
                )
                session.commit()
                raise

            delivery_mode = str(delivery.get("delivery") or "email")
            delivery_status = (
                PORTAL_INVITE_DELIVERY_SENT if delivery_mode else PORTAL_INVITE_DELIVERY_QUEUED
            )
            next_status = (
                ACCOUNT_MEMBERSHIP_STATUS_ACTIVE
                if str(membership.status or "") == ACCOUNT_MEMBERSHIP_STATUS_ACTIVE
                else ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE
            )
            updated_metadata = {
                **metadata,
                "email": normalized_email,
                "source": metadata.get("source") or "admin_invite_member",
                "invited_via": "admin_accounts_detail",
                "invite_state": "sent",
                "invite_delivery": delivery_mode,
                "invite_count": invite_count,
                "last_invited_at": now_value,
                "invited_at": metadata.get("invited_at") or now_value,
                "last_delivery_status": delivery_status,
                "last_delivery_error_code": "",
                "last_delivery_error_message": "",
            }
            membership = repository.upsert_account_membership(
                account_id=account_id,
                member_ref=normalized_member_ref,
                role=ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN,
                status=next_status,
                metadata_json=_normalize_portal_membership_metadata(
                    member_ref=normalized_member_ref,
                    status=next_status,
                    metadata_json=updated_metadata,
                ),
            )
            payload: dict[str, object] = {
                "account_id": account_id,
                "member_ref": normalized_member_ref,
                "email": normalized_email,
                "delivery": delivery_mode,
                "delivery_status": delivery_status,
                "last_invited_at": now_value,
                "invite_count": invite_count,
                "membership": self._serialize_account_membership(membership),
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="account_membership.invite_resend",
                outcome="succeeded",
                account_id=account_id,
                scope_kind="account_membership",
                scope_id=f"{account_id}:{normalized_member_ref}",
                payload_json=payload,
            )
            session.commit()
            return payload

    def disable_admin_account_member(
        self,
        *,
        account_id: str,
        member_ref: str,
        platform_role: str,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        assert_platform_admin_capability(
            role=platform_role,
            capability="can_manage_accounts",
            error_code="service.platform_admin_role_forbidden",
            message="platform admin cannot disable portal members",
        )
        normalized_member_ref = str(member_ref or "").strip()
        disabled_at = self._serialize_datetime(self.now_factory())
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            account = repository.get_account(account_id)
            if account is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )
            membership = repository.get_account_membership(
                account_id=account_id,
                member_ref=normalized_member_ref,
            )
            if membership is None:
                raise CommercialNotFoundError(
                    "service.account_membership_not_found",
                    f"member '{normalized_member_ref}' was not found in account '{account_id}'",
                )
            if str(membership.status or "") == ACCOUNT_MEMBERSHIP_STATUS_DISABLED:
                return {
                    "account_id": account_id,
                    "member_ref": normalized_member_ref,
                    "status": ACCOUNT_MEMBERSHIP_STATUS_DISABLED,
                }
            updated_metadata = {
                **dict(getattr(membership, "metadata_json", None) or {}),
                "disabled_via": "admin_accounts_detail",
                "disabled_at": disabled_at,
                "disabled_reason": "admin_disabled",
                "invite_state": "disabled",
            }
            membership = repository.upsert_account_membership(
                account_id=account_id,
                member_ref=normalized_member_ref,
                role=ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN,
                status=ACCOUNT_MEMBERSHIP_STATUS_DISABLED,
                metadata_json=_normalize_portal_membership_metadata(
                    member_ref=normalized_member_ref,
                    status=ACCOUNT_MEMBERSHIP_STATUS_DISABLED,
                    metadata_json=updated_metadata,
                ),
            )
            payload: dict[str, object] = {
                "account_id": account_id,
                "member_ref": normalized_member_ref,
                "status": ACCOUNT_MEMBERSHIP_STATUS_DISABLED,
                "disabled_at": disabled_at,
                "membership": self._serialize_account_membership(membership),
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="account_membership.disable",
                outcome="succeeded",
                account_id=account_id,
                scope_kind="account_membership",
                scope_id=f"{account_id}:{normalized_member_ref}",
                payload_json=payload,
            )
            session.commit()
            return payload

    def enable_admin_account_member(
        self,
        *,
        account_id: str,
        member_ref: str,
        platform_role: str,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        assert_platform_admin_capability(
            role=platform_role,
            capability="can_manage_accounts",
            error_code="service.platform_admin_role_forbidden",
            message="platform admin cannot enable portal members",
        )
        normalized_member_ref = str(member_ref or "").strip()
        enabled_at = self._serialize_datetime(self.now_factory())
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            account = repository.get_account(account_id)
            if account is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )
            membership = repository.get_account_membership(
                account_id=account_id,
                member_ref=normalized_member_ref,
            )
            if membership is None:
                raise CommercialNotFoundError(
                    "service.account_membership_not_found",
                    f"member '{normalized_member_ref}' was not found in account '{account_id}'",
                )
            if str(membership.status or "") == ACCOUNT_MEMBERSHIP_STATUS_ACTIVE:
                return {
                    "account_id": account_id,
                    "member_ref": normalized_member_ref,
                    "status": ACCOUNT_MEMBERSHIP_STATUS_ACTIVE,
                }
            metadata = dict(getattr(membership, "metadata_json", None) or {})
            metadata.pop("disabled_at", None)
            metadata.pop("disabled_via", None)
            metadata.pop("disabled_reason", None)
            updated_metadata = {
                **metadata,
                "enabled_via": "admin_accounts_detail",
                "enabled_at": enabled_at,
                "invite_state": "accepted" if metadata.get("last_login_at") else "pending",
            }
            membership = repository.upsert_account_membership(
                account_id=account_id,
                member_ref=normalized_member_ref,
                role=ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN,
                status=ACCOUNT_MEMBERSHIP_STATUS_ACTIVE,
                metadata_json=_normalize_portal_membership_metadata(
                    member_ref=normalized_member_ref,
                    status=ACCOUNT_MEMBERSHIP_STATUS_ACTIVE,
                    metadata_json=updated_metadata,
                ),
            )
            payload: dict[str, object] = {
                "account_id": account_id,
                "member_ref": normalized_member_ref,
                "status": ACCOUNT_MEMBERSHIP_STATUS_ACTIVE,
                "enabled_at": enabled_at,
                "membership": self._serialize_account_membership(membership),
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="account_membership.enable",
                outcome="succeeded",
                account_id=account_id,
                scope_kind="account_membership",
                scope_id=f"{account_id}:{normalized_member_ref}",
                payload_json=payload,
            )
            session.commit()
            return payload

    def complete_portal_member_login(
        self,
        *,
        member_ref: str,
        login_at: datetime | None = None,
    ) -> dict[str, object]:
        normalized_member_ref = str(member_ref or "").strip()
        if not normalized_member_ref:
            raise CommercialPermissionError(
                "service.portal_member_ref_required",
                "portal member ref is required",
            )
        resolved_login_at = login_at or self.now_factory()
        updated_items: list[dict[str, object]] = []
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            memberships = repository.list_account_memberships(
                member_ref=normalized_member_ref,
                statuses=sorted(PORTAL_MEMBER_ALLOWED_LOGIN_STATUSES),
                limit=None,
            )
            if not memberships:
                raise CommercialPermissionError(
                    "service.portal_membership_required",
                    f"member '{normalized_member_ref}' is not active for any accessible account",
                )
            for membership in memberships:
                metadata = dict(getattr(membership, "metadata_json", None) or {})
                metadata["last_login_at"] = self._serialize_datetime(resolved_login_at)
                metadata.setdefault("enabled_at", self._serialize_datetime(resolved_login_at))
                metadata["invite_state"] = "accepted"
                membership.status = ACCOUNT_MEMBERSHIP_STATUS_ACTIVE
                membership.metadata_json = _normalize_portal_membership_metadata(
                    member_ref=membership.member_ref,
                    status=membership.status,
                    metadata_json=metadata,
                )
                updated_items.append(self._serialize_account_membership(membership))
            session.commit()
        return {
            "member_ref": normalized_member_ref,
            "last_login_at": self._serialize_datetime(resolved_login_at),
            "memberships": updated_items,
        }

    def resolve_portal_member_login(
        self,
        *,
        email: str,
    ) -> dict[str, object]:
        normalized_email = email.strip().lower()
        if not normalized_email or "@" not in normalized_email or " " in normalized_email:
            raise CommercialPermissionError(
                "service.portal_email_invalid",
                "a valid portal email is required",
            )

        member_ref = f"user:{normalized_email}"
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            candidate_accounts = self._list_resolved_portal_account_memberships(
                repository,
                member_ref=member_ref,
            )
            candidate_sites = repository.list_sites_for_member(
                member_ref=member_ref,
                membership_statuses=sorted(PORTAL_MEMBER_ALLOWED_LOGIN_STATUSES),
            )
        account_ids = {
            str(getattr(account, "account_id", "") or "")
            for account, _membership in candidate_accounts
        }
        items = []
        for site, membership in candidate_sites:
            if not _portal_membership_has_allowed_role(membership):
                continue
            if site.account_id not in account_ids:
                continue
            items.append(
                {
                    "member_ref": membership.member_ref,
                    "identity_type": _resolve_identity_type(
                        str(getattr(membership, "role", "") or "")
                    ),
                    "allowed_actions": _resolve_portal_allowed_actions(
                        str(getattr(membership, "role", "") or "")
                    ),
                    "role": _normalize_customer_membership_role(str(getattr(membership, "role", "") or "")),
                    "status": membership.status,
                    "site": cast(Any, self)._serialize_site(site),
                }
            )
        account_items = [
            self._serialize_portal_account_context(
                account,
                membership,
                accessible_sites=[
                    site
                    for site, site_membership in candidate_sites
                    if site.account_id == getattr(account, "account_id", "")
                    and _portal_membership_has_allowed_role(site_membership)
                ],
            )
            for account, membership in candidate_accounts
        ]
        if not account_items:
            raise CommercialPermissionError(
                "service.portal_email_not_found",
                f"no invite-only portal memberships were found for '{normalized_email}'",
            )
        return {
            "email": normalized_email,
            "member_ref": member_ref,
            "sites": items,
            "accounts": account_items,
        }

    def get_portal_member_summary(
        self,
        *,
        member_ref: str,
        selected_site_id: str = "",
    ) -> dict[str, object]:
        normalized_member_ref = str(member_ref or "").strip()
        if not normalized_member_ref:
            raise CommercialPermissionError(
                "service.portal_member_ref_required",
                "portal member_ref is required",
            )

        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            identity = repository.get_portal_member_identity_by_member_ref(
                member_ref=normalized_member_ref,
            )
            account_contexts = cast(Any, self).list_portal_accounts(
                member_ref=normalized_member_ref
            )

        account_items = [
            item
            for item in list(account_contexts.get("items") or [])
            if isinstance(item, dict)
        ]
        roles = sorted(
            {
                str(item.get("identity_type") or "").strip()
                for item in account_items
                if str(item.get("identity_type") or "").strip()
            }
        )
        accessible_sites_count = sum(
            max(0, int(item.get("site_count") or 0))
            for item in account_items
        )
        identity_metadata = (
            dict(getattr(identity, "metadata_json", None) or {})
            if identity is not None
            else {}
        )
        return {
            "member_ref": normalized_member_ref,
            "email": _normalize_portal_member_email(
                normalized_member_ref,
                {
                    "email": str(getattr(identity, "email", "") or ""),
                    **identity_metadata,
                },
            ),
            "auth_mode": "magic-link",
            "roles": roles,
            "identity_type": IDENTITY_TYPE_USER_ADMIN,
            "allowed_actions": sorted(
                {
                    action
                    for item in account_items
                    for action in list(item.get("allowed_actions") or [])
                    if str(action).strip()
                }
            ),
            "accessible_sites_count": accessible_sites_count,
            "selected_site_id": str(selected_site_id or ""),
            "memberships": [
                {
                    "account_id": str(item.get("account_id") or ""),
                    "identity_type": str(
                        item.get("identity_type") or IDENTITY_TYPE_USER_ADMIN
                    ),
                    "allowed_actions": [
                        str(action)
                        for action in list(item.get("allowed_actions") or [])
                        if str(action).strip()
                    ],
                    "role": _normalize_customer_membership_role(str(item.get("role") or "")),
                    "membership_status": str(item.get("membership_status") or ""),
                    "site_count": max(0, int(item.get("site_count") or 0)),
                }
                for item in account_items
            ],
        }

    def upsert_account_subscription(
        self,
        *,
        subscription_id: str | None,
        account_id: str,
        plan_id: str,
        plan_version_id: str,
        status: str = SUBSCRIPTION_STATUS_ACTIVE,
        current_period_start_at: datetime | None = None,
        current_period_end_at: datetime | None = None,
        metadata_json: dict[str, object] | None = None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        resolved_subscription_id = subscription_id or f"sub_{uuid4().hex}"
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            payload = self._upsert_account_subscription_in_session(
                repository=repository,
                subscription_id=resolved_subscription_id,
                account_id=account_id,
                plan_id=plan_id,
                plan_version_id=plan_version_id,
                status=status,
                current_period_start_at=current_period_start_at,
                current_period_end_at=current_period_end_at,
                metadata_json=metadata_json,
                audit_context=audit_context,
            )
            session.commit()
            return payload

    def suspend_account_subscription(
        self,
        account_id: str,
        *,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            subscription = repository.get_latest_account_subscription(account_id)
            if subscription is None:
                raise CommercialNotFoundError(
                    "service.subscription_not_found",
                    f"no subscription was found for account '{account_id}'",
                )
            subscription.status = SUBSCRIPTION_STATUS_SUSPENDED
            subscription.suspended_at = now
            payload = cast(Any, self)._serialize_subscription(subscription)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="subscription.suspend",
                outcome="succeeded",
                account_id=subscription.account_id,
                subscription_id=subscription.subscription_id,
                plan_id=subscription.plan_id,
                plan_version_id=subscription.plan_version_id,
                scope_kind="subscription",
                scope_id=subscription.subscription_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def cancel_account_subscription(
        self,
        account_id: str,
        *,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            subscription = repository.get_latest_account_subscription(account_id)
            if subscription is None:
                raise CommercialNotFoundError(
                    "service.subscription_not_found",
                    f"no subscription was found for account '{account_id}'",
                )
            subscription.status = SUBSCRIPTION_STATUS_CANCELED
            subscription.canceled_at = now
            payload = cast(Any, self)._serialize_subscription(subscription)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="subscription.cancel",
                outcome="succeeded",
                account_id=subscription.account_id,
                subscription_id=subscription.subscription_id,
                plan_id=subscription.plan_id,
                plan_version_id=subscription.plan_version_id,
                scope_kind="subscription",
                scope_id=subscription.subscription_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def _bind_default_free_subscription_for_account_in_session(
        self,
        *,
        repository: CommercialRepository,
        account_id: str,
        audit_context: ServiceAuditContext | None,
    ) -> dict[str, object] | None:
        existing_subscriptions = repository.list_account_subscriptions(account_id)
        if existing_subscriptions:
            return None

        service = cast(Any, self)
        plan_id, plan_version_id = service._ensure_plan_free_version_in_session(
            repository=repository
        )
        now = self.now_factory()
        subscription, snapshot = service._bind_subscription_in_session(
            repository=repository,
            subscription_id=f"sub_{account_id}_free",
            account_id=account_id,
            plan_id=plan_id,
            plan_version_id=plan_version_id,
            status=SUBSCRIPTION_STATUS_ACTIVE,
            current_period_start_at=now,
            current_period_end_at=now + timedelta(days=30),
            metadata_json={
                "source": DEFAULT_FREE_SUBSCRIPTION_SOURCE,
                "tier_id": "starter",
                "package_alias": PLAN_TIER_REGISTRY["starter"].get("package_alias") or "Free",
                "plan_kind": DEFAULT_FREE_PLAN_KIND,
                "site_limit": self._coerce_int(
                    PLAN_TIER_REGISTRY["starter"].get("site_limit")
                )
                or 1,
            },
        )
        payload = {
            "subscription": service._serialize_subscription(subscription),
            "entitlement_snapshot": service._serialize_entitlement_snapshot(snapshot),
        }
        self._record_service_audit_in_session(
            repository=repository,
            audit_context=audit_context,
            event_kind="subscription.bind",
            outcome="succeeded",
            account_id=account_id,
            subscription_id=subscription.subscription_id,
            plan_id=plan_id,
            plan_version_id=plan_version_id,
            scope_kind="subscription",
            scope_id=subscription.subscription_id,
            payload_json=payload,
        )
        return payload

    def _upsert_account_subscription_in_session(
        self,
        *,
        repository: CommercialRepository,
        subscription_id: str,
        account_id: str,
        plan_id: str,
        plan_version_id: str,
        status: str = SUBSCRIPTION_STATUS_ACTIVE,
        current_period_start_at: datetime | None = None,
        current_period_end_at: datetime | None = None,
        metadata_json: dict[str, object] | None = None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        now = self.now_factory()
        if repository.get_account(account_id) is None:
            raise CommercialNotFoundError(
                "service.account_not_found",
                f"account '{account_id}' was not found",
            )
        requested_tier_id = str((metadata_json or {}).get("tier_id") or plan_id).strip()
        if (
            requested_tier_id in PLAN_TIER_REGISTRY
            and (
                repository.get_plan(plan_id) is None
                or repository.get_plan_version(plan_version_id) is None
            )
        ):
            service = cast(Any, self)
            ensured_plan_id, ensured_plan_version_id = service._ensure_plan_tier_version_in_session(
                repository=repository,
                tier_id=requested_tier_id,
            )
            plan_id = ensured_plan_id
            plan_version_id = ensured_plan_version_id
        plan = repository.get_plan(plan_id)
        if plan is None:
            raise CommercialNotFoundError(
                "service.plan_not_found",
                f"plan '{plan_id}' was not found",
            )
        plan_version = repository.get_plan_version(plan_version_id)
        if plan_version is None or plan_version.plan_id != plan.plan_id:
            raise CommercialNotFoundError(
                "service.plan_version_not_found",
                f"plan version '{plan_version_id}' was not found for plan '{plan_id}'",
            )
        service = cast(Any, self)
        subscription, snapshot = service._bind_subscription_in_session(
            repository=repository,
            subscription_id=subscription_id,
            account_id=account_id,
            plan_id=plan_id,
            plan_version_id=plan_version_id,
            status=status,
            current_period_start_at=current_period_start_at or now,
            current_period_end_at=current_period_end_at or (now + timedelta(days=30)),
            metadata_json=metadata_json,
        )
        covered_sites = repository.list_sites(account_id=subscription.account_id, limit=None)
        period_start_at, period_end_at = service._resolve_period(subscription, now)
        service._refresh_subscription_billing_snapshots_in_session(
            repository=repository,
            subscription=subscription,
            covered_sites=covered_sites,
            period_start_at=period_start_at,
            period_end_at=period_end_at,
        )
        payload = {
            "subscription": service._serialize_subscription(subscription),
            "entitlement_snapshot": service._serialize_entitlement_snapshot(snapshot),
        }
        self._record_service_audit_in_session(
            repository=repository,
            audit_context=audit_context,
            event_kind="subscription.upsert",
            outcome="succeeded",
            account_id=account_id,
            subscription_id=subscription.subscription_id,
            plan_id=plan_id,
            plan_version_id=plan_version_id,
            scope_kind="subscription",
            scope_id=subscription.subscription_id,
            payload_json=payload,
        )
        return payload

    def _serialize_account(self, account: object) -> dict[str, object]:
        return {
            "account_id": str(getattr(account, "account_id", "") or ""),
            "name": str(getattr(account, "name", "") or ""),
            "status": str(getattr(account, "status", "") or ""),
            "metadata": getattr(account, "metadata_json", None) or {},
            "created_at": self._serialize_datetime(getattr(account, "created_at", None)),
            "updated_at": self._serialize_datetime(getattr(account, "updated_at", None)),
        }

    def _serialize_account_membership(
        self,
        membership: object,
        *,
        accessible_sites: list[Site] | None = None,
    ) -> dict[str, object]:
        metadata = _normalize_portal_membership_metadata(
            member_ref=str(getattr(membership, "member_ref", "") or ""),
            status=str(getattr(membership, "status", "") or ""),
            metadata_json=getattr(membership, "metadata_json", None) or {},
        )
        invite_count_raw = metadata.get("invite_count", 0)
        try:
            invite_count = self._coerce_int(invite_count_raw)
        except (TypeError, ValueError):
            invite_count = 0
        return {
            "account_id": str(getattr(membership, "account_id", "") or ""),
            "member_ref": str(getattr(membership, "member_ref", "") or ""),
            "email": _normalize_portal_member_email(
                str(getattr(membership, "member_ref", "") or ""),
                metadata,
            ),
            "identity_type": _resolve_identity_type(
                str(getattr(membership, "role", "") or "")
            ),
            "allowed_actions": _resolve_portal_allowed_actions(
                str(getattr(membership, "role", "") or "")
            ),
            "role": str(getattr(membership, "role", "") or ""),
            "status": str(getattr(membership, "status", "") or ""),
            "invite_state": str(metadata.get("invite_state") or ""),
            "invite_count": invite_count,
            "invited_at": self._serialize_datetime(cast(Any, metadata.get("invited_at"))),
            "last_invited_at": self._serialize_datetime(
                cast(Any, metadata.get("last_invited_at"))
            ),
            "invite_expires_at": self._serialize_datetime(
                cast(Any, metadata.get("invite_expires_at"))
            ),
            "last_delivery_status": str(metadata.get("last_delivery_status") or ""),
            "last_delivery_error_code": str(metadata.get("last_delivery_error_code") or ""),
            "last_delivery_error_message": str(metadata.get("last_delivery_error_message") or ""),
            "last_login_at": self._serialize_datetime(
                cast(Any, metadata.get("last_login_at"))
            ),
            "enabled_at": self._serialize_datetime(cast(Any, metadata.get("enabled_at"))),
            "disabled_at": self._serialize_datetime(
                cast(Any, metadata.get("disabled_at"))
            ),
            "disabled_reason": str(metadata.get("disabled_reason") or ""),
            "accessible_sites": [
                {
                    "site_id": site.site_id,
                    "name": site.name,
                    "status": site.status,
                }
                for site in (accessible_sites or [])
            ],
            "metadata": metadata,
            "created_at": self._serialize_datetime(getattr(membership, "created_at", None)),
            "updated_at": self._serialize_datetime(getattr(membership, "updated_at", None)),
        }

    def _serialize_portal_account_context(
        self,
        account: object,
        membership: object,
        *,
        accessible_sites: list[Site] | None = None,
    ) -> dict[str, object]:
        sites = accessible_sites or []
        return {
            "account_id": str(getattr(account, "account_id", "") or ""),
            "name": str(getattr(account, "name", "") or ""),
            "status": str(getattr(account, "status", "") or ""),
            "member_ref": str(getattr(membership, "member_ref", "") or ""),
            "identity_type": _resolve_identity_type(
                str(getattr(membership, "role", "") or "")
            ),
            "allowed_actions": _resolve_portal_allowed_actions(
                str(getattr(membership, "role", "") or "")
            ),
            "role": _normalize_customer_membership_role(str(getattr(membership, "role", "") or "")),
            "membership_status": str(getattr(membership, "status", "") or ""),
            "site_count": len(sites),
            "sites": [cast(Any, self)._serialize_site(site) for site in sites],
        }

    def _list_resolved_portal_account_memberships(
        self,
        repository: CommercialRepository,
        *,
        member_ref: str,
        statuses: set[str] | None = None,
    ) -> list[tuple[object, object]]:
        memberships = repository.list_account_memberships(
            member_ref=member_ref,
            statuses=sorted(statuses or PORTAL_MEMBER_ALLOWED_LOGIN_STATUSES),
            limit=None,
        )
        items: list[tuple[object, object]] = []
        for membership in memberships:
            if not _portal_membership_has_allowed_role(membership):
                continue
            account_id = str(getattr(membership, "account_id", "") or "").strip()
            if not account_id:
                continue
            account = repository.get_account(account_id)
            if account is None or str(getattr(account, "status", "") or "") != ACCOUNT_STATUS_ACTIVE:
                continue
            items.append((account, membership))
        items.sort(
            key=lambda item: (
                _portal_membership_role_priority(str(getattr(item[1], "role", "") or "")),
                str(getattr(item[0], "account_id", "") or ""),
            )
        )
        return items

    def _assert_account_site_capacity(
        self,
        *,
        repository: CommercialRepository,
        account_id: str,
        snapshot: object,
    ) -> None:
        site_limit = cast(Any, self)._resolve_site_limit(snapshot=snapshot)
        site_counts = repository.count_sites_by_account(
            account_ids=[account_id],
        )
        current_count = self._coerce_int(site_counts.get(account_id, 0))
        if current_count >= site_limit:
            raise CommercialPermissionError(
                "service.site_limit_exceeded",
                f"account '{account_id}' has reached its site limit for the current subscription",
            )
