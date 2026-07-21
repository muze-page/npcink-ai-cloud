from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, text: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def _install_deploy_lock_owner(
    release_root: Path, environment: dict[str, str]
) -> str:
    owner = "f" * 64
    deploy_lock = release_root.parent / ".deploy-lock"
    deploy_lock.mkdir(mode=0o700)
    owner_file = deploy_lock / "one-off-owner"
    owner_file.write_text(owner + "\n", encoding="utf-8")
    owner_file.chmod(0o600)
    environment["NPCINK_CLOUD_DEPLOY_LOCK_OWNER"] = owner
    return owner


def test_env_loader_assigns_shell_metacharacters_literally(tmp_path: Path) -> None:
    env_file = tmp_path / "literal.env"
    execution_marker = tmp_path / "must-not-execute"
    command_substitution = '$(touch "${ENV_EXEC_MARKER}");semi & literal'
    backtick_substitution = '`touch "${ENV_EXEC_MARKER}"`'
    quoted_literal = "space $() ; & value"
    env_file.write_text(
        "\n".join(
            (
                f"NPCINK_CLOUD_PROMPT_TEXT={command_substitution}",
                f"NPCINK_CLOUD_SITE_URL={backtick_substitution}",
                f"NPCINK_CLOUD_WP_CRON_USER_AGENT='{quoted_literal}'",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "ENV_EXEC_MARKER": str(execution_marker),
            "NPCINK_CLOUD_ENV_FILE": str(env_file),
        }
    )
    for key in (
        "NPCINK_CLOUD_PROMPT_TEXT",
        "NPCINK_CLOUD_SITE_URL",
        "NPCINK_CLOUD_WP_CRON_USER_AGENT",
    ):
        environment.pop(key, None)
    completed = subprocess.run(
        [
            "bash",
            "-c",
            (
                f'. "{ROOT / "deploy/common.sh"}"; '
                f'npcink_ai_cloud_load_env_file "{tmp_path}"; '
                "printf '%s\\n' \"${NPCINK_CLOUD_PROMPT_TEXT}\" "
                '"${NPCINK_CLOUD_SITE_URL}" "${NPCINK_CLOUD_WP_CRON_USER_AGENT}"'
            ),
        ],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.splitlines() == [
        command_substitution,
        backtick_substitution,
        quoted_literal,
    ]
    assert not execution_marker.exists()


def test_env_loader_keeps_unreviewed_runtime_keys_out_of_root_shell(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "container-only.env"
    env_file.write_text(
        "NPCINK_CLOUD_FUTURE_HOST_CONTROL=container-runtime-value\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["NPCINK_CLOUD_ENV_FILE"] = str(env_file)
    environment.pop("NPCINK_CLOUD_FUTURE_HOST_CONTROL", None)

    completed = subprocess.run(
        [
            "bash",
            "-c",
            (
                f'. "{ROOT / "deploy/common.sh"}"; '
                f'npcink_ai_cloud_load_env_file "{tmp_path}"; '
                'if [ -n "${NPCINK_CLOUD_FUTURE_HOST_CONTROL+x}" ]; then exit 91; fi'
            ),
        ],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_env_loader_keeps_container_env_out_of_shell_but_passes_original_to_compose(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "runtime.env"
    original = (
        "NPCINK_CLOUD_BASE_URL=https://cloud.example.test\n"
        "NPCINK_CLOUD_DATABASE_URL=postgresql+psycopg://runtime-secret\n"
        "NPCINK_CLOUD_OPENAI_API_KEY=provider-secret\n"
        "POSTGRES_PASSWORD=postgres-secret\n"
        "NPCINK_CLOUD_FUTURE_HOST_CONTROL=container-only\n"
    )
    env_file.write_text(original, encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write(
        fake_bin / "docker",
        """#!/usr/bin/env bash
set -euo pipefail
for key in \
    NPCINK_CLOUD_DATABASE_URL \
    NPCINK_CLOUD_OPENAI_API_KEY \
    POSTGRES_PASSWORD \
    NPCINK_CLOUD_FUTURE_HOST_CONTROL; do
    [ -z "${!key+x}" ] || exit 85
done
printf 'backend:%s\n' "${NPCINK_CLOUD_BACKEND_ENV_FILE:-unset}"
printf 'argv:'
printf '%s|' "$@"
printf '\n'
""",
        executable=True,
    )
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
    environment["NPCINK_CLOUD_ENV_FILE"] = str(env_file)
    environment.pop("NPCINK_CLOUD_BACKEND_ENV_FILE", None)
    for key in (
        "NPCINK_CLOUD_BASE_URL",
        "NPCINK_CLOUD_DATABASE_URL",
        "NPCINK_CLOUD_OPENAI_API_KEY",
        "POSTGRES_PASSWORD",
        "NPCINK_CLOUD_FUTURE_HOST_CONTROL",
    ):
        environment.pop(key, None)

    completed = subprocess.run(
        [
            "bash",
            "-c",
            (
                f'. "{ROOT / "deploy/common.sh"}"; '
                f'npcink_ai_cloud_load_env_file "{tmp_path}"; '
                '[ "${NPCINK_CLOUD_BASE_URL}" = "https://cloud.example.test" ]; '
                f'npcink_ai_cloud_compose "{tmp_path}" config'
            ),
        ],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert f"backend:{env_file}" in completed.stdout
    assert f"--env-file|{env_file}|" in completed.stdout
    assert env_file.read_text(encoding="utf-8") == original


def test_shell_import_allowlist_has_no_namespace_wildcard() -> None:
    source = (ROOT / "deploy/common.sh").read_text(encoding="utf-8")
    function_body = source.split(
        "npcink_ai_cloud_env_key_is_shell_importable() {", 1
    )[1].split("\n}\n\nnpcink_ai_cloud_load_env_file()", 1)[0]

    assert "NPCINK_CLOUD_*|" not in function_body
    assert "NPCINK_CLOUD_*_RELEASE_IMAGE" not in function_body


@pytest.mark.parametrize(
    "rows",
    (
        "",
        "npcink-ai-cloud-api:prod\t-\t-\n",
        "npcink-ai-cloud-api:prod\trollback\tsha256:short\n",
        (
            "npcink-ai-cloud-api:prod\trollback-1\t"
            f"sha256:{'a' * 64}\n"
            "npcink-ai-cloud-api:prod\trollback-2\t"
            f"sha256:{'a' * 64}\n"
        ),
    ),
)
def test_rollback_image_lookup_rejects_missing_or_ambiguous_map_rows(
    tmp_path: Path,
    rows: str,
) -> None:
    rollback_map = tmp_path / "rollback.tsv"
    rollback_map.write_text(rows, encoding="utf-8")

    completed = subprocess.run(
        [
            "bash",
            "-c",
            (
                f'. "{ROOT / "deploy/common.sh"}"; '
                "npcink_ai_cloud_expected_rollback_image_id "
                f'"{rollback_map}" "npcink-ai-cloud-api:prod"'
            ),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0


@pytest.mark.parametrize(
    "reserved_key",
    (
        "BASH_ENV",
        "LD_PRELOAD",
        "NPCINK_CLOUD_RELEASE_TOOL_PYTHON",
        "NPCINK_CLOUD_API_RELEASE_IMAGE",
        "NPCINK_CLOUD_DEPLOY_SSH_HOST",
        "NPCINK_CLOUD_SECRET",
    ),
)
def test_env_loader_rejects_host_and_release_control_keys(
    tmp_path: Path, reserved_key: str
) -> None:
    env_file = tmp_path / "reserved.env"
    env_file.write_text(f"{reserved_key}=attacker-controlled\n", encoding="utf-8")
    environment = os.environ.copy()
    environment["NPCINK_CLOUD_ENV_FILE"] = str(env_file)
    if reserved_key != "NPCINK_CLOUD_ENV_FILE":
        environment.pop(reserved_key, None)

    completed = subprocess.run(
        [
            "bash",
            "-c",
            (
                f'. "{ROOT / "deploy/common.sh"}"; '
                f'npcink_ai_cloud_load_env_file "{tmp_path}"'
            ),
        ],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert f"not an allowed runtime setting: {reserved_key}" in completed.stderr


def _deploy_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    fixture = tmp_path / "fixture"
    fake_bin = tmp_path / "bin"
    log_dir = tmp_path / "logs"
    bundle = fixture / "dist" / "deploy-bundle.tgz"

    (fixture / "deploy").mkdir(parents=True)
    (fixture / "scripts").mkdir()
    fake_bin.mkdir()
    log_dir.mkdir()
    shutil.copy2(
        ROOT / "deploy/deploy-to-ssh-host.sh",
        fixture / "deploy/deploy-to-ssh-host.sh",
    )
    shutil.copy2(ROOT / "deploy/common.sh", fixture / "deploy/common.sh")
    _write(
        fixture / "deploy/verify-release-bundle.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n",
        executable=True,
    )
    _write(
        fixture / "scripts/verify-release-bundle-manifest.py",
        """from __future__ import annotations
import sys

if sys.argv[1:2] == ["archive-platform"]:
    print("linux/amd64")
    raise SystemExit(0)
raise SystemExit(64)
""",
    )
    bundle.parent.mkdir()
    bundle.write_bytes(b"fixture bundle\n")
    bundle.with_suffix(bundle.suffix + ".sha256").write_text(
        f"{'a' * 64}  deploy-bundle.tgz\n",
        encoding="utf-8",
    )

    ssh = r"""#!/usr/bin/env bash
set -euo pipefail
{
    printf 'ssh'
    for arg in "$@"; do
        printf '\t%s' "${arg}"
    done
    printf '\n'
} >>"${SSH_LOG}"

command_line="$*"
if [[ "${command_line}" == *"version_info"* ]]; then
    if [ "${REMOTE_PYTHON_OK:-1}" = "1" ]; then
        printf '3.11.9\n'
        exit 0
    fi
    exit 91
fi
if [[ "${command_line}" == *"id -u"* ]]; then
    printf '%s\n' "${REMOTE_UID:-0}"
    exit 0
fi
if [[ "${command_line}" == *"uname -m"* ]]; then
    printf 'x86_64\n'
    exit 0
fi
if [[ "${command_line}" == *"bash -s --"* ]]; then
    cat >/dev/null
    printf 'staged_release=/srv/npcink-cloud/release-fixture\n'
fi
exit 0
"""
    scp = r"""#!/usr/bin/env bash
set -euo pipefail
{
    printf 'scp'
    for arg in "$@"; do
        printf '\t%s' "${arg}"
    done
    printf '\n'
} >>"${SCP_LOG}"
if [ -n "${FAIL_SCP_SUBSTRING:-}" ] && [[ "$*" == *"${FAIL_SCP_SUBSTRING}"* ]]; then
    exit 73
fi
"""
    _write(fake_bin / "ssh", ssh, executable=True)
    _write(fake_bin / "scp", scp, executable=True)
    return fixture, fake_bin, log_dir, bundle


def _run_stage_only(
    tmp_path: Path,
    *,
    remote_python_ok: bool = True,
    fail_scp_substring: str = "",
    host_python: str = "",
    remote_uid: str = "0",
    extra_args: tuple[str, ...] = (),
) -> tuple[subprocess.CompletedProcess[str], str, str]:
    fixture, fake_bin, log_dir, bundle = _deploy_fixture(tmp_path)
    ssh_log = log_dir / "ssh.log"
    scp_log = log_dir / "scp.log"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "SSH_LOG": str(ssh_log),
            "SCP_LOG": str(scp_log),
            "REMOTE_PYTHON_OK": "1" if remote_python_ok else "0",
            "REMOTE_UID": remote_uid,
            "FAIL_SCP_SUBSTRING": fail_scp_substring,
            "NPCINK_CLOUD_SECRET": "ambient-site-secret-must-not-cross-ssh",
            "NPCINK_CLOUD_PROMPT_TEXT": "ambient-prompt-must-not-cross-ssh",
            "NPCINK_CLOUD_MEMBER_EMAIL": "ambient-member-must-not-cross-ssh@example.com",
        }
    )
    command = [
        "bash",
        str(fixture / "deploy/deploy-to-ssh-host.sh"),
        "--stage-only",
        "--skip-bundle-build",
        "--ssh-host",
        "fixture.invalid",
        "--remote-dir",
        "/srv/npcink-cloud",
        "--bundle-path",
        str(bundle),
    ]
    if host_python:
        command.extend(("--host-python", host_python))
    command.extend(extra_args)
    completed = subprocess.run(
        command,
        cwd=fixture,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return (
        completed,
        ssh_log.read_text(encoding="utf-8") if ssh_log.exists() else "",
        scp_log.read_text(encoding="utf-8") if scp_log.exists() else "",
    )


def test_stage_only_preflights_default_host_python_and_keeps_remote_argv_minimal(
    tmp_path: Path,
) -> None:
    completed, ssh_log, scp_log = _run_stage_only(tmp_path)

    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
    ssh_lines = ssh_log.splitlines()
    python_probe_index = next(
        index for index, line in enumerate(ssh_lines) if "version_info" in line
    )
    prepare_index = next(index for index, line in enumerate(ssh_lines) if "mkdir -p" in line)
    assert python_probe_index < prepare_index
    assert "/usr/bin/python3.11" in ssh_lines[python_probe_index]
    final_entry = next(line for line in ssh_lines if "bash\t-s\t--\tstage-only" in line)
    assert "/srv/npcink-cloud" in final_entry
    assert "/usr/bin/python3.11" in final_entry
    for forbidden in (
        "ambient-site-secret-must-not-cross-ssh",
        "ambient-prompt-must-not-cross-ssh",
        "ambient-member-must-not-cross-ssh@example.com",
        "site_smoke",
        "key_default",
        "catalog:read",
        "text.balanced",
    ):
        assert forbidden not in final_entry
        assert forbidden not in ssh_log
    assert "deploy-bundle.tgz" in scp_log
    assert "StrictHostKeyChecking=yes" in ssh_log
    assert "StrictHostKeyChecking=accept-new" not in ssh_log
    assert "StrictHostKeyChecking=yes" in scp_log


def test_stage_only_uses_configured_host_python_for_probe_and_remote_entry(
    tmp_path: Path,
) -> None:
    configured_python = "/opt/npcink-tools/python3.12"
    completed, ssh_log, _scp_log = _run_stage_only(
        tmp_path,
        host_python=configured_python,
    )

    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
    probe = next(line for line in ssh_log.splitlines() if "version_info" in line)
    final_entry = next(line for line in ssh_log.splitlines() if "bash\t-s\t--\tstage-only" in line)
    assert configured_python in probe
    assert configured_python in final_entry


def test_remote_host_python_failure_precedes_remote_directory_and_upload(
    tmp_path: Path,
) -> None:
    completed, ssh_log, scp_log = _run_stage_only(
        tmp_path,
        remote_python_ok=False,
    )

    assert completed.returncode == 1
    assert "version 3.11 or newer" in completed.stderr
    assert "version_info" in ssh_log
    assert "mkdir -p" not in ssh_log
    assert scp_log == ""


def test_non_root_remote_account_fails_before_host_python_directory_and_upload(
    tmp_path: Path,
) -> None:
    completed, ssh_log, scp_log = _run_stage_only(tmp_path, remote_uid="1001")

    assert completed.returncode == 1
    assert "must have UID 0" in completed.stderr
    assert "id -u" in ssh_log
    assert "version_info" not in ssh_log
    assert "mkdir -p" not in ssh_log
    assert scp_log == ""


def test_stage_only_rejects_explicit_runtime_options_before_network(
    tmp_path: Path,
) -> None:
    completed, ssh_log, scp_log = _run_stage_only(
        tmp_path,
        extra_args=("--secret", "must-not-be-printed"),
    )

    assert completed.returncode == 1
    assert "accepts only bundle/platform" in completed.stderr
    assert "--secret" in completed.stderr
    assert "must-not-be-printed" not in completed.stderr
    assert ssh_log == ""
    assert scp_log == ""


def test_full_deploy_requires_explicit_runtime_secret_before_network(tmp_path: Path) -> None:
    fixture, fake_bin, log_dir, bundle = _deploy_fixture(tmp_path)
    ssh_log = log_dir / "ssh.log"
    scp_log = log_dir / "scp.log"
    environment = os.environ.copy()
    environment.pop("NPCINK_CLOUD_SECRET", None)
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "SSH_LOG": str(ssh_log),
            "SCP_LOG": str(scp_log),
        }
    )

    completed = subprocess.run(
        [
            "bash",
            str(fixture / "deploy/deploy-to-ssh-host.sh"),
            "--skip-bundle-build",
            "--ssh-host",
            "fixture.invalid",
            "--remote-dir",
            "/srv/npcink-cloud",
            "--bundle-path",
            str(bundle),
        ],
        cwd=fixture,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "NPCINK_CLOUD_SECRET is required" in completed.stderr
    assert not ssh_log.exists()
    assert not scp_log.exists()


def test_upload_failure_attempts_remote_incoming_cleanup(tmp_path: Path) -> None:
    completed, ssh_log, scp_log = _run_stage_only(
        tmp_path,
        fail_scp_substring="deploy-bundle.tgz",
    )

    assert completed.returncode == 73
    assert "deploy-bundle.tgz" in scp_log
    ssh_lines = ssh_log.splitlines()
    prepare_index = next(index for index, line in enumerate(ssh_lines) if "mkdir -p" in line)
    cleanup_index = next(
        index
        for index, line in enumerate(ssh_lines)
        if "rm -rf" in line and "/srv/npcink-cloud/.incoming/" in line
    )
    assert prepare_index < cleanup_index


def test_local_release_tools_keep_python39_floor_while_remote_host_requires_311(
    tmp_path: Path,
) -> None:
    common = ROOT / "deploy/common.sh"
    default_shell = (
        f". {common}; "
        "unset NPCINK_CLOUD_RELEASE_TOOL_PYTHON; "
        "python_command=$(npcink_ai_cloud_release_tool_python); "
        'npcink_ai_cloud_require_release_tool_python "${python_command}"'
    )
    default_completed = subprocess.run(
        ["bash", "-c", default_shell],
        text=True,
        capture_output=True,
        check=False,
    )
    assert default_completed.returncode == 0, default_completed.stderr

    old_python = tmp_path / "old-python"
    _write(old_python, "#!/usr/bin/env bash\nexit 1\n", executable=True)
    shell = (
        f". {common}; "
        f"NPCINK_CLOUD_RELEASE_TOOL_PYTHON={old_python}; "
        "python_command=$(npcink_ai_cloud_release_tool_python); "
        'npcink_ai_cloud_require_release_tool_python "${python_command}"'
    )
    completed = subprocess.run(
        ["bash", "-c", shell],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 1
    assert "Python 3.9 or newer is required" in completed.stderr

    python310 = tmp_path / "python310"
    _write(
        python310,
        r"""#!/usr/bin/env bash
set -euo pipefail
case "${2:-}" in
    *"(3, 9)"*) exit 0 ;;
    *"(3, 11)"*) exit 1 ;;
    *) exit 64 ;;
esac
""",
        executable=True,
    )
    host_shell = (
        f". {common}; "
        f"NPCINK_CLOUD_RELEASE_TOOL_PYTHON={python310}; "
        "python_command=$(npcink_ai_cloud_release_tool_python); "
        'npcink_ai_cloud_require_host_release_tool_python "${python_command}"'
    )
    host_completed = subprocess.run(
        ["bash", "-c", host_shell],
        text=True,
        capture_output=True,
        check=False,
    )
    assert host_completed.returncode == 1
    assert "Host release-tool Python 3.11 or newer is required" in host_completed.stderr

    for relative_path in (
        "deploy/verify-release-bundle.sh",
        "deploy/remote-load-and-up.sh",
        "deploy/remote-operational-ready.sh",
    ):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert 'RELEASE_TOOL_PYTHON="$(npcink_ai_cloud_release_tool_python)"' in source
        assert "npcink_ai_cloud_require_release_tool_python" in source
        assert not re.search(r"(?<![A-Za-z0-9_])python3(?![A-Za-z0-9_])", source)

    deploy = (ROOT / "deploy/deploy-to-ssh-host.sh").read_text(encoding="utf-8")
    assert 'DEPLOY_HOST_PYTHON="${NPCINK_CLOUD_DEPLOY_HOST_PYTHON:-/usr/bin/python3.11}"' in deploy
    assert "npcink_ai_cloud_require_host_release_tool_python" in deploy


def test_runtime_compose_never_pulls_and_v227_run_commands_have_no_pull_flag() -> None:
    runtime_compose = (ROOT / "docker-compose.runtime.yml").read_text(encoding="utf-8")
    service_names = (
        "postgres",
        "redis",
        "api",
        "frontend",
        "worker",
        "callback-worker",
        "ops-worker",
        "proxy",
        "release-one-off",
    )
    for index, service_name in enumerate(service_names):
        start = runtime_compose.index(f"  {service_name}:\n")
        if index + 1 < len(service_names):
            end = runtime_compose.index(f"  {service_names[index + 1]}:\n", start)
        else:
            end = runtime_compose.index("\nvolumes:\n", start)
        block = runtime_compose[start:end]
        assert "    image:" in block
        assert "    pull_policy: never\n" in block

    migrate = (ROOT / "deploy/remote-migrate.sh").read_text(encoding="utf-8")
    refresh = (ROOT / "deploy/remote-refresh-providers.sh").read_text(encoding="utf-8")
    loader = (ROOT / "deploy/remote-load-and-up.sh").read_text(encoding="utf-8")
    assert "run --rm --no-deps --pull never" not in migrate
    assert "run --rm --no-deps --pull never" not in refresh
    assert "npcink_ai_cloud_compose_run_with_image_proof" in migrate
    assert "npcink_ai_cloud_compose_run_with_image_proof" in refresh
    assert "loaded-role-daemon-id" in migrate
    assert "loaded-role-daemon-id" in refresh
    assert "exec -T api" not in refresh
    assert "NPCINK_CLOUD_REFRESH_PROVIDERS_ONE_OFF" not in refresh
    assert "up -d --pull never --no-build" not in migrate
    assert "worker callback-worker ops-worker" not in migrate
    assert "Migration completed without starting application services" in migrate
    assert "up -d --pull never --no-build" not in loader
    assert "up --no-start --pull never --no-build --no-deps --force-recreate" in loader
    assert 'docker start "${container_ids_to_start[@]}"' in loader
    assert 'LOAD_MODE="${NPCINK_CLOUD_LOAD_MODE:-}"' in loader
    assert "full|" not in loader
    assert "npcink-ai-cloud-postgres:prod" in loader
    assert "npcink-ai-cloud-external-redis:prod" in loader
    assert "{{.Image}}" in loader
    assert "true false 0 healthy" in loader


def test_exact_loader_rejects_compose_file_outside_release(tmp_path: Path) -> None:
    external_compose = tmp_path / "external-compose.yml"
    external_compose.write_text("services: {}\n", encoding="utf-8")
    completed, docker_log, identity_log = (
        _run_remote_data_only_with_distinct_portable_and_daemon_ids(
            tmp_path,
            compose_file_env=str(external_compose),
        )
    )

    assert completed.returncode != 0
    assert "requires a canonical bundled Compose file" in completed.stderr
    assert docker_log == ""
    assert identity_log == ""


def _run_remote_migrate_with_distinct_portable_and_daemon_ids(
    tmp_path: Path,
    *,
    tag_image_id: str,
    container_image_id: str,
    identity_proof_status: int = 0,
    install_deploy_owner: bool = True,
) -> tuple[subprocess.CompletedProcess[str], str, str]:
    release = tmp_path / "release-fixture"
    fake_bin = tmp_path / "bin"
    docker_log_path = tmp_path / "docker.log"
    identity_log_path = tmp_path / "identity.log"
    portable_config_image_id = f"sha256:{'a' * 64}"
    target_daemon_image_id = f"sha256:{'b' * 64}"

    (release / "deploy").mkdir(parents=True)
    (release / "scripts").mkdir()
    (release / "docker-compose.prod.yml").write_text(
        "services: {}\n", encoding="utf-8"
    )
    (tmp_path / ".release-state").mkdir(mode=0o700)
    fake_bin.mkdir()
    shutil.copy2(ROOT / "deploy/common.sh", release / "deploy/common.sh")
    shutil.copy2(ROOT / "deploy/remote-migrate.sh", release / "deploy/remote-migrate.sh")
    _write(
        release / "scripts/verify-release-bundle-manifest.py",
        r"""from __future__ import annotations

import os
import sys

with open(os.environ["IDENTITY_LOG"], "a", encoding="utf-8") as handle:
    handle.write(" ".join(sys.argv[1:]) + "\n")

command = sys.argv[1] if len(sys.argv) > 1 else ""
if command == "loaded-role-daemon-id":
    if int(os.environ["IDENTITY_PROOF_STATUS"]) != 0:
        raise SystemExit(int(os.environ["IDENTITY_PROOF_STATUS"]))
    print(os.environ["TARGET_DAEMON_IMAGE_ID"])
else:
    raise SystemExit(64)
""",
    )
    _write(
        fake_bin / "docker",
        r"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${DOCKER_LOG}"
if [[ "$*" == *" config --format json release-one-off" ]]; then
    printf '{"services":{"release-one-off":{"image":"%s"}}}\n' "${NPCINK_CLOUD_API_RELEASE_IMAGE}"
    exit 0
fi
if [[ "$*" == *" ps --all -q release-one-off" ]]; then
    [ ! -f "${CANDIDATE_STATE_PATH}" ] || printf '%s\n' 'proof-api-container'
    exit 0
fi
if [[ "$*" == *" up --no-start "*" release-one-off" ]]; then
    rm -f "${STARTED_STATE}"
    : >"${CANDIDATE_STATE_PATH}"
    exit 0
fi
if [[ "$*" == compose\ * && "$*" == *" rm -f -s release-one-off" ]]; then
    rm -f "${CANDIDATE_STATE_PATH}" "${STARTED_STATE}"
    exit 0
fi
case "${1:-} ${2:-}" in
    "container ls")
        [ ! -f "${CANDIDATE_STATE_PATH}" ] || printf '%s\n' 'proof-api-container'
        exit 0
        ;;
    "image inspect")
        printf '%s\n' "${TAG_IMAGE_ID}"
        ;;
    "compose --env-file"|"compose -f")
        exit 0
        ;;
    "inspect --format")
        case "${3:-}" in
            "{{.State.Status}} {{.RestartCount}}")
                if [ -f "${STARTED_STATE}" ]; then
                    printf '%s\n' 'running 0'
                else
                    printf '%s\n' 'created 0'
                fi
                ;;
            "{{.State.Running}}")
                if [ -f "${STARTED_STATE}" ]; then
                    printf '%s\n' 'true'
                else
                    printf '%s\n' 'false'
                fi
                ;;
            *) printf '%s\n' "${CONTAINER_IMAGE_ID}" ;;
        esac
        ;;
    "start proof-api-container")
        : >"${STARTED_STATE}"
        exit 0
        ;;
    "exec -i")
        exit 0
        ;;
    "rm -f")
        rm -f "${CANDIDATE_STATE_PATH}" "${STARTED_STATE}"
        exit 0
        ;;
    *)
        exit 64
        ;;
