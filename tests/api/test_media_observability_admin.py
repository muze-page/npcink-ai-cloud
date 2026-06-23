from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import MediaDerivativeArtifact, MediaDerivativeJobMetric, RunRecord
from app.core.services import CloudServices
from tests.conftest import TEST_INTERNAL_AUTH_TOKEN, build_internal_headers, seed_site_auth


def _build_client(tmp_path: Path) -> tuple[str, TestClient]:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'media-obs-admin.sqlite3'}"
    init_schema(database_url)
    seed_site_auth(database_url, site_id="site-media-001", scopes=["runtime:execute"])
    seed_site_auth(database_url, site_id="site-media-002", scopes=["runtime:execute"])
    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
    )
    return database_url, TestClient(create_app(CloudServices(settings=settings)))


def _run_record(
    run_id: str,
    site_id: str,
    *,
    status: str,
    now: datetime,
    policy_json: dict[str, object] | None = None,
) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        site_id=site_id,
        account_id=f"account-{site_id}",
        subscription_id=f"sub-{site_id}",
        plan_version_id="plan-media",
        ability_name="generate_optimized_media_derivative",
        ability_family="vision",
        skill_id="",
        workflow_id="",
        contract_version="media_derivative_cloud_request.v1",
        channel="openapi",
        execution_kind="media_derivative",
        execution_tier="cloud",
        execution_pattern="whole_run_offload",
        data_classification="internal",
        profile_id="media_derivative.worker",
        canonical_run_id=None,
        status=status,
        idempotency_key=f"idem-{run_id}",
        request_fingerprint=f"fingerprint-{run_id}",
        trace_id=f"trace-{run_id}",
        input_json={},
        execution_input_ciphertext=None,
        policy_json=policy_json or {},
        selected_provider_id="media_derivative",
        selected_model_id="pillow",
        selected_instance_id="cloud-worker",
        fallback_used=False,
        started_at=now - timedelta(seconds=5),
        processing_started_at=now - timedelta(seconds=4),
        finished_at=now,
    )


def _seed_media_metrics(database_url: str) -> None:
    now = datetime.now(UTC)
    with get_session(database_url) as session:
        session.add_all(
            [
                _run_record(
                    "run-media-001",
                    "site-media-001",
                    status="succeeded",
                    now=now,
                    policy_json={
                        "media_derivative": {
                            "target_format": "webp",
                            "batch_context": {
                                "batch_id": "batch-media-001",
                                "item_index": 1,
                                "item_count": 3,
                                "chunk_size": 2,
                                "explicit_avif": False,
                            },
                            "write_posture": "artifact_only",
                            "direct_wordpress_write": False,
                        }
                    },
                ),
                _run_record("run-media-002", "site-media-001", status="failed", now=now),
                _run_record("run-media-003", "site-media-002", status="succeeded", now=now),
            ]
        )
        session.flush()
        session.add_all(
            [
                MediaDerivativeArtifact(
                    artifact_id="art-media-001",
                    run_id="run-media-001",
                    site_id="site-media-001",
                    storage_ref="blob://media_derivative/art-media-001",
                    blob_data=b"1234",
                    mime_type="image/webp",
                    format="webp",
                    width=100,
                    height=80,
                    filesize_bytes=400,
                    checksum="sha256:abc",
                    source_media_type="image",
                    processing_warnings_json={"warnings": []},
                    expires_at=now + timedelta(minutes=30),
                    created_at=now,
                ),
                MediaDerivativeArtifact(
                    artifact_id="art-media-003",
                    run_id="run-media-003",
                    site_id="site-media-002",
                    storage_ref="blob://media_derivative/art-media-003",
                    blob_data=b"12345",
                    mime_type="image/jpeg",
                    format="jpeg",
                    width=200,
                    height=100,
                    filesize_bytes=800,
                    checksum="sha256:def",
                    source_media_type="image",
                    processing_warnings_json={"warnings": []},
                    expires_at=now + timedelta(minutes=30),
                    created_at=now,
                ),
            ]
        )
        session.add_all(
            [
                MediaDerivativeJobMetric(
                    run_id="run-media-001",
                    site_id="site-media-001",
                    account_id="account-site-media-001",
                    subscription_id="sub-site-media-001",
                    status="succeeded",
                    target_format="webp",
                    output_format="webp",
                    source_media_type="image",
                    source_bytes=1000,
                    output_bytes=400,
                    source_width=200,
                    source_height=160,
                    output_width=100,
                    output_height=80,
                    compression_ratio=0.6,
                    queue_wait_ms=1000,
                    processing_duration_ms=120,
                    total_duration_ms=5000,
                    watermark_applied=False,
                    warnings_count=0,
                    artifact_id="art-media-001",
                    artifact_expires_at=now + timedelta(minutes=30),
                    artifact_download_count=1,
                    created_at=now - timedelta(minutes=10),
                    finished_at=now - timedelta(minutes=10),
                ),
                MediaDerivativeJobMetric(
                    run_id="run-media-002",
                    site_id="site-media-001",
                    account_id="account-site-media-001",
                    subscription_id="sub-site-media-001",
                    status="failed",
                    error_code="media_derivative.source_decode_failed",
                    target_format="webp",
                    output_format=None,
                    source_media_type="image",
                    source_bytes=200,
                    output_bytes=0,
                    compression_ratio=0,
                    queue_wait_ms=800,
                    processing_duration_ms=50,
                    total_duration_ms=4000,
                    watermark_applied=True,
                    warnings_count=0,
                    created_at=now - timedelta(minutes=5),
                    finished_at=now - timedelta(minutes=5),
                ),
                MediaDerivativeJobMetric(
                    run_id="run-media-003",
                    site_id="site-media-002",
                    account_id="account-site-media-002",
                    subscription_id="sub-site-media-002",
                    status="succeeded",
                    target_format="jpeg",
                    output_format="jpeg",
                    source_media_type="image",
                    source_bytes=1600,
                    output_bytes=800,
                    source_width=400,
                    source_height=200,
                    output_width=200,
                    output_height=100,
                    compression_ratio=0.5,
                    queue_wait_ms=2000,
                    processing_duration_ms=260,
                    total_duration_ms=6000,
                    watermark_applied=False,
                    warnings_count=1,
                    artifact_id="art-media-003",
                    artifact_expires_at=now + timedelta(minutes=30),
                    created_at=now - timedelta(minutes=15),
                    finished_at=now - timedelta(minutes=15),
                ),
            ]
        )
        session.commit()


