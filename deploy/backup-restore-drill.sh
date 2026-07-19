#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
CONTRACT="p5_b5_backup_restore_drill.v1"

usage() {
	cat <<'EOF'
Usage: deploy/backup-restore-drill.sh

Run a destructive, fully local backup/restore drill against disposable
PostgreSQL 16 containers and a disposable local-volume ArtifactStore.

Optional environment variables:
  NPCINK_RESTORE_DRILL_POSTGRES_IMAGE   PostgreSQL 16 image (default: postgres:16-alpine)
  NPCINK_RESTORE_DRILL_TIMEOUT_SECONDS  Per-container readiness timeout (default: 90)
  NPCINK_RESTORE_DRILL_PYTHON           Python with this repo's locked dev dependencies

The script never reads .env or .env.deploy, never connects to a configured
database, and always removes its temporary containers, volumes, network, and
working directory. One JSON evidence summary is written to stdout.
EOF
}

case "${1:-}" in
	-h | --help)
		usage
		exit 0
		;;
	"") ;;
	*)
		usage >&2
		exit 64
		;;
esac

POSTGRES_IMAGE="${NPCINK_RESTORE_DRILL_POSTGRES_IMAGE:-postgres:16-alpine}"
TIMEOUT_SECONDS="${NPCINK_RESTORE_DRILL_TIMEOUT_SECONDS:-90}"
PYTHON_BIN="${NPCINK_RESTORE_DRILL_PYTHON:-${ROOT_DIR}/.venv/bin/python}"

if [[ ! "${TIMEOUT_SECONDS}" =~ ^[0-9]+$ ]] || ((TIMEOUT_SECONDS < 10 || TIMEOUT_SECONDS > 900)); then
	printf '[restore-drill:error] timeout must be an integer between 10 and 900 seconds\n' >&2
	exit 64
fi
if [[ -z "${POSTGRES_IMAGE}" ]]; then
	printf '[restore-drill:error] PostgreSQL image must not be empty\n' >&2
	exit 64
fi
if [[ ! -x "${PYTHON_BIN}" ]]; then
	printf '[restore-drill:error] Python is unavailable: %s\n' "${PYTHON_BIN}" >&2
	printf '[restore-drill:error] run make bootstrap-dev or set NPCINK_RESTORE_DRILL_PYTHON\n' >&2
	exit 69
fi
if [[ -n "${DOCKER_HOST:-}" ]]; then
	DOCKER_ENDPOINT="${DOCKER_HOST}"
	case "${DOCKER_ENDPOINT}" in
		unix:///*) ;;
		*)
			printf '[restore-drill:error] refusing non-local Docker endpoint: only a Unix socket is allowed\n' >&2
			exit 64
			;;
	esac
fi
if ! command -v docker >/dev/null 2>&1; then
	printf '[restore-drill:error] Docker is required\n' >&2
	exit 69
fi

if [[ -z "${DOCKER_HOST:-}" ]]; then
	DOCKER_ENDPOINT="$(docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null)" || {
		printf '[restore-drill:error] active Docker context cannot be inspected\n' >&2
		exit 69
	}
fi
case "${DOCKER_ENDPOINT}" in
	unix:///*)
		DOCKER_SOCKET_PATH="${DOCKER_ENDPOINT#unix://}"
		;;
	*)
		printf '[restore-drill:error] refusing non-local Docker endpoint: only a Unix socket is allowed\n' >&2
		exit 64
		;;
esac
if [[ ! -S "${DOCKER_SOCKET_PATH}" ]]; then
	printf '[restore-drill:error] local Docker Unix socket is unavailable\n' >&2
	exit 69
fi
if ! docker info >/dev/null 2>&1; then
	printf '[restore-drill:error] Docker daemon is unavailable\n' >&2
	exit 69
fi

umask 077
STARTED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
STARTED_EPOCH="$(date '+%s')"
RUN_SUFFIX="$(date -u '+%Y%m%d%H%M%S')_$$_${RANDOM}"
RESOURCE_PREFIX="npcink_p5b5_restore_${RUN_SUFFIX}"
SOURCE_CONTAINER="${RESOURCE_PREFIX}_source"
RESTORE_CONTAINER="${RESOURCE_PREFIX}_restored"
SOURCE_VOLUME="${RESOURCE_PREFIX}_source_data"
RESTORE_VOLUME="${RESOURCE_PREFIX}_restored_data"
NETWORK="${RESOURCE_PREFIX}_network"
DB_USER="restore_drill"
DB_NAME="npcink_restore_drill"
DB_PASSWORD="local_${RUN_SUFFIX}"
TMP_ROOT="${TMPDIR:-/tmp}"
TMP_DIR="$(mktemp -d "${TMP_ROOT%/}/npcink-p5-b5-restore-drill.XXXXXX")"
ISOLATED_CWD="${TMP_DIR}/no-env"
BACKUP_DIR="${TMP_DIR}/backup"
SOURCE_ARTIFACT_ROOT="${TMP_DIR}/source-artifacts"
RESTORED_ARTIFACT_ROOT="${TMP_DIR}/restored-artifacts"
FAULT_ARTIFACT_ROOT="${TMP_DIR}/fault-artifacts"
ALEMBIC_CONFIG="${TMP_DIR}/alembic.ini"
DB_DUMP="${BACKUP_DIR}/database.dump"
DB_MANIFEST="${BACKUP_DIR}/database-manifest.tsv"
ARTIFACT_ARCHIVE="${BACKUP_DIR}/artifact-store.tar"
ARTIFACT_MANIFEST="${BACKUP_DIR}/artifact-manifest.tsv"
RECOVERY_MANIFEST="${BACKUP_DIR}/recovery-point-manifest.json"
CURRENT_STAGE="initialization"
SUMMARY_EMITTED=0
CLEANUP_ERROR=0

