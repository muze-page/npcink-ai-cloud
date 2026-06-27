"""Commercial service: site and site-key operations mixin."""

from __future__ import annotations

import secrets
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import uuid4

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.callback_security import (
    RuntimeCallbackTargetValidationError,
    validate_runtime_callback_target,
)
from app.core.db import get_session
from app.core.models import (
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE,
    PRINCIPAL_STATUS_ACTIVE,
    SITE_API_KEY_STATUS_ACTIVE,
    SITE_API_KEY_STATUS_EXPIRED,
    SITE_API_KEY_STATUS_REVOKED,
    SITE_STATUS_ACTIVE,
    SITE_STATUS_ARCHIVED,
    SITE_STATUS_PROVISIONING,
    SITE_STATUS_SUSPENDED,
    SITE_USER_GRANT_STATUS_ACTIVE,
    AccountSubscription,
    Site,
    SiteApiKey,
)
from app.core.secrets import (
    encrypt_runtime_terminal_callback_secret,
    encrypt_site_api_signing_secret,
)
from app.core.security import build_secret_hash
from app.domain.commercial.audit_context import ServiceAuditContext
from app.domain.commercial.customer_api_keys import expand_api_key_scopes
from app.domain.commercial.errors import (
    CommercialNotFoundError,
    CommercialPermissionError,
    CommercialValidationError,
)
from app.domain.commercial.identity import (
    IDENTITY_TYPE_USER,
    USER_ROLE_USER,
    _extract_site_wordpress_url,
    _normalize_portal_site_url,
    _slugify_portal_site_segment,
    normalize_user_role,
    resolve_principal_allowed_actions,
)
from app.domain.commercial.mixins._audit_mixin import CommercialServiceAuditMixin
from app.domain.commercial.service import (
    DEFAULT_PLAN_TIER_ID,
    PLAN_TIER_REGISTRY,
)


