from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


SITE_STATUS_PROVISIONING = "provisioning"
SITE_STATUS_ACTIVE = "active"
SITE_STATUS_INACTIVE = "inactive"
SITE_STATUS_SUSPENDED = "suspended"
SITE_STATUS_ARCHIVED = "archived"
PLATFORM_KIND_WORDPRESS = "wordpress"

SITE_API_KEY_STATUS_ACTIVE = "active"
SITE_API_KEY_STATUS_REVOKED = "revoked"
SITE_API_KEY_STATUS_EXPIRED = "expired"

ACCOUNT_STATUS_ACTIVE = "active"
ACCOUNT_STATUS_SUSPENDED = "suspended"

PORTAL_LOGIN_CODE_STATUS_PENDING = "pending"
PORTAL_LOGIN_CODE_STATUS_CONSUMED = "consumed"
PORTAL_LOGIN_CODE_STATUS_EXPIRED = "expired"
PORTAL_LOGIN_CODE_STATUS_LOCKED = "locked"
IDENTITY_PROVIDER_BINDING_STATUS_ACTIVE = "active"
IDENTITY_PROVIDER_BINDING_STATUS_REVOKED = "revoked"
PORTAL_OAUTH_STATE_STATUS_PENDING = "pending"
PORTAL_OAUTH_STATE_STATUS_CONSUMED = "consumed"
PORTAL_OAUTH_STATE_STATUS_EXPIRED = "expired"

PRINCIPAL_STATUS_ACTIVE = "active"
PRINCIPAL_STATUS_DISABLED = "disabled"
PORTAL_IDEMPOTENCY_STATE_PROCESSING = "processing"
PORTAL_IDEMPOTENCY_STATE_COMPLETED = "completed"
ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE = "active"
ACCOUNT_USER_MEMBERSHIP_STATUS_REVOKED = "revoked"

SUPPORT_REQUEST_STATUS_OPEN = "open"
SUPPORT_REQUEST_STATUS_IN_PROGRESS = "in_progress"
SUPPORT_REQUEST_STATUS_RESOLVED = "resolved"
SUPPORT_REQUEST_STATUS_CLOSED = "closed"
SUPPORT_REQUEST_MESSAGE_AUTHOR_CUSTOMER = "customer"
SUPPORT_REQUEST_MESSAGE_AUTHOR_OPERATOR = "operator"
SUPPORT_REQUEST_MESSAGE_AUTHOR_SYSTEM = "system"
SUPPORT_REQUEST_MESSAGE_VISIBILITY_PUBLIC = "public"
SUPPORT_REQUEST_MESSAGE_VISIBILITY_INTERNAL = "internal"
SUPPORT_REQUEST_ATTACHMENT_UPLOADER_CUSTOMER = "customer"
SUPPORT_REQUEST_ATTACHMENT_UPLOADER_OPERATOR = "operator"

PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN = "platform_admin"

PLATFORM_ADMIN_STATUS_ACTIVE = "active"
PLATFORM_ADMIN_STATUS_DISABLED = "disabled"

PLAN_STATUS_DRAFT = "draft"
PLAN_STATUS_ACTIVE = "active"
PLAN_STATUS_ARCHIVED = "archived"

PLAN_VERSION_STATUS_DRAFT = "draft"
PLAN_VERSION_STATUS_PUBLISHED = "published"
PLAN_VERSION_STATUS_ARCHIVED = "archived"

PLAN_OFFER_STATUS_DRAFT = "draft"
PLAN_OFFER_STATUS_ACTIVE = "active"
PLAN_OFFER_STATUS_RETIRED = "retired"
PLAN_OFFER_PURCHASE_MODE_SELF_SERVE = "self_serve"
PLAN_OFFER_PURCHASE_MODE_QUOTE = "quote"

SUBSCRIPTION_ORDER_STATUS_PENDING_PAYMENT = "pending_payment"
SUBSCRIPTION_ORDER_STATUS_PAID = "paid"
SUBSCRIPTION_ORDER_STATUS_ACTIVATED = "activated"
SUBSCRIPTION_ORDER_STATUS_CANCELED = "canceled"
SUBSCRIPTION_ORDER_STATUS_REFUNDED = "refunded"
SUBSCRIPTION_ORDER_KIND_PURCHASE = "purchase"
SUBSCRIPTION_ORDER_KIND_UPGRADE = "upgrade"
SUBSCRIPTION_ORDER_KIND_RENEWAL = "renewal"
SUBSCRIPTION_ORDER_KIND_DOWNGRADE = "downgrade"

TRIAL_CLAIM_STATUS_ACTIVE = "active"
TRIAL_CLAIM_STATUS_EXPIRED = "expired"
TRIAL_CLAIM_STATUS_CONVERTED = "converted"

SUBSCRIPTION_STATUS_TRIALING = "trialing"
SUBSCRIPTION_STATUS_SCHEDULED = "scheduled"
SUBSCRIPTION_STATUS_ACTIVE = "active"
SUBSCRIPTION_STATUS_PAST_DUE = "past_due"
SUBSCRIPTION_STATUS_SUSPENDED = "suspended"
SUBSCRIPTION_STATUS_CANCELED = "canceled"

ENTITLEMENT_SNAPSHOT_STATUS_ACTIVE = "active"
ENTITLEMENT_SNAPSHOT_STATUS_SUPERSEDED = "superseded"

PAYMENT_ORDER_STATUS_PENDING = "pending"
PAYMENT_ORDER_STATUS_PAID = "paid"
PAYMENT_ORDER_STATUS_CANCELED = "canceled"
PAYMENT_ORDER_STATUS_REFUNDED = "refunded"

PAYMENT_REFUND_STATUS_REQUESTED = "requested"
PAYMENT_REFUND_STATUS_SUCCEEDED = "succeeded"
PAYMENT_REFUND_STATUS_FAILED = "failed"

PAYMENT_EVENT_STATUS_RECEIVED = "received"
PAYMENT_EVENT_STATUS_PROCESSED = "processed"

CREDIT_LEDGER_EVENT_CONSUME = "consume"
CREDIT_LEDGER_EVENT_GRANT = "grant"
CREDIT_LEDGER_EVENT_ADJUSTMENT = "adjustment"
CREDIT_LEDGER_EVENT_REFUND = "refund"

RUN_CALLBACK_STATUS_NOT_REQUESTED = "not_requested"
RUN_CALLBACK_STATUS_PENDING = "pending"
RUN_CALLBACK_STATUS_DISPATCHING = "dispatching"
RUN_CALLBACK_STATUS_DELIVERED = "delivered"
RUN_CALLBACK_STATUS_FAILED = "failed"


