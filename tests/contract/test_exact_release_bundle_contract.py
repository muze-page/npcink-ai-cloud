from __future__ import annotations

import ast
import gzip
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="exact release-bundle contracts require the host Git executable",
)

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "verify-release-bundle-manifest.py"


def load_helper_module():
    spec = importlib.util.spec_from_file_location("exact_bundle_helper", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_helper(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HELPER), *args],
        text=True,
        capture_output=True,
        env=env,
    )


def write(path: Path, content: str = "fixture\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_fixture_docker_archive(
    path: Path,
    *,
    key: str,
    reference: str,
    extra_references: tuple[str, ...] = (),
) -> None:
    layer = io.BytesIO()
    with tarfile.open(fileobj=layer, mode="w") as layer_archive:
        payload = f"fixture layer for {key}\n".encode()
        payload_info = tarfile.TarInfo("fixture.txt")
        payload_info.size = len(payload)
        layer_archive.addfile(payload_info, io.BytesIO(payload))
    layer_bytes = layer.getvalue()
    config = json.dumps(
        {
            "architecture": "amd64",
            "config": {},
            "created": "2026-01-01T00:00:00Z",
            "fixture": key,
            "os": "linux",
            "rootfs": {
                "diff_ids": ["sha256:" + hashlib.sha256(layer_bytes).hexdigest()],
                "type": "layers",
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    config_hex = hashlib.sha256(config).hexdigest()
    manifest = json.dumps(
        [
            {
                "Config": f"{config_hex}.json",
                "RepoTags": [reference, *extra_references],
                "Layers": ["layer.tar"],
            }
        ],
        separators=(",", ":"),
    ).encode()
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        for name, content in (
            ("manifest.json", manifest),
            (f"{config_hex}.json", config),
            ("layer.tar", layer_bytes),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    path.write_bytes(gzip.compress(raw.getvalue(), mtime=0))


def fixture_archive_config_id(path: Path) -> str:
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(path.read_bytes())), mode="r:") as archive:
        manifest = json.loads(archive.extractfile("manifest.json").read())
        config_name = manifest[0]["Config"]
        config_bytes = archive.extractfile(config_name).read()
    return "sha256:" + hashlib.sha256(config_bytes).hexdigest()


def test_docker_archive_rejects_undeclared_repo_tags(tmp_path: Path) -> None:
    helper = load_helper_module()
    archive = tmp_path / "api.tar.gz"
    reference = "npcink-ai-cloud-api:prod"
    write_fixture_docker_archive(
        archive,
        key="api",
        reference=reference,
        extra_references=("unexpected:prod",),
    )

    with pytest.raises(helper.BundleError, match="RepoTags must contain only"):
        helper.docker_archive_subject(archive, archive_reference=reference)


def image_lock() -> dict[str, object]:
    scan_policy = {
        "sbom_format": "cyclonedx-json",
        "severity_threshold": "high",
        "unfixed_policy": "block",
        "unknown_severity_policy": "block",
        "allowlist_file": "deploy/image-lock/cve-allowlist.json",
        "generated_artifacts_must_not_be_committed": True,
        "max_database_age_hours": 72,
        "max_exception_days": 30,
    }
    return {
        "schema_version": "npcink.production-image-lock.v1",
        "resolved_from_revision": "a" * 40,
        "production_inputs": [
            {
                "key": "redis",
                "kind": "compose_external",
                "reference": "redis:7-alpine@sha256:" + "1" * 64,
                "release_reference": "npcink-ai-cloud-external-redis:prod",
            },
            {
                "key": "caddy",
                "kind": "compose_external",
                "reference": "caddy:2-alpine@sha256:" + "2" * 64,
                "release_reference": "npcink-ai-cloud-external-caddy:prod",
            },
        ],
        "application_outputs": [
            {
                "key": "api",
                "reference": "npcink-ai-cloud-api:prod",
                "dockerfile": "Dockerfile",
                "scan_by_default": True,
            },
            {
                "key": "frontend",
                "reference": "npcink-ai-cloud-frontend:prod",
                "dockerfile": "frontend/Dockerfile",
                "scan_by_default": True,
            },
            {
                "key": "postgres",
                "reference": "npcink-ai-cloud-postgres:prod",
                "dockerfile": "Dockerfile.postgres",
                "scan_by_default": True,
            },
            {
                "key": "worker",
                "reference": "npcink-ai-cloud-worker:prod",
                "dockerfile": "Dockerfile",
                "scan_equivalent_to": "api",
            },
            {
                "key": "callback_worker",
                "reference": "npcink-ai-cloud-callback-worker:prod",
                "dockerfile": "Dockerfile",
                "scan_equivalent_to": "api",
            },
            {
                "key": "ops_worker",
                "reference": "npcink-ai-cloud-ops-worker:prod",
                "dockerfile": "Dockerfile",
                "scan_equivalent_to": "api",
            },
        ],
        "scanner_images": [
            {"key": "syft", "version": "1.33.0"},
            {"key": "grype", "version": "0.98.0"},
        ],
        "scan_policy": scan_policy,
    }


def create_scan_evidence(bundle: Path, lock: dict[str, object]) -> dict[str, str]:
    scan_root = bundle / "release/image-scan"
    scan_root.mkdir(parents=True)
    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat()
    policy = lock["scan_policy"]
    references = {
        "api": "npcink-ai-cloud-api:prod",
        "frontend": "npcink-ai-cloud-frontend:prod",
        "postgres": "npcink-ai-cloud-postgres:prod",
        "redis": "redis:7-alpine@sha256:" + "1" * 64,
        "caddy": "caddy:2-alpine@sha256:" + "2" * 64,
    }
    archive_references = {
        "api": references["api"],
        "frontend": references["frontend"],
        "postgres": references["postgres"],
        "redis": "npcink-ai-cloud-external-redis:prod",
        "caddy": "npcink-ai-cloud-external-caddy:prod",
    }
    source_ids = {
        "api": "sha256:" + "8" * 64,
        "frontend": "sha256:" + "9" * 64,
        "postgres": "sha256:" + "a" * 64,
        "redis": "sha256:" + "b" * 64,
        "caddy": "sha256:" + "c" * 64,
    }
    archive_paths = {
        "api": bundle / "dist/api.tar.gz",
        "frontend": bundle / "dist/frontend.tar.gz",
        "postgres": bundle / "dist/postgres.tar.gz",
        "redis": bundle / "dist/external-redis.tar.gz",
        "caddy": bundle / "dist/external-caddy.tar.gz",
    }
    config_ids = {
        key: fixture_archive_config_id(path) for key, path in archive_paths.items()
    }
    lock_sha256 = hashlib.sha256(
        (bundle / "deploy/image-lock/production-images.json").read_bytes()
    ).hexdigest()
    allowlist_sha256 = hashlib.sha256(
        (bundle / "deploy/image-lock/cve-allowlist.json").read_bytes()
    ).hexdigest()
    database_identity = {
        "schema_version": "6",
        "built": timestamp,
        "source": "https://grype.anchore.io/databases/v6/latest.json?checksum=sha256%3A"
        + "d" * 64,
        "checksum_sha256": "d" * 64,
        "valid": True,
        "providers": {
            "nvd": {"captured": timestamp, "input": "xxh64:" + "e" * 16},
            "alpine": {"captured": timestamp, "input": "xxh64:" + "f" * 16},
        },
    }
    image_index_records: list[dict[str, object]] = []
    for key in sorted(references):
        artifacts: dict[str, str] = {}
        for suffix, artifact_key in (
            ("image-inspect.json", "image_inspect_sha256"),
            ("syft.json", "syft_native_json_sha256"),
            ("sbom.cdx.json", "sbom_cyclonedx_json_sha256"),
            ("grype.json", "grype_json_sha256"),
        ):
            artifact_path = scan_root / f"{key}.{suffix}"
            write(artifact_path, json.dumps({"fixture": key, "kind": suffix}) + "\n")
            artifacts[artifact_key] = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        receipt = {
            "contract_version": "npcink.production-image-scan-receipt.v1",
            "status": "passed",
            "scope": "release",
            "release_gate": True,
            "generated_at_utc": timestamp,
            "image_key": key,
            "lock_path": "deploy/image-lock/production-images.json",
            "lock_sha256": lock_sha256,
            "allowlist_path": "deploy/image-lock/cve-allowlist.json",
            "allowlist_sha256": allowlist_sha256,
            "requested_reference": references[key],
            "archive_reference": archive_references[key],
            "archive_sha256": hashlib.sha256(
                gzip.decompress(archive_paths[key].read_bytes())
            ).hexdigest(),
            "config_image_id": config_ids[key],
            "syft_subject_manifest_digest": "sha256:" + "d" * 64,
            "source_daemon_image_id": source_ids[key],
            "repo_digests": [references[key]] if key in {"redis", "caddy"} else [],
            "platform": "linux/amd64",
            "scanner_docker_context": "default",
            "policy": policy,
            "syft_version": "1.33.0",
            "grype_version": "0.98.0",
            "grype_database": {
                **database_identity,
                "age_hours_at_scan": 0.0,
            },
            "target_distro": {"name": "alpine", "version": "3.22"},
            "severity_counts": {},
            "artifacts": artifacts,
            "blocking_finding_count": 0,
            "allowlisted_blocking_finding_count": 0,
            "unallowlisted_blocking_finding_count": 0,
            "allowlisted_blocking_findings": [],
            "unallowlisted_blocking_findings": [],
        }
        receipt_path = scan_root / f"{key}.receipt.json"
        write(receipt_path, json.dumps(receipt, sort_keys=True) + "\n")
        image_index_records.append(
            {
                "image_key": key,
                "requested_reference": references[key],
                "archive_reference": archive_references[key],
                "archive_sha256": receipt["archive_sha256"],
                "config_image_id": config_ids[key],
                "syft_subject_manifest_digest": receipt["syft_subject_manifest_digest"],
                "source_daemon_image_id": source_ids[key],
                "platform": "linux/amd64",
                "scanner_docker_context": "default",
                "status": "passed",
                "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                "artifacts": artifacts,
                "grype_database": receipt["grype_database"],
                "blocking_finding_count": 0,
                "unallowlisted_blocking_finding_count": 0,
            }
        )
    equivalence = {
        "contract_version": "npcink.production-image-equivalence.v1",
        "status": "passed",
        "generated_at_utc": timestamp,
        "images": [
            {
                "key": key,
                "reference": f"npcink-ai-cloud-{key.replace('_', '-')}:prod",
                "representative_key": "api",
                "representative_reference": "npcink-ai-cloud-api:prod",
                "image_id": source_ids["api"],
                "representative_image_id": source_ids["api"],
                "status": "passed",
            }
            for key in ("worker", "callback_worker", "ops_worker")
        ],
    }
    write(
        scan_root / "application-image-equivalence.json",
        json.dumps(equivalence, sort_keys=True) + "\n",
    )
    index = {
        "contract_version": "npcink.production-image-scan-index.v1",
        "status": "passed",
        "scope": "release",
        "release_gate": True,
        "generated_at_utc": timestamp,
        "lock_path": "deploy/image-lock/production-images.json",
        "lock_sha256": lock_sha256,
        "allowlist_path": "deploy/image-lock/cve-allowlist.json",
        "allowlist_sha256": allowlist_sha256,
        "release_platform": "linux/amd64",
        "grype_database_identity": database_identity,
        "required_image_keys": sorted(references),
        "equivalent_application_images": equivalence,
        "images": image_index_records,
    }
    write(scan_root / "scan-index.json", json.dumps(index, sort_keys=True) + "\n")
    return {**config_ids, **{f"source_{key}": value for key, value in source_ids.items()}}


@pytest.fixture()
def exact_bundle_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "source"
    bundle = tmp_path / "bundle with spaces"
    bundle.mkdir(parents=True)
    files = {
        "uv.lock": "uv\n",
        "pnpm-lock.yaml": "pnpm\n",
        "pyproject.toml": "[project]\nname='fixture'\n",
        "package.json": "{}\n",
        "pnpm-workspace.yaml": "packages: []\n",
        "frontend/package.json": "{}\n",
        "Dockerfile": "FROM scratch\n",
        "Dockerfile.postgres": "FROM scratch\nUSER postgres\n",
        "frontend/Dockerfile": "FROM scratch\n",
        "docker-compose.prod.yml": "services: {}\n",
        "docker-compose.runtime.yml": "services: {}\n",
        "migrations/versions/0001.py": "revision='0001'\n",
        "deploy/verify-release-bundle.sh": "#!/usr/bin/env bash\n",
        "site/terms/index.html": "terms\n",
    }
    for relative, content in files.items():
        write(source / relative, content)
    lock = image_lock()
    lock_text = json.dumps(lock, sort_keys=True) + "\n"
    allowlist_text = json.dumps(
        {"schema_version": "npcink.production-image-cve-allowlist.v1", "entries": []},
        sort_keys=True,
    ) + "\n"
    write(source / "deploy/image-lock/production-images.json", lock_text)
    write(source / "deploy/image-lock/cve-allowlist.json", allowlist_text)
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "add", "."], cwd=source, check=True)

    write(bundle / "deploy/image-lock/production-images.json", lock_text)
    write(bundle / "deploy/image-lock/cve-allowlist.json", allowlist_text)
    write(bundle / "deploy/verify-release-bundle.sh", "#!/usr/bin/env bash\n")
    write(bundle / "scripts/verify-release-bundle-manifest.py", "# bundled verifier\n")
    write(bundle / "site/terms/file with spaces.txt", "space-safe payload\n")
    (bundle / "dist").mkdir()
    archive_specs = (
        ("api", "dist/api.tar.gz", "npcink-ai-cloud-api:prod"),
        ("frontend", "dist/frontend.tar.gz", "npcink-ai-cloud-frontend:prod"),
        ("postgres", "dist/postgres.tar.gz", "npcink-ai-cloud-postgres:prod"),
        ("redis", "dist/external-redis.tar.gz", "npcink-ai-cloud-external-redis:prod"),
        ("caddy", "dist/external-caddy.tar.gz", "npcink-ai-cloud-external-caddy:prod"),
    )
    for key, relative, reference in archive_specs:
        write_fixture_docker_archive(bundle / relative, key=key, reference=reference)
    image_ids = create_scan_evidence(bundle, lock)
    records = tmp_path / "images.tsv"
    records.write_text(
        "".join(
            "dist/api.tar.gz\t"
            f"{role}\t{reference}\t{reference}\t{image_ids['source_api']}\t"
            f"{image_ids['api']}\t1\t{primary}\n"
            for role, reference, primary in (
                ("api", "npcink-ai-cloud-api:prod", "1"),
                ("worker", "npcink-ai-cloud-worker:prod", "0"),
                ("callback_worker", "npcink-ai-cloud-callback-worker:prod", "0"),
                ("ops_worker", "npcink-ai-cloud-ops-worker:prod", "0"),
            )
        )
        + "dist/frontend.tar.gz\tfrontend\tnpcink-ai-cloud-frontend:prod\t"
        + "npcink-ai-cloud-frontend:prod\t"
        + f"{image_ids['source_frontend']}\t{image_ids['frontend']}\t1\t1\n"
        + "dist/postgres.tar.gz\tpostgres\tnpcink-ai-cloud-postgres:prod\t"
        + "npcink-ai-cloud-postgres:prod\t"
        + f"{image_ids['source_postgres']}\t{image_ids['postgres']}\t1\t1\n"
        + "dist/external-redis.tar.gz\texternal_redis\t"
        + "npcink-ai-cloud-external-redis:prod\t"
        + f"redis:7-alpine@sha256:{'1' * 64}\t"
        + f"{image_ids['source_redis']}\t{image_ids['redis']}\t1\t1\n"
        + "dist/external-caddy.tar.gz\texternal_caddy\t"
        + "npcink-ai-cloud-external-caddy:prod\t"
        + f"caddy:2-alpine@sha256:{'2' * 64}\t"
        + f"{image_ids['source_caddy']}\t{image_ids['caddy']}\t1\t1\n",
        encoding="utf-8",
    )
    result = run_helper(
        "create",
        "--source-root",
        str(source),
        "--bundle-root",
        str(bundle),
        "--revision",
        "a" * 40,
        "--tree",
        "b" * 40,
        "--branch",
        "codex/fixture",
        "--image-platform",
        "linux/amd64",
        "--gzip-level",
        "1",
        "--frontend-included",
        "1",
        "--external-images-included",
        "1",
        "--image-lock",
        "deploy/image-lock/production-images.json",
        "--image-records",
        str(records),
    )
    assert result.returncode == 0, result.stderr
    return source, bundle, records


