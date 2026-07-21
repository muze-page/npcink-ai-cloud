from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "runtime-data-encryption-recovery.sh"


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_recovery_script_is_executable_and_shell_valid() -> None:
    mode = stat.S_IMODE(SCRIPT.stat().st_mode)
    assert mode == 0o755
    completed = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_help_exposes_only_paths_flags_and_exact_acknowledgements() -> None:
    completed = subprocess.run(
        [str(SCRIPT), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "--preflight-only" in completed.stdout
    assert "--confirm-full-restore" in completed.stdout
    assert "--confirm-write-loss" in completed.stdout
    assert "--secret" not in completed.stdout
    assert "--old-root" not in completed.stdout


def test_recovery_is_narrowly_bound_to_the_observed_pre_activation_failure() -> None:
    source = _source()
    for marker in (
        '"phase": "restore-public-traffic"',
        '"outcome": "full_database_restore_required"',
        '"migration_started": "1"',
        '"post_migration_writer_stop_proved": "1"',
        '"activation_committed": "0"',
        "activation commit exists; destructive recovery is forbidden",
        "global activation receipt exists; destructive recovery is forbidden",
    ):
        assert marker in source
    assert "alembic downgrade" not in source


def test_failure_marker_and_secret_snapshots_are_never_sourced_or_evaluated() -> None:
    source = _source()
    assert '. "${FAILURE_MARKER}"' not in source
    assert 'source "${FAILURE_MARKER}"' not in source
    assert '. "${MAINTENANCE_SNAPSHOT}"' not in source
    assert 'source "${MAINTENANCE_SNAPSHOT}"' not in source
    assert "eval " not in source
    assert "set -x" not in source
    assert 'set +x' in source
    assert "Secret values are read only from protected snapshots" in source


def test_whole_database_restore_precedes_previous_application_restart() -> None:
    source = _source()
    ordered = (
        'CURRENT_STAGE="re-prove-writer-fence"',
        'CURRENT_STAGE="restore-previous-data-services"',
        'CURRENT_STAGE="restore-whole-database"',
        'dropdb --force --if-exists',
        'createdb -U "$POSTGRES_USER"',
        "pg_restore --exit-on-error --no-owner --no-acl",
        'CURRENT_STAGE="restore-previous-release-pointer"',
        'CURRENT_STAGE="start-previous-api"',
        'CURRENT_STAGE="start-previous-workers"',
        'CURRENT_STAGE="restore-previous-public-traffic"',
        'CURRENT_STAGE="validate-matched-recovery"',
    )
    positions = [source.index(marker) for marker in ordered]
    assert positions == sorted(positions)


def test_success_evidence_is_the_commit_point_before_unlock_and_marker_archive() -> None:
    source = _source()
    evidence = source.index('CURRENT_STAGE="commit-recovery-evidence"')
    committed = source.index("RECOVERY_COMMITTED=1", evidence)
    terminalize_call = source.index(
        'terminalize_recovery || fail "recovery terminalization failed"', committed
    )
    terminalize_function = source[
        source.index("terminalize_recovery() {") : source.index(
            "assert_recovery_images_available() {"
        )
    ]
    archive = terminalize_function.index(
        'CURRENT_STAGE="archive-and-clear-failure-marker-under-lock"'
    )
    unlock = terminalize_function.index('CURRENT_STAGE="release-recovery-lock-last"')
    assert evidence < committed < terminalize_call
    assert archive < unlock
    assert "recovery committed; healthy previous runtime" in source
    assert "recovery not committed; public/write services remain fenced" in source


def test_existing_recovery_result_is_terminalization_only_before_destructive_work() -> None:
    source = _source()
    result_branch = source.index('if [ -e "${RECOVERY_RESULT}" ]')
    destructive_restore = source.index('CURRENT_STAGE="restore-whole-database"')
    assert result_branch < destructive_restore
    branch = source[result_branch:destructive_restore]
    assert "terminalization-only-validate-committed-recovery" in branch
    assert "terminalized without another database restore" in branch
    assert "dropdb" not in branch
    assert "pg_restore" not in branch


def test_docker_target_is_pinned_to_one_local_unix_daemon() -> None:
    source = _source()
    proof = source.index('DOCKER_ENDPOINT="$(docker context inspect')
    first_fence = source.index('CURRENT_STAGE="re-prove-writer-fence"')
    assert proof < first_fence
    assert '[[ "${DOCKER_ENDPOINT}" = unix:///* ]]' in source
    assert "DOCKER_DAEMON_ID=" in source
    assert source.count("assert_local_docker_identity || fail") >= 6
    clean_env = source[source.index("clean_env() {"):source.index("compose_previous() {")]
    assert "DOCKER_CONTEXT" not in clean_env
    assert "DOCKER_CONFIG" not in clean_env


def test_managed_service_queries_are_project_scoped_and_one_off_stays_global() -> None:
    source = _source()
    stop = source[
        source.index("stop_application_services() {") : source.index(
            "assert_application_services_stopped() {"
        )
    ]
    assert 'label=com.docker.compose.project=${COMPOSE_PROJECT_NAME_EFFECTIVE}' in stop
    assert "label=com.docker.compose.service=release-one-off" in stop
    assert "OLD_WRITER_IMAGE_IDS" in stop


def test_only_historical_proxy_may_use_a_retained_repo_digest_exception() -> None:
    source = _source()
    assert 'elif service == "proxy":' in source
    assert 'source = "retained-lock-repo-digest"' in source
    assert "Every application image except the historical official proxy" in source
    assert "raise SystemExit(1)" in source


def test_preflight_only_exits_before_image_env_database_or_pointer_mutation() -> None:
    source = _source()
    preflight_exit = source.index(
        "preflight passed; no production state was changed"
    )
    mutation_markers = (
        'CURRENT_STAGE="restore-previous-image-tags"',
        'CURRENT_STAGE="restore-previous-external-env"',
        'CURRENT_STAGE="restore-previous-data-services"',
        'CURRENT_STAGE="restore-whole-database"',
        'CURRENT_STAGE="restore-previous-release-pointer"',
    )
    assert all(preflight_exit < source.index(marker) for marker in mutation_markers)
    preflight_fence = source[source.index('CURRENT_STAGE="re-prove-writer-fence"'):preflight_exit]
    assert 'if [ "${PREFLIGHT_ONLY}" != "1" ]' in preflight_fence


def test_all_container_python_heredocs_keep_stdin_open() -> None:
    source = _source()
    assert 'docker exec "${API_ID}" python -' not in source
    assert source.count('docker exec -i "${API_ID}" python -') == 3


def test_in_container_api_readiness_uses_the_frozen_production_host_contract() -> None:
    source = _source()
    readiness_start = source.index('CURRENT_STAGE="start-previous-api"')
    decrypt_start = source.index(
        'CURRENT_STAGE="prove-previous-runtime-can-decrypt-restored-data"'
    )
    readiness = source[readiness_start:decrypt_start]
    assert 'os.environ.get("NPCINK_CLOUD_DOMAIN_NAME"' in readiness
    assert 'os.environ.get("NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST"' in readiness
    assert 'os.environ.get("NPCINK_CLOUD_INTERNAL_AUTH_TOKEN"' in readiness
    assert '"X-Npcink-Internal-Token": internal_token' in readiness
    assert 'urllib.request.urlopen("http://127.0.0.1:8000/health/ready"' not in readiness


def test_public_https_readiness_streams_internal_auth_without_secret_argv() -> None:
    source = _source()
    emitter = source[
        source.index("emit_internal_auth_header() {") : source.index(
            "curl_previous_public_ready() {"
        )
    ]
    curl_helper = source[
        source.index("curl_previous_public_ready() {") : source.index(
            "assert_previous_public_ready() {"
        )
    ]
    assert 'os.open(sys.argv[1], os.O_RDONLY | os.O_NOFOLLOW)' in emitter
    assert 'values.get("NPCINK_CLOUD_INTERNAL_AUTH_TOKEN"' in emitter
    assert 'X-Npcink-Internal-Token: {token}' in emitter
    assert "emit_internal_auth_header |" in curl_helper
    assert "--header @-" in curl_helper
    assert "--resolve" in curl_helper
    assert "X-Npcink-Internal-Token: ${" not in source


def test_recovery_holds_a_nonblocking_inode_lock_for_its_whole_lifetime() -> None:
    source = _source()
    marker_repair = source.index('CURRENT_STAGE="detect-interrupted-terminalization"')
    lock_open = source.index('exec {RECOVERY_EXECUTION_LOCK_FD}<"${EARLY_DEPLOY_LOCK}"')
    lock_claim = source.index('flock -n "${RECOVERY_EXECUTION_LOCK_FD}"')
    destructive_restore = source.index('CURRENT_STAGE="restore-whole-database"')
    assert lock_open < lock_claim < marker_repair < destructive_restore
    assert "flock -u" not in source


def test_committed_result_branch_is_read_only_during_preflight_and_never_refenced() -> None:
    source = _source()
    result_branch = source.index('if [ -e "${RECOVERY_RESULT}" ]')
    destructive_restore = source.index('CURRENT_STAGE="restore-whole-database"')
    branch = source[result_branch:destructive_restore]
    durable_validation = branch.index("validate_recovery_result")
    committed = branch.index("RECOVERY_COMMITTED=1", durable_validation)
    runtime_validation = branch.index("assert_local_docker_identity", committed)
    preflight_exit = branch.index("committed-recovery preflight passed", runtime_validation)
    terminalize = branch.index("terminalize_recovery || fail", preflight_exit)
    assert durable_validation < committed < runtime_validation < preflight_exit < terminalize


def test_in_use_target_data_tag_removal_is_deferred_until_old_candidate_replacement() -> None:
    source = _source()
    tag_restore = source.index('CURRENT_STAGE="restore-previous-image-tags"')
    data_restore = source.index('CURRENT_STAGE="restore-previous-data-services"')
    candidate_start = source.index(
        "create_prove_and_start_exact_services postgres redis", data_restore
    )
    remove_tags = source.index("remove_expected_absent_image_tags", candidate_start)
    database_restore = source.index('CURRENT_STAGE="restore-whole-database"')
    assert tag_restore < data_restore < candidate_start < remove_tags < database_restore
    restore_function = source[
        source.index("restore_image_tags() {") : source.index(
            "remove_expected_absent_image_tags() {"
        )
    ]
    assert "docker image rm" not in restore_function
    assert "never force-remove an in-use recovery image" in restore_function


def test_ambient_secret_like_environment_cannot_enable_missing_acknowledgements() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET": "must-not-enable-recovery",
            "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET": "must-not-enable-recovery",
            "NPCINK_CLOUD_SERVICE_SETTINGS_SECRET": "must-not-enable-recovery",
            "NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET": "must-not-enable-recovery",
        }
    )
    completed = subprocess.run(
        [
            str(SCRIPT),
            "--remote-dir",
            "/tmp/not-a-production-root",
            "--failure-marker",
            "/tmp/not-a-production-root/.cutover-failed",
            "--host-python",
            os.environ.get("PYTHON", "python3"),
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode != 0
    assert (
        "full recovery acknowledgement is missing" in completed.stderr
        or "recovery must run as root" in completed.stderr
    )
    for value in environment.values():
        if value == "must-not-enable-recovery":
            assert value not in completed.stdout
            assert value not in completed.stderr
