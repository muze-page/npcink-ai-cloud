from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from app.domain.site_ops_analysis.contracts import (
    SITE_OPS_ANALYSIS_RESULT_CONTRACT,
    validate_site_ops_analysis_runtime_contract,
)


@dataclass(slots=True)
class SiteOpsAnalysisExecutionResult:
    result_json: dict[str, Any]


class SiteOpsAnalysisService:
    def execute(
        self,
        *,
        site_id: str,
        ability_name: str,
        contract_version: str,
        input_payload: dict[str, Any],
        run_id: str,
    ) -> SiteOpsAnalysisExecutionResult:
        validate_site_ops_analysis_runtime_contract(
            ability_name=ability_name,
            contract_version=contract_version,
            input_payload=input_payload,
        )
        request_input = _dict(input_payload.get("input"))
        local_findings = _list(request_input.get("local_findings"))
        sample_summaries = _dict(request_input.get("sample_summaries"))
        blocked_items = _list(request_input.get("blocked_items"))
        priority_queue = _priority_queue(local_findings, sample_summaries)
        normalized_blocked_items = _blocked_items(blocked_items, request_input)
        dimension_summaries = _dimension_summaries(
            local_findings,
            sample_summaries,
            priority_queue,
        )
        trend_notes = _trend_notes(sample_summaries)
        trend_explanations = _trend_explanations(trend_notes, sample_summaries)
        result = {
            "contract_version": SITE_OPS_ANALYSIS_RESULT_CONTRACT,
            "artifact_type": "site_ops_cloud_analysis_result",
            "status": "ready",
            "site_id": site_id,
            "analysis_id": f"site_ops_{_hash_text(f'{site_id}:{run_id}')[:24]}",
            "source": {
                "provider": "npcink_ai_cloud",
                "provider_mode": "deterministic_site_ops_analyzer",
                "request_contract": contract_version,
                "source_pack_contract": _text(input_payload.get("source_pack_contract")),
                "request_id_hash": _hash_text(_text(input_payload.get("request_id"))),
            },
            "executive_summary": _executive_summary(
                priority_queue,
                dimension_summaries,
                normalized_blocked_items,
            ),
            "priority_queue": priority_queue,
            "dimension_summaries": dimension_summaries,
            "semantic_ranked_findings": _semantic_ranked_findings(priority_queue),
            "trend_notes": trend_notes,
            "trend_explanations": trend_explanations,
            "confidence": _confidence(sample_summaries, priority_queue),
            "blocked_items": normalized_blocked_items,
            "core_handoff_candidates": _core_handoff_candidates(priority_queue),
            "operator_next_actions": _operator_next_actions(
                priority_queue,
                normalized_blocked_items,
            ),
            "analysis_closure": _analysis_closure(
                priority_queue,
                dimension_summaries,
                normalized_blocked_items,
            ),
            "safety": {
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
                "core_proposal_created": False,
                "cloud_scheduler_truth": False,
                "wordpress_write_owner": "core_proposal_approval",
                "operator_review_required": True,
                "comment_text_returned": False,
                "private_comment_author_contact_returned": False,
                "private_comment_network_metadata_returned": False,
            },
            "write_posture": "suggestion_only",
            "direct_wordpress_write": False,
            "core_proposal_created": False,
        }
        return SiteOpsAnalysisExecutionResult(result_json=result)


