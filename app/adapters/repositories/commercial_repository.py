from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.models import (
    ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE,
    ACCOUNT_USER_MEMBERSHIP_STATUS_REVOKED,
    CREDIT_LEDGER_EVENT_CONSUME,
    IDENTITY_PROVIDER_BINDING_STATUS_ACTIVE,
    IDENTITY_PROVIDER_BINDING_STATUS_REVOKED,
    PAYMENT_ORDER_STATUS_PENDING,
    PORTAL_LOGIN_CODE_STATUS_PENDING,
    PORTAL_OAUTH_STATE_STATUS_PENDING,
    PRINCIPAL_STATUS_ACTIVE,
    Account,
    AccountEntitlementSnapshot,
    AccountSubscription,
    AccountUserMembership,
    BillingSnapshot,
    CommercialDecisionEvent,
    CreditLedgerEntry,
    IdentityProviderBinding,
    PaymentEvent,
    PaymentOrder,
    PaymentRefund,
    Plan,
    PlanOffer,
    PlanVersion,
    PlatformAdminGrant,
    PortalLoginCode,
    PortalOAuthState,
    Principal,
    ProviderCallRecord,
    RunRecord,
    ServiceAuditEvent,
    Site,
    SiteApiKey,
    SiteKnowledgeChunk,
    SiteKnowledgeDocument,
    SiteKnowledgeIndexJobMetric,
    SubscriptionOrder,
    SupportRequest,
    SupportRequestAttachment,
    SupportRequestFeedback,
    SupportRequestMessage,
    TrialClaim,
    UsageMeterEvent,
)

type SQLAFilter = ColumnElement[bool]


class CommercialRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_account(self, account_id: str) -> Account | None:
        return self.session.get(Account, account_id)

    def get_account_for_update(self, account_id: str) -> Account | None:
        return self.session.scalar(
            select(Account).where(Account.account_id == account_id).with_for_update()
        )

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

    def get_support_request(self, request_id: str) -> SupportRequest | None:
        return self.session.get(SupportRequest, request_id)

    def create_support_request(
        self,
        *,
        request_id: str,
        account_id: str,
        site_id: str | None,
        principal_id: str,
        email: str,
        topic: str,
        title: str,
        description: str,
        status: str,
        priority: str,
        source_path: str,
        admin_note: str | None = None,
        context_json: dict[str, object] | None = None,
    ) -> SupportRequest:
        request = SupportRequest(
            request_id=request_id,
            account_id=account_id,
            site_id=site_id or None,
            principal_id=principal_id or None,
            email=email,
            topic=topic,
            title=title,
            description=description,
            status=status,
            priority=priority,
            source_path=source_path,
            admin_note=admin_note,
            context_json=context_json,
        )
        self.session.add(request)
        self.session.flush()
        return request

    def create_support_request_message(
        self,
        *,
        message_id: str,
        request: SupportRequest,
        author_kind: str,
        visibility: str,
        body: str,
        principal_id: str | None = None,
        email: str = "",
        metadata_json: dict[str, object] | None = None,
    ) -> SupportRequestMessage:
        message = SupportRequestMessage(
            message_id=message_id,
            request_id=str(request.request_id or ""),
            account_id=str(request.account_id or ""),
            site_id=str(request.site_id or "") or None,
            principal_id=str(principal_id or request.principal_id or "") or None,
            email=str(email or request.email or ""),
            author_kind=author_kind,
            visibility=visibility,
            body=body,
            metadata_json=metadata_json,
        )
        request.updated_at = datetime.now(UTC)
        self.session.add(message)
        self.session.flush()
        return message

    def list_support_request_messages(
        self,
        *,
        request_id: str,
        include_internal: bool = False,
    ) -> list[SupportRequestMessage]:
        statement = select(SupportRequestMessage).where(
            SupportRequestMessage.request_id == request_id
        )
        if not include_internal:
            statement = statement.where(SupportRequestMessage.visibility == "public")
        statement = statement.order_by(
            SupportRequestMessage.created_at.asc(),
            SupportRequestMessage.message_id.asc(),
        )
        return list(self.session.scalars(statement))

    def create_support_request_attachment(
        self,
        *,
        attachment_id: str,
        request: SupportRequest,
        uploader_kind: str,
        visibility: str,
        filename: str,
        content_type: str,
        content_bytes: bytes,
        message_id: str | None = None,
        principal_id: str | None = None,
        email: str = "",
        metadata_json: dict[str, object] | None = None,
    ) -> SupportRequestAttachment:
        attachment = SupportRequestAttachment(
            attachment_id=attachment_id,
            request_id=str(request.request_id or ""),
            message_id=str(message_id or "") or None,
            account_id=str(request.account_id or ""),
            site_id=str(request.site_id or "") or None,
            principal_id=str(principal_id or request.principal_id or "") or None,
            email=str(email or request.email or ""),
            uploader_kind=uploader_kind,
            visibility=visibility,
            filename=filename,
            content_type=content_type,
            byte_size=len(content_bytes),
            content_bytes=content_bytes,
            metadata_json=metadata_json,
        )
        request.updated_at = datetime.now(UTC)
        self.session.add(attachment)
        self.session.flush()
        return attachment

    def get_support_request_attachment(
        self,
        attachment_id: str,
    ) -> SupportRequestAttachment | None:
        return self.session.get(SupportRequestAttachment, attachment_id)

    def list_support_request_attachments(
        self,
        *,
        request_id: str,
        include_internal: bool = False,
    ) -> list[SupportRequestAttachment]:
        statement = select(SupportRequestAttachment).where(
            SupportRequestAttachment.request_id == request_id
        )
        if not include_internal:
            statement = statement.where(SupportRequestAttachment.visibility == "public")
        statement = statement.order_by(
            SupportRequestAttachment.created_at.asc(),
            SupportRequestAttachment.attachment_id.asc(),
        )
        return list(self.session.scalars(statement))

    def count_support_request_attachments(self, *, request_id: str) -> int:
        statement = select(func.count(SupportRequestAttachment.attachment_id)).where(
            SupportRequestAttachment.request_id == request_id
        )
        return int(self.session.scalar(statement) or 0)

    def get_support_request_feedback(self, request_id: str) -> SupportRequestFeedback | None:
        statement = select(SupportRequestFeedback).where(
            SupportRequestFeedback.request_id == request_id
        )
        return self.session.scalar(statement)

    def upsert_support_request_feedback(
        self,
        *,
        feedback_id: str,
        request: SupportRequest,
        principal_id: str,
        email: str,
        resolved: bool,
        rating: int,
        comment: str,
        metadata_json: dict[str, object] | None = None,
    ) -> SupportRequestFeedback:
        feedback = self.get_support_request_feedback(str(request.request_id or ""))
        if feedback is None:
            feedback = SupportRequestFeedback(
                feedback_id=feedback_id,
                request_id=str(request.request_id or ""),
                account_id=str(request.account_id or ""),
                site_id=str(request.site_id or "") or None,
                principal_id=principal_id,
                email=email,
                resolved=resolved,
                rating=rating,
                comment=comment,
                metadata_json=metadata_json,
            )
            self.session.add(feedback)
        else:
            feedback.principal_id = principal_id
            feedback.email = email
            feedback.resolved = resolved
            feedback.rating = rating
            feedback.comment = comment
            feedback.metadata_json = metadata_json
        request.updated_at = datetime.now(UTC)
        self.session.flush()
        return feedback

    def list_support_requests(
        self,
        *,
        account_id: str | None = None,
        site_id: str | None = None,
        principal_id: str | None = None,
        status: str | None = None,
        topic: str | None = None,
        query: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[SupportRequest]:
        statement = select(SupportRequest).where(
            *self._support_request_filters(
                account_id=account_id,
                site_id=site_id,
                principal_id=principal_id,
                status=status,
                topic=topic,
                query=query,
            )
        )
        statement = statement.order_by(
            SupportRequest.updated_at.desc(),
            SupportRequest.created_at.desc(),
            SupportRequest.request_id.desc(),
        )
        if offset > 0:
            statement = statement.offset(offset)
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def count_support_requests(
        self,
        *,
        account_id: str | None = None,
        site_id: str | None = None,
        principal_id: str | None = None,
        status: str | None = None,
        topic: str | None = None,
        query: str | None = None,
    ) -> int:
        statement = select(func.count(SupportRequest.request_id)).where(
            *self._support_request_filters(
                account_id=account_id,
                site_id=site_id,
                principal_id=principal_id,
                status=status,
                topic=topic,
                query=query,
            )
        )
        return int(self.session.scalar(statement) or 0)

    def _support_request_filters(
        self,
        *,
        account_id: str | None,
        site_id: str | None,
        principal_id: str | None,
        status: str | None,
        topic: str | None,
        query: str | None,
    ) -> list[SQLAFilter]:
        filters: list[SQLAFilter] = []
        if account_id:
            filters.append(SupportRequest.account_id == account_id)
        if site_id:
            filters.append(SupportRequest.site_id == site_id)
        if principal_id:
            filters.append(SupportRequest.principal_id == principal_id)
        if status:
            filters.append(SupportRequest.status == status)
        if topic:
            filters.append(SupportRequest.topic == topic)
        normalized_query = str(query or "").strip().lower()
        if normalized_query:
            pattern = f"%{normalized_query}%"
            filters.append(
                or_(
                    func.lower(SupportRequest.request_id).like(pattern),
                    func.lower(SupportRequest.email).like(pattern),
                    func.lower(SupportRequest.title).like(pattern),
                    func.lower(SupportRequest.account_id).like(pattern),
                    func.lower(SupportRequest.site_id).like(pattern),
                )
            )
        return filters

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
        principal_id: str,
        code_hash: str,
        expires_at: datetime,
        metadata_json: dict[str, object] | None = None,
    ) -> PortalLoginCode:
        code = PortalLoginCode(
            code_id=code_id,
            email=email,
            principal_id=principal_id,
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
        principal_id: str | None = None,
        status: str | None = None,
        active_only: bool = False,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> list[PortalLoginCode]:
        statement = select(PortalLoginCode)
        if email:
            statement = statement.where(func.lower(PortalLoginCode.email) == email.lower())
        if principal_id:
            statement = statement.where(PortalLoginCode.principal_id == principal_id)
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

    def get_principal_identity_by_email(self, *, email: str) -> Principal | None:
        if not str(email or "").strip():
            return None
        return self.session.scalar(
            select(Principal).where(func.lower(Principal.email) == email.lower())
        )

    def get_principal_identity(self, principal_id: str) -> Principal | None:
        return self.session.get(Principal, principal_id)

    def get_principal_identity_by_ref(
        self,
        *,
        principal_id: str,
    ) -> Principal | None:
        return self.session.scalar(select(Principal).where(Principal.principal_id == principal_id))

    def get_identity_provider_binding(
        self,
        *,
        provider: str,
        external_subject_hash: str,
    ) -> IdentityProviderBinding | None:
        return self.session.scalar(
            select(IdentityProviderBinding).where(
                IdentityProviderBinding.provider == provider,
                IdentityProviderBinding.external_subject_hash == external_subject_hash,
            )
        )

    def get_identity_provider_binding_by_unionid(
        self,
        *,
        provider: str,
        unionid_hash: str,
    ) -> IdentityProviderBinding | None:
        if not unionid_hash:
            return None
        return self.session.scalar(
            select(IdentityProviderBinding).where(
                IdentityProviderBinding.provider == provider,
                IdentityProviderBinding.unionid_hash == unionid_hash,
            )
        )

    def list_identity_provider_bindings_for_principal(
        self,
        *,
        principal_id: str,
        provider: str | None = None,
        status: str | None = None,
    ) -> list[IdentityProviderBinding]:
        statement = select(IdentityProviderBinding).where(
            IdentityProviderBinding.principal_id == principal_id,
        )
        if provider:
            statement = statement.where(IdentityProviderBinding.provider == provider)
        if status:
            statement = statement.where(IdentityProviderBinding.status == status)
        statement = statement.order_by(
            IdentityProviderBinding.created_at.desc(),
            IdentityProviderBinding.binding_id.desc(),
        )
        return list(self.session.scalars(statement))

    def list_identity_provider_bindings(
        self,
        *,
        principal_ids: list[str] | None = None,
        provider: str | None = None,
        statuses: list[str] | None = None,
    ) -> list[IdentityProviderBinding]:
        statement = select(IdentityProviderBinding)
        if principal_ids is not None:
            if not principal_ids:
                return []
            statement = statement.where(IdentityProviderBinding.principal_id.in_(principal_ids))
        if provider:
            statement = statement.where(IdentityProviderBinding.provider == provider)
        if statuses is not None:
            if not statuses:
                return []
            statement = statement.where(IdentityProviderBinding.status.in_(statuses))
        statement = statement.order_by(
            IdentityProviderBinding.created_at.desc(),
            IdentityProviderBinding.binding_id.desc(),
        )
        return list(self.session.scalars(statement))

    def revoke_identity_provider_bindings(
        self,
        *,
        principal_id: str,
        provider: str | None = None,
    ) -> int:
        bindings = self.list_identity_provider_bindings(
            principal_ids=[principal_id],
            provider=provider,
            statuses=[IDENTITY_PROVIDER_BINDING_STATUS_ACTIVE],
        )
        for binding in bindings:
            binding.status = IDENTITY_PROVIDER_BINDING_STATUS_REVOKED
        self.session.flush()
        return len(bindings)

    def upsert_identity_provider_binding(
        self,
        *,
        binding_id: str,
        principal_id: str,
        provider: str,
        external_subject_hash: str,
        unionid_hash: str | None,
        status: str = IDENTITY_PROVIDER_BINDING_STATUS_ACTIVE,
        metadata_json: dict[str, object] | None = None,
        last_login_at: datetime | None = None,
    ) -> IdentityProviderBinding:
        binding = self.get_identity_provider_binding(
            provider=provider,
            external_subject_hash=external_subject_hash,
        )
        if binding is None:
            binding = IdentityProviderBinding(
                binding_id=binding_id,
                principal_id=principal_id,
                provider=provider,
                external_subject_hash=external_subject_hash,
                unionid_hash=unionid_hash or None,
                status=status,
                metadata_json=metadata_json,
                last_login_at=last_login_at,
            )
            self.session.add(binding)
        else:
            binding.principal_id = principal_id
            binding.unionid_hash = unionid_hash or None
            binding.status = status
            binding.metadata_json = metadata_json
            if last_login_at is not None:
                binding.last_login_at = last_login_at
        self.session.flush()
        return binding

    def get_portal_oauth_state(
        self,
        *,
        provider: str,
        state_hash: str,
    ) -> PortalOAuthState | None:
        return self.session.scalar(
            select(PortalOAuthState).where(
                PortalOAuthState.provider == provider,
                PortalOAuthState.state_hash == state_hash,
            )
        )

    def create_portal_oauth_state(
        self,
        *,
        state_id: str,
        provider: str,
        state_hash: str,
        return_to: str | None,
        client_scope_id: str | None,
        expires_at: datetime,
        metadata_json: dict[str, object] | None = None,
    ) -> PortalOAuthState:
        state = PortalOAuthState(
            state_id=state_id,
            provider=provider,
            state_hash=state_hash,
            status=PORTAL_OAUTH_STATE_STATUS_PENDING,
            return_to=return_to or None,
            client_scope_id=client_scope_id or None,
            expires_at=expires_at,
            consumed_at=None,
            metadata_json=metadata_json,
        )
        self.session.add(state)
        self.session.flush()
        return state

    def count_principals(self, *, status: str | None = None) -> int:
        statement = select(func.count(Principal.principal_id))
        if status:
            statement = statement.where(Principal.status == status)
        return int(self.session.scalar(statement) or 0)

    def list_principals(
        self,
        *,
        status: str | None = None,
        principal_ids: list[str] | None = None,
        limit: int | None = None,
    ) -> list[Principal]:
        statement = select(Principal)
        if status:
            statement = statement.where(Principal.status == status)
        if principal_ids is not None:
            if not principal_ids:
                return []
            statement = statement.where(Principal.principal_id.in_(principal_ids))
        statement = statement.order_by(Principal.created_at.desc(), Principal.principal_id.asc())
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def upsert_principal_identity(
        self,
        *,
        principal_id: str,
        email: str | None,
        status: str = PRINCIPAL_STATUS_ACTIVE,
        metadata_json: dict[str, object] | None = None,
        last_login_at: datetime | None = None,
    ) -> Principal:
        identity = self.get_principal_identity_by_ref(principal_id=principal_id)
        if identity is None and email:
            identity = self.get_principal_identity_by_email(email=email)
        if identity is None:
            identity = Principal(
                principal_id=principal_id,
                email=email,
                status=status,
                metadata_json=metadata_json,
                last_login_at=last_login_at,
            )
            self.session.add(identity)
        else:
            identity.email = email
            identity.status = status
            identity.metadata_json = metadata_json
            if last_login_at is not None:
                identity.last_login_at = last_login_at
        self.session.flush()
        return identity

    def increment_principal_session_version(self, *, principal_id: str) -> Principal | None:
        identity = self.get_principal_identity_by_ref(principal_id=principal_id)
        if identity is None:
            return None
        identity.session_version = int(identity.session_version or 0) + 1
        self.session.flush()
        return identity

    def upsert_account_user_membership(
        self,
        *,
        membership_id: str,
        principal_id: str,
        account_id: str,
        role: str,
        status: str = ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE,
        allowed_actions_json: list[str] | None = None,
        metadata_json: dict[str, object] | None = None,
    ) -> AccountUserMembership:
        membership = self.session.scalar(
            select(AccountUserMembership).where(
                AccountUserMembership.principal_id == principal_id,
                AccountUserMembership.account_id == account_id,
            )
        )
        if membership is None:
            membership = AccountUserMembership(
                membership_id=membership_id,
                principal_id=principal_id,
                account_id=account_id,
                role=role,
                status=status,
                allowed_actions_json=allowed_actions_json or [],
                metadata_json=metadata_json,
            )
            self.session.add(membership)
        else:
            membership.role = role
            membership.status = status
            membership.allowed_actions_json = allowed_actions_json or []
            membership.metadata_json = metadata_json
        self.session.flush()
        return membership

    def list_account_user_memberships(
        self,
        *,
        principal_ids: list[str] | None = None,
        account_ids: list[str] | None = None,
        statuses: list[str] | None = None,
    ) -> list[AccountUserMembership]:
        statement = select(AccountUserMembership)
        if principal_ids is not None:
            if not principal_ids:
                return []
            statement = statement.where(AccountUserMembership.principal_id.in_(principal_ids))
        if account_ids is not None:
            if not account_ids:
                return []
            statement = statement.where(AccountUserMembership.account_id.in_(account_ids))
        if statuses is not None:
            if not statuses:
                return []
            statement = statement.where(AccountUserMembership.status.in_(statuses))
        statement = statement.order_by(
            AccountUserMembership.created_at.desc(),
            AccountUserMembership.membership_id.desc(),
        )
        return list(self.session.scalars(statement))

    def revoke_account_user_memberships(self, *, principal_id: str) -> int:
        memberships = self.list_account_user_memberships(
            principal_ids=[principal_id],
            statuses=[ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE],
        )
        for membership in memberships:
            membership.status = ACCOUNT_USER_MEMBERSHIP_STATUS_REVOKED
        self.session.flush()
        return len(memberships)

    def get_account_user_membership(
        self,
        *,
        principal_id: str,
        account_id: str,
    ) -> tuple[Account, Principal, AccountUserMembership] | None:
        row = self.session.execute(
            select(Account, Principal, AccountUserMembership)
            .join(
                AccountUserMembership,
                AccountUserMembership.account_id == Account.account_id,
            )
            .join(Principal, Principal.principal_id == AccountUserMembership.principal_id)
            .where(
                AccountUserMembership.principal_id == principal_id,
                AccountUserMembership.account_id == account_id,
            )
        ).first()
        if row is None:
            return None
        return row[0], row[1], row[2]

    def list_accounts_for_principal(
        self,
        *,
        principal_id: str,
        membership_statuses: list[str] | None = None,
    ) -> list[tuple[Account, Principal, AccountUserMembership]]:
        statuses = membership_statuses or [ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE]
        statement = (
            select(Account, Principal, AccountUserMembership)
            .join(
                AccountUserMembership,
                AccountUserMembership.account_id == Account.account_id,
            )
            .join(Principal, Principal.principal_id == AccountUserMembership.principal_id)
            .where(
                Principal.principal_id == principal_id,
                Principal.status == PRINCIPAL_STATUS_ACTIVE,
                AccountUserMembership.status.in_(statuses),
                Account.status == "active",
            )
            .order_by(Account.created_at.desc(), Account.account_id.asc())
        )
        return [
            (account, identity, membership)
            for account, identity, membership in self.session.execute(statement).all()
        ]

    def list_sites_for_principal(
        self,
        *,
        principal_id: str,
        membership_statuses: list[str] | None = None,
    ) -> list[tuple[Site, Principal, AccountUserMembership]]:
        statuses = membership_statuses or [ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE]
        statement = (
            select(Site, Principal, AccountUserMembership)
            .join(
                AccountUserMembership,
                AccountUserMembership.account_id == Site.account_id,
            )
            .join(Principal, Principal.principal_id == AccountUserMembership.principal_id)
            .join(Account, Account.account_id == Site.account_id)
            .where(
                Principal.principal_id == principal_id,
                Principal.status == PRINCIPAL_STATUS_ACTIVE,
                AccountUserMembership.status.in_(statuses),
                Account.status == "active",
            )
            .order_by(Site.created_at.desc(), Site.site_id.asc())
        )
        return [
            (site, identity, membership)
            for site, identity, membership in self.session.execute(statement).all()
        ]

    def get_portal_site_access(
        self,
        *,
        principal_id: str,
        site_id: str,
    ) -> tuple[Site, Account, Principal | None, AccountUserMembership | None] | None:
        row = self.session.execute(
            select(Site, Account, Principal, AccountUserMembership)
            .join(Account, Account.account_id == Site.account_id)
            .outerjoin(
                AccountUserMembership,
                and_(
                    AccountUserMembership.account_id == Site.account_id,
                    AccountUserMembership.principal_id == principal_id,
                ),
            )
            .outerjoin(
                Principal,
                Principal.principal_id == AccountUserMembership.principal_id,
            )
            .where(Site.site_id == site_id)
        ).first()
        if row is None:
            return None
        return row[0], row[1], row[2], row[3]

    def get_platform_admin_grant(
        self,
        *,
        principal_id: str,
    ) -> PlatformAdminGrant | None:
        return self.session.scalar(
            select(PlatformAdminGrant).where(
                PlatformAdminGrant.principal_id == principal_id,
            )
        )

    def get_platform_admin_grant_by_subject(
        self,
        *,
        provider: str,
        external_subject: str,
    ) -> PlatformAdminGrant | None:
        return self.session.scalar(
            select(PlatformAdminGrant).where(
                PlatformAdminGrant.provider == provider,
                PlatformAdminGrant.external_subject == external_subject,
            )
        )

    def get_platform_admin_grant_by_email(
        self,
        *,
        provider: str,
        email: str,
    ) -> PlatformAdminGrant | None:
        return self.session.scalar(
            select(PlatformAdminGrant).where(
                PlatformAdminGrant.provider == provider,
                func.lower(PlatformAdminGrant.email) == email.lower(),
            )
        )

    def upsert_platform_admin_grant(
        self,
        *,
        grant_id: str,
        principal_id: str,
        provider: str,
        external_subject: str | None,
        email: str | None,
        role: str,
        status: str,
        metadata_json: dict[str, object] | None = None,
    ) -> PlatformAdminGrant:
        identity = self.get_platform_admin_grant(principal_id=principal_id)
        if identity is None:
            identity = PlatformAdminGrant(
                grant_id=grant_id,
                principal_id=principal_id,
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

    def list_platform_admin_grants(
        self,
        *,
        status: str | None = None,
        role: str | None = None,
        provider: str | None = None,
        limit: int | None = None,
    ) -> list[PlatformAdminGrant]:
        statement = select(PlatformAdminGrant)
        if status:
            statement = statement.where(PlatformAdminGrant.status == status)
        if role:
            statement = statement.where(PlatformAdminGrant.role == role)
        if provider:
            statement = statement.where(PlatformAdminGrant.provider == provider)
        statement = statement.order_by(
            PlatformAdminGrant.created_at.desc(),
            PlatformAdminGrant.principal_id.asc(),
        )
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def delete_platform_admin_grant(
        self,
        *,
        principal_id: str,
    ) -> bool:
        identity = self.get_platform_admin_grant(principal_id=principal_id)
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
        statuses: list[str] | None = None,
    ) -> dict[str, int]:
        statement = select(Site.account_id, func.count(Site.site_id)).group_by(Site.account_id)
        if account_ids is not None:
            if not account_ids:
                return {}
            statement = statement.where(Site.account_id.in_(account_ids))
        if status:
            statement = statement.where(Site.status == status)
        if statuses is not None:
            normalized_statuses = [str(item).strip() for item in statuses if str(item).strip()]
            if not normalized_statuses:
                return {}
            statement = statement.where(Site.status.in_(normalized_statuses))
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

    def get_plan_offer(self, offer_id: str) -> PlanOffer | None:
        return self.session.get(PlanOffer, offer_id)

    def list_plan_offers(
        self,
        *,
        account_id: str | None = None,
        status: str | None = None,
        self_serve_only: bool = False,
        now: datetime | None = None,
    ) -> list[PlanOffer]:
        statement = select(PlanOffer)
        if account_id:
            statement = statement.where(
                or_(PlanOffer.account_id.is_(None), PlanOffer.account_id == account_id)
            )
        else:
            statement = statement.where(PlanOffer.account_id.is_(None))
        if status:
            statement = statement.where(PlanOffer.status == status)
        if self_serve_only:
            statement = statement.where(PlanOffer.purchase_mode == "self_serve")
        if now is not None:
            statement = statement.where(
                or_(PlanOffer.valid_from_at.is_(None), PlanOffer.valid_from_at <= now),
                or_(PlanOffer.valid_until_at.is_(None), PlanOffer.valid_until_at > now),
            )
        statement = statement.order_by(PlanOffer.amount.asc(), PlanOffer.offer_id.asc())
        return list(self.session.scalars(statement))

    def upsert_plan_offer(
        self,
        *,
        offer_id: str,
        plan_id: str,
        plan_version_id: str,
        account_id: str | None,
        tier_id: str,
        billing_cycle: str,
        amount: Decimal,
        currency: str,
        purchase_mode: str,
        status: str,
        trial_enabled: bool,
        trial_days: int,
        trial_credit_limit: int,
        trial_requires_approval: bool,
        valid_from_at: datetime | None,
        valid_until_at: datetime | None,
        metadata_json: dict[str, object] | None,
    ) -> PlanOffer:
        offer = self.get_plan_offer(offer_id)
        values = {
            "plan_id": plan_id,
            "plan_version_id": plan_version_id,
            "account_id": account_id,
            "tier_id": tier_id,
            "billing_cycle": billing_cycle,
            "amount": amount,
            "currency": currency,
            "purchase_mode": purchase_mode,
            "status": status,
            "trial_enabled": trial_enabled,
            "trial_days": trial_days,
            "trial_credit_limit": trial_credit_limit,
            "trial_requires_approval": trial_requires_approval,
            "valid_from_at": valid_from_at,
            "valid_until_at": valid_until_at,
            "metadata_json": metadata_json,
        }
        if offer is None:
            offer = PlanOffer(offer_id=offer_id, **values)
            self.session.add(offer)
        else:
            for key, value in values.items():
                setattr(offer, key, value)
        self.session.flush()
        return offer

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

    def get_trial_claim(self, claim_id: str) -> TrialClaim | None:
        return self.session.get(TrialClaim, claim_id)

    def find_trial_claim(
        self,
        *,
        account_id: str | None = None,
        principal_id: str | None = None,
        site_domain: str | None = None,
    ) -> TrialClaim | None:
        filters: list[SQLAFilter] = []
        if account_id:
            filters.append(TrialClaim.account_id == account_id)
        if principal_id:
            filters.append(TrialClaim.principal_id == principal_id)
        if site_domain:
            filters.append(TrialClaim.site_domain == site_domain)
        if not filters:
            return None
        return self.session.scalar(select(TrialClaim).where(or_(*filters)))

    def create_trial_claim(
        self,
        *,
        claim_id: str,
        account_id: str,
        principal_id: str | None,
        site_domain: str | None,
        plan_id: str,
        plan_version_id: str,
        tier_id: str,
        highest_tier_id: str,
        status: str,
        credit_limit: int,
        started_at: datetime,
        ends_at: datetime,
        approved_by_principal_id: str | None,
        metadata_json: dict[str, object] | None,
    ) -> TrialClaim:
        claim = TrialClaim(
            claim_id=claim_id,
            account_id=account_id,
            principal_id=principal_id,
            site_domain=site_domain,
            plan_id=plan_id,
            plan_version_id=plan_version_id,
            tier_id=tier_id,
            highest_tier_id=highest_tier_id,
            status=status,
            credit_limit=credit_limit,
            started_at=started_at,
            ends_at=ends_at,
            approved_by_principal_id=approved_by_principal_id,
            metadata_json=metadata_json,
        )
        self.session.add(claim)
        self.session.flush()
        return claim

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

    def get_payment_order_for_update(self, order_id: str) -> PaymentOrder | None:
        return self.session.scalar(
            select(PaymentOrder).where(PaymentOrder.order_id == order_id).with_for_update()
        )

    def get_payment_order_by_idempotency_key(self, idempotency_key: str) -> PaymentOrder | None:
        if not idempotency_key:
            return None
        return self.session.scalar(
            select(PaymentOrder).where(PaymentOrder.idempotency_key == idempotency_key)
        )

    def get_payment_order_by_provider_external_order(
        self,
        *,
        provider: str,
        external_order_no: str,
    ) -> PaymentOrder | None:
        if not provider or not external_order_no:
            return None
        return self.session.scalar(
            select(PaymentOrder).where(
                PaymentOrder.provider == provider,
                PaymentOrder.external_order_no == external_order_no,
            )
        )

    def list_payment_orders(
        self,
        *,
        account_id: str,
        site_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[PaymentOrder]:
        statement = select(PaymentOrder).where(PaymentOrder.account_id == account_id)
        if site_id:
            statement = statement.where(PaymentOrder.site_id == site_id)
        statement = statement.order_by(PaymentOrder.created_at.desc(), PaymentOrder.order_id.desc())
        if offset > 0:
            statement = statement.offset(offset)
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def list_pending_payment_orders_before(
        self,
        *,
        cutoff: datetime,
        account_id: str | None = None,
        site_id: str | None = None,
    ) -> list[PaymentOrder]:
        statement = select(PaymentOrder).where(
            PaymentOrder.status == PAYMENT_ORDER_STATUS_PENDING,
            PaymentOrder.created_at <= cutoff,
        )
        if account_id:
            statement = statement.where(PaymentOrder.account_id == account_id)
        if site_id:
            statement = statement.where(PaymentOrder.site_id == site_id)
        return list(self.session.scalars(statement))

    def count_payment_orders(
        self,
        *,
        account_id: str,
        site_id: str | None = None,
    ) -> int:
        statement = select(func.count(PaymentOrder.order_id)).where(
            PaymentOrder.account_id == account_id
        )
        if site_id:
            statement = statement.where(PaymentOrder.site_id == site_id)
        return int(self.session.scalar(statement) or 0)

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

    def get_subscription_order(self, subscription_order_id: str) -> SubscriptionOrder | None:
        return self.session.get(SubscriptionOrder, subscription_order_id)

    def get_subscription_order_by_payment_order(
        self, payment_order_id: str
    ) -> SubscriptionOrder | None:
        if not payment_order_id:
            return None
        return self.session.scalar(
            select(SubscriptionOrder).where(SubscriptionOrder.payment_order_id == payment_order_id)
        )

    def list_subscription_orders(
        self,
        *,
        account_id: str,
        limit: int | None = None,
    ) -> list[SubscriptionOrder]:
        statement = (
            select(SubscriptionOrder)
            .where(SubscriptionOrder.account_id == account_id)
            .order_by(
                SubscriptionOrder.created_at.desc(),
                SubscriptionOrder.subscription_order_id.desc(),
            )
        )
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def create_subscription_order(
        self,
        *,
        subscription_order_id: str,
        account_id: str,
        offer_id: str,
        payment_order_id: str | None,
        source_subscription_id: str | None,
        target_plan_id: str,
        target_plan_version_id: str,
        order_kind: str,
        status: str,
        list_amount: Decimal,
        credit_amount: Decimal,
        payable_amount: Decimal,
        currency: str,
        effective_at: datetime | None,
        period_start_at: datetime | None,
        period_end_at: datetime | None,
        metadata_json: dict[str, object] | None,
    ) -> SubscriptionOrder:
        order = SubscriptionOrder(
            subscription_order_id=subscription_order_id,
            account_id=account_id,
            offer_id=offer_id,
            payment_order_id=payment_order_id,
            source_subscription_id=source_subscription_id,
            target_plan_id=target_plan_id,
            target_plan_version_id=target_plan_version_id,
            order_kind=order_kind,
            status=status,
            list_amount=list_amount,
            credit_amount=credit_amount,
            payable_amount=payable_amount,
            currency=currency,
            effective_at=effective_at,
            period_start_at=period_start_at,
            period_end_at=period_end_at,
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
            items.setdefault(str(site_id or ""), {"documents": 0, "chunks": 0})["documents"] = int(
                count or 0
            )
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
            select(CreditLedgerEntry).where(CreditLedgerEntry.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing

        normalized_credit_delta = round(float(credit_delta or 0.0), 6)
        if (
            event_type == CREDIT_LEDGER_EVENT_CONSUME
            and not float(normalized_credit_delta).is_integer()
        ):
            raise ValueError("consume credit_delta must be an integer credit unit")
        if event_type == CREDIT_LEDGER_EVENT_CONSUME:
            normalized_credit_delta = float(int(normalized_credit_delta))

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
            credit_delta=normalized_credit_delta,
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
        source_types: list[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
        offset: int | None = None,
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
        if source_types is not None:
            if not source_types:
                return []
            statement = statement.where(CreditLedgerEntry.source_type.in_(source_types))
        if since is not None:
            statement = statement.where(CreditLedgerEntry.created_at >= since)
        if until is not None:
            statement = statement.where(CreditLedgerEntry.created_at <= until)
        statement = statement.order_by(
            CreditLedgerEntry.created_at.desc(),
            CreditLedgerEntry.ledger_entry_id.desc(),
        )
        if offset is not None and offset > 0:
            statement = statement.offset(offset)
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def count_credit_ledger_entries(
        self,
        *,
        account_ids: list[str] | None = None,
        site_ids: list[str] | None = None,
        subscription_id: str | None = None,
        event_types: list[str] | None = None,
        source_types: list[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> int:
        statement = select(func.count(CreditLedgerEntry.ledger_entry_id))
        if account_ids is not None:
            if not account_ids:
                return 0
            statement = statement.where(CreditLedgerEntry.account_id.in_(account_ids))
        if site_ids is not None:
            if not site_ids:
                return 0
            statement = statement.where(CreditLedgerEntry.site_id.in_(site_ids))
        if subscription_id is not None:
            statement = statement.where(CreditLedgerEntry.subscription_id == subscription_id)
        if event_types is not None:
            if not event_types:
                return 0
            statement = statement.where(CreditLedgerEntry.event_type.in_(event_types))
        if source_types is not None:
            if not source_types:
                return 0
            statement = statement.where(CreditLedgerEntry.source_type.in_(source_types))
        if since is not None:
            statement = statement.where(CreditLedgerEntry.created_at >= since)
        if until is not None:
            statement = statement.where(CreditLedgerEntry.created_at <= until)
        return int(self.session.scalar(statement) or 0)

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

    def list_run_records_by_ids(self, run_ids: list[str]) -> list[RunRecord]:
        normalized_ids = [str(run_id or "").strip() for run_id in run_ids]
        normalized_ids = [run_id for run_id in normalized_ids if run_id]
        if not normalized_ids:
            return []
        statement = select(RunRecord).where(RunRecord.run_id.in_(normalized_ids))
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
        site_ids: list[str] | None = None,
        account_id: str | None = None,
        event_kind: str | None = None,
        outcome: str | None = None,
        limit: int = 50,
    ) -> list[ServiceAuditEvent]:
        statement = select(ServiceAuditEvent).where(
            *self._service_audit_filters(
                site_id=site_id,
                site_ids=site_ids,
                account_id=account_id,
                event_kind=event_kind,
                outcome=outcome,
            )
        )
        statement = statement.order_by(
            ServiceAuditEvent.created_at.desc(),
            ServiceAuditEvent.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def list_service_audit_events_for_principal(
        self,
        *,
        principal_id: str,
        limit: int = 50,
    ) -> list[ServiceAuditEvent]:
        normalized_principal_id = str(principal_id or "").strip()
        if not normalized_principal_id:
            return []
        statement = (
            select(ServiceAuditEvent)
            .where(
                or_(
                    ServiceAuditEvent.scope_id == normalized_principal_id,
                    ServiceAuditEvent.scope_id.like(f"%:{normalized_principal_id}"),
                )
            )
            .order_by(ServiceAuditEvent.created_at.desc(), ServiceAuditEvent.id.desc())
            .limit(max(1, limit))
        )
        return list(self.session.scalars(statement))

    def count_service_audit_events(
        self,
        *,
        site_id: str | None = None,
        site_ids: list[str] | None = None,
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
                            site_ids=site_ids,
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
        site_ids: list[str] | None = None,
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
                    site_ids=site_ids,
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
        site_ids: list[str] | None = None,
        account_id: str | None = None,
        event_kind: str | None = None,
        outcome: str | None = None,
        since: datetime | None = None,
    ) -> list[SQLAFilter]:
        filters: list[SQLAFilter] = []
        normalized_site_ids = (
            sorted({str(item).strip() for item in site_ids if str(item).strip()})
            if site_ids is not None
            else None
        )
        if site_id:
            filters.append(ServiceAuditEvent.site_id == site_id)
        elif account_id and normalized_site_ids is not None:
            if normalized_site_ids:
                filters.append(
                    or_(
                        ServiceAuditEvent.account_id == account_id,
                        ServiceAuditEvent.site_id.in_(normalized_site_ids),
                    )
                )
            else:
                filters.append(ServiceAuditEvent.account_id == account_id)
        elif normalized_site_ids is not None:
            if normalized_site_ids:
                filters.append(ServiceAuditEvent.site_id.in_(normalized_site_ids))
            else:
                filters.append(ServiceAuditEvent.id == -1)
        elif account_id:
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
