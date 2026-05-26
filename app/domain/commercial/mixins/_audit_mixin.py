"""Commercial service: audit, serialization, and coercion base mixin."""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.models import (
    ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN,
    ACCOUNT_MEMBERSHIP_STATUS_ACTIVE,
    ACCOUNT_MEMBERSHIP_STATUS_DISABLED,
    ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE,
    ACCOUNT_STATUS_ACTIVE,
    CommercialDecisionEvent,
    PLAN_STATUS_ACTIVE,
    PLAN_VERSION_STATUS_PUBLISHED,
    PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
    ServiceAuditEvent,
    Site,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_TRIALING,
)
from app.domain.commercial.errors import CommercialPermissionError


PORTAL_SITE_KEY_WRITE_ROLES = {
    ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN,
}
PORTAL_SITE_PROVISION_ROLES = {
    ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN,
}
PORTAL_SITE_READ_ROLES = {
    ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN,
}
PORTAL_MEMBERSHIP_ALLOWED_ROLES = PORTAL_SITE_READ_ROLES
ACCOUNT_MEMBERSHIP_ALLOWED_ROLES = PORTAL_MEMBERSHIP_ALLOWED_ROLES
PLATFORM_ADMIN_ALLOWED_ROLES = {
    PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
}
PLATFORM_ADMIN_ACCOUNT_WRITE_ROLES = {
    PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
}
PLATFORM_ADMIN_CATALOG_WRITE_ROLES = {
    PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
}
PLATFORM_IMPERSONATION_ALLOWED_ROLES = {
    PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
}
PORTAL_MEMBER_ALLOWED_LOGIN_STATUSES = {
    ACCOUNT_MEMBERSHIP_STATUS_ACTIVE,
    ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE,
}
COMMERCIAL_COVERED_SUBSCRIPTION_STATUSES = {
    SUBSCRIPTION_STATUS_TRIALING,
    SUBSCRIPTION_STATUS_ACTIVE,
}
PORTAL_INVITE_DELIVERY_QUEUED = "queued"
PORTAL_INVITE_DELIVERY_SENT = "sent"
PORTAL_INVITE_DELIVERY_FAILED = "failed"
PORTAL_INVITE_DELIVERY_SKIPPED = "skipped"
PORTAL_MEMBER_PREFERENCE_LOCALES = {"en", "zh-CN", "zh-TW"}
PORTAL_MEMBER_PREFERENCE_CURRENCIES = {"USD", "CNY", "HKD"}
PORTAL_MEMBER_IDENTITY_PROVIDER = "email_magic_link"
IDENTITY_TYPE_PLATFORM_ADMIN = "platform_admin"
IDENTITY_TYPE_USER_ADMIN = "user_admin"
USER_ALLOWED_ACTION_VIEW_SITES = "view_sites"
USER_ALLOWED_ACTION_VIEW_USAGE = "view_usage"
USER_ALLOWED_ACTION_VIEW_BILLING = "view_billing"
USER_ALLOWED_ACTION_VIEW_AUDIT = "view_audit"
USER_ALLOWED_ACTION_PROVISION_SITES = "provision_sites"
USER_ALLOWED_ACTION_MANAGE_SITE_KEYS = "manage_site_keys"
USER_ALLOWED_ACTION_ARCHIVE_SITES = "archive_sites"


@dataclass(slots=True)
class ServiceAuditContext:
    trace_id: str
    idempotency_key: str
    method: str
    path: str
    actor_kind: str = "internal_token"
    actor_ref: str = "internal"


def _normalize_portal_member_email(member_ref: str, metadata_json: dict[str, object] | None) -> str:
    metadata = metadata_json or {}
    email = str(metadata.get("email") or "").strip().lower()
    if email:
        return email
    normalized_member_ref = str(member_ref or "").strip()
    if normalized_member_ref.startswith("user:"):
        return normalized_member_ref[len("user:") :].strip().lower()
    return ""


def _normalize_portal_member_locale(value: object) -> str:
    locale = str(value or "").strip()
    if locale in PORTAL_MEMBER_PREFERENCE_LOCALES:
        return locale
    return ""


def _normalize_portal_member_currency(value: object) -> str:
    currency = str(value or "").strip().upper()
    if currency in PORTAL_MEMBER_PREFERENCE_CURRENCIES:
        return currency
    return "CNY"