def update_manifest_checksum(bundle: Path) -> None:
    manifest = bundle / "release-bundle-manifest.json"
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    checksum_file = bundle / "SHA256SUMS"
    lines = checksum_file.read_text(encoding="utf-8").splitlines()
    lines = [
        f"{digest}  release-bundle-manifest.json"
        if line.endswith("  release-bundle-manifest.json")
        else line
        for line in lines
    ]
    checksum_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_exact_bundle_verifier_rejects_tamper_missing_extra_and_schema(
    exact_bundle_fixture: tuple[Path, Path, Path],
) -> None:
    _, bundle, _ = exact_bundle_fixture
    passed = run_helper("verify-directory", "--root", str(bundle))
    assert passed.returncode == 0, passed.stderr

    archive = bundle / "dist/api.tar.gz"
    original = archive.read_bytes()
    archive.write_bytes(original + b"tampered")
    tampered = run_helper("verify-directory", "--root", str(bundle))
    assert tampered.returncode == 1
    assert "payload hash/size mismatch" in tampered.stderr
    archive.write_bytes(original)

    archive.unlink()
    missing = run_helper("verify-directory", "--root", str(bundle))
    assert missing.returncode == 1
    assert "not a regular file" in missing.stderr
    archive.write_bytes(original)

    write(bundle / "unexpected file.txt", "not declared\n")
    extra = run_helper("verify-directory", "--root", str(bundle))
    assert extra.returncode == 1
    assert "file set" in extra.stderr
    (bundle / "unexpected file.txt").unlink()

    manifest_path = bundle / "release-bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "npcink.release-bundle.v999"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    update_manifest_checksum(bundle)
    schema = run_helper("verify-directory", "--root", str(bundle))
    assert schema.returncode == 1
    assert "unsupported release bundle manifest schema" in schema.stderr


