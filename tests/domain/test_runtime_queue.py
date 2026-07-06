from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import httpx
import pytest
from sqlalchemy import select

from app.adapters.callbacks.base import RuntimeCallbackDispatchRequest
from app.adapters.callbacks.http import HttpRuntimeCallbackDispatcher
from app.adapters.queue.in_memory import InMemoryRuntimeQueue
from app.adapters.queue.redis_runtime_queue import RedisRuntimeQueue
from app.adapters.repositories.runtime_repository import RuntimeRepository
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import RunRecord, ServiceAuditEvent
from app.domain.catalog.service import CatalogService
from app.domain.runtime.errors import (
    RuntimeResultExpiredError,
    RuntimeSiteInactiveError,
    RuntimeSiteNotProvisionedError,
)
from app.domain.runtime.models import (
    RUNTIME_CALLBACK_DISPATCH_LEASE_RECOVERY_ERROR_CODE,
    RuntimeRequest,
)
from app.domain.runtime.service import RuntimeService
from tests.conftest import seed_openai_model_allowlist, seed_site_auth


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'runtime-queue.sqlite3'}"


def _runtime_service(
    database_url: str,
    **kwargs: object,
) -> RuntimeService:
    settings = kwargs.pop("settings", None)
    if settings is None:
        from app.core.config import Settings

        settings = Settings(
            environment="test",
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
            internal_auth_token="i" * 32,
        )
    return RuntimeService(database_url, settings=settings, **kwargs)


