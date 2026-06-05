from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.adapters.queue.in_memory import InMemoryRuntimeQueue
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    MediaDerivativeArtifact,
    MediaDerivativeJobMetric,
    ProviderCallRecord,
    RunRecord,
)
from app.core.services import CloudServices
from app.domain.media_derivatives.contracts import BLOCKED_RESPONSE_FIELDS, MAX_UPLOAD_BYTES_IMAGE
from app.domain.runtime.service import RuntimeService
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
    build_auth_headers,
    seed_site_auth,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'media-derivative-api.sqlite3'}"


def _build_client(
    tmp_path: Path,
    *,
    runtime_queue: InMemoryRuntimeQueue | None = None,
    settings_overrides: dict[str, object] | None = None,
) -> tuple[str, TestClient]:
    database_url = _sqlite_url(tmp_path)
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
    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        **(settings_overrides or {}),
    )
    return database_url, TestClient(
        create_app(
            CloudServices(
                settings=settings,
                providers={},
                runtime_queue=runtime_queue or InMemoryRuntimeQueue(),
            )
        )
    )


def _make_png_bytes(
    width: int = 100,
    height: int = 80,
    *,
    color: str | tuple[int, int, int, int] = "red",
    mode: str = "RGB",
) -> bytes:
    img = Image.new(mode, (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_bmp_bytes(width: int = 1200, height: int = 1200) -> bytes:
    img = Image.new("RGB", (width, height), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="BMP")
    return buf.getvalue()


def _make_animated_gif_bytes() -> bytes:
    frames = [Image.new("RGB", (10, 10), color=c) for c in ("red", "green")]
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return buf.getvalue()


def _build_multipart_body(
    request_dict: dict,
    image_bytes: bytes,
    watermark_bytes: bytes | None = None,
    boundary: str = "boundary123",
) -> tuple[bytes, str]:
    parts = []
    parts.append(f"--{boundary}".encode())
    parts.append(b'Content-Disposition: form-data; name="request"')
    parts.append(b"")
    parts.append(json.dumps(request_dict).encode())
    parts.append(f"--{boundary}".encode())
    parts.append(b'Content-Disposition: form-data; name="source_file"; filename="test.png"')
    parts.append(b"Content-Type: image/png")
    parts.append(b"")
    parts.append(image_bytes)
    if watermark_bytes is not None:
        parts.append(f"--{boundary}".encode())
        parts.append(
            b'Content-Disposition: form-data; name="watermark_file"; filename="logo.png"'
        )
        parts.append(b"Content-Type: image/png")
        parts.append(b"")
        parts.append(watermark_bytes)
    parts.append(f"--{boundary}--".encode())
    body = b"\r\n".join(parts)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


def _process_queued_runs(database_url: str) -> None:
    service = RuntimeService(
        database_url,
        settings=Settings(
            environment="test",
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
            internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
            admin_session_secret=TEST_ADMIN_SESSION_SECRET,
            portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        ),
    )
    service.process_queued_runs(max_runs=10, timeout_seconds=0)


def test_worker_success_path(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        image_bytes = _make_png_bytes(200, 160)
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 100,
                "quality": 80,
                "source_media_type": "image",
            },
            "ttl_minutes": 30,
        }
        body, content_type = _build_multipart_body(request_dict, image_bytes)
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-worker-test-001",
            nonce="nonce-worker-test-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 200, response.json()
        data = response.json()["data"]
        assert data["status"] == "queued"
        run_id = data["run_id"]

        _process_queued_runs(database_url)

        result_headers = build_auth_headers(
            "GET",
            f"/v1/runs/{run_id}/result",
            site_id="site_alpha",
        )
        result_headers["content-type"] = "application/json"
        result_response = client.get(f"/v1/runs/{run_id}/result", headers=result_headers)
        assert result_response.status_code == 200, result_response.json()
        result_data = result_response.json()["data"]
        assert result_data["status"] == "succeeded"
        artifact = result_data["result"]["artifact"]
        assert artifact["format"] == "webp"
        assert artifact["width"] == 100
        assert artifact["height"] == 80
        assert artifact["filesize_bytes"] > 0
        assert artifact["checksum"].startswith("sha256:")
        assert artifact["mime_type"] == "image/webp"
        assert artifact["suggested_filename"].endswith(".webp")
        assert artifact["suggested_filename"].startswith("media-derivative-webp-")
        assert artifact["filename_basis"]["owner"] == "wordpress_write_ability_final"
        assert artifact["processing_warnings"] == []
        with get_session(database_url) as session:
            metric = session.query(MediaDerivativeJobMetric).filter_by(run_id=run_id).one()
            assert metric.status == "succeeded"
            assert metric.target_format == "webp"
            assert metric.output_format == "webp"
            assert metric.source_bytes == len(image_bytes)
            assert metric.output_bytes == artifact["filesize_bytes"]
            assert metric.source_width == 200
            assert metric.source_height == 160
            assert metric.output_width == 100
            assert metric.output_height == 80
            assert metric.processing_duration_ms >= 0
            assert metric.artifact_id == artifact["artifact_id"]
    finally:
        dispose_engine(database_url)


def test_response_contains_no_wordpress_write_fields(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        image_bytes = _make_png_bytes(50, 50)
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 50,
                "quality": 80,
                "source_media_type": "image",
            },
        }
        body, content_type = _build_multipart_body(request_dict, image_bytes)
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-no-wp-001",
            nonce="nonce-no-wp-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 200
        response_text = json.dumps(response.json())
        for field in BLOCKED_RESPONSE_FIELDS:
            assert field not in response_text, f"blocked field '{field}' found in response"
    finally:
        dispose_engine(database_url)


