#!/usr/bin/env python3
"""Disposable PostgreSQL 16 high-cardinality proof for runtime hot queries.

The proof imports the canonical query definitions and expected-index truth from
``scripts.runtime_hot_path_explain``. It never calls the application runtime,
providers, or WordPress, and its fixtures keep payload columns empty.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import runtime_hot_path_explain

CONTRACT_VERSION = "p5_b4_hot_query_proof.v1"
EXPECTED_DATABASE_NAME = "npcink_p5_b4_hot_query_proof"
EXPECTED_DATABASE_MARKER = "npcink.p5_b4_hot_query_proof.disposable.v1"
FOCUS_SITE_ID = "site_p5_b4_query_focus"
FIXTURE_CLOCK = datetime(2026, 7, 18, 0, 0, tzinfo=UTC)

FORMAL_RUN_ROWS = 100_000
FORMAL_PROVIDER_CALL_ROWS = 20_000
FORMAL_ITERATIONS = 30
FORMAL_WARMUP_ITERATIONS = 3
QUICK_RUN_ROWS = 2_000
QUICK_PROVIDER_CALL_ROWS = 400
QUICK_ITERATIONS = 3
QUICK_WARMUP_ITERATIONS = 1
QUERY_LIMIT = 50
P95_THRESHOLD_MS = 50.0
LARGE_TABLE_ROW_THRESHOLD = 50_000

REVISION_RE = re.compile(r"^[0-9a-f]{7,64}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

QUERY_MINIMUM_ACTUAL_ROWS: dict[str, int] = {
    "runtime_queue_claim_candidates": 50,
    "runtime_running_stale_diagnostics": 50,
    "runtime_callback_due_diagnostics": 50,
    "runtime_callback_dispatching_recovery": 50,
    "runtime_recent_nightly_runs": 5,
    "image_source_provider_metrics": 2,
}


class ProofSafetyError(RuntimeError):
    """Raised before fixture insertion when the disposable boundary is not proven."""


@dataclass(frozen=True)
class ProofConfig:
    mode: str
    run_rows: int
    provider_call_rows: int
    iterations: int
    warmup_iterations: int
    p95_threshold_ms: float
    cloud_revision: str
    compose_sha256: str
    wrapper_sha256: str
    worktree_dirty: bool
    worktree_status_sha256: str
    worktree_dirty_entry_count: int

    @property
    def formal(self) -> bool:
        return self.mode == "formal"


def percentile(values: Sequence[float], quantile: float) -> float:
    """Return a deterministic linearly interpolated percentile."""

    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("quantile must be between zero and one")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


def parse_explain_json(value: object) -> dict[str, Any]:
    """Normalize psycopg or textual ``EXPLAIN ... FORMAT JSON`` output."""

    parsed: object = value
    if isinstance(parsed, str):
        parsed = json.loads(parsed)
    if isinstance(parsed, list):
        if len(parsed) != 1 or not isinstance(parsed[0], dict):
            raise ValueError("EXPLAIN JSON must contain one document")
        parsed = parsed[0]
    if not isinstance(parsed, dict) or not isinstance(parsed.get("Plan"), dict):
        raise ValueError("EXPLAIN JSON document is missing Plan")
    return parsed


def iter_plan_nodes(plan: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    yield plan
    children = plan.get("Plans", [])
    if not isinstance(children, list):
        return
    for child in children:
        if isinstance(child, dict):
            yield from iter_plan_nodes(child)


def classify_seq_scans(
    plan: Mapping[str, Any],
    *,
    relation_row_counts: Mapping[str, int],
    large_table_row_threshold: int = LARGE_TABLE_ROW_THRESHOLD,
) -> list[dict[str, object]]:
    """Explain every sequential scan without exposing predicates or SQL."""

    scans: list[dict[str, object]] = []
    for node in iter_plan_nodes(plan):
        if node.get("Node Type") != "Seq Scan":
            continue
        relation = str(node.get("Relation Name") or "unknown")
        cardinality_known = relation in relation_row_counts
        row_count = int(relation_row_counts[relation]) if cardinality_known else None
        large_table = (
            row_count >= large_table_row_threshold if row_count is not None else None
        )
        explained = bool(cardinality_known and large_table is False)
        if not cardinality_known:
            reason_code = "relation_cardinality_unknown"
        elif large_table:
            reason_code = "unexplained_large_relation_seq_scan"
        else:
            reason_code = "small_relation_below_large_table_threshold"
        scans.append(
            {
                "relation": relation,
                "relation_row_count": row_count,
                "large_table": large_table,
                "cardinality_known": cardinality_known,
                "explained": explained,
                "reason_code": reason_code,
            }
        )
    return scans


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the disposable P5-B4 PostgreSQL hot-query proof.",
    )
    parser.add_argument("--confirm-disposable", action="store_true")
    parser.add_argument("--mode", choices=("formal", "quick"), default="formal")
    parser.add_argument("--run-rows", type=int, default=None)
    parser.add_argument("--provider-call-rows", type=int, default=None)
    parser.add_argument("--iterations", type=int, default=None)
    parser.add_argument("--warmup-iterations", type=int, default=None)
    parser.add_argument("--p95-threshold-ms", type=float, default=P95_THRESHOLD_MS)
    parser.add_argument(
        "--cloud-revision",
        default=os.getenv("P5_B4_CLOUD_REVISION", "").strip(),
    )
    parser.add_argument(
        "--compose-sha256",
        default=os.getenv("P5_B4_COMPOSE_SHA256", "").strip(),
    )
    parser.add_argument(
        "--wrapper-sha256",
        default=os.getenv("P5_B4_WRAPPER_SHA256", "").strip(),
    )
    parser.add_argument(
        "--worktree-dirty",
        choices=("true", "false"),
        default=os.getenv("P5_B4_WORKTREE_DIRTY", "").strip(),
    )
    parser.add_argument(
        "--worktree-status-sha256",
        default=os.getenv("P5_B4_WORKTREE_STATUS_SHA256", "").strip(),
    )
    parser.add_argument(
        "--worktree-dirty-entry-count",
        type=int,
        default=(os.getenv("P5_B4_WORKTREE_DIRTY_ENTRY_COUNT", "").strip() or None),
    )
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> ProofConfig:
    if not bool(args.confirm_disposable):
        raise ProofSafetyError("--confirm-disposable is required")
    mode = str(args.mode)
    formal = mode == "formal"
    run_rows = int(
        args.run_rows
        if args.run_rows is not None
        else (FORMAL_RUN_ROWS if formal else QUICK_RUN_ROWS)
    )
    provider_call_rows = int(
        args.provider_call_rows
        if args.provider_call_rows is not None
        else (FORMAL_PROVIDER_CALL_ROWS if formal else QUICK_PROVIDER_CALL_ROWS)
    )
    iterations = int(
        args.iterations
        if args.iterations is not None
        else (FORMAL_ITERATIONS if formal else QUICK_ITERATIONS)
    )
    warmup_iterations = int(
        args.warmup_iterations
        if args.warmup_iterations is not None
        else (FORMAL_WARMUP_ITERATIONS if formal else QUICK_WARMUP_ITERATIONS)
    )
    threshold = float(args.p95_threshold_ms)
    revision = str(args.cloud_revision or "").strip().lower()
    compose_sha256 = str(args.compose_sha256 or "").strip().lower()
    wrapper_sha256 = str(args.wrapper_sha256 or "").strip().lower()
    worktree_dirty_value = str(args.worktree_dirty or "").strip().lower()
    worktree_status_sha256 = str(args.worktree_status_sha256 or "").strip().lower()
    if args.worktree_dirty_entry_count is None:
        raise ProofSafetyError("worktree dirty entry count is required")
    worktree_dirty_entry_count = int(args.worktree_dirty_entry_count)

    if not REVISION_RE.fullmatch(revision):
        raise ProofSafetyError("cloud revision must be a hexadecimal Git revision")
    if not SHA256_RE.fullmatch(compose_sha256) or not SHA256_RE.fullmatch(wrapper_sha256):
        raise ProofSafetyError("compose and wrapper SHA-256 inputs are required")
    if not SHA256_RE.fullmatch(worktree_status_sha256):
        raise ProofSafetyError("worktree status SHA-256 input is required")
    if worktree_dirty_value not in {"true", "false"}:
        raise ProofSafetyError("worktree dirty posture must be explicit")
    worktree_dirty = worktree_dirty_value == "true"
    if worktree_dirty_entry_count < 0:
        raise ProofSafetyError("worktree dirty entry count cannot be negative")
    if worktree_dirty != (worktree_dirty_entry_count > 0):
        raise ProofSafetyError("worktree dirty posture and entry count disagree")
    if provider_call_rows > run_rows:
        raise ProofSafetyError("provider-call rows cannot exceed run rows")
    if iterations < 1 or warmup_iterations < 1 or threshold <= 0:
        raise ProofSafetyError("iterations, warmups, and threshold must be positive")
    if formal:
        if worktree_dirty:
            raise ProofSafetyError("formal mode requires a clean tracked and untracked worktree")
        if run_rows < FORMAL_RUN_ROWS:
            raise ProofSafetyError("formal mode requires at least 100000 run rows")
        if provider_call_rows < FORMAL_PROVIDER_CALL_ROWS:
            raise ProofSafetyError("formal mode requires at least 20000 provider-call rows")
        if iterations < FORMAL_ITERATIONS:
            raise ProofSafetyError("formal mode requires at least 30 measured iterations")
        if threshold > P95_THRESHOLD_MS:
            raise ProofSafetyError("formal p95 threshold cannot exceed 50ms")
    else:
        if run_rows < 100 or run_rows > 10_000:
            raise ProofSafetyError("quick mode run rows must remain between 100 and 10000")
        if provider_call_rows < 1 or provider_call_rows > 2_000:
            raise ProofSafetyError("quick mode provider-call rows must remain between 1 and 2000")
        if iterations > 5 or warmup_iterations > 2:
            raise ProofSafetyError("quick mode iterations must remain non-acceptance sized")

    return ProofConfig(
        mode=mode,
        run_rows=run_rows,
        provider_call_rows=provider_call_rows,
        iterations=iterations,
        warmup_iterations=warmup_iterations,
        p95_threshold_ms=threshold,
        cloud_revision=revision,
        compose_sha256=compose_sha256,
        wrapper_sha256=wrapper_sha256,
        worktree_dirty=worktree_dirty,
        worktree_status_sha256=worktree_status_sha256,
        worktree_dirty_entry_count=worktree_dirty_entry_count,
    )


def _database_url() -> str:
    database_url = os.getenv("NPCINK_CLOUD_DATABASE_URL", "").strip()
    if not database_url:
        raise ProofSafetyError("NPCINK_CLOUD_DATABASE_URL is required")
    return database_url


def verify_disposable_database(connection: Connection) -> dict[str, object]:
    if connection.dialect.name != "postgresql":
        raise ProofSafetyError("proof requires PostgreSQL")
    identity = connection.execute(
        text(
            """
            SELECT
                current_database(),
                current_setting('server_version'),
                current_setting('server_version_num')::integer,
                shobj_description(oid, 'pg_database')
            FROM pg_database
            WHERE datname = current_database()
            """
        )
    ).one()
    database_name = str(identity[0])
    postgres_version = str(identity[1])
    server_version_num = int(identity[2])
    database_marker = str(identity[3] or "")
    if database_name != EXPECTED_DATABASE_NAME:
        raise ProofSafetyError("database name does not match the disposable proof identity")
    if database_marker != EXPECTED_DATABASE_MARKER:
        raise ProofSafetyError("database marker does not match the disposable proof identity")
    if server_version_num // 10_000 != 16:
        raise ProofSafetyError("proof requires PostgreSQL major version 16")

    preexisting = {
        "run_records": int(
            connection.execute(text("SELECT count(*) FROM run_records")).scalar_one()
        ),
        "provider_call_records": int(
            connection.execute(text("SELECT count(*) FROM provider_call_records")).scalar_one()
        ),
        "proof_sites": int(
            connection.execute(
                text("SELECT count(*) FROM sites WHERE site_id LIKE 'site_p5_b4_query_%'")
            ).scalar_one()
        ),
    }
    if any(preexisting.values()):
        raise ProofSafetyError("disposable proof tables must be empty before fixture insertion")
    return {
        "database_name": database_name,
        "database_marker_verified": True,
        "postgresql_version": postgres_version,
        "postgresql_major": 16,
        "preinsert_runtime_rows": preexisting,
    }


def _seed_fixtures(connection: Connection, config: ProofConfig) -> None:
    connection.execute(
        text(
            """
            INSERT INTO sites (
                site_id, name, status, site_url, platform_kind, metadata_json,
                provisioned_at, activated_at, created_at, updated_at
            )
            SELECT
                CASE WHEN fixture_id = 1
                    THEN :focus_site_id
                    ELSE 'site_p5_b4_query_' || lpad(fixture_id::text, 3, '0')
                END,
                'P5 B4 metadata-only proof site',
                'active',
                '',
                'wordpress',
                NULL,
                :fixture_clock,
                :fixture_clock,
                :fixture_clock,
                :fixture_clock
            FROM generate_series(1, 64) AS fixture_id
            """
        ),
        {"focus_site_id": FOCUS_SITE_ID, "fixture_clock": FIXTURE_CLOCK},
    )
    connection.execute(
        text(
            """
            WITH fixture AS (
                SELECT
                    fixture_id,
                    fixture_id % 10 AS bucket,
                    :fixture_clock - ((fixture_id % 86400) * interval '1 second') AS started_at
                FROM generate_series(1, :run_rows) AS fixture_id
            )
            INSERT INTO run_records (
                run_id, site_id, ability_name, ability_family, channel,
                execution_kind, execution_tier, execution_pattern,
                data_classification, profile_id, status, idempotency_key,
                request_fingerprint, trace_id, input_json,
                execution_input_ciphertext, policy_json, result_json,
                callback_status, callback_attempt_count,
                callback_last_attempt_at, callback_next_attempt_at,
                fallback_used, started_at, processing_started_at, finished_at
            )
            SELECT
                'run_p5b4_' || lpad(fixture_id::text, 9, '0'),
                CASE WHEN ((fixture_id - 1) % 64) = 0
                    THEN :focus_site_id
                    ELSE 'site_p5_b4_query_' || lpad((((fixture_id - 1) % 64) + 1)::text, 3, '0')
                END,
                CASE
                    WHEN bucket = 8 THEN 'npcink-cloud/search-image-source'
                    WHEN bucket = 9 THEN 'npcink-toolbox/search-image-source'
                    WHEN bucket = 0 THEN 'npcink-cloud/analyze-nightly-content-batch'
                    ELSE 'npcink-cloud/metadata-only-query-proof'
                END,
                CASE WHEN bucket IN (8, 9) THEN 'knowledge' ELSE 'text' END,
                'proof',
                CASE WHEN (fixture_id % 5) = 0
                    THEN 'nightly_site_inspection'
                    ELSE 'inline'
                END,
                'cloud',
                'whole_run_offload',
                'internal',
                'p5-b4-query-proof.managed',
                CASE
                    WHEN bucket IN (0, 1) THEN 'queued'
                    WHEN bucket IN (2, 3) THEN 'running'
                    ELSE 'succeeded'
                END,
                NULL,
                NULL,
                'trace_p5b4_' || lpad(fixture_id::text, 9, '0'),
                NULL,
                NULL,
                NULL,
                NULL,
                CASE
                    WHEN bucket IN (4, 5) THEN 'pending'
                    WHEN bucket IN (6, 7) THEN 'dispatching'
                    ELSE 'not_requested'
                END,
                CASE WHEN bucket IN (4, 5, 6, 7) THEN 1 ELSE 0 END,
                CASE
                    WHEN bucket = 6 THEN :fixture_clock - interval '20 minutes'
                    WHEN bucket = 7 THEN :fixture_clock - interval '1 minute'
                    ELSE NULL
                END,
                CASE
                    WHEN bucket = 4 THEN :fixture_clock - interval '10 minutes'
                    WHEN bucket = 5 THEN :fixture_clock + interval '10 minutes'
                    ELSE NULL
                END,
                false,
                started_at,
                CASE
                    WHEN bucket = 2 THEN :fixture_clock - interval '30 minutes'
                    WHEN bucket = 3 THEN :fixture_clock - interval '2 minutes'
                    ELSE NULL
                END,
                CASE WHEN bucket >= 4 THEN started_at + interval '30 seconds' ELSE NULL END
            FROM fixture
            """
        ),
        {
            "focus_site_id": FOCUS_SITE_ID,
            "fixture_clock": FIXTURE_CLOCK,
            "run_rows": config.run_rows,
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO provider_call_records (
                run_id, provider_id, model_id, instance_id, region,
                latency_ms, tokens_in, tokens_out, cost, retry_count,
                fallback_used, error_code, created_at
            )
            SELECT
                'run_p5b4_' || lpad(fixture_id::text, 9, '0'),
                CASE WHEN fixture_id % 2 = 0 THEN 'proof-provider-a' ELSE 'proof-provider-b' END,
                'proof-model',
                'proof-instance',
                'proof-region',
                10 + (fixture_id % 40),
                0,
                0,
                0,
                0,
                false,
                NULL,
                :fixture_clock - ((fixture_id % 3600) * interval '1 second')
            FROM generate_series(1, :provider_call_rows) AS fixture_id
            """
        ),
        {
            "fixture_clock": FIXTURE_CLOCK,
            "provider_call_rows": config.provider_call_rows,
        },
    )
    connection.execute(text("ANALYZE run_records"))
    connection.execute(text("ANALYZE provider_call_records"))


