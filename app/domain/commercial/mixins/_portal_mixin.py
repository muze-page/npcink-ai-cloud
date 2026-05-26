"""Commercial service: portal operations mixin."""
from __future__ import annotations

import re
import secrets
from collections import defaultdict
from datetime import datetime, timedelta
from uuid import uuid4

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.db import get_session
from app.core.models import (
    ACCOUNT_MEMBERSHIP_STATUS_ACTIVE,
    PORTAL_ACTION_REQUEST_STATUS_ACKNOWLEDGED,
    PORTAL_ACTION_REQUEST_STATUS_CANCELED,
    PORTAL_ACTION_REQUEST_STATUS_OPEN,
    PORTAL_ACTION_REQUEST_STATUS_RESOLVED,
    PORTAL_LOGIN_CODE_STATUS_CONSUMED,
    PORTAL_LOGIN_CODE_STATUS_EXPIRED,
    PORTAL_LOGIN_CODE_STATUS_LOCKED,
    PortalActionRequest,
    Site,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_PAST_DUE,
    SUBSCRIPTION_STATUS_SUSPENDED,
    SUBSCRIPTION_STATUS_TRIALING,
)
from app.core.security import build_secret_hash
from app.domain.commercial.errors import (
    CommercialNotFoundError,
    CommercialPermissionError,
    CommercialValidationError,
)
from app.domain.commercial.mixins._audit_mixin import (
    PORTAL_MEMBER_ALLOWED_LOGIN_STATUSES,
    ServiceAuditContext,
    _normalize_portal_membership_metadata,
    _portal_membership_has_allowed_role,
)
from app.domain.commercial.service import PLAN_TIER_REGISTRY

