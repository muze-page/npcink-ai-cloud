from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "deploy-static-terms-to-ssh-host.sh"


def _remote_mutation_body() -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    opening = "<<'REMOTE_MUTATION'\n"
    start = source.index(opening) + len(opening)
    end = source.index("\nREMOTE_MUTATION\n", start)
    return source[start:end]


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _write_terms(root: Path, *, label: str, valid_public_markers: bool) -> None:
    files = {
        "index.html": "Npcink Cloud Legal Documents" if valid_public_markers else label,
        "en/terms.html": "Npcink Cloud Terms of Service" if valid_public_markers else label,
        "zh/terms.html": "Npcink Cloud 服务条款" if valid_public_markers else label,
        "styles.css": "site-header" if valid_public_markers else label,
        "en/privacy.html": label,
        "zh/privacy.html": label,
        "assets/icon.txt": label,
    }
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{content}\n", encoding="utf-8")
        target.chmod(0o644)
    for directory in [root, *[path for path in root.rglob("*") if path.is_dir()]]:
        directory.chmod(0o755)


@dataclass(frozen=True)
class StaticTermsFixture:
    remote: Path
    release_a: Path
    release_b: Path
    bundle: Path
    fake_bin: Path
    env: dict[str, str]

    @property
    def lock(self) -> Path:
        return self.remote / ".deploy-lock"

    @property
    def failure_marker(self) -> Path:
        return self.remote / ".static-terms-failed"