def test_exact_bundle_requires_one_api_archive_for_all_worker_roles(
    exact_bundle_fixture: tuple[Path, Path, Path],
) -> None:
    _, bundle, _ = exact_bundle_fixture
    manifest_path = bundle / "release-bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["archives"][0]["images"] = [
        image for image in manifest["archives"][0]["images"] if image["role"] != "ops_worker"
    ]
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    update_manifest_checksum(bundle)
    completed = run_helper("verify-directory", "--root", str(bundle))
    assert completed.returncode == 1
    assert "image role set does not exactly match" in completed.stderr


def test_exact_bundle_rejects_extra_unlocked_image_role(
    exact_bundle_fixture: tuple[Path, Path, Path],
) -> None:
    _, bundle, _ = exact_bundle_fixture
    manifest_path = bundle / "release-bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    unexpected = dict(manifest["archives"][0]["images"][0])
    unexpected.update(
        {
            "role": "unexpected",
            "reference": "unexpected:prod",
            "source_reference": "unexpected:prod",
            "primary": False,
        }
    )
    manifest["archives"][0]["images"].append(unexpected)
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    update_manifest_checksum(bundle)

    completed = run_helper("verify-directory", "--root", str(bundle))

    assert completed.returncode == 1
    assert "image role set does not exactly match" in completed.stderr