def _fixture_counts(connection: Connection) -> dict[str, object]:
    params = {"fixture_clock": FIXTURE_CLOCK}
    row = connection.execute(
        text(
            """
            SELECT
                count(*) AS run_rows,
                count(*) FILTER (WHERE status = 'queued') AS queued_rows,
                count(*) FILTER (
                    WHERE status = 'running'
                      AND processing_started_at <= :fixture_clock - interval '15 minutes'
                ) AS stale_running_rows,
                count(*) FILTER (
                    WHERE callback_status = 'pending'
                      AND callback_next_attempt_at <= :fixture_clock
                ) AS callback_pending_due_rows,
                count(*) FILTER (
                    WHERE callback_status = 'dispatching'
                      AND callback_last_attempt_at <= :fixture_clock - interval '5 minutes'
                ) AS stale_dispatching_rows
            FROM run_records
            """
        ),
        params,
    ).one()
    counts: dict[str, object] = {
        "run_records": int(row[0]),
        "provider_call_records": int(
            connection.execute(text("SELECT count(*) FROM provider_call_records")).scalar_one()
        ),
        "distribution": {
            "queued": int(row[1]),
            "stale_running": int(row[2]),
            "callback_pending_due": int(row[3]),
            "stale_dispatching": int(row[4]),
        },
    }
    distribution = counts["distribution"]
    if not isinstance(distribution, dict) or any(int(value) < 1 for value in distribution.values()):
        raise ProofSafetyError("fixture distribution is not representative")
    return counts