class CommercialServicePortalMixin:

    def issue_portal_login_code(
        self,
        *,
        email: str,
        ttl_seconds: int,
    ) -> dict[str, object]:
        login = self.resolve_portal_member_login(email=email)
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
                updated_items.append(self._serialize_account_membership(membership))
            session.commit()
        return {
            "email": normalized_email,
            "member_ref": member_ref,
            "last_login_at": self._serialize_datetime(now),
            "memberships": updated_items,
        }


    def create_portal_action_request(
        self,
        *,
        request_type: str,
        member_ref: str,
        account_id: str | None,
        site_id: str | None,
        title: str,
        message: str,
        payload_json: dict[str, object] | None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_type = self._normalize_portal_action_request_type(request_type)
        if not normalized_type:
            raise CommercialValidationError("service.invalid_request_type", "request type is invalid")
        normalized_member_ref = str(member_ref or "").strip()
        if not normalized_member_ref:
            raise CommercialValidationError("service.invalid_member_ref", "member ref is required")
        normalized_title = str(title or "").strip()[:191]
        if not normalized_title:
            raise CommercialValidationError("service.invalid_request_title", "request title is required")

        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            existing = repository.list_portal_action_requests(
                member_ref=normalized_member_ref,
                site_id=str(site_id or "").strip() or None,
                request_type=normalized_type,
                statuses=[PORTAL_ACTION_REQUEST_STATUS_OPEN],
                limit=1,
            )
            if existing:
                return self._serialize_portal_action_request(existing[0])

            item = repository.create_portal_action_request(
                request_id=f"par_{uuid4().hex}",
                request_type=normalized_type,
                account_id=str(account_id or "").strip() or None,
                site_id=str(site_id or "").strip() or None,
                member_ref=normalized_member_ref,
                title=normalized_title,
                message=str(message or "").strip()[:2000] or None,
                status=PORTAL_ACTION_REQUEST_STATUS_OPEN,
                payload_json=payload_json or {},
            )
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind=f"portal_action_request.{normalized_type}.created",
                outcome="succeeded",
                account_id=str(account_id or "").strip() or None,
                site_id=str(site_id or "").strip() or None,
                scope_kind="portal_action_request",
                scope_id=item.request_id,
                payload_json=self._serialize_portal_action_request(item),
            )
            session.commit()
            return self._serialize_portal_action_request(item)


    def list_portal_action_requests(
        self,
        *,
        member_ref: str,
        account_id: str | None = None,
        site_id: str | None = None,
        request_type: str | None = None,
        statuses: list[str] | None = None,
        limit: int = 50,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            items = repository.list_portal_action_requests(
                member_ref=str(member_ref or "").strip(),
                account_id=str(account_id or "").strip() or None,
                site_id=str(site_id or "").strip() or None,
                request_type=self._normalize_portal_action_request_type(request_type or ""),
                statuses=[self._normalize_portal_action_request_status(item) for item in statuses or [] if item],
                limit=limit,
            )
            return {
                "items": [self._serialize_portal_action_request(item) for item in items],
                "pagination": {"limit": max(1, min(limit, 100)), "total": len(items)},
            }


    def acknowledge_portal_action_request(
        self,
        *,
        request_id: str,
        member_ref: str,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            item = repository.get_portal_action_request(str(request_id or "").strip())
            if item is None or item.member_ref != str(member_ref or "").strip():
                raise CommercialNotFoundError("service.portal_action_request_not_found", "portal action request was not found")
            if item.status == PORTAL_ACTION_REQUEST_STATUS_OPEN:
                now = self.now_factory()
                item.status = PORTAL_ACTION_REQUEST_STATUS_ACKNOWLEDGED
                item.acknowledged_at = now
                item.updated_at = now
                self._record_service_audit_in_session(
                    repository=repository,
                    audit_context=audit_context,
                    event_kind="portal_action_request.acknowledged",
                    outcome="succeeded",
                    account_id=item.account_id,
                    site_id=item.site_id,
                    scope_kind="portal_action_request",
                    scope_id=item.request_id,
                    payload_json=self._serialize_portal_action_request(item),
                )
            session.commit()
            return self._serialize_portal_action_request(item)


    def decide_portal_action_request(
        self,
        *,
        request_id: str,
        decision: str,
        decision_note: str = "",
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_decision = str(decision or "").strip().lower()
        if normalized_decision not in {"approve", "reject"}:
            raise CommercialValidationError("service.invalid_request_decision", "decision must be approve or reject")
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            item = repository.get_portal_action_request(str(request_id or "").strip())
            if item is None:
                raise CommercialNotFoundError("service.portal_action_request_not_found", "portal action request was not found")
            if str(item.status or "").strip() not in {
                PORTAL_ACTION_REQUEST_STATUS_OPEN,
                PORTAL_ACTION_REQUEST_STATUS_ACKNOWLEDGED,
            }:
                raise CommercialValidationError(
                    "service.portal_action_request_already_decided",
                    "portal action request has already been decided",
                )
            now = self.now_factory()
            payload = dict(item.payload_json or {})
            payload["admin_decision"] = normalized_decision
            payload["admin_decision_note"] = str(decision_note or "").strip()[:1000]
            payload["admin_decided_at"] = self._serialize_datetime(now)
            if normalized_decision == "approve":
                payload["application_result"] = self._apply_portal_action_request_approval_in_session(
                    repository=repository,
                    item=item,
                    decision_note=str(decision_note or "").strip(),
                    audit_context=audit_context,
                )
            item.status = (
                PORTAL_ACTION_REQUEST_STATUS_RESOLVED
                if normalized_decision == "approve"
                else PORTAL_ACTION_REQUEST_STATUS_CANCELED
            )
            if normalized_decision == "approve":
                item.resolved_at = now
            else:
                item.canceled_at = now
            item.payload_json = payload
            item.updated_at = now
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind=f"portal_action_request.{normalized_decision}",
                outcome="succeeded",
                account_id=item.account_id,
                site_id=item.site_id,
                scope_kind="portal_action_request",
                scope_id=item.request_id,
                payload_json=self._serialize_portal_action_request(item),
            )
            session.commit()
            return self._serialize_portal_action_request(item)


    def list_portal_accounts(
        self,
        *,
        member_ref: str,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            account_memberships = self._list_resolved_portal_account_memberships(
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
                    self._serialize_portal_account_context(
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


    def get_portal_usage_alert_settings(self, site_id: str) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            site = repository.get_site(site_id)
            if site is None:
                raise CommercialNotFoundError("service.site_not_found", f"site '{site_id}' was not found")
            settings = self._normalize_usage_alert_settings(
                (site.metadata_json or {}).get("portal_usage_alert_settings")
            )
            return {"site_id": site_id, **settings}


    def update_portal_usage_alert_settings(
        self,
        site_id: str,
        *,
        settings: dict[str, object],
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized = self._normalize_usage_alert_settings(settings, strict=True)
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            site = repository.get_site(site_id)
            if site is None:
                raise CommercialNotFoundError("service.site_not_found", f"site '{site_id}' was not found")
            metadata = dict(site.metadata_json or {})
            metadata["portal_usage_alert_settings"] = normalized
            site.metadata_json = metadata
            site.updated_at = self.now_factory()
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="usage_alert_settings.updated",
                outcome="succeeded",
                account_id=site.account_id,
                site_id=site.site_id,
                scope_kind="site",
                scope_id=site.site_id,
                payload_json={"settings": normalized},
            )
            session.commit()
            return {"site_id": site_id, **normalized}


    def _apply_portal_action_request_approval_in_session(
        self,
        *,
        repository: CommercialRepository,
        item: PortalActionRequest,
        decision_note: str = "",
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_type = self._normalize_portal_action_request_type(item.request_type)
        payload = dict(item.payload_json or {})
        if normalized_type == "package_change":
            return self._apply_portal_package_change_request_in_session(
                repository=repository,
                item=item,
                payload=payload,
                decision_note=decision_note,
                audit_context=audit_context,
            )
        if normalized_type == "topup_pack":
            account_id = str(item.account_id or "").strip()
            if not account_id:
                raise CommercialValidationError(
                    "service.portal_action_request_account_required",
                    "portal top-up approvals require an account",
                )
            subscription = repository.get_runtime_subscription(account_id)
            if subscription is None:
                raise CommercialNotFoundError(
                    "service.subscription_not_found",
                    f"no subscription was found for account '{account_id}'",
                )
            topup_result = self._apply_operator_managed_subscription_topup_in_session(
                repository=repository,
                subscription_id=subscription.subscription_id,
                pack_id=str(payload.get("pack_id") or ""),
                runs_increment=0.0,
                tokens_increment=0.0,
                cost_increment=0.0,
                reason=str(item.message or payload.get("reason") or item.title or "").strip()
                or "portal_topup_request_approved",
                note=decision_note,
                audit_context=audit_context,
            )
            return {
                "kind": "topup_applied",
                "subscription_id": str(
                    (topup_result.get("subscription") or {}).get("subscription_id") or ""
                ),
                "pack_id": str(payload.get("pack_id") or ""),
                "pack_label": str(payload.get("pack_label") or ""),
                "topup": topup_result.get("topup") or {},
                "topup_summary": topup_result.get("topup_summary") or {},
            }
        return {}


    def _apply_portal_package_change_request_in_session(
        self,
        *,
        repository: CommercialRepository,
        item: PortalActionRequest,
        payload: dict[str, object],
        decision_note: str = "",
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        account_id = str(item.account_id or "").strip()
        if not account_id:
            raise CommercialValidationError(
                "service.portal_action_request_account_required",
                "portal package approvals require an account",
            )
        target_package = str(payload.get("target_package") or "").strip().lower()
        tier_id = self._resolve_portal_target_package_tier_id(target_package)
        plan_id, plan_version_id = self._ensure_plan_tier_version_in_session(
            repository=repository,
            tier_id=tier_id,
        )
        existing_subscription = repository.get_runtime_subscription(account_id)
        baseline = PLAN_TIER_REGISTRY[tier_id]
        metadata_json = dict(existing_subscription.metadata_json or {}) if existing_subscription else {}
        metadata_json.pop("plan_kind", None)
        metadata_json.update(
            {
                "tier_id": tier_id,
                "package_alias": str(baseline.get("package_alias") or ""),
                "site_limit": int(baseline.get("site_limit") or 1),
                "monthly_included_points": int(baseline.get("monthly_included_points") or 0),
                "max_batch_items": int(baseline.get("max_batch_items") or 0),
                "automation_enabled": bool(baseline.get("automation_enabled")),
                "api_enabled": bool(baseline.get("api_enabled")),
                "openclaw_enabled": bool(baseline.get("openclaw_enabled")),
                "source": "portal_action_request.approved",
                "approved_request_id": item.request_id,
                "approved_site_id": str(item.site_id or ""),
            }
        )
        if decision_note:
            metadata_json["operator_note"] = decision_note[:500]
        subscription_status = (
            str(existing_subscription.status or "").strip()
            if existing_subscription is not None
            else ""
        )
        if subscription_status not in {
            SUBSCRIPTION_STATUS_TRIALING,
            SUBSCRIPTION_STATUS_ACTIVE,
            SUBSCRIPTION_STATUS_PAST_DUE,
            SUBSCRIPTION_STATUS_SUSPENDED,
        }:
            subscription_status = SUBSCRIPTION_STATUS_ACTIVE
        subscription_result = self._upsert_account_subscription_in_session(
            repository=repository,
            subscription_id=(
                str(existing_subscription.subscription_id or "").strip()
                if existing_subscription is not None
                else f"sub_{account_id}_{tier_id}"
            ),
            account_id=account_id,
            plan_id=plan_id,
            plan_version_id=plan_version_id,
            status=subscription_status,
            current_period_start_at=(
                existing_subscription.current_period_start_at
                if existing_subscription is not None
                else None
            ),
            current_period_end_at=(
                existing_subscription.current_period_end_at
                if existing_subscription is not None
                else None
            ),
            metadata_json=metadata_json,
            audit_context=audit_context,
        )
        return {
            "kind": "package_changed",
            "target_package": target_package,
            "tier_id": tier_id,
            "subscription": subscription_result.get("subscription") or {},
            "entitlement_snapshot": subscription_result.get("entitlement_snapshot") or {},
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


    def _normalize_portal_action_request_type(self, value: str) -> str:
        normalized = re.sub(r"[^a-z0-9_.-]+", "_", str(value or "").strip().lower()).strip("_")
        allowed = {
            "package_change",
            "topup_pack",
            "site_delete",
            "usage_alert",
            "key_expiry",
            "auth_guard",
        }
        return normalized if normalized in allowed else ""


    def _normalize_portal_action_request_status(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        allowed = {
            PORTAL_ACTION_REQUEST_STATUS_OPEN,
            PORTAL_ACTION_REQUEST_STATUS_ACKNOWLEDGED,
            "resolved",
            "canceled",
        }
        return normalized if normalized in allowed else PORTAL_ACTION_REQUEST_STATUS_OPEN


    def _normalize_usage_alert_settings(
        self,
        value: object,
        *,
        strict: bool = False,
    ) -> dict[str, object]:
        raw = value if isinstance(value, dict) else {}
        default = {
            "enabled": True,
            "requests": {"warning": 80, "critical": 95},
            "tokens": {"warning": 80, "critical": 95},
            "cost": {"warning": 80, "critical": 95},
        }
        normalized: dict[str, object] = {"enabled": bool(raw.get("enabled", default["enabled"]))}
        for metric in ("requests", "tokens", "cost"):
            entry = raw.get(metric)
            source = entry if isinstance(entry, dict) else {}
            warning = self._normalize_usage_alert_threshold(source.get("warning", 80), strict=strict)
            critical = self._normalize_usage_alert_threshold(source.get("critical", 95), strict=strict)
            if warning >= critical:
                if strict:
                    raise CommercialValidationError(
                        "service.invalid_usage_alert_threshold",
                        "warning threshold must be lower than critical threshold",
                    )
                warning, critical = 80, 95
            normalized[metric] = {"warning": warning, "critical": critical}
        return normalized


    def _normalize_usage_alert_threshold(self, value: object, *, strict: bool) -> int:
        try:
            threshold = int(value)
        except (TypeError, ValueError):
            if strict:
                raise CommercialValidationError(
                    "service.invalid_usage_alert_threshold",
                    "usage alert threshold must be an integer",
                ) from None
            return 80
        if threshold < 1 or threshold > 100:
            if strict:
                raise CommercialValidationError(
                    "service.invalid_usage_alert_threshold",
                    "usage alert threshold must be between 1 and 100",
                )
            return max(1, min(threshold, 100))
        return threshold


    def _serialize_portal_action_request(self, item: PortalActionRequest) -> dict[str, object]:
        return {
            "request_id": item.request_id,
            "request_type": item.request_type,
            "account_id": item.account_id or "",
            "site_id": item.site_id or "",
            "member_ref": item.member_ref,
            "title": item.title,
            "message": item.message or "",
            "status": item.status,
            "payload": item.payload_json or {},
            "acknowledged_at": self._serialize_datetime(item.acknowledged_at),
            "resolved_at": self._serialize_datetime(item.resolved_at),
            "canceled_at": self._serialize_datetime(item.canceled_at),
            "created_at": self._serialize_datetime(item.created_at),
            "updated_at": self._serialize_datetime(item.updated_at),
        }