def test_exact_bundle_rejects_locked_alias_reference_drift(
    exact_bundle_fixture: tuple[Path, Path, Path],
) -> None:
    _, bundle, _ = exact_bundle_fixture
    manifest_path = bundle / "release-bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    worker = next(
        image
        for archive in manifest["archives"]
        for image in archive["images"]
        if image["role"] == "worker"
    )
    worker["reference"] = "unexpected-worker:prod"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    update_manifest_checksum(bundle)

    completed = run_helper("verify-directory", "--root", str(bundle))

    assert completed.returncode == 1
    assert "application image archive set does not match" in completed.stderr


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    (
        ("build", "package_extras", "[zilliz,dev]", "production package extras"),
        ("build", "image_platform", "darwin/arm64", "image platform"),
        ("source", "branch", "../unsafe", "source branch"),
        (
            "production_image_lock",
            "resolved_from_revision",
            123,
            "image-lock hash/schema",
        ),
    ),
)
def test_manifest_rejects_invalid_bounded_fields(
    exact_bundle_fixture: tuple[Path, Path, Path],
    section: str,
    field: str,
    value: object,
    message: str,
) -> None:
    _, bundle, _ = exact_bundle_fixture
    manifest_path = bundle / "release-bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[section][field] = value
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    update_manifest_checksum(bundle)
    completed = run_helper("verify-directory", "--root", str(bundle))
    assert completed.returncode == 1
    assert message in completed.stderr