esac
""",
        executable=True,
    )
    env_file = release / "env.deploy"
    env_file.write_text("NPCINK_CLOUD_COMPOSE_PROJECT_NAME=npcink-ai-cloud\n")
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "DOCKER_LOG": str(docker_log_path),
            "IDENTITY_LOG": str(identity_log_path),
            "PORTABLE_CONFIG_IMAGE_ID": portable_config_image_id,
            "TARGET_DAEMON_IMAGE_ID": target_daemon_image_id,
            "IDENTITY_PROOF_STATUS": str(identity_proof_status),
            "TAG_IMAGE_ID": tag_image_id,
            "CONTAINER_IMAGE_ID": container_image_id,
            "STARTED_STATE": str(tmp_path / "started.state"),
            "CANDIDATE_STATE_PATH": str(tmp_path / "candidate.state"),
            "NPCINK_CLOUD_ENV_FILE": str(env_file),
            "NPCINK_CLOUD_COMPOSE_FILE": str(release / "docker-compose.prod.yml"),
            "NPCINK_CLOUD_RELEASE_TOOL_PYTHON": sys.executable,
        }
    )
    if install_deploy_owner:
        _install_deploy_lock_owner(release, environment)
    completed = subprocess.run(
        ["bash", str(release / "deploy/remote-migrate.sh")],
        cwd=release,
        env=environment,
        text=True,
        input="",
        capture_output=True,
        check=False,
    )
    docker_log = docker_log_path.read_text(encoding="utf-8") if docker_log_path.exists() else ""
    identity_log = (
        identity_log_path.read_text(encoding="utf-8") if identity_log_path.exists() else ""
    )
    return completed, docker_log, identity_log


def test_remote_migrate_accepts_distinct_portable_and_target_daemon_ids_after_proof(
    tmp_path: Path,
) -> None:
    target_daemon_image_id = f"sha256:{'b' * 64}"
    completed, docker_log, identity_log = _run_remote_migrate_with_distinct_portable_and_daemon_ids(
        tmp_path,
        tag_image_id=target_daemon_image_id,
        container_image_id=target_daemon_image_id,
    )

    assert completed.returncode == 0, completed.stderr
    assert "loaded-role-daemon-id --root" in identity_log
    assert "--role api" in identity_log
    assert "role-image-id" not in identity_log
    assert docker_log.count("up --no-start --pull never") == 2
    assert docker_log.count("start proof-api-container") == 2
    assert docker_log.count("exec -i proof-api-container") == 2


def test_remote_migrate_blocks_before_container_when_loaded_identity_proof_fails(
    tmp_path: Path,
) -> None:
    target_daemon_image_id = f"sha256:{'b' * 64}"
    completed, docker_log, identity_log = _run_remote_migrate_with_distinct_portable_and_daemon_ids(
        tmp_path,
        tag_image_id=target_daemon_image_id,
        container_image_id=target_daemon_image_id,
        identity_proof_status=71,
    )

    assert completed.returncode != 0
    assert "loaded-role-daemon-id --root" in identity_log
    assert "compose " not in docker_log
    assert "exec -i" not in docker_log


def test_remote_migrate_requires_matching_deploy_owner_before_manifest_or_docker(
    tmp_path: Path,
) -> None:
    target_daemon_image_id = f"sha256:{'b' * 64}"
    completed, docker_log, identity_log = (
        _run_remote_migrate_with_distinct_portable_and_daemon_ids(
            tmp_path,
            tag_image_id=target_daemon_image_id,
            container_image_id=target_daemon_image_id,
            install_deploy_owner=False,
        )
    )

    assert completed.returncode != 0
    assert "matching deployment-lock owner proof" in completed.stderr
    assert identity_log == ""
    assert docker_log == ""


def _run_remote_data_only_with_distinct_portable_and_daemon_ids(
    tmp_path: Path,
    *,
    identity_proof_failure_role: str = "",
    postgres_container_image_id: str | None = None,
    redis_container_image_id: str | None = None,
    compose_file_env: str | None = None,
    run_cwd: Path | None = None,
    install_deploy_owner: bool = True,
) -> tuple[subprocess.CompletedProcess[str], str, str]:
    release = tmp_path / "release-fixture"
    fake_bin = tmp_path / "bin"
    docker_log_path = tmp_path / "docker.log"
    identity_log_path = tmp_path / "identity.log"
    portable_postgres_image_id = f"sha256:{'a' * 64}"
    portable_redis_image_id = f"sha256:{'b' * 64}"
    target_postgres_image_id = f"sha256:{'c' * 64}"
    target_redis_image_id = f"sha256:{'d' * 64}"

    (release / "deploy").mkdir(parents=True)
    (release / "scripts").mkdir()
    fake_bin.mkdir()
    shutil.copy2(ROOT / "deploy/common.sh", release / "deploy/common.sh")
    shutil.copy2(
        ROOT / "deploy/remote-load-and-up.sh",
        release / "deploy/remote-load-and-up.sh",
    )
    _write(
        release / "scripts/verify-release-bundle-manifest.py",
        r"""from __future__ import annotations

