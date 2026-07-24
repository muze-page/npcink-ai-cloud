from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "m4-preview.sh"
REDACTOR = ROOT / "scripts" / "redact-m4-preview-logs.py"
PACKAGE_PROXY = ROOT / "scripts" / "m4-package-proxy.py"
OVERLAY = ROOT / "docker-compose.m4-preview.yml"
RUNBOOK = ROOT / "docs" / "m4-preview-development-v1.md"
AI_STANDARD = ROOT / "docs" / "m4-preview-ai-development-standard-v1.md"
OLLAMA_LAUNCH_AGENT = ROOT / "deploy" / "top.mqzj.npcink-ollama-preview.plist"


def test_m4_preview_commands_are_explicit() -> None:
    scripts = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]

    expected = {
        "m4:preview:prepare": "bash scripts/m4-preview.sh prepare",
        "m4:preview:deploy": "bash scripts/m4-preview.sh deploy",
        "m4:preview:sync": "bash scripts/m4-preview.sh sync",
        "m4:preview:promote": "bash scripts/m4-preview.sh promote",
        "m4:preview:tunnel": "bash scripts/m4-preview.sh tunnel",
        "m4:preview:status": "bash scripts/m4-preview.sh status",
        "m4:preview:logs": "bash scripts/m4-preview.sh logs",
        "m4:preview:test": "bash scripts/m4-preview.sh test",
        "m4:preview:recover": "bash scripts/m4-preview.sh recover",
        "m4:preview:ollama:install": "bash scripts/m4-preview.sh ollama-install",
        "m4:preview:ollama:configure": "bash scripts/m4-preview.sh ollama-configure",
        "m4:preview:ollama:status": "bash scripts/m4-preview.sh ollama-status",
        "m4:preview:ollama:restart": "bash scripts/m4-preview.sh ollama-restart",
        "m4:preview:restart": "bash scripts/m4-preview.sh restart",
        "m4:preview:stop": "bash scripts/m4-preview.sh stop",
    }
    assert {name: scripts.get(name) for name in expected} == expected


