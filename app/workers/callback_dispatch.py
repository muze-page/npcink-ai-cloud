from __future__ import annotations

import time
from typing import Any

from app.adapters.callbacks.http import HttpRuntimeCallbackDispatcher
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

    logger = get_logger("magick_ai_cloud.callback_dispatch")
    callback_dispatcher = HttpRuntimeCallbackDispatcher(
        timeout_seconds=settings.runtime_callback_timeout_seconds,
    )
    service = RuntimeService(
        settings.database_url,
        settings=settings,
        callback_dispatcher=callback_dispatcher,
        callback_max_attempts=settings.runtime_callback_max_attempts,
        callback_retry_backoff_seconds=settings.runtime_callback_retry_backoff_seconds,
    )
    heartbeat = WorkerHeartbeat(
        settings=settings,
        worker_id="callback_dispatch",
        interval_seconds=settings.worker_heartbeat_interval_seconds,
    )

    logger.info(
        "callback dispatch worker started (poll=%ss, batch=%s)",
        settings.runtime_callback_worker_poll_seconds,
        settings.runtime_callback_batch_size,
    )
    heartbeat.maybe_record(
        status="started",
        payload={"batch_size": settings.runtime_callback_batch_size},
        force=True,
    )

    try:
        while True:
            auto_repair = service.run_bounded_auto_repairs(
                worker_id="callback_dispatch",
                max_stale_queued=0,
                max_callback_overdue=settings.runtime_callback_batch_size,
                max_running_stale_suggestions=0,
            )
            callbacks = service.dispatch_pending_callbacks(
                max_callbacks=settings.runtime_callback_batch_size,
            )
            heartbeat_status = (
                "processed"
                if callbacks
                else "repairing"
                if int(auto_repair.get("redelivered_callback_overdue_total") or 0) > 0
                else "idle"
            )
            heartbeat.maybe_record(
                status=heartbeat_status,
                payload={
                    "processed_callbacks": len(callbacks),
                    "redelivered_callback_overdue_total": int(
                        auto_repair.get("redelivered_callback_overdue_total") or 0
                    ),
                },
            )
            if not callbacks:
                if int(auto_repair.get("redelivered_callback_overdue_total") or 0) > 0:
                    logger.info(
                        "callback worker auto-redelivered overdue callbacks: count=%s run_ids=%s",
                        auto_repair["redelivered_callback_overdue_total"],
                        [
                            item["run_id"]
                            for item in auto_repair.get("redelivered_callback_overdue", [])
                            if isinstance(item, dict)
                        ],
                    )
                time.sleep(settings.runtime_callback_worker_poll_seconds)
                continue
            logger.info(
                "runtime callback batch processed: count=%s run_ids=%s",
                len(callbacks),
                [result["run_id"] for result in callbacks],
            )
    finally:
        _close_if_supported(callback_dispatcher)


if __name__ == "__main__":
    main()
