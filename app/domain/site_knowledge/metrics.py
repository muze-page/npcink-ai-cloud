from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.config import Settings
from app.core.db import get_session
from app.core.models import (
    RunRecord,
    SiteKnowledgeIndexJobMetric,
    SiteKnowledgeIndexSnapshot,
    SiteKnowledgeSearchMetric,
)
from app.domain.commercial.credits import AI_CREDIT_RATE_VERSION, vector_credit_component
from app.domain.site_knowledge.contracts import (
    SITE_KNOWLEDGE_SEARCH_ABILITY,
    SITE_KNOWLEDGE_STATUS_ABILITY,
    SITE_KNOWLEDGE_SYNC_ABILITY,
)
from app.domain.site_knowledge.repository import SiteKnowledgeRepository


def record_site_knowledge_run_metric(
    *,
    session: Session,
    run: RunRecord,
    input_payload: dict[str, Any],
    result_json: dict[str, Any],
    execution_started_at: datetime,
    settings: Settings,
) -> None:
    finished_at = _to_utc(run.finished_at) or datetime.now(UTC)
    if run.ability_name == SITE_KNOWLEDGE_SYNC_ABILITY:
        _record_index_job_metric(
            session=session,
            run=run,
            input_payload=input_payload,
            result_json=result_json,
            execution_started_at=execution_started_at,
            finished_at=finished_at,
            settings=settings,
        )
        _record_index_snapshot(
            session=session,
            run=run,
            settings=settings,
            captured_at=finished_at,
        )
    elif run.ability_name == SITE_KNOWLEDGE_SEARCH_ABILITY:
        _record_search_metric(
            session=session,
            run=run,
            input_payload=input_payload,
            result_json=result_json,
            execution_started_at=execution_started_at,
            finished_at=finished_at,
            settings=settings,
        )
    elif run.ability_name == SITE_KNOWLEDGE_STATUS_ABILITY:
        _record_index_snapshot(
            session=session,
            run=run,
            settings=settings,
            captured_at=finished_at,
        )
    session.flush()


def record_site_knowledge_failure_metric(
    *,
    session: Session,
    run: RunRecord,
    input_payload: dict[str, Any],
    error_code: str,
    execution_started_at: datetime,
    settings: Settings,
) -> None:
    finished_at = _to_utc(run.finished_at) or datetime.now(UTC)
    if run.ability_name == SITE_KNOWLEDGE_SYNC_ABILITY:
        _record_index_job_metric(
            session=session,
            run=run,
            input_payload=input_payload,
            result_json={},
            execution_started_at=execution_started_at,
            finished_at=finished_at,
            settings=settings,
            status="failed",
            error_code=error_code,
        )
    elif run.ability_name == SITE_KNOWLEDGE_SEARCH_ABILITY:
        _record_search_metric(
            session=session,
            run=run,
            input_payload=input_payload,
            result_json={},
            execution_started_at=execution_started_at,
            finished_at=finished_at,
            settings=settings,
            status="failed",
            error_code=error_code,
        )
    session.flush()


