from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy.orm import Session

from app.adapters.repositories.runtime_repository import RuntimeRepository
from app.core.db import get_session
from app.core.models import RunRecord
from app.domain.audio_generation.artifacts import (
    AUDIO_ARTIFACT_DEFAULT_MAX_BYTES,
    AUDIO_ARTIFACT_DEFAULT_TIMEOUT_SECONDS,
    AUDIO_ARTIFACT_DEFAULT_TTL_MINUTES,
    AudioArtifactMaterializationConfig,
    materialize_audio_generation_candidates,
)
from app.domain.image_generation.inline_images import (
    INLINE_IMAGE_DEFAULT_MAX_BYTES,
    INLINE_IMAGE_DEFAULT_TIMEOUT_SECONDS,
    InlineImageMaterializationConfig,
    materialize_inline_image_candidates_from_urls,
)
from app.domain.media_derivatives.artifacts import (
    build_artifact_result_json,
    create_artifact,
)
from app.domain.media_derivatives.contracts import ARTIFACT_DEFAULT_TTL_MINUTES
from app.domain.media_derivatives.errors import (
    MediaDerivativeAnimatedSourceUnavailableError,
    MediaDerivativeFormatUnavailableError,
    MediaDerivativeProcessingFailedError,
    MediaDerivativeSourceDecodeFailedError,
    MediaDerivativeSourceTooLargeError,
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
    inline_image_max_bytes: int = INLINE_IMAGE_DEFAULT_MAX_BYTES
    inline_image_timeout_seconds: float = INLINE_IMAGE_DEFAULT_TIMEOUT_SECONDS
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
    ) -> dict[str, Any]: ...


