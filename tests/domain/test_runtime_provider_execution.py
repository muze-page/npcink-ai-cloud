from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.adapters.providers.base import (
    IMAGE_GENERATION_PROVIDER_ERROR_MESSAGE,
    VISION_PROVIDER_ERROR_MESSAGE,
    ProviderCatalogSnapshot,
    ProviderExecutionError,
    ProviderExecutionRequest,
    ProviderExecutionResult,
    ProviderMediaCandidate,
)
from app.adapters.repositories.runtime_repository import RuntimeRepository
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import ProviderCallRecord, RunRecord, Site
from app.domain.runtime.provider_execution import (
    ProviderCallEvidenceCommand,
    ProviderOutputDecision,
    ProviderOutputFinalizationError,
    RuntimeProviderExecutionService,
)


class RecordingUsageRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def record_provider_call_usage(
        self,
        *,
        session: Session,
        run: RunRecord,
        provider_call: ProviderCallRecord,
        usage_context: dict[str, object] | None = None,
    ) -> None:
        self.calls.append(
            {
                "session": session,
                "run": run,
                "provider_call": provider_call,
                "usage_context": usage_context,
            }
        )


@dataclass(frozen=True, slots=True)
class Candidate:
    provider_id: str
    model_id: str
    instance_id: str
    endpoint_variant: str = "test"
    region: str = "test-region"
    price_input: float | None = None
    price_output: float | None = None


class SequenceProvider:
    display_name = "Sequence Provider"
    adapter_type = "test"

    def __init__(self, provider_id: str, outcomes: list[object]) -> None:
        self.provider_id = provider_id
        self.outcomes = outcomes
        self.attempts: list[int] = []

    def fetch_catalog(self) -> ProviderCatalogSnapshot:
        raise AssertionError("catalog is not used by provider execution tests")

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        self.attempts.append(request.retry_count)
        outcome = self.outcomes[len(self.attempts) - 1]
        if isinstance(outcome, ProviderExecutionError):
            raise outcome
        assert isinstance(outcome, ProviderExecutionResult)
        return outcome


class RecordingRunController:
    def __init__(self, *, cancel_on_check: int = 0) -> None:
        self.cancel_on_check = cancel_on_check
        self.cancel_checks = 0

    def cancel_if_requested(
        self,
        *,
        repository: RuntimeRepository,
        run: RunRecord,
    ) -> bool:
        self.cancel_checks += 1
        if self.cancel_on_check == self.cancel_checks:
            repository.mark_run_canceled(run)
            return True
        return False

    def fail_run(
        self,
        repository: RuntimeRepository,
        run: RunRecord,
        **kwargs: Any,
    ) -> RunRecord:
        return repository.mark_run_failed(run, **kwargs)

    def succeed_run(
        self,
        repository: RuntimeRepository,
        run: RunRecord,
        **kwargs: Any,
    ) -> RunRecord:
        return repository.mark_run_succeeded(run, **kwargs)


@pytest.fixture
def database_url(tmp_path: Path) -> Iterator[str]:
    url = f"sqlite+pysqlite:///{tmp_path / 'runtime-provider-execution.sqlite3'}"
    init_schema(url)
    with get_session(url) as session:
        session.add(Site(site_id="site_alpha", name="Site Alpha", status="active"))
        session.commit()
    yield url
    dispose_engine(url)


def create_run(
    repository: RuntimeRepository,
    *,
    run_id: str,
    policy: dict[str, Any] | None = None,
    execution_kind: str = "text",
) -> RunRecord:
    return repository.create_run(
        run_id=run_id,
        site_id="site_alpha",
        account_id=None,
        subscription_id=None,
        plan_version_id=None,
        ability_name="npcink/test-provider-evidence",
        ability_family="text",
        skill_id="",
        workflow_id="",
        contract_version="v1",
        channel="openapi",
        execution_kind=execution_kind,
        execution_tier="cloud",
        execution_pattern="inline",
        data_classification="internal",
        profile_id="text.balanced",
        canonical_run_id=None,
        status="running",
        idempotency_key=f"idem-{run_id}",
        request_fingerprint=f"fingerprint-{run_id}",
        trace_id=f"trace-{run_id}",
        input_json={"messages": []},
        execution_input_ciphertext=None,
        policy_json=policy or {},
    )


