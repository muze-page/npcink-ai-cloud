from __future__ import annotations

import ast
import base64
import io
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import select

from app.adapters.providers.base import ProviderMediaCandidate
from app.adapters.queue.in_memory import InMemoryRuntimeQueue
from app.adapters.repositories.runtime_repository import RuntimeRepository
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    MediaArtifact,
    MediaDerivativeJobMetric,
    RunRecord,
)
from app.domain.audio_generation.artifacts import AudioArtifactMaterializationError
from app.domain.image_generation.materialization import (
    ImageGenerationArtifactMaterializationError,
)
from app.domain.media_artifacts import ArtifactStoreError
from app.domain.media_derivatives.artifacts import (
    cleanup_expired_artifacts,
    get_artifact,
    validate_image_upload_stream,
)
from app.domain.runtime.errors import RuntimeRunNotFoundError
from app.domain.runtime.service import RuntimeService
from tests.conftest import seed_site_auth


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    database_url: str
    service: RuntimeService


@pytest.fixture
def runtime_context(tmp_path: Path) -> Iterator[RuntimeContext]:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'artifact-coordination.sqlite3'}"
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
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        artifact_store_root=str(tmp_path / "artifacts"),
        audio_generation_artifact_ttl_minutes=3,
    )
    yield RuntimeContext(
        database_url=database_url,
        service=RuntimeService(
            database_url,
            settings=settings,
            providers={},
            runtime_queue=InMemoryRuntimeQueue(),
        ),
    )
    dispose_engine(database_url)


def _png_bytes(*, width: int = 64, height: int = 48) -> bytes:
    image = Image.new("RGB", (width, height), color="blue")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _media_input(source_artifact_id: str, *, ttl_minutes: int = 7) -> dict[str, Any]:
    return {
        "request_contract_version": "media_job_request.v1",
        "operation": "image.transform.v1",
        "source_artifact_id": source_artifact_id,
        "params": {
            "target_format": "png",
            "max_width": 32,
            "quality": 80,
            "source_media_type": "image",
        },
        "result_ttl_minutes": ttl_minutes,
    }


def _upload_source(
    context: RuntimeContext,
    *,
    source_bytes: bytes,
    idempotency_key: str,
    ttl_minutes: int = 7,
) -> str:
    stream = io.BytesIO(source_bytes)
    upload = validate_image_upload_stream(stream, declared_content_type="image/png")
    response = context.service.create_media_upload(
        site_id="site_alpha",
        request_payload={
            "request_contract_version": "media_upload_request.v1",
            "media_kind": "image",
            "ttl_minutes": ttl_minutes,
        },
        stream=stream,
        upload=upload,
        ttl_minutes=ttl_minutes,
        idempotency_key=f"{idempotency_key}-upload",
        trace_id=f"trace-{idempotency_key}-upload",
    )
    assert response.status == "succeeded"
    return str(response.result["artifact"]["artifact_id"])


def _enqueue_and_process(
    context: RuntimeContext,
    *,
    source_bytes: bytes,
    idempotency_key: str,
    ttl_minutes: int = 7,
) -> str:
    source_artifact_id = _upload_source(
        context,
        source_bytes=source_bytes,
        idempotency_key=idempotency_key,
        ttl_minutes=ttl_minutes,
    )
    response = context.service.enqueue_media_job_run(
        site_id="site_alpha",
        input_payload=_media_input(source_artifact_id, ttl_minutes=ttl_minutes),
        idempotency_key=idempotency_key,
        trace_id=f"trace-{idempotency_key}",
    )
    assert response.status == "queued"
    processed = context.service.process_queued_runs(max_runs=1, timeout_seconds=0)
    assert len(processed) == 1
    assert processed[0]["run_id"] == response.run_id
    return response.run_id


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _create_audio_run(
    repository: RuntimeRepository,
    *,
    run_id: str = "run_audio_artifact_characterization",
) -> RunRecord:
    return repository.create_run(
        run_id=run_id,
        site_id="site_alpha",
        account_id=None,
        subscription_id=None,
        plan_version_id=None,
        ability_name="npcink-cloud/generate-audio",
        ability_family="audio",
        skill_id="",
        workflow_id="",
        contract_version="audio_generation_request.v1",
        channel="openapi",
        execution_kind="audio_generation",
        execution_tier="cloud",
        execution_pattern="inline",
        data_classification="internal",
        profile_id="audio.narration.default",
        canonical_run_id=None,
        status="running",
        idempotency_key=f"idem-{run_id}",
        request_fingerprint=f"fingerprint-{run_id}",
        trace_id=f"trace-{run_id}",
        input_json={},
        execution_input_ciphertext=None,
        policy_json={"storage_mode": "result_only"},
    )


