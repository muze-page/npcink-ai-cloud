#!/usr/bin/env python3
"""Verify that a production environment exactly matches a uv locked export."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

SCHEMA_VERSION = "npcink-ai-cloud.production-python-lock.v1"
SUPPORTED_PACKAGE_EXTRAS = {
    "": (),
    "[dev]": ("dev",),
    "[zilliz]": ("zilliz",),
    "[dev,zilliz]": ("dev", "zilliz"),
}
BOOTSTRAP_DISTRIBUTIONS = frozenset({"pip"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _selected_extras(package_extras: str) -> tuple[str, ...]:
    if package_extras not in SUPPORTED_PACKAGE_EXTRAS:
        supported = ", ".join(repr(value) for value in sorted(SUPPORTED_PACKAGE_EXTRAS))
        raise SystemExit(
            f"Unsupported PACKAGE_EXTRAS {package_extras!r}; expected one of: {supported}"
        )
    return SUPPORTED_PACKAGE_EXTRAS[package_extras]


def _locked_distributions(requirements_path: Path, package_extras: str) -> dict[str, str]:
    selected_extras = _selected_extras(package_extras)
    expected: dict[str, str] = {}

    for line_number, raw_line in enumerate(requirements_path.read_text().splitlines(), start=1):
        if not raw_line or raw_line.isspace() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line[0].isspace():
            # Hash continuations are validated by pip --require-hashes during the build.
            continue

        requirement_text = raw_line.rstrip().removesuffix("\\").rstrip()
        if requirement_text.startswith("-"):
            raise SystemExit(
                f"Unsupported requirements directive at {requirements_path}:{line_number}: "
                f"{requirement_text}"
            )

        requirement = Requirement(requirement_text)
        if requirement.marker is not None:
            marker_extras = ("", *selected_extras)
            if not any(
                requirement.marker.evaluate({"extra": selected_extra})
                for selected_extra in marker_extras
            ):
                continue
        if requirement.url is not None:
            raise SystemExit(
                f"URL requirement is not a locked distribution at "
                f"{requirements_path}:{line_number}: {requirement_text}"
            )

        specifiers = list(requirement.specifier)
        if (
            len(specifiers) != 1
            or specifiers[0].operator != "=="
            or specifiers[0].version.endswith(".*")
        ):
            raise SystemExit(
                f"Requirement is not exactly pinned at {requirements_path}:{line_number}: "
                f"{requirement_text}"
            )

        name = canonicalize_name(requirement.name)
        version = specifiers[0].version
        previous = expected.setdefault(name, version)
        if previous != version:
            raise SystemExit(
                f"Conflicting active versions for {name}: {previous!r} and {version!r}"
            )

    if not expected:
        raise SystemExit(f"No active locked distributions found in {requirements_path}")
    if BOOTSTRAP_DISTRIBUTIONS.intersection(expected):
        overlap = sorted(BOOTSTRAP_DISTRIBUTIONS.intersection(expected))
        raise SystemExit(f"Bootstrap ignore overlaps locked runtime distributions: {overlap}")
    return expected


def _installed_distributions() -> dict[str, str]:
    installed: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        raw_name = distribution.metadata.get("Name")
        if not raw_name:
            raise SystemExit(f"Installed distribution without Name metadata: {distribution!r}")
        name = canonicalize_name(raw_name)
        version = distribution.version
        previous = installed.setdefault(name, version)
        if previous != version:
            raise SystemExit(
                f"Multiple installed versions for {name}: {previous!r} and {version!r}"
            )
    return installed


def _verify_distribution_graph(
    expected_distributions: dict[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    installed = _installed_distributions()
    bootstrap = {
        name: version for name, version in installed.items() if name in BOOTSTRAP_DISTRIBUTIONS
    }
    runtime_distributions = {
        name: version for name, version in installed.items() if name not in BOOTSTRAP_DISTRIBUTIONS
    }
    if expected_distributions != runtime_distributions:
        missing = {
            name: version
            for name, version in expected_distributions.items()
            if name not in runtime_distributions
        }
        unexpected = {
            name: version
            for name, version in runtime_distributions.items()
            if name not in expected_distributions
        }
        mismatched = {
            name: {
                "expected": expected_distributions[name],
                "actual": runtime_distributions[name],
            }
            for name in expected_distributions.keys() & runtime_distributions.keys()
            if expected_distributions[name] != runtime_distributions[name]
        }
        raise SystemExit(
            "Installed production distributions do not match the locked export:\n"
            + json.dumps(
                {
                    "missing": missing,
                    "unexpected": unexpected,
                    "version_mismatches": mismatched,
                },
                indent=2,
                sort_keys=True,
            )
        )
    return runtime_distributions, bootstrap


def _assert_distribution_expectations(
    runtime_distributions: dict[str, str],
    *,
    expected: tuple[str, ...] | list[str],
    forbidden: tuple[str, ...] | list[str],
) -> None:
    expected_names = {canonicalize_name(name) for name in expected}
    forbidden_names = {canonicalize_name(name) for name in forbidden}
    if "" in expected_names or "" in forbidden_names:
        raise SystemExit("Distribution expectations cannot contain an empty name")
    overlap = expected_names & forbidden_names
    if overlap:
        raise SystemExit(f"Distributions cannot be both expected and forbidden: {sorted(overlap)}")

    missing = sorted(expected_names - runtime_distributions.keys())
    if missing:
        raise SystemExit(f"Expected distributions are missing: {missing}")
    installed_forbidden = sorted(forbidden_names & runtime_distributions.keys())
    if installed_forbidden:
        raise SystemExit(f"Forbidden distributions are installed: {installed_forbidden}")


def _distribution_entries(distributions: dict[str, str]) -> list[dict[str, str]]:
    return [{"name": name, "version": distributions[name]} for name in sorted(distributions)]


def _build_manifest(
    *,
    package_extras: str,
    uv_version: str,
    uv_lock_path: Path,
    requirements_path: Path,
    runtime_distributions: dict[str, str],
    bootstrap_distributions: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "package_extras": package_extras,
        "uv_version": uv_version,
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "uv_lock_sha256": _sha256(uv_lock_path),
        "requirements_sha256": _sha256(requirements_path),
        "distributions": _distribution_entries(runtime_distributions),
        "bootstrap_distributions": _distribution_entries(bootstrap_distributions),
    }


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def _check_manifest(path: Path, expected_manifest: dict[str, Any]) -> None:
    actual_manifest = json.loads(path.read_text())
    if actual_manifest != expected_manifest:
        raise SystemExit(
            f"Production dependency manifest mismatch at {path}:\n"
            + json.dumps(
                {"expected": expected_manifest, "actual": actual_manifest},
                indent=2,
                sort_keys=True,
            )
        )


def _import_app() -> None:
    import app.api.main  # noqa: F401, PLC0415


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--uv-lock", type=Path, required=True)
    parser.add_argument("--package-extras", required=True)
    parser.add_argument("--uv-version", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write-manifest", type=Path)
    action.add_argument("--check-manifest", type=Path)
    parser.add_argument("--expect-distribution", action="append", default=[])
    parser.add_argument("--forbid-distribution", action="append", default=[])
    parser.add_argument("--import-app", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    expected = _locked_distributions(args.requirements, args.package_extras)
    runtime, bootstrap = _verify_distribution_graph(expected)
    _assert_distribution_expectations(
        runtime,
        expected=args.expect_distribution,
        forbidden=args.forbid_distribution,
    )
    manifest = _build_manifest(
        package_extras=args.package_extras,
        uv_version=args.uv_version,
        uv_lock_path=args.uv_lock,
        requirements_path=args.requirements,
        runtime_distributions=runtime,
        bootstrap_distributions=bootstrap,
    )

    if args.write_manifest is not None:
        _write_manifest(args.write_manifest, manifest)
    else:
        _check_manifest(args.check_manifest, manifest)

    if args.import_app:
        _import_app()

    print(
        json.dumps(
            {
                "status": "ok",
                "app_import_ok": args.import_app,
                "package_extras": args.package_extras,
                "distribution_count": len(runtime),
                "uv_lock_sha256": manifest["uv_lock_sha256"],
                "requirements_sha256": manifest["requirements_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
