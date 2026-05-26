from __future__ import annotations

import json
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

from app.adapters.recognition.huggingface import HuggingFaceRecognitionEvidenceImporter
from app.adapters.recognition.litellm import LiteLLMRecognitionEvidenceImporter
from app.adapters.recognition.openrouter import OpenRouterRecognitionEvidenceImporter
from app.adapters.recognition.ollama import OllamaRecognitionEvidenceImporter
from app.adapters.recognition.siliconflow import SiliconFlowRecognitionEvidenceImporter
from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.logging import configure_logging, get_logger
from app.adapters.repositories.catalog_repository import CatalogRepository
from app.domain.catalog.recognition import (
    load_active_upstream_evidence_payload,
    merge_upstream_evidence_payloads,
    normalize_upstream_evidence_payload,
    write_upstream_evidence_snapshot,
)


WORKER_SOURCE = "cloud_recognition_evidence_refresh_worker"


def run_once(
    settings: Settings,
    *,
    now_factory: Any | None = None,
    importer: LiteLLMRecognitionEvidenceImporter | None = None,
    openrouter_importer: OpenRouterRecognitionEvidenceImporter | None = None,
    siliconflow_importer: SiliconFlowRecognitionEvidenceImporter | None = None,
    hf_importer: HuggingFaceRecognitionEvidenceImporter | None = None,
    ollama_importer: OllamaRecognitionEvidenceImporter | None = None,
) -> dict[str, Any]:
    snapshot_path = str(settings.recognition_evidence_snapshot_path or "").strip()
    if not snapshot_path:
        return {
            "source": WORKER_SOURCE,
            "status": "skipped",
            "reason": "recognition_evidence_snapshot_path_not_configured",
            "records_total": 0,
        }

    generated_at = _serialize_timestamp(
        (now_factory or (lambda: datetime.now(UTC)))()
    )
    current_time = _parse_timestamp(generated_at)
    source_path = str(settings.recognition_evidence_source_path or "").strip()
    active_importer = importer or _build_litellm_importer(settings)
    active_openrouter_importer = openrouter_importer or _build_openrouter_importer(settings)
    active_siliconflow_importer = siliconflow_importer or _build_siliconflow_importer(settings)
    active_hf_importer = hf_importer or _build_huggingface_importer(settings)
    active_ollama_importer = ollama_importer or _build_ollama_importer(settings)
    if not source_path:
        cached_payload = _load_fresh_snapshot_if_available(
            snapshot_path=snapshot_path,
            now=current_time,
            min_refresh_seconds=settings.recognition_evidence_min_refresh_seconds,
        )
        if cached_payload is not None:
            return {
                "source": WORKER_SOURCE,
                "status": "skipped",
                "snapshot_path": str(snapshot_path),
                "generated_at": str(cached_payload["generated_at"]),
                "version": str(cached_payload["version"]),
                "records_total": len(cached_payload["records"]),
                "source_keys": sorted(cached_payload["sources"].keys()),
                "source_kind": "cached_snapshot",
                "source_runs": list(cached_payload.get("source_runs") or []),
                "source_run_ids": list(cached_payload.get("source_run_ids") or []),
                "source_failures": list(cached_payload.get("source_failures") or []),
                "cached_age_seconds": int(
                    max(
                        0,
                        (current_time - _parse_timestamp(str(cached_payload["generated_at"]))).total_seconds(),
                    )
                ),
            }
    source_kind = "bundled_seed"
    if source_path:
        source_payload = json.loads(Path(source_path).read_text(encoding="utf-8"))
        source_kind = "json_source_path"
        source_runs = [
            {
                "source": "json_source_path",
                "run_id": f"json_source_path:{generated_at}",
                "status": "ok",
                "generated_at": generated_at,
                "records_fetched": len(
                    dict(source_payload.get("records", {}))
                    if isinstance(source_payload, dict)
                    else {}
                ),
                "records_accepted": len(
                    dict(source_payload.get("records", {}))
                    if isinstance(source_payload, dict)
                    else {}
                ),
                "duration_ms": 0,
            }
        ]
        source_failures: list[dict[str, str]] = []
        if isinstance(source_payload, dict):
            source_payload["source_runs"] = source_runs
            source_payload["source_run_ids"] = [
                str(item.get("run_id") or "").strip()
                for item in source_runs
                if str(item.get("run_id") or "").strip()
            ]
            source_payload["source_failures"] = source_failures
    else:
        imported_payloads: list[dict[str, Any]] = []
        source_runs = []
        source_failures: list[dict[str, str]] = []
        for source_name, active_source in (
            ("litellm", active_importer),
            ("openrouter", active_openrouter_importer),
            ("siliconflow", active_siliconflow_importer),
            ("huggingface", active_hf_importer),
            ("ollama", active_ollama_importer),
        ):
            if active_source is None:
                continue
            started = perf_counter()
            try:
                payload = active_source.fetch_upstream_evidence_payload()
                imported_payloads.append(payload)
                record_count = len(
                    dict(payload.get("records", {}))
                    if isinstance(payload, dict)
                    else {}
                )
                source_runs.append(
                    {
                        "source": source_name,
                        "run_id": f"{source_name}:{generated_at}",
                        "status": "ok",
                        "generated_at": generated_at,
                        "records_fetched": record_count,
                        "records_accepted": record_count,
                        "duration_ms": int(max(0.0, (perf_counter() - started) * 1000.0)),
                    }
                )
            except (RuntimeError, ValueError) as error:
                duration_ms = int(max(0.0, (perf_counter() - started) * 1000.0))
                source_failures.append(
                    {
                        "source": source_name,
                        "error": str(error),
                    }
                )
                source_runs.append(
                    {
                        "source": source_name,
                        "run_id": f"{source_name}:{generated_at}",
                        "status": "error",
                        "generated_at": generated_at,
                        "records_fetched": 0,
                        "records_accepted": 0,
                        "duration_ms": duration_ms,
                        "error": str(error),
                    }
                )

        if imported_payloads:
            source_payload = merge_upstream_evidence_payloads(
                *imported_payloads,
                generated_at=generated_at,
            )
            source_payload["source_runs"] = source_runs
            source_payload["source_run_ids"] = [
                str(item.get("run_id") or "").strip()
                for item in source_runs
                if str(item.get("run_id") or "").strip()
            ]
            source_payload["source_failures"] = source_failures
            source_kind = (
                _describe_importer_mix(
                    active_importer is not None,
                    active_openrouter_importer is not None,
                    active_siliconflow_importer is not None,
                    active_hf_importer is not None,
                    active_ollama_importer is not None,
                )
            )
        else:
            source_payload = load_active_upstream_evidence_payload()
            if source_failures:
                source_kind = "importer_failures_fell_back_to_bundled_seed"
            source_payload["source_runs"] = source_runs
            source_payload["source_run_ids"] = [
                str(item.get("run_id") or "").strip()
                for item in source_runs
                if str(item.get("run_id") or "").strip()
            ]
            source_payload["source_failures"] = source_failures

    normalized = normalize_upstream_evidence_payload(
        source_payload if isinstance(source_payload, dict) else {},
        generated_at=generated_at,
    )
    written_path = write_upstream_evidence_snapshot(snapshot_path, normalized)
    _persist_source_runs(
        database_url=settings.database_url,
        generated_at=generated_at,
        source_runs=list(normalized.get("source_runs") or []),
        source_kind=source_kind,
        snapshot_path=str(written_path),
    )
    _persist_snapshot_publication(
        database_url=settings.database_url,
        payload=normalized,
        snapshot_path=str(written_path),
    )

    return {
        "source": WORKER_SOURCE,
        "status": "ok",
        "snapshot_path": str(written_path),
        "generated_at": str(normalized["generated_at"]),
        "version": str(normalized["version"]),
        "records_total": len(normalized["records"]),
        "source_keys": sorted(normalized["sources"].keys()),
        "source_kind": source_kind,
        "source_runs": list(normalized.get("source_runs") or []),
        "source_run_ids": list(normalized.get("source_run_ids") or []),
        "source_failures": list(normalized.get("source_failures") or []),
    }


