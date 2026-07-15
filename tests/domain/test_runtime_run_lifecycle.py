from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.adapters.queue.base import RuntimeQueueError
from app.adapters.repositories.runtime_repository import RuntimeRepository
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import RunRecord, Site
from app.domain.runtime.errors import (
    RuntimeCancelNotAllowedError,
    RuntimeIdempotencyConflictError,
    RuntimeResultExpiredError,
    RuntimeRunNotFoundError,
)
from app.domain.runtime.models import RuntimeRequest
from app.domain.runtime.run_lifecycle import (
    RuntimeRunCreationCommand,
    RuntimeRunLifecycleService,
)
from app.domain.runtime.run_projection import RuntimeRunProjector

PAST_RETENTION = datetime(2000, 1, 1, tzinfo=UTC)
FUTURE_CLEANUP = datetime(2100, 1, 1, tzinfo=UTC)


class RecordingExecutor:
    def __init__(self) -> None:
        self.run_ids: list[str] = []

    def __call__(
        self,
        run: RunRecord,
        *,
        repository: RuntimeRepository,
    ) -> None:
        self.run_ids.append(run.run_id)
        repository.mark_run_succeeded(
            run,
            result_json={"output_text": f"completed {run.run_id}"},
            provider_id="test_provider",
            model_id="test_model",
            instance_id="test_instance",
            fallback_used=False,
        )


class FailingRuntimeQueue:
    def __init__(self) -> None:
        self.published_run_ids: list[str] = []
        self.consume_timeouts: list[int] = []

    def publish(self, run_id: str) -> None:
        self.published_run_ids.append(run_id)
        raise RuntimeQueueError("queue publish unavailable")

    def consume(self, timeout_seconds: int) -> str | None:
        self.consume_timeouts.append(timeout_seconds)
        raise RuntimeQueueError("queue consume unavailable")


class FixedSignalRuntimeQueue:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id

    def publish(self, run_id: str) -> None:
        self.run_id = run_id

    def consume(self, timeout_seconds: int) -> str | None:
        del timeout_seconds
        run_id, self.run_id = self.run_id, ""
        return run_id or None


@pytest.fixture
def database_url(tmp_path: Path) -> Iterator[str]:
    url = f"sqlite+pysqlite:///{tmp_path / 'runtime-run-lifecycle.sqlite3'}"
    init_schema(url)
    with get_session(url) as session:
        session.add_all(
            [
                Site(site_id="site_alpha", name="Site Alpha", status="active"),
                Site(site_id="site_beta", name="Site Beta", status="active"),
            ]
        )
        session.commit()
    yield url
    dispose_engine(url)


def _service(
    database_url: str,
    *,
    executor: RecordingExecutor | None = None,
    runtime_queue: FailingRuntimeQueue | FixedSignalRuntimeQueue | None = None,
    media_derivative_site_running_limit: int = 1,
) -> RuntimeRunLifecycleService:
    return RuntimeRunLifecycleService(
        database_url=database_url,
        runtime_queue=runtime_queue,
        run_projector=RuntimeRunProjector(),
        claimed_run_executor=executor or RecordingExecutor(),
        media_derivative_site_running_limit=media_derivative_site_running_limit,
    )


def _create_run(
    repository: RuntimeRepository,
    *,
    run_id: str,
    site_id: str = "site_alpha",
    status: str = "queued",
    execution_kind: str = "text",
    execution_pattern: str = "whole_run_offload",
    idempotency_key: str | None = None,
    request_fingerprint: str = "fingerprint",
) -> RunRecord:
    return repository.create_run(
        run_id=run_id,
        site_id=site_id,
        account_id=None,
        subscription_id=None,
        plan_version_id=None,
        ability_name="npcink/test-runtime-lifecycle",
        ability_family="text",
        skill_id="",
        workflow_id="",
        contract_version="v1",
        channel="openapi",
        execution_kind=execution_kind,
        execution_tier="cloud",
        execution_pattern=execution_pattern,
        data_classification="internal",
        profile_id="text.balanced",
        canonical_run_id=f"local_{run_id}",
        status=status,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
        trace_id=f"trace-{run_id}",
        input_json={"messages": [{"role": "user", "content": run_id}]},
        execution_input_ciphertext=None,
        policy_json={
            "storage_mode": "result_only",
            "retention_ttl": 60,
            "task_backend": {
                "enabled": execution_pattern == "whole_run_offload",
                "mode": "polling",
            },
        },
    )


