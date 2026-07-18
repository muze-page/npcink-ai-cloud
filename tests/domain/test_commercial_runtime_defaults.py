from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.adapters.repositories.runtime_repository import RuntimeRepository
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    AccountEntitlementSnapshot,
    AccountSubscription,
    CreditLedgerEntry,
    PaidCreditGrant,
)
from app.domain.commercial.service import CommercialService
from app.domain.runtime.errors import RuntimeQuotaExceededError
from tests.conftest import seed_site_auth


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'commercial-runtime-defaults.sqlite3'}"


def _record_existing_credit_usage(
    database_url: str,
    *,
    site_id: str,
    credits: float,
) -> None:
    with get_session(database_url) as session:
        repository = CommercialRepository(session)
        subscription = session.scalar(select(AccountSubscription))
        assert subscription is not None
        repository.record_credit_ledger_entry(
            account_id=subscription.account_id,
            site_id=site_id,
            subscription_id=subscription.subscription_id,
            plan_version_id=subscription.plan_version_id,
            run_id=f"run_{site_id}_existing_usage",
            provider_call_id=None,
            source_type="runs",
            source_id=f"{site_id}_existing_usage",
            credit_delta=-credits,
            quantity=credits,
            unit="credit",
            rate=1,
            rate_unit="credit",
            rate_version="ai-credit-ledger-v2",
            idempotency_key=f"{site_id}-existing-usage",
        )
        session.commit()