def _priority_queue(
    local_findings: list[Any],
    sample_summaries: dict[str, Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for finding in local_findings:
        if not isinstance(finding, dict):
            continue
        priority_score = _coerce_int(finding.get("priority_score"))
        issue_type = _key(finding.get("issue_type"))
        score = min(100, priority_score + _issue_boost(issue_type, sample_summaries))
        reason_codes = _reason_codes(issue_type, sample_summaries)
        items.append(
            {
                "finding_id": _key(finding.get("id")) or "finding",
                "issue_type": issue_type,
                "severity": _key(finding.get("severity")) or _severity_from_score(score),
                "cloud_priority_score": score,
                "local_priority_score": priority_score,
                "reason_codes": reason_codes,
                "evidence_summary": _clean_text(finding.get("evidence_summary"), limit=600),
                "recommended_action": _clean_text(finding.get("recommended_action"), limit=600),
                "write_boundary": _key(finding.get("write_boundary")) or "suggestion_only",
                "source_refs": _source_refs(_list(finding.get("source_refs"))),
            }
        )
    items.sort(key=lambda item: (-int(item["cloud_priority_score"]), str(item["finding_id"])))
    for index, item in enumerate(items, start=1):
        item["rank"] = index
    return items[:8]


def _trend_notes(sample_summaries: dict[str, Any]) -> list[dict[str, Any]]:
    posts = _dict(sample_summaries.get("posts"))
    media = _dict(sample_summaries.get("media"))
    comments = _dict(sample_summaries.get("comments"))
    taxonomies = _dict(sample_summaries.get("taxonomies"))
    category = _dict(taxonomies.get("category"))
    tag = _dict(taxonomies.get("post_tag"))
    notes: list[dict[str, Any]] = []
    if _coerce_int(posts.get("stale_180d_count")) > 0:
        notes.append(
            {
                "id": "content_refresh_trend",
                "summary": (
                    "Sampled content includes stale public items that should be reviewed "
                    "before new production."
                ),
                "signal_count": _coerce_int(posts.get("stale_180d_count")),
            }
        )
    if _coerce_int(comments.get("question_like_count")) > 0:
        notes.append(
            {
                "id": "comment_question_trend",
                "summary": (
                    "Approved public comments show repeated question-like demand without "
                    "exposing raw comment text."
                ),
                "signal_count": _coerce_int(comments.get("question_like_count")),
            }
        )
    media_gap = _coerce_int(media.get("missing_alt_count")) + _coerce_int(
        media.get("referenced_alt_gap_count")
    )
    if media_gap > 0:
        notes.append(
            {
                "id": "media_metadata_trend",
                "summary": (
                    "Media metadata gaps are visible in attachment and referenced-image "
                    "samples."
                ),
                "signal_count": media_gap,
            }
        )
    taxonomy_gap = (
        _coerce_int(category.get("empty_count"))
        + _coerce_int(category.get("low_count"))
        + _coerce_int(tag.get("empty_count"))
        + _coerce_int(tag.get("low_count"))
    )
    if taxonomy_gap > 0:
        notes.append(
            {
                "id": "taxonomy_drift_trend",
                "summary": (
                    "Sparse or empty taxonomy terms may weaken discovery and recommendation "
                    "quality."
                ),
                "signal_count": taxonomy_gap,
            }
        )
    return notes


def _executive_summary(
    priority_queue: list[dict[str, Any]],
    dimension_summaries: list[dict[str, Any]],
    blocked_items: list[dict[str, Any]],
) -> dict[str, Any]:
    primary = priority_queue[0] if priority_queue else {}
    active_dimensions = [
        str(item["dimension"])
        for item in dimension_summaries
        if int(item.get("finding_count") or 0) > 0 or int(item.get("signal_score") or 0) > 0
    ]
    primary_focus = str(primary.get("finding_id") or "")
    if not primary_focus and active_dimensions:
        primary_focus = active_dimensions[0]
    if not primary_focus:
        primary_focus = "collect_stronger_site_context"

    return {
        "headline": _summary_headline(priority_queue, blocked_items),
        "primary_focus": primary_focus,
        "affected_dimensions": active_dimensions[:4],
        "operator_sequence": _operator_sequence(priority_queue, blocked_items),
        "cloud_role": "runtime_detail",
        "write_posture": "suggestion_only",
        "summary": _summary_sentence(priority_queue, active_dimensions, blocked_items),
    }


def _dimension_summaries(
    local_findings: list[Any],
    sample_summaries: dict[str, Any],
    priority_queue: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    dimensions = [
        (
            "content",
            {"content_freshness", "content_quality", "metadata"},
            _content_signal_score(sample_summaries),
            "Review stale, thin, and weakly connected public content before scaling output.",
        ),
        (
            "media",
            {"media"},
            _media_signal_score(sample_summaries),
            "Review image ALT/caption gaps and referenced media metadata as a bounded set.",
        ),
        (
            "comments",
            {"comments"},
            _comment_signal_score(sample_summaries),
            "Review approved-comment demand signals without exposing raw comment text.",
        ),
        (
            "structure",
            {"taxonomy", "site_context", "site_knowledge"},
            _structure_signal_score(sample_summaries),
            "Review taxonomy shape, Site Context readiness, and Cloud Site Knowledge readiness.",
        ),
    ]
    queued_by_type = {
        str(item.get("issue_type") or ""): item
        for item in priority_queue
        if isinstance(item, dict)
    }
    summaries: list[dict[str, Any]] = []
    for dimension, issue_types, signal_score, guidance in dimensions:
        findings = [
            finding
            for finding in local_findings
            if isinstance(finding, dict) and _key(finding.get("issue_type")) in issue_types
        ]
        top_score = max(
            [signal_score]
            + [
                int(queued_by_type.get(issue_type, {}).get("cloud_priority_score") or 0)
                for issue_type in issue_types
            ]
        )
        summaries.append(
            {
                "dimension": dimension,
                "finding_count": len(findings),
                "signal_score": min(100, top_score),
                "priority": _dimension_priority(top_score, len(findings)),
                "summary": _dimension_summary_text(dimension, len(findings), signal_score),
                "recommended_next": guidance,
                "write_posture": "suggestion_only",
            }
        )
    return summaries


def _semantic_ranked_findings(priority_queue: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in priority_queue:
        issue_type = _key(item.get("issue_type"))
        items.append(
            {
                "rank": int(item.get("rank") or 0),
                "finding_id": str(item.get("finding_id") or ""),
                "semantic_cluster": _semantic_cluster(issue_type),
                "reason": _semantic_reason(issue_type, _list(item.get("reason_codes"))),
                "score": int(item.get("cloud_priority_score") or 0),
                "recommended_action": str(item.get("recommended_action") or ""),
                "write_boundary": str(item.get("write_boundary") or "suggestion_only"),
            }
        )
    return items


def _trend_explanations(
    trend_notes: list[dict[str, Any]],
    sample_summaries: dict[str, Any],
) -> list[dict[str, Any]]:
    explanations: list[dict[str, Any]] = []
    for note in trend_notes:
        note_id = _key(note.get("id"))
        explanations.append(
            {
                "id": note_id or "trend",
                "summary": str(note.get("summary") or ""),
                "operator_impact": _trend_operator_impact(note_id),
                "next_check": _trend_next_check(note_id),
                "signal_count": _coerce_int(note.get("signal_count")),
            }
        )
    if not explanations and _total_sample_size(sample_summaries) == 0:
        explanations.append(
            {
                "id": "insufficient_signal",
                "summary": "No aggregate signal was strong enough for trend explanation.",
                "operator_impact": (
                    "Run the local scan after more public content evidence is available."
                ),
                "next_check": "complete_site_context_and_repeat_local_preview",
                "signal_count": 0,
            }
        )
    return explanations[:6]


def _analysis_closure(
    priority_queue: list[dict[str, Any]],
    dimension_summaries: list[dict[str, Any]],
    blocked_items: list[dict[str, Any]],
) -> dict[str, Any]:
    covered_dimensions = [
        str(item["dimension"])
        for item in dimension_summaries
        if int(item.get("finding_count") or 0) > 0 or int(item.get("signal_score") or 0) > 0
    ]
    if blocked_items:
        loop_status = "blocked_until_operator_review"
    elif priority_queue:
        loop_status = "ready_for_operator_prioritization"
    else:
        loop_status = "no_priority_findings"
    return {
        "loop_status": loop_status,
        "covered_dimensions": covered_dimensions,
        "answered_questions": [
            "which_site_areas_need_attention",
            "which_findings_should_be_reviewed_first",
            "which_items_are_only_planning_hints",
        ],
        "cloud_only_reasons": [
            "cross_run_trend_explanation",
            "semantic_ranking",
            "heavier_runtime_detail",
        ],
        "next_step": _closure_next_step(loop_status),
        "core_proposal_created": False,
        "direct_wordpress_write": False,
    }


def _confidence(
    sample_summaries: dict[str, Any],
    priority_queue: list[dict[str, Any]],
) -> dict[str, Any]:
    posts = _dict(sample_summaries.get("posts"))
    media = _dict(sample_summaries.get("media"))
    comments = _dict(sample_summaries.get("comments"))
    sample_size = (
        _coerce_int(posts.get("sampled_count"))
        + _coerce_int(media.get("sampled_count"))
        + _coerce_int(comments.get("recent_sample_count"))
    )
    level = "low"
    if sample_size >= 30 and priority_queue:
        level = "high"
    elif sample_size >= 10 or priority_queue:
        level = "medium"
    return {
        "level": level,
        "sample_size": sample_size,
        "method": "deterministic_aggregate_signal_scoring",
        "limitations": [
            "No raw comment text was used.",
            "No private WordPress content was used.",
            "No WordPress writes or Core proposals were created.",
        ],
    }


def _blocked_items(blocked_items: list[Any], request_input: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in blocked_items:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "id": _key(item.get("id")) or "blocked_item",
                "reason": _key(item.get("reason")) or "review_required",
                "next": _key(item.get("next")) or "operator_review",
            }
        )
    operator_context = _dict(request_input.get("operator_context"))
    if operator_context and not bool(operator_context.get("content_context_ready")):
        items.append(
            {
                "id": "site_context_brief",
                "reason": "content_context_incomplete",
                "next": "complete_site_context_before_repeating_analysis",
            }
        )
    return items[:8]


def _core_handoff_candidates(priority_queue: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in priority_queue:
        if item.get("write_boundary") != "core_handoff_candidate":
            continue
        candidates.append(
            {
                "finding_id": item["finding_id"],
                "proposal_ready": False,
                "operator_review_required": True,
                "suggested_handoff": "prepare_core_proposal_after_operator_selection",
                "direct_wordpress_write": False,
                "core_proposal_created": False,
            }
        )
    return candidates[:5]


def _operator_next_actions(
    priority_queue: list[dict[str, Any]],
    blocked_items: list[Any],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if blocked_items:
        actions.append(
            {
                "id": "clear_blockers",
                "label": "Review blocked prerequisites",
                "target": "blocked_items",
            }
        )
    for item in priority_queue[:3]:
        actions.append(
            {
                "id": f"review_{item['finding_id']}",
                "label": item.get("recommended_action") or "Review finding",
                "target": item["finding_id"],
            }
        )
    return actions[:5]


def _issue_boost(issue_type: str, sample_summaries: dict[str, Any]) -> int:
    posts = _dict(sample_summaries.get("posts"))
    media = _dict(sample_summaries.get("media"))
    comments = _dict(sample_summaries.get("comments"))
    if issue_type == "comments" and _coerce_int(comments.get("question_like_count")) >= 3:
        return 8
    if issue_type == "content_freshness" and _coerce_int(posts.get("commented_item_count")) > 0:
        return 6
    if issue_type == "media" and _coerce_int(media.get("missing_alt_count")) >= 5:
        return 6
    return 0


def _reason_codes(issue_type: str, sample_summaries: dict[str, Any]) -> list[str]:
    posts = _dict(sample_summaries.get("posts"))
    media = _dict(sample_summaries.get("media"))
    comments = _dict(sample_summaries.get("comments"))
    codes = [issue_type or "local_signal"]
    if _coerce_int(comments.get("question_like_count")) > 0:
        codes.append("comment_question_signal")
    if _coerce_int(posts.get("stale_180d_count")) > 0:
        codes.append("stale_content_signal")
    if _coerce_int(media.get("missing_alt_count")) > 0:
        codes.append("media_metadata_gap")
    return sorted(set(codes))


def _summary_headline(
    priority_queue: list[dict[str, Any]],
    blocked_items: list[dict[str, Any]],
) -> str:
    if blocked_items:
        return "Review blockers before turning findings into an action plan."
    if priority_queue:
        return "Prioritize the strongest full-site signals before creating new work."
    return "No priority full-site findings were detected in the current aggregate sample."


def _summary_sentence(
    priority_queue: list[dict[str, Any]],
    active_dimensions: list[str],
    blocked_items: list[dict[str, Any]],
) -> str:
    if blocked_items:
        return "The analysis found prerequisites that should be cleared before repeated review."
    if priority_queue:
        dimension_text = ", ".join(active_dimensions[:4]) or "the sampled site data"
        return (
            f"Cloud runtime/detail ranked {len(priority_queue)} findings across "
            f"{dimension_text}; review the first item before expanding work."
        )
    return "The current aggregate sample is reviewable, but it did not produce a priority queue."


def _operator_sequence(
    priority_queue: list[dict[str, Any]],
    blocked_items: list[dict[str, Any]],
) -> list[str]:
    sequence: list[str] = []
    if blocked_items:
        sequence.append("clear_blocked_prerequisites")
    if priority_queue:
        sequence.append("review_top_ranked_finding")
        sequence.append("select_manual_or_core_handoff_path")
    else:
        sequence.append("refresh_local_scan_after_context_changes")
    sequence.append("keep_wordpress_writes_in_core_governance")
    return sequence


def _dimension_priority(score: int, finding_count: int) -> str:
    if score >= 80 or finding_count >= 2:
        return "high"
    if score >= 40 or finding_count == 1:
        return "medium"
    return "low"


def _dimension_summary_text(dimension: str, finding_count: int, signal_score: int) -> str:
    if finding_count > 0:
        return f"{dimension} has {finding_count} ranked finding(s) in the current request."
    if signal_score > 0:
        return f"{dimension} has aggregate signals but no ranked local finding."
    return f"{dimension} has no priority signal in the current aggregate sample."


def _semantic_cluster(issue_type: str) -> str:
    if issue_type in {"content_freshness", "content_quality", "metadata"}:
        return "content_quality_and_discoverability"
    if issue_type == "media":
        return "media_accessibility_and_reuse"
    if issue_type == "comments":
        return "audience_demand_signal"
    if issue_type in {"taxonomy", "site_context", "site_knowledge"}:
        return "site_structure_and_context"
    return "general_site_review"


def _semantic_reason(issue_type: str, reason_codes: list[Any]) -> str:
    codes = {_key(code) for code in reason_codes}
    if issue_type == "media" or "media_metadata_gap" in codes:
        return "Media metadata affects accessibility, reuse, and evidence quality."
    if issue_type == "comments" or "comment_question_signal" in codes:
        return "Approved comment signals can reveal unanswered audience needs."
    if issue_type == "content_freshness" or "stale_content_signal" in codes:
        return "Older active content should be refreshed before expanding similar work."
    return "This finding is ranked from aggregate local evidence and operator review value."


def _trend_operator_impact(note_id: str) -> str:
    impacts = {
        "content_refresh_trend": "Refresh planning should start with active stale pages.",
        "comment_question_trend": "Repeated questions can become FAQ or article-refresh work.",
        "media_metadata_trend": "Accessibility and media search quality may be weaker.",
        "taxonomy_drift_trend": "Sparse vocabulary can fragment discovery and recommendations.",
    }
    return impacts.get(note_id, "Review the aggregate signal before creating new work.")


def _trend_next_check(note_id: str) -> str:
    checks = {
        "content_refresh_trend": "compare_stale_items_with_recent_comment_activity",
        "comment_question_trend": "group_repeated_comment_questions_without_raw_text",
        "media_metadata_trend": "sample_media_alt_and_caption_review_set",
        "taxonomy_drift_trend": "review_empty_and_low_use_terms",
    }
    return checks.get(note_id, "repeat_cloud_detail_after_next_local_scan")


def _closure_next_step(loop_status: str) -> str:
    if loop_status == "blocked_until_operator_review":
        return "clear_blocked_items_then_repeat_cloud_analysis"
    if loop_status == "ready_for_operator_prioritization":
        return "review_top_ranked_finding_then_choose_manual_or_core_handoff"
    return "keep_as_current_snapshot_or_refresh_after_site_changes"


def _content_signal_score(sample_summaries: dict[str, Any]) -> int:
    posts = _dict(sample_summaries.get("posts"))
    return min(
        100,
        _coerce_int(posts.get("stale_180d_count")) * 8
        + _coerce_int(posts.get("short_content_count")) * 6
        + _coerce_int(posts.get("no_internal_link_count")) * 5
        + _coerce_int(posts.get("commented_item_count")) * 4,
    )


def _media_signal_score(sample_summaries: dict[str, Any]) -> int:
    media = _dict(sample_summaries.get("media"))
    return min(
        100,
        _coerce_int(media.get("missing_alt_count")) * 8
        + _coerce_int(media.get("missing_caption_count")) * 4
        + _coerce_int(media.get("referenced_alt_gap_count")) * 6,
    )


def _comment_signal_score(sample_summaries: dict[str, Any]) -> int:
    comments = _dict(sample_summaries.get("comments"))
    return min(
        100,
        _coerce_int(comments.get("question_like_count")) * 10
        + _coerce_int(comments.get("long_comment_count")) * 4
        + _coerce_int(comments.get("pending_total")) * 3,
    )


def _structure_signal_score(sample_summaries: dict[str, Any]) -> int:
    taxonomies = _dict(sample_summaries.get("taxonomies"))
    category = _dict(taxonomies.get("category"))
    tag = _dict(taxonomies.get("post_tag"))
    return min(
        100,
        _coerce_int(category.get("empty_count")) * 6
        + _coerce_int(category.get("low_count")) * 5
        + _coerce_int(tag.get("empty_count")) * 4
        + _coerce_int(tag.get("low_count")) * 3,
    )


def _total_sample_size(sample_summaries: dict[str, Any]) -> int:
    posts = _dict(sample_summaries.get("posts"))
    media = _dict(sample_summaries.get("media"))
    comments = _dict(sample_summaries.get("comments"))
    return (
        _coerce_int(posts.get("sampled_count"))
        + _coerce_int(media.get("sampled_count"))
        + _coerce_int(comments.get("recent_sample_count"))
    )


def _source_refs(refs: list[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for ref in refs[:5]:
        if not isinstance(ref, dict):
            continue
        items.append(
            {
                "object_type": _key(ref.get("object_type")) or "post",
                "object_id": max(0, _coerce_int(ref.get("object_id"))),
                "title": _clean_text(ref.get("title"), limit=160),
            }
        )
    return items


def _severity_from_score(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _key(value: Any) -> str:
    raw = _text(value).lower().replace(" ", "_")
    return "".join(ch for ch in raw if ch.isalnum() or ch in {"_", "-"})


def _clean_text(value: Any, *, limit: int) -> str:
    return " ".join(_text(value).split())[:limit]


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
