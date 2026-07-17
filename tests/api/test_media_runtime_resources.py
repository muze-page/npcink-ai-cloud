from __future__ import annotations

import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.adapters.queue.in_memory import InMemoryRuntimeQueue
from app.api.main import create_app
from app.api.routes import media_derivatives as media_routes
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    MediaArtifact,
    MediaArtifactDelivery,
    ProviderCallRecord,
    ReplayReceipt,
    RunRecord,
    RuntimeGuardEvent,
)
from app.core.secrets import decrypt_runtime_execution_input
from app.core.services import CloudServices
from app.domain.media_artifacts import build_artifact_store
from app.domain.media_artifacts import delivery as delivery_module
from app.domain.media_artifacts.delivery import (
    MEDIA_ARTIFACT_MIN_PULL_WINDOW_SECONDS,
    MediaArtifactDeliveryWindowUnavailableError,
    MediaArtifactExpiredError,
    iter_verified_delivery_chunks,
    prepare_media_artifact_delivery,
)
from app.domain.media_artifacts.lifecycle import MediaArtifactLifecycleService
from app.domain.media_artifacts.publication import (
    ArtifactPublicationCleanupUncertainError,
)
from app.domain.media_artifacts.store import ArtifactStorageMetadata
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


def _download_path(artifact_id: str) -> str:
    return f"/v1/runtime/media/artifacts/{artifact_id}/download"


def _ack_path(artifact_id: str) -> str:
    return f"/v1/runtime/media/artifacts/{artifact_id}/delivery-ack"


def _pull_headers(
    artifact_id: str,
    *,
    nonce: str = "",
    site_id: str = "site_alpha",
    key_id: str = TEST_KEY_ID,
    query: str = "",
    idempotency_key: str = "",
) -> dict[str, str]:
    return build_auth_headers(
        "GET",
        _download_path(artifact_id),
        site_id=site_id,
        key_id=key_id,
        nonce=nonce,
        query=query,
        idempotency_key=idempotency_key,
    )


def _ack_headers(
    artifact_id: str,
    payload: dict[str, object],
    *,
    key: str,
    nonce: str,
    query: str = "",
    site_id: str = "site_alpha",
    key_id: str = TEST_KEY_ID,
) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = build_auth_headers(
        "POST",
        _ack_path(artifact_id),
        site_id=site_id,
        key_id=key_id,
        body=body,
        nonce=nonce,
        idempotency_key=key,
        query=query,
    )
    headers["content-type"] = "application/json"
    return body, headers


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


def test_upload_publication_cleanup_uncertain_remains_storage_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, _, _, client = _client(tmp_path)

    def fail_cleanup(self: RuntimeService, **kwargs: object) -> object:
        del self, kwargs
        raise ArtifactPublicationCleanupUncertainError(
            ("obj_00000000000000000000000000000011",)
        )

    monkeypatch.setattr(RuntimeService, "create_media_upload", fail_cleanup)
    try:
        response = _upload(
            client,
            _png(),
            key="upload-cleanup-uncertain",
            nonce="upload-cleanup-uncertain",
        )

        assert response.status_code == 503
        assert response.json()["error_code"] == "media_upload.storage_unavailable"
    finally:
        dispose_engine(database_url)


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


@pytest.mark.parametrize(
    ("remaining", "allowed"),
    [
        (
            timedelta(seconds=MEDIA_ARTIFACT_MIN_PULL_WINDOW_SECONDS) - timedelta(microseconds=1),
            False,
        ),
        (timedelta(seconds=MEDIA_ARTIFACT_MIN_PULL_WINDOW_SECONDS), False),
        (
            timedelta(seconds=MEDIA_ARTIFACT_MIN_PULL_WINDOW_SECONDS) + timedelta(microseconds=1),
            True,
        ),
    ],
)
def test_prepare_delivery_enforces_exact_minimum_pull_window_without_store_access(
    tmp_path: Path,
    remaining: timedelta,
    allowed: bool,
) -> None:
    database_url, _, _, client = _client(tmp_path)
    payload = _png()
    now = datetime(2026, 7, 15, 13, 0, tzinfo=UTC)
    try:
        artifact_id = _artifact_id(
            _upload(
                client, payload, key=f"pull-window-{remaining}", nonce=f"pull-window-{remaining}"
            )
        )
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            assert artifact is not None
            artifact.expires_at = now + remaining
            storage_key = artifact.storage_key
            checksum = artifact.checksum
            byte_size = artifact.byte_size
            session.commit()

        class CountingPreparedStore:
            chunk_size = 64 * 1024

            def __init__(self) -> None:
                self.metadata_calls = 0
                self.open_calls = 0

            def metadata(self, requested_key: str) -> ArtifactStorageMetadata:
                self.metadata_calls += 1
                return ArtifactStorageMetadata(requested_key, byte_size, checksum)

            def open(self, requested_key: str) -> io.BytesIO:
                assert requested_key == storage_key
                self.open_calls += 1
                return io.BytesIO(payload)

        store = CountingPreparedStore()
        with get_session(database_url) as session:
            if not allowed:
                with pytest.raises(MediaArtifactDeliveryWindowUnavailableError):
                    prepare_media_artifact_delivery(
                        session=session,
                        artifact_store=store,  # type: ignore[arg-type]
                        artifact_id=artifact_id,
                        site_id="site_alpha",
                        trace_id="trace-pull-window",
                        now=now,
                    )
                assert store.metadata_calls == 0
                assert store.open_calls == 0
            else:
                prepared = prepare_media_artifact_delivery(
                    session=session,
                    artifact_store=store,  # type: ignore[arg-type]
                    artifact_id=artifact_id,
                    site_id="site_alpha",
                    trace_id="trace-pull-window",
                    now=now,
                )
                assert prepared.delivery.ack_deadline_at == now + remaining
                assert store.metadata_calls == 1
                assert store.open_calls == 1
                prepared.stream.close()
                session.commit()

        with get_session(database_url) as session:
            deliveries = list(
                session.scalars(
                    select(MediaArtifactDelivery).where(
                        MediaArtifactDelivery.artifact_id == artifact_id
                    )
                )
            )
        assert len(deliveries) == (1 if allowed else 0)
    finally:
        dispose_engine(database_url)


@pytest.mark.parametrize(
    ("final_advance", "error_type"),
    [
        (timedelta(seconds=1), MediaArtifactDeliveryWindowUnavailableError),
        (timedelta(seconds=302), delivery_module.MediaArtifactExpiredError),
    ],
)
def test_prepare_delivery_rechecks_time_after_store_open_and_closes_crossed_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    final_advance: timedelta,
    error_type: type[Exception],
) -> None:
    database_url, _, _, client = _client(tmp_path)
    payload = _png()
    initial_time = datetime(2026, 7, 15, 13, 0, tzinfo=UTC)
    try:
        artifact_id = _artifact_id(
            _upload(client, payload, key=f"slow-pull-{final_advance}", nonce="slow-pull")
        )
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            assert artifact is not None
            artifact.expires_at = initial_time + timedelta(seconds=301)
            storage_key = artifact.storage_key
            checksum = artifact.checksum
            byte_size = artifact.byte_size
            session.commit()

        class TrackingStream(io.BytesIO):
            closed_by_cleanup = False

            def close(self) -> None:
                self.closed_by_cleanup = True
                super().close()

        class ControlledSlowStore:
            chunk_size = 64 * 1024

            def __init__(self) -> None:
                self.stream = TrackingStream(payload)

            def metadata(self, requested_key: str) -> ArtifactStorageMetadata:
                assert requested_key == storage_key
                return ArtifactStorageMetadata(requested_key, byte_size, checksum)

            def open(self, requested_key: str) -> TrackingStream:
                assert requested_key == storage_key
                return self.stream

        clock_values = iter((initial_time, initial_time + final_advance))
        monkeypatch.setattr(delivery_module, "_delivery_clock_now", lambda: next(clock_values))
        store = ControlledSlowStore()
        with get_session(database_url) as session:
            with pytest.raises(error_type):
                prepare_media_artifact_delivery(
                    session=session,
                    artifact_store=store,  # type: ignore[arg-type]
                    artifact_id=artifact_id,
                    site_id="site_alpha",
                    trace_id="trace-slow-pull",
                )
            assert store.stream.closed_by_cleanup is True
            assert not session.new

        with get_session(database_url) as session:
            assert session.scalar(
                select(MediaArtifactDelivery).where(
                    MediaArtifactDelivery.artifact_id == artifact_id
                )
            ) is None
    finally:
        dispose_engine(database_url)


