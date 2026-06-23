from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import get_session, init_schema
from app.core.models import RunRecord, UsageMeterEvent
from app.core.services import CloudServices
from app.domain.site_ops_analysis.service import SiteOpsAnalysisExecutionResult
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
    build_auth_headers,
    merge_json_headers,
    seed_site_auth,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'site-ops-analysis.sqlite3'}"


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
        project_name="Magick AI Cloud Site Ops Analysis Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
    )
    client = TestClient(create_app(CloudServices(settings=settings, providers={})))
    return database_url, client


def _site_ops_request(input_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    input_payload: dict[str, Any] = {
        "artifact_type": "site_ops_cloud_analysis_request",
        "contract_version": "site_ops_cloud_analysis_request.v1",
        "request_id": "site-ops-fixture-cloud-analysis",
        "site_id": "example-site",
        "generated_at": "2026-06-22T00:00:00Z",
        "source_pack_contract": "site_ops_insight_pack.v1",
        "expected_result_contract": "site_ops_cloud_analysis_result.v1",
        "cloud_role": "runtime_detail",
        "execution_pattern": "whole_run_offload",
        "data_classification": "public_site_aggregate",
        "storage_mode": "cloud_runtime_policy",
        "write_posture": "suggestion_only",
        "direct_wordpress_write": False,
        "core_proposal_created": False,
        "local_runtime_created": False,
        "local_scheduler_created": False,
        "input": {
            "sample_summaries": {
                "posts": {
                    "sampled_count": 12,
                    "stale_180d_count": 4,
                    "short_content_count": 2,
                    "no_internal_link_count": 5,
                    "commented_item_count": 3,
                    "missing_alt_ref_count": 2,
                },
                "media": {
                    "sampled_count": 8,
                    "missing_alt_count": 6,
                    "missing_caption_count": 3,
                    "referenced_alt_gap_count": 2,
                },
                "comments": {
                    "approved_total": 20,
                    "pending_total": 2,
                    "recent_sample_count": 10,
                    "question_like_count": 4,
                    "long_comment_count": 2,
                    "active_post_count": 6,
                    "privacy": {
                        "comment_text_returned": False,
                        "author_email_returned": False,
                        "ip_address_returned": False,
                        "user_agent_returned": False,
                    },
                },
                "taxonomies": {
                    "category": {"total": 5, "empty_count": 1, "low_count": 1},
                    "post_tag": {"total": 8, "empty_count": 2, "low_count": 3},
                },
            },
            "local_findings": [
                {
                    "id": "media_metadata_debt",
                    "issue_type": "media",
                    "severity": "high",
                    "priority_score": 82,
                    "evidence_summary": "6 sampled attachments lack ALT text.",
                    "recommended_action": "Start with media ALT/caption review.",
                    "write_boundary": "core_handoff_candidate",
                    "source_refs": [
                        {"object_type": "attachment", "object_id": 301, "title": "Diagram"}
                    ],
                },
                {
                    "id": "comment_signal_review",
                    "issue_type": "comments",
                    "severity": "medium",
                    "priority_score": 70,
                    "evidence_summary": "Question-like approved comments are visible.",
                    "recommended_action": "Review repeated public comment needs.",
                    "write_boundary": "manual_review_only",
                    "source_refs": [],
                },
            ],
            "blocked_items": [],
            "analysis_tasks": [
                "prioritize_operator_review_queue",
                "prepare_core_handoff_candidates_without_creating_proposals",
            ],
            "operator_context": {
                "content_context_ready": True,
                "cloud_ready": True,
            },
        },
        "safety": {
            "cloud_request_prepared": True,
            "cloud_called": False,
            "cloud_is_runtime_detail_only": True,
            "direct_wordpress_write": False,
            "automatic_core_proposal": False,
            "comment_text_returned": False,
            "comment_author_email_returned": False,
            "comment_ip_returned": False,
            "comment_user_agent_returned": False,
        },
    }
    input_payload.update(input_overrides or {})
    return {
        "ability_name": "magick-ai-toolbox/analyze-site-ops",
        "contract_version": "site_ops_cloud_analysis_request.v1",
        "execution_pattern": "whole_run_offload",
        "data_classification": "public_site_aggregate",
        "storage_mode": "result_only",
        "timeout_seconds": 20,
        "retry_max": 0,
        "retention_ttl": 3600,
        "input": input_payload,
        "policy": {"allow_fallback": False},
    }


def _execute(
    client: TestClient,
    payload: dict[str, Any],
    *,
    idempotency_key: str = "site-ops-analysis-idem",
    nonce: str | None = None,
) -> Any:
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            key_id="key_default",
            idempotency_key=idempotency_key,
            nonce=nonce or f"nonce-{idempotency_key}",
            trace_id="siteopsanalysis000000000000000",
            body=body,
        )
    )
    return client.post("/v1/runtime/execute", content=body, headers=headers)


