from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.adapters.queue.in_memory import InMemoryRuntimeQueue
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import MediaArtifact, ProviderCallRecord, RunRecord
from app.core.secrets import decrypt_runtime_execution_input
from app.core.services import CloudServices
from app.domain.media_artifacts import build_artifact_store
from app.domain.media_derivatives.contracts import BLOCKED_RESPONSE_FIELDS, MediaJobRequest
from app.domain.runtime.service import RuntimeService
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_KEY_ID,
    TEST_PORTAL_JWT_SECRET,
    build_auth_headers,
    build_internal_headers,
    seed_site_auth,
)

UPLOAD_PATH = "/v1/runtime/media/uploads"
JOB_PATH = "/v1/runtime/media/jobs"


def _png(width: int = 32, height: int = 24, color: str = "red") -> bytes:
    image = Image.new("RGB", (width, height), color=color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _multipart(request_payload: dict[str, object], payload: bytes) -> tuple[bytes, str]:
    boundary = "npcink-media-boundary"
    body = b"\r\n".join(
        (
            f"--{boundary}".encode(),
            b'Content-Disposition: form-data; name="request"',
            b"",
            json.dumps(request_payload, separators=(",", ":")).encode(),
            f"--{boundary}".encode(),
            b'Content-Disposition: form-data; name="file"; filename="source.png"',
            b"Content-Type: image/png",
            b"",
            payload,
            f"--{boundary}--".encode(),
        )
    )
    return body, f"multipart/form-data; boundary={boundary}"


def _client(
    tmp_path: Path,
    *,
    settings_overrides: dict[str, object] | None = None,
) -> tuple[str, Settings, InMemoryRuntimeQueue, TestClient]:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'media-resources.sqlite3'}"
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read"],
    )
    seed_site_auth(
        database_url,
        site_id="site_beta",
        key_id="key_beta",
        scopes=["runtime:execute", "runtime:read"],
    )
    settings_values: dict[str, object] = {
        "environment": "test",
        "database_url": database_url,
        "redis_url": "redis://localhost:6379/0",
        "artifact_store_root": str(tmp_path / "artifacts"),
        "internal_auth_token": TEST_INTERNAL_AUTH_TOKEN,
        "admin_session_secret": TEST_ADMIN_SESSION_SECRET,
        "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
    }
    settings_values.update(settings_overrides or {})
    settings = Settings(**settings_values)
    queue = InMemoryRuntimeQueue()
    client = TestClient(create_app(CloudServices(settings=settings, runtime_queue=queue)))
    return database_url, settings, queue, client


def _upload(
    client: TestClient,
    payload: bytes,
    *,
    key: str,
    nonce: str,
    site_id: str = "site_alpha",
    key_id: str = TEST_KEY_ID,
) -> Any:
    body, content_type = _multipart(
        {
            "request_contract_version": "media_upload_request.v1",
            "media_kind": "image",
            "ttl_minutes": 30,
        },
        payload,
    )
    headers = build_auth_headers(
        "POST",
        UPLOAD_PATH,
        site_id=site_id,
        key_id=key_id,
        body=body,
        idempotency_key=key,
        nonce=nonce,
    )
    headers["content-type"] = content_type
    return client.post(UPLOAD_PATH, content=body, headers=headers)


def _job_payload(source_artifact_id: str) -> dict[str, object]:
    return {
        "request_contract_version": "media_job_request.v1",
        "operation": "image.transform.v1",
        "source_artifact_id": source_artifact_id,
        "params": {
            "target_format": "webp",
            "max_width": 16,
            "quality": 80,
            "source_media_type": "image",
        },
        "result_ttl_minutes": 30,
    }


def _post_job(
    client: TestClient,
    payload: dict[str, object],
    *,
    key: str,
    nonce: str,
    site_id: str = "site_alpha",
    key_id: str = TEST_KEY_ID,
) -> Any:
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = build_auth_headers(
        "POST",
        JOB_PATH,
        site_id=site_id,
        key_id=key_id,
        body=body,
        idempotency_key=key,
        nonce=nonce,
    )
    headers["content-type"] = "application/json"
    return client.post(JOB_PATH, content=body, headers=headers)


def _artifact_id(response: Any) -> str:
    assert response.status_code == 200, response.json()
    return str(response.json()["data"]["result"]["artifact"]["artifact_id"])


def _process_jobs(
    database_url: str,
    settings: Settings,
    queue: InMemoryRuntimeQueue,
    *,
    max_runs: int = 10,
) -> list[dict[str, object]]:
    return RuntimeService(
        database_url,
        settings=settings,
        runtime_queue=queue,
    ).process_queued_runs(max_runs=max_runs, timeout_seconds=0)