def _create_image_generation_run(
    repository: RuntimeRepository,
    *,
    run_id: str = "run_image_artifact_characterization",
) -> RunRecord:
    return repository.create_run(
        run_id=run_id,
        site_id="site_alpha",
        account_id=None,
        subscription_id=None,
        plan_version_id=None,
        ability_name="npcink-cloud/generate-image",
        ability_family="vision",
        skill_id="",
        workflow_id="",
        contract_version="image_generation_request.v1",
        channel="openapi",
        execution_kind="image_generation",
        execution_tier="cloud",
        execution_pattern="inline",
        data_classification="internal",
        profile_id="image.grok-imagine.default",
        canonical_run_id=None,
        status="running",
        idempotency_key=f"idem-{run_id}",
        request_fingerprint=f"fingerprint-{run_id}",
        trace_id=f"trace-{run_id}",
        input_json={},
        execution_input_ciphertext=None,
        policy_json={"storage_mode": "result_only"},
    )


def test_media_derivative_artifact_correlation_scope_ttl_and_cleanup_handoff(
    runtime_context: RuntimeContext,
) -> None:
    run_id = _enqueue_and_process(
        runtime_context,
        source_bytes=_png_bytes(),
        idempotency_key="idem-artifact-success",
    )

    with get_session(runtime_context.database_url) as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        assert run.status == "succeeded"
        assert isinstance(run.result_json, dict)
        result_artifact = run.result_json["artifact"]
        artifact = session.scalar(select(MediaArtifact).where(MediaArtifact.run_id == run_id))
        assert artifact is not None
        assert artifact.run_id == run.run_id
        assert artifact.site_id == run.site_id == "site_alpha"
        assert result_artifact["artifact_id"] == artifact.artifact_id
        assert result_artifact["artifact_reference"] == {"artifact_id": artifact.artifact_id}
        assert datetime.fromisoformat(result_artifact["expires_at"]) == _as_utc(artifact.expires_at)
        ttl = _as_utc(artifact.expires_at) - _as_utc(artifact.created_at)
        assert timedelta(minutes=6, seconds=45) <= ttl <= timedelta(minutes=7, seconds=15)

        assert get_artifact(session, artifact.artifact_id, site_id="site_alpha") is artifact
        assert get_artifact(session, artifact.artifact_id, site_id="site_beta") is None
        artifact_id = artifact.artifact_id
        cleanup_at = _as_utc(artifact.expires_at) + timedelta(seconds=1)

        class FailingDeleteStore:
            def delete(self, storage_key: str) -> None:
                raise ArtifactStoreError(f"cannot delete {storage_key}")

        assert (
            cleanup_expired_artifacts(
                database_url=runtime_context.database_url,
                artifact_store=FailingDeleteStore(),  # type: ignore[arg-type]
                now=cleanup_at,
                session=session,
            )
            == 0
        )
        assert artifact.status == "purge_pending"
        assert artifact.purged_at is None
        assert artifact.purge_attempt_count == 1
        assert artifact.purge_last_error_code == "artifact_store.delete_failed"
        assert "cannot delete" not in artifact.purge_last_error_code
        assert artifact.purge_next_attempt_at is not None
        retry_at = _as_utc(artifact.purge_next_attempt_at) + timedelta(seconds=1)
        assert (
            cleanup_expired_artifacts(
                database_url=runtime_context.database_url,
                artifact_store=runtime_context.service.artifact_store,
                now=retry_at,
                session=session,
            )
            == 2
        )
        assert artifact.purged_at is not None
        assert _as_utc(artifact.purged_at) == retry_at
        assert artifact.status == "purged"
        session.commit()

    with pytest.raises(RuntimeRunNotFoundError):
        runtime_context.service.get_run_result(run_id, site_id="site_beta")
    with get_session(runtime_context.database_url) as session:
        purged = get_artifact(session, artifact_id, site_id="site_alpha")
        assert purged is not None
        assert purged.purged_at is not None
        assert purged.status == "purged"