def test_records_success_evidence_before_usage_with_all_fields(database_url: str) -> None:
    usage_recorder = RecordingUsageRecorder()
    service = RuntimeProviderExecutionService(usage_recorder=usage_recorder)
    command = ProviderCallEvidenceCommand(
        provider_id="provider_primary",
        model_id="model_primary",
        instance_id="instance_primary",
        region="test-region",
        latency_ms=73,
        tokens_in=11,
        tokens_out=7,
        cost=0.42,
        retry_count=1,
        fallback_used=True,
    )

    with get_session(database_url) as session:
        repository = RuntimeRepository(session)
        run = create_run(repository, run_id="run_success")
        provider_call = service.record_provider_call(
            repository=repository,
            run=run,
            command=command,
        )

        assert provider_call.id is not None
        assert (
            provider_call.run_id,
            provider_call.provider_id,
            provider_call.model_id,
            provider_call.instance_id,
            provider_call.region,
            provider_call.latency_ms,
            provider_call.tokens_in,
            provider_call.tokens_out,
            provider_call.cost,
            provider_call.retry_count,
            provider_call.fallback_used,
            provider_call.error_code,
        ) == (
            "run_success",
            "provider_primary",
            "model_primary",
            "instance_primary",
            "test-region",
            73,
            11,
            7,
            0.42,
            1,
            True,
            None,
        )
        assert usage_recorder.calls == [
            {
                "session": session,
                "run": run,
                "provider_call": provider_call,
                "usage_context": None,
            }
        ]
        assert repository.list_provider_calls(run.run_id) == [provider_call]


def test_records_error_evidence_and_passes_usage_context_unchanged(database_url: str) -> None:
    usage_recorder = RecordingUsageRecorder()
    service = RuntimeProviderExecutionService(usage_recorder=usage_recorder)
    usage_context = {
        "provider": "managed_search",
        "managed_source": "web_search",
        "intent": "research",
    }

    with get_session(database_url) as session:
        repository = RuntimeRepository(session)
        run = create_run(repository, run_id="run_error")
        provider_call = service.record_provider_call(
            repository=repository,
            run=run,
            command=ProviderCallEvidenceCommand(
                provider_id="provider_search",
                model_id="model_search",
                instance_id="instance_search",
                region="search-region",
                latency_ms=901,
                tokens_in=3,
                tokens_out=0,
                cost=0.17,
                retry_count=2,
                fallback_used=False,
                error_code="provider.upstream_unavailable",
            ),
            usage_context=usage_context,
        )

        assert provider_call.error_code == "provider.upstream_unavailable"
        assert provider_call.latency_ms == 901
        assert provider_call.tokens_in == 3
        assert provider_call.tokens_out == 0
        assert provider_call.cost == 0.17
        assert provider_call.retry_count == 2
        assert provider_call.fallback_used is False
        assert usage_recorder.calls[0]["session"] is session
        assert usage_recorder.calls[0]["run"] is run
        assert usage_recorder.calls[0]["provider_call"] is provider_call
        assert usage_recorder.calls[0]["usage_context"] is usage_context


def provider_success(text: str) -> ProviderExecutionResult:
    return ProviderExecutionResult(
        output={"output_text": text},
        latency_ms=25,
        tokens_in=4,
        tokens_out=3,
        cost=0.2,
    )


def execution_service(
    *,
    providers: dict[str, SequenceProvider],
    controller: RecordingRunController,
    output_preparer: Any = None,
    output_finalizer: Any = None,
    usage_recorder: RecordingUsageRecorder | None = None,
) -> RuntimeProviderExecutionService:
    return RuntimeProviderExecutionService(
        usage_recorder=usage_recorder or RecordingUsageRecorder(),
        providers=providers,
        run_controller=controller,
        input_preprocessor=lambda run, **kwargs: kwargs["input_payload"],
        output_preparer=output_preparer
        or (
            lambda run, **kwargs: ProviderOutputDecision(
                accepted=True,
                output=kwargs["provider_output"],
            )
        ),
        output_finalizer=output_finalizer or (lambda run, **kwargs: kwargs["provider_output"]),
    )


