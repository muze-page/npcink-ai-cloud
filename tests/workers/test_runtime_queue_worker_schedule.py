from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.workers import runtime_queue as worker


def _schedule_after_full_batch(*, repaired_at: float = 100.0) -> worker.AutoRepairSchedule:
    schedule = worker.AutoRepairSchedule()
    assert worker._should_run_auto_repair(schedule, current_time=repaired_at) is True
    schedule = worker._record_auto_repair(schedule, current_time=repaired_at)
    return worker._record_processed_batch(
        schedule,
        processed_count=8,
        batch_size=8,
    )


def test_full_batch_skips_auto_repair_until_forced_deadline() -> None:
    repaired_at = 100.0
    schedule = _schedule_after_full_batch(repaired_at=repaired_at)

    assert worker.AUTO_REPAIR_MAX_DEFER_SECONDS == 15.0
    assert (
        worker._should_run_auto_repair(
            schedule,
            current_time=repaired_at + worker.AUTO_REPAIR_MAX_DEFER_SECONDS - 0.001,
        )
        is False
    )
    assert (
        worker._should_run_auto_repair(
            schedule,
            current_time=repaired_at + worker.AUTO_REPAIR_MAX_DEFER_SECONDS,
        )
        is True
    )


@pytest.mark.parametrize("processed_count", [0, 1, 7])
def test_partial_or_empty_batch_restores_auto_repair(processed_count: int) -> None:
    schedule = _schedule_after_full_batch()
    schedule = worker._record_processed_batch(
        schedule,
        processed_count=processed_count,
        batch_size=8,
    )

    assert worker._should_run_auto_repair(schedule, current_time=101.0) is True


def test_consecutive_full_batches_do_not_extend_forced_deadline() -> None:
    schedule = _schedule_after_full_batch(repaired_at=100.0)
    original_deadline = schedule.next_forced_at

    for _ in range(4):
        schedule = worker._record_processed_batch(
            schedule,
            processed_count=8,
            batch_size=8,
        )

    assert schedule.next_forced_at == original_deadline
    assert worker._should_run_auto_repair(schedule, current_time=115.0) is True


class _StopWorker(RuntimeError):
    pass


def test_provider_refresh_and_heartbeat_continue_when_auto_repair_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        log_level="WARNING",
        database_url="sqlite://",
        redis_url="redis://proof",
        runtime_queue_key="runtime:proof",
        runtime_worker_poll_seconds=5,
        runtime_worker_batch_size=8,
        worker_heartbeat_interval_seconds=30,
    )

    class FakeQueue:
        closed = False

        def close(self) -> None:
            self.closed = True

    class FakeLogger:
        def info(self, *_args: object) -> None:
            return None

        def warning(self, *_args: object) -> None:
            return None

    class FakeService:
        providers = {"proof-provider": object()}
        auto_repair_calls = 0
        process_calls = 0

        def run_bounded_auto_repairs(self, **_kwargs: object) -> dict[str, object]:
            self.auto_repair_calls += 1
            return worker._empty_auto_repair_result()

        def process_queued_runs(self, **_kwargs: object) -> list[dict[str, object]]:
            self.process_calls += 1
            return [{"run_id": f"run-{index}"} for index in range(8)]

    heartbeat_calls: list[dict[str, Any]] = []

    class FakeHeartbeat:
        def __init__(self, **_kwargs: object) -> None:
            return None

        def maybe_record(self, **kwargs: Any) -> bool:
            heartbeat_calls.append(dict(kwargs))
            if len(heartbeat_calls) == 3:
                raise _StopWorker
            return True

    queue = FakeQueue()
    service = FakeService()
    build_calls: list[float] = []
    monotonic_values = iter([0.0, 2.0])

    def build_service(*_args: object, **_kwargs: object) -> FakeService:
        build_calls.append(1.0)
        return service

    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "configure_logging", lambda _level: None)
    monkeypatch.setattr(worker, "require_database_connection", lambda _url: None)
    monkeypatch.setattr(worker, "get_logger", lambda _name: FakeLogger())
    monkeypatch.setattr(worker, "RedisRuntimeQueue", lambda *_args: queue)
    monkeypatch.setattr(worker, "WorkerHeartbeat", FakeHeartbeat)
    monkeypatch.setattr(worker, "_build_runtime_service", build_service)
    monkeypatch.setattr(worker, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(worker, "PROVIDER_REFRESH_SECONDS", 1.0)

    with pytest.raises(_StopWorker):
        worker.main()

    assert len(build_calls) == 2
    assert service.auto_repair_calls == 1
    assert service.process_calls == 2
    assert [call["status"] for call in heartbeat_calls] == [
        "started",
        "processed",
        "processed",
    ]
    assert heartbeat_calls[-1]["payload"]["requeued_stale_queued_total"] == 0
    assert queue.closed is True
