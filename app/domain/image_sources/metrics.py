from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

from sqlalchemy import case, func, select

from app.core.db import get_session
from app.core.models import ProviderCallRecord, RunRecord
from app.domain.image_sources.contracts import IMAGE_SOURCE_ABILITIES


class ProviderMetricsRow(NamedTuple):
    provider_id: object
    call_count: object
    error_count: object
    latency_total_ms: object
    cost_total: object
    last_seen_at: datetime | None


class ImageSourceMetricsService:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def get_summary(
        self,
        *,
        site_id: str | None = None,
        window_hours: int = 24,
        now: datetime | None = None,
    ) -> dict[str, object]:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        bounded_hours = min(168, max(1, int(window_hours or 24)))
        start_at = current_time - timedelta(hours=bounded_hours)

        with get_session(self.database_url) as session:
            run_statement = select(RunRecord).where(
                RunRecord.ability_name.in_(IMAGE_SOURCE_ABILITIES),
                RunRecord.started_at >= start_at,
                RunRecord.started_at <= current_time,
            )
            if site_id:
                run_statement = run_statement.where(RunRecord.site_id == site_id)
            runs = list(
                session.scalars(
                    run_statement.order_by(
                        RunRecord.started_at.desc(),
                        RunRecord.run_id.desc(),
                    ).limit(5000)
                )
            )

            call_statement = (
                select(
                    ProviderCallRecord.provider_id,
                    func.count(ProviderCallRecord.id),
                    func.sum(
                        case(
                            (
                                ProviderCallRecord.error_code.is_not(None)
                                & (ProviderCallRecord.error_code != ""),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    func.sum(ProviderCallRecord.latency_ms),
                    func.sum(ProviderCallRecord.cost),
                    func.max(ProviderCallRecord.created_at),
                )
                .join(RunRecord, ProviderCallRecord.run_id == RunRecord.run_id)
                .where(
                    RunRecord.ability_name.in_(IMAGE_SOURCE_ABILITIES),
                    RunRecord.started_at >= start_at,
                    RunRecord.started_at <= current_time,
                )
            )
            if site_id:
                call_statement = call_statement.where(RunRecord.site_id == site_id)
            provider_rows = [
                ProviderMetricsRow(
                    provider_id=provider_id,
                    call_count=call_count,
                    error_count=error_count,
                    latency_total_ms=latency_total,
                    cost_total=cost_total,
                    last_seen_at=last_seen_at if isinstance(last_seen_at, datetime) else None,
                )
                for (
                    provider_id,
                    call_count,
                    error_count,
                    latency_total,
                    cost_total,
                    last_seen_at,
                ) in session.execute(
                    call_statement.group_by(ProviderCallRecord.provider_id).order_by(
                        func.count(ProviderCallRecord.id).desc(),
                        ProviderCallRecord.provider_id.asc(),
                    )
                ).all()
            ]

        return self._build_summary(
            site_id=site_id or "",
            window_hours=bounded_hours,
            start_at=start_at,
            current_time=current_time,
            runs=runs,
            provider_rows=provider_rows,
        )

    def _build_summary(
        self,
        *,
        site_id: str,
        window_hours: int,
        start_at: datetime,
        current_time: datetime,
        runs: list[RunRecord],
        provider_rows: list[ProviderMetricsRow],
    ) -> dict[str, object]:
        fast_first_runs = [run for run in runs if self._latency_mode(run) == "fast_first"]
        deferred_runs = [run for run in runs if self._has_deferred_enrichment(run)]
        provider_summaries = [
            self._finalize_provider_group(
                {
                    "provider_id": str(row.provider_id or "unknown").strip() or "unknown",
                    "calls": self._coerce_int(row.call_count),
                    "errors": self._coerce_int(row.error_count),
                    "latency_total_ms": self._coerce_int(row.latency_total_ms),
                    "cost_total": self._coerce_float(row.cost_total),
                    "last_seen_at": self._format_datetime(row.last_seen_at),
                }
            )
            for row in provider_rows
        ]

        recent_runs = [self._run_summary(run) for run in runs[:20]]
        total_runs = len(runs)
        total_provider_calls = sum(
            self._coerce_int(provider.get("calls")) for provider in provider_summaries
        )
        total_provider_errors = sum(
            self._coerce_int(provider.get("errors")) for provider in provider_summaries
        )
        latency_total = sum(
            self._coerce_int(row.latency_total_ms) for row in provider_rows
        )
        totals = {
            "runs": total_runs,
            "succeeded": sum(1 for run in runs if run.status == "succeeded"),
            "failed": sum(1 for run in runs if run.status == "failed"),
            "fast_first_runs": len(fast_first_runs),
            "complete_runs": max(0, total_runs - len(fast_first_runs)),
            "deferred_enrichment_runs": len(deferred_runs),
            "provider_calls": total_provider_calls,
            "provider_errors": total_provider_errors,
            "avg_provider_latency_ms": self._average_int(
                [latency_total],
                denominator=total_provider_calls,
            ),
        }
        return {
            "contract_version": "image-source-readonly-metrics.v1",
            "generated_at": self._format_datetime(current_time),
            "filters": {
                "site_id": site_id,
                "window_hours": window_hours,
            },
            "window": {
                "start_at": self._format_datetime(start_at),
                "end_at": self._format_datetime(current_time),
                "hours": window_hours,
            },
            "totals": totals,
            "rates": {
                "fast_first_rate": self._rate(len(fast_first_runs), total_runs),
                "deferred_enrichment_rate": self._rate(len(deferred_runs), total_runs),
                "provider_error_rate": self._rate(total_provider_errors, total_provider_calls),
            },
            "providers": provider_summaries,
            "recent_runs": recent_runs,
            "boundary": {
                "surface": "internal_admin_readonly",
                "cloud_role": "image_source_runtime_detail",
                "local_control_plane": "wordpress_plugin",
                "direct_wordpress_write": False,
                "contains_prompt_or_result_payloads": False,
                "contains_provider_secrets": False,
            },
        }

    def _run_summary(self, run: RunRecord) -> dict[str, object]:
        result = self._dict_or_empty(run.result_json)
        visual_brief = self._dict_or_empty(result.get("visual_brief"))
        active_sources = self._dict_list(result.get("active_sources"))
        return {
            "run_id": run.run_id,
            "site_id": run.site_id,
            "status": run.status,
            "latency_mode": self._latency_mode(run),
            "deferred_enrichment": self._has_deferred_enrichment(run),
            "resolved_provider": str(result.get("resolved_provider") or ""),
            "candidate_count": sum(self._coerce_int(item.get("count")) for item in active_sources),
            "query_chars": self._coerce_int(result.get("query_chars")),
            "site_context_status": str(visual_brief.get("site_context_status") or ""),
            "llm_prompt_planner_status": str(
                visual_brief.get("llm_prompt_planner_status") or ""
            ),
            "error_code": str(run.error_code or ""),
            "started_at": self._format_datetime(run.started_at),
            "finished_at": self._format_datetime(run.finished_at),
        }

    def _latency_mode(self, run: RunRecord) -> str:
        input_payload = self._dict_or_empty(run.input_json)
        visual_context = self._dict_or_empty(input_payload.get("visual_context"))
        result = self._dict_or_empty(run.result_json)
        visual_brief = self._dict_or_empty(result.get("visual_brief"))
        source_context = self._dict_or_empty(visual_brief.get("source_context"))
        latency_mode = str(
            input_payload.get("latency_mode")
            or visual_context.get("latency_mode")
            or source_context.get("latency_mode")
            or ""
        ).strip().lower()
        return "fast_first" if latency_mode == "fast_first" else "complete"

    def _has_deferred_enrichment(self, run: RunRecord) -> bool:
        input_payload = self._dict_or_empty(run.input_json)
        if str(input_payload.get("enhancement_mode") or "").strip().lower() == "deferred":
            return True
        result = self._dict_or_empty(run.result_json)
        visual_brief = self._dict_or_empty(result.get("visual_brief"))
        return (
            str(visual_brief.get("site_context_status") or "").strip().lower()
            == "deferred"
            or str(visual_brief.get("llm_prompt_planner_status") or "").strip().lower()
            == "deferred"
        )

    def _finalize_provider_group(self, group: dict[str, object]) -> dict[str, object]:
        calls = self._coerce_int(group.get("calls"))
        errors = self._coerce_int(group.get("errors"))
        latency_total = self._coerce_int(group.get("latency_total_ms"))
        return {
            "provider_id": str(group.get("provider_id") or ""),
            "calls": calls,
            "errors": errors,
            "error_rate": self._rate(errors, calls),
            "avg_latency_ms": self._average_int([latency_total], denominator=calls),
            "cost_total": round(self._coerce_float(group.get("cost_total")), 6),
            "last_seen_at": str(group.get("last_seen_at") or ""),
        }

    @staticmethod
    def _dict_or_empty(value: object) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _dict_list(value: object) -> list[dict[str, Any]]:
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @staticmethod
    def _coerce_int(value: object) -> int:
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
                return 0
        return 0

    @staticmethod
    def _coerce_float(value: object) -> float:
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return 0.0
        return 0.0

    @staticmethod
    def _average_int(values: list[int], *, denominator: int | None = None) -> int:
        if denominator is not None:
            return int(round((values[0] if values else 0) / denominator)) if denominator else 0
        return int(round(sum(values) / len(values))) if values else 0

    @staticmethod
    def _rate(numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(numerator / denominator, 4)

    @classmethod
    def _max_timestamp(cls, current: str, candidate: datetime | None) -> str:
        candidate_text = cls._format_datetime(candidate)
        if not current:
            return candidate_text
        return max(current, candidate_text)

    @staticmethod
    def _format_datetime(value: datetime | None) -> str:
        if value is None:
            return ""
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return normalized.astimezone(UTC).isoformat().replace("+00:00", "Z")
