from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.db import get_session
from app.core.models import UsageMeterEvent
from app.domain.agent_feedback.contracts import (
    AGENT_FEEDBACK_CONTRACT_VERSION,
    AGENT_FEEDBACK_EVENT_KIND,
    AGENT_FEEDBACK_EXECUTION_KIND,
    AGENT_FEEDBACK_METER_PREFIX,
)

AGENT_FEEDBACK_SUMMARY_MAX_EVENTS = 5000


class AgentFeedbackService:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def record_event(
        self,
        *,
        site_id: str,
        idempotency_key: str,
        trace_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        source_runtime = str(payload.get("source_runtime") or "agent").strip()
        local_outcome = str(payload.get("local_outcome") or "").strip()
        labels = self._string_list(payload.get("feedback_labels"))
        event_payload = {
            **payload,
            "site_id": site_id,
            "feedback_labels": labels,
            "redaction_status": self._redaction_status(payload),
            "cloud_feedback_policy": {
                "accepted_for_eval": True,
                "quality_rollup_candidate": True,
                "production_mutation": False,
                "approval_truth": "wordpress_local",
                "preflight_truth": "wordpress_local",
                "final_write_truth": "wordpress_local",
            },
        }
        dedupe_key = f"agent-feedback:{site_id}:{idempotency_key}"

        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            event = repository.record_usage_meter_event(
                account_id=None,
                site_id=site_id,
                subscription_id=None,
                plan_version_id=None,
                run_id=str(payload.get("source_run_id") or "") or None,
                provider_call_id=None,
                event_kind=AGENT_FEEDBACK_EVENT_KIND,
                meter_key=f"{AGENT_FEEDBACK_METER_PREFIX}.{source_runtime}"[:64],
                quantity=1.0,
                ability_family="knowledge" if source_runtime == "site_knowledge" else "agent",
                channel=str(payload.get("local_surface") or "") or None,
                execution_kind=AGENT_FEEDBACK_EXECUTION_KIND,
                execution_tier="cloud",
                data_classification="internal",
                currency=None,
                dedupe_key=dedupe_key,
                payload_json=event_payload,
            )
            session.commit()
            event_id = int(event.id)
            created_at = event.created_at

        return {
            "artifact_type": "cloud_agent_feedback_receipt",
            "contract_version": str(payload.get("contract_version") or ""),
            "feedback_event_id": event_id,
            "site_id": site_id,
            "agent_id": str(payload.get("agent_id") or ""),
            "source_runtime": source_runtime,
            "local_outcome": local_outcome,
            "feedback_labels": labels,
            "accepted_for_eval": True,
            "quality_rollup_candidate": True,
            "production_mutation": False,
            "approval_truth": "wordpress_local",
            "preflight_truth": "wordpress_local",
            "final_write_truth": "wordpress_local",
            "stored_as": "usage_meter_event",
            "created_at": self._format_datetime(created_at),
            "trace_id": trace_id,
        }

    def get_summary(self, *, site_id: str | None, window_hours: int) -> dict[str, Any]:
        window_hours = max(1, min(168, int(window_hours or 24)))
        since = datetime.now(UTC) - timedelta(hours=window_hours)

        with get_session(self.database_url) as session:
            query = (
                select(UsageMeterEvent)
                .where(UsageMeterEvent.event_kind == AGENT_FEEDBACK_EVENT_KIND)
                .where(UsageMeterEvent.created_at >= since)
                .order_by(UsageMeterEvent.created_at.desc(), UsageMeterEvent.id.desc())
                .limit(AGENT_FEEDBACK_SUMMARY_MAX_EVENTS + 1)
            )
            if site_id:
                query = query.where(UsageMeterEvent.site_id == site_id)
            events = list(
                session.scalars(query)
            )
        limited = len(events) > AGENT_FEEDBACK_SUMMARY_MAX_EVENTS
        if limited:
            events = events[:AGENT_FEEDBACK_SUMMARY_MAX_EVENTS]

        outcomes: dict[str, int] = {}
        labels: dict[str, int] = {}
        source_runtimes: dict[str, int] = {}
        local_surfaces: dict[str, int] = {}
        trend: dict[str, dict[str, int]] = {}
        scenarios: dict[str, dict[str, Any]] = {}
        rejection_reasons: dict[str, int] = {}
        for event in events:
            payload = event.payload_json if isinstance(event.payload_json, dict) else {}
            outcome = str(payload.get("local_outcome") or "unknown").strip() or "unknown"
            source_runtime = str(payload.get("source_runtime") or "unknown").strip() or "unknown"
            local_surface = str(payload.get("local_surface") or "unknown").strip() or "unknown"
            feedback_labels = self._string_list(payload.get("feedback_labels"))
            self._increment(outcomes, outcome)
            self._increment(source_runtimes, source_runtime)
            self._increment(local_surfaces, local_surface)
            self._increment_trend_bucket(trend, event.created_at, outcome, feedback_labels)
            self._increment_scenario(
                scenarios,
                local_surface,
                source_runtime,
                outcome,
                feedback_labels,
            )
            for label in feedback_labels:
                self._increment(labels, label)
                if self._is_rejected_outcome(outcome):
                    self._increment(rejection_reasons, label)

        total = len(events)
        last_event_at = events[0].created_at if events else None
        return {
            "artifact_type": "cloud_agent_feedback_summary",
            "contract_version": AGENT_FEEDBACK_CONTRACT_VERSION,
            "site_id": site_id or "",
            "scope": "site" if site_id else "all_sites",
            "window_hours": window_hours,
            "generated_at": self._format_datetime(datetime.now(UTC)),
            "window_start_at": self._format_datetime(since),
            "last_event_at": self._format_datetime(last_event_at) if last_event_at else "",
            "events_total": total,
            "limited": limited,
            "max_events": AGENT_FEEDBACK_SUMMARY_MAX_EVENTS,
            "outcomes": outcomes,
            "labels": labels,
            "source_runtimes": source_runtimes,
            "local_surfaces": local_surfaces,
            "scenarios": self._scenario_summary(scenarios),
            "quality_trend": self._trend_summary(trend),
            "low_quality_labels": self._top_counts(
                labels,
                allowed={
                    "evidence_weak",
                    "wrong_intent",
                    "wrong_next_step",
                    "missing_context",
                    "wrong_priority",
                    "already_handled",
                    "unsafe_or_overreaching",
                    "too_generic",
                    "duplicate_suggestion",
                    "not_relevant_to_site",
                    "operator_confidence_low",
                },
            ),
            "rejection_reasons": self._top_counts(rejection_reasons),
            "nightly_inspection": self._nightly_inspection_summary(events),
            "rates": {
                "accepted_rate": self._rate(
                    outcomes.get("accepted", 0) + outcomes.get("edited_before_accept", 0),
                    total,
                ),
                "evidence_useful_rate": self._rate(labels.get("evidence_useful", 0), total),
                "evidence_weak_rate": self._rate(labels.get("evidence_weak", 0), total),
                "wrong_next_step_rate": self._rate(labels.get("wrong_next_step", 0), total),
            },
            "production_mutation": False,
            "approval_truth": "wordpress_local",
            "preflight_truth": "wordpress_local",
            "final_write_truth": "wordpress_local",
        }

    def _nightly_inspection_summary(self, events: list[UsageMeterEvent]) -> dict[str, Any]:
        outcomes: dict[str, int] = {}
        labels: dict[str, int] = {}
        reason_codes: dict[str, int] = {}
        rejected_reason_codes: dict[str, int] = {}
        severities: dict[str, int] = {}
        action_ids: set[str] = set()
        score_sum = 0
        score_count = 0

        for event in events:
            payload = event.payload_json if isinstance(event.payload_json, dict) else {}
            source_runtime = str(payload.get("source_runtime") or "").strip()
            local_surface = str(payload.get("local_surface") or "").strip()
            if source_runtime != "nightly_site_inspection" and "nightly" not in local_surface:
                continue

            outcome = str(payload.get("local_outcome") or "unknown").strip() or "unknown"
            source_action_id = str(payload.get("source_action_id") or "").strip()
            source_severity = str(payload.get("source_severity") or "").strip()
            source_score = payload.get("source_score")
            feedback_labels = self._string_list(payload.get("feedback_labels"))
            source_reasons = self._string_list(payload.get("source_reason_codes"))

            self._increment(outcomes, outcome)
            for label in feedback_labels:
                self._increment(labels, label)
            for reason in source_reasons:
                self._increment(reason_codes, reason)
                if self._is_rejected_outcome(outcome):
                    self._increment(rejected_reason_codes, reason)
            if source_severity:
                self._increment(severities, source_severity)
            if source_action_id:
                action_ids.add(source_action_id)
            if isinstance(source_score, int):
                score_sum += source_score
                score_count += 1

        total = sum(outcomes.values())
        return {
            "source_runtime": "nightly_site_inspection",
            "events_total": total,
            "action_feedback_total": len(action_ids),
            "outcomes": outcomes,
            "labels": labels,
            "reason_codes": reason_codes,
            "rejected_reason_codes": self._top_counts(rejected_reason_codes),
            "severities": severities,
            "average_source_score": round(score_sum / score_count, 2) if score_count else 0.0,
            "rates": {
                "accepted_rate": self._rate(
                    outcomes.get("accepted", 0) + outcomes.get("edited_before_accept", 0),
                    total,
                ),
                "wrong_priority_rate": self._rate(labels.get("wrong_priority", 0), total),
                "evidence_weak_rate": self._rate(labels.get("evidence_weak", 0), total),
                "already_handled_rate": self._rate(labels.get("already_handled", 0), total),
            },
            "production_mutation": False,
            "approval_truth": "wordpress_local",
            "final_write_truth": "wordpress_local",
        }

    @staticmethod
    def _string_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if text and text not in normalized:
                normalized.append(text)
        return normalized

    @staticmethod
    def _redaction_status(payload: dict[str, Any]) -> str:
        explicit = str(payload.get("redaction_status") or "").strip()
        if explicit:
            return explicit
        if str(payload.get("operator_note") or "").strip():
            return "tenant_scoped_unredacted"
        return "aggregate_safe"

    @staticmethod
    def _increment(bucket: dict[str, int], key: str) -> None:
        normalized = key.strip() or "unknown"
        bucket[normalized] = bucket.get(normalized, 0) + 1

    @classmethod
    def _increment_trend_bucket(
        cls,
        trend: dict[str, dict[str, int]],
        created_at: datetime | None,
        outcome: str,
        labels: list[str],
    ) -> None:
        if created_at is None:
            bucket_at = datetime.now(UTC)
        else:
            bucket_at = (
                created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=UTC)
            )
        bucket_key = bucket_at.astimezone(UTC).strftime("%Y-%m-%dT%H:00:00Z")
        bucket = trend.setdefault(
            bucket_key,
            {
                "events_total": 0,
                "accepted": 0,
                "rejected": 0,
                "evidence_weak": 0,
                "wrong_next_step": 0,
            },
        )
        bucket["events_total"] += 1
        if outcome in {"accepted", "edited_before_accept"}:
            bucket["accepted"] += 1
        if cls._is_rejected_outcome(outcome):
            bucket["rejected"] += 1
        if "evidence_weak" in labels:
            bucket["evidence_weak"] += 1
        if "wrong_next_step" in labels:
            bucket["wrong_next_step"] += 1

    @classmethod
    def _increment_scenario(
        cls,
        scenarios: dict[str, dict[str, Any]],
        local_surface: str,
        source_runtime: str,
        outcome: str,
        labels: list[str],
    ) -> None:
        scenario = scenarios.setdefault(
            local_surface,
            {
                "local_surface": local_surface,
                "source_runtime": source_runtime,
                "events_total": 0,
                "outcomes": {},
                "labels": {},
            },
        )
        scenario["events_total"] += 1
        cls._increment(scenario["outcomes"], outcome)
        for label in labels:
            cls._increment(scenario["labels"], label)

    @classmethod
    def _scenario_summary(cls, scenarios: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        summary: list[dict[str, Any]] = []
        for scenario in scenarios.values():
            total = int(scenario["events_total"])
            outcomes = dict(scenario["outcomes"])
            labels = dict(scenario["labels"])
            summary.append(
                {
                    "local_surface": scenario["local_surface"],
                    "source_runtime": scenario["source_runtime"],
                    "events_total": total,
                    "outcomes": outcomes,
                    "labels": labels,
                    "accepted_rate": cls._rate(
                        int(outcomes.get("accepted", 0))
                        + int(outcomes.get("edited_before_accept", 0)),
                        total,
                    ),
                    "evidence_weak_rate": cls._rate(int(labels.get("evidence_weak", 0)), total),
                    "wrong_next_step_rate": cls._rate(
                        int(labels.get("wrong_next_step", 0)),
                        total,
                    ),
                }
            )
        return sorted(
            summary,
            key=lambda item: (-int(item["events_total"]), str(item["local_surface"])),
        )

    @staticmethod
    def _trend_summary(trend: dict[str, dict[str, int]]) -> list[dict[str, int | str]]:
        return [
            {"bucket": bucket, **counts}
            for bucket, counts in sorted(trend.items(), key=lambda item: item[0])
        ]

    @staticmethod
    def _top_counts(
        counts: dict[str, int],
        allowed: set[str] | None = None,
    ) -> list[dict[str, int | str]]:
        items = (
            (key, value)
            for key, value in counts.items()
            if value > 0 and (allowed is None or key in allowed)
        )
        return [
            {"label": key, "count": value}
            for key, value in sorted(items, key=lambda item: (-item[1], item[0]))[:8]
        ]

    @staticmethod
    def _is_rejected_outcome(outcome: str) -> bool:
        return outcome in {
            "rejected",
            "blocked_by_policy",
            "blocked_by_missing_input",
            "ignored",
            "expired",
        }

    @staticmethod
    def _rate(count: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return round(count / total, 4)

    @staticmethod
    def _format_datetime(value: datetime | None) -> str:
        if value is None:
            return datetime.now(UTC).isoformat()
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
