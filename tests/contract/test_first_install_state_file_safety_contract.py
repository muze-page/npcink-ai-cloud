from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "deploy" / "validate-installation-complete.py"
ROLLBACK = ROOT / "deploy" / "first-install-rollback.sh"


def _load_validator(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, text: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)


def _write_json(path: Path, payload: dict[str, object], *, mode: int) -> bytes:
    raw = (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)
    return raw


def test_protected_json_happy_path_is_bound_to_the_open_descriptor(
    tmp_path: Path,
) -> None:
    module = _load_validator("installation_validator_happy")
    path = tmp_path / "install-state.json"
    expected = {"installation_state": "pending", "attempt_id": "attempt-1"}
    raw = _write_json(path, expected, mode=0o640)

    payload, observed_raw = module._load_protected_json(  # noqa: SLF001
        path,
        label="install-state.json",
        uid=os.getuid(),
        gid=os.getgid(),
        mode=0o640,
    )

    assert payload == expected
    assert observed_raw == raw


def test_protected_json_rejects_symlink(tmp_path: Path) -> None:
    module = _load_validator("installation_validator_symlink")
    target = tmp_path / "target.json"
    _write_json(target, {"installation_state": "pending"}, mode=0o640)
    link = tmp_path / "install-state.json"
    link.symlink_to(target)

    with pytest.raises((OSError, ValueError)):
        module._load_protected_json(  # noqa: SLF001
            link,
            label="install-state.json",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o640,
        )


def test_protected_json_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "install-state.json"
    os.mkfifo(fifo, 0o640)
    probe = f"""
import importlib.util
import os
from pathlib import Path

spec = importlib.util.spec_from_file_location("fifo_validator", {str(VALIDATOR)!r})
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
try:
    module._load_protected_json(
        Path({str(fifo)!r}),
        label="install-state.json",
        uid=os.getuid(),
        gid=os.getgid(),
        mode=0o640,
    )
except (OSError, ValueError) as exc:
    print(exc)
    raise SystemExit(17)
raise SystemExit(0)
"""

    result = subprocess.run(
        [sys.executable, "-c", probe],
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )

    assert result.returncode == 17
    assert "regular non-symlink file" in result.stdout


def test_validator_cli_accepts_bound_runtime_and_enforces_expected_release(
    tmp_path: Path,
) -> None:
    managed = tmp_path / "managed"
    release = managed / "release-candidate"
    release.mkdir(parents=True)
    runtime = managed / "runtime-config.json"
    runtime_raw = _write_json(
        runtime,
        {"database": {"host": "private.example", "port": 5432}},
        mode=0o600,
    )
    digest = hashlib.sha256(runtime_raw).hexdigest()
    state = managed / "install-state.json"
    _write_json(
        state,
        {
            "config_digest": digest,
            "database_contract": "pg18_empty_initialization.v1",
            "installation_state": "complete",
        },
        mode=0o640,
    )
    sentinel = managed / ".installation-complete"
    _write_json(
        sentinel,
        {
            "accepted_at": "2026-01-01T00:00:00Z",
            "config_digest": digest,
            "contract": "installation_complete.v1",
            "release": str(release),
        },
        mode=0o600,
    )
    portable_validator = VALIDATOR.read_text(encoding="utf-8")
    portable_validator = portable_validator.replace(
        "uid=0,\n        gid=0,",
        f"uid={os.getuid()},\n        gid={os.getgid()},",
    ).replace(
        "uid=999,\n        gid=999,",
        f"uid={os.getuid()},\n        gid={os.getgid()},",
    )
    validator = tmp_path / "validate-installation-complete.py"
    _write(validator, portable_validator, mode=0o755)
    command = [
        sys.executable,
        str(validator),
        "--managed-root",
        str(managed),
        "--sentinel",
        str(sentinel),
        "--state",
        str(state),
        "--runtime",
        str(runtime),
        "--expected-release",
        str(release),
    ]

    accepted = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )
    rejected = subprocess.run(
        [*command[:-1], str(managed / "release-other")],
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )

    assert accepted.returncode == 0, accepted.stderr
    assert accepted.stdout.strip() == "installation_complete_valid.v1"
    assert rejected.returncode != 0
    assert "does not match expected release" in rejected.stderr


def test_protected_json_rejects_wrong_mode_and_owner_portably(
    tmp_path: Path,
) -> None:
    module = _load_validator("installation_validator_metadata")
    path = tmp_path / "install-state.json"
    _write_json(path, {"installation_state": "pending"}, mode=0o644)

    with pytest.raises(ValueError, match="mode is unsafe"):
        module._load_protected_json(  # noqa: SLF001
            path,
            label="install-state.json",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o640,
        )

    path.chmod(0o640)
    with pytest.raises(ValueError, match="ownership is unsafe"):
        module._load_protected_json(  # noqa: SLF001
            path,
            label="install-state.json",
            uid=os.getuid() + 1,
            gid=os.getgid(),
            mode=0o640,
        )


