"""Commercial service: admin and platform operations mixin."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.db import get_session
from app.core.models import (
    ACCOUNT_MEMBERSHIP_STATUS_ACTIVE,
    PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
    PLATFORM_ADMIN_STATUS_ACTIVE,
    SITE_API_KEY_STATUS_ACTIVE,
    SITE_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_PAST_DUE,
    SUBSCRIPTION_STATUS_SUSPENDED,
    SUBSCRIPTION_STATUS_TRIALING,
    AccountSubscription,
)
from app.domain.commercial.errors import (
    CommercialNotFoundError,
    CommercialPermissionError,
)
from app.domain.commercial.mixins._audit_mixin import (
    IDENTITY_TYPE_PLATFORM_ADMIN,
    IDENTITY_TYPE_USER_ADMIN,
    CommercialServiceAuditMixin,
    ServiceAuditContext,
    _canonicalize_platform_admin_role_for_write,
    _platform_capability_flags,
    _subscription_counts_as_covered,
)
from app.domain.commercial.mixins._billing_mixin import (
    SHADOW_PRICING_TARIFF_REGISTRY,
    SHADOW_PRICING_TARIFF_VERSION,
)


class CommercialServiceAdminMixin(CommercialServiceAuditMixin):

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
            payload = cast(Any, self)._serialize_platform_admin_identity(identity)
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
            return cast(Any, self)._serialize_platform_admin_identity(identity)


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
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            identity = repository.get_platform_admin_identity(admin_ref=normalized_admin_ref)
            if identity is None:
                raise CommercialNotFoundError(
                    "service.platform_admin_not_found",
                    f"platform admin '{normalized_admin_ref}' was not found",
                )
            payload = cast(Any, self)._serialize_platform_admin_identity(identity)
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
                cast(Any, self)._serialize_site(site)
                for site in sites
                if site.account_id == subscription.account_id
            ]
            return {
                "subscription": cast(Any, self)._serialize_subscription(subscription),
                "expiry": cast(Any, self)._serialize_expiry_state(subscription),
                "account": (
                    cast(Any, self)._serialize_account(matched_account)
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

        def _expires_within_attention_window(subscription: AccountSubscription) -> bool:
            expires_at = _normalize_overview_datetime(subscription.current_period_end_at)
            return (
                subscription.status in active_subscription_statuses
                and expires_at is not None
                and expires_at <= now + timedelta(days=30)
            )

        plan_counts = Counter(subscription.plan_id for subscription in subscriptions if subscription.plan_id)
        status_counts = Counter(
            subscription.status for subscription in subscriptions if subscription.status
        )
        usage_totals = cast(Any, self)._aggregate_meter_events(usage_events)
        expiring_subscription_items = [
            _serialize_overview_subscription(subscription)
            for subscription in sorted(
                [
                    subscription
                    for subscription in subscriptions
                    if _expires_within_attention_window(subscription)
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
            run_item = ensure_item(run.ability_name, run.ability_family)
            run_item["runs"] = self._coerce_int(run_item.get("runs")) + 1

        for provider_call in provider_calls:
            matched_run = run_lookup.get(str(provider_call.run_id or ""))
            item = ensure_item(
                getattr(matched_run, "ability_name", ""),
                getattr(matched_run, "ability_family", ""),
            )
            item["provider_calls"] = self._coerce_int(item.get("provider_calls")) + 1
            item["provider_cost"] = round(
                self._coerce_float(item.get("provider_cost"))
                + self._coerce_float(provider_call.cost),
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
                self._coerce_float(item.get("tokens_total"))
                + self._coerce_float(getattr(event, "quantity", 0.0)),
                6,
            )

        ability_items: list[dict[str, object]] = []
        family_map: dict[str, dict[str, object]] = {}
        for item in items_by_key.values():
            runs_total = self._coerce_int(item.get("runs"))
            tokens_total = self._coerce_float(item.get("tokens_total"))
            provider_cost = self._coerce_float(item.get("provider_cost"))
            shadow_revenue = round(
                runs_total * self._coerce_float(item.get("base_run_price"))
                + (tokens_total / 1000.0)
                * self._coerce_float(item.get("per_1k_tokens_price")),
                6,
            )
            margin_delta = round(shadow_revenue - provider_cost, 6)
            serialized_item = {
                "ability_key": item["ability_key"],
                "ability_family": item["ability_family"],
                "runs": runs_total,
                    "provider_calls": self._coerce_int(item.get("provider_calls")),
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
            family_item["runs"] = self._coerce_int(family_item.get("runs")) + runs_total
            family_item["provider_calls"] = self._coerce_int(
                family_item.get("provider_calls")
            ) + self._coerce_int(
                item.get("provider_calls")
            )
            family_item["tokens_total"] = round(
                self._coerce_float(family_item.get("tokens_total")) + tokens_total,
                6,
            )
            family_item["provider_cost"] = round(
                self._coerce_float(family_item.get("provider_cost")) + provider_cost,
                6,
            )
            family_item["shadow_revenue"] = round(
                self._coerce_float(family_item.get("shadow_revenue")) + shadow_revenue,
                6,
            )
            family_item["margin_delta"] = round(
                self._coerce_float(family_item.get("margin_delta")) + margin_delta,
                6,
            )

        ability_items.sort(
            key=lambda item: (
                self._coerce_float(item.get("provider_cost")),
                self._coerce_int(item.get("runs")),
                self._coerce_float(item.get("tokens_total")),
            ),
            reverse=True,
        )
        family_items = sorted(
            family_map.values(),
            key=lambda item: (
                self._coerce_float(item.get("provider_cost")),
                self._coerce_int(item.get("runs")),
                self._coerce_float(item.get("tokens_total")),
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
                "runs": sum(self._coerce_int(item.get("runs")) for item in ability_items),
                "provider_calls": sum(
                    self._coerce_int(item.get("provider_calls")) for item in ability_items
                ),
                "tokens_total": round(
                    sum(self._coerce_float(item.get("tokens_total")) for item in ability_items),
                    6,
                ),
                "provider_cost": round(
                    sum(self._coerce_float(item.get("provider_cost")) for item in ability_items),
                    6,
                ),
                "shadow_revenue": round(
                    sum(self._coerce_float(item.get("shadow_revenue")) for item in ability_items),
                    6,
                ),
                "margin_delta": round(
                    sum(self._coerce_float(item.get("margin_delta")) for item in ability_items),
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
            service = cast(Any, self)
            primary_subscription = service._select_primary_subscription(account_subscriptions)
            package_summary = service._build_subscription_package_summary(
                primary_subscription,
                site_count=int(site_counts.get(account.account_id, 0) or 0),
            )
            top_plan = Counter(
                subscription.plan_id
                for subscription in account_subscriptions
                if subscription.plan_id
            ).most_common(1)
            nearest_expiry = service._find_nearest_subscription_expiry(account_subscriptions)
            item = {
                "account": service._serialize_account(account),
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
            "account": cast(Any, self)._serialize_account(account),
            "memberships": [
                cast(Any, self)._serialize_account_membership(
                    membership,
                    accessible_sites=sites,
                )
                for membership in memberships
            ],
            "sites": [cast(Any, self)._serialize_site(site) for site in sites],
            "subscriptions": [
                {
                    "subscription": cast(Any, self)._serialize_subscription(subscription),
                    "expiry": cast(Any, self)._serialize_expiry_state(subscription),
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
        service = cast(Any, self)
        latest_subscription_by_account = service._latest_subscription_map(subscriptions)

        members_payload: list[dict[str, object]] = []
        follow_up_site_ids: set[str] = set()
        covered_member_count = 0

        for membership in memberships:
            serialized_membership = service._serialize_account_membership(
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
                package_summary = service._build_subscription_package_summary(
                    subscription,
                    site_count=1,
                )
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
            "account": service._serialize_account(account),
            "summary": {
                "member_count": len(members_payload),
                "covered_member_count": covered_member_count,
                "sites_needing_follow_up_count": len([site_id for site_id in follow_up_site_ids if site_id]),
            },
            "members": members_payload,
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
            serialized = cast(Any, self)._serialize_account_membership(
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
            "account": cast(Any, self)._serialize_account(account),
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
            "account": cast(Any, self)._serialize_account(account),
            "membership": cast(Any, self)._serialize_account_membership(
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
            "items": [
                cast(Any, self)._serialize_platform_admin_identity(identity)
                for identity in identities
            ],
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
