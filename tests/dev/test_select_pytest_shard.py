from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str, filename: str):
    module_path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, module_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


select_pytest_shard = _load_script("select_pytest_shard", "select-pytest-shard.py")
write_pytest_duration_weights = _load_script(
    "write_pytest_duration_weights",
    "write-pytest-duration-weights.py",
)


def test_weighted_shards_balance_slowest_files_first(tmp_path: Path) -> None:
    tests_root = tmp_path / "tests" / "api"
    tests_root.mkdir(parents=True)
    for name in ("test_a.py", "test_b.py", "test_c.py", "test_d.py"):
        (tests_root / name).write_text("def test_placeholder(): pass\n", encoding="utf-8")

    files = select_pytest_shard.discover_test_files([tests_root])
    weights = {
        f"{tests_root.as_posix()}/test_a.py": 10,
        f"{tests_root.as_posix()}/test_b.py": 8,
        f"{tests_root.as_posix()}/test_c.py": 2,
        f"{tests_root.as_posix()}/test_d.py": 1,
    }

    shards = select_pytest_shard.assign_files(files, weights, shard_count=2)

    assert [path.name for path in shards[0].files] == ["test_a.py", "test_d.py"]
    assert [path.name for path in shards[1].files] == [
        "test_b.py",
        "test_c.py",
    ]


def test_junit_report_writes_per_file_weights(tmp_path: Path) -> None:
    report = tmp_path / "pytest.xml"
    report.write_text(
        """
<testsuite>
  <testcase classname="tests.api.test_runtime" name="test_one" time="1.25" />
  <testcase classname="tests.api.test_runtime" name="test_two" time="2" />
  <testcase classname="tests.api.test_auth.TestDecodePortalBearerToken"
            name="test_decode" time="0.75" />
  <testcase classname="tests.contract.test_release" name="test_release" time="0.5" />
</testsuite>
""",
        encoding="utf-8",
    )

    payload = write_pytest_duration_weights.build_payload(report, "fixture")

    assert payload == {
        "schema": "pytest-duration-weights-v1",
        "source": "fixture",
        "weights": {
            "tests/api/test_auth.py": 0.75,
            "tests/api/test_runtime.py": 3.25,
            "tests/contract/test_release.py": 0.5,
        },
    }


def test_junit_reports_merge_per_file_weights_across_shards(tmp_path: Path) -> None:
    first = tmp_path / "first.xml"
    second = tmp_path / "second.xml"
    first.write_text(
        """
<testsuite>
  <testcase classname="tests.contract.test_release" name="test_one" time="2" />
</testsuite>
""",
        encoding="utf-8",
    )
    second.write_text(
        """
<testsuite>
  <testcase classname="tests.contract.test_release" name="test_two" time="3" />
  <testcase classname="tests.domain.test_runtime" name="test_three" time="1" />
</testsuite>
""",
        encoding="utf-8",
    )

    payload = write_pytest_duration_weights.build_payload([first, second], "fixture shards")

    assert payload["source"] == "fixture shards"
    assert payload["weights"] == {
        "tests/contract/test_release.py": 5.0,
        "tests/domain/test_runtime.py": 1.0,
    }
