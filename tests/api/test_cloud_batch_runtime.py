from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.queue.in_memory import InMemoryRuntimeQueue
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import get_session, init_schema
from app.core.models import (
    AccountSubscription,
    PlanVersion,
    ProviderCallRecord,
    RunRecord,
    UsageMeterEvent,
)
from app.core.services import CloudServices
from app.domain.runtime.service import RuntimeService
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_PORTAL_JWT_SECRET,
    build_auth_headers,
    merge_json_headers,
    seed_site_auth,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'cloud-batch-runtime.sqlite3'}"


def _build_client(tmp_path: Path) -> tuple[str, Settings, InMemoryRuntimeQueue, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read"],
    )
    settings = Settings(
        _env_file=None,
        project_name="Magick AI Cloud Batch Runtime Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        deployment_region="test-region",
    )
    runtime_queue = InMemoryRuntimeQueue()
    client = TestClient(
        create_app(
            CloudServices(
                settings=settings,
                providers={},
                runtime_queue=runtime_queue,
            )
        )
    )
    return database_url, settings, runtime_queue, client


def _payload(input_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    input_payload: dict[str, Any] = {
        "contract_version": "cloud_batch_runtime_request.v1",
        "task_profile": "nightly_site_inspection_morning_brief",
        "items": [
            {
                "object_type": "post",
                "object_id": 123,
                "title": "Short title",
                "meta_description": "",
                "word_count": 420,
                "internal_link_count": 0,
                "image_alt_missing": 2,
                "days_since_modified": 430,
            },
            {
                "object_type": "page",
                "object_id": 456,
                "title": "Complete evergreen service page with useful context",
                "meta_description": (
                    "A complete service page summary with enough detail for local "
                    "operator review and clear search-snippet context."
                ),
                "word_count": 900,
                "internal_link_count": 3,
                "image_alt_missing": 0,
                "days_since_modified": 20,
            },
        ],
        "direct_wordpress_write": False,
    }
    input_payload.update(input_overrides or {})
    return {
        "ability_name": "magick-ai-toolbox/analyze-nightly-content-batch",
        "contract_version": "cloud_batch_runtime_request.v1",
        "execution_pattern": "whole_run_offload",
        "storage_mode": "result_only",
        "retention_ttl": 86400,
        "timeout_seconds": 60,
        "retry_max": 0,
        "input": input_payload,
        "policy": {"allow_fallback": True},
    }


def _post_execute(
    client: TestClient,
    payload: dict[str, Any],
    *,
    idempotency_key: str = "cloud-batch-idem",
) -> Any:
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            key_id="key_default",
            idempotency_key=idempotency_key,
            nonce=f"nonce-{idempotency_key}",
            trace_id="cloudbatch00000000000000000000",
            body=body,
        )
    )
    return client.post("/v1/runtime/execute", content=body, headers=headers)


def _set_plan_metadata(database_url: str, metadata: dict[str, Any]) -> None:
    with get_session(database_url) as session:
        plan_version = session.get(PlanVersion, "plan_free_v1")
        assert plan_version is not None
        existing = (
            plan_version.metadata_json if isinstance(plan_version.metadata_json, dict) else {}
        )
        plan_version.metadata_json = {**existing, **metadata}
        session.commit()


def _get_result(client: TestClient, run_id: str) -> Any:
    headers = build_auth_headers(
        "GET",
        f"/v1/runs/{run_id}/result",
        site_id="site_alpha",
        key_id="key_default",
        trace_id="cloudbatchresult0000000000000",
    )
    return client.get(f"/v1/runs/{run_id}/result", headers=headers)


