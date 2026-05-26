from __future__ import annotations

from typing import Any

from app.adapters.providers.registry import resolve_execution_provider_adapters
from app.adapters.queue.redis_runtime_queue import RedisRuntimeQueue
from app.core.config import get_settings
from app.core.db import require_database_connection
from app.core.logging import configure_logging, get_logger
from app.domain.runtime.service import RuntimeService
from app.workers.heartbeat import WorkerHeartbeat


def _close_if_supported(resource: Any) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        close()


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    require_database_connection(settings.database_url)

    logger = get_logger("magick_ai_cloud.runtime_queue")
    providers = resolve_execution_provider_adapters(settings)
    runtime_queue = RedisRuntimeQueue(
        settings.redis_url,
        settings.runtime_queue_key,
    )
    service = RuntimeService(
        settings.database_url,
        settings=settings,
        providers=providers,
        runtime_queue=runtime_queue,
    )
    heartbeat = WorkerHeartbeat(
        settings=settings,
        worker_id="runtime_queue",
        interval_seconds=settings.worker_heartbeat_interval_seconds,
    )

    logger.info(
        "runtime queue worker started (poll=%ss, batch=%s, queue=%s)",
        settings.runtime_worker_poll_seconds,
        settings.runtime_worker_batch_size,
        settings.runtime_queue_key,
    )
    heartbeat.maybe_record(
        status="started",
        payload={
            "batch_size": settings.runtime_worker_batch_size,
            "queue_key": settings.runtime_queue_key,
        },
        force=True,
    )

    try:
        while True:
            auto_repair = service.run_bounded_auto_repairs(
                worker_id="runtime_queue",
                max_stale_queued=settings.runtime_worker_batch_size,
                max_callback_overdue=0,
                max_running_stale_suggestions=settings.runtime_worker_batch_size,
            )
            results = service.process_queued_runs(
                max_runs=settings.runtime_worker_batch_size,
                timeout_seconds=settings.runtime_worker_poll_seconds,
            )
            heartbeat_status = (
                "processed"
                if results
                else "repairing"
                if (
                    int(auto_repair.get("requeued_stale_queued_total") or 0) > 0
                    or int(auto_repair.get("running_stale_operator_queue_total") or 0) > 0
                )
                else "idle"
            )
            heartbeat.maybe_record(
                status=heartbeat_status,
                payload={
                    "processed_runs": len(results),
                    "requeued_stale_queued_total": int(
                        auto_repair.get("requeued_stale_queued_total") or 0
                    ),
                    "running_stale_operator_queue_total": int(
                        auto_repair.get("running_stale_operator_queue_total") or 0
                    ),
                },
            )
            if not results:
                if int(auto_repair.get("requeued_stale_queued_total") or 0) > 0:
                    logger.info(
                        "runtime queue auto-requeued stale queued runs: count=%s run_ids=%s",
                        auto_repair["requeued_stale_queued_total"],
                        [
                            item["run_id"]
                            for item in auto_repair.get("requeued_stale_queued", [])
                            if isinstance(item, dict)
                        ],
                    )
                if int(auto_repair.get("running_stale_operator_queue_total") or 0) > 0:
                    logger.warning(
                        "runtime queue observed stale running runs requiring operator action: count=%s run_ids=%s",
                        auto_repair["running_stale_operator_queue_total"],
                        [
                            item["run_id"]
                            for item in auto_repair.get("running_stale_operator_queue", [])
                            if isinstance(item, dict)
                        ],
                    )
                continue
            if results:
                logger.info(
                    "runtime queue processed batch: count=%s run_ids=%s",
                    len(results),
                    [result["run_id"] for result in results],
                )
    finally:
        _close_if_supported(runtime_queue)


if __name__ == "__main__":
    main()
