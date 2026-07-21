from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import get_session, init_schema
from app.core.models import (
    MediaArtifact,
    MediaArtifactDelivery,
    MediaDerivativeJobMetric,
    RunRecord,
)
from app.core.services import CloudServices
from app.domain.commercial.service import CommercialService
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
    seed_site_auth,
)
from tests.conftest import (
    build_portal_headers as _build_portal_headers,
)

_PORTAL_GRANT: dict[str, object] = {}


def build_portal_headers(**kwargs: object) -> dict[str, str]:
    if "principal_id" not in kwargs and _PORTAL_GRANT:
        kwargs["principal_id"] = str(_PORTAL_GRANT["principal_id"])
        kwargs["session_version"] = int(_PORTAL_GRANT.get("session_version") or 1)
    return _build_portal_headers(**kwargs)


def _build_client(tmp_path: Path) -> tuple[str, TestClient]:
    _PORTAL_GRANT.clear()
    database_url = f"sqlite+pysqlite:///{tmp_path / 'media-obs-portal.sqlite3'}"
    init_schema(database_url)
    seed_site_auth(database_url, site_id="site-media-portal-001", scopes=["stats:read"])
    seed_site_auth(database_url, site_id="site-media-portal-002", scopes=["stats:read"])
    _PORTAL_GRANT.update(
        CommercialService(database_url).upsert_account_member_access(
            account_id="acct_site-media-portal-001",
            email="portal-admin@example.com",
            metadata_json={"source": "test"},
        )
    )
    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
    )
    return database_url, TestClient(create_app(CloudServices(settings=settings)))


def _run_record(run_id: str, site_id: str, *, status: str, now: datetime) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        site_id=site_id,
        account_id=f"acct_{site_id}",
        subscription_id=f"sub_{site_id}",
        plan_version_id="plan-media",
        ability_name="media_image_transform",
        ability_family="vision",
        skill_id="",
        workflow_id="",
        contract_version="media_job_request.v1",
        channel="openapi",
        execution_kind="media_derivative",
        execution_tier="cloud",
        execution_pattern="whole_run_offload",
        data_classification="internal",
        profile_id="media.transform.worker",
        canonical_run_id=None,
        status=status,
        idempotency_key=f"idem-{run_id}",
        request_fingerprint=f"fingerprint-{run_id}",
        trace_id=f"trace-{run_id}",
        input_json={},
        execution_input_ciphertext=None,
        policy_json={},
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
                    "run-media-portal-001",
                    "site-media-portal-001",
                    status="succeeded",
                    now=now,
                ),
                _run_record(
                    "run-media-portal-002",
                    "site-media-portal-002",
                    status="failed",
                    now=now,
                ),
            ]
        )
        session.flush()
        artifact = MediaArtifact(
            artifact_id="art-media-portal-001",
            run_id="run-media-portal-001",
            site_id="site-media-portal-001",
            storage_key="obj_11111111111111111111111111111111",
            media_kind="image",
            operation="image.transform.v1",
            status="available",
            content_type="image/webp",
            format="webp",
            width=100,
            height=80,
            byte_size=400,
            checksum="sha256:abc",
            processing_warnings_json={"warnings": []},
            expires_at=now + timedelta(minutes=30),
            created_at=now,
        )
        foreign_artifact = MediaArtifact(
            artifact_id="art-media-portal-foreign",
            run_id="run-media-portal-002",
            site_id="site-media-portal-002",
            storage_key="obj_22222222222222222222222222222222",
            media_kind="image",
            operation="image.transform.v1",
            status="available",
            content_type="image/jpeg",
            format="jpeg",
            width=100,
            height=80,
            byte_size=500,
            checksum="sha256:foreign",
            processing_warnings_json={"warnings": []},
            expires_at=now + timedelta(minutes=30),
            created_at=now,
        )
        session.add_all([artifact, foreign_artifact])
        session.flush()
        session.add_all(
            [
                MediaArtifactDelivery(
                    delivery_id="delivery-media-portal-001",
                    artifact_id=artifact.artifact_id,
                    site_id=artifact.site_id,
                    expected_byte_size=artifact.byte_size,
                    expected_checksum=artifact.checksum,
                    pull_trace_id="trace-delivery-media-portal-001",
                    started_at=now - timedelta(minutes=9),
                    completed_at=now - timedelta(minutes=8),
                    completed_byte_size=artifact.byte_size,
                    completed_checksum=artifact.checksum,
                    ack_deadline_at=now + timedelta(minutes=1),
                    acked_at=now - timedelta(minutes=7),
                    ack_idempotency_key="ack-delivery-media-portal-001",
                    ack_request_fingerprint="f" * 64,
                    ack_trace_id="ack-trace-delivery-media-portal-001",
                    received_byte_size=artifact.byte_size,
                    received_checksum=artifact.checksum,
                    byte_size_verified=True,
                    checksum_verified=True,
                ),
                MediaArtifactDelivery(
                    delivery_id="delivery-media-portal-002",
                    artifact_id=artifact.artifact_id,
                    site_id=artifact.site_id,
                    expected_byte_size=artifact.byte_size,
                    expected_checksum=artifact.checksum,
                    pull_trace_id="trace-delivery-media-portal-002",
                    started_at=now - timedelta(minutes=6),
                    ack_deadline_at=now + timedelta(minutes=4),
                ),
                MediaArtifactDelivery(
                    delivery_id="delivery-media-portal-cross-site-artifact",
                    artifact_id=foreign_artifact.artifact_id,
                    site_id=artifact.site_id,
                    expected_byte_size=foreign_artifact.byte_size,
                    expected_checksum=foreign_artifact.checksum,
                    pull_trace_id="trace-delivery-media-portal-cross-site-artifact",
                    started_at=now - timedelta(minutes=5),
                    ack_deadline_at=now + timedelta(minutes=5),
                ),
            ]
        )
        session.add_all(
            [
                MediaDerivativeJobMetric(
                    run_id="run-media-portal-001",
                    site_id="site-media-portal-001",
                    account_id="acct_site-media-portal-001",
                    subscription_id="sub_site-media-portal-001",
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
                    artifact_id="art-media-portal-001",
                    artifact_expires_at=now + timedelta(minutes=30),
                    created_at=now - timedelta(minutes=10),
                    finished_at=now - timedelta(minutes=10),
                ),
                MediaDerivativeJobMetric(
                    run_id="run-media-portal-002",
                    site_id="site-media-portal-002",
                    account_id="acct_site-media-portal-002",
                    subscription_id="sub_site-media-portal-002",
                    status="failed",
                    error_code="media_derivative.source_decode_failed",
                    target_format="jpeg",
                    output_format=None,
                    source_media_type="image",
                    source_bytes=200,
                    output_bytes=0,
                    compression_ratio=0,
                    queue_wait_ms=800,
                    processing_duration_ms=50,
                    total_duration_ms=4000,
                    watermark_applied=False,
                    warnings_count=0,
                    created_at=now - timedelta(minutes=5),
                    finished_at=now - timedelta(minutes=5),
                ),
            ]
        )
        session.commit()