class CommercialServiceSiteMixin(CommercialServiceAuditMixin):
    def provision_site(
        self,
        *,
        site_id: str,
        account_id: str,
        name: str,
        status: str = SITE_STATUS_PROVISIONING,
        metadata_json: dict[str, object] | None = None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            account = repository.get_account(account_id)
            if account is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )
            if str(account.status or "") != ACCOUNT_STATUS_ACTIVE:
                raise CommercialPermissionError(
                    "service.account_inactive",
                    f"account '{account_id}' is not active",
                )
            subscription = repository.get_runtime_subscription(account_id)
            snapshot = (
                repository.get_active_entitlement_snapshot(
                    account_id,
                    subscription_id=subscription.subscription_id,
                )
                if subscription is not None
                else None
            )
            existing_site = repository.get_site(site_id)
            if existing_site is None and snapshot is not None:
                cast(Any, self)._assert_account_site_capacity(
                    repository=repository,
                    account_id=account_id,
                    snapshot=snapshot,
                )
            site = repository.upsert_site(
                site_id=site_id,
                account_id=account_id,
                name=name or site_id,
                status=status,
                metadata_json=metadata_json,
                provisioned_at=now,
            )
            payload = self._serialize_site(site)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="site.provision",
                outcome="succeeded",
                account_id=account_id,
                site_id=site.site_id,
                scope_kind="site",
                scope_id=site.site_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def provision_portal_site(
        self,
        *,
        account_id: str,
        principal_id: str,
        wordpress_url: str,
        site_name: str = "",
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_account_id = str(account_id or "").strip()
        normalized_principal_id = str(principal_id or "").strip()
        canonical_wordpress_url, site_source = _normalize_portal_site_url(wordpress_url)
        site_slug = _slugify_portal_site_segment(site_source)
        if not normalized_account_id:
            raise CommercialPermissionError(
                "service.account_id_required",
                "account id is required",
            )
        if not normalized_principal_id:
            raise CommercialPermissionError(
                "service.principal_id_required",
                "principal id is required",
            )
        if not site_slug:
            raise CommercialPermissionError(
                "service.portal_site_slug_invalid",
                "wordpress site url could not be converted into a stable site id",
            )
        normalized_site_id = f"site_{site_slug}"
        resolved_site_name = (
            str(site_name or "").strip()
            or urlsplit(canonical_wordpress_url).hostname
            or normalized_site_id
        )
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            account = repository.get_account(normalized_account_id)
            if account is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{normalized_account_id}' was not found",
                )
            if str(account.status or "") != ACCOUNT_STATUS_ACTIVE:
                raise CommercialPermissionError(
                    "service.portal_account_inactive",
                    f"account '{normalized_account_id}' is not active",
                )
            identity = repository.get_principal_identity_by_ref(
                principal_id=normalized_principal_id,
            )
            if identity is None or identity.status != PRINCIPAL_STATUS_ACTIVE:
                raise CommercialPermissionError(
                    "service.principal_access_required",
                    f"principal '{normalized_principal_id}' is not active",
                )
            existing_site = repository.get_site(normalized_site_id)
            if existing_site is not None:
                if str(existing_site.account_id or "") == normalized_account_id:
                    raise CommercialPermissionError(
                        "service.portal_site_exists",
                        f"site '{normalized_site_id}' already exists in account '{normalized_account_id}'",
                    )
                raise CommercialPermissionError(
                    "service.portal_site_conflict",
                    f"site id '{normalized_site_id}' is already bound to another account",
                )
            subscription = repository.get_runtime_subscription(normalized_account_id)
            if subscription is None:
                raise CommercialPermissionError(
                    "service.subscription_required",
                    f"account '{normalized_account_id}' does not have an active customer subscription",
                )
            snapshot = repository.get_active_entitlement_snapshot(
                normalized_account_id,
                subscription_id=subscription.subscription_id,
            )
            if snapshot is None:
                raise CommercialPermissionError(
                    "service.entitlement_snapshot_required",
                    f"account '{normalized_account_id}' does not have an active entitlement snapshot",
                )
            service = cast(Any, self)
            service._assert_account_site_capacity(
                repository=repository,
                account_id=normalized_account_id,
                snapshot=snapshot,
            )
            site = repository.upsert_site(
                site_id=normalized_site_id,
                account_id=normalized_account_id,
                name=resolved_site_name,
                status=SITE_STATUS_PROVISIONING,
                metadata_json={
                    "source": "portal_self_serve",
                    "wordpress_url": canonical_wordpress_url,
                    "created_via": "portal_connect_site",
                },
                provisioned_at=now,
            )
            repository.upsert_principal_site_grant(
                grant_id=f"sadmg_{uuid4().hex}",
                principal_id=identity.principal_id,
                site_id=site.site_id,
                status=SITE_USER_GRANT_STATUS_ACTIVE,
                metadata_json={"source": "portal_connect_site"},
            )
            repository.upsert_account_user_membership(
                membership_id=f"aum_{uuid4().hex}",
                principal_id=identity.principal_id,
                account_id=normalized_account_id,
                role=normalize_user_role(USER_ROLE_USER),
                status=ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE,
                allowed_actions_json=resolve_principal_allowed_actions(),
                metadata_json={"source": "portal_connect_site"},
            )
            payload = {
                "account_id": normalized_account_id,
                "principal_id": normalized_principal_id,
                "identity_type": IDENTITY_TYPE_USER,
                "role": USER_ROLE_USER,
                "wordpress_url": canonical_wordpress_url,
                "site": self._serialize_site(site),
                "subscription": service._serialize_subscription(subscription),
                "commercial_onboarding": {
                    "auto_bound": False,
                    "tier_id": service._infer_plan_tier_id(
                        {
                            "plan_id": subscription.plan_id,
                            "metadata": subscription.metadata_json or {},
                        },
                        [],
                    ),
                    "package_alias": str(
                        (subscription.metadata_json or {}).get("package_alias")
                        or service._build_plan_tier_summary(
                            {
                                "plan_id": subscription.plan_id,
                                "metadata": subscription.metadata_json or {},
                            },
                            [],
                        ).get("package_alias")
                        or ""
                    ),
                },
                "next": {
                    "keys_path": f"/portal/keys?site={site.site_id}",
                    "sites_path": f"/portal/sites?site={site.site_id}",
                },
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="site.provision",
                outcome="succeeded",
                account_id=normalized_account_id,
                site_id=site.site_id,
                scope_kind="site",
                scope_id=site.site_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def activate_site(
        self,
        site_id: str,
        *,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            site = repository.get_site(site_id)
            if site is None:
                raise CommercialNotFoundError(
                    "service.site_not_found",
                    f"site '{site_id}' was not found",
                )
            site.status = SITE_STATUS_ACTIVE
            if site.provisioned_at is None:
                site.provisioned_at = now
            site.activated_at = now
            site.suspended_at = None
            site.suspension_reason = None
            payload = self._serialize_site(site)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="site.activate",
                outcome="succeeded",
                account_id=site.account_id,
                site_id=site.site_id,
                scope_kind="site",
                scope_id=site.site_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def suspend_site(
        self,
        site_id: str,
        *,
        reason: str = "",
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            site = repository.get_site(site_id)
            if site is None:
                raise CommercialNotFoundError(
                    "service.site_not_found",
                    f"site '{site_id}' was not found",
                )
            site.status = SITE_STATUS_SUSPENDED
            site.suspended_at = now
            site.suspension_reason = reason or None
            payload = self._serialize_site(site)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="site.suspend",
                outcome="succeeded",
                account_id=site.account_id,
                site_id=site.site_id,
                scope_kind="site",
                scope_id=site.site_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def archive_site(
        self,
        site_id: str,
        *,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            site = repository.get_site(site_id)
            if site is None:
                raise CommercialNotFoundError(
                    "service.site_not_found",
                    f"site '{site_id}' was not found",
                )
            metadata = dict(site.metadata_json or {})
            lifecycle = metadata.get("portal_lifecycle")
            lifecycle = dict(lifecycle) if isinstance(lifecycle, dict) else {}
            previous_status = str(site.status or "").strip()
            lifecycle["previous_status"] = previous_status
            lifecycle["archived_at"] = self._serialize_datetime(now)
            lifecycle["archived"] = True
            metadata["portal_lifecycle"] = lifecycle
            site.metadata_json = metadata
            site.status = SITE_STATUS_ARCHIVED
            payload = self._serialize_site(site)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="site.archive",
                outcome="succeeded",
                account_id=site.account_id,
                site_id=site.site_id,
                scope_kind="site",
                scope_id=site.site_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def restore_site(
        self,
        site_id: str,
        *,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            site = repository.get_site(site_id)
            if site is None:
                raise CommercialNotFoundError(
                    "service.site_not_found",
                    f"site '{site_id}' was not found",
                )
            metadata = dict(site.metadata_json or {})
            lifecycle = metadata.get("portal_lifecycle")
            lifecycle = dict(lifecycle) if isinstance(lifecycle, dict) else {}
            previous_status = str(lifecycle.get("previous_status") or "").strip()
            if previous_status not in {
                SITE_STATUS_ACTIVE,
                SITE_STATUS_PROVISIONING,
                SITE_STATUS_SUSPENDED,
            }:
                previous_status = (
                    SITE_STATUS_ACTIVE
                    if site.activated_at is not None
                    else SITE_STATUS_PROVISIONING
                )
            lifecycle["archived"] = False
            lifecycle["restored_at"] = self._serialize_datetime(now)
            metadata["portal_lifecycle"] = lifecycle
            site.metadata_json = metadata
            site.status = previous_status
            payload = self._serialize_site(site)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="site.restore",
                outcome="succeeded",
                account_id=site.account_id,
                site_id=site.site_id,
                scope_kind="site",
                scope_id=site.site_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def update_site_runtime_callbacks(
        self,
        *,
        site_id: str,
        terminal_callback: dict[str, object] | None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            site = repository.get_site(site_id)
            if site is None:
                raise CommercialNotFoundError(
                    "service.site_not_found",
                    f"site '{site_id}' was not found",
                )

            metadata = dict(site.metadata_json or {})
            runtime_callbacks = metadata.get("runtime_callbacks")
            runtime_callbacks = (
                dict(runtime_callbacks) if isinstance(runtime_callbacks, dict) else {}
            )
            normalized_terminal = cast(Any, self)._normalize_runtime_terminal_callback(
                terminal_callback
            )
            callback_url = str(normalized_terminal.get("callback_url") or "")
            if callback_url:
                try:
                    validate_runtime_callback_target(callback_url)
                except RuntimeCallbackTargetValidationError as error:
                    raise CommercialValidationError(
                        "service.validation_error",
                        str(error),
                    ) from error
            secret_ciphertext = encrypt_runtime_terminal_callback_secret(
                str(normalized_terminal.get("secret") or ""),
                settings=self.settings,
            )
            stored_terminal = {
                "enabled": bool(normalized_terminal.get("enabled")),
                "callback_url": str(normalized_terminal.get("callback_url") or ""),
                "key_id": str(normalized_terminal.get("key_id") or ""),
                "secret_ciphertext": secret_ciphertext,
                "callback_id": str(normalized_terminal.get("callback_id") or "runtime_terminal"),
            }
            runtime_callbacks["terminal"] = stored_terminal
            metadata["runtime_callbacks"] = runtime_callbacks
            metadata["runtime_terminal_callback_enabled"] = bool(normalized_terminal.get("enabled"))
            metadata["runtime_terminal_callback_url"] = str(
                normalized_terminal.get("callback_url") or ""
            )
            metadata["runtime_terminal_callback_key_id"] = str(
                normalized_terminal.get("key_id") or ""
            )
            metadata["runtime_terminal_callback_id"] = str(
                normalized_terminal.get("callback_id") or "runtime_terminal"
            )
            metadata.pop("runtime_terminal_callback_secret", None)
            site.metadata_json = metadata

            payload: dict[str, object] = {
                "site_id": site.site_id,
                "runtime_callback": {
                    "enabled": bool(normalized_terminal.get("enabled")),
                    "callback_url": str(normalized_terminal.get("callback_url") or ""),
                    "key_id": str(normalized_terminal.get("key_id") or ""),
                    "callback_id": str(
                        normalized_terminal.get("callback_id") or "runtime_terminal"
                    ),
                },
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="site.runtime_callbacks.update",
                outcome="succeeded",
                account_id=site.account_id,
                site_id=site.site_id,
                scope_kind="site",
                scope_id=site.site_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def issue_site_key(
        self,
        *,
        site_id: str,
        key_id: str | None,
        secret: str | None,
        scopes: list[str] | None,
        label: str,
        expires_at: datetime | None,
        metadata_json: dict[str, object] | None = None,
        rotated_from_key_id: str | None = None,
        audit_context: ServiceAuditContext | None = None,
        activate_site_on_issue: bool = False,
    ) -> dict[str, object]:
        resolved_key_id = key_id or f"key_{uuid4().hex}"
        plaintext_secret = secret or f"sk_{secrets.token_urlsafe(24)}"
        now = self.now_factory()
        normalized_scopes = expand_api_key_scopes(scopes)

        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            site = repository.get_site(site_id)
            if site is None:
                raise CommercialNotFoundError(
                    "service.site_not_found",
                    f"site '{site_id}' was not found",
                )
            api_key = repository.upsert_site_key(
                key_id=resolved_key_id,
                site_id=site_id,
                secret_hash=build_secret_hash(plaintext_secret),
                signing_secret_ciphertext=encrypt_site_api_signing_secret(
                    plaintext_secret,
                    settings=self.settings,
                ),
                label=label,
                scopes_json=normalized_scopes,
                metadata_json=metadata_json,
                status=SITE_API_KEY_STATUS_ACTIVE,
                rotated_from_key_id=rotated_from_key_id,
                replaced_by_key_id=None,
                expires_at=expires_at,
                revoked_at=None,
            )
            payload = self._serialize_site_key(api_key)
            payload["secret"] = plaintext_secret
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="site_key.issue",
                outcome="succeeded",
                site_id=site_id,
                key_id=api_key.key_id,
                scope_kind="site_key",
                scope_id=api_key.key_id,
                payload_json=payload,
            )
            if activate_site_on_issue and site.status == SITE_STATUS_PROVISIONING:
                site.status = SITE_STATUS_ACTIVE
                if site.provisioned_at is None:
                    site.provisioned_at = now
                site.activated_at = now
                site.suspended_at = None
                site.suspension_reason = None
                payload["site_status"] = site.status
                payload["site_activated"] = True
                self._record_service_audit_in_session(
                    repository=repository,
                    audit_context=audit_context,
                    event_kind="site.activate",
                    outcome="succeeded",
                    account_id=site.account_id,
                    site_id=site.site_id,
                    key_id=api_key.key_id,
                    scope_kind="site",
                    scope_id=site.site_id,
                    payload_json=self._serialize_site(site),
                )
            else:
                payload["site_status"] = str(site.status or "")
                payload["site_activated"] = False
            session.commit()
            return payload

    def list_site_keys(
        self,
        site_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            if repository.get_site(site_id) is None:
                raise CommercialNotFoundError(
                    "service.site_not_found",
                    f"site '{site_id}' was not found",
                )
            total = repository.count_site_keys(site_id)
            normalized_offset = max(offset, 0)
            normalized_limit = limit if limit is None else max(limit, 1)
            keys = repository.list_site_keys(
                site_id,
                limit=normalized_limit,
                offset=normalized_offset,
            )
            effective_limit = normalized_limit if normalized_limit is not None else total
            next_offset = normalized_offset + len(keys)
            has_more = next_offset < total
            return {
                "site_id": site_id,
                "items": [self._serialize_site_key(item) for item in keys],
                "pagination": {
                    "limit": effective_limit,
                    "offset": normalized_offset,
                    "total": total,
                    "has_more": has_more,
                    "next_offset": next_offset if has_more else None,
                },
                "sort": {
                    "created_at": "desc",
                    "key_id": "desc",
                },
            }

    def rotate_site_key(
        self,
        *,
        site_id: str,
        key_id: str,
        next_key_id: str | None,
        secret: str | None,
        scopes: list[str] | None,
        label: str,
        expires_at: datetime | None,
        metadata_json: dict[str, object] | None = None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        now = self.now_factory()
        normalized_scopes = expand_api_key_scopes(scopes) if scopes is not None else None
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            current = repository.get_site_key(key_id)
            if current is None or current.site_id != site_id:
                raise CommercialNotFoundError(
                    "service.key_not_found",
                    f"site key '{key_id}' was not found for site '{site_id}'",
                )
            resolved_key_id = next_key_id or f"key_{uuid4().hex}"
            plaintext_secret = secret or f"sk_{secrets.token_urlsafe(24)}"
            rotated_key = repository.upsert_site_key(
                key_id=resolved_key_id,
                site_id=site_id,
                secret_hash=build_secret_hash(plaintext_secret),
                signing_secret_ciphertext=encrypt_site_api_signing_secret(
                    plaintext_secret,
                    settings=self.settings,
                ),
                label=label or (current.label or ""),
                scopes_json=(
                    normalized_scopes
                    if normalized_scopes is not None
                    else list(current.scopes_json or [])
                ),
                metadata_json=metadata_json,
                status=SITE_API_KEY_STATUS_ACTIVE,
                rotated_from_key_id=key_id,
                replaced_by_key_id=None,
                expires_at=expires_at,
                revoked_at=None,
            )
            current.status = SITE_API_KEY_STATUS_REVOKED
            current.revoked_at = now
            current.replaced_by_key_id = rotated_key.key_id
            payload: dict[str, object] = {
                "previous": self._serialize_site_key(current),
                "current": {
                    **self._serialize_site_key(rotated_key),
                    "secret": plaintext_secret,
                },
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="site_key.rotate",
                outcome="succeeded",
                site_id=site_id,
                key_id=rotated_key.key_id,
                scope_kind="site_key",
                scope_id=rotated_key.key_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def revoke_site_key(
        self,
        *,
        site_id: str,
        key_id: str,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            api_key = repository.get_site_key(key_id)
            if api_key is None or api_key.site_id != site_id:
                raise CommercialNotFoundError(
                    "service.key_not_found",
                    f"site key '{key_id}' was not found for site '{site_id}'",
                )
            api_key.status = SITE_API_KEY_STATUS_REVOKED
            api_key.revoked_at = now
            payload = self._serialize_site_key(api_key)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="site_key.revoke",
                outcome="succeeded",
                site_id=site_id,
                key_id=api_key.key_id,
                scope_kind="site_key",
                scope_id=api_key.key_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def expire_site_key(
        self,
        *,
        site_id: str,
        key_id: str,
        expires_at: datetime,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            api_key = repository.get_site_key(key_id)
            if api_key is None or api_key.site_id != site_id:
                raise CommercialNotFoundError(
                    "service.key_not_found",
                    f"site key '{key_id}' was not found for site '{site_id}'",
                )
            api_key.status = SITE_API_KEY_STATUS_EXPIRED
            api_key.expires_at = expires_at
            payload = self._serialize_site_key(api_key)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="site_key.expire",
                outcome="succeeded",
                site_id=site_id,
                key_id=api_key.key_id,
                scope_kind="site_key",
                scope_id=api_key.key_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def resolve_portal_site_access(
        self,
        *,
        site_id: str,
        principal_id: str,
        required_roles: set[str] | None = None,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            site = repository.get_site(site_id)
            if site is None:
                raise CommercialNotFoundError(
                    "service.site_not_found",
                    f"site '{site_id}' was not found",
                )
            if not site.account_id:
                raise CommercialPermissionError(
                    "service.portal_account_required",
                    f"site '{site_id}' is not bound to an account",
                )
            account = repository.get_account(site.account_id)
            if account is None or account.status != ACCOUNT_STATUS_ACTIVE:
                raise CommercialPermissionError(
                    "service.portal_account_inactive",
                    f"account '{site.account_id}' is not active",
                )
            grant_pair = repository.get_principal_site_grant(
                principal_id=principal_id,
                site_id=site_id,
            )
            if grant_pair is None:
                raise CommercialPermissionError(
                    "service.principal_access_required",
                    f"principal '{principal_id}' is not active for site '{site_id}'",
                )
            identity, grant = grant_pair
            if (
                identity.status != PRINCIPAL_STATUS_ACTIVE
                or grant.status != SITE_USER_GRANT_STATUS_ACTIVE
            ):
                raise CommercialPermissionError(
                    "service.principal_access_required",
                    f"principal '{principal_id}' is not active for site '{site_id}'",
                )
            membership_row = repository.get_account_user_membership(
                principal_id=principal_id,
                account_id=site.account_id,
            )
            if membership_row is None:
                raise CommercialPermissionError(
                    "service.principal_access_required",
                    f"principal '{principal_id}' is not active for account '{site.account_id}'",
                )
            _account, _membership_identity, membership = membership_row
            if membership.status != ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE:
                raise CommercialPermissionError(
                    "service.principal_access_required",
                    f"principal '{principal_id}' is not active for account '{site.account_id}'",
                )
            role = normalize_user_role(str(membership.role or USER_ROLE_USER))
            allowed_actions = (
                [
                    str(action).strip()
                    for action in (membership.allowed_actions_json or [])
                    if str(action).strip()
                ]
                or resolve_principal_allowed_actions()
            )
            if required_roles is not None and role not in required_roles:
                raise CommercialPermissionError(
                    "service.portal_role_forbidden",
                    f"principal '{principal_id}' lacks required role for site '{site_id}'",
                )
        return {
            "site_id": site.site_id,
            "account_id": site.account_id,
            "principal_id": principal_id,
            "identity_type": IDENTITY_TYPE_USER,
            "allowed_actions": allowed_actions,
            "role": role,
            "site": self._serialize_site(site),
        }

    def list_portal_sites(
        self,
        *,
        principal_id: str,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            items = []
            for site, _identity, grant in repository.list_sites_for_principal(
                principal_id=principal_id,
                grant_statuses=[SITE_USER_GRANT_STATUS_ACTIVE],
            ):
                items.append(
                    {
                        "principal_id": principal_id,
                        "identity_type": IDENTITY_TYPE_USER,
                        "allowed_actions": resolve_principal_allowed_actions(),
                        "role": USER_ROLE_USER,
                        "grant_status": grant.status,
                        "site": self._serialize_site(site),
                    }
                )
            return {
                "principal_id": principal_id,
                "items": items,
            }

    def list_admin_sites(
        self,
        *,
        status: str | None = None,
        account_id: str | None = None,
        subscription_status: str | None = None,
        expires_before: datetime | None = None,
        limit: int = 100,
        usage_window_days: int = 7,
    ) -> dict[str, object]:
        usage_since = self.now_factory() - timedelta(days=max(1, usage_window_days))
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            filtered_site_ids: set[str] | None = None
            if subscription_status or expires_before is not None:
                filtered_subscriptions = repository.list_subscriptions(
                    status=subscription_status,
                    current_period_end_before=expires_before,
                    limit=None,
                )
                filtered_site_ids = {
                    site.site_id
                    for site in repository.list_sites(
                        account_ids=[
                            subscription.account_id
                            for subscription in filtered_subscriptions
                            if subscription.account_id
                        ],
                        limit=None,
                    )
                }
            sites = repository.list_sites(
                status=status,
                account_id=account_id,
                site_ids=sorted(filtered_site_ids) if filtered_site_ids is not None else None,
                limit=limit,
            )
            site_ids = [site.site_id for site in sites]
            account_ids = [site.account_id for site in sites if site.account_id]
            key_counts = repository.count_site_keys_by_site(
                site_ids=site_ids,
                statuses=[SITE_API_KEY_STATUS_ACTIVE],
            )
            subscriptions = repository.list_subscriptions(account_ids=account_ids, limit=None)
            usage_summary = repository.summarize_usage_meter_by_site(
                site_ids=site_ids,
                since=usage_since,
            )
            latest_billing_by_site = repository.get_latest_billing_snapshots_by_site(
                site_ids=site_ids
            )

        service = cast(Any, self)
        latest_subscription_by_account = service._latest_subscription_map(subscriptions)
        site_counts_by_account = Counter(
            site.account_id for site in sites if str(site.account_id or "").strip()
        )
        items = []
        for site in sites:
            subscription = latest_subscription_by_account.get(site.account_id or "")
            billing_snapshot = latest_billing_by_site.get(site.site_id)
            usage = usage_summary.get(site.site_id, {})
            items.append(
                {
                    "site": self._serialize_site(site),
                    "active_key_count": key_counts.get(site.site_id, 0),
                    "coverage": service._build_subscription_coverage_summary(
                        subscription,
                        site_count=site_counts_by_account.get(site.account_id or "", 0),
                    ),
                    "recent_usage": {
                        "window_days": max(1, usage_window_days),
                        "event_count": self._coerce_int(usage.get("event_count")),
                        "quantity_total": round(
                            self._coerce_float(usage.get("quantity_total")),
                            6,
                        ),
                        "last_seen_at": usage.get("last_seen_at"),
                    },
                    "latest_billing_snapshot": (
                        service._serialize_billing_snapshot(billing_snapshot)
                        if billing_snapshot is not None
                        else None
                    ),
                }
            )
        return {
            "filters": {
                "status": status or "",
                "account_id": account_id or "",
                "subscription_status": subscription_status or "",
                "expires_before": self._serialize_datetime(expires_before),
                "limit": limit,
                "usage_window_days": max(1, usage_window_days),
            },
            "items": items,
        }

    def get_admin_site(self, site_id: str) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            site = repository.get_site(site_id)
            if site is None:
                raise CommercialNotFoundError(
                    "service.site_not_found",
                    f"site '{site_id}' was not found",
                )
            account = repository.get_account(site.account_id) if site.account_id else None
            keys = repository.list_site_keys(site_id)
            subscription = repository.get_latest_account_subscription(site.account_id or "")
            snapshot = repository.get_active_entitlement_snapshot(
                site.account_id or "",
                subscription_id=subscription.subscription_id if subscription is not None else None,
            )
            site_count = repository.count_sites_by_account(
                account_ids=[str(site.account_id or "")]
            ).get(site.account_id or "", 0)

        service = cast(Any, self)
        usage_meter = service.inspect_usage_meter(site_id, limit=20)
        billing_snapshots = service.list_billing_snapshots(site_id)
        reconciliation = (
            service.reconcile_billing_snapshot(site_id) if subscription is not None else None
        )
        commercial_policy = service.inspect_commercial_policy(site_id)
        return {
            "site": self._serialize_site(site),
            "account": service._serialize_account(account) if account is not None else None,
            "site_keys": [self._serialize_site_key(item) for item in keys],
            "subscription": (
                service._serialize_subscription(subscription) if subscription is not None else None
            ),
            "coverage": service._build_subscription_coverage_summary(
                subscription,
                site_count=site_count,
                site_limit=int(getattr(snapshot, "site_limit", 0) or 0),
            ),
            "usage_meter": usage_meter,
            "billing_snapshots": billing_snapshots,
            "billing_reconciliation": reconciliation,
            "commercial_policy": commercial_policy,
        }

    def get_portal_site_diagnostics(self, site_id: str) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            site = repository.get_site(site_id)
            if site is None:
                raise CommercialNotFoundError(
                    "service.site_not_found", f"site '{site_id}' was not found"
                )
            keys = repository.list_site_keys(site_id, limit=100)
            active_keys = [item for item in keys if item.status == SITE_API_KEY_STATUS_ACTIVE]
            recent_events = repository.list_service_audit_events(site_id=site_id, limit=20)
            failed_events = [
                item
                for item in recent_events
                if str(item.outcome or "").lower() in {"error", "denied", "failed"}
            ]
            latest_key_usage = max(
                [item.last_used_at for item in keys if item.last_used_at],
                default=None,
            )
            expiring_threshold = self.now_factory() + timedelta(days=14)
            if expiring_threshold.tzinfo is None:
                expiring_threshold = expiring_threshold.replace(tzinfo=UTC)
            expiring_soon = 0
            for item in active_keys:
                expires_at = item.expires_at
                if expires_at is None:
                    continue
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if expires_at <= expiring_threshold:
                    expiring_soon += 1
            metadata = site.metadata_json or {}
            wordpress_url = str(metadata.get("wordpress_url") or metadata.get("url") or "").strip()
            checks = [
                self._build_diagnostic_check(
                    "site_status",
                    site.status == SITE_STATUS_ACTIVE,
                    "站点已激活" if site.status == SITE_STATUS_ACTIVE else "站点尚未激活或已暂停",
                    "先在站点页恢复/激活站点，再重试云端请求。",
                ),
                self._build_diagnostic_check(
                    "active_key",
                    len(active_keys) > 0,
                    "存在可用 API Key" if active_keys else "没有可用 API Key",
                    "在密钥页创建或轮换一个有效 Key。",
                ),
                self._build_diagnostic_check(
                    "wordpress_url",
                    bool(wordpress_url),
                    "WordPress URL 已配置" if wordpress_url else "WordPress URL 未配置",
                    "在站点记录中确认站点 URL，方便排查绑定关系。",
                ),
                self._build_diagnostic_check(
                    "recent_failures",
                    len(failed_events) == 0,
                    "最近未发现失败事件" if not failed_events else "最近存在失败或拒绝事件",
                    "打开审计页查看失败事件详情和 trace id。",
                ),
            ]
            return {
                "site_id": site.site_id,
                "account_id": site.account_id or "",
                "status": "ok" if all(item["ok"] for item in checks) else "attention",
                "generated_at": self._serialize_datetime(self.now_factory()),
                "site": self._serialize_site(site),
                "site_status": site.status,
                "wordpress_url": wordpress_url,
                "active_key_count": len(active_keys),
                "latest_key_used_at": self._serialize_datetime(latest_key_usage),
                "latest_auth_failure_at": self._serialize_datetime(
                    failed_events[0].created_at if failed_events else None
                ),
                "key_summary": {
                    "total": len(keys),
                    "active": len(active_keys),
                    "latest_used_at": self._serialize_datetime(latest_key_usage),
                    "expiring_soon": expiring_soon,
                },
                "recent_failures": [
                    self._serialize_service_audit_event(item) for item in failed_events[:5]
                ],
                "checks": checks,
            }

    def _serialize_site(self, site: Site) -> dict[str, object]:
        return {
            "site_id": site.site_id,
            "account_id": site.account_id or "",
            "name": site.name,
            "status": site.status,
            "wordpress_url": _extract_site_wordpress_url(site),
            "metadata": site.metadata_json or {},
            "provisioned_at": self._serialize_datetime(site.provisioned_at),
            "activated_at": self._serialize_datetime(site.activated_at),
            "suspended_at": self._serialize_datetime(site.suspended_at),
            "suspension_reason": site.suspension_reason or "",
            "created_at": self._serialize_datetime(site.created_at),
            "updated_at": self._serialize_datetime(site.updated_at),
        }

    def _serialize_site_key(self, api_key: SiteApiKey) -> dict[str, object]:
        return {
            "key_id": api_key.key_id,
            "site_id": api_key.site_id,
            "label": api_key.label or "",
            "scopes": list(api_key.scopes_json or []),
            "metadata": api_key.metadata_json or {},
            "status": api_key.status,
            "rotated_from_key_id": api_key.rotated_from_key_id or "",
            "replaced_by_key_id": api_key.replaced_by_key_id or "",
            "expires_at": self._serialize_datetime(api_key.expires_at),
            "revoked_at": self._serialize_datetime(api_key.revoked_at),
            "last_used_at": self._serialize_datetime(api_key.last_used_at),
            "created_at": self._serialize_datetime(api_key.created_at),
            "updated_at": self._serialize_datetime(api_key.updated_at),
        }

    def _latest_subscription_map_by_site(
        self,
        *,
        subscriptions: list[AccountSubscription],
        sites: list[Site],
    ) -> dict[str, AccountSubscription]:
        latest_by_account = cast(Any, self)._latest_subscription_map(subscriptions)
        return {
            site.site_id: latest_by_account[site.account_id]
            for site in sites
            if site.account_id and site.account_id in latest_by_account
        }

    def _resolve_site_limit(
        self,
        *,
        plan_version: object | None = None,
        subscription: object | None = None,
        snapshot: object | None = None,
    ) -> int:
        sources = [
            getattr(snapshot, "site_limit", None),
            (getattr(snapshot, "metadata_json", None) or {}).get("site_limit")
            if snapshot is not None
            else None,
            (getattr(plan_version, "metadata_json", None) or {}).get("site_limit")
            if plan_version is not None
            else None,
            (getattr(subscription, "metadata_json", None) or {}).get("site_limit")
            if subscription is not None
            else None,
        ]
        for source in sources:
            if source is not None:
                return max(0, self._coerce_int(source))
        tier_id = cast(Any, self)._infer_plan_tier_id(
            {
                "plan_id": str(getattr(subscription, "plan_id", "") or ""),
                "metadata": getattr(subscription, "metadata_json", None) or {},
            },
            [],
        )
        baseline = PLAN_TIER_REGISTRY.get(tier_id, PLAN_TIER_REGISTRY[DEFAULT_PLAN_TIER_ID])
        return max(0, self._coerce_int(baseline.get("site_limit")))
