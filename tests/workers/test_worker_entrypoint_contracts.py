from __future__ import annotations

from pathlib import Path


def _workers_root() -> Path:
    return Path(__file__).resolve().parents[2] / "app" / "workers"


def test_runtime_queue_worker_only_processes_execution_backlog() -> None:
    source = (_workers_root() / "runtime_queue.py").read_text()

    assert "process_queued_runs" in source
    assert "dispatch_pending_callbacks" not in source


def test_runtime_queue_worker_refreshes_execution_providers_with_ttl() -> None:
    source = (_workers_root() / "runtime_queue.py").read_text()

    assert "resolve_execution_provider_adapters(settings)" in source
    assert "PROVIDER_REFRESH_SECONDS" in source
    assert "next_provider_refresh_at" in source
    assert "runtime queue execution providers resolved" in source


def test_callback_dispatch_worker_exists_as_separate_entrypoint() -> None:
    source = (_workers_root() / "callback_dispatch.py").read_text()

    assert "dispatch_pending_callbacks" in source
    assert "runtime_callback_worker_poll_seconds" in source
