from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO, Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.repositories.runtime_repository import RuntimeRepository
from app.core.db import get_session
from app.core.models import MediaArtifact, RunRecord
from app.domain.audio_generation.artifacts import (
    AUDIO_ARTIFACT_DEFAULT_MAX_BYTES,
    AUDIO_ARTIFACT_DEFAULT_TIMEOUT_SECONDS,
    AUDIO_ARTIFACT_DEFAULT_TTL_MINUTES,
    AudioArtifactMaterializationConfig,
    materialize_audio_generation_candidates,
)
from app.domain.image_generation.materialization import (
    IMAGE_GENERATION_DEFAULT_MAX_RUN_BYTES,
    IMAGE_GENERATION_DEFAULT_TTL_MINUTES,
    ImageGenerationMaterializationConfig,
    ProviderMediaCandidateLike,
    materialize_image_generation_candidates,
)
from app.domain.image_generation.provider_fetch import (
    PROVIDER_IMAGE_DEFAULT_MAX_BYTES,
    PROVIDER_IMAGE_DEFAULT_TIMEOUT_SECONDS,
)
from app.domain.media_artifacts import (
    ArtifactStore,
    ArtifactStoreError,
    read_artifact_bytes,
)
from app.domain.media_artifacts.publication import publish_and_track_artifact
from app.domain.media_derivatives.artifacts import (
    ValidatedImageUpload,
    build_artifact_result_json,
    build_upload_artifact_result_json,
    create_artifact,
    create_uploaded_artifact,
    is_artifact_expired,
)
from app.domain.media_derivatives.contracts import (
    ARTIFACT_DEFAULT_TTL_MINUTES,
    MAX_UPLOAD_BYTES_IMAGE,
)
from app.domain.media_derivatives.errors import (
    MediaDerivativeAnimatedSourceUnavailableError,
    MediaDerivativeErrorBase,
    MediaDerivativeFormatUnavailableError,
    MediaDerivativeOutputTooLargeError,
    MediaDerivativeProcessingFailedError,
    MediaDerivativeSourceDecodeFailedError,
    MediaDerivativeSourceTooLargeError,
    MediaJobArtifactExpiredError,
    MediaJobArtifactNotFoundError,
    MediaJobArtifactUnavailableError,
    MediaJobQueueFullError,
    MediaUploadReplayUnavailableError,
)
from app.domain.media_derivatives.metrics import record_media_derivative_job_metric
from app.domain.media_derivatives.processor import process_media_derivative
from app.domain.runtime.models import RuntimeExecutionResponse
from app.domain.runtime.run_lifecycle import RuntimeRunCreationCommand


@dataclass(frozen=True, slots=True)
class RuntimeArtifactCoordinationConfig:
    audio_artifact_ttl_minutes: int = AUDIO_ARTIFACT_DEFAULT_TTL_MINUTES
    audio_artifact_max_bytes: int = AUDIO_ARTIFACT_DEFAULT_MAX_BYTES
    audio_artifact_download_timeout_seconds: float = AUDIO_ARTIFACT_DEFAULT_TIMEOUT_SECONDS
    image_generation_artifact_ttl_minutes: int = IMAGE_GENERATION_DEFAULT_TTL_MINUTES
    image_generation_max_image_bytes: int = PROVIDER_IMAGE_DEFAULT_MAX_BYTES
    image_generation_max_run_bytes: int = IMAGE_GENERATION_DEFAULT_MAX_RUN_BYTES
    image_generation_download_timeout_seconds: float = (
        PROVIDER_IMAGE_DEFAULT_TIMEOUT_SECONDS
    )
    media_derivative_batch_default_chunk_size: int = 10
    media_derivative_batch_max_chunk_size: int = 20
    media_derivative_site_queued_limit: int = 100
    media_derivative_site_running_limit: int = 2


class RuntimeArtifactRunController(Protocol):
    def build_media_derivative_request_fingerprint(
        self,
        site_id: str,
        input_payload: dict[str, Any],
        *,
        source_checksum: str,
        watermark_checksum: str = "",
    ) -> str: ...

    def get_idempotent_replay(
        self,
        *,
        repository: RuntimeRepository,
        site_id: str,
        idempotency_key: str | None,
        request_fingerprint: str,
    ) -> RunRecord | None: ...

    def create_durable_run(
        self,
        *,
        repository: RuntimeRepository,
        command: RuntimeRunCreationCommand,
    ) -> RunRecord: ...

    def publish_queue_signal(self, run_id: str) -> None: ...

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
    ) -> RunRecord: ...

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
    ) -> RunRecord: ...


