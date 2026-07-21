from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = ROOT / "deploy/deploy-to-ssh-host.sh"


def _remote_deploy_body() -> str:
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    marker = "<<'EOF'\n"
    assert source.count(marker) == 1
    return source.split(marker, 1)[1].rsplit("\nEOF\n", 1)[0]


def _write(path: Path, text: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def _runtime_compose_source(*, partial: bool = False) -> str:
    if partial:
        return (
            "services:\n"
            "  api:\n"
            "    command: ${NPCINK_CLOUD_RUNTIME_PROXY_IPV4:-172.28.0.10}\n"
        )
    return """services:
  api:
    command: ${NPCINK_CLOUD_RUNTIME_PROXY_IPV4:-172.28.0.10}
  proxy:
    volumes:
      - ${NPCINK_CLOUD_RUNTIME_NGINX_CONFIG_PATH:-./deploy/nginx.prod.conf}:/nginx.conf:ro
    networks:
      default:
        ipv4_address: ${NPCINK_CLOUD_RUNTIME_PROXY_IPV4:-172.28.0.10}
networks:
  default:
    ipam:
      config:
        - subnet: ${NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET:-172.28.0.0/24}
          gateway: ${NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY:-172.28.0.1}
"""


def _stub_bundle(source: Path) -> None:
    verifier = r"""#!/usr/bin/env bash
set -euo pipefail
printf 'verify:%s:%s\n' "${1:-}" "${2:-}" >>"${CUTOVER_LOG}"
[ "${1:-}" = "--pre-load" ]
[ "${2:-}" = "$(cd "$(dirname "$0")/.." && pwd -P)" ]
if [ "${FAIL_STAGE_VERIFY:-0}" = "1" ]; then
    exit 47
fi
"""
    loader = r"""#!/usr/bin/env bash
set -euo pipefail
printf 'load:%s\n' "${NPCINK_CLOUD_LOAD_MODE:-missing}" >>"${CUTOVER_LOG}"
if [ "${NPCINK_CLOUD_LOAD_MODE:-}" = "prepare-only" ]; then
    if [ "${ABSENT_ROLLBACK_REFERENCE:-0}" = "1" ]; then
        printf 'npcink-ai-cloud-api:prod\t-\t-\n' \
            >"${NPCINK_CLOUD_ROLLBACK_IMAGE_MAP}"
    else
        {
            printf '%s\t%s\tsha256:%064d\n' \
                'npcink-ai-cloud-api:prod' 'npcink-ai-cloud-rollback:test-1' 0
            printf '%s\t%s\tsha256:%064d\n' \
                'npcink-ai-cloud-frontend:prod' 'npcink-ai-cloud-rollback:test-2' 1
            printf '%s\t%s\tsha256:%064d\n' \
                'npcink-ai-cloud-external-nginx:prod' \
                'npcink-ai-cloud-rollback:test-3' 2
            printf '%s\t%s\tsha256:%064d\n' \
                'npcink-ai-cloud-worker:prod' 'npcink-ai-cloud-rollback:test-4' 3
            printf '%s\t%s\tsha256:%064d\n' \
                'npcink-ai-cloud-callback-worker:prod' \
                'npcink-ai-cloud-rollback:test-5' 4
            printf '%s\t%s\tsha256:%064d\n' \
                'npcink-ai-cloud-ops-worker:prod' \
                'npcink-ai-cloud-rollback:test-6' 5
            printf '%s\t%s\tsha256:%064d\n' \
                'npcink-ai-cloud-postgres:prod' 'npcink-ai-cloud-rollback:test-7' 6
            printf '%s\t%s\tsha256:%064d\n' \
                'npcink-ai-cloud-external-redis:prod' \
                'npcink-ai-cloud-rollback:test-8' 7
        } >"${NPCINK_CLOUD_ROLLBACK_IMAGE_MAP}"
    fi
    chmod 0600 "${NPCINK_CLOUD_ROLLBACK_IMAGE_MAP}"
fi
if [ "${FAIL_AT:-}" = "${NPCINK_CLOUD_LOAD_MODE:-}" ]; then
    if [ -n "${PREVIOUS_RUNTIME_NETWORK_DRIFT_PATH:-}" ]; then
        printf '# injected drift\n' >>"${PREVIOUS_RUNTIME_NETWORK_DRIFT_PATH}"
    fi
    : >"${CUTOVER_FAILURE_TRIGGERED}"
    exit 42
fi
"""
    migrate = r"""#!/usr/bin/env bash
set -euo pipefail
printf 'migrate:%s\n' "${NPCINK_CLOUD_MIGRATION_ONLY:-0}" >>"${CUTOVER_LOG}"
if [ "${FAIL_AT:-}" = "migrate" ]; then
    : >"${CUTOVER_FAILURE_TRIGGERED}"
    exit 43
fi
if [ "${FAIL_AT:-}" = "oneoff_cleanup" ]; then
    mkdir -p "${ONE_OFF_LOCK_PATH}"
    : >"${CUTOVER_FAILURE_TRIGGERED}"
    exit 43
fi
"""
    refresh = r"""#!/usr/bin/env bash
set -euo pipefail
printf 'refresh:governed\n' >>"${CUTOVER_LOG}"
if [ "${FAIL_AT:-}" = "refresh" ]; then
    : >"${CUTOVER_FAILURE_TRIGGERED}"
    exit 44
fi
"""
    baseline = r"""#!/usr/bin/env bash
set -euo pipefail
printf 'baseline\n' >>"${CUTOVER_LOG}"
if [ "${FAIL_AT:-}" = "baseline" ]; then
    : >"${CUTOVER_FAILURE_TRIGGERED}"
    exit 45
fi
if [ -n "${LOCK_SENTINEL_PATH:-}" ]; then
    : >"${LOCK_SENTINEL_PATH}"
fi
"""
    operational = r"""#!/usr/bin/env bash
set -euo pipefail
printf 'operational:%s\n' "${NPCINK_CLOUD_OPERATIONAL_READY_INTERNAL:-0}" >>"${CUTOVER_LOG}"
if [ "${FAIL_AT:-}" = "operational" ]; then
    : >"${CUTOVER_FAILURE_TRIGGERED}"
    exit 46
fi
"""

    (source / "deploy").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "deploy/common.sh", source / "deploy/common.sh")
    _write(source / "deploy/verify-release-bundle.sh", verifier)
    _write(source / "deploy/remote-load-and-up.sh", loader)
    _write(source / "deploy/remote-migrate.sh", migrate)
    _write(source / "deploy/remote-refresh-providers.sh", refresh)
    _write(source / "deploy/remote-operational-ready.sh", operational)
    _write(source / "deploy/remote-baseline-status.sh", baseline)
    _write(source / "docker-compose.prod.yml", "services: {}\n")
    _write(source / "docker-compose.runtime.yml", _runtime_compose_source())


