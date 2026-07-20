from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, text: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(0o755)


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

    ssh = r'''#!/usr/bin/env bash
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
'''
    scp = r'''#!/usr/bin/env bash
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
'''
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
    prepare_index = next(
        index for index, line in enumerate(ssh_lines) if "mkdir -p" in line
    )
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
    final_entry = next(
        line for line in ssh_log.splitlines() if "bash\t-s\t--\tstage-only" in line
    )
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


def test_upload_failure_attempts_remote_incoming_cleanup(tmp_path: Path) -> None:
    completed, ssh_log, scp_log = _run_stage_only(
        tmp_path,
        fail_scp_substring="deploy-bundle.tgz",
    )

    assert completed.returncode == 73
    assert "deploy-bundle.tgz" in scp_log
    ssh_lines = ssh_log.splitlines()
    prepare_index = next(
        index for index, line in enumerate(ssh_lines) if "mkdir -p" in line
    )
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
        r'''#!/usr/bin/env bash
set -euo pipefail
case "${2:-}" in
    *"(3, 9)"*) exit 0 ;;
    *"(3, 11)"*) exit 1 ;;
    *) exit 64 ;;
esac
''',
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
    runtime_compose = (ROOT / "docker-compose.runtime.yml").read_text(
        encoding="utf-8"
    )
    service_names = (
        "postgres",
        "redis",
        "api",
        "frontend",
        "worker",
        "callback-worker",
        "ops-worker",
        "proxy",
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
    refresh = (ROOT / "deploy/remote-refresh-providers.sh").read_text(
        encoding="utf-8"
    )
    loader = (ROOT / "deploy/remote-load-and-up.sh").read_text(encoding="utf-8")
    assert "run --rm --no-deps --pull never" not in migrate
    assert "run --rm --no-deps --pull never" not in refresh
    assert "npcink_ai_cloud_compose_run_with_image_proof" in migrate
    assert "npcink_ai_cloud_compose_run_with_image_proof" in refresh
    assert "up -d --pull never --no-build" in migrate
    assert "up -d --pull never --no-build" in loader
    assert "--no-deps --force-recreate" in loader
    assert "npcink-ai-cloud-postgres:prod" in loader
    assert "npcink-ai-cloud-external-redis:prod" in loader
    assert "{{.Image}}" in loader
    assert "true false 0 healthy" in loader


def _run_one_off_image_proof(
    tmp_path: Path,
    *,
    actual_image_id: str,
    run_status: int = 0,
    cleanup_status: int = 0,
    tag_image_id: str | None = None,
    terminate_during_payload: bool = False,
    terminate_during_stdin_capture: bool = False,
    stdin_payload: str = "one-off-stdin-sentinel\nsecond-line\n",
) -> tuple[subprocess.CompletedProcess[str], str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_path = tmp_path / "docker.log"
    stdin_observation_path = tmp_path / "stdin-observation.json"
    stdin_tmp_dir = tmp_path / "one-off-tmp"
    stdin_tmp_dir.mkdir()
    expected_image_id = f"sha256:{'a' * 64}"
    tag_image_id = tag_image_id or expected_image_id
    _write(
        fake_bin / "docker",
        r'''#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${DOCKER_LOG}"
case "${1:-} ${2:-}" in
    "image inspect")
        printf '%s\n' "${EXPECTED_IMAGE_ID}"
        ;;
    "compose --env-file"|"compose -f")
        exit 0
        ;;
    "inspect --format")
        printf '%s\n' "${ACTUAL_IMAGE_ID}"
        ;;
    "exec -i")
        python3 -c '
import json
import os
import stat
import sys
from pathlib import Path

payload = sys.stdin.buffer.read()
temporary_root = Path(os.environ["TMPDIR"])
protected_directories = list(temporary_root.iterdir())
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
        exit "${CLEANUP_STATUS}"
        ;;
    *)
        exit 64
        ;;
esac
''',
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
            "EXPECTED_IMAGE_ID": tag_image_id,
            "ACTUAL_IMAGE_ID": actual_image_id,
            "RUN_STATUS": str(run_status),
            "CLEANUP_STATUS": str(cleanup_status),
            "RUN_SLEEP_SECONDS": "30" if terminate_during_payload else "0",
            "NPCINK_CLOUD_ENV_FILE": str(env_file),
            "NPCINK_CLOUD_COMPOSE_FILE": str(tmp_path / "runtime.yml"),
            "TMPDIR": str(stdin_tmp_dir),
        }
    )
    shell = (
        "set -euo pipefail; "
        f". {ROOT / 'deploy/common.sh'}; "
        f"npcink_ai_cloud_compose_run_with_image_proof {tmp_path} api "
        f"npcink-ai-cloud-api:prod {expected_image_id} python -c 'print(1)'"
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
            protected_files = list(
                stdin_tmp_dir.glob("npcink-release-proof-stdin.*/payload.stdin")
            )
            if (
                len(protected_files) == 1
                and protected_files[0].stat().st_size == expected_size
            ):
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
            docker_log = (
                log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            )
            observation_ready = False
            if stdin_observation_path.exists():
                try:
                    observation = json.loads(
                        stdin_observation_path.read_text(encoding="utf-8")
                    )
                    observation_ready = bytes.fromhex(
                        observation["payload_hex"]
                    ) == stdin_payload.encode()
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
    exact_image_id = f"sha256:{'a' * 64}"
    completed, docker_log = _run_one_off_image_proof(
        tmp_path,
        actual_image_id=exact_image_id,
    )

    assert completed.returncode == 0, completed.stderr
    assert "run -d --name npcink-release-proof-api-" in docker_log
    assert " --no-deps --rm --entrypoint python api -c import time; time.sleep(900)" in docker_log
    assert "exec -i npcink-release-proof-api-" in docker_log
    assert " python -c print(1)" in docker_log
    assert "--pull" not in docker_log
    assert "inspect --format {{.Image}}" in docker_log
    assert "rm -f npcink-release-proof-api-" in docker_log
    observation = json.loads(
        (tmp_path / "stdin-observation.json").read_text(encoding="utf-8")
    )
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
    assert list((tmp_path / "one-off-tmp").iterdir()) == []


def test_one_off_image_proof_rejects_mismatch_and_still_cleans(
    tmp_path: Path,
) -> None:
    completed, docker_log = _run_one_off_image_proof(
        tmp_path,
        actual_image_id=f"sha256:{'b' * 64}",
    )

    assert completed.returncode == 1
    assert "payload was blocked" in completed.stderr
    assert "exec -i npcink-release-proof-api-" not in docker_log
    assert "rm -f npcink-release-proof-api-" in docker_log
    assert not (tmp_path / "stdin-observation.json").exists()
    assert list((tmp_path / "one-off-tmp").iterdir()) == []


def test_one_off_image_proof_blocks_tag_that_drifted_before_container_creation(
    tmp_path: Path,
) -> None:
    drifted = f"sha256:{'b' * 64}"
    completed, docker_log = _run_one_off_image_proof(
        tmp_path,
        actual_image_id=drifted,
        tag_image_id=drifted,
    )

    assert completed.returncode == 1
    assert "tag drifted from the bundle manifest" in completed.stderr
    assert "compose " not in docker_log
    assert "exec -i" not in docker_log
    assert not (tmp_path / "stdin-observation.json").exists()
    assert list((tmp_path / "one-off-tmp").iterdir()) == []


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
    assert "rm -f npcink-release-proof-api-" in docker_log
    observation = json.loads(
        (tmp_path / "stdin-observation.json").read_text(encoding="utf-8")
    )
    assert observation["directory_mode"] == 0o700
    assert observation["file_mode"] == 0o600
    assert observation["stdin_mode"] == 0o600
    assert bytes.fromhex(observation["payload_hex"]) == (
        b"one-off-stdin-sentinel\nsecond-line\n"
    )
    assert list((tmp_path / "one-off-tmp").iterdir()) == []


def test_one_off_image_proof_fails_when_cleanup_fails(tmp_path: Path) -> None:
    completed, _docker_log = _run_one_off_image_proof(
        tmp_path,
        actual_image_id=f"sha256:{'a' * 64}",
        cleanup_status=74,
    )

    assert completed.returncode == 1
    assert "proof container could not be removed" in completed.stderr
    assert list((tmp_path / "one-off-tmp").iterdir()) == []


def test_one_off_image_proof_removes_container_when_interrupted(tmp_path: Path) -> None:
    completed, docker_log = _run_one_off_image_proof(
        tmp_path,
        actual_image_id=f"sha256:{'a' * 64}",
        terminate_during_payload=True,
    )

    assert completed.returncode == 143
    assert "exec -i npcink-release-proof-api-" in docker_log
    assert "rm -f npcink-release-proof-api-" in docker_log
    observation = json.loads(
        (tmp_path / "stdin-observation.json").read_text(encoding="utf-8")
    )
    assert observation["directory_mode"] == 0o700
    assert observation["file_mode"] == 0o600
    assert observation["stdin_mode"] == 0o600
    assert bytes.fromhex(observation["payload_hex"]) == (
        b"one-off-stdin-sentinel\nsecond-line\n"
    )
    assert list((tmp_path / "one-off-tmp").iterdir()) == []


def test_one_off_image_proof_removes_stdin_when_capture_is_interrupted(
    tmp_path: Path,
) -> None:
    completed, docker_log = _run_one_off_image_proof(
        tmp_path,
        actual_image_id=f"sha256:{'a' * 64}",
        terminate_during_stdin_capture=True,
    )

    assert completed.returncode == 143
    assert docker_log == ""
    assert "one-off-stdin-sentinel" not in completed.stdout + completed.stderr
    assert not (tmp_path / "stdin-observation.json").exists()
    assert list((tmp_path / "one-off-tmp").iterdir()) == []
