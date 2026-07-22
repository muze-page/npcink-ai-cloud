#!/usr/bin/env bash
set -euo pipefail
set +x

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
. "${ROOT_DIR}/deploy/common.sh"
npcink_ai_cloud_require_deploy_lock_owner "${ROOT_DIR}"
npcink_ai_cloud_load_env_file "${ROOT_DIR}"
npcink_ai_cloud_require_cmd docker

RELEASE_TOOL_PYTHON="${NPCINK_CLOUD_RELEASE_TOOL_PYTHON:-/usr/bin/python3.11}"
MANIFEST_HELPER="${ROOT_DIR}/scripts/verify-release-bundle-manifest.py"
npcink_ai_cloud_require_host_release_tool_python "${RELEASE_TOOL_PYTHON}"
export NPCINK_CLOUD_RELEASE_TOOL_PYTHON="${RELEASE_TOOL_PYTHON}"
EXPECTED_API_IMAGE_ID="$(
	"${RELEASE_TOOL_PYTHON}" "${MANIFEST_HELPER}" loaded-role-daemon-id \
		--root "${ROOT_DIR}" --role api
)"

if ! npcink_ai_cloud_compose_run_with_image_proof \
	"${ROOT_DIR}" api npcink-ai-cloud-api:prod "${EXPECTED_API_IMAGE_ID}" \
	sh -ceu 'python - <<'"'"'PY'"'"'
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine
from scripts.alembic_revision_gate import require_upgradeable_revisions

settings = get_settings()
engine = get_engine(
    settings.database_url,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout_seconds=settings.database_pool_timeout_seconds,
    pool_recycle_seconds=settings.database_pool_recycle_seconds,
    connect_timeout_seconds=settings.database_connect_timeout_seconds,
)
with engine.connect() as connection:
    version_num = int(connection.execute(text("SHOW server_version_num")).scalar_one())
    if version_num // 10000 != 18:
        raise SystemExit(2)
    observed = {
        str(row[0])
        for row in connection.execute(text("SELECT version_num FROM alembic_version"))
    }
try:
    require_upgradeable_revisions(
        ScriptDirectory.from_config(Config("alembic.ini")), observed
    )
except ValueError:
    raise SystemExit(3)
PY' >/dev/null 2>&1; then
	echo "[fail] Candidate image could not prove protected runtime config, PostgreSQL 18 TLS reachability, and an upgradeable Alembic revision." >&2
	exit 1
fi

echo "[ok] Candidate image proved protected runtime config, PostgreSQL 18 TLS reachability, and an upgradeable Alembic revision before writers stopped."