@pytest.mark.parametrize(
    ("final_advance", "error_type"),
    [
        (timedelta(seconds=1), MediaArtifactDeliveryWindowUnavailableError),
        (timedelta(seconds=302), delivery_module.MediaArtifactExpiredError),
    ],
)
def test_prepare_delivery_rechecks_time_after_flush_and_rolls_back_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    final_advance: timedelta,
    error_type: type[Exception],
) -> None:
    database_url, _, _, client = _client(tmp_path)
    payload = _png()
    initial_time = datetime(2026, 7, 15, 13, 0, tzinfo=UTC)
    try:
        artifact_id = _artifact_id(
            _upload(client, payload, key=f"flush-window-{final_advance}", nonce="flush-window")
        )
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            assert artifact is not None
            artifact.expires_at = initial_time + timedelta(seconds=301)
            storage_key = artifact.storage_key
            checksum = artifact.checksum
            byte_size = artifact.byte_size
            session.commit()

        class TrackingStream(io.BytesIO):
            closed_by_cleanup = False

            def close(self) -> None:
                self.closed_by_cleanup = True
                super().close()

        class ControlledFlushStore:
            chunk_size = 64 * 1024

            def __init__(self) -> None:
                self.stream = TrackingStream(payload)

            def metadata(self, requested_key: str) -> ArtifactStorageMetadata:
                assert requested_key == storage_key
                return ArtifactStorageMetadata(requested_key, byte_size, checksum)

            def open(self, requested_key: str) -> TrackingStream:
                assert requested_key == storage_key
                return self.stream

        clock_values = iter((initial_time, initial_time, initial_time + final_advance))
        monkeypatch.setattr(delivery_module, "_delivery_clock_now", lambda: next(clock_values))
        store = ControlledFlushStore()
        with get_session(database_url) as session:
            with pytest.raises(error_type):
                prepare_media_artifact_delivery(
                    session=session,
                    artifact_store=store,  # type: ignore[arg-type]
                    artifact_id=artifact_id,
                    site_id="site_alpha",
                    trace_id="trace-flush-window",
                )
            assert store.stream.closed_by_cleanup is True
            assert not session.new

        with get_session(database_url) as session:
            assert session.scalar(
                select(MediaArtifactDelivery).where(
                    MediaArtifactDelivery.artifact_id == artifact_id
                )
            ) is None
    finally:
        dispose_engine(database_url)


def test_prepare_delivery_uses_last_precommit_time_for_started_at_and_ack_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, settings, _, client = _client(tmp_path)
    initial_time = datetime(2026, 7, 15, 13, 0, tzinfo=UTC)
    post_open_time = initial_time + timedelta(seconds=7)
    precommit_time = initial_time + timedelta(seconds=11)
    try:
        artifact_id = _artifact_id(
            _upload(client, _png(), key="pull-final-time", nonce="pull-final-time")
        )
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            assert artifact is not None
            artifact.expires_at = initial_time + timedelta(seconds=1000)
            session.commit()

        clock_values = iter((initial_time, post_open_time, precommit_time))
        monkeypatch.setattr(delivery_module, "_delivery_clock_now", lambda: next(clock_values))
        with get_session(database_url) as session:
            prepared = prepare_media_artifact_delivery(
                session=session,
                artifact_store=build_artifact_store(settings),
                artifact_id=artifact_id,
                site_id="site_alpha",
                trace_id="trace-pull-final-time",
            )
            assert prepared.delivery.started_at == precommit_time
            assert prepared.delivery.ack_deadline_at == precommit_time + timedelta(minutes=15)
            prepared.stream.close()
    finally:
        dispose_engine(database_url)


def test_prepare_delivery_flush_cleanup_preserves_primary_error_when_close_interrupts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, _, _, client = _client(tmp_path)
    payload = _png()
    now = datetime(2026, 7, 15, 13, 0, tzinfo=UTC)
    primary_error = RuntimeError("primary flush failure")
    try:
        artifact_id = _artifact_id(
            _upload(client, payload, key="flush-cleanup", nonce="flush-cleanup")
        )
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            assert artifact is not None
            artifact.expires_at = now + timedelta(hours=1)
            storage_key = artifact.storage_key
            checksum = artifact.checksum
            byte_size = artifact.byte_size
            session.commit()

        class InterruptingCloseStream(io.BytesIO):
            close_attempted = False

            def close(self) -> None:
                self.close_attempted = True
                raise KeyboardInterrupt("secondary close interrupt")

        class FlushFailureStore:
            chunk_size = 64 * 1024

            def __init__(self) -> None:
                self.stream = InterruptingCloseStream(payload)

            def metadata(self, requested_key: str) -> ArtifactStorageMetadata:
                return ArtifactStorageMetadata(requested_key, byte_size, checksum)

            def open(self, requested_key: str) -> InterruptingCloseStream:
                assert requested_key == storage_key
                return self.stream

        store = FlushFailureStore()
        with get_session(database_url) as session:
            def fail_flush() -> None:
                raise primary_error

            monkeypatch.setattr(session, "flush", fail_flush)
            with pytest.raises(RuntimeError) as captured:
                prepare_media_artifact_delivery(
                    session=session,
                    artifact_store=store,  # type: ignore[arg-type]
                    artifact_id=artifact_id,
                    site_id="site_alpha",
                    trace_id="trace-flush-cleanup",
                    now=now,
                )
            assert captured.value is primary_error
            assert store.stream.close_attempted is True
    finally:
        dispose_engine(database_url)


@pytest.mark.parametrize("primary_error", [RuntimeError("commit failed"), KeyboardInterrupt()])
@pytest.mark.parametrize(
    "exit_error",
    [RuntimeError("secondary session exit failure"), KeyboardInterrupt("secondary exit")],
)
def test_prepare_signed_delivery_commit_cleanup_preserves_primary_base_exception(
    monkeypatch: pytest.MonkeyPatch,
    primary_error: BaseException,
    exit_error: BaseException,
) -> None:
    class CommitFailingSession:
        def commit(self) -> None:
            raise primary_error

    class InterruptingCloseStream:
        close_attempted = False

        def close(self) -> None:
            self.close_attempted = True
            raise KeyboardInterrupt("secondary close interrupt")

    session = CommitFailingSession()
    stream = InterruptingCloseStream()
    prepared = SimpleNamespace(stream=stream)

    @contextmanager
    def fake_get_session(_database_url: str) -> Any:
        try:
            yield session
        finally:
            raise exit_error

    monkeypatch.setattr(media_routes, "get_session", fake_get_session)
    monkeypatch.setattr(
        media_routes,
        "prepare_media_artifact_delivery",
        lambda **_kwargs: prepared,
    )

    with pytest.raises(type(primary_error)) as captured:
        media_routes._prepare_signed_delivery(
            database_url="sqlite+pysqlite:///:memory:",
            artifact_store=object(),
            artifact_id="art_commit_failure",
            site_id="site_alpha",
            trace_id="trace-commit-failure",
        )

    assert captured.value is primary_error
    assert stream.close_attempted is True


@pytest.mark.parametrize(
    "compensation_error",
    [RuntimeError("secondary compensation failure"), KeyboardInterrupt("secondary interrupt")],
)
def test_prepare_signed_delivery_postcommit_failure_closes_before_compensation_without_masking(
    monkeypatch: pytest.MonkeyPatch,
    compensation_error: BaseException,
) -> None:
    class SuccessfulSession:
        def commit(self) -> None:
            return None

    class InterruptingCloseStream:
        close_attempted = False

        def close(self) -> None:
            self.close_attempted = True
            raise KeyboardInterrupt("secondary close interrupt")

    primary_error = delivery_module.MediaArtifactDeliveryWindowUnavailableError(
        "media artifact delivery window is unavailable"
    )
    session = SuccessfulSession()
    stream = InterruptingCloseStream()
    prepared = SimpleNamespace(
        stream=stream,
        artifact=SimpleNamespace(artifact_id="art_postcommit", site_id="site_alpha"),
        delivery=SimpleNamespace(delivery_id="mdl_postcommit"),
    )

    @contextmanager
    def fake_get_session(_database_url: str) -> Any:
        yield session

    def fail_revalidation(**_kwargs: Any) -> None:
        raise primary_error

    def fail_compensation(**_kwargs: Any) -> None:
        assert stream.close_attempted is True
        raise compensation_error

    monkeypatch.setattr(media_routes, "get_session", fake_get_session)
    monkeypatch.setattr(
        media_routes,
        "prepare_media_artifact_delivery",
        lambda **_kwargs: prepared,
    )
    monkeypatch.setattr(
        media_routes,
        "revalidate_committed_media_artifact_delivery",
        fail_revalidation,
    )
    monkeypatch.setattr(
        media_routes,
        "discard_pristine_media_artifact_delivery_best_effort",
        fail_compensation,
    )

    with pytest.raises(delivery_module.MediaArtifactDeliveryWindowUnavailableError) as captured:
        media_routes._prepare_signed_delivery(
            database_url="sqlite+pysqlite:///:memory:",
            artifact_store=object(),
            artifact_id="art_postcommit",
            site_id="site_alpha",
            trace_id="trace-postcommit",
        )

    assert captured.value is primary_error
    assert stream.close_attempted is True