def _run_explain_json(
    connection: Connection,
    query: runtime_hot_path_explain.HotPathQuery,
) -> dict[str, Any]:
    normalized_sql = " ".join(query.sql.split())
    row = connection.execute(
        text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + normalized_sql),
        query.params,
    ).one()
    return parse_explain_json(row[0])


def _index_names(plan: Mapping[str, Any]) -> set[str]:
    return {
        str(node["Index Name"])
        for node in iter_plan_nodes(plan)
        if isinstance(node.get("Index Name"), str)
    }


def _plan_posture(plan: Mapping[str, Any]) -> dict[str, object]:
    node_types = sorted(
        {
            str(node.get("Node Type"))
            for node in iter_plan_nodes(plan)
            if node.get("Node Type")
        }
    )
    return {
        "root_node_type": str(plan.get("Node Type") or "unknown"),
        "node_types": node_types,
        "index_names": sorted(_index_names(plan)),
    }


def evaluate_gate_results(
    query_results: Sequence[Mapping[str, Any]],
    *,
    missing_indexes: Sequence[str],
    formal: bool,
) -> dict[str, object]:
    """Evaluate structural gates and formal-only timing/large-plan gates."""

    canonical_ids = set(QUERY_MINIMUM_ACTUAL_ROWS)
    observed_ids = {str(result.get("query_id") or "") for result in query_results}
    missing_query_ids = sorted(canonical_ids - observed_ids)
    threshold_failures = sorted(
        str(result["query_id"])
        for result in query_results
        if result.get("p95_within_threshold") is False
    )
    hit_cardinality_failures = sorted(
        str(result["query_id"])
        for result in query_results
        if not bool(
            result.get("hit_cardinality", {}).get("representative_hits_passed")
            if isinstance(result.get("hit_cardinality"), dict)
            else False
        )
    )
    unexplained_scans = [
        {
            "query_id": str(result["query_id"]),
            "relation": str(scan["relation"]),
            "reason_code": str(scan["reason_code"]),
        }
        for result in query_results
        for scan in result.get("sequential_scans", [])
        if isinstance(scan, dict) and scan.get("explained") is False
    ]
    unknown_cardinality_scans = [
        scan
        for scan in unexplained_scans
        if scan["reason_code"] == "relation_cardinality_unknown"
    ]

    structural_failures: list[str] = []
    if missing_query_ids:
        structural_failures.append("canonical_query_measurement_missing")
    if missing_indexes:
        structural_failures.append("expected_indexes_missing")
    if hit_cardinality_failures:
        structural_failures.append("representative_query_hits_missing")
    if unknown_cardinality_scans:
        structural_failures.append("seq_scan_relation_cardinality_unknown")

    applied_failures = list(structural_failures)
    if formal and threshold_failures:
        applied_failures.append("canonical_query_p95_threshold_exceeded")
    if formal and unexplained_scans:
        applied_failures.append("unexplained_seq_scan")
    return {
        "missing_query_ids": missing_query_ids,
        "threshold_failures": threshold_failures,
        "hit_cardinality_failures": hit_cardinality_failures,
        "unexplained_scans": unexplained_scans,
        "unknown_cardinality_scans": unknown_cardinality_scans,
        "failure_reason_codes": applied_failures,
    }


