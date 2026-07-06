from __future__ import annotations

# ruff: noqa: E402
import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core.config import Settings
from app.dev.baseline_status import load_remote_baseline_status
from scripts import runtime_hot_path_explain

HTTP_ENDPOINTS: tuple[tuple[str, str, bool, dict[str, str]], ...] = (
    ("health_live", "/health/live", False, {}),
    ("health_ready", "/health/ready", True, {}),
    ("health_operational_ready", "/health/operational-ready", True, {}),
    (
        "observability_summary",
        "/internal/service/observability/summary",
        True,
        {"recent_minutes": "60", "backlog_limit": "10"},
    ),
    ("ops_cadence", "/internal/service/ops/cadence", True, {}),
    (
        "runtime_diagnostics_summary",
        "/internal/service/runtime/diagnostics/summary",
        True,
        {"recent_minutes": "120"},
    ),
    (
        "runtime_diagnostics_backlog",
        "/internal/service/runtime/diagnostics/backlog",
        True,
        {"scope_kind": "site_id", "limit": "10"},
    ),
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _env_default_base_url() -> str:
    configured = os.getenv("NPCINK_CLOUD_BASE_URL", "").strip()
    if configured:
        return configured
    port = os.getenv("NPCINK_CLOUD_PORT", "8010").strip() or "8010"
    return f"http://127.0.0.1:{port}"


def _fetch_count_map(engine: Engine, sql: str) -> dict[str, int]:
    with engine.connect() as connection:
        rows = connection.execute(text(sql)).all()
    return {
        str(row[0] if row[0] is not None else "null"): int(row[1] or 0)
        for row in rows
    }


def _fetch_scalar(engine: Engine, sql: str, params: dict[str, object] | None = None) -> int:
    with engine.connect() as connection:
        value = connection.execute(text(sql), params or {}).scalar_one()
    return int(value or 0)


def _load_database_runtime_summary(engine: Engine, now: datetime) -> dict[str, object]:
    callback_due_before = now
    running_stale_before = now - timedelta(minutes=15)
    callback_stale_before = now - timedelta(minutes=5)
    recent_start = now - timedelta(hours=24)
    return {
        "run_records_by_status": _fetch_count_map(
            engine,
            """
            SELECT COALESCE(status, 'null') AS bucket, COUNT(*)
            FROM run_records
            GROUP BY COALESCE(status, 'null')
            ORDER BY bucket
            """,
        ),
        "callback_records_by_status": _fetch_count_map(
            engine,
            """
            SELECT COALESCE(callback_status, 'null') AS bucket, COUNT(*)
            FROM run_records
            GROUP BY COALESCE(callback_status, 'null')
            ORDER BY bucket
            """,
        ),
        "hot_counts": {
            "queued": _fetch_scalar(
                engine,
                "SELECT COUNT(*) FROM run_records WHERE status = 'queued'",
            ),
            "running_stale": _fetch_scalar(
                engine,
                """
                SELECT COUNT(*)
                FROM run_records
                WHERE status = 'running'
                  AND processing_started_at IS NOT NULL
                  AND processing_started_at <= :running_stale_before
                """,
                {"running_stale_before": running_stale_before},
            ),
            "callback_due": _fetch_scalar(
                engine,
                """
                SELECT COUNT(*)
                FROM run_records
                WHERE finished_at IS NOT NULL
                  AND callback_status = 'pending'
                  AND callback_next_attempt_at IS NOT NULL
                  AND callback_next_attempt_at <= :callback_due_before
                """,
                {"callback_due_before": callback_due_before},
            ),
            "callback_dispatching_stale": _fetch_scalar(
                engine,
                """
                SELECT COUNT(*)
                FROM run_records
                WHERE finished_at IS NOT NULL
                  AND callback_status = 'dispatching'
                  AND callback_last_attempt_at IS NOT NULL
                  AND callback_last_attempt_at <= :callback_stale_before
                """,
                {"callback_stale_before": callback_stale_before},
            ),
            "recent_24h_runs": _fetch_scalar(
                engine,
                "SELECT COUNT(*) FROM run_records WHERE started_at >= :recent_start",
                {"recent_start": recent_start},
            ),
            "provider_call_records": _fetch_scalar(
                engine,
                "SELECT COUNT(*) FROM provider_call_records",
            ),
        },
    }


def _load_hot_path_report(
    engine: Engine,
    *,
    site_id: str,
    limit: int,
    analyze: bool,
) -> dict[str, object]:
    now = _utc_now()
    checks: list[dict[str, object]] = []
    with engine.connect() as connection:
        dialect_name = connection.dialect.name
        available_indexes = runtime_hot_path_explain._fetch_available_indexes(
            connection,
            dialect_name,
        )
        for query in runtime_hot_path_explain._build_queries(
            now=now,
            site_id=site_id,
            limit=max(1, limit),
        ):
            checks.append(
                runtime_hot_path_explain._build_check_result(
                    connection=connection,
                    dialect_name=dialect_name,
                    available_indexes=available_indexes,
                    query=query,
                    analyze=analyze,
                )
            )
    return {
        "contract_version": "runtime_hot_path_explain.v1",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "database_dialect": engine.dialect.name,
        "analyze": analyze,
        "site_id": site_id,
        "checks": checks,
        "boundary": {
            "cloud_role": "runtime_performance_detail",
            "direct_wordpress_write": False,
            "contains_prompt_or_result_payloads": False,
            "contains_provider_secrets": False,
        },
    }


def _http_get_json(
    *,
    base_url: str,
    path: str,
    query: dict[str, str],
    internal_token: str | None,
    timeout_seconds: float,
) -> dict[str, object]:
    url = f"{base_url.rstrip('/')}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    headers = {"Accept": "application/json"}
    if internal_token:
        headers["X-Npcink-Internal-Token"] = internal_token
    request = Request(url, headers=headers, method="GET")
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw_body = response.read()
            elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
            try:
                body: object = json.loads(raw_body.decode("utf-8"))
            except json.JSONDecodeError:
                body = {"raw_body_prefix": raw_body[:500].decode("utf-8", errors="replace")}
            return {
                "status": int(response.status),
                "elapsed_ms": elapsed_ms,
                "body": body,
            }
    except HTTPError as error:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        raw_body = error.read()
        return {
            "status": int(error.code),
            "elapsed_ms": elapsed_ms,
            "error": error.reason,
            "body_prefix": raw_body[:500].decode("utf-8", errors="replace"),
        }
    except URLError as error:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        return {
            "status": None,
            "elapsed_ms": elapsed_ms,
            "error": str(error.reason),
        }


def _load_http_summary(
    *,
    base_url: str,
    internal_token: str | None,
    timeout_seconds: float,
    skip_http: bool,
) -> dict[str, object]:
    if skip_http:
        return {"skipped": True, "reason": "skip_http_requested", "checks": {}}

    checks: dict[str, object] = {}
    for name, path, requires_internal_token, query in HTTP_ENDPOINTS:
        if requires_internal_token and not internal_token:
            checks[name] = {
                "skipped": True,
                "reason": "internal_auth_token_missing",
                "path": path,
            }
            continue
        checks[name] = {
            "path": path,
            **_http_get_json(
                base_url=base_url,
                path=path,
                query=query,
                internal_token=internal_token if requires_internal_token else None,
                timeout_seconds=timeout_seconds,
            ),
        }
    return {
        "skipped": False,
        "base_url": base_url.rstrip("/"),
        "internal_auth_token_configured": bool(internal_token),
        "checks": checks,
    }


def _find_failures(
    report: dict[str, object],
    *,
    require_indexes: bool,
    require_plan_index_use: bool,
) -> list[str]:
    failures: list[str] = []
    baseline = report.get("baseline_status")
    if isinstance(baseline, dict) and baseline.get("failures"):
        failures.append("baseline_status_failed")

    hot_path = report.get("hot_path_explain")
    if isinstance(hot_path, dict):
        checks = hot_path.get("checks")
        if isinstance(checks, list):
            if require_indexes and any(
                isinstance(check, dict) and check.get("expected_indexes_missing")
                for check in checks
            ):
                failures.append("hot_path_expected_indexes_missing")
            if require_plan_index_use and any(
                isinstance(check, dict)
                and check.get("expected_indexes")
                and check.get("expected_indexes_not_in_plan")
                for check in checks
            ):
                failures.append("hot_path_expected_indexes_not_in_plan")

    http = report.get("http")
    if isinstance(http, dict):
        checks = http.get("checks")
        if isinstance(checks, dict):
            for name, item in checks.items():
                if not isinstance(item, dict) or item.get("skipped"):
                    continue
                status = item.get("status")
                if status != 200:
                    failures.append(f"http_{name}_status_{status}")
    return failures


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect a read-only production performance baseline for Cloud runtime.",
    )
    parser.add_argument("--base-url", default=_env_default_base_url())
    parser.add_argument("--site-id", default=os.getenv("NPCINK_CLOUD_SITE_ID", "site_smoke"))
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--format", choices=("json",), default="json")
    parser.add_argument("--explain-analyze", action="store_true")
    parser.add_argument("--require-indexes", action="store_true")
    parser.add_argument("--require-plan-index-use", action="store_true")
    parser.add_argument("--skip-http", action="store_true")
    parser.add_argument("--http-timeout-seconds", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    settings = Settings()
    engine = create_engine(settings.database_url)
    generated_at = _utc_now()
    report: dict[str, object] = {
        "contract_version": "production_performance_baseline.v1",
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "environment": settings.environment,
        "boundary": {
            "cloud_role": "runtime_performance_detail",
            "direct_wordpress_write": False,
            "contains_prompt_or_result_payloads": False,
            "contains_provider_secrets": False,
            "synthetic_runtime_smoke": False,
        },
        "baseline_status": load_remote_baseline_status(require_internal_auth_token=False),
        "database_runtime_summary": _load_database_runtime_summary(engine, generated_at),
        "hot_path_explain": _load_hot_path_report(
            engine,
            site_id=str(args.site_id),
            limit=max(1, int(args.limit)),
            analyze=bool(args.explain_analyze),
        ),
        "http": _load_http_summary(
            base_url=str(args.base_url),
            internal_token=settings.internal_auth_token,
            timeout_seconds=float(args.http_timeout_seconds),
            skip_http=bool(args.skip_http),
        ),
    }
    failures = _find_failures(
        report,
        require_indexes=bool(args.require_indexes),
        require_plan_index_use=bool(args.require_plan_index_use),
    )
    report["status"] = "ok" if not failures else "fail"
    report["failures"] = failures

    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True, default=_json_default))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
