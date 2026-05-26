from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

os.environ.setdefault("MAGICK_CLOUD_PORTAL_JWT_SECRET", "magick-cloud-portal-jwt-secret-32b")

from app.api.main import create_app
from app.adapters.repositories.addon_projection_repository import AddonProjectionRepository
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    AccountSubscription,
    RunRecord,
    RuntimeGuardEvent,
    ServiceAuditEvent,
    Site,
    UsageMeterEvent,
)
from app.core.services import CloudServices
from app.domain.addon_projection.service import (
    ADDON_OVERVIEW_PROJECTION_KIND,
    PROVIDER_RELEASE_SUMMARY_PROJECTION_KIND,
)
from app.domain.catalog.service import CatalogService
from app.domain.runtime.models import RuntimeRequest
from app.domain.runtime.service import RuntimeService
from tests.conftest import (
    TEST_PROVIDER_CONNECTION_SECRET,
    build_auth_headers,
    merge_json_headers,
    seed_site_auth,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'addon-routes.sqlite3'}"


def _build_client(tmp_path: Path) -> tuple[str, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    CatalogService(database_url).scan_provider_health()

    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        provider_connection_secret=TEST_PROVIDER_CONNECTION_SECRET,
    )
    return database_url, TestClient(create_app(CloudServices(settings=settings)))