def test_candidate_engine_retries_then_falls_back_and_succeeds(database_url: str) -> None:
    primary = SequenceProvider(
        "primary",
        [
            ProviderExecutionError("provider.rate_limited", "retry"),
            ProviderExecutionError("provider.rate_limited", "fallback"),
        ],
    )
    fallback = SequenceProvider("fallback", [provider_success("fallback result")])
    controller = RecordingRunController()
    service = execution_service(
        providers={"primary": primary, "fallback": fallback},
        controller=controller,
    )

    with get_session(database_url) as session:
        repository = RuntimeRepository(session)
        run = create_run(
            repository,
            run_id="run_retry_fallback",
            policy={"allow_fallback": True, "max_retries": 1, "timeout_ms": 500},
        )
        service.execute_candidate_chain(
            repository=repository,
            run=run,
            candidates=[
                Candidate("primary", "model-primary", "instance-primary"),
                Candidate("fallback", "model-fallback", "instance-fallback"),
            ],
            input_payload={"messages": []},
        )

        assert primary.attempts == [0, 1]
        assert fallback.attempts == [0]
        assert run.status == "succeeded"
        assert run.selected_provider_id == "fallback"
        assert run.fallback_used is True
        assert [call.retry_count for call in repository.list_provider_calls(run.run_id)] == [
            0,
            1,
            0,
        ]


def test_candidate_engine_stops_on_nonfallbackable_error(database_url: str) -> None:
    primary = SequenceProvider(
        "primary",
        [ProviderExecutionError("provider.invalid_request", "invalid", retryable=False)],
    )
    fallback = SequenceProvider("fallback", [provider_success("must not run")])
    service = execution_service(
        providers={"primary": primary, "fallback": fallback},
        controller=RecordingRunController(),
    )

    with get_session(database_url) as session:
        repository = RuntimeRepository(session)
        run = create_run(
            repository,
            run_id="run_nonfallbackable",
            policy={"allow_fallback": True, "max_retries": 2},
        )
        service.execute_candidate_chain(
            repository=repository,
            run=run,
            candidates=[
                Candidate("primary", "model-primary", "instance-primary"),
                Candidate("fallback", "model-fallback", "instance-fallback"),
            ],
            input_payload={},
        )

        assert primary.attempts == [0]
        assert fallback.attempts == []
        assert run.status == "failed"
        assert run.error_code == "provider.invalid_request"


def test_candidate_engine_canonicalizes_image_provider_errors_before_persistence(
    database_url: str,
) -> None:
    leaked_message = (
        "UPSTREAM-PRIVATE-PROMPT-ECHO "
        "https://images.provider.test/generated.png?sig=secret "
        "b64_json=c2Vuc2l0aXZlLWltYWdl"
    )
    primary = SequenceProvider(
        "primary",
        [ProviderExecutionError("provider.upstream_error", leaked_message, retryable=False)],
    )
    service = execution_service(
        providers={"primary": primary},
        controller=RecordingRunController(),
    )

    with get_session(database_url) as session:
        repository = RuntimeRepository(session)
        run = create_run(
            repository,
            run_id="run_image_provider_error",
            execution_kind="image_generation",
            policy={"allow_fallback": False},
        )
        service.execute_candidate_chain(
            repository=repository,
            run=run,
            candidates=[Candidate("primary", "model-primary", "instance-primary")],
            input_payload={"prompt": "A private product concept"},
        )

        assert run.status == "failed"
        assert run.error_code == "provider.upstream_error"
        assert run.error_message == IMAGE_GENERATION_PROVIDER_ERROR_MESSAGE
        assert leaked_message not in (run.error_message or "")