def test_batch_context_response_includes_queue_pressure_and_policy(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "media_derivative_batch_default_chunk_size": 6,
            "media_derivative_batch_max_chunk_size": 12,
            "media_derivative_site_queued_limit": 20,
            "media_derivative_site_running_limit": 2,
        },
    )
    try:
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 100,
                "quality": 80,
                "source_media_type": "image",
            },
            "batch_context": {
                "batch_id": "batch-april-media",
                "item_index": 1,
                "item_count": 12,
                "chunk_size": 6,
            },
        }
        body, content_type = _build_multipart_body(
            request_dict,
            _make_png_bytes(100, 100),
            boundary="boundary-batch-context",
        )
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-batch-context-001",
            nonce="nonce-batch-context-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 200, response.json()
        data = response.json()["data"]
        assert data["batch"]["context"]["batch_id"] == "batch-april-media"
        assert data["batch"]["chunking"]["recommended_chunk_size"] == 6
        assert data["batch"]["chunking"]["max_chunk_size"] == 12
        assert data["batch"]["avif_policy"]["batch_requires_explicit_opt_in"] is True
        assert data["queue_pressure"]["queued"] == 1
        assert data["queue_pressure"]["running"] == 0
        assert data["queue_pressure"]["pressure_state"] == "healthy"
        with get_session(database_url) as session:
            run = session.get(RunRecord, data["run_id"])
            assert run is not None
            media_policy = run.policy_json["media_derivative"]
            assert media_policy["batch_context"]["batch_id"] == "batch-april-media"
            assert media_policy["limits"]["site_queued"] == 20
            assert media_policy["write_posture"] == "artifact_only"
            assert media_policy["direct_wordpress_write"] is False
    finally:
        dispose_engine(database_url)


def test_batch_avif_requires_explicit_opt_in(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "avif",
                "max_width": 100,
                "quality": 80,
                "source_media_type": "image",
            },
            "batch_context": {
                "batch_id": "batch-avif-media",
                "item_index": 1,
                "item_count": 2,
                "chunk_size": 2,
            },
        }
        body, content_type = _build_multipart_body(
            request_dict,
            _make_png_bytes(100, 100),
            boundary="boundary-batch-avif",
        )
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-batch-avif-001",
            nonce="nonce-batch-avif-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 422
        assert response.json()["error_code"] == "media_derivative.invalid_format"
    finally:
        dispose_engine(database_url)