def test_manifest_rejects_invalid_created_at(
    exact_bundle_fixture: tuple[Path, Path, Path],
) -> None:
    _, bundle, _ = exact_bundle_fixture
    manifest_path = bundle / "release-bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["created_at_utc"] = "not-a-timestamp"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    update_manifest_checksum(bundle)
    completed = run_helper("verify-directory", "--root", str(bundle))
    assert completed.returncode == 1
    assert "manifest created_at_utc" in completed.stderr


def test_source_input_record_must_equal_matching_bundled_payload(
    exact_bundle_fixture: tuple[Path, Path, Path],
) -> None:
    _, bundle, _ = exact_bundle_fixture
    helper = load_helper_module()
    manifest_path = bundle / "release-bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    deploy_group = next(
        group for group in manifest["source_inputs"] if group["name"] == "deploy_tree"
    )
    record = next(
        item for item in deploy_group["files"] if item["path"] == "deploy/verify-release-bundle.sh"
    )
    record["sha256"] = "0" * 64
    deploy_group["sha256"] = helper.tree_digest(deploy_group["files"])
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    update_manifest_checksum(bundle)
    completed = run_helper("verify-directory", "--root", str(bundle))
    assert completed.returncode == 1
    assert "source input and bundled payload disagree" in completed.stderr


def update_scan_receipt_index(bundle: Path, key: str, receipt: dict[str, object]) -> None:
    scan_root = bundle / "release/image-scan"
    receipt_path = scan_root / f"{key}.receipt.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    index_path = scan_root / "scan-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    image = next(item for item in index["images"] if item["image_key"] == key)
    for field in (
        "requested_reference",
        "archive_reference",
        "archive_sha256",
        "config_image_id",
        "syft_subject_manifest_digest",
        "source_daemon_image_id",
        "platform",
        "scanner_docker_context",
        "artifacts",
        "grype_database",
        "blocking_finding_count",
        "unallowlisted_blocking_finding_count",
    ):
        image[field] = receipt[field]
    image["receipt_sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")


