from __future__ import annotations

from typing import Any

from app.adapters.providers.registry import resolve_execution_provider_adapters
from app.adapters.queue.redis_runtime_queue import RedisRuntimeQueue
from app.core.config import get_settings
from app.core.db import require_database_connection
from app.core.logging import configure_logging, get_logger
from app.domain.orchestration.service import OrchestrationService
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

    logger = get_logger("magick_ai_cloud.orchestration_worker")
    providers = resolve_execution_provider_adapters(settings)

    orchestration_queue_key = settings.runtime_queue_key + ":orchestration"
    orchestration_queue = RedisRuntimeQueue(
        settings.redis_url,
        orchestration_queue_key,
    )

    runtime_queue = RedisRuntimeQueue(
        settings.redis_url,
        settings.runtime_queue_key,
    )

    runtime_service = RuntimeService(
        settings.database_url,
        settings=settings,
        providers=providers,
        runtime_queue=runtime_queue,
    )

    orchestration_service = OrchestrationService(
        settings.database_url,
        settings=settings,
        runtime_service=runtime_service,
        runtime_queue=orchestration_queue,
        callback_dispatcher=settings.callback_dispatcher if hasattr(settings, "callback_dispatcher") else None,
        callback_max_attempts=settings.runtime_callback_max_attempts,
        callback_retry_backoff_seconds=settings.runtime_callback_retry_backoff_seconds,
    )

    heartbeat = WorkerHeartbeat(
        settings=settings,
        worker_id="orchestration_worker",
        interval_seconds=settings.worker_heartbeat_interval_seconds,
    )

    poll_seconds = getattr(settings, "orchestration_worker_poll_seconds", 5)
    batch_size = getattr(settings, "orchestration_worker_batch_size", 1)

    logger.info(
        "orchestration worker started (poll=%ss, batch=%s, queue=%s)",
        poll_seconds,
        batch_size,
        orchestration_queue_key,
    )
    heartbeat.maybe_record(
        status="started",
        payload={
            "batch_size": batch_size,
            "queue_key": orchestration_queue_key,
        },
        force=True,
    )

    try:
        while True:
            try:
                orchestration_run_id = orchestration_queue.consume(poll_seconds)
            except Exception as e:
                logger.error("Failed to consume from orchestration queue: %s", e)
                continue

            if not orchestration_run_id:
                heartbeat.maybe_record(
                    status="idle",
                    payload={"queue_key": orchestration_queue_key},
                )
                continue

            logger.info(
                "Processing orchestration run: %s",
                orchestration_run_id,
            )

            try:
                result = orchestration_service.execute_next_step(
                    orchestration_run_id
                )
                logger.info(
                    "Orchestration run %s result: %s",
                    orchestration_run_id,
                    result.get("status", "unknown"),
                )
                heartbeat.maybe_record(
                    status="processed",
                    payload={
                        "orchestration_run_id": orchestration_run_id,
                        "result_status": result.get("status"),
                    },
                )
            except Exception as e:
                logger.error(
                    "Failed to process orchestration run %s: %s",
                    orchestration_run_id,
                    e,
                    exc_info=True,
                )
                heartbeat.maybe_record(
                    status="error",
                    payload={
                        "orchestration_run_id": orchestration_run_id,
                        "error": str(e),
                    },
                )
    except KeyboardInterrupt:
        logger.info("Orchestration worker shutting down")
    finally:
        _close_if_supported(orchestration_queue)
        _close_if_supported(runtime_queue)
        heartbeat.maybe_record(
            status="stopped",
            payload={},
            force=True,
        )


if __name__ == "__main__":
    main()
