from __future__ import annotations

import ast
import hashlib
import io
import json
from collections.abc import Iterator
from dataclasses import FrozenInstanceError, asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.adapters.providers.base import ProviderMediaCandidate
from app.adapters.repositories.runtime_repository import RuntimeRepository
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    MediaArtifact,
    MediaDerivativeJobMetric,
    RunRecord,
    Site,
)
from app.domain.audio_generation.artifacts import AudioArtifactMaterializationConfig
from app.domain.image_generation.materialization import ImageGenerationMaterializationConfig
from app.domain.media_artifacts import LocalVolumeArtifactStore
from app.domain.media_derivatives.artifacts import ValidatedImageUpload
from app.domain.media_derivatives.errors import (
    MediaDerivativeOutputTooLargeError,
    MediaDerivativeSourceDecodeFailedError,
)
from app.domain.media_derivatives.processor import MediaDerivativeResult
from app.domain.runtime import artifact_coordination
from app.domain.runtime.artifact_coordination import (
    RuntimeArtifactCoordinationConfig,
    RuntimeArtifactCoordinationDependencies,
    RuntimeArtifactCoordinationService,
)
from app.domain.runtime.models import RuntimeExecutionResponse
from app.domain.runtime.run_lifecycle import RuntimeRunCreationCommand


@dataclass
class RecordingRunController:
    fingerprint_calls: list[dict[str, object]] = field(default_factory=list)
    creation_commands: list[RuntimeRunCreationCommand] = field(default_factory=list)
    published_run_ids: list[str] = field(default_factory=list)

    def build_media_derivative_request_fingerprint(
        self,
        site_id: str,
        input_payload: dict[str, Any],
        *,
        source_checksum: str,
        watermark_checksum: str = "",
    ) -> str:
        self.fingerprint_calls.append(
            {
                "site_id": site_id,
                "input_payload": input_payload,
                "source_checksum": source_checksum,
                "watermark_checksum": watermark_checksum,
            }
        )
        return f"fingerprint:{site_id}:{source_checksum}:{watermark_checksum}"

    def get_idempotent_replay(
        self,
        *,
        repository: RuntimeRepository,
        site_id: str,
        idempotency_key: str | None,
        request_fingerprint: str,
    ) -> RunRecord | None:
        if not idempotency_key:
            return None
        existing = repository.get_run_by_idempotency(site_id, idempotency_key)
        if existing is not None:
            assert existing.request_fingerprint == request_fingerprint
        return existing

    def create_durable_run(
        self,
        *,
        repository: RuntimeRepository,
        command: RuntimeRunCreationCommand,
    ) -> RunRecord:
        self.creation_commands.append(command)
        return repository.create_run(**asdict(command))

    def publish_queue_signal(self, run_id: str) -> None:
        self.published_run_ids.append(run_id)

    def fail_run(
        self,
        repository: RuntimeRepository,
        run: RunRecord,
        *,
        error_code: str,
        error_message: str,
        provider_id: str | None = None,
        model_id: str | None = None,
        instance_id: str | None = None,
        fallback_used: bool | None = None,
    ) -> RunRecord:
        return repository.mark_run_failed(
            run,
            error_code=error_code,
            error_message=error_message,
            provider_id=provider_id,
            model_id=model_id,
            instance_id=instance_id,
            fallback_used=fallback_used,
        )

    def succeed_run(
        self,
        repository: RuntimeRepository,
        run: RunRecord,
        *,
        result_json: dict[str, Any],
        provider_id: str,
        model_id: str,
        instance_id: str,
        fallback_used: bool,
    ) -> RunRecord:
        return repository.mark_run_succeeded(
            run,
            result_json=result_json,
            provider_id=provider_id,
            model_id=model_id,
            instance_id=instance_id,
            fallback_used=fallback_used,
        )


