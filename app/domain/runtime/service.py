from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.adapters.callbacks.base import RuntimeCallbackDispatcher
from app.adapters.providers.base import (
    ProviderAdapter,
    ProviderExecutionError,
    ProviderExecutionRequest,
    ProviderExecutionResult,
    ProviderMediaCandidate,
)
from app.adapters.providers.registry import build_provider_adapters
from app.adapters.queue.base import RuntimeQueue
from app.adapters.repositories.runtime_repository import RuntimeRepository
from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.error_taxonomy import get_error_taxonomy
from app.core.logging import get_logger
from app.core.models import (
    RUN_CALLBACK_STATUS_FAILED,
    RUN_CALLBACK_STATUS_PENDING,
    SITE_STATUS_ACTIVE,
    ProviderCallRecord,
    RunRecord,
    RuntimeGuardEvent,
    UsageMeterEvent,
)
from app.core.secrets import (
    decrypt_runtime_execution_input,
    encrypt_runtime_execution_input,
)
from app.core.security import (
    REPLAY_SCOPE_INTERNAL_POST,
    REPLAY_SCOPE_INTERNAL_POST_IP,
    REPLAY_SCOPE_PUBLIC_POST_IP,
    REPLAY_SCOPE_PUBLIC_POST_KEY,
    REPLAY_SCOPE_PUBLIC_POST_SITE,
)
from app.domain.audio_generation.artifacts import (
    AudioArtifactMaterializationError,
    materialize_audio_generation_candidates,
)
from app.domain.audio_generation.contracts import (
    AUDIO_GENERATION_ABILITIES,
)
from app.domain.cloud_batch_runtime.contracts import (
    CLOUD_BATCH_RUNTIME_ABILITIES,
    CLOUD_BATCH_RUNTIME_EXECUTION_KIND,
    CLOUD_BATCH_RUNTIME_PROFILE_ID,
    CloudBatchRuntimeContractViolation,
)
from app.domain.cloud_batch_runtime.service import CloudBatchRuntimeService
from app.domain.commercial.credits import (
    AI_CREDIT_RATE_VERSION,
    classify_provider_credit_component,
    estimate_runtime_request_ai_credits,
)
from app.domain.commercial.service import CommercialService, ServiceAuditContext
from app.domain.connector_runtime.contracts import (
    CONNECTOR_RUNTIME_ABILITIES,
)
from app.domain.hosted_model_defaults import FREE_GPT55_TEXT_PROFILE_ID
from app.domain.image_context_evidence.contracts import (
    IMAGE_CONTEXT_EVIDENCE_ABILITIES,
    IMAGE_CONTEXT_EVIDENCE_PROFILE_ID,
    ImageContextEvidenceContractViolation,
)
from app.domain.image_context_evidence.service import (
    ImageContextEvidenceProviderError,
    ImageContextEvidenceService,
)
from app.domain.image_generation.contracts import IMAGE_GENERATION_ABILITIES
from app.domain.image_generation.materialization import (
    ImageGenerationArtifactMaterializationError,
)
from app.domain.image_sources.contracts import (
    IMAGE_SOURCE_ABILITIES,
    IMAGE_SOURCE_PROFILE_ID,
    ImageSourceContractViolation,
)
from app.domain.image_sources.service import ImageSourceProviderError, ImageSourceService
from app.domain.media_artifacts import ArtifactStore, build_artifact_store
from app.domain.media_artifacts.input_loading import (
    ArtifactInputError,
    LoadedArtifactInput,
    admit_artifact_input,
    load_artifact_input,
)
from app.domain.media_artifacts.projection import project_media_artifact_lifecycle
from app.domain.media_batch_plans.contracts import (
    MEDIA_BATCH_PLAN_ABILITIES,
    MEDIA_BATCH_PLAN_PROFILE_ID,
    MediaBatchPlanContractViolation,
)
from app.domain.media_batch_plans.service import MediaBatchPlanService
from app.domain.routing.errors import RoutingError
from app.domain.routing.models import RoutingCandidate, RoutingResolution
from app.domain.routing.service import RoutingService
from app.domain.runtime.analysis_result import build_analysis_result_envelope
from app.domain.runtime.artifact_coordination import (
    RuntimeArtifactCoordinationConfig,
    RuntimeArtifactCoordinationDependencies,
    RuntimeArtifactCoordinationService,
)
from app.domain.runtime.callback_delivery import RuntimeCallbackDeliveryService
from app.domain.runtime.contract_validation import RuntimeContractValidator
from app.domain.runtime.errors import (
    RuntimeBatchLimitExceededError,
    RuntimeErrorBase,
    RuntimeExecutionContractError,
    RuntimeResultExpiredError,
    RuntimeResultNotReadyError,
    RuntimeRunNotFoundError,
    RuntimeSiteInactiveError,
    RuntimeSiteNotProvisionedError,
)
from app.domain.runtime.models import (
    ABUSE_GUARD_ATTENTION_RATIO,
    ABUSE_GUARD_CRITICAL_RATIO,
    RUNTIME_BACKLOG_QUEUED_AGING_AFTER_SECONDS,
    RUNTIME_BACKLOG_RUNNING_AGING_AFTER_SECONDS,
    RUNTIME_CALLBACK_DISPATCH_LEASE_RECOVERY_AFTER_SECONDS,
    RUNTIME_CALLBACK_DISPATCH_LEASE_RECOVERY_ERROR_CODE,
    RUNTIME_DIAGNOSTIC_CALLBACK_DISPATCHING_STALE_AFTER_SECONDS,
    RUNTIME_DIAGNOSTIC_CALLBACK_OVERDUE_AFTER_SECONDS,
    RUNTIME_DIAGNOSTIC_CANCEL_STUCK_AFTER_SECONDS,
    RUNTIME_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS,
    RUNTIME_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS,
    RUNTIME_STORAGE_MODE_FULL_STORE_WITH_TTL,
    RUNTIME_STORAGE_MODE_NO_STORE,
    RUNTIME_STORAGE_MODE_RESULT_ONLY,
    RuntimeExecutionResponse,
    RuntimeRequest,
    normalize_runtime_request_policy,
    normalize_runtime_task_backend,
)
from app.domain.runtime.provider_execution import (
    ProviderCallEvidenceCommand,
    ProviderOutputDecision,
    ProviderOutputFinalizationError,
    RuntimeProviderExecutionService,
)
from app.domain.runtime.result_normalization import (
    RuntimeResultNormalizationCommand,
    RuntimeResultNormalizationService,
    get_transient_runtime_result,
    set_transient_runtime_result,
)
from app.domain.runtime.run_lifecycle import (
    RuntimeRunCreationCommand,
    RuntimeRunLifecycleService,
)
from app.domain.runtime.run_projection import RuntimeRunProjector
from app.domain.site_knowledge.backends import SiteKnowledgeBackendError
from app.domain.site_knowledge.contracts import (
    SITE_KNOWLEDGE_ABILITIES,
    SITE_KNOWLEDGE_CONTRACTS,
    SITE_KNOWLEDGE_SEARCH_ABILITY,
    SITE_KNOWLEDGE_STATUS_ABILITY,
    SITE_KNOWLEDGE_SYNC_ABILITY,
    SiteKnowledgeContractViolation,
)
from app.domain.site_knowledge.metrics import (
    record_site_knowledge_failure_metric,
    record_site_knowledge_run_metric,
)
from app.domain.site_knowledge.service import SiteKnowledgeService
from app.domain.site_ops_analysis.contracts import (
    SITE_OPS_ANALYSIS_ABILITIES,
    SITE_OPS_ANALYSIS_DATA_CLASSIFICATION,
    SITE_OPS_ANALYSIS_PROFILE_ID,
    SITE_OPS_ANALYSIS_RESULT_CONTRACT,
    SiteOpsAnalysisContractViolation,
)
from app.domain.site_ops_analysis.service import SiteOpsAnalysisService
from app.domain.web_search.auto_policy import (
    attach_automatic_web_search_evidence,
    build_automatic_web_search_plan,
    build_automatic_web_search_success_report,
)
from app.domain.web_search.contracts import (
    WEB_SEARCH_ABILITIES,
    WEB_SEARCH_ABILITY,
    WEB_SEARCH_CONTRACT,
    WebSearchContractViolation,
)
from app.domain.web_search.service import WebSearchProviderError, WebSearchService
from app.domain.wordpress_ai_connector.runtime import WordPressOperationRuntime

__all__ = [
    "RuntimeResultExpiredError",
    "RuntimeResultNotReadyError",
    "RuntimeService",
]

logger = get_logger(__name__)

OPERATOR_REPAIR_REASON_MIN_LENGTH = 12
OPERATOR_REPAIR_EVIDENCE_MIN_LENGTH = 24
NON_AI_ZERO_CREDIT_EXECUTION_KINDS = frozenset({"media_upload"})


