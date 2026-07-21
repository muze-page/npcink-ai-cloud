"""Contract checks for the isolated P5-B4 hot-query proof tooling."""

from __future__ import annotations

import argparse
import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import p5_b4_hot_query_proof as proof

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.p5-b4-query-proof.yml"
SCRIPT = ROOT / "scripts" / "p5_b4_hot_query_proof.py"
GATE = ROOT / "scripts" / "check-p5-b4-hot-query-proof.sh"


def _args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "confirm_disposable": True,
        "mode": "formal",
        "run_rows": None,
        "provider_call_rows": None,
        "iterations": None,
        "warmup_iterations": None,
        "p95_threshold_ms": 50.0,
        "cloud_revision": "a" * 40,
        "compose_sha256": "b" * 64,
        "wrapper_sha256": "c" * 64,
        "worktree_dirty": "false",
        "worktree_status_sha256": "d" * 64,
        "worktree_dirty_entry_count": 0,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_percentile_is_sorted_interpolated_and_rejects_invalid_input() -> None:
    assert proof.percentile([40.0, 10.0, 30.0, 20.0], 0.50) == pytest.approx(25.0)
    assert proof.percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.95) == pytest.approx(4.8)
    with pytest.raises(ValueError):
        proof.percentile([], 0.95)
    with pytest.raises(ValueError):
        proof.percentile([1.0], 1.1)


def test_explain_parser_and_seq_scan_classification_are_redacted() -> None:
    document = proof.parse_explain_json(
        json.dumps(
            [
                {
                    "Plan": {
                        "Node Type": "Nested Loop",
                        "Plans": [
                            {
                                "Node Type": "Seq Scan",
                                "Relation Name": "provider_call_records",
                                "Filter": "must not be projected",
                            },
                            {
                                "Node Type": "Seq Scan",
                                "Relation Name": "run_records",
                            },
                        ],
                    },
                    "Execution Time": 1.25,
                }
            ]
        )
    )
    scans = proof.classify_seq_scans(
        document["Plan"],
        relation_row_counts={"provider_call_records": 20_000, "run_records": 100_000},
    )

    assert scans == [
        {
            "relation": "provider_call_records",
            "relation_row_count": 20_000,
            "large_table": False,
            "cardinality_known": True,
            "explained": True,
            "reason_code": "small_relation_below_large_table_threshold",
        },
        {
            "relation": "run_records",
            "relation_row_count": 100_000,
            "large_table": True,
            "cardinality_known": True,
            "explained": False,
            "reason_code": "unexplained_large_relation_seq_scan",
        },
    ]
    assert "Filter" not in json.dumps(scans)

    unknown = proof.classify_seq_scans(
        {"Node Type": "Seq Scan", "Relation Name": "unmapped_relation"},
        relation_row_counts={},
    )
    assert unknown == [
        {
            "relation": "unmapped_relation",
            "relation_row_count": None,
            "large_table": None,
            "cardinality_known": False,
            "explained": False,
            "reason_code": "relation_cardinality_unknown",
        }
    ]


def test_formal_defaults_and_quick_non_acceptance_limits_fail_closed() -> None:
    formal = proof.build_config(_args())
    assert formal.formal is True
    assert formal.run_rows == 100_000
    assert formal.provider_call_rows == 20_000
    assert formal.iterations == 30
    assert formal.p95_threshold_ms == 50.0

    quick = proof.build_config(_args(mode="quick"))
    assert quick.formal is False
    assert quick.run_rows == 2_000
    assert quick.provider_call_rows == 400
    assert quick.iterations == 3

    with pytest.raises(proof.ProofSafetyError, match="--confirm-disposable"):
        proof.build_config(_args(confirm_disposable=False))
    with pytest.raises(proof.ProofSafetyError, match="at least 100000"):
        proof.build_config(_args(run_rows=99_999))
    with pytest.raises(proof.ProofSafetyError, match="at least 30"):
        proof.build_config(_args(iterations=29))
    with pytest.raises(proof.ProofSafetyError, match="cannot exceed 50ms"):
        proof.build_config(_args(p95_threshold_ms=50.1))
    with pytest.raises(proof.ProofSafetyError, match="non-acceptance sized"):
        proof.build_config(_args(mode="quick", iterations=6))
    with pytest.raises(proof.ProofSafetyError, match="requires a clean"):
        proof.build_config(
            _args(
                worktree_dirty="true",
                worktree_dirty_entry_count=1,
            )
        )


