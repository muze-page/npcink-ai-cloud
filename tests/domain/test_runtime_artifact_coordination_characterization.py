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

from app.adapters.queue.in_memory import InMemoryRuntimeQueue
from app.adapters.repositories.runtime_repository import RuntimeRepository
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    MediaDerivativeArtifact,
    MediaDerivativeJobMetric,
    RunRecord,
)
from app.domain.image_generation import inline_images
from app.domain.media_derivatives.artifacts import (
    cleanup_expired_artifacts,
    get_artifact,
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


def _media_input(*, ttl_minutes: int = 7) -> dict[str, Any]:
    return {
        "cloud_job_payload": {
            "job_type": "generate_optimized_media_derivative",
            "target_format": "png",
            "max_width": 32,
            "quality": 80,
            "source_media_type": "image",
        },
        "source_media_type": "image",
        "ttl_minutes": ttl_minutes,
    }


def _enqueue_and_process(
    context: RuntimeContext,
    *,
    source_bytes: bytes,
    idempotency_key: str,
    ttl_minutes: int = 7,
) -> str:
    response = context.service.enqueue_media_derivative_run(
        site_id="site_alpha",
        input_payload=_media_input(ttl_minutes=ttl_minutes),
        source_bytes=source_bytes,
        ttl_minutes=ttl_minutes,
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


def _create_audio_run(repository: RuntimeRepository) -> RunRecord:
    return repository.create_run(
        run_id="run_audio_artifact_characterization",
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
        idempotency_key="idem-audio-artifact-characterization",
        request_fingerprint="fingerprint-audio-artifact-characterization",
        trace_id="trace-audio-artifact-characterization",
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
        artifact = session.scalar(
            select(MediaDerivativeArtifact).where(MediaDerivativeArtifact.run_id == run_id)
        )
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
        assert (
            cleanup_expired_artifacts(
                database_url=runtime_context.database_url,
                now=cleanup_at,
                session=session,
            )
            == 1
        )
        assert artifact.purged_at is not None
        assert _as_utc(artifact.purged_at) == cleanup_at
        assert artifact.blob_data == b""
        session.commit()

    with pytest.raises(RuntimeRunNotFoundError):
        runtime_context.service.get_run_result(run_id, site_id="site_beta")
    with get_session(runtime_context.database_url) as session:
        purged = get_artifact(session, artifact_id, site_id="site_alpha")
        assert purged is not None
        assert purged.purged_at is not None
        assert purged.blob_data == b""


@pytest.mark.parametrize(
    ("source_bytes", "expected_source_bytes", "idempotency_key"),
    [
        (b"", 0, "idem-artifact-no-source"),
        (b"not-an-image", len(b"not-an-image"), "idem-artifact-bad-source"),
    ],
)
def test_media_derivative_source_failures_map_to_run_result_and_metric(
    runtime_context: RuntimeContext,
    source_bytes: bytes,
    expected_source_bytes: int,
    idempotency_key: str,
) -> None:
    run_id = _enqueue_and_process(
        runtime_context,
        source_bytes=source_bytes,
        idempotency_key=idempotency_key,
    )

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
            "error_message": (
                "no source bytes found in media derivative run"
                if not source_bytes
                else "source image could not be decoded"
            ),
        }
        assert metric is not None
        assert metric.run_id == run.run_id
        assert metric.site_id == run.site_id
        assert metric.status == "failed"
        assert metric.error_code == run.error_code
        assert metric.source_bytes == expected_source_bytes
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
        artifact = session.get(MediaDerivativeArtifact, audio["artifact_id"])
        assert artifact is not None
        assert artifact.run_id == run.run_id
        assert artifact.site_id == run.site_id == "site_alpha"
        assert artifact.source_media_type == "audio"
        assert artifact.blob_data == audio_bytes
        assert audio["artifact"]["artifact_id"] == artifact.artifact_id
        assert audio["artifact"]["artifact_reference"] == {"artifact_id": artifact.artifact_id}
        assert audio["url"] == audio["audio_url"] == audio["download_url"]
        assert audio["artifact"]["download_url"] == audio["url"]
        assert audio["artifact"]["authenticated_download_url"] == (
            f"/v1/runtime/artifacts/{artifact.artifact_id}/download"
        )
        assert result["audio_materialization"] == {
            "status": "materialized",
            "artifact_count": 1,
            "storage": "cloud_short_ttl_artifact",
            "direct_wordpress_write": False,
        }
        expires_at = _as_utc(artifact.expires_at)
        assert started_at + timedelta(minutes=2, seconds=50) <= expires_at
        assert expires_at <= datetime.now(UTC) + timedelta(minutes=3, seconds=10)


def test_wordpress_inline_image_url_materialization_success_and_failure(
    runtime_context: RuntimeContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_download(
        source_url: str,
        *,
        config: inline_images.InlineImageMaterializationConfig,
    ) -> tuple[bytes, str]:
        assert source_url == "https://provider.example.test/generated.png"
        assert config.max_bytes > 0
        return b"inline-image-bytes", "image/png"

    monkeypatch.setattr(inline_images, "_download_image_url", fake_download)
    result = runtime_context.service._materialize_wordpress_ai_inline_image_output(
        {
            "artifact_type": "image_generation_candidates",
            "images": [
                {
                    "url": "https://provider.example.test/generated.png",
                    "b64_json": "",
                }
            ],
            "provider_response_format": "url",
        }
    )
    assert result["provider_response_format"] == "b64_json"
    assert result["inline_materialized_from_url"] is True
    assert result["inline_materialized_count"] == 1
    assert result["images"][0]["b64_json"] == base64.b64encode(b"inline-image-bytes").decode(
        "ascii"
    )

    monkeypatch.undo()
    with pytest.raises(inline_images.InlineImageMaterializationError) as error:
        runtime_context.service._materialize_wordpress_ai_inline_image_output(
            {
                "artifact_type": "image_generation_candidates",
                "images": [{"url": "http://provider.example.test/generated.png"}],
            }
        )
    assert error.value.error_code == "image_generation.inline_materialization_failed"
    assert error.value.message == "provider image URL must use HTTPS"


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
        "enqueue_media_derivative_run": (
            "artifact_coordination_service.enqueue_media_derivative_run"
        ),
        "_execute_media_derivative_run": (
            "artifact_coordination_service.execute_media_derivative_run"
        ),
        "_materialize_audio_generation_output": (
            "artifact_coordination_service.materialize_audio_generation_output"
        ),
        "_materialize_wordpress_ai_inline_image_output": (
            "artifact_coordination_service.materialize_inline_image_output"
        ),
    }

    assert expected_calls.keys() <= methods.keys()
    for method_name, expected_call in expected_calls.items():
        assert source.count(f"def {method_name}(") == 1
        assert expected_call in ast.unparse(methods[method_name])
    for method_name in expected_calls:
        assert len(methods[method_name].body) == 1