def test_site_queue_full_rejects_new_media_derivative(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "media_derivative_site_queued_limit": 1,
            "media_derivative_site_running_limit": 1,
        },
    )
    try:
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 100,
                "quality": 80,
                "source_media_type": "image",
            },
        }
        first_body, first_content_type = _build_multipart_body(
            request_dict,
            _make_png_bytes(100, 100),
            boundary="boundary-queue-full-first",
        )
        first_headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=first_body,
            idempotency_key="idem-queue-full-001",
            nonce="nonce-queue-full-001",
        )
        first_headers["content-type"] = first_content_type
        first_response = client.post(
            "/v1/runtime/media-derivatives",
            content=first_body,
            headers=first_headers,
        )
        assert first_response.status_code == 200, first_response.json()

        second_body, second_content_type = _build_multipart_body(
            request_dict,
            _make_png_bytes(100, 100),
            boundary="boundary-queue-full-second",
        )
        second_headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=second_body,
            idempotency_key="idem-queue-full-002",
            nonce="nonce-queue-full-002",
        )
        second_headers["content-type"] = second_content_type
        second_response = client.post(
            "/v1/runtime/media-derivatives",
            content=second_body,
            headers=second_headers,
        )
        assert second_response.status_code == 429
        assert second_response.json()["error_code"] == "media_derivative.site_queue_full"
    finally:
        dispose_engine(database_url)


def test_watermark_file_success_path(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        image_bytes = _make_png_bytes(100, 100, color="white")
        watermark_bytes = _make_png_bytes(10, 10, color="red")
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "png",
                "max_width": 100,
                "quality": 80,
                "source_media_type": "image",
                "watermark": {
                    "type": "image",
                    "position": "bottom_right",
                    "opacity": 1.0,
                    "scale_percent": 20,
                    "margin_px": 0,
                },
            },
        }
        body, content_type = _build_multipart_body(
            request_dict,
            image_bytes,
            watermark_bytes=watermark_bytes,
            boundary="boundary-watermark-file",
        )
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-watermark-file-001",
            nonce="nonce-watermark-file-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 200, response.json()
        run_id = response.json()["data"]["run_id"]

        _process_queued_runs(database_url)

        result_headers = build_auth_headers(
            "GET",
            f"/v1/runs/{run_id}/result",
            site_id="site_alpha",
        )
        result_response = client.get(f"/v1/runs/{run_id}/result", headers=result_headers)
        assert result_response.status_code == 200, result_response.json()
        artifact = result_response.json()["data"]["result"]["artifact"]
        assert artifact["format"] == "png"
        artifact_id = artifact["artifact_id"]

        dl_headers = build_auth_headers(
            "GET",
            f"/v1/runtime/artifacts/{artifact_id}/download",
            site_id="site_alpha",
        )
        dl_response = client.get(
            f"/v1/runtime/artifacts/{artifact_id}/download",
            headers=dl_headers,
        )
        assert dl_response.status_code == 200
        watermarked = Image.open(io.BytesIO(dl_response.content))
        assert watermarked.getpixel((95, 95))[:3] == (255, 0, 0)
        with get_session(database_url) as session:
            metric = session.query(MediaDerivativeJobMetric).filter_by(run_id=run_id).one()
            assert metric.watermark_applied is True
            assert metric.artifact_download_count == 1
            assert metric.artifact_last_downloaded_at is not None
    finally:
        dispose_engine(database_url)


def test_text_watermark_success_path_without_watermark_artifact(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        image_bytes = _make_png_bytes(100, 100, color="white")
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "png",
                "max_width": 100,
                "quality": 80,
                "source_media_type": "image",
                "watermark": {
                    "type": "text",
                    "text": "AI",
                    "position": "top_right",
                    "opacity": 1.0,
                    "font_size": 24,
                    "color": "#000000",
                    "background": "transparent",
                    "margin_px": 0,
                },
            },
        }
        body, content_type = _build_multipart_body(
            request_dict,
            image_bytes,
            boundary="boundary-text-watermark",
        )
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-text-watermark-001",
            nonce="nonce-text-watermark-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 200, response.json()
        run_id = response.json()["data"]["run_id"]

        _process_queued_runs(database_url)

        result_headers = build_auth_headers(
            "GET",
            f"/v1/runs/{run_id}/result",
            site_id="site_alpha",
        )
        result_response = client.get(f"/v1/runs/{run_id}/result", headers=result_headers)
        assert result_response.status_code == 200, result_response.json()
        artifact = result_response.json()["data"]["result"]["artifact"]
        artifact_id = artifact["artifact_id"]

        dl_headers = build_auth_headers(
            "GET",
            f"/v1/runtime/artifacts/{artifact_id}/download",
            site_id="site_alpha",
        )
        dl_response = client.get(
            f"/v1/runtime/artifacts/{artifact_id}/download",
            headers=dl_headers,
        )
        assert dl_response.status_code == 200
        watermarked = Image.open(io.BytesIO(dl_response.content)).convert("RGB")
        top_right_pixels = [
            watermarked.getpixel((x, y))
            for x in range(50, 100)
            for y in range(0, 40)
        ]
        assert any(pixel != (255, 255, 255) for pixel in top_right_pixels)
        with get_session(database_url) as session:
            metric = session.query(MediaDerivativeJobMetric).filter_by(run_id=run_id).one()
            assert metric.watermark_applied is True
    finally:
        dispose_engine(database_url)