def _query_results(
    *,
    threshold_failure: str | None = None,
    hit_failure: str | None = None,
    unknown_scan: str | None = None,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for query_id in proof.QUERY_MINIMUM_ACTUAL_ROWS:
        scans: list[dict[str, object]] = []
        if query_id == unknown_scan:
            scans.append(
                {
                    "relation": "unmapped_relation",
                    "explained": False,
                    "reason_code": "relation_cardinality_unknown",
                }
            )
        results.append(
            {
                "query_id": query_id,
                "p95_within_threshold": query_id != threshold_failure,
                "hit_cardinality": {
                    "representative_hits_passed": query_id != hit_failure,
                },
                "sequential_scans": scans,
            }
        )
    return results


def test_formal_gate_covers_all_six_queries_and_rejects_zero_hit_shortcuts() -> None:
    assert len(proof.QUERY_MINIMUM_ACTUAL_ROWS) == 6
    last_query = "image_source_provider_metrics"
    timing_failure = proof.evaluate_gate_results(
        _query_results(threshold_failure=last_query),
        missing_indexes=[],
        formal=True,
    )
    assert timing_failure["threshold_failures"] == [last_query]
    assert "canonical_query_p95_threshold_exceeded" in timing_failure[
        "failure_reason_codes"
    ]

    zero_hit = proof.evaluate_gate_results(
        _query_results(hit_failure=last_query),
        missing_indexes=[],
        formal=True,
    )
    assert zero_hit["hit_cardinality_failures"] == [last_query]
    assert "representative_query_hits_missing" in zero_hit["failure_reason_codes"]


def test_unknown_seq_scan_cardinality_fails_closed_even_in_quick_mode() -> None:
    query_id = "runtime_queue_claim_candidates"
    evaluation = proof.evaluate_gate_results(
        _query_results(unknown_scan=query_id),
        missing_indexes=[],
        formal=False,
    )
    assert evaluation["unknown_cardinality_scans"] == [
        {
            "query_id": query_id,
            "relation": "unmapped_relation",
            "reason_code": "relation_cardinality_unknown",
        }
    ]
    assert "seq_scan_relation_cardinality_unknown" in evaluation[
        "failure_reason_codes"
    ]


def test_cli_refuses_to_connect_without_explicit_confirmation() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "quick",
            "--cloud-revision",
            "b" * 40,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == (
        "P5-B4 hot-query proof failed closed before producing acceptance evidence\n"
    )
    assert "postgresql" not in completed.stderr.lower()


def test_compose_is_one_disposable_postgres_16_stack_without_host_ports() -> None:
    compose = COMPOSE.read_text()

    assert "image: postgres:16-alpine" in compose
    assert compose.count("image:") == 1
    assert "POSTGRES_DB: npcink_p5_b4_hot_query_proof" in compose
    assert "p5-b4-query-proof-postgres:/var/lib/postgresql/data" in compose
    assert "container_name:" not in compose
    assert "ports:" not in compose
    assert "env_file:" not in compose
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "P5_B4_CLOUD_REVISION" in compose
    assert "P5_B4_COMPOSE_SHA256" in compose
    assert "P5_B4_WRAPPER_SHA256" in compose
    assert "P5_B4_WORKTREE_DIRTY" in compose


def test_gate_requires_confirmation_marks_database_and_always_removes_volume() -> None:
    gate = GATE.read_text()

    assert GATE.stat().st_mode & stat.S_IXUSR
    assert gate.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert "--confirm-disposable is required" in gate
    assert gate.count("--confirm-disposable") >= 3
    assert "COMMENT ON DATABASE" in gate
    assert "npcink.p5_b4_hot_query_proof.disposable.v1" in gate
    assert "trap cleanup EXIT" in gate
    assert "handle_signal 130 signal_int" in gate
    assert "handle_signal 143 signal_term" in gate
    assert "down --volumes --remove-orphans --rmi local" in gate
    assert "status --porcelain=v1 --untracked-files=all" in gate
    assert "Refusing formal proof" in gate
    assert "P5_B4_WORKTREE_STATUS_SHA256" in gate
    assert "sha256_file" in gate
    assert "docker volume prune" not in gate
    assert "set -x" not in gate
    assert "compose.log" in gate
    assert "cat " not in gate
    assert "grep " not in gate
    assert "tail " not in gate
    cleanup_call = gate.index("if ! cleanup; then")
    publish_call = gate.rindex('publish_output "${OUTPUT_FILE}"')
    assert cleanup_call < publish_call
    assert "install -m 600" not in gate


def test_output_contract_freezes_synthetic_warm_sequential_limitations() -> None:
    source = SCRIPT.read_text()
    gate = GATE.read_text()

    for expected in (
        "deterministic_synthetic_metadata_only",
        "warm_cache_after_explicit_warmups",
        "one_postgresql_connection",
        "sequential_queries",
        "cold_cache_performance",
        "concurrent_contention",
        "production_data_distribution",
        "production_hardware_performance",
        "production_slo",
        "engineering_acceptance_threshold_not_production_slo",
    ):
        assert expected in source
        assert expected in gate


def test_source_reuses_canonical_queries_and_keeps_quick_plans_non_acceptance() -> None:
    source = SCRIPT.read_text()

    assert "from scripts import runtime_hot_path_explain" in source
    assert "runtime_hot_path_explain._build_queries" in source
    assert "runtime_hot_path_explain._fetch_available_indexes" in source
    assert "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)" in source
    assert '"p50"' in source
    assert '"p95"' in source
    assert '"p99"' in source
    assert "not_evaluated_non_acceptance_quick" in source
    assert "canonical_query_p95_threshold_exceeded" in source
    assert "relation_cardinality_unknown" in source
    assert "representative_query_hits_missing" in source
    assert "QUERY_MINIMUM_ACTUAL_ROWS" in source
    assert "_predicate_target_counts" not in source
    assert "predicate_target_rows" not in source
    assert "migration_file_count" in source
    assert "worktree_contract" in source
    assert "metadata_only_null_payload_columns" in source
    assert '"direct_wordpress_write": False' in source
    assert '"contains_credentials": False' in source
    assert '"contains_prompt_or_result_payloads": False' in source
    assert "UPDATE run_records" not in source
    assert "DELETE FROM run_records" not in source
