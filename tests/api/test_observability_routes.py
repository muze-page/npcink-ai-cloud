from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import get_session, init_schema
from app.core.models import PluginObservabilityEvent
from app.core.services import CloudServices
from tests.conftest import build_auth_headers, merge_json_headers, seed_site_auth


def _build_client(tmp_path: Path) -> tuple[str, TestClient]:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'observability-api.sqlite3'}"
    init_schema(database_url)
    seed_site_auth(database_url, site_id="site_obs", scopes=["stats:read"])
    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    return database_url, TestClient(create_app(CloudServices(settings=settings)))


def test_plugin_observability_batch_is_signed_and_metadata_only(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "contract_version": "magick-plugin-observability-v1",
        "source": "magick-ai-cloud-addon",
        "events": [
            {
                "schema_version": "2026-06-01",
                "plugin_slug": "magick-ai-core",
                "plugin_version": "0.1.0",
                "source": "local",
                "event_kind": "core.proposal.create",
                "event_id": "evt_core_1",
                "status": "ok",
                "latency_ms": 12,
                "ability_id": "magick-ai/create-draft",
                "proposal_id": "proposal_123",
                "captured_at": "2026-06-01T00:00:00Z",
            },
            {
                "schema_version": "2026-06-01",
                "plugin_slug": "magick-ai-adapter",
                "plugin_version": "0.1.0",
                "source": "local",
                "event_kind": "adapter.core.request",
                "event_id": "evt_adapter_1",
                "status": "error",
                "error_code": "magick_ai_adapter_upstream_failed",
                "method": "POST",
                "route": "/magick-ai-core/v1/proposals",
                "status_code": 500,
                "captured_at": "2026-06-01T00:00:01Z",
            },
        ],
    }
    body = json.dumps(payload, separators=(",", ":")).encode()

    response = client.post(
        "/v1/observability/plugin-events",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/observability/plugin-events",
                site_id="site_obs",
                body=body,
                idempotency_key="obs-batch-1",
                trace_id="traceobsapi0010000000000000000",
            )
        ),
    )

    assert response.status_code == 200
    envelope = response.json()
    assert envelope["status"] == "ok"
    assert envelope["data"]["accepted_count"] == 2
    assert envelope["data"]["stored_count"] == 2

    with get_session(database_url) as session:
        events = list(
            session.scalars(
                select(PluginObservabilityEvent).order_by(PluginObservabilityEvent.id.asc())
            )
        )
        assert len(events) == 2
        assert events[0].site_id == "site_obs"
        assert events[0].plugin_slug == "magick-ai-core"
        assert events[0].event_kind == "core.proposal.create"
        assert events[0].ability_id == "magick-ai/create-draft"
        assert events[0].payload_json == {}
        assert events[1].error_code == "magick_ai_adapter_upstream_failed"
        assert events[1].route == "/magick-ai-core/v1/proposals"


def test_plugin_observability_requires_stats_scope(tmp_path: Path) -> None:
    _, client = _build_client(tmp_path)
    seed_site_auth(
        client.app.state.services.settings.database_url,
        site_id="site_no_scope",
        scopes=["catalog:read"],
    )
    payload = {
        "contract_version": "magick-plugin-observability-v1",
        "events": [
            {
                "plugin_slug": "magick-ai-core",
                "event_kind": "core.proposal.create",
                "event_id": "evt_denied",
            }
        ],
    }
    body = json.dumps(payload, separators=(",", ":")).encode()

    response = client.post(
        "/v1/observability/plugin-events",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/observability/plugin-events",
                site_id="site_no_scope",
                body=body,
                idempotency_key="obs-denied-1",
                trace_id="traceobsapi0020000000000000000",
            )
        ),
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "auth.scope_denied"


def test_plugin_observability_summary_returns_aggregates(tmp_path: Path) -> None:
    _, client = _build_client(tmp_path)
    payload = {
        "contract_version": "magick-plugin-observability-v1",
        "events": [
            {
                "plugin_slug": "magick-ai-core",
                "event_kind": "core.proposal.create",
                "event_id": "evt_summary_core_ok",
                "status": "ok",
                "latency_ms": 10,
            },
            {
                "plugin_slug": "magick-ai-core",
                "event_kind": "core.proposal.create",
                "event_id": "evt_summary_core_error",
                "status": "error",
                "error_code": "core.proposal_invalid",
                "latency_ms": 30,
                "ability_id": "magick-ai/create-draft",
            },
            {
                "plugin_slug": "magick-ai-adapter",
                "event_kind": "adapter.core.request",
                "event_id": "evt_summary_adapter_ok",
                "status": "ok",
                "latency_ms": 20,
                "route": "/magick-ai-core/v1/proposals",
            },
        ],
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    ingest_response = client.post(
        "/v1/observability/plugin-events",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/observability/plugin-events",
                site_id="site_obs",
                body=body,
                idempotency_key="obs-summary-1",
                trace_id="traceobsapi0040000000000000000",
            )
        ),
    )
    assert ingest_response.status_code == 200

    response = client.get(
        "/v1/observability/plugin-summary?window_hours=24",
        headers=build_auth_headers(
            "GET",
            "/v1/observability/plugin-summary",
            site_id="site_obs",
            query="window_hours=24",
            trace_id="traceobsapi0050000000000000000",
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["totals"]["events_total"] == 3
    assert data["totals"]["error_total"] == 1
    assert data["totals"]["success_rate"] == 0.6667
    plugins = {item["plugin_slug"]: item for item in data["plugins"]}
    assert plugins["magick-ai-core"]["events_total"] == 2
    assert plugins["magick-ai-core"]["error_total"] == 1
    assert plugins["magick-ai-core"]["avg_latency_ms"] == 20
    assert data["errors"][0]["error_code"] == "core.proposal_invalid"
    assert data["recent_errors"][0]["ability_id"] == "magick-ai/create-draft"


def test_plugin_observability_event_id_is_deduped_after_replay_window(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = {
        "contract_version": "magick-plugin-observability-v1",
        "events": [
            {
                "plugin_slug": "magick-ai-abilities",
                "event_kind": "abilities.callback.completed",
                "event_id": "evt_same",
                "status": "ok",
            }
        ],
    }

    for index in range(2):
        body = json.dumps(payload, separators=(",", ":")).encode()
        response = client.post(
            "/v1/observability/plugin-events",
            content=body,
            headers=merge_json_headers(
                build_auth_headers(
                    "POST",
                    "/v1/observability/plugin-events",
                    site_id="site_obs",
                    body=body,
                    idempotency_key=f"obs-dedupe-{index}",
                    trace_id=f"traceobsapi003{index}0000000000000000",
                )
            ),
        )
        assert response.status_code == 200

    with get_session(database_url) as session:
        count = session.scalar(select(func.count()).select_from(PluginObservabilityEvent))
        assert count == 1
