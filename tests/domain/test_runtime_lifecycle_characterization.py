from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app.adapters.providers.base import (
    ProviderExecutionRequest,
    ProviderExecutionResult,
)
from app.adapters.providers.openai import OpenAIProviderAdapter
from app.adapters.queue.in_memory import InMemoryRuntimeQueue
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import ProviderCallRecord, RunRecord
from app.domain.catalog.service import CatalogService
from app.domain.runtime.errors import (
    RuntimeCancelNotAllowedError,
    RuntimeIdempotencyConflictError,
    RuntimeResultExpiredError,
    RuntimeRunNotFoundError,
)
from app.domain.runtime.models import RuntimeRequest
from app.domain.runtime.service import RuntimeService
from tests.conftest import seed_openai_model_allowlist, seed_site_auth

PAST_RETENTION = datetime(2000, 1, 1, tzinfo=UTC)
FUTURE_CLEANUP = datetime(2100, 1, 1, tzinfo=UTC)


def _dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


class LifecycleRecordingProvider(OpenAIProviderAdapter):
    def __init__(self) -> None:
        super().__init__(sample_catalog_profile="free-gpt55")
        self.requests: list[ProviderExecutionRequest] = []

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        self.requests.append(request)
        return ProviderExecutionResult(
            output={"output_text": "lifecycle characterization result"},
            latency_ms=21,
            tokens_in=4,
            tokens_out=3,
            cost=0.0,
        )


def _setup_runtime(
    tmp_path: Path,
) -> tuple[str, Settings, LifecycleRecordingProvider]:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'runtime-lifecycle.sqlite3'}"
    provider = LifecycleRecordingProvider()
    init_schema(database_url)
    CatalogService(database_url, providers={"openai": provider}).refresh_catalog()
    seed_openai_model_allowlist(database_url)
    seed_site_auth(database_url, site_id="site_alpha")
    seed_site_auth(database_url, site_id="site_beta", key_id="key_beta")
    settings = Settings(
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token="i" * 32,
    )
    return database_url, settings, provider


def _service(
    database_url: str,
    settings: Settings,
    provider: LifecycleRecordingProvider,
    *,
    runtime_queue: InMemoryRuntimeQueue | None = None,
) -> RuntimeService:
    return RuntimeService(
        database_url,
        settings=settings,
        providers={"openai": provider},
        runtime_queue=runtime_queue,
    )


def _queued_request(
    *,
    site_id: str = "site_alpha",
    idempotency_key: str,
    content: str,
    canonical_run_id: str = "local_run_lifecycle",
) -> RuntimeRequest:
    return RuntimeRequest(
        site_id=site_id,
        ability_name="workflow/media_nightly_image_optimize",
        ability_family="automation",
        skill_id="media_nightly_optimize",
        workflow_id="media_nightly_image_optimize",
        canonical_run_id=canonical_run_id,
        contract_version="v1",
        channel="openapi",
        execution_kind="text",
        profile_id="text.balanced",
        execution_tier="cloud",
        execution_pattern="whole_run_offload",
        data_classification="internal",
        timeout_seconds=1800,
        retry_max=0,
        retention_ttl=86400,
        task_backend={
            "enabled": True,
            "mode": "polling",
            "callback_mode": "polling_preferred",
            "polling_interval_sec": 30,
        },
        input_payload={"messages": [{"role": "user", "content": content}]},
        policy={"allow_fallback": True},
        idempotency_key=idempotency_key,
        trace_id=f"trace-{idempotency_key}",
    )


def _inline_request(*, idempotency_key: str, content: str) -> RuntimeRequest:
    return RuntimeRequest(
        site_id="site_alpha",
        ability_name="npcink-abilities-toolkit/build-article-block-plan",
        ability_family="workflow",
        contract_version="v1",
        channel="openapi",
        execution_kind="text",
        profile_id="text.balanced",
        execution_pattern="inline",
        retention_ttl=60,
        input_payload={"messages": [{"role": "user", "content": content}]},
        idempotency_key=idempotency_key,
        trace_id=f"trace-{idempotency_key}",
    )


