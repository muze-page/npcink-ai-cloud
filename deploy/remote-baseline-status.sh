#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# Shared compose/env helpers for deploy scripts.
. "${ROOT_DIR}/deploy/common.sh"

magick_ai_cloud_require_cmd docker

magick_ai_cloud_compose "${ROOT_DIR}" exec -T api python -m app.dev.baseline_status
