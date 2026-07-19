from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_frontend_has_one_root_workspace_lock() -> None:
    root_package = json.loads(_read("package.json"))
    frontend_package = json.loads(_read("frontend/package.json"))
    root_lock = ROOT / "pnpm-lock.yaml"

    assert root_package["packageManager"] == (
        "pnpm@10.33.0+sha512."
        "10568bb4a6afb58c9eb3630da90cc9516417abebd3fabbe6739f0ae795728da1"
        "491e9db5a544c76ad8eb7570f5c4bb3d6c637b2cb41bfdcdb47fa823c8649319"
    )
    assert "pnpm" not in frontend_package
    assert root_lock.is_file()
    assert not (ROOT / "frontend/pnpm-lock.yaml").exists()
    assert "\n  frontend:\n" in root_lock.read_text(encoding="utf-8")


def test_lock_gate_uses_the_pinned_pnpm_and_real_frozen_install() -> None:
    gate = _read("scripts/check-frontend-lock-sync.js")

    assert "path.resolve(__dirname, '..')" in gate
    assert "frontend/pnpm-lock.yaml must not exist" in gate
    assert "packageManager must pin pnpm with an exact sha512 integrity" in gate
    assert "[0-9a-f]{128}" in gate
    assert "['install', '--frozen-lockfile', '--lockfile-only', '--ignore-scripts']" in gate
    assert "CI: 'true'" in gate
    assert "refresh both lockfiles" not in gate
    assert "--ignore-workspace" not in gate


def test_dev_frontend_build_and_runtime_install_from_root_lock() -> None:
    dockerfile = _read("frontend/Dockerfile.dev")
    compose = _read("docker-compose.dev.yml")

    assert "COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./" in dockerfile
    assert "COPY frontend/package.json ./frontend/package.json" in dockerfile
    assert "corepack enable && corepack install" in dockerfile
    assert "pnpm install --frozen-lockfile --filter frontend..." in dockerfile
    assert "npm install -g pnpm" not in dockerfile
    assert "--no-frozen-lockfile" not in dockerfile

    assert "context: .\n      dockerfile: frontend/Dockerfile.dev" in compose
    assert "pnpm install --frozen-lockfile --filter frontend..." in compose
    assert "./frontend:/app/frontend" in compose
    assert "cloud-frontend-node-modules-dev:/app/frontend/node_modules" in compose
    assert "cloud-frontend-next-cache-dev:/app/frontend/.next" in compose


def test_watch_doctor_and_ci_consume_only_the_root_lock() -> None:
    watch = _read("scripts/watch-cloud-frontend-sync.js")
    doctor = _read("scripts/dev-frontend-doctor.sh")
    workflows = "\n".join(
        _read(relative_path)
        for relative_path in (
            ".github/workflows/ci.yml",
            ".github/workflows/deploy-production.yml",
        )
    )

    assert "path.join( cloudRoot, 'pnpm-lock.yaml' )" in watch
    assert "path.join( cloudRoot, '.dockerignore' )" in watch
    assert "path.join( frontendRoot, '.dockerignore' )" not in watch
    assert "path.join( frontendRoot, 'pnpm-lock.yaml' )" not in watch
    assert "'frontend/pnpm-lock.yaml'" not in watch
    assert "root frontend dependency lock is invalid" in doctor
    assert "/app/frontend/node_modules" in doctor
    assert "/app/node_modules/.pnpm" in doctor

    assert "frontend/pnpm-lock.yaml" not in workflows
    assert workflows.count("cache-dependency-path: pnpm-lock.yaml") == 6
    assert workflows.count('node-version: "22"') == 6
    assert 'node-version: "20"' not in workflows
    assert "pnpm install --frozen-lockfile --filter frontend..." in workflows
    assert "working-directory: frontend" not in workflows
    assert "npm install -g pnpm" not in workflows


def test_frontend_has_no_nested_dead_ci_or_unused_context_ignore() -> None:
    assert not (ROOT / "frontend/.github/workflows/ci-cd.yml").exists()
    assert not (ROOT / "frontend/.dockerignore").exists()