def test_candidate_engine_canonicalizes_vision_provider_errors_before_persistence(
    database_url: str,
) -> None:
    leaked_message = "data:image/png;base64,c2Vuc2l0aXZlLWltYWdl private prompt"
    primary = SequenceProvider(
        "primary",
        [ProviderExecutionError("provider.upstream_error", leaked_message, retryable=False)],
    )
    service = execution_service(
        providers={"primary": primary},
        controller=RecordingRunController(),
    )

    with get_session(database_url) as session:
        repository = RuntimeRepository(session)
        run = create_run(
            repository,
            run_id="run_vision_provider_error",
            execution_kind="vision",
            policy={"allow_fallback": False},
        )
        service.execute_candidate_chain(
            repository=repository,
            run=run,
            candidates=[Candidate("primary", "model-primary", "instance-primary")],
            input_payload={"source_artifact_id": "artifact_private"},
        )

        assert run.status == "failed"
        assert run.error_code == "provider.upstream_error"
        assert run.error_message == VISION_PROVIDER_ERROR_MESSAGE
        assert leaked_message not in (run.error_message or "")


def test_candidate_engine_rejected_output_falls_back(database_url: str) -> None:
    primary = SequenceProvider("primary", [provider_success("reject")])
    fallback = SequenceProvider("fallback", [provider_success("accept")])

    def prepare_output(run: RunRecord, **kwargs: Any) -> ProviderOutputDecision:
        output = kwargs["provider_output"]
        if output["output_text"] == "reject":
            return ProviderOutputDecision(
                accepted=False,
                output=output,
                error_code="provider.output_quality_rejected",
                error_message="empty output",
            )
        return ProviderOutputDecision(accepted=True, output=output)

    service = execution_service(
        providers={"primary": primary, "fallback": fallback},
        controller=RecordingRunController(),
        output_preparer=prepare_output,
    )
    with get_session(database_url) as session:
        repository = RuntimeRepository(session)
        run = create_run(
            repository,
            run_id="run_rejected_fallback",
            policy={"allow_fallback": True},
        )
        service.execute_candidate_chain(
            repository=repository,
            run=run,
            candidates=[
                Candidate("primary", "model-primary", "instance-primary"),
                Candidate("fallback", "model-fallback", "instance-fallback"),
            ],
            input_payload={},
        )

        assert run.status == "succeeded"
        calls = repository.list_provider_calls(run.run_id)
        assert [call.error_code for call in calls] == [
            "provider.output_quality_rejected",
            None,
        ]
        assert calls[1].fallback_used is True


def test_finalization_failure_follows_success_evidence_and_cancel_stops_attempts(
    database_url: str,
) -> None:
    media_candidate = ProviderMediaCandidate(
        index=1,
        content_bytes=b"generated-image-bytes",
        source_url=None,
        image_output_hosts=(),
        claimed_mime_type="image/png",
        revised_prompt="A refined image prompt.",
        claimed_width=64,
        claimed_height=48,
    )
    provider = SequenceProvider(
        "primary",
        [
            ProviderExecutionResult(
                output={"artifact_type": "image_generation_candidates"},
                media_candidates=(media_candidate,),
                latency_ms=25,
                tokens_in=4,
                tokens_out=0,
                cost=0.2,
            )
        ],
    )
    fallback_provider = SequenceProvider("fallback", [provider_success("must not run")])
    received_candidates: list[tuple[ProviderMediaCandidate, ...]] = []
    usage_recorder = RecordingUsageRecorder()

    def fail_finalization(run: RunRecord, **kwargs: Any) -> dict[str, Any]:
        received_candidates.append(kwargs["media_candidates"])
        raise ProviderOutputFinalizationError("artifact.materialization_failed", "failed")

    with get_session(database_url) as session:
        repository = RuntimeRepository(session)
        run = create_run(repository, run_id="run_finalization_failure")
        run.policy_json = {"allow_fallback": True}
        service = execution_service(
            providers={"primary": provider, "fallback": fallback_provider},
            controller=RecordingRunController(),
            output_finalizer=fail_finalization,
            usage_recorder=usage_recorder,
        )
        service.execute_candidate_chain(
            repository=repository,
            run=run,
            candidates=[
                Candidate("primary", "model", "instance"),
                Candidate("fallback", "fallback-model", "fallback-instance"),
            ],
            input_payload={},
        )
        assert run.status == "failed"
        assert run.error_code == "artifact.materialization_failed"
        assert received_candidates == [(media_candidate,)]
        assert fallback_provider.attempts == []
        provider_calls = repository.list_provider_calls(run.run_id)
        assert len(provider_calls) == 1
        assert provider_calls[0].error_code is None
        assert len(usage_recorder.calls) == 1
        assert usage_recorder.calls[0]["provider_call"] is provider_calls[0]

        canceled_provider = SequenceProvider("cancel", [provider_success("unused")])
        canceled_run = create_run(repository, run_id="run_canceled")
        canceled_service = execution_service(
            providers={"cancel": canceled_provider},
            controller=RecordingRunController(cancel_on_check=1),
        )
        canceled_service.execute_candidate_chain(
            repository=repository,
            run=canceled_run,
            candidates=[Candidate("cancel", "model", "instance")],
            input_payload={},
        )
        assert canceled_run.status == "canceled"
        assert canceled_provider.attempts == []


