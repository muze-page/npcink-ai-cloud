from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib.util
import json
import re
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from urllib.parse import urlsplit

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "scripts" / "p5_b4_runtime_load_soak.py"
COMPOSE = ROOT / "docker-compose.p5-b4-runtime-proof.yml"
WRAPPER = ROOT / "scripts" / "check-p5-b4-runtime-load-soak.sh"
API_PROCESS_IDENTITY_SHA256 = "c" * 64
WORKER_PROCESS_IDENTITY_SHA256 = "d" * 64


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _shell_function(source: str, name: str) -> str:
    match = re.search(
        rf"^{re.escape(name)}\(\) \{{.*?^\}}$",
        source,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None
    return match.group(0)


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("p5_b4_runtime_load_soak", HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def harness() -> ModuleType:
    return _module()


def _valid_diagnostics(harness: ModuleType, *, sample_count: int = 2) -> dict[str, object]:
    assert sample_count >= 2
    observations = [
        harness.Observation(
            request_hash="a" * 64,
            run_id="",
            http_status=400,
            runtime_status="",
            error_code="auth.site_mismatch",
            elapsed_ms=1.0,
            phase="cross_site",
        ),
        harness.Observation(
            request_hash="b" * 64,
            run_id="run-safe",
            http_status=200,
            runtime_status="succeeded",
            error_code="",
            elapsed_ms=1.0,
            phase="soak",
        ),
    ]
    summary = harness._diagnostic_summary(observations)
    extra = sample_count - 2
    summary["sample_count"] += extra
    summary["by_http_status"]["200"] += extra
    summary["by_error_code"]["none"] += extra
    summary["by_runtime_status"]["succeeded"] += extra
    summary["by_phase"]["soak"] += extra
    summary["by_phase_and_error_code"]["soak"]["none"] += extra
    assert harness._diagnostics_valid(summary) is True
    return summary


def _resource_row(
    elapsed_seconds: int | float,
    api_rss_bytes: int,
    api_fd_count: int,
    worker_rss_bytes: int,
    worker_fd_count: int,
    postgres_connections: int,
    api_restart_count: int = 0,
    worker_restart_count: int = 0,
    api_running: int = 1,
    worker_running: int = 2,
    api_process_count: int = 3,
    worker_process_count: int = 2,
    api_process_identity_sha256: str = API_PROCESS_IDENTITY_SHA256,
    worker_process_identity_sha256: str = WORKER_PROCESS_IDENTITY_SHA256,
) -> str:
    """Build one v5 aggregate sampler row while preserving the first ten columns."""
    return "\t".join(
        str(value)
        for value in (
            elapsed_seconds,
            api_rss_bytes,
            api_fd_count,
            worker_rss_bytes,
            worker_fd_count,
            postgres_connections,
            api_restart_count,
            worker_restart_count,
            api_running,
            worker_running,
            api_process_count,
            worker_process_count,
            api_process_identity_sha256,
            worker_process_identity_sha256,
        )
    )


def _valid_queue_timing(harness: ModuleType, count: int) -> dict[str, object]:
    submitted_at = datetime(2026, 7, 19, tzinfo=UTC)
    runs = [
        SimpleNamespace(
            started_at=submitted_at,
            processing_started_at=submitted_at + timedelta(seconds=1 + index / 100),
        )
        for index in range(count)
    ]
    evidence = harness._queue_timing_evidence(
        runs,
        expected_count=count,
        cohort_size=harness.DEFAULT_WORKER_BATCH_SIZE,
    )
    assert evidence["complete"] is True
    return evidence


def _valid_phase_stats(*, samples: int, rate: float, concurrency: int) -> dict[str, object]:
    return {
        "actual_phase_wall_seconds": float(samples / rate),
        "achieved_requests_per_second": float(rate),
        "achieved_rate_ratio": 1.0,
        "scheduler_drift_p95_ms": 0.0,
        "scheduler_drift_max_ms": 0.0,
        "semaphore_wait_p95_ms": 0.0,
        "semaphore_wait_max_ms": 0.0,
        "max_in_flight": concurrency,
        "sample_count": samples,
    }


def _valid_rss_growth(harness: ModuleType, *, formal: bool) -> dict[str, object]:
    if formal:
        window = {
            "sample_count": 12,
            "sample_span_seconds": 55.0,
            "minimum_sample_count": 12,
            "minimum_span_seconds": 55.0,
            "median_rss_bytes": 1_000_000.0,
            "complete": True,
        }
        idle = {
            "required": True,
            "evaluated": True,
            "method": "four_block_budget_confirmation_v1",
            "sample_count": 12,
            "sample_span_seconds": 55.0,
            "minimum_sample_count": 12,
            "minimum_span_seconds": 55.0,
            "block_sample_counts": [3, 3, 3, 3],
            "block_median_rss_bytes": [1_000_000.0] * 4,
            "baseline_median_rss_bytes": 1_000_000.0,
            "budget_ceiling_rss_bytes": 1_100_000.0,
            "last_two_block_median_rss_bytes": [1_000_000.0, 1_000_000.0],
            "status": "within_budget",
            "within_budget": True,
        }
        return {
            "evaluated": True,
            "method": "steady_endpoint_window_median_v1",
            "threshold_percent": 10.0,
            "observed_measured_sample_count": 120,
            "baseline_window": dict(window),
            "terminal_window": dict(window),
            "windows_non_overlapping": True,
            "growth_percent": 0.0,
            "growth_percent_rounded": 0.0,
            "active_within_budget": True,
            "idle_confirmation": idle,
            "within_budget": True,
        }
    empty_window = {
        "sample_count": 0,
        "sample_span_seconds": None,
        "minimum_sample_count": 12,
        "minimum_span_seconds": 55.0,
        "median_rss_bytes": None,
        "complete": False,
    }
    return {
        "evaluated": False,
        "method": "steady_endpoint_window_median_v1",
        "threshold_percent": 10.0,
        "observed_measured_sample_count": 2,
        "baseline_window": dict(empty_window),
        "terminal_window": dict(empty_window),
        "windows_non_overlapping": False,
        "growth_percent": None,
        "growth_percent_rounded": None,
        "active_within_budget": None,
        "idle_confirmation": {
            "required": False,
            "evaluated": False,
            "method": "four_block_budget_confirmation_v1",
            "sample_count": 0,
            "sample_span_seconds": 0.0,
            "minimum_sample_count": 12,
            "minimum_span_seconds": 55.0,
            "block_sample_counts": [],
            "block_median_rss_bytes": [],
            "baseline_median_rss_bytes": None,
            "budget_ceiling_rss_bytes": None,
            "last_two_block_median_rss_bytes": [],
            "status": "not_evaluated",
            "within_budget": None,
        },
        "within_budget": None,
    }


def _valid_process_cohort(harness: ModuleType, *, sample_count: int) -> dict[str, object]:
    def service(count: int, minimum: int, identity: str) -> dict[str, object]:
        return {
            "sample_count": sample_count,
            "minimum_process_count": minimum,
            "process_counts": [count],
            "process_count_stable": True,
            "minimum_process_count_met": True,
            "identity_sha256_values": [identity],
            "identity_sha256_unique": True,
            "passed": True,
        }

    return {
        "scope": "measured_and_idle_samples",
        "evaluated": True,
        "sample_count": sample_count,
        "api": service(3, 3, API_PROCESS_IDENTITY_SHA256),
        "worker": service(2, harness.FORMAL_WORKER_REPLICAS, WORKER_PROCESS_IDENTITY_SHA256),
        "all_valid": True,
    }


def _valid_resource_trend(
    harness: ModuleType,
    *,
    formal: bool,
    measured_count: int,
    idle_count: int,
    idle_span: float,
    idle_complete: bool,
    level: float,
) -> dict[str, object]:
    method = "six_block_median_low_with_terminal_subwindows_and_post_load_idle_confirmation"
    minimum_count = 108 if formal else 1
    evaluated = formal and measured_count >= minimum_count
    if not evaluated:
        return {
            "sample_count": measured_count,
            "evaluated": False,
            "method": method,
            "block_sample_counts": [],
            "block_median_levels": [],
            "new_high_event_blocks": [],
            "new_high_event_count": 0,
            "first_to_last_delta": 0.0,
            "global_candidate_growth": False,
            "global_sustained_growth": False,
            "terminal_window": {
                "evaluated": False,
                "block_sample_counts": [],
                "block_median_levels": [],
                "new_high_event_blocks": [],
                "new_high_event_count": 0,
                "first_to_last_delta": 0.0,
                "candidate_growth": False,
                "sustained_growth": False,
            },
            "idle_recovery": {
                "required": formal,
                "evaluated": False,
                "sample_count": idle_count,
                "sample_span_seconds": idle_span,
                "minimum_sample_count": harness.FORMAL_RESOURCE_IDLE_MIN_SAMPLES,
                "minimum_span_seconds": harness.FORMAL_RESOURCE_IDLE_MIN_SPAN_SECONDS,
                "samples_complete": idle_complete,
                "block_sample_counts": [],
                "block_median_levels": [],
                "reference_level": None,
                "retained_growth_threshold": None,
                "last_two_block_levels": [],
                "continued_growth_candidate": False,
                "status": "not_evaluated",
            },
            "least_squares_slope_per_minute": 0.0,
            "candidate_growth": False,
            "confirmed_sustained_growth": False,
            "sustained_growth": False,
        }

    block_counts = [
        (index + 1) * measured_count // 6 - index * measured_count // 6 for index in range(6)
    ]
    terminal_count = block_counts[-1]
    terminal_counts = [
        (index + 1) * terminal_count // 4 - index * terminal_count // 4 for index in range(4)
    ]
    idle_counts = (
        [(index + 1) * idle_count // 4 - index * idle_count // 4 for index in range(4)]
        if idle_complete
        else []
    )
    return {
        "sample_count": measured_count,
        "evaluated": True,
        "method": method,
        "block_sample_counts": block_counts,
        "block_median_levels": [level] * 6,
        "new_high_event_blocks": [],
        "new_high_event_count": 0,
        "first_to_last_delta": 0.0,
        "global_candidate_growth": False,
        "global_sustained_growth": False,
        "terminal_window": {
            "evaluated": True,
            "block_sample_counts": terminal_counts,
            "block_median_levels": [level] * 4,
            "new_high_event_blocks": [],
            "new_high_event_count": 0,
            "first_to_last_delta": 0.0,
            "candidate_growth": False,
            "sustained_growth": False,
        },
        "idle_recovery": {
            "required": True,
            "evaluated": idle_complete,
            "sample_count": idle_count,
            "sample_span_seconds": idle_span,
            "minimum_sample_count": harness.FORMAL_RESOURCE_IDLE_MIN_SAMPLES,
            "minimum_span_seconds": harness.FORMAL_RESOURCE_IDLE_MIN_SPAN_SECONDS,
            "samples_complete": idle_complete,
            "block_sample_counts": idle_counts,
            "block_median_levels": [level] * 4 if idle_complete else [],
            "reference_level": level,
            "retained_growth_threshold": level + 2.0,
            "last_two_block_levels": [level, level] if idle_complete else [],
            "continued_growth_candidate": False,
            "status": "recovered" if idle_complete else "insufficient_samples",
        },
        "least_squares_slope_per_minute": 0.0,
        "candidate_growth": False,
        "confirmed_sustained_growth": False,
        "sustained_growth": False,
    }


def _valid_resources(harness: ModuleType, *, formal: bool) -> dict[str, object]:
    sample_count = 132 if formal else 2
    measured_count = 120 if formal else 2
    idle_count = 12 if formal else 0
    idle_span = 55.0 if formal else 0.0
    idle_complete = True
    return {
        "sample_count": sample_count,
        "measured_sample_count": measured_count,
        "minimum_sample_count": 108 if formal else 1,
        "measured_sample_count_passed": True,
        "idle_recovery_required": formal,
        "idle_recovery_sample_count": idle_count,
        "idle_recovery_minimum_sample_count": 12,
        "idle_recovery_sample_span_seconds": idle_span,
        "idle_recovery_minimum_span_seconds": 55.0,
        "idle_recovery_samples_complete": True,
        "sample_count_passed": True,
        "warmup_boundary_elapsed_seconds": 0.0,
        "load_end_boundary_elapsed_seconds": 595.0 if formal else 5.0,
        "idle_end_boundary_elapsed_seconds": 655.0 if formal else 5.0,
        "api_peak_rss_bytes": 1_000_000,
        "worker_peak_rss_bytes": 2_000_000,
        "api_rss_growth": _valid_rss_growth(harness, formal=formal),
        "worker_rss_growth": _valid_rss_growth(harness, formal=formal),
        "process_cohort_evidence": _valid_process_cohort(harness, sample_count=sample_count),
        "api_fd_sustained_growth": False,
        "worker_fd_sustained_growth": False,
        "postgres_connection_sustained_growth": False,
        "api_fd_trend": _valid_resource_trend(
            harness,
            formal=formal,
            measured_count=measured_count,
            idle_count=idle_count,
            idle_span=idle_span,
            idle_complete=idle_complete,
            level=10.0,
        ),
        "worker_fd_trend": _valid_resource_trend(
            harness,
            formal=formal,
            measured_count=measured_count,
            idle_count=idle_count,
            idle_span=idle_span,
            idle_complete=idle_complete,
            level=20.0,
        ),
        "postgres_connection_trend": _valid_resource_trend(
            harness,
            formal=formal,
            measured_count=measured_count,
            idle_count=idle_count,
            idle_span=idle_span,
            idle_complete=idle_complete,
            level=3.0,
        ),
        "services_survived_all_samples": True,
        "restart_count_zero": True,
    }


def _record(
    harness: ModuleType,
    index: int,
    *,
    mode: str = "formal",
    p95: float = 100.0,
    p99: float = 150.0,
) -> dict:
    shape = harness._expected_record_shape(mode)
    formal = mode == "formal"
    warmup_samples = max(1, round(shape.warmup_seconds * shape.request_rate))
    soak_samples = max(1, round(shape.duration_seconds * shape.request_rate))
    attempted = 1 + shape.concurrency + shape.queue_burst + warmup_samples + soak_samples
    queue_timing = _valid_queue_timing(harness, shape.queue_burst)
    dataset_raw = json.dumps(
        harness.EXPECTED_DATASET_CONFIG,
        sort_keys=True,
        separators=(",", ":"),
    )
    checks = dict.fromkeys(harness.RECORD_CHECK_IDS, True)
    return {
        "contract": harness.CONTRACT_ID,
        "generated_at": datetime(2026, 7, 19, tzinfo=UTC).isoformat(),
        "mode": mode,
        "baseline_index": index,
        "baseline_environment_receipt_sha256": f"{index:064x}",
        "verdict": "record_passed",
        "record_thresholds_passed": True,
        "formal_record_shape": formal,
        "formal_acceptance": False,
        "production_slo_claim": False,
        "identity": {
            "revision": "a" * 40,
            "proof_image": f"sha256:{'b' * 64}",
            "context_sha256": "c" * 64,
            "harness_sha256": "d" * 64,
            "compose_sha256": "e" * 64,
            "wrapper_sha256": "f" * 64,
            "git_status_sha256": "1" * 64,
            "git_dirty": False,
            "git_dirty_count": 0,
            "postgres_image": f"sha256:{'2' * 64}",
            "redis_image": f"sha256:{'3' * 64}",
            "migration_manifest_sha256": "4" * 64,
            "migration_head_sha256": "5" * 64,
            "migration_head_source_sha256": "6" * 64,
            "environment_fingerprint": "7" * 64,
            "dataset_fingerprint": harness.EXPECTED_DATASET_ID,
            "dataset_config": json.loads(dataset_raw),
            "dataset_sha256": hashlib.sha256(dataset_raw.encode()).hexdigest(),
            "docker": {
                "arch": "arm64",
                "cpu_count": "8",
                "memory_bytes": "17179869184",
                "server_version": "test",
                "compose_version": "test",
                "background_container_count": "0",
            },
        },
        "configuration": harness._record_configuration(
            shape,
            provider_delay_ms=harness.FORMAL_PROVIDER_DELAY_MS,
        ),
        "scheduler": {
            "warmup": _valid_phase_stats(
                samples=warmup_samples,
                rate=shape.request_rate,
                concurrency=shape.concurrency,
            ),
            "measured": _valid_phase_stats(
                samples=soak_samples,
                rate=shape.request_rate,
                concurrency=shape.concurrency,
            ),
            "concurrency_probe_client_max": shape.concurrency,
            "concurrency_probe_provider_max": shape.concurrency,
        },
        "requests": {
            "attempted": attempted,
            "accepted": attempted,
            "completed": attempted,
            "accepted_rate": 1.0,
            "completed_rate": 1.0,
            "unexpected_5xx": 0,
        },
        "observation_diagnostics": _valid_diagnostics(harness, sample_count=attempted + 1),
        "queue": {
            "requested": shape.queue_burst,
            "accepted": shape.queue_burst,
            "completed": shape.queue_burst,
            "wait_p95_seconds": queue_timing["wait_seconds"]["p95"],
            "timing_evidence": queue_timing,
            "result_read_succeeded": True,
        },
        "latency": {
            "attempted_sample_count": soak_samples,
            "accepted_sample_count": soak_samples,
            "sample_count": soak_samples,
            "missing_persistent_evidence_count": 0,
            "provider_excluded_p95_ms": float(p95),
            "provider_excluded_p99_ms": float(p99),
            "proof_provider_wall_p95_ms": 150.0,
            "database_provider_call_p95_ms": 150.0,
            "exclusion_method": (
                "client_elapsed_minus_max_persistent_provider_wall_and_database_provider_call"
            ),
            "all_accepted_samples_have_persistent_provider_evidence": True,
        },
        "integrity": {
            "observed_records": attempted,
            "database_records": attempted,
            "observed_identifier_set_exact": True,
            "succeeded_records": attempted,
            "provider_call_records": attempted,
            "provider_invocations": attempted,
            "provider_invocation_set_exact": True,
            "provider_usage_key_set_exact": True,
            "run_usage_key_set_exact": True,
            "provider_meter_set_exact": True,
            "provider_meter_mismatches": 0,
            "usage_event_contract_violations": 0,
            "duplicates_or_missing": 0,
            "queued_residue": 0,
            "running_residue": 0,
            "dispatching_residue": 0,
            "redis_queue_residue": 0,
            "provider_active_residue": 0,
            "provider_max_concurrency": shape.concurrency,
            "provider_barrier_timeouts": 0,
            "artifact_records": 0,
            "queue_timing_evidence": queue_timing,
            "queue_wait_p95_seconds": queue_timing["wait_seconds"]["p95"],
        },
        "isolation": {
            "payload_mismatch_zero_side_effect": True,
            "cross_site_record_read_rejected": True,
            "cross_site_result_read_rejected": True,
            "own_site_result_read_succeeded": True,
        },
        "resources": _valid_resources(harness, formal=formal),
        "checks": checks,
        "boundary": dict(harness.RECORD_BOUNDARY),
        "redaction": dict(harness.RECORD_REDACTION),
        "limitations": list(harness.RECORD_LIMITATIONS),
    }


def _mark_record_failed(record: dict, *check_ids: str) -> None:
    for check_id in check_ids:
        record["checks"][check_id] = False
    record["record_thresholds_passed"] = False
    record["verdict"] = "record_failed"


def _zero_accepted_record(harness: ModuleType, record: dict) -> None:
    attempted = record["requests"]["attempted"]
    observations = [
        harness.Observation(
            request_hash="a" * 64,
            run_id="",
            http_status=400,
            runtime_status="",
            error_code="auth.site_mismatch",
            elapsed_ms=1.0,
            phase="cross_site",
        ),
        *[
            harness.Observation(
                request_hash=f"{index:064x}",
                run_id="",
                http_status=400,
                runtime_status="",
                error_code="auth.invalid_signature",
                elapsed_ms=1.0,
                phase="soak",
            )
            for index in range(attempted)
        ],
    ]
    diagnostics = harness._diagnostic_summary(observations)
    assert diagnostics["complete"] is True
    shape = harness._expected_record_shape(record["mode"])
    queue_timing = harness._queue_timing_evidence(
        [],
        expected_count=shape.queue_burst,
        cohort_size=harness.DEFAULT_WORKER_BATCH_SIZE,
    )
    assert queue_timing["complete"] is False
    record["requests"].update(
        accepted=0,
        completed=0,
        accepted_rate=0.0,
        completed_rate=0.0,
    )
    record["observation_diagnostics"] = diagnostics
    record["queue"].update(
        accepted=0,
        completed=0,
        wait_p95_seconds=0.0,
        timing_evidence=queue_timing,
        result_read_succeeded=False,
    )
    record["latency"].update(
        accepted_sample_count=0,
        sample_count=0,
        missing_persistent_evidence_count=0,
        provider_excluded_p95_ms=0.0,
        provider_excluded_p99_ms=0.0,
        proof_provider_wall_p95_ms=0.0,
        database_provider_call_p95_ms=0.0,
        all_accepted_samples_have_persistent_provider_evidence=True,
    )
    record["scheduler"]["concurrency_probe_provider_max"] = 0
    record["integrity"].update(
        observed_records=0,
        database_records=0,
        succeeded_records=0,
        provider_call_records=0,
        provider_invocations=0,
        provider_max_concurrency=0,
        queue_timing_evidence=queue_timing,
        queue_wait_p95_seconds=0.0,
    )
    _mark_record_failed(
        record,
        "accepted_rate",
        "completed_rate",
        "queue_requested_accepted_completed_exact",
        "queue_timing_evidence_complete",
        "proof_fixture_rejections_zero",
        "real_concurrency_observed",
    )


def _incomplete_queue_record(harness: ModuleType, record: dict) -> None:
    shape = harness._expected_record_shape(record["mode"])
    submitted_at = datetime(2026, 7, 19, tzinfo=UTC)
    runs = [
        SimpleNamespace(
            run_id=f"queue-{index}",
            started_at=submitted_at,
            processing_started_at=(
                None if index == 0 else submitted_at + timedelta(seconds=1 + index / 100)
            ),
        )
        for index in range(shape.queue_burst)
    ]
    queue_timing = harness._queue_timing_evidence(
        runs,
        expected_count=shape.queue_burst,
        cohort_size=harness.DEFAULT_WORKER_BATCH_SIZE,
    )
    assert queue_timing["sample_count"] == shape.queue_burst
    assert queue_timing["complete"] is False
    wait_p95 = queue_timing["wait_seconds"]["p95"]
    record["queue"]["timing_evidence"] = queue_timing
    record["queue"]["wait_p95_seconds"] = wait_p95
    record["integrity"]["queue_timing_evidence"] = queue_timing
    record["integrity"]["queue_wait_p95_seconds"] = wait_p95
    _mark_record_failed(record, "queue_timing_evidence_complete")


def _formal_rss_insufficient_record(harness: ModuleType, record: dict) -> None:
    measured_samples = [
        SimpleNamespace(
            elapsed_seconds=float(index * 5),
            api_rss_bytes=1_000_000,
            worker_rss_bytes=2_000_000,
        )
        for index in range(2)
    ]
    resources = record["resources"]
    resources.update(
        sample_count=2,
        measured_sample_count=2,
        measured_sample_count_passed=False,
        idle_recovery_sample_count=0,
        idle_recovery_sample_span_seconds=0.0,
        idle_recovery_samples_complete=False,
        sample_count_passed=False,
        process_cohort_evidence=_valid_process_cohort(harness, sample_count=2),
    )
    for service in ("api", "worker"):
        resources[f"{service}_rss_growth"] = harness._rss_growth_evidence(
            measured_samples,
            [],
            formal=True,
            rss_attribute=f"{service}_rss_bytes",
        )
        assert resources[f"{service}_rss_growth"]["evaluated"] is False
        assert resources[f"{service}_rss_growth"]["idle_confirmation"]["status"] == (
            "insufficient_samples"
        )
    for trend_name, level in (
        ("api_fd_trend", 10.0),
        ("worker_fd_trend", 20.0),
        ("postgres_connection_trend", 3.0),
    ):
        resources[trend_name] = _valid_resource_trend(
            harness,
            formal=True,
            measured_count=2,
            idle_count=0,
            idle_span=0.0,
            idle_complete=False,
            level=level,
        )
    _mark_record_failed(record, "rss_growth", "resource_samples_complete")


def _write_records(path: Path, records: list[dict]) -> None:
    for record in records:
        (path / f"baseline-{record['baseline_index']}.json").write_text(
            json.dumps(record, sort_keys=True), encoding="utf-8"
        )


def _write_resource_rows(path: Path, harness: ModuleType, rows: list[str]) -> None:
    path.write_text(
        "\n".join([harness.RESOURCE_HEADER, *rows]) + "\n",
        encoding="utf-8",
    )


def _formal_rss_evidence(
    harness: ModuleType,
    path: Path,
    *,
    active_api_rss: list[int],
    active_worker_rss: list[int],
    idle_api_rss: list[int],
    idle_worker_rss: list[int],
    api_process_counts: list[int] | None = None,
    worker_process_counts: list[int] | None = None,
    api_process_identities: list[str] | None = None,
    worker_process_identities: list[str] | None = None,
) -> dict[str, object]:
    active_count = len(active_api_rss)
    idle_count = len(idle_api_rss)
    assert active_count == len(active_worker_rss) == 120
    assert idle_count == len(idle_worker_rss) == 12
    sample_count = active_count + idle_count
    api_process_counts = api_process_counts or [3] * sample_count
    worker_process_counts = worker_process_counts or [2] * sample_count
    api_process_identities = api_process_identities or [API_PROCESS_IDENTITY_SHA256] * sample_count
    worker_process_identities = (
        worker_process_identities or [WORKER_PROCESS_IDENTITY_SHA256] * sample_count
    )
    assert all(
        len(values) == sample_count
        for values in (
            api_process_counts,
            worker_process_counts,
            api_process_identities,
            worker_process_identities,
        )
    )

    rows: list[str] = []
    for index, (api_rss, worker_rss) in enumerate(
        zip(
            [*active_api_rss, *idle_api_rss],
            [*active_worker_rss, *idle_worker_rss],
            strict=True,
        )
    ):
        rows.append(
            _resource_row(
                index * 5,
                api_rss,
                10,
                worker_rss,
                20,
                3,
                api_process_count=api_process_counts[index],
                worker_process_count=worker_process_counts[index],
                api_process_identity_sha256=api_process_identities[index],
                worker_process_identity_sha256=worker_process_identities[index],
            )
        )
    _write_resource_rows(path, harness, rows)
    evidence = harness._resource_evidence(
        path,
        harness.Shape("formal", 600, 0, 8, 8.0, 64),
        warmup_finished_seconds=0.0,
        load_finished_seconds=595.0,
        idle_finished_seconds=655.0,
    )
    for service in ("api", "worker"):
        assert harness._rss_growth_valid(
            evidence[f"{service}_rss_growth"],
            formal=True,
            expected_measured_sample_count=evidence["measured_sample_count"],
            expected_idle_sample_count=evidence["idle_recovery_sample_count"],
        )
    return evidence


def test_external_topology_replaces_all_old_in_process_seams() -> None:
    source = _source(HARNESS)
    compose = _source(COMPOSE)

    for forbidden in (
        "ASGITransport",
        "create_app",
        "CloudServices",
        "RuntimeService(",
        "process_queued_runs",
    ):
        assert forbidden not in source
    assert "base_url=api_url" in source
    assert "proof-api:" in compose
    assert "gunicorn" in compose
    assert "uvicorn.workers.UvicornWorker" in compose
    assert "proof-worker:" in compose
    assert "app.workers.runtime_queue" in compose
    assert "proof-provider:" in compose
    assert re.search(r"--keep-alive\s+- \"10\"", compose)
    worker_service = re.search(
        r"^  proof-worker:\n(.*?)(?=^  [a-z]|\Z)", compose, re.MULTILINE | re.DOTALL
    )
    assert worker_service is not None
    assert re.search(r"^    deploy:\n      replicas: 2$", worker_service.group(1), re.MULTILINE)
    assert 'NPCINK_CLOUD_WORKER_HEARTBEAT_INTERVAL_SECONDS: "30"' in compose
    api_url = re.search(r"P5_B4_PROOF_API_URL:\s*(\S+)", compose)
    trusted_hosts = re.search(r"NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST:\s*(\S+)", compose)
    assert api_url is not None and trusted_hosts is not None
    assert urlsplit(api_url.group(1)).hostname in trusted_hosts.group(1).split(",")
    assert "internal: true" in compose
    assert "ports:" not in compose


def test_formal_shape_and_subcommand_contract_are_frozen(harness: ModuleType) -> None:
    assert harness.CONTRACT_ID == "p5_b4_external_runtime_load_soak_proof.v5"
    assert harness.FORMAL_RECORDS == 3
    assert harness.FORMAL_DURATION_SECONDS == 600
    assert harness.FORMAL_WARMUP_SECONDS == 30
    assert harness.FORMAL_CONCURRENCY == 8
    assert harness.FORMAL_REQUEST_RATE == 8.0
    assert harness.FORMAL_QUEUE_BURST == 64
    assert harness.DEFAULT_WORKER_POLL_SECONDS == 5
    assert harness.DEFAULT_WORKER_BATCH_SIZE == 8
    assert harness.FORMAL_WORKER_REPLICAS == 2
    assert harness.FORMAL_RESOURCE_IDLE_RECOVERY_SECONDS == 60
    assert harness.FORMAL_RESOURCE_IDLE_MIN_SAMPLES == 12
    assert harness.FORMAL_RESOURCE_IDLE_MIN_SPAN_SECONDS == 55.0
    assert harness.FORMAL_RSS_ENDPOINT_WINDOW_SAMPLES == 12
    assert harness.FORMAL_RSS_ENDPOINT_WINDOW_MIN_SPAN_SECONDS == 55.0
    assert harness.FORMAL_RSS_IDLE_BLOCK_COUNT == 4
    assert harness.SITE_COUNT == 8
    assert harness.PROOF_MAX_AI_CREDITS_PER_SITE_PERIOD == 10_000.0
    assert len(harness.RECORD_CHECK_IDS) == 29
    assert len(set(harness.RECORD_CHECK_IDS)) == 29
    assert "transport_http_failures_zero" in harness.RECORD_CHECK_IDS
    source = _source(HARNESS)
    tree = ast.parse(source)
    run_record = next(
        node
        for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "_run_record"
    )
    checks_assignment = next(
        node
        for node in ast.walk(run_record)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "checks" for target in node.targets)
    )
    assert isinstance(checks_assignment.value, ast.Dict)
    check_ids = tuple(ast.literal_eval(key) for key in checks_assignment.value.keys)
    assert check_ids == harness.RECORD_CHECK_IDS
    assert "max_connections=shape.concurrency" in source
    assert "max_keepalive_connections=shape.concurrency" in source
    assert "keepalive_expiry=5.0" in source
    assert "retries=" not in source
    parser = harness._parser()
    assert parser.parse_args(["--confirm-disposable", "serve-provider"]).command == (
        "serve-provider"
    )
    assert parser.parse_args(["--confirm-disposable", "probe-api"]).command == "probe-api"
    assert (
        parser.parse_args(["--confirm-disposable", "prepare", "--baseline-index", "1"]).command
        == "prepare"
    )


def test_dataset_attribution_requires_v5(
    harness: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = json.loads(json.dumps(harness.EXPECTED_DATASET_CONFIG))
    monkeypatch.setenv("P5_B4_DATASET_ID", harness.EXPECTED_DATASET_ID)

    def set_dataset(value: dict[str, object]) -> None:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
        monkeypatch.setenv("P5_B4_DATASET_CONFIG", raw)
        monkeypatch.setenv("P5_B4_DATASET_SHA256", hashlib.sha256(raw.encode()).hexdigest())

    set_dataset(dataset)
    parsed, digest = harness._dataset_attribution()
    assert parsed == dataset
    assert (
        digest
        == hashlib.sha256(
            json.dumps(dataset, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )

    set_dataset({**dataset, "contract": "p5_b4_runtime_dataset.v4"})
    with pytest.raises(harness.ProofFailure, match="configuration.dataset_contract_invalid"):
        harness._dataset_attribution()

    set_dataset(dataset)
    monkeypatch.setenv("P5_B4_DATASET_ID", "p5_b4_runtime_8_sites_v4")
    with pytest.raises(harness.ProofFailure, match="configuration.dataset_id_invalid"):
        harness._dataset_attribution()


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_threshold",
        "changed_window",
        "float_window",
        "boolean_baselines",
        "float_worker_replicas",
        "boolean_worker_replicas",
    ],
)
def test_dataset_attribution_rejects_incomplete_or_mutated_v5_identity(
    harness: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    dataset = json.loads(json.dumps(harness.EXPECTED_DATASET_CONFIG))
    formal = dataset["formal"]
    assert isinstance(formal, dict)
    if mutation == "missing_threshold":
        del formal["rss_growth_percent_max"]
    elif mutation == "changed_window":
        formal["rss_endpoint_window_sample_count"] = 11
    elif mutation == "float_window":
        formal["rss_endpoint_window_sample_count"] = 12.0
    elif mutation == "boolean_baselines":
        quick = dataset["quick"]
        assert isinstance(quick, dict)
        quick["baselines"] = True
    else:
        worker = dataset["worker"]
        assert isinstance(worker, dict)
        worker["replicas"] = 2.0 if mutation == "float_worker_replicas" else True
    raw = json.dumps(dataset, sort_keys=True, separators=(",", ":"))
    monkeypatch.setenv("P5_B4_DATASET_ID", harness.EXPECTED_DATASET_ID)
    monkeypatch.setenv("P5_B4_DATASET_CONFIG", raw)
    monkeypatch.setenv("P5_B4_DATASET_SHA256", hashlib.sha256(raw.encode()).hexdigest())
    with pytest.raises(harness.ProofFailure, match="configuration.dataset_contract_invalid"):
        harness._dataset_attribution()


def test_formal_needs_three_records_and_quick_never_claims_acceptance(
    harness: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("P5_B4_TOPOLOGY_VERIFIED", "true")
    _write_records(tmp_path, [_record(harness, 1)])
    formal, formal_ok = harness._aggregate(
        SimpleNamespace(mode="formal", input_dir=tmp_path, baseline_count=1)
    )
    assert formal_ok is False
    assert formal["formal_acceptance"] is False

    (tmp_path / "baseline-1.json").unlink()
    _write_records(tmp_path, [_record(harness, 1, mode="quick")])
    quick, quick_ok = harness._aggregate(
        SimpleNamespace(mode="quick", input_dir=tmp_path, baseline_count=1)
    )
    assert quick_ok is True
    assert quick["verdict"] == "non_acceptance_observation"
    assert quick["formal_acceptance"] is False
    monkeypatch.setenv("P5_B4_TOPOLOGY_VERIFIED", "false")
    unverified, unverified_ok = harness._aggregate(
        SimpleNamespace(mode="quick", input_dir=tmp_path, baseline_count=1)
    )
    assert unverified_ok is False
    assert unverified["verdict"] == "failed"


def test_formal_aggregate_locks_first_record_and_keeps_receipts(
    harness: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("P5_B4_TOPOLOGY_VERIFIED", "true")
    records = [
        _record(harness, 1),
        _record(harness, 2, p95=180, p99=240),
        _record(harness, 3, p95=200, p99=250),
    ]
    _write_records(tmp_path, records)
    expected_hash = hashlib.sha256((tmp_path / "baseline-1.json").read_bytes()).hexdigest()
    report, ok = harness._aggregate(
        SimpleNamespace(mode="formal", input_dir=tmp_path, baseline_count=3)
    )
    assert ok is True
    assert report["formal_acceptance"] is True
    assert report["first_record_sha256"] == expected_hash
    assert len(report["baseline_receipts"]) == 3
    assert all("record_sha256" in receipt for receipt in report["baseline_receipts"])
    assert all("observation_diagnostics" in receipt for receipt in report["baseline_receipts"])
    assert report["diagnostics_valid_all_records"] is True

    records[2]["contract"] = "unexpected-contract"
    _write_records(tmp_path, [records[2]])
    with pytest.raises(harness.ProofFailure, match="aggregate.record_schema_invalid"):
        harness._aggregate(SimpleNamespace(mode="formal", input_dir=tmp_path, baseline_count=3))

    records[2] = _record(harness, 3)
    records[2]["observation_diagnostics"]["by_phase"]["raw-dynamic-phase"] = 1
    _write_records(tmp_path, [records[2]])
    with pytest.raises(harness.ProofFailure, match="aggregate.record_schema_invalid"):
        harness._aggregate(SimpleNamespace(mode="formal", input_dir=tmp_path, baseline_count=3))


def test_formal_aggregate_rejects_v4_record(
    harness: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("P5_B4_TOPOLOGY_VERIFIED", "true")
    records = [_record(harness, index) for index in range(1, 4)]
    records[1]["contract"] = "p5_b4_external_runtime_load_soak_proof.v4"
    _write_records(tmp_path, records)

    with pytest.raises(harness.ProofFailure, match="aggregate.record_schema_invalid"):
        harness._aggregate(SimpleNamespace(mode="formal", input_dir=tmp_path, baseline_count=3))

    records[1]["observation_diagnostics"]["schema_version"] = "p5_b4_observation_diagnostics.v1"
    del records[1]["observation_diagnostics"]["by_phase_and_error_code"]
    _write_records(tmp_path, [records[1]])
    with pytest.raises(harness.ProofFailure, match="aggregate.record_schema_invalid"):
        harness._aggregate(SimpleNamespace(mode="formal", input_dir=tmp_path, baseline_count=3))


@pytest.mark.parametrize("drift", ["configuration_int_to_float", "identity_bool_to_int"])
def test_formal_aggregate_rejects_json_type_drift(
    harness: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    monkeypatch.setenv("P5_B4_TOPOLOGY_VERIFIED", "true")
    records = [_record(harness, index) for index in range(1, 4)]
    if drift == "configuration_int_to_float":
        for record in records:
            record["configuration"]["worker_replicas"] = 2.0
    else:
        for record in records:
            record["identity"]["git_dirty"] = 0
    _write_records(tmp_path, records)

    with pytest.raises(harness.ProofFailure, match="aggregate.record_schema_invalid"):
        harness._aggregate(SimpleNamespace(mode="formal", input_dir=tmp_path, baseline_count=3))


@pytest.mark.parametrize(
    "mutation",
    ["empty_checks", "empty_resources", "missing_field", "inconsistent_false_resource"],
)
def test_aggregate_rejects_three_equally_malformed_records(
    harness: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    monkeypatch.setenv("P5_B4_TOPOLOGY_VERIFIED", "true")
    records = [_record(harness, index) for index in range(1, 4)]
    for record in records:
        if mutation == "empty_checks":
            record["checks"] = {}
        elif mutation == "empty_resources":
            record["resources"] = {}
        elif mutation == "missing_field":
            del record["queue"]
        else:
            record["resources"]["services_survived_all_samples"] = False
    _write_records(tmp_path, records)

    with pytest.raises(harness.ProofFailure, match="aggregate.record_schema_invalid"):
        harness._aggregate(SimpleNamespace(mode="formal", input_dir=tmp_path, baseline_count=3))


@pytest.mark.parametrize(
    "mutation",
    [
        "negative_control_matrix_absent",
        "boundary_bool_to_int",
        "redaction_bool_to_float",
        "trend_reduced_to_summary",
        "trend_sample_count_type_drift",
    ],
)
def test_formal_aggregate_rejects_three_equal_strict_schema_bypasses(
    harness: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    monkeypatch.setenv("P5_B4_TOPOLOGY_VERIFIED", "true")
    records = [_record(harness, index) for index in range(1, 4)]
    for record in records:
        if mutation == "negative_control_matrix_absent":
            diagnostics = record["observation_diagnostics"]
            diagnostics["by_error_code"]["auth.site_mismatch"] -= 1
            diagnostics["by_error_code"]["none"] += 1
            diagnostics["by_phase_and_error_code"]["cross_site"]["auth.site_mismatch"] -= 1
            diagnostics["by_phase_and_error_code"]["cross_site"]["none"] += 1
        elif mutation == "boundary_bool_to_int":
            record["boundary"]["new_runtime_infrastructure"] = 0
        elif mutation == "redaction_bool_to_float":
            record["redaction"]["secret_fields_emitted"] = 0.0
        elif mutation == "trend_reduced_to_summary":
            record["resources"]["api_fd_trend"] = {"sustained_growth": False}
        else:
            record["resources"]["api_fd_trend"]["sample_count"] = "120"
        assert harness._record_schema_valid(record, expected_mode="formal") is False
    _write_records(tmp_path, records)

    with pytest.raises(harness.ProofFailure, match="aggregate.record_schema_invalid"):
        harness._aggregate(SimpleNamespace(mode="formal", input_dir=tmp_path, baseline_count=3))


@pytest.mark.parametrize(
    "mutation",
    [
        "diagnostics_transport_cross_dimension",
        "diagnostics_5xx_exceeds_request_count",
        "diagnostics_accepted_runtime_mismatch",
        "timing_percentiles_out_of_order",
        "timing_distribution_sample_mismatch",
        "queue_wait_p95_mismatch",
        "queue_complete_not_recomputed",
        "latency_sample_exceeds_accepted",
        "latency_missing_count_mismatch",
        "latency_complete_mismatch",
        "identifier_exact_count_mismatch",
        "provider_invocation_set_not_gated",
        "provider_usage_key_set_not_gated",
        "run_usage_key_set_not_gated",
        "provider_meter_set_not_gated",
        "provider_meter_mismatch_not_gated",
        "provider_contract_violation_not_gated",
        "provider_invocation_count_not_gated",
        "provider_succeeded_exceeds_calls",
        "provider_calls_exceed_database",
        "resource_trend_summary_mismatch",
        "resource_sample_summary_mismatch",
        "rss_within_budget_not_recomputed",
    ],
)
def test_formal_aggregate_rejects_three_equal_review_reproduction_mutations(
    harness: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    monkeypatch.setenv("P5_B4_TOPOLOGY_VERIFIED", "true")
    records = [_record(harness, index) for index in range(1, 4)]
    for record in records:
        diagnostics = record["observation_diagnostics"]
        timing = record["queue"]["timing_evidence"]
        latency = record["latency"]
        integrity = record["integrity"]
        resources = record["resources"]
        if mutation == "diagnostics_transport_cross_dimension":
            diagnostics["by_error_code"]["none"] -= 1
            diagnostics["by_error_code"]["transport.read_error"] += 1
            diagnostics["by_phase_and_error_code"]["soak"]["none"] -= 1
            diagnostics["by_phase_and_error_code"]["soak"]["transport.read_error"] += 1
        elif mutation == "diagnostics_5xx_exceeds_request_count":
            diagnostics["by_http_status"]["200"] -= 1
            diagnostics["by_http_status"]["5xx"] += 1
        elif mutation == "diagnostics_accepted_runtime_mismatch":
            diagnostics["by_runtime_status"]["succeeded"] -= 1
            diagnostics["by_runtime_status"]["failed"] += 1
        elif mutation == "timing_percentiles_out_of_order":
            timing["wait_seconds"]["p50"] = timing["wait_seconds"]["max"] + 1.0
        elif mutation == "timing_distribution_sample_mismatch":
            timing["wait_seconds"]["sample_count"] -= 1
        elif mutation == "queue_wait_p95_mismatch":
            timing["wait_seconds"]["p95"] = 999.0
            timing["wait_seconds"]["p99"] = 999.0
            timing["wait_seconds"]["max"] = 999.0
        elif mutation == "queue_complete_not_recomputed":
            timing["complete"] = False
            _mark_record_failed(record, "queue_timing_evidence_complete")
        elif mutation == "latency_sample_exceeds_accepted":
            latency["sample_count"] = latency["accepted_sample_count"] + 1
        elif mutation == "latency_missing_count_mismatch":
            latency["missing_persistent_evidence_count"] = 1
        elif mutation == "latency_complete_mismatch":
            latency["all_accepted_samples_have_persistent_provider_evidence"] = False
        elif mutation == "identifier_exact_count_mismatch":
            integrity["observed_records"] -= 1
        elif mutation.endswith("_set_not_gated"):
            integrity[
                {
                    "provider_invocation_set_not_gated": "provider_invocation_set_exact",
                    "provider_usage_key_set_not_gated": "provider_usage_key_set_exact",
                    "run_usage_key_set_not_gated": "run_usage_key_set_exact",
                    "provider_meter_set_not_gated": "provider_meter_set_exact",
                }[mutation]
            ] = False
        elif mutation == "provider_meter_mismatch_not_gated":
            integrity["provider_meter_mismatches"] = 1
        elif mutation == "provider_contract_violation_not_gated":
            integrity["usage_event_contract_violations"] = 1
        elif mutation == "provider_invocation_count_not_gated":
            integrity["provider_invocations"] -= 1
        elif mutation == "provider_succeeded_exceeds_calls":
            integrity["provider_call_records"] -= 1
            integrity["provider_invocations"] -= 1
        elif mutation == "provider_calls_exceed_database":
            integrity["provider_call_records"] += 1
            integrity["provider_invocations"] += 1
        elif mutation == "resource_trend_summary_mismatch":
            resources["api_fd_trend"]["sustained_growth"] = True
        elif mutation == "resource_sample_summary_mismatch":
            resources["measured_sample_count_passed"] = False
        else:
            for service in ("api", "worker"):
                resources[f"{service}_rss_growth"]["within_budget"] = False
            _mark_record_failed(record, "rss_growth")
    _write_records(tmp_path, records)

    with pytest.raises(harness.ProofFailure, match="aggregate.record_schema_invalid"):
        harness._aggregate(SimpleNamespace(mode="formal", input_dir=tmp_path, baseline_count=3))


@pytest.mark.parametrize(
    "scenario",
    ["zero_accepted", "incomplete_queue", "formal_rss_insufficient"],
)
def test_structurally_valid_failure_evidence_aggregates_as_non_acceptance(
    harness: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    monkeypatch.setenv("P5_B4_TOPOLOGY_VERIFIED", "true")
    records = [_record(harness, index) for index in range(1, 4)]
    modifier = {
        "zero_accepted": _zero_accepted_record,
        "incomplete_queue": _incomplete_queue_record,
        "formal_rss_insufficient": _formal_rss_insufficient_record,
    }[scenario]
    for record in records:
        modifier(harness, record)
        assert harness._record_schema_valid(record, expected_mode="formal") is True
    _write_records(tmp_path, records)

    report, ok = harness._aggregate(
        SimpleNamespace(mode="formal", input_dir=tmp_path, baseline_count=3)
    )

    assert ok is False
    assert report["formal_acceptance"] is False
    assert report["records_passed"] is False


def test_structurally_valid_failed_record_aggregates_as_non_acceptance(
    harness: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("P5_B4_TOPOLOGY_VERIFIED", "true")
    records = [_record(harness, index) for index in range(1, 4)]
    failed = records[1]
    failed["resources"]["services_survived_all_samples"] = False
    failed["checks"]["services_survived"] = False
    failed["record_thresholds_passed"] = False
    failed["verdict"] = "record_failed"
    assert harness._record_schema_valid(failed, expected_mode="formal") is True
    _write_records(tmp_path, records)

    report, ok = harness._aggregate(
        SimpleNamespace(mode="formal", input_dir=tmp_path, baseline_count=3)
    )

    assert ok is False
    assert report["formal_acceptance"] is False
    assert report["records_passed"] is False


def test_real_resource_helper_records_round_trip_success_and_failures(
    harness: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("P5_B4_TOPOLOGY_VERIFIED", "true")
    success_resources = _formal_rss_evidence(
        harness,
        tmp_path / "roundtrip-success.tsv",
        active_api_rss=[1_000_000] * 108 + [1_100_000] * 12,
        active_worker_rss=[2_000_000] * 108 + [2_200_000] * 12,
        idle_api_rss=[1_100_000] * 12,
        idle_worker_rss=[2_200_000] * 12,
    )
    success_records = [_record(harness, index) for index in range(1, 4)]
    for record in success_records:
        record["resources"] = json.loads(json.dumps(success_resources))
        assert harness._record_schema_valid(record, expected_mode="formal") is True
    success_dir = tmp_path / "success-records"
    success_dir.mkdir()
    _write_records(success_dir, success_records)
    success_report, success = harness._aggregate(
        SimpleNamespace(mode="formal", input_dir=success_dir, baseline_count=3)
    )
    assert success is True
    assert success_report["formal_acceptance"] is True

    overbudget_resources = _formal_rss_evidence(
        harness,
        tmp_path / "roundtrip-overbudget.tsv",
        active_api_rss=[1_000_000] * 108 + [1_100_001] * 12,
        active_worker_rss=[2_000_000] * 120,
        idle_api_rss=[1_000_000] * 12,
        idle_worker_rss=[2_000_000] * 12,
    )
    overbudget_records = [_record(harness, index) for index in range(1, 4)]
    for record in overbudget_records:
        record["resources"] = json.loads(json.dumps(overbudget_resources))
        _mark_record_failed(record, "rss_growth")
        assert harness._record_schema_valid(record, expected_mode="formal") is True
    overbudget_dir = tmp_path / "overbudget-records"
    overbudget_dir.mkdir()
    _write_records(overbudget_dir, overbudget_records)
    overbudget_report, overbudget = harness._aggregate(
        SimpleNamespace(mode="formal", input_dir=overbudget_dir, baseline_count=3)
    )
    assert overbudget is False
    assert overbudget_report["formal_acceptance"] is False
    assert overbudget_report["records_passed"] is False

    quick_resource = tmp_path / "roundtrip-quick.tsv"
    _write_resource_rows(
        quick_resource,
        harness,
        [
            _resource_row(0.0, 1_000_000, 10, 2_000_000, 20, 3),
            _resource_row(5.0, 1_000_000, 10, 2_000_000, 20, 3),
        ],
    )
    quick_resources = harness._resource_evidence(
        quick_resource,
        harness.Shape("quick", 5, 3, 2, 2.0, 8),
        warmup_finished_seconds=0.0,
        load_finished_seconds=5.0,
        idle_finished_seconds=5.0,
    )
    quick_record = _record(harness, 1, mode="quick")
    quick_record["resources"] = quick_resources
    assert harness._record_schema_valid(quick_record, expected_mode="quick") is True

    insufficient_resource = tmp_path / "roundtrip-insufficient.tsv"
    _write_resource_rows(
        insufficient_resource,
        harness,
        [
            _resource_row(0.0, 1_000_000, 10, 2_000_000, 20, 3),
            _resource_row(5.0, 1_000_000, 10, 2_000_000, 20, 3),
        ],
    )
    insufficient_resources = harness._resource_evidence(
        insufficient_resource,
        harness.Shape("formal", 600, 30, 8, 8.0, 64),
        warmup_finished_seconds=0.0,
        load_finished_seconds=5.0,
        idle_finished_seconds=5.0,
    )
    insufficient_record = _record(harness, 1)
    insufficient_record["resources"] = insufficient_resources
    _mark_record_failed(insufficient_record, "rss_growth", "resource_samples_complete")
    assert harness._record_schema_valid(insufficient_record, expected_mode="formal") is True


def test_record_schema_accepts_finite_negative_rss_growth(harness: ModuleType) -> None:
    record = _record(harness, 1)
    for service in ("api", "worker"):
        growth = record["resources"][f"{service}_rss_growth"]
        growth["growth_percent"] = -14.8
        growth["growth_percent_rounded"] = -14.8
        growth["terminal_window"]["median_rss_bytes"] = 852_000.0

    assert harness._record_schema_valid(record, expected_mode="formal") is True


def test_regression_requires_both_absolute_and_relative_thresholds(harness: ModuleType) -> None:
    assert harness._regression_failed(100, 201) is True
    assert harness._regression_failed(500, 601) is True
    assert harness._regression_failed(500, 600) is False
    assert harness._regression_failed(1_000, 1_101) is False
    assert harness._regression_failed(100, 121) is False


def test_exact_set_queue_and_achieved_rate_gates(harness: ModuleType) -> None:
    assert harness._exact_identifier_set(["a", "b"], {"a", "b"}) is True
    assert harness._exact_identifier_set(["a", "a"], {"a"}) is False
    assert harness._exact_identifier_set(["a"], {"a", "b"}) is False
    assert harness._queue_gate(64, 64, 64, 200) is True
    assert harness._queue_gate(64, 63, 63, 200) is False
    assert harness._queue_gate(64, 64, 64, 500) is False
    assert harness._achieved_rate_passed(7.6, 8.0) is True
    assert harness._achieved_rate_passed(7.59, 8.0) is False


def test_queue_timing_evidence_is_complete_bounded_and_aggregate_only(
    harness: ModuleType,
) -> None:
    submitted_at = datetime(2026, 7, 19, tzinfo=UTC)
    runs = [
        SimpleNamespace(
            run_id=f"hidden-run-{index:03d}",
            started_at=submitted_at,
            processing_started_at=submitted_at + timedelta(seconds=1 + index / 10),
        )
        for index in range(harness.FORMAL_QUEUE_BURST)
    ]

    evidence = harness._queue_timing_evidence(
        runs,
        expected_count=harness.FORMAL_QUEUE_BURST,
        cohort_size=harness.DEFAULT_WORKER_BATCH_SIZE,
    )

    assert evidence["expected_sample_count"] == 64
    assert evidence["sample_count"] == 64
    assert evidence["processing_started_sample_count"] == 64
    assert evidence["missing_processing_started_count"] == 0
    assert evidence["timing_sample_count"] == 64
    assert evidence["complete"] is True
    assert evidence["wait_seconds"] == {
        "sample_count": 64,
        "p50": 4.15,
        "p90": 6.67,
        "p95": 6.985,
        "p99": 7.237,
        "max": 7.3,
    }
    assert evidence["first_claim_lag_seconds"] == 1.0
    assert evidence["submission_span_seconds"] == 0.0
    assert evidence["processing_start_span_seconds"] == 6.3
    assert evidence["adjacent_claim_gap_seconds"] == {
        "sample_count": 63,
        "p50": 0.1,
        "p90": 0.1,
        "p95": 0.1,
        "p99": 0.1,
        "max": 0.1,
    }
    assert evidence["cohort_size"] == 8
    assert evidence["expected_cohort_count"] == 8
    assert evidence["cohort_count"] == 8
    cohorts = evidence["cohorts"]
    assert len(cohorts) == 8
    assert all(cohort["sample_count"] == 8 for cohort in cohorts)
    assert all(cohort["complete"] is True for cohort in cohorts)
    assert cohorts[0]["wait_seconds"]["p50"] == 1.35
    assert cohorts[-1]["wait_seconds"]["max"] == 7.3

    serialized = json.dumps(evidence, sort_keys=True)
    assert "hidden-run-" not in serialized
    assert harness._redaction_violations(evidence) == []


def test_queue_timing_evidence_and_gate_fail_closed_without_processing_start(
    harness: ModuleType,
) -> None:
    submitted_at = datetime(2026, 7, 19, tzinfo=UTC)
    runs = [
        SimpleNamespace(
            run_id=f"hidden-run-{index:03d}",
            started_at=submitted_at,
            processing_started_at=(
                None if index == 7 else submitted_at + timedelta(seconds=1 + index / 10)
            ),
        )
        for index in range(harness.FORMAL_QUEUE_BURST)
    ]

    evidence = harness._queue_timing_evidence(
        runs,
        expected_count=harness.FORMAL_QUEUE_BURST,
        cohort_size=harness.DEFAULT_WORKER_BATCH_SIZE,
    )

    assert evidence["sample_count"] == 64
    assert evidence["processing_started_sample_count"] == 63
    assert evidence["missing_processing_started_count"] == 1
    assert evidence["timing_sample_count"] == 63
    assert evidence["wait_seconds"]["sample_count"] == 63
    assert evidence["complete"] is False
    assert evidence["cohorts"][0]["complete"] is False
    source = _source(HARNESS)
    assert 'int(queue_timing["sample_count"]) == shape.queue_burst' in source
    assert 'and bool(queue_timing["complete"])' in source
    assert 'float(integrity["queue_wait_p95_seconds"]) <= DEFAULT_WORKER_POLL_SECONDS * 2' in source


def test_diagnostics_are_bounded_redacted_and_require_run_identifier(
    harness: ModuleType,
) -> None:
    valid = harness.Observation(
        request_hash="a" * 64,
        run_id="run-safe",
        http_status=200,
        runtime_status="succeeded",
        error_code="",
        elapsed_ms=1.0,
        phase="warmup",
    )
    missing_identifier = harness.Observation(
        request_hash="b" * 64,
        run_id="",
        http_status=200,
        runtime_status="succeeded",
        error_code="",
        elapsed_ms=1.0,
        phase="soak",
    )
    unsafe = harness.Observation(
        request_hash="c" * 64,
        run_id="",
        http_status=422,
        runtime_status="user-controlled-status",
        error_code="contains/raw/identifier",
        elapsed_ms=1.0,
        phase="user-controlled-phase",
    )
    negative_control = harness.Observation(
        request_hash="d" * 64,
        run_id="",
        http_status=400,
        runtime_status="",
        error_code="auth.site_mismatch",
        elapsed_ms=1.0,
        phase="cross_site",
    )

    assert valid.accepted is True
    assert missing_identifier.success_envelope is True
    assert missing_identifier.accepted is False
    summary = harness._diagnostic_summary([negative_control, valid, missing_identifier, unsafe])
    assert set(summary["by_http_status"]) == set(harness.DIAGNOSTIC_HTTP_BUCKETS)
    assert set(summary["by_error_code"]) == set(harness.DIAGNOSTIC_ERROR_BUCKETS)
    assert set(summary["by_runtime_status"]) == set(harness.DIAGNOSTIC_RUNTIME_BUCKETS)
    assert set(summary["by_phase"]) == set(harness.DIAGNOSTIC_PHASE_BUCKETS)
    assert set(summary["by_phase_and_error_code"]) == set(harness.DIAGNOSTIC_PHASE_BUCKETS)
    assert all(
        set(counts) == set(harness.DIAGNOSTIC_ERROR_BUCKETS)
        for counts in summary["by_phase_and_error_code"].values()
    )
    assert summary["by_http_status"]["200"] == 2
    assert summary["by_http_status"]["400"] == 1
    assert summary["by_http_status"]["422"] == 1
    assert summary["by_error_code"]["auth.site_mismatch"] == 1
    assert summary["by_error_code"]["other"] == 1
    assert summary["by_runtime_status"]["other"] == 1
    assert summary["by_phase"]["other"] == 1
    assert summary["by_phase_and_error_code"]["cross_site"]["auth.site_mismatch"] == 1
    assert summary["by_phase_and_error_code"]["warmup"]["none"] == 1
    assert summary["by_phase_and_error_code"]["soak"]["none"] == 1
    assert summary["by_phase_and_error_code"]["other"]["other"] == 1
    assert summary["response_shape_violation_count"] == 2
    assert summary["other_count"] == 3
    assert summary["complete"] is False
    serialized = json.dumps(summary, sort_keys=True)
    assert "contains/raw/identifier" not in serialized
    assert "user-controlled-status" not in serialized
    assert "user-controlled-phase" not in serialized
    assert harness._diagnostics_valid(summary) is True
    assert harness._proof_fixture_rejections_zero(summary) is True
    assert harness._redaction_violations(summary) == []

    quota = harness.Observation(
        request_hash="e" * 64,
        run_id="",
        http_status=429,
        runtime_status="",
        error_code="commercial.quota_exceeded",
        elapsed_ms=1.0,
        phase="warmup",
    )
    quota_summary = harness._diagnostic_summary([negative_control, quota])
    assert quota_summary["complete"] is True
    assert harness._proof_fixture_rejections_zero(quota_summary) is False


def test_provider_reference_is_reversible_and_never_looks_like_pii(
    harness: ModuleType,
) -> None:
    from app.domain.runtime.data_guard import find_runtime_data_guard_finding

    labels = [
        "baseline-1-cross-valid",
        *(f"baseline-1-concurrency-{index}" for index in range(harness.FORMAL_CONCURRENCY)),
        *(f"baseline-1-queue-{index}" for index in range(harness.FORMAL_QUEUE_BURST)),
        *(
            f"baseline-1-soak-{index}"
            for index in range(round(harness.FORMAL_DURATION_SECONDS * harness.FORMAL_REQUEST_RATE))
        ),
    ]
    for label in labels:
        request_hash = harness._request_hash(label)
        request_ref = harness._proof_request_ref(request_hash)
        assert harness.PROOF_REQUEST_REF_PATTERN.fullmatch(request_ref)
        assert harness._proof_request_hash(request_ref) == request_hash
        assert (
            find_runtime_data_guard_finding({"metadata": {"proof_request_ref": request_ref}})
            is None
        )

    with pytest.raises(harness.ProofFailure, match="provider.request_ref_invalid"):
        harness._proof_request_hash("not-a-fixed-proof-reference")


def test_concurrency_probe_metadata_and_provider_barrier_are_fail_closed(
    harness: ModuleType,
) -> None:
    from app.domain.runtime.data_guard import find_runtime_data_guard_finding

    normal_body, _ = harness._payload("site", "normal", queued=False)
    normal_metadata = json.loads(normal_body)["input"]["metadata"]
    assert "proof_concurrency_target" not in normal_metadata

    probe_body, _ = harness._payload(
        "site",
        "probe",
        queued=False,
        provider_concurrency_target=harness.FORMAL_CONCURRENCY,
    )
    probe_metadata = json.loads(probe_body)["input"]["metadata"]
    assert probe_metadata["proof_concurrency_target"] == str(harness.FORMAL_CONCURRENCY)
    assert harness._proof_concurrency_target(probe_metadata) == harness.FORMAL_CONCURRENCY
    assert find_runtime_data_guard_finding({"metadata": probe_metadata}) is None

    for invalid in (True, "08", "-1", str(harness.FORMAL_CONCURRENCY + 1)):
        with pytest.raises(harness.ProofFailure, match="provider.concurrency_target_invalid"):
            harness._proof_concurrency_target({"proof_concurrency_target": invalid})

    class ActiveRedis:
        def __init__(self, values: list[int]) -> None:
            self.values = values

        def get(self, _key: str) -> int:
            if len(self.values) > 1:
                return self.values.pop(0)
            return self.values[0]

    assert (
        harness._wait_for_provider_concurrency(ActiveRedis([7, 8]), 8, timeout_seconds=0.1) is True
    )
    assert harness._wait_for_provider_concurrency(ActiveRedis([7]), 8, timeout_seconds=0) is False
    assert "provider_concurrency_target=concurrency" in _source(HARNESS)


def test_failed_response_shape_is_persisted_but_not_accepted(harness: ModuleType) -> None:
    failed = harness.Observation(
        request_hash="e" * 64,
        run_id="run-failed",
        http_status=200,
        runtime_status="failed",
        error_code="runtime.provider_not_configured",
        elapsed_ms=1.0,
        phase="queue",
    )
    assert harness._response_shape_valid(failed) is True
    assert failed.accepted is False


def test_diagnostics_validation_rejects_missing_dynamic_and_inconsistent_fields(
    harness: ModuleType,
) -> None:
    valid = _valid_diagnostics(harness)
    assert harness._diagnostics_valid(valid) is True

    missing = json.loads(json.dumps(valid))
    del missing["by_phase"]
    assert harness._diagnostics_valid(missing) is False

    dynamic = json.loads(json.dumps(valid))
    dynamic["by_error_code"]["raw.dynamic.code"] = 1
    assert harness._diagnostics_valid(dynamic) is False

    inconsistent = json.loads(json.dumps(valid))
    inconsistent["by_http_status"]["200"] += 1
    assert harness._diagnostics_valid(inconsistent) is False

    dynamic_matrix = json.loads(json.dumps(valid))
    dynamic_matrix["by_phase_and_error_code"]["soak"]["raw.dynamic.code"] = 1
    assert harness._diagnostics_valid(dynamic_matrix) is False

    inconsistent_matrix = json.loads(json.dumps(valid))
    inconsistent_matrix["by_phase_and_error_code"]["soak"]["none"] += 1
    assert harness._diagnostics_valid(inconsistent_matrix) is False

    boolean_count = json.loads(json.dumps(valid))
    boolean_count["by_phase_and_error_code"]["soak"]["none"] = True
    assert harness._diagnostics_valid(boolean_count) is False

    float_count = json.loads(json.dumps(valid))
    float_count["by_phase_and_error_code"]["soak"]["none"] = 1.0
    assert harness._diagnostics_valid(float_count) is False


def test_transport_timeout_is_safely_classified_without_exception_text(
    harness: ModuleType,
) -> None:
    class TimeoutClient:
        async def post(self, *_args: object, **_kwargs: object) -> None:
            raise httpx.ReadTimeout("secret transport detail")

    observation = asyncio.run(
        harness._execute(
            TimeoutClient(),
            credential=("site", "key", "secret"),
            label="transport-timeout",
            phase="soak",
        )
    )
    assert observation.http_status == 0
    assert observation.error_code == "transport.timeout"
    summary = harness._diagnostic_summary([observation])
    serialized = json.dumps(summary, sort_keys=True)
    assert summary["by_http_status"]["transport"] == 1
    assert summary["by_error_code"]["transport.timeout"] == 1
    assert summary["by_phase_and_error_code"]["soak"]["transport.timeout"] == 1
    assert summary["negative_control_included"] is False
    assert summary["complete"] is False
    assert "secret transport detail" not in serialized


def test_transport_http_bucket_is_an_explicit_hard_gate(harness: ModuleType) -> None:
    clean = _valid_diagnostics(harness)
    assert harness._transport_http_failures_zero(clean) is True

    observations = [
        harness.Observation(
            request_hash="a" * 64,
            run_id="",
            http_status=400,
            runtime_status="",
            error_code="auth.site_mismatch",
            elapsed_ms=1.0,
            phase="cross_site",
        ),
        harness.Observation(
            request_hash="b" * 64,
            run_id="",
            http_status=0,
            runtime_status="",
            error_code="transport.connect_error",
            elapsed_ms=1.0,
            phase="soak",
        ),
    ]
    transport = harness._diagnostic_summary(observations)
    assert harness._diagnostics_valid(transport) is True
    assert transport["by_http_status"]["transport"] == 1
    assert harness._transport_http_failures_zero(transport) is False
    source = _source(HARNESS)
    assert '"transport_http_failures_zero": _transport_http_failures_zero(diagnostics)' in source


def test_transport_subtype_and_accepted_latency_denominator_are_precise(
    harness: ModuleType,
) -> None:
    accepted = harness.Observation(
        request_hash="a" * 64,
        run_id="run-a",
        http_status=200,
        runtime_status="succeeded",
        error_code="",
        elapsed_ms=200.0,
        phase="soak",
    )
    transport = harness.Observation(
        request_hash="b" * 64,
        run_id="",
        http_status=0,
        runtime_status="",
        error_code="transport.read_error",
        elapsed_ms=1.0,
        phase="soak",
    )
    summary = harness._latency_summary(
        [accepted, transport],
        {accepted.request_hash: 1},
        {accepted.request_hash: 150.0, "db:run-a": 155.0},
    )
    assert summary["attempted_sample_count"] == 2
    assert summary["accepted_sample_count"] == 1
    assert summary["sample_count"] == 1
    assert summary["missing_persistent_evidence_count"] == 0
    assert summary["all_accepted_samples_have_persistent_provider_evidence"] is True

    missing = harness._latency_summary([accepted], {}, {})
    assert missing["accepted_sample_count"] == 1
    assert missing["missing_persistent_evidence_count"] == 1
    assert missing["all_accepted_samples_have_persistent_provider_evidence"] is False

    error = httpx.ReadError("sensitive transport detail")
    assert harness._transport_error_code(error) == "transport.read_error"
    diagnostic = harness._diagnostic_summary([transport])
    assert diagnostic["by_http_status"]["transport"] == 1
    assert diagnostic["by_error_code"]["transport.read_error"] == 1
    assert "sensitive transport detail" not in json.dumps(diagnostic, sort_keys=True)


def test_usage_meter_closed_set_enforces_structural_references(harness: ModuleType) -> None:
    runs = {"run-a"}
    calls = {7: "run-a"}
    assert harness._usage_event_valid(
        SimpleNamespace(meter_key="runs", run_id="run-a", provider_call_id=None, quantity=1),
        runs,
        calls,
    )
    assert not harness._usage_event_valid(
        SimpleNamespace(meter_key="runs", run_id="run-a", provider_call_id=7, quantity=1),
        runs,
        calls,
    )
    assert harness._usage_event_valid(
        SimpleNamespace(meter_key="provider_calls", run_id="run-a", provider_call_id=7, quantity=1),
        runs,
        calls,
    )
    assert not harness._usage_event_valid(
        SimpleNamespace(meter_key="tokens_total", run_id="foreign", provider_call_id=7, quantity=5),
        runs,
        calls,
    )
    assert not harness._usage_event_valid(
        SimpleNamespace(meter_key="cost", run_id="run-a", provider_call_id=7, quantity=0),
        runs,
        calls,
    )
    assert harness._expected_provider_meter_quantities(
        SimpleNamespace(tokens_in=3, tokens_out=2, cost=0)
    ) == {
        "provider_calls": 1.0,
        "tokens_in": 3.0,
        "tokens_out": 2.0,
        "tokens_total": 5.0,
    }
    assert harness._expected_provider_meter_quantities(
        SimpleNamespace(tokens_in=0, tokens_out=0, cost=0.25)
    ) == {"provider_calls": 1.0, "cost": 0.25}


def test_resource_sampler_v5_aggregate_schema_is_exact_and_fail_closed(
    harness: ModuleType, tmp_path: Path
) -> None:
    assert harness.RESOURCE_HEADER.split("\t") == [
        "elapsed_seconds",
        "api_rss_bytes",
        "api_fd_count",
        "worker_rss_bytes",
        "worker_fd_count",
        "postgres_connections",
        "api_restart_count",
        "worker_restart_count",
        "api_running",
        "worker_running",
        "api_process_count",
        "worker_process_count",
        "api_process_identity_sha256",
        "worker_process_identity_sha256",
    ]
    resource = tmp_path / "resources-invalid-v5.tsv"
    old_v3_row = "0\t100\t10\t100\t20\t3\t0\t0\t1\t1"
    _write_resource_rows(resource, harness, [old_v3_row])
    with pytest.raises(harness.ProofFailure, match="resources.row_invalid"):
        harness._resource_evidence(
            resource,
            harness.Shape("quick", 5, 1, 2, 2.0, 8),
            warmup_finished_seconds=0,
            load_finished_seconds=0,
            idle_finished_seconds=0,
        )

    valid = _resource_row(0, 100, 10, 100, 20, 3).split("\t")
    for column, invalid in (
        (9, "2.0"),
        (9, "3"),
        (10, "3.0"),
        (12, "not-a-sha256"),
    ):
        invalid_row = valid.copy()
        invalid_row[column] = invalid
        _write_resource_rows(resource, harness, ["\t".join(invalid_row)])
        with pytest.raises(harness.ProofFailure, match="resources.row_invalid"):
            harness._resource_evidence(
                resource,
                harness.Shape("quick", 5, 1, 2, 2.0, 8),
                warmup_finished_seconds=0,
                load_finished_seconds=0,
                idle_finished_seconds=0,
            )


def test_rss_endpoint_windows_ignore_single_first_and_last_outliers(
    harness: ModuleType, tmp_path: Path
) -> None:
    active = [9_000_000, *([1_000_000] * 107), *([1_100_000] * 11), 9_000_000]
    assert len(active) == 120
    evidence = _formal_rss_evidence(
        harness,
        tmp_path / "rss-endpoint-outliers.tsv",
        active_api_rss=active,
        active_worker_rss=active,
        idle_api_rss=[1_100_000] * 12,
        idle_worker_rss=[1_100_000] * 12,
    )

    for service in ("api", "worker"):
        growth = evidence[f"{service}_rss_growth"]
        assert growth["evaluated"] is True
        assert growth["method"] == "steady_endpoint_window_median_v1"
        assert growth["baseline_window"]["sample_count"] == 12
        assert growth["baseline_window"]["sample_span_seconds"] == 55.0
        assert growth["baseline_window"]["minimum_sample_count"] == 12
        assert growth["baseline_window"]["minimum_span_seconds"] == 55.0
        assert growth["baseline_window"]["median_rss_bytes"] == 1_000_000
        assert growth["baseline_window"]["complete"] is True
        assert growth["terminal_window"]["median_rss_bytes"] == 1_100_000
        assert growth["terminal_window"]["sample_count"] == 12
        assert growth["terminal_window"]["sample_span_seconds"] == 55.0
        assert growth["windows_non_overlapping"] is True
        assert growth["active_within_budget"] is True
        assert growth["idle_confirmation"]["status"] == "within_budget"
        assert growth["within_budget"] is True


def test_rss_exact_ten_percent_passes_but_one_byte_over_fails_without_rounding(
    harness: ModuleType, tmp_path: Path
) -> None:
    baseline = 1_000_000
    exact_ceiling = 1_100_000
    exact = _formal_rss_evidence(
        harness,
        tmp_path / "rss-exact-threshold.tsv",
        active_api_rss=[baseline] * 108 + [exact_ceiling] * 12,
        active_worker_rss=[baseline] * 108 + [exact_ceiling] * 12,
        idle_api_rss=[exact_ceiling] * 12,
        idle_worker_rss=[exact_ceiling] * 12,
    )
    assert exact["api_rss_growth"]["growth_percent"] == 10.0
    assert exact["api_rss_growth"]["active_within_budget"] is True
    assert exact["api_rss_growth"]["within_budget"] is True

    one_byte_over = _formal_rss_evidence(
        harness,
        tmp_path / "rss-one-byte-over.tsv",
        active_api_rss=[baseline] * 108 + [exact_ceiling + 1] * 12,
        active_worker_rss=[baseline] * 108 + [exact_ceiling] * 12,
        idle_api_rss=[baseline] * 12,
        idle_worker_rss=[exact_ceiling] * 12,
    )
    api_growth = one_byte_over["api_rss_growth"]
    assert api_growth["growth_percent"] > 10.0
    assert api_growth["growth_percent_rounded"] == 10.0
    assert api_growth["active_within_budget"] is False
    assert api_growth["idle_confirmation"]["status"] == "within_budget"
    assert api_growth["within_budget"] is False


def test_rss_gate_requires_both_api_and_worker_to_pass(harness: ModuleType, tmp_path: Path) -> None:
    evidence = _formal_rss_evidence(
        harness,
        tmp_path / "rss-worker-over-budget.tsv",
        active_api_rss=[1_000_000] * 108 + [1_100_000] * 12,
        active_worker_rss=[2_000_000] * 108 + [2_200_001] * 12,
        idle_api_rss=[1_100_000] * 12,
        idle_worker_rss=[2_000_000] * 12,
    )
    assert evidence["api_rss_growth"]["within_budget"] is True
    assert evidence["worker_rss_growth"]["within_budget"] is False
    source = _source(HARNESS)
    rss_check = re.search(
        r"rss_growth_passed\s*=\s*not shape\.formal or \((.*?)\)", source, re.DOTALL
    )
    assert rss_check is not None
    assert 'api_rss_growth["within_budget"] is True' in rss_check.group(1)
    assert 'worker_rss_growth["within_budget"] is True' in rss_check.group(1)
    assert 'resources["api_rss_growth"]' in source
    assert 'resources["worker_rss_growth"]' in source
    assert '"rss_growth": rss_growth_passed' in source


def test_rss_active_over_budget_cannot_be_rehabilitated_by_idle_recovery(
    harness: ModuleType, tmp_path: Path
) -> None:
    evidence = _formal_rss_evidence(
        harness,
        tmp_path / "rss-active-over-idle-recovered.tsv",
        active_api_rss=[1_000_000] * 108 + [1_100_001] * 12,
        active_worker_rss=[1_000_000] * 120,
        idle_api_rss=[1_000_000] * 12,
        idle_worker_rss=[1_000_000] * 12,
    )
    growth = evidence["api_rss_growth"]
    assert growth["active_within_budget"] is False
    assert growth["idle_confirmation"]["within_budget"] is True
    assert growth["within_budget"] is False


def test_rss_idle_last_two_blocks_retained_over_budget_fail(
    harness: ModuleType, tmp_path: Path
) -> None:
    evidence = _formal_rss_evidence(
        harness,
        tmp_path / "rss-idle-retained.tsv",
        active_api_rss=[1_000_000] * 108 + [1_100_000] * 12,
        active_worker_rss=[1_000_000] * 120,
        idle_api_rss=[1_100_000] * 6 + [1_100_001] * 6,
        idle_worker_rss=[1_000_000] * 12,
    )
    growth = evidence["api_rss_growth"]
    assert growth["active_within_budget"] is True
    assert growth["idle_confirmation"]["last_two_block_median_rss_bytes"] == [
        1_100_001,
        1_100_001,
    ]
    assert growth["idle_confirmation"]["within_budget"] is False
    assert growth["idle_confirmation"]["status"] != "within_budget"
    assert growth["within_budget"] is False


def test_rss_idle_mixed_last_blocks_fail_closed(harness: ModuleType, tmp_path: Path) -> None:
    evidence = _formal_rss_evidence(
        harness,
        tmp_path / "rss-idle-mixed.tsv",
        active_api_rss=[1_000_000] * 108 + [1_100_000] * 12,
        active_worker_rss=[1_000_000] * 120,
        idle_api_rss=[1_100_000] * 9 + [1_100_001] * 3,
        idle_worker_rss=[1_000_000] * 12,
    )
    idle = evidence["api_rss_growth"]["idle_confirmation"]
    assert idle["last_two_block_median_rss_bytes"] == [1_100_000, 1_100_001]
    assert idle["status"] != "within_budget"
    assert idle["within_budget"] is False
    assert evidence["api_rss_growth"]["within_budget"] is False


def test_rss_idle_missing_samples_fail_closed(harness: ModuleType, tmp_path: Path) -> None:
    rows = [
        _resource_row(index * 5, 1_000_000 if index < 108 else 1_100_000, 10, 1_000_000, 20, 3)
        for index in range(120)
    ]
    rows.extend(
        _resource_row(600 + index * 5, 1_100_000, 10, 1_000_000, 20, 3) for index in range(11)
    )
    resource = tmp_path / "rss-idle-missing.tsv"
    _write_resource_rows(resource, harness, rows)
    evidence = harness._resource_evidence(
        resource,
        harness.Shape("formal", 600, 0, 8, 8.0, 64),
        warmup_finished_seconds=0,
        load_finished_seconds=595,
        idle_finished_seconds=655,
    )
    growth = evidence["api_rss_growth"]
    assert growth["idle_confirmation"]["sample_count"] == 11
    assert growth["idle_confirmation"]["evaluated"] is False
    assert growth["idle_confirmation"]["within_budget"] is False
    assert growth["within_budget"] is False


def test_rss_endpoint_windows_fail_closed_on_short_span_or_overlap(
    harness: ModuleType, tmp_path: Path
) -> None:
    short_span_times = [*range(12), *range(12, 108), *range(540, 600, 5)]
    assert len(short_span_times) == 120
    short_span_rows = [
        _resource_row(
            elapsed,
            1_000_000 if index < 108 else 1_100_000,
            10,
            1_000_000,
            20,
            3,
        )
        for index, elapsed in enumerate(short_span_times)
    ]
    short_span_rows.extend(
        _resource_row(elapsed, 1_100_000, 10, 1_000_000, 20, 3) for elapsed in range(600, 656, 5)
    )
    short_span_path = tmp_path / "rss-endpoint-short-span.tsv"
    _write_resource_rows(short_span_path, harness, short_span_rows)
    short_span = harness._resource_evidence(
        short_span_path,
        harness.Shape("formal", 600, 0, 8, 8.0, 64),
        warmup_finished_seconds=0,
        load_finished_seconds=595,
        idle_finished_seconds=655,
    )["api_rss_growth"]
    assert short_span["baseline_window"]["sample_count"] == 12
    assert short_span["baseline_window"]["sample_span_seconds"] == 11.0
    assert short_span["evaluated"] is False
    assert short_span["within_budget"] is False

    overlap_rows = [
        _resource_row(
            index * 5,
            1_000_000 if index < 9 else 1_100_000,
            10,
            1_000_000,
            20,
            3,
        )
        for index in range(21)
    ]
    overlap_rows.extend(
        _resource_row(105 + index * 5, 1_100_000, 10, 1_000_000, 20, 3) for index in range(12)
    )
    overlap_path = tmp_path / "rss-endpoint-overlap.tsv"
    _write_resource_rows(overlap_path, harness, overlap_rows)
    overlap = harness._resource_evidence(
        overlap_path,
        harness.Shape("formal", 100, 0, 8, 8.0, 64),
        warmup_finished_seconds=0,
        load_finished_seconds=100,
        idle_finished_seconds=160,
    )["api_rss_growth"]
    assert overlap["baseline_window"]["sample_span_seconds"] == 55.0
    assert overlap["terminal_window"]["sample_span_seconds"] == 55.0
    assert overlap["windows_non_overlapping"] is False
    assert overlap["evaluated"] is False
    assert overlap["within_budget"] is False


def test_rss_samples_outside_explicit_boundaries_do_not_affect_growth(
    harness: ModuleType, tmp_path: Path
) -> None:
    rows = [_resource_row(0, 99_000_000, 10, 99_000_000, 20, 3)]
    rows.extend(
        _resource_row(
            5 + index * 5,
            1_000_000 if index < 108 else 1_100_000,
            10,
            1_000_000 if index < 108 else 1_100_000,
            20,
            3,
        )
        for index in range(120)
    )
    rows.extend(
        _resource_row(605 + index * 5, 1_100_000, 10, 1_100_000, 20, 3) for index in range(12)
    )
    rows.append(_resource_row(665, 99_000_000, 10, 99_000_000, 20, 3))
    resource = tmp_path / "rss-boundary-isolation.tsv"
    _write_resource_rows(resource, harness, rows)
    evidence = harness._resource_evidence(
        resource,
        harness.Shape("formal", 600, 0, 8, 8.0, 64),
        warmup_finished_seconds=5,
        load_finished_seconds=600,
        idle_finished_seconds=660,
    )
    assert evidence["api_rss_growth"]["growth_percent"] == 10.0
    assert evidence["api_rss_growth"]["within_budget"] is True
    assert evidence["worker_rss_growth"]["within_budget"] is True


@pytest.mark.parametrize(
    ("service", "mutation"),
    [
        ("api", "process_count"),
        ("api", "identity_sha256"),
        ("worker", "process_count"),
        ("worker", "identity_sha256"),
    ],
)
def test_resource_process_cohort_changes_fail_closed(
    harness: ModuleType, tmp_path: Path, service: str, mutation: str
) -> None:
    sample_count = 132
    api_counts = [3] * sample_count
    worker_counts = [2] * sample_count
    api_identities = [API_PROCESS_IDENTITY_SHA256] * sample_count
    worker_identities = [WORKER_PROCESS_IDENTITY_SHA256] * sample_count
    if mutation == "process_count":
        if service == "api":
            api_counts[60] = 4
        else:
            worker_counts[60] = 1
    else:
        if service == "api":
            api_identities[60] = "e" * 64
        else:
            worker_identities[60] = "f" * 64
    evidence = _formal_rss_evidence(
        harness,
        tmp_path / f"rss-cohort-{service}-{mutation}.tsv",
        active_api_rss=[1_000_000] * 120,
        active_worker_rss=[1_000_000] * 120,
        idle_api_rss=[1_000_000] * 12,
        idle_worker_rss=[1_000_000] * 12,
        api_process_counts=api_counts,
        worker_process_counts=worker_counts,
        api_process_identities=api_identities,
        worker_process_identities=worker_identities,
    )
    cohort = evidence["process_cohort_evidence"]
    assert cohort["evaluated"] is True
    assert cohort["all_valid"] is False
    assert cohort[service]["passed"] is False
    if mutation == "process_count":
        assert cohort[service]["process_count_stable"] is False
    else:
        assert cohort[service]["identity_sha256_unique"] is False
    other_service = "worker" if service == "api" else "api"
    assert cohort[other_service]["passed"] is True
    source = _source(HARNESS)
    assert '"process_cohort_stable": process_cohort_evidence["all_valid"] is True' in source


def test_dual_worker_aggregate_identity_and_survival_are_frozen(
    harness: ModuleType, tmp_path: Path
) -> None:
    evidence = _formal_rss_evidence(
        harness,
        tmp_path / "rss-dual-worker-stable.tsv",
        active_api_rss=[1_000_000] * 120,
        active_worker_rss=[2_000_000] * 120,
        idle_api_rss=[1_000_000] * 12,
        idle_worker_rss=[2_000_000] * 12,
    )
    worker = evidence["process_cohort_evidence"]["worker"]
    assert worker["minimum_process_count"] == 2
    assert worker["process_counts"] == [2]
    assert worker["identity_sha256_values"] == [WORKER_PROCESS_IDENTITY_SHA256]
    assert worker["passed"] is True
    assert evidence["services_survived_all_samples"] is True

    row = _resource_row(
        0,
        1_000_000,
        10,
        2_000_000,
        20,
        3,
        worker_running=1,
    )
    resource = tmp_path / "rss-one-worker-down.tsv"
    _write_resource_rows(resource, harness, [row])
    degraded = harness._resource_evidence(
        resource,
        harness.Shape("quick", 5, 1, 2, 2.0, 8),
        warmup_finished_seconds=0,
        load_finished_seconds=0,
        idle_finished_seconds=0,
    )
    assert degraded["services_survived_all_samples"] is False


def test_resource_gate_detects_restart_downtime_and_per_service_growth(
    harness: ModuleType, tmp_path: Path
) -> None:
    resource = tmp_path / "resources.tsv"
    rows = [
        harness.RESOURCE_HEADER,
        _resource_row(0, 100, 10, 100, 20, 3),
        _resource_row(5, 101, 10, 101, 20, 3),
        _resource_row(10, 102, 10, 102, 20, 3),
        _resource_row(15, 103, 11, 103, 21, 4),
        _resource_row(20, 104, 11, 104, 21, 4),
        _resource_row(25, 105, 11, 105, 21, 4),
        _resource_row(30, 106, 12, 106, 22, 5),
        _resource_row(35, 107, 12, 107, 22, 5),
        _resource_row(40, 108, 12, 108, 22, 5, api_restart_count=1, api_running=0),
    ]
    rows.extend(
        _resource_row(elapsed, 108, 12, 108, 22, 5, api_restart_count=1)
        for elapsed in range(45, 101, 5)
    )
    resource.write_text("\n".join(rows) + "\n", encoding="utf-8")
    quick = harness._resource_evidence(
        resource,
        harness.Shape("quick", 5, 1, 2, 2.0, 8),
        warmup_finished_seconds=0,
        load_finished_seconds=40,
        idle_finished_seconds=40,
    )
    assert quick["api_fd_trend"]["evaluated"] is False
    assert quick["api_fd_sustained_growth"] is False

    evidence = harness._resource_evidence(
        resource,
        harness.Shape("formal", 45, 0, 2, 2.0, 8),
        warmup_finished_seconds=0,
        load_finished_seconds=40,
        idle_finished_seconds=100,
    )
    assert evidence["services_survived_all_samples"] is False
    assert evidence["restart_count_zero"] is False
    assert evidence["api_fd_sustained_growth"] is True
    assert evidence["worker_fd_sustained_growth"] is True
    assert evidence["postgres_connection_sustained_growth"] is True
    assert evidence["api_fd_trend"]["evaluated"] is True
    measured = harness._resource_evidence(
        resource,
        harness.Shape("formal", 45, 0, 2, 2.0, 8),
        warmup_finished_seconds=35,
        load_finished_seconds=40,
        idle_finished_seconds=100,
    )
    assert measured["measured_sample_count"] == 2
    assert measured["api_fd_trend"]["evaluated"] is False
    assert measured["api_fd_sustained_growth"] is False


def test_resource_gate_does_not_call_initial_step_or_stable_jitter_a_leak(
    harness: ModuleType, tmp_path: Path
) -> None:
    resource = tmp_path / "resources-stable.tsv"
    rows = [harness.RESOURCE_HEADER]
    api_fds = [10, 12, 12, 12, 12, 12, 12, 12, 12]
    worker_fds = [20, 21, 20, 21, 20, 21, 20, 21, 20]
    postgres_connections = [3, 4, 4, 4, 4, 4, 4, 4, 4]
    for index, (api_fd, worker_fd, connections) in enumerate(
        zip(api_fds, worker_fds, postgres_connections, strict=True)
    ):
        rows.append(_resource_row(index * 5, 100, api_fd, 100, worker_fd, connections))
    rows.extend(_resource_row(elapsed, 100, 12, 100, 20, 4) for elapsed in range(45, 101, 5))
    resource.write_text("\n".join(rows) + "\n", encoding="utf-8")
    evidence = harness._resource_evidence(
        resource,
        harness.Shape("formal", 45, 0, 8, 8.0, 64),
        warmup_finished_seconds=0,
        load_finished_seconds=40,
        idle_finished_seconds=100,
    )
    assert evidence["api_fd_sustained_growth"] is False
    assert evidence["worker_fd_sustained_growth"] is False
    assert evidence["postgres_connection_sustained_growth"] is False


@pytest.mark.parametrize("step", [1, 5])
def test_resource_gate_does_not_call_one_permanent_step_sustained_growth(
    harness: ModuleType, tmp_path: Path, step: int
) -> None:
    resource = tmp_path / f"resources-single-step-{step}.tsv"
    values = [20] * 60 + [20 + step] * 60
    rows = [harness.RESOURCE_HEADER]
    for index, value in enumerate(values):
        rows.append(_resource_row(index * 5, 100, value, 100, value, value))
    rows.extend(
        _resource_row(elapsed, 100, values[-1], 100, values[-1], values[-1])
        for elapsed in range(600, 656, 5)
    )
    resource.write_text("\n".join(rows) + "\n", encoding="utf-8")

    evidence = harness._resource_evidence(
        resource,
        harness.Shape("formal", 600, 0, 8, 8.0, 64),
        warmup_finished_seconds=0,
        load_finished_seconds=595,
        idle_finished_seconds=655,
    )
    trend = evidence["api_fd_trend"]
    assert trend["evaluated"] is True
    assert trend["new_high_event_count"] == 1
    assert trend["sustained_growth"] is False


@pytest.mark.parametrize(
    ("name", "values"),
    [
        ("repeated", [20] * 40 + [21] * 40 + [22] * 40),
        ("gradual", [20 + index // 30 for index in range(120)]),
        ("late", [10] * 80 + [11] * 10 + [12] * 10 + [13] * 10 + [14] * 10),
    ],
)
def test_resource_gate_detects_repeated_or_late_growth(
    harness: ModuleType, tmp_path: Path, name: str, values: list[int]
) -> None:
    resource = tmp_path / f"resources-{name}.tsv"
    rows = [harness.RESOURCE_HEADER]
    for index, value in enumerate(values):
        rows.append(_resource_row(index * 5, 100, value, 100, value, value))
    rows.extend(
        _resource_row(elapsed, 100, values[-1], 100, values[-1], values[-1])
        for elapsed in range(600, 656, 5)
    )
    resource.write_text("\n".join(rows) + "\n", encoding="utf-8")

    evidence = harness._resource_evidence(
        resource,
        harness.Shape("formal", 600, 0, 8, 8.0, 64),
        warmup_finished_seconds=0,
        load_finished_seconds=595,
        idle_finished_seconds=655,
    )
    trend = evidence["api_fd_trend"]
    assert trend["evaluated"] is True
    assert trend["new_high_event_count"] >= 2
    assert trend["first_to_last_delta"] >= 2
    assert trend["candidate_growth"] is True
    assert trend["idle_recovery"]["status"] == "retained"
    assert trend["sustained_growth"] is True
    assert harness._resource_trend_valid(
        trend,
        formal=True,
        expected_measured_sample_count=evidence["measured_sample_count"],
        expected_minimum_sample_count=evidence["minimum_sample_count"],
        expected_idle_sample_count=evidence["idle_recovery_sample_count"],
        expected_idle_span_seconds=evidence["idle_recovery_sample_span_seconds"],
        expected_idle_samples_complete=evidence["idle_recovery_samples_complete"],
    )


def test_resource_gate_transient_active_growth_recovers_during_idle(
    harness: ModuleType, tmp_path: Path
) -> None:
    resource = tmp_path / "resources-transient-recovery.tsv"
    measured = [20] * 40 + [21] * 40 + [22] * 40
    idle = [22] * 3 + [21] * 3 + [20] * 6
    values = [*measured, *idle]
    rows = [harness.RESOURCE_HEADER]
    for index, value in enumerate(values):
        rows.append(_resource_row(index * 5, 100, value, 100, value, value))
    resource.write_text("\n".join(rows) + "\n", encoding="utf-8")

    evidence = harness._resource_evidence(
        resource,
        harness.Shape("formal", 600, 0, 8, 8.0, 64),
        warmup_finished_seconds=0,
        load_finished_seconds=595,
        idle_finished_seconds=655,
    )
    trend = evidence["api_fd_trend"]
    assert evidence["idle_recovery_samples_complete"] is True
    assert trend["candidate_growth"] is True
    assert trend["global_candidate_growth"] is True
    assert trend["idle_recovery"]["status"] == "recovered"
    assert trend["global_sustained_growth"] is False
    assert trend["confirmed_sustained_growth"] is False
    assert trend["sustained_growth"] is False
    assert harness._resource_trend_valid(
        trend,
        formal=True,
        expected_measured_sample_count=evidence["measured_sample_count"],
        expected_minimum_sample_count=evidence["minimum_sample_count"],
        expected_idle_sample_count=evidence["idle_recovery_sample_count"],
        expected_idle_span_seconds=evidence["idle_recovery_sample_span_seconds"],
        expected_idle_samples_complete=evidence["idle_recovery_samples_complete"],
    )


def test_resource_gate_excludes_samples_after_idle_end_boundary(
    harness: ModuleType, tmp_path: Path
) -> None:
    resource = tmp_path / "resources-bounded-idle.tsv"
    measured = [20] * 40 + [21] * 40 + [22] * 40
    idle = [22] * 3 + [21] * 3 + [20] * 6
    after_idle = [30, 31, 32, 33, 34, 35]
    rows = [harness.RESOURCE_HEADER]
    for index, value in enumerate([*measured, *idle, *after_idle]):
        rows.append(_resource_row(index * 5, 100, value, 100, value, value))
    resource.write_text("\n".join(rows) + "\n", encoding="utf-8")

    evidence = harness._resource_evidence(
        resource,
        harness.Shape("formal", 600, 0, 8, 8.0, 64),
        warmup_finished_seconds=0,
        load_finished_seconds=595,
        idle_finished_seconds=655,
    )
    trend = evidence["api_fd_trend"]
    assert evidence["sample_count"] == len(measured) + len(idle) + len(after_idle)
    assert evidence["idle_recovery_sample_count"] == 12
    assert evidence["idle_end_boundary_elapsed_seconds"] == 655
    assert trend["idle_recovery"]["block_median_levels"] == [22.0, 21.0, 20.0, 20.0]
    assert trend["idle_recovery"]["status"] == "recovered"
    assert trend["sustained_growth"] is False


def test_resource_gate_rejects_idle_end_before_load_end(
    harness: ModuleType, tmp_path: Path
) -> None:
    resource = tmp_path / "resources-invalid-idle-boundary.tsv"
    resource.write_text(
        f"{harness.RESOURCE_HEADER}\n{_resource_row(0, 100, 10, 100, 20, 3)}\n",
        encoding="utf-8",
    )

    with pytest.raises(harness.ProofFailure, match="resources.idle_boundary_invalid"):
        harness._resource_evidence(
            resource,
            harness.Shape("quick", 5, 1, 2, 2.0, 8),
            warmup_finished_seconds=0,
            load_finished_seconds=5,
            idle_finished_seconds=4,
        )


def test_resource_gate_fails_closed_when_idle_samples_are_insufficient(
    harness: ModuleType, tmp_path: Path
) -> None:
    resource = tmp_path / "resources-idle-insufficient.tsv"
    measured = [20] * 40 + [21] * 40 + [22] * 40
    idle = [22] * 11
    rows = [harness.RESOURCE_HEADER]
    for index, value in enumerate([*measured, *idle]):
        rows.append(_resource_row(index * 5, 100, value, 100, value, value))
    resource.write_text("\n".join(rows) + "\n", encoding="utf-8")

    evidence = harness._resource_evidence(
        resource,
        harness.Shape("formal", 600, 0, 8, 8.0, 64),
        warmup_finished_seconds=0,
        load_finished_seconds=595,
        idle_finished_seconds=650,
    )
    trend = evidence["api_fd_trend"]
    assert evidence["measured_sample_count_passed"] is True
    assert evidence["idle_recovery_sample_count"] == 11
    assert evidence["idle_recovery_sample_span_seconds"] == 50
    assert evidence["idle_recovery_samples_complete"] is False
    assert evidence["sample_count_passed"] is False
    assert trend["candidate_growth"] is True
    assert trend["idle_recovery"]["status"] == "insufficient_samples"
    assert trend["sustained_growth"] is True
    assert harness._resource_trend_valid(
        trend,
        formal=True,
        expected_measured_sample_count=evidence["measured_sample_count"],
        expected_minimum_sample_count=evidence["minimum_sample_count"],
        expected_idle_sample_count=evidence["idle_recovery_sample_count"],
        expected_idle_span_seconds=evidence["idle_recovery_sample_span_seconds"],
        expected_idle_samples_complete=evidence["idle_recovery_samples_complete"],
    )


def test_resource_gate_treats_mixed_idle_floor_as_inconclusive(
    harness: ModuleType, tmp_path: Path
) -> None:
    resource = tmp_path / "resources-idle-inconclusive.tsv"
    measured = [20] * 40 + [21] * 40 + [22] * 40
    idle = [22] * 6 + [21] * 3 + [22] * 3
    rows = [harness.RESOURCE_HEADER]
    for index, value in enumerate([*measured, *idle]):
        rows.append(_resource_row(index * 5, 100, value, 100, value, value))
    resource.write_text("\n".join(rows) + "\n", encoding="utf-8")

    evidence = harness._resource_evidence(
        resource,
        harness.Shape("formal", 600, 0, 8, 8.0, 64),
        warmup_finished_seconds=0,
        load_finished_seconds=595,
        idle_finished_seconds=655,
    )
    trend = evidence["api_fd_trend"]
    assert trend["idle_recovery"]["last_two_block_levels"] == [21.0, 22.0]
    assert trend["idle_recovery"]["status"] == "inconclusive"
    assert trend["sustained_growth"] is True


def test_resource_gate_fails_when_idle_itself_keeps_growing(
    harness: ModuleType, tmp_path: Path
) -> None:
    resource = tmp_path / "resources-idle-growing.tsv"
    measured = [20] * 120
    idle = [20] * 3 + [21] * 3 + [22] * 3 + [23] * 3
    rows = [harness.RESOURCE_HEADER]
    for index, value in enumerate([*measured, *idle]):
        rows.append(_resource_row(index * 5, 100, value, 100, value, value))
    resource.write_text("\n".join(rows) + "\n", encoding="utf-8")

    evidence = harness._resource_evidence(
        resource,
        harness.Shape("formal", 600, 0, 8, 8.0, 64),
        warmup_finished_seconds=0,
        load_finished_seconds=595,
        idle_finished_seconds=655,
    )
    trend = evidence["api_fd_trend"]
    assert trend["candidate_growth"] is False
    assert trend["idle_recovery"]["continued_growth_candidate"] is True
    assert trend["idle_recovery"]["status"] == "continued_growth"
    assert trend["sustained_growth"] is True


def test_resource_gate_detects_growth_confined_to_terminal_window(
    harness: ModuleType, tmp_path: Path
) -> None:
    resource = tmp_path / "resources-terminal-growth.tsv"
    values = [20] * 100 + [20] * 2 + [21] * 3 + [22] * 5 + [23] * 5 + [24] * 5
    rows = [harness.RESOURCE_HEADER]
    for index, value in enumerate(values):
        rows.append(_resource_row(index * 5, 100, value, 100, value, value))
    rows.extend(_resource_row(elapsed, 100, 24, 100, 24, 24) for elapsed in range(600, 656, 5))
    resource.write_text("\n".join(rows) + "\n", encoding="utf-8")

    evidence = harness._resource_evidence(
        resource,
        harness.Shape("formal", 600, 0, 8, 8.0, 64),
        warmup_finished_seconds=0,
        load_finished_seconds=595,
        idle_finished_seconds=655,
    )
    trend = evidence["api_fd_trend"]
    assert trend["global_candidate_growth"] is False
    assert trend["new_high_event_count"] == 1
    assert trend["terminal_window"]["new_high_event_count"] >= 2
    assert trend["terminal_window"]["sustained_growth"] is True
    assert trend["sustained_growth"] is True


def test_resource_gate_does_not_call_one_late_step_terminal_growth(
    harness: ModuleType, tmp_path: Path
) -> None:
    resource = tmp_path / "resources-terminal-step.tsv"
    values = [20] * 110 + [25] * 10
    rows = [harness.RESOURCE_HEADER]
    for index, value in enumerate(values):
        rows.append(_resource_row(index * 5, 100, value, 100, value, value))
    rows.extend(_resource_row(elapsed, 100, 25, 100, 25, 25) for elapsed in range(600, 656, 5))
    resource.write_text("\n".join(rows) + "\n", encoding="utf-8")

    evidence = harness._resource_evidence(
        resource,
        harness.Shape("formal", 600, 0, 8, 8.0, 64),
        warmup_finished_seconds=0,
        load_finished_seconds=595,
        idle_finished_seconds=655,
    )
    trend = evidence["api_fd_trend"]
    assert trend["terminal_window"]["new_high_event_count"] == 1
    assert trend["terminal_window"]["sustained_growth"] is False
    assert trend["sustained_growth"] is False


def test_resource_gate_ignores_spike_and_requires_formal_sample_floor(
    harness: ModuleType, tmp_path: Path
) -> None:
    resource = tmp_path / "resources-sample-floor.tsv"

    def evidence_for(values: list[int]) -> dict[str, object]:
        rows = [harness.RESOURCE_HEADER]
        for index, value in enumerate(values):
            rows.append(_resource_row(index * 5, 100, value, 100, value, value))
        load_finished_seconds = (len(values) - 1) * 5
        rows.extend(
            _resource_row(
                load_finished_seconds + offset,
                100,
                values[-1],
                100,
                values[-1],
                values[-1],
            )
            for offset in range(5, 61, 5)
        )
        resource.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return harness._resource_evidence(
            resource,
            harness.Shape("formal", 600, 0, 8, 8.0, 64),
            warmup_finished_seconds=0,
            load_finished_seconds=load_finished_seconds,
            idle_finished_seconds=load_finished_seconds + 60,
        )

    spike = evidence_for([20] * 59 + [50] + [20] * 60)
    assert spike["api_fd_trend"]["sustained_growth"] is False

    below_floor = evidence_for([20] * 107)
    assert below_floor["sample_count_passed"] is False
    assert below_floor["api_fd_trend"]["evaluated"] is False

    at_floor = evidence_for([20] * 108)
    assert at_floor["sample_count_passed"] is True
    assert at_floor["api_fd_trend"]["evaluated"] is True
    assert at_floor["api_fd_trend"]["sustained_growth"] is False


def test_resource_sampler_origin_is_shared_before_record_timer(harness: ModuleType) -> None:
    request, response = harness._resource_sync_paths(Path("resources.tsv"))
    assert request.name == "resources.tsv.sync-request"
    assert response.name == "resources.tsv.sync-response"
    source = _source(HARNESS)
    assert source.index(
        "resource_time_origin = await asyncio.to_thread(_resource_time_origin"
    ) < source.index("record_started = time.monotonic()")
    client_close = source.index(
        "load_finished_seconds = resource_time_origin + time.monotonic() - record_started"
    )
    first_idle_sync = source.index(
        "await asyncio.to_thread(_resource_time_origin, args.resource_file)",
        client_close,
    )
    idle_wait = source.index(
        "await asyncio.sleep(FORMAL_RESOURCE_IDLE_RECOVERY_SECONDS)",
        first_idle_sync,
    )
    final_idle_sync = source.index(
        "idle_finished_seconds = await asyncio.to_thread(",
        idle_wait,
    )
    assert client_close < first_idle_sync < idle_wait < final_idle_sync


def test_redaction_and_atomic_locked_output(harness: ModuleType, tmp_path: Path) -> None:
    safe = {"requests": {"attempted": 1}, "raw_run_or_site_identifiers_emitted": False}
    assert harness._redaction_violations(safe) == []
    assert harness._redaction_violations({"run_id": "raw"}) == ["$.run_id"]
    assert harness._redaction_violations({"request_hash": "raw"}) == ["$.request_hash"]
    output = tmp_path / "evidence.json"
    harness._write_json(output, safe)
    assert json.loads(output.read_text(encoding="utf-8")) == safe
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    source = _source(HARNESS)
    assert "handle.flush()" in source
    assert "os.fsync(handle.fileno())" in source
    assert source.index("os.fsync(handle.fileno())") < source.index("os.replace(temporary, path)")


def test_provider_and_database_safety_contracts_are_fail_closed() -> None:
    source = _source(HARNESS)

    assert "shobj_description(oid, 'pg_database')" in source
    assert "length < 1 or length > 1024 * 1024" in source
    assert "provider_invocations" in source
    assert "provider_duration_us" in source
    assert "provider_max_active" in source
    assert "P5_B4_MIGRATION_HEAD_SOURCE_SHA256" in source
    assert "P5_B4_DATASET_CONFIG" in source
    assert "P5_B4_GIT_DIRTY_COUNT" in source
    assert "AccountEntitlementSnapshot.plan_version_id" in source
    assert "prepare.commercial_baseline_incomplete" in source


def test_wrapper_output_path_and_cleanup_guards_are_fail_closed() -> None:
    source = _source(WRAPPER)

    for function_name in (
        "canonicalize_path",
        "canonicalize_existing_directory",
        "path_is_equal_or_within",
    ):
        assert re.search(rf"^{function_name}\(\) \{{", source, re.MULTILINE)
    absolute_git_dir = source.index("git rev-parse --absolute-git-dir")
    common_git_dir = source.index("git rev-parse --git-common-dir")
    docker_probe = source.index("docker info >/dev/null 2>&1")
    assert absolute_git_dir < common_git_dir < docker_probe
    assert 'canonicalize_existing_directory "${WORKTREE_GIT_DIR_RAW}"' in source
    assert 'canonicalize_existing_directory "${GIT_COMMON_DIR_RAW}"' in source
    for protected_root in ("ROOT_DIR", "WORKTREE_GIT_DIR", "GIT_COMMON_DIR"):
        assert f'path_is_equal_or_within "${{OUTPUT_PATH}}" "${{{protected_root}}}"' in source

    assert '[ ! -L "${OUTPUT_CANDIDATE}" ] || fail' in source
    non_regular_guard = re.search(
        r'if \[ -e "\$\{OUTPUT_PATH\}" \] && \[ ! -f "\$\{OUTPUT_PATH\}" \]; then\n'
        r"\s*fail 'existing output path must be a regular file'\nfi",
        source,
    )
    assert non_regular_guard is not None
    assert '[ -e "${OUTPUT_PATH}" ] && [ -f "${OUTPUT_PATH}" ]' not in source

    cleanup_assignments = re.findall(r"^DOCKER_CLEANUP_REQUIRED=([01])$", source, re.MULTILINE)
    assert cleanup_assignments == ["0", "1"]
    cleanup_arm = source.index("DOCKER_CLEANUP_REQUIRED=1")
    assert cleanup_arm < source.index("docker build", cleanup_arm)
    on_exit = re.search(r"^on_exit\(\) \{(.*?)^\}$", source, re.MULTILINE | re.DOTALL)
    assert on_exit is not None
    assert 'if [ "${DOCKER_CLEANUP_REQUIRED}" -eq 1 ]; then' in on_exit.group(1)


def test_sampler_job_state_excludes_done_but_keeps_running_and_stopped() -> None:
    active_function = _shell_function(_source(WRAPPER), "sampler_job_is_active")
    script = f"""
set -u
{active_function}

job_state=done
jobs() {{
    case "${{job_state}}:$1" in
    done:-p|running:-p|stopped:-p)
        printf '%s\n' 4242
        ;;
    running:-pr|stopped:-ps)
        printf '%s\n' 4242
        ;;
    done:-pr|done:-ps|running:-ps|stopped:-pr|missing:-pr|missing:-ps)
        return 0
        ;;
    *)
        return 91
        ;;
    esac
}}

sampler_job_is_active 4242 && exit 10
job_state=running
sampler_job_is_active 4242 || exit 11
job_state=stopped
sampler_job_is_active 4242 || exit 12
job_state=missing
sampler_job_is_active 4242 && exit 13
exit 0
"""
    completed = subprocess.run(
        ["/bin/bash"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_stop_sampler_reaps_success_and_propagates_nonzero_exit() -> None:
    source = _source(WRAPPER)
    functions = "\n\n".join(
        _shell_function(source, name)
        for name in (
            "sampler_job_is_active",
            "wait_for_sampler_exit",
            "stop_sampler",
        )
    )
    script = f"""
set -u
{functions}

scratch="$(mktemp -d)" || exit 20
trap 'rm -rf -- "${{scratch}}"' EXIT
SAMPLER_PID=""
SAMPLER_STOP_FILE="${{scratch}}/success-stop"
successful_sampler() {{
    while [ ! -e "${{SAMPLER_STOP_FILE}}" ]; do
        sleep 0.01 || return 21
    done
    return 0
}}
successful_sampler &
SAMPLER_PID=$!
stop_sampler || exit 22
[ -z "${{SAMPLER_PID}}" ] || exit 23
[ -z "$(jobs -p)" ] || exit 24

SAMPLER_STOP_FILE="${{scratch}}/failure-stop"
failing_sampler() {{
    while [ ! -e "${{SAMPLER_STOP_FILE}}" ]; do
        sleep 0.01 || return 25
    done
    return 7
}}
failing_sampler &
SAMPLER_PID=$!
stop_sampler && exit 26
[ -z "${{SAMPLER_PID}}" ] || exit 27
[ -z "$(jobs -p)" ] || exit 28
exit 0
"""
    completed = subprocess.run(
        ["/bin/bash"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_wrapper_has_fresh_baselines_cleanup_and_no_quick_acceptance_claim(
    harness: ModuleType,
) -> None:
    source = _source(WRAPPER)

    dataset_match = re.search(r"^DATASET_CONFIG='(.+)'$", source, re.MULTILINE)
    assert dataset_match is not None
    dataset_id_match = re.search(r'^DATASET_ID="(.+)"$', source, re.MULTILINE)
    assert dataset_id_match is not None
    assert dataset_id_match.group(1) == harness.EXPECTED_DATASET_ID
    dataset = json.loads(dataset_match.group(1))
    assert dataset == harness.EXPECTED_DATASET_CONFIG
    assert dataset_match.group(1) == json.dumps(
        harness.EXPECTED_DATASET_CONFIG,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert dataset["contract"] == "p5_b4_runtime_dataset.v5"
    assert dataset["commercial"] == {"max_ai_credits_per_site_period": 10_000.0}
    assert dataset["formal"]["resource_idle_recovery_seconds"] == 60
    assert dataset["formal"]["resource_idle_minimum_sample_count"] == 12
    assert dataset["formal"]["resource_idle_minimum_span_seconds"] == 55
    assert (
        dataset["formal"]["resource_process_scope"]
        == "pid1_service_trees_aggregate_stable_cohort_v3"
    )
    assert dataset["formal"]["rss_endpoint_window_sample_count"] == 12
    assert dataset["formal"]["rss_endpoint_window_min_span_seconds"] == 55
    assert dataset["formal"]["rss_growth_method"] == "steady_endpoint_window_median_v1"
    assert dataset["formal"]["rss_growth_percent_max"] == 10
    assert dataset["formal"]["rss_idle_method"] == "four_block_budget_confirmation_v1"
    assert dataset["worker"]["replicas"] == 2

    assert "NON-ACCEPTANCE" in source
    assert "--volumes" in source
    assert "--remove-orphans" in source
    assert 'P5_B4_TOPOLOGY_VERIFIED="true"' in source
    assert "api_restart_count" in source
    assert "worker_restart_count" in source
    assert ".sync-request" in source
    assert ".sync-response" in source
    assert "P5-B4 prepare failure evidence" in source
    assert "runner-network API preflight" in source
    assert "probe-api" in source
    assert "baseline-" in source
    assert "aggregate" in source
    assert "def process_identity(pid):" in source
    assert "service process tree changed during measurement" in source
    assert 'container_process_metrics "${api_container}" 3' in source
    assert 'container_process_metrics "${worker_container}" 1' in source
    assert "project_container_inventory()" in source
    assert "capture_proof_topology()" in source
    assert "topology_is_running_and_unrestarted()" in source
    assert "verify_topology_snapshot()" in source
    assert "verify_source_snapshot()" in source
    assert "require_source_snapshot()" in source
    for checkpoint in (
        "require_source_snapshot 'after proof image build'",
        'require_source_snapshot "before baseline ${baseline_index}"',
        'require_source_snapshot "after baseline ${baseline_index}"',
        "require_source_snapshot 'before aggregate'",
        "require_source_snapshot 'after aggregate'",
        "require_source_snapshot 'immediately before publish_output'",
    ):
        assert checkpoint in source
    assert source.index("docker build") < source.index(
        "require_source_snapshot 'after proof image build'"
    )
    assert source.index("require_source_snapshot 'after aggregate'") < source.index(
        'publish_output "${OUTPUT_PATH}"'
    )
    assert "proof-api proof-worker proof-provider proof-postgres proof-redis" in source
    assert 'container_ids_have_count "${worker_containers}" 2' in source
    assert '[ "${current_topology}" = "${expected_topology}" ]' in source
    assert 'docker exec "${postgres_container}"' in source
    assert '[ "${worker_container_running}" -eq 1 ]' in source
    assert '[ "${worker_container_restarts}" -eq 0 ]' in source
    assert "worker_rss=$((worker_rss + worker_container_rss))" in source
    assert "worker_fds=$((worker_fds + worker_container_fds))" in source
    assert (
        "worker_process_count=$((worker_process_count + worker_container_process_count))" in source
    )
    assert "worker_identity_material" in source
    assert '"${worker_container}"' in source
    assert "expected_worker_process_identity_sha256" in source
    assert "proof-worker topology does not contain exactly two containers" in source
    assert "real API/two-worker/provider/Postgres/Redis topology is not healthy" in source
    topology_health = re.search(
        r"topology_is_running_and_unrestarted\(\) \{(.*?)\n\}\n\nverify_topology_snapshot",
        source,
        re.DOTALL,
    )
    assert topology_health is not None
    topology_health_body = topology_health.group(1)
    assert re.search(r"proof-worker\)\s*;;", topology_health_body)
    assert "proof-api|proof-provider|proof-postgres|proof-redis)" in topology_health_body
    assert 'health_status="$(container_health_status "${container_id}")"' in topology_health_body
    assert '[ "${health_status}" = "healthy" ] || return 1' in topology_health_body
    assert 'topology_is_running_and_unrestarted "${current_topology}" || return 1' in source
    assert "sampler_job_is_active()" in source
    assert "wait_for_sampler_exit()" in source
    sampler_active = _shell_function(source, "sampler_job_is_active")
    assert 'active_jobs="$({ jobs -pr; jobs -ps; })"' in sampler_active
    assert re.search(r"\bjobs -p\b", sampler_active) is None
    assert 'kill -TERM "${sampler_pid}"' in source
    assert 'kill -KILL "${sampler_pid}"' in source
    assert 'wait_for_sampler_exit "${sampler_pid}" 150' in source
    assert 'wait_for_sampler_exit "${sampler_pid}" 50' in source
    assert 'wait_for_sampler_exit "${sampler_pid}" 20' in source
    assert (
        'docker ps --all --quiet --filter "label=com.docker.compose.project=${project}"' in source
    )
    assert (
        'docker volume ls --quiet --filter "label=com.docker.compose.project=${project}"' in source
    )
    assert (
        'docker network ls --quiet --filter "label=com.docker.compose.project=${project}"' in source
    )
    assert 'if ! all_image_ids="$(docker image ls --all --quiet --no-trunc)"' in source
    assert "api_process_count" in source
    assert "worker_process_count" in source
    assert "api_process_identity_sha256" in source
    assert "worker_process_identity_sha256" in source
    assert "publish_output" in source
    assert "os.fsync(stream.fileno())" in source
    assert source.index("os.fsync(stream.fileno())") < source.index(
        "os.replace(temporary_name, target)"
    )
    assert "install -m 600" not in source
    assert "docker system prune" not in source
