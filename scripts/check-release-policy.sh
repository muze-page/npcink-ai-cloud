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

reject_file() {
	local path="$1"
	if [ -e "${ROOT_DIR}/${path}" ] || [ -L "${ROOT_DIR}/${path}" ]; then
		echo "[fail] Retired release policy file still exists: ${path}" >&2
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
	local service_block
	service_block="$(compose_service_block "${path}" "${service}")"
	if ! grep -Fq -- "${marker}" <<<"${service_block}"; then
		echo "[fail] Missing ${service} service marker in ${path}: ${marker}" >&2
		exit 1
	fi
}

reject_service_marker() {
	local path="$1"
	local service="$2"
	local marker="$3"
	local service_block
	service_block="$(compose_service_block "${path}" "${service}")"
	if grep -Fq -- "${marker}" <<<"${service_block}"; then
		echo "[fail] Forbidden ${service} service marker in ${path}: ${marker}" >&2
		exit 1
	fi
}

require_service_image_seam() {
	local path="$1"
	local service="$2"
	local expected_image="$3"
	local actual_lines
	local expected_line

	expected_line="    image: ${expected_image}"
	actual_lines="$(compose_service_block "${path}" "${service}" | awk '/^    image:/ { print }')"
	if [ "${actual_lines}" != "${expected_line}" ]; then
		echo "[fail] ${path}:${service} must use the exact governed release image seam: ${expected_image}" >&2
		exit 1
	fi
}

require_canonical_dependabot_config() {
	local expected

	IFS= read -r -d '' expected <<'YAML' || true
version: 2
# Pre-GA maintenance: keep each weekly ecosystem queue small and reviewable.
# Docker and digest-lock updates stay in the independent image-lock scan lane.
updates:
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
      day: monday
      time: "09:00"
      timezone: Asia/Shanghai
    open-pull-requests-limit: 2
    labels:
      - dependencies

  - package-ecosystem: npm
    directory: /
    schedule:
      interval: weekly
      day: monday
      time: "09:30"
      timezone: Asia/Shanghai
    open-pull-requests-limit: 2
    labels:
      - dependencies

  - package-ecosystem: uv
    directory: /
    schedule:
      interval: weekly
      day: monday
      time: "10:00"
      timezone: Asia/Shanghai
    open-pull-requests-limit: 2
    labels:
      - dependencies
YAML
	if ! cmp -s "${ROOT_DIR}/.github/dependabot.yml" <(printf '%s' "${expected}"); then
		echo "[fail] .github/dependabot.yml does not match the canonical pre-GA policy" >&2
		exit 1
	fi
}

require_file "docs/cloud-production-release-policy-v1.md"
require_file "deploy/PRODUCTION_GITHUB_DEPLOY.md"
require_file "deploy/RELEASE_CHECKLIST.md"
require_file "deploy/OPS_PLAYBOOK.md"
require_file "docs/refactor-master-plan-v1.md"
require_file "docs/p5-b8-final-engineering-closeout-2026-07-19.md"
require_file "docs/python-3-14-6-controlled-production-validation-risk-decision-2026-07-21.md"
require_file "deploy/deploy-to-ssh-host.sh"
require_file "deploy/runtime-data-encryption-cutover.sh"
require_file "deploy/certificate-renewal-readiness.sh"
require_file "deploy/common.sh"
require_file "deploy/remote-load-and-up.sh"
require_file "deploy/remote-migrate.sh"
require_file "deploy/remote-refresh-providers.sh"
require_file "deploy/remote-operational-ready.sh"
require_file ".env.example"
require_file "docker-compose.dev.yml"
require_file "docker-compose.prod.yml"
require_file "docker-compose.p5-b4-runtime-proof.yml"
require_file "docker-compose.runtime.yml"
require_file "scripts/cloud-deploy-bundle-smoke-flow.sh"
require_file "scripts/production-image-supply.py"
require_file "scripts/dev-compose.sh"
require_file "scripts/dev-frontend-recover.sh"
require_file "package.json"
require_file "Makefile"
require_file "README.md"
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

require_canonical_dependabot_config
require_executable "deploy/runtime-data-encryption-cutover.sh"
require_executable "deploy/certificate-renewal-readiness.sh"

require_marker "docs/python-3-14-6-controlled-production-validation-risk-decision-2026-07-21.md" \
	'npcink.controlled_production_cve_risk_acceptance.v1'
require_marker "docs/python-3-14-6-controlled-production-validation-risk-decision-2026-07-21.md" \
	'accepted_by_operator'
require_marker "docs/python-3-14-6-controlled-production-validation-risk-decision-2026-07-21.md" \
	'controlled_production_validation_only'
require_marker "docs/python-3-14-6-controlled-production-validation-risk-decision-2026-07-21.md" \
	'GA is not authorized'
require_marker "docs/python-3-14-6-controlled-production-validation-risk-decision-2026-07-21.md" \
	'deployment, image-scan, and P1-E06 tooling do not consume this acceptance'
for marker in \
	'"decision_document": "docs/python-3-14-6-controlled-production-validation-risk-decision-2026-07-21.md"' \
	'"source_revision": "<40-lowercase-hex>"' \
	'"source_tree": "<40-lowercase-hex>"' \
	'"bundle_sha256": "<64-lowercase-hex>"' \
	'"scan_index_sha256": "<64-lowercase-hex>"' \
	'"api_scan_receipt_sha256": "<64-lowercase-hex>"' \
	'"allowlist_sha256": "<64-lowercase-hex>"' \
	'"scan_index_status": "passed"' \
	'"api_scan_status": "passed"' \
	'"image_platform": "linux/amd64"' \
	'"api_image_reference": "npcink-ai-cloud-api:prod"' \
	'"blocking_finding_count": 3' \
	'"allowlisted_blocking_finding_count": 3' \
	'"unallowlisted_blocking_finding_count": 0' \
	'"allowlisted_findings"' \
	'"vulnerability_id": "CVE-2026-11940"' \
	'"vulnerability_id": "CVE-2026-11972"' \
	'"vulnerability_id": "CVE-2026-15308"' \
	'"package_version": "3.14.6"' \
	'"severity": "high"' \
	'"fix_state": "unknown"' \
	'"fix_state": "fixed"' \
	'"cisa_ssvc_exploitation"' \
	'"cisa_ssvc_checked_at_utc": "<RFC3339-UTC>"' \
	'"exception_expires_on": "2026-08-05"' \
	'"ga_authorized": false' \
	'"authorized_by": "Muze"' \
	'"authorized_at_utc": "<RFC3339-UTC>"' \
	'outside Git, the deploy bundle, and every release tree' \
	'owner-only mode-`0600` file' \
	'record its SHA-256 separately' \
	'cannot contain a self-digest'; do
	require_marker \
		"docs/python-3-14-6-controlled-production-validation-risk-decision-2026-07-21.md" \
		"${marker}"
done
reject_marker "docs/python-3-14-6-controlled-production-validation-risk-decision-2026-07-21.md" \
	'"receipt_sha256"'
reject_marker "docs/python-3-14-6-controlled-production-validation-risk-decision-2026-07-21.md" \
	'"acceptance_sha256"'
require_marker "deploy/image-lock/cve-allowlist.json" \
	'operator-authorized controlled production validation only'
require_marker "deploy/image-lock/cve-allowlist.json" \
	'no GA, customer rollout, or general production authorization'
require_marker "deploy/image-lock/cve-allowlist.json" \
	'npcink.controlled_production_cve_risk_acceptance.v1'
require_marker "deploy/OPS_PLAYBOOK.md" \
	'npcink.controlled_production_cve_risk_acceptance.v1'
require_marker "deploy/OPS_PLAYBOOK.md" \
	'root-owned mode-`0400` custom-format backup and checksum'
require_marker "deploy/RELEASE_CHECKLIST.md" \
	'npcink.controlled_production_cve_risk_acceptance.v1'
require_marker "deploy/RELEASE_CHECKLIST.md" \
	'root-owned non-symlink mode-`0400` backup and checksum'

if git -C "${ROOT_DIR}" ls-files | grep -Eq '(^|/)\.env\.deploy$'; then
	echo "[fail] Release payload source must not track .env.deploy" >&2
	exit 1
