from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCOPED_SCRIPTS = (
    "scripts/cloud-deploy-bundle-smoke-flow.sh",
    "scripts/local-alpha-smoke.sh",
    "scripts/site-knowledge-real-chain-smoke.sh",
    "deploy/dev/remote-portal-login-code-smoke.sh",
    "deploy/validate-secret-rotation.sh",
)


def _write(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def _copy_common(fixture: Path) -> None:
    target = fixture / "deploy/common.sh"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "deploy/common.sh", target)


def _install_fake_curl(fake_bin: Path) -> None:
    _write(
        fake_bin / "curl",
        r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys

args = sys.argv[1:]
with open(os.environ["ARGV_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(args, ensure_ascii=True) + "\n")

protected_paths: list[Path] = []
for index, value in enumerate(args):
    if value in {"--header", "--data-binary"} and index + 1 < len(args):
        candidate = args[index + 1]
        if candidate.startswith("@"):
            protected_paths.append(Path(candidate[1:]))

with open(os.environ["PATH_LOG"], "a", encoding="utf-8") as handle:
    for path in protected_paths:
        metadata = path.stat()
        mode = stat.S_IMODE(metadata.st_mode)
        if mode != 0o600:
            raise SystemExit(f"protected request file has mode {mode:o}")
        handle.write(str(path) + "\n")

def option_value(*names: str) -> str:
    for index, value in enumerate(args):
        if value in names and index + 1 < len(args):
            return args[index + 1]
    return ""

response_body = os.environ.get("FAKE_CURL_BODY", "{}")
body_path = option_value("-o", "--output")
if body_path:
    Path(body_path).write_text(response_body, encoding="utf-8")
headers_path = option_value("-D", "--dump-header")
if headers_path:
    Path(headers_path).write_text("HTTP/1.1 200 OK\r\n\r\n", encoding="utf-8")
if "-w" in args or "--write-out" in args:
    sys.stdout.write(os.environ.get("FAKE_CURL_STATUS", "200"))
''',
        executable=True,
    )


def _install_fake_child_bash(fake_bin: Path) -> None:
    _write(
        fake_bin / "bash",
        r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys

key = os.environ.get("OBSERVED_ENV_KEY", "NPCINK_CLOUD_SECRET")
expected = os.environ.get("EXPECTED_SECRET", "")
record = {
    "argv": sys.argv[1:],
    "secret_present": bool(expected) and os.environ.get(key, "") == expected,
}
with open(os.environ["CHILD_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(record, ensure_ascii=True) + "\n")
''',
        executable=True,
    )


def _read_json_lines(path: Path) -> list[object]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _assert_secrets_absent(completed: subprocess.CompletedProcess[str], *secrets: str) -> None:
    output = completed.stdout + completed.stderr
    for secret in secrets:
        assert secret not in output


def _assert_request_files_were_protected_and_removed(path_log: Path) -> None:
    paths = [Path(line) for line in path_log.read_text(encoding="utf-8").splitlines()]
    assert paths
    assert all(not path.exists() for path in paths)


def test_local_smoke_sources_retire_secret_bearing_process_arguments() -> None:
    sources = {
        relative: (ROOT / relative).read_text(encoding="utf-8")
        for relative in SCOPED_SCRIPTS
    }

    for source in sources.values():
        assert "set +x" in source
        assert "body=${HTTP_BODY}" not in source

    combined = "\n".join(sources.values())
    assert "openssl dgst -sha256 -hmac" not in combined
    assert not re.search(r'--secret\s+"\$\{SECRET\}"', combined)
    assert '--login-code "${LOGIN_CODE}"' not in combined
    assert '--data-urlencode "pwd=${WORDPRESS_ADMIN_PASSWORD}"' not in combined

    bundle = sources["scripts/cloud-deploy-bundle-smoke-flow.sh"]
    assert 'unset NPCINK_CLOUD_SECRET' in bundle
    assert 'NPCINK_CLOUD_SECRET="${SECRET}"' in bundle

    alpha = sources["scripts/local-alpha-smoke.sh"]
    knowledge = sources["scripts/site-knowledge-real-chain-smoke.sh"]
    for source in (alpha, knowledge):
        assert 'NPCINK_CLOUD_HMAC_SECRET="${SECRET}" python3 -c' in source
        assert "seed_site_auth" in source
        assert '--header "@${request_headers}"' in source
        assert '--data-binary "@${request_body}"' in source

    dev_portal = sources["deploy/dev/remote-portal-login-code-smoke.sh"]
    assert "--login-code is forbidden" in dev_portal
    assert 'NPCINK_CLOUD_PORTAL_LOGIN_CODE="${LOGIN_CODE}"' in dev_portal

    rotation = sources["deploy/validate-secret-rotation.sh"]
    assert 'unset NPCINK_CLOUD_INTERNAL_AUTH_TOKEN' in rotation
    assert 'X-Npcink-Internal-Token: ${INTERNAL_AUTH_TOKEN}' in rotation


def test_alpha_and_site_knowledge_http_hmac_helpers_hide_secrets(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _install_fake_curl(fake_bin)
    _write(fake_bin / "docker", "#!/bin/sh\nexit 0\n", executable=True)
    argv_log = tmp_path / "curl-argv.jsonl"
    path_log = tmp_path / "request-paths.txt"

    cases = (
        (
            "scripts/local-alpha-smoke.sh",
            'ok "Ensuring local Cloud dev services are running"',
            '''
signature="$(build_signature \
  "POST" "/v1/runtime/execute" "" "1700000000" "nonce" "idem" \
  "00-00000000000000000000000000000000-0000000000000000-01" \
  '{"code":"local-login-secret"}')"
[ "${#signature}" -eq 64 ]
http_request \
  "POST" "http://127.0.0.1/test" "${PORTAL_COOKIE_JAR}" \
  '{"code":"local-login-secret"}' \
  "X-Npcink-Internal-Token: ${NPCINK_CLOUD_INTERNAL_AUTH_TOKEN}"
''',
            {
                "NPCINK_CLOUD_SECRET": "local-runtime-secret",
                "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN": "local-internal-secret",
                "NPCINK_CLOUD_ADMIN_KEY": "local-admin-secret",
            },
            (
                "local-runtime-secret",
                "local-login-secret",
                "local-internal-secret",
                "local-admin-secret",
            ),
        ),
        (
            "scripts/site-knowledge-real-chain-smoke.sh",
            'if [ "${RUN_COMPOSE_UP}" = "true" ]; then',
            '''
signature="$(build_signature \
  "POST" "/v1/runtime/execute" "" "1700000000" "nonce" "idem" \
  "00-00000000000000000000000000000000-0000000000000000-01" \
  '{"credential":"knowledge-body-secret"}')"
[ "${#signature}" -eq 64 ]
http_request \
  "POST" "http://127.0.0.1/test" \
  '{"credential":"knowledge-body-secret"}' \
  "X-Test-Secret: knowledge-header-secret"
''',
            {"NPCINK_CLOUD_SITE_KNOWLEDGE_SMOKE_SECRET": "knowledge-runtime-secret"},
            ("knowledge-runtime-secret", "knowledge-body-secret", "knowledge-header-secret"),
        ),
    )

    for index, (relative, marker, appended, extra_env, secrets) in enumerate(cases):
        fixture = tmp_path / f"fixture-{index}"
        _copy_common(fixture)
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert marker in source
        harness = fixture / relative
        _write(harness, source.split(marker, 1)[0] + appended, executable=True)
        env = os.environ.copy()
        env.update(extra_env)
        env.update(
            {
                "PATH": f"{fake_bin}:{env['PATH']}",
                "ARGV_LOG": str(argv_log),
                "PATH_LOG": str(path_log),
                "NPCINK_CLOUD_LOCAL_ALPHA_SMOKE_EVIDENCE_DIR": str(tmp_path / "alpha-evidence"),
                "NPCINK_CLOUD_SITE_KNOWLEDGE_SMOKE_EVIDENCE_DIR": str(
                    tmp_path / "knowledge-evidence"
                ),
            }
        )
        completed = subprocess.run(
            ["/bin/bash", str(harness)],
            cwd=fixture,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        _assert_secrets_absent(completed, *secrets)

    argv_text = argv_log.read_text(encoding="utf-8")
    for secret in (
        "local-runtime-secret",
        "local-login-secret",
        "local-internal-secret",
        "local-admin-secret",
        "knowledge-runtime-secret",
        "knowledge-body-secret",
        "knowledge-header-secret",
    ):
        assert secret not in argv_text
    _assert_request_files_were_protected_and_removed(path_log)


def test_rotation_http_helper_hides_internal_token_and_body(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    _copy_common(fixture)
    source = (ROOT / "deploy/validate-secret-rotation.sh").read_text(encoding="utf-8")
    marker = "npcink_ai_cloud_require_internal_token"
    assert marker in source
    harness = fixture / "deploy/validate-secret-rotation-harness.sh"
    _write(
        harness,
        source.split(marker, 1)[0]
        + '''
http_request \
  "POST" "http://127.0.0.1/test" \
  '{"token":"rotation-body-secret"}' \
  "X-Npcink-Internal-Token: rotation-internal-secret"
''',
        executable=True,
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _install_fake_curl(fake_bin)
    argv_log = tmp_path / "curl-argv.jsonl"
    path_log = tmp_path / "request-paths.txt"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "ARGV_LOG": str(argv_log),
            "PATH_LOG": str(path_log),
        }
    )
    completed = subprocess.run(
        ["/bin/bash", str(harness)],
        cwd=fixture,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    _assert_secrets_absent(completed, "rotation-body-secret", "rotation-internal-secret")
    argv_text = argv_log.read_text(encoding="utf-8")
    assert "rotation-body-secret" not in argv_text
    assert "rotation-internal-secret" not in argv_text
    _assert_request_files_were_protected_and_removed(path_log)


def test_dev_portal_login_code_moves_from_protected_response_to_child_env(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    _copy_common(fixture)
    script = fixture / "deploy/dev/remote-portal-login-code-smoke.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "deploy/dev/remote-portal-login-code-smoke.sh", script)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _install_fake_curl(fake_bin)
    _install_fake_child_bash(fake_bin)
    argv_log = tmp_path / "curl-argv.jsonl"
    path_log = tmp_path / "request-paths.txt"
    child_log = tmp_path / "child.jsonl"
    login_code = "dev-login-code-secret"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "ARGV_LOG": str(argv_log),
            "PATH_LOG": str(path_log),
            "CHILD_LOG": str(child_log),
            "OBSERVED_ENV_KEY": "NPCINK_CLOUD_PORTAL_LOGIN_CODE",
            "EXPECTED_SECRET": login_code,
            "FAKE_CURL_BODY": json.dumps({"data": {"code": login_code}}),
            "NPCINK_CLOUD_SITE_ID": "site-dev-smoke",
            "NPCINK_CLOUD_MEMBER_EMAIL": "dev@example.test",
        }
    )
    completed = subprocess.run(
        ["/bin/bash", str(script)],
        cwd=fixture,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    _assert_secrets_absent(completed, login_code)
    assert login_code not in argv_log.read_text(encoding="utf-8")
    child_records = _read_json_lines(child_log)
    assert len(child_records) == 1
    assert child_records[0]["secret_present"] is True
    assert login_code not in json.dumps(child_records[0]["argv"])
    _assert_request_files_were_protected_and_removed(path_log)


def test_bundle_smoke_passes_runtime_secret_only_through_child_env(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    script = fixture / "scripts/cloud-deploy-bundle-smoke-flow.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "scripts/cloud-deploy-bundle-smoke-flow.sh", script)
    dist = fixture / "dist"
    dist.mkdir()
    (dist / "deploy-bundle.tgz").write_bytes(b"fixture")
    (dist / "deploy-bundle.tgz.sha256").write_text(
        f"{'a' * 64}  deploy-bundle.tgz\n", encoding="utf-8"
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _install_fake_child_bash(fake_bin)
    _write(
        fake_bin / "docker",
        '''#!/bin/sh
case "$*" in
  *"exec -T postgres18-proof"*) printf '%s\n' postgresql-18 ;;
esac
exit 0
''',
        executable=True,
    )
    _write(
        fake_bin / "tar",
        '''#!/usr/bin/env python3
import json
import sys
if "-xOf" in sys.argv:
    print(json.dumps({"source": {"revision": "abc123"}}))
''',
        executable=True,
    )
    _write(fake_bin / "git", "#!/bin/sh\nprintf '%s\\n' abc123\n", executable=True)
    child_log = tmp_path / "child.jsonl"
    runtime_secret = "bundle-runtime-secret"
    internal_secret = "bundle-internal-secret"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "CHILD_LOG": str(child_log),
            "EXPECTED_SECRET": runtime_secret,
            "OBSERVED_ENV_KEY": "NPCINK_CLOUD_SECRET",
            "NPCINK_CLOUD_SECRET": runtime_secret,
            "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN": internal_secret,
            "NPCINK_CLOUD_DEPLOY_SMOKE_SKIP_BUILD": "1",
        }
    )
    completed = subprocess.run(
        ["/bin/bash", str(script)],
        cwd=fixture,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    _assert_secrets_absent(completed, runtime_secret, internal_secret)
    records = _read_json_lines(child_log)
    assert records
    seed_records = [
        record
        for record in records
        if "remote-seed-runtime.sh" in " ".join(record["argv"])
    ]
    smoke_records = [record for record in records if "remote-smoke.sh" in " ".join(record["argv"])]
    assert len(seed_records) == 1 and seed_records[0]["secret_present"] is True
    assert len(smoke_records) == 1 and smoke_records[0]["secret_present"] is True
    for record in records:
        argv_text = json.dumps(record["argv"])
        assert runtime_secret not in argv_text
        assert internal_secret not in argv_text
    match = re.search(r"Extracting deploy bundle to (.+)", completed.stdout)
    assert match is not None
    assert not Path(match.group(1).strip()).exists()
