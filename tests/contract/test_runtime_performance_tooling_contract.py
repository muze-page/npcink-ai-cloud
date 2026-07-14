from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_hot_path_explain_tool_covers_new_runtime_indexes() -> None:
    source = (ROOT / "scripts" / "runtime_hot_path_explain.py").read_text()

    assert "runtime_hot_path_explain.v1" in source
    assert "ix_run_records_status_started_run" in source
    assert "ix_run_records_status_processing_started" in source
    assert "ix_run_records_callback_due" in source
    assert "ix_run_records_callback_dispatching_lease" in source
    assert "direct_wordpress_write" in source
    assert "contains_prompt_or_result_payloads" in source


def test_production_compose_allows_optional_python_package_extras() -> None:
    compose_text = (ROOT / "docker-compose.prod.yml").read_text()

    assert "PACKAGE_EXTRAS: ${NPCINK_CLOUD_PACKAGE_EXTRAS:-}" in compose_text
    assert compose_text.count("PACKAGE_EXTRAS: ${NPCINK_CLOUD_PACKAGE_EXTRAS:-}") == 4


def test_development_runtime_images_include_zilliz_sdk() -> None:
    compose_text = (ROOT / "docker-compose.dev.yml").read_text()

    assert compose_text.count('PACKAGE_EXTRAS: "[dev,zilliz]"') == 4


def test_production_image_packages_runtime_performance_scripts() -> None:
    dockerfile_text = (ROOT / "Dockerfile").read_text()

    assert "COPY scripts ./scripts" in dockerfile_text
    assert dockerfile_text.count("COPY scripts ./scripts") == 2


def test_package_json_exposes_runtime_perf_and_prod_extras_smoke() -> None:
    package_json = json.loads((ROOT / "package.json").read_text())
    scripts = package_json["scripts"]

    assert scripts["perf:runtime-hot-path"].startswith("docker compose")
    assert "--require-indexes" in scripts["perf:runtime-hot-path:require-indexes"]
    assert "--require-indexes" in scripts["perf:production-baseline"]
    assert (
        scripts["perf:production-baseline:ssh"]
        == "bash deploy/production-performance-baseline-to-ssh-host.sh"
    )
    assert scripts["smoke:prod-python-extras"] == "bash scripts/production-python-extras-smoke.sh"


def test_production_python_extras_smoke_checks_default_and_zilliz_images() -> None:
    source = (ROOT / "scripts" / "production-python-extras-smoke.sh").read_text()

    assert "PACKAGE_EXTRAS=" in source
    assert "expected_package_extras" in source
    assert "pymilvus_installed" in source
    assert "NPCINK_CLOUD_PROD_EXTRAS_SKIP_ZILLIZ" in source


def test_production_performance_baseline_is_readonly_and_boundary_labeled() -> None:
    source = (ROOT / "scripts" / "production_performance_baseline.py").read_text()

    assert "production_performance_baseline.v1" in source
    assert "runtime_performance_detail" in source
    assert "direct_wordpress_write" in source
    assert "contains_prompt_or_result_payloads" in source
    assert "contains_provider_secrets" in source
    assert "synthetic_runtime_smoke" in source
    assert "INSERT " not in source
    assert "UPDATE " not in source
    assert "DELETE " not in source


def test_remote_production_performance_baseline_keeps_synthetic_smoke_explicit() -> None:
    remote_source = (ROOT / "deploy" / "remote-performance-baseline.sh").read_text()
    ssh_source = (ROOT / "deploy" / "production-performance-baseline-to-ssh-host.sh").read_text()

    assert "production_performance_baseline.py" in remote_source
    assert "--require-indexes" in remote_source
    assert "NPCINK_CLOUD_PRODUCTION_PERF_ANALYZE" in remote_source
    assert "WITH_SYNTHETIC_SMOKE=0" in ssh_source
    assert "--with-synthetic-smoke" in ssh_source
    assert "remote-smoke.sh" in ssh_source