@pytest.mark.parametrize(
    ("artifact_ttl", "final_advance", "error_type"),
    [
        (
            timedelta(seconds=301),
            timedelta(seconds=1),
            MediaArtifactDeliveryWindowUnavailableError,
        ),
        (
            timedelta(seconds=301),
            timedelta(seconds=302),
            delivery_module.MediaArtifactExpiredError,
        ),
        (
            timedelta(hours=1),
            timedelta(minutes=10),
            MediaArtifactDeliveryWindowUnavailableError,
        ),
    ],
)
def test_prepare_signed_delivery_revalidates_after_commit_and_deletes_crossed_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_ttl: timedelta,
    final_advance: timedelta,
    error_type: type[Exception],
) -> None:
    database_url, _, _, client = _client(tmp_path)
    payload = _png()
    initial_time = datetime(2026, 7, 15, 13, 0, tzinfo=UTC)
    try:
        artifact_id = _artifact_id(
            _upload(client, payload, key=f"commit-window-{final_advance}", nonce="commit-window")
        )
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            assert artifact is not None
            artifact.expires_at = initial_time + artifact_ttl
            storage_key = artifact.storage_key
            checksum = artifact.checksum
            byte_size = artifact.byte_size
            session.commit()

        class TrackingStream(io.BytesIO):
            closed_by_cleanup = False

            def close(self) -> None:
                self.closed_by_cleanup = True
                super().close()

        class ControlledCommitStore:
            chunk_size = 64 * 1024

            def __init__(self) -> None:
                self.stream = TrackingStream(payload)

            def metadata(self, requested_key: str) -> ArtifactStorageMetadata:
                assert requested_key == storage_key
                return ArtifactStorageMetadata(requested_key, byte_size, checksum)

            def open(self, requested_key: str) -> TrackingStream:
                assert requested_key == storage_key
                return self.stream

        clock_values = iter(
            (
                initial_time,
                initial_time,
                initial_time,
                initial_time + final_advance,
                initial_time + final_advance,
            )
        )
        monkeypatch.setattr(delivery_module, "_delivery_clock_now", lambda: next(clock_values))
        store = ControlledCommitStore()
        with pytest.raises(error_type):
            media_routes._prepare_signed_delivery(
                database_url=database_url,
                artifact_store=store,
                artifact_id=artifact_id,
                site_id="site_alpha",
                trace_id="trace-commit-window",
            )

        assert store.stream.closed_by_cleanup is True
        with get_session(database_url) as session:
            assert session.scalar(
                select(MediaArtifactDelivery).where(
                    MediaArtifactDelivery.artifact_id == artifact_id
                )
            ) is None
    finally:
        dispose_engine(database_url)


@pytest.mark.parametrize("advancing_exit", ["preparation", "revalidation"])
def test_prepare_signed_delivery_final_clock_runs_after_both_session_exits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    advancing_exit: str,
) -> None:
    database_url, _, _, client = _client(tmp_path)
    payload = _png()
    initial_time = datetime(2026, 7, 15, 13, 0, tzinfo=UTC)
    current_time = {"value": initial_time}
    try:
        artifact_id = _artifact_id(
            _upload(
                client,
                payload,
                key=f"session-exit-window-{advancing_exit}",
                nonce=f"session-exit-window-{advancing_exit}",
            )
        )
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            assert artifact is not None
            artifact.expires_at = initial_time + timedelta(seconds=301)
            storage_key = artifact.storage_key
            checksum = artifact.checksum
            byte_size = artifact.byte_size
            session.commit()

        class TrackingStream(io.BytesIO):
            closed_by_cleanup = False

            def close(self) -> None:
                self.closed_by_cleanup = True
                super().close()

        class ControlledStore:
            chunk_size = 64 * 1024

            def __init__(self) -> None:
                self.stream = TrackingStream(payload)

            def metadata(self, requested_key: str) -> ArtifactStorageMetadata:
                assert requested_key == storage_key
                return ArtifactStorageMetadata(requested_key, byte_size, checksum)

            def open(self, requested_key: str) -> TrackingStream:
                assert requested_key == storage_key
                return self.stream

        real_route_get_session = media_routes.get_session
        real_delivery_get_session = delivery_module.get_session

        @contextmanager
        def advance_after_route_session(database: str) -> Any:
            with real_route_get_session(database) as session:
                yield session
            current_time["value"] = initial_time + timedelta(seconds=1)

        @contextmanager
        def advance_after_revalidation_session(database: str) -> Any:
            with real_delivery_get_session(database) as session:
                yield session
            current_time["value"] = initial_time + timedelta(seconds=1)

        if advancing_exit == "preparation":
            monkeypatch.setattr(media_routes, "get_session", advance_after_route_session)
        else:
            monkeypatch.setattr(
                delivery_module,
                "get_session",
                advance_after_revalidation_session,
            )
        monkeypatch.setattr(
            delivery_module,
            "_delivery_clock_now",
            lambda: current_time["value"],
        )
        store = ControlledStore()

        with pytest.raises(MediaArtifactDeliveryWindowUnavailableError):
            media_routes._prepare_signed_delivery(
                database_url=database_url,
                artifact_store=store,
                artifact_id=artifact_id,
                site_id="site_alpha",
                trace_id=f"trace-session-exit-{advancing_exit}",
            )

        assert store.stream.closed_by_cleanup is True
        with get_session(database_url) as session:
            assert session.scalar(
                select(MediaArtifactDelivery).where(
                    MediaArtifactDelivery.artifact_id == artifact_id
                )
            ) is None
    finally:
        dispose_engine(database_url)


def test_prepare_signed_delivery_allows_valid_postcommit_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, settings, _, client = _client(tmp_path)
    initial_time = datetime(2026, 7, 15, 13, 0, tzinfo=UTC)
    try:
        artifact_id = _artifact_id(
            _upload(client, _png(), key="commit-window-valid", nonce="commit-window-valid")
        )
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            assert artifact is not None
            artifact.expires_at = initial_time + timedelta(hours=2)
            session.commit()

        clock_values = iter((initial_time,) * 5)
        monkeypatch.setattr(delivery_module, "_delivery_clock_now", lambda: next(clock_values))
        prepared = media_routes._prepare_signed_delivery(
            database_url=database_url,
            artifact_store=build_artifact_store(settings),
            artifact_id=artifact_id,
            site_id="site_alpha",
            trace_id="trace-commit-window-valid",
        )
        prepared.stream.close()

        with get_session(database_url) as session:
            delivery = session.get(MediaArtifactDelivery, prepared.delivery.delivery_id)
            assert delivery is not None
            assert delivery.revoked_at is None
    finally:
        dispose_engine(database_url)


@pytest.mark.parametrize("terminal_field", ["completed_at", "acked_at", "revoked_at"])
def test_postcommit_gate_never_deletes_terminal_delivery(
    monkeypatch: pytest.MonkeyPatch,
    terminal_field: str,
) -> None:
    now = datetime(2026, 7, 15, 13, 0, tzinfo=UTC)
    artifact = SimpleNamespace(
        status="available",
        purged_at=None,
        expires_at=now + timedelta(hours=1),
    )
    delivery = SimpleNamespace(
        revoked_at=None,
        completed_at=None,
        acked_at=None,
        ack_deadline_at=now + timedelta(minutes=15),
    )
    setattr(delivery, terminal_field, now)

    class TrackingSession:
        def __init__(self) -> None:
            self.values = iter((artifact, delivery))
            self.delete_called = False
            self.commit_called = False

        def scalar(self, _statement: Any) -> Any:
            return next(self.values)

        def delete(self, _value: Any) -> None:
            self.delete_called = True

        def commit(self) -> None:
            self.commit_called = True

    session = TrackingSession()

    @contextmanager
    def fake_get_session(_database_url: str) -> Any:
        yield session

    monkeypatch.setattr(delivery_module, "get_session", fake_get_session)
    with pytest.raises(delivery_module.MediaArtifactNotAvailableError):
        delivery_module.revalidate_committed_media_artifact_delivery(
            database_url="sqlite+pysqlite:///:memory:",
            artifact_id="art_terminal",
            site_id="site_alpha",
            delivery_id="mdl_terminal",
            now=now,
        )

    assert session.delete_called is False
    assert session.commit_called is False


