from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import AccountSubscription, PlanVersion, UsageMeterEvent
from app.core.services import CloudServices
from app.domain.commercial.service import CommercialService
from tests.conftest import (
    build_auth_headers,
    seed_site_auth,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'entitlements-api.sqlite3'}"


def _build_client(tmp_path: Path) -> tuple[str, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        audit_retention_days_default=45,
    )
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["entitlement:read"],
    )
    seed_site_auth(
        database_url,
        site_id="site_readonly",
        key_id="key_readonly",
        scopes=["runtime:read"],
    )
    CommercialService(database_url, settings=settings).upsert_account_subscription(
        subscription_id="sub_site_alpha_pro",
        account_id="acct_site_alpha",
        plan_id="pro",
        plan_version_id="pro_v1",
        status="active",
        current_period_start_at=datetime(2026, 5, 1, tzinfo=UTC),
        current_period_end_at=datetime(2026, 6, 1, tzinfo=UTC),
        metadata_json={"tier_id": "pro", "package_alias": "Pro"},
    )
    return database_url, TestClient(create_app(CloudServices(settings=settings)))


def test_current_entitlement_returns_site_scoped_public_contract(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    query = "object_type=site&object_id=site_alpha"
    response = client.get(
        f"/v1/entitlements/current?{query}",
        headers=build_auth_headers(
            "GET",
            "/v1/entitlements/current",
            site_id="site_alpha",
            query=query,
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["contract_version"] == "cloud-billing-entitlement-v1"
    assert data["paid_object"] == {
        "type": "site",
        "id": "site_alpha",
        "account_id": "acct_site_alpha",
    }
    assert data["package"] == "Pro"
    assert data["package_tier"] == "pro"
    assert data["status"] == "active"
    assert data["period"] == {
        "start_at": "2026-05-01T00:00:00Z",
        "end_at": "2026-06-01T00:00:00Z",
    }
    assert "task_packs" not in data["entitlement"]
    assert data["entitlement"]["usage_limits"] == {
        "period": "month",
        "max_runs": 0.0,
        "max_tokens": 0.0,
        "max_cost_usd": 0.0,
        "max_sites": 0,
    }
    assert data["entitlement"]["analytics_retention"] == {"days": 45}
    assert data["entitlement"]["hosted_runtime_quota"] == {
        "max_active_runs": 0,
        "max_batch_items": 25,
        "execution_tiers": ["cloud"],
    }
    assert data["entitlement"]["pro_cloud_runtime"] == {
        "contract_version": "pro-cloud-runtime-entitlement-v1",
        "feature_id": "nightly_site_inspection",
        "execution_pattern": "whole_run_offload",
        "meter_key": "nightly_site_inspection_runs",
        "limit_enforced": True,
        "max_nightly_inspection_runs_per_period": 30,
        "used_nightly_inspection_runs": 0,
        "remaining_nightly_inspection_runs": 30,
        "quota_exhausted": False,
        "max_batch_items": 25,
        "result_retention_days": 14,
        "payload_modes": ["metadata_only", "excerpt"],
        "cloud_role": "runtime_detail",
        "local_truth": {
            "schedule_owner": "wordpress_wp_cron_or_local_runtime",
            "runtime_owner": "npcink-local-automation-runtime",
            "final_write_path": "core_proposal_required",
            "direct_wordpress_write": False,
        },
    }

    dispose_engine(database_url)


def test_current_entitlement_returns_pro_cloud_runtime_usage_detail(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    with get_session(database_url) as session:
        plan_version = session.get(PlanVersion, "pro_v1")
        assert plan_version is not None
        metadata = (
            plan_version.metadata_json if isinstance(plan_version.metadata_json, dict) else {}
        )
        plan_version.metadata_json = {
            **metadata,
            "max_batch_items": 25,
            "nightly_inspection_runs_per_period": 3,
            "nightly_inspection_retention_days": 21,
            "nightly_inspection_payload_modes": ["metadata_only"],
        }
        subscription = session.get(AccountSubscription, "sub_site_alpha_pro")
        assert subscription is not None
        session.add(
            UsageMeterEvent(
                account_id="acct_site_alpha",
                site_id="site_alpha",
                subscription_id=subscription.subscription_id,
                plan_version_id=subscription.plan_version_id,
                run_id="run_nightly_used_001",
                provider_call_id=None,
                event_kind="run",
                meter_key="runs",
                quantity=1.0,
                ability_family="automation",
                channel="openapi",
                execution_kind="nightly_site_inspection",
                execution_tier="cloud",
                data_classification="internal",
                currency="USD",
                dedupe_key="run:nightly-used-001:runs",
                payload_json={"source": "test_entitlement_usage"},
                created_at=datetime(2026, 5, 15, tzinfo=UTC),
            )
        )
        session.commit()

    query = "object_type=site&object_id=site_alpha"
    response = client.get(
        f"/v1/entitlements/current?{query}",
        headers=build_auth_headers(
            "GET",
            "/v1/entitlements/current",
            site_id="site_alpha",
            query=query,
        ),
    )

    assert response.status_code == 200
    pro_runtime = response.json()["data"]["entitlement"]["pro_cloud_runtime"]
    assert pro_runtime["limit_enforced"] is True
    assert pro_runtime["max_nightly_inspection_runs_per_period"] == 3
    assert pro_runtime["used_nightly_inspection_runs"] == 1
    assert pro_runtime["remaining_nightly_inspection_runs"] == 2
    assert pro_runtime["quota_exhausted"] is False
    assert pro_runtime["max_batch_items"] == 25
    assert pro_runtime["result_retention_days"] == 21
    assert pro_runtime["payload_modes"] == ["metadata_only"]

    dispose_engine(database_url)


def test_current_entitlement_requires_entitlement_scope(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    query = "object_type=site&object_id=site_readonly"
    response = client.get(
        f"/v1/entitlements/current?{query}",
        headers=build_auth_headers(
            "GET",
            "/v1/entitlements/current",
            site_id="site_readonly",
            key_id="key_readonly",
            query=query,
        ),
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "auth.scope_denied"

    dispose_engine(database_url)


def test_current_entitlement_rejects_cross_site_object(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    query = "object_type=site&object_id=site_beta"
    response = client.get(
        f"/v1/entitlements/current?{query}",
        headers=build_auth_headers(
            "GET",
            "/v1/entitlements/current",
            site_id="site_alpha",
            query=query,
        ),
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "auth.object_mismatch"

    dispose_engine(database_url)


def test_current_entitlement_rejects_unsupported_object_type(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    query = "object_type=agency&object_id=site_alpha"
    response = client.get(
        f"/v1/entitlements/current?{query}",
        headers=build_auth_headers(
            "GET",
            "/v1/entitlements/current",
            site_id="site_alpha",
            query=query,
        ),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "entitlement.object_type_unsupported"

    dispose_engine(database_url)
