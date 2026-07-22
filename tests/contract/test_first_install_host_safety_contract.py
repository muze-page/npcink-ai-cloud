from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY_TO_SSH = ROOT / "deploy" / "deploy-to-ssh-host.sh"


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_install_lock_revalidates_path_after_flock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module(ROOT / "deploy" / "install-lock.py", "install_lock")
    lock_path = tmp_path / ".install.lock"
    lock_path.write_bytes(b"")
    lock_path.chmod(0o600)
    original_flock = module.fcntl.flock

    def replace_path_during_flock(descriptor: int, operation: int) -> None:
        original_flock(descriptor, operation)
        lock_path.unlink()
        lock_path.write_bytes(b"replacement")
        lock_path.chmod(0o600)

    monkeypatch.setattr(module.fcntl, "flock", replace_path_during_flock)
    with pytest.raises(RuntimeError, match="path changed while it was opened"):
        module._open_lock(  # noqa: SLF001 - focused security contract
            lock_path,
            create=False,
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o600,
        )


def test_install_lock_rejects_symlink(tmp_path: Path) -> None:
    module = _load_module(ROOT / "deploy" / "install-lock.py", "install_lock_symlink")
    target = tmp_path / "target"
    target.write_bytes(b"")
    target.chmod(0o600)
    link = tmp_path / ".install.lock"
    link.symlink_to(target)

    with pytest.raises(OSError):
        module._open_lock(  # noqa: SLF001 - focused security contract
            link,
            create=False,
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o600,
        )


def _bundle_with_allowlist(tmp_path: Path, entries: list[dict[str, str]]) -> Path:
    payload = json.dumps(
        {
            "schema_version": "npcink.production-image-cve-allowlist.v1",
            "entries": entries,
        },
        separators=(",", ":"),
    ).encode()
    bundle = tmp_path / "bundle.tgz"
    info = tarfile.TarInfo("deploy/image-lock/cve-allowlist.json")
    info.size = len(payload)
    with tarfile.open(bundle, mode="w:gz") as archive:
        archive.addfile(info, io.BytesIO(payload))
    return bundle


def _write_private_json(path: Path, payload: dict[str, object]) -> bytes:
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path.write_bytes(raw)
    path.chmod(0o600)
    return raw


