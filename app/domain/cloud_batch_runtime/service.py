from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.domain.cloud_batch_runtime.contracts import (
    CLOUD_BATCH_RUNTIME_EXECUTION_KIND,
    CLOUD_BATCH_RUNTIME_REQUEST_CONTRACT,
    CLOUD_BATCH_RUNTIME_RESULT_CONTRACT,
    NIGHTLY_SITE_INSPECTION_CORE_REVIEW_PLAN_ABILITY,
    NIGHTLY_SITE_INSPECTION_CORE_REVIEW_PLAN_ARTIFACT,
    NIGHTLY_SITE_INSPECTION_CORE_REVIEW_PLAN_CONTRACT,
    NIGHTLY_SITE_INSPECTION_RESULT_CONTRACT,
    CloudBatchRuntimeContractViolation,
    validate_cloud_batch_runtime_contract,
)

SCORE_VERSION = "nightly_content_quality_score.v2"
NIGHTLY_INTELLIGENCE_SURFACE = "nightly_intelligence"
NIGHTLY_INTELLIGENCE_CONTRACT = "nightly_intelligence_detail.v1"
NIGHTLY_RUN_DETAIL_CONTRACT = "nightly_site_inspection_run_detail.v1"

SCORE_DIMENSIONS = (
    "metadata_completeness",
    "content_depth",
    "freshness",
    "internal_navigation",
    "media_accessibility",
    "editorial_opportunity",
)

SCORE_DIMENSION_LABELS = {
    "metadata_completeness": "Metadata completeness",
    "content_depth": "Content depth",
    "freshness": "Freshness",
    "internal_navigation": "Internal navigation",
    "media_accessibility": "Media accessibility",
    "editorial_opportunity": "Editorial opportunity",
}

REASON_WEIGHTS = {
    "short_title": 12,
    "missing_meta_description": 14,
    "short_meta_description": 8,
    "thin_content": 10,
    "missing_internal_links": 9,
    "missing_image_alt_text": 15,
    "stale_content": 10,
}

REASON_DIMENSIONS = {
    "short_title": "metadata_completeness",
    "missing_meta_description": "metadata_completeness",
    "short_meta_description": "metadata_completeness",
    "thin_content": "content_depth",
    "missing_internal_links": "internal_navigation",
    "missing_image_alt_text": "media_accessibility",
    "stale_content": "freshness",
}

ISSUE_GROUPS = {
    "metadata": {
        "label": "Metadata",
        "reason_codes": {"short_title", "missing_meta_description", "short_meta_description"},
    },
    "content_depth": {"label": "Content depth", "reason_codes": {"thin_content"}},
    "internal_links": {"label": "Internal links", "reason_codes": {"missing_internal_links"}},
    "media_accessibility": {
        "label": "Media accessibility",
        "reason_codes": {"missing_image_alt_text"},
    },
    "freshness": {"label": "Freshness", "reason_codes": {"stale_content"}},
}


@dataclass(slots=True)
class CloudBatchRuntimeExecution:
    result_json: dict[str, Any]


