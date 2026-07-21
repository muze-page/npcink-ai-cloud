from __future__ import annotations

import shlex
import subprocess
from pathlib import Path


def _cloud_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _edge_bind_source() -> str:
    return (_cloud_root() / "deploy" / "bind-domain-to-ssh-host.sh").read_text()


def _extract_bash_function(source: str, name: str) -> str:
    lines = source.splitlines()
    start = lines.index(f"{name}() {{")
    for end in range(start + 1, len(lines)):
        if lines[end] == "}":
            return "\n".join(lines[start : end + 1])
    raise AssertionError(f"unterminated Bash function: {name}")


def _extract_candidate_nginx_transaction(source: str) -> str:
    start = source.index("\nROLLBACK_REQUIRED=1\n") + 1
    end = source.index('\n\nif [ "${PREPARE_ONLY}" = "1" ]; then', start)
    return source[start:end]


def _run_bash(tmp_path: Path, body: str) -> subprocess.CompletedProcess[str]:
    harness_path = tmp_path / "recovery-harness.sh"
    harness_path.write_text(f"#!/usr/bin/env bash\nset -Eeuo pipefail\n{body}\n")
    return subprocess.run(
        ["bash", str(harness_path)],
        text=True,
        capture_output=True,
        check=False,
    )


def _run_failed_candidate_recovery(
    tmp_path: Path, *, restore_complete: bool
) -> tuple[subprocess.CompletedProcess[str], Path, Path, str]:
    source = _edge_bind_source()
    candidate_transaction = _extract_candidate_nginx_transaction(source)
    functions = "\n\n".join(
        _extract_bash_function(source, name)
        for name in (
            "restored_target_matches_snapshot",
            "verify_restored_nginx_state",
            "verify_original_nginx_service_state",
            "verify_original_caddy_running",
            "rollback_edge_transaction",
            "cleanup_remote_tmp",
            "release_deploy_lock",
            "on_exit",
        )
    )
    remote_tmp = tmp_path / "remote-tmp"
    deploy_lock = tmp_path / "deploy-lock"
    event_log = tmp_path / "events.log"
    remote_tmp.mkdir()
    deploy_lock.mkdir()
    (remote_tmp / "candidate-evidence").write_text("candidate nginx -t failed\n")
    candidate_config = remote_tmp / "candidate.conf"
    candidate_config.write_text("candidate\n")
    restore_body = (
        'rm -f -- "${SITE_AVAILABLE}" "${SITE_ENABLED}" "${DEFAULT_ENABLED}"\n\treturn 1'
        if restore_complete
        else "return 1"
    )
    body = f"""
{functions}

restore_nginx_files() {{
    {restore_body}
}}
nginx() {{
    printf 'nginx:%s\\n' "$*" >>"${{EVENT_LOG}}"
    [ "$(grep -c '^nginx:' "${{EVENT_LOG}}")" -gt 1 ]
}}
systemctl() {{
    printf 'systemctl:%s\\n' "$*" >>"${{EVENT_LOG}}"
    case "$1" in
        is-active) printf 'inactive\\n'; return 3 ;;
        is-enabled) printf 'disabled\\n'; return 1 ;;
        *) return 0 ;;
    esac
}}
docker() {{
    printf 'docker:%s\\n' "$*" >>"${{EVENT_LOG}}"
    [ "$1" = "inspect" ] || return 1
    [ "${{@: -1}}" = "caddy0123456" ] || return 1
    printf 'true\\n'
}}

EVENT_LOG={shlex.quote(str(event_log))}
REMOTE_TMP_DIR={shlex.quote(str(remote_tmp))}
REMOTE_TMP_CONF={shlex.quote(str(candidate_config))}
ROLLBACK_DIR="${{REMOTE_TMP_DIR}}/rollback"
DEPLOY_LOCK_DIR={shlex.quote(str(deploy_lock))}
SITE_AVAILABLE="${{REMOTE_TMP_DIR}}/site-available"
SITE_ENABLED="${{REMOTE_TMP_DIR}}/site-enabled"
DEFAULT_ENABLED="${{REMOTE_TMP_DIR}}/default-enabled"
SITE_AVAILABLE_EXISTED=0
SITE_ENABLED_EXISTED=0
DEFAULT_ENABLED_EXISTED=0
EDGE_SERVICE_MUTATION_STARTED=0
ROLLBACK_REQUIRED=0
TRANSACTION_COMMITTED=0
LOCK_HELD=1
PRESERVE_ROLLBACK_EVIDENCE=0
NGINX_WAS_ACTIVE=0
NGINX_ACTIVE_STATE=inactive
NGINX_ENABLEMENT_STATE=disabled
ORIGINAL_CADDY_IDS=(caddy0123456)

trap on_exit EXIT
# Execute the production transaction slice, including rollback arming, candidate
# installation and the first failing NGINX syntax check.
{candidate_transaction}
"""
    result = _run_bash(tmp_path, body)
    return result, remote_tmp, deploy_lock, event_log.read_text()


