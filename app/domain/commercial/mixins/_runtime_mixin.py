"""Commercial service: runtime authorization and policy mixin."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy.orm import Session

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.db import get_session
from app.core.models import (
    ACCOUNT_STATUS_ACTIVE,
    ENTITLEMENT_SNAPSHOT_STATUS_ACTIVE,
    PLAN_STATUS_ACTIVE,
    PLAN_VERSION_STATUS_PUBLISHED,
    SITE_API_KEY_STATUS_ACTIVE,
    SITE_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_TRIALING,
    AccountEntitlementSnapshot,
    AccountSubscription,
    ProviderCallRecord,
    RunRecord,
)
from app.core.secrets import encrypt_site_api_signing_secret
from app.core.security import build_secret_hash
from app.domain.commercial.credits import (
    AI_CREDIT_RATE_VERSION,
    usage_meter_credit_component,
)
from app.domain.commercial.mixins._audit_mixin import CommercialServiceAuditMixin
from app.domain.commercial.mixins._billing_mixin import (
    DEFAULT_FREE_PLAN_ID,
    DEFAULT_FREE_PLAN_KIND,
    DEFAULT_FREE_PLAN_VERSION_ID,
    DEFAULT_RUNTIME_BUDGETS,
    DEFAULT_RUNTIME_COMMERCIAL_POLICY,
    DEFAULT_RUNTIME_CONCURRENCY,
    DEFAULT_RUNTIME_ENTITLEMENTS,
)
from app.domain.runtime.errors import (
    RuntimeConcurrencyExceededError,
    RuntimeEntitlementDeniedError,
    RuntimeErrorBase,
    RuntimeQuotaExceededError,
    RuntimeSiteInactiveError,
    RuntimeSiteNotProvisionedError,
    RuntimeSubscriptionInactiveError,
)


class CommercialServiceRuntimeMixin(CommercialServiceAuditMixin):
    def provision_runtime_baseline(
        self,
        *,
        site_id: str,
        key_id: str,
        secret: str,
        site_name: str,
        scopes: list[str],
        account_id: str | None = None,
        plan_id: str = DEFAULT_FREE_PLAN_ID,
        plan_version_id: str = DEFAULT_FREE_PLAN_VERSION_ID,
        subscription_id: str | None = None,
    ) -> dict[str, object]:
        now = self.now_factory()
        resolved_account_id = account_id or f"acct_{site_id}"
        resolved_subscription_id = subscription_id or f"sub_{site_id}"

        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            service = cast(Any, self)
            repository.upsert_account(
                account_id=resolved_account_id,
                name=resolved_account_id,
                status=ACCOUNT_STATUS_ACTIVE,
                metadata_json={"source": "seed_runtime"},
            )
            if plan_id == DEFAULT_FREE_PLAN_ID and plan_version_id == DEFAULT_FREE_PLAN_VERSION_ID:
                service._ensure_plan_free_version_in_session(repository=repository)
            else:
                repository.upsert_plan(
                    plan_id=plan_id,
                    name=plan_id,
                    status=PLAN_STATUS_ACTIVE,
                    description="Runtime baseline commercial plan",
                    metadata_json={"source": "seed_runtime"},
                )
                repository.upsert_plan_version(
                    plan_version_id=plan_version_id,
                    plan_id=plan_id,
                    version_label="v1",
                    status=PLAN_VERSION_STATUS_PUBLISHED,
                    currency="USD",
                    entitlements_json=cast(dict[str, object], DEFAULT_RUNTIME_ENTITLEMENTS),
                    budgets_json=DEFAULT_RUNTIME_BUDGETS,
                    concurrency_json=DEFAULT_RUNTIME_CONCURRENCY,
                    policy_json=DEFAULT_RUNTIME_COMMERCIAL_POLICY,
                    metadata_json={"source": "seed_runtime"},
                )
            site = repository.upsert_site(
                site_id=site_id,
                account_id=resolved_account_id,
                name=site_name or site_id,
                status=SITE_STATUS_ACTIVE,
                metadata_json=(
                    {
                        "source": "seed_runtime",
                        "tier_id": "free",
                        "package_alias": "Free",
                        "plan_kind": DEFAULT_FREE_PLAN_KIND,
                    }
                    if plan_id == DEFAULT_FREE_PLAN_ID
                    else {"source": "seed_runtime"}
                ),
                provisioned_at=now,
            )
            site.activated_at = now

            repository.upsert_site_key(
                key_id=key_id,
                site_id=site_id,
                secret_hash=build_secret_hash(secret),
                signing_secret_ciphertext=encrypt_site_api_signing_secret(
                    secret,
                    settings=self.settings,
                ),
                label="seed-runtime",
                scopes_json=scopes,
                metadata_json={"source": "seed_runtime"},
                status=SITE_API_KEY_STATUS_ACTIVE,
                rotated_from_key_id=None,
                replaced_by_key_id=None,
                expires_at=None,
                revoked_at=None,
            )
            service._bind_subscription_in_session(
                repository=repository,
                subscription_id=resolved_subscription_id,
                account_id=resolved_account_id,
                plan_id=plan_id,
                plan_version_id=plan_version_id,
                status=SUBSCRIPTION_STATUS_ACTIVE,
                current_period_start_at=now,
                current_period_end_at=now + timedelta(days=30),
                metadata_json={"source": "seed_runtime"},
            )
            session.commit()

        return {
            "site_id": site_id,
            "account_id": resolved_account_id,
            "plan_id": plan_id,
            "plan_version_id": plan_version_id,
            "subscription_id": resolved_subscription_id,
            "key_id": key_id,
            "scopes": scopes,
        }

    def authorize_runtime_request(
        self,
        *,
        session: Session,
        site_id: str,
        ability_family: str,
        channel: str,
        execution_kind: str,
        execution_tier: str,
        data_classification: str,
        trace_id: str = "",
        idempotency_key: str | None = None,
        request_kind: str = "execute",
        run_id: str | None = None,
    ) -> dict[str, object]:
        now = self.now_factory()
        repository = CommercialRepository(session)
        site = repository.get_site(site_id)
        if site is None:
            error: RuntimeErrorBase = RuntimeSiteNotProvisionedError(site_id)
            self._record_commercial_decision_in_session(
                repository=repository,
                account_id=None,
                site_id=site_id,
                subscription_id=None,
                plan_version_id=None,
                run_id=run_id,
                request_kind=request_kind,
                decision="deny",
                decision_code=error.error_code,
                ability_family=ability_family,
                channel=channel,
                execution_kind=execution_kind,
                execution_tier=execution_tier,
                data_classification=data_classification,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                payload_json={"reason": "site_missing"},
            )
            session.commit()
            raise error
        if site.status != SITE_STATUS_ACTIVE:
            error = RuntimeSiteInactiveError(site_id, site.status)
            self._record_commercial_decision_in_session(
                repository=repository,
                account_id=site.account_id,
                site_id=site_id,
                subscription_id=None,
                plan_version_id=None,
                run_id=run_id,
                request_kind=request_kind,
                decision="deny",
                decision_code=error.error_code,
                ability_family=ability_family,
                channel=channel,
                execution_kind=execution_kind,
                execution_tier=execution_tier,
                data_classification=data_classification,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                payload_json={"site_status": site.status},
            )
            session.commit()
            raise error

        subscription = repository.get_runtime_subscription(site.account_id or "")
        if subscription is None:
            error = RuntimeSubscriptionInactiveError(site_id, "missing")
            self._record_commercial_decision_in_session(
                repository=repository,
                account_id=site.account_id,
                site_id=site_id,
                subscription_id=None,
                plan_version_id=None,
                run_id=run_id,
                request_kind=request_kind,
                decision="deny",
                decision_code=error.error_code,
                ability_family=ability_family,
                channel=channel,
                execution_kind=execution_kind,
                execution_tier=execution_tier,
                data_classification=data_classification,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                payload_json={"subscription_status": "missing"},
            )
            session.commit()
            raise error

        service = cast(Any, self)
        period_start_at, period_end_at = service._resolve_period(subscription, now)
        policy_actions: list[dict[str, object]] = []
        snapshot = repository.get_active_entitlement_snapshot(
            site.account_id or "",
            subscription_id=subscription.subscription_id,
        )
        plan_version = (
            repository.get_plan_version(subscription.plan_version_id)
            if subscription.plan_version_id
            else None
        )
        if snapshot is None or snapshot.status != ENTITLEMENT_SNAPSHOT_STATUS_ACTIVE:
            error = RuntimeEntitlementDeniedError(site_id, ability_family, "snapshot_missing")
            self._record_commercial_decision_in_session(
                repository=repository,
                account_id=subscription.account_id,
                site_id=site_id,
                subscription_id=subscription.subscription_id,
                plan_version_id=subscription.plan_version_id,
                run_id=run_id,
                request_kind=request_kind,
                decision="deny",
                decision_code=error.error_code,
                ability_family=ability_family,
                channel=channel,
                execution_kind=execution_kind,
                execution_tier=execution_tier,
                data_classification=data_classification,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                payload_json={"reason": "snapshot_missing"},
            )
            session.commit()
            raise error

        policy = service._normalize_commercial_policy(snapshot.policy_json)
        batch_limits = service._resolve_runtime_batch_limits(
            snapshot=snapshot,
            plan_version=plan_version,
        )

        if subscription.status not in {
            SUBSCRIPTION_STATUS_TRIALING,
            SUBSCRIPTION_STATUS_ACTIVE,
        }:
            subscription_action = self._resolve_subscription_policy_action(
                subscription=subscription,
                policy=policy,
                period_end_at=period_end_at,
                now=now,
                reason="status_not_runtime_active",
            )
            if subscription_action is None:
                error = RuntimeSubscriptionInactiveError(site_id, subscription.status)
                self._record_commercial_decision_in_session(
                    repository=repository,
                    account_id=site.account_id,
                    site_id=site_id,
                    subscription_id=subscription.subscription_id,
                    plan_version_id=subscription.plan_version_id,
                    run_id=run_id,
                    request_kind=request_kind,
                    decision="deny",
                    decision_code=error.error_code,
                    ability_family=ability_family,
                    channel=channel,
                    execution_kind=execution_kind,
                    execution_tier=execution_tier,
                    data_classification=data_classification,
                    trace_id=trace_id,
                    idempotency_key=idempotency_key,
                    payload_json={"subscription_status": subscription.status},
                )
                session.commit()
                raise error
            policy_actions.append(subscription_action)

        if period_end_at < now:
            subscription_action = self._resolve_subscription_policy_action(
                subscription=subscription,
                policy=policy,
                period_end_at=period_end_at,
                now=now,
                reason="period_expired",
            )
            if subscription_action is None:
                error = RuntimeSubscriptionInactiveError(site_id, subscription.status)
                self._record_commercial_decision_in_session(
                    repository=repository,
                    account_id=subscription.account_id,
                    site_id=site_id,
                    subscription_id=subscription.subscription_id,
                    plan_version_id=subscription.plan_version_id,
                    run_id=run_id,
                    request_kind=request_kind,
                    decision="deny",
                    decision_code=error.error_code,
                    ability_family=ability_family,
                    channel=channel,
                    execution_kind=execution_kind,
                    execution_tier=execution_tier,
                    data_classification=data_classification,
                    trace_id=trace_id,
                    idempotency_key=idempotency_key,
                    payload_json={
                        "subscription_status": subscription.status,
                        "period_end_at": self._serialize_datetime(period_end_at),
                    },
                )
                session.commit()
                raise error
            if not any(
                action.get("kind") == subscription_action.get("kind") for action in policy_actions
            ):
                policy_actions.append(subscription_action)

        if not self._entitlements_allow(
            snapshot,
            ability_family=ability_family,
            channel=channel,
            execution_kind=execution_kind,
            execution_tier=execution_tier,
            data_classification=data_classification,
        ):
            error = RuntimeEntitlementDeniedError(site_id, ability_family, "entitlement_miss")
            self._record_commercial_decision_in_session(
                repository=repository,
                account_id=subscription.account_id,
                site_id=site_id,
                subscription_id=subscription.subscription_id,
                plan_version_id=subscription.plan_version_id,
                run_id=run_id,
                request_kind=request_kind,
                decision="deny",
                decision_code=error.error_code,
                ability_family=ability_family,
                channel=channel,
                execution_kind=execution_kind,
                execution_tier=execution_tier,
                data_classification=data_classification,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                payload_json={
                    "reason": "entitlement_miss",
                    "entitlements": service._normalize_entitlements(snapshot.entitlements_json),
                },
            )
            session.commit()
            raise error

        active_runs = repository.count_active_runs(site_id)
        concurrency = service._normalize_concurrency(snapshot.concurrency_json)
        max_active_runs = self._coerce_int(concurrency.get("max_active_runs"))
        if request_kind == "execute" and max_active_runs > 0 and active_runs >= max_active_runs:
            error = RuntimeConcurrencyExceededError(site_id, max_active_runs)
            self._record_commercial_decision_in_session(
                repository=repository,
                account_id=subscription.account_id,
                site_id=site_id,
                subscription_id=subscription.subscription_id,
                plan_version_id=subscription.plan_version_id,
                run_id=run_id,
                request_kind=request_kind,
                decision="deny",
                decision_code=error.error_code,
                ability_family=ability_family,
                channel=channel,
                execution_kind=execution_kind,
                execution_tier=execution_tier,
                data_classification=data_classification,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                payload_json={
                    "active_runs": active_runs,
                    "max_active_runs": max_active_runs,
                },
            )
            session.commit()
            raise error

        totals = service._aggregate_meter_events(
            repository.list_usage_meter_events(
                site_id,
                subscription_id=subscription.subscription_id,
                period_start_at=period_start_at,
                period_end_at=period_end_at,
                limit=None,
            )
        )
        budgets = service._normalize_budgets(snapshot.budgets_json)
        budget_checks = (
            ("runs", totals.get("runs", 0.0), budgets.get("max_runs_per_period")),
            ("tokens", totals.get("tokens_total", 0.0), budgets.get("max_tokens_per_period")),
            ("cost", totals.get("cost", 0.0), budgets.get("max_cost_per_period")),
        )
        for meter_key, current_total, budget_value in budget_checks:
            limit = self._coerce_float(budget_value)
            if limit <= 0 or current_total < limit:
                continue
            budget_action = self._resolve_budget_policy_action(
                repository=repository,
                subscription=subscription,
                policy=policy,
                meter_key=meter_key,
                current_total=current_total,
                limit=limit,
                period_start_at=period_start_at,
                request_kind=request_kind,
            )
            if budget_action is None:
                error = RuntimeQuotaExceededError(meter_key, limit)
                self._record_commercial_decision_in_session(
                    repository=repository,
                    account_id=subscription.account_id,
                    site_id=site_id,
                    subscription_id=subscription.subscription_id,
                    plan_version_id=subscription.plan_version_id,
                    run_id=run_id,
                    request_kind=request_kind,
                    decision="deny",
                    decision_code=error.error_code,
                    ability_family=ability_family,
                    channel=channel,
                    execution_kind=execution_kind,
                    execution_tier=execution_tier,
                    data_classification=data_classification,
                    trace_id=trace_id,
                    idempotency_key=idempotency_key,
                    payload_json={
                        "meter_key": meter_key,
                        "current_total": round(float(current_total), 6),
                        "limit": round(float(limit), 6),
                    },
                )
                session.commit()
                raise error
            policy_actions.append(budget_action)
            break

        effective_runtime_policy_overrides: dict[str, object] = {}
        for action in policy_actions:
            effective_runtime_policy_overrides = self._merge_runtime_policy_overrides(
                effective_runtime_policy_overrides,
                action.get("runtime_policy_overrides"),
            )

        decision_code = self._resolve_allow_decision_code(policy_actions)
        decision = {
            "account_id": subscription.account_id,
            "site_id": site_id,
            "subscription_id": subscription.subscription_id,
            "plan_version_id": subscription.plan_version_id,
            "period_start_at": period_start_at,
            "period_end_at": period_end_at,
            "entitlements": service._normalize_entitlements(snapshot.entitlements_json),
            "budgets": budgets,
            "concurrency": concurrency,
            "batch_limits": batch_limits,
            "policy": policy,
            "policy_actions": policy_actions,
            "runtime_policy_overrides": effective_runtime_policy_overrides,
            "decision_code": decision_code,
        }
        self._record_commercial_decision_in_session(
            repository=repository,
            account_id=subscription.account_id,
            site_id=site_id,
            subscription_id=subscription.subscription_id,
            plan_version_id=subscription.plan_version_id,
            run_id=run_id,
            request_kind=request_kind,
            decision="allow",
            decision_code=decision_code,
            ability_family=ability_family,
            channel=channel,
            execution_kind=execution_kind,
            execution_tier=execution_tier,
            data_classification=data_classification,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            payload_json={
                "period_start_at": self._serialize_datetime(period_start_at),
                "period_end_at": self._serialize_datetime(period_end_at),
                "budgets": budgets,
                "concurrency": concurrency,
                "batch_limits": batch_limits,
                "active_runs": active_runs,
                "policy": policy,
                "policy_actions": policy_actions,
                "runtime_policy_overrides": effective_runtime_policy_overrides,
            },
        )
        return decision

    def record_run_acceptance(
        self,
        *,
        session: Session,
        run: RunRecord,
    ) -> None:
        repository = CommercialRepository(session)
        event = repository.record_usage_meter_event(
            account_id=run.account_id,
            site_id=run.site_id,
            subscription_id=run.subscription_id,
            plan_version_id=run.plan_version_id,
            run_id=run.run_id,
            provider_call_id=None,
            event_kind="run",
            meter_key="runs",
            quantity=1.0,
            ability_family=run.ability_family,
            channel=run.channel,
            execution_kind=run.execution_kind,
            execution_tier=run.execution_tier,
            data_classification=run.data_classification,
            currency="USD",
            dedupe_key=f"run:{run.run_id}:runs",
            payload_json={"status": run.status},
        )
        self._record_credit_for_usage_meter_event(repository=repository, event=event)

    def record_provider_call_usage(
        self,
        *,
        session: Session,
        run: RunRecord,
        provider_call: ProviderCallRecord,
    ) -> None:
        repository = CommercialRepository(session)
        base_payload = {
            "provider_id": provider_call.provider_id,
            "model_id": provider_call.model_id,
            "instance_id": provider_call.instance_id,
            "retry_count": provider_call.retry_count,
            "error_code": provider_call.error_code,
        }
        event = repository.record_usage_meter_event(
            account_id=run.account_id,
            site_id=run.site_id,
            subscription_id=run.subscription_id,
            plan_version_id=run.plan_version_id,
            run_id=run.run_id,
            provider_call_id=provider_call.id,
            event_kind="provider_call",
            meter_key="provider_calls",
            quantity=1.0,
            ability_family=run.ability_family,
            channel=run.channel,
            execution_kind=run.execution_kind,
            execution_tier=run.execution_tier,
            data_classification=run.data_classification,
            currency="USD",
            dedupe_key=f"provider_call:{provider_call.id}:provider_calls",
            payload_json=base_payload,
        )
        self._record_credit_for_usage_meter_event(repository=repository, event=event)
        metric_rows = (
            ("tokens_in", float(provider_call.tokens_in)),
            ("tokens_out", float(provider_call.tokens_out)),
            ("tokens_total", float(provider_call.tokens_in + provider_call.tokens_out)),
            ("cost", float(provider_call.cost)),
        )
        for meter_key, quantity in metric_rows:
            if quantity <= 0:
                continue
            event = repository.record_usage_meter_event(
                account_id=run.account_id,
                site_id=run.site_id,
                subscription_id=run.subscription_id,
                plan_version_id=run.plan_version_id,
                run_id=run.run_id,
                provider_call_id=provider_call.id,
                event_kind="provider_call",
                meter_key=meter_key,
                quantity=quantity,
                ability_family=run.ability_family,
                channel=run.channel,
                execution_kind=run.execution_kind,
                execution_tier=run.execution_tier,
                data_classification=run.data_classification,
                currency="USD",
                dedupe_key=f"provider_call:{provider_call.id}:{meter_key}",
                payload_json=base_payload,
            )
            self._record_credit_for_usage_meter_event(repository=repository, event=event)

    def _record_credit_for_usage_meter_event(
        self,
        *,
        repository: CommercialRepository,
        event: object,
    ) -> None:
        component = usage_meter_credit_component(event)
        if component is None:
            return
        event_id = getattr(event, "id", None)
        if event_id is None:
            return
        source_type = str(component.get("source_type") or "")
        credits = float(component.get("credits") or 0.0)
        repository.record_credit_ledger_entry(
            account_id=getattr(event, "account_id", None),
            site_id=getattr(event, "site_id", None),
            subscription_id=getattr(event, "subscription_id", None),
            plan_version_id=getattr(event, "plan_version_id", None),
            run_id=getattr(event, "run_id", None),
            provider_call_id=getattr(event, "provider_call_id", None),
            source_type=source_type,
            source_id=str(event_id),
            credit_delta=-credits,
            quantity=float(component.get("quantity") or 0.0),
            unit=str(component.get("unit") or "credit"),
            rate=float(component.get("rate") or 0.0),
            rate_unit=(
                str(component.get("rate_unit"))
                if component.get("rate_unit") is not None
                else None
            ),
            rate_version=AI_CREDIT_RATE_VERSION,
            idempotency_key=f"usage_meter_event:{event_id}",
            metadata_json={
                "usage_meter_event_id": event_id,
                "meter_key": str(getattr(event, "meter_key", "") or ""),
                "event_kind": str(getattr(event, "event_kind", "") or ""),
                "ability_family": str(getattr(event, "ability_family", "") or ""),
                "execution_kind": str(getattr(event, "execution_kind", "") or ""),
            },
            created_at=getattr(event, "created_at", None),
        )

    def _resolve_budget_policy_action(
        self,
        *,
        repository: CommercialRepository,
        subscription: AccountSubscription,
        policy: dict[str, object],
        meter_key: str,
        current_total: float,
        limit: float,
        period_start_at: datetime,
        request_kind: str,
    ) -> dict[str, object] | None:
        budgets_policy = policy.get("budgets")
        budgets_policy = budgets_policy if isinstance(budgets_policy, dict) else {}
        meter_policy = budgets_policy.get(meter_key)
        meter_policy = meter_policy if isinstance(meter_policy, dict) else {}
        grace_requests = max(0, self._coerce_int(meter_policy.get("grace_requests")))
        if grace_requests <= 0:
            return None

        used_grace_requests = repository.count_commercial_decision_events(
            subscription_id=subscription.subscription_id,
            decision="allow",
            decision_code=f"commercial.quota_grace.{meter_key}",
            request_kind="execute",
            since=period_start_at,
        )
        if request_kind == "execute" and used_grace_requests >= grace_requests:
            return None

        remaining_after_request = max(
            0,
            grace_requests - used_grace_requests - (1 if request_kind == "execute" else 0),
        )
        return {
            "kind": "budget_grace",
            "decision_code": (
                f"commercial.quota_grace.{meter_key}"
                if request_kind == "execute"
                else f"commercial.quota_soft_limit.{meter_key}"
            ),
            "meter_key": meter_key,
            "current_total": round(float(current_total), 6),
            "limit": round(float(limit), 6),
            "grace_requests": grace_requests,
            "used_grace_requests": used_grace_requests,
            "remaining_grace_requests": remaining_after_request,
            "runtime_policy_overrides": self._normalize_runtime_policy_overrides(
                meter_policy.get("downgrade_policy")
            ),
        }

    def _merge_runtime_policy_overrides(
        self,
        base: object,
        incoming: object,
    ) -> dict[str, object]:
        left = base if isinstance(base, dict) else {}
        right = incoming if isinstance(incoming, dict) else {}
        merged: dict[str, object] = dict(left)
        for key, value in right.items():
            if (
                key == "task_backend"
                and isinstance(merged.get(key), dict)
                and isinstance(value, dict)
            ):
                task_backend = self._sanitize_payload_dict(merged.get(key)) or {}
                task_backend.update(value)
                merged[key] = task_backend
                continue
            merged[key] = value
        return merged

    def _resolve_allow_decision_code(self, policy_actions: list[dict[str, object]]) -> str:
        for action in policy_actions:
            decision_code = str(action.get("decision_code") or "")
            if decision_code.startswith("commercial.quota_grace."):
                return decision_code
        for action in policy_actions:
            decision_code = str(action.get("decision_code") or "")
            if decision_code.startswith("commercial.quota_soft_limit."):
                return decision_code
        for action in policy_actions:
            decision_code = str(action.get("decision_code") or "")
            if decision_code:
                return decision_code
        return "commercial.allowed"

    def _entitlements_allow(
        self,
        snapshot: AccountEntitlementSnapshot,
        *,
        ability_family: str,
        channel: str,
        execution_kind: str,
        execution_tier: str,
        data_classification: str,
    ) -> bool:
        entitlements = cast(Any, self)._normalize_entitlements(snapshot.entitlements_json)
        checks = (
            (entitlements.get("ability_families"), ability_family),
            (entitlements.get("channels"), channel),
            (entitlements.get("execution_kinds"), execution_kind),
            (entitlements.get("execution_tiers"), execution_tier),
            (entitlements.get("data_classifications"), data_classification),
        )
        for allowed, actual in checks:
            allowed_values = [str(value).strip() for value in allowed or [] if str(value).strip()]
            if not allowed_values or "*" in allowed_values:
                continue
            if actual not in allowed_values:
                return False
        return True

    def _assert_budget(self, meter_key: str, current_total: float, budget_value: object) -> None:
        limit = self._coerce_float(budget_value)
        if limit <= 0:
            return
        if current_total < limit:
            return
        raise RuntimeQuotaExceededError(meter_key, limit)

    def _normalize_runtime_terminal_callback(
        self,
        callback: dict[str, object] | None,
    ) -> dict[str, object]:
        raw = callback or {}
        callback_url = str(raw.get("callback_url") or raw.get("url") or "").strip()
        key_id = str(raw.get("key_id") or "").strip()
        secret = str(raw.get("secret") or "").strip()
        callback_id = (
            str(raw.get("callback_id") or "runtime_terminal").strip() or "runtime_terminal"
        )
        return {
            "enabled": bool(raw.get("enabled")),
            "callback_url": callback_url,
            "key_id": key_id,
            "secret": secret,
            "callback_id": callback_id,
        }
