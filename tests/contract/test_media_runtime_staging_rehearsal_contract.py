from __future__ import annotations

import json
import os
import re
import shlex
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/media-runtime-staging-rehearsal.sh"
CONTROL_ENV_KEYS = (
    "COMPOSE_PROJECT_NAME",
    "COMPOSE_FILE",
    "COMPOSE_ENV_FILES",
    "ENV_FILE",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_CONFIG",
    "NPCINK_CLOUD_COMPOSE_PROJECT_NAME",
    "NPCINK_CLOUD_COMPOSE_FILE",
    "NPCINK_CLOUD_ENV_FILE",
    "NPCINK_CLOUD_DEPLOY_SMOKE_BASE_URL",
    "NPCINK_CLOUD_DEPLOY_SMOKE_PORT",
    "NPCINK_CLOUD_BASE_URL",
    "NPCINK_CLOUD_PORT",
    "CLOUD_API_BASE_URL",
    "CLOUD_PUBLIC_BASE_URL",
    "NPCINK_CLOUD_ENVIRONMENT",
    "NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_ENABLED",
    "NPCINK_CLOUD_DEPLOY_SMOKE_KEEP",
    "NPCINK_CLOUD_DEPLOY_SMOKE_SKIP_BUILD",
    "NPCINK_CLOUD_SKIP_FRONTEND_IMAGE",
)
SENSITIVE_ENV_KEYS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "MAGICK_CLOUD_API_KEY",
    "MAGICK_CLOUD_BASE_URL",
    "DATABASE_URL",
    "POSTGRES_PASSWORD",
    "PGHOST",
    "REDIS_URL",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "JAEGER_ENDPOINT",
    "NPCINK_CLOUD_SITE_ID",
    "NPCINK_CLOUD_KEY_ID",
    "NPCINK_CLOUD_SECRET",
    "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN",
    "NPCINK_CLOUD_OPENAI_API_KEY",
    "NPCINK_CLOUD_PROVIDER_BASE_URL",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
)


def _run(
    *arguments: str,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key in CONTROL_ENV_KEYS:
        env.pop(key, None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(SCRIPT), *arguments],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _write_fake_toolchain(
    tmp_path: Path,
    *,
    fail_gate: str = "",
    docker_endpoint: str = "unix:///var/run/docker.sock",
) -> tuple[Path, Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    pnpm_log = tmp_path / "pnpm.log"
    docker_log = tmp_path / "docker.log"

    forbidden_checks = "\n".join(
        f'if [[ -n "${{{name}+x}}" ]]; then exit 91; fi'
        for name in SENSITIVE_ENV_KEYS
    )
    fail_check = ""
    if fail_gate:
        fail_check = (
            f'if [[ "$*" == {shlex.quote(f"run {fail_gate}")} ]]; then exit 47; fi\n'
        )
    fake_pnpm = fake_bin / "pnpm"
    fake_pnpm.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "[[ \"${MEDIA_RUNTIME_REHEARSAL_ENV_SENTINEL:-}\" == "
        "\"media-runtime-disposable-local-v1\" ]] || exit 90\n"
        "[[ \"${NPCINK_CLOUD_ENVIRONMENT:-}\" == \"test\" ]] || exit 92\n"
        "[[ \"${NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_ENABLED:-}\" == "
        "\"false\" ]] || exit 93\n"
        "[[ \"${NPCINK_CLOUD_SKIP_FRONTEND_IMAGE:-}\" == \"0\" ]] || exit 94\n"
        f"{forbidden_checks}\n"
        f"printf '%s\\n' \"$*\" >> {shlex.quote(str(pnpm_log))}\n"
        f"{fail_check}"
    )
    fake_pnpm.chmod(0o700)

    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "[[ \"${MEDIA_RUNTIME_REHEARSAL_ENV_SENTINEL:-}\" == "
        "\"media-runtime-disposable-local-v1\" ]] || exit 90\n"
        f"printf '%s\\n' \"$*\" >> {shlex.quote(str(docker_log))}\n"
        "case \"${1:-} ${2:-}\" in\n"
        "  \"context show\") printf 'desktop-linux\\n' ;;\n"
        f"  \"context inspect\") printf '%s\\n' {shlex.quote(docker_endpoint)} ;;\n"
        "  \"info \" ) exit 0 ;;\n"
        "  *) exit 95 ;;\n"
        "esac\n"
    )
    fake_docker.chmod(0o700)
    return fake_bin, pnpm_log, docker_log