def test_failed_candidate_cleans_lock_when_final_recovery_is_complete(
    tmp_path: Path,
) -> None:
    result, remote_tmp, deploy_lock, events = _run_failed_candidate_recovery(
        tmp_path, restore_complete=True
    )

    assert result.returncode != 0
    assert "restore commands returned non-zero; checking final state" in result.stderr
    assert "rollback verification failed" not in result.stderr, result.stderr
    assert events.count("nginx:-t\n") == 2
    assert "systemctl:is-active nginx\n" in events
    assert "systemctl:is-enabled nginx\n" in events
    assert "docker:inspect --format {{.State.Running}} caddy0123456\n" in events
    assert not deploy_lock.exists()
    assert not remote_tmp.exists()


def test_failed_candidate_preserves_lock_when_final_recovery_is_incomplete(
    tmp_path: Path,
) -> None:
    result, remote_tmp, deploy_lock, events = _run_failed_candidate_recovery(
        tmp_path, restore_complete=False
    )

    assert result.returncode != 0
    assert "sites-available config should be absent" in result.stderr
    assert "rollback verification failed" in result.stderr
    assert events.count("nginx:-t\n") == 2
    assert deploy_lock.is_dir()
    assert (remote_tmp / "RETAIN_ROLLBACK_EVIDENCE").is_file()


def test_snapshot_comparison_fails_closed_on_metadata_or_readlink_errors(
    tmp_path: Path,
) -> None:
    function = _extract_bash_function(_edge_bind_source(), "restored_target_matches_snapshot")
    rollback = tmp_path / "rollback"
    rollback.mkdir()
    backup = rollback / "site-available"
    target = tmp_path / "site-available"
    backup.write_text("same\n")
    target.write_text("same\n")
    common = f"""
{function}
ROLLBACK_DIR={shlex.quote(str(rollback))}
file_type_of() {{ printf 'regular file\\n'; }}
metadata_of() {{ return 1; }}
restored_target_matches_snapshot test {shlex.quote(str(target))} site-available 1
"""
    metadata_result = _run_bash(tmp_path, common)
    assert metadata_result.returncode != 0

    backup.unlink()
    target.unlink()
    backup.symlink_to("same-target")
    target.symlink_to("same-target")
    link_body = f"""
{function}
ROLLBACK_DIR={shlex.quote(str(rollback))}
file_type_of() {{ printf 'symbolic link\\n'; }}
metadata_of() {{ printf '0:0:777\\n'; }}
readlink() {{ return 1; }}
restored_target_matches_snapshot test {shlex.quote(str(target))} site-available 1
"""
    link_result = _run_bash(tmp_path, link_body)
    assert link_result.returncode != 0