class CloudBatchRuntimeService:
    def execute(
        self,
        *,
        site_id: str,
        ability_name: str,
        contract_version: str,
        input_payload: dict[str, Any],
        run_id: str,
    ) -> CloudBatchRuntimeExecution:
        validate_cloud_batch_runtime_contract(
            ability_name=ability_name,
            contract_version=contract_version,
            input_payload=input_payload,
        )

        raw_items = _extract_raw_items(input_payload)
        actions = [
            _score_item(item, sequence=index + 1)
            if isinstance(item, dict)
            else _failed_item_action(item, sequence=index + 1)
            for index, item in enumerate(raw_items)
        ]
        successful_actions = [
            action
            for action in actions
            if str(action.get("status") or "") == "succeeded"
        ]
        failed_actions = [
            action
            for action in actions
            if str(action.get("status") or "") not in {"", "succeeded"}
        ]
        warning_count = sum(1 for action in actions if action["severity"] == "warning")
        critical_count = sum(1 for action in actions if action["severity"] == "critical")
        average_score = round(
            sum(float(action["score"]) for action in successful_actions)
            / max(1, len(successful_actions)),
            2,
        )
        result_status = "partially_succeeded" if failed_actions else "succeeded"
        worker_phase = "partial_result_ready" if failed_actions else "result_ready"

        generated_at = datetime.now(UTC).isoformat()
        summary = {
            "items_scanned": len(raw_items),
            "items_succeeded": len(successful_actions),
            "items_failed": len(failed_actions),
            "actions_total": len([action for action in actions if action["reason_codes"]]),
            "warning_total": warning_count,
            "critical_total": critical_count,
            "average_score": average_score,
            "score_version": SCORE_VERSION,
        }
        nightly_result = _build_nightly_result(
            run_id=run_id,
            site_id=site_id,
            generated_at=generated_at,
            summary=summary,
            actions=actions,
        )
        core_review_plan = _build_core_review_plan(
            run_id=run_id,
            generated_at=generated_at,
            actions=actions,
        )
        writing_preparation = _build_writing_preparation(actions)
        morning_brief = _build_morning_brief(
            summary=summary,
            actions=actions,
            writing_preparation=writing_preparation,
            core_review_plan=core_review_plan,
        )
        blocked_items = _build_blocked_items(actions)
        retry_guidance = _build_retry_guidance(actions)
        operational_summary = _build_operational_summary(
            actions,
            blocked_items=blocked_items,
            retry_guidance=retry_guidance,
        )
        core_handoff_suggestion = _build_core_handoff_suggestion(
            core_review_plan=core_review_plan,
            actions=actions,
        )
        core_intake_package = _build_core_intake_package(
            run_id=run_id,
            generated_at=generated_at,
            review_items=operational_summary["review_items"],
            core_review_plan=core_review_plan,
            core_handoff_suggestion=core_handoff_suggestion,
        )
        nightly_intelligence_detail = _build_nightly_intelligence_detail(
            run_id=run_id,
            site_id=site_id,
            generated_at=generated_at,
            summary=summary,
            actions=actions,
            morning_brief=morning_brief,
            blocked_items=blocked_items,
            retry_guidance=retry_guidance,
            core_handoff_suggestion=core_handoff_suggestion,
        )
        nightly_run_detail = _build_nightly_run_detail(
            run_id=run_id,
            site_id=site_id,
            generated_at=generated_at,
            status=result_status,
            worker_phase=worker_phase,
            summary=summary,
            operational_summary=operational_summary,
            morning_brief=morning_brief,
            retry_guidance=retry_guidance,
            core_intake_package=core_intake_package,
        )
        execution_state = _build_execution_state(
            status=result_status,
            worker_phase=worker_phase,
            actions=actions,
            retry_guidance=retry_guidance,
        )

        result = {
            "contract_version": CLOUD_BATCH_RUNTIME_RESULT_CONTRACT,
            "request_contract_version": CLOUD_BATCH_RUNTIME_REQUEST_CONTRACT,
            "product_surface": NIGHTLY_INTELLIGENCE_SURFACE,
            "product_label": "Nightly Intelligence",
            "run_id": run_id,
            "site_id": site_id,
            "status": result_status,
            "worker_phase": worker_phase,
            "execution_kind": CLOUD_BATCH_RUNTIME_EXECUTION_KIND,
            "generated_at": generated_at,
            "execution_state": execution_state,
            "runtime_owner": "npcink-local-automation-runtime",
            "cloud_role": "runtime_detail",
            "task_profile": str(
                input_payload.get("task_profile") or "nightly_site_inspection_morning_brief"
            ),
            "summary": summary,
            "eligibility_summary": operational_summary["eligibility_summary"],
            "blocked_items": operational_summary["blocked_items"],
            "review_items": operational_summary["review_items"],
            "operator_next_action": operational_summary["operator_next_action"],
            "retryable": operational_summary["retryable"],
            "retry_guidance": operational_summary["retry_guidance"],
            "scoring_profile": _build_scoring_profile(),
            "actions": actions,
            "nightly_result": nightly_result,
            "morning_brief": morning_brief,
            "writing_preparation": writing_preparation,
            "core_handoff_suggestion": core_handoff_suggestion,
            "core_intake_package": core_intake_package,
            "nightly_intelligence_detail": nightly_intelligence_detail,
            "nightly_run_detail": nightly_run_detail,
            "core_review_plan": core_review_plan,
            "safety": {
                "direct_wordpress_write": False,
                "final_write_path": "core_proposal_required",
                "article_body_generated": False,
                "article_write_plan_generated": False,
                "requires_local_review": True,
            },
            "handoff": {
                "target_owner": "magick-ai-core",
                "target_plan_ability_id": NIGHTLY_SITE_INSPECTION_CORE_REVIEW_PLAN_ABILITY,
                "target_plan_contract": NIGHTLY_SITE_INSPECTION_CORE_REVIEW_PLAN_CONTRACT,
                "core_intake_package_available": bool(core_intake_package["available"]),
                "proposal_created": False,
                "proposal_candidate_available": bool(core_review_plan["write_actions"]),
                "operator_next_action": "review_cloud_batch_result",
            },
        }
        return CloudBatchRuntimeExecution(result_json=result)