def test_admin_media_observability_returns_cross_site_summary(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        _seed_media_metrics(database_url)
        response = client.get(
            "/internal/service/admin/media-observability?window_hours=24",
            headers=build_internal_headers(trace_id="tracemedia0010000000000000000000"),
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["contract_version"] == "magick-media-observability-summary-v1"
        assert data["workflow_metadata"]["workflow_id"] == ("media_derivative_artifact_generation")
        assert data["workflow_metadata"]["handoff_owner"] == "wordpress_local"
        assert data["workflow_metadata"]["direct_wordpress_write"] is False
        assert data["totals"]["jobs_total"] == 3
        assert data["totals"]["succeeded_total"] == 2
        assert data["totals"]["failed_total"] == 1
        assert data["totals"]["source_bytes_total"] == 2800
        assert data["totals"]["output_bytes_total"] == 1200
        assert data["totals"]["bytes_saved_total"] == 1600
        assert data["totals"]["artifact_download_count"] == 1
        assert data["totals"]["active_site_count"] == 2
        assert data["totals"]["active_artifact_bytes"] == 1200
        assert data["health"]["status"] in {"ok", "warning", "error"}
        assert data["queue"]["queued_total"] == 0
        assert data["queue"]["running_total"] == 0
        assert data["queue"]["limits"]["site_queued"] == 100
        assert data["batch"]["active_or_recent_batch_count"] == 1
        assert data["batch"]["items"][0]["batch_id"] == "batch-media-001"
        assert data["batch"]["items"][0]["succeeded"] == 1
        assert sum(item["jobs_total"] for item in data["timeline"]) == 3
        assert {item["target_format"] for item in data["formats"]} == {"webp", "jpeg"}
        assert len(data["sites"]) == 2
        assert data["errors"][0]["error_code"] == "media_derivative.source_decode_failed"
        assert "source_bytes" in data["recent_failures"][0]
        assert "blob_data" not in data["recent_failures"][0]
    finally:
        dispose_engine(database_url)


def test_admin_media_observability_filters_by_site_and_format(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        _seed_media_metrics(database_url)
        response = client.get(
            "/internal/service/admin/media-observability"
            "?window_hours=24&site_id=site-media-001&target_format=webp",
            headers=build_internal_headers(trace_id="tracemedia0020000000000000000000"),
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["totals"]["jobs_total"] == 2
        assert data["totals"]["active_site_count"] == 1
        assert all(item["target_format"] == "webp" for item in data["formats"])
        assert all(item["site_id"] == "site-media-001" for item in data["sites"])
    finally:
        dispose_engine(database_url)


def test_admin_media_observability_rejects_without_internal_token(tmp_path: Path) -> None:
    _, client = _build_client(tmp_path)
    response = client.get("/internal/service/admin/media-observability?window_hours=24")
    assert response.status_code in (401, 403)
    assert response.json()["status"] == "error"


def test_admin_media_observability_empty_data_returns_zero_counts(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        response = client.get(
            "/internal/service/admin/media-observability?window_hours=24",
            headers=build_internal_headers(trace_id="tracemedia0030000000000000000000"),
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["totals"]["jobs_total"] == 0
        assert data["totals"]["active_artifact_bytes"] == 0
        assert data["formats"] == []
        assert data["sites"] == []
        assert data["health"]["status"] == "inactive"
    finally:
        dispose_engine(database_url)
