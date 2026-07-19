from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import re
import tarfile
from argparse import Namespace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "deploy" / "image-lock" / "production-images.json"
LAYER_DIGEST = "sha256:" + "b" * 64
CONFIG_BYTES = json.dumps(
    {
        "architecture": "amd64",
        "os": "linux",
        "rootfs": {"type": "layers", "diff_ids": [LAYER_DIGEST]},
    },
    separators=(",", ":"),
).encode()
SHA256 = "sha256:" + hashlib.sha256(CONFIG_BYTES).hexdigest()
SYFT_MANIFEST_BYTES = json.dumps(
    {
        "schemaVersion": 2,
        "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
        "config": {
            "mediaType": "application/vnd.docker.container.image.v1+json",
            "size": len(CONFIG_BYTES),
            "digest": SHA256,
        },
        "layers": [
            {
                "mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip",
                "size": 1,
                "digest": LAYER_DIGEST,
            }
        ],
    },
    separators=(",", ":"),
).encode()
SUBJECT_SHA256 = "sha256:" + hashlib.sha256(SYFT_MANIFEST_BYTES).hexdigest()
OTHER_SHA256 = "sha256:" + "d" * 64


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fresh_db_built() -> str:
    return _utc_text(datetime.now(UTC) - timedelta(hours=1))


