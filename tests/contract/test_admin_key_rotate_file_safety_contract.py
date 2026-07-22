from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ROTATE_SCRIPT = ROOT / "deploy" / "admin-key-rotate.sh"
PYTHON_START = 'ADMIN_KEY="$("${RELEASE_TOOL_PYTHON}" - "${CONFIG_DIR}" <<\'PY\'\n'
PYTHON_END = '\nPY\n)"\n'
EXECUTION_MARKER = "config_dir = Path(sys.argv[1])\n"


def _rotation_program() -> str:
    source = ROTATE_SCRIPT.read_text(encoding="utf-8")
    assert source.count(PYTHON_START) == 1
    remainder = source.split(PYTHON_START, 1)[1]
    assert remainder.count(PYTHON_END) == 1
    return remainder.split(PYTHON_END, 1)[0]


def _portable_rotation_program(
    *,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
) -> str:
    program = _rotation_program()
    uid = os.geteuid() if expected_uid is None else expected_uid
    gid = os.getegid() if expected_gid is None else expected_gid
    replacements = {
        "CONFIG_FILE_UID = 999": f"CONFIG_FILE_UID = {uid}",
        "CONFIG_FILE_GID = 999": f"CONFIG_FILE_GID = {gid}",
    }
    for production_value, portable_value in replacements.items():
        assert program.count(production_value) == 1
        program = program.replace(production_value, portable_value, 1)
    return program


def _inject_before_execution(program: str, source: str) -> str:
    assert program.count(EXECUTION_MARKER) == 1
    return program.replace(EXECUTION_MARKER, source + "\n\n" + EXECUTION_MARKER, 1)