def test_execute_requires_preprovisioned_active_site(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_openai_model_allowlist(database_url)

    service = _runtime_service(database_url)
    request = RuntimeRequest(
        site_id="site_queue",
        ability_name="workflow/media_nightly_image_optimize",
        skill_id="media_nightly_optimize",
        workflow_id="media_nightly_image_optimize",
        contract_version="v1",
        channel="openapi",
        execution_kind="text",
        profile_id="text.balanced",
        execution_tier="cloud",
        execution_pattern="whole_run_offload",
        data_classification="internal",
        timeout_seconds=1800,
        retry_max=2,
        retention_ttl=86400,
        task_backend={
            "enabled": True,
            "mode": "polling",
            "callback_mode": "polling_preferred",
            "polling_interval_sec": 120,
        },
        input_payload={
            "messages": [{"role": "user", "content": "queue this run after provisioning"}]
        },
        policy={"allow_fallback": True},
        idempotency_key="queue-domain-preprovision-001",
        trace_id="trace-queue-domain-preprovision-001",
    )

    with pytest.raises(RuntimeSiteNotProvisionedError):
        service.execute(request)

    seed_site_auth(
        database_url,
        site_id="site_queue",
        site_status="suspended",
    )

    with pytest.raises(RuntimeSiteInactiveError):
        service.execute(request)

    dispose_engine(database_url)


def test_process_next_queued_run_claims_from_database_without_signal(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_openai_model_allowlist(database_url)
    seed_site_auth(database_url, site_id="site_queue")

    service = _runtime_service(database_url)
    queued = service.execute(
        RuntimeRequest(
            site_id="site_queue",
            ability_name="workflow/media_nightly_image_optimize",
            skill_id="media_nightly_optimize",
            workflow_id="media_nightly_image_optimize",
            contract_version="v1",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            execution_tier="cloud",
            execution_pattern="whole_run_offload",
            data_classification="internal",
            timeout_seconds=1800,
            retry_max=2,
            retention_ttl=86400,
            task_backend={
                "enabled": True,
                "mode": "polling",
                "callback_mode": "polling_preferred",
                "polling_interval_sec": 120,
            },
            input_payload={
                "messages": [{"role": "user", "content": "queue this run without a signal backend"}]
            },
            policy={"allow_fallback": True},
            idempotency_key="queue-domain-001",
            trace_id="trace-queue-domain-001",
        )
    )

    assert queued.status == "queued"
    assert queued.provider_call_count == 0
    assert queued.task_backend["status"] == "queued"

    processed = service.process_next_queued_run(timeout_seconds=1)
    assert processed == {
        "run_id": queued.run_id,
        "status": "succeeded",
        "trace_id": "trace-queue-domain-001",
    }

    final_run = service.get_run(queued.run_id)
    assert final_run["status"] == "succeeded"
    assert final_run["provider_call_count"] == 1
    assert final_run["task_backend"]["status"] == "completed"

    dispose_engine(database_url)


def test_claim_next_queued_run_uses_atomic_update_returning(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_openai_model_allowlist(database_url)
    seed_site_auth(database_url, site_id="site_queue")

    service = _runtime_service(database_url)
    queued = service.execute(
        RuntimeRequest(
            site_id="site_queue",
            ability_name="workflow/media_nightly_image_optimize",
            skill_id="media_nightly_optimize",
            workflow_id="media_nightly_image_optimize",
            contract_version="v1",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            execution_tier="cloud",
            execution_pattern="whole_run_offload",
            data_classification="internal",
            timeout_seconds=1800,
            retry_max=2,
            retention_ttl=86400,
            task_backend={"enabled": True},
            input_payload={"messages": [{"role": "user", "content": "atomic claim"}]},
            idempotency_key="queue-domain-atomic-001",
            trace_id="trace-queue-domain-atomic-001",
        )
    )
    assert queued.status == "queued"

    with get_session(database_url) as session:
        repository = RuntimeRepository(session)

        def _unexpected_scalar(*args: object, **kwargs: object) -> None:
            raise AssertionError(
                "claim_next_queued_run should not perform a pre-claim scalar select"
            )

        session.scalar = _unexpected_scalar  # type: ignore[method-assign]
        claimed = repository.claim_next_queued_run()
        assert claimed is not None
        assert claimed.run_id == queued.run_id
        assert claimed.status == "running"

    dispose_engine(database_url)


def test_process_queued_runs_drains_signaled_and_unsignaled_runs_in_one_cycle(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_openai_model_allowlist(database_url)
    seed_site_auth(
        database_url,
        site_id="site_queue",
        concurrency={"max_active_runs": 2},
    )

    runtime_queue = InMemoryRuntimeQueue()
    queue_service = _runtime_service(database_url, runtime_queue=runtime_queue)
    fallback_service = _runtime_service(database_url)

    signaled = queue_service.execute(
        RuntimeRequest(
            site_id="site_queue",
            ability_name="workflow/media_nightly_image_optimize",
            skill_id="media_nightly_optimize",
            workflow_id="media_nightly_image_optimize",
            contract_version="v1",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            execution_tier="cloud",
            execution_pattern="whole_run_offload",
            data_classification="internal",
            timeout_seconds=1800,
            retry_max=2,
            retention_ttl=86400,
            task_backend={
                "enabled": True,
                "mode": "polling",
                "callback_mode": "polling_preferred",
                "polling_interval_sec": 120,
            },
            input_payload={
                "messages": [{"role": "user", "content": "queue this run with a wake-up signal"}]
            },
            policy={"allow_fallback": True},
            idempotency_key="queue-domain-batch-001",
            trace_id="trace-queue-domain-batch-001",
        )
    )
    unsignaled = fallback_service.execute(
        RuntimeRequest(
            site_id="site_queue",
            ability_name="workflow/media_nightly_image_optimize",
            skill_id="media_nightly_optimize",
            workflow_id="media_nightly_image_optimize",
            contract_version="v1",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            execution_tier="cloud",
            execution_pattern="whole_run_offload",
            data_classification="internal",
            timeout_seconds=1800,
            retry_max=2,
            retention_ttl=86400,
            task_backend={
                "enabled": True,
                "mode": "polling",
                "callback_mode": "polling_preferred",
                "polling_interval_sec": 120,
            },
            input_payload={
                "messages": [{"role": "user", "content": "queue this run without a wake-up signal"}]
            },
            policy={"allow_fallback": True},
            idempotency_key="queue-domain-batch-002",
            trace_id="trace-queue-domain-batch-002",
        )
    )

    worker = _runtime_service(database_url, runtime_queue=runtime_queue)
    processed = worker.process_queued_runs(max_runs=2, timeout_seconds=1)

    assert processed == [
        {
            "run_id": signaled.run_id,
            "status": "succeeded",
            "trace_id": "trace-queue-domain-batch-001",
        },
        {
            "run_id": unsignaled.run_id,
            "status": "succeeded",
            "trace_id": "trace-queue-domain-batch-002",
        },
    ]

    assert worker.get_run(signaled.run_id)["task_backend"]["status"] == "completed"
    assert worker.get_run(unsignaled.run_id)["task_backend"]["status"] == "completed"

    dispose_engine(database_url)


def test_cleanup_expired_run_results_purges_stored_result(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_openai_model_allowlist(database_url)
    seed_site_auth(database_url, site_id="site_queue")

    service = _runtime_service(database_url)
    completed = service.execute(
        RuntimeRequest(
            site_id="site_queue",
            ability_name="workflow/media_nightly_image_optimize",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            retention_ttl=60,
            idempotency_key="queue-domain-expire-001",
            trace_id="trace-queue-domain-expire-001",
            input_payload={"messages": [{"role": "user", "content": "expire stored result"}]},
        )
    )

    with get_session(database_url) as session:
        run = session.scalar(select(RunRecord).where(RunRecord.run_id == completed.run_id))
        assert run is not None
        run.retention_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        session.commit()

    purged = service.cleanup_expired_run_results(now=datetime.now(UTC))
    assert purged == 1

    with pytest.raises(RuntimeResultExpiredError):
        service.get_run_result(completed.run_id)

    run_view = service.get_run(completed.run_id)
    assert run_view["run_lifecycle"]["retention"]["state"] == "expired"
    assert run_view["run_lifecycle"]["retention"]["result_purged_at"] is not None

    dispose_engine(database_url)


def test_cancel_run_marks_queued_run_canceled(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_openai_model_allowlist(database_url)
    seed_site_auth(database_url, site_id="site_queue")

    service = _runtime_service(database_url)
    queued = service.execute(
        RuntimeRequest(
            site_id="site_queue",
            ability_name="workflow/media_nightly_image_optimize",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            execution_pattern="whole_run_offload",
            task_backend={"enabled": True, "mode": "polling"},
            idempotency_key="queue-domain-cancel-001",
            trace_id="trace-queue-domain-cancel-001",
            input_payload={"messages": [{"role": "user", "content": "cancel this queued run"}]},
        )
    )

    assert queued.status == "queued"
    canceled = service.cancel_run(queued.run_id, site_id="site_queue")
    assert canceled["status"] == "canceled"
    assert canceled["run_lifecycle"]["cancel"]["state"] == "canceled"
    assert canceled["task_backend"]["status"] == "canceled"
    assert service.process_next_queued_run(timeout_seconds=0) is None

    dispose_engine(database_url)


def test_dispatch_pending_callbacks_delivers_terminal_run(
    tmp_path: Path,
    allow_example_callback_dns: None,
) -> None:
    callback_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        callback_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(204)

    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_openai_model_allowlist(database_url)
    seed_site_auth(database_url, site_id="site_queue")

    service = _runtime_service(database_url)
    completed = service.execute(
        RuntimeRequest(
            site_id="site_queue",
            ability_name="workflow/media_nightly_image_optimize",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            callback_url="https://example.com/domain",
            idempotency_key="queue-domain-callback-001",
            trace_id="trace-queue-domain-callback-001",
            input_payload={"messages": [{"role": "user", "content": "deliver callback"}]},
        )
    )

    assert completed.status == "succeeded"
    dispatcher = HttpRuntimeCallbackDispatcher(transport=httpx.MockTransport(handler))
    worker = RuntimeService(
        database_url,
        callback_dispatcher=dispatcher,
        callback_max_attempts=2,
        callback_retry_backoff_seconds=0,
    )
    dispatched = worker.dispatch_pending_callbacks(max_callbacks=1)

    assert dispatched == [
        {
            "run_id": completed.run_id,
            "callback_status": "delivered",
            "trace_id": "trace-queue-domain-callback-001",
            "status_code": 204,
        }
    ]
    assert callback_payloads[0]["run_id"] == completed.run_id
    assert callback_payloads[0]["status"] == "succeeded"

    dispose_engine(database_url)


def test_dispatch_pending_callbacks_recovers_stale_dispatching_lease(
    tmp_path: Path,
    allow_example_callback_dns: None,
) -> None:
    callback_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        callback_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(202)

    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_openai_model_allowlist(database_url)
    seed_site_auth(database_url, site_id="site_queue")

    service = _runtime_service(database_url)
    completed = service.execute(
        RuntimeRequest(
            site_id="site_queue",
            ability_name="workflow/media_nightly_image_optimize",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            callback_url="https://example.com/recover",
            idempotency_key="queue-domain-callback-recover-001",
            trace_id="trace-queue-domain-callback-recover-001",
            input_payload={"messages": [{"role": "user", "content": "recover callback"}]},
        )
    )

    with get_session(database_url) as session:
        run = session.get(RunRecord, completed.run_id)
        assert run is not None
        run.callback_status = "dispatching"
        run.callback_attempt_count = 1
        run.callback_last_attempt_at = datetime.now(UTC) - timedelta(minutes=7)
        run.callback_next_attempt_at = None
        session.commit()

    dispatcher = HttpRuntimeCallbackDispatcher(transport=httpx.MockTransport(handler))
    worker = RuntimeService(
        database_url,
        callback_dispatcher=dispatcher,
        callback_max_attempts=3,
        callback_retry_backoff_seconds=0,
    )
    dispatched = worker.dispatch_pending_callbacks(max_callbacks=1)

    assert dispatched == [
        {
            "run_id": completed.run_id,
            "callback_status": "delivered",
            "trace_id": "trace-queue-domain-callback-recover-001",
            "status_code": 202,
        }
    ]
    assert callback_payloads[0]["run_id"] == completed.run_id

    with get_session(database_url) as session:
        run = session.get(RunRecord, completed.run_id)
        assert run is not None
        assert run.callback_status == "delivered"
        assert run.callback_attempt_count == 2
        audit_event = session.scalar(
            select(ServiceAuditEvent)
            .where(ServiceAuditEvent.event_kind == "runtime.callback_dispatch_recovered")
            .order_by(ServiceAuditEvent.created_at.desc(), ServiceAuditEvent.id.desc())
        )
        assert audit_event is not None
        assert audit_event.scope_id == completed.run_id
        assert audit_event.payload_json is not None
        assert (
            audit_event.payload_json["callback_last_error_code"]
            == RUNTIME_CALLBACK_DISPATCH_LEASE_RECOVERY_ERROR_CODE
        )
        assert (
            audit_event.payload_json["recovery_action"]
            == "requeue_pending_after_stale_dispatch_lease"
        )
        assert int(audit_event.payload_json["stale_for_seconds"]) >= 300

    dispose_engine(database_url)


def test_bounded_auto_repairs_requeue_stale_queued_runs_and_audit_worker_actor(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_openai_model_allowlist(database_url)
    seed_site_auth(database_url, site_id="site_queue")

    service = _runtime_service(database_url)
    queued = service.execute(
        RuntimeRequest(
            site_id="site_queue",
            ability_name="workflow/media_nightly_image_optimize",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            execution_pattern="whole_run_offload",
            task_backend={"enabled": True, "mode": "polling"},
            idempotency_key="queue-domain-auto-repair-queued-001",
            trace_id="trace-queue-domain-auto-repair-queued-001",
            input_payload={"messages": [{"role": "user", "content": "stale queued auto repair"}]},
        )
    )

    with get_session(database_url) as session:
        run = session.get(RunRecord, queued.run_id)
        assert run is not None
        run.status = "queued"
        run.started_at = datetime.now(UTC) - timedelta(minutes=12)
        run.processing_started_at = None
        run.finished_at = None
        session.commit()

    repair = service.run_bounded_auto_repairs(
        worker_id="runtime_queue",
        max_stale_queued=5,
        max_callback_overdue=0,
        max_running_stale_suggestions=0,
    )

    assert repair["requeued_stale_queued_total"] == 1
    assert repair["redelivered_callback_overdue_total"] == 0
    assert repair["running_stale_operator_queue_total"] == 0
    assert repair["requeued_stale_queued"][0]["run_id"] == queued.run_id

    with get_session(database_url) as session:
        audit_event = session.scalar(
            select(ServiceAuditEvent)
            .where(ServiceAuditEvent.event_kind == "runtime.repair.requeue_stale_queued")
            .order_by(ServiceAuditEvent.created_at.desc(), ServiceAuditEvent.id.desc())
        )
        assert audit_event is not None
        assert audit_event.actor_kind == "system_worker"
        assert audit_event.actor_ref == "runtime_queue"
        assert audit_event.scope_id == queued.run_id

    dispose_engine(database_url)


def test_bounded_auto_repairs_redeliver_callback_overdue_runs_and_surface_operator_only_running_stale(
    tmp_path: Path,
    allow_example_callback_dns: None,
) -> None:
    callback_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        callback_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(204)

    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_openai_model_allowlist(database_url)
    seed_site_auth(database_url, site_id="site_queue")

    service = _runtime_service(database_url)
    callback_run = service.execute(
        RuntimeRequest(
            site_id="site_queue",
            ability_name="workflow/media_nightly_image_optimize",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            callback_url="https://example.com/callback-overdue",
            idempotency_key="queue-domain-auto-repair-callback-001",
            trace_id="trace-queue-domain-auto-repair-callback-001",
            input_payload={
                "messages": [{"role": "user", "content": "callback overdue auto repair"}]
            },
        )
    )
    running = service.execute(
        RuntimeRequest(
            site_id="site_queue",
            ability_name="workflow/media_nightly_image_optimize",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="queue-domain-auto-repair-running-001",
            trace_id="trace-queue-domain-auto-repair-running-001",
            input_payload={"messages": [{"role": "user", "content": "running stale suggestion"}]},
        )
    )

    with get_session(database_url) as session:
        callback_record = session.get(RunRecord, callback_run.run_id)
        running_record = session.get(RunRecord, running.run_id)
        assert callback_record is not None
        assert running_record is not None
        callback_record.status = "succeeded"
        callback_record.finished_at = datetime.now(UTC) - timedelta(minutes=15)
        callback_record.callback_status = "pending"
        callback_record.callback_next_attempt_at = datetime.now(UTC) - timedelta(minutes=12)
        callback_record.callback_last_attempt_at = datetime.now(UTC) - timedelta(minutes=13)

        running_record.status = "running"
        running_record.started_at = datetime.now(UTC) - timedelta(minutes=30)
        running_record.processing_started_at = datetime.now(UTC) - timedelta(minutes=20)
        running_record.finished_at = None
        session.commit()

    repair = service.run_bounded_auto_repairs(
        worker_id="callback_dispatch",
        max_stale_queued=0,
        max_callback_overdue=5,
        max_running_stale_suggestions=5,
    )

    assert repair["requeued_stale_queued_total"] == 0
    assert repair["redelivered_callback_overdue_total"] == 1
    assert repair["redelivered_callback_overdue"][0]["run_id"] == callback_run.run_id
    assert repair["running_stale_operator_queue_total"] == 1
    assert repair["running_stale_operator_queue"][0]["run_id"] == running.run_id
    assert repair["running_stale_operator_queue"][0]["suggested_action"] == (
        "mark_stale_running_failed"
    )
    assert repair["running_stale_operator_queue"][0]["mode"] == "operator_only"

    dispatcher = HttpRuntimeCallbackDispatcher(transport=httpx.MockTransport(handler))
    worker = RuntimeService(
        database_url,
        callback_dispatcher=dispatcher,
        callback_max_attempts=2,
        callback_retry_backoff_seconds=0,
    )
    dispatched = worker.dispatch_pending_callbacks(max_callbacks=1)

    assert dispatched[0]["run_id"] == callback_run.run_id
    assert callback_payloads[0]["run_id"] == callback_run.run_id

    with get_session(database_url) as session:
        running_record = session.get(RunRecord, running.run_id)
        assert running_record is not None
        assert running_record.status == "running"
        audit_event = session.scalar(
            select(ServiceAuditEvent)
            .where(ServiceAuditEvent.event_kind == "runtime.repair.redeliver_failed_callback")
            .order_by(ServiceAuditEvent.created_at.desc(), ServiceAuditEvent.id.desc())
        )
        assert audit_event is not None
        assert audit_event.actor_kind == "system_worker"
        assert audit_event.actor_ref == "callback_dispatch"
        assert audit_event.scope_id == callback_run.run_id

    dispose_engine(database_url)


def test_runtime_backlog_diagnostics_group_by_scope_and_classify_bottlenecks(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_openai_model_allowlist(database_url)
    seed_site_auth(
        database_url,
        site_id="site_queue",
        concurrency={"max_active_runs": 2},
    )
    seed_site_auth(database_url, site_id="site_other")

    service = _runtime_service(database_url)
    queued = service.execute(
        RuntimeRequest(
            site_id="site_queue",
            ability_name="workflow/media_nightly_image_optimize",
            ability_family="automation",
            channel="openapi",
            execution_kind="text",
            execution_pattern="whole_run_offload",
            task_backend={"enabled": True, "mode": "polling"},
            profile_id="text.balanced",
            idempotency_key="queue-domain-backlog-queued-001",
            trace_id="trace-queue-domain-backlog-queued-001",
            input_payload={"messages": [{"role": "user", "content": "queued stale backlog"}]},
        )
    )
    running = service.execute(
        RuntimeRequest(
            site_id="site_queue",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            ability_family="workflow",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="queue-domain-backlog-running-001",
            trace_id="trace-queue-domain-backlog-running-001",
            input_payload={"messages": [{"role": "user", "content": "running stale backlog"}]},
        )
    )
    other = service.execute(
        RuntimeRequest(
            site_id="site_other",
            ability_name="npcink-abilities-toolkit/build-article-block-plan",
            ability_family="workflow",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            idempotency_key="queue-domain-backlog-other-001",
            trace_id="trace-queue-domain-backlog-other-001",
            input_payload={"messages": [{"role": "user", "content": "fresh second scope"}]},
        )
    )

    with get_session(database_url) as session:
        queued_run = session.get(RunRecord, queued.run_id)
        running_run = session.get(RunRecord, running.run_id)
        other_run = session.get(RunRecord, other.run_id)
        assert queued_run is not None
        assert running_run is not None
        assert other_run is not None
        queued_run.status = "queued"
        queued_run.started_at = datetime.now(UTC) - timedelta(minutes=11)
        running_run.status = "running"
        running_run.processing_started_at = datetime.now(UTC) - timedelta(minutes=20)
        other_run.status = "queued"
        other_run.started_at = datetime.now(UTC) - timedelta(seconds=30)
        session.commit()

    backlog = service.get_runtime_backlog_diagnostics(scope_kind="site_id", limit=10)

    assert backlog["totals"]["queued"]["state"] == "stale"
    assert backlog["totals"]["running"]["state"] == "stale"
    assert backlog["totals"]["bottleneck_state"] == "mixed"
    assert backlog["totals"]["pressure_state"] == "critical"
    assert backlog["scope_pressure"]["spread_state"] == "isolated"
    assert backlog["scope_pressure"]["stale_scope_count"] == 1
    first_item = backlog["items"][0]
    assert first_item["scope_kind"] == "site_id"
    assert first_item["scope_id"] == "site_queue"
    assert first_item["queued"]["stale_runs"] == 1
    assert first_item["running"]["stale_runs"] == 1
    assert first_item["lease_recovery_inputs"]["total_stale_runs"] == 2
    assert first_item["bottleneck_state"] == "mixed"
    assert "queue.stale" in first_item["pressure_reasons"]
    assert "worker.stale" in first_item["pressure_reasons"]

    dispose_engine(database_url)


def test_callback_dispatch_recovery_logs_audit_failure_but_keeps_recovery_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    allow_example_callback_dns: None,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_openai_model_allowlist(database_url)
    seed_site_auth(database_url, site_id="site_queue")

    service = _runtime_service(database_url)
    completed = service.execute(
        RuntimeRequest(
            site_id="site_queue",
            ability_name="workflow/media_nightly_image_optimize",
            channel="openapi",
            execution_kind="text",
            profile_id="text.balanced",
            callback_url="https://example.com/recover-failure",
            input_payload={"messages": [{"role": "user", "content": "recover with audit failure"}]},
            idempotency_key="queue-domain-callback-recover-failure-001",
            trace_id="trace-queue-domain-callback-recover-failure-001",
        )
    )

    with get_session(database_url) as session:
        run = session.get(RunRecord, completed.run_id)
        assert run is not None
        run.callback_status = "dispatching"
        run.callback_attempt_count = 1
        run.callback_last_attempt_at = datetime.now(UTC) - timedelta(minutes=7)
        run.callback_next_attempt_at = None
        session.commit()

    callback_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        callback_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(202, json={"ok": True})

    dispatcher = HttpRuntimeCallbackDispatcher(transport=httpx.MockTransport(handler))
    worker = RuntimeService(
        database_url,
        callback_dispatcher=dispatcher,
        callback_max_attempts=3,
        callback_retry_backoff_seconds=0,
    )

    call_count = 0

    def raise_audit_failure(*args: object, **kwargs: object) -> None:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(
        worker.commercial_service,
        "record_service_audit_event",
        raise_audit_failure,
    )
    caplog.set_level(logging.ERROR, logger="app.domain.runtime.service")

    dispatched = worker.dispatch_pending_callbacks(max_callbacks=1)

    assert dispatched == [
        {
            "run_id": completed.run_id,
            "callback_status": "delivered",
            "trace_id": "trace-queue-domain-callback-recover-failure-001",
            "status_code": 202,
        }
    ]
    assert callback_payloads[0]["run_id"] == completed.run_id
    assert any(
        "runtime callback dispatch recovery audit failed" in record.message
        and record.exc_info is not None
        and completed.run_id in record.message
        for record in caplog.records
    )

    with get_session(database_url) as session:
        run = session.get(RunRecord, completed.run_id)
        assert run is not None
        assert run.callback_status == "delivered"
        assert run.callback_attempt_count == 2
        audit_event = session.scalar(
            select(ServiceAuditEvent)
            .where(ServiceAuditEvent.event_kind == "runtime.callback_dispatch_recovered")
            .order_by(ServiceAuditEvent.created_at.desc(), ServiceAuditEvent.id.desc())
        )
        assert audit_event is None

    dispose_engine(database_url)


def test_redis_runtime_queue_reuses_one_client_across_publish_and_consume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRedisClient:
        def __init__(self) -> None:
            self.values: list[str] = []
            self.closed = False

        def lpush(self, queue_key: str, run_id: str) -> None:
            assert queue_key == "runtime:test"
            self.values.insert(0, run_id)

        def brpop(self, queue_keys: list[str], timeout: int) -> tuple[str, str] | None:
            assert queue_keys == ["runtime:test"]
            assert timeout == 3
            if not self.values:
                return None
            return queue_keys[0], self.values.pop()

        def close(self) -> None:
            self.closed = True

    instances: list[FakeRedisClient] = []

    def fake_from_url(redis_url: str, decode_responses: bool) -> FakeRedisClient:
        assert redis_url == "redis://example"
        assert decode_responses is True
        client = FakeRedisClient()
        instances.append(client)
        return client

    monkeypatch.setattr(
        "app.adapters.queue.redis_runtime_queue.Redis.from_url",
        fake_from_url,
    )

    queue = RedisRuntimeQueue("redis://example", "runtime:test")
    queue.publish("run-1")
    assert queue.consume(3) == "run-1"
    queue.close()

    assert len(instances) == 1
    assert instances[0].closed is True


def test_http_callback_dispatcher_reuses_one_client_across_dispatches(
    monkeypatch: pytest.MonkeyPatch,
    allow_example_callback_dns: None,
) -> None:
    class FakeHttpClient:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            self.closed = False

        def post(self, url: str, *, content: bytes, headers: dict[str, str]) -> httpx.Response:
            assert url == "https://example.com/reuse"
            assert headers["X-Npcink-Run-Id"] in {"run-1", "run-2"}
            assert cast(dict[str, object], json.loads(content.decode("utf-8")))["run_id"] in {
                "run-1",
                "run-2",
            }
            return httpx.Response(204)

        def close(self) -> None:
            self.closed = True

    created_clients: list[FakeHttpClient] = []

    def fake_client(**kwargs: object) -> FakeHttpClient:
        client = FakeHttpClient(**kwargs)
        created_clients.append(client)
        return client

    monkeypatch.setattr("app.adapters.callbacks.http.httpx.Client", fake_client)

    dispatcher = HttpRuntimeCallbackDispatcher(timeout_seconds=5.0)
    dispatcher.dispatch(
        RuntimeCallbackDispatchRequest(
            run_id="run-1",
            trace_id="trace-1",
            callback_url="https://example.com/reuse",
            payload={"run_id": "run-1"},
        )
    )
    dispatcher.dispatch(
        RuntimeCallbackDispatchRequest(
            run_id="run-2",
            trace_id="trace-2",
            callback_url="https://example.com/reuse",
            payload={"run_id": "run-2"},
        )
    )
    dispatcher.close()

    assert len(created_clients) == 1
    assert created_clients[0].kwargs["timeout"] == 5.0
    assert created_clients[0].kwargs["follow_redirects"] is False
    assert created_clients[0].closed is True