def test_m4_preview_shell_contract_is_syntax_valid_and_fail_closed() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], cwd=ROOT, check=True)
    source = SCRIPT.read_text(encoding="utf-8")

    assert "npcink-ai-cloud-m4-dev" in source
    assert "npcink-ai-cloud-m4-preview)" in source
    assert "legacy project name is forbidden" in source
    assert "operation.lock" in source
    assert 'if ! mkdir "${lock_dir}"' in source
    assert "lock_acquired=0" in source
    assert 'if [ "${lock_acquired}" = "1" ]; then' in source
    assert "built_image_marker" in source
    assert "deployed_image_marker" in source
    assert "deployed_config_marker" in source
    assert "prepared image inputs are not deployed" in source
    assert 'test ! -L "${remote_dir}"' in source
    assert 'resolved_remote_dir="$(cd "${remote_dir}" && pwd -P)"' in source
    assert 'work_dir="${staging}"' in source
    assert 'work_dir="${remote_dir}"' in source
    assert "com.docker.compose.service" in source
    assert "source_bundle_sha256" in source
    assert "source_dirty_paths" in source
    assert "acceptance_state" in source
    assert "promotion_pr" in source
    assert "deployed_at_utc" in source
    assert "git ls-files -z --cached --others --exclude-standard" in source
    assert "--exclude '.env'" in source
    assert "--exclude '.env.local'" in source
    assert "--exclude 'frontend/.next'" in source
    assert "--exclude 'node_modules'" in source
    assert "docker system prune" not in source
    assert "docker volume prune" not in source
    assert "docker image save" not in source
    assert "docker image load" not in source
    assert "docker compose" in source
    assert "exec --interactive=false -T" in source
    assert "building runtime image on M4" in source
    assert "ghcr.nju.edu.cn/astral-sh/uv:" in source
    assert "m.daocloud.io/docker.io/library/python:" in source
    assert "m.daocloud.io/docker.io/library/node:" in source
    assert "crane pull" in source
    assert "remote_config_digest" in source
    assert "verified M4-local base aliases" in source
    assert "scripts/m4-package-proxy.py" in source
    assert '--secret "id=pip_index_url' in source
    assert "NPCINK_CLOUD_M4_NPM_REGISTRY" in source
    assert 'frontend_volume="${project_name}_cloud-frontend-node-modules-dev"' in source
    assert "com.docker.compose.project" in source
    assert "prepare complete: images and Compose config are ready" in source
    assert "equivalent_gate=pnpm run check:fast" in source
    assert 'label=com.docker.compose.oneoff=False' in source
    assert "recovery requires existing container" in source
    assert '"${compose[@]}" start postgres redis' in source
    assert '"${compose[@]}" start api frontend proxy worker callback-worker ops-worker' in source
    assert "recovery complete" in source
    assert 'key.startswith("NPCINK_CLOUD_")' in source
    assert "pytest.main(sys.argv[1:])" in source
    assert "tests/contract" in source
    assert "tests/domain" in source
    assert "NPCINK_CLOUD_M4_TUNNEL_LOCAL_PORT" in source
    assert 'forward="127.0.0.1:${local_port}:127.0.0.1:${M4_PORT}"' in source
    assert "ExitOnForwardFailure=yes" in source
    assert "ServerAliveCountMax=3" in source
    assert "top.mqzj.npcink-ollama-preview" in source
    assert "m4:preview:ollama:install" in source
    assert "scripts/configure_m4_ollama_preview.py" in source
    assert "env PYTHONPATH=/app python scripts/configure_m4_ollama_preview.py" in source
    assert "managed Ollama is not installed; skipping preview recovery" in source
    assert "127.0.0.1:${M4_OLLAMA_PORT}" in source
    assert 'source_branch}" = "master"' in source
    assert "promotion requires a clean master worktree" in source
    assert "refs/remotes/origin/master" in source
    assert "PR #${pr_number} is not merged" in source
    assert "PR #${pr_number} targets ${pr_base}, not master" in source
    assert "m4:preview:promote -- --pr ${promotion_pr} --deploy" in source

    prepare_block = source.rsplit('if [ "${mode}" = "prepare" ]; then', 1)[1].split(
        'elif [ "${mode}" = "deploy" ]; then',
        1,
    )[0]
    assert "deployed_image_marker" not in prepare_block
    assert "deployed_config_marker" not in prepare_block
    assert source.index("wait_for_http") < source.index('> "${deployed_image_marker}"')


