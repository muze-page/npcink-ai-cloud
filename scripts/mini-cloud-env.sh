#!/usr/bin/env bash

# Shared defaults for Mac mini remote dev/deploy helpers.
# This workspace intentionally targets one fixed personal Mac mini by default.
# Keep these defaults for local convenience; do not treat this file as a
# multi-environment or team-shared target registry.
# If the mini host/IP changes, update this file or override via
# `scripts/mini-cloud.env`.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="${MINI_CLOUD_ENV_FILE:-${SCRIPT_DIR}/mini-cloud.env}"

if [ -f "${ENV_FILE}" ]; then
	# shellcheck disable=SC1090
	source "${ENV_FILE}"
fi

export MINI_CLOUD_REMOTE_HOST="${MINI_CLOUD_REMOTE_HOST:-muze@100.102.170.79}"
export MINI_CLOUD_REMOTE_IP="${MINI_CLOUD_REMOTE_IP:-100.102.170.79}"
export MINI_CLOUD_REMOTE_ROOT="${MINI_CLOUD_REMOTE_ROOT:-~/gitee/magick-ai-cloud}"
export MINI_CLOUD_REMOTE_PROJECT_DIR="${MINI_CLOUD_REMOTE_PROJECT_DIR:-${MINI_CLOUD_REMOTE_ROOT}}"