def _measure_query(
    connection: Connection,
    *,
    query: runtime_hot_path_explain.HotPathQuery,
    config: ProofConfig,
    relation_row_counts: Mapping[str, int],
    available_indexes: set[str],
) -> dict[str, object]:
    for _iteration in range(config.warmup_iterations):
        _run_explain_json(connection, query)

    timings: list[float] = []
    actual_rows_samples: list[int] = []
    observed_index_names: set[str] = set()
    observed_seq_scans: dict[tuple[str, str], dict[str, object]] = {}
    last_plan: Mapping[str, Any] = {}
    for _iteration in range(config.iterations):
        document = _run_explain_json(connection, query)
        execution_time = document.get("Execution Time")
        plan = document["Plan"]
        if not isinstance(execution_time, (int, float)) or not isinstance(plan, dict):
            raise ValueError("EXPLAIN JSON is missing execution timing or plan")
        timings.append(float(execution_time))
        actual_rows = plan.get("Actual Rows")
        if not isinstance(actual_rows, (int, float)):
            raise ValueError("EXPLAIN JSON is missing root Actual Rows")
        actual_rows_samples.append(int(actual_rows))
        observed_index_names.update(_index_names(plan))
        for scan in classify_seq_scans(plan, relation_row_counts=relation_row_counts):
            key = (str(scan["relation"]), str(scan["reason_code"]))
            observed_seq_scans[key] = scan
        last_plan = plan

    expected_indexes = list(query.expected_indexes)
    missing_indexes = [name for name in expected_indexes if name not in available_indexes]
    p50 = percentile(timings, 0.50)
    p95 = percentile(timings, 0.95)
    p99 = percentile(timings, 0.99)
    minimum_actual_rows_required = QUERY_MINIMUM_ACTUAL_ROWS[query.query_id]
    minimum_actual_rows_observed = min(actual_rows_samples)
    representative_hits_passed = minimum_actual_rows_observed >= minimum_actual_rows_required
    return {
        "query_id": query.query_id,
        "purpose": query.purpose,
        "measured_iterations": config.iterations,
        "warmup_iterations": config.warmup_iterations,
        "timing_ms": {
            "p50": round(p50, 6),
            "p95": round(p95, 6),
            "p99": round(p99, 6),
            "minimum": round(min(timings), 6),
            "maximum": round(max(timings), 6),
        },
        "p95_threshold_ms": config.p95_threshold_ms,
        "p95_within_threshold": p95 <= config.p95_threshold_ms,
        "hit_cardinality": {
            "minimum_actual_rows_observed": minimum_actual_rows_observed,
            "minimum_actual_rows_required": minimum_actual_rows_required,
            "representative_hits_passed": representative_hits_passed,
        },
        "expected_indexes": expected_indexes,
        "expected_indexes_available": [
            name for name in expected_indexes if name in available_indexes
        ],
        "expected_indexes_missing": missing_indexes,
        "expected_indexes_observed_in_plan": [
            name for name in expected_indexes if name in observed_index_names
        ],
        "plan_posture": _plan_posture(last_plan),
        "sequential_scans": sorted(
            observed_seq_scans.values(),
            key=lambda item: (str(item["relation"]), str(item["reason_code"])),
        ),
    }