def test_watermark_file_and_artifact_conflict_is_rejected(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        image_bytes = _make_png_bytes(100, 100, color="white")
        watermark_bytes = _make_png_bytes(10, 10, color="red")
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "png",
                "max_width": 100,
                "quality": 80,
                "source_media_type": "image",
                "watermark": {
                    "type": "image",
                    "artifact_id": "art_conflicting_logo",
                    "position": "bottom_right",
                },
            },
        }
        body, content_type = _build_multipart_body(
            request_dict,
            image_bytes,
            watermark_bytes=watermark_bytes,
            boundary="boundary-watermark-conflict",
        )
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-watermark-conflict-001",
            nonce="nonce-watermark-conflict-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 400
        assert response.json()["error_code"] == "media_derivative.invalid_watermark"
    finally:
        dispose_engine(database_url)


def test_watermark_artifact_must_be_same_site(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        logo_request = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "png",
                "max_width": 10,
                "quality": 80,
                "source_media_type": "image",
            },
        }
        logo_body, logo_content_type = _build_multipart_body(
            logo_request,
            _make_png_bytes(10, 10, color="red"),
            boundary="boundary-watermark-artifact-logo",
        )
        logo_headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=logo_body,
            idempotency_key="idem-watermark-artifact-logo-001",
            nonce="nonce-watermark-artifact-logo-001",
        )
        logo_headers["content-type"] = logo_content_type
        logo_response = client.post(
            "/v1/runtime/media-derivatives",
            content=logo_body,
            headers=logo_headers,
        )
        assert logo_response.status_code == 200, logo_response.json()
        _process_queued_runs(database_url)

        with get_session(database_url) as session:
            artifact = session.query(MediaDerivativeArtifact).first()
            assert artifact is not None
            artifact_id = artifact.artifact_id

        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "png",
                "max_width": 100,
                "quality": 80,
                "source_media_type": "image",
                "watermark": {
                    "type": "image",
                    "artifact_id": artifact_id,
                    "position": "bottom_right",
                },
            },
        }
        body, content_type = _build_multipart_body(
            request_dict,
            _make_png_bytes(100, 100, color="white"),
            boundary="boundary-watermark-cross-site",
        )
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_beta",
            key_id="key_beta",
            body=body,
            idempotency_key="idem-watermark-cross-site-001",
            nonce="nonce-watermark-cross-site-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 404
        assert response.json()["error_code"] == "media_derivative.watermark_artifact_not_found"
    finally:
        dispose_engine(database_url)


def test_expired_watermark_artifact_is_rejected(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        logo_request = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "png",
                "max_width": 10,
                "quality": 80,
                "source_media_type": "image",
            },
        }
        logo_body, logo_content_type = _build_multipart_body(
            logo_request,
            _make_png_bytes(10, 10, color="red"),
            boundary="boundary-watermark-expired-logo",
        )
        logo_headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=logo_body,
            idempotency_key="idem-watermark-expired-logo-001",
            nonce="nonce-watermark-expired-logo-001",
        )
        logo_headers["content-type"] = logo_content_type
        logo_response = client.post(
            "/v1/runtime/media-derivatives",
            content=logo_body,
            headers=logo_headers,
        )
        assert logo_response.status_code == 200, logo_response.json()
        _process_queued_runs(database_url)

        with get_session(database_url) as session:
            artifact = session.query(MediaDerivativeArtifact).first()
            assert artifact is not None
            artifact.expires_at = datetime.now(UTC) - timedelta(minutes=1)
            session.commit()
            artifact_id = artifact.artifact_id

        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "png",
                "max_width": 100,
                "quality": 80,
                "source_media_type": "image",
                "watermark": {
                    "type": "image",
                    "artifact_id": artifact_id,
                    "position": "bottom_right",
                },
            },
        }
        body, content_type = _build_multipart_body(
            request_dict,
            _make_png_bytes(100, 100, color="white"),
            boundary="boundary-watermark-expired",
        )
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-watermark-expired-001",
            nonce="nonce-watermark-expired-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 404
        assert response.json()["error_code"] == "media_derivative.watermark_artifact_not_found"
    finally:
        dispose_engine(database_url)