def _creation_command(
    run_id: str,
    *,
    status: str = "running",
) -> RuntimeRunCreationCommand:
    return RuntimeRunCreationCommand(
        run_id=run_id,
        site_id="site_alpha",
        account_id="account_alpha",
        subscription_id="subscription_alpha",
        plan_version_id="plan_version_alpha",
        ability_name="npcink/test-runtime-lifecycle",
        ability_family="vision",
        skill_id="skill_alpha",
        workflow_id="workflow_alpha",
        contract_version="runtime_contract.v2",
        channel="openapi",
        execution_kind="image",
        execution_tier="cloud",
        execution_pattern="whole_run_offload",
        data_classification="restricted",
        profile_id="image.quality",
        canonical_run_id=f"local_{run_id}",
        status=status,
        idempotency_key=f"idempotency-{run_id}",
        request_fingerprint=f"fingerprint-{run_id}",
        trace_id=f"trace-{run_id}",
        input_json={"prompt": run_id},
        execution_input_ciphertext=f"ciphertext-{run_id}",
        policy_json={
            "storage_mode": "full_store_with_ttl",
            "retention_ttl": 60,
            "runtime_callback": {"callback_url": "https://callback.example/runtime"},
            "task_backend": {"enabled": True, "mode": "polling"},
        },
        selected_provider_id="provider_alpha",
        selected_model_id="model_alpha",
        selected_instance_id="instance_alpha",
    )


def test_creation_command_maps_every_durable_field_and_processing_timestamp(
    database_url: str,
) -> None:
    service = _service(database_url)
    running_command = _creation_command("run_creation_running")
    queued_command = replace(
        running_command,
        run_id="run_creation_queued",
        canonical_run_id="local_run_creation_queued",
        status="queued",
        idempotency_key="idempotency-run_creation-queued",
        request_fingerprint="fingerprint-run_creation-queued",
        trace_id="trace-run_creation-queued",
    )
    with get_session(database_url) as session:
        repository = RuntimeRepository(session)
        running = service.create_durable_run(
            repository=repository,
            command=running_command,
        )
        queued = service.create_durable_run(
            repository=repository,
            command=queued_command,
        )
        session.commit()

        assert running.run_id == running_command.run_id
        assert running.site_id == running_command.site_id
        assert running.account_id == running_command.account_id
        assert running.subscription_id == running_command.subscription_id
        assert running.plan_version_id == running_command.plan_version_id
        assert running.ability_name == running_command.ability_name
        assert running.ability_family == running_command.ability_family
        assert running.skill_id == running_command.skill_id
        assert running.workflow_id == running_command.workflow_id
        assert running.contract_version == running_command.contract_version
        assert running.channel == running_command.channel
        assert running.execution_kind == running_command.execution_kind
        assert running.execution_tier == running_command.execution_tier
        assert running.execution_pattern == running_command.execution_pattern
        assert running.data_classification == running_command.data_classification
        assert running.profile_id == running_command.profile_id
        assert running.canonical_run_id == running_command.canonical_run_id
        assert running.status == running_command.status
        assert running.idempotency_key == running_command.idempotency_key
        assert running.request_fingerprint == running_command.request_fingerprint
        assert running.trace_id == running_command.trace_id
        assert running.input_json == running_command.input_json
        assert running.execution_input_ciphertext == running_command.execution_input_ciphertext
        assert running.policy_json == running_command.policy_json
        assert running.selected_provider_id == running_command.selected_provider_id
        assert running.selected_model_id == running_command.selected_model_id
        assert running.selected_instance_id == running_command.selected_instance_id
        assert running.processing_started_at is not None
        assert queued.processing_started_at is None