def _sha256_file(source: Path) -> str:
    return hashlib.sha256(source.read_bytes()).hexdigest()


def _migration_hashes(alembic_revision: str) -> dict[str, object]:
    repository_root = Path(__file__).resolve().parents[1]
    migration_root = repository_root / "migrations" / "versions"
    migration_files = sorted(migration_root.glob("*.py"), key=lambda item: item.name)
    if not migration_files:
        raise ProofSafetyError("migration source files are unavailable")
    manifest = hashlib.sha256()
    head_files: list[Path] = []
    revision_pattern = re.compile(r"(?m)^revision\s*=\s*['\"]([^'\"]+)['\"]")
    for migration_file in migration_files:
        relative_name = migration_file.relative_to(repository_root).as_posix()
        source_bytes = migration_file.read_bytes()
        manifest.update(relative_name.encode("utf-8"))
        manifest.update(b"\0")
        manifest.update(hashlib.sha256(source_bytes).digest())
        manifest.update(b"\0")
        match = revision_pattern.search(source_bytes.decode("utf-8"))
        if match and match.group(1) == alembic_revision:
            head_files.append(migration_file)
    if len(head_files) != 1:
        raise ProofSafetyError("Alembic head must map to exactly one migration source file")
    head_file = head_files[0]
    return {
        "alembic_head": alembic_revision,
        "head_file": head_file.relative_to(repository_root).as_posix(),
        "head_file_sha256": _sha256_file(head_file),
        "manifest_sha256": manifest.hexdigest(),
        "migration_file_count": len(migration_files),
    }