class RuntimeService:
    def __init__(
        self,
        database_url: str,
        settings: Settings | None = None,
        providers: dict[str, ProviderAdapter] | None = None,
        runtime_queue: RuntimeQueue | None = None,
        callback_dispatcher: RuntimeCallbackDispatcher | None = None,
        callback_max_attempts: int = 3,
        callback_retry_backoff_seconds: int = 30,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self.database_url = database_url
        self.settings = settings or get_settings()
        self.artifact_store = artifact_store or build_artifact_store(self.settings)
        self.commercial_service = CommercialService(database_url, settings=self.settings)
        self.result_normalization_service = RuntimeResultNormalizationService()
        self.providers = (
            providers if providers is not None else build_provider_adapters(self.settings)
        )
        self.wordpress_operation_runtime = WordPressOperationRuntime(
            settings=self.settings,
            providers=self.providers,
        )
        self.run_projector = RuntimeRunProjector()
        self.callback_delivery_service = RuntimeCallbackDeliveryService(
            database_url=self.database_url,
            settings=self.settings,
            dispatcher=callback_dispatcher,
            max_attempts=callback_max_attempts,
            retry_backoff_seconds=callback_retry_backoff_seconds,
            run_projector=self.run_projector,
            recovery_audit_callback=self._record_callback_dispatch_recovery,
        )
        self.contract_validator = RuntimeContractValidator(
            callback_target_resolver=self.callback_delivery_service,
        )
        self.routing_service = RoutingService(
            database_url,
            settings=self.settings,
            execution_provider_ids=set(self.providers),
        )
        self.runtime_queue = runtime_queue
        self.run_lifecycle_service = RuntimeRunLifecycleService(
            database_url=self.database_url,
            runtime_queue=self.runtime_queue,
            run_projector=self.run_projector,
            claimed_run_executor=self._execute_existing_run,
            media_derivative_site_running_limit=(self.settings.media_derivative_site_running_limit),
        )
        self.artifact_coordination_service = RuntimeArtifactCoordinationService(
            config=RuntimeArtifactCoordinationConfig(
                audio_artifact_ttl_minutes=(self.settings.audio_generation_artifact_ttl_minutes),
                audio_artifact_max_bytes=self.settings.audio_generation_artifact_max_bytes,
                audio_artifact_download_timeout_seconds=(
                    self.settings.audio_generation_artifact_download_timeout_seconds
                ),
                media_derivative_batch_default_chunk_size=(
                    self.settings.media_derivative_batch_default_chunk_size
                ),
                media_derivative_batch_max_chunk_size=(
                    self.settings.media_derivative_batch_max_chunk_size
                ),
                media_derivative_site_queued_limit=(
                    self.settings.media_derivative_site_queued_limit
                ),
                media_derivative_site_running_limit=(
                    self.settings.media_derivative_site_running_limit
                ),
            ),
            dependencies=RuntimeArtifactCoordinationDependencies(
                database_url=self.database_url,
                active_site_guard=self._require_active_site,
                commercial_authorizer=self.commercial_service.authorize_runtime_request,
                commercial_acceptance_recorder=(self.commercial_service.record_run_acceptance),
                credit_estimator=estimate_runtime_request_ai_credits,
                execution_input_encryptor=lambda input_payload: encrypt_runtime_execution_input(
                    input_payload, settings=self.settings
                ),
                execution_response_builder=self._build_execution_response,
                artifact_store=self.artifact_store,
            ),
            run_controller=self.run_lifecycle_service,
            execution_input_loader=self._get_execution_input_payload,
            audio_candidate_materializer=materialize_audio_generation_candidates,
        )
        self.provider_execution_service = RuntimeProviderExecutionService(
            usage_recorder=self.commercial_service,
            providers=self.providers,
            run_controller=self.run_lifecycle_service,
            input_preprocessor=self._preprocess_provider_input,
            output_preparer=self._prepare_provider_output,
            output_finalizer=self._finalize_provider_output,
        )

    def resolve(self, request: RuntimeRequest) -> dict[str, object]:
        self.contract_validator.validate_runtime_data_handling_contract(request)
        self._validate_image_generation_artifact_storage(request)
        connector_envelope: dict[str, Any] | None = None
        if self._is_audio_generation_request(request):
            self.contract_validator.validate_audio_generation_contract(request)
        if self._is_image_generation_request(request):
            self.contract_validator.validate_image_generation_contract(request)
        if self._is_wordpress_ai_connector_request(request):
            connector_envelope = self.contract_validator.validate_connector_runtime_contract(
                request
            )
            request.input_payload = connector_envelope

        resolution = self.routing_service.resolve(
            profile_id=request.profile_id,
            execution_kind=request.execution_kind,
        )

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            site = self._require_active_site(repository, request.site_id)
            if connector_envelope is not None:
                self.contract_validator.validate_connector_runtime_site_binding(
                    connector_envelope,
                    site=site,
                )
                self._admit_wordpress_operation_artifact_input(
                    repository,
                    site_id=request.site_id,
                    connector_envelope=connector_envelope,
                )
            commercial_decision = self.commercial_service.authorize_runtime_request(
                session=session,
                site_id=request.site_id,
                ability_family=request.ability_family,
                channel=request.channel,
                execution_kind=request.execution_kind,
                execution_tier=request.execution_tier,
                data_classification=request.data_classification,
                trace_id=request.trace_id or "",
                idempotency_key=request.idempotency_key,
                request_kind="resolve",
            )
            self._enforce_batch_limits(
                request=request,
                commercial_decision=commercial_decision,
            )
            execution_contract = self.contract_validator.build_execution_contract(
                request=request,
                resolution=resolution,
                site=site,
            )
            session.commit()

        merged_policy = self._merge_policy(resolution.default_policy, request.policy)
        merged_policy = self.contract_validator.apply_execution_contract(
            merged_policy,
            execution_contract=execution_contract,
        )
        if self._is_wordpress_ai_connector_managed_request(request):
            merged_policy = self.wordpress_operation_runtime.apply_managed_policy(
                merged_policy,
                default_policy=resolution.default_policy,
                profile_id=resolution.profile_id,
            )
        merged_policy = self._apply_routing_snapshot(merged_policy, resolution)
        merged_policy = self._apply_commercial_policy_overrides(
            merged_policy,
            commercial_decision=commercial_decision,
        )
        should_enqueue = self._should_enqueue(request, merged_policy)

        candidates = [
            self._serialize_routing_candidate(candidate) for candidate in resolution.candidates
        ]
        task_backend_status = "queued" if should_enqueue else "running"

        return {
            "profile_id": resolution.profile_id,
            "execution_kind": resolution.execution_kind,
            "revision": resolution.revision,
            "policy": merged_policy,
            "selected_candidate": candidates[0],
            "candidates": candidates,
            "run_lifecycle": self.run_projector.build_planned_run_lifecycle(
                execution_pattern=request.execution_pattern,
                policy=merged_policy,
                initial_phase="queued" if task_backend_status == "queued" else "processing",
            ),
            "task_backend": self.run_projector.build_task_backend_payload_from_policy(
                merged_policy,
                run_status=task_backend_status,
            ),
        }

    def execute(self, request: RuntimeRequest) -> RuntimeExecutionResponse:
        self.contract_validator.validate_runtime_data_handling_contract(request)
        self._validate_image_generation_artifact_storage(request)
        connector_envelope: dict[str, Any] | None = None
        if self._is_cloud_batch_runtime_request(request):
            return self._execute_cloud_batch_runtime_request(request)
        if self._is_site_ops_analysis_request(request):
            return self._execute_site_ops_analysis_request(request)
        if self._is_media_batch_plan_request(request):
            return self._execute_media_batch_plan_request(request)
        if self._is_image_context_evidence_request(request):
            return self._execute_image_context_evidence_request(request)
        if self._is_image_source_request(request):
            return self._execute_image_source_request(request)
        if self._is_site_knowledge_request(request):
            return self._execute_site_knowledge_request(request)
        if self._is_web_search_request(request):
            return self._execute_web_search_request(request)
        if self._is_audio_generation_request(request):
            self.contract_validator.validate_audio_generation_contract(request)
        if self._is_image_generation_request(request):
            self.contract_validator.validate_image_generation_contract(request)
        if self._is_wordpress_ai_connector_request(request):
            connector_envelope = self.contract_validator.validate_connector_runtime_contract(
                request
            )
            request.input_payload = connector_envelope

        resolution = self.routing_service.resolve(
            profile_id=request.profile_id,
            execution_kind=request.execution_kind,
        )
        merged_policy = self._merge_policy(resolution.default_policy, request.policy)
        resolution = self._prefer_routing_candidate(resolution, merged_policy)
        merged_policy = self._apply_routing_snapshot(merged_policy, resolution)
        trace_id = request.trace_id or uuid4().hex
        run_id = f"run_{uuid4().hex}"
        request_fingerprint = self.run_lifecycle_service.build_request_fingerprint(
            request,
            merged_policy,
        )
        should_enqueue = self._should_enqueue(request, merged_policy)
        selected_candidate = resolution.selected_candidate

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            site = self._require_active_site(repository, request.site_id)
            if connector_envelope is not None:
                self.contract_validator.validate_connector_runtime_site_binding(
                    connector_envelope,
                    site=site,
                )
            execution_contract = self.contract_validator.build_execution_contract(
                request=request,
                resolution=resolution,
                site=site,
            )
            merged_policy = self.contract_validator.apply_execution_contract(
                merged_policy,
                execution_contract=execution_contract,
            )
            if self._is_wordpress_ai_connector_managed_request(request):
                merged_policy = self.wordpress_operation_runtime.apply_managed_policy(
                    merged_policy,
                    default_policy=resolution.default_policy,
                    profile_id=resolution.profile_id,
                )

            existing = self.run_lifecycle_service.get_idempotent_replay(
                repository=repository,
                site_id=request.site_id,
                idempotency_key=request.idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            if existing is not None:
                session.commit()
                return self._build_execution_response(
                    existing,
                    repository=repository,
                    idempotent_replay=True,
                )

            if connector_envelope is not None:
                self._admit_wordpress_operation_artifact_input(
                    repository,
                    site_id=request.site_id,
                    connector_envelope=connector_envelope,
                )

            commercial_decision = self.commercial_service.authorize_runtime_request(
                session=session,
                site_id=request.site_id,
                ability_family=request.ability_family,
                channel=request.channel,
                execution_kind=request.execution_kind,
                execution_tier=request.execution_tier,
                data_classification=request.data_classification,
                trace_id=trace_id,
                idempotency_key=request.idempotency_key,
                request_kind="execute",
                run_id=run_id,
                estimated_ai_credits=self._estimate_runtime_request_ai_credits(request),
            )
            self._enforce_batch_limits(
                request=request,
                commercial_decision=commercial_decision,
            )
            merged_policy = self._apply_commercial_policy_overrides(
                merged_policy,
                commercial_decision=commercial_decision,
            )
            should_enqueue = self._should_enqueue(request, merged_policy)
            storage_mode = self._get_storage_mode(merged_policy)
            prepared_input = self._prepare_input_for_storage(
                request.input_payload,
                storage_mode=storage_mode,
            )
            execution_input_ciphertext = None
            if should_enqueue:
                execution_input_ciphertext = encrypt_runtime_execution_input(
                    request.input_payload,
                    settings=self.settings,
                )

            run = self.run_lifecycle_service.create_durable_run(
                repository=repository,
                command=RuntimeRunCreationCommand(
                    run_id=run_id,
                    site_id=request.site_id,
                    account_id=str(commercial_decision.get("account_id") or "") or None,
                    subscription_id=str(commercial_decision.get("subscription_id") or "") or None,
                    plan_version_id=str(commercial_decision.get("plan_version_id") or "") or None,
                    ability_name=request.ability_name,
                    ability_family=request.ability_family,
                    skill_id=request.skill_id,
                    workflow_id=request.workflow_id,
                    contract_version=request.contract_version,
                    channel=request.channel,
                    execution_kind=request.execution_kind,
                    execution_tier=request.execution_tier,
                    execution_pattern=request.execution_pattern,
                    data_classification=request.data_classification,
                    profile_id=request.profile_id,
                    canonical_run_id=request.canonical_run_id or None,
                    status="queued" if should_enqueue else "running",
                    idempotency_key=request.idempotency_key,
                    request_fingerprint=request_fingerprint,
                    trace_id=trace_id,
                    input_json=prepared_input,
                    execution_input_ciphertext=execution_input_ciphertext,
                    policy_json=merged_policy,
                    selected_provider_id=selected_candidate.provider_id,
                    selected_model_id=selected_candidate.model_id,
                    selected_instance_id=selected_candidate.instance_id,
                ),
            )
            self.commercial_service.record_run_acceptance(session=session, run=run)

            if should_enqueue:
                session.commit()
                response = self._build_execution_response(
                    run,
                    repository=repository,
                    idempotent_replay=False,
                )
                self.run_lifecycle_service.publish_queue_signal(run.run_id)
                return response

            provider_input_payload = request.input_payload
            if self._is_wordpress_ai_connector_request(request):
                provider_input_payload = self._prepare_wordpress_operation_execution_input(
                    run,
                    repository=repository,
                    connector_envelope=connector_envelope or {},
                )

            self._execute_candidate_chain(
                run,
                repository=repository,
                candidates=resolution.candidates,
                input_payload=provider_input_payload,
                connector_envelope=connector_envelope,
            )
            session.commit()
            return self._build_execution_response(
                run,
                repository=repository,
                idempotent_replay=False,
            )

    def _execute_site_knowledge_request(
        self,
        request: RuntimeRequest,
    ) -> RuntimeExecutionResponse:
        self.contract_validator.validate_site_knowledge_contract(request)
        trace_id = request.trace_id or uuid4().hex
        run_id = f"run_{uuid4().hex}"
        merged_policy = self._build_site_knowledge_policy(request)
        request_fingerprint = self.run_lifecycle_service.build_request_fingerprint(
            request,
            merged_policy,
        )
        should_enqueue = self._should_enqueue(request, merged_policy)

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            self._require_active_site(repository, request.site_id)

            existing = self.run_lifecycle_service.get_idempotent_replay(
                repository=repository,
                site_id=request.site_id,
                idempotency_key=request.idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            if existing is not None:
                session.commit()
                return self._build_execution_response(
                    existing,
                    repository=repository,
                    idempotent_replay=True,
                )

            commercial_decision = self.commercial_service.authorize_runtime_request(
                session=session,
                site_id=request.site_id,
                ability_family=request.ability_family,
                channel=request.channel,
                execution_kind=request.execution_kind,
                execution_tier=request.execution_tier,
                data_classification=request.data_classification,
                trace_id=trace_id,
                idempotency_key=request.idempotency_key,
                request_kind=(
                    "status" if request.ability_name == SITE_KNOWLEDGE_STATUS_ABILITY else "execute"
                ),
                run_id=run_id,
                estimated_ai_credits=self._estimate_runtime_request_ai_credits(request),
            )
            self._enforce_batch_limits(
                request=request,
                commercial_decision=commercial_decision,
            )
            merged_policy = self._apply_commercial_policy_overrides(
                merged_policy,
                commercial_decision=commercial_decision,
            )
            should_enqueue = self._should_enqueue(request, merged_policy)
            storage_mode = self._get_storage_mode(merged_policy)
            execution_input_ciphertext = None
            if should_enqueue:
                execution_input_ciphertext = encrypt_runtime_execution_input(
                    request.input_payload,
                    settings=self.settings,
                )

            run = self.run_lifecycle_service.create_durable_run(
                repository=repository,
                command=RuntimeRunCreationCommand(
                    run_id=run_id,
                    site_id=request.site_id,
                    account_id=str(commercial_decision.get("account_id") or "") or None,
                    subscription_id=str(commercial_decision.get("subscription_id") or "") or None,
                    plan_version_id=str(commercial_decision.get("plan_version_id") or "") or None,
                    ability_name=request.ability_name,
                    ability_family=request.ability_family,
                    skill_id=request.skill_id,
                    workflow_id=request.workflow_id,
                    contract_version=request.contract_version,
                    channel=request.channel,
                    execution_kind=request.execution_kind,
                    execution_tier=request.execution_tier,
                    execution_pattern=request.execution_pattern,
                    data_classification=request.data_classification,
                    profile_id=request.profile_id,
                    canonical_run_id=request.canonical_run_id or None,
                    status="queued" if should_enqueue else "running",
                    idempotency_key=request.idempotency_key,
                    request_fingerprint=request_fingerprint,
                    trace_id=trace_id,
                    input_json=self._prepare_input_for_storage(
                        request.input_payload,
                        storage_mode=storage_mode,
                    ),
                    execution_input_ciphertext=execution_input_ciphertext,
                    policy_json=merged_policy,
                    selected_provider_id="site_knowledge",
                    selected_model_id="site-knowledge-managed",
                    selected_instance_id="cloud-runtime",
                ),
            )
            self.commercial_service.record_run_acceptance(session=session, run=run)

            if should_enqueue:
                session.commit()
                response = self._build_execution_response(
                    run,
                    repository=repository,
                    idempotent_replay=False,
                )
                self.run_lifecycle_service.publish_queue_signal(run.run_id)
                return response

            self._execute_site_knowledge_run(
                run,
                repository=repository,
                input_payload=request.input_payload,
            )
            session.commit()
            return self._build_execution_response(
                run,
                repository=repository,
                idempotent_replay=False,
            )

    def _execute_cloud_batch_runtime_request(
        self,
        request: RuntimeRequest,
    ) -> RuntimeExecutionResponse:
        self.contract_validator.validate_cloud_batch_runtime_contract(request)
        trace_id = request.trace_id or uuid4().hex
        run_id = f"run_{uuid4().hex}"
        merged_policy = self._build_cloud_batch_runtime_policy(request)
        request_fingerprint = self.run_lifecycle_service.build_request_fingerprint(
            request,
            merged_policy,
        )
        should_enqueue = self._should_enqueue(request, merged_policy)

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            self._require_active_site(repository, request.site_id)

            existing = self.run_lifecycle_service.get_idempotent_replay(
                repository=repository,
                site_id=request.site_id,
                idempotency_key=request.idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            if existing is not None:
                session.commit()
                return self._build_execution_response(
                    existing,
                    repository=repository,
                    idempotent_replay=True,
                )

            commercial_decision = self.commercial_service.authorize_runtime_request(
                session=session,
                site_id=request.site_id,
                ability_family=request.ability_family,
                channel=request.channel,
                execution_kind=request.execution_kind,
                execution_tier=request.execution_tier,
                data_classification=request.data_classification,
                trace_id=trace_id,
                idempotency_key=request.idempotency_key,
                request_kind="execute",
                run_id=run_id,
                estimated_ai_credits=self._estimate_runtime_request_ai_credits(request),
            )
            self._enforce_batch_limits(
                request=request,
                commercial_decision=commercial_decision,
            )
            merged_policy = self._apply_commercial_policy_overrides(
                merged_policy,
                commercial_decision=commercial_decision,
            )
            should_enqueue = self._should_enqueue(request, merged_policy)
            storage_mode = self._get_storage_mode(merged_policy)
            execution_input_ciphertext = None
            if should_enqueue:
                execution_input_ciphertext = encrypt_runtime_execution_input(
                    request.input_payload,
                    settings=self.settings,
                )

            run = self.run_lifecycle_service.create_durable_run(
                repository=repository,
                command=RuntimeRunCreationCommand(
                    run_id=run_id,
                    site_id=request.site_id,
                    account_id=str(commercial_decision.get("account_id") or "") or None,
                    subscription_id=str(commercial_decision.get("subscription_id") or "") or None,
                    plan_version_id=str(commercial_decision.get("plan_version_id") or "") or None,
                    ability_name=request.ability_name,
                    ability_family=request.ability_family,
                    skill_id=request.skill_id,
                    workflow_id=request.workflow_id,
                    contract_version=request.contract_version,
                    channel=request.channel,
                    execution_kind=request.execution_kind,
                    execution_tier=request.execution_tier,
                    execution_pattern=request.execution_pattern,
                    data_classification=request.data_classification,
                    profile_id=request.profile_id or CLOUD_BATCH_RUNTIME_PROFILE_ID,
                    canonical_run_id=request.canonical_run_id or None,
                    status="queued" if should_enqueue else "running",
                    idempotency_key=request.idempotency_key,
                    request_fingerprint=request_fingerprint,
                    trace_id=trace_id,
                    input_json=self._prepare_input_for_storage(
                        request.input_payload,
                        storage_mode=storage_mode,
                    ),
                    execution_input_ciphertext=execution_input_ciphertext,
                    policy_json=merged_policy,
                    selected_provider_id="cloud_batch_runtime",
                    selected_model_id="deterministic-content-quality-v1",
                    selected_instance_id="cloud-runtime",
                ),
            )
            self.commercial_service.record_run_acceptance(session=session, run=run)

            if should_enqueue:
                session.commit()
                response = self._build_execution_response(
                    run,
                    repository=repository,
                    idempotent_replay=False,
                )
                self.run_lifecycle_service.publish_queue_signal(run.run_id)
                return response

            self._execute_cloud_batch_runtime_run(
                run,
                repository=repository,
                input_payload=request.input_payload,
            )
            session.commit()
            return self._build_execution_response(
                run,
                repository=repository,
                idempotent_replay=False,
            )

    def create_media_upload(
        self,
        *,
        site_id: str,
        request_payload: dict[str, Any],
        stream: Any,
        upload: Any,
        ttl_minutes: int,
        idempotency_key: str | None = None,
        trace_id: str | None = None,
    ) -> RuntimeExecutionResponse:
        return self.artifact_coordination_service.create_media_upload(
            site_id=site_id,
            request_payload=request_payload,
            stream=stream,
            upload=upload,
            ttl_minutes=ttl_minutes,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
        )

    def enqueue_media_job_run(
        self,
        *,
        site_id: str,
        input_payload: dict[str, Any],
        idempotency_key: str | None = None,
        trace_id: str | None = None,
    ) -> RuntimeExecutionResponse:
        return self.artifact_coordination_service.enqueue_media_job_run(
            site_id=site_id,
            input_payload=input_payload,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
        )

    def get_media_derivative_queue_pressure(self, *, site_id: str) -> dict[str, object]:
        queued_limit = max(1, int(self.settings.media_derivative_site_queued_limit))
        running_limit = max(1, int(self.settings.media_derivative_site_running_limit))
        default_chunk_size = max(
            1,
            min(
                int(self.settings.media_derivative_batch_default_chunk_size),
                int(self.settings.media_derivative_batch_max_chunk_size),
            ),
        )
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            counts = repository.summarize_media_derivative_queue_pressure(site_id)
            session.commit()

        queued = int(counts.get("queued") or 0)
        running = int(counts.get("running") or 0)
        queue_remaining = max(0, queued_limit - queued)
        running_remaining = max(0, running_limit - running)
        pressure_state = "healthy"
        pressure_reasons: list[str] = []
        if queued >= queued_limit:
            pressure_state = "rejecting"
            pressure_reasons.append("site_media_derivative_queue_full")
        elif running >= running_limit or queued >= max(default_chunk_size * 2, queued_limit // 2):
            pressure_state = "attention"
            if running >= running_limit:
                pressure_reasons.append("site_media_derivative_running_saturated")
            if queued >= max(default_chunk_size * 2, queued_limit // 2):
                pressure_reasons.append("site_media_derivative_queue_depth_high")

        return {
            "scope": "site",
            "site_id": site_id,
            "queued": queued,
            "running": running,
            "limits": {
                "queued": queued_limit,
                "running": running_limit,
            },
            "remaining": {
                "queued": queue_remaining,
                "running": running_remaining,
            },
            "pressure_state": pressure_state,
            "pressure_reasons": pressure_reasons,
            "recommended_chunk_size": max(1, min(default_chunk_size, queue_remaining or 1)),
        }

    def _execute_media_derivative_run(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
    ) -> None:
        self.artifact_coordination_service.execute_media_derivative_run(
            run,
            repository=repository,
        )

    def process_next_queued_run(self, *, timeout_seconds: int = 1) -> dict[str, object] | None:
        return self.run_lifecycle_service.process_next_queued_run(
            timeout_seconds=timeout_seconds,
        )

    def process_queued_runs(
        self,
        *,
        max_runs: int = 1,
        timeout_seconds: int = 1,
    ) -> list[dict[str, object]]:
        return self.run_lifecycle_service.process_queued_runs(
            max_runs=max_runs,
            timeout_seconds=timeout_seconds,
        )

    def get_run(self, run_id: str, *, site_id: str | None = None) -> dict[str, object]:
        return self.run_lifecycle_service.get_run(run_id, site_id=site_id)

    def get_run_result(self, run_id: str, *, site_id: str | None = None) -> dict[str, object]:
        return self.run_lifecycle_service.get_run_result(run_id, site_id=site_id)

    def list_recent_nightly_inspection_runs(
        self,
        *,
        site_id: str,
        limit: int = 10,
    ) -> dict[str, object]:
        max_items = max(1, min(50, limit))
        with get_session(self.database_url) as session:
            runs = list(
                session.scalars(
                    select(RunRecord)
                    .where(
                        RunRecord.site_id == site_id,
                        RunRecord.execution_kind == CLOUD_BATCH_RUNTIME_EXECUTION_KIND,
                    )
                    .order_by(RunRecord.started_at.desc(), RunRecord.run_id.desc())
                    .limit(max_items)
                )
            )
            provider_calls_by_run = {
                run.run_id: RuntimeRepository(session).list_provider_calls(run.run_id)
                for run in runs
            }
            session.commit()

        items = [
            self._serialize_nightly_inspection_run_card(
                run,
                provider_calls=provider_calls_by_run.get(run.run_id, []),
            )
            for run in runs
        ]
        latest = items[0] if items else {}

        def item_retryable(item: dict[str, object]) -> bool:
            run_state = self._dict_or_empty(item.get("run_state"))
            retry = self._dict_or_empty(run_state.get("retry"))
            return bool(retry.get("retryable"))

        latest_failure = next(
            (item for item in items if item.get("status") == "failed" or item_retryable(item)),
            {},
        )
        return {
            "contract_version": "nightly_site_inspection_recent_runs.v1",
            "site_id": site_id,
            "limit": max_items,
            "items": items,
            "latest": latest,
            "latest_failure": latest_failure,
            "toolbox_guidance": {
                "display_surface": "morning_brief_recent_runs",
                "primary_next_action": (
                    "inspect_latest_failure"
                    if latest_failure
                    else "review_latest_morning_brief"
                    if latest
                    else "run_nightly_inspection"
                ),
                "polling_supported": True,
                "cloud_scheduler_truth": False,
                "direct_wordpress_write": False,
            },
            "boundary": {
                "cloud_role": "runtime_detail",
                "schedule_truth": "wordpress_local",
                "proposal_truth": "magick_ai_core",
                "final_write_truth": "wordpress_local",
                "direct_wordpress_write": False,
            },
        }

    def retry_nightly_inspection_run(
        self,
        *,
        run_id: str,
        site_id: str,
        idempotency_key: str,
        trace_id: str,
        input_payload: dict[str, Any] | None = None,
    ) -> RuntimeExecutionResponse:
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            run = repository.get_run(run_id)
            if run is None or run.site_id != site_id:
                raise RuntimeRunNotFoundError(run_id)
            if not self._is_cloud_batch_runtime_run(run):
                raise RuntimeExecutionContractError(
                    "runtime.retry_not_supported",
                    "retry is only supported for nightly inspection cloud batch runs",
                )
            if run.status not in {"failed", "canceled", "succeeded"}:
                raise RuntimeExecutionContractError(
                    "runtime.retry_not_allowed",
                    "retry requires a terminal nightly inspection run",
                )
            stored_input = self._get_execution_input_payload(run)
            policy = run.policy_json if isinstance(run.policy_json, dict) else {}
            retry_run_context = {
                "ability_name": run.ability_name,
                "ability_family": run.ability_family,
                "canonical_run_id": run.canonical_run_id or run.run_id,
                "skill_id": run.skill_id or "",
                "workflow_id": run.workflow_id or "",
                "contract_version": run.contract_version or "",
                "channel": run.channel,
                "execution_kind": run.execution_kind,
                "execution_tier": run.execution_tier,
                "execution_pattern": self.run_projector.public_execution_pattern(
                    run.execution_pattern
                ),
                "data_classification": run.data_classification,
                "profile_id": run.profile_id,
            }
            session.commit()

        retry_input = input_payload if isinstance(input_payload, dict) else stored_input
        if not retry_input:
            raise RuntimeExecutionContractError(
                "runtime.retry_input_required",
                "nightly inspection retry requires the original batch input payload",
            )

        request = RuntimeRequest(
            site_id=site_id,
            ability_name=str(retry_run_context["ability_name"]),
            ability_family=str(retry_run_context["ability_family"]),
            canonical_run_id=str(retry_run_context["canonical_run_id"]),
            skill_id=str(retry_run_context["skill_id"]),
            workflow_id=str(retry_run_context["workflow_id"]),
            contract_version=str(retry_run_context["contract_version"]),
            channel=str(retry_run_context["channel"]),
            execution_kind=str(retry_run_context["execution_kind"]),
            execution_tier=str(retry_run_context["execution_tier"]),
            execution_pattern=str(retry_run_context["execution_pattern"]),
            data_classification=str(retry_run_context["data_classification"]),
            storage_mode=str(policy.get("storage_mode") or RUNTIME_STORAGE_MODE_RESULT_ONLY),
            timeout_seconds=self._coerce_int(policy.get("timeout_seconds"), default=0),
            retry_max=self._coerce_int(policy.get("retry_max"), default=0),
            retention_ttl=self._coerce_int(policy.get("retention_ttl"), default=0),
            task_backend=self._dict_or_empty(policy.get("task_backend")),
            profile_id=str(retry_run_context["profile_id"]),
            input_payload=retry_input,
            policy={},
            idempotency_key=idempotency_key,
            trace_id=trace_id,
        )
        return self.execute(request)

    def get_nightly_inspection_observability(
        self,
        *,
        site_id: str | None = None,
        recent_minutes: int = 1440,
        limit: int = 20,
    ) -> dict[str, object]:
        current_time = datetime.now(UTC)
        recent_since = current_time - timedelta(minutes=max(1, recent_minutes))
        max_items = max(1, min(100, limit))
        with get_session(self.database_url) as session:
            run_statement = select(RunRecord).where(
                RunRecord.execution_kind == CLOUD_BATCH_RUNTIME_EXECUTION_KIND,
                RunRecord.started_at >= recent_since,
            )
            if site_id:
                run_statement = run_statement.where(RunRecord.site_id == site_id)
            runs = list(
                session.scalars(
                    run_statement.order_by(
                        RunRecord.started_at.desc(),
                        RunRecord.run_id.desc(),
                    ).limit(5000)
                )
            )
            run_ids = [run.run_id for run in runs]
            provider_calls = (
                list(
                    session.scalars(
                        select(ProviderCallRecord)
                        .where(ProviderCallRecord.run_id.in_(run_ids))
                        .order_by(ProviderCallRecord.created_at.desc())
                    )
                )
                if run_ids
                else []
            )
            usage_events = (
                list(
                    session.scalars(
                        select(UsageMeterEvent).where(
                            UsageMeterEvent.run_id.in_(run_ids),
                            UsageMeterEvent.created_at >= recent_since,
                        )
                    )
                )
                if run_ids
                else []
            )
            session.commit()

        status_counts: dict[str, int] = {}
        for run in runs:
            status_counts[run.status] = status_counts.get(run.status, 0) + 1
        failed_runs = [run for run in runs if run.status == "failed"]
        partial_runs = [
            run
            for run in runs
            if isinstance(run.result_json, dict)
            and str(run.result_json.get("status") or "") == "partially_succeeded"
        ]
        retryable_partial_runs = [
            run
            for run in partial_runs
            if bool(
                self._dict_or_empty(self._dict_or_empty(run.result_json).get("retry_guidance")).get(
                    "retryable"
                )
            )
        ]
        provider_error_calls = [call for call in provider_calls if call.error_code]
        metered_run_ids = {
            str(event.run_id or "")
            for event in usage_events
            if str(event.run_id or "").strip() and event.meter_key == "runs"
        }
        run_cards = [
            self._serialize_nightly_inspection_run_card(
                run,
                provider_calls=[call for call in provider_calls if call.run_id == run.run_id],
            )
            for run in runs[:max_items]
        ]
        alert_state = (
            "error"
            if failed_runs or provider_error_calls
            else "warning"
            if partial_runs
            else "ok"
            if runs
            else "inactive"
        )
        return {
            "contract_version": "nightly_site_inspection_observability.v1",
            "filters": {
                "site_id": site_id or "",
                "recent_minutes": recent_minutes,
                "limit": max_items,
            },
            "generated_at": self.run_projector.serialize_timestamp(current_time),
            "window": {
                "since": self.run_projector.serialize_timestamp(recent_since),
                "until": self.run_projector.serialize_timestamp(current_time),
            },
            "totals": {
                "runs": len(runs),
                "status_counts": status_counts,
                "partial_success_runs": len(partial_runs),
                "retryable_partial_runs": len(retryable_partial_runs),
                "provider_calls": len(provider_calls),
                "provider_error_calls": len(provider_error_calls),
                "usage_meter_events": len(usage_events),
                "metered_run_coverage_rate": self._safe_ratio(
                    len(metered_run_ids),
                    len(runs),
                ),
            },
            "alert_summary": {
                "status": alert_state,
                "primary_reason": (
                    "failed_runs"
                    if failed_runs
                    else "provider_error_calls"
                    if provider_error_calls
                    else "partial_success_runs"
                    if partial_runs
                    else "healthy"
                    if runs
                    else "no_recent_runs"
                ),
                "suggested_action": (
                    "inspect_failed_nightly_inspection_runs"
                    if failed_runs or provider_error_calls
                    else "review_partial_success_retry_guidance"
                    if partial_runs
                    else "continue_monitoring"
                ),
            },
            "recent_runs": run_cards,
            "boundary": {
                "surface": "internal_operator_diagnostics",
                "cloud_role": "runtime_detail",
                "schedule_truth": "wordpress_local",
                "proposal_truth": "magick_ai_core",
                "final_write_truth": "wordpress_local",
                "direct_wordpress_write": False,
                "contains_prompt_or_result_payloads": False,
            },
        }

    def get_runtime_diagnostics_summary(
        self,
        *,
        site_id: str | None = None,
        recent_minutes: int = 60,
    ) -> dict[str, object]:
        current_time = datetime.now(UTC)
        recent_since = current_time - timedelta(minutes=max(1, recent_minutes))
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            summary = repository.get_runtime_diagnostics_summary(
                site_id=site_id,
                now=current_time,
                recent_since=recent_since,
            )
            guard_summary = {
                "recent_events": repository.count_runtime_guard_events(
                    since=recent_since,
                    site_id=site_id,
                ),
                "recent_rate_limit_exceeded": repository.count_runtime_guard_events(
                    since=recent_since,
                    site_id=site_id,
                    event_code="auth.rate_limit_exceeded",
                ),
                "recent_replay_blocked": repository.count_runtime_guard_events(
                    since=recent_since,
                    site_id=site_id,
                    event_code="auth.replay_blocked",
                ),
                "recent_payload_too_large": repository.count_runtime_guard_events(
                    since=recent_since,
                    site_id=site_id,
                    event_code="auth.payload_too_large",
                ),
                "recent_invalid_nonce": repository.count_runtime_guard_events(
                    since=recent_since,
                    site_id=site_id,
                    event_code="auth.invalid_nonce",
                ),
                "recent_invalid_idempotency_key": repository.count_runtime_guard_events(
                    since=recent_since,
                    site_id=site_id,
                    event_code="auth.invalid_idempotency_key",
                ),
                "event_codes": repository.summarize_runtime_guard_event_codes(
                    since=recent_since,
                    site_id=site_id,
                    limit=10,
                ),
            }
        summary = self._augment_runtime_diagnostics_summary(summary, current_time)
        return {
            "filters": {
                "site_id": site_id or "",
                "recent_minutes": recent_minutes,
            },
            "generated_at": self.run_projector.serialize_timestamp(current_time),
            "guard": guard_summary,
            **summary,
        }

    def get_runtime_telemetry_diagnostics(
        self,
        *,
        site_id: str | None = None,
        recent_minutes: int = 60,
        limit: int = 20,
    ) -> dict[str, object]:
        current_time = datetime.now(UTC)
        recent_since = current_time - timedelta(minutes=max(1, recent_minutes))
        max_items = max(1, min(100, limit))
        with get_session(self.database_url) as session:
            run_statement = select(RunRecord).where(RunRecord.started_at >= recent_since)
            if site_id:
                run_statement = run_statement.where(RunRecord.site_id == site_id)
            runs = list(
                session.scalars(
                    run_statement.order_by(
                        RunRecord.started_at.desc(),
                        RunRecord.run_id.desc(),
                    ).limit(5000)
                )
            )

            call_statement = (
                select(ProviderCallRecord, RunRecord)
                .join(RunRecord, ProviderCallRecord.run_id == RunRecord.run_id)
                .where(ProviderCallRecord.created_at >= recent_since)
            )
            if site_id:
                call_statement = call_statement.where(RunRecord.site_id == site_id)
            provider_call_rows = list(
                session.execute(
                    call_statement.order_by(
                        ProviderCallRecord.created_at.desc(),
                        ProviderCallRecord.id.desc(),
                    ).limit(10000)
                )
            )

            meter_statement = select(UsageMeterEvent).where(
                UsageMeterEvent.created_at >= recent_since
            )
            if site_id:
                meter_statement = meter_statement.where(UsageMeterEvent.site_id == site_id)
            meter_events = list(
                session.scalars(
                    meter_statement.order_by(
                        UsageMeterEvent.created_at.desc(),
                        UsageMeterEvent.id.desc(),
                    ).limit(10000)
                )
            )

        run_ids = {run.run_id for run in runs}
        ai_evidence_required_run_ids = {
            run.run_id
            for run in runs
            if str(run.execution_kind or "").strip() not in NON_AI_ZERO_CREDIT_EXECUTION_KINDS
        }
        provider_call_run_ids = {
            call.run_id for call, _run in provider_call_rows if call.run_id in run_ids
        }
        meter_run_ids = {
            str(event.run_id or "") for event in meter_events if str(event.run_id or "") in run_ids
        }
        run_groups: dict[str, dict[str, object]] = {}
        profile_groups: dict[str, dict[str, object]] = {}
        execution_kind_groups: dict[str, dict[str, object]] = {}
        provider_model_groups: dict[str, dict[str, object]] = {}

        for run in runs:
            family = str(run.ability_family or "unknown").strip() or "unknown"
            profile_id = str(run.profile_id or "unknown").strip() or "unknown"
            execution_kind = str(run.execution_kind or "unknown").strip() or "unknown"
            self._update_hosted_governance_run_group(
                run_groups.setdefault(
                    family,
                    self._empty_hosted_governance_group(
                        group_kind="ability_family",
                        group_id=family,
                    ),
                ),
                run,
            )
            self._update_hosted_governance_run_group(
                profile_groups.setdefault(
                    profile_id,
                    self._empty_hosted_governance_group(
                        group_kind="profile_id",
                        group_id=profile_id,
                    ),
                ),
                run,
            )
            self._update_hosted_governance_run_group(
                execution_kind_groups.setdefault(
                    execution_kind,
                    self._empty_hosted_governance_group(
                        group_kind="execution_kind",
                        group_id=execution_kind,
                    ),
                ),
                run,
            )

        for call, run in provider_call_rows:
            family = str(run.ability_family or "unknown").strip() or "unknown"
            profile_id = str(run.profile_id or "unknown").strip() or "unknown"
            execution_kind = str(run.execution_kind or "unknown").strip() or "unknown"
            provider_model_key = f"{call.provider_id or 'unknown'}::{call.model_id or 'unknown'}"
            for group in (
                run_groups.setdefault(
                    family,
                    self._empty_hosted_governance_group(
                        group_kind="ability_family",
                        group_id=family,
                    ),
                ),
                profile_groups.setdefault(
                    profile_id,
                    self._empty_hosted_governance_group(
                        group_kind="profile_id",
                        group_id=profile_id,
                    ),
                ),
                execution_kind_groups.setdefault(
                    execution_kind,
                    self._empty_hosted_governance_group(
                        group_kind="execution_kind",
                        group_id=execution_kind,
                    ),
                ),
                provider_model_groups.setdefault(
                    provider_model_key,
                    self._empty_hosted_governance_group(
                        group_kind="provider_model",
                        group_id=provider_model_key,
                    ),
                ),
            ):
                self._update_hosted_governance_provider_call_group(group, call)

        for event in meter_events:
            family = str(event.ability_family or "unknown").strip() or "unknown"
            execution_kind = str(event.execution_kind or "unknown").strip() or "unknown"
            for group in (
                run_groups.setdefault(
                    family,
                    self._empty_hosted_governance_group(
                        group_kind="ability_family",
                        group_id=family,
                    ),
                ),
                execution_kind_groups.setdefault(
                    execution_kind,
                    self._empty_hosted_governance_group(
                        group_kind="execution_kind",
                        group_id=execution_kind,
                    ),
                ),
            ):
                self._update_hosted_governance_meter_group(group, event)

        capability_items = self._finalize_hosted_governance_groups(
            run_groups.values(),
            limit=max_items,
            provider_call_run_ids=provider_call_run_ids,
            meter_run_ids=meter_run_ids,
            ai_evidence_required_run_ids=ai_evidence_required_run_ids,
        )
        profile_items = self._finalize_hosted_governance_groups(
            profile_groups.values(),
            limit=max_items,
            provider_call_run_ids=provider_call_run_ids,
            meter_run_ids=meter_run_ids,
            ai_evidence_required_run_ids=ai_evidence_required_run_ids,
        )
        execution_kind_items = self._finalize_hosted_governance_groups(
            execution_kind_groups.values(),
            limit=max_items,
            provider_call_run_ids=provider_call_run_ids,
            meter_run_ids=meter_run_ids,
            ai_evidence_required_run_ids=ai_evidence_required_run_ids,
        )
        provider_model_items = self._finalize_hosted_governance_groups(
            provider_model_groups.values(),
            limit=max_items,
            provider_call_run_ids=provider_call_run_ids,
            meter_run_ids=meter_run_ids,
            ai_evidence_required_run_ids=ai_evidence_required_run_ids,
        )
        governance_gaps = self._build_hosted_governance_gap_summary(
            capability_items=capability_items,
            ai_evidence_required_run_ids=ai_evidence_required_run_ids,
            provider_call_run_ids=provider_call_run_ids,
            meter_run_ids=meter_run_ids,
        )
        result: dict[str, object] = {
            "filters": {
                "site_id": site_id or "",
                "recent_minutes": recent_minutes,
                "limit": max_items,
            },
            "generated_at": self.run_projector.serialize_timestamp(current_time),
            "window": {
                "since": self.run_projector.serialize_timestamp(recent_since),
                "until": self.run_projector.serialize_timestamp(current_time),
            },
            "totals": {
                "runs": len(runs),
                "ai_evidence_required_runs": len(ai_evidence_required_run_ids),
                "non_ai_zero_credit_runs": len(runs) - len(ai_evidence_required_run_ids),
                "provider_calls": len(provider_call_rows),
                "usage_meter_events": len(meter_events),
                "provider_call_run_coverage_rate": self._safe_coverage_ratio(
                    len(provider_call_run_ids & ai_evidence_required_run_ids),
                    len(ai_evidence_required_run_ids),
                ),
                "metered_run_coverage_rate": self._safe_coverage_ratio(
                    len(meter_run_ids & ai_evidence_required_run_ids),
                    len(ai_evidence_required_run_ids),
                ),
            },
            "capability_groups": capability_items,
            "profile_groups": profile_items,
            "execution_kind_groups": execution_kind_items,
            "provider_model_groups": provider_model_items,
            "governance_gaps": governance_gaps,
            "boundary": {
                "surface": "internal_operator_diagnostics",
                "cloud_role": "hosted_runtime_detail",
                "local_control_plane": "wordpress_plugin",
                "direct_wordpress_write": False,
                "contains_prompt_or_result_payloads": False,
            },
        }
        result["alert_summary"] = self._build_hosted_governance_alert_summary(result)
        return result

    def get_runtime_backlog_diagnostics(
        self,
        *,
        scope_kind: str,
        site_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, object]:
        current_time = datetime.now(UTC)
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            runs = repository.list_runtime_backlog_runs(site_id=site_id)

        queued_ages: list[int] = []
        running_ages: list[int] = []
        grouped_runs: dict[str, dict[str, object]] = {}
        for run in runs:
            age_seconds = self._resolve_backlog_age_seconds(run, current_time)
            scope_id = self._resolve_backlog_scope_id(run, scope_kind)
            entry = grouped_runs.setdefault(
                scope_id,
                {
                    "scope_kind": scope_kind,
                    "scope_id": scope_id,
                    "queued_ages": [],
                    "running_ages": [],
                },
            )
            if run.status == "queued":
                queued_ages.append(age_seconds)
                cast(list[int], entry["queued_ages"]).append(age_seconds)
            elif run.status == "running":
                running_ages.append(age_seconds)
                cast(list[int], entry["running_ages"]).append(age_seconds)

        total_queued = self._summarize_backlog_status(
            queued_ages,
            aging_after_seconds=RUNTIME_BACKLOG_QUEUED_AGING_AFTER_SECONDS,
            stale_after_seconds=RUNTIME_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS,
        )
        total_running = self._summarize_backlog_status(
            running_ages,
            aging_after_seconds=RUNTIME_BACKLOG_RUNNING_AGING_AFTER_SECONDS,
            stale_after_seconds=RUNTIME_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS,
        )

        items: list[dict[str, object]] = []
        for item in grouped_runs.values():
            item_queued = self._summarize_backlog_status(
                cast(list[int], item["queued_ages"]),
                aging_after_seconds=RUNTIME_BACKLOG_QUEUED_AGING_AFTER_SECONDS,
                stale_after_seconds=RUNTIME_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS,
            )
            item_running = self._summarize_backlog_status(
                cast(list[int], item["running_ages"]),
                aging_after_seconds=RUNTIME_BACKLOG_RUNNING_AGING_AFTER_SECONDS,
                stale_after_seconds=RUNTIME_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS,
            )
            pressure_state, pressure_reasons = self._classify_backlog_pressure(
                queued_state=str(item_queued["state"]),
                running_state=str(item_running["state"]),
            )
            items.append(
                {
                    "scope_kind": str(item["scope_kind"]),
                    "scope_id": str(item["scope_id"]),
                    "total_runs": self._coerce_int(item_queued.get("runs"), default=0)
                    + self._coerce_int(item_running.get("runs"), default=0),
                    "queued": item_queued,
                    "running": item_running,
                    "bottleneck_state": self._classify_backlog_bottleneck(
                        queued_state=str(item_queued["state"]),
                        running_state=str(item_running["state"]),
                    ),
                    "pressure_state": pressure_state,
                    "pressure_reasons": pressure_reasons,
                    "lease_recovery_inputs": {
                        "queued_stale_runs": self._coerce_int(
                            item_queued.get("stale_runs"), default=0
                        ),
                        "running_stale_runs": self._coerce_int(
                            item_running.get("stale_runs"), default=0
                        ),
                        "total_stale_runs": (
                            self._coerce_int(item_queued.get("stale_runs"), default=0)
                            + self._coerce_int(item_running.get("stale_runs"), default=0)
                        ),
                    },
                }
            )

        def backlog_sort_key(item: dict[str, object]) -> tuple[int, int, int, str]:
            lease_recovery_inputs = self._dict_or_empty(item.get("lease_recovery_inputs"))
            return (
                0
                if item.get("pressure_state") == "critical"
                else 1
                if item.get("pressure_state") == "attention"
                else 2,
                -self._coerce_int(lease_recovery_inputs.get("total_stale_runs"), default=0),
                -self._coerce_int(item.get("total_runs"), default=0),
                str(item.get("scope_id") or ""),
            )

        items.sort(key=backlog_sort_key)
        limited_items = items[: max(1, limit)]
        active_scope_count = len(items)
        pressured_scope_count = sum(1 for item in items if item["pressure_state"] != "healthy")
        stale_scope_count = sum(
            1
            for item in items
            if self._coerce_int(
                self._dict_or_empty(item.get("lease_recovery_inputs")).get("total_stale_runs"),
                default=0,
            )
            > 0
        )
        total_active_runs = max(
            1,
            self._coerce_int(total_queued.get("runs"), default=0)
            + self._coerce_int(total_running.get("runs"), default=0),
        )
        dominant_scope_share = (
            round(self._coerce_int(items[0].get("total_runs"), default=0) / total_active_runs, 3)
            if items
            else 0.0
        )
        total_pressure_state, total_pressure_reasons = self._classify_backlog_pressure(
            queued_state=str(total_queued["state"]),
            running_state=str(total_running["state"]),
        )

        return {
            "filters": {
                "site_id": site_id or "",
                "scope_kind": scope_kind,
                "limit": limit,
            },
            "generated_at": self.run_projector.serialize_timestamp(current_time),
            "thresholds": {
                "queued_aging_after_seconds": RUNTIME_BACKLOG_QUEUED_AGING_AFTER_SECONDS,
                "queued_stale_after_seconds": RUNTIME_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS,
                "running_aging_after_seconds": RUNTIME_BACKLOG_RUNNING_AGING_AFTER_SECONDS,
                "running_stale_after_seconds": RUNTIME_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS,
            },
            "totals": {
                "queued": total_queued,
                "running": total_running,
                "bottleneck_state": self._classify_backlog_bottleneck(
                    queued_state=str(total_queued["state"]),
                    running_state=str(total_running["state"]),
                ),
                "pressure_state": total_pressure_state,
                "pressure_reasons": total_pressure_reasons,
                "lease_recovery_inputs": {
                    "queued_stale_runs": self._coerce_int(
                        total_queued.get("stale_runs"), default=0
                    ),
                    "running_stale_runs": self._coerce_int(
                        total_running.get("stale_runs"), default=0
                    ),
                    "stale_scope_count": stale_scope_count,
                },
            },
            "scope_pressure": {
                "scope_kind": scope_kind,
                "active_scope_count": active_scope_count,
                "pressured_scope_count": pressured_scope_count,
                "stale_scope_count": stale_scope_count,
                "spread_state": self._classify_backlog_spread_state(
                    pressured_scope_count=pressured_scope_count,
                    stale_scope_count=stale_scope_count,
                    dominant_scope_share=dominant_scope_share,
                ),
                "dominant_scope_share": dominant_scope_share,
            },
            "items": limited_items,
        }

    def _empty_hosted_governance_group(
        self,
        *,
        group_kind: str,
        group_id: str,
    ) -> dict[str, object]:
        return {
            "group_kind": group_kind,
            "group_id": group_id,
            "run_ids": set(),
            "provider_call_run_ids": set(),
            "meter_run_ids": set(),
            "runs_total": 0,
            "succeeded": 0,
            "failed": 0,
            "queued": 0,
            "running": 0,
            "canceled": 0,
            "provider_calls": 0,
            "provider_errors": 0,
            "latency_ms_total": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "cost": 0.0,
            "meter_events": 0,
            "meter_totals": {},
            "profile_ids": set(),
            "execution_kinds": set(),
            "provider_ids": set(),
            "model_ids": set(),
            "instance_ids": set(),
            "data_classifications": set(),
        }

    def _update_hosted_governance_run_group(
        self,
        group: dict[str, object],
        run: RunRecord,
    ) -> None:
        cast(set[str], group["run_ids"]).add(run.run_id)
        group["runs_total"] = self._coerce_int(group.get("runs_total"), default=0) + 1
        status = str(run.status or "unknown")
        if status == "succeeded":
            group["succeeded"] = self._coerce_int(group.get("succeeded"), default=0) + 1
        elif status == "failed":
            group["failed"] = self._coerce_int(group.get("failed"), default=0) + 1
        elif status == "queued":
            group["queued"] = self._coerce_int(group.get("queued"), default=0) + 1
        elif status == "running":
            group["running"] = self._coerce_int(group.get("running"), default=0) + 1
        elif status == "canceled":
            group["canceled"] = self._coerce_int(group.get("canceled"), default=0) + 1

        self._add_nonempty(cast(set[str], group["profile_ids"]), run.profile_id)
        self._add_nonempty(cast(set[str], group["execution_kinds"]), run.execution_kind)
        self._add_nonempty(
            cast(set[str], group["data_classifications"]),
            run.data_classification,
        )

    def _update_hosted_governance_provider_call_group(
        self,
        group: dict[str, object],
        call: ProviderCallRecord,
    ) -> None:
        cast(set[str], group["run_ids"]).add(call.run_id)
        cast(set[str], group["provider_call_run_ids"]).add(call.run_id)
        group["provider_calls"] = self._coerce_int(group.get("provider_calls"), default=0) + 1
        if call.error_code:
            group["provider_errors"] = self._coerce_int(group.get("provider_errors"), default=0) + 1
        group["latency_ms_total"] = self._coerce_int(
            group.get("latency_ms_total"), default=0
        ) + self._coerce_int(call.latency_ms, default=0)
        group["tokens_in"] = self._coerce_int(group.get("tokens_in"), default=0) + self._coerce_int(
            call.tokens_in, default=0
        )
        group["tokens_out"] = self._coerce_int(
            group.get("tokens_out"), default=0
        ) + self._coerce_int(call.tokens_out, default=0)
        cost = self._coerce_float(group.get("cost")) or 0.0
        group["cost"] = round(cost + float(call.cost or 0.0), 8)
        self._add_nonempty(cast(set[str], group["provider_ids"]), call.provider_id)
        self._add_nonempty(cast(set[str], group["model_ids"]), call.model_id)
        self._add_nonempty(cast(set[str], group["instance_ids"]), call.instance_id)

    def _update_hosted_governance_meter_group(
        self,
        group: dict[str, object],
        event: UsageMeterEvent,
    ) -> None:
        run_id = str(event.run_id or "").strip()
        if run_id:
            cast(set[str], group["run_ids"]).add(run_id)
            cast(set[str], group["meter_run_ids"]).add(run_id)
        group["meter_events"] = self._coerce_int(group.get("meter_events"), default=0) + 1
        meter_key = str(event.meter_key or "unknown").strip() or "unknown"
        meter_totals = cast(dict[str, float], group["meter_totals"])
        meter_totals[meter_key] = round(
            float(meter_totals.get(meter_key, 0.0)) + float(event.quantity or 0.0),
            8,
        )

    def _finalize_hosted_governance_groups(
        self,
        groups: Any,
        *,
        limit: int,
        provider_call_run_ids: set[str],
        meter_run_ids: set[str],
        ai_evidence_required_run_ids: set[str],
    ) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for raw_group in groups:
            group = dict(raw_group)
            run_ids = cast(set[str], group.pop("run_ids", set()))
            group.pop("provider_call_run_ids", set())
            group.pop("meter_run_ids", set())
            runs_total = max(
                self._coerce_int(group.get("runs_total"), default=0),
                len(run_ids),
            )
            provider_calls = self._coerce_int(group.get("provider_calls"), default=0)
            provider_errors = self._coerce_int(group.get("provider_errors"), default=0)
            latency_total = self._coerce_int(group.pop("latency_ms_total", 0), default=0)
            tokens_in = self._coerce_int(group.get("tokens_in"), default=0)
            tokens_out = self._coerce_int(group.get("tokens_out"), default=0)
            group["runs_total"] = runs_total
            group_ai_evidence_required_run_ids = run_ids & ai_evidence_required_run_ids
            group["ai_evidence_required_runs"] = len(group_ai_evidence_required_run_ids)
            group["tokens_total"] = tokens_in + tokens_out
            group["avg_latency_ms"] = (
                round(latency_total / provider_calls, 2) if provider_calls else 0.0
            )
            group["provider_error_rate"] = self._safe_ratio(provider_errors, provider_calls)
            group["provider_call_run_coverage_rate"] = self._safe_coverage_ratio(
                len(group_ai_evidence_required_run_ids & provider_call_run_ids),
                len(group_ai_evidence_required_run_ids),
            )
            group["metered_run_coverage_rate"] = self._safe_coverage_ratio(
                len(group_ai_evidence_required_run_ids & meter_run_ids),
                len(group_ai_evidence_required_run_ids),
            )
            group["profile_ids"] = sorted(cast(set[str], group["profile_ids"]))[:10]
            group["execution_kinds"] = sorted(cast(set[str], group["execution_kinds"]))[:10]
            group["provider_ids"] = sorted(cast(set[str], group["provider_ids"]))[:10]
            group["model_ids"] = sorted(cast(set[str], group["model_ids"]))[:10]
            group["instance_ids"] = sorted(cast(set[str], group["instance_ids"]))[:10]
            group["data_classifications"] = sorted(cast(set[str], group["data_classifications"]))[
                :10
            ]
            items.append(group)

        items.sort(
            key=lambda item: (
                -self._coerce_int(item.get("runs_total"), default=0),
                -self._coerce_int(item.get("provider_calls"), default=0),
                -(self._coerce_float(item.get("cost")) or 0.0),
                str(item.get("group_id") or ""),
            )
        )
        return items[: max(1, limit)]

    def _build_hosted_governance_gap_summary(
        self,
        *,
        capability_items: list[dict[str, object]],
        ai_evidence_required_run_ids: set[str],
        provider_call_run_ids: set[str],
        meter_run_ids: set[str],
    ) -> dict[str, object]:
        unmetered_capabilities = [
            str(item.get("group_id") or "")
            for item in capability_items
            if self._coerce_int(item.get("ai_evidence_required_runs"), default=0) > 0
            and (self._coerce_float(item.get("metered_run_coverage_rate")) or 0.0) < 1.0
        ]
        missing_provider_call_capabilities = [
            str(item.get("group_id") or "")
            for item in capability_items
            if self._coerce_int(item.get("ai_evidence_required_runs"), default=0) > 0
            and self._coerce_int(item.get("provider_calls"), default=0) <= 0
            and str(item.get("group_id") or "") not in {"vision"}
        ]
        ai_runs_total = len(ai_evidence_required_run_ids)
        return {
            "unmetered_capabilities": unmetered_capabilities,
            "missing_provider_call_capabilities": missing_provider_call_capabilities,
            "unmetered_run_count": max(
                0,
                ai_runs_total - len(meter_run_ids & ai_evidence_required_run_ids),
            ),
            "runs_without_provider_call_count": max(
                0,
                ai_runs_total - len(provider_call_run_ids & ai_evidence_required_run_ids),
            ),
            "review_guidance": (
                "Inspect capabilities below full metering coverage before enabling "
                "new runtime providers at higher traffic."
            )
            if unmetered_capabilities or missing_provider_call_capabilities
            else "Recent runtime providers have meter coverage in this window.",
        }

    def _build_hosted_governance_alert_summary(
        self,
        diagnostics: dict[str, object],
    ) -> dict[str, object]:
        totals = self._dict_or_empty(diagnostics.get("totals"))
        gaps = self._dict_or_empty(diagnostics.get("governance_gaps"))
        raw_capability_items = diagnostics.get("capability_groups")
        raw_capability_items = (
            raw_capability_items if isinstance(raw_capability_items, list) else []
        )
        capability_items = [
            self._dict_or_empty(item) for item in raw_capability_items if isinstance(item, dict)
        ]
        runs_total = self._coerce_int(totals.get("runs"), default=0)
        ai_evidence_required_runs = self._coerce_int(
            totals.get("ai_evidence_required_runs"),
            default=runs_total,
        )
        non_ai_zero_credit_runs = self._coerce_int(
            totals.get("non_ai_zero_credit_runs"),
            default=0,
        )
        provider_calls = self._coerce_int(totals.get("provider_calls"), default=0)
        meter_events = self._coerce_int(totals.get("usage_meter_events"), default=0)
        metered_rate = self._coerce_float(totals.get("metered_run_coverage_rate")) or 0.0
        provider_rate = self._coerce_float(totals.get("provider_call_run_coverage_rate")) or 0.0
        unmetered_run_count = self._coerce_int(gaps.get("unmetered_run_count"), default=0)
        runs_without_provider_call_count = self._coerce_int(
            gaps.get("runs_without_provider_call_count"),
            default=0,
        )

        alerts: list[dict[str, object]] = []

        def add_alert(
            *,
            code: str,
            severity: str,
            title: str,
            summary: str,
            count: int,
            capabilities: list[str],
            suggested_action: str,
        ) -> None:
            alerts.append(
                {
                    "code": code,
                    "severity": severity,
                    "title": title,
                    "summary": summary,
                    "count": max(0, count),
                    "capabilities": capabilities[:10],
                    "suggested_action": suggested_action,
                    "href": "/admin/troubleshooting",
                }
            )

        unmetered_capabilities = [
            str(item)
            for item in self._list_or_empty(gaps.get("unmetered_capabilities"))
            if str(item or "").strip()
        ]
        if unmetered_run_count > 0 or unmetered_capabilities:
            add_alert(
                code="hosted_model.unmetered_runs",
                severity="error",
                title="Runtime meter coverage gap",
                summary="Some runtime runs are not represented in usage metering.",
                count=unmetered_run_count,
                capabilities=unmetered_capabilities,
                suggested_action="inspect_metering_callback_or_usage_event_mapping",
            )

        provider_gap_capabilities = [
            str(item.get("group_id") or "")
            for item in capability_items
            if isinstance(item, dict)
            and self._coerce_int(item.get("ai_evidence_required_runs"), default=0) > 0
            and (self._coerce_float(item.get("provider_call_run_coverage_rate")) or 0.0) < 1.0
        ]
        if runs_without_provider_call_count > 0 or provider_gap_capabilities:
            add_alert(
                code="hosted_model.provider_call_gap",
                severity="warning",
                title="Provider call coverage gap",
                summary="Some runtime runs do not have matching provider call telemetry.",
                count=runs_without_provider_call_count,
                capabilities=provider_gap_capabilities,
                suggested_action="inspect_provider_call_recording_for_hosted_profiles",
            )

        provider_error_groups = [
            str(item.get("group_id") or "")
            for item in capability_items
            if isinstance(item, dict)
            and self._coerce_int(item.get("provider_errors"), default=0) > 0
        ]
        provider_errors = sum(
            self._coerce_int(item.get("provider_errors"), default=0)
            for item in capability_items
            if isinstance(item, dict)
        )
        if provider_errors > 0:
            add_alert(
                code="hosted_model.provider_errors",
                severity="error" if provider_errors >= 5 else "warning",
                title="Provider call errors",
                summary="Provider calls are returning errors in the current telemetry window.",
                count=provider_errors,
                capabilities=provider_error_groups,
                suggested_action="inspect_provider_credentials_quota_and_health",
            )

        failed_groups = [
            str(item.get("group_id") or "")
            for item in capability_items
            if isinstance(item, dict) and self._coerce_int(item.get("failed"), default=0) > 0
        ]
        failed_runs = sum(
            self._coerce_int(item.get("failed"), default=0)
            for item in capability_items
            if isinstance(item, dict)
        )
        if failed_runs > 0:
            add_alert(
                code="hosted_model.failed_runs",
                severity="warning",
                title="Runtime runs failed",
                summary="Runtime runs are failing before or during provider execution.",
                count=failed_runs,
                capabilities=failed_groups,
                suggested_action="inspect_runtime_failure_detail",
            )

        alerts.sort(
            key=lambda item: (
                0 if item["severity"] == "error" else 1,
                -self._coerce_int(item.get("count"), default=0),
                str(item.get("code") or ""),
            )
        )
        status = (
            "inactive"
            if runs_total <= 0
            else "error"
            if any(item["severity"] == "error" for item in alerts)
            else "warning"
            if alerts
            else "ok"
        )
        if status == "inactive":
            summary = "No runtime runs were observed in this telemetry window."
            next_action = "continue_monitoring"
        elif status == "error":
            summary = "Runtime telemetry has coverage or provider errors that need review."
            next_action = str(alerts[0].get("suggested_action") or "inspect_runtime_telemetry")
        elif status == "warning":
            summary = "Runtime telemetry has coverage gaps to review before traffic expands."
            next_action = str(alerts[0].get("suggested_action") or "inspect_runtime_telemetry")
        else:
            summary = "Runtime telemetry is covered in this window."
            next_action = "continue_monitoring"

        return {
            "status": status,
            "summary": summary,
            "next_action": next_action,
            "href": "/admin/troubleshooting",
            "alerts": alerts[:8],
            "alert_count": len(alerts),
            "daily_digest": {
                "runs": runs_total,
                "ai_evidence_required_runs": ai_evidence_required_runs,
                "non_ai_zero_credit_runs": non_ai_zero_credit_runs,
                "provider_calls": provider_calls,
                "meter_events": meter_events,
                "metered_run_coverage_rate": metered_rate,
                "provider_call_run_coverage_rate": provider_rate,
                "unmetered_run_count": unmetered_run_count,
                "runs_without_provider_call_count": runs_without_provider_call_count,
            },
            "boundary": {
                "surface": "internal_admin_summary",
                "cloud_role": "hosted_runtime_detail",
                "local_control_plane": "wordpress_plugin",
                "direct_wordpress_write": False,
                "contains_prompt_or_result_payloads": False,
            },
        }

    def _add_nonempty(self, values: set[str], value: object) -> None:
        normalized = str(value or "").strip()
        if normalized:
            values.add(normalized)

    def _safe_ratio(self, numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(max(0, numerator) / denominator, 4)

    def _safe_coverage_ratio(self, numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 1.0
        return self._safe_ratio(numerator, denominator)

    def list_runtime_diagnostic_runs(
        self,
        *,
        issue_kind: str,
        site_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            runs = repository.list_runtime_diagnostic_runs(
                issue_kind=issue_kind,
                site_id=site_id,
                limit=limit,
            )
        return {
            "filters": {
                "issue_kind": issue_kind,
                "site_id": site_id or "",
                "limit": limit,
            },
            "items": [self._serialize_runtime_diagnostic_run(run) for run in runs],
        }

    def repair_run(
        self,
        *,
        run_id: str,
        action: str,
        audit_context: ServiceAuditContext | None,
        site_id: str | None = None,
        operator_reason: str = "",
        operator_evidence: str = "",
    ) -> dict[str, object]:
        normalized_action = str(action or "").strip()
        reason = str(operator_reason or "").strip()
        evidence = str(operator_evidence or "").strip()
        current_time = datetime.now(UTC)

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            run = repository.get_run(run_id)
            if run is None or (site_id and run.site_id != site_id):
                raise RuntimeRunNotFoundError(run_id)

            before = self._serialize_runtime_diagnostic_run(run)

            if normalized_action == "requeue_stale_queued":
                if run.status != "queued" or not self._is_queued_run_stale(run, current_time):
                    raise RuntimeExecutionContractError(
                        "runtime.repair_not_allowed",
                        "requeue_stale_queued requires a stale queued run",
                    )
                self.run_lifecycle_service.publish_queue_signal(run.run_id)
                outcome = {
                    "repair_action": normalized_action,
                    "state_transition": "queued->queued",
                    "operator_reason": reason,
                    "operator_evidence": evidence,
                }
            elif normalized_action == "redeliver_failed_callback":
                if not self._can_redeliver_callback(run, current_time):
                    raise RuntimeExecutionContractError(
                        "runtime.repair_not_allowed",
                        "redeliver_failed_callback requires a failed or overdue callback run",
                    )
                run.callback_status = RUN_CALLBACK_STATUS_PENDING
                run.callback_next_attempt_at = current_time
                run.callback_delivered_at = None
                if reason:
                    run.callback_last_error_message = reason
                session.flush()
                self.run_lifecycle_service.publish_queue_signal(run.run_id)
                outcome = {
                    "repair_action": normalized_action,
                    "state_transition": f"{before.get('callback_status') or ''}->pending",
                    "operator_reason": reason,
                    "operator_evidence": evidence,
                }
            elif normalized_action == "mark_stale_running_failed":
                if run.status != "running" or not self._is_running_run_stale(run, current_time):
                    raise RuntimeExecutionContractError(
                        "runtime.repair_not_allowed",
                        "mark_stale_running_failed requires a stale running run",
                    )
                self._validate_operator_repair_evidence(
                    action=normalized_action,
                    operator_reason=reason,
                    operator_evidence=evidence,
                )
                self.run_lifecycle_service.fail_run(
                    repository,
                    run,
                    error_code="runtime.operator_stale_running_failed",
                    error_message=f"operator marked stale running failed: {reason}",
                )
                outcome = {
                    "repair_action": normalized_action,
                    "state_transition": "running->failed",
                    "operator_reason": reason,
                    "operator_evidence": evidence,
                }
            else:
                raise RuntimeExecutionContractError(
                    "runtime.repair_action_invalid",
                    "unsupported runtime repair action",
                )

            after = self._serialize_runtime_diagnostic_run(run)
            session.commit()

        self.commercial_service.record_service_audit_event(
            audit_context=audit_context,
            event_kind=f"runtime.repair.{normalized_action}",
            outcome="succeeded",
            account_id=run.account_id,
            site_id=run.site_id,
            subscription_id=run.subscription_id,
            plan_version_id=run.plan_version_id,
            scope_kind="runtime_run",
            scope_id=run.run_id,
            payload_json={
                "run_id": run.run_id,
                "canonical_run_id": str(run.canonical_run_id or ""),
                "before": before,
                "after": after,
                **outcome,
            },
        )

        return {
            "run_id": run.run_id,
            "canonical_run_id": str(run.canonical_run_id or ""),
            "repair_action": normalized_action,
            "before": before,
            "after": after,
            "summary": outcome,
        }

    def _validate_operator_repair_evidence(
        self,
        *,
        action: str,
        operator_reason: str,
        operator_evidence: str,
    ) -> None:
        normalized_action = str(action or "").strip()
        if normalized_action != "mark_stale_running_failed":
            return

        reason = str(operator_reason or "").strip()
        evidence = str(operator_evidence or "").strip()
        if not reason or not evidence:
            raise RuntimeExecutionContractError(
                "runtime.repair_reason_required",
                "mark_stale_running_failed requires operator_reason and operator_evidence",
            )
        if len(reason) < OPERATOR_REPAIR_REASON_MIN_LENGTH:
            raise RuntimeExecutionContractError(
                "runtime.repair_reason_too_short",
                "mark_stale_running_failed requires a reason that explains why the run "
                "is considered stale",
            )
        if len(evidence) < OPERATOR_REPAIR_EVIDENCE_MIN_LENGTH:
            raise RuntimeExecutionContractError(
                "runtime.repair_evidence_too_short",
                "mark_stale_running_failed requires evidence that records the observed "
                "stale-running signals",
            )

    def run_bounded_auto_repairs(
        self,
        *,
        worker_id: str,
        max_stale_queued: int = 0,
        max_callback_overdue: int = 0,
        max_running_stale_suggestions: int = 20,
        site_id: str | None = None,
    ) -> dict[str, object]:
        normalized_worker_id = str(worker_id or "").strip() or "runtime_worker"
        queued_limit = max(0, int(max_stale_queued))
        callback_limit = max(0, int(max_callback_overdue))
        suggestion_limit = max(0, int(max_running_stale_suggestions))

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            stale_queued_runs = (
                repository.list_runtime_diagnostic_runs(
                    issue_kind="queued_stale",
                    site_id=site_id,
                    limit=queued_limit,
                )
                if queued_limit > 0
                else []
            )
            callback_overdue_runs = (
                repository.list_runtime_diagnostic_runs(
                    issue_kind="callback_overdue",
                    site_id=site_id,
                    limit=callback_limit,
                )
                if callback_limit > 0
                else []
            )
            running_stale_runs = (
                repository.list_runtime_diagnostic_runs(
                    issue_kind="running_stale",
                    site_id=site_id,
                    limit=max(1, suggestion_limit) if suggestion_limit > 0 else 1,
                )
                if suggestion_limit > 0
                else []
            )
            session.commit()

        audit_context = ServiceAuditContext(
            trace_id=f"trace_runtime_auto_repair_{normalized_worker_id}_{uuid4().hex[:16]}",
            idempotency_key="",
            method="WORKER",
            path=f"/internal/workers/runtime/{normalized_worker_id}/auto-repair",
            actor_kind="system_worker",
            actor_ref=normalized_worker_id,
        )
        requeued_stale_queued: list[dict[str, object]] = []
        redelivered_callback_overdue: list[dict[str, object]] = []
        running_stale_suggestions: list[dict[str, object]] = []

        for run in stale_queued_runs:
            try:
                repair = self.repair_run(
                    run_id=run.run_id,
                    action="requeue_stale_queued",
                    audit_context=audit_context,
                    site_id=site_id,
                )
            except RuntimeErrorBase:
                continue
            requeued_stale_queued.append(
                {
                    "run_id": str(repair.get("run_id") or ""),
                    "canonical_run_id": str(repair.get("canonical_run_id") or ""),
                    "repair_action": "requeue_stale_queued",
                }
            )

        for run in callback_overdue_runs:
            try:
                repair = self.repair_run(
                    run_id=run.run_id,
                    action="redeliver_failed_callback",
                    audit_context=audit_context,
                    site_id=site_id,
                )
            except RuntimeErrorBase:
                continue
            redelivered_callback_overdue.append(
                {
                    "run_id": str(repair.get("run_id") or ""),
                    "canonical_run_id": str(repair.get("canonical_run_id") or ""),
                    "repair_action": "redeliver_failed_callback",
                }
            )

        current_time = datetime.now(UTC)
        for run in running_stale_runs:
            if not self._is_running_run_stale(run, current_time):
                continue
            running_stale_suggestions.append(
                {
                    "run_id": run.run_id,
                    "canonical_run_id": str(run.canonical_run_id or ""),
                    "status": run.status,
                    "suggested_action": "mark_stale_running_failed",
                    "mode": "operator_only",
                    "requires_operator_reason": True,
                    "requires_operator_evidence": True,
                }
            )

        return {
            "worker_id": normalized_worker_id,
            "site_id": site_id or "",
            "requeued_stale_queued_total": len(requeued_stale_queued),
            "redelivered_callback_overdue_total": len(redelivered_callback_overdue),
            "running_stale_operator_queue_total": len(running_stale_suggestions),
            "requeued_stale_queued": requeued_stale_queued,
            "redelivered_callback_overdue": redelivered_callback_overdue,
            "running_stale_operator_queue": running_stale_suggestions,
        }

    def list_runtime_guard_events(
        self,
        *,
        site_id: str | None = None,
        scope_kind: str | None = None,
        event_code: str | None = None,
        limit: int = 20,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            events = repository.list_runtime_guard_events(
                site_id=site_id,
                scope_kind=scope_kind,
                event_code=event_code,
                limit=limit,
            )
        return {
            "filters": {
                "site_id": site_id or "",
                "scope_kind": scope_kind or "",
                "event_code": event_code or "",
                "limit": limit,
            },
            "items": [self._serialize_runtime_guard_event(event) for event in events],
        }

    def get_abuse_guard_diagnostics(
        self,
        *,
        window_seconds: int,
        cooldown_window_seconds: int,
        limit_per_scope: int,
        public_post_site_limit: int,
        public_post_key_limit: int,
        public_post_ip_limit: int,
        public_guard_site_cooldown_limit: int,
        public_guard_key_cooldown_limit: int,
        public_guard_ip_cooldown_limit: int,
        internal_post_token_limit: int,
        internal_post_ip_limit: int,
        internal_guard_token_cooldown_limit: int,
        internal_guard_ip_cooldown_limit: int,
    ) -> dict[str, object]:
        current_time = datetime.now(UTC)
        since = current_time - timedelta(seconds=max(1, window_seconds))
        cooldown_since = current_time - timedelta(seconds=max(1, cooldown_window_seconds))
        scope_kinds = [
            REPLAY_SCOPE_PUBLIC_POST_SITE,
            REPLAY_SCOPE_PUBLIC_POST_KEY,
            REPLAY_SCOPE_PUBLIC_POST_IP,
            REPLAY_SCOPE_INTERNAL_POST,
            REPLAY_SCOPE_INTERNAL_POST_IP,
        ]
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            grouped = repository.summarize_replay_receipts(
                scope_kinds=scope_kinds,
                since=since,
                limit_per_scope=limit_per_scope,
            )
            cooldown_grouped = repository.summarize_runtime_guard_events(
                scope_kinds=scope_kinds,
                since=cooldown_since,
                limit_per_scope=limit_per_scope,
            )
            event_codes = repository.summarize_runtime_guard_event_codes(
                since=cooldown_since,
                limit=limit_per_scope,
            )
            cooldown_code_breakdown = (
                repository.summarize_runtime_guard_event_code_breakdown_by_scope(
                    scope_kinds=scope_kinds,
                    since=cooldown_since,
                    limit_per_scope=3,
                )
            )
        scope_specs = {
            REPLAY_SCOPE_PUBLIC_POST_SITE: {
                "request_limit": public_post_site_limit,
                "cooldown_limit": public_guard_site_cooldown_limit,
            },
            REPLAY_SCOPE_PUBLIC_POST_KEY: {
                "request_limit": public_post_key_limit,
                "cooldown_limit": public_guard_key_cooldown_limit,
            },
            REPLAY_SCOPE_PUBLIC_POST_IP: {
                "request_limit": public_post_ip_limit,
                "cooldown_limit": public_guard_ip_cooldown_limit,
            },
            REPLAY_SCOPE_INTERNAL_POST: {
                "request_limit": internal_post_token_limit,
                "cooldown_limit": internal_guard_token_cooldown_limit,
            },
            REPLAY_SCOPE_INTERNAL_POST_IP: {
                "request_limit": internal_post_ip_limit,
                "cooldown_limit": internal_guard_ip_cooldown_limit,
            },
        }
        scopes: dict[str, dict[str, object]] = {}
        watchlist: list[dict[str, object]] = []
        for scope_kind in scope_kinds:
            scope_spec = scope_specs[scope_kind]
            request_limit = max(0, self._coerce_int(scope_spec.get("request_limit"), default=0))
            cooldown_limit = max(0, self._coerce_int(scope_spec.get("cooldown_limit"), default=0))
            request_items = [
                self._decorate_abuse_guard_item(
                    scope_kind=scope_kind,
                    item=item,
                    observed_count=max(0, self._coerce_int(item.get("request_count"), default=0)),
                    limit=request_limit,
                    signal_kind="request_burst",
                    near_limit_reason="request_burst_near_limit",
                    exceeded_reason="request_burst_limit_exceeded",
                )
                for item in grouped.get(scope_kind, [])
            ]
            cooldown_items = []
            for item in cooldown_grouped.get(scope_kind, []):
                scope_id = str(item.get("scope_id") or "")
                breakdown = cooldown_code_breakdown.get((scope_kind, scope_id), [])
                cooldown_items.append(
                    self._decorate_abuse_guard_item(
                        scope_kind=scope_kind,
                        item=item,
                        observed_count=max(0, self._coerce_int(item.get("event_count"), default=0)),
                        limit=cooldown_limit,
                        signal_kind="reject_storm",
                        near_limit_reason="reject_storm_near_limit",
                        exceeded_reason="reject_storm_limit_exceeded",
                        event_code_breakdown=breakdown,
                    )
                )

            scopes[scope_kind] = {
                "max_requests_per_window": request_limit,
                "items": request_items,
                "request_pressure": self._summarize_abuse_guard_pressure(request_items),
                "max_reject_events_per_cooldown_window": cooldown_limit,
                "cooldown_items": cooldown_items,
                "cooldown_pressure": self._summarize_abuse_guard_pressure(cooldown_items),
            }
            watchlist.extend(
                item for item in (*request_items, *cooldown_items) if item["severity"] != "healthy"
            )

        sorted_watchlist = sorted(
            watchlist,
            key=lambda item: (
                0 if item.get("severity") == "critical" else 1,
                -(self._coerce_float(item.get("limit_ratio")) or 0.0),
                -self._coerce_int(item.get("observed_count"), default=0),
                str(item.get("scope_kind") or ""),
                str(item.get("scope_id") or ""),
            ),
        )
        return {
            "generated_at": self.run_projector.serialize_timestamp(current_time),
            "window_seconds": window_seconds,
            "cooldown_window_seconds": cooldown_window_seconds,
            "limit_per_scope": limit_per_scope,
            "guard_event_codes": event_codes,
            "watchlist_summary": {
                "highest_severity": (
                    "critical"
                    if any(item["severity"] == "critical" for item in sorted_watchlist)
                    else "attention"
                    if sorted_watchlist
                    else "healthy"
                ),
                "attention_count": sum(
                    1 for item in sorted_watchlist if item["severity"] == "attention"
                ),
                "critical_count": sum(
                    1 for item in sorted_watchlist if item["severity"] == "critical"
                ),
                "request_burst_count": sum(
                    1 for item in sorted_watchlist if item["signal_kind"] == "request_burst"
                ),
                "reject_storm_count": sum(
                    1 for item in sorted_watchlist if item["signal_kind"] == "reject_storm"
                ),
            },
            "watchlist": sorted_watchlist,
            "scopes": scopes,
        }

    def _augment_runtime_diagnostics_summary(
        self,
        summary: dict[str, object],
        current_time: datetime,
    ) -> dict[str, object]:
        queue = self._dict_or_empty(summary.get("queue"))
        queued_oldest_age_seconds = self._calculate_age_seconds(
            current_time,
            queue.get("queued_oldest_requested_at"),
        )
        running_oldest_age_seconds = self._calculate_age_seconds(
            current_time,
            queue.get("running_oldest_processing_started_at"),
        )
        queue["queued_oldest_age_seconds"] = queued_oldest_age_seconds
        queue["running_oldest_age_seconds"] = running_oldest_age_seconds
        queue["pressure_thresholds"] = {
            "queued_stale_after_seconds": RUNTIME_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS,
            "running_stale_after_seconds": RUNTIME_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS,
        }
        queue["pressure_state"], queue["pressure_reasons"] = self._classify_runtime_pressure(
            (
                (
                    "queue.queued_stale",
                    queued_oldest_age_seconds is not None
                    and queued_oldest_age_seconds >= RUNTIME_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS,
                    queued_oldest_age_seconds is not None
                    and queued_oldest_age_seconds
                    >= (RUNTIME_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS * 3),
                ),
                (
                    "queue.running_stale",
                    running_oldest_age_seconds is not None
                    and running_oldest_age_seconds
                    >= RUNTIME_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS,
                    running_oldest_age_seconds is not None
                    and running_oldest_age_seconds
                    >= (RUNTIME_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS * 3),
                ),
            )
        )

        cancel = self._dict_or_empty(summary.get("cancel"))
        oldest_request_age_seconds = self._calculate_age_seconds(
            current_time,
            cancel.get("oldest_requested_at"),
        )
        cancel["oldest_request_age_seconds"] = oldest_request_age_seconds
        cancel["pressure_thresholds"] = {
            "cancel_stuck_after_seconds": RUNTIME_DIAGNOSTIC_CANCEL_STUCK_AFTER_SECONDS,
        }
        cancel["pressure_state"], cancel["pressure_reasons"] = self._classify_runtime_pressure(
            (
                (
                    "cancel.request_stuck",
                    oldest_request_age_seconds is not None
                    and oldest_request_age_seconds >= RUNTIME_DIAGNOSTIC_CANCEL_STUCK_AFTER_SECONDS,
                    oldest_request_age_seconds is not None
                    and oldest_request_age_seconds
                    >= (RUNTIME_DIAGNOSTIC_CANCEL_STUCK_AFTER_SECONDS * 3),
                ),
            )
        )

        callback = self._dict_or_empty(summary.get("callback"))
        pending = max(0, self._coerce_int(callback.get("pending"), default=0))
        due_now = max(0, self._coerce_int(callback.get("due_now"), default=0))
        failed = max(0, self._coerce_int(callback.get("failed"), default=0))
        dispatching = max(0, self._coerce_int(callback.get("dispatching"), default=0))
        recoverable_dispatching = max(
            0, self._coerce_int(callback.get("recoverable_dispatching"), default=0)
        )
        oldest_due_age_seconds = self._calculate_age_seconds(
            current_time,
            callback.get("oldest_due_at"),
        )
        dispatching_oldest_age_seconds = self._calculate_age_seconds(
            current_time,
            callback.get("dispatching_oldest_last_attempt_at"),
        )
        callback["pending_not_due"] = max(0, pending - due_now)
        callback["oldest_due_age_seconds"] = oldest_due_age_seconds
        callback["dispatching_oldest_age_seconds"] = dispatching_oldest_age_seconds
        callback["recovery_action"] = "requeue_pending_after_stale_dispatch_lease"
        callback["pressure_thresholds"] = {
            "callback_overdue_after_seconds": RUNTIME_DIAGNOSTIC_CALLBACK_OVERDUE_AFTER_SECONDS,
            "dispatching_stale_after_seconds": (
                RUNTIME_DIAGNOSTIC_CALLBACK_DISPATCHING_STALE_AFTER_SECONDS
            ),
        }
        callback["pressure_state"], callback["pressure_reasons"] = self._classify_runtime_pressure(
            (
                ("callback.failed", failed > 0, failed >= 3),
                (
                    "callback.overdue",
                    oldest_due_age_seconds is not None
                    and oldest_due_age_seconds >= RUNTIME_DIAGNOSTIC_CALLBACK_OVERDUE_AFTER_SECONDS,
                    oldest_due_age_seconds is not None
                    and oldest_due_age_seconds
                    >= (RUNTIME_DIAGNOSTIC_CALLBACK_OVERDUE_AFTER_SECONDS * 3),
                ),
                (
                    "callback.due_now",
                    due_now > 0
                    and (
                        oldest_due_age_seconds is None
                        or oldest_due_age_seconds
                        < RUNTIME_DIAGNOSTIC_CALLBACK_OVERDUE_AFTER_SECONDS
                    ),
                    False,
                ),
                (
                    "callback.dispatching_stale",
                    recoverable_dispatching > 0,
                    recoverable_dispatching >= 3
                    or (
                        dispatching_oldest_age_seconds is not None
                        and dispatching_oldest_age_seconds
                        >= (RUNTIME_DIAGNOSTIC_CALLBACK_DISPATCHING_STALE_AFTER_SECONDS * 3)
                    ),
                ),
                (
                    "callback.dispatching",
                    dispatching > 0
                    and (
                        dispatching_oldest_age_seconds is None
                        or dispatching_oldest_age_seconds
                        < RUNTIME_DIAGNOSTIC_CALLBACK_DISPATCHING_STALE_AFTER_SECONDS
                    ),
                    False,
                ),
            )
        )

        failures = self._dict_or_empty(summary.get("failures"))
        failed_recent = max(0, self._coerce_int(failures.get("failed_recent"), default=0))
        provider_error_calls_recent = max(
            0,
            self._coerce_int(failures.get("provider_error_calls_recent"), default=0),
        )
        failures["pressure_state"], failures["pressure_reasons"] = self._classify_runtime_pressure(
            (
                ("failures.failed_recent", failed_recent > 0, failed_recent >= 3),
                (
                    "failures.provider_error_calls_recent",
                    provider_error_calls_recent > 0,
                    provider_error_calls_recent >= 3,
                ),
            )
        )
        failures["dominant_error"] = self._build_dominant_runtime_error(failures)
        operator_guidance = self._build_runtime_operator_guidance(
            queue=queue,
            cancel=cancel,
            callback=callback,
            failures=failures,
            retention=self._dict_or_empty(summary.get("retention")),
        )

        return {
            **summary,
            "queue": queue,
            "cancel": cancel,
            "callback": callback,
            "failures": failures,
            "operator_guidance": operator_guidance,
        }

    def _build_dominant_runtime_error(
        self,
        failures: dict[str, object],
    ) -> dict[str, object]:
        top_error_codes = failures.get("top_error_codes")
        top_provider_errors = failures.get("top_provider_errors")
        candidates: list[dict[str, object]] = []
        if isinstance(top_error_codes, list):
            candidates.extend(item for item in top_error_codes if isinstance(item, dict))
        if isinstance(top_provider_errors, list):
            candidates.extend(item for item in top_provider_errors if isinstance(item, dict))
        if not candidates:
            return {
                "error_code": "",
                "error_stage": "",
                "count": 0,
                "provider_id": "",
                "last_seen_at": "",
            }

        def sort_key(item: dict[str, object]) -> tuple[int, str]:
            return (
                self._coerce_int(item.get("count"), default=0),
                str(item.get("last_seen_at") or ""),
            )

        dominant = sorted(candidates, key=sort_key, reverse=True)[0]
        error_code = str(dominant.get("error_code") or "")
        taxonomy = get_error_taxonomy(error_code)
        return {
            "error_code": error_code,
            "error_stage": taxonomy.error_stage,
            "count": self._coerce_int(dominant.get("count"), default=0),
            "provider_id": str(dominant.get("provider_id") or ""),
            "last_seen_at": str(dominant.get("last_seen_at") or ""),
        }

    def _build_runtime_operator_guidance(
        self,
        *,
        queue: dict[str, object],
        cancel: dict[str, object],
        callback: dict[str, object],
        failures: dict[str, object],
        retention: dict[str, object],
    ) -> dict[str, object]:
        candidates: list[dict[str, object]] = []

        def add_candidate(
            *,
            reason: str,
            state: str,
            evidence_path: str,
            action: str,
            mode: str,
            priority: int,
        ) -> None:
            candidates.append(
                {
                    "reason": reason,
                    "state": state,
                    "evidence_path": evidence_path,
                    "suggested_action": action,
                    "mode": mode,
                    "priority": priority,
                }
            )

        if callback.get("pressure_state") in {"attention", "critical"}:
            add_candidate(
                reason="callback_delivery",
                state=str(callback.get("pressure_state") or "attention"),
                evidence_path="callback.pressure_reasons",
                action="inspect_callback_delivery_and_retry_buffer",
                mode="operator_review",
                priority=10,
            )
        if queue.get("pressure_state") in {"attention", "critical"}:
            add_candidate(
                reason="runtime_queue",
                state=str(queue.get("pressure_state") or "attention"),
                evidence_path="queue.pressure_reasons",
                action="inspect_runtime_worker_and_backlog_scope",
                mode="operator_review",
                priority=20,
            )
        if cancel.get("pressure_state") in {"attention", "critical"}:
            add_candidate(
                reason="cancel_requests",
                state=str(cancel.get("pressure_state") or "attention"),
                evidence_path="cancel.pressure_reasons",
                action="inspect_stuck_cancel_requests",
                mode="operator_review",
                priority=30,
            )
        if failures.get("pressure_state") in {"attention", "critical"}:
            dominant = failures.get("dominant_error")
            dominant_error = dominant if isinstance(dominant, dict) else {}
            error_stage = str(dominant_error.get("error_stage") or "runtime")
            action_by_stage = {
                "provider": "inspect_provider_credentials_quota_and_health",
                "auth": "inspect_site_key_signature_and_request_headers",
                "routing": "inspect_profile_catalog_and_routing_candidates",
                "runtime": "inspect_runtime_execution_error_and_worker_logs",
            }
            add_candidate(
                reason=f"{error_stage}_failures",
                state=str(failures.get("pressure_state") or "attention"),
                evidence_path="failures.dominant_error",
                action=action_by_stage.get(error_stage, "inspect_runtime_failure_detail"),
                mode="operator_review",
                priority=40,
            )
        if self._coerce_int(retention.get("due_purge"), default=0) > 0:
            add_candidate(
                reason="retention_due",
                state="attention",
                evidence_path="retention.due_purge",
                action="run_retention_cleanup_or_check_ops_cadence",
                mode="worker_auto",
                priority=50,
            )

        candidates.sort(key=lambda item: self._coerce_int(item.get("priority"), default=0))
        primary = (
            candidates[0]
            if candidates
            else {
                "reason": "none",
                "state": "healthy",
                "evidence_path": "",
                "suggested_action": "continue_monitoring",
                "mode": "none",
                "priority": 100,
            }
        )
        return {
            "state": str(primary["state"]),
            "primary_reason": str(primary["reason"]),
            "primary_evidence_path": str(primary["evidence_path"]),
            "suggested_actions": [
                {
                    "action": str(item["suggested_action"]),
                    "reason": str(item["reason"]),
                    "mode": str(item["mode"]),
                    "evidence_path": str(item["evidence_path"]),
                }
                for item in candidates[:5]
            ],
        }

    def cancel_run(self, run_id: str, *, site_id: str | None = None) -> dict[str, object]:
        return self.run_lifecycle_service.cancel_run(run_id, site_id=site_id)

    def dispatch_pending_callbacks(
        self,
        *,
        max_callbacks: int = 1,
    ) -> list[dict[str, object]]:
        return self.callback_delivery_service.dispatch_pending_callbacks(
            max_callbacks=max_callbacks
        )

    def _execute_existing_run(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
    ) -> None:
        if self._is_cloud_batch_runtime_run(run):
            self._execute_cloud_batch_runtime_run(run, repository=repository)
            return
        if run.execution_kind == "media_derivative":
            self._execute_media_derivative_run(run, repository=repository)
            return
        if self._is_media_batch_plan_run(run):
            self._execute_media_batch_plan_run(run, repository=repository)
            return
        if self._is_image_context_evidence_run(run):
            self._execute_image_context_evidence_run(run, repository=repository)
            return
        if self._is_image_source_run(run):
            self._execute_image_source_run(run, repository=repository)
            return
        if self._is_site_knowledge_run(run):
            self._execute_site_knowledge_run(run, repository=repository)
            return
        if self._is_web_search_run(run):
            self._execute_web_search_run(run, repository=repository)
            return

        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
        candidates = self._deserialize_routing_candidates(policy)
        if not candidates:
            resolution = self.routing_service.resolve(
                profile_id=run.profile_id,
                execution_kind=run.execution_kind,
            )
            policy = self._apply_routing_snapshot(policy, resolution)
            run.policy_json = policy
            candidates = resolution.candidates

        try:
            input_payload = self._get_execution_input_payload(run)
        except RuntimeError:
            if not self._is_wordpress_ai_connector_run(run):
                raise
            self.run_lifecycle_service.fail_run(
                repository,
                run,
                error_code="connector_runtime.execution_input_invalid",
                error_message="connector runtime execution input could not be decoded",
            )
            return
        connector_envelope: dict[str, Any] | None = None
        if self._is_wordpress_ai_connector_run(run):
            try:
                connector_envelope = self.contract_validator.normalize_connector_runtime_envelope(
                    ability_name=str(run.ability_name or ""),
                    contract_version=str(run.contract_version or ""),
                    channel=str(run.channel or ""),
                    input_payload=input_payload,
                )
                site = self._require_active_site(repository, run.site_id)
                self.contract_validator.validate_connector_runtime_site_binding(
                    connector_envelope,
                    site=site,
                )
                input_payload = self._prepare_wordpress_operation_execution_input(
                    run,
                    repository=repository,
                    connector_envelope=connector_envelope,
                )
            except RuntimeErrorBase as error:
                self.run_lifecycle_service.fail_run(
                    repository,
                    run,
                    error_code=error.error_code,
                    error_message=error.message,
                )
                return

        self._execute_candidate_chain(
            run,
            repository=repository,
            candidates=candidates,
            input_payload=input_payload,
            connector_envelope=connector_envelope,
        )

    def _execute_candidate_chain(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        candidates: list[RoutingCandidate],
        input_payload: dict[str, Any],
        connector_envelope: dict[str, Any] | None = None,
    ) -> None:
        self.provider_execution_service.execute_candidate_chain(
            repository=repository,
            run=run,
            candidates=candidates,
            input_payload=input_payload,
            finalization_context=connector_envelope,
        )

    def _preprocess_provider_input(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any],
        policy: dict[str, object],
    ) -> dict[str, Any]:
        return self._apply_automatic_web_search(
            run,
            repository=repository,
            input_payload=input_payload,
            policy=policy,
        )

    def _prepare_provider_output(
        self,
        run: RunRecord,
        *,
        input_payload: dict[str, Any],
        provider_output: dict[str, Any],
    ) -> ProviderOutputDecision:
        if not self._is_wordpress_ai_connector_run(run):
            return ProviderOutputDecision(accepted=True, output=provider_output)
        normalized_output = self.wordpress_operation_runtime.normalize_provider_output(
            provider_output,
            input_payload=input_payload,
        )
        if self.wordpress_operation_runtime.is_empty_text_output(
            input_payload=input_payload,
            provider_output=normalized_output,
        ):
            return ProviderOutputDecision(
                accepted=False,
                output=normalized_output,
                error_code="provider.output_quality_rejected",
                error_message="provider returned no usable WordPress AI connector text",
            )
        return ProviderOutputDecision(accepted=True, output=normalized_output)

    def _finalize_provider_output(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any],
        provider_output: dict[str, Any],
        media_candidates: tuple[ProviderMediaCandidate, ...],
        policy: dict[str, object],
        finalization_context: object | None,
    ) -> dict[str, Any]:
        if self._is_image_generation_run(run):
            try:
                provider_output = self._materialize_image_generation_output(
                    run,
                    repository=repository,
                    provider_output=provider_output,
                    media_candidates=media_candidates,
                )
            except ImageGenerationArtifactMaterializationError as error:
                raise ProviderOutputFinalizationError(
                    error.error_code,
                    error.message,
                ) from error
        if self._is_audio_generation_run(run):
            try:
                provider_output = self._materialize_audio_generation_output(
                    run,
                    repository=repository,
                    provider_output=provider_output,
                )
            except AudioArtifactMaterializationError as error:
                raise ProviderOutputFinalizationError(
                    error.error_code,
                    error.message,
                ) from error

        automatic_web_search = policy.get("automatic_web_search")
        connector_envelope = (
            finalization_context if isinstance(finalization_context, dict) else None
        )
        normalized_result = self.result_normalization_service.normalize(
            RuntimeResultNormalizationCommand(
                site_id=run.site_id,
                provider_output=provider_output,
                storage_mode=self._get_storage_mode(policy),
                ability_family=run.ability_family or "text",
                ability_name=run.ability_name or "",
                input_payload=input_payload,
                connector_envelope=connector_envelope,
                automatic_web_search=(
                    automatic_web_search if isinstance(automatic_web_search, dict) else None
                ),
            )
        )
        if normalized_result.transient_result is not None:
            set_transient_runtime_result(run, normalized_result.transient_result)
        return normalized_result.durable_result

    def _apply_automatic_web_search(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any],
        policy: dict[str, object],
    ) -> dict[str, Any]:
        plan = build_automatic_web_search_plan(
            input_payload,
            ability_name=run.ability_name or "",
            workflow_id=run.workflow_id or "",
            channel=run.channel or "",
        )
        if plan is None:
            return input_payload

        if plan.is_dry_run:
            self._record_automatic_web_search_report(
                run,
                policy=policy,
                report=plan.to_report(status="would_search"),
            )
            return input_payload

        try:
            search_result = WebSearchService(self.settings).execute(
                site_id=run.site_id,
                ability_name=WEB_SEARCH_ABILITY,
                contract_version=WEB_SEARCH_CONTRACT,
                input_payload=plan.to_web_search_input(),
                run_id=f"{run.run_id}:automatic-web-search",
            )
        except WebSearchProviderError as error:
            if error.usage is not None:
                self._record_automatic_web_search_provider_call(
                    run,
                    repository=repository,
                    usage=error.usage,
                )
            report = plan.to_report(
                status="failed",
                error_code=error.error_code,
                message=error.message,
            )
            if error.usage is not None:
                report["usage_summary"] = {
                    "provider_id": str(getattr(error.usage, "provider_id", "") or ""),
                    "model_id": str(getattr(error.usage, "model_id", "") or ""),
                    "instance_id": str(getattr(error.usage, "instance_id", "") or ""),
                    "region": str(getattr(error.usage, "region", "") or ""),
                    "latency_ms": max(0, int(getattr(error.usage, "latency_ms", 0) or 0)),
                    "cost": max(0.0, float(getattr(error.usage, "cost", 0.0) or 0.0)),
                    "error_code": str(getattr(error.usage, "error_code", "") or ""),
                }
            self._record_automatic_web_search_report(run, policy=policy, report=report)
            if plan.is_required:
                self.run_lifecycle_service.fail_run(
                    repository,
                    run,
                    error_code=error.error_code,
                    error_message=error.message,
                    provider_id="web_search",
                    model_id="web-search-managed",
                    instance_id="cloud-runtime",
                    fallback_used=False,
                )
            return input_payload
        except WebSearchContractViolation as error:
            report = plan.to_report(
                status="failed",
                error_code=error.error_code,
                message=error.message,
            )
            self._record_automatic_web_search_report(run, policy=policy, report=report)
            if plan.is_required:
                self.run_lifecycle_service.fail_run(
                    repository,
                    run,
                    error_code=error.error_code,
                    error_message=error.message,
                    provider_id="web_search",
                    model_id="web-search-managed",
                    instance_id="cloud-runtime",
                    fallback_used=False,
                )
            return input_payload

        self._record_automatic_web_search_provider_call(
            run,
            repository=repository,
            usage=search_result.usage,
        )
        report = build_automatic_web_search_success_report(
            plan,
            search_result.result_json,
            usage=search_result.usage,
        )
        self._record_automatic_web_search_report(run, policy=policy, report=report)
        return attach_automatic_web_search_evidence(
            input_payload,
            result_json=search_result.result_json,
            report=report,
        )

    def _record_automatic_web_search_provider_call(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        usage: Any,
    ) -> None:
        self.provider_execution_service.record_provider_call(
            repository=repository,
            run=run,
            command=ProviderCallEvidenceCommand(
                provider_id=usage.provider_id,
                model_id=usage.model_id,
                instance_id=usage.instance_id,
                region=usage.region,
                latency_ms=usage.latency_ms,
                tokens_in=0,
                tokens_out=0,
                cost=usage.cost,
                retry_count=0,
                fallback_used=False,
                error_code=usage.error_code,
            ),
        )

    def _record_automatic_web_search_report(
        self,
        run: RunRecord,
        *,
        policy: dict[str, object],
        report: dict[str, Any],
    ) -> None:
        updated_policy = dict(policy)
        updated_policy["automatic_web_search"] = report
        run.policy_json = updated_policy
        flag_modified(run, "policy_json")
        policy.clear()
        policy.update(updated_policy)

    def _execute_site_knowledge_run(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any] | None = None,
    ) -> None:
        if self.run_lifecycle_service.cancel_if_requested(
            repository=repository,
            run=run,
        ):
            return

        payload = (
            input_payload
            if isinstance(input_payload, dict)
            else self._get_execution_input_payload(run)
        )
        execution_started_at = datetime.now(UTC)

        def record_progress(progress: dict[str, Any]) -> None:
            run.result_json = {
                "artifact_type": "site_knowledge_sync_progress",
                "composition_role": "site_knowledge_sync_progress",
                "status": str(progress.get("status") or "running"),
                "run_id": run.run_id,
                "progress": progress,
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            }
            flag_modified(run, "result_json")
            repository.session.flush()
            repository.session.commit()

        def record_embedding_usage(
            provider_id: str,
            provider_request: ProviderExecutionRequest,
            provider_result: ProviderExecutionResult | None,
            provider_error: ProviderExecutionError | None,
        ) -> None:
            self._record_site_knowledge_embedding_provider_call(
                run,
                repository=repository,
                provider_id=provider_id,
                provider_request=provider_request,
                provider_result=provider_result,
                provider_error=provider_error,
            )

        try:
            result_json = SiteKnowledgeService(
                repository.session,
                settings=self.settings,
                providers=self.providers,
                progress_callback=record_progress
                if run.ability_name == SITE_KNOWLEDGE_SYNC_ABILITY
                else None,
                embedding_usage_callback=record_embedding_usage,
            ).execute(
                site_id=run.site_id,
                ability_name=run.ability_name,
                contract_version=run.contract_version or "",
                input_payload=payload,
                run_id=run.run_id,
            )
        except (SiteKnowledgeContractViolation, SiteKnowledgeBackendError) as error:
            self.run_lifecycle_service.fail_run(
                repository,
                run,
                error_code=error.error_code,
                error_message=error.message,
                provider_id="site_knowledge",
                model_id="site-knowledge-managed",
                instance_id="cloud-runtime",
                fallback_used=False,
            )
            record_site_knowledge_failure_metric(
                session=repository.session,
                run=run,
                input_payload=payload,
                error_code=error.error_code,
                execution_started_at=execution_started_at,
                settings=self.settings,
            )
            return

        self.run_lifecycle_service.succeed_run(
            repository,
            run,
            result_json=result_json,
            provider_id="site_knowledge",
            model_id="site-knowledge-managed",
            instance_id="cloud-runtime",
            fallback_used=False,
        )
        record_site_knowledge_run_metric(
            session=repository.session,
            run=run,
            input_payload=payload,
            result_json=result_json,
            execution_started_at=execution_started_at,
            settings=self.settings,
        )

    def _record_site_knowledge_embedding_provider_call(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        provider_id: str,
        provider_request: ProviderExecutionRequest,
        provider_result: ProviderExecutionResult | None = None,
        provider_error: ProviderExecutionError | None = None,
    ) -> None:
        self.provider_execution_service.record_provider_call(
            repository=repository,
            run=run,
            command=ProviderCallEvidenceCommand(
                provider_id=provider_id,
                model_id=provider_request.model_id,
                instance_id=provider_request.instance_id,
                region="unspecified",
                latency_ms=(provider_result.latency_ms if provider_result is not None else 0),
                tokens_in=(
                    provider_result.tokens_in
                    if provider_result is not None
                    else max(0, int(getattr(provider_error, "tokens_in", 0) or 0))
                ),
                tokens_out=(
                    provider_result.tokens_out
                    if provider_result is not None
                    else max(0, int(getattr(provider_error, "tokens_out", 0) or 0))
                ),
                cost=(
                    provider_result.cost
                    if provider_result is not None
                    else max(0.0, float(getattr(provider_error, "cost", 0.0) or 0.0))
                ),
                retry_count=provider_request.retry_count,
                fallback_used=False,
                error_code=provider_error.error_code if provider_error is not None else None,
            ),
        )

    def _execute_web_search_request(
        self,
        request: RuntimeRequest,
    ) -> RuntimeExecutionResponse:
        self.contract_validator.validate_web_search_contract(request)
        trace_id = request.trace_id or uuid4().hex
        run_id = f"run_{uuid4().hex}"
        merged_policy = self._build_web_search_policy(request)
        request_fingerprint = self.run_lifecycle_service.build_request_fingerprint(
            request,
            merged_policy,
        )

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            self._require_active_site(repository, request.site_id)

            existing = self.run_lifecycle_service.get_idempotent_replay(
                repository=repository,
                site_id=request.site_id,
                idempotency_key=request.idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            if existing is not None:
                session.commit()
                return self._build_execution_response(
                    existing,
                    repository=repository,
                    idempotent_replay=True,
                )

            commercial_decision = self.commercial_service.authorize_runtime_request(
                session=session,
                site_id=request.site_id,
                ability_family=request.ability_family,
                channel=request.channel,
                execution_kind=request.execution_kind,
                execution_tier=request.execution_tier,
                data_classification=request.data_classification,
                trace_id=trace_id,
                idempotency_key=request.idempotency_key,
                request_kind="execute",
                run_id=run_id,
                estimated_ai_credits=self._estimate_web_search_ai_credits(request),
            )
            self._enforce_batch_limits(
                request=request,
                commercial_decision=commercial_decision,
            )
            merged_policy = self._apply_commercial_policy_overrides(
                merged_policy,
                commercial_decision=commercial_decision,
            )
            storage_mode = self._get_storage_mode(merged_policy)
            run = self.run_lifecycle_service.create_durable_run(
                repository=repository,
                command=RuntimeRunCreationCommand(
                    run_id=run_id,
                    site_id=request.site_id,
                    account_id=str(commercial_decision.get("account_id") or "") or None,
                    subscription_id=str(commercial_decision.get("subscription_id") or "") or None,
                    plan_version_id=str(commercial_decision.get("plan_version_id") or "") or None,
                    ability_name=request.ability_name,
                    ability_family=request.ability_family,
                    skill_id=request.skill_id,
                    workflow_id=request.workflow_id,
                    contract_version=request.contract_version,
                    channel=request.channel,
                    execution_kind=request.execution_kind,
                    execution_tier=request.execution_tier,
                    execution_pattern=request.execution_pattern,
                    data_classification=request.data_classification,
                    profile_id=request.profile_id,
                    canonical_run_id=request.canonical_run_id or None,
                    status="running",
                    idempotency_key=request.idempotency_key,
                    request_fingerprint=request_fingerprint,
                    trace_id=trace_id,
                    input_json=self._prepare_input_for_storage(
                        request.input_payload,
                        storage_mode=storage_mode,
                    ),
                    execution_input_ciphertext=None,
                    policy_json=merged_policy,
                    selected_provider_id="web_search",
                    selected_model_id="web-search-managed",
                    selected_instance_id="cloud-runtime",
                ),
            )
            self.commercial_service.record_run_acceptance(session=session, run=run)
            self._execute_web_search_run(
                run,
                repository=repository,
                input_payload=request.input_payload,
            )
            session.commit()
            return self._build_execution_response(
                run,
                repository=repository,
                idempotent_replay=False,
            )

    def _execute_web_search_run(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any] | None = None,
    ) -> None:
        if self.run_lifecycle_service.cancel_if_requested(
            repository=repository,
            run=run,
        ):
            return

        payload = (
            input_payload
            if isinstance(input_payload, dict)
            else self._get_execution_input_payload(run)
        )
        try:
            execution = WebSearchService(self.settings).execute(
                site_id=run.site_id,
                ability_name=run.ability_name,
                contract_version=run.contract_version or "",
                input_payload=payload,
                run_id=run.run_id,
            )
        except WebSearchContractViolation as error:
            self.run_lifecycle_service.fail_run(
                repository,
                run,
                error_code=error.error_code,
                error_message=error.message,
                provider_id="web_search",
                model_id="web-search-managed",
                instance_id="cloud-runtime",
                fallback_used=False,
            )
            return
        except WebSearchProviderError as error:
            if error.usage is not None:
                self.provider_execution_service.record_provider_call(
                    repository=repository,
                    run=run,
                    command=ProviderCallEvidenceCommand(
                        provider_id=error.usage.provider_id,
                        model_id=error.usage.model_id,
                        instance_id=error.usage.instance_id,
                        region=error.usage.region,
                        latency_ms=error.usage.latency_ms,
                        tokens_in=0,
                        tokens_out=0,
                        cost=error.usage.cost,
                        retry_count=0,
                        fallback_used=False,
                        error_code=error.usage.error_code or error.error_code,
                    ),
                )
            self.run_lifecycle_service.fail_run(
                repository,
                run,
                error_code=error.error_code,
                error_message=error.message,
                provider_id="web_search",
                model_id="web-search-managed",
                instance_id="cloud-runtime",
                fallback_used=False,
            )
            return

        result_json = dict(execution.result_json)
        usage_context = self._build_web_search_usage_context(payload, result_json=result_json)
        result_json["usage_summary"] = self._build_web_search_usage_summary(
            run,
            usage_context=usage_context,
        )
        self.provider_execution_service.record_provider_call(
            repository=repository,
            run=run,
            command=ProviderCallEvidenceCommand(
                provider_id=execution.usage.provider_id,
                model_id=execution.usage.model_id,
                instance_id=execution.usage.instance_id,
                region=execution.usage.region,
                latency_ms=execution.usage.latency_ms,
                tokens_in=0,
                tokens_out=0,
                cost=execution.usage.cost,
                retry_count=0,
                fallback_used=False,
                error_code=execution.usage.error_code,
            ),
            usage_context=usage_context,
        )
        self.run_lifecycle_service.succeed_run(
            repository,
            run,
            result_json=result_json,
            provider_id="web_search",
            model_id="web-search-managed",
            instance_id="cloud-runtime",
            fallback_used=False,
        )

    def _estimate_web_search_ai_credits(self, request: RuntimeRequest) -> float:
        return self._estimate_runtime_request_ai_credits(
            request,
            payload_json=self._build_web_search_usage_context(request.input_payload),
        )

    def _estimate_runtime_request_ai_credits(
        self,
        request: RuntimeRequest,
        *,
        payload_json: dict[str, object] | None = None,
    ) -> float:
        return estimate_runtime_request_ai_credits(
            ability_name=request.ability_name,
            ability_family=request.ability_family,
            execution_kind=request.execution_kind,
            payload_json=payload_json if payload_json is not None else request.input_payload,
        )

    def _build_web_search_usage_context(
        self,
        input_payload: dict[str, Any],
        *,
        result_json: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        result = result_json if isinstance(result_json, dict) else {}
        source_type = str(
            input_payload.get("source_type")
            or result.get("source_type")
            or result.get("intent")
            or ""
        ).strip()
        managed_source = str(input_payload.get("managed_source") or "").strip()
        intent = str(input_payload.get("intent") or result.get("intent") or "").strip()
        provider = str(result.get("provider") or input_payload.get("provider") or "").strip()
        if not provider and (
            source_type.startswith("zhihu")
            or source_type.startswith("zhida")
            or managed_source.startswith("zhihu")
            or intent.startswith("zhihu")
            or intent.startswith("zhida")
        ):
            provider = "zhihu"
        context: dict[str, object] = {
            "provider": provider,
            "provider_mode": str(result.get("provider_mode") or provider or "").strip(),
            "requested_provider": str(
                result.get("requested_provider") or input_payload.get("provider") or ""
            ).strip(),
            "source_type": source_type,
            "managed_source": managed_source or source_type or intent,
            "intent": intent or source_type,
        }
        for key in ("cache_status", "result_count"):
            value = result.get(key)
            if value is not None and value != "":
                context[key] = value
        return context

    def _build_web_search_usage_summary(
        self,
        run: RunRecord,
        *,
        usage_context: dict[str, object],
    ) -> dict[str, object]:
        component = classify_provider_credit_component(
            execution_kind=run.execution_kind,
            ability_family=run.ability_family,
            payload_json=usage_context,
        )
        provider_credits = float(self._coerce_float(component.get("rate")) or 0.0)
        return {
            "rate_version": AI_CREDIT_RATE_VERSION,
            "quota_owner": "cloud_runtime_entitlement",
            "meter_key": "provider_calls",
            "source_type": str(component.get("source_type") or ""),
            "unit": str(component.get("unit") or "call"),
            "provider_call_credits": provider_credits,
            "run_acceptance_credits": 1.0,
            "estimated_total_ai_credits": round(1.0 + max(0.0, provider_credits), 6),
            "provider": str(usage_context.get("provider") or ""),
            "managed_source": str(usage_context.get("managed_source") or ""),
            "intent": str(usage_context.get("intent") or ""),
        }

    def _execute_image_source_request(
        self,
        request: RuntimeRequest,
    ) -> RuntimeExecutionResponse:
        self.contract_validator.validate_image_source_contract(request)
        trace_id = request.trace_id or uuid4().hex
        run_id = f"run_{uuid4().hex}"
        merged_policy = self._build_image_source_policy(request)
        request_fingerprint = self.run_lifecycle_service.build_request_fingerprint(
            request,
            merged_policy,
        )

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            self._require_active_site(repository, request.site_id)

            existing = self.run_lifecycle_service.get_idempotent_replay(
                repository=repository,
                site_id=request.site_id,
                idempotency_key=request.idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            if existing is not None:
                session.commit()
                return self._build_execution_response(
                    existing,
                    repository=repository,
                    idempotent_replay=True,
                )

            commercial_decision = self.commercial_service.authorize_runtime_request(
                session=session,
                site_id=request.site_id,
                ability_family=request.ability_family,
                channel=request.channel,
                execution_kind=request.execution_kind,
                execution_tier=request.execution_tier,
                data_classification=request.data_classification,
                trace_id=trace_id,
                idempotency_key=request.idempotency_key,
                request_kind="execute",
                run_id=run_id,
                estimated_ai_credits=self._estimate_runtime_request_ai_credits(request),
            )
            self._enforce_batch_limits(
                request=request,
                commercial_decision=commercial_decision,
            )
            merged_policy = self._apply_commercial_policy_overrides(
                merged_policy,
                commercial_decision=commercial_decision,
            )
            storage_mode = self._get_storage_mode(merged_policy)
            run = self.run_lifecycle_service.create_durable_run(
                repository=repository,
                command=RuntimeRunCreationCommand(
                    run_id=run_id,
                    site_id=request.site_id,
                    account_id=str(commercial_decision.get("account_id") or "") or None,
                    subscription_id=str(commercial_decision.get("subscription_id") or "") or None,
                    plan_version_id=str(commercial_decision.get("plan_version_id") or "") or None,
                    ability_name=request.ability_name,
                    ability_family=request.ability_family,
                    skill_id=request.skill_id,
                    workflow_id=request.workflow_id,
                    contract_version=request.contract_version,
                    channel=request.channel,
                    execution_kind=request.execution_kind,
                    execution_tier=request.execution_tier,
                    execution_pattern=request.execution_pattern,
                    data_classification=request.data_classification,
                    profile_id=request.profile_id or IMAGE_SOURCE_PROFILE_ID,
                    canonical_run_id=request.canonical_run_id or None,
                    status="running",
                    idempotency_key=request.idempotency_key,
                    request_fingerprint=request_fingerprint,
                    trace_id=trace_id,
                    input_json=self._prepare_input_for_storage(
                        request.input_payload,
                        storage_mode=storage_mode,
                    ),
                    execution_input_ciphertext=None,
                    policy_json=merged_policy,
                    selected_provider_id="image_source",
                    selected_model_id="image-source-managed",
                    selected_instance_id="cloud-runtime",
                ),
            )
            self.commercial_service.record_run_acceptance(session=session, run=run)
            self._execute_image_source_run(
                run,
                repository=repository,
                input_payload=request.input_payload,
            )
            session.commit()
            return self._build_execution_response(
                run,
                repository=repository,
                idempotent_replay=False,
            )

    def _execute_media_batch_plan_request(
        self,
        request: RuntimeRequest,
    ) -> RuntimeExecutionResponse:
        self.contract_validator.validate_media_batch_plan_contract(request)
        trace_id = request.trace_id or uuid4().hex
        run_id = f"run_{uuid4().hex}"
        merged_policy = self._build_media_batch_plan_policy(request)
        request_fingerprint = self.run_lifecycle_service.build_request_fingerprint(
            request,
            merged_policy,
        )

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            self._require_active_site(repository, request.site_id)

            existing = self.run_lifecycle_service.get_idempotent_replay(
                repository=repository,
                site_id=request.site_id,
                idempotency_key=request.idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            if existing is not None:
                session.commit()
                return self._build_execution_response(
                    existing,
                    repository=repository,
                    idempotent_replay=True,
                )

            commercial_decision = self.commercial_service.authorize_runtime_request(
                session=session,
                site_id=request.site_id,
                ability_family=request.ability_family,
                channel=request.channel,
                execution_kind=request.execution_kind,
                execution_tier=request.execution_tier,
                data_classification=request.data_classification,
                trace_id=trace_id,
                idempotency_key=request.idempotency_key,
                request_kind="execute",
                run_id=run_id,
                estimated_ai_credits=self._estimate_runtime_request_ai_credits(request),
            )
            self._enforce_batch_limits(
                request=request,
                commercial_decision=commercial_decision,
            )
            merged_policy = self._apply_commercial_policy_overrides(
                merged_policy,
                commercial_decision=commercial_decision,
            )
            storage_mode = self._get_storage_mode(merged_policy)
            run = self.run_lifecycle_service.create_durable_run(
                repository=repository,
                command=RuntimeRunCreationCommand(
                    run_id=run_id,
                    site_id=request.site_id,
                    account_id=str(commercial_decision.get("account_id") or "") or None,
                    subscription_id=str(commercial_decision.get("subscription_id") or "") or None,
                    plan_version_id=str(commercial_decision.get("plan_version_id") or "") or None,
                    ability_name=request.ability_name,
                    ability_family=request.ability_family,
                    skill_id=request.skill_id,
                    workflow_id=request.workflow_id,
                    contract_version=request.contract_version,
                    channel=request.channel,
                    execution_kind=request.execution_kind,
                    execution_tier=request.execution_tier,
                    execution_pattern=request.execution_pattern,
                    data_classification=request.data_classification,
                    profile_id=request.profile_id or MEDIA_BATCH_PLAN_PROFILE_ID,
                    canonical_run_id=request.canonical_run_id or None,
                    status="running",
                    idempotency_key=request.idempotency_key,
                    request_fingerprint=request_fingerprint,
                    trace_id=trace_id,
                    input_json=self._prepare_input_for_storage(
                        request.input_payload,
                        storage_mode=storage_mode,
                    ),
                    execution_input_ciphertext=None,
                    policy_json=merged_policy,
                    selected_provider_id="media_batch_plan",
                    selected_model_id="deterministic-intent-parser",
                    selected_instance_id="cloud-runtime",
                ),
            )
            self.commercial_service.record_run_acceptance(session=session, run=run)
            self._execute_media_batch_plan_run(
                run,
                repository=repository,
                input_payload=request.input_payload,
            )
            session.commit()
            return self._build_execution_response(
                run,
                repository=repository,
                idempotent_replay=False,
            )

    def _execute_site_ops_analysis_request(
        self,
        request: RuntimeRequest,
    ) -> RuntimeExecutionResponse:
        self.contract_validator.validate_site_ops_analysis_contract(request)
        trace_id = request.trace_id or uuid4().hex
        run_id = f"run_{uuid4().hex}"
        merged_policy = self._build_site_ops_analysis_policy(request)
        request_fingerprint = self.run_lifecycle_service.build_request_fingerprint(
            request,
            merged_policy,
        )

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            self._require_active_site(repository, request.site_id)

            existing = self.run_lifecycle_service.get_idempotent_replay(
                repository=repository,
                site_id=request.site_id,
                idempotency_key=request.idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            if existing is not None:
                session.commit()
                return self._build_execution_response(
                    existing,
                    repository=repository,
                    idempotent_replay=True,
                )

            commercial_decision = self.commercial_service.authorize_runtime_request(
                session=session,
                site_id=request.site_id,
                ability_family=request.ability_family,
                channel=request.channel,
                execution_kind=request.execution_kind,
                execution_tier=request.execution_tier,
                data_classification=request.data_classification,
                trace_id=trace_id,
                idempotency_key=request.idempotency_key,
                request_kind="execute",
                run_id=run_id,
                estimated_ai_credits=self._estimate_runtime_request_ai_credits(request),
            )
            self._enforce_batch_limits(
                request=request,
                commercial_decision=commercial_decision,
            )
            merged_policy = self._apply_commercial_policy_overrides(
                merged_policy,
                commercial_decision=commercial_decision,
            )
            storage_mode = self._get_storage_mode(merged_policy)
            run = self.run_lifecycle_service.create_durable_run(
                repository=repository,
                command=RuntimeRunCreationCommand(
                    run_id=run_id,
                    site_id=request.site_id,
                    account_id=str(commercial_decision.get("account_id") or "") or None,
                    subscription_id=str(commercial_decision.get("subscription_id") or "") or None,
                    plan_version_id=str(commercial_decision.get("plan_version_id") or "") or None,
                    ability_name=request.ability_name,
                    ability_family=request.ability_family,
                    skill_id=request.skill_id,
                    workflow_id=request.workflow_id,
                    contract_version=request.contract_version,
                    channel=request.channel,
                    execution_kind=request.execution_kind,
                    execution_tier=request.execution_tier,
                    execution_pattern=request.execution_pattern,
                    data_classification=request.data_classification,
                    profile_id=request.profile_id or SITE_OPS_ANALYSIS_PROFILE_ID,
                    canonical_run_id=request.canonical_run_id or None,
                    status="running",
                    idempotency_key=request.idempotency_key,
                    request_fingerprint=request_fingerprint,
                    trace_id=trace_id,
                    input_json=self._prepare_input_for_storage(
                        request.input_payload,
                        storage_mode=storage_mode,
                    ),
                    execution_input_ciphertext=None,
                    policy_json=merged_policy,
                    selected_provider_id="site_ops_analysis",
                    selected_model_id="deterministic-ops-analyzer-v1",
                    selected_instance_id="cloud-runtime",
                ),
            )
            self.commercial_service.record_run_acceptance(session=session, run=run)
            self._execute_site_ops_analysis_run(
                run,
                repository=repository,
                input_payload=request.input_payload,
            )
            session.commit()
            return self._build_execution_response(
                run,
                repository=repository,
                idempotent_replay=False,
            )

    def _execute_image_context_evidence_request(
        self,
        request: RuntimeRequest,
    ) -> RuntimeExecutionResponse:
        self.contract_validator.validate_image_context_evidence_contract(request)
        resolution = self.routing_service.resolve(
            profile_id=request.profile_id,
            execution_kind="vision",
        )
        trace_id = request.trace_id or uuid4().hex
        run_id = f"run_{uuid4().hex}"
        merged_policy = self._build_image_context_evidence_policy(request, resolution)
        request_fingerprint = self.run_lifecycle_service.build_request_fingerprint(
            request,
            merged_policy,
        )
        selected_candidate = resolution.selected_candidate

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            self._require_active_site(repository, request.site_id)

            existing = self.run_lifecycle_service.get_idempotent_replay(
                repository=repository,
                site_id=request.site_id,
                idempotency_key=request.idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            if existing is not None:
                session.commit()
                return self._build_execution_response(
                    existing,
                    repository=repository,
                    idempotent_replay=True,
                )

            commercial_decision = self.commercial_service.authorize_runtime_request(
                session=session,
                site_id=request.site_id,
                ability_family=request.ability_family,
                channel=request.channel,
                execution_kind=request.execution_kind,
                execution_tier=request.execution_tier,
                data_classification=request.data_classification,
                trace_id=trace_id,
                idempotency_key=request.idempotency_key,
                request_kind="execute",
                run_id=run_id,
                estimated_ai_credits=self._estimate_runtime_request_ai_credits(request),
            )
            self._enforce_batch_limits(
                request=request,
                commercial_decision=commercial_decision,
            )
            merged_policy = self._apply_commercial_policy_overrides(
                merged_policy,
                commercial_decision=commercial_decision,
            )
            storage_mode = self._get_storage_mode(merged_policy)
            run = self.run_lifecycle_service.create_durable_run(
                repository=repository,
                command=RuntimeRunCreationCommand(
                    run_id=run_id,
                    site_id=request.site_id,
                    account_id=str(commercial_decision.get("account_id") or "") or None,
                    subscription_id=str(commercial_decision.get("subscription_id") or "") or None,
                    plan_version_id=str(commercial_decision.get("plan_version_id") or "") or None,
                    ability_name=request.ability_name,
                    ability_family=request.ability_family,
                    skill_id=request.skill_id,
                    workflow_id=request.workflow_id,
                    contract_version=request.contract_version,
                    channel=request.channel,
                    execution_kind=request.execution_kind,
                    execution_tier=request.execution_tier,
                    execution_pattern=request.execution_pattern,
                    data_classification=request.data_classification,
                    profile_id=request.profile_id or IMAGE_CONTEXT_EVIDENCE_PROFILE_ID,
                    canonical_run_id=request.canonical_run_id or None,
                    status="running",
                    idempotency_key=request.idempotency_key,
                    request_fingerprint=request_fingerprint,
                    trace_id=trace_id,
                    input_json=self._prepare_input_for_storage(
                        request.input_payload,
                        storage_mode=storage_mode,
                    ),
                    execution_input_ciphertext=None,
                    policy_json=merged_policy,
                    selected_provider_id=selected_candidate.provider_id,
                    selected_model_id=selected_candidate.model_id,
                    selected_instance_id=selected_candidate.instance_id,
                ),
            )
            self.commercial_service.record_run_acceptance(session=session, run=run)
            self._execute_image_context_evidence_run(
                run,
                repository=repository,
                input_payload=request.input_payload,
                candidate=selected_candidate,
            )
            session.commit()
            return self._build_execution_response(
                run,
                repository=repository,
                idempotent_replay=False,
            )

    def _execute_media_batch_plan_run(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any] | None = None,
    ) -> None:
        if self.run_lifecycle_service.cancel_if_requested(
            repository=repository,
            run=run,
        ):
            return

        payload = (
            input_payload
            if isinstance(input_payload, dict)
            else self._get_execution_input_payload(run)
        )
        try:
            execution = MediaBatchPlanService(self.settings).execute(
                site_id=run.site_id,
                ability_name=run.ability_name,
                contract_version=run.contract_version or "",
                input_payload=payload,
                run_id=run.run_id,
            )
        except MediaBatchPlanContractViolation as error:
            self.run_lifecycle_service.fail_run(
                repository,
                run,
                error_code=error.error_code,
                error_message=error.message,
                provider_id="media_batch_plan",
                model_id="deterministic-intent-parser",
                instance_id="cloud-runtime",
                fallback_used=False,
            )
            return

        self.run_lifecycle_service.succeed_run(
            repository,
            run,
            result_json=execution.result_json,
            provider_id="media_batch_plan",
            model_id="deterministic-intent-parser",
            instance_id="cloud-runtime",
            fallback_used=False,
        )

    def _execute_site_ops_analysis_run(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any] | None = None,
    ) -> None:
        if self.run_lifecycle_service.cancel_if_requested(
            repository=repository,
            run=run,
        ):
            return

        payload = (
            input_payload
            if isinstance(input_payload, dict)
            else self._get_execution_input_payload(run)
        )
        try:
            execution = SiteOpsAnalysisService().execute(
                site_id=run.site_id,
                ability_name=run.ability_name,
                contract_version=run.contract_version or "",
                input_payload=payload,
                run_id=run.run_id,
            )
        except SiteOpsAnalysisContractViolation as error:
            self.run_lifecycle_service.fail_run(
                repository,
                run,
                error_code=error.error_code,
                error_message=error.message,
                provider_id="site_ops_analysis",
                model_id="deterministic-ops-analyzer-v1",
                instance_id="cloud-runtime",
                fallback_used=False,
            )
            return
        except Exception:
            logger.exception(
                "site ops analysis runtime failed: run_id=%s site_id=%s trace_id=%s",
                run.run_id,
                run.site_id,
                run.trace_id,
            )
            self.run_lifecycle_service.fail_run(
                repository,
                run,
                error_code="site_ops_analysis.execution_failed",
                error_message="site ops analysis runtime failed",
                provider_id="site_ops_analysis",
                model_id="deterministic-ops-analyzer-v1",
                instance_id="cloud-runtime",
                fallback_used=False,
            )
            return

        self.run_lifecycle_service.succeed_run(
            repository,
            run,
            result_json=execution.result_json,
            provider_id="site_ops_analysis",
            model_id="deterministic-ops-analyzer-v1",
            instance_id="cloud-runtime",
            fallback_used=False,
        )

    def _execute_image_context_evidence_run(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any] | None = None,
        candidate: RoutingCandidate | None = None,
    ) -> None:
        if self.run_lifecycle_service.cancel_if_requested(
            repository=repository,
            run=run,
        ):
            return

        payload = (
            input_payload
            if isinstance(input_payload, dict)
            else self._get_execution_input_payload(run)
        )
        selected_candidate = candidate or self._resolve_run_routing_candidate(run)
        provider = self.providers.get(selected_candidate.provider_id)
        if provider is None:
            self.run_lifecycle_service.fail_run(
                repository,
                run,
                error_code="runtime.provider_not_configured",
                error_message=(
                    f"provider adapter is not configured for {selected_candidate.provider_id}"
                ),
                provider_id=selected_candidate.provider_id,
                model_id=selected_candidate.model_id,
                instance_id=selected_candidate.instance_id,
                fallback_used=False,
            )
            return

        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
        timeout_ms = max(1, self._coerce_int(policy.get("timeout_ms"), default=30_000))
        try:
            execution = ImageContextEvidenceService(self.settings).execute(
                site_id=run.site_id,
                ability_name=run.ability_name,
                contract_version=run.contract_version or "",
                input_payload=payload,
                run_id=run.run_id,
                provider=provider,
                provider_id=selected_candidate.provider_id,
                model_id=selected_candidate.model_id,
                instance_id=selected_candidate.instance_id,
                endpoint_variant=selected_candidate.endpoint_variant,
                region=selected_candidate.region,
                trace_id=run.trace_id,
                profile_id=run.profile_id,
                policy=policy,
                timeout_ms=timeout_ms,
                price_input=selected_candidate.price_input,
                price_output=selected_candidate.price_output,
            )
        except ImageContextEvidenceContractViolation as error:
            self.run_lifecycle_service.fail_run(
                repository,
                run,
                error_code=error.error_code,
                error_message=error.message,
                provider_id=selected_candidate.provider_id,
                model_id=selected_candidate.model_id,
                instance_id=selected_candidate.instance_id,
                fallback_used=False,
            )
            return
        except ImageContextEvidenceProviderError as error:
            if error.usage is not None:
                self.provider_execution_service.record_provider_call(
                    repository=repository,
                    run=run,
                    command=ProviderCallEvidenceCommand(
                        provider_id=error.usage.provider_id,
                        model_id=error.usage.model_id,
                        instance_id=error.usage.instance_id,
                        region=error.usage.region,
                        latency_ms=error.usage.latency_ms,
                        tokens_in=error.usage.tokens_in,
                        tokens_out=error.usage.tokens_out,
                        cost=error.usage.cost,
                        retry_count=0,
                        fallback_used=False,
                        error_code=error.usage.error_code or error.error_code,
                    ),
                )
            self.run_lifecycle_service.fail_run(
                repository,
                run,
                error_code=error.error_code,
                error_message=error.message,
                provider_id=selected_candidate.provider_id,
                model_id=selected_candidate.model_id,
                instance_id=selected_candidate.instance_id,
                fallback_used=False,
            )
            return

        self.provider_execution_service.record_provider_call(
            repository=repository,
            run=run,
            command=ProviderCallEvidenceCommand(
                provider_id=execution.usage.provider_id,
                model_id=execution.usage.model_id,
                instance_id=execution.usage.instance_id,
                region=execution.usage.region,
                latency_ms=execution.usage.latency_ms,
                tokens_in=execution.usage.tokens_in,
                tokens_out=execution.usage.tokens_out,
                cost=execution.usage.cost,
                retry_count=0,
                fallback_used=False,
                error_code=execution.usage.error_code,
            ),
        )
        self.run_lifecycle_service.succeed_run(
            repository,
            run,
            result_json=execution.result_json,
            provider_id=execution.usage.provider_id,
            model_id=execution.usage.model_id,
            instance_id=execution.usage.instance_id,
            fallback_used=False,
        )

    def _execute_cloud_batch_runtime_run(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any] | None = None,
    ) -> None:
        if self.run_lifecycle_service.cancel_if_requested(
            repository=repository,
            run=run,
        ):
            return

        started = perf_counter()
        logger.info(
            "cloud batch runtime started: run_id=%s site_id=%s trace_id=%s "
            "ability_name=%s execution_kind=%s",
            run.run_id,
            run.site_id,
            run.trace_id,
            run.ability_name,
            run.execution_kind,
        )
        payload = (
            input_payload
            if isinstance(input_payload, dict)
            else self._get_execution_input_payload(run)
        )
        try:
            execution = CloudBatchRuntimeService().execute(
                site_id=run.site_id,
                ability_name=run.ability_name,
                contract_version=run.contract_version or "",
                input_payload=payload,
                run_id=run.run_id,
            )
        except CloudBatchRuntimeContractViolation as error:
            latency_ms = max(0, int((perf_counter() - started) * 1000))
            self.provider_execution_service.record_provider_call(
                repository=repository,
                run=run,
                command=ProviderCallEvidenceCommand(
                    provider_id="cloud_batch_runtime",
                    model_id="deterministic-content-quality-v1",
                    instance_id="cloud-runtime",
                    region=self.settings.deployment_region,
                    latency_ms=latency_ms,
                    tokens_in=0,
                    tokens_out=0,
                    cost=0.0,
                    retry_count=0,
                    fallback_used=False,
                    error_code=error.error_code,
                ),
            )
            self.run_lifecycle_service.fail_run(
                repository,
                run,
                error_code=error.error_code,
                error_message=error.message,
                provider_id="cloud_batch_runtime",
                model_id="deterministic-content-quality-v1",
                instance_id="cloud-runtime",
                fallback_used=False,
            )
            logger.warning(
                "cloud batch runtime failed: run_id=%s site_id=%s trace_id=%s "
                "error_code=%s latency_ms=%s",
                run.run_id,
                run.site_id,
                run.trace_id,
                error.error_code,
                latency_ms,
            )
            return
        latency_ms = max(0, int((perf_counter() - started) * 1000))

        self.provider_execution_service.record_provider_call(
            repository=repository,
            run=run,
            command=ProviderCallEvidenceCommand(
                provider_id="cloud_batch_runtime",
                model_id="deterministic-content-quality-v1",
                instance_id="cloud-runtime",
                region=self.settings.deployment_region,
                latency_ms=latency_ms,
                tokens_in=0,
                tokens_out=0,
                cost=0.0,
                retry_count=0,
                fallback_used=False,
            ),
        )
        self.run_lifecycle_service.succeed_run(
            repository,
            run,
            result_json=execution.result_json,
            provider_id="cloud_batch_runtime",
            model_id="deterministic-content-quality-v1",
            instance_id="cloud-runtime",
            fallback_used=False,
        )
        logger.info(
            "cloud batch runtime finished: run_id=%s site_id=%s trace_id=%s "
            "result_status=%s worker_phase=%s latency_ms=%s",
            run.run_id,
            run.site_id,
            run.trace_id,
            execution.result_json.get("status"),
            execution.result_json.get("worker_phase"),
            latency_ms,
        )

    def _execute_image_source_run(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any] | None = None,
    ) -> None:
        if self.run_lifecycle_service.cancel_if_requested(
            repository=repository,
            run=run,
        ):
            return

        payload = (
            input_payload
            if isinstance(input_payload, dict)
            else self._get_execution_input_payload(run)
        )
        if self._image_source_fast_first(payload):
            site_knowledge_context = self._skipped_image_source_site_knowledge_context(
                reason="fast_first_deferred"
            )
            llm_prompt_plan = self._skipped_image_source_llm_prompt_plan(
                reason="fast_first_deferred"
            )
        else:
            site_knowledge_context = self._build_image_source_site_knowledge_context(
                run,
                repository=repository,
                input_payload=payload,
            )
            llm_prompt_plan = self._build_image_source_llm_prompt_plan(
                run,
                repository=repository,
                input_payload=payload,
                site_knowledge_context=site_knowledge_context,
            )
        try:
            execution = ImageSourceService(self.settings).execute(
                site_id=run.site_id,
                ability_name=run.ability_name,
                contract_version=run.contract_version or "",
                input_payload=payload,
                run_id=run.run_id,
                site_knowledge_context=site_knowledge_context,
                llm_prompt_plan=llm_prompt_plan,
            )
        except ImageSourceContractViolation as error:
            self.run_lifecycle_service.fail_run(
                repository,
                run,
                error_code=error.error_code,
                error_message=error.message,
                provider_id="image_source",
                model_id="image-source-managed",
                instance_id="cloud-runtime",
                fallback_used=False,
            )
            return
        except ImageSourceProviderError as error:
            if error.usage is not None:
                self.provider_execution_service.record_provider_call(
                    repository=repository,
                    run=run,
                    command=ProviderCallEvidenceCommand(
                        provider_id=error.usage.provider_id,
                        model_id=error.usage.model_id,
                        instance_id=error.usage.instance_id,
                        region=error.usage.region,
                        latency_ms=error.usage.latency_ms,
                        tokens_in=0,
                        tokens_out=0,
                        cost=error.usage.cost,
                        retry_count=0,
                        fallback_used=False,
                        error_code=error.usage.error_code or error.error_code,
                    ),
                )
            self.run_lifecycle_service.fail_run(
                repository,
                run,
                error_code=error.error_code,
                error_message=error.message,
                provider_id="image_source",
                model_id="image-source-managed",
                instance_id="cloud-runtime",
                fallback_used=False,
            )
            return

        self.provider_execution_service.record_provider_call(
            repository=repository,
            run=run,
            command=ProviderCallEvidenceCommand(
                provider_id=execution.usage.provider_id,
                model_id=execution.usage.model_id,
                instance_id=execution.usage.instance_id,
                region=execution.usage.region,
                latency_ms=execution.usage.latency_ms,
                tokens_in=0,
                tokens_out=0,
                cost=execution.usage.cost,
                retry_count=0,
                fallback_used=False,
                error_code=execution.usage.error_code,
            ),
        )
        self.run_lifecycle_service.succeed_run(
            repository,
            run,
            result_json=execution.result_json,
            provider_id="image_source",
            model_id="image-source-managed",
            instance_id="cloud-runtime",
            fallback_used=False,
        )

    def _image_source_fast_first(self, input_payload: dict[str, Any]) -> bool:
        visual_context = self._dict_or_empty(input_payload.get("visual_context"))
        latency_mode = (
            str(input_payload.get("latency_mode") or visual_context.get("latency_mode") or "")
            .strip()
            .lower()
        )
        enhancement_mode = str(input_payload.get("enhancement_mode") or "").strip().lower()
        if latency_mode == "fast_first" or enhancement_mode == "deferred":
            return True

        cloud_steps = visual_context.get("cloud_ai_steps")
        if isinstance(cloud_steps, list) and cloud_steps:
            normalized_steps = {str(step).strip() for step in cloud_steps}
            return (
                "site_context_vectors" not in normalized_steps
                and "candidate_rerank" not in normalized_steps
            )
        return False

    def _skipped_image_source_site_knowledge_context(self, *, reason: str) -> dict[str, Any]:
        return {
            "status": "deferred",
            "reason": reason,
            "intent": "image_context",
            "results": [],
            "write_posture": "suggestion_only",
            "direct_wordpress_write": False,
        }

    def _skipped_image_source_llm_prompt_plan(self, *, reason: str) -> dict[str, Any]:
        return {
            "status": "deferred",
            "reason": reason,
            "fallback": "rule_prompt_candidates",
            "prompt_candidates": [],
        }

    def _build_image_source_site_knowledge_context(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any],
    ) -> dict[str, Any]:
        query = self._image_source_site_knowledge_query(input_payload)
        if not query:
            return {
                "status": "skipped",
                "reason": "no_visual_context",
                "intent": "image_context",
                "results": [],
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            }

        visual_context = self._dict_or_empty(input_payload.get("visual_context"))
        current_post_id = self._coerce_int(
            visual_context.get("post_id") or input_payload.get("post_id"),
            default=0,
        )
        candidate_limits = self._dict_or_empty(visual_context.get("candidate_limits"))
        max_results = min(
            4,
            max(
                1,
                self._coerce_int(
                    candidate_limits.get("max_site_context_results"),
                    default=3,
                ),
            ),
        )

        def record_embedding_usage(
            provider_id: str,
            provider_request: ProviderExecutionRequest,
            provider_result: ProviderExecutionResult | None,
            provider_error: ProviderExecutionError | None,
        ) -> None:
            self._record_site_knowledge_embedding_provider_call(
                run,
                repository=repository,
                provider_id=provider_id,
                provider_request=provider_request,
                provider_result=provider_result,
                provider_error=provider_error,
            )

        try:
            result = SiteKnowledgeService(
                repository.session,
                settings=self.settings,
                providers=self.providers,
                embedding_usage_callback=record_embedding_usage,
            ).execute(
                site_id=run.site_id,
                ability_name=SITE_KNOWLEDGE_SEARCH_ABILITY,
                contract_version=SITE_KNOWLEDGE_CONTRACTS[SITE_KNOWLEDGE_SEARCH_ABILITY],
                input_payload={
                    "contract_version": SITE_KNOWLEDGE_CONTRACTS[SITE_KNOWLEDGE_SEARCH_ABILITY],
                    "query": query,
                    "intent": "image_context",
                    "max_results": max_results,
                    "current_post_id": current_post_id,
                    "filters": {
                        "post_types": ["post", "page"],
                        "status": ["publish"],
                        "source_types": ["post", "page"],
                    },
                    "evidence_policy": {
                        "min_score": 0.2,
                        "required_sources": 1,
                        "no_hit_policy": "fallback_to_general",
                    },
                    "write_posture": "suggestion_only",
                },
                run_id=run.run_id,
            )
        except (SiteKnowledgeContractViolation, SiteKnowledgeBackendError) as error:
            return {
                "status": "unavailable",
                "intent": "image_context",
                "error_code": error.error_code,
                "results": [],
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            }

        results = result.get("results") if isinstance(result.get("results"), list) else []
        return {
            "status": str(result.get("status") or "ready")
            if results
            else str(result.get("evidence_gate", {}).get("status") or "insufficient_evidence"),
            "intent": str(result.get("intent") or "image_context"),
            "evidence_gate": result.get("evidence_gate")
            if isinstance(result.get("evidence_gate"), dict)
            else {},
            "rerank": result.get("rerank") if isinstance(result.get("rerank"), dict) else {},
            "results": results,
            "write_posture": "suggestion_only",
            "direct_wordpress_write": False,
        }

    def _build_image_source_llm_prompt_plan(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any],
        site_knowledge_context: dict[str, Any],
    ) -> dict[str, Any]:
        query = self._image_source_site_knowledge_query(input_payload)
        if not query:
            return {
                "status": "skipped",
                "fallback": "rule_prompt_candidates",
                "prompt_candidates": [],
            }

        try:
            candidate, profile_id, default_policy = self._resolve_image_prompt_planner_candidate()
        except RoutingError as error:
            return {
                "status": "unavailable",
                "error_code": error.error_code,
                "fallback": "rule_prompt_candidates",
                "prompt_candidates": [],
            }

        provider = self.providers.get(candidate.provider_id)
        if provider is None:
            return {
                "status": "unavailable",
                "error_code": "runtime.provider_not_configured",
                "profile_id": profile_id,
                "provider_id": candidate.provider_id,
                "model_id": candidate.model_id,
                "fallback": "rule_prompt_candidates",
                "prompt_candidates": [],
            }

        timeout_ms = max(1, self._coerce_int(default_policy.get("timeout_ms"), default=12_000))
        request = ProviderExecutionRequest(
            run_id=run.run_id,
            site_id=run.site_id,
            ability_name="npcink-cloud/image-prompt-planner",
            profile_id=profile_id,
            execution_kind="text",
            model_id=candidate.model_id,
            instance_id=candidate.instance_id,
            endpoint_variant=candidate.endpoint_variant,
            trace_id=run.trace_id or run.run_id,
            input_payload=self._build_image_prompt_planner_input(
                input_payload=input_payload,
                site_knowledge_context=site_knowledge_context,
            ),
            policy={"storage_mode": "result_only"},
            timeout_ms=timeout_ms,
            price_input=candidate.price_input,
            price_output=candidate.price_output,
        )
        try:
            provider_result = self.provider_execution_service.execute_provider(
                provider,
                request,
            )
        except ProviderExecutionError as error:
            self.provider_execution_service.record_provider_call(
                repository=repository,
                run=run,
                command=ProviderCallEvidenceCommand(
                    provider_id=candidate.provider_id,
                    model_id=candidate.model_id,
                    instance_id=candidate.instance_id,
                    region=candidate.region,
                    latency_ms=(timeout_ms if error.error_code == "provider.timeout" else 0),
                    tokens_in=max(0, int(getattr(error, "tokens_in", 0) or 0)),
                    tokens_out=max(0, int(getattr(error, "tokens_out", 0) or 0)),
                    cost=max(0.0, float(getattr(error, "cost", 0.0) or 0.0)),
                    retry_count=0,
                    fallback_used=False,
                    error_code=error.error_code,
                ),
            )
            return {
                "status": "failed",
                "error_code": error.error_code,
                "profile_id": profile_id,
                "provider_id": candidate.provider_id,
                "model_id": candidate.model_id,
                "fallback": "rule_prompt_candidates",
                "prompt_candidates": [],
            }

        self.provider_execution_service.record_provider_call(
            repository=repository,
            run=run,
            command=ProviderCallEvidenceCommand(
                provider_id=candidate.provider_id,
                model_id=candidate.model_id,
                instance_id=candidate.instance_id,
                region=candidate.region,
                latency_ms=provider_result.latency_ms,
                tokens_in=provider_result.tokens_in,
                tokens_out=provider_result.tokens_out,
                cost=provider_result.cost,
                retry_count=0,
                fallback_used=False,
                error_code=None,
            ),
        )
        prompt_candidates = self._parse_image_prompt_planner_output(
            provider_result.output.get("output_text"),
        )
        if not prompt_candidates:
            return {
                "status": "failed",
                "error_code": "image_prompt_planner.invalid_output",
                "profile_id": profile_id,
                "provider_id": candidate.provider_id,
                "model_id": candidate.model_id,
                "fallback": "rule_prompt_candidates",
                "prompt_candidates": [],
            }
        return {
            "status": "ready",
            "profile_id": profile_id,
            "provider_id": candidate.provider_id,
            "model_id": candidate.model_id,
            "prompt_candidates": prompt_candidates,
        }

    def _resolve_image_prompt_planner_candidate(
        self,
    ) -> tuple[RoutingCandidate, str, dict[str, object]]:
        last_error: RoutingError | None = None
        for profile_id in (FREE_GPT55_TEXT_PROFILE_ID, "text.balanced"):
            try:
                resolution = self.routing_service.resolve(
                    profile_id=profile_id,
                    execution_kind="text",
                )
                return (
                    resolution.selected_candidate,
                    resolution.profile_id,
                    resolution.default_policy,
                )
            except RoutingError as error:
                last_error = error
        if last_error is not None:
            raise last_error
        raise RoutingError(
            "routing.profile_not_found",
            "image prompt planner text routing profile is not configured",
        )

    def _build_image_prompt_planner_input(
        self,
        *,
        input_payload: dict[str, Any],
        site_knowledge_context: dict[str, Any],
    ) -> dict[str, Any]:
        visual_context = self._dict_or_empty(input_payload.get("visual_context"))
        evidence = []
        for item in site_knowledge_context.get("results", []):
            if not isinstance(item, dict):
                continue
            evidence.append(
                {
                    "title": str(item.get("title") or "")[:160],
                    "match_context": str(item.get("match_context") or item.get("chunk_text") or "")[
                        :320
                    ],
                    "score": item.get("score", 0),
                }
            )
        planner_context = {
            "query": str(input_payload.get("query") or "")[:300],
            "image_mode": str(
                visual_context.get("image_mode") or visual_context.get("image_use") or ""
            )[:40],
            "title": str(visual_context.get("title") or "")[:160],
            "excerpt": str(visual_context.get("excerpt") or "")[:240],
            "selected_text": str(
                visual_context.get("selected_text")
                or visual_context.get("selected_block_text")
                or ""
            )[:600],
            "site_evidence": evidence[:4],
        }
        return {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an editorial image prompt planner. Return only JSON. "
                        "Plan original image-generation prompts from the selected article "
                        "context and site evidence. Do not copy article wording as visible "
                        "image text. Do not include logos, watermarks, UI screenshots, "
                        "credentials, or WordPress write instructions."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Return JSON with key prompt_candidates, an array of 1 to 3 "
                        "objects. Each object must include id, label, direction_type, "
                        "visual_strategy, reason, and prompt. Use direction_type values "
                        "like editorial_scene, conceptual_metaphor, workflow_detail, "
                        "or article_cover so the editor can show distinct visual choices. "
                        "reason must briefly explain why the direction fits the selected "
                        "paragraph and nearby article context. Prompts must be "
                        "publication-safe, concrete, and "
                        "must explicitly forbid visible text, letters, numbers, logos, "
                        "watermarks, screenshots, and copied article wording.\n\n"
                        f"Context:\n{json.dumps(planner_context, ensure_ascii=False)}"
                    ),
                },
            ],
            "params": {
                "temperature": 0.3,
                "max_tokens": 900,
                "max_output_tokens": 900,
            },
        }

    def _parse_image_prompt_planner_output(self, output_text: object) -> list[dict[str, object]]:
        text = str(output_text or "").strip()
        if not text:
            return []
        payload: object
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                return []
            try:
                payload = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return []
        if not isinstance(payload, dict):
            return []
        raw_candidates = payload.get("prompt_candidates")
        if not isinstance(raw_candidates, list):
            return []
        candidates: list[dict[str, object]] = []
        for index, item in enumerate(raw_candidates[:3], start=1):
            if not isinstance(item, dict):
                continue
            prompt = " ".join(str(item.get("prompt") or "").split())[:1200]
            if not prompt:
                continue
            candidates.append(
                {
                    "id": str(item.get("id") or f"llm_prompt_{index}")[:80],
                    "label": str(item.get("label") or f"LLM prompt {index}")[:80],
                    "direction_type": str(item.get("direction_type") or "")[:80],
                    "visual_strategy": str(item.get("visual_strategy") or "")[:160],
                    "reason": str(item.get("reason") or "")[:220],
                    "image_use": str(item.get("image_use") or "")[:80],
                    "prompt": prompt,
                }
            )
        return candidates

    def _image_source_site_knowledge_query(self, input_payload: dict[str, Any]) -> str:
        visual_context = self._dict_or_empty(input_payload.get("visual_context"))
        parts = [
            visual_context.get("selected_text"),
            visual_context.get("selected_block_text"),
            visual_context.get("manual_query"),
            visual_context.get("fallback_query"),
            visual_context.get("title"),
            visual_context.get("excerpt"),
            input_payload.get("query"),
        ]
        text = " ".join(str(part or "").strip() for part in parts if str(part or "").strip())
        return " ".join(text.split())[:500]

    def _is_image_source_request(self, request: RuntimeRequest) -> bool:
        return request.ability_name in IMAGE_SOURCE_ABILITIES

    def _is_image_generation_request(self, request: RuntimeRequest) -> bool:
        return request.ability_name in IMAGE_GENERATION_ABILITIES

    def _validate_image_generation_artifact_storage(self, request: RuntimeRequest) -> None:
        if (
            self._is_image_generation_request(request)
            and str(request.storage_mode or RUNTIME_STORAGE_MODE_RESULT_ONLY).strip()
            == RUNTIME_STORAGE_MODE_NO_STORE
        ):
            raise RuntimeExecutionContractError(
                "image_generation.artifact_storage_required",
                "image generation requires result_only or full_store_with_ttl storage",
            )

    def _is_audio_generation_request(self, request: RuntimeRequest) -> bool:
        return request.ability_name in AUDIO_GENERATION_ABILITIES

    def _is_media_batch_plan_request(self, request: RuntimeRequest) -> bool:
        return request.ability_name in MEDIA_BATCH_PLAN_ABILITIES

    def _is_site_ops_analysis_request(self, request: RuntimeRequest) -> bool:
        return request.ability_name in SITE_OPS_ANALYSIS_ABILITIES

    def _is_image_context_evidence_request(self, request: RuntimeRequest) -> bool:
        return request.ability_name in IMAGE_CONTEXT_EVIDENCE_ABILITIES

    def _is_cloud_batch_runtime_request(self, request: RuntimeRequest) -> bool:
        return request.ability_name in CLOUD_BATCH_RUNTIME_ABILITIES

    def _is_site_knowledge_request(self, request: RuntimeRequest) -> bool:
        return request.ability_name in SITE_KNOWLEDGE_ABILITIES

    def _is_web_search_request(self, request: RuntimeRequest) -> bool:
        return request.ability_name in WEB_SEARCH_ABILITIES

    def _is_wordpress_ai_connector_request(self, request: RuntimeRequest) -> bool:
        return request.ability_name in CONNECTOR_RUNTIME_ABILITIES

    def _is_wordpress_ai_connector_managed_request(self, request: RuntimeRequest) -> bool:
        if self._is_wordpress_ai_connector_request(request):
            return True
        input_payload = request.input_payload if isinstance(request.input_payload, dict) else {}
        return (
            self._is_image_generation_request(request)
            and request.channel == "wordpress_ai_connector"
            and str(input_payload.get("source_surface") or "") == "wordpress_ai_connector"
            and str(input_payload.get("connector_id") or "") == "npcink-cloud"
            and str(input_payload.get("task") or "") == "image_generation"
        )

    def _is_image_source_run(self, run: RunRecord) -> bool:
        return str(run.ability_name or "") in IMAGE_SOURCE_ABILITIES

    def _is_image_generation_run(self, run: RunRecord) -> bool:
        return str(run.ability_name or "") in IMAGE_GENERATION_ABILITIES

    def _is_audio_generation_run(self, run: RunRecord) -> bool:
        return str(run.ability_name or "") in AUDIO_GENERATION_ABILITIES

    def _materialize_audio_generation_output(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        provider_output: dict[str, Any],
    ) -> dict[str, Any]:
        return self.artifact_coordination_service.materialize_audio_generation_output(
            run=run,
            repository=repository,
            provider_output=provider_output,
        )

    def _materialize_image_generation_output(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        provider_output: dict[str, Any],
        media_candidates: tuple[ProviderMediaCandidate, ...],
    ) -> dict[str, Any]:
        return self.artifact_coordination_service.materialize_image_generation_output(
            run=run,
            repository=repository,
            provider_output=provider_output,
            media_candidates=media_candidates,
        )

    def _is_media_batch_plan_run(self, run: RunRecord) -> bool:
        return str(run.ability_name or "") in MEDIA_BATCH_PLAN_ABILITIES

    def _is_image_context_evidence_run(self, run: RunRecord) -> bool:
        return str(run.ability_name or "") in IMAGE_CONTEXT_EVIDENCE_ABILITIES

    def _is_cloud_batch_runtime_run(self, run: RunRecord) -> bool:
        return str(run.ability_name or "") in CLOUD_BATCH_RUNTIME_ABILITIES

    def _is_site_knowledge_run(self, run: RunRecord) -> bool:
        return str(run.ability_name or "") in SITE_KNOWLEDGE_ABILITIES

    def _is_web_search_run(self, run: RunRecord) -> bool:
        return str(run.ability_name or "") in WEB_SEARCH_ABILITIES

    def _is_wordpress_ai_connector_run(self, run: RunRecord) -> bool:
        return str(run.ability_name or "") in CONNECTOR_RUNTIME_ABILITIES

    def _prepare_wordpress_operation_execution_input(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        connector_envelope: dict[str, Any],
    ) -> dict[str, Any]:
        def record_embedding_usage(
            provider_id: str,
            provider_request: ProviderExecutionRequest,
            provider_result: ProviderExecutionResult | None,
            provider_error: ProviderExecutionError | None,
        ) -> None:
            self._record_site_knowledge_embedding_provider_call(
                run,
                repository=repository,
                provider_id=provider_id,
                provider_request=provider_request,
                provider_result=provider_result,
                provider_error=provider_error,
            )

        source_artifact = self._load_wordpress_operation_artifact_input(
            repository,
            site_id=run.site_id,
            connector_envelope=connector_envelope,
        )
        provider_input = self.wordpress_operation_runtime.build_provider_input(
            connector_envelope,
            source_artifact=source_artifact,
        )
        return self.wordpress_operation_runtime.apply_site_knowledge_reference(
            site_id=run.site_id,
            run_id=run.run_id,
            session=repository.session,
            input_payload=connector_envelope,
            provider_input=provider_input,
            embedding_usage_callback=record_embedding_usage,
        )

    def _admit_wordpress_operation_artifact_input(
        self,
        repository: RuntimeRepository,
        *,
        site_id: str,
        connector_envelope: dict[str, Any],
    ) -> None:
        artifact_id = self.wordpress_operation_runtime.source_artifact_id(
            connector_envelope
        )
        if not artifact_id:
            return
        try:
            admit_artifact_input(
                repository.session,
                site_id=site_id,
                artifact_id=artifact_id,
            )
        except ArtifactInputError as error:
            raise RuntimeExecutionContractError(
                error.error_code,
                error.message,
            ) from error

    def _load_wordpress_operation_artifact_input(
        self,
        repository: RuntimeRepository,
        *,
        site_id: str,
        connector_envelope: dict[str, Any],
    ) -> LoadedArtifactInput | None:
        artifact_id = self.wordpress_operation_runtime.source_artifact_id(
            connector_envelope
        )
        if not artifact_id:
            return None
        try:
            return load_artifact_input(
                repository.session,
                self.artifact_store,
                site_id=site_id,
                artifact_id=artifact_id,
            )
        except ArtifactInputError as error:
            raise RuntimeExecutionContractError(
                error.error_code,
                error.message,
            ) from error

    def _build_site_knowledge_policy(self, request: RuntimeRequest) -> dict[str, object]:
        policy = self._apply_runtime_controls(dict(request.policy), request)
        if request.ability_name == SITE_KNOWLEDGE_SYNC_ABILITY:
            policy.setdefault("allow_fallback", False)
        if request.execution_pattern == "whole_run_offload":
            task_backend = policy.get("task_backend")
            if not isinstance(task_backend, dict) or not task_backend:
                policy["task_backend"] = {
                    "enabled": True,
                    "mode": "queue",
                    "callback_mode": "polling_preferred",
                    "polling_interval_sec": 5,
                }
        policy["execution_contract"] = {
            "ability_name": request.ability_name,
            "contract_version": request.contract_version,
            "profile_id": request.profile_id,
            "execution_pattern": request.execution_pattern,
            "data_classification": request.data_classification,
            "storage_mode": request.storage_mode,
            "timeout_seconds": max(0, request.timeout_seconds),
            "retry_max": max(0, request.retry_max),
            "retention_ttl": max(0, request.retention_ttl),
            "task_backend": (
                policy.get("task_backend") if isinstance(policy.get("task_backend"), dict) else {}
            ),
        }
        return policy

    def _build_cloud_batch_runtime_policy(self, request: RuntimeRequest) -> dict[str, object]:
        policy = self._apply_runtime_controls(dict(request.policy), request)
        policy["allow_fallback"] = False
        if request.execution_pattern == "whole_run_offload":
            task_backend = policy.get("task_backend")
            if not isinstance(task_backend, dict) or not task_backend:
                policy["task_backend"] = {
                    "enabled": True,
                    "mode": "queue",
                    "callback_mode": "polling_preferred",
                    "polling_interval_sec": 10,
                }
        policy["execution_contract"] = {
            "ability_name": request.ability_name,
            "contract_version": request.contract_version,
            "profile_id": request.profile_id or CLOUD_BATCH_RUNTIME_PROFILE_ID,
            "execution_pattern": request.execution_pattern,
            "data_classification": request.data_classification,
            "storage_mode": request.storage_mode,
            "timeout_seconds": max(0, request.timeout_seconds),
            "retry_max": max(0, request.retry_max),
            "retention_ttl": max(0, request.retention_ttl),
            "result_contract": "cloud_batch_runtime_result.v1",
            "runtime_owner": "npcink-local-automation-runtime",
            "cloud_role": "runtime_detail",
            "final_writes": "core_proposal_required",
            "direct_wordpress_write": False,
            "task_backend": (
                policy.get("task_backend") if isinstance(policy.get("task_backend"), dict) else {}
            ),
        }
        return policy

    def _build_media_batch_plan_policy(self, request: RuntimeRequest) -> dict[str, object]:
        policy = self._apply_runtime_controls(dict(request.policy), request)
        policy["allow_fallback"] = False
        policy["execution_contract"] = {
            "ability_name": request.ability_name,
            "contract_version": request.contract_version,
            "profile_id": request.profile_id or MEDIA_BATCH_PLAN_PROFILE_ID,
            "execution_pattern": request.execution_pattern,
            "data_classification": request.data_classification,
            "storage_mode": request.storage_mode,
            "timeout_seconds": max(0, request.timeout_seconds),
            "retry_max": max(0, request.retry_max),
            "retention_ttl": max(0, request.retention_ttl),
            "plan_contract": "media_derivative_batch_plan.v1",
            "final_writes": "core_proposal_required",
            "direct_wordpress_write": False,
        }
        return policy

    def _build_site_ops_analysis_policy(self, request: RuntimeRequest) -> dict[str, object]:
        policy = self._apply_runtime_controls(dict(request.policy), request)
        policy["allow_fallback"] = False
        policy["execution_contract"] = {
            "ability_name": request.ability_name,
            "contract_version": request.contract_version,
            "profile_id": request.profile_id or SITE_OPS_ANALYSIS_PROFILE_ID,
            "execution_pattern": request.execution_pattern,
            "data_classification": SITE_OPS_ANALYSIS_DATA_CLASSIFICATION,
            "storage_mode": request.storage_mode,
            "timeout_seconds": max(0, request.timeout_seconds),
            "retry_max": max(0, request.retry_max),
            "retention_ttl": max(0, request.retention_ttl),
            "result_contract": SITE_OPS_ANALYSIS_RESULT_CONTRACT,
            "cloud_role": "runtime_detail",
            "write_posture": "suggestion_only",
            "direct_wordpress_write": False,
            "core_proposal_created": False,
            "cloud_scheduler_truth": False,
        }
        return policy

    def _build_image_context_evidence_policy(
        self,
        request: RuntimeRequest,
        resolution: RoutingResolution,
    ) -> dict[str, object]:
        policy = self._merge_policy(resolution.default_policy, request.policy)
        policy = self._apply_runtime_controls(policy, request)
        policy = self._apply_routing_snapshot(policy, resolution)
        policy["allow_fallback"] = False
        policy["execution_contract"] = {
            "ability_name": request.ability_name,
            "contract_version": request.contract_version,
            "profile_id": request.profile_id or IMAGE_CONTEXT_EVIDENCE_PROFILE_ID,
            "execution_pattern": request.execution_pattern,
            "data_classification": request.data_classification,
            "storage_mode": request.storage_mode,
            "timeout_seconds": max(0, request.timeout_seconds),
            "retry_max": max(0, request.retry_max),
            "retention_ttl": max(0, request.retention_ttl),
            "result_contract": "image_context_evidence.v1",
            "provider_source": "cloud_vision_model",
            "final_writes": "core_proposal_required",
            "direct_wordpress_write": False,
            "requires_human_visual_check": True,
        }
        return policy

    def _build_image_source_policy(self, request: RuntimeRequest) -> dict[str, object]:
        policy = self._apply_runtime_controls(dict(request.policy), request)
        policy["allow_fallback"] = False
        policy["execution_contract"] = {
            "ability_name": request.ability_name,
            "contract_version": request.contract_version,
            "profile_id": request.profile_id or IMAGE_SOURCE_PROFILE_ID,
            "execution_pattern": request.execution_pattern,
            "data_classification": request.data_classification,
            "storage_mode": request.storage_mode,
            "timeout_seconds": max(0, request.timeout_seconds),
            "retry_max": max(0, request.retry_max),
            "retention_ttl": max(0, request.retention_ttl),
            "provider_source": "cloud_managed",
            "candidate_contract": "image_candidate.v1",
            "final_writes": "core_proposal_required",
            "direct_wordpress_write": False,
        }
        return policy

    def _build_web_search_policy(self, request: RuntimeRequest) -> dict[str, object]:
        policy = self._apply_runtime_controls(dict(request.policy), request)
        policy["allow_fallback"] = False
        policy["execution_contract"] = {
            "ability_name": request.ability_name,
            "contract_version": request.contract_version,
            "profile_id": request.profile_id,
            "execution_pattern": request.execution_pattern,
            "data_classification": request.data_classification,
            "storage_mode": request.storage_mode,
            "timeout_seconds": max(0, request.timeout_seconds),
            "retry_max": max(0, request.retry_max),
            "retention_ttl": max(0, request.retention_ttl),
            "provider_source": "cloud_managed",
        }
        return policy

    def _merge_policy(
        self,
        default_policy: dict[str, object],
        request_policy: dict[str, object],
    ) -> dict[str, object]:
        merged = dict(default_policy)
        merged.update(normalize_runtime_request_policy(request_policy))
        return merged

    def _apply_runtime_controls(
        self,
        policy: dict[str, object],
        request: RuntimeRequest,
    ) -> dict[str, object]:
        updated = dict(policy)
        if request.timeout_seconds > 0:
            updated["timeout_seconds"] = max(0, int(request.timeout_seconds))
            updated["timeout_ms"] = max(0, int(request.timeout_seconds)) * 1000
        if request.retry_max > 0 or request.retry_max == 0:
            updated["retry_max"] = max(0, int(request.retry_max))
            updated["max_retries"] = max(0, int(request.retry_max))
        if request.retention_ttl > 0:
            updated["retention_ttl"] = max(0, int(request.retention_ttl))
        normalized_task_backend = normalize_runtime_task_backend(request.task_backend)
        if normalized_task_backend:
            updated["task_backend"] = normalized_task_backend
        updated["storage_mode"] = str(request.storage_mode or RUNTIME_STORAGE_MODE_RESULT_ONLY)
        if request.callback_url:
            updated["callback_url"] = str(request.callback_url or "").strip()
        return updated

    def _require_active_site(
        self,
        repository: RuntimeRepository,
        site_id: str,
    ) -> Any:
        site = repository.get_site(site_id)
        if site is None:
            raise RuntimeSiteNotProvisionedError(site_id)
        if site.status != SITE_STATUS_ACTIVE:
            raise RuntimeSiteInactiveError(site_id, site.status)
        return site

    def _enforce_batch_limits(
        self,
        *,
        request: RuntimeRequest,
        commercial_decision: dict[str, object],
    ) -> None:
        batch_limits = commercial_decision.get("batch_limits")
        batch_limits = batch_limits if isinstance(batch_limits, dict) else {}
        max_batch_items = max(0, self._coerce_int(batch_limits.get("max_batch_items"), default=0))
        requested_items = self._resolve_batch_request_size(request)
        if requested_items <= 0:
            return
        if max_batch_items <= 0:
            return
        if requested_items > max_batch_items:
            raise RuntimeBatchLimitExceededError(
                feature_id=self._resolve_batch_feature_id(request),
                requested_items=requested_items,
                limit=max_batch_items,
            )

    def _resolve_batch_request_size(self, request: RuntimeRequest) -> int:
        feature_id = self._resolve_batch_feature_id(request)
        input_payload = request.input_payload if isinstance(request.input_payload, dict) else {}
        if feature_id == "media_alt_completion":
            items = input_payload.get("items")
            if isinstance(items, list):
                return len([item for item in items if isinstance(item, dict)])
            return 0
        if feature_id == "media_nightly_image_optimize":
            items = input_payload.get("items")
            if isinstance(items, list):
                return len([item for item in items if isinstance(item, dict)])
            return max(0, self._coerce_int(input_payload.get("per_page"), default=0))
        if feature_id == "nightly_site_inspection":
            items = input_payload.get("items")
            if isinstance(items, list):
                return len([item for item in items if isinstance(item, dict)])
            snapshot = input_payload.get("snapshot")
            if isinstance(snapshot, dict) and isinstance(snapshot.get("items"), list):
                return len([item for item in snapshot["items"] if isinstance(item, dict)])
            return 0
        return 0

    def _resolve_batch_feature_id(self, request: RuntimeRequest) -> str:
        workflow_id = str(request.workflow_id or "").strip()
        if workflow_id in {"media_alt_completion", "media_nightly_image_optimize"}:
            return workflow_id
        ability_name = str(request.ability_name or "").strip()
        if ability_name in CLOUD_BATCH_RUNTIME_ABILITIES:
            return "nightly_site_inspection"
        if ability_name.endswith("/media_alt_completion"):
            return "media_alt_completion"
        if ability_name.endswith("/media_nightly_image_optimize"):
            return "media_nightly_image_optimize"
        return ""

    def _apply_routing_snapshot(
        self,
        merged_policy: dict[str, object],
        resolution: RoutingResolution,
    ) -> dict[str, object]:
        policy = dict(merged_policy)
        policy["routing_revision"] = resolution.revision
        policy["routing_candidates"] = [
            self._serialize_routing_candidate(candidate) for candidate in resolution.candidates
        ]
        return policy

    def _prefer_routing_candidate(
        self,
        resolution: RoutingResolution,
        policy: dict[str, object],
    ) -> RoutingResolution:
        preferred_instance_id = str(policy.get("preferred_instance_id") or "").strip()
        if not preferred_instance_id:
            return resolution
        candidates = list(resolution.candidates)
        preferred = [
            candidate for candidate in candidates if candidate.instance_id == preferred_instance_id
        ]
        if not preferred:
            return resolution
        resolution.candidates = preferred + [
            candidate for candidate in candidates if candidate.instance_id != preferred_instance_id
        ]
        return resolution

    def _apply_commercial_policy_overrides(
        self,
        merged_policy: dict[str, object],
        *,
        commercial_decision: dict[str, object],
    ) -> dict[str, object]:
        policy = dict(merged_policy)
        overrides = commercial_decision.get("runtime_policy_overrides")
        overrides = overrides if isinstance(overrides, dict) else {}
        for key, value in overrides.items():
            if (
                key == "task_backend"
                and isinstance(policy.get("task_backend"), dict)
                and isinstance(value, dict)
            ):
                task_backend = self._dict_or_empty(policy.get("task_backend"))
                task_backend.update(value)
                policy["task_backend"] = task_backend
                continue
            policy[key] = value
        policy = self.contract_validator.enforce_policy_within_execution_contract(policy)
        policy["commercial_policy"] = {
            "decision_code": str(commercial_decision.get("decision_code") or ""),
            "policy_actions": commercial_decision.get("policy_actions")
            if isinstance(commercial_decision.get("policy_actions"), list)
            else [],
            "runtime_policy_overrides": overrides,
        }
        return policy

    def _serialize_routing_candidate(self, candidate: RoutingCandidate) -> dict[str, object]:
        return {
            "provider_id": candidate.provider_id,
            "model_id": candidate.model_id,
            "instance_id": candidate.instance_id,
            "endpoint_variant": candidate.endpoint_variant,
            "region": candidate.region,
            "weight": candidate.weight,
            "health_status": candidate.health_status,
            "price_input": candidate.price_input,
            "price_output": candidate.price_output,
            "capability_tags": candidate.capability_tags,
        }

    def _deserialize_routing_candidates(self, policy: dict[str, object]) -> list[RoutingCandidate]:
        raw_candidates = policy.get("routing_candidates")
        if not isinstance(raw_candidates, list):
            return []

        candidates: list[RoutingCandidate] = []
        for item in raw_candidates:
            if not isinstance(item, dict):
                continue
            candidates.append(
                RoutingCandidate(
                    provider_id=str(item.get("provider_id") or ""),
                    model_id=str(item.get("model_id") or ""),
                    instance_id=str(item.get("instance_id") or ""),
                    endpoint_variant=str(item.get("endpoint_variant") or ""),
                    region=str(item.get("region") or ""),
                    weight=max(0, self._coerce_int(item.get("weight"), default=0)),
                    health_status=str(item.get("health_status") or "unknown"),
                    price_input=self._coerce_float(item.get("price_input")),
                    price_output=self._coerce_float(item.get("price_output")),
                    capability_tags=[
                        str(tag) for tag in item.get("capability_tags", []) if isinstance(tag, str)
                    ],
                )
            )
        return [
            candidate
            for candidate in candidates
            if candidate.provider_id and candidate.model_id and candidate.instance_id
        ]

    def _resolve_run_routing_candidate(self, run: RunRecord) -> RoutingCandidate:
        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
        candidates = self._deserialize_routing_candidates(policy)
        if candidates:
            return candidates[0]
        resolution = self.routing_service.resolve(
            profile_id=run.profile_id,
            execution_kind=(
                "vision" if self._is_image_context_evidence_run(run) else run.execution_kind
            ),
        )
        return resolution.selected_candidate

    def _should_enqueue(
        self,
        request: RuntimeRequest,
        merged_policy: dict[str, object],
    ) -> bool:
        if request.execution_pattern == "whole_run_offload":
            return self.run_projector.is_task_backend_enabled(merged_policy)
        return False

    def _build_execution_response(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        idempotent_replay: bool,
    ) -> RuntimeExecutionResponse:
        provider_calls = repository.list_provider_calls(run.run_id)
        failure_details = self.run_projector.build_failure_details(run, provider_calls)
        response_result = get_transient_runtime_result(run)
        if not isinstance(response_result, dict):
            response_result = run.result_json or {}
        response_result = project_media_artifact_lifecycle(
            response_result,
            session=repository.session,
            site_id=run.site_id,
            run_id=run.run_id,
        )
        result = build_analysis_result_envelope(
            response_result,
            ability_family=run.ability_family or "text",
            ability_name=run.ability_name or "",
            input_payload=run.input_json if isinstance(run.input_json, dict) else {},
        )
        return RuntimeExecutionResponse(
            run_id=run.run_id,
            canonical_run_id=run.canonical_run_id or "",
            status=run.status,
            trace_id=run.trace_id,
            profile_id=run.profile_id,
            provider_id=run.selected_provider_id or "",
            model_id=run.selected_model_id or "",
            instance_id=run.selected_instance_id or "",
            fallback_used=run.fallback_used,
            idempotent_replay=idempotent_replay,
            error_code=run.error_code or "",
            error_message=run.error_message or "",
            error_stage=failure_details.error_stage,
            retryable=failure_details.retryable,
            retry_exhausted=failure_details.retry_exhausted,
            provider_call_count=len(provider_calls),
            execution_context=self.run_projector.build_execution_context(run),
            task_backend=self.run_projector.build_task_backend_payload(run),
            run_lifecycle=self.run_projector.build_run_lifecycle(run),
            run_state=self.run_projector.build_run_state_payload(run, provider_calls),
            result=self._apply_analysis_envelope(result, run),
        )

    def _apply_analysis_envelope(self, result: dict[str, Any], run: Any) -> dict[str, Any]:
        if (run.ability_family or "text") != "openclaw":
            return result
        return build_analysis_result_envelope(
            result,
            ability_family=run.ability_family or "text",
            ability_name=run.ability_name or "",
            input_payload=run.input_payload if hasattr(run, "input_payload") else {},
        )

    def cleanup_expired_run_results(self, *, now: datetime | None = None) -> int:
        return self.run_lifecycle_service.cleanup_expired_run_results(now=now)

    def _serialize_runtime_diagnostic_run(self, run: RunRecord) -> dict[str, object]:
        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
        return {
            "run_id": run.run_id,
            "site_id": run.site_id,
            "status": run.status,
            "trace_id": run.trace_id,
            "ability_name": run.ability_name,
            "ability_family": run.ability_family,
            "profile_id": run.profile_id,
            "execution_pattern": self.run_projector.public_execution_pattern(run.execution_pattern),
            "callback_requested": self.run_projector.has_callback_target(policy),
            "callback_status": run.callback_status,
            "callback_attempt_count": max(0, int(run.callback_attempt_count or 0)),
            "callback_next_attempt_at": self.run_projector.serialize_timestamp(
                run.callback_next_attempt_at
            ),
            "callback_last_attempt_at": self.run_projector.serialize_timestamp(
                run.callback_last_attempt_at
            ),
            "callback_last_error_code": run.callback_last_error_code or "",
            "cancel_requested_at": self.run_projector.serialize_timestamp(run.cancel_requested_at),
            "canceled_at": self.run_projector.serialize_timestamp(run.canceled_at),
            "retention_expires_at": self.run_projector.serialize_timestamp(
                run.retention_expires_at
            ),
            "result_purged_at": self.run_projector.serialize_timestamp(run.result_purged_at),
            "started_at": self.run_projector.serialize_timestamp(run.started_at),
            "processing_started_at": self.run_projector.serialize_timestamp(
                run.processing_started_at
            ),
            "finished_at": self.run_projector.serialize_timestamp(run.finished_at),
            "suggested_actions": self._build_runtime_suggested_actions(run),
        }

    def _serialize_nightly_inspection_run_card(
        self,
        run: RunRecord,
        *,
        provider_calls: list[ProviderCallRecord],
    ) -> dict[str, object]:
        result = run.result_json if isinstance(run.result_json, dict) else {}
        summary = self._dict_or_empty(result.get("summary"))
        nightly_run_detail = self._dict_or_empty(result.get("nightly_run_detail"))
        operator_summary = self._dict_or_empty(nightly_run_detail.get("operator_summary"))
        retry_guidance = self._dict_or_empty(result.get("retry_guidance"))
        run_state = self.run_projector.build_run_state_payload(run, provider_calls)
        return {
            "run_id": run.run_id,
            "canonical_run_id": run.canonical_run_id or "",
            "site_id": run.site_id,
            "status": run.status,
            "result_status": str(result.get("status") or run.status),
            "worker_phase": str(result.get("worker_phase") or ""),
            "trace_id": run.trace_id,
            "idempotency_key": run.idempotency_key or "",
            "started_at": self.run_projector.serialize_timestamp(run.started_at),
            "processing_started_at": self.run_projector.serialize_timestamp(
                run.processing_started_at
            ),
            "finished_at": self.run_projector.serialize_timestamp(run.finished_at),
            "error_code": run.error_code or "",
            "error_message": run.error_message or "",
            "summary": {
                "items_scanned": self._coerce_int(summary.get("items_scanned"), default=0),
                "items_succeeded": self._coerce_int(
                    summary.get("items_succeeded"),
                    default=self._coerce_int(summary.get("items_scanned"), default=0),
                ),
                "items_failed": self._coerce_int(summary.get("items_failed"), default=0),
                "reviewable_count": self._coerce_int(
                    operator_summary.get("reviewable_count"),
                    default=0,
                ),
                "blocked_count": self._coerce_int(
                    operator_summary.get("blocked_count"),
                    default=0,
                ),
                "average_score": self._coerce_float(summary.get("average_score")) or 0.0,
                "score_version": str(summary.get("score_version") or ""),
            },
            "retry_guidance": {
                "available": bool(retry_guidance.get("available")),
                "retryable": bool(retry_guidance.get("retryable")),
                "retry_owner": str(retry_guidance.get("retry_owner") or "not_needed"),
                "operator_next_action": str(
                    retry_guidance.get("operator_next_action") or "review_morning_brief"
                ),
                "failed_action_ids": self._list_or_empty(retry_guidance.get("failed_action_ids"))[
                    :10
                ],
                "resubmit_requires_new_idempotency_key": bool(retry_guidance.get("retryable")),
            },
            "run_state": run_state,
            "core_handoff_summary": self._dict_or_empty(
                nightly_run_detail.get("core_handoff_summary")
            ),
            "read_only_boundary": {
                "cloud_role": "runtime_detail",
                "cloud_scheduler_truth": False,
                "direct_wordpress_write": False,
            },
        }

    def _is_queued_run_stale(self, run: RunRecord, current_time: datetime) -> bool:
        started_at = self.run_projector.normalize_timestamp(run.started_at)
        return run.status == "queued" and started_at <= (
            current_time - timedelta(seconds=RUNTIME_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS)
        )

    def _is_running_run_stale(self, run: RunRecord, current_time: datetime) -> bool:
        if run.status != "running" or run.processing_started_at is None:
            return False
        processing_started_at = self.run_projector.normalize_timestamp(run.processing_started_at)
        return processing_started_at <= (
            current_time - timedelta(seconds=RUNTIME_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS)
        )

    def _can_redeliver_callback(self, run: RunRecord, current_time: datetime) -> bool:
        if run.finished_at is None or not self.run_projector.has_callback_target(
            run.policy_json if isinstance(run.policy_json, dict) else {}
        ):
            return False
        if run.callback_status == RUN_CALLBACK_STATUS_FAILED:
            return True
        if (
            run.callback_status == RUN_CALLBACK_STATUS_PENDING
            and run.callback_next_attempt_at is not None
        ):
            return self.run_projector.normalize_timestamp(run.callback_next_attempt_at) <= (
                current_time - timedelta(seconds=RUNTIME_DIAGNOSTIC_CALLBACK_OVERDUE_AFTER_SECONDS)
            )
        return False

    def _build_runtime_suggested_actions(
        self,
        run: RunRecord,
    ) -> list[dict[str, object]]:
        current_time = datetime.now(UTC)
        actions: list[dict[str, object]] = []
        if self._is_queued_run_stale(run, current_time):
            actions.append(
                {
                    "action": "requeue_stale_queued",
                    "mode": "worker_auto",
                    "requires_operator_reason": False,
                    "requires_operator_evidence": False,
                }
            )
        if self._can_redeliver_callback(run, current_time):
            actions.append(
                {
                    "action": "redeliver_failed_callback",
                    "mode": (
                        "worker_auto"
                        if run.callback_status == RUN_CALLBACK_STATUS_PENDING
                        else "operator_repair"
                    ),
                    "requires_operator_reason": False,
                    "requires_operator_evidence": False,
                }
            )
        if self._is_running_run_stale(run, current_time):
            actions.append(
                {
                    "action": "mark_stale_running_failed",
                    "mode": "operator_only",
                    "requires_operator_reason": True,
                    "requires_operator_evidence": True,
                }
            )
        return actions

    def _decorate_abuse_guard_item(
        self,
        *,
        scope_kind: str,
        item: dict[str, object],
        observed_count: int,
        limit: int,
        signal_kind: str,
        near_limit_reason: str,
        exceeded_reason: str,
        event_code_breakdown: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        limit_ratio = self._calculate_limit_ratio(observed_count, limit)
        severity = self._classify_abuse_guard_severity(limit_ratio)
        reason_codes: list[str] = []
        if severity == "critical":
            reason_codes.append(exceeded_reason)
        elif severity == "attention":
            reason_codes.append(near_limit_reason)
        if signal_kind == "reject_storm":
            reason_codes.extend(
                self._derive_guard_breakdown_reason_codes(event_code_breakdown or [])
            )
        return {
            **item,
            "scope_kind": scope_kind,
            "signal_kind": signal_kind,
            "severity": severity,
            "observed_count": observed_count,
            "limit": limit,
            "limit_ratio": limit_ratio,
            "remaining_before_limit": max(limit - observed_count, 0),
            "exceeded_by": max(observed_count - limit, 0),
            "reason_codes": reason_codes,
            "event_code_breakdown": event_code_breakdown or [],
        }

    def _summarize_abuse_guard_pressure(
        self,
        items: list[dict[str, object]],
    ) -> dict[str, object]:
        return {
            "highest_severity": (
                "critical"
                if any(item["severity"] == "critical" for item in items)
                else "attention"
                if any(item["severity"] == "attention" for item in items)
                else "healthy"
            ),
            "healthy_count": sum(1 for item in items if item["severity"] == "healthy"),
            "attention_count": sum(1 for item in items if item["severity"] == "attention"),
            "critical_count": sum(1 for item in items if item["severity"] == "critical"),
        }

    def _calculate_limit_ratio(self, observed_count: int, limit: int) -> float:
        if limit <= 0:
            return 0.0
        return round(observed_count / limit, 3)

    def _classify_abuse_guard_severity(self, limit_ratio: float) -> str:
        if limit_ratio >= ABUSE_GUARD_CRITICAL_RATIO:
            return "critical"
        if limit_ratio >= ABUSE_GUARD_ATTENTION_RATIO:
            return "attention"
        return "healthy"

    def _derive_guard_breakdown_reason_codes(
        self,
        breakdown: list[dict[str, object]],
    ) -> list[str]:
        reason_codes: list[str] = []
        if any(item.get("event_code") == "auth.replay_blocked" for item in breakdown):
            reason_codes.append("rejects_include_replay_blocks")
        if any(item.get("event_code") == "auth.rate_limit_exceeded" for item in breakdown):
            reason_codes.append("rejects_include_rate_limits")
        if any(item.get("event_code") == "auth.payload_too_large" for item in breakdown):
            reason_codes.append("rejects_include_payload_limits")
        if any(item.get("event_code") == "auth.invalid_nonce" for item in breakdown):
            reason_codes.append("rejects_include_invalid_nonce")
        if any(item.get("event_code") == "auth.invalid_idempotency_key" for item in breakdown):
            reason_codes.append("rejects_include_invalid_idempotency_key")
        return reason_codes

    def _resolve_backlog_scope_id(
        self,
        run: RunRecord,
        scope_kind: str,
    ) -> str:
        if scope_kind == "site_id":
            return str(run.site_id or "unknown")
        if scope_kind == "ability_family":
            return str(run.ability_family or "unknown")
        if scope_kind == "execution_pattern":
            return str(run.execution_pattern or "unknown")
        return "unknown"

    def _resolve_backlog_age_seconds(
        self,
        run: RunRecord,
        current_time: datetime,
    ) -> int:
        if run.status == "running" and run.processing_started_at is not None:
            started_at = self.run_projector.normalize_timestamp(run.processing_started_at)
        else:
            started_at = self.run_projector.normalize_timestamp(run.started_at)
        return max(0, int((current_time - started_at).total_seconds()))

    def _summarize_backlog_status(
        self,
        ages: list[int],
        *,
        aging_after_seconds: int,
        stale_after_seconds: int,
    ) -> dict[str, object]:
        ordered = sorted(max(0, int(age)) for age in ages)
        fresh_count = sum(1 for age in ordered if age < aging_after_seconds)
        aging_count = sum(
            1 for age in ordered if age >= aging_after_seconds and age < stale_after_seconds
        )
        stale_count = sum(1 for age in ordered if age >= stale_after_seconds)
        if not ordered:
            state = "idle"
        elif stale_count > 0:
            state = "stale"
        elif aging_count > 0:
            state = "aging"
        else:
            state = "fresh_wave"
        return {
            "runs": len(ordered),
            "stale_runs": stale_count,
            "oldest_age_seconds": ordered[-1] if ordered else None,
            "p95_age_seconds": self._calculate_percentile(ordered, percentile=95),
            "state": state,
            "age_buckets": {
                "fresh": fresh_count,
                "aging": aging_count,
                "stale": stale_count,
            },
        }

    def _calculate_percentile(
        self,
        ordered_values: list[int],
        *,
        percentile: int,
    ) -> int | None:
        if not ordered_values:
            return None
        bounded = min(100, max(1, percentile))
        index = max(0, ((len(ordered_values) * bounded) - 1) // 100)
        return ordered_values[index]

    def _classify_backlog_pressure(
        self,
        *,
        queued_state: str,
        running_state: str,
    ) -> tuple[str, list[str]]:
        reasons: list[str] = []
        if queued_state == "stale":
            reasons.append("queue.stale")
        elif queued_state == "aging":
            reasons.append("queue.aging")
        if running_state == "stale":
            reasons.append("worker.stale")
        elif running_state == "aging":
            reasons.append("worker.aging")

        if any(reason.endswith(".stale") for reason in reasons):
            return "critical", reasons
        if reasons:
            return "attention", reasons
        return "healthy", []

    def _classify_backlog_bottleneck(
        self,
        *,
        queued_state: str,
        running_state: str,
    ) -> str:
        queued_abnormal = queued_state in {"aging", "stale"}
        running_abnormal = running_state in {"aging", "stale"}
        if queued_abnormal and running_abnormal:
            return "mixed"
        if queued_abnormal:
            return "queue_claiming_lag"
        if running_abnormal:
            return "worker_stall"
        return "healthy"

    def _classify_backlog_spread_state(
        self,
        *,
        pressured_scope_count: int,
        stale_scope_count: int,
        dominant_scope_share: float,
    ) -> str:
        if pressured_scope_count <= 0:
            return "none"
        if stale_scope_count <= 1 and dominant_scope_share >= 0.8:
            return "isolated"
        if pressured_scope_count == 1:
            return "isolated"
        return "multi_scope"

    def _classify_runtime_pressure(
        self,
        rules: tuple[tuple[str, bool, bool], ...],
    ) -> tuple[str, list[str]]:
        reasons: list[str] = []
        critical = False
        for code, active, is_critical in rules:
            if not active:
                continue
            reasons.append(code)
            critical = critical or is_critical
        if critical:
            return "critical", reasons
        if reasons:
            return "attention", reasons
        return "healthy", []

    def _calculate_age_seconds(
        self,
        current_time: datetime,
        serialized_timestamp: object,
    ) -> int | None:
        if not isinstance(serialized_timestamp, str) or not serialized_timestamp:
            return None
        try:
            parsed = datetime.fromisoformat(serialized_timestamp.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        age = current_time - parsed.astimezone(UTC)
        return max(0, int(age.total_seconds()))

    def _serialize_runtime_guard_event(self, event: RuntimeGuardEvent) -> dict[str, object]:
        return {
            "id": event.id,
            "auth_surface": event.auth_surface,
            "scope_kind": event.scope_kind,
            "scope_id": event.scope_id,
            "site_id": event.site_id or "",
            "key_id": event.key_id or "",
            "client_ref": event.client_ref or "",
            "event_code": event.event_code,
            "status_code": event.status_code,
            "method": event.method or "",
            "path": event.path or "",
            "trace_id": event.trace_id or "",
            "payload": event.payload_json or {},
            "created_at": self.run_projector.serialize_timestamp(event.created_at),
        }

    def _record_callback_dispatch_recovery(
        self,
        run: RunRecord,
        *,
        recovered_at: datetime,
    ) -> None:
        if run.callback_last_attempt_at is None:
            return
        last_attempt_at = self.run_projector.normalize_timestamp(run.callback_last_attempt_at)
        stale_for_seconds = max(0, int((recovered_at - last_attempt_at).total_seconds()))
        try:
            self.commercial_service.record_service_audit_event(
                audit_context=ServiceAuditContext(
                    trace_id=run.trace_id,
                    idempotency_key=str(run.idempotency_key or ""),
                    method="WORKER",
                    path="/internal/workers/runtime/callback-dispatch-recovery",
                    actor_kind="system_worker",
                    actor_ref="runtime_queue",
                ),
                event_kind="runtime.callback_dispatch_recovered",
                outcome="succeeded",
                account_id=run.account_id,
                site_id=run.site_id,
                subscription_id=run.subscription_id,
                plan_version_id=run.plan_version_id,
                scope_kind="runtime_run",
                scope_id=run.run_id,
                payload_json={
                    "run_id": run.run_id,
                    "trace_id": run.trace_id,
                    "callback_status": run.callback_status,
                    "callback_attempt_count": max(0, int(run.callback_attempt_count or 0)),
                    "callback_last_attempt_at": self.run_projector.serialize_timestamp(
                        run.callback_last_attempt_at
                    ),
                    "callback_next_attempt_at": self.run_projector.serialize_timestamp(
                        run.callback_next_attempt_at
                    ),
                    "callback_last_error_code": (
                        run.callback_last_error_code
                        or RUNTIME_CALLBACK_DISPATCH_LEASE_RECOVERY_ERROR_CODE
                    ),
                    "recovery_action": "requeue_pending_after_stale_dispatch_lease",
                    "stale_after_seconds": (RUNTIME_CALLBACK_DISPATCH_LEASE_RECOVERY_AFTER_SECONDS),
                    "stale_for_seconds": stale_for_seconds,
                },
            )
        except Exception:
            logger.exception(
                "runtime callback dispatch recovery audit failed: operation=%s "
                "run_id=%s site_id=%s trace_id=%s error_code=%s",
                "record_callback_dispatch_recovery_audit",
                run.run_id,
                run.site_id,
                run.trace_id,
                run.callback_last_error_code or RUNTIME_CALLBACK_DISPATCH_LEASE_RECOVERY_ERROR_CODE,
            )

    def _prepare_input_for_storage(
        self,
        input_payload: dict[str, Any],
        *,
        storage_mode: str,
    ) -> dict[str, Any]:
        if storage_mode in {
            RUNTIME_STORAGE_MODE_NO_STORE,
            RUNTIME_STORAGE_MODE_RESULT_ONLY,
        }:
            return {}
        return input_payload if isinstance(input_payload, dict) else {}

    def _get_execution_input_payload(self, run: RunRecord) -> dict[str, Any]:
        ciphertext = str(getattr(run, "execution_input_ciphertext", "") or "").strip()
        if ciphertext:
            return decrypt_runtime_execution_input(ciphertext, settings=self.settings)
        return run.input_json if isinstance(run.input_json, dict) else {}

    def _get_storage_mode(self, policy: dict[str, object]) -> str:
        storage_mode = str(policy.get("storage_mode") or RUNTIME_STORAGE_MODE_RESULT_ONLY)
        if storage_mode == RUNTIME_STORAGE_MODE_NO_STORE:
            return RUNTIME_STORAGE_MODE_NO_STORE
        if storage_mode == RUNTIME_STORAGE_MODE_FULL_STORE_WITH_TTL:
            return RUNTIME_STORAGE_MODE_FULL_STORE_WITH_TTL
        return RUNTIME_STORAGE_MODE_RESULT_ONLY

    def _coerce_int(self, value: object | None, *, default: int) -> int:
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

    def _coerce_float(self, value: object | None) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

    def _dict_or_empty(self, value: object | None) -> dict[str, object]:
        return value if isinstance(value, dict) else {}

    def _list_or_empty(self, value: object | None) -> list[object]:
        return value if isinstance(value, list) else []