def test_terminal_transition_seams_preserve_evidence_retention_and_callback(
    database_url: str,
) -> None:
    service = _service(database_url)
    with get_session(database_url) as session:
        repository = RuntimeRepository(session)
        succeeded = service.create_durable_run(
            repository=repository,
            command=_creation_command("run_transition_succeeded"),
        )
        failed = service.create_durable_run(
            repository=repository,
            command=_creation_command("run_transition_failed"),
        )
        canceled = service.create_durable_run(
            repository=repository,
            command=_creation_command("run_transition_canceled"),
        )
        not_requested = service.create_durable_run(
            repository=repository,
            command=_creation_command("run_transition_not_requested"),
        )

        service.succeed_run(
            repository,
            succeeded,
            result_json={"output_text": "success evidence"},
            provider_id="success_provider",
            model_id="success_model",
            instance_id="success_instance",
            fallback_used=True,
        )
        service.fail_run(
            repository,
            failed,
            error_code="provider.timeout",
            error_message="provider timed out",
            provider_id="failed_provider",
            model_id="failed_model",
            instance_id="failed_instance",
            fallback_used=False,
        )
        repository.request_run_cancel(canceled)
        assert service.cancel_if_requested(repository=repository, run=canceled) is True
        assert service.cancel_if_requested(repository=repository, run=not_requested) is False
        session.commit()

        assert succeeded.status == "succeeded"
        assert succeeded.result_json == {"output_text": "success evidence"}
        assert succeeded.selected_provider_id == "success_provider"
        assert succeeded.selected_model_id == "success_model"
        assert succeeded.selected_instance_id == "success_instance"
        assert succeeded.fallback_used is True

        assert failed.status == "failed"
        assert failed.error_code == "provider.timeout"
        assert failed.error_message == "provider timed out"
        assert failed.selected_provider_id == "failed_provider"
        assert failed.selected_model_id == "failed_model"
        assert failed.selected_instance_id == "failed_instance"
        assert failed.fallback_used is False

        assert canceled.status == "canceled"
        assert canceled.error_code == "runtime.canceled"
        assert canceled.error_message == "run canceled before execution completed"
        assert canceled.cancel_requested_at is not None
        assert canceled.canceled_at is not None
        assert not_requested.status == "running"

        for terminal in (succeeded, failed, canceled):
            assert terminal.finished_at is not None
            assert terminal.retention_expires_at is not None
            assert terminal.callback_status == "pending"
            assert terminal.callback_next_attempt_at is not None
            assert terminal.execution_input_ciphertext is None


