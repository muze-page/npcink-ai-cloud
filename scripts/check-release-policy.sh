#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

require_file() {
	local path="$1"
	if [ ! -f "${ROOT_DIR}/${path}" ]; then
		echo "[fail] Missing required release policy file: ${path}" >&2
		exit 1
	fi
}

require_marker() {
	local path="$1"
	local marker="$2"
	if ! grep -Fq "${marker}" "${ROOT_DIR}/${path}"; then
		echo "[fail] Missing release policy marker in ${path}: ${marker}" >&2
		exit 1
	fi
}

require_file "docs/cloud-production-release-policy-v1.md"
require_file "deploy/PRODUCTION_GITHUB_DEPLOY.md"
require_file "deploy/RELEASE_CHECKLIST.md"
require_file ".github/pull_request_template.md"
require_file ".github/workflows/ci.yml"
require_file ".github/workflows/deploy-production.yml"

require_marker "docs/cloud-production-release-policy-v1.md" "master"
require_marker "docs/cloud-production-release-policy-v1.md" "production"
require_marker "docs/cloud-production-release-policy-v1.md" "Approved for production validation by operator."
require_marker "docs/cloud-production-release-policy-v1.md" "Do not directly edit production application code on the server."
require_marker "docs/cloud-production-release-policy-v1.md" "Cloud is not becoming a WordPress write owner"

require_marker ".github/pull_request_template.md" "Focused module:"
require_marker ".github/pull_request_template.md" "Cloud boundary impact:"
require_marker ".github/pull_request_template.md" "Approved for production validation by operator."
require_marker ".github/pull_request_template.md" "does not commit production secrets"

require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "docs/cloud-production-release-policy-v1.md"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "pnpm run check:release-policy"
require_marker ".github/workflows/ci.yml" "github.ref == 'refs/heads/production'"
require_marker ".github/workflows/ci.yml" "environment: production"
require_marker ".github/workflows/deploy-production.yml" "github.ref == 'refs/heads/production'"

echo "[ok] Lightweight release policy gate passed"