def _persist_source_runs(
    *,
    database_url: str,
    generated_at: str,
    source_runs: list[dict[str, Any]],
    source_kind: str,
    snapshot_path: str,
) -> None:
    snapshot_generated_at = _parse_timestamp(generated_at)
    with get_session(database_url) as session:
        repository = CatalogRepository(session)
        for item in source_runs:
            if not isinstance(item, dict):
                continue
            run_id = str(item.get("run_id") or "").strip()
            source_name = str(item.get("source") or "").strip()
            if not run_id or not source_name:
                continue
            finished_at = _parse_timestamp_or_none(str(item.get("generated_at") or generated_at)) or snapshot_generated_at
            duration_ms = max(0, int(item.get("duration_ms") or 0))
            started_at = finished_at
            if duration_ms > 0:
                started_at = finished_at - timedelta(milliseconds=duration_ms)
            repository.upsert_recognition_source_run(
                run_id=run_id,
                source_name=source_name,
                snapshot_generated_at=snapshot_generated_at,
                started_at=started_at,
                finished_at=finished_at,
                status=str(item.get("status") or "unknown").strip() or "unknown",
                duration_ms=duration_ms,
                records_fetched=int(item.get("records_fetched") or 0),
                records_accepted=int(item.get("records_accepted") or 0),
                error_message=str(item.get("error") or "").strip() or None,
                metadata_json={
                    "source_kind": source_kind,
                    "snapshot_path": snapshot_path,
                },
            )
        session.commit()