def test_cloud_batch_runtime_queues_and_worker_returns_review_only_result(tmp_path: Path) -> None:
    database_url, settings, runtime_queue, client = _build_client(tmp_path)

    execute_response = _post_execute(client, _payload())

    assert execute_response.status_code == 200
    execute_body = execute_response.json()
    assert execute_body["data"]["status"] == "queued"
    assert execute_body["data"]["execution_context"]["ability_family"] == "automation"
    assert execute_body["data"]["execution_context"]["execution_pattern"] == "whole_run_offload"
    assert execute_body["data"]["task_backend"]["status"] == "queued"
    run_id = execute_body["data"]["run_id"]

    worker_result = RuntimeService(
        database_url,
        settings=settings,
        runtime_queue=runtime_queue,
    ).process_next_queued_run(timeout_seconds=0)

    assert worker_result == {
        "run_id": run_id,
        "status": "succeeded",
        "trace_id": execute_body["data"]["trace_id"],
    }

    result_response = _get_result(client, run_id)
    assert result_response.status_code == 200
    result = result_response.json()["data"]["result"]
    assert result["contract_version"] == "cloud_batch_runtime_result.v1"
    assert result["runtime_owner"] == "npcink-local-automation-runtime"
    assert result["cloud_role"] == "runtime_detail"
    assert result["summary"]["items_scanned"] == 2
    assert result["summary"]["score_version"] == "nightly_content_quality_score.v2"
    assert result["scoring_profile"]["editorial_truth"] == "wordpress_local"
    assert result["safety"]["direct_wordpress_write"] is False
    assert result["safety"]["final_write_path"] == "core_proposal_required"
    assert result["safety"]["article_body_generated"] is False
    assert result["actions"][0]["status"] == "succeeded"
    assert "missing_meta_description" in result["actions"][0]["reason_codes"]
    assert result["actions"][0]["score_breakdown"]["score_version"] == (
        "nightly_content_quality_score.v2"
    )
    score_dimensions = {
        item["id"]: item for item in result["actions"][0]["score_breakdown"]["dimensions"]
    }
    assert "missing_meta_description" in score_dimensions[
        "metadata_completeness"
    ]["reason_codes"]
    assert score_dimensions["media_accessibility"]["impact"] == 10
    assert result["actions"][0]["priority_reason"] == "critical_score"
    assert result["nightly_result"]["contract_version"] == "nightly_site_inspection_result.v1"
    assert result["nightly_result"]["safety"]["cloud_scheduler_truth"] is False
    assert result["nightly_result"]["issue_groups"][0]["id"] == "metadata"
    assert result["morning_brief"]["contract_version"] == (
        "nightly_site_inspection_morning_brief.v2"
    )
    assert result["morning_brief"]["top_summary"]["reviewable_items"] == 1
    assert result["morning_brief"]["priority_queue"][0]["action_id"] == "action_001"
    assert result["morning_brief"]["priority_queue"][0]["group_ids"] == [
        "metadata",
        "content_depth",
        "internal_links",
        "media_accessibility",
        "freshness",
    ]
    assert result["morning_brief"]["core_handoff"]["available"] is True
    assert result["writing_preparation"][0]["suggested_review_angle"] == (
        "refresh_existing_content"
    )
    assert "candidate_internal_targets" in result["writing_preparation"][0]["missing_context"]
    assert result["core_review_plan"]["contract_version"] == (
        "nightly_site_inspection_core_review_plan.v1"
    )
    assert result["core_review_plan"]["artifact_type"] == "nightly_site_inspection_review_plan"
    assert result["core_review_plan"]["requires_approval"] is True
    assert result["core_review_plan"]["commit_execution"] is False
    assert result["core_review_plan"]["dry_run"] is True
    assert result["core_review_plan"]["direct_wordpress_write"] is False
    assert result["core_review_plan"]["write_actions"][0]["target_ability_id"] == (
        "npcink-abilities-toolkit/create-draft"
    )
    assert result["core_review_plan"]["write_actions"][0]["proposal_ready"] is False
    assert result["core_review_plan"]["write_actions"][0]["requires_input"] == [
        "title",
        "content",
    ]
    assert result["handoff"]["target_plan_ability_id"] == (
        "npcink-toolbox/build-nightly-inspection-review-plan"
    )
    assert result["handoff"]["proposal_candidate_available"] is True

    with get_session(database_url) as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        assert run.execution_kind == "nightly_site_inspection"
        assert run.execution_input_ciphertext is None
        provider_call = session.scalar(
            select(ProviderCallRecord).where(ProviderCallRecord.run_id == run_id)
        )
        assert provider_call is not None
        assert provider_call.provider_id == "cloud_batch_runtime"


def test_cloud_batch_runtime_rejects_over_plan_batch_item_limit(tmp_path: Path) -> None:
    database_url, _, _, client = _build_client(tmp_path)
    _set_plan_metadata(database_url, {"max_batch_items": 1})

    response = _post_execute(
        client,
        _payload(),
        idempotency_key="cloud-batch-item-limit",
    )

    assert response.status_code == 429
    body = response.json()
    assert body["error_code"] == "commercial.batch_limit_exceeded"
    assert "nightly_site_inspection" in body["message"]


def test_cloud_batch_runtime_rejects_over_period_inspection_quota(tmp_path: Path) -> None:
    database_url, _, _, client = _build_client(tmp_path)
    _set_plan_metadata(
        database_url,
        {
            "max_batch_items": 10,
            "nightly_inspection_runs_per_period": 1,
        },
    )
    with get_session(database_url) as session:
        subscription = session.get(AccountSubscription, "sub_site_alpha")
        assert subscription is not None
        created_at = subscription.current_period_start_at + timedelta(seconds=1)
        session.add(
            UsageMeterEvent(
                account_id="acct_site_alpha",
                site_id="site_alpha",
                subscription_id=subscription.subscription_id,
                plan_version_id=subscription.plan_version_id,
                run_id="run_prior_nightly_inspection",
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
                dedupe_key="run:prior-nightly-inspection:runs",
                payload_json={"source": "test_prior_usage"},
                created_at=created_at,
            )
        )
        session.commit()

    response = _post_execute(
        client,
        _payload(),
        idempotency_key="cloud-batch-period-limit",
    )

    assert response.status_code == 429
    body = response.json()
    assert body["error_code"] == "commercial.quota_exceeded"
    assert "nightly_site_inspection_runs" in body["message"]


def test_cloud_batch_runtime_rejects_write_control_fields(tmp_path: Path) -> None:
    _, _, _, client = _build_client(tmp_path)

    response = _post_execute(
        client,
        _payload({"items": [{"object_id": 1, "title": "Needs review"}], "update_post": True}),
        idempotency_key="cloud-batch-write-field",
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "cloud_batch_runtime.write_or_secret_field_forbidden"
