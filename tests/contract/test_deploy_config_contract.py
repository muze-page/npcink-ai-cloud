from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

from app.core.config import Settings

SERVICE_SETTINGS_ROOT = base64.urlsafe_b64encode(b"s" * 32).decode("ascii")
RUNTIME_DATA_ROOT = base64.urlsafe_b64encode(b"r" * 32).decode("ascii")
SERVICE_SETTINGS_KEY_ID = "service-settings-v1"
RUNTIME_DATA_KEY_ID = "runtime-data-v1"


def _cloud_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_first_install_preparation_refuses_unmanaged_source_tree_before_mutation(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "shared" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "runtime-config.json").write_text("{}")
    environment = os.environ.copy()
    environment["NPCINK_CLOUD_CONFIG_DIR_HOST"] = str(config_dir)
    environment["NPCINK_CLOUD_RELEASE_TOOL_PYTHON"] = sys.executable

    result = subprocess.run(
        ["bash", str(_cloud_root() / "deploy" / "prepare-first-install.sh")],
        cwd=_cloud_root(),
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "direct managed release-* directory" in result.stderr
    assert not (config_dir / "install-state.json").exists()
    assert not (config_dir / "setup-auth.json").exists()


def test_prepare_setup_code_rotation_refuses_unmanaged_source_tree(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "shared" / "config"
    config_dir.mkdir(parents=True, mode=0o700)
    (config_dir / "install-state.json").write_text(
        json.dumps(
            {
                "installation_state": "pending",
                "retry_allowed": True,
                "setup_revision": "first-install-v1",
                "updated_at": "2026-07-22T00:00:00Z",
            }
        )
    )
    (config_dir / "install-state.json").chmod(0o640)
    environment = os.environ.copy()
    environment["NPCINK_CLOUD_CONFIG_DIR_HOST"] = str(config_dir)
    environment["NPCINK_CLOUD_RELEASE_TOOL_PYTHON"] = sys.executable

    result = subprocess.run(
        ["bash", str(_cloud_root() / "deploy" / "prepare-first-install.sh"), "--rotate"],
        cwd=_cloud_root(),
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "direct managed release-* directory" in result.stderr
    assert "nca_setup_" not in result.stdout
    assert not (config_dir / "setup-auth.json").exists()


def test_unmanaged_setup_code_rotation_does_not_mutate_retry_or_auth_evidence(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "shared" / "config"
    config_dir.mkdir(parents=True, mode=0o700)
    state_path = config_dir / "install-state.json"
    state_path.write_text(
        json.dumps(
            {
                "attempt_id": "install_interrupted",
                "idempotency_key_sha256": "a" * 64,
                "install_request_hmac_sha256": "b" * 64,
                "installation_state": "pending",
                "retry_allowed": True,
                "setup_revision": "first-install-v1",
                "updated_at": "2026-07-22T00:00:00Z",
            }
        )
    )
    state_path.chmod(0o640)
    auth_path = config_dir / "setup-auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "created_at": "2026-07-22T00:00:00Z",
                "session_secret": "x" * 43,
                "setup_code_sha256": "c" * 64,
            }
        )
    )
    auth_path.chmod(0o600)
    original_state = state_path.read_bytes()
    original_auth = auth_path.read_bytes()
    environment = os.environ.copy()
    environment["NPCINK_CLOUD_CONFIG_DIR_HOST"] = str(config_dir)
    environment["NPCINK_CLOUD_RELEASE_TOOL_PYTHON"] = sys.executable

    result = subprocess.run(
        ["bash", str(_cloud_root() / "deploy" / "prepare-first-install.sh"), "--rotate"],
        cwd=_cloud_root(),
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "direct managed release-* directory" in result.stderr
    assert "nca_setup_" not in result.stdout
    assert state_path.read_bytes() == original_state
    assert auth_path.read_bytes() == original_auth


def _release_policy_fixture_root(tmp_path: Path, dependabot_text: str) -> Path:
    cloud_root = _cloud_root()
    fixture_root = tmp_path / "release-policy-fixture"
    fixture_root.mkdir(parents=True)

    for name in (
        "AGENTS.md",
        ".env.example",
        "docker-compose.dev.yml",
        "docker-compose.pg18-proof.yml",
        "docker-compose.p5-b4-runtime-proof.yml",
        "docker-compose.prod.yml",
        "docker-compose.runtime.yml",
        "package.json",
        "Makefile",
        "README.md",
        "docs",
        "deploy",
        "site",
    ):
        source = cloud_root / name
        (fixture_root / name).symlink_to(source, target_is_directory=source.is_dir())

    fixture_github = fixture_root / ".github"
    fixture_github.mkdir()
    (fixture_github / "pull_request_template.md").symlink_to(
        cloud_root / ".github" / "pull_request_template.md"
    )
    (fixture_github / "workflows").symlink_to(
        cloud_root / ".github" / "workflows", target_is_directory=True
    )
    (fixture_github / "dependabot.yml").write_text(dependabot_text)

    fixture_scripts = fixture_root / "scripts"
    fixture_scripts.mkdir()
    shutil.copy2(
        cloud_root / "scripts" / "check-release-policy.sh",
        fixture_scripts / "check-release-policy.sh",
    )
    for name in (
        "bundle-images.sh",
        "alembic_revision_gate.py",
        "check-first-install-cve-gate.py",
        "check-pg18-proof.sh",
        "check-pr-backend-gate.sh",
        "classify-ci-changes.sh",
        "cloud-deploy-bundle-smoke-flow.sh",
        "dev-compose.sh",
        "dev-frontend-recover.sh",
        "local-alpha-smoke.sh",
        "production-image-supply.py",
        "production-python-extras-smoke.sh",
        "pg18-semantic-proof.py",
        "verify-release-bundle-manifest.py",
    ):
        (fixture_scripts / name).symlink_to(cloud_root / "scripts" / name)

    return fixture_root


def _run_release_policy_with_restricted_path(
    fixture_root: Path, tmp_path: Path
) -> subprocess.CompletedProcess[str]:
    restricted_bin = tmp_path / "release-policy-bin"
    restricted_bin.mkdir(exist_ok=True)
    for command in ("awk", "cmp", "cut", "dirname", "git", "grep"):
        command_path = shutil.which(command)
        assert command_path is not None
        destination = restricted_bin / command
        if not destination.exists():
            destination.symlink_to(command_path)

    assert shutil.which("uv", path=str(restricted_bin)) is None
    return subprocess.run(
        ["/bin/bash", str(fixture_root / "scripts" / "check-release-policy.sh")],
        cwd=fixture_root,
        env={"PATH": str(restricted_bin)},
        text=True,
        capture_output=True,
        check=False,
    )


def _inflate_compose_service_block(
    compose_path: Path,
    service: str,
    *,
    marker_after_header: str = "",
) -> None:
    compose_text = compose_path.read_text()
    service_block = _compose_service_block(compose_text, service)
    service_header = f"  {service}:\n"
    assert service_block.startswith(service_header)

    if marker_after_header:
        service_block = service_block.replace(
            service_header,
            service_header + marker_after_header,
            1,
        )

    large_safe_tail = "".join(
        f"    # release-policy-pipefill-{index:05d}-{'x' * 64}\n"
        for index in range(16_384)
    )
    inflated_text = compose_text.replace(
        _compose_service_block(compose_text, service),
        service_block + "\n" + large_safe_tail,
        1,
    )

    compose_path.unlink()
    compose_path.write_text(inflated_text)


def _documented_env_value(text: str, key: str) -> str:
    prefix = f"{key}="
    for token in text.replace("`", " ").split():
        if token.startswith(prefix):
            return token.removeprefix(prefix).rstrip(".,;")
    return ""


def _documented_https_host(text: str, key: str) -> str:
    parsed = urlsplit(_documented_env_value(text, key))
    return parsed.netloc if parsed.scheme == "https" else ""


def _nginx_location_block(text: str, location: str) -> str:
    return text.split(f"location {location} {{", 1)[1].split("\n    }", 1)[0]


def _compose_service_block(text: str, service: str) -> str:
    lines = text.splitlines()
    marker = f"  {service}:"
    start = lines.index(marker)
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            break
        block.append(line)
    return "\n".join(block)


def _compose_environment_keys(service_block: str) -> set[str]:
    lines = service_block.splitlines()
    environment_index = lines.index("    environment:")
    keys: set[str] = set()
    for line in lines[environment_index + 1 :]:
        if not line.startswith("      "):
            break
        keys.add(line.strip().split(":", 1)[0])
    return keys


def test_dev_compose_wrapper_layers_local_env_for_frontend_token(
    tmp_path: Path,
) -> None:
    cloud_root = _cloud_root()
    wrapper_text = (cloud_root / "scripts" / "dev-compose.sh").read_text()
    dev_compose = (cloud_root / "docker-compose.dev.yml").read_text()
    package_scripts = json.loads((cloud_root / "package.json").read_text())["scripts"]
    makefile = (cloud_root / "Makefile").read_text()
    recover_script = (cloud_root / "scripts" / "dev-frontend-recover.sh").read_text()

    expected_dev_scripts = {
        "dev": "bash scripts/dev-compose.sh up --build",
        "dev:runtime": "bash scripts/dev-compose.sh --profile runtime up --build",
        "dev:callback": (
            "bash scripts/dev-compose.sh --profile runtime --profile callback up --build"
        ),
        "dev:ops": (
            "bash scripts/dev-compose.sh --profile runtime --profile callback "
            "--profile ops up --build"
        ),
    }
    assert {name: package_scripts[name] for name in expected_dev_scripts} == expected_dev_scripts
    assert "dev:\n\tbash scripts/dev-compose.sh up --build" in makefile
    assert "docker compose" not in recover_script
    assert recover_script.count('"${COMPOSE_CMD[@]}"') == 4

    fixture_root = tmp_path / "cloud"
    fixture_scripts = fixture_root / "scripts"
    fixture_scripts.mkdir(parents=True)
    fixture_wrapper = fixture_scripts / "dev-compose.sh"
    fixture_wrapper.write_text(wrapper_text)
    (fixture_root / "docker-compose.dev.yml").write_text("services: {}\n")
    (fixture_root / ".env").write_text(
        "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN=base-token\n"
        "NPCINK_CLOUD_ADMIN_SESSION_SECRET=base-admin-secret\n"
    )
    (fixture_root / ".env.local").write_text("NPCINK_CLOUD_INTERNAL_AUTH_TOKEN=local-token\n")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
    fake_docker.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
    environment.pop("NPCINK_CLOUD_DEV_COMPOSE_FILE", None)

    result = subprocess.run(
        ["bash", str(fixture_wrapper), "config", "--quiet"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    arguments = result.stdout.splitlines()
    env_files = [
        Path(arguments[index + 1])
        for index, argument in enumerate(arguments)
        if argument == "--env-file"
    ]
    assert env_files == [fixture_root / ".env", fixture_root / ".env.local"]

    resolved: dict[str, str] = {}
    for env_file in env_files:
        for line in env_file.read_text().splitlines():
            key, value = line.split("=", 1)
            resolved[key] = value
    assert resolved["NPCINK_CLOUD_INTERNAL_AUTH_TOKEN"] == "local-token"

    frontend_block = _compose_service_block(dev_compose, "frontend")
    assert (
        "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN: ${NPCINK_CLOUD_INTERNAL_AUTH_TOKEN:-}" in frontend_block
    )
    for forbidden_secret in (
        "NPCINK_CLOUD_ADMIN_KEY",
        "NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN",
        "NPCINK_CLOUD_ADMIN_SESSION_SECRET",
        "NPCINK_CLOUD_SERVICE_SETTINGS_SECRET",
        "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID",
        "NPCINK_CLOUD_PORTAL_JWT_SECRET",
        "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET",
        "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID",
    ):
        assert forbidden_secret not in frontend_block

    for env_file in env_files:
        env_file.unlink()
    missing_env_result = subprocess.run(
        ["bash", str(fixture_wrapper), "config", "--quiet"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert "--env-file" not in missing_env_result.stdout.splitlines()


def test_media_upload_proxy_overrides_are_exact_and_bounded() -> None:
    cloud_root = _cloud_root()
    dev = (cloud_root / "deploy" / "nginx.dev.conf").read_text()
    prod = (cloud_root / "deploy" / "nginx.prod.conf").read_text()
    domain = (cloud_root / "deploy" / "magick-domain-nginx.conf.template").read_text()
    runtime_compose = (cloud_root / "docker-compose.runtime.yml").read_text()

    for text in (dev, prod, domain):
        assert text.count("location = /v1/runtime/media/uploads {") == 1
        assert text.count("client_max_body_size 52m;") == 1
        block = _nginx_location_block(text, "= /v1/runtime/media/uploads")
        assert "client_max_body_size 52m;" in block
        assert "client_body_timeout 60s;" in block

    for text in (dev, prod):
        assert ("limit_req_zone $binary_remote_addr zone=media_upload_rate:10m rate=2r/s;") in text
        assert "limit_conn_zone $binary_remote_addr zone=media_upload_conn:10m;" in text
        assert "limit_conn_zone $server_name zone=media_upload_global_conn:1m;" in text
        assert "limit_req_status 429;" in text
        assert "limit_conn_status 429;" in text
        block = _nginx_location_block(text, "= /v1/runtime/media/uploads")
        assert "limit_conn media_upload_conn 2;" in block
        assert "limit_conn media_upload_global_conn 8;" in block
        assert "limit_req zone=media_upload_rate burst=4 nodelay;" in block

    assert dev.count("client_max_body_size 2m;") == 1
    assert prod.count("client_max_body_size 1m;") == 1
    assert domain.count("client_max_body_size 2m;") == 1

    dev_media = _nginx_location_block(dev, "= /v1/runtime/media/uploads")
    dev_v1 = _nginx_location_block(dev, "/v1/")
    assert "proxy_pass http://$npcink_ai_cloud_api;" in dev_media
    assert "proxy_pass http://$npcink_ai_cloud_api;" in dev_v1
    assert "client_max_body_size" not in dev_v1

    prod_media = _nginx_location_block(prod, "= /v1/runtime/media/uploads")
    prod_v1 = _nginx_location_block(prod, "/v1/")
    for directive in (
        "limit_req zone=public_runtime burst=40 nodelay;",
        "proxy_connect_timeout 5s;",
        "proxy_send_timeout 180s;",
        "proxy_read_timeout 180s;",
        "proxy_pass http://npcink_ai_cloud_api;",
    ):
        assert directive in prod_media
        assert directive in prod_v1
    assert "client_max_body_size" not in prod_v1

    domain_media = _nginx_location_block(domain, "= /v1/runtime/media/uploads")
    domain_default = _nginx_location_block(domain, "/")
    assert "proxy_pass __UPSTREAM__;" in domain_media
    assert "proxy_pass __UPSTREAM__;" in domain_default
    assert "proxy_request_buffering off;" in domain_media
    assert "client_max_body_size" not in domain_default
    assert "media_upload_rate" not in domain
    assert "media_upload_conn" not in domain
    for external_edge_header in (
        "proxy_set_header X-Real-IP $remote_addr;",
        "proxy_set_header X-Forwarded-For $remote_addr;",
        "proxy_set_header X-Forwarded-Host $host;",
        "proxy_set_header X-Forwarded-Proto https;",
        "proxy_set_header X-Forwarded-Port 443;",
    ):
        assert external_edge_header in domain
    assert "listen 443 ssl http2;" in domain
    assert "listen [::]:443 ssl http2;" in domain
    assert "http2 on;" not in domain
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" not in domain

    runtime_proxy = _compose_service_block(runtime_compose, "proxy")
    assert '"127.0.0.1:${NPCINK_CLOUD_PORT:-8010}:8080"' in runtime_proxy
    assert "  caddy:" not in runtime_compose

    prod_real_ip_trust = {
        line.strip() for line in prod.splitlines() if line.strip().startswith("set_real_ip_from ")
    }
    assert prod_real_ip_trust == {
        "set_real_ip_from 172.28.0.1;",
    }
    assert "real_ip_header X-Real-IP;" in prod
    assert "real_ip_recursive on;" in prod
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in prod
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" not in prod
    for direct_client_config in (dev, domain):
        assert "real_ip_header" not in direct_client_config
        assert "set_real_ip_from" not in direct_client_config


def test_media_pull_proxy_is_exact_get_only_streaming_and_independently_bounded() -> None:
    cloud_root = _cloud_root()
    configs = {
        "dev": (cloud_root / "deploy" / "nginx.dev.conf").read_text(),
        "prod": (cloud_root / "deploy" / "nginx.prod.conf").read_text(),
        "domain": (cloud_root / "deploy" / "magick-domain-nginx.conf.template").read_text(),
    }
    location = r'~ "^/v1/runtime/media/artifacts/art_[0-9a-f]{32}/download$"'

    for text in configs.values():
        assert "log_format npcink_uri_only" in text
        log_format = text.split("log_format npcink_uri_only", 1)[1].split(";", 1)[0]
        assert "$uri" in log_format
        for forbidden_log_value in (
            "$request ",
            "$request_uri",
            "$args",
            "$query_string",
            "$http_referer",
        ):
            assert forbidden_log_value not in log_format
        assert text.count(f"location {location} {{") == 1
        block = _nginx_location_block(text, location)
        assert "proxy_buffering off;" in block
        assert "proxy_request_buffering off;" not in block

    for text in (configs["dev"], configs["prod"]):
        block = _nginx_location_block(text, location)
        assert "limit_except GET {" in block
        assert "deny all;" in block
        assert ("limit_req_zone $binary_remote_addr zone=media_pull_rate:10m rate=5r/s;") in text
        assert "limit_conn_zone $binary_remote_addr zone=media_pull_conn:10m;" in text
        assert "limit_conn_zone $server_name zone=media_pull_global_conn:1m;" in text
        block = _nginx_location_block(text, location)
        assert "limit_conn media_pull_conn 4;" in block
        assert "limit_conn media_pull_global_conn 16;" in block
        assert "limit_req zone=media_pull_rate burst=10 nodelay;" in block

    domain_block = _nginx_location_block(configs["domain"], location)
    assert "limit_except" not in domain_block
    assert "media_pull_rate" not in configs["domain"]
    assert "media_pull_conn" not in configs["domain"]

    sanitized_access_log = "access_log /var/log/nginx/access.log npcink_uri_only;"
    assert configs["dev"].count(sanitized_access_log) == 1
    assert configs["prod"].count(sanitized_access_log) == 1
    assert configs["domain"].count(sanitized_access_log) == 2

    prod_block = _nginx_location_block(configs["prod"], location)
    assert "limit_req zone=public_runtime burst=40 nodelay;" in prod_block
    assert "proxy_connect_timeout 5s;" in prod_block
    assert "proxy_send_timeout 180s;" in prod_block
    assert "proxy_read_timeout 180s;" in prod_block
    assert "proxy_pass http://npcink_ai_cloud_api;" in prod_block
    assert "proxy_pass http://$npcink_ai_cloud_api;" in _nginx_location_block(
        configs["dev"], location
    )
    assert "proxy_pass __UPSTREAM__;" in _nginx_location_block(configs["domain"], location)


def test_production_api_trusts_the_same_pinned_network_used_by_compose() -> None:
    compose = (_cloud_root() / "docker-compose.prod.yml").read_text()
    runtime_compose = (_cloud_root() / "docker-compose.runtime.yml").read_text()
    nginx = (_cloud_root() / "deploy" / "nginx.prod.conf").read_text()

    shared_subnet = "172.28.0.0/24"
    trusted_gateway_ip = "172.28.0.1"
    trusted_proxy_ip = "172.28.0.10"
    assert f"--forwarded-allow-ips {trusted_proxy_ip}" in compose
    assert f"ipv4_address: {trusted_proxy_ip}" in compose
    assert f"- subnet: {shared_subnet}" in compose
    assert f"gateway: {trusted_gateway_ip}" in compose
    assert compose.count(shared_subnet) == 1
    assert compose.count(f"gateway: {trusted_gateway_ip}") == 1
    assert compose.count(trusted_proxy_ip) == 2

    runtime_proxy = "${NPCINK_CLOUD_RUNTIME_PROXY_IPV4:-172.28.0.10}"
    runtime_subnet = "${NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET:-172.28.0.0/24}"
    runtime_gateway = "${NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY:-172.28.0.1}"
    assert f"--forwarded-allow-ips {runtime_proxy}" in runtime_compose
    assert f"ipv4_address: {runtime_proxy}" in runtime_compose
    assert f"- subnet: {runtime_subnet}" in runtime_compose
    assert f"gateway: {runtime_gateway}" in runtime_compose
    assert runtime_compose.count(runtime_proxy) == 2
    assert runtime_compose.count(runtime_subnet) == 1
    assert runtime_compose.count(runtime_gateway) == 1

    for compose_text in (compose, runtime_compose):
        assert "--forwarded-allow-ips *" not in compose_text
        assert '"127.0.0.1:${NPCINK_CLOUD_PORT:-8010}:8080"' in compose_text
        assert '"80:80"' not in compose_text
        assert '"443:443"' not in compose_text
        assert "172.28.0.11" not in compose_text
        for retired_service in ("caddy", "jaeger", "otel-collector"):
            assert f"  {retired_service}:" not in compose_text

    assert f"set_real_ip_from {trusted_gateway_ip};" in nginx
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in nginx
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" not in nginx


def test_runtime_network_authority_is_documented_as_release_scoped() -> None:
    cloud_root = _cloud_root()
    ops_playbook = (cloud_root / "deploy" / "OPS_PLAYBOOK.md").read_text()
    deploy_guide = (cloud_root / "deploy" / "PRODUCTION_GITHUB_DEPLOY.md").read_text()
    release_checklist = (cloud_root / "deploy" / "RELEASE_CHECKLIST.md").read_text()
    media_boundary = (cloud_root / "docs" / "media-runtime-boundary-v1.md").read_text()
    edge_adr = (
        cloud_root / "docs" / "decisions" / "020-external-tls-single-bundled-nginx.md"
    ).read_text()
    network_adr = (
        cloud_root
        / "docs"
        / "decisions"
        / "021-release-scoped-runtime-network-authority.md"
    ).read_text()

    active_docs = tuple(
        " ".join(document.split())
        for document in (ops_playbook, deploy_guide, release_checklist, media_boundary)
    )
    normalized_network_adr = " ".join(network_adr.split())
    assert all("per-release runtime network state" in document for document in active_docs)
    assert "! -type l -a -perm /022" in ops_playbook
    assert "ADR-021" in edge_adr
    for marker in (
        "runtime-network.env",
        "nginx.runtime.conf",
        "an existing managed network is retained",
        "temporarily absent proxy retains its frozen address",
        "previous release's own network authority",
    ):
        assert marker in normalized_network_adr

    stale_authority_phrases = (
        "pinned Compose gateway `172.28.0.1`",
        "Runtime Compose pins its gateway to `172.28.0.1`",
        "NGINX trusts real-client headers only from gateway `172.28.0.1`",
    )
    assert all(
        phrase not in document
        for document in active_docs
        for phrase in stale_authority_phrases
    )


def _run_runtime_network_contract_prepare(
    tmp_path: Path,
    *,
    subnet: str,
    gateway: str,
    endpoints: list[tuple[str, str, str]],
    network_id: str = "f" * 64,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    cloud_root = _cloud_root()
    managed_root = tmp_path / "managed"
    release = managed_root / "release-network-contract"
    deploy = release / "deploy"
    scripts = release / "scripts"
    state_dir = managed_root / ".release-state" / release.name
    lock_dir = managed_root / ".deploy-lock"
    fake_bin = tmp_path / "bin"
    for directory in (deploy, scripts, release / "dist", state_dir, lock_dir, fake_bin):
        directory.mkdir(parents=True, exist_ok=True)
    state_dir.chmod(0o700)
    lock_dir.chmod(0o700)

    shutil.copy2(cloud_root / "deploy" / "common.sh", deploy / "common.sh")
    shutil.copy2(
        cloud_root / "deploy" / "remote-load-and-up.sh",
        deploy / "remote-load-and-up.sh",
    )
    shutil.copy2(cloud_root / "deploy" / "nginx.prod.conf", deploy / "nginx.prod.conf")
    shutil.copy2(
        cloud_root / "docker-compose.runtime.yml",
        release / "docker-compose.runtime.yml",
    )
    (release / "docker-compose.prod.yml").write_text("services: {}\n", encoding="utf-8")

    for helper in ("verify-release-bundle.sh", "certificate-renewal-readiness.sh"):
        helper_path = deploy / helper
        helper_path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        helper_path.chmod(0o755)
    manifest = scripts / "verify-release-bundle-manifest.py"
    manifest.write_text("from __future__ import annotations\n", encoding="utf-8")

    owner = "a" * 64
    (lock_dir / "one-off-owner").write_text(owner + "\n", encoding="utf-8")
    (lock_dir / "one-off-owner").chmod(0o600)
    env_file = state_dir / "env.deploy"
    env_file.write_text(
        "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN=network-contract-token\n"
        "NPCINK_CLOUD_BASE_URL=https://cloud.example.com\n"
        "NPCINK_CLOUD_DOMAIN_NAME=cloud.example.com\n"
        "NPCINK_CLOUD_EXTERNAL_EDGE_READY=true\n"
        "NPCINK_CLOUD_CERTIFICATE_RENEWAL_CERT_PATH=/tmp/cert.pem\n"
        "NPCINK_CLOUD_CERTIFICATE_RENEWAL_EVIDENCE_PATH=/tmp/cert-evidence.json\n"
        "NPCINK_CLOUD_CERTIFICATE_RENEWAL_TIMER=certbot-renew.timer\n"
        "NPCINK_CLOUD_CERTIFICATE_RENEWAL_HOOK_PATH=/tmp/cert-hook\n"
        "NPCINK_CLOUD_COMPOSE_PROJECT_NAME=npcink-ai-cloud\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)

    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        r"""#!/usr/bin/env bash
set -euo pipefail
case "${1:-}:${2:-}" in
    network:ls)
        printf '%s\n' "${FAKE_NETWORK_ID}"
        ;;
    network:inspect)
        format="${4:-}"
        case "${format}" in
            '{{.Driver}}') printf 'bridge\n' ;;
            '{{.Internal}}') printf 'false\n' ;;
            '{{len .IPAM.Config}}') printf '1\n' ;;
            '{{(index .IPAM.Config 0).Subnet}}') printf '%s\n' "${FAKE_NETWORK_SUBNET}" ;;
            '{{(index .IPAM.Config 0).Gateway}}') printf '%s\n' "${FAKE_NETWORK_GATEWAY}" ;;
            '{{range $id, $container := .Containers}}'*)
                awk -F '|' 'NF == 3 {print $1 "|" $2}' <<<"${FAKE_NETWORK_ENDPOINTS}"
                ;;
            *) printf 'unexpected network inspect format: %s\n' "${format}" >&2; exit 91 ;;
        esac
        ;;
    inspect:--format)
        format="${3:-}"
        container_id="${4:-}"
        row="$(
            awk -F '|' -v id="${container_id}" '$1 == id {print; exit}' \
                <<<"${FAKE_NETWORK_ENDPOINTS}"
        )"
        [ -n "${row}" ] || exit 92
        case "${format}" in
            '{{index .Config.Labels "com.docker.compose.project"}}')
                printf 'npcink-ai-cloud\n'
                ;;
            '{{index .Config.Labels "com.docker.compose.service"}}')
                printf '%s\n' "$(awk -F '|' '{print $3}' <<<"${row}")"
                ;;
            *) printf 'unexpected container inspect format: %s\n' "${format}" >&2; exit 93 ;;
        esac
        ;;
    info:)
        ;;
    *)
        printf 'unexpected docker command: %s\n' "$*" >&2
        exit 94
        ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    environment = _runtime_network_contract_environment(
        tmp_path,
        state_dir / "runtime-network.env",
        subnet=subnet,
        gateway=gateway,
        endpoints=endpoints,
        network_id=network_id,
    )
    completed = subprocess.run(
        ["bash", str(deploy / "remote-load-and-up.sh")],
        cwd=release,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed, state_dir / "runtime-network.env"


def _runtime_network_contract_environment(
    tmp_path: Path,
    state_file: Path,
    *,
    subnet: str,
    gateway: str,
    endpoints: list[tuple[str, str, str]],
    network_id: str = "f" * 64,
) -> dict[str, str]:
    managed_root = state_file.parents[2]
    release = managed_root / state_file.parent.name
    env_file = state_file.parent / "env.deploy"
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("NPCINK_CLOUD_")
    }
    environment.update(
        {
            "PATH": f"{tmp_path / 'bin'}{os.pathsep}{environment['PATH']}",
            "FAKE_NETWORK_ID": network_id,
            "FAKE_NETWORK_SUBNET": subnet,
            "FAKE_NETWORK_GATEWAY": gateway,
            "FAKE_NETWORK_ENDPOINTS": "\n".join("|".join(row) for row in endpoints),
            "NPCINK_CLOUD_ENV_FILE": str(env_file),
            "NPCINK_CLOUD_BACKEND_ENV_FILE": str(env_file),
            "NPCINK_CLOUD_COMPOSE_FILE": str(release / "docker-compose.runtime.yml"),
            "NPCINK_CLOUD_LOAD_MODE": "prepare-only",
            "NPCINK_CLOUD_ROLLBACK_IMAGE_MAP": str(
                state_file.parent / "rollback-images.tsv"
            ),
            "NPCINK_CLOUD_ROLLBACK_TAG_SUFFIX": "network-contract",
            "NPCINK_CLOUD_DEPLOY_LOCK_OWNER": "a" * 64,
            "NPCINK_CLOUD_RELEASE_TOOL_PYTHON": sys.executable,
        }
    )
    return environment


def test_runtime_network_contract_environment_drops_inherited_cloud_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NPCINK_CLOUD_BASE_URL", "http://unsafe-local.example")
    monkeypatch.setenv(
        "NPCINK_CLOUD_DATABASE_URL", "postgresql://inherited-secret.example/db"
    )
    state_file = (
        tmp_path
        / "managed"
        / ".release-state"
        / "release-network-contract"
        / "runtime-network.env"
    )

    environment = _runtime_network_contract_environment(
        tmp_path,
        state_file,
        subnet="172.28.0.0/24",
        gateway="172.28.0.1",
        endpoints=[],
    )

    assert "NPCINK_CLOUD_BASE_URL" not in environment
    assert "NPCINK_CLOUD_DATABASE_URL" not in environment
    assert {key for key in environment if key.startswith("NPCINK_CLOUD_")} == {
        "NPCINK_CLOUD_BACKEND_ENV_FILE",
        "NPCINK_CLOUD_COMPOSE_FILE",
        "NPCINK_CLOUD_DEPLOY_LOCK_OWNER",
        "NPCINK_CLOUD_ENV_FILE",
        "NPCINK_CLOUD_LOAD_MODE",
        "NPCINK_CLOUD_RELEASE_TOOL_PYTHON",
        "NPCINK_CLOUD_ROLLBACK_IMAGE_MAP",
        "NPCINK_CLOUD_ROLLBACK_TAG_SUFFIX",
    }


@pytest.mark.parametrize(
    ("subnet", "gateway", "endpoints", "expected_proxy"),
    [
        (
            "10.255.1.0/24",
            "10.255.1.1",
            [
                ("b" * 64, "10.255.1.3/24", "postgres"),
                ("c" * 64, "10.255.1.4/24", "redis"),
            ],
            "10.255.1.10",
        ),
        (
            "192.168.240.0/20",
            "192.168.240.1",
            [
                ("b" * 64, "192.168.240.3/20", "postgres"),
                ("c" * 64, "192.168.240.4/20", "redis"),
                ("d" * 64, "192.168.240.27/20", "proxy"),
            ],
            "192.168.240.27",
        ),
        (
            "172.30.8.0/23",
            "172.30.8.1",
            [("b" * 64, "172.30.8.10/23", "postgres")],
            "172.30.9.254",
        ),
    ],
)
def test_runtime_network_prepare_freezes_existing_ipv4_topology(
    tmp_path: Path,
    subnet: str,
    gateway: str,
    endpoints: list[tuple[str, str, str]],
    expected_proxy: str,
) -> None:
    completed, state_file = _run_runtime_network_contract_prepare(
        tmp_path,
        subnet=subnet,
        gateway=gateway,
        endpoints=endpoints,
    )

    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
    assert state_file.stat().st_mode & 0o777 == 0o600
    assert state_file.read_text(encoding="utf-8").splitlines() == [
        "NPCINK_CLOUD_RUNTIME_NETWORK_PROJECT=npcink-ai-cloud",
        f"NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET={subnet}",
        f"NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY={gateway}",
        f"NPCINK_CLOUD_RUNTIME_PROXY_IPV4={expected_proxy}",
    ]
    rendered_nginx = state_file.with_name("nginx.runtime.conf")
    assert rendered_nginx.stat().st_mode & 0o777 == 0o600
    assert f"set_real_ip_from {gateway};" in rendered_nginx.read_text(encoding="utf-8")
    assert (
        "set_real_ip_from 172.28.0.1;" not in rendered_nginx.read_text(encoding="utf-8")
        or gateway == "172.28.0.1"
    )
    assert f"subnet={subnet} gateway={gateway} proxy={expected_proxy}" in completed.stdout


def test_runtime_network_prepare_freezes_fresh_deploy_defaults(tmp_path: Path) -> None:
    completed, state_file = _run_runtime_network_contract_prepare(
        tmp_path,
        subnet="ignored",
        gateway="ignored",
        endpoints=[],
        network_id="",
    )

    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
    assert state_file.read_text(encoding="utf-8").splitlines() == [
        "NPCINK_CLOUD_RUNTIME_NETWORK_PROJECT=npcink-ai-cloud",
        "NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET=172.28.0.0/24",
        "NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY=172.28.0.1",
        "NPCINK_CLOUD_RUNTIME_PROXY_IPV4=172.28.0.10",
    ]


def test_runtime_network_revalidation_preserves_the_frozen_proxy_address(
    tmp_path: Path,
) -> None:
    subnet = "192.168.240.0/20"
    gateway = "192.168.240.1"
    initial_endpoints = [
        ("b" * 64, "192.168.240.3/20", "postgres"),
        ("c" * 64, "192.168.240.4/20", "redis"),
        ("d" * 64, "192.168.240.27/20", "proxy"),
    ]
    completed, state_file = _run_runtime_network_contract_prepare(
        tmp_path,
        subnet=subnet,
        gateway=gateway,
        endpoints=initial_endpoints,
    )
    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"

    release = state_file.parents[2] / state_file.parent.name
    without_proxy = initial_endpoints[:2]
    environment = _runtime_network_contract_environment(
        tmp_path,
        state_file,
        subnet=subnet,
        gateway=gateway,
        endpoints=without_proxy,
    )
    environment["NPCINK_CLOUD_ROLLBACK_IMAGE_MAP"] = str(
        state_file.parent / "rollback-images-revalidate.tsv"
    )
    revalidated = subprocess.run(
        ["bash", str(release / "deploy" / "remote-load-and-up.sh")],
        cwd=release,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert revalidated.returncode == 0, f"{revalidated.stdout}\n{revalidated.stderr}"
    assert "proxy=192.168.240.27" in revalidated.stdout

    occupied_environment = _runtime_network_contract_environment(
        tmp_path,
        state_file,
        subnet=subnet,
        gateway=gateway,
        endpoints=without_proxy
        + [("e" * 64, "192.168.240.27/20", "worker")],
    )
    occupied_environment["NPCINK_CLOUD_ROLLBACK_IMAGE_MAP"] = str(
        state_file.parent / "rollback-images-occupied.tsv"
    )
    occupied = subprocess.run(
        ["bash", str(release / "deploy" / "remote-load-and-up.sh")],
        cwd=release,
        env=occupied_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert occupied.returncode != 0
    assert "occupied by a non-proxy endpoint" in occupied.stderr

    wrong_proxy_environment = _runtime_network_contract_environment(
        tmp_path,
        state_file,
        subnet=subnet,
        gateway=gateway,
        endpoints=without_proxy
        + [("f" * 64, "192.168.240.28/20", "proxy")],
    )
    wrong_proxy_environment["NPCINK_CLOUD_ROLLBACK_IMAGE_MAP"] = str(
        state_file.parent / "rollback-images-wrong-proxy.tsv"
    )
    wrong_proxy = subprocess.run(
        ["bash", str(release / "deploy" / "remote-load-and-up.sh")],
        cwd=release,
        env=wrong_proxy_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert wrong_proxy.returncode != 0
    assert "differs from the frozen runtime proxy IPv4 address" in wrong_proxy.stderr


def test_common_compose_wrapper_reloads_protected_runtime_network_state(
    tmp_path: Path,
) -> None:
    cloud_root = _cloud_root()
    managed_root = tmp_path / "managed"
    release = managed_root / "release-common-network"
    deploy = release / "deploy"
    state_root = managed_root / ".release-state"
    state_dir = state_root / release.name
    fake_bin = tmp_path / "bin"
    for directory in (deploy, state_root, state_dir, fake_bin):
        directory.mkdir(parents=True, exist_ok=True)
    state_root.chmod(0o700)
    state_dir.chmod(0o700)
    shutil.copy2(cloud_root / "deploy" / "common.sh", deploy / "common.sh")
    shutil.copy2(cloud_root / "deploy" / "nginx.prod.conf", deploy / "nginx.prod.conf")
    shutil.copy2(
        cloud_root / "docker-compose.runtime.yml",
        release / "docker-compose.runtime.yml",
    )

    state_file = state_dir / "runtime-network.env"
    state_file.write_text(
        "NPCINK_CLOUD_RUNTIME_NETWORK_PROJECT=npcink-ai-cloud\n"
        "NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET=10.255.1.0/24\n"
        "NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY=10.255.1.1\n"
        "NPCINK_CLOUD_RUNTIME_PROXY_IPV4=10.255.1.27\n",
        encoding="utf-8",
    )
    state_file.chmod(0o600)
    nginx_source = (deploy / "nginx.prod.conf").read_text(encoding="utf-8")
    nginx_runtime = state_dir / "nginx.runtime.conf"
    nginx_runtime.write_text(
        nginx_source.replace(
            "    set_real_ip_from 172.28.0.1;",
            "    set_real_ip_from 10.255.1.1;",
            1,
        ),
        encoding="utf-8",
    )
    nginx_runtime.chmod(0o600)
    env_file = state_dir / "env.deploy"
    env_file.write_text(
        "NPCINK_CLOUD_COMPOSE_PROJECT_NAME=npcink-ai-cloud\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)

    capture = tmp_path / "compose-runtime.env"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
[ "${1:-}" = "compose" ]
{
    printf 'subnet=%s\n' "${NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET-unset}"
    printf 'gateway=%s\n' "${NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY-unset}"
    printf 'proxy=%s\n' "${NPCINK_CLOUD_RUNTIME_PROXY_IPV4-unset}"
    printf 'nginx=%s\n' "${NPCINK_CLOUD_RUNTIME_NGINX_CONFIG_PATH-unset}"
} >"${CAPTURE_FILE}"
printf '{"services":{"release-one-off":{"image":"test"}}}\n'
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    command = [
        "bash",
        "-c",
        '. "$1"; npcink_ai_cloud_compose "$2" config --format json release-one-off',
        "_",
        str(deploy / "common.sh"),
        str(release),
    ]
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "CAPTURE_FILE": str(capture),
            "NPCINK_CLOUD_ENV_FILE": str(env_file),
            "NPCINK_CLOUD_BACKEND_ENV_FILE": str(env_file),
            "NPCINK_CLOUD_COMPOSE_FILE": str(release / "docker-compose.runtime.yml"),
            "NPCINK_CLOUD_COMPOSE_PROJECT_NAME": "npcink-ai-cloud",
            "NPCINK_CLOUD_RELEASE_TOOL_PYTHON": sys.executable,
            "NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET": "192.0.2.0/24",
            "NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY": "192.0.2.1",
            "NPCINK_CLOUD_RUNTIME_PROXY_IPV4": "192.0.2.10",
            "NPCINK_CLOUD_RUNTIME_NGINX_CONFIG_PATH": "/ambient/nginx.conf",
        }
    )
    completed = subprocess.run(
        command,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
    assert capture.read_text(encoding="utf-8").splitlines() == [
        "subnet=10.255.1.0/24",
        "gateway=10.255.1.1",
        "proxy=10.255.1.27",
        f"nginx={nginx_runtime}",
    ]

    nginx_runtime.write_text(nginx_source, encoding="utf-8")
    drifted = subprocess.run(
        command,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert drifted.returncode != 0
    assert "differs from the bundled gateway contract" in drifted.stderr

    nginx_runtime.write_text(
        nginx_source.replace(
            "    set_real_ip_from 172.28.0.1;",
            "    set_real_ip_from 10.255.1.1;",
            1,
        ),
        encoding="utf-8",
    )
    state_file.unlink()
    missing = subprocess.run(
        command,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert missing.returncode != 0
    assert "runtime-network.env" in missing.stderr

    (release / "docker-compose.runtime.yml").write_text(
        "services: {}\n",
        encoding="utf-8",
    )
    legacy = subprocess.run(
        command,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert legacy.returncode == 0, f"{legacy.stdout}\n{legacy.stderr}"
    assert capture.read_text(encoding="utf-8").splitlines() == [
        "subnet=unset",
        "gateway=unset",
        "proxy=unset",
        "nginx=unset",
    ]


def test_runtime_network_contract_is_locked_before_image_or_container_mutation() -> None:
    loader = (_cloud_root() / "deploy" / "remote-load-and-up.sh").read_text()
    common = (_cloud_root() / "deploy" / "common.sh").read_text()

    assert "printf '%s/runtime-network.env'" in loader
    assert '"$(npcink_ai_cloud_mode_of "${state_file}"' in loader
    assert '"label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}"' in loader
    assert "Managed Compose network contains a foreign or unlabelled endpoint" in loader
    assert "Bundled NGINX gateway trust anchor is not unique" in loader
    assert 'export NPCINK_CLOUD_RUNTIME_NGINX_CONFIG_PATH="${rendered_path}"' in loader
    assert loader.index("prepare_runtime_network_contract\n") < loader.index(
        "prepare_release_images\n"
    )
    candidate_create = loader.index('npcink_ai_cloud_compose "${ROOT_DIR}" "${compose_args[@]}"')
    network_reproof = loader.index(
        "if is_runtime_compose_file && ! assert_runtime_network_contract", candidate_create
    )
    immutable_start = loader.index('docker start "${container_ids_to_start[@]}"')
    assert candidate_create < network_reproof < immutable_start
    assert "npcink_ai_cloud_prepare_runtime_compose_environment() {" in common
    assert "Parameterized runtime Compose interpolation structure" in common
    assert "Frozen runtime NGINX config differs from the bundled gateway contract" in common
    assert common.index("npcink_ai_cloud_prepare_runtime_compose_environment \\") < common.index(
        "docker compose --env-file"
    )


def test_formal_runtime_requires_the_external_tls_edge_contract() -> None:
    cloud_root = _cloud_root()
    loader = (cloud_root / "deploy" / "remote-load-and-up.sh").read_text()
    bind_domain = (cloud_root / "deploy" / "bind-domain-to-ssh-host.sh").read_text()
    env_example = (cloud_root / ".env.example").read_text()
    prod_compose = (cloud_root / "docker-compose.prod.yml").read_text()
    runtime_compose = (cloud_root / "docker-compose.runtime.yml").read_text()

    edge_gate = loader.split("require_external_edge_for_formal_runtime() {", 1)[1].split(
        "\n}",
        1,
    )[0]
    assert '$(basename "${COMPOSE_FILE}")' in edge_gate
    assert '"docker-compose.runtime.yml"' in edge_gate
    assert '[[ "${BASE_URL}" != https://* ]]' in edge_gate
    assert "NPCINK_CLOUD_EXTERNAL_EDGE_READY" in edge_gate
    assert "NPCINK_CLOUD_BASE_URL" in edge_gate
    assert "NPCINK_CLOUD_DOMAIN_NAME" in edge_gate
    assert 'parsed.scheme.lower() != "https"' in edge_gate
    assert "actual_host != expected_host" in edge_gate
    assert "port not in (None, 443)" in edge_gate
    assert "parsed.username is not None or parsed.password is not None" in edge_gate
    assert "parsed.path not in" in edge_gate
    edge_gate_call = "\nrequire_external_edge_for_formal_runtime\n"
    assert loader.count(edge_gate_call) == 1
    assert loader.index(edge_gate_call) < loader.index(
        '\nif [ "${LOAD_MODE}" = "data-only" ]; then\n'
    )

    assert "NPCINK_CLOUD_DOMAIN_NAME=" in env_example
    assert "NPCINK_CLOUD_EXTERNAL_EDGE_READY=false" in env_example
    assert (
        'UPSTREAM_URL="${NPCINK_CLOUD_DOMAIN_UPSTREAM_URL:-http://127.0.0.1:8010}"' in bind_domain
    )
    assert 'parsed.hostname != "127.0.0.1" or port != 8010' in bind_domain
    assert 'CERTIFICATE_PATH="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"' in bind_domain
    assert 'PRIVATE_KEY_PATH="/etc/letsencrypt/live/${DOMAIN}/privkey.pem"' in bind_domain
    assert "ssl_certificate ${FAKE_NGINX_CERT_PATH}" not in bind_domain
    assert "certificate and private key do not match" in bind_domain
    assert "checkend 2592000" in bind_domain
    assert "secrets.token_hex(16)" in bind_domain
    assert "trap cleanup EXIT" in bind_domain
    assert "trap on_exit EXIT" in bind_domain
    assert "Certbot live symlink" in bind_domain
    assert "/etc/letsencrypt/archive" in bind_domain
    assert "private-key archive target must not grant group or other permissions" in bind_domain
    assert "umask 077" in bind_domain
    assert 'install -d -m 700 -- "${REMOTE_TMP_DIR}"' in bind_domain
    assert 'test "$(stat -c \'%a\' "${REMOTE_TMP_DIR}")" = "700"' in bind_domain
    assert "REMOTE_TMP_CERT" not in bind_domain
    assert "REMOTE_TMP_KEY" not in bind_domain
    assert "REMOTE_CERT_DIR" not in bind_domain
    assert "ssl_certificate __SSL_CERT__;" not in bind_domain
    assert "remote_shell_arg() {" in bind_domain
    assert "import shlex" in bind_domain
    assert "shlex.quote(sys.argv[1])" in bind_domain
    assert 'remote_command+=" $(remote_shell_arg "${remote_arg}")"' in bind_domain
    assert 'ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "${remote_command}"' in bind_domain
    assert '"${SSH_TARGET}" bash -s --' not in bind_domain
    assert '--filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}"' in (
        bind_domain
    )
    assert '--filter "label=com.docker.compose.service=caddy"' in bind_domain
    assert "--prepare-only" in bind_domain
    assert "apt-get" not in bind_domain
    assert "Install prerequisites before running the migration helper" in bind_domain
    prepare_branch = bind_domain.split('if [ "${PREPARE_ONLY}" = "1" ]; then', 1)[1]
    assert prepare_branch.index("restore_nginx_files") < prepare_branch.index("exit 0")
    assert prepare_branch.index("ROLLBACK_REQUIRED=0") < prepare_branch.index(
        "TRANSACTION_COMMITTED=1"
    )
    assert prepare_branch.index("TRANSACTION_COMMITTED=1") < prepare_branch.index(
        "release_deploy_lock"
    )
    assert prepare_branch.index("exit 0") < prepare_branch.index("systemctl restart nginx")
    assert 'DEPLOY_LOCK_DIR="${REMOTE_DIR}/.deploy-lock"' in bind_domain
    lock_acquire = bind_domain.index('mkdir -- "${DEPLOY_LOCK_DIR}"')
    freeze_nginx = bind_domain.index('backup_target "${SITE_AVAILABLE}"')
    freeze_caddy = bind_domain.index("snapshot_original_caddy_ids || fail_remote")
    assert "done < <(docker ps -q" not in bind_domain
    stop_caddy = bind_domain.index('docker stop "${ORIGINAL_CADDY_IDS[@]}"')
    nginx_restart = bind_domain.index("systemctl restart nginx", stop_caddy)
    edge_health = bind_domain.index('--resolve "${DOMAIN}:443:127.0.0.1"')
    transaction_commit = bind_domain.index("TRANSACTION_COMMITTED=1", edge_health)
    lock_release = bind_domain.index("release_deploy_lock", transaction_commit)
    assert lock_acquire < freeze_nginx < freeze_caddy < stop_caddy < nginx_restart
    assert nginx_restart < edge_health < transaction_commit < lock_release
    release_lock_body = bind_domain.split("release_deploy_lock() {", 1)[1].split("\n}", 1)[0]
    assert 'if ! rmdir -- "${DEPLOY_LOCK_DIR}"' in release_lock_body
    assert "PRESERVE_ROLLBACK_EVIDENCE=1" in release_lock_body
    assert "return 1" in release_lock_body
    assert '[ "${TRANSACTION_COMMITTED}" != "1" ]' in bind_domain
    assert 'assert_safe_directory "/etc/nginx/sites-available"' in bind_domain
    assert 'assert_safe_directory "/etc/nginx/sites-enabled"' in bind_domain
    assert "existing sites-available config must not be a symlink" in bind_domain
    unlink_candidate_target = bind_domain.index('rm -f -- "${SITE_AVAILABLE}" "${SITE_ENABLED}"')
    install_candidate = bind_domain.index(
        'install -m 644 -- "${REMOTE_TMP_CONF}" "${SITE_AVAILABLE}"'
    )
    assert freeze_nginx < unlink_candidate_target < install_candidate
    assert "rollback_edge_transaction" in bind_domain
    assert 'docker start "${ORIGINAL_CADDY_IDS[@]}"' in bind_domain
    assert "verify_original_caddy_running" in bind_domain
    assert (
        "restoring the previous host NGINX state and exact retired Caddy containers" in bind_domain
    )
    assert '"${UPSTREAM_URL%/}/health/live"' in bind_domain
    assert '--resolve "${DOMAIN}:443:127.0.0.1"' in bind_domain
    assert "NPCINK_CLOUD_EXTERNAL_EDGE_READY=true" in bind_domain
    for compose_text in (prod_compose, runtime_compose):
        assert '"127.0.0.1:${NPCINK_CLOUD_PORT:-8010}:8080"' in compose_text
        assert '"80:80"' not in compose_text
        assert '"443:443"' not in compose_text


def test_runtime_data_encryption_deploy_boundary_is_backend_only() -> None:
    cloud_root = _cloud_root()
    env_example = (cloud_root / ".env.example").read_text()
    dev_compose = (cloud_root / "docker-compose.dev.yml").read_text()
    prod_compose = (cloud_root / "docker-compose.prod.yml").read_text()
    runtime_compose = (cloud_root / "docker-compose.runtime.yml").read_text()
    deploy_smoke = (cloud_root / "scripts" / "cloud-deploy-bundle-smoke-flow.sh").read_text()
    checklist = (cloud_root / "deploy" / "RELEASE_CHECKLIST.md").read_text()
    playbook = (cloud_root / "deploy" / "OPS_PLAYBOOK.md").read_text()
    deploy_guide = (cloud_root / "deploy" / "PRODUCTION_GITHUB_DEPLOY.md").read_text()
    release_policy = (cloud_root / "docs" / "cloud-production-release-policy-v1.md").read_text()
    pg18_runbook = (
        cloud_root / "docs" / "cloud-first-install-rds-pg18-runbook.md"
    ).read_text()
    deploy_to_ssh = (cloud_root / "deploy" / "deploy-to-ssh-host.sh").read_text()

    encryption_secret = "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET"
    encryption_key_id = "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID"
    service_secret = "NPCINK_CLOUD_SERVICE_SETTINGS_SECRET"
    service_key_id = "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID"
    backend_services = ("api", "worker", "callback-worker", "ops-worker")

    for protected_key in (encryption_secret, encryption_key_id, service_secret, service_key_id):
        assert protected_key in env_example
        assert f"{protected_key}=" not in env_example
    assert deploy_smoke.count(encryption_secret) >= 2
    assert deploy_smoke.count(encryption_key_id) >= 2
    assert deploy_smoke.count(service_secret) >= 2
    assert deploy_smoke.count(service_key_id) >= 2

    for service in backend_services:
        prod_block = _compose_service_block(prod_compose, service)
        assert "NPCINK_CLOUD_CONFIG_DIR: /run/npcink-config" in prod_block
        assert "/run/npcink-config" in prod_block
        assert encryption_secret not in prod_block
        assert encryption_key_id not in prod_block
        assert service_secret not in prod_block
        assert service_key_id not in prod_block
        assert "NPCINK_CLOUD_DATABASE_URL" not in prod_block
        assert "env_file:" in prod_block
        assert "- ${NPCINK_CLOUD_BACKEND_ENV_FILE:-/dev/null}" in prod_block

        runtime_block = _compose_service_block(runtime_compose, service)
        assert "env_file:" in runtime_block
        assert "- ${NPCINK_CLOUD_BACKEND_ENV_FILE:-.env.deploy}" in runtime_block
        assert "pull_policy: never" in runtime_block

        dev_block = _compose_service_block(dev_compose, service)
        assert "env_file:" in dev_block
        assert "- ./.env" in dev_block
        assert "- ./.env.local" in dev_block

    expected_frontend_env = {
        "docker-compose.dev.yml": {
            "CLOUD_API_BASE_URL",
            "CLOUD_PUBLIC_BASE_URL",
            "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN",
            "NPCINK_CLOUD_DEV_ADMIN_KEY",
            "NPCINK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT",
            "NODE_OPTIONS",
            "NEXT_TELEMETRY_DISABLED",
            "DISABLE_DEPENDENCY_CHECK",
        },
        "docker-compose.prod.yml": {
            "CLOUD_API_BASE_URL",
            "CLOUD_PUBLIC_BASE_URL",
            "NEXT_PUBLIC_ENV",
            "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN_FILE",
            "NPCINK_CLOUD_SETUP_STATE_OVERRIDE",
            "NODE_ENV",
        },
        "docker-compose.runtime.yml": {
            "CLOUD_API_BASE_URL",
            "CLOUD_PUBLIC_BASE_URL",
            "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN_FILE",
            "NODE_ENV",
        },
    }
    compose_by_name = {
        "docker-compose.dev.yml": dev_compose,
        "docker-compose.prod.yml": prod_compose,
        "docker-compose.runtime.yml": runtime_compose,
    }
    forbidden_frontend_secrets = (
        encryption_secret,
        encryption_key_id,
        service_secret,
        service_key_id,
        "NPCINK_CLOUD_ADMIN_KEY",
        "NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN",
        "NPCINK_CLOUD_ADMIN_SESSION_SECRET",
        "NPCINK_CLOUD_PORTAL_JWT_SECRET",
        "NPCINK_CLOUD_DATABASE_URL",
    )
    for compose_name, compose_text in compose_by_name.items():
        frontend_block = _compose_service_block(compose_text, "frontend")
        assert "env_file:" not in frontend_block
        assert _compose_environment_keys(frontend_block) == expected_frontend_env[compose_name]
        for forbidden_secret in forbidden_frontend_secrets:
            assert forbidden_secret not in frontend_block

    prod_frontend = _compose_service_block(prod_compose, "frontend")
    assert "${NPCINK_CLOUD_DEPLOY_SMOKE_FRONTEND_ENV:-production}" in prod_frontend
    assert "${NPCINK_CLOUD_DEPLOY_SMOKE_SETUP_STATE_OVERRIDE:-}" in prod_frontend
    assert "NPCINK_CLOUD_DEPLOY_SMOKE_FRONTEND_ENV" not in _compose_service_block(
        runtime_compose, "frontend"
    )

    assert "127.0.0.1:${NPCINK_CLOUD_PORT:-8010}:8080" in prod_compose
    assert '- "${NPCINK_CLOUD_PORT:-8010}:8080"' not in prod_compose

    assert "Current PostgreSQL 18 Release Contract" in release_policy
    assert "Historical PG16 and P1-E06 Policy (non-normative)" in release_policy
    assert "must not be used to reopen compatibility" in release_policy
    assert "database_contract=pg18_empty_initialization.v1" in release_policy
    assert "candidate head or one of its known ancestors" in release_policy
    assert "exact sole\n  candidate head" in release_policy
    assert "candidate-image RDS PostgreSQL 18/TLS/Alembic preflight" in release_policy
    documented_release_order = (
        "5. Runs the explicit `prepare-only` phase",
        "6. Uses the exact candidate API image",
        "7. Stops the old public/write services",
        "8. Runs the explicit `data-only` phase",
        "9. Runs the external RDS migration",
        "10. Moves `current` atomically",
    )
    documented_positions = [
        deploy_guide.index(marker) for marker in documented_release_order
    ]
    assert documented_positions == sorted(documented_positions)
    assert "The Python image CVE exception must either be" in release_policy
    assert "trusted workstation instead of the GitHub deploy workflow" in release_policy
    for marker in (
        "pg18_empty_initialization.v1",
        "`verify-full`",
        "deploy/first-install-finalize.sh",
        "deploy/first-install-rollback.sh",
        ".installation-complete",
    ):
        assert marker in pg18_runbook

    assert "assert_fresh_pg18_install_gate" in deploy_to_ssh
    assert "candidate-runtime-config-and-pg18-preflight" in deploy_to_ssh
    assert "remote-runtime-config-preflight.sh" in deploy_to_ssh
    assert "assert_p1_e06_ordinary_deploy_gate" not in deploy_to_ssh
    assert "NPCINK_CLOUD_REQUIRE_P1_E06_RECEIPT" not in deploy_to_ssh

    assert "--stage-only)" in deploy_to_ssh
    assert "--host-python)" in deploy_to_ssh
    assert "NPCINK_CLOUD_DEPLOY_HOST_PYTHON:-/usr/bin/python3.11" in deploy_to_ssh
    assert "Stage-only remote entry requires exactly five arguments." in deploy_to_ssh
    assert "cleanup_remote_incoming_on_exit" in deploy_to_ssh
    assert "--stage-only does not accept an env file" in deploy_to_ssh
    stage_branch = deploy_to_ssh.split(
        "# Stage-only deliberately exits before resolving current", 1
    )[1]
    stage_branch = stage_branch.split("atomic_set_current()", 1)[0]
    assert "verify-release-bundle.sh" in stage_branch
    assert "--pre-load" in stage_branch
    assert "staged_release=%s" in stage_branch
    for forbidden in (
        "docker ",
        "CURRENT_LINK",
        "RELEASE_STATE_ROOT",
        "remote-load-and-up.sh",
        "remote-migrate.sh",
    ):
        assert forbidden not in stage_branch

    current_gate_markers = (
        "assert_fresh_pg18_install_gate",
        'CUTOVER_PHASE="prepare-release-images"',
        'CUTOVER_PHASE="candidate-runtime-config-and-pg18-preflight"',
        'CUTOVER_PHASE="stop-old-application-services"',
    )
    positions = [deploy_to_ssh.index(marker) for marker in current_gate_markers]
    assert positions == sorted(positions)
    assert "runtime-data-encryption-cutover.sh" not in deploy_to_ssh

    assert "Current PostgreSQL 18 Release Contract" in release_policy
    assert "protected structured configuration" in release_policy
    assert "database_contract=pg18_empty_initialization.v1" in release_policy

    for surface in (playbook, deploy_guide, checklist, release_policy):
        assert "--env-from-file" not in surface
        assert "run --rm --no-deps --pull never" not in surface


def test_prod_env_files_use_canonical_admin_names_and_do_not_expose_ai_provider_env() -> None:
    cloud_root = _cloud_root()
    compose_text = (cloud_root / "docker-compose.prod.yml").read_text()
    env_example_text = (cloud_root / ".env.example").read_text()
    readme_text = (cloud_root / "README.md").read_text()
    checklist_text = (cloud_root / "deploy" / "RELEASE_CHECKLIST.md").read_text()
    playbook_text = (cloud_root / "deploy" / "OPS_PLAYBOOK.md").read_text()
    provider_runbook_text = (
        cloud_root / "docs" / "provider-connection-production-runbook-2026-06-30.md"
    ).read_text()

    for text in (env_example_text, readme_text, checklist_text):
        assert "NPCINK_CLOUD_ADMIN_SESSION_SECRET" in text
        assert "NPCINK_CLOUD_ADMIN_KEY" in text
        assert "NPCINK_CLOUD_BASE_URL" in text or text is readme_text
        assert "NPCINK_CLOUD_OPS_CADENCE_POLL_SECONDS" in text
        assert "NPCINK_CLOUD_RUNTIME_CALLBACK_WORKER_POLL_SECONDS" in text or text is checklist_text
        assert "NPCINK_CLOUD_WORKER_HEARTBEAT_INTERVAL_SECONDS" in text or text is checklist_text
        assert (
            "NPCINK_CLOUD_PROVIDER_HEALTH_SCAN_INTERVAL_SECONDS" in text or text is checklist_text
        )
        assert "NPCINK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT" in text
        assert "NPCINK_CLOUD_OTEL_TRACE_QUERY_URL" in text

    assert "NPCINK_CLOUD_ADMIN_SESSION_SECRET" not in compose_text
    assert "NPCINK_CLOUD_ADMIN_KEY" not in compose_text
    assert "NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN" not in compose_text
    assert "NPCINK_CLOUD_DATABASE_URL" not in compose_text
    assert "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN:" not in compose_text
    assert "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN_FILE" in compose_text
    assert "NPCINK_CLOUD_CONFIG_DIR: /run/npcink-config" in compose_text
    prod_compose = (cloud_root / "docker-compose.prod.yml").read_text()
    runtime_compose = (cloud_root / "docker-compose.runtime.yml").read_text()
    for service in ("api", "worker", "callback-worker", "ops-worker"):
        assert (
            "NPCINK_CLOUD_ENVIRONMENT: "
            "${NPCINK_CLOUD_DEPLOY_SMOKE_BACKEND_ENV:-production}"
        ) in _compose_service_block(prod_compose, service)
        assert "NPCINK_CLOUD_ENVIRONMENT: production" in _compose_service_block(
            runtime_compose,
            service,
        )
        assert "NPCINK_CLOUD_DEPLOY_SMOKE_BACKEND_ENV" not in _compose_service_block(
            runtime_compose,
            service,
        )

    assert "callback-worker:" in compose_text
    for retired_service in ("caddy", "otel-collector", "jaeger"):
        assert f"  {retired_service}:" not in compose_text
    for text in (
        compose_text,
        env_example_text,
        readme_text,
        checklist_text,
        playbook_text,
    ):
        assert "NPCINK_CLOUD_OTEL_TRACE_SINK_OTLP_ENDPOINT" not in text
    assert "NPCINK_CLOUD_ADMIN_PRINCIPAL_ID" in compose_text
    assert "NPCINK_CLOUD_ADMIN_PRINCIPAL_ID" in env_example_text
    assert "NPCINK_CLOUD_ADMIN_PLATFORM_ADMIN_ROLE" not in compose_text
    assert "NPCINK_CLOUD_ADMIN_PLATFORM_ADMIN_ROLE" not in env_example_text
    assert "NPCINK_CLOUD_ADMIN_BOOTSTRAP_PRINCIPAL_ID" not in compose_text
    assert "NPCINK_CLOUD_ADMIN_BOOTSTRAP_PLATFORM_ADMIN_ROLE" not in compose_text
    assert "NPCINK_CLOUD_PORTAL_JWT_ISSUER=npcink-ai-cloud" in env_example_text
    assert "NPCINK_CLOUD_PORTAL_JWT_AUDIENCE=npcink-ai-cloud-portal" in env_example_text
    assert (
        "NPCINK_CLOUD_PORTAL_JWT_ISSUER: "
        "${NPCINK_CLOUD_PORTAL_JWT_ISSUER:-npcink-ai-cloud}" in compose_text
    )
    assert (
        "NPCINK_CLOUD_PORTAL_JWT_AUDIENCE: "
        "${NPCINK_CLOUD_PORTAL_JWT_AUDIENCE:-npcink-ai-cloud-portal}" in compose_text
    )

    assert "NPCINK_CLOUD_OPS_SESSION_SECRET" not in compose_text
    assert "NPCINK_CLOUD_OPS_SESSION_SECRET" not in env_example_text
    assert "NPCINK_CLOUD_OPS_SESSION_SECRET" not in readme_text
    assert "NPCINK_CLOUD_OPS_SESSION_SECRET" not in checklist_text
    assert "NPCINK_CLOUD_ADMIN_BOOTSTRAP_ADMIN_REF" not in compose_text
    assert "NPCINK_CLOUD_ADMIN_BOOTSTRAP_ADMIN_REF" not in env_example_text
    assert "NPCINK_CLOUD_ADMIN_BOOTSTRAP_ADMIN_ROLE" not in compose_text
    assert "NPCINK_CLOUD_ADMIN_BOOTSTRAP_ADMIN_ROLE" not in env_example_text
    assert "NPCINK_CLOUD_OPENAI_COMPATIBLE_" not in compose_text
    assert "NPCINK_CLOUD_OPENAI_COMPATIBLE_" not in env_example_text
    assert "NPCINK_CLOUD_OPENAI_COMPATIBLE_" not in readme_text
    assert "NPCINK_CLOUD_OPENAI_API_KEY=" not in env_example_text
    assert "NPCINK_CLOUD_OPENAI_BASE_URL=" not in env_example_text
    assert "NPCINK_CLOUD_MINIMAX_API_KEY=" not in env_example_text
    assert "NPCINK_CLOUD_MINIMAX_BASE_URL=" not in env_example_text
    assert "NPCINK_CLOUD_ANTHROPIC_API_KEY=" not in env_example_text
    assert "NPCINK_CLOUD_LITELLM_API_KEY=" not in env_example_text
    assert "NPCINK_CLOUD_VLLM_API_KEY=" not in env_example_text
    assert "NPCINK_CLOUD_TEI_API_KEY=" not in env_example_text
    assert "NPCINK_CLOUD_OPENROUTER_API_KEY=" not in env_example_text
    assert "NPCINK_CLOUD_SILICONFLOW_API_KEY=" not in env_example_text
    assert "AI provider channels are managed in Cloud runtime storage" in env_example_text
    assert "NPCINK_CLOUD_FEATURE_FLAGS_JSON" not in env_example_text
    assert "NPCINK_CLOUD_FEATURE_FLAGS_JSON" not in readme_text
    assert "http://127.0.0.1:8010" in env_example_text
    assert _documented_https_host(checklist_text, "NPCINK_CLOUD_BASE_URL") == "cloud.npc.ink"
    assert (
        _documented_env_value(checklist_text, "NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST")
        == "cloud.npc.ink"
    )
    assert _documented_https_host(playbook_text, "NPCINK_CLOUD_BASE_URL") == "cloud.npc.ink"
    assert "Resource Tuning Baseline" in playbook_text
    assert "fixes Gunicorn to exactly one API worker" in playbook_text
    assert "NPCINK_CLOUD_API_WORKERS" in playbook_text
    assert "NPCINK_CLOUD_RUNTIME_WORKER_POLL_SECONDS" in playbook_text
    assert "db_managed_provider_connections" in provider_runbook_text
    assert "deploy/remote-provider-matrix-smoke.sh" in provider_runbook_text
    assert "`search_tavily`" in provider_runbook_text
    assert "`search_bocha`" in provider_runbook_text
    assert "`search_apify`" in provider_runbook_text
    assert "`search_zhihu`" in provider_runbook_text
    assert "`search_jina_reader`" in provider_runbook_text
    assert "optional URL reader enhancement" in provider_runbook_text
    assert "`image_unsplash`" in provider_runbook_text
    assert "`siliconflow_env`" in provider_runbook_text
    assert "`tei_env`" in provider_runbook_text
    assert "`embedding_siliconflow`" not in provider_runbook_text
    assert "`vector_zilliz`" in provider_runbook_text
    assert "Do not put provider credentials back into `.env.deploy`" in provider_runbook_text
    assert "NPCINK_CLOUD_WEB_SEARCH_ZHIHU_ACCESS_SECRET=" not in provider_runbook_text
    assert "NPCINK_CLOUD_IMAGE_SOURCE_UNSPLASH_ACCESS_KEY=" not in provider_runbook_text
    assert "NPCINK_CLOUD_SITE_KNOWLEDGE_ZILLIZ_TOKEN=" not in provider_runbook_text
    assert "NPCINK_CLOUD_RUNTIME_CALLBACK_WORKER_POLL_SECONDS" in playbook_text


def test_env_example_does_not_restore_first_install_runtime_secrets() -> None:
    env_text = (_cloud_root() / ".env.example").read_text()

    for retired_or_protected in (
        "NPCINK_CLOUD_DATABASE_URL=",
        "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN=",
        "NPCINK_CLOUD_ADMIN_KEY=",
        "NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN=",
        "NPCINK_CLOUD_ADMIN_SESSION_SECRET=",
        "NPCINK_CLOUD_SERVICE_SETTINGS_SECRET=",
        "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID=",
        "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET=",
        "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID=",
        "NPCINK_CLOUD_PORTAL_JWT_SECRET=",
        "POSTGRES_PASSWORD=",
    ):
        assert retired_or_protected not in env_text

    assert "NPCINK_CLOUD_ADMIN_PRINCIPAL_ID=platform:internal_root" in env_text
    assert "NPCINK_CLOUD_ADMIN_PLATFORM_ADMIN_ROLE" not in env_text


def test_admin_key_rotation_publishes_recoverable_dual_digest_transition() -> None:
    script = (_cloud_root() / "deploy" / "admin-key-rotate.sh").read_text()

    transition = 'state["config_transition"] = "admin_key_rotation.v1"'
    previous = 'state["previous_config_digest"] = observed_digest'
    publish_transition = "atomic_write(state_path, transition_state_bytes, 0o640)"
    publish_runtime = "atomic_write(runtime_path, runtime_bytes, 0o600)"
    clear_transition = 'state.pop("config_transition", None)'
    publish_final_state = "atomic_write(state_path, canonical_bytes(state), 0o640)"

    for marker in (
        transition,
        previous,
        publish_transition,
        publish_runtime,
        clear_transition,
        publish_final_state,
    ):
        assert marker in script
    assert script.index(transition) < script.index(publish_transition)
    assert script.index(previous) < script.index(publish_transition)
    assert script.index(publish_transition) < script.index(publish_runtime)
    assert script.index(publish_runtime) < script.index(clear_transition)
    assert script.index(clear_transition) < script.index(publish_final_state)
    assert 'LOCK_DIR="${MANAGED_ROOT}/.deploy-lock"' in script
    assert "Another deployment or administrator-key rotation is active" in script
    assert 'CURRENT_LINK="${MANAGED_ROOT}/current"' in script
    active_release_check = "Administrator-key rotation must run from the active managed release."
    assert active_release_check in script
    assert script.index(active_release_check) < script.index('mkdir -m 0700 "${LOCK_DIR}"')
    assert '.admin-key-rotate.lock' not in script


def test_operator_secret_rotation_fails_closed_without_tty() -> None:
    cloud_root = _cloud_root()
    setup_rotate = (cloud_root / "deploy" / "setup-code-rotate.sh").read_text()
    prepare_setup = (cloud_root / "deploy" / "prepare-first-install.sh").read_text()
    admin_rotate = (cloud_root / "deploy" / "admin-key-rotate.sh").read_text()

    assert '[ ! -t 1 ]' in setup_rotate
    assert setup_rotate.index('[ ! -t 1 ]') < setup_rotate.index("prepare-first-install.sh")
    assert 'if [ "${MODE}" = "rotate" ]; then' in prepare_setup
    assert '[ ! -t 1 ]' in prepare_setup
    assert '[ "${EUID}" -ne 0 ]' in prepare_setup
    assert prepare_setup.index('[ ! -t 1 ]') < prepare_setup.index("setup_code = token")
    assert prepare_setup.index('[ "${EUID}" -ne 0 ]') < prepare_setup.index(
        "setup_code = token"
    )
    assert '[ ! -t 1 ]' in admin_rotate
    assert admin_rotate.index('[ ! -t 1 ]') < admin_rotate.index(
        'ADMIN_KEY="$("${RELEASE_TOOL_PYTHON}"'
    )
    for script in (setup_rotate, admin_rotate):
        assert "refusing to expose plaintext to captured output" in script


def test_host_first_install_helpers_use_controlled_python_311() -> None:
    deploy_dir = _cloud_root() / "deploy"
    for name in (
        "prepare-first-install.sh",
        "admin-key-rotate.sh",
        "first-install-finalize.sh",
        "first-install-rollback.sh",
        "remote-runtime-config-preflight.sh",
    ):
        source = (deploy_dir / name).read_text()
        assert 'NPCINK_CLOUD_RELEASE_TOOL_PYTHON:-/usr/bin/python3.11' in source
        assert "npcink_ai_cloud_require_host_release_tool_python" in source
        assert "\npython3 " not in source
        assert "$(python3 " not in source

    worker_wait = (deploy_dir / "wait-for-install.sh").read_text()
    candidate_preflight = (deploy_dir / "remote-runtime-config-preflight.sh").read_text()
    assert "while ! python -" in worker_wait
    assert "sh -ceu 'python -" in candidate_preflight


def test_production_deploy_explicitly_rejects_contract_overrides_in_dotenv() -> None:
    deploy = (_cloud_root() / "deploy" / "deploy-to-ssh-host.sh").read_text()
    rejection = "Production .env.deploy explicitly forbids contract overrides"
    copy_to_release = 'install -m 0600 "${NEW_ENV_SOURCE}" "${RELEASE_ENV_TMP}"'

    for key in (
        "NPCINK_CLOUD_API_WORKERS",
        "NPCINK_CLOUD_DEPLOY_SMOKE_BACKEND_ENV",
        "NPCINK_CLOUD_DEPLOY_SMOKE_FRONTEND_ENV",
        "NPCINK_CLOUD_DEPLOY_SMOKE_SETUP_STATE_OVERRIDE",
    ):
        assert key in deploy
    assert rejection in deploy
    assert deploy.index(rejection) < deploy.index(copy_to_release)


def test_production_api_worker_count_is_fixed_to_one() -> None:
    cloud_root = _cloud_root()
    for name in ("docker-compose.prod.yml", "docker-compose.runtime.yml"):
        api = _compose_service_block((cloud_root / name).read_text(), "api")
        assert "-w 1" in api
        assert "NPCINK_CLOUD_API_WORKERS" not in api


def test_pg18_proof_covers_runtime_semantics_but_not_rds_tls() -> None:
    cloud_root = _cloud_root()
    gate = (cloud_root / "scripts" / "check-pg18-proof.sh").read_text()
    proof = (cloud_root / "scripts" / "pg18-semantic-proof.py").read_text()
    compose = (cloud_root / "docker-compose.pg18-proof.yml").read_text()

    assert "python scripts/pg18-semantic-proof.py" in gate
    assert "PYTHONPATH: /app" in compose
    assert "no TLS; not RDS evidence" in gate
    for semantic in (
        "jsonb",
        "timestamp with time zone",
        "WHERE active",
        "ON CONFLICT",
        "FOR UPDATE SKIP LOCKED",
        "fence_token = 1",
        "stale fencing token unexpectedly mutated",
    ):
        assert semantic in proof


def test_pending_first_install_preserves_stopped_postgres_for_rollback() -> None:
    cloud_root = _cloud_root()
    deploy = (cloud_root / "deploy" / "deploy-to-ssh-host.sh").read_text()
    loader = (cloud_root / "deploy" / "remote-load-and-up.sh").read_text()
    rollback = (cloud_root / "deploy" / "first-install-rollback.sh").read_text()

    assert 'NPCINK_CLOUD_PRESERVE_FIRST_INSTALL_POSTGRES="${FIRST_INSTALL_PENDING}"' in deploy
    assert "stop_retired_postgres_for_first_install_rollback" in loader
    traffic = loader.split('if [ "${LOAD_MODE}" = "traffic-only" ]; then', 1)[1]
    assert traffic.index("wait_for_public_health") < traffic.index(
        "stop_retired_postgres_for_first_install_rollback"
    )
    assert 'docker stop --time 30 "${container_id}"' in loader
    assert 'docker rm -f "${container_id}"' not in loader.split(
        "stop_retired_postgres_for_first_install_rollback() {", 1
    )[1].split("\n}", 1)[0]
    assert 'npcink_ai_cloud_compose "${root}" up -d' in rollback
    assert "First-install rollback is allowed only before installation completes." in rollback


def test_first_install_lifecycle_mutations_validate_shared_lock_metadata() -> None:
    deploy_dir = _cloud_root() / "deploy"
    for name in ("first-install-finalize.sh", "first-install-rollback.sh"):
        source = (deploy_dir / name).read_text()
        assert 'INSTALL_LOCK_FILE="${CONFIG_DIR}/.install.lock"' in source
        assert "npcink_ai_cloud_start_install_lock_broker" in source
        assert '"${ROOT_DIR}" "${INSTALL_LOCK_FILE}" 0' in source
        assert 'exec 8<>"${INSTALL_LOCK_FILE}"' not in source
        assert "flock -n" not in source

    common = (deploy_dir / "common.sh").read_text()
    helper = (deploy_dir / "install-lock.py").read_text()
    assert 'getattr(os, "O_NOFOLLOW", 0)' in helper
    assert 'getattr(os, "O_NONBLOCK", 0)' in helper
    assert helper.count("_validate_descriptor_path(") >= 3
    assert "fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)" in helper
    assert "path changed while it was opened" in helper
    assert "npcink_ai_cloud_start_install_lock_broker" in common


def test_production_deploy_branches_post_install_gates_on_explicit_state() -> None:
    cloud_root = _cloud_root()
    deploy = (cloud_root / "deploy" / "deploy-to-ssh-host.sh").read_text()
    workflow = (cloud_root / ".github" / "workflows" / "deploy-production.yml").read_text()

    assert "printf 'installation_state=pending\\n'" in deploy
    assert "printf 'installation_state=complete\\n'" in deploy
    assert "id: deploy" in workflow
    assert "^installation_state=(pending|complete)$" in workflow
    assert "exactly one explicit installation_state=pending|complete" in workflow
    assert "steps.deploy.outputs.installation_state == 'pending'" in workflow
    assert workflow.count("steps.deploy.outputs.installation_state == 'complete'") == 2
    assert "Post-install preflight and release smoke were intentionally skipped." in workflow
    assert (
        "While the lifecycle remains pending, run the complete-only Release Smoke workflow"
        in workflow
    )
    assert "Only after those acceptance checks pass" in workflow
    assert workflow.index(
        "While the lifecycle remains pending, run the complete-only Release Smoke workflow"
    ) < workflow.index("Only after those acceptance checks pass")
    assert "setup-code-rotate.sh" in workflow
    assert "first-install-finalize.sh" in workflow
    assert "setup/v1/state" not in workflow
    assert "setup.installation_required" not in workflow


def test_current_release_docs_separate_pg18_gates_from_retired_p1_e06() -> None:
    deploy_dir = _cloud_root() / "deploy"
    checklist = (deploy_dir / "RELEASE_CHECKLIST.md").read_text()
    playbook = (deploy_dir / "OPS_PLAYBOOK.md").read_text()

    assert "Current deployment authority is the fresh PostgreSQL 18 contract" in checklist
    assert "Historical P1-E06 Edge migration evidence (non-normative)" in checklist
    assert "unchecked evidence above is not authoritative for current deployment" in checklist
    assert "Current deployment authority is the fresh PostgreSQL 18 path" in playbook
    assert "Historical P1-E06 Edge migration procedure (non-normative)" in playbook
    assert "Only the CVE acceptance pair is a current, temporary PostgreSQL 18" in playbook
    assert "Both gates are required." not in playbook
    assert "P1-E06 has an independent production Edge hard gate." not in playbook


def test_openai_provider_ceiling_supports_bounded_long_form_runtime(monkeypatch) -> None:
    monkeypatch.delenv("NPCINK_CLOUD_OPENAI_TIMEOUT_SECONDS", raising=False)

    cloud_root = _cloud_root()
    settings = Settings(_env_file=None)
    compose_text = (cloud_root / "docker-compose.prod.yml").read_text()
    readme_text = (cloud_root / "README.md").read_text()

    assert settings.openai_timeout_seconds == 60.0
    assert (
        compose_text.count(
            "NPCINK_CLOUD_OPENAI_TIMEOUT_SECONDS: ${NPCINK_CLOUD_OPENAI_TIMEOUT_SECONDS:-60}"
        )
        == 3
    )
    assert "OpenAI provider ceiling defaults to 60 seconds" in readme_text
    assert "shorter tasks remain constrained by the smaller value" in readme_text


def test_settings_ignore_retired_admin_and_openai_aliases(monkeypatch) -> None:
    monkeypatch.setenv("NPCINK_CLOUD_ENVIRONMENT", "production")
    monkeypatch.setenv("NPCINK_CLOUD_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("NPCINK_CLOUD_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("NPCINK_CLOUD_INTERNAL_AUTH_TOKEN", "i" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN", "b" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_ADMIN_KEY_SHA256", "c" * 64)
    monkeypatch.setenv("NPCINK_CLOUD_ADMIN_SESSION_SECRET", "a" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_OPS_SESSION_SECRET", "z" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_SERVICE_SETTINGS_SECRET", SERVICE_SETTINGS_ROOT)
    monkeypatch.setenv(
        "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID",
        SERVICE_SETTINGS_KEY_ID,
    )
    monkeypatch.setenv("NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET", RUNTIME_DATA_ROOT)
    monkeypatch.setenv("NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID", RUNTIME_DATA_KEY_ID)
    monkeypatch.setenv("NPCINK_CLOUD_PORTAL_JWT_SECRET", "j" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST", "https://cloud.example.com")
    monkeypatch.setenv("NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST", "cloud.example.com")
    monkeypatch.setenv(
        "NPCINK_CLOUD_OPENAI_COMPATIBLE_BASE_URL",
        "https://retired.example.com/v1",
    )
    monkeypatch.setenv("NPCINK_CLOUD_JINA_API_KEY", "retired-jina-secret")
    monkeypatch.setenv("JINA_API_KEY", "external-jina-secret")

    settings = Settings(_env_file=None)

    assert settings.admin_session_secret == "a" * 32
    assert settings.openai_api_key in {None, ""}
    assert settings.openai_base_url == "https://api.openai.com/v1"
    assert settings.site_knowledge_jina_api_key in {None, ""}


def test_retired_ops_secret_does_not_satisfy_production_config(monkeypatch) -> None:
    monkeypatch.setenv("NPCINK_CLOUD_ENVIRONMENT", "production")
    monkeypatch.setenv("NPCINK_CLOUD_INTERNAL_AUTH_TOKEN", "i" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN", "b" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_ADMIN_KEY_SHA256", "c" * 64)
    monkeypatch.delenv("NPCINK_CLOUD_ADMIN_SESSION_SECRET", raising=False)
    monkeypatch.setenv("NPCINK_CLOUD_OPS_SESSION_SECRET", "z" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_SERVICE_SETTINGS_SECRET", SERVICE_SETTINGS_ROOT)
    monkeypatch.setenv(
        "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID",
        SERVICE_SETTINGS_KEY_ID,
    )
    monkeypatch.setenv("NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET", RUNTIME_DATA_ROOT)
    monkeypatch.setenv("NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID", RUNTIME_DATA_KEY_ID)
    monkeypatch.setenv("NPCINK_CLOUD_PORTAL_JWT_SECRET", "j" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST", "https://cloud.example.com")
    monkeypatch.setenv("NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST", "cloud.example.com")

    with pytest.raises(ValueError, match="admin_session_secret is required"):
        Settings(_env_file=None)


def test_preview_and_baseline_scripts_lock_migration_and_schema_checks() -> None:
    cloud_root = _cloud_root()
    dev_compose_text = (cloud_root / "docker-compose.dev.yml").read_text()
    preview_script_path = cloud_root / "scripts" / "remote-preview-mini.sh"
    preview_script = preview_script_path.read_text()
    baseline_script = (_cloud_root() / "deploy" / "remote-baseline-status.sh").read_text()
    nginx_dev_conf = (_cloud_root() / "deploy" / "nginx.dev.conf").read_text()
    release_smoke_script = (_cloud_root() / "deploy" / "release-smoke.sh").read_text()
    remote_smoke_script = (_cloud_root() / "deploy" / "remote-smoke.sh").read_text()
    secret_rotation_script = (_cloud_root() / "deploy" / "validate-secret-rotation.sh").read_text()
    remote_migrate_script = (_cloud_root() / "deploy" / "remote-migrate.sh").read_text()
    deploy_to_ssh_script = (_cloud_root() / "deploy" / "deploy-to-ssh-host.sh").read_text()
    common_script = (_cloud_root() / "deploy" / "common.sh").read_text()
    remote_load_script = (_cloud_root() / "deploy" / "remote-load-and-up.sh").read_text()
    provider_matrix_smoke = (
        _cloud_root() / "deploy" / "remote-provider-matrix-smoke.sh"
    ).read_text()

    assert "alembic upgrade head" in preview_script
    assert "python -m app.dev.baseline_status" in preview_script
    assert (
        'SERVICES="${SERVICES:-api worker callback-worker ops-worker frontend}"' in preview_script
    )
    assert "for service in ${SERVICES}; do" in preview_script
    assert "fatal startup log detected" in preview_script
    assert "NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST" in preview_script
    assert "NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST" in preview_script
    assert "NPCINK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT" in preview_script
    assert "NPCINK_CLOUD_OTEL_TRACE_SINK_OTLP_ENDPOINT" not in preview_script
    assert "NPCINK_CLOUD_OTEL_TRACE_QUERY_URL" in preview_script
    assert "ensure_remote_trace_sink" in preview_script
    assert "verify_remote_trace_sink" in preview_script
    assert "reload_remote_proxy" in preview_script
    assert ".cache/npcink-ai-cloud-mini" in preview_script
    assert "PREVIEW_STACK_SERVICES" in preview_script
    assert "DEPENDENCY_IMAGES=(" in preview_script
    assert (
        "keychain cannot be accessed because the current session does not allow user interaction"
    ) in preview_script
    assert "falling back to local dependency image transfer" in preview_script
    assert "falling back to local build + image transfer" in preview_script
    assert "--pull never" in preview_script
    assert "http://host.docker.internal:4318/v1/traces" in preview_script
    assert "http://${REMOTE_IP}:16686" in preview_script
    assert "--set=receivers.otlp.protocols.http.endpoint=0.0.0.0:4318" in preview_script
    assert "mini-preview-smoke-span" in preview_script
    assert "force_flush()" in preview_script
    assert "api:8000" in preview_script
    assert "proxy:8080" in preview_script
    assert "proxy_set_header Host $host;" in nginx_dev_conf
    assert "proxy_set_header X-Forwarded-Host $host;" in nginx_dev_conf
    assert "location = /health/operational-ready" in nginx_dev_conf
    assert "location /open/" in nginx_dev_conf
    dev_open_block = nginx_dev_conf.split("location /open/ {", 1)[1].split("\n    }", 1)[0]
    assert "proxy_set_header Connection" not in dev_open_block
    assert "callback-worker:" in preview_script
    assert "ops-worker:" in preview_script
    assert "ops-worker:" in dev_compose_text
    assert "python -m app.workers.ops_cadence" in dev_compose_text
    assert "npcink-ai-cloud-ops-worker:dev" in dev_compose_text
    assert "/health/operational-ready" in preview_script
    assert "python -m app.dev.baseline_status" in baseline_script
    assert "/internal/service/observability/summary" in release_smoke_script
    assert "/health/operational-ready" in release_smoke_script
    assert "deploy/remote-smoke.sh" in release_smoke_script
    assert "/internal/service/observability/summary" in remote_smoke_script
    assert "/health/operational-ready" in remote_smoke_script
    assert '"policy":{"allow_fallback":true}}' in remote_smoke_script
    assert 'openssl dgst -sha256 -hmac "${SECRET}"' not in remote_smoke_script
    assert 'NPCINK_CLOUD_HMAC_SECRET="${SECRET}" python3 -c' in remote_smoke_script
    assert 'os.environ.pop("NPCINK_CLOUD_HMAC_SECRET", "")' in remote_smoke_script
    assert "max_retries" not in remote_smoke_script
    assert (
        'NPCINK_CLOUD_OBSERVABILITY_CADENCE_WAIT_ATTEMPTS:-8'
        in remote_smoke_script
    )
    assert (
        'NPCINK_CLOUD_OBSERVABILITY_CADENCE_WAIT_DELAY_SECONDS:-5'
        in remote_smoke_script
    )
    assert "OBSERVABILITY_CADENCE_CONNECT_TIMEOUT_SECONDS=3" in remote_smoke_script
    assert "OBSERVABILITY_CADENCE_MAX_TIME_SECONDS=10" in remote_smoke_script
    assert "OBSERVABILITY_CADENCE_WAIT_WINDOW_SECONDS" in remote_smoke_script
    assert "OBSERVABILITY_CADENCE_WALL_CLOCK_LIMIT_SECONDS" in remote_smoke_script
    assert '"${OBSERVABILITY_CADENCE_WAIT_WINDOW_SECONDS}" -lt 35' in remote_smoke_script
    assert "canonical integer between 1 and 20" in remote_smoke_script
    assert "canonical integer between 0 and 10" in remote_smoke_script
    assert "print_cadence_wait_diagnostics" in remote_smoke_script
    diagnostics_block = remote_smoke_script.split(
        "print_cadence_wait_diagnostics() {", 1
    )[1].split("build_traceparent() {", 1)[0]
    for allowed_diagnostic_field in (
        "task_id",
        "freshness",
        "age_seconds",
        "interval_seconds",
        "last_outcome",
    ):
        assert allowed_diagnostic_field in diagnostics_block
    for cadence_task_id in (
        "retention_cleanup",
        "plugin_observability_cleanup",
        "usage_rollup",
        "router_diagnostics_summary",
        "latency_probe_summary",
        "alert_provider_degradation",
        "provider_health_scan",
        "artifact_cleanup",
        "artifact_inventory_reconciliation",
        "payment_order_expiration",
    ):
        assert f'"{cadence_task_id}"' in diagnostics_block
    assert "safe_task_id_pattern" not in diagnostics_block
    assert 'freshness_values = {"attention", "stale", "missing"}' in diagnostics_block
    assert 'last_outcome_values = {"succeeded", "error"}' in diagnostics_block
    assert 'return "unknown"' in diagnostics_block
    assert "return -1" in diagnostics_block
    assert "if len(diagnostics) >= 10" in diagnostics_block
    assert "payload = sys.stdin.read()" in diagnostics_block
    assert remote_smoke_script.count("payload = sys.stdin.read()") >= 2
    assert "JSON_PAYLOAD" not in remote_smoke_script
    assert 'item.get("payload")' not in diagnostics_block
    assert 'item.get("last_error_message")' not in diagnostics_block
    plain_http_request_block = remote_smoke_script.split("\nhttp_request() {", 1)[
        1
    ].split("\nobservability_summary_request() {", 1)[0]
    assert '_http_request "" "" "$@"' in plain_http_request_block
    observability_request_block = remote_smoke_script.split(
        "\nobservability_summary_request() {", 1
    )[1].split("\nsigned_request() {", 1)[0]
    assert "OBSERVABILITY_CADENCE_CONNECT_TIMEOUT_SECONDS" in (
        observability_request_block
    )
    assert "OBSERVABILITY_CADENCE_MAX_TIME_SECONDS" in observability_request_block
    final_response_marker = remote_smoke_script.index(
        "# Revalidate every requirement against the same final response"
    )
    assert remote_smoke_script.index(
        'assert_status "${HTTP_STATUS}" "200"', final_response_marker
    ) < remote_smoke_script.index(
        'data.workers.totals.missing_total', final_response_marker
    )
    assert remote_smoke_script.index(
        'data.cadence.totals.non_fresh_total', final_response_marker
    ) < remote_smoke_script.index('data.providers.freshness', final_response_marker)
    assert remote_smoke_script.index(
        'data.runtime.summary.callback.pressure_state', final_response_marker
    ) < remote_smoke_script.index(
        'data.tracing.otlp_configured', final_response_marker
    )
    assert "/internal/service/observability/summary" in secret_rotation_script
    assert not (_cloud_root() / "deploy" / "env-to-ssh-host.sh").exists()
    assert not (_cloud_root() / "deploy" / "remote-env-upsert.sh").exists()
    assert "up -d --pull never --no-build" not in remote_migrate_script
    assert "worker callback-worker ops-worker" not in remote_migrate_script
    assert "Migration completed without starting application services" in (
        remote_migrate_script
    )
    assert "SSH identity file not found" in deploy_to_ssh_script
    assert "BatchMode=yes" in deploy_to_ssh_script
    assert "ConnectTimeout" in deploy_to_ssh_script
    assert "SSH target is not reachable" in deploy_to_ssh_script
    assert "Operational readiness gate: enabled" in deploy_to_ssh_script
    assert "Running remote operational readiness gate" in deploy_to_ssh_script
    assert "Remote operational readiness gate passed" in deploy_to_ssh_script
    assert "npcink_ai_cloud_start_timing_summary" in deploy_to_ssh_script
    assert 'remote_run_timed "remote load and up"' in deploy_to_ssh_script
    assert 'remote_run_timed "remote operational readiness"' in deploy_to_ssh_script
    assert "bash deploy/remote-load-and-up.sh </dev/null" in deploy_to_ssh_script
    assert "bash deploy/remote-migrate.sh </dev/null" in deploy_to_ssh_script
    assert "bash deploy/remote-refresh-providers.sh </dev/null" in deploy_to_ssh_script
    assert 'bash deploy/remote-smoke.sh "${SMOKE_ARGS[@]}" </dev/null' in deploy_to_ssh_script
    assert (
        'bash deploy/remote-operational-ready.sh --base-url "${BASE_URL}" </dev/null'
        in deploy_to_ssh_script
    )
    assert "NPCINK_CLOUD_HEALTH_HOST_HEADER" in common_script
    assert "NPCINK_CLOUD_HEALTH_FORWARDED_PROTO" in common_script
    assert "npcink_ai_cloud_run_timed" in common_script
    assert "NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST" in remote_load_script
    assert "configure_ready_origin_headers" in remote_load_script
    assert "up --no-start --pull never --no-build --no-deps --force-recreate" in (
        remote_load_script
    )
    assert 'docker start "${container_ids_to_start[@]}"' in remote_load_script
    assert "NPCINK_CLOUD_REQUIRED_PROVIDER_CAPABILITIES" in provider_matrix_smoke
    assert "db_managed_provider_connections" in provider_matrix_smoke
    assert '"direct_wordpress_write": False' in provider_matrix_smoke
    assert '"secret_exposure": "none"' in provider_matrix_smoke


def test_remote_deploy_keeps_env_file_private_end_to_end() -> None:
    deploy_script = (_cloud_root() / "deploy" / "deploy-to-ssh-host.sh").read_text()

    assert 'chmod 0700 $(remote_shell_arg "${REMOTE_INCOMING_DIR}")' in deploy_script
    upload_marker = 'scp "${SCP_ARGS[@]}" "${ENV_FILE}" "${SSH_TARGET}:${REMOTE_ENV_PATH}"'
    restrict_marker = 'chmod 0600 $(remote_shell_arg "${REMOTE_ENV_PATH}")'
    assert upload_marker in deploy_script
    assert restrict_marker in deploy_script
    assert deploy_script.index(upload_marker) < deploy_script.index(restrict_marker)
    assert (
        r"""test \"\$(stat -c '%a' $(remote_shell_arg "${REMOTE_ENV_PATH}"))\" = 600"""
        in deploy_script
    )
    assert 'RELEASE_STATE_ROOT="${REMOTE_DIR}/.release-state"' in deploy_script
    assert 'RELEASE_STATE_DIR="${RELEASE_STATE_ROOT}/${RELEASE_NAME}"' in deploy_script
    assert 'RELEASE_ENV_FILE="${RELEASE_STATE_DIR}/env.deploy"' in deploy_script
    assert 'ensure_private_release_state_directory "${RELEASE_STATE_ROOT}"' in deploy_script
    assert 'ensure_private_release_state_directory "${RELEASE_STATE_DIR}"' in deploy_script
    assert 'mv -n "${RELEASE_ENV_TMP}" "${RELEASE_ENV_FILE}"' in deploy_script
    assert "Deployment env source must be a root-owned" in deploy_script
    assert 'export NPCINK_CLOUD_ENV_FILE="${RELEASE_ENV_FILE}"' in deploy_script
    assert 'export NPCINK_CLOUD_BACKEND_ENV_FILE="${RELEASE_ENV_FILE}"' in deploy_script
    assert '"${RELEASE_DIR}/${REMOTE_ENV_BASENAME}"' not in deploy_script


def test_deploy_bundle_smoke_uses_sample_provider_and_skip_frontend_contract() -> None:
    cloud_root = _cloud_root()
    ci_workflow = (cloud_root / ".github" / "workflows" / "ci.yml").read_text()
    deploy_workflow = (cloud_root / ".github" / "workflows" / "deploy-production.yml").read_text()
    maintenance_workflow = (
        cloud_root / ".github" / "workflows" / "production-maintenance.yml"
    ).read_text()
    compose_text = (cloud_root / "docker-compose.prod.yml").read_text()
    runtime_compose_text = (cloud_root / "docker-compose.runtime.yml").read_text()
    package_json = (cloud_root / "package.json").read_text()
    frontend_dockerfile = (cloud_root / "frontend" / "Dockerfile").read_text()
    bundle_script = (cloud_root / "deploy" / "bundle-images.sh").read_text()
    remote_load_script = (cloud_root / "deploy" / "remote-load-and-up.sh").read_text()
    static_terms_deploy_script = (
        cloud_root / "deploy" / "deploy-static-terms-to-ssh-host.sh"
    ).read_text()
    next_config = (cloud_root / "frontend" / "next.config.mjs").read_text()
    deploy_bundle_smoke = (cloud_root / "scripts" / "cloud-deploy-bundle-smoke-flow.sh").read_text()
    remote_smoke_script = (cloud_root / "deploy" / "remote-smoke.sh").read_text()
    nginx_prod_conf = (cloud_root / "deploy" / "nginx.prod.conf").read_text()
    frontend_proxy = (cloud_root / "frontend" / "src" / "proxy.ts").read_text()

    package_manager = json.loads(package_json)["packageManager"]
    assert package_manager == (
        "pnpm@10.33.0+sha512."
        "10568bb4a6afb58c9eb3630da90cc9516417abebd3fabbe6739f0ae795728da1491e9db5a544"
        "c76ad8eb7570f5c4bb3d6c637b2cb41bfdcdb47fa823c8649319"
    )
    assert "context: ." in compose_text
    assert "dockerfile: frontend/Dockerfile" in compose_text
    assert "COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./" in frontend_dockerfile
    assert (
        'corepack prepare "$(node -p "require(\'./package.json\').packageManager")" --activate'
        in frontend_dockerfile
    )
    assert "pnpm install --frozen-lockfile --filter frontend..." in frontend_dockerfile

    assert "CLOUD_API_BASE_URL: process.env.CLOUD_API_BASE_URL" not in next_config
    assert "CLOUD_PUBLIC_BASE_URL: process.env.CLOUD_PUBLIC_BASE_URL" not in next_config

    assert 'export NPCINK_CLOUD_ENVIRONMENT="${NPCINK_CLOUD_ENVIRONMENT:-test}"' in (
        deploy_bundle_smoke
    )
    assert 'export NPCINK_CLOUD_DEPLOY_SMOKE_BACKEND_ENV="test"' in deploy_bundle_smoke
    assert "NPCINK_CLOUD_ENVIRONMENT" in deploy_bundle_smoke
    assert "NPCINK_CLOUD_SKIP_FRONTEND_IMAGE" in deploy_bundle_smoke
    assert 'docker image rm "${rollback_reference}"' in deploy_bundle_smoke

    assert 'if [ "${NPCINK_CLOUD_SKIP_FRONTEND_IMAGE:-0}" = "1" ]; then' in (remote_smoke_script)
    assert "Skipping frontend page checks" in remote_smoke_script
    assert "buyer-facing home page should succeed" in remote_smoke_script

    assert "upstream npcink_ai_cloud_frontend" not in nginx_prod_conf
    assert "resolver 127.0.0.11" in nginx_prod_conf
    assert 'set $npcink_ai_cloud_frontend "frontend:3000";' in nginx_prod_conf
    assert "map $http_x_forwarded_proto $npcink_forwarded_proto" in nginx_prod_conf
    assert "map $http_x_forwarded_host $npcink_forwarded_host" in nginx_prod_conf
    assert "proxy_set_header X-Forwarded-Host $host;" not in nginx_prod_conf
    assert "proxy_set_header X-Forwarded-Proto $npcink_forwarded_proto;" in nginx_prod_conf
    assert "location = /admin/auth/login" in nginx_prod_conf
    assert "location = /admin/auth/bootstrap" not in nginx_prod_conf
    assert "location = /setup" in nginx_prod_conf
    assert "location /setup/" in nginx_prod_conf
    assert "location /setup/v1/" in nginx_prod_conf
    assert "location /open/" in nginx_prod_conf
    admin_login_block = nginx_prod_conf.split("location = /admin/auth/login {", 1)[1].split(
        "\n    }",
        1,
    )[0]
    assert "proxy_pass http://$npcink_ai_cloud_frontend;" in admin_login_block
    assert "proxy_pass http://npcink_ai_cloud_api;" not in admin_login_block
    assert "proxy_set_header X-Forwarded-Host" not in admin_login_block
    assert "proxy_connect_timeout 5s;" in admin_login_block
    assert "proxy_read_timeout 30s;" in admin_login_block
    setup_page_block = nginx_prod_conf.split("location = /setup {", 1)[1].split(
        "\n    }", 1
    )[0]
    setup_api_block = nginx_prod_conf.split("location /setup/v1/ {", 1)[1].split(
        "\n    }", 1
    )[0]
    assert "proxy_pass http://$npcink_ai_cloud_frontend;" in setup_page_block
    assert "proxy_pass http://npcink_ai_cloud_api;" not in setup_page_block
    assert "proxy_pass http://npcink_ai_cloud_api;" in setup_api_block
    assert "proxy_pass http://$npcink_ai_cloud_frontend;" not in setup_api_block
    assert "setup.installation_required" in frontend_proxy
    assert "pathname.startsWith('/admin/auth/')" in frontend_proxy
    prod_open_block = nginx_prod_conf.split("location /open/ {", 1)[1].split("\n    }", 1)[0]
    prod_portal_api_block = nginx_prod_conf.split("location /portal/v1/ {", 1)[1].split(
        "\n    }",
        1,
    )[0]
    assert "proxy_set_header Connection" not in prod_open_block
    assert "proxy_set_header Connection" not in prod_portal_api_block
    assert "proxy_set_header Host $npcink_forwarded_host;" in nginx_prod_conf
    assert "proxy_set_header X-Forwarded-Host $npcink_forwarded_host;" in nginx_prod_conf
    assert "proxy_set_header X-Real-IP $remote_addr;" in nginx_prod_conf
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in nginx_prod_conf
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" not in (nginx_prod_conf)
    assert "proxy_pass http://npcink_ai_cloud_api;" in nginx_prod_conf
    assert "./site:/usr/share/nginx/html/npcink-site:ro" in runtime_compose_text
    assert 'git -C "${CLOUD_DIR}" archive HEAD --' in bundle_script
    archive_paths_block = bundle_script.split("ARCHIVE_PATHS=(", 1)[1].split("\n)", 1)[0]
    assert "\n\tsite\n" in archive_paths_block
    assert "location = /terms" in nginx_prod_conf
    assert "try_files /terms/index.html =404;" in nginx_prod_conf
    assert "location /terms/" in nginx_prod_conf
    assert "root /usr/share/nginx/html/npcink-site;" in nginx_prod_conf
    assert "./site:/usr/share/nginx/html/npcink-site:ro" in compose_text
    assert '"${BASE_URL%/}/terms"' in remote_smoke_script
    assert "/terms/en/terms.html" in remote_smoke_script
    assert "/terms/zh/terms.html" in remote_smoke_script
    assert "/terms/styles.css" in remote_smoke_script
    assert "--skip-terms-checks" in remote_smoke_script
    assert "Npcink Cloud Legal Documents" in remote_smoke_script
    assert "data.result.images" in remote_smoke_script
    assert 'INCLUDE_EXTERNAL_IMAGES="${NPCINK_CLOUD_INCLUDE_EXTERNAL_IMAGES:-1}"' in (bundle_script)
    assert "must include every locked external image" in bundle_script
    assert 'IMAGE_LOCK="deploy/image-lock/production-images.json"' in bundle_script
    assert "external-plan" in bundle_script
    assert '"external_${key}"' in bundle_script
    for production_compose in (compose_text, runtime_compose_text):
        for retired_service in ("caddy", "otel-collector", "jaeger"):
            assert f"  {retired_service}:" not in production_compose
        api_block = _compose_service_block(production_compose, "api")
        assert "NPCINK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT:" in api_block
        assert "NPCINK_CLOUD_OTEL_TRACE_QUERY_URL:" in api_block
        for non_http_process in ("worker", "callback-worker", "ops-worker"):
            assert "NPCINK_CLOUD_OTEL_" not in _compose_service_block(
                production_compose,
                non_http_process,
            )
        assert "NPCINK_CLOUD_OTEL_TRACE_SINK_OTLP_ENDPOINT" not in production_compose
        assert "http://otel-collector:4318" not in production_compose
        assert "jaeger:4317" not in production_compose

    assert "RETIRED_BUNDLE_SERVICES=(postgres caddy jaeger otel-collector)" in remote_load_script
    assert "assert_retired_bundle_services_absent" in remote_load_script
    retired_marker = "[ok] Retired bundle services are absent:"
    assert retired_marker in remote_load_script
    assert "--remove-orphans" in remote_load_script
    assert remote_load_script.rindex("assert_retired_bundle_services_absent") < (
        remote_load_script.index('"wait for live health"')
    )
    assert '-C "${CLOUD_DIR}" dist/worker.tar.gz' not in bundle_script
    assert '-C "${CLOUD_DIR}" dist/callback-worker.tar.gz' not in bundle_script
    assert '-C "${CLOUD_DIR}" dist/ops-worker.tar.gz' not in bundle_script
    assert "build api worker callback-worker ops-worker" not in bundle_script
    assert 'GZIP_LEVEL="${NPCINK_CLOUD_BUNDLE_GZIP_LEVEL:-1}"' in bundle_script
    build_cache_scope_prefix = (
        'BUILD_CACHE_SCOPE_PREFIX="${NPCINK_CLOUD_BUILD_CACHE_SCOPE_PREFIX:-npcink-ai-cloud}"'
    )
    assert build_cache_scope_prefix in bundle_script
    assert '--cache-from "type=gha,scope=${BUILD_CACHE_SCOPE_PREFIX}-${cache_scope}"' in (
        bundle_script
    )
    build_cache_to = (
        '--cache-to "type=gha,scope=${BUILD_CACHE_SCOPE_PREFIX}-${cache_scope},'
        'mode=max,ignore-error=true"'
    )
    assert build_cache_to in bundle_script
    assert "set_build_cache_args api" in bundle_script
    assert "set_build_cache_args frontend" in bundle_script
    assert 'gzip -n "-${GZIP_LEVEL}" -c "${archive_path}"' in bundle_script
    assert "docker save" not in bundle_script
    assert 'python3 "${MANIFEST_HELPER}" pack' in bundle_script
    assert '--output "${DIST_DIR}/deploy-bundle.tgz"' in bundle_script
    assert "actions: read" in ci_workflow
    assert "actions: read" in deploy_workflow
    external_images_default = 'NPCINK_CLOUD_INCLUDE_EXTERNAL_IMAGES: "1"'
    assert external_images_default not in ci_workflow
    assert external_images_default in deploy_workflow
    assert "PROD_INCLUDE_EXTERNAL_IMAGES" not in ci_workflow
    assert "PROD_INCLUDE_EXTERNAL_IMAGES" not in deploy_workflow
    assert "deploy_required:" in ci_workflow
    ci_classifier = (
        cloud_root / "scripts" / "classify-ci-changes.sh"
    ).read_text()
    assert ".github/workflows/ci.yml|.github/workflows/deploy-production.yml" in (
        ci_classifier
    )
    assert "docker-compose*.yml|Dockerfile*|*/Dockerfile*|deploy/*.sh" in ci_classifier
    assert "needs: [classify, backend-scope]" in ci_workflow
    assert "needs['backend-scope'].outputs.requires_full_backend == '1'" in ci_workflow
    assert "should be skipped for a targeted PR" in ci_workflow
    backend_gate = (cloud_root / "scripts" / "check-pr-backend-gate.sh").read_text()
    assert "deploy/image-lock/*|deploy/image-lock/**/*" in backend_gate
    assert "scripts/production-python-extras-smoke.sh" in backend_gate
    assert "scripts/production-image-supply.py|scripts/scan-production-images.sh" in backend_gate
    assert 'docker tag "${source_reference}" "${alias_reference}"' in remote_load_script
    assert "load-plan" in remote_load_script
    assert "verify loaded image IDs" in remote_load_script
    assert "static_terms_only" in ci_workflow
    assert "site/terms/*" in ci_classifier
    assert "- secret-scan" in ci_workflow
    assert "backend-scope:" in ci_workflow
    assert "backend-targeted:" in ci_workflow
    assert "backend-static:" in ci_workflow
    assert "backend-pytest:" in ci_workflow
    assert "matrix:" in ci_workflow
    assert "shard: [1, 2, 3]" in ci_workflow
    assert "scripts/select-pytest-shard.py" in ci_workflow
    assert "backend pytest shards did not pass" in ci_workflow
    assert "bash deploy/deploy-static-terms-to-ssh-host.sh" not in ci_workflow
    assert "post-production-smoke:" not in ci_workflow
    assert "bash deploy/deploy-to-ssh-host.sh" not in ci_workflow
    assert "environment: production" not in ci_workflow
    assert "workflow_dispatch:" in deploy_workflow
    assert "workflow_run:" not in deploy_workflow
    assert "environment: production" in deploy_workflow
    assert "Approved for production validation by operator." in deploy_workflow
    assert "select(.head_sha == $sha)" in deploy_workflow
    assert 'test "${conclusion}" = "success"' in deploy_workflow
    assert "bash deploy/small-customer-trial-preflight.sh" in deploy_workflow
    assert "--require-alipay-enabled" in deploy_workflow
    assert "bash deploy/release-smoke.sh --base-url" in deploy_workflow
    assert "ci-observability:" in ci_workflow
    assert "python3 scripts/report-release-timing.py" in ci_workflow
    assert "artifacts/pytest-backend-shard-${{ matrix.shard }}.xml" in ci_workflow
    assert "artifacts/pytest-files-shard-${{ matrix.shard }}.txt" in ci_workflow
    assert "python3 scripts/report-junit-timing.py" in ci_workflow
    assert "actions/checkout@v6" in ci_workflow
    assert "actions/setup-node@v6" in ci_workflow
    assert "actions/setup-python@v6" in ci_workflow
    assert "pnpm/action-setup@v6" in ci_workflow
    assert "docker/setup-buildx-action@v4" in ci_workflow
    assert "gitleaks/gitleaks-action@v3" in ci_workflow
    assert "args: detect --source" not in ci_workflow
    assert "actions/upload-artifact@v7" in ci_workflow
    assert "pytest-backend-timing-shard-${{ matrix.shard }}" in ci_workflow
    assert (cloud_root / "ci" / "pytest-backend-durations.json").is_file()
    assert "deploy:static-terms:ssh" in package_json
    assert "release:junit-timing" in package_json
    assert 'CURRENT_LINK="${REMOTE_DIR}/current"' in static_terms_deploy_script
    assert 'tar czf "${TERMS_BUNDLE}" -C "${ROOT_DIR}/site" terms' in (static_terms_deploy_script)
    assert 'assert_public_static_page "/terms"' in static_terms_deploy_script
    assert "Static terms deploy completed" in static_terms_deploy_script

    assert "name: Production Maintenance" in maintenance_workflow
    assert "github.ref == 'refs/heads/production'" in maintenance_workflow
    assert "environment: production" in maintenance_workflow
    assert "docker container prune -f" in maintenance_workflow
    assert "docker image prune -af" in maintenance_workflow
    assert "docker builder prune -af" in maintenance_workflow
    assert "docker system prune" not in maintenance_workflow
    assert "--volumes" not in maintenance_workflow
    assert 'rm -rf -- "${release_dir}"' in maintenance_workflow


def test_static_terms_pages_are_in_release_tree() -> None:
    cloud_root = _cloud_root()

    expected_files = (
        "site/terms/index.html",
        "site/terms/styles.css",
        "site/terms/assets/icon-128x128.png",
        "site/terms/assets/icon-256x256.png",
        "site/terms/en/index.html",
        "site/terms/en/terms.html",
        "site/terms/en/privacy.html",
        "site/terms/en/data-retention.html",
        "site/terms/zh/index.html",
        "site/terms/zh/terms.html",
        "site/terms/zh/privacy.html",
        "site/terms/zh/data-retention.html",
    )
    for relative_path in expected_files:
        assert (cloud_root / relative_path).is_file()

    assert not (cloud_root / "site" / ".DS_Store").exists()
    assert (
        "Npcink Cloud Terms of Service"
        in (cloud_root / "site" / "terms" / "en" / "terms.html").read_text()
    )
    assert (
        "Npcink Cloud 服务条款" in (cloud_root / "site" / "terms" / "zh" / "terms.html").read_text()
    )


def test_release_gate_documents_current_cloud_blockers() -> None:
    cloud_root = _cloud_root()
    checklist_text = (cloud_root / "deploy" / "RELEASE_CHECKLIST.md").read_text()
    playbook_text = (cloud_root / "deploy" / "OPS_PLAYBOOK.md").read_text()
    deploy_guide = (cloud_root / "deploy" / "PRODUCTION_GITHUB_DEPLOY.md").read_text()
    release_smoke_script = (cloud_root / "deploy" / "release-smoke.sh").read_text()
    remote_smoke_script = (cloud_root / "deploy" / "remote-smoke.sh").read_text()
    secret_rotation_script = (cloud_root / "deploy" / "validate-secret-rotation.sh").read_text()
    release_smoke_env_example = (cloud_root / "deploy" / "release-smoke.env.example").read_text()
    release_smoke_workflow = (
        cloud_root / ".github" / "workflows" / "release-smoke.yml"
    ).read_text()

    for marker in (
        "repo ready",
        "env required",
        "operator required",
        "smoke required",
        "real Alipay transaction",
        "real WordPress reconnect",
        "formal release smoke",
        "schema drift baseline",
        "OTLP sink",
        "24-hour observation",
    ):
        assert marker in checklist_text

    assert "the PC launch candidate is deployed to production" in checklist_text
    assert "Cloud must not be treated as GA-ready" in checklist_text
    assert "deploy/release-smoke.sh" in checklist_text
    assert "Release Smoke" in checklist_text
    assert "manually run the `Release Smoke` workflow from the `production` branch" in (
        checklist_text
    )
    assert "deploy/RELEASE_CHECKLIST.md" in playbook_text
    assert "the release is blocked" in playbook_text
    assert "Do not replace it with a second release entry point" in playbook_text
    assert "deploy/remote-smoke.sh" in release_smoke_script
    assert "--runtime-site-id" in release_smoke_script
    assert "Signed hosted runtime smoke." in release_smoke_env_example
    assert "signed `POST /v1/runtime/execute`" in checklist_text
    assert "signed `GET /v1/catalog/models`" in playbook_text
    assert "deploy/bind-domain-to-ssh-host.sh" in checklist_text
    assert "deploy/bind-domain-to-ssh-host.sh" in playbook_text
    assert "--prepare-only" in checklist_text
    assert "--prepare-only" in playbook_text
    assert "--prepare-only" in deploy_guide
    assert "One locked remote transaction" in deploy_guide
    assert "restarts and verifies those exact original" in deploy_guide

    for formal_https_smoke in (
        release_smoke_script,
        remote_smoke_script,
        secret_rotation_script,
    ):
        assert "assert_json_non_empty() {" in formal_https_smoke
        assert "https://*)" in formal_https_smoke
        assert "data.tracing.otlp_configured" in formal_https_smoke
        assert "data.tracing.otlp_endpoint" in formal_https_smoke
        assert "data.tracing.trace_query_configured" in formal_https_smoke
        assert "data.tracing.trace_query_url" in formal_https_smoke
        assert "data.tracing.trace_sink_otlp_endpoint" not in formal_https_smoke

    for removed_marker in (
        "/v1/addon/dashboard",
        "/v1/addon/providers/release-summary",
        "signed addon projection reads",
        "Signed addon projection smoke.",
    ):
        assert removed_marker not in release_smoke_script
        assert removed_marker not in checklist_text
        assert removed_marker not in playbook_text
        assert removed_marker not in release_smoke_env_example

    assert "workflow_dispatch:" in release_smoke_workflow
    assert "github.ref == 'refs/heads/production'" in release_smoke_workflow
    assert "environment: production" in release_smoke_workflow
    assert "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN" in release_smoke_workflow
    assert "NPCINK_CLOUD_ADMIN_KEY" in release_smoke_workflow
    assert "NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN" not in release_smoke_workflow
    assert "NPCINK_CLOUD_RELEASE_MEMBER_EMAIL" in release_smoke_workflow
    assert "NPCINK_CLOUD_PORTAL_LOGIN_CODE" in release_smoke_workflow
    assert "NPCINK_CLOUD_RELEASE_SITE_ID" in release_smoke_workflow
    assert "NPCINK_CLOUD_RELEASE_KEY_ID" in release_smoke_workflow
    assert "NPCINK_CLOUD_RELEASE_KEY_SECRET" in release_smoke_workflow
    assert "Verify smoke tools" in release_smoke_workflow
    assert "make bootstrap-dev" not in release_smoke_workflow
    assert "--require-smoke-env" in release_smoke_workflow
    assert "--run-release-smoke" in release_smoke_workflow
    assert "--require-alipay-enabled" in release_smoke_workflow
    assert 'if [ -z "${LOGIN_CODE}" ]; then' in release_smoke_script
    assert "Using pre-issued Portal login code" in release_smoke_script
    assert "Reusing persisted Portal session" in release_smoke_script
    assert "NPCINK_CLOUD_PORTAL_COOKIE_JAR" in release_smoke_script
    assert "NPCINK_CLOUD_PORTAL_COOKIE_JAR" in release_smoke_env_example
    assert "Do not persist this file in CI artifacts" in release_smoke_env_example
    assert "skips requesting a replacement code" in release_smoke_env_example
    assert release_smoke_script.count('"Origin: ${BASE_URL%/}"') >= 3
    assert release_smoke_script.count('"data.principal_id"') >= 3
    assert '"data.member_ref"' not in release_smoke_script
    assert '"data.platform_admin_ref"' not in release_smoke_script
    assert "200 | 303" in release_smoke_script


def test_lightweight_release_policy_gate_is_documented(tmp_path: Path) -> None:
    cloud_root = _cloud_root()
    agents_text = (cloud_root / "AGENTS.md").read_text()
    policy_text = (cloud_root / "docs" / "cloud-production-release-policy-v1.md").read_text()
    deploy_text = (cloud_root / "deploy" / "PRODUCTION_GITHUB_DEPLOY.md").read_text()
    pr_template_text = (cloud_root / ".github" / "pull_request_template.md").read_text()
    dependabot_text = (cloud_root / ".github" / "dependabot.yml").read_text()
    package_text = (cloud_root / "package.json").read_text()
    script_text = (cloud_root / "scripts" / "check-release-policy.sh").read_text()

    for marker in (
        "`master` is the development integration branch",
        "`production` is the production release source",
        "Do not directly edit production application code on the server.",
        "Approved for production validation by operator.",
        "Cloud is not becoming a WordPress write owner",
        "Branch divergence is expected",
        "9aca0dc0",
        "c9f3036b",
    ):
        assert marker in policy_text

    expected_dependabot_config = {
        "version": 2,
        "updates": [
            {
                "package-ecosystem": "github-actions",
                "directory": "/",
                "schedule": {
                    "interval": "weekly",
                    "day": "monday",
                    "time": "09:00",
                    "timezone": "Asia/Shanghai",
                },
                "open-pull-requests-limit": 2,
                "labels": ["dependencies"],
            },
            {
                "package-ecosystem": "npm",
                "directory": "/",
                "schedule": {
                    "interval": "weekly",
                    "day": "monday",
                    "time": "09:30",
                    "timezone": "Asia/Shanghai",
                },
                "open-pull-requests-limit": 2,
                "labels": ["dependencies"],
            },
            {
                "package-ecosystem": "uv",
                "directory": "/",
                "schedule": {
                    "interval": "weekly",
                    "day": "monday",
                    "time": "10:00",
                    "timezone": "Asia/Shanghai",
                },
                "open-pull-requests-limit": 2,
                "labels": ["dependencies"],
            },
        ],
    }

    def assert_dependabot_config(config_text: str) -> None:
        assert yaml.safe_load(config_text) == expected_dependabot_config

    extra_job_config = (
        dependabot_text
        + """
  - package-ecosystem: npm
    directory: /frontend
    schedule:
      interval: weekly
      day: monday
      time: "10:30"
      timezone: Asia/Shanghai
    open-pull-requests-limit: 2
    labels:
      - dependencies
"""
    )
    adversarial_configs = (
        "version: 2\nupdates: []\n",
        "version: 2\n# open-pull-requests-limit: 2\nupdates: []\n",
        extra_job_config,
    )

    assert_dependabot_config(dependabot_text)
    for adversarial_config in adversarial_configs:
        with pytest.raises(AssertionError):
            assert_dependabot_config(adversarial_config)

    valid_fixture = _release_policy_fixture_root(tmp_path / "valid", dependabot_text)
    valid_result = _run_release_policy_with_restricted_path(valid_fixture, tmp_path / "valid")
    assert valid_result.returncode == 0, valid_result.stderr
    assert "Lightweight release policy gate passed" in valid_result.stdout

    for index, adversarial_config in enumerate(adversarial_configs):
        case_root = tmp_path / f"invalid-{index}"
        fixture_root = _release_policy_fixture_root(case_root, adversarial_config)
        result = _run_release_policy_with_restricted_path(fixture_root, case_root)
        assert result.returncode != 0
        assert "does not match the canonical pre-GA policy" in result.stderr

    nul_case_root = tmp_path / "invalid-nul-tail"
    nul_fixture = _release_policy_fixture_root(nul_case_root, dependabot_text)
    (nul_fixture / ".github" / "dependabot.yml").write_bytes(
        dependabot_text.encode() + b"\x00\nupdates: []\n"
    )
    nul_result = _run_release_policy_with_restricted_path(nul_fixture, nul_case_root)
    assert nul_result.returncode != 0
    assert "does not match the canonical pre-GA policy" in nul_result.stderr

    compose_seam_cases = (
        (
            "docker-compose.prod.yml",
            "api",
            "${NPCINK_CLOUD_API_RELEASE_IMAGE:-npcink-ai-cloud-api:prod}",
            "npcink-ai-cloud-api:prod",
        ),
        (
            "docker-compose.runtime.yml",
            "api",
            "${NPCINK_CLOUD_API_RELEASE_IMAGE:-npcink-ai-cloud-api:prod}",
            "npcink-ai-cloud-api:prod",
        ),
        (
            "docker-compose.prod.yml",
            "release-one-off",
            "${NPCINK_CLOUD_API_RELEASE_IMAGE:-npcink-ai-cloud-api:prod}",
            "npcink-ai-cloud-api:prod",
        ),
        (
            "docker-compose.runtime.yml",
            "release-one-off",
            "${NPCINK_CLOUD_API_RELEASE_IMAGE:-npcink-ai-cloud-api:prod}",
            "npcink-ai-cloud-api:prod",
        ),
    )
    for index, (compose_name, service, governed_seam, literal_image) in enumerate(
        compose_seam_cases
    ):
        case_root = tmp_path / f"invalid-compose-seam-{index}"
        fixture_root = _release_policy_fixture_root(case_root, dependabot_text)
        compose_path = fixture_root / compose_name
        compose_text = (_cloud_root() / compose_name).read_text()
        service_marker = f"  {service}:\n"
        before_service, service_and_after = compose_text.split(service_marker, 1)
        governed_line = f"    image: {governed_seam}"
        assert governed_line in service_and_after
        service_and_after = service_and_after.replace(
            governed_line,
            f"    image: {literal_image}\n    # {governed_line.strip()}",
            1,
        )
        compose_path.unlink()
        compose_path.write_text(before_service + service_marker + service_and_after)

        result = _run_release_policy_with_restricted_path(fixture_root, case_root)
        assert result.returncode != 0
        assert "must use the exact governed release image seam" in result.stderr

    assert "docs/cloud-production-release-policy-v1.md" in deploy_text
    assert "pnpm run check:release-policy" in deploy_text
    assert "/terms/en/terms.html" in deploy_text
    assert "static terms fast path" in deploy_text
    assert "Focused module:" in pr_template_text
    assert "Cloud boundary impact:" in pr_template_text
    assert "does not commit production secrets" in pr_template_text
    assert "check:release-policy" in package_text
    assert "Lightweight release policy gate passed" in script_text
    assert "require_canonical_dependabot_config" in script_text
    assert "require_service_image_seam" in script_text
    assert "uv run" not in script_text
    assert "yaml.safe_load" not in script_text
    assert "/terms/en/terms.html" in script_text
    assert "deploy-static-terms-to-ssh-host.sh" in script_text

    for marker in (
        "AI Production Operation Rules",
        "Production source branch is `production`",
        "Do not directly edit production application code on the server.",
        "Any emergency server fix must be backported to Git before the next deploy.",
        "Do not commit SMTP passwords",
        "Do not push or deploy to Gitee. Current project source control is GitHub-only.",
        "pnpm run check:release-policy",
    ):
        assert marker in agents_text


def test_release_policy_service_marker_checks_are_pipefail_safe(tmp_path: Path) -> None:
    cloud_root = _cloud_root()
    dependabot_text = (cloud_root / ".github" / "dependabot.yml").read_text()
    script_text = (cloud_root / "scripts" / "check-release-policy.sh").read_text()
    old_pipeline = (
        'compose_service_block "${path}" "${service}" | grep -Fq -- "${marker}"'
    )

    required_case_root = tmp_path / "required-marker-large-service"
    required_fixture = _release_policy_fixture_root(required_case_root, dependabot_text)
    _inflate_compose_service_block(
        required_fixture / "docker-compose.prod.yml",
        "api",
    )
    required_result = _run_release_policy_with_restricted_path(
        required_fixture,
        required_case_root,
    )
    assert required_result.returncode == 0, required_result.stderr
    assert "Lightweight release policy gate passed" in required_result.stdout

    forbidden_case_root = tmp_path / "forbidden-marker-large-service"
    forbidden_fixture = _release_policy_fixture_root(forbidden_case_root, dependabot_text)
    _inflate_compose_service_block(
        forbidden_fixture / "docker-compose.prod.yml",
        "frontend",
        marker_after_header="    env_file:\n      - .env.deploy\n",
    )
    forbidden_result = _run_release_policy_with_restricted_path(
        forbidden_fixture,
        forbidden_case_root,
    )
    assert forbidden_result.returncode != 0
    assert (
        "Forbidden frontend service marker in docker-compose.prod.yml: env_file:"
        in forbidden_result.stderr
    )

    assert old_pipeline not in script_text
    assert script_text.count(
        'service_block="$(compose_service_block "${path}" "${service}")"'
    ) == 2
    assert script_text.count('grep -Fq -- "${marker}" <<<"${service_block}"') == 2


def test_controlled_production_cve_risk_acceptance_is_external_and_bundle_bound() -> None:
    cloud_root = _cloud_root()
    contract = "npcink.controlled_production_cve_risk_acceptance.v1"
    decision = (
        cloud_root
        / "docs"
        / "python-3-14-6-controlled-production-validation-risk-decision-2026-07-21.md"
    ).read_text()
    ops_playbook = (cloud_root / "deploy" / "OPS_PLAYBOOK.md").read_text()
    release_checklist = (cloud_root / "deploy" / "RELEASE_CHECKLIST.md").read_text()
    release_policy = (cloud_root / "scripts" / "check-release-policy.sh").read_text()

    for marker in (
        contract,
        "accepted_by_operator",
        "controlled_production_validation_only",
        "GA is not authorized",
    ):
        assert marker in decision

    template_text = decision.split("```json\n", maxsplit=1)[1].split(
        "\n```", maxsplit=1
    )[0]
    template = json.loads(template_text)
    assert set(template) == {
        "contract",
        "status",
        "scope",
        "decision_document",
        "source_revision",
        "source_tree",
        "bundle_sha256",
        "scan_index_sha256",
        "api_scan_receipt_sha256",
        "allowlist_sha256",
        "scan_index_status",
        "api_scan_status",
        "image_platform",
        "api_image_reference",
        "blocking_finding_count",
        "allowlisted_blocking_finding_count",
        "unallowlisted_blocking_finding_count",
        "allowlisted_findings",
        "cisa_ssvc_exploitation",
        "cisa_ssvc_checked_at_utc",
        "exception_expires_on",
        "ga_authorized",
        "authorized_by",
        "authorized_at_utc",
    }
    assert template == {
        "contract": contract,
        "status": "accepted_by_operator",
        "scope": "controlled_production_validation_only",
        "decision_document": (
            "docs/python-3-14-6-controlled-production-validation-risk-decision-"
            "2026-07-21.md"
        ),
        "source_revision": "<40-lowercase-hex>",
        "source_tree": "<40-lowercase-hex>",
        "bundle_sha256": "<64-lowercase-hex>",
        "scan_index_sha256": "<64-lowercase-hex>",
        "api_scan_receipt_sha256": "<64-lowercase-hex>",
        "allowlist_sha256": "<64-lowercase-hex>",
        "scan_index_status": "passed",
        "api_scan_status": "passed",
        "image_platform": "linux/amd64",
        "api_image_reference": "npcink-ai-cloud-api:prod",
        "blocking_finding_count": 3,
        "allowlisted_blocking_finding_count": 3,
        "unallowlisted_blocking_finding_count": 0,
        "allowlisted_findings": [
            {
                "vulnerability_id": "CVE-2026-11940",
                "package": "python",
                "package_version": "3.14.6",
                "severity": "high",
                "fix_state": "unknown",
            },
            {
                "vulnerability_id": "CVE-2026-11972",
                "package": "python",
                "package_version": "3.14.6",
                "severity": "high",
                "fix_state": "unknown",
            },
            {
                "vulnerability_id": "CVE-2026-15308",
                "package": "python",
                "package_version": "3.14.6",
                "severity": "high",
                "fix_state": "fixed",
            },
        ],
        "cisa_ssvc_exploitation": {
            "CVE-2026-11940": "none",
            "CVE-2026-11972": "none",
            "CVE-2026-15308": "none",
        },
        "cisa_ssvc_checked_at_utc": "<RFC3339-UTC>",
        "exception_expires_on": "2026-08-05",
        "ga_authorized": False,
        "authorized_by": "Muze",
        "authorized_at_utc": "<RFC3339-UTC>",
    }
    assert "receipt_sha256" not in template
    assert "acceptance_sha256" not in template

    assert contract in ops_playbook
    assert contract in release_checklist
    assert contract in release_policy
    for marker in (
        "outside Git, the deploy bundle, and every release tree",
        "owner-only mode-`0600` file",
        "record its SHA-256 separately",
        "cannot contain a self-digest",
    ):
        assert marker in decision
    verifier = (cloud_root / "scripts" / "check-first-install-cve-gate.py").read_text()
    deploy = (cloud_root / "deploy" / "deploy-to-ssh-host.sh").read_text()
    assert contract in verifier
    assert "--controlled-cve-risk-acceptance" in deploy
    assert "--controlled-cve-risk-acceptance-checksum" in deploy
    assert contract not in (
        cloud_root / "scripts" / "production-image-supply.py"
    ).read_text()


def test_exact_release_docs_freeze_map_trust_and_cutover_batch_order() -> None:
    cloud_root = _cloud_root()
    checklist = " ".join((cloud_root / "deploy" / "RELEASE_CHECKLIST.md").read_text().split())
    contract = " ".join(
        (cloud_root / "docs" / "p5-b5-exact-release-bundle-v1.md").read_text().split()
    )

    for marker in (
        ".release-state/<release-name>/target-daemon-images.json",
        "owner-controlled non-symlink mode-`0700` directories",
        "owner-controlled non-symlink regular file with mode `0600`",
        "maps larger than 256 KiB",
        "canonical resolved release path",
        "same deployment lock",
        "required a fresh `prepare-only` plus full verifier run",
        "each `data-only`, `api-only`, `workers-only`, and `traffic-only` batch",
        "Only a fully proved batch was started by its captured IDs",
        "post-start gate proved those same IDs were running the same images",
    ):
        assert marker in checklist

    for marker in (
        "every governed service image, including `release-one-off`",
        "literal mutable tag is rejected",
        "canonical resolved release path",
        "operator must rerun `prepare-only` and the full verifier",
        "`data-only`, `api-only`, `workers-only`, and `traffic-only` batches",
        "same IDs are running with the same images",
    ):
        assert marker in contract

    migration = contract.index("then run migration and provider refresh")
    pointer = contract.index("atomically promote the `current` link")
    api = contract.index("After the pointer switch, start and verify the API batch")
    readiness = contract.index("prove release-specific and generic operational readiness")
    assert migration < pointer < api < readiness


def test_runtime_image_prepares_writable_shared_artifact_volume() -> None:
    cloud_root = Path(__file__).resolve().parents[2]
    dockerfile = (cloud_root / "Dockerfile").read_text()
    assert "mkdir -p /app/.runtime" in dockerfile
    assert "/var/lib/npcink-ai-cloud/artifacts" in dockerfile
    assert (
        "chown -R app:app /app/.runtime /home/app /var/lib/npcink-ai-cloud/artifacts" in dockerfile
    )
    assert "chown -R app:app /app " not in dockerfile
    assert "COPY --chown=app" not in dockerfile
    assert dockerfile.index("chown -R app:app") < dockerfile.index("USER app")

    for compose_name in (
        "docker-compose.dev.yml",
        "docker-compose.prod.yml",
        "docker-compose.runtime.yml",
    ):
        compose = (cloud_root / compose_name).read_text()
        assert "NPCINK_CLOUD_ARTIFACT_STORE_ROOT: /var/lib/npcink-ai-cloud/artifacts" in compose
        assert "cloud-artifacts-" in compose