fi

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
require_marker "docs/cloud-production-release-policy-v1.md" "configuration and secret changes are releases"
require_marker "docs/cloud-production-release-policy-v1.md" "edit the active release env or restart Compose services in place."
require_marker "docs/cloud-production-release-policy-v1.md" "hosted provider connections, credentials, routing, and execution"
require_marker "docs/cloud-production-release-policy-v1.md" "Approved for production validation by operator."
require_marker "docs/cloud-production-release-policy-v1.md" "Do not directly edit production application code on the server."
require_marker "docs/cloud-production-release-policy-v1.md" "Cloud is not becoming a WordPress write owner"
require_marker "docs/cloud-production-release-policy-v1.md" "Branch divergence is expected"
require_marker "docs/cloud-production-release-policy-v1.md" "9aca0dc0"
require_marker "docs/cloud-production-release-policy-v1.md" "c9f3036b"
require_marker "docs/cloud-production-release-policy-v1.md" "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET"
require_marker "docs/cloud-production-release-policy-v1.md" "python -m app.dev.reencrypt_runtime_data"
require_marker "docs/cloud-production-release-policy-v1.md" "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID"
require_marker "docs/cloud-production-release-policy-v1.md" "python -m app.dev.reencrypt_service_secrets"
require_marker "docs/cloud-production-release-policy-v1.md" "deploy/runtime-data-encryption-cutover.sh"
require_marker "docs/cloud-production-release-policy-v1.md" "deploy/deploy-to-ssh-host.sh --stage-only"
require_marker "docs/cloud-production-release-policy-v1.md" "p1_e06_off_host_backup_receipt.v1"
require_marker "docs/cloud-production-release-policy-v1.md" 'release-one-off` stopped candidate'
require_marker "docs/cloud-production-release-policy-v1.md" 'docker exec -i --env VARIABLE_NAME'
reject_marker "docs/cloud-production-release-policy-v1.md" "run --rm --no-deps -e VARIABLE_NAME"
require_marker "docs/cloud-production-release-policy-v1.md" "pull_policy: never"
require_marker "docs/cloud-production-release-policy-v1.md" 'Future `rde.v1`'
require_marker "docs/cloud-production-release-policy-v1.md" "independent PostgreSQL 16"
require_marker "docs/cloud-production-release-policy-v1.md" "off-host"
require_marker "docs/cloud-production-release-policy-v1.md" 'release payload must never contain `.env.deploy`'
require_marker "docs/cloud-production-release-policy-v1.md" '.release-state/<release-name>/env.deploy'
require_marker "docs/cloud-production-release-policy-v1.md" 'old and new Compose project names must match'
require_marker "docs/cloud-production-release-policy-v1.md" 'actual old writer container'
require_marker "docs/cloud-production-release-policy-v1.md" '`--skip-frontend-image` additionally requires'
require_marker "docs/cloud-production-release-policy-v1.md" 'isolate the new release environment'
require_marker "docs/cloud-production-release-policy-v1.md" 'Once migration starts'
require_marker "docs/cloud-production-release-policy-v1.md" 'deployment lock remains'
require_marker "docs/cloud-production-release-policy-v1.md" 'remove the temporary rollback-image map'
require_marker "docs/cloud-production-release-policy-v1.md" 'pass each old key ID'
require_marker "docs/cloud-production-release-policy-v1.md" "Normal runtime has no legacy or dual-read path"
require_marker "docs/cloud-production-release-policy-v1.md" 'whole `0058` database'
require_marker "docs/cloud-production-release-policy-v1.md" "certificate-renewal owner"
require_marker "docs/cloud-production-release-policy-v1.md" "npcink_cloud_certificate_renewal_readiness.v1"
require_marker "docs/cloud-production-release-policy-v1.md" "NPCINK_CLOUD_CERTIFICATE_RENEWAL_EVIDENCE_PATH"
require_marker "docs/cloud-production-release-policy-v1.md" "NPCINK_CLOUD_CERTIFICATE_RENEWAL_TIMER"
require_marker "docs/cloud-production-release-policy-v1.md" "NPCINK_CLOUD_CERTIFICATE_RENEWAL_HOOK_PATH"
require_marker "docs/cloud-production-release-policy-v1.md" 'certbot-renew.timer'
require_marker "docs/cloud-production-release-policy-v1.md" "/usr/bin/python3.11"
require_marker "docs/cloud-production-release-policy-v1.md" 'root-managed `root:root` tree'
require_marker "docs/cloud-production-release-policy-v1.md" "Pure stage-only archive upload/verification"
require_marker "docs/cloud-production-release-policy-v1.md" "off-host-receipt-verified.json"
require_marker "docs/cloud-production-release-policy-v1.md" "activation-commit.json"
require_marker "docs/cloud-production-release-policy-v1.md" "activation_committed_terminalization_incomplete"
require_marker ".github/workflows/ci.yml" "production-python-image-smoke:"
require_marker ".github/workflows/ci.yml" "bash scripts/production-python-extras-smoke.sh"
require_marker ".github/workflows/ci.yml" "PRODUCTION_PYTHON_IMAGE_SMOKE_RESULT"
require_marker ".github/workflows/ci.yml" "Python 3.14 Alpine production image smoke did not pass"
require_marker ".github/workflows/ci.yml" "Dockerfile*|*/Dockerfile*"
require_marker ".github/workflows/deploy-production.yml" 'NPCINK_CLOUD_INCLUDE_EXTERNAL_IMAGES: "1"'
reject_marker ".github/workflows/ci.yml" "PROD_INCLUDE_EXTERNAL_IMAGES"
reject_marker ".github/workflows/deploy-production.yml" "PROD_INCLUDE_EXTERNAL_IMAGES"
require_marker "scripts/production-python-extras-smoke.sh" 'PYTHON_VERSION="3.14"'
require_marker "scripts/production-python-extras-smoke.sh" "--import-app"
require_marker "scripts/production-python-extras-smoke.sh" "--check-manifest"
require_marker "scripts/check-pr-backend-gate.sh" "Dockerfile*|*/Dockerfile*"

require_marker ".github/pull_request_template.md" "Focused module:"
require_marker ".github/pull_request_template.md" "Cloud boundary impact:"
require_marker ".github/pull_request_template.md" "Approved for production validation by operator."
require_marker ".github/pull_request_template.md" "does not commit production secrets"

