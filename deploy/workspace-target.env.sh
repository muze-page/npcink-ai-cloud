#!/usr/bin/env bash

# Workspace-local remote deploy target for Npcink AI Cloud.
# Source this file before running deploy helpers:
#   source deploy/workspace-target.env.sh
#
# Still required before real deploy:
# - NPCINK_CLOUD_DEPLOY_SSH_USER
# - NPCINK_CLOUD_BASE_URL
# - NPCINK_CLOUD_ENV_FILE (or .env.deploy in place)

export NPCINK_CLOUD_DEPLOY_SSH_HOST="114.132.150.46"
export NPCINK_CLOUD_DEPLOY_SSH_USER="root"
export NPCINK_CLOUD_DEPLOY_IDENTITY_FILE="../../config/key/Magick_AI.pem"
export NPCINK_CLOUD_BASE_URL="https://magick.sofile.cn"
export NPCINK_CLOUD_DOMAIN_NAME="magick.sofile.cn"
export NPCINK_CLOUD_DOMAIN_CERT_PATH="../../config/magick.sofile.cn_nginx-ssl/magick.sofile.cn.pem"
export NPCINK_CLOUD_DOMAIN_KEY_PATH="../../config/magick.sofile.cn_nginx-ssl/magick.sofile.cn.key"
export NPCINK_CLOUD_DOMAIN_UPSTREAM_URL="http://127.0.0.1:8010"

# Optional overrides. Keep commented until the real values are confirmed.
# export NPCINK_CLOUD_DEPLOY_REMOTE_DIR="/opt/npcink-ai-cloud"
# export NPCINK_CLOUD_ENV_FILE=".env.deploy"
# export NPCINK_CLOUD_WP_CRON_SITE_BASE_URL="https://example-wordpress-site.test"
# export NPCINK_CLOUD_WP_CRON_SCHEDULE="*/5 * * * *"
# export NPCINK_CLOUD_WP_CRON_CURL_TIMEOUT_SECONDS="90"
