#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

SITE_ID="${NPCINK_CLOUD_DEV_PORTAL_SITE_ID:-site_smoke}"
MEMBER_EMAIL="${NPCINK_CLOUD_DEV_PORTAL_EMAIL:-portal-demo@example.com}"
KEY_ID="${NPCINK_CLOUD_DEV_SITE_KEY_ID:-key_default}"
SECRET="${NPCINK_CLOUD_DEV_SITE_SECRET:-npcink-cloud-test-secret}"
PUBLIC_BASE_URL="${NPCINK_CLOUD_DEV_PORTAL_PUBLIC_BASE_URL:-http://127.0.0.1:8010}"
COMPOSE_PROJECT_NAME="${NPCINK_CLOUD_COMPOSE_PROJECT_NAME:-${COMPOSE_PROJECT_NAME:-npcink-ai-cloud}}"

cd "${ROOT_DIR}"

COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose -f docker-compose.dev.yml run --rm api \
	python -m app.dev.seed_runtime \
		--site-id "${SITE_ID}" \
		--key-id "${KEY_ID}" \
		--secret "${SECRET}" \
		--site-name "Npcink Local Smoke Site" \
		--skip-catalog-refresh \
		--skip-health-scan

COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" docker compose -f docker-compose.dev.yml run --rm api \
	python -m app.dev.bootstrap_portal_site \
		--site-id "${SITE_ID}" \
		--site-admin-email "${MEMBER_EMAIL}" \
		--public-base-url "${PUBLIC_BASE_URL}" \
		--skip-billing-rebuild
