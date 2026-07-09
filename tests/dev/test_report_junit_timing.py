import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "report-junit-timing.py"
SPEC = importlib.util.spec_from_file_location("report_junit_timing", MODULE_PATH)
assert SPEC is not None
report_junit_timing = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["report_junit_timing"] = report_junit_timing
SPEC.loader.exec_module(report_junit_timing)

collect_test_timings = report_junit_timing.collect_test_timings
render_markdown = report_junit_timing.render_markdown
summarize = report_junit_timing.summarize


def test_junit_timing_summary_orders_slowest_cases(tmp_path: Path) -> None:
    report = tmp_path / "pytest.xml"
    report.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="3">
  <testcase classname="tests.api.test_runtime" name="test_fast" time="0.012" />
  <testcase classname="tests.api.test_runtime" name="test_slow" time="1.237" />
  <testcase classname="tests.contract.test_release" name="test_medium" time="0.500" />
</testsuite>
""",
        encoding="utf-8",
    )

    summary = summarize(report, top=2)

    assert summary["count"] == 3
    assert summary["total_seconds"] == 1.749
    assert summary["slowest"] == [
        {"name": "tests.api.test_runtime::test_slow", "seconds": 1.237},
        {"name": "tests.contract.test_release::test_medium", "seconds": 0.5},
    ]


def test_junit_timing_renderer_uses_markdown_table(tmp_path: Path) -> None:
    report = tmp_path / "pytest.xml"
    report.write_text(
        """
<testsuite>
  <testcase classname="tests.domain.test_a" name="test_one" time="2" />
</testsuite>
""",
        encoding="utf-8",
    )

    markdown = render_markdown(summarize(report, top=1))

    assert "## Pytest Timing Report" in markdown
    assert "| `tests.domain.test_a::test_one` | 2.000 |" in markdown
