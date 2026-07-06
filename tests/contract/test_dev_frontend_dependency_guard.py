from __future__ import annotations

import json
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_dev_frontend_dependencies_are_container_owned() -> None:
    compose_text = (_repo_root() / "docker-compose.dev.yml").read_text()

    assert "./node_modules/.pnpm:/node_modules/.pnpm" not in compose_text
    assert "cloud-frontend-node-modules-dev:/app/node_modules" in compose_text
    assert "cloud-frontend-next-cache-dev:/app/.next" in compose_text
    assert "cloud-frontend-node-modules-dev:" in compose_text
    assert "cloud-frontend-next-cache-dev:" in compose_text


def test_dev_frontend_doctor_and_recover_commands_are_exposed() -> None:
    package_json = json.loads((_repo_root() / "package.json").read_text())
    scripts = package_json["scripts"]

    assert scripts["frontend:doctor"] == "bash scripts/dev-frontend-doctor.sh"
    assert scripts["frontend:recover"] == "bash scripts/dev-frontend-recover.sh"
    assert scripts["frontend:type-check"] == "cd frontend && ./node_modules/.bin/tsc --noEmit"

    doctor_text = (_repo_root() / "scripts/dev-frontend-doctor.sh").read_text()
    recover_text = (_repo_root() / "scripts/dev-frontend-recover.sh").read_text()
    assert "@swc/helpers/package.json" in doctor_text
    assert "next-flight-client-entry-loader" in doctor_text
    assert "Npcink AI Cloud" in doctor_text
    assert "bash scripts/dev-frontend-recover.sh" in doctor_text
    assert "docker volume rm" in recover_text
    assert "cloud-frontend-node-modules-dev" in recover_text


def test_api_dev_reload_ignores_frontend_dependency_churn() -> None:
    compose_text = (_repo_root() / "docker-compose.dev.yml").read_text()

    assert "--reload-dir app" in compose_text
    assert "--reload-dir migrations" in compose_text
    assert "--reload-exclude app/workers/*" in compose_text
    assert "--timeout-graceful-shutdown 5" in compose_text
    assert "--reload-dir frontend" not in compose_text
    assert "--reload-dir node_modules" not in compose_text


def test_dev_stack_does_not_enable_missing_otel_collector_by_default() -> None:
    compose_text = (_repo_root() / "docker-compose.dev.yml").read_text()

    assert "otel-collector:" not in compose_text
    assert (
        "NPCINK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT: "
        "${NPCINK_CLOUD_DEV_OTEL_EXPORTER_OTLP_ENDPOINT:-}"
    ) in compose_text
    assert (
        compose_text.count(
            "NPCINK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT: "
            "${NPCINK_CLOUD_DEV_OTEL_EXPORTER_OTLP_ENDPOINT:-}"
        )
        == 5
    )


def test_pnpm_build_script_policy_is_explicit() -> None:
    workspace_text = (_repo_root() / "pnpm-workspace.yaml").read_text()

    assert "allowBuilds:" in workspace_text
    assert "  esbuild: true" in workspace_text
    assert "  sharp: true" in workspace_text
    assert "  unrs-resolver: true" in workspace_text
    assert "set this to true or false" not in workspace_text
