from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import get_session, init_schema
from app.core.models import UsageMeterEvent
from app.core.services import CloudServices
from app.domain.agent_feedback import service as agent_feedback_service_module
from app.domain.agent_feedback.contracts import find_forbidden_agent_feedback_field
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
    build_auth_headers,
    build_internal_headers,
    merge_json_headers,
    seed_site_auth,
)

AGENT_FEEDBACK_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "agent_feedback"


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'agent-feedback.sqlite3'}"


def _build_client(tmp_path: Path) -> tuple[str, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "stats:read"],
    )
    settings = Settings(
        _env_file=None,
        project_name="Magick AI Cloud Agent Feedback Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
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


def _load_content_support_regression_fixture() -> dict[str, object]:
    fixture_path = AGENT_FEEDBACK_FIXTURE_DIR / "content_support_regression_samples.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def _assert_regression_sample_is_metadata_only(sample: dict[str, object]) -> None:
    forbidden_path = find_forbidden_agent_feedback_field(sample)
    assert forbidden_path == ""
    assert "operator_note" not in sample or str(sample.get("operator_note") or "") == ""
    serialized = json.dumps(sample, sort_keys=True)
    for forbidden_fragment in (
        "post_content",
        "prompt_text",
        "provider_response",
        "api_key",
        "secret",
        "confirm_token",
        "write_confirmed",
    ):
        assert forbidden_fragment not in serialized


def _post_feedback(
    client: TestClient,
    payload: dict[str, object],
    *,
    idempotency_key: str = "agent-feedback-001",
    nonce: str | None = None,
    site_id: str = "site_alpha",
    key_id: str = "key_default",
) -> object:
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/agent-feedback/events",
            site_id=site_id,
            key_id=key_id,
            idempotency_key=idempotency_key,
            nonce=nonce or f"nonce-{idempotency_key}",
            trace_id="agentfeedback000000000000000000",
            body=body,
        )
    )
    return client.post("/v1/agent-feedback/events", content=body, headers=headers)


def _get_feedback_summary(client: TestClient, *, window_hours: int = 24) -> object:
    path = f"/v1/agent-feedback/summary?window_hours={window_hours}"
    headers = build_auth_headers(
        "GET",
        path,
        site_id="site_alpha",
        key_id="key_default",
        trace_id="agentfeedbacksummary000000000",
    )
    return client.get(path, headers=headers)


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


