#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.pg18-proof.yml"
PROJECT_NAME="npcink-ai-cloud-pg18-proof-${PPID}-$$"

cleanup() {
	COMPOSE_PROJECT_NAME="${PROJECT_NAME}" \
		docker compose -f "${COMPOSE_FILE}" --profile proof down -v --remove-orphans \
			>/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[info] Starting local PostgreSQL 18 proof target (no TLS; not RDS evidence)."
COMPOSE_PROJECT_NAME="${PROJECT_NAME}" \
	docker compose -f "${COMPOSE_FILE}" up -d --wait postgres18-proof

echo "[info] Applying the complete Alembic history to an empty PostgreSQL 18 database."
COMPOSE_PROJECT_NAME="${PROJECT_NAME}" \
	docker compose -f "${COMPOSE_FILE}" --profile proof run --rm migration-proof

echo "[info] Replaying Alembic head to prove migration idempotence."
COMPOSE_PROJECT_NAME="${PROJECT_NAME}" \
	docker compose -f "${COMPOSE_FILE}" --profile proof run --rm migration-proof

echo "[info] Proving PostgreSQL 18 runtime semantics with disposable rows (no TLS; not RDS evidence)."
COMPOSE_PROJECT_NAME="${PROJECT_NAME}" \
	docker compose -f "${COMPOSE_FILE}" --profile proof run --rm \
		migration-proof python scripts/pg18-semantic-proof.py

COMPOSE_PROJECT_NAME="${PROJECT_NAME}" \
	docker compose -f "${COMPOSE_FILE}" exec -T postgres18-proof \
		psql -v ON_ERROR_STOP=1 -U npcink -d npcink_ai_cloud -Atc \
		"select case when current_setting('server_version_num')::int >= 180000 and current_setting('server_version_num')::int < 190000 then 'postgresql-18' else current_setting('server_version') end"

echo "[ok] Local/CI PostgreSQL 18 schema proof passed; RDS TLS, private networking, backup, restart, availability, and capacity remain separate gates."