def test_upload_replay_and_conflict_do_not_duplicate_artifacts(tmp_path: Path) -> None:
    database_url, _, _, client = _client(tmp_path)
    try:
        first = _upload(client, _png(color="red"), key="upload-key", nonce="upload-1")
        assert first.status_code == 200, first.json()
        replay = _upload(client, _png(color="red"), key="upload-key", nonce="upload-2")
        assert replay.status_code == 200, replay.json()
        assert replay.json()["data"]["idempotent_replay"] is True
        assert replay.json()["data"]["run_id"] == first.json()["data"]["run_id"]

        conflict = _upload(client, _png(color="blue"), key="upload-key", nonce="upload-3")
        assert conflict.status_code == 409, conflict.json()
        with get_session(database_url) as session:
            artifacts = list(session.scalars(select(MediaArtifact)))
            assert len(artifacts) == 1
            assert artifacts[0].operation == "image.upload.v1"
            run = session.get(RunRecord, first.json()["data"]["run_id"])
            assert run is not None
            assert run.status == "succeeded"
            assert run.contract_version == "media_upload_request.v1"
            assert run.ability_family == "media"
            assert run.execution_input_ciphertext is None
    finally:
        dispose_engine(database_url)


def test_successful_upload_is_visible_as_non_ai_zero_credit_telemetry(
    tmp_path: Path,
) -> None:
    database_url, _, _, client = _client(tmp_path)
    try:
        upload = _upload(client, _png(), key="telemetry-upload", nonce="telemetry-1")
        assert upload.status_code == 200, upload.json()

        response = client.get(
            "/internal/service/runtime/diagnostics/runtime-telemetry"
            "?site_id=site_alpha&recent_minutes=60&limit=10",
            headers=build_internal_headers(),
        )

        assert response.status_code == 200, response.json()
        data = response.json()["data"]
        assert data["totals"] == {
            "runs": 1,
            "ai_evidence_required_runs": 0,
            "non_ai_zero_credit_runs": 1,
            "provider_calls": 0,
            "usage_meter_events": 0,
            "provider_call_run_coverage_rate": 1.0,
            "metered_run_coverage_rate": 1.0,
        }
        media_group = next(
            item for item in data["capability_groups"] if item["group_id"] == "media"
        )
        assert media_group["runs_total"] == 1
        assert media_group["ai_evidence_required_runs"] == 0
        assert media_group["provider_call_run_coverage_rate"] == 1.0
        assert media_group["metered_run_coverage_rate"] == 1.0
        assert data["governance_gaps"]["unmetered_capabilities"] == []
        assert data["governance_gaps"]["missing_provider_call_capabilities"] == []
        assert data["governance_gaps"]["unmetered_run_count"] == 0
        assert data["governance_gaps"]["runs_without_provider_call_count"] == 0
        assert data["alert_summary"]["status"] == "ok"
        assert data["alert_summary"]["alerts"] == []
        assert data["alert_summary"]["daily_digest"]["runs"] == 1
        assert data["alert_summary"]["daily_digest"]["ai_evidence_required_runs"] == 0
        assert data["alert_summary"]["daily_digest"]["non_ai_zero_credit_runs"] == 1
    finally:
        dispose_engine(database_url)


def test_upload_validates_mime(tmp_path: Path) -> None:
    database_url, _, _, client = _client(tmp_path)
    try:
        body, content_type = _multipart(
            {
                "request_contract_version": "media_upload_request.v1",
                "media_kind": "image",
            },
            _png(),
        )
        body = body.replace(b"Content-Type: image/png", b"Content-Type: image/jpeg")
        headers = build_auth_headers(
            "POST",
            UPLOAD_PATH,
            site_id="site_alpha",
            body=body,
            idempotency_key="mime-key",
            nonce="mime-1",
        )
        headers["content-type"] = content_type
        response = client.post(UPLOAD_PATH, content=body, headers=headers)
        assert response.status_code == 422
        assert response.json()["error_code"] == "media_upload.content_type_mismatch"
        with get_session(database_url) as session:
            assert session.scalar(select(MediaArtifact)) is None
    finally:
        dispose_engine(database_url)