def _build_fixture(tmp_path: Path, *, token: str = "a" * 32) -> StaticTermsFixture:
    remote = tmp_path / "managed-root"
    incoming = remote / ".incoming"
    release_a = remote / "release-a"
    release_b = remote / "release-b"
    incoming.mkdir(parents=True)
    incoming.chmod(0o700)
    for release, label in ((release_a, "old-a"), (release_b, "old-b")):
        (release / "site").mkdir(parents=True)
        _write_terms(release / "site" / "terms", label=label, valid_public_markers=False)
        release.chmod(0o755)
        (release / "site").chmod(0o755)
    remote.chmod(0o755)
    (remote / "current").symlink_to(release_a)

    source = tmp_path / "new-source" / "terms"
    _write_terms(source, label="new", valid_public_markers=True)
    bundle = incoming / f"static-terms.{token}.tgz"
    with tarfile.open(bundle, "w:gz") as archive:
        archive.add(source, arcname="terms")
    bundle.chmod(0o600)

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "id",
        r"""#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "-u" ]; then
    printf '%s\n' "${FAKE_STATIC_TERMS_UID:-0}"
    exit 0
fi
exec /usr/bin/id "$@"
""",
    )
    _write_executable(
        fake_bin / "stat",
        r"""#!/usr/bin/env python3
from __future__ import annotations

import os
import stat
import sys

args = [value for value in sys.argv[1:] if value != "--"]
if len(args) < 3 or args[0] != "-c":
    raise SystemExit(2)
format_string = args[1]
path = args[-1]
metadata = os.stat(path)
if format_string == "%u":
    print(os.environ.get("FAKE_STATIC_TERMS_OWNER_UID", "0"))
elif format_string == "%a":
    print(format(stat.S_IMODE(metadata.st_mode), "o"))
else:
    raise SystemExit(2)
""",
    )
    _write_executable(
        fake_bin / "curl",
        r"""#!/usr/bin/env bash
set -euo pipefail
output=""
url=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        -o)
            output="$2"
            shift 2
            ;;
        --)
            shift
            ;;
        https://*)
            url="$1"
            shift
            ;;
        *)
            shift
            ;;
    esac
done
if [ -n "${FAKE_STATIC_TERMS_CURL_FAIL_PATH:-}" ] &&
    [[ "${url}" == *"${FAKE_STATIC_TERMS_CURL_FAIL_PATH}"* ]]; then
    exit 75
fi
if [ -n "${output}" ]; then
    case "${url}" in
        */terms|*/terms/) printf '%s\n' 'Npcink Cloud Legal Documents' >"${output}" ;;
        */terms/en/terms.html) printf '%s\n' 'Npcink Cloud Terms of Service' >"${output}" ;;
        */terms/zh/terms.html) printf '%s\n' 'Npcink Cloud 服务条款' >"${output}" ;;
        */terms/styles.css) printf '%s\n' 'site-header' >"${output}" ;;
        *) : >"${output}" ;;
    esac
fi
""",
    )
    real_tar = shutil.which("tar")
    real_mv = shutil.which("mv")
    real_rmdir = shutil.which("rmdir")
    assert real_tar and real_mv and real_rmdir
    _write_executable(
        fake_bin / "tar",
        f"""#!/usr/bin/env bash
set -euo pipefail
if [ -n "${{FAKE_STATIC_TERMS_TAR_STARTED:-}}" ]; then
    : >"${{FAKE_STATIC_TERMS_TAR_STARTED}}"
fi
if [ -n "${{FAKE_STATIC_TERMS_TAR_RELEASE:-}}" ]; then
    while [ ! -e "${{FAKE_STATIC_TERMS_TAR_RELEASE}}" ]; do
        sleep 0.05
    done
fi
{real_tar!s} "$@"
if [ -n "${{FAKE_STATIC_TERMS_SWITCH_CURRENT_TO:-}}" ]; then
    ln -sfn "${{FAKE_STATIC_TERMS_SWITCH_CURRENT_TO}}" "${{FAKE_STATIC_TERMS_REMOTE}}/current"
fi
""",
    )
    _write_executable(
        fake_bin / "mv",
        f"""#!/usr/bin/env bash
set -euo pipefail
previous=""
last=""
for argument in "$@"; do
    previous="${{last}}"
    last="${{argument}}"
done
if [ "${{FAKE_STATIC_TERMS_FAIL_ACTIVATION:-0}}" = "1" ] &&
    [[ "${{previous}}" == *.work/terms ]] && [[ "${{last}}" == */site/terms ]]; then
    exit 76
fi
if [ "${{FAKE_STATIC_TERMS_FAIL_RETIRE:-0}}" = "1" ] &&
    [[ "${{previous}}" == */site/terms ]] && [[ "${{last}}" == */site/terms.previous ]]; then
    exit 78
fi
exec {real_mv!s} "$@"
""",
    )
    _write_executable(
        fake_bin / "rmdir",
        f"""#!/usr/bin/env bash
set -euo pipefail
last=""
for argument in "$@"; do
    last="${{argument}}"
done
if [ "${{FAKE_STATIC_TERMS_FAIL_UNLOCK:-0}}" = "1" ] &&
    [[ "${{last}}" == */.deploy-lock ]]; then
    exit 77
fi
exec {real_rmdir!s} "$@"
""",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["FAKE_STATIC_TERMS_REMOTE"] = str(remote)
    return StaticTermsFixture(
        remote=remote,
        release_a=release_a,
        release_b=release_b,
        bundle=bundle,
        fake_bin=fake_bin,
        env=env,
    )


def _run_remote(
    fixture: StaticTermsFixture,
    *,
    bundle: Path | None = None,
    env_overrides: dict[str, str] | None = None,
    timeout: float = 15,
) -> subprocess.CompletedProcess[str]:
    env = fixture.env.copy()
    env.update(env_overrides or {})
    return subprocess.run(
        [
            "bash",
            "-c",
            _remote_mutation_body(),
            "static-terms-remote",
            str(fixture.remote),
            str(bundle or fixture.bundle),
            "https://cloud.npc.ink",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _wait_for(path: Path, *, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {path}")


def _marker(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line
    )


def test_static_terms_source_contract_is_fail_closed() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert (
        'REMOTE_TERMS_BUNDLE="${REMOTE_DIR}/.incoming/static-terms.${UPLOAD_TOKEN}.tgz"' in source
    )
    assert 'DEPLOY_LOCK_DIR="${REMOTE_DIR}/.deploy-lock"' in source
    assert 'FROZEN_RELEASE="$(readlink -f "${CURRENT_LINK}")"' in source
    assert 'TERMS_TARGET="${FROZEN_RELEASE}/site/terms"' in source
    assert 'TERMS_PREVIOUS="${FROZEN_RELEASE}/site/terms.previous"' in source
    assert "remote_shell_arg()" in source
    assert 'PREPARE_COMMAND="bash -s -- $(remote_shell_arg "${REMOTE_DIR}")' in source
    assert 'MUTATION_COMMAND="bash -s -- $(remote_shell_arg "${REMOTE_DIR}")' in source
    assert '[ "${SSH_USER}" = "root" ]' in source
    assert "StrictHostKeyChecking=yes" in source
    assert "activation_committed_terminalization_incomplete" in source
    assert "rolled_back_unlock_failed" in source
    assert (
        'release_deploy_lock || fail "Shared deployment lock release could not be proved"' in source
    )


def test_pointer_switch_cannot_redirect_the_frozen_release(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)

    result = _run_remote(
        fixture,
        env_overrides={
            "FAKE_STATIC_TERMS_SWITCH_CURRENT_TO": str(fixture.release_b),
        },
    )

    assert result.returncode == 0, result.stderr
    assert (fixture.remote / "current").resolve() == fixture.release_b.resolve()
    assert "Npcink Cloud Legal Documents" in (
        fixture.release_a / "site" / "terms" / "index.html"
    ).read_text(encoding="utf-8")
    assert "old-b" in (fixture.release_b / "site" / "terms" / "index.html").read_text(
        encoding="utf-8"
    )
    assert not (fixture.release_a / "site" / "terms.previous").exists()
    assert not fixture.bundle.exists()
    assert not fixture.lock.exists()
    assert not fixture.failure_marker.exists()


def test_concurrent_static_terms_run_is_blocked_and_cleans_its_upload(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path, token="a" * 32)
    second_source = tmp_path / "second-source" / "terms"
    _write_terms(second_source, label="second", valid_public_markers=True)
    second_bundle = fixture.remote / ".incoming" / f"static-terms.{'b' * 32}.tgz"
    with tarfile.open(second_bundle, "w:gz") as archive:
        archive.add(second_source, arcname="terms")
    second_bundle.chmod(0o600)
    started = tmp_path / "tar-started"
    release = tmp_path / "tar-release"
    first_env = fixture.env.copy()
    first_env.update(
        {
            "FAKE_STATIC_TERMS_TAR_STARTED": str(started),
            "FAKE_STATIC_TERMS_TAR_RELEASE": str(release),
        }
    )
    first = subprocess.Popen(
        [
            "bash",
            "-c",
            _remote_mutation_body(),
            "static-terms-remote",
            str(fixture.remote),
            str(fixture.bundle),
            "https://cloud.npc.ink",
        ],
        cwd=ROOT,
        env=first_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _wait_for(started)
    assert fixture.lock.is_dir()

    second = _run_remote(fixture, bundle=second_bundle)
    assert second.returncode != 0
    assert "holds the shared lock" in second.stderr
    assert not second_bundle.exists()
    assert fixture.lock.is_dir()

    release.touch()
    stdout, stderr = first.communicate(timeout=15)
    assert first.returncode == 0, f"{stdout}\n{stderr}"
    assert not fixture.lock.exists()
    assert not fixture.bundle.exists()


def test_activation_failure_restores_previous_terms_and_releases_lock(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    old_body = (fixture.release_a / "site" / "terms" / "index.html").read_text(encoding="utf-8")

    result = _run_remote(
        fixture,
        env_overrides={"FAKE_STATIC_TERMS_FAIL_ACTIVATION": "1"},
    )

    assert result.returncode != 0
    assert (fixture.release_a / "site" / "terms" / "index.html").read_text(
        encoding="utf-8"
    ) == old_body
    assert not (fixture.release_a / "site" / "terms.previous").exists()
    assert not fixture.bundle.exists()
    assert not fixture.lock.exists()
    marker = _marker(fixture.failure_marker)
    assert marker["outcome"] == "rolled_back"
    assert marker["recovery"] == "previous_terms_restored_or_no_prior_terms_recreated"


def test_first_rename_failure_preserves_original_terms_and_releases_lock(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path)
    old_body = (fixture.release_a / "site" / "terms" / "index.html").read_text(encoding="utf-8")

    result = _run_remote(
        fixture,
        env_overrides={"FAKE_STATIC_TERMS_FAIL_RETIRE": "1"},
    )

    assert result.returncode != 0
    assert (fixture.release_a / "site" / "terms" / "index.html").read_text(
        encoding="utf-8"
    ) == old_body
    assert not (fixture.release_a / "site" / "terms.previous").exists()
    assert not fixture.bundle.exists()
    assert not fixture.lock.exists()
    assert _marker(fixture.failure_marker)["outcome"] == "rolled_back"


def test_public_validation_failure_restores_previous_terms_and_releases_lock(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path)
    old_body = (fixture.release_a / "site" / "terms" / "index.html").read_text(encoding="utf-8")

    result = _run_remote(
        fixture,
        env_overrides={"FAKE_STATIC_TERMS_CURL_FAIL_PATH": "/terms/en/terms.html"},
    )

    assert result.returncode != 0
    assert (fixture.release_a / "site" / "terms" / "index.html").read_text(
        encoding="utf-8"
    ) == old_body
    assert not (fixture.release_a / "site" / "terms.previous").exists()
    assert not fixture.bundle.exists()
    assert not fixture.lock.exists()
    assert _marker(fixture.failure_marker)["outcome"] == "rolled_back"


def test_unlock_failure_is_nonzero_and_retains_lock_and_evidence(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)

    result = _run_remote(
        fixture,
        env_overrides={"FAKE_STATIC_TERMS_FAIL_UNLOCK": "1"},
    )

    assert result.returncode != 0
    assert "Shared deployment lock release could not be proved" in result.stderr
    assert fixture.lock.is_dir()
    assert not fixture.bundle.exists()
    assert "Npcink Cloud Legal Documents" in (
        fixture.release_a / "site" / "terms" / "index.html"
    ).read_text(encoding="utf-8")
    marker = _marker(fixture.failure_marker)
    assert marker["outcome"] == "activation_committed_terminalization_incomplete"
    assert marker["recovery"] == "keep_new_terms_and_repair_cleanup_or_unlock"


def test_root_and_managed_path_boundaries_fail_before_mutation(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    old_body = (fixture.release_a / "site" / "terms" / "index.html").read_text(encoding="utf-8")

    non_root = _run_remote(
        fixture,
        env_overrides={"FAKE_STATIC_TERMS_UID": "1000"},
    )
    assert non_root.returncode != 0
    assert not fixture.lock.exists()
    assert (fixture.release_a / "site" / "terms" / "index.html").read_text(
        encoding="utf-8"
    ) == old_body

    fixture.remote.chmod(0o777)
    unsafe_mode = _run_remote(fixture)
    assert unsafe_mode.returncode != 0
    assert not fixture.lock.exists()
    assert (fixture.release_a / "site" / "terms" / "index.html").read_text(
        encoding="utf-8"
    ) == old_body


def test_preexisting_unique_work_path_is_not_deleted(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path)
    work = Path(f"{fixture.bundle.with_suffix('')}.work")
    work.mkdir()
    sentinel = work / "operator-evidence.txt"
    sentinel.write_text("preserve\n", encoding="utf-8")

    result = _run_remote(fixture)

    assert result.returncode != 0
    assert sentinel.read_text(encoding="utf-8") == "preserve\n"
    assert work.is_dir()
    assert not fixture.bundle.exists()
    assert not fixture.lock.exists()