require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "docs/cloud-production-release-policy-v1.md"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "pnpm run check:release-policy"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "/terms/en/terms.html"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "static terms fast path"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "deploy/runtime-data-encryption-cutover.sh"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "deploy/deploy-to-ssh-host.sh --stage-only --skip-bundle-build"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "staged_release=/absolute/release-path"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "p1_e06_off_host_backup_receipt.v1"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" 'release-one-off` stopped candidate'
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" 'docker exec -i --env VARIABLE_NAME'
reject_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "run --rm --no-deps -e VARIABLE_NAME"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "python -m app.dev.reencrypt_service_secrets"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "--old-key-id"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" '/opt/npcink-ai-cloud/.release-state/<release-name>/env.deploy'
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" '`--skip-frontend-image` preserves an existing frontend only'
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "Normal runtime has no legacy or dual-read path"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "migration begins, a"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" '`.deploy-lock` is'
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" 'temporary rollback-image map'
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "independent hard gate"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" 'Pure `--stage-only` archive'
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "/usr/bin/python3.11"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "certificate-renewal owner"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "production-host-mutation"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "Prune production images and old releases."
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "deploy/certificate-renewal-readiness.sh"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "NPCINK_CLOUD_CERTIFICATE_RENEWAL_EVIDENCE_PATH"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "NPCINK_CLOUD_CERTIFICATE_RENEWAL_TIMER"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "NPCINK_CLOUD_CERTIFICATE_RENEWAL_HOOK_PATH"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "off-host-receipt-verified.json"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "activation-commit.json"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "activation_committed_terminalization_incomplete"
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "Runtime configuration changes are releases."
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "Never remove the lock first."
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "com.docker.compose.service=release-one-off"
reject_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "Runtime configuration-only changes can normally be applied"
require_marker "deploy/OPS_PLAYBOOK.md" "deploy/runtime-data-encryption-cutover.sh"
require_marker "deploy/OPS_PLAYBOOK.md" "deploy/deploy-to-ssh-host.sh --stage-only"
require_marker "deploy/OPS_PLAYBOOK.md" "staged_release=/absolute/release-path"
require_marker "deploy/OPS_PLAYBOOK.md" "p1_e06_off_host_backup_receipt.v1"
require_marker "deploy/OPS_PLAYBOOK.md" "python -m app.dev.reencrypt_runtime_data verify"
require_marker "deploy/OPS_PLAYBOOK.md" "python -m app.dev.reencrypt_service_secrets verify"
require_marker "deploy/OPS_PLAYBOOK.md" "There is intentionally no copy/paste Compose command"
reject_marker "deploy/OPS_PLAYBOOK.md" "run --rm --no-deps"
require_marker "deploy/OPS_PLAYBOOK.md" "protected names-only environment handoff"
require_marker "deploy/OPS_PLAYBOOK.md" 'Retained `release-one-off` lock recovery'
require_marker "deploy/OPS_PLAYBOOK.md" "Never remove the lock first."
require_marker "deploy/OPS_PLAYBOOK.md" "npcink-release-proof-stdin.*"
require_marker "deploy/OPS_PLAYBOOK.md" "There is no standalone production worker-restart entry point."
reject_marker "deploy/OPS_PLAYBOOK.md" 'npcink_ai_cloud_compose "${RELEASE_DIR}" restart worker callback-worker ops-worker'
require_marker "deploy/OPS_PLAYBOOK.md" "Database rollback is a matched release-recovery operation"
require_marker "deploy/OPS_PLAYBOOK.md" "Do not use bare Compose restarts."
require_marker "deploy/OPS_PLAYBOOK.md" "Cloud admin surface"
reject_marker "deploy/OPS_PLAYBOOK.md" "Update provider routing/connection state from the local plugin control plane"
reject_marker "deploy/OPS_PLAYBOOK.md" 'restart `callback-worker`.'
reject_marker "deploy/OPS_PLAYBOOK.md" 'Restart `api`, `worker`, `callback-worker`, and `ops-worker`.'
reject_marker "deploy/OPS_PLAYBOOK.md" 'restart `ops-worker`.'
reject_marker "deploy/OPS_PLAYBOOK.md" "Tune resources through environment variables and service restarts"
require_marker "deploy/OPS_PLAYBOOK.md" "--confirm-maintenance-window"
require_marker "deploy/OPS_PLAYBOOK.md" "--old-root-env NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET"
require_marker "deploy/OPS_PLAYBOOK.md" "--old-root-env NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET"
require_marker "deploy/OPS_PLAYBOOK.md" "--old-key-id"
require_marker "deploy/OPS_PLAYBOOK.md" '.release-state/<release-name>/env.deploy'
require_marker "deploy/OPS_PLAYBOOK.md" 'isolated process'
require_marker "deploy/OPS_PLAYBOOK.md" '--old-key-id "${OLD_RUNTIME_DATA_KEY_ID}"'
require_marker "deploy/OPS_PLAYBOOK.md" "Normal runtime has no legacy or dual-read path"
require_marker "deploy/OPS_PLAYBOOK.md" 'Once migration begins'
require_marker "deploy/OPS_PLAYBOOK.md" 'keep `.deploy-lock`'
require_marker "deploy/OPS_PLAYBOOK.md" 'Remove the temporary rollback-image map'
require_marker "deploy/OPS_PLAYBOOK.md" "old application revision"
require_marker "deploy/OPS_PLAYBOOK.md" "certificate-renewal owner"
require_marker "deploy/OPS_PLAYBOOK.md" "deploy/certificate-renewal-readiness.sh"
require_marker "deploy/OPS_PLAYBOOK.md" "NPCINK_CLOUD_CERTIFICATE_RENEWAL_EVIDENCE_PATH"
require_marker "deploy/OPS_PLAYBOOK.md" "NPCINK_CLOUD_CERTIFICATE_RENEWAL_TIMER"
require_marker "deploy/OPS_PLAYBOOK.md" "NPCINK_CLOUD_CERTIFICATE_RENEWAL_HOOK_PATH"
require_marker "deploy/OPS_PLAYBOOK.md" "/usr/bin/python3.11"
require_marker "deploy/OPS_PLAYBOOK.md" "off-host-receipt-verified.json"
require_marker "deploy/OPS_PLAYBOOK.md" "activation-commit.json"
require_marker "deploy/OPS_PLAYBOOK.md" "activation_committed_terminalization_incomplete"
require_marker "deploy/OPS_PLAYBOOK.md" 'Pure `--stage-only` upload'
require_marker "deploy/RELEASE_CHECKLIST.md" "new-key-only \`verify\`"
require_marker "deploy/RELEASE_CHECKLIST.md" "python -m app.dev.reencrypt_service_secrets"
require_marker "deploy/RELEASE_CHECKLIST.md" "NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET"
require_marker "deploy/RELEASE_CHECKLIST.md" "deploy/runtime-data-encryption-cutover.sh"
require_marker "deploy/RELEASE_CHECKLIST.md" "deploy/deploy-to-ssh-host.sh --stage-only --skip-bundle-build"
require_marker "deploy/RELEASE_CHECKLIST.md" "staged_release=/absolute/release-path"
require_marker "deploy/RELEASE_CHECKLIST.md" "p1_e06_off_host_backup_receipt.v1"
require_marker "deploy/RELEASE_CHECKLIST.md" 'release-one-off` stopped candidate'
require_marker "deploy/RELEASE_CHECKLIST.md" 'docker exec -i --env VARIABLE_NAME'
reject_marker "deploy/RELEASE_CHECKLIST.md" "run --rm --no-deps -e VARIABLE_NAME"
require_marker "deploy/RELEASE_CHECKLIST.md" "pull_policy: never"
require_marker "deploy/RELEASE_CHECKLIST.md" "first raw-ciphertext cutover omitted \`--old-key-id\`"
require_marker "deploy/RELEASE_CHECKLIST.md" 'supplies old key IDs'
require_marker "deploy/RELEASE_CHECKLIST.md" "normal runtime has no legacy/dual-read path"
require_marker "deploy/RELEASE_CHECKLIST.md" '.release-state/<release-name>/env.deploy'
require_marker "deploy/RELEASE_CHECKLIST.md" 'same Compose project name'
require_marker "deploy/RELEASE_CHECKLIST.md" 'actual old-writer container-label check'
require_marker "deploy/RELEASE_CHECKLIST.md" '`--skip-frontend-image` was selected'
require_marker "deploy/RELEASE_CHECKLIST.md" 'isolated process environment'
require_marker "deploy/RELEASE_CHECKLIST.md" 'heartbeats were newer than the recorded cutoff'
require_marker "deploy/RELEASE_CHECKLIST.md" 'retains `.deploy-lock`'
require_marker "deploy/RELEASE_CHECKLIST.md" 'removed the temporary rollback-image map'
require_marker "deploy/RELEASE_CHECKLIST.md" "stage-only upload/verification was allowed to precede this gate"
require_marker "deploy/RELEASE_CHECKLIST.md" "operator-owned external Edge and TLS are valid for the release host"
require_marker "deploy/RELEASE_CHECKLIST.md" 'Runtime Compose sets `NPCINK_CLOUD_EXTERNAL_EDGE_READY=true`'
require_marker "deploy/RELEASE_CHECKLIST.md" "certificate-renewal owner"
require_marker "deploy/RELEASE_CHECKLIST.md" "production-host-mutation"
require_marker "deploy/RELEASE_CHECKLIST.md" "deploy/certificate-renewal-readiness.sh generate"
require_marker "deploy/RELEASE_CHECKLIST.md" "npcink_cloud_certificate_renewal_readiness.v1"
require_marker "deploy/RELEASE_CHECKLIST.md" "NPCINK_CLOUD_CERTIFICATE_RENEWAL_TIMER"
require_marker "deploy/RELEASE_CHECKLIST.md" "NPCINK_CLOUD_CERTIFICATE_RENEWAL_HOOK_PATH"
require_marker "deploy/RELEASE_CHECKLIST.md" "/usr/bin/python3.11"
require_marker "deploy/RELEASE_CHECKLIST.md" "off-host-receipt-verified.json"
require_marker "deploy/RELEASE_CHECKLIST.md" "activation-commit.json"
require_marker "deploy/RELEASE_CHECKLIST.md" "activation_committed_terminalization_incomplete"
for certificate_readiness_doc in \
	deploy/OPS_PLAYBOOK.md \
	deploy/PRODUCTION_GITHUB_DEPLOY.md \
	deploy/RELEASE_CHECKLIST.md; do
	require_marker "${certificate_readiness_doc}" "renewal_service"
	require_marker "${certificate_readiness_doc}" "certbot_real_path"
	require_marker "${certificate_readiness_doc}" "renewal_exec_start_sha256"