def _revision_inputs(config: ProofConfig, alembic_revision: str) -> dict[str, object]:
    repository_root = Path(__file__).resolve().parents[1]
    harness_file = Path(__file__).resolve()
    wrapper_file = repository_root / "scripts" / "check-p5-b4-hot-query-proof.sh"
    canonical_query_file = Path(runtime_hot_path_explain.__file__).resolve()
    wrapper_sha256 = _sha256_file(wrapper_file)
    if wrapper_sha256 != config.wrapper_sha256:
        raise ProofSafetyError("wrapper source hash differs between host preflight and proof image")
    return {
        "cloud_git_revision": config.cloud_revision,
        "worktree_contract": {
            "source": "git_status_porcelain_v1_including_untracked",
            "dirty": config.worktree_dirty,
            "dirty_entry_count": config.worktree_dirty_entry_count,
            "status_sha256": config.worktree_status_sha256,
            "formal_clean_required": True,
        },
        "source_files": {
            "proof_harness": {
                "path": "scripts/p5_b4_hot_query_proof.py",
                "sha256": _sha256_file(harness_file),
            },
            "compose": {
                "path": "docker-compose.p5-b4-query-proof.yml",
                "sha256": config.compose_sha256,
            },
            "wrapper": {
                "path": "scripts/check-p5-b4-hot-query-proof.sh",
                "sha256": wrapper_sha256,
            },
            "canonical_query_source": {
                "path": "scripts/runtime_hot_path_explain.py",
                "sha256": _sha256_file(canonical_query_file),
            },
        },
        "migrations": _migration_hashes(alembic_revision),
    }