def test_job_persists_only_refs_and_worker_reads_artifact(tmp_path: Path) -> None:
    database_url, settings, queue, client = _client(tmp_path)
    try:
        upload = _upload(client, _png(32, 24), key="source-key", nonce="source-1")
        assert upload.status_code == 200, upload.json()
        source_id = upload.json()["data"]["result"]["artifact"]["artifact_id"]
        request_payload = _job_payload(source_id)
        normalized_payload = MediaJobRequest.model_validate(request_payload).model_dump()
        job = _post_job(client, request_payload, key="job-key", nonce="job-1")
        assert job.status_code == 200, job.json()
        run_id = job.json()["data"]["run_id"]

        with get_session(database_url) as session:
            run = session.get(RunRecord, run_id)
            assert run is not None
            assert run.input_json == normalized_payload
            execution_input = decrypt_runtime_execution_input(
                run.execution_input_ciphertext or "",
                settings=settings,
            )
            assert execution_input == normalized_payload
            serialized = json.dumps(execution_input)
            assert "storage_key" not in serialized
            assert "base64" not in serialized.lower()
            assert "_bytes_b64" not in serialized

        RuntimeService(database_url, settings=settings, runtime_queue=queue).process_queued_runs(
            max_runs=1,
            timeout_seconds=0,
        )
        with get_session(database_url) as session:
            run = session.get(RunRecord, run_id)
            assert run is not None and run.status == "succeeded"
            artifact = session.scalar(select(MediaArtifact).where(MediaArtifact.run_id == run_id))
            assert artifact is not None
            assert artifact.operation == "image.transform.v1"
            assert artifact.width == 16
            assert artifact.height == 12
    finally:
        dispose_engine(database_url)


def test_job_replay_survives_source_expiry_but_new_job_fails_closed(tmp_path: Path) -> None:
    database_url, _, _, client = _client(tmp_path)
    try:
        upload = _upload(client, _png(), key="exp-source", nonce="exp-source-1")
        source_id = upload.json()["data"]["result"]["artifact"]["artifact_id"]
        payload = _job_payload(source_id)
        first = _post_job(client, payload, key="exp-job", nonce="exp-job-1")
        assert first.status_code == 200, first.json()
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, source_id)
            assert artifact is not None
            artifact.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()

        replay = _post_job(client, payload, key="exp-job", nonce="exp-job-2")
        assert replay.status_code == 200, replay.json()
        assert replay.json()["data"]["idempotent_replay"] is True
        rejected = _post_job(client, payload, key="exp-job-new", nonce="exp-job-3")
        assert rejected.status_code == 410, rejected.json()
        assert rejected.json()["error_code"] == "media_job.source_artifact_expired"
    finally:
        dispose_engine(database_url)


def test_cross_site_artifact_is_not_visible_and_old_post_is_gone(tmp_path: Path) -> None:
    database_url, _, _, client = _client(tmp_path)
    try:
        upload = _upload(client, _png(), key="cross-source", nonce="cross-source-1")
        source_id = upload.json()["data"]["result"]["artifact"]["artifact_id"]
        payload = _job_payload(source_id)
        body = json.dumps(payload, separators=(",", ":")).encode()
        headers = build_auth_headers(
            "POST",
            JOB_PATH,
            site_id="site_beta",
            key_id="key_beta",
            body=body,
            idempotency_key="cross-job",
            nonce="cross-job-1",
        )
        headers["content-type"] = "application/json"
        response = client.post(JOB_PATH, content=body, headers=headers)
        assert response.status_code == 404, response.json()
        assert response.json()["error_code"] == "media_job.source_artifact_not_found"

        old = client.post("/v1/runtime/media-derivatives")
        assert old.status_code == 404
    finally:
        dispose_engine(database_url)


@pytest.mark.parametrize(
    "case",
    [
        "target_format",
        "quality",
        "max_width",
        "source_media_type",
        "crop_ratio",
        "watermark_position",
        "result_ttl",
        "wordpress_write_field",
    ],
)
def test_job_parameter_gates_fail_before_queue_admission(
    tmp_path: Path,
    case: str,
) -> None:
    database_url, _, queue, client = _client(tmp_path)
    try:
        source_id = _artifact_id(
            _upload(client, _png(), key=f"gate-source-{case}", nonce=f"gate-source-{case}")
        )
        payload = _job_payload(source_id)
        params = payload["params"]
        assert isinstance(params, dict)
        if case == "target_format":
            params["target_format"] = "gif"
        elif case == "quality":
            params["quality"] = 0
        elif case == "max_width":
            params["max_width"] = 0
        elif case == "source_media_type":
            params["source_media_type"] = "video"
        elif case == "crop_ratio":
            params["crop"] = {
                "type": "aspect_ratio",
                "aspect_ratio": "invalid",
                "position": "center",
            }
        elif case == "watermark_position":
            params["watermark"] = {
                "type": "text",
                "text": "Npcink",
                "position": "outside",
            }
        elif case == "result_ttl":
            payload["result_ttl_minutes"] = 120
        else:
            payload["target_attachment_id"] = 42

        response = _post_job(
            client,
            payload,
            key=f"gate-job-{case}",
            nonce=f"gate-job-{case}",
        )

        assert response.status_code == 422, response.json()
        assert response.json()["error_code"] == "media_job.validation_error"
        assert queue.consume(timeout_seconds=0) is None
        with get_session(database_url) as session:
            assert (
                session.scalar(
                    select(RunRecord).where(RunRecord.execution_kind == "media_derivative")
                )
                is None
            )
    finally:
        dispose_engine(database_url)


