from __future__ import annotations

from typing import Any

# Phrases that imply a write has already been completed to WordPress or WooCommerce.
# If these appear in provider output, the analysis MUST set requires_local_approval=True
# and MUST NOT present the result as an applied write.
WRITE_COMPLETION_PHRASES = frozenset(
    {
        "written to wordpress",
        "changes applied",
        "product updated",
        "已写入 woocommerce",
        "已写入wordpress",
        "changes saved",
        "update completed",
        "write completed",
        "已成功更新",
        "已成功写入",
    }
)

# Ability-name fragments that suggest the run is intended to produce a mutation
# recommendation rather than a read-only report.
WRITE_ABILITY_HINTS = frozenset(
    {
        "write",
        "update",
        "create",
        "delete",
        "apply",
        "modify",
        "publish",
        "optimize",
    }
)

VALID_ANALYSIS_TYPES = frozenset({"report", "recommendation", "proposal_input"})


def build_analysis_result_envelope(
    result: dict[str, Any],
    *,
    ability_family: str,
    ability_name: str,
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    """Post-process a provider result into the Cloud analysis envelope.

    This helper is called from the service layer for runs where the
    ``ability_family`` indicates an Adapter-facing analysis lane
    (currently ``openclaw``). It does not mutate provider adapters.

    The envelope guarantees these top-level fields:

    - ``analysis_type``: ``"report"``, ``"recommendation"``, or ``"proposal_input"``
    - ``summary``: a short human-readable summary
    - ``findings``: list of structured findings (empty if provider gave free text)
    - ``recommendations``: list of recommendations (empty if provider gave free text)
    - ``requires_local_approval``: ``True`` whenever the output implies a WordPress
      mutation or contains write-completion language
    - ``proposal_handoff``: dict carrying correlation ids from the Adapter so that
      Core can create a governed proposal
    - ``_cloud_raw_result``: sanitized provider metadata / debug metadata.
      Dangerous text fields such as ``output_text`` and ``messages`` are removed
      when write-completion language is detected.

    Args:
        result: the raw provider output dict (usually contains ``output_text``,
            ``messages``, ``model_id``, etc.)
        ability_family: the ability family from the run request
        ability_name: the ability name from the run request
        input_payload: the original input payload sent by Adapter

    Returns:
        Either the original ``result`` (when ``ability_family`` is not an analysis
        lane) or a dict wrapped with the analysis envelope.
    """
    if ability_family != "openclaw":
        return result

    # If the provider already returned a well-formed envelope, just ensure the
    # approval flag and handoff are present.
    if isinstance(result, dict) and "analysis_type" in result:
        return _ensure_analysis_envelope_fields(
            dict(result),
            ability_name=ability_name,
            input_payload=input_payload,
        )

    raw_text = str(result.get("output_text", ""))
    requires_local_approval = _detect_write_completion_language(raw_text)
    if not requires_local_approval:
        requires_local_approval = _ability_name_implies_mutation(ability_name)

    analysis_type = "proposal_input" if requires_local_approval else "report"

    if requires_local_approval:
        summary = (
            "Provider output contained write-completion language;"
            " local approval required."
        )
        cloud_raw_result = _sanitize_raw_result(result)
    else:
        summary = raw_text[:2000] if raw_text else ""
        cloud_raw_result = result

    proposal_handoff = _extract_proposal_handoff(input_payload)

    return {
        "analysis_type": analysis_type,
        "summary": summary,
        "findings": [],
        "recommendations": [],
        "requires_local_approval": requires_local_approval,
        "proposal_handoff": proposal_handoff,
        "_cloud_raw_result": cloud_raw_result,
    }


def _ensure_analysis_envelope_fields(
    result: dict[str, Any],
    *,
    ability_name: str,
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    """Ensure an already-structured analysis result has the required guard fields."""
    raw_text = str(result.get("summary", ""))
    requires_local_approval = bool(result.get("requires_local_approval", False))

    if not requires_local_approval:
        requires_local_approval = _detect_write_completion_language(raw_text)
    if not requires_local_approval:
        requires_local_approval = _ability_name_implies_mutation(ability_name)

    if result.get("analysis_type") not in VALID_ANALYSIS_TYPES:
        result["analysis_type"] = "proposal_input" if requires_local_approval else "report"

    result["requires_local_approval"] = requires_local_approval

    if requires_local_approval:
        result["analysis_type"] = "proposal_input"
        if _detect_write_completion_language(raw_text):
            result["summary"] = (
                "Provider output contained write-completion language;"
                " local approval required."
            )
        if "_cloud_raw_result" in result:
            result["_cloud_raw_result"] = _sanitize_raw_result(
                result["_cloud_raw_result"]
            )

    if "proposal_handoff" not in result:
        result["proposal_handoff"] = _extract_proposal_handoff(input_payload)
    else:
        existing_handoff = (
            dict(result["proposal_handoff"])
            if isinstance(result["proposal_handoff"], dict)
            else {}
        )
        for key, value in _extract_proposal_handoff(input_payload).items():
            if key not in existing_handoff:
                existing_handoff[key] = value
        result["proposal_handoff"] = existing_handoff

    return result


def _sanitize_raw_result(result: dict[str, Any]) -> dict[str, Any]:
    """Remove dangerous text fields from a provider result for public exposure."""
    if not isinstance(result, dict):
        return {}
    sanitized = dict(result)
    sanitized.pop("output_text", None)
    sanitized.pop("messages", None)
    return sanitized


def _detect_write_completion_language(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in WRITE_COMPLETION_PHRASES)


def _ability_name_implies_mutation(ability_name: str) -> bool:
    lower = ability_name.lower()
    return any(hint in lower for hint in WRITE_ABILITY_HINTS)


def _extract_proposal_handoff(input_payload: dict[str, Any]) -> dict[str, Any]:
    handoff: dict[str, Any] = {}
    for key in ("proposal_id", "correlation_id", "external_thread_id", "openclaw_thread_id"):
        if key in input_payload:
            handoff[key] = input_payload[key]
    return handoff