def test_fingerprints_and_idempotent_replay_are_canonical_and_conflict_exactly(
    database_url: str,
) -> None:
    service = _service(database_url)
    request = RuntimeRequest(
        site_id="site_alpha",
        ability_name="npcink/test-runtime-lifecycle",
        channel="openapi",
        execution_kind="text",
        profile_id="text.balanced",
        input_payload={"messages": [{"role": "user", "content": "hello"}]},
    )
    policy = {"storage_mode": "result_only", "retention_ttl": 60}
    fingerprint = service.build_request_fingerprint(request, policy)

    assert fingerprint == service.build_request_fingerprint(request, dict(policy))
    assert fingerprint != service.build_request_fingerprint(
        request,
        {**policy, "retention_ttl": 120},
    )
    assert service.build_media_derivative_request_fingerprint(
        "site_alpha",
        {"target_format": "webp"},
        source_checksum="source-checksum",
    ) != service.build_media_derivative_request_fingerprint(
        "site_alpha",
        {"target_format": "webp"},
        source_checksum="changed-source-checksum",
    )

    with get_session(database_url) as session:
        repository = RuntimeRepository(session)
        created = _create_run(
            repository,
            run_id="run_replay",
            idempotency_key="replay-key",
            request_fingerprint=fingerprint,
        )
        session.commit()

        assert (
            service.get_idempotent_replay(
                repository=repository,
                site_id="site_alpha",
                idempotency_key="replay-key",
                request_fingerprint=fingerprint,
            ).run_id
            == created.run_id
        )
        assert (
            service.get_idempotent_replay(
                repository=repository,
                site_id="site_alpha",
                idempotency_key=None,
                request_fingerprint=fingerprint,
            )
            is None
        )
        with pytest.raises(RuntimeIdempotencyConflictError) as conflict:
            service.get_idempotent_replay(
                repository=repository,
                site_id="site_alpha",
                idempotency_key="replay-key",
                request_fingerprint="changed-fingerprint",
            )

    assert conflict.value.status_code == 409
    assert conflict.value.error_code == "runtime.idempotency_conflict"
    assert conflict.value.message == (
        "idempotency key 'replay-key' for site 'site_alpha' does not match the original request"
    )


def test_queue_failures_fall_back_to_one_durable_database_claim(database_url: str) -> None:
    runtime_queue = FailingRuntimeQueue()
    executor = RecordingExecutor()
    service = _service(
        database_url,
        executor=executor,
        runtime_queue=runtime_queue,
    )
    with get_session(database_url) as session:
        _create_run(RuntimeRepository(session), run_id="run_durable")
        session.commit()

    service.publish_queue_signal("run_durable")
    processed = service.process_next_queued_run(timeout_seconds=7)

    assert runtime_queue.published_run_ids == ["run_durable"]
    assert runtime_queue.consume_timeouts == [7]
    assert processed == {
        "run_id": "run_durable",
        "status": "succeeded",
        "trace_id": "trace-run_durable",
    }
    assert executor.run_ids == ["run_durable"]
    assert service.process_next_queued_run(timeout_seconds=0) is None
    assert executor.run_ids == ["run_durable"]


def test_queue_signal_without_durable_record_is_never_run_truth(database_url: str) -> None:
    executor = RecordingExecutor()
    service = _service(
        database_url,
        executor=executor,
        runtime_queue=FixedSignalRuntimeQueue("missing_run"),
    )

    assert service.process_next_queued_run(timeout_seconds=0) is None
    assert executor.run_ids == []


def test_site_scoped_views_result_and_provider_evidence(database_url: str) -> None:
    service = _service(database_url)
    with get_session(database_url) as session:
        repository = RuntimeRepository(session)
        run = _create_run(repository, run_id="run_result", status="running")
        repository.mark_run_succeeded(
            run,
            result_json={"output_text": "result evidence"},
            provider_id="provider_a",
            model_id="model_a",
            instance_id="instance_a",
            fallback_used=False,
        )
        repository.record_provider_call(
            run_id=run.run_id,
            provider_id="provider_a",
            model_id="model_a",
            instance_id="instance_a",
            region="global",
            latency_ms=17,
            tokens_in=3,
            tokens_out=5,
            cost=0.01,
            retry_count=0,
            fallback_used=False,
        )
        session.commit()

    status = service.get_run("run_result", site_id="site_alpha")
    result = service.get_run_result("run_result", site_id="site_alpha")
    assert status["status"] == "succeeded"
    assert status["provider_call_count"] == 1
    assert result["result"]["output_text"] == "result evidence"
    assert result["provider_calls"] == [
        {
            "provider_id": "provider_a",
            "model_id": "model_a",
            "instance_id": "instance_a",
            "region": "global",
            "latency_ms": 17,
            "tokens_in": 3,
            "tokens_out": 5,
            "cost": 0.01,
            "retry_count": 0,
            "fallback_used": False,
            "error_code": None,
            "error_stage": "",
            "retryable": False,
        }
    ]

    for operation in (
        lambda: service.get_run("run_result", site_id="site_beta"),
        lambda: service.get_run_result("run_result", site_id="site_beta"),
    ):
        with pytest.raises(RuntimeRunNotFoundError) as not_found:
            operation()
        assert not_found.value.error_code == "runtime.run_not_found"