def test_cleanup_retry_backoff_prevents_failed_prefix_starvation(
    runtime_context: RuntimeContext,
) -> None:
    run_id = _enqueue_and_process(
        runtime_context,
        source_bytes=_png_bytes(),
        idempotency_key="idem-cleanup-starvation",
    )
    now = datetime.now(UTC)
    failure_ids = [f"art_fail_{index:03d}" for index in range(101)]
    success_ids = [f"art_success_{index:03d}" for index in range(101)]

    with get_session(runtime_context.database_url) as session:
        session.add_all(
            [
                MediaArtifact(
                    artifact_id=artifact_id,
                    run_id=run_id,
                    site_id="site_alpha",
                    media_kind="image",
                    operation="media_derivative",
                    content_type="image/png",
                    byte_size=1,
                    checksum=f"sha256:{index:064x}",
                    storage_key=f"fail_{index:03d}",
                    status="available",
                    format="png",
                    width=1,
                    height=1,
                    expires_at=now - timedelta(minutes=2),
                    created_at=now - timedelta(minutes=3),
                )
                for index, artifact_id in enumerate(failure_ids)
            ]
            + [
                MediaArtifact(
                    artifact_id=artifact_id,
                    run_id=run_id,
                    site_id="site_alpha",
                    media_kind="image",
                    operation="media_derivative",
                    content_type="image/png",
                    byte_size=1,
                    checksum=f"sha256:{index + 1000:064x}",
                    storage_key=f"success_{index:03d}",
                    status="available",
                    format="png",
                    width=1,
                    height=1,
                    expires_at=now - timedelta(minutes=1),
                    created_at=now - timedelta(minutes=3),
                )
                for index, artifact_id in enumerate(success_ids)
            ]
        )
        session.flush()

        class PrefixFailingStore:
            def __init__(self) -> None:
                self.attempted: list[str] = []

            def delete(self, storage_key: str) -> None:
                self.attempted.append(storage_key)
                if storage_key.startswith("fail_"):
                    raise ArtifactStoreError("injected delete failure")

        store = PrefixFailingStore()
        assert (
            cleanup_expired_artifacts(
                database_url=runtime_context.database_url,
                artifact_store=store,  # type: ignore[arg-type]
                now=now,
                session=session,
                batch_size=100,
            )
            == 0
        )
        assert len(store.attempted) == 100
        assert (
            cleanup_expired_artifacts(
                database_url=runtime_context.database_url,
                artifact_store=store,  # type: ignore[arg-type]
                now=now,
                session=session,
                batch_size=100,
            )
            == 99
        )
        assert len(store.attempted) == 200
        assert (
            cleanup_expired_artifacts(
                database_url=runtime_context.database_url,
                artifact_store=store,  # type: ignore[arg-type]
                now=now,
                session=session,
                batch_size=100,
            )
            == 2
        )
        assert len(store.attempted) == 202
        failed = list(
            session.scalars(select(MediaArtifact).where(MediaArtifact.artifact_id.in_(failure_ids)))
        )
        succeeded = list(
            session.scalars(select(MediaArtifact).where(MediaArtifact.artifact_id.in_(success_ids)))
        )
        assert {artifact.status for artifact in failed} == {"purge_pending"}
        assert {artifact.purge_last_error_code for artifact in failed} == {
            "artifact_store.delete_failed"
        }
        assert all("injected" not in str(artifact.purge_last_error_code) for artifact in failed)
        assert sum(artifact.status == "purged" for artifact in succeeded) == 101
        assert sum(artifact.status == "available" for artifact in succeeded) == 0

        first_retry_at = min(
            _as_utc(artifact.purge_next_attempt_at)
            for artifact in failed
            if artifact.purge_next_attempt_at is not None
        )
        assert (
            cleanup_expired_artifacts(
                database_url=runtime_context.database_url,
                artifact_store=store,  # type: ignore[arg-type]
                now=first_retry_at - timedelta(microseconds=1),
                session=session,
                batch_size=100,
            )
            == 0
        )
        assert len(store.attempted) == 202
        assert (
            cleanup_expired_artifacts(
                database_url=runtime_context.database_url,
                artifact_store=store,  # type: ignore[arg-type]
                now=first_retry_at,
                session=session,
                batch_size=100,
            )
            == 0
        )
        assert len(store.attempted) == 302
        assert sum(artifact.purge_attempt_count == 2 for artifact in failed) == 100