def test_rehearsal_delegates_existing_gates_and_freezes_environment() -> None:
    script = SCRIPT.read_text()
    package_scripts = json.loads((ROOT / "package.json").read_text())["scripts"]

    assert SCRIPT.stat().st_mode & stat.S_IXUSR
    assert script.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert 'TARGET="local-staging"' in script
    assert '[[ "${TARGET}" != "local-staging" ]]' in script
    assert "env -i" in script
    assert 'REHEARSAL_SENTINEL="media-runtime-disposable-local-v1"' in script
    assert '"NPCINK_CLOUD_ENVIRONMENT=test"' in script
    assert '"NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_ENABLED=false"' in script
    assert '"NPCINK_CLOUD_DEPLOY_SMOKE_KEEP=0"' in script
    assert '"NPCINK_CLOUD_DEPLOY_SMOKE_SKIP_BUILD=0"' in script
    assert '"NPCINK_CLOUD_SKIP_FRONTEND_IMAGE=0"' in script
    assert "--allow-partial is forbidden in full mode" in script
    assert "full mode requires --confirm-disposable-local-docker" in script
    assert 'exit 3' in script
    assert "urlsplit" not in script
    assert package_scripts["check:media:staging"] == (
        "bash scripts/media-runtime-staging-rehearsal.sh --target local-staging "
        "--confirm-disposable-local-docker"
    )
    assert package_scripts["diagnose:media:staging:quick"] == (
        "bash scripts/media-runtime-staging-rehearsal.sh --target local-staging "
        "--quick --allow-partial"
    )

    for variable_name in CONTROL_ENV_KEYS:
        assert f'"{variable_name}"' in script
    for delegated_gate in (
        "pnpm run check:release-policy",
        "pnpm run check:anti-drift",
        "pnpm run check:e2e:deploy-bundle:smoke",
        "pnpm run check:artifact-orphan-isolation-proof",
    ):
        assert delegated_gate in script

    assert "set -x" not in script
    assert not re.search(r"(?m)^[ \t]*(?:command[ \t]+)?(?:ssh|scp)[ \t]", script)
    syntax = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr


def test_full_mode_requires_confirmation_and_forbids_partial_override() -> None:
    missing_confirmation = _run()
    assert missing_confirmation.returncode == 2
    assert "full mode requires --confirm-disposable-local-docker" in (
        missing_confirmation.stderr
    )

    partial_full = _run(
        "--allow-partial",
        "--confirm-disposable-local-docker",
    )
    assert partial_full.returncode == 2
    assert "--allow-partial is forbidden in full mode" in partial_full.stderr


def test_quick_partial_requires_explicit_allowance() -> None:
    rejected_partial = _run("--quick", "--skip-config")
    assert rejected_partial.returncode == 3
    assert (
        "MEDIA_RUNTIME_STAGING_REHEARSAL PARTIAL "
        "target=local-staging mode=quick passed=0 skipped=4"
    ) in rejected_partial.stdout

    allowed_partial = _run("--quick", "--skip-config", "--allow-partial")
    assert allowed_partial.returncode == 0, allowed_partial.stderr
    assert "MEDIA_RUNTIME_STAGING_REHEARSAL PARTIAL" in allowed_partial.stdout


def test_quick_sentinel_clears_sensitive_environment(tmp_path: Path) -> None:
    fake_bin, pnpm_log, docker_log = _write_fake_toolchain(tmp_path)
    sensitive_overrides = {name: f"s3cr3t-{index}" for index, name in enumerate(SENSITIVE_ENV_KEYS)}
    sensitive_overrides["PATH"] = f"{fake_bin}:{os.environ['PATH']}"

    completed = _run(
        "--quick",
        "--allow-partial",
        env_overrides=sensitive_overrides,
    )

    assert completed.returncode == 0, completed.stderr
    assert pnpm_log.read_text().splitlines() == [
        "run check:release-policy",
        "run check:anti-drift",
    ]
    assert not docker_log.exists()
    assert "MEDIA_RUNTIME_STAGING_REHEARSAL PARTIAL" in completed.stdout
    combined_output = completed.stdout + completed.stderr
    assert not any(value in combined_output for value in sensitive_overrides.values())