mkdir -m 700 "${ISOLATED_CWD}" "${BACKUP_DIR}" "${SOURCE_ARTIFACT_ROOT}"

log() {
	printf '[restore-drill] %s\n' "$*" >&2
}

die() {
	printf '[restore-drill:error] stage=%s %s\n' "${CURRENT_STAGE}" "$*" >&2
	exit 1
}

remove_container() {
	local name="$1"
	if docker container inspect "${name}" >/dev/null 2>&1; then
		docker rm -f "${name}" >/dev/null 2>&1 || CLEANUP_ERROR=1
	fi
}

remove_volume() {
	local name="$1"
	if docker volume inspect "${name}" >/dev/null 2>&1; then
		docker volume rm "${name}" >/dev/null 2>&1 || CLEANUP_ERROR=1
	fi
}

remove_network() {
	local name="$1"
	if docker network inspect "${name}" >/dev/null 2>&1; then
		docker network rm "${name}" >/dev/null 2>&1 || CLEANUP_ERROR=1
	fi
}

cleanup_docker() {
	CLEANUP_ERROR=0
	remove_container "${SOURCE_CONTAINER}"
	remove_container "${RESTORE_CONTAINER}"
	remove_volume "${SOURCE_VOLUME}"
	remove_volume "${RESTORE_VOLUME}"
	remove_network "${NETWORK}"
	return "${CLEANUP_ERROR}"
}

emit_failure_summary() {
	local exit_code="$1"
	"${PYTHON_BIN}" - "${CONTRACT}" "${CURRENT_STAGE}" "${exit_code}" \
		"${RESOURCE_PREFIX}" "${STARTED_AT}" <<'PY'
import json
import sys

contract, stage, exit_code, resource_prefix, started_at = sys.argv[1:]
print(json.dumps({
    "contract": contract,
    "status": "failed",
    "failed_stage": stage,
    "exit_code": int(exit_code),
    "resource_prefix": resource_prefix,
    "started_at": started_at,
    "production_contacted": False,
}, sort_keys=True, separators=(",", ":")))
PY
}

on_exit() {
	local exit_code=$?
	trap - EXIT INT TERM HUP
	set +e
	cleanup_docker
	local cleanup_code=$?
	if ((exit_code == 0 && cleanup_code != 0)); then
		exit_code=1
		CURRENT_STAGE="cleanup"
	fi
	if ((exit_code != 0 && SUMMARY_EMITTED == 0)); then
		emit_failure_summary "${exit_code}"
	fi
	rm -rf -- "${TMP_DIR}"
	exit "${exit_code}"
}

on_signal() {
	local signal_name="$1"
	local exit_code="$2"
	CURRENT_STAGE="signal-${signal_name}"
	exit "${exit_code}"
}

trap on_exit EXIT
trap 'on_signal hangup 129' HUP
trap 'on_signal interrupt 130' INT
trap 'on_signal terminated 143' TERM

isolated_python() (
	cd "${ISOLATED_CWD}"
	env -i \
		PATH="${PATH}" \
		HOME="${HOME:-/tmp}" \
		TMPDIR="${TMP_DIR}" \
		PYTHONPATH="${ROOT_DIR}" \
		"${PYTHON_BIN}" "$@"
)

