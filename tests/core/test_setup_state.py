from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from app.setup import state as state_module
from app.setup.state import INSTALL_LOCK_FILE, SetupConfigStore, SetupStateError


def _lock_path(tmp_path: Path) -> Path:
    return tmp_path / INSTALL_LOCK_FILE


def test_install_lock_creates_owner_controlled_regular_file(tmp_path: Path) -> None:
    store = SetupConfigStore(tmp_path)

    with store.install_lock():
        metadata = _lock_path(tmp_path).lstat()
        assert stat.S_ISREG(metadata.st_mode)
        assert stat.S_IMODE(metadata.st_mode) == 0o600
        assert metadata.st_uid == os.geteuid()
        assert metadata.st_gid == os.getegid()


def test_install_lock_rejects_symlink_without_mutating_target(tmp_path: Path) -> None:
    target = tmp_path / "outside-lock-target"
    target.write_text("must-not-change", encoding="utf-8")
    target.chmod(0o640)
    before = target.stat()
    _lock_path(tmp_path).symlink_to(target.name)

    with pytest.raises(SetupStateError, match="installation lock is unavailable"):
        with SetupConfigStore(tmp_path).install_lock():
            pytest.fail("unsafe symlink lock must never be acquired")

    after = target.stat()
    assert target.read_text(encoding="utf-8") == "must-not-change"
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode) == 0o640
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)


def test_install_lock_rejects_fifo_without_mutating_it(tmp_path: Path) -> None:
    lock_path = _lock_path(tmp_path)
    os.mkfifo(lock_path, 0o600)
    before = lock_path.lstat()

    with pytest.raises(SetupStateError, match="installation lock is invalid"):
        with SetupConfigStore(tmp_path).install_lock():
            pytest.fail("FIFO lock must never be acquired")

    after = lock_path.lstat()
    assert stat.S_ISFIFO(after.st_mode)
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode) == 0o600
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)


def test_install_lock_rejects_unsafe_mode_without_repairing_it(tmp_path: Path) -> None:
    lock_path = _lock_path(tmp_path)
    lock_path.write_bytes(b"")
    lock_path.chmod(0o640)

    with pytest.raises(SetupStateError, match="installation lock is invalid"):
        with SetupConfigStore(tmp_path).install_lock():
            pytest.fail("unsafe lock mode must never be repaired or acquired")

    assert stat.S_IMODE(lock_path.lstat().st_mode) == 0o640


def test_install_lock_rejects_owner_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_uid = os.geteuid()
    monkeypatch.setattr(state_module.os, "geteuid", lambda: current_uid + 1)

    with pytest.raises(SetupStateError, match="installation lock is invalid"):
        with SetupConfigStore(tmp_path).install_lock():
            pytest.fail("foreign-owned lock must never be acquired")

    assert stat.S_IMODE(_lock_path(tmp_path).lstat().st_mode) == 0o600


def test_install_lock_detects_path_swap_after_flock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SetupConfigStore(tmp_path)
    lock_path = _lock_path(tmp_path)
    with store.install_lock():
        original_inode = lock_path.lstat().st_ino

    replacement = tmp_path / ".replacement-install.lock"
    replacement.write_bytes(b"")
    replacement.chmod(0o600)
    replacement_inode = replacement.lstat().st_ino
    original_flock = state_module.fcntl.flock
    swapped = False

    def swap_path_then_flock(descriptor: int, operation: int) -> None:
        nonlocal swapped
        if operation & state_module.fcntl.LOCK_EX and not swapped:
            os.replace(replacement, lock_path)
            swapped = True
        original_flock(descriptor, operation)

    monkeypatch.setattr(state_module.fcntl, "flock", swap_path_then_flock)

    with pytest.raises(SetupStateError, match="installation lock is invalid"):
        with store.install_lock():
            pytest.fail("replaced lock path must never enter the critical section")

    assert swapped is True
    assert lock_path.lstat().st_ino == replacement_inode
    assert lock_path.lstat().st_ino != original_inode