def test_snapshot_comparison_checks_content_link_target_and_metadata(
    tmp_path: Path,
) -> None:
    function = _extract_bash_function(_edge_bind_source(), "restored_target_matches_snapshot")
    rollback = tmp_path / "rollback"
    rollback.mkdir()
    backup = rollback / "site-available"
    target = tmp_path / "site-available"
    backup.write_text("before\n")
    target.write_text("after\n")
    content_body = f"""
{function}
ROLLBACK_DIR={shlex.quote(str(rollback))}
file_type_of() {{ printf 'regular file\\n'; }}
metadata_of() {{ printf '0:0:600\\n'; }}
restored_target_matches_snapshot test {shlex.quote(str(target))} site-available 1
"""
    assert _run_bash(tmp_path, content_body).returncode != 0

    target.write_text("before\n")
    metadata_body = content_body.replace(
        "metadata_of() { printf '0:0:600\\n'; }",
        "metadata_of() { case \"$1\" in *rollback*) printf '0:0:600\\n' ;; "
        "*) printf '0:0:644\\n' ;; esac; }",
    )
    assert _run_bash(tmp_path, metadata_body).returncode != 0

    backup.unlink()
    target.unlink()
    backup.symlink_to("before-target")
    target.symlink_to("after-target")
    link_body = f"""
{function}
ROLLBACK_DIR={shlex.quote(str(rollback))}
file_type_of() {{ printf 'symbolic link\\n'; }}
metadata_of() {{ printf '0:0:777\\n'; }}
restored_target_matches_snapshot test {shlex.quote(str(target))} site-available 1
"""
    assert _run_bash(tmp_path, link_body).returncode != 0


def test_nginx_state_query_error_is_not_treated_as_inactive(tmp_path: Path) -> None:
    function = _extract_bash_function(_edge_bind_source(), "verify_original_nginx_service_state")
    body = f"""
{function}
NGINX_ACTIVE_STATE=inactive
NGINX_ENABLEMENT_STATE=disabled
systemctl() {{
    case "$1" in
        is-active) printf 'inactive\\n'; return 1 ;;
        is-enabled) printf 'disabled\\n'; return 1 ;;
    esac
}}
verify_original_nginx_service_state
"""
    result = _run_bash(tmp_path, body)
    assert result.returncode != 0
    assert "active state is unreadable" in result.stderr


def test_caddy_snapshot_propagates_query_failure_and_keeps_exact_ids(
    tmp_path: Path,
) -> None:
    source = _edge_bind_source()
    function = _extract_bash_function(source, "snapshot_original_caddy_ids")
    rollback = tmp_path / "rollback"
    rollback.mkdir()
    failure_body = f"""
{function}
ROLLBACK_DIR={shlex.quote(str(rollback))}
COMPOSE_PROJECT_NAME_EFFECTIVE=npcink-ai-cloud
ORIGINAL_CADDY_IDS=()
docker() {{ return 1; }}
snapshot_original_caddy_ids
"""
    failure = _run_bash(tmp_path, failure_body)
    assert failure.returncode != 0
    assert "could not snapshot" in failure.stderr

    success_body = f"""
{function}
ROLLBACK_DIR={shlex.quote(str(rollback))}
COMPOSE_PROJECT_NAME_EFFECTIVE=npcink-ai-cloud
ORIGINAL_CADDY_IDS=()
docker() {{ printf '0123456789ab\\nabcdef0123456789\\n'; }}
snapshot_original_caddy_ids
printf '<%s>\\n' "${{ORIGINAL_CADDY_IDS[@]}}"
"""
    success = _run_bash(tmp_path, success_body)
    assert success.returncode == 0, success.stderr
    assert success.stdout.splitlines() == ["<0123456789ab>", "<abcdef0123456789>"]
    assert "snapshot_original_caddy_ids || fail_remote" in source


def test_initial_nginx_snapshot_requires_exact_active_state_status() -> None:
    source = _edge_bind_source()
    assert 'case "${NGINX_ACTIVE_STATE}:${NGINX_ACTIVE_STATUS}"' in source
    assert "active:0) NGINX_WAS_ACTIVE=1" in source
    assert "inactive:3)" in source


def test_successful_prepare_only_verifies_every_restored_postcondition() -> None:
    source = _edge_bind_source()
    transaction_start = source.index("\nROLLBACK_REQUIRED=1\n")
    prepare_start = source.index('if [ "${PREPARE_ONLY}" = "1" ]; then', transaction_start)
    rollback_disarm = source.index("ROLLBACK_REQUIRED=0", prepare_start)

    for verifier in (
        "verify_restored_nginx_state",
        "verify_original_nginx_service_state",
        "verify_original_caddy_running",
    ):
        assert prepare_start < source.index(verifier, prepare_start) < rollback_disarm