resolve_alembic_head() {
	isolated_python - "${ROOT_DIR}/migrations/versions" <<'PY'
from __future__ import annotations

import ast
import sys
from pathlib import Path

versions = Path(sys.argv[1])
revisions: set[str] = set()
parents: set[str] = set()

for path in sorted(versions.glob("*.py")):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in {"revision", "down_revision"}:
            continue
        values[target.id] = ast.literal_eval(node.value)
    revision = values.get("revision")
    if not isinstance(revision, str) or not revision:
        raise SystemExit(f"invalid Alembic revision declaration: {path.name}")
    if revision in revisions:
        raise SystemExit(f"duplicate Alembic revision: {revision}")
    revisions.add(revision)
    down_revision = values.get("down_revision")
    if isinstance(down_revision, str):
        parents.add(down_revision)
    elif isinstance(down_revision, (tuple, list)):
        if not all(isinstance(item, str) for item in down_revision):
            raise SystemExit(f"invalid Alembic parent declaration: {path.name}")
        parents.update(down_revision)
    elif down_revision is not None:
        raise SystemExit(f"invalid Alembic parent declaration: {path.name}")

unknown = parents - revisions
heads = sorted(revisions - parents)
if unknown:
    raise SystemExit(f"unknown Alembic parents: {sorted(unknown)}")
if len(heads) != 1:
    raise SystemExit(f"expected exactly one Alembic head, found: {heads}")
print(heads[0])
PY
}