import os
import sys

with open(os.environ["IDENTITY_LOG"], "a", encoding="utf-8") as handle:
    handle.write(" ".join(sys.argv[1:]) + "\n")

arguments = sys.argv[1:]
if len(arguments) != 5 or arguments[1] != "--root" or arguments[3] != "--role":
    raise SystemExit(64)

command = arguments[0]
role = arguments[4]
portable_ids = {
    "postgres": os.environ["PORTABLE_POSTGRES_IMAGE_ID"],
    "external_redis": os.environ["PORTABLE_REDIS_IMAGE_ID"],
}
target_ids = {
    "postgres": os.environ["TARGET_POSTGRES_IMAGE_ID"],
    "external_redis": os.environ["TARGET_REDIS_IMAGE_ID"],
}
if role not in target_ids:
    raise SystemExit(64)
if command == "loaded-role-daemon-id":
    if role == os.environ["IDENTITY_PROOF_FAILURE_ROLE"]:
        raise SystemExit(71)
    print(target_ids[role])
else:
    raise SystemExit(64)
""",
    )
    _write(
        fake_bin / "docker",
        r"""#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

arguments = sys.argv[1:]
with open(os.environ["DOCKER_LOG"], "a", encoding="utf-8") as handle:
    handle.write(" ".join(arguments) + "\n")