def _canonical_bytes(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _complete_config(config_dir: Path) -> tuple[Path, Path, bytes, str]:
    config_dir.mkdir(mode=0o700)
    old_session_secret = "old-admin-session-secret-that-must-not-leak"
    runtime_payload: dict[str, object] = {
        "config_version": "runtime-config-v1",
        "security": {
            "admin_key_sha256": "a" * 64,
            "admin_session_secret": old_session_secret,
        },
    }
    runtime_bytes = _canonical_bytes(runtime_payload)
    runtime_path = config_dir / "runtime-config.json"
    runtime_path.write_bytes(runtime_bytes)
    runtime_path.chmod(0o600)

    state_payload: dict[str, object] = {
        "config_digest": hashlib.sha256(runtime_bytes).hexdigest(),
        "database_contract": "pg18_empty_initialization.v1",
        "installation_state": "complete",
        "updated_at": "2026-07-22T00:00:00Z",
    }
    state_path = config_dir / "install-state.json"
    state_path.write_bytes(_canonical_bytes(state_payload))
    state_path.chmod(0o640)
    return runtime_path, state_path, runtime_bytes, old_session_secret


def _run_rotation_program(
    program: str,
    config_dir: Path,
    *,
    timeout: float = 5,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-", str(config_dir)],
        input=program,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _assert_failed_without_plaintext(
    completed: subprocess.CompletedProcess[str],
    *,
    forbidden: str = "",
) -> None:
    assert completed.returncode != 0
    combined = completed.stdout + completed.stderr
    assert "nca_admin_" not in combined
    if forbidden:
        assert forbidden not in combined


def test_admin_key_rotation_reads_and_rotates_the_same_protected_runtime_bytes(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    runtime_path, state_path, old_runtime_bytes, old_session_secret = _complete_config(
        config_dir
    )

    completed = _run_rotation_program(_portable_rotation_program(), config_dir)

    assert completed.returncode == 0, completed.stderr
    admin_key = completed.stdout.strip()
    assert admin_key.startswith("nca_admin_")
    assert "\n" not in admin_key
    assert old_session_secret not in completed.stdout + completed.stderr

    runtime_bytes = runtime_path.read_bytes()
    runtime = json.loads(runtime_bytes)
    state = json.loads(state_path.read_bytes())
    security = runtime["security"]
    assert isinstance(security, dict)
    assert security["admin_key_sha256"] == hashlib.sha256(admin_key.encode()).hexdigest()
    assert security["admin_session_secret"] != old_session_secret
    assert runtime_bytes != old_runtime_bytes
    assert state["config_digest"] == hashlib.sha256(runtime_bytes).hexdigest()
    assert "config_transition" not in state
    assert "previous_config_digest" not in state
    assert runtime_path.stat().st_mode & 0o777 == 0o600
    assert state_path.stat().st_mode & 0o777 == 0o640


def test_admin_key_rotation_rejects_runtime_symlink_without_disclosing_plaintext(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    runtime_path, state_path, _runtime_bytes, old_session_secret = _complete_config(config_dir)
    original_state = state_path.read_bytes()
    target = config_dir / "runtime-target.json"
    runtime_path.replace(target)
    runtime_path.symlink_to(target.name)

    completed = _run_rotation_program(_portable_rotation_program(), config_dir)

    _assert_failed_without_plaintext(completed, forbidden=old_session_secret)
    assert runtime_path.is_symlink()
    assert state_path.read_bytes() == original_state


def test_admin_key_rotation_fifo_swap_fails_without_blocking_or_disclosing_plaintext(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    runtime_path, state_path, _runtime_bytes, old_session_secret = _complete_config(config_dir)
    original_state = state_path.read_bytes()
    hook = """
original_open = os.open
runtime_open_swapped = False

def open_with_fifo_swap(path, flags, *args, **kwargs):
    global runtime_open_swapped
    candidate = Path(path)
    if not runtime_open_swapped and candidate.name == "runtime-config.json":
        runtime_open_swapped = True
        candidate.unlink()
        os.mkfifo(candidate, 0o600)
    return original_open(path, flags, *args, **kwargs)

os.open = open_with_fifo_swap
""".strip()
    program = _inject_before_execution(_portable_rotation_program(), hook)

    completed = _run_rotation_program(program, config_dir, timeout=3)

    _assert_failed_without_plaintext(completed, forbidden=old_session_secret)
    assert runtime_path.exists()
    assert state_path.read_bytes() == original_state


@pytest.mark.parametrize(
    ("expected_uid", "expected_gid"),
    (
        (os.geteuid() + 1, os.getegid()),
        (os.geteuid(), os.getegid() + 1),
    ),
)
def test_admin_key_rotation_rejects_unexpected_owner_portably(
    tmp_path: Path,
    expected_uid: int,
    expected_gid: int,
) -> None:
    config_dir = tmp_path / "config"
    _runtime_path, state_path, _runtime_bytes, old_session_secret = _complete_config(config_dir)
    original_state = state_path.read_bytes()

    completed = _run_rotation_program(
        _portable_rotation_program(expected_uid=expected_uid, expected_gid=expected_gid),
        config_dir,
    )

    _assert_failed_without_plaintext(completed, forbidden=old_session_secret)
    assert "ownership is unsafe" in completed.stderr
    assert state_path.read_bytes() == original_state


@pytest.mark.parametrize(
    ("file_name", "unsafe_mode"),
    (("runtime-config.json", 0o640), ("install-state.json", 0o600)),
)
def test_admin_key_rotation_rejects_wrong_protected_file_mode(
    tmp_path: Path,
    file_name: str,
    unsafe_mode: int,
) -> None:
    config_dir = tmp_path / "config"
    _runtime_path, state_path, _runtime_bytes, old_session_secret = _complete_config(config_dir)
    original_state = state_path.read_bytes()
    (config_dir / file_name).chmod(unsafe_mode)

    completed = _run_rotation_program(_portable_rotation_program(), config_dir)

    _assert_failed_without_plaintext(completed, forbidden=old_session_secret)
    assert "mode is unsafe" in completed.stderr
    assert state_path.read_bytes() == original_state


def test_admin_key_rotation_rejects_runtime_path_replacement_and_mixed_content(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    runtime_path, state_path, _runtime_bytes, old_session_secret = _complete_config(config_dir)
    original_state = state_path.read_bytes()
    replacement_payload: dict[str, object] = {
        "config_version": "runtime-config-v1",
        "security": {
            "admin_key_sha256": "b" * 64,
            "admin_session_secret": "replacement-content-must-not-be-blessed",
        },
    }
    replacement_bytes = _canonical_bytes(replacement_payload)
    hook = f"""
original_open = os.open
runtime_open_swapped = False
replacement_runtime_bytes = {replacement_bytes!r}

def open_with_runtime_replacement(path, flags, *args, **kwargs):
    global runtime_open_swapped
    candidate = Path(path)
    if not runtime_open_swapped and candidate.name == "runtime-config.json":
        runtime_open_swapped = True
        replacement = candidate.with_name(".runtime-config.replacement")
        replacement.write_bytes(replacement_runtime_bytes)
        replacement.chmod(0o600)
        os.replace(replacement, candidate)
    return original_open(path, flags, *args, **kwargs)

os.open = open_with_runtime_replacement
""".strip()
    program = _inject_before_execution(_portable_rotation_program(), hook)

    completed = _run_rotation_program(program, config_dir)

    _assert_failed_without_plaintext(completed, forbidden=old_session_secret)
    assert "changed while it was opened" in completed.stderr
    assert runtime_path.read_bytes() == replacement_bytes
    assert state_path.read_bytes() == original_state


def test_admin_key_rotation_failure_after_key_generation_never_discloses_plaintext(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    runtime_path, state_path, old_runtime_bytes, old_session_secret = _complete_config(
        config_dir
    )
    hook = """
original_replace = os.replace

def replace_with_runtime_publish_failure(source, destination):
    if Path(destination).name == "runtime-config.json":
        raise OSError("injected runtime publish failure")
    return original_replace(source, destination)

os.replace = replace_with_runtime_publish_failure
""".strip()
    program = _inject_before_execution(_portable_rotation_program(), hook)

    completed = _run_rotation_program(program, config_dir)

    _assert_failed_without_plaintext(completed, forbidden=old_session_secret)
    assert runtime_path.read_bytes() == old_runtime_bytes
    transition_state = json.loads(state_path.read_bytes())
    assert transition_state["config_transition"] == "admin_key_rotation.v1"
    assert transition_state["previous_config_digest"] == hashlib.sha256(
        old_runtime_bytes
    ).hexdigest()


def test_admin_key_rotation_keeps_api_fail_closed_fence_and_one_time_disclosure() -> None:
    shell_source = ROTATE_SCRIPT.read_text(encoding="utf-8")
    program = _rotation_program()
    stop = 'npcink_ai_cloud_compose "${ROOT_DIR}" stop -t 30 api'
    mutation = 'ADMIN_KEY="$("${RELEASE_TOOL_PYTHON}"'
    start = 'npcink_ai_cloud_compose "${ROOT_DIR}" start api'
    ready = "npcink_ai_cloud_wait_for_internal_endpoint"
    disclose = 'printf \'%s\\n\' "${ADMIN_KEY}"'

    fence = shell_source.index("API_FENCE_ACTIVE=1")
    main_stop = shell_source.index(stop, fence)
    assert main_stop < shell_source.index(mutation) < shell_source.index(start)
    assert shell_source.index(start) < shell_source.index(ready) < shell_source.index(disclose)
    assert shell_source.index(disclose) < shell_source.index("API_FENCE_ACTIVE=0", fence)
    cleanup = shell_source.split("cleanup() {", 1)[1].split("trap cleanup EXIT", 1)[0]
    assert stop in cleanup
    assert 'if [ "${API_FENCE_ACTIVE}" = "1" ]; then' in cleanup

    assert 'getattr(os, "O_NOFOLLOW", 0)' in program
    assert 'getattr(os, "O_NONBLOCK", 0)' in program
    assert "runtime_path.read_bytes()" not in program
    assert "runtime, runtime_bytes = load_protected_object(" in program
    assert "descriptor_metadata_before = os.fstat(descriptor)" in program
    assert "descriptor_metadata_after = os.fstat(descriptor)" in program
    assert "path_metadata_after = os.lstat(path)" in program