@pytest.mark.parametrize(
    "exit_error",
    [RuntimeError("secondary snapshot exit"), KeyboardInterrupt("secondary snapshot interrupt")],
)
def test_postcommit_gate_prioritizes_purge_snapshot_over_exit_and_retains_delivery(
    monkeypatch: pytest.MonkeyPatch,
    exit_error: BaseException,
) -> None:
    now = datetime(2026, 7, 15, 13, 0, tzinfo=UTC)
    artifact = SimpleNamespace(
        status="purge_pending",
        purged_at=None,
        expires_at=now + timedelta(hours=1),
    )
    delivery = SimpleNamespace(
        revoked_at=now,
        completed_at=None,
        acked_at=None,
        ack_deadline_at=now + timedelta(minutes=15),
    )

    class SuccessfulPreparationSession:
        def commit(self) -> None:
            return None

    class TrackingDeliverySession:
        def __init__(self) -> None:
            self.values = iter((artifact, delivery))
            self.delete_called = False
            self.commit_called = False

        def scalar(self, _statement: Any) -> Any:
            return next(self.values)

        def delete(self, _value: Any) -> None:
            self.delete_called = True

        def commit(self) -> None:
            self.commit_called = True

    class TrackingStream:
        close_attempted = False

        def close(self) -> None:
            self.close_attempted = True

    stream = TrackingStream()
    prepared = SimpleNamespace(
        stream=stream,
        artifact=SimpleNamespace(artifact_id="art_purge_race", site_id="site_alpha"),
        delivery=SimpleNamespace(delivery_id="mdl_purge_race"),
    )
    sessions: list[TrackingDeliverySession] = []

    @contextmanager
    def fake_preparation_session(_database_url: str) -> Any:
        yield SuccessfulPreparationSession()

    @contextmanager
    def fake_delivery_session(_database_url: str) -> Any:
        session = TrackingDeliverySession()
        sessions.append(session)
        if len(sessions) == 2:
            assert stream.close_attempted is True
        try:
            yield session
        finally:
            raise exit_error

    monkeypatch.setattr(media_routes, "get_session", fake_preparation_session)
    monkeypatch.setattr(
        media_routes,
        "prepare_media_artifact_delivery",
        lambda **_kwargs: prepared,
    )
    monkeypatch.setattr(delivery_module, "get_session", fake_delivery_session)
    with pytest.raises(delivery_module.MediaArtifactExpiredError) as captured:
        media_routes._prepare_signed_delivery(
            database_url="sqlite+pysqlite:///:memory:",
            artifact_store=object(),
            artifact_id="art_purge_race",
            site_id="site_alpha",
            trace_id="trace-purge-race",
        )

    assert str(captured.value) == "media artifact has expired"
    assert stream.close_attempted is True
    assert len(sessions) == 2
    assert all(session.delete_called is False for session in sessions)
    assert all(session.commit_called is False for session in sessions)


@pytest.mark.parametrize(
    ("exit_error", "expected_error_type"),
    [
        (
            RuntimeError("valid snapshot exit failure"),
            delivery_module.MediaArtifactNotAvailableError,
        ),
        (KeyboardInterrupt("valid snapshot exit interrupt"), KeyboardInterrupt),
    ],
)
def test_valid_postcommit_snapshot_propagates_exit_failure_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    exit_error: BaseException,
    expected_error_type: type[BaseException],
) -> None:
    now = datetime(2026, 7, 15, 13, 0, tzinfo=UTC)
    artifact = SimpleNamespace(
        status="available",
        purged_at=None,
        expires_at=now + timedelta(hours=1),
    )
    delivery = SimpleNamespace(
        revoked_at=None,
        completed_at=None,
        acked_at=None,
        ack_deadline_at=now + timedelta(minutes=15),
    )

    class SnapshotSession:
        def __init__(self) -> None:
            self.values = iter((artifact, delivery))

        def scalar(self, _statement: Any) -> Any:
            return next(self.values)

    @contextmanager
    def failing_exit_session(_database_url: str) -> Any:
        try:
            yield SnapshotSession()
        finally:
            raise exit_error

    monkeypatch.setattr(delivery_module, "get_session", failing_exit_session)
    with pytest.raises(expected_error_type) as captured:
        delivery_module.revalidate_committed_media_artifact_delivery(
            database_url="sqlite+pysqlite:///:memory:",
            artifact_id="art_valid_snapshot",
            site_id="site_alpha",
            delivery_id="mdl_valid_snapshot",
            now=now,
        )

    if isinstance(exit_error, KeyboardInterrupt):
        assert captured.value is exit_error
    else:
        assert str(captured.value) == "media artifact delivery is not available"


def test_postcommit_snapshot_query_base_exception_wins_over_exit_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary_error = KeyboardInterrupt("primary snapshot query interrupt")

    class QueryFailingSession:
        def scalar(self, _statement: Any) -> Any:
            raise primary_error

    @contextmanager
    def query_and_exit_failing_session(_database_url: str) -> Any:
        try:
            yield QueryFailingSession()
        finally:
            raise SystemExit("secondary snapshot exit")

    monkeypatch.setattr(
        delivery_module,
        "get_session",
        query_and_exit_failing_session,
    )
    with pytest.raises(KeyboardInterrupt) as captured:
        delivery_module.revalidate_committed_media_artifact_delivery(
            database_url="sqlite+pysqlite:///:memory:",
            artifact_id="art_query_failure",
            site_id="site_alpha",
            delivery_id="mdl_query_failure",
        )

    assert captured.value is primary_error


def test_signed_pull_maps_insufficient_delivery_window_to_stable_public_error(
    tmp_path: Path,
) -> None:
    database_url, _, _, client = _client(tmp_path)
    try:
        artifact_id = _artifact_id(
            _upload(client, _png(), key="pull-window-api", nonce="pull-window-api")
        )
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            assert artifact is not None
            storage_key = artifact.storage_key
            artifact.expires_at = datetime.now(UTC) + timedelta(minutes=4)
            session.commit()

        response = client.get(
            _download_path(artifact_id),
            headers=_pull_headers(artifact_id, nonce="pull-window-api-download"),
        )

        assert response.status_code == 409, response.json()
        assert response.json()["error_code"] == ("media_artifact.delivery_window_unavailable")
        assert response.json()["data"] == {}
        assert storage_key not in response.text
        assert "retry-after" not in response.headers
        with get_session(database_url) as session:
            assert (
                session.scalar(
                    select(MediaArtifactDelivery).where(
                        MediaArtifactDelivery.artifact_id == artifact_id
                    )
                )
                is None
            )
    finally:
        dispose_engine(database_url)


def test_signed_pull_and_ack_record_verified_transfer_evidence(tmp_path: Path) -> None:
    database_url, settings, _, client = _client(tmp_path)
    payload = _png()
    checksum = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    try:
        artifact_id = _artifact_id(
            _upload(client, payload, key="delivery-source", nonce="delivery-source")
        )
        download = client.get(
            _download_path(artifact_id),
            headers=_pull_headers(artifact_id, nonce="delivery-pull-1"),
        )

        assert download.status_code == 200, download.json()
        assert download.content == payload
        assert download.headers["accept-ranges"] == "none"
        assert download.headers["cache-control"] == "private, no-store"
        assert "token" not in download.headers["content-disposition"]
        delivery_id = download.headers["x-npcink-delivery-id"]
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            delivery = session.get(MediaArtifactDelivery, delivery_id)
            assert artifact is not None and delivery is not None
            original_artifact_expiry = artifact.expires_at
            assert delivery.completed_at is not None
            assert delivery.completed_byte_size == len(payload)
            assert delivery.completed_checksum == checksum

        ack_payload = {
            "contract_version": "media_artifact_delivery_ack.v1",
            "delivery_id": delivery_id,
            "received_byte_size": len(payload),
            "received_checksum": checksum,
        }
        invalid_body, invalid_headers = _ack_headers(
            artifact_id,
            {**ack_payload, "unexpected": "rejected"},
            key="delivery-ack-invalid",
            nonce="delivery-ack-invalid",
        )
        invalid = client.post(
            _ack_path(artifact_id), content=invalid_body, headers=invalid_headers
        )
        assert invalid.status_code == 422, invalid.json()
        assert invalid.json()["error_code"] == (
            "media_artifact.delivery_ack_validation_error"
        )

        query = "credential=forbidden"
        queried_body, queried_headers = _ack_headers(
            artifact_id,
            ack_payload,
            key="delivery-ack-query",
            nonce="delivery-ack-query",
            query=query,
        )
        queried = client.post(
            f"{_ack_path(artifact_id)}?{query}",
            content=queried_body,
            headers=queried_headers,
        )
        assert queried.status_code == 400, queried.json()
        assert queried.json()["error_code"] == "media_artifact.query_not_allowed"

        ack_body, ack_headers = _ack_headers(
            artifact_id,
            ack_payload,
            key="delivery-ack-key",
            nonce="delivery-ack-1",
        )
        acknowledged = client.post(
            _ack_path(artifact_id), content=ack_body, headers=ack_headers
        )

        assert acknowledged.status_code == 200, acknowledged.json()
        ack_data = acknowledged.json()["data"]
        assert ack_data["acknowledgement_scope"] == "verified_transfer_only"
        assert ack_data["idempotent_replay"] is False
        assert "direct_cms_write" not in ack_data
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            delivery = session.get(MediaArtifactDelivery, delivery_id)
            assert artifact is not None and delivery is not None
            assert delivery.acked_at is not None
            assert delivery.retention_expires_at_before is not None
            assert delivery.retention_expires_at_after is not None
            assert artifact.expires_at == original_artifact_expiry
            assert delivery.retention_expires_at_before == original_artifact_expiry
            assert delivery.retention_expires_at_after == original_artifact_expiry
            acknowledged_at = delivery.acked_at

        six_minutes_after_ack = acknowledged_at + timedelta(minutes=6)
        assert original_artifact_expiry > six_minutes_after_ack + timedelta(minutes=5)
        with get_session(database_url) as session:
            prepared_after_review = prepare_media_artifact_delivery(
                session=session,
                artifact_store=build_artifact_store(settings),
                artifact_id=artifact_id,
                site_id="site_alpha",
                trace_id="delivery-after-review-delay",
                now=six_minutes_after_ack,
            )
            prepared_after_review.stream.close()
            session.rollback()
        with get_session(database_url) as session:
            with pytest.raises(MediaArtifactExpiredError):
                prepare_media_artifact_delivery(
                    session=session,
                    artifact_store=build_artifact_store(settings),
                    artifact_id=artifact_id,
                    site_id="site_alpha",
                    trace_id="delivery-at-original-expiry",
                    now=original_artifact_expiry,
                )
            session.rollback()

        replay_body, replay_headers = _ack_headers(
            artifact_id,
            ack_payload,
            key="delivery-ack-key",
            nonce="delivery-ack-2",
        )
        replay = client.post(
            _ack_path(artifact_id), content=replay_body, headers=replay_headers
        )
        assert replay.status_code == 200, replay.json()
        assert replay.json()["data"]["idempotent_replay"] is True

        conflicting_payload = {**ack_payload, "received_byte_size": len(payload) - 1}
        conflict_body, conflict_headers = _ack_headers(
            artifact_id,
            conflicting_payload,
            key="delivery-ack-key",
            nonce="delivery-ack-3",
        )
        conflict = client.post(
            _ack_path(artifact_id), content=conflict_body, headers=conflict_headers
        )
        assert conflict.status_code == 409, conflict.json()
        assert conflict.json()["error_code"] == "media_artifact.delivery_ack_conflict"
    finally:
        dispose_engine(database_url)


