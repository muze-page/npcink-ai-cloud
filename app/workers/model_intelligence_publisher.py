from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from app.adapters.repositories.catalog_repository import CatalogRepository
from app.core.config import Settings
from app.core.db import get_session
from app.model_intelligence.publisher.runner import run_publisher


WORKER_SOURCE = "model_intelligence_publisher_worker"
FRESH_AFTER_HOURS = 12.0
EXPIRE_AFTER_HOURS = 48.0


def run_once(
    settings: Settings,
    *,
    publisher_runner: Callable[..., Any] | None = None,
    now_factory: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    bundle_path = str(settings.model_intelligence_bundle_path or "").strip()
    summary_path = str(settings.model_intelligence_run_summary_path or "").strip()

    if not bundle_path:
        return {
            "source": WORKER_SOURCE,
            "status": "skipped",
            "reason": "model_intelligence_bundle_path_not_configured",
            "bundle_path": bundle_path,
            "run_summary_path": summary_path,
        }
    if not summary_path:
        return {
            "source": WORKER_SOURCE,
            "status": "skipped",
            "reason": "model_intelligence_run_summary_path_not_configured",
            "bundle_path": bundle_path,
            "run_summary_path": summary_path,
        }

    active_runner = publisher_runner or run_publisher
    clock = now_factory or (lambda: datetime.now(UTC))
    started_at = _serialize_timestamp(clock())
    try:
        active_runner(settings, now_factory=clock)
    except Exception as error:
        result = {
            "source": WORKER_SOURCE,
            "status": "error",
            "started_at": started_at,
            "finished_at": _serialize_timestamp(clock()),
            "exit_code": 1,
            "script_path": "",
            "bundle_path": bundle_path,
            "run_summary_path": summary_path,
            "stdout": "",
            "stderr": str(error).strip(),
            "reason": "model_intelligence_publisher_run_failed",
        }
        summary_payload = _read_json_file(summary_path)
        if summary_payload is not None:
            result["scheduled_summary"] = summary_payload
        return result

    summary_payload = _read_json_file(summary_path)
    bundle_payload = _read_json_file(bundle_path)
    result = {
        "source": WORKER_SOURCE,
        "status": "ok",
        "started_at": started_at,
        "finished_at": _serialize_timestamp(clock()),
        "exit_code": 0,
        "script_path": "",
        "bundle_path": bundle_path,
        "run_summary_path": summary_path,
        "stdout": "",
        "stderr": "",
    }
    if summary_payload is not None:
        result["scheduled_summary"] = summary_payload
    if bundle_payload is None:
        result["status"] = "error"
        result["reason"] = "model_intelligence_bundle_missing_after_run"
        return result

    generated_at = str(bundle_payload.get("generated_at") or "").strip()
    checksum = str(bundle_payload.get("checksum") or "").strip().lower()
    source_ids = _extract_source_ids(bundle_payload.get("sources"))
    record_keys = _extract_record_keys(bundle_payload.get("models"))
    records_total = len(record_keys)
    revision = _build_revision(bundle_payload, checksum=checksum, records_total=records_total)

    result.update(
        {
            "generated_at": generated_at,
            "checksum": checksum,
            "revision": revision,
            "records_total": records_total,
            "source_keys": source_ids,
        }
    )

    summary_status = str((summary_payload or {}).get("status") or "").strip().lower()
    if summary_status == "error":
        result["status"] = "error"
        result["reason"] = "model_intelligence_publisher_run_failed"
        return result

    _persist_publication(
        settings=settings,
        bundle_payload=bundle_payload,
        summary_payload=summary_payload or {},
        revision=revision,
        checksum=checksum,
        generated_at=generated_at,
        source_ids=source_ids,
        record_keys=record_keys,
        bundle_path=bundle_path,
        summary_path=summary_path,
    )
    return result


def inspect_publisher_state(settings: Settings) -> dict[str, Any]:
    return inspect_publisher_state_at(settings)


def inspect_publisher_state_at(
    settings: Settings,
    *,
    now_factory: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    bundle_path = str(settings.model_intelligence_bundle_path or "").strip()
    summary_path = str(settings.model_intelligence_run_summary_path or "").strip()
    bundle_payload = _read_json_file(bundle_path)
    summary_payload = _read_json_file(summary_path)
    clock = now_factory or (lambda: datetime.now(UTC))
    now = clock()
    source_rows = _normalize_source_rows(bundle_payload.get("sources") if bundle_payload else None)
    failed_sources = _extract_failed_sources(
        summary_payload.get("failed_sources") if summary_payload else None,
        source_rows=source_rows,
    )

    state: dict[str, Any] = {
        "configured": bool(bundle_path and summary_path),
        "enabled": bool(settings.model_intelligence_publisher_enabled),
        "script_path": "",
        "script_exists": False,
        "bundle_path": bundle_path,
        "bundle_exists": bool(bundle_path and Path(bundle_path).exists()),
        "run_summary_path": summary_path,
        "run_summary_exists": bool(summary_path and Path(summary_path).exists()),
        "generated_at": "",
        "hours_old": None,
        "freshness_status": "missing",
        "checksum": "",
        "records_total": 0,
        "source_keys": [],
        "failed_sources": failed_sources,
        "revision": "",
        "latest_publication": {},
        "recent_publications": [],
        "health_status": "error",
        "health_issues": [],
        "operator_alerts": [],
        "fallback": {
            "previous_bundle_used": False,
            "published_bundle_source": "",
            "bundle_retained_reason": "",
            "cached_sources_used": [],
        },
    }
    if bundle_payload is not None:
        source_keys = _extract_source_ids(bundle_payload.get("sources"))
        record_keys = _extract_record_keys(bundle_payload.get("models"))
        checksum = str(bundle_payload.get("checksum") or "").strip().lower()
        generated_at = str(bundle_payload.get("generated_at") or "").strip()
        generated_at_dt = _parse_timestamp(generated_at)
        hours_old = _compute_hours_old(generated_at_dt, now)
        state.update(
            {
                "generated_at": generated_at,
                "hours_old": hours_old,
                "freshness_status": _freshness_status(hours_old),
                "checksum": checksum,
                "records_total": len(record_keys),
                "source_keys": source_keys,
                "revision": _build_revision(
                    bundle_payload,
                    checksum=checksum,
                    records_total=len(record_keys),
                ),
            }
        )
    if summary_payload is not None:
        state["scheduled_summary"] = summary_payload
        state["fallback"] = {
            "previous_bundle_used": bool(summary_payload.get("previous_bundle_used")),
            "published_bundle_source": str(summary_payload.get("published_bundle_source") or ""),
            "bundle_retained_reason": str(summary_payload.get("bundle_retained_reason") or ""),
            "cached_sources_used": list(summary_payload.get("cached_sources_used") or []),
        }

    with get_session(settings.database_url) as session:
        repository = CatalogRepository(session)
        publications = repository.list_recent_recognition_snapshot_publications(limit=5)
    if publications:
        publication = publications[0]
        state["latest_publication"] = {
            "revision": str(publication.revision or ""),
            "checksum": str(publication.checksum or ""),
            "generated_at": _serialize_timestamp(publication.generated_at),
            "hours_old": _compute_hours_old(publication.generated_at, now),
            "freshness_status": _freshness_status(
                _compute_hours_old(publication.generated_at, now)
            ),
            "records_total": int(publication.records_total or 0),
            "source_keys": list(publication.source_keys_json or []),
            "metadata": dict(publication.metadata_json or {}),
            "failed_sources": list((publication.metadata_json or {}).get("failed_sources") or []),
            "fallback": {
                "previous_bundle_used": bool((publication.metadata_json or {}).get("previous_bundle_used")),
                "bundle_retained_reason": str((publication.metadata_json or {}).get("bundle_retained_reason") or ""),
                "cached_sources_used": list((publication.metadata_json or {}).get("cached_sources_used") or []),
            },
        }
        state["recent_publications"] = [
            {
                "revision": str(item.revision or ""),
                "checksum": str(item.checksum or ""),
                "generated_at": _serialize_timestamp(item.generated_at),
                "hours_old": _compute_hours_old(item.generated_at, now),
                "freshness_status": _freshness_status(_compute_hours_old(item.generated_at, now)),
                "records_total": int(item.records_total or 0),
                "source_keys": list(item.source_keys_json or []),
                "failed_sources": list((item.metadata_json or {}).get("failed_sources") or []),
                "fallback": {
                    "previous_bundle_used": bool((item.metadata_json or {}).get("previous_bundle_used")),
                    "bundle_retained_reason": str((item.metadata_json or {}).get("bundle_retained_reason") or ""),
                    "cached_sources_used": list((item.metadata_json or {}).get("cached_sources_used") or []),
                },
            }
            for item in publications
        ]
    health_status, health_issues = _build_health_summary(state)
    state["health_status"] = health_status
    state["health_issues"] = health_issues
    state["operator_alerts"] = _build_operator_alerts(state)
    return state


def _build_health_summary(state: dict[str, Any]) -> tuple[str, list[str]]:
    issues: list[str] = []
    if not state.get("enabled"):
        issues.append("publisher_disabled")
    if not state.get("configured"):
        issues.append("publisher_unconfigured")
    if not state.get("bundle_exists"):
        issues.append("bundle_missing")
    freshness_status = str(state.get("freshness_status") or "missing")
    if freshness_status == "expired":
        issues.append("bundle_expired")
    elif freshness_status == "stale":
        issues.append("bundle_stale")
    elif freshness_status == "missing":
        issues.append("bundle_missing")
    failed_sources = list(state.get("failed_sources") or [])
    if failed_sources:
        issues.append("source_failures_present")
    fallback = state.get("fallback") if isinstance(state.get("fallback"), dict) else {}
    if fallback.get("previous_bundle_used"):
        issues.append("previous_bundle_fallback_used")
    if issues:
        if any(
            issue in {"publisher_unconfigured", "bundle_missing", "bundle_expired", "source_failures_present"}
            for issue in issues
        ):
            return "error", issues
        return "warning", issues
    return "ok", []


def _build_operator_alerts(state: dict[str, Any]) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    freshness_status = str(state.get("freshness_status") or "missing")
    hours_old = state.get("hours_old")
    failed_sources = list(state.get("failed_sources") or [])
    fallback = state.get("fallback") if isinstance(state.get("fallback"), dict) else {}

    if not state.get("configured"):
        alerts.append(
            {
                "code": "publisher_unconfigured",
                "severity": "error",
                "hours_old": hours_old,
                "failed_sources": [],
            }
        )
    elif freshness_status == "expired":
        alerts.append(
            {
                "code": "bundle_expired",
                "severity": "error",
                "hours_old": hours_old,
                "failed_sources": [],
            }
        )
    elif freshness_status == "stale":
        alerts.append(
            {
                "code": "bundle_stale",
                "severity": "warning",
                "hours_old": hours_old,
                "failed_sources": [],
            }
        )

    if failed_sources:
        alerts.append(
            {
                "code": "source_failures_present",
                "severity": "error",
                "hours_old": hours_old,
                "failed_sources": failed_sources,
            }
        )

    cached_sources_used = list(fallback.get("cached_sources_used") or [])
    if fallback.get("previous_bundle_used"):
        alerts.append(
            {
                "code": "previous_bundle_fallback_used",
                "severity": "warning",
                "hours_old": hours_old,
                "failed_sources": [],
                "bundle_retained_reason": str(fallback.get("bundle_retained_reason") or ""),
                "cached_sources_used": cached_sources_used,
            }
        )
    elif cached_sources_used:
        alerts.append(
            {
                "code": "cached_sources_fallback_used",
                "severity": "warning",
                "hours_old": hours_old,
                "failed_sources": [],
                "cached_sources_used": cached_sources_used,
            }
        )

    return alerts


def _persist_publication(
    *,
    settings: Settings,
    bundle_payload: dict[str, Any],
    summary_payload: dict[str, Any],
    revision: str,
    checksum: str,
    generated_at: str,
    source_ids: list[str],
    record_keys: list[str],
    bundle_path: str,
    summary_path: str,
) -> None:
    publication_generated_at = _parse_timestamp(generated_at) or datetime.now(UTC)
    source_run_ids = _persist_source_runs(
        settings=settings,
        summary_payload=summary_payload,
        generated_at=publication_generated_at,
        bundle_path=bundle_path,
    )

    metadata = {
        "source_kind": "publisher_bundle",
        "bundle_kind": str(bundle_payload.get("bundle_kind") or ""),
        "schema_version": str(bundle_payload.get("schema_version") or ""),
        "bundle_path": bundle_path,
        "run_summary_path": summary_path,
        "failed_sources": list(summary_payload.get("failed_sources") or []),
        "previous_bundle_used": bool(summary_payload.get("previous_bundle_used")),
        "bundle_retained_reason": str(summary_payload.get("bundle_retained_reason") or ""),
        "cached_sources_used": list(summary_payload.get("cached_sources_used") or []),
    }
    with get_session(settings.database_url) as session:
        repository = CatalogRepository(session)
        repository.upsert_recognition_snapshot_publication(
            revision=revision,
            checksum=checksum,
            generated_at=publication_generated_at,
            records_total=len(record_keys),
            source_keys_json=source_ids,
            source_run_ids_json=source_run_ids,
            record_keys_json=record_keys,
            metadata_json=metadata,
        )
        session.commit()


def _persist_source_runs(
    *,
    settings: Settings,
    summary_payload: dict[str, Any],
    generated_at: datetime,
    bundle_path: str,
) -> list[str]:
    raw_sources = summary_payload.get("sources")
    if not isinstance(raw_sources, list):
        return []

    run_ids: list[str] = []
    with get_session(settings.database_url) as session:
        repository = CatalogRepository(session)
        for item in raw_sources:
            if not isinstance(item, dict):
                continue
            source_name = str(item.get("source_id") or "").strip().lower()
            if not source_name:
                continue
            run_id = f"publisher:{generated_at.strftime('%Y%m%dT%H%M%SZ')}:{source_name}"
            repository.upsert_recognition_source_run(
                run_id=run_id,
                source_name=source_name,
                snapshot_generated_at=generated_at,
                started_at=generated_at,
                finished_at=generated_at,
                status="ok",
                duration_ms=0,
                records_fetched=max(0, int(item.get("records_total") or 0)),
                records_accepted=max(0, int(item.get("records_total") or 0)),
                error_message=None,
                metadata_json={
                    "source_kind": "publisher_bundle",
                    "checksum": str(item.get("checksum") or ""),
                    "cached_fallback_used": bool(item.get("cached_fallback_used")),
                    "bundle_path": bundle_path,
                },
            )
            run_ids.append(run_id)
        session.commit()
    return run_ids


def _extract_source_ids(payload: Any) -> list[str]:
    if not isinstance(payload, list):
        return []
    source_ids: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id") or "").strip()
        if source_id and source_id not in source_ids:
            source_ids.append(source_id)
    return source_ids


def _normalize_source_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    source_rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id") or "").strip()
        if not source_id:
            continue
        source_rows.append(
            {
                "source_id": source_id,
                "status": str(item.get("status") or "").strip().lower() or "ok",
                "fetched_at": str(item.get("fetched_at") or "").strip(),
            }
        )
    return source_rows


def _extract_failed_sources(payload: Any, *, source_rows: list[dict[str, Any]]) -> list[str]:
    failed: list[str] = []
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                source_id = str(item.get("source_id") or item.get("source") or "").strip()
            else:
                source_id = str(item or "").strip()
            if source_id and source_id not in failed:
                failed.append(source_id)
    for item in source_rows:
        source_id = str(item.get("source_id") or "").strip()
        status = str(item.get("status") or "").strip().lower()
        if source_id and status not in {"ok", "success", "configured"} and source_id not in failed:
            failed.append(source_id)
    return failed


def _extract_record_keys(payload: Any) -> list[str]:
    if not isinstance(payload, list):
        return []
    record_keys: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "").strip()
        model_id = str(item.get("model_id") or "").strip()
        if not provider or not model_id:
            continue
        record_keys.append(f"{provider}::{model_id}")
    return record_keys


def _build_revision(
    bundle_payload: dict[str, Any],
    *,
    checksum: str,
    records_total: int,
) -> str:
    generated_at = str(bundle_payload.get("generated_at") or "").strip() or "unknown"
    if checksum:
        return f"publisher-{generated_at}-{checksum[:12]}"
    revision_seed = json.dumps(
        {
            "bundle_kind": bundle_payload.get("bundle_kind"),
            "schema_version": bundle_payload.get("schema_version"),
            "generated_at": generated_at,
            "records_total": records_total,
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return f"publisher-{generated_at}-{hashlib.sha256(revision_seed).hexdigest()[:12]}"


def _read_json_file(path_value: str) -> dict[str, Any] | None:
    path_value = str(path_value or "").strip()
    if not path_value:
        return None
    path = Path(path_value)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_timestamp(raw_value: str) -> datetime | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _compute_hours_old(value: datetime | None, now: datetime) -> float | None:
    if value is None:
        return None
    delta = max(0.0, (now - value.astimezone(UTC)).total_seconds())
    return round(delta / 3600, 2)


def _freshness_status(hours_old: float | None) -> str:
    if hours_old is None:
        return "missing"
    if hours_old > EXPIRE_AFTER_HOURS:
        return "expired"
    if hours_old > FRESH_AFTER_HOURS:
        return "stale"
    return "fresh"


def _serialize_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