class Account(Base):
    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    name: Mapped[str] = mapped_column(String(191))
    status: Mapped[str] = mapped_column(
        String(32),
        default=ACCOUNT_STATUS_ACTIVE,
        index=True,
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class PortalLoginCode(Base):
    __tablename__ = "portal_login_codes"

    code_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    email: Mapped[str] = mapped_column(String(191), index=True)
    principal_id: Mapped[str] = mapped_column(String(191), index=True)
    code_hash: Mapped[str] = mapped_column(String(191))
    status: Mapped[str] = mapped_column(
        String(32),
        default=PORTAL_LOGIN_CODE_STATUS_PENDING,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class PlatformAdminGrant(Base):
    __tablename__ = "platform_admin_grants"
    __table_args__ = (
        UniqueConstraint("principal_id", name="uq_platform_admin_grants_principal_id"),
    )

    grant_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    principal_id: Mapped[str] = mapped_column(ForeignKey("principals.principal_id"), index=True)
    provider: Mapped[str] = mapped_column(String(64), default="manual", index=True)
    external_subject: Mapped[str | None] = mapped_column(String(191), index=True)
    email: Mapped[str | None] = mapped_column(String(191), index=True)
    role: Mapped[str] = mapped_column(
        String(64),
        default=PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default=PLATFORM_ADMIN_STATUS_ACTIVE,
        index=True,
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class Plan(Base):
    __tablename__ = "plans"

    plan_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    name: Mapped[str] = mapped_column(String(191))
    status: Mapped[str] = mapped_column(
        String(32),
        default=PLAN_STATUS_ACTIVE,
        index=True,
    )
    description: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class PlanVersion(Base):
    __tablename__ = "plan_versions"
    __table_args__ = (
        UniqueConstraint("plan_id", "version_label", name="uq_plan_versions_plan_label"),
    )

    plan_version_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.plan_id"), index=True)
    version_label: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(32),
        default=PLAN_VERSION_STATUS_PUBLISHED,
        index=True,
    )
    currency: Mapped[str] = mapped_column(String(16), default="CNY")
    entitlements_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    budgets_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    concurrency_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class PlanOffer(Base):
    __tablename__ = "plan_offers"

    offer_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.plan_id"), index=True)
    plan_version_id: Mapped[str] = mapped_column(
        ForeignKey("plan_versions.plan_version_id"), index=True
    )
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    tier_id: Mapped[str] = mapped_column(String(32), index=True)
    billing_cycle: Mapped[str] = mapped_column(String(32), default="monthly")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(16), default="CNY")
    purchase_mode: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    trial_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    trial_days: Mapped[int] = mapped_column(Integer, default=0)
    trial_credit_limit: Mapped[int] = mapped_column(Integer, default=0)
    trial_requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    valid_from_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SubscriptionOrder(Base):
    __tablename__ = "subscription_orders"

    subscription_order_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    offer_id: Mapped[str] = mapped_column(ForeignKey("plan_offers.offer_id"), index=True)
    payment_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("payment_orders.order_id"), unique=True, index=True
    )
    source_subscription_id: Mapped[str | None] = mapped_column(String(191), index=True)
    target_plan_id: Mapped[str] = mapped_column(String(191), index=True)
    target_plan_version_id: Mapped[str] = mapped_column(String(191), index=True)
    order_kind: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    list_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    credit_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    payable_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(16), default="CNY")
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TrialClaim(Base):
    __tablename__ = "trial_claims"
    __table_args__ = (
        UniqueConstraint("account_id", name="uq_trial_claims_account"),
        UniqueConstraint("principal_id", name="uq_trial_claims_principal"),
        UniqueConstraint("site_domain", name="uq_trial_claims_site_domain"),
    )

    claim_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    principal_id: Mapped[str | None] = mapped_column(
        ForeignKey("principals.principal_id"), nullable=True, index=True
    )
    site_domain: Mapped[str | None] = mapped_column(String(255), index=True)
    plan_id: Mapped[str] = mapped_column(String(191), index=True)
    plan_version_id: Mapped[str] = mapped_column(String(191), index=True)
    tier_id: Mapped[str] = mapped_column(String(32), index=True)
    highest_tier_id: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), index=True)
    credit_limit: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    approved_by_principal_id: Mapped[str | None] = mapped_column(String(191))
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Site(Base):
    __tablename__ = "sites"

    site_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    account_id: Mapped[str | None] = mapped_column(String(191), index=True)
    name: Mapped[str] = mapped_column(String(191))
    status: Mapped[str] = mapped_column(
        String(32),
        default=SITE_STATUS_ACTIVE,
        index=True,
    )
    site_url: Mapped[str] = mapped_column(String(2048), default="", server_default="")
    platform_kind: Mapped[str] = mapped_column(
        String(32),
        default=PLATFORM_KIND_WORDPRESS,
        server_default=PLATFORM_KIND_WORDPRESS,
        index=True,
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    provisioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspension_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class Principal(Base):
    __tablename__ = "principals"
    __table_args__ = (UniqueConstraint("email", name="uq_principals_email"),)

    principal_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(191), index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default=PRINCIPAL_STATUS_ACTIVE,
        index=True,
    )
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class PortalMutationIdempotencyReceipt(Base):
    __tablename__ = "portal_mutation_idempotency_receipts"
    __table_args__ = (
        UniqueConstraint(
            "principal_id",
            "idempotency_key",
            name="uq_portal_mutation_idempotency_principal_key",
        ),
        CheckConstraint(
            "state IN ('processing', 'completed')",
            name="ck_portal_mutation_idempotency_state",
        ),
        CheckConstraint(
            "retention_ttl_seconds > 0",
            name="ck_portal_mutation_idempotency_ttl_positive",
        ),
        CheckConstraint(
            "response_status IS NULL OR "
            "(response_status >= 100 AND response_status <= 599)",
            name="ck_portal_mutation_idempotency_response_status",
        ),
        CheckConstraint(
            "((state = 'processing' AND claim_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND response_status IS NULL "
            "AND response_body_ciphertext IS NULL AND completed_at IS NULL) OR "
            "(state = 'completed' AND claim_token IS NULL "
            "AND lease_expires_at IS NULL AND response_status IS NOT NULL "
            "AND response_body_ciphertext IS NOT NULL AND completed_at IS NOT NULL))",
            name="ck_portal_mutation_idempotency_lifecycle",
        ),
        Index(
            "ix_portal_mutation_idempotency_expiry",
            "expires_at",
            "receipt_id",
        ),
        Index(
            "ix_portal_mutation_idempotency_processing_lease",
            "state",
            "lease_expires_at",
        ),
    )

    receipt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    principal_id: Mapped[str] = mapped_column(
        ForeignKey("principals.principal_id"),
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_method: Mapped[str] = mapped_column(String(16))
    request_path: Mapped[str] = mapped_column(String(512))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    claim_token: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body_ciphertext: Mapped[str | None] = mapped_column(Text)
    retention_ttl_seconds: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class AccountUserMembership(Base):
    __tablename__ = "account_user_memberships"
    __table_args__ = (
        UniqueConstraint(
            "principal_id",
            "account_id",
            name="uq_account_user_memberships_principal_account",
        ),
        CheckConstraint("role IN ('user')", name="ck_account_user_memberships_role"),
        Index(
            "ix_account_user_memberships_principal_status_account",
            "principal_id",
            "status",
            "account_id",
        ),
    )

    membership_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    principal_id: Mapped[str] = mapped_column(
        ForeignKey("principals.principal_id"),
        index=True,
    )
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    role: Mapped[str] = mapped_column(String(64), default="user", index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default=ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE,
        index=True,
    )
    allowed_actions_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class SupportRequest(Base):
    __tablename__ = "support_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'in_progress', 'resolved', 'closed')",
            name="ck_support_requests_status",
        ),
    )

    request_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.site_id"), index=True)
    principal_id: Mapped[str | None] = mapped_column(
        ForeignKey("principals.principal_id"),
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), default="", index=True)
    topic: Mapped[str] = mapped_column(String(64), default="general", index=True)
    title: Mapped[str] = mapped_column(String(191))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default=SUPPORT_REQUEST_STATUS_OPEN, index=True)
    priority: Mapped[str] = mapped_column(String(32), default="normal", index=True)
    source_path: Mapped[str] = mapped_column(String(191), default="")
    admin_note: Mapped[str | None] = mapped_column(Text)
    context_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )


class SupportRequestMessage(Base):
    __tablename__ = "support_request_messages"
    __table_args__ = (
        CheckConstraint(
            "author_kind IN ('customer', 'operator', 'system')",
            name="ck_support_request_messages_author_kind",
        ),
        CheckConstraint(
            "visibility IN ('public', 'internal')",
            name="ck_support_request_messages_visibility",
        ),
    )

    message_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    request_id: Mapped[str] = mapped_column(
        ForeignKey("support_requests.request_id"),
        index=True,
    )
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.site_id"), index=True)
    principal_id: Mapped[str | None] = mapped_column(
        ForeignKey("principals.principal_id"),
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), default="", index=True)
    author_kind: Mapped[str] = mapped_column(String(32), index=True)
    visibility: Mapped[str] = mapped_column(String(32), index=True)
    body: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )


class SupportRequestAttachment(Base):
    __tablename__ = "support_request_attachments"
    __table_args__ = (
        CheckConstraint(
            "uploader_kind IN ('customer', 'operator')",
            name="ck_support_request_attachments_uploader_kind",
        ),
        CheckConstraint(
            "visibility IN ('public', 'internal')",
            name="ck_support_request_attachments_visibility",
        ),
    )

    attachment_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    request_id: Mapped[str] = mapped_column(
        ForeignKey("support_requests.request_id"),
        index=True,
    )
    message_id: Mapped[str | None] = mapped_column(
        ForeignKey("support_request_messages.message_id"),
        index=True,
    )
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.site_id"), index=True)
    principal_id: Mapped[str | None] = mapped_column(
        ForeignKey("principals.principal_id"),
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), default="", index=True)
    uploader_kind: Mapped[str] = mapped_column(String(32), index=True)
    visibility: Mapped[str] = mapped_column(String(32), index=True)
    filename: Mapped[str] = mapped_column(String(191))
    content_type: Mapped[str] = mapped_column(String(128), default="")
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    content_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )


class SupportRequestFeedback(Base):
    __tablename__ = "support_request_feedback"

    feedback_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    request_id: Mapped[str] = mapped_column(
        ForeignKey("support_requests.request_id"),
        unique=True,
        index=True,
    )
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.site_id"), index=True)
    principal_id: Mapped[str] = mapped_column(ForeignKey("principals.principal_id"), index=True)
    email: Mapped[str] = mapped_column(String(255), default="", index=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    rating: Mapped[int] = mapped_column(Integer, default=5, index=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )


class IdentityProviderBinding(Base):
    __tablename__ = "identity_provider_bindings"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "external_subject_hash",
            name="uq_identity_provider_bindings_provider_subject",
        ),
    )

    binding_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    principal_id: Mapped[str] = mapped_column(
        ForeignKey("principals.principal_id"),
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), index=True)
    external_subject_hash: Mapped[str] = mapped_column(String(191), index=True)
    unionid_hash: Mapped[str | None] = mapped_column(String(191), index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default=IDENTITY_PROVIDER_BINDING_STATUS_ACTIVE,
        index=True,
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class PortalOAuthState(Base):
    __tablename__ = "portal_oauth_states"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "state_hash",
            name="uq_portal_oauth_states_provider_state",
        ),
    )

    state_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    state_hash: Mapped[str] = mapped_column(String(191), index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default=PORTAL_OAUTH_STATE_STATUS_PENDING,
        index=True,
    )
    return_to: Mapped[str | None] = mapped_column(String(255))
    client_scope_id: Mapped[str | None] = mapped_column(String(191), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class SiteApiKey(Base):
    __tablename__ = "site_api_keys"

    key_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.site_id"), index=True)
    secret_hash: Mapped[str] = mapped_column(String(191))
    signing_secret_ciphertext: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(String(191))
    scopes_json: Mapped[list[str] | None] = mapped_column(JSON)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(
        String(32),
        default=SITE_API_KEY_STATUS_ACTIVE,
        index=True,
    )
    rotated_from_key_id: Mapped[str | None] = mapped_column(String(191))
    replaced_by_key_id: Mapped[str | None] = mapped_column(String(191))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class SiteKnowledgeDocument(Base):
    __tablename__ = "site_knowledge_documents"
    __table_args__ = (
        UniqueConstraint(
            "site_id",
            "source_type",
            "source_id",
            name="uq_site_knowledge_documents_site_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.site_id"), index=True)
    post_id: Mapped[int] = mapped_column(Integer, index=True)
    source_type: Mapped[str] = mapped_column(String(32), default="post", index=True)
    source_id: Mapped[int] = mapped_column(Integer, index=True)
    parent_post_id: Mapped[int | None] = mapped_column(Integer, index=True)
    post_type: Mapped[str] = mapped_column(String(64), index=True)
    post_status: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    modified_gmt: Mapped[str | None] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(128), index=True)
    last_sync_run_id: Mapped[str | None] = mapped_column(String(191), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    last_indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class SiteKnowledgeChunk(Base):
    __tablename__ = "site_knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "site_id",
            "source_type",
            "source_id",
            "chunk_index",
            name="uq_site_knowledge_chunks_site_source_chunk",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.site_id"), index=True)
    post_id: Mapped[int] = mapped_column(Integer, index=True)
    source_type: Mapped[str] = mapped_column(String(32), default="post", index=True)
    source_id: Mapped[int] = mapped_column(Integer, index=True)
    parent_post_id: Mapped[int | None] = mapped_column(Integer, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    post_type: Mapped[str] = mapped_column(String(64), index=True)
    post_status: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    chunk_text: Mapped[str] = mapped_column(Text)
    embedding_json: Mapped[list[float]] = mapped_column(JSON)
    embedding_model: Mapped[str] = mapped_column(String(191))
    content_hash: Mapped[str] = mapped_column(String(128), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )


class SiteKnowledgeIndexJobMetric(Base):
    __tablename__ = "site_knowledge_index_job_metrics"
    __table_args__ = (UniqueConstraint("run_id", name="uq_site_knowledge_index_job_metrics_run"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run_records.run_id"), index=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.site_id"), index=True)
    account_id: Mapped[str | None] = mapped_column(String(191), index=True)
    subscription_id: Mapped[str | None] = mapped_column(String(191), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    error_code: Mapped[str | None] = mapped_column(String(128), index=True)
    sync_mode: Mapped[str] = mapped_column(String(32), index=True)
    accepted_documents: Mapped[int] = mapped_column(Integer, default=0)
    indexed_documents: Mapped[int] = mapped_column(Integer, default=0)
    indexed_chunks: Mapped[int] = mapped_column(Integer, default=0)
    failed_documents: Mapped[int] = mapped_column(Integer, default=0)
    deleted_entries: Mapped[int] = mapped_column(Integer, default=0)
    embedding_provider: Mapped[str] = mapped_column(String(64), index=True)
    embedding_model: Mapped[str] = mapped_column(String(191), index=True)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, default=0)
    vector_backend: Mapped[str] = mapped_column(String(64), index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class SiteKnowledgeSearchMetric(Base):
    __tablename__ = "site_knowledge_search_metrics"
    __table_args__ = (UniqueConstraint("run_id", name="uq_site_knowledge_search_metrics_run"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run_records.run_id"), index=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.site_id"), index=True)
    account_id: Mapped[str | None] = mapped_column(String(191), index=True)
    subscription_id: Mapped[str | None] = mapped_column(String(191), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    error_code: Mapped[str | None] = mapped_column(String(128), index=True)
    intent: Mapped[str] = mapped_column(String(64), index=True)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    no_hit: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    top1_score: Mapped[float] = mapped_column(Float, default=0.0)
    avg_score: Mapped[float] = mapped_column(Float, default=0.0)
    query_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    query_chars: Mapped[int] = mapped_column(Integer, default=0)
    max_results: Mapped[int] = mapped_column(Integer, default=0)
    filter_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    embedding_provider: Mapped[str] = mapped_column(String(64), index=True)
    embedding_model: Mapped[str] = mapped_column(String(191), index=True)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, default=0)
    vector_backend: Mapped[str] = mapped_column(String(64), index=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class SiteKnowledgeIndexSnapshot(Base):
    __tablename__ = "site_knowledge_index_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.site_id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(191), index=True)
    document_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    post_type_counts_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    source_type_counts_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    embedding_provider: Mapped[str] = mapped_column(String(64), index=True)
    embedding_model: Mapped[str] = mapped_column(String(191), index=True)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, default=0)
    vector_backend: Mapped[str] = mapped_column(String(64), index=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )


class AccountSubscription(Base):
    __tablename__ = "account_subscriptions"

    subscription_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    plan_id: Mapped[str] = mapped_column(String(191), index=True)
    plan_version_id: Mapped[str] = mapped_column(String(191), index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default=SUBSCRIPTION_STATUS_ACTIVE,
        index=True,
    )
    current_period_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_plan_id: Mapped[str | None] = mapped_column(String(191), index=True)
    scheduled_plan_version_id: Mapped[str | None] = mapped_column(String(191))
    scheduled_change_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class AccountEntitlementSnapshot(Base):
    __tablename__ = "account_entitlement_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    subscription_id: Mapped[str] = mapped_column(String(191), index=True)
    plan_version_id: Mapped[str] = mapped_column(String(191), index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default=ENTITLEMENT_SNAPSHOT_STATUS_ACTIVE,
        index=True,
    )
    entitlements_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    budgets_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    concurrency_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    site_limit: Mapped[int] = mapped_column(Integer, default=1)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class PaymentOrder(Base):
    __tablename__ = "payment_orders"
    __table_args__ = (
        UniqueConstraint("provider", "external_order_no", name="uq_payment_orders_provider_ext"),
        UniqueConstraint("idempotency_key", name="uq_payment_orders_idempotency"),
    )

    order_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    site_id: Mapped[str | None] = mapped_column(String(191), index=True)
    subscription_id: Mapped[str | None] = mapped_column(String(191), index=True)
    plan_id: Mapped[str] = mapped_column(String(191), index=True)
    plan_version_id: Mapped[str] = mapped_column(String(191), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="alipay", index=True)
    external_order_no: Mapped[str] = mapped_column(String(191), index=True)
    provider_trade_no: Mapped[str | None] = mapped_column(String(191), index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default=PAYMENT_ORDER_STATUS_PENDING,
        index=True,
    )
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(16), default="CNY")
    subject: Mapped[str] = mapped_column(String(191))
    checkout_url: Mapped[str | None] = mapped_column(Text)
    refund_window_end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(191), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class PaymentRefund(Base):
    __tablename__ = "payment_refunds"
    __table_args__ = (
        UniqueConstraint("provider", "external_refund_no", name="uq_payment_refunds_provider_ext"),
        UniqueConstraint("idempotency_key", name="uq_payment_refunds_idempotency"),
    )

    refund_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("payment_orders.order_id"), index=True)
    account_id: Mapped[str] = mapped_column(String(191), index=True)
    subscription_id: Mapped[str | None] = mapped_column(String(191), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="alipay", index=True)
    external_refund_no: Mapped[str] = mapped_column(String(191), index=True)
    provider_refund_no: Mapped[str | None] = mapped_column(String(191), index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default=PAYMENT_REFUND_STATUS_REQUESTED,
        index=True,
    )
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(16), default="CNY")
    reason: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(191), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class PaymentEvent(Base):
    __tablename__ = "payment_events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_payment_events_provider_event"),
        UniqueConstraint("idempotency_key", name="uq_payment_events_idempotency"),
    )

    event_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), default="alipay", index=True)
    event_kind: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default=PAYMENT_EVENT_STATUS_RECEIVED,
        index=True,
    )
    order_id: Mapped[str | None] = mapped_column(String(191), index=True)
    refund_id: Mapped[str | None] = mapped_column(String(191), index=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(191), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(191), index=True)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )


class CatalogProvider(Base):
    __tablename__ = "catalog_providers"

    provider_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128))
    adapter_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="active")
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class CatalogRevision(Base):
    __tablename__ = "catalog_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    revision: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    provider_id: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(64), default="provider_refresh")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class CatalogModel(Base):
    __tablename__ = "catalog_models"

    model_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    provider_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_providers.provider_id"),
        index=True,
    )
    family: Mapped[str] = mapped_column(String(64))
    feature: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    context_window: Mapped[int | None] = mapped_column(Integer)
    price_input: Mapped[float | None] = mapped_column(Float)
    price_output: Mapped[float | None] = mapped_column(Float)
    is_deprecated: Mapped[bool] = mapped_column(Boolean, default=False)
    fallback_candidate: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[str] = mapped_column(String(64), index=True)
    raw_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class CatalogInstance(Base):
    __tablename__ = "catalog_instances"

    instance_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("catalog_models.model_id"), index=True)
    provider_id: Mapped[str] = mapped_column(String(64), index=True)
    endpoint_variant: Mapped[str] = mapped_column(String(64))
    region: Mapped[str] = mapped_column(String(64))
    capability_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    health_status: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    weight: Mapped[int] = mapped_column(Integer, default=100)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ModelReferenceSource(Base):
    __tablename__ = "model_reference_sources"

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128))
    source_url: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ModelReferenceModel(Base):
    __tablename__ = "model_reference_models"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "provider_id",
            "model_id",
            name="uq_model_reference_models_source_provider_model",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("model_reference_sources.source_id"),
        index=True,
    )
    provider_id: Mapped[str] = mapped_column(String(64), index=True)
    model_id: Mapped[str] = mapped_column(String(191), index=True)
    display_name: Mapped[str] = mapped_column(String(191), default="")
    family: Mapped[str] = mapped_column(String(96), default="")
    feature: Mapped[str] = mapped_column(String(32), default="text", index=True)
    modalities_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    capability_flags_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    context_window: Mapped[int | None] = mapped_column(Integer)
    output_limit: Mapped[int | None] = mapped_column(Integer)
    price_input: Mapped[float | None] = mapped_column(Float)
    price_output: Mapped[float | None] = mapped_column(Float)
    price_cache_read: Mapped[float | None] = mapped_column(Float)
    price_cache_write: Mapped[float | None] = mapped_column(Float)
    price_unit: Mapped[str] = mapped_column(String(64), default="usd_per_1m_tokens")
    release_date: Mapped[str] = mapped_column(String(32), default="")
    source_updated_at: Mapped[str] = mapped_column(String(32), default="")
    is_deprecated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    raw_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ModelReferenceOverride(Base):
    __tablename__ = "model_reference_overrides"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "model_id",
            name="uq_model_reference_overrides_provider_model",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[str] = mapped_column(String(64), index=True)
    model_id: Mapped[str] = mapped_column(String(191), index=True)
    feature_override: Mapped[str | None] = mapped_column(String(32))
    status_override: Mapped[str | None] = mapped_column(String(32))
    price_input_override: Mapped[float | None] = mapped_column(Float)
    price_output_override: Mapped[float | None] = mapped_column(Float)
    price_cache_read_override: Mapped[float | None] = mapped_column(Float)
    price_cache_write_override: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class RoutingProfile(Base):
    __tablename__ = "routing_profiles"

    profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_kind: Mapped[str] = mapped_column(String(32))
    default_policy_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class RoutingBinding(Base):
    __tablename__ = "routing_bindings"

    profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    candidate_instance_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    selection_policy_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    revision: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ProviderConnection(Base):
    __tablename__ = "provider_connections"

    connection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_type: Mapped[str] = mapped_column(String(64), index=True)
    display_name: Mapped[str] = mapped_column(String(191))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    base_url: Mapped[str] = mapped_column(String(500), default="")
    config_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    secret_ciphertext: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="configured", index=True)
    source_role: Mapped[str] = mapped_column(
        String(32),
        default="execution_source",
        index=True,
    )
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ServiceSetting(Base):
    __tablename__ = "service_settings"

    setting_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    setting_kind: Mapped[str] = mapped_column(String(64), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    config_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    secret_ciphertext_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="missing_config", index=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class RunRecord(Base):
    __tablename__ = "run_records"
    __table_args__ = (
        UniqueConstraint("site_id", "idempotency_key", name="uq_run_records_site_idempotency"),
    )

    run_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.site_id"), index=True)
    account_id: Mapped[str | None] = mapped_column(String(191), index=True)
    subscription_id: Mapped[str | None] = mapped_column(String(191), index=True)
    plan_version_id: Mapped[str | None] = mapped_column(String(191), index=True)
    ability_name: Mapped[str] = mapped_column(String(191), index=True)
    ability_family: Mapped[str] = mapped_column(String(32), default="text", index=True)
    skill_id: Mapped[str | None] = mapped_column(String(191))
    workflow_id: Mapped[str | None] = mapped_column(String(191))
    contract_version: Mapped[str | None] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(64), index=True)
    execution_kind: Mapped[str] = mapped_column(String(32), index=True)
    execution_tier: Mapped[str] = mapped_column(String(32), default="cloud", index=True)
    execution_pattern: Mapped[str] = mapped_column(String(32), default="step_offload")
    data_classification: Mapped[str] = mapped_column(String(32), default="internal")
    profile_id: Mapped[str] = mapped_column(String(64), index=True)
    canonical_run_id: Mapped[str | None] = mapped_column(String(191), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(191), nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(191), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    execution_input_ciphertext: Mapped[str | None] = mapped_column(Text)
    policy_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    result_ref: Mapped[str | None] = mapped_column(String(64))
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    callback_status: Mapped[str] = mapped_column(
        String(32),
        default=RUN_CALLBACK_STATUS_NOT_REQUESTED,
        index=True,
    )
    callback_attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    callback_last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    callback_delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    callback_next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    callback_last_error_code: Mapped[str | None] = mapped_column(String(64))
    callback_last_error_message: Mapped[str | None] = mapped_column(Text)
    selected_provider_id: Mapped[str | None] = mapped_column(String(64))
    selected_model_id: Mapped[str | None] = mapped_column(String(191))
    selected_instance_id: Mapped[str | None] = mapped_column(String(191))
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderCallRecord(Base):
    __tablename__ = "provider_call_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run_records.run_id"), index=True)
    provider_id: Mapped[str] = mapped_column(String(64), index=True)
    model_id: Mapped[str] = mapped_column(String(191), index=True)
    instance_id: Mapped[str] = mapped_column(String(191), index=True)
    region: Mapped[str] = mapped_column(String(64))
    latency_ms: Mapped[int] = mapped_column(Integer)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class UsageMeterEvent(Base):
    __tablename__ = "usage_meter_events"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_usage_meter_events_dedupe"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str | None] = mapped_column(String(191), index=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.site_id"), index=True)
    subscription_id: Mapped[str | None] = mapped_column(String(191), index=True)
    plan_version_id: Mapped[str | None] = mapped_column(String(191), index=True)
    run_id: Mapped[str | None] = mapped_column(String(191), index=True)
    provider_call_id: Mapped[int | None] = mapped_column(Integer, index=True)
    event_kind: Mapped[str] = mapped_column(String(32), index=True)
    meter_key: Mapped[str] = mapped_column(String(64), index=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    ability_family: Mapped[str | None] = mapped_column(String(32), index=True)
    channel: Mapped[str | None] = mapped_column(String(64), index=True)
    execution_kind: Mapped[str | None] = mapped_column(String(32), index=True)
    execution_tier: Mapped[str | None] = mapped_column(String(32), index=True)
    data_classification: Mapped[str | None] = mapped_column(String(32), index=True)
    currency: Mapped[str | None] = mapped_column(String(16))
    dedupe_key: Mapped[str] = mapped_column(String(255))
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class CreditLedgerEntry(Base):
    __tablename__ = "credit_ledger_entries"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_credit_ledger_entries_idempotency"),
    )

    ledger_entry_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    account_id: Mapped[str | None] = mapped_column(String(191), index=True)
    site_id: Mapped[str | None] = mapped_column(String(191), index=True)
    subscription_id: Mapped[str | None] = mapped_column(String(191), index=True)
    plan_version_id: Mapped[str | None] = mapped_column(String(191), index=True)
    run_id: Mapped[str | None] = mapped_column(String(191), index=True)
    provider_call_id: Mapped[int | None] = mapped_column(Integer, index=True)
    event_type: Mapped[str] = mapped_column(
        String(32),
        default=CREDIT_LEDGER_EVENT_CONSUME,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[str] = mapped_column(String(191), index=True)
    credit_delta: Mapped[float] = mapped_column(Float, default=0.0)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[str] = mapped_column(String(32), default="credit")
    rate: Mapped[float] = mapped_column(Float, default=0.0)
    rate_unit: Mapped[str | None] = mapped_column(String(64))
    rate_version: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )


class PaidCreditGrant(Base):
    """Payment-order-backed expiring credits; not a general-purpose wallet."""

    __tablename__ = "paid_credit_grants"
    __table_args__ = (
        CheckConstraint(
            "original_credits >= 0 AND remaining_credits >= 0 AND refunded_credits >= 0",
            name="ck_paid_credit_grants_nonnegative",
        ),
        CheckConstraint(
            "remaining_credits + refunded_credits <= original_credits",
            name="ck_paid_credit_grants_balance",
        ),
    )

    grant_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    payment_order_id: Mapped[str] = mapped_column(
        ForeignKey("payment_orders.order_id"), unique=True, index=True
    )
    original_credits: Mapped[float] = mapped_column(Float)
    remaining_credits: Mapped[float] = mapped_column(Float)
    refunded_credits: Mapped[float] = mapped_column(Float, default=0.0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReplayReceipt(Base):
    __tablename__ = "replay_receipts"
    __table_args__ = (
        UniqueConstraint(
            "scope_kind",
            "scope_id",
            "replay_key",
            name="uq_replay_receipts_scope_marker",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_kind: Mapped[str] = mapped_column(String(32), index=True)
    scope_id: Mapped[str] = mapped_column(String(191), index=True)
    replay_key: Mapped[str] = mapped_column(String(191))
    method: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(String(255))
    trace_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RuntimeGuardEvent(Base):
    __tablename__ = "runtime_guard_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    auth_surface: Mapped[str] = mapped_column(String(32), index=True)
    scope_kind: Mapped[str] = mapped_column(String(32), index=True)
    scope_id: Mapped[str] = mapped_column(String(191), index=True)
    site_id: Mapped[str | None] = mapped_column(String(191), index=True)
    key_id: Mapped[str | None] = mapped_column(String(191), index=True)
    client_ref: Mapped[str | None] = mapped_column(String(191), index=True)
    event_code: Mapped[str] = mapped_column(String(64), index=True)
    status_code: Mapped[int] = mapped_column(Integer, index=True)
    method: Mapped[str | None] = mapped_column(String(16))
    path: Mapped[str | None] = mapped_column(String(255))
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )


class PluginObservabilityEvent(Base):
    __tablename__ = "plugin_observability_events"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_plugin_observability_events_dedupe"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dedupe_key: Mapped[str] = mapped_column(String(255))
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.site_id"), index=True)
    key_id: Mapped[str | None] = mapped_column(String(191), index=True)
    schema_version: Mapped[str] = mapped_column(String(32), default="")
    plugin_slug: Mapped[str] = mapped_column(String(64), index=True)
    plugin_version: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(32), default="local", index=True)
    event_kind: Mapped[str] = mapped_column(String(96), index=True)
    event_id: Mapped[str | None] = mapped_column(String(96), index=True)
    status: Mapped[str | None] = mapped_column(String(32), index=True)
    status_detail: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(128), index=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    ability_id: Mapped[str | None] = mapped_column(String(191), index=True)
    proposal_id: Mapped[str | None] = mapped_column(String(191), index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(191), index=True)
    adapter_request_id: Mapped[str | None] = mapped_column(String(191), index=True)
    method: Mapped[str | None] = mapped_column(String(16))
    route: Mapped[str | None] = mapped_column(String(255), index=True)
    status_code: Mapped[int | None] = mapped_column(Integer)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    emitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )


class PluginObservabilityAttentionState(Base):
    __tablename__ = "plugin_observability_attention_states"
    __table_args__ = (
        UniqueConstraint(
            "attention_key",
            name="uq_plugin_observability_attention_states_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attention_key: Mapped[str] = mapped_column(String(64), index=True)
    attention_code: Mapped[str] = mapped_column(String(128), index=True)
    site_id: Mapped[str | None] = mapped_column(String(191), index=True)
    plugin_slug: Mapped[str | None] = mapped_column(String(64), index=True)
    event_kind: Mapped[str | None] = mapped_column(String(96), index=True)
    error_code: Mapped[str | None] = mapped_column(String(128), index=True)
    workflow_status: Mapped[str] = mapped_column(
        String(32),
        default="acknowledged",
        index=True,
    )
    muted_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
    operator_note: Mapped[str | None] = mapped_column(Text)
    actor_ref: Mapped[str | None] = mapped_column(String(191), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )


class HealthSnapshot(Base):
    __tablename__ = "health_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[str] = mapped_column(String(64), index=True)
    instance_id: Mapped[str | None] = mapped_column(String(191), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class UsageRollup(Base):
    __tablename__ = "usage_rollups"

    rollup_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    site_scope: Mapped[str] = mapped_column(String(191), index=True)
    scope_kind: Mapped[str] = mapped_column(String(32), index=True)
    scope_id: Mapped[str] = mapped_column(String(191), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class SiteServiceProjection(Base):
    __tablename__ = "site_service_projections"

    projection_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    site_id: Mapped[str] = mapped_column(String(191), index=True)
    projection_kind: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    fresh_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_revision: Mapped[str] = mapped_column(String(64), default="")
    generation_ms: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class BillingSnapshot(Base):
    __tablename__ = "billing_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    account_id: Mapped[str | None] = mapped_column(String(191), index=True)
    site_id: Mapped[str | None] = mapped_column(String(191), index=True)
    subscription_id: Mapped[str | None] = mapped_column(String(191), index=True)
    plan_version_id: Mapped[str | None] = mapped_column(String(191), index=True)
    currency: Mapped[str] = mapped_column(String(16), default="CNY")
    period_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    period_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    totals_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    breakdown_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ServiceAuditEvent(Base):
    __tablename__ = "service_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str | None] = mapped_column(String(191), index=True)
    site_id: Mapped[str | None] = mapped_column(String(191), index=True)
    key_id: Mapped[str | None] = mapped_column(String(191), index=True)
    subscription_id: Mapped[str | None] = mapped_column(String(191), index=True)
    plan_id: Mapped[str | None] = mapped_column(String(191), index=True)
    plan_version_id: Mapped[str | None] = mapped_column(String(191), index=True)
    scope_kind: Mapped[str | None] = mapped_column(String(32), index=True)
    scope_id: Mapped[str | None] = mapped_column(String(191), index=True)
    event_kind: Mapped[str] = mapped_column(String(64), index=True)
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    method: Mapped[str | None] = mapped_column(String(16))
    path: Mapped[str | None] = mapped_column(String(255))
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(191))
    actor_kind: Mapped[str] = mapped_column(String(32), default="internal_token")
    actor_ref: Mapped[str | None] = mapped_column(String(191))
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )


class CommercialDecisionEvent(Base):
    __tablename__ = "commercial_decision_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str | None] = mapped_column(String(191), index=True)
    site_id: Mapped[str | None] = mapped_column(String(191), index=True)
    subscription_id: Mapped[str | None] = mapped_column(String(191), index=True)
    plan_version_id: Mapped[str | None] = mapped_column(String(191), index=True)
    run_id: Mapped[str | None] = mapped_column(String(191), index=True)
    request_kind: Mapped[str] = mapped_column(String(32), index=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    decision_code: Mapped[str] = mapped_column(String(64), index=True)
    ability_family: Mapped[str | None] = mapped_column(String(32), index=True)
    channel: Mapped[str | None] = mapped_column(String(64), index=True)
    execution_kind: Mapped[str | None] = mapped_column(String(32), index=True)
    execution_tier: Mapped[str | None] = mapped_column(String(32), index=True)
    data_classification: Mapped[str | None] = mapped_column(String(32), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(191))
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )


class MediaArtifact(Base):
    __tablename__ = "media_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "storage_key",
            name="uq_media_artifacts_storage_key",
        ),
        CheckConstraint(
            "((purge_claim_id IS NULL AND purge_claim_expires_at IS NULL) OR "
            "(purge_claim_id IS NOT NULL AND purge_claim_expires_at IS NOT NULL))",
            name="ck_media_artifacts_purge_claim_pair",
        ),
    )

    artifact_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run_records.run_id"), index=True)
    site_id: Mapped[str] = mapped_column(String(191), index=True)
    media_kind: Mapped[str] = mapped_column(String(16), default="image")
    operation: Mapped[str] = mapped_column(String(64), default="image.transform.v1")
    content_type: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    storage_key: Mapped[str] = mapped_column(String(191))
    status: Mapped[str] = mapped_column(String(32), default="available", index=True)
    format: Mapped[str] = mapped_column(String(16))
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str] = mapped_column(String(128))
    processing_warnings_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    purge_last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    purge_last_error_code: Mapped[str | None] = mapped_column(String(64))
    purge_claim_id: Mapped[str | None] = mapped_column(String(64))
    purge_claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class MediaArtifactReconciliationPass(Base):
    __tablename__ = "media_artifact_reconciliation_passes"
    __table_args__ = (
        UniqueConstraint(
            "active_slot",
            name="uq_media_artifact_reconciliation_passes_active_slot",
        ),
        UniqueConstraint(
            "head_slot",
            name="uq_media_artifact_reconciliation_passes_head_slot",
        ),
        CheckConstraint(
            "state IN ('running', 'completed', 'abandoned')",
            name="ck_media_artifact_reconciliation_passes_state",
        ),
        CheckConstraint(
            "active_slot IS NULL OR active_slot = 'active'",
            name="ck_media_artifact_reconciliation_passes_active_slot_value",
        ),
        CheckConstraint(
            "head_slot IS NULL OR head_slot = 'head'",
            name="ck_media_artifact_reconciliation_passes_head_slot_value",
        ),
        CheckConstraint(
            "((scan_claim_id IS NULL AND lease_expires_at IS NULL) OR "
            "(scan_claim_id IS NOT NULL AND lease_expires_at IS NOT NULL))",
            name="ck_media_artifact_reconciliation_passes_claim_pair",
        ),
        CheckConstraint(
            "((state = 'running' AND active_slot = 'active' AND head_slot IS NULL "
            "AND scan_claim_id IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND completed_at IS NULL) OR "
            "(state = 'completed' AND active_slot IS NULL AND scan_claim_id IS NULL "
            "AND lease_expires_at IS NULL AND completed_at IS NOT NULL) OR "
            "(state = 'abandoned' AND active_slot IS NULL AND head_slot IS NULL "
            "AND scan_claim_id IS NULL AND lease_expires_at IS NULL "
            "AND completed_at IS NULL))",
            name="ck_media_artifact_reconciliation_passes_lifecycle",
        ),
        Index(
            "ix_media_artifact_recon_passes_previous_id",
            "previous_completed_pass_id",
        ),
    )

    pass_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), index=True)
    active_slot: Mapped[str | None] = mapped_column(String(16))
    head_slot: Mapped[str | None] = mapped_column(String(16))
    scan_claim_id: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    previous_completed_pass_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "media_artifact_reconciliation_passes.pass_id",
            name="fk_media_artifact_reconciliation_passes_previous",
        ),
    )
    store_generation: Mapped[str] = mapped_column(String(64), index=True)
    next_cursor: Mapped[str | None] = mapped_column(String(191))
    last_storage_key: Mapped[str | None] = mapped_column(String(191))
    store_examined: Mapped[int] = mapped_column(Integer, default=0)
    referenced_present: Mapped[int] = mapped_column(Integer, default=0)
    orphan_observed: Mapped[int] = mapped_column(Integer, default=0)
    orphan_deferred: Mapped[int] = mapped_column(Integer, default=0)
    orphan_eligible: Mapped[int] = mapped_column(Integer, default=0)
    db_available_examined: Mapped[int] = mapped_column(Integer, default=0)
    referenced_missing: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )


class MediaArtifactOrphanCandidate(Base):
    __tablename__ = "media_artifact_orphan_candidates"
    __table_args__ = (
        CheckConstraint(
            "state IN ('observed', 'eligible', 'claimed', 'retry_wait', "
            "'deleted', 'invalidated')",
            name="ck_media_artifact_orphan_candidates_state",
        ),
        CheckConstraint(
            "((claim_id IS NULL AND claim_expires_at IS NULL) OR "
            "(claim_id IS NOT NULL AND claim_expires_at IS NOT NULL))",
            name="ck_media_artifact_orphan_candidates_claim_pair",
        ),
        CheckConstraint(
            "((state = 'claimed' AND claim_id IS NOT NULL AND claim_expires_at IS NOT NULL) "
            "OR (state <> 'claimed' AND claim_id IS NULL AND claim_expires_at IS NULL))",
            name="ck_media_artifact_orphan_candidates_claim_state",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_media_artifact_orphan_candidates_attempt_count",
        ),
        CheckConstraint(
            "((state = 'retry_wait' AND retry_at IS NOT NULL "
            "AND last_error_code IS NOT NULL) OR "
            "(state <> 'retry_wait' AND retry_at IS NULL "
            "AND last_error_code IS NULL))",
            name="ck_media_artifact_orphan_candidates_retry_state",
        ),
        CheckConstraint(
            "((state IN ('deleted', 'invalidated') AND resolved_at IS NOT NULL) OR "
            "(state NOT IN ('deleted', 'invalidated') AND resolved_at IS NULL))",
            name="ck_media_artifact_orphan_candidates_resolution",
        ),
        Index(
            "ix_media_artifact_orphan_candidates_cleanup",
            "state",
            "retry_at",
            "claim_expires_at",
        ),
    )

    storage_key: Mapped[str] = mapped_column(String(191), primary_key=True)
    object_version: Mapped[str] = mapped_column(String(64))
    store_generation: Mapped[str] = mapped_column(String(64), index=True)
    first_pass_id: Mapped[str] = mapped_column(
        ForeignKey(
            "media_artifact_reconciliation_passes.pass_id",
            name="fk_media_artifact_orphan_candidates_first_pass",
        ),
        index=True,
    )
    last_pass_id: Mapped[str] = mapped_column(
        ForeignKey(
            "media_artifact_reconciliation_passes.pass_id",
            name="fk_media_artifact_orphan_candidates_last_pass",
        ),
        index=True,
    )
    state: Mapped[str] = mapped_column(String(16), index=True)
    claim_id: Mapped[str | None] = mapped_column(String(64))
    claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MediaArtifactDelivery(Base):
    __tablename__ = "media_artifact_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "site_id",
            "ack_idempotency_key",
            name="uq_media_artifact_deliveries_site_ack_key",
        ),
    )

    delivery_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("media_artifacts.artifact_id"), index=True
    )
    site_id: Mapped[str] = mapped_column(String(191), index=True)
    expected_byte_size: Mapped[int] = mapped_column(Integer)
    expected_checksum: Mapped[str] = mapped_column(String(128))
    pull_trace_id: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_byte_size: Mapped[int | None] = mapped_column(Integer)
    completed_checksum: Mapped[str | None] = mapped_column(String(128))
    ack_deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ack_idempotency_key: Mapped[str | None] = mapped_column(String(128))
    ack_request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    ack_trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    received_byte_size: Mapped[int | None] = mapped_column(Integer)
    received_checksum: Mapped[str | None] = mapped_column(String(128))
    byte_size_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    checksum_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    retention_expires_at_before: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    retention_expires_at_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class MediaDerivativeJobMetric(Base):
    __tablename__ = "media_derivative_job_metrics"
    __table_args__ = (UniqueConstraint("run_id", name="uq_media_derivative_job_metrics_run"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run_records.run_id"), index=True)
    site_id: Mapped[str] = mapped_column(String(191), index=True)
    account_id: Mapped[str | None] = mapped_column(String(191), index=True)
    subscription_id: Mapped[str | None] = mapped_column(String(191), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    error_code: Mapped[str | None] = mapped_column(String(128), index=True)
    target_format: Mapped[str] = mapped_column(String(16), index=True)
    output_format: Mapped[str | None] = mapped_column(String(16), index=True)
    source_media_type: Mapped[str] = mapped_column(String(16), default="image", index=True)
    source_bytes: Mapped[int] = mapped_column(Integer, default=0)
    output_bytes: Mapped[int] = mapped_column(Integer, default=0)
    source_width: Mapped[int] = mapped_column(Integer, default=0)
    source_height: Mapped[int] = mapped_column(Integer, default=0)
    output_width: Mapped[int] = mapped_column(Integer, default=0)
    output_height: Mapped[int] = mapped_column(Integer, default=0)
    compression_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    queue_wait_ms: Mapped[int] = mapped_column(Integer, default=0)
    processing_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    total_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    watermark_applied: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    warnings_count: Mapped[int] = mapped_column(Integer, default=0)
    artifact_id: Mapped[str | None] = mapped_column(String(191), index=True)
    artifact_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
