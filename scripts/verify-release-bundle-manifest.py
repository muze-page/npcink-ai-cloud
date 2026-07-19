#!/usr/bin/env python3
"""Build and verify the exact release-bundle manifest without third-party deps."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any, Optional

SCHEMA_VERSION = "npcink.release-bundle.v1"
IMAGE_LOCK_SCHEMA = "npcink.production-image-lock.v1"
SCAN_INDEX_SCHEMA = "npcink.production-image-scan-index.v1"
SCAN_RECEIPT_SCHEMA = "npcink.production-image-scan-receipt.v1"
MANIFEST_NAME = "release-bundle-manifest.json"
CHECKSUMS_NAME = "SHA256SUMS"
SCAN_INDEX_PATH = "release/image-scan/scan-index.json"
CANONICAL_IMAGE_LOCK_PATH = "deploy/image-lock/production-images.json"
CANONICAL_ALLOWLIST_PATH = "deploy/image-lock/cve-allowlist.json"
MAX_TAR_MEMBERS = 20_000
MAX_TAR_UNCOMPRESSED_BYTES = 20 * 1024 * 1024 * 1024
MAX_DOCKER_ARCHIVE_BYTES = 4 * 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
REQUIRED_MAX_DATABASE_AGE_HOURS = 72
REQUIRED_MAX_EXCEPTION_DAYS = 30
MAX_SCAN_TO_BUNDLE_AGE_HOURS = 24
CLOCK_SKEW = dt.timedelta(minutes=5)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40,64}$")
REQUIRED_SOURCE_INPUTS = {
    "uv_lock",
    "pnpm_lock",
    "python_project",
    "pnpm_workspace",
    "production_dockerfiles",
    "frontend_dockerfile",
    "production_compose",
    "runtime_compose",
    "migration_manifest",
    "deploy_tree",
    "site_tree",
}
ALLOWED_SECRET_IDS = {"pip_index_url", "pip_extra_index_url", "pip_trusted_host"}
SCAN_INDEX_TOP_KEYS = {
    "contract_version",
    "status",
    "scope",
    "release_gate",
    "generated_at_utc",
    "lock_path",
    "lock_sha256",
    "allowlist_path",
    "allowlist_sha256",
    "release_platform",
    "grype_database_identity",
    "required_image_keys",
    "equivalent_application_images",
    "images",
}
SCAN_INDEX_IMAGE_KEYS = {
    "image_key",
    "requested_reference",
    "archive_reference",
    "archive_sha256",
    "config_image_id",
    "syft_subject_manifest_digest",
    "source_daemon_image_id",
    "platform",
    "scanner_docker_context",
    "status",
    "receipt_sha256",
    "artifacts",
    "grype_database",
    "blocking_finding_count",
    "unallowlisted_blocking_finding_count",
}


class BundleError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise BundleError(message)


def repository_digest_identity(reference: str) -> str:
    if "@" not in reference:
        fail("external image reference must be digest-pinned")
    tagged, digest = reference.rsplit("@", 1)
    if IMAGE_ID_RE.fullmatch(digest) is None:
        fail("external image reference has an invalid digest")
    last_slash = tagged.rfind("/")
    last_colon = tagged.rfind(":")
    repository = tagged[:last_colon] if last_colon > last_slash else tagged
    if not repository:
        fail("external image reference has an invalid repository")
    return f"{repository}@{digest}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_gzip_payload(path: Path) -> str:
    digest = hashlib.sha256()
    size = 0
    try:
        with gzip.open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                size += len(chunk)
                if size > MAX_DOCKER_ARCHIVE_BYTES:
                    fail("Docker image archive exceeds the uncompressed byte limit")
                digest.update(chunk)
    except (OSError, EOFError) as exc:
        fail(f"invalid compressed Docker image archive: {exc}")
    return digest.hexdigest()


def docker_archive_subject(path: Path, *, archive_reference: str) -> dict[str, str]:
    try:
        with tarfile.open(path, mode="r:*") as archive:
            manifest_member = archive.getmember("manifest.json")
            if not manifest_member.isfile() or manifest_member.size > MAX_MANIFEST_BYTES:
                fail("Docker archive manifest.json is invalid")
            manifest_stream = archive.extractfile(manifest_member)
            if manifest_stream is None:
                fail("Docker archive manifest.json cannot be read")
            manifest = json.loads(manifest_stream.read(MAX_MANIFEST_BYTES + 1))
            if not isinstance(manifest, list) or len(manifest) != 1:
                fail("Docker archive manifest must contain exactly one image")
            entry = manifest[0]
            if not isinstance(entry, dict) or set(entry) != {"Config", "RepoTags", "Layers"}:
                fail("Docker archive manifest entry is invalid")
            config_name = entry.get("Config")
            match = re.fullmatch(
                r"(?:blobs/sha256/)?([0-9a-f]{64})(?:[.]json)?", str(config_name)
            )
            if match is None:
                fail("Docker archive Config is not an exact sha256 object")
            repo_tags = entry.get("RepoTags")
            if repo_tags != [archive_reference]:
                fail("Docker archive RepoTags must contain only its governed release reference")
            config_member = archive.getmember(str(config_name))
            if not config_member.isfile() or config_member.size > MAX_MANIFEST_BYTES:
                fail("Docker archive Config is invalid")
            config_stream = archive.extractfile(config_member)
            if config_stream is None:
                fail("Docker archive Config cannot be read")
            config_bytes = config_stream.read(MAX_MANIFEST_BYTES + 1)
    except (KeyError, OSError, tarfile.TarError, json.JSONDecodeError) as exc:
        fail(f"cannot inspect Docker image archive: {exc}")
    config_hex = hashlib.sha256(config_bytes).hexdigest()
    if config_hex != match.group(1):
        fail("Docker archive Config filename/content digest mismatch")
    try:
        config = json.loads(config_bytes)
    except json.JSONDecodeError as exc:
        fail(f"Docker archive Config JSON is invalid: {exc}")
    if not isinstance(config, dict):
        fail("Docker archive Config must be an object")
    os_name = config.get("os")
    architecture = config.get("architecture")
    if architecture == "aarch64":
        architecture = "arm64"
    elif architecture == "x86_64":
        architecture = "amd64"
    platform = f"{os_name}/{architecture}"
    if platform not in {"linux/amd64", "linux/arm64"}:
        fail("Docker archive Config platform is unsupported")
    return {"config_image_id": f"sha256:{config_hex}", "platform": platform}


def safe_relative(value: str) -> str:
    if not value or "\\" in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        fail(f"unsafe bundle path: {value!r}")
    path = PurePosixPath(value)
    normalized = path.as_posix()
    if (
        not path.parts
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or normalized != value
    ):
        fail(f"unsafe bundle path: {value!r}")
    return normalized


def ensure_plain_file(root: Path, relative: str) -> Path:
    relative = safe_relative(relative)
    path = root.joinpath(*PurePosixPath(relative).parts)
    if path.is_symlink() or not path.is_file():
        fail(f"bundle payload is not a regular file: {relative}")
    resolved_root = root.resolve()
    try:
        path.resolve().relative_to(resolved_root)
    except ValueError:
        fail(f"bundle payload escapes root: {relative}")
    return path


def regular_files(root: Path, *, exclude: set[str] | None = None) -> list[str]:
    excluded = exclude or set()
    result: list[str] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        safe_relative(relative)
        if path.is_symlink():
            fail(f"symlinks are forbidden in release bundles: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            fail(f"special files are forbidden in release bundles: {relative}")
        if relative not in excluded:
            result.append(relative)
    return sorted(result)


def file_record(root: Path, relative: str) -> dict[str, Any]:
    path = ensure_plain_file(root, relative)
    return {"path": relative, "sha256": sha256_file(path), "size": path.stat().st_size}


def tree_digest(records: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(record["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(record["sha256"].encode("ascii"))
        digest.update(b"\0")
        digest.update(str(record["size"]).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def git_tracked(source_root: Path, pathspecs: list[str]) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", *pathspecs],
        cwd=source_root,
        check=True,
        stdout=subprocess.PIPE,
    )
    paths = []
    for raw in completed.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            relative = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            fail(f"tracked input path is not UTF-8: {exc}")
        paths.append(safe_relative(relative))
    return sorted(paths)


def source_input_groups(source_root: Path) -> list[dict[str, Any]]:
    definitions = (
        ("uv_lock", ["uv.lock"]),
        ("pnpm_lock", ["pnpm-lock.yaml"]),
        ("python_project", ["pyproject.toml"]),
        ("pnpm_workspace", ["package.json", "pnpm-workspace.yaml", "frontend/package.json"]),
        ("production_dockerfiles", ["Dockerfile", "Dockerfile.*"]),
        ("frontend_dockerfile", ["frontend/Dockerfile"]),
        ("production_compose", ["docker-compose.prod.yml"]),
        ("runtime_compose", ["docker-compose.runtime.yml"]),
        ("migration_manifest", ["migrations"]),
        ("deploy_tree", ["deploy"]),
        ("site_tree", ["site"]),
    )
    groups: list[dict[str, Any]] = []
    for name, pathspecs in definitions:
        paths = git_tracked(source_root, pathspecs)
        if not paths:
            fail(f"required source input is empty: {name}")
        records = [file_record(source_root, path) for path in paths]
        groups.append({"name": name, "sha256": tree_digest(records), "files": records})
    return groups


def load_image_lock(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"invalid production image lock: {exc}")
    if payload.get("schema_version") != IMAGE_LOCK_SCHEMA:
        fail("unsupported production image-lock schema")
    inputs = payload.get("production_inputs")
    if not isinstance(inputs, list):
        fail("production image lock has no production_inputs list")
    policy = payload.get("scan_policy")
    if (
        not isinstance(policy, dict)
        or policy.get("allowlist_file") != CANONICAL_ALLOWLIST_PATH
        or policy.get("max_database_age_hours") != REQUIRED_MAX_DATABASE_AGE_HOURS
        or policy.get("max_exception_days") != REQUIRED_MAX_EXCEPTION_DAYS
    ):
        fail("production image lock has no canonical bounded scan policy")
    return payload


def external_images(image_lock: dict[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in image_lock["production_inputs"]:
        if not isinstance(item, dict) or item.get("kind") != "compose_external":
            continue
        key = item.get("key")
        reference = item.get("reference")
        release_reference = item.get("release_reference")
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9_]+", key):
            fail("invalid compose_external image key")
        if not isinstance(reference, str) or "@sha256:" not in reference:
            fail(f"compose_external image is not digest-pinned: {key}")
        if (
            not isinstance(release_reference, str)
            or not release_reference.startswith("npcink-ai-cloud-external-")
            or "@" in release_reference
            or release_reference.endswith(":latest")
        ):
            fail(f"compose_external image has no deterministic release alias: {key}")
        if key in seen:
            fail(f"duplicate compose_external image key: {key}")
        seen.add(key)
        result.append(
            {
                "key": key,
                "reference": reference,
                "release_reference": release_reference,
                "archive": f"dist/external-{key.replace('_', '-')}.tar.gz",
            }
        )
    if not result:
        fail("production image lock has no compose_external images")
    return result


def application_images(image_lock: dict[str, Any]) -> list[dict[str, str]]:
    outputs = image_lock.get("application_outputs")
    if not isinstance(outputs, list):
        fail("production image lock has no application_outputs list")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in outputs:
        if not isinstance(item, dict) or item.get("scan_by_default") is not True:
            continue
        key = item.get("key")
        reference = item.get("reference")
        dockerfile = item.get("dockerfile")
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9_]+", key):
            fail("invalid application image key")
        if not isinstance(reference, str) or not reference or any(
            ord(char) < 32 for char in reference
        ):
            fail(f"invalid application image reference: {key}")
        if not isinstance(dockerfile, str):
            fail(f"application image has no Dockerfile: {key}")
        dockerfile = safe_relative(dockerfile)
        if key in seen:
            fail(f"duplicate application image key: {key}")
        seen.add(key)
        result.append(
            {
                "key": key,
                "reference": reference,
                "dockerfile": dockerfile,
                "archive": f"dist/{key.replace('_', '-')}.tar.gz",
            }
        )
    if not {"api", "frontend"}.issubset(seen):
        fail("production image lock lacks required API/frontend outputs")
    external_keys = {item["key"] for item in external_images(image_lock)}
    overlap = seen & external_keys
    if overlap:
        fail(f"application and external image keys overlap: {sorted(overlap)!r}")
    return result


def parse_utc_timestamp(value: object, field: str) -> dt.datetime:
    if not isinstance(value, str) or not value or len(value) > 64:
        fail(f"{field} must be a bounded UTC timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(candidate)
    except ValueError:
        fail(f"{field} must be an ISO-8601 UTC timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
        fail(f"{field} must use UTC")
    return parsed


def validate_branch(value: object) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 255
        or not re.fullmatch(r"[A-Za-z0-9._/-]+", value)
        or value.startswith("/")
        or value.endswith("/")
        or "//" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        fail("invalid source branch")
    return value


def archive_roles(archives: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        image["role"]: {**image, "archive": archive["path"]}
        for archive in archives
        for image in archive["images"]
    }


def validate_scan_evidence(
    root: Path,
    image_lock: dict[str, Any],
    archives: list[dict[str, Any]],
    expected_platform: str,
    scan_index_relative: str = SCAN_INDEX_PATH,
    bundle_created_at: Optional[dt.datetime] = None,  # noqa: UP045
) -> dict[str, Any]:
    if scan_index_relative != SCAN_INDEX_PATH:
        fail("production scan index must use the frozen bundle path")
    scan_path = ensure_plain_file(root, scan_index_relative)
    try:
        index = json.loads(scan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid production image scan index: {exc}")
    if not isinstance(index, dict) or set(index) != SCAN_INDEX_TOP_KEYS:
        fail("production image scan index has an unexpected schema")
    if (
        index["contract_version"] != SCAN_INDEX_SCHEMA
        or index["status"] != "passed"
        or index["scope"] != "release"
        or index["release_gate"] is not True
    ):
        fail("production image scan index is not a complete passed release gate")
    canonical_lock = ensure_plain_file(root, CANONICAL_IMAGE_LOCK_PATH)
    canonical_allowlist = ensure_plain_file(root, CANONICAL_ALLOWLIST_PATH)
    lock_sha256 = sha256_file(canonical_lock)
    allowlist_sha256 = sha256_file(canonical_allowlist)
    if (
        index["lock_path"] != CANONICAL_IMAGE_LOCK_PATH
        or index["lock_sha256"] != lock_sha256
        or index["allowlist_path"] != CANONICAL_ALLOWLIST_PATH
        or index["allowlist_sha256"] != allowlist_sha256
        or index["release_platform"] != expected_platform
    ):
        fail("production image scan index policy/platform binding is invalid")
    generated_at = parse_utc_timestamp(index["generated_at_utc"], "scan index generated_at_utc")
    scan_policy = image_lock.get("scan_policy")
    if not isinstance(scan_policy, dict):
        fail("production image lock has no scan policy")
    max_age_hours = scan_policy.get("max_database_age_hours")
    if (
        max_age_hours != REQUIRED_MAX_DATABASE_AGE_HOURS
        or scan_policy.get("max_exception_days") != REQUIRED_MAX_EXCEPTION_DAYS
        or scan_policy.get("allowlist_file") != CANONICAL_ALLOWLIST_PATH
    ):
        fail("production image lock has no bounded scan freshness policy")
    # Verification binds the immutable evidence timeline to bundle creation,
    # not the verifier's wall clock. This keeps a valid old bundle replayable
    # for rollback while creation still fails if the scan is stale.
    if bundle_created_at is None:
        bundle_created_at = dt.datetime.now(dt.timezone.utc)  # noqa: UP017
    verifier_now = dt.datetime.now(dt.timezone.utc)  # noqa: UP017
    if bundle_created_at > verifier_now + CLOCK_SKEW:
        fail("bundle creation timestamp is future-dated")
    max_age = dt.timedelta(hours=max_age_hours)
    max_scan_to_bundle_age = dt.timedelta(hours=MAX_SCAN_TO_BUNDLE_AGE_HOURS)
    if (
        generated_at > bundle_created_at + CLOCK_SKEW
        or bundle_created_at - generated_at > max_scan_to_bundle_age
    ):
        fail("production image scan index and bundle creation timeline is invalid")

    application_outputs = image_lock.get("application_outputs")
    if not isinstance(application_outputs, list):
        fail("production image lock has no application_outputs list")
    scanned_applications = application_images(image_lock)
    application_keys = {record["key"] for record in scanned_applications}
    external_keys = {item["key"] for item in external_images(image_lock)}
    expected_keys = application_keys | external_keys
    expected_references = {
        record["key"]: record["reference"] for record in scanned_applications
    }
    expected_references.update(
        {item["key"]: item["reference"] for item in external_images(image_lock)}
    )
    expected_archive_references = {
        record["key"]: record["reference"] for record in scanned_applications
    }
    expected_archive_references.update(
        {item["key"]: item["release_reference"] for item in external_images(image_lock)}
    )
    roles = archive_roles(archives)
    required_keys = index["required_image_keys"]
    if (
        not isinstance(required_keys, list)
        or required_keys != sorted(expected_keys)
        or any(not isinstance(key, str) for key in required_keys)
    ):
        fail("production image scan index required key set is incomplete")
    images = index["images"]
    if not isinstance(images, list) or len(images) != len(expected_keys):
        fail("production image scan index image records are incomplete")
    by_key: dict[str, dict[str, Any]] = {}
    scan_root = root / "release" / "image-scan"
    expected_scan_files = {"scan-index.json", "application-image-equivalence.json"}
    scanner_contexts: set[str] = set()
    database_identity = index["grype_database_identity"]
    database_identity_keys = {
        "schema_version",
        "built",
        "source",
        "checksum_sha256",
        "valid",
        "providers",
    }
    if not isinstance(database_identity, dict) or set(database_identity) != database_identity_keys:
        fail("production image scan index Grype database identity is invalid")
    for record in images:
        if not isinstance(record, dict) or set(record) != SCAN_INDEX_IMAGE_KEYS:
            fail("invalid production image scan record")
        key = record["image_key"]
        if key in by_key or key not in expected_keys:
            fail("duplicate or unexpected production image scan key")
        if (
            record["status"] != "passed"
            or not IMAGE_ID_RE.fullmatch(str(record["config_image_id"]))
            or not IMAGE_ID_RE.fullmatch(str(record["syft_subject_manifest_digest"]))
            or not IMAGE_ID_RE.fullmatch(str(record["source_daemon_image_id"]))
            or not SHA256_RE.fullmatch(str(record["archive_sha256"]))
            or not SHA256_RE.fullmatch(str(record["receipt_sha256"]))
            or record["requested_reference"] != expected_references[key]
            or record["archive_reference"] != expected_archive_references[key]
            or record["platform"] != expected_platform
            or not isinstance(record["scanner_docker_context"], str)
            or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", record["scanner_docker_context"])
            or record["grype_database"] != {
                **database_identity,
                "age_hours_at_scan": record["grype_database"].get("age_hours_at_scan")
                if isinstance(record["grype_database"], dict)
                else None,
            }
            or record["unallowlisted_blocking_finding_count"] != 0
        ):
            fail(f"production image scan did not pass for {key}")
        scanner_contexts.add(record["scanner_docker_context"])
        artifacts = record["artifacts"]
        expected_artifact_keys = {
            "image_inspect_sha256",
            "syft_native_json_sha256",
            "sbom_cyclonedx_json_sha256",
            "grype_json_sha256",
        }
        if not isinstance(artifacts, dict) or set(artifacts) != expected_artifact_keys:
            fail(f"production image scan artifacts are incomplete for {key}")
        if any(not SHA256_RE.fullmatch(str(value)) for value in artifacts.values()):
            fail(f"production image scan artifact hash is invalid for {key}")
        receipt_relative = f"release/image-scan/{key}.receipt.json"
        inspect_relative = f"release/image-scan/{key}.image-inspect.json"
        syft_relative = f"release/image-scan/{key}.syft.json"
        sbom_relative = f"release/image-scan/{key}.sbom.cdx.json"
        grype_relative = f"release/image-scan/{key}.grype.json"
        expected_scan_files.update(
            {
                f"{key}.receipt.json",
                f"{key}.image-inspect.json",
                f"{key}.syft.json",
                f"{key}.sbom.cdx.json",
                f"{key}.grype.json",
            }
        )
        receipt_path = ensure_plain_file(root, receipt_relative)
        if sha256_file(receipt_path) != record["receipt_sha256"]:
            fail(f"production image scan receipt hash mismatch for {key}")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt_keys = {
            "contract_version",
            "status",
            "scope",
            "release_gate",
            "generated_at_utc",
            "image_key",
            "lock_path",
            "lock_sha256",
            "allowlist_path",
            "allowlist_sha256",
            "requested_reference",
            "archive_reference",
            "archive_sha256",
            "config_image_id",
            "syft_subject_manifest_digest",
            "source_daemon_image_id",
            "repo_digests",
            "platform",
            "scanner_docker_context",
            "policy",
            "syft_version",
            "grype_version",
            "grype_database",
            "target_distro",
            "severity_counts",
            "blocking_finding_count",
            "allowlisted_blocking_finding_count",
            "unallowlisted_blocking_finding_count",
            "allowlisted_blocking_findings",
            "unallowlisted_blocking_findings",
            "artifacts",
        }
        scanner_versions = {
            item.get("key"): item.get("version")
            for item in image_lock.get("scanner_images", [])
            if isinstance(item, dict)
        }
        if (
            not isinstance(receipt, dict)
            or set(receipt) != receipt_keys
            or receipt.get("contract_version") != SCAN_RECEIPT_SCHEMA
            or receipt.get("status") != "passed"
            or receipt.get("scope") != "release"
            or receipt.get("release_gate") is not True
            or receipt.get("image_key") != key
            or receipt.get("archive_reference") != record["archive_reference"]
            or receipt.get("archive_sha256") != record["archive_sha256"]
            or receipt.get("config_image_id") != record["config_image_id"]
            or receipt.get("syft_subject_manifest_digest")
            != record["syft_subject_manifest_digest"]
            or receipt.get("source_daemon_image_id") != record["source_daemon_image_id"]
            or receipt.get("requested_reference") != expected_references[key]
            or receipt.get("platform") != expected_platform
            or receipt.get("scanner_docker_context") != record["scanner_docker_context"]
            or receipt.get("lock_path") != CANONICAL_IMAGE_LOCK_PATH
            or receipt.get("lock_sha256") != lock_sha256
            or receipt.get("allowlist_path") != CANONICAL_ALLOWLIST_PATH
            or receipt.get("allowlist_sha256") != allowlist_sha256
            or receipt.get("artifacts") != artifacts
            or receipt.get("grype_database") != record["grype_database"]
            or receipt.get("blocking_finding_count") != record["blocking_finding_count"]
            or receipt.get("unallowlisted_blocking_finding_count") != 0
            or receipt.get("policy") != scan_policy
            or receipt.get("syft_version") != scanner_versions.get("syft")
            or receipt.get("grype_version") != scanner_versions.get("grype")
            or not isinstance(receipt.get("repo_digests"), list)
            or any(not isinstance(item, str) for item in receipt.get("repo_digests", []))
            or not isinstance(receipt.get("severity_counts"), dict)
            or not isinstance(receipt.get("allowlisted_blocking_findings"), list)
            or not isinstance(receipt.get("unallowlisted_blocking_findings"), list)
            or receipt.get("unallowlisted_blocking_findings") != []
            or receipt.get("allowlisted_blocking_finding_count")
            != len(receipt.get("allowlisted_blocking_findings", []))
        ):
            fail(f"production image scan receipt is inconsistent for {key}")
        receipt_generated = parse_utc_timestamp(
            receipt.get("generated_at_utc"), f"scan receipt generated_at_utc for {key}"
        )
        grype_database = receipt.get("grype_database")
        expected_database_keys = {
            "schema_version",
            "built",
            "source",
            "checksum_sha256",
            "age_hours_at_scan",
            "valid",
            "providers",
        }
        if (
            not isinstance(grype_database, dict)
            or set(grype_database) != expected_database_keys
            or grype_database.get("valid") is not True
            or not isinstance(grype_database.get("providers"), dict)
            or not {"nvd", "alpine"}.issubset(grype_database["providers"])
            or not isinstance(grype_database.get("source"), str)
            or not grype_database["source"].startswith("https://grype.anchore.io/databases/")
            or not SHA256_RE.fullmatch(str(grype_database.get("checksum_sha256", "")))
            or not isinstance(grype_database.get("age_hours_at_scan"), (int, float))
            or not 0 <= grype_database["age_hours_at_scan"] <= max_age_hours
        ):
            fail(f"production image scan database evidence is missing for {key}")
        if {field: grype_database[field] for field in database_identity_keys} != database_identity:
            fail(f"production image scan database identity drifted for {key}")
        checksum_marker = f"sha256:{grype_database['checksum_sha256']}"
        encoded_checksum_marker = f"sha256%3A{grype_database['checksum_sha256']}"
        if (
            checksum_marker not in grype_database["source"]
            and encoded_checksum_marker not in grype_database["source"]
        ):
            fail(f"production image scan database checksum is inconsistent for {key}")
        for provider_name, provider in grype_database["providers"].items():
            if (
                not isinstance(provider_name, str)
                or not provider_name
                or not isinstance(provider, dict)
                or set(provider) != {"captured", "input"}
                or not re.fullmatch(r"xxh64:[0-9a-f]{16}", str(provider.get("input", "")))
            ):
                fail(f"production image scan database provider is invalid for {key}")
            captured = parse_utc_timestamp(
                provider.get("captured"), f"Grype provider captured for {key}"
            )
            if captured > receipt_generated + CLOCK_SKEW:
                fail(f"production image scan database provider is future-dated for {key}")
        database_built = parse_utc_timestamp(
            grype_database.get("built"), f"Grype database built for {key}"
        )
        if (
            receipt_generated > generated_at + CLOCK_SKEW
            or generated_at - receipt_generated > max_scan_to_bundle_age
            or database_built > receipt_generated + CLOCK_SKEW
            or receipt_generated - database_built > max_age
        ):
            fail(f"production image scan evidence timeline is invalid for {key}")
        artifact_paths = {
            "image_inspect_sha256": inspect_relative,
            "syft_native_json_sha256": syft_relative,
            "sbom_cyclonedx_json_sha256": sbom_relative,
            "grype_json_sha256": grype_relative,
        }
        for artifact_key, relative in artifact_paths.items():
            if sha256_file(ensure_plain_file(root, relative)) != artifacts[artifact_key]:
                fail(f"production image scan artifact hash mismatch for {key}")
        role_name = key if key in application_keys else f"external_{key}"
        bundled_role = roles.get(role_name)
        bundled_subject = (
            docker_archive_subject(
                ensure_plain_file(root, bundled_role["archive"]),
                archive_reference=record["archive_reference"],
            )
            if bundled_role is not None
            else None
        )
        if (
            bundled_role is None
            or bundled_role["reference"] != record["archive_reference"]
            or bundled_role["source_reference"] != record["requested_reference"]
            or bundled_role["expected_image_id"] != record["config_image_id"]
            or bundled_role["source_daemon_image_id"]
            != record["source_daemon_image_id"]
            or sha256_gzip_payload(ensure_plain_file(root, bundled_role["archive"]))
            != record["archive_sha256"]
            or bundled_subject
            != {"config_image_id": record["config_image_id"], "platform": expected_platform}
        ):
            fail(f"bundled Docker archive is not the scanned archive for {key}")
        if key in external_keys:
            repo_digests = receipt.get("repo_digests")
            expected_repo_digest = repository_digest_identity(expected_references[key])
            if not isinstance(repo_digests, list) or expected_repo_digest not in repo_digests:
                fail(f"external scan receipt lacks the locked repo digest for {key}")
        by_key[key] = record
    if set(by_key) != expected_keys:
        fail("production image scan index does not cover the complete release set")
    if len(scanner_contexts) != 1:
        fail("production image scans do not share one local Docker context")
    actual_scan_files = set(regular_files(scan_root))
    if actual_scan_files != expected_scan_files:
        fail("production image scan artifact file set is incomplete or unexpected")

    equivalence_path = ensure_plain_file(
        root, "release/image-scan/application-image-equivalence.json"
    )
    equivalence = json.loads(equivalence_path.read_text(encoding="utf-8"))
    if equivalence != index["equivalent_application_images"]:
        fail("application image equivalence file does not match scan index")
    if (
        equivalence.get("contract_version") != "npcink.production-image-equivalence.v1"
        or equivalence.get("status") != "passed"
    ):
        fail("application image equivalence is not a passed v1 record")

    for key, scan_record in by_key.items():
        role = key if key in application_keys else f"external_{key}"
        if role in roles and (
            roles[role]["expected_image_id"] != scan_record["config_image_id"]
            or roles[role]["source_daemon_image_id"]
            != scan_record["source_daemon_image_id"]
        ):
            fail(f"bundled image identity was not the scanned image identity: {role}")
    equivalent_records = equivalence.get("images")
    if not isinstance(equivalent_records, list):
        fail("application image equivalence records are missing")
    outputs_by_key = {
        record["key"]: record
        for record in application_outputs
        if isinstance(record, dict) and isinstance(record.get("key"), str)
    }
    expected_equivalent_keys = {
        key for key, record in outputs_by_key.items() if record.get("scan_equivalent_to")
    }
    actual_equivalent_keys = {
        record.get("key") for record in equivalent_records if isinstance(record, dict)
    }
    if actual_equivalent_keys != expected_equivalent_keys:
        fail("application image equivalence key set is incomplete")
    for record in equivalent_records:
        if not isinstance(record, dict):
            fail("invalid application image equivalence record")
        key = record.get("key")
        representative_key = outputs_by_key[key].get("scan_equivalent_to")
        if (
            key not in roles
            or record.get("status") != "passed"
            or record.get("image_id") != roles[key]["source_daemon_image_id"]
            or representative_key != "api"
            or record.get("representative_key") != representative_key
            or record.get("reference") != outputs_by_key[key]["reference"]
            or record.get("representative_reference") != outputs_by_key["api"]["reference"]
            or record.get("representative_image_id")
            != by_key["api"]["source_daemon_image_id"]
        ):
            fail(f"bundled worker alias lacks matching scan equivalence: {key}")

    return {
        "path": scan_index_relative,
        "schema_version": SCAN_INDEX_SCHEMA,
        "sha256": sha256_file(scan_path),
        "status": "passed",
        "scope": "release",
        "generated_at_utc": index["generated_at_utc"],
        "config_image_ids": {
            key: by_key[key]["config_image_id"] for key in sorted(by_key)
        },
        "archive_sha256": {
            key: by_key[key]["archive_sha256"] for key in sorted(by_key)
        },
        "source_daemon_image_ids": {
            key: by_key[key]["source_daemon_image_id"] for key in sorted(by_key)
        },
        "lock_sha256": lock_sha256,
        "allowlist_sha256": allowlist_sha256,
        "platform": expected_platform,
        "integrity_posture": "checksums_are_integrity_evidence_not_authenticity",
    }


def read_image_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        fields = line.split("\t")
        if len(fields) != 8:
            fail(f"invalid image record line {number}")
        (
            archive,
            role,
            reference,
            source_reference,
            source_daemon_image_id,
            image_id,
            required,
            primary,
        ) = fields
        safe_relative(archive)
        if not re.fullmatch(r"[a-z0-9_]+", role):
            fail(f"invalid image role on line {number}")
        if any(ord(char) < 32 for char in reference + source_reference):
            fail(f"invalid image reference on line {number}")
        if not IMAGE_ID_RE.fullmatch(image_id) or not IMAGE_ID_RE.fullmatch(
            source_daemon_image_id
        ):
            fail(f"invalid image ID on line {number}")
        if required not in {"0", "1"} or primary not in {"0", "1"}:
            fail(f"invalid boolean image field on line {number}")
        records.append(
            {
                "archive": archive,
                "role": role,
                "reference": reference,
                "source_reference": source_reference,
                "source_daemon_image_id": source_daemon_image_id,
                "expected_image_id": image_id,
                "required": required == "1",
                "primary": primary == "1",
            }
        )
    if not records:
        fail("image records are empty")
    return records


def validate_finalization_scan_index(
    index: Any, image_lock: dict[str, Any], image_lock_path: Path
) -> list[dict[str, Any]]:
    if not isinstance(index, dict) or set(index) != SCAN_INDEX_TOP_KEYS:
        fail("scan index has an unexpected schema for image-record finalization")
    if (
        index["contract_version"] != SCAN_INDEX_SCHEMA
        or index["status"] != "passed"
        or index["scope"] != "release"
        or index["release_gate"] is not True
    ):
        fail("scan index is not a complete passed release gate for finalization")
    release_platform = index["release_platform"]
    if release_platform not in {"linux/amd64", "linux/arm64"}:
        fail("scan index has an invalid release platform for finalization")
    parse_utc_timestamp(index["generated_at_utc"], "finalization scan index generated_at_utc")

    allowlist_path = image_lock_path.parent / Path(CANONICAL_ALLOWLIST_PATH).name
    if (
        index["lock_path"] != CANONICAL_IMAGE_LOCK_PATH
        or index["lock_sha256"] != sha256_file(image_lock_path)
        or index["allowlist_path"] != CANONICAL_ALLOWLIST_PATH
        or index["allowlist_sha256"] != sha256_file(allowlist_path)
    ):
        fail("scan index policy hashes are invalid for image-record finalization")

    expected_keys = {
        item["key"] for item in application_images(image_lock)
    } | {item["key"] for item in external_images(image_lock)}
    if index["required_image_keys"] != sorted(expected_keys):
        fail("scan index required image keys are invalid for finalization")
    images = index["images"]
    if not isinstance(images, list) or len(images) != len(expected_keys):
        fail("scan index has no complete image records for finalization")
    actual_keys: set[str] = set()
    for scan in images:
        if not isinstance(scan, dict) or set(scan) != SCAN_INDEX_IMAGE_KEYS:
            fail("scan index has an invalid image record for finalization")
        key = scan["image_key"]
        if key in actual_keys or key not in expected_keys:
            fail("scan index image keys are invalid for finalization")
        actual_keys.add(key)
        if (
            scan["status"] != "passed"
            or scan["platform"] != release_platform
            or scan["unallowlisted_blocking_finding_count"] != 0
            or not SHA256_RE.fullmatch(str(scan["receipt_sha256"]))
        ):
            fail(f"scan index image is not a passed release record for finalization: {key}")
    if actual_keys != expected_keys:
        fail("scan index image key set is incomplete for finalization")
    return images


def finalize_image_records(
    *, image_lock_path: Path, scan_index_path: Path, input_path: Path, output_path: Path
) -> None:
    image_lock = load_image_lock(image_lock_path)
    try:
        index = json.loads(scan_index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"invalid scan index for image-record finalization: {exc}")
    images = validate_finalization_scan_index(index, image_lock, image_lock_path)
    records = read_image_records(input_path)
    scans: dict[str, dict[str, Any]] = {}
    for scan in images:
        if not isinstance(scan, dict) or not isinstance(scan.get("image_key"), str):
            fail("scan index has an invalid image record for finalization")
        key = scan["image_key"]
        if key in scans:
            fail(f"scan index duplicates image key during finalization: {key}")
        if (
            not IMAGE_ID_RE.fullmatch(str(scan.get("config_image_id", "")))
            or not IMAGE_ID_RE.fullmatch(str(scan.get("source_daemon_image_id", "")))
            or not SHA256_RE.fullmatch(str(scan.get("archive_sha256", "")))
        ):
            fail(f"scan index lacks portable/source image IDs for {key}")
        scans[key] = scan

    outputs = {
        item["key"]: item
        for item in image_lock.get("application_outputs", [])
        if isinstance(item, dict) and isinstance(item.get("key"), str)
    }
    externals = {item["key"]: item for item in external_images(image_lock)}
    finalized: list[str] = []
    for record in records:
        role = record["role"]
        if role.startswith("external_"):
            key = role.removeprefix("external_")
            external = externals.get(key)
            if (
                external is None
                or record["reference"] != external["release_reference"]
                or record["source_reference"] != external["reference"]
            ):
                fail(f"external image record does not match lock during finalization: {role}")
            expected_scan_reference = external["reference"]
            expected_archive_reference = external["release_reference"]
        else:
            output = outputs.get(role)
            if output is None or record["source_reference"] != output.get("reference"):
                fail(f"application image record does not match lock during finalization: {role}")
            key = str(output.get("scan_equivalent_to") or role)
            representative = outputs.get(key)
            if representative is None:
                fail(f"application image has no scan representative: {role}")
            expected_scan_reference = representative.get("reference")
            expected_archive_reference = representative.get("reference")
        scan = scans.get(key)
        if scan is None:
            fail(f"image record has no matching release scan: {role}")
        if (
            scan.get("requested_reference") != expected_scan_reference
            or scan.get("archive_reference") != expected_archive_reference
            or scan.get("source_daemon_image_id") != record["source_daemon_image_id"]
        ):
            fail(f"image record source identity drifted during scan: {role}")
        finalized.append(
            "\t".join(
                (
                    record["archive"],
                    role,
                    record["reference"],
                    record["source_reference"],
                    record["source_daemon_image_id"],
                    str(scan["config_image_id"]),
                    "1" if record["required"] else "0",
                    "1" if record["primary"] else "0",
                )
            )
        )
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            delete=False,
        ) as handle:
            handle.write("\n".join(finalized) + "\n")
            temporary_path = Path(handle.name)
        os.replace(temporary_path, output_path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def create_manifest(args: argparse.Namespace) -> None:
    source_root = Path(args.source_root).resolve()
    bundle_root = Path(args.bundle_root).resolve()
    if args.image_lock != CANONICAL_IMAGE_LOCK_PATH:
        fail("formal release bundles require the canonical production image lock")
    image_lock_path = source_root / args.image_lock
    image_lock = load_image_lock(image_lock_path)
    records = read_image_records(Path(args.image_records))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["archive"]].append(record)

    archives: list[dict[str, Any]] = []
    for archive_path in sorted(grouped):
        payload = file_record(bundle_root, archive_path)
        images = []
        for record in grouped[archive_path]:
            images.append(
                {
                    "role": record["role"],
                    "reference": record["reference"],
                    "source_reference": record["source_reference"],
                    "source_daemon_image_id": record["source_daemon_image_id"],
                    "expected_image_id": record["expected_image_id"],
                    "primary": record["primary"],
                }
            )
        archives.append(
            {
                **payload,
                "required": all(record["required"] for record in grouped[archive_path]),
                "images": images,
            }
        )

    # datetime.UTC does not exist on the remote verifier's Python 3.9 floor.
    created_at = (
        dt.datetime.now(dt.timezone.utc)  # noqa: UP017
        .replace(microsecond=0)
        .isoformat()
    )
    scan_evidence = validate_scan_evidence(
        bundle_root,
        image_lock,
        archives,
        args.image_platform,
        args.scan_index,
        parse_utc_timestamp(created_at, "manifest created_at_utc"),
    )

    payload_files = [
        file_record(bundle_root, relative)
        for relative in regular_files(bundle_root, exclude={MANIFEST_NAME, CHECKSUMS_NAME})
    ]
    secret_ids = sorted(filter(None, args.buildkit_secret_ids.split(",")))
    if not set(secret_ids).issubset(ALLOWED_SECRET_IDS):
        fail("unknown BuildKit secret ID")
    if args.source_inputs_file:
        source_inputs = json.loads(Path(args.source_inputs_file).read_text(encoding="utf-8"))
        validate_source_inputs(source_inputs)
    else:
        source_inputs = source_input_groups(source_root)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": created_at,
        "source": {
            "revision": args.revision,
            "tree": args.tree,
            "branch": args.branch,
            "git_clean_required": True,
        },
        "build": {
            "image_platform": args.image_platform,
            "package_extras": args.package_extras,
            "gzip_level": args.gzip_level,
            "frontend_included": args.frontend_included == "1",
            "external_images_included": args.external_images_included == "1",
            "buildkit_secret_ids": secret_ids,
        },
        "production_image_lock": {
            "path": args.image_lock,
            "schema_version": image_lock["schema_version"],
            "sha256": sha256_file(image_lock_path),
            "resolved_from_revision": image_lock.get("resolved_from_revision", ""),
        },
        "production_image_scan": scan_evidence,
        "source_inputs": source_inputs,
        "archives": archives,
        "payload_files": payload_files,
        "checksum_table": {
            "path": CHECKSUMS_NAME,
            "format": "sha256-two-space-v1",
            "covers": "all_regular_payload_files_except_itself",
        },
    }
    if not REVISION_RE.fullmatch(args.revision) or not REVISION_RE.fullmatch(args.tree):
        fail("revision and tree must be full hexadecimal object IDs")
    manifest_path = bundle_root / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    checksum_paths = regular_files(bundle_root, exclude={CHECKSUMS_NAME})
    checksum_lines = [
        f"{sha256_file(ensure_plain_file(bundle_root, path))}  {path}" for path in checksum_paths
    ]
    (bundle_root / CHECKSUMS_NAME).write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    verify_directory(bundle_root, post_load=False)


def parse_checksum_table(path: Path) -> dict[str, str]:
    return parse_checksum_text(path.read_text(encoding="utf-8"))


def parse_checksum_text(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None:
            fail(f"invalid SHA256SUMS line {number}")
        digest, relative = match.groups()
        relative = safe_relative(relative)
        if relative in entries:
            fail(f"duplicate SHA256SUMS path: {relative}")
        entries[relative] = digest
    return entries


def validate_source_inputs(inputs: Any) -> None:
    if not isinstance(inputs, list):
        fail("source_inputs must be a list")
    names: set[str] = set()
    paths: set[str] = set()
    for group in inputs:
        if not isinstance(group, dict) or set(group) != {"name", "sha256", "files"}:
            fail("invalid source input group")
        name = group["name"]
        if name in names or not isinstance(name, str):
            fail("duplicate or invalid source input name")
        names.add(name)
        if not SHA256_RE.fullmatch(group["sha256"]):
            fail(f"invalid source input digest: {name}")
        files = group["files"]
        if not isinstance(files, list) or not files:
            fail(f"empty source input group: {name}")
        for record in files:
            validate_payload_record(record)
            relative = record["path"]
            if relative in paths:
                fail(f"duplicate source input path across groups: {relative}")
            paths.add(relative)
        if tree_digest(files) != group["sha256"]:
            fail(f"source input aggregate digest mismatch: {name}")
    if names != REQUIRED_SOURCE_INPUTS:
        fail("source input group set is incomplete")


def validate_payload_record(record: Any) -> None:
    if not isinstance(record, dict) or set(record) != {"path", "sha256", "size"}:
        fail("invalid payload file record")
    safe_relative(record["path"])
    if not isinstance(record["sha256"], str) or not SHA256_RE.fullmatch(record["sha256"]):
        fail(f"invalid payload digest: {record.get('path')}")
    if not isinstance(record["size"], int) or record["size"] < 0:
        fail(f"invalid payload size: {record.get('path')}")


def loaded_image_id(reference: str, role: str) -> str:
    try:
        completed = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", reference],
            text=True,
            capture_output=True,
        )
    except OSError as exc:
        fail(f"cannot inspect loaded image for {role}: {exc}")
    actual_id = completed.stdout.strip()
    if completed.returncode != 0 or not IMAGE_ID_RE.fullmatch(actual_id):
        fail(f"loaded image is missing or has an invalid daemon ID for {role}")
    return actual_id


def verify_loaded_images(archives: list[dict[str, Any]], expected_platform: str) -> None:
    with tempfile.TemporaryDirectory(prefix="npcink-loaded-image-verify-") as temp:
        temp_root = Path(temp)
        for position, archive in enumerate(archives):
            primary = next(image for image in archive["images"] if image["primary"])
            primary_id = loaded_image_id(primary["reference"], primary["role"])
            saved_archive = temp_root / f"image-{position}.tar"
            try:
                completed = subprocess.run(
                    [
                        "docker",
                        "image",
                        "save",
                        "--output",
                        str(saved_archive),
                        primary["reference"],
                    ],
                    text=True,
                    capture_output=True,
                )
            except OSError as exc:
                fail(f"cannot save loaded image for {primary['role']}: {exc}")
            if completed.returncode != 0:
                fail(f"cannot save loaded image for {primary['role']}")
            if (
                saved_archive.is_symlink()
                or not saved_archive.is_file()
                or saved_archive.stat().st_size > MAX_DOCKER_ARCHIVE_BYTES
            ):
                fail(f"loaded Docker archive is invalid for {primary['role']}")
            subject = docker_archive_subject(
                saved_archive, archive_reference=primary["reference"]
            )
            if subject != {
                "config_image_id": primary["expected_image_id"],
                "platform": expected_platform,
            }:
                fail(f"loaded Docker archive identity mismatch for {primary['role']}")
            for image in archive["images"]:
                if image["primary"]:
                    continue
                alias_id = loaded_image_id(image["reference"], image["role"])
                if alias_id != primary_id:
                    fail(f"loaded image alias mismatch for {image['role']}")


def verify_directory(root: Path, *, post_load: bool) -> None:
    root = root.resolve()
    manifest_path = ensure_plain_file(root, MANIFEST_NAME)
    checksum_path = ensure_plain_file(root, CHECKSUMS_NAME)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid release bundle manifest JSON: {exc}")
    expected_top = {
        "schema_version",
        "created_at_utc",
        "source",
        "build",
        "production_image_lock",
        "production_image_scan",
        "source_inputs",
        "archives",
        "payload_files",
        "checksum_table",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_top:
        fail("release bundle manifest has an unexpected top-level schema")
    if manifest["schema_version"] != SCHEMA_VERSION:
        fail("unsupported release bundle manifest schema")
    bundle_created_at = parse_utc_timestamp(
        manifest["created_at_utc"], "manifest created_at_utc"
    )
    source = manifest["source"]
    if not isinstance(source, dict) or set(source) != {
        "revision",
        "tree",
        "branch",
        "git_clean_required",
    }:
        fail("invalid source identity schema")
    if not REVISION_RE.fullmatch(source["revision"]) or not REVISION_RE.fullmatch(source["tree"]):
        fail("invalid source revision or tree")
    if source["git_clean_required"] is not True:
        fail("invalid source clean/branch posture")
    validate_branch(source["branch"])
    build = manifest["build"]
    build_keys = {
        "image_platform",
        "package_extras",
        "gzip_level",
        "frontend_included",
        "external_images_included",
        "buildkit_secret_ids",
    }
    if not isinstance(build, dict) or set(build) != build_keys:
        fail("invalid build metadata schema")
    if not isinstance(build["frontend_included"], bool) or not isinstance(
        build["external_images_included"], bool
    ):
        fail("invalid bundle include flags")
    if not isinstance(build["gzip_level"], int) or not 1 <= build["gzip_level"] <= 9:
        fail("invalid bundle gzip level")
    if build["image_platform"] not in {"linux/amd64", "linux/arm64"}:
        fail("invalid or unresolved image platform")
    if build["package_extras"] not in {"", "[zilliz]"}:
        fail("invalid production package extras")
    if not isinstance(build["buildkit_secret_ids"], list) or not set(
        build["buildkit_secret_ids"]
    ).issubset(ALLOWED_SECRET_IDS):
        fail("invalid BuildKit secret ID metadata")
    lock_meta = manifest["production_image_lock"]
    if not isinstance(lock_meta, dict) or set(lock_meta) != {
        "path",
        "schema_version",
        "sha256",
        "resolved_from_revision",
    }:
        fail("invalid production image-lock metadata")
    if lock_meta["path"] != CANONICAL_IMAGE_LOCK_PATH:
        fail("production image-lock path is not canonical")
    lock_path = ensure_plain_file(root, CANONICAL_IMAGE_LOCK_PATH)
    if (
        lock_meta["schema_version"] != IMAGE_LOCK_SCHEMA
        or sha256_file(lock_path) != lock_meta["sha256"]
        or not REVISION_RE.fullmatch(str(lock_meta["resolved_from_revision"]))
    ):
        fail("production image-lock hash/schema mismatch")
    image_lock = load_image_lock(lock_path)
    validate_source_inputs(manifest["source_inputs"])

    payload_records = manifest["payload_files"]
    if not isinstance(payload_records, list):
        fail("payload_files must be a list")
    payload_by_path: dict[str, dict[str, Any]] = {}
    for record in payload_records:
        validate_payload_record(record)
        relative = record["path"]
        if relative in payload_by_path or relative in {MANIFEST_NAME, CHECKSUMS_NAME}:
            fail(f"duplicate or reserved payload path: {relative}")
        payload_by_path[relative] = record
        actual = file_record(root, relative)
        if actual != record:
            fail(f"payload hash/size mismatch: {relative}")

    source_records = {
        record["path"]: record for group in manifest["source_inputs"] for record in group["files"]
    }
    for relative in sorted(set(source_records) & set(payload_by_path)):
        if source_records[relative] != payload_by_path[relative]:
            fail(f"source input and bundled payload disagree: {relative}")

    actual_files = set(regular_files(root))
    expected_files = set(payload_by_path) | {MANIFEST_NAME, CHECKSUMS_NAME}
    if actual_files != expected_files:
        fail("bundle payload file set does not match manifest")
    checksums = parse_checksum_table(checksum_path)
    expected_checksums = expected_files - {CHECKSUMS_NAME}
    if set(checksums) != expected_checksums:
        fail("SHA256SUMS does not cover the complete payload file set")
    for relative, digest in checksums.items():
        if sha256_file(ensure_plain_file(root, relative)) != digest:
            fail(f"SHA256SUMS mismatch: {relative}")

    checksum_meta = manifest["checksum_table"]
    if checksum_meta != {
        "path": CHECKSUMS_NAME,
        "format": "sha256-two-space-v1",
        "covers": "all_regular_payload_files_except_itself",
    }:
        fail("invalid checksum-table schema")

    archives = manifest["archives"]
    if not isinstance(archives, list) or not archives:
        fail("archives must be a non-empty list")
    roles: dict[str, dict[str, Any]] = {}
    archive_paths: set[str] = set()
    for archive in archives:
        expected_archive_keys = {"path", "sha256", "size", "required", "images"}
        if not isinstance(archive, dict) or set(archive) != expected_archive_keys:
            fail("invalid archive record")
        validate_payload_record({key: archive[key] for key in ("path", "sha256", "size")})
        if archive["path"] in archive_paths or archive["path"] not in payload_by_path:
            fail("duplicate or missing archive payload")
        archive_paths.add(archive["path"])
        if archive["required"] is not True:
            fail("all recorded release archives must be required")
        if payload_by_path[archive["path"]] != {
            key: archive[key] for key in ("path", "sha256", "size")
        }:
            fail(f"archive payload metadata mismatch: {archive['path']}")
        images = archive["images"]
        if not isinstance(images, list) or not images:
            fail("archive has no image records")
        primary_count = 0
        for image in images:
            if not isinstance(image, dict) or set(image) != {
                "role",
                "reference",
                "source_reference",
                "source_daemon_image_id",
                "expected_image_id",
                "primary",
            }:
                fail("invalid archive image record")
            role = image["role"]
            if role in roles or not isinstance(role, str) or not re.fullmatch(r"[a-z0-9_]+", role):
                fail("duplicate or invalid image role")
            if not isinstance(image["reference"], str) or not isinstance(
                image["source_reference"], str
            ) or any(
                ord(char) < 32 for char in image["reference"] + image["source_reference"]
            ):
                fail(f"invalid image reference: {role}")
            if not IMAGE_ID_RE.fullmatch(image["expected_image_id"]) or not IMAGE_ID_RE.fullmatch(
                image["source_daemon_image_id"]
            ):
                fail(f"invalid expected image ID: {role}")
            if not isinstance(image["primary"], bool):
                fail(f"invalid primary image marker: {role}")
            primary_count += int(image["primary"])
            roles[role] = {**image, "archive": archive["path"]}
        if primary_count != 1:
            fail(f"archive must have exactly one primary image: {archive['path']}")

    application_outputs = image_lock.get("application_outputs")
    if not isinstance(application_outputs, list):
        fail("production image lock has no application_outputs list")
    locked_outputs = {
        item["key"]: item
        for item in application_outputs
        if isinstance(item, dict) and isinstance(item.get("key"), str)
    }
    if len(locked_outputs) != len(application_outputs):
        fail("production image lock has invalid or duplicate application outputs")
    locked_applications = {item["key"]: item for item in application_images(image_lock)}
    locked_external = {item["key"]: item for item in external_images(image_lock)}
    expected_roles = set(locked_outputs) | {
        f"external_{key}" for key in locked_external
    }
    if set(roles) != expected_roles:
        fail("release bundle image role set does not exactly match production image lock")
    expected_archive_paths = {
        item["archive"] for item in locked_applications.values()
    } | {item["archive"] for item in locked_external.values()}
    if archive_paths != expected_archive_paths:
        fail("release bundle archive path set does not exactly match production image lock")

    for key, output in locked_outputs.items():
        reference = output.get("reference")
        representative_key = output.get("scan_equivalent_to")
        if representative_key is None:
            representative = locked_applications.get(key)
            expected_primary = True
        else:
            representative = locked_applications.get(representative_key)
            expected_primary = False
        record = roles[key]
        if (
            not isinstance(reference, str)
            or representative is None
            or record["reference"] != reference
            or record["source_reference"] != reference
            or record["archive"] != representative["archive"]
            or record["primary"] is not expected_primary
        ):
            fail(f"application image archive set does not match production image lock: {key}")

    api_roles = {"api", "worker", "callback_worker", "ops_worker"}
    if not api_roles.issubset(roles):
        fail("API archive role set is incomplete")
    api_archive = roles["api"]["archive"]
    if any(roles[role]["archive"] != api_archive for role in api_roles):
        fail("workers must reuse the exact API archive")
    if any(
        roles[role]["expected_image_id"] != roles["api"]["expected_image_id"] for role in api_roles
    ):
        fail("worker aliases must reuse the exact API image ID")
    if any(
        roles[role]["source_daemon_image_id"] != roles["api"]["source_daemon_image_id"]
        for role in api_roles
    ):
        fail("worker aliases must reuse the exact API source daemon image ID")
    if build["frontend_included"] != ("frontend" in roles):
        fail("frontend include flag does not match archives")
    if build["frontend_included"] is not True:
        fail("complete exact release bundles must include the frontend image")

    bundled_external = {
        role.removeprefix("external_"): record
        for role, record in roles.items()
        if role.startswith("external_")
    }
    if build["external_images_included"] is not True:
        fail("exact offline release bundles must include every external image")
    if set(bundled_external) != set(locked_external):
        fail("external image archive set does not match production image lock")
    for key, record in bundled_external.items():
        if (
            record["reference"] != locked_external[key]["release_reference"]
            or record["source_reference"] != locked_external[key]["reference"]
            or record["archive"] != locked_external[key]["archive"]
            or record["primary"] is not True
        ):
            fail(f"external image reference drift: {key}")

    scan_meta = validate_scan_evidence(
        root,
        image_lock,
        archives,
        build["image_platform"],
        bundle_created_at=bundle_created_at,
    )
    if manifest["production_image_scan"] != scan_meta:
        fail("production image scan metadata does not match bundled scan evidence")

    if post_load:
        verify_loaded_images(archives, build["image_platform"])


def emit_image_plan(root: Path, *, aliases: bool) -> None:
    verify_directory(root, post_load=False)
    manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    for archive in manifest["archives"]:
        primary = next(image for image in archive["images"] if image["primary"])
        if aliases:
            for image in archive["images"]:
                if not image["primary"]:
                    print(f"{primary['reference']}\t{image['reference']}")
        else:
            print(f"{archive['path']}\t{primary['role']}\t{primary['reference']}")


def verify_archive(bundle: Path, checksum: Path) -> dict[str, Any]:
    expected_line = checksum.read_text(encoding="utf-8").strip()
    match = re.fullmatch(r"([0-9a-f]{64})  ([^/\r\n]+)", expected_line)
    if match is None or match.group(2) != bundle.name:
        fail("invalid outer bundle checksum file")
    if sha256_file(bundle) != match.group(1):
        fail("outer bundle checksum mismatch")
    with tarfile.open(bundle, "r:gz") as archive:
        member_by_name: dict[str, tarfile.TarInfo] = {}
        total_size = 0
        member_count = 0
        for member in archive:
            member_count += 1
            if member_count > MAX_TAR_MEMBERS:
                fail("release bundle exceeds the tar member limit")
            name = safe_relative(member.name)
            if name in member_by_name:
                fail(f"duplicate tar member: {name}")
            if not member.isfile():
                fail(f"release bundle permits regular tar members only: {name}")
            member_by_name[name] = member
            total_size += member.size
            if total_size > MAX_TAR_UNCOMPRESSED_BYTES:
                fail("release bundle exceeds the uncompressed byte limit")
        manifest_member = member_by_name.get(MANIFEST_NAME)
        checksum_member = member_by_name.get(CHECKSUMS_NAME)
        if manifest_member is None or checksum_member is None:
            fail("required bundle metadata member is missing")
        if manifest_member.size > MAX_MANIFEST_BYTES or checksum_member.size > MAX_MANIFEST_BYTES:
            fail("release bundle metadata exceeds the byte limit")
        manifest_stream = archive.extractfile(manifest_member)
        checksum_stream = archive.extractfile(checksum_member)
        if manifest_stream is None or checksum_stream is None:
            fail("release bundle metadata cannot be read")
        try:
            manifest_bytes = manifest_stream.read(MAX_MANIFEST_BYTES + 1)
            checksum_bytes = checksum_stream.read(MAX_MANIFEST_BYTES + 1)
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            checksum_entries = parse_checksum_text(checksum_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            fail(f"release bundle metadata is invalid: {exc}")
        if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
            fail("unsupported release bundle manifest schema")
        payload_records = manifest.get("payload_files")
        if not isinstance(payload_records, list):
            fail("release bundle manifest has no payload file list")
        expected_sizes: dict[str, int] = {}
        for record in payload_records:
            validate_payload_record(record)
            relative = record["path"]
            if relative in expected_sizes or relative in {MANIFEST_NAME, CHECKSUMS_NAME}:
                fail(f"duplicate or reserved payload path: {relative}")
            expected_sizes[relative] = record["size"]
        expected_members = set(expected_sizes) | {MANIFEST_NAME, CHECKSUMS_NAME}
        if set(member_by_name) != expected_members:
            fail("tar member set does not exactly match the release manifest")
        for relative, size in expected_sizes.items():
            if member_by_name[relative].size != size:
                fail(f"tar member size does not match manifest: {relative}")
        expected_checksum_paths = expected_members - {CHECKSUMS_NAME}
        if set(checksum_entries) != expected_checksum_paths:
            fail("tar SHA256SUMS does not cover the exact member set")

        with tempfile.TemporaryDirectory(prefix="npcink-release-bundle-verify-") as temp:
            temp_root = Path(temp)
            for relative, member in member_by_name.items():
                source = archive.extractfile(member)
                if source is None:
                    fail(f"tar member cannot be read: {relative}")
                destination = temp_root.joinpath(*PurePosixPath(relative).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                written = 0
                with destination.open("wb") as output:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        digest.update(chunk)
                        output.write(chunk)
                if written != member.size:
                    fail(f"tar member extracted size mismatch: {relative}")
                if relative != CHECKSUMS_NAME and digest.hexdigest() != checksum_entries[relative]:
                    fail(f"tar member hash mismatch: {relative}")
                destination.chmod(member.mode & 0o777)
            verify_directory(temp_root, post_load=False)
    return manifest


def pack_bundle(root: Path, output: Path, gzip_level: int, mtime: int) -> None:
    verify_directory(root, post_load=False)
    files = regular_files(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output.with_name(f".{output.name}.tmp-{os.getpid()}")
    try:
        with temp_output.open("wb") as raw:
            with gzip.GzipFile(
                filename="", mode="wb", compresslevel=gzip_level, mtime=0, fileobj=raw
            ) as compressed:
                with tarfile.open(
                    fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT
                ) as archive:
                    for relative in files:
                        path = ensure_plain_file(root, relative)
                        info = tarfile.TarInfo(relative)
                        info.size = path.stat().st_size
                        info.mode = 0o755 if os.access(path, os.X_OK) else 0o644
                        info.mtime = mtime
                        info.uid = 0
                        info.gid = 0
                        info.uname = "root"
                        info.gname = "root"
                        with path.open("rb") as handle:
                            archive.addfile(info, handle)
        os.replace(temp_output, output)
    finally:
        temp_output.unlink(missing_ok=True)


def write_outer_checksum(bundle: Path, output: Path) -> None:
    output.write_text(f"{sha256_file(bundle)}  {bundle.name}\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("external-plan")
    plan.add_argument("--image-lock", required=True)
    plan.add_argument("--output", required=True)
    application_plan = subparsers.add_parser("application-plan")
    application_plan.add_argument("--image-lock", required=True)
    application_plan.add_argument("--output", required=True)
    finalize_records = subparsers.add_parser("finalize-image-records")
    finalize_records.add_argument("--image-lock", required=True)
    finalize_records.add_argument("--scan-index", required=True)
    finalize_records.add_argument("--input", required=True)
    finalize_records.add_argument("--output", required=True)
    inputs = subparsers.add_parser("source-inputs")
    inputs.add_argument("--source-root", required=True)
    inputs.add_argument("--output", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--source-root", required=True)
    create.add_argument("--source-inputs-file", default="")
    create.add_argument("--bundle-root", required=True)
    create.add_argument("--revision", required=True)
    create.add_argument("--tree", required=True)
    create.add_argument("--branch", required=True)
    create.add_argument("--image-platform", default="")
    create.add_argument("--package-extras", default="")
    create.add_argument("--gzip-level", type=int, required=True)
    create.add_argument("--frontend-included", choices=("0", "1"), required=True)
    create.add_argument("--external-images-included", choices=("0", "1"), required=True)
    create.add_argument("--buildkit-secret-ids", default="")
    create.add_argument("--image-lock", required=True)
    create.add_argument("--scan-index", default=SCAN_INDEX_PATH)
    create.add_argument("--image-records", required=True)
    verify = subparsers.add_parser("verify-directory")
    verify.add_argument("--root", required=True)
    verify.add_argument("--post-load", action="store_true")
    load_plan = subparsers.add_parser("load-plan")
    load_plan.add_argument("--root", required=True)
    alias_plan = subparsers.add_parser("alias-plan")
    alias_plan.add_argument("--root", required=True)
    archive = subparsers.add_parser("verify-archive")
    archive.add_argument("--bundle", required=True)
    archive.add_argument("--checksum", required=True)
    archive_platform = subparsers.add_parser("archive-platform")
    archive_platform.add_argument("--bundle", required=True)
    archive_platform.add_argument("--checksum", required=True)
    pack = subparsers.add_parser("pack")
    pack.add_argument("--root", required=True)
    pack.add_argument("--output", required=True)
    pack.add_argument("--gzip-level", type=int, required=True)
    pack.add_argument("--mtime", type=int, required=True)
    checksum = subparsers.add_parser("checksum")
    checksum.add_argument("--bundle", required=True)
    checksum.add_argument("--output", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "external-plan":
            lock = load_image_lock(Path(args.image_lock))
            lines = [
                f"{item['key']}\t{item['reference']}\t{item['release_reference']}\t{item['archive']}"
                for item in external_images(lock)
            ]
            Path(args.output).write_text("\n".join(lines) + "\n", encoding="utf-8")
        elif args.command == "application-plan":
            lock = load_image_lock(Path(args.image_lock))
            lines = [
                "\t".join(
                    (item["key"], item["reference"], item["dockerfile"], item["archive"])
                )
                for item in application_images(lock)
                if item["key"] not in {"api", "frontend"}
            ]
            Path(args.output).write_text(
                "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
            )
        elif args.command == "finalize-image-records":
            finalize_image_records(
                image_lock_path=Path(args.image_lock),
                scan_index_path=Path(args.scan_index),
                input_path=Path(args.input),
                output_path=Path(args.output),
            )
        elif args.command == "source-inputs":
            groups = source_input_groups(Path(args.source_root).resolve())
            Path(args.output).write_text(
                json.dumps(groups, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        elif args.command == "create":
            create_manifest(args)
        elif args.command == "verify-directory":
            verify_directory(Path(args.root), post_load=args.post_load)
        elif args.command == "load-plan":
            emit_image_plan(Path(args.root).resolve(), aliases=False)
        elif args.command == "alias-plan":
            emit_image_plan(Path(args.root).resolve(), aliases=True)
        elif args.command == "verify-archive":
            verify_archive(Path(args.bundle), Path(args.checksum))
        elif args.command == "archive-platform":
            manifest = verify_archive(Path(args.bundle), Path(args.checksum))
            print(manifest["build"]["image_platform"])
        elif args.command == "pack":
            pack_bundle(Path(args.root), Path(args.output), args.gzip_level, args.mtime)
        elif args.command == "checksum":
            write_outer_checksum(Path(args.bundle), Path(args.output))
        return 0
    except (BundleError, OSError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        print(f"[fail] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