def test_authorize_runtime_request_uses_free_ai_credit_package_defaults(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    service = CommercialService(database_url)
    with get_session(database_url) as session:
        decision = service.authorize_runtime_request(
            session=session,
            site_id="site_alpha",
            ability_family="workflow",
            channel="openapi",
            execution_kind="text",
            execution_tier="cloud",
            data_classification="internal",
            trace_id="trace-commercial-defaults-001",
            idempotency_key="idem-commercial-defaults-001",
            request_kind="resolve",
        )
        session.commit()

    assert decision["budgets"] == {
        "max_ai_credits_per_period": 300.0,
        "max_runs_per_period": 0.0,
        "max_tokens_per_period": 0.0,
        "max_cost_per_period": 0.0,
    }
    assert decision["concurrency"] == {
        "max_active_runs": 1,
    }

    dispose_engine(database_url)


def test_authorize_runtime_request_allows_cloud_managed_knowledge_family(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    service = CommercialService(database_url)
    with get_session(database_url) as session:
        decision = service.authorize_runtime_request(
            session=session,
            site_id="site_alpha",
            ability_family="knowledge",
            channel="openapi",
            execution_kind="embedding",
            execution_tier="cloud",
            data_classification="public_site_content",
            trace_id="trace-commercial-knowledge-001",
            idempotency_key="idem-commercial-knowledge-001",
            request_kind="resolve",
        )
        session.commit()

    assert decision["decision_code"] == "commercial.allowed"
    assert decision["entitlements"]["ability_families"] == ["*"]

    dispose_engine(database_url)


def test_authorize_runtime_request_adds_active_paid_grants_to_package_headroom(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_paid_credits",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )
    now = datetime(2026, 7, 11, tzinfo=UTC)
    with get_session(database_url) as session:
        repository = CommercialRepository(session)
        subscription = session.scalar(select(AccountSubscription))
        assert subscription is not None
        period_start = subscription.current_period_start_at or now
        if period_start.tzinfo is None:
            period_start = period_start.replace(tzinfo=UTC)
        now = service_now = period_start + timedelta(hours=1)
        repository.create_payment_order(
            order_id="pay_runtime_paid_grant",
            account_id=subscription.account_id,
            site_id="site_paid_credits",
            subscription_id=subscription.subscription_id,
            plan_id=subscription.plan_id,
            plan_version_id=subscription.plan_version_id,
            provider="manual",
            external_order_no="pay_runtime_paid_grant",
            status="paid",
            amount=99.0,
            currency="CNY",
            subject="Paid-credit runtime fixture",
            checkout_url=None,
            refund_window_end_at=None,
            idempotency_key="pay-runtime-paid-grant",
            metadata_json={"purchase_kind": "credit_pack"},
        )
        repository.upsert_paid_credit_grant(
            account_id=subscription.account_id,
            payment_order_id="pay_runtime_paid_grant",
            original_credits=10_000,
            expires_at=now + timedelta(days=365),
        )
        repository.record_credit_ledger_entry(
            account_id=subscription.account_id,
            site_id="site_paid_credits",
            subscription_id=subscription.subscription_id,
            plan_version_id=subscription.plan_version_id,
            run_id="run_base_allowance",
            provider_call_id=None,
            source_type="runs",
            source_id="base_allowance_consumed",
            credit_delta=-300,
            quantity=300,
            unit="credit",
            rate=1,
            rate_unit="credit",
            rate_version="ai-credit-ledger-v2",
            idempotency_key="base-allowance-consumed",
            created_at=now,
        )
        session.commit()

    service = CommercialService(database_url, now_factory=lambda: service_now)
    with get_session(database_url) as session:
        decision = service.authorize_runtime_request(
            session=session,
            site_id="site_paid_credits",
            ability_family="workflow",
            channel="openapi",
            execution_kind="text",
            execution_tier="cloud",
            data_classification="internal",
            trace_id="trace-commercial-paid-credit-001",
            idempotency_key="idem-commercial-paid-credit-001",
            request_kind="execute",
            estimated_ai_credits=100,
        )
        session.commit()

    assert decision["ai_credit_budget"] == {
        "used": 300.0,
        "estimated_request": 100.0,
        "limit": 10300.0,
        "package_limit": 300.0,
        "package_remaining": 0.0,
        "paid_remaining": 10000.0,
        "paid_grant_count": 1,
        "remaining_before_request": 10000.0,
    }

    with get_session(database_url) as session:
        subscription = session.scalar(select(AccountSubscription))
        assert subscription is not None
        run = RuntimeRepository(session).create_run(
            run_id="run_paid_credit_allocation",
            site_id="site_paid_credits",
            account_id=subscription.account_id,
            subscription_id=subscription.subscription_id,
            plan_version_id=subscription.plan_version_id,
            ability_name="test/paid-credit",
            ability_family="workflow",
            skill_id="",
            workflow_id="",
            contract_version="v1",
            channel="openapi",
            execution_kind="text",
            execution_tier="cloud",
            execution_pattern="inline",
            data_classification="internal",
            profile_id="text.balanced",
            canonical_run_id=None,
            status="running",
            idempotency_key="run-paid-credit-allocation",
            request_fingerprint="fingerprint-paid-credit-allocation",
            trace_id="trace-paid-credit-allocation",
            input_json={},
            execution_input_ciphertext=None,
            policy_json={},
        )
        service.record_run_acceptance(session=session, run=run)
        grant = session.scalar(select(PaidCreditGrant))
        paid_consume = session.scalar(
            select(CreditLedgerEntry).where(
                CreditLedgerEntry.run_id == "run_paid_credit_allocation"
            )
        )
        session.commit()
    assert grant is not None
    assert grant.remaining_credits == 9999.0
    assert paid_consume is not None
    assert paid_consume.metadata_json["paid_credit_consumed"] == 1.0
    dispose_engine(database_url)


def test_authorize_runtime_request_keeps_zero_credit_limit_unlimited_after_usage(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_unlimited_credits",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
        budgets={"max_ai_credits_per_period": 0},
    )
    _record_existing_credit_usage(
        database_url,
        site_id="site_unlimited_credits",
        credits=5,
    )

    service = CommercialService(database_url)
    with get_session(database_url) as session:
        decision = service.authorize_runtime_request(
            session=session,
            site_id="site_unlimited_credits",
            ability_family="text",
            channel="openapi",
            execution_kind="text",
            execution_tier="cloud",
            data_classification="internal",
            trace_id="trace-unlimited-credits-001",
            idempotency_key="idem-unlimited-credits-001",
            request_kind="execute",
            estimated_ai_credits=1,
        )
        session.commit()

    assert decision["decision_code"] == "commercial.allowed"
    assert decision["ai_credit_budget"] == {
        "used": 5.0,
        "estimated_request": 1.0,
        "limit": 0.0,
        "package_limit": 0.0,
        "package_remaining": 0.0,
        "paid_remaining": 0.0,
        "paid_grant_count": 0,
        "remaining_before_request": 0.0,
    }
    dispose_engine(database_url)


def test_zero_credit_limit_does_not_consume_paid_grants_after_acceptance(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_unlimited_with_paid_grant",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
        budgets={"max_ai_credits_per_period": 0},
    )
    with get_session(database_url) as session:
        repository = CommercialRepository(session)
        subscription = session.scalar(select(AccountSubscription))
        assert subscription is not None
        period_start = subscription.current_period_start_at or datetime.now(UTC)
        if period_start.tzinfo is None:
            period_start = period_start.replace(tzinfo=UTC)
        now = period_start + timedelta(hours=1)
        repository.create_payment_order(
            order_id="pay_unlimited_runtime_grant",
            account_id=subscription.account_id,
            site_id="site_unlimited_with_paid_grant",
            subscription_id=subscription.subscription_id,
            plan_id=subscription.plan_id,
            plan_version_id=subscription.plan_version_id,
            provider="manual",
            external_order_no="pay_unlimited_runtime_grant",
            status="paid",
            amount=10.0,
            currency="CNY",
            subject="Unlimited runtime paid-credit fixture",
            checkout_url=None,
            refund_window_end_at=None,
            idempotency_key="pay-unlimited-runtime-grant",
            metadata_json={"purchase_kind": "credit_pack"},
        )
        repository.upsert_paid_credit_grant(
            account_id=subscription.account_id,
            payment_order_id="pay_unlimited_runtime_grant",
            original_credits=10,
            expires_at=now + timedelta(days=365),
        )
        run = RuntimeRepository(session).create_run(
            run_id="run_unlimited_paid_credit_allocation",
            site_id="site_unlimited_with_paid_grant",
            account_id=subscription.account_id,
            subscription_id=subscription.subscription_id,
            plan_version_id=subscription.plan_version_id,
            ability_name="test/unlimited-paid-credit",
            ability_family="workflow",
            skill_id="",
            workflow_id="",
            contract_version="v1",
            channel="openapi",
            execution_kind="text",
            execution_tier="cloud",
            execution_pattern="inline",
            data_classification="internal",
            profile_id="text.balanced",
            canonical_run_id=None,
            status="running",
            idempotency_key="run-unlimited-paid-credit-allocation",
            request_fingerprint="fingerprint-unlimited-paid-credit-allocation",
            trace_id="trace-unlimited-paid-credit-allocation",
            input_json={},
            execution_input_ciphertext=None,
            policy_json={},
        )
        service = CommercialService(database_url, now_factory=lambda: now)
        service.record_run_acceptance(session=session, run=run)
        grant = session.scalar(select(PaidCreditGrant))
        consume = session.scalar(
            select(CreditLedgerEntry).where(
                CreditLedgerEntry.run_id == "run_unlimited_paid_credit_allocation"
            )
        )
        session.commit()

    assert grant is not None
    assert grant.remaining_credits == 10.0
    assert consume is not None
    assert consume.metadata_json["paid_credit_consumed"] == 0.0
    assert consume.metadata_json["package_credit_consumed"] == 1.0
    dispose_engine(database_url)


def test_authorize_runtime_request_still_rejects_exhausted_finite_credit_limit(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_finite_credits",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
        budgets={"max_ai_credits_per_period": 5},
    )
    _record_existing_credit_usage(
        database_url,
        site_id="site_finite_credits",
        credits=5,
    )

    service = CommercialService(database_url)
    with get_session(database_url) as session:
        with pytest.raises(RuntimeQuotaExceededError) as exc_info:
            service.authorize_runtime_request(
                session=session,
                site_id="site_finite_credits",
                ability_family="text",
                channel="openapi",
                execution_kind="text",
                execution_tier="cloud",
                data_classification="internal",
                trace_id="trace-finite-credits-001",
                idempotency_key="idem-finite-credits-001",
                request_kind="execute",
                estimated_ai_credits=1,
            )

    assert exc_info.value.error_code == "commercial.quota_exceeded"
    dispose_engine(database_url)


def test_site_capacity_uses_current_plan_version_site_limit(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    service = CommercialService(database_url)
    service.upsert_account(
        account_id="acct_capacity",
        name="Capacity Account",
        bind_default_free=True,
    )
    service.provision_site(
        site_id="site_first",
        account_id="acct_capacity",
        name="First Site",
    )

    with get_session(database_url) as session:
        snapshot = session.scalar(select(AccountEntitlementSnapshot))
        assert snapshot is not None
        assert snapshot.plan_version_id == "free_v1"
        assert snapshot.site_limit == 1

    service.publish_plan_version(
        plan_id="free",
        plan_version_id="free_v1",
        version_label="v1",
        metadata_json={
            "tier_id": "free",
            "package_alias": "Free",
            "plan_kind": "default_free",
            "site_limit": 3,
            "monthly_included_points": 300,
            "max_batch_items": 5,
        },
    )

    second_site = service.provision_site(
        site_id="site_second",
        account_id="acct_capacity",
        name="Second Site",
    )

    assert second_site["site_id"] == "site_second"

    dispose_engine(database_url)


def test_authorize_runtime_request_lazily_renews_expired_active_period(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )
    expired_start = datetime(2026, 4, 1, tzinfo=UTC)
    expired_end = datetime(2026, 5, 1, tzinfo=UTC)
    now = datetime(2026, 5, 2, tzinfo=UTC)

    with get_session(database_url) as session:
        subscription = session.scalar(select(AccountSubscription))
        assert subscription is not None
        subscription.current_period_start_at = expired_start
        subscription.current_period_end_at = expired_end
        subscription.metadata_json = {
            **(subscription.metadata_json or {}),
            "current_period_topup_totals": {
                "ai_credits": 10_000.0,
                "runs": 0.0,
                "tokens": 0.0,
                "cost": 0.0,
            },
            "operator_managed_topups": [
                {
                    "target_period_start_at": expired_start.isoformat(),
                    "target_period_end_at": expired_end.isoformat(),
                    "increments": {"ai_credits": 10_000.0},
                }
            ],
        }
        session.commit()

    service = CommercialService(database_url, now_factory=lambda: now)
    with get_session(database_url) as session:
        decision = service.authorize_runtime_request(
            session=session,
            site_id="site_alpha",
            ability_family="workflow",
            channel="openapi",
            execution_kind="text",
            execution_tier="cloud",
            data_classification="internal",
            trace_id="trace-commercial-renew-001",
            idempotency_key="idem-commercial-renew-001",
            request_kind="execute",
            estimated_ai_credits=1,
        )
        renewed_subscription = session.scalar(select(AccountSubscription))
        session.commit()

    assert decision["period_renewed"] is True
    assert decision["period_start_at"] == expired_end
    assert decision["period_end_at"] == expired_end + timedelta(days=30)
    assert decision["budgets"]["max_ai_credits_per_period"] == 300.0
    assert renewed_subscription is not None
    assert (
        service._normalize_datetime(renewed_subscription.current_period_start_at)
        == expired_end
    )
    assert (
        service._normalize_datetime(renewed_subscription.current_period_end_at)
        == expired_end + timedelta(days=30)
    )
    assert renewed_subscription.metadata_json["current_period_topup_totals"]["ai_credits"] == 0.0

    dispose_engine(database_url)
