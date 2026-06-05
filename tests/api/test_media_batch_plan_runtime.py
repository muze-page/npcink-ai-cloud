from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.queue.in_memory import InMemoryRuntimeQueue
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import get_session, init_schema
from app.core.models import RunRecord, UsageMeterEvent
from app.core.services import CloudServices
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
    build_auth_headers,
    merge_json_headers,
    seed_site_auth,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'media-batch-plan.sqlite3'}"


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
        project_name="Magick AI Cloud Media Batch Plan Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        media_derivative_batch_default_chunk_size=7,
        media_derivative_batch_max_chunk_size=13,
    )
    client = TestClient(
        create_app(
            CloudServices(
                settings=settings,
                providers={},
                runtime_queue=InMemoryRuntimeQueue(),
            )
        )
    )
    return database_url, client


def _payload(input_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    input_payload: dict[str, Any] = {
        "contract_version": "media_derivative_batch_plan_request.v1",
        "user_request": (
            "把 2026 年 4 月媒体库大图转换成 PNG，最大宽度 1600，"
            "质量 82，加右下角 LOGO 水印"
        ),
        "site_context": {"current_date": "2026-06-05T00:00:00Z"},
    }
    input_payload.update(input_overrides or {})
    return {
        "ability_name": "magick-ai-toolbox/plan-media-derivative-batch",
        "contract_version": "media_derivative_batch_plan_request.v1",
        "execution_pattern": "inline",
        "data_classification": "internal",
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
    idempotency_key: str = "media-batch-plan-idem",
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
            trace_id="mediabatchplan0000000000000000",
            body=body,
        )
    )
    return client.post("/v1/runtime/execute", content=body, headers=headers)


def test_media_batch_plan_runtime_generates_governed_chunk_plan(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    response = _execute(client, _payload())

    assert response.status_code == 200, response.json()
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    assert data["provider_id"] == "media_batch_plan"
    assert data["model_id"] == "deterministic-intent-parser"
    assert data["provider_call_count"] == 0
    assert data["profile_id"] == "media-derivative-batch-plan.managed"
    assert data["execution_context"]["ability_family"] == "vision"
    assert data["execution_context"]["execution_pattern"] == "inline"

    result = data["result"]
    assert result["contract_version"] == "media_derivative_batch_plan.v1"
    assert result["artifact_type"] == "media_derivative_batch_plan"
    assert result["scope"]["uploaded_from"] == "2026-04-01"
    assert result["scope"]["uploaded_to"] == "2026-04-30"
    assert result["operation"]["target_format"] == "png"
    assert result["operation"]["max_width"] == 1600
    assert result["operation"]["quality"] == 82
    assert result["operation"]["watermark"]["type"] == "image"
    assert result["operation"]["watermark"]["position"] == "bottom_right"
    assert result["execution_plan"]["recommended_chunk_size"] == 7
    assert result["execution_plan"]["max_chunk_size"] == 13
    assert result["handoff"]["final_writes"] == "core_proposal_required"
    assert result["direct_wordpress_write"] is False
    assert "把 2026 年 4 月媒体库大图" not in json.dumps(result, ensure_ascii=False)

    with get_session(database_url) as session:
        run = session.get(RunRecord, data["run_id"])
        assert run is not None
        assert run.execution_kind == "media_derivative_batch_plan"
        assert run.input_json == {}
        assert run.policy_json["execution_contract"]["direct_wordpress_write"] is False
        meter_events = list(
            session.scalars(
                select(UsageMeterEvent)
                .where(UsageMeterEvent.run_id == run.run_id)
                .order_by(UsageMeterEvent.id.asc())
            )
        )
        assert [event.meter_key for event in meter_events] == ["runs"]


def test_media_batch_plan_rejects_wordpress_write_fields(tmp_path: Path) -> None:
    _, client = _build_client(tmp_path)

    response = _execute(
        client,
        _payload({"wordpress_write_policy": {"replace_file": True}}),
        idempotency_key="media-batch-plan-forbidden-write",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "media_batch_plan.write_field_forbidden"


def test_media_batch_plan_idempotent_replay(tmp_path: Path) -> None:
    _, client = _build_client(tmp_path)
    payload = _payload({"user_request": "自动优化 4 月媒体库图片为 webp，跳过小图"})

    first = _execute(
        client,
        payload,
        idempotency_key="media-batch-plan-replay",
        nonce="nonce-media-batch-plan-replay-1",
    )
    second = _execute(
        client,
        payload,
        idempotency_key="media-batch-plan-replay",
        nonce="nonce-media-batch-plan-replay-2",
    )

    assert first.status_code == 200
    assert second.status_code == 200
    first_data = first.json()["data"]
    second_data = second.json()["data"]
    assert second_data["idempotent_replay"] is True
    assert second_data["run_id"] == first_data["run_id"]
    assert second_data["result"]["operation"]["target_format"] == "webp"
    assert second_data["result"]["exclusions"]["skip_if_filesize_below"] == 100000


def test_media_batch_plan_requires_user_request(tmp_path: Path) -> None:
    _, client = _build_client(tmp_path)

    response = _execute(
        client,
        _payload({"user_request": ""}),
        idempotency_key="media-batch-plan-missing-request",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "media_batch_plan.user_request_required"