def test_delivery_ack_rejects_incomplete_delivery(tmp_path: Path) -> None:
    database_url, settings, _, client = _client(tmp_path)
    try:
        artifact_id = _artifact_id(
            _upload(client, _png(), key="ack-incomplete-source", nonce="ack-incomplete-source")
        )
        with get_session(database_url) as session:
            prepared = prepare_media_artifact_delivery(
                session=session,
                artifact_store=build_artifact_store(settings),
                artifact_id=artifact_id,
                site_id="site_alpha",
                trace_id="ack-incomplete-trace",
            )
            delivery_id = prepared.delivery.delivery_id
            byte_size = prepared.delivery.expected_byte_size
            checksum = prepared.delivery.expected_checksum
            session.commit()
        prepared.stream.close()
        payload = {
            "contract_version": "media_artifact_delivery_ack.v1",
            "delivery_id": delivery_id,
            "received_byte_size": byte_size,
            "received_checksum": checksum,
        }
        body, headers = _ack_headers(
            artifact_id,
            payload,
            key="ack-incomplete",
            nonce="ack-incomplete",
        )

        response = client.post(_ack_path(artifact_id), content=body, headers=headers)

        assert response.status_code == 409, response.json()
        assert response.json()["error_code"] == "media_artifact.delivery_not_completed"
        with get_session(database_url) as session:
            delivery = session.get(MediaArtifactDelivery, delivery_id)
            assert delivery is not None
            assert delivery.acked_at is None
    finally:
        dispose_engine(database_url)


def test_committed_ack_replay_remains_successful_after_purge_and_conflict_stays_409(
    tmp_path: Path,
) -> None:
    database_url, settings, _, client = _client(tmp_path)
    media_bytes = _png()
    checksum = f"sha256:{hashlib.sha256(media_bytes).hexdigest()}"
    try:
        artifact_id = _artifact_id(
            _upload(
                client, media_bytes, key="ack-replay-purge-source", nonce="ack-replay-purge-source"
            )
        )
        download = client.get(
            _download_path(artifact_id),
            headers=_pull_headers(artifact_id, nonce="ack-replay-purge-pull"),
        )
        assert download.status_code == 200, download.json()
        delivery_id = download.headers["x-npcink-delivery-id"]
        payload = {
            "contract_version": "media_artifact_delivery_ack.v1",
            "delivery_id": delivery_id,
            "received_byte_size": len(media_bytes),
            "received_checksum": checksum,
        }
        body, headers = _ack_headers(
            artifact_id,
            payload,
            key="ack-replay-purge-key",
            nonce="ack-replay-purge-first",
        )
        first = client.post(_ack_path(artifact_id), content=body, headers=headers)
        assert first.status_code == 200, first.json()

        cleanup_at = datetime.now(UTC)
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            delivery = session.get(MediaArtifactDelivery, delivery_id)
            assert artifact is not None and delivery is not None
            artifact.expires_at = cleanup_at - timedelta(seconds=1)
            retention_before_purge = artifact.expires_at
            session.commit()
        cleanup = MediaArtifactLifecycleService(
            database_url,
            artifact_store=build_artifact_store(settings),
        ).cleanup_expired_artifacts(now=cleanup_at)
        assert cleanup["purged"] == 1

        replay_body, replay_headers = _ack_headers(
            artifact_id,
            payload,
            key="ack-replay-purge-key",
            nonce="ack-replay-purge-exact",
        )
        replay = client.post(_ack_path(artifact_id), content=replay_body, headers=replay_headers)
        assert replay.status_code == 200, replay.json()
        assert replay.json()["data"]["idempotent_replay"] is True

        conflict_body, conflict_headers = _ack_headers(
            artifact_id,
            {**payload, "received_byte_size": len(media_bytes) - 1},
            key="ack-replay-purge-key",
            nonce="ack-replay-purge-conflict",
        )
        conflict = client.post(
            _ack_path(artifact_id), content=conflict_body, headers=conflict_headers
        )
        assert conflict.status_code == 409, conflict.json()
        assert conflict.json()["error_code"] == "media_artifact.delivery_ack_conflict"
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            delivery = session.get(MediaArtifactDelivery, delivery_id)
            assert artifact is not None and delivery is not None
            assert artifact.status == "purged"
            assert artifact.expires_at == retention_before_purge.replace(tzinfo=None)
            assert delivery.acked_at is not None
            assert delivery.revoked_at is None
    finally:
        dispose_engine(database_url)


@pytest.mark.parametrize(
    "terminal_state",
    [
        "revoked",
        "artifact_expired",
        "artifact_pending",
        "artifact_purged",
        "artifact_failed",
        "artifact_unknown",
    ],
)
def test_first_ack_terminal_state_wins_over_incomplete_delivery(
    tmp_path: Path,
    terminal_state: str,
) -> None:
    database_url, settings, _, client = _client(tmp_path)
    media_bytes = _png()
    try:
        artifact_id = _artifact_id(
            _upload(
                client,
                media_bytes,
                key=f"ack-priority-{terminal_state}-source",
                nonce=f"ack-priority-{terminal_state}-source",
            )
        )
        with get_session(database_url) as session:
            prepared = prepare_media_artifact_delivery(
                session=session,
                artifact_store=build_artifact_store(settings),
                artifact_id=artifact_id,
                site_id="site_alpha",
                trace_id="ack-priority-trace",
            )
            delivery_id = prepared.delivery.delivery_id
            byte_size = prepared.delivery.expected_byte_size
            checksum = prepared.delivery.expected_checksum
            session.commit()
        prepared.stream.close()
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            delivery = session.get(MediaArtifactDelivery, delivery_id)
            assert artifact is not None and delivery is not None
            if terminal_state == "revoked":
                delivery.revoked_at = datetime.now(UTC)
            elif terminal_state == "artifact_expired":
                artifact.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            elif terminal_state == "artifact_pending":
                artifact.status = "purge_pending"
            elif terminal_state == "artifact_purged":
                artifact.status = "purged"
                artifact.purged_at = datetime.now(UTC)
            elif terminal_state == "artifact_failed":
                artifact.status = "failed"
            else:
                artifact.status = "unknown_future_status"
            retention_before = artifact.expires_at
            session.commit()

        payload = {
            "contract_version": "media_artifact_delivery_ack.v1",
            "delivery_id": delivery_id,
            "received_byte_size": byte_size,
            "received_checksum": checksum,
        }
        body, headers = _ack_headers(
            artifact_id,
            payload,
            key=f"ack-priority-{terminal_state}",
            nonce=f"ack-priority-{terminal_state}",
        )
        response = client.post(_ack_path(artifact_id), content=body, headers=headers)

        assert response.status_code == 410, response.json()
        assert response.json()["error_code"] == "media_artifact.delivery_expired"
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            delivery = session.get(MediaArtifactDelivery, delivery_id)
            assert artifact is not None and delivery is not None
            assert artifact.expires_at == retention_before.replace(tzinfo=None)
            assert delivery.acked_at is None
            assert delivery.ack_idempotency_key is None
            assert delivery.retention_expires_at_before is None
            assert delivery.retention_expires_at_after is None
    finally:
        dispose_engine(database_url)


