from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.adapters.providers.base import (
    IMAGE_GENERATION_PROVIDER_ERROR_MESSAGE,
    VISION_PROVIDER_ERROR_MESSAGE,
    ProviderAdapter,
    ProviderExecutionError,
    ProviderExecutionRequest,
    ProviderExecutionResult,
    ProviderMediaCandidate,
)
from app.adapters.repositories.runtime_repository import RuntimeRepository
from app.core.error_taxonomy import get_error_taxonomy
from app.core.models import ProviderCallRecord, RunRecord


@dataclass(frozen=True, slots=True)
class ProviderCallEvidenceCommand:
    provider_id: str
    model_id: str
    instance_id: str
    region: str
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost: float
    retry_count: int
    fallback_used: bool
    error_code: str | None = None


class ProviderUsageRecorder(Protocol):
    def record_provider_call_usage(
        self,
        *,
        session: Session,
        run: RunRecord,
        provider_call: ProviderCallRecord,
        usage_context: dict[str, object] | None = None,
    ) -> None: ...


class ProviderCandidate(Protocol):
    provider_id: str
    model_id: str
    instance_id: str
    endpoint_variant: str
    region: str
    price_input: float | None
    price_output: float | None


@dataclass(frozen=True, slots=True)
class ProviderOutputDecision:
    accepted: bool
    output: dict[str, Any]
    error_code: str = ""
    error_message: str = ""


class ProviderOutputFinalizationError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


class RuntimeRunController(Protocol):
    def cancel_if_requested(
        self,
        *,
        repository: RuntimeRepository,
        run: RunRecord,
    ) -> bool: ...

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


class ProviderInputPreprocessor(Protocol):
    def __call__(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any],
        policy: dict[str, object],
    ) -> dict[str, Any]: ...


class ProviderOutputPreparer(Protocol):
    def __call__(
        self,
        run: RunRecord,
        *,
        input_payload: dict[str, Any],
        provider_output: dict[str, Any],
    ) -> ProviderOutputDecision: ...


class ProviderOutputFinalizer(Protocol):
    def __call__(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
        input_payload: dict[str, Any],
        provider_output: dict[str, Any],
        media_candidates: tuple[ProviderMediaCandidate, ...],
        policy: dict[str, object],
        finalization_context: object | None,
    ) -> dict[str, Any]: ...


