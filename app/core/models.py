from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
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
SITE_STATUS_SUSPENDED = "suspended"
SITE_STATUS_ARCHIVED = "archived"

SITE_API_KEY_STATUS_ACTIVE = "active"
SITE_API_KEY_STATUS_REVOKED = "revoked"
SITE_API_KEY_STATUS_EXPIRED = "expired"

ACCOUNT_STATUS_ACTIVE = "active"
ACCOUNT_STATUS_SUSPENDED = "suspended"

ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN = "user_admin"

ACCOUNT_MEMBERSHIP_STATUS_ACTIVE = "active"
ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE = "pending_invite"
ACCOUNT_MEMBERSHIP_STATUS_INVITED = ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE
ACCOUNT_MEMBERSHIP_STATUS_DISABLED = "disabled"
PORTAL_LOGIN_CODE_STATUS_PENDING = "pending"
PORTAL_LOGIN_CODE_STATUS_CONSUMED = "consumed"
PORTAL_LOGIN_CODE_STATUS_EXPIRED = "expired"
PORTAL_LOGIN_CODE_STATUS_LOCKED = "locked"

PORTAL_MEMBER_IDENTITY_STATUS_ACTIVE = "active"
PORTAL_MEMBER_IDENTITY_STATUS_DISABLED = "disabled"

PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN = "platform_admin"

PLATFORM_ADMIN_STATUS_ACTIVE = "active"
PLATFORM_ADMIN_STATUS_DISABLED = "disabled"

PLAN_STATUS_DRAFT = "draft"
PLAN_STATUS_ACTIVE = "active"
PLAN_STATUS_ARCHIVED = "archived"

PLAN_VERSION_STATUS_DRAFT = "draft"
PLAN_VERSION_STATUS_PUBLISHED = "published"
PLAN_VERSION_STATUS_ARCHIVED = "archived"

SUBSCRIPTION_STATUS_TRIALING = "trialing"
SUBSCRIPTION_STATUS_ACTIVE = "active"
SUBSCRIPTION_STATUS_PAST_DUE = "past_due"
SUBSCRIPTION_STATUS_SUSPENDED = "suspended"
SUBSCRIPTION_STATUS_CANCELED = "canceled"

ENTITLEMENT_SNAPSHOT_STATUS_ACTIVE = "active"
ENTITLEMENT_SNAPSHOT_STATUS_SUPERSEDED = "superseded"

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


class AccountMembership(Base):
    __tablename__ = "account_memberships"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "member_ref",
            name="uq_account_memberships_account_member",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    member_ref: Mapped[str] = mapped_column(String(191))
    role: Mapped[str] = mapped_column(
        String(32),
        default=ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default=ACCOUNT_MEMBERSHIP_STATUS_ACTIVE,
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


class PortalMemberIdentity(Base):
    __tablename__ = "portal_member_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "external_subject",
            name="uq_portal_member_identities_provider_subject",
        ),
    )

    identity_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    external_subject: Mapped[str] = mapped_column(String(191))
    email: Mapped[str | None] = mapped_column(String(191), index=True)
    member_ref: Mapped[str] = mapped_column(String(191), index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default=PORTAL_MEMBER_IDENTITY_STATUS_ACTIVE,
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
    member_ref: Mapped[str] = mapped_column(String(191), index=True)
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


class PlatformAdminIdentity(Base):
    __tablename__ = "platform_admin_identities"
    __table_args__ = (
        UniqueConstraint("admin_ref", name="uq_platform_admin_identities_admin_ref"),
    )

    admin_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    admin_ref: Mapped[str] = mapped_column(String(191), index=True)
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
    currency: Mapped[str] = mapped_column(String(16), default="USD")
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
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_usage_meter_events_dedupe"),
    )

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
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_plugin_observability_events_dedupe"),
    )

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
    currency: Mapped[str] = mapped_column(String(16), default="USD")
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


class MediaDerivativeArtifact(Base):
    __tablename__ = "media_derivative_artifacts"

    artifact_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run_records.run_id"), index=True)
    site_id: Mapped[str] = mapped_column(String(191), index=True)
    storage_ref: Mapped[str] = mapped_column(String(512))
    blob_data: Mapped[bytes] = mapped_column(LargeBinary)
    mime_type: Mapped[str] = mapped_column(String(64))
    format: Mapped[str] = mapped_column(String(16))
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    filesize_bytes: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str] = mapped_column(String(128))
    source_media_type: Mapped[str] = mapped_column(String(16), default="image")
    processing_warnings_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class MediaDerivativeJobMetric(Base):
    __tablename__ = "media_derivative_job_metrics"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_media_derivative_job_metrics_run"),
    )

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
    artifact_download_count: Mapped[int] = mapped_column(Integer, default=0)
    artifact_last_downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