def test_public_cancel_mutates_only_queue_backed_runs(database_url: str) -> None:
    service = _service(database_url)
    with get_session(database_url) as session:
        repository = RuntimeRepository(session)
        _create_run(repository, run_id="run_cancel")
        _create_run(
            repository,
            run_id="run_inline",
            status="running",
            execution_pattern="inline",
        )
        session.commit()

    canceled = service.cancel_run("run_cancel", site_id="site_alpha")
    assert canceled["status"] == "canceled"
    assert canceled["error_code"] == "runtime.canceled"
    assert service.cancel_run("run_cancel", site_id="site_alpha")["status"] == "canceled"

    with pytest.raises(RuntimeCancelNotAllowedError) as not_allowed:
        service.cancel_run("run_inline", site_id="site_alpha")
    assert not_allowed.value.error_code == "runtime.cancel_not_allowed"
    with pytest.raises(RuntimeRunNotFoundError):
        service.cancel_run("run_inline", site_id="site_beta")


def test_expired_result_cleanup_purges_payload_but_preserves_run(database_url: str) -> None:
    service = _service(database_url)
    with get_session(database_url) as session:
        repository = RuntimeRepository(session)
        run = _create_run(repository, run_id="run_expired", status="running")
        repository.mark_run_succeeded(
            run,
            result_json={"output_text": "expires"},
            provider_id="provider_a",
            model_id="model_a",
            instance_id="instance_a",
            fallback_used=False,
        )
        run.retention_expires_at = PAST_RETENTION
        session.commit()

    assert service.cleanup_expired_run_results(now=FUTURE_CLEANUP) == 1
    assert service.cleanup_expired_run_results(now=FUTURE_CLEANUP) == 0
    with pytest.raises(RuntimeResultExpiredError) as expired:
        service.get_run_result("run_expired", site_id="site_alpha")
    assert expired.value.error_code == "runtime.result_expired"
    assert service.get_run("run_expired", site_id="site_alpha")["status"] == "succeeded"

    with get_session(database_url) as session:
        run = RuntimeRepository(session).get_run("run_expired")
        assert run is not None
        assert run.result_json is None
        assert run.result_ref == "purged"
        assert run.result_purged_at is not None


def test_media_derivative_site_running_limit_skips_only_saturated_site_work(
    database_url: str,
) -> None:
    executor = RecordingExecutor()
    service = _service(
        database_url,
        executor=executor,
        media_derivative_site_running_limit=1,
    )
    with get_session(database_url) as session:
        repository = RuntimeRepository(session)
        _create_run(
            repository,
            run_id="run_media_running",
            status="running",
            execution_kind="media_derivative",
        )
        _create_run(
            repository,
            run_id="run_media_queued",
            execution_kind="media_derivative",
        )
        _create_run(repository, run_id="run_text_queued")
        session.commit()

    assert service.process_next_queued_run(timeout_seconds=0) == {
        "run_id": "run_text_queued",
        "status": "succeeded",
        "trace_id": "trace-run_text_queued",
    }
    assert executor.run_ids == ["run_text_queued"]
    with get_session(database_url) as session:
        queued_media = RuntimeRepository(session).get_run("run_media_queued")
        assert queued_media is not None
        assert queued_media.status == "queued"