def test_queued_idempotency_reuses_one_durable_run_and_rejects_payload_conflict(
    tmp_path: Path,
) -> None:
    database_url, settings, provider = _setup_runtime(tmp_path)
    service = _service(database_url, settings, provider)
    idempotency_key = "lifecycle-idempotency-001"

    first = service.execute(
        _queued_request(
            idempotency_key=idempotency_key,
            content="queue this canonical request",
        )
    )
    replay = service.execute(
        _queued_request(
            idempotency_key=idempotency_key,
            content="queue this canonical request",
        )
    )

    assert first.status == "queued"
    assert first.idempotent_replay is False
    assert replay.idempotent_replay is True
    assert replay.run_id == first.run_id
    assert replay.canonical_run_id == first.canonical_run_id == "local_run_lifecycle"
    assert first.run_state["idempotency"]["canonical_truth"] == "run_records"
    assert first.run_state["boundary"]["cloud_scheduler_truth"] is False

    with get_session(database_url) as session:
        runs = list(session.scalars(select(RunRecord)))
        provider_calls = list(session.scalars(select(ProviderCallRecord)))
    assert [run.run_id for run in runs] == [first.run_id]
    assert provider_calls == []
    assert provider.requests == []

    with pytest.raises(RuntimeIdempotencyConflictError) as conflict:
        service.execute(
            _queued_request(
                idempotency_key=idempotency_key,
                content="changed request body",
            )
        )
    assert conflict.value.status_code == 409
    assert conflict.value.error_code == "runtime.idempotency_conflict"
    assert conflict.value.message == (
        "idempotency key 'lifecycle-idempotency-001' for site 'site_alpha' "
        "does not match the original request"
    )

    processed = service.process_next_queued_run(timeout_seconds=0)
    assert processed == {
        "run_id": first.run_id,
        "status": "succeeded",
        "trace_id": "trace-lifecycle-idempotency-001",
    }
    with get_session(database_url) as session:
        assert len(list(session.scalars(select(RunRecord)))) == 1
        assert len(list(session.scalars(select(ProviderCallRecord)))) == 1
    assert len(provider.requests) == 1

    dispose_engine(database_url)


def test_site_scoping_hides_run_status_result_and_cancel_from_other_sites(
    tmp_path: Path,
) -> None:
    database_url, settings, provider = _setup_runtime(tmp_path)
    service = _service(database_url, settings, provider)
    queued = service.execute(
        _queued_request(
            idempotency_key="lifecycle-site-scope-001",
            content="site alpha private run",
        )
    )

    for operation in (
        lambda: service.get_run(queued.run_id, site_id="site_beta"),
        lambda: service.get_run_result(queued.run_id, site_id="site_beta"),
        lambda: service.cancel_run(queued.run_id, site_id="site_beta"),
    ):
        with pytest.raises(RuntimeRunNotFoundError) as not_found:
            operation()
        assert not_found.value.status_code == 404
        assert not_found.value.error_code == "runtime.run_not_found"
        assert not_found.value.message == f"run '{queued.run_id}' was not found"

    assert service.get_run(queued.run_id, site_id="site_alpha")["status"] == "queued"
    dispose_engine(database_url)


def test_queue_signal_is_only_wakeup_assist_and_database_polling_is_run_truth(
    tmp_path: Path,
) -> None:
    database_url, settings, provider = _setup_runtime(tmp_path)
    runtime_queue = InMemoryRuntimeQueue()
    worker = _service(
        database_url,
        settings,
        provider,
        runtime_queue=runtime_queue,
    )

    runtime_queue.publish("run_signal_without_durable_record")
    assert worker.process_next_queued_run(timeout_seconds=0) is None
    with get_session(database_url) as session:
        assert list(session.scalars(select(RunRecord))) == []

    intake_without_queue = _service(database_url, settings, provider)
    assert intake_without_queue.runtime_queue is None
    queued = intake_without_queue.execute(
        _queued_request(
            idempotency_key="lifecycle-db-poll-001",
            content="claim this run from durable database state",
        )
    )
    assert queued.status == "queued"
    assert queued.run_lifecycle["phase"] == "queued"
    assert queued.run_state["state_machine"] == "requested->queued->running->terminal"
    assert queued.run_state["observability"]["run_record_truth"] == "run_records"
    assert queued.provider_call_count == 0

    processed = worker.process_next_queued_run(timeout_seconds=0)

    assert processed == {
        "run_id": queued.run_id,
        "status": "succeeded",
        "trace_id": "trace-lifecycle-db-poll-001",
    }
    final = worker.get_run(queued.run_id, site_id="site_alpha")
    assert final["status"] == "succeeded"
    assert _dict(final["run_lifecycle"])["phase"] == "terminal"
    assert final["provider_call_count"] == 1
    with get_session(database_url) as session:
        durable_run = session.get(RunRecord, queued.run_id)
        assert durable_run is not None
        assert durable_run.processing_started_at is not None
        assert durable_run.finished_at is not None
        durable_calls = list(
            session.scalars(
                select(ProviderCallRecord).where(ProviderCallRecord.run_id == queued.run_id)
            )
        )
    assert len(durable_calls) == 1
    assert len(provider.requests) == 1
    assert worker.process_next_queued_run(timeout_seconds=0) is None

    dispose_engine(database_url)


