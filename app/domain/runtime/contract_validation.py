from __future__ import annotations

from typing import Any, Protocol

from app.domain.audio_generation.contracts import (
    AUDIO_GENERATION_ABILITIES,
    AudioGenerationContractViolation,
    validate_audio_generation_runtime_contract,
)
from app.domain.cloud_batch_runtime.contracts import (
    CLOUD_BATCH_RUNTIME_ABILITIES,
    CloudBatchRuntimeContractViolation,
    validate_cloud_batch_runtime_contract,
)
from app.domain.connector_runtime.contracts import (
    CONNECTOR_RUNTIME_CHANNEL,
    ConnectorRuntimeContractViolation,
    validate_connector_runtime_envelope,
    validate_connector_site_binding,
)
from app.domain.image_context_evidence.contracts import (
    IMAGE_CONTEXT_EVIDENCE_ABILITIES,
    ImageContextEvidenceContractViolation,
    validate_image_context_evidence_runtime_contract,
)
from app.domain.image_generation.contracts import (
    IMAGE_GENERATION_ABILITIES,
    ImageGenerationContractViolation,
    validate_image_generation_runtime_contract,
)
from app.domain.image_sources.contracts import (
    IMAGE_SOURCE_ABILITIES,
    ImageSourceContractViolation,
    validate_image_source_runtime_contract,
)
from app.domain.media_batch_plans.contracts import (
    MEDIA_BATCH_PLAN_ABILITIES,
    MediaBatchPlanContractViolation,
    validate_media_batch_plan_runtime_contract,
)
from app.domain.routing.models import RoutingResolution
from app.domain.runtime.data_guard import find_runtime_data_guard_finding
from app.domain.runtime.errors import RuntimeExecutionContractError
from app.domain.runtime.models import (
    FORBIDDEN_HOSTED_RUNTIME_DATA_CLASSIFICATIONS,
    RUNTIME_MAX_RETENTION_TTL,
    RUNTIME_MAX_RETRY_MAX,
    RUNTIME_MAX_TIMEOUT_SECONDS,
    RUNTIME_STORAGE_MODE_FULL_STORE_WITH_TTL,
    RUNTIME_STORAGE_MODE_NO_STORE,
    RUNTIME_STORAGE_MODE_RESULT_ONLY,
    SENSITIVE_RUNTIME_DATA_CLASSIFICATIONS,
    RuntimeRequest,
    normalize_runtime_task_backend,
)
from app.domain.site_knowledge.contracts import (
    SiteKnowledgeContractViolation,
    validate_site_knowledge_runtime_contract,
)
from app.domain.site_ops_analysis.contracts import (
    SITE_OPS_ANALYSIS_ABILITIES,
    SiteOpsAnalysisContractViolation,
    validate_site_ops_analysis_runtime_contract,
)
from app.domain.web_search.contracts import (
    WEB_SEARCH_ABILITIES,
    WebSearchContractViolation,
    validate_web_search_runtime_contract,
)
from app.domain.wordpress_ai_connector.contracts import (
    WP_AI_CONNECTOR_MAX_TIMEOUT_SECONDS,
    WordPressOperationContractViolation,
    validate_wordpress_operation_contract,
)


class CallbackTargetResolver(Protocol):
    def resolve_callback_target(
        self,
        *,
        site: Any,
        request: RuntimeRequest,
        callback_mode: str,
    ) -> dict[str, object]: ...