@dataclass
class RecordingCoordinationDependencies:
    database_url: str
    active_site_calls: list[str] = field(default_factory=list)
    authorization_calls: list[dict[str, object]] = field(default_factory=list)
    acceptance_run_ids: list[str] = field(default_factory=list)
    credit_calls: list[dict[str, object]] = field(default_factory=list)
    encrypted_inputs: list[dict[str, object]] = field(default_factory=list)
    response_calls: list[dict[str, object]] = field(default_factory=list)

    def active_site_guard(
        self,
        repository: RuntimeRepository,
        site_id: str,
    ) -> object:
        self.active_site_calls.append(site_id)
        site = repository.get_site(site_id)
        assert site is not None
        assert site.status == "active"
        return site

    def commercial_authorizer(
        self,
        *,
        session: Any,
        site_id: str,
        ability_family: str,
        channel: str,
        execution_kind: str,
        execution_tier: str,
        data_classification: str,
        trace_id: str,
        idempotency_key: str | None,
        request_kind: str,
        run_id: str | None,
        estimated_ai_credits: float,
    ) -> dict[str, object]:
        self.authorization_calls.append(
            {
                "session": session,
                "site_id": site_id,
                "ability_family": ability_family,
                "channel": channel,
                "execution_kind": execution_kind,
                "execution_tier": execution_tier,
                "data_classification": data_classification,
                "trace_id": trace_id,
                "idempotency_key": idempotency_key,
                "request_kind": request_kind,
                "run_id": run_id,
                "estimated_ai_credits": estimated_ai_credits,
            }
        )
        return {
            "account_id": "account_alpha",
            "subscription_id": "subscription_alpha",
            "plan_version_id": "plan_version_alpha",
        }

    def commercial_acceptance_recorder(
        self,
        *,
        session: Any,
        run: RunRecord,
    ) -> None:
        assert session is not None
        self.acceptance_run_ids.append(run.run_id)

    def credit_estimator(
        self,
        *,
        ability_family: str | None,
        execution_kind: str | None,
        payload_json: dict[str, object] | None = None,
    ) -> float:
        self.credit_calls.append(
            {
                "ability_family": ability_family or "",
                "execution_kind": execution_kind or "",
                "payload_json": payload_json or {},
            }
        )
        return 2.5

    def execution_input_encryptor(self, input_payload: dict[str, object]) -> str:
        self.encrypted_inputs.append(dict(input_payload))
        return "encrypted-media-input"

    def execution_response_builder(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        idempotent_replay: bool,
    ) -> RuntimeExecutionResponse:
        self.response_calls.append(
            {
                "run_id": run.run_id,
                "idempotent_replay": idempotent_replay,
                "session_in_transaction": repository.session.in_transaction(),
            }
        )
        return cast(
            RuntimeExecutionResponse,
            SimpleNamespace(
                run_id=run.run_id,
                status=run.status,
                idempotent_replay=idempotent_replay,
            ),
        )

    def build(self) -> RuntimeArtifactCoordinationDependencies:
        return RuntimeArtifactCoordinationDependencies(
            database_url=self.database_url,
            active_site_guard=self.active_site_guard,
            commercial_authorizer=self.commercial_authorizer,
            commercial_acceptance_recorder=self.commercial_acceptance_recorder,
            credit_estimator=self.credit_estimator,
            execution_input_encryptor=self.execution_input_encryptor,
            execution_response_builder=self.execution_response_builder,
            artifact_store=LocalVolumeArtifactStore(
                Path(self.database_url.removeprefix("sqlite+pysqlite:///")).parent / "artifacts"
            ),
        )


@pytest.fixture
def database_url(tmp_path: Path) -> Iterator[str]:
    url = f"sqlite+pysqlite:///{tmp_path / 'runtime-artifact-coordination.sqlite3'}"
    init_schema(url)
    with get_session(url) as session:
        session.add(Site(site_id="site_alpha", name="Alpha", status="active"))
        session.commit()
    yield url
    dispose_engine(url)


def _create_run(repository: RuntimeRepository, *, run_id: str) -> RunRecord:
    return repository.create_run(
        run_id=run_id,
        site_id="site_alpha",
        account_id=None,
        subscription_id=None,
        plan_version_id=None,
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
        status="running",
        idempotency_key=f"idem-{run_id}",
        request_fingerprint=f"fingerprint-{run_id}",
        trace_id=f"trace-{run_id}",
        input_json={},
        execution_input_ciphertext=None,
        policy_json={"storage_mode": "result_only"},
    )