def test_invalid_format_gif_returns_422(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "gif",
                "max_width": 100,
                "quality": 80,
                "source_media_type": "image",
            },
        }
        body = json.dumps(request_dict).encode()
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-gif-001",
            nonce="nonce-gif-001",
        )
        headers["content-type"] = "application/json"
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 422
        assert "invalid_format" in response.json()["error_code"]
    finally:
        dispose_engine(database_url)


def test_invalid_watermark_position_returns_422(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "png",
                "max_width": 100,
                "quality": 80,
                "source_media_type": "image",
                "watermark": {
                    "type": "image",
                    "position": "diagonal",
                    "opacity": 0.75,
                    "scale_percent": 20,
                    "margin_px": 8,
                },
            },
        }
        body, content_type = _build_multipart_body(
            request_dict,
            _make_png_bytes(100, 100),
            watermark_bytes=_make_png_bytes(10, 10),
            boundary="boundary-invalid-watermark-position",
        )
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-invalid-watermark-position-001",
            nonce="nonce-invalid-watermark-position-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 422
        assert response.json()["error_code"] == "media_derivative.invalid_watermark"
    finally:
        dispose_engine(database_url)


def test_quality_out_of_bounds_returns_422(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 100,
                "quality": 0,
                "source_media_type": "image",
            },
        }
        body, content_type = _build_multipart_body(
            request_dict,
            _make_png_bytes(100, 100),
            boundary="boundary-quality-out-of-bounds",
        )
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-quality-out-of-bounds-001",
            nonce="nonce-quality-out-of-bounds-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 422
        assert response.json()["error_code"] == "media_derivative.validation_error"
    finally:
        dispose_engine(database_url)


def test_ttl_out_of_bounds_returns_422(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 100,
                "quality": 80,
                "source_media_type": "image",
            },
            "ttl_minutes": 120,
        }
        body, content_type = _build_multipart_body(
            request_dict,
            _make_png_bytes(100, 100),
            boundary="boundary-ttl-out-of-bounds",
        )
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-ttl-out-of-bounds-001",
            nonce="nonce-ttl-out-of-bounds-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 422
        assert response.json()["error_code"] == "media_derivative.validation_error"
    finally:
        dispose_engine(database_url)


def test_valid_upload_above_default_runtime_body_limit_is_accepted(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        image_bytes = _make_bmp_bytes()
        assert len(image_bytes) > 1_048_576
        assert len(image_bytes) < MAX_UPLOAD_BYTES_IMAGE
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 100,
                "quality": 80,
                "source_media_type": "image",
            },
        }
        body, content_type = _build_multipart_body(request_dict, image_bytes)
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-large-valid-001",
            nonce="nonce-large-valid-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 200, response.json()
        assert response.json()["data"]["status"] == "queued"
    finally:
        dispose_engine(database_url)


def test_idempotency_key_conflict_returns_409(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        base_request = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 50,
                "quality": 80,
                "source_media_type": "image",
            },
        }
        first_body, first_content_type = _build_multipart_body(
            base_request,
            _make_png_bytes(50, 50),
            boundary="boundary-idem-a",
        )
        first_headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=first_body,
            idempotency_key="idem-conflict-001",
            nonce="nonce-conflict-001",
        )
        first_headers["content-type"] = first_content_type
        first_response = client.post(
            "/v1/runtime/media-derivatives",
            content=first_body,
            headers=first_headers,
        )
        assert first_response.status_code == 200, first_response.json()

        changed_request = {
            **base_request,
            "cloud_job_payload": {
                **base_request["cloud_job_payload"],
                "quality": 60,
            },
        }
        second_body, second_content_type = _build_multipart_body(
            changed_request,
            _make_png_bytes(50, 50),
            boundary="boundary-idem-b",
        )
        second_headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=second_body,
            idempotency_key="idem-conflict-001",
            nonce="nonce-conflict-002",
        )
        second_headers["content-type"] = second_content_type
        second_response = client.post(
            "/v1/runtime/media-derivatives",
            content=second_body,
            headers=second_headers,
        )
        assert second_response.status_code == 409
        assert second_response.json()["error_code"] == "runtime.idempotency_conflict"
    finally:
        dispose_engine(database_url)


