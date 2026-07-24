from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLASSIFIER = ROOT / "scripts" / "classify-ci-changes.sh"
DOCS_GATE = ROOT / "scripts" / "check-docs-only.sh"
BACKEND_GATE = ROOT / "scripts" / "check-pr-backend-gate.sh"
WEIGHT_REFRESH = ROOT / "scripts" / "refresh-pytest-duration-weights.sh"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _classify(*paths: str) -> dict[str, str]:
    completed = subprocess.run(
        ["bash", str(CLASSIFIER), *paths],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return dict(line.split("=", 1) for line in completed.stdout.splitlines())


def test_ci_change_classifier_is_fail_closed_without_paths() -> None:
    assert _classify() == {
        "deploy_required": "true",
        "static_terms_only": "false",
        "docs_only": "false",
    }


def test_ci_change_classifier_selects_only_safe_documentation_paths() -> None:
    assert _classify(
        "README.md",
        "AGENTS.md",
        "docs/m4-preview-development-v1.md",
        "deploy/OPS_PLAYBOOK.md",
    ) == {
        "deploy_required": "false",
        "static_terms_only": "false",
        "docs_only": "true",
    }

    assert _classify(
        "docs/m4-preview-development-v1.md",
        "tests/contract/test_ci_efficiency_contract.py",
    )["docs_only"] == "false"


def test_ci_change_classifier_preserves_static_terms_and_runtime_boundaries() -> None:
    assert _classify("site/terms/index.html", "site/terms/styles.css") == {
        "deploy_required": "true",
        "static_terms_only": "true",
        "docs_only": "false",
    }

    assert _classify("app/main.py") == {
        "deploy_required": "true",
        "static_terms_only": "false",
        "docs_only": "false",
    }
    assert _classify(".github/workflows/ci.yml") == {
        "deploy_required": "true",
        "static_terms_only": "false",
        "docs_only": "false",
    }


def test_docs_only_scripts_and_workflow_are_fail_closed() -> None:
    subprocess.run(["bash", "-n", str(CLASSIFIER)], cwd=ROOT, check=True)
    subprocess.run(["bash", "-n", str(DOCS_GATE)], cwd=ROOT, check=True)

    docs_gate = DOCS_GATE.read_text(encoding="utf-8")
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "git -C" in docs_gate
    assert "mapfile" not in docs_gate
    assert "changed_files+=(\"${changed_file}\")" in docs_gate
    assert "--diff-filter=ACMRD" in docs_gate
    assert "diff --check" in docs_gate
    assert "check-release-policy.sh" in docs_gate
    assert "docs_only=true" in docs_gate
    assert "received a non-documentation change" in docs_gate

    assert "docs_only: ${{ steps.changed.outputs.docs_only }}" in workflow
    assert workflow.count("--diff-filter=ACMRD") == 3
    assert "bash scripts/classify-ci-changes.sh" in workflow
    assert "bash scripts/check-docs-only.sh" in workflow
    assert "Docs-only frontend acknowledgement" in workflow
    assert "python dependency audit should be skipped for docs-only changes" in workflow


@pytest.mark.skipif(
    not (ROOT / ".git").exists(),
    reason="CI-only Git diff contract requires repository metadata omitted from M4 bundles",
)
def test_docs_only_gate_runs_fail_closed_with_system_bash() -> None:
    environment = os.environ.copy()
    environment["NPCINK_CLOUD_CI_BASE_SHA"] = "origin/master"
    environment["NPCINK_CLOUD_CI_HEAD_SHA"] = "HEAD"

    completed = subprocess.run(
        ["/bin/bash", str(DOCS_GATE)],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert (
        "docs-only gate received no changed files" in completed.stderr
        or "docs-only gate received a non-documentation change" in completed.stderr
    )
    assert "command not found" not in completed.stderr


def test_targeted_backend_gate_times_contracts_without_rerunning_changed_contracts() -> None:
    source = BACKEND_GATE.read_text(encoding="utf-8")
    changed_test_selection = source.split(
        'while IFS= read -r path; do',
        1,
    )[1].split(
        'done < "${TMP_CHANGED}"',
        1,
    )[0]

    assert "pytest tests/contract -q --durations=25" in source
    assert "tests/contract/test_*.py" not in changed_test_selection
    assert "contract files are already covered" in source


def test_pytest_weight_refresh_is_reproducible_and_fail_closed() -> None:
    subprocess.run(["bash", "-n", str(WEIGHT_REFRESH)], cwd=ROOT, check=True)
    help_result = subprocess.run(
        ["bash", str(WEIGHT_REFRESH), "--", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    source = WEIGHT_REFRESH.read_text(encoding="utf-8")
    package = (ROOT / "package.json").read_text(encoding="utf-8")

    assert "ci:pytest:weights:refresh" in help_result.stdout
    assert "EXPECTED_SHARDS=3" in source
    assert "gh run download" in source
    assert "pytest-backend-timing-shard-*" in source
    assert "write-pytest-duration-weights.py" in source
    assert "expected ${EXPECTED_SHARDS} pytest shard reports" in source
    assert 'mv "${OUTPUT_TEMP}" "${ROOT_DIR}/ci/pytest-backend-durations.json"' in source
    assert '"ci:pytest:weights:refresh"' in package
