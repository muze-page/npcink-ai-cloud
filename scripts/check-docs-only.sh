#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
BASE_REF="${NPCINK_CLOUD_CI_BASE_SHA:-origin/${GITHUB_BASE_REF:-master}}"
HEAD_REF="${NPCINK_CLOUD_CI_HEAD_SHA:-HEAD}"

if ! git -C "${ROOT_DIR}" rev-parse --verify --quiet "${BASE_REF}" >/dev/null; then
	git -C "${ROOT_DIR}" fetch origin "${GITHUB_BASE_REF:-master}" --depth=1
fi

if ! git -C "${ROOT_DIR}" rev-parse --verify --quiet "${BASE_REF}" >/dev/null; then
	echo "[error] docs-only base ref is unavailable: ${BASE_REF}" >&2
	exit 1
fi
if ! git -C "${ROOT_DIR}" rev-parse --verify --quiet "${HEAD_REF}" >/dev/null; then
	echo "[error] docs-only head ref is unavailable: ${HEAD_REF}" >&2
	exit 1
fi

mapfile -t changed_files < <(
	git -C "${ROOT_DIR}" diff --name-only --diff-filter=ACMRD "${BASE_REF}...${HEAD_REF}"
)
if [ "${#changed_files[@]}" -eq 0 ]; then
	echo "[error] docs-only gate received no changed files" >&2
	exit 1
fi

classification="$(bash "${ROOT_DIR}/scripts/classify-ci-changes.sh" "${changed_files[@]}")"
if ! grep -qx 'docs_only=true' <<< "${classification}"; then
	echo "[error] docs-only gate received a non-documentation change" >&2
	printf '%s\n' "${classification}" >&2
	printf ' - %s\n' "${changed_files[@]}" >&2
	exit 1
fi

bash "${ROOT_DIR}/scripts/check-release-policy.sh"
git -C "${ROOT_DIR}" diff --check "${BASE_REF}...${HEAD_REF}"

printf '[ok] Docs-only gate passed for %s file(s)\n' "${#changed_files[@]}"