def test_portal_media_observability_returns_current_site_summary(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    _seed_media_metrics(database_url)

    response = client.get(
        "/portal/v1/sites/site-media-portal-001/media-observability?window_hours=24",
        headers=build_portal_headers(),
    )

    assert response.status_code == 200
    envelope = response.json()
    assert envelope["status"] == "ok"
    data = envelope["data"]
    assert data["contract_version"] == "magick-media-observability-summary-v2"
    assert data["workflow_metadata"]["workflow_id"] == ("media_derivative_artifact_generation")
    assert data["workflow_metadata"]["direct_wordpress_write"] is False
    assert data["site_id"] == "site-media-portal-001"
    assert {
        "account_id",
        "principal_id",
        "identity_type",
        "role",
        "allowed_actions",
        "site_admin_ref",
        "member_ref",
    }.isdisjoint(data)
    assert data["totals"]["jobs_total"] == 1
    assert data["totals"]["succeeded_total"] == 1
    assert data["totals"]["failed_total"] == 0
    assert data["totals"]["delivery_started_count"] == 2
    assert data["totals"]["delivery_stream_completed_count"] == 1
    assert data["totals"]["delivery_acknowledged_count"] == 1
    assert data["totals"]["stream_completion_rate"] == 0.5
    assert data["totals"]["acknowledgement_rate"] == 1.0
    assert "artifact_download_count" not in data["totals"]
    assert {item["site_id"] for item in data["delivery_evidence"]["by_site"]} == {
        "site-media-portal-001"
    }
    assert data["delivery_evidence"]["cms_write_evidence"] is False
    assert data["totals"]["active_artifact_count"] == 1
    assert data["formats"][0]["target_format"] == "webp"
    assert data["errors"] == []
    assert "sites" not in data
    assert "storage_key" not in str(data)


def test_portal_media_observability_rejects_other_site(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    _seed_media_metrics(database_url)

    response = client.get(
        "/portal/v1/sites/site-media-portal-002/media-observability?window_hours=24",
        headers=build_portal_headers(),
    )

    assert response.status_code == 403
    assert response.json()["status"] == "error"