def test_media_derivative_source_failures_map_to_run_result_and_metric(
    runtime_context: RuntimeContext,
) -> None:
    source_artifact_id = _upload_source(
        runtime_context,
        source_bytes=_png_bytes(),
        idempotency_key="idem-artifact-bad-source",
    )
    invalid_bytes = b"not-an-image"
    stored = runtime_context.service.artifact_store.put(
        io.BytesIO(invalid_bytes),
        max_bytes=len(invalid_bytes),
        metadata={"media_kind": "image"},
    )
    with get_session(runtime_context.database_url) as session:
        source = session.get(MediaArtifact, source_artifact_id)
        assert source is not None
        source.storage_key = stored.storage_key
        source.byte_size = stored.byte_size
        source.checksum = stored.checksum
        session.commit()

    response = runtime_context.service.enqueue_media_job_run(
        site_id="site_alpha",
        input_payload=_media_input(source_artifact_id),
        idempotency_key="idem-artifact-bad-source",
        trace_id="trace-idem-artifact-bad-source",
    )
    processed = runtime_context.service.process_queued_runs(max_runs=1, timeout_seconds=0)
    assert [item["run_id"] for item in processed] == [response.run_id]
    run_id = response.run_id

    with get_session(runtime_context.database_url) as session:
        run = session.get(RunRecord, run_id)
        metric = session.scalar(
            select(MediaDerivativeJobMetric).where(MediaDerivativeJobMetric.run_id == run_id)
        )
        assert run is not None
        assert run.status == "failed"
        assert run.error_code == "media_derivative.source_decode_failed"
        assert run.result_json == {
            "status": "failed",
            "error_code": "media_derivative.source_decode_failed",
            "error_message": "source image could not be decoded",
        }
        assert metric is not None
        assert metric.run_id == run.run_id
        assert metric.site_id == run.site_id
        assert metric.status == "failed"
        assert metric.error_code == run.error_code
        assert metric.source_bytes == len(invalid_bytes)
        assert metric.output_bytes == 0
        assert metric.artifact_id is None


def test_audio_materialization_correlates_short_ttl_artifact_and_output_references(
    runtime_context: RuntimeContext,
) -> None:
    audio_bytes = b"ID3-characterization-audio"
    started_at = datetime.now(UTC)
    with get_session(runtime_context.database_url) as session:
        repository = RuntimeRepository(session)
        run = _create_audio_run(repository)
        result = runtime_context.service._materialize_audio_generation_output(
            run,
            repository=repository,
            provider_output={
                "artifact_type": "audio_generation_candidates",
                "audios": [
                    {
                        "b64_json": base64.b64encode(audio_bytes).decode("ascii"),
                        "format": "mp3",
                        "mime_type": "audio/mpeg",
                    }
                ],
            },
        )

        audio = result["audios"][0]
        artifact = session.get(MediaArtifact, audio["artifact_id"])
        assert artifact is not None
        assert artifact.run_id == run.run_id
        assert artifact.site_id == run.site_id == "site_alpha"
        assert artifact.media_kind == "audio"
        assert audio["artifact"]["artifact_id"] == artifact.artifact_id
        assert audio["artifact"]["artifact_reference"] == {"artifact_id": artifact.artifact_id}
        assert result["provider_response_format"] == "artifact_reference"
        assert {
            "url",
            "audio_url",
            "download_url",
            "authenticated_download_url",
            "subtitle_url",
            "b64_json",
        }.isdisjoint(audio)
        assert {"download_url", "authenticated_download_url"}.isdisjoint(audio["artifact"])
        assert result["audio_materialization"] == {
            "status": "materialized",
            "artifact_count": 1,
            "storage": "cloud_short_ttl_artifact",
            "direct_wordpress_write": False,
        }
        expires_at = _as_utc(artifact.expires_at)
        assert started_at + timedelta(minutes=2, seconds=50) <= expires_at
        assert expires_at <= datetime.now(UTC) + timedelta(minutes=3, seconds=10)