def _parse_timestamp_or_none(value: str) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return _parse_timestamp(normalized)


def _persist_snapshot_publication(
    *,
    database_url: str,
    payload: dict[str, Any],
    snapshot_path: str,
) -> None:
    generated_at = _parse_timestamp(str(payload.get("generated_at") or _serialize_timestamp(datetime.now(UTC))))
    record_keys = sorted(
        [
            str(key).strip()
            for key in dict(payload.get("records", {})).keys()
            if str(key).strip()
        ]
    ) if isinstance(payload.get("records"), dict) else []
    source_keys = sorted(
        [
            str(key).strip()
            for key in dict(payload.get("sources", {})).keys()
            if str(key).strip()
        ]
    ) if isinstance(payload.get("sources"), dict) else []
    source_counts: dict[str, int] = {}
    if isinstance(payload.get("records"), dict):
        for item in dict(payload.get("records", {})).values():
            if not isinstance(item, dict):
                continue
            source_name = str(item.get("evidence_source") or "").strip()
            if not source_name:
                continue
            source_counts[source_name] = int(source_counts.get(source_name, 0)) + 1
    checksum = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    revision = f"recognition-intelligence-{generated_at.strftime('%Y%m%d%H%M%S')}"
    with get_session(database_url) as session:
        repository = CatalogRepository(session)
        repository.upsert_recognition_snapshot_publication(
            revision=revision,
            checksum=checksum,
            generated_at=generated_at,
            records_total=len(record_keys),
            source_keys_json=source_keys,
            source_run_ids_json=[
                str(item).strip()
                for item in list(payload.get("source_run_ids") or [])
                if str(item).strip()
            ],
            record_keys_json=record_keys,
            metadata_json={
                "snapshot_path": snapshot_path,
                "source_failures": list(payload.get("source_failures") or []),
                "source_counts": source_counts,
            },
        )
        session.commit()


def main(daemon: bool = False) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger("magick_ai_cloud.recognition_evidence_refresh")

    if not daemon:
        summary = run_once(settings)
        logger.info("recognition evidence refreshed: %s", summary)
        return

    # Daemon mode: run in a loop with heartbeat
    from app.core.db import require_database_connection
    from app.workers.heartbeat import WorkerHeartbeat
    from app.workers.model_intelligence_publisher import run_once as run_model_intelligence_publisher
    import time

    require_database_connection(settings.database_url)
    heartbeat = WorkerHeartbeat(
        settings=settings,
        worker_id="recognition_evidence",
        interval_seconds=settings.worker_heartbeat_interval_seconds,
    )
    cycles = 0
    logger.info(
        "recognition evidence daemon started (enabled=%s, poll=%ss)",
        settings.recognition_evidence_worker_enabled,
        settings.recognition_evidence_worker_poll_seconds,
    )
    heartbeat.maybe_record(
        status="started",
        payload={
            "recognition_enabled": settings.recognition_evidence_worker_enabled,
            "publisher_enabled": settings.model_intelligence_publisher_enabled,
        },
        force=True,
    )

    while True:
        cycle_status = "idle"
        payload: dict[str, object] = {
            "recognition_enabled": settings.recognition_evidence_worker_enabled,
            "publisher_enabled": settings.model_intelligence_publisher_enabled,
        }
        if settings.recognition_evidence_worker_enabled:
            summary = run_once(settings)
            logger.info("recognition evidence refresh cycle completed: %s", summary)
            payload["recognition_refresh"] = summary
            cycle_status = "processed"
        else:
            logger.info("recognition evidence daemon idle: worker disabled")

        if settings.model_intelligence_publisher_enabled:
            publisher_summary = run_model_intelligence_publisher(settings)
            logger.info("model intelligence publisher cycle completed: %s", publisher_summary)
            payload["model_intelligence_publisher"] = publisher_summary
            cycle_status = "processed"
        else:
            logger.info("model intelligence publisher idle: worker disabled")

        heartbeat.maybe_record(status=cycle_status, payload=payload)

        cycles += 1
        time.sleep(settings.recognition_evidence_worker_poll_seconds)


