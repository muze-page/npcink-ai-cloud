from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.domain.cloud_batch_runtime.contracts import (
    CLOUD_BATCH_RUNTIME_REQUEST_CONTRACT,
    CLOUD_BATCH_RUNTIME_RESULT_CONTRACT,
    CloudBatchRuntimeContractViolation,
    NIGHTLY_SITE_INSPECTION_CORE_REVIEW_PLAN_ABILITY,
    NIGHTLY_SITE_INSPECTION_CORE_REVIEW_PLAN_ARTIFACT,
    NIGHTLY_SITE_INSPECTION_CORE_REVIEW_PLAN_CONTRACT,
    NIGHTLY_SITE_INSPECTION_RESULT_CONTRACT,
    validate_cloud_batch_runtime_contract,
)


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

        items = _extract_items(input_payload)
        actions = [
            _score_item(item, sequence=index + 1)
            for index, item in enumerate(items)
            if isinstance(item, dict)
        ]
        warning_count = sum(1 for action in actions if action["severity"] == "warning")
        critical_count = sum(1 for action in actions if action["severity"] == "critical")
        average_score = round(
            sum(float(action["score"]) for action in actions) / len(actions),
            2,
        )

        generated_at = datetime.now(UTC).isoformat()
        summary = {
            "items_scanned": len(actions),
            "actions_total": len([action for action in actions if action["reason_codes"]]),
            "warning_total": warning_count,
            "critical_total": critical_count,
            "average_score": average_score,
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

        result = {
            "contract_version": CLOUD_BATCH_RUNTIME_RESULT_CONTRACT,
            "request_contract_version": CLOUD_BATCH_RUNTIME_REQUEST_CONTRACT,
            "run_id": run_id,
            "site_id": site_id,
            "generated_at": generated_at,
            "runtime_owner": "npcink-local-automation-runtime",
            "cloud_role": "runtime_detail",
            "task_profile": str(
                input_payload.get("task_profile") or "nightly_site_inspection_morning_brief"
            ),
            "summary": summary,
            "actions": actions,
            "nightly_result": nightly_result,
            "writing_preparation": _build_writing_preparation(actions),
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
                "proposal_created": False,
                "proposal_candidate_available": bool(core_review_plan["write_actions"]),
                "operator_next_action": "review_cloud_batch_result",
            },
        }
        return CloudBatchRuntimeExecution(result_json=result)


def _extract_items(input_payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = input_payload.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    snapshot = input_payload.get("snapshot")
    if isinstance(snapshot, dict) and isinstance(snapshot.get("items"), list):
        return [item for item in snapshot["items"] if isinstance(item, dict)]
    raise CloudBatchRuntimeContractViolation(
        "cloud_batch_runtime.items_required",
        "cloud batch runtime input requires at least one content item",
    )


def _score_item(item: dict[str, Any], *, sequence: int) -> dict[str, Any]:
    reason_codes: list[str] = []
    title = str(item.get("title") or "").strip()
    excerpt = str(item.get("excerpt") or item.get("summary") or "").strip()
    meta_description = str(item.get("meta_description") or "").strip()
    word_count = _coerce_int(item.get("word_count"), default=0)
    internal_link_count = _coerce_int(item.get("internal_link_count"), default=0)
    image_alt_missing = _coerce_int(item.get("image_alt_missing"), default=0)
    days_since_modified = _coerce_int(item.get("days_since_modified"), default=0)

    score = 100
    if len(title) < 20:
        score -= 12
        reason_codes.append("short_title")
    if not meta_description:
        score -= 14
        reason_codes.append("missing_meta_description")
    elif len(meta_description) < 80:
        score -= 8
        reason_codes.append("short_meta_description")
    if word_count and word_count < 500:
        score -= 10
        reason_codes.append("thin_content")
    if internal_link_count <= 0:
        score -= 9
        reason_codes.append("missing_internal_links")
    if image_alt_missing > 0:
        score -= min(15, 5 * image_alt_missing)
        reason_codes.append("missing_image_alt_text")
    if days_since_modified >= 365:
        score -= 10
        reason_codes.append("stale_content")

    normalized_score = max(0, min(100, score))
    severity = "ok"
    if normalized_score < 60:
        severity = "critical"
    elif normalized_score < 80:
        severity = "warning"

    object_type = str(item.get("object_type") or item.get("post_type") or "post")
    object_id = str(item.get("object_id") or item.get("post_id") or item.get("id") or "")
    return {
        "action_id": f"action_{sequence:03d}",
        "action_type": "content_quality_signal",
        "object_type": object_type,
        "object_id": object_id,
        "title": title or "(untitled)",
        "score": normalized_score,
        "severity": severity,
        "reason_codes": reason_codes,
        "evidence_summary": _build_evidence_summary(reason_codes, excerpt=excerpt),
        "recommended_next_action": (
            "review_update_brief" if severity != "ok" else "no_immediate_action"
        ),
        "direct_wordpress_write": False,
        "status": "succeeded",
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
                "source_object_ids": [action.get("object_id")],
                "opportunity_kind": "refresh_existing_content",
                "evidence_summary": action.get("evidence_summary") or "",
                "forbidden_output_absent": True,
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
        "priorities": priorities,
        "writing_preparation": _build_writing_preparation(actions),
        "safety": {
            "direct_wordpress_write": False,
            "requires_local_review": True,
            "cloud_scheduler_truth": False,
            "article_body_generated": False,
            "article_write_plan_generated": False,
        },
    }


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