class RuntimeExecutionInputLoader(Protocol):
    def __call__(self, run: RunRecord) -> dict[str, Any]: ...


class AudioCandidateMaterializer(Protocol):
    def __call__(
        self,
        *,
        session: Session,
        run: RunRecord,
        result_json: dict[str, Any],
        config: AudioArtifactMaterializationConfig,
        artifact_store: ArtifactStore,
    ) -> dict[str, Any]: ...


class ImageGenerationCandidateMaterializer(Protocol):
    def __call__(
        self,
        *,
        session: Session,
        artifact_store: ArtifactStore,
        run: RunRecord,
        media_candidates: Sequence[ProviderMediaCandidateLike],
        provider_output: dict[str, Any],
        config: ImageGenerationMaterializationConfig,
    ) -> dict[str, Any]: ...


class RuntimeActiveSiteGuard(Protocol):
    def __call__(
        self,
        repository: RuntimeRepository,
        site_id: str,
    ) -> Any: ...


class RuntimeCommercialAuthorizer(Protocol):
    def __call__(
        self,
        *,
        session: Session,
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
    ) -> dict[str, object]: ...


class RuntimeCommercialAcceptanceRecorder(Protocol):
    def __call__(
        self,
        *,
        session: Session,
        run: RunRecord,
    ) -> None: ...


class RuntimeCreditEstimator(Protocol):
    def __call__(
        self,
        *,
        ability_family: str | None,
        execution_kind: str | None,
        payload_json: dict[str, object] | None = None,
    ) -> float: ...


class RuntimeExecutionInputEncryptor(Protocol):
    def __call__(self, input_payload: dict[str, object]) -> str: ...


class RuntimeExecutionResponseBuilder(Protocol):
    def __call__(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        idempotent_replay: bool,
    ) -> RuntimeExecutionResponse: ...


@dataclass(frozen=True, slots=True)
class RuntimeArtifactCoordinationDependencies:
    database_url: str
    active_site_guard: RuntimeActiveSiteGuard
    commercial_authorizer: RuntimeCommercialAuthorizer
    commercial_acceptance_recorder: RuntimeCommercialAcceptanceRecorder
    credit_estimator: RuntimeCreditEstimator
    execution_input_encryptor: RuntimeExecutionInputEncryptor
    execution_response_builder: RuntimeExecutionResponseBuilder
    artifact_store: ArtifactStore