def _serialize_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    normalized = str(value or "").strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized).astimezone(UTC)


def _load_fresh_snapshot_if_available(
    *,
    snapshot_path: str,
    now: datetime,
    min_refresh_seconds: int,
) -> dict[str, Any] | None:
    path = Path(snapshot_path)
    if not path.exists():
        return None
    payload = load_active_upstream_evidence_payload(path)
    generated_at = str(payload.get("generated_at") or "").strip()
    if not generated_at:
        return None
    try:
        snapshot_time = _parse_timestamp(generated_at)
    except ValueError:
        return None
    age_seconds = max(0.0, (now - snapshot_time).total_seconds())
    if age_seconds >= float(max(min_refresh_seconds, 60)):
        return None
    return payload


def _build_litellm_importer(
    settings: Settings,
) -> LiteLLMRecognitionEvidenceImporter | None:
    base_url = str(settings.litellm_base_url or "").strip()
    if not base_url:
        return None

    return LiteLLMRecognitionEvidenceImporter(
        base_url=base_url,
        api_key=settings.litellm_api_key,
        timeout_seconds=settings.litellm_timeout_seconds,
        app_name=settings.project_name,
    )


def _build_huggingface_importer(
    settings: Settings,
) -> HuggingFaceRecognitionEvidenceImporter | None:
    repo_ids = [
        repo_id.strip()
        for repo_id in str(settings.huggingface_model_allowlist or "").split(",")
        if repo_id.strip()
    ]
    if not repo_ids:
        return None

    return HuggingFaceRecognitionEvidenceImporter(
        repo_ids=repo_ids,
        base_url=settings.huggingface_base_url,
        api_token=settings.huggingface_api_token,
        timeout_seconds=settings.huggingface_timeout_seconds,
        app_name=settings.project_name,
    )


def _build_openrouter_importer(
    settings: Settings,
) -> OpenRouterRecognitionEvidenceImporter | None:
    if not settings.openrouter_recognition_enabled:
        return None

    return OpenRouterRecognitionEvidenceImporter(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        timeout_seconds=settings.openrouter_timeout_seconds,
        app_name=settings.project_name,
        site_url=settings.openrouter_site_url,
    )


def _build_siliconflow_importer(
    settings: Settings,
) -> SiliconFlowRecognitionEvidenceImporter | None:
    if not settings.siliconflow_recognition_enabled:
        return None
    pricing_url = str(settings.siliconflow_pricing_url or "").strip()
    if not pricing_url:
        return None
    return SiliconFlowRecognitionEvidenceImporter(
        pricing_url=pricing_url,
        timeout_seconds=settings.siliconflow_timeout_seconds,
        app_name=settings.project_name,
        cny_per_usd=settings.recognition_price_cny_per_usd,
    )


def _build_ollama_importer(
    settings: Settings,
) -> OllamaRecognitionEvidenceImporter | None:
    base_url = str(settings.ollama_base_url or "").strip()
    model_names = [
        model_name.strip()
        for model_name in str(settings.ollama_model_allowlist or "").split(",")
        if model_name.strip()
    ]
    if not base_url or (not model_names and not settings.ollama_catalog_enabled):
        return None

    return OllamaRecognitionEvidenceImporter(
        model_names=model_names,
        base_url=base_url,
        api_key=settings.ollama_api_key,
        catalog_enabled=settings.ollama_catalog_enabled,
        catalog_limit=settings.ollama_catalog_limit,
        timeout_seconds=settings.ollama_timeout_seconds,
        app_name=settings.project_name,
    )


def _describe_importer_mix(
    has_litellm: bool,
    has_openrouter: bool,
    has_siliconflow: bool,
    has_hf: bool,
    has_ollama: bool,
) -> str:
    enabled = []
    if has_litellm:
        enabled.append("litellm")
    if has_openrouter:
        enabled.append("openrouter")
    if has_siliconflow:
        enabled.append("siliconflow")
    if has_hf:
        enabled.append("huggingface")
    if has_ollama:
        enabled.append("ollama")
    if not enabled:
        return "bundled_seed"
    if len(enabled) == 1:
        return f"{enabled[0]}_importer"
    return "_and_".join(enabled) + "_importers"


if __name__ == "__main__":
    import sys
    daemon_mode = "--daemon" in sys.argv
    main(daemon=daemon_mode)
