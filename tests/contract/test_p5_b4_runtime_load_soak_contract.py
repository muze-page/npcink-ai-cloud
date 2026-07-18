from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import re
import stat
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


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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


def _valid_diagnostics(harness: ModuleType) -> dict[str, object]:
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
    return harness._diagnostic_summary(observations)


def _record(
    harness: ModuleType,
    index: int,
    *,
    mode: str = "formal",
    p95: float = 100,
    p99: float = 150,
) -> dict:
    return {
        "contract": "p5_b4_external_runtime_load_soak_proof.v3",
        "mode": mode,
        "baseline_index": index,
        "baseline_environment_receipt_sha256": f"{index:064x}",
        "verdict": "record_passed",
        "record_thresholds_passed": True,
        "formal_record_shape": mode == "formal",
        "formal_acceptance": False,
        "identity": {"revision": "a" * 40, "dataset_sha256": "b" * 64},
        "configuration": {"duration_seconds": 600 if mode == "formal" else 5},
        "scheduler": {"measured": {"max_in_flight": 8}},
        "requests": {"unexpected_5xx": 0},
        "observation_diagnostics": _valid_diagnostics(harness),
        "queue": {"requested": 64, "accepted": 64, "completed": 64},
        "latency": {
            "provider_excluded_p95_ms": p95,
            "provider_excluded_p99_ms": p99,
        },
        "integrity": {"duplicates_or_missing": 0},
        "isolation": {"cross_site_result_read_rejected": True},
        "resources": {"restart_count_zero": True},
        "checks": {"all": True},
        "boundary": {"external_http_gunicorn": True},
        "limitations": ["deterministic_local_provider"],
    }


def _write_records(path: Path, records: list[dict]) -> None:
    for record in records:
        (path / f"baseline-{record['baseline_index']}.json").write_text(
            json.dumps(record, sort_keys=True), encoding="utf-8"
        )


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
    assert 'NPCINK_CLOUD_WORKER_HEARTBEAT_INTERVAL_SECONDS: "30"' in compose
    api_url = re.search(r"P5_B4_PROOF_API_URL:\s*(\S+)", compose)
    trusted_hosts = re.search(r"NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST:\s*(\S+)", compose)
    assert api_url is not None and trusted_hosts is not None
    assert urlsplit(api_url.group(1)).hostname in trusted_hosts.group(1).split(",")
    assert "internal: true" in compose
    assert "ports:" not in compose


def test_formal_shape_and_subcommand_contract_are_frozen(harness: ModuleType) -> None:
    assert harness.CONTRACT_ID == "p5_b4_external_runtime_load_soak_proof.v3"
    assert harness.FORMAL_RECORDS == 3
    assert harness.FORMAL_DURATION_SECONDS == 600
    assert harness.FORMAL_WARMUP_SECONDS == 30
    assert harness.FORMAL_CONCURRENCY == 8
    assert harness.FORMAL_REQUEST_RATE == 8.0
    assert harness.FORMAL_QUEUE_BURST == 64
    assert harness.DEFAULT_WORKER_POLL_SECONDS == 5
    assert harness.DEFAULT_WORKER_BATCH_SIZE == 8
    assert harness.FORMAL_RESOURCE_IDLE_RECOVERY_SECONDS == 60
    assert harness.FORMAL_RESOURCE_IDLE_MIN_SAMPLES == 12
    assert harness.FORMAL_RESOURCE_IDLE_MIN_SPAN_SECONDS == 55.0
    assert harness.SITE_COUNT == 8
    assert harness.PROOF_MAX_AI_CREDITS_PER_SITE_PERIOD == 10_000.0
    parser = harness._parser()
    assert parser.parse_args(["--confirm-disposable", "serve-provider"]).command == (
        "serve-provider"
    )
    assert parser.parse_args(["--confirm-disposable", "probe-api"]).command == "probe-api"
    assert (
        parser.parse_args(["--confirm-disposable", "prepare", "--baseline-index", "1"]).command
        == "prepare"
    )