def test_m4_tunnel_dry_run_is_local_only_and_non_mutating() -> None:
    completed = subprocess.run(
        ["bash", str(SCRIPT), "tunnel", "--dry-run"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "local_url=http://127.0.0.1:18010" in completed.stdout
    assert "127.0.0.1:18010:127.0.0.1:8010" in completed.stdout
    assert "ExitOnForwardFailure=yes" in completed.stdout
    assert "ServerAliveInterval=15" in completed.stdout
    assert "ServerAliveCountMax=3" in completed.stdout
    assert "docker" not in completed.stdout
    assert "rsync" not in completed.stdout


def test_m4_ollama_launch_agent_is_loopback_only_and_dry_run_is_non_mutating() -> None:
    source = OLLAMA_LAUNCH_AGENT.read_text(encoding="utf-8")

    assert "<string>top.mqzj.npcink-ollama-preview</string>" in source
    assert "<string>/usr/local/bin/ollama</string>" in source
    assert "<string>serve</string>" in source
    assert "<string>127.0.0.1:11434</string>" in source
    assert "0.0.0.0" not in source
    assert "<key>RunAtLoad</key>" in source
    assert "<key>KeepAlive</key>" in source

    completed = subprocess.run(
        ["bash", str(SCRIPT), "ollama-install", "--dry-run"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "dry-run: install top.mqzj.npcink-ollama-preview" in completed.stdout
    assert "127.0.0.1:11434" in completed.stdout
    assert "docker" not in completed.stdout
    assert "rsync" not in completed.stdout


def test_m4_overlay_is_loopback_only_and_starts_the_complete_runtime() -> None:
    overlay = OVERLAY.read_text(encoding="utf-8")
    base = (ROOT / "docker-compose.dev.yml").read_text(encoding="utf-8")

    for binding in (
        "127.0.0.1:${NPCINK_CLOUD_M4_PORT:-8010}:8080",
        "127.0.0.1:${NPCINK_CLOUD_M4_POSTGRES_PORT:-15433}:5432",
        "127.0.0.1:${NPCINK_CLOUD_M4_REDIS_PORT:-16380}:6379",
    ):
        assert binding in overlay

    assert "0.0.0.0:" not in overlay
    assert "npcink-ai-cloud-runtime:m4-dev" in overlay
    assert "npcink-ai-cloud-frontend:m4-dev" in overlay
    assert "NEXT_PUBLIC_ENV: development" in overlay
    assert (
        "NEXT_PUBLIC_MINI_DEV_HOST_ALLOWLIST: "
        "${NPCINK_CLOUD_M4_MINI_DEV_HOST_ALLOWLIST:-cloud.mqzjmax.top,127.0.0.1,localhost}"
        in overlay
    )
    assert "NPCINK_CLOUD_SETUP_STATE_OVERRIDE: complete" in overlay
    assert (
        overlay.count(
            "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID: "
            "${NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID:-m4-preview-service-v1}"
        )
        == 4
    )
    assert '"node"' in overlay
    assert '"node_modules/next/dist/bin/next"' in overlay
    for service in (
        "postgres",
        "redis",
        "api",
        "frontend",
        "proxy",
        "worker",
        "callback-worker",
        "ops-worker",
    ):
        assert f"  {service}:" in base
    assert base.count("restart: unless-stopped") == 8


def test_m4_log_redactor_masks_env_canaries_and_common_credentials(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.local"
    env_canary = "env-canary-91b7d19e"
    database_canary = "db-canary-b7fe4c9a"
    env_file.write_text(
        f"NPCINK_CLOUD_API_KEY={env_canary}\nNPCINK_CLOUD_DATABASE_URL={database_canary}\n",
        encoding="utf-8",
    )
    raw = (
        f"api_key={env_canary}\n"
        f"database={database_canary}\n"
        "Authorization: Bearer auth-canary-ec78\n"
        "password=plain-canary-09ac\n"
        "required=false\n"
        "postgresql://user-canary:pass-canary@postgres:5432/db?token=query-canary\n"
    )

    completed = subprocess.run(
        [sys.executable, str(REDACTOR), "--env-file", str(env_file)],
        cwd=ROOT,
        input=raw,
        text=True,
        capture_output=True,
        check=True,
    )

    for secret in (
        env_canary,
        database_canary,
        "auth-canary-ec78",
        "plain-canary-09ac",
        "user-canary",
        "pass-canary",
        "query-canary",
    ):
        assert secret not in completed.stdout
    assert "[redacted]" in completed.stdout
    assert "required=false" in completed.stdout


def _load_package_proxy():
    spec = importlib.util.spec_from_file_location("m4_package_proxy", PACKAGE_PROXY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_m4_package_proxy_is_fixed_destination_and_rewrites_registry_links() -> None:
    proxy = _load_package_proxy()
    pypi = proxy.resolve_route("/pypi/simple/alembic/?x=1")
    npm = proxy.resolve_route("/npm/pnpm")

    assert pypi is not None
    assert npm is not None
    assert pypi.upstream_url == "https://pypi.org/simple/alembic/?x=1"
    assert npm.upstream_url == "https://registry.npmjs.org/pnpm"
    assert proxy.resolve_route("/https://example.com/private") is None

    public_base = "http://host.docker.internal:18081"
    pypi_body = proxy.rewrite_payload(
        "pypi",
        b'<a href="https://files.pythonhosted.org/packages/a.whl">wheel</a>',
        public_base,
    )
    npm_body = proxy.rewrite_payload(
        "npm",
        b'{"tarball":"https://registry.npmjs.org/pnpm/-/pnpm.tgz"}',
        public_base,
    )
    assert b"http://host.docker.internal:18081/pypi-files/packages/a.whl" in pypi_body
    assert b"http://host.docker.internal:18081/npm/pnpm/-/pnpm.tgz" in npm_body


def test_m4_package_proxy_binds_loopback_and_publishes_readiness(tmp_path: Path) -> None:
    ready_file = tmp_path / "proxy.port"
    process = subprocess.Popen(
        [
            sys.executable,
            str(PACKAGE_PROXY),
            "--bind",
            "127.0.0.1",
            "--port",
            "0",
            "--ready-file",
            str(ready_file),
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _attempt in range(100):
            if ready_file.exists() and ready_file.read_text(encoding="utf-8").strip():
                break
            assert process.poll() is None
            time.sleep(0.02)
        port = int(ready_file.read_text(encoding="utf-8").strip())
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
            assert response.status == 200
            assert response.read() == b"ok\n"
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_m4_package_proxy_buffers_and_retries_upstream_downloads() -> None:
    proxy_source = PACKAGE_PROXY.read_text(encoding="utf-8")
    preview_source = SCRIPT.read_text(encoding="utf-8")
    assert "tempfile.SpooledTemporaryFile" in proxy_source
    assert "for attempt in range(1, 4)" in proxy_source
    assert 'package_proxy_port="18081"' in preview_source
    assert '--port "${package_proxy_port}"' in preview_source


def test_m4_runbook_preserves_source_cloudflare_and_recovery_boundaries() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")

    assert "source and Git truth" in runbook
    assert "No day-to-day Docker installation" in runbook
    assert "does not authorize a production deploy" in runbook
    assert "Cloudflare DNS, Access, or Tunnel change" in runbook
    assert "127.0.0.1:8010" in runbook
    assert "127.0.0.1:15433" in runbook
    assert "127.0.0.1:16380" in runbook
    assert "docker system prune" in runbook
    assert "m4:preview:recover" in runbook
    assert "m4:preview:tunnel" in runbook
    assert "five working days" in runbook
    assert "Docker Desktop 4.83.0" in runbook
    assert "m4:preview:stop" in runbook
    assert "last known-good Git revision" in runbook
    assert "portal-demo@example.com" in runbook
    assert "https://cloud.mqzjmax.top/portal/dev-entry" in runbook
    assert "shared development identity" in runbook
    assert "Candidate and Accepted States" in runbook
    assert "pnpm run m4:preview:promote -- --pr" in runbook
    assert "acceptance_state=accepted" in runbook
    assert "receives no M4 SSH credential" in runbook


def test_m4_ai_development_standard_is_actionable_and_linked() -> None:
    standard = AI_STANDARD.read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = RUNBOOK.read_text(encoding="utf-8")
    standard_path = "docs/m4-preview-ai-development-standard-v1.md"

    assert standard_path in agents
    assert standard_path in readme
    assert "m4-preview-ai-development-standard-v1.md" in runbook

    for required_text in (
        "Local-only",
        "Cloud source",
        "Build/runtime",
        "M4 MUST NOT become source or Git truth",
        "WordPress remains the local control plane",
        "pnpm run m4:preview:sync",
        "pnpm run m4:preview:deploy",
        "pnpm run m4:preview:promote -- --pr",
        "pnpm run m4:preview:test",
        "http://127.0.0.1:18010",
        "https://cloud.mqzjmax.top",
        "acceptance_state=accepted",
        "source_branch=master",
        "source_dirty=false",
        "under two minutes",
        "under ten minutes per",
        "report candidate validation as accepted completion",
    ):
        assert required_text in standard
