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

reject_marker() {
	local path="$1"
	local marker="$2"
	if grep -Fq -- "${marker}" "${ROOT_DIR}/${path}"; then
		echo "[fail] Forbidden release policy marker in ${path}: ${marker}" >&2
		exit 1
	fi
}

require_executable() {
	local path="$1"
	if [ ! -x "${ROOT_DIR}/${path}" ]; then
		echo "[fail] Required release policy script is not executable: ${path}" >&2
		exit 1
	fi
}

require_marker_before() {
	local path="$1"
	local earlier="$2"
	local later="$3"
	local earlier_line
	local later_line
	earlier_line="$(grep -n -F -m 1 -- "${earlier}" "${ROOT_DIR}/${path}" | cut -d: -f1)"
	later_line="$(grep -n -F -m 1 -- "${later}" "${ROOT_DIR}/${path}" | cut -d: -f1)"
	if [ -z "${earlier_line}" ] || [ -z "${later_line}" ] || [ "${earlier_line}" -ge "${later_line}" ]; then
		echo "[fail] Release policy markers are out of order in ${path}: ${earlier} before ${later}" >&2
		exit 1
	fi
}

compose_service_block() {
	local path="$1"
	local service="$2"
	awk -v service="${service}" '
		$0 == "  " service ":" { in_service = 1 }
		in_service && $0 ~ /^  [A-Za-z0-9_-]+:$/ && $0 != "  " service ":" { exit }
		in_service { print }
	' "${ROOT_DIR}/${path}"
}

require_service_marker() {
	local path="$1"
	local service="$2"
	local marker="$3"
	if ! compose_service_block "${path}" "${service}" | grep -Fq -- "${marker}"; then
		echo "[fail] Missing ${service} service marker in ${path}: ${marker}" >&2
		exit 1
	fi
}

reject_service_marker() {
	local path="$1"
	local service="$2"
	local marker="$3"
	if compose_service_block "${path}" "${service}" | grep -Fq -- "${marker}"; then
		echo "[fail] Forbidden ${service} service marker in ${path}: ${marker}" >&2
		exit 1
	fi
}

require_file "docs/cloud-production-release-policy-v1.md"
require_file "deploy/PRODUCTION_GITHUB_DEPLOY.md"
require_file "deploy/RELEASE_CHECKLIST.md"
require_file "deploy/OPS_PLAYBOOK.md"
require_file ".env.example"
require_file "docker-compose.dev.yml"
require_file "docker-compose.prod.yml"
require_file "docker-compose.runtime.yml"
require_file "scripts/cloud-deploy-bundle-smoke-flow.sh"
require_file "scripts/dev-compose.sh"
require_file "scripts/dev-frontend-recover.sh"
require_file "package.json"
require_file "Makefile"
require_file "AGENTS.md"
require_file ".github/pull_request_template.md"
require_file ".github/dependabot.yml"
require_file ".github/workflows/ci.yml"
require_file ".github/workflows/deploy-production.yml"
require_file "deploy/deploy-static-terms-to-ssh-host.sh"
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
require_marker "AGENTS.md" "Do not push or deploy to Gitee. Current project source control is GitHub-only."
require_marker "AGENTS.md" "pnpm run check:release-policy"

require_marker "docs/cloud-production-release-policy-v1.md" "master"
require_marker "docs/cloud-production-release-policy-v1.md" "production"
require_marker "docs/cloud-production-release-policy-v1.md" "Approved for production validation by operator."
require_marker "docs/cloud-production-release-policy-v1.md" "Do not directly edit production application code on the server."
require_marker "docs/cloud-production-release-policy-v1.md" "Cloud is not becoming a WordPress write owner"
require_marker "docs/cloud-production-release-policy-v1.md" "Branch divergence is expected"
require_marker "docs/cloud-production-release-policy-v1.md" "9aca0dc0"
require_marker "docs/cloud-production-release-policy-v1.md" "c9f3036b"
require_marker "docs/cloud-production-release-policy-v1.md" "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET"
require_marker "docs/cloud-production-release-policy-v1.md" "python -m app.dev.reencrypt_runtime_data"
require_marker "docs/cloud-production-release-policy-v1.md" "run --rm --no-deps --env-from-file"
require_marker "docs/cloud-production-release-policy-v1.md" 'future `rde.v1` rotations'
require_marker "docs/cloud-production-release-policy-v1.md" "host application source"
require_marker "docs/cloud-production-release-policy-v1.md" 'bundle excludes `.env.deploy`'
require_marker "docs/cloud-production-release-policy-v1.md" 'pass each old key ID to `inventory`'
require_marker "docs/cloud-production-release-policy-v1.md" "Normal runtime has no legacy or dual-read path"
require_marker "docs/cloud-production-release-policy-v1.md" "old database"
require_marker ".github/dependabot.yml" "open-pull-requests-limit: 0"

