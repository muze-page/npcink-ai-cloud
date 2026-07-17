from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    MediaArtifact,
    MediaArtifactDelivery,
    MediaDerivativeJobMetric,
    RunRecord,
)
from app.core.services import CloudServices
from app.domain.media_derivatives.metrics import MediaDerivativeObservabilityService
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
        policy_json=policy_json or {},
        selected_provider_id="media_processor",
        selected_model_id="pillow",
        selected_instance_id="cloud-worker",
        fallback_used=False,
        started_at=now - timedelta(seconds=5),
        processing_started_at=now - timedelta(seconds=4),
        finished_at=now,
    )


def _delivery(
    delivery_id: str,
    artifact: MediaArtifact,
    *,
    started_at: datetime,
    completed_at: datetime | None = None,
    acked_at: datetime | None = None,
    site_id: str | None = None,
) -> MediaArtifactDelivery:
    return MediaArtifactDelivery(
        delivery_id=delivery_id,
        artifact_id=artifact.artifact_id,
        site_id=site_id or artifact.site_id,
        expected_byte_size=artifact.byte_size,
        expected_checksum=artifact.checksum,
        pull_trace_id=f"trace-{delivery_id}",
        started_at=started_at,
        completed_at=completed_at,
        completed_byte_size=artifact.byte_size if completed_at is not None else None,
        completed_checksum=artifact.checksum if completed_at is not None else None,
        ack_deadline_at=started_at + timedelta(minutes=10),
        acked_at=acked_at,
        ack_idempotency_key=f"ack-{delivery_id}" if acked_at is not None else None,
        ack_request_fingerprint=("f" * 64) if acked_at is not None else None,
        ack_trace_id=f"ack-trace-{delivery_id}" if acked_at is not None else None,
        received_byte_size=artifact.byte_size if acked_at is not None else None,
        received_checksum=artifact.checksum if acked_at is not None else None,
        byte_size_verified=acked_at is not None,
        checksum_verified=acked_at is not None,
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
        artifacts = [
            MediaArtifact(
                artifact_id="art-media-001",
                run_id="run-media-001",
                site_id="site-media-001",
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
            ),
            MediaArtifact(
                artifact_id="art-media-003",
                run_id="run-media-003",
                site_id="site-media-002",
                storage_key="obj_33333333333333333333333333333333",
                media_kind="image",
                operation="image.transform.v1",
                status="available",
                content_type="image/jpeg",
                format="jpeg",
                width=200,
                height=100,
                byte_size=800,
                checksum="sha256:def",
                processing_warnings_json={"warnings": []},
                expires_at=now + timedelta(minutes=30),
                created_at=now,
            ),
            MediaArtifact(
                artifact_id="art-audio-ignored",
                run_id="run-media-001",
                site_id="site-media-001",
                storage_key="obj_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                media_kind="audio",
                operation="audio_generation",
                status="available",
                content_type="audio/mpeg",
                format="mp3",
                width=0,
                height=0,
                byte_size=9999,
                checksum="sha256:audio",
                processing_warnings_json={"warnings": []},
                expires_at=now + timedelta(minutes=30),
                created_at=now,
            ),
        ]
        session.add_all(artifacts)
        session.flush()
        artifact_by_id = {artifact.artifact_id: artifact for artifact in artifacts}
        session.add_all(
            [
                _delivery(
                    "delivery-media-001",
                    artifact_by_id["art-media-001"],
                    started_at=now - timedelta(minutes=9),
                    completed_at=now - timedelta(minutes=8),
                    acked_at=now - timedelta(minutes=7),
                ),
                _delivery(
                    "delivery-media-002",
                    artifact_by_id["art-media-001"],
                    started_at=now - timedelta(minutes=6),
                ),
                _delivery(
                    "delivery-media-003",
                    artifact_by_id["art-media-003"],
                    started_at=now - timedelta(minutes=14),
                    completed_at=now - timedelta(minutes=13),
                ),
                _delivery(
                    "delivery-audio-001",
                    artifact_by_id["art-audio-ignored"],
                    started_at=now - timedelta(minutes=4),
                    completed_at=now - timedelta(minutes=3),
                    acked_at=now - timedelta(minutes=2),
                ),
                _delivery(
                    "delivery-future-state-001",
                    artifact_by_id["art-media-003"],
                    started_at=now - timedelta(minutes=1),
                    completed_at=now + timedelta(minutes=1),
                    acked_at=now + timedelta(minutes=2),
                ),
                _delivery(
                    "delivery-future-completed-past-acked",
                    artifact_by_id["art-media-003"],
                    started_at=now - timedelta(minutes=2),
                    completed_at=now + timedelta(minutes=2),
                    acked_at=now - timedelta(minutes=1),
                ),
                _delivery(
                    "delivery-before-window",
                    artifact_by_id["art-media-003"],
                    started_at=now - timedelta(hours=25),
                ),
                _delivery(
                    "delivery-started-in-future",
                    artifact_by_id["art-media-003"],
                    started_at=now + timedelta(minutes=1),
                ),
                _delivery(
                    "delivery-cross-site-mismatch",
                    artifact_by_id["art-media-001"],
                    site_id="site-media-002",
                    started_at=now - timedelta(minutes=1),
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
        with get_session(database_url) as session:
            anomalous_delivery = session.get(
                MediaArtifactDelivery,
                "delivery-future-completed-past-acked",
            )
            assert anomalous_delivery is not None
            assert anomalous_delivery.byte_size_verified is True
            assert anomalous_delivery.checksum_verified is True
            assert (
                anomalous_delivery.received_byte_size
                == anomalous_delivery.expected_byte_size
            )
            assert anomalous_delivery.received_checksum == anomalous_delivery.expected_checksum
            assert anomalous_delivery.acked_at < anomalous_delivery.completed_at
        response = client.get(
            "/internal/service/admin/media-observability?window_hours=24",
            headers=build_internal_headers(trace_id="tracemedia0010000000000000000000"),
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["contract_version"] == "magick-media-observability-summary-v2"
        assert data["workflow_metadata"]["workflow_id"] == ("media_derivative_artifact_generation")
        assert data["workflow_metadata"]["handoff_owner"] == "wordpress_local"
        assert data["workflow_metadata"]["direct_wordpress_write"] is False
        assert data["totals"]["jobs_total"] == 3
        assert data["totals"]["succeeded_total"] == 2
        assert data["totals"]["failed_total"] == 1
        assert data["totals"]["source_bytes_total"] == 2800
        assert data["totals"]["output_bytes_total"] == 1200
        assert data["totals"]["bytes_saved_total"] == 1600
        assert data["totals"]["delivery_started_count"] == 6
        assert data["totals"]["delivery_stream_completed_count"] == 3
        assert data["totals"]["delivery_acknowledged_count"] == 2
        assert data["totals"]["stream_completion_rate"] == 0.5
        assert data["totals"]["acknowledgement_rate"] == 0.6667
        assert data["totals"]["stream_completion_rate"] <= 1
        assert data["totals"]["acknowledgement_rate"] <= 1
        assert "artifact_download_count" not in data["totals"]
        evidence = data["delivery_evidence"]
        assert evidence["evidence_scope"] == "verified_transfer_only"
        assert evidence["acknowledged_semantics"] == "verified_client_receipt"
        assert evidence["cms_write_evidence"] is False
        assert evidence["by_site_limit"] == 50
        assert evidence["by_site_truncated"] is False
        assert {item["operation"] for item in evidence["by_operation"]} == {
            "audio_generation",
            "image.transform.v1",
        }
        assert {item["site_id"] for item in evidence["by_site"]} == {
            "site-media-001",
            "site-media-002",
        }
        assert sum(item["delivery_started_count"] for item in evidence["by_date"]) == 6
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
        assert "storage_key" not in data["recent_failures"][0]
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
        assert data["totals"]["delivery_started_count"] == 2
        assert data["totals"]["delivery_stream_completed_count"] == 1
        assert data["totals"]["delivery_acknowledged_count"] == 1
        assert data["totals"]["stream_completion_rate"] == 0.5
        assert data["totals"]["acknowledgement_rate"] == 1.0
        assert {item["site_id"] for item in data["delivery_evidence"]["by_site"]} == {
            "site-media-001"
        }
        assert {item["operation"] for item in data["delivery_evidence"]["by_operation"]} == {
            "image.transform.v1"
        }
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
        assert data["totals"]["delivery_started_count"] == 0
        assert data["totals"]["stream_completion_rate"] == 0.0
        assert data["totals"]["acknowledgement_rate"] == 0.0
        assert data["totals"]["active_artifact_bytes"] == 0
        assert data["formats"] == []
        assert data["sites"] == []
        assert data["health"]["status"] == "inactive"
    finally:
        dispose_engine(database_url)


def _seed_delivery_only_rows(
    database_url: str,
    *,
    now: datetime,
    rows: list[tuple[str, datetime]],
) -> None:
    with get_session(database_url) as session:
        runs = [
            _run_record(
                f"run-delivery-only-{index:03d}",
                site_id,
                status="succeeded",
                now=now,
            )
            for index, (site_id, _) in enumerate(rows)
        ]
        session.add_all(runs)
        session.flush()
        artifacts = [
            MediaArtifact(
                artifact_id=f"art-delivery-only-{index:03d}",
                run_id=runs[index].run_id,
                site_id=site_id,
                storage_key=f"obj_delivery_only_{index:03d}",
                media_kind="image",
                operation="image.transform.v1",
                status="available",
                content_type="image/webp",
                format="webp",
                width=10,
                height=10,
                byte_size=100 + index,
                checksum=f"sha256:delivery-only-{index:03d}",
                processing_warnings_json={"warnings": []},
                expires_at=now + timedelta(hours=1),
                created_at=now,
            )
            for index, (site_id, _) in enumerate(rows)
        ]
        session.add_all(artifacts)
        session.flush()
        session.add_all(
            _delivery(
                f"delivery-only-{index:03d}",
                artifacts[index],
                started_at=started_at,
            )
            for index, (_, started_at) in enumerate(rows)
        )
        session.commit()


def test_admin_delivery_by_site_is_stably_limited_to_fifty_rows(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'media-obs-site-limit.sqlite3'}"
    init_schema(database_url)
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    site_ids = [f"site-limit-{index:03d}" for index in range(52)]
    try:
        _seed_delivery_only_rows(
            database_url,
            now=now,
            rows=[(site_id, now - timedelta(minutes=1)) for site_id in site_ids],
        )

        summary = MediaDerivativeObservabilityService(database_url).get_summary(now=now)
        evidence = summary["delivery_evidence"]

        assert isinstance(evidence, dict)
        assert evidence["by_site_limit"] == 50
        assert evidence["by_site_truncated"] is True
        assert [item["site_id"] for item in evidence["by_site"]] == site_ids[:50]
        assert all(item["delivery_started_count"] == 1 for item in evidence["by_site"])
    finally:
        dispose_engine(database_url)


def test_admin_delivery_by_date_uses_sqlite_utc_calendar_dates(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'media-obs-utc-date.sqlite3'}"
    init_schema(database_url)
    now = datetime(2026, 7, 16, 0, 30, tzinfo=UTC)
    try:
        _seed_delivery_only_rows(
            database_url,
            now=now,
            rows=[
                ("site-date-before-midnight", datetime(2026, 7, 15, 23, 59, tzinfo=UTC)),
                ("site-date-after-midnight", datetime(2026, 7, 16, 0, 1, tzinfo=UTC)),
            ],
        )

        summary = MediaDerivativeObservabilityService(database_url).get_summary(now=now)
        evidence = summary["delivery_evidence"]

        assert isinstance(evidence, dict)
        assert evidence["by_date"] == [
            {
                "date": "2026-07-15",
                "delivery_started_count": 1,
                "delivery_stream_completed_count": 0,
                "delivery_acknowledged_count": 0,
                "stream_completion_rate": 0.0,
                "acknowledgement_rate": 0.0,
            },
            {
                "date": "2026-07-16",
                "delivery_started_count": 1,
                "delivery_stream_completed_count": 0,
                "delivery_acknowledged_count": 0,
                "stream_completion_rate": 0.0,
                "acknowledgement_rate": 0.0,
            },
        ]
    finally:
        dispose_engine(database_url)