class RuntimeContractValidator:
    """Validates hosted runtime ingress without owning execution state."""

    def __init__(
        self,
        *,
        callback_target_resolver: CallbackTargetResolver,
    ) -> None:
        self.callback_target_resolver = callback_target_resolver

    def validate_runtime_data_handling_contract(self, request: RuntimeRequest) -> None:
        data_classification = str(request.data_classification or "").strip().lower()
        storage_mode = str(request.storage_mode or RUNTIME_STORAGE_MODE_RESULT_ONLY).strip()
        finding = find_runtime_data_guard_finding(request.input_payload)
        if finding is not None and finding.kind == "secret":
            raise RuntimeExecutionContractError(
                "runtime.secret_input_detected",
                f"runtime input contains secret-like data at '{finding.path}'",
            )
        if finding is not None and finding.kind == "pii" and data_classification != "pii":
            raise RuntimeExecutionContractError(
                "runtime.pii_classification_required",
                "runtime input appears to contain personal data and must use "
                "data_classification=pii",
            )
        if (
            data_classification in SENSITIVE_RUNTIME_DATA_CLASSIFICATIONS
            and storage_mode != RUNTIME_STORAGE_MODE_NO_STORE
        ):
            raise RuntimeExecutionContractError(
                "runtime.sensitive_data_requires_no_store",
                "pii and secret runtime requests must use storage_mode=no_store",
            )
        if data_classification in FORBIDDEN_HOSTED_RUNTIME_DATA_CLASSIFICATIONS:
            raise RuntimeExecutionContractError(
                "runtime.secret_data_forbidden",
                "secret-classified data is excluded from hosted runtime execution",
            )

    def validate_site_knowledge_contract(self, request: RuntimeRequest) -> None:
        try:
            validate_site_knowledge_runtime_contract(
                ability_name=request.ability_name,
                contract_version=request.contract_version,
                input_payload=request.input_payload,
            )
        except SiteKnowledgeContractViolation as error:
            raise RuntimeExecutionContractError(error.error_code, error.message) from error
        self._validate_common_limits(request)

    def validate_cloud_batch_runtime_contract(self, request: RuntimeRequest) -> None:
        try:
            validate_cloud_batch_runtime_contract(
                ability_name=request.ability_name,
                contract_version=request.contract_version,
                input_payload=request.input_payload,
            )
        except CloudBatchRuntimeContractViolation as error:
            raise RuntimeExecutionContractError(error.error_code, error.message) from error
        if request.ability_name not in CLOUD_BATCH_RUNTIME_ABILITIES:
            raise RuntimeExecutionContractError(
                "cloud_batch_runtime.unknown_ability",
                "cloud batch runtime ability_name is not supported",
            )
        if request.execution_pattern not in {"inline", "whole_run_offload"}:
            raise RuntimeExecutionContractError(
                "cloud_batch_runtime.execution_pattern_invalid",
                "cloud batch runtime supports inline or whole_run_offload execution",
            )
        self._validate_common_limits(request)

    def validate_image_source_contract(self, request: RuntimeRequest) -> None:
        try:
            validate_image_source_runtime_contract(
                ability_name=request.ability_name,
                contract_version=request.contract_version,
                input_payload=request.input_payload,
            )
        except ImageSourceContractViolation as error:
            raise RuntimeExecutionContractError(error.error_code, error.message) from error
        if request.ability_name not in IMAGE_SOURCE_ABILITIES:
            raise RuntimeExecutionContractError(
                "image_source.unknown_ability",
                "image source ability_name is not supported",
            )
        if request.execution_pattern not in {"inline", "step_offload"}:
            raise RuntimeExecutionContractError(
                "image_source.inline_required",
                "image source currently supports inline-compatible execution only",
            )
        self._validate_common_limits(request)

    def validate_audio_generation_contract(self, request: RuntimeRequest) -> None:
        try:
            validate_audio_generation_runtime_contract(
                ability_name=request.ability_name,
                contract_version=request.contract_version,
                input_payload=request.input_payload,
            )
        except AudioGenerationContractViolation as error:
            raise RuntimeExecutionContractError(error.error_code, error.message) from error
        if request.ability_name not in AUDIO_GENERATION_ABILITIES:
            raise RuntimeExecutionContractError(
                "audio_generation.unknown_ability",
                "audio generation ability_name is not supported",
            )
        if request.execution_pattern not in {"inline", "whole_run_offload"}:
            raise RuntimeExecutionContractError(
                "audio_generation.execution_pattern_invalid",
                "audio generation supports inline or whole_run_offload execution",
            )
        self._validate_common_limits(request)

    def validate_image_generation_contract(self, request: RuntimeRequest) -> None:
        try:
            validate_image_generation_runtime_contract(
                ability_name=request.ability_name,
                contract_version=request.contract_version,
                input_payload=request.input_payload,
            )
        except ImageGenerationContractViolation as error:
            raise RuntimeExecutionContractError(error.error_code, error.message) from error
        if request.ability_name not in IMAGE_GENERATION_ABILITIES:
            raise RuntimeExecutionContractError(
                "image_generation.unknown_ability",
                "image generation ability_name is not supported",
            )
        if request.execution_pattern not in {"inline", "whole_run_offload"}:
            raise RuntimeExecutionContractError(
                "image_generation.execution_pattern_invalid",
                "image generation supports inline or whole_run_offload execution",
            )
        self._validate_common_limits(request)

    def validate_media_batch_plan_contract(self, request: RuntimeRequest) -> None:
        try:
            validate_media_batch_plan_runtime_contract(
                ability_name=request.ability_name,
                contract_version=request.contract_version,
                input_payload=request.input_payload,
            )
        except MediaBatchPlanContractViolation as error:
            raise RuntimeExecutionContractError(error.error_code, error.message) from error
        if request.ability_name not in MEDIA_BATCH_PLAN_ABILITIES:
            raise RuntimeExecutionContractError(
                "media_batch_plan.unknown_ability",
                "media batch plan ability_name is not supported",
            )
        if request.execution_pattern != "inline":
            raise RuntimeExecutionContractError(
                "media_batch_plan.inline_required",
                "media batch plan currently supports inline execution only",
            )
        self._validate_common_limits(request)

    def validate_site_ops_analysis_contract(self, request: RuntimeRequest) -> None:
        try:
            validate_site_ops_analysis_runtime_contract(
                ability_name=request.ability_name,
                contract_version=request.contract_version,
                input_payload=request.input_payload,
            )
        except SiteOpsAnalysisContractViolation as error:
            raise RuntimeExecutionContractError(error.error_code, error.message) from error
        if request.ability_name not in SITE_OPS_ANALYSIS_ABILITIES:
            raise RuntimeExecutionContractError(
                "site_ops_analysis.unknown_ability",
                "site ops analysis ability_name is not supported",
            )
        if request.execution_pattern not in {"inline", "whole_run_offload"}:
            raise RuntimeExecutionContractError(
                "site_ops_analysis.execution_pattern_unsupported",
                "site ops analysis supports inline or whole_run_offload execution",
            )
        self._validate_common_limits(request)

    def validate_image_context_evidence_contract(self, request: RuntimeRequest) -> None:
        try:
            validate_image_context_evidence_runtime_contract(
                ability_name=request.ability_name,
                contract_version=request.contract_version,
                input_payload=request.input_payload,
            )
        except ImageContextEvidenceContractViolation as error:
            raise RuntimeExecutionContractError(error.error_code, error.message) from error
        if request.ability_name not in IMAGE_CONTEXT_EVIDENCE_ABILITIES:
            raise RuntimeExecutionContractError(
                "image_context_evidence.unknown_ability",
                "image context evidence ability_name is not supported",
            )
        if request.execution_pattern != "inline":
            raise RuntimeExecutionContractError(
                "image_context_evidence.inline_required",
                "image context evidence currently supports inline execution only",
            )
        self._validate_common_limits(request)

    def normalize_connector_runtime_envelope(
        self,
        *,
        ability_name: str,
        contract_version: str,
        channel: str,
        input_payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            envelope = validate_connector_runtime_envelope(
                ability_name=ability_name,
                contract_version=contract_version,
                input_payload=input_payload,
            )
        except ConnectorRuntimeContractViolation as error:
            raise RuntimeExecutionContractError(error.error_code, error.message) from error
        try:
            operation_contract = validate_wordpress_operation_contract(
                envelope["operation_contract"]
            )
        except WordPressOperationContractViolation as error:
            raise RuntimeExecutionContractError(error.error_code, error.message) from error
        envelope["operation_contract"] = operation_contract
        if channel != CONNECTOR_RUNTIME_CHANNEL:
            raise RuntimeExecutionContractError(
                "connector_runtime.channel_invalid",
                f"connector runtime requires channel={CONNECTOR_RUNTIME_CHANNEL}",
            )
        return envelope

    def validate_connector_runtime_contract(
        self,
        request: RuntimeRequest,
    ) -> dict[str, Any]:
        envelope = self.normalize_connector_runtime_envelope(
            ability_name=request.ability_name,
            contract_version=request.contract_version,
            channel=request.channel,
            input_payload=request.input_payload,
        )
        if request.timeout_seconds > WP_AI_CONNECTOR_MAX_TIMEOUT_SECONDS:
            raise RuntimeExecutionContractError(
                "connector_runtime.timeout_exceeded",
                "connector runtime timeout_seconds exceeds max allowed value "
                f"{WP_AI_CONNECTOR_MAX_TIMEOUT_SECONDS}",
            )
        if request.retry_max > 1:
            raise RuntimeExecutionContractError(
                "connector_runtime.retry_exceeded",
                "connector runtime retry_max exceeds max allowed value 1",
            )
        if request.retention_ttl > 86400:
            raise RuntimeExecutionContractError(
                "connector_runtime.retention_exceeded",
                "connector runtime retention_ttl exceeds max allowed value 86400",
            )
        return envelope

    def validate_connector_runtime_site_binding(
        self,
        envelope: dict[str, Any],
        *,
        site: Any,
    ) -> None:
        try:
            validate_connector_site_binding(
                envelope,
                site_url=str(site.site_url or ""),
                platform_kind=str(site.platform_kind or ""),
            )
        except ConnectorRuntimeContractViolation as error:
            raise RuntimeExecutionContractError(error.error_code, error.message) from error

    def validate_web_search_contract(self, request: RuntimeRequest) -> None:
        try:
            validate_web_search_runtime_contract(
                ability_name=request.ability_name,
                contract_version=request.contract_version,
                input_payload=request.input_payload,
            )
        except WebSearchContractViolation as error:
            raise RuntimeExecutionContractError(error.error_code, error.message) from error
        if request.ability_name not in WEB_SEARCH_ABILITIES:
            raise RuntimeExecutionContractError(
                "web_search.unknown_ability",
                "web search ability_name is not supported",
            )
        if request.execution_pattern != "inline":
            raise RuntimeExecutionContractError(
                "web_search.inline_required",
                "web search currently supports inline execution only",
            )
        self._validate_common_limits(request)

    def build_execution_contract(
        self,
        *,
        request: RuntimeRequest,
        resolution: RoutingResolution,
        site: Any,
    ) -> dict[str, object]:
        if not str(request.ability_name or "").strip():
            raise RuntimeExecutionContractError(
                "runtime.contract_invalid",
                "ability_name is required for hosted runtime execution",
            )
        if not str(request.contract_version or "").strip():
            raise RuntimeExecutionContractError(
                "runtime.contract_version_required",
                "contract_version is required for hosted runtime execution",
            )
        if request.profile_id != resolution.profile_id:
            raise RuntimeExecutionContractError(
                "runtime.contract_profile_mismatch",
                "profile_id does not match the resolved routing profile",
            )
        self._validate_common_limits(request)
        if (
            request.storage_mode == RUNTIME_STORAGE_MODE_FULL_STORE_WITH_TTL
            and request.retention_ttl <= 0
        ):
            raise RuntimeExecutionContractError(
                "runtime.contract_retention_required",
                "full_store_with_ttl requires a positive retention_ttl",
            )

        task_backend = normalize_runtime_task_backend(request.task_backend)
        callback_mode = str(task_backend.get("callback_mode") or "")
        callback_target = self.callback_target_resolver.resolve_callback_target(
            site=site,
            request=request,
            callback_mode=callback_mode,
        )
        if request.execution_pattern == "whole_run_offload" and not bool(
            task_backend.get("enabled")
        ):
            raise RuntimeExecutionContractError(
                "runtime.contract_task_backend_required",
                "whole_run_offload requires task_backend.enabled=true",
            )

        return {
            "ability_name": request.ability_name,
            "contract_version": request.contract_version,
            "profile_id": resolution.profile_id,
            "execution_pattern": request.execution_pattern,
            "data_classification": request.data_classification,
            "storage_mode": request.storage_mode,
            "timeout_seconds": max(0, request.timeout_seconds),
            "retry_max": max(0, request.retry_max),
            "retention_ttl": max(0, request.retention_ttl),
            "task_backend": task_backend,
            "callback_target": callback_target,
        }

    def apply_execution_contract(
        self,
        merged_policy: dict[str, object],
        *,
        execution_contract: dict[str, object],
    ) -> dict[str, object]:
        policy = dict(merged_policy)
        timeout_seconds = max(
            0,
            self._coerce_int(execution_contract.get("timeout_seconds"), default=0),
        )
        retry_max = max(
            0,
            self._coerce_int(execution_contract.get("retry_max"), default=0),
        )
        retention_ttl = max(
            0,
            self._coerce_int(execution_contract.get("retention_ttl"), default=0),
        )
        task_backend = execution_contract.get("task_backend")
        callback_target = execution_contract.get("callback_target")
        callback_target = callback_target if isinstance(callback_target, dict) else {}

        if timeout_seconds > 0:
            policy["timeout_seconds"] = timeout_seconds
            policy["timeout_ms"] = timeout_seconds * 1000
        if retry_max > 0 or execution_contract.get("retry_max") == 0:
            policy["retry_max"] = retry_max
            policy["max_retries"] = retry_max
        if retention_ttl > 0:
            policy["retention_ttl"] = retention_ttl
        if isinstance(task_backend, dict) and task_backend:
            policy["task_backend"] = task_backend
        policy["storage_mode"] = str(
            execution_contract.get("storage_mode") or RUNTIME_STORAGE_MODE_RESULT_ONLY
        )
        policy["execution_contract"] = {
            "ability_name": str(execution_contract.get("ability_name") or ""),
            "contract_version": str(execution_contract.get("contract_version") or ""),
            "profile_id": str(execution_contract.get("profile_id") or ""),
            "execution_pattern": str(execution_contract.get("execution_pattern") or ""),
            "data_classification": str(execution_contract.get("data_classification") or ""),
            "storage_mode": str(execution_contract.get("storage_mode") or ""),
            "timeout_seconds": timeout_seconds,
            "retry_max": retry_max,
            "retention_ttl": retention_ttl,
            "task_backend": task_backend if isinstance(task_backend, dict) else {},
        }
        if callback_target:
            policy["runtime_callback"] = callback_target
            policy.pop("callback_url", None)
        else:
            policy.pop("runtime_callback", None)
            policy.pop("callback_url", None)
        return policy

    def enforce_policy_within_execution_contract(
        self,
        policy: dict[str, object],
    ) -> dict[str, object]:
        execution_contract = policy.get("execution_contract")
        execution_contract = execution_contract if isinstance(execution_contract, dict) else {}
        if not execution_contract:
            return policy

        timeout_seconds = max(0, self._coerce_int(policy.get("timeout_seconds"), default=0))
        contract_timeout_seconds = max(
            0,
            self._coerce_int(execution_contract.get("timeout_seconds"), default=0),
        )
        if contract_timeout_seconds > 0 and timeout_seconds > contract_timeout_seconds:
            raise RuntimeExecutionContractError(
                "runtime.contract_override_out_of_range",
                "commercial override may not increase timeout_seconds beyond the "
                "execution contract",
            )

        retry_max = max(0, self._coerce_int(policy.get("retry_max"), default=0))
        contract_retry_max = max(
            0,
            self._coerce_int(execution_contract.get("retry_max"), default=0),
        )
        if retry_max > contract_retry_max:
            raise RuntimeExecutionContractError(
                "runtime.contract_override_out_of_range",
                "commercial override may not increase retry_max beyond the execution contract",
            )

        retention_ttl = max(0, self._coerce_int(policy.get("retention_ttl"), default=0))
        contract_retention_ttl = max(
            0,
            self._coerce_int(execution_contract.get("retention_ttl"), default=0),
        )
        if contract_retention_ttl > 0 and retention_ttl > contract_retention_ttl:
            raise RuntimeExecutionContractError(
                "runtime.contract_override_out_of_range",
                "commercial override may not increase retention_ttl beyond the execution contract",
            )

        contract_task_backend = execution_contract.get("task_backend")
        contract_task_backend = (
            contract_task_backend if isinstance(contract_task_backend, dict) else {}
        )
        task_backend = policy.get("task_backend")
        task_backend = task_backend if isinstance(task_backend, dict) else {}

        if bool(task_backend.get("enabled")) and not bool(contract_task_backend.get("enabled")):
            raise RuntimeExecutionContractError(
                "runtime.contract_override_out_of_range",
                "commercial override may not enable task_backend when the execution "
                "contract disabled it",
            )
        if not bool(task_backend.get("enabled")):
            return policy
        contract_mode = str(contract_task_backend.get("mode") or "")
        override_mode = str(task_backend.get("mode") or "")
        if contract_mode and override_mode and override_mode != contract_mode:
            raise RuntimeExecutionContractError(
                "runtime.contract_override_out_of_range",
                "commercial override may not replace task_backend.mode outside the "
                "execution contract",
            )
        contract_callback_mode = str(contract_task_backend.get("callback_mode") or "")
        override_callback_mode = str(task_backend.get("callback_mode") or "")
        if contract_callback_mode and override_callback_mode not in {
            "",
            contract_callback_mode,
        }:
            raise RuntimeExecutionContractError(
                "runtime.contract_override_out_of_range",
                "commercial override may not widen task_backend.callback_mode beyond "
                "the execution contract",
            )
        return policy

    @staticmethod
    def _validate_common_limits(request: RuntimeRequest) -> None:
        if request.timeout_seconds > RUNTIME_MAX_TIMEOUT_SECONDS:
            raise RuntimeExecutionContractError(
                "runtime.contract_timeout_exceeded",
                f"timeout_seconds exceeds max allowed value {RUNTIME_MAX_TIMEOUT_SECONDS}",
            )
        if request.retry_max > RUNTIME_MAX_RETRY_MAX:
            raise RuntimeExecutionContractError(
                "runtime.contract_retry_exceeded",
                f"retry_max exceeds max allowed value {RUNTIME_MAX_RETRY_MAX}",
            )
        if request.retention_ttl > RUNTIME_MAX_RETENTION_TTL:
            raise RuntimeExecutionContractError(
                "runtime.contract_retention_exceeded",
                f"retention_ttl exceeds max allowed value {RUNTIME_MAX_RETENTION_TTL}",
            )

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