require_marker ".github/pull_request_template.md" "Focused module:"
require_marker ".github/pull_request_template.md" "Cloud boundary impact:"
require_marker ".github/pull_request_template.md" "Approved for production validation by operator."
require_marker ".github/pull_request_template.md" "does not commit production secrets"

require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "docs/cloud-production-release-policy-v1.md"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "pnpm run check:release-policy"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "/terms/en/terms.html"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "static terms fast path"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "python -m app.dev.reencrypt_runtime_data inventory"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "run --rm --no-deps --env-from-file"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "--old-key-id"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "staged release"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "ENV_SOURCE=/opt/npcink-ai-cloud/.env.deploy"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" 'install -m 600 "${ENV_SOURCE}" ./.env.deploy'
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" 'inventory --old-key-id "${OLD_RUNTIME_DATA_KEY_ID}"'
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "general deploy helper"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "Normal runtime has no legacy or dual-read path"
require_marker_before "deploy/PRODUCTION_GITHUB_DEPLOY.md" "install -m 600" "docker compose --env-file .env.deploy"
require_marker "deploy/OPS_PLAYBOOK.md" "stop and fence all four writers"
require_marker "deploy/OPS_PLAYBOOK.md" "python -m app.dev.reencrypt_runtime_data verify"
require_marker "deploy/OPS_PLAYBOOK.md" "run --rm --no-deps --env-from-file"
require_marker "deploy/OPS_PLAYBOOK.md" "--confirm-maintenance-window"
require_marker "deploy/OPS_PLAYBOOK.md" "--old-root-env NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET"
require_marker "deploy/OPS_PLAYBOOK.md" "--old-key-id"
require_marker "deploy/OPS_PLAYBOOK.md" 'Keep `postgres` and `redis`'
require_marker "deploy/OPS_PLAYBOOK.md" "ENV_SOURCE=/opt/npcink-ai-cloud/.env.deploy"
require_marker "deploy/OPS_PLAYBOOK.md" 'install -m 600 "${ENV_SOURCE}" ./.env.deploy'
require_marker "deploy/OPS_PLAYBOOK.md" 'inventory --old-key-id "${OLD_RUNTIME_DATA_KEY_ID}"'
require_marker "deploy/OPS_PLAYBOOK.md" "general deploy helper"
require_marker "deploy/OPS_PLAYBOOK.md" "Normal runtime has no legacy or dual-read path"
require_marker_before "deploy/OPS_PLAYBOOK.md" "install -m 600" "docker compose --env-file .env.deploy"
require_marker "deploy/OPS_PLAYBOOK.md" "old application revision"
require_marker "deploy/RELEASE_CHECKLIST.md" "new-key-only \`verify\`"
require_marker "deploy/RELEASE_CHECKLIST.md" "bundle-backed staged release API image"
require_marker "deploy/RELEASE_CHECKLIST.md" "--env-from-file"
require_marker "deploy/RELEASE_CHECKLIST.md" "first raw-ciphertext cutover omitted \`--old-key-id\`"
require_marker "deploy/RELEASE_CHECKLIST.md" "before the first staged Compose command"
require_marker "deploy/RELEASE_CHECKLIST.md" 'supplies old key IDs to `inventory`'
require_marker "deploy/RELEASE_CHECKLIST.md" "normal runtime has no legacy/dual-read path"
reject_marker "deploy/OPS_PLAYBOOK.md" "old-key compatibility path"
reject_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "old-key compatibility path"
reject_marker "docs/cloud-production-release-policy-v1.md" "compatibility reads"
reject_marker "deploy/OPS_PLAYBOOK.md" "--old-root-env NPCINK_CLOUD_ADMIN_SESSION_SECRET"
reject_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "--old-root-env NPCINK_CLOUD_ADMIN_SESSION_SECRET"
require_executable "scripts/dev-compose.sh"
require_marker "scripts/dev-compose.sh" 'for env_file in "${ROOT_DIR}/.env" "${ROOT_DIR}/.env.local"; do'
require_marker "scripts/dev-compose.sh" 'compose_args+=(--env-file "${env_file}")'
require_marker "package.json" '"dev": "bash scripts/dev-compose.sh up --build"'
require_marker "package.json" '"dev:runtime": "bash scripts/dev-compose.sh --profile runtime up --build"'
require_marker "package.json" '"dev:callback": "bash scripts/dev-compose.sh --profile runtime --profile callback up --build"'
require_marker "package.json" '"dev:ops": "bash scripts/dev-compose.sh --profile runtime --profile callback --profile ops up --build"'
require_marker "Makefile" "bash scripts/dev-compose.sh up --build"
require_marker "scripts/dev-frontend-recover.sh" "COMPOSE_CMD=(bash scripts/dev-compose.sh)"
reject_marker "scripts/dev-frontend-recover.sh" "docker compose"
require_marker ".env.example" "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET="
require_marker ".env.example" "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID="
require_marker "scripts/cloud-deploy-bundle-smoke-flow.sh" "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET"
require_marker "scripts/cloud-deploy-bundle-smoke-flow.sh" "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID"
require_marker "docker-compose.prod.yml" '127.0.0.1:${NPCINK_CLOUD_PORT:-8010}:8080'
for service in api worker callback-worker ops-worker; do
	require_service_marker "docker-compose.prod.yml" "${service}" "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET"
	require_service_marker "docker-compose.prod.yml" "${service}" "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID"
	require_service_marker "docker-compose.runtime.yml" "${service}" ".env.deploy"