done
reject_marker "deploy/OPS_PLAYBOOK.md" "old-key compatibility path"
reject_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "old-key compatibility path"
reject_marker "docs/cloud-production-release-policy-v1.md" "compatibility reads"
reject_marker "deploy/OPS_PLAYBOOK.md" "--old-root-env NPCINK_CLOUD_ADMIN_SESSION_SECRET"
reject_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" "--old-root-env NPCINK_CLOUD_ADMIN_SESSION_SECRET"
for cutover_surface in \
	deploy/runtime-data-encryption-cutover.sh \
	deploy/OPS_PLAYBOOK.md \
	deploy/PRODUCTION_GITHUB_DEPLOY.md \
	deploy/RELEASE_CHECKLIST.md \
	docs/cloud-production-release-policy-v1.md; do
	reject_marker "${cutover_surface}" "--env-from-file"
done
for historical_doc in \
	docs/refactor-master-plan-v1.md \
	docs/p5-b8-final-engineering-closeout-2026-07-19.md; do
	require_marker "${historical_doc}" "Integration Correction — 2026-07-20"
	require_marker "${historical_doc}" '`0663d95f`'
	require_marker "${historical_doc}" '`linux/arm64`'
	require_marker "${historical_doc}" '`linux/amd64`'
	require_marker "${historical_doc}" 'merged `master`'
done
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
require_marker ".env.example" "NPCINK_CLOUD_SERVICE_SETTINGS_SECRET="
require_marker ".env.example" "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID="
require_marker "scripts/cloud-deploy-bundle-smoke-flow.sh" "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET"
require_marker "scripts/cloud-deploy-bundle-smoke-flow.sh" "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID"
require_marker "scripts/cloud-deploy-bundle-smoke-flow.sh" "NPCINK_CLOUD_SERVICE_SETTINGS_SECRET"
require_marker "scripts/cloud-deploy-bundle-smoke-flow.sh" "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID"
for ordinary_runtime_surface in \
	docker-compose.prod.yml \
	docker-compose.p5-b4-runtime-proof.yml \
	.env.example \
	scripts/cloud-deploy-bundle-smoke-flow.sh; do
	reject_marker "${ordinary_runtime_surface}" "NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET"
	reject_marker "${ordinary_runtime_surface}" "NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET"
done
require_marker "docker-compose.prod.yml" '127.0.0.1:${NPCINK_CLOUD_PORT:-8010}:8080'
for service in api worker callback-worker ops-worker; do
	require_service_marker "docker-compose.prod.yml" "${service}" "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET"
	require_service_marker "docker-compose.prod.yml" "${service}" "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID"
	require_service_marker "docker-compose.prod.yml" "${service}" "NPCINK_CLOUD_SERVICE_SETTINGS_SECRET"
	require_service_marker "docker-compose.prod.yml" "${service}" "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID"
	require_service_marker "docker-compose.runtime.yml" "${service}" '${NPCINK_CLOUD_BACKEND_ENV_FILE:-.env.deploy}'
done
for service in postgres redis api frontend worker callback-worker ops-worker proxy release-one-off; do
	require_service_marker "docker-compose.runtime.yml" "${service}" "pull_policy: never"
done
for compose_file in docker-compose.prod.yml docker-compose.runtime.yml; do
	require_service_image_seam "${compose_file}" "postgres" '${NPCINK_CLOUD_POSTGRES_RELEASE_IMAGE:-npcink-ai-cloud-postgres:prod}'
	require_service_image_seam "${compose_file}" "redis" '${NPCINK_CLOUD_REDIS_RELEASE_IMAGE:-npcink-ai-cloud-external-redis:prod}'
	require_service_image_seam "${compose_file}" "api" '${NPCINK_CLOUD_API_RELEASE_IMAGE:-npcink-ai-cloud-api:prod}'
	require_service_image_seam "${compose_file}" "frontend" '${NPCINK_CLOUD_FRONTEND_RELEASE_IMAGE:-npcink-ai-cloud-frontend:prod}'
	require_service_image_seam "${compose_file}" "proxy" '${NPCINK_CLOUD_PROXY_RELEASE_IMAGE:-npcink-ai-cloud-external-nginx:prod}'
	require_service_image_seam "${compose_file}" "release-one-off" '${NPCINK_CLOUD_API_RELEASE_IMAGE:-npcink-ai-cloud-api:prod}'
	require_service_marker "${compose_file}" "release-one-off" 'pull_policy: never'
	require_service_marker "${compose_file}" "release-one-off" 'profiles: ["release-one-off"]'
	require_service_marker "${compose_file}" "release-one-off" 'restart: "no"'
	require_service_marker "${compose_file}" "release-one-off" 'import signal; signal.pause()'
done
require_service_image_seam "docker-compose.prod.yml" "worker" '${NPCINK_CLOUD_WORKER_RELEASE_IMAGE:-npcink-ai-cloud-worker:prod}'
require_service_image_seam "docker-compose.prod.yml" "callback-worker" '${NPCINK_CLOUD_CALLBACK_WORKER_RELEASE_IMAGE:-npcink-ai-cloud-callback-worker:prod}'
require_service_image_seam "docker-compose.prod.yml" "ops-worker" '${NPCINK_CLOUD_OPS_WORKER_RELEASE_IMAGE:-npcink-ai-cloud-ops-worker:prod}'
require_service_image_seam "docker-compose.runtime.yml" "worker" '${NPCINK_CLOUD_WORKER_RELEASE_IMAGE:-npcink-ai-cloud-worker:prod}'
require_service_image_seam "docker-compose.runtime.yml" "callback-worker" '${NPCINK_CLOUD_CALLBACK_WORKER_RELEASE_IMAGE:-npcink-ai-cloud-worker:prod}'
require_service_image_seam "docker-compose.runtime.yml" "ops-worker" '${NPCINK_CLOUD_OPS_WORKER_RELEASE_IMAGE:-npcink-ai-cloud-worker:prod}'
for compose_file in docker-compose.dev.yml docker-compose.prod.yml docker-compose.runtime.yml; do
	reject_service_marker "${compose_file}" "frontend" "env_file:"
	reject_service_marker "${compose_file}" "frontend" "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET"
	reject_service_marker "${compose_file}" "frontend" "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID"
	reject_service_marker "${compose_file}" "frontend" "NPCINK_CLOUD_SERVICE_SETTINGS_SECRET"
	reject_service_marker "${compose_file}" "frontend" "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID"
done

require_marker "deploy/deploy-to-ssh-host.sh" '--stage-only'
require_marker "deploy/deploy-to-ssh-host.sh" '--host-python'
require_marker "deploy/deploy-to-ssh-host.sh" 'DEPLOY_HOST_PYTHON="${NPCINK_CLOUD_DEPLOY_HOST_PYTHON:-/usr/bin/python3.11}"'
require_marker "deploy/deploy-to-ssh-host.sh" 'Remote host release-tool Python must be executable and version 3.11 or newer'
require_marker "deploy/deploy-to-ssh-host.sh" 'REMOTE_SEQUENCE_VALUES=('
require_marker "deploy/deploy-to-ssh-host.sh" 'Stage-only remote entry requires exactly five arguments.'
require_marker "deploy/deploy-to-ssh-host.sh" 'cleanup_remote_incoming_on_exit'
require_marker_before "deploy/deploy-to-ssh-host.sh" \
	'REMOTE_PYTHON_PROBE=' \
	'echo "[info] Preparing remote directory'
require_marker "deploy/common.sh" 'NPCINK_CLOUD_RELEASE_TOOL_PYTHON'
require_marker "deploy/common.sh" 'sys.version_info >= (3, 11)'
require_marker "deploy/deploy-to-ssh-host.sh" '[fail] --stage-only does not accept an env file.'
require_marker "deploy/deploy-to-ssh-host.sh" 'verify-release-bundle.sh'
require_marker "deploy/deploy-to-ssh-host.sh" '--pre-load "${RELEASE_DIR}"'
require_marker "deploy/deploy-to-ssh-host.sh" 'printf '\''staged_release=%s\n'\'' "${STAGED_RELEASE}"'
require_marker "deploy/deploy-to-ssh-host.sh" 'Stage-only deliberately exits before resolving current'
require_marker_before "deploy/deploy-to-ssh-host.sh" \
	'if [ "${STAGE_ONLY}" = "1" ]; then' \
	'atomic_set_current() {'