@pytest.mark.parametrize("mismatch", ["byte_size", "checksum"])
def test_first_delivery_ack_rejects_mismatched_received_facts(
    tmp_path: Path,
    mismatch: str,
) -> None:
    database_url, _, _, client = _client(tmp_path)
    media_bytes = _png()
    try:
        artifact_id = _artifact_id(
            _upload(
                client,
                media_bytes,
                key=f"ack-mismatch-source-{mismatch}",
                nonce=f"ack-mismatch-source-{mismatch}",
            )
        )
        download = client.get(
            _download_path(artifact_id),
            headers=_pull_headers(artifact_id, nonce=f"ack-mismatch-pull-{mismatch}"),
        )
        assert download.status_code == 200, download.json()
        delivery_id = download.headers["x-npcink-delivery-id"]
        payload = {
            "contract_version": "media_artifact_delivery_ack.v1",
            "delivery_id": delivery_id,
            "received_byte_size": (
                len(media_bytes) - 1 if mismatch == "byte_size" else len(media_bytes)
            ),
            "received_checksum": (
                "sha256:" + ("0" * 64)
                if mismatch == "checksum"
                else f"sha256:{hashlib.sha256(media_bytes).hexdigest()}"
            ),
        }
        body, headers = _ack_headers(
            artifact_id,
            payload,
            key=f"ack-mismatch-{mismatch}",
            nonce=f"ack-mismatch-{mismatch}",
        )

        response = client.post(_ack_path(artifact_id), content=body, headers=headers)

        assert response.status_code == 422, response.json()
        assert response.json()["error_code"] == (
            "media_artifact.delivery_integrity_mismatch"
        )
        with get_session(database_url) as session:
            delivery = session.get(MediaArtifactDelivery, delivery_id)
            assert delivery is not None
            assert delivery.acked_at is None
            assert delivery.ack_idempotency_key is None
    finally:
        dispose_engine(database_url)


def test_delivery_ack_hides_cross_site_delivery(tmp_path: Path) -> None:
    database_url, _, _, client = _client(tmp_path)
    media_bytes = _png()
    try:
        artifact_id = _artifact_id(
            _upload(client, media_bytes, key="ack-cross-site-source", nonce="ack-cross-site-source")
        )
        download = client.get(
            _download_path(artifact_id),
            headers=_pull_headers(artifact_id, nonce="ack-cross-site-pull"),
        )
        assert download.status_code == 200, download.json()
        delivery_id = download.headers["x-npcink-delivery-id"]
        payload = {
            "contract_version": "media_artifact_delivery_ack.v1",
            "delivery_id": delivery_id,
            "received_byte_size": len(media_bytes),
            "received_checksum": f"sha256:{hashlib.sha256(media_bytes).hexdigest()}",
        }
        body, headers = _ack_headers(
            artifact_id,
            payload,
            key="ack-cross-site",
            nonce="ack-cross-site",
            site_id="site_beta",
            key_id="key_beta",
        )

        response = client.post(_ack_path(artifact_id), content=body, headers=headers)

        assert response.status_code == 404, response.json()
        assert response.json()["error_code"] == "media_artifact.delivery_not_found"
        with get_session(database_url) as session:
            delivery = session.get(MediaArtifactDelivery, delivery_id)
            assert delivery is not None
            assert delivery.acked_at is None
    finally:
        dispose_engine(database_url)


@pytest.mark.parametrize("delivery_state", ["expired", "revoked"])
def test_delivery_ack_rejects_expired_or_revoked_delivery(
    tmp_path: Path,
    delivery_state: str,
) -> None:
    database_url, _, _, client = _client(tmp_path)
    media_bytes = _png()
    try:
        artifact_id = _artifact_id(
            _upload(
                client,
                media_bytes,
                key=f"ack-{delivery_state}-source",
                nonce=f"ack-{delivery_state}-source",
            )
        )
        download = client.get(
            _download_path(artifact_id),
            headers=_pull_headers(artifact_id, nonce=f"ack-{delivery_state}-pull"),
        )
        assert download.status_code == 200, download.json()
        delivery_id = download.headers["x-npcink-delivery-id"]
        with get_session(database_url) as session:
            delivery = session.get(MediaArtifactDelivery, delivery_id)
            assert delivery is not None
            if delivery_state == "expired":
                delivery.ack_deadline_at = datetime.now(UTC) - timedelta(seconds=1)
            else:
                delivery.revoked_at = datetime.now(UTC)
            session.commit()
        payload = {
            "contract_version": "media_artifact_delivery_ack.v1",
            "delivery_id": delivery_id,
            "received_byte_size": len(media_bytes),
            "received_checksum": f"sha256:{hashlib.sha256(media_bytes).hexdigest()}",
        }
        body, headers = _ack_headers(
            artifact_id,
            payload,
            key=f"ack-{delivery_state}",
            nonce=f"ack-{delivery_state}",
        )

        response = client.post(_ack_path(artifact_id), content=body, headers=headers)

        assert response.status_code == 410, response.json()
        assert response.json()["error_code"] == "media_artifact.delivery_expired"
        with get_session(database_url) as session:
            delivery = session.get(MediaArtifactDelivery, delivery_id)
            assert delivery is not None
            assert delivery.acked_at is None
    finally:
        dispose_engine(database_url)


def test_delivery_ack_does_not_revive_a_purged_artifact(tmp_path: Path) -> None:
    database_url, settings, _, client = _client(tmp_path)
    media_bytes = _png()
    try:
        artifact_id = _artifact_id(
            _upload(client, media_bytes, key="ack-purged-source", nonce="ack-purged-source")
        )
        download = client.get(
            _download_path(artifact_id),
            headers=_pull_headers(artifact_id, nonce="ack-purged-pull"),
        )
        assert download.status_code == 200, download.json()
        delivery_id = download.headers["x-npcink-delivery-id"]
        cleanup_time = datetime.now(UTC)
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            assert artifact is not None
            artifact.expires_at = cleanup_time - timedelta(seconds=1)
            session.commit()
        cleanup = MediaArtifactLifecycleService(
            database_url,
            artifact_store=build_artifact_store(settings),
        ).cleanup_expired_artifacts(now=cleanup_time)
        assert cleanup["purged"] == 1
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            delivery = session.get(MediaArtifactDelivery, delivery_id)
            assert artifact is not None
            assert delivery is not None
            purged_at = artifact.purged_at
            expires_at = artifact.expires_at
            assert artifact.status == "purged"
            assert purged_at is not None
            assert delivery.completed_at is not None
            assert delivery.revoked_at is not None
            assert delivery.completed_at <= delivery.revoked_at

        payload = {
            "contract_version": "media_artifact_delivery_ack.v1",
            "delivery_id": delivery_id,
            "received_byte_size": len(media_bytes),
            "received_checksum": f"sha256:{hashlib.sha256(media_bytes).hexdigest()}",
        }
        body, headers = _ack_headers(
            artifact_id,
            payload,
            key="ack-purged",
            nonce="ack-purged",
        )

        response = client.post(_ack_path(artifact_id), content=body, headers=headers)

        assert response.status_code == 410, response.json()
        assert response.json()["error_code"] == "media_artifact.delivery_expired"
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            delivery = session.get(MediaArtifactDelivery, delivery_id)
            assert artifact is not None and delivery is not None
            assert artifact.status == "purged"
            assert artifact.purged_at == purged_at
            assert artifact.expires_at == expires_at
            assert delivery.acked_at is None
    finally:
        dispose_engine(database_url)


def test_ack_idempotency_key_cannot_be_reused_across_deliveries(tmp_path: Path) -> None:
    database_url, _, _, client = _client(tmp_path)
    media_payloads = (_png(color="red"), _png(color="blue"))
    try:
        deliveries: list[tuple[str, str, bytes]] = []
        for index, media_bytes in enumerate(media_payloads, start=1):
            artifact_id = _artifact_id(
                _upload(
                    client,
                    media_bytes,
                    key=f"ack-key-reuse-source-{index}",
                    nonce=f"ack-key-reuse-source-{index}",
                )
            )
            download = client.get(
                _download_path(artifact_id),
                headers=_pull_headers(artifact_id, nonce=f"ack-key-reuse-pull-{index}"),
            )
            assert download.status_code == 200, download.json()
            deliveries.append(
                (artifact_id, download.headers["x-npcink-delivery-id"], media_bytes)
            )

        responses = []
        for index, (artifact_id, delivery_id, media_bytes) in enumerate(
            deliveries,
            start=1,
        ):
            ack_payload = {
                "contract_version": "media_artifact_delivery_ack.v1",
                "delivery_id": delivery_id,
                "received_byte_size": len(media_bytes),
                "received_checksum": f"sha256:{hashlib.sha256(media_bytes).hexdigest()}",
            }
            body, headers = _ack_headers(
                artifact_id,
                ack_payload,
                key="ack-key-shared-across-deliveries",
                nonce=f"ack-key-reuse-{index}",
            )
            responses.append(
                client.post(_ack_path(artifact_id), content=body, headers=headers)
            )

        assert responses[0].status_code == 200, responses[0].json()
        assert responses[1].status_code == 409, responses[1].json()
        assert responses[1].json()["error_code"] == (
            "media_artifact.delivery_ack_conflict"
        )
        with get_session(database_url) as session:
            acked = list(
                session.scalars(
                    select(MediaArtifactDelivery).where(
                        MediaArtifactDelivery.ack_idempotency_key
                        == "ack-key-shared-across-deliveries"
                    )
                )
            )
        assert len(acked) == 1
        assert acked[0].delivery_id == deliveries[0][1]
    finally:
        dispose_engine(database_url)