def _subscription_counts_as_covered(subscription: object | None) -> bool:
    if subscription is None:
        return False
    status = str(getattr(subscription, "status", "") or "").strip()
    plan_id = str(getattr(subscription, "plan_id", "") or "").strip()
    plan_version_id = str(getattr(subscription, "plan_version_id", "") or "").strip()
    return (
        status in COMMERCIAL_COVERED_SUBSCRIPTION_STATUSES
        and bool(plan_id)
        and bool(plan_version_id)
    )


def _aggregate_membership_status(statuses: set[str]) -> str:
    if ACCOUNT_MEMBERSHIP_STATUS_DISABLED in statuses:
        return ACCOUNT_MEMBERSHIP_STATUS_DISABLED
    if ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE in statuses:
        return ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE
    if ACCOUNT_MEMBERSHIP_STATUS_ACTIVE in statuses:
        return ACCOUNT_MEMBERSHIP_STATUS_ACTIVE
    return next(iter(statuses), "")


def _normalize_portal_membership_metadata(
    *,
    member_ref: str,
    status: str,
    metadata_json: dict[str, object] | None,
) -> dict[str, object]:
    normalized_status = str(status or "").strip() or ACCOUNT_MEMBERSHIP_STATUS_ACTIVE
    metadata: dict[str, object] = dict(metadata_json or {})
    email = _normalize_portal_member_email(member_ref, metadata)
    if email:
        metadata["email"] = email

    invite_state = str(metadata.get("invite_state") or "").strip().lower()
    last_delivery_status = str(metadata.get("last_delivery_status") or "").strip().lower()

    if normalized_status == ACCOUNT_MEMBERSHIP_STATUS_PENDING_INVITE:
        metadata["invite_state"] = invite_state or "pending"
    elif normalized_status == ACCOUNT_MEMBERSHIP_STATUS_ACTIVE:
        if invite_state in {"pending", "sent"} and metadata.get("last_login_at"):
            metadata["invite_state"] = "accepted"
        elif invite_state:
            metadata["invite_state"] = invite_state
        elif metadata.get("last_login_at"):
            metadata["invite_state"] = "accepted"
        else:
            metadata["invite_state"] = "active"
    elif normalized_status == ACCOUNT_MEMBERSHIP_STATUS_DISABLED:
        metadata["invite_state"] = "disabled"

    if last_delivery_status in {
        PORTAL_INVITE_DELIVERY_QUEUED,
        PORTAL_INVITE_DELIVERY_SENT,
        PORTAL_INVITE_DELIVERY_FAILED,
        PORTAL_INVITE_DELIVERY_SKIPPED,
    }:
        metadata["last_delivery_status"] = last_delivery_status

    return metadata


def _portal_membership_is_active(membership: object | None) -> bool:
    return bool(
        membership is not None
        and getattr(membership, "status", "") == ACCOUNT_MEMBERSHIP_STATUS_ACTIVE
    )


def _portal_membership_has_allowed_role(
    membership: object | None,
    *,
    required_roles: set[str] | None = None,
) -> bool:
    if membership is None:
        return False
    role = str(getattr(membership, "role", "") or "")
    if role not in PORTAL_MEMBERSHIP_ALLOWED_ROLES:
        return False
    normalized_role = _normalize_customer_membership_role(role)
    if required_roles is not None and normalized_role not in required_roles:
        return False
    return True


def _normalize_customer_membership_role(role: str) -> str:
    normalized_role = str(role or "").strip()
    if normalized_role == ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN:
        return ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN
    return ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN


def _resolve_identity_type(role: str) -> str:
    normalized_role = str(role or "").strip()
    if normalized_role in PLATFORM_ADMIN_ALLOWED_ROLES:
        return IDENTITY_TYPE_PLATFORM_ADMIN
    return IDENTITY_TYPE_USER_ADMIN


def _portal_membership_role_priority(role: str) -> int:
    return 0


def _normalize_platform_admin_role(role: str) -> str:
    return str(role or "").strip()


def _canonicalize_customer_membership_role_for_write(role: str) -> str:
    normalized_role = str(role or "").strip()
    if normalized_role in ACCOUNT_MEMBERSHIP_ALLOWED_ROLES:
        return ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN
    return ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN


def _canonicalize_platform_admin_role_for_write(role: str) -> str:
    normalized_role = str(role or "").strip()
    if normalized_role in PLATFORM_ADMIN_ALLOWED_ROLES:
        return PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN
    return PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN


def _resolve_portal_allowed_actions(role: str) -> list[str]:
    normalized_role = _normalize_customer_membership_role(role)
    actions = [
        USER_ALLOWED_ACTION_VIEW_SITES,
        USER_ALLOWED_ACTION_VIEW_USAGE,
        USER_ALLOWED_ACTION_VIEW_BILLING,
        USER_ALLOWED_ACTION_VIEW_AUDIT,
        USER_ALLOWED_ACTION_PROVISION_SITES,
        USER_ALLOWED_ACTION_MANAGE_SITE_KEYS,
        USER_ALLOWED_ACTION_ARCHIVE_SITES,
    ]
    return actions


def _platform_capability_flags(role: str) -> dict[str, bool]:
    normalized_role = _normalize_platform_admin_role(role)
    return {
        "can_manage_accounts": normalized_role in PLATFORM_ADMIN_ACCOUNT_WRITE_ROLES,
        "can_manage_catalog": normalized_role in PLATFORM_ADMIN_CATALOG_WRITE_ROLES,
        "can_impersonate": normalized_role in PLATFORM_IMPERSONATION_ALLOWED_ROLES,
        "can_manage_billing": normalized_role in PLATFORM_ADMIN_ALLOWED_ROLES,
        "can_review_diagnostics": normalized_role in PLATFORM_ADMIN_ALLOWED_ROLES,
    }