def test_protected_json_rejects_path_replacement_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_validator("installation_validator_replace")
    path = tmp_path / "install-state.json"
    held = tmp_path / "opened-install-state.json"
    _write_json(path, {"installation_state": "pending"}, mode=0o640)
    original_read = module.os.read
    replaced = False

    def replace_path_then_read(descriptor: int, size: int) -> bytes:
        nonlocal replaced
        if not replaced:
            replaced = True
            path.replace(held)
            _write_json(path, {"installation_state": "complete"}, mode=0o640)
        return original_read(descriptor, size)

    monkeypatch.setattr(module.os, "read", replace_path_then_read)
    with pytest.raises(ValueError, match="changed while it was opened"):
        module._load_protected_json(  # noqa: SLF001
            path,
            label="install-state.json",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o640,
        )


def test_protected_json_revalidates_mode_after_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_validator("installation_validator_post_mode")
    path = tmp_path / "runtime-config.json"
    _write_json(path, {"database": {"host": "private.example"}}, mode=0o600)
    original_read = module.os.read
    changed = False

    def change_mode_then_read(descriptor: int, size: int) -> bytes:
        nonlocal changed
        if not changed:
            changed = True
            path.chmod(0o644)
        return original_read(descriptor, size)

    monkeypatch.setattr(module.os, "read", change_mode_then_read)
    with pytest.raises(ValueError, match="mode is unsafe"):
        module._load_protected_json(  # noqa: SLF001
            path,
            label="runtime-config.json",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o600,
        )


def _fake_command(path: Path, body: str) -> None:
    _write(path, "#!/usr/bin/env bash\nset -euo pipefail\n" + body, mode=0o755)


def _rollback_fixture(
    tmp_path: Path, *, portable_ownership: bool
) -> tuple[Path, Path, Path, Path, dict[str, str]]:
    managed = tmp_path / "managed"
    release = managed / "release-candidate"
    previous = managed / "release-previous"
    config = managed / "shared" / "config"
    fake_bin = tmp_path / "bin"
    for directory in (release / "deploy", previous / "deploy", config, fake_bin):
        directory.mkdir(parents=True, exist_ok=True)
    (managed / "current").symlink_to(release)

    rollback_source = ROLLBACK.read_text(encoding="utf-8")
    if portable_ownership:
        rollback_source = rollback_source.replace("uid=0,", f"uid={os.getuid()},")
        rollback_source = rollback_source.replace("gid=0,", f"gid={os.getgid()},")
        rollback_source = rollback_source.replace("uid=999,", f"uid={os.getuid()},")
        rollback_source = rollback_source.replace("gid=999,", f"gid={os.getgid()},")
    _write(release / "deploy" / "first-install-rollback.sh", rollback_source, mode=0o755)
    shutil.copy2(VALIDATOR, release / "deploy" / VALIDATOR.name)
    shutil.copy2(ROOT / "deploy" / "install-lock.py", release / "deploy/install-lock.py")

    common = """
npcink_ai_cloud_require_host_release_tool_python() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
}
npcink_ai_cloud_managed_root_for_release() { cd "$1/.." && pwd -P; }
npcink_ai_cloud_require_cmd() { command -v "$1" >/dev/null; }
npcink_ai_cloud_start_install_lock_broker() { return 0; }
npcink_ai_cloud_stop_install_lock_broker() { return 0; }
npcink_ai_cloud_compose() { shift; docker compose "$@"; }
npcink_ai_cloud_read_env_value() { awk -F= -v key="$2" '$1 == key { print $2 }' "$1"; }
npcink_ai_cloud_wait_for_ready() { curl "${1%/}/health/live" >/dev/null 2>&1; }
"""
    _write(release / "deploy/common.sh", common)
    _write(previous / "deploy/common.sh", common)
    _write(previous / "docker-compose.runtime.yml", "services: {}\n", mode=0o644)
    previous_env = previous / "env.deploy"
    _write(previous_env, "NPCINK_CLOUD_BASE_URL=http://127.0.0.1:8010\n", mode=0o600)
    rollback_map = managed / ".first-install-rollback-images.tsv"
    image_id = "sha256:" + "1" * 64
    _write(
        rollback_map,
        f"npcink-ai-cloud-api:prod\tnpcink-ai-cloud-rollback:test\t{image_id}\n",
    )
    pending = managed / ".first-install-pending.json"
    _write_json(
        pending,
        {
            "contract": "first_install_pending.v1",
            "previous_compose_file": str(previous / "docker-compose.runtime.yml"),
            "previous_compose_project": "npcink-ai-cloud",
            "previous_env_file": str(previous_env),
            "previous_release": str(previous),
            "release": str(release),
            "rollback_image_map": str(rollback_map),
        },
        mode=0o600,
    )
    _write_json(
        config / "install-state.json",
        {"installation_state": "pending", "attempt_id": "attempt-1"},
        mode=0o640,
    )

    log = tmp_path / "docker.log"
    _fake_command(
        fake_bin / "id",
        'if [ "${1:-}" = "-u" ]; then printf "0\\n"; else exec /usr/bin/id "$@"; fi\n',
    )
    _fake_command(
        fake_bin / "docker",
        f"""printf '%s\\n' "$*" >>{str(log)!r}
if [ "${{1:-}}" = "image" ] && [ "${{2:-}}" = "inspect" ]; then
    printf '%s\\n' '{image_id}'
fi
exit 0
""",
    )
    _fake_command(
        fake_bin / "curl",
        '[ "${ROLLBACK_READY:-0}" = "1" ]\n',
    )
    _fake_command(fake_bin / "sleep", "exit 0\n")
    _fake_command(
        fake_bin / "mv",
        'if [ "${1:-}" = "-Tf" ]; then\n'
        '    /bin/rm -f -- "$3"\n'
        '    exec /bin/mv "$2" "$3"\n'
        "fi\n"
        'exec /bin/mv "$@"\n',
    )
    _fake_command(
        fake_bin / "readlink",
        f"""if [ "${{1:-}}" = "-f" ]; then
    exec {sys.executable!r} -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$2"
fi
exec /usr/bin/readlink "$@"
""",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "NPCINK_CLOUD_CONFIG_DIR_HOST": str(config),
            "NPCINK_CLOUD_RELEASE_TOOL_PYTHON": sys.executable,
            "PATH": f"{fake_bin}:{environment['PATH']}",
        }
    )
    return release, previous, pending, rollback_map, environment


