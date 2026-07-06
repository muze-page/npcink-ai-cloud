from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from app.core.config import Settings
from app.domain.cloud_batch_runtime.contracts import CLOUD_BATCH_RUNTIME_EXECUTION_KIND
from app.domain.image_sources.contracts import IMAGE_SOURCE_ABILITIES


@dataclass(frozen=True)
class HotPathQuery:
    query_id: str
    purpose: str
    sql: str
    params: dict[str, object]
    expected_indexes: tuple[str, ...] = ()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _image_source_ability_params() -> tuple[str, dict[str, object]]:
    names = sorted(IMAGE_SOURCE_ABILITIES)
    placeholders = ", ".join(f":image_source_ability_{index}" for index, _name in enumerate(names))
    params = {
        f"image_source_ability_{index}": name
        for index, name in enumerate(names)
    }
    return placeholders, params


def _build_queries(*, now: datetime, site_id: str, limit: int) -> list[HotPathQuery]:
    image_ability_placeholders, image_ability_params = _image_source_ability_params()
    image_metrics_params: dict[str, object] = {
        "metrics_start_at": now - timedelta(hours=24),
        "metrics_end_at": now,
        **image_ability_params,
    }
    return [
        HotPathQuery(
            query_id="runtime_queue_claim_candidates",
            purpose="worker selects the oldest queued runs before claim/update",
            sql="""
                SELECT run_id
                FROM run_records
                WHERE status = 'queued'
                ORDER BY started_at ASC, run_id ASC
                LIMIT :limit
            """,
            params={"limit": limit},
            expected_indexes=("ix_run_records_status_started_run",),
        ),
        HotPathQuery(
            query_id="runtime_running_stale_diagnostics",
            purpose="runtime diagnostics and repair scan stale running runs",
            sql="""
                SELECT run_id
                FROM run_records
                WHERE status = 'running'
                  AND processing_started_at IS NOT NULL
                  AND processing_started_at <= :running_stale_before
                ORDER BY processing_started_at ASC, started_at ASC
                LIMIT :limit
            """,
            params={
                "running_stale_before": now - timedelta(minutes=15),
                "limit": limit,
            },
            expected_indexes=("ix_run_records_status_processing_started",),
        ),
        HotPathQuery(
            query_id="runtime_callback_due_diagnostics",
            purpose="callback worker and diagnostics scan due callback deliveries",
            sql="""
                SELECT run_id
                FROM run_records
                WHERE finished_at IS NOT NULL
                  AND callback_status = 'pending'
                  AND callback_next_attempt_at IS NOT NULL
                  AND callback_next_attempt_at <= :now
                ORDER BY callback_next_attempt_at ASC, finished_at ASC
                LIMIT :limit
            """,
            params={"now": now, "limit": limit},
            expected_indexes=("ix_run_records_callback_due",),
        ),
        HotPathQuery(
            query_id="runtime_callback_dispatching_recovery",
            purpose="callback worker recovers stale dispatching callback leases",
            sql="""
                SELECT run_id
                FROM run_records
                WHERE finished_at IS NOT NULL
                  AND callback_status = 'dispatching'
                  AND callback_last_attempt_at IS NOT NULL
                  AND callback_last_attempt_at <= :callback_stale_before
                ORDER BY callback_last_attempt_at ASC, finished_at ASC
                LIMIT :limit
            """,
            params={
                "callback_stale_before": now - timedelta(minutes=5),
                "limit": limit,
            },
            expected_indexes=("ix_run_records_callback_dispatching_lease",),
        ),
        HotPathQuery(
            query_id="runtime_recent_nightly_runs",
            purpose="public read path loads recent nightly inspection runs for one site",
            sql="""
                SELECT run_id
                FROM run_records
                WHERE site_id = :site_id
                  AND execution_kind = :execution_kind
                ORDER BY started_at DESC, run_id DESC
                LIMIT :limit
            """,
            params={
                "site_id": site_id,
                "execution_kind": CLOUD_BATCH_RUNTIME_EXECUTION_KIND,
                "limit": limit,
            },
        ),
        HotPathQuery(
            query_id="image_source_provider_metrics",
            purpose="readonly image source metrics aggregate provider calls in SQL",
            sql=f"""
                SELECT
                    provider_call_records.provider_id,
                    count(provider_call_records.id) AS call_count,
                    sum(CASE
                        WHEN provider_call_records.error_code IS NOT NULL
                         AND provider_call_records.error_code != ''
                        THEN 1 ELSE 0
                    END) AS error_count,
                    sum(provider_call_records.latency_ms) AS latency_total_ms,
                    sum(provider_call_records.cost) AS cost_total,
                    max(provider_call_records.created_at) AS last_seen_at
                FROM provider_call_records
                JOIN run_records
                  ON provider_call_records.run_id = run_records.run_id
                WHERE run_records.ability_name IN ({image_ability_placeholders})
                  AND run_records.started_at >= :metrics_start_at
                  AND run_records.started_at <= :metrics_end_at
                GROUP BY provider_call_records.provider_id
                ORDER BY count(provider_call_records.id) DESC,
                         provider_call_records.provider_id ASC
            """,
            params=image_metrics_params,
        ),
    ]


def _resolve_database_url(raw_database_url: str | None) -> str:
    if raw_database_url:
        return raw_database_url
    env_database_url = os.getenv("NPCINK_CLOUD_DATABASE_URL", "").strip()
    if env_database_url:
        return env_database_url
    return Settings().database_url