def test_scan_evidence_rejects_stale_database_and_post_scan_image_drift(
    exact_bundle_fixture: tuple[Path, Path, Path],
) -> None:
    source, bundle, _ = exact_bundle_fixture
    helper = load_helper_module()
    manifest = json.loads((bundle / "release-bundle-manifest.json").read_text(encoding="utf-8"))
    lock = json.loads((source / "deploy/image-lock/production-images.json").read_text())

    api_receipt_path = bundle / "release/image-scan/api.receipt.json"
    api_receipt = json.loads(api_receipt_path.read_text(encoding="utf-8"))
    api_receipt["grype_database"]["age_hours_at_scan"] = 73
    update_scan_receipt_index(bundle, "api", api_receipt)
    with pytest.raises(helper.BundleError, match="database evidence"):
        helper.validate_scan_evidence(bundle, lock, manifest["archives"], "linux/amd64")

    api_receipt["grype_database"]["age_hours_at_scan"] = 0
    api_receipt["config_image_id"] = "sha256:" + "0" * 64
    update_scan_receipt_index(bundle, "api", api_receipt)
    with pytest.raises(helper.BundleError, match="bundled Docker archive is not the scanned"):
        helper.validate_scan_evidence(bundle, lock, manifest["archives"], "linux/amd64")


