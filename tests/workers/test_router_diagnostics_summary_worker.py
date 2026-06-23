from __future__ import annotations

import json
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.adapters.repositories.stats_repository import StatsRepository
from app.core.callback_security import RuntimeCallbackTargetValidationError
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import SITE_STATUS_SUSPENDED, RunRecord, RuntimeGuardEvent
from app.domain.catalog.service import CatalogService
from app.domain.runtime.models import RuntimeRequest
from app.domain.runtime.service import RuntimeService
from app.domain.usage.rollup import ROUTER_DIAGNOSTICS_BATCH_SCOPE
from app.workers.router_diagnostics_summary import _dispatch_callback, run_once
from tests.conftest import seed_site_auth


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'router-diagnostics-worker.sqlite3'}"


def _resolve_example_test_to_public_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def test_router_diagnostics_summary_worker_generates_active_site_runtime_summary(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    CatalogService(database_url).scan_provider_health()
    seed_site_auth(database_url, site_id="site_alpha", scopes=["stats:read"])
    seed_site_auth(
        database_url,
        site_id="site_suspended",
        scopes=["stats:read"],
        site_status=SITE_STATUS_SUSPENDED,
    )

    runtime_service = RuntimeService(database_url)
    result = runtime_service.execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="worker-router-diagnostics-a",
            trace_id="worker-router-diagnostics-a",
            input_payload={"messages": [{"role": "user", "content": "diagnostics batch"}]},
        )
    )

    fixed_now = datetime(2026, 3, 24, 9, 20, tzinfo=UTC)
    with get_session(database_url) as session:
        run = session.scalar(select(RunRecord).where(RunRecord.run_id == result.run_id))
        assert run is not None
        run.started_at = fixed_now - timedelta(minutes=20)
        run.finished_at = fixed_now - timedelta(minutes=19)
        run.policy_json = {"callback_url": "https://callbacks.example.test/runtime"}
        run.callback_status = "failed"
        run.callback_last_attempt_at = fixed_now - timedelta(minutes=4)
        run.error_code = "callback.failed"

        session.add(
            RuntimeGuardEvent(
                auth_surface="openapi",
                scope_kind="site",
                scope_id="site_alpha",
                site_id="site_alpha",
                key_id="key_alpha",
                client_ref="client_alpha",
                event_code="auth.rate_limit_exceeded",
                status_code=429,
                method="GET",
                path="/v1/runtime/execute",
                trace_id="trace-diagnostics-worker-1",
                payload_json={"reason": "synthetic"},
                created_at=fixed_now - timedelta(minutes=2),
            )
        )
        session.commit()

    summary = run_once(
        Settings(
            project_name="Npcink AI Cloud Test",
            environment="test",
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
            router_diagnostics_worker_recent_minutes=60,
            router_diagnostics_worker_site_limit=10,
        ),
        now_factory=lambda: fixed_now,
    )

    assert summary["source"] == "cloud_router_diagnostics_worker"
    assert summary["recent_minutes"] == 60
    assert summary["sites_total"] == 1
    assert summary["stored_batches_total"] == 1
    assert summary["delivery_owner"] == "wordpress_fetch_apply"
    assert summary["rollup_scope_kind"] == ROUTER_DIAGNOSTICS_BATCH_SCOPE
    assert summary["callback_attempted_total"] == 0
    assert summary["callback_delivered_total"] == 0
    assert summary["callback_skipped_total"] == 1
    assert len(summary["site_batches"]) == 1
    batch = summary["site_batches"][0]
    assert batch["site_id"] == "site_alpha"
    assert batch["regressions_count"] >= 1
    assert batch["quality_regressions_count"] >= 1
    assert batch["regression_items_total"] >= 1
    assert batch["quality_items_total"] >= 1
    assert batch["source"] == "cloud_router_diagnostics"
    assert batch["scope_id"] == "2026-03-24T09:20:00Z__60m"

    with get_session(database_url) as session:
        repository = StatsRepository(session)
        stored_batches = repository.list_usage_rollups(
            site_scope="site_alpha",
            scope_kind=ROUTER_DIAGNOSTICS_BATCH_SCOPE,
        )

    assert len(stored_batches) == 1
    assert stored_batches[0].payload_json["delivery"]["buffer_kind"] == "usage_rollup"
    assert stored_batches[0].payload_json["report"]["regressions"]["count"] >= 1

    dispose_engine(database_url)