def test_concurrent_signed_pull_nonce_allows_exactly_one_request(tmp_path: Path) -> None:
    database_url, _, _, seed_client = _client(tmp_path)
    first_client = TestClient(seed_client.app)
    second_client = TestClient(seed_client.app)
    try:
        artifact_id = _artifact_id(
            _upload(
                seed_client,
                _png(),
                key="concurrent-pull-source",
                nonce="concurrent-pull-source",
            )
        )
        headers = _pull_headers(artifact_id, nonce="concurrent-pull-shared-nonce")

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    client.get,
                    _download_path(artifact_id),
                    headers=headers,
                )
                for client in (first_client, second_client)
            ]
        responses = [future.result() for future in futures]

        assert sorted(response.status_code for response in responses) == [200, 409]
        rejected = next(response for response in responses if response.status_code == 409)
        assert rejected.json()["error_code"] == "auth.replay_blocked"
        with get_session(database_url) as session:
            deliveries = list(
                session.scalars(
                    select(MediaArtifactDelivery).where(
                        MediaArtifactDelivery.artifact_id == artifact_id
                    )
                )
            )
            receipts = list(
                session.scalars(
                    select(ReplayReceipt).where(
                        ReplayReceipt.replay_key == "concurrent-pull-shared-nonce"
                    )
                )
            )
        assert len(deliveries) == 1
        assert len(receipts) == 3
        assert {receipt.scope_kind for receipt in receipts} == {
            "public_pull_site",
            "public_pull_key",
            "public_pull_ip",
        }
    finally:
        first_client.close()
        second_client.close()
        dispose_engine(database_url)


def test_signed_pull_security_failures_are_isolated_from_public_post_guard(
    tmp_path: Path,
) -> None:
    database_url, _, _, client = _client(tmp_path)
    try:
        upload = _upload(
            client,
            _png(),
            key="pull-security-source",
            nonce="pull-security-source",
        )
        artifact_id = _artifact_id(upload)
        run_path = f"/v1/runs/{upload.json()['data']['run_id']}"
        ordinary_get_headers = build_auth_headers(
            "GET",
            run_path,
            site_id="site_alpha",
        )
        assert "X-Npcink-Nonce" not in ordinary_get_headers
        ordinary_get = client.get(run_path, headers=ordinary_get_headers)
        assert ordinary_get.status_code == 200, ordinary_get.json()

        missing_nonce = client.get(
            _download_path(artifact_id),
            headers=_pull_headers(artifact_id),
        )
        assert missing_nonce.status_code == 401, missing_nonce.json()
        assert missing_nonce.json()["error_code"] == "auth.nonce_required"
        with get_session(database_url) as session:
            scopes = set(session.scalars(select(RuntimeGuardEvent.scope_kind)))
        assert scopes == {"public_pull_site", "public_pull_key", "public_pull_ip"}
        assert not any(scope.startswith("public_post") for scope in scopes)

        secret_query = "token=supersecret"
        rejected_query = client.get(
            f"{_download_path(artifact_id)}?{secret_query}",
            headers=_pull_headers(artifact_id, query=secret_query),
        )
        assert rejected_query.status_code == 401, rejected_query.json()
        with get_session(database_url) as session:
            guard_payloads = list(session.scalars(select(RuntimeGuardEvent.payload_json)))
        serialized_guard_payloads = json.dumps(guard_payloads, sort_keys=True)
        assert "supersecret" not in serialized_guard_payloads
        assert '"query"' not in serialized_guard_payloads
        assert any(payload and payload.get("has_query") is True for payload in guard_payloads)

        replay_headers = _pull_headers(artifact_id, nonce="pull-security-replay")
        first = client.get(_download_path(artifact_id), headers=replay_headers)
        assert first.status_code == 200, first.json()
        replay = client.get(_download_path(artifact_id), headers=replay_headers)
        assert replay.status_code == 409, replay.json()
        assert replay.json()["error_code"] == "auth.replay_blocked"

        cross_site = client.get(
            _download_path(artifact_id),
            headers=_pull_headers(
                artifact_id,
                nonce="pull-security-cross-site",
                site_id="site_beta",
                key_id="key_beta",
            ),
        )
        assert cross_site.status_code == 404, cross_site.json()

        ranged_headers = _pull_headers(artifact_id, nonce="pull-security-range")
        ranged_headers["Range"] = "bytes=0-9"
        ranged = client.get(_download_path(artifact_id), headers=ranged_headers)
        assert ranged.status_code == 416, ranged.json()
        assert ranged.headers["accept-ranges"] == "none"

        query = "credential=forbidden"
        queried = client.get(
            f"{_download_path(artifact_id)}?{query}",
            headers=_pull_headers(
                artifact_id,
                nonce="pull-security-query",
                query=query,
            ),
        )
        assert queried.status_code == 400, queried.json()
        assert queried.json()["error_code"] == "media_artifact.query_not_allowed"

        keyed = client.get(
            _download_path(artifact_id),
            headers=_pull_headers(
                artifact_id,
                nonce="pull-security-keyed",
                idempotency_key="not-allowed",
            ),
        )
        assert keyed.status_code == 400, keyed.json()
        assert keyed.json()["error_code"] == "media_artifact.idempotency_key_not_allowed"
    finally:
        dispose_engine(database_url)


def test_signed_pull_uses_distinct_client_ip_replay_scopes(tmp_path: Path) -> None:
    database_url, _, _, seed_client = _client(tmp_path)
    first_client = TestClient(seed_client.app, client=("198.51.100.10", 50000))
    second_client = TestClient(seed_client.app, client=("198.51.100.11", 50000))
    try:
        artifact_id = _artifact_id(
            _upload(seed_client, _png(), key="pull-ip-source", nonce="pull-ip-source")
        )
        first = first_client.get(
            _download_path(artifact_id),
            headers=_pull_headers(artifact_id, nonce="pull-ip-first"),
        )
        second = second_client.get(
            _download_path(artifact_id),
            headers=_pull_headers(artifact_id, nonce="pull-ip-second"),
        )
        assert first.status_code == 200, first.json()
        assert second.status_code == 200, second.json()
        with get_session(database_url) as session:
            pull_ip_scopes = set(
                session.scalars(
                    select(ReplayReceipt.scope_id).where(
                        ReplayReceipt.scope_kind == "public_pull_ip"
                    )
                )
            )
        assert pull_ip_scopes == {"198.51.100.10", "198.51.100.11"}
    finally:
        first_client.close()
        second_client.close()
        dispose_engine(database_url)


@pytest.mark.parametrize(
    ("artifact_mutation", "expected_status", "expected_code"),
    [
        ("pending", 409, "media_artifact.not_available"),
        ("expired", 410, "media_artifact.expired"),
        ("storage_mismatch", 503, "media_artifact.bytes_unavailable"),
    ],
)
def test_signed_pull_fails_closed_for_unavailable_artifact_or_bytes(
    tmp_path: Path,
    artifact_mutation: str,
    expected_status: int,
    expected_code: str,
) -> None:
    database_url, _, _, client = _client(tmp_path)
    try:
        artifact_id = _artifact_id(
            _upload(
                client,
                _png(),
                key=f"pull-fail-{artifact_mutation}",
                nonce=f"pull-fail-{artifact_mutation}",
            )
        )
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            assert artifact is not None
            if artifact_mutation == "pending":
                artifact.status = "pending"
            elif artifact_mutation == "expired":
                artifact.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            else:
                artifact.byte_size += 1
            session.commit()

        response = client.get(
            _download_path(artifact_id),
            headers=_pull_headers(artifact_id, nonce=f"pull-fail-{artifact_mutation}"),
        )
        assert response.status_code == expected_status, response.json()
        assert response.json()["error_code"] == expected_code
    finally:
        dispose_engine(database_url)


@pytest.mark.parametrize("failure_mode", ["interrupted", "checksum_mismatch", "oversize"])
def test_delivery_is_not_completed_for_interrupted_or_mismatched_stream(
    tmp_path: Path,
    failure_mode: str,
) -> None:
    database_url, settings, _, client = _client(tmp_path)
    try:
        artifact_id = _artifact_id(
            _upload(client, _png(), key="stream-evidence", nonce="stream-evidence")
        )
        with get_session(database_url) as session:
            prepared = prepare_media_artifact_delivery(
                session=session,
                artifact_store=build_artifact_store(settings),
                artifact_id=artifact_id,
                site_id="site_alpha",
                trace_id="stream-evidence-trace",
            )
            delivery_id = prepared.delivery.delivery_id
            expected_byte_size = prepared.delivery.expected_byte_size
            expected_checksum = prepared.delivery.expected_checksum
            session.commit()

        chunks = iter_verified_delivery_chunks(
            prepared.stream,
            database_url=database_url,
            artifact_id=artifact_id,
            site_id="site_alpha",
            delivery_id=delivery_id,
            expected_byte_size=(
                expected_byte_size - 1 if failure_mode == "oversize" else expected_byte_size
            ),
            expected_checksum=(
                "sha256:" + ("0" * 64)
                if failure_mode == "checksum_mismatch"
                else expected_checksum
            ),
            chunk_size=prepared.chunk_size,
        )
        if failure_mode == "interrupted":
            next(chunks)
            chunks.close()
        else:
            delivered = b"".join(chunks)
            if failure_mode == "oversize":
                assert len(delivered) <= expected_byte_size - 1

        with get_session(database_url) as session:
            delivery = session.get(MediaArtifactDelivery, delivery_id)
            assert delivery is not None
            assert delivery.completed_at is None
            assert delivery.completed_byte_size is None
            assert delivery.completed_checksum is None
    finally:
        dispose_engine(database_url)