class RuntimeProviderExecutionService:
    def __init__(
        self,
        *,
        usage_recorder: ProviderUsageRecorder,
        providers: Mapping[str, ProviderAdapter] | None = None,
        run_controller: RuntimeRunController | None = None,
        input_preprocessor: ProviderInputPreprocessor | None = None,
        output_preparer: ProviderOutputPreparer | None = None,
        output_finalizer: ProviderOutputFinalizer | None = None,
    ) -> None:
        self.usage_recorder = usage_recorder
        self.providers = providers or {}
        self.run_controller = run_controller
        self.input_preprocessor = input_preprocessor
        self.output_preparer = output_preparer
        self.output_finalizer = output_finalizer

    @staticmethod
    def execute_provider(
        provider: ProviderAdapter,
        request: ProviderExecutionRequest,
    ) -> ProviderExecutionResult:
        return provider.execute(request)

    def record_provider_call(
        self,
        *,
        repository: RuntimeRepository,
        run: RunRecord,
        command: ProviderCallEvidenceCommand,
        usage_context: dict[str, object] | None = None,
    ) -> ProviderCallRecord:
        provider_call = repository.record_provider_call(
            run_id=run.run_id,
            provider_id=command.provider_id,
            model_id=command.model_id,
            instance_id=command.instance_id,
            region=command.region,
            latency_ms=command.latency_ms,
            tokens_in=command.tokens_in,
            tokens_out=command.tokens_out,
            cost=command.cost,
            retry_count=command.retry_count,
            fallback_used=command.fallback_used,
            error_code=command.error_code,
        )
        self.usage_recorder.record_provider_call_usage(
            session=repository.session,
            run=run,
            provider_call=provider_call,
            usage_context=usage_context,
        )
        return provider_call

    def execute_candidate_chain(
        self,
        *,
        repository: RuntimeRepository,
        run: RunRecord,
        candidates: Sequence[ProviderCandidate],
        input_payload: dict[str, Any],
        finalization_context: object | None = None,
    ) -> None:
        if (
            self.run_controller is None
            or self.input_preprocessor is None
            or self.output_preparer is None
            or self.output_finalizer is None
        ):
            raise RuntimeError("provider candidate execution callbacks are not configured")

        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
        input_payload = self.input_preprocessor(
            run,
            repository=repository,
            input_payload=input_payload,
            policy=policy,
        )
        if run.status == "failed":
            return
        allow_fallback = bool(policy.get("allow_fallback", True))
        max_retries = max(0, self._coerce_int(policy.get("max_retries"), default=0))
        timeout_ms = max(1, self._coerce_int(policy.get("timeout_ms"), default=30_000))
        last_error_code = "runtime.execute_failed"
        last_error_message = "runtime execution failed"
        last_fallback_used = False
        last_provider_id = ""
        last_model_id = ""
        last_instance_id = ""

        if self.run_controller.cancel_if_requested(repository=repository, run=run):
            return

        for candidate_index, candidate in enumerate(candidates):
            fallback_used = candidate_index > 0
            for retry_count in range(max_retries + 1):
                if self.run_controller.cancel_if_requested(repository=repository, run=run):
                    return
                last_fallback_used = fallback_used
                last_provider_id = candidate.provider_id
                last_model_id = candidate.model_id
                last_instance_id = candidate.instance_id
                provider = self.providers.get(candidate.provider_id)
                if provider is None:
                    last_error_code = "runtime.provider_not_configured"
                    last_error_message = (
                        f"provider adapter is not configured for {candidate.provider_id}"
                    )
                    if allow_fallback and get_error_taxonomy(last_error_code).fallback_eligible:
                        break
                    self.run_controller.fail_run(
                        repository,
                        run,
                        error_code=last_error_code,
                        error_message=last_error_message,
                        provider_id=candidate.provider_id,
                        model_id=candidate.model_id,
                        instance_id=candidate.instance_id,
                        fallback_used=fallback_used,
                    )
                    return

                try:
                    provider_result = provider.execute(
                        ProviderExecutionRequest(
                            run_id=run.run_id,
                            site_id=run.site_id,
                            ability_name=run.ability_name,
                            profile_id=run.profile_id,
                            execution_kind=run.execution_kind,
                            model_id=candidate.model_id,
                            instance_id=candidate.instance_id,
                            endpoint_variant=candidate.endpoint_variant,
                            trace_id=run.trace_id,
                            input_payload=input_payload,
                            policy=policy,
                            timeout_ms=timeout_ms,
                            price_input=candidate.price_input,
                            price_output=candidate.price_output,
                            retry_count=retry_count,
                        )
                    )
                except ProviderExecutionError as error:
                    self._record_attempt_error(
                        repository=repository,
                        run=run,
                        candidate=candidate,
                        retry_count=retry_count,
                        fallback_used=fallback_used,
                        timeout_ms=timeout_ms,
                        error=error,
                    )
                    last_error_code = error.error_code
                    last_error_message = (
                        IMAGE_GENERATION_PROVIDER_ERROR_MESSAGE
                        if run.execution_kind == "image_generation"
                        else (
                            VISION_PROVIDER_ERROR_MESSAGE
                            if run.execution_kind == "vision"
                            else error.message
                        )
                    )
                    taxonomy = get_error_taxonomy(error.error_code)
                    if retry_count < max_retries and error.retryable and taxonomy.retryable:
                        continue
                    if allow_fallback and taxonomy.fallback_eligible:
                        break
                    self.run_controller.fail_run(
                        repository,
                        run,
                        error_code=last_error_code,
                        error_message=last_error_message,
                        provider_id=candidate.provider_id,
                        model_id=candidate.model_id,
                        instance_id=candidate.instance_id,
                        fallback_used=fallback_used,
                    )
                    return

                decision = self.output_preparer(
                    run,
                    input_payload=input_payload,
                    provider_output=provider_result.output,
                )
                if not decision.accepted:
                    last_error_code = decision.error_code
                    last_error_message = decision.error_message
                    self._record_attempt_result(
                        repository=repository,
                        run=run,
                        candidate=candidate,
                        retry_count=retry_count,
                        fallback_used=fallback_used,
                        provider_result=provider_result,
                        error_code=decision.error_code,
                    )
                    if allow_fallback:
                        break
                    self.run_controller.fail_run(
                        repository,
                        run,
                        error_code=last_error_code,
                        error_message=last_error_message,
                        provider_id=candidate.provider_id,
                        model_id=candidate.model_id,
                        instance_id=candidate.instance_id,
                        fallback_used=fallback_used,
                    )
                    return

                self._record_attempt_result(
                    repository=repository,
                    run=run,
                    candidate=candidate,
                    retry_count=retry_count,
                    fallback_used=fallback_used,
                    provider_result=provider_result,
                )
                try:
                    durable_result = self.output_finalizer(
                        run,
                        repository=repository,
                        input_payload=input_payload,
                        provider_output=decision.output,
                        media_candidates=provider_result.media_candidates,
                        policy=policy,
                        finalization_context=finalization_context,
                    )
                except ProviderOutputFinalizationError as error:
                    self.run_controller.fail_run(
                        repository,
                        run,
                        error_code=error.error_code,
                        error_message=error.message,
                        provider_id=candidate.provider_id,
                        model_id=candidate.model_id,
                        instance_id=candidate.instance_id,
                        fallback_used=fallback_used,
                    )
                    return
                self.run_controller.succeed_run(
                    repository,
                    run,
                    result_json=durable_result,
                    provider_id=candidate.provider_id,
                    model_id=candidate.model_id,
                    instance_id=candidate.instance_id,
                    fallback_used=fallback_used,
                )
                return
            if not allow_fallback:
                break

        self.run_controller.fail_run(
            repository,
            run,
            error_code=last_error_code,
            error_message=last_error_message,
            provider_id=last_provider_id or None,
            model_id=last_model_id or None,
            instance_id=last_instance_id or None,
            fallback_used=last_fallback_used,
        )

    def _record_attempt_error(
        self,
        *,
        repository: RuntimeRepository,
        run: RunRecord,
        candidate: ProviderCandidate,
        retry_count: int,
        fallback_used: bool,
        timeout_ms: int,
        error: ProviderExecutionError,
    ) -> None:
        self.record_provider_call(
            repository=repository,
            run=run,
            command=ProviderCallEvidenceCommand(
                provider_id=candidate.provider_id,
                model_id=candidate.model_id,
                instance_id=candidate.instance_id,
                region=candidate.region,
                latency_ms=timeout_ms if error.error_code == "provider.timeout" else 0,
                tokens_in=max(0, int(error.tokens_in or 0)),
                tokens_out=max(0, int(error.tokens_out or 0)),
                cost=max(0.0, float(error.cost or 0.0)),
                retry_count=retry_count,
                fallback_used=fallback_used,
                error_code=error.error_code,
            ),
        )

    def _record_attempt_result(
        self,
        *,
        repository: RuntimeRepository,
        run: RunRecord,
        candidate: ProviderCandidate,
        retry_count: int,
        fallback_used: bool,
        provider_result: ProviderExecutionResult,
        error_code: str | None = None,
    ) -> None:
        self.record_provider_call(
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
                retry_count=retry_count,
                fallback_used=fallback_used,
                error_code=error_code,
            ),
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
