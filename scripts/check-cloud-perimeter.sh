#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLOUD_DIR="${ROOT_DIR}"

cd "${CLOUD_DIR}"

POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-perimeter-prod-password-32-characters-secret}" \
MAGICK_CLOUD_DATABASE_URL="${MAGICK_CLOUD_DATABASE_URL:-postgresql+psycopg://magick:perimeter-prod-password-32-characters-secret@postgres:5432/magick_ai_cloud}" \
  docker compose -f docker-compose.prod.yml config >/dev/null
docker compose -f docker-compose.dev.yml run --rm api python -m pytest tests/api/test_health.py tests/contract/test_health_contract.py -q
