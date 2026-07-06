from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import AccountEntitlementSnapshot, AccountSubscription
from app.domain.commercial.service import CommercialService
from tests.conftest import seed_site_auth


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'commercial-runtime-defaults.sqlite3'}"


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
