from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.db import get_session
from app.domain.agent_feedback.contracts import (
    AGENT_FEEDBACK_EVENT_KIND,
    AGENT_FEEDBACK_EXECUTION_KIND,
    AGENT_FEEDBACK_METER_PREFIX,
)


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
    def _format_datetime(value: datetime | None) -> str:
        if value is None:
            return datetime.now(UTC).isoformat()
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
