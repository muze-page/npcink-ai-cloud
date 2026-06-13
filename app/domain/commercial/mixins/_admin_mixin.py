"""Commercial service: admin and platform operations mixin."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.db import get_session
from app.core.models import (
    ACCOUNT_STATUS_ACTIVE,
    CREDIT_LEDGER_EVENT_CONSUME,
    PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
    PLATFORM_ADMIN_STATUS_ACTIVE,
    SITE_ADMIN_STATUS_ACTIVE,
    SITE_API_KEY_STATUS_ACTIVE,
    SITE_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_PAST_DUE,
    SUBSCRIPTION_STATUS_SUSPENDED,
    SUBSCRIPTION_STATUS_TRIALING,
    AccountSubscription,
)
from app.domain.commercial.audit_context import ServiceAuditContext
from app.domain.commercial.credits import (
    AI_CREDIT_RATE_VERSION,
    build_credit_breakdown_from_ledger,
)
from app.domain.commercial.errors import (
    CommercialNotFoundError,
    CommercialPermissionError,
)
from app.domain.commercial.identity import (
    IDENTITY_TYPE_PLATFORM_ADMIN,
    _canonicalize_platform_admin_role_for_write,
    _platform_capability_flags,
)
from app.domain.commercial.mixins._audit_mixin import CommercialServiceAuditMixin
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
            accounts_total = repository.count_accounts()
            site_admins_active = repository.count_site_admin_identities(
                status=SITE_ADMIN_STATUS_ACTIVE
            )
            sites_total = repository.count_sites()
            sites_active = repository.count_sites(status=SITE_STATUS_ACTIVE)
            subscriptions_total = repository.count_subscriptions()
            subscriptions_active = repository.count_subscriptions(
                statuses=active_subscription_statuses
            )
            active_site_key_count = repository.count_site_keys_total(
                statuses=[SITE_API_KEY_STATUS_ACTIVE]
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
            status_counts = repository.summarize_subscription_status_counts()
            plan_counts = repository.summarize_subscription_plan_counts()
            usage_summary = repository.summarize_usage_meter_events_for_admin(since=usage_since)
            usage_meter_events = repository.list_usage_meter_events_for_admin(
                since=usage_since,
                limit=None,
            )
            credit_ledger_entries = repository.list_credit_ledger_entries(
                event_types=[CREDIT_LEDGER_EVENT_CONSUME],
                since=usage_since,
                until=now,
                limit=None,
            )
            knowledge_index_usage = repository.summarize_site_knowledge_index_usage(
                since=usage_since,
                until=now,
            )
            expiring_subscriptions = repository.list_subscriptions(
                statuses=active_subscription_statuses,
                current_period_end_before=now + timedelta(days=30),
                limit=None,
            )
            attention_subscriptions = (
                repository.list_subscriptions(status=SUBSCRIPTION_STATUS_PAST_DUE, limit=5)
                + repository.list_subscriptions(status=SUBSCRIPTION_STATUS_SUSPENDED, limit=5)
            )
            detail_account_ids = sorted(
                {
                    subscription.account_id
                    for subscription in [*expiring_subscriptions, *attention_subscriptions]
                    if subscription.account_id
                }
            )
            accounts = (
                repository.list_accounts(account_ids=detail_account_ids, limit=None)
                if detail_account_ids
                else []
            )
            sites = (
                repository.list_sites(account_ids=detail_account_ids, limit=None)
                if detail_account_ids
                else []
            )

        def _serialize_overview_subscription(
            subscription: AccountSubscription,
        ) -> dict[str, object]:
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

        expiring_subscription_items = [
            _serialize_overview_subscription(subscription)
            for subscription in sorted(
                [
                    subscription
                    for subscription in expiring_subscriptions
                    if _expires_within_attention_window(subscription)
                ],
                key=lambda item: (
                    _normalize_overview_datetime(item.current_period_end_at)
                    or datetime.max.replace(tzinfo=UTC)
                ),
            )[:5]
        ]
        usage_totals = usage_summary.get("totals")
        usage_event_count = int(cast(Any, usage_summary.get("event_count") or 0))
        platform_credit_summary = self._build_platform_credit_summary(
            meter_events=usage_meter_events,
            ledger_entries=credit_ledger_entries,
            window_days=max(1, usage_window_days),
            start_at=usage_since,
            end_at=now,
            knowledge_index_usage=knowledge_index_usage,
        )
        attention_subscription_items = [
            _serialize_overview_subscription(subscription)
            for subscription in attention_subscriptions
            if subscription.status in (SUBSCRIPTION_STATUS_PAST_DUE, SUBSCRIPTION_STATUS_SUSPENDED)
        ][:5]
        return {
            "generated_at": self._serialize_datetime(now),
            "counts": {
                "accounts_total": accounts_total,
                "site_admins_active": site_admins_active,
                "sites_total": sites_total,
                "sites_active": sites_active,
                "subscriptions_total": subscriptions_total,
                "subscriptions_active": subscriptions_active,
                "site_keys_active": active_site_key_count,
            },
            "expiring_subscriptions": {
                "within_7_days": expiring_in_7_days,
                "within_30_days": expiring_in_30_days,
                "within_7_days_expires_before": self._serialize_datetime(now + timedelta(days=7)),
                "within_30_days_expires_before": self._serialize_datetime(now + timedelta(days=30)),
                "items": expiring_subscription_items,
            },
            "attention_subscriptions": attention_subscription_items,
            "subscription_status_distribution": [
                {"status": status, "count": count}
                for status, count in sorted(status_counts.items())
            ],
            "plan_distribution": [
                {"plan_id": plan_id, "count": count} for plan_id, count in plan_counts.items()
            ],
            "recent_usage": {
                "window_days": max(1, usage_window_days),
                "event_count": usage_event_count,
                "totals": usage_totals if isinstance(usage_totals, dict) else {},
            },
            "platform_credit_summary": platform_credit_summary,
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
                str(raw_ability_key or "").strip() or f"{resolved_ability_family}/unclassified"
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
                + (tokens_total / 1000.0) * self._coerce_float(item.get("per_1k_tokens_price")),
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
            ) + self._coerce_int(item.get("provider_calls"))
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
            item for item in ability_items if str(item.get("tariff_source") or "") != "ability"
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
        expires_before: datetime | None = None,
        coverage_state: str | None = None,
        package_kind: str | None = None,
        top_plan_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            filtered_account_ids: set[str] | None = None
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
                    sorted(filtered_account_ids) if filtered_account_ids is not None else None
                ),
                limit=None if coverage_state or package_kind or top_plan_id else limit,
            )
            account_ids = [account.account_id for account in accounts]
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
            sites = repository.list_sites(account_id=account_id, limit=None)
            subscriptions = repository.list_subscriptions(account_id=account_id, limit=None)
            active_key_counts = repository.count_site_keys_by_site(
                site_ids=[site.site_id for site in sites],
                statuses=[SITE_API_KEY_STATUS_ACTIVE],
            )

        return {
            "account": cast(Any, self)._serialize_account(account),
            "sites": [cast(Any, self)._serialize_site(site) for site in sites],
            "subscriptions": [
                {
                    "subscription": cast(Any, self)._serialize_subscription(subscription),
                    "expiry": cast(Any, self)._serialize_expiry_state(subscription),
                }
                for subscription in subscriptions
            ],
            "trial_readiness": cast(Any, self)._build_account_trial_readiness_summary(
                account=account,
                sites=sites,
                subscriptions=subscriptions,
                active_key_counts=active_key_counts,
            ),
        }

    def get_admin_account_quota_summary(self, account_id: str) -> dict[str, object]:
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            account = repository.get_account(account_id)
            if account is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )
            sites = repository.list_sites(account_id=account_id, limit=None)
            site_ids = [str(site.site_id or "") for site in sites if str(site.site_id or "")]
            subscriptions = repository.list_subscriptions(account_id=account_id, limit=None)
            primary_subscription = cast(Any, self)._select_primary_subscription(subscriptions)
            plan_version = (
                repository.get_plan_version(primary_subscription.plan_version_id)
                if primary_subscription is not None and primary_subscription.plan_version_id
                else None
            )
            snapshot = repository.get_active_entitlement_snapshot(
                account_id,
                subscription_id=(
                    primary_subscription.subscription_id
                    if primary_subscription is not None
                    else None
                ),
            )
            period_start_at, period_end_at = cast(Any, self)._resolve_period(
                primary_subscription,
                now,
            )
            meter_events = [
                event
                for event in repository.list_usage_meter_events_for_admin(
                    account_ids=[account_id],
                    since=period_start_at,
                    limit=None,
                )
                if (
                    primary_subscription is None
                    or str(getattr(event, "subscription_id", "") or "")
                    == primary_subscription.subscription_id
                )
                and (
                    period_end_at is None
                    or (
                        (event_created_at := getattr(event, "created_at", None)) is not None
                        and cast(Any, self)._normalize_datetime(event_created_at) <= period_end_at
                    )
                )
            ]
            credit_ledger_entries = repository.list_credit_ledger_entries(
                account_ids=[account_id],
                subscription_id=(
                    primary_subscription.subscription_id
                    if primary_subscription is not None
                    else None
                ),
                event_types=[CREDIT_LEDGER_EVENT_CONSUME],
                since=period_start_at,
                until=period_end_at,
                limit=None,
            )
            totals = cast(Any, self)._aggregate_meter_events(meter_events)
            budgets = (
                cast(Any, self)._normalize_budgets(snapshot.budgets_json)
                if snapshot is not None
                else cast(Any, self)._normalize_budgets(
                    getattr(plan_version, "budgets_json", None)
                )
            )
            policy = cast(Any, self)._normalize_commercial_policy(
                snapshot.policy_json
                if snapshot is not None
                else getattr(plan_version, "policy_json", None)
            )
            budget_state = cast(Any, self)._build_budget_policy_state(
                repository=repository,
                subscription=primary_subscription,
                policy=policy,
                budgets=budgets,
                totals=totals,
                period_start_at=period_start_at,
            )
            active_key_counts = repository.count_site_keys_by_site(
                site_ids=site_ids,
                statuses=[SITE_API_KEY_STATUS_ACTIVE],
            )
            active_runs_by_site = repository.count_active_runs_by_site(site_ids=site_ids)
            knowledge_counts = repository.summarize_site_knowledge_current_counts(
                site_ids=site_ids
            )
            knowledge_index_usage = repository.summarize_site_knowledge_index_usage(
                account_id=account_id,
                subscription_id=(
                    primary_subscription.subscription_id
                    if primary_subscription is not None
                    else None
                ),
                since=period_start_at,
                until=period_end_at,
            )
            batch_limits = cast(Any, self)._resolve_runtime_batch_limits(
                snapshot=snapshot,
                plan_version=plan_version,
            )

        service = cast(Any, self)
        site_count = len(sites)
        active_site_count = sum(
            1 for site in sites if str(getattr(site, "status", "") or "") == SITE_STATUS_ACTIVE
        )
        active_key_site_count = sum(
            1 for site_id in site_ids if int(active_key_counts.get(site_id, 0) or 0) > 0
        )
        active_run_count = sum(int(value or 0) for value in active_runs_by_site.values())
        indexed_document_count = sum(
            int(item.get("documents") or 0) for item in knowledge_counts.values()
        )
        indexed_chunk_count = sum(
            int(item.get("chunks") or 0) for item in knowledge_counts.values()
        )
        site_limit = service._coerce_int(getattr(snapshot, "site_limit", 0))
        concurrency = (
            service._normalize_concurrency(snapshot.concurrency_json)
            if snapshot is not None
            else service._normalize_concurrency(getattr(plan_version, "concurrency_json", None))
        )
        ledger_source = bool(credit_ledger_entries)
        credit_rate_version = AI_CREDIT_RATE_VERSION if ledger_source else "ai-credit-estimate-v1"
        credit_breakdown = build_credit_breakdown_from_ledger(credit_ledger_entries)
        if not credit_breakdown:
            credit_breakdown = self._build_admin_account_credit_breakdown(
                meter_events=meter_events,
                totals=totals,
                indexed_document_count=service._coerce_int(
                    knowledge_index_usage.get("indexed_documents")
                ),
                indexed_chunk_count=service._coerce_int(knowledge_index_usage.get("indexed_chunks")),
            )
        credit_used = round(
            sum(service._coerce_float(item.get("credits")) for item in credit_breakdown),
            6,
        )
        credit_limit = service._coerce_float(budgets.get("max_ai_credits_per_period"))
        if credit_limit <= 0:
            credit_limit = service._coerce_float(budgets.get("max_runs_per_period"))
        credit_status = self._quota_status(used=credit_used, limit=credit_limit)

        resource_limits = [
            self._quota_metric(
                key="bound_sites",
                label="Bound sites",
                used=site_count,
                limit=site_limit,
                unit="site",
            ),
            self._quota_metric(
                key="active_api_key_sites",
                label="Sites with active API keys",
                used=active_key_site_count,
                limit=site_count,
                unit="site",
                status="ok" if active_key_site_count >= site_count else "limited",
            ),
            self._quota_metric(
                key="concurrent_runs",
                label="Concurrent runs",
                used=active_run_count,
                limit=service._coerce_int(concurrency.get("max_active_runs")),
                unit="run",
            ),
            self._quota_metric(
                key="batch_items",
                label="Batch items per request",
                used=0,
                limit=service._coerce_int(batch_limits.get("max_batch_items")),
                unit="item",
            ),
            self._quota_metric(
                key="vector_documents",
                label="Vector indexed articles",
                used=indexed_document_count,
                limit=site_count
                * max(
                    0,
                    int(self.settings.site_knowledge_max_indexed_documents_per_site),
                ),
                unit="document",
            ),
            self._quota_metric(
                key="vector_chunks",
                label="Vector indexed chunks",
                used=indexed_chunk_count,
                limit=site_count
                * max(
                    0,
                    int(self.settings.site_knowledge_max_indexed_chunks_per_site),
                ),
                unit="chunk",
            ),
            self._quota_metric(
                key="vector_sync_documents_per_run",
                label="Vector sync documents per run",
                used=0,
                limit=max(0, int(self.settings.site_knowledge_max_sync_documents_per_run)),
                unit="document",
            ),
            self._quota_metric(
                key="vector_sync_chunks_per_run",
                label="Vector sync chunks per run",
                used=0,
                limit=max(0, int(self.settings.site_knowledge_max_sync_chunks_per_run)),
                unit="chunk",
            ),
        ]
        internal_limits = [
            self._quota_metric(
                key="tokens",
                label="Tokens",
                used=service._coerce_float(totals.get("tokens_total")),
                limit=service._coerce_float(budgets.get("max_tokens_per_period")),
                unit="token",
            ),
            self._quota_metric(
                key="cost",
                label="Provider cost",
                used=service._coerce_float(totals.get("cost")),
                limit=service._coerce_float(budgets.get("max_cost_per_period")),
                unit="usd",
            ),
            self._quota_metric(
                key="provider_calls",
                label="Provider calls",
                used=service._coerce_float(totals.get("provider_calls")),
                limit=0,
                unit="call",
            ),
        ]
        resource_statuses = [
            str(item.get("status") or "ok") for item in [*resource_limits, *internal_limits]
        ]
        status = "limited" if "limited" in [credit_status, *resource_statuses] else (
            "near_limit" if "near_limit" in [credit_status, *resource_statuses] else "ok"
        )
        return {
            "account_id": account_id,
            "generated_at": self._serialize_datetime(now),
            "period_start_at": self._serialize_datetime(period_start_at),
            "period_end_at": self._serialize_datetime(period_end_at),
            "status": status,
            "credit": self._quota_metric(
                key="ai_credits",
                label="AI credits",
                used=credit_used,
                limit=credit_limit,
                unit="credit",
                status=credit_status,
                extra={
                    "estimated": not ledger_source,
                    "rate_version": credit_rate_version,
                    "source": "ledger" if ledger_source else "estimate",
                    "limit_source": (
                        "max_ai_credits_per_period"
                        if service._coerce_float(budgets.get("max_ai_credits_per_period")) > 0
                        else "max_runs_per_period"
                    ),
                },
            ),
            "resource_limits": resource_limits,
            "internal_limits": internal_limits,
            "breakdown": credit_breakdown,
            "totals": totals,
            "budget_state": budget_state,
            "coverage": {
                "site_count": site_count,
                "active_site_count": active_site_count,
                "active_key_site_count": active_key_site_count,
                **service._build_subscription_package_summary(
                    primary_subscription,
                    site_count=site_count,
                ),
            },
        }

    def get_portal_account_quota_summary(self, account_id: str) -> dict[str, object]:
        summary = self.get_admin_account_quota_summary(account_id)
        return {
            "account_id": str(summary.get("account_id") or account_id),
            "generated_at": summary.get("generated_at"),
            "period_start_at": summary.get("period_start_at"),
            "period_end_at": summary.get("period_end_at"),
            "status": summary.get("status"),
            "credit": summary.get("credit"),
            "resource_limits": (
                summary.get("resource_limits")
                if isinstance(summary.get("resource_limits"), list)
                else []
            ),
            "breakdown": (
                summary.get("breakdown")
                if isinstance(summary.get("breakdown"), list)
                else []
            ),
        }

    def _build_platform_credit_summary(
        self,
        *,
        meter_events: list[object],
        ledger_entries: list[object],
        window_days: int,
        start_at: datetime,
        end_at: datetime,
        knowledge_index_usage: dict[str, int],
    ) -> dict[str, object]:
        service = cast(Any, self)
        totals = service._aggregate_meter_events(meter_events)
        ledger_source = bool(ledger_entries)
        breakdown = build_credit_breakdown_from_ledger(ledger_entries)
        if not breakdown:
            breakdown = self._build_admin_account_credit_breakdown(
                meter_events=meter_events,
                totals=totals,
                indexed_document_count=service._coerce_int(
                    knowledge_index_usage.get("indexed_documents")
                ),
                indexed_chunk_count=service._coerce_int(knowledge_index_usage.get("indexed_chunks")),
            )
        credit_used = round(
            sum(service._coerce_float(item.get("credits")) for item in breakdown),
            6,
        )
        account_events: dict[str, list[object]] = defaultdict(list)
        for event in meter_events:
            account_id = str(getattr(event, "account_id", "") or "")
            if account_id:
                account_events[account_id].append(event)
        account_ledger_entries: dict[str, list[object]] = defaultdict(list)
        for entry in ledger_entries:
            account_id = str(getattr(entry, "account_id", "") or "")
            if account_id:
                account_ledger_entries[account_id].append(entry)
        top_accounts = []
        account_ids = set(account_events.keys()) | set(account_ledger_entries.keys())
        for account_id in account_ids:
            events = account_events.get(account_id, [])
            account_totals = service._aggregate_meter_events(events)
            account_breakdown = build_credit_breakdown_from_ledger(
                account_ledger_entries.get(account_id, [])
            )
            if not account_breakdown:
                account_breakdown = self._build_admin_account_credit_breakdown(
                    meter_events=events,
                    totals=account_totals,
                    indexed_document_count=0,
                    indexed_chunk_count=0,
                )
            account_credit_used = round(
                sum(service._coerce_float(item.get("credits")) for item in account_breakdown),
                6,
            )
            top_accounts.append(
                {
                    "account_id": account_id,
                    "credits": account_credit_used,
                    "runs": service._coerce_float(account_totals.get("runs")),
                    "provider_calls": service._coerce_float(account_totals.get("provider_calls")),
                    "tokens_total": service._coerce_float(account_totals.get("tokens_total")),
                }
            )
        top_accounts = sorted(
            top_accounts,
            key=lambda item: service._coerce_float(item.get("credits")),
            reverse=True,
        )[:5]
        return {
            "window_days": max(1, int(window_days or 1)),
            "period_start_at": self._serialize_datetime(start_at),
            "period_end_at": self._serialize_datetime(end_at),
            "credit": self._quota_metric(
                key="platform_ai_credits",
                label="Platform AI credits",
                used=credit_used,
                limit=0,
                unit="credit",
                extra={
                    "estimated": not ledger_source,
                    "rate_version": (
                        AI_CREDIT_RATE_VERSION if ledger_source else "ai-credit-estimate-v1"
                    ),
                    "scope": "platform",
                    "source": "ledger" if ledger_source else "estimate",
                },
            ),
            "breakdown": breakdown,
            "top_accounts": top_accounts,
        }

    def _build_admin_account_credit_breakdown(
        self,
        *,
        meter_events: list[object],
        totals: dict[str, float],
        indexed_document_count: int,
        indexed_chunk_count: int,
    ) -> list[dict[str, object]]:
        service = cast(Any, self)
        web_search_calls = 0.0
        image_calls = 0.0
        other_provider_calls = 0.0
        for event in meter_events:
            if str(getattr(event, "meter_key", "") or "") != "provider_calls":
                continue
            execution_kind = str(getattr(event, "execution_kind", "") or "").lower()
            ability_family = str(getattr(event, "ability_family", "") or "").lower()
            quantity = service._coerce_float(getattr(event, "quantity", 0.0))
            if "web_search" in execution_kind or "search" in execution_kind:
                web_search_calls += quantity
            elif "image" in execution_kind or ability_family in {"vision"}:
                image_calls += quantity
            else:
                other_provider_calls += quantity
        run_count = service._coerce_float(totals.get("runs"))
        token_units = service._coerce_float(totals.get("tokens_total")) / 1000.0
        items = [
            {
                "key": "runs",
                "label": "Hosted runs",
                "quantity": round(run_count, 6),
                "unit": "run",
                "rate": 1.0,
                "credits": round(run_count, 6),
            },
            {
                "key": "tokens_total",
                "label": "Model tokens",
                "quantity": round(service._coerce_float(totals.get("tokens_total")), 6),
                "unit": "token",
                "rate": 1.0,
                "rate_unit": "1000_tokens",
                "credits": round(token_units, 6),
            },
            {
                "key": "web_search",
                "label": "Search calls",
                "quantity": round(web_search_calls, 6),
                "unit": "call",
                "rate": 5.0,
                "credits": round(web_search_calls * 5.0, 6),
            },
            {
                "key": "image_recommendation",
                "label": "Image recommendation calls",
                "quantity": round(image_calls, 6),
                "unit": "call",
                "rate": 3.0,
                "credits": round(image_calls * 3.0, 6),
            },
            {
                "key": "provider_calls_other",
                "label": "Other provider calls",
                "quantity": round(other_provider_calls, 6),
                "unit": "call",
                "rate": 0.0,
                "credits": 0.0,
            },
            {
                "key": "vector_documents",
                "label": "Vector indexed articles",
                "quantity": indexed_document_count,
                "unit": "document",
                "rate": 2.0,
                "credits": round(indexed_document_count * 2.0, 6),
            },
            {
                "key": "vector_chunks",
                "label": "Vector indexed chunks",
                "quantity": indexed_chunk_count,
                "unit": "chunk",
                "rate": 0.1,
                "credits": round(indexed_chunk_count * 0.1, 6),
            },
        ]
        return [item for item in items if service._coerce_float(item.get("quantity")) > 0]

    def _quota_metric(
        self,
        *,
        key: str,
        label: str,
        used: float,
        limit: float,
        unit: str,
        status: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> dict[str, object]:
        used_value = round(float(used or 0.0), 6)
        limit_value = round(float(limit or 0.0), 6)
        unlimited = limit_value <= 0
        remaining = 0.0 if unlimited else max(0.0, limit_value - used_value)
        usage_ratio = 0.0 if unlimited else used_value / max(limit_value, 1e-9)
        payload = {
            "key": key,
            "label": label,
            "used": used_value,
            "limit": limit_value,
            "remaining": round(remaining, 6),
            "unlimited": unlimited,
            "usage_ratio": round(usage_ratio, 6),
            "status": status or self._quota_status(used=used_value, limit=limit_value),
            "unit": unit,
        }
        if extra:
            payload.update(extra)
        return payload

    def _quota_status(self, *, used: float, limit: float) -> str:
        if float(limit or 0.0) <= 0:
            return "ok"
        ratio = float(used or 0.0) / max(float(limit), 1e-9)
        if ratio >= 1.0:
            return "limited"
        if ratio >= 0.8:
            return "near_limit"
        return "ok"

    def _build_account_trial_readiness_summary(
        self,
        *,
        account: object,
        sites: list[object],
        subscriptions: list[AccountSubscription],
        active_key_counts: dict[str, int],
    ) -> dict[str, object]:
        service = cast(Any, self)
        primary_subscription = service._select_primary_subscription(subscriptions)
        package_summary = service._build_subscription_package_summary(
            primary_subscription,
            site_count=len(sites),
        )
        package_kind = str(package_summary.get("package_kind") or "")
        coverage_state = str(package_summary.get("coverage_state") or "")
        account_active = str(getattr(account, "status", "") or "") == ACCOUNT_STATUS_ACTIVE
        site_count = len(sites)
        active_site_count = sum(
            1 for site in sites if str(getattr(site, "status", "") or "") == SITE_STATUS_ACTIVE
        )
        sites_without_active_key = [
            str(getattr(site, "site_id", "") or "")
            for site in sites
            if int(active_key_counts.get(str(getattr(site, "site_id", "") or ""), 0) or 0) <= 0
        ]
        active_key_site_count = site_count - len(sites_without_active_key)
        subscription_status = str(getattr(primary_subscription, "status", "") or "")
        has_coverage = coverage_state == "covered" and package_kind not in {
            "dev_baseline",
            "unknown",
            "uncovered",
        }
        package_label = str(package_summary.get("display_package_label") or "Package")
        subscription_stable = subscription_status in {
            SUBSCRIPTION_STATUS_ACTIVE,
            SUBSCRIPTION_STATUS_TRIALING,
        }
        checks = [
            {
                "code": "account_active",
                "label": "Customer active",
                "ok": account_active,
                "detail": (
                    "Customer record is active."
                    if account_active
                    else "Resume or review the customer before inviting it into trial."
                ),
            },
            {
                "code": "site_attached",
                "label": "Site attached",
                "ok": site_count > 0,
                "detail": (
                    f"{site_count} site(s) attached."
                    if site_count > 0
                    else "Attach or provision at least one approved WordPress site."
                ),
            },
            {
                "code": "sites_active",
                "label": "Sites active",
                "ok": site_count > 0 and active_site_count == site_count,
                "detail": (
                    "Every attached site is active."
                    if site_count > 0 and active_site_count == site_count
                    else f"{active_site_count}/{site_count} site(s) are active."
                ),
            },
            {
                "code": "active_api_key",
                "label": "Cloud API key",
                "ok": site_count > 0 and active_key_site_count == site_count,
                "detail": (
                    "Every attached site has an active Cloud API key."
                    if site_count > 0 and active_key_site_count == site_count
                    else f"{len(sites_without_active_key)} site(s) need an active Cloud API key."
                ),
            },
            {
                "code": "package_coverage",
                "label": "Package coverage",
                "ok": has_coverage and subscription_stable,
                "detail": (
                    f"{package_label} coverage is ready."
                    if has_coverage and subscription_stable
                    else "Apply Free, Pro, or Agency coverage before granting site admin access."
                ),
            },
        ]
        blocking_codes = [str(item["code"]) for item in checks if not bool(item["ok"])]
        status = "ready" if not blocking_codes else "action_required"
        if not account_active or site_count == 0:
            status = "blocked"
        next_action = "review_site_admin_access"
        next_action_label = "Review site admin access"
        if not account_active:
            next_action = "review_customer_status"
            next_action_label = "Review customer status"
        elif site_count == 0:
            next_action = "attach_approved_site"
            next_action_label = "Attach approved site"
        elif not has_coverage or not subscription_stable:
            next_action = "apply_package_coverage"
            next_action_label = "Apply package coverage"
        elif active_site_count != site_count:
            next_action = "activate_sites"
            next_action_label = "Activate attached sites"
        elif sites_without_active_key:
            next_action = "issue_or_verify_key"
            next_action_label = "Issue or verify Cloud API key"
        return {
            "status": status,
            "next_action": next_action,
            "next_action_label": next_action_label,
            "blocking_codes": blocking_codes,
            "summary": {
                "site_count": site_count,
                "active_site_count": active_site_count,
                "active_key_site_count": active_key_site_count,
                "sites_without_active_key": sites_without_active_key,
                "subscription_status": subscription_status,
                **package_summary,
            },
            "checks": checks,
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
