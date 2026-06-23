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
from app.core.models import SITE_STATUS_SUSPENDED, ProviderCallRecord, RunRecord
from app.domain.catalog.service import CatalogService
from app.domain.runtime.models import RuntimeRequest
from app.domain.runtime.service import RuntimeService
from app.domain.usage.rollup import ROUTER_PERFORMANCE_BATCH_SCOPE
from app.workers.router_performance_snapshot import _dispatch_callback, run_once
from tests.conftest import seed_site_auth


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'router-performance-worker.sqlite3'}"


def _resolve_example_test_to_public_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def test_router_performance_snapshot_worker_generates_active_site_batches(
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
            idempotency_key="worker-router-performance-a",
            trace_id="worker-router-performance-a",
            input_payload={"messages": [{"role": "user", "content": "worker batch"}]},
            policy={"preset_id": "preset.alpha"},
        )
    )

    fixed_now = datetime(2026, 3, 24, 9, 20, tzinfo=UTC)
    with get_session(database_url) as session:
        run = session.scalar(select(RunRecord).where(RunRecord.run_id == result.run_id))
        assert run is not None
        run.started_at = fixed_now - timedelta(minutes=30)
        run.finished_at = fixed_now - timedelta(minutes=30) + timedelta(milliseconds=120)
        run.policy_json = {"preset_id": "preset.alpha"}

        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord)
                .where(ProviderCallRecord.run_id == result.run_id)
                .order_by(ProviderCallRecord.id.asc())
            )
        )
        for index, provider_call in enumerate(provider_calls):
            provider_call.created_at = run.started_at + timedelta(seconds=index + 1)
            if index == 0:
                provider_call.error_code = "quota.rate_limited"

        session.commit()

    summary = run_once(
        Settings(
            project_name="Npcink AI Cloud Test",
            environment="test",
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
            router_performance_worker_window_hours=1,
            router_performance_worker_site_limit=10,
        ),
        now_factory=lambda: fixed_now,
    )

    assert summary["source"] == "cloud_router_performance_snapshot_worker"
    assert summary["window"]["start_gmt"] == "2026-03-24 08:00:00"
    assert summary["window"]["end_gmt"] == "2026-03-24 09:00:00"
    assert summary["sites_total"] == 1
    assert summary["stored_batches_total"] == 1
    assert summary["delivery_owner"] == "wordpress_fetch_apply"
    assert summary["rollup_scope_kind"] == ROUTER_PERFORMANCE_BATCH_SCOPE
    assert summary["callback_attempted_total"] == 0
    assert summary["callback_delivered_total"] == 0
    assert summary["callback_skipped_total"] == 1
    assert len(summary["site_batches"]) == 1
    batch = summary["site_batches"][0]
    assert batch["site_id"] == "site_alpha"
    assert batch["rows_total"] >= 1
    assert batch["request_total"] >= 1
    assert batch["guard_fail_total"] >= 1
    assert batch["scope_id"] == "2026-03-24T08:00:00Z__2026-03-24T09:00:00Z"

    with get_session(database_url) as session:
        repository = StatsRepository(session)
        stored_batches = repository.list_usage_rollups(
            site_scope="site_alpha",
            scope_kind=ROUTER_PERFORMANCE_BATCH_SCOPE,
        )

    assert len(stored_batches) == 1
    assert stored_batches[0].payload_json["delivery"]["buffer_kind"] == "usage_rollup"
    assert stored_batches[0].payload_json["window"]["end_gmt"] == "2026-03-24 09:00:00"

    dispose_engine(database_url)


def test_router_performance_snapshot_worker_dispatches_optional_callback_when_configured(
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
            "router_performance_callback_key_id": "kp_alpha",
            "router_performance_callback_secret": "callback-secret-alpha",
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
            idempotency_key="worker-router-performance-b",
            trace_id="worker-router-performance-b",
            input_payload={"messages": [{"role": "user", "content": "worker callback"}]},
            policy={"preset_id": "preset.alpha"},
        )
    )

    fixed_now = datetime(2026, 3, 24, 9, 20, tzinfo=UTC)
    with get_session(database_url) as session:
        run = session.scalar(select(RunRecord).where(RunRecord.run_id == result.run_id))
        assert run is not None
        run.started_at = fixed_now - timedelta(minutes=20)
        run.finished_at = fixed_now - timedelta(minutes=20) + timedelta(milliseconds=180)
        run.policy_json = {"preset_id": "preset.alpha"}
        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord)
                .where(ProviderCallRecord.run_id == result.run_id)
                .order_by(ProviderCallRecord.id.asc())
            )
        )
        for index, provider_call in enumerate(provider_calls):
            provider_call.created_at = run.started_at + timedelta(seconds=index + 1)
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
            router_performance_worker_window_hours=1,
            router_performance_worker_site_limit=10,
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
        == "https://wp.example.test/wp-json/npcink/open/v1/router/performance-snapshot/callback"
    )
    assert delivered["headers"]["x-npcink-cloud-event"] == "router.performance_snapshot.batch"
    assert delivered["headers"]["x-npcink-key-id"] == "kp_alpha"
    assert delivered["body"]["window"]["end_gmt"] == "2026-03-24 09:00:00"
    assert delivered["body"]["delivery"]["buffer_kind"] == "usage_rollup"
    assert summary["site_batches"][0]["callback"]["status"] == "delivered"

    dispose_engine(database_url)


def test_router_performance_snapshot_callback_rejects_private_target_before_dispatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected callback dispatch to {request.url}")

    with pytest.raises(RuntimeCallbackTargetValidationError):
        _dispatch_callback(
            callback_url="https://127.0.0.1/wp-json/npcink/open/v1/router/performance-snapshot/callback",
            site_id="site_alpha",
            key_id="kp_alpha",
            secret="callback-secret-alpha",
            callback_id="batch_alpha",
            payload={"status": "test"},
            timeout_seconds=10.0,
            transport=httpx.MockTransport(handler),
        )


def test_router_performance_snapshot_callback_bounds_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _resolve_example_test_to_public_ip(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(500, text="x" * 5000)

    delivery = _dispatch_callback(
        callback_url="https://wp.example.test/wp-json/npcink/open/v1/router/performance-snapshot/callback",
        site_id="site_alpha",
        key_id="kp_alpha",
        secret="callback-secret-alpha",
        callback_id="batch_alpha",
        payload={"status": "test"},
        timeout_seconds=10.0,
        transport=httpx.MockTransport(handler),
    )

    assert delivery["delivered"] is False
    assert len(str(delivery["response_body"])) < 4100
    assert str(delivery["response_body"]).endswith("...[truncated]")
