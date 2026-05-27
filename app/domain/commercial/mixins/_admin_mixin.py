"""Commercial service: admin and platform operations mixin."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.db import get_session
from app.core.models import (
    ACCOUNT_MEMBERSHIP_STATUS_ACTIVE,
    AccountSubscription,
    PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
    PLATFORM_ADMIN_STATUS_ACTIVE,
    PLATFORM_IMPERSONATION_STATUS_ACTIVE,
    PLATFORM_IMPERSONATION_STATUS_ENDED,
    PlatformImpersonationSession,
    SITE_API_KEY_STATUS_ACTIVE,
    SITE_STATUS_ACTIVE,
    Site,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_PAST_DUE,
    SUBSCRIPTION_STATUS_SUSPENDED,
    SUBSCRIPTION_STATUS_TRIALING,
)
from app.domain.commercial.errors import (
    CommercialNotFoundError,
    CommercialPermissionError,
)
from app.domain.commercial.mixins._audit_mixin import (
    ServiceAuditContext,
    IDENTITY_TYPE_PLATFORM_ADMIN,
    IDENTITY_TYPE_USER_ADMIN,
    _aggregate_membership_status,
    _canonicalize_platform_admin_role_for_write,
    _subscription_counts_as_covered,
    _platform_capability_flags,
)
from app.domain.commercial.mixins._billing_mixin import (
    SHADOW_PRICING_TARIFF_REGISTRY,
    SHADOW_PRICING_TARIFF_VERSION,
)


# Default impersonation TTL (30 minutes)
PLATFORM_IMPERSONATION_MAX_TTL_SECONDS = 30 * 60

class CommercialServiceAdminMixin:

    def upsert_platform_admin_identity(
        self,
        *,
        admin_ref: str,
        role: str = PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
        status: str = PLATFORM_ADMIN_STATUS_ACTIVE,
        provider: str = "manual",
        external_subject: str | None = None,
        email: str | None = None,
        metadata_json: dict[str, object] | None = None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_admin_ref = admin_ref.strip()
        normalized_role = _canonicalize_platform_admin_role_for_write(role)
        normalized_status = status.strip() or PLATFORM_ADMIN_STATUS_ACTIVE
        normalized_provider = provider.strip().lower() or "manual"
        normalized_email = email.strip().lower() if email else None
        normalized_subject = external_subject.strip() if external_subject else None
        if not normalized_admin_ref:
            raise CommercialPermissionError(
                "service.platform_admin_ref_required",
                "platform admin ref is required",
            )
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            identity = repository.upsert_platform_admin_identity(
                admin_id=f"pad_{uuid4().hex}",
                admin_ref=normalized_admin_ref,
                provider=normalized_provider,
                external_subject=normalized_subject,
                email=normalized_email,
                role=normalized_role,
                status=normalized_status,
                metadata_json=metadata_json,
            )
            payload = self._serialize_platform_admin_identity(identity)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="platform_admin_identity.upsert",
                outcome="succeeded",
                scope_kind="platform_admin",
                scope_id=normalized_admin_ref,
                payload_json=payload,
            )
            session.commit()
            return payload


    def resolve_platform_admin_identity(
        self,
        *,
        admin_ref: str,
        bootstrap_role: str = PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
        allow_bootstrap: bool = False,
    ) -> dict[str, object]:
        normalized_admin_ref = admin_ref.strip()
        if not normalized_admin_ref:
            raise CommercialPermissionError(
                "service.platform_admin_ref_required",
                "platform admin ref is required",
            )
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            identity = repository.get_platform_admin_identity(admin_ref=normalized_admin_ref)
            if identity is None:
                if not allow_bootstrap:
                    raise CommercialNotFoundError(
                        "service.platform_admin_not_found",
                        f"platform admin '{normalized_admin_ref}' was not found",
                    )
                return {
                    "admin_ref": normalized_admin_ref,
                    "identity_type": IDENTITY_TYPE_PLATFORM_ADMIN,
                    "role": _canonicalize_platform_admin_role_for_write(bootstrap_role),
                    "capabilities": _platform_capability_flags(
                        _canonicalize_platform_admin_role_for_write(bootstrap_role)
                    ),
                    "status": PLATFORM_ADMIN_STATUS_ACTIVE,
                    "provider": "internal_token",
                    "external_subject": "",
                    "email": "",
                    "metadata": {"bootstrap": True},
                    "created_at": None,
                    "updated_at": None,
                }
            if str(identity.status or "") != PLATFORM_ADMIN_STATUS_ACTIVE:
                raise CommercialPermissionError(
                    "service.platform_admin_disabled",
                    f"platform admin '{normalized_admin_ref}' is disabled",
                )
            return self._serialize_platform_admin_identity(identity)


    def delete_platform_admin_identity(
        self,
        *,
        admin_ref: str,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_admin_ref = admin_ref.strip()
        if not normalized_admin_ref:
            raise CommercialPermissionError(
                "service.platform_admin_ref_required",
                "platform admin ref is required",
            )
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            identity = repository.get_platform_admin_identity(admin_ref=normalized_admin_ref)
            if identity is None:
                raise CommercialNotFoundError(
                    "service.platform_admin_not_found",
                    f"platform admin '{normalized_admin_ref}' was not found",
                )
            active_impersonations = repository.list_platform_impersonations(
                platform_admin_ref=normalized_admin_ref,
                active_only=True,
                now=now,
                limit=1,
            )
            if active_impersonations:
                raise CommercialPermissionError(
                    "service.platform_admin_impersonation_active",
                    f"platform admin '{normalized_admin_ref}' has an active impersonation session",
                )
            payload = self._serialize_platform_admin_identity(identity)
            repository.delete_platform_admin_identity(admin_ref=normalized_admin_ref)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="platform_admin_identity.delete",
                outcome="succeeded",
                scope_kind="platform_admin",
                scope_id=normalized_admin_ref,
                payload_json=payload,
            )
            session.commit()
            return payload


    def start_platform_impersonation(
        self,
        *,
        platform_admin_ref: str,
        platform_role: str,
        member_ref: str,
        site_id: str,
        reason_code: str,
        reason_text: str = "",
        read_only: bool = True,
        ttl_seconds: int = PLATFORM_IMPERSONATION_MAX_TTL_SECONDS,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_platform_admin_ref = platform_admin_ref.strip()
        normalized_platform_role = platform_role.strip()
        normalized_member_ref = member_ref.strip()
        normalized_site_id = site_id.strip()
        normalized_reason_code = reason_code.strip() or "support_debug"
        normalized_reason_text = reason_text.strip()
        assert_platform_admin_capability(
            role=normalized_platform_role,
            capability="can_impersonate",
            error_code="service.platform_impersonation_role_forbidden",
            message="platform admin cannot start impersonation",
        )
        if not normalized_member_ref:
            raise CommercialPermissionError(
                "service.platform_impersonation_member_required",
                "target member ref is required",
            )
        if not normalized_site_id:
            raise CommercialPermissionError(
                "service.platform_impersonation_site_required",
                "target site id is required",
            )
        now = self.now_factory()
        bounded_ttl_seconds = max(60, min(int(ttl_seconds or 0), PLATFORM_IMPERSONATION_MAX_TTL_SECONDS))
        expires_at = now + timedelta(seconds=bounded_ttl_seconds)
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            access = self.resolve_portal_site_access(
                site_id=normalized_site_id,
                member_ref=normalized_member_ref,
            )
            impersonation = repository.create_platform_impersonation(
                impersonation_id=f"imp_{uuid4().hex}",
                platform_admin_ref=normalized_platform_admin_ref,
                platform_role=normalized_platform_role,
                member_ref=normalized_member_ref,
                account_id=str(access.get("account_id") or ""),
                site_id=normalized_site_id,
                reason_code=normalized_reason_code,
                reason_text=normalized_reason_text or None,
                read_only=read_only,
                status=PLATFORM_IMPERSONATION_STATUS_ACTIVE,
                started_at=now,
                expires_at=expires_at,
                metadata_json={
                    "target_role": str(access.get("role") or ""),
                    "site": access.get("site"),
                },
            )
            payload = self._serialize_platform_impersonation(impersonation)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="platform_impersonation.start",
                outcome="succeeded",
                account_id=str(access.get("account_id") or ""),
                site_id=normalized_site_id,
                scope_kind="platform_impersonation",
                scope_id=impersonation.impersonation_id,
                payload_json=payload,
            )
            session.commit()
            return payload


    def get_platform_impersonation(
        self,
        *,
        impersonation_id: str,
        active_only: bool = False,
    ) -> dict[str, object]:
        normalized_id = impersonation_id.strip()
        if not normalized_id:
            raise CommercialNotFoundError(
                "service.platform_impersonation_not_found",
                "platform impersonation was not found",
            )
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            record = (
                repository.get_active_platform_impersonation(
                    impersonation_id=normalized_id,
                    now=self.now_factory(),
                )
                if active_only
                else repository.get_platform_impersonation(impersonation_id=normalized_id)
            )
            if record is None:
                raise CommercialNotFoundError(
                    "service.platform_impersonation_not_found",
                    f"platform impersonation '{normalized_id}' was not found",
                )
            return self._serialize_platform_impersonation(record)


    def end_platform_impersonation(
        self,
        *,
        impersonation_id: str,
        platform_admin_ref: str,
        ended_reason: str = "",
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_id = impersonation_id.strip()
        normalized_platform_admin_ref = platform_admin_ref.strip()
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            record = repository.get_platform_impersonation(impersonation_id=normalized_id)
            if record is None:
                raise CommercialNotFoundError(
                    "service.platform_impersonation_not_found",
                    f"platform impersonation '{normalized_id}' was not found",
                )
            if str(record.platform_admin_ref or "") != normalized_platform_admin_ref:
                raise CommercialPermissionError(
                    "service.platform_impersonation_admin_required",
                    f"platform admin '{normalized_platform_admin_ref}' cannot end impersonation '{normalized_id}'",
                )
            record.status = PLATFORM_IMPERSONATION_STATUS_ENDED
            record.ended_at = now
            record.ended_reason = ended_reason.strip() or "ended_by_admin"
            payload = self._serialize_platform_impersonation(record)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="platform_impersonation.end",
                outcome="succeeded",
                account_id=record.account_id,
                site_id=record.site_id,
                scope_kind="platform_impersonation",
                scope_id=record.impersonation_id,
                payload_json=payload,
            )
            session.commit()
            return payload


    def get_admin_overview(
        self,
        *,
        usage_window_days: int = 7,
        audit_window_minutes: int = 1440,
    ) -> dict[str, object]:
        now = self.now_factory()
        usage_since = now - timedelta(days=max(1, usage_window_days))
        audit_since = now - timedelta(minutes=max(1, audit_window_minutes))
        active_subscription_statuses = [
            SUBSCRIPTION_STATUS_TRIALING,
            SUBSCRIPTION_STATUS_ACTIVE,
            SUBSCRIPTION_STATUS_PAST_DUE,
            SUBSCRIPTION_STATUS_SUSPENDED,
        ]
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            accounts = repository.list_accounts(limit=None)
            sites = repository.list_sites(limit=None)
            subscriptions = repository.list_subscriptions(limit=None)
            usage_events = repository.list_usage_meter_events_for_admin(
                since=usage_since,
                limit=None,
            )
            active_membership_count = len(
                repository.list_account_memberships(
                    status=ACCOUNT_MEMBERSHIP_STATUS_ACTIVE,
                    limit=None,
                )
            )
            active_site_key_count = sum(
                repository.count_site_keys_by_site(
                    statuses=[SITE_API_KEY_STATUS_ACTIVE],
                ).values()
            )
            expiring_in_7_days = repository.count_subscriptions_expiring_by(
                before=now + timedelta(days=7),
                statuses=active_subscription_statuses,
            )
            expiring_in_30_days = repository.count_subscriptions_expiring_by(
                before=now + timedelta(days=30),
                statuses=active_subscription_statuses,
            )
            recent_audit = repository.summarize_service_audit_events(
                since=audit_since,
                limit=5,
            )
            recent_decisions = repository.summarize_commercial_decision_events(
                since=audit_since,
                limit=5,
            )

        def _serialize_overview_subscription(subscription: AccountSubscription) -> dict[str, object]:
            matched_account = next(
                (account for account in accounts if account.account_id == subscription.account_id),
                None,
            )
            matched_sites = [
                self._serialize_site(site)
                for site in sites
                if site.account_id == subscription.account_id
            ]
            return {
                "subscription": self._serialize_subscription(subscription),
                "expiry": self._serialize_expiry_state(subscription),
                "account": (
                    self._serialize_account(matched_account)
                    if matched_account is not None
                    else None
                ),
                "sites": matched_sites,
            }

        def _normalize_overview_datetime(value: datetime | None) -> datetime | None:
            if value is None:
                return None
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value

        plan_counts = Counter(subscription.plan_id for subscription in subscriptions if subscription.plan_id)
        status_counts = Counter(
            subscription.status for subscription in subscriptions if subscription.status
        )
        usage_totals = self._aggregate_meter_events(usage_events)
        expiring_subscription_items = [
            _serialize_overview_subscription(subscription)
            for subscription in sorted(
                [
                    subscription
                    for subscription in subscriptions
                    if subscription.status in active_subscription_statuses
                    and _normalize_overview_datetime(subscription.current_period_end_at)
                    is not None
                    and _normalize_overview_datetime(subscription.current_period_end_at)
                    <= now + timedelta(days=30)
                ],
                key=lambda item: (
                    _normalize_overview_datetime(item.current_period_end_at)
                    or datetime.max.replace(tzinfo=UTC)
                ),
            )[:5]
        ]
        attention_subscription_items = [
            _serialize_overview_subscription(subscription)
            for subscription in subscriptions
            if subscription.status in (SUBSCRIPTION_STATUS_PAST_DUE, SUBSCRIPTION_STATUS_SUSPENDED)
        ][:5]
        return {
            "generated_at": self._serialize_datetime(now),
            "counts": {
                "accounts_total": len(accounts),
                "memberships_active": active_membership_count,
                "sites_total": len(sites),
                "sites_active": sum(1 for site in sites if site.status == SITE_STATUS_ACTIVE),
                "subscriptions_total": len(subscriptions),
                "subscriptions_active": sum(
                    1
                    for subscription in subscriptions
                    if subscription.status in active_subscription_statuses
                ),
                "site_keys_active": active_site_key_count,
            },
            "expiring_subscriptions": {
                "within_7_days": expiring_in_7_days,
                "within_30_days": expiring_in_30_days,
                "within_7_days_expires_before": self._serialize_datetime(now + timedelta(days=7)),
                "within_30_days_expires_before": self._serialize_datetime(
                    now + timedelta(days=30)
                ),
                "items": expiring_subscription_items,
            },
            "attention_subscriptions": attention_subscription_items,
            "subscription_status_distribution": [
                {"status": status, "count": count}
                for status, count in sorted(status_counts.items())
            ],
            "plan_distribution": [
                {"plan_id": plan_id, "count": count}
                for plan_id, count in plan_counts.most_common()
            ],
            "recent_usage": {
                "window_days": max(1, usage_window_days),
                "event_count": len(usage_events),
                "totals": usage_totals,
            },
            "recent_audit_summary": {
                "window_minutes": max(1, audit_window_minutes),
                "items": recent_audit,
            },
            "recent_commercial_decision_summary": {
                "window_minutes": max(1, audit_window_minutes),
                "items": recent_decisions,
            },
        }


    def get_commercial_shadow_pricing_summary(
        self,
        *,
        window_days: int = 7,
        site_id: str | None = None,
        ability_family: str | None = None,
        limit: int = 5,
    ) -> dict[str, object]:
        now = self.now_factory()
        resolved_window_days = max(1, window_days)
        resolved_limit = max(1, limit)
        start_at = now - timedelta(days=resolved_window_days)

        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            runs = repository.list_run_records_for_admin(
                site_id=site_id,
                ability_family=ability_family,
                since=start_at,
                limit=None,
            )
            run_lookup = {str(run.run_id or ""): run for run in runs}
            provider_calls = repository.list_provider_call_records_for_admin(
                site_id=site_id,
                ability_family=ability_family,
                since=start_at,
                limit=None,
            )
            token_events = repository.list_usage_meter_events_for_admin(
                site_ids=[site_id] if site_id else None,
                ability_family=ability_family,
                meter_keys=["tokens_total"],
                since=start_at,
                limit=None,
            )

        items_by_key: dict[str, dict[str, object]] = {}

        def ensure_item(raw_ability_key: str, raw_ability_family: str) -> dict[str, object]:
            resolved_ability_family = str(raw_ability_family or "unknown").strip() or "unknown"
            resolved_ability_key = (
                str(raw_ability_key or "").strip()
                or f"{resolved_ability_family}/unclassified"
            )
            item = items_by_key.get(resolved_ability_key)
            if item is not None:
                return item
            tariff = self._resolve_shadow_tariff(
                ability_key=resolved_ability_key,
                ability_family=resolved_ability_family,
            )
            item = {
                "ability_key": resolved_ability_key,
                "ability_family": resolved_ability_family,
                "runs": 0,
                "provider_calls": 0,
                "tokens_total": 0.0,
                "provider_cost": 0.0,
                "shadow_revenue": 0.0,
                "margin_delta": 0.0,
                "tariff_class": tariff["tariff_class"],
                "tariff_source": tariff["tariff_source"],
                "base_run_price": tariff["base_run_price"],
                "per_1k_tokens_price": tariff["per_1k_tokens_price"],
            }
            items_by_key[resolved_ability_key] = item
            return item

        for run in runs:
            ensure_item(run.ability_name, run.ability_family)["runs"] += 1

        for provider_call in provider_calls:
            matched_run = run_lookup.get(str(provider_call.run_id or ""))
            item = ensure_item(
                getattr(matched_run, "ability_name", ""),
                getattr(matched_run, "ability_family", ""),
            )
            item["provider_calls"] = int(item["provider_calls"]) + 1
            item["provider_cost"] = round(
                float(item["provider_cost"]) + float(provider_call.cost or 0.0),
                6,
            )

        for event in token_events:
            matched_run = run_lookup.get(str(getattr(event, "run_id", "") or ""))
            item = ensure_item(
                getattr(matched_run, "ability_name", ""),
                getattr(matched_run, "ability_family", "")
                or str(getattr(event, "ability_family", "") or ""),
            )
            item["tokens_total"] = round(
                float(item["tokens_total"]) + float(getattr(event, "quantity", 0.0) or 0.0),
                6,
            )

        ability_items: list[dict[str, object]] = []
        family_map: dict[str, dict[str, object]] = {}
        for item in items_by_key.values():
            runs_total = int(item["runs"])
            tokens_total = float(item["tokens_total"])
            provider_cost = float(item["provider_cost"])
            shadow_revenue = round(
                runs_total * float(item["base_run_price"])
                + (tokens_total / 1000.0) * float(item["per_1k_tokens_price"]),
                6,
            )
            margin_delta = round(shadow_revenue - provider_cost, 6)
            serialized_item = {
                "ability_key": item["ability_key"],
                "ability_family": item["ability_family"],
                "runs": runs_total,
                "provider_calls": int(item["provider_calls"]),
                "tokens_total": round(tokens_total, 6),
                "provider_cost": round(provider_cost, 6),
                "shadow_revenue": shadow_revenue,
                "margin_delta": margin_delta,
                "tariff_class": item["tariff_class"],
                "tariff_source": item["tariff_source"],
            }
            ability_items.append(serialized_item)

            family_key = str(item["ability_family"])
            family_item = family_map.get(family_key)
            if family_item is None:
                family_tariff = self._resolve_shadow_tariff(
                    ability_key="",
                    ability_family=family_key,
                )
                family_item = {
                    "ability_family": family_key,
                    "runs": 0,
                    "provider_calls": 0,
                    "tokens_total": 0.0,
                    "provider_cost": 0.0,
                    "shadow_revenue": 0.0,
                    "margin_delta": 0.0,
                    "tariff_class": family_tariff["tariff_class"],
                    "tariff_source": family_tariff["tariff_source"],
                }
                family_map[family_key] = family_item
            family_item["runs"] = int(family_item["runs"]) + runs_total
            family_item["provider_calls"] = int(family_item["provider_calls"]) + int(
                item["provider_calls"]
            )
            family_item["tokens_total"] = round(
                float(family_item["tokens_total"]) + tokens_total,
                6,
            )
            family_item["provider_cost"] = round(
                float(family_item["provider_cost"]) + provider_cost,
                6,
            )
            family_item["shadow_revenue"] = round(
                float(family_item["shadow_revenue"]) + shadow_revenue,
                6,
            )
            family_item["margin_delta"] = round(
                float(family_item["margin_delta"]) + margin_delta,
                6,
            )

        ability_items.sort(
            key=lambda item: (
                float(item["provider_cost"]),
                int(item["runs"]),
                float(item["tokens_total"]),
            ),
            reverse=True,
        )
        family_items = sorted(
            family_map.values(),
            key=lambda item: (
                float(item["provider_cost"]),
                int(item["runs"]),
                float(item["tokens_total"]),
            ),
            reverse=True,
        )
        attention_items = [
            item
            for item in ability_items
            if str(item.get("tariff_source") or "") != "ability"
        ][:resolved_limit]

        return {
            "window": {
                "start_at": self._serialize_datetime(start_at),
                "end_at": self._serialize_datetime(now),
                "window_days": resolved_window_days,
            },
            "filters": {
                "site_id": site_id or "",
                "ability_family": ability_family or "",
                "limit": resolved_limit,
            },
            "tariff_version": SHADOW_PRICING_TARIFF_VERSION,
            "totals": {
                "runs": sum(int(item["runs"]) for item in ability_items),
                "provider_calls": sum(int(item["provider_calls"]) for item in ability_items),
                "tokens_total": round(
                    sum(float(item["tokens_total"]) for item in ability_items),
                    6,
                ),
                "provider_cost": round(
                    sum(float(item["provider_cost"]) for item in ability_items),
                    6,
                ),
                "shadow_revenue": round(
                    sum(float(item["shadow_revenue"]) for item in ability_items),
                    6,
                ),
                "margin_delta": round(
                    sum(float(item["margin_delta"]) for item in ability_items),
                    6,
                ),
            },
            "top_abilities": ability_items[:resolved_limit],
            "top_families": family_items[:resolved_limit],
            "attention_items": attention_items,
        }


    def list_admin_accounts(
        self,
        *,
        status: str | None = None,
        member_ref: str | None = None,
        expires_before: datetime | None = None,
        coverage_state: str | None = None,
        package_kind: str | None = None,
        top_plan_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            filtered_account_ids: set[str] | None = None
            if member_ref:
                memberships = repository.list_account_memberships(
                    member_ref=member_ref,
                    status=ACCOUNT_MEMBERSHIP_STATUS_ACTIVE,
                    limit=None,
                )
                filtered_account_ids = {membership.account_id for membership in memberships}
            if expires_before is not None:
                expiring_subscriptions = repository.list_subscriptions(
                    current_period_end_before=expires_before,
                    limit=None,
                )
                expiring_account_ids = {
                    subscription.account_id
                    for subscription in expiring_subscriptions
                    if subscription.account_id
                }
                filtered_account_ids = (
                    expiring_account_ids
                    if filtered_account_ids is None
                    else filtered_account_ids & expiring_account_ids
                )
            accounts = repository.list_accounts(
                status=status,
                account_ids=(
                    sorted(filtered_account_ids)
                    if filtered_account_ids is not None
                    else None
                ),
                limit=None if coverage_state or package_kind or top_plan_id else limit,
            )
            account_ids = [account.account_id for account in accounts]
            membership_counts = repository.count_account_memberships_by_account(
                account_ids=account_ids,
                status=ACCOUNT_MEMBERSHIP_STATUS_ACTIVE,
            )
            site_counts = repository.count_sites_by_account(account_ids=account_ids)
            subscription_counts = repository.count_subscriptions_by_account(
                account_ids=account_ids,
                statuses=[
                    SUBSCRIPTION_STATUS_TRIALING,
                    SUBSCRIPTION_STATUS_ACTIVE,
                    SUBSCRIPTION_STATUS_PAST_DUE,
                    SUBSCRIPTION_STATUS_SUSPENDED,
                ],
            )
            subscriptions = repository.list_subscriptions(account_ids=account_ids, limit=None)

        subscriptions_by_account: dict[str, list[AccountSubscription]] = defaultdict(list)
        for subscription in subscriptions:
            subscriptions_by_account[subscription.account_id].append(subscription)

        items = []
        for account in accounts:
            account_subscriptions = subscriptions_by_account.get(account.account_id, [])
            primary_subscription = self._select_primary_subscription(account_subscriptions)
            package_summary = self._build_subscription_package_summary(
                primary_subscription,
                site_count=int(site_counts.get(account.account_id, 0) or 0),
            )
            top_plan = Counter(
                subscription.plan_id
                for subscription in account_subscriptions
                if subscription.plan_id
            ).most_common(1)
            nearest_expiry = self._find_nearest_subscription_expiry(account_subscriptions)
            item = {
                "account": self._serialize_account(account),
                "member_count": membership_counts.get(account.account_id, 0),
                "site_count": site_counts.get(account.account_id, 0),
                "active_subscription_count": subscription_counts.get(account.account_id, 0),
                "top_plan_id": str(
                    (getattr(primary_subscription, "plan_id", "") or "")
                    or (top_plan[0][0] if top_plan else "")
                ).strip(),
                "nearest_expiry_at": self._serialize_datetime(nearest_expiry),
                "primary_subscription_id": str(
                    getattr(primary_subscription, "subscription_id", "") or ""
                ),
                "coverage_follow_up_required": bool(
                    package_summary.get("coverage_state") == "uncovered"
                    and int(site_counts.get(account.account_id, 0) or 0) > 0
                ),
                **package_summary,
            }
            if coverage_state and str(item.get("coverage_state") or "") != coverage_state:
                continue
            if package_kind and str(item.get("package_kind") or "") != package_kind:
                continue
            if top_plan_id and str(item.get("top_plan_id") or "") != top_plan_id:
                continue
            items.append(item)
        if limit > 0:
            items = items[:limit]
        return {
            "filters": {
                "status": status or "",
                "member_ref": member_ref or "",
                "expires_before": self._serialize_datetime(expires_before),
                "coverage_state": coverage_state or "",
                "package_kind": package_kind or "",
                "top_plan_id": top_plan_id or "",
                "limit": limit,
            },
            "items": items,
            "total": len(items),
        }


    def get_admin_account(self, account_id: str) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            account = repository.get_account(account_id)
            if account is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )
            memberships = repository.list_account_memberships(account_id=account_id, limit=None)
            sites = repository.list_sites(account_id=account_id, limit=None)
            subscriptions = repository.list_subscriptions(account_id=account_id, limit=None)

        return {
            "account": self._serialize_account(account),
            "memberships": [
                self._serialize_account_membership(
                    membership,
                    accessible_sites=sites,
                )
                for membership in memberships
            ],
            "sites": [self._serialize_site(site) for site in sites],
            "subscriptions": [
                {
                    "subscription": self._serialize_subscription(subscription),
                    "expiry": self._serialize_expiry_state(subscription),
                }
                for subscription in subscriptions
            ],
        }


    def get_admin_account_member_plan_coverage(self, account_id: str) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            account = repository.get_account(account_id)
            if account is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )
            memberships = repository.list_account_memberships(account_id=account_id, limit=None)
            sites = repository.list_sites(account_id=account_id, limit=None)
            subscriptions = repository.list_subscriptions(account_id=account_id, limit=None)

        sites_by_id = {
            str(site.site_id or ""): site
            for site in sites
            if str(site.site_id or "").strip()
        }
        latest_subscription_by_account = self._latest_subscription_map(subscriptions)

        members_payload: list[dict[str, object]] = []
        follow_up_site_ids: set[str] = set()
        covered_member_count = 0

        for membership in memberships:
            serialized_membership = self._serialize_account_membership(
                membership,
                accessible_sites=sites,
            )
            accessible_sites_payload: list[dict[str, object]] = []
            member_has_covered_site = False
            serialized_accessible_sites = list(serialized_membership.get("accessible_sites") or [])
            for accessible_site in serialized_accessible_sites:
                site_id = str(accessible_site.get("site_id") or "").strip()
                site = sites_by_id.get(site_id)
                subscription = latest_subscription_by_account.get(str(getattr(site, "account_id", "") or "").strip())
                covered = _subscription_counts_as_covered(subscription)
                if covered:
                    member_has_covered_site = True
                else:
                    follow_up_site_ids.add(site_id)
                plan_id = str(getattr(subscription, "plan_id", "") or "").strip() if subscription is not None else ""
                plan_version_id = str(getattr(subscription, "plan_version_id", "") or "").strip() if subscription is not None else ""
                package_summary = self._build_subscription_package_summary(subscription, site_count=1)
                accessible_sites_payload.append(
                    {
                        "site_id": site_id,
                        "site_name": str(getattr(site, "name", "") or accessible_site.get("name") or site_id),
                        "site_status": str(getattr(site, "status", "") or accessible_site.get("status") or ""),
                        "plan_id": plan_id,
                        "plan_version_id": plan_version_id,
                        "package_alias": str(package_summary.get("package_alias") or ""),
                        "display_package_label": str(package_summary.get("display_package_label") or ""),
                        "package_kind": str(package_summary.get("package_kind") or ""),
                        "coverage_state": str(package_summary.get("coverage_state") or ""),
                        "covered": covered,
                        "coverage": {
                            "covered_by_subscription_id": str(getattr(subscription, "subscription_id", "") or ""),
                            "status": str(getattr(subscription, "status", "") or ""),
                            "package_kind": str(package_summary.get("package_kind") or ""),
                            "coverage_state": str(package_summary.get("coverage_state") or ""),
                        },
                    }
                )

            if member_has_covered_site:
                covered_member_count += 1

            members_payload.append(
                {
                    "member_ref": str(serialized_membership.get("member_ref") or ""),
                    "email": str(serialized_membership.get("email") or ""),
                    "identity_type": str(
                        serialized_membership.get("identity_type")
                        or IDENTITY_TYPE_USER_ADMIN
                    ),
                    "allowed_actions": [
                        str(action)
                        for action in list(
                            serialized_membership.get("allowed_actions") or []
                        )
                        if str(action).strip()
                    ],
                    "role": str(serialized_membership.get("role") or ""),
                    "status": str(serialized_membership.get("status") or ""),
                    "covered_site_count": sum(1 for site in accessible_sites_payload if bool(site.get("covered"))),
                    "sites_needing_follow_up_count": sum(1 for site in accessible_sites_payload if not bool(site.get("covered"))),
                    "accessible_sites": accessible_sites_payload,
                }
            )

        return {
            "account": self._serialize_account(account),
            "summary": {
                "member_count": len(members_payload),
                "covered_member_count": covered_member_count,
                "sites_needing_follow_up_count": len([site_id for site_id in follow_up_site_ids if site_id]),
            },
            "members": members_payload,
        }


    def list_admin_members_queue(
        self,
        *,
        member_ref: str | None = None,
        status: str | None = None,
        account_id: str | None = None,
        has_coverage_follow_up: bool | None = None,
        disabled: bool | None = None,
        dev_baseline: bool | None = None,
        never_logged_in: bool = False,
        limit: int = 100,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            memberships = repository.list_account_memberships(limit=None)
            sites = repository.list_sites(limit=None)
            subscriptions = repository.list_subscriptions(limit=None)
            accounts = repository.list_accounts(limit=None)

        accounts_by_id = {
            str(account.account_id or ""): account
            for account in accounts
            if str(account.account_id or "").strip()
        }
        sites_by_account: dict[str, list[Site]] = defaultdict(list)
        for site in sites:
            site_account_id = str(getattr(site, "account_id", "") or "").strip()
            if site_account_id:
                sites_by_account[site_account_id].append(site)

        latest_subscription_by_account = self._latest_subscription_map(subscriptions)

        member_items: dict[str, dict[str, object]] = {}
        for membership in memberships:
            serialized = self._serialize_account_membership(
                membership,
                accessible_sites=sites_by_account.get(str(getattr(membership, "account_id", "") or "").strip(), []),
            )
            current_member_ref = str(serialized.get("member_ref") or "").strip()
            if not current_member_ref:
                continue
            if member_ref and member_ref not in current_member_ref:
                continue
            current_account_id = str(serialized.get("account_id") or "").strip()
            if account_id and current_account_id != account_id:
                continue

            bucket = member_items.setdefault(
                current_member_ref,
                {
                    "member_ref": current_member_ref,
                    "email": str(serialized.get("email") or ""),
                    "allowed_action_set": set(),
                    "status_set": set(),
                    "invite_state_set": set(),
                    "accounts": [],
                    "accessible_site_count": 0,
                    "sites_needing_follow_up_count": 0,
                    "last_login_at": "",
                    "dev_baseline": False,
                    "covered_subscription_ids": set(),
                },
            )
            for action in list(serialized.get("allowed_actions") or []):
                normalized_action = str(action).strip()
                if normalized_action:
                    bucket["allowed_action_set"].add(normalized_action)
            bucket["status_set"].add(str(serialized.get("status") or ""))
            if str(serialized.get("invite_state") or "").strip():
                bucket["invite_state_set"].add(str(serialized.get("invite_state") or ""))

            last_login_at = str(serialized.get("last_login_at") or "")
            if last_login_at and last_login_at > str(bucket.get("last_login_at") or ""):
                bucket["last_login_at"] = last_login_at

            accessible_sites = list(serialized.get("accessible_sites") or [])
            account_site_count = 0
            account_covered_site_count = 0
            account_sites_needing_follow_up_count = 0
            highlighted_follow_up_site_id = ""
            highlighted_subscription_id = ""
            for accessible_site in accessible_sites:
                site_id = str(accessible_site.get("site_id") or "").strip()
                if not site_id:
                    continue
                account_site_count += 1
                bucket["accessible_site_count"] += 1
                subscription = latest_subscription_by_account.get(current_account_id)
                covered = _subscription_counts_as_covered(subscription)
                plan_value = str(getattr(subscription, "plan_id", "") or "").strip() if subscription is not None else ""
                if plan_value:
                    if plan_value == "plan_dev_unlimited":
                        bucket["dev_baseline"] = True
                if covered:
                    account_covered_site_count += 1
                    subscription_id = str(getattr(subscription, "subscription_id", "") or "").strip()
                    if subscription_id:
                        bucket["covered_subscription_ids"].add(subscription_id)
                else:
                    account_sites_needing_follow_up_count += 1
                    bucket["sites_needing_follow_up_count"] += 1
                    if not highlighted_follow_up_site_id:
                        highlighted_follow_up_site_id = site_id
                        highlighted_subscription_id = str(getattr(subscription, "subscription_id", "") or "")

            bucket["accounts"].append(
                {
                    "account_id": current_account_id,
                    "account_name": str(getattr(accounts_by_id.get(current_account_id), "name", "") or current_account_id),
                    "site_count": account_site_count,
                    "covered_site_count": account_covered_site_count,
                    "sites_needing_follow_up_count": account_sites_needing_follow_up_count,
                    "highlight_site_id": highlighted_follow_up_site_id,
                    "highlight_subscription_id": highlighted_subscription_id,
                }
            )

        items: list[dict[str, object]] = []
        members_needing_coverage_follow_up = 0
        never_logged_in_members = 0
        disabled_mapped_members = 0
        members_on_dev_baseline = 0

        for item in member_items.values():
            resolved_status = _aggregate_membership_status(set(item.get("status_set") or set()))
            resolved_invite_state = "accepted"
            invite_states = set(item.get("invite_state_set") or set())
            if "pending" in invite_states:
                resolved_invite_state = "pending"
            elif "sent" in invite_states:
                resolved_invite_state = "sent"
            elif invite_states:
                resolved_invite_state = next(iter(invite_states))

            accessible_site_count = int(item.get("accessible_site_count") or 0)
            sites_needing_follow_up_count = int(item.get("sites_needing_follow_up_count") or 0)
            dev_baseline_member = bool(item.get("dev_baseline"))
            has_coverage_follow_up_value = sites_needing_follow_up_count > 0
            never_logged_in_member = not str(item.get("last_login_at") or "")
            disabled_mapped = resolved_status == "disabled" and accessible_site_count > 0
            primary_account = None
            for account_summary in list(item.get("accounts") or []):
                if int(account_summary.get("sites_needing_follow_up_count") or 0) > 0:
                    primary_account = account_summary
                    break
            if primary_account is None:
                accounts_list = list(item.get("accounts") or [])
                primary_account = accounts_list[0] if accounts_list else None

            primary_account_id = str((primary_account or {}).get("account_id") or "")
            primary_follow_up_site_id = str((primary_account or {}).get("highlight_site_id") or "")
            primary_impersonation_href = ""

            covered_subscription_ids = sorted(
                {
                    str(value or "").strip()
                    for value in item.get("covered_subscription_ids") or set()
                    if str(value or "").strip()
                }
            )
            single_covered_subscription_id = ""
            if len(covered_subscription_ids) == 1 and not dev_baseline_member:
                single_covered_subscription_id = covered_subscription_ids[0]

            if status and resolved_status != status:
                continue
            if has_coverage_follow_up is True and not has_coverage_follow_up_value:
                continue
            if has_coverage_follow_up is False and has_coverage_follow_up_value:
                continue
            if disabled is True and not disabled_mapped:
                continue
            if disabled is False and disabled_mapped:
                continue
            if dev_baseline is True and not dev_baseline_member:
                continue
            if dev_baseline is False and dev_baseline_member:
                continue
            if never_logged_in and not never_logged_in_member:
                continue

            if has_coverage_follow_up_value:
                members_needing_coverage_follow_up += 1
            if never_logged_in_member:
                never_logged_in_members += 1
            if disabled_mapped:
                disabled_mapped_members += 1
            if dev_baseline_member:
                members_on_dev_baseline += 1

            items.append(
                {
                    "member_ref": str(item.get("member_ref") or ""),
                    "email": str(item.get("email") or ""),
                    "identity_type": IDENTITY_TYPE_USER_ADMIN,
                    "status": resolved_status,
                    "invite_state": resolved_invite_state,
                    "allowed_actions": sorted(
                        {
                            value
                            for value in item.get("allowed_action_set") or set()
                            if value
                        }
                    ),
                    "account_count": len(item.get("accounts") or []),
                    "accessible_site_count": accessible_site_count,
                    "sites_needing_follow_up_count": sites_needing_follow_up_count,
                    "last_login_at": str(item.get("last_login_at") or ""),
                    "accounts": list(item.get("accounts") or []),
                    "dev_baseline": dev_baseline_member,
                    "has_coverage_follow_up": has_coverage_follow_up_value,
                    "never_logged_in": never_logged_in_member,
                    "disabled_mapped": disabled_mapped,
                    "primary_account_id": primary_account_id,
                    "primary_follow_up_site_id": primary_follow_up_site_id,
                    "primary_impersonation_href": primary_impersonation_href,
                    "single_covered_subscription_id": single_covered_subscription_id,
                }
            )

        items.sort(
            key=lambda item: (
                0 if bool(item.get("has_coverage_follow_up")) else 1,
                0 if bool(item.get("disabled_mapped")) else 1,
                0 if bool(item.get("never_logged_in")) else 1,
                0 if bool(item.get("dev_baseline")) else 1,
                str(item.get("member_ref") or ""),
            )
        )
        bounded_items = items[: max(1, int(limit or 0))]

        return {
            "filters": {
                "member_ref": member_ref or "",
                "status": status or "",
                "account_id": account_id or "",
                "has_coverage_follow_up": has_coverage_follow_up,
                "disabled": disabled,
                "dev_baseline": dev_baseline,
                "never_logged_in": bool(never_logged_in),
                "limit": limit,
            },
            "summary": {
                "total": len(items),
                "members_needing_coverage_follow_up": members_needing_coverage_follow_up,
                "never_logged_in_members": never_logged_in_members,
                "disabled_mapped_members": disabled_mapped_members,
                "members_on_dev_baseline": members_on_dev_baseline,
            },
            "items": bounded_items,
        }


    def list_admin_account_members(
        self,
        *,
        account_id: str,
        status: str | None = None,
        invite_state: str | None = None,
        delivery_status: str | None = None,
        never_logged_in: bool = False,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            account = repository.get_account(account_id)
            if account is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )
            memberships = repository.list_account_memberships(account_id=account_id, limit=None)
            sites = repository.list_sites(account_id=account_id, limit=None)

        items = []
        for membership in memberships:
            serialized = self._serialize_account_membership(
                membership,
                accessible_sites=sites,
            )
            if status and serialized["status"] != status:
                continue
            if invite_state and serialized["invite_state"] != invite_state:
                continue
            if delivery_status and serialized["last_delivery_status"] != delivery_status:
                continue
            if never_logged_in and serialized["last_login_at"]:
                continue
            items.append(serialized)

        return {
            "account": self._serialize_account(account),
            "filters": {
                "status": status or "",
                "invite_state": invite_state or "",
                "delivery_status": delivery_status or "",
                "never_logged_in": bool(never_logged_in),
            },
            "items": items,
        }


    def get_admin_account_member(
        self,
        *,
        account_id: str,
        member_ref: str,
    ) -> dict[str, object]:
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
                member_ref=member_ref,
            )
            if membership is None:
                raise CommercialNotFoundError(
                    "service.account_membership_not_found",
                    f"member '{member_ref}' was not found in account '{account_id}'",
                )
            sites = repository.list_sites(account_id=account_id, limit=None)
        return {
            "account": self._serialize_account(account),
            "membership": self._serialize_account_membership(
                membership,
                accessible_sites=sites,
            ),
        }


    def list_admin_platform_admin_identities(
        self,
        *,
        status: str | None = None,
        role: str | None = None,
        provider: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            identities = repository.list_platform_admin_identities(
                status=status,
                role=role,
                provider=provider,
                limit=limit,
            )
        return {
            "filters": {
                "status": status or "",
                "role": role or "",
                "provider": provider or "",
                "limit": limit,
            },
            "items": [self._serialize_platform_admin_identity(identity) for identity in identities],
        }


    def list_admin_platform_impersonations(
        self,
        *,
        status: str | None = None,
        platform_admin_ref: str | None = None,
        member_ref: str | None = None,
        account_id: str | None = None,
        site_id: str | None = None,
        active_only: bool = False,
        limit: int = 100,
    ) -> dict[str, object]:
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            records = repository.list_platform_impersonations(
                status=status,
                platform_admin_ref=platform_admin_ref,
                member_ref=member_ref,
                account_id=account_id,
                site_id=site_id,
                active_only=active_only,
                now=now,
                limit=limit,
            )
        return {
            "filters": {
                "status": status or "",
                "platform_admin_ref": platform_admin_ref or "",
                "member_ref": member_ref or "",
                "account_id": account_id or "",
                "site_id": site_id or "",
                "active_only": bool(active_only),
                "limit": limit,
            },
            "items": [self._serialize_platform_impersonation(record) for record in records],
        }


    def _serialize_platform_admin_identity(self, identity: object) -> dict[str, object]:
        role = str(getattr(identity, "role", "") or "")
        return {
            "admin_ref": str(getattr(identity, "admin_ref", "") or ""),
            "provider": str(getattr(identity, "provider", "") or ""),
            "external_subject": str(getattr(identity, "external_subject", "") or ""),
            "email": str(getattr(identity, "email", "") or ""),
            "identity_type": IDENTITY_TYPE_PLATFORM_ADMIN,
            "role": role,
            "capabilities": _platform_capability_flags(role),
            "status": str(getattr(identity, "status", "") or ""),
            "metadata": getattr(identity, "metadata_json", None) or {},
            "created_at": self._serialize_datetime(getattr(identity, "created_at", None)),
            "updated_at": self._serialize_datetime(getattr(identity, "updated_at", None)),
        }


    def _serialize_platform_impersonation(
        self,
        record: PlatformImpersonationSession | object,
    ) -> dict[str, object]:
        return {
            "impersonation_id": str(getattr(record, "impersonation_id", "") or ""),
            "platform_admin_ref": str(getattr(record, "platform_admin_ref", "") or ""),
            "platform_role": str(getattr(record, "platform_role", "") or ""),
            "member_ref": str(getattr(record, "member_ref", "") or ""),
            "account_id": str(getattr(record, "account_id", "") or ""),
            "site_id": str(getattr(record, "site_id", "") or ""),
            "reason_code": str(getattr(record, "reason_code", "") or ""),
            "reason_text": str(getattr(record, "reason_text", "") or ""),
            "read_only": bool(getattr(record, "read_only", True)),
            "status": str(getattr(record, "status", "") or ""),
            "started_at": self._serialize_datetime(getattr(record, "started_at", None)),
            "expires_at": self._serialize_datetime(getattr(record, "expires_at", None)),
            "ended_at": self._serialize_datetime(getattr(record, "ended_at", None)),
            "ended_reason": str(getattr(record, "ended_reason", "") or ""),
            "metadata": getattr(record, "metadata_json", None) or {},
            "created_at": self._serialize_datetime(getattr(record, "created_at", None)),
            "updated_at": self._serialize_datetime(getattr(record, "updated_at", None)),
        }


    def _resolve_shadow_tariff(
        self,
        *,
        ability_key: str,
        ability_family: str,
    ) -> dict[str, object]:
        normalized_ability_key = str(ability_key or "").strip()
        normalized_ability_family = str(ability_family or "").strip()
        ability_tariff = SHADOW_PRICING_TARIFF_REGISTRY["ability"].get(normalized_ability_key)
        if ability_tariff is not None:
            return {
                "tariff_class": str(ability_tariff.get("tariff_class") or "medium"),
                "tariff_source": "ability",
                "base_run_price": round(float(ability_tariff.get("base_run_price") or 0.0), 6),
                "per_1k_tokens_price": round(
                    float(ability_tariff.get("per_1k_tokens_price") or 0.0),
                    6,
                ),
            }
        family_tariff = SHADOW_PRICING_TARIFF_REGISTRY["ability_family"].get(
            normalized_ability_family
        )
        if family_tariff is not None:
            return {
                "tariff_class": str(family_tariff.get("tariff_class") or "medium"),
                "tariff_source": "ability_family",
                "base_run_price": round(float(family_tariff.get("base_run_price") or 0.0), 6),
                "per_1k_tokens_price": round(
                    float(family_tariff.get("per_1k_tokens_price") or 0.0),
                    6,
                ),
            }
        return {
            "tariff_class": "unclassified",
            "tariff_source": "unclassified",
            "base_run_price": 0.0,
            "per_1k_tokens_price": 0.0,
        }