class SiteKnowledgeObservabilityService:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def get_summary(
        self,
        *,
        window_hours: int = 24,
        site_id: str = "",
        now: datetime | None = None,
    ) -> dict[str, object]:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        bounded_hours = min(168, max(1, int(window_hours or 24)))
        start_at = current_time - timedelta(hours=bounded_hours)

        with get_session(self.database_url) as session:
            index_conditions = [
                SiteKnowledgeIndexJobMetric.created_at >= start_at,
                SiteKnowledgeIndexJobMetric.created_at <= current_time,
            ]
            search_conditions = [
                SiteKnowledgeSearchMetric.created_at >= start_at,
                SiteKnowledgeSearchMetric.created_at <= current_time,
            ]
            snapshot_conditions = [
                SiteKnowledgeIndexSnapshot.captured_at <= current_time,
            ]
            if site_id:
                index_conditions.append(SiteKnowledgeIndexJobMetric.site_id == site_id)
                search_conditions.append(SiteKnowledgeSearchMetric.site_id == site_id)
                snapshot_conditions.append(SiteKnowledgeIndexSnapshot.site_id == site_id)

            index_row = session.execute(
                select(
                    func.count(SiteKnowledgeIndexJobMetric.id),
                    func.sum(case((SiteKnowledgeIndexJobMetric.status == "succeeded", 1), else_=0)),
                    func.sum(case((SiteKnowledgeIndexJobMetric.status == "failed", 1), else_=0)),
                    func.sum(SiteKnowledgeIndexJobMetric.accepted_documents),
                    func.sum(SiteKnowledgeIndexJobMetric.indexed_documents),
                    func.sum(SiteKnowledgeIndexJobMetric.indexed_chunks),
                    func.sum(SiteKnowledgeIndexJobMetric.failed_documents),
                    func.sum(SiteKnowledgeIndexJobMetric.deleted_entries),
                    func.avg(SiteKnowledgeIndexJobMetric.duration_ms),
                    func.max(SiteKnowledgeIndexJobMetric.finished_at),
                    func.count(func.distinct(SiteKnowledgeIndexJobMetric.site_id)),
                ).where(*index_conditions)
            ).one()

            search_row = session.execute(
                select(
                    func.count(SiteKnowledgeSearchMetric.id),
                    func.sum(case((SiteKnowledgeSearchMetric.status == "succeeded", 1), else_=0)),
                    func.sum(case((SiteKnowledgeSearchMetric.status == "failed", 1), else_=0)),
                    func.sum(case((SiteKnowledgeSearchMetric.no_hit.is_(True), 1), else_=0)),
                    func.avg(SiteKnowledgeSearchMetric.latency_ms),
                    func.avg(SiteKnowledgeSearchMetric.top1_score),
                    func.avg(SiteKnowledgeSearchMetric.avg_score),
                    func.max(SiteKnowledgeSearchMetric.finished_at),
                    func.count(func.distinct(SiteKnowledgeSearchMetric.site_id)),
                ).where(*search_conditions)
            ).one()

            latest_snapshots = self._latest_snapshots(session, snapshot_conditions)
            index_metrics = list(
                session.scalars(
                    select(SiteKnowledgeIndexJobMetric)
                    .where(*index_conditions)
                    .order_by(SiteKnowledgeIndexJobMetric.created_at.asc())
                )
            )
            search_metrics = list(
                session.scalars(
                    select(SiteKnowledgeSearchMetric)
                    .where(*search_conditions)
                    .order_by(SiteKnowledgeSearchMetric.created_at.asc())
                )
            )
            intent_rows = session.execute(
                select(
                    SiteKnowledgeSearchMetric.intent,
                    func.count(SiteKnowledgeSearchMetric.id),
                    func.sum(case((SiteKnowledgeSearchMetric.no_hit.is_(True), 1), else_=0)),
                    func.avg(SiteKnowledgeSearchMetric.top1_score),
                    func.avg(SiteKnowledgeSearchMetric.latency_ms),
                )
                .where(*search_conditions)
                .group_by(SiteKnowledgeSearchMetric.intent)
                .order_by(desc(func.count(SiteKnowledgeSearchMetric.id)))
            ).all()
            site_rows = session.execute(
                select(
                    SiteKnowledgeSearchMetric.site_id,
                    func.count(SiteKnowledgeSearchMetric.id),
                    func.sum(case((SiteKnowledgeSearchMetric.no_hit.is_(True), 1), else_=0)),
                    func.avg(SiteKnowledgeSearchMetric.top1_score),
                    func.avg(SiteKnowledgeSearchMetric.latency_ms),
                    func.max(SiteKnowledgeSearchMetric.finished_at),
                )
                .where(*search_conditions)
                .group_by(SiteKnowledgeSearchMetric.site_id)
                .order_by(desc(func.count(SiteKnowledgeSearchMetric.id)))
                .limit(50)
            ).all()
            error_rows = session.execute(
                select(
                    SiteKnowledgeSearchMetric.error_code,
                    func.count(SiteKnowledgeSearchMetric.id),
                    func.max(SiteKnowledgeSearchMetric.finished_at),
                )
                .where(
                    *search_conditions,
                    SiteKnowledgeSearchMetric.status == "failed",
                    SiteKnowledgeSearchMetric.error_code.is_not(None),
                    SiteKnowledgeSearchMetric.error_code != "",
                )
                .group_by(SiteKnowledgeSearchMetric.error_code)
                .order_by(desc(func.count(SiteKnowledgeSearchMetric.id)))
                .limit(25)
            ).all()

        totals = self._build_totals(
            index_row=index_row,
            search_row=search_row,
            latest_snapshots=latest_snapshots,
            index_metrics=index_metrics,
            search_metrics=search_metrics,
        )
        return {
            "contract_version": "magick-vector-observability-summary-v1",
            "generated_at": self._format_datetime(current_time),
            "window": {
                "hours": bounded_hours,
                "start_at": self._format_datetime(start_at),
                "end_at": self._format_datetime(current_time),
            },
            "totals": totals,
            "health": self._build_health(totals),
            "timeline": self._build_timeline(
                index_metrics=index_metrics,
                search_metrics=search_metrics,
                start_at=start_at,
                end_at=current_time,
                window_hours=bounded_hours,
            ),
            "intents": [self._intent_summary(row) for row in intent_rows],
            "sites": [
                self._site_summary(row, latest_snapshots=latest_snapshots) for row in site_rows
            ],
            "index_snapshots": [
                self._snapshot_summary(snapshot) for snapshot in latest_snapshots.values()
            ],
            "errors": [self._error_summary(row) for row in error_rows],
        }

    def _latest_snapshots(
        self,
        session: Session,
        conditions: list[Any],
    ) -> dict[str, SiteKnowledgeIndexSnapshot]:
        snapshots = list(
            session.scalars(
                select(SiteKnowledgeIndexSnapshot)
                .where(*conditions)
                .order_by(
                    SiteKnowledgeIndexSnapshot.site_id.asc(),
                    SiteKnowledgeIndexSnapshot.captured_at.desc(),
                    SiteKnowledgeIndexSnapshot.id.desc(),
                )
            )
        )
        latest: dict[str, SiteKnowledgeIndexSnapshot] = {}
        for snapshot in snapshots:
            latest.setdefault(snapshot.site_id, snapshot)
        return latest

    def _build_totals(
        self,
        *,
        index_row: Any,
        search_row: Any,
        latest_snapshots: dict[str, SiteKnowledgeIndexSnapshot],
        index_metrics: list[SiteKnowledgeIndexJobMetric],
        search_metrics: list[SiteKnowledgeSearchMetric],
    ) -> dict[str, object]:
        index_jobs_total = int(index_row[0] or 0)
        index_failed_total = int(index_row[2] or 0)
        search_queries_total = int(search_row[0] or 0)
        search_failed_total = int(search_row[2] or 0)
        no_hit_total = int(search_row[3] or 0)
        document_count = sum(
            int(snapshot.document_count or 0) for snapshot in latest_snapshots.values()
        )
        chunk_count = sum(int(snapshot.chunk_count or 0) for snapshot in latest_snapshots.values())
        return {
            "index_jobs_total": index_jobs_total,
            "index_succeeded_total": int(index_row[1] or 0),
            "index_failed_total": index_failed_total,
            "index_success_rate": self._success_rate(index_jobs_total, index_failed_total),
            "accepted_documents_total": int(index_row[3] or 0),
            "indexed_documents_total": int(index_row[4] or 0),
            "indexed_chunks_total": int(index_row[5] or 0),
            "failed_documents_total": int(index_row[6] or 0),
            "deleted_entries_total": int(index_row[7] or 0),
            "avg_index_duration_ms": self._optional_avg(index_row[8]),
            "p95_index_duration_ms": self._p95(
                [int(metric.duration_ms or 0) for metric in index_metrics]
            ),
            "last_index_job_finished_at": self._format_datetime(index_row[9]),
            "search_queries_total": search_queries_total,
            "search_succeeded_total": int(search_row[1] or 0),
            "search_failed_total": search_failed_total,
            "search_success_rate": self._success_rate(search_queries_total, search_failed_total),
            "no_hit_total": no_hit_total,
            "no_hit_rate": round(no_hit_total / max(1, search_queries_total), 4)
            if search_queries_total
            else 0.0,
            "avg_search_latency_ms": self._optional_avg(search_row[4]),
            "p95_search_latency_ms": self._p95(
                [int(metric.latency_ms or 0) for metric in search_metrics]
            ),
            "avg_top1_score": round(float(search_row[5] or 0.0), 4),
            "avg_result_score": round(float(search_row[6] or 0.0), 4),
            "last_search_finished_at": self._format_datetime(search_row[7]),
            "active_site_count": max(int(index_row[10] or 0), int(search_row[8] or 0)),
            "indexed_site_count": len(latest_snapshots),
            "current_document_count": document_count,
            "current_chunk_count": chunk_count,
        }

    def _intent_summary(self, row: Any) -> dict[str, object]:
        queries_total = int(row[1] or 0)
        no_hit_total = int(row[2] or 0)
        return {
            "intent": str(row[0] or ""),
            "queries_total": queries_total,
            "no_hit_total": no_hit_total,
            "no_hit_rate": round(no_hit_total / max(1, queries_total), 4) if queries_total else 0.0,
            "avg_top1_score": round(float(row[3] or 0.0), 4),
            "avg_latency_ms": self._optional_avg(row[4]),
        }

    def _site_summary(
        self,
        row: Any,
        *,
        latest_snapshots: dict[str, SiteKnowledgeIndexSnapshot],
    ) -> dict[str, object]:
        site_id = str(row[0] or "")
        queries_total = int(row[1] or 0)
        no_hit_total = int(row[2] or 0)
        snapshot = latest_snapshots.get(site_id)
        return {
            "site_id": site_id,
            "queries_total": queries_total,
            "no_hit_total": no_hit_total,
            "no_hit_rate": round(no_hit_total / max(1, queries_total), 4) if queries_total else 0.0,
            "avg_top1_score": round(float(row[3] or 0.0), 4),
            "avg_latency_ms": self._optional_avg(row[4]),
            "last_search_finished_at": self._format_datetime(row[5]),
            "document_count": int(snapshot.document_count or 0) if snapshot else 0,
            "chunk_count": int(snapshot.chunk_count or 0) if snapshot else 0,
            "last_indexed_at": self._format_datetime(snapshot.last_indexed_at) if snapshot else "",
        }

    def _snapshot_summary(self, snapshot: SiteKnowledgeIndexSnapshot) -> dict[str, object]:
        return {
            "site_id": snapshot.site_id,
            "document_count": int(snapshot.document_count or 0),
            "chunk_count": int(snapshot.chunk_count or 0),
            "post_type_counts": snapshot.post_type_counts_json or {},
            "source_type_counts": snapshot.source_type_counts_json or {},
            "last_indexed_at": self._format_datetime(snapshot.last_indexed_at),
            "embedding_provider": snapshot.embedding_provider,
            "embedding_model": snapshot.embedding_model,
            "embedding_dimensions": int(snapshot.embedding_dimensions or 0),
            "vector_backend": snapshot.vector_backend,
            "captured_at": self._format_datetime(snapshot.captured_at),
        }

    def _error_summary(self, row: Any) -> dict[str, object]:
        return {
            "error_code": str(row[0] or ""),
            "count": int(row[1] or 0),
            "last_seen_at": self._format_datetime(row[2]),
        }

    def _build_health(self, totals: dict[str, object]) -> dict[str, object]:
        queries_total = _coerce_int(totals.get("search_queries_total"), default=0)
        index_jobs_total = _coerce_int(totals.get("index_jobs_total"), default=0)
        no_hit_rate = _coerce_float(totals.get("no_hit_rate"), default=0.0)
        search_failures = _coerce_int(totals.get("search_failed_total"), default=0)
        index_failures = _coerce_int(totals.get("index_failed_total"), default=0)
        p95_latency = _coerce_int(totals.get("p95_search_latency_ms"), default=0)
        if queries_total == 0 and index_jobs_total == 0:
            return {
                "status": "inactive",
                "score": 0,
                "summary": "No site knowledge activity in this window.",
            }
        score = 100
        if search_failures or index_failures:
            score -= 25
        if no_hit_rate >= 0.5:
            score -= 25
        elif no_hit_rate >= 0.25:
            score -= 10
        if p95_latency >= 3000:
            score -= 15
        elif p95_latency >= 1200:
            score -= 8
        status = "ok"
        if score < 70:
            status = "error"
        elif score < 90:
            status = "warning"
        return {
            "status": status,
            "score": max(0, score),
            "summary": (
                f"{queries_total} searches, {no_hit_rate * 100:.1f}% no-hit, P95 {p95_latency} ms."
            ),
        }

    def _build_timeline(
        self,
        *,
        index_metrics: list[SiteKnowledgeIndexJobMetric],
        search_metrics: list[SiteKnowledgeSearchMetric],
        start_at: datetime,
        end_at: datetime,
        window_hours: int,
    ) -> list[dict[str, object]]:
        bucket_count = min(24, max(1, int(window_hours or 24)))
        bucket_seconds = max(3600, int((end_at - start_at).total_seconds() / bucket_count))
        buckets: dict[int, dict[str, int]] = defaultdict(
            lambda: {
                "index_jobs_total": 0,
                "indexed_chunks_total": 0,
                "search_queries_total": 0,
                "no_hit_total": 0,
                "failed_total": 0,
            }
        )
        for metric in index_metrics:
            bucket = buckets[
                self._bucket_index(metric.created_at, start_at, bucket_count, bucket_seconds)
            ]
            bucket["index_jobs_total"] += 1
            bucket["indexed_chunks_total"] += int(metric.indexed_chunks or 0)
            if metric.status == "failed":
                bucket["failed_total"] += 1
        for search_metric in search_metrics:
            bucket = buckets[
                self._bucket_index(search_metric.created_at, start_at, bucket_count, bucket_seconds)
            ]
            bucket["search_queries_total"] += 1
            if search_metric.no_hit:
                bucket["no_hit_total"] += 1
            if search_metric.status == "failed":
                bucket["failed_total"] += 1

        timeline = []
        for index in range(bucket_count):
            bucket_start = start_at + timedelta(seconds=bucket_seconds * index)
            bucket = buckets[index]
            timeline.append(
                {
                    "bucket_start_at": self._format_datetime(bucket_start),
                    "index_jobs_total": bucket["index_jobs_total"],
                    "indexed_chunks_total": bucket["indexed_chunks_total"],
                    "search_queries_total": bucket["search_queries_total"],
                    "no_hit_total": bucket["no_hit_total"],
                    "failed_total": bucket["failed_total"],
                }
            )
        return timeline

    def _bucket_index(
        self,
        value: datetime | None,
        start_at: datetime,
        bucket_count: int,
        bucket_seconds: int,
    ) -> int:
        created_at = _to_utc(value) or start_at
        offset = max(0, int((created_at - start_at).total_seconds()))
        return min(bucket_count - 1, offset // bucket_seconds)

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
            resolved = _to_utc(value)
            if resolved is None:
                return ""
            return resolved.isoformat().replace("+00:00", "Z")
        return str(value)


def _record_index_job_metric(
    *,
    session: Session,
    run: RunRecord,
    input_payload: dict[str, Any],
    result_json: dict[str, Any],
    execution_started_at: datetime,
    finished_at: datetime,
    settings: Settings,
    status: str | None = None,
    error_code: str = "",
) -> None:
    metric = session.scalar(
        select(SiteKnowledgeIndexJobMetric).where(SiteKnowledgeIndexJobMetric.run_id == run.run_id)
    )
    if metric is None:
        metric = SiteKnowledgeIndexJobMetric(run_id=run.run_id)
        session.add(metric)
    sync_value = result_json.get("sync")
    sync = sync_value if isinstance(sync_value, dict) else {}
    sync_mode = str(sync.get("sync_mode") or input_payload.get("sync_mode") or "refresh")
    metric.site_id = run.site_id
    metric.account_id = run.account_id or None
    metric.subscription_id = run.subscription_id or None
    metric.status = status or run.status
    metric.error_code = error_code or run.error_code or None
    metric.sync_mode = sync_mode[:32]
    metric.accepted_documents = _coerce_int(sync.get("accepted_documents"), default=0)
    metric.indexed_documents = _coerce_int(sync.get("indexed_documents"), default=0)
    metric.indexed_chunks = _coerce_int(sync.get("indexed_chunks"), default=0)
    metric.failed_documents = _coerce_int(sync.get("failed_documents"), default=0)
    metric.deleted_entries = _coerce_int(sync.get("deleted_entries"), default=0)
    metric.embedding_provider = _embedding_provider(settings)
    metric.embedding_model = _embedding_model(settings)
    metric.embedding_dimensions = _embedding_dimensions(settings)
    metric.vector_backend = _vector_backend(settings)
    metric.duration_ms = _duration_ms(execution_started_at, finished_at)
    metric.finished_at = finished_at
    session.flush()
    _record_index_credit_ledger_entries(session=session, run=run, metric=metric)


def _record_index_credit_ledger_entries(
    *,
    session: Session,
    run: RunRecord,
    metric: SiteKnowledgeIndexJobMetric,
) -> None:
    repository = CommercialRepository(session)
    for source_type, quantity in (
        ("vector_documents", metric.indexed_documents),
        ("vector_chunks", metric.indexed_chunks),
    ):
        component = vector_credit_component(source_type=source_type, quantity=quantity)
        if component is None:
            continue
        credits = float(component.get("credits") or 0.0)
        repository.record_credit_ledger_entry(
            account_id=metric.account_id or run.account_id,
            site_id=metric.site_id or run.site_id,
            subscription_id=metric.subscription_id or run.subscription_id,
            plan_version_id=run.plan_version_id,
            run_id=metric.run_id,
            provider_call_id=None,
            source_type=source_type,
            source_id=metric.run_id,
            credit_delta=-credits,
            quantity=float(component.get("quantity") or 0.0),
            unit=str(component.get("unit") or "credit"),
            rate=float(component.get("rate") or 0.0),
            rate_unit=(
                str(component.get("rate_unit"))
                if component.get("rate_unit") is not None
                else None
            ),
            rate_version=AI_CREDIT_RATE_VERSION,
            idempotency_key=f"site_knowledge_index:{metric.run_id}:{source_type}",
            metadata_json={
                "site_knowledge_index_metric_id": int(metric.id or 0),
                "sync_mode": str(metric.sync_mode or ""),
                "status": str(metric.status or ""),
            },
            created_at=metric.finished_at or metric.created_at,
        )


def _record_search_metric(
    *,
    session: Session,
    run: RunRecord,
    input_payload: dict[str, Any],
    result_json: dict[str, Any],
    execution_started_at: datetime,
    finished_at: datetime,
    settings: Settings,
    status: str | None = None,
    error_code: str = "",
) -> None:
    metric = session.scalar(
        select(SiteKnowledgeSearchMetric).where(SiteKnowledgeSearchMetric.run_id == run.run_id)
    )
    if metric is None:
        metric = SiteKnowledgeSearchMetric(run_id=run.run_id)
        session.add(metric)
    results_value = result_json.get("results")
    results = results_value if isinstance(results_value, list) else []
    scores = [
        _coerce_float(item.get("score"), default=0.0) for item in results if isinstance(item, dict)
    ]
    query = " ".join(str(input_payload.get("query") or "").split())
    metric.site_id = run.site_id
    metric.account_id = run.account_id or None
    metric.subscription_id = run.subscription_id or None
    metric.status = status or run.status
    metric.error_code = error_code or run.error_code or None
    metric.intent = str(result_json.get("intent") or input_payload.get("intent") or "site_search")[
        :64
    ]
    metric.result_count = len(results)
    metric.no_hit = len(results) == 0
    metric.top1_score = round(float(scores[0] if scores else 0.0), 4)
    metric.avg_score = round(sum(scores) / len(scores), 4) if scores else 0.0
    metric.query_hash = _query_hash(query) if query else None
    metric.query_chars = len(query)
    metric.max_results = _coerce_positive_int(
        input_payload.get("max_results"),
        default=8,
        maximum=20,
    )
    metric.filter_json = _safe_filter_summary(input_payload.get("filters"))
    metric.embedding_provider = _embedding_provider(settings)
    metric.embedding_model = _embedding_model(settings)
    metric.embedding_dimensions = _embedding_dimensions(settings)
    metric.vector_backend = _vector_backend(settings)
    metric.latency_ms = _duration_ms(execution_started_at, finished_at)
    metric.finished_at = finished_at


def _record_index_snapshot(
    *,
    session: Session,
    run: RunRecord,
    settings: Settings,
    captured_at: datetime,
) -> None:
    repository = SiteKnowledgeRepository(session)
    session.add(
        SiteKnowledgeIndexSnapshot(
            site_id=run.site_id,
            run_id=run.run_id,
            document_count=repository.count_documents(run.site_id),
            chunk_count=repository.count_chunks(run.site_id),
            post_type_counts_json=repository.post_type_counts(run.site_id),
            source_type_counts_json=repository.source_type_counts(run.site_id),
            last_indexed_at=repository.last_sync_at(run.site_id),
            embedding_provider=_embedding_provider(settings),
            embedding_model=_embedding_model(settings),
            embedding_dimensions=_embedding_dimensions(settings),
            vector_backend=_vector_backend(settings),
            captured_at=captured_at,
        )
    )


def _safe_filter_summary(value: Any) -> dict[str, object]:
    filters = value if isinstance(value, dict) else {}
    return {
        "post_types": _safe_string_list(filters.get("post_types"), limit=12),
        "status": _safe_string_list(filters.get("status"), limit=8),
        "source_types": _safe_string_list(filters.get("source_types"), limit=8),
    }


def _safe_string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:64] for item in value[:limit] if str(item).strip()]


def _query_hash(query: str) -> str:
    return hashlib.sha256(query.lower().encode("utf-8")).hexdigest()


def _embedding_provider(settings: Settings) -> str:
    return str(settings.site_knowledge_embedding_provider or "deterministic")[:64]


def _embedding_model(settings: Settings) -> str:
    return str(settings.site_knowledge_embedding_model or "BAAI/bge-m3")[:191]


def _embedding_dimensions(settings: Settings) -> int:
    return int(settings.site_knowledge_embedding_dimensions or 0)


def _vector_backend(settings: Settings) -> str:
    return str(settings.site_knowledge_vector_backend or "local")[:64]


def _coerce_positive_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number <= 0:
        return default
    return min(number, maximum)


def _coerce_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _coerce_float(value: object, *, default: float) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _duration_ms(start_at: datetime | None, end_at: datetime | None) -> int:
    if start_at is None or end_at is None:
        return 0
    resolved_start = _to_utc(start_at)
    resolved_end = _to_utc(end_at)
    if resolved_start is None or resolved_end is None:
        return 0
    return max(0, int((resolved_end - resolved_start).total_seconds() * 1000))


def _to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
