from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.core.db import dispose_engine, init_schema
from app.dev.bootstrap_portal_site import bootstrap_portal_site
from app.dev.seed_runtime import seed_site_auth


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'bootstrap-portal-site.sqlite3'}"


def test_bootstrap_portal_site_binds_principal_to_existing_site_without_demo_usage(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        portal_jwt_secret="dev-portal-jwt-secret-with-at-least-thirty-two-bytes",
    )

    seed_site_auth(
        settings=settings,
        site_id="site_realish",
        key_id="key_existing",
        secret="npcink-cloud-existing-secret",
        site_name="Realish Site",
        scopes=["runtime:resolve", "runtime:execute", "runtime:read", "stats:read"],
        account_id="acct_realish",
        plan_id="plan_realish",
        plan_version_id="plan_realish_v1",
        subscription_id="sub_realish",
    )

    result = bootstrap_portal_site(
        settings=settings,
        site_id="site_realish",
        principal_email="buyer@example.com",
        public_base_url="http://127.0.0.1:8010",
        rebuild_billing_snapshot=True,
        issue_key=False,
        key_id="",
        secret="",
        key_label="",
        scopes=["runtime:resolve", "runtime:execute", "runtime:read", "stats:read"],
    )

    assert result["data_mode"] == "real_site_bootstrap"
    assert result["portal"]["account_membership"]["principal_id"].startswith("prn_")
    assert result["portal"]["account_membership"]["status"] == "active"
    assert result["portal"]["account_membership"]["membership_status"] == "active"
    assert result["site_summary"]["site"]["site_id"] == "site_realish"
    assert result["usage_summary"]["windows"]["today"]["runs_total"] == 0
    assert result["usage_meter"]["totals"] == {}
    assert result["billing_snapshot"]["totals"] == {}
    assert len(result["billing_snapshots"]["items"]) == 1
    assert len(result["site_keys"]["items"]) == 1
    assert result["issued_key"] is None
    assert result["sample_site"]["auth_mode"] == "email_code"
    assert (
        result["sample_site"]["login_code_request"]["verify_url"]
        == "http://127.0.0.1:8010/portal/v1/auth/code/verify"
    )

    dispose_engine(database_url)


def test_bootstrap_portal_site_can_optionally_issue_one_new_key(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        portal_jwt_secret="dev-portal-jwt-secret-with-at-least-thirty-two-bytes",
    )

    seed_site_auth(
        settings=settings,
        site_id="site_realish_issue",
        key_id="key_existing",
        secret="npcink-cloud-existing-secret",
        site_name="Realish Site",
        scopes=["runtime:resolve", "runtime:execute", "runtime:read", "stats:read"],
        account_id="acct_realish_issue",
        plan_id="plan_realish",
        plan_version_id="plan_realish_v1",
        subscription_id="sub_realish_issue",
    )

    result = bootstrap_portal_site(
        settings=settings,
        site_id="site_realish_issue",
        principal_email="buyer@example.com",
        public_base_url="http://127.0.0.1:8010",
        rebuild_billing_snapshot=False,
        issue_key=True,
        key_id="key_portal_issue",
        secret="npcink-cloud-issued-secret",
        key_label="Issued from bootstrap",
        scopes=["runtime:resolve", "stats:read"],
    )

    assert result["issued_key"]["key_id"] == "key_portal_issue"
    assert result["issued_key"]["secret"] == "npcink-cloud-issued-secret"
    assert result["sample_site"]["cloud_api_key"].startswith("mak1_")
    assert len(result["site_keys"]["items"]) == 2

    dispose_engine(database_url)
