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
from app.core.models import MediaDerivativeArtifact, ProviderCallRecord, RunRecord
from app.core.services import CloudServices
from app.domain.media_derivatives.contracts import BLOCKED_RESPONSE_FIELDS, MAX_UPLOAD_BYTES_IMAGE
from app.domain.runtime.service import RuntimeService
from tests.conftest import build_auth_headers, seed_site_auth


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'media-derivative-api.sqlite3'}"


def _build_client(
    tmp_path: Path,
    *,
    runtime_queue: InMemoryRuntimeQueue | None = None,
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


def _make_png_bytes(width: int = 100, height: int = 80) -> bytes:
    img = Image.new("RGB", (width, height), color="red")
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
        assert artifact["processing_warnings"] == []
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
