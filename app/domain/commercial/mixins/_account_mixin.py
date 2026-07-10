"""Commercial service: account and subscription operations mixin."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.db import get_session
from app.core.models import (
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_SUSPENDED,
    SITE_STATUS_ACTIVE,
    SITE_STATUS_PROVISIONING,
    SITE_STATUS_SUSPENDED,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_CANCELED,
    SUBSCRIPTION_STATUS_SUSPENDED,
    SUBSCRIPTION_STATUS_TRIALING,
)
from app.domain.commercial.audit_context import ServiceAuditContext
from app.domain.commercial.errors import (
    CommercialNotFoundError,
    CommercialPermissionError,
    CommercialValidationError,
)
from app.domain.commercial.mixins._audit_mixin import CommercialServiceAuditMixin
from app.domain.commercial.service import (
    DEFAULT_FREE_PLAN_KIND,
    DEFAULT_FREE_SUBSCRIPTION_SOURCE,
    PLAN_TIER_REGISTRY,
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

    def set_account_status(
        self,
        account_id: str,
        *,
        status: str,
        reason: str = "",
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in {ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_SUSPENDED}:
            raise CommercialValidationError(
                "service.account_status_invalid",
                "account status must be active or suspended",
            )

        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            account = repository.get_account(account_id)
            if account is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )

            now = self.now_factory()
            normalized_reason = str(reason or "").strip()
            metadata_json = dict(getattr(account, "metadata_json", None) or {})
            metadata_json["account_status_action"] = normalized_status
            metadata_json["account_status_updated_at"] = self._serialize_datetime(now)
            if normalized_status == ACCOUNT_STATUS_SUSPENDED and normalized_reason:
                metadata_json["account_status_note"] = normalized_reason[:500]

            account.status = normalized_status
            account.metadata_json = metadata_json
            session.flush()
            payload = self._serialize_account(account)
            event_kind = (
                "account.restore"
                if normalized_status == ACCOUNT_STATUS_ACTIVE
                else "account.suspend"
            )
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind=event_kind,
                outcome="succeeded",
                account_id=account.account_id,
                scope_kind="account",
                scope_id=account.account_id,
                payload_json=payload,
            )
            session.commit()
            return payload

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
        plan_id, plan_version_id = service._ensure_free_version_in_session(repository=repository)
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
                "tier_id": "free",
                "package_alias": PLAN_TIER_REGISTRY["free"].get("package_alias") or "Free",
                "plan_kind": DEFAULT_FREE_PLAN_KIND,
                "site_limit": self._coerce_int(PLAN_TIER_REGISTRY["free"].get("site_limit")),
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

    def _restore_default_free_subscription_for_account_in_session(
        self,
        *,
        repository: CommercialRepository,
        account_id: str,
        now: datetime,
        reason: str,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        service = cast(Any, self)
        plan_id, plan_version_id = service._ensure_free_version_in_session(repository=repository)
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
                "tier_id": "free",
                "package_alias": PLAN_TIER_REGISTRY["free"].get("package_alias") or "Free",
                "plan_kind": DEFAULT_FREE_PLAN_KIND,
                "site_limit": self._coerce_int(PLAN_TIER_REGISTRY["free"].get("site_limit")),
                "restored_at": service._serialize_datetime(now),
                "restore_reason": reason,
            },
        )
        covered_sites = repository.list_sites(account_id=subscription.account_id, limit=None)
        service._refresh_subscription_billing_snapshots_in_session(
            repository=repository,
            subscription=subscription,
            covered_sites=covered_sites,
            period_start_at=now,
            period_end_at=now + timedelta(days=30),
        )
        payload = {
            "subscription": service._serialize_subscription(subscription),
            "entitlement_snapshot": service._serialize_entitlement_snapshot(snapshot),
        }
        self._record_service_audit_in_session(
            repository=repository,
            audit_context=audit_context,
            event_kind="subscription.free.restore",
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

    def _reconcile_account_subscription_state_in_session(
        self,
        *,
        repository: CommercialRepository,
        account_id: str,
        now: datetime,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object] | None:
        applied_free_downgrade = cast(Any, self)._apply_due_free_downgrade_in_session(
            repository=repository,
            account_id=account_id,
            now=now,
        )
        activated_orders = cast(Any, self)._activate_due_subscription_orders_in_session(
            repository=repository,
            account_id=account_id,
            now=now,
        )
        subscriptions = repository.list_account_subscriptions(account_id)
        expired_trials = []
        for subscription in subscriptions:
            if subscription.status != SUBSCRIPTION_STATUS_TRIALING:
                continue
            metadata = dict(subscription.metadata_json or {})
            if not str(metadata.get("trial_for_tier") or "").strip():
                continue
            period_end_at = subscription.current_period_end_at
            if period_end_at is None:
                continue
            normalized_period_end_at = self._normalize_datetime(period_end_at)
            if normalized_period_end_at > now:
                continue
            metadata["trial_expired_at"] = self._serialize_datetime(now)
            metadata["trial_expiry_action"] = "fallback_to_free"
            subscription.status = SUBSCRIPTION_STATUS_CANCELED
            subscription.canceled_at = now
            subscription.metadata_json = metadata
            expired_trials.append(subscription)

        trial_claim = repository.find_trial_claim(account_id=account_id)
        if (
            trial_claim is not None
            and trial_claim.status == "active"
            and self._normalize_datetime(trial_claim.ends_at) <= now
        ):
            trial_claim.status = "expired"

        if not expired_trials and not activated_orders and applied_free_downgrade is None:
            return None

        if not expired_trials:
            return {
                "activated_subscriptions": [
                    cast(Any, self)._serialize_subscription(subscription)
                    for subscription in activated_orders
                ],
                "restored_subscription": (
                    cast(Any, self)._serialize_subscription(applied_free_downgrade)
                    if applied_free_downgrade is not None
                    else None
                ),
            }

        repository.supersede_entitlement_snapshots(account_id)
        repository.session.flush()
        active_after_expiry = [
            subscription
            for subscription in repository.list_account_subscriptions(account_id)
            if subscription.status == SUBSCRIPTION_STATUS_ACTIVE
        ]
        if active_after_expiry:
            payload = {
                "expired_trials": [
                    cast(Any, self)._serialize_subscription(subscription)
                    for subscription in expired_trials
                ],
                "active_subscription": cast(Any, self)._serialize_subscription(
                    active_after_expiry[0]
                ),
            }
        else:
            restored = self._restore_default_free_subscription_for_account_in_session(
                repository=repository,
                account_id=account_id,
                now=now,
                reason="paid_package_trial_expired",
                audit_context=audit_context,
            )
            payload = {
                "expired_trials": [
                    cast(Any, self)._serialize_subscription(subscription)
                    for subscription in expired_trials
                ],
                "restored_subscription": restored.get("subscription"),
            }
        self._record_service_audit_in_session(
            repository=repository,
            audit_context=audit_context,
            event_kind="subscription.paid_trial.expire",
            outcome="succeeded",
            account_id=account_id,
            scope_kind="account",
            scope_id=account_id,
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
        if requested_tier_id in PLAN_TIER_REGISTRY and (
            repository.get_plan(plan_id) is None
            or repository.get_plan_version(plan_version_id) is None
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

    def _cancel_covered_subscriptions_for_replacement(
        self,
        *,
        repository: CommercialRepository,
        account_id: str,
        now: datetime,
        reason: str,
        except_subscription_id: str = "",
    ) -> None:
        for subscription in repository.list_account_subscriptions(account_id):
            if subscription.subscription_id == except_subscription_id:
                continue
            if subscription.status not in {
                SUBSCRIPTION_STATUS_ACTIVE,
                SUBSCRIPTION_STATUS_TRIALING,
            }:
                continue
            metadata = dict(subscription.metadata_json or {})
            metadata["replaced_at"] = self._serialize_datetime(now)
            metadata["replacement_reason"] = reason
            subscription.status = SUBSCRIPTION_STATUS_CANCELED
            subscription.canceled_at = now
            subscription.metadata_json = metadata
        repository.supersede_entitlement_snapshots(account_id)
        repository.session.flush()

    def _serialize_account(self, account: object) -> dict[str, object]:
        return {
            "account_id": str(getattr(account, "account_id", "") or ""),
            "name": str(getattr(account, "name", "") or ""),
            "status": str(getattr(account, "status", "") or ""),
            "metadata": getattr(account, "metadata_json", None) or {},
            "created_at": self._serialize_datetime(getattr(account, "created_at", None)),
            "updated_at": self._serialize_datetime(getattr(account, "updated_at", None)),
        }

    def _assert_account_site_capacity(
        self,
        *,
        repository: CommercialRepository,
        account_id: str,
        snapshot: object,
    ) -> None:
        plan_version = None
        plan_version_id = str(getattr(snapshot, "plan_version_id", "") or "").strip()
        if plan_version_id:
            plan_version = repository.get_plan_version(plan_version_id)
        plan_version_metadata: dict[str, object] = {}
        if plan_version is not None:
            plan_version_metadata = getattr(plan_version, "metadata_json", None) or {}
        site_limit = (
            cast(Any, self)._resolve_site_limit(plan_version=plan_version)
            if plan_version is not None and plan_version_metadata.get("site_limit") is not None
            else cast(Any, self)._resolve_site_limit(snapshot=snapshot)
        )
        site_counts = repository.count_sites_by_account(
            account_ids=[account_id],
            statuses=[
                SITE_STATUS_ACTIVE,
                SITE_STATUS_PROVISIONING,
                SITE_STATUS_SUSPENDED,
            ],
        )
        current_count = self._coerce_int(site_counts.get(account_id, 0))
        if site_limit > 0 and current_count >= site_limit:
            raise CommercialPermissionError(
                "service.site_limit_exceeded",
                f"account '{account_id}' has reached its site limit for the current subscription",
            )