def _fetch_postgres_indexes(connection: Connection) -> set[str]:
    rows = connection.execute(
        text(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = current_schema()
              AND tablename IN ('run_records', 'provider_call_records')
            """
        )
    ).all()
    return {str(row[0]) for row in rows}


def _fetch_sqlite_indexes(connection: Connection) -> set[str]:
    index_names: set[str] = set()
    for table_name in ("run_records", "provider_call_records"):
        rows = connection.execute(text(f"PRAGMA index_list('{table_name}')")).all()
        index_names.update(str(row[1]) for row in rows if len(row) > 1)
    return index_names


def _fetch_available_indexes(connection: Connection, dialect_name: str) -> set[str]:
    if dialect_name == "postgresql":
        return _fetch_postgres_indexes(connection)
    if dialect_name == "sqlite":
        return _fetch_sqlite_indexes(connection)
    return set()


def _run_explain(
    connection: Connection,
    *,
    dialect_name: str,
    query: HotPathQuery,
    analyze: bool,
) -> list[str]:
    normalized_sql = " ".join(query.sql.split())
    if dialect_name == "postgresql":
        options = "ANALYZE, BUFFERS" if analyze else ""
        prefix = f"EXPLAIN ({options}) " if options else "EXPLAIN "
        rows = connection.execute(text(prefix + normalized_sql), query.params).all()
        return [str(row[0]) for row in rows]
    if dialect_name == "sqlite":
        rows = connection.execute(text("EXPLAIN QUERY PLAN " + normalized_sql), query.params).all()
        return [" | ".join(str(value) for value in row) for row in rows]
    rows = connection.execute(text("EXPLAIN " + normalized_sql), query.params).all()
    return [str(row[0]) for row in rows]


def _build_check_result(
    *,
    connection: Connection,
    dialect_name: str,
    available_indexes: set[str],
    query: HotPathQuery,
    analyze: bool,
) -> dict[str, object]:
    plan_lines = _run_explain(
        connection,
        dialect_name=dialect_name,
        query=query,
        analyze=analyze,
    )
    plan_text = "\n".join(plan_lines)
    expected_indexes = list(query.expected_indexes)
    available_expected_indexes = [
        index_name for index_name in expected_indexes if index_name in available_indexes
    ]
    plan_expected_indexes = [
        index_name for index_name in expected_indexes if index_name in plan_text
    ]
    return {
        "query_id": query.query_id,
        "purpose": query.purpose,
        "expected_indexes": expected_indexes,
        "expected_indexes_available": available_expected_indexes,
        "expected_indexes_missing": [
            index_name for index_name in expected_indexes if index_name not in available_indexes
        ],
        "expected_indexes_in_plan": plan_expected_indexes,
        "expected_indexes_not_in_plan": [
            index_name for index_name in expected_indexes if index_name not in plan_text
        ],
        "plan": plan_lines,
    }


def _format_text(report: dict[str, object]) -> str:
    lines = [
        f"Runtime hot path explain ({report['database_dialect']}, analyze={report['analyze']})",
        f"generated_at={report['generated_at']}",
        "",
    ]
    checks = report.get("checks")
    if isinstance(checks, list):
        for check in checks:
            if not isinstance(check, dict):
                continue
            lines.append(f"== {check.get('query_id')} ==")
            lines.append(f"purpose: {check.get('purpose')}")
            expected = check.get("expected_indexes")
            if expected:
                lines.append(f"expected_indexes: {', '.join(str(item) for item in expected)}")
                missing = check.get("expected_indexes_missing")
                if missing:
                    lines.append(f"missing_indexes: {', '.join(str(item) for item in missing)}")
                in_plan = check.get("expected_indexes_in_plan")
                if in_plan:
                    lines.append(f"indexes_in_plan: {', '.join(str(item) for item in in_plan)}")
            lines.append("plan:")
            plan = check.get("plan")
            if isinstance(plan, list):
                lines.extend(f"  {line}" for line in plan)
            lines.append("")
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run EXPLAIN baselines for Cloud runtime hot path queries.",
    )
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--site-id", default="site_smoke")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--analyze", dest="analyze", action="store_true", default=True)
    parser.add_argument("--no-analyze", dest="analyze", action="store_false")
    parser.add_argument("--require-indexes", action="store_true")
    parser.add_argument("--require-plan-index-use", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    database_url = _resolve_database_url(args.database_url)
    engine = create_engine(database_url)
    now = _utc_now()
    checks: list[dict[str, object]] = []
    with engine.connect() as connection:
        dialect_name = connection.dialect.name
        available_indexes = _fetch_available_indexes(connection, dialect_name)
        for query in _build_queries(now=now, site_id=args.site_id, limit=max(1, args.limit)):
            checks.append(
                _build_check_result(
                    connection=connection,
                    dialect_name=dialect_name,
                    available_indexes=available_indexes,
                    query=query,
                    analyze=bool(args.analyze),
                )
            )

    report: dict[str, object] = {
        "contract_version": "runtime_hot_path_explain.v1",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "database_dialect": engine.dialect.name,
        "analyze": bool(args.analyze),
        "site_id": str(args.site_id),
        "checks": checks,
        "boundary": {
            "cloud_role": "runtime_performance_detail",
            "direct_wordpress_write": False,
            "contains_prompt_or_result_payloads": False,
            "contains_provider_secrets": False,
        },
    }
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_format_text(report))

    missing_index_checks = [
        check
        for check in checks
        if check.get("expected_indexes_missing")
    ]
    missing_plan_checks = [
        check
        for check in checks
        if check.get("expected_indexes") and check.get("expected_indexes_not_in_plan")
    ]
    if args.require_indexes and missing_index_checks:
        return 1
    if args.require_plan_index_use and missing_plan_checks:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