def test_video_source_media_type_returns_422(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 100,
                "quality": 80,
                "source_media_type": "video",
            },
        }
        body = json.dumps(request_dict).encode()
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-video-001",
            nonce="nonce-video-001",
        )
        headers["content-type"] = "application/json"
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 422
        assert "source_media_type_unavailable" in response.json()["error_code"]
    finally:
        dispose_engine(database_url)


def test_expired_artifact_download_returns_410(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        image_bytes = _make_png_bytes(50, 50)
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "png",
                "max_width": 50,
                "quality": 80,
                "source_media_type": "image",
            },
        }
        body, content_type = _build_multipart_body(request_dict, image_bytes)
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-expire-001",
            nonce="nonce-expire-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 200
        _process_queued_runs(database_url)

        with get_session(database_url) as session:
            artifact = session.query(MediaDerivativeArtifact).first()
            assert artifact is not None
            artifact.expires_at = datetime.now(UTC) - timedelta(minutes=1)
            session.commit()
            artifact_id = artifact.artifact_id

        dl_headers = build_auth_headers(
            "GET",
            f"/v1/runtime/artifacts/{artifact_id}/download",
            site_id="site_alpha",
        )
        dl_response = client.get(
            f"/v1/runtime/artifacts/{artifact_id}/download",
            headers=dl_headers,
        )
        assert dl_response.status_code == 410
    finally:
        dispose_engine(database_url)


def test_artifact_reference_must_be_same_site(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        image_bytes = _make_png_bytes(50, 50)
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "png",
                "max_width": 50,
                "quality": 80,
                "source_media_type": "image",
            },
        }
        body, content_type = _build_multipart_body(request_dict, image_bytes)
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-cross-site-001",
            nonce="nonce-cross-site-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 200
        _process_queued_runs(database_url)

        with get_session(database_url) as session:
            artifact = session.query(MediaDerivativeArtifact).first()
            assert artifact is not None
            artifact_id = artifact.artifact_id

        ref_request = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 50,
                "quality": 80,
                "source_media_type": "image",
            },
            "source": {"artifact_id": artifact_id},
        }
        ref_body = json.dumps(ref_request).encode()
        ref_headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_beta",
            key_id="key_beta",
            body=ref_body,
            idempotency_key="idem-cross-site-002",
            nonce="nonce-cross-site-002",
        )
        ref_headers["content-type"] = "application/json"
        ref_response = client.post(
            "/v1/runtime/media-derivatives",
            content=ref_body,
            headers=ref_headers,
        )
        assert ref_response.status_code == 404
    finally:
        dispose_engine(database_url)


def test_animated_image_rejected(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        image_bytes = _make_animated_gif_bytes()
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 100,
                "quality": 80,
                "source_media_type": "image",
            },
        }
        body, content_type = _build_multipart_body(request_dict, image_bytes)
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-animated-001",
            nonce="nonce-animated-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 200
        _process_queued_runs(database_url)

        run_id = response.json()["data"]["run_id"]
        result_headers = build_auth_headers(
            "GET",
            f"/v1/runs/{run_id}/result",
            site_id="site_alpha",
        )
        result_headers["content-type"] = "application/json"
        result_response = client.get(f"/v1/runs/{run_id}/result", headers=result_headers)
        assert result_response.status_code == 200
        result_data = result_response.json()["data"]
        assert result_data["status"] == "failed"
        assert "animated_source_unavailable" in (
            result_data.get("result", {}).get("error_code") or ""
        )
        with get_session(database_url) as session:
            metric = session.query(MediaDerivativeJobMetric).filter_by(run_id=run_id).one()
            assert metric.status == "failed"
            assert metric.error_code == "media_derivative.animated_source_unavailable"
            assert metric.target_format == "webp"
            assert metric.source_bytes == len(image_bytes)
            assert metric.output_bytes == 0
    finally:
        dispose_engine(database_url)