def test_fake_full_runs_all_four_existing_stages_in_order(tmp_path: Path) -> None:
    fake_bin, pnpm_log, docker_log = _write_fake_toolchain(tmp_path)
    completed = _run(
        "--confirm-disposable-local-docker",
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert completed.returncode == 0, completed.stderr
    assert pnpm_log.read_text().splitlines() == [
        "run check:release-policy",
        "run check:anti-drift",
        "run check:e2e:deploy-bundle:smoke",
        "run check:artifact-orphan-isolation-proof",
    ]
    assert docker_log.read_text().splitlines() == [
        "context show",
        "context inspect desktop-linux --format {{(index .Endpoints \"docker\").Host}}",
        "info",
    ]
    assert (
        "MEDIA_RUNTIME_STAGING_REHEARSAL PASS "
        "target=local-staging mode=full passed=4 skipped=0"
    ) in completed.stdout


def test_fake_full_preserves_late_stage_failure_exit_code(tmp_path: Path) -> None:
    fake_bin, pnpm_log, _ = _write_fake_toolchain(
        tmp_path,
        fail_gate="check:artifact-orphan-isolation-proof",
    )
    completed = _run(
        "--confirm-disposable-local-docker",
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert completed.returncode == 47
    assert pnpm_log.read_text().splitlines()[-1] == (
        "run check:artifact-orphan-isolation-proof"
    )
    assert "[rehearsal:pass] runtime/exact-deploy-bundle" in completed.stdout
    assert "[rehearsal:fail] media/isolated-artifact-recovery exit=47" in completed.stderr
    assert "MEDIA_RUNTIME_STAGING_REHEARSAL" not in completed.stdout


def test_dangerous_control_environment_is_rejected_without_value_echo() -> None:
    cases = (
        "NPCINK_CLOUD_COMPOSE_PROJECT_NAME",
        "COMPOSE_PROJECT_NAME",
        "NPCINK_CLOUD_COMPOSE_FILE",
        "COMPOSE_FILE",
        "NPCINK_CLOUD_ENV_FILE",
        "ENV_FILE",
        "COMPOSE_ENV_FILES",
        "DOCKER_CONTEXT",
        "DOCKER_HOST",
        "DOCKER_CONFIG",
        "NPCINK_CLOUD_DEPLOY_SMOKE_BASE_URL",
        "NPCINK_CLOUD_BASE_URL",
        "CLOUD_API_BASE_URL",
        "NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_ENABLED",
        "NPCINK_CLOUD_SKIP_FRONTEND_IMAGE",
    )

    for index, variable_name in enumerate(cases):
        secret_value = f"s3cr3t-control-value-{index}"
        completed = _run(
            "--quick",
            "--allow-partial",
            env_overrides={variable_name: secret_value},
        )
        combined_output = completed.stdout + completed.stderr
        assert completed.returncode == 2
        assert variable_name in completed.stderr
        assert secret_value not in combined_output
        assert "MEDIA_RUNTIME_STAGING_REHEARSAL" not in combined_output


def test_nonlocal_active_docker_context_is_rejected_without_endpoint_echo(
    tmp_path: Path,
) -> None:
    remote_endpoint = "tcp://s3cr3t-production-docker.example:2376"
    fake_bin, pnpm_log, _ = _write_fake_toolchain(
        tmp_path,
        docker_endpoint=remote_endpoint,
    )
    completed = _run(
        "--confirm-disposable-local-docker",
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert completed.returncode == 2
    assert "active Docker context is not local" in completed.stderr
    assert remote_endpoint not in completed.stdout + completed.stderr
    assert not pnpm_log.exists()