def _alembic_revision(connection: Connection) -> str:
    rows = connection.execute(
        text("SELECT version_num FROM alembic_version ORDER BY version_num")
    ).all()
    values = [str(row[0]) for row in rows]
    if len(values) != 1:
        raise ProofSafetyError("proof database must have exactly one Alembic head")
    return values[0]


def run_proof(connection: Connection, config: ProofConfig) -> dict[str, object]:
    identity = verify_disposable_database(connection)
    alembic_revision = _alembic_revision(connection)
    _seed_fixtures(connection, config)
    connection.commit()
    fixture_counts = _fixture_counts(connection)

    queries = runtime_hot_path_explain._build_queries(
        now=FIXTURE_CLOCK,
        site_id=FOCUS_SITE_ID,
        limit=QUERY_LIMIT,
    )
    available_indexes = runtime_hot_path_explain._fetch_available_indexes(
        connection,
        connection.dialect.name,
    )
    relation_row_counts = {
        "run_records": int(fixture_counts["run_records"]),
        "provider_call_records": int(fixture_counts["provider_call_records"]),
        "sites": 64,
    }
    canonical_query_ids = [query.query_id for query in queries]
    if set(canonical_query_ids) != set(QUERY_MINIMUM_ACTUAL_ROWS):
        raise ProofSafetyError("canonical query set differs from frozen hit thresholds")
    query_results = [
        _measure_query(
            connection,
            query=query,
            config=config,
            relation_row_counts=relation_row_counts,
            available_indexes=available_indexes,
        )
        for query in queries
    ]

    required_results = [result for result in query_results if result["expected_indexes"]]
    missing_indexes = sorted(
        {
            str(index_name)
            for result in required_results
            for index_name in result["expected_indexes_missing"]  # type: ignore[union-attr]
        }
    )
    gate_evaluation = evaluate_gate_results(
        query_results,
        missing_indexes=missing_indexes,
        formal=config.formal,
    )
    threshold_failures = gate_evaluation["threshold_failures"]
    applied_failures = gate_evaluation["failure_reason_codes"]
    if not isinstance(threshold_failures, list) or not isinstance(applied_failures, list):
        raise ValueError("gate evaluation returned an invalid shape")
    acceptance_status = (
        ("passed" if not applied_failures else "failed")
        if config.formal
        else (
            "non_acceptance_quick_completed"
            if not applied_failures
            else "non_acceptance_quick_structural_failure"
        )
    )

    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "mode": config.mode,
        "acceptance": {
            "eligible": config.formal,
            "status": acceptance_status,
            "formal_defaults": {
                "run_rows": FORMAL_RUN_ROWS,
                "provider_call_rows": FORMAL_PROVIDER_CALL_ROWS,
                "measured_iterations": FORMAL_ITERATIONS,
                "p95_threshold_ms": P95_THRESHOLD_MS,
            },
            "failure_reason_codes": applied_failures,
            "quick_mode_disclaimer": (
                None
                if config.formal
                else "quick mode is executable smoke evidence, never P5-B4 acceptance evidence"
            ),
        },
        "revision_inputs": _revision_inputs(config, alembic_revision),
        "database_identity": identity,
        "fixture": {
            "clock": FIXTURE_CLOCK.isoformat().replace("+00:00", "Z"),
            "row_counts": fixture_counts,
            "payload_posture": "metadata_only_null_payload_columns",
            "deterministic": True,
        },
        "scope_and_limitations": {
            "fixture_scope": "deterministic_synthetic_metadata_only",
            "cache_posture": "warm_cache_after_explicit_warmups",
            "connection_posture": "one_postgresql_connection",
            "query_execution_posture": "sequential_queries",
            "p95_posture": "engineering_acceptance_threshold_not_production_slo",
            "does_not_prove": [
                "cold_cache_performance",
                "concurrent_contention",
                "production_data_distribution",
                "production_hardware_performance",
                "production_slo",
            ],
        },
        "measurement": {
            "query_limit": QUERY_LIMIT,
            "measured_iterations_per_query": config.iterations,
            "warmup_iterations_per_query": config.warmup_iterations,
            "queries_from_canonical_source": canonical_query_ids,
            "required_index_query_ids": [
                query.query_id for query in queries if query.expected_indexes
            ],
            "queries": query_results,
        },
        "gate_posture": {
            "formal_gate_applied": config.formal,
            "threshold_status": (
                ("passed" if not threshold_failures else "failed")
                if config.formal
                else "not_evaluated_non_acceptance_quick"
            ),
            "expected_indexes_status": "passed" if not missing_indexes else "failed",
            "expected_indexes_missing": missing_indexes,
            "canonical_query_threshold_failures": (
                threshold_failures if config.formal else []
            ),
            "hit_cardinality_status": (
                "passed"
                if not gate_evaluation["hit_cardinality_failures"]
                else "failed"
            ),
            "hit_cardinality_failures": gate_evaluation["hit_cardinality_failures"],
            "large_table_row_threshold": LARGE_TABLE_ROW_THRESHOLD,
            "unexplained_seq_scans": (
                gate_evaluation["unexplained_scans"] if config.formal else []
            ),
            "unknown_cardinality_seq_scans": gate_evaluation[
                "unknown_cardinality_scans"
            ],
            "quick_plan_posture": (
                None
                if config.formal
                else (
                    "observed_only; small-cardinality plan and timing do not pass "
                    "or fail formal gates"
                )
            ),
        },
        "boundary": {
            "cloud_role": "runtime_performance_evidence",
            "direct_wordpress_write": False,
            "contains_credentials": False,
            "contains_prompt_or_result_payloads": False,
            "provider_execution_performed": False,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        config = build_config(args)
        engine = create_engine(_database_url(), pool_pre_ping=True)
        with engine.connect() as connection:
            report = run_proof(connection, config)
        print(json.dumps(report, indent=2, sort_keys=True))
        failure_codes = report["acceptance"]["failure_reason_codes"]  # type: ignore[index]
        return 1 if failure_codes else 0
    except (ProofSafetyError, ValueError):
        print(
            "P5-B4 hot-query proof failed closed before producing acceptance evidence",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
