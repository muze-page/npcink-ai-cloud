"""Commercial service: admin and platform operations mixin."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.db import get_session
from app.core.models import (
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE,
    CREDIT_LEDGER_EVENT_ADJUSTMENT,
    CREDIT_LEDGER_EVENT_CONSUME,
    CREDIT_LEDGER_EVENT_GRANT,
    CREDIT_LEDGER_EVENT_REFUND,
    IDENTITY_PROVIDER_BINDING_STATUS_ACTIVE,
    PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
    PLATFORM_ADMIN_STATUS_ACTIVE,
    PLATFORM_KIND_WORDPRESS,
    PRINCIPAL_STATUS_ACTIVE,
    PRINCIPAL_STATUS_DISABLED,
    SITE_API_KEY_STATUS_ACTIVE,
    SITE_STATUS_ACTIVE,
    SITE_STATUS_ARCHIVED,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_PAST_DUE,
    SUBSCRIPTION_STATUS_SUSPENDED,
    SUBSCRIPTION_STATUS_TRIALING,
    AccountSubscription,
)
from app.domain.commercial.audit_context import ServiceAuditContext
from app.domain.commercial.credits import (
    AI_CREDIT_COMPONENT_LABELS,
    AI_CREDIT_RATE_VERSION,
    build_credit_breakdown_from_ledger,
    is_site_knowledge_index_meter_event,
    package_credit_used,
    rounded_token_credits,
)
from app.domain.commercial.errors import (
    CommercialNotFoundError,
    CommercialPermissionError,
    CommercialValidationError,
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

AI_CREDIT_VISIBLE_LEDGER_EVENT_TYPES = [
    CREDIT_LEDGER_EVENT_CONSUME,
    CREDIT_LEDGER_EVENT_GRANT,
    CREDIT_LEDGER_EVENT_ADJUSTMENT,
    CREDIT_LEDGER_EVENT_REFUND,
]

AI_CREDIT_LEDGER_CATEGORY_LABELS = {
    "monthly_plan_grant": "Monthly plan grant",
    "credit_pack_purchase": "Credit pack purchase",
    "ai_usage": "AI usage",
    "refund_adjustment": "Refund adjustment",
    "operator_adjustment": "Operator adjustment",
    "refund": "Refund",
    "other": "Other credit event",
}

_ADMIN_INTERNAL_ACCOUNT_RE = re.compile(
    r"(^|[_-])(smoke)([_-]|$)|codex_image_smoke|site_knowledge_smoke",
    re.IGNORECASE,
)
_ADMIN_MALFORMED_ACCOUNT_RE = re.compile(
    r"Fatal error|Stack trace|Command line code|Uncaught ValueError|Path must not be empty",
    re.IGNORECASE,
)


class CommercialServiceAdminMixin(CommercialServiceAuditMixin):
    def _serialize_platform_admin_grant(
        self,
        identity: Any,
        *,
        principal: Any | None = None,
    ) -> dict[str, object]:
        metadata = getattr(identity, "metadata_json", None)
        return {
            "grant_id": str(getattr(identity, "grant_id", "") or ""),
            "principal_id": str(getattr(identity, "principal_id", "") or ""),
            "identity_type": IDENTITY_TYPE_PLATFORM_ADMIN,
            "role": str(getattr(identity, "role", "") or PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN),
            "capabilities": _platform_capability_flags(
                str(getattr(identity, "role", "") or PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN)
            ),
            "status": str(getattr(identity, "status", "") or ""),
            "provider": str(getattr(identity, "provider", "") or ""),
            "external_subject": str(getattr(identity, "external_subject", "") or ""),
            "email": str(getattr(identity, "email", "") or ""),
            "session_version": int(getattr(principal, "session_version", 1) or 1),
            "metadata": metadata if isinstance(metadata, dict) else {},
            "created_at": self._serialize_datetime(getattr(identity, "created_at", None)),
            "updated_at": self._serialize_datetime(getattr(identity, "updated_at", None)),
        }

    def upsert_platform_admin_grant(
        self,
        *,
        principal_id: str,
        role: str = PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
        status: str = PLATFORM_ADMIN_STATUS_ACTIVE,
        provider: str = "manual",
        external_subject: str | None = None,
        email: str | None = None,
        metadata_json: dict[str, object] | None = None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_principal_id = principal_id.strip()
        normalized_role = _canonicalize_platform_admin_role_for_write(role)
        normalized_status = status.strip() or PLATFORM_ADMIN_STATUS_ACTIVE
        normalized_provider = provider.strip().lower() or "manual"
        normalized_email = email.strip().lower() if email else None
        normalized_subject = external_subject.strip() if external_subject else None
        if not normalized_principal_id:
            raise CommercialPermissionError(
                "service.principal_id_required",
                "principal id is required",
            )
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            principal = repository.upsert_principal_identity(
                principal_id=normalized_principal_id,
                email=normalized_email,
                status=PRINCIPAL_STATUS_ACTIVE,
                metadata_json={"source": "platform_admin_grant"},
            )
            identity = repository.upsert_platform_admin_grant(
                grant_id=f"pad_{uuid4().hex}",
                principal_id=normalized_principal_id,
                provider=normalized_provider,
                external_subject=normalized_subject,
                email=normalized_email,
                role=normalized_role,
                status=normalized_status,
                metadata_json=metadata_json,
            )
            payload = self._serialize_platform_admin_grant(identity, principal=principal)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="platform_admin_grant.upsert",
                outcome="succeeded",
                scope_kind="platform_admin",
                scope_id=normalized_principal_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def resolve_platform_admin_grant(
        self,
        *,
        principal_id: str,
        bootstrap_role: str = PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
        allow_bootstrap: bool = False,
    ) -> dict[str, object]:
        normalized_principal_id = principal_id.strip()
        if not normalized_principal_id:
            raise CommercialPermissionError(
                "service.principal_id_required",
                "principal id is required",
            )
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            identity = repository.get_platform_admin_grant(principal_id=normalized_principal_id)
            if identity is None:
                if not allow_bootstrap:
                    raise CommercialNotFoundError(
                        "service.platform_admin_not_found",
                        f"platform admin '{normalized_principal_id}' was not found",
                    )
                return {
                    "principal_id": normalized_principal_id,
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
                    f"platform admin '{normalized_principal_id}' is disabled",
                )
            principal = repository.get_principal_identity_by_ref(
                principal_id=normalized_principal_id,
            )
            return self._serialize_platform_admin_grant(identity, principal=principal)

    def delete_platform_admin_grant(
        self,
        *,
        principal_id: str,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_principal_id = principal_id.strip()
        if not normalized_principal_id:
            raise CommercialPermissionError(
                "service.principal_id_required",
                "principal id is required",
            )
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            identity = repository.get_platform_admin_grant(principal_id=normalized_principal_id)
            if identity is None:
                raise CommercialNotFoundError(
                    "service.platform_admin_not_found",
                    f"platform admin '{normalized_principal_id}' was not found",
                )
            principal = repository.get_principal_identity_by_ref(
                principal_id=normalized_principal_id,
            )
            payload = self._serialize_platform_admin_grant(identity, principal=principal)
            repository.delete_platform_admin_grant(principal_id=normalized_principal_id)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="platform_admin_grant.delete",
                outcome="succeeded",
                scope_kind="platform_admin",
                scope_id=normalized_principal_id,
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
        previous_usage_since = usage_since - timedelta(days=max(1, usage_window_days))
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
            principals_active = repository.count_principals(status=PRINCIPAL_STATUS_ACTIVE)
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
            previous_usage_meter_events = [
                event
                for event in repository.list_usage_meter_events_for_admin(
                    since=previous_usage_since,
                    limit=None,
                )
                if (
                    (event_created_at := getattr(event, "created_at", None)) is not None
                    and cast(Any, self)._normalize_datetime(event_created_at) < usage_since
                )
            ]
            credit_ledger_entries = repository.list_credit_ledger_entries(
                event_types=[CREDIT_LEDGER_EVENT_CONSUME],
                since=usage_since,
                until=now,
                limit=None,
            )
            previous_credit_ledger_entries = repository.list_credit_ledger_entries(
                event_types=[CREDIT_LEDGER_EVENT_CONSUME],
                since=previous_usage_since,
                until=usage_since,
                limit=None,
            )
            knowledge_index_usage = repository.summarize_site_knowledge_index_usage(
                since=usage_since,
                until=now,
            )
            previous_knowledge_index_usage = repository.summarize_site_knowledge_index_usage(
                since=previous_usage_since,
                until=usage_since,
            )
            expiring_subscriptions = repository.list_subscriptions(
                statuses=active_subscription_statuses,
                current_period_end_before=now + timedelta(days=30),
                limit=None,
            )
            attention_subscriptions = repository.list_subscriptions(
                status=SUBSCRIPTION_STATUS_PAST_DUE, limit=5
            ) + repository.list_subscriptions(status=SUBSCRIPTION_STATUS_SUSPENDED, limit=5)
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
            previous_meter_events=previous_usage_meter_events,
            previous_ledger_entries=previous_credit_ledger_entries,
            window_days=max(1, usage_window_days),
            start_at=usage_since,
            end_at=now,
            previous_start_at=previous_usage_since,
            previous_end_at=usage_since,
            knowledge_index_usage=knowledge_index_usage,
            previous_knowledge_index_usage=previous_knowledge_index_usage,
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
                "principals_active": principals_active,
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

    def list_admin_portal_users(
        self,
        *,
        q: str | None = None,
        source: str | None = "portal_self_registration",
        status: str | None = None,
        package_alias: str | None = None,
        qq_bound: bool | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, object]:
        normalized_q = str(q or "").strip().lower()
        normalized_source = str(source or "portal_self_registration").strip().lower()
        if normalized_source in {"", "self_registered", "self-registration"}:
            normalized_source = "portal_self_registration"
        if normalized_source not in {"all", "portal_self_registration", "account_membership"}:
            raise CommercialValidationError(
                "service.portal_user_source_invalid",
                "portal user source must be all, portal_self_registration, or account_membership",
            )
        normalized_status = str(status or "").strip().lower()
        if normalized_status and normalized_status not in {
            PRINCIPAL_STATUS_ACTIVE,
            PRINCIPAL_STATUS_DISABLED,
        }:
            raise CommercialValidationError(
                "service.portal_user_status_invalid",
                "portal user status must be active or disabled",
            )
        normalized_package = str(package_alias or "").strip().lower()
        resolved_limit = min(max(int(limit or 100), 1), 500)
        normalized_offset = max(0, int(offset or 0))

        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            principals = repository.list_principals(
                status=normalized_status or None,
                limit=None,
            )
            principal_ids = [str(principal.principal_id or "") for principal in principals]
            memberships = repository.list_account_user_memberships(
                principal_ids=principal_ids,
                statuses=None,
            )
            qq_bindings = repository.list_identity_provider_bindings(
                principal_ids=principal_ids,
                provider="qq",
                statuses=None,
            )
            account_ids = sorted(
                {
                    str(membership.account_id or "")
                    for membership in memberships
                    if str(membership.account_id or "").strip()
                }
            )
            accounts = repository.list_accounts(account_ids=account_ids, limit=None)
            sites = repository.list_sites(account_ids=account_ids, limit=None)
            subscriptions = repository.list_subscriptions(account_ids=account_ids, limit=None)

        memberships_by_principal: dict[str, list[Any]] = defaultdict(list)
        for membership in memberships:
            memberships_by_principal[str(membership.principal_id or "")].append(membership)

        qq_bindings_by_principal: dict[str, list[Any]] = defaultdict(list)
        for binding in qq_bindings:
            qq_bindings_by_principal[str(binding.principal_id or "")].append(binding)

        accounts_by_id = {str(account.account_id or ""): account for account in accounts}
        sites_by_account: dict[str, list[Any]] = defaultdict(list)
        for account_site in sites:
            sites_by_account[str(account_site.account_id or "")].append(account_site)
        subscriptions_by_account: dict[str, list[AccountSubscription]] = defaultdict(list)
        for subscription in subscriptions:
            subscriptions_by_account[str(subscription.account_id or "")].append(subscription)

        def metadata_source(*objects: Any) -> str:
            for item in objects:
                metadata = getattr(item, "metadata_json", None)
                if isinstance(metadata, dict):
                    source_value = str(metadata.get("source") or "").strip()
                    if source_value:
                        return source_value
            return ""

        def preferred_active(items: Sequence[Any], *, active_status: str) -> Any | None:
            return next(
                (item for item in items if str(getattr(item, "status", "") or "") == active_status),
                items[0] if items else None,
            )

        service = cast(Any, self)
        items: list[dict[str, object]] = []
        for principal in principals:
            principal_id = str(principal.principal_id or "")
            principal_memberships = memberships_by_principal.get(principal_id, [])
            if not principal_memberships:
                continue
            selected_membership = preferred_active(
                principal_memberships,
                active_status=ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE,
            )
            account = accounts_by_id.get(str(getattr(selected_membership, "account_id", "") or ""))
            account_sites = sites_by_account.get(
                str(getattr(selected_membership, "account_id", "") or ""),
                [],
            )
            site = account_sites[0] if account_sites else None
            source_value = metadata_source(
                principal,
                selected_membership,
                account,
                site,
            )
            if normalized_source != "all" and source_value != normalized_source:
                continue
            account_subscriptions = (
                subscriptions_by_account.get(str(getattr(account, "account_id", "") or ""), [])
                if account is not None
                else []
            )
            primary_subscription = service._select_primary_subscription(account_subscriptions)
            package_summary = service._build_subscription_package_summary(
                primary_subscription,
                site_count=len(account_sites),
            )
            subscription_payload = (
                service._serialize_subscription(primary_subscription)
                if primary_subscription is not None
                else None
            )
            active_qq_bindings = [
                binding
                for binding in qq_bindings_by_principal.get(principal_id, [])
                if str(getattr(binding, "status", "") or "")
                == IDENTITY_PROVIDER_BINDING_STATUS_ACTIVE
            ]
            is_qq_bound = bool(active_qq_bindings)
            if qq_bound is not None and is_qq_bound is not qq_bound:
                continue
            package_blob = " ".join(
                [
                    str(package_summary.get("package_alias") or ""),
                    str(package_summary.get("display_package_label") or ""),
                    str(getattr(primary_subscription, "plan_id", "") or ""),
                ]
            ).lower()
            if normalized_package and normalized_package not in package_blob:
                continue
            site_url = str(getattr(site, "site_url", "") or "").strip()
            search_blob = " ".join(
                [
                    principal_id,
                    str(getattr(principal, "email", "") or ""),
                    str(getattr(account, "account_id", "") or ""),
                    str(getattr(account, "name", "") or ""),
                    str(getattr(site, "site_id", "") or ""),
                    str(getattr(site, "name", "") or ""),
                    site_url,
                    str(package_summary.get("package_alias") or ""),
                ]
            ).lower()
            if normalized_q and normalized_q not in search_blob:
                continue
            latest_qq_login_at = next(
                (
                    getattr(binding, "last_login_at", None)
                    for binding in active_qq_bindings
                    if getattr(binding, "last_login_at", None) is not None
                ),
                None,
            )
            item = {
                "principal_id": principal_id,
                "email": str(getattr(principal, "email", "") or ""),
                "status": str(getattr(principal, "status", "") or ""),
                "session_version": int(getattr(principal, "session_version", 1) or 1),
                "source": source_value,
                "registration_source": source_value,
                "last_login_at": self._serialize_datetime(
                    getattr(principal, "last_login_at", None)
                ),
                "created_at": self._serialize_datetime(getattr(principal, "created_at", None)),
                "account": service._serialize_account(account) if account is not None else None,
                "account_id": str(getattr(account, "account_id", "") or ""),
                "account_name": str(getattr(account, "name", "") or ""),
                "account_status": str(getattr(account, "status", "") or ""),
                "membership_status": str(getattr(selected_membership, "status", "") or ""),
                "site": service._serialize_site(site) if site is not None else None,
                "site_id": str(getattr(site, "site_id", "") or ""),
                "site_name": str(getattr(site, "name", "") or ""),
                "site_status": str(getattr(site, "status", "") or ""),
                "site_url": site_url,
                "platform_kind": str(
                    getattr(site, "platform_kind", "") or PLATFORM_KIND_WORDPRESS
                ),
                "subscription": subscription_payload,
                "subscription_id": str(getattr(primary_subscription, "subscription_id", "") or ""),
                "subscription_status": str(getattr(primary_subscription, "status", "") or ""),
                "plan_id": str(getattr(primary_subscription, "plan_id", "") or ""),
                **package_summary,
                "qq_bound": is_qq_bound,
                "qq_binding_count": len(active_qq_bindings),
                "qq_last_login_at": self._serialize_datetime(latest_qq_login_at),
            }
            items.append(item)

        summary_counts = Counter(str(item.get("status") or "") for item in items)
        qq_bound_total = sum(1 for item in items if bool(item.get("qq_bound")))
        self_registered_total = sum(
            1 for item in items if str(item.get("source") or "") == "portal_self_registration"
        )
        filtered_total = len(items)
        items = items[normalized_offset : normalized_offset + resolved_limit]
        return {
            "filters": {
                "q": normalized_q,
                "source": normalized_source,
                "status": normalized_status,
                "package_alias": package_alias or "",
                "qq_bound": qq_bound,
                "offset": normalized_offset,
                "limit": resolved_limit,
            },
            "items": items,
            "total": filtered_total,
            "summary": {
                "active": int(summary_counts.get(PRINCIPAL_STATUS_ACTIVE, 0)),
                "disabled": int(summary_counts.get(PRINCIPAL_STATUS_DISABLED, 0)),
                "qq_bound": qq_bound_total,
                "self_registered": self_registered_total,
            },
            "pagination": {
                "offset": normalized_offset,
                "limit": resolved_limit,
                "total": filtered_total,
                "has_more": normalized_offset + len(items) < filtered_total,
            },
        }

    def get_admin_portal_user_audit(
        self,
        *,
        principal_id: str,
        limit: int = 50,
    ) -> dict[str, object]:
        normalized_principal_id = str(principal_id or "").strip()
        if not normalized_principal_id:
            raise CommercialValidationError(
                "service.principal_id_required",
                "principal id is required",
            )
        resolved_limit = min(max(int(limit or 50), 1), 100)
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            identity = repository.get_principal_identity_by_ref(
                principal_id=normalized_principal_id,
            )
            if identity is None:
                raise CommercialNotFoundError(
                    "service.principal_not_found",
                    f"principal '{normalized_principal_id}' was not found",
                )
            events = repository.list_service_audit_events_for_principal(
                principal_id=normalized_principal_id,
                limit=resolved_limit,
            )

        items = [self._serialize_service_audit_event(event) for event in events]
        outcomes = Counter(str(item.get("outcome") or "unknown") for item in items)
        event_kinds = Counter(str(item.get("event_kind") or "unknown") for item in items)
        disable_events = [
            item for item in items if str(item.get("event_kind") or "") == "portal_user.disable"
        ]
        latest_disable = disable_events[0] if disable_events else None
        latest_payload: dict[str, object] = {}
        if isinstance(latest_disable, dict) and isinstance(latest_disable.get("payload"), dict):
            latest_payload = cast(dict[str, object], latest_disable.get("payload"))
        return {
            "principal": {
                "principal_id": normalized_principal_id,
                "email": str(getattr(identity, "email", "") or ""),
                "status": str(getattr(identity, "status", "") or ""),
                "session_version": int(getattr(identity, "session_version", 1) or 1),
                "last_login_at": self._serialize_datetime(getattr(identity, "last_login_at", None)),
                "created_at": self._serialize_datetime(getattr(identity, "created_at", None)),
            },
            "items": items,
            "total": len(items),
            "summary": {
                "events": len(items),
                "succeeded": int(outcomes.get("succeeded", 0)),
                "failed": int(outcomes.get("failed", 0)),
                "registration_events": int(event_kinds.get("portal.registration", 0)),
                "disable_events": int(event_kinds.get("portal_user.disable", 0)),
                "latest_disable_reason": str(latest_payload.get("reason") or ""),
                "latest_disable_revoked_account_memberships": self._coerce_int(
                    latest_payload.get("revoked_account_memberships")
                ),
                "latest_disable_revoked_identity_provider_bindings": self._coerce_int(
                    latest_payload.get("revoked_identity_provider_bindings")
                ),
            },
            "filters": {
                "principal_id": normalized_principal_id,
                "limit": resolved_limit,
            },
        }

    def disable_admin_portal_user(
        self,
        *,
        principal_id: str,
        reason: str = "",
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_principal_id = principal_id.strip()
        if not normalized_principal_id:
            raise CommercialValidationError(
                "service.principal_id_required",
                "principal id is required",
            )
        normalized_reason = str(reason or "").strip()[:500]
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            identity = repository.get_principal_identity_by_ref(
                principal_id=normalized_principal_id,
            )
            if identity is None:
                raise CommercialNotFoundError(
                    "service.principal_not_found",
                    f"principal '{normalized_principal_id}' was not found",
                )
            identity.status = PRINCIPAL_STATUS_DISABLED
            identity = (
                repository.increment_principal_session_version(
                    principal_id=normalized_principal_id,
                )
                or identity
            )
            revoked_memberships = repository.revoke_account_user_memberships(
                principal_id=normalized_principal_id,
            )
            revoked_bindings = repository.revoke_identity_provider_bindings(
                principal_id=normalized_principal_id,
                provider="qq",
            )
            payload: dict[str, object] = {
                "principal_id": normalized_principal_id,
                "email": str(getattr(identity, "email", "") or ""),
                "status": str(getattr(identity, "status", "") or ""),
                "session_version": int(getattr(identity, "session_version", 1) or 1),
                "revoked_account_memberships": revoked_memberships,
                "revoked_identity_provider_bindings": revoked_bindings,
                "reason": normalized_reason,
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="portal_user.disable",
                outcome="succeeded",
                scope_kind="principal",
                scope_id=normalized_principal_id,
                payload_json=payload,
            )
            session.commit()
            return payload

    def batch_disable_admin_portal_users(
        self,
        *,
        principal_ids: Sequence[str],
        reason: str,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_reason = str(reason or "").strip()[:500]
        if not normalized_reason:
            raise CommercialValidationError(
                "service.portal_user_batch_disable_reason_required",
                "batch disable reason is required",
            )
        normalized_principal_ids: list[str] = []
        seen_principal_ids: set[str] = set()
        for principal_id in principal_ids:
            normalized_principal_id = str(principal_id or "").strip()
            if not normalized_principal_id or normalized_principal_id in seen_principal_ids:
                continue
            normalized_principal_ids.append(normalized_principal_id)
            seen_principal_ids.add(normalized_principal_id)
        if not normalized_principal_ids:
            raise CommercialValidationError(
                "service.portal_user_batch_disable_empty",
                "at least one principal id is required",
            )
        if len(normalized_principal_ids) > 100:
            raise CommercialValidationError(
                "service.portal_user_batch_disable_too_many",
                "batch disable accepts at most 100 principal ids",
            )

        items: list[dict[str, object]] = []
        totals = {
            "attempted": len(normalized_principal_ids),
            "disabled": 0,
            "already_disabled": 0,
            "failed": 0,
            "revoked_account_memberships": 0,
            "revoked_identity_provider_bindings": 0,
        }
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            for normalized_principal_id in normalized_principal_ids:
                identity = repository.get_principal_identity_by_ref(
                    principal_id=normalized_principal_id,
                )
                if identity is None:
                    totals["failed"] += 1
                    items.append(
                        {
                            "principal_id": normalized_principal_id,
                            "outcome": "failed",
                            "error_code": "service.principal_not_found",
                            "message": f"principal '{normalized_principal_id}' was not found",
                        }
                    )
                    continue

                was_disabled = (
                    str(getattr(identity, "status", "") or "") == PRINCIPAL_STATUS_DISABLED
                )
                identity.status = PRINCIPAL_STATUS_DISABLED
                if not was_disabled:
                    identity = (
                        repository.increment_principal_session_version(
                            principal_id=normalized_principal_id,
                        )
                        or identity
                    )
                revoked_memberships = repository.revoke_account_user_memberships(
                    principal_id=normalized_principal_id,
                )
                revoked_bindings = repository.revoke_identity_provider_bindings(
                    principal_id=normalized_principal_id,
                    provider="qq",
                )
                totals["revoked_account_memberships"] += revoked_memberships
                totals["revoked_identity_provider_bindings"] += revoked_bindings
                outcome = "already_disabled" if was_disabled else "disabled"
                totals[outcome] += 1
                item_payload: dict[str, object] = {
                    "principal_id": normalized_principal_id,
                    "email": str(getattr(identity, "email", "") or ""),
                    "status": str(getattr(identity, "status", "") or ""),
                    "session_version": int(getattr(identity, "session_version", 1) or 1),
                    "outcome": outcome,
                    "revoked_account_memberships": revoked_memberships,
                    "revoked_identity_provider_bindings": revoked_bindings,
                    "reason": normalized_reason,
                }
                items.append(item_payload)
                self._record_service_audit_in_session(
                    repository=repository,
                    audit_context=audit_context,
                    event_kind="portal_user.disable",
                    outcome="succeeded",
                    scope_kind="principal",
                    scope_id=normalized_principal_id,
                    payload_json={
                        **item_payload,
                        "batch": True,
                        "batch_id": (
                            audit_context.idempotency_key if audit_context is not None else ""
                        ),
                    },
                )

            batch_payload: dict[str, object] = {
                "reason": normalized_reason,
                "totals": totals,
                "principal_ids": normalized_principal_ids,
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="portal_user.batch_disable",
                outcome="succeeded" if totals["failed"] == 0 else "partial",
                scope_kind="portal_user_batch",
                scope_id=(audit_context.idempotency_key if audit_context is not None else ""),
                payload_json=batch_payload,
            )
            session.commit()

        return {
            "reason": normalized_reason,
            "items": items,
            "totals": totals,
            "total": len(items),
        }

    def list_admin_accounts(
        self,
        *,
        q: str | None = None,
        status: str | None = None,
        expires_before: datetime | None = None,
        coverage_state: str | None = None,
        package_kind: str | None = None,
        top_plan_id: str | None = None,
        exclude_internal: bool = False,
        sort: str = "created_at",
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, object]:
        normalized_query = " ".join(str(q or "").strip().lower().split())
        normalized_sort = sort if sort in {"created_at", "display_name", "risk"} else "created_at"
        normalized_offset = max(0, int(offset or 0))

        def account_payload_for(item: dict[str, object]) -> dict[str, object]:
            account_payload = item.get("account")
            return account_payload if isinstance(account_payload, dict) else {}

        def account_display_sort_key(item: dict[str, object]) -> tuple[str, str]:
            account_payload = account_payload_for(item)
            metadata = account_payload.get("metadata")
            metadata_payload = metadata if isinstance(metadata, dict) else {}
            display_name = (
                str(metadata_payload.get("operator_display_name") or "").strip()
                or str(account_payload.get("name") or "").strip()
                or str(account_payload.get("account_id") or "").strip()
            )
            return (display_name.lower(), str(account_payload.get("account_id") or ""))

        def account_risk_sort_key(item: dict[str, object]) -> tuple[int, datetime, str, str]:
            account_payload = account_payload_for(item)
            account_status = str(account_payload.get("status") or "")
            expiry_raw = item.get("nearest_expiry_at")
            expiry = expiry_raw if isinstance(expiry_raw, datetime) else None
            if expiry is None and isinstance(expiry_raw, str) and expiry_raw:
                try:
                    expiry = datetime.fromisoformat(expiry_raw.replace("Z", "+00:00"))
                except ValueError:
                    expiry = None
            now = self.now_factory()
            if expiry is not None and expiry.tzinfo is None and now.tzinfo is not None:
                expiry = expiry.replace(tzinfo=now.tzinfo)
            risk_rank = 3
            if account_status == "suspended":
                risk_rank = 0
            elif bool(item.get("coverage_follow_up_required")):
                risk_rank = 1
            elif expiry is not None and expiry <= now + timedelta(days=14):
                risk_rank = 2
            display_name, account_id = account_display_sort_key(item)
            return (
                risk_rank,
                expiry or datetime.max.replace(tzinfo=now.tzinfo),
                display_name,
                account_id,
            )

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
                limit=None
                if coverage_state
                or package_kind
                or top_plan_id
                or normalized_query
                or normalized_sort in {"display_name", "risk"}
                or normalized_offset
                else limit,
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
            if normalized_query:
                account_payload = account_payload_for(item)
                raw_metadata = account_payload.get("metadata")
                metadata: dict[str, object] = (
                    cast(dict[str, object], raw_metadata) if isinstance(raw_metadata, dict) else {}
                )
                searchable_text = " ".join(
                    str(value or "")
                    for value in [
                        account_payload.get("account_id"),
                        account_payload.get("name"),
                        metadata.get("operator_display_name"),
                        metadata.get("operator_note"),
                        metadata.get("account_status_note"),
                        item.get("display_package_label"),
                        item.get("package_kind"),
                        item.get("coverage_state"),
                        item.get("top_plan_id"),
                    ]
                ).lower()
                if not all(term in searchable_text for term in normalized_query.split(" ")):
                    continue
            items.append(item)
        hidden_internal_total = sum(
            1
            for item in items
            if self._is_internal_or_malformed_admin_account(item)
        )
        if exclude_internal:
            items = [
                item
                for item in items
                if not self._is_internal_or_malformed_admin_account(item)
            ]
        if normalized_sort == "display_name":
            items = sorted(items, key=account_display_sort_key)
        elif normalized_sort == "risk":
            items = sorted(items, key=account_risk_sort_key)
        total = len(items)
        if normalized_offset:
            items = items[normalized_offset:]
        if limit > 0:
            items = items[:limit]
        return {
            "filters": {
                "q": normalized_query,
                "status": status or "",
                "expires_before": self._serialize_datetime(expires_before),
                "coverage_state": coverage_state or "",
                "package_kind": package_kind or "",
                "top_plan_id": top_plan_id or "",
                "exclude_internal": exclude_internal,
                "sort": normalized_sort,
                "offset": normalized_offset,
                "limit": limit,
            },
            "items": items,
            "total": total,
            "hidden_internal_total": hidden_internal_total,
            "pagination": {
                "offset": normalized_offset,
                "limit": limit,
                "total": total,
                "has_more": normalized_offset + len(items) < total,
            },
        }

    @staticmethod
    def _is_internal_or_malformed_admin_account(item: dict[str, object]) -> bool:
        account = item.get("account")
        account_payload = account if isinstance(account, dict) else {}
        metadata = account_payload.get("metadata")
        metadata_payload = metadata if isinstance(metadata, dict) else {}
        searchable = " ".join(
            str(value or "")
            for value in (
                account_payload.get("account_id"),
                account_payload.get("name"),
                metadata_payload.get("operator_display_name"),
            )
        )
        return bool(
            _ADMIN_INTERNAL_ACCOUNT_RE.search(searchable)
            or _ADMIN_MALFORMED_ACCOUNT_RE.search(searchable)
        )

    def get_admin_coverage_work_queue(
        self,
        *,
        limit: int = 100,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            accounts = repository.list_accounts(limit=None)
            account_ids = [account.account_id for account in accounts]
            subscriptions = repository.list_subscriptions(account_ids=account_ids, limit=None)
            sites = repository.list_sites(account_ids=account_ids, limit=None)
            site_ids = [site.site_id for site in sites]
            active_key_counts = repository.count_site_keys_by_site(
                site_ids=site_ids,
                statuses=[SITE_API_KEY_STATUS_ACTIVE],
            )
            latest_billing_by_site = repository.get_latest_billing_snapshots_by_site(
                site_ids=site_ids,
            )

        service = cast(Any, self)
        subscriptions_by_account: dict[str, list[AccountSubscription]] = defaultdict(list)
        for subscription in subscriptions:
            subscriptions_by_account[subscription.account_id].append(subscription)

        sites_by_account: dict[str, list[Any]] = defaultdict(list)
        for site in sites:
            if site.account_id:
                sites_by_account[site.account_id].append(site)

        now = self.now_factory()
        items: list[dict[str, object]] = []
        for account in accounts:
            account_sites = sites_by_account.get(account.account_id, [])
            account_subscriptions = subscriptions_by_account.get(account.account_id, [])
            primary_subscription = service._select_primary_subscription(account_subscriptions)
            package_summary = service._build_subscription_package_summary(
                primary_subscription,
                site_count=len(account_sites),
            )
            site_count = len(account_sites)
            active_site_count = sum(
                1
                for site in account_sites
                if str(getattr(site, "status", "") or "") == SITE_STATUS_ACTIVE
            )
            active_key_site_count = sum(
                1
                for site in account_sites
                if int(active_key_counts.get(str(getattr(site, "site_id", "") or ""), 0) or 0) > 0
            )
            missing_key_site_count = max(0, site_count - active_key_site_count)
            subscription_status = str(getattr(primary_subscription, "status", "") or "")
            coverage_state = str(package_summary.get("coverage_state") or "")
            raw_period_end_at = getattr(primary_subscription, "current_period_end_at", None)
            period_end_at = (
                self._normalize_datetime(raw_period_end_at)
                if isinstance(raw_period_end_at, datetime)
                else None
            )
            days_until_end: int | None = None
            if period_end_at is not None:
                days_until_end = int((period_end_at - now).total_seconds() // 86400)
                if (period_end_at - now).total_seconds() % 86400:
                    days_until_end += 1
            billing_status: dict[str, object] = {
                "status": "missing" if site_count > 0 else "not_applicable",
                "summary": "",
                "fresh_site_count": 0,
                "stale_site_count": 0,
                "missing_site_count": site_count,
            }
            if primary_subscription is not None:
                period_start_at, resolved_period_end_at = service._resolve_period(
                    primary_subscription,
                    now,
                )
                billing_status = service._build_subscription_billing_snapshot_status(
                    subscription=primary_subscription,
                    sites=account_sites,
                    latest_billing_snapshots=latest_billing_by_site,
                    period_start_at=period_start_at,
                    period_end_at=resolved_period_end_at,
                )

            reason_code = ""
            reason_label = ""
            recommended_action = ""
            action_label = ""
            action_href = ""
            severity = "ok"

            if primary_subscription is None and coverage_state == "uncovered" and site_count > 0:
                severity = "error"
                reason_code = "missing_package_coverage"
                reason_label = "Customer has sites but no active package coverage."
                recommended_action = "change_customer_package"
                action_label = "Open package actions"
                action_href = f"/admin/accounts/{account.account_id}#coverage-actions"
            elif subscription_status and subscription_status not in {"active", "trialing"}:
                severity = "error"
                reason_code = "subscription_lifecycle_risk"
                reason_label = "Subscription status can block service continuity."
                recommended_action = "repair_subscription_lifecycle"
                action_label = "Inspect subscription"
                action_href = (
                    f"/admin/subscriptions/{primary_subscription.subscription_id}"
                    if primary_subscription is not None
                    else f"/admin/accounts/{account.account_id}#coverage-actions"
                )
            elif str(billing_status.get("status") or "") in {"missing", "stale"} and site_count > 0:
                severity = "warning"
                reason_code = "billing_snapshot_follow_up"
                reason_label = "Current-period billing snapshot needs follow-up."
                recommended_action = "inspect_billing_snapshot"
                action_label = "Inspect subscription"
                action_href = (
                    f"/admin/subscriptions/{primary_subscription.subscription_id}"
                    if primary_subscription is not None
                    else f"/admin/accounts/{account.account_id}#coverage-actions"
                )
            elif days_until_end is not None and 0 <= days_until_end <= 14:
                severity = "warning"
                reason_code = "subscription_expiring_soon"
                reason_label = "Current period ends soon."
                recommended_action = "review_renewal"
                action_label = "Inspect subscription"
                action_href = (
                    f"/admin/subscriptions/{primary_subscription.subscription_id}"
                    if primary_subscription is not None
                    else f"/admin/accounts/{account.account_id}#coverage-actions"
                )
            elif active_site_count < site_count:
                severity = "warning"
                reason_code = "site_status_follow_up"
                reason_label = "One or more sites are not active."
                recommended_action = "inspect_site_footprint"
                action_label = "Open site footprint"
                action_href = f"/admin/accounts/{account.account_id}#site-footprint"
            elif missing_key_site_count > 0:
                severity = "warning"
                reason_code = "site_key_missing"
                reason_label = "One or more sites lack active Cloud API key coverage."
                recommended_action = "inspect_site_key_coverage"
                action_label = "Open site footprint"
                action_href = f"/admin/accounts/{account.account_id}#site-footprint"
            elif site_count > 0:
                severity = "ok"
                reason_code = "service_coverage_aligned"
                reason_label = "Package, subscription, site, key, and billing evidence are aligned."
                recommended_action = "inspect_when_needed"
                action_label = "Open customer"
                action_href = f"/admin/accounts/{account.account_id}"
            else:
                severity = "inactive"
                reason_code = "no_site_footprint"
                reason_label = "Customer has no site footprint yet."
                recommended_action = "wait_for_site_onboarding"
                action_label = "Open customer"
                action_href = f"/admin/accounts/{account.account_id}"

            if severity == "ok" and reason_code == "service_coverage_aligned":
                priority = 90
            elif severity == "inactive":
                priority = 100
            elif severity == "error":
                priority = 0
            else:
                priority = 10
            if reason_code == "missing_package_coverage":
                priority = 0
            elif reason_code == "subscription_lifecycle_risk":
                priority = 1
            elif reason_code == "billing_snapshot_follow_up":
                priority = 2
            elif reason_code == "subscription_expiring_soon":
                priority = 3
            elif reason_code == "site_status_follow_up":
                priority = 4
            elif reason_code == "site_key_missing":
                priority = 5

            items.append(
                {
                    "account": service._serialize_account(account),
                    "primary_subscription": (
                        service._serialize_subscription(primary_subscription)
                        if primary_subscription is not None
                        else None
                    ),
                    "package": package_summary,
                    "severity": severity,
                    "priority": priority,
                    "reason_code": reason_code,
                    "reason_label": reason_label,
                    "recommended_action": recommended_action,
                    "action_label": action_label,
                    "action_href": action_href,
                    "evidence": {
                        "site_count": site_count,
                        "active_site_count": active_site_count,
                        "active_key_site_count": active_key_site_count,
                        "missing_key_site_count": missing_key_site_count,
                        "subscription_status": subscription_status or "missing",
                        "billing_snapshot_status": billing_status,
                        "current_period_end_at": self._serialize_datetime(period_end_at),
                        "days_until_end": days_until_end,
                    },
                }
            )

        def work_queue_sort_key(item: dict[str, object]) -> tuple[int, str, str]:
            priority_source = item.get("priority")
            priority = self._coerce_int(priority_source if priority_source else 100)
            account = item.get("account")
            account_payload: dict[str, object] = (
                cast(dict[str, object], account) if isinstance(account, dict) else {}
            )
            return (
                priority,
                str(account_payload.get("name") or ""),
                str(account_payload.get("account_id") or ""),
            )

        items.sort(key=work_queue_sort_key)
        visible_items = items[:limit] if limit > 0 else items
        reason_counts = Counter(str(item.get("reason_code") or "") for item in items)
        severity_counts = Counter(str(item.get("severity") or "") for item in items)
        return {
            "generated_at": self._serialize_datetime(now),
            "filters": {"limit": limit},
            "summary": {
                "total": len(items),
                "visible": len(visible_items),
                "needs_action": sum(
                    1 for item in items if str(item.get("severity") or "") in {"error", "warning"}
                ),
                "error": severity_counts.get("error", 0),
                "warning": severity_counts.get("warning", 0),
                "ok": severity_counts.get("ok", 0),
                "inactive": severity_counts.get("inactive", 0),
                "reason_counts": dict(reason_counts),
            },
            "items": visible_items,
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
            reconciled = cast(Any, self)._reconcile_account_subscription_state_in_session(
                repository=repository,
                account_id=account_id,
                now=self.now_factory(),
            )
            sites = repository.list_sites(account_id=account_id, limit=None)
            subscriptions = repository.list_subscriptions(account_id=account_id, limit=None)
            primary_subscription = cast(Any, self)._select_primary_subscription(subscriptions)
            if primary_subscription is not None:
                subscriptions = [
                    primary_subscription,
                    *[
                        subscription
                        for subscription in subscriptions
                        if subscription.subscription_id != primary_subscription.subscription_id
                    ],
                ]
            active_key_counts = repository.count_site_keys_by_site(
                site_ids=[site.site_id for site in sites],
                statuses=[SITE_API_KEY_STATUS_ACTIVE],
            )
            if reconciled is not None:
                session.commit()

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
            reconciled = cast(Any, self)._reconcile_account_subscription_state_in_session(
                repository=repository,
                account_id=account_id,
                now=now,
            )
            sites = [
                site
                for site in repository.list_sites(account_id=account_id, limit=None)
                if str(getattr(site, "status", "") or "") != SITE_STATUS_ARCHIVED
            ]
            site_ids = [str(site.site_id or "") for site in sites if str(site.site_id or "")]
            subscriptions = repository.list_subscriptions(account_id=account_id, limit=None)
            if reconciled is not None:
                session.commit()
            primary_subscription = cast(Any, self)._select_primary_subscription(subscriptions)
            plan_version = cast(Any, self)._resolve_current_subscription_plan_version(
                repository,
                primary_subscription,
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
                event_types=AI_CREDIT_VISIBLE_LEDGER_EVENT_TYPES,
                since=period_start_at,
                until=period_end_at,
                limit=None,
            )
            paid_credit = cast(Any, self)._paid_credit_balance_in_session(
                repository,
                account_id=account_id,
                now=now,
            )
            totals = cast(Any, self)._aggregate_meter_events(meter_events)
            budgets = cast(Any, self)._resolve_effective_subscription_budgets(
                plan_version=plan_version,
                subscription=primary_subscription,
            )
            policy = cast(Any, self)._normalize_commercial_policy(
                getattr(plan_version, "policy_json", None)
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
            knowledge_counts = repository.summarize_site_knowledge_current_counts(site_ids=site_ids)
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
                snapshot=None,
                plan_version=plan_version,
            )
            session.commit()

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
        site_limit = service._resolve_site_limit(
            plan_version=plan_version,
            subscription=primary_subscription,
        )
        concurrency = service._normalize_concurrency(
            getattr(plan_version, "concurrency_json", None)
        )
        vector_document_limit = cast(Any, self)._resolve_account_vector_documents_limit(
            snapshot=None,
            plan_version=plan_version,
        )
        ledger_source = bool(credit_ledger_entries)
        credit_rate_version = AI_CREDIT_RATE_VERSION if ledger_source else "ai-credit-estimate-v2"
        credit_ledger_summary = self._summarize_credit_ledger_entries(credit_ledger_entries)
        credit_breakdown = build_credit_breakdown_from_ledger(credit_ledger_entries)
        if not credit_breakdown:
            credit_breakdown = self._build_admin_account_credit_breakdown(
                meter_events=meter_events,
                totals=totals,
                indexed_document_count=service._coerce_int(
                    knowledge_index_usage.get("indexed_documents")
                ),
                indexed_chunk_count=service._coerce_int(
                    knowledge_index_usage.get("indexed_chunks")
                ),
            )
        credit_used = round(
            sum(service._coerce_float(item.get("credits")) for item in credit_breakdown),
            6,
        )
        if ledger_source:
            credit_used = package_credit_used(credit_ledger_entries)
        package_credit_limit = service._coerce_float(
            budgets.get("max_ai_credits_per_period")
        )
        if package_credit_limit <= 0:
            package_credit_limit = service._coerce_float(budgets.get("max_runs_per_period"))
        paid_credit_remaining = service._coerce_float(paid_credit.get("remaining"))
        package_credit_remaining = max(0.0, package_credit_limit - credit_used)
        credit_limit = round(
            credit_used + package_credit_remaining + paid_credit_remaining,
            6,
        )
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
                limit=vector_document_limit,
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
        status = (
            "limited"
            if "limited" in [credit_status, *resource_statuses]
            else ("near_limit" if "near_limit" in [credit_status, *resource_statuses] else "ok")
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
                    "package_limit": round(package_credit_limit, 6),
                    "package_remaining": round(package_credit_remaining, 6),
                    "paid_remaining": round(paid_credit_remaining, 6),
                    "paid_grant_count": int(paid_credit.get("grant_count") or 0),
                    "paid_next_expires_at": paid_credit.get("next_expires_at") or "",
                    "total_remaining": round(
                        package_credit_remaining + paid_credit_remaining,
                        6,
                    ),
                },
            ),
            "credit_policy": {
                "rate_version": AI_CREDIT_RATE_VERSION,
                "period_policy": "subscription_period",
                "renewal_policy": "monthly_plan_grant_resets_each_period",
                "topup_policy": "operator_topups_apply_to_target_period_only",
                "paid_credit_policy": "payment_order_grants_expire_independently",
            },
            "resource_limits": resource_limits,
            "internal_limits": internal_limits,
            "breakdown": credit_breakdown,
            "credit_ledger_summary": credit_ledger_summary,
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

    def apply_admin_account_credit_adjustment(
        self,
        account_id: str,
        *,
        event_type: str,
        credit_delta: float,
        reason: str,
        note: str = "",
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_event_type = str(event_type or "").strip().lower()
        if normalized_event_type not in {
            CREDIT_LEDGER_EVENT_GRANT,
            CREDIT_LEDGER_EVENT_ADJUSTMENT,
        }:
            raise CommercialValidationError(
                "service.credit_adjustment_event_type_invalid",
                "credit adjustment event_type must be either grant or adjustment",
            )
        normalized_reason = str(reason or "").strip()
        if not normalized_reason:
            raise CommercialValidationError(
                "service.credit_adjustment_reason_required",
                "credit adjustment requires an operator reason",
            )
        normalized_delta = round(self._coerce_float(credit_delta), 6)
        if normalized_delta == 0:
            raise CommercialValidationError(
                "service.credit_adjustment_delta_required",
                "credit adjustment requires a non-zero credit delta",
            )
        if normalized_event_type == CREDIT_LEDGER_EVENT_GRANT and normalized_delta <= 0:
            raise CommercialValidationError(
                "service.credit_grant_delta_invalid",
                "credit grant requires a positive credit delta",
            )

        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            account = repository.get_account(account_id)
            if account is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )
            subscriptions = repository.list_subscriptions(account_id=account_id, limit=None)
            primary_subscription = cast(Any, self)._select_primary_subscription(subscriptions)
            if primary_subscription is None:
                raise CommercialValidationError(
                    "service.credit_adjustment_subscription_required",
                    "credit adjustment requires a current account subscription",
                )
            period_start_at, period_end_at = cast(Any, self)._resolve_period(
                primary_subscription,
                now,
            )
            ledger_idempotency = (
                f"account_credit_adjustment:{account_id}:"
                f"{audit_context.idempotency_key if audit_context else uuid4().hex}"
            )
            entry = repository.record_credit_ledger_entry(
                account_id=account_id,
                site_id=None,
                subscription_id=primary_subscription.subscription_id,
                plan_version_id=primary_subscription.plan_version_id,
                run_id=None,
                provider_call_id=None,
                event_type=normalized_event_type,
                source_type="operator_credit_adjustment",
                source_id=ledger_idempotency,
                credit_delta=normalized_delta,
                quantity=abs(normalized_delta),
                unit="credit",
                rate=1.0,
                rate_unit=None,
                rate_version=AI_CREDIT_RATE_VERSION,
                idempotency_key=ledger_idempotency,
                metadata_json={
                    "reason": normalized_reason,
                    "note": str(note or "").strip(),
                    "actor_kind": audit_context.actor_kind if audit_context else "",
                    "actor_ref": audit_context.actor_ref if audit_context else "",
                    "period_start_at": self._serialize_datetime(period_start_at),
                    "period_end_at": self._serialize_datetime(period_end_at),
                },
                created_at=now,
            )
            summary_entries = repository.list_credit_ledger_entries(
                account_ids=[account_id],
                subscription_id=primary_subscription.subscription_id,
                event_types=AI_CREDIT_VISIBLE_LEDGER_EVENT_TYPES,
                since=period_start_at,
                until=period_end_at,
                limit=None,
            )
            payload: dict[str, object] = {
                "account_id": account_id,
                "period_start_at": self._serialize_datetime(period_start_at),
                "period_end_at": self._serialize_datetime(period_end_at),
                "entry": self._serialize_credit_ledger_entry(entry, include_internal=True),
                "summary": self._summarize_credit_ledger_entries(summary_entries),
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="credit_ledger.adjustment",
                outcome="succeeded",
                account_id=account_id,
                subscription_id=primary_subscription.subscription_id,
                plan_id=primary_subscription.plan_id,
                plan_version_id=primary_subscription.plan_version_id,
                scope_kind="account",
                scope_id=account_id,
                payload_json=payload,
            )
            session.commit()
        return payload

    def get_admin_account_credit_ledger(
        self,
        account_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        source_type: str | None = None,
        site_ids: list[str] | None = None,
    ) -> dict[str, object]:
        now = self.now_factory()
        normalized_limit = min(100, max(1, int(limit or 50)))
        normalized_offset = max(0, int(offset or 0))
        normalized_source_type = str(source_type or "").strip()
        source_types = [normalized_source_type] if normalized_source_type else None
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            account = repository.get_account(account_id)
            if account is None:
                raise CommercialNotFoundError(
                    "service.account_not_found",
                    f"account '{account_id}' was not found",
                )
            subscriptions = repository.list_subscriptions(account_id=account_id, limit=None)
            primary_subscription = cast(Any, self)._select_primary_subscription(subscriptions)
            period_start_at, period_end_at = cast(Any, self)._resolve_period(
                primary_subscription,
                now,
            )
            subscription_id = (
                primary_subscription.subscription_id if primary_subscription is not None else None
            )
            entries = repository.list_credit_ledger_entries(
                account_ids=[account_id],
                site_ids=site_ids,
                subscription_id=subscription_id,
                event_types=AI_CREDIT_VISIBLE_LEDGER_EVENT_TYPES,
                source_types=source_types,
                since=period_start_at,
                until=period_end_at,
                limit=normalized_limit,
                offset=normalized_offset,
            )
            total = repository.count_credit_ledger_entries(
                account_ids=[account_id],
                site_ids=site_ids,
                subscription_id=subscription_id,
                event_types=AI_CREDIT_VISIBLE_LEDGER_EVENT_TYPES,
                source_types=source_types,
                since=period_start_at,
                until=period_end_at,
            )
            summary_entries = repository.list_credit_ledger_entries(
                account_ids=[account_id],
                site_ids=site_ids,
                subscription_id=subscription_id,
                event_types=AI_CREDIT_VISIBLE_LEDGER_EVENT_TYPES,
                source_types=source_types,
                since=period_start_at,
                until=period_end_at,
                limit=None,
            )
            run_records_by_id = {
                str(run.run_id): run
                for run in repository.list_run_records_by_ids(
                    [
                        str(getattr(entry, "run_id", "") or "")
                        for entry in entries
                        if str(getattr(entry, "run_id", "") or "").strip()
                    ]
                )
            }
            feature_by_entry_id = {
                str(getattr(entry, "ledger_entry_id", "") or ""): (
                    self._build_portal_credit_ledger_feature(
                        source_type=str(getattr(entry, "source_type", "") or ""),
                        run=run_records_by_id.get(str(getattr(entry, "run_id", "") or "")),
                    )
                )
                for entry in entries
                if self._credit_ledger_entry_category(
                    event_type=str(getattr(entry, "event_type", "") or ""),
                    source_type=str(getattr(entry, "source_type", "") or ""),
                )
                == "ai_usage"
            }

        service = cast(Any, self)
        breakdown = build_credit_breakdown_from_ledger(summary_entries)
        total_credits = round(
            sum(service._coerce_float(item.get("credits")) for item in breakdown),
            6,
        )
        ledger_summary = self._summarize_credit_ledger_entries(summary_entries)
        return {
            "account_id": account_id,
            "generated_at": self._serialize_datetime(now),
            "period_start_at": self._serialize_datetime(period_start_at),
            "period_end_at": self._serialize_datetime(period_end_at),
            "rate_version": AI_CREDIT_RATE_VERSION,
            "filters": {
                "source_type": normalized_source_type,
                "site_ids": site_ids or [],
                "limit": normalized_limit,
                "offset": normalized_offset,
            },
            "pagination": {
                "limit": normalized_limit,
                "offset": normalized_offset,
                "total": total,
                "has_more": normalized_offset + len(entries) < total,
            },
            "summary": {
                "total_credits": total_credits,
                **ledger_summary,
                "entry_count": total,
                "breakdown": breakdown,
            },
            "items": [
                {
                    **self._serialize_credit_ledger_entry(entry, include_internal=True),
                    **feature_by_entry_id.get(str(getattr(entry, "ledger_entry_id", "") or ""), {}),
                }
                for entry in entries
            ],
        }

    def get_portal_account_quota_summary(self, account_id: str) -> dict[str, object]:
        summary = self.get_admin_account_quota_summary(account_id)
        raw_breakdown = summary.get("breakdown")
        breakdown: list[object] = raw_breakdown if isinstance(raw_breakdown, list) else []
        raw_credit = summary.get("credit")
        credit: dict[str, object] = (
            cast(dict[str, object], raw_credit) if isinstance(raw_credit, dict) else {}
        )
        raw_resource_limits = summary.get("resource_limits")
        raw_resource_limits = raw_resource_limits if isinstance(raw_resource_limits, list) else []
        resource_by_key = {
            str(item.get("key") or ""): item
            for item in raw_resource_limits
            if isinstance(item, dict)
        }
        resource_limits = [
            resource_by_key[key]
            for key in ("bound_sites", "vector_documents")
            if key in resource_by_key
        ]
        visible_statuses = [
            str(item.get("status") or "ok")
            for item in [credit, *resource_limits]
            if isinstance(item, dict)
        ]
        portal_status = (
            "limited"
            if "limited" in visible_statuses
            else "near_limit"
            if "near_limit" in visible_statuses
            else "ok"
        )
        return {
            "account_id": str(summary.get("account_id") or account_id),
            "generated_at": summary.get("generated_at"),
            "period_start_at": summary.get("period_start_at"),
            "period_end_at": summary.get("period_end_at"),
            "status": portal_status,
            "credit": credit,
            "credit_ledger_summary": (
                summary.get("credit_ledger_summary")
                if isinstance(summary.get("credit_ledger_summary"), dict)
                else {}
            ),
            "credit_policy": (
                summary.get("credit_policy")
                if isinstance(summary.get("credit_policy"), dict)
                else {}
            ),
            "resource_limits": resource_limits,
            "breakdown": breakdown,
            "credit_usage_detail": self._build_portal_credit_usage_detail(
                credit=credit,
                breakdown=breakdown,
                recent_items=[],
                generated_at=summary.get("generated_at"),
                period_start_at=summary.get("period_start_at"),
                period_end_at=summary.get("period_end_at"),
            ),
        }

    def get_portal_account_credit_ledger(
        self,
        account_id: str,
        *,
        limit: int = 25,
        offset: int = 0,
        site_id: str | None = None,
    ) -> dict[str, object]:
        normalized_site_id = str(site_id or "").strip()
        ledger = self.get_admin_account_credit_ledger(
            account_id,
            limit=min(50, max(1, int(limit or 25))),
            offset=max(0, int(offset or 0)),
            site_ids=[normalized_site_id] if normalized_site_id else None,
        )
        raw_summary = ledger.get("summary")
        summary: dict[str, object] = (
            cast(dict[str, object], raw_summary) if isinstance(raw_summary, dict) else {}
        )
        raw_breakdown = summary.get("breakdown")
        breakdown: list[object] = raw_breakdown if isinstance(raw_breakdown, list) else []
        items = [
            self._serialize_credit_ledger_entry(entry, include_internal=False)
            for entry in self._credit_ledger_entries_from_payload(ledger.get("items"))
        ]
        return {
            "account_id": str(ledger.get("account_id") or account_id),
            "generated_at": ledger.get("generated_at"),
            "period_start_at": ledger.get("period_start_at"),
            "period_end_at": ledger.get("period_end_at"),
            "rate_version": ledger.get("rate_version"),
            "pagination": ledger.get("pagination"),
            "summary": summary,
            "usage_detail": self._build_portal_credit_usage_detail(
                credit={},
                breakdown=breakdown,
                recent_items=items,
                generated_at=ledger.get("generated_at"),
                period_start_at=ledger.get("period_start_at"),
                period_end_at=ledger.get("period_end_at"),
            ),
            "items": items,
        }

    def _credit_ledger_entries_from_payload(self, items: object) -> list[object]:
        return items if isinstance(items, list) else []

    def _summarize_credit_ledger_entries(self, entries: Sequence[object]) -> dict[str, object]:
        service = cast(Any, self)
        consumed = 0.0
        granted = 0.0
        adjustment = 0.0
        refund = 0.0
        net_delta = 0.0
        by_event_type: dict[str, float] = defaultdict(float)
        by_category: dict[str, float] = defaultdict(float)

        for entry in entries:
            if isinstance(entry, dict):
                event_type = str(entry.get("event_type") or "")
                source_type = str(entry.get("source_type") or "")
                delta = service._coerce_float(entry.get("credit_delta"))
            else:
                event_type = str(getattr(entry, "event_type", "") or "")
                source_type = str(getattr(entry, "source_type", "") or "")
                delta = service._coerce_float(getattr(entry, "credit_delta", 0.0))

            category = self._credit_ledger_entry_category(
                event_type=event_type,
                source_type=source_type,
            )
            net_delta += delta
            by_event_type[event_type] += delta
            by_category[category] += delta
            if event_type == CREDIT_LEDGER_EVENT_CONSUME:
                consumed += max(0.0, -delta)
            elif event_type == CREDIT_LEDGER_EVENT_GRANT:
                granted += max(0.0, delta)
            elif event_type == CREDIT_LEDGER_EVENT_ADJUSTMENT:
                adjustment += delta
            elif event_type == CREDIT_LEDGER_EVENT_REFUND:
                refund += max(0.0, delta)

        return {
            "consumed_credits": round(consumed, 6),
            "granted_credits": round(granted, 6),
            "adjustment_credits": round(adjustment, 6),
            "refund_credits": round(refund, 6),
            "net_credit_delta": round(net_delta, 6),
            "net_used_credits": round(max(0.0, -net_delta), 6),
            "event_type_totals": {
                key: round(value, 6) for key, value in sorted(by_event_type.items())
            },
            "category_totals": {
                key: {
                    "label": AI_CREDIT_LEDGER_CATEGORY_LABELS.get(key, key),
                    "net_credit_delta": round(value, 6),
                }
                for key, value in sorted(by_category.items())
            },
            "entry_count": len(entries),
        }

    def _build_portal_credit_usage_detail(
        self,
        *,
        credit: dict[str, object],
        breakdown: list[object],
        recent_items: list[dict[str, object]],
        generated_at: object,
        period_start_at: object,
        period_end_at: object,
    ) -> dict[str, object]:
        service = cast(Any, self)
        limit = service._coerce_float(credit.get("limit")) if credit else 0.0
        used = service._coerce_float(credit.get("used")) if credit else 0.0
        remaining = max(0.0, limit - used) if limit > 0 else None
        return {
            "surface": "portal_personal_credit_usage",
            "default_visibility": "cloud_portal_only",
            "local_addon_policy": "summary_and_link_only",
            "generated_at": generated_at,
            "period": {
                "start_at": period_start_at,
                "end_at": period_end_at,
            },
            "summary": {
                "used": round(used, 6),
                "limit": round(limit, 6),
                "remaining": round(remaining, 6) if remaining is not None else None,
                "status": str(credit.get("status") or ""),
                "unit": str(credit.get("unit") or "credit"),
                "rate_version": str(credit.get("rate_version") or AI_CREDIT_RATE_VERSION),
            },
            "breakdown": [
                self._portal_credit_breakdown_item(item)
                for item in breakdown
                if isinstance(item, dict)
            ],
            "recent_items": recent_items[:10],
            "copy": {
                "title": "AI credit usage",
                "summary": "Current-period Cloud usage is grouped by capability.",
                "addon_summary": "View credit details in the Cloud portal.",
            },
            "legend": [
                {"category": key, "label": label}
                for key, label in AI_CREDIT_LEDGER_CATEGORY_LABELS.items()
            ],
            "portal_paths": {
                "credit_usage": "/portal/usage",
                "credit_ledger": "/portal/usage/credits",
            },
        }

    def _portal_credit_breakdown_item(self, item: dict[str, object]) -> dict[str, object]:
        service = cast(Any, self)
        key = str(item.get("key") or "")
        return {
            "key": key,
            "label": str(item.get("label") or AI_CREDIT_COMPONENT_LABELS.get(key, key)),
            "quantity": service._coerce_float(item.get("quantity")),
            "unit": str(item.get("unit") or "credit"),
            "rate": service._coerce_float(item.get("rate")),
            "rate_unit": item.get("rate_unit"),
            "credits": service._coerce_float(item.get("credits")),
            "capability_group": self._portal_credit_capability_group(key),
        }

    def _portal_credit_capability_group(self, source_type: str) -> str:
        if source_type.startswith("zhihu_"):
            return "zhihu_open_platform"
        if source_type == "web_search":
            return "search"
        if source_type.startswith("zhihu_direct_answer"):
            return "zhihu_open_platform"
        if source_type == "tokens_total":
            return "model_tokens"
        if source_type == "image_recommendation":
            return "image"
        if source_type.startswith("vector_"):
            return "site_knowledge"
        if source_type == "runs":
            return "hosted_runtime"
        return "other"

    def _credit_ledger_entry_category(self, *, event_type: str, source_type: str) -> str:
        if event_type == CREDIT_LEDGER_EVENT_CONSUME:
            return "ai_usage"
        if event_type == CREDIT_LEDGER_EVENT_GRANT:
            if source_type == "credit_pack_purchase":
                return "credit_pack_purchase"
            if source_type == "operator_credit_adjustment":
                return "operator_adjustment"
            return "monthly_plan_grant"
        if event_type == CREDIT_LEDGER_EVENT_ADJUSTMENT:
            if source_type == "credit_pack_refund":
                return "refund_adjustment"
            return "operator_adjustment"
        if event_type == CREDIT_LEDGER_EVENT_REFUND:
            return "refund"
        return "other"

    def _credit_ledger_entry_direction(self, credit_delta: float) -> str:
        if credit_delta > 0:
            return "credit_in"
        if credit_delta < 0:
            return "credit_out"
        return "neutral"

    def _credit_ledger_entry_explanation(
        self,
        *,
        event_type: str,
        source_type: str,
        category: str,
        credit_delta: float,
    ) -> str:
        credits = round(abs(credit_delta), 6)
        if category == "monthly_plan_grant":
            return f"Monthly package grant added {credits} AI credits to the current period."
        if category == "credit_pack_purchase":
            return f"Credit pack payment added {credits} AI credits after payment confirmation."
        if category == "ai_usage":
            label = AI_CREDIT_COMPONENT_LABELS.get(source_type, source_type or "AI capability")
            return f"{label} consumed {credits} AI credits."
        if category == "refund_adjustment":
            return f"Refund adjustment removed {credits} AI credits from the current period."
        if category == "operator_adjustment":
            direction = "added" if credit_delta >= 0 else "removed"
            return f"Operator adjustment {direction} {credits} AI credits."
        if category == "refund":
            return f"Refund event added {credits} AI credits back to the account."
        return f"{event_type or 'Credit'} ledger event recorded {credits} AI credits."

    def _build_portal_credit_ledger_feature(
        self,
        *,
        source_type: str,
        run: object | None,
    ) -> dict[str, object]:
        ability_name = str(getattr(run, "ability_name", "") or "").strip().lower()
        ability_family = str(getattr(run, "ability_family", "") or "").strip().lower()
        execution_kind = str(getattr(run, "execution_kind", "") or "").strip().lower()
        normalized_source = str(source_type or "").strip().lower()
        tokens = " ".join(
            token
            for token in (normalized_source, ability_name, ability_family, execution_kind)
            if token
        )

        if normalized_source.startswith("zhihu") or "zhihu" in tokens:
            feature_key = "topic_research"
        elif normalized_source == "web_search" or "web-search" in tokens:
            feature_key = "web_search"
        elif (
            "site-knowledge" in tokens
            or "site_knowledge" in tokens
            or ability_family == "knowledge"
            or execution_kind in {"embedding", "site_knowledge", "knowledge"}
            or normalized_source in {"vector_documents", "vector_chunks"}
        ):
            feature_key = "site_knowledge"
        elif (
            "image" in tokens
            or ability_family in {"vision", "image"}
            or normalized_source == "image_recommendation"
        ):
            feature_key = "image_assistance"
        elif "audio" in tokens or normalized_source == "audio_generation":
            feature_key = "audio_generation"
        elif (
            "article" in tokens
            or "content" in tokens
            or "writing" in tokens
            or "wp-ai-connector" in tokens
            or normalized_source in {"runs", "tokens", "tokens_total", "provider_calls_other"}
            or ability_family in {"text", "workflow"}
        ):
            feature_key = "content_generation"
        else:
            feature_key = "content_generation"

        labels = {
            "content_generation": (
                "Content writing",
                "The site used AI to draft, revise, or organize content.",
            ),
            "topic_research": (
                "Topic research",
                "The site used AI to look up public topics or hot-list information.",
            ),
            "web_search": (
                "Web search",
                "The site used AI to search public web information.",
            ),
            "site_knowledge": (
                "Site knowledge",
                "The site used AI to search or update its site knowledge.",
            ),
            "image_assistance": (
                "Image assistance",
                "The site used AI to recommend, generate, or process images.",
            ),
            "audio_generation": (
                "Audio generation",
                "The site used AI to generate or process audio.",
            ),
        }
        label, detail = labels[feature_key]
        return {
            "feature_key": feature_key,
            "feature_label": label,
            "feature_detail": detail,
        }

    def _serialize_credit_ledger_entry(
        self,
        entry: object,
        *,
        include_internal: bool = False,
    ) -> dict[str, object]:
        service = cast(Any, self)

        def value(key: str, default: object = None) -> object:
            if isinstance(entry, dict):
                return entry.get(key, default)
            return getattr(entry, key, default)

        credit_delta = service._coerce_float(value("credit_delta", 0.0))
        event_type = str(value("event_type", "") or "")
        source_type = str(value("source_type", "") or "")
        category = self._credit_ledger_entry_category(
            event_type=event_type,
            source_type=source_type,
        )
        created_at = value("created_at")
        payload: dict[str, object] = {
            "ledger_entry_id": str(value("ledger_entry_id", "") or ""),
            "site_id": str(value("site_id", "") or ""),
            "event_type": event_type,
            "source_type": source_type,
            "category": category,
            "category_label": AI_CREDIT_LEDGER_CATEGORY_LABELS.get(category, category),
            "direction": self._credit_ledger_entry_direction(credit_delta),
            "explanation": self._credit_ledger_entry_explanation(
                event_type=event_type,
                source_type=source_type,
                category=category,
                credit_delta=credit_delta,
            ),
            "source_id": str(value("source_id", "") or ""),
            "run_id": str(value("run_id", "") or ""),
            "credit_delta": credit_delta,
            "consumed_credits": max(0.0, -credit_delta),
            "granted_credits": max(0.0, credit_delta),
            "net_credit_delta": credit_delta,
            "quantity": service._coerce_float(value("quantity", 0.0)),
            "unit": str(value("unit", "") or ""),
            "rate": service._coerce_float(value("rate", 0.0)),
            "rate_unit": value("rate_unit"),
            "rate_version": str(value("rate_version", "") or ""),
            "created_at": self._serialize_datetime(
                created_at if isinstance(created_at, datetime | str) else None
            ),
        }
        if isinstance(entry, dict):
            for key in ("feature_key", "feature_label", "feature_detail"):
                if entry.get(key):
                    payload[key] = str(entry.get(key) or "")
        if include_internal:
            payload.update(
                {
                    "account_id": str(value("account_id", "") or ""),
                    "subscription_id": str(value("subscription_id", "") or ""),
                    "plan_version_id": str(value("plan_version_id", "") or ""),
                    "provider_call_id": value("provider_call_id"),
                    "metadata": (
                        value("metadata")
                        if isinstance(entry, dict)
                        else (getattr(entry, "metadata_json", None) or {})
                    ),
                }
            )
        return payload

    def _build_platform_credit_summary(
        self,
        *,
        meter_events: Sequence[object],
        ledger_entries: Sequence[object],
        previous_meter_events: Sequence[object],
        previous_ledger_entries: Sequence[object],
        window_days: int,
        start_at: datetime,
        end_at: datetime,
        previous_start_at: datetime,
        previous_end_at: datetime,
        knowledge_index_usage: dict[str, int],
        previous_knowledge_index_usage: dict[str, int],
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
                indexed_chunk_count=service._coerce_int(
                    knowledge_index_usage.get("indexed_chunks")
                ),
            )
        credit_used = round(
            sum(service._coerce_float(item.get("credits")) for item in breakdown),
            6,
        )
        previous_totals = service._aggregate_meter_events(previous_meter_events)
        previous_ledger_source = bool(previous_ledger_entries)
        previous_breakdown = build_credit_breakdown_from_ledger(previous_ledger_entries)
        if not previous_breakdown:
            previous_breakdown = self._build_admin_account_credit_breakdown(
                meter_events=previous_meter_events,
                totals=previous_totals,
                indexed_document_count=service._coerce_int(
                    previous_knowledge_index_usage.get("indexed_documents")
                ),
                indexed_chunk_count=service._coerce_int(
                    previous_knowledge_index_usage.get("indexed_chunks")
                ),
            )
        previous_credit_used = round(
            sum(service._coerce_float(item.get("credits")) for item in previous_breakdown),
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
        trend = self._build_platform_credit_trend(
            current_used=credit_used,
            previous_used=previous_credit_used,
            previous_start_at=previous_start_at,
            previous_end_at=previous_end_at,
        )
        watch_items = self._build_platform_credit_watch_items(
            current_used=credit_used,
            trend=trend,
            breakdown=breakdown,
            top_accounts=top_accounts,
            ledger_source=ledger_source,
            previous_ledger_source=previous_ledger_source,
        )
        return {
            "window_days": max(1, int(window_days or 1)),
            "period_start_at": self._serialize_datetime(start_at),
            "period_end_at": self._serialize_datetime(end_at),
            "previous_period_start_at": self._serialize_datetime(previous_start_at),
            "previous_period_end_at": self._serialize_datetime(previous_end_at),
            "credit": self._quota_metric(
                key="platform_ai_credits",
                label="Platform AI credits",
                used=credit_used,
                limit=0,
                unit="credit",
                extra={
                    "estimated": not ledger_source,
                    "rate_version": (
                        AI_CREDIT_RATE_VERSION if ledger_source else "ai-credit-estimate-v2"
                    ),
                    "scope": "platform",
                    "source": "ledger" if ledger_source else "estimate",
                },
            ),
            "breakdown": breakdown,
            "top_accounts": top_accounts,
            "trend": trend,
            "watch_items": watch_items,
        }

    def _build_platform_credit_trend(
        self,
        *,
        current_used: float,
        previous_used: float,
        previous_start_at: datetime,
        previous_end_at: datetime,
    ) -> dict[str, object]:
        service = cast(Any, self)
        current_value = round(service._coerce_float(current_used), 6)
        previous_value = round(service._coerce_float(previous_used), 6)
        delta = round(current_value - previous_value, 6)
        if previous_value > 0:
            delta_percent = round((delta / previous_value) * 100, 2)
        elif current_value > 0:
            delta_percent = None
        else:
            delta_percent = 0.0
        if current_value > 0 and previous_value <= 0:
            status = "new_activity"
        elif abs(delta) < 0.000001:
            status = "flat"
        elif delta > 0:
            status = "up"
        else:
            status = "down"
        return {
            "current_used": current_value,
            "previous_used": previous_value,
            "delta": delta,
            "delta_percent": delta_percent,
            "status": status,
            "previous_period_start_at": self._serialize_datetime(previous_start_at),
            "previous_period_end_at": self._serialize_datetime(previous_end_at),
        }

    def _build_platform_credit_watch_items(
        self,
        *,
        current_used: float,
        trend: dict[str, object],
        breakdown: list[dict[str, object]],
        top_accounts: list[dict[str, object]],
        ledger_source: bool,
        previous_ledger_source: bool,
    ) -> list[dict[str, object]]:
        service = cast(Any, self)
        current_value = service._coerce_float(current_used)
        items: list[dict[str, object]] = []
        delta = service._coerce_float(trend.get("delta"))
        previous_value = service._coerce_float(trend.get("previous_used"))
        delta_percent = trend.get("delta_percent")
        if current_value > 0 and previous_value <= 0:
            items.append(
                {
                    "code": "credit_new_activity",
                    "severity": "info",
                    "title": "New platform credit activity",
                    "detail": "The previous comparison window had no AI credit consumption.",
                    "metric": "ai_credits",
                    "value": current_value,
                    "href": "/admin/accounts",
                }
            )
        elif (
            current_value >= 10
            and delta >= 10
            and isinstance(delta_percent, (int, float))
            and float(delta_percent) >= 50
        ):
            items.append(
                {
                    "code": "credit_usage_spike",
                    "severity": "warning",
                    "title": "AI credit usage rose sharply",
                    "detail": "Current usage is at least 50% above the previous comparison window.",
                    "metric": "ai_credits",
                    "value": current_value,
                    "delta": round(delta, 6),
                    "href": "/admin/accounts",
                }
            )

        top_account = top_accounts[0] if top_accounts else None
        if top_account is not None and current_value >= 10:
            account_credits = service._coerce_float(top_account.get("credits"))
            if account_credits / max(current_value, 1.0) >= 0.6:
                account_id = str(top_account.get("account_id") or "")
                items.append(
                    {
                        "code": "credit_account_concentration",
                        "severity": "warning",
                        "title": "Consumption is concentrated in one account",
                        "detail": (
                            "The top account accounts for at least 60% of this window's AI credits."
                        ),
                        "metric": "ai_credits",
                        "value": round(account_credits, 6),
                        "account_id": account_id,
                        "href": (
                            f"/admin/accounts/{account_id}" if account_id else "/admin/accounts"
                        ),
                    }
                )

        top_component = max(
            breakdown,
            key=lambda item: service._coerce_float(item.get("credits")),
            default=None,
        )
        if top_component is not None and current_value >= 10:
            component_credits = service._coerce_float(top_component.get("credits"))
            if component_credits / max(current_value, 1.0) >= 0.65:
                items.append(
                    {
                        "code": "credit_component_concentration",
                        "severity": "info",
                        "title": "One meter family dominates usage",
                        "detail": (
                            "One credit component accounts for at least 65% of "
                            "this window's consumption."
                        ),
                        "metric": str(top_component.get("key") or "ai_credits"),
                        "value": round(component_credits, 6),
                        "href": "/admin/accounts",
                    }
                )

        if not ledger_source and previous_ledger_source:
            items.append(
                {
                    "code": "credit_source_changed_to_estimate",
                    "severity": "warning",
                    "title": "Current window is using estimated credits",
                    "detail": (
                        "The comparison window had ledger entries, but the current "
                        "window is falling back to meter estimates."
                    ),
                    "metric": "ai_credits",
                    "value": current_value,
                    "href": "/admin/accounts",
                }
            )
        return items[:4]

    def _build_admin_account_credit_breakdown(
        self,
        *,
        meter_events: Sequence[object],
        totals: dict[str, float],
        indexed_document_count: int,
        indexed_chunk_count: int,
    ) -> list[dict[str, object]]:
        service = cast(Any, self)
        web_search_calls = 0.0
        image_calls = 0.0
        other_provider_calls = 0.0
        maintenance_totals: dict[str, float] = defaultdict(float)
        for event in meter_events:
            if is_site_knowledge_index_meter_event(event):
                meter_key = str(getattr(event, "meter_key", "") or "")
                maintenance_totals[meter_key] += service._coerce_float(
                    getattr(event, "quantity", 0.0)
                )
                continue
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
        run_count = max(
            0.0,
            service._coerce_float(totals.get("runs")) - maintenance_totals["runs"],
        )
        token_count = max(
            0.0,
            service._coerce_float(totals.get("tokens_total"))
            - maintenance_totals["tokens_total"],
        )
        token_credits = rounded_token_credits(token_count)
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
                "quantity": round(token_count, 6),
                "unit": "token",
                "rate": 1.0,
                "rate_unit": "1000_tokens_rounded_up",
                "credits": token_credits,
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
                "label": "Vector indexed articles (meter only)",
                "quantity": indexed_document_count,
                "unit": "document",
                "rate": 0.0,
                "credits": 0.0,
            },
            {
                "key": "vector_chunks",
                "label": "Vector indexed chunks (meter only)",
                "quantity": indexed_chunk_count,
                "unit": "chunk",
                "rate": 0.0,
                "credits": 0.0,
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
                    else "Apply Free, Plus, Pro, or Agency coverage before granting account access."
                ),
            },
        ]
        blocking_codes = [str(item["code"]) for item in checks if not bool(item["ok"])]
        status = "ready" if not blocking_codes else "action_required"
        if not account_active or site_count == 0:
            status = "blocked"
        next_action = "review_account_membership"
        next_action_label = "Review account membership"
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

    def list_admin_platform_admin_grants(
        self,
        *,
        status: str | None = None,
        role: str | None = None,
        provider: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            identities = repository.list_platform_admin_grants(
                status=status,
                role=role,
                provider=provider,
                limit=limit,
            )
            items = [
                self._serialize_platform_admin_grant(
                    identity,
                    principal=repository.get_principal_identity_by_ref(
                        principal_id=str(identity.principal_id)
                    ),
                )
                for identity in identities
            ]
        return {
            "filters": {
                "status": status or "",
                "role": role or "",
                "provider": provider or "",
                "limit": limit,
            },
            "items": items,
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