if arguments[:2] == ["image", "inspect"]:
    reference = arguments[-1]
    image_ids = {
        "npcink-ai-cloud-postgres:prod": os.environ["TARGET_POSTGRES_IMAGE_ID"],
        "npcink-ai-cloud-external-redis:prod": os.environ["TARGET_REDIS_IMAGE_ID"],
    }
    if reference not in image_ids:
        raise SystemExit(64)
    print(image_ids[reference])
    raise SystemExit(0)

if arguments[:1] == ["compose"]:
    if "up" in arguments:
        raise SystemExit(0)
    if arguments[-4:] == ["ps", "--all", "-q", "postgres"]:
        print("postgres-container")
        raise SystemExit(0)
    if arguments[-4:] == ["ps", "--all", "-q", "redis"]:
        print("redis-container")
        raise SystemExit(0)
    if arguments[-3:] == ["ps", "-q", "postgres"]:
        print("postgres-container")
        raise SystemExit(0)
    if arguments[-3:] == ["ps", "-q", "redis"]:
        print("redis-container")
        raise SystemExit(0)
    raise SystemExit(64)

if arguments[:1] == ["start"]:
    open(os.environ["STARTED_STATE"], "w", encoding="utf-8").close()
    raise SystemExit(0)

if arguments[:2] == ["rm", "-f"]:
    raise SystemExit(0)

if arguments[:2] == ["inspect", "--format"] and len(arguments) == 4:
    inspect_format = arguments[2]
    container_id = arguments[3]
    if inspect_format == "{{.Image}}":
        container_ids = {
            "postgres-container": os.environ["POSTGRES_CONTAINER_IMAGE_ID"],
            "redis-container": os.environ["REDIS_CONTAINER_IMAGE_ID"],
        }
        if container_id not in container_ids:
            raise SystemExit(64)
        print(container_ids[container_id])
        raise SystemExit(0)
    started = os.path.exists(os.environ["STARTED_STATE"])
    if inspect_format == "{{.State.Status}} {{.RestartCount}}":
        print("running 0" if started else "created 0")
        raise SystemExit(0)
    if inspect_format == "{{.State.Running}}":
        print("true" if started else "false")
        raise SystemExit(0)
    if ".State.Running" in inspect_format:
        print("true false 0 healthy")
        raise SystemExit(0)

