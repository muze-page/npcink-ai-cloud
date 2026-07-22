#!/usr/bin/env python3
"""Open and hold the shared setup/deploy lock without a path-open race."""

from __future__ import annotations

import argparse
import fcntl
import os
import stat
import subprocess
import sys
from pathlib import Path


def _validate_descriptor_path(
    descriptor: int, path: Path, *, uid: int, gid: int, mode: int
) -> None:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("installation lock must be a regular file")
    if (metadata.st_uid, metadata.st_gid) != (uid, gid):
        raise RuntimeError("installation lock ownership is unsafe")
    if stat.S_IMODE(metadata.st_mode) != mode:
        raise RuntimeError("installation lock mode is unsafe")
    path_metadata = os.lstat(path)
    if stat.S_ISLNK(path_metadata.st_mode) or not stat.S_ISREG(path_metadata.st_mode):
        raise RuntimeError("installation lock path is not a regular non-symlink file")
    if (path_metadata.st_dev, path_metadata.st_ino) != (
        metadata.st_dev,
        metadata.st_ino,
    ):
        raise RuntimeError("installation lock path changed while it was opened")


def _open_lock(path: Path, *, create: bool, uid: int, gid: int, mode: int) -> int:
    flags = (
        os.O_RDWR
        | os.O_CLOEXEC
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    created = False
    if create:
        try:
            descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, mode)
            created = True
        except FileExistsError:
            descriptor = os.open(path, flags)
    else:
        descriptor = os.open(path, flags)

    try:
        initial_metadata = os.fstat(descriptor)
        if not stat.S_ISREG(initial_metadata.st_mode):
            raise RuntimeError("installation lock must be a regular file")
        if created:
            os.fchmod(descriptor, mode)
            os.fchown(descriptor, uid, gid)
        _validate_descriptor_path(descriptor, path, uid=uid, gid=gid, mode=mode)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Revalidate after the lock is held. A path swap between the first
        # lstat and flock must never yield a lock on an orphaned old inode.
        _validate_descriptor_path(descriptor, path, uid=uid, gid=gid, mode=mode)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _parse_mode(value: str) -> int:
    try:
        parsed = int(value, 8)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("mode must be octal") from exc
    if parsed < 0 or parsed > 0o777:
        raise argparse.ArgumentTypeError("mode must be between 000 and 777")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--uid", required=True, type=int)
    parser.add_argument("--gid", required=True, type=int)
    parser.add_argument("--mode", default="0600", type=_parse_mode)
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--command-output-fd", type=int)
    parser.add_argument("command", choices=("hold", "exec"))
    parser.add_argument("remainder", nargs=argparse.REMAINDER)
    return parser


def main() -> int:
    args = _parser().parse_args()
    descriptor = _open_lock(
        args.path,
        create=args.create,
        uid=args.uid,
        gid=args.gid,
        mode=args.mode,
    )
    if args.command == "hold":
        command = list(args.remainder)
        if command and command[0] == "--":
            command.pop(0)
        if command:
            if args.command_output_fd is None or args.command_output_fd < 0:
                raise SystemExit("[fail] install-lock hold command requires an output fd")
            os.set_inheritable(descriptor, True)
            environment = dict(os.environ)
            environment["NPCINK_CLOUD_INSTALL_LOCK_FD"] = str(descriptor)
            environment["NPCINK_CLOUD_INSTALL_LOCK_HELD"] = "1"
            completed = subprocess.run(
                command,
                check=False,
                env=environment,
                pass_fds=(descriptor, args.command_output_fd),
                stdin=subprocess.DEVNULL,
                stdout=args.command_output_fd,
                stderr=None,
            )
            if completed.returncode != 0:
                raise SystemExit(completed.returncode)
        print("install_lock_acquired.v1", flush=True)
        sys.stdin.buffer.read()
        os.close(descriptor)
        return 0

    command = list(args.remainder)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        raise SystemExit("[fail] install-lock exec requires a command")
    target_fd = 8
    if descriptor != target_fd:
        os.dup2(descriptor, target_fd, inheritable=True)
        os.close(descriptor)
    else:
        os.set_inheritable(descriptor, True)
    environment = dict(os.environ)
    environment["NPCINK_CLOUD_INSTALL_LOCK_FD"] = str(target_fd)
    environment["NPCINK_CLOUD_INSTALL_LOCK_HELD"] = "1"
    os.execvpe(command[0], command, environment)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BlockingIOError, FileNotFoundError, PermissionError, RuntimeError) as exc:
        raise SystemExit(f"[fail] {exc}") from exc
