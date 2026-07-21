from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, desc, func, select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.models import (
    MediaArtifact,
    MediaArtifactDelivery,
    MediaDerivativeJobMetric,
    RunRecord,
)
from app.domain.media_derivatives.processor import MediaDerivativeResult


def _delivery_completed_predicate(current_time: datetime) -> Any:
    return and_(
        MediaArtifactDelivery.completed_at.is_not(None),
        MediaArtifactDelivery.completed_at <= current_time,
        MediaArtifactDelivery.completed_byte_size
        == MediaArtifactDelivery.expected_byte_size,
        MediaArtifactDelivery.completed_checksum == MediaArtifactDelivery.expected_checksum,
    )


def _delivery_acknowledged_predicate(current_time: datetime) -> Any:
    return and_(
        _delivery_completed_predicate(current_time),
        MediaArtifactDelivery.acked_at.is_not(None),
        MediaArtifactDelivery.acked_at <= current_time,
        MediaArtifactDelivery.acked_at >= MediaArtifactDelivery.completed_at,
        MediaArtifactDelivery.byte_size_verified.is_(True),
        MediaArtifactDelivery.checksum_verified.is_(True),
        MediaArtifactDelivery.received_byte_size
        == MediaArtifactDelivery.expected_byte_size,
        MediaArtifactDelivery.received_checksum == MediaArtifactDelivery.expected_checksum,
    )


def _delivery_count_columns(current_time: datetime) -> tuple[Any, Any, Any]:
    return (
        func.count(func.distinct(MediaArtifactDelivery.delivery_id)),
        func.count(
            func.distinct(
                case(
                    (
                        _delivery_completed_predicate(current_time),
                        MediaArtifactDelivery.delivery_id,
                    ),
                    else_=None,
                )
            )
        ),
        func.count(
            func.distinct(
                case(
                    (
                        _delivery_acknowledged_predicate(current_time),
                        MediaArtifactDelivery.delivery_id,
                    ),
                    else_=None,
                )
            )
        ),
    )


def record_media_derivative_job_metric(
    *,
    session: Session,
    run: RunRecord,
    target_format: str,
    source_media_type: str,
    source_bytes: int,
    processing_started_at: datetime,
    result: MediaDerivativeResult | None = None,
    artifact: MediaArtifact | None = None,
    error_code: str = "",
    watermark_applied: bool = False,
) -> MediaDerivativeJobMetric:
    finished_at = _to_utc(run.finished_at) or datetime.now(UTC)
    run_started_at = _to_utc(run.started_at) or processing_started_at
    started_processing_at = _to_utc(run.processing_started_at) or processing_started_at
    output_bytes = int(result.filesize_bytes if result is not None else 0)
    compression_ratio = (
        (int(source_bytes) - output_bytes) / max(1, int(source_bytes)) if source_bytes else 0.0
    )
    metric = session.scalar(
        select(MediaDerivativeJobMetric).where(MediaDerivativeJobMetric.run_id == run.run_id)
    )
    if metric is None:
        metric = MediaDerivativeJobMetric(run_id=run.run_id)
        session.add(metric)

    metric.site_id = run.site_id
    metric.account_id = run.account_id or None
    metric.subscription_id = run.subscription_id or None
    metric.status = run.status
    metric.error_code = error_code or run.error_code or None
    metric.target_format = target_format
    metric.output_format = result.format if result is not None else None
    metric.source_media_type = source_media_type
    metric.source_bytes = int(source_bytes or 0)
    metric.output_bytes = output_bytes
    metric.source_width = int(result.source_width if result is not None else 0)
    metric.source_height = int(result.source_height if result is not None else 0)
    metric.output_width = int(result.width if result is not None else 0)
    metric.output_height = int(result.height if result is not None else 0)
    metric.compression_ratio = float(compression_ratio)
    metric.queue_wait_ms = _duration_ms(run_started_at, started_processing_at)
    metric.processing_duration_ms = _duration_ms(processing_started_at, finished_at)
    metric.total_duration_ms = _duration_ms(run_started_at, finished_at)
    metric.watermark_applied = bool(watermark_applied)
    metric.warnings_count = len(result.processing_warnings) if result is not None else 0
    metric.artifact_id = artifact.artifact_id if artifact is not None else None
    metric.artifact_expires_at = artifact.expires_at if artifact is not None else None
    metric.finished_at = finished_at
    session.flush()
    return metric


