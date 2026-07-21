from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _python_source(root: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))


def _frontend_source(root: Path) -> str:
    suffixes = {".ts", ".tsx", ".js", ".mjs"}
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.rglob("*")
        if path.is_file() and path.suffix in suffixes
    )


def test_b4b3_removes_derivative_download_counter_from_active_surfaces() -> None:
    active_source = _python_source(ROOT / "app") + _frontend_source(ROOT / "frontend/src")
    assert "artifact_download_count" not in active_source
    assert "artifact_last_downloaded_at" not in active_source
    assert "magick-media-observability-summary-v1" not in active_source


def test_b4b3_uses_platform_neutral_delivery_evidence_contract() -> None:
    metrics_source = (ROOT / "app/domain/media_derivatives/metrics.py").read_text(encoding="utf-8")
    normalized_source = " ".join(metrics_source.split())
    for marker in (
        "magick-media-observability-summary-v2",
        "MediaArtifactDelivery",
        "MediaArtifact.operation",
        "MediaArtifact.site_id == MediaArtifactDelivery.site_id",
        "delivery_started_count",
        "delivery_stream_completed_count",
        "delivery_acknowledged_count",
        "stream_completion_rate",
        "acknowledgement_rate",
        '"cms_write_evidence": False',
        '"by_site_limit": 50',
        '"by_site_truncated": delivery_site_truncated',
        ".limit(51)",
    ):
        assert marker in metrics_source
    for expression in (
        "MediaArtifactDelivery.started_at >= start_at",
        "MediaArtifactDelivery.started_at <= current_time",
        "MediaArtifactDelivery.completed_at <= current_time",
        "MediaArtifactDelivery.completed_byte_size == MediaArtifactDelivery.expected_byte_size",
        "MediaArtifactDelivery.completed_checksum == MediaArtifactDelivery.expected_checksum",
        "MediaArtifactDelivery.acked_at <= current_time",
        "MediaArtifactDelivery.acked_at >= MediaArtifactDelivery.completed_at",
        "MediaArtifactDelivery.byte_size_verified.is_(True)",
        "MediaArtifactDelivery.checksum_verified.is_(True)",
        "MediaArtifactDelivery.received_byte_size == MediaArtifactDelivery.expected_byte_size",
        "MediaArtifactDelivery.received_checksum == MediaArtifactDelivery.expected_checksum",
        "delivery_site_count_columns[0].desc()",
    ):
        assert expression in normalized_source