def test_finalize_image_records_requires_a_complete_passed_release_index(
    exact_bundle_fixture: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    _, bundle, records = exact_bundle_fixture
    lock_path = bundle / "deploy/image-lock/production-images.json"
    scan_index_path = bundle / "release/image-scan/scan-index.json"
    base_index = json.loads(scan_index_path.read_text())

    passed_output = tmp_path / "passed-images.tsv"
    completed = run_helper(
        "finalize-image-records",
        "--image-lock",
        str(lock_path),
        "--scan-index",
        str(scan_index_path),
        "--input",
        str(records),
        "--output",
        str(passed_output),
    )
    assert completed.returncode == 0, completed.stderr
    assert passed_output.is_file()

    mutations = (
        ("failed-gate", lambda payload: payload.__setitem__("status", "failed")),
        ("missing-field", lambda payload: payload.pop("release_gate")),
        (
            "invalid-platform",
            lambda payload: payload.__setitem__("release_platform", "linux/s390x"),
        ),
        (
            "lock-drift",
            lambda payload: payload.__setitem__("lock_sha256", "0" * 64),
        ),
        (
            "failed-image",
            lambda payload: payload["images"][0].__setitem__("status", "failed"),
        ),
    )
    for label, mutate in mutations:
        payload = json.loads(json.dumps(base_index))
        mutate(payload)
        invalid_index = tmp_path / f"{label}.json"
        invalid_index.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        rejected_output = tmp_path / f"{label}.tsv"
        completed = run_helper(
            "finalize-image-records",
            "--image-lock",
            str(lock_path),
            "--scan-index",
            str(invalid_index),
            "--input",
            str(records),
            "--output",
            str(rejected_output),
        )
        assert completed.returncode == 1, label
        assert "finalization" in completed.stderr, label
        assert not rejected_output.exists(), label


def test_gzip_payload_limit_is_enforced_while_streaming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = load_helper_module()
    monkeypatch.setattr(helper, "MAX_DOCKER_ARCHIVE_BYTES", 64)
    archive = tmp_path / "oversized.tar.gz"
    archive.write_bytes(gzip.compress(b"x" * 65, mtime=0))
    with pytest.raises(helper.BundleError, match="exceeds the uncompressed byte limit"):
        helper.sha256_gzip_payload(archive)


def test_exact_bundle_post_load_uses_portable_archive_config_identity(
    exact_bundle_fixture: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    _, bundle, _ = exact_bundle_fixture
    manifest = json.loads((bundle / "release-bundle-manifest.json").read_text())
    archive_by_reference: dict[str, str] = {}
    daemon_id_by_reference: dict[str, str] = {}
    for archive in manifest["archives"]:
        primary = next(image for image in archive["images"] if image["primary"])
        archive_by_reference[primary["reference"]] = str(bundle / archive["path"])
        for image in archive["images"]:
            daemon_id_by_reference[image["reference"]] = image["source_daemon_image_id"]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        """#!/usr/bin/env python3
import gzip
import json
import os
import shutil
import sys

args = sys.argv[1:]
if args[:2] == ["image", "inspect"]:
    print(json.loads(os.environ["FAKE_DOCKER_IDS"])[args[-1]])
elif args[:2] == ["image", "save"] and args[2] == "--output":
    source = json.loads(os.environ["FAKE_DOCKER_ARCHIVES"])[args[4]]
    with gzip.open(source, "rb") as input_handle, open(args[3], "wb") as output_handle:
        shutil.copyfileobj(input_handle, output_handle)
else:
    raise SystemExit(2)
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["FAKE_DOCKER_IDS"] = json.dumps(daemon_id_by_reference)
    env["FAKE_DOCKER_ARCHIVES"] = json.dumps(archive_by_reference)
    completed = run_helper("verify-directory", "--root", str(bundle), "--post-load", env=env)
    assert completed.returncode == 0, completed.stderr

    wrong_api = tmp_path / "wrong-api.tar.gz"
    write_fixture_docker_archive(
        wrong_api, key="wrong-api", reference="npcink-ai-cloud-api:prod"
    )
    archive_by_reference["npcink-ai-cloud-api:prod"] = str(wrong_api)
    env["FAKE_DOCKER_ARCHIVES"] = json.dumps(archive_by_reference)
    completed = run_helper("verify-directory", "--root", str(bundle), "--post-load", env=env)
    assert completed.returncode == 1
    assert "loaded Docker archive identity mismatch for api" in completed.stderr


def test_archive_preflight_rejects_path_traversal(tmp_path: Path) -> None:
    archive_path = tmp_path / "deploy-bundle.tgz"
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo("../escape")
        info.size = 0
        archive.addfile(info)
    checksum = tmp_path / "deploy-bundle.tgz.sha256"
    checksum.write_text(
        f"{hashlib.sha256(archive_path.read_bytes()).hexdigest()}  {archive_path.name}\n",
        encoding="utf-8",
    )
    completed = run_helper(
        "verify-archive", "--bundle", str(archive_path), "--checksum", str(checksum)
    )
    assert completed.returncode == 1
    assert "unsafe bundle path" in completed.stderr
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize(
    "member_name",
    (".", "./a", "a//b", "a/./b", "a/../b", "a\\b", "control\x01name"),
)
def test_archive_preflight_rejects_noncanonical_paths(tmp_path: Path, member_name: str) -> None:
    archive_path = tmp_path / "deploy-bundle.tgz"
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo(member_name)
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    checksum = tmp_path / "deploy-bundle.tgz.sha256"
    checksum.write_text(
        f"{hashlib.sha256(archive_path.read_bytes()).hexdigest()}  {archive_path.name}\n",
        encoding="utf-8",
    )
    completed = run_helper(
        "verify-archive", "--bundle", str(archive_path), "--checksum", str(checksum)
    )
    assert completed.returncode == 1
    assert "unsafe bundle path" in completed.stderr


def test_archive_preflight_applies_limits_before_extraction(
    exact_bundle_fixture: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    _, bundle, _ = exact_bundle_fixture
    archive = tmp_path / "deploy-bundle.tgz"
    checksum = tmp_path / "deploy-bundle.tgz.sha256"
    assert (
        run_helper(
            "pack",
            "--root",
            str(bundle),
            "--output",
            str(archive),
            "--gzip-level",
            "1",
            "--mtime",
            "0",
        ).returncode
        == 0
    )
    assert (
        run_helper("checksum", "--bundle", str(archive), "--output", str(checksum)).returncode == 0
    )
    helper = load_helper_module()
    helper.MAX_TAR_UNCOMPRESSED_BYTES = 1
    with pytest.raises(helper.BundleError, match="uncompressed byte limit"):
        helper.verify_archive(archive, checksum)


def test_exact_bundle_pack_outer_hash_and_archive_preflight(
    exact_bundle_fixture: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    _, bundle, _ = exact_bundle_fixture
    archive = tmp_path / "deploy-bundle.tgz"
    checksum = tmp_path / "deploy-bundle.tgz.sha256"
    packed = run_helper(
        "pack",
        "--root",
        str(bundle),
        "--output",
        str(archive),
        "--gzip-level",
        "1",
        "--mtime",
        "0",
    )
    assert packed.returncode == 0, packed.stderr
    written = run_helper("checksum", "--bundle", str(archive), "--output", str(checksum))
    assert written.returncode == 0, written.stderr
    verified = run_helper("verify-archive", "--bundle", str(archive), "--checksum", str(checksum))
    assert verified.returncode == 0, verified.stderr

    archive.write_bytes(archive.read_bytes() + b"changed after receipt")
    rejected = run_helper("verify-archive", "--bundle", str(archive), "--checksum", str(checksum))
    assert rejected.returncode == 1
    assert "outer bundle checksum mismatch" in rejected.stderr


def test_external_plan_consumes_digest_locked_caddy_without_hardcoding(tmp_path: Path) -> None:
    lock = tmp_path / "production-images.json"
    lock.write_text(json.dumps(image_lock()) + "\n", encoding="utf-8")
    output = tmp_path / "plan.tsv"
    completed = run_helper("external-plan", "--image-lock", str(lock), "--output", str(output))
    assert completed.returncode == 0, completed.stderr
    assert "caddy\tcaddy:2-alpine@sha256:" in output.read_text(encoding="utf-8")


def test_formal_bundle_dirty_tree_fails_before_docker(tmp_path: Path) -> None:
    repo = tmp_path / "dirty-repo"
    (repo / "deploy").mkdir(parents=True)
    script = repo / "deploy/bundle-images.sh"
    script.write_bytes((ROOT / "deploy/bundle-images.sh").read_bytes())
    script.chmod(0o755)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "deploy/bundle-images.sh"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.com",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=repo,
        check=True,
    )
    write(repo / "dirty.txt")
    completed = subprocess.run(["bash", str(script)], cwd=repo, text=True, capture_output=True)
    assert completed.returncode == 1
    assert "requires a clean Git worktree" in completed.stderr
    assert "docker is required" not in completed.stderr


def test_release_scripts_enforce_pre_and_post_load_and_same_bundle_replay() -> None:
    bundle = (ROOT / "deploy/bundle-images.sh").read_text(encoding="utf-8")
    loader = (ROOT / "deploy/remote-load-and-up.sh").read_text(encoding="utf-8")
    ssh_deploy = (ROOT / "deploy/deploy-to-ssh-host.sh").read_text(encoding="utf-8")
    smoke = (ROOT / "scripts/cloud-deploy-bundle-smoke-flow.sh").read_text(encoding="utf-8")

    assert "status --porcelain=v1 --untracked-files=all" in bundle
    assert "NPCINK_CLOUD_ALLOW_DIRTY" not in bundle
    assert 'git -C "${CLOUD_DIR}" archive HEAD' in bundle
    assert "production-images.json" in bundle
    assert "external-plan" in bundle
    assert "postgres:16-alpine|" not in bundle
    assert bundle.count("Building API image exactly once") == 1
    assert "dist/worker.tar.gz" not in bundle
    assert "deploy-bundle.tgz.sha256" in bundle
    assert 'INCLUDE_EXTERNAL_IMAGES="${NPCINK_CLOUD_INCLUDE_EXTERNAL_IMAGES:-1}"' in bundle
    assert "must include every locked external image" in bundle
    assert "must include the frontend image" in bundle
    assert "scan-production-images.sh" in bundle
    scan_index = bundle.index('bash "${CLOUD_DIR}/scripts/scan-production-images.sh"')
    first_package = bundle.index("package_scanned_image api dist/api.tar.gz")
    assert scan_index < first_package
    assert "docker save" not in bundle
    assert 'gzip -n "-${GZIP_LEVEL}" -c "${archive_path}"' in bundle

    pre_index = loader.index("verify exact bundle before load")
    load_index = loader.index("gzip -dc")
    post_index = loader.index("verify loaded image IDs")
    up_index = loader.index("compose up services")
    assert pre_index < load_index < post_index < up_index
    assert "load-plan" in loader and "alias-plan" in loader
    assert "--pull never --no-build" in loader

    remote_verify_index = ssh_deploy.index("verify remote deploy bundle before extraction")
    remote_extract_index = ssh_deploy.index("remote extract bundle")
    assert remote_verify_index < remote_extract_index
    assert 'BUNDLE_CHECKSUM_PATH="${BUNDLE_PATH}.sha256"' in ssh_deploy

    verify_index = smoke.index("Verifying exact bundle before extraction")
    extract_index = smoke.index("Extracting deploy bundle")
    assert verify_index < extract_index
    assert smoke.count("run_deploy_command bash deploy/remote-load-and-up.sh") == 2
    assert "same exact bundle receipt was reused" in smoke
    assert "preflight_status=\\$?" in ssh_deploy
    assert 'rm -rf $(remote_shell_arg "${REMOTE_PREFLIGHT_DIR}")' in ssh_deploy


def test_manifest_helper_keeps_python39_floor_and_no_unsafe_tar_extract() -> None:
    source = HELPER.read_text(encoding="utf-8")
    ast.parse(source, feature_version=(3, 9))
    assert "dt.UTC" not in source
    assert ".extractall(" not in source
    assert ".getmembers(" not in source
    assert "MAX_TAR_UNCOMPRESSED_BYTES = 20 * 1024 * 1024 * 1024" in source
    assert "MAX_DOCKER_ARCHIVE_BYTES = 4 * 1024 * 1024 * 1024" in source
    assert "REQUIRED_MAX_DATABASE_AGE_HOURS = 72" in source
