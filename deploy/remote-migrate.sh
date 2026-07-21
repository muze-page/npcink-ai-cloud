#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

# Shared compose/env helpers for deploy scripts.
. "${ROOT_DIR}/deploy/common.sh"
npcink_ai_cloud_require_deploy_lock_owner "${ROOT_DIR}"

npcink_ai_cloud_require_cmd docker
RELEASE_TOOL_PYTHON="$(npcink_ai_cloud_release_tool_python)"
MANIFEST_HELPER="${ROOT_DIR}/scripts/verify-release-bundle-manifest.py"
npcink_ai_cloud_require_release_tool_python "${RELEASE_TOOL_PYTHON}"
EXPECTED_API_IMAGE_ID="$(
	"${RELEASE_TOOL_PYTHON}" "${MANIFEST_HELPER}" loaded-role-daemon-id \
		--root "${ROOT_DIR}" --role api
)"

npcink_ai_cloud_run_timed "wait for database auth" \
	npcink_ai_cloud_compose_run_with_image_proof \
	"${ROOT_DIR}" api npcink-ai-cloud-api:prod "${EXPECTED_API_IMAGE_ID}" python -c '
import os
import sys
import time

import psycopg

url = os.environ["NPCINK_CLOUD_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
last_error = None
for _ in range(30):
    try:
        with psycopg.connect(url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                cursor.fetchone()
        sys.exit(0)
    except Exception as exc:
        last_error = exc
        time.sleep(2)

print(f"[fail] Database authentication did not become ready: {last_error}", file=sys.stderr)
sys.exit(1)
'
npcink_ai_cloud_run_timed "alembic upgrade" \
	npcink_ai_cloud_compose_run_with_image_proof \
	"${ROOT_DIR}" api npcink-ai-cloud-api:prod "${EXPECTED_API_IMAGE_ID}" \
	alembic upgrade head
echo "[ok] Migration completed without starting application services."