class MediaDerivativeObservabilityService:
    def __init__(
        self,
        database_url: str,
        *,
        site_queued_limit: int = 100,
        site_running_limit: int = 2,
        default_chunk_size: int = 10,
    ) -> None:
        self.database_url = database_url
        self.site_queued_limit = max(1, int(site_queued_limit))
        self.site_running_limit = max(1, int(site_running_limit))
        self.default_chunk_size = max(1, int(default_chunk_size))

    def get_summary(
        self,
        *,
        window_hours: int = 24,
        site_id: str = "",
        target_format: str = "",
        now: datetime | None = None,
    ) -> dict[str, object]:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        bounded_hours = min(168, max(1, int(window_hours or 24)))
        start_at = current_time - timedelta(hours=bounded_hours)

        with get_session(self.database_url) as session:
            base_conditions = [
                MediaDerivativeJobMetric.created_at >= start_at,
                MediaDerivativeJobMetric.created_at <= current_time,
            ]
            artifact_conditions = [
                MediaArtifact.operation == "image.transform.v1",
                MediaArtifact.created_at <= current_time,
                MediaArtifact.expires_at > current_time,
                MediaArtifact.purged_at.is_(None),
            ]
            if site_id:
                base_conditions.append(MediaDerivativeJobMetric.site_id == site_id)
                artifact_conditions.append(MediaArtifact.site_id == site_id)
            if target_format:
                base_conditions.append(MediaDerivativeJobMetric.target_format == target_format)

            delivery_conditions = [
                MediaArtifactDelivery.started_at >= start_at,
                MediaArtifactDelivery.started_at <= current_time,
            ]
            if site_id:
                delivery_conditions.append(MediaArtifactDelivery.site_id == site_id)

            def delivery_statement(*columns: Any) -> Any:
                statement = (
                    select(*columns)
                    .select_from(MediaArtifactDelivery)
                    .join(
                        MediaArtifact,
                        and_(
                            MediaArtifact.artifact_id == MediaArtifactDelivery.artifact_id,
                            MediaArtifact.site_id == MediaArtifactDelivery.site_id,
                        ),
                    )
                    .where(*delivery_conditions)
                )
                if target_format:
                    statement = statement.join(
                        MediaDerivativeJobMetric,
                        MediaDerivativeJobMetric.artifact_id == MediaArtifact.artifact_id,
                    ).where(MediaDerivativeJobMetric.target_format == target_format)
                return statement

            delivery_totals_row = session.execute(
                delivery_statement(*_delivery_count_columns(current_time))
            ).one()
            delivery_operation_rows = session.execute(
                delivery_statement(
                    MediaArtifact.operation,
                    *_delivery_count_columns(current_time),
                )
                .group_by(MediaArtifact.operation)
                .order_by(MediaArtifact.operation.asc())
            ).all()
            delivery_site_count_columns = _delivery_count_columns(current_time)
            delivery_site_rows = session.execute(
                delivery_statement(
                    MediaArtifactDelivery.site_id,
                    *delivery_site_count_columns,
                )
                .group_by(MediaArtifactDelivery.site_id)
                .order_by(
                    delivery_site_count_columns[0].desc(),
                    MediaArtifactDelivery.site_id.asc(),
                )
                .limit(51)
            ).all()
            delivery_site_truncated = len(delivery_site_rows) > 50
            delivery_site_rows = delivery_site_rows[:50]
            if session.get_bind().dialect.name == "postgresql":
                delivery_utc_date = func.date(
                    func.timezone("UTC", MediaArtifactDelivery.started_at)
                )
            else:
                # SQLite tests persist application-normalized UTC timestamps.
                delivery_utc_date = func.date(MediaArtifactDelivery.started_at)
            delivery_date_rows = session.execute(
                delivery_statement(
                    delivery_utc_date,
                    *_delivery_count_columns(current_time),
                )
                .group_by(delivery_utc_date)
                .order_by(delivery_utc_date.asc())
            ).all()

            totals_row = session.execute(
                select(
                    func.count(MediaDerivativeJobMetric.id),
                    func.sum(case((MediaDerivativeJobMetric.status == "succeeded", 1), else_=0)),
                    func.sum(case((MediaDerivativeJobMetric.status == "failed", 1), else_=0)),
                    func.avg(MediaDerivativeJobMetric.processing_duration_ms),
                    func.avg(MediaDerivativeJobMetric.queue_wait_ms),
                    func.sum(MediaDerivativeJobMetric.source_bytes),
                    func.sum(MediaDerivativeJobMetric.output_bytes),
                    func.max(MediaDerivativeJobMetric.finished_at),
                    func.count(func.distinct(MediaDerivativeJobMetric.site_id)),
                    func.count(func.distinct(MediaDerivativeJobMetric.account_id)),
                    func.sum(
                        case((MediaDerivativeJobMetric.watermark_applied.is_(True), 1), else_=0)
                    ),
                ).where(*base_conditions)
            ).one()

            storage_statement = select(
                func.count(MediaArtifact.artifact_id),
                func.sum(MediaArtifact.byte_size),
            ).where(*artifact_conditions)
            if target_format:
                storage_statement = storage_statement.join(
                    MediaDerivativeJobMetric,
                    MediaDerivativeJobMetric.artifact_id == MediaArtifact.artifact_id,
                ).where(MediaDerivativeJobMetric.target_format == target_format)
            storage_row = session.execute(storage_statement).one()

            format_rows = session.execute(
                select(
                    MediaDerivativeJobMetric.target_format,
                    func.count(MediaDerivativeJobMetric.id),
                    func.sum(case((MediaDerivativeJobMetric.status == "succeeded", 1), else_=0)),
                    func.sum(case((MediaDerivativeJobMetric.status == "failed", 1), else_=0)),
                    func.sum(MediaDerivativeJobMetric.source_bytes),
                    func.sum(MediaDerivativeJobMetric.output_bytes),
                    func.avg(MediaDerivativeJobMetric.processing_duration_ms),
                )
                .where(*base_conditions)
                .group_by(MediaDerivativeJobMetric.target_format)
                .order_by(desc(func.count(MediaDerivativeJobMetric.id)))
            ).all()

            site_rows = session.execute(
                select(
                    MediaDerivativeJobMetric.site_id,
                    func.count(MediaDerivativeJobMetric.id),
                    func.sum(case((MediaDerivativeJobMetric.status == "succeeded", 1), else_=0)),
                    func.sum(case((MediaDerivativeJobMetric.status == "failed", 1), else_=0)),
                    func.sum(MediaDerivativeJobMetric.source_bytes),
                    func.sum(MediaDerivativeJobMetric.output_bytes),
                    func.avg(MediaDerivativeJobMetric.processing_duration_ms),
                    func.max(MediaDerivativeJobMetric.finished_at),
                )
                .where(*base_conditions)
                .group_by(MediaDerivativeJobMetric.site_id)
                .order_by(desc(func.count(MediaDerivativeJobMetric.id)))
                .limit(50)
            ).all()

            error_rows = session.execute(
                select(
                    MediaDerivativeJobMetric.error_code,
                    func.count(MediaDerivativeJobMetric.id),
                    func.max(MediaDerivativeJobMetric.finished_at),
                )
                .where(
                    *base_conditions,
                    MediaDerivativeJobMetric.status == "failed",
                    MediaDerivativeJobMetric.error_code.is_not(None),
                    MediaDerivativeJobMetric.error_code != "",
                )
                .group_by(MediaDerivativeJobMetric.error_code)
                .order_by(desc(func.count(MediaDerivativeJobMetric.id)))
                .limit(25)
            ).all()

            recent_failures = list(
                session.scalars(
                    select(MediaDerivativeJobMetric)
                    .where(*base_conditions, MediaDerivativeJobMetric.status == "failed")
                    .order_by(MediaDerivativeJobMetric.finished_at.desc())
                    .limit(10)
                )
            )

            timeline_metrics = list(
                session.scalars(
                    select(MediaDerivativeJobMetric)
                    .where(*base_conditions)
                    .order_by(MediaDerivativeJobMetric.created_at.asc())
                )
            )
            active_runs_conditions = [
                RunRecord.execution_kind == "media_derivative",
                RunRecord.status.in_(("queued", "running")),
            ]
            batch_run_conditions = [
                RunRecord.execution_kind == "media_derivative",
                RunRecord.started_at >= start_at,
                RunRecord.started_at <= current_time,
            ]
            if site_id:
                active_runs_conditions.append(RunRecord.site_id == site_id)
                batch_run_conditions.append(RunRecord.site_id == site_id)
            active_runs = list(
                session.scalars(
                    select(RunRecord)
                    .where(*active_runs_conditions)
                    .order_by(RunRecord.started_at.asc())
                    .limit(500)
                )
            )
            batch_runs = list(
                session.scalars(
                    select(RunRecord)
                    .where(*batch_run_conditions)
                    .order_by(RunRecord.started_at.asc())
                    .limit(1000)
                )
            )

        totals = self._build_totals(
            totals_row,
            storage_row=storage_row,
            timeline_metrics=timeline_metrics,
            delivery_totals_row=delivery_totals_row,
        )
        formats = [self._format_summary(row) for row in format_rows]
        sites = [self._site_summary(row) for row in site_rows]
        errors = [self._error_summary(row) for row in error_rows]
        return {
            "contract_version": "magick-media-observability-summary-v2",
            "generated_at": self._format_datetime(current_time),
            "window": {
                "hours": bounded_hours,
                "start_at": self._format_datetime(start_at),
                "end_at": self._format_datetime(current_time),
            },
            "totals": totals,
            "delivery_evidence": {
                "evidence_scope": "verified_transfer_only",
                "cohort_time_field": "started_at",
                "stream_completed_semantics": "cloud_stream_completed",
                "acknowledged_semantics": "verified_client_receipt",
                "cms_write_evidence": False,
                "by_site_limit": 50,
                "by_site_truncated": delivery_site_truncated,
                "by_operation": [
                    self._delivery_breakdown(row, dimension="operation")
                    for row in delivery_operation_rows
                ],
                "by_site": [
                    self._delivery_breakdown(row, dimension="site_id") for row in delivery_site_rows
                ],
                "by_date": [
                    self._delivery_breakdown(row, dimension="date") for row in delivery_date_rows
                ],
            },
            "health": self._build_health(totals),
            "queue": self._queue_summary(active_runs),
            "batch": self._batch_summary(batch_runs, target_format=target_format),
            "timeline": self._build_timeline(
                timeline_metrics,
                start_at=start_at,
                end_at=current_time,
                window_hours=bounded_hours,
            ),
            "formats": formats,
            "sites": sites,
            "errors": errors,
            "recent_failures": [self._recent_failure(metric) for metric in recent_failures],
        }

    def _queue_summary(self, active_runs: list[RunRecord]) -> dict[str, object]:
        sites: dict[str, dict[str, int]] = defaultdict(lambda: {"queued": 0, "running": 0})
        queued_total = 0
        running_total = 0
        for run in active_runs:
            site = str(run.site_id or "")
            if run.status == "queued":
                queued_total += 1
                sites[site]["queued"] += 1
            elif run.status == "running":
                running_total += 1
                sites[site]["running"] += 1
        site_items = []
        for site_id, counts in sites.items():
            queued = int(counts.get("queued") or 0)
            running = int(counts.get("running") or 0)
            pressure_state = "healthy"
            reasons: list[str] = []
            if queued >= self.site_queued_limit:
                pressure_state = "rejecting"
                reasons.append("site_media_derivative_queue_full")
            elif running >= self.site_running_limit:
                pressure_state = "attention"
                reasons.append("site_media_derivative_running_saturated")
            site_items.append(
                {
                    "site_id": site_id,
                    "queued": queued,
                    "running": running,
                    "pressure_state": pressure_state,
                    "pressure_reasons": reasons,
                }
            )
        site_items.sort(
            key=lambda item: (
                0 if item["pressure_state"] == "rejecting" else 1,
                -_int_or_zero(item.get("queued")) - _int_or_zero(item.get("running")),
                str(item["site_id"]),
            )
        )
        return {
            "queued_total": queued_total,
            "running_total": running_total,
            "active_site_count": len(site_items),
            "limits": {
                "site_queued": self.site_queued_limit,
                "site_running": self.site_running_limit,
            },
            "sites": site_items[:50],
        }

    def _batch_summary(
        self,
        runs: list[RunRecord],
        *,
        target_format: str = "",
    ) -> dict[str, object]:
        batches: dict[str, dict[str, object]] = {}
        for run in runs:
            policy = run.policy_json if isinstance(run.policy_json, dict) else {}
            media_policy_value = policy.get("media_derivative")
            media_policy = media_policy_value if isinstance(media_policy_value, dict) else {}
            batch_context_value = media_policy.get("batch_context")
            batch_context = batch_context_value if isinstance(batch_context_value, dict) else {}
            batch_id = str(batch_context.get("batch_id") or "")
            if not batch_id:
                continue
            run_target_format = str(media_policy.get("target_format") or "")
            if target_format and run_target_format != target_format:
                continue
            entry = batches.setdefault(
                batch_id,
                {
                    "batch_id": batch_id,
                    "site_id": str(run.site_id or ""),
                    "target_format": run_target_format,
                    "item_count": _int_or_zero(batch_context.get("item_count")),
                    "chunk_size": _int_or_zero(batch_context.get("chunk_size"))
                    or self.default_chunk_size,
                    "queued": 0,
                    "running": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "seen_runs": 0,
                },
            )
            entry["seen_runs"] = _int_or_zero(entry.get("seen_runs")) + 1
            if run.status == "queued":
                entry["queued"] = _int_or_zero(entry.get("queued")) + 1
            elif run.status == "running":
                entry["running"] = _int_or_zero(entry.get("running")) + 1
            elif run.status == "succeeded":
                entry["succeeded"] = _int_or_zero(entry.get("succeeded")) + 1
            elif run.status == "failed":
                entry["failed"] = _int_or_zero(entry.get("failed")) + 1
        items = list(batches.values())
        items.sort(
            key=lambda item: (
                -_int_or_zero(item.get("queued")) - _int_or_zero(item.get("running")),
                str(item.get("batch_id") or ""),
            )
        )
        return {
            "active_or_recent_batch_count": len(items),
            "default_chunk_size": self.default_chunk_size,
            "items": items[:50],
        }

    def _build_totals(
        self,
        row: Any,
        *,
        storage_row: Any,
        timeline_metrics: list[MediaDerivativeJobMetric],
        delivery_totals_row: Any,
    ) -> dict[str, object]:
        jobs_total = int(row[0] or 0)
        succeeded_total = int(row[1] or 0)
        failed_total = int(row[2] or 0)
        source_bytes = int(row[5] or 0)
        output_bytes = int(row[6] or 0)
        bytes_saved = source_bytes - output_bytes
        delivery_counts = self._delivery_counts(delivery_totals_row)
        return {
            "jobs_total": jobs_total,
            "succeeded_total": succeeded_total,
            "failed_total": failed_total,
            "success_rate": self._success_rate(jobs_total, failed_total),
            "avg_processing_duration_ms": self._optional_avg(row[3]),
            "p95_processing_duration_ms": self._p95(
                [int(metric.processing_duration_ms or 0) for metric in timeline_metrics]
            ),
            "avg_queue_wait_ms": self._optional_avg(row[4]),
            "source_bytes_total": source_bytes,
            "output_bytes_total": output_bytes,
            "bytes_saved_total": bytes_saved,
            "compression_ratio": bytes_saved / max(1, source_bytes) if source_bytes else 0.0,
            **delivery_counts,
            "last_finished_at": self._format_datetime(row[7]),
            "active_site_count": int(row[8] or 0),
            "active_account_count": int(row[9] or 0),
            "watermark_job_count": int(row[10] or 0),
            "active_artifact_count": int(storage_row[0] or 0),
            "active_artifact_bytes": int(storage_row[1] or 0),
        }

    def _delivery_breakdown(self, row: Any, *, dimension: str) -> dict[str, object]:
        return {
            dimension: str(row[0] or ""),
            **self._delivery_counts(row, offset=1),
        }

    def _delivery_counts(self, row: Any, *, offset: int = 0) -> dict[str, object]:
        started = int(row[offset] or 0)
        completed = int(row[offset + 1] or 0)
        acknowledged = int(row[offset + 2] or 0)
        return self._delivery_counts_from_values(started, completed, acknowledged)

    def _delivery_counts_from_values(
        self,
        started: int,
        completed: int,
        acknowledged: int,
    ) -> dict[str, object]:
        return {
            "delivery_started_count": started,
            "delivery_stream_completed_count": completed,
            "delivery_acknowledged_count": acknowledged,
            "stream_completion_rate": self._ratio(completed, started),
            "acknowledgement_rate": self._ratio(acknowledged, completed),
        }

    def _ratio(self, numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(numerator / denominator, 4)

    def _format_summary(self, row: Any) -> dict[str, object]:
        jobs_total = int(row[1] or 0)
        succeeded_total = int(row[2] or 0)
        failed_total = int(row[3] or 0)
        source_bytes = int(row[4] or 0)
        output_bytes = int(row[5] or 0)
        bytes_saved = source_bytes - output_bytes
        return {
            "target_format": str(row[0] or ""),
            "jobs_total": jobs_total,
            "succeeded_total": succeeded_total,
            "failed_total": failed_total,
            "success_rate": self._success_rate(jobs_total, failed_total),
            "source_bytes_total": source_bytes,
            "output_bytes_total": output_bytes,
            "bytes_saved_total": bytes_saved,
            "compression_ratio": bytes_saved / max(1, source_bytes) if source_bytes else 0.0,
            "avg_processing_duration_ms": self._optional_avg(row[6]),
        }

    def _site_summary(self, row: Any) -> dict[str, object]:
        jobs_total = int(row[1] or 0)
        succeeded_total = int(row[2] or 0)
        failed_total = int(row[3] or 0)
        source_bytes = int(row[4] or 0)
        output_bytes = int(row[5] or 0)
        bytes_saved = source_bytes - output_bytes
        return {
            "site_id": str(row[0] or ""),
            "jobs_total": jobs_total,
            "succeeded_total": succeeded_total,
            "failed_total": failed_total,
            "success_rate": self._success_rate(jobs_total, failed_total),
            "source_bytes_total": source_bytes,
            "output_bytes_total": output_bytes,
            "bytes_saved_total": bytes_saved,
            "compression_ratio": bytes_saved / max(1, source_bytes) if source_bytes else 0.0,
            "avg_processing_duration_ms": self._optional_avg(row[6]),
            "last_finished_at": self._format_datetime(row[7]),
        }

    def _error_summary(self, row: Any) -> dict[str, object]:
        return {
            "error_code": str(row[0] or ""),
            "count": int(row[1] or 0),
            "last_seen_at": self._format_datetime(row[2]),
        }

    def _recent_failure(self, metric: MediaDerivativeJobMetric) -> dict[str, object]:
        return {
            "run_id": metric.run_id,
            "site_id": metric.site_id,
            "target_format": metric.target_format,
            "error_code": metric.error_code or "",
            "source_bytes": int(metric.source_bytes or 0),
            "queue_wait_ms": int(metric.queue_wait_ms or 0),
            "processing_duration_ms": int(metric.processing_duration_ms or 0),
            "finished_at": self._format_datetime(metric.finished_at),
        }

    def _build_health(self, totals: dict[str, object]) -> dict[str, object]:
        jobs_total = _int_or_zero(totals.get("jobs_total"))
        failed_total = _int_or_zero(totals.get("failed_total"))
        p95 = _int_or_zero(totals.get("p95_processing_duration_ms"))
        active_artifact_bytes = _int_or_zero(totals.get("active_artifact_bytes"))
        if jobs_total == 0:
            return {
                "status": "inactive",
                "score": 0,
                "summary": "No media processing jobs in this window.",
            }
        failure_rate = failed_total / max(1, jobs_total)
        score = 100
        if failure_rate >= 0.10:
            score -= 35
        elif failure_rate >= 0.03:
            score -= 15
        if p95 >= 15000:
            score -= 20
        elif p95 >= 8000:
            score -= 10
        if active_artifact_bytes >= 512 * 1024 * 1024:
            score -= 10
        status = "ok"
        if score < 70:
            status = "error"
        elif score < 90:
            status = "warning"
        return {
            "status": status,
            "score": max(0, score),
            "summary": (f"{jobs_total} jobs, {failure_rate * 100:.1f}% failed, P95 {p95} ms."),
        }

    def _build_timeline(
        self,
        metrics: list[MediaDerivativeJobMetric],
        *,
        start_at: datetime,
        end_at: datetime,
        window_hours: int,
    ) -> list[dict[str, object]]:
        bucket_count = min(24, max(1, int(window_hours or 24)))
        bucket_seconds = max(3600, int((end_at - start_at).total_seconds() / bucket_count))
        buckets: dict[int, dict[str, int]] = defaultdict(
            lambda: {
                "jobs_total": 0,
                "failed_total": 0,
                "source_bytes_total": 0,
                "output_bytes_total": 0,
            }
        )
        for metric in metrics:
            created_at = _to_utc(metric.created_at) or start_at
            offset = max(0, int((created_at - start_at).total_seconds()))
            bucket_index = min(bucket_count - 1, offset // bucket_seconds)
            bucket = buckets[int(bucket_index)]
            bucket["jobs_total"] += 1
            if metric.status == "failed":
                bucket["failed_total"] += 1
            bucket["source_bytes_total"] += int(metric.source_bytes or 0)
            bucket["output_bytes_total"] += int(metric.output_bytes or 0)

        timeline = []
        for index in range(bucket_count):
            bucket_start = start_at + timedelta(seconds=bucket_seconds * index)
            bucket = buckets[index]
            timeline.append(
                {
                    "bucket_start_at": self._format_datetime(bucket_start),
                    "jobs_total": bucket["jobs_total"],
                    "failed_total": bucket["failed_total"],
                    "bytes_saved_total": (
                        bucket["source_bytes_total"] - bucket["output_bytes_total"]
                    ),
                }
            )
        return timeline

    def _success_rate(self, total: int, failed: int) -> float:
        if total <= 0:
            return 0.0
        return round((total - failed) / total, 4)

    def _optional_avg(self, value: Any) -> int:
        if value is None:
            return 0
        return int(round(float(value)))

    def _p95(self, values: list[int]) -> int:
        clean_values = sorted(value for value in values if value >= 0)
        if not clean_values:
            return 0
        index = int((len(clean_values) - 1) * 0.95)
        return clean_values[index]

    def _format_datetime(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            normalized = _to_utc(value)
            return normalized.isoformat().replace("+00:00", "Z") if normalized is not None else ""
        return str(value)


def _int_or_zero(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _duration_ms(start_at: datetime | None, end_at: datetime | None) -> int:
    if start_at is None or end_at is None:
        return 0
    return max(0, int((end_at - start_at).total_seconds() * 1000))


def _to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
