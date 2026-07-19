#!/usr/bin/env python3
"""Verify the production image lock and evaluate immutable-image scan reports."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
import subprocess
import sys
import tarfile
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = ROOT / "deploy" / "image-lock" / "production-images.json"
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_ID_RE = DIGEST_RE
SEVERITY_ORDER = {
    "negligible": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}
UTC_ZONE = timezone(timedelta(0))
RECEIPT_CONTRACT = "npcink.production-image-scan-receipt.v1"
GRYPE_BUILTIN_IGNORE_RULES = [
    {
        "vulnerability": "",
        "include-aliases": False,
        "reason": "",
        "namespace": "",
        "fix-state": "",
        "package": {
            "name": "kernel-headers",
            "version": "",
            "language": "",
            "type": "rpm",
            "location": "",
            "upstream-name": "kernel",
        },
        "vex-status": "",
        "vex-justification": "",
        "match-type": "exact-indirect-match",
    },
    {
        "vulnerability": "",
        "include-aliases": False,
        "reason": "",
        "namespace": "",
        "fix-state": "",
        "package": {
            "name": "linux(-.*)?-headers-.*",
            "version": "",
            "language": "",
            "type": "deb",
            "location": "",
            "upstream-name": "linux.*",
        },
        "vex-status": "",
        "vex-justification": "",
        "match-type": "exact-indirect-match",
    },
    {
        "vulnerability": "",
        "include-aliases": False,
        "reason": "",
        "namespace": "",
        "fix-state": "",
        "package": {
            "name": "linux-libc-dev",
            "version": "",
            "language": "",
            "type": "deb",
            "location": "",
            "upstream-name": "linux",
        },
        "vex-status": "",
        "vex-justification": "",
        "match-type": "exact-indirect-match",
    },
]


class SupplyError(ValueError):
    """Raised when an image-supply contract fails closed."""


def _utc_now() -> datetime:
    return datetime.now(UTC_ZONE)


def _parse_utc_timestamp(value: object, field: str) -> datetime:
    timestamp = _required_text(value, field)
    if not timestamp.endswith("Z"):
        raise SupplyError(f"{field} must be an explicit UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(timestamp[:-1] + "+00:00")
    except ValueError as error:
        raise SupplyError(f"{field} must be a valid ISO-8601 UTC timestamp") from error
    if parsed.utcoffset() != timedelta(0):
        raise SupplyError(f"{field} must use UTC")
    return parsed


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise SupplyError(f"cannot read valid JSON from {path}: {error}") from error
    if not isinstance(payload, dict):
        raise SupplyError(f"expected JSON object in {path}")
    return payload


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SupplyError(f"{field} must be a non-empty string")
    return value


def _normalize_sha256(value: object, field: str) -> str:
    digest = _required_text(value, field)
    if re.fullmatch(r"[0-9a-f]{64}", digest):
        digest = f"sha256:{digest}"
    if not DIGEST_RE.fullmatch(digest):
        raise SupplyError(f"{field} must be an exact sha256 digest")
    return digest


def _docker_archive_subject(path: Path, *, archive_reference: str) -> dict[str, Any]:
    try:
        with tarfile.open(path, mode="r:*") as archive:
            manifest_member = archive.getmember("manifest.json")
            if not manifest_member.isfile():
                raise SupplyError("Docker archive manifest.json must be a regular file")
            manifest_stream = archive.extractfile(manifest_member)
            if manifest_stream is None:
                raise SupplyError("Docker archive manifest.json cannot be read")
            manifest = json.loads(manifest_stream.read())
            if not isinstance(manifest, list) or len(manifest) != 1:
                raise SupplyError("Docker archive manifest must contain exactly one image")
            entry = manifest[0]
            if not isinstance(entry, dict) or set(entry) != {"Config", "RepoTags", "Layers"}:
                raise SupplyError("Docker archive manifest entry has unknown or missing fields")
            config_name = _required_text(entry.get("Config"), "docker_archive.Config")
            config_match = re.fullmatch(
                r"(?:blobs/sha256/)?([0-9a-f]{64})(?:[.]json)?", config_name
            )
            if config_match is None:
                raise SupplyError("Docker archive Config is not an exact sha256 object")
            repo_tags = entry.get("RepoTags")
            if not isinstance(repo_tags, list) or not all(
                isinstance(tag, str) and tag for tag in repo_tags
            ):
                raise SupplyError("Docker archive RepoTags must be a non-empty string array")
            if repo_tags != [archive_reference]:
                raise SupplyError(
                    "Docker archive RepoTags must be the exact singleton archive reference "
                    f"[{archive_reference!r}]"
                )
            layers = entry.get("Layers")
            if not isinstance(layers, list) or not layers or not all(
                isinstance(layer, str) and layer for layer in layers
            ):
                raise SupplyError("Docker archive Layers must be a non-empty string array")
            for layer in layers:
                member = archive.getmember(layer)
                if not member.isfile():
                    raise SupplyError(f"Docker archive layer {layer!r} is not a regular file")
            config_member = archive.getmember(config_name)
            if not config_member.isfile():
                raise SupplyError("Docker archive Config must be a regular file")
            config_stream = archive.extractfile(config_member)
            if config_stream is None:
                raise SupplyError("Docker archive Config cannot be read")
            config_bytes = config_stream.read()
    except (KeyError, OSError, tarfile.TarError, json.JSONDecodeError) as error:
        raise SupplyError(f"cannot inspect Docker image archive {path}: {error}") from error

    config_hex = hashlib.sha256(config_bytes).hexdigest()
    if config_hex != config_match.group(1):
        raise SupplyError("Docker archive Config filename does not match its content digest")
    try:
        config = json.loads(config_bytes)
    except json.JSONDecodeError as error:
        raise SupplyError("Docker archive Config is not valid JSON") from error
    if not isinstance(config, dict):
        raise SupplyError("Docker archive Config must be a JSON object")
    os_name = _required_text(config.get("os"), "docker_archive.config.os")
    architecture = _required_text(
        config.get("architecture"), "docker_archive.config.architecture"
    )
    if architecture == "aarch64":
        architecture = "arm64"
    elif architecture == "x86_64":
        architecture = "amd64"
    return {
        "archive_sha256": _sha256(path),
        "config_image_id": f"sha256:{config_hex}",
        "platform": f"{os_name}/{architecture}",
        "repo_tags": sorted(repo_tags),
    }


def _base64_payload(value: object, field: str) -> bytes:
    encoded = _required_text(value, field)
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise SupplyError(f"{field} must be canonical base64") from error


def _validate_syft_subject(
    *,
    native: dict[str, Any],
    sbom: dict[str, Any],
    image_key: str,
    config_image_id: str,
    expected_syft_version: str,
) -> str:
    source = native.get("source")
    if not isinstance(source, dict) or source.get("type") != "image":
        raise SupplyError("Syft native source must describe an image")
    metadata = source.get("metadata")
    if not isinstance(metadata, dict):
        raise SupplyError("Syft native source metadata is missing")
    expected_filename = f"{image_key}.image.tar"
    user_input = _required_text(metadata.get("userInput"), "syft.source.metadata.userInput")
    if user_input.rsplit("/", 1)[-1] != expected_filename:
        raise SupplyError("Syft native source does not name the governed image archive")
    if metadata.get("imageID") != config_image_id:
        raise SupplyError("Syft native source imageID does not bind the archive Config digest")
    config_bytes = _base64_payload(metadata.get("config"), "syft.source.metadata.config")
    if f"sha256:{hashlib.sha256(config_bytes).hexdigest()}" != config_image_id:
        raise SupplyError("Syft native source config bytes do not bind the archive Config digest")
    subject_digest = _normalize_sha256(
        metadata.get("manifestDigest"), "syft.source.metadata.manifestDigest"
    )
    manifest_bytes = _base64_payload(metadata.get("manifest"), "syft.source.metadata.manifest")
    if f"sha256:{hashlib.sha256(manifest_bytes).hexdigest()}" != subject_digest:
        raise SupplyError("Syft native source manifest bytes do not bind its manifest digest")
    if (
        source.get("id") != subject_digest.split(":", 1)[1]
        or source.get("version") != subject_digest
    ):
        raise SupplyError("Syft native source identity does not bind its manifest digest")
    media_type = _required_text(metadata.get("mediaType"), "syft.source.metadata.mediaType")
    if media_type not in {
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
    }:
        raise SupplyError("Syft native source manifest media type is unsupported")
    try:
        config_payload = json.loads(config_bytes)
        manifest_payload = json.loads(manifest_bytes)
    except json.JSONDecodeError as error:
        raise SupplyError("Syft native source config/manifest payload is not valid JSON") from error
    if not isinstance(config_payload, dict) or not isinstance(manifest_payload, dict):
        raise SupplyError("Syft native source config/manifest payload must be an object")
    manifest_config = manifest_payload.get("config")
    manifest_layers = manifest_payload.get("layers")
    config_diff_ids = config_payload.get("rootfs", {}).get("diff_ids")
    if (
        not isinstance(manifest_config, dict)
        or manifest_config.get("digest") != config_image_id
        or manifest_config.get("size") != len(config_bytes)
        or not isinstance(manifest_layers, list)
        or not manifest_layers
        or not isinstance(config_diff_ids, list)
        or [layer.get("digest") for layer in manifest_layers if isinstance(layer, dict)]
        != config_diff_ids
        or len(manifest_layers) != len(config_diff_ids)
        or any(
            not isinstance(layer, dict)
            or not DIGEST_RE.fullmatch(str(layer.get("digest", "")))
            or not isinstance(layer.get("size"), int)
            or isinstance(layer.get("size"), bool)
            or layer["size"] < 0
            for layer in manifest_layers
        )
    ):
        raise SupplyError("Syft native manifest does not bind its config and layer identities")
    descriptor = native.get("descriptor")
    if (
        not isinstance(descriptor, dict)
        or descriptor.get("name") != "syft"
        or str(descriptor.get("version", "")).lstrip("v") != expected_syft_version
    ):
        raise SupplyError("Syft native descriptor does not match the locked scanner")

    if sbom.get("bomFormat") != "CycloneDX":
        raise SupplyError("SBOM must be CycloneDX JSON")
    sbom_component = sbom.get("metadata", {}).get("component")
    if (
        not isinstance(sbom_component, dict)
        or sbom_component.get("type") != "container"
        or sbom_component.get("version") != subject_digest
        or not isinstance(sbom_component.get("bom-ref"), str)
        or not sbom_component["bom-ref"]
    ):
        raise SupplyError("CycloneDX component does not bind the Syft subject manifest digest")
    tools = sbom.get("metadata", {}).get("tools", {}).get("components", [])
    sbom_syft_version = next(
        (
            str(tool.get("version", "")).lstrip("v")
            for tool in tools
            if isinstance(tool, dict) and tool.get("name") == "syft"
        ),
        "",
    )
    if sbom_syft_version != expected_syft_version:
        raise SupplyError("CycloneDX Syft version does not match the locked scanner")
    return subject_digest


def _validate_grype_configuration(descriptor: dict[str, Any], report: dict[str, Any]) -> None:
    configuration = descriptor.get("configuration")
    if not isinstance(configuration, dict):
        raise SupplyError("Grype report configuration is missing")
    expected_values = {
        "ignore": GRYPE_BUILTIN_IGNORE_RULES,
        "exclude": [],
        "only-fixed": False,
        "only-notfixed": False,
        "ignore-wontfix": "",
        "vex-documents": [],
        "vex-add": [],
        "show-suppressed": False,
        "search": {
            "scope": "squashed",
            "unindexed-archives": False,
            "indexed-archives": True,
        },
    }
    for field, expected in expected_values.items():
        if configuration.get(field) != expected:
            raise SupplyError(f"Grype configuration {field!r} can suppress governed findings")
    database = configuration.get("db")
    if (
        not isinstance(database, dict)
        or database.get("auto-update") is not False
        or database.get("validate-by-hash-on-start") is not True
        or database.get("validate-age") is not True
    ):
        raise SupplyError("Grype database runtime configuration is not frozen")
    ignored_matches = report.get("ignoredMatches")
    if ignored_matches not in (None, []):
        raise SupplyError("Grype report contains suppressed vulnerability matches")


def _validate_image_record(record: dict[str, Any], *, label: str) -> None:
    tag = _required_text(record.get("tag"), f"{label}.tag")
    digest = _required_text(record.get("digest"), f"{label}.digest")
    reference = _required_text(record.get("reference"), f"{label}.reference")
    if not DIGEST_RE.fullmatch(digest):
        raise SupplyError(f"{label}.digest is not an exact sha256 digest")
    if "@" in tag or tag.endswith(":latest") or ":" not in tag.rsplit("/", 1)[-1]:
        raise SupplyError(f"{label}.tag must be a versioned tag without a digest")
    if reference != f"{tag}@{digest}":
        raise SupplyError(f"{label}.reference must equal tag@digest")
    platforms = record.get("required_platforms")
    if not isinstance(platforms, list) or not all(isinstance(item, str) for item in platforms):
        raise SupplyError(f"{label}.required_platforms must be a string array")
    if not {"linux/amd64", "linux/arm64"}.issubset(set(platforms)):
        raise SupplyError(f"{label} must lock both linux/amd64 and linux/arm64")


def _dockerfile_external_froms(path: Path) -> list[str]:
    aliases: set[str] = set()
    external: list[str] = []
    for line in path.read_text().splitlines():
        match = re.match(r"^FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?\s*$", line, re.I)
        if match is None:
            continue
        reference, alias = match.groups()
        if reference not in aliases:
            external.append(reference)
        if alias:
            aliases.add(alias)
    return external


def _compose_images(path: Path) -> dict[str, str]:
    section = ""
    service = ""
    images: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        top = re.match(r"^([A-Za-z0-9_-]+):\s*$", raw_line)
        if top:
            section = top.group(1)
            service = ""
            continue
        if section != "services":
            continue
        service_match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", raw_line)
        if service_match:
            service = service_match.group(1)
            continue
        image_match = re.match(r"^    image:\s*[\"']?([^\"'\s]+)[\"']?\s*$", raw_line)
        if service and image_match:
            images[service] = image_match.group(1)
    return images


def _validate_allowlist_shape(
    payload: dict[str, Any], known_images: set[str], *, max_exception_days: int
) -> list[dict[str, str]]:
    if set(payload) != {"schema_version", "entries"}:
        raise SupplyError("CVE allowlist has unknown or missing top-level fields")
    if payload.get("schema_version") != "npcink.production-image-cve-allowlist.v1":
        raise SupplyError("unsupported CVE allowlist schema_version")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise SupplyError("CVE allowlist entries must be an array")
    if (
        not isinstance(max_exception_days, int)
        or isinstance(max_exception_days, bool)
        or max_exception_days < 1
        or max_exception_days > 90
    ):
        raise SupplyError("max_exception_days must be an integer between 1 and 90")

    required = {
        "image",
        "vulnerability_id",
        "package",
        "package_version",
        "owner",
        "reason",
        "expires_on",
    }
    entries: list[dict[str, str]] = []
    identities: set[tuple[str, str, str, str]] = set()
    today = _utc_now().date()
    for index, raw_entry in enumerate(raw_entries):
        if not isinstance(raw_entry, dict) or set(raw_entry) != required:
            raise SupplyError(f"allowlist entry {index} has unknown or missing fields")
        entry = {
            field: _required_text(raw_entry.get(field), f"entries[{index}].{field}")
            for field in required
        }
        if entry["image"] not in known_images:
            raise SupplyError(f"allowlist entry {index} names unknown image {entry['image']!r}")
        if len(entry["reason"]) < 12:
            raise SupplyError(f"allowlist entry {index} reason must contain at least 12 characters")
        try:
            expires_on = date.fromisoformat(entry["expires_on"])
        except ValueError as error:
            raise SupplyError(f"allowlist entry {index} expires_on must be YYYY-MM-DD") from error
        if expires_on < today:
            raise SupplyError(f"allowlist entry {index} expired on {expires_on.isoformat()}")
        if expires_on > today + timedelta(days=max_exception_days):
            raise SupplyError(
                f"allowlist entry {index} exceeds the {max_exception_days}-day maximum"
            )
        identity = (
            entry["image"],
            entry["vulnerability_id"],
            entry["package"],
            entry["package_version"],
        )
        if identity in identities:
            raise SupplyError(f"duplicate allowlist entry {identity!r}")
        identities.add(identity)
        entries.append(entry)
    return entries


def _lock_image_keys(lock: dict[str, Any]) -> set[str]:
    return {
        _required_text(record.get("key"), "image.key")
        for collection in ("production_inputs", "application_outputs")
        for record in lock.get(collection, [])
        if isinstance(record, dict)
    }


def _scan_targets(lock: dict[str, Any]) -> dict[str, dict[str, str]]:
    targets: dict[str, dict[str, str]] = {}
    for record in lock.get("application_outputs", []):
        if not isinstance(record, dict):
            continue
        key = _required_text(record.get("key"), "application_output.key")
        targets[key] = {
            "reference": _required_text(record.get("reference"), f"{key}.reference"),
            "archive_reference": _required_text(record.get("reference"), f"{key}.reference"),
            "kind": "application_output",
        }
    for record in lock.get("production_inputs", []):
        if not isinstance(record, dict) or record.get("kind") != "compose_external":
            continue
        key = _required_text(record.get("key"), "compose_external.key")
        targets[key] = {
            "reference": _required_text(record.get("reference"), f"{key}.reference"),
            "archive_reference": _required_text(
                record.get("release_reference"), f"{key}.release_reference"
            ),
            "kind": "compose_external",
        }
    return targets


def _release_scan_targets(lock: dict[str, Any]) -> dict[str, dict[str, str]]:
    all_targets = _scan_targets(lock)
    required_keys = {
        record["key"]
        for record in lock.get("application_outputs", [])
        if isinstance(record, dict) and record.get("scan_by_default")
    } | {
        record["key"]
        for record in lock.get("production_inputs", [])
        if isinstance(record, dict) and record.get("kind") == "compose_external"
    }
    return {key: all_targets[key] for key in sorted(required_keys)}


def _repository_from_reference(reference: str) -> str:
    tagged = reference.split("@", 1)[0]
    last_slash = tagged.rfind("/")
    last_colon = tagged.rfind(":")
    return tagged[:last_colon] if last_colon > last_slash else tagged


def _validate_external_repo_digest(
    *, reference: str, repo_digests: object, field: str
) -> None:
    if "@" not in reference:
        raise SupplyError(f"{field} expected reference must be digest locked")
    digest = reference.rsplit("@", 1)[1]
    expected = f"{_repository_from_reference(reference)}@{digest}"
    if not isinstance(repo_digests, list) or not all(
        isinstance(item, str) for item in repo_digests
    ):
        raise SupplyError(f"{field} RepoDigests must be a string array")
    if expected not in repo_digests:
        raise SupplyError(
            f"{field} RepoDigests do not bind requested digest; expected {expected!r}"
        )


def _validate_grype_database(
    *, descriptor: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    grype_db = descriptor.get("db")
    if not isinstance(grype_db, dict):
        raise SupplyError("Grype report is missing vulnerability database identity")
    status = grype_db.get("status")
    providers = grype_db.get("providers")
    if not isinstance(status, dict) or not isinstance(providers, dict):
        raise SupplyError("Grype vulnerability database identity is incomplete")

    schema = _required_text(status.get("schemaVersion"), "descriptor.db.schemaVersion")
    built_text = _required_text(status.get("built"), "descriptor.db.built")
    source = _required_text(status.get("from"), "descriptor.db.from")
    if status.get("valid") is not True:
        raise SupplyError("Grype vulnerability database is not valid")

    parsed_source = urlparse(source)
    try:
        checksums = parse_qs(parsed_source.query, strict_parsing=True).get("checksum", [])
    except ValueError as error:
        raise SupplyError("Grype database source query is invalid") from error
    if (
        parsed_source.scheme != "https"
        or parsed_source.hostname != "grype.anchore.io"
        or not parsed_source.path.startswith("/databases/")
        or len(checksums) != 1
        or re.fullmatch(r"sha256:[0-9a-f]{64}", checksums[0]) is None
    ):
        raise SupplyError("Grype database source must be an Anchore HTTPS URL with exact sha256")

    built = _parse_utc_timestamp(built_text, "descriptor.db.built")
    now = _utc_now()
    if built > now:
        raise SupplyError("Grype vulnerability database built timestamp is in the future")
    max_age_hours = policy.get("max_database_age_hours")
    if not isinstance(max_age_hours, int) or isinstance(max_age_hours, bool):
        raise SupplyError("scan policy max_database_age_hours must be an integer")
    age_seconds = (now - built).total_seconds()
    if age_seconds > max_age_hours * 3600:
        raise SupplyError(
            "Grype vulnerability database is stale: "
            f"age={age_seconds / 3600:.2f}h max={max_age_hours}h"
        )

    if not {"nvd", "alpine"}.issubset(providers):
        raise SupplyError("Grype database providers must include nvd and alpine")
    for provider_name, provider in providers.items():
        if not isinstance(provider_name, str) or not provider_name:
            raise SupplyError("Grype database provider name is invalid")
        if not isinstance(provider, dict) or set(provider) != {"captured", "input"}:
            raise SupplyError(f"Grype database provider {provider_name!r} has invalid identity")
        captured = _parse_utc_timestamp(
            provider.get("captured"), f"descriptor.db.providers.{provider_name}.captured"
        )
        if captured > now:
            raise SupplyError(f"Grype database provider {provider_name!r} is from the future")
        provider_input = _required_text(
            provider.get("input"), f"descriptor.db.providers.{provider_name}.input"
        )
        if re.fullmatch(r"xxh64:[0-9a-f]{16}", provider_input) is None:
            raise SupplyError(f"Grype database provider {provider_name!r} input is invalid")

    return {
        "schema_version": schema,
        "built": built_text,
        "source": source,
        "checksum_sha256": checksums[0].split(":", 1)[1],
        "valid": True,
        "age_hours_at_scan": round(age_seconds / 3600, 6),
        "providers": providers,
    }


def validate_lock(lock_path: Path, *, online: bool) -> dict[str, Any]:
    lock = _load_json(lock_path)
    expected_top = {
        "schema_version",
        "resolved_at_utc",
        "resolved_from_revision",
        "production_inputs",
        "application_outputs",
        "scanner_images",
        "scan_policy",
    }
    if set(lock) != expected_top:
        raise SupplyError("image lock has unknown or missing top-level fields")
    if lock.get("schema_version") != "npcink.production-image-lock.v1":
        raise SupplyError("unsupported production image lock schema_version")

    production_inputs = lock.get("production_inputs")
    application_outputs = lock.get("application_outputs")
    scanner_images = lock.get("scanner_images")
    if not all(
        isinstance(value, list)
        for value in (production_inputs, application_outputs, scanner_images)
    ):
        raise SupplyError("image lock collections must be arrays")
    if not production_inputs or not application_outputs or not scanner_images:
        raise SupplyError("image lock collections must not be empty")

    all_keys: list[str] = []
    for collection_name, records in (
        ("production_inputs", production_inputs),
        ("application_outputs", application_outputs),
        ("scanner_images", scanner_images),
    ):
        for index, raw_record in enumerate(records):
            if not isinstance(raw_record, dict):
                raise SupplyError(f"{collection_name}[{index}] must be an object")
            key = _required_text(raw_record.get("key"), f"{collection_name}[{index}].key")
            all_keys.append(key)
            if collection_name != "application_outputs":
                _validate_image_record(raw_record, label=f"{collection_name}[{index}]")
    if len(all_keys) != len(set(all_keys)):
        raise SupplyError("image lock keys must be globally unique")

    policy = lock.get("scan_policy")
    if not isinstance(policy, dict):
        raise SupplyError("scan_policy must be an object")
    expected_policy = {
        "sbom_format": "cyclonedx-json",
        "severity_threshold": "high",
        "unfixed_policy": "block",
        "unknown_severity_policy": "block",
        "max_database_age_hours": 72,
        "max_exception_days": 30,
        "allowlist_file": "deploy/image-lock/cve-allowlist.json",
        "generated_artifacts_must_not_be_committed": True,
    }
    if policy != expected_policy:
        raise SupplyError("scan_policy must match the frozen fail-closed policy")

    expected_froms: dict[str, set[str]] = {}
    syntax_entries: list[dict[str, Any]] = []
    expected_compose: dict[str, dict[str, str]] = {
        "docker-compose.prod.yml": {},
        "docker-compose.runtime.yml": {},
    }
    compose_release_references: set[str] = set()
    for record in production_inputs:
        kind = record.get("kind")
        if kind == "dockerfile_frontend":
            syntax_entries.append(record)
        elif kind == "dockerfile_base":
            source_file = _required_text(record.get("source_file"), "dockerfile_base.source_file")
            expected_froms.setdefault(source_file, set()).add(record["reference"])
        elif kind == "compose_external":
            source_files = record.get("source_files")
            services = record.get("services")
            release_reference = _required_text(
                record.get("release_reference"), f"{record['key']}.release_reference"
            )
            if (
                "@" in release_reference
                or release_reference.endswith(":latest")
                or ":" not in release_reference.rsplit("/", 1)[-1]
            ):
                raise SupplyError(
                    f"compose image {record['key']} release_reference must be a versioned local tag"
                )
            if release_reference in compose_release_references:
                raise SupplyError(f"duplicate compose release_reference {release_reference!r}")
            compose_release_references.add(release_reference)
            if not isinstance(source_files, list) or not isinstance(services, list):
                raise SupplyError(
                    f"compose image {record['key']} needs source_files and services arrays"
                )
            for source_file in source_files:
                if source_file not in expected_compose:
                    raise SupplyError(f"unexpected production compose file {source_file!r}")
                for service in services:
                    if service in expected_compose[source_file]:
                        raise SupplyError(f"duplicate image contract for {source_file}:{service}")
                    expected_compose[source_file][service] = release_reference
        else:
            raise SupplyError(f"unsupported production input kind {kind!r}")

    if len(syntax_entries) != 1:
        raise SupplyError("exactly one Dockerfile frontend lock is required")
    syntax = syntax_entries[0]
    syntax_file = ROOT / _required_text(
        syntax.get("source_file"), "dockerfile_frontend.source_file"
    )
    if syntax_file.read_text().splitlines()[0] != f"# syntax={syntax['reference']}":
        raise SupplyError("Dockerfile syntax frontend does not match image lock")

    for source_file, expected in expected_froms.items():
        actual = _dockerfile_external_froms(ROOT / source_file)
        if not actual or set(actual) != expected or any(item not in expected for item in actual):
            raise SupplyError(
                f"external FROM references in {source_file} do not match image lock: {actual!r}"
            )

    for output in application_outputs:
        reference = _required_text(
            output.get("reference"), f"application_outputs.{output.get('key')}.reference"
        )
        if "@" in reference or reference.endswith(":latest"):
            raise SupplyError(
                "local application outputs must be versioned local tags, not mutable latest/digests"
            )
        if reference in compose_release_references:
            raise SupplyError(
                "application output conflicts with compose external release_reference"
            )
        dockerfile = _required_text(output.get("dockerfile"), "application_output.dockerfile")
        if not (ROOT / dockerfile).is_file():
            raise SupplyError(f"missing application output Dockerfile {dockerfile}")
        compose_references = output.get("compose_references")
        if not isinstance(compose_references, list) or not compose_references:
            raise SupplyError(f"application output {output['key']} needs compose_references")
        for mapping in compose_references:
            if not isinstance(mapping, dict) or set(mapping) != {"source_file", "services"}:
                raise SupplyError(
                    f"invalid compose reference for application output {output['key']}"
                )
            source_file = mapping["source_file"]
            services = mapping["services"]
            if source_file not in expected_compose or not isinstance(services, list):
                raise SupplyError(f"invalid compose mapping for application output {output['key']}")
            for service in services:
                if service in expected_compose[source_file]:
                    raise SupplyError(f"duplicate image contract for {source_file}:{service}")
                expected_compose[source_file][service] = reference

    for compose_file, expected in expected_compose.items():
        actual = _compose_images(ROOT / compose_file)
        if actual != expected:
            missing = sorted(set(expected.items()) - set(actual.items()))
            unexpected = sorted(set(actual.items()) - set(expected.items()))
            raise SupplyError(
                f"{compose_file} image references do not match lock; "
                f"missing={missing!r} unexpected={unexpected!r}"
            )

    allowlist_path = ROOT / policy["allowlist_file"]
    _validate_allowlist_shape(
        _load_json(allowlist_path),
        _lock_image_keys(lock),
        max_exception_days=policy["max_exception_days"],
    )
    schema = _load_json(ROOT / "deploy" / "image-lock" / "cve-allowlist.schema.json")
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise SupplyError("allowlist schema must use JSON Schema draft 2020-12")

    online_receipts: list[dict[str, Any]] = []
    if online:
        for record in [*production_inputs, *scanner_images]:
            command = [
                "docker",
                "buildx",
                "imagetools",
                "inspect",
                record["reference"],
                "--format",
                "{{json .Manifest}}",
            ]
            result = subprocess.run(command, check=False, capture_output=True, text=True)
            if result.returncode != 0:
                raise SupplyError(f"cannot resolve {record['reference']}: {result.stderr.strip()}")
            try:
                manifest = json.loads(result.stdout)
            except json.JSONDecodeError as error:
                raise SupplyError(
                    f"registry returned invalid manifest JSON for {record['key']}"
                ) from error
            if manifest.get("digest") != record["digest"]:
                raise SupplyError(f"registry digest mismatch for {record['key']}")
            platforms = {
                "/".join(
                    (
                        str(item.get("platform", {}).get("os")),
                        str(item.get("platform", {}).get("architecture")),
                    )
                )
                for item in manifest.get("manifests", [])
                if isinstance(item, dict)
            }
            missing_platforms = sorted(set(record["required_platforms"]) - platforms)
            if missing_platforms:
                raise SupplyError(
                    f"{record['key']} lacks required platforms: {missing_platforms!r}"
                )
            online_receipts.append(
                {"key": record["key"], "digest": manifest["digest"], "platforms": sorted(platforms)}
            )

    return {
        "contract_version": "npcink.production-image-lock-verification.v1",
        "status": "passed",
        "lock": str(lock_path),
        "production_input_count": len(production_inputs),
        "application_output_count": len(application_outputs),
        "scanner_image_count": len(scanner_images),
        "online_resolution": online,
        "online_receipts": online_receipts,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _blocking_findings(report: dict[str, Any], policy: dict[str, Any]) -> list[dict[str, str]]:
    matches = report.get("matches")
    if not isinstance(matches, list):
        raise SupplyError("Grype report is missing matches array")
    threshold = SEVERITY_ORDER[policy["severity_threshold"]]
    findings: dict[tuple[str, str, str], dict[str, str]] = {}
    for index, match in enumerate(matches):
        if not isinstance(match, dict):
            raise SupplyError(f"Grype match {index} is not an object")
        vulnerability = match.get("vulnerability")
        artifact = match.get("artifact")
        if not isinstance(vulnerability, dict) or not isinstance(artifact, dict):
            raise SupplyError(f"Grype match {index} is missing vulnerability/artifact")
        vulnerability_id = _required_text(
            vulnerability.get("id"), f"matches[{index}].vulnerability.id"
        )
        severity = _required_text(
            vulnerability.get("severity"), f"matches[{index}].vulnerability.severity"
        ).lower()
        package = _required_text(artifact.get("name"), f"matches[{index}].artifact.name")
        package_version = _required_text(
            artifact.get("version"), f"matches[{index}].artifact.version"
        )
        severity_rank = SEVERITY_ORDER.get(severity)
        is_blocking = severity_rank is None or severity_rank >= threshold
        if not is_blocking:
            continue
        fix = vulnerability.get("fix")
        fix_state = "unknown"
        if (
            isinstance(fix, dict)
            and isinstance(fix.get("state"), str)
            and fix["state"].strip()
        ):
            fix_state = fix["state"]
        key = (vulnerability_id, package, package_version)
        findings[key] = {
            "vulnerability_id": vulnerability_id,
            "package": package,
            "package_version": package_version,
            "severity": severity,
            "fix_state": fix_state,
        }
    return [findings[key] for key in sorted(findings)]


def evaluate_scan(args: argparse.Namespace) -> int:
    lock_path = Path(args.lock).resolve()
    if args.scope == "release" and lock_path != DEFAULT_LOCK.resolve():
        raise SupplyError("release scans must use the canonical repository image lock")
    lock = _load_json(lock_path)
    policy = lock.get("scan_policy")
    if not isinstance(policy, dict):
        raise SupplyError("scan policy is missing")
    image_key = args.image_key
    known_images = _lock_image_keys(lock)
    targets = _scan_targets(lock)
    if image_key not in targets:
        raise SupplyError(f"unknown scan image key {image_key!r}")
    if not IMAGE_ID_RE.fullmatch(args.source_daemon_image_id):
        raise SupplyError("source daemon image ID must be an exact sha256 ID")
    if args.scope not in {"release", "focused"}:
        raise SupplyError("scan scope must be release or focused")
    expected_target = targets[image_key]
    if args.scope == "release" and args.requested_reference != expected_target["reference"]:
        raise SupplyError(
            f"release scan reference mismatch for {image_key}: "
            f"expected {expected_target['reference']!r}"
        )
    if args.scope == "release" and args.archive_reference != expected_target["archive_reference"]:
        raise SupplyError(
            f"release archive reference mismatch for {image_key}: "
            f"expected {expected_target['archive_reference']!r}"
        )
    if args.expected_platform not in {"linux/amd64", "linux/arm64"}:
        raise SupplyError("expected scan platform must be linux/amd64 or linux/arm64")
    scanner_context = _required_text(args.docker_context, "docker_context")

    allowlist_path = Path(args.allowlist).resolve()
    expected_allowlist_path = (ROOT / policy["allowlist_file"]).resolve()
    if args.scope == "release" and allowlist_path != expected_allowlist_path:
        raise SupplyError("release scans must use the canonical repository CVE allowlist")
    allowlist_entries = _validate_allowlist_shape(
        _load_json(allowlist_path),
        known_images,
        max_exception_days=policy["max_exception_days"],
    )
    report_path = Path(args.report).resolve()
    sbom_path = Path(args.sbom).resolve()
    syft_path = Path(args.syft_json).resolve()
    inspect_path = Path(args.inspect_json).resolve()
    archive_path = Path(args.archive).resolve()
    report = _load_json(report_path)
    sbom = _load_json(sbom_path)
    syft_native = _load_json(syft_path)
    archive_subject = _docker_archive_subject(
        archive_path, archive_reference=args.archive_reference
    )
    config_image_id = archive_subject["config_image_id"]
    if archive_subject["platform"] != args.expected_platform:
        raise SupplyError(
            "Docker archive platform mismatch: "
            f"expected {args.expected_platform}, got {archive_subject['platform']}"
        )
    inspect_payload = json.loads(inspect_path.read_text())
    if not isinstance(inspect_payload, list) or len(inspect_payload) != 1:
        raise SupplyError("docker image inspect receipt must contain exactly one image")
    inspect_record = inspect_payload[0]
    if (
        not isinstance(inspect_record, dict)
        or inspect_record.get("Id") != args.source_daemon_image_id
    ):
        raise SupplyError("docker inspect image ID does not match source daemon image ID")
    actual_platform = "/".join(
        (
            str(inspect_record.get("Os", "unknown")),
            str(inspect_record.get("Architecture", "unknown")),
        )
    )
    if actual_platform != args.expected_platform:
        raise SupplyError(
            f"scanned image platform mismatch: expected {args.expected_platform}, "
            f"got {actual_platform}"
        )
    if args.scope == "release" and expected_target["kind"] == "compose_external":
        _validate_external_repo_digest(
            reference=expected_target["reference"],
            repo_digests=inspect_record.get("RepoDigests"),
            field=image_key,
        )
    expected_syft = next(
        record["version"] for record in lock["scanner_images"] if record["key"] == "syft"
    )
    syft_subject_manifest_digest = _validate_syft_subject(
        native=syft_native,
        sbom=sbom,
        image_key=image_key,
        config_image_id=config_image_id,
        expected_syft_version=expected_syft,
    )

    descriptor = report.get("descriptor")
    if not isinstance(descriptor, dict):
        raise SupplyError("Grype report descriptor must be an object")
    grype_version = str(descriptor.get("version", "")).lstrip("v")
    expected_grype = next(
        record["version"] for record in lock["scanner_images"] if record["key"] == "grype"
    )
    if descriptor.get("name") != "grype" or grype_version != expected_grype:
        raise SupplyError(
            "expected locked Grype scanner descriptor, report records "
            f"{descriptor.get('name')!r} {grype_version or 'unknown'}"
        )
    _validate_grype_configuration(descriptor, report)
    report_source = report.get("source")
    if not isinstance(report_source, dict) or report_source.get("type") != "image":
        raise SupplyError("Grype source must describe an image")
    report_target = report.get("source", {}).get("target")
    sbom_component = sbom.get("metadata", {}).get("component")
    if not isinstance(report_target, dict) or not isinstance(sbom_component, dict):
        raise SupplyError("Grype source target is missing")
    grype_user_input = _required_text(
        report_target.get("userInput"), "grype.source.target.userInput"
    )
    if grype_user_input.rsplit("/", 1)[-1] != f"{image_key}.image.tar":
        raise SupplyError("Grype source target does not name the governed image archive")
    if report_target.get("imageID") != sbom_component.get("bom-ref"):
        raise SupplyError("Grype source target imageID does not bind the CycloneDX bom-ref")
    if (
        _normalize_sha256(
            report_target.get("manifestDigest"), "grype.source.target.manifestDigest"
        )
        != syft_subject_manifest_digest
    ):
        raise SupplyError("Grype source target does not bind the Syft subject manifest digest")
    grype_database = _validate_grype_database(descriptor=descriptor, policy=policy)

    blockers = _blocking_findings(report, policy)
    blocker_keys = {
        (item["vulnerability_id"], item["package"], item["package_version"]) for item in blockers
    }
    image_allowlist = [entry for entry in allowlist_entries if entry["image"] == image_key]
    allowed_keys = {
        (entry["vulnerability_id"], entry["package"], entry["package_version"])
        for entry in image_allowlist
    }
    stale = sorted(allowed_keys - blocker_keys)
    if stale:
        raise SupplyError(f"stale allowlist entries for {image_key}: {stale!r}")
    unallowlisted = [
        item
        for item in blockers
        if (item["vulnerability_id"], item["package"], item["package_version"]) not in allowed_keys
    ]
    allowed = [
        item
        for item in blockers
        if (item["vulnerability_id"], item["package"], item["package_version"]) in allowed_keys
    ]

    all_matches = report.get("matches", [])
    severity_counts = Counter(
        str(match.get("vulnerability", {}).get("severity", "unknown")).lower()
        for match in all_matches
        if isinstance(match, dict)
    )
    status = "passed" if not unallowlisted else "failed"
    receipt = {
        "contract_version": RECEIPT_CONTRACT,
        "status": status,
        "scope": args.scope,
        "release_gate": args.scope == "release",
        "generated_at_utc": _utc_now()
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "image_key": image_key,
        "lock_path": (
            str(lock_path.relative_to(ROOT)) if lock_path.is_relative_to(ROOT) else str(lock_path)
        ),
        "lock_sha256": _sha256(lock_path),
        "allowlist_path": (
            str(allowlist_path.relative_to(ROOT))
            if allowlist_path.is_relative_to(ROOT)
            else str(allowlist_path)
        ),
        "allowlist_sha256": _sha256(allowlist_path),
        "requested_reference": args.requested_reference,
        "archive_reference": args.archive_reference,
        "archive_sha256": archive_subject["archive_sha256"],
        "config_image_id": config_image_id,
        "syft_subject_manifest_digest": syft_subject_manifest_digest,
        "source_daemon_image_id": args.source_daemon_image_id,
        "repo_digests": sorted(inspect_record.get("RepoDigests") or []),
        "platform": actual_platform,
        "scanner_docker_context": scanner_context,
        "policy": policy,
        "syft_version": expected_syft,
        "grype_version": grype_version,
        "grype_database": grype_database,
        "target_distro": report.get("distro"),
        "severity_counts": dict(sorted(severity_counts.items())),
        "blocking_finding_count": len(blockers),
        "allowlisted_blocking_finding_count": len(allowed),
        "unallowlisted_blocking_finding_count": len(unallowlisted),
        "allowlisted_blocking_findings": allowed,
        "unallowlisted_blocking_findings": unallowlisted,
        "artifacts": {
            "image_inspect_sha256": _sha256(inspect_path),
            "syft_native_json_sha256": _sha256(syft_path),
            "sbom_cyclonedx_json_sha256": _sha256(sbom_path),
            "grype_json_sha256": _sha256(report_path),
        },
    }
    receipt_path = Path(args.receipt).resolve()
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if status == "passed" else 1


def verify_equivalence(args: argparse.Namespace) -> int:
    lock = _load_json(Path(args.lock).resolve())
    outputs = {
        record["key"]: record
        for record in lock.get("application_outputs", [])
        if isinstance(record, dict)
    }
    receipts: list[dict[str, str]] = []
    for key, record in outputs.items():
        representative_key = record.get("scan_equivalent_to")
        if not representative_key:
            continue
        if representative_key not in outputs:
            raise SupplyError(
                f"application output {key} has unknown scan representative {representative_key!r}"
            )
        reference = _required_text(record.get("reference"), f"application_outputs.{key}.reference")
        representative_reference = _required_text(
            outputs[representative_key].get("reference"),
            f"application_outputs.{representative_key}.reference",
        )
        ids: dict[str, str] = {}
        for name, image_reference in (
            ("image_id", reference),
            ("representative_image_id", representative_reference),
        ):
            result = subprocess.run(
                ["docker", "image", "inspect", image_reference, "--format", "{{.Id}}"],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise SupplyError(
                    f"cannot inspect application image {image_reference}: {result.stderr.strip()}"
                )
            image_id = result.stdout.strip()
            if not IMAGE_ID_RE.fullmatch(image_id):
                raise SupplyError(f"Docker returned invalid image ID for {image_reference}")
            ids[name] = image_id
        status = "passed" if ids["image_id"] == ids["representative_image_id"] else "failed"
        receipts.append(
            {
                "key": key,
                "reference": reference,
                "representative_key": representative_key,
                "representative_reference": representative_reference,
                "image_id": ids["image_id"],
                "representative_image_id": ids["representative_image_id"],
                "status": status,
            }
        )

    if not receipts:
        raise SupplyError("image lock has no scan-equivalent application outputs")
    payload = {
        "contract_version": "npcink.production-image-equivalence.v1",
        "status": "passed" if all(item["status"] == "passed" for item in receipts) else "failed",
        "generated_at_utc": _utc_now()
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "images": receipts,
    }
    output = Path(args.output).resolve()
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "passed" else 1


def _validate_index_receipt(
    *,
    lock: dict[str, Any],
    lock_path: Path,
    receipt: dict[str, Any],
    receipt_path: Path,
    release_gate: bool,
    expected_platform: str | None,
) -> None:
    expected_fields = {
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
    if set(receipt) != expected_fields:
        raise SupplyError("scan receipt has unknown or missing fields")
    if receipt.get("contract_version") != RECEIPT_CONTRACT:
        raise SupplyError("scan receipt contract_version is invalid")
    status = receipt.get("status")
    if status not in {"passed", "failed"}:
        raise SupplyError("scan receipt status must be passed or failed")
    expected_scope = "release" if release_gate else "focused"
    if receipt.get("scope") != expected_scope or receipt.get("release_gate") is not release_gate:
        raise SupplyError("scan receipt scope/release_gate does not match index scope")
    generated_at = _parse_utc_timestamp(
        receipt.get("generated_at_utc"), "scan_receipt.generated_at_utc"
    )
    if generated_at > _utc_now():
        raise SupplyError("scan receipt generated_at_utc is in the future")

    image_key = _required_text(receipt.get("image_key"), "scan_receipt.image_key")
    recorded_lock_path = Path(
        _required_text(receipt.get("lock_path"), "scan_receipt.lock_path")
    )
    if not recorded_lock_path.is_absolute():
        recorded_lock_path = ROOT / recorded_lock_path
    if recorded_lock_path.resolve() != lock_path.resolve():
        raise SupplyError("scan receipt lock_path does not match indexed lock")
    if release_gate and receipt.get("lock_path") != str(DEFAULT_LOCK.relative_to(ROOT)):
        raise SupplyError("release scan receipt must record the canonical relative lock path")
    if receipt.get("lock_sha256") != _sha256(lock_path):
        raise SupplyError("scan receipt lock_sha256 does not match indexed lock")
    recorded_allowlist_path = Path(
        _required_text(receipt.get("allowlist_path"), "scan_receipt.allowlist_path")
    )
    if not recorded_allowlist_path.is_absolute():
        recorded_allowlist_path = ROOT / recorded_allowlist_path
    expected_allowlist_path = (ROOT / lock["scan_policy"]["allowlist_file"]).resolve()
    if release_gate and recorded_allowlist_path.resolve() != expected_allowlist_path:
        raise SupplyError("release scan receipt allowlist_path is not canonical")
    if release_gate and receipt.get("allowlist_path") != lock["scan_policy"]["allowlist_file"]:
        raise SupplyError("release scan receipt must record the canonical relative allowlist path")
    if (
        not recorded_allowlist_path.is_file()
        or receipt.get("allowlist_sha256") != _sha256(recorded_allowlist_path)
    ):
        raise SupplyError("scan receipt allowlist_sha256 does not match its governed allowlist")
    targets = _scan_targets(lock)
    if image_key not in targets:
        raise SupplyError(f"scan receipt names unknown target {image_key!r}")
    reference = _required_text(
        receipt.get("requested_reference"), "scan_receipt.requested_reference"
    )
    if release_gate and reference != targets[image_key]["reference"]:
        raise SupplyError(f"release scan receipt reference mismatch for {image_key}")
    archive_reference = _required_text(
        receipt.get("archive_reference"), "scan_receipt.archive_reference"
    )
    if release_gate and archive_reference != targets[image_key]["archive_reference"]:
        raise SupplyError(f"release scan receipt archive reference mismatch for {image_key}")
    archive_sha256 = _required_text(
        receipt.get("archive_sha256"), "scan_receipt.archive_sha256"
    )
    if re.fullmatch(r"[0-9a-f]{64}", archive_sha256) is None:
        raise SupplyError("scan receipt archive_sha256 is invalid")
    config_image_id = _required_text(
        receipt.get("config_image_id"), "scan_receipt.config_image_id"
    )
    if IMAGE_ID_RE.fullmatch(config_image_id) is None:
        raise SupplyError("scan receipt config_image_id is invalid")
    subject_digest = _required_text(
        receipt.get("syft_subject_manifest_digest"),
        "scan_receipt.syft_subject_manifest_digest",
    )
    if IMAGE_ID_RE.fullmatch(subject_digest) is None:
        raise SupplyError("scan receipt syft_subject_manifest_digest is invalid")
    source_daemon_image_id = _required_text(
        receipt.get("source_daemon_image_id"), "scan_receipt.source_daemon_image_id"
    )
    if IMAGE_ID_RE.fullmatch(source_daemon_image_id) is None:
        raise SupplyError("scan receipt source_daemon_image_id is invalid")
    platform = _required_text(receipt.get("platform"), "scan_receipt.platform")
    if platform not in {"linux/amd64", "linux/arm64"}:
        raise SupplyError("scan receipt platform is unsupported")
    if expected_platform is not None and platform != expected_platform:
        raise SupplyError("release scan receipts do not share the selected platform")
    _required_text(receipt.get("scanner_docker_context"), "scan_receipt.scanner_docker_context")
    repo_digests = receipt.get("repo_digests")
    if not isinstance(repo_digests, list) or not all(
        isinstance(item, str) for item in repo_digests
    ):
        raise SupplyError("scan receipt repo_digests must be a string array")
    if release_gate and targets[image_key]["kind"] == "compose_external":
        _validate_external_repo_digest(
            reference=targets[image_key]["reference"],
            repo_digests=repo_digests,
            field=image_key,
        )

    policy = lock.get("scan_policy")
    if not isinstance(policy, dict) or receipt.get("policy") != policy:
        raise SupplyError("scan receipt policy does not match the image lock")
    expected_scanners = {
        record["key"]: record["version"] for record in lock.get("scanner_images", [])
    }
    if receipt.get("syft_version") != expected_scanners.get("syft"):
        raise SupplyError("scan receipt Syft version does not match the image lock")
    if receipt.get("grype_version") != expected_scanners.get("grype"):
        raise SupplyError("scan receipt Grype version does not match the image lock")

    receipt_db = receipt.get("grype_database")
    if not isinstance(receipt_db, dict) or set(receipt_db) != {
        "schema_version",
        "built",
        "source",
        "checksum_sha256",
        "valid",
        "age_hours_at_scan",
        "providers",
    }:
        raise SupplyError("scan receipt Grype database identity is incomplete")
    descriptor = {
        "db": {
            "status": {
                "schemaVersion": receipt_db.get("schema_version"),
                "built": receipt_db.get("built"),
                "from": receipt_db.get("source"),
                "valid": receipt_db.get("valid"),
            },
            "providers": receipt_db.get("providers"),
        }
    }
    current_db = _validate_grype_database(descriptor=descriptor, policy=policy)
    for field in ("schema_version", "built", "source", "checksum_sha256", "valid", "providers"):
        if receipt_db.get(field) != current_db[field]:
            raise SupplyError(f"scan receipt Grype database {field} does not match source identity")
    recorded_age = receipt_db.get("age_hours_at_scan")
    if not isinstance(recorded_age, (int, float)) or isinstance(recorded_age, bool):
        raise SupplyError("scan receipt Grype database age_hours_at_scan is invalid")
    if recorded_age < 0 or recorded_age > policy["max_database_age_hours"]:
        raise SupplyError("scan receipt Grype database age exceeded policy at scan time")

    severity_counts = receipt.get("severity_counts")
    if not isinstance(severity_counts, dict) or any(
        not isinstance(key, str)
        or not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        for key, value in severity_counts.items()
    ):
        raise SupplyError("scan receipt severity_counts is invalid")
    allowed = receipt.get("allowlisted_blocking_findings")
    unallowed = receipt.get("unallowlisted_blocking_findings")
    finding_fields = {
        "vulnerability_id",
        "package",
        "package_version",
        "severity",
        "fix_state",
    }
    for label, findings in (("allowlisted", allowed), ("unallowlisted", unallowed)):
        if not isinstance(findings, list) or any(
            not isinstance(finding, dict)
            or set(finding) != finding_fields
            or any(not isinstance(value, str) or not value for value in finding.values())
            for finding in findings
        ):
            raise SupplyError(f"scan receipt {label} findings are invalid")
    counts = (
        receipt.get("blocking_finding_count"),
        receipt.get("allowlisted_blocking_finding_count"),
        receipt.get("unallowlisted_blocking_finding_count"),
    )
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts):
        raise SupplyError("scan receipt blocking finding counts are invalid")
    total_count, allowed_count, unallowed_count = counts
    if (
        total_count != allowed_count + unallowed_count
        or allowed_count != len(allowed)
        or unallowed_count != len(unallowed)
        or (status == "passed") != (unallowed_count == 0)
    ):
        raise SupplyError("scan receipt status and blocking findings are inconsistent")

    artifacts = receipt.get("artifacts")
    artifact_names = {
        "image_inspect_sha256": f"{image_key}.image-inspect.json",
        "syft_native_json_sha256": f"{image_key}.syft.json",
        "sbom_cyclonedx_json_sha256": f"{image_key}.sbom.cdx.json",
        "grype_json_sha256": f"{image_key}.grype.json",
    }
    if not isinstance(artifacts, dict) or set(artifacts) != set(artifact_names):
        raise SupplyError("scan receipt is missing exact artifact hashes")
    artifact_paths: dict[str, Path] = {}
    for hash_key, filename in artifact_names.items():
        expected_hash = artifacts.get(hash_key)
        if re.fullmatch(r"[0-9a-f]{64}", str(expected_hash)) is None:
            raise SupplyError("scan receipt contains an invalid artifact sha256")
        artifact_path = receipt_path.parent / filename
        if not artifact_path.is_file() or _sha256(artifact_path) != expected_hash:
            raise SupplyError(f"scan receipt artifact hash mismatch for {filename}")
        artifact_paths[hash_key] = artifact_path

    archive_path = receipt_path.parent / f"{image_key}.image.tar"
    if not archive_path.is_file() or _sha256(archive_path) != archive_sha256:
        raise SupplyError("scan receipt image archive hash does not match its retained archive")
    archive_subject = _docker_archive_subject(
        archive_path, archive_reference=archive_reference
    )
    if (
        archive_subject["archive_sha256"] != archive_sha256
        or archive_subject["config_image_id"] != config_image_id
        or archive_subject["platform"] != platform
    ):
        raise SupplyError("scan receipt does not match its retained Docker image archive")

    inspect_payload = json.loads(artifact_paths["image_inspect_sha256"].read_text())
    if not isinstance(inspect_payload, list) or len(inspect_payload) != 1:
        raise SupplyError("indexed image inspect artifact must contain exactly one image")
    inspect_record = inspect_payload[0]
    if (
        not isinstance(inspect_record, dict)
        or inspect_record.get("Id") != source_daemon_image_id
        or f"{inspect_record.get('Os')}/{inspect_record.get('Architecture')}" != platform
        or sorted(inspect_record.get("RepoDigests") or []) != sorted(repo_digests)
    ):
        raise SupplyError("scan receipt does not match its image inspect artifact")

    sbom = _load_json(artifact_paths["sbom_cyclonedx_json_sha256"])
    syft_native = _load_json(artifact_paths["syft_native_json_sha256"])
    indexed_subject_digest = _validate_syft_subject(
        native=syft_native,
        sbom=sbom,
        image_key=image_key,
        config_image_id=config_image_id,
        expected_syft_version=receipt["syft_version"],
    )
    if indexed_subject_digest != subject_digest:
        raise SupplyError("scan receipt does not match its Syft subject manifest digest")

    report = _load_json(artifact_paths["grype_json_sha256"])
    descriptor = report.get("descriptor")
    if not isinstance(descriptor, dict):
        raise SupplyError("indexed Grype report descriptor is invalid")
    if (
        descriptor.get("name") != "grype"
        or str(descriptor.get("version", "")).lstrip("v") != receipt.get("grype_version")
    ):
        raise SupplyError("scan receipt does not match its Grype report version")
    _validate_grype_configuration(descriptor, report)
    report_source = report.get("source")
    if not isinstance(report_source, dict) or report_source.get("type") != "image":
        raise SupplyError("scan receipt Grype source is not an image")
    report_target = report.get("source", {}).get("target")
    sbom_component = sbom.get("metadata", {}).get("component")
    if (
        not isinstance(report_target, dict)
        or not isinstance(sbom_component, dict)
        or report_target.get("imageID") != sbom_component.get("bom-ref")
        or _normalize_sha256(
            report_target.get("manifestDigest"), "grype.source.target.manifestDigest"
        )
        != subject_digest
    ):
        raise SupplyError("scan receipt does not match its Grype source target")
    grype_user_input = _required_text(
        report_target.get("userInput"), "grype.source.target.userInput"
    )
    if grype_user_input.rsplit("/", 1)[-1] != f"{image_key}.image.tar":
        raise SupplyError("scan receipt Grype target does not name the retained archive")
    report_db = _validate_grype_database(descriptor=descriptor, policy=policy)
    for field in ("schema_version", "built", "source", "checksum_sha256", "valid", "providers"):
        if report_db[field] != receipt_db[field]:
            raise SupplyError("scan receipt does not match its Grype database identity")
    report_blockers = _blocking_findings(report, policy)
    receipt_blockers = sorted(
        [*allowed, *unallowed],
        key=lambda item: (item["vulnerability_id"], item["package"], item["package_version"]),
    )
    if report_blockers != receipt_blockers:
        raise SupplyError("scan receipt findings do not match its Grype report")
    report_severity_counts = Counter(
        str(match.get("vulnerability", {}).get("severity", "unknown")).lower()
        for match in report.get("matches", [])
        if isinstance(match, dict)
    )
    if dict(sorted(report_severity_counts.items())) != severity_counts:
        raise SupplyError("scan receipt severity counts do not match its Grype report")
    if report.get("distro") != receipt.get("target_distro"):
        raise SupplyError("scan receipt target distro does not match its Grype report")

    allowlist_entries = _validate_allowlist_shape(
        _load_json(recorded_allowlist_path),
        _lock_image_keys(lock),
        max_exception_days=policy["max_exception_days"],
    )
    allowed_identities = {
        (entry["vulnerability_id"], entry["package"], entry["package_version"])
        for entry in allowlist_entries
        if entry["image"] == image_key
    }
    actual_allowed = {
        (item["vulnerability_id"], item["package"], item["package_version"])
        for item in allowed
    }
    blocker_identities = {
        (item["vulnerability_id"], item["package"], item["package_version"])
        for item in report_blockers
    }
    if actual_allowed != (allowed_identities & blocker_identities):
        raise SupplyError("scan receipt allowlisted findings do not match the governed allowlist")


def write_index(args: argparse.Namespace) -> int:
    lock_path = Path(args.lock).resolve()
    release_gate = args.scope == "release"
    if release_gate and lock_path != DEFAULT_LOCK.resolve():
        raise SupplyError("release scan indexes must use the canonical repository image lock")
    lock = _load_json(lock_path)
    receipt_paths = [Path(path).resolve() for path in args.receipts]
    receipts = [_load_json(path) for path in receipt_paths]
    if not receipts:
        raise SupplyError("at least one scan receipt is required")
    receipt_keys = [receipt.get("image_key") for receipt in receipts]
    if not all(isinstance(key, str) and key for key in receipt_keys):
        raise SupplyError("every scan receipt must name an image_key")
    if len(receipt_keys) != len(set(receipt_keys)):
        raise SupplyError("scan receipts contain duplicate image keys")
    expected_platform = args.expected_platform
    if expected_platform not in {"linux/amd64", "linux/arm64"}:
        raise SupplyError("scan index expected platform must be linux/amd64 or linux/arm64")
    for index, receipt in enumerate(receipts):
        receipt_path = receipt_paths[index]
        _validate_index_receipt(
            lock=lock,
            lock_path=lock_path,
            receipt=receipt,
            receipt_path=receipt_path,
            release_gate=release_gate,
            expected_platform=expected_platform,
        )

    equivalence = None
    if release_gate:
        required_keys = set(_release_scan_targets(lock))
        actual_keys = set(receipt_keys)
        if actual_keys != required_keys:
            raise SupplyError(
                "release scan receipt set is incomplete or unexpected; "
                f"missing={sorted(required_keys - actual_keys)!r} "
                f"unexpected={sorted(actual_keys - required_keys)!r}"
            )
        if not args.equivalence_json:
            raise SupplyError("release scan index requires image equivalence evidence")
        equivalence = _load_json(Path(args.equivalence_json).resolve())
        if set(equivalence) != {"contract_version", "status", "generated_at_utc", "images"}:
            raise SupplyError("image equivalence evidence has unknown or missing fields")
        if equivalence.get("contract_version") != "npcink.production-image-equivalence.v1":
            raise SupplyError("invalid image equivalence contract")
        if equivalence.get("status") != "passed":
            raise SupplyError("worker image equivalence did not pass")
        if _parse_utc_timestamp(
            equivalence.get("generated_at_utc"), "image_equivalence.generated_at_utc"
        ) > _utc_now():
            raise SupplyError("image equivalence evidence is from the future")
        expected_equivalent_keys = {
            record["key"]
            for record in lock["application_outputs"]
            if record.get("scan_equivalent_to")
        }
        expected_equivalent_records = {
            record["key"]: record for record in lock["application_outputs"]
        }
        equivalent_records = equivalence.get("images")
        if not isinstance(equivalent_records, list):
            raise SupplyError("image equivalence evidence is missing image records")
        equivalence_fields = {
            "key",
            "reference",
            "representative_key",
            "representative_reference",
            "image_id",
            "representative_image_id",
            "status",
        }
        if any(
            not isinstance(record, dict) or set(record) != equivalence_fields
            for record in equivalent_records
        ):
            raise SupplyError("image equivalence records have unknown or missing fields")
        actual_equivalent_keys = {
            record.get("key") for record in equivalent_records if isinstance(record, dict)
        }
        if actual_equivalent_keys != expected_equivalent_keys:
            raise SupplyError("image equivalence evidence does not cover every declared equivalent")
        if any(
            record.get("status") != "passed"
            or record.get("image_id") != record.get("representative_image_id")
            or record.get("representative_key")
            != expected_equivalent_records[record["key"]].get("scan_equivalent_to")
            or record.get("reference") != expected_equivalent_records[record["key"]]["reference"]
            or record.get("representative_reference")
            != expected_equivalent_records[
                expected_equivalent_records[record["key"]]["scan_equivalent_to"]
            ]["reference"]
            for record in equivalent_records
        ):
            raise SupplyError("image equivalence evidence contains unequal image IDs")
        receipt_by_key = {str(receipt["image_key"]): receipt for receipt in receipts}
        for record in equivalent_records:
            representative_key = record["representative_key"]
            representative_receipt = receipt_by_key.get(representative_key)
            if representative_receipt is None:
                raise SupplyError(
                    f"image equivalence representative {representative_key!r} was not scanned"
                )
            if (
                record["representative_image_id"]
                != representative_receipt["source_daemon_image_id"]
                or record["image_id"] != representative_receipt["source_daemon_image_id"]
            ):
                raise SupplyError(
                    "image equivalence IDs are not bound to the representative scan receipt"
                )

    db_identity_fields = (
        "schema_version",
        "built",
        "source",
        "checksum_sha256",
        "valid",
        "providers",
    )
    database_identities = [
        {field: receipt["grype_database"][field] for field in db_identity_fields}
        for receipt in receipts
    ]
    if any(identity != database_identities[0] for identity in database_identities[1:]):
        raise SupplyError("scan receipts do not share one Grype database identity")

    status = (
        "passed" if all(receipt.get("status") == "passed" for receipt in receipts) else "failed"
    )
    required_image_keys = (
        sorted(_release_scan_targets(lock))
        if release_gate
        else sorted(str(key) for key in receipt_keys)
    )
    payload = {
        "contract_version": "npcink.production-image-scan-index.v1",
        "status": status,
        "scope": args.scope,
        "release_gate": release_gate,
        "generated_at_utc": _utc_now()
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "lock_path": receipts[0]["lock_path"],
        "lock_sha256": receipts[0]["lock_sha256"],
        "allowlist_path": receipts[0]["allowlist_path"],
        "allowlist_sha256": receipts[0]["allowlist_sha256"],
        "release_platform": expected_platform,
        "grype_database_identity": database_identities[0],
        "required_image_keys": required_image_keys,
        "equivalent_application_images": equivalence,
        "images": [
            {
                "image_key": receipt.get("image_key"),
                "requested_reference": receipt.get("requested_reference"),
                "archive_reference": receipt.get("archive_reference"),
                "archive_sha256": receipt.get("archive_sha256"),
                "config_image_id": receipt.get("config_image_id"),
                "syft_subject_manifest_digest": receipt.get(
                    "syft_subject_manifest_digest"
                ),
                "source_daemon_image_id": receipt.get("source_daemon_image_id"),
                "platform": receipt.get("platform"),
                "scanner_docker_context": receipt.get("scanner_docker_context"),
                "status": receipt.get("status"),
                "receipt_sha256": _sha256(receipt_path),
                "artifacts": receipt.get("artifacts"),
                "grype_database": receipt.get("grype_database"),
                "blocking_finding_count": receipt.get("blocking_finding_count"),
                "unallowlisted_blocking_finding_count": receipt.get(
                    "unallowlisted_blocking_finding_count"
                ),
            }
            for index, receipt in enumerate(receipts)
            for receipt_path in (receipt_paths[index],)
        ],
    }
    output = Path(args.output).resolve()
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if status == "passed" else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--lock", default=str(DEFAULT_LOCK))
    verify.add_argument("--online", action="store_true")

    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--lock", default=str(DEFAULT_LOCK))
    evaluate.add_argument("--allowlist", required=True)
    evaluate.add_argument("--image-key", required=True)
    evaluate.add_argument("--source-daemon-image-id", required=True)
    evaluate.add_argument("--requested-reference", required=True)
    evaluate.add_argument("--archive-reference", required=True)
    evaluate.add_argument("--scope", choices=("release", "focused"), required=True)
    evaluate.add_argument("--expected-platform", required=True)
    evaluate.add_argument("--docker-context", required=True)
    evaluate.add_argument("--inspect-json", required=True)
    evaluate.add_argument("--archive", required=True)
    evaluate.add_argument("--syft-json", required=True)
    evaluate.add_argument("--sbom", required=True)
    evaluate.add_argument("--report", required=True)
    evaluate.add_argument("--receipt", required=True)

    index = subparsers.add_parser("index")
    index.add_argument("--lock", default=str(DEFAULT_LOCK))
    index.add_argument("--output", required=True)
    index.add_argument("--scope", choices=("release", "focused"), required=True)
    index.add_argument("--expected-platform", required=True)
    index.add_argument("--equivalence-json")
    index.add_argument("receipts", nargs="+")

    equivalence = subparsers.add_parser("equivalence")
    equivalence.add_argument("--lock", default=str(DEFAULT_LOCK))
    equivalence.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "verify":
            receipt = validate_lock(Path(args.lock).resolve(), online=args.online)
            print(json.dumps(receipt, indent=2, sort_keys=True))
            return 0
        if args.command == "evaluate":
            return evaluate_scan(args)
        if args.command == "index":
            return write_index(args)
        if args.command == "equivalence":
            return verify_equivalence(args)
        raise SupplyError(f"unsupported command {args.command!r}")
    except SupplyError as error:
        print(f"[fail] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