def _seed_runtime_attention(database_url: str) -> dict[str, str]:
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["stats:read", "runtime:read", "runtime:execute", "runtime:resolve"],
    )
    runtime_service = RuntimeService(database_url)

    queued = runtime_service.execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="magick-ai/workflows/generate-post-draft",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="addon-queued-001",
            trace_id="addontracequeued0010000000000000",
            input_payload={"messages": [{"role": "user", "content": "queued"}]},
        )
    )
    running = runtime_service.execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="magick-ai/workflows/generate-post-draft",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="addon-running-001",
            trace_id="addontracerunning010000000000000",
            input_payload={"messages": [{"role": "user", "content": "running"}]},
        )
    )
    callback_failed = runtime_service.execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="magick-ai/workflows/generate-post-draft",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="addon-callback-001",
            trace_id="addontracecallback10000000000000",
            callback_url="https://example.com/callback",
            input_payload={"messages": [{"role": "user", "content": "callback"}]},
        )
    )
    callback_overdue = runtime_service.execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="magick-ai/workflows/generate-post-draft",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="addon-callback-overdue-001",
            trace_id="addontracecallbackoverdue0000001",
            callback_url="https://example.com/callback-overdue",
            input_payload={"messages": [{"role": "user", "content": "callback overdue"}]},
        )
    )
    retention_due = runtime_service.execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="magick-ai/workflows/generate-post-draft",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="addon-retention-001",
            trace_id="addontraceretention0000000000001",
            callback_url="https://example.com/callback",
            input_payload={"messages": [{"role": "user", "content": "retention"}]},
        )
    )
    failed = runtime_service.execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="magick-ai/workflows/generate-post-draft",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="addon-failed-001",
            trace_id="addontracefailed000000000000001",
            input_payload={
                "messages": [{"role": "user", "content": "failed"}],
                "simulate_error_for_instances": [
                    "openai-us-east-text-balanced",
                    "anthropic-us-east-text-balanced",
                ],
            },
            policy={"allow_fallback": False},
        )
    )

    now = datetime.now(UTC)
    with get_session(database_url) as session:
        queued_run = session.get(RunRecord, queued.run_id)
        running_run = session.get(RunRecord, running.run_id)
        callback_failed_run = session.get(RunRecord, callback_failed.run_id)
        callback_overdue_run = session.get(RunRecord, callback_overdue.run_id)
        retention_due_run = session.get(RunRecord, retention_due.run_id)
        failed_run = session.get(RunRecord, failed.run_id)
        assert queued_run is not None
        assert running_run is not None
        assert callback_failed_run is not None
        assert callback_overdue_run is not None
        assert retention_due_run is not None
        assert failed_run is not None

        queued_run.status = "queued"
        queued_run.started_at = now - timedelta(minutes=12)
        queued_run.finished_at = None
        queued_run.processing_started_at = None
        queued_run.callback_status = "pending"

        running_run.status = "running"
        running_run.started_at = now - timedelta(minutes=25)
        running_run.processing_started_at = now - timedelta(minutes=20)
        running_run.finished_at = None

        callback_failed_run.status = "succeeded"
        callback_failed_run.started_at = now - timedelta(minutes=25)
        callback_failed_run.finished_at = now - timedelta(minutes=22)
        callback_failed_run.callback_status = "failed"
        callback_failed_run.callback_last_attempt_at = now - timedelta(minutes=20)
        callback_failed_run.callback_last_error_code = "runtime.callback_delivery_failed"

        callback_overdue_run.status = "succeeded"
        callback_overdue_run.started_at = now - timedelta(minutes=21)
        callback_overdue_run.finished_at = now - timedelta(minutes=19)
        callback_overdue_run.callback_status = "pending"
        callback_overdue_run.callback_next_attempt_at = now - timedelta(minutes=12)
        callback_overdue_run.callback_last_attempt_at = now - timedelta(minutes=13)

        retention_due_run.status = "succeeded"
        retention_due_run.started_at = now - timedelta(hours=2)
        retention_due_run.finished_at = now - timedelta(hours=2) + timedelta(minutes=1)
        retention_due_run.retention_expires_at = now - timedelta(minutes=5)

        failed_run.status = "failed"
        failed_run.started_at = now - timedelta(minutes=40)
        failed_run.finished_at = now - timedelta(minutes=39)

        session.add(
            RuntimeGuardEvent(
                auth_surface="public",
                scope_kind="public_post_site",
                scope_id="site_alpha",
                site_id="site_alpha",
                key_id="key_default",
                client_ref="127.0.0.1",
                event_code="auth.replay_blocked",
                status_code=409,
                method="POST",
                path="/v1/runtime/execute",
                trace_id="addon-guard-trace",
                payload_json={"reason": "replay"},
            )
        )
        session.commit()

    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["stats:read", "runtime:read", "runtime:execute", "runtime:resolve"],
        expires_at=now + timedelta(days=3),
        subscription_status="past_due",
        budgets={"max_runs_per_period": 1},
        policy={
            "subscription": {"grace_period_days": 5},
            "budgets": {"runs": {"grace_requests": 0}},
        },
    )
    with get_session(database_url) as session:
        site = session.get(Site, "site_alpha")
        assert site is not None
        subscription = session.scalar(
            select(AccountSubscription).where(AccountSubscription.account_id == site.account_id)
        )
        assert subscription is not None
        session.add(
            UsageMeterEvent(
                account_id=subscription.account_id,
                site_id="site_alpha",
                subscription_id=subscription.subscription_id,
                plan_version_id=subscription.plan_version_id,
                run_id=None,
                provider_call_id=None,
                event_kind="usage",
                meter_key="runs",
                quantity=2.0,
                ability_family="magick-ai/workflows",
                channel="openapi",
                execution_kind="text",
                execution_tier="cloud",
                data_classification="internal",
                currency="USD",
                dedupe_key="addon-budget-over-limit-001",
                payload_json={"source": "test"},
            )
        )
        session.commit()

    return {
        "queued_run_id": queued.run_id,
        "running_run_id": running.run_id,
        "callback_failed_run_id": callback_failed.run_id,
        "callback_overdue_run_id": callback_overdue.run_id,
        "retention_due_run_id": retention_due.run_id,
        "failed_run_id": failed.run_id,
    }