done
for compose_file in docker-compose.dev.yml docker-compose.prod.yml docker-compose.runtime.yml; do
	reject_service_marker "${compose_file}" "frontend" "env_file:"
	reject_service_marker "${compose_file}" "frontend" "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET"
	reject_service_marker "${compose_file}" "frontend" "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID"
done
require_marker "deploy/bundle-images.sh" "-C \"\${CLOUD_DIR}\" site"
require_marker "deploy/deploy-static-terms-to-ssh-host.sh" "CURRENT_LINK=\"\${REMOTE_DIR}/current\""
require_marker "deploy/deploy-static-terms-to-ssh-host.sh" "assert_public_static_page \"/terms\""
require_marker "deploy/deploy-static-terms-to-ssh-host.sh" "Static terms deploy completed"
require_marker "deploy/remote-smoke.sh" "\${BASE_URL%/}/terms"
require_marker "deploy/remote-smoke.sh" "/terms/en/terms.html"
require_marker "deploy/remote-smoke.sh" "/terms/zh/terms.html"
require_marker "deploy/remote-smoke.sh" "/terms/styles.css"
require_marker "docker-compose.runtime.yml" "./site:/usr/share/nginx/html/npcink-site:ro"
require_marker "deploy/nginx.prod.conf" "location /terms/"
require_marker "deploy/nginx.prod.conf" "try_files /terms/index.html =404;"
require_marker ".github/workflows/ci.yml" "github.ref == 'refs/heads/production'"
require_marker ".github/workflows/ci.yml" "environment: production"
require_marker ".github/workflows/ci.yml" "static_terms_only"
require_marker ".github/workflows/ci.yml" "site/terms/*"
require_marker ".github/workflows/ci.yml" "deploy-static-terms-to-ssh-host.sh"
require_marker ".github/workflows/deploy-production.yml" "github.ref == 'refs/heads/production'"

echo "[ok] Lightweight release policy gate passed"