require_marker "deploy/runtime-data-encryption-cutover.sh" 'CONTRACT="p1_e06_runtime_data_encryption_cutover.v1"'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'EXPECTED_SOURCE_REVISION="20260710_0058"'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'EXPECTED_TARGET_REVISION="20260717_0068"'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'EXPECTED_RUNTIME_LEGACY_TOTAL=18'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'EXPECTED_SERVICE_LEGACY_TOTAL=12'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'EXPECTED_LEGACY_TOTAL=$((EXPECTED_RUNTIME_LEGACY_TOTAL + EXPECTED_SERVICE_LEGACY_TOTAL))'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'EXPECTED_RUNTIME_ROW_IDENTIFIERS_SHA256="675cce444dbbf801bc8ab7fb35b717888c878e062097e5fb7f2f5f110e5a764c"'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'EXPECTED_SERVICE_ROW_IDENTIFIERS_SHA256="e5010d2b0a2afe22b7729c4c2395c91001a078e282abee87f03a5f0289aa0bf6"'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'OFF_HOST_RECEIPT_CONTRACT="p1_e06_off_host_backup_receipt.v1"'
require_marker "deploy/runtime-data-encryption-cutover.sh" '--off-host-receipt-timeout-seconds'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'I_ACKNOWLEDGE_THE_BACKUP_COPY_IS_OFF_HOST_AND_INDEPENDENT'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'I_ACKNOWLEDGE_ROLLBACK_RESTORES_DATABASE_RELEASE_ENV_AND_BOTH_OLD_ROOTS_TOGETHER'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'I_AUTHORIZE_THE_P1_E06_PRODUCTION_CUTOVER'
require_marker "deploy/runtime-data-encryption-cutover.sh" '--edge-readiness-env'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'p1_e06_edge_readiness_env_handoff.v1'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'CURRENT_ENV_SNAPSHOT="${EVIDENCE_DIR}/.current-env.snapshot"'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'restore_original_edge_env()'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'fsync_p1_e06_recovery_anchors()'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'previous_external_env_snapshot_sha256='
require_marker "deploy/runtime-data-encryption-cutover.sh" 'maintenance_env_snapshot_sha256='
require_marker "deploy/runtime-data-encryption-cutover.sh" 'CURRENT_EXTERNAL_EDGE_READY'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'CURRENT_STAGE="verify-certificate-renewal-readiness"'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'deploy/certificate-renewal-readiness.sh'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'systemctl is-active --quiet nginx'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'nginx -t'
require_marker "deploy/runtime-data-encryption-cutover.sh" '--resolve "${domain_name}:443:127.0.0.1"'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'NPCINK_CLOUD_LOAD_MODE=prepare-only'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'p1_e06_off_host_backup_handoff.v1'
require_marker "deploy/runtime-data-encryption-cutover.sh" '[p1-e06:handoff] marker=%s receipt=%s'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'p1_e06_independent_pg16_restore.v1'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'chmod 0400 "${BACKUP_PATH}"'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'chmod 0400 "${BACKUP_PATH}.sha256"'
reject_marker "deploy/runtime-data-encryption-cutover.sh" 'chmod 0600 "${BACKUP_PATH}"'
reject_marker "deploy/runtime-data-encryption-cutover.sh" 'chmod 0600 "${BACKUP_PATH}.sha256"'
require_marker "deploy/runtime-data-encryption-cutover.sh" '-e NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET'
require_marker "deploy/runtime-data-encryption-cutover.sh" '-e NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID'
require_marker "deploy/runtime-data-encryption-cutover.sh" '-e NPCINK_CLOUD_RUNTIME_DATA_OLD_ROOT_SECRET'
require_marker "deploy/runtime-data-encryption-cutover.sh" '-e NPCINK_CLOUD_SERVICE_SETTINGS_SECRET'
require_marker "deploy/runtime-data-encryption-cutover.sh" '-e NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID'
require_marker "deploy/runtime-data-encryption-cutover.sh" '-e NPCINK_CLOUD_SERVICE_SETTINGS_OLD_ROOT_SECRET'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'python -m app.dev.reencrypt_service_secrets'
require_marker "deploy/runtime-data-encryption-cutover.sh" '-e NPCINK_CLOUD_DATABASE_URL'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'run_exact_api_one_off "${env_flags[@]}" --'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'whole_database_restore_required_for_rollback'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'rmdir "${DEPLOY_LOCK_DIR}"'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'publish_fresh_file "${FINAL_RESULT_TMP}" "${PASSED_RESULT}"'
require_marker_before "deploy/runtime-data-encryption-cutover.sh" \
	'fsync_p1_e06_recovery_anchors ||' \
	'CURRENT_STAGE="apply-governed-edge-readiness-env-handoff"'
require_marker_before "deploy/runtime-data-encryption-cutover.sh" \
	'CURRENT_STAGE="apply-governed-edge-readiness-env-handoff"' \
	'CURRENT_STAGE="verify-certificate-renewal-readiness"'
require_marker_before "deploy/runtime-data-encryption-cutover.sh" \
	'CURRENT_STAGE="verify-certificate-renewal-readiness"' \
	'CURRENT_STAGE="prepare-exact-bundle-images"'
require_marker_before "deploy/runtime-data-encryption-cutover.sh" \
	'CURRENT_STAGE="verify-local-docker-and-host-edge"' \
	'CURRENT_STAGE="prepare-exact-bundle-images"'
