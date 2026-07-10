#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLOUD_DIR="${ROOT_DIR}"

cd "${CLOUD_DIR}"

POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-perimeter-prod-password-32-characters-secret}" \
NPCINK_CLOUD_DATABASE_URL="${NPCINK_CLOUD_DATABASE_URL:-postgresql+psycopg://npcink:perimeter-prod-password-32-characters-secret@postgres:5432/npcink_ai_cloud}" \
  docker compose -f docker-compose.prod.yml config >/dev/null
docker compose -f docker-compose.dev.yml run --rm \
  -e NPCINK_CLOUD_OPENAI_API_KEY= \
  api python -m pytest tests/api/test_health.py tests/contract/test_health_contract.py -q
