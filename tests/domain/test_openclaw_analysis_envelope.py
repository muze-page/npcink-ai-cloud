from __future__ import annotations

from app.domain.runtime.analysis_result import build_analysis_result_envelope


def test_build_analysis_result_envelope_returns_passthrough_for_non_openclaw():
    result = build_analysis_result_envelope(
        {"output_text": "hello"},
        ability_family="text",
        ability_name="test.ability",
        input_payload={},
    )
    assert result == {"output_text": "hello"}


def test_build_analysis_result_envelope_returns_report_for_read_only():
    result = build_analysis_result_envelope(
        {"output_text": "Analysis of the site shows 3 issues"},
        ability_family="openclaw",
        ability_name="openclaw.site_audit",
        input_payload={},
    )
    assert result["analysis_type"] == "report"
    assert result["requires_local_approval"] is False
    assert result["proposal_handoff"] == {}


def test_build_analysis_result_envelope_returns_proposal_input_for_write_like():
    result = build_analysis_result_envelope(
        {"output_text": "Recommendation: update the WordPress theme"},
        ability_family="openclaw",
        ability_name="openclaw.theme_update",
        input_payload={},
    )
    assert result["analysis_type"] == "proposal_input"
    assert result["requires_local_approval"] is True


def test_build_analysis_result_envelope_proposal_input_not_proposal():
    result = build_analysis_result_envelope(
        {"output_text": "Will create a new post"},
        ability_family="openclaw",
        ability_name="openclaw.create_post",
        input_payload={"proposal_id": "p1", "correlation_id": "c1"},
    )
    assert result["analysis_type"] == "proposal_input"
    assert result["requires_local_approval"] is True
    assert result["proposal_handoff"]["proposal_id"] == "p1"


def test_build_analysis_result_envelope_corrects_invalid_analysis_type():
    result = build_analysis_result_envelope(
        {"analysis_type": "proposal", "summary": "test"},
        ability_family="openclaw",
        ability_name="openclaw.create_post",
        input_payload={},
    )
    assert result["analysis_type"] in {"report", "recommendation", "proposal_input"}


def test_build_analysis_result_envelope_corrects_unknown_analysis_type_to_report():
    result = build_analysis_result_envelope(
        {"analysis_type": "action", "summary": "read-only result"},
        ability_family="openclaw",
        ability_name="openclaw.site_audit",
        input_payload={},
    )
    assert result["analysis_type"] == "report"