def test_addon_dashboard_route_returns_customer_safe_summary_and_notices(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    _seed_runtime_attention(database_url)

    response = client.get(
        "/v1/addon/dashboard",
        headers=build_auth_headers(
            "GET",
            "/v1/addon/dashboard",
            site_id="site_alpha",
            trace_id="addonroutedashboard0000000000001",
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    data = payload["data"]

    assert payload["meta"]["revision"] == "m7"
    assert data["site"]["site_id"] == "site_alpha"
    assert data["connection"]["auth_surface"] == "runtime_hmac_site_key"
    assert data["connection"]["auth_ok"] is True
    assert "base_url_hint" not in data["connection"]
    assert data["source"] == "live_fallback"
    assert data["fallback_reason"] == "projection_missing"
    assert isinstance(data["generated_at"], str) and data["generated_at"]
    assert isinstance(data["fresh_until"], str) and data["fresh_until"]
    assert data["stale"] is False
    assert isinstance(data["generation_ms"], int)
    assert data["current_key"]["key_id"] == "key_default"
    assert data["subscription"]["status"] == "past_due"
    assert data["subscription"]["plan_name"] == "Free"
    assert data["entitlements"]["max_batch_items"] == 0
    assert data["runtime"]["queue"]["queued_runs"] == 1
    assert data["runtime"]["callback"]["failed"] == 1
    assert data["runtime"]["retention"]["due_purge"] == 1
    assert data["runtime"]["guard"]["recent_rejected"] >= 1

    notice_codes = {item["code"] for item in data["notices"]}
    assert {
        "key.expiring_soon",
        "subscription.past_due",
        "entitlement.budget_exceeded",
        "runtime.queue_backlog",
        "runtime.callback_failed",
        "runtime.guard_rejections_detected",
    } <= notice_codes
    guard_notice = next(
        item for item in data["notices"] if item["code"] == "runtime.guard_rejections_detected"
    )
    assert "最近 24 小时拦截" in guard_notice["message"]
    assert "API Key 是否属于当前站点" in guard_notice["message"]
    assert "防护事件" in guard_notice["message"]

    dispose_engine(database_url)


def test_addon_provider_release_summary_route_returns_customer_safe_release_evidence(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["stats:read"],
    )

    response = client.get(
        "/v1/addon/providers/release-summary",
        headers=build_auth_headers(
            "GET",
            "/v1/addon/providers/release-summary",
            site_id="site_alpha",
            trace_id="addonproviderrelease000000000001",
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    data = payload["data"]

    assert payload["meta"]["revision"] == "m7"
    assert data["site_id"] == "site_alpha"
    assert data["source"] == "live_fallback"
    assert data["fallback_reason"] == "projection_missing"
    assert data["stale"] is False
    assert isinstance(data["fresh_until"], str) and data["fresh_until"]
    assert isinstance(data["generation_ms"], int)
    assert isinstance(data["items"], list)
    if data["items"]:
        item = data["items"][0]
        assert "active_execution_revision" in item
        assert "execution_release_state" in item
        assert "execution_release_test_state" in item
        assert "execution_release_smoke_state" in item
        assert "last_release_smoke_ok_at" in item
        assert "last_release_promoted_at" in item
        assert "last_release_smoked_at" in item
        assert "last_release_preflight_ok_at" in item

    dispose_engine(database_url)


def test_addon_dashboard_route_prefers_fresh_projection(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(database_url, site_id="site_alpha", scopes=["stats:read"])
    now = datetime.now(UTC)

    with get_session(database_url) as session:
        repository = AddonProjectionRepository(session)
        repository.upsert_projection(
            site_id="site_alpha",
            projection_kind=ADDON_OVERVIEW_PROJECTION_KIND,
            payload_json={
                "site": {
                    "site_id": "site_alpha",
                    "site_name": "Projected Site",
                    "account_id": "acct_projected",
                },
                "connection": {
                    "auth_surface": "runtime_hmac_site_key",
                    "live_ok": True,
                    "auth_ok": True,
                },
                "site_keys": [
                    {
                        "key_id": "key_default",
                        "label": "Projected Key",
                        "status": "active",
                        "last_four": "1234",
                    }
                ],
                "subscription": {"status": "active", "plan_code": "v1", "plan_name": "Projected Plan"},
                "entitlements": {"budget_state": {}, "subscription_grace": {}, "usage_totals": {}},
                "billing": {"latest_snapshot_at": "", "reconciliation_status": "ok"},
                "usage": {"windows": {"today": {"runs_total": 0}}},
                "runtime": {
                    "queue": {"queued_runs": 0, "running_runs": 0},
                    "callback": {"failed": 0, "due_now": 0},
                    "retention": {"due_purge": 0},
                    "guard": {"recent_rejected": 0, "top_codes": []},
                },
                "notices": [],
            },
            generated_at=now,
            fresh_until=now + timedelta(seconds=120),
            source_revision="addon_projection_v1",
            generation_ms=7,
        )
        session.commit()

    response = client.get(
        "/v1/addon/dashboard",
        headers=build_auth_headers(
            "GET",
            "/v1/addon/dashboard",
            site_id="site_alpha",
            trace_id="addonrouteprojected000000000001",
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source"] == "projection"
    assert "fallback_reason" not in data
    assert data["site"]["site_name"] == "Projected Site"
    assert data["current_key"]["key_id"] == "key_default"
    assert data["current_key"]["label"] == "Projected Key"
    assert data["generation_ms"] == 7

    dispose_engine(database_url)


def test_addon_dashboard_route_serves_recent_stale_projection_without_live_fallback(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    _seed_runtime_attention(database_url)
    stale_now = datetime.now(UTC) - timedelta(minutes=10)

    with get_session(database_url) as session:
        repository = AddonProjectionRepository(session)
        repository.upsert_projection(
            site_id="site_alpha",
            projection_kind=ADDON_OVERVIEW_PROJECTION_KIND,
            payload_json={
                "site": {"site_id": "site_alpha", "site_name": "Stale Site", "account_id": "acct_stale"},
                "connection": {"auth_surface": "runtime_hmac_site_key", "live_ok": True, "auth_ok": True},
                "site_keys": [],
                "subscription": {"status": "active", "plan_code": "v1", "plan_name": "Stale Plan"},
                "entitlements": {"budget_state": {}, "subscription_grace": {}, "usage_totals": {}},
                "billing": {"latest_snapshot_at": "", "reconciliation_status": "ok"},
                "usage": {"windows": {"today": {"runs_total": 0}}},
                "runtime": {
                    "queue": {"queued_runs": 0, "running_runs": 0},
                    "callback": {"failed": 0, "due_now": 0},
                    "retention": {"due_purge": 0},
                    "guard": {"recent_rejected": 0, "top_codes": []},
                },
                "notices": [],
            },
            generated_at=stale_now,
            fresh_until=stale_now + timedelta(seconds=120),
            source_revision="addon_projection_v1",
            generation_ms=9,
        )
        session.commit()

    response = client.get(
        "/v1/addon/dashboard",
        headers=build_auth_headers(
            "GET",
            "/v1/addon/dashboard",
            site_id="site_alpha",
            trace_id="addonroutestaleprojection000001",
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source"] == "projection"
    assert data["stale"] is True
    assert "fallback_reason" not in data
    assert data["site"]["site_name"] == "Stale Site"
    assert data["generation_ms"] == 9

    dispose_engine(database_url)


def test_addon_dashboard_route_falls_back_when_projection_is_hard_stale(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    _seed_runtime_attention(database_url)
    stale_now = datetime.now(UTC) - timedelta(minutes=45)

    with get_session(database_url) as session:
        repository = AddonProjectionRepository(session)
        repository.upsert_projection(
            site_id="site_alpha",
            projection_kind=ADDON_OVERVIEW_PROJECTION_KIND,
            payload_json={
                "site": {"site_id": "site_alpha", "site_name": "Hard Stale Site", "account_id": "acct_stale"},
                "connection": {"auth_surface": "runtime_hmac_site_key", "live_ok": True, "auth_ok": True},
                "site_keys": [],
                "subscription": {"status": "active", "plan_code": "v1", "plan_name": "Stale Plan"},
                "entitlements": {"budget_state": {}, "subscription_grace": {}, "usage_totals": {}},
                "billing": {"latest_snapshot_at": "", "reconciliation_status": "ok"},
                "usage": {"windows": {"today": {"runs_total": 0}}},
                "runtime": {
                    "queue": {"queued_runs": 0, "running_runs": 0},
                    "callback": {"failed": 0, "due_now": 0},
                    "retention": {"due_purge": 0},
                    "guard": {"recent_rejected": 0, "top_codes": []},
                },
                "notices": [],
            },
            generated_at=stale_now,
            fresh_until=stale_now + timedelta(seconds=120),
            source_revision="addon_projection_v1",
            generation_ms=9,
        )
        session.commit()

    response = client.get(
        "/v1/addon/dashboard",
        headers=build_auth_headers(
            "GET",
            "/v1/addon/dashboard",
            site_id="site_alpha",
            trace_id="addonroutehardstaleprojection001",
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source"] == "live_fallback"
    assert data["fallback_reason"] == "projection_stale"
    assert data["site"]["site_name"] != "Hard Stale Site"
    assert data["runtime"]["queue"]["queued_runs"] == 1

    dispose_engine(database_url)


def test_addon_routes_fall_back_when_projection_lookup_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_url, client = _build_client(tmp_path)
    _seed_runtime_attention(database_url)

    def fail_get_projection(self, *, site_id: str, projection_kind: str):
        raise RuntimeError(f"projection lookup failed for {projection_kind}:{site_id}")

    monkeypatch.setattr(
        AddonProjectionRepository,
        "get_projection",
        fail_get_projection,
    )

    dashboard = client.get(
        "/v1/addon/dashboard",
        headers=build_auth_headers(
            "GET",
            "/v1/addon/dashboard",
            site_id="site_alpha",
            trace_id="addonprojectionlookuperror000001",
        ),
    )
    assert dashboard.status_code == 200
    dashboard_data = dashboard.json()["data"]
    assert dashboard_data["source"] == "live_fallback"
    assert dashboard_data["fallback_reason"] == "projection_error"
    assert isinstance(dashboard_data["fresh_until"], str) and dashboard_data["fresh_until"]

    provider = client.get(
        "/v1/addon/providers/release-summary",
        headers=build_auth_headers(
            "GET",
            "/v1/addon/providers/release-summary",
            site_id="site_alpha",
            trace_id="addonproviderprojectionerror0001",
        ),
    )
    assert provider.status_code == 200
    provider_data = provider.json()["data"]
    assert provider_data["source"] == "live_fallback"
    assert provider_data["fallback_reason"] == "projection_error"
    assert isinstance(provider_data["fresh_until"], str) and provider_data["fresh_until"]

    dispose_engine(database_url)


def test_addon_provider_release_summary_route_prefers_fresh_projection(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(database_url, site_id="site_alpha", scopes=["stats:read"])
    now = datetime.now(UTC)

    with get_session(database_url) as session:
        repository = AddonProjectionRepository(session)
        repository.upsert_projection(
            site_id="site_alpha",
            projection_kind=PROVIDER_RELEASE_SUMMARY_PROJECTION_KIND,
            payload_json={
                "site_id": "site_alpha",
                "items": [
                    {
                        "connection_id": "conn_projected",
                        "display_name": "Projected Provider",
                        "provider_type": "openai",
                        "enabled": True,
                        "active_execution_revision": "rev-live",
                        "candidate_execution_revision": "rev-next",
                        "execution_release_state": "active",
                        "execution_release_test_state": "passed",
                        "execution_release_smoke_state": "passed",
                        "last_release_smoke_revision": "rev-live",
                        "last_release_smoke_ok_at": "2026-04-15T12:00:00Z",
                        "last_release_smoked_at": "2026-04-15T12:00:00Z",
                        "last_release_promoted_at": "2026-04-15T12:05:00Z",
                        "last_release_preflight_ok_at": "2026-04-15T12:05:00Z",
                    }
                ],
            },
            generated_at=now,
            fresh_until=now + timedelta(seconds=300),
            source_revision="addon_projection_v1",
            generation_ms=11,
        )
        session.commit()

    response = client.get(
        "/v1/addon/providers/release-summary",
        headers=build_auth_headers(
            "GET",
            "/v1/addon/providers/release-summary",
            site_id="site_alpha",
            trace_id="addonproviderprojection0000001",
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source"] == "projection"
    assert data["items"][0]["connection_id"] == "conn_projected"
    assert data["generation_ms"] == 11

    dispose_engine(database_url)


def test_addon_runtime_callback_registration_route_persists_registered_terminal_callback(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    payload = {
        "enabled": True,
        "callback_url": "https://example.com/wp-json/magick-ai/open/v1/runtime/callback",
        "key_id": "runtime_callback_key",
        "secret": "runtime-callback-secret-for-tests-32b",
        "callback_id": "runtime_terminal",
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/v1/addon/runtime/callback-registration",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/addon/runtime/callback-registration",
                site_id="site_alpha",
                idempotency_key="addon-runtime-callback-registration-001",
                trace_id="addonruntimecallbackregister001",
                body=body,
            )
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["site_id"] == "site_alpha"
    assert data["runtime_callback"] == {
        "enabled": True,
        "callback_url": "https://example.com/wp-json/magick-ai/open/v1/runtime/callback",
        "key_id": "runtime_callback_key",
        "callback_id": "runtime_terminal",
    }

    with get_session(database_url) as session:
        site = session.get(Site, "site_alpha")
        assert site is not None
        metadata = site.metadata_json if isinstance(site.metadata_json, dict) else {}
        runtime_callbacks = metadata.get("runtime_callbacks")
        runtime_callbacks = runtime_callbacks if isinstance(runtime_callbacks, dict) else {}
        terminal = runtime_callbacks.get("terminal")
        terminal = terminal if isinstance(terminal, dict) else {}
        assert terminal["enabled"] is True
        assert (
            terminal["callback_url"]
            == "https://example.com/wp-json/magick-ai/open/v1/runtime/callback"
        )
        assert terminal["key_id"] == "runtime_callback_key"
        assert isinstance(terminal.get("secret_ciphertext"), str)
        assert terminal["secret_ciphertext"] != ""
        assert "secret" not in terminal
        assert terminal["callback_id"] == "runtime_terminal"
    assert "runtime_terminal_callback_secret" not in metadata

    dispose_engine(database_url)


def test_addon_runtime_callback_registration_rejects_insecure_callback_target(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )
    payload = {
        "enabled": True,
        "callback_url": "http://127.0.0.1:8080/callback",
        "key_id": "mak_test_callback_key",
        "secret": "runtime-terminal-secret-32bytes!!",
        "callback_id": "runtime_terminal",
    }
    body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/v1/addon/runtime/callback-registration",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/addon/runtime/callback-registration",
                site_id="site_alpha",
                idempotency_key="addon-callback-invalid-001",
                trace_id="addoncallbackinvalid001000000000",
                body=body,
            )
        ),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "service.validation_error"

    dispose_engine(database_url)


def test_addon_runtime_runs_route_returns_attention_groups(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    seeded = _seed_runtime_attention(database_url)

    response = client.get(
        "/v1/addon/runtime/runs?view=attention&limit=5",
        headers=build_auth_headers(
            "GET",
            "/v1/addon/runtime/runs",
            site_id="site_alpha",
            trace_id="addonrouteruns0000000000000001",
            query="view=attention&limit=5",
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["site_id"] == "site_alpha"
    assert payload["view"] == "attention"
    assert payload["summary"]["queued_runs"] == 1
    assert payload["summary"]["running_runs"] == 1
    assert payload["summary"]["callback_failed"] == 1
    assert payload["summary"]["retention_due"] == 1
    assert payload["summary"]["guard_rejected_recent"] >= 1

    groups = {item["issue_kind"]: item for item in payload["groups"]}
    assert groups["queued_stale"]["items"][0]["headline"] == "magick-ai/workflows/generate-post-draft"
    assert groups["queued_stale"]["items"][0]["attention_reason"] == (
        "该运行已超过队列陈旧阈值，系统会优先自动重新投递队列信号。"
    )
    assert groups["queued_stale"]["items"][0]["suggested_actions"][0]["action"] == (
        "requeue_stale_queued"
    )
    assert groups["running_stale"]["items"][0]["suggested_actions"][0]["action"] == (
        "mark_stale_running_failed"
    )
    assert groups["running_stale"]["items"][0]["suggested_actions"][0]["mode"] == "operator_only"
    assert groups["callback_overdue"]["items"][0]["run_id"] == seeded["callback_overdue_run_id"]
    assert groups["callback_overdue"]["items"][0]["suggested_actions"][0]["action"] == (
        "redeliver_failed_callback"
    )
    assert groups["callback_overdue"]["items"][0]["suggested_actions"][0]["mode"] == "worker_auto"
    assert groups["callback_failed"]["items"][0]["callback_last_error_code"] == "runtime.callback_delivery_failed"
    assert groups["retention_due"]["items"][0]["retention_expires_at"] != ""

    dispose_engine(database_url)


def test_addon_runtime_run_detail_and_result_routes_return_customer_safe_payloads(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    seeded = _seed_runtime_attention(database_url)
    run_id = seeded["callback_failed_run_id"]

    detail_response = client.get(
        f"/v1/addon/runtime/runs/{run_id}",
        headers=build_auth_headers(
            "GET",
            f"/v1/addon/runtime/runs/{run_id}",
            site_id="site_alpha",
            trace_id="addonrunroutedetail000000000001",
        ),
    )

    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert detail["run_id"] == run_id
    assert detail["status"] == "succeeded"
    assert detail["execution_pattern"] == "inline"
    assert isinstance(detail["task_backend"], dict)

    result_response = client.get(
        f"/v1/addon/runtime/runs/{run_id}/result",
        headers=build_auth_headers(
            "GET",
            f"/v1/addon/runtime/runs/{run_id}/result",
            site_id="site_alpha",
            trace_id="addonrunrouteresult000000000001",
        ),
    )

    assert result_response.status_code == 200
    result = result_response.json()["data"]
    assert result["run_id"] == run_id
    assert result["status"] == "succeeded"
    assert isinstance(result["result"], dict)
    assert result["execution_context"]["execution_pattern"] == "inline"

    dispose_engine(database_url)


def test_addon_runtime_repair_route_requeues_stale_queued_runs_and_audits(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    seeded = _seed_runtime_attention(database_url)
    run_id = seeded["queued_run_id"]
    with get_session(database_url) as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        run.started_at = datetime.now(UTC) - timedelta(minutes=10)
        session.commit()
    body = json.dumps({"action": "requeue_stale_queued"}).encode("utf-8")

    response = client.post(
        f"/v1/addon/runtime/runs/{run_id}/repair",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                f"/v1/addon/runtime/runs/{run_id}/repair",
                site_id="site_alpha",
                idempotency_key="addon-repair-queued-001",
                trace_id="addonrepairqueued000000000001",
                body=body,
            )
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["run_id"] == run_id
    assert data["repair_action"] == "requeue_stale_queued"
    assert data["summary"]["state_transition"] == "queued->queued"
    assert data["after"]["status"] == "queued"

    with get_session(database_url) as session:
        event = session.scalar(
            select(ServiceAuditEvent)
            .where(ServiceAuditEvent.scope_id == run_id)
            .order_by(ServiceAuditEvent.created_at.desc())
        )
        assert event is not None
        assert event.event_kind == "runtime.repair.requeue_stale_queued"

    dispose_engine(database_url)


def test_addon_runtime_repair_route_marks_stale_running_failed_with_evidence(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    seeded = _seed_runtime_attention(database_url)
    run_id = seeded["running_run_id"]
    with get_session(database_url) as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        run.processing_started_at = datetime.now(UTC) - timedelta(minutes=20)
        session.commit()
    body = json.dumps(
        {
            "action": "mark_stale_running_failed",
            "operator_reason": "worker lost lease",
            "operator_evidence": "queue drained twice without heartbeat",
        }
    ).encode("utf-8")

    response = client.post(
        f"/v1/addon/runtime/runs/{run_id}/repair",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                f"/v1/addon/runtime/runs/{run_id}/repair",
                site_id="site_alpha",
                idempotency_key="addon-repair-running-001",
                trace_id="addonrepairrunning00000000001",
                body=body,
            )
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["repair_action"] == "mark_stale_running_failed"
    assert data["summary"]["state_transition"] == "running->failed"
    assert data["summary"]["operator_reason"] == "worker lost lease"
    assert data["after"]["status"] == "failed"

    with get_session(database_url) as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        assert run.error_code == "runtime.operator_stale_running_failed"

    dispose_engine(database_url)


def test_addon_runtime_repair_route_rejects_short_stale_running_evidence(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    seeded = _seed_runtime_attention(database_url)
    run_id = seeded["running_run_id"]
    with get_session(database_url) as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        run.processing_started_at = datetime.now(UTC) - timedelta(minutes=20)
        session.commit()
    body = json.dumps(
        {
            "action": "mark_stale_running_failed",
            "operator_reason": "stale",
            "operator_evidence": "no heartbeat",
        }
    ).encode("utf-8")

    response = client.post(
        f"/v1/addon/runtime/runs/{run_id}/repair",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                f"/v1/addon/runtime/runs/{run_id}/repair",
                site_id="site_alpha",
                idempotency_key="addon-repair-running-short-001",
                trace_id="addonrepairrunningshort000001",
                body=body,
            )
        ),
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] in {
        "runtime.repair_reason_too_short",
        "runtime.repair_evidence_too_short",
    }

    dispose_engine(database_url)


def test_addon_routes_reject_invalid_signature(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(database_url, site_id="site_alpha", scopes=["stats:read", "runtime:read"])

    response = client.get(
        "/v1/addon/dashboard",
        headers=build_auth_headers(
            "GET",
            "/v1/addon/dashboard",
            site_id="site_alpha",
            secret="wrong-secret",
            trace_id="addoninvalidsig000000000000001",
        ),
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.invalid_signature"

    dispose_engine(database_url)


def test_addon_routes_reject_wrong_site_key_scope(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(database_url, site_id="site_alpha", scopes=["stats:read", "runtime:read"])
    seed_site_auth(
        database_url,
        site_id="site_beta",
        key_id="key_beta",
        secret="site-beta-secret",
        scopes=["stats:read", "runtime:read"],
    )

    response = client.get(
        "/v1/addon/dashboard",
        headers=build_auth_headers(
            "GET",
            "/v1/addon/dashboard",
            site_id="site_alpha",
            key_id="key_beta",
            secret="site-beta-secret",
            trace_id="addonwrongscope00000000000001",
        ),
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.invalid_key"

    dispose_engine(database_url)
