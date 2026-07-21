from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shlex
import stat
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "runtime-data-encryption-cutover.sh"

OFF_HOST_ACK = "I_ACKNOWLEDGE_THE_BACKUP_COPY_IS_OFF_HOST_AND_INDEPENDENT"
RESTORE_ACK = "I_ACKNOWLEDGE_ROLLBACK_RESTORES_DATABASE_RELEASE_ENV_AND_BOTH_OLD_ROOTS_TOGETHER"
CUTOVER_ACK = "I_AUTHORIZE_THE_P1_E06_PRODUCTION_CUTOVER"
RUNTIME_TARGET_SECRET = "cnJycnJycnJycnJycnJycnJycnJycnJycnJycnJycnI="  # gitleaks:allow
SERVICE_TARGET_SECRET = "c3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3M="  # gitleaks:allow
RUNTIME_TARGET_KEY_ID = "p1-e06-runtime-target"
SERVICE_TARGET_KEY_ID = "p1-e06-service-target"
RUNTIME_OLD_SECRET = "legacy-runtime-root-secret-0123456789-ABCDEFGHIJ"  # gitleaks:allow
SERVICE_OLD_SECRET = "legacy-service-root-secret-0123456789-ABCDEFGHIJ"  # gitleaks:allow
REPLACEMENT_RUNTIME_TARGET_SECRET = "dXV1dXV1dXV1dXV1dXV1dXV1dXV1dXV1dXV1dXV1dXU="  # gitleaks:allow
REPLACEMENT_SERVICE_TARGET_SECRET = "dnZ2dnZ2dnZ2dnZ2dnZ2dnZ2dnZ2dnZ2dnZ2dnZ2dnY="  # gitleaks:allow
REPLACEMENT_RUNTIME_OLD_SECRET = (
    "replacement-runtime-old-secret-0123456789-ABCDEFGHIJ"  # gitleaks:allow
)
REPLACEMENT_SERVICE_OLD_SECRET = (
    "replacement-service-old-secret-0123456789-ABCDEFGHIJ"  # gitleaks:allow
)
REPLACEMENT_RUNTIME_KEY_ID = "p1-e06-runtime-replacement-b"
REPLACEMENT_SERVICE_KEY_ID = "p1-e06-service-replacement-b"
PRODUCTION_RUNTIME_ROW_IDENTIFIERS = tuple(
    sorted(
        (
            "addon_connection_payload:wacs_8239a93ef5ae4eef91959346e2b5f382",
            "site_api_key:key_00bf64e1bbbe4eb68035b8f7627b54fa",  # gitleaks:allow
            "site_api_key:key_default",
            "site_api_key:key_release_cookie_20260711015023",
            "site_api_key:key_release_final_20260711013147",
            "site_api_key:key_release_local_20260711012801",
            "site_api_key:key_release_local_20260711012851",
            "site_api_key:key_release_smoke_20260708103911",
            "site_api_key:key_release_smoke_20260710163858",
            "site_api_key:key_release_smoke_20260710170234",
            "site_api_key:key_release_smoke_20260710170741",
            "site_api_key:key_release_smoke_20260710171254",
            "site_api_key:key_release_smoke_20260710171746",
            "site_api_key:key_release_smoke_20260710173411",
            "site_api_key:key_release_smoke_20260710182706",
            "site_api_key:key_release_smoke_20260711011455",
            "site_api_key:key_release_validation_1783676489",
            "site_api_key:key_release_validation_1783676542",
        )
    )
)
PRODUCTION_RUNTIME_IDENTITY_SHA256 = hashlib.sha256(
    json.dumps(
        PRODUCTION_RUNTIME_ROW_IDENTIFIERS,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()
PRODUCTION_SERVICE_ROW_IDENTIFIERS = tuple(
    sorted(
        (
            "provider_connection_secret:deepseek",
            "provider_connection_secret:image_pexels",
            "provider_connection_secret:image_pixabay",
            "provider_connection_secret:image_unsplash",
            "provider_connection_secret:openai_compatible",
            "provider_connection_secret:search_apify",
            "provider_connection_secret:search_tavily",
            "provider_connection_secret:search_zhihu",
            "service_setting_secret:payment_alipay:private_key",
            "service_setting_secret:payment_alipay:public_key",
            "service_setting_secret:portal_email:smtp_password",
            "service_setting_secret:portal_qq_login:client_secret",
        )
    )
)
PRODUCTION_SERVICE_IDENTITY_SHA256 = hashlib.sha256(
    json.dumps(
        PRODUCTION_SERVICE_ROW_IDENTIFIERS,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()
OLD_API_IMAGE_ID = "sha256:" + "a" * 64
NEW_API_IMAGE_ID = "sha256:" + "b" * 64
OLD_FRONTEND_IMAGE_ID = "sha256:" + "1" * 64
OLD_WORKER_IMAGE_ID = "sha256:" + "2" * 64
OLD_PROXY_IMAGE_ID = "sha256:" + "3" * 64
WRONG_RUNTIME_IMAGE_ID = "sha256:" + "9" * 64
OLD_POSTGRES_IMAGE_ID = "sha256:" + "c" * 64
NEW_POSTGRES_IMAGE_ID = "sha256:" + "d" * 64
OLD_REDIS_IMAGE_ID = "sha256:" + "e" * 64
NEW_REDIS_IMAGE_ID = "sha256:" + "f" * 64


@dataclass(frozen=True)
class CutoverFixture:
    root: Path
    remote: Path
    previous_release: Path
    staged_release: Path
    maintenance_env: Path
    backup: Path
    receipt: Path
    handoff: Path
    evidence: Path
    fake_bin: Path
    state: Path
    events: Path
    docker_calls: Path


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _write_executable(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _shell_path(path: Path) -> str:
    return shlex.quote(str(path))


def _make_fixture(tmp_path: Path) -> CutoverFixture:
    fixture_root = tmp_path / "fixture"
    remote = fixture_root / "remote"
    previous_release = remote / "release-old"
    staged_release = remote / "release-new"
    previous_deploy = previous_release / "deploy"
    staged_deploy = staged_release / "deploy"
    staged_scripts = staged_release / "scripts"
    fake_bin = fixture_root / "fake-bin"
    state_dir = fixture_root / "state"
    private_tmp = fixture_root / "tmp"
    backup_dir = fixture_root / "backups"
    receipt_dir = fixture_root / "receipts"
    previous_state = remote / ".release-state" / "release-old"
    for directory in (
        previous_deploy,
        staged_deploy,
        staged_scripts,
        fake_bin,
        state_dir,
        private_tmp,
        backup_dir,
        receipt_dir,
        previous_state,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    (remote / ".release-state").chmod(0o700)
    previous_state.chmod(0o700)
    private_tmp.chmod(0o700)
    (state_dir / "host-python").write_text(
        str(Path(sys.executable).resolve()) + "\n",
        encoding="utf-8",
    )
    (state_dir / "fail-at").write_text("", encoding="utf-8")
    (state_dir / "production-service-row-identifiers.json").write_text(
        json.dumps(
            PRODUCTION_SERVICE_ROW_IDENTIFIERS,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    (state_dir / "production-runtime-row-identifiers.json").write_text(
        json.dumps(
            PRODUCTION_RUNTIME_ROW_IDENTIFIERS,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    (remote / "current").symlink_to(previous_release)
    for compose_file in (
        previous_release / "docker-compose.runtime.yml",
        staged_release / "docker-compose.runtime.yml",
    ):
        compose_file.write_text("services: {}\n", encoding="utf-8")

    certificate_path = Path("/etc/letsencrypt/live/cloud.example.invalid/fullchain.pem")
    private_key_path = Path("/etc/letsencrypt/live/cloud.example.invalid/privkey.pem")
    certificate_real_path = Path("/etc/letsencrypt/archive/cloud.example.invalid/fullchain1.pem")
    private_key_real_path = Path("/etc/letsencrypt/archive/cloud.example.invalid/privkey1.pem")
    certbot_path = fake_bin / "certbot"
    _write_executable(
        certbot_path,
        """#!/usr/bin/env bash
set -Eeuo pipefail
exit 0
""",
    )
    certbot_real_path = str(certbot_path.resolve())
    renewal_exec_start_sha256 = hashlib.sha256(
        json.dumps(
            {
                "argv": [certbot_real_path, "renew", "--quiet"],
                "ignore_errors": False,
                "path": certbot_real_path,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    renewal_hook_dir = fixture_root / "etc" / "letsencrypt" / "renewal-hooks" / "deploy"
    renewal_hook_dir.mkdir(parents=True, mode=0o700)
    renewal_hook_path = renewal_hook_dir / "reload-nginx"
    _write_executable(
        renewal_hook_path,
        """#!/usr/bin/env bash
set -Eeuo pipefail
nginx -t
systemctl reload nginx
""",
    )
    renewal_hook_sha256 = hashlib.sha256(renewal_hook_path.read_bytes()).hexdigest()
    nginx_tls_binding_sha256 = hashlib.sha256(
        json.dumps(
            {
                "domain": "cloud.example.invalid",
                "ssl_certificate": str(certificate_path),
                "ssl_certificate_key": str(private_key_path),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    certificate_evidence = previous_state / "certificate-renewal-readiness.json"
    generated_at_epoch = int(time.time())
    generated_at = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(generated_at_epoch),
    )
    certificate_evidence.write_text(
        json.dumps(
            {
                "contract": "npcink_cloud_certificate_renewal_readiness.v1",
                "status": "passed",
                "domain": "cloud.example.invalid",
                "certificate_path": str(certificate_path),
                "certificate_real_path": str(certificate_real_path),
                "private_key_path": str(private_key_path),
                "private_key_real_path": str(private_key_real_path),
                "certbot_lineage_name": "cloud.example.invalid",
                "certificate_leaf_sha256_fingerprint": "a" * 64,
                "certificate_private_key_match": True,
                "renewal_owner": "certbot",
                "timer": "certbot-renew.timer",
                "timer_enabled": True,
                "timer_active": True,
                "timer_next_run": "Tue 2026-07-21 00:00:00 CST",
                "renewal_service": "certbot-renew.service",
                "certbot_real_path": certbot_real_path,
                "renewal_exec_start_sha256": renewal_exec_start_sha256,
                "renewal_dry_run_passed": True,
                "deploy_hook_path": str(renewal_hook_path.resolve()),
                "deploy_hook_sha256": renewal_hook_sha256,
                "deploy_hook_execution_passed": True,
                "nginx_config_valid": True,
                "nginx_ssl_certificate_path": str(certificate_path),
                "nginx_ssl_certificate_key_path": str(private_key_path),
                "nginx_tls_binding_sha256": nginx_tls_binding_sha256,
                "nginx_references_certbot_lineage": True,
                "nginx_reload_passed": True,
                "nginx_active": True,
                "certificate_domain_match": True,
                "certificate_validity_floor_passed": True,
                "served_certificate_domain_match": True,
                "served_certificate_validity_floor_passed": True,
                "served_leaf_matches_certificate": True,
                "minimum_validity_days": 30,
                "generated_at": generated_at,
                "generated_at_epoch": generated_at_epoch,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    certificate_evidence.chmod(0o600)

    current_env = previous_state / "env.deploy"
    current_env.write_text(
        "\n".join(
            (
                "NPCINK_CLOUD_COMPOSE_PROJECT_NAME=npcink-ai-cloud",
                "NPCINK_CLOUD_EXTERNAL_EDGE_READY=true",
                "NPCINK_CLOUD_BASE_URL=https://cloud.example.invalid",
                "NPCINK_CLOUD_DOMAIN_NAME=cloud.example.invalid",
                f"NPCINK_CLOUD_CERTIFICATE_RENEWAL_CERT_PATH={certificate_path}",
                f"NPCINK_CLOUD_CERTIFICATE_RENEWAL_EVIDENCE_PATH={certificate_evidence}",
                "NPCINK_CLOUD_CERTIFICATE_RENEWAL_TIMER=certbot-renew.timer",
                f"NPCINK_CLOUD_CERTIFICATE_RENEWAL_HOOK_PATH={renewal_hook_path}",
                "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN=test-internal-token",
                "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET=stale-legacy-root-secret-0123456789",  # noqa: E501  # gitleaks:allow
                "NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET=stale-service-root-secret-0123456789",  # noqa: E501  # gitleaks:allow
            )
        )
        + "\n",
        encoding="utf-8",
    )
    current_env.chmod(0o600)

    maintenance_env = fixture_root / "runtime-data-reencrypt.env"
    maintenance_env.write_text(
        "\n".join(
            (
                f"NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET={RUNTIME_TARGET_SECRET}",
                f"NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID={RUNTIME_TARGET_KEY_ID}",
                f"NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET={RUNTIME_OLD_SECRET}",
                f"NPCINK_CLOUD_SERVICE_SETTINGS_SECRET={SERVICE_TARGET_SECRET}",
                f"NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID={SERVICE_TARGET_KEY_ID}",
                f"NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET={SERVICE_OLD_SECRET}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    maintenance_env.chmod(0o600)

    (staged_deploy / "common.sh").write_text(
        (ROOT / "deploy" / "common.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    certificate_readiness = staged_deploy / "certificate-renewal-readiness.sh"
    certificate_readiness.write_text(
        (ROOT / "deploy" / "certificate-renewal-readiness.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    certificate_readiness.chmod(0o755)
    fixture_root_shell = _shell_path(fixture_root)
    _write_executable(
        staged_deploy / "remote-load-and-up.sh",
        f"""
        #!/usr/bin/env bash
        set -Eeuo pipefail
        FIXTURE_ROOT={fixture_root_shell}
        EXPECTED_HOST_PYTHON="$(tr -d '\n' <"${{FIXTURE_ROOT}}/state/host-python")"
        [ "${{NPCINK_CLOUD_RELEASE_TOOL_PYTHON:-}}" = "${{EXPECTED_HOST_PYTHON}}" ] || {{
            printf 'failure:release-helper-host-python\n' >>"${{FIXTURE_ROOT}}/events.log"
            exit 92
        }}
        printf 'helper:%s\n' "${{NPCINK_CLOUD_LOAD_MODE:-missing}}" >>"${{FIXTURE_ROOT}}/events.log"
        case "${{NPCINK_CLOUD_LOAD_MODE:-}}" in
            prepare-only)
                {{
                    printf '%s\t%s\t%s\n' \
                        'npcink-ai-cloud-api:prod' \
                        'npcink-ai-cloud-api:rollback-p1e06' \
                        '{OLD_API_IMAGE_ID}'
                    printf '%s\t%s\t%s\n' \
                        'npcink-ai-cloud-frontend:prod' \
                        'npcink-ai-cloud-frontend:rollback-p1e06' \
                        '{OLD_FRONTEND_IMAGE_ID}'
                    printf '%s\t%s\t%s\n' \
                        'npcink-ai-cloud-worker:prod' \
                        'npcink-ai-cloud-worker:rollback-p1e06' \
                        '{OLD_WORKER_IMAGE_ID}'
                    printf '%s\t%s\t%s\n' \
                        'npcink-ai-cloud-external-nginx:prod' \
                        'npcink-ai-cloud-external-nginx:rollback-p1e06' \
                        '{OLD_PROXY_IMAGE_ID}'
                    printf '%s\t%s\t%s\n' \
                        'npcink-ai-cloud-postgres:prod' \
                        'npcink-ai-cloud-postgres:rollback-p1e06' \
                        '{OLD_POSTGRES_IMAGE_ID}'
                    printf '%s\t%s\t%s\n' \
                        'npcink-ai-cloud-external-redis:prod' \
                        'npcink-ai-cloud-external-redis:rollback-p1e06' \
                        '{OLD_REDIS_IMAGE_ID}'
                }} >"${{NPCINK_CLOUD_ROLLBACK_IMAGE_MAP}}"
                chmod 0600 "${{NPCINK_CLOUD_ROLLBACK_IMAGE_MAP}}"
                : >"${{FIXTURE_ROOT}}/state/image-prepared"
                ;;
            data-only)
                env \
                    -u POSTGRES_USER -u POSTGRES_DB -u COMPOSE_FILE \
                    -u COMPOSE_PROFILES -u NPCINK_CLOUD_RELEASE_TOOL_PYTHON \
                    docker compose \
                    --env-file "${{NPCINK_CLOUD_ENV_FILE}}" \
                    -f "${{NPCINK_CLOUD_COMPOSE_FILE}}" \
                    up -d --pull never --no-build \
                    --no-deps --force-recreate postgres redis
                ;;
            api-only|workers-only|traffic-only)
                ;;
            *)
                exit 91
                ;;
        esac
        """,
    )
    _write_executable(
        staged_deploy / "remote-operational-ready.sh",
        f"""
        #!/usr/bin/env bash
        set -Eeuo pipefail
        EXPECTED_HOST_PYTHON="$(tr -d '\n' <{fixture_root_shell}/state/host-python)"
        [ "${{NPCINK_CLOUD_RELEASE_TOOL_PYTHON:-}}" = "${{EXPECTED_HOST_PYTHON}}" ] || exit 92
        printf 'helper:operational-ready\n' >>{fixture_root_shell}/events.log
        """,
    )
    _write_executable(
        staged_deploy / "remote-baseline-status.sh",
        f"""
        #!/usr/bin/env bash
        set -Eeuo pipefail
        EXPECTED_HOST_PYTHON="$(tr -d '\n' <{fixture_root_shell}/state/host-python)"
        [ "${{NPCINK_CLOUD_RELEASE_TOOL_PYTHON:-}}" = "${{EXPECTED_HOST_PYTHON}}" ] || exit 92
        printf 'helper:baseline-status\n' >>{fixture_root_shell}/events.log
        """,
    )
    _write_executable(
        staged_deploy / "verify-release-bundle.sh",
        """
        #!/usr/bin/env bash
        set -Eeuo pipefail
        exit 0
        """,
    )
    _write_executable(
        staged_scripts / "verify-release-bundle-manifest.py",
        f"""
        #!/usr/bin/env python3
        from pathlib import Path
        import sys

        if sys.version_info < (3, 11):
            raise SystemExit(36)
        if len(sys.argv) != 6 or sys.argv[1] != "loaded-role-daemon-id":
            raise SystemExit(2)
        if sys.argv[2] != "--root" or sys.argv[4] != "--role":
            raise SystemExit(2)
        roles = {{
            "api": {NEW_API_IMAGE_ID!r},
            "postgres": {NEW_POSTGRES_IMAGE_ID!r},
            "external_redis": {NEW_REDIS_IMAGE_ID!r},
        }}
        role = sys.argv[5]
        if role not in roles:
            raise SystemExit(3)
        with Path({str(fixture_root / "events.log")!r}).open("a", encoding="utf-8") as handle:
            handle.write(f"manifest:loaded-role-daemon-id:{{role}}\\n")
        print(roles[role])
        """,
    )

    _write_executable(
        fake_bin / "id",
        """
        #!/usr/bin/env bash
        set -Eeuo pipefail
        [ "${1:-}" = "-u" ] || exit 2
        printf '0\n'
        """,
    )
    _write_executable(
        fake_bin / "python3",
        """
        #!/usr/bin/env bash
        set -Eeuo pipefail
        FAKE_BIN="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
        FIXTURE_ROOT="$(dirname "${FAKE_BIN}")"
        printf 'failure:default-python3-used\n' >>"${FIXTURE_ROOT}/events.log"
        printf 'Python 3.6.15 (intentionally unsupported fake)\n' >&2
        exit 36
        """,
    )
    _write_executable(
        fake_bin / "stat",
        """
        #!/usr/bin/env bash
        set -Eeuo pipefail
        FAKE_BIN="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
        FIXTURE_ROOT="$(dirname "${FAKE_BIN}")"
        HOST_PYTHON="$(tr -d '\n' <"${FIXTURE_ROOT}/state/host-python")"
        [ "${1:-}" = "-c" ] || exit 2
        format="${2:-}"
        path="${3:-}"
        [ "${path}" != "--" ] || path="${4:-}"
        case "${format}" in
            %a)
                case "${path}" in
                    /etc/letsencrypt/archive/cloud.example.invalid/fullchain1.pem)
                        printf '644\n'
                        exit 0
                        ;;
                    /etc/letsencrypt/archive/cloud.example.invalid/privkey1.pem)
                        printf '600\n'
                        exit 0
                        ;;
                    /etc/letsencrypt|/etc/letsencrypt/live|/etc/letsencrypt/live/cloud.example.invalid|/etc/letsencrypt/archive|/etc/letsencrypt/archive/cloud.example.invalid)
                        printf '755\n'
                        exit 0
                        ;;
                esac
                "${HOST_PYTHON}" - "${path}" "${FIXTURE_ROOT}" <<'PY'
import os
import stat
import sys

metadata = os.stat(sys.argv[1])
fixture_root = os.path.realpath(sys.argv[2])
path = os.path.realpath(sys.argv[1])
if stat.S_ISDIR(metadata.st_mode) and os.path.commonpath((path, fixture_root)) != fixture_root:
    # The executable fixture simulates the root-owned production hierarchy even
    # when pytest itself stores the fixture below Docker's world-writable /tmp.
    print("755")
else:
    print(oct(stat.S_IMODE(metadata.st_mode))[2:])
PY
                ;;
            %u)
                printf '0\n'
                ;;
            %F)
                case "${path}" in
                    /etc/letsencrypt/live/cloud.example.invalid/fullchain.pem|/etc/letsencrypt/live/cloud.example.invalid/privkey.pem)
                        printf 'symbolic link\n'
                        ;;
                    /etc/letsencrypt/archive/cloud.example.invalid/fullchain1.pem|/etc/letsencrypt/archive/cloud.example.invalid/privkey1.pem)
                        printf 'regular file\n'
                        ;;
                    /etc/letsencrypt|/etc/letsencrypt/live|/etc/letsencrypt/live/cloud.example.invalid|/etc/letsencrypt/archive|/etc/letsencrypt/archive/cloud.example.invalid)
                        printf 'directory\n'
                        ;;
                    *)
                        [ -d "${path}" ] && printf 'directory\n' || printf 'regular file\n'
                        ;;
                esac
                ;;
            *)
                exit 2
                ;;
        esac
        """,
    )
    _write_executable(
        fake_bin / "readlink",
        """
        #!/usr/bin/env bash
        set -Eeuo pipefail
        FAKE_BIN="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
        FIXTURE_ROOT="$(dirname "${FAKE_BIN}")"
        [ "${1:-}" = "-f" ] || exit 2
        shift
        [ "${1:-}" != "--" ] || shift
        path="${1:-}"
        case "${path}" in
            /etc/letsencrypt/live/cloud.example.invalid/fullchain.pem)
                printf '/etc/letsencrypt/archive/cloud.example.invalid/fullchain1.pem\n'
                exit 0
                ;;
            /etc/letsencrypt/live/cloud.example.invalid/privkey.pem)
                printf '/etc/letsencrypt/archive/cloud.example.invalid/privkey1.pem\n'
                exit 0
                ;;
        esac
        if [ "${path}" = "${FIXTURE_ROOT}/remote/current" ]; then
            [ -d "${FIXTURE_ROOT}/remote/.deploy-lock" ] || {
                printf 'lock:current-read-before-lock\n' >>"${FIXTURE_ROOT}/events.log"
                exit 93
            }
            printf 'lock:current-read-after-lock\n' >>"${FIXTURE_ROOT}/events.log"
        fi
        HOST_PYTHON="$(tr -d '\n' <"${FIXTURE_ROOT}/state/host-python")"
        "${HOST_PYTHON}" - "${path}" <<'PY'
import os
import sys

print(os.path.realpath(sys.argv[1]))
PY
        """,
    )
    _write_executable(
        fake_bin / "mv",
        """
        #!/usr/bin/env bash
        set -Eeuo pipefail
        FAKE_BIN="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
        FIXTURE_ROOT="$(dirname "${FAKE_BIN}")"
        no_clobber=0
        case "${1:-}" in
            -Tn)
                no_clobber=1
                shift
                ;;
            -Tf|-f)
                shift
                ;;
        esac
        [ "$#" -eq 2 ] || exit 2
        source_path="$1"
        destination_path="$2"
        case "${destination_path}" in
            */cutover-result.json)
                [ -d "${FIXTURE_ROOT}/remote/.deploy-lock" ] || exit 94
                fail_at="$(tr -d '\n' <"${FIXTURE_ROOT}/state/fail-at" 2>/dev/null || true)"
                if [ "${fail_at}" = "terminal_publish" ]; then
                    printf 'failure:terminal-publish\n' >>"${FIXTURE_ROOT}/events.log"
                    exit 95
                fi
                printf 'terminal:private-result-published-under-lock\n' \
                    >>"${FIXTURE_ROOT}/events.log"
                ;;
            */.release-state/p1-e06-activation.json)
                [ -d "${FIXTURE_ROOT}/remote/.deploy-lock" ] || exit 96
                fail_at="$(tr -d '\n' <"${FIXTURE_ROOT}/state/fail-at" 2>/dev/null || true)"
                if [ "${fail_at}" = "global_receipt_publish" ] || \
                    [ "${fail_at}" = "result_cleanup_failure" ] || \
                    [ "${fail_at}" = "result_quarantine_failure" ]; then
                    printf 'failure:global-receipt-publish\n' \
                        >>"${FIXTURE_ROOT}/events.log"
                    exit 97
                fi
                printf 'terminal:global-receipt-published-under-lock\n' \
                    >>"${FIXTURE_ROOT}/events.log"
                ;;
            */.conflicting-cutover-result.*.json)
                fail_at="$(tr -d '\n' <"${FIXTURE_ROOT}/state/fail-at" 2>/dev/null || true)"
                if [ "${fail_at}" = "result_quarantine_failure" ]; then
                    printf 'failure:result-quarantine\n' >>"${FIXTURE_ROOT}/events.log"
                    exit 98
                fi
                printf 'terminal:result-quarantined\n' >>"${FIXTURE_ROOT}/events.log"
                ;;
            */off-host-handoff.json)
                printf 'handoff:marker-published\n' >>"${FIXTURE_ROOT}/events.log"
                ;;
        esac
        HOST_PYTHON="$(tr -d '\n' <"${FIXTURE_ROOT}/state/host-python")"
        "${HOST_PYTHON}" - "${source_path}" "${destination_path}" "${no_clobber}" <<'PY'
import os
import sys

source, destination, no_clobber = sys.argv[1:]
if no_clobber == "1" and os.path.lexists(destination):
    raise SystemExit(1)
if no_clobber == "1":
    os.rename(source, destination)
else:
    os.replace(source, destination)
PY
        """,
    )
    _write_executable(
        fake_bin / "rm",
        """
        #!/usr/bin/env bash
        set -Eeuo pipefail
        FAKE_BIN="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
        FIXTURE_ROOT="$(dirname "${FAKE_BIN}")"
        fail_at="$(tr -d '\n' <"${FIXTURE_ROOT}/state/fail-at" 2>/dev/null || true)"
        if [ "${fail_at}" = "result_cleanup_failure" ] || \
            [ "${fail_at}" = "result_quarantine_failure" ]; then
            for path in "$@"; do
                case "${path}" in
                    */cutover-result.json|*/cutover-result.json.tmp.*)
                        printf 'failure:result-cleanup\n' >>"${FIXTURE_ROOT}/events.log"
                        exit 98
                        ;;
                esac
            done
        fi
        exec /bin/rm "$@"
        """,
    )
    _write_executable(
        fake_bin / "rmdir",
        """
        #!/usr/bin/env bash
        set -Eeuo pipefail
        FAKE_BIN="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
        FIXTURE_ROOT="$(dirname "${FAKE_BIN}")"
        [ "${1:-}" != "--" ] || shift
        [ "$#" -eq 1 ] || exit 2
        fail_at="$(tr -d '\n' <"${FIXTURE_ROOT}/state/fail-at" 2>/dev/null || true)"
        is_deploy_lock=0
        if [ "$1" = "${FIXTURE_ROOT}/remote/.deploy-lock" ]; then
            is_deploy_lock=1
            [ -f "${FIXTURE_ROOT}/remote/.release-state/p1-e06-activation.json" ] || {
                printf 'failure:unlock-before-global-receipt\n' \
                    >>"${FIXTURE_ROOT}/events.log"
                exit 97
            }
        fi
        if [ "${fail_at}" = "commit_unlock" ] && \
            [ "$1" = "${FIXTURE_ROOT}/remote/.deploy-lock" ]; then
            printf 'failure:commit-unlock\n' >>"${FIXTURE_ROOT}/events.log"
            exit 96
        fi
        HOST_PYTHON="$(tr -d '\n' <"${FIXTURE_ROOT}/state/host-python")"
        "${HOST_PYTHON}" - "$1" <<'PY'
import os
import sys

os.rmdir(sys.argv[1])
PY
        if [ "${is_deploy_lock}" = "1" ]; then
            printf 'terminal:lock-released-after-global-receipt\n' \
                >>"${FIXTURE_ROOT}/events.log"
        fi
        """,
    )
    _write_executable(
        fake_bin / "systemctl",
        """
        #!/usr/bin/env bash
        set -Eeuo pipefail
        FAKE_BIN="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
        FIXTURE_ROOT="$(dirname "${FAKE_BIN}")"
        case "${1:-}:${2:-}:${3:-}:${4:-}" in
            is-enabled:--quiet:certbot-renew.timer:|is-active:--quiet:certbot-renew.timer:|is-active:--quiet:nginx:)
                exit 0
                ;;
            show:certbot-renew.timer:--property=NextElapseUSecRealtime:--value)
                printf 'Tue 2026-07-21 00:00:00 CST\n'
                ;;
            show:certbot-renew.timer:--property=Unit:--value)
                printf 'certbot-renew.service\n'
                ;;
            show:certbot-renew.service:--property=ExecStart:--value)
                printf '{ path=%s ; argv[]=%s renew --quiet ; %s%s\n' \
                    "${FIXTURE_ROOT}/fake-bin/certbot" \
                    "${FIXTURE_ROOT}/fake-bin/certbot" \
                    'ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; ' \
                    'pid=0 ; code=(null) ; status=0/0 }'
                ;;
            show:nginx:--property=ExecReload:--value)
                if [ -s "${FIXTURE_ROOT}/state/nginx-reloads" ]; then
                    cat "${FIXTURE_ROOT}/state/nginx-reloads"
                else
                    printf 'never\n'
                fi
                ;;
            reload:nginx::)
                printf 'reload\n' >>"${FIXTURE_ROOT}/state/nginx-reloads"
                ;;
            *)
                exit 2
                ;;
        esac
        """,
    )
    _write_executable(
        fake_bin / "openssl",
        """
        #!/usr/bin/env bash
        set -Eeuo pipefail
        case "${1:-}" in
            s_client)
                [[ " $* " = *" -connect 127.0.0.1:443 "* ]]
                [[ " $* " = *" -servername cloud.example.invalid "* ]]
                printf 'fixture served leaf\n'
                ;;
            x509)
                input_path=""
                output_path=""
                previous=""
                for token in "$@"; do
                    [ "${previous}" != "-in" ] || input_path="${token}"
                    [ "${previous}" != "-out" ] || output_path="${token}"
                    previous="${token}"
                done
                if [[ " $* " = *" -outform PEM "* ]]; then
                    cat >/dev/null
                    printf 'fixture served leaf\n' >"${output_path}"
                elif [[ " $* " = *" -pubkey "* ]]; then
                    printf 'fixture-public-key\n'
                elif [[ " $* " = *" -checkhost cloud.example.invalid "* ]]; then
                    exit 0
                elif [[ " $* " = *" -checkend 2592000 "* ]]; then
                    exit 0
                elif [[ " $* " = *" -fingerprint -sha256 "* ]]; then
                    [ -n "${input_path}" ]
                    printf 'SHA256 Fingerprint=%s\n' \
                        'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
                else
                    exit 2
                fi
                ;;
            pkey)
                if [[ " $* " = *" -check "* ]]; then
                    exit 0
                elif [[ " $* " = *" -pubin "* ]]; then
                    cat
                elif [[ " $* " = *" -pubout "* ]]; then
                    printf 'fixture-public-key\n'
                else
                    exit 2
                fi
                ;;
            *) exit 2 ;;
        esac
        """,
    )
    _write_executable(
        fake_bin / "nginx",
        """
        #!/usr/bin/env bash
        set -Eeuo pipefail
        FAKE_BIN="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
        FIXTURE_ROOT="$(dirname "${FAKE_BIN}")"
        case "${1:-}" in
            -t)
                printf 'edge:nginx-t\n' >>"${FIXTURE_ROOT}/events.log"
                ;;
            -T)
                cat <<'EOF'
server {
    listen 443 ssl;
    server_name cloud.example.invalid;
    ssl_certificate /etc/letsencrypt/live/cloud.example.invalid/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/cloud.example.invalid/privkey.pem;
}
EOF
                ;;
            *) exit 2 ;;
        esac
        """,
    )
    _write_executable(
        fake_bin / "curl",
        """
        #!/usr/bin/env bash
        set -Eeuo pipefail
        FAKE_BIN="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
        FIXTURE_ROOT="$(dirname "${FAKE_BIN}")"
        joined=" $* "
        [[ "${joined}" = *" --resolve cloud.example.invalid:443:127.0.0.1 "* ]]
        [[ "${joined}" = *" https://cloud.example.invalid/health/live "* ]]
        printf 'edge:loopback-https-health\n' >>"${FIXTURE_ROOT}/events.log"
        """,
    )
    _write_executable(
        fake_bin / "sleep",
        """
        #!/usr/bin/env bash
        set -Eeuo pipefail
        FAKE_BIN="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
        FIXTURE_ROOT="$(dirname "${FAKE_BIN}")"
        HOST_PYTHON="$(tr -d '\n' <"${FIXTURE_ROOT}/state/host-python")"
        "${HOST_PYTHON}" - <<'PY'
import time

time.sleep(0.01)
PY
        """,
    )
    _write_executable(fake_bin / "docker", _fake_docker_source())

    evidence = remote / ".release-state" / "release-new" / "p1-e06-runtime-data-cutover"
    return CutoverFixture(
        root=fixture_root,
        remote=remote,
        previous_release=previous_release,
        staged_release=staged_release,
        maintenance_env=maintenance_env,
        backup=backup_dir / "p1-e06.dump",
        receipt=receipt_dir / "p1-e06-off-host-receipt.json",
        handoff=evidence / "off-host-handoff.json",
        evidence=evidence,
        fake_bin=fake_bin,
        state=state_dir,
        events=fixture_root / "events.log",
        docker_calls=fixture_root / "docker-calls.log",
    )


def _fake_docker_source() -> str:
    return r"""
    #!/usr/bin/env bash
    set -Eeuo pipefail

    FAKE_BIN="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
    FIXTURE_ROOT="$(dirname "${FAKE_BIN}")"
    STATE="${FIXTURE_ROOT}/state"
    EVENTS="${FIXTURE_ROOT}/events.log"
    CALLS="${FIXTURE_ROOT}/docker-calls.log"
    HOST_PYTHON="$(tr -d '\n' <"${STATE}/host-python")"
    OLD_API_IMAGE_ID="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    NEW_API_IMAGE_ID="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    OLD_FRONTEND_IMAGE_ID="sha256:1111111111111111111111111111111111111111111111111111111111111111"
    OLD_WORKER_IMAGE_ID="sha256:2222222222222222222222222222222222222222222222222222222222222222"
    OLD_PROXY_IMAGE_ID="sha256:3333333333333333333333333333333333333333333333333333333333333333"
    WRONG_RUNTIME_IMAGE_ID="sha256:9999999999999999999999999999999999999999999999999999999999999999"
    OLD_POSTGRES_IMAGE_ID="sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    NEW_POSTGRES_IMAGE_ID="sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
    OLD_REDIS_IMAGE_ID="sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    NEW_REDIS_IMAGE_ID="sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    mkdir -p "${STATE}"

    {
        printf 'docker'
        printf '|%s' "$@"
        printf '\n'
    } >>"${CALLS}"

    joined=" $* "
    for secret_value in \
        "${NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET:-}" \
        "${NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET:-}" \
        "${NPCINK_CLOUD_SERVICE_SETTINGS_SECRET:-}" \
        "${NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET:-}" \
        "${NPCINK_CLOUD_DATABASE_URL:-}"; do
        if [ -n "${secret_value}" ] && [[ "${joined}" = *"${secret_value}"* ]]; then
            exit 97
        fi
    done

    has_env_name() {
        local needle="$1"
        shift
        local previous=""
        local token=""
        for token in "$@"; do
            if [ "${previous}" = "-e" ] && [ "${token}" = "${needle}" ]; then
                return 0
            fi
            previous="${token}"
        done
        return 1
    }

    command_name="${1:-}"
    case "${command_name}" in
        context)
            printf 'unix:///tmp/p1-e06-fake-docker.sock\n'
            exit 0
            ;;
        info)
            exit 0
            ;;
        ps)
            service=""
            ancestor=""
            for token in "$@"; do
                case "${token}" in
                    label=com.docker.compose.service=*) service="${token##*=}" ;;
                    ancestor=*) ancestor="${token##*=}" ;;
                esac
            done
            if [ -n "${ancestor}" ]; then
                if [ -e "${STATE}/writers-reappeared" ] && \
                    { [ "${ancestor}" = "${OLD_API_IMAGE_ID}" ] || \
                        [ "${ancestor}" = "${NEW_API_IMAGE_ID}" ]; }; then
                    printf 'id-api\n'
                fi
                exit 0
            fi
            if [ "${service}" = "caddy" ]; then
                [[ "${joined}" != *' -aq '* ]] || printf 'stopped-caddy-id\n'
                exit 0
            fi
            if [ -n "${service}" ] && \
                { [ ! -e "${STATE}/writers-stopped" ] || \
                    [ -e "${STATE}/writers-reappeared" ]; }; then
                printf 'id-%s\n' "${service}"
            fi
            exit 0
            ;;
        inspect)
            if [[ "${joined}" = *'.Config.Labels'* ]]; then
                printf 'npcink-ai-cloud\n'
            elif [[ "${joined}" = *'.Config.Image'* ]]; then
                case "${!#}" in
                    id-api) printf '%s\n' 'npcink-ai-cloud-api:prod' ;;
                    id-frontend) printf '%s\n' 'npcink-ai-cloud-frontend:prod' ;;
                    id-proxy) printf '%s\n' 'npcink-ai-cloud-external-nginx:prod' ;;
                    id-worker|id-callback-worker|id-ops-worker)
                        printf '%s\n' 'npcink-ai-cloud-worker:prod' ;;
                    *) exit 78 ;;
                esac
            elif [[ "${joined}" = *'.Image'* ]]; then
                container_id="${!#}"
                one_off_container="$(
                    tr -d '\n' 2>/dev/null <"${STATE}/api-oneoff-container" || true
                )"
                fail_at="$(tr -d '\n' <"${STATE}/fail-at" 2>/dev/null || true)"
                case "${container_id}" in
                    "${one_off_container}")
                        [ -n "${one_off_container}" ] || exit 2
                        if [ "${fail_at}" = "oneoff_image_mismatch" ]; then
                            printf 'oneoff:image-mismatch\n' >>"${EVENTS}"
                            printf '%s\n' "${OLD_API_IMAGE_ID}"
                        else
                            printf '%s\n' "${NEW_API_IMAGE_ID}"
                        fi ;;
                    id-postgres-old|id-postgres-restored)
                        printf '%s\n' "${OLD_POSTGRES_IMAGE_ID}" ;;
                    id-redis-old|id-redis-restored)
                        printf '%s\n' "${OLD_REDIS_IMAGE_ID}" ;;
                    id-postgres-new)
                        printf '%s\n' "${NEW_POSTGRES_IMAGE_ID}" ;;
                    id-redis-new)
                        printf '%s\n' "${NEW_REDIS_IMAGE_ID}" ;;
                    id-frontend)
                        printf '%s\n' "${OLD_FRONTEND_IMAGE_ID}" ;;
                    id-proxy)
                        printf '%s\n' "${OLD_PROXY_IMAGE_ID}" ;;
                    id-worker|id-ops-worker)
                        printf '%s\n' "${OLD_WORKER_IMAGE_ID}" ;;
                    id-callback-worker)
                        if [ "${fail_at}" = "previous_runtime_image_mismatch" ]; then
                            printf 'recovery:runtime-image-mismatch\n' >>"${EVENTS}"
                            printf '%s\n' "${WRONG_RUNTIME_IMAGE_ID}"
                        else
                            printf '%s\n' "${OLD_WORKER_IMAGE_ID}"
                        fi ;;
                    *)
                        printf '%s\n' "${OLD_API_IMAGE_ID}" ;;
                esac
			elif [[ "${joined}" = *'{{.State.Status}} {{.RestartCount}}'* ]]; then
				one_off_container="$(
					tr -d '\n' 2>/dev/null <"${STATE}/api-oneoff-container" || true
				)"
				[ -n "${one_off_container}" ] && [ "${!#}" = "${one_off_container}" ] || exit 2
				if [ -e "${STATE}/api-oneoff-started" ]; then
					printf 'running 0\n'
				else
					printf 'created 0\n'
					printf 'oneoff:candidate-created-proved\n' >>"${EVENTS}"
				fi
            elif [[ "${joined}" = *'.State.Health'* ]]; then
                printf 'true false 0 healthy\n'
                printf 'recovery:dependency-health-proved\n' >>"${EVENTS}"
            elif [[ "${joined}" = *'.State.Running'* ]]; then
				if [[ "${joined}" = *'.State.Restarting'* ]]; then
					printf 'true false 0\n'
				else
					one_off_container="$(
						tr -d '\n' 2>/dev/null <"${STATE}/api-oneoff-container" || true
					)"
					[ -n "${one_off_container}" ] && [ "${!#}" = "${one_off_container}" ] || exit 2
					[ -e "${STATE}/api-oneoff-started" ] && printf 'true\n' || printf 'false\n'
				fi
            fi
            exit 0
            ;;
        image)
            subcommand="${2:-}"
            reference="${!#}"
            case "${subcommand}" in
                inspect)
                    if [[ "${reference}" = *':rollback-p1e06' ]] && \
                        [ -e "${STATE}/rollback-removed" ]; then
                        exit 1
                    fi
                    if [[ "${joined}" = *'{{.Id}}'* ]]; then
                        restored=0
                        [ ! -e "${STATE}/image-restored" ] || restored=1
                        case "${reference}" in
                            npcink-ai-cloud-api:prod)
                                fail_at="$(
                                    tr -d '\n' <"${STATE}/fail-at" 2>/dev/null || true
                                )"
                                if [ "${fail_at}" = "oneoff_pre_tag_drift" ] && \
                                    [ -e "${STATE}/restore-container-started" ] && \
                                    [ ! -e "${STATE}/oneoff-pretag-triggered" ]; then
                                    : >"${STATE}/oneoff-pretag-triggered"
                                    printf 'oneoff:pre-tag-drift\n' >>"${EVENTS}"
                                    printf '%s\n' "${OLD_API_IMAGE_ID}"
                                elif [ "${restored}" = 1 ]; then
                                    printf '%s\n' "${OLD_API_IMAGE_ID}"
                                else
                                    printf '%s\n' "${NEW_API_IMAGE_ID}"
                                fi ;;
                            npcink-ai-cloud-frontend:prod)
                                printf '%s\n' "${OLD_FRONTEND_IMAGE_ID}" ;;
                            npcink-ai-cloud-worker:prod)
                                printf '%s\n' "${OLD_WORKER_IMAGE_ID}" ;;
                            npcink-ai-cloud-external-nginx:prod)
                                printf '%s\n' "${OLD_PROXY_IMAGE_ID}" ;;
                            npcink-ai-cloud-postgres:prod)
                                if [ "${restored}" = 1 ]; then
                                    printf '%s\n' "${OLD_POSTGRES_IMAGE_ID}"
                                else
                                    printf '%s\n' "${NEW_POSTGRES_IMAGE_ID}"
                                fi ;;
                            npcink-ai-cloud-external-redis:prod)
                                if [ "${restored}" = 1 ]; then
                                    printf '%s\n' "${OLD_REDIS_IMAGE_ID}"
                                else
                                    printf '%s\n' "${NEW_REDIS_IMAGE_ID}"
                                fi ;;
                            npcink-ai-cloud-api:rollback-p1e06)
                                printf '%s\n' "${OLD_API_IMAGE_ID}" ;;
                            npcink-ai-cloud-frontend:rollback-p1e06)
                                printf '%s\n' "${OLD_FRONTEND_IMAGE_ID}" ;;
                            npcink-ai-cloud-worker:rollback-p1e06)
                                printf '%s\n' "${OLD_WORKER_IMAGE_ID}" ;;
                            npcink-ai-cloud-external-nginx:rollback-p1e06)
                                printf '%s\n' "${OLD_PROXY_IMAGE_ID}" ;;
                            npcink-ai-cloud-postgres:rollback-p1e06)
                                printf '%s\n' "${OLD_POSTGRES_IMAGE_ID}" ;;
                            npcink-ai-cloud-external-redis:rollback-p1e06)
                                printf '%s\n' "${OLD_REDIS_IMAGE_ID}" ;;
                            *)
                                printf '%s\n' "${OLD_API_IMAGE_ID}" ;;
                        esac
                    fi
                    exit 0
                    ;;
                rm)
                    fail_at="$(tr -d '\n' <"${STATE}/fail-at" 2>/dev/null || true)"
                    if [ "${fail_at}" = "commit_cleanup" ] && \
                        [[ "${reference}" = *':rollback-p1e06' ]]; then
                        printf 'failure:commit-cleanup\n' >>"${EVENTS}"
                        exit 44
                    fi
                    if [[ "${reference}" = *':rollback-p1e06' ]]; then
                        : >"${STATE}/rollback-removed"
                        printf 'images:rollback-tag-removed\n' >>"${EVENTS}"
                    fi
                    exit 0
                    ;;
            esac
            ;;
        tag)
            : >"${STATE}/image-restored"
            printf 'images:production-tag-restored\n' >>"${EVENTS}"
            exit 0
            ;;
        stop)
            fail_at="$(tr -d '\n' <"${STATE}/fail-at" 2>/dev/null || true)"
            if [ "${fail_at}" = "post_migration_stop" ] && \
                [ -e "${STATE}/production-migrated" ]; then
                printf 'failure:docker-writer-stop\n' >>"${EVENTS}"
                exit 46
            fi
            exit 0
            ;;
		start)
			one_off_container="$(
				tr -d '\n' 2>/dev/null <"${STATE}/api-oneoff-container" || true
			)"
			[ -n "${one_off_container}" ] && [ "${2:-}" = "${one_off_container}" ] || exit 2
			: >"${STATE}/api-oneoff-started"
			printf 'oneoff:captured-id-started\n' >>"${EVENTS}"
			exit 0
			;;
        network)
            printf 'network-id\n'
            exit 0
            ;;
        volume)
            case "${2:-}" in
                create)
                    printf '%s\n' "${3:-restore-volume}"
                    exit 0
                    ;;
                rm)
                    printf 'restore:volume-removed\n' >>"${EVENTS}"
                    exit 0
                    ;;
                inspect)
                    exit 1
                    ;;
            esac
            ;;
        run)
            : >"${STATE}/restore-container-started"
            printf 'restore:postgres16-container-started\n' >>"${EVENTS}"
            printf 'restore-container-id\n'
            exit 0
            ;;
        exec)
            one_off_container="$(
                tr -d '\n' 2>/dev/null <"${STATE}/api-oneoff-container" || true
            )"
			shift
			exec_env_names=":"
			exec_container=""
			while [ "$#" -gt 0 ]; do
				case "$1" in
					-i)
						shift
						;;
					--env|-e)
						[ "$#" -ge 2 ] || exit 98
						[[ "$2" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || exit 98
						exec_env_names="${exec_env_names}$2:"
						shift 2
						;;
					*)
						exec_container="$1"
						shift
						break
						;;
				esac
			done
            if [ -n "${one_off_container}" ] && \
                [ "${exec_container}" = "${one_off_container}" ]; then
                fail_at="$(tr -d '\n' <"${STATE}/fail-at" 2>/dev/null || true)"
				for required_exec_env in \
					NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET \
					NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID \
					NPCINK_CLOUD_SERVICE_SETTINGS_SECRET \
					NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID; do
					[[ "${exec_env_names}" = *":${required_exec_env}:"* ]] || exit 82
				done
				if [ "${NPCINK_CLOUD_DATABASE_URL+x}" = "x" ]; then
					[[ "${exec_env_names}" = *':NPCINK_CLOUD_DATABASE_URL:'* ]] || exit 85
				else
					[[ "${exec_env_names}" != *':NPCINK_CLOUD_DATABASE_URL:'* ]] || exit 86
				fi
				for optional_exec_env in \
					NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET \
					NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET; do
					if [ -n "${!optional_exec_env+x}" ]; then
						[[ "${exec_env_names}" = *":${optional_exec_env}:"* ]] || exit 84
					else
						[[ "${exec_env_names}" != *":${optional_exec_env}:"* ]] || exit 77
					fi
				done
				[ -d "${FIXTURE_ROOT}/remote/.release-state/.release-one-off.lock" ] || {
					printf 'oneoff:lock-bypassed-before-payload\n' >>"${EVENTS}"
					exit 99
				}
                printf 'oneoff:payload-started\n' >>"${EVENTS}"
                if [ "${fail_at}" = "oneoff_term_wait" ]; then
                    while :; do /bin/sleep 1; done
                fi
                if [ "${fail_at}" = "oneoff_payload_failure" ]; then
                    printf 'oneoff:payload-failed\n' >>"${EVENTS}"
                    exit 42
                fi
                if [[ "${joined}" = *' alembic upgrade head '* ]]; then
                    [ "${NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET+x}" != "x" ] || exit 89
                    [ "${NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET+x}" != "x" ] || exit 90
                    if [ "${NPCINK_CLOUD_DATABASE_URL+x}" = "x" ]; then
                        if [ "${fail_at}" = "restore_migrate" ] || \
                            [ "${fail_at}" = "previous_runtime_image_mismatch" ] || \
                            [ "${fail_at}" = "previous_runtime_compose_up_failure" ]; then
                            printf 'failure:restore-migrate\n' >>"${EVENTS}"
                            exit 42
                        fi
                        : >"${STATE}/restore-migrated"
                        printf 'migration:independent-restore-to-0068\n' >>"${EVENTS}"
                    else
                        : >"${STATE}/production-migrated"
                        printf 'migration:production-to-0068\n' >>"${EVENTS}"
                    fi
                    exit 0
                fi
                mode=""
                for token in "$@"; do
                    case "${token}" in
                        inventory|dry-run|apply|verify) mode="${token}" ;;
                    esac
                done
                [ -n "${mode}" ] || exit 87
                family=""
                if [[ "${joined}" = *' app.dev.reencrypt_runtime_data '* ]]; then
                    family=runtime
                elif [[ "${joined}" = *' app.dev.reencrypt_service_secrets '* ]]; then
                    family=service
                else
                    exit 88
                fi
                case "${family}:${mode}" in
                    runtime:dry-run|runtime:apply)
                        [ "${NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET+x}" = "x" ] || exit 91
                        [ "${NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET+x}" != "x" ] || exit 92
                        ;;
                    service:dry-run|service:apply)
                        [ "${NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET+x}" != "x" ] || exit 93
                        [ "${NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET+x}" = "x" ] || exit 94
                        ;;
                    runtime:inventory|runtime:verify|service:inventory|service:verify)
                        [ "${NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET+x}" != "x" ] || exit 95
                        [ "${NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET+x}" != "x" ] || exit 96
                        ;;
                    *) exit 97 ;;
                esac
                location=production
                if [ "${NPCINK_CLOUD_DATABASE_URL+x}" = "x" ]; then
                    location=restore
                fi
                if [ "${fail_at}" = "production_service_inventory" ] && \
                    [ "${location}" = "production" ] && [ "${family}" = "service" ] && \
                    [ "${mode}" = "inventory" ]; then
                    printf 'failure:production-service-inventory-after-migration\n' >>"${EVENTS}"
                    exit 43
                fi
                if [ "${fail_at}" = "post_migration_stop" ] && \
                    [ "${location}" = "production" ] && [ "${family}" = "runtime" ] && \
                    [ "${mode}" = "inventory" ]; then
                    rm -f "${STATE}/writers-stopped"
                    : >"${STATE}/writers-reappeared"
                    printf 'failure:writer-reappeared-after-migration\n' >>"${EVENTS}"
                    exit 43
                fi
                printf '%s:%s:%s\n' "${family}" "${location}" "${mode}" >>"${EVENTS}"
                if [ "${fail_at}" = "production_service_identity_drift" ] && \
                    [ "${location}" = "production" ] && [ "${family}" = "service" ] && \
                    [ "${mode}" = "inventory" ]; then
                    printf 'injection:production-service-identity-drift\n' >>"${EVENTS}"
                fi
                if [ "${fail_at}" = "production_service_apply" ] && \
                    [ "${location}" = "production" ] && [ "${family}" = "service" ] && \
                    [ "${mode}" = "apply" ]; then
                    printf 'failure:production-service-apply-after-runtime-apply\n' >>"${EVENTS}"
                    exit 43
                fi
                "${HOST_PYTHON}" - \
                    "${family}" \
                    "${mode}" \
                    "${location}" \
                    "${fail_at}" \
                    "${STATE}" <<'PY'
import json
import sys
from pathlib import Path

family = sys.argv[1]
mode = sys.argv[2]
location = sys.argv[3]
fail_at = sys.argv[4]
state_path = Path(sys.argv[5])
totals = {"runtime": 18, "service": 12}
total = totals[family]
values = {
    "inventory": (total, total, 0, 0, total),
    "dry-run": (total, total, 0, 0, total),
    "apply": (total, 0, total, total, total),
    "verify": (total, 0, total, 0, 0),
}[mode]
counts_by_family = {
    "runtime": {
        "site_api_key": {"total": 17},
        "site_runtime_callback": {"total": 0},
        "addon_connection_payload": {"total": 1},
        "portal_idempotency_response": {"total": 0},
        "runtime_execution_input": {"total": 0},
    },
    "service": {
        "provider_connection_secret": {"total": 8},
        "service_setting_secret": {"total": 4},
    },
}
identity_path = state_path / f"production-{family}-row-identifiers.json"
row_identifiers = json.loads(identity_path.read_text(encoding="utf-8"))
if (
    fail_at == "production_service_identity_drift"
    and location == "production"
    and family == "service"
):
    row_identifiers[-1] = "service_setting_secret:portal_qq_login:wrong_entry"
if len(row_identifiers) != total or len(set(row_identifiers)) != total:
    raise SystemExit(98)
payload = {
    "mode": mode,
    "total": values[0],
    "legacy": values[1],
    "current": values[2],
    "migrated": values[3],
    "would_migrate": values[4],
    "counts_by_kind": counts_by_family[family],
    "row_identifiers": row_identifiers,
}
print(json.dumps(payload, sort_keys=True))
PY
                exit 0
            elif [[ "${joined}" = *'pg_isready'* ]]; then
                exit 0
            elif [[ "${joined}" = *'show server_version_num'* ]]; then
                printf '160000\n'
                exit 0
            elif [[ "${joined}" = *'pg_restore --exit-on-error'* ]]; then
                printf 'restore:backup-restored\n' >>"${EVENTS}"
                exit 0
            elif [[ "${joined}" = *'select version_num from alembic_version'* ]]; then
                if [ -e "${STATE}/restore-migrated" ]; then
                    printf '20260717_0068\n'
                else
                    printf '20260710_0058\n'
                fi
                exit 0
            fi
            exit 0
            ;;
        rm)
            target="${!#}"
            one_off_container="$(
                tr -d '\n' 2>/dev/null <"${STATE}/api-oneoff-container" || true
            )"
            fail_at="$(tr -d '\n' <"${STATE}/fail-at" 2>/dev/null || true)"
            if [ -n "${one_off_container}" ] && [ "${target}" = "${one_off_container}" ]; then
                if [ "${fail_at}" = "oneoff_cleanup_failure" ]; then
                    printf 'oneoff:cleanup-failed\n' >>"${EVENTS}"
                    exit 45
                fi
				if [ "${fail_at}" = "oneoff_cleanup_false_success" ]; then
					printf 'oneoff:cleanup-false-success\n' >>"${EVENTS}"
					exit 0
				fi
				rm -f "${STATE}/api-oneoff-container" "${STATE}/api-oneoff-started"
				if [ "${fail_at}" = "oneoff_cleanup_probe_failure" ]; then
					: >"${STATE}/oneoff-cleanup-probe-armed"
				fi
                printf 'oneoff:container-removed\n' >>"${EVENTS}"
                exit 0
            fi
            printf 'restore:container-removed\n' >>"${EVENTS}"
            exit 0
            ;;
        container)
            if [ "${2:-}" = "ls" ]; then
				fail_at="$(tr -d '\n' <"${STATE}/fail-at" 2>/dev/null || true)"
				if [ "${fail_at}" = "oneoff_cleanup_probe_failure" ] && \
					[ -e "${STATE}/oneoff-cleanup-probe-armed" ]; then
					printf 'oneoff:cleanup-probe-failed\n' >>"${EVENTS}"
					exit 46
				fi
				one_off_container="$(
					tr -d '\n' 2>/dev/null <"${STATE}/api-oneoff-container" || true
				)"
				filter_id=""
				previous_token=""
				for token in "$@"; do
					if [ "${previous_token}" = "--filter" ]; then
						case "${token}" in id=*) filter_id="${token#id=}" ;; esac
					fi
					previous_token="${token}"
				done
				if [ -n "${one_off_container}" ] && \
					{ [ -z "${filter_id}" ] || [ "${filter_id}" = "${one_off_container}" ]; }; then
					printf '%s\n' "${one_off_container}"
				fi
                exit 0
			elif [ "${2:-}" = "inspect" ]; then
                one_off_container="$(
                    tr -d '\n' 2>/dev/null <"${STATE}/api-oneoff-container" || true
                )"
                [ -n "${one_off_container}" ] && [ "${3:-}" = "${one_off_container}" ]
                exit $?
            fi
            ;;
        compose)
            for forbidden_name in \
                POSTGRES_USER POSTGRES_DB COMPOSE_FILE COMPOSE_PROFILES \
                NPCINK_CLOUD_RELEASE_TOOL_PYTHON; do
                [ "${!forbidden_name+x}" != "x" ] || exit 75
            done
            shift
            action=""
            compose_env_file=""
			compose_file=""
            previous_token=""
            while [ "$#" -gt 0 ]; do
                if [ "${previous_token}" = "--env-file" ]; then
                    compose_env_file="$1"
                fi
				if [ "${previous_token}" = "-f" ]; then
					compose_file="$1"
				fi
                previous_token="$1"
                case "$1" in
					config|exec|stop|run|ps|rm|up)
                        action="$1"
                        shift
                        break
                        ;;
                    *) shift ;;
                esac
            done
            action_joined=" $* "
			case "${compose_file}" in
				"${FIXTURE_ROOT}/remote/release-new/docker-compose.runtime.yml"|\
				"${FIXTURE_ROOT}/remote/release-old/docker-compose.runtime.yml") ;;
				*) exit 76 ;;
			esac
			case "${action}" in
				config)
					if [ "${!#}" = "release-one-off" ]; then
						printf '{"services":{"release-one-off":{"image":"%s"}}}\n' \
							"${NPCINK_CLOUD_API_RELEASE_IMAGE}"
					elif [[ "${action_joined}" = *' --format json '* ]]; then
						cat <<'JSON'
{
  "services": {
    "proxy": {"image": "npcink-ai-cloud-external-nginx:prod"},
    "frontend": {"image": "npcink-ai-cloud-frontend:prod"},
    "api": {"image": "npcink-ai-cloud-api:prod"},
    "worker": {"image": "npcink-ai-cloud-worker:prod"},
    "callback-worker": {"image": "npcink-ai-cloud-worker:prod"},
    "ops-worker": {"image": "npcink-ai-cloud-worker:prod"}
  }
}
JSON
					else
						exit 2
					fi
					exit 0
					;;
                stop)
                    fail_at="$(tr -d '\n' <"${STATE}/fail-at" 2>/dev/null || true)"
                    if [ "${fail_at}" = "post_migration_stop" ] && \
                        [ -e "${STATE}/production-migrated" ]; then
                        printf 'failure:compose-writer-stop\n' >>"${EVENTS}"
                        exit 47
                    fi
                    : >"${STATE}/writers-stopped"
                    rm -f "${STATE}/writers-reappeared"
                    printf 'writers:stopped\n' >>"${EVENTS}"
                    exit 0
                    ;;
                up)
					if [[ "${action_joined}" = *' release-one-off '* ]]; then
						[[ "${action_joined}" = *' --no-start '* ]] || exit 67
						[[ "${action_joined}" = *' --pull never '* ]] || exit 68
						[[ "${action_joined}" = *' --no-build '* ]] || exit 69
						[[ "${action_joined}" = *' --no-deps '* ]] || exit 70
						[[ "${action_joined}" = *' --force-recreate '* ]] || exit 71
						[ -d "${FIXTURE_ROOT}/remote/.release-state/.release-one-off.lock" ] || {
							printf 'oneoff:lock-bypassed-before-create\n' >>"${EVENTS}"
							exit 99
						}
						[ ! -e "${STATE}/api-oneoff-container" ] || exit 72
						printf 'id-release-one-off\n' >"${STATE}/api-oneoff-container"
						rm -f "${STATE}/api-oneoff-started"
						printf 'oneoff:lock-observed\n' >>"${EVENTS}"
						printf 'oneoff:container-created\n' >>"${EVENTS}"
						exit 0
					fi
                    if [[ "${action_joined}" = *' --force-recreate '* ]]; then
                        [[ "${action_joined}" = *' --no-deps '* ]] || exit 88
                        if [[ "${action_joined}" = *' postgres '* ]] && \
                            [[ "${action_joined}" = *' redis '* ]]; then
                            fail_at="$(tr -d '\n' <"${STATE}/fail-at" 2>/dev/null || true)"
                            if [ -e "${STATE}/image-restored" ]; then
                                if [ "${fail_at}" = "data_restore" ] || \
                                    [ "${fail_at}" = "data_switch_restore_failure" ]; then
                                    printf 'failure:old-data-restore\n' >>"${EVENTS}"
                                    exit 45
                                fi
                                printf 'restored\n' >"${STATE}/data-generation"
                                printf 'recovery:previous-data-services-recreated\n' >>"${EVENTS}"
                            else
                                printf 'new\n' >"${STATE}/data-generation"
                                printf 'data:target-services-recreated\n' >>"${EVENTS}"
                                if [ "${fail_at}" = "maintenance_env_replace" ]; then
                                    replacement="${FIXTURE_ROOT}/.maintenance-env-b.$$"
                                    {
                                        printf '%s\n' \
                                            'NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET=dXV1dXV1dXV1dXV1dXV1dXV1dXV1dXV1dXV1dXV1dXU='
                                        printf '%s\n' \
                                            'NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID=p1-e06-runtime-replacement-b'
                                        printf '%s\n' \
                                            'NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET=replacement-runtime-old-secret-0123456789-ABCDEFGHIJ'
                                        printf '%s\n' \
                                            'NPCINK_CLOUD_SERVICE_SETTINGS_SECRET=dnZ2dnZ2dnZ2dnZ2dnZ2dnZ2dnZ2dnZ2dnZ2dnZ2dnY='
                                        printf '%s\n' \
                                            'NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID=p1-e06-service-replacement-b'
                                        printf '%s\n' \
                                            'NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET=replacement-service-old-secret-0123456789-ABCDEFGHIJ'
                                    } >"${replacement}"
                                    chmod 0600 "${replacement}"
                                    mv -f "${replacement}" \
                                        "${FIXTURE_ROOT}/runtime-data-reencrypt.env"
                                    printf 'maintenance-env:replaced-with-valid-b\n' >>"${EVENTS}"
                                fi
                                if [ "${fail_at}" = "data_switch" ] || \
                                    [ "${fail_at}" = "data_switch_restore_failure" ]; then
                                    printf 'failure:data-switch\n' >>"${EVENTS}"
                                    exit 44
                                fi
                            fi
                        else
                            [[ "${action_joined}" != *' postgres '* ]] || exit 89
                            [[ "${action_joined}" != *' redis '* ]] || exit 90
                            rm -f "${STATE}/writers-stopped" "${STATE}/writers-reappeared"
                            printf 'recovery:previous-public-writers-recreated\n' >>"${EVENTS}"
                            fail_at="$(tr -d '\n' <"${STATE}/fail-at" 2>/dev/null || true)"
                            if [ "${fail_at}" = "previous_runtime_compose_up_failure" ]; then
                                printf 'failure:previous-runtime-compose-up\n' >>"${EVENTS}"
                                exit 48
                            fi
                        fi
                    fi
                    exit 0
                    ;;
                ps)
                    service="${!#}"
                    if [ "${service}" = "release-one-off" ]; then
						if [ -e "${STATE}/api-oneoff-container" ]; then
							cat "${STATE}/api-oneoff-container"
						fi
					elif [ "${service}" = "postgres" ] || [ "${service}" = "redis" ]; then
                        generation="$(
                            tr -d '\n' <"${STATE}/data-generation" 2>/dev/null || \
                                printf 'old'
                        )"
                        printf 'id-%s-%s\n' "${service}" "${generation}"
                    else
                        printf 'id-%s\n' "${service}"
                    fi
                    exit 0
                    ;;
				rm)
					[ "${!#}" = "release-one-off" ] || exit 2
					fail_at="$(tr -d '\n' <"${STATE}/fail-at" 2>/dev/null || true)"
					if [ "${fail_at}" = "oneoff_cleanup_failure" ]; then
						printf 'oneoff:cleanup-failed\n' >>"${EVENTS}"
						exit 45
					fi
					if [ "${fail_at}" = "oneoff_cleanup_false_success" ]; then
						printf 'oneoff:cleanup-false-success\n' >>"${EVENTS}"
						exit 0
					fi
					if [ -e "${STATE}/api-oneoff-container" ]; then
						rm -f "${STATE}/api-oneoff-container" "${STATE}/api-oneoff-started"
						printf 'oneoff:container-removed\n' >>"${EVENTS}"
					fi
					exit 0
					;;
                exec)
                    if [[ "${action_joined}" = *'pg_dump'* ]]; then
                        printf 'FAKE_CUSTOM_POSTGRES_DUMP\n'
                    elif [[ "${action_joined}" = *'pg_restore --list'* ]]; then
                        printf 'FAKE RESTORE CATALOG\n'
                    elif [[ "${action_joined}" = *'pg_stat_activity'* ]]; then
                        printf '0\n'
                    elif [[ "${action_joined}" = \
                        *'select version_num from alembic_version'* ]]; then
                        if [ -e "${STATE}/production-migrated" ]; then
                            printf '20260717_0068\n'
                        else
                            printf '20260710_0058\n'
                            if [ -e "${STATE}/writers-running" ]; then
                                printf 'recovery:previous-database-still-0058\n' >>"${EVENTS}"
                            fi
                        fi
                    fi
                    exit 0
                    ;;
            esac
            ;;
    esac

    printf 'unhandled-docker-call:%s\n' "${joined}" >>"${EVENTS}"
    exit 92
    """


def _cutover_command(fixture: CutoverFixture) -> list[str]:
    return [
        str(SCRIPT),
        "--remote-dir",
        str(fixture.remote),
        "--staged-release",
        str(fixture.staged_release),
        "--maintenance-env",
        str(fixture.maintenance_env),
        "--backup-path",
        str(fixture.backup),
        "--off-host-receipt",
        str(fixture.receipt),
        "--host-python",
        sys.executable,
        "--off-host-receipt-timeout-seconds",
        "30",
        "--confirm-off-host-handoff",
        OFF_HOST_ACK,
        "--confirm-whole-database-restore",
        RESTORE_ACK,
        "--confirm-production-cutover",
        CUTOVER_ACK,
    ]


def _cutover_environment(fixture: CutoverFixture) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PATH"] = f"{fixture.fake_bin}{os.pathsep}{environment['PATH']}"
    environment["TMPDIR"] = str(fixture.root / "tmp")
    environment["POSTGRES_USER"] = "ambient-must-not-reach-compose"
    environment["POSTGRES_DB"] = "ambient-must-not-reach-compose"
    environment["COMPOSE_FILE"] = "/ambient/must-not-reach-compose.yml"
    environment["COMPOSE_PROFILES"] = "ambient-must-not-reach-compose"
    environment["NPCINK_CLOUD_RELEASE_TOOL_PYTHON"] = "/ambient/python3.6"
    environment["NPCINK_CLOUD_DATABASE_URL"] = "ambient-must-not-reach-compose"
    environment.pop("DOCKER_HOST", None)
    return environment


def _run_cutover(
    fixture: CutoverFixture,
    *,
    fail_at: str | None = None,
) -> subprocess.CompletedProcess[str]:
    process, command = _start_cutover(fixture, fail_at=fail_at)
    _publish_off_host_receipt(fixture, process)
    stdout, stderr = process.communicate(timeout=30)
    completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    if completed.returncode != 0:
        assert not _global_activation_receipt(fixture).exists()
        assert not _maintenance_env_snapshot(fixture).exists()
    return completed


def _start_cutover(
    fixture: CutoverFixture,
    *,
    fail_at: str | None = None,
) -> tuple[subprocess.Popen[str], list[str]]:
    if fail_at is not None:
        (fixture.state / "fail-at").write_text(fail_at + "\n", encoding="utf-8")
    command = _cutover_command(fixture)
    environment = _cutover_environment(fixture)
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return process, command


def _publish_off_host_receipt(
    fixture: CutoverFixture,
    process: subprocess.Popen[str],
) -> None:
    deadline = time.monotonic() + 20
    while not fixture.handoff.exists():
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"cutover exited before receipt handoff ({process.returncode})\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            )
        if time.monotonic() >= deadline:
            process.terminate()
            stdout, stderr = process.communicate(timeout=5)
            raise AssertionError(f"timed out waiting for handoff\n{stdout}\n{stderr}")
        time.sleep(0.01)

    handoff = json.loads(fixture.handoff.read_text(encoding="utf-8"))
    receipt_tmp = fixture.receipt.with_name(f".{fixture.receipt.name}.tmp")
    receipt_tmp.write_text(
        json.dumps(
            {
                "contract": "p1_e06_off_host_backup_receipt.v1",
                "status": "passed",
                "backup_sha256": handoff["backup_sha256"],
                "off_host_copy": True,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    receipt_tmp.chmod(0o600)
    os.replace(receipt_tmp, fixture.receipt)


def _wait_for_event(
    fixture: CutoverFixture,
    process: subprocess.Popen[str],
    expected: str,
) -> None:
    deadline = time.monotonic() + 20
    while True:
        if fixture.events.exists() and expected in _read_events(fixture):
            return
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"cutover exited before event {expected!r} ({process.returncode})\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            )
        if time.monotonic() >= deadline:
            process.terminate()
            stdout, stderr = process.communicate(timeout=5)
            raise AssertionError(f"timed out waiting for event {expected!r}\n{stdout}\n{stderr}")
        time.sleep(0.01)


def _read_events(fixture: CutoverFixture) -> list[str]:
    return fixture.events.read_text(encoding="utf-8").splitlines()


def _one_off_exec_payloads(fixture: CutoverFixture) -> list[tuple[str, ...]]:
    payloads: list[tuple[str, ...]] = []
    for line in fixture.docker_calls.read_text(encoding="utf-8").splitlines():
        if not line.startswith("docker|exec|-i|") or "|id-release-one-off|" not in line:
            continue
        fields = line.split("|")
        assert fields[:3] == ["docker", "exec", "-i"]
        container_index = fields.index("id-release-one-off")
        env_options = fields[3:container_index]
        assert len(env_options) % 2 == 0
        assert all(env_options[index] == "--env" for index in range(0, len(env_options), 2))
        assert all(env_options[index].isidentifier() for index in range(1, len(env_options), 2))
        payloads.append(tuple(fields[container_index + 1 :]))
    return payloads


def _row_identity_sha256(row_identifiers: object) -> str:
    assert isinstance(row_identifiers, list)
    assert all(isinstance(identifier, str) for identifier in row_identifiers)
    canonical = json.dumps(
        sorted(row_identifiers),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _global_activation_receipt(fixture: CutoverFixture) -> Path:
    return fixture.remote / ".release-state" / "p1-e06-activation.json"


def _maintenance_env_snapshot(fixture: CutoverFixture) -> Path:
    return fixture.evidence / ".maintenance-env.snapshot"


def _read_marker(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line
    )


def test_cutover_entry_is_executable_valid_bash_and_help_is_non_mutating() -> None:
    assert SCRIPT.is_file()
    assert os.access(SCRIPT, os.X_OK)
    subprocess.run(["bash", "-n", str(SCRIPT)], cwd=ROOT, check=True)

    completed = subprocess.run(
        [str(SCRIPT), "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "one-time, fail-closed P1-E06" in completed.stdout
    assert "--off-host-receipt" in completed.stdout
    assert "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET=<old-root>" in completed.stdout
    assert "NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET=<old-root>" in completed.stdout
    assert "filesystem device numbers" in completed.stdout
    assert "never restarts old code after" in completed.stdout
    assert "migration starts" in completed.stdout


def test_static_contract_is_fail_closed_and_compose_v227_compatible() -> None:
    source = _source()
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert source.index('CURRENT_UID="$(id -u)"') < source.index('mkdir "${DEPLOY_LOCK_DIR}"')
    assert source.index('HOST_PYTHON_VERSION="$(') < source.index('mkdir "${DEPLOY_LOCK_DIR}"')
    assert "managed remote directory must be owned by root" in source
    assert "managed remote directory must not be group/world writable" in source
    assert source.index('mkdir "${DEPLOY_LOCK_DIR}"') < source.index(
        'PREVIOUS_RELEASE="$(readlink -f "${CURRENT_LINK}")"'
    )
    assert source.index('mkdir "${DEPLOY_LOCK_DIR}"') < source.index(
        'done <"${MAINTENANCE_ENV_SNAPSHOT}"'
    )
    assert '"${STAGED_ENV_FILE}" "${MAINTENANCE_ENV_SNAPSHOT}"' in source
    assert source.count("assert_maintenance_env_source_unchanged") >= 4
    assert 'GLOBAL_ACTIVATION_RECEIPT="${RELEASE_STATE_ROOT}/p1-e06-activation.json"' in source
    assert 'CURRENT_EXTERNAL_EDGE_READY}" = "true"' in source
    assert 'CADDY_IDS="$(docker ps -q' in source
    assert 'CADDY_IDS="$(docker ps -aq' not in source
    assert "systemctl is-active --quiet nginx" in source
    assert "nginx -t" in source
    assert '--resolve "${domain_name}:443:127.0.0.1"' in source
    assert "--env-from-file" not in source
    assert "run --rm --no-deps --pull never" not in source
    assert "run_exact_api_one_off_isolated() {" in source
    assert 'run_exact_api_one_off_isolated "$@" &' in source
    assert 'ONE_OFF_PREVIOUS_ASYNC_PID="$!"' in source
    assert 'observed_async_pid="$!"' in source
    assert 'ACTIVE_ONE_OFF_PID="${observed_async_pid}"' in source
    assert 'kill "-${signal_name}" "${ACTIVE_ONE_OFF_PID}"' in source
    assert source.index("set +x") < source.index("MAINTENANCE_ENV_SOURCE_PROOF=")
    assert source.index(
        'CURRENT_STAGE="prove-governed-one-off-absence-before-mutation"'
    ) < source.index('CURRENT_STAGE="prepare-exact-bundle-images"')
    assert "compose_maintenance" not in source
    assert "time.sleep(900)" not in source
    assert "npcink_ai_cloud_compose_run_with_image_proof" in source
    assert 'exec_env_args+=(--exec-env "${env_name}")' in source
    assert '"${exec_env_args[@]}" -- "${payload[@]}" </dev/null' in source
    assert "API_ONE_OFF_CONTAINER" not in source
    assert "docker image inspect --format '{{.Id}}' npcink-ai-cloud-api:prod" in source
    assert "EXPECTED_RUNTIME_LEGACY_TOTAL=18" in source
    assert "EXPECTED_SERVICE_LEGACY_TOTAL=12" in source
    assert "EXPECTED_LEGACY_TOTAL=$((EXPECTED_RUNTIME_LEGACY_TOTAL +" in source
    assert "if set(values) != allowed:" in source
    assert 'base64.urlsafe_b64encode(decoded).decode("ascii") != value' in source
    assert '"NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET"' in source
    assert '"NPCINK_CLOUD_SERVICE_SETTINGS_SECRET"' in source
    assert '"NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET"' in source
    assert '"NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET"' in source
    assert "-e NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET" in source
    assert "-e NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID" in source
    assert "-e NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET" in source
    assert "-e NPCINK_CLOUD_SERVICE_SETTINGS_SECRET" in source
    assert "-e NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID" in source
    assert "-e NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET" in source
    assert "-e NPCINK_CLOUD_DATABASE_URL" in source
    assert "python -m app.dev.reencrypt_runtime_data" in source
    assert "python -m app.dev.reencrypt_service_secrets" in source
    assert source.count("run_api_evidence restore") == 4
    assert source.count("run_service_api_evidence restore") == 4
    assert source.count("run_api_evidence production") == 4
    assert source.count("run_service_api_evidence production") == 4
    assert 'NPCINK_CLOUD_RELEASE_TOOL_PYTHON="${HOST_PYTHON}"' in source
    assert "docker run -d \\\n\t--pull=never" in source
    assert '"${RESTORE_POSTGRES_IMAGE_ID}"' in source
    assert '"${MANIFEST_HELPER}" loaded-role-daemon-id' in source
    assert "--target-daemon-map" not in source
    assert '--root "${STAGED_RELEASE}" --role api' in source
    assert '--root "${STAGED_RELEASE}" --role "${role}"' in source
    assert 'reference="npcink-ai-cloud-external-redis:prod"' in source
    assert 'reference="npcink-ai-cloud-redis:prod"' not in source
    assert "MIGRATION_STARTED=1" in source
    assert (
        "PREVIOUS_RUNTIME_SERVICES=(proxy frontend api worker callback-worker ops-worker)"
        in source
    )
    assert (
        'PUBLIC_AND_WRITER_SERVICES=("${PREVIOUS_RUNTIME_SERVICES[@]}" release-one-off)'
        in source
    )
    assert 'for service in "${PREVIOUS_RUNTIME_SERVICES[@]}"; do' in source
    assert "backend-postgres-cutover:" in ci
    assert "image: postgres:16" in ci
    assert "tests/integration/test_runtime_data_encryption_0058_to_0068.py" in ci
    assert "BACKEND_POSTGRES_CUTOVER_RESULT" in ci
    assert "PostgreSQL 16 encryption cutover regression did not pass" in ci
    assert 'CURRENT_STAGE="switch-production-data-services-to-target-images"' in source
    assert "NPCINK_CLOUD_LOAD_MODE=data-only" in source
    assert 'bash "${STAGED_RELEASE}/deploy/remote-load-and-up.sh"' in source
    assert "DATA_SWITCH_ATTEMPTED=1" in source
    assert "ACTIVATION_COMMITTED=1" in source
    assert "activation_committed_terminalization_incomplete" in source
    assert "do_not_rollback_healthy_active_runtime" in source
    assert "stop_expected_services_and_verify" in source
    assert 'outcome="full_database_restore_required"' in source
    assert 'outcome="previous_release_restored_before_migration"' in source
    assert 'for terminal_evidence_path in "${PASSED_RESULT}" "${FINAL_RESULT_TMP}"' in source
    assert 'mv -Tn "${terminal_evidence_path}" "${quarantine_path}"' in source
    assert "conflicting_terminal_evidence" in source
    assert source.index(
        'publish_fresh_file "${FINAL_RESULT_TMP}" "${PASSED_RESULT}"'
    ) < source.index(
        'publish_fresh_file "${GLOBAL_ACTIVATION_RECEIPT_TMP}" "${GLOBAL_ACTIVATION_RECEIPT}"'
    )
    assert source.index(
        'publish_fresh_file "${GLOBAL_ACTIVATION_RECEIPT_TMP}" "${GLOBAL_ACTIVATION_RECEIPT}"'
    ) < source.index('rmdir "${DEPLOY_LOCK_DIR}"')


def test_maintenance_env_requires_exact_independent_canonical_dual_domain_values(
    tmp_path: Path,
) -> None:
    base_values = {
        "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET": RUNTIME_TARGET_SECRET,
        "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID": RUNTIME_TARGET_KEY_ID,
        "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET": RUNTIME_OLD_SECRET,
        "NPCINK_CLOUD_SERVICE_SETTINGS_SECRET": SERVICE_TARGET_SECRET,
        "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID": SERVICE_TARGET_KEY_ID,
        "NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET": SERVICE_OLD_SECRET,
    }
    invalid_variants = {
        "missing-service-old": {
            key: value
            for key, value in base_values.items()
            if key != "NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET"
        },
        "unexpected-seventh-key": base_values | {"NPCINK_CLOUD_UNEXPECTED": "rejected"},
        "noncanonical-runtime-root": base_values
        | {"NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET": (RUNTIME_TARGET_SECRET.rstrip("="))},
        "shared-target-root": base_values
        | {"NPCINK_CLOUD_SERVICE_SETTINGS_SECRET": RUNTIME_TARGET_SECRET},
        "runtime-target-reused-as-service-old": base_values
        | {"NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET": RUNTIME_TARGET_SECRET},
        "service-target-reused-as-runtime-old": base_values
        | {"NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET": SERVICE_TARGET_SECRET},
        "cross-domain-target-old-roots-swapped": base_values
        | {
            "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET": SERVICE_TARGET_SECRET,
            "NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET": RUNTIME_TARGET_SECRET,
        },
        "shared-key-id": base_values
        | {"NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID": RUNTIME_TARGET_KEY_ID},
    }

    for case_name, values in invalid_variants.items():
        fixture = _make_fixture(tmp_path / case_name)
        fixture.maintenance_env.write_text(
            "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
            encoding="utf-8",
        )
        fixture.maintenance_env.chmod(0o600)

        completed = subprocess.run(
            _cutover_command(fixture),
            cwd=ROOT,
            env=_cutover_environment(fixture),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

        assert completed.returncode != 0
        assert "maintenance env contract is invalid" in completed.stderr
        assert not (fixture.state / "image-prepared").exists()
        assert not fixture.handoff.exists()
        combined_output = completed.stdout + completed.stderr
        assert all(secret not in combined_output for secret in values.values())


def test_stale_certificate_evidence_fails_before_image_prepare(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    evidence_path = (
        fixture.remote / ".release-state" / "release-old" / "certificate-renewal-readiness.json"
    )
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    stale = dt.datetime.now(dt.UTC) - dt.timedelta(days=8)
    payload["generated_at_epoch"] = int(stale.timestamp())
    payload["generated_at"] = stale.isoformat(timespec="seconds").replace("+00:00", "Z")
    evidence_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    evidence_path.chmod(0o600)

    completed = subprocess.run(
        _cutover_command(fixture),
        cwd=ROOT,
        env=_cutover_environment(fixture),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode != 0
    assert "certificate renewal evidence is invalid or stale" in completed.stderr
    assert not (fixture.state / "image-prepared").exists()
    assert not fixture.handoff.exists()
    assert not _global_activation_receipt(fixture).exists()
    assert not _maintenance_env_snapshot(fixture).exists()
    if fixture.docker_calls.exists():
        assert "docker|load|" not in fixture.docker_calls.read_text(encoding="utf-8")


def test_executable_success_proves_receipt_restore_lock_edge_env_and_terminal_evidence(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture)

    assert completed.returncode == 0, completed.stderr
    result_path = fixture.evidence / "cutover-result.json"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["status"] == "passed"
    assert payload["off_host_copy_verified"] is True
    assert payload["independent_postgres16_restore_verified"] is True
    assert payload["exact_data_service_images_activated"] is True
    assert payload["activation_committed"] is True
    assert payload["runtime_legacy_rows_migrated"] == 18
    assert payload["service_legacy_rows_migrated"] == 12
    assert payload["legacy_rows_migrated"] == 30
    assert payload["off_host_receipt"] == str(fixture.receipt)
    global_receipt_path = _global_activation_receipt(fixture)
    assert global_receipt_path.is_file()
    assert not global_receipt_path.is_symlink()
    assert stat.S_IMODE(global_receipt_path.stat().st_mode) == 0o600
    global_receipt = json.loads(global_receipt_path.read_text(encoding="utf-8"))
    assert global_receipt == {
        "contract": "p1_e06_global_activation.v1",
        "status": "passed",
        "source_revision": "20260710_0058",
        "target_revision": "20260717_0068",
        "runtime_legacy_rows_migrated": 18,
        "service_legacy_rows_migrated": 12,
        "legacy_rows_migrated": 30,
        "active_release": str(fixture.staged_release),
        "activation_commit_sha256": hashlib.sha256(
            (fixture.evidence / "activation-commit.json").read_bytes()
        ).hexdigest(),
        "cutover_result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
    }
    assert not _maintenance_env_snapshot(fixture).exists()
    receipt_evidence_path = fixture.evidence / "off-host-receipt-verified.json"
    receipt_evidence = json.loads(receipt_evidence_path.read_text(encoding="utf-8"))
    assert receipt_evidence["status"] == "passed"
    assert receipt_evidence["source_receipt_path"] == str(fixture.receipt)
    assert receipt_evidence["validated_receipt"]["off_host_copy"] is True
    assert payload["off_host_receipt_sha256"] == receipt_evidence["source_receipt_sha256"]
    activation = json.loads(
        (fixture.evidence / "activation-commit.json").read_text(encoding="utf-8")
    )
    assert activation["status"] == "committed"
    assert activation["database_revision"] == "20260717_0068"
    assert activation["runtime_legacy_rows_migrated"] == 18
    assert activation["service_legacy_rows_migrated"] == 12
    assert activation["legacy_rows_migrated"] == 30
    restore_proof = json.loads(
        (fixture.evidence / "restore-proof.json").read_text(encoding="utf-8")
    )
    assert restore_proof["runtime_legacy_rows"] == 18
    assert restore_proof["service_legacy_rows"] == 12
    assert restore_proof["legacy_rows"] == 30
    assert stat.S_IMODE(result_path.stat().st_mode) == 0o600
    assert fixture.backup.is_file()
    assert stat.S_IMODE(fixture.backup.stat().st_mode) == 0o400
    assert stat.S_IMODE((Path(f"{fixture.backup}.sha256")).stat().st_mode) == 0o400
    assert not (fixture.remote / ".deploy-lock").exists()
    assert not (fixture.remote / ".cutover-failed").exists()
    assert not (fixture.evidence / "rollback-images.tsv").exists()
    assert (fixture.remote / "current").resolve() == fixture.staged_release
    staged_env = (fixture.remote / ".release-state" / "release-new" / "env.deploy").read_text(
        encoding="utf-8"
    )
    current_env = (fixture.remote / ".release-state" / "release-old" / "env.deploy").read_text(
        encoding="utf-8"
    )
    maintenance_values = dict(
        line.split("=", 1)
        for line in fixture.maintenance_env.read_text(encoding="utf-8").splitlines()
    )
    assert maintenance_values == {
        "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET": RUNTIME_TARGET_SECRET,
        "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID": RUNTIME_TARGET_KEY_ID,
        "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET": RUNTIME_OLD_SECRET,
        "NPCINK_CLOUD_SERVICE_SETTINGS_SECRET": SERVICE_TARGET_SECRET,
        "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID": SERVICE_TARGET_KEY_ID,
        "NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET": SERVICE_OLD_SECRET,
    }
    assert "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET=" not in staged_env
    assert "NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET=" not in staged_env
    assert "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET=" in current_env
    assert "NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET=" in current_env
    assert f"NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET={RUNTIME_TARGET_SECRET}" in staged_env
    assert f"NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID={RUNTIME_TARGET_KEY_ID}" in staged_env
    assert f"NPCINK_CLOUD_SERVICE_SETTINGS_SECRET={SERVICE_TARGET_SECRET}" in staged_env
    assert f"NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID={SERVICE_TARGET_KEY_ID}" in staged_env
    data_image_evidence = (fixture.evidence / "new-data-service-image-ids.tsv").read_text(
        encoding="utf-8"
    )
    assert "redis\tnpcink-ai-cloud-external-redis:prod\t" in data_image_evidence
    assert "npcink-ai-cloud-redis:prod" not in data_image_evidence

    events = _read_events(fixture)
    assert events.index("lock:current-read-after-lock") < events.index("edge:nginx-t")
    assert events.index("edge:loopback-https-health") < events.index("helper:prepare-only")
    assert events.index("handoff:marker-published") < events.index(
        "restore:postgres16-container-started"
    )
    assert events.index("migration:independent-restore-to-0068") < events.index(
        "runtime:restore:inventory"
    )
    assert events.index("runtime:restore:inventory") < events.index("service:restore:inventory")
    assert events.index("service:restore:verify") < events.index("data:target-services-recreated")
    assert events.index("data:target-services-recreated") < events.index(
        "migration:production-to-0068"
    )
    assert events.index("terminal:private-result-published-under-lock") < events.index(
        "terminal:global-receipt-published-under-lock"
    )
    assert events.index("terminal:global-receipt-published-under-lock") < events.index(
        "terminal:lock-released-after-global-receipt"
    )
    assert events[-1] == "terminal:lock-released-after-global-receipt"
    assert "images:rollback-tag-removed" in events
    assert "manifest:loaded-role-daemon-id:api" in events
    assert "manifest:loaded-role-daemon-id:postgres" in events
    assert "manifest:loaded-role-daemon-id:external_redis" in events
    assert "failure:default-python3-used" not in events
    assert "failure:release-helper-host-python" not in events
    for location in ("restore", "production"):
        for family in ("runtime", "service"):
            for mode in ("inventory", "dry-run", "apply", "verify"):
                assert events.count(f"{family}:{location}:{mode}") == 1

    docker_calls = fixture.docker_calls.read_text(encoding="utf-8")
    run_calls = [
        line for line in docker_calls.splitlines() if "|compose|" in line and "|run|" in line
    ]
    assert run_calls == []
    assert "time.sleep(900)" not in docker_calls
    one_off_create_calls = [
        line
        for line in docker_calls.splitlines()
        if "|compose|" in line
        and "|up|--no-start|--pull|never|--no-build|--no-deps|--force-recreate|release-one-off"
        in line
    ]
    assert len(one_off_create_calls) == 18
    exec_calls = [
        line
        for line in docker_calls.splitlines()
        if line.startswith("docker|exec|-i|") and "|id-release-one-off|" in line
    ]
    assert len(exec_calls) == 18
    assert all("|--env|NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET" in line for line in exec_calls)
    assert all("|--env|NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID" in line for line in exec_calls)
    assert all("|--env|NPCINK_CLOUD_SERVICE_SETTINGS_SECRET" in line for line in exec_calls)
    assert all(
        "|--env|NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID" in line for line in exec_calls
    )
    assert (
        sum("|--env|NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET" in line for line in exec_calls) == 4
    )
    assert (
        sum("|--env|NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET" in line for line in exec_calls)
        == 4
    )
    assert all(
        not (
            "|--env|NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET" in line
            and "|--env|NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET" in line
        )
        for line in exec_calls
    )
    assert sum("|--env|NPCINK_CLOUD_DATABASE_URL" in line for line in exec_calls) == 9
    runtime_module = ("python", "-m", "app.dev.reencrypt_runtime_data")
    service_module = ("python", "-m", "app.dev.reencrypt_service_secrets")
    encryption_payloads = [
        runtime_module + ("inventory",),
        service_module + ("inventory",),
        runtime_module
        + (
            "dry-run",
            "--old-root-env",
            "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET",
        ),
        service_module
        + (
            "dry-run",
            "--old-root-env",
            "NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET",
        ),
        runtime_module
        + (
            "apply",
            "--confirm-maintenance-window",
            "--old-root-env",
            "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET",
        ),
        service_module
        + (
            "apply",
            "--confirm-maintenance-window",
            "--old-root-env",
            "NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET",
        ),
        runtime_module + ("verify",),
        service_module + ("verify",),
    ]
    assert _one_off_exec_payloads(fixture) == [
        ("alembic", "upgrade", "head"),
        *encryption_payloads,
        ("alembic", "upgrade", "head"),
        *encryption_payloads,
    ]
    assert events.count("oneoff:container-created") == 18
    assert events.count("oneoff:container-removed") == 18
    assert events.count("oneoff:lock-observed") == 18
    assert events.count("oneoff:candidate-created-proved") == 18
    assert events.count("oneoff:captured-id-started") == 18
    assert "oneoff:lock-bypassed-before-create" not in events
    assert "oneoff:lock-bypassed-before-payload" not in events
    assert events.index("oneoff:lock-observed") < events.index("oneoff:candidate-created-proved")
    assert events.index("oneoff:candidate-created-proved") < events.index(
        "oneoff:captured-id-started"
    )
    assert events.index("oneoff:captured-id-started") < events.index("oneoff:payload-started")
    assert not (fixture.remote / ".release-state" / ".release-one-off.lock").exists()
    assert RUNTIME_TARGET_SECRET not in docker_calls
    assert SERVICE_TARGET_SECRET not in docker_calls
    assert RUNTIME_OLD_SECRET not in docker_calls
    assert SERVICE_OLD_SECRET not in docker_calls
    assert "postgresql+psycopg://" not in docker_calls
    assert PRODUCTION_RUNTIME_IDENTITY_SHA256 == (
        "675cce444dbbf801bc8ab7fb35b717888c878e062097e5fb7f2f5f110e5a764c"
    )
    assert PRODUCTION_SERVICE_IDENTITY_SHA256 == (
        "e5010d2b0a2afe22b7729c4c2395c91001a078e282abee87f03a5f0289aa0bf6"
    )
    for location in ("restore", "production"):
        for family, expected_identifiers, expected_digest in (
            (
                "runtime",
                PRODUCTION_RUNTIME_ROW_IDENTIFIERS,
                PRODUCTION_RUNTIME_IDENTITY_SHA256,
            ),
            (
                "service",
                PRODUCTION_SERVICE_ROW_IDENTIFIERS,
                PRODUCTION_SERVICE_IDENTITY_SHA256,
            ),
        ):
            family_segment = "" if family == "runtime" else "-service"
            for mode in ("inventory", "dry-run", "apply", "verify"):
                report = json.loads(
                    (fixture.evidence / f"{location}{family_segment}-{mode}.json").read_text(
                        encoding="utf-8"
                    )
                )
                assert tuple(report["row_identifiers"]) == expected_identifiers
                assert _row_identity_sha256(report["row_identifiers"]) == expected_digest
    restore_container_calls = [
        line for line in docker_calls.splitlines() if line.startswith("docker|run|")
    ]
    assert len(restore_container_calls) == 1
    assert "|--pull=never|" in restore_container_calls[0]
    assert restore_container_calls[0].endswith(f"|{NEW_POSTGRES_IMAGE_ID}")
    assert "npcink-ai-cloud-postgres:prod" not in restore_container_calls[0]


def test_maintenance_env_replacement_fails_closed_without_activating_b(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="maintenance_env_replace")

    assert completed.returncode != 0
    events = _read_events(fixture)
    assert "maintenance-env:replaced-with-valid-b" in events
    assert "migration:production-to-0068" not in events
    marker = _read_marker(fixture.remote / ".cutover-failed")
    assert marker["phase"] == "recheck-production-fence-before-migration"
    assert marker["migration_started"] == "0"
    assert (fixture.remote / "current").resolve() == fixture.previous_release
    replacement_source = fixture.maintenance_env.read_text(encoding="utf-8")
    replacement_values = (
        REPLACEMENT_RUNTIME_TARGET_SECRET,
        REPLACEMENT_SERVICE_TARGET_SECRET,
        REPLACEMENT_RUNTIME_OLD_SECRET,
        REPLACEMENT_SERVICE_OLD_SECRET,
        REPLACEMENT_RUNTIME_KEY_ID,
        REPLACEMENT_SERVICE_KEY_ID,
    )
    assert all(value in replacement_source for value in replacement_values)
    staged_env = (fixture.remote / ".release-state" / "release-new" / "env.deploy").read_text(
        encoding="utf-8"
    )
    assert all(value not in staged_env for value in replacement_values)
    assert not _maintenance_env_snapshot(fixture).exists()
    assert not _global_activation_receipt(fixture).exists()
    docker_calls = fixture.docker_calls.read_text(encoding="utf-8")
    assert all(value not in docker_calls for value in replacement_values)


def test_exact_api_one_off_blocks_pre_creation_tag_drift(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="oneoff_pre_tag_drift")

    assert completed.returncode != 0
    events = _read_events(fixture)
    assert "oneoff:pre-tag-drift" in events
    assert "oneoff:container-created" not in events
    assert "oneoff:payload-started" not in events
    assert not (fixture.state / "api-oneoff-container").exists()
    assert not _global_activation_receipt(fixture).exists()
    assert not _maintenance_env_snapshot(fixture).exists()
    marker = _read_marker(fixture.remote / ".cutover-failed")
    assert marker["phase"] == "independent-restore-migration-rehearsal"
    assert marker["migration_started"] == "0"
    assert "migration:production-to-0068" not in events


def test_exact_api_one_off_image_mismatch_blocks_payload_and_cleans_container(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="oneoff_image_mismatch")

    assert completed.returncode != 0
    events = _read_events(fixture)
    assert "oneoff:container-created" in events
    assert "oneoff:image-mismatch" in events
    assert "oneoff:payload-started" not in events
    assert "oneoff:container-removed" in events
    assert not (fixture.state / "api-oneoff-container").exists()
    assert not _global_activation_receipt(fixture).exists()
    assert not _maintenance_env_snapshot(fixture).exists()
    marker = _read_marker(fixture.remote / ".cutover-failed")
    assert marker["phase"] == "independent-restore-migration-rehearsal"
    assert "migration:production-to-0068" not in events


def test_exact_api_one_off_payload_failure_cleans_container(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="oneoff_payload_failure")

    assert completed.returncode != 0
    events = _read_events(fixture)
    assert "oneoff:container-created" in events
    assert "oneoff:payload-started" in events
    assert "oneoff:payload-failed" in events
    assert "oneoff:container-removed" in events
    assert not (fixture.state / "api-oneoff-container").exists()
    marker = _read_marker(fixture.remote / ".cutover-failed")
    assert marker["phase"] == "independent-restore-migration-rehearsal"
    assert "migration:production-to-0068" not in events


def test_exact_api_one_off_cleanup_failure_is_fail_closed(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="oneoff_cleanup_failure")

    assert completed.returncode != 0
    events = _read_events(fixture)
    assert "oneoff:container-created" in events
    assert "oneoff:payload-started" in events
    assert "migration:independent-restore-to-0068" in events
    assert events.count("oneoff:cleanup-failed") >= 2
    assert "oneoff:container-removed" not in events
    assert (fixture.state / "api-oneoff-container").exists()
    marker = _read_marker(fixture.remote / ".cutover-failed")
    assert marker["phase"] == "independent-restore-migration-rehearsal"
    assert marker["outcome"] == "recovery_incomplete"
    assert marker["recovery"] == "manual_recovery_required_from_observed_state"
    assert "migration:production-to-0068" not in events


def test_exact_api_one_off_cleanup_probe_failure_is_fail_closed(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="oneoff_cleanup_probe_failure")

    assert completed.returncode != 0
    events = _read_events(fixture)
    assert "oneoff:container-created" in events
    assert "oneoff:payload-started" in events
    assert events.count("oneoff:cleanup-probe-failed") >= 2
    assert "oneoff:container-removed" in events
    assert not (fixture.state / "api-oneoff-container").exists()
    assert (fixture.remote / ".release-state" / ".release-one-off.lock").is_dir()
    marker = _read_marker(fixture.remote / ".cutover-failed")
    assert marker["phase"] == "independent-restore-migration-rehearsal"
    assert marker["outcome"] == "recovery_incomplete"
    assert marker["recovery"] == "manual_recovery_required_from_observed_state"
    assert "migration:production-to-0068" not in events


def test_exact_api_one_off_rejects_preexisting_cross_release_lock(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    global_one_off_lock = fixture.remote / ".release-state" / ".release-one-off.lock"
    global_one_off_lock.mkdir(mode=0o700)

    process, command = _start_cutover(fixture)
    stdout, stderr = process.communicate(timeout=30)
    completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)

    assert completed.returncode != 0
    events = _read_events(fixture)
    assert "oneoff:container-created" not in events
    assert "oneoff:payload-started" not in events
    assert "images:prepared" not in events
    assert not fixture.handoff.exists()
    assert global_one_off_lock.is_dir()
    assert (fixture.remote / ".deploy-lock").is_dir()
    marker = _read_marker(fixture.remote / ".cutover-failed")
    assert marker["phase"] == "prove-governed-one-off-absence-before-mutation"
    assert marker["outcome"] == "recovery_incomplete"
    assert "governed release one-off lock is already present" in completed.stderr


def test_cutover_rejects_preexisting_one_off_container_before_mutation(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)
    (fixture.state / "api-oneoff-container").write_text(
        "id-release-one-off\n", encoding="utf-8"
    )

    process, command = _start_cutover(fixture)
    stdout, stderr = process.communicate(timeout=30)
    completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)

    assert completed.returncode != 0
    events = _read_events(fixture)
    assert "images:prepared" not in events
    assert "writers:stopped" not in events
    assert not fixture.handoff.exists()
    assert (fixture.state / "api-oneoff-container").is_file()
    assert (fixture.remote / ".deploy-lock").is_dir()
    marker = _read_marker(fixture.remote / ".cutover-failed")
    assert marker["phase"] == "prove-governed-one-off-absence-before-mutation"
    assert marker["outcome"] == "validation_failed_before_image_or_database_mutation"
    assert "a governed one-off container is already present" in completed.stderr


def test_exact_api_one_off_retains_lock_when_cleanup_reports_false_success(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="oneoff_cleanup_false_success")

    assert completed.returncode != 0
    events = _read_events(fixture)
    assert "oneoff:container-created" in events
    assert "oneoff:payload-started" in events
    assert events.count("oneoff:cleanup-false-success") >= 2
    assert "oneoff:container-removed" not in events
    assert (fixture.state / "api-oneoff-container").exists()
    assert (fixture.remote / ".release-state" / ".release-one-off.lock").is_dir()
    errors = (fixture.evidence / "restore-migrate-to-head.stderr").read_text(
        encoding="utf-8"
    )
    assert "cleanup was incomplete; the global one-off lock was retained" in errors


def test_exact_api_one_off_term_signal_cleans_container(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    process, command = _start_cutover(fixture, fail_at="oneoff_term_wait")
    _publish_off_host_receipt(fixture, process)
    _wait_for_event(fixture, process, "oneoff:payload-started")

    process.terminate()
    stdout, stderr = process.communicate(timeout=15)
    completed = subprocess.CompletedProcess(
        command,
        process.returncode,
        stdout,
        stderr,
    )

    assert completed.returncode != 0
    events = _read_events(fixture)
    assert "oneoff:container-created" in events
    assert "oneoff:payload-started" in events
    assert "oneoff:container-removed" in events
    assert not (fixture.state / "api-oneoff-container").exists()
    assert not _global_activation_receipt(fixture).exists()
    assert not _maintenance_env_snapshot(fixture).exists()
    marker = _read_marker(fixture.remote / ".cutover-failed")
    assert marker["phase"] == "signal-term"
    assert marker["migration_started"] == "0"
    assert "migration:production-to-0068" not in events


def test_executable_pre_migration_failure_restores_only_old_runtime_generation(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="restore_migrate")

    assert completed.returncode != 0
    marker_path = fixture.remote / ".cutover-failed"
    marker = _read_marker(marker_path)
    assert marker["status"] == "failed"
    assert marker["phase"] == "independent-restore-migration-rehearsal"
    assert marker["outcome"] == "previous_release_restored_before_migration"
    assert marker["recovery"] == ("previous_release_proved_at_0058_without_database_restore")
    assert marker["data_switch_attempted"] == "0"
    assert marker["previous_data_services_restored"] == "0"
    assert marker["previous_runtime_restored"] == "1"
    assert marker["database_recovery_point"] == str(fixture.backup)
    assert marker["off_host_receipt"] == str(fixture.receipt)
    assert stat.S_IMODE(marker_path.stat().st_mode) == 0o600
    assert (fixture.remote / ".deploy-lock").is_dir()
    assert not (fixture.evidence / "cutover-result.json").exists()
    assert (fixture.remote / "current").resolve() == fixture.previous_release

    events = _read_events(fixture)
    assert "failure:restore-migrate" in events
    assert "images:production-tag-restored" in events
    assert "recovery:previous-public-writers-recreated" in events
    assert "data:target-services-recreated" not in events
    assert "recovery:previous-data-services-recreated" not in events
    assert "migration:production-to-0068" not in events
    assert "terminal:success-published-after-unlock" not in events

    force_recreate_calls = [
        line
        for line in fixture.docker_calls.read_text(encoding="utf-8").splitlines()
        if "|up|" in line
        and "|--force-recreate|" in line
        and "|release-one-off" not in line
    ]
    assert len(force_recreate_calls) == 1
    assert "|--no-deps|" in force_recreate_calls[0]
    assert "|postgres|" not in force_recreate_calls[0]
    assert "|redis|" not in force_recreate_calls[0]
    assert "|caddy|" not in force_recreate_calls[0]


def test_executable_pre_migration_recovery_rejects_wrong_runtime_image(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="previous_runtime_image_mismatch")

    assert completed.returncode != 0
    marker = _read_marker(fixture.remote / ".cutover-failed")
    assert marker["outcome"] == "recovery_incomplete"
    assert marker["recovery"] == "manual_recovery_required_from_observed_state"
    assert marker["previous_runtime_restored"] == "0"
    assert (fixture.remote / ".deploy-lock").is_dir()
    assert (fixture.remote / "current").resolve() == fixture.previous_release
    events = _read_events(fixture)
    assert "recovery:runtime-image-mismatch" in events
    assert events.count("writers:stopped") >= 2
    assert "terminal:success-published-after-unlock" not in events


def test_executable_pre_migration_recovery_refences_partial_compose_start(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(
        fixture,
        fail_at="previous_runtime_compose_up_failure",
    )

    assert completed.returncode != 0
    marker = _read_marker(fixture.remote / ".cutover-failed")
    assert marker["outcome"] == "recovery_incomplete"
    assert marker["recovery"] == "manual_recovery_required_from_observed_state"
    assert marker["previous_runtime_restored"] == "0"
    assert (fixture.remote / ".deploy-lock").is_dir()
    assert (fixture.remote / "current").resolve() == fixture.previous_release
    events = _read_events(fixture)
    assert "recovery:previous-public-writers-recreated" in events
    assert "failure:previous-runtime-compose-up" in events
    assert events.count("writers:stopped") >= 2
    assert "terminal:success-published-after-unlock" not in events
    for service in ("proxy", "frontend", "api", "worker", "callback-worker", "ops-worker"):
        observed = subprocess.run(
            [
                str(fixture.fake_bin / "docker"),
                "ps",
                "-q",
                "--filter",
                "label=com.docker.compose.project=npcink-ai-cloud",
                "--filter",
                f"label=com.docker.compose.service={service}",
            ],
            env=_cutover_environment(fixture),
            text=True,
            capture_output=True,
            check=False,
        )
        assert observed.returncode == 0
        assert observed.stdout == ""


def test_executable_post_migration_failure_never_restarts_old_code_and_requires_full_restore(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="production_service_inventory")

    assert completed.returncode != 0
    marker_path = fixture.remote / ".cutover-failed"
    marker = _read_marker(marker_path)
    assert marker["status"] == "failed"
    assert marker["phase"] == "production-encryption-inventory"
    assert marker["outcome"] == "full_database_restore_required"
    assert marker["recovery"] == (
        "restore_whole_database_previous_release_external_env_and_both_old_roots_together"
    )
    assert marker["previous_external_env"] == str(
        fixture.remote / ".release-state" / "release-old" / "env.deploy"
    )
    assert marker["required_old_root_env_names"] == (
        "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET,NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET"
    )
    assert marker["database_recovery_point"] == str(fixture.backup)
    assert marker["off_host_receipt"] == str(fixture.receipt)
    assert marker["data_services_switched"] == "1"
    assert marker["image_tags_restored"] == "0"
    assert marker["previous_runtime_restored"] == "0"
    assert marker["post_migration_writer_stop_proved"] == "1"
    assert (fixture.remote / ".deploy-lock").is_dir()
    assert not (fixture.evidence / "cutover-result.json").exists()
    assert (fixture.remote / "current").resolve() == fixture.previous_release

    events = _read_events(fixture)
    assert "migration:production-to-0068" in events
    assert "runtime:production:inventory" in events
    assert "failure:production-service-inventory-after-migration" in events
    assert "service:production:inventory" not in events
    assert "images:production-tag-restored" not in events
    assert "recovery:previous-public-writers-recreated" not in events
    assert (fixture.state / "writers-stopped").exists()
    assert "terminal:success-published-after-unlock" not in events


def test_service_identity_drift_with_frozen_count_requires_full_restore(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="production_service_identity_drift")

    assert completed.returncode != 0
    marker = _read_marker(fixture.remote / ".cutover-failed")
    assert marker["phase"] == "production-encryption-inventory"
    assert marker["outcome"] == "full_database_restore_required"
    assert marker["recovery"] == (
        "restore_whole_database_previous_release_external_env_and_both_old_roots_together"
    )
    assert marker["previous_external_env"] == str(
        fixture.remote / ".release-state" / "release-old" / "env.deploy"
    )
    assert marker["required_old_root_env_names"] == (
        "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET,NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET"
    )
    assert marker["migration_started"] == "1"
    assert marker["data_services_switched"] == "1"
    assert marker["image_tags_restored"] == "0"
    assert marker["previous_data_services_restored"] == "0"
    assert marker["previous_runtime_restored"] == "0"
    assert (fixture.remote / ".deploy-lock").is_dir()
    assert (fixture.remote / "current").resolve() == fixture.previous_release
    assert not (fixture.evidence / "activation-commit.json").exists()
    assert not (fixture.evidence / "cutover-result.json").exists()
    assert not _global_activation_receipt(fixture).exists()

    drifted_report = json.loads(
        (fixture.evidence / "production-service-inventory.json").read_text(encoding="utf-8")
    )
    assert drifted_report["total"] == 12
    assert len(drifted_report["row_identifiers"]) == 12
    assert len(set(drifted_report["row_identifiers"])) == 12
    assert _row_identity_sha256(drifted_report["row_identifiers"]) != (
        PRODUCTION_SERVICE_IDENTITY_SHA256
    )

    events = _read_events(fixture)
    assert "migration:production-to-0068" in events
    assert "runtime:production:inventory" in events
    assert "service:production:inventory" in events
    assert "injection:production-service-identity-drift" in events
    assert "runtime:production:dry-run" not in events
    assert "images:production-tag-restored" not in events
    assert "recovery:previous-data-services-recreated" not in events
    assert "recovery:previous-public-writers-recreated" not in events
    assert "terminal:success-published-after-unlock" not in events


def test_service_apply_failure_after_runtime_apply_requires_full_restore_without_old_restart(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="production_service_apply")

    assert completed.returncode != 0
    marker_path = fixture.remote / ".cutover-failed"
    marker = _read_marker(marker_path)
    assert marker["status"] == "failed"
    assert marker["phase"] == "production-encryption-apply"
    assert marker["outcome"] == "full_database_restore_required"
    assert marker["recovery"] == (
        "restore_whole_database_previous_release_external_env_and_both_old_roots_together"
    )
    assert marker["migration_started"] == "1"
    assert marker["data_services_switched"] == "1"
    assert marker["image_tags_restored"] == "0"
    assert marker["previous_data_services_restored"] == "0"
    assert marker["previous_runtime_restored"] == "0"
    assert marker["post_migration_writer_stop_proved"] == "1"
    assert marker["database_recovery_point"] == str(fixture.backup)
    assert marker["off_host_receipt"] == str(fixture.receipt)
    assert stat.S_IMODE(marker_path.stat().st_mode) == 0o600
    assert (fixture.remote / ".deploy-lock").is_dir()
    assert (fixture.remote / "current").resolve() == fixture.previous_release
    assert not (fixture.evidence / "activation-commit.json").exists()
    assert not (fixture.evidence / "cutover-result.json").exists()
    assert not _global_activation_receipt(fixture).exists()

    runtime_apply_report = json.loads(
        (fixture.evidence / "production-apply.json").read_text(encoding="utf-8")
    )
    assert runtime_apply_report["mode"] == "apply"
    assert runtime_apply_report["migrated"] == 18
    assert _row_identity_sha256(runtime_apply_report["row_identifiers"]) == (
        PRODUCTION_RUNTIME_IDENTITY_SHA256
    )
    service_apply_report = fixture.evidence / "production-service-apply.json"
    assert service_apply_report.is_file()
    assert service_apply_report.read_text(encoding="utf-8") == ""

    events = _read_events(fixture)
    runtime_apply_index = events.index("runtime:production:apply")
    service_apply_index = events.index("service:production:apply")
    failure_index = events.index("failure:production-service-apply-after-runtime-apply")
    assert runtime_apply_index < service_apply_index < failure_index
    assert "runtime:production:verify" not in events
    assert "service:production:verify" not in events
    assert "images:production-tag-restored" not in events
    assert "recovery:previous-data-services-recreated" not in events
    assert "recovery:previous-public-writers-recreated" not in events
    assert "terminal:private-result-published-under-lock" not in events
    assert "terminal:global-receipt-published-under-lock" not in events
    assert "terminal:success-published-after-unlock" not in events
    assert (fixture.state / "writers-stopped").exists()


def test_executable_data_switch_failure_restores_exact_old_data_before_old_apps(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="data_switch")

    assert completed.returncode != 0
    marker = _read_marker(fixture.remote / ".cutover-failed")
    assert marker["phase"] == "switch-production-data-services-to-target-images"
    assert marker["outcome"] == "previous_release_restored_before_migration"
    assert marker["data_switch_attempted"] == "1"
    assert marker["data_services_switched"] == "0"
    assert marker["previous_data_services_restored"] == "1"
    assert marker["previous_runtime_restored"] == "1"
    events = _read_events(fixture)
    assert "failure:data-switch" in events
    assert events.index("recovery:previous-data-services-recreated") < events.index(
        "recovery:previous-public-writers-recreated"
    )
    assert "migration:production-to-0068" not in events
    assert (fixture.state / "data-generation").read_text(encoding="utf-8").strip() == ("restored")


def test_executable_failed_old_data_restore_is_honest_and_never_restarts_old_apps(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="data_switch_restore_failure")

    assert completed.returncode != 0
    marker = _read_marker(fixture.remote / ".cutover-failed")
    assert marker["outcome"] == "recovery_incomplete"
    assert marker["recovery"] == "manual_recovery_required_from_observed_state"
    assert marker["previous_data_services_restored"] == "0"
    assert marker["previous_runtime_restored"] == "0"
    events = _read_events(fixture)
    assert "failure:data-switch" in events
    assert "failure:old-data-restore" in events
    assert "recovery:previous-public-writers-recreated" not in events


def test_executable_post_migration_stop_failure_never_changes_pointer_or_tags(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="post_migration_stop")

    assert completed.returncode != 0
    marker = _read_marker(fixture.remote / ".cutover-failed")
    assert marker["outcome"] == "recovery_incomplete"
    assert marker["recovery"] == "manual_recovery_required_from_observed_state"
    assert marker["migration_started"] == "1"
    assert marker["image_tags_restored"] == "0"
    assert marker["post_migration_writer_stop_proved"] == "0"
    assert (fixture.remote / "current").resolve() == fixture.previous_release
    events = _read_events(fixture)
    assert "failure:writer-reappeared-after-migration" in events
    assert "failure:compose-writer-stop" in events
    assert "failure:docker-writer-stop" in events
    assert "images:production-tag-restored" not in events
    assert (fixture.state / "writers-reappeared").exists()


def _assert_committed_terminalization_failure(
    fixture: CutoverFixture,
    *,
    phase: str,
) -> dict[str, str]:
    marker = _read_marker(fixture.remote / ".cutover-failed")
    assert marker["status"] == "terminalization_incomplete"
    assert marker["phase"] == phase
    assert marker["outcome"] == "activation_committed_terminalization_incomplete"
    assert marker["recovery"] == "do_not_rollback_healthy_active_runtime"
    assert marker["activation_committed"] == "1"
    assert (fixture.remote / ".deploy-lock").is_dir()
    assert (fixture.remote / "current").resolve() == fixture.staged_release
    assert not _global_activation_receipt(fixture).exists()
    assert not _maintenance_env_snapshot(fixture).exists()
    assert not (fixture.evidence / "cutover-result.json").exists()
    assert (
        json.loads((fixture.evidence / "activation-commit.json").read_text(encoding="utf-8"))[
            "status"
        ]
        == "committed"
    )
    events = _read_events(fixture)
    assert "images:production-tag-restored" not in events
    assert "recovery:previous-public-writers-recreated" not in events
    return marker


def test_executable_post_commit_cleanup_failure_keeps_healthy_activation(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="commit_cleanup")

    assert completed.returncode != 0
    _assert_committed_terminalization_failure(
        fixture,
        phase="cleanup-rollback-images-and-map",
    )
    assert "failure:commit-cleanup" in _read_events(fixture)
    assert (fixture.evidence / "rollback-images.tsv").exists()


def test_executable_post_commit_unlock_failure_keeps_healthy_activation(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="commit_unlock")

    assert completed.returncode != 0
    _assert_committed_terminalization_failure(
        fixture,
        phase="release-deploy-lock",
    )
    assert "failure:commit-unlock" in _read_events(fixture)
    assert "terminal:global-receipt-published-under-lock" in _read_events(fixture)
    assert not (fixture.evidence / "rollback-images.tsv").exists()


def test_executable_global_receipt_publish_failure_keeps_lock_and_no_receipt(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="global_receipt_publish")

    assert completed.returncode != 0
    _assert_committed_terminalization_failure(
        fixture,
        phase="publish-global-activation-receipt",
    )
    events = _read_events(fixture)
    assert "terminal:private-result-published-under-lock" in events
    assert "failure:global-receipt-publish" in events
    assert "terminal:lock-released-after-global-receipt" not in events
    assert not _global_activation_receipt(fixture).exists()


def test_executable_result_cleanup_failure_is_an_explicit_locked_conflict(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="result_cleanup_failure")

    assert completed.returncode != 0
    marker = _read_marker(fixture.remote / ".cutover-failed")
    assert marker["status"] == "terminalization_incomplete"
    assert marker["phase"] == "publish-global-activation-receipt"
    assert marker["activation_committed"] == "1"
    assert (fixture.remote / ".deploy-lock").is_dir()
    assert (fixture.remote / "current").resolve() == fixture.staged_release
    assert not _global_activation_receipt(fixture).exists()
    assert (
        json.loads((fixture.evidence / "activation-commit.json").read_text(encoding="utf-8"))[
            "status"
        ]
        == "committed"
    )
    assert not (fixture.evidence / "cutover-result.json").exists()
    quarantined_results = list(fixture.evidence.glob(".conflicting-cutover-result.*.json"))
    assert len(quarantined_results) == 1
    quarantined_result = quarantined_results[0]
    assert stat.S_IMODE(quarantined_result.stat().st_mode) == 0o600
    assert json.loads(quarantined_result.read_text(encoding="utf-8"))["status"] == "passed"
    assert marker["conflicting_terminal_evidence"] == str(quarantined_result)
    assert "conflicting terminal success evidence quarantined" in completed.stderr
    events = _read_events(fixture)
    assert "failure:global-receipt-publish" in events
    assert "failure:result-cleanup" in events
    assert "terminal:result-quarantined" in events
    assert "terminal:lock-released-after-global-receipt" not in events


def test_executable_result_quarantine_failure_writes_no_ordinary_failure_marker(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="result_quarantine_failure")

    assert completed.returncode != 0
    assert not (fixture.remote / ".cutover-failed").exists()
    assert (fixture.remote / ".deploy-lock").is_dir()
    assert (fixture.remote / "current").resolve() == fixture.staged_release
    assert not _global_activation_receipt(fixture).exists()
    assert (
        json.loads((fixture.evidence / "activation-commit.json").read_text(encoding="utf-8"))[
            "status"
        ]
        == "committed"
    )
    assert (
        json.loads((fixture.evidence / "cutover-result.json").read_text(encoding="utf-8"))["status"]
        == "passed"
    )
    assert not list(fixture.evidence.glob(".conflicting-cutover-result.*.json"))
    assert "could not be atomically quarantined" in completed.stderr
    assert "no ordinary failure marker was written" in completed.stderr
    events = _read_events(fixture)
    assert "failure:global-receipt-publish" in events
    assert "failure:result-cleanup" in events
    assert "failure:result-quarantine" in events
    assert "terminal:lock-released-after-global-receipt" not in events


def test_executable_post_unlock_evidence_failure_reacquires_lock_without_rollback(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_cutover(fixture, fail_at="terminal_publish")

    assert completed.returncode != 0
    _assert_committed_terminalization_failure(
        fixture,
        phase="publish-terminal-success-evidence",
    )
    assert "failure:terminal-publish" in _read_events(fixture)
    assert not (fixture.evidence / "cutover-result.json").exists()