raise SystemExit(64)
""",
        executable=True,
    )
    _write(
        fake_bin / "sleep",
        "#!/usr/bin/env bash\nexit 0\n",
        executable=True,
    )
    _write(
        fake_bin / "curl",
        "#!/usr/bin/env bash\nexit 86\n",
        executable=True,
    )
    (release / "docker-compose.prod.yml").write_text(
        "services: {}\n",
        encoding="utf-8",
    )
    env_file = release / "env.deploy"
    env_file.write_text(
        "NPCINK_CLOUD_COMPOSE_PROJECT_NAME=npcink-ai-cloud\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "DOCKER_LOG": str(docker_log_path),
            "IDENTITY_LOG": str(identity_log_path),
            "PORTABLE_POSTGRES_IMAGE_ID": portable_postgres_image_id,
            "PORTABLE_REDIS_IMAGE_ID": portable_redis_image_id,
            "TARGET_POSTGRES_IMAGE_ID": target_postgres_image_id,
            "TARGET_REDIS_IMAGE_ID": target_redis_image_id,
            "IDENTITY_PROOF_FAILURE_ROLE": identity_proof_failure_role,
            "POSTGRES_CONTAINER_IMAGE_ID": (
                postgres_container_image_id or target_postgres_image_id
            ),
            "REDIS_CONTAINER_IMAGE_ID": (redis_container_image_id or target_redis_image_id),
            "STARTED_STATE": str(tmp_path / "started.state"),
            "NPCINK_CLOUD_LOAD_MODE": "data-only",
            "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN": "fixture-internal-token-at-least-32-chars",
            "NPCINK_CLOUD_BASE_URL": "http://127.0.0.1:8110",
            "NPCINK_CLOUD_ENV_FILE": str(env_file),
            "NPCINK_CLOUD_COMPOSE_FILE": compose_file_env
            or str(release / "docker-compose.prod.yml"),
            "NPCINK_CLOUD_RELEASE_TOOL_PYTHON": sys.executable,
        }
    )
    if install_deploy_owner:
        _install_deploy_lock_owner(release, environment)
    completed = subprocess.run(
        ["bash", str(release / "deploy/remote-load-and-up.sh")],
        cwd=run_cwd or release,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    docker_log = docker_log_path.read_text(encoding="utf-8") if docker_log_path.exists() else ""
    identity_log = (
        identity_log_path.read_text(encoding="utf-8") if identity_log_path.exists() else ""
    )
    return completed, docker_log, identity_log


def test_remote_data_only_accepts_distinct_portable_and_target_daemon_ids(
    tmp_path: Path,
) -> None:
    completed, docker_log, identity_log = (
        _run_remote_data_only_with_distinct_portable_and_daemon_ids(tmp_path)
    )

    assert completed.returncode == 0, completed.stderr
    assert identity_log.count("loaded-role-daemon-id") == 4
    assert "--role postgres" in identity_log
    assert "--role external_redis" in identity_log
    assert "role-image-id" not in identity_log
    assert (
        docker_log.count(
            "up --no-start --pull never --no-build --no-deps --force-recreate postgres redis"
        )
        == 1
    )
    assert "ps -q postgres" in docker_log
    assert "ps -q redis" in docker_log
    assert (
        "[ok] Data service postgres uses the frozen exact image ID and is healthy."
        in completed.stdout
    )
    assert (
        "[ok] Data service redis uses the frozen exact image ID and is healthy." in completed.stdout
    )
    assert "[ok] Data services are ready for one-off migration." in completed.stdout


def test_remote_data_only_requires_matching_deploy_owner_before_manifest_or_docker(
    tmp_path: Path,
) -> None:
    completed, docker_log, identity_log = (
        _run_remote_data_only_with_distinct_portable_and_daemon_ids(
            tmp_path,
            install_deploy_owner=False,
        )
    )

    assert completed.returncode != 0
    assert "matching deployment-lock owner proof" in completed.stderr
    assert identity_log == ""
    assert docker_log == ""


def test_exact_loader_executes_the_canonical_compose_file_from_external_cwd(
    tmp_path: Path,
) -> None:
    external_compose = tmp_path / "docker-compose.prod.yml"
    external_compose.write_text("services:\n  attacker-controlled: {}\n", encoding="utf-8")

    completed, docker_log, _ = _run_remote_data_only_with_distinct_portable_and_daemon_ids(
        tmp_path,
        compose_file_env="docker-compose.prod.yml",
        run_cwd=tmp_path,
    )

    canonical_compose = tmp_path / "release-fixture" / "docker-compose.prod.yml"
    assert completed.returncode == 0, completed.stderr
    assert f"-f {canonical_compose}" in docker_log
    assert f"-f {external_compose}" not in docker_log


def test_remote_data_only_blocks_compose_when_second_identity_proof_fails(
    tmp_path: Path,
) -> None:
    completed, docker_log, identity_log = (
        _run_remote_data_only_with_distinct_portable_and_daemon_ids(
            tmp_path,
            identity_proof_failure_role="external_redis",
        )
    )

    assert completed.returncode != 0
    assert identity_log.count("loaded-role-daemon-id") == 2
    assert "--role postgres" in identity_log
    assert "--role external_redis" in identity_log
    assert docker_log == ""
    assert "Data services are ready for one-off migration." not in completed.stdout


def test_remote_data_only_rejects_healthy_container_with_unproved_image_id(
    tmp_path: Path,
) -> None:
    unproved_image_id = f"sha256:{'e' * 64}"
    completed, docker_log, identity_log = (
        _run_remote_data_only_with_distinct_portable_and_daemon_ids(
            tmp_path,
            redis_container_image_id=unproved_image_id,
        )
    )

    assert completed.returncode != 0
    assert identity_log.count("loaded-role-daemon-id") == 2
    assert "up --no-start --pull never --no-build" in docker_log
    assert "start postgres-container redis-container" not in docker_log
    assert docker_log.count("inspect --format {{.Image}} redis-container") == 1
    assert ".State.Running" not in docker_log
    assert "[ok] Data service postgres" not in completed.stdout
    assert "[ok] Data service redis" not in completed.stdout
    assert "does not use the proved target-daemon image ID" in completed.stderr
    assert "Data services are ready for one-off migration." not in completed.stdout


def _run_remote_service_phase(
    tmp_path: Path,
    *,
    load_mode: str,
    mismatch_service: str = "",
    skip_frontend: bool = False,
    candidate_state: str = "created 0",
    start_failure_after: int = 0,
    cleanup_residue_service: str = "",
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    release = tmp_path / "release-fixture"
    fake_bin = tmp_path / "bin"
    event_log_path = tmp_path / "events.log"
    role_ids = {
        "api": f"sha256:{'a' * 64}",
        "worker": f"sha256:{'b' * 64}",
        "callback_worker": f"sha256:{'c' * 64}",
        "ops_worker": f"sha256:{'d' * 64}",
        "frontend": f"sha256:{'e' * 64}",
        "external_nginx": f"sha256:{'f' * 64}",
    }

    (release / "deploy").mkdir(parents=True)
    (release / "scripts").mkdir()
    fake_bin.mkdir()
    shutil.copy2(ROOT / "deploy/common.sh", release / "deploy/common.sh")
    shutil.copy2(
        ROOT / "deploy/remote-load-and-up.sh",
        release / "deploy/remote-load-and-up.sh",
    )
    _write(
        release / "scripts/verify-release-bundle-manifest.py",
        r"""from __future__ import annotations

import json
import os
import sys

arguments = sys.argv[1:]
if not arguments or arguments[0] != "loaded-role-daemon-id":
    raise SystemExit(64)
try:
    role = arguments[arguments.index("--role") + 1]
except (ValueError, IndexError):
    raise SystemExit(64)

role_ids = json.loads(os.environ["ROLE_IDS"])
if role not in role_ids:
    raise SystemExit(64)
with open(os.environ["EVENT_LOG"], "a", encoding="utf-8") as handle:
    handle.write(f"identity {role}\n")
print(role_ids[role])
""",
    )
    _write(
        fake_bin / "docker",
        r"""#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys

arguments = sys.argv[1:]
with open(os.environ["EVENT_LOG"], "a", encoding="utf-8") as handle:
    handle.write("docker " + " ".join(arguments) + "\n")

role_ids = json.loads(os.environ["ROLE_IDS"])
service_roles = {
    "api": "api",
    "worker": "worker",
    "callback-worker": "callback_worker",
    "ops-worker": "ops_worker",
    "frontend": "frontend",
    "proxy": "external_nginx",
}
service_references = {
    "npcink-ai-cloud-api:prod": "api",
    "npcink-ai-cloud-worker:prod": "worker",
    "npcink-ai-cloud-callback-worker:prod": "callback_worker",
    "npcink-ai-cloud-ops-worker:prod": "ops_worker",
    "npcink-ai-cloud-frontend:prod": "frontend",
    "npcink-ai-cloud-external-nginx:prod": "external_nginx",
}

def has_line(path, value):
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as handle:
        return value in {line.strip() for line in handle if line.strip()}

def append_lines(path, values):
    with open(path, "a", encoding="utf-8") as handle:
        for value in values:
            handle.write(value + "\n")

if arguments[:2] == ["image", "inspect"]:
    role = service_references.get(arguments[-1])
    if role is None:
        raise SystemExit(64)
    print(role_ids[role])
    raise SystemExit(0)

if arguments[:1] == ["compose"]:
    if "up" in arguments:
        raise SystemExit(0)
    if len(arguments) >= 4 and arguments[-4:-1] == ["ps", "--all", "-q"]:
        service = arguments[-1]
        if service not in service_roles:
            raise SystemExit(64)
        container_id = f"captured-{service}-container"
        if service == os.environ["CLEANUP_RESIDUE_SERVICE"] or not has_line(
            os.environ["REMOVED_IDS"], container_id
        ):
            print(container_id)
        raise SystemExit(0)
    if "exec" in arguments:
        raise SystemExit(0)
    raise SystemExit(64)

if arguments[:2] == ["inspect", "--format"] and len(arguments) == 4:
    inspect_format = arguments[2]
    container_id = arguments[3]
    prefix = "captured-"
    suffix = "-container"
    if not container_id.startswith(prefix) or not container_id.endswith(suffix):
        raise SystemExit(64)
    service = container_id[len(prefix) : -len(suffix)]
    role = service_roles.get(service)
    if role is None:
        raise SystemExit(64)
    if inspect_format == "{{.Image}}":
        if service == os.environ["MISMATCH_SERVICE"]:
            print("sha256:" + "0" * 64)
        else:
            print(role_ids[role])
        raise SystemExit(0)
    started = has_line(os.environ["STARTED_IDS"], container_id)
    if inspect_format == "{{.State.Status}} {{.RestartCount}}":
        print("running 0" if started else os.environ["CANDIDATE_STATE"])
        raise SystemExit(0)
    if inspect_format == "{{.State.Running}}":
        print("true" if started else "false")
        raise SystemExit(0)
    raise SystemExit(64)

if arguments[:1] == ["start"]:
    container_ids = arguments[1:]
    failure_after = int(os.environ["START_FAILURE_AFTER"])
    if failure_after:
        append_lines(os.environ["STARTED_IDS"], container_ids[:failure_after])
        raise SystemExit(71)
    append_lines(os.environ["STARTED_IDS"], container_ids)
    raise SystemExit(0)
if arguments[:1] == ["stop"]:
    raise SystemExit(0)
if arguments[:2] == ["rm", "-f"]:
    append_lines(os.environ["REMOVED_IDS"], arguments[2:])
    raise SystemExit(0)
if arguments[:1] == ["inspect"] and len(arguments) == 2:
    raise SystemExit(1 if has_line(os.environ["REMOVED_IDS"], arguments[1]) else 0)