def _controlled_acceptance_fixture(
    tmp_path: Path,
    module: ModuleType,
) -> tuple[Path, Path, Path, datetime]:
    generated_at = "2026-07-22T10:00:00Z"
    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    allowlist = {
        "schema_version": "npcink.production-image-cve-allowlist.v1",
        "entries": [
            {
                "image": "api",
                "vulnerability_id": finding["vulnerability_id"],
                "package": "python",
                "package_version": "3.14.6",
            }
            for finding in module.EXPECTED_FINDINGS
        ],
    }
    allowlist_raw = (json.dumps(allowlist, sort_keys=True, separators=(",", ":")) + "\n").encode()
    allowlist_sha256 = hashlib.sha256(allowlist_raw).hexdigest()
    api_receipt = {
        "contract_version": "npcink.production-image-scan-receipt.v1",
        "status": "passed",
        "scope": "release",
        "release_gate": True,
        "generated_at_utc": generated_at,
        "image_key": "api",
        "requested_reference": "npcink-ai-cloud-api:prod",
        "archive_reference": "npcink-ai-cloud-api:prod",
        "platform": "linux/amd64",
        "allowlist_sha256": allowlist_sha256,
        "blocking_finding_count": 3,
        "allowlisted_blocking_finding_count": 3,
        "unallowlisted_blocking_finding_count": 0,
        "allowlisted_blocking_findings": module.EXPECTED_FINDINGS,
        "unallowlisted_blocking_findings": [],
    }
    api_receipt_raw = (
        json.dumps(api_receipt, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    scan_index = {
        "contract_version": "npcink.production-image-scan-index.v1",
        "status": "passed",
        "scope": "release",
        "release_gate": True,
        "generated_at_utc": generated_at,
        "allowlist_sha256": allowlist_sha256,
        "release_platform": "linux/amd64",
        "images": [
            {
                "image_key": "api",
                "status": "passed",
                "platform": "linux/amd64",
                "archive_reference": "npcink-ai-cloud-api:prod",
                "blocking_finding_count": 3,
                "unallowlisted_blocking_finding_count": 0,
                "receipt_sha256": hashlib.sha256(api_receipt_raw).hexdigest(),
            }
        ],
    }
    scan_index_raw = (json.dumps(scan_index, sort_keys=True, separators=(",", ":")) + "\n").encode()
    manifest = {
        "source": {
            "revision": "a" * 40,
            "tree": "b" * 40,
        }
    }
    manifest_raw = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    members = {
        "deploy/image-lock/cve-allowlist.json": allowlist_raw,
        "release-bundle-manifest.json": manifest_raw,
        "release/image-scan/scan-index.json": scan_index_raw,
        "release/image-scan/api.receipt.json": api_receipt_raw,
    }
    bundle = tmp_path / "controlled-bundle.tgz"
    with tarfile.open(bundle, mode="w:gz") as archive:
        for name, raw in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
    acceptance = {
        "contract": module.ACCEPTANCE_CONTRACT,
        "status": "accepted_by_operator",
        "scope": "controlled_production_validation_only",
        "decision_document": module.DECISION_DOCUMENT,
        "source_revision": "a" * 40,
        "source_tree": "b" * 40,
        "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
        "scan_index_sha256": hashlib.sha256(scan_index_raw).hexdigest(),
        "api_scan_receipt_sha256": hashlib.sha256(api_receipt_raw).hexdigest(),
        "allowlist_sha256": allowlist_sha256,
        "scan_index_status": "passed",
        "api_scan_status": "passed",
        "image_platform": "linux/amd64",
        "api_image_reference": "npcink-ai-cloud-api:prod",
        "blocking_finding_count": 3,
        "allowlisted_blocking_finding_count": 3,
        "unallowlisted_blocking_finding_count": 0,
        "allowlisted_findings": module.EXPECTED_FINDINGS,
        "cisa_ssvc_exploitation": {cve: "none" for cve in sorted(module.BLOCKED)},
        "cisa_ssvc_checked_at_utc": "2026-07-22T11:00:00Z",
        "exception_expires_on": "2026-08-05",
        "ga_authorized": False,
        "authorized_by": "Muze",
        "authorized_at_utc": "2026-07-22T11:05:00Z",
    }
    acceptance_path = tmp_path / "controlled-risk-acceptance.json"
    acceptance_raw = _write_private_json(acceptance_path, acceptance)
    checksum_path = tmp_path / "controlled-risk-acceptance.sha256"
    checksum_path.write_text(hashlib.sha256(acceptance_raw).hexdigest() + "\n")
    checksum_path.chmod(0o600)
    return bundle, acceptance_path, checksum_path, now


def test_first_install_cve_gate_blocks_any_named_python_3146_exception(
    tmp_path: Path,
) -> None:
    module = _load_module(
        ROOT / "scripts" / "check-first-install-cve-gate.py", "first_install_cve_gate"
    )
    bundle = _bundle_with_allowlist(
        tmp_path,
        [
            {
                "vulnerability_id": "CVE-2026-11940",
                "package": "python",
                "package_version": "3.14.6",
            }
        ],
    )

    with pytest.raises(ValueError, match="first installation is blocked"):
        module.assert_first_install_allowed(module._read_allowlist(bundle))


def test_first_install_cve_gate_accepts_exact_bundle_after_exception_removal(
    tmp_path: Path,
) -> None:
    module = _load_module(
        ROOT / "scripts" / "check-first-install-cve-gate.py", "first_install_cve_gate_clear"
    )
    bundle = _bundle_with_allowlist(tmp_path, [])

    module.assert_first_install_allowed(module._read_allowlist(bundle))


def test_first_install_cve_gate_accepts_only_exact_fresh_operator_receipt(
    tmp_path: Path,
) -> None:
    module = _load_module(
        ROOT / "scripts" / "check-first-install-cve-gate.py",
        "first_install_cve_gate_controlled",
    )
    bundle, acceptance, checksum, now = _controlled_acceptance_fixture(tmp_path, module)

    module.assert_controlled_first_install_allowed(
        bundle=bundle,
        acceptance_path=acceptance,
        acceptance_checksum_path=checksum,
        now=now,
    )


def test_first_install_cve_gate_rejects_rebound_or_unprotected_operator_receipt(
    tmp_path: Path,
) -> None:
    module = _load_module(
        ROOT / "scripts" / "check-first-install-cve-gate.py",
        "first_install_cve_gate_tamper",
    )
    bundle, acceptance, checksum, now = _controlled_acceptance_fixture(tmp_path, module)
    payload = json.loads(acceptance.read_text())
    payload["bundle_sha256"] = "0" * 64
    raw = _write_private_json(acceptance, payload)
    checksum.write_text(hashlib.sha256(raw).hexdigest() + "\n")
    checksum.chmod(0o600)

    with pytest.raises(ValueError, match="does not bind the exact bundle"):
        module.assert_controlled_first_install_allowed(
            bundle=bundle,
            acceptance_path=acceptance,
            acceptance_checksum_path=checksum,
            now=now,
        )

    acceptance.chmod(0o644)
    with pytest.raises(ValueError, match="mode-0600"):
        module.assert_controlled_first_install_allowed(
            bundle=bundle,
            acceptance_path=acceptance,
            acceptance_checksum_path=checksum,
            now=now,
        )

    payload["bundle_sha256"] = hashlib.sha256(bundle.read_bytes()).hexdigest()
    payload["authorized_at_utc"] = "2026-07-20T11:05:00Z"
    raw = _write_private_json(acceptance, payload)
    checksum.write_text(hashlib.sha256(raw).hexdigest() + "\n")
    checksum.chmod(0o600)
    with pytest.raises(ValueError, match="operator authorization must be no more"):
        module.assert_controlled_first_install_allowed(
            bundle=bundle,
            acceptance_path=acceptance,
            acceptance_checksum_path=checksum,
            now=now,
        )


def _remote_install_state_probe_program() -> str:
    source = DEPLOY_TO_SSH.read_text(encoding="utf-8")
    fragment = source.split('REMOTE_INSTALLATION_STATE="$(', 1)[1]
    program = fragment.split("<<'PY'\n", 1)[1]
    return program.split('\nPY\n\t)"', 1)[0]


def _portable_remote_install_state_probe(*, hook: str = "") -> str:
    program = _remote_install_state_probe_program()
    production_ids = "(999, 999)"
    assert program.count(production_ids) == 1
    program = program.replace(
        production_ids,
        f"({os.getuid()}, {os.getgid()})",
        1,
    )
    if hook:
        marker = "path = Path(sys.argv[1])\n"
        assert program.count(marker) == 1
        program = program.replace(marker, hook.strip() + "\n\n" + marker, 1)
    return program


def _run_remote_install_state_probe(
    path: Path,
    *,
    hook: str = "",
    timeout: float = 3,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-", str(path)],
        input=_portable_remote_install_state_probe(hook=hook),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _write_install_state(path: Path, state: str = "pending") -> None:
    path.write_text(json.dumps({"installation_state": state}) + "\n", encoding="utf-8")
    path.chmod(0o640)


def test_remote_install_state_probe_reads_bound_regular_file_and_missing_state(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "install-state.json"
    missing = _run_remote_install_state_probe(state_path)
    _write_install_state(state_path)
    pending = _run_remote_install_state_probe(state_path)

    assert missing.returncode == 0
    assert missing.stdout.strip() == "missing"
    assert pending.returncode == 0, pending.stderr
    assert pending.stdout.strip() == "pending"


def test_remote_install_state_probe_rejects_fifo_swap_without_blocking(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "install-state.json"
    _write_install_state(state_path)
    hook = """
original_open = os.open
swapped = False

def open_with_fifo_swap(target, flags, *args, **kwargs):
    global swapped
    candidate = Path(target)
    if not swapped and candidate.name == "install-state.json":
        swapped = True
        candidate.unlink()
        os.mkfifo(candidate, 0o640)
    return original_open(target, flags, *args, **kwargs)

os.open = open_with_fifo_swap
"""

    result = _run_remote_install_state_probe(state_path, hook=hook, timeout=2)

    assert result.returncode != 0
    assert "Remote installation state is unreadable" in result.stderr


def test_remote_install_state_probe_rejects_path_replacement_during_read(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "install-state.json"
    _write_install_state(state_path)
    hook = """
original_read = os.read
replaced = False

def read_with_path_replacement(descriptor, size):
    global replaced
    if not replaced:
        replaced = True
        candidate = Path(sys.argv[1])
        candidate.replace(candidate.with_name("opened-install-state.json"))
        candidate.write_text('{"installation_state":"complete"}\\n', encoding="utf-8")
        candidate.chmod(0o640)
    return original_read(descriptor, size)

os.read = read_with_path_replacement
"""

    result = _run_remote_install_state_probe(state_path, hook=hook)

    assert result.returncode != 0
    assert "Remote installation state is unreadable" in result.stderr


def test_remote_install_state_probe_rejects_in_place_change_and_oversized_state(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "install-state.json"
    _write_install_state(state_path)
    hook = """
original_read = os.read
changed = False

def read_with_in_place_change(descriptor, size):
    global changed
    if not changed:
        changed = True
        candidate = Path(sys.argv[1])
        candidate.write_text(
            '{"installation_state":"complete","changed":true}\\n',
            encoding="utf-8",
        )
        candidate.chmod(0o640)
    return original_read(descriptor, size)

os.read = read_with_in_place_change
"""
    changed = _run_remote_install_state_probe(state_path, hook=hook)

    state_path.write_bytes(
        b'{"installation_state":"pending","padding":"' + (b"x" * (1024 * 1024)) + b'"}\n'
    )
    state_path.chmod(0o640)
    oversized = _run_remote_install_state_probe(state_path)

    assert changed.returncode != 0
    assert oversized.returncode != 0
    assert "Remote installation state is unreadable" in changed.stderr
    assert "Remote installation state is unreadable" in oversized.stderr


def test_admin_key_rotation_fences_api_before_disk_mutation_and_supports_retry() -> None:
    source = (ROOT / "deploy" / "admin-key-rotate.sh").read_text()
    lookup = 'npcink_ai_cloud_compose "${ROOT_DIR}" ps --all -q api'
    stop = 'npcink_ai_cloud_compose "${ROOT_DIR}" stop -t 30 api'
    mutation = 'ADMIN_KEY="$("${RELEASE_TOOL_PYTHON}"'
    start = 'npcink_ai_cloud_compose "${ROOT_DIR}" start api'
    ready = "npcink_ai_cloud_wait_for_internal_endpoint"
    disclose = "printf '%s\\n' \"${ADMIN_KEY}\""
    main_fence = source.index("# Establish the serving fence")
    main_stop = source.index(stop, main_fence)

    assert lookup in source
    assert source.index(lookup) < main_stop < source.index(mutation)
    assert source.index(mutation) < source.index(start) < source.index(ready)
    assert source.index(ready) < source.index(disclose)
    assert source.index(disclose) < source.index("API_FENCE_ACTIVE=0", source.index(ready))
    assert 'if [ "${API_FENCE_ACTIVE}" = "1" ]; then' in source
    assert source.count(stop) >= 2
    assert "STARTED_API_CONTAINER_ID" in source
    # --all is the recovery property: a prior fail-closed run leaves the exact
    # container stopped, and the next run can still identify and start it.
    assert 'ps -q api)"' not in source.split("API_CONTAINER_ID=", 1)[1].split("\n", 1)[0]


def test_ordinary_deploy_and_safe_prune_require_positive_durable_sentinel() -> None:
    deploy = (ROOT / "deploy" / "deploy-to-ssh-host.sh").read_text()
    maintenance = (ROOT / ".github/workflows/production-maintenance.yml").read_text()
    validator = (ROOT / "deploy" / "validate-installation-complete.py").read_text()

    for source in (deploy, maintenance):
        assert ".installation-complete" in source
        assert "validate-installation-complete.py" in source
        assert "pg18_empty_initialization.v1" in validator
    assert "installation_complete.v1" in validator
    assert "release.parent != managed_root" in validator
    assert "release ==" not in validator
    assert "current_link" not in validator
    assert "current_release" not in validator
    assert maintenance.index("validate_completed_installation") < maintenance.index(
        "docker image prune -af"
    )


def test_first_install_cve_probe_is_protected_and_precedes_host_mutation() -> None:
    source = DEPLOY_TO_SSH.read_text()
    probe = 'REMOTE_INSTALLATION_STATE="$('
    gate = "check-first-install-cve-gate.py"
    first_mutation = 'echo "[info] Preparing remote directory'

    assert probe in source
    assert "stat.S_IMODE(metadata.st_mode) != 0o640" in source
    assert "(metadata.st_uid, metadata.st_gid) != (999, 999)" in source
    assert 'getattr(os, "O_NOFOLLOW", 0)' in source
    assert 'getattr(os, "O_NONBLOCK", 0)' in source
    assert "MAX_INSTALL_STATE_BYTES = 1024 * 1024" in source
    assert "descriptor_metadata_after = os.fstat(descriptor)" in source
    assert "path_metadata_after = path.lstat()" in source
    assert "--controlled-cve-risk-acceptance" in source
    assert "--controlled-cve-risk-acceptance-checksum" in source
    assert "FIRST_INSTALL_CVE_GATE_ARGS" in source
    assert source.index("Stage-only upload is forbidden") < source.index(first_mutation)
    assert source.index(probe) < source.index(gate) < source.index(first_mutation)