def test_router_diagnostics_summary_worker_dispatches_optional_callback_when_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _resolve_example_test_to_public_ip(monkeypatch)
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    CatalogService(database_url).scan_provider_health()
    seed_site_auth(database_url, site_id="site_alpha", scopes=["stats:read"])

    with get_session(database_url) as session:
        site = CommercialRepository(session).get_site("site_alpha")
        assert site is not None
        site.metadata_json = {
            "public_base_url": "https://wp.example.test",
            "router_diagnostics_callback_key_id": "kd_alpha",
            "router_diagnostics_callback_secret": "callback-secret-alpha",
        }
        session.commit()

    runtime_service = RuntimeService(database_url)
    result = runtime_service.execute(
        RuntimeRequest(
            site_id="site_alpha",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="worker-router-diagnostics-b",
            trace_id="worker-router-diagnostics-b",
            input_payload={"messages": [{"role": "user", "content": "diagnostics callback"}]},
        )
    )

    fixed_now = datetime(2026, 3, 24, 9, 20, tzinfo=UTC)
    with get_session(database_url) as session:
        run = session.scalar(select(RunRecord).where(RunRecord.run_id == result.run_id))
        assert run is not None
        run.started_at = fixed_now - timedelta(minutes=20)
        run.finished_at = fixed_now - timedelta(minutes=19)
        run.policy_json = {"callback_url": "https://callbacks.example.test/runtime"}
        run.callback_status = "failed"
        run.callback_last_attempt_at = fixed_now - timedelta(minutes=4)
        run.error_code = "callback.failed"
        session.add(
            RuntimeGuardEvent(
                auth_surface="openapi",
                scope_kind="site",
                scope_id="site_alpha",
                site_id="site_alpha",
                key_id="key_alpha",
                client_ref="client_alpha",
                event_code="auth.rate_limit_exceeded",
                status_code=429,
                method="GET",
                path="/v1/runtime/execute",
                trace_id="trace-diagnostics-worker-2",
                payload_json={"reason": "synthetic"},
                created_at=fixed_now - timedelta(minutes=2),
            )
        )
        session.commit()

    delivered_requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        delivered_requests.append(
            {
                "url": str(request.url),
                "headers": dict(request.headers),
                "body": json.loads(request.content.decode("utf-8")),
            }
        )
        return httpx.Response(202, json={"ok": True})

    summary = run_once(
        Settings(
            project_name="Npcink AI Cloud Test",
            environment="test",
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
            router_diagnostics_worker_recent_minutes=60,
            router_diagnostics_worker_site_limit=10,
        ),
        now_factory=lambda: fixed_now,
        transport=httpx.MockTransport(handler),
    )

    assert summary["callback_attempted_total"] == 1
    assert summary["callback_delivered_total"] == 1
    assert summary["callback_failed_total"] == 0
    assert len(delivered_requests) == 1
    delivered = delivered_requests[0]
    assert (
        delivered["url"]
        == "https://wp.example.test/wp-json/npcink/open/v1/router/diagnostics/callback"
    )
    assert delivered["headers"]["x-npcink-cloud-event"] == "router.diagnostics.batch"
    assert delivered["headers"]["x-npcink-key-id"] == "kd_alpha"
    assert delivered["body"]["config_revision"] == "cloud_runtime_summary_worker"
    assert delivered["body"]["delivery"]["buffer_kind"] == "usage_rollup"
    assert summary["site_batches"][0]["callback"]["status"] == "delivered"

    dispose_engine(database_url)


def test_router_diagnostics_callback_rejects_private_target_before_dispatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected callback dispatch to {request.url}")

    with pytest.raises(RuntimeCallbackTargetValidationError):
        _dispatch_callback(
            callback_url="https://127.0.0.1/wp-json/npcink/open/v1/router/diagnostics/callback",
            site_id="site_alpha",
            key_id="kd_alpha",
            secret="callback-secret-alpha",
            payload={"status": "test"},
            transport=httpx.MockTransport(handler),
        )