def test_rollback_rejects_permanent_complete_sentinel_before_mutation(
    tmp_path: Path,
) -> None:
    release, _previous, pending, rollback_map, environment = _rollback_fixture(
        tmp_path, portable_ownership=False
    )
    complete = release.parent / ".installation-complete"
    _write(complete, "permanent acceptance\n")
    before_pending = pending.read_bytes()
    before_map = rollback_map.read_bytes()

    result = subprocess.run(
        ["bash", str(release / "deploy/first-install-rollback.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Permanent installation-complete acceptance forbids" in result.stderr
    assert pending.read_bytes() == before_pending
    assert rollback_map.read_bytes() == before_map
    assert not (release.parent / ".deploy-lock").exists()


@pytest.mark.parametrize("ready", [True, False])
def test_rollback_happy_path_and_failure_asset_retention(
    tmp_path: Path, ready: bool
) -> None:
    release, previous, pending, rollback_map, environment = _rollback_fixture(
        tmp_path, portable_ownership=True
    )
    environment["ROLLBACK_READY"] = "1" if ready else "0"

    result = subprocess.run(
        ["bash", str(release / "deploy/first-install-rollback.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=5,
    )

    current = release.parent / "current"
    if ready:
        assert result.returncode == 0, result.stderr
        assert current.resolve() == previous.resolve()
        assert not pending.exists()
        assert not rollback_map.exists()
    else:
        assert result.returncode != 0
        assert "rollback evidence are retained" in result.stderr
        assert current.resolve() == release.resolve()
        assert pending.exists()
        assert rollback_map.exists()


def test_finalize_and_rollback_use_fd_bound_loader_without_weakening_ids() -> None:
    finalize = (ROOT / "deploy/first-install-finalize.sh").read_text(encoding="utf-8")
    rollback = ROLLBACK.read_text(encoding="utf-8")
    validator = VALIDATOR.read_text(encoding="utf-8")

    assert finalize.count("load_protected_json(") >= 5
    assert rollback.count("load_protected_json(") == 2
    assert "read_text(" not in finalize
    assert "read_bytes(" not in finalize
    assert "read_text(" not in rollback
    assert "read_bytes(" not in rollback
    for source in (finalize, rollback, validator):
        assert "uid=999" in source
        assert "gid=999" in source
    assert 'getattr(os, "O_NOFOLLOW", 0)' in validator
    assert 'getattr(os, "O_NONBLOCK", 0)' in validator
    assert validator.count("validate_descriptor(descriptor)") == 2