p1_e06_phases=(
	'CURRENT_STAGE="create-fresh-custom-backup"'
	'CURRENT_STAGE="wait-for-off-host-backup-receipt"'
	'CURRENT_STAGE="independent-postgres16-restore"'
	'CURRENT_STAGE="production-migrate-0058-to-head"'
	'CURRENT_STAGE="prepare-private-success-evidence"'
	'CURRENT_STAGE="cleanup-rollback-images-and-map"'
	'CURRENT_STAGE="publish-terminal-success-evidence"'
	'CURRENT_STAGE="publish-global-activation-receipt"'
	'CURRENT_STAGE="release-deploy-lock"'
	'CURRENT_STAGE="complete"'
)
for ((phase_index = 0; phase_index < ${#p1_e06_phases[@]} - 1; phase_index++)); do
	require_marker_before "deploy/runtime-data-encryption-cutover.sh" \
		"${p1_e06_phases[${phase_index}]}" \
		"${p1_e06_phases[$((phase_index + 1))]}"
done

require_marker "deploy/deploy-to-ssh-host.sh" 'RELEASE_STATE_ROOT="${REMOTE_DIR}/.release-state"'
require_marker "deploy/deploy-to-ssh-host.sh" 'RELEASE_STATE_DIR="${RELEASE_STATE_ROOT}/${RELEASE_NAME}"'
require_marker "deploy/deploy-to-ssh-host.sh" 'RELEASE_ENV_FILE="${RELEASE_STATE_DIR}/env.deploy"'
require_marker "deploy/deploy-to-ssh-host.sh" 'ensure_private_release_state_directory "${RELEASE_STATE_ROOT}"'
require_marker "deploy/deploy-to-ssh-host.sh" 'ensure_private_release_state_directory "${RELEASE_STATE_DIR}"'
require_marker "deploy/deploy-to-ssh-host.sh" 'install -m 0600 "${NEW_ENV_SOURCE}" "${RELEASE_ENV_TMP}"'
require_marker "deploy/deploy-to-ssh-host.sh" 'mv -n "${RELEASE_ENV_TMP}" "${RELEASE_ENV_FILE}"'
require_marker "deploy/deploy-to-ssh-host.sh" 'export NPCINK_CLOUD_BACKEND_ENV_FILE="${RELEASE_ENV_FILE}"'
require_marker "deploy/deploy-to-ssh-host.sh" 'Compose project rename is not supported during ordinary deployment'
require_marker "deploy/deploy-to-ssh-host.sh" 'com.docker.compose.project'
require_marker "deploy/deploy-to-ssh-host.sh" '--skip-frontend-image requires an existing managed release'
require_marker "deploy/deploy-to-ssh-host.sh" 'local clean_env=(env -i'
require_marker "deploy/deploy-to-ssh-host.sh" 'assert_p1_e06_ordinary_deploy_gate()'
require_marker "deploy/deploy-to-ssh-host.sh" 'NPCINK_CLOUD_REQUIRE_P1_E06_RECEIPT:-1'
require_marker "deploy/deploy-to-ssh-host.sh" 'Full deployment cannot disable the P1-E06 activation receipt gate'
require_marker "deploy/deploy-to-ssh-host.sh" 'Ordinary production deployment cannot migrate revision 0058'
require_marker "deploy/deploy-to-ssh-host.sh" 'p1_e06_global_activation.v1'
reject_marker "deploy/deploy-to-ssh-host.sh" 'npcink.controlled_production_cve_risk_acceptance.v1'
reject_marker "deploy/runtime-data-encryption-cutover.sh" 'npcink.controlled_production_cve_risk_acceptance.v1'
reject_marker "scripts/production-image-supply.py" 'npcink.controlled_production_cve_risk_acceptance.v1'
require_marker "deploy/deploy-to-ssh-host.sh" 'a migration-graph descendant shipped by this release'
require_marker ".github/workflows/deploy-production.yml" 'NPCINK_CLOUD_REQUIRE_P1_E06_RECEIPT: "1"'
require_marker "deploy/workspace-target.env.sh" 'NPCINK_CLOUD_REQUIRE_P1_E06_RECEIPT="1"'
require_marker "docs/cloud-production-release-policy-v1.md" 'production deployment is never an implicit host bootstrap'
require_marker_before "deploy/deploy-to-ssh-host.sh" \
	'Compose project rename is not supported during ordinary deployment' \
	'CUTOVER_MUTATION_STARTED=1'

require_marker "deploy/certificate-renewal-readiness.sh" 'CONTRACT="npcink_cloud_certificate_renewal_readiness.v1"'
require_marker "deploy/certificate-renewal-readiness.sh" 'MAX_EVIDENCE_AGE_SECONDS=$((7 * 24 * 60 * 60))'
require_marker "deploy/certificate-renewal-readiness.sh" 'MINIMUM_CERTIFICATE_VALIDITY_DAYS=30'
require_marker "deploy/certificate-renewal-readiness.sh" '"${CERTBOT_REAL_PATH}" renew --dry-run --cert-name "${CERTBOT_LINEAGE_NAME}"'
require_marker "deploy/certificate-renewal-readiness.sh" 'Alibaba Cloud Linux 3 EPEL Certbot 1.22 has no --run-deploy-hooks flag.'
require_marker "deploy/certificate-renewal-readiness.sh" 'The mandatory direct hook/reload proof immediately below remains the hook gate.'
reject_marker "deploy/certificate-renewal-readiness.sh" 'renew --dry-run --cert-name "${CERTBOT_LINEAGE_NAME}" --run-deploy-hooks'
require_marker "deploy/certificate-renewal-readiness.sh" '--property=Unit'
require_marker "deploy/certificate-renewal-readiness.sh" '--property=ExecStart'
require_marker "deploy/certificate-renewal-readiness.sh" 'if os.path.realpath(exec_path) != expected_certbot_real_path:'
require_marker "deploy/certificate-renewal-readiness.sh" 'if arguments.count("renew") != 1:'
require_marker "deploy/certificate-renewal-readiness.sh" 'ignore_errors != "no"'
require_marker "deploy/certificate-renewal-readiness.sh" 'renewal_service'
require_marker "deploy/certificate-renewal-readiness.sh" 'certbot_real_path'
require_marker "deploy/certificate-renewal-readiness.sh" 'renewal_exec_start_sha256'
require_marker "deploy/certificate-renewal-readiness.sh" '--property=ExecReload'
require_marker "deploy/certificate-renewal-readiness.sh" 'evidence must have mode 0600'
require_marker "deploy/certificate-renewal-readiness.sh" 'invalidate_existing_evidence'
require_marker "deploy/certificate-renewal-readiness.sh" '-connect 127.0.0.1:443'
require_marker "deploy/certificate-renewal-readiness.sh" 'deploy hook must be located directly in renewal-hooks/deploy'
require_marker "deploy/certificate-renewal-readiness.sh" 'deploy_hook_sha256'
require_marker "deploy/certificate-renewal-readiness.sh" 'certificate path must be a Certbot live symlink'
require_marker "deploy/certificate-renewal-readiness.sh" 'private-key archive target must not grant group or other permissions'
require_marker "deploy/certificate-renewal-readiness.sh" 'nginx -T'
require_marker "deploy/certificate-renewal-readiness.sh" 'nginx_ssl_certificate_key_path'
require_marker "deploy/certificate-renewal-readiness.sh" 'certificate_private_key_match'
require_marker "deploy/bind-domain-to-ssh-host.sh" 'DEPLOY_LOCK_DIR="${REMOTE_DIR}/.deploy-lock"'
require_marker "deploy/bind-domain-to-ssh-host.sh" 'docker stop "${ORIGINAL_CADDY_IDS[@]}"'
require_marker "deploy/bind-domain-to-ssh-host.sh" 'docker start "${ORIGINAL_CADDY_IDS[@]}"'
require_marker "deploy/bind-domain-to-ssh-host.sh" 'verify_original_caddy_running'
require_marker "deploy/bind-domain-to-ssh-host.sh" 'restore_nginx_files'
require_marker "deploy/bind-domain-to-ssh-host.sh" 'remote_shell_arg() {'
reject_marker "deploy/bind-domain-to-ssh-host.sh" 'REMOTE_CERT_DIR'
reject_marker "deploy/bind-domain-to-ssh-host.sh" '"${SSH_TARGET}" bash -s --'
require_marker "deploy/remote-load-and-up.sh" 'verify_certificate_renewal_readiness'
require_marker "deploy/remote-load-and-up.sh" 'Certificate-renewal readiness verifier is missing or not executable.'
require_marker "deploy/remote-load-and-up.sh" 'Formal runtime requires NPCINK_CLOUD_CERTIFICATE_RENEWAL_TIMER.'
require_marker "deploy/remote-load-and-up.sh" 'Formal runtime requires NPCINK_CLOUD_CERTIFICATE_RENEWAL_HOOK_PATH.'

cutover_phases=(
	'CUTOVER_PHASE="prepare-release-images"'
	'CUTOVER_PHASE="stop-old-application-services"'
	'CUTOVER_PHASE="start-data-services"'
	'CUTOVER_PHASE="migrate-with-staged-image"'
	'CUTOVER_PHASE="activate-new-release-pointer"'
	'CUTOVER_PHASE="start-new-api"'
	'CUTOVER_PHASE="start-new-workers"'
	'CUTOVER_PHASE="verify-worker-operational-readiness"'
	'CUTOVER_PHASE="restore-frontend-and-proxy-traffic"'
)
for ((phase_index = 0; phase_index < ${#cutover_phases[@]} - 1; phase_index++)); do
	require_marker_before "deploy/deploy-to-ssh-host.sh" \
		"${cutover_phases[${phase_index}]}" \
		"${cutover_phases[$((phase_index + 1))]}"
done
require_marker "deploy/deploy-to-ssh-host.sh" 'MIGRATION_STARTED=1'
require_marker "deploy/deploy-to-ssh-host.sh" 'Never manufacture a rollback by starting the old API'
require_marker "deploy/deploy-to-ssh-host.sh" 'Deployment lock retained for operator recovery'
require_marker "deploy/deploy-to-ssh-host.sh" 'GLOBAL_ONE_OFF_LOCK_DIR="${RELEASE_STATE_ROOT}/.release-one-off.lock"'
require_marker "deploy/deploy-to-ssh-host.sh" 'assert_governed_one_off_absent'
require_marker "deploy/deploy-to-ssh-host.sh" 'release-one-off)'
require_marker_before "deploy/deploy-to-ssh-host.sh" \
	'assert governed one-off absent before mutation' \
	'CUTOVER_PHASE="prepare-release-images"'
require_marker "deploy/deploy-to-ssh-host.sh" 'rm -f "${ROLLBACK_IMAGE_MAP}"'
require_marker "deploy/deploy-to-ssh-host.sh" '--worker-cutoff "${WORKER_CUTOFF}"'

require_marker "deploy/remote-load-and-up.sh" 'prepare-only|data-only|api-only|workers-only|traffic-only'
reject_marker "deploy/remote-load-and-up.sh" 'full|prepare-only'
reject_marker "deploy/remote-load-and-up.sh" 'up -d --pull never --no-build'
reject_marker "deploy/remote-load-and-up.sh" 'NPCINK_CLOUD_TARGET_DAEMON_MAP'
reject_marker "deploy/remote-load-and-up.sh" '--target-daemon-map'
require_marker "deploy/remote-load-and-up.sh" 'up --no-start --pull never --no-build --no-deps --force-recreate'
require_marker "deploy/remote-load-and-up.sh" 'docker start "${container_ids_to_start[@]}"'
require_marker "deploy/remote-load-and-up.sh" 'remove_exact_candidate_services'
require_marker "deploy/remote-load-and-up.sh" 'docker container ls -aq --no-trunc'
require_marker "deploy/remote-load-and-up.sh" "{{.State.Status}} {{.RestartCount}}"
require_marker "deploy/remote-load-and-up.sh" 'Exact release loader requires a canonical bundled Compose file.'
require_marker "deploy/remote-load-and-up.sh" 'npcink-ai-cloud-external-redis:prod'
require_marker "deploy/remote-load-and-up.sh" 'true false 0 healthy'
require_marker "deploy/common.sh" 'up --no-start --pull never'
require_marker "deploy/common.sh" '--no-build --no-deps --force-recreate "${proof_service}"'
require_marker "deploy/common.sh" 'docker start "${container_name}"'
require_marker "deploy/common.sh" '.release-one-off.lock'
require_marker "deploy/common.sh" "{{.State.Status}} {{.RestartCount}}"
reject_marker "deploy/common.sh" 'run -d'
require_marker "docker-compose.prod.yml" 'release-one-off:'
require_marker "docker-compose.runtime.yml" 'release-one-off:'
require_marker "docker-compose.prod.yml" 'profiles: ["release-one-off"]'
require_marker "docker-compose.runtime.yml" 'profiles: ["release-one-off"]'
require_marker "docker-compose.prod.yml" 'import signal; signal.pause()'
require_marker "docker-compose.runtime.yml" 'import signal; signal.pause()'
reject_marker "docs/cloud-production-release-policy-v1.md" 'run -d --name'
reject_marker "deploy/OPS_PLAYBOOK.md" 'run -d --name'
reject_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" 'run -d --name'
reject_marker "deploy/RELEASE_CHECKLIST.md" 'run -d --name'
require_marker "deploy/common.sh" "docker inspect --format '{{.Image}}'"
require_marker "deploy/common.sh" 'docker exec -i "${exec_env_args[@]}" "${container_name}"'
require_marker "deploy/common.sh" 'docker rm -f "${container_name}"'
require_marker "deploy/common.sh" "trap 'one_off_signal 143' TERM"
require_marker "deploy/runtime-data-encryption-cutover.sh" 'ONE_OFF_PREVIOUS_ASYNC_PID="$!"'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'observed_async_pid="$!"'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'ACTIVE_ONE_OFF_PID="${observed_async_pid}"'
require_marker_before "deploy/runtime-data-encryption-cutover.sh" \
	'set +x' 'MAINTENANCE_ENV_SOURCE_PROOF='
require_marker_before "deploy/runtime-data-encryption-cutover.sh" \
	'CURRENT_STAGE="prove-governed-one-off-absence-before-mutation"' \
	'CURRENT_STAGE="prepare-exact-bundle-images"'
require_marker "deploy/remote-migrate.sh" 'loaded-role-daemon-id'
require_marker "deploy/remote-migrate.sh" 'npcink_ai_cloud_compose_run_with_image_proof'
require_marker "deploy/common.sh" 'npcink_ai_cloud_require_deploy_lock_owner()'
require_marker_before "deploy/remote-load-and-up.sh" \
	'npcink_ai_cloud_require_deploy_lock_owner "${ROOT_DIR}"' \
	'npcink_ai_cloud_load_env_file "${ROOT_DIR}"'
require_marker "deploy/remote-migrate.sh" 'npcink_ai_cloud_require_deploy_lock_owner "${ROOT_DIR}"'
require_marker "deploy/remote-refresh-providers.sh" 'npcink_ai_cloud_require_deploy_lock_owner "${ROOT_DIR}"'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'NPCINK_CLOUD_DEPLOY_LOCK_OWNER="${DEPLOY_LOCK_OWNER}"'
require_marker "scripts/cloud-deploy-bundle-smoke-flow.sh" 'NPCINK_CLOUD_DEPLOY_LOCK_OWNER="${DEPLOY_LOCK_OWNER}"'
reject_marker "deploy/common.sh" 'eval "export ${line}"'
require_marker "deploy/common.sh" 'npcink_ai_cloud_env_key_is_runtime_config()'
require_marker "deploy/common.sh" 'npcink_ai_cloud_env_key_is_shell_importable()'
require_marker "deploy/common.sh" 'npcink_ai_cloud_compose_service_image_reference()'
require_marker "deploy/common.sh" 'npcink_ai_cloud_assert_container_matches_rollback_image()'
require_marker "deploy/deploy-to-ssh-host.sh" 'RECOVERY_REQUIRED_SERVICES=(postgres redis proxy frontend api worker callback-worker ops-worker)'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'fence_previous_runtime_recovery()'
require_marker "deploy/common.sh" 'Dotenv key is not an allowed runtime setting'
reject_marker "deploy/deploy-to-ssh-host.sh" 'npcink-cloud-test-secret'
require_marker "deploy/deploy-to-ssh-host.sh" 'NPCINK_CLOUD_SECRET is required unless both runtime seed and signed smoke are skipped.'
require_marker "deploy/deploy-to-ssh-host.sh" 'protected process environment'
reject_marker "deploy/remote-smoke.sh" 'npcink-cloud-test-secret'
require_marker "deploy/remote-smoke.sh" 'NPCINK_CLOUD_SECRET is required for signed runtime smoke'
require_marker "deploy/remote-bootstrap-portal-site.sh" 'NPCINK_CLOUD_SECRET is required with --issue-key so the issued key is recoverable.'
require_marker "deploy/bootstrap-portal-site-to-ssh-host.sh" 'Remote portal bootstrap does not support --issue-key'
require_marker "deploy/bootstrap-portal-site-to-ssh-host.sh" '--secret is forbidden because process arguments and the SSH command are observable.'
require_marker "README.md" 'The remote'
require_marker "README.md" '`portal:bind:ssh` wrapper intentionally rejects key issuance.'
require_marker "docs/cloud-production-release-policy-v1.md" 'p1_e06_edge_readiness_env_handoff.v1'
require_marker "docs/cloud-production-release-policy-v1.md" 'digest-bound maintenance snapshot'
require_marker "deploy/OPS_PLAYBOOK.md" '--edge-readiness-env /run/npcink-ai-cloud/p1-e06-edge-readiness.env'
require_marker "deploy/PRODUCTION_GITHUB_DEPLOY.md" '--edge-readiness-env /run/npcink-ai-cloud/p1-e06-edge-readiness.env'
require_marker "deploy/RELEASE_CHECKLIST.md" 'p1_e06_edge_readiness_env_handoff.v1'
reject_marker "deploy/production-performance-baseline-to-ssh-host.sh" '--with-synthetic-smoke'
reject_marker "deploy/production-performance-baseline-to-ssh-host.sh" 'remote-smoke.sh'
reject_marker "README.md" '--secret npcink-cloud-test-secret'
require_marker "README.md" 'IFS= read -r -s NPCINK_CLOUD_SECRET'
require_marker "README.md" 'is not read from `.env.deploy`'
reject_file "deploy/env-to-ssh-host.sh"
reject_file "deploy/remote-env-upsert.sh"
reject_marker "package.json" '"env:ssh"'
reject_marker "Makefile" "env-ssh"
reject_marker "deploy/remote-migrate.sh" 'NPCINK_CLOUD_MIGRATION_ONLY'
reject_marker "deploy/remote-migrate.sh" 'up -d --pull never --no-build'
reject_marker "deploy/remote-migrate.sh" 'worker callback-worker ops-worker'
require_marker_before "scripts/cloud-deploy-bundle-smoke-flow.sh" \
	'NPCINK_CLOUD_LOAD_MODE=data-only' \
	'run_deploy_command bash deploy/remote-migrate.sh'
require_marker_before "scripts/cloud-deploy-bundle-smoke-flow.sh" \
	'run_deploy_command bash deploy/remote-migrate.sh' \
	'NPCINK_CLOUD_LOAD_MODE=api-only'
require_marker "deploy/remote-refresh-providers.sh" 'loaded-role-daemon-id'
require_marker "deploy/remote-refresh-providers.sh" 'npcink_ai_cloud_compose_run_with_image_proof'
reject_marker "deploy/remote-refresh-providers.sh" 'exec -T api'
reject_marker "deploy/remote-refresh-providers.sh" 'NPCINK_CLOUD_REFRESH_PROVIDERS_ONE_OFF'
reject_marker "deploy/deploy-to-ssh-host.sh" 'NPCINK_CLOUD_REFRESH_PROVIDERS_ONE_OFF'
require_marker "deploy/remote-load-and-up.sh" 'loaded-role-daemon-id'
require_marker "deploy/runtime-data-encryption-cutover.sh" 'loaded-role-daemon-id'
require_marker "scripts/verify-release-bundle-manifest.py" 'validate_target_daemon_map_payload'
require_marker "scripts/verify-release-bundle-manifest.py" 'load_strict_target_daemon_map'
require_marker "scripts/verify-release-bundle-manifest.py" 'MAX_TARGET_DAEMON_MAP_BYTES = 256 * 1024'
require_marker "scripts/verify-release-bundle-manifest.py" '"release_name": root.resolve().name'
require_marker "scripts/verify-release-bundle-manifest.py" '"release_path": str(root.resolve())'
require_marker "deploy/RELEASE_CHECKLIST.md" '.release-state/<release-name>/target-daemon-images.json'
require_marker "deploy/RELEASE_CHECKLIST.md" 'canonical resolved release path'
require_marker "deploy/RELEASE_CHECKLIST.md" 'required a fresh'
require_marker "docs/p5-b5-exact-release-bundle-v1.md" 'canonical resolved release path'
require_marker "docs/p5-b5-exact-release-bundle-v1.md" 'operator must rerun `prepare-only` and the full verifier'
reject_marker "deploy/remote-migrate.sh" ' role-image-id'
reject_marker "deploy/remote-refresh-providers.sh" ' role-image-id'
reject_marker "deploy/remote-load-and-up.sh" ' role-image-id'
reject_marker "deploy/runtime-data-encryption-cutover.sh" ' role-image-id'
reject_marker "deploy/remote-migrate.sh" 'run --rm --no-deps --pull never'
reject_marker "deploy/remote-refresh-providers.sh" 'run --rm --no-deps --pull never'
reject_marker "deploy/runtime-data-encryption-cutover.sh" 'run --rm --no-deps --pull never'
require_marker "deploy/remote-operational-ready.sh" 'Cutover operational readiness requires --worker-cutoff.'
require_marker "deploy/remote-operational-ready.sh" 'restart_count_value != 0'
require_marker "deploy/remote-operational-ready.sh" 'observed[worker_id] <= cutoff'
require_marker "deploy/remote-operational-ready.sh" 'Worker container changed during the stability window'
require_marker_before "deploy/remote-operational-ready.sh" \
	'All required worker heartbeats are newer than the cutover cutoff.' \
	'/health/operational-ready'

require_marker "deploy/bundle-images.sh" 'git -C "${CLOUD_DIR}" archive HEAD'
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
require_marker ".github/workflows/ci.yml" "branches: [master, main, production]"
require_marker ".github/workflows/ci.yml" "static_terms_only"
require_marker ".github/workflows/ci.yml" "site/terms/*"
reject_marker ".github/workflows/ci.yml" "environment: production"
reject_marker ".github/workflows/ci.yml" "deploy/deploy-to-ssh-host.sh"
reject_marker ".github/workflows/ci.yml" "deploy/deploy-static-terms-to-ssh-host.sh"
reject_marker ".github/workflows/ci.yml" "PROD_SSH_KEY"
require_marker ".github/workflows/deploy-production.yml" "workflow_dispatch:"
require_marker ".github/workflows/deploy-production.yml" "Approved for production validation by operator."
require_marker ".github/workflows/deploy-production.yml" "environment: production"
require_marker ".github/workflows/deploy-production.yml" "group: production-host-mutation"
require_marker ".github/workflows/deploy-production.yml" "actions: read"
require_marker ".github/workflows/deploy-production.yml" 'select(.head_sha == $sha)'
require_marker ".github/workflows/deploy-production.yml" 'test "${conclusion}" = "success"'
require_marker ".github/workflows/deploy-production.yml" 'NPCINK_CLOUD_DEPLOY_SSH_USER: ${{ secrets.PROD_SSH_USER }}'
require_marker ".github/workflows/deploy-production.yml" 'test "${PROD_SSH_USER}" = "root"'
require_marker ".github/workflows/deploy-production.yml" 'PROD_SSH_KNOWN_HOSTS: ${{ secrets.PROD_SSH_KNOWN_HOSTS }}'
require_marker ".github/workflows/deploy-production.yml" 'ssh-keygen -F "${known_host_lookup}"'
reject_marker ".github/workflows/deploy-production.yml" "ssh-keyscan"
require_marker "deploy/deploy-to-ssh-host.sh" 'the remote deployment account must have UID 0'
require_marker "deploy/deploy-to-ssh-host.sh" 'STAGE_ONLY_DISALLOWED_CLI'
require_marker "deploy/deploy-to-ssh-host.sh" '--stage-only accepts only bundle/platform'
require_marker "deploy/deploy-to-ssh-host.sh" 'StrictHostKeyChecking=yes'
reject_marker "deploy/deploy-to-ssh-host.sh" 'StrictHostKeyChecking=accept-new'
reject_marker ".github/workflows/production-maintenance.yml" "ssh-keyscan"
require_marker ".github/workflows/production-maintenance.yml" 'PROD_SSH_KNOWN_HOSTS: ${{ secrets.PROD_SSH_KNOWN_HOSTS }}'
require_marker ".github/workflows/production-maintenance.yml" 'StrictHostKeyChecking=yes'
require_marker ".github/workflows/production-maintenance.yml" "group: production-host-mutation"
require_marker ".github/workflows/production-maintenance.yml" "permissions: {}"
require_marker ".github/workflows/production-maintenance.yml" "safe_prune_confirmation:"
require_marker ".github/workflows/production-maintenance.yml" "Prune production images and old releases."
require_marker ".github/workflows/production-maintenance.yml" '[[ ! "${PROD_REMOTE_DIR}" =~ ^/[A-Za-z0-9._/-]+$ ]]'
require_marker ".github/workflows/production-maintenance.yml" 'remote_shell_arg() {'
require_marker ".github/workflows/production-maintenance.yml" 'ssh "${ssh_args[@]}" "${ssh_target}" "${remote_command}"'
reject_marker ".github/workflows/production-maintenance.yml" '"${ssh_target}" bash -s --'
require_marker ".github/workflows/production-maintenance.yml" 'mkdir -- "${remote_dir}/.deploy-lock"'
require_marker ".github/workflows/production-maintenance.yml" 'rmdir -- "${remote_dir}/.deploy-lock"'
for ssh_helper in \
	deploy/bind-domain-to-ssh-host.sh \
	deploy/deploy-static-terms-to-ssh-host.sh \
	deploy/production-performance-baseline-to-ssh-host.sh \
	deploy/wp-cron-to-ssh-host.sh \
	deploy/bootstrap-portal-site-to-ssh-host.sh \
	deploy/portal-smoke-to-ssh-host.sh; do
	require_marker "${ssh_helper}" 'StrictHostKeyChecking=yes'
	reject_marker "${ssh_helper}" 'StrictHostKeyChecking=accept-new'
done
reject_marker ".github/workflows/deploy-production.yml" "workflow_run:"
reject_marker ".github/workflows/deploy-production.yml" "push:"
require_marker ".github/workflows/deploy-production.yml" "github.ref == 'refs/heads/production'"

echo "[ok] Lightweight release policy gate passed"