def test_cancel_accepts_queued_run_and_rejects_inline_or_terminal_run(
    tmp_path: Path,
) -> None:
    database_url, settings, provider = _setup_runtime(tmp_path)
    service = _service(database_url, settings, provider)

    queued = service.execute(
        _queued_request(
            idempotency_key="lifecycle-cancel-queued-001",
            content="cancel before worker claim",
        )
    )
    canceled = service.cancel_run(queued.run_id, site_id="site_alpha")
    assert canceled["status"] == "canceled"
    assert _dict(_dict(canceled["run_lifecycle"])["cancel"])["state"] == "canceled"
    assert _dict(canceled["task_backend"])["status"] == "canceled"
    assert service.process_next_queued_run(timeout_seconds=0) is None

    inline = service.execute(
        _inline_request(
            idempotency_key="lifecycle-cancel-inline-001",
            content="complete inline then reject cancel",
        )
    )
    assert inline.status == "succeeded"
    assert inline.run_lifecycle["cancel"]["supported"] is False
    with pytest.raises(RuntimeCancelNotAllowedError) as inline_cancel:
        service.cancel_run(inline.run_id, site_id="site_alpha")
    assert inline_cancel.value.status_code == 409
    assert inline_cancel.value.error_code == "runtime.cancel_not_allowed"
    assert inline_cancel.value.message == (
        f"run '{inline.run_id}' in status 'succeeded' does not permit public cancel"
    )

    queued_to_terminal = service.execute(
        _queued_request(
            idempotency_key="lifecycle-cancel-terminal-001",
            content="finish queued run then reject cancel",
        )
    )
    processed = service.process_next_queued_run(timeout_seconds=0)
    assert processed is not None
    assert processed["run_id"] == queued_to_terminal.run_id
    with pytest.raises(RuntimeCancelNotAllowedError) as terminal_cancel:
        service.cancel_run(queued_to_terminal.run_id, site_id="site_alpha")
    assert terminal_cancel.value.status_code == 409
    assert terminal_cancel.value.error_code == "runtime.cancel_not_allowed"
    assert terminal_cancel.value.message == (
        f"run '{queued_to_terminal.run_id}' in status 'succeeded' does not permit public cancel"
    )

    dispose_engine(database_url)


def test_expired_result_is_unreadable_while_durable_run_record_remains(
    tmp_path: Path,
) -> None:
    database_url, settings, provider = _setup_runtime(tmp_path)
    service = _service(database_url, settings, provider)
    completed = service.execute(
        _inline_request(
            idempotency_key="lifecycle-retention-001",
            content="retain run evidence after result expiry",
        )
    )
    assert completed.status == "succeeded"

    with get_session(database_url) as session:
        durable_run = session.get(RunRecord, completed.run_id)
        assert durable_run is not None
        assert durable_run.result_json is not None
        durable_run.retention_expires_at = PAST_RETENTION
        session.commit()

    assert service.cleanup_expired_run_results(now=FUTURE_CLEANUP) == 1
    with pytest.raises(RuntimeResultExpiredError) as expired:
        service.get_run_result(completed.run_id, site_id="site_alpha")
    assert expired.value.status_code == 410
    assert expired.value.error_code == "runtime.result_expired"
    assert expired.value.message == (
        f"run '{completed.run_id}' result has expired and is no longer available"
    )

    run_view = service.get_run(completed.run_id, site_id="site_alpha")
    assert run_view["status"] == "succeeded"
    retention = _dict(_dict(run_view["run_lifecycle"])["retention"])
    assert retention["state"] == "expired"
    assert retention["result_purged_at"] is not None
    with get_session(database_url) as session:
        durable_run = session.get(RunRecord, completed.run_id)
        assert durable_run is not None
        assert durable_run.result_json is None
        assert durable_run.result_purged_at is not None
        assert durable_run.result_purged_at.replace(tzinfo=UTC) == FUTURE_CLEANUP

    dispose_engine(database_url)