class InlineImageCandidateMaterializer(Protocol):
    def __call__(
        self,
        result_json: dict[str, Any],
        *,
        config: InlineImageMaterializationConfig,
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


class RuntimeArtifactCoordinationService:
    def __init__(
        self,
        *,
        config: RuntimeArtifactCoordinationConfig,
        dependencies: RuntimeArtifactCoordinationDependencies,
        run_controller: RuntimeArtifactRunController,
        execution_input_loader: RuntimeExecutionInputLoader,
        audio_candidate_materializer: AudioCandidateMaterializer | None = None,
        inline_image_candidate_materializer: InlineImageCandidateMaterializer | None = None,
    ) -> None:
        self.config = config
        self.dependencies = dependencies
        self.run_controller = run_controller
        self.execution_input_loader = execution_input_loader
        self.audio_candidate_materializer = (
            audio_candidate_materializer or materialize_audio_generation_candidates
        )
        self.inline_image_candidate_materializer = (
            inline_image_candidate_materializer or materialize_inline_image_candidates_from_urls
        )

    def enqueue_media_derivative_run(
        self,
        *,
        site_id: str,
        input_payload: dict[str, Any],
        source_bytes: bytes,
        watermark_bytes: bytes | None = None,
        ttl_minutes: int = 30,
        idempotency_key: str | None = None,
        trace_id: str | None = None,
    ) -> RuntimeExecutionResponse:
        resolved_trace_id = trace_id or uuid4().hex
        run_id = f"run_{uuid4().hex}"
        resolved_idempotency_key = idempotency_key or f"auto_{uuid4().hex}"
        source_checksum = hashlib.sha256(source_bytes).hexdigest()
        watermark_checksum = hashlib.sha256(watermark_bytes).hexdigest() if watermark_bytes else ""
        media_derivative_policy = self._build_media_derivative_policy(input_payload)
        request_fingerprint = self.run_controller.build_media_derivative_request_fingerprint(
            site_id,
            input_payload,
            source_checksum=source_checksum,
            watermark_checksum=watermark_checksum,
        )

        with get_session(self.dependencies.database_url) as session:
            repository = RuntimeRepository(session)
            self.dependencies.active_site_guard(repository, site_id)

            existing = self.run_controller.get_idempotent_replay(
                repository=repository,
                site_id=site_id,
                idempotency_key=resolved_idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            if existing is not None:
                session.commit()
                return self.dependencies.execution_response_builder(
                    existing,
                    repository=repository,
                    idempotent_replay=True,
                )

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

            media_input: dict[str, object] = {
                **input_payload,
                "_source_bytes_b64": base64.b64encode(source_bytes).decode("ascii"),
            }
            if watermark_bytes:
                media_input["_watermark_bytes_b64"] = base64.b64encode(watermark_bytes).decode(
                    "ascii"
                )

            policy = {
                "storage_mode": "result_only",
                "media_derivative": media_derivative_policy,
                "execution_contract": {
                    "ability_name": "generate_optimized_media_derivative",
                    "contract_version": "media_derivative_cloud_request.v1",
                    "profile_id": "media_derivative.worker",
                    "execution_pattern": "whole_run_offload",
                    "data_classification": "internal",
                    "storage_mode": "result_only",
                    "timeout_seconds": 300,
                    "retry_max": 0,
                    "retention_ttl": 3600,
                    "task_backend": {"enabled": True},
                },
            }

            run = self.run_controller.create_durable_run(
                repository=repository,
                command=RuntimeRunCreationCommand(
                    run_id=run_id,
                    site_id=site_id,
                    account_id=str(commercial_decision.get("account_id") or "") or None,
                    subscription_id=(str(commercial_decision.get("subscription_id") or "") or None),
                    plan_version_id=(str(commercial_decision.get("plan_version_id") or "") or None),
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
                    status="queued",
                    idempotency_key=resolved_idempotency_key,
                    request_fingerprint=request_fingerprint,
                    trace_id=resolved_trace_id,
                    input_json={},
                    execution_input_ciphertext=(
                        self.dependencies.execution_input_encryptor(media_input)
                    ),
                    policy_json=policy,
                    selected_provider_id="media_derivative",
                    selected_model_id="pillow",
                    selected_instance_id="cloud-worker",
                ),
            )
            self.dependencies.commercial_acceptance_recorder(session=session, run=run)
            self.run_controller.publish_queue_signal(run.run_id)
            session.commit()
            return self.dependencies.execution_response_builder(
                run,
                repository=repository,
                idempotent_replay=False,
            )

    def _build_media_derivative_policy(
        self,
        input_payload: dict[str, Any],
    ) -> dict[str, object]:
        cloud_job_payload = self._dict_or_empty(input_payload.get("cloud_job_payload"))
        batch_context = self._dict_or_empty(input_payload.get("batch_context"))
        return {
            "target_format": str(cloud_job_payload.get("target_format") or "webp"),
            "source_media_type": str(cloud_job_payload.get("source_media_type") or "image"),
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
        cloud_job_payload = media_input.get("cloud_job_payload", {})
        source_media_type = cloud_job_payload.get("source_media_type", "image")
        target_format = cloud_job_payload.get("target_format", "webp")
        max_width = int(cloud_job_payload.get("max_width", 1200))
        quality = int(cloud_job_payload.get("quality", 82))
        crop_options = cloud_job_payload.get("crop")
        crop_options = crop_options if isinstance(crop_options, dict) else None
        watermark_options = cloud_job_payload.get("watermark")
        watermark_options = watermark_options if isinstance(watermark_options, dict) else None
        ttl_minutes = int(media_input.get("ttl_minutes", ARTIFACT_DEFAULT_TTL_MINUTES))

        source_b64 = media_input.get("_source_bytes_b64", "")
        source_bytes = base64.b64decode(source_b64) if source_b64 else b""
        watermark_b64 = media_input.get("_watermark_bytes_b64", "")
        watermark_bytes = base64.b64decode(watermark_b64) if watermark_b64 else None
        processing_started_at = datetime.now(UTC)
        watermark_applied = bool(watermark_bytes) or bool(
            watermark_options and watermark_options.get("type") == "text"
        )

        if not source_bytes:
            self.run_controller.fail_run(
                repository,
                run,
                error_code="media_derivative.source_decode_failed",
                error_message="no source bytes found in media derivative run",
            )
            run.result_json = {
                "status": "failed",
                "error_code": "media_derivative.source_decode_failed",
                "error_message": "no source bytes found in media derivative run",
            }
            record_media_derivative_job_metric(
                session=repository.session,
                run=run,
                target_format=target_format,
                source_media_type=source_media_type,
                source_bytes=0,
                processing_started_at=processing_started_at,
                error_code="media_derivative.source_decode_failed",
                watermark_applied=watermark_applied,
            )
            return

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
        )

    def materialize_inline_image_output(
        self,
        provider_output: dict[str, Any],
    ) -> dict[str, Any]:
        return self.inline_image_candidate_materializer(
            provider_output,
            config=InlineImageMaterializationConfig(
                max_bytes=max(1, int(self.config.inline_image_max_bytes)),
                timeout_seconds=max(0.001, float(self.config.inline_image_timeout_seconds)),
            ),
        )
