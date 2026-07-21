from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "backup-restore-drill.sh"
DOC = ROOT / "docs" / "p5-b5-local-backup-restore-drill-v1.md"


def test_restore_drill_script_is_executable_and_valid_bash() -> None:
    assert SCRIPT.is_file()
    assert os.access(SCRIPT, os.X_OK)
    subprocess.run(["bash", "-n", str(SCRIPT)], cwd=ROOT, check=True)


def test_restore_drill_help_is_non_executing_and_documents_narrow_overrides() -> None:
    completed = subprocess.run(
        [str(SCRIPT), "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "fully local backup/restore drill" in completed.stdout
    assert "NPCINK_RESTORE_DRILL_POSTGRES_IMAGE" in completed.stdout
    assert "NPCINK_RESTORE_DRILL_TIMEOUT_SECONDS" in completed.stdout
    assert "NPCINK_RESTORE_DRILL_PYTHON" in completed.stdout
    assert "never reads .env or .env.deploy" in completed.stdout


def test_restore_drill_has_unique_disposable_postgres_16_resources_and_cleanup() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'POSTGRES_IMAGE="${NPCINK_RESTORE_DRILL_POSTGRES_IMAGE:-postgres:16-alpine}"' in source
    assert 'RUN_SUFFIX="$(date -u' in source
    assert "_$$_${RANDOM}" in source
    assert 'SOURCE_CONTAINER="${RESOURCE_PREFIX}_source"' in source
    assert 'RESTORE_CONTAINER="${RESOURCE_PREFIX}_restored"' in source
    assert 'SOURCE_VOLUME="${RESOURCE_PREFIX}_source_data"' in source
    assert 'RESTORE_VOLUME="${RESOURCE_PREFIX}_restored_data"' in source
    assert 'NETWORK="${RESOURCE_PREFIX}_network"' in source
    assert "-p '127.0.0.1::5432'" in source
    assert "server_version_num" in source
    assert "SOURCE_POSTGRES_VERSION < 160000" in source
    assert "SOURCE_POSTGRES_VERSION >= 170000" in source
    assert "trap on_exit EXIT" in source
    assert "trap 'on_signal hangup 129' HUP" in source
    assert "trap 'on_signal interrupt 130' INT" in source
    assert "trap 'on_signal terminated 143' TERM" in source
    assert "trap on_exit EXIT INT TERM HUP" not in source
    assert 'remove_container "${SOURCE_CONTAINER}"' in source
    assert 'remove_container "${RESTORE_CONTAINER}"' in source
    assert 'remove_volume "${SOURCE_VOLUME}"' in source
    assert 'remove_volume "${RESTORE_VOLUME}"' in source
    assert 'remove_network "${NETWORK}"' in source
    assert "assert_docker_resources_absent" in source
    assert 'rm -rf -- "${TMP_DIR}"' in source


def test_restore_drill_discovers_and_verifies_the_live_alembic_head() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "ast.parse" in source
    assert "values[target.id] = ast.literal_eval(node.value)" in source
    assert "heads = sorted(revisions - parents)" in source
    assert "if len(heads) != 1:" in source
    assert 'run_migrations "${SOURCE_PORT}"' in source
    assert '[[ "${SOURCE_HEAD}" == "${ALEMBIC_HEAD}" ]]' in source
    assert '[[ "${RESTORED_HEAD}" == "${ALEMBIC_HEAD}" ]]' in source
    assert "20260717_0068" not in source


def test_restore_drill_does_not_load_configured_or_production_environment() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'ISOLATED_CWD="${TMP_DIR}/no-env"' in source
    assert source.count("env -i") >= 2
    assert 'NPCINK_CLOUD_DATABASE_URL="${database_url}"' in source
    assert "source .env" not in source
    assert "docker compose" not in source
    assert source.count(".env.deploy") == 1
    assert "cloud.npc.ink" not in source
    assert "DATABASE_URL:-" not in source
    assert "docker context inspect --format '{{.Endpoints.docker.Host}}'" in source
    assert "unix:///*)" in source
    assert "refusing non-local Docker endpoint" in source


def test_restore_drill_rejects_remote_docker_host_before_contact() -> None:
    completed = subprocess.run(
        [str(SCRIPT)],
        cwd=ROOT,
        env={
            **os.environ,
            "DOCKER_HOST": "ssh://production.example.invalid",
            "NPCINK_RESTORE_DRILL_PYTHON": sys.executable,
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 64
    assert "refusing non-local Docker endpoint" in completed.stderr
    assert "production.example.invalid" not in completed.stderr


def test_restore_drill_binds_relational_rows_to_real_artifact_store_bytes() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "from app.domain.media_artifacts import LocalVolumeArtifactStore" in source
    assert "LocalVolumeArtifactStore(sys.argv[1]).put" in source
    for table in (
        "accounts",
        "principals",
        "account_user_memberships",
        "sites",
        "run_records",
        "media_artifacts",
        "media_artifact_deliveries",
    ):
        assert f"INSERT INTO {table}" in source
    assert "relationship_count" in source
    assert "JOIN media_artifact_deliveries" in source
    assert '[[ "${RELATIONSHIP_COUNT}" == "1" ]]' in source
    assert "actual_checksum != expected_checksum" in source


def test_restore_drill_freezes_database_and_artifact_recovery_point() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "pg_dump" in source
    assert "--format=custom --no-owner --no-acl" in source
    assert "pg_restore --list" in source
    assert "pg_restore" in source and "--exit-on-error" in source
    assert (
        'COPYFILE_DISABLE=1 tar -C "${SOURCE_ARTIFACT_ROOT}" -cpf "${ARTIFACT_ARCHIVE}" .' in source
    )
    assert "write_database_manifest" in source
    assert 'docker exec -i "${container}" psql' in source
    assert "write_artifact_manifest" in source
    assert '"contract": "p5_b5_backup_restore_recovery_point.v1"' in source
    assert "database_manifest_sha256" in source
    assert "artifact_manifest_sha256" in source
    assert "recovery_manifest_sha256" in source
    assert "safe_extract_artifact_archive" in source
    assert 'relative.is_absolute() or ".." in relative.parts' in source
    assert "member.isfile()" in source


def test_restore_drill_proves_corruption_and_missing_artifact_are_rejected() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "fault-injection-database-corruption" in source
    assert "printf 'injected-corruption'" in source
    assert 'if verify_checksum "${CORRUPT_DB_DUMP}" "${DB_DUMP_SHA256}"; then' in source
    assert "corrupted database dump passed checksum verification" in source
    assert "fault-injection-artifact-missing" in source
    assert 'rm -f -- "${FAULT_ARTIFACT_ROOT}/${ARTIFACT_RELATIVE_PATH}"' in source
    assert 'if cmp -s "${ARTIFACT_MANIFEST}"' in source
    assert "missing artifact passed manifest verification" in source
    assert '"database_corruption_rejected": True' in source
    assert '"artifact_missing_rejected": True' in source


def test_restore_drill_emits_fail_closed_machine_readable_evidence() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'CONTRACT="p5_b5_backup_restore_drill.v1"' in source
    assert '"status": "failed"' in source
    assert '"failed_stage": stage' in source
    assert '"status": "passed"' in source
    assert '"docker_resources_removed": True' in source
    assert '"temporary_directory_removed": True' in source
    assert 'rm -rf -- "${TMP_DIR}" || die "temporary directory cleanup failed"' in source
    assert '[[ ! -e "${TMP_DIR}" ]]' in source
    assert source.index('[[ ! -e "${TMP_DIR}" ]]') < source.index(
        "printf '%s\\n' \"${SUMMARY_JSON}\""
    )
    assert '"local_docker_unix_socket_verified": True' in source
    assert source.count('"production_contacted": False') == 2


def test_restore_drill_document_freezes_scope_and_honest_evidence_boundary() -> None:
    document = DOC.read_text(encoding="utf-8")

    assert "Status: active engineering gate." in document
    assert "production-backup-restore-drill-2026-07-10.md" in document
    assert "production-backup-restore-drill-2026-07-11.md" in document
    assert "database and local-volume\nArtifactStore" in document
    assert "20260717_0068" in document
    assert "The script does not freeze that literal" in document
    assert "Mandatory Failure Injection" in document
    assert "Fresh Restore Acceptance" in document
    assert "Machine-Readable Result" in document
    assert "WordPress remains the\nonly CMS write owner" in document
    assert "not production backup evidence" in document
    assert "authorize a production deployment or GA claim" in document