def _extract_items(input_payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = _extract_raw_items(input_payload)
    return [item for item in raw_items if isinstance(item, dict)]


def _extract_raw_items(input_payload: dict[str, Any]) -> list[Any]:
    items = input_payload.get("items")
    if isinstance(items, list):
        return list(items)
    snapshot = input_payload.get("snapshot")
    if isinstance(snapshot, dict) and isinstance(snapshot.get("items"), list):
        return list(snapshot["items"])
    raise CloudBatchRuntimeContractViolation(
        "cloud_batch_runtime.items_required",
        "cloud batch runtime input requires at least one content item",
    )


def _failed_item_action(item: Any, *, sequence: int) -> dict[str, Any]:
    return {
        "action_id": f"action_{sequence:03d}",
        "action_type": "content_quality_signal",
        "object_type": "unknown",
        "object_id": "",
        "title": "(invalid item)",
        "score": 0,
        "score_version": SCORE_VERSION,
        "score_breakdown": _build_score_breakdown(
            normalized_score=0,
            severity="warning",
            reason_codes=[],
            dimension_impacts={dimension: 0 for dimension in SCORE_DIMENSIONS},
            dimension_reasons={dimension: [] for dimension in SCORE_DIMENSIONS},
            dimension_evidence={
                dimension: ["item_validation:failed"]
                if dimension == "editorial_opportunity"
                else []
                for dimension in SCORE_DIMENSIONS
            },
        ),
        "severity": "warning",
        "reason_codes": [],
        "evidence_summary": "Item could not be analyzed because its payload was invalid.",
        "priority_reason": "item_analysis_failed",
        "recommended_next_action": "retry_failed_cloud_analysis",
        "direct_wordpress_write": False,
        "status": "failed",
        "error_code": "cloud_batch_runtime.item_invalid",
        "error_message": "nightly inspection item must be an object",
        "retryable": True,
    }


def _score_item(item: dict[str, Any], *, sequence: int) -> dict[str, Any]:
    reason_codes: list[str] = []
    dimension_impacts: dict[str, int] = {dimension: 0 for dimension in SCORE_DIMENSIONS}
    dimension_reasons: dict[str, list[str]] = {dimension: [] for dimension in SCORE_DIMENSIONS}
    dimension_evidence: dict[str, list[str]] = {dimension: [] for dimension in SCORE_DIMENSIONS}
    title = str(item.get("title") or "").strip()
    excerpt = str(item.get("excerpt") or item.get("summary") or "").strip()
    meta_description = str(item.get("meta_description") or "").strip()
    word_count = _coerce_int(item.get("word_count"), default=0)
    internal_link_count = _coerce_int(item.get("internal_link_count"), default=0)
    image_alt_missing = _coerce_int(item.get("image_alt_missing"), default=0)
    days_since_modified = _coerce_int(item.get("days_since_modified"), default=0)

    score = 100
    if len(title) < 20:
        score -= _add_reason(
            reason_codes,
            dimension_impacts,
            dimension_reasons,
            dimension_evidence,
            "short_title",
            evidence=f"title_length:{len(title)}",
        )
    if not meta_description:
        score -= _add_reason(
            reason_codes,
            dimension_impacts,
            dimension_reasons,
            dimension_evidence,
            "missing_meta_description",
            evidence="meta_description:missing",
        )
    elif len(meta_description) < 80:
        score -= _add_reason(
            reason_codes,
            dimension_impacts,
            dimension_reasons,
            dimension_evidence,
            "short_meta_description",
            evidence=f"meta_description_length:{len(meta_description)}",
        )
    if word_count and word_count < 500:
        score -= _add_reason(
            reason_codes,
            dimension_impacts,
            dimension_reasons,
            dimension_evidence,
            "thin_content",
            evidence=f"word_count:{word_count}",
        )
    if internal_link_count <= 0:
        score -= _add_reason(
            reason_codes,
            dimension_impacts,
            dimension_reasons,
            dimension_evidence,
            "missing_internal_links",
            evidence=f"internal_link_count:{internal_link_count}",
        )
    if image_alt_missing > 0:
        score -= _add_reason(
            reason_codes,
            dimension_impacts,
            dimension_reasons,
            dimension_evidence,
            "missing_image_alt_text",
            impact=min(15, 5 * image_alt_missing),
            evidence=f"image_alt_missing:{image_alt_missing}",
        )
    if days_since_modified >= 365:
        score -= _add_reason(
            reason_codes,
            dimension_impacts,
            dimension_reasons,
            dimension_evidence,
            "stale_content",
            evidence=f"days_since_modified:{days_since_modified}",
        )

    normalized_score = max(0, min(100, score))
    severity = "ok"
    if normalized_score < 60:
        severity = "critical"
    elif normalized_score < 80:
        severity = "warning"

    object_type = str(item.get("object_type") or item.get("post_type") or "post")
    object_id = str(item.get("object_id") or item.get("post_id") or item.get("id") or "")
    score_breakdown = _build_score_breakdown(
        normalized_score=normalized_score,
        severity=severity,
        reason_codes=reason_codes,
        dimension_impacts=dimension_impacts,
        dimension_reasons=dimension_reasons,
        dimension_evidence=dimension_evidence,
    )
    return {
        "action_id": f"action_{sequence:03d}",
        "action_type": "content_quality_signal",
        "object_type": object_type,
        "object_id": object_id,
        "title": title or "(untitled)",
        "score": normalized_score,
        "score_version": SCORE_VERSION,
        "score_breakdown": score_breakdown,
        "severity": severity,
        "reason_codes": reason_codes,
        "evidence_summary": _build_evidence_summary(reason_codes, excerpt=excerpt),
        "priority_reason": _priority_reason(
            score=normalized_score,
            severity=severity,
            reason_codes=reason_codes,
        ),
        "recommended_next_action": (
            "review_update_brief" if severity != "ok" else "no_immediate_action"
        ),
        "direct_wordpress_write": False,
        "status": "succeeded",
    }


def _add_reason(
    reason_codes: list[str],
    dimension_impacts: dict[str, int],
    dimension_reasons: dict[str, list[str]],
    dimension_evidence: dict[str, list[str]],
    reason_code: str,
    *,
    impact: int | None = None,
    evidence: str,
) -> int:
    resolved_impact = int(impact if impact is not None else REASON_WEIGHTS[reason_code])
    dimension = REASON_DIMENSIONS[reason_code]
    reason_codes.append(reason_code)
    dimension_impacts[dimension] += resolved_impact
    dimension_reasons[dimension].append(reason_code)
    dimension_evidence[dimension].append(evidence)
    return resolved_impact


def _build_score_breakdown(
    *,
    normalized_score: int,
    severity: str,
    reason_codes: list[str],
    dimension_impacts: dict[str, int],
    dimension_reasons: dict[str, list[str]],
    dimension_evidence: dict[str, list[str]],
) -> dict[str, Any]:
    if reason_codes:
        editorial_impact = 35 if severity == "critical" else 20 if severity == "warning" else 10
        dimension_impacts["editorial_opportunity"] = max(
            dimension_impacts["editorial_opportunity"],
            editorial_impact,
        )
        dimension_reasons["editorial_opportunity"] = list(reason_codes[:5])
        dimension_evidence["editorial_opportunity"] = [
            "review_candidate:true",
            f"severity:{severity}",
        ]

    dimensions = []
    for dimension in SCORE_DIMENSIONS:
        impact = max(0, min(100, int(dimension_impacts.get(dimension, 0))))
        dimensions.append(
            {
                "id": dimension,
                "label": SCORE_DIMENSION_LABELS[dimension],
                "score": max(0, 100 - impact),
                "impact": impact,
                "reason_codes": list(dimension_reasons.get(dimension, [])),
                "evidence": list(dimension_evidence.get(dimension, []))[:6],
            }
        )

    return {
        "score_version": SCORE_VERSION,
        "overall_score": normalized_score,
        "severity": severity,
        "dimensions": dimensions,
        "reason_weights": {
            reason: REASON_WEIGHTS[reason]
            for reason in reason_codes
            if reason in REASON_WEIGHTS
        },
        "severity_thresholds": _severity_thresholds(),
    }


def _build_scoring_profile() -> dict[str, Any]:
    return {
        "score_version": SCORE_VERSION,
        "dimensions": [
            {"id": dimension, "label": SCORE_DIMENSION_LABELS[dimension]}
            for dimension in SCORE_DIMENSIONS
        ],
        "reason_weights": dict(REASON_WEIGHTS),
        "severity_thresholds": _severity_thresholds(),
        "cloud_role": "runtime_detail",
        "editorial_truth": "wordpress_local",
    }


def _severity_thresholds() -> dict[str, int]:
    return {
        "critical_below": 60,
        "warning_below": 80,
    }


def _build_evidence_summary(reason_codes: list[str], *, excerpt: str) -> str:
    if reason_codes:
        return "Review suggested for: " + ", ".join(reason_codes[:5])
    if excerpt:
        return "No immediate quality issue detected from supplied evidence."
    return "No immediate quality issue detected from supplied metadata."


def _build_writing_preparation(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preparation: list[dict[str, Any]] = []
    for action in actions:
        reason_codes = action.get("reason_codes")
        if not isinstance(reason_codes, list) or not reason_codes:
            continue
        preparation.append(
            {
                "source_action_id": action.get("action_id"),
                "source_object_ids": [action.get("object_id")],
                "opportunity_kind": "refresh_existing_content",
                "evidence_summary": action.get("evidence_summary") or "",
                "suggested_review_angle": _suggested_review_angle(reason_codes),
                "missing_context": _missing_context(reason_codes),
                "next_local_action": _next_local_action(reason_codes),
                "forbidden_output_absent": True,
                "direct_wordpress_write": False,
            }
        )
    return preparation


def _build_nightly_result(
    *,
    run_id: str,
    site_id: str,
    generated_at: str,
    summary: dict[str, Any],
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    priorities = [
        {
            "object_type": action.get("object_type"),
            "object_id": action.get("object_id"),
            "title": action.get("title"),
            "score": action.get("score"),
            "severity": action.get("severity"),
            "reason_codes": action.get("reason_codes") or [],
            "explanation": action.get("evidence_summary") or "",
            "recommended_next_action": action.get("recommended_next_action"),
        }
        for action in actions
        if action.get("reason_codes")
    ]

    return {
        "contract_version": NIGHTLY_SITE_INSPECTION_RESULT_CONTRACT,
        "run_id": run_id,
        "site_id": site_id,
        "generated_at": generated_at,
        "summary": summary,
        "scoring_profile": _build_scoring_profile(),
        "priorities": priorities,
        "writing_preparation": _build_writing_preparation(actions),
        "issue_groups": _build_issue_groups(actions),
        "safety": {
            "direct_wordpress_write": False,
            "requires_local_review": True,
            "cloud_scheduler_truth": False,
            "article_body_generated": False,
            "article_write_plan_generated": False,
        },
    }


def _build_morning_brief(
    *,
    summary: dict[str, Any],
    actions: list[dict[str, Any]],
    writing_preparation: list[dict[str, Any]],
    core_review_plan: dict[str, Any],
) -> dict[str, Any]:
    reviewable_actions = _reviewable_actions(actions)
    return {
        "contract_version": "nightly_site_inspection_morning_brief.v2",
        "organization_version": "morning_brief_review_queue.v1",
        "top_summary": {
            "items_scanned": summary.get("items_scanned", 0),
            "reviewable_items": len(reviewable_actions),
            "warnings": summary.get("warning_total", 0),
            "critical": summary.get("critical_total", 0),
            "average_score": summary.get("average_score", 0),
            "score_version": summary.get("score_version", SCORE_VERSION),
        },
        "priority_queue": [
            _priority_queue_item(action) for action in reviewable_actions[:10]
        ],
        "issue_groups": _build_issue_groups(actions),
        "writing_preparation": writing_preparation[:10],
        "core_handoff": {
            "available": bool(core_review_plan.get("write_actions")),
            "proposal_created": False,
            "target_plan_ability_id": NIGHTLY_SITE_INSPECTION_CORE_REVIEW_PLAN_ABILITY,
            "target_plan_contract": NIGHTLY_SITE_INSPECTION_CORE_REVIEW_PLAN_CONTRACT,
            "requires_input": ["title", "content"]
            if core_review_plan.get("write_actions")
            else [],
            "operator_next_action": (
                "review_priority_queue"
                if core_review_plan.get("write_actions")
                else "no_core_handoff_needed"
            ),
        },
        "safety": {
            "review_only": True,
            "direct_wordpress_write": False,
            "cloud_scheduler_truth": False,
            "article_body_generated": False,
            "article_write_plan_generated": False,
        },
    }


def _build_blocked_items(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocked: list[dict[str, Any]] = []
    for action in actions:
        reason_codes = [
            str(reason)
            for reason in action.get("reason_codes", [])
            if str(reason or "").strip()
        ]
        missing_context = _missing_context(reason_codes)
        if not missing_context:
            continue
        blocked.append(
            {
                "action_id": action.get("action_id"),
                "object_type": action.get("object_type"),
                "object_id": action.get("object_id"),
                "title": action.get("title"),
                "blocked_reason": "local_review_required",
                "missing_context": missing_context,
                "retryable": False,
                "operator_next_action": _next_local_action(reason_codes),
                "direct_wordpress_write": False,
            }
        )
    return blocked[:10]


def _build_retry_guidance(actions: list[dict[str, Any]]) -> dict[str, Any]:
    failed_actions = [
        action for action in actions if str(action.get("status") or "") not in {"", "succeeded"}
    ]
    return {
        "available": bool(failed_actions),
        "retry_owner": "cloud_runtime" if failed_actions else "not_needed",
        "operator_next_action": (
            "retry_failed_cloud_analysis" if failed_actions else "review_morning_brief"
        ),
        "failed_action_ids": [
            str(action.get("action_id") or "") for action in failed_actions[:10]
        ],
        "retryable": bool(failed_actions),
        "cloud_scheduler_truth": False,
        "direct_wordpress_write": False,
    }


def _build_execution_state(
    *,
    status: str,
    worker_phase: str,
    actions: list[dict[str, Any]],
    retry_guidance: dict[str, Any],
) -> dict[str, Any]:
    failed_actions = [
        action for action in actions if str(action.get("status") or "") not in {"", "succeeded"}
    ]
    succeeded_actions = [
        action for action in actions if str(action.get("status") or "") == "succeeded"
    ]
    return {
        "contract_version": "cloud_run_execution_state.v1",
        "state_machine": "queued->running->terminal",
        "status": status,
        "phase": "terminal",
        "worker_phase": worker_phase,
        "partial_success": bool(failed_actions and succeeded_actions),
        "action_counts": {
            "total": len(actions),
            "succeeded": len(succeeded_actions),
            "failed": len(failed_actions),
        },
        "retry": {
            "retryable": bool(retry_guidance.get("retryable")),
            "retry_owner": retry_guidance.get("retry_owner", "not_needed"),
            "failed_action_ids": retry_guidance.get("failed_action_ids", []),
            "operator_next_action": retry_guidance.get(
                "operator_next_action",
                "review_morning_brief",
            ),
            "resubmit_requires_new_idempotency_key": bool(retry_guidance.get("retryable")),
        },
        "idempotency": {
            "canonical_truth": "run_records.site_id_idempotency_key",
            "replay_safe": True,
        },
        "events": [
            {
                "event": "runtime.run.terminal",
                "status": status,
                "worker_phase": worker_phase,
            }
        ],
        "boundary": {
            "cloud_role": "runtime_detail",
            "cloud_scheduler_truth": False,
            "direct_wordpress_write": False,
        },
    }


def _build_core_handoff_suggestion(
    *,
    core_review_plan: dict[str, Any],
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    reviewable_actions = _reviewable_actions(actions)
    return {
        "available": bool(core_review_plan.get("write_actions")),
        "suggestion_type": "core_review_plan_candidate",
        "target_owner": "magick-ai-core",
        "target_plan_ability_id": NIGHTLY_SITE_INSPECTION_CORE_REVIEW_PLAN_ABILITY,
        "target_plan_contract": NIGHTLY_SITE_INSPECTION_CORE_REVIEW_PLAN_CONTRACT,
        "source_action_ids": [
            str(action.get("action_id") or "") for action in reviewable_actions[:10]
        ],
        "proposal_created": False,
        "requires_local_review": True,
        "operator_next_action": (
            "review_priority_queue" if reviewable_actions else "no_core_handoff_needed"
        ),
        "direct_wordpress_write": False,
    }


def _build_nightly_intelligence_detail(
    *,
    run_id: str,
    site_id: str,
    generated_at: str,
    summary: dict[str, Any],
    actions: list[dict[str, Any]],
    morning_brief: dict[str, Any],
    blocked_items: list[dict[str, Any]],
    retry_guidance: dict[str, Any],
    core_handoff_suggestion: dict[str, Any],
) -> dict[str, Any]:
    review_items = _reviewable_actions(actions)
    return {
        "artifact_type": "nightly_intelligence_detail",
        "contract_version": NIGHTLY_INTELLIGENCE_CONTRACT,
        "run_id": run_id,
        "site_id": site_id,
        "generated_at": generated_at,
        "positioning": "nightly_site_inspection_and_morning_editorial_preparation",
        "output_contract": {
            "review_items": len(review_items),
            "blocked_items": len(blocked_items),
            "retry_guidance": bool(retry_guidance.get("available")),
            "morning_brief": bool(morning_brief),
            "score_breakdown": True,
            "core_handoff_suggestion": bool(core_handoff_suggestion.get("available")),
        },
        "summary": {
            "items_scanned": summary.get("items_scanned", 0),
            "reviewable_items": len(review_items),
            "blocked_items": len(blocked_items),
            "warnings": summary.get("warning_total", 0),
            "critical": summary.get("critical_total", 0),
            "average_score": summary.get("average_score", 0),
            "score_version": summary.get("score_version", SCORE_VERSION),
        },
        "read_surface": "run_result_detail",
        "runtime_owner": "npcink-local-automation-runtime",
        "cloud_role": "runtime_detail",
        "truth_boundary": {
            "schedule_truth": "wordpress_local",
            "approval_truth": "wordpress_local",
            "proposal_truth": "magick_ai_core",
            "final_write_truth": "wordpress_local",
            "cloud_scheduler_truth": False,
            "direct_wordpress_write": False,
        },
        "forbidden_outputs_absent": [
            "bulk_image_mutation",
            "bulk_tag_mutation",
            "bulk_post_update",
            "automatic_publish",
            "automatic_seo_meta_write",
            "article_body",
            "article_write_plan",
        ],
    }


def _build_nightly_run_detail(
    *,
    run_id: str,
    site_id: str,
    generated_at: str,
    status: str,
    worker_phase: str,
    summary: dict[str, Any],
    operational_summary: dict[str, Any],
    morning_brief: dict[str, Any],
    retry_guidance: dict[str, Any],
    core_intake_package: dict[str, Any],
) -> dict[str, Any]:
    raw_eligibility = operational_summary.get("eligibility_summary")
    eligibility: dict[str, Any] = raw_eligibility if isinstance(raw_eligibility, dict) else {}
    raw_review_items = operational_summary.get("review_items")
    review_items: list[Any] = raw_review_items if isinstance(raw_review_items, list) else []
    raw_blocked_items = operational_summary.get("blocked_items")
    blocked_items: list[dict[str, Any]] = [
        item for item in raw_blocked_items if isinstance(item, dict)
    ] if isinstance(raw_blocked_items, list) else []
    raw_priority_queue = morning_brief.get("priority_queue")
    priority_queue: list[Any] = raw_priority_queue if isinstance(raw_priority_queue, list) else []
    raw_selected_review_item_ids = core_intake_package.get("selected_review_item_ids")
    selected_review_item_ids: list[Any] = (
        raw_selected_review_item_ids
        if isinstance(raw_selected_review_item_ids, list)
        else []
    )

    return {
        "artifact_type": "nightly_site_inspection_run_detail",
        "contract_version": NIGHTLY_RUN_DETAIL_CONTRACT,
        "run_id": run_id,
        "site_id": site_id,
        "generated_at": generated_at,
        "status": status,
        "worker_phase": worker_phase,
        "operator_summary": {
            "items_scanned": summary.get("items_scanned", 0),
            "reviewable_count": eligibility.get("reviewable_count", len(review_items)),
            "blocked_count": eligibility.get("blocked_count", len(blocked_items)),
            "selected_count": eligibility.get("selected_count", len(priority_queue)),
            "warning_count": summary.get("warning_total", 0),
            "critical_count": summary.get("critical_total", 0),
            "average_score": summary.get("average_score", 0),
            "score_version": summary.get("score_version", SCORE_VERSION),
        },
        "review_queue": {
            "available": bool(priority_queue),
            "source": "morning_brief.priority_queue",
            "selected_review_item_ids": selected_review_item_ids,
            "operator_next_action": operational_summary.get(
                "operator_next_action",
                "review_cloud_batch_result",
            ),
        },
        "blocked_summary": {
            "blocked_count": len(blocked_items),
            "blocked_action_ids": [
                str(item.get("action_id") or "")
                for item in blocked_items[:10]
                if isinstance(item, dict) and str(item.get("action_id") or "").strip()
            ],
            "operator_next_action": "resolve_locally_or_select_review_item",
            "direct_wordpress_write": False,
        },
        "retry_summary": {
            "retryable": bool(retry_guidance.get("retryable")),
            "retry_owner": retry_guidance.get("retry_owner", "not_needed"),
            "operator_next_action": retry_guidance.get(
                "operator_next_action",
                "review_morning_brief",
            ),
            "failed_action_ids": retry_guidance.get("failed_action_ids", []),
            "cloud_scheduler_truth": False,
            "direct_wordpress_write": False,
        },
        "core_handoff_summary": {
            "available": bool(core_intake_package.get("available")),
            "target_owner": core_intake_package.get("target_owner", "magick-ai-core"),
            "target_route": core_intake_package.get("target_route", "core:/proposals/from-plan"),
            "target_plan_ability_id": core_intake_package.get(
                "target_plan_ability_id",
                NIGHTLY_SITE_INSPECTION_CORE_REVIEW_PLAN_ABILITY,
            ),
            "selected_review_item_ids": selected_review_item_ids,
            "proposal_created": False,
            "proposal_state_owner": "magick-ai-core",
            "approval_truth": "wordpress_local",
            "final_write_truth": "wordpress_local",
            "receipt_owner": _string_path(
                core_intake_package,
                ("receipt_expectation", "receipt_owner"),
            )
            or "wordpress_toolbox_local",
        },
        "read_only_boundary": {
            "cloud_role": "runtime_detail",
            "cloud_scheduler_truth": False,
            "direct_wordpress_write": False,
            "automatic_publish": False,
            "article_body_generated": False,
            "article_write_plan_generated": False,
        },
        "detail_sources": {
            "morning_brief": "morning_brief",
            "blocked_items": "blocked_items",
            "retry_guidance": "retry_guidance",
            "core_intake_package": "core_intake_package",
        },
    }


def _build_core_intake_package(
    *,
    run_id: str,
    generated_at: str,
    review_items: list[dict[str, Any]],
    core_review_plan: dict[str, Any],
    core_handoff_suggestion: dict[str, Any],
) -> dict[str, Any]:
    selected_review_items = [
        {
            "action_id": item.get("action_id"),
            "object_type": item.get("object_type"),
            "object_id": item.get("object_id"),
            "score": item.get("score"),
            "severity": item.get("severity"),
            "reason_codes": item.get("reason_codes") or [],
            "recommended_next_action": item.get("recommended_next_action"),
            "direct_wordpress_write": False,
        }
        for item in review_items
    ]
    write_actions = core_review_plan.get("write_actions")
    write_action = write_actions[0] if isinstance(write_actions, list) and write_actions else {}

    return {
        "artifact_type": "nightly_site_inspection_core_intake_package",
        "contract_version": "nightly_site_inspection_core_intake_package.v1",
        "available": bool(core_handoff_suggestion.get("available")),
        "source_run_id": run_id,
        "generated_at": generated_at,
        "user_action": "select_review_item_in_morning_brief",
        "selected_review_item_ids": [
            str(item.get("action_id") or "")
            for item in selected_review_items
            if str(item.get("action_id") or "").strip()
        ],
        "selected_review_items": selected_review_items,
        "target_owner": "magick-ai-core",
        "handoff_owner": "wordpress_toolbox_local",
        "handoff_surface": "morning_brief_review_queue",
        "target_plan_ability_id": NIGHTLY_SITE_INSPECTION_CORE_REVIEW_PLAN_ABILITY,
        "target_plan_contract": NIGHTLY_SITE_INSPECTION_CORE_REVIEW_PLAN_CONTRACT,
        "target_route": "core:/proposals/from-plan",
        "core_review_plan": core_review_plan,
        "core_review_plan_idempotency_key": _string_path(
            write_action,
            ("input", "idempotency_key"),
        ),
        "proposal_created": False,
        "proposal_state_owner": "magick-ai-core",
        "approval_truth": "wordpress_local",
        "final_write_truth": "wordpress_local",
        "cloud_role": "runtime_detail",
        "cloud_scheduler_truth": False,
        "direct_wordpress_write": False,
        "requires_local_review": True,
        "operator_next_action": (
            "submit_selected_review_items_to_core"
            if selected_review_items
            else "no_core_handoff_needed"
        ),
        "receipt_expectation": {
            "expected_local_receipt": "core_proposal_id",
            "receipt_owner": "wordpress_toolbox_local",
            "cloud_receipt_storage": "not_canonical",
        },
    }


def _reviewable_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [action for action in actions if action.get("reason_codes")],
        key=lambda action: (
            0 if action.get("severity") == "critical" else 1,
            int(action.get("score") or 100),
            str(action.get("action_id") or ""),
        ),
    )


def _build_operational_summary(
    actions: list[dict[str, Any]],
    *,
    blocked_items: list[dict[str, Any]],
    retry_guidance: dict[str, Any],
) -> dict[str, Any]:
    reviewable_actions = _reviewable_actions(actions)
    operator_next_action = (
        "review_cloud_batch_result"
        if reviewable_actions
        else "no_review_needed"
    )
    return {
        "eligibility_summary": {
            "items_total": len(actions),
            "eligible_count": max(0, len(actions) - len(blocked_items)),
            "blocked_count": len(blocked_items),
            "reviewable_count": len(reviewable_actions),
            "selected_count": len(reviewable_actions[:10]),
        },
        "blocked_items": blocked_items,
        "review_items": [
            _priority_queue_item(action) for action in reviewable_actions[:10]
        ],
        "operator_next_action": operator_next_action,
        "retryable": bool(retry_guidance.get("retryable")),
        "retry_guidance": retry_guidance,
    }


def _priority_queue_item(action: dict[str, Any]) -> dict[str, Any]:
    reason_codes = [
        str(reason)
        for reason in action.get("reason_codes", [])
        if str(reason or "").strip()
    ]
    return {
        "action_id": action.get("action_id"),
        "object_type": action.get("object_type"),
        "object_id": action.get("object_id"),
        "title": action.get("title"),
        "score": action.get("score"),
        "severity": action.get("severity"),
        "priority_reason": action.get("priority_reason") or _priority_reason(
            score=int(action.get("score") or 100),
            severity=str(action.get("severity") or "ok"),
            reason_codes=reason_codes,
        ),
        "reason_codes": reason_codes,
        "group_ids": _group_ids_for_reasons(reason_codes),
        "evidence_summary": action.get("evidence_summary") or "",
        "recommended_next_action": action.get("recommended_next_action"),
        "direct_wordpress_write": False,
    }


def _build_issue_groups(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for group_id, definition in ISSUE_GROUPS.items():
        matched = [
            action
            for action in actions
            if set(action.get("reason_codes") or []) & set(definition["reason_codes"])
        ]
        if not matched:
            continue
        groups.append(
            {
                "id": group_id,
                "label": definition["label"],
                "count": len(matched),
                "top_action_ids": [
                    str(action.get("action_id") or "")
                    for action in _reviewable_actions(matched)[:5]
                ],
                "reason_codes": sorted(
                    {
                        str(reason)
                        for action in matched
                        for reason in action.get("reason_codes", [])
                        if reason in definition["reason_codes"]
                    }
                ),
                "next_local_action": _group_next_local_action(group_id),
            }
        )
    return groups


def _group_ids_for_reasons(reason_codes: list[str]) -> list[str]:
    group_ids: list[str] = []
    reason_set = set(reason_codes)
    for group_id, definition in ISSUE_GROUPS.items():
        if reason_set & set(definition["reason_codes"]):
            group_ids.append(group_id)
    return group_ids


def _priority_reason(*, score: int, severity: str, reason_codes: list[str]) -> str:
    if severity == "critical":
        return "critical_score"
    if len(reason_codes) >= 3:
        return "multiple_quality_signals"
    if "stale_content" in reason_codes:
        return "refresh_opportunity"
    if score < 80:
        return "warning_score"
    return "reviewable_quality_signal"


def _suggested_review_angle(reason_codes: list[str]) -> str:
    if "stale_content" in reason_codes:
        return "refresh_existing_content"
    if "missing_internal_links" in reason_codes:
        return "strengthen_internal_navigation"
    if "missing_image_alt_text" in reason_codes:
        return "improve_media_accessibility"
    if "missing_meta_description" in reason_codes or "short_meta_description" in reason_codes:
        return "complete_search_snippet_context"
    if "thin_content" in reason_codes:
        return "expand_existing_page_evidence"
    return "review_quality_signal"


def _missing_context(reason_codes: list[str]) -> list[str]:
    context: list[str] = []
    if "missing_meta_description" in reason_codes or "short_meta_description" in reason_codes:
        context.append("search_snippet_intent")
    if "thin_content" in reason_codes:
        context.append("source_evidence_or_outline")
    if "missing_internal_links" in reason_codes:
        context.append("candidate_internal_targets")
    if "missing_image_alt_text" in reason_codes:
        context.append("image_subject_context")
    if "stale_content" in reason_codes:
        context.append("current_facts_to_verify")
    return context


def _next_local_action(reason_codes: list[str]) -> str:
    if "missing_image_alt_text" in reason_codes and len(reason_codes) == 1:
        return "review_media_accessibility"
    if "missing_internal_links" in reason_codes:
        return "review_internal_links"
    if "missing_meta_description" in reason_codes or "short_meta_description" in reason_codes:
        return "prepare_metadata_review"
    return "review_update_brief"


def _group_next_local_action(group_id: str) -> str:
    return {
        "metadata": "prepare_metadata_review",
        "content_depth": "review_content_depth",
        "internal_links": "review_internal_links",
        "media_accessibility": "review_media_accessibility",
        "freshness": "review_refresh_need",
    }.get(group_id, "review_update_brief")


def _string_path(value: dict[str, Any], path: tuple[str, ...]) -> str:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return str(current or "")


def _build_core_review_plan(
    *,
    run_id: str,
    generated_at: str,
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    issue_actions = [action for action in actions if action.get("reason_codes")]
    evidence_refs = [
        {
            "action_id": action.get("action_id"),
            "title": action.get("title"),
            "post_id": action.get("object_id"),
            "source_type": action.get("object_type"),
            "score": action.get("score"),
            "severity": action.get("severity"),
            "reason_codes": action.get("reason_codes") or [],
            "suggested_use": "morning_brief_review_evidence",
        }
        for action in issue_actions[:10]
    ]

    write_actions: list[dict[str, Any]] = []
    preview: list[dict[str, Any]] = []
    if evidence_refs:
        action_id = "review_nightly_site_inspection"
        preview.append(
            {
                "action_id": action_id,
                "proposal_ready": False,
                "evidence_ref_count": len(evidence_refs),
            }
        )
        write_actions.append(
            {
                "action_id": action_id,
                "target_ability_id": "npcink-abilities-toolkit/create-draft",
                "input": {
                    "title": "",
                    "content": "",
                    "status": "draft",
                    "dry_run": True,
                    "commit": False,
                    "idempotency_key": f"nightly-inspection-review-{run_id}",
                },
                "risk": "medium",
                "requires_approval": True,
                "commit_execution": False,
                "proposal_ready": False,
                "requires_input": ["title", "content"],
                "reason": "Morning Brief found reviewable content quality signals.",
            }
        )

    return {
        "artifact_type": NIGHTLY_SITE_INSPECTION_CORE_REVIEW_PLAN_ARTIFACT,
        "contract_version": NIGHTLY_SITE_INSPECTION_CORE_REVIEW_PLAN_CONTRACT,
        "version": 1,
        "batch_id": run_id,
        "cloud_run_id": run_id,
        "generated_at": generated_at,
        "requires_approval": True,
        "dry_run": True,
        "commit_execution": False,
        "proposal_mode": "single",
        "write_posture": "core_proposal_handoff",
        "direct_wordpress_write": False,
        "runtime_owner": "npcink-local-automation-runtime",
        "agent_id": "nightly_site_inspection_cloud_runtime",
        "agent_version": "nightly_site_inspection_cloud_runtime.v1",
        "workflow": "nightly_site_inspection",
        "intent": "morning_review_preparation",
        "cloud_output": "proposal_candidate",
        "local_next_action": "operator_review",
        "evidence_gate_status": "passed" if evidence_refs else "no_action",
        "evidence_refs": evidence_refs,
        "blocked_outputs": [
            "direct_wordpress_write",
            "article_body",
            "article_write_plan",
            "final_seo_copy",
        ],
        "issue_types": ["nightly_site_inspection"],
        "risk": {
            "level": "medium" if evidence_refs else "low",
            "reason": "review_required" if evidence_refs else "no_reviewable_issue",
        },
        "preview": preview,
        "write_actions": write_actions,
    }


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