write_isolated_alembic_config() {
	isolated_python - "${ROOT_DIR}/alembic.ini" "${ALEMBIC_CONFIG}" \
		"${ROOT_DIR}/migrations" "${ROOT_DIR}" <<'PY'
from pathlib import Path
import sys

source, destination, migrations, root = map(Path, sys.argv[1:])
lines: list[str] = []
for line in source.read_text(encoding="utf-8").splitlines():
    if line.startswith("script_location ="):
        line = f"script_location = {migrations}"
    elif line.startswith("prepend_sys_path ="):
        line = f"prepend_sys_path = {root}"
    lines.append(line)
destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

run_migrations() {
	local port="$1"
	local database_url="postgresql+psycopg://${DB_USER}:${DB_PASSWORD}@127.0.0.1:${port}/${DB_NAME}"
	(
		cd "${ISOLATED_CWD}"
		env -i \
			PATH="${PATH}" \
			HOME="${HOME:-/tmp}" \
			TMPDIR="${TMP_DIR}" \
			PYTHONPATH="${ROOT_DIR}" \
			NPCINK_CLOUD_ENVIRONMENT="testing" \
			NPCINK_CLOUD_DATABASE_URL="${database_url}" \
			"${PYTHON_BIN}" -m alembic -c "${ALEMBIC_CONFIG}" upgrade head
	) >&2
}

sha256_file() {
	isolated_python - "$1" <<'PY'
import hashlib
import sys

digest = hashlib.sha256()
with open(sys.argv[1], "rb") as stream:
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
print(digest.hexdigest())
PY
}

verify_checksum() {
	local path="$1"
	local expected="$2"
	[[ "$(sha256_file "${path}")" == "${expected}" ]]
}

write_artifact_manifest() {
	local root="$1"
	local output="$2"
	isolated_python - "${root}" "${output}" <<'PY'
from __future__ import annotations

import hashlib
import os
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve(strict=True)
output = Path(sys.argv[2])
rows: list[str] = []
for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
    relative = path.relative_to(root).as_posix()
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise SystemExit(f"artifact manifest rejects symlink: {relative}")
    if stat.S_ISDIR(info.st_mode):
        continue
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise SystemExit(f"artifact manifest rejects unsafe entry: {relative}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    rows.append(
        f"{relative}\t{stat.S_IMODE(info.st_mode):04o}\t{info.st_size}\t{digest.hexdigest()}"
    )
if not rows:
    raise SystemExit("artifact manifest must not be empty")
output.write_text("\n".join(rows) + "\n", encoding="utf-8")
os.chmod(output, 0o600)
PY
}

safe_extract_artifact_archive() {
	local archive="$1"
	local destination="$2"
	isolated_python - "${archive}" "${destination}" <<'PY'
from __future__ import annotations

import os
import shutil
import stat
import sys
import tarfile
from pathlib import Path, PurePosixPath

archive_path = Path(sys.argv[1])
destination = Path(sys.argv[2])
destination.mkdir(mode=0o700, parents=True, exist_ok=False)
with tarfile.open(archive_path, mode="r:*") as bundle:
    members = bundle.getmembers()
    if not members:
        raise SystemExit("artifact archive must not be empty")
    for member in members:
        relative = PurePosixPath(member.name)
        if relative.is_absolute() or ".." in relative.parts:
            raise SystemExit("artifact archive contains an unsafe path")
        if member.name in {".", "./"}:
            continue
        target = destination.joinpath(*[part for part in relative.parts if part != "."])
        if member.isdir():
            target.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(target, stat.S_IMODE(member.mode))
            continue
        if not member.isfile():
            raise SystemExit("artifact archive contains a non-regular entry")
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        source = bundle.extractfile(member)
        if source is None:
            raise SystemExit("artifact archive entry is unreadable")
        with source, target.open("xb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)
        os.chmod(target, stat.S_IMODE(member.mode))
PY
}

start_postgres() {
	local container="$1"
	local volume="$2"
	docker volume create \
		--label "npcink.contract=${CONTRACT}" \
		--label "npcink.resource-prefix=${RESOURCE_PREFIX}" \
		"${volume}" >/dev/null
	docker run -d \
		--name "${container}" \
		--network "${NETWORK}" \
		--label "npcink.contract=${CONTRACT}" \
		--label "npcink.resource-prefix=${RESOURCE_PREFIX}" \
		-p '127.0.0.1::5432' \
		-e POSTGRES_USER="${DB_USER}" \
		-e POSTGRES_PASSWORD="${DB_PASSWORD}" \
		-e POSTGRES_DB="${DB_NAME}" \
		-v "${volume}:/var/lib/postgresql/data" \
		--health-cmd "pg_isready -U ${DB_USER} -d ${DB_NAME}" \
		--health-interval 1s \
		--health-timeout 3s \
		--health-retries "${TIMEOUT_SECONDS}" \
		"${POSTGRES_IMAGE}" >/dev/null
}

wait_for_postgres() {
	local container="$1"
	local deadline=$((SECONDS + TIMEOUT_SECONDS))
	while ((SECONDS < deadline)); do
		if docker exec "${container}" pg_isready -U "${DB_USER}" -d "${DB_NAME}" >/dev/null 2>&1; then
			return 0
		fi
		sleep 1
	done
	docker logs "${container}" >&2 || true
	return 1
}

container_port() {
	local binding
	binding="$(docker port "$1" 5432/tcp | head -n 1)"
	local port="${binding##*:}"
	[[ "${port}" =~ ^[0-9]+$ ]] || return 1
	printf '%s\n' "${port}"
}

postgres_version_num() {
	docker exec "$1" psql -X --no-psqlrc -At \
		-U "${DB_USER}" -d "${DB_NAME}" -c 'SHOW server_version_num'
}

database_head() {
	docker exec "$1" psql -X --no-psqlrc -At \
		-U "${DB_USER}" -d "${DB_NAME}" \
		-c 'SELECT version_num FROM alembic_version'
}

write_database_manifest() {
	local container="$1"
	local output="$2"
	docker exec -i "${container}" psql -X --no-psqlrc -At -F $'\t' \
		-U "${DB_USER}" -d "${DB_NAME}" >"${output}" <<'SQL'
SELECT 'alembic', version_num FROM alembic_version ORDER BY version_num;
SELECT 'account', account_id, name, status FROM accounts ORDER BY account_id;
SELECT 'principal', principal_id, email, status, session_version::text FROM principals ORDER BY principal_id;
SELECT 'membership_relation', m.membership_id, p.principal_id, p.email, a.account_id, a.name, m.role, m.status
FROM account_user_memberships AS m
JOIN principals AS p ON p.principal_id = m.principal_id
JOIN accounts AS a ON a.account_id = m.account_id
ORDER BY m.membership_id;
SELECT 'site_relation', s.site_id, s.account_id, a.name, s.site_url, s.platform_kind, s.status
FROM sites AS s JOIN accounts AS a ON a.account_id = s.account_id ORDER BY s.site_id;
SELECT 'run_relation', r.run_id, r.site_id, r.account_id, r.ability_name, r.status, r.trace_id
FROM run_records AS r JOIN sites AS s ON s.site_id = r.site_id ORDER BY r.run_id;
SELECT 'artifact_relation', m.artifact_id, m.run_id, m.site_id, m.storage_key,
       m.byte_size::text, m.checksum, m.status
FROM media_artifacts AS m JOIN run_records AS r ON r.run_id = m.run_id ORDER BY m.artifact_id;
SELECT 'delivery_relation', d.delivery_id, d.artifact_id, d.site_id,
       d.expected_byte_size::text, d.expected_checksum, d.pull_trace_id
FROM media_artifact_deliveries AS d
JOIN media_artifacts AS m ON m.artifact_id = d.artifact_id
ORDER BY d.delivery_id;
SELECT 'relationship_count', count(*)::text
FROM accounts AS a
JOIN account_user_memberships AS m ON m.account_id = a.account_id
JOIN principals AS p ON p.principal_id = m.principal_id
JOIN sites AS s ON s.account_id = a.account_id
JOIN run_records AS r ON r.site_id = s.site_id AND r.account_id = a.account_id
JOIN media_artifacts AS ma ON ma.run_id = r.run_id AND ma.site_id = s.site_id
JOIN media_artifact_deliveries AS d ON d.artifact_id = ma.artifact_id AND d.site_id = s.site_id;
SQL
	chmod 600 "${output}"
}

assert_docker_resources_absent() {
	! docker container inspect "${SOURCE_CONTAINER}" >/dev/null 2>&1 || return 1
	! docker container inspect "${RESTORE_CONTAINER}" >/dev/null 2>&1 || return 1
	! docker volume inspect "${SOURCE_VOLUME}" >/dev/null 2>&1 || return 1
	! docker volume inspect "${RESTORE_VOLUME}" >/dev/null 2>&1 || return 1
	! docker network inspect "${NETWORK}" >/dev/null 2>&1 || return 1
}

CURRENT_STAGE="migration-head-resolution"
ALEMBIC_HEAD="$(resolve_alembic_head)"
[[ -n "${ALEMBIC_HEAD}" ]] || die "Alembic head resolution returned no revision"
write_isolated_alembic_config
log "resolved Alembic head ${ALEMBIC_HEAD}"

CURRENT_STAGE="docker-source-start"
docker network create \
	--label "npcink.contract=${CONTRACT}" \
	--label "npcink.resource-prefix=${RESOURCE_PREFIX}" \
	"${NETWORK}" >/dev/null
start_postgres "${SOURCE_CONTAINER}" "${SOURCE_VOLUME}"
wait_for_postgres "${SOURCE_CONTAINER}" || die "source PostgreSQL did not become ready"
SOURCE_PORT="$(container_port "${SOURCE_CONTAINER}")" || die "source port discovery failed"
SOURCE_POSTGRES_VERSION="$(postgres_version_num "${SOURCE_CONTAINER}")"
if [[ ! "${SOURCE_POSTGRES_VERSION}" =~ ^[0-9]+$ ]] || \
	((SOURCE_POSTGRES_VERSION < 160000 || SOURCE_POSTGRES_VERSION >= 170000)); then
	die "source database is not PostgreSQL 16"
fi

CURRENT_STAGE="source-migration"
run_migrations "${SOURCE_PORT}"
SOURCE_HEAD="$(database_head "${SOURCE_CONTAINER}")"
[[ "${SOURCE_HEAD}" == "${ALEMBIC_HEAD}" ]] || die "source schema head mismatch"

CURRENT_STAGE="artifact-seed"
isolated_python - "${SOURCE_ARTIFACT_ROOT}" >"${TMP_DIR}/artifact-seed.tsv" <<'PY'
from io import BytesIO
import sys

from app.domain.media_artifacts import LocalVolumeArtifactStore

payload = b"\x89PNG\r\n\x1a\n" + b"npcink-p5-b5-backup-restore-drill\n"
stored = LocalVolumeArtifactStore(sys.argv[1]).put(BytesIO(payload), max_bytes=4096)
print(f"{stored.storage_key}\t{stored.byte_size}\t{stored.checksum}")
PY
IFS=$'\t' read -r ARTIFACT_STORAGE_KEY ARTIFACT_BYTE_SIZE ARTIFACT_CHECKSUM \
	<"${TMP_DIR}/artifact-seed.tsv"
[[ "${ARTIFACT_STORAGE_KEY}" =~ ^obj_[0-9a-f]{32}$ ]] || die "invalid ArtifactStore key"
[[ "${ARTIFACT_BYTE_SIZE}" =~ ^[0-9]+$ ]] || die "invalid ArtifactStore byte size"
[[ "${ARTIFACT_CHECKSUM}" =~ ^sha256:[0-9a-f]{64}$ ]] || die "invalid ArtifactStore checksum"

CURRENT_STAGE="database-seed"
docker exec -i "${SOURCE_CONTAINER}" psql -X --no-psqlrc \
	--set ON_ERROR_STOP=1 \
	--set=artifact_storage_key="${ARTIFACT_STORAGE_KEY}" \
	--set=artifact_byte_size="${ARTIFACT_BYTE_SIZE}" \
	--set=artifact_checksum="${ARTIFACT_CHECKSUM}" \
	-U "${DB_USER}" -d "${DB_NAME}" >/dev/null <<'SQL'
INSERT INTO accounts (account_id, name, status, metadata_json)
VALUES ('acct_restore_drill', 'Restore Drill Account', 'active', '{"source":"p5-b5-restore-drill"}'::json);
INSERT INTO principals (principal_id, email, status, session_version, metadata_json)
VALUES ('prn_restore_drill', 'restore-drill@example.invalid', 'active', 3,
        '{"source":"p5-b5-restore-drill"}'::json);
INSERT INTO account_user_memberships
    (membership_id, principal_id, account_id, role, status, allowed_actions_json, metadata_json)
VALUES ('mem_restore_drill', 'prn_restore_drill', 'acct_restore_drill', 'user', 'active',
        '["portal.read"]'::json, '{"source":"p5-b5-restore-drill"}'::json);
INSERT INTO sites
    (site_id, account_id, name, status, site_url, platform_kind, metadata_json,
     provisioned_at, activated_at)
VALUES ('site_restore_drill', 'acct_restore_drill', 'Restore Drill WordPress', 'active',
        'https://restore-drill.example.invalid', 'wordpress',
        '{"connector_id":"wordpress_ai_connector"}'::json, now(), now());
INSERT INTO run_records
    (run_id, site_id, account_id, ability_name, ability_family, contract_version,
     channel, execution_kind, execution_tier, execution_pattern, data_classification,
     profile_id, status, idempotency_key, trace_id, result_json, finished_at)
VALUES ('run_restore_drill', 'site_restore_drill', 'acct_restore_drill',
        'media/image-transform', 'media', 'wordpress_operation.v1', 'wordpress',
        'media', 'cloud', 'whole_run_offload', 'internal', 'wp-ai.image-transform.v1',
        'succeeded', 'idem_restore_drill', 'trace_restore_drill',
        '{"suggestion_only":true}'::json, now());
INSERT INTO media_artifacts
    (artifact_id, run_id, site_id, media_kind, operation, content_type, byte_size,
     checksum, storage_key, status, format, width, height, expires_at,
     processing_warnings_json)
VALUES ('art_restore_drill', 'run_restore_drill', 'site_restore_drill', 'image',
        'image.transform.v1', 'image/png', :artifact_byte_size, :'artifact_checksum',
        :'artifact_storage_key', 'available', 'png', 1, 1, now() + interval '1 day', '[]'::json);
INSERT INTO media_artifact_deliveries
    (delivery_id, artifact_id, site_id, expected_byte_size, expected_checksum,
     pull_trace_id, started_at, completed_at, completed_byte_size, completed_checksum,
     ack_deadline_at, byte_size_verified, checksum_verified)
VALUES ('delivery_restore_drill', 'art_restore_drill', 'site_restore_drill',
        :artifact_byte_size, :'artifact_checksum', 'trace_restore_drill_pull', now(), now(),
        :artifact_byte_size, :'artifact_checksum', now() + interval '10 minutes', true, true);
SQL

CURRENT_STAGE="source-manifests"
write_database_manifest "${SOURCE_CONTAINER}" "${DB_MANIFEST}"
if ! grep -Fqx $'relationship_count\t1' "${DB_MANIFEST}"; then
	sed -n '1,80p' "${DB_MANIFEST}" >&2
	die "representative relation is incomplete"
fi
write_artifact_manifest "${SOURCE_ARTIFACT_ROOT}" "${ARTIFACT_MANIFEST}"

CURRENT_STAGE="backup"
docker exec "${SOURCE_CONTAINER}" pg_dump -U "${DB_USER}" -d "${DB_NAME}" \
	--format=custom --no-owner --no-acl >"${DB_DUMP}"
chmod 600 "${DB_DUMP}"
[[ -s "${DB_DUMP}" ]] || die "database dump is empty"
docker exec -i "${SOURCE_CONTAINER}" pg_restore --list >/dev/null <"${DB_DUMP}"
# macOS bsdtar otherwise injects AppleDouble `._*` metadata files that are not
# part of the ArtifactStore recovery point.
COPYFILE_DISABLE=1 tar -C "${SOURCE_ARTIFACT_ROOT}" -cpf "${ARTIFACT_ARCHIVE}" .
chmod 600 "${ARTIFACT_ARCHIVE}"
[[ -s "${ARTIFACT_ARCHIVE}" ]] || die "artifact archive is empty"

DB_DUMP_SHA256="$(sha256_file "${DB_DUMP}")"
DB_MANIFEST_SHA256="$(sha256_file "${DB_MANIFEST}")"
ARTIFACT_ARCHIVE_SHA256="$(sha256_file "${ARTIFACT_ARCHIVE}")"
ARTIFACT_MANIFEST_SHA256="$(sha256_file "${ARTIFACT_MANIFEST}")"

isolated_python - "${RECOVERY_MANIFEST}" "${ALEMBIC_HEAD}" "${POSTGRES_IMAGE}" \
	"${DB_DUMP_SHA256}" "${DB_MANIFEST_SHA256}" "${ARTIFACT_ARCHIVE_SHA256}" \
	"${ARTIFACT_MANIFEST_SHA256}" <<'PY'
import json
import os
import sys
from pathlib import Path

(
    output,
    alembic_head,
    postgres_image,
    database_dump_sha256,
    database_manifest_sha256,
    artifact_archive_sha256,
    artifact_manifest_sha256,
) = sys.argv[1:]
payload = {
    "contract": "p5_b5_backup_restore_recovery_point.v1",
    "alembic_head": alembic_head,
    "postgres_image": postgres_image,
    "database": {
        "archive": "database.dump",
        "format": "custom",
        "sha256": database_dump_sha256,
        "manifest": "database-manifest.tsv",
        "manifest_sha256": database_manifest_sha256,
    },
    "artifact_store": {
        "archive": "artifact-store.tar",
        "sha256": artifact_archive_sha256,
        "manifest": "artifact-manifest.tsv",
        "manifest_sha256": artifact_manifest_sha256,
    },
}
Path(output).write_text(
    json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
os.chmod(output, 0o600)
PY
RECOVERY_MANIFEST_SHA256="$(sha256_file "${RECOVERY_MANIFEST}")"

CURRENT_STAGE="fault-injection-database-corruption"
CORRUPT_DB_DUMP="${TMP_DIR}/database-corrupt.dump"
cp "${DB_DUMP}" "${CORRUPT_DB_DUMP}"
printf 'injected-corruption' >>"${CORRUPT_DB_DUMP}"
if verify_checksum "${CORRUPT_DB_DUMP}" "${DB_DUMP_SHA256}"; then
	die "corrupted database dump passed checksum verification"
fi
DATABASE_CORRUPTION_REJECTED=true
rm -f -- "${CORRUPT_DB_DUMP}"

CURRENT_STAGE="fault-injection-artifact-missing"
safe_extract_artifact_archive "${ARTIFACT_ARCHIVE}" "${FAULT_ARTIFACT_ROOT}"
ARTIFACT_RELATIVE_PATH="${ARTIFACT_STORAGE_KEY:4:2}/${ARTIFACT_STORAGE_KEY:6:2}/${ARTIFACT_STORAGE_KEY}"
[[ -f "${FAULT_ARTIFACT_ROOT}/${ARTIFACT_RELATIVE_PATH}" ]] || die "seed artifact path is missing"
rm -f -- "${FAULT_ARTIFACT_ROOT}/${ARTIFACT_RELATIVE_PATH}"
write_artifact_manifest "${FAULT_ARTIFACT_ROOT}" "${TMP_DIR}/fault-artifact-manifest.tsv"
if cmp -s "${ARTIFACT_MANIFEST}" "${TMP_DIR}/fault-artifact-manifest.tsv"; then
	die "missing artifact passed manifest verification"
fi
ARTIFACT_MISSING_REJECTED=true

CURRENT_STAGE="source-destruction"
remove_container "${SOURCE_CONTAINER}"
remove_volume "${SOURCE_VOLUME}"
[[ "${CLEANUP_ERROR}" == "0" ]] || die "source Docker resources could not be removed"
rm -rf -- "${SOURCE_ARTIFACT_ROOT}" "${FAULT_ARTIFACT_ROOT}"

CURRENT_STAGE="docker-restore-start"
start_postgres "${RESTORE_CONTAINER}" "${RESTORE_VOLUME}"
wait_for_postgres "${RESTORE_CONTAINER}" || die "restore PostgreSQL did not become ready"
RESTORE_POSTGRES_VERSION="$(postgres_version_num "${RESTORE_CONTAINER}")"
[[ "${RESTORE_POSTGRES_VERSION}" == "${SOURCE_POSTGRES_VERSION}" ]] || \
	die "source and restore PostgreSQL versions differ"

CURRENT_STAGE="pre-restore-integrity"
verify_checksum "${DB_DUMP}" "${DB_DUMP_SHA256}" || die "database dump checksum mismatch"
verify_checksum "${DB_MANIFEST}" "${DB_MANIFEST_SHA256}" || die "database manifest checksum mismatch"
verify_checksum "${ARTIFACT_ARCHIVE}" "${ARTIFACT_ARCHIVE_SHA256}" || die "artifact archive checksum mismatch"
verify_checksum "${ARTIFACT_MANIFEST}" "${ARTIFACT_MANIFEST_SHA256}" || die "artifact manifest checksum mismatch"
verify_checksum "${RECOVERY_MANIFEST}" "${RECOVERY_MANIFEST_SHA256}" || die "recovery manifest checksum mismatch"

CURRENT_STAGE="database-restore"
docker exec -i "${RESTORE_CONTAINER}" pg_restore \
	-U "${DB_USER}" -d "${DB_NAME}" \
	--no-owner --no-acl --exit-on-error <"${DB_DUMP}" >&2
RESTORED_HEAD="$(database_head "${RESTORE_CONTAINER}")"
[[ "${RESTORED_HEAD}" == "${ALEMBIC_HEAD}" ]] || die "restored schema head mismatch"
write_database_manifest "${RESTORE_CONTAINER}" "${TMP_DIR}/restored-database-manifest.tsv"
cmp -s "${DB_MANIFEST}" "${TMP_DIR}/restored-database-manifest.tsv" || \
	die "restored database manifest differs"
DATABASE_MANIFEST_MATCH=true
RELATIONSHIP_COUNT="$(docker exec "${RESTORE_CONTAINER}" psql -X --no-psqlrc -At \
	-U "${DB_USER}" -d "${DB_NAME}" -c \
	"SELECT count(*) FROM accounts a JOIN account_user_memberships m ON m.account_id=a.account_id JOIN principals p ON p.principal_id=m.principal_id JOIN sites s ON s.account_id=a.account_id JOIN run_records r ON r.site_id=s.site_id AND r.account_id=a.account_id JOIN media_artifacts ma ON ma.run_id=r.run_id AND ma.site_id=s.site_id JOIN media_artifact_deliveries d ON d.artifact_id=ma.artifact_id AND d.site_id=s.site_id")"
[[ "${RELATIONSHIP_COUNT}" == "1" ]] || die "restored representative relation failed"

CURRENT_STAGE="artifact-restore"
safe_extract_artifact_archive "${ARTIFACT_ARCHIVE}" "${RESTORED_ARTIFACT_ROOT}"
write_artifact_manifest "${RESTORED_ARTIFACT_ROOT}" "${TMP_DIR}/restored-artifact-manifest.tsv"
if ! cmp -s "${ARTIFACT_MANIFEST}" "${TMP_DIR}/restored-artifact-manifest.tsv"; then
	diff -u "${ARTIFACT_MANIFEST}" "${TMP_DIR}/restored-artifact-manifest.tsv" >&2 || true
	die "restored ArtifactStore manifest differs"
fi
ARTIFACT_MANIFEST_MATCH=true
isolated_python - "${RESTORED_ARTIFACT_ROOT}" "${ARTIFACT_STORAGE_KEY}" \
	"${ARTIFACT_BYTE_SIZE}" "${ARTIFACT_CHECKSUM}" <<'PY'
import hashlib
import sys
from pathlib import Path

root, storage_key, expected_size, expected_checksum = sys.argv[1:]
path = Path(root) / storage_key[4:6] / storage_key[6:8] / storage_key
payload = path.read_bytes()
actual_checksum = "sha256:" + hashlib.sha256(payload).hexdigest()
if len(payload) != int(expected_size) or actual_checksum != expected_checksum:
    raise SystemExit("restored artifact metadata differs from database evidence")
PY

CURRENT_STAGE="cleanup"
cleanup_docker || die "Docker resource cleanup failed"
assert_docker_resources_absent || die "temporary Docker resources remain"
DOCKER_RESOURCES_REMOVED=true

FINISHED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
FINISHED_EPOCH="$(date '+%s')"
DURATION_SECONDS=$((FINISHED_EPOCH - STARTED_EPOCH))
POSTGRES_IMAGE_ID="$(docker image inspect "${POSTGRES_IMAGE}" --format '{{.Id}}')"

CURRENT_STAGE="evidence-summary"
SUMMARY_JSON="$(isolated_python - \
	"${CONTRACT}" "${STARTED_AT}" "${FINISHED_AT}" "${DURATION_SECONDS}" \
	"${RESOURCE_PREFIX}" "${POSTGRES_IMAGE}" "${POSTGRES_IMAGE_ID}" \
	"${SOURCE_POSTGRES_VERSION}" "${ALEMBIC_HEAD}" "${DB_DUMP_SHA256}" \
	"${DB_MANIFEST_SHA256}" "${ARTIFACT_ARCHIVE_SHA256}" \
	"${ARTIFACT_MANIFEST_SHA256}" "${RECOVERY_MANIFEST_SHA256}" \
	"${RELATIONSHIP_COUNT}" <<'PY'
import json
import sys

(
    contract,
    started_at,
    finished_at,
    duration_seconds,
    resource_prefix,
    postgres_image,
    postgres_image_id,
    postgres_version_num,
    alembic_head,
    database_dump_sha256,
    database_manifest_sha256,
    artifact_archive_sha256,
    artifact_manifest_sha256,
    recovery_manifest_sha256,
    relationship_count,
) = sys.argv[1:]
payload = {
    "contract": contract,
    "status": "passed",
    "started_at": started_at,
    "finished_at": finished_at,
    "duration_seconds": int(duration_seconds),
    "resource_prefix": resource_prefix,
    "postgres": {
        "image": postgres_image,
        "image_id": postgres_image_id,
        "server_version_num": int(postgres_version_num),
        "major": 16,
    },
    "alembic_head": alembic_head,
    "backup": {
        "database_format": "custom",
        "database_sha256": database_dump_sha256,
        "database_manifest_sha256": database_manifest_sha256,
        "artifact_archive_sha256": artifact_archive_sha256,
        "artifact_manifest_sha256": artifact_manifest_sha256,
        "recovery_manifest_sha256": recovery_manifest_sha256,
    },
    "fault_injection": {
        "database_corruption_rejected": True,
        "artifact_missing_rejected": True,
    },
    "restore": {
        "database_manifest_match": True,
        "artifact_manifest_match": True,
        "relationship_count": int(relationship_count),
    },
    "cleanup": {
        "docker_resources_removed": True,
        "temporary_directory_removed": True,
    },
    "local_docker_unix_socket_verified": True,
    "production_contacted": False,
}
print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
PY
)"
CURRENT_STAGE="temporary-directory-cleanup"
rm -rf -- "${TMP_DIR}" || die "temporary directory cleanup failed"
[[ ! -e "${TMP_DIR}" ]] || die "temporary directory remains"
CURRENT_STAGE="evidence-summary"
printf '%s\n' "${SUMMARY_JSON}"
SUMMARY_EMITTED=1
