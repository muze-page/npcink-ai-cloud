from __future__ import annotations

from app.domain.runtime.data_guard import find_runtime_data_guard_finding


def test_cloud_artifact_id_is_not_misclassified_as_pii() -> None:
    finding = find_runtime_data_guard_finding(
        {"source_artifact_id": "art_0123456789abcdef0123456789abcdef"}
    )

    assert finding is None


def test_artifact_id_exemption_requires_full_canonical_match() -> None:
    finding = find_runtime_data_guard_finding(
        {"value": "prefix-art_0123456789abcdef0123456789abcdef"}
    )

    assert finding is not None
    assert finding.kind == "pii"


def test_artifact_id_exemption_does_not_change_secret_field_detection() -> None:
    finding = find_runtime_data_guard_finding(
        {"api_key": "art_0123456789abcdef0123456789abcdef"}
    )

    assert finding is not None
    assert finding.kind == "secret"
    assert finding.code == "secret_field"