@pytest.mark.parametrize("mismatch", ["byte_size", "checksum"])
def test_stream_completion_rejects_facts_that_differ_from_locked_delivery_evidence(
    tmp_path: Path,
    mismatch: str,
) -> None:
    database_url, settings, _, client = _client(tmp_path)
    media_bytes = _png()
    try:
        artifact_id = _artifact_id(
            _upload(client, media_bytes, key="completion-db-facts", nonce="completion-db-facts")
        )
        with get_session(database_url) as session:
            prepared = prepare_media_artifact_delivery(
                session=session,
                artifact_store=build_artifact_store(settings),
                artifact_id=artifact_id,
                site_id="site_alpha",
                trace_id="completion-db-facts-trace",
            )
            delivery_id = prepared.delivery.delivery_id
            expected_byte_size = prepared.delivery.expected_byte_size
            expected_checksum = prepared.delivery.expected_checksum
            session.commit()
        with get_session(database_url) as session:
            delivery = session.get(MediaArtifactDelivery, delivery_id)
            assert delivery is not None
            if mismatch == "byte_size":
                delivery.expected_byte_size += 1
            else:
                delivery.expected_checksum = "sha256:" + ("0" * 64)
            session.commit()

        delivered = b"".join(
            iter_verified_delivery_chunks(
                prepared.stream,
                database_url=database_url,
                artifact_id=artifact_id,
                site_id="site_alpha",
                delivery_id=delivery_id,
                expected_byte_size=expected_byte_size,
                expected_checksum=expected_checksum,
                chunk_size=prepared.chunk_size,
            )
        )

        assert delivered == media_bytes
        with get_session(database_url) as session:
            delivery = session.get(MediaArtifactDelivery, delivery_id)
            assert delivery is not None
            assert delivery.completed_at is None
            assert delivery.completed_byte_size is None
            assert delivery.completed_checksum is None
    finally:
        dispose_engine(database_url)


def test_wall_clock_expiry_does_not_erase_completion_for_already_issued_stream(
    tmp_path: Path,
) -> None:
    database_url, settings, _, client = _client(tmp_path)
    media_bytes = _png()
    try:
        artifact_id = _artifact_id(
            _upload(
                client,
                media_bytes,
                key="completion-expiry-source",
                nonce="completion-expiry-source",
            )
        )
        with get_session(database_url) as session:
            prepared = prepare_media_artifact_delivery(
                session=session,
                artifact_store=build_artifact_store(settings),
                artifact_id=artifact_id,
                site_id="site_alpha",
                trace_id="completion-expiry-trace",
            )
            delivery_id = prepared.delivery.delivery_id
            expected_byte_size = prepared.delivery.expected_byte_size
            expected_checksum = prepared.delivery.expected_checksum
            session.commit()
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            assert artifact is not None
            artifact.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()

        delivered = b"".join(
            iter_verified_delivery_chunks(
                prepared.stream,
                database_url=database_url,
                artifact_id=artifact_id,
                site_id="site_alpha",
                delivery_id=delivery_id,
                expected_byte_size=expected_byte_size,
                expected_checksum=expected_checksum,
                chunk_size=prepared.chunk_size,
            )
        )

        assert delivered == media_bytes
        with get_session(database_url) as session:
            delivery = session.get(MediaArtifactDelivery, delivery_id)
            assert delivery is not None
            assert delivery.completed_at is not None
            assert delivery.completed_byte_size == expected_byte_size
            assert delivery.completed_checksum == expected_checksum
    finally:
        dispose_engine(database_url)


@pytest.mark.parametrize("terminal_state", ["pending", "purged", "revoked"])
def test_terminal_artifact_or_delivery_state_blocks_new_stream_completion(
    tmp_path: Path,
    terminal_state: str,
) -> None:
    database_url, settings, _, client = _client(tmp_path)
    media_bytes = _png()
    try:
        artifact_id = _artifact_id(
            _upload(
                client,
                media_bytes,
                key=f"completion-terminal-{terminal_state}",
                nonce=f"completion-terminal-{terminal_state}",
            )
        )
        with get_session(database_url) as session:
            prepared = prepare_media_artifact_delivery(
                session=session,
                artifact_store=build_artifact_store(settings),
                artifact_id=artifact_id,
                site_id="site_alpha",
                trace_id="completion-terminal-trace",
            )
            delivery_id = prepared.delivery.delivery_id
            expected_byte_size = prepared.delivery.expected_byte_size
            expected_checksum = prepared.delivery.expected_checksum
            session.commit()
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            delivery = session.get(MediaArtifactDelivery, delivery_id)
            assert artifact is not None and delivery is not None
            if terminal_state == "pending":
                artifact.status = "purge_pending"
            elif terminal_state == "purged":
                artifact.status = "purged"
                artifact.purged_at = datetime.now(UTC)
            else:
                delivery.revoked_at = datetime.now(UTC)
            session.commit()

        assert (
            b"".join(
                iter_verified_delivery_chunks(
                    prepared.stream,
                    database_url=database_url,
                    artifact_id=artifact_id,
                    site_id="site_alpha",
                    delivery_id=delivery_id,
                    expected_byte_size=expected_byte_size,
                    expected_checksum=expected_checksum,
                    chunk_size=prepared.chunk_size,
                )
            )
            == media_bytes
        )
        with get_session(database_url) as session:
            delivery = session.get(MediaArtifactDelivery, delivery_id)
            assert delivery is not None
            assert delivery.completed_at is None
            assert delivery.completed_byte_size is None
            assert delivery.completed_checksum is None
    finally:
        dispose_engine(database_url)


def test_purge_claim_wins_before_stream_completion(tmp_path: Path) -> None:
    database_url, settings, _, client = _client(tmp_path)
    media_bytes = _png()
    try:
        artifact_id = _artifact_id(
            _upload(
                client, media_bytes, key="purge-before-completion", nonce="purge-before-completion"
            )
        )
        with get_session(database_url) as session:
            prepared = prepare_media_artifact_delivery(
                session=session,
                artifact_store=build_artifact_store(settings),
                artifact_id=artifact_id,
                site_id="site_alpha",
                trace_id="purge-before-completion-trace",
            )
            delivery_id = prepared.delivery.delivery_id
            expected_byte_size = prepared.delivery.expected_byte_size
            expected_checksum = prepared.delivery.expected_checksum
            session.commit()
        cleanup_at = datetime.now(UTC)
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            assert artifact is not None
            artifact.expires_at = cleanup_at - timedelta(seconds=1)
            session.commit()
        cleanup = MediaArtifactLifecycleService(
            database_url,
            artifact_store=build_artifact_store(settings),
        ).cleanup_expired_artifacts(now=cleanup_at)
        assert cleanup["purged"] == 1

        assert (
            b"".join(
                iter_verified_delivery_chunks(
                    prepared.stream,
                    database_url=database_url,
                    artifact_id=artifact_id,
                    site_id="site_alpha",
                    delivery_id=delivery_id,
                    expected_byte_size=expected_byte_size,
                    expected_checksum=expected_checksum,
                    chunk_size=prepared.chunk_size,
                )
            )
            == media_bytes
        )
        with get_session(database_url) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            delivery = session.get(MediaArtifactDelivery, delivery_id)
            assert artifact is not None and delivery is not None
            assert artifact.status == "purged"
            assert delivery.revoked_at is not None
            assert delivery.completed_at is None
    finally:
        dispose_engine(database_url)


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
        artifact = result.json()["data"]["result"]["artifact"]
        assert set(artifact) == {
            "artifact_id",
            "artifact_reference",
            "expires_at",
            "suggested_filename",
            "filename_basis",
            "mime_type",
            "format",
            "width",
            "height",
            "filesize_bytes",
            "checksum",
            "processing_warnings",
        }
        assert "status" not in artifact
        assert "purged_at" not in artifact
        serialized = json.dumps({"job": job.json(), "result": result.json()})
        for field in BLOCKED_RESPONSE_FIELDS:
            assert field not in serialized
        with get_session(database_url) as session:
            assert session.scalar(select(ProviderCallRecord)) is None
    finally:
        dispose_engine(database_url)