def _service(
    *,
    database_url: str,
    input_payload: dict[str, Any] | None = None,
    config: RuntimeArtifactCoordinationConfig | None = None,
) -> RuntimeArtifactCoordinationService:
    return RuntimeArtifactCoordinationService(
        config=config or RuntimeArtifactCoordinationConfig(),
        dependencies=RecordingCoordinationDependencies(database_url).build(),
        run_controller=RecordingRunController(),
        execution_input_loader=lambda run: input_payload or {},
    )


def _seed_artifact(
    *,
    database_url: str,
    session: Any,
    artifact_id: str,
    payload: bytes,
) -> MediaArtifact:
    store = LocalVolumeArtifactStore(
        Path(database_url.removeprefix("sqlite+pysqlite:///")).parent / "artifacts"
    )
    stored = store.put(
        io.BytesIO(payload),
        max_bytes=max(1, len(payload)),
        metadata={"media_kind": "image"},
    )
    artifact = MediaArtifact(
        artifact_id=artifact_id,
        run_id=f"run-upload-{artifact_id}",
        site_id="site_alpha",
        media_kind="image",
        operation="image.upload.v1",
        content_type="image/png",
        byte_size=stored.byte_size,
        checksum=stored.checksum,
        storage_key=stored.storage_key,
        status="available",
        format="png",
        width=64,
        height=48,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    session.add(artifact)
    session.flush()
    return artifact


def test_artifact_coordination_config_is_frozen() -> None:
    config = RuntimeArtifactCoordinationConfig(audio_artifact_ttl_minutes=9)

    with pytest.raises(FrozenInstanceError):
        config.audio_artifact_ttl_minutes = 10  # type: ignore[misc]


def test_enqueue_media_job_run_uses_injected_dependencies_and_exact_command(
    database_url: str,
) -> None:
    controller = RecordingRunController()
    dependencies = RecordingCoordinationDependencies(database_url)
    config = RuntimeArtifactCoordinationConfig(
        media_derivative_batch_default_chunk_size=6,
        media_derivative_batch_max_chunk_size=12,
        media_derivative_site_queued_limit=20,
        media_derivative_site_running_limit=2,
    )
    service = RuntimeArtifactCoordinationService(
        config=config,
        dependencies=dependencies.build(),
        run_controller=controller,
        execution_input_loader=lambda run: {},
    )
    source_id = "art_source_exact"
    watermark_id = "art_watermark_exact"
    with get_session(database_url) as session:
        source = _seed_artifact(
            database_url=database_url,
            session=session,
            artifact_id=source_id,
            payload=b"source-image",
        )
        watermark = _seed_artifact(
            database_url=database_url,
            session=session,
            artifact_id=watermark_id,
            payload=b"watermark-image",
        )
        source_checksum = source.checksum
        watermark_checksum = watermark.checksum
        session.commit()
    input_payload: dict[str, Any] = {
        "request_contract_version": "media_job_request.v1",
        "operation": "image.transform.v1",
        "source_artifact_id": source_id,
        "watermark_artifact_id": watermark_id,
        "params": {
            "target_format": "avif",
            "max_width": 1200,
            "quality": 82,
            "source_media_type": "image",
        },
        "batch_context": {
            "batch_id": "batch-alpha",
            "item_index": "2",
            "item_count": "invalid",
            "explicit_avif": True,
        },
        "result_ttl_minutes": 13,
    }

    response = service.enqueue_media_job_run(
        site_id="site_alpha",
        input_payload=input_payload,
        idempotency_key="idem-direct-enqueue",
        trace_id="trace-direct-enqueue",
    )

    assert response.status == "queued"
    assert response.idempotent_replay is False
    assert dependencies.active_site_calls == ["site_alpha"]
    assert dependencies.credit_calls == [
        {
            "ability_family": "vision",
            "execution_kind": "media_derivative",
            "payload_json": input_payload,
        }
    ]
    assert len(dependencies.authorization_calls) == 1
    authorization_call = dependencies.authorization_calls[0]
    assert {key: value for key, value in authorization_call.items() if key != "session"} == {
        "site_id": "site_alpha",
        "ability_family": "vision",
        "channel": "openapi",
        "execution_kind": "media_derivative",
        "execution_tier": "cloud",
        "data_classification": "internal",
        "trace_id": "trace-direct-enqueue",
        "idempotency_key": "idem-direct-enqueue",
        "request_kind": "execute",
        "run_id": response.run_id,
        "estimated_ai_credits": 2.5,
    }
    assert controller.fingerprint_calls == [
        {
            "site_id": "site_alpha",
            "input_payload": input_payload,
            "source_checksum": source_checksum,
            "watermark_checksum": watermark_checksum,
        }
    ]
    assert len(controller.creation_commands) == 1
    command = controller.creation_commands[0]
    assert command.run_id == response.run_id
    assert command.run_id.startswith("run_")
    assert command.site_id == "site_alpha"
    assert command.account_id == "account_alpha"
    assert command.subscription_id == "subscription_alpha"
    assert command.plan_version_id == "plan_version_alpha"
    assert command.idempotency_key == "idem-direct-enqueue"
    assert command.trace_id == "trace-direct-enqueue"
    assert command.request_fingerprint.startswith("fingerprint:site_alpha:")
    assert command.status == "queued"
    assert command.execution_input_ciphertext == "encrypted-media-input"
    assert command.input_json == input_payload
    assert command.selected_provider_id == "media_processor"
    assert command.selected_model_id == "pillow"
    assert command.selected_instance_id == "cloud-worker"
    assert command.policy_json == {
        "storage_mode": "result_only",
        "media_derivative": {
            "target_format": "avif",
            "source_media_type": "image",
            "batch_context": {
                "batch_id": "batch-alpha",
                "item_index": 2,
                "item_count": 1,
                "chunk_size": 6,
                "explicit_avif": True,
            },
            "limits": {
                "site_queued": 20,
                "site_running": 2,
                "batch_max_chunk_size": 12,
            },
            "write_posture": "artifact_only",
            "direct_wordpress_write": False,
        },
        "execution_contract": {
            "ability_name": "media_image_transform",
            "contract_version": "media_job_request.v1",
            "profile_id": "media.transform.worker",
            "execution_pattern": "whole_run_offload",
            "data_classification": "internal",
            "storage_mode": "result_only",
            "timeout_seconds": 300,
            "retry_max": 0,
            "retention_ttl": 780,
            "task_backend": {"enabled": True},
        },
    }
    assert dependencies.encrypted_inputs == [input_payload]
    serialized_inputs = json.dumps(dependencies.encrypted_inputs)
    assert "storage_key" not in serialized_inputs
    assert "base64" not in serialized_inputs.lower()
    assert "_bytes_b64" not in serialized_inputs
    assert dependencies.acceptance_run_ids == [response.run_id]
    assert controller.published_run_ids == [response.run_id]
    assert dependencies.response_calls == [
        {
            "run_id": response.run_id,
            "idempotent_replay": False,
            "session_in_transaction": False,
        }
    ]
    with get_session(database_url) as session:
        persisted = session.get(RunRecord, response.run_id)
        assert persisted is not None
        assert persisted.status == "queued"


def test_enqueue_media_job_replay_skips_side_effect_dependencies(
    database_url: str,
) -> None:
    controller = RecordingRunController()
    dependencies = RecordingCoordinationDependencies(database_url)
    service = RuntimeArtifactCoordinationService(
        config=RuntimeArtifactCoordinationConfig(),
        dependencies=dependencies.build(),
        run_controller=controller,
        execution_input_loader=lambda run: {},
    )
    source_id = "art_source_replay"
    with get_session(database_url) as session:
        _seed_artifact(
            database_url=database_url,
            session=session,
            artifact_id=source_id,
            payload=b"same-source",
        )
        session.commit()
    input_payload = {
        "request_contract_version": "media_job_request.v1",
        "operation": "image.transform.v1",
        "source_artifact_id": source_id,
        "params": {
            "target_format": "webp",
            "max_width": 1200,
            "quality": 82,
            "source_media_type": "image",
        },
        "result_ttl_minutes": 60,
    }

    first = service.enqueue_media_job_run(
        site_id="site_alpha",
        input_payload=input_payload,
        idempotency_key="idem-direct-replay",
        trace_id="trace-direct-replay",
    )
    replay = service.enqueue_media_job_run(
        site_id="site_alpha",
        input_payload=input_payload,
        idempotency_key="idem-direct-replay",
        trace_id="trace-direct-replay",
    )

    assert replay.run_id == first.run_id
    assert replay.idempotent_replay is True
    assert len(controller.fingerprint_calls) == 2
    assert len(controller.creation_commands) == 1
    assert controller.published_run_ids == [first.run_id]
    assert dependencies.active_site_calls == ["site_alpha", "site_alpha"]
    assert len(dependencies.authorization_calls) == 1
    assert len(dependencies.credit_calls) == 1
    assert len(dependencies.encrypted_inputs) == 1
    assert dependencies.acceptance_run_ids == [first.run_id]
    assert dependencies.response_calls == [
        {
            "run_id": first.run_id,
            "idempotent_replay": False,
            "session_in_transaction": False,
        },
        {
            "run_id": first.run_id,
            "idempotent_replay": True,
            "session_in_transaction": False,
        },
    ]


def test_enqueue_media_job_unique_race_reloads_winner_without_loser_side_effects(
    database_url: str,
) -> None:
    winner_run_id = "run_media_job_race_winner"

    class SimulatedUniqueRaceController(RecordingRunController):
        def create_durable_run(
            self,
            *,
            repository: RuntimeRepository,
            command: RuntimeRunCreationCommand,
        ) -> RunRecord:
            self.creation_commands.append(command)
            with get_session(database_url) as winner_session:
                winner_repository = RuntimeRepository(winner_session)
                winner_repository.create_run(
                    **asdict(
                        replace(
                            command,
                            run_id=winner_run_id,
                            trace_id="trace-media-job-race-winner",
                        )
                    )
                )
                winner_session.commit()
            raise IntegrityError(
                "INSERT INTO run_records",
                {"site_id": command.site_id, "idempotency_key": command.idempotency_key},
                Exception("uq_run_records_site_idempotency"),
            )

    controller = SimulatedUniqueRaceController()
    dependencies = RecordingCoordinationDependencies(database_url)
    service = RuntimeArtifactCoordinationService(
        config=RuntimeArtifactCoordinationConfig(),
        dependencies=dependencies.build(),
        run_controller=controller,
        execution_input_loader=lambda run: {},
    )
    source_id = "art_source_unique_race"
    with get_session(database_url) as session:
        _seed_artifact(
            database_url=database_url,
            session=session,
            artifact_id=source_id,
            payload=b"race-source",
        )
        session.commit()
    input_payload = {
        "request_contract_version": "media_job_request.v1",
        "operation": "image.transform.v1",
        "source_artifact_id": source_id,
        "params": {
            "target_format": "webp",
            "max_width": 1200,
            "quality": 82,
            "source_media_type": "image",
        },
        "result_ttl_minutes": 30,
    }

    response = service.enqueue_media_job_run(
        site_id="site_alpha",
        input_payload=input_payload,
        idempotency_key="idem-media-job-unique-race",
        trace_id="trace-media-job-race-loser",
    )

    assert response.run_id == winner_run_id
    assert response.idempotent_replay is True
    assert len(controller.creation_commands) == 1
    assert dependencies.active_site_calls == ["site_alpha", "site_alpha"]
    assert len(dependencies.authorization_calls) == 1
    assert len(dependencies.credit_calls) == 1
    assert dependencies.encrypted_inputs == [input_payload]
    assert dependencies.acceptance_run_ids == []
    assert controller.published_run_ids == []
    assert dependencies.response_calls == [
        {
            "run_id": winner_run_id,
            "idempotent_replay": True,
            "session_in_transaction": False,
        }
    ]
    with get_session(database_url) as session:
        persisted = list(
            session.scalars(
                select(RunRecord).where(
                    RunRecord.site_id == "site_alpha",
                    RunRecord.idempotency_key == "idem-media-job-unique-race",
                )
            )
        )
        assert [run.run_id for run in persisted] == [winner_run_id]


def test_media_upload_integrity_race_rolls_back_object_before_loading_replay(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SimulatedUploadRaceController(RecordingRunController):
        def create_durable_run(
            self,
            *,
            repository: RuntimeRepository,
            command: RuntimeRunCreationCommand,
        ) -> RunRecord:
            del repository
            self.creation_commands.append(command)
            raise IntegrityError(
                "INSERT INTO run_records",
                {"site_id": command.site_id, "idempotency_key": command.idempotency_key},
                Exception("uq_run_records_site_idempotency"),
            )

    controller = SimulatedUploadRaceController()
    recording_dependencies = RecordingCoordinationDependencies(database_url)
    dependencies = recording_dependencies.build()
    service = RuntimeArtifactCoordinationService(
        config=RuntimeArtifactCoordinationConfig(),
        dependencies=dependencies,
        run_controller=controller,
        execution_input_loader=lambda run: {},
    )
    artifact_root = Path(database_url.removeprefix("sqlite+pysqlite:///")).parent / "artifacts"
    replay_calls: list[dict[str, str]] = []

    def load_replay_after_race(**kwargs: str) -> RuntimeExecutionResponse:
        assert not [path for path in artifact_root.rglob("obj_*") if path.is_file()]
        replay_calls.append(dict(kwargs))
        return cast(
            RuntimeExecutionResponse,
            SimpleNamespace(
                run_id="run_upload_race_winner",
                status="succeeded",
                idempotent_replay=True,
            ),
        )

    monkeypatch.setattr(
        service,
        "_load_upload_replay_after_race",
        load_replay_after_race,
    )
    payload = b"validated-upload-payload"
    checksum = f"sha256:{hashlib.sha256(payload).hexdigest()}"

    response = service.create_media_upload(
        site_id="site_alpha",
        request_payload={"request_contract_version": "media_upload_request.v1"},
        stream=io.BytesIO(payload),
        upload=ValidatedImageUpload(
            byte_size=len(payload),
            checksum=checksum,
            content_type="image/png",
            format="png",
            width=1,
            height=1,
        ),
        ttl_minutes=10,
        idempotency_key="idem-upload-race",
        trace_id="trace-upload-race",
    )

    assert response.run_id == "run_upload_race_winner"
    assert response.idempotent_replay is True
    assert replay_calls == [
        {
            "site_id": "site_alpha",
            "idempotency_key": "idem-upload-race",
            "request_fingerprint": f"fingerprint:site_alpha:{checksum}:",
            "upload_checksum": checksum,
        }
    ]


def test_execute_media_derivative_success_records_artifact_metric_and_terminal_evidence(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_bytes = b"source-image-bytes"

    def fake_process(**kwargs: Any) -> MediaDerivativeResult:
        assert kwargs == {
            "source_bytes": source_bytes,
            "source_media_type": "image",
            "target_format": "png",
            "max_width": 320,
            "quality": 77,
            "crop_options": None,
            "watermark_bytes": None,
            "watermark_options": None,
        }
        return MediaDerivativeResult(
            output_bytes=b"processed-image-bytes",
            width=320,
            height=200,
            filesize_bytes=len(b"processed-image-bytes"),
            checksum="sha256:processed",
            mime_type="image/png",
            format="png",
            source_width=640,
            source_height=400,
        )

    monkeypatch.setattr(artifact_coordination, "process_media_derivative", fake_process)
    source_artifact_id = "art_worker_success_source"
    service = _service(
        database_url=database_url,
        input_payload={
            "request_contract_version": "media_job_request.v1",
            "operation": "image.transform.v1",
            "source_artifact_id": source_artifact_id,
            "params": {
                "source_media_type": "image",
                "target_format": "png",
                "max_width": 320,
                "quality": 77,
            },
            "result_ttl_minutes": 11,
        },
    )

    with get_session(database_url) as session:
        repository = RuntimeRepository(session)
        run = _create_run(repository, run_id="run_artifact_success")
        _seed_artifact(
            database_url=database_url,
            session=session,
            artifact_id=source_artifact_id,
            payload=source_bytes,
        )
        service.execute_media_derivative_run(run, repository=repository)

        artifact = session.scalar(select(MediaArtifact).where(MediaArtifact.run_id == run.run_id))
        metric = session.scalar(
            select(MediaDerivativeJobMetric).where(MediaDerivativeJobMetric.run_id == run.run_id)
        )
        assert run.status == "succeeded"
        assert run.selected_provider_id == "media_derivative"
        assert run.selected_model_id == "pillow"
        assert run.selected_instance_id == "cloud-worker"
        assert run.fallback_used is False
        assert artifact is not None
        assert artifact.site_id == run.site_id
        assert isinstance(run.result_json, dict)
        assert run.result_json["artifact"]["artifact_id"] == artifact.artifact_id
        assert metric is not None
        assert metric.status == "succeeded"
        assert metric.artifact_id == artifact.artifact_id
        assert metric.source_bytes == len(source_bytes)
        assert metric.output_bytes == len(b"processed-image-bytes")


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_message"),
    [
        (
            MediaDerivativeSourceDecodeFailedError(),
            "media_derivative.source_decode_failed",
            "source image could not be decoded",
        ),
        (
            MediaDerivativeOutputTooLargeError(),
            "media_derivative.output_too_large",
            "generated derivative exceeds the deliverable artifact size limit",
        ),
    ],
)
def test_execute_media_derivative_domain_failure_preserves_result_and_metric(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_code: str,
    expected_message: str,
) -> None:
    source_bytes = b"bad-image"

    def fail_process(**kwargs: Any) -> MediaDerivativeResult:
        raise error

    monkeypatch.setattr(artifact_coordination, "process_media_derivative", fail_process)
    suffix = expected_code.rsplit(".", 1)[-1]
    source_artifact_id = f"art_worker_failure_{suffix}"
    service = _service(
        database_url=database_url,
        input_payload={
            "request_contract_version": "media_job_request.v1",
            "operation": "image.transform.v1",
            "source_artifact_id": source_artifact_id,
            "params": {
                "source_media_type": "image",
                "target_format": "webp",
            },
            "result_ttl_minutes": 60,
        },
    )

    with get_session(database_url) as session:
        repository = RuntimeRepository(session)
        run = _create_run(repository, run_id=f"run_artifact_failure_{suffix}")
        _seed_artifact(
            database_url=database_url,
            session=session,
            artifact_id=source_artifact_id,
            payload=source_bytes,
        )
        service.execute_media_derivative_run(run, repository=repository)

        metric = session.scalar(
            select(MediaDerivativeJobMetric).where(MediaDerivativeJobMetric.run_id == run.run_id)
        )
        assert run.status == "failed"
        assert run.error_code == expected_code
        assert run.result_json == {
            "status": "failed",
            "error_code": expected_code,
            "error_message": expected_message,
        }
        assert metric is not None
        assert metric.status == "failed"
        assert metric.error_code == run.error_code
        assert metric.source_bytes == len(source_bytes)
        assert metric.output_bytes == 0
        assert metric.artifact_id is None


def test_audio_and_image_generation_wrappers_delegate_with_frozen_config(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_audio_materialization(
        *,
        session: Any,
        run: RunRecord,
        result_json: dict[str, Any],
        config: AudioArtifactMaterializationConfig,
        artifact_store: Any,
    ) -> dict[str, Any]:
        captured["audio_session"] = session
        captured["audio_run"] = run
        captured["audio_input"] = result_json
        captured["audio_config"] = config
        captured["artifact_store"] = artifact_store
        return {"audio": "materialized"}

    def fake_image_materialization(
        *,
        session: Any,
        artifact_store: Any,
        run: RunRecord,
        media_candidates: Any,
        provider_output: dict[str, Any],
        config: ImageGenerationMaterializationConfig,
    ) -> dict[str, Any]:
        captured["image_session"] = session
        captured["image_store"] = artifact_store
        captured["image_run"] = run
        captured["image_candidates"] = media_candidates
        captured["image_input"] = provider_output
        captured["image_config"] = config
        return {"image": "materialized"}

    monkeypatch.setattr(
        artifact_coordination,
        "materialize_audio_generation_candidates",
        fake_audio_materialization,
    )
    monkeypatch.setattr(
        artifact_coordination,
        "materialize_image_generation_candidates",
        fake_image_materialization,
    )
    config = RuntimeArtifactCoordinationConfig(
        audio_artifact_ttl_minutes=9,
        audio_artifact_max_bytes=1234,
        audio_artifact_download_timeout_seconds=2.5,
        image_generation_artifact_ttl_minutes=7,
        image_generation_max_image_bytes=5678,
        image_generation_max_run_bytes=6789,
        image_generation_download_timeout_seconds=3.5,
    )
    service = _service(database_url=database_url, config=config)

    with get_session(database_url) as session:
        repository = RuntimeRepository(session)
        run = _create_run(repository, run_id="run_artifact_wrappers")
        audio_input = {"artifact_type": "audio_generation_candidates"}
        image_input = {"artifact_type": "image_generation_candidates"}
        image_candidates = (
            ProviderMediaCandidate(index=1, content_bytes=b"image"),
        )

        assert service.materialize_audio_generation_output(
            run,
            repository=repository,
            provider_output=audio_input,
        ) == {"audio": "materialized"}
        assert service.materialize_image_generation_output(
            run,
            repository=repository,
            provider_output=image_input,
            media_candidates=image_candidates,
        ) == {"image": "materialized"}
        assert captured["audio_session"] is session
        assert captured["audio_run"] is run
        assert captured["audio_input"] is audio_input
        assert captured["audio_config"] == AudioArtifactMaterializationConfig(
            ttl_minutes=9,
            max_bytes=1234,
            timeout_seconds=2.5,
        )
        assert captured["image_session"] is session
        assert captured["image_store"] is captured["artifact_store"]
        assert captured["image_run"] is run
        assert captured["image_candidates"] is image_candidates
        assert captured["image_input"] is image_input
        assert captured["image_config"] == ImageGenerationMaterializationConfig(
            ttl_minutes=7,
            max_image_bytes=5678,
            max_run_bytes=6789,
            timeout_seconds=3.5,
        )


def test_artifact_coordination_module_and_runtime_facade_keep_boundaries() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    module_path = repository_root / "app/domain/runtime/artifact_coordination.py"
    service_path = repository_root / "app/domain/runtime/service.py"
    module_tree = ast.parse(module_path.read_text(encoding="utf-8"))
    service_source = service_path.read_text(encoding="utf-8")

    imported_modules = {
        node.module or "" for node in ast.walk(module_tree) if isinstance(node, ast.ImportFrom)
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(module_tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    forbidden_prefixes = (
        "app.domain.runtime.service",
        "app.core.config",
        "app.domain.commercial",
        "app.domain.routing",
        "app.adapters.providers",
        "app.domain.wordpress",
        "app.domain.connector_runtime",
        "app.domain.runtime.callback_delivery",
        "app.api",
        "fastapi",
    )
    assert not {
        module
        for module in imported_modules
        if any(module.startswith(prefix) for prefix in forbidden_prefixes)
    }

    forbidden_service_calls = (
        "process_media_derivative(",
        "create_artifact(",
        "record_media_derivative_job_metric(",
        "materialize_audio_generation_candidates(",
        "materialize_image_generation_candidates(",
    )
    assert not {call for call in forbidden_service_calls if call in service_source}
    assert "except ImageGenerationArtifactMaterializationError as error:" in service_source
    assert "except AudioArtifactMaterializationError as error:" in service_source