if arguments[:2] == ["ps", "-aq"]:
    raise SystemExit(0)

raise SystemExit(64)
""",
        executable=True,
    )
    _write(
        fake_bin / "curl",
        r"""#!/usr/bin/env bash
set -euo pipefail
printf 'curl %s\n' "$*" >>"${EVENT_LOG}"
exit 0
""",
        executable=True,
    )
    (release / "docker-compose.prod.yml").write_text(
        "services: {}\n",
        encoding="utf-8",
    )
    env_file = release / "env.deploy"
    env_file.write_text(
        "NPCINK_CLOUD_COMPOSE_PROJECT_NAME=npcink-ai-cloud\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "EVENT_LOG": str(event_log_path),
            "ROLE_IDS": json.dumps(role_ids, sort_keys=True),
            "MISMATCH_SERVICE": mismatch_service,
            "STARTED_IDS": str(tmp_path / "started.ids"),
            "REMOVED_IDS": str(tmp_path / "removed.ids"),
            "CANDIDATE_STATE": candidate_state,
            "START_FAILURE_AFTER": str(start_failure_after),
            "CLEANUP_RESIDUE_SERVICE": cleanup_residue_service,
            "NPCINK_CLOUD_LOAD_MODE": load_mode,
            "NPCINK_CLOUD_SKIP_FRONTEND_IMAGE": "1" if skip_frontend else "0",
            "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN": ("fixture-internal-token-at-least-32-chars"),
            "NPCINK_CLOUD_BASE_URL": "http://127.0.0.1:8110",
            "NPCINK_CLOUD_ENV_FILE": str(env_file),
            "NPCINK_CLOUD_COMPOSE_FILE": str(release / "docker-compose.prod.yml"),
            "NPCINK_CLOUD_RELEASE_TOOL_PYTHON": sys.executable,
        }
    )
    _install_deploy_lock_owner(release, environment)
    completed = subprocess.run(
        ["bash", str(release / "deploy/remote-load-and-up.sh")],
        cwd=release,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    events = (
        event_log_path.read_text(encoding="utf-8").splitlines() if event_log_path.exists() else []
    )
    return completed, events


def _event_index(events: list[str], expected: str) -> int:
    return next(index for index, event in enumerate(events) if expected in event)


def test_remote_api_only_proves_before_create_and_starts_captured_container(
    tmp_path: Path,
) -> None:
    completed, events = _run_remote_service_phase(tmp_path, load_mode="api-only")

    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
    first_proof = _event_index(events, "identity api")
    create = _event_index(events, "docker compose ")
    candidate_proof = _event_index(
        events,
        "docker inspect --format {{.Image}} captured-api-container",
    )
    second_proof = next(
        index
        for index, event in enumerate(events)
        if index > first_proof and event == "identity api"
    )
    start = _event_index(events, "docker start captured-api-container")

    assert first_proof < create < candidate_proof < second_proof < start
    assert (
        "up --no-start --pull never --no-build --no-deps --force-recreate api" in (events[create])
    )
    assert "[ok] Staged API is internally ready." in completed.stdout


def test_remote_workers_only_rejects_batch_mismatch_without_starting_any_candidate(
    tmp_path: Path,
) -> None:
    completed, events = _run_remote_service_phase(
        tmp_path,
        load_mode="workers-only",
        mismatch_service="ops-worker",
    )

    assert completed.returncode != 0
    create = _event_index(events, "docker compose ")
    expected_roles = ("worker", "callback_worker", "ops_worker")
    initial_proofs = [_event_index(events, f"identity {role}") for role in expected_roles]
    assert max(initial_proofs) < create
    assert (
        "up --no-start --pull never --no-build --no-deps --force-recreate "
        "worker callback-worker ops-worker"
    ) in events[create]
    assert "docker inspect --format {{.Image}} captured-ops-worker-container" in events
    assert not any(event.startswith("docker start ") for event in events)
    assert "does not use the proved target-daemon image ID" in completed.stderr


def test_remote_workers_only_starts_captured_batch_after_complete_reproof(
    tmp_path: Path,
) -> None:
    completed, events = _run_remote_service_phase(
        tmp_path,
        load_mode="workers-only",
    )

    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
    expected_roles = ("worker", "callback_worker", "ops_worker")
    proof_indexes = {
        role: [index for index, event in enumerate(events) if event == f"identity {role}"]
        for role in expected_roles
    }
    assert all(len(indexes) == 2 for indexes in proof_indexes.values())
    create = _event_index(events, "docker compose ")
    candidate_proofs = [
        _event_index(
            events,
            f"docker inspect --format {{{{.Image}}}} captured-{service}-container",
        )
        for service in ("worker", "callback-worker", "ops-worker")
    ]
    start = _event_index(
        events,
        "docker start captured-worker-container captured-callback-worker-container "
        "captured-ops-worker-container",
    )

    assert max(indexes[0] for indexes in proof_indexes.values()) < create
    assert create < min(candidate_proofs)
    assert max(candidate_proofs) < min(indexes[1] for indexes in proof_indexes.values())
    assert max(indexes[1] for indexes in proof_indexes.values()) < start


def test_remote_workers_only_removes_entire_batch_after_partial_start_failure(
    tmp_path: Path,
) -> None:
    completed, events = _run_remote_service_phase(
        tmp_path,
        load_mode="workers-only",
        start_failure_after=2,
    )

    assert completed.returncode != 0
    assert any(
        event
        == "docker start captured-worker-container captured-callback-worker-container "
        "captured-ops-worker-container"
        for event in events
    )
    assert any(event.startswith("docker stop captured-worker-container") for event in events)
    for service in ("worker", "callback-worker", "ops-worker"):
        assert f"docker rm -f captured-{service}-container" in events
    assert "[ok] Started exact stopped candidates" not in completed.stdout


def test_remote_workers_only_requires_operator_recovery_when_cleanup_is_unproved(
    tmp_path: Path,
) -> None:
    completed, events = _run_remote_service_phase(
        tmp_path,
        load_mode="workers-only",
        start_failure_after=1,
        cleanup_residue_service="ops-worker",
    )

    assert completed.returncode != 0
    assert "docker rm -f captured-ops-worker-container" in events
    assert "operator recovery is required" in completed.stderr


def test_remote_traffic_only_skip_frontend_proves_and_starts_only_proxy(
    tmp_path: Path,
) -> None:
    completed, events = _run_remote_service_phase(
        tmp_path,
        load_mode="traffic-only",
        skip_frontend=True,
    )

    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
    assert events.count("identity external_nginx") == 2
    assert not any("identity frontend" in event for event in events)
    create = _event_index(events, "docker compose ")
    assert (
        "up --no-start --pull never --no-build --no-deps --force-recreate --remove-orphans proxy"
    ) in events[create]
    assert "docker start captured-proxy-container" in events
    assert not any("captured-frontend-container" in event for event in events)
    assert any(event.startswith("curl ") for event in events)
    assert "[info] Restoring public traffic last: proxy" in completed.stdout
    assert "[ok] Public traffic now serves the new Cloud release" in completed.stdout


@pytest.mark.parametrize("candidate_state", ("running 0", "exited 0"))
def test_remote_api_only_rejects_candidate_that_was_already_started(
    tmp_path: Path,
    candidate_state: str,
) -> None:
    completed, events = _run_remote_service_phase(
        tmp_path,
        load_mode="api-only",
        candidate_state=candidate_state,
    )

    assert completed.returncode != 0
    assert "docker inspect --format {{.State.Status}} {{.RestartCount}} captured-api-container" in (
        events
    )
    assert not any(event.startswith("docker start ") for event in events)
    assert "candidate was not proved never-started" in completed.stderr


def _run_one_off_image_proof(
    tmp_path: Path,
    *,
    actual_image_id: str,
    expected_daemon_image_id: str | None = None,
    run_status: int = 0,
    cleanup_status: int = 0,
    tag_image_id: str | None = None,
    terminate_during_payload: bool = False,
    terminate_during_stdin_capture: bool = False,
    stdin_payload: str = "one-off-stdin-sentinel\nsecond-line\n",
    candidate_state: str = "created 0",
    candidate_ids: str = "proof-api-container",
    preexisting_lock: bool = False,
    preexisting_container: bool = False,
    deploy_lock_owner: str | None = None,
    configured_deploy_lock_owner: str | None = None,
    cleanup_query_failure: bool = False,
) -> tuple[subprocess.CompletedProcess[str], str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_path = tmp_path / "docker.log"
    stdin_observation_path = tmp_path / "stdin-observation.json"
    stdin_tmp_dir = tmp_path / "one-off-tmp"
    stdin_tmp_dir.mkdir()
    release_root = tmp_path / "release-fixture"
    release_root.mkdir()
    compose_file = release_root / "docker-compose.runtime.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    state_root = tmp_path / ".release-state"
    state_root.mkdir(mode=0o700)
    if preexisting_lock:
        (state_root / ".release-one-off.lock").mkdir(mode=0o700)
    if preexisting_container:
        (tmp_path / "candidate.state").touch()
    if deploy_lock_owner is not None:
        deploy_lock = tmp_path / ".deploy-lock"
        deploy_lock.mkdir(mode=0o700)
        owner_file = deploy_lock / "one-off-owner"
        owner_file.write_text(deploy_lock_owner + "\n", encoding="utf-8")
        owner_file.chmod(0o600)
    expected_daemon_image_id = expected_daemon_image_id or f"sha256:{'a' * 64}"
    tag_image_id = tag_image_id or expected_daemon_image_id
    _write(
        fake_bin / "docker",
        r"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${DOCKER_LOG}"
if [[ "$*" == *" config --format json release-one-off" ]]; then
    printf '{"services":{"release-one-off":{"image":"%s"}}}\n' "${NPCINK_CLOUD_API_RELEASE_IMAGE}"
    exit 0
fi
if [[ "$*" == *" ps --all -q release-one-off" ]]; then
    [ ! -f "${CANDIDATE_STATE_PATH}" ] || printf '%s\n' "${CANDIDATE_IDS}"
    exit 0
fi
if [[ "$*" == *" up --no-start "*" release-one-off" ]]; then
    rm -f "${STARTED_STATE}"
    : >"${CANDIDATE_STATE_PATH}"
    exit 0
fi
if [[ "$*" == compose\ * && "$*" == *" rm -f -s release-one-off" ]]; then
    if [ "${CLEANUP_STATUS}" -eq 0 ]; then
        rm -f "${CANDIDATE_STATE_PATH}" "${STARTED_STATE}"
    fi
    exit "${CLEANUP_STATUS}"
fi
case "${1:-} ${2:-}" in
	"container ls")
		if [ "${CLEANUP_QUERY_FAILURE}" = "1" ] && \
			[ -e "${CLEANUP_PROBE_ARMED}" ]; then
			exit 75
		fi
        [ ! -f "${CANDIDATE_STATE_PATH}" ] || printf '%s\n' 'proof-api-container'
        exit 0
        ;;
    "image inspect")
        printf '%s\n' "${TAG_IMAGE_ID}"
        ;;
    "compose --env-file"|"compose -f")
        exit 0
        ;;
    "inspect --format")
        case "${3:-}" in
            "{{.State.Status}} {{.RestartCount}}")
                if [ -f "${STARTED_STATE}" ]; then
                    printf '%s\n' 'running 0'
                else
                    printf '%s\n' "${CANDIDATE_STATE}"
                fi
                ;;
            "{{.State.Running}}")
                if [ -f "${STARTED_STATE}" ]; then
                    printf '%s\n' 'true'
                else
                    printf '%s\n' 'false'
                fi
                ;;
            *) printf '%s\n' "${ACTUAL_IMAGE_ID}" ;;
        esac
        ;;
    "start proof-api-container")
        : >"${STARTED_STATE}"
        exit 0
        ;;
	"exec -i")
		"${TEST_PYTHON}" -c '
import json
import os
import stat
import sys
from pathlib import Path

payload = sys.stdin.buffer.read()
temporary_root = Path(os.environ["TMPDIR"])
protected_directories = list(temporary_root.glob("npcink-release-proof-stdin.*"))
assert len(protected_directories) == 1
protected_directory = protected_directories[0]
protected_files = list(protected_directory.iterdir())
assert len(protected_files) == 1
protected_file = protected_files[0]
directory_stat = os.lstat(protected_directory)
file_stat = os.lstat(protected_file)
stdin_stat = os.fstat(0)
with open(os.environ["STDIN_OBSERVATION_PATH"], "w", encoding="utf-8") as handle:
    json.dump(
        {
            "directory_is_symlink": stat.S_ISLNK(directory_stat.st_mode),
            "directory_mode": stat.S_IMODE(directory_stat.st_mode),
            "directory_owned": directory_stat.st_uid == os.geteuid(),
            "file_is_symlink": stat.S_ISLNK(file_stat.st_mode),
            "file_mode": stat.S_IMODE(file_stat.st_mode),
            "file_owned": file_stat.st_uid == os.geteuid(),
            "payload_hex": payload.hex(),
            "stdin_mode": stat.S_IMODE(stdin_stat.st_mode),
            "stdin_owned": stdin_stat.st_uid == os.geteuid(),
        },
        handle,
        sort_keys=True,
    )
'
        if [ "${RUN_SLEEP_SECONDS:-0}" -gt 0 ]; then
            sleep "${RUN_SLEEP_SECONDS}"
        fi
        exit "${RUN_STATUS}"
        ;;
	"rm -f")
        if [ "${CLEANUP_STATUS}" -eq 0 ]; then
            rm -f "${CANDIDATE_STATE_PATH}" "${STARTED_STATE}"
			if [ "${CLEANUP_QUERY_FAILURE}" = "1" ]; then
				: >"${CLEANUP_PROBE_ARMED}"
			fi
        fi
        exit "${CLEANUP_STATUS}"
        ;;
    *)
        exit 64
        ;;
esac
""",
        executable=True,
    )
    env_file = tmp_path / "env.deploy"
    env_file.write_text("NPCINK_CLOUD_COMPOSE_PROJECT_NAME=npcink-ai-cloud\n")
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "DOCKER_LOG": str(log_path),
            "STDIN_OBSERVATION_PATH": str(stdin_observation_path),
            "TAG_IMAGE_ID": tag_image_id,
            "ACTUAL_IMAGE_ID": actual_image_id,
            "RUN_STATUS": str(run_status),
            "CLEANUP_STATUS": str(cleanup_status),
            "RUN_SLEEP_SECONDS": "30" if terminate_during_payload else "0",
            "STARTED_STATE": str(tmp_path / "started.state"),
            "CANDIDATE_STATE_PATH": str(tmp_path / "candidate.state"),
            "CANDIDATE_STATE": candidate_state,
            "CANDIDATE_IDS": candidate_ids,
            "CLEANUP_QUERY_FAILURE": "1" if cleanup_query_failure else "0",
            "CLEANUP_PROBE_ARMED": str(tmp_path / "cleanup-probe-armed"),
            "NPCINK_CLOUD_ENV_FILE": str(env_file),
            "NPCINK_CLOUD_COMPOSE_FILE": str(compose_file),
            "TMPDIR": str(stdin_tmp_dir),
            "TEST_PYTHON": sys.executable,
        }
    )
    if configured_deploy_lock_owner is not None:
        environment["NPCINK_CLOUD_DEPLOY_LOCK_OWNER"] = configured_deploy_lock_owner
    shell = (
        "set -euo pipefail; "
        f". {ROOT / 'deploy/common.sh'}; "
        f"npcink_ai_cloud_compose_run_with_image_proof {release_root} api "
        f"npcink-ai-cloud-api:prod {expected_daemon_image_id} python -c 'print(1)'"
    )
    if terminate_during_stdin_capture:
        process = subprocess.Popen(
            ["bash", "-c", shell],
            env=environment,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        assert process.stdin is not None
        process.stdin.write(stdin_payload)
        process.stdin.flush()
        expected_size = len(stdin_payload.encode())
        deadline = time.monotonic() + 10
        while True:
            protected_files = list(stdin_tmp_dir.glob("npcink-release-proof-stdin.*/payload.stdin"))
            if len(protected_files) == 1 and protected_files[0].stat().st_size == expected_size:
                break
            if process.poll() is not None:
                break
            if time.monotonic() >= deadline:
                process.kill()
                raise AssertionError("stdin capture did not start before timeout")
            time.sleep(0.02)
        process.send_signal(signal.SIGTERM)
        signal_deadline = time.monotonic() + 2
        while process.poll() is None and time.monotonic() < signal_deadline:
            time.sleep(0.02)
        if process.poll() is None:
            process.stdin.close()
            process.stdin = None
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=10)
            raise AssertionError("TERM did not interrupt protected stdin capture")
        try:
            process.stdin.close()
        except BrokenPipeError:
            pass
        process.stdin = None
        stdout, stderr = process.communicate(timeout=10)
        completed = subprocess.CompletedProcess(
            ["bash", "-c", shell],
            process.returncode,
            stdout,
            stderr,
        )
    elif terminate_during_payload:
        caller_stdin = tmp_path / "caller-stdin.txt"
        caller_stdin.write_text(stdin_payload, encoding="utf-8")
        with caller_stdin.open(encoding="utf-8") as stdin_handle:
            process = subprocess.Popen(
                ["bash", "-c", shell],
                env=environment,
                text=True,
                stdin=stdin_handle,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        deadline = time.monotonic() + 10
        while True:
            docker_log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            observation_ready = False
            if stdin_observation_path.exists():
                try:
                    observation = json.loads(stdin_observation_path.read_text(encoding="utf-8"))
                    observation_ready = (
                        bytes.fromhex(observation["payload_hex"]) == stdin_payload.encode()
                    )
                except (json.JSONDecodeError, KeyError, OSError, ValueError):
                    observation_ready = False
            if "exec -i" in docker_log and observation_ready:
                break
            if process.poll() is not None:
                break
            if time.monotonic() >= deadline:
                process.kill()
                raise AssertionError("one-off payload did not start before timeout")
            time.sleep(0.02)
        os.killpg(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)
        completed = subprocess.CompletedProcess(
            ["bash", "-c", shell],
            process.returncode,
            stdout,
            stderr,
        )
    else:
        completed = subprocess.run(
            ["bash", "-c", shell],
            env=environment,
            text=True,
            input=stdin_payload,
            capture_output=True,
            check=False,
        )
    docker_log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    return completed, docker_log


def test_one_off_image_proof_inspects_exact_container_and_cleans_it(
    tmp_path: Path,
) -> None:
    exact_image_id = f"sha256:{'b' * 64}"
    completed, docker_log = _run_one_off_image_proof(
        tmp_path,
        actual_image_id=exact_image_id,
        expected_daemon_image_id=exact_image_id,
    )

    assert completed.returncode == 0, completed.stderr
    assert "up --no-start --pull never --no-build --no-deps --force-recreate release-one-off" in (
        docker_log
    )
    assert "ps --all -q release-one-off" in docker_log
    assert "start proof-api-container" in docker_log
    assert "exec -i proof-api-container" in docker_log
    assert " python -c print(1)" in docker_log
    assert docker_log.count("inspect --format {{.Image}} proof-api-container") == 2
    assert (
        docker_log.count("inspect --format {{.State.Status}} {{.RestartCount}} proof-api-container")
        == 1
    )
    assert docker_log.count("inspect --format {{.State.Running}} proof-api-container") == 1
    assert docker_log.count("image inspect --format {{.Id}} npcink-ai-cloud-api:prod") == 4
    assert "rm -f proof-api-container" in docker_log
    assert docker_log.index("inspect --format {{.Image}} proof-api-container") < docker_log.index(
        "start proof-api-container"
    )
    assert docker_log.index("start proof-api-container") < docker_log.index(
        "exec -i proof-api-container"
    )
    observation = json.loads((tmp_path / "stdin-observation.json").read_text(encoding="utf-8"))
    assert observation == {
        "directory_is_symlink": False,
        "directory_mode": 0o700,
        "directory_owned": True,
        "file_is_symlink": False,
        "file_mode": 0o600,
        "file_owned": True,
        "payload_hex": b"one-off-stdin-sentinel\nsecond-line\n".hex(),
        "stdin_mode": 0o600,
        "stdin_owned": True,
    }
    assert "one-off-stdin-sentinel" not in completed.stdout + completed.stderr
    assert "one-off-stdin-sentinel" not in docker_log
    assert "npcink-release-proof-stdin" not in docker_log
    assert list((tmp_path / "one-off-tmp").glob("npcink-release-proof-stdin.*")) == []


def test_one_off_image_proof_rejects_previously_started_candidate(tmp_path: Path) -> None:
    completed, docker_log = _run_one_off_image_proof(
        tmp_path,
        actual_image_id=f"sha256:{'a' * 64}",
        candidate_state="exited 0",
    )

    assert completed.returncode == 1
    assert "start proof-api-container" not in docker_log
    assert "exec -i proof-api-container" not in docker_log
    assert "payload was blocked" in completed.stderr


def test_one_off_image_proof_rejects_ambiguous_candidate_set(tmp_path: Path) -> None:
    completed, docker_log = _run_one_off_image_proof(
        tmp_path,
        actual_image_id=f"sha256:{'a' * 64}",
        candidate_ids="proof-api-container\nunexpected-proof-container",
    )

    assert completed.returncode == 1
    assert "start proof-api-container" not in docker_log
    assert "exec -i" not in docker_log


def test_one_off_image_proof_rejects_concurrent_global_lock(tmp_path: Path) -> None:
    completed, docker_log = _run_one_off_image_proof(
        tmp_path,
        actual_image_id=f"sha256:{'a' * 64}",
        preexisting_lock=True,
    )

    assert completed.returncode == 1
    assert "Another governed release one-off is already active" in completed.stderr
    assert " up --no-start " not in docker_log


def test_one_off_image_proof_rejects_unowned_deploy_lock_and_releases_own_lock(
    tmp_path: Path,
) -> None:
    completed, docker_log = _run_one_off_image_proof(
        tmp_path,
        actual_image_id=f"sha256:{'a' * 64}",
        deploy_lock_owner="a" * 64,
    )

    assert completed.returncode != 0
    assert "blocked by an unowned deployment lock" in completed.stderr
    assert " up --no-start " not in docker_log
    assert not (tmp_path / ".release-state" / ".release-one-off.lock").exists()


def test_one_off_image_proof_allows_matching_deploy_lock_owner(
    tmp_path: Path,
) -> None:
    owner = "b" * 64
    completed, docker_log = _run_one_off_image_proof(
        tmp_path,
        actual_image_id=f"sha256:{'a' * 64}",
        deploy_lock_owner=owner,
        configured_deploy_lock_owner=owner,
    )

    assert completed.returncode == 0, completed.stderr
    assert " up --no-start " in docker_log
    assert not (tmp_path / ".release-state" / ".release-one-off.lock").exists()


def test_one_off_image_proof_rejects_orphan_container_and_retains_recovery_lock(
    tmp_path: Path,
) -> None:
    completed, docker_log = _run_one_off_image_proof(
        tmp_path,
        actual_image_id=f"sha256:{'a' * 64}",
        preexisting_container=True,
    )

    assert completed.returncode != 0
    assert "pre-existing governed one-off container" in completed.stderr
    assert " up --no-start " not in docker_log
    assert (tmp_path / ".release-state" / ".release-one-off.lock").is_dir()


def test_one_off_image_proof_retains_lock_when_label_cleanup_query_fails(
    tmp_path: Path,
) -> None:
    completed, docker_log = _run_one_off_image_proof(
        tmp_path,
        actual_image_id=f"sha256:{'a' * 64}",
        cleanup_query_failure=True,
    )

    assert completed.returncode != 0
    assert "cleanup was incomplete" in completed.stderr
    assert "container ls -aq --no-trunc" in docker_log
    assert (tmp_path / ".release-state" / ".release-one-off.lock").is_dir()


def test_one_off_image_proof_rejects_mismatch_and_still_cleans(
    tmp_path: Path,
) -> None:
    expected_daemon_image_id = f"sha256:{'b' * 64}"
    completed, docker_log = _run_one_off_image_proof(
        tmp_path,
        actual_image_id=f"sha256:{'c' * 64}",
        expected_daemon_image_id=expected_daemon_image_id,
    )

    assert completed.returncode == 1
    assert "payload was blocked" in completed.stderr
    assert "up --no-start --pull never" in docker_log
    assert "start proof-api-container" not in docker_log
    assert "exec -i proof-api-container" not in docker_log
    assert "rm -f proof-api-container" in docker_log
    assert not (tmp_path / "stdin-observation.json").exists()
    assert list((tmp_path / "one-off-tmp").glob("npcink-release-proof-stdin.*")) == []


def test_one_off_image_proof_blocks_tag_that_drifted_before_container_creation(
    tmp_path: Path,
) -> None:
    expected_daemon_image_id = f"sha256:{'b' * 64}"
    drifted = f"sha256:{'c' * 64}"
    completed, docker_log = _run_one_off_image_proof(
        tmp_path,
        actual_image_id=drifted,
        expected_daemon_image_id=expected_daemon_image_id,
        tag_image_id=drifted,
    )

    assert completed.returncode == 1
    assert "tag drifted from the bundle manifest" in completed.stderr
    assert " config --format json release-one-off" in docker_log
    assert " up --no-start " not in docker_log
    assert "exec -i" not in docker_log
    assert not (tmp_path / "stdin-observation.json").exists()
    assert list((tmp_path / "one-off-tmp").glob("npcink-release-proof-stdin.*")) == []


def test_one_off_image_proof_preserves_command_failure_and_cleans(
    tmp_path: Path,
) -> None:
    completed, docker_log = _run_one_off_image_proof(
        tmp_path,
        actual_image_id=f"sha256:{'a' * 64}",
        run_status=73,
    )

    assert completed.returncode == 73
    assert "command failed" in completed.stderr
    assert "rm -f proof-api-container" in docker_log
    observation = json.loads((tmp_path / "stdin-observation.json").read_text(encoding="utf-8"))
    assert observation["directory_mode"] == 0o700
    assert observation["file_mode"] == 0o600
    assert observation["stdin_mode"] == 0o600
    assert bytes.fromhex(observation["payload_hex"]) == (b"one-off-stdin-sentinel\nsecond-line\n")
    assert list((tmp_path / "one-off-tmp").glob("npcink-release-proof-stdin.*")) == []


def test_one_off_image_proof_fails_when_cleanup_fails(tmp_path: Path) -> None:
    completed, _docker_log = _run_one_off_image_proof(
        tmp_path,
        actual_image_id=f"sha256:{'a' * 64}",
        cleanup_status=74,
    )

    assert completed.returncode == 1
    assert "cleanup was incomplete" in completed.stderr
    assert (tmp_path / ".release-state" / ".release-one-off.lock").is_dir()
    assert list((tmp_path / "one-off-tmp").glob("npcink-release-proof-stdin.*")) == []


def test_one_off_image_proof_removes_container_when_interrupted(tmp_path: Path) -> None:
    completed, docker_log = _run_one_off_image_proof(
        tmp_path,
        actual_image_id=f"sha256:{'a' * 64}",
        terminate_during_payload=True,
    )

    assert completed.returncode == 143
    assert "exec -i proof-api-container" in docker_log
    assert "rm -f proof-api-container" in docker_log
    observation = json.loads((tmp_path / "stdin-observation.json").read_text(encoding="utf-8"))
    assert observation["directory_mode"] == 0o700
    assert observation["file_mode"] == 0o600
    assert observation["stdin_mode"] == 0o600
    assert bytes.fromhex(observation["payload_hex"]) == (b"one-off-stdin-sentinel\nsecond-line\n")
    assert list((tmp_path / "one-off-tmp").glob("npcink-release-proof-stdin.*")) == []


def test_one_off_image_proof_removes_stdin_when_capture_is_interrupted(
    tmp_path: Path,
) -> None:
    completed, docker_log = _run_one_off_image_proof(
        tmp_path,
        actual_image_id=f"sha256:{'a' * 64}",
        terminate_during_stdin_capture=True,
    )

    assert completed.returncode == 143
    assert " config --format json release-one-off" in docker_log
    assert " up --no-start " not in docker_log
    assert "one-off-stdin-sentinel" not in completed.stdout + completed.stderr
    assert not (tmp_path / "stdin-observation.json").exists()
    assert list((tmp_path / "one-off-tmp").glob("npcink-release-proof-stdin.*")) == []
