from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def _copy_fixture(tmp_path: Path, *relative_paths: str) -> Path:
    fixture = tmp_path / "fixture"
    for relative_path in relative_paths:
        target = fixture / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative_path, target)
    return fixture


def _install_fake_curl(fake_bin: Path) -> None:
    _write(
        fake_bin / "curl",
        r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

args = sys.argv[1:]
log_path = Path(os.environ["CURL_ARGV_LOG"])
with log_path.open("a", encoding="utf-8") as handle:
    handle.write("curl\t" + "\t".join(args) + "\n")

for key in os.environ.get("FORBIDDEN_CURL_ENV_KEYS", "").split(","):
    if key and os.environ.get(key):
        raise SystemExit(97)

output_path = None
headers_path = None
request_header_path = None
request_body_path = None
write_status = False
url = ""
index = 0
while index < len(args):
    value = args[index]
    if value in {"-o", "-D", "-w", "--header", "--data-binary"} and index + 1 < len(args):
        selected = args[index + 1]
        if value == "-o":
            output_path = selected
        elif value == "-D":
            headers_path = selected
        elif value == "-w":
            write_status = True
        elif value == "--header" and selected.startswith("@"):
            request_header_path = selected[1:]
        elif value == "--data-binary" and selected.startswith("@"):
            request_body_path = selected[1:]
        index += 2
        continue
    if value.startswith(("http://", "https://")):
        url = value
    index += 1

if not output_path and not write_status:
    raise SystemExit(0)

request_headers = ""
if request_header_path:
    request_headers = Path(request_header_path).read_text(encoding="utf-8")
request_body = ""
if request_body_path:
    request_body = Path(request_body_path).read_text(encoding="utf-8")

path = urlparse(url).path
status = "200"
body: object = {"status": "ok", "data": {}}
response_headers = ["HTTP/1.1 200 OK"]

if path in {"/docs", "/redoc"}:
    status = "404"
    body = {"status": "error"}
elif path == "/health/ready":
    if "X-Npcink-Internal-Token:" not in request_headers:
        status = "401"
        body = {"status": "error"}
    else:
        body = {"status": "ok", "data": {}}
elif path == "/internal/catalog/refresh":
    status = "401"
    body = {"status": "error"}
elif path == "/health/operational-ready":
    body = {"status": "ok", "data": {"required_workers": ["runtime_queue"]}}
elif path == "/internal/service/observability/summary":
    observability_failure_mode = os.environ.get("OBSERVABILITY_FAILURE_MODE", "")
    if observability_failure_mode == "transport_timeout":
        raise SystemExit(28)
    sequence = [
        int(value)
        for value in os.environ.get("OBSERVABILITY_CADENCE_SEQUENCE", "0").split(",")
    ]
    state_value = 0
    state_location = os.environ.get("OBSERVABILITY_CADENCE_STATE_PATH", "")
    if state_location:
        observability_state = Path(state_location)
        if observability_state.exists():
            state_value = int(observability_state.read_text(encoding="utf-8") or "0")
        observability_state.write_text(str(state_value + 1), encoding="utf-8")
    non_fresh_total = sequence[min(state_value, len(sequence) - 1)]
    is_fresh = non_fresh_total == 0
    diagnostic_secret = os.environ.get("OBSERVABILITY_DIAGNOSTIC_SECRET", "")
    malicious_diagnostics = (
        os.environ.get("OBSERVABILITY_MALICIOUS_DIAGNOSTICS", "") == "1"
    )
    diagnostic_item = {
        "task_id": (
            diagnostic_secret
            if malicious_diagnostics
            else "payment_order_expiration"
        ),
        "freshness": (
            diagnostic_secret
            if malicious_diagnostics
            else ("fresh" if is_fresh else "attention")
        ),
        "age_seconds": (
            diagnostic_secret
            if malicious_diagnostics
            else (0 if is_fresh else 61)
        ),
        "interval_seconds": True if malicious_diagnostics else 60,
        "last_outcome": (
            diagnostic_secret if malicious_diagnostics else "succeeded"
        ),
        "last_error_message": diagnostic_secret,
        "payload": {"private": diagnostic_secret},
    }
    body = {
        "status": "ok",
        "data": {
            "workers": {"totals": {"missing_total": 0 if is_fresh else 9}},
            "cadence": {
                "totals": {
                    "tasks_total": 1,
                    "non_fresh_total": non_fresh_total,
                },
                "items": [diagnostic_item] * (11 if malicious_diagnostics else 1),
            },
            "providers": {"freshness": "fresh" if is_fresh else "stale"},
            "runtime": {
                "summary": {
                    "callback": {
                        "pressure_state": "healthy" if is_fresh else "critical"
                    }
                }
            },
            "tracing": {
                "otlp_configured": is_fresh,
                "otlp_endpoint": "https://otel.example.test",
                "trace_query_configured": is_fresh,
                "trace_query_url": "https://trace.example.test",
            },
        },
    }
    if observability_failure_mode == "http_non_200":
        status = "503"
    elif observability_failure_mode == "malformed_json":
        body = "{"
    elif observability_failure_mode == "missing_field":
        del body["data"]["cadence"]["totals"]["non_fresh_total"]
    elif observability_failure_mode == "wrong_type":
        body["data"]["cadence"]["totals"]["non_fresh_total"] = {
            "unexpected": True
        }
elif path == "/v1/catalog/models":
    body = {"status": "ok", "data": {"items": [{"id": "model"}]}}
elif path == "/v1/runtime/execute":
    body = {
        "status": "ok",
        "data": {
            "status": "succeeded",
            "run_id": "run_1",
            "provider_id": "provider",
            "model_id": "model",
            "instance_id": "instance",
        },
    }
elif path == "/v1/runs/run_1/result":
    body = {"status": "ok", "data": {"result": {"output_text": "ok"}}}
elif path == "/v1/runs/run_1":
    body = {"status": "ok", "data": {"run_id": "run_1"}}
elif path.startswith("/v1/stats/profiles/"):
    body = {"status": "ok", "data": {"profile_id": path.rsplit("/", 1)[-1]}}
elif path == "/v1/usage/summary":
    body = {
        "status": "ok",
        "data": {"windows": {"rolling_24h": {"provider_calls_total": 1}}},
    }
elif path == "/portal/v1/auth/code/request":
    body = {"status": "ok", "data": {"delivery": "smtp", "member_ref": "user:member@example.test"}}
elif path == "/portal/v1/auth/code/verify":
    body = {"status": "ok", "data": {"principal_id": "principal_1"}}
elif path == "/portal/v1/session":
    body = {
        "status": "ok",
        "data": {
            "principal_id": "principal_1",
            "member_ref": "user:member@example.test",
            "site_id": "site_runtime",
        },
    }
elif path == "/admin/auth/bootstrap":
    state_path = Path(os.environ["CURL_STATE_PATH"])
    count = int(state_path.read_text(encoding="utf-8") or "0") if state_path.exists() else 0
    state_path.write_text(str(count + 1), encoding="utf-8")
    if count == 0:
        status = "401"
        body = {"status": "error"}
    else:
        response_headers.append("Set-Cookie: npcink_admin_session_token=session")
        body = {"status": "ok", "data": {}}
elif path == "/admin/session":
    body = {"status": "ok", "data": {"principal_id": "admin_1"}}
elif path.endswith("/summary") and "/portal/v1/sites/" in path:
    body = {"status": "ok", "data": {"site_id": "site_runtime"}}
elif path.endswith("/usage-summary"):
    body = {"status": "ok", "data": {"windows": {"today": {"runs_total": 1}}}}
elif path.endswith("/entitlements"):
    body = {"status": "ok", "data": {"site": {"site_id": "site_runtime"}}}
elif path.endswith("/billing-snapshots/reconciliation"):
    body = {"status": "ok", "data": {"snapshot": {"totals": {"runs": 1}}}}
elif path.endswith("/api-keys"):
    body = {"status": "ok", "data": {"items": [{"key_id": "key_runtime"}]}}

response_headers[0] = f"HTTP/1.1 {status} Fixture"
if output_path:
    serialized = body if isinstance(body, str) else json.dumps(body, separators=(",", ":"))
    Path(output_path).write_text(serialized, encoding="utf-8")
if headers_path:
    Path(headers_path).write_text("\r\n".join(response_headers) + "\r\n\r\n", encoding="utf-8")
if write_status:
    sys.stdout.write(status)
''',
        executable=True,
    )


def test_production_workflows_serialize_host_mutation_and_confirm_prune() -> None:
    deploy = (ROOT / ".github/workflows/deploy-production.yml").read_text(encoding="utf-8")
    maintenance = (ROOT / ".github/workflows/production-maintenance.yml").read_text(
        encoding="utf-8"
    )

    assert "group: production-host-mutation" in deploy
    assert "group: production-host-mutation" in maintenance
    assert "group: production-deploy" not in deploy
    assert "group: production-maintenance" not in maintenance
    assert "permissions: {}" in maintenance
    assert "safe_prune_confirmation:" in maintenance
    assert "Prune production images and old releases." in maintenance
    assert 'MAINTENANCE_ACTION}" = "safe-prune"' in maintenance
    assert '[[ ! "${PROD_REMOTE_DIR}" =~ ^/[A-Za-z0-9._/-]+$ ]]' in maintenance
    assert "remote_shell_arg() {" in maintenance
    assert "printf '%q' \"$1\"" in maintenance
    assert '"${ssh_target}" "${remote_command}"' in maintenance
    assert '"${ssh_target}" bash -s --' not in maintenance
    assert 'mkdir -- "${remote_dir}/.deploy-lock"' in maintenance
    assert 'rmdir -- "${remote_dir}/.deploy-lock"' in maintenance
    assert "Production deploy or another mutating operation holds the lock." in maintenance


def test_secret_bearing_cli_and_http_argv_patterns_are_retired() -> None:
    deploy = (ROOT / "deploy/deploy-to-ssh-host.sh").read_text(encoding="utf-8")
    release = (ROOT / "deploy/release-smoke.sh").read_text(encoding="utf-8")
    remote = (ROOT / "deploy/remote-smoke.sh").read_text(encoding="utf-8")
    seed = (ROOT / "deploy/remote-seed-runtime.sh").read_text(encoding="utf-8")
    portal = (ROOT / "deploy/remote-portal-smoke.sh").read_text(encoding="utf-8")
    bootstrap = (ROOT / "deploy/remote-bootstrap-portal-site.sh").read_text(
        encoding="utf-8"
    )
    bootstrap_ssh = (ROOT / "deploy/bootstrap-portal-site-to-ssh-host.sh").read_text(
        encoding="utf-8"
    )
    operational = (ROOT / "deploy/remote-operational-ready.sh").read_text(
        encoding="utf-8"
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert '"${SECRET}"' not in "\n".join(
        line for line in deploy.splitlines() if "REMOTE_SEQUENCE_VALUES" in line
    )
    assert '--secret "${SECRET}"' not in deploy
    assert '--secret "${RUNTIME_SECRET}"' not in release
    assert '-hmac "${SECRET}"' not in remote
    assert '--secret "${SECRET}"' not in seed
    assert '--secret "${SECRET}"' not in bootstrap
    assert 'SECRET="${NPCINK_CLOUD_SECRET:-}"' in remote
    assert "npcink-cloud-test-secret" not in remote
    assert "NPCINK_CLOUD_SECRET is required for signed runtime smoke" in remote
    assert "--secret npcink-cloud-test-secret" not in readme
    assert "IFS= read -r -s NPCINK_CLOUD_SECRET" in readme
    assert "NPCINK_CLOUD_SECRET is required with --issue-key" in bootstrap
    assert "Remote portal bootstrap does not support --issue-key" in bootstrap_ssh
    assert "--secret is forbidden" in bootstrap_ssh
    assert bootstrap_ssh.index("--secret)") < bootstrap_ssh.index('REMOTE_CMD="')
    assert bootstrap_ssh.index("--issue-key)") < bootstrap_ssh.index('REMOTE_CMD="')
    for script in (release, remote, portal):
        assert '--data "${body}"' not in script
        assert '--data-binary "@${request_body}"' in script
        assert '--header "@${request_headers}"' in script
    assert '-H "X-Npcink-Internal-Token:' not in operational
    assert '--header "@${REQUEST_HEADERS}"' in operational
    assert "deploy-input.json" in deploy
    assert "mode-0600" in deploy


def test_full_deploy_keeps_secret_out_of_local_and_remote_argv(tmp_path: Path) -> None:
    fixture = _copy_fixture(
        tmp_path,
        "deploy/deploy-to-ssh-host.sh",
        "deploy/common.sh",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    temp_root = tmp_path / "tmp"
    temp_root.mkdir()
    bundle = fixture / "dist/deploy-bundle.tgz"
    bundle.parent.mkdir()
    bundle.write_bytes(b"fixture\n")
    bundle.with_suffix(bundle.suffix + ".sha256").write_text(
        f"{'a' * 64}  deploy-bundle.tgz\n", encoding="utf-8"
    )
    _write(
        fixture / "deploy/verify-release-bundle.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n",
        executable=True,
    )
    _write(
        fixture / "scripts/verify-release-bundle-manifest.py",
        """from __future__ import annotations
import sys
if sys.argv[1:2] == ["archive-platform"]:
    print("linux/amd64")
    raise SystemExit(0)
raise SystemExit(64)
""",
    )
    _write(
        fake_bin / "ssh",
        r'''#!/bin/bash
set -euo pipefail
if [ -n "${NPCINK_CLOUD_SECRET:-}" ]; then
    exit 97
fi
if [ -n "${SECRET:-}" ]; then
    exit 98
fi
{
    printf 'ssh'
    for arg in "$@"; do printf '\t%s' "${arg}"; done
    printf '\n'
} >>"${SSH_ARGV_LOG}"
command_line="$*"
if [[ "${command_line}" == *"id -u"* ]]; then printf '0\n'; exit 0; fi
if [[ "${command_line}" == *"version_info"* ]]; then printf '3.11.9\n'; exit 0; fi
if [[ "${command_line}" == *"uname -m"* ]]; then printf 'x86_64\n'; exit 0; fi
if [[ "${command_line}" == *"bash -s --"* ]]; then cat >/dev/null; fi
exit 0
''',
        executable=True,
    )
    _write(
        fake_bin / "scp",
        r'''#!/usr/bin/env bash
set -euo pipefail
if [ -n "${NPCINK_CLOUD_SECRET:-}" ]; then
    exit 97
fi
if [ -n "${SECRET:-}" ]; then
    exit 98
fi
{
    printf 'scp'
    for arg in "$@"; do printf '\t%s' "${arg}"; done
    printf '\n'
} >>"${SCP_ARGV_LOG}"
''',
        executable=True,
    )

    secret = "deploy-runtime-secret-sentinel"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "TMPDIR": str(temp_root),
            "SSH_ARGV_LOG": str(log_dir / "ssh.log"),
            "SCP_ARGV_LOG": str(log_dir / "scp.log"),
            "NPCINK_CLOUD_SECRET": secret,
            "SECRET": "ambient-exported-secret-sentinel",
        }
    )
    completed = subprocess.run(
        [
            "/bin/bash",
            str(fixture / "deploy/deploy-to-ssh-host.sh"),
            "--skip-bundle-build",
            "--skip-seed",
            "--skip-smoke",
            "--ssh-host",
            "fixture.invalid",
            "--remote-dir",
            "/srv/npcink-cloud",
            "--bundle-path",
            str(bundle),
        ],
        cwd=fixture,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    evidence = "\n".join(
        (
            completed.stdout,
            completed.stderr,
            (log_dir / "ssh.log").read_text(encoding="utf-8"),
            (log_dir / "scp.log").read_text(encoding="utf-8"),
        )
    )
    assert completed.returncode == 0, evidence
    assert secret not in evidence
    assert "bash\t-s\t--\tdeploy" in evidence
    assert "deploy-input.json" in evidence
    assert list(temp_root.iterdir()) == []


def test_release_and_remote_smoke_keep_http_credentials_out_of_argv(
    tmp_path: Path,
) -> None:
    fixture = _copy_fixture(
        tmp_path,
        "deploy/common.sh",
        "deploy/release-smoke.sh",
        "deploy/remote-smoke.sh",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _install_fake_curl(fake_bin)
    _write(
        fake_bin / "bash",
        r'''#!/bin/bash
set -euo pipefail
{
    printf 'bash'
    for arg in "$@"; do printf '\t%s' "${arg}"; done
    printf '\n'
} >>"${BASH_ARGV_LOG}"
if [[ "${1:-}" == */deploy/remote-smoke.sh ]]; then
    exit 0
fi
exec /bin/bash "$@"
''',
        executable=True,
    )
    curl_log = tmp_path / "curl.log"
    bash_log = tmp_path / "bash.log"
    state_path = tmp_path / "curl-state"
    temp_root = tmp_path / "request-tmp"
    temp_root.mkdir()
    credentials = tmp_path / "release-credentials.json"
    sentinels = {
        "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN": "internal-token-sentinel",
        "NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN": "admin-token-sentinel",
        "NPCINK_CLOUD_RELEASE_MEMBER_EMAIL": "member@example.test",
        "NPCINK_CLOUD_PORTAL_LOGIN_CODE": "login-code-sentinel",
        "NPCINK_CLOUD_RELEASE_SITE_ID": "site_runtime",
        "NPCINK_CLOUD_RELEASE_KEY_ID": "key_runtime",
        "NPCINK_CLOUD_RELEASE_KEY_SECRET": "runtime-secret-sentinel",
    }
    credentials.write_text(json.dumps(sentinels), encoding="utf-8")
    credentials.chmod(0o600)
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "TMPDIR": str(temp_root),
            "CURL_ARGV_LOG": str(curl_log),
            "BASH_ARGV_LOG": str(bash_log),
            "CURL_STATE_PATH": str(state_path),
            "FORBIDDEN_CURL_ENV_KEYS": ",".join(
                (
                    "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN",
                    "NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN",
                    "NPCINK_CLOUD_PORTAL_LOGIN_CODE",
                    "NPCINK_CLOUD_RELEASE_KEY_SECRET",
                    "NPCINK_CLOUD_SECRET",
                )
            ),
        }
    )
    completed = subprocess.run(
        [
            "/bin/bash",
            str(fixture / "deploy/release-smoke.sh"),
            "--base-url",
            "http://cloud.example.test",
            "--credentials-file",
            str(credentials),
        ],
        cwd=fixture,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    evidence = "\n".join(
        (
            completed.stdout,
            completed.stderr,
            curl_log.read_text(encoding="utf-8"),
            bash_log.read_text(encoding="utf-8") if bash_log.exists() else "",
        )
    )
    assert completed.returncode == 0, evidence
    for key, value in sentinels.items():
        if key.endswith(("TOKEN", "LOGIN_CODE", "KEY_SECRET")):
            assert value not in evidence
    curl_argv = curl_log.read_text(encoding="utf-8")
    assert "--header\t@" in curl_argv
    assert "--data-binary\t@" in curl_argv
    assert "X-Npcink-Internal-Token:" not in curl_argv
    assert list(temp_root.iterdir()) == []

    curl_log.unlink()
    state_path.unlink(missing_ok=True)

    missing_remote_secret_environment = environment.copy()
    missing_remote_secret_environment.update(
        {
            "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN": "remote-internal-token-sentinel",
            "NPCINK_CLOUD_SKIP_FRONTEND_IMAGE": "1",
        }
    )
    missing_remote_secret_environment.pop("NPCINK_CLOUD_SECRET", None)
    missing_remote_secret = subprocess.run(
        [
            "/bin/bash",
            str(fixture / "deploy/remote-smoke.sh"),
            "--base-url",
            "http://cloud.example.test",
        ],
        cwd=fixture,
        env=missing_remote_secret_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert missing_remote_secret.returncode == 1
    assert "NPCINK_CLOUD_SECRET is required for signed runtime smoke" in (
        missing_remote_secret.stderr
    )
    assert not curl_log.exists()

    remote_environment = environment.copy()
    remote_environment.update(
        {
            "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN": "remote-internal-token-sentinel",
            "NPCINK_CLOUD_SECRET": "remote-runtime-secret-sentinel",
            "NPCINK_CLOUD_SKIP_FRONTEND_IMAGE": "1",
            "FORBIDDEN_CURL_ENV_KEYS": "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN,NPCINK_CLOUD_SECRET",
        }
    )
    remote = subprocess.run(
        [
            "/bin/bash",
            str(fixture / "deploy/remote-smoke.sh"),
            "--base-url",
            "http://cloud.example.test",
            "--site-id",
            "site_runtime",
            "--key-id",
            "key_runtime",
            "--skip-terms-checks",
        ],
        cwd=fixture,
        env=remote_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    remote_evidence = "\n".join(
        (remote.stdout, remote.stderr, curl_log.read_text(encoding="utf-8"))
    )
    assert remote.returncode == 0, remote_evidence
    assert "remote-internal-token-sentinel" not in remote_evidence
    assert "remote-runtime-secret-sentinel" not in remote_evidence
    assert "X-Npcink-Signature:" not in curl_log.read_text(encoding="utf-8")
    assert list(temp_root.iterdir()) == []


def test_remote_smoke_waits_for_final_fresh_observability_response(
    tmp_path: Path,
) -> None:
    fixture = _copy_fixture(
        tmp_path,
        "deploy/common.sh",
        "deploy/remote-smoke.sh",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _install_fake_curl(fake_bin)
    curl_log = tmp_path / "curl.log"
    observability_state = tmp_path / "observability-state"
    temp_root = tmp_path / "request-tmp"
    temp_root.mkdir()
    diagnostic_secret = "observability-private-payload-sentinel"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "TMPDIR": str(temp_root),
            "CURL_ARGV_LOG": str(curl_log),
            "CURL_STATE_PATH": str(tmp_path / "curl-state"),
            "OBSERVABILITY_CADENCE_SEQUENCE": "1,0",
            "OBSERVABILITY_CADENCE_STATE_PATH": str(observability_state),
            "OBSERVABILITY_DIAGNOSTIC_SECRET": diagnostic_secret,
            "NPCINK_CLOUD_ENVIRONMENT": "test",
            "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN": "remote-internal-token-sentinel",
            "NPCINK_CLOUD_SECRET": "remote-runtime-secret-sentinel",
            "NPCINK_CLOUD_SKIP_FRONTEND_IMAGE": "1",
            "NPCINK_CLOUD_OBSERVABILITY_CADENCE_WAIT_ATTEMPTS": "2",
            "NPCINK_CLOUD_OBSERVABILITY_CADENCE_WAIT_DELAY_SECONDS": "0",
            "FORBIDDEN_CURL_ENV_KEYS": (
                "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN,NPCINK_CLOUD_SECRET"
            ),
        }
    )

    completed = subprocess.run(
        [
            "/bin/bash",
            str(fixture / "deploy/remote-smoke.sh"),
            "--base-url",
            "http://cloud.example.test",
            "--site-id",
            "site_runtime",
            "--key-id",
            "key_runtime",
            "--skip-terms-checks",
        ],
        cwd=fixture,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    curl_argv = curl_log.read_text(encoding="utf-8")
    evidence = "\n".join((completed.stdout, completed.stderr, curl_argv))
    assert completed.returncode == 0, evidence
    assert observability_state.read_text(encoding="utf-8") == "2"
    assert curl_argv.count("/internal/service/observability/summary") == 2
    observability_requests = [
        line
        for line in curl_argv.splitlines()
        if "/internal/service/observability/summary" in line
    ]
    assert all("\t--connect-timeout\t3" in line for line in observability_requests)
    assert all("\t--max-time\t10" in line for line in observability_requests)
    for unbounded_request_path in ("/v1/catalog/models", "/v1/runtime/execute"):
        matching_requests = [
            line
            for line in curl_argv.splitlines()
            if unbounded_request_path in line
        ]
        assert matching_requests
        assert all(
            "--connect-timeout" not in line and "--max-time" not in line
            for line in matching_requests
        )
    assert "/v1/catalog/models" in curl_argv
    assert "cadence_diagnostic=" not in evidence
    assert diagnostic_secret not in evidence
    assert list(temp_root.iterdir()) == []


def test_remote_smoke_cadence_timeout_is_fail_closed_and_redacted(
    tmp_path: Path,
) -> None:
    fixture = _copy_fixture(
        tmp_path,
        "deploy/common.sh",
        "deploy/remote-smoke.sh",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _install_fake_curl(fake_bin)
    curl_log = tmp_path / "curl.log"
    observability_state = tmp_path / "observability-state"
    temp_root = tmp_path / "request-tmp"
    temp_root.mkdir()
    diagnostic_secret = "a" * 64
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "TMPDIR": str(temp_root),
            "CURL_ARGV_LOG": str(curl_log),
            "CURL_STATE_PATH": str(tmp_path / "curl-state"),
            "OBSERVABILITY_CADENCE_SEQUENCE": "1,1",
            "OBSERVABILITY_CADENCE_STATE_PATH": str(observability_state),
            "OBSERVABILITY_DIAGNOSTIC_SECRET": diagnostic_secret,
            "OBSERVABILITY_MALICIOUS_DIAGNOSTICS": "1",
            "NPCINK_CLOUD_ENVIRONMENT": "test",
            "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN": "remote-internal-token-sentinel",
            "NPCINK_CLOUD_SECRET": "remote-runtime-secret-sentinel",
            "NPCINK_CLOUD_SKIP_FRONTEND_IMAGE": "1",
            "NPCINK_CLOUD_OBSERVABILITY_CADENCE_WAIT_ATTEMPTS": "2",
            "NPCINK_CLOUD_OBSERVABILITY_CADENCE_WAIT_DELAY_SECONDS": "0",
            "FORBIDDEN_CURL_ENV_KEYS": (
                "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN,NPCINK_CLOUD_SECRET"
            ),
        }
    )

    completed = subprocess.run(
        [
            "/bin/bash",
            str(fixture / "deploy/remote-smoke.sh"),
            "--base-url",
            "http://cloud.example.test",
            "--site-id",
            "site_runtime",
            "--key-id",
            "key_runtime",
            "--skip-terms-checks",
        ],
        cwd=fixture,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    curl_argv = curl_log.read_text(encoding="utf-8")
    evidence = "\n".join((completed.stdout, completed.stderr, curl_argv))
    assert completed.returncode == 1, evidence
    assert observability_state.read_text(encoding="utf-8") == "2"
    assert curl_argv.count("/internal/service/observability/summary") == 2
    assert "/v1/catalog/models" not in curl_argv
    diagnostic_lines = [
        line
        for line in completed.stderr.splitlines()
        if line.startswith("cadence_diagnostic=")
    ]
    assert len(diagnostic_lines) == 10
    expected_diagnostic = {
        "task_id": "unknown",
        "freshness": "unknown",
        "age_seconds": -1,
        "interval_seconds": -1,
        "last_outcome": "unknown",
    }
    assert [
        json.loads(diagnostic_line.split("=", 1)[1])
        for diagnostic_line in diagnostic_lines
    ] == [expected_diagnostic] * 10
    assert "bounded wait expired" in completed.stderr
    assert diagnostic_secret not in evidence
    assert "last_error_message" not in completed.stderr
    assert '"payload"' not in completed.stderr
    assert list(temp_root.iterdir()) == []


@pytest.mark.parametrize(
    ("failure_mode", "expected_error"),
    (
        pytest.param(
            "transport_timeout",
            "HTTP request failed",
            id="transport-timeout",
        ),
        pytest.param(
            "http_non_200",
            "observability summary with internal token should succeed",
            id="http-non-200",
        ),
        pytest.param(
            "malformed_json",
            "observability summary should expose cadence non-fresh total",
            id="malformed-json",
        ),
        pytest.param(
            "missing_field",
            "observability summary should expose cadence non-fresh total",
            id="missing-field",
        ),
        pytest.param(
            "wrong_type",
            "observability cadence non-fresh total must be a non-negative integer",
            id="wrong-type",
        ),
    ),
)
def test_remote_smoke_observability_failures_stop_before_runtime(
    tmp_path: Path,
    failure_mode: str,
    expected_error: str,
) -> None:
    fixture = _copy_fixture(
        tmp_path,
        "deploy/common.sh",
        "deploy/remote-smoke.sh",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _install_fake_curl(fake_bin)
    curl_log = tmp_path / "curl.log"
    temp_root = tmp_path / "request-tmp"
    temp_root.mkdir()
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "TMPDIR": str(temp_root),
            "CURL_ARGV_LOG": str(curl_log),
            "CURL_STATE_PATH": str(tmp_path / "curl-state"),
            "OBSERVABILITY_FAILURE_MODE": failure_mode,
            "NPCINK_CLOUD_ENVIRONMENT": "test",
            "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN": "remote-internal-token-sentinel",
            "NPCINK_CLOUD_SECRET": "remote-runtime-secret-sentinel",
            "NPCINK_CLOUD_SKIP_FRONTEND_IMAGE": "1",
            "NPCINK_CLOUD_OBSERVABILITY_CADENCE_WAIT_ATTEMPTS": "2",
            "NPCINK_CLOUD_OBSERVABILITY_CADENCE_WAIT_DELAY_SECONDS": "0",
            "FORBIDDEN_CURL_ENV_KEYS": (
                "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN,NPCINK_CLOUD_SECRET"
            ),
        }
    )

    completed = subprocess.run(
        [
            "/bin/bash",
            str(fixture / "deploy/remote-smoke.sh"),
            "--base-url",
            "http://cloud.example.test",
            "--site-id",
            "site_runtime",
            "--key-id",
            "key_runtime",
            "--skip-terms-checks",
        ],
        cwd=fixture,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    curl_argv = curl_log.read_text(encoding="utf-8")
    observability_requests = [
        line
        for line in curl_argv.splitlines()
        if "/internal/service/observability/summary" in line
    ]
    assert completed.returncode == 1
    assert expected_error in completed.stderr
    assert len(observability_requests) == 1
    assert "\t--connect-timeout\t3" in observability_requests[0]
    assert "\t--max-time\t10" in observability_requests[0]
    assert "/v1/catalog/models" not in curl_argv
    assert "/v1/runtime/execute" not in curl_argv
    assert list(temp_root.iterdir()) == []


@pytest.mark.parametrize(
    ("attempts", "delay_seconds", "expected_error"),
    (
        pytest.param(
            "7",
            "5",
            "wait window must cover at least 35 seconds",
            id="short-production-window",
        ),
        pytest.param(
            "08",
            "5",
            "WAIT_ATTEMPTS must be a canonical integer between 1 and 20",
            id="non-canonical-attempts",
        ),
        pytest.param(
            "21",
            "5",
            "WAIT_ATTEMPTS must be a canonical integer between 1 and 20",
            id="attempts-above-bound",
        ),
        pytest.param(
            "8",
            "00",
            "WAIT_DELAY_SECONDS must be a canonical integer between 0 and 10",
            id="non-canonical-delay",
        ),
        pytest.param(
            "8",
            "11",
            "WAIT_DELAY_SECONDS must be a canonical integer between 0 and 10",
            id="delay-above-bound",
        ),
    ),
)
def test_remote_smoke_rejects_invalid_observability_wait_configuration(
    tmp_path: Path,
    attempts: str,
    delay_seconds: str,
    expected_error: str,
) -> None:
    fixture = _copy_fixture(
        tmp_path,
        "deploy/common.sh",
        "deploy/remote-smoke.sh",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _install_fake_curl(fake_bin)
    curl_log = tmp_path / "curl.log"
    temp_root = tmp_path / "request-tmp"
    temp_root.mkdir()
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "TMPDIR": str(temp_root),
            "CURL_ARGV_LOG": str(curl_log),
            "CURL_STATE_PATH": str(tmp_path / "curl-state"),
            "NPCINK_CLOUD_ENVIRONMENT": "production",
            "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN": "remote-internal-token-sentinel",
            "NPCINK_CLOUD_SECRET": "remote-runtime-secret-sentinel",
            "NPCINK_CLOUD_SKIP_FRONTEND_IMAGE": "1",
            "NPCINK_CLOUD_OBSERVABILITY_CADENCE_WAIT_ATTEMPTS": attempts,
            "NPCINK_CLOUD_OBSERVABILITY_CADENCE_WAIT_DELAY_SECONDS": delay_seconds,
            "FORBIDDEN_CURL_ENV_KEYS": (
                "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN,NPCINK_CLOUD_SECRET"
            ),
        }
    )

    completed = subprocess.run(
        [
            "/bin/bash",
            str(fixture / "deploy/remote-smoke.sh"),
            "--base-url",
            "http://cloud.example.test",
            "--site-id",
            "site_runtime",
            "--key-id",
            "key_runtime",
            "--skip-terms-checks",
        ],
        cwd=fixture,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert expected_error in completed.stderr
    assert not curl_log.exists()
    assert list(temp_root.iterdir()) == []


def test_seed_bootstrap_operational_and_portal_children_hide_secrets(
    tmp_path: Path,
) -> None:
    fixture = _copy_fixture(
        tmp_path,
        "deploy/common.sh",
        "deploy/remote-seed-runtime.sh",
        "deploy/remote-bootstrap-portal-site.sh",
        "deploy/remote-operational-ready.sh",
        "deploy/remote-portal-smoke.sh",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    exact_api_image_id = f"sha256:{'a' * 64}"
    (tmp_path / ".release-state").mkdir(mode=0o700)
    (fixture / "docker-compose.prod.yml").write_text(
        "services: {}\n", encoding="utf-8"
    )
    _write(
        fixture / "scripts/verify-release-bundle-manifest.py",
        r'''from __future__ import annotations

import os
import sys

arguments = sys.argv[1:]
if (
    len(arguments) != 5
    or arguments[0] != "loaded-role-daemon-id"
    or arguments[1] != "--root"
    or arguments[3:] != ["--role", "api"]
):
    raise SystemExit(64)
print(os.environ["EXACT_API_IMAGE_ID"])
''',
    )
    _write(
        fake_bin / "docker",
        r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

arguments = sys.argv[1:]
with open(os.environ["DOCKER_ARGV_LOG"], "a", encoding="utf-8") as handle:
    handle.write("docker\t" + "\t".join(arguments) + "\n")

candidate = Path(os.environ["ONE_OFF_CANDIDATE"])
started = Path(os.environ["ONE_OFF_STARTED"])
container_id = "secret-proof-container"
exact_id = os.environ["EXACT_API_IMAGE_ID"]

if arguments[:1] == ["compose"]:
    if "config" in arguments and arguments[-1] == "release-one-off":
        print(json.dumps({"services": {"release-one-off": {"image": exact_id}}}))
        raise SystemExit(0)
    if "ps" in arguments and arguments[-1] == "release-one-off":
        if candidate.exists():
            print(container_id)
        raise SystemExit(0)
    if "up" in arguments and arguments[-1] == "release-one-off":
        candidate.touch()
        started.unlink(missing_ok=True)
        raise SystemExit(0)
    if "rm" in arguments and arguments[-1] == "release-one-off":
        candidate.unlink(missing_ok=True)
        started.unlink(missing_ok=True)
        raise SystemExit(0)
    raise SystemExit(64)

if arguments[:2] == ["container", "ls"]:
    if candidate.exists():
        print(container_id)
    raise SystemExit(0)
if arguments[:2] == ["image", "inspect"]:
    print(exact_id)
    raise SystemExit(0)
if arguments[:2] == ["inspect", "--format"]:
    if arguments[2] == "{{.Image}}":
        print(exact_id)
    elif arguments[2] == "{{.State.Status}} {{.RestartCount}}":
        print("running 0" if started.exists() else "created 0")
    elif arguments[2] == "{{.State.Running}}":
        print("true" if started.exists() else "false")
    else:
        raise SystemExit(64)
    raise SystemExit(0)
if arguments[:2] == ["start", container_id]:
    started.touch()
    raise SystemExit(0)
if arguments[:1] == ["exec"]:
    sys.stdin.buffer.read()
    raise SystemExit(0)
if arguments[:2] == ["rm", "-f"]:
    candidate.unlink(missing_ok=True)
    started.unlink(missing_ok=True)
    raise SystemExit(0)
raise SystemExit(64)
''',
        executable=True,
    )
    _install_fake_curl(fake_bin)
    curl_log = tmp_path / "curl.log"
    temp_root = tmp_path / "tmp"
    temp_root.mkdir()
    base_environment = os.environ.copy()
    base_environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{base_environment['PATH']}",
            "DOCKER_ARGV_LOG": str(docker_log),
            "CURL_ARGV_LOG": str(curl_log),
            "CURL_STATE_PATH": str(tmp_path / "curl-state"),
            "EXACT_API_IMAGE_ID": exact_api_image_id,
            "ONE_OFF_CANDIDATE": str(tmp_path / "one-off-candidate"),
            "ONE_OFF_STARTED": str(tmp_path / "one-off-started"),
            "NPCINK_CLOUD_RELEASE_TOOL_PYTHON": sys.executable,
            "TMPDIR": str(temp_root),
        }
    )

    missing_bootstrap_environment = base_environment.copy()
    missing_bootstrap_environment.update(
        {
            "NPCINK_CLOUD_SITE_ID": "site_runtime",
            "NPCINK_CLOUD_MEMBER_EMAIL": "member@example.test",
        }
    )
    missing_bootstrap_environment.pop("NPCINK_CLOUD_SECRET", None)
    missing_bootstrap = subprocess.run(
        [
            "/bin/bash",
            str(fixture / "deploy/remote-bootstrap-portal-site.sh"),
            "--issue-key",
        ],
        cwd=fixture,
        env=missing_bootstrap_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert missing_bootstrap.returncode == 1
    assert "NPCINK_CLOUD_SECRET is required with --issue-key" in missing_bootstrap.stderr
    assert not docker_log.exists()

    seed_environment = base_environment.copy()
    seed_environment["NPCINK_CLOUD_SECRET"] = "seed-secret-sentinel"
    seed = subprocess.run(
        ["/bin/bash", str(fixture / "deploy/remote-seed-runtime.sh")],
        cwd=fixture,
        env=seed_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert seed.returncode == 0, f"{seed.stdout}\n{seed.stderr}"

    bootstrap_environment = base_environment.copy()
    bootstrap_environment.update(
        {
            "NPCINK_CLOUD_SECRET": "bootstrap-secret-sentinel",
            "NPCINK_CLOUD_SITE_ID": "site_runtime",
            "NPCINK_CLOUD_MEMBER_EMAIL": "member@example.test",
        }
    )
    bootstrap = subprocess.run(
        ["/bin/bash", str(fixture / "deploy/remote-bootstrap-portal-site.sh")],
        cwd=fixture,
        env=bootstrap_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert bootstrap.returncode == 0, f"{bootstrap.stdout}\n{bootstrap.stderr}"
    docker_argv = docker_log.read_text(encoding="utf-8")
    assert "seed-secret-sentinel" not in docker_argv
    assert "bootstrap-secret-sentinel" not in docker_argv
    assert "--env\tNPCINK_CLOUD_SEED_RUNTIME_SECRET" in docker_argv
    assert "--env\tNPCINK_CLOUD_BOOTSTRAP_SITE_SECRET" in docker_argv
    assert "--site-admin-email\tmember@example.test" in docker_argv
    assert "--member-role" not in docker_argv

    operational_environment = base_environment.copy()
    operational_environment.update(
        {
            "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN": "operational-token-sentinel",
            "FORBIDDEN_CURL_ENV_KEYS": "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN",
        }
    )
    operational = subprocess.run(
        [
            "/bin/bash",
            str(fixture / "deploy/remote-operational-ready.sh"),
            "--base-url",
            "http://cloud.example.test",
        ],
        cwd=fixture,
        env=operational_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert operational.returncode == 0, f"{operational.stdout}\n{operational.stderr}"

    portal_environment = base_environment.copy()
    portal_environment.update(
        {
            "NPCINK_CLOUD_PORTAL_LOGIN_CODE": "portal-code-sentinel",
            "NPCINK_CLOUD_SITE_ID": "site_runtime",
            "NPCINK_CLOUD_MEMBER_EMAIL": "member@example.test",
            "FORBIDDEN_CURL_ENV_KEYS": "NPCINK_CLOUD_PORTAL_LOGIN_CODE",
        }
    )
    portal = subprocess.run(
        [
            "/bin/bash",
            str(fixture / "deploy/remote-portal-smoke.sh"),
            "--base-url",
            "http://cloud.example.test",
        ],
        cwd=fixture,
        env=portal_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    evidence = "\n".join(
        (
            operational.stdout,
            operational.stderr,
            portal.stdout,
            portal.stderr,
            curl_log.read_text(encoding="utf-8"),
        )
    )
    assert portal.returncode == 0, evidence
    assert "operational-token-sentinel" not in evidence
    assert "portal-code-sentinel" not in evidence
    assert "--header\t@" in curl_log.read_text(encoding="utf-8")
    assert "--data-binary\t@" in curl_log.read_text(encoding="utf-8")
    assert list(temp_root.iterdir()) == []