def _supply_module() -> ModuleType:
    path = ROOT / "scripts" / "production-image-supply.py"
    spec = importlib.util.spec_from_file_location("production_image_supply", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _lock() -> dict[str, object]:
    return json.loads(LOCK_PATH.read_text())


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _add_tar_bytes(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    member.mode = 0o600
    archive.addfile(member, io.BytesIO(payload))


def _write_image_archive(
    path: Path, *, archive_reference: str, repo_tags: list[str] | None = None
) -> None:
    config_name = f"blobs/sha256/{SHA256.split(':', 1)[1]}"
    layer_name = "blobs/sha256/" + "e" * 64
    manifest = json.dumps(
        [
            {
                "Config": config_name,
                "RepoTags": repo_tags if repo_tags is not None else [archive_reference],
                "Layers": [layer_name],
            }
        ],
        separators=(",", ":"),
    ).encode()
    with tarfile.open(path, mode="w") as archive:
        _add_tar_bytes(archive, "manifest.json", manifest)
        _add_tar_bytes(archive, config_name, CONFIG_BYTES)
        _add_tar_bytes(archive, layer_name, b"x")


def _syft_native(image_key: str) -> dict[str, object]:
    return {
        "source": {
            "id": SUBJECT_SHA256.split(":", 1)[1],
            "name": f"/input/{image_key}.image.tar",
            "version": SUBJECT_SHA256,
            "type": "image",
            "metadata": {
                "userInput": f"/input/{image_key}.image.tar",
                "imageID": SHA256,
                "manifestDigest": SUBJECT_SHA256,
                "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
                "config": base64.b64encode(CONFIG_BYTES).decode(),
                "manifest": base64.b64encode(SYFT_MANIFEST_BYTES).decode(),
            },
        },
        "descriptor": {"name": "syft", "version": "1.33.0"},
    }


def _grype_configuration() -> dict[str, object]:
    supply = _supply_module()
    return {
        "ignore": supply.GRYPE_BUILTIN_IGNORE_RULES,
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
        "db": {
            "auto-update": False,
            "validate-by-hash-on-start": True,
            "validate-age": True,
        },
    }


def _scan_report(
    *, severity: str = "medium", built: str | None = None, image_key: str = "api"
) -> dict[str, object]:
    built = built or _fresh_db_built()
    return {
        "descriptor": {
            "name": "grype",
            "version": "0.98.0",
            "configuration": _grype_configuration(),
            "db": {
                "status": {
                    "schemaVersion": "v6.1.9",
                    "built": built,
                    "from": (
                        "https://grype.anchore.io/databases/v6/"
                        "vulnerability-db_v6.1.9.tar.zst?checksum=sha256%3A" + "c" * 64
                    ),
                    "valid": True,
                },
                "providers": {
                    "nvd": {
                        "captured": built,
                        "input": "xxh64:50726faea9716bd9",
                    },
                    "alpine": {
                        "captured": built,
                        "input": "xxh64:34ae38de8c990548",
                    },
                },
            },
        },
        "source": {
            "type": "image",
            "target": {
                "userInput": f"/input/{image_key}.image.tar",
                "imageID": "fixture-bom-ref",
                "manifestDigest": SUBJECT_SHA256,
            },
        },
        "distro": {"name": "alpine", "version": "3.24.1", "idLike": ["alpine"]},
        "ignoredMatches": None,
        "matches": [
            {
                "vulnerability": {
                    "id": "CVE-2999-0001",
                    "severity": severity,
                    "fix": {"versions": [], "state": ""},
                },
                "artifact": {"name": "demo", "version": "1.0.0"},
            }
        ],
    }


def _evaluate_args(
    tmp_path: Path,
    *,
    allowlist: dict[str, object],
    severity: str,
    built: str | None = None,
    source_daemon_image_id: str = SHA256,
) -> Namespace:
    tmp_path.mkdir(parents=True, exist_ok=True)
    inspect_path = tmp_path / "inspect.json"
    sbom_path = tmp_path / "sbom.json"
    syft_path = tmp_path / "syft.json"
    report_path = tmp_path / "grype.json"
    archive_path = tmp_path / "api.image.tar"
    allowlist_path = tmp_path / "allowlist.json"
    receipt_path = tmp_path / "receipt.json"
    _write_json(
        inspect_path,
        [
            {
                "Id": source_daemon_image_id,
                "RepoDigests": ["demo@" + SHA256],
                "Os": "linux",
                "Architecture": "amd64",
            }
        ],
    )
    archive_reference = "npcink-ai-cloud-api:test"
    _write_image_archive(archive_path, archive_reference=archive_reference)
    _write_json(syft_path, _syft_native("api"))
    _write_json(
        sbom_path,
        {
            "bomFormat": "CycloneDX",
            "metadata": {
                "tools": {
                    "components": [{"type": "application", "name": "syft", "version": "1.33.0"}]
                },
                "component": {
                    "bom-ref": "fixture-bom-ref",
                    "type": "container",
                    "name": "sha256",
                    "version": SUBJECT_SHA256,
                },
            },
        },
    )
    _write_json(report_path, _scan_report(severity=severity, built=built))
    _write_json(allowlist_path, allowlist)
    return Namespace(
        lock=str(LOCK_PATH),
        allowlist=str(allowlist_path),
        image_key="api",
        source_daemon_image_id=source_daemon_image_id,
        requested_reference=archive_reference,
        archive_reference=archive_reference,
        scope="focused",
        expected_platform="linux/amd64",
        docker_context="test-local-unix",
        inspect_json=str(inspect_path),
        archive=str(archive_path),
        syft_json=str(syft_path),
        sbom=str(sbom_path),
        report=str(report_path),
        receipt=str(receipt_path),
    )


def test_production_image_lock_matches_every_dockerfile_and_deploy_compose() -> None:
    supply = _supply_module()
    receipt = supply.validate_lock(LOCK_PATH, online=False)
    lock = _lock()
    inputs = {record["key"]: record for record in lock["production_inputs"]}

    assert receipt["status"] == "passed"
    assert inputs["python_runtime"]["tag"] == "python:3.14-alpine"
    assert inputs["uv_builder"]["reference"].startswith("ghcr.io/astral-sh/uv:0.11.29@sha256:")
    assert inputs["postgres_base"]["source_file"] == "Dockerfile.postgres"
    assert inputs["node_frontend"]["tag"] == "node:22-alpine"
    assert inputs["nginx"]["source_files"] == [
        "docker-compose.prod.yml",
        "docker-compose.runtime.yml",
    ]
    compose_external_keys = {
        record["key"]
        for record in lock["production_inputs"]
        if record["kind"] == "compose_external"
    }
    assert compose_external_keys == {"redis", "nginx"}
    assert {"caddy", "otel_collector", "jaeger"}.isdisjoint(compose_external_keys)
    for record in lock["production_inputs"]:
        if record["kind"] == "compose_external":
            assert record["release_reference"].startswith("npcink-ai-cloud-external-")
            assert record["release_reference"].endswith(":prod")
            assert "@" not in record["release_reference"]

    outputs = {record["key"]: record for record in lock["application_outputs"]}
    assert outputs["postgres"]["reference"] == "npcink-ai-cloud-postgres:prod"
    assert outputs["postgres"]["scan_by_default"] is True
    postgres_dockerfile = (ROOT / "Dockerfile.postgres").read_text()
    assert "rm /usr/local/bin/gosu" in postgres_dockerfile
    assert postgres_dockerfile.rstrip().endswith("USER postgres")

    for record in [*lock["production_inputs"], *lock["scanner_images"]]:
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", record["digest"])
        assert record["reference"] == f"{record['tag']}@{record['digest']}"
        assert {"linux/amd64", "linux/arm64"}.issubset(record["required_platforms"])


def test_python_lock_and_extras_smoke_use_the_same_interpreter_line() -> None:
    lock = _lock()
    inputs = {record["key"]: record for record in lock["production_inputs"]}
    smoke = (ROOT / "scripts" / "production-python-extras-smoke.sh").read_text()

    python_tag = inputs["python_runtime"]["tag"]
    version_match = re.fullmatch(r"python:(\d+\.\d+)-alpine", python_tag)
    assert version_match is not None
    assert f'PYTHON_VERSION="{version_match.group(1)}"' in smoke
    assert '--python "${PYTHON_VERSION}"' in smoke
    assert "--python 3.12" not in smoke


def test_application_runtime_identity_is_stable_and_verified_in_built_images() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    smoke = (ROOT / "scripts" / "production-python-extras-smoke.sh").read_text()

    assert 'test "$(getent group 999)" = "ping:x:999:"' in dockerfile
    assert 'test -z "$(getent passwd 999 || true)"' in dockerfile
    assert "sed -i 's/^ping:x:999:$/app:x:999:/' /etc/group" in dockerfile
    assert "--uid 999 --ingroup app" in dockerfile
    assert "getent passwd app | cut -d: -f3-4" in dockerfile
    assert "getent group app | cut -d: -f3" in dockerfile
    assert "stat -c '%u:%g' /var/lib/npcink-ai-cloud/artifacts" in dockerfile
    assert "docker image inspect --format '{{.Config.User}}'" in smoke
    assert '[ "$(id -u)" = "999" ]' in smoke
    assert '[ "$(id -g)" = "999" ]' in smoke


def test_scan_policy_is_fail_closed_and_canonical_exceptions_are_exact_and_bounded() -> None:
    lock = _lock()
    policy = lock["scan_policy"]
    allowlist = json.loads((ROOT / policy["allowlist_file"]).read_text())
    schema = json.loads((ROOT / "deploy" / "image-lock" / "cve-allowlist.schema.json").read_text())

    assert policy == {
        "sbom_format": "cyclonedx-json",
        "severity_threshold": "high",
        "unfixed_policy": "block",
        "unknown_severity_policy": "block",
        "max_database_age_hours": 72,
        "max_exception_days": 30,
        "allowlist_file": "deploy/image-lock/cve-allowlist.json",
        "generated_artifacts_must_not_be_committed": True,
    }
    assert allowlist["schema_version"] == "npcink.production-image-cve-allowlist.v1"
    entries = allowlist["entries"]
    assert [
        (
            entry["image"],
            entry["vulnerability_id"],
            entry["package"],
            entry["package_version"],
        )
        for entry in entries
    ] == [
        ("api", "CVE-2026-11940", "python", "3.14.6"),
        ("api", "CVE-2026-11972", "python", "3.14.6"),
        ("api", "CVE-2026-15308", "python", "3.14.6"),
    ]
    assert {entry["owner"] for entry in entries} == {"Muze"}
    assert {entry["expires_on"] for entry in entries} == {"2026-08-05"}
    assert all("P5 engineering" in entry["reason"] for entry in entries)
    assert all("no production or GA authorization" in entry["reason"] for entry in entries)
    required = schema["properties"]["entries"]["items"]["required"]
    assert {"image", "vulnerability_id", "package", "package_version"}.issubset(required)
    assert {"owner", "reason", "expires_on"}.issubset(required)
    assert schema["properties"]["entries"]["items"]["additionalProperties"] is False


def test_high_unfixed_finding_blocks_and_exact_temporary_exception_is_audited(
    tmp_path: Path,
) -> None:
    supply = _supply_module()
    empty = {"schema_version": "npcink.production-image-cve-allowlist.v1", "entries": []}
    blocked_args = _evaluate_args(tmp_path / "blocked", allowlist=empty, severity="high")

    assert supply.evaluate_scan(blocked_args) == 1
    blocked = json.loads(Path(blocked_args.receipt).read_text())
    assert blocked["status"] == "failed"
    assert blocked["unallowlisted_blocking_finding_count"] == 1
    assert blocked["unallowlisted_blocking_findings"][0]["fix_state"] == "unknown"
    assert blocked["grype_database"]["schema_version"] == "v6.1.9"
    assert "checksum=sha256%3A" in blocked["grype_database"]["source"]
    assert blocked["lock_sha256"] == hashlib.sha256(LOCK_PATH.read_bytes()).hexdigest()
    assert blocked["syft_version"] == "1.33.0"

    exception = {
        "schema_version": "npcink.production-image-cve-allowlist.v1",
        "entries": [
            {
                "image": "api",
                "vulnerability_id": "CVE-2999-0001",
                "package": "demo",
                "package_version": "1.0.0",
                "owner": "security-team",
                "reason": "Confirmed upstream false positive pending database correction.",
                "expires_on": (supply._utc_now().date() + timedelta(days=10)).isoformat(),
            }
        ],
    }
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    allowed_args = _evaluate_args(allowed_dir, allowlist=exception, severity="high")
    assert supply.evaluate_scan(allowed_args) == 0
    allowed = json.loads(Path(allowed_args.receipt).read_text())
    assert allowed["status"] == "passed"
    assert allowed["allowlisted_blocking_finding_count"] == 1


def test_expired_or_stale_allowlist_entry_fails_closed(tmp_path: Path) -> None:
    supply = _supply_module()
    expired = {
        "schema_version": "npcink.production-image-cve-allowlist.v1",
        "entries": [
            {
                "image": "api",
                "vulnerability_id": "CVE-2999-0001",
                "package": "demo",
                "package_version": "1.0.0",
                "owner": "security-team",
                "reason": "Expired exception must never be accepted.",
                "expires_on": "2000-01-01",
            }
        ],
    }
    args = _evaluate_args(tmp_path, allowlist=expired, severity="high")
    with pytest.raises(supply.SupplyError, match="expired"):
        supply.evaluate_scan(args)

    too_long = json.loads(json.dumps(expired))
    too_long["entries"][0]["expires_on"] = (
        supply._utc_now().date() + timedelta(days=31)
    ).isoformat()
    too_long_args = _evaluate_args(tmp_path / "too-long", allowlist=too_long, severity="high")
    with pytest.raises(supply.SupplyError, match="30-day maximum"):
        supply.evaluate_scan(too_long_args)


def test_grype_database_age_boundary_and_future_time_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supply = _supply_module()
    now = datetime(2030, 1, 4, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(supply, "_utc_now", lambda: now)
    empty = {"schema_version": "npcink.production-image-cve-allowlist.v1", "entries": []}

    boundary = _evaluate_args(
        tmp_path / "boundary",
        allowlist=empty,
        severity="medium",
        built=_utc_text(now - timedelta(hours=72)),
    )
    assert supply.evaluate_scan(boundary) == 0

    stale = _evaluate_args(
        tmp_path / "stale-db",
        allowlist=empty,
        severity="medium",
        built=_utc_text(now - timedelta(hours=72, seconds=1)),
    )
    with pytest.raises(supply.SupplyError, match="database is stale"):
        supply.evaluate_scan(stale)

    future = _evaluate_args(
        tmp_path / "future-db",
        allowlist=empty,
        severity="medium",
        built=_utc_text(now + timedelta(seconds=1)),
    )
    with pytest.raises(supply.SupplyError, match="timestamp is in the future"):
        supply.evaluate_scan(future)


def test_evaluator_rejects_wrong_release_reference_repo_digest_and_lock_override(
    tmp_path: Path,
) -> None:
    supply = _supply_module()
    built = _fresh_db_built()
    _write_release_receipt(supply, tmp_path, "redis", built=built)
    lock = _lock()
    reference = supply._scan_targets(lock)["redis"]["reference"]
    args = Namespace(
        lock=str(LOCK_PATH),
        allowlist=str(ROOT / lock["scan_policy"]["allowlist_file"]),
        image_key="redis",
        source_daemon_image_id=SHA256,
        requested_reference="redis:7-alpine@" + OTHER_SHA256,
        archive_reference=supply._scan_targets(lock)["redis"]["archive_reference"],
        scope="release",
        expected_platform="linux/amd64",
        docker_context="test-local-unix",
        inspect_json=str(tmp_path / "redis.image-inspect.json"),
        archive=str(tmp_path / "redis.image.tar"),
        syft_json=str(tmp_path / "redis.syft.json"),
        sbom=str(tmp_path / "redis.sbom.cdx.json"),
        report=str(tmp_path / "redis.grype.json"),
        receipt=str(tmp_path / "wrong.receipt.json"),
    )
    with pytest.raises(supply.SupplyError, match="reference mismatch"):
        supply.evaluate_scan(args)

    args.requested_reference = reference
    inspect_payload = json.loads(Path(args.inspect_json).read_text())
    inspect_payload[0]["RepoDigests"] = ["redis@" + OTHER_SHA256]
    _write_json(Path(args.inspect_json), inspect_payload)
    with pytest.raises(supply.SupplyError, match="do not bind requested digest"):
        supply.evaluate_scan(args)

    copied_lock = tmp_path / "production-images.json"
    copied_lock.write_bytes(LOCK_PATH.read_bytes())
    args.lock = str(copied_lock)
    with pytest.raises(supply.SupplyError, match="canonical repository image lock"):
        supply.evaluate_scan(args)


def test_evaluator_rejects_sbom_or_grype_target_for_another_image(tmp_path: Path) -> None:
    supply = _supply_module()
    empty = {"schema_version": "npcink.production-image-cve-allowlist.v1", "entries": []}
    args = _evaluate_args(tmp_path, allowlist=empty, severity="medium")
    sbom = json.loads(Path(args.sbom).read_text())
    sbom["metadata"]["component"]["version"] = OTHER_SHA256
    _write_json(Path(args.sbom), sbom)
    with pytest.raises(supply.SupplyError, match="CycloneDX component"):
        supply.evaluate_scan(args)

    sbom["metadata"]["component"]["version"] = SUBJECT_SHA256
    _write_json(Path(args.sbom), sbom)
    syft = json.loads(Path(args.syft_json).read_text())
    syft["source"]["metadata"]["imageID"] = OTHER_SHA256
    _write_json(Path(args.syft_json), syft)
    with pytest.raises(supply.SupplyError, match="source imageID"):
        supply.evaluate_scan(args)

    syft["source"]["metadata"]["imageID"] = SHA256
    _write_json(Path(args.syft_json), syft)
    report = json.loads(Path(args.report).read_text())
    report["source"]["target"]["manifestDigest"] = OTHER_SHA256
    _write_json(Path(args.report), report)
    with pytest.raises(supply.SupplyError, match="Syft subject manifest"):
        supply.evaluate_scan(args)


def test_evaluator_rejects_extra_docker_archive_repo_tag(tmp_path: Path) -> None:
    supply = _supply_module()
    empty = {"schema_version": "npcink.production-image-cve-allowlist.v1", "entries": []}
    args = _evaluate_args(tmp_path, allowlist=empty, severity="medium")
    _write_image_archive(
        Path(args.archive),
        archive_reference=args.archive_reference,
        repo_tags=[args.archive_reference, "attacker.example/undeclared:latest"],
    )

    with pytest.raises(supply.SupplyError, match="exact singleton archive reference"):
        supply.evaluate_scan(args)


def test_receipt_separates_portable_config_id_from_multiarch_daemon_id(tmp_path: Path) -> None:
    supply = _supply_module()
    empty = {"schema_version": "npcink.production-image-cve-allowlist.v1", "entries": []}
    args = _evaluate_args(
        tmp_path,
        allowlist=empty,
        severity="medium",
        source_daemon_image_id=OTHER_SHA256,
    )
    assert supply.evaluate_scan(args) == 0
    receipt = json.loads(Path(args.receipt).read_text())
    assert receipt["config_image_id"] == SHA256
    assert receipt["syft_subject_manifest_digest"] == SUBJECT_SHA256
    assert receipt["source_daemon_image_id"] == OTHER_SHA256


def test_evaluator_rejects_grype_suppressions_and_mutable_result_policy(tmp_path: Path) -> None:
    supply = _supply_module()
    empty = {"schema_version": "npcink.production-image-cve-allowlist.v1", "entries": []}
    args = _evaluate_args(tmp_path, allowlist=empty, severity="medium")
    report = json.loads(Path(args.report).read_text())
    report["ignoredMatches"] = [
        {
            "vulnerability": {"id": "CVE-2999-9999"},
            "artifact": {"name": "hidden", "version": "1"},
        }
    ]
    _write_json(Path(args.report), report)
    with pytest.raises(supply.SupplyError, match="suppressed vulnerability matches"):
        supply.evaluate_scan(args)

    report["ignoredMatches"] = None
    report["descriptor"]["configuration"]["exclude"] = ["/app"]
    _write_json(Path(args.report), report)
    with pytest.raises(supply.SupplyError, match="can suppress governed findings"):
        supply.evaluate_scan(args)

    report["descriptor"]["configuration"]["exclude"] = []
    report["descriptor"]["configuration"]["db"]["auto-update"] = True
    _write_json(Path(args.report), report)
    with pytest.raises(supply.SupplyError, match="database runtime configuration"):
        supply.evaluate_scan(args)

    report["descriptor"]["configuration"]["db"]["auto-update"] = False
    report["descriptor"]["name"] = "not-grype"
    _write_json(Path(args.report), report)
    with pytest.raises(supply.SupplyError, match="locked Grype scanner descriptor"):
        supply.evaluate_scan(args)


def _write_release_receipt(
    supply: ModuleType,
    directory: Path,
    key: str,
    *,
    built: str,
    severity: str = "medium",
) -> str:
    lock = _lock()
    target = supply._scan_targets(lock)[key]
    reference = target["reference"]
    archive_reference = target["archive_reference"]
    repo_digests: list[str] = []
    if target["kind"] == "compose_external":
        repo_digests = [
            f"{supply._repository_from_reference(reference)}@{reference.rsplit('@', 1)[1]}"
        ]

    inspect_path = directory / f"{key}.image-inspect.json"
    archive_path = directory / f"{key}.image.tar"
    syft_path = directory / f"{key}.syft.json"
    sbom_path = directory / f"{key}.sbom.cdx.json"
    report_path = directory / f"{key}.grype.json"
    receipt_path = directory / f"{key}.receipt.json"
    _write_json(
        inspect_path,
        [
            {
                "Id": SHA256,
                "RepoDigests": repo_digests,
                "Os": "linux",
                "Architecture": "amd64",
            }
        ],
    )
    _write_image_archive(archive_path, archive_reference=archive_reference)
    _write_json(syft_path, _syft_native(key))
    _write_json(
        sbom_path,
        {
            "bomFormat": "CycloneDX",
            "metadata": {
                "tools": {
                    "components": [{"type": "application", "name": "syft", "version": "1.33.0"}]
                },
                "component": {
                    "bom-ref": "fixture-bom-ref",
                    "type": "container",
                    "name": "sha256",
                    "version": SUBJECT_SHA256,
                },
            },
        },
    )
    report = _scan_report(severity=severity, built=built, image_key=key)
    if key == "api":
        canonical_allowlist = json.loads(
            (ROOT / lock["scan_policy"]["allowlist_file"]).read_text()
        )
        matches = report["matches"]
        assert isinstance(matches, list)
        for entry in canonical_allowlist["entries"]:
            matches.append(
                {
                    "vulnerability": {
                        "id": entry["vulnerability_id"],
                        "severity": "high",
                        "fix": {"versions": [], "state": ""},
                    },
                    "artifact": {
                        "name": entry["package"],
                        "version": entry["package_version"],
                    },
                }
            )
    _write_json(report_path, report)
    args = Namespace(
        lock=str(LOCK_PATH),
        allowlist=str(ROOT / lock["scan_policy"]["allowlist_file"]),
        image_key=key,
        source_daemon_image_id=SHA256,
        requested_reference=reference,
        archive_reference=archive_reference,
        scope="release",
        expected_platform="linux/amd64",
        docker_context="test-local-unix",
        inspect_json=str(inspect_path),
        archive=str(archive_path),
        syft_json=str(syft_path),
        sbom=str(sbom_path),
        report=str(report_path),
        receipt=str(receipt_path),
    )
    expected_result = 0 if severity == "medium" else 1
    assert supply.evaluate_scan(args) == expected_result
    return str(receipt_path)


def _equivalence(lock: dict[str, object]) -> dict[str, object]:
    outputs = {record["key"]: record for record in lock["application_outputs"]}
    return {
        "contract_version": "npcink.production-image-equivalence.v1",
        "status": "passed",
        "generated_at_utc": _utc_text(datetime.now(UTC)),
        "images": [
            {
                "key": key,
                "reference": record["reference"],
                "representative_key": record["scan_equivalent_to"],
                "representative_reference": outputs[record["scan_equivalent_to"]]["reference"],
                "image_id": SHA256,
                "representative_image_id": SHA256,
                "status": "passed",
            }
            for key, record in outputs.items()
            if record.get("scan_equivalent_to")
        ],
    }


def test_release_scan_index_requires_complete_deploy_set_and_real_id_equivalence(
    tmp_path: Path,
) -> None:
    supply = _supply_module()
    lock = _lock()
    required_keys = sorted(
        {record["key"] for record in lock["application_outputs"] if record.get("scan_by_default")}
        | {
            record["key"]
            for record in lock["production_inputs"]
            if record["kind"] == "compose_external"
        }
    )
    receipt_paths: list[str] = []
    db_built = _fresh_db_built()
    for key in required_keys:
        receipt_paths.append(_write_release_receipt(supply, tmp_path, key, built=db_built))

    equivalence_path = tmp_path / "equivalence.json"
    equivalence = _equivalence(lock)
    _write_json(equivalence_path, equivalence)
    output = tmp_path / "index.json"
    args = Namespace(
        lock=str(LOCK_PATH),
        output=str(output),
        scope="release",
        expected_platform="linux/amd64",
        equivalence_json=str(equivalence_path),
        receipts=receipt_paths,
    )
    assert supply.write_index(args) == 0
    index = json.loads(output.read_text())
    assert index["release_gate"] is True
    assert index["required_image_keys"] == required_keys
    assert all(re.fullmatch(r"[0-9a-f]{64}", image["receipt_sha256"]) for image in index["images"])

    args.receipts = receipt_paths[:-1]
    with pytest.raises(supply.SupplyError, match="incomplete"):
        supply.write_index(args)

    args.receipts = receipt_paths
    bad_equivalence = json.loads(json.dumps(equivalence))
    bad_equivalence["images"][0]["image_id"] = OTHER_SHA256
    bad_equivalence["images"][0]["representative_image_id"] = OTHER_SHA256
    _write_json(equivalence_path, bad_equivalence)
    with pytest.raises(supply.SupplyError, match="representative scan receipt"):
        supply.write_index(args)

    _write_json(equivalence_path, equivalence)
    api_path = Path(
        _write_release_receipt(supply, tmp_path, "api", built=db_built, severity="high")
    )
    forged = json.loads(api_path.read_text())
    forged["status"] = "passed"
    forged["blocking_finding_count"] = 0
    forged["allowlisted_blocking_finding_count"] = 0
    forged["allowlisted_blocking_findings"] = []
    forged["unallowlisted_blocking_finding_count"] = 0
    forged["unallowlisted_blocking_findings"] = []
    _write_json(api_path, forged)
    with pytest.raises(supply.SupplyError, match="Grype report"):
        supply.write_index(args)


def test_release_index_rejects_mixed_grype_database_identities(tmp_path: Path) -> None:
    supply = _supply_module()
    lock = _lock()
    required_keys = sorted(supply._release_scan_targets(lock))
    db_built = _fresh_db_built()
    receipt_paths = [
        _write_release_receipt(supply, tmp_path, key, built=db_built) for key in required_keys
    ]
    receipt_paths[-1] = _write_release_receipt(
        supply,
        tmp_path,
        required_keys[-1],
        built=_utc_text(datetime.now(UTC) - timedelta(hours=2)),
    )
    equivalence_path = tmp_path / "equivalence.json"
    _write_json(equivalence_path, _equivalence(lock))
    args = Namespace(
        lock=str(LOCK_PATH),
        output=str(tmp_path / "index.json"),
        scope="release",
        expected_platform="linux/amd64",
        equivalence_json=str(equivalence_path),
        receipts=receipt_paths,
    )
    with pytest.raises(supply.SupplyError, match="one Grype database identity"):
        supply.write_index(args)


def test_scanner_binds_sbom_and_cve_report_to_exact_local_image_id() -> None:
    source = (ROOT / "scripts" / "scan-production-images.sh").read_text()

    assert 'image_id="$(docker image inspect "${reference}" --format \'{{.Id}}\')"' in source
    assert '"docker-archive:/input/${key}.image.tar"' in source
    assert "docker image save" in source
    assert '"syft-json=/output/${key}.syft.json"' in source
    assert 'archive_path="${OUTPUT_DIR}/${key}.image.tar"' in source
    assert 'rm -f "${archive_path}"' not in source
    assert "/var/run/docker.sock:/var/run/docker.sock" not in source
    assert '"sbom:/output/${key}.sbom.cdx.json"' in source
    assert "GRYPE_DB_VALIDATE_BY_HASH_ON_START=true" in source
    assert "GRYPE_DB_AUTO_UPDATE=false" in source
    assert '"${GRYPE_IMAGE}" db update' in source
    assert "DOCKER_HOST is forbidden" in source
    assert 'docker pull --platform "${RELEASE_PLATFORM}"' in source
    assert 'docker image tag "${image_id}" "${archive_reference}"' in source
    assert "npcink-ai-cloud-scan-${CUSTOM_KEYS[${custom_index}]}" in source
    assert "APPLICATIONS_ONLY=0" in source
    assert 'if image["kind"] == "compose_external"' in source
    assert 'RELEASE_SCOPE="1"' not in source
    assert "RELEASE_SCOPE=1" in source
    assert "--only-fixed" not in source
    assert "--ignore" not in source
    assert "scan output must stay outside the Git worktree" in source