def test_batch_avif_requires_explicit_confirmation(tmp_path: Path) -> None:
    database_url, _, _, client = _client(tmp_path)
    try:
        source_id = _artifact_id(_upload(client, _png(), key="avif-source", nonce="avif-source"))
        payload = _job_payload(source_id)
        params = payload["params"]
        assert isinstance(params, dict)
        params["target_format"] = "avif"
        payload["batch_context"] = {
            "batch_id": "batch-avif",
            "item_index": 1,
            "item_count": 2,
            "chunk_size": 2,
            "explicit_avif": False,
        }

        rejected = _post_job(
            client,
            payload,
            key="avif-job-rejected",
            nonce="avif-job-rejected",
        )
        assert rejected.status_code == 422, rejected.json()
        assert rejected.json()["error_code"] == "media_job.validation_error"

        batch_context = payload["batch_context"]
        assert isinstance(batch_context, dict)
        batch_context["explicit_avif"] = True
        accepted = _post_job(
            client,
            payload,
            key="avif-job-accepted",
            nonce="avif-job-accepted",
        )
        assert accepted.status_code == 200, accepted.json()
        assert accepted.json()["data"]["status"] == "queued"
    finally:
        dispose_engine(database_url)


def test_site_queue_full_rejects_second_job(tmp_path: Path) -> None:
    database_url, _, _, client = _client(
        tmp_path,
        settings_overrides={
            "media_derivative_site_queued_limit": 1,
            "media_derivative_site_running_limit": 1,
        },
    )
    try:
        source_id = _artifact_id(_upload(client, _png(), key="queue-source", nonce="queue-source"))
        payload = _job_payload(source_id)
        first = _post_job(client, payload, key="queue-job-1", nonce="queue-job-1")
        assert first.status_code == 200, first.json()

        second = _post_job(client, payload, key="queue-job-2", nonce="queue-job-2")
        assert second.status_code == 429, second.json()
        assert second.json()["error_code"] == "media_derivative.site_queue_full"
        with get_session(database_url) as session:
            queued = list(
                session.scalars(
                    select(RunRecord).where(
                        RunRecord.execution_kind == "media_derivative",
                        RunRecord.status == "queued",
                    )
                )
            )
            assert [run.run_id for run in queued] == [first.json()["data"]["run_id"]]
    finally:
        dispose_engine(database_url)


def test_watermark_artifact_must_belong_to_job_site(tmp_path: Path) -> None:
    database_url, _, _, client = _client(tmp_path)
    try:
        source_id = _artifact_id(
            _upload(
                client,
                _png(),
                key="beta-source",
                nonce="beta-source",
                site_id="site_beta",
                key_id="key_beta",
            )
        )
        watermark_id = _artifact_id(
            _upload(client, _png(8, 8), key="alpha-watermark", nonce="alpha-watermark")
        )
        payload = _job_payload(source_id)
        payload["watermark_artifact_id"] = watermark_id
        params = payload["params"]
        assert isinstance(params, dict)
        params["watermark"] = {"type": "image", "position": "bottom_right"}

        response = _post_job(
            client,
            payload,
            key="cross-site-watermark-job",
            nonce="cross-site-watermark-job",
            site_id="site_beta",
            key_id="key_beta",
        )

        assert response.status_code == 404, response.json()
        assert response.json()["error_code"] == "media_job.watermark_artifact_not_found"
    finally:
        dispose_engine(database_url)


