from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import get_session, init_schema
from app.core.models import UsageMeterEvent
from app.core.services import CloudServices
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_PORTAL_JWT_SECRET,
    build_auth_headers,
    merge_json_headers,
    seed_site_auth,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'agent-feedback.sqlite3'}"


def _build_client(tmp_path: Path) -> tuple[str, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read"],
    )
    settings = Settings(
        _env_file=None,
        project_name="Magick AI Cloud Agent Feedback Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
    )
    return database_url, TestClient(create_app(CloudServices(settings=settings)))


def _feedback_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_version": "cloud_agent_feedback.v1",
        "agent_id": "site_knowledge_suggestion_agent",
        "agent_version": "2026-06-07",
        "source_runtime": "site_knowledge",
        "source_run_id": "run_site_knowledge_123",
        "handoff_id": "handoff_site_knowledge_123",
        "handoff_type": "proposal_input",
        "local_surface": "toolbox_site_knowledge",
        "local_outcome": "edited_before_accept",
        "feedback_labels": ["evidence_useful", "missing_context"],
        "operator_note": "Evidence was useful, but the draft needed a narrower title.",
        "local_proposal_id": "proposal_123",
        "evidence_ref_ids": ["post:123"],
        "created_at": datetime.now(UTC).isoformat(),
    }
    payload.update(overrides)
    return payload


def _post_feedback(
    client: TestClient,
    payload: dict[str, object],
    *,
    idempotency_key: str = "agent-feedback-001",
    nonce: str | None = None,
) -> object:
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/agent-feedback/events",
            site_id="site_alpha",
            key_id="key_default",
            idempotency_key=idempotency_key,
            nonce=nonce or f"nonce-{idempotency_key}",
            trace_id="agentfeedback000000000000000000",
            body=body,
        )
    )
    return client.post("/v1/agent-feedback/events", content=body, headers=headers)


def test_agent_feedback_event_is_accepted_for_eval(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    response = _post_feedback(client, _feedback_payload())

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["artifact_type"] == "cloud_agent_feedback_receipt"
    assert data["accepted_for_eval"] is True
    assert data["quality_rollup_candidate"] is True
    assert data["production_mutation"] is False
    assert data["approval_truth"] == "wordpress_local"
    assert data["preflight_truth"] == "wordpress_local"
    assert data["final_write_truth"] == "wordpress_local"

    with get_session(database_url) as session:
        events = list(session.scalars(select(UsageMeterEvent)))

    assert len(events) == 1
    event = events[0]
    assert event.event_kind == "agent.feedback"
    assert event.meter_key == "agent_feedback.site_knowledge"
    assert event.execution_kind == "agent_feedback"
    assert event.quantity == 1.0
    assert event.payload_json is not None
    assert event.payload_json["local_outcome"] == "edited_before_accept"
    assert event.payload_json["feedback_labels"] == ["evidence_useful", "missing_context"]
    assert event.payload_json["cloud_feedback_policy"]["production_mutation"] is False
    assert event.payload_json["cloud_feedback_policy"]["approval_truth"] == "wordpress_local"


def test_agent_feedback_idempotency_dedupes_meter_event(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    payload = _feedback_payload()

    first = _post_feedback(
        client,
        payload,
        idempotency_key="agent-feedback-repeat",
        nonce="nonce-agent-feedback-repeat-a",
    )
    second = _post_feedback(
        client,
        payload,
        idempotency_key="agent-feedback-repeat",
        nonce="nonce-agent-feedback-repeat-b",
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["feedback_event_id"] == second.json()["data"]["feedback_event_id"]
    with get_session(database_url) as session:
        assert len(list(session.scalars(select(UsageMeterEvent)))) == 1


def test_agent_feedback_rejects_write_authority_fields(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    response = _post_feedback(
        client,
        _feedback_payload(direct_wordpress_write=True),
        idempotency_key="agent-feedback-write-field",
    )

    assert response.status_code == 422
    assert "write authority" in response.text
    with get_session(database_url) as session:
        assert len(list(session.scalars(select(UsageMeterEvent)))) == 0


def test_agent_feedback_rejects_unknown_label(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    response = _post_feedback(
        client,
        _feedback_payload(feedback_labels=["evidence_useful", "auto_publish_it"]),
        idempotency_key="agent-feedback-bad-label",
    )

    assert response.status_code == 422
    assert "feedback label is not supported" in response.text
    with get_session(database_url) as session:
        assert len(list(session.scalars(select(UsageMeterEvent)))) == 0
