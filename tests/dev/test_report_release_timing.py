import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "report-release-timing.py"
SPEC = importlib.util.spec_from_file_location("report_release_timing", MODULE_PATH)
assert SPEC is not None
report_release_timing = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["report_release_timing"] = report_release_timing
SPEC.loader.exec_module(report_release_timing)

format_duration = report_release_timing.format_duration
summarize = report_release_timing.summarize


def test_release_timing_summary_orders_jobs_by_duration() -> None:
    run = {
        "status": "completed",
        "conclusion": "success",
        "createdAt": "2026-07-08T16:44:41Z",
        "updatedAt": "2026-07-08T17:07:12Z",
        "jobs": [
            {
                "name": "frontend",
                "conclusion": "success",
                "startedAt": "2026-07-08T16:44:50Z",
                "completedAt": "2026-07-08T16:45:35Z",
            },
            {
                "name": "backend",
                "conclusion": "success",
                "startedAt": "2026-07-08T16:44:50Z",
                "completedAt": "2026-07-08T16:52:48Z",
            },
        ],
    }

    summary = summarize(run)

    assert summary["duration"] == "22m31s"
    assert summary["jobs"][0]["name"] == "backend"
    assert summary["jobs"][0]["duration"] == "7m58s"
    assert summary["jobs"][1]["name"] == "frontend"
    assert summary["jobs"][1]["duration"] == "45s"


def test_format_duration_handles_missing_and_seconds() -> None:
    assert format_duration(None) == "n/a"
    assert format_duration(7) == "7s"
    assert format_duration(65) == "1m05s"