def test_site_ops_analysis_runtime_returns_suggestion_only_detail(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    response = _execute(client, _site_ops_request())

    assert response.status_code == 200, response.json()
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    assert data["provider_id"] == "site_ops_analysis"
    assert data["model_id"] == "deterministic-ops-analyzer-v1"
    assert data["provider_call_count"] == 0
    assert data["profile_id"] == "site-ops-analysis.managed"
    assert data["execution_context"]["ability_family"] == "automation"
    assert data["execution_context"]["execution_pattern"] == "whole_run_offload"
    assert data["execution_context"]["data_classification"] == "public_site_aggregate"

    result = data["result"]
    assert result["contract_version"] == "site_ops_cloud_analysis_result.v1"
    assert result["artifact_type"] == "site_ops_cloud_analysis_result"
    assert result["write_posture"] == "suggestion_only"
    assert result["direct_wordpress_write"] is False
    assert result["core_proposal_created"] is False
    assert result["safety"]["cloud_scheduler_truth"] is False
    assert result["safety"]["comment_text_returned"] is False
    assert result["safety"]["private_comment_author_contact_returned"] is False
    assert result["safety"]["private_comment_network_metadata_returned"] is False
    assert result["priority_queue"][0]["finding_id"] == "media_metadata_debt"
    assert result["priority_queue"][0]["cloud_priority_score"] >= 82
    assert result["executive_summary"]["cloud_role"] == "runtime_detail"
    assert result["executive_summary"]["write_posture"] == "suggestion_only"
    assert result["executive_summary"]["primary_focus"] == "media_metadata_debt"
    assert "media" in result["executive_summary"]["affected_dimensions"]
    assert "review_top_ranked_finding" in result["executive_summary"]["operator_sequence"]
    assert result["dimension_summaries"][0]["dimension"] == "content"
    assert result["dimension_summaries"][1]["dimension"] == "media"
    assert result["dimension_summaries"][1]["priority"] == "high"
    assert result["dimension_summaries"][1]["write_posture"] == "suggestion_only"
    assert result["semantic_ranked_findings"][0]["finding_id"] == "media_metadata_debt"
    assert result["semantic_ranked_findings"][0]["semantic_cluster"] == (
        "media_accessibility_and_reuse"
    )
    assert result["trend_explanations"][0]["operator_impact"]
    assert result["analysis_closure"]["loop_status"] == "ready_for_operator_prioritization"
    assert "semantic_ranking" in result["analysis_closure"]["cloud_only_reasons"]
    assert result["analysis_closure"]["direct_wordpress_write"] is False
    assert result["core_handoff_candidates"][0]["proposal_ready"] is False
    assert result["core_handoff_candidates"][0]["direct_wordpress_write"] is False
    assert any(note["id"] == "comment_question_trend" for note in result["trend_notes"])
    encoded = json.dumps(result)
    assert "comment_content" not in encoded
    assert "comment_author_email" not in encoded
    assert "comment_author_IP" not in encoded
    assert "wp_update_post" not in encoded

    with get_session(database_url) as session:
        run = session.get(RunRecord, data["run_id"])
        assert run is not None
        assert run.execution_kind == "site_ops_cloud_analysis"
        assert run.input_json == {}
        assert run.policy_json["execution_contract"]["cloud_role"] == "runtime_detail"
        assert run.policy_json["execution_contract"]["direct_wordpress_write"] is False
        assert run.policy_json["execution_contract"]["cloud_scheduler_truth"] is False
        meter_events = list(
            session.scalars(
                select(UsageMeterEvent)
                .where(UsageMeterEvent.run_id == run.run_id)
                .order_by(UsageMeterEvent.id.asc())
            )
        )
        assert [event.meter_key for event in meter_events] == ["runs"]


def test_site_ops_analysis_rejects_private_comment_fields(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    request = _site_ops_request()
    request["input"]["input"]["raw_comment"] = {
        "comment_content": "This raw comment text must not leave WordPress."
    }

    response = _execute(
        client,
        request,
        idempotency_key="site-ops-analysis-private-field",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == (
        "site_ops_analysis.private_or_write_field_forbidden"
    )
    with get_session(database_url) as session:
        runs = list(session.scalars(select(RunRecord)))
        meter_events = list(session.scalars(select(UsageMeterEvent)))
        assert runs == []
        assert meter_events == []


def test_site_ops_analysis_runtime_failure_records_failed_detail(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url, client = _build_client(tmp_path)

    class FailingSiteOpsAnalysisService:
        def execute(self, **_: Any) -> SiteOpsAnalysisExecutionResult:
            raise RuntimeError("simulated analyzer failure")

    monkeypatch.setattr(
        "app.domain.runtime.service.SiteOpsAnalysisService",
        FailingSiteOpsAnalysisService,
    )

    response = _execute(
        client,
        _site_ops_request(),
        idempotency_key="site-ops-analysis-runtime-failed",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    data = payload["data"]
    assert data["status"] == "failed"
    assert data["provider_id"] == "site_ops_analysis"
    assert data["model_id"] == "deterministic-ops-analyzer-v1"
    assert data["fallback_used"] is False
    assert data["error_code"] == "site_ops_analysis.execution_failed"
    assert data["error_message"] == "site ops analysis runtime failed"
    assert data["provider_call_count"] == 0

    with get_session(database_url) as session:
        run = session.get(RunRecord, data["run_id"])
        assert run is not None
        assert run.status == "failed"
        assert run.execution_kind == "site_ops_cloud_analysis"
        assert run.error_code == "site_ops_analysis.execution_failed"
        assert run.fallback_used is False
        assert run.policy_json["execution_contract"]["cloud_role"] == "runtime_detail"
        assert run.policy_json["execution_contract"]["direct_wordpress_write"] is False
        assert run.policy_json["execution_contract"]["cloud_scheduler_truth"] is False
        meter_events = list(
            session.scalars(
                select(UsageMeterEvent)
                .where(UsageMeterEvent.run_id == run.run_id)
                .order_by(UsageMeterEvent.id.asc())
            )
        )
        assert [event.meter_key for event in meter_events] == ["runs"]


def test_site_ops_analysis_low_signal_request_degrades_to_reviewable_empty_detail(
    tmp_path: Path,
) -> None:
    _, client = _build_client(tmp_path)
    request = _site_ops_request()
    request["input"]["input"]["local_findings"] = []
    request["input"]["input"]["sample_summaries"] = {
        "posts": {"sampled_count": 0},
        "media": {"sampled_count": 0},
        "comments": {"recent_sample_count": 0},
        "taxonomies": {"category": {}, "post_tag": {}},
    }
    request["input"]["input"]["operator_context"] = {
        "content_context_ready": False,
        "cloud_ready": True,
    }

    response = _execute(
        client,
        request,
        idempotency_key="site-ops-analysis-low-signal",
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    result = data["result"]
    assert result["contract_version"] == "site_ops_cloud_analysis_result.v1"
    assert result["priority_queue"] == []
    assert result["trend_notes"] == []
    assert result["executive_summary"]["primary_focus"] == "collect_stronger_site_context"
    assert result["semantic_ranked_findings"] == []
    assert result["analysis_closure"]["loop_status"] == "blocked_until_operator_review"
    assert result["trend_explanations"] == [
        {
            "id": "insufficient_signal",
            "summary": "No aggregate signal was strong enough for trend explanation.",
            "operator_impact": (
                "Run the local scan after more public content evidence is available."
            ),
            "next_check": "complete_site_context_and_repeat_local_preview",
            "signal_count": 0,
        }
    ]
    assert result["confidence"]["level"] == "low"
    assert result["confidence"]["sample_size"] == 0
    assert result["blocked_items"] == [
        {
            "id": "site_context_brief",
            "reason": "content_context_incomplete",
            "next": "complete_site_context_before_repeating_analysis",
        }
    ]
    assert result["operator_next_actions"][0]["id"] == "clear_blockers"
    assert result["safety"]["direct_wordpress_write"] is False
    assert result["safety"]["cloud_scheduler_truth"] is False
    assert result["safety"]["operator_review_required"] is True


def test_site_ops_analysis_idempotent_replay(tmp_path: Path) -> None:
    _, client = _build_client(tmp_path)
    payload = _site_ops_request()

    first = _execute(
        client,
        payload,
        idempotency_key="site-ops-analysis-replay",
        nonce="nonce-site-ops-analysis-replay-1",
    )
    second = _execute(
        client,
        payload,
        idempotency_key="site-ops-analysis-replay",
        nonce="nonce-site-ops-analysis-replay-2",
    )

    assert first.status_code == 200
    assert second.status_code == 200
    first_data = first.json()["data"]
    second_data = second.json()["data"]
    assert second_data["idempotent_replay"] is True
    assert second_data["run_id"] == first_data["run_id"]
    assert second_data["result"]["contract_version"] == "site_ops_cloud_analysis_result.v1"
