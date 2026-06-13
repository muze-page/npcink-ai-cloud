from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.models import (
    CREDIT_LEDGER_EVENT_CONSUME,
    PORTAL_LOGIN_CODE_STATUS_PENDING,
    SITE_ADMIN_SITE_GRANT_STATUS_ACTIVE,
    SITE_ADMIN_STATUS_ACTIVE,
    Account,
    AccountEntitlementSnapshot,
    AccountSubscription,
    BillingSnapshot,
    CommercialDecisionEvent,
    CreditLedgerEntry,
    PaymentEvent,
    PaymentOrder,
    PaymentRefund,
    Plan,
    PlanVersion,
    PlatformAdminIdentity,
    PortalLoginCode,
    ProviderCallRecord,
    RunRecord,
    ServiceAuditEvent,
    Site,
    SiteAdminIdentity,
    SiteAdminSiteGrant,
    SiteApiKey,
    SiteKnowledgeChunk,
    SiteKnowledgeDocument,
    SiteKnowledgeIndexJobMetric,
    UsageMeterEvent,
)

type SQLAFilter = ColumnElement[bool]


class CommercialRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_account(self, account_id: str) -> Account | None:
        return self.session.get(Account, account_id)

    def list_accounts(
        self,
        *,
        status: str | None = None,
        account_ids: list[str] | None = None,
        limit: int | None = None,
    ) -> list[Account]:
        statement = select(Account)
        if status:
            statement = statement.where(Account.status == status)
        if account_ids is not None:
            if not account_ids:
                return []
            statement = statement.where(Account.account_id.in_(account_ids))
        statement = statement.order_by(Account.created_at.desc(), Account.account_id.asc())
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def count_accounts(self, *, status: str | None = None) -> int:
        statement = select(func.count(Account.account_id))
        if status:
            statement = statement.where(Account.status == status)
        return int(self.session.scalar(statement) or 0)

    def upsert_account(
        self,
        *,
        account_id: str,
        name: str,
        status: str,
        metadata_json: dict[str, object] | None,
    ) -> Account:
        account = self.get_account(account_id)
        if account is None:
            account = Account(
                account_id=account_id,
                name=name or account_id,
                status=status,
                metadata_json=metadata_json,
            )
            self.session.add(account)
        else:
            account.name = name or account.name or account_id
            account.status = status
            account.metadata_json = metadata_json
        self.session.flush()
        return account

    def create_portal_login_code(
        self,
        *,
        code_id: str,
        email: str,
        site_admin_ref: str,
        code_hash: str,
        expires_at: datetime,
        metadata_json: dict[str, object] | None = None,
    ) -> PortalLoginCode:
        code = PortalLoginCode(
            code_id=code_id,
            email=email,
            site_admin_ref=site_admin_ref,
            code_hash=code_hash,
            status=PORTAL_LOGIN_CODE_STATUS_PENDING,
            expires_at=expires_at,
            consumed_at=None,
            attempt_count=0,
            metadata_json=metadata_json,
        )
        self.session.add(code)
        self.session.flush()
        return code

    def list_portal_login_codes(
        self,
        *,
        email: str | None = None,
        site_admin_ref: str | None = None,
        status: str | None = None,
        active_only: bool = False,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> list[PortalLoginCode]:
        statement = select(PortalLoginCode)
        if email:
            statement = statement.where(func.lower(PortalLoginCode.email) == email.lower())
        if site_admin_ref:
            statement = statement.where(PortalLoginCode.site_admin_ref == site_admin_ref)
        if status:
            statement = statement.where(PortalLoginCode.status == status)
        if active_only:
            current = now or datetime.now(UTC)
            statement = statement.where(
                PortalLoginCode.status == PORTAL_LOGIN_CODE_STATUS_PENDING,
                PortalLoginCode.consumed_at.is_(None),
                PortalLoginCode.expires_at > current,
            )
        statement = statement.order_by(
            PortalLoginCode.created_at.desc(), PortalLoginCode.code_id.desc()
        )
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def get_site_admin_identity_by_email(self, *, email: str) -> SiteAdminIdentity | None:
        return self.session.scalar(
            select(SiteAdminIdentity).where(func.lower(SiteAdminIdentity.email) == email.lower())
        )

    def get_site_admin_identity_by_ref(
        self,
        *,
        site_admin_ref: str,
    ) -> SiteAdminIdentity | None:
        return self.session.scalar(
            select(SiteAdminIdentity).where(SiteAdminIdentity.site_admin_ref == site_admin_ref)
        )

    def count_site_admin_identities(self, *, status: str | None = None) -> int:
        statement = select(func.count(SiteAdminIdentity.site_admin_id))
        if status:
            statement = statement.where(SiteAdminIdentity.status == status)
        return int(self.session.scalar(statement) or 0)

    def upsert_site_admin_identity(
        self,
        *,
        site_admin_id: str,
        site_admin_ref: str,
        email: str,
        status: str = SITE_ADMIN_STATUS_ACTIVE,
        metadata_json: dict[str, object] | None = None,
        last_login_at: datetime | None = None,
    ) -> SiteAdminIdentity:
        identity = self.get_site_admin_identity_by_ref(site_admin_ref=site_admin_ref)
        if identity is None:
            identity = self.get_site_admin_identity_by_email(email=email)
        if identity is None:
            identity = SiteAdminIdentity(
                site_admin_id=site_admin_id,
                site_admin_ref=site_admin_ref,
                email=email,
                status=status,
                metadata_json=metadata_json,
                last_login_at=last_login_at,
            )
            self.session.add(identity)
        else:
            identity.site_admin_ref = site_admin_ref
            identity.email = email
            identity.status = status
            identity.metadata_json = metadata_json
            if last_login_at is not None:
                identity.last_login_at = last_login_at
        self.session.flush()
        return identity

    def upsert_site_admin_site_grant(
        self,
        *,
        grant_id: str,
        site_admin_id: str,
        site_id: str,
        status: str = SITE_ADMIN_SITE_GRANT_STATUS_ACTIVE,
        metadata_json: dict[str, object] | None = None,
    ) -> SiteAdminSiteGrant:
        grant = self.session.scalar(
            select(SiteAdminSiteGrant).where(
                SiteAdminSiteGrant.site_admin_id == site_admin_id,
                SiteAdminSiteGrant.site_id == site_id,
            )
        )
        if grant is None:
            grant = SiteAdminSiteGrant(
                grant_id=grant_id,
                site_admin_id=site_admin_id,
                site_id=site_id,
                status=status,
                metadata_json=metadata_json,
            )
            self.session.add(grant)
        else:
            grant.status = status
            grant.metadata_json = metadata_json
        self.session.flush()
        return grant

    def get_site_admin_site_grant(
        self,
        *,
        site_admin_ref: str,
        site_id: str,
    ) -> tuple[SiteAdminIdentity, SiteAdminSiteGrant] | None:
        row = self.session.execute(
            select(SiteAdminIdentity, SiteAdminSiteGrant)
            .join(
                SiteAdminSiteGrant,
                SiteAdminSiteGrant.site_admin_id == SiteAdminIdentity.site_admin_id,
            )
            .where(
                SiteAdminIdentity.site_admin_ref == site_admin_ref,
                SiteAdminSiteGrant.site_id == site_id,
            )
        ).first()
        if row is None:
            return None
        return row[0], row[1]

    def list_sites_for_site_admin(
        self,
        *,
        site_admin_ref: str,
        grant_statuses: list[str] | None = None,
    ) -> list[tuple[Site, SiteAdminIdentity, SiteAdminSiteGrant]]:
        statuses = grant_statuses or [SITE_ADMIN_SITE_GRANT_STATUS_ACTIVE]
        statement = (
            select(Site, SiteAdminIdentity, SiteAdminSiteGrant)
            .join(SiteAdminSiteGrant, SiteAdminSiteGrant.site_id == Site.site_id)
            .join(
                SiteAdminIdentity,
                SiteAdminIdentity.site_admin_id == SiteAdminSiteGrant.site_admin_id,
            )
            .join(Account, Account.account_id == Site.account_id)
            .where(
                SiteAdminIdentity.site_admin_ref == site_admin_ref,
                SiteAdminIdentity.status == SITE_ADMIN_STATUS_ACTIVE,
                SiteAdminSiteGrant.status.in_(statuses),
                Account.status == "active",
            )
            .order_by(Site.created_at.desc(), Site.site_id.asc())
        )
        return [
            (site, identity, grant)
            for site, identity, grant in self.session.execute(statement).all()
        ]

    def get_platform_admin_identity(
        self,
        *,
        admin_ref: str,
    ) -> PlatformAdminIdentity | None:
        return self.session.scalar(
            select(PlatformAdminIdentity).where(
                PlatformAdminIdentity.admin_ref == admin_ref,
            )
        )

    def get_platform_admin_identity_by_subject(
        self,
        *,
        provider: str,
        external_subject: str,
    ) -> PlatformAdminIdentity | None:
        return self.session.scalar(
            select(PlatformAdminIdentity).where(
                PlatformAdminIdentity.provider == provider,
                PlatformAdminIdentity.external_subject == external_subject,
            )
        )

    def get_platform_admin_identity_by_email(
        self,
        *,
        provider: str,
        email: str,
    ) -> PlatformAdminIdentity | None:
        return self.session.scalar(
            select(PlatformAdminIdentity).where(
                PlatformAdminIdentity.provider == provider,
                func.lower(PlatformAdminIdentity.email) == email.lower(),
            )
        )

    def upsert_platform_admin_identity(
        self,
        *,
        admin_id: str,
        admin_ref: str,
        provider: str,
        external_subject: str | None,
        email: str | None,
        role: str,
        status: str,
        metadata_json: dict[str, object] | None = None,
    ) -> PlatformAdminIdentity:
        identity = self.get_platform_admin_identity(admin_ref=admin_ref)
        if identity is None:
            identity = PlatformAdminIdentity(
                admin_id=admin_id,
                admin_ref=admin_ref,
                provider=provider,
                external_subject=external_subject,
                email=email,
                role=role,
                status=status,
                metadata_json=metadata_json,
            )
            self.session.add(identity)
        else:
            identity.provider = provider
            identity.external_subject = external_subject
            identity.email = email
            identity.role = role
            identity.status = status
            identity.metadata_json = metadata_json
        self.session.flush()
        return identity

    def list_platform_admin_identities(
        self,
        *,
        status: str | None = None,
        role: str | None = None,
        provider: str | None = None,
        limit: int | None = None,
    ) -> list[PlatformAdminIdentity]:
        statement = select(PlatformAdminIdentity)
        if status:
            statement = statement.where(PlatformAdminIdentity.status == status)
        if role:
            statement = statement.where(PlatformAdminIdentity.role == role)
        if provider:
            statement = statement.where(PlatformAdminIdentity.provider == provider)
        statement = statement.order_by(
            PlatformAdminIdentity.created_at.desc(),
            PlatformAdminIdentity.admin_ref.asc(),
        )
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def delete_platform_admin_identity(
        self,
        *,
        admin_ref: str,
    ) -> bool:
        identity = self.get_platform_admin_identity(admin_ref=admin_ref)
        if identity is None:
            return False
        self.session.delete(identity)
        self.session.flush()
        return True

    def get_site(self, site_id: str) -> Site | None:
        return self.session.get(Site, site_id)

    def list_sites(
        self,
        *,
        status: str | None = None,
        account_id: str | None = None,
        account_ids: list[str] | None = None,
        site_ids: list[str] | None = None,
        limit: int | None = None,
    ) -> list[Site]:
        statement = select(Site)
        if status:
            statement = statement.where(Site.status == status)
        if account_id:
            statement = statement.where(Site.account_id == account_id)
        if account_ids is not None:
            if not account_ids:
                return []
            statement = statement.where(Site.account_id.in_(account_ids))
        if site_ids is not None:
            if not site_ids:
                return []
            statement = statement.where(Site.site_id.in_(site_ids))
        statement = statement.order_by(Site.created_at.desc(), Site.site_id.asc())
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def count_sites(self, *, status: str | None = None) -> int:
        statement = select(func.count(Site.site_id))
        if status:
            statement = statement.where(Site.status == status)
        return int(self.session.scalar(statement) or 0)

    def count_sites_by_account(
        self,
        *,
        account_ids: list[str] | None = None,
        status: str | None = None,
    ) -> dict[str, int]:
        statement = select(Site.account_id, func.count(Site.site_id)).group_by(Site.account_id)
        if account_ids is not None:
            if not account_ids:
                return {}
            statement = statement.where(Site.account_id.in_(account_ids))
        if status:
            statement = statement.where(Site.status == status)
        return {
            str(account_id or ""): int(count or 0)
            for account_id, count in self.session.execute(statement)
            if account_id
        }

    def upsert_site(
        self,
        *,
        site_id: str,
        account_id: str | None,
        name: str,
        status: str,
        metadata_json: dict[str, object] | None,
        provisioned_at: datetime | None,
    ) -> Site:
        site = self.get_site(site_id)
        if site is None:
            site = Site(
                site_id=site_id,
                account_id=account_id,
                name=name or site_id,
                status=status,
                metadata_json=metadata_json,
                provisioned_at=provisioned_at,
            )
            self.session.add(site)
        else:
            site.account_id = account_id
            site.name = name or site.name or site_id
            site.status = status
            site.metadata_json = metadata_json
            if provisioned_at is not None and site.provisioned_at is None:
                site.provisioned_at = provisioned_at
        self.session.flush()
        return site

    def get_site_key(self, key_id: str) -> SiteApiKey | None:
        return self.session.get(SiteApiKey, key_id)

    def list_site_keys(
        self,
        site_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[SiteApiKey]:
        statement = (
            select(SiteApiKey)
            .where(SiteApiKey.site_id == site_id)
            .order_by(SiteApiKey.created_at.desc(), SiteApiKey.key_id.desc())
        )
        if offset > 0:
            statement = statement.offset(offset)
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def count_site_keys(self, site_id: str) -> int:
        statement = select(func.count(SiteApiKey.key_id)).where(SiteApiKey.site_id == site_id)
        count = self.session.scalar(statement)
        return int(count or 0)

    def count_site_keys_by_site(
        self,
        *,
        site_ids: list[str] | None = None,
        statuses: list[str] | None = None,
    ) -> dict[str, int]:
        statement = select(SiteApiKey.site_id, func.count(SiteApiKey.key_id)).group_by(
            SiteApiKey.site_id
        )
        if site_ids is not None:
            if not site_ids:
                return {}
            statement = statement.where(SiteApiKey.site_id.in_(site_ids))
        if statuses:
            statement = statement.where(SiteApiKey.status.in_(statuses))
        return {
            str(site_id or ""): int(count or 0)
            for site_id, count in self.session.execute(statement)
        }

    def count_site_keys_total(self, *, statuses: list[str] | None = None) -> int:
        statement = select(func.count(SiteApiKey.key_id))
        if statuses:
            statement = statement.where(SiteApiKey.status.in_(statuses))
        return int(self.session.scalar(statement) or 0)

    def upsert_site_key(
        self,
        *,
        key_id: str,
        site_id: str,
        secret_hash: str,
        signing_secret_ciphertext: str,
        label: str,
        scopes_json: list[str] | None,
        metadata_json: dict[str, object] | None,
        status: str,
        rotated_from_key_id: str | None,
        replaced_by_key_id: str | None,
        expires_at: datetime | None,
        revoked_at: datetime | None,
    ) -> SiteApiKey:
        api_key = self.get_site_key(key_id)
        if api_key is None:
            api_key = SiteApiKey(
                key_id=key_id,
                site_id=site_id,
                secret_hash=secret_hash,
                signing_secret_ciphertext=signing_secret_ciphertext,
                label=label or None,
                scopes_json=scopes_json,
                metadata_json=metadata_json,
                status=status,
                rotated_from_key_id=rotated_from_key_id,
                replaced_by_key_id=replaced_by_key_id,
                expires_at=expires_at,
                revoked_at=revoked_at,
            )
            self.session.add(api_key)
        else:
            api_key.site_id = site_id
            api_key.secret_hash = secret_hash
            api_key.signing_secret_ciphertext = signing_secret_ciphertext
            api_key.label = label or None
            api_key.scopes_json = scopes_json
            api_key.metadata_json = metadata_json
            api_key.status = status
            api_key.rotated_from_key_id = rotated_from_key_id
            api_key.replaced_by_key_id = replaced_by_key_id
            api_key.expires_at = expires_at
            api_key.revoked_at = revoked_at
        self.session.flush()
        return api_key

    def get_plan(self, plan_id: str) -> Plan | None:
        return self.session.get(Plan, plan_id)

    def list_plans(
        self,
        *,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[Plan]:
        statement = select(Plan).order_by(Plan.created_at.desc(), Plan.plan_id.desc())
        if status:
            statement = statement.where(Plan.status == status)
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def upsert_plan(
        self,
        *,
        plan_id: str,
        name: str,
        status: str,
        description: str,
        metadata_json: dict[str, object] | None,
    ) -> Plan:
        plan = self.get_plan(plan_id)
        if plan is None:
            plan = Plan(
                plan_id=plan_id,
                name=name or plan_id,
                status=status,
                description=description or None,
                metadata_json=metadata_json,
            )
            self.session.add(plan)
        else:
            plan.name = name or plan.name or plan_id
            plan.status = status
            plan.description = description or None
            plan.metadata_json = metadata_json
        self.session.flush()
        return plan

    def get_plan_version(self, plan_version_id: str) -> PlanVersion | None:
        return self.session.get(PlanVersion, plan_version_id)

    def list_plan_versions(
        self,
        *,
        plan_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[PlanVersion]:
        statement = select(PlanVersion).order_by(
            PlanVersion.created_at.desc(),
            PlanVersion.plan_version_id.desc(),
        )
        if plan_id:
            statement = statement.where(PlanVersion.plan_id == plan_id)
        if status:
            statement = statement.where(PlanVersion.status == status)
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def upsert_plan_version(
        self,
        *,
        plan_version_id: str,
        plan_id: str,
        version_label: str,
        status: str,
        currency: str,
        entitlements_json: dict[str, object],
        budgets_json: dict[str, object],
        concurrency_json: dict[str, object],
        policy_json: dict[str, object],
        metadata_json: dict[str, object] | None,
    ) -> PlanVersion:
        plan_version = self.get_plan_version(plan_version_id)
        if plan_version is None:
            plan_version = PlanVersion(
                plan_version_id=plan_version_id,
                plan_id=plan_id,
                version_label=version_label,
                status=status,
                currency=currency,
                entitlements_json=entitlements_json,
                budgets_json=budgets_json,
                concurrency_json=concurrency_json,
                policy_json=policy_json,
                metadata_json=metadata_json,
            )
            self.session.add(plan_version)
        else:
            plan_version.plan_id = plan_id
            plan_version.version_label = version_label
            plan_version.status = status
            plan_version.currency = currency
            plan_version.entitlements_json = entitlements_json
            plan_version.budgets_json = budgets_json
            plan_version.concurrency_json = concurrency_json
            plan_version.policy_json = policy_json
            plan_version.metadata_json = metadata_json
        self.session.flush()
        return plan_version

    def get_subscription(self, subscription_id: str) -> AccountSubscription | None:
        return self.session.get(AccountSubscription, subscription_id)

    def list_account_subscriptions(self, account_id: str) -> list[AccountSubscription]:
        statement = (
            select(AccountSubscription)
            .where(AccountSubscription.account_id == account_id)
            .order_by(
                AccountSubscription.created_at.desc(),
                AccountSubscription.subscription_id.desc(),
            )
        )
        return list(self.session.scalars(statement))

    def list_subscriptions(
        self,
        *,
        status: str | None = None,
        statuses: list[str] | None = None,
        account_id: str | None = None,
        account_ids: list[str] | None = None,
        site_id: str | None = None,
        site_ids: list[str] | None = None,
        plan_id: str | None = None,
        current_period_end_before: datetime | None = None,
        limit: int | None = None,
    ) -> list[AccountSubscription]:
        statement = select(AccountSubscription)
        if status:
            statement = statement.where(AccountSubscription.status == status)
        if statuses:
            statement = statement.where(AccountSubscription.status.in_(statuses))
        if account_id:
            statement = statement.where(AccountSubscription.account_id == account_id)
        if account_ids is not None:
            if not account_ids:
                return []
            statement = statement.where(AccountSubscription.account_id.in_(account_ids))
        joined_sites = False
        if site_id:
            statement = statement.join(
                Site,
                Site.account_id == AccountSubscription.account_id,
            ).where(Site.site_id == site_id)
            joined_sites = True
        if site_ids is not None:
            if not site_ids:
                return []
            statement = statement.join(
                Site,
                Site.account_id == AccountSubscription.account_id,
            ).where(Site.site_id.in_(site_ids))
            joined_sites = True
        if plan_id:
            statement = statement.where(AccountSubscription.plan_id == plan_id)
        if current_period_end_before is not None:
            statement = statement.where(
                AccountSubscription.current_period_end_at.is_not(None),
                AccountSubscription.current_period_end_at <= current_period_end_before,
            )
        statement = statement.order_by(
            AccountSubscription.created_at.desc(),
            AccountSubscription.subscription_id.desc(),
        )
        if joined_sites:
            statement = statement.distinct()
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def count_subscriptions(
        self,
        *,
        status: str | None = None,
        statuses: list[str] | None = None,
    ) -> int:
        statement = select(func.count(AccountSubscription.subscription_id))
        if status:
            statement = statement.where(AccountSubscription.status == status)
        if statuses:
            statement = statement.where(AccountSubscription.status.in_(statuses))
        return int(self.session.scalar(statement) or 0)

    def summarize_subscription_status_counts(self) -> dict[str, int]:
        statement = (
            select(AccountSubscription.status, func.count(AccountSubscription.subscription_id))
            .where(AccountSubscription.status.is_not(None))
            .group_by(AccountSubscription.status)
        )
        return {
            str(status or ""): int(count or 0)
            for status, count in self.session.execute(statement)
            if status
        }

    def summarize_subscription_plan_counts(self) -> dict[str, int]:
        statement = (
            select(AccountSubscription.plan_id, func.count(AccountSubscription.subscription_id))
            .where(AccountSubscription.plan_id.is_not(None))
            .group_by(AccountSubscription.plan_id)
            .order_by(func.count(AccountSubscription.subscription_id).desc())
        )
        return {
            str(plan_id or ""): int(count or 0)
            for plan_id, count in self.session.execute(statement)
            if plan_id
        }

    def count_subscriptions_by_account(
        self,
        *,
        account_ids: list[str] | None = None,
        statuses: list[str] | None = None,
    ) -> dict[str, int]:
        statement = select(
            AccountSubscription.account_id,
            func.count(AccountSubscription.subscription_id),
        ).group_by(AccountSubscription.account_id)
        if account_ids is not None:
            if not account_ids:
                return {}
            statement = statement.where(AccountSubscription.account_id.in_(account_ids))
        if statuses:
            statement = statement.where(AccountSubscription.status.in_(statuses))
        return {
            str(account_id or ""): int(count or 0)
            for account_id, count in self.session.execute(statement)
        }

    def count_subscriptions_by_site(
        self,
        *,
        site_ids: list[str] | None = None,
        statuses: list[str] | None = None,
    ) -> dict[str, int]:
        statement = (
            select(
                Site.site_id,
                func.count(AccountSubscription.subscription_id),
            )
            .select_from(Site)
            .join(AccountSubscription, AccountSubscription.account_id == Site.account_id)
            .group_by(Site.site_id)
        )
        if site_ids is not None:
            if not site_ids:
                return {}
            statement = statement.where(Site.site_id.in_(site_ids))
        if statuses:
            statement = statement.where(AccountSubscription.status.in_(statuses))
        return {
            str(site_id or ""): int(count or 0)
            for site_id, count in self.session.execute(statement)
        }

    def upsert_account_subscription(
        self,
        *,
        subscription_id: str,
        account_id: str,
        plan_id: str,
        plan_version_id: str,
        status: str,
        current_period_start_at: datetime | None,
        current_period_end_at: datetime | None,
        started_at: datetime | None,
        canceled_at: datetime | None,
        suspended_at: datetime | None,
        metadata_json: dict[str, object] | None,
    ) -> AccountSubscription:
        subscription = self.get_subscription(subscription_id)
        if subscription is None:
            subscription = AccountSubscription(
                subscription_id=subscription_id,
                account_id=account_id,
                plan_id=plan_id,
                plan_version_id=plan_version_id,
                status=status,
                current_period_start_at=current_period_start_at,
                current_period_end_at=current_period_end_at,
                started_at=started_at,
                canceled_at=canceled_at,
                suspended_at=suspended_at,
                metadata_json=metadata_json,
            )
            self.session.add(subscription)
        else:
            subscription.account_id = account_id
            subscription.plan_id = plan_id
            subscription.plan_version_id = plan_version_id
            subscription.status = status
            subscription.current_period_start_at = current_period_start_at
            subscription.current_period_end_at = current_period_end_at
            subscription.started_at = started_at
            subscription.canceled_at = canceled_at
            subscription.suspended_at = suspended_at
            subscription.metadata_json = metadata_json
        self.session.flush()
        return subscription

    def get_latest_account_subscription(self, account_id: str) -> AccountSubscription | None:
        return next(iter(self.list_account_subscriptions(account_id)), None)

    def get_runtime_subscription(self, account_id: str) -> AccountSubscription | None:
        candidates = self.list_account_subscriptions(account_id)
        active_statuses = {"trialing", "active"}
        for subscription in candidates:
            if subscription.status in active_statuses:
                return subscription
        return candidates[0] if candidates else None

    def supersede_entitlement_snapshots(
        self,
        account_id: str,
        *,
        subscription_id: str | None = None,
    ) -> None:
        snapshots = list(
            self.session.scalars(
                select(AccountEntitlementSnapshot).where(
                    AccountEntitlementSnapshot.account_id == account_id,
                    AccountEntitlementSnapshot.status == "active",
                    *(
                        (AccountEntitlementSnapshot.subscription_id == subscription_id,)
                        if subscription_id
                        else ()
                    ),
                )
            )
        )
        for snapshot in snapshots:
            snapshot.status = "superseded"
        self.session.flush()

    def create_entitlement_snapshot(
        self,
        *,
        account_id: str,
        subscription_id: str,
        plan_version_id: str,
        entitlements_json: dict[str, object],
        budgets_json: dict[str, object],
        concurrency_json: dict[str, object],
        policy_json: dict[str, object],
        site_limit: int,
        metadata_json: dict[str, object] | None = None,
    ) -> AccountEntitlementSnapshot:
        snapshot = AccountEntitlementSnapshot(
            account_id=account_id,
            subscription_id=subscription_id,
            plan_version_id=plan_version_id,
            status="active",
            entitlements_json=entitlements_json,
            budgets_json=budgets_json,
            concurrency_json=concurrency_json,
            policy_json=policy_json,
            site_limit=site_limit,
            metadata_json=metadata_json,
        )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot

    def get_payment_order(self, order_id: str) -> PaymentOrder | None:
        return self.session.get(PaymentOrder, order_id)

    def get_payment_order_by_idempotency_key(self, idempotency_key: str) -> PaymentOrder | None:
        if not idempotency_key:
            return None
        return self.session.scalar(
            select(PaymentOrder).where(PaymentOrder.idempotency_key == idempotency_key)
        )

    def create_payment_order(
        self,
        *,
        order_id: str,
        account_id: str,
        site_id: str | None,
        subscription_id: str | None,
        plan_id: str,
        plan_version_id: str,
        provider: str,
        external_order_no: str,
        status: str,
        amount: float,
        currency: str,
        subject: str,
        checkout_url: str | None,
        refund_window_end_at: datetime | None,
        idempotency_key: str | None,
        metadata_json: dict[str, object] | None,
    ) -> PaymentOrder:
        order = PaymentOrder(
            order_id=order_id,
            account_id=account_id,
            site_id=site_id,
            subscription_id=subscription_id,
            plan_id=plan_id,
            plan_version_id=plan_version_id,
            provider=provider,
            external_order_no=external_order_no,
            status=status,
            amount=amount,
            currency=currency,
            subject=subject,
            checkout_url=checkout_url,
            refund_window_end_at=refund_window_end_at,
            idempotency_key=idempotency_key,
            metadata_json=metadata_json,
        )
        self.session.add(order)
        self.session.flush()
        return order

    def get_payment_refund(self, refund_id: str) -> PaymentRefund | None:
        return self.session.get(PaymentRefund, refund_id)

    def get_payment_refund_by_idempotency_key(self, idempotency_key: str) -> PaymentRefund | None:
        if not idempotency_key:
            return None
        return self.session.scalar(
            select(PaymentRefund).where(PaymentRefund.idempotency_key == idempotency_key)
        )

    def list_payment_refunds(self, order_id: str) -> list[PaymentRefund]:
        return list(
            self.session.scalars(
                select(PaymentRefund)
                .where(PaymentRefund.order_id == order_id)
                .order_by(PaymentRefund.created_at.desc(), PaymentRefund.refund_id.desc())
            )
        )

    def create_payment_refund(
        self,
        *,
        refund_id: str,
        order_id: str,
        account_id: str,
        subscription_id: str | None,
        provider: str,
        external_refund_no: str,
        status: str,
        amount: float,
        currency: str,
        reason: str | None,
        requested_at: datetime,
        idempotency_key: str | None,
        metadata_json: dict[str, object] | None,
    ) -> PaymentRefund:
        refund = PaymentRefund(
            refund_id=refund_id,
            order_id=order_id,
            account_id=account_id,
            subscription_id=subscription_id,
            provider=provider,
            external_refund_no=external_refund_no,
            status=status,
            amount=amount,
            currency=currency,
            reason=reason,
            requested_at=requested_at,
            idempotency_key=idempotency_key,
            metadata_json=metadata_json,
        )
        self.session.add(refund)
        self.session.flush()
        return refund

    def get_payment_event_by_idempotency_key(self, idempotency_key: str) -> PaymentEvent | None:
        if not idempotency_key:
            return None
        return self.session.scalar(
            select(PaymentEvent).where(PaymentEvent.idempotency_key == idempotency_key)
        )

    def get_payment_event_by_provider_event(
        self,
        *,
        provider: str,
        provider_event_id: str,
    ) -> PaymentEvent | None:
        if not provider_event_id:
            return None
        return self.session.scalar(
            select(PaymentEvent).where(
                PaymentEvent.provider == provider,
                PaymentEvent.provider_event_id == provider_event_id,
            )
        )

    def create_payment_event(
        self,
        *,
        event_id: str,
        provider: str,
        event_kind: str,
        status: str,
        order_id: str | None,
        refund_id: str | None,
        provider_event_id: str | None,
        idempotency_key: str | None,
        payload_json: dict[str, object] | None,
        processed_at: datetime | None,
    ) -> PaymentEvent:
        event = PaymentEvent(
            event_id=event_id,
            provider=provider,
            event_kind=event_kind,
            status=status,
            order_id=order_id,
            refund_id=refund_id,
            provider_event_id=provider_event_id,
            idempotency_key=idempotency_key,
            payload_json=payload_json,
            processed_at=processed_at,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def get_active_entitlement_snapshot(
        self,
        account_id: str,
        *,
        subscription_id: str | None = None,
    ) -> AccountEntitlementSnapshot | None:
        statement = select(AccountEntitlementSnapshot).where(
            AccountEntitlementSnapshot.account_id == account_id,
            AccountEntitlementSnapshot.status == "active",
        )
        if subscription_id:
            statement = statement.where(
                AccountEntitlementSnapshot.subscription_id == subscription_id
            )
        statement = statement.order_by(
            AccountEntitlementSnapshot.generated_at.desc(),
            AccountEntitlementSnapshot.id.desc(),
        )
        return self.session.scalar(statement)

    def count_active_runs(self, site_id: str) -> int:
        statement = (
            select(func.count())
            .select_from(RunRecord)
            .where(
                RunRecord.site_id == site_id,
                RunRecord.status.in_(("queued", "running")),
            )
        )
        return int(self.session.scalar(statement) or 0)

    def count_active_runs_by_site(self, *, site_ids: list[str]) -> dict[str, int]:
        if not site_ids:
            return {}
        statement = (
            select(RunRecord.site_id, func.count())
            .select_from(RunRecord)
            .where(
                RunRecord.site_id.in_(site_ids),
                RunRecord.status.in_(("queued", "running")),
            )
            .group_by(RunRecord.site_id)
        )
        return {
            str(site_id or ""): int(count or 0)
            for site_id, count in self.session.execute(statement)
            if site_id
        }

    def summarize_site_knowledge_current_counts(
        self,
        *,
        site_ids: list[str],
    ) -> dict[str, dict[str, int]]:
        if not site_ids:
            return {}
        items: dict[str, dict[str, int]] = {
            site_id: {"documents": 0, "chunks": 0} for site_id in site_ids
        }
        document_statement = (
            select(SiteKnowledgeDocument.site_id, func.count())
            .select_from(SiteKnowledgeDocument)
            .where(SiteKnowledgeDocument.site_id.in_(site_ids))
            .group_by(SiteKnowledgeDocument.site_id)
        )
        for site_id, count in self.session.execute(document_statement):
            items.setdefault(str(site_id or ""), {"documents": 0, "chunks": 0})[
                "documents"
            ] = int(count or 0)
        chunk_statement = (
            select(SiteKnowledgeChunk.site_id, func.count())
            .select_from(SiteKnowledgeChunk)
            .where(SiteKnowledgeChunk.site_id.in_(site_ids))
            .group_by(SiteKnowledgeChunk.site_id)
        )
        for site_id, count in self.session.execute(chunk_statement):
            items.setdefault(str(site_id or ""), {"documents": 0, "chunks": 0})["chunks"] = int(
                count or 0
            )
        return items

    def summarize_site_knowledge_index_usage(
        self,
        *,
        account_id: str | None = None,
        subscription_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, int]:
        statement = select(
            func.sum(SiteKnowledgeIndexJobMetric.accepted_documents),
            func.sum(SiteKnowledgeIndexJobMetric.indexed_documents),
            func.sum(SiteKnowledgeIndexJobMetric.indexed_chunks),
        )
        if account_id:
            statement = statement.where(SiteKnowledgeIndexJobMetric.account_id == account_id)
        if subscription_id:
            statement = statement.where(
                SiteKnowledgeIndexJobMetric.subscription_id == subscription_id
            )
        if since is not None:
            statement = statement.where(SiteKnowledgeIndexJobMetric.created_at >= since)
        if until is not None:
            statement = statement.where(SiteKnowledgeIndexJobMetric.created_at <= until)
        accepted_documents, indexed_documents, indexed_chunks = self.session.execute(
            statement
        ).one()
        return {
            "accepted_documents": int(accepted_documents or 0),
            "indexed_documents": int(indexed_documents or 0),
            "indexed_chunks": int(indexed_chunks or 0),
        }

    def record_usage_meter_event(
        self,
        *,
        account_id: str | None,
        site_id: str,
        subscription_id: str | None,
        plan_version_id: str | None,
        run_id: str | None,
        provider_call_id: int | None,
        event_kind: str,
        meter_key: str,
        quantity: float,
        ability_family: str | None,
        channel: str | None,
        execution_kind: str | None,
        execution_tier: str | None,
        data_classification: str | None,
        currency: str | None,
        dedupe_key: str,
        payload_json: dict[str, object] | None = None,
    ) -> UsageMeterEvent:
        existing = self.session.scalar(
            select(UsageMeterEvent).where(UsageMeterEvent.dedupe_key == dedupe_key)
        )
        if existing is not None:
            return existing

        event = UsageMeterEvent(
            account_id=account_id,
            site_id=site_id,
            subscription_id=subscription_id,
            plan_version_id=plan_version_id,
            run_id=run_id,
            provider_call_id=provider_call_id,
            event_kind=event_kind,
            meter_key=meter_key,
            quantity=quantity,
            ability_family=ability_family,
            channel=channel,
            execution_kind=execution_kind,
            execution_tier=execution_tier,
            data_classification=data_classification,
            currency=currency,
            dedupe_key=dedupe_key,
            payload_json=payload_json,
            created_at=datetime.now(UTC),
        )
        self.session.add(event)
        self.session.flush()
        return event

    def record_credit_ledger_entry(
        self,
        *,
        account_id: str | None,
        site_id: str | None,
        subscription_id: str | None,
        plan_version_id: str | None,
        run_id: str | None,
        provider_call_id: int | None,
        event_type: str = CREDIT_LEDGER_EVENT_CONSUME,
        source_type: str,
        source_id: str,
        credit_delta: float,
        quantity: float,
        unit: str,
        rate: float,
        rate_unit: str | None,
        rate_version: str,
        idempotency_key: str,
        metadata_json: dict[str, object] | None = None,
        created_at: datetime | None = None,
    ) -> CreditLedgerEntry:
        existing = self.session.scalar(
            select(CreditLedgerEntry).where(
                CreditLedgerEntry.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            return existing

        entry = CreditLedgerEntry(
            ledger_entry_id=f"cle_{uuid4().hex}",
            account_id=account_id,
            site_id=site_id,
            subscription_id=subscription_id,
            plan_version_id=plan_version_id,
            run_id=run_id,
            provider_call_id=provider_call_id,
            event_type=event_type,
            source_type=source_type,
            source_id=source_id,
            credit_delta=round(float(credit_delta or 0.0), 6),
            quantity=round(float(quantity or 0.0), 6),
            unit=unit,
            rate=round(float(rate or 0.0), 6),
            rate_unit=rate_unit,
            rate_version=rate_version,
            idempotency_key=idempotency_key,
            metadata_json=metadata_json,
            created_at=created_at or datetime.now(UTC),
        )
        self.session.add(entry)
        self.session.flush()
        return entry

    def list_credit_ledger_entries(
        self,
        *,
        account_ids: list[str] | None = None,
        site_ids: list[str] | None = None,
        subscription_id: str | None = None,
        event_types: list[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
    ) -> list[CreditLedgerEntry]:
        statement = select(CreditLedgerEntry)
        if account_ids is not None:
            if not account_ids:
                return []
            statement = statement.where(CreditLedgerEntry.account_id.in_(account_ids))
        if site_ids is not None:
            if not site_ids:
                return []
            statement = statement.where(CreditLedgerEntry.site_id.in_(site_ids))
        if subscription_id is not None:
            statement = statement.where(CreditLedgerEntry.subscription_id == subscription_id)
        if event_types is not None:
            if not event_types:
                return []
            statement = statement.where(CreditLedgerEntry.event_type.in_(event_types))
        if since is not None:
            statement = statement.where(CreditLedgerEntry.created_at >= since)
        if until is not None:
            statement = statement.where(CreditLedgerEntry.created_at <= until)
        statement = statement.order_by(
            CreditLedgerEntry.created_at.desc(),
            CreditLedgerEntry.ledger_entry_id.desc(),
        )
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def list_usage_meter_events(
        self,
        site_id: str,
        *,
        subscription_id: str | None = None,
        period_start_at: datetime | None = None,
        period_end_at: datetime | None = None,
        limit: int | None = None,
    ) -> list[UsageMeterEvent]:
        statement = select(UsageMeterEvent).where(UsageMeterEvent.site_id == site_id)
        if subscription_id is not None:
            statement = statement.where(UsageMeterEvent.subscription_id == subscription_id)
        if period_start_at is not None:
            statement = statement.where(UsageMeterEvent.created_at >= period_start_at)
        if period_end_at is not None:
            statement = statement.where(UsageMeterEvent.created_at <= period_end_at)
        statement = statement.order_by(
            UsageMeterEvent.created_at.desc(),
            UsageMeterEvent.id.desc(),
        )
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def list_usage_meter_events_for_admin(
        self,
        *,
        site_ids: list[str] | None = None,
        account_ids: list[str] | None = None,
        ability_family: str | None = None,
        meter_keys: list[str] | None = None,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[UsageMeterEvent]:
        statement = select(UsageMeterEvent)
        if site_ids is not None:
            if not site_ids:
                return []
            statement = statement.where(UsageMeterEvent.site_id.in_(site_ids))
        if account_ids is not None:
            if not account_ids:
                return []
            statement = statement.where(UsageMeterEvent.account_id.in_(account_ids))
        if ability_family:
            statement = statement.where(UsageMeterEvent.ability_family == ability_family)
        if meter_keys is not None:
            if not meter_keys:
                return []
            statement = statement.where(UsageMeterEvent.meter_key.in_(meter_keys))
        if since is not None:
            statement = statement.where(UsageMeterEvent.created_at >= since)
        statement = statement.order_by(
            UsageMeterEvent.created_at.desc(),
            UsageMeterEvent.id.desc(),
        )
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def summarize_usage_meter_events_for_admin(
        self,
        *,
        since: datetime | None = None,
    ) -> dict[str, object]:
        count_statement = select(func.count(UsageMeterEvent.id))
        totals_statement = (
            select(UsageMeterEvent.meter_key, func.sum(UsageMeterEvent.quantity))
            .where(UsageMeterEvent.meter_key.is_not(None))
            .group_by(UsageMeterEvent.meter_key)
        )
        if since is not None:
            count_statement = count_statement.where(UsageMeterEvent.created_at >= since)
            totals_statement = totals_statement.where(UsageMeterEvent.created_at >= since)
        totals = {
            str(meter_key or ""): round(float(quantity or 0.0), 6)
            for meter_key, quantity in self.session.execute(totals_statement)
            if meter_key
        }
        return {
            "event_count": int(self.session.scalar(count_statement) or 0),
            "totals": dict(sorted(totals.items())),
        }

    def list_run_records_for_admin(
        self,
        *,
        site_id: str | None = None,
        ability_family: str | None = None,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[RunRecord]:
        statement = select(RunRecord)
        if site_id:
            statement = statement.where(RunRecord.site_id == site_id)
        if ability_family:
            statement = statement.where(RunRecord.ability_family == ability_family)
        if since is not None:
            statement = statement.where(RunRecord.started_at >= since)
        statement = statement.order_by(RunRecord.started_at.desc(), RunRecord.run_id.desc())
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def list_provider_call_records_for_admin(
        self,
        *,
        site_id: str | None = None,
        ability_family: str | None = None,
        since: datetime | None = None,
        run_ids: list[str] | None = None,
        limit: int | None = None,
    ) -> list[ProviderCallRecord]:
        statement = select(ProviderCallRecord)
        if site_id or ability_family:
            statement = statement.join(RunRecord, RunRecord.run_id == ProviderCallRecord.run_id)
        if site_id:
            statement = statement.where(RunRecord.site_id == site_id)
        if ability_family:
            statement = statement.where(RunRecord.ability_family == ability_family)
        if run_ids is not None:
            if not run_ids:
                return []
            statement = statement.where(ProviderCallRecord.run_id.in_(run_ids))
        if since is not None:
            statement = statement.where(ProviderCallRecord.created_at >= since)
        statement = statement.order_by(
            ProviderCallRecord.created_at.desc(),
            ProviderCallRecord.id.desc(),
        )
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def summarize_usage_meter_by_site(
        self,
        *,
        site_ids: list[str] | None = None,
        since: datetime | None = None,
    ) -> dict[str, dict[str, object]]:
        statement = select(
            UsageMeterEvent.site_id,
            func.count(UsageMeterEvent.id),
            func.sum(UsageMeterEvent.quantity),
            func.max(UsageMeterEvent.created_at),
        ).group_by(UsageMeterEvent.site_id)
        if site_ids is not None:
            if not site_ids:
                return {}
            statement = statement.where(UsageMeterEvent.site_id.in_(site_ids))
        if since is not None:
            statement = statement.where(UsageMeterEvent.created_at >= since)
        items: dict[str, dict[str, object]] = {}
        for site_id, event_count, quantity_total, last_seen_at in self.session.execute(statement):
            items[str(site_id or "")] = {
                "event_count": int(event_count or 0),
                "quantity_total": round(float(quantity_total or 0.0), 6),
                "last_seen_at": self._serialize_datetime(last_seen_at),
            }
        return items

    def list_billing_snapshots(self, site_id: str) -> list[BillingSnapshot]:
        statement = (
            select(BillingSnapshot)
            .where(BillingSnapshot.site_id == site_id)
            .order_by(BillingSnapshot.period_start_at.desc(), BillingSnapshot.snapshot_id.desc())
        )
        return list(self.session.scalars(statement))

    def get_latest_billing_snapshots_by_site(
        self,
        *,
        site_ids: list[str] | None = None,
    ) -> dict[str, BillingSnapshot]:
        statement = select(BillingSnapshot)
        if site_ids is not None:
            if not site_ids:
                return {}
            statement = statement.where(BillingSnapshot.site_id.in_(site_ids))
        statement = statement.order_by(
            BillingSnapshot.site_id.asc(),
            BillingSnapshot.period_end_at.desc(),
            BillingSnapshot.generated_at.desc(),
            BillingSnapshot.snapshot_id.desc(),
        )
        items: dict[str, BillingSnapshot] = {}
        for snapshot in self.session.scalars(statement):
            site_id = str(snapshot.site_id or "")
            if site_id and site_id not in items:
                items[site_id] = snapshot
        return items

    def count_subscriptions_expiring_by(
        self,
        *,
        before: datetime,
        statuses: list[str] | None = None,
    ) -> int:
        statement = (
            select(func.count())
            .select_from(AccountSubscription)
            .where(
                AccountSubscription.current_period_end_at.is_not(None),
                AccountSubscription.current_period_end_at <= before,
            )
        )
        if statuses:
            statement = statement.where(AccountSubscription.status.in_(statuses))
        return int(self.session.scalar(statement) or 0)

    def record_service_audit_event(
        self,
        *,
        account_id: str | None,
        site_id: str | None,
        key_id: str | None,
        subscription_id: str | None,
        plan_id: str | None,
        plan_version_id: str | None,
        scope_kind: str | None,
        scope_id: str | None,
        event_kind: str,
        outcome: str,
        method: str | None,
        path: str | None,
        trace_id: str | None,
        idempotency_key: str | None,
        actor_kind: str,
        actor_ref: str | None,
        payload_json: dict[str, object] | None = None,
    ) -> ServiceAuditEvent:
        event = ServiceAuditEvent(
            account_id=account_id,
            site_id=site_id,
            key_id=key_id,
            subscription_id=subscription_id,
            plan_id=plan_id,
            plan_version_id=plan_version_id,
            scope_kind=scope_kind,
            scope_id=scope_id,
            event_kind=event_kind,
            outcome=outcome,
            method=method,
            path=path,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            actor_kind=actor_kind,
            actor_ref=actor_ref,
            payload_json=payload_json,
            created_at=datetime.now(UTC),
        )
        self.session.add(event)
        self.session.flush()
        return event

    def list_service_audit_events(
        self,
        *,
        site_id: str | None = None,
        account_id: str | None = None,
        event_kind: str | None = None,
        outcome: str | None = None,
        limit: int = 50,
    ) -> list[ServiceAuditEvent]:
        statement = select(ServiceAuditEvent)
        if site_id:
            statement = statement.where(ServiceAuditEvent.site_id == site_id)
        if account_id:
            statement = statement.where(ServiceAuditEvent.account_id == account_id)
        if event_kind:
            statement = statement.where(ServiceAuditEvent.event_kind == event_kind)
        if outcome:
            statement = statement.where(ServiceAuditEvent.outcome == outcome)
        statement = statement.order_by(
            ServiceAuditEvent.created_at.desc(),
            ServiceAuditEvent.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def count_service_audit_events(
        self,
        *,
        site_id: str | None = None,
        account_id: str | None = None,
        event_kind: str | None = None,
        outcome: str | None = None,
        since: datetime | None = None,
    ) -> int:
        return int(
            self.session.scalar(
                cast(
                    Any,
                    select(func.count())
                    .select_from(ServiceAuditEvent)
                    .where(
                        *self._service_audit_filters(
                            site_id=site_id,
                            account_id=account_id,
                            event_kind=event_kind,
                            outcome=outcome,
                            since=since,
                        )
                    ),
                )
            )
            or 0
        )

    def summarize_service_audit_events(
        self,
        *,
        site_id: str | None = None,
        account_id: str | None = None,
        since: datetime | None = None,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        event_count = func.count(ServiceAuditEvent.id).label("event_count")
        first_seen_at = func.min(ServiceAuditEvent.created_at).label("first_seen_at")
        last_seen_at = func.max(ServiceAuditEvent.created_at).label("last_seen_at")
        statement = (
            select(
                ServiceAuditEvent.event_kind,
                ServiceAuditEvent.outcome,
                event_count,
                first_seen_at,
                last_seen_at,
            )
            .where(
                *self._service_audit_filters(
                    site_id=site_id,
                    account_id=account_id,
                    since=since,
                )
            )
            .group_by(ServiceAuditEvent.event_kind, ServiceAuditEvent.outcome)
            .order_by(event_count.desc(), last_seen_at.desc())
            .limit(max(1, limit))
        )
        items: list[dict[str, object]] = []
        for event_kind_value, outcome_value, count, first_seen, last_seen in self.session.execute(
            statement
        ):
            items.append(
                {
                    "event_kind": str(event_kind_value or ""),
                    "outcome": str(outcome_value or ""),
                    "count": int(count or 0),
                    "first_seen_at": self._serialize_datetime(first_seen),
                    "last_seen_at": self._serialize_datetime(last_seen),
                }
            )
        return items

    def record_commercial_decision_event(
        self,
        *,
        account_id: str | None,
        site_id: str | None,
        subscription_id: str | None,
        plan_version_id: str | None,
        run_id: str | None,
        request_kind: str,
        decision: str,
        decision_code: str,
        ability_family: str | None,
        channel: str | None,
        execution_kind: str | None,
        execution_tier: str | None,
        data_classification: str | None,
        trace_id: str | None,
        idempotency_key: str | None,
        payload_json: dict[str, object] | None = None,
    ) -> CommercialDecisionEvent:
        event = CommercialDecisionEvent(
            account_id=account_id,
            site_id=site_id,
            subscription_id=subscription_id,
            plan_version_id=plan_version_id,
            run_id=run_id,
            request_kind=request_kind,
            decision=decision,
            decision_code=decision_code,
            ability_family=ability_family,
            channel=channel,
            execution_kind=execution_kind,
            execution_tier=execution_tier,
            data_classification=data_classification,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            payload_json=payload_json,
            created_at=datetime.now(UTC),
        )
        self.session.add(event)
        self.session.flush()
        return event

    def list_commercial_decision_events(
        self,
        *,
        site_id: str | None = None,
        subscription_id: str | None = None,
        decision: str | None = None,
        decision_code: str | None = None,
        request_kind: str | None = None,
        since: datetime | None = None,
        limit: int | None = 50,
    ) -> list[CommercialDecisionEvent]:
        statement = select(CommercialDecisionEvent)
        if site_id:
            statement = statement.where(CommercialDecisionEvent.site_id == site_id)
        if subscription_id:
            statement = statement.where(CommercialDecisionEvent.subscription_id == subscription_id)
        if decision:
            statement = statement.where(CommercialDecisionEvent.decision == decision)
        if decision_code:
            statement = statement.where(CommercialDecisionEvent.decision_code == decision_code)
        if request_kind:
            statement = statement.where(CommercialDecisionEvent.request_kind == request_kind)
        if since is not None:
            statement = statement.where(CommercialDecisionEvent.created_at >= since)
        statement = statement.order_by(
            CommercialDecisionEvent.created_at.desc(),
            CommercialDecisionEvent.id.desc(),
        )
        if limit is not None:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def count_commercial_decision_events(
        self,
        *,
        site_id: str | None = None,
        subscription_id: str | None = None,
        decision: str | None = None,
        decision_code: str | None = None,
        request_kind: str | None = None,
        since: datetime | None = None,
    ) -> int:
        return int(
            self.session.scalar(
                cast(
                    Any,
                    select(func.count())
                    .select_from(CommercialDecisionEvent)
                    .where(
                        *self._commercial_decision_filters(
                            site_id=site_id,
                            subscription_id=subscription_id,
                            decision=decision,
                            decision_code=decision_code,
                            request_kind=request_kind,
                            since=since,
                        )
                    ),
                )
            )
            or 0
        )

    def summarize_commercial_decision_events(
        self,
        *,
        site_id: str | None = None,
        subscription_id: str | None = None,
        request_kind: str | None = None,
        since: datetime | None = None,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        event_count = func.count(CommercialDecisionEvent.id).label("event_count")
        first_seen_at = func.min(CommercialDecisionEvent.created_at).label("first_seen_at")
        last_seen_at = func.max(CommercialDecisionEvent.created_at).label("last_seen_at")
        statement = (
            select(
                CommercialDecisionEvent.request_kind,
                CommercialDecisionEvent.decision,
                CommercialDecisionEvent.decision_code,
                event_count,
                first_seen_at,
                last_seen_at,
            )
            .where(
                *self._commercial_decision_filters(
                    site_id=site_id,
                    subscription_id=subscription_id,
                    request_kind=request_kind,
                    since=since,
                )
            )
            .group_by(
                CommercialDecisionEvent.request_kind,
                CommercialDecisionEvent.decision,
                CommercialDecisionEvent.decision_code,
            )
            .order_by(event_count.desc(), last_seen_at.desc())
            .limit(max(1, limit))
        )
        items: list[dict[str, object]] = []
        for (
            request_kind_value,
            decision_value,
            decision_code_value,
            count,
            first_seen,
            last_seen,
        ) in self.session.execute(statement):
            items.append(
                {
                    "request_kind": str(request_kind_value or ""),
                    "decision": str(decision_value or ""),
                    "decision_code": str(decision_code_value or ""),
                    "count": int(count or 0),
                    "first_seen_at": self._serialize_datetime(first_seen),
                    "last_seen_at": self._serialize_datetime(last_seen),
                }
            )
        return items

    def upsert_billing_snapshot(
        self,
        *,
        snapshot_id: str,
        account_id: str | None,
        site_id: str | None,
        subscription_id: str | None,
        plan_version_id: str | None,
        currency: str,
        period_start_at: datetime,
        period_end_at: datetime,
        totals_json: dict[str, object],
        breakdown_json: dict[str, object],
    ) -> BillingSnapshot:
        snapshot = self.session.get(BillingSnapshot, snapshot_id)
        if snapshot is None:
            snapshot = BillingSnapshot(
                snapshot_id=snapshot_id,
                account_id=account_id,
                site_id=site_id,
                subscription_id=subscription_id,
                plan_version_id=plan_version_id,
                currency=currency,
                period_start_at=period_start_at,
                period_end_at=period_end_at,
                totals_json=totals_json,
                breakdown_json=breakdown_json,
            )
            self.session.add(snapshot)
        else:
            snapshot.account_id = account_id
            snapshot.site_id = site_id
            snapshot.subscription_id = subscription_id
            snapshot.plan_version_id = plan_version_id
            snapshot.currency = currency
            snapshot.period_start_at = period_start_at
            snapshot.period_end_at = period_end_at
            snapshot.totals_json = totals_json
            snapshot.breakdown_json = breakdown_json
        self.session.flush()
        return snapshot

    def _service_audit_filters(
        self,
        *,
        site_id: str | None = None,
        account_id: str | None = None,
        event_kind: str | None = None,
        outcome: str | None = None,
        since: datetime | None = None,
    ) -> list[SQLAFilter]:
        filters: list[SQLAFilter] = []
        if site_id:
            filters.append(ServiceAuditEvent.site_id == site_id)
        if account_id:
            filters.append(ServiceAuditEvent.account_id == account_id)
        if event_kind:
            filters.append(ServiceAuditEvent.event_kind == event_kind)
        if outcome:
            filters.append(ServiceAuditEvent.outcome == outcome)
        if since is not None:
            filters.append(ServiceAuditEvent.created_at >= since)
        return filters

    def _commercial_decision_filters(
        self,
        *,
        site_id: str | None = None,
        subscription_id: str | None = None,
        decision: str | None = None,
        decision_code: str | None = None,
        request_kind: str | None = None,
        since: datetime | None = None,
    ) -> list[SQLAFilter]:
        filters: list[SQLAFilter] = []
        if site_id:
            filters.append(CommercialDecisionEvent.site_id == site_id)
        if subscription_id:
            filters.append(CommercialDecisionEvent.subscription_id == subscription_id)
        if decision:
            filters.append(CommercialDecisionEvent.decision == decision)
        if decision_code:
            filters.append(CommercialDecisionEvent.decision_code == decision_code)
        if request_kind:
            filters.append(CommercialDecisionEvent.request_kind == request_kind)
        if since is not None:
            filters.append(CommercialDecisionEvent.created_at >= since)
        return filters

    def _serialize_datetime(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return normalized.isoformat().replace("+00:00", "Z")
