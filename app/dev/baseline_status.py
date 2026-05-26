from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import ValidationError
from sqlalchemy import inspect, text

from app.core.config import Settings, get_settings
from app.core.db import get_session


def get_required_schema() -> dict[str, list[str]]:
    return {
        "sites": [
            "site_id",
            "status",
            "account_id",
            "provisioned_at",
            "activated_at",
            "suspended_at",
        ],
        "site_api_keys": [
            "key_id",
            "site_id",
            "status",
            "expires_at",
            "revoked_at",
            "rotated_from_key_id",
            "replaced_by_key_id",
        ],
        "run_records": [
            "run_id",
            "site_id",
            "account_id",
            "subscription_id",
            "plan_version_id",
            "ability_family",
            "cancel_requested_at",
            "canceled_at",
            "callback_status",
            "callback_attempt_count",
            "callback_next_attempt_at",
        ],
        "plan_versions": [
            "plan_version_id",
            "plan_id",
            "entitlements_json",
            "budgets_json",
            "concurrency_json",
            "policy_json",
        ],
        "account_entitlement_snapshots": [
            "id",
            "account_id",
            "subscription_id",
            "plan_version_id",
            "entitlements_json",
            "budgets_json",
            "concurrency_json",
            "policy_json",
            "site_limit",
        ],
        "usage_meter_events": [
            "id",
            "site_id",
            "subscription_id",
            "plan_version_id",
            "event_kind",
            "meter_key",
            "dedupe_key",
            "ability_family",
        ],
        "billing_snapshots": [
            "snapshot_id",
            "site_id",
            "subscription_id",
            "plan_version_id",
            "totals_json",
            "breakdown_json",
        ],
        "service_audit_events": [
            "id",
            "site_id",
            "key_id",
            "event_kind",
            "outcome",
            "actor_kind",
            "trace_id",
        ],
        "commercial_decision_events": [
            "id",
            "site_id",
            "subscription_id",
            "plan_version_id",
            "request_kind",
            "decision",
            "decision_code",
            "trace_id",
        ],
        "runtime_guard_events": [
            "id",
            "auth_surface",
            "scope_kind",
            "scope_id",
            "event_code",
            "status_code",
            "created_at",
        ],
        "provider_connections": [
            "connection_id",
            "provider_type",
            "source_role",
            "enabled",
            "base_url",
            "status",
        ],
    }


def _build_alembic_config() -> Config:
    root_dir = Path(__file__).resolve().parents[2]
    return Config(str(root_dir / "alembic.ini"))


def _build_settings_validation_failure_payload(error: ValidationError) -> dict[str, Any]:
    alembic_heads = sorted(ScriptDirectory.from_config(_build_alembic_config()).get_heads())
    config_errors = []
    for item in error.errors():
        loc = item.get("loc", ())
        field = ".".join(str(part) for part in loc if str(part))
        config_errors.append(
            {
                "field": field,
                "message": str(item.get("msg", "")),
                "type": str(item.get("type", "")),
            }
        )

    return {
        "environment": "unknown",
        "internal_auth_token_configured": False,
        "config_errors": config_errors,
        "alembic": {
            "version_table_present": False,
            "database_versions": [],
            "expected_heads": alembic_heads,
            "in_sync": False,
        },
        "schema": {
            "missing_tables": [],
            "missing_columns": {},
            "row_counts": {},
        },
        "status": "fail",
        "failures": ["settings_validation_error"],
    }


def evaluate_remote_baseline_status(
    settings: Settings,
    *,
    require_internal_auth_token: bool = True,
) -> dict[str, Any]:
    alembic_config = _build_alembic_config()
    alembic_heads = sorted(ScriptDirectory.from_config(alembic_config).get_heads())

    with get_session(settings.database_url) as session:
        connection = session.connection()
        inspector = inspect(connection)
        existing_tables = set(inspector.get_table_names())
        alembic_version_present = "alembic_version" in existing_tables
        database_versions = (
            sorted(
                session.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num"))
                .scalars()
                .all()
            )
            if alembic_version_present
            else []
        )

        missing_tables: list[str] = []
        missing_columns: dict[str, list[str]] = {}
        row_counts: dict[str, int] = {}

        for table_name, required_columns in get_required_schema().items():
            if table_name not in existing_tables:
                missing_tables.append(table_name)
                continue

            present_columns = {column["name"] for column in inspector.get_columns(table_name)}
            missing = sorted(set(required_columns) - present_columns)
            if missing:
                missing_columns[table_name] = missing

            row_counts[table_name] = int(
                session.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar_one()
            )

    failures: list[str] = []
    if require_internal_auth_token and not settings.internal_auth_token:
        failures.append("internal_auth_token_missing")
    if not alembic_version_present:
        failures.append("alembic_version_missing")
    elif database_versions != alembic_heads:
        failures.append("alembic_head_mismatch")
    if missing_tables:
        failures.append("missing_tables")
    if missing_columns:
        failures.append("missing_columns")

    return {
        "environment": settings.environment,
        "internal_auth_token_configured": bool(settings.internal_auth_token),
        "config_errors": [],
        "alembic": {
            "version_table_present": alembic_version_present,
            "database_versions": database_versions,
            "expected_heads": alembic_heads,
            "in_sync": alembic_version_present and database_versions == alembic_heads,
        },
        "schema": {
            "missing_tables": missing_tables,
            "missing_columns": missing_columns,
            "row_counts": row_counts,
        },
        "status": "ok" if not failures else "fail",
        "failures": failures,
    }


def load_remote_baseline_status(
    *,
    require_internal_auth_token: bool = True,
    settings_loader: Callable[[], Settings] = get_settings,
) -> dict[str, Any]:
    try:
        settings = settings_loader()
    except ValidationError as error:
        return _build_settings_validation_failure_payload(error)

    return evaluate_remote_baseline_status(
        settings,
        require_internal_auth_token=require_internal_auth_token,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-internal-auth-token",
        action="store_true",
        help="Only validate schema/alembic state.",
    )
    args = parser.parse_args()

    payload = load_remote_baseline_status(
        require_internal_auth_token=not args.skip_internal_auth_token,
    )
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if not payload["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