def test_lifecycle_dependency_boundary_and_runtime_service_facades() -> None:
    repository_root = Path(__file__).parents[2]
    lifecycle_path = repository_root / "app/domain/runtime/run_lifecycle.py"
    service_path = repository_root / "app/domain/runtime/service.py"
    artifact_coordination_path = repository_root / "app/domain/runtime/artifact_coordination.py"
    lifecycle_source = lifecycle_path.read_text(encoding="utf-8")
    service_source = service_path.read_text(encoding="utf-8")
    artifact_coordination_source = artifact_coordination_path.read_text(encoding="utf-8")
    lifecycle_tree = ast.parse(lifecycle_source)
    service_tree = ast.parse(service_source)

    imported_modules = {
        node.module or "" for node in ast.walk(lifecycle_tree) if isinstance(node, ast.ImportFrom)
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(lifecycle_tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    forbidden_fragments = (
        "app.core.config",
        "app.domain.runtime.service",
        "app.domain.commercial",
        "app.domain.runtime.callback_delivery",
        "app.adapters.providers",
        "app.domain.routing",
        "wordpress",
        "artifact",
        "media_derivatives",
    )
    assert not {
        module
        for module in imported_modules
        if any(fragment in module for fragment in forbidden_fragments)
    }
    assert "Settings" not in lifecycle_source

    runtime_service = next(
        node
        for node in service_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "RuntimeService"
    )
    methods = {
        node.name: node
        for node in runtime_service.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    old_private_paths = {
        "_build_request_fingerprint",
        "_build_media_derivative_request_fingerprint",
        "_get_idempotent_replay",
        "_publish_queue_signal",
        "_consume_queue_signal",
        "_process_single_queued_run",
        "_cancel_requested_before_attempt",
    }
    assert old_private_paths.isdisjoint(methods)

    for method_name in (
        "process_next_queued_run",
        "process_queued_runs",
        "get_run",
        "get_run_result",
        "cancel_run",
        "cleanup_expired_run_results",
    ):
        method = methods[method_name]
        assert len(method.body) == 1
        statement = method.body[0]
        assert isinstance(statement, ast.Return)
        assert isinstance(statement.value, ast.Call)
        assert ast.unparse(statement.value.func).startswith("self.run_lifecycle_service.")

    assert ".get_run_by_idempotency(" not in service_source
    assert ".get_run_by_idempotency(" not in artifact_coordination_source
    service_idempotent_replay_calls = service_source.count(".get_idempotent_replay(")
    artifact_idempotent_replay_calls = artifact_coordination_source.count(".get_idempotent_replay(")
    assert (service_idempotent_replay_calls, artifact_idempotent_replay_calls) == (8, 4)
    assert service_idempotent_replay_calls + artifact_idempotent_replay_calls == 12
    assert service_source.count(".build_request_fingerprint(") == 8
    service_media_fingerprint_calls = service_source.count(
        ".build_media_derivative_request_fingerprint("
    )
    artifact_media_fingerprint_calls = artifact_coordination_source.count(
        ".build_media_derivative_request_fingerprint("
    )
    assert (service_media_fingerprint_calls, artifact_media_fingerprint_calls) == (0, 2)
    assert service_media_fingerprint_calls + artifact_media_fingerprint_calls == 2
    service_publish_queue_calls = service_source.count(".publish_queue_signal(")
    artifact_publish_queue_calls = artifact_coordination_source.count(".publish_queue_signal(")
    assert (service_publish_queue_calls, artifact_publish_queue_calls) == (5, 1)
    assert service_publish_queue_calls + artifact_publish_queue_calls == 6
    for forbidden_repository_transition in (
        ".create_run(",
        ".mark_run_succeeded(",
        ".mark_run_failed(",
        ".mark_run_canceled(",
    ):
        assert f"repository{forbidden_repository_transition}" not in service_source
    assert "_cancel_requested_before_attempt" not in service_source
    assert "repository.record_provider_call(" not in service_source
    assert "self.provider_execution_service.record_provider_call(" in service_source
    assert "def _execute_existing_run(" in service_source
    assert "def _execute_candidate_chain(" in service_source
