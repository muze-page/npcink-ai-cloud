from __future__ import annotations

from typing import Any

AGENT_FEEDBACK_CONTRACT_VERSION = "cloud_agent_feedback.v1"
AGENT_FEEDBACK_EVENT_KIND = "agent.feedback"
AGENT_FEEDBACK_EXECUTION_KIND = "agent_feedback"
AGENT_FEEDBACK_METER_PREFIX = "agent_feedback"

ALLOWED_AGENT_FEEDBACK_OUTCOMES = frozenset(
    {
        "accepted",
        "rejected",
        "edited_before_accept",
        "ignored",
        "expired",
        "blocked_by_policy",
        "blocked_by_missing_input",
    }
)

ALLOWED_AGENT_FEEDBACK_LABELS = frozenset(
    {
        "evidence_useful",
        "evidence_weak",
        "wrong_intent",
        "wrong_next_step",
        "missing_context",
        "wrong_priority",
        "already_handled",
        "unsafe_or_overreaching",
        "too_generic",
        "duplicate_suggestion",
        "good_but_needs_human_draft",
        "not_relevant_to_site",
        "source_or_license_risk",
        "visual_quality_low",
        "operator_confidence_high",
        "operator_confidence_low",
    }
)

FORBIDDEN_AGENT_FEEDBACK_KEYS = frozenset(
    {
        "approval_policy",
        "approval_truth",
        "approve",
        "approved",
        "commit",
        "confirm_token",
        "direct_publish",
        "direct_wordpress_write",
        "execute",
        "final_write_policy",
        "final_write_target",
        "preflight_policy",
        "publish",
        "router_adoption",
        "set_post_content",
        "update_post",
        "wordpress_write_policy",
        "wordpress_write_target",
        "write_confirmed",
        "write_control",
        "write_controls",
    }
)


class AgentFeedbackContractViolation(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def find_forbidden_agent_feedback_field(value: Any, *, prefix: str = "") -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").strip().lower()
            current_path = f"{prefix}.{normalized_key}" if prefix else normalized_key
            if normalized_key in FORBIDDEN_AGENT_FEEDBACK_KEYS:
                return current_path
            nested = find_forbidden_agent_feedback_field(item, prefix=current_path)
            if nested:
                return nested
    if isinstance(value, list):
        for index, item in enumerate(value):
            nested = find_forbidden_agent_feedback_field(item, prefix=f"{prefix}[{index}]")
            if nested:
                return nested
    return ""
