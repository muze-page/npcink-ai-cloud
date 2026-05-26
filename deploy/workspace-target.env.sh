#!/usr/bin/env bash

# Workspace-local remote deploy target for Magick AI Cloud.
# Source this file before running deploy helpers:
#   source cloud/deploy/workspace-target.env.sh
#
# Still required before real deploy:
# - MAGICK_CLOUD_DEPLOY_SSH_USER
# - MAGICK_CLOUD_BASE_URL
# - MAGICK_CLOUD_ENV_FILE (or cloud/.env.deploy in place)

export MAGICK_CLOUD_DEPLOY_SSH_HOST="114.132.150.46"
export MAGICK_CLOUD_DEPLOY_SSH_USER="root"
export MAGICK_CLOUD_DEPLOY_IDENTITY_FILE="../../config/key/Magick_AI.pem"
export MAGICK_CLOUD_BASE_URL="https://magick.sofile.cn"
export MAGICK_CLOUD_PORTAL_PUBLIC_BASE_URL="https://magick.sofile.cn"
export MAGICK_CLOUD_DOMAIN_NAME="magick.sofile.cn"
export MAGICK_CLOUD_DOMAIN_CERT_PATH="../../config/magick.sofile.cn_nginx-ssl/magick.sofile.cn.pem"
export MAGICK_CLOUD_DOMAIN_KEY_PATH="../../config/magick.sofile.cn_nginx-ssl/magick.sofile.cn.key"
export MAGICK_CLOUD_DOMAIN_UPSTREAM_URL="http://127.0.0.1:8010"

# Optional overrides. Keep commented until the real values are confirmed.
# export MAGICK_CLOUD_DEPLOY_REMOTE_DIR="/opt/magick-ai-cloud"
# export MAGICK_CLOUD_ENV_FILE="../../cloud/.env.deploy"
# export MAGICK_CLOUD_WP_CRON_SITE_BASE_URL="https://example-wordpress-site.test"
# export MAGICK_CLOUD_WP_CRON_SCHEDULE="*/5 * * * *"
# export MAGICK_CLOUD_WP_CRON_CURL_TIMEOUT_SECONDS="90"
