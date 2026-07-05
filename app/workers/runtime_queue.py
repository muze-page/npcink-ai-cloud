from __future__ import annotations

from typing import Any, cast

from app.adapters.providers.registry import resolve_execution_provider_adapters
from app.adapters.queue.base import RuntimeQueue
from app.adapters.queue.redis_runtime_queue import RedisRuntimeQueue
from app.core.config import Settings, get_settings
from app.core.db import require_database_connection
from app.core.logging import configure_logging, get_logger
from app.domain.runtime.service import RuntimeService
from app.workers.heartbeat import WorkerHeartbeat


def _close_if_supported(resource: Any) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        close()


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return default


def _dict_items(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [
        {str(key): item for key, item in candidate.items()}
        for candidate in value
        if isinstance(candidate, dict)
    ]


def _build_runtime_service(settings: Settings, runtime_queue: RuntimeQueue) -> RuntimeService:
    return RuntimeService(
        settings.database_url,
        settings=settings,
        providers=resolve_execution_provider_adapters(settings),
        runtime_queue=runtime_queue,
    )


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    require_database_connection(settings.database_url)

    logger = get_logger("npcink_ai_cloud.runtime_queue")
    runtime_queue = RedisRuntimeQueue(
        settings.redis_url,
        settings.runtime_queue_key,
    )
    heartbeat = WorkerHeartbeat(
        settings=settings,
        worker_id="runtime_queue",
        interval_seconds=settings.worker_heartbeat_interval_seconds,
    )
    last_provider_ids: tuple[str, ...] = ()

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
            service = _build_runtime_service(settings, runtime_queue)
            provider_ids = tuple(sorted(service.providers))
            if provider_ids != last_provider_ids:
                logger.info(
                    "runtime queue execution providers resolved: provider_ids=%s",
                    list(provider_ids),
                )
                last_provider_ids = provider_ids
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
                    _coerce_int(auto_repair.get("requeued_stale_queued_total")) > 0
                    or _coerce_int(auto_repair.get("running_stale_operator_queue_total")) > 0
                )
                else "idle"
            )
            heartbeat.maybe_record(
                status=heartbeat_status,
                payload={
                    "processed_runs": len(results),
                    "execution_provider_ids": list(provider_ids),
                    "requeued_stale_queued_total": _coerce_int(
                        auto_repair.get("requeued_stale_queued_total")
                    ),
                    "running_stale_operator_queue_total": _coerce_int(
                        auto_repair.get("running_stale_operator_queue_total")
                    ),
                },
            )
            if not results:
                requeued_total = _coerce_int(auto_repair.get("requeued_stale_queued_total"))
                if requeued_total > 0:
                    logger.info(
                        "runtime queue auto-requeued stale queued runs: count=%s run_ids=%s",
                        requeued_total,
                        [
                            item.get("run_id")
                            for item in _dict_items(auto_repair.get("requeued_stale_queued"))
                        ],
                    )
                running_stale_total = _coerce_int(
                    auto_repair.get("running_stale_operator_queue_total")
                )
                if running_stale_total > 0:
                    logger.warning(
                        "runtime queue observed stale running runs requiring operator action: "
                        "count=%s run_ids=%s",
                        running_stale_total,
                        [
                            item.get("run_id")
                            for item in _dict_items(auto_repair.get("running_stale_operator_queue"))
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