def _slugify_portal_site_segment(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized


def _normalize_portal_site_url(value: str) -> tuple[str, str]:
    raw = str(value or "").strip()
    if not raw:
        raise CommercialPermissionError(
            "service.portal_site_url_required",
            "wordpress site url is required",
        )
    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlsplit(candidate)
    hostname = str(parsed.hostname or "").strip().lower()
    if not hostname:
        raise CommercialPermissionError(
            "service.portal_site_url_invalid",
            "wordpress site url is invalid",
        )
    path = re.sub(r"/+", "/", str(parsed.path or "/").strip())
    path = "/" if not path or path == "." else path
    canonical = f"{parsed.scheme.lower() or 'https'}://{hostname}"
    if path not in {"", "/"}:
        canonical = f"{canonical}{path.rstrip('/')}"
    return canonical, hostname + (f"{path.rstrip('/').replace('/', '-')}" if path not in {"", "/"} else "")


def _extract_site_wordpress_url(site: Site) -> str:
    metadata = site.metadata_json if isinstance(site.metadata_json, dict) else {}
    raw_value = metadata.get("wordpress_url", "")
    return str(raw_value).strip() if raw_value is not None else ""


def assert_platform_admin_role_allowed(
    *,
    role: str,
    allowed_roles: set[str],
    error_code: str,
    message: str,
) -> str:
    normalized_role = _normalize_platform_admin_role(role)
    if normalized_role not in PLATFORM_ADMIN_ALLOWED_ROLES:
        raise CommercialPermissionError(
            "service.platform_admin_role_invalid",
            f"unsupported platform admin role '{normalized_role}'",
        )
    if normalized_role not in allowed_roles:
        raise CommercialPermissionError(error_code, message)
    return normalized_role


def assert_platform_admin_capability(
    *,
    role: str,
    capability: str,
    error_code: str,
    message: str,
) -> str:
    normalized_role = _normalize_platform_admin_role(role)
    if normalized_role not in PLATFORM_ADMIN_ALLOWED_ROLES:
        raise CommercialPermissionError(
            "service.platform_admin_role_invalid",
            f"unsupported platform admin role '{normalized_role}'",
        )
    capabilities = _platform_capability_flags(normalized_role)
    if not bool(capabilities.get(capability)):
        raise CommercialPermissionError(error_code, message)
    return normalized_role


class CommercialServiceAuditMixin:
    def __init__(
        self,
        database_url: str,
        now_factory: Callable[[], datetime] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.database_url = database_url
        self.now_factory = now_factory or (lambda: datetime.now(UTC))
        self.settings = settings or get_settings()

    def _serialize_service_audit_event(self, event: ServiceAuditEvent) -> dict[str, object]:
        return {
            "event_id": int(event.id or 0),
            "account_id": event.account_id or "",
            "site_id": event.site_id or "",
            "key_id": event.key_id or "",
            "subscription_id": event.subscription_id or "",
            "plan_id": event.plan_id or "",
            "plan_version_id": event.plan_version_id or "",
            "scope_kind": event.scope_kind or "",
            "scope_id": event.scope_id or "",
            "event_kind": event.event_kind,
            "outcome": event.outcome,
            "method": event.method or "",
            "path": event.path or "",
            "trace_id": event.trace_id or "",
            "idempotency_key": event.idempotency_key or "",
            "actor_kind": event.actor_kind,
            "actor_ref": event.actor_ref or "",
            "payload": event.payload_json or {},
            "created_at": self._serialize_datetime(event.created_at),
        }

    def _serialize_commercial_decision_event(
        self,
        event: CommercialDecisionEvent,
    ) -> dict[str, object]:
        return {
            "event_id": int(event.id or 0),
            "account_id": event.account_id or "",
            "site_id": event.site_id or "",
            "subscription_id": event.subscription_id or "",
            "plan_version_id": event.plan_version_id or "",
            "run_id": event.run_id or "",
            "request_kind": event.request_kind,
            "decision": event.decision,
            "decision_code": event.decision_code,
            "ability_family": event.ability_family or "",
            "channel": event.channel or "",
            "execution_kind": event.execution_kind or "",
            "execution_tier": event.execution_tier or "",
            "data_classification": event.data_classification or "",
            "trace_id": event.trace_id or "",
            "idempotency_key": event.idempotency_key or "",
            "payload": event.payload_json or {},
            "created_at": self._serialize_datetime(event.created_at),
        }

    def _record_service_audit_in_session(
        self,
        *,
        repository: CommercialRepository,
        audit_context: ServiceAuditContext | None,
        event_kind: str,
        outcome: str,
        account_id: str | None = None,
        site_id: str | None = None,
        key_id: str | None = None,
        subscription_id: str | None = None,
        plan_id: str | None = None,
        plan_version_id: str | None = None,
        scope_kind: str | None = None,
        scope_id: str | None = None,
        payload_json: dict[str, object] | None = None,
    ) -> ServiceAuditEvent | None:
        if audit_context is None:
            return None

        return repository.record_service_audit_event(
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
            method=audit_context.method.upper(),
            path=audit_context.path,
            trace_id=audit_context.trace_id,
            idempotency_key=audit_context.idempotency_key,
            actor_kind=audit_context.actor_kind,
            actor_ref=audit_context.actor_ref,
            payload_json=self._sanitize_payload(payload_json),
        )

    def _record_commercial_decision_in_session(
        self,
        *,
        repository: CommercialRepository,
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
        return repository.record_commercial_decision_event(
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
            payload_json=self._sanitize_payload(payload_json),
        )

    def _sanitize_payload(self, payload: object) -> object:
        if isinstance(payload, dict):
            sanitized: dict[str, object] = {}
            for key, value in payload.items():
                normalized_key = str(key).lower()
                if normalized_key == "secret":
                    sanitized[str(key)] = "[redacted]"
                    continue
                sanitized[str(key)] = self._sanitize_payload(value)
            return sanitized
        if isinstance(payload, list):
            return [self._sanitize_payload(item) for item in payload]
        return payload

    def _build_subscription_grace_state(
        self,
        *,
        subscription: AccountSubscription | None,
        policy: dict[str, object],
        period_end_at: datetime,
        now: datetime,
    ) -> dict[str, object]:
        if subscription is None:
            return {
                "active": False,
                "subscription_status": "missing",
                "grace_until_at": "",
                "grace_period_days": 0,
            }
        action = self._resolve_subscription_policy_action(
            subscription=subscription,
            policy=policy,
            period_end_at=period_end_at,
            now=now,
            reason="inspect",
        )
        subscription_policy = policy.get("subscription")
        subscription_policy = (
            subscription_policy if isinstance(subscription_policy, dict) else {}
        )
        return {
            "active": action is not None,
            "subscription_status": subscription.status,
            "grace_period_days": max(
                0,
                self._coerce_int(subscription_policy.get("grace_period_days")),
            ),
            "grace_until_at": str(action.get("grace_until_at") or "") if action else "",
            "runtime_policy_overrides": (
                action.get("runtime_policy_overrides") if action else {}
            ),
        }

    def _build_budget_policy_state(
        self,
        *,
        repository: CommercialRepository,
        subscription: AccountSubscription | None,
        policy: dict[str, object],
        budgets: dict[str, object],
        totals: dict[str, float],
        period_start_at: datetime,
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        normalized_policy = policy.get("budgets")
        normalized_policy = normalized_policy if isinstance(normalized_policy, dict) else {}
        for meter_key, budget_key in (
            ("runs", "max_runs_per_period"),
            ("tokens", "max_tokens_per_period"),
            ("cost", "max_cost_per_period"),
        ):
            meter_policy = normalized_policy.get(meter_key)
            meter_policy = meter_policy if isinstance(meter_policy, dict) else {}
            grace_requests = max(0, self._coerce_int(meter_policy.get("grace_requests")))
            used_grace_requests = 0
            if subscription is not None and grace_requests > 0:
                used_grace_requests = repository.count_commercial_decision_events(
                    subscription_id=subscription.subscription_id,
                    decision="allow",
                    decision_code=f"commercial.quota_grace.{meter_key}",
                    request_kind="execute",
                    since=period_start_at,
                )
            result[meter_key] = {
                "current_total": round(float(totals.get(
                    "tokens_total" if meter_key == "tokens" else meter_key,
                    0.0,
                )), 6),
                "limit": round(float(self._coerce_float(budgets.get(budget_key))), 6),
                "grace_requests": grace_requests,
                "used_grace_requests": used_grace_requests,
                "remaining_grace_requests": max(0, grace_requests - used_grace_requests),
                "downgrade_policy": self._normalize_runtime_policy_overrides(
                    meter_policy.get("downgrade_policy")
                ),
                "over_limit": round(float(totals.get(
                    "tokens_total" if meter_key == "tokens" else meter_key,
                    0.0,
                )), 6) >= round(float(self._coerce_float(budgets.get(budget_key))), 6)
                and self._coerce_float(budgets.get(budget_key)) > 0,
            }
        return result

    def _build_diagnostic_check(
        self,
        code: str,
        ok: bool,
        label: str,
        next_step: str,
    ) -> dict[str, object]:
        return {
            "code": code,
            "key": code,
            "ok": ok,
            "status": "ok" if ok else "warning",
            "label": label,
            "title": label,
            "next_step": next_step,
            "detail": label,
            "action": next_step,
        }

    def _normalize_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _coerce_bool(self, value: object | None) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    def _coerce_int(self, value: object | None) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return 0
        return 0

    def _coerce_float(self, value: object | None) -> float:
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return 0.0
        return 0.0

    def _serialize_datetime(self, value: datetime | str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return None
            try:
                parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
            except ValueError:
                return normalized
            return self._normalize_datetime(parsed).isoformat()
        return self._normalize_datetime(value).isoformat()

    def record_service_audit_event(
        self,
        *,
        audit_context: ServiceAuditContext | None,
        event_kind: str,
        outcome: str,
        account_id: str | None = None,
        site_id: str | None = None,
        key_id: str | None = None,
        subscription_id: str | None = None,
        plan_id: str | None = None,
        plan_version_id: str | None = None,
        scope_kind: str | None = None,
        scope_id: str | None = None,
        payload_json: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            event = self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind=event_kind,
                outcome=outcome,
                account_id=account_id,
                site_id=site_id,
                key_id=key_id,
                subscription_id=subscription_id,
                plan_id=plan_id,
                plan_version_id=plan_version_id,
                scope_kind=scope_kind,
                scope_id=scope_id,
                payload_json=payload_json,
            )
            if event is None:
                return None
            session.commit()
            return self._serialize_service_audit_event(event)

    def list_service_audit_events(
        self,
        *,
        site_id: str | None = None,
        account_id: str | None = None,
        event_kind: str | None = None,
        outcome: str | None = None,
        limit: int = 50,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            events = repository.list_service_audit_events(
                site_id=site_id,
                account_id=account_id,
                event_kind=event_kind,
                outcome=outcome,
                limit=limit,
            )
            return {
                "items": [self._serialize_service_audit_event(event) for event in events],
                "total": len(events),
            }