class RuntimeArtifactCoordinationService:
    def __init__(
        self,
        *,
        config: RuntimeArtifactCoordinationConfig,
        dependencies: RuntimeArtifactCoordinationDependencies,
        run_controller: RuntimeArtifactRunController,
        execution_input_loader: RuntimeExecutionInputLoader,
        audio_candidate_materializer: AudioCandidateMaterializer | None = None,
        image_generation_candidate_materializer: (
            ImageGenerationCandidateMaterializer | None
        ) = None,
    ) -> None:
        self.config = config
        self.dependencies = dependencies
        self.run_controller = run_controller
        self.execution_input_loader = execution_input_loader
        self.audio_candidate_materializer = (
            audio_candidate_materializer or materialize_audio_generation_candidates
        )
        self.image_generation_candidate_materializer = (
            image_generation_candidate_materializer
            or materialize_image_generation_candidates
        )

    def create_media_upload(
        self,
        *,
        site_id: str,
        request_payload: dict[str, Any],
        stream: BinaryIO,
        upload: ValidatedImageUpload,
        ttl_minutes: int,
        idempotency_key: str | None = None,
        trace_id: str | None = None,
    ) -> RuntimeExecutionResponse:
        resolved_trace_id = trace_id or uuid4().hex
        run_id = f"run_{uuid4().hex}"
        resolved_idempotency_key = idempotency_key or f"auto_{uuid4().hex}"
        upload_input = {
            "request": request_payload,
            "content": {
                "media_kind": "image",
                "content_type": upload.content_type,
                "format": upload.format,
                "byte_size": upload.byte_size,
                "checksum": upload.checksum,
                "width": upload.width,
                "height": upload.height,
            },
        }
        request_fingerprint = self.run_controller.build_media_derivative_request_fingerprint(
            site_id,
            upload_input,
            source_checksum=upload.checksum,
        )

        with get_session(self.dependencies.database_url) as session:
            repository = RuntimeRepository(session)
            site = self.dependencies.active_site_guard(repository, site_id)

            existing = self.run_controller.get_idempotent_replay(
                repository=repository,
                site_id=site_id,
                idempotency_key=resolved_idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            if existing is not None:
                artifact = session.scalar(
                    select(MediaArtifact).where(
                        MediaArtifact.run_id == existing.run_id,
                        MediaArtifact.site_id == site_id,
                        MediaArtifact.operation == "image.upload.v1",
                    )
                )
                if artifact is None or is_artifact_expired(artifact):
                    raise MediaUploadReplayUnavailableError()
                try:
                    replay_metadata = self.dependencies.artifact_store.metadata(
                        artifact.storage_key
                    )
                except ArtifactStoreError as error:
                    raise MediaUploadReplayUnavailableError() from error
                if (
                    replay_metadata.byte_size != artifact.byte_size
                    or replay_metadata.checksum != artifact.checksum
                    or artifact.checksum != upload.checksum
                ):
                    raise MediaUploadReplayUnavailableError()
                session.commit()
                return self.dependencies.execution_response_builder(
                    existing,
                    repository=repository,
                    idempotent_replay=True,
                )

            # Resource admission reuses the existing media entitlement boundary, but the
            # synchronous upload evidence is zero-credit and is not recorded as an AI run.
            commercial_decision = self.dependencies.commercial_authorizer(
                session=session,
                site_id=site_id,
                ability_family="vision",
                channel="openapi",
                execution_kind="media_derivative",
                execution_tier="cloud",
                data_classification="internal",
                trace_id=resolved_trace_id,
                idempotency_key=resolved_idempotency_key,
                request_kind="execute",
                run_id=run_id,
                estimated_ai_credits=0.0,
            )

            policy = {
                "storage_mode": "full_store_with_ttl",
                "execution_contract": {
                    "ability_name": "media_artifact_upload",
                    "contract_version": "media_upload_request.v1",
                    "profile_id": "media.upload",
                    "execution_pattern": "inline",
                    "data_classification": "internal",
                    "storage_mode": "full_store_with_ttl",
                    "timeout_seconds": 60,
                    "retry_max": 0,
                    "retention_ttl": ttl_minutes * 60,
                    "task_backend": {"enabled": False},
                },
            }
            try:
                try:
                    stream.seek(0)
                except OSError as error:
                    raise ArtifactStoreError("upload spool seek failed") from error
                stored = publish_and_track_artifact(
                    session,
                    store=self.dependencies.artifact_store,
                    stream=stream,
                    max_bytes=MAX_UPLOAD_BYTES_IMAGE,
                    metadata={"media_kind": "image"},
                )
                if stored.byte_size != upload.byte_size or stored.checksum != upload.checksum:
                    raise ArtifactStoreError("stored upload evidence does not match validation")
                run = self.run_controller.create_durable_run(
                    repository=repository,
                    command=RuntimeRunCreationCommand(
                        run_id=run_id,
                        site_id=site_id,
                        account_id=(
                            str(commercial_decision.get("account_id") or "")
                            or str(getattr(site, "account_id", "") or "")
                            or None
                        ),
                        subscription_id=(
                            str(commercial_decision.get("subscription_id") or "") or None
                        ),
                        plan_version_id=(
                            str(commercial_decision.get("plan_version_id") or "") or None
                        ),
                        ability_name="media_artifact_upload",
                        ability_family="media",
                        skill_id="",
                        workflow_id="",
                        contract_version="media_upload_request.v1",
                        channel="openapi",
                        execution_kind="media_upload",
                        execution_tier="cloud",
                        execution_pattern="inline",
                        data_classification="internal",
                        profile_id="media.upload",
                        canonical_run_id=None,
                        status="running",
                        idempotency_key=resolved_idempotency_key,
                        request_fingerprint=request_fingerprint,
                        trace_id=resolved_trace_id,
                        input_json=upload_input,
                        execution_input_ciphertext=None,
                        policy_json=policy,
                    ),
                )
                artifact = create_uploaded_artifact(
                    session=session,
                    run_id=run.run_id,
                    site_id=site_id,
                    stored=stored,
                    upload=upload,
                    ttl_minutes=ttl_minutes,
                )
                self.run_controller.succeed_run(
                    repository,
                    run,
                    result_json=build_upload_artifact_result_json(artifact),
                    provider_id="media_store",
                    model_id="none",
                    instance_id="cloud-runtime",
                    fallback_used=False,
                )
                session.commit()
            except IntegrityError:
                session.rollback()
                return self._load_upload_replay_after_race(
                    site_id=site_id,
                    idempotency_key=resolved_idempotency_key,
                    request_fingerprint=request_fingerprint,
                    upload_checksum=upload.checksum,
                )
            except BaseException:
                session.rollback()
                raise
            return self.dependencies.execution_response_builder(
                run,
                repository=repository,
                idempotent_replay=False,
            )

    def _load_upload_replay_after_race(
        self,
        *,
        site_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        upload_checksum: str,
    ) -> RuntimeExecutionResponse:
        with get_session(self.dependencies.database_url) as session:
            repository = RuntimeRepository(session)
            self.dependencies.active_site_guard(repository, site_id)
            existing = self.run_controller.get_idempotent_replay(
                repository=repository,
                site_id=site_id,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            if existing is None:
                raise MediaUploadReplayUnavailableError()
            artifact = session.scalar(
                select(MediaArtifact).where(
                    MediaArtifact.run_id == existing.run_id,
                    MediaArtifact.site_id == site_id,
                    MediaArtifact.operation == "image.upload.v1",
                )
            )
            if (
                artifact is None
                or is_artifact_expired(artifact)
                or artifact.checksum != upload_checksum
            ):
                raise MediaUploadReplayUnavailableError()
            try:
                stored = self.dependencies.artifact_store.metadata(artifact.storage_key)
            except ArtifactStoreError as error:
                raise MediaUploadReplayUnavailableError() from error
            if stored.byte_size != artifact.byte_size or stored.checksum != artifact.checksum:
                raise MediaUploadReplayUnavailableError()
            session.commit()
            return self.dependencies.execution_response_builder(
                existing,
                repository=repository,
                idempotent_replay=True,
            )

    def enqueue_media_job_run(
        self,
        *,
        site_id: str,
        input_payload: dict[str, Any],
        idempotency_key: str | None = None,
        trace_id: str | None = None,
    ) -> RuntimeExecutionResponse:
        resolved_trace_id = trace_id or uuid4().hex
        run_id = f"run_{uuid4().hex}"
        resolved_idempotency_key = idempotency_key or f"auto_{uuid4().hex}"

        with get_session(self.dependencies.database_url) as session:
            repository = RuntimeRepository(session)
            self.dependencies.active_site_guard(repository, site_id)
            source = self._find_job_artifact(
                session,
                site_id=site_id,
                artifact_id=str(input_payload["source_artifact_id"]),
                role="source",
            )
            watermark_id = str(input_payload.get("watermark_artifact_id") or "")
            watermark = (
                self._find_job_artifact(
                    session, site_id=site_id, artifact_id=watermark_id, role="watermark"
                )
                if watermark_id
                else None
            )
            fingerprint_input = {
                "request_contract_version": input_payload["request_contract_version"],
                "operation": input_payload["operation"],
                "source_artifact_id": input_payload["source_artifact_id"],
                "watermark_artifact_id": input_payload.get("watermark_artifact_id"),
                "params": input_payload["params"],
                "batch_context": input_payload.get("batch_context"),
                "result_ttl_minutes": input_payload["result_ttl_minutes"],
            }
            request_fingerprint = self.run_controller.build_media_derivative_request_fingerprint(
                site_id,
                fingerprint_input,
                source_checksum=source.checksum,
                watermark_checksum=watermark.checksum if watermark else "",
            )
            existing = self.run_controller.get_idempotent_replay(
                repository=repository,
                site_id=site_id,
                idempotency_key=resolved_idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            if existing is not None:
                session.commit()
                return self.dependencies.execution_response_builder(
                    existing, repository=repository, idempotent_replay=True
                )
            self._require_job_artifact(
                session,
                site_id=site_id,
                artifact_id=source.artifact_id,
                role="source",
            )
            if watermark is not None:
                self._require_job_artifact(
                    session,
                    site_id=site_id,
                    artifact_id=watermark.artifact_id,
                    role="watermark",
                )
            queue_counts = repository.summarize_media_derivative_queue_pressure(site_id)
            if int(queue_counts.get("queued") or 0) >= int(
                self.config.media_derivative_site_queued_limit
            ):
                raise MediaJobQueueFullError()

            commercial_decision = self.dependencies.commercial_authorizer(
                session=session,
                site_id=site_id,
                ability_family="vision",
                channel="openapi",
                execution_kind="media_derivative",
                execution_tier="cloud",
                data_classification="internal",
                trace_id=resolved_trace_id,
                idempotency_key=resolved_idempotency_key,
                request_kind="execute",
                run_id=run_id,
                estimated_ai_credits=self.dependencies.credit_estimator(
                    ability_family="vision",
                    execution_kind="media_derivative",
                    payload_json=input_payload,
                ),
            )
            policy = {
                "storage_mode": "result_only",
                "media_derivative": self._build_media_derivative_policy(input_payload),
                "execution_contract": {
                    "ability_name": "media_image_transform",
                    "contract_version": "media_job_request.v1",
                    "profile_id": "media.transform.worker",
                    "execution_pattern": "whole_run_offload",
                    "data_classification": "internal",
                    "storage_mode": "result_only",
                    "timeout_seconds": 300,
                    "retry_max": 0,
                    "retention_ttl": int(input_payload["result_ttl_minutes"]) * 60,
                    "task_backend": {"enabled": True},
                },
            }
            try:
                run = self.run_controller.create_durable_run(
                    repository=repository,
                    command=RuntimeRunCreationCommand(
                        run_id=run_id,
                        site_id=site_id,
                        account_id=str(commercial_decision.get("account_id") or "") or None,
                        subscription_id=(
                            str(commercial_decision.get("subscription_id") or "") or None
                        ),
                        plan_version_id=(
                            str(commercial_decision.get("plan_version_id") or "") or None
                        ),
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
                        status="queued",
                        idempotency_key=resolved_idempotency_key,
                        request_fingerprint=request_fingerprint,
                        trace_id=resolved_trace_id,
                        input_json=input_payload,
                        execution_input_ciphertext=(
                            self.dependencies.execution_input_encryptor(input_payload)
                        ),
                        policy_json=policy,
                        selected_provider_id="media_processor",
                        selected_model_id="pillow",
                        selected_instance_id="cloud-worker",
                    ),
                )
            except IntegrityError:
                session.rollback()
                replay = self._load_media_job_replay_after_race(
                    site_id=site_id,
                    idempotency_key=resolved_idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                if replay is None:
                    raise
                return replay
            self.dependencies.commercial_acceptance_recorder(session=session, run=run)
            self.run_controller.publish_queue_signal(run.run_id)
            session.commit()
            return self.dependencies.execution_response_builder(
                run, repository=repository, idempotent_replay=False
            )

    def _load_media_job_replay_after_race(
        self,
        *,
        site_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> RuntimeExecutionResponse | None:
        with get_session(self.dependencies.database_url) as session:
            repository = RuntimeRepository(session)
            self.dependencies.active_site_guard(repository, site_id)
            existing = self.run_controller.get_idempotent_replay(
                repository=repository,
                site_id=site_id,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            if existing is None:
                return None
            session.commit()
            return self.dependencies.execution_response_builder(
                existing,
                repository=repository,
                idempotent_replay=True,
            )

    def _build_media_derivative_policy(
        self,
        input_payload: dict[str, Any],
    ) -> dict[str, object]:
        transform_params = self._dict_or_empty(input_payload.get("params"))
        batch_context = self._dict_or_empty(input_payload.get("batch_context"))
        return {
            "target_format": str(transform_params.get("target_format") or "webp"),
            "source_media_type": str(transform_params.get("source_media_type") or "image"),
            "batch_context": {
                "batch_id": str(batch_context.get("batch_id") or ""),
                "item_index": self._coerce_int(batch_context.get("item_index"), default=1),
                "item_count": self._coerce_int(batch_context.get("item_count"), default=1),
                "chunk_size": self._coerce_int(
                    batch_context.get("chunk_size"),
                    default=int(self.config.media_derivative_batch_default_chunk_size),
                ),
                "explicit_avif": bool(batch_context.get("explicit_avif")),
            }
            if batch_context
            else {},
            "limits": {
                "site_queued": int(self.config.media_derivative_site_queued_limit),
                "site_running": int(self.config.media_derivative_site_running_limit),
                "batch_max_chunk_size": int(self.config.media_derivative_batch_max_chunk_size),
            },
            "write_posture": "artifact_only",
            "direct_wordpress_write": False,
        }

    @staticmethod
    def _dict_or_empty(value: object) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _coerce_int(value: object | None, *, default: int) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return default
        return default

    def execute_media_derivative_run(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
    ) -> None:
        media_input = self.execution_input_loader(run)
        transform_params = media_input.get("params", {})
        source_media_type = transform_params.get("source_media_type", "image")
        target_format = transform_params.get("target_format", "webp")
        max_width = int(transform_params.get("max_width", 1200))
        quality = int(transform_params.get("quality", 82))
        crop_options = transform_params.get("crop")
        crop_options = crop_options if isinstance(crop_options, dict) else None
        watermark_options = transform_params.get("watermark")
        watermark_options = watermark_options if isinstance(watermark_options, dict) else None
        ttl_minutes = int(media_input.get("result_ttl_minutes", ARTIFACT_DEFAULT_TTL_MINUTES))
        processing_started_at = datetime.now(UTC)
        source_artifact_id = str(media_input.get("source_artifact_id") or "")
        watermark_artifact_id = str(media_input.get("watermark_artifact_id") or "")
        try:
            source_artifact = self._require_job_artifact(
                repository.session,
                site_id=run.site_id,
                artifact_id=source_artifact_id,
                role="source",
                minimum_remaining_seconds=0,
            )
        except (MediaJobArtifactNotFoundError, MediaJobArtifactExpiredError) as error:
            self._fail_media_job_input(repository, run, error, media_input=media_input)
            return
        try:
            source_bytes = read_artifact_bytes(
                self.dependencies.artifact_store,
                source_artifact.storage_key,
                max_bytes=MAX_UPLOAD_BYTES_IMAGE,
                expected_bytes=source_artifact.byte_size,
                expected_checksum=source_artifact.checksum,
            )
        except ArtifactStoreError:
            self._fail_media_job_input(
                repository,
                run,
                MediaJobArtifactUnavailableError("source"),
                media_input=media_input,
            )
            return
        watermark_bytes = None
        if watermark_artifact_id:
            try:
                watermark_artifact = self._require_job_artifact(
                    repository.session,
                    site_id=run.site_id,
                    artifact_id=watermark_artifact_id,
                    role="watermark",
                    minimum_remaining_seconds=0,
                )
            except (MediaJobArtifactNotFoundError, MediaJobArtifactExpiredError) as error:
                self._fail_media_job_input(repository, run, error, media_input=media_input)
                return
            try:
                watermark_bytes = read_artifact_bytes(
                    self.dependencies.artifact_store,
                    watermark_artifact.storage_key,
                    max_bytes=MAX_UPLOAD_BYTES_IMAGE,
                    expected_bytes=watermark_artifact.byte_size,
                    expected_checksum=watermark_artifact.checksum,
                )
            except ArtifactStoreError:
                self._fail_media_job_input(
                    repository,
                    run,
                    MediaJobArtifactUnavailableError("watermark"),
                    media_input=media_input,
                )
                return

        watermark_applied = bool(watermark_bytes) or bool(
            watermark_options and watermark_options.get("type") == "text"
        )

        try:
            result = process_media_derivative(
                source_bytes=source_bytes,
                source_media_type=source_media_type,
                target_format=target_format,
                max_width=max_width,
                quality=quality,
                crop_options=crop_options,
                watermark_bytes=watermark_bytes,
                watermark_options=watermark_options,
            )
        except (
            MediaDerivativeSourceDecodeFailedError,
            MediaDerivativeSourceTooLargeError,
            MediaDerivativeAnimatedSourceUnavailableError,
            MediaDerivativeFormatUnavailableError,
            MediaDerivativeOutputTooLargeError,
            MediaDerivativeProcessingFailedError,
        ) as error:
            self.run_controller.fail_run(
                repository,
                run,
                error_code=error.error_code,
                error_message=error.message,
            )
            run.result_json = {
                "status": "failed",
                "error_code": error.error_code,
                "error_message": error.message,
            }
            record_media_derivative_job_metric(
                session=repository.session,
                run=run,
                target_format=target_format,
                source_media_type=source_media_type,
                source_bytes=len(source_bytes),
                processing_started_at=processing_started_at,
                error_code=error.error_code,
                watermark_applied=watermark_applied,
            )
            return

        artifact = create_artifact(
            session=repository.session,
            artifact_store=self.dependencies.artifact_store,
            run_id=run.run_id,
            site_id=run.site_id,
            result=result,
            source_media_type=source_media_type,
            ttl_minutes=ttl_minutes,
        )
        result_json = build_artifact_result_json(artifact)
        self.run_controller.succeed_run(
            repository,
            run,
            result_json=result_json,
            provider_id="media_derivative",
            model_id="pillow",
            instance_id="cloud-worker",
            fallback_used=False,
        )
        record_media_derivative_job_metric(
            session=repository.session,
            run=run,
            target_format=target_format,
            source_media_type=source_media_type,
            source_bytes=len(source_bytes),
            processing_started_at=processing_started_at,
            result=result,
            artifact=artifact,
            watermark_applied=watermark_applied,
        )

    @staticmethod
    def _find_job_artifact(
        session: Session,
        *,
        site_id: str,
        artifact_id: str,
        role: str,
    ) -> MediaArtifact:
        artifact = session.scalar(
            select(MediaArtifact).where(
                MediaArtifact.artifact_id == artifact_id,
                MediaArtifact.site_id == site_id,
                MediaArtifact.media_kind == "image",
            )
        )
        if artifact is None:
            raise MediaJobArtifactNotFoundError(role)
        return artifact

    @staticmethod
    def _require_job_artifact(
        session: Session,
        *,
        site_id: str,
        artifact_id: str,
        role: str,
        minimum_remaining_seconds: int = 330,
    ) -> MediaArtifact:
        artifact = RuntimeArtifactCoordinationService._find_job_artifact(
            session,
            site_id=site_id,
            artifact_id=artifact_id,
            role=role,
        )
        now = datetime.now(UTC)
        if is_artifact_expired(artifact, now=now):
            raise MediaJobArtifactExpiredError(role)
        expires_at = artifact.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= now + timedelta(seconds=max(0, minimum_remaining_seconds)):
            raise MediaJobArtifactExpiredError(role)
        return artifact

    def _fail_media_job_input(
        self,
        repository: RuntimeRepository,
        run: RunRecord,
        error: MediaDerivativeErrorBase,
        *,
        media_input: dict[str, Any] | None = None,
    ) -> None:
        self.run_controller.fail_run(
            repository,
            run,
            error_code=error.error_code,
            error_message=error.message,
        )
        run.result_json = {
            "status": "failed",
            "error_code": error.error_code,
            "error_message": error.message,
        }
        payload = self._dict_or_empty((media_input or {}).get("params"))
        record_media_derivative_job_metric(
            session=repository.session,
            run=run,
            target_format=str(payload.get("target_format") or "unknown"),
            source_media_type=str(payload.get("source_media_type") or "image"),
            source_bytes=0,
            processing_started_at=datetime.now(UTC),
            error_code=error.error_code,
            watermark_applied=False,
        )

    def materialize_audio_generation_output(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        provider_output: dict[str, Any],
    ) -> dict[str, Any]:
        return self.audio_candidate_materializer(
            session=repository.session,
            run=run,
            result_json=provider_output,
            config=AudioArtifactMaterializationConfig(
                ttl_minutes=max(1, int(self.config.audio_artifact_ttl_minutes)),
                max_bytes=max(1, int(self.config.audio_artifact_max_bytes)),
                timeout_seconds=max(
                    0.001,
                    float(self.config.audio_artifact_download_timeout_seconds),
                ),
            ),
            artifact_store=self.dependencies.artifact_store,
        )

    def materialize_image_generation_output(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        provider_output: dict[str, Any],
        media_candidates: Sequence[ProviderMediaCandidateLike],
    ) -> dict[str, Any]:
        return self.image_generation_candidate_materializer(
            session=repository.session,
            artifact_store=self.dependencies.artifact_store,
            run=run,
            media_candidates=media_candidates,
            provider_output=provider_output,
            config=ImageGenerationMaterializationConfig(
                ttl_minutes=max(
                    1,
                    int(self.config.image_generation_artifact_ttl_minutes),
                ),
                max_image_bytes=max(
                    1,
                    int(self.config.image_generation_max_image_bytes),
                ),
                max_run_bytes=max(
                    1,
                    int(self.config.image_generation_max_run_bytes),
                ),
                timeout_seconds=max(
                    0.001,
                    float(self.config.image_generation_download_timeout_seconds),
                ),
            ),
        )
