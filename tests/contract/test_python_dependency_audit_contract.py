from __future__ import annotations

import importlib.util
import json
import re
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _production_lock_verifier() -> ModuleType:
    path = ROOT / "scripts" / "verify-production-python-lock.py"
    spec = importlib.util.spec_from_file_location("production_python_lock_verifier", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _locked_project() -> dict[str, object]:
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    return next(
        package
        for package in lock["package"]
        if package["name"] == "npcink-ai-cloud"
    )


def test_pillow_security_floor_and_lock_are_exact() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    project = _locked_project()

    assert "Pillow>=12.3,<13.0" in pyproject["project"]["dependencies"]
    assert [
        package["version"]
        for package in lock["package"]
        if package["name"] == "pillow"
    ] == ["12.3.0"]
    assert {
        requirement["specifier"]
        for requirement in project["metadata"]["requires-dist"]
        if requirement["name"] == "pillow"
    } == {">=12.3,<13.0"}


def test_zilliz_dependency_remains_optional_in_lock() -> None:
    project = _locked_project()

    assert "pymilvus" not in {
        dependency["name"] for dependency in project["dependencies"]
    }
    assert project["optional-dependencies"]["zilliz"] == [{"name": "pymilvus"}]
    assert {
        requirement.get("marker")
        for requirement in project["metadata"]["requires-dist"]
        if requirement["name"] == "pymilvus"
    } == {"extra == 'zilliz'"}
    assert set(project["metadata"]["provides-extras"]) == {"dev", "zilliz"}


def test_dependency_audit_is_locked_hashed_and_covers_production_variants() -> None:
    script = (ROOT / "scripts" / "check-python-dependency-audit.sh").read_text()
    package_scripts = json.loads((ROOT / "package.json").read_text())["scripts"]

    assert 'PIP_AUDIT_VERSION="2.10.1"' in script
    assert '"${UV_BIN}" lock --check' in script
    assert "--locked" in script
    assert "--no-emit-project" in script
    assert "--disable-pip" in script
    assert "--require-hashes" in script
    assert "audit_export default" in script
    assert "audit_export zilliz --extra zilliz" in script
    assert package_scripts["check:python-dependency-audit"] == (
        "bash scripts/check-python-dependency-audit.sh"
    )


def test_ci_blocks_backend_and_keeps_production_deploy_separate() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "python-dependency-audit:" in workflow
    assert "run: bash scripts/check-python-dependency-audit.sh" in workflow
    assert "PYTHON_DEPENDENCY_AUDIT_RESULT" in workflow
    assert "python dependency audit did not pass" in workflow
    assert "deploy-production:" not in workflow
    assert "PROD_SSH_KEY" not in workflow


def test_gitleaks_fixture_ignores_are_exact_reviewed_fingerprints() -> None:
    ignore_lines = [
        line.strip()
        for line in (ROOT / ".gitleaksignore").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert ignore_lines == [
        "86ac095d3fd9b4d8fa9bcfad902ae5ed8c699b86:"
        "tests/domain/test_payment_gateways.py:private-key:173",
        "45dc5ef1e91b00c819ba74f32aec98dc5bcdad1f:"
        "tests/core/test_logging_redaction.py:jwt:56",
    ]


def test_production_dockerfile_consumes_the_locked_hashed_runtime_graph() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert "COPY pyproject.toml uv.lock README.md alembic.ini ./" in dockerfile
    assert (
        "COPY scripts/verify-production-python-lock.py "
        "./scripts/verify-production-python-lock.py" in dockerfile
    )
    assert 'UV_VERSION="0.11.29"' in dockerfile
    assert re.search(
        r"^FROM ghcr[.]io/astral-sh/uv:0[.]11[.]29@sha256:[0-9a-f]{64} AS uv$",
        dockerfile,
        re.MULTILINE,
    )
    assert "COPY --from=uv /uv /usr/local/bin/uv" in dockerfile
    assert '"uv==${UV_VERSION}"' not in dockerfile
    assert "uv export" in dockerfile
    assert "--locked" in dockerfile
    assert "--no-dev" in dockerfile
    assert "--no-emit-project" in dockerfile
    assert dockerfile.count("--no-header") == 4
    assert "--require-hashes" in dockerfile
    assert "verify-production-python-lock.py" in dockerfile
    assert "production-python-lock.json" in dockerfile
    assert dockerfile.count("verify-production-python-lock.py") >= 4
    assert "--check-manifest /usr/local/share/npcink-ai-cloud/production-python-lock.json" in (
        dockerfile
    )
    assert "--import-app" in dockerfile
    assert "RUN PYTHONPATH=/app python scripts/verify-production-python-lock.py" in dockerfile
    assert dockerfile.index("COPY app ./app") < dockerfile.index("--check-manifest")
    assert dockerfile.index("--check-manifest") < dockerfile.index("USER app")
    assert "--upgrade pip" not in dockerfile
    assert '"setuptools>=69"' not in dockerfile
    assert "pip wheel" not in dockerfile
    assert re.search(r"\bset\s+-[a-z]*x[a-z]*\b", dockerfile) is None
    assert "set -o xtrace" not in dockerfile
    assert "set -eu;" in dockerfile
    assert "ARG PIP_INDEX_URL" not in dockerfile
    assert "ARG PIP_EXTRA_INDEX_URL" not in dockerfile
    assert "ARG PIP_TRUSTED_HOST" not in dockerfile
    assert "--mount=type=secret,id=pip_index_url,required=false" in dockerfile
    assert "--mount=type=secret,id=pip_extra_index_url,required=false" in dockerfile
    assert "--mount=type=secret,id=pip_trusted_host,required=false" in dockerfile
    assert "$(cat /run/secrets/pip_index_url)" in dockerfile


def test_dockerfile_locks_supported_package_extras_and_rejects_unknown_values() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    dev_zilliz_branch = dockerfile.split(
        'if [ "${PACKAGE_EXTRAS}" = "[dev,zilliz]" ]; then', maxsplit=1
    )[1].split('elif [ "${PACKAGE_EXTRAS}" = "[dev]" ]; then', maxsplit=1)[0]
    dev_branch = dockerfile.split('elif [ "${PACKAGE_EXTRAS}" = "[dev]" ]; then', maxsplit=1)[
        1
    ].split('elif [ "${PACKAGE_EXTRAS}" = "[zilliz]" ]; then', maxsplit=1)[0]

    assert 'case "${PACKAGE_EXTRAS}" in' in dockerfile
    assert '"[dev]")' in dockerfile
    assert '"[zilliz]")' in dockerfile
    assert '"[dev,zilliz]")' in dockerfile
    assert "uv export" in dev_zilliz_branch
    assert "--locked" in dev_zilliz_branch
    assert "--extra dev --extra zilliz" in dev_zilliz_branch
    assert "uv export" in dev_branch
    assert "--locked" in dev_branch
    assert "--extra dev" in dev_branch
    assert "Unsupported PACKAGE_EXTRAS" in dockerfile
    assert "exit 64" in dockerfile


def test_runtime_image_installs_shell_contract_tools_only_for_dev_package_extras() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    runtime_stage, development_and_production = dockerfile.rsplit(
        "FROM python:3.14-alpine@sha256:", maxsplit=1
    )[1].split("FROM runtime AS development", maxsplit=1)
    development_stage, production_stage = development_and_production.split(
        "FROM runtime AS production", maxsplit=1
    )
    dev_branch = re.search(
        r'"\[dev\]"\|"\[dev,zilliz\]"\)(?P<body>.*?) ;;',
        development_stage,
        re.DOTALL,
    )
    development_compose = (ROOT / "docker-compose.dev.yml").read_text()

    assert dev_branch is not None
    package_install = "apk add --no-cache bash coreutils curl git openssl"
    assert package_install in dev_branch.group("body")
    assert development_stage.count(package_install) == 1
    assert package_install not in runtime_stage
    assert package_install not in production_stage
    assert production_stage.strip() == ""
    assert development_compose.count("target: development") == 4
    assert development_compose.count('PACKAGE_EXTRAS: "[dev,zilliz]"') == 4


def test_production_lock_verifier_compares_the_complete_distribution_set() -> None:
    verifier = (ROOT / "scripts" / "verify-production-python-lock.py").read_text()

    assert "importlib.metadata.distributions" in verifier
    assert "Requirement" in verifier
    assert 'BOOTSTRAP_DISTRIBUTIONS = frozenset({"pip"})' in verifier
    assert "expected_distributions != runtime_distributions" in verifier
    assert '"uv_lock_sha256"' in verifier
    assert '"requirements_sha256"' in verifier
    assert "import app.api.main" in verifier


@pytest.mark.parametrize(
    ("package_extras", "selected"),
    [
        ("", ()),
        ("[dev]", ("dev",)),
        ("[zilliz]", ("zilliz",)),
        ("[dev,zilliz]", ("dev", "zilliz")),
    ],
)
def test_production_lock_verifier_supports_exact_extra_variants(
    package_extras: str,
    selected: tuple[str, ...],
) -> None:
    verifier = _production_lock_verifier()

    assert verifier._selected_extras(package_extras) == selected


def test_production_lock_verifier_rejects_unknown_extra_variants() -> None:
    verifier = _production_lock_verifier()

    with pytest.raises(SystemExit, match="Unsupported PACKAGE_EXTRAS"):
        verifier._selected_extras("[zilliz,dev]")


def test_production_lock_verifier_reports_missing_and_unexpected_distributions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _production_lock_verifier()

    monkeypatch.setattr(
        verifier,
        "_installed_distributions",
        lambda: {"pip": "25.0", "alpha": "1.0"},
    )
    with pytest.raises(SystemExit, match='"beta": "2.0"'):
        verifier._verify_distribution_graph({"alpha": "1.0", "beta": "2.0"})

    monkeypatch.setattr(
        verifier,
        "_installed_distributions",
        lambda: {"pip": "25.0", "alpha": "1.0", "rogue": "9.0"},
    )
    with pytest.raises(SystemExit, match='"rogue": "9.0"'):
        verifier._verify_distribution_graph({"alpha": "1.0"})


def test_production_lock_verifier_rejects_manifest_tampering(tmp_path: Path) -> None:
    verifier = _production_lock_verifier()
    requirements = tmp_path / "requirements.txt"
    uv_lock = tmp_path / "uv.lock"
    manifest_path = tmp_path / "manifest.json"
    requirements.write_text("alpha==1.0 --hash=sha256:" + "a" * 64 + "\n")
    uv_lock.write_text("version = 1\n")
    manifest = verifier._build_manifest(
        package_extras="",
        uv_version="0.11.29",
        uv_lock_path=uv_lock,
        requirements_path=requirements,
        runtime_distributions={"alpha": "1.0"},
        bootstrap_distributions={"pip": "25.0"},
    )
    manifest_path.write_text(json.dumps({**manifest, "package_extras": "[zilliz]"}))

    with pytest.raises(SystemExit, match="manifest mismatch"):
        verifier._check_manifest(manifest_path, manifest)


def test_production_lock_verifier_enforces_distribution_presence() -> None:
    verifier = _production_lock_verifier()

    verifier._assert_distribution_expectations(
        {"alpha": "1.0", "pymilvus": "2.6.16"},
        expected=("pymilvus",),
        forbidden=(),
    )
    with pytest.raises(SystemExit, match="Expected distributions are missing"):
        verifier._assert_distribution_expectations(
            {"alpha": "1.0"},
            expected=("pymilvus",),
            forbidden=(),
        )
    with pytest.raises(SystemExit, match="Forbidden distributions are installed"):
        verifier._assert_distribution_expectations(
            {"alpha": "1.0", "pymilvus": "2.6.16"},
            expected=(),
            forbidden=("pymilvus",),
        )


def test_production_image_smoke_verifies_default_and_zilliz_locked_graphs() -> None:
    script = (ROOT / "scripts" / "production-python-extras-smoke.sh").read_text()

    assert "verify-production-python-lock.py" in script
    assert "--check-manifest" in script
    assert "--import-app" in script
    assert 'UV_VERSION="0.11.29"' in script
    assert 'UVX_BIN="${UVX_BIN:-uvx}"' in script
    assert '"uv==${UV_VERSION}"' in script
    assert "--no-header" in script
    assert ":/tmp/expected-requirements.txt:ro" in script
    assert "--forbid-distribution pymilvus" in script
    assert "--expect-distribution pymilvus" in script
    assert 'verify_image "${DEFAULT_TAG}" "" "forbid"' in script
    assert 'verify_image "${ZILLIZ_TAG}" "[zilliz]" "expect"' in script
    assert "NPCINK_CLOUD_PROD_EXTRAS_SKIP_ZILLIZ" in script


def test_bundle_passes_optional_pip_indexes_only_as_buildkit_secrets() -> None:
    bundle_script = (ROOT / "deploy" / "bundle-images.sh").read_text()

    for env_name, secret_id in (
        ("NPCINK_CLOUD_PIP_INDEX_URL", "pip_index_url"),
        ("NPCINK_CLOUD_PIP_EXTRA_INDEX_URL", "pip_extra_index_url"),
        ("NPCINK_CLOUD_PIP_TRUSTED_HOST", "pip_trusted_host"),
    ):
        assert f'id={secret_id},env={env_name}' in bundle_script
        assert f'--build-arg "{env_name}=' not in bundle_script
        assert f'--build-arg "{env_name.removeprefix("NPCINK_CLOUD_")}=' not in bundle_script
    assert 'BUILD_ARGS=(--build-arg "PACKAGE_EXTRAS=${PACKAGE_EXTRAS}")' in bundle_script
    assert 'docker buildx build --platform "${MANIFEST_IMAGE_PLATFORM}"' in bundle_script
    unsafe_compose_build = (
        'docker compose -f "${CLOUD_DIR}/docker-compose.prod.yml" '
        'build "${BUILD_ARGS[@]}"'
    )
    assert unsafe_compose_build not in bundle_script
