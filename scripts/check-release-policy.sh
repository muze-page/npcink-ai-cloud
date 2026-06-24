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
	if ! grep -Fq -- "${marker}" "${ROOT_DIR}/${path}"; then
		echo "[fail] Missing release policy marker in ${path}: ${marker}" >&2
		exit 1
	fi
}

require_file "docs/cloud-production-release-policy-v1.md"
require_file "deploy/PRODUCTION_GITHUB_DEPLOY.md"
require_file "deploy/RELEASE_CHECKLIST.md"
require_file "AGENTS.md"
require_file ".github/pull_request_template.md"
require_file ".github/workflows/ci.yml"
require_file ".github/workflows/deploy-production.yml"
require_file "site/terms/en/terms.html"
require_file "site/terms/en/privacy.html"
require_file "site/terms/en/data-retention.html"
require_file "site/terms/zh/terms.html"
require_file "site/terms/zh/privacy.html"
require_file "site/terms/zh/data-retention.html"

require_marker "AGENTS.md" "AI Production Operation Rules"
require_marker "AGENTS.md" "Production source branch is \`production\`"
require_marker "AGENTS.md" "development integration branch is"
require_marker "AGENTS.md" "Do not directly edit production application code on the server."
require_marker "AGENTS.md" "Any emergency server fix must be backported to Git before the next deploy."
require_marker "AGENTS.md" "Do not commit SMTP passwords"
require_marker "AGENTS.md" "Do not push or deploy to Gitee unless the user explicitly asks."
require_marker "AGENTS.md" "pnpm run check:release-policy"

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
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "/terms/en/terms.html"
require_marker "deploy/bundle-images.sh" "-C \"\${CLOUD_DIR}\" site"
require_marker "deploy/remote-smoke.sh" "/terms/en/terms.html"
require_marker "deploy/remote-smoke.sh" "/terms/zh/terms.html"
require_marker "deploy/remote-smoke.sh" "/terms/styles.css"
require_marker "docker-compose.runtime.yml" "./site:/usr/share/nginx/html/npcink-site:ro"
require_marker "deploy/nginx.prod.conf" "location /terms/"
require_marker ".github/workflows/ci.yml" "github.ref == 'refs/heads/production'"
require_marker ".github/workflows/ci.yml" "environment: production"
require_marker ".github/workflows/deploy-production.yml" "github.ref == 'refs/heads/production'"

echo "[ok] Lightweight release policy gate passed"
