#!/usr/bin/env bash

# Workspace-local remote deploy target for Npcink AI Cloud.
# Source this file before running deploy helpers:
#   source deploy/workspace-target.env.sh
#
# Still required before real deploy:
# - operator-held SSH password, key, or an already configured SSH agent/session
# - NPCINK_CLOUD_ENV_FILE (or .env.deploy in place)

export NPCINK_CLOUD_DEPLOY_SSH_HOST="120.24.237.214"
export NPCINK_CLOUD_DEPLOY_SSH_USER="root"
export NPCINK_CLOUD_BASE_URL="https://cloud.npc.ink"
export NPCINK_CLOUD_DOMAIN_NAME="cloud.npc.ink"
export NPCINK_CLOUD_DOMAIN_UPSTREAM_URL="http://127.0.0.1:8010"

# Optional overrides. Keep commented until the real values are confirmed.
# export NPCINK_CLOUD_DEPLOY_IDENTITY_FILE="/path/to/operator-held-key.pem"
# export NPCINK_CLOUD_DOMAIN_CERT_PATH="/path/to/cloud.npc.ink.pem"
# export NPCINK_CLOUD_DOMAIN_KEY_PATH="/path/to/cloud.npc.ink.key"
# export NPCINK_CLOUD_DEPLOY_REMOTE_DIR="/opt/npcink-ai-cloud"
# export NPCINK_CLOUD_ENV_FILE=".env.deploy"
# export NPCINK_CLOUD_WP_CRON_SITE_BASE_URL="https://example-wordpress-site.test"
# export NPCINK_CLOUD_WP_CRON_SCHEDULE="*/5 * * * *"
# export NPCINK_CLOUD_WP_CRON_CURL_TIMEOUT_SECONDS="90"