def _install_p1_e06_receipt(
    remote_dir: Path,
    active_release: Path,
    *,
    tamper_result_after_receipt: bool = False,
    omit_restore_proof: bool = False,
) -> None:
    evidence_dir = (
        remote_dir / ".release-state" / active_release.name / "p1-e06-runtime-data-cutover"
    )
    evidence_dir.mkdir(parents=True)
    (remote_dir / ".release-state").chmod(0o700)
    evidence_dir.parent.chmod(0o700)
    evidence_dir.chmod(0o700)

    activation_path = evidence_dir / "activation-commit.json"
    result_path = evidence_dir / "cutover-result.json"
    activation_path.write_text(
        json.dumps(
            {
                "contract": "p1_e06_activation_commit.v1",
                "status": "committed",
                "active_release": str(active_release),
                "database_revision": "20260717_0068",
                "runtime_legacy_rows_migrated": 18,
                "service_legacy_rows_migrated": 12,
                "legacy_rows_migrated": 30,
                "backup_sha256": "a" * 64,
                "off_host_receipt_sha256": "b" * 64,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    result_payload = {
        "contract": "p1_e06_runtime_data_encryption_cutover.v1",
        "status": "passed",
        "source_revision": "20260710_0058",
        "target_revision": "20260717_0068",
        "runtime_legacy_rows_migrated": 18,
        "service_legacy_rows_migrated": 12,
        "legacy_rows_migrated": 30,
        "backup_sha256": "a" * 64,
        "previous_release": str(remote_dir / "release-before-cutover"),
        "active_release": str(active_release),
        "off_host_receipt": str(remote_dir / "off-host-receipt.json"),
        "off_host_receipt_sha256": "b" * 64,
        "off_host_receipt_evidence": str(evidence_dir / "off-host-receipt-verified.json"),
        "off_host_copy_verified": True,
        "independent_postgres16_restore_verified": True,
        "exact_data_service_images_activated": True,
        "activation_committed": True,
        "old_code_automatically_restarted_after_failure": False,
        "whole_database_restore_required_for_rollback": True,
        "plaintext_included": False,
        "ciphertext_included": False,
        "root_secret_included": False,
    }
    if omit_restore_proof:
        result_payload.pop("independent_postgres16_restore_verified")
    result_path.write_text(
        json.dumps(result_payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    activation_path.chmod(0o600)
    result_path.chmod(0o600)
    global_path = remote_dir / ".release-state" / "p1-e06-activation.json"
    global_path.write_text(
        json.dumps(
            {
                "contract": "p1_e06_global_activation.v1",
                "status": "passed",
                "source_revision": "20260710_0058",
                "target_revision": "20260717_0068",
                "runtime_legacy_rows_migrated": 18,
                "service_legacy_rows_migrated": 12,
                "legacy_rows_migrated": 30,
                "active_release": str(active_release),
                "activation_commit_sha256": hashlib.sha256(
                    activation_path.read_bytes()
                ).hexdigest(),
                "cutover_result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    global_path.chmod(0o600)
    if tamper_result_after_receipt:
        result_path.write_text("{}\n", encoding="utf-8")
        result_path.chmod(0o600)


def _fake_docker(path: Path) -> None:
    script = r"""#!/usr/bin/env bash
set -euo pipefail
FIXTURE_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
. "${FIXTURE_ROOT}/fake-docker-config"
OLD_API_IMAGE_ID="sha256:0000000000000000000000000000000000000000000000000000000000000000"
OLD_FRONTEND_IMAGE_ID="sha256:0000000000000000000000000000000000000000000000000000000000000001"
OLD_PROXY_IMAGE_ID="sha256:0000000000000000000000000000000000000000000000000000000000000002"
OLD_WORKER_IMAGE_ID="sha256:0000000000000000000000000000000000000000000000000000000000000003"
OLD_CALLBACK_WORKER_IMAGE_ID="sha256:0000000000000000000000000000000000000000000000000000000000000004"
OLD_OPS_WORKER_IMAGE_ID="sha256:0000000000000000000000000000000000000000000000000000000000000005"
OLD_POSTGRES_IMAGE_ID="sha256:0000000000000000000000000000000000000000000000000000000000000006"
OLD_REDIS_IMAGE_ID="sha256:0000000000000000000000000000000000000000000000000000000000000007"
WRONG_RECOVERY_IMAGE_ID="sha256:8888888888888888888888888888888888888888888888888888888888888888"
printf 'docker:%s\n' "$*" >>"${CUTOVER_LOG}"
if [ "${1:-}" = "compose" ]; then
    env_file=""
    previous_arg=""
    for arg in "$@"; do
        if [ "${previous_arg}" = "--env-file" ]; then
            env_file="${arg}"
            break
        fi
        previous_arg="${arg}"
    done
    printf 'compose-shell-sentinel:%s\n' \
        "${NPCINK_CLOUD_TEST_RECOVERY_SENTINEL:-unset}" >>"${CUTOVER_LOG}"
    if [ -f "${CUTOVER_FAILURE_TRIGGERED}" ]; then
        compose_phase="recovery"
    else
        compose_phase="inspection"
    fi
    printf 'compose-network:%s:%s:%s:%s:%s\n' \
        "${compose_phase}" \
        "${NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET:-unset}" \
        "${NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY:-unset}" \
        "${NPCINK_CLOUD_RUNTIME_PROXY_IPV4:-unset}" \
        "${NPCINK_CLOUD_RUNTIME_NGINX_CONFIG_PATH:-unset}" >>"${CUTOVER_LOG}"
    if [ -n "${env_file}" ] && [ -f "${env_file}" ]; then
        awk -F= '$1=="NPCINK_CLOUD_TEST_RECOVERY_SENTINEL" {print "compose-file-sentinel:" $2}' \
            "${env_file}" >>"${CUTOVER_LOG}"
    fi
fi
if [ "${1:-}" = "ps" ] && [ -f "${CUTOVER_FAILURE_TRIGGERED}" ] && \
    [ "${RECOVERY_DOCKER_PS_FAIL:-0}" = "1" ]; then
    exit 71
fi
if [ "${1:-}" = "ps" ] && \
    [[ " $* " = *"label=com.docker.compose.service=release-one-off"* ]]; then
    exit 0
fi
if [ "${1:-}" = "info" ]; then
    exit 0
fi
if [ "${1:-}" = "compose" ] && \
    [[ " $* " = *"select version_num from alembic_version"* ]]; then
    printf '%s\n' "${DATABASE_REVISION}"
    exit 0
fi
if [ "${1:-}" = "image" ] && [ "${2:-}" = "inspect" ]; then
    inspected_reference="${*: -1}"
    if [[ "${inspected_reference}" = npcink-ai-cloud-rollback:test-* ]] && \
        [ -f "${ROLLBACK_REFERENCE_REMOVED}" ]; then
        exit 1
    fi
    if [ "${ABSENT_ROLLBACK_REFERENCE:-0}" = "1" ]; then
        [ ! -f "${ROLLBACK_REFERENCE_REMOVED}" ] || exit 1
        printf '%s\n' "${WRONG_RECOVERY_IMAGE_ID}"
    else
        case "${inspected_reference}" in
            npcink-ai-cloud-api:prod|npcink-ai-cloud-rollback:test-1)
                printf '%s\n' "${OLD_API_IMAGE_ID}" ;;
            npcink-ai-cloud-frontend:prod|npcink-ai-cloud-rollback:test-2)
                printf '%s\n' "${OLD_FRONTEND_IMAGE_ID}" ;;
            npcink-ai-cloud-external-nginx:prod|npcink-ai-cloud-rollback:test-3)
                printf '%s\n' "${OLD_PROXY_IMAGE_ID}" ;;
            npcink-ai-cloud-worker:prod|npcink-ai-cloud-rollback:test-4)
                printf '%s\n' "${OLD_WORKER_IMAGE_ID}" ;;
            npcink-ai-cloud-callback-worker:prod|npcink-ai-cloud-rollback:test-5)
                printf '%s\n' "${OLD_CALLBACK_WORKER_IMAGE_ID}" ;;
            npcink-ai-cloud-ops-worker:prod|npcink-ai-cloud-rollback:test-6)
                printf '%s\n' "${OLD_OPS_WORKER_IMAGE_ID}" ;;
            npcink-ai-cloud-postgres:prod|npcink-ai-cloud-rollback:test-7)
                printf '%s\n' "${OLD_POSTGRES_IMAGE_ID}" ;;
            npcink-ai-cloud-external-redis:prod|npcink-ai-cloud-rollback:test-8)
                printf '%s\n' "${OLD_REDIS_IMAGE_ID}" ;;
            *) exit 72 ;;
        esac
    fi
    exit 0
fi
if [ "${1:-}" = "image" ] && [ "${2:-}" = "rm" ]; then
    if [ "${FAIL_ROLLBACK_REMOVE:-0}" = "1" ]; then
        exit 62
    fi
    : >"${ROLLBACK_REFERENCE_REMOVED}"
    exit 0
fi
if [ "${1:-}" = "tag" ]; then
    exit 0
fi
if [ "${1:-}" = "compose" ] && [[ " $* " = *" up -d "* ]] && \
    [ -f "${CUTOVER_FAILURE_TRIGGERED}" ]; then
    for service_name in postgres redis proxy frontend api worker callback-worker ops-worker; do
        : >"${RECOVERY_RUNNING_STATE}/${service_name}"
    done
    if [ "${FAIL_OLD_COMPOSE_UP:-0}" = "1" ]; then
        exit 61
    fi
fi
if [ "${1:-}" = "compose" ] && [[ " $* " = *" config --services "* ]]; then
    printf '%s\n' postgres redis api frontend proxy worker callback-worker ops-worker
elif [ "${1:-}" = "compose" ] && [[ " $* " = *" config --images "* ]]; then
    printf '%s\n' \
        npcink-ai-cloud-api:prod \
        npcink-ai-cloud-frontend:prod \
        npcink-ai-cloud-external-nginx:prod \
        npcink-ai-cloud-worker:prod \
        npcink-ai-cloud-callback-worker:prod \
        npcink-ai-cloud-ops-worker:prod \
        npcink-ai-cloud-postgres:prod \
        npcink-ai-cloud-external-redis:prod
elif [ "${1:-}" = "compose" ] && [[ " $* " = *" config --format json "* ]]; then
    cat <<'JSON'
{
  "services": {
    "postgres": {"image": "npcink-ai-cloud-postgres:prod"},
    "redis": {"image": "npcink-ai-cloud-external-redis:prod"},
    "proxy": {"image": "npcink-ai-cloud-external-nginx:prod"},
    "frontend": {"image": "npcink-ai-cloud-frontend:prod"},
    "api": {"image": "npcink-ai-cloud-api:prod"},
    "worker": {"image": "npcink-ai-cloud-worker:prod"},
    "callback-worker": {"image": "npcink-ai-cloud-callback-worker:prod"},
    "ops-worker": {"image": "npcink-ai-cloud-ops-worker:prod"}
  }
}
JSON
elif [ "${1:-}" = "compose" ] && [[ " $* " = *" ps -q "* ]]; then
    service_name="${*: -1}"
    if [ "${MISSING_PREVIOUS_SERVICE:-}" != "${service_name}" ] && \
        { [ ! -f "${CUTOVER_FAILURE_TRIGGERED}" ] || \
          [ -f "${RECOVERY_RUNNING_STATE}/${service_name}" ]; }; then
        printf 'previous-%s\n' "${service_name}"
    fi
    if [ "${MULTIPLE_PREVIOUS_CONTAINERS:-0}" = "1" ] && \
        [ -f "${CUTOVER_FAILURE_TRIGGERED}" ]; then
        printf 'previous-extra-%s\n' "${service_name}"
    fi
elif [ "${1:-}" = "stop" ]; then
    service_name="${2#previous-}"
    [ -f "${RECOVERY_RUNNING_STATE}/${service_name}" ] || exit 75
elif [ "${1:-}" = "rm" ]; then
    service_name="${*: -1}"
    service_name="${service_name#previous-}"
    rm -f "${RECOVERY_RUNNING_STATE}/${service_name}"
elif [ "${1:-}" = "inspect" ]; then
    if [[ "${3:-}" = *"com.docker.compose.project"* ]]; then
        printf '%s\n' "${ACTUAL_CONTAINER_PROJECT_NAME:-npcink-ai-cloud}"
    elif [ "${3:-}" = "{{.State.Running}}" ]; then
        printf 'true\n'
    elif [ "${3:-}" = "{{.Config.Image}}" ]; then
        case "${4:-}" in
            previous-postgres) printf '%s\n' 'npcink-ai-cloud-postgres:prod' ;;
            previous-redis) printf '%s\n' 'npcink-ai-cloud-external-redis:prod' ;;
            previous-proxy) printf '%s\n' 'npcink-ai-cloud-external-nginx:prod' ;;
            previous-frontend) printf '%s\n' 'npcink-ai-cloud-frontend:prod' ;;
            previous-api) printf '%s\n' 'npcink-ai-cloud-api:prod' ;;
            previous-worker) printf '%s\n' 'npcink-ai-cloud-worker:prod' ;;
            previous-callback-worker) printf '%s\n' 'npcink-ai-cloud-callback-worker:prod' ;;
            previous-ops-worker) printf '%s\n' 'npcink-ai-cloud-ops-worker:prod' ;;
            *) exit 73 ;;
        esac
    elif [ "${3:-}" = "{{.Image}}" ]; then
        service_name="${4#previous-}"
        if [ "${RECOVERY_WRONG_IMAGE_SERVICE:-}" = "${service_name}" ] && \
            [ -f "${CUTOVER_FAILURE_TRIGGERED}" ]; then
            printf '%s\n' "${WRONG_RECOVERY_IMAGE_ID}"
        else
            case "${service_name}" in
                postgres) printf '%s\n' "${OLD_POSTGRES_IMAGE_ID}" ;;
                redis) printf '%s\n' "${OLD_REDIS_IMAGE_ID}" ;;
                proxy) printf '%s\n' "${OLD_PROXY_IMAGE_ID}" ;;
                frontend) printf '%s\n' "${OLD_FRONTEND_IMAGE_ID}" ;;
                api) printf '%s\n' "${OLD_API_IMAGE_ID}" ;;
                worker) printf '%s\n' "${OLD_WORKER_IMAGE_ID}" ;;
                callback-worker) printf '%s\n' "${OLD_CALLBACK_WORKER_IMAGE_ID}" ;;
                ops-worker) printf '%s\n' "${OLD_OPS_WORKER_IMAGE_ID}" ;;
                *) exit 74 ;;
            esac
        fi
    else
        printf 'true false 0\n'
    fi
elif [ "${1:-}" = "ps" ] && [ -f "${CUTOVER_FAILURE_TRIGGERED}" ]; then
    service_name=""
    for arg in "$@"; do
        if [[ "${arg}" = label=com.docker.compose.service=* ]]; then
            service_name="${arg#label=com.docker.compose.service=}"
            break
        fi
    done
    if [ -n "${service_name}" ] && \
        [ -f "${RECOVERY_RUNNING_STATE}/${service_name}" ]; then
        printf 'previous-%s\n' "${service_name}"
    elif [ "${RECOVERY_STILL_RUNNING:-0}" = "1" ]; then
        printf 'stuck-container\n'
    fi
fi
"""
    _write(path, script, executable=True)


def _fake_linux_file_commands(fake_bin: Path) -> None:
    stat = r"""#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "-c" ] && [ "${2:-}" = "%a" ]; then
    if /usr/bin/stat -c %a "$3" >/dev/null 2>&1; then
        exec /usr/bin/stat -c %a "$3"
    fi
    exec /usr/bin/stat -f %Lp "$3"
fi
if [ "${1:-}" = "-c" ] && [ "${2:-}" = "%u" ]; then
    printf '0\n'
    exit 0
fi
exec /usr/bin/stat "$@"
"""
    identity = r"""#!/usr/bin/env bash
set -euo pipefail
[ "${1:-}" = "-u" ] || exit 2
printf '0\n'
"""
    mv = r"""#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "-Tf" ] || [ "${1:-}" = "-fT" ]; then
    if /bin/mv -Tf "$2" "$3" 2>/dev/null; then
        exit 0
    fi
    /bin/rm -f "$3"
    exec /bin/mv -f "$2" "$3"
fi
exec /bin/mv "$@"
"""
    rm = r"""#!/usr/bin/env bash
set -euo pipefail
for candidate in "$@"; do
    if [ "${FAIL_INCOMING_CLEANUP:-0}" = "1" ] && \
        [ "${candidate}" = "${INCOMING_CLEANUP_PATH}" ]; then
        exit 63
    fi
    if [ "${FAIL_ROLLBACK_MAP_REMOVE:-0}" = "1" ] && \
        [ "${candidate}" = "${ROLLBACK_IMAGE_MAP_PATH}" ]; then
        exit 64
    fi
done
exec /bin/rm "$@"
"""
    _write(fake_bin / "stat", stat, executable=True)
    _write(fake_bin / "id", identity, executable=True)
    _write(fake_bin / "mv", mv, executable=True)
    _write(fake_bin / "rm", rm, executable=True)


def _run_remote_cutover(
    tmp_path: Path,
    fail_at: str = "",
    *,
    current_kind: str = "valid",
    old_project_name: str = "npcink-ai-cloud",
    new_project_name: str | None = None,
    fail_old_compose_up: bool = False,
    recovery_still_running: bool = False,
    recovery_docker_ps_fail: bool = False,
    multiple_previous_containers: bool = False,
    recovery_wrong_image_service: str = "",
    skip_frontend_image: bool = False,
    actual_container_project_name: str = "npcink-ai-cloud",
    missing_previous_service: str = "",
    absent_rollback_reference: bool = False,
    fail_rollback_remove: bool = False,
    fail_incoming_cleanup: bool = False,
    fail_rollback_map_remove: bool = False,
    stage_only: bool = False,
    fail_stage_verify: bool = False,
    old_env_sentinel: str = "old-value",
    new_env_sentinel: str = "",
    block_successful_unlock: bool = False,
    database_revision: str = "20260717_0068",
    require_p1_e06_receipt: bool = False,
    install_p1_e06_receipt: bool = False,
    tamper_p1_e06_result: bool = False,
    receipt_active_release_name: str = "release-previous",
    omit_p1_e06_restore_proof: bool = False,
    descendant_revision: str = "",
    preexisting_one_off_lock: bool = False,
    previous_runtime_network_contract: bool = False,
    runtime_network_state_variant: str = "valid",
    drift_previous_runtime_network_after_failure: bool = False,
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    remote_dir = tmp_path / "remote"
    incoming = remote_dir / ".incoming" / "test-upload"
    previous = remote_dir / "release-previous"
    bundle_source = tmp_path / "bundle-source"
    fake_bin = tmp_path / "bin"
    bundle = incoming / "deploy-bundle.tgz"
    log = tmp_path / "cutover.log"
    failure_triggered = tmp_path / "cutover-failure-triggered"
    rollback_reference_removed = tmp_path / "rollback-reference-removed"
    recovery_running_state = tmp_path / "recovery-running"

    incoming.mkdir(parents=True)
    previous.mkdir(parents=True)
    fake_bin.mkdir()
    recovery_running_state.mkdir()
    (previous / ".env.deploy").write_text(
        f"NPCINK_CLOUD_COMPOSE_PROJECT_NAME={old_project_name}\n"
        f"NPCINK_CLOUD_TEST_RECOVERY_SENTINEL={old_env_sentinel}\n",
        encoding="utf-8",
    )
    (previous / ".env.deploy").chmod(0o600)
    (previous / "docker-compose.prod.yml").write_text("services: {}\n", encoding="utf-8")
    if previous_runtime_network_contract:
        partial_compose = runtime_network_state_variant == "partial-compose"
        (previous / "docker-compose.runtime.yml").write_text(
            _runtime_compose_source(partial=partial_compose),
            encoding="utf-8",
        )
        nginx_source = (
            "events {}\n"
            "http {\n"
            "    set_real_ip_from 172.28.0.1;\n"
            "}\n"
        )
        _write(previous / "deploy/nginx.prod.conf", nginx_source)
        if runtime_network_state_variant != "missing":
            previous_state = remote_dir / ".release-state" / previous.name
            previous_state.mkdir(parents=True)
            (remote_dir / ".release-state").chmod(0o700)
            previous_state.chmod(0o700)
            project_name = old_project_name
            subnet = "10.255.1.0/24"
            gateway = "10.255.1.1"
            proxy_ipv4 = "10.255.1.9"
            if runtime_network_state_variant == "project-mismatch":
                project_name = "another-project"
            elif runtime_network_state_variant == "invalid-ipv4":
                subnet = "10.255.1.0/33"
            state_file = previous_state / "runtime-network.env"
            state_file.write_text(
                "NPCINK_CLOUD_RUNTIME_NETWORK_PROJECT=" f"{project_name}\n"
                "NPCINK_CLOUD_RUNTIME_NETWORK_SUBNET=" f"{subnet}\n"
                "NPCINK_CLOUD_RUNTIME_NETWORK_GATEWAY=" f"{gateway}\n"
                "NPCINK_CLOUD_RUNTIME_PROXY_IPV4=" f"{proxy_ipv4}\n",
                encoding="utf-8",
            )
            state_file.chmod(0o600)
            rendered_nginx = nginx_source.replace("172.28.0.1", gateway)
            if runtime_network_state_variant == "nginx-mismatch":
                rendered_nginx = nginx_source
            nginx_file = previous_state / "nginx.runtime.conf"
            nginx_file.write_text(rendered_nginx, encoding="utf-8")
            nginx_file.chmod(0o600)
            if runtime_network_state_variant == "state-mode":
                state_file.chmod(0o644)
    current_target = previous
    if current_kind == "broken":
        current_target = remote_dir / "missing-release"
    elif current_kind == "nested":
        current_target = previous / "release-nested"
        current_target.mkdir()
    if current_kind != "absent":
        (remote_dir / "current").symlink_to(current_target)
    if install_p1_e06_receipt:
        _install_p1_e06_receipt(
            remote_dir,
            remote_dir / receipt_active_release_name,
            tamper_result_after_receipt=tamper_p1_e06_result,
            omit_restore_proof=omit_p1_e06_restore_proof,
        )
    if preexisting_one_off_lock:
        one_off_lock = remote_dir / ".release-state" / ".release-one-off.lock"
        one_off_lock.mkdir(parents=True, mode=0o700)
        (remote_dir / ".release-state").chmod(0o700)
    _stub_bundle(bundle_source)
    if descendant_revision:
        _write(
            bundle_source / "migrations" / "versions" / f"{descendant_revision}_fixture.py",
            f'revision: str = "{descendant_revision}"\ndown_revision: str = "20260717_0068"\n',
        )
    _fake_docker(fake_bin / "docker")
    _fake_linux_file_commands(fake_bin)
    _write(fake_bin / "curl", "#!/usr/bin/env bash\nexit 0\n", executable=True)

    with tarfile.open(bundle, "w:gz") as archive:
        for item in sorted(bundle_source.rglob("*")):
            archive.add(item, arcname=item.relative_to(bundle_source))

    remote_body = tmp_path / "remote-deploy-body.sh"
    _write(remote_body, _remote_deploy_body(), executable=True)

    uploaded_env = ""
    if new_project_name is not None or new_env_sentinel:
        uploaded_env_path = incoming / "uploaded.env"
        uploaded_env_path.write_text(
            "NPCINK_CLOUD_COMPOSE_PROJECT_NAME="
            f"{new_project_name or old_project_name}\n"
            "NPCINK_CLOUD_TEST_RECOVERY_SENTINEL="
            f"{new_env_sentinel or old_env_sentinel}\n",
            encoding="utf-8",
        )
        uploaded_env_path.chmod(0o600)
        uploaded_env = str(uploaded_env_path)

    if stage_only:
        args = [
            "stage-only",
            str(remote_dir),
            "release-next",
            str(bundle),
            str(incoming),
            sys.executable,
        ]
    else:
        protected_input = incoming / "deploy-input.json"
        protected_input.write_text(
            json.dumps(
                {
                    "REMOTE_ENV_BASENAME": ".env.deploy",
                    "SITE_ID": "site-test",
                    "KEY_ID": "key-test",
                    "SECRET": "test-secret",
                    "SCOPES": "catalog:read",
                    "BASE_URL": "http://127.0.0.1:8010",
                    "PROFILE_ID": "text.balanced",
                    "ABILITY_NAME": "test/ability",
                    "EXECUTION_KIND": "text",
                    "IDEMPOTENCY_SUFFIX": "",
                    "PROMPT_TEXT": "test prompt",
                    "EXPECTED_PROVIDER_ID": "",
                    "EXPECTED_MODEL_ID": "",
                    "EXPECTED_INSTANCE_ID": "",
                    "MEMBER_EMAIL": "",
                    "SKIP_SEED": "1",
                    "SKIP_SMOKE": "1",
                    "REMOTE_ENV_PATH": uploaded_env,
                    "WITH_PORTAL_SMOKE": "0",
                    "SKIP_FRONTEND_IMAGE": "1" if skip_frontend_image else "0",
                    "REMOTE_COMPOSE_FILE": (
                        "docker-compose.runtime.yml"
                        if previous_runtime_network_contract
                        else ""
                    ),
                    "REFRESH_PROVIDERS": "1",
                    "WITH_OPERATIONAL_READY": "0",
                    "REQUIRE_P1_E06_RECEIPT": ("1" if require_p1_e06_receipt else "0"),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        protected_input.chmod(0o600)
        args = [
            "deploy",
            str(remote_dir),
            "release-next",
            str(bundle),
            str(incoming),
            sys.executable,
        ]
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "CUTOVER_LOG": str(log),
            "FAIL_AT": fail_at,
            "CUTOVER_FAILURE_TRIGGERED": str(failure_triggered),
            "FAIL_OLD_COMPOSE_UP": "1" if fail_old_compose_up else "0",
            "RECOVERY_STILL_RUNNING": "1" if recovery_still_running else "0",
            "RECOVERY_DOCKER_PS_FAIL": "1" if recovery_docker_ps_fail else "0",
            "MULTIPLE_PREVIOUS_CONTAINERS": ("1" if multiple_previous_containers else "0"),
            "RECOVERY_WRONG_IMAGE_SERVICE": recovery_wrong_image_service,
            "RECOVERY_RUNNING_STATE": str(recovery_running_state),
            "ACTUAL_CONTAINER_PROJECT_NAME": actual_container_project_name,
            "MISSING_PREVIOUS_SERVICE": missing_previous_service,
            "ABSENT_ROLLBACK_REFERENCE": "1" if absent_rollback_reference else "0",
            "FAIL_ROLLBACK_REMOVE": "1" if fail_rollback_remove else "0",
            "FAIL_INCOMING_CLEANUP": "1" if fail_incoming_cleanup else "0",
            "INCOMING_CLEANUP_PATH": str(incoming),
            "FAIL_ROLLBACK_MAP_REMOVE": ("1" if fail_rollback_map_remove else "0"),
            "ROLLBACK_IMAGE_MAP_PATH": str(
                remote_dir / ".release-state" / "release-next" / "rollback-images.tsv"
            ),
            "FAIL_STAGE_VERIFY": "1" if fail_stage_verify else "0",
            "ROLLBACK_REFERENCE_REMOVED": str(rollback_reference_removed),
            "LOCK_SENTINEL_PATH": (
                str(remote_dir / ".deploy-lock" / "injected-sentinel")
                if block_successful_unlock
                else ""
            ),
            "DATABASE_REVISION": database_revision,
            "ONE_OFF_LOCK_PATH": str(
                remote_dir / ".release-state" / ".release-one-off.lock"
            ),
            "PREVIOUS_RUNTIME_NETWORK_DRIFT_PATH": (
                str(
                    remote_dir
                    / ".release-state"
                    / previous.name
                    / "runtime-network.env"
                )
                if drift_previous_runtime_network_after_failure
                else ""
            ),
        }
    )
    fake_config = {
        "ABSENT_ROLLBACK_REFERENCE": "1" if absent_rollback_reference else "0",
        "ACTUAL_CONTAINER_PROJECT_NAME": actual_container_project_name,
        "CUTOVER_FAILURE_TRIGGERED": str(failure_triggered),
        "CUTOVER_LOG": str(log),
        "DATABASE_REVISION": database_revision,
        "FAIL_OLD_COMPOSE_UP": "1" if fail_old_compose_up else "0",
        "FAIL_ROLLBACK_REMOVE": "1" if fail_rollback_remove else "0",
        "MISSING_PREVIOUS_SERVICE": missing_previous_service,
        "MULTIPLE_PREVIOUS_CONTAINERS": ("1" if multiple_previous_containers else "0"),
        "RECOVERY_WRONG_IMAGE_SERVICE": recovery_wrong_image_service,
        "RECOVERY_RUNNING_STATE": str(recovery_running_state),
        "RECOVERY_DOCKER_PS_FAIL": "1" if recovery_docker_ps_fail else "0",
        "RECOVERY_STILL_RUNNING": "1" if recovery_still_running else "0",
        "ROLLBACK_REFERENCE_REMOVED": str(rollback_reference_removed),
    }
    _write(
        tmp_path / "fake-docker-config",
        "".join(f"{key}={shlex.quote(value)}\n" for key, value in fake_config.items()),
    )
    completed = subprocess.run(
        ["bash", str(remote_body), *args],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    return completed, remote_dir, log


def _assert_recovery_generation_was_refenced(tmp_path: Path, log_path: Path) -> None:
    services = (
        "postgres",
        "redis",
        "proxy",
        "frontend",
        "api",
        "worker",
        "callback-worker",
        "ops-worker",
    )
    assert list((tmp_path / "recovery-running").iterdir()) == []
    log = log_path.read_text(encoding="utf-8")
    for service in services:
        assert f"docker:stop --time 10 previous-{service}" in log
        assert f"docker:rm -f previous-{service}" in log


def test_atomic_cutover_command_order_and_one_off_modes() -> None:
    deploy = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    loader = (ROOT / "deploy/remote-load-and-up.sh").read_text(encoding="utf-8")
    migrate = (ROOT / "deploy/remote-migrate.sh").read_text(encoding="utf-8")
    refresh = (ROOT / "deploy/remote-refresh-providers.sh").read_text(encoding="utf-8")

    ordered_markers = [
        'CUTOVER_PHASE="prepare-release-images"',
        "NPCINK_CLOUD_LOAD_MODE=prepare-only",
        'CUTOVER_PHASE="stop-old-application-services"',
        'remote_run_timed "assert application services stopped"',
        "NPCINK_CLOUD_LOAD_MODE=data-only",
        "MIGRATION_STARTED=1",
        'CUTOVER_PHASE="refresh-provider-projections-with-staged-image"',
        "bash deploy/remote-refresh-providers.sh </dev/null",
        'CUTOVER_PHASE="activate-new-release-pointer"',
        'atomic_set_current "${RELEASE_DIR}"',
        "NPCINK_CLOUD_LOAD_MODE=api-only",
        "NPCINK_CLOUD_LOAD_MODE=workers-only",
        "NPCINK_CLOUD_OPERATIONAL_READY_INTERNAL=1",
        "NPCINK_CLOUD_LOAD_MODE=traffic-only",
        'remote_run_timed "remote baseline status"',
        'CUTOVER_PHASE="finalize-current-release"',
    ]
    positions = [deploy.index(marker) for marker in ordered_markers]
    assert positions == sorted(positions)

    assert "prepare-only|data-only|api-only|workers-only|traffic-only" in loader
    api_start = loader.index("create, prove, and start exact staged API")
    api_ready = loader.index("wait for staged API internal readiness")
    workers_start = loader.index("create, prove, and start exact workers")
    traffic_start = loader.index("create, prove, and start exact frontend and proxy")
    public_health = loader.index("\twait_for_public_health", traffic_start)
    assert api_start < api_ready < workers_start < traffic_start < public_health
    assert "up -d --pull never --no-build" not in loader
    assert 'docker start "${container_ids_to_start[@]}"' in loader
    assert "loaded-role-daemon-id" in migrate
    assert "npcink_ai_cloud_compose_run_with_image_proof" in migrate
    assert "run --rm --no-deps --pull never" not in migrate
    assert "NPCINK_CLOUD_MIGRATION_ONLY" not in migrate
    assert "up -d --pull never --no-build" not in migrate
    assert "worker callback-worker ops-worker" not in migrate
    assert "loaded-role-daemon-id" in refresh
    assert "npcink_ai_cloud_compose_run_with_image_proof" in refresh
    assert "run --rm --no-deps --pull never" not in refresh
    assert "exec -T api" not in refresh
    assert "NPCINK_CLOUD_REFRESH_PROVIDERS_ONE_OFF" not in refresh
    assert "NPCINK_CLOUD_REFRESH_PROVIDERS_ONE_OFF" not in deploy

    gate = deploy.index("\nassert_p1_e06_ordinary_deploy_gate\n")
    first_image_mutation = deploy.index('CUTOVER_PHASE="prepare-release-images"')
    assert gate < first_image_mutation
    assert "APPLICATION_SERVICES=(caddy proxy)" in deploy
    assert 'if [ "${SKIP_FRONTEND_IMAGE}" != "1" ]; then' in deploy
    assert "APPLICATION_SERVICES+=(frontend)" in deploy
    assert "APPLICATION_SERVICES+=(api worker callback-worker ops-worker" in deploy
    assert "release-one-off)" in deploy
    assert 'GLOBAL_ONE_OFF_LOCK_DIR="${RELEASE_STATE_ROOT}/.release-one-off.lock"' in deploy
    assert "assert_governed_one_off_absent" in deploy
    assert 'if [ "${SKIP_FRONTEND_IMAGE}" != "1" ]; then' in loader
    assert "SERVICES+=(frontend)" in loader
    assert "{{json .}}" not in deploy
    assert "{{json .}}" not in (ROOT / "deploy/remote-operational-ready.sh").read_text(
        encoding="utf-8"
    )
    assert '{{index .Config.Labels "com.docker.compose.project"}}' in deploy
    readiness = (ROOT / "deploy/remote-operational-ready.sh").read_text(encoding="utf-8")
    for field in (
        "{{.State.Running}}",
        "{{.State.Restarting}}",
        "{{.RestartCount}}",
        "{{.State.StartedAt}}",
    ):
        assert field in readiness


def test_formal_production_workflow_requires_p1_e06_receipt() -> None:
    workflow = (ROOT / ".github/workflows/deploy-production.yml").read_text(encoding="utf-8")
    assert 'NPCINK_CLOUD_REQUIRE_P1_E06_RECEIPT: "1"' in workflow
    deploy = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    workspace_target = (ROOT / "deploy/workspace-target.env.sh").read_text(encoding="utf-8")
    assert "NPCINK_CLOUD_REQUIRE_P1_E06_RECEIPT:-1" in deploy
    assert '"REQUIRE_P1_E06_RECEIPT": "REQUIRE_P1_E06_RECEIPT"' in deploy
    assert "Ordinary production deployment cannot migrate revision 0058" in deploy
    assert "Full deployment cannot disable" in deploy
    assert 'chmod 0700 "${DEPLOY_LOCK_DIR}"' in deploy
    assert "stat -c '%u' \"${DEPLOY_LOCK_DIR}\"" in deploy
    assert "stat -c '%a' \"${DEPLOY_LOCK_DIR}\"" in deploy
    assert 'NPCINK_CLOUD_REQUIRE_P1_E06_RECEIPT="1"' in workspace_target


def test_full_deploy_cli_cannot_disable_p1_e06_receipt_gate() -> None:
    env = os.environ.copy()
    env.update(
        {
            "NPCINK_CLOUD_BASE_URL": "https://CLOUD.NPC.INK.",
            "NPCINK_CLOUD_REQUIRE_P1_E06_RECEIPT": "0",
        }
    )
    completed = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "Full deployment cannot disable" in completed.stderr


def test_stage_only_extracts_and_verifies_without_runtime_mutation(
    tmp_path: Path,
) -> None:
    completed, remote_dir, log_path = _run_remote_cutover(
        tmp_path,
        stage_only=True,
    )

    staged_release = remote_dir / "release-next"
    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
    assert f"staged_release={staged_release.resolve()}\n" in completed.stdout
    assert staged_release.is_dir()
    assert (remote_dir / "current").resolve() == remote_dir / "release-previous"
    assert not (remote_dir / ".release-state").exists()
    assert not (remote_dir / ".cutover-failed").exists()
    assert not (remote_dir / ".deploy-lock").exists()
    assert not (remote_dir / ".incoming" / "test-upload").exists()
    log = log_path.read_text(encoding="utf-8")
    assert log == f"verify:--pre-load:{staged_release.resolve()}\n"
    log_lines = log.splitlines()
    for forbidden in ("docker:", "load:", "migrate:", "operational:", "baseline"):
        assert not any(line.startswith(forbidden) for line in log_lines)


def test_stage_only_verification_failure_cleans_without_runtime_mutation(
    tmp_path: Path,
) -> None:
    completed, remote_dir, log_path = _run_remote_cutover(
        tmp_path,
        stage_only=True,
        fail_stage_verify=True,
    )

    assert completed.returncode == 47
    assert "staged_release=" not in completed.stdout
    assert not (remote_dir / "release-next").exists()
    assert (remote_dir / "current").resolve() == remote_dir / "release-previous"
    assert not (remote_dir / ".release-state").exists()
    assert not (remote_dir / ".cutover-failed").exists()
    assert not (remote_dir / ".deploy-lock").exists()
    assert not (remote_dir / ".incoming" / "test-upload").exists()
    log = log_path.read_text(encoding="utf-8")
    assert "verify:--pre-load:" in log
    log_lines = log.splitlines()
    for forbidden in ("docker:", "load:", "migrate:", "operational:", "baseline"):
        assert not any(line.startswith(forbidden) for line in log_lines)


def test_stage_only_rejects_env_before_ssh(tmp_path: Path) -> None:
    env_file = tmp_path / "deploy.env"
    env_file.write_text("SECRET=must-not-upload\n", encoding="utf-8")
    env = os.environ.copy()
    env["NPCINK_CLOUD_ENV_FILE"] = ""

    completed = subprocess.run(
        [
            "bash",
            str(DEPLOY_SCRIPT),
            "--stage-only",
            "--ssh-host",
            "not-contacted.invalid",
            "--env-file",
            str(env_file),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "--stage-only does not accept an env file" in completed.stderr
    assert "SSH target is not reachable" not in completed.stderr


def test_internal_readiness_probe_uses_production_trusted_host(tmp_path: Path) -> None:
    capture_path = tmp_path / "request-headers.json"
    sitecustomize = r"""
from __future__ import annotations

import json
import os
import urllib.request

class Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

def urlopen(request, timeout=0):
    headers = {key.lower(): value for key, value in request.header_items()}
    with open(os.environ["PROBE_CAPTURE"], "w", encoding="utf-8") as handle:
        json.dump(headers, handle)
    return Response()

urllib.request.urlopen = urlopen
"""
    _write(tmp_path / "sitecustomize.py", sitecustomize)
    shell = r"""
set -euo pipefail
. deploy/common.sh
npcink_ai_cloud_compose() {
    local _root="$1"
    shift
    [ "$1" = exec ]; shift
    [ "$1" = -T ]; shift
    [ "$1" = api ]; shift
    [ "$1" = python ]; shift
    "${PROBE_PYTHON}" "$@"
}
npcink_ai_cloud_wait_for_internal_endpoint \
    "$PWD" "/health/ready" "probe passed"
"""
    env = os.environ.copy()
    env.update(
        {
            "NPCINK_CLOUD_DOMAIN_NAME": "cloud.npc.ink",
            "NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST": "wrong.example",
            "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN": "internal-test-token",
            "PROBE_CAPTURE": str(capture_path),
            "PROBE_PYTHON": sys.executable,
            "PYTHONPATH": str(tmp_path),
        }
    )
    completed = subprocess.run(
        ["bash", "-c", shell],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    received_headers = json.loads(capture_path.read_text(encoding="utf-8"))
    assert received_headers == {
        "host": "cloud.npc.ink",
        "x-npcink-internal-token": "internal-test-token",
    }


@pytest.mark.parametrize(
    ("heartbeat_time", "change_container_ids", "expected_error"),
    [
        (
            "2026-07-20T00:00:00.500000Z",
            False,
            "New worker heartbeat proof did not pass",
        ),
        (
            "2026-07-20T00:00:02.500000Z",
            True,
            "Worker container changed during the stability window",
        ),
    ],
)
def test_cutover_worker_proof_rejects_stale_heartbeat_or_replaced_container(
    tmp_path: Path,
    heartbeat_time: str,
    change_container_ids: bool,
    expected_error: str,
) -> None:
    release = tmp_path / "release-next"
    state_dir = tmp_path / ".release-state" / "release-next"
    fake_bin = tmp_path / "bin"
    release.joinpath("deploy").mkdir(parents=True)
    state_dir.mkdir(parents=True)
    fake_bin.mkdir()
    shutil.copy2(ROOT / "deploy/common.sh", release / "deploy/common.sh")
    shutil.copy2(
        ROOT / "deploy/remote-operational-ready.sh",
        release / "deploy/remote-operational-ready.sh",
    )
    (release / "docker-compose.prod.yml").write_text("services: {}\n", encoding="utf-8")
    (state_dir / "env.deploy").write_text(
        "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN=internal-test-token\n"
        "NPCINK_CLOUD_COMPOSE_PROJECT_NAME=npcink-ai-cloud\n",
        encoding="utf-8",
    )
    state_dir.chmod(0o700)
    (state_dir / "env.deploy").chmod(0o600)

    docker = r"""#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "compose" ] && [[ " $* " = *" ps -q "* ]]; then
    service_name="${*: -1}"
    marker="${ID_CALL_DIR}/${service_name}"
    if [ "${CHANGE_CONTAINER_IDS:-0}" = "1" ] && [ -f "${marker}" ]; then
        printf 'changed-%s\n' "${service_name}"
    else
        : >"${marker}"
        printf 'new-%s\n' "${service_name}"
    fi
    exit 0
fi
if [ "${1:-}" = "inspect" ]; then
    case "${3:-}" in
        '{{.State.Running}}') printf 'true\n' ;;
        '{{.State.Restarting}}') printf 'false\n' ;;
        '{{.RestartCount}}') printf '0\n' ;;
        '{{.State.StartedAt}}') printf '2026-07-20T00:00:02.000000Z\n' ;;
        *) exit 71 ;;
    esac
    exit 0
fi
if [ "${1:-}" = "compose" ] && [[ " $* " = *" exec -T api python - "* ]]; then
    while [ "$#" -gt 0 ] && [ "$1" != "python" ]; do shift; done
    shift
    [ "$1" = "-" ]
    shift
    exec "${PROBE_PYTHON}" - "$@"
fi
echo "unexpected docker command: $*" >&2
exit 70
"""
    _write(fake_bin / "docker", docker, executable=True)

    sitecustomize = r"""
from __future__ import annotations

import json
import os
import urllib.request

class Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, *_args):
        workers = ("runtime_queue", "callback_dispatch", "ops_cadence")
        return json.dumps(
            {
                "data": {
                    "workers": {
                        "items": [
                            {
                                "worker_id": worker_id,
                                "freshness": "fresh",
                                "last_seen_at": os.environ["HEARTBEAT_TIME"],
                            }
                            for worker_id in workers
                        ]
                    }
                }
            }
        ).encode("utf-8")

urllib.request.urlopen = lambda *_args, **_kwargs: Response()
"""
    _write(tmp_path / "sitecustomize.py", sitecustomize)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "PROBE_PYTHON": sys.executable,
            "PYTHONPATH": str(tmp_path),
            "ID_CALL_DIR": str(tmp_path),
            "CHANGE_CONTAINER_IDS": "1" if change_container_ids else "0",
            "HEARTBEAT_TIME": heartbeat_time,
            "NPCINK_CLOUD_OPERATIONAL_READY_INTERNAL": "1",
            "NPCINK_CLOUD_WORKER_READINESS_ATTEMPTS": "1",
            "NPCINK_CLOUD_WORKER_READINESS_SLEEP_SECONDS": "0",
            "NPCINK_CLOUD_WORKER_STABILITY_SECONDS": "0",
        }
    )
    completed = subprocess.run(
        [
            "bash",
            str(release / "deploy/remote-operational-ready.sh"),
            "--worker-cutoff",
            "2026-07-20T00:00:01.000000Z",
        ],
        cwd=release,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert expected_error in completed.stderr
    if not change_container_ids:
        assert "runtime_queue" in completed.stderr


def test_successful_cutover_uses_staged_commands_in_order(tmp_path: Path) -> None:
    completed, remote_dir, log_path = _run_remote_cutover(tmp_path)

    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
    log = log_path.read_text(encoding="utf-8")
    ordered = [
        "load:prepare-only",
        "load:data-only",
        "migrate:0",
        "refresh:governed",
        "load:api-only",
        "load:workers-only",
        "operational:1",
        "load:traffic-only",
        "baseline",
    ]
    positions = [log.index(marker) for marker in ordered]
    assert positions == sorted(positions)
    assert (remote_dir / "current").resolve() == remote_dir / "release-next"
    assert not (remote_dir / ".cutover-failed").exists()
    release_state = remote_dir / ".release-state" / "release-next"
    assert release_state.stat().st_mode & 0o777 == 0o700
    assert (release_state / "env.deploy").stat().st_mode & 0o777 == 0o600
    assert not (remote_dir / "release-next" / ".env.deploy").exists()
    assert not (release_state / "rollback-images.tsv").exists()
    assert not (remote_dir / ".deploy-lock").exists()


def test_ordinary_deploy_blocks_0058_before_any_image_mutation(tmp_path: Path) -> None:
    completed, remote_dir, log_path = _run_remote_cutover(
        tmp_path,
        database_revision="20260710_0058",
    )

    assert completed.returncode != 0
    assert "cannot migrate revision 0058" in completed.stderr
    assert "load:" not in log_path.read_text(encoding="utf-8")
    assert (remote_dir / "current").resolve() == remote_dir / "release-previous"


def test_ordinary_full_deploy_without_current_is_never_an_implicit_bootstrap(
    tmp_path: Path,
) -> None:
    completed, _remote_dir, log_path = _run_remote_cutover(
        tmp_path,
        current_kind="absent",
        new_project_name="npcink-ai-cloud",
        database_revision="20260710_0058",
    )

    assert completed.returncode != 0
    assert "requires an existing managed current release" in completed.stderr
    log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    assert "load:" not in log


def test_formal_production_deploy_requires_global_p1_e06_receipt(
    tmp_path: Path,
) -> None:
    completed, _remote_dir, log_path = _run_remote_cutover(
        tmp_path,
        require_p1_e06_receipt=True,
    )

    assert completed.returncode != 0
    assert "Global P1-E06 receipt" in completed.stderr
    assert "load:" not in log_path.read_text(encoding="utf-8")


def test_formal_production_deploy_accepts_bound_p1_e06_receipt(
    tmp_path: Path,
) -> None:
    completed, remote_dir, _log_path = _run_remote_cutover(
        tmp_path,
        require_p1_e06_receipt=True,
        install_p1_e06_receipt=True,
    )

    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
    assert (remote_dir / "current").resolve() == remote_dir / "release-next"
    assert "Governed P1-E06 activation evidence matches" in completed.stdout


def test_formal_production_deploy_accepts_receipt_from_original_cutover_release(
    tmp_path: Path,
) -> None:
    completed, remote_dir, _log_path = _run_remote_cutover(
        tmp_path,
        require_p1_e06_receipt=True,
        install_p1_e06_receipt=True,
        receipt_active_release_name="release-original-cutover",
    )

    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
    assert (remote_dir / "current").resolve() == remote_dir / "release-next"


def test_formal_production_deploy_accepts_migration_graph_descendant_of_0068(
    tmp_path: Path,
) -> None:
    completed, remote_dir, _log_path = _run_remote_cutover(
        tmp_path,
        database_revision="20260718_0069",
        descendant_revision="20260718_0069",
        require_p1_e06_receipt=True,
        install_p1_e06_receipt=True,
    )

    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
    assert (remote_dir / "current").resolve() == remote_dir / "release-next"


def test_formal_production_deploy_rejects_unproved_revision_descendant(
    tmp_path: Path,
) -> None:
    completed, _remote_dir, log_path = _run_remote_cutover(
        tmp_path,
        database_revision="20260718_0069",
        require_p1_e06_receipt=True,
        install_p1_e06_receipt=True,
    )

    assert completed.returncode != 0
    assert "not 0068 or a migration-graph descendant" in completed.stderr
    assert "load:" not in log_path.read_text(encoding="utf-8")


def test_formal_production_deploy_rejects_tampered_p1_e06_evidence(
    tmp_path: Path,
) -> None:
    completed, _remote_dir, log_path = _run_remote_cutover(
        tmp_path,
        require_p1_e06_receipt=True,
        install_p1_e06_receipt=True,
        tamper_p1_e06_result=True,
    )

    assert completed.returncode != 0
    assert "cutover result digest mismatch" in completed.stderr
    assert "load:" not in log_path.read_text(encoding="utf-8")


def test_formal_production_deploy_rejects_digest_bound_but_incomplete_evidence(
    tmp_path: Path,
) -> None:
    completed, _remote_dir, log_path = _run_remote_cutover(
        tmp_path,
        require_p1_e06_receipt=True,
        install_p1_e06_receipt=True,
        omit_p1_e06_restore_proof=True,
    )

    assert completed.returncode != 0
    assert "cutover result schema mismatch" in completed.stderr
    assert "load:" not in log_path.read_text(encoding="utf-8")


def test_successful_activation_reports_unlock_failure_and_retains_lock(
    tmp_path: Path,
) -> None:
    completed, remote_dir, _log_path = _run_remote_cutover(
        tmp_path,
        block_successful_unlock=True,
    )

    assert completed.returncode == 1
    assert (remote_dir / "current").resolve() == remote_dir / "release-next"
    assert (remote_dir / ".deploy-lock" / "injected-sentinel").is_file()
    assert (remote_dir / ".release-state" / "release-next" / "rollback-images.tsv").is_file()
    marker = (remote_dir / ".cutover-failed").read_text(encoding="utf-8")
    assert "phase=finalize-deploy-lock-release" in marker
    assert "outcome=post_commit_cleanup_incomplete" in marker
    assert "Deployment lock release could not be proved" in completed.stderr
    assert "Remote release ready" not in completed.stdout


def test_post_commit_incoming_cleanup_failure_is_fail_closed(tmp_path: Path) -> None:
    completed, remote_dir, log_path = _run_remote_cutover(
        tmp_path,
        fail_incoming_cleanup=True,
    )

    release_state = remote_dir / ".release-state" / "release-next"
    assert completed.returncode != 0
    assert (remote_dir / "current").resolve() == remote_dir / "release-next"
    assert (release_state / "rollback-images.tsv").is_file()
    assert (remote_dir / ".deploy-lock").is_dir()
    marker = (remote_dir / ".cutover-failed").read_text(encoding="utf-8")
    assert "phase=finalize-incoming-cleanup" in marker
    assert "outcome=post_commit_cleanup_incomplete" in marker
    assert "protected incoming cleanup could not be proved" in completed.stderr
    assert "Deployment lock retained for operator recovery" in completed.stderr
    assert "Remote release ready" not in completed.stdout
    assert "restore previous release services" not in completed.stdout
    assert " up -d --pull never --no-build --force-recreate --remove-orphans" not in (
        log_path.read_text(encoding="utf-8")
    )


def test_post_commit_rollback_tag_cleanup_failure_is_fail_closed(
    tmp_path: Path,
) -> None:
    completed, remote_dir, log_path = _run_remote_cutover(
        tmp_path,
        fail_rollback_remove=True,
    )

    release_state = remote_dir / ".release-state" / "release-next"
    assert completed.returncode != 0
    assert (remote_dir / "current").resolve() == remote_dir / "release-next"
    assert (release_state / "rollback-images.tsv").is_file()
    assert (remote_dir / ".deploy-lock").is_dir()
    marker = (remote_dir / ".cutover-failed").read_text(encoding="utf-8")
    assert "phase=finalize-rollback-image-tags" in marker
    assert "outcome=post_commit_cleanup_incomplete" in marker
    assert "Rollback image tag still exists after cleanup" in completed.stderr
    assert "Deployment lock retained for operator recovery" in completed.stderr
    assert "Remote release ready" not in completed.stdout
    assert "restore previous release services" not in completed.stdout
    assert " up -d --pull never --no-build --force-recreate --remove-orphans" not in (
        log_path.read_text(encoding="utf-8")
    )


def test_post_commit_rollback_map_cleanup_failure_is_fail_closed(
    tmp_path: Path,
) -> None:
    completed, remote_dir, log_path = _run_remote_cutover(
        tmp_path,
        fail_rollback_map_remove=True,
    )

    release_state = remote_dir / ".release-state" / "release-next"
    assert completed.returncode != 0
    assert (remote_dir / "current").resolve() == remote_dir / "release-next"
    assert (release_state / "rollback-images.tsv").is_file()
    assert (remote_dir / ".deploy-lock").is_dir()
    marker = (remote_dir / ".cutover-failed").read_text(encoding="utf-8")
    assert "phase=finalize-rollback-image-map" in marker
    assert "outcome=post_commit_cleanup_incomplete" in marker
    assert "rollback image map cleanup could not be proved" in completed.stderr
    assert "Deployment lock retained for operator recovery" in completed.stderr
    assert "Remote release ready" not in completed.stdout
    assert "restore previous release services" not in completed.stdout
    assert " up -d --pull never --no-build --force-recreate --remove-orphans" not in (
        log_path.read_text(encoding="utf-8")
    )


def test_backend_only_cutover_preserves_existing_frontend_container(
    tmp_path: Path,
) -> None:
    completed, _remote_dir, log_path = _run_remote_cutover(
        tmp_path,
        skip_frontend_image=True,
    )

    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
    log = log_path.read_text(encoding="utf-8")
    assert "service=frontend" not in log
    assert "load:traffic-only" in log


@pytest.mark.parametrize(
    ("current_kind", "missing_service"),
    [("absent", ""), ("valid", "frontend")],
)
def test_backend_only_cutover_requires_a_running_frontend_to_preserve(
    tmp_path: Path,
    current_kind: str,
    missing_service: str,
) -> None:
    completed, remote_dir, log_path = _run_remote_cutover(
        tmp_path,
        current_kind=current_kind,
        new_project_name="npcink-ai-cloud" if current_kind == "absent" else None,
        skip_frontend_image=True,
        missing_previous_service=missing_service,
    )

    assert completed.returncode == 1
    marker = (remote_dir / ".cutover-failed").read_text(encoding="utf-8")
    assert "outcome=validation_failed_before_mutation" in marker
    log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    assert "load:prepare-only" not in log
    if current_kind == "absent":
        assert "requires an existing managed release" in completed.stderr
    else:
        assert "found 0" in completed.stderr


def test_pre_migration_failure_restores_previous_release(tmp_path: Path) -> None:
    completed, remote_dir, log_path = _run_remote_cutover(tmp_path, fail_at="data-only")

    assert completed.returncode == 42
    assert (remote_dir / "current").resolve() == remote_dir / "release-previous"
    marker = (remote_dir / ".cutover-failed").read_text(encoding="utf-8")
    assert "outcome=previous_release_restored" in marker
    log = log_path.read_text(encoding="utf-8")
    assert "migrate:0" not in log
    assert "load:api-only" not in log
    assert " up -d --pull never --no-build --force-recreate --remove-orphans" in log


def test_pre_migration_recovery_rejects_wrong_container_image(
    tmp_path: Path,
) -> None:
    completed, remote_dir, log_path = _run_remote_cutover(
        tmp_path,
        fail_at="data-only",
        recovery_wrong_image_service="callback-worker",
    )

    assert completed.returncode != 0
    marker = (remote_dir / ".cutover-failed").read_text(encoding="utf-8")
    assert "outcome=previous_release_restored" not in marker
    assert "outcome=fail_closed_without_safe_rollback" in marker
    assert (remote_dir / ".deploy-lock").is_dir()
    assert "does not use its snapshotted rollback image" in completed.stderr
    assert "Deployment lock retained for operator recovery" in completed.stderr
    log = log_path.read_text(encoding="utf-8")
    assert "postgres redis proxy frontend api worker callback-worker ops-worker" in log
    _assert_recovery_generation_was_refenced(tmp_path, log_path)


def test_previous_release_recovery_uses_only_previous_env_for_compose(
    tmp_path: Path,
) -> None:
    completed, _remote_dir, log_path = _run_remote_cutover(
        tmp_path,
        fail_at="data-only",
        new_project_name="npcink-ai-cloud",
        old_env_sentinel="old-value",
        new_env_sentinel="new-value",
    )

    assert completed.returncode == 42
    log = log_path.read_text(encoding="utf-8")
    assert "compose-file-sentinel:old-value" in log
    assert "compose-file-sentinel:new-value" not in log
    assert "compose-shell-sentinel:new-value" not in log
    assert "compose-shell-sentinel:unset" in log


def test_parameterized_previous_compose_uses_frozen_network_for_inspection_and_recovery(
    tmp_path: Path,
) -> None:
    completed, remote_dir, log_path = _run_remote_cutover(
        tmp_path,
        fail_at="data-only",
        previous_runtime_network_contract=True,
    )

    assert completed.returncode == 42, f"{completed.stdout}\n{completed.stderr}"
    assert (remote_dir / "current").resolve() == remote_dir / "release-previous"
    state_dir = remote_dir / ".release-state" / "release-previous"
    expected_suffix = (
        "10.255.1.0/24:10.255.1.1:10.255.1.9:"
        f"{state_dir / 'nginx.runtime.conf'}"
    )
    network_lines = [
        line
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("compose-network:")
    ]
    assert any(line == f"compose-network:inspection:{expected_suffix}" for line in network_lines)
    assert any(line == f"compose-network:recovery:{expected_suffix}" for line in network_lines)
    assert all(line.endswith(expected_suffix) for line in network_lines)
    assert all("172.28.0." not in line and ":unset" not in line for line in network_lines)


@pytest.mark.parametrize(
    ("variant", "expected_error"),
    [
        ("partial-compose", "interpolation structure is incomplete or ambiguous"),
        ("missing", "per-release state directory is missing"),
        ("project-mismatch", "belongs to another Compose project"),
        ("invalid-ipv4", "Frozen runtime network state is invalid"),
        ("nginx-mismatch", "differs from the bundled gateway contract"),
        ("state-mode", "has an unsafe mode"),
    ],
)
def test_parameterized_previous_compose_rejects_unsafe_network_state_before_mutation(
    tmp_path: Path,
    variant: str,
    expected_error: str,
) -> None:
    completed, remote_dir, log_path = _run_remote_cutover(
        tmp_path,
        previous_runtime_network_contract=True,
        runtime_network_state_variant=variant,
    )

    assert completed.returncode != 0
    assert expected_error in completed.stderr
    marker = (remote_dir / ".cutover-failed").read_text(encoding="utf-8")
    assert "outcome=validation_failed_before_mutation" in marker
    log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    assert "load:prepare-only" not in log
    assert "docker:tag" not in log
    assert "docker:stop" not in log
    assert "docker:rm" not in log


def test_previous_runtime_network_drift_refuses_rollback_recreate(
    tmp_path: Path,
) -> None:
    completed, remote_dir, log_path = _run_remote_cutover(
        tmp_path,
        fail_at="data-only",
        previous_runtime_network_contract=True,
        drift_previous_runtime_network_after_failure=True,
    )

    assert completed.returncode != 0
    marker = (remote_dir / ".cutover-failed").read_text(encoding="utf-8")
    assert "outcome=fail_closed_without_safe_rollback" in marker
    assert (remote_dir / ".deploy-lock").is_dir()
    assert "runtime network contract drifted or became unsafe" in completed.stderr
    log = log_path.read_text(encoding="utf-8")
    assert " up -d --pull never --no-build --force-recreate --remove-orphans" not in log
    assert "Deployment lock retained for operator recovery" in completed.stderr


def test_legacy_previous_compose_recovery_needs_no_runtime_network_state(
    tmp_path: Path,
) -> None:
    completed, remote_dir, log_path = _run_remote_cutover(tmp_path, fail_at="data-only")

    assert completed.returncode == 42, f"{completed.stdout}\n{completed.stderr}"
    assert not (remote_dir / ".release-state" / "release-previous").exists()
    assert "pre-runtime-network Compose contract" in completed.stdout
    network_lines = [
        line
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("compose-network:")
    ]
    assert network_lines
    assert all(line.endswith(":unset:unset:unset:unset") for line in network_lines)


def test_compose_project_drift_fails_before_docker_mutation(tmp_path: Path) -> None:
    completed, remote_dir, log_path = _run_remote_cutover(
        tmp_path,
        old_project_name="npcink-ai-cloud",
        new_project_name="renamed-cloud",
    )

    assert completed.returncode == 1
    assert "Compose project rename is not supported" in completed.stderr
    marker = (remote_dir / ".cutover-failed").read_text(encoding="utf-8")
    assert "outcome=validation_failed_before_mutation" in marker
    assert not log_path.exists() or "docker:" not in log_path.read_text(encoding="utf-8")


def test_actual_writer_project_drift_fails_before_cutover_mutation(
    tmp_path: Path,
) -> None:
    completed, remote_dir, log_path = _run_remote_cutover(
        tmp_path,
        actual_container_project_name="unexpected-project",
    )

    assert completed.returncode == 1
    assert "not a running member of expected Compose project" in completed.stderr
    marker = (remote_dir / ".cutover-failed").read_text(encoding="utf-8")
    assert "outcome=validation_failed_before_mutation" in marker
    log = log_path.read_text(encoding="utf-8")
    assert "load:prepare-only" not in log
    assert "docker:tag" not in log
    assert "docker:stop" not in log
    assert "docker:rm" not in log


def test_previous_compose_up_failure_is_not_misclassified_as_restored(
    tmp_path: Path,
) -> None:
    completed, remote_dir, _log_path = _run_remote_cutover(
        tmp_path,
        fail_at="data-only",
        fail_old_compose_up=True,
    )

    assert completed.returncode != 0
    marker = (remote_dir / ".cutover-failed").read_text(encoding="utf-8")
    assert "outcome=fail_closed_without_safe_rollback" in marker
    assert "outcome=previous_release_restored" not in marker
    assert "Previous release Compose start failed" in completed.stderr
    assert (remote_dir / ".deploy-lock").is_dir()
    _assert_recovery_generation_was_refenced(tmp_path, _log_path)


def test_unproven_fail_closed_recovery_retains_deploy_lock(tmp_path: Path) -> None:
    completed, remote_dir, _log_path = _run_remote_cutover(
        tmp_path,
        fail_at="baseline",
        recovery_still_running=True,
    )

    assert completed.returncode != 0
    marker = (remote_dir / ".cutover-failed").read_text(encoding="utf-8")
    assert "outcome=recovery_incomplete" in marker
    assert (remote_dir / ".deploy-lock").is_dir()
    assert "Deployment lock retained for operator recovery" in completed.stderr


def test_recovery_docker_ps_failure_retains_deploy_lock(tmp_path: Path) -> None:
    completed, remote_dir, _log_path = _run_remote_cutover(
        tmp_path,
        fail_at="baseline",
        recovery_docker_ps_fail=True,
    )

    assert completed.returncode != 0
    marker = (remote_dir / ".cutover-failed").read_text(encoding="utf-8")
    assert "outcome=recovery_incomplete" in marker
    assert (remote_dir / ".deploy-lock").is_dir()
    assert "Docker could not prove governed release one-off containers absent" in completed.stderr


def test_failed_removal_of_new_image_tag_retains_deploy_lock(tmp_path: Path) -> None:
    completed, remote_dir, _log_path = _run_remote_cutover(
        tmp_path,
        fail_at="data-only",
        absent_rollback_reference=True,
        fail_rollback_remove=True,
    )

    assert completed.returncode == 42
    marker = (remote_dir / ".cutover-failed").read_text(encoding="utf-8")
    assert "outcome=recovery_incomplete" in marker
    assert (remote_dir / ".deploy-lock").is_dir()
    assert "Could not remove release image tag" in completed.stderr
    assert "Image-tag recovery is incomplete" in completed.stderr


def test_multiple_previous_containers_are_not_accepted_as_restored(
    tmp_path: Path,
) -> None:
    completed, remote_dir, _log_path = _run_remote_cutover(
        tmp_path,
        fail_at="data-only",
        multiple_previous_containers=True,
    )

    assert completed.returncode != 0
    marker = (remote_dir / ".cutover-failed").read_text(encoding="utf-8")
    assert "outcome=fail_closed_without_safe_rollback" in marker
    assert "outcome=previous_release_restored" not in marker
    assert "must have exactly one container" in completed.stderr
    assert (remote_dir / ".deploy-lock").is_dir()


@pytest.mark.parametrize("current_kind", ["broken", "nested"])
def test_pre_mutation_validation_failure_does_not_stop_running_services(
    tmp_path: Path, current_kind: str
) -> None:
    completed, remote_dir, log_path = _run_remote_cutover(tmp_path, current_kind=current_kind)

    assert completed.returncode == 1
    assert (remote_dir / "current").is_symlink()
    marker = (remote_dir / ".cutover-failed").read_text(encoding="utf-8")
    assert "outcome=validation_failed_before_mutation" in marker
    assert not log_path.exists() or "docker:" not in log_path.read_text(encoding="utf-8")
    assert "running services were untouched" in completed.stderr


def test_preexisting_one_off_lock_blocks_deploy_without_mutation(
    tmp_path: Path,
) -> None:
    completed, remote_dir, log_path = _run_remote_cutover(
        tmp_path, preexisting_one_off_lock=True
    )

    assert completed.returncode != 0
    assert (remote_dir / "current").resolve() == remote_dir / "release-previous"
    assert (remote_dir / ".release-state" / ".release-one-off.lock").is_dir()
    assert not (remote_dir / ".deploy-lock").exists()
    marker = (remote_dir / ".cutover-failed").read_text(encoding="utf-8")
    assert "outcome=validation_failed_before_mutation" in marker
    log = log_path.read_text(encoding="utf-8")
    assert "load:prepare-only" not in log
    assert "docker:stop" not in log
    assert "docker:rm" not in log
    assert "left it untouched" in completed.stderr


def test_internal_one_off_cleanup_failure_retains_both_recovery_locks(
    tmp_path: Path,
) -> None:
    completed, remote_dir, log_path = _run_remote_cutover(
        tmp_path, fail_at="oneoff_cleanup"
    )

    assert completed.returncode != 0
    assert (remote_dir / "current").resolve() == remote_dir / "release-previous"
    assert (remote_dir / ".release-state" / ".release-one-off.lock").is_dir()
    assert (remote_dir / ".deploy-lock").is_dir()
    assert (remote_dir / ".deploy-lock" / "one-off-owner").is_file()
    marker = (remote_dir / ".cutover-failed").read_text(encoding="utf-8")
    assert "outcome=recovery_incomplete" in marker
    log = log_path.read_text(encoding="utf-8")
    assert "load:api-only" not in log
    assert "load:workers-only" not in log
    assert "load:traffic-only" not in log
    assert "cleanup is unproved" in completed.stderr


@pytest.mark.parametrize("fail_at", ["migrate", "baseline"])
def test_failure_after_migration_starts_is_fail_closed(tmp_path: Path, fail_at: str) -> None:
    completed, remote_dir, log_path = _run_remote_cutover(tmp_path, fail_at=fail_at)

    assert completed.returncode in {43, 45}
    assert (remote_dir / "current").resolve() == remote_dir / "release-previous"
    marker = (remote_dir / ".cutover-failed").read_text(encoding="utf-8")
    assert "outcome=fail_closed_after_migration_started" in marker
    log = log_path.read_text(encoding="utf-8")
    assert "restore previous release services" not in completed.stdout
    assert " up -d --pull never --no-build --force-recreate --remove-orphans" not in log
    assert "Migration had started; public/write services remain stopped" in completed.stderr