def test_no_provider_call_record_created(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        image_bytes = _make_png_bytes(50, 50)
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 50,
                "quality": 80,
                "source_media_type": "image",
            },
        }
        body, content_type = _build_multipart_body(request_dict, image_bytes)
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-no-provider-001",
            nonce="nonce-no-provider-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 200
        _process_queued_runs(database_url)

        with get_session(database_url) as session:
            count = len(list(session.query(ProviderCallRecord).all()))
            assert count == 0
    finally:
        dispose_engine(database_url)


def test_artifact_expires_at_is_short_ttl(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        image_bytes = _make_png_bytes(50, 50)
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "png",
                "max_width": 50,
                "quality": 80,
                "source_media_type": "image",
            },
            "ttl_minutes": 20,
        }
        body, content_type = _build_multipart_body(request_dict, image_bytes)
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-ttl-001",
            nonce="nonce-ttl-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 200
        _process_queued_runs(database_url)

        with get_session(database_url) as session:
            artifact = session.query(MediaDerivativeArtifact).first()
            assert artifact is not None
            created_at = artifact.created_at
            expires_at = artifact.expires_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            delta_minutes = (expires_at - created_at).total_seconds() / 60
            assert 15 <= delta_minutes <= 60
    finally:
        dispose_engine(database_url)


def test_oversized_upload_returns_413(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        oversized_bytes = b"\x00" * (MAX_UPLOAD_BYTES_IMAGE + 1)
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 100,
                "quality": 80,
                "source_media_type": "image",
            },
        }
        body, content_type = _build_multipart_body(request_dict, oversized_bytes)
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-oversized-001",
            nonce="nonce-oversized-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 413
        assert response.json()["error_code"] == "media_derivative.upload_too_large"
    finally:
        dispose_engine(database_url)


def test_purged_artifact_reference_is_rejected(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        image_bytes = _make_png_bytes(50, 50)
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "png",
                "max_width": 50,
                "quality": 80,
                "source_media_type": "image",
            },
        }
        body, content_type = _build_multipart_body(request_dict, image_bytes)
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-purged-001",
            nonce="nonce-purged-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 200
        _process_queued_runs(database_url)

        with get_session(database_url) as session:
            artifact = session.query(MediaDerivativeArtifact).first()
            assert artifact is not None
            artifact.purged_at = datetime.now(UTC)
            session.commit()
            artifact_id = artifact.artifact_id

        ref_request = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 50,
                "quality": 80,
                "source_media_type": "image",
            },
            "source": {"artifact_id": artifact_id},
        }
        ref_body = json.dumps(ref_request).encode()
        ref_headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=ref_body,
            idempotency_key="idem-purged-002",
            nonce="nonce-purged-002",
        )
        ref_headers["content-type"] = "application/json"
        ref_response = client.post(
            "/v1/runtime/media-derivatives",
            content=ref_body,
            headers=ref_headers,
        )
        assert ref_response.status_code == 404
    finally:
        dispose_engine(database_url)


def test_endpoint_bypasses_model_routing(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    try:
        image_bytes = _make_png_bytes(50, 50)
        request_dict = {
            "request_contract_version": "media_derivative_cloud_request.v1",
            "cloud_job_payload": {
                "job_type": "generate_optimized_media_derivative",
                "target_format": "webp",
                "max_width": 50,
                "quality": 80,
                "source_media_type": "image",
            },
        }
        body, content_type = _build_multipart_body(request_dict, image_bytes)
        headers = build_auth_headers(
            "POST",
            "/v1/runtime/media-derivatives",
            site_id="site_alpha",
            body=body,
            idempotency_key="idem-no-routing-001",
            nonce="nonce-no-routing-001",
        )
        headers["content-type"] = content_type
        response = client.post("/v1/runtime/media-derivatives", content=body, headers=headers)
        assert response.status_code == 200
        run_id = response.json()["data"]["run_id"]

        with get_session(database_url) as session:
            run = session.get(RunRecord, run_id)
            assert run is not None
            assert run.execution_kind == "media_derivative"
            assert run.selected_provider_id == "media_derivative"
            assert run.selected_model_id == "pillow"
    finally:
        dispose_engine(database_url)