def test_provider_evidence_command_is_frozen() -> None:
    command = ProviderCallEvidenceCommand(
        provider_id="provider",
        model_id="model",
        instance_id="instance",
        region="region",
        latency_ms=1,
        tokens_in=2,
        tokens_out=3,
        cost=0.1,
        retry_count=0,
        fallback_used=False,
    )

    with pytest.raises(FrozenInstanceError):
        command.retry_count = 1  # type: ignore[misc]


def test_provider_execution_module_and_service_keep_the_extraction_boundary() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    module_path = repository_root / "app/domain/runtime/provider_execution.py"
    service_path = repository_root / "app/domain/runtime/service.py"
    module_tree = ast.parse(module_path.read_text(encoding="utf-8"))
    service_tree = ast.parse(service_path.read_text(encoding="utf-8"))

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
        "app.domain.commercial",
        "app.domain.routing",
        "app.domain.wordpress",
        "app.domain.audio_generation",
        "app.domain.image_",
        "app.domain.media_",
        "app.domain.runtime.callback_delivery",
        "app.core.config",
        "fastapi",
    )
    assert not {
        module
        for module in imported_modules
        if any(module.startswith(prefix) for prefix in forbidden_prefixes)
    }

    direct_repository_calls = 0
    direct_commercial_calls = 0
    extracted_calls = 0
    service_function_names: set[str] = set()
    service_provider_execute_calls = 0
    for node in ast.walk(service_tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            service_function_names.add(node.name)
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if (
            isinstance(node.func.value, ast.Name)
            and node.func.value.id == "repository"
            and node.func.attr == "record_provider_call"
        ):
            direct_repository_calls += 1
        if (
            isinstance(node.func.value, ast.Attribute)
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "self"
            and node.func.value.attr == "commercial_service"
            and node.func.attr == "record_provider_call_usage"
        ):
            direct_commercial_calls += 1
        if (
            isinstance(node.func.value, ast.Attribute)
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "self"
            and node.func.value.attr == "provider_execution_service"
            and node.func.attr == "record_provider_call"
        ):
            extracted_calls += 1
        if (
            isinstance(node.func.value, ast.Name)
            and node.func.value.id == "provider"
            and node.func.attr == "execute"
        ):
            service_provider_execute_calls += 1

    assert direct_repository_calls == 0
    assert direct_commercial_calls == 0
    assert extracted_calls == 12
    assert {"_execute_existing_run", "_execute_candidate_chain"} <= service_function_names
    assert service_provider_execute_calls == 0
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "provider"
        and node.func.attr == "execute"
        for node in ast.walk(module_tree)
    )
    runtime_service = next(
        node
        for node in service_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "RuntimeService"
    )
    candidate_method = next(
        node
        for node in runtime_service.body
        if isinstance(node, ast.FunctionDef) and node.name == "_execute_candidate_chain"
    )
    assert len(candidate_method.body) == 1
    assert "provider_execution_service.execute_candidate_chain" in ast.unparse(
        candidate_method.body[0]
    )
