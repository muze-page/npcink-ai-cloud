from __future__ import annotations

from pathlib import Path


def _workers_root() -> Path:
    return Path(__file__).resolve().parents[2] / "app" / "workers"


def test_runtime_queue_worker_only_processes_execution_backlog() -> None:
    source = (_workers_root() / "runtime_queue.py").read_text()

    assert "process_queued_runs" in source
    assert "dispatch_pending_callbacks" not in source


def test_callback_dispatch_worker_exists_as_separate_entrypoint() -> None:
    source = (_workers_root() / "callback_dispatch.py").read_text()

    assert "dispatch_pending_callbacks" in source
    assert "runtime_callback_worker_poll_seconds" in source


def test_addon_projection_workers_exist_as_separate_entrypoints() -> None:
    overview_source = (_workers_root() / "addon_overview_projection.py").read_text()
    provider_source = (_workers_root() / "provider_release_summary_projection.py").read_text()

    assert "refresh_addon_overview_projections" in overview_source
    assert "def run_once" in overview_source
    assert "refresh_provider_release_summary_projections" in provider_source
    assert "def run_once" in provider_source