@pytest.mark.parametrize(
    "audios",
    [
        [],
        [{}],
        ["invalid"],
        [{"url": "relative-provider-path"}],
        [{"b64_json": ""}, {"b64_json": ""}],
    ],
)
def test_audio_materialization_fails_closed_without_one_materializable_candidate(
    runtime_context: RuntimeContext,
    audios: list[object],
) -> None:
    with get_session(runtime_context.database_url) as session:
        repository = RuntimeRepository(session)
        candidate_kind = type(audios[0]).__name__ if audios else "empty"
        run = _create_audio_run(
            repository,
            run_id=f"run_audio_invalid_{len(audios)}_{candidate_kind}",
        )
        with pytest.raises(AudioArtifactMaterializationError):
            runtime_context.service._materialize_audio_generation_output(
                run,
                repository=repository,
                provider_output={
                    "artifact_type": "audio_generation_candidates",
                    "contract_version": "audio_generation_result.v1",
                    "audios": audios,
                },
            )
        assert session.scalar(
            select(MediaArtifact).where(MediaArtifact.run_id == run.run_id)
        ) is None


def test_image_generation_materialization_returns_only_artifact_references(
    runtime_context: RuntimeContext,
) -> None:
    image_bytes = _png_bytes(width=64, height=48)
    candidate = ProviderMediaCandidate(
        index=1,
        content_bytes=image_bytes,
        claimed_mime_type="image/png",
        revised_prompt="A refined prompt.",
        claimed_width=64,
        claimed_height=48,
    )
    with get_session(runtime_context.database_url) as session:
        repository = RuntimeRepository(session)
        run = _create_image_generation_run(repository)
        result = runtime_context.service._materialize_image_generation_output(
            run,
            repository=repository,
            provider_output={"model_id": "grok-imagine", "candidate_count": 1},
            media_candidates=(candidate,),
        )
        artifact = session.execute(select(MediaArtifact)).scalar_one()

        assert result["artifact_type"] == "image_generation_artifacts"
        assert result["contract_version"] == "image_generation_result.v1"
        assert result["operation"] == "image.generate.v1"
        assert result["suggestion_only"] is True
        assert result["requires_local_review"] is True
        assert result["artifacts"] == [
            {
                "artifact_id": artifact.artifact_id,
                "artifact_reference": {"artifact_id": artifact.artifact_id},
                "status": "available",
                "media_kind": "image",
                "operation": "image.generate.v1",
                "content_type": "image/png",
                "format": "png",
                "width": 64,
                "height": 48,
                "filesize_bytes": artifact.byte_size,
                "checksum": artifact.checksum,
                "expires_at": result["artifacts"][0]["expires_at"],
            }
        ]
        assert artifact.run_id == run.run_id
        assert artifact.site_id == run.site_id
        assert artifact.operation == "image.generate.v1"
        assert artifact.storage_key not in str(result)

        invalid_run = _create_image_generation_run(
            repository,
            run_id="run_image_artifact_invalid",
        )
        with pytest.raises(ImageGenerationArtifactMaterializationError) as error:
            runtime_context.service._materialize_image_generation_output(
                invalid_run,
                repository=repository,
                provider_output={"candidate_count": 1},
                media_candidates=(ProviderMediaCandidate(index=1, content_bytes=b"not-an-image"),),
            )
        assert error.value.error_code == "image_generation.artifact_materialization_failed"


def test_runtime_facade_retains_run_04_entrypoints_with_extracted_delegation() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    service_path = repository_root / "app/domain/runtime/service.py"
    source = service_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    runtime_service = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "RuntimeService"
    )
    methods = {
        node.name: node
        for node in runtime_service.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    expected_calls = {
        "create_media_upload": ("artifact_coordination_service.create_media_upload"),
        "enqueue_media_job_run": ("artifact_coordination_service.enqueue_media_job_run"),
        "_execute_media_derivative_run": (
            "artifact_coordination_service.execute_media_derivative_run"
        ),
        "_materialize_audio_generation_output": (
            "artifact_coordination_service.materialize_audio_generation_output"
        ),
        "_materialize_image_generation_output": (
            "artifact_coordination_service.materialize_image_generation_output"
        ),
    }

    assert expected_calls.keys() <= methods.keys()
    for method_name, expected_call in expected_calls.items():
        assert source.count(f"def {method_name}(") == 1
        assert expected_call in ast.unparse(methods[method_name])
    for method_name in expected_calls:
        assert len(methods[method_name].body) == 1