def test_dataset_attribution_requires_v3(
    harness: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = {
        "commercial": {"max_ai_credits_per_site_period": 10_000.0},
        "contract": "p5_b4_runtime_dataset.v3",
    }

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

    set_dataset({**dataset, "contract": "p5_b4_runtime_dataset.v2"})
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
    rejected, rejected_ok = harness._aggregate(
        SimpleNamespace(mode="formal", input_dir=tmp_path, baseline_count=3)
    )
    assert rejected_ok is False
    assert rejected["record_contracts_match"] is False

    records[2]["observation_diagnostics"]["by_phase"]["raw-dynamic-phase"] = 1
    _write_records(tmp_path, [records[2]])
    with pytest.raises(
        harness.ProofFailure,
        match="aggregate.observation_diagnostics_invalid",
    ):
        harness._aggregate(SimpleNamespace(mode="formal", input_dir=tmp_path, baseline_count=3))


def test_formal_aggregate_rejects_legacy_v2_record(
    harness: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("P5_B4_TOPOLOGY_VERIFIED", "true")
    records = [_record(harness, index) for index in range(1, 4)]
    records[1]["contract"] = "p5_b4_external_runtime_load_soak_proof.v2"
    _write_records(tmp_path, records)

    report, ok = harness._aggregate(
        SimpleNamespace(mode="formal", input_dir=tmp_path, baseline_count=3)
    )

    assert ok is False
    assert report["formal_acceptance"] is False
    assert report["record_contracts_match"] is False


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
    assert summary["by_http_status"]["200"] == 2
    assert summary["by_http_status"]["400"] == 1
    assert summary["by_http_status"]["422"] == 1
    assert summary["by_error_code"]["auth.site_mismatch"] == 1
    assert summary["by_error_code"]["other"] == 1
    assert summary["by_runtime_status"]["other"] == 1
    assert summary["by_phase"]["other"] == 1
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
    assert summary["negative_control_included"] is False
    assert summary["complete"] is False
    assert "secret transport detail" not in serialized


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


def test_resource_gate_detects_restart_downtime_and_per_service_growth(
    harness: ModuleType, tmp_path: Path
) -> None:
    resource = tmp_path / "resources.tsv"
    rows = [
        harness.RESOURCE_HEADER,
        "0\t100\t10\t100\t20\t3\t0\t0\t1\t1",
        "5\t101\t10\t101\t20\t3\t0\t0\t1\t1",
        "10\t102\t10\t102\t20\t3\t0\t0\t1\t1",
        "15\t103\t11\t103\t21\t4\t0\t0\t1\t1",
        "20\t104\t11\t104\t21\t4\t0\t0\t1\t1",
        "25\t105\t11\t105\t21\t4\t0\t0\t1\t1",
        "30\t106\t12\t106\t22\t5\t0\t0\t1\t1",
        "35\t107\t12\t107\t22\t5\t0\t0\t1\t1",
        "40\t108\t12\t108\t22\t5\t1\t0\t0\t1",
    ]
    rows.extend(f"{elapsed}\t108\t12\t108\t22\t5\t1\t0\t1\t1" for elapsed in range(45, 101, 5))
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
        rows.append(f"{index * 5}\t100\t{api_fd}\t100\t{worker_fd}\t{connections}\t0\t0\t1\t1")
    rows.extend(f"{elapsed}\t100\t12\t100\t20\t4\t0\t0\t1\t1" for elapsed in range(45, 101, 5))
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
        rows.append(f"{index * 5}\t100\t{value}\t100\t{value}\t{value}\t0\t0\t1\t1")
    rows.extend(
        f"{elapsed}\t100\t{values[-1]}\t100\t{values[-1]}\t{values[-1]}\t0\t0\t1\t1"
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
        rows.append(f"{index * 5}\t100\t{value}\t100\t{value}\t{value}\t0\t0\t1\t1")
    rows.extend(
        f"{elapsed}\t100\t{values[-1]}\t100\t{values[-1]}\t{values[-1]}\t0\t0\t1\t1"
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


def test_resource_gate_transient_active_growth_recovers_during_idle(
    harness: ModuleType, tmp_path: Path
) -> None:
    resource = tmp_path / "resources-transient-recovery.tsv"
    measured = [20] * 40 + [21] * 40 + [22] * 40
    idle = [22] * 3 + [21] * 3 + [20] * 6
    values = [*measured, *idle]
    rows = [harness.RESOURCE_HEADER]
    for index, value in enumerate(values):
        rows.append(f"{index * 5}\t100\t{value}\t100\t{value}\t{value}\t0\t0\t1\t1")
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


def test_resource_gate_excludes_samples_after_idle_end_boundary(
    harness: ModuleType, tmp_path: Path
) -> None:
    resource = tmp_path / "resources-bounded-idle.tsv"
    measured = [20] * 40 + [21] * 40 + [22] * 40
    idle = [22] * 3 + [21] * 3 + [20] * 6
    after_idle = [30, 31, 32, 33, 34, 35]
    rows = [harness.RESOURCE_HEADER]
    for index, value in enumerate([*measured, *idle, *after_idle]):
        rows.append(f"{index * 5}\t100\t{value}\t100\t{value}\t{value}\t0\t0\t1\t1")
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
        f"{harness.RESOURCE_HEADER}\n0\t100\t10\t100\t20\t3\t0\t0\t1\t1\n",
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
        rows.append(f"{index * 5}\t100\t{value}\t100\t{value}\t{value}\t0\t0\t1\t1")
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


def test_resource_gate_treats_mixed_idle_floor_as_inconclusive(
    harness: ModuleType, tmp_path: Path
) -> None:
    resource = tmp_path / "resources-idle-inconclusive.tsv"
    measured = [20] * 40 + [21] * 40 + [22] * 40
    idle = [22] * 6 + [21] * 3 + [22] * 3
    rows = [harness.RESOURCE_HEADER]
    for index, value in enumerate([*measured, *idle]):
        rows.append(f"{index * 5}\t100\t{value}\t100\t{value}\t{value}\t0\t0\t1\t1")
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
        rows.append(f"{index * 5}\t100\t{value}\t100\t{value}\t{value}\t0\t0\t1\t1")
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
        rows.append(f"{index * 5}\t100\t{value}\t100\t{value}\t{value}\t0\t0\t1\t1")
    rows.extend(f"{elapsed}\t100\t24\t100\t24\t24\t0\t0\t1\t1" for elapsed in range(600, 656, 5))
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
        rows.append(f"{index * 5}\t100\t{value}\t100\t{value}\t{value}\t0\t0\t1\t1")
    rows.extend(f"{elapsed}\t100\t25\t100\t25\t25\t0\t0\t1\t1" for elapsed in range(600, 656, 5))
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
            rows.append(f"{index * 5}\t100\t{value}\t100\t{value}\t{value}\t0\t0\t1\t1")
        load_finished_seconds = (len(values) - 1) * 5
        rows.extend(
            f"{load_finished_seconds + offset}\t100\t{values[-1]}\t100\t{values[-1]}"
            f"\t{values[-1]}\t0\t0\t1\t1"
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


def test_wrapper_has_fresh_baselines_cleanup_and_no_quick_acceptance_claim() -> None:
    source = _source(WRAPPER)

    dataset_match = re.search(r"^DATASET_CONFIG='(.+)'$", source, re.MULTILINE)
    assert dataset_match is not None
    dataset = json.loads(dataset_match.group(1))
    assert dataset["contract"] == "p5_b4_runtime_dataset.v3"
    assert dataset["commercial"] == {"max_ai_credits_per_site_period": 10_000.0}
    assert dataset["formal"]["resource_idle_recovery_seconds"] == 60
    assert dataset["formal"]["resource_idle_minimum_sample_count"] == 12
    assert dataset["formal"]["resource_idle_minimum_span_seconds"] == 55
    assert dataset["formal"]["resource_process_scope"] == "pid1_service_tree_stable_snapshot_v1"

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
    assert "publish_output" in source
    assert "os.fsync(stream.fileno())" in source
    assert source.index("os.fsync(stream.fileno())") < source.index(
        "os.replace(temporary_name, target)"
    )
    assert "install -m 600" not in source
    assert "docker system prune" not in source