def test_agent_feedback_accepts_image_quality_labels(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    response = _post_feedback(
        client,
        _feedback_payload(
            agent_id="image_source_candidate_agent",
            source_runtime="image_candidates",
            handoff_type="image_candidate_result",
            local_surface="toolbox_image_candidates",
            local_outcome="rejected",
            feedback_labels=[
                "visual_quality_low",
                "source_or_license_risk",
                "operator_confidence_low",
            ],
            evidence_ref_ids=["image:ai_generated:cloud:candidate-1"],
        ),
        idempotency_key="agent-feedback-image-labels",
    )

    assert response.status_code == 200
    with get_session(database_url) as session:
        events = list(session.scalars(select(UsageMeterEvent)))

    assert len(events) == 1
    event = events[0]
    assert event.payload_json is not None
    assert event.payload_json["local_surface"] == "toolbox_image_candidates"
    assert event.payload_json["feedback_labels"] == [
        "visual_quality_low",
        "source_or_license_risk",
        "operator_confidence_low",
    ]


def test_agent_feedback_accepts_editor_content_support_feedback(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    response = _post_feedback(
        client,
        _feedback_payload(
            agent_id="editor_content_support_agent",
            agent_version="editor_content_support_flow",
            source_runtime="content_support",
            source_run_id="local-browser-acceptance-202606130438",
            handoff_id="content_support:title_suggestions:editor_content_support_flow",
            handoff_type="editor_content_support_result",
            local_surface="editor_content_support_sidebar",
            local_outcome="accepted",
            feedback_labels=["evidence_useful", "operator_confidence_high"],
            operator_note="",
            local_proposal_id="",
            evidence_ref_ids=[
                "content_support_section:title_suggestions",
                "artifact:editor_content_support_flow",
            ],
            redaction_status="metadata_only",
            retention_class="quality_eval",
        ),
        idempotency_key="agent-feedback-editor-content-support",
    )
    summary_response = _get_feedback_summary(client, window_hours=24)

    assert response.status_code == 200
    receipt = response.json()["data"]
    assert receipt["accepted_for_eval"] is True
    assert receipt["quality_rollup_candidate"] is True
    assert receipt["production_mutation"] is False
    assert receipt["approval_truth"] == "wordpress_local"
    assert receipt["preflight_truth"] == "wordpress_local"
    assert receipt["final_write_truth"] == "wordpress_local"
    assert receipt["source_runtime"] == "content_support"

    with get_session(database_url) as session:
        events = list(session.scalars(select(UsageMeterEvent)))

    assert len(events) == 1
    event = events[0]
    assert event.meter_key == "agent_feedback.content_support"
    assert event.ability_family == "agent"
    assert event.channel == "editor_content_support_sidebar"
    assert event.payload_json is not None
    assert event.payload_json["local_surface"] == "editor_content_support_sidebar"
    assert event.payload_json["source_runtime"] == "content_support"
    assert event.payload_json["operator_note"] == ""
    assert event.payload_json["redaction_status"] == "metadata_only"
    assert event.payload_json["evidence_ref_ids"] == [
        "content_support_section:title_suggestions",
        "artifact:editor_content_support_flow",
    ]
    assert event.payload_json["cloud_feedback_policy"]["production_mutation"] is False

    assert summary_response.status_code == 200
    summary = summary_response.json()["data"]
    assert summary["events_total"] == 1
    assert summary["source_runtimes"] == {"content_support": 1}
    assert summary["local_surfaces"] == {"editor_content_support_sidebar": 1}
    assert summary["outcomes"] == {"accepted": 1}
    assert summary["labels"] == {
        "evidence_useful": 1,
        "operator_confidence_high": 1,
    }
    assert summary["scenarios"] == [
        {
            "local_surface": "editor_content_support_sidebar",
            "source_runtime": "content_support",
            "events_total": 1,
            "outcomes": {"accepted": 1},
            "labels": {
                "evidence_useful": 1,
                "operator_confidence_high": 1,
            },
            "accepted_rate": 1.0,
            "evidence_weak_rate": 0.0,
            "wrong_next_step_rate": 0.0,
        }
    ]
    assert summary["production_mutation"] is False
    assert summary["approval_truth"] == "wordpress_local"
    assert summary["preflight_truth"] == "wordpress_local"
    assert summary["final_write_truth"] == "wordpress_local"


def test_agent_feedback_accepts_nightly_inspection_feedback_summary(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)

    accepted = _post_feedback(
        client,
        _feedback_payload(
            agent_id="nightly_site_inspection_cloud_runtime",
            agent_version="nightly_inspection_cloud_runtime.v1",
            source_runtime="nightly_site_inspection",
            source_run_id="run_nightly_123",
            handoff_id="action_001",
            handoff_type="morning_brief_priority",
            local_surface="toolbox_nightly_inspection_morning_brief",
            local_outcome="accepted",
            feedback_labels=["evidence_useful", "operator_confidence_high"],
            operator_note="",
            local_proposal_id="",
            evidence_ref_ids=["action_001", "post:123"],
            source_action_id="action_001",
            source_object_type="post",
            source_object_id="123",
            source_reason_codes=["missing_meta_description", "stale_content"],
            source_score=67,
            source_severity="warning",
            retention_class="quality_eval",
        ),
        idempotency_key="agent-feedback-nightly-accepted",
    )
    rejected = _post_feedback(
        client,
        _feedback_payload(
            agent_id="nightly_site_inspection_cloud_runtime",
            agent_version="nightly_inspection_cloud_runtime.v1",
            source_runtime="nightly_site_inspection",
            source_run_id="run_nightly_123",
            handoff_id="action_002",
            handoff_type="morning_brief_priority",
            local_surface="toolbox_nightly_inspection_morning_brief",
            local_outcome="rejected",
            feedback_labels=["wrong_priority", "already_handled", "operator_confidence_low"],
            operator_note="",
            local_proposal_id="",
            evidence_ref_ids=["action_002", "post:456"],
            source_action_id="action_002",
            source_object_type="post",
            source_object_id="456",
            source_reason_codes=["missing_internal_links"],
            source_score=78,
            source_severity="warning",
            retention_class="quality_eval",
        ),
        idempotency_key="agent-feedback-nightly-rejected",
    )
    wrong_next_step = _post_feedback(
        client,
        _feedback_payload(
            agent_id="nightly_site_inspection_cloud_runtime",
            agent_version="nightly_inspection_cloud_runtime.v1",
            source_runtime="nightly_site_inspection",
            source_run_id="run_nightly_456",
            handoff_id="action_003",
            handoff_type="morning_brief_priority",
            local_surface="toolbox_nightly_inspection_morning_brief",
            local_outcome="rejected",
            feedback_labels=["wrong_next_step", "not_relevant_to_site"],
            operator_note="",
            local_proposal_id="",
            evidence_ref_ids=["action_003", "post:789"],
            source_action_id="action_003",
            source_object_type="post",
            source_object_id="789",
            source_reason_codes=["thin_content", "stale_content"],
            source_score=45,
            source_severity="critical",
            retention_class="quality_eval",
        ),
        idempotency_key="agent-feedback-nightly-wrong-next-step",
    )
    duplicate = _post_feedback(
        client,
        _feedback_payload(
            agent_id="nightly_site_inspection_cloud_runtime",
            agent_version="nightly_inspection_cloud_runtime.v1",
            source_runtime="nightly_site_inspection",
            source_run_id="run_nightly_789",
            handoff_id="action_004",
            handoff_type="morning_brief_priority",
            local_surface="toolbox_nightly_inspection_morning_brief",
            local_outcome="rejected",
            feedback_labels=["duplicate_suggestion"],
            operator_note="",
            local_proposal_id="",
            evidence_ref_ids=["action_004", "post:790"],
            source_action_id="action_004",
            source_object_type="post",
            source_object_id="790",
            source_reason_codes=["stale_content"],
            source_score=45,
            source_severity="critical",
            retention_class="quality_eval",
        ),
        idempotency_key="agent-feedback-nightly-duplicate",
    )

    assert accepted.status_code == 200
    assert rejected.status_code == 200
    assert wrong_next_step.status_code == 200
    assert duplicate.status_code == 200

    summary_response = _get_feedback_summary(client, window_hours=24)

    assert summary_response.status_code == 200
    nightly = summary_response.json()["data"]["nightly_inspection"]
    assert nightly["events_total"] == 4
    assert nightly["action_feedback_total"] == 4
    assert nightly["outcomes"]["accepted"] == 1
    assert nightly["outcomes"]["rejected"] == 3
    assert nightly["labels"]["wrong_priority"] == 1
    assert nightly["labels"]["already_handled"] == 1
    assert nightly["labels"]["wrong_next_step"] == 1
    assert nightly["labels"]["not_relevant_to_site"] == 1
    assert nightly["labels"]["duplicate_suggestion"] == 1
    assert nightly["rejected_labels"] == [
        {"label": "already_handled", "count": 1},
        {"label": "duplicate_suggestion", "count": 1},
        {"label": "not_relevant_to_site", "count": 1},
        {"label": "operator_confidence_low", "count": 1},
        {"label": "wrong_next_step", "count": 1},
        {"label": "wrong_priority", "count": 1},
    ]
    assert nightly["reason_codes"]["missing_meta_description"] == 1
    assert nightly["reason_codes"]["missing_internal_links"] == 1
    assert nightly["reason_codes"]["stale_content"] == 3
    assert nightly["rejected_reason_codes"] == [
        {"label": "stale_content", "count": 2},
        {"label": "missing_internal_links", "count": 1},
        {"label": "thin_content", "count": 1},
    ]
    assert nightly["average_source_score"] == 58.75
    assert nightly["rates"]["accepted_rate"] == 0.25
    assert nightly["rates"]["rejected_rate"] == 0.75
    assert nightly["rates"]["wrong_priority_rate"] == 0.25
    assert nightly["rates"]["wrong_next_step_rate"] == 0.25
    assert nightly["rates"]["already_handled_rate"] == 0.25
    assert nightly["rates"]["not_relevant_to_site_rate"] == 0.25
    assert nightly["rates"]["duplicate_suggestion_rate"] == 0.25
    assert nightly["production_mutation"] is False

    with get_session(database_url) as session:
        events = list(session.scalars(select(UsageMeterEvent)))

    assert len(events) == 4
    assert events[0].payload_json["source_action_id"] in {
        "action_001",
        "action_002",
        "action_003",
        "action_004",
    }


def test_content_support_feedback_regression_samples_roll_up_expected_quality(
    tmp_path: Path,
) -> None:
    _database_url, client = _build_client(tmp_path)
    fixture = _load_content_support_regression_fixture()
    samples = fixture["samples"]
    expected = fixture["expected_summary"]

    assert fixture["contract_version"] == "cloud_agent_feedback_regression_samples.v1"
    assert isinstance(samples, list)
    assert isinstance(expected, dict)

    for sample in samples:
        assert isinstance(sample, dict)
        _assert_regression_sample_is_metadata_only(sample)
        sample_id = str(sample["sample_id"])
        response = _post_feedback(
            client,
            _feedback_payload(
                agent_id="editor_content_support_agent",
                agent_version="editor_content_support_flow",
                source_runtime=sample["source_runtime"],
                source_run_id=sample["source_run_id"],
                handoff_id=sample["handoff_id"],
                handoff_type=sample["handoff_type"],
                local_surface=sample["local_surface"],
                local_outcome=sample["local_outcome"],
                feedback_labels=sample["feedback_labels"],
                operator_note="",
                local_proposal_id="",
                evidence_ref_ids=sample["evidence_ref_ids"],
                redaction_status="metadata_only",
                retention_class="quality_eval",
            ),
            idempotency_key=f"agent-feedback-regression-{sample_id}",
        )
        assert response.status_code == 200
        receipt = response.json()["data"]
        assert receipt["accepted_for_eval"] is True
        assert receipt["production_mutation"] is False
        assert receipt["approval_truth"] == "wordpress_local"

    summary_response = _get_feedback_summary(client, window_hours=24)
    admin_response = client.get(
        "/internal/service/admin/agent-feedback?window_hours=24",
        headers=build_internal_headers(),
    )

    assert summary_response.status_code == 200
    assert admin_response.status_code == 200
    summary = summary_response.json()["data"]
    admin_summary = admin_response.json()["data"]
    assert summary["events_total"] == expected["events_total"]
    assert summary["source_runtimes"] == {"content_support": expected["events_total"]}
    assert summary["local_surfaces"] == {
        "editor_content_support_sidebar": expected["events_total"]
    }
    assert summary["outcomes"] == expected["outcomes"]
    assert summary["labels"] == expected["labels"]
    assert summary["rates"]["accepted_rate"] == expected["accepted_rate"]
    assert summary["rates"]["evidence_useful_rate"] == expected["evidence_useful_rate"]
    assert summary["rates"]["evidence_weak_rate"] == expected["evidence_weak_rate"]
    assert summary["rates"]["wrong_next_step_rate"] == expected["wrong_next_step_rate"]
    assert summary["scenarios"] == [
        {
            "local_surface": "editor_content_support_sidebar",
            "source_runtime": "content_support",
            "events_total": expected["events_total"],
            "outcomes": expected["outcomes"],
            "labels": expected["labels"],
            "accepted_rate": expected["accepted_rate"],
            "evidence_weak_rate": expected["evidence_weak_rate"],
            "wrong_next_step_rate": expected["wrong_next_step_rate"],
        }
    ]
    assert summary["production_mutation"] is False
    assert summary["approval_truth"] == "wordpress_local"
    assert admin_summary["read_only"] is True
    assert admin_summary["boundary"]["control_plane"] == "wordpress_local"
    assert admin_summary["events_total"] == expected["events_total"]


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


def test_agent_feedback_summary_rolls_up_outcomes_and_labels(tmp_path: Path) -> None:
    _database_url, client = _build_client(tmp_path)

    accepted = _post_feedback(
        client,
        _feedback_payload(
            local_outcome="accepted",
            feedback_labels=["evidence_useful", "operator_confidence_high"],
        ),
        idempotency_key="agent-feedback-summary-accepted",
    )
    rejected = _post_feedback(
        client,
        _feedback_payload(
            local_outcome="rejected",
            feedback_labels=["evidence_weak", "wrong_next_step", "operator_confidence_low"],
        ),
        idempotency_key="agent-feedback-summary-rejected",
    )
    response = _get_feedback_summary(client, window_hours=24)

    assert accepted.status_code == 200
    assert rejected.status_code == 200
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["artifact_type"] == "cloud_agent_feedback_summary"
    assert data["contract_version"] == "cloud_agent_feedback.v1"
    assert data["events_total"] == 2
    assert data["outcomes"] == {"rejected": 1, "accepted": 1}
    assert data["labels"]["evidence_useful"] == 1
    assert data["labels"]["evidence_weak"] == 1
    assert data["labels"]["wrong_next_step"] == 1
    assert data["rates"]["accepted_rate"] == 0.5
    assert data["rates"]["evidence_useful_rate"] == 0.5
    assert data["rates"]["evidence_weak_rate"] == 0.5
    assert data["rates"]["wrong_next_step_rate"] == 0.5
    assert data["low_quality_labels"] == [
        {"label": "evidence_weak", "count": 1},
        {"label": "operator_confidence_low", "count": 1},
        {"label": "wrong_next_step", "count": 1},
    ]
    assert data["rejection_reasons"] == [
        {"label": "evidence_weak", "count": 1},
        {"label": "operator_confidence_low", "count": 1},
        {"label": "wrong_next_step", "count": 1},
    ]
    assert data["scenarios"][0]["local_surface"] == "toolbox_site_knowledge"
    assert data["scenarios"][0]["events_total"] == 2
    assert data["scenarios"][0]["accepted_rate"] == 0.5
    assert len(data["quality_trend"]) == 1
    assert data["quality_trend"][0]["events_total"] == 2
    assert data["quality_trend"][0]["accepted"] == 1
    assert data["quality_trend"][0]["rejected"] == 1
    assert data["production_mutation"] is False
    assert data["approval_truth"] == "wordpress_local"


def test_admin_agent_feedback_summary_is_cross_site_read_only(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_beta",
        key_id="key_beta",
        scopes=["runtime:execute", "runtime:read", "stats:read"],
    )

    alpha = _post_feedback(
        client,
        _feedback_payload(
            source_runtime="content_support",
            local_surface="editor_content_support_sidebar",
            local_outcome="accepted",
            feedback_labels=["evidence_useful", "operator_confidence_high"],
            operator_note="",
            redaction_status="metadata_only",
        ),
        idempotency_key="agent-feedback-admin-alpha",
    )
    beta = _post_feedback(
        client,
        _feedback_payload(
            source_runtime="site_knowledge",
            local_surface="toolbox_site_knowledge",
            local_outcome="rejected",
            feedback_labels=["evidence_weak", "wrong_intent", "operator_confidence_low"],
            operator_note="",
            redaction_status="metadata_only",
        ),
        idempotency_key="agent-feedback-admin-beta",
        site_id="site_beta",
        key_id="key_beta",
    )

    response = client.get(
        "/internal/service/admin/agent-feedback?window_hours=24",
        headers=build_internal_headers(),
    )
    unauthenticated = client.get("/internal/service/admin/agent-feedback?window_hours=24")

    assert alpha.status_code == 200
    assert beta.status_code == 200
    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["artifact_type"] == "cloud_agent_feedback_summary"
    assert data["scope"] == "all_sites"
    assert data["read_only"] is True
    assert data["surface"] == "internal_admin_quality_feedback"
    assert data["events_total"] == 2
    assert data["source_runtimes"] == {
        "site_knowledge": 1,
        "content_support": 1,
    }
    assert data["local_surfaces"] == {
        "toolbox_site_knowledge": 1,
        "editor_content_support_sidebar": 1,
    }
    assert data["rates"]["accepted_rate"] == 0.5
    assert data["labels"]["wrong_intent"] == 1
    assert data["labels"]["evidence_weak"] == 1
    assert data["production_mutation"] is False
    assert data["approval_truth"] == "wordpress_local"
    assert data["preflight_truth"] == "wordpress_local"
    assert data["final_write_truth"] == "wordpress_local"
    assert data["boundary"] == {
        "production_mutation": False,
        "approval_truth": "wordpress_local",
        "preflight_truth": "wordpress_local",
        "final_write_truth": "wordpress_local",
        "control_plane": "wordpress_local",
    }

    site_filtered = client.get(
        "/internal/service/admin/agent-feedback?window_hours=24&site_id=site_alpha",
        headers=build_internal_headers(),
    )
    assert site_filtered.status_code == 200
    site_data = site_filtered.json()["data"]
    assert site_data["scope"] == "site"
    assert site_data["site_id"] == "site_alpha"
    assert site_data["events_total"] == 1
    assert site_data["source_runtimes"] == {"content_support": 1}


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


def test_agent_feedback_rejects_mixed_case_write_authority_fields(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    response = _post_feedback(
        client,
        _feedback_payload(Direct_WordPress_Write=True),
        idempotency_key="agent-feedback-mixed-case-write-field",
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


def test_agent_feedback_summary_reports_limited_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _database_url, client = _build_client(tmp_path)
    monkeypatch.setattr(agent_feedback_service_module, "AGENT_FEEDBACK_SUMMARY_MAX_EVENTS", 1)
    first = _post_feedback(
        client,
        _feedback_payload(local_outcome="accepted"),
        idempotency_key="agent-feedback-limited-a",
    )
    second = _post_feedback(
        client,
        _feedback_payload(local_outcome="rejected"),
        idempotency_key="agent-feedback-limited-b",
    )

    response = _get_feedback_summary(client, window_hours=24)

    assert first.status_code == 200
    assert second.status_code == 200
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["events_total"] == 1
    assert data["limited"] is True
    assert data["max_events"] == 1
