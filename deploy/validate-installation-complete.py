#!/usr/bin/env python3
"""Validate durable first-install acceptance and optional current runtime state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path

LOWER_SHA256 = re.compile(r"[0-9a-f]{64}")
RELEASE_NAME = re.compile(r"release-[A-Za-z0-9][A-Za-z0-9._-]*")


def _load_protected_json(
    path: Path, *, label: str, uid: int, gid: int, mode: int
) -> tuple[dict[str, object], bytes]:
    def validate_descriptor(descriptor: int) -> tuple[os.stat_result, os.stat_result]:
        path_metadata = os.lstat(path)
        descriptor_metadata = os.fstat(descriptor)
        for metadata in (path_metadata, descriptor_metadata):
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ValueError(f"{label} must be a regular non-symlink file")
            if (metadata.st_uid, metadata.st_gid) != (uid, gid):
                raise ValueError(f"{label} ownership is unsafe")
            if stat.S_IMODE(metadata.st_mode) != mode:
                raise ValueError(f"{label} mode is unsafe")
        if (descriptor_metadata.st_dev, descriptor_metadata.st_ino) != (
            path_metadata.st_dev,
            path_metadata.st_ino,
        ):
            raise ValueError(f"{label} changed while it was opened")
        return path_metadata, descriptor_metadata

    descriptor = os.open(
        path,
        os.O_RDONLY
        | os.O_CLOEXEC
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        _path_before, descriptor_before = validate_descriptor(descriptor)
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 64 * 1024):
            chunks.append(chunk)
        raw = b"".join(chunks)
        _path_after, descriptor_after = validate_descriptor(descriptor)
        if (
            descriptor_after.st_size,
            descriptor_after.st_mtime_ns,
            descriptor_after.st_ctime_ns,
        ) != (
            descriptor_before.st_size,
            descriptor_before.st_mtime_ns,
            descriptor_before.st_ctime_ns,
        ):
            raise ValueError(f"{label} changed while it was read")
    finally:
        os.close(descriptor)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload, raw


def _valid_accepted_at(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed <= datetime.now(UTC)


def validate_sentinel(
    managed_root: Path, sentinel_path: Path, *, expected_release: Path | None = None
) -> None:
    managed_root = Path(os.path.abspath(managed_root))
    if managed_root == Path("/") or managed_root.is_symlink() or not managed_root.is_dir():
        raise ValueError("managed root must be a canonical non-symlink directory")
    payload, _ = _load_protected_json(
        sentinel_path,
        label="installation-complete sentinel",
        uid=0,
        gid=0,
        mode=0o600,
    )
    if payload.get("contract") != "installation_complete.v1":
        raise ValueError("installation-complete sentinel contract is invalid")
    if not _valid_accepted_at(payload.get("accepted_at")):
        raise ValueError("installation-complete accepted_at is invalid")
    digest = payload.get("config_digest")
    if not isinstance(digest, str) or not LOWER_SHA256.fullmatch(digest):
        raise ValueError("installation-complete config_digest is invalid")
    release = Path(str(payload.get("release") or ""))
    if (
        not release.is_absolute()
        or release.parent != managed_root
        or not RELEASE_NAME.fullmatch(release.name)
    ):
        raise ValueError("installation-complete release is not a direct managed release")
    if expected_release is not None and release != Path(os.path.abspath(expected_release)):
        raise ValueError("installation-complete release does not match expected release")


def validate_current_runtime(state_path: Path, runtime_path: Path) -> None:
    state, _ = _load_protected_json(
        state_path,
        label="install-state.json",
        uid=999,
        gid=999,
        mode=0o640,
    )
    runtime, runtime_bytes = _load_protected_json(
        runtime_path,
        label="runtime-config.json",
        uid=999,
        gid=999,
        mode=0o600,
    )
    if not runtime:
        raise ValueError("runtime-config.json must not be empty")
    if state.get("installation_state") != "complete":
        raise ValueError("current installation state is not complete")
    if state.get("database_contract") != "pg18_empty_initialization.v1":
        raise ValueError("current PostgreSQL 18 installation contract is missing")
    digest = state.get("config_digest")
    if (
        not isinstance(digest, str)
        or not LOWER_SHA256.fullmatch(digest)
        or digest != hashlib.sha256(runtime_bytes).hexdigest()
    ):
        raise ValueError("current runtime configuration digest does not match")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--managed-root", required=True, type=Path)
    parser.add_argument("--sentinel", required=True, type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--expected-release", type=Path)
    args = parser.parse_args()
    if (args.state is None) != (args.runtime is None):
        parser.error("--state and --runtime must be supplied together")
    validate_sentinel(
        args.managed_root,
        args.sentinel,
        expected_release=args.expected_release,
    )
    if args.state is not None and args.runtime is not None:
        validate_current_runtime(args.state, args.runtime)
    print("installation_complete_valid.v1")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        raise SystemExit(f"[fail] {exc}") from exc