def test_expired_and_missing_watermark_artifacts_fail_closed(tmp_path: Path) -> None:
    database_url, _, _, client = _client(tmp_path)
    try:
        source_id = _artifact_id(_upload(client, _png(), key="wm-source", nonce="wm-source"))
        watermark_id = _artifact_id(
            _upload(client, _png(8, 8), key="wm-expiring", nonce="wm-expiring")
        )
        payload = _job_payload(source_id)
        payload["watermark_artifact_id"] = watermark_id
        params = payload["params"]
        assert isinstance(params, dict)
        params["watermark"] = {"type": "image", "position": "bottom_right"}
        with get_session(database_url) as session:
            watermark = session.get(MediaArtifact, watermark_id)
            assert watermark is not None
            watermark.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()

        expired = _post_job(
            client,
            payload,
            key="expired-watermark-job",
            nonce="expired-watermark-job",
        )
        assert expired.status_code == 410, expired.json()
        assert expired.json()["error_code"] == "media_job.watermark_artifact_expired"

        payload["watermark_artifact_id"] = "art_missing_watermark"
        missing = _post_job(
            client,
            payload,
            key="missing-watermark-job",
            nonce="missing-watermark-job",
        )
        assert missing.status_code == 404, missing.json()
        assert missing.json()["error_code"] == "media_job.watermark_artifact_not_found"
    finally:
        dispose_engine(database_url)


def test_missing_watermark_bytes_fail_worker_without_provider_call(tmp_path: Path) -> None:
    database_url, settings, queue, client = _client(tmp_path)
    try:
        source_id = _artifact_id(
            _upload(client, _png(), key="wm-bytes-source", nonce="wm-bytes-source")
        )
        watermark_id = _artifact_id(_upload(client, _png(8, 8), key="wm-bytes", nonce="wm-bytes"))
        with get_session(database_url) as session:
            watermark = session.get(MediaArtifact, watermark_id)
            assert watermark is not None
            build_artifact_store(settings).delete(watermark.storage_key)

        payload = _job_payload(source_id)
        payload["watermark_artifact_id"] = watermark_id
        params = payload["params"]
        assert isinstance(params, dict)
        params["watermark"] = {"type": "image", "position": "bottom_right"}
        job = _post_job(
            client,
            payload,
            key="missing-watermark-bytes-job",
            nonce="missing-watermark-bytes-job",
        )
        assert job.status_code == 200, job.json()
        run_id = job.json()["data"]["run_id"]

        processed = _process_jobs(database_url, settings, queue, max_runs=1)
        assert [item["run_id"] for item in processed] == [run_id]
        with get_session(database_url) as session:
            run = session.get(RunRecord, run_id)
            assert run is not None
            assert run.status == "failed"
            assert run.error_code == "media_job.watermark_artifact_unavailable"
            assert session.scalar(select(ProviderCallRecord)) is None
    finally:
        dispose_engine(database_url)


def test_purged_source_artifact_is_rejected(tmp_path: Path) -> None:
    database_url, _, _, client = _client(tmp_path)
    try:
        source_id = _artifact_id(
            _upload(client, _png(), key="purged-source", nonce="purged-source")
        )
        with get_session(database_url) as session:
            source = session.get(MediaArtifact, source_id)
            assert source is not None
            source.status = "purged"
            source.purged_at = datetime.now(UTC)
            session.commit()

        response = _post_job(
            client,
            _job_payload(source_id),
            key="purged-source-job",
            nonce="purged-source-job",
        )

        assert response.status_code == 410, response.json()
        assert response.json()["error_code"] == "media_job.source_artifact_expired"
    finally:
        dispose_engine(database_url)


def test_job_results_exclude_wordpress_write_fields_and_provider_calls(tmp_path: Path) -> None:
    database_url, settings, queue, client = _client(tmp_path)
    try:
        source_id = _artifact_id(
            _upload(client, _png(), key="boundary-source", nonce="boundary-source")
        )
        job = _post_job(
            client,
            _job_payload(source_id),
            key="boundary-job",
            nonce="boundary-job",
        )
        assert job.status_code == 200, job.json()
        run_id = job.json()["data"]["run_id"]
        _process_jobs(database_url, settings, queue, max_runs=1)

        result_path = f"/v1/runs/{run_id}/result"
        headers = build_auth_headers("GET", result_path, site_id="site_alpha")
        result = client.get(result_path, headers=headers)
        assert result.status_code == 200, result.json()
        serialized = json.dumps({"job": job.json(), "result": result.json()})
        for field in BLOCKED_RESPONSE_FIELDS:
            assert field not in serialized
        with get_session(database_url) as session:
            assert session.scalar(select(ProviderCallRecord)) is None
    finally:
        dispose_engine(database_url)
