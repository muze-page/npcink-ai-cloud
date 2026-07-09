#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
BASE_REF="${NPCINK_CLOUD_PR_BASE_REF:-origin/${GITHUB_BASE_REF:-master}}"
TMP_CHANGED="$(mktemp)"
TMP_TESTS="$(mktemp)"
trap 'rm -f "${TMP_CHANGED}" "${TMP_TESTS}"' EXIT

if ! git -C "${ROOT_DIR}" rev-parse --verify --quiet "${BASE_REF}" >/dev/null; then
	git -C "${ROOT_DIR}" fetch origin "${GITHUB_BASE_REF:-master}" --depth=1
fi

if git -C "${ROOT_DIR}" rev-parse --verify --quiet "${BASE_REF}" >/dev/null; then
	MERGE_BASE="$(git -C "${ROOT_DIR}" merge-base HEAD "${BASE_REF}")"
	{
		git -C "${ROOT_DIR}" diff --name-only --diff-filter=ACMR "${MERGE_BASE}...HEAD"
		git -C "${ROOT_DIR}" diff --name-only --cached --diff-filter=ACMR
		git -C "${ROOT_DIR}" diff --name-only --diff-filter=ACMR
		git -C "${ROOT_DIR}" ls-files --others --exclude-standard
	} | sort -u > "${TMP_CHANGED}"
else
	{
		git -C "${ROOT_DIR}" diff --name-only --diff-filter=ACMR HEAD~1...HEAD
		git -C "${ROOT_DIR}" diff --name-only --cached --diff-filter=ACMR
		git -C "${ROOT_DIR}" diff --name-only --diff-filter=ACMR
		git -C "${ROOT_DIR}" ls-files --others --exclude-standard
	} | sort -u > "${TMP_CHANGED}"
fi

echo "[info] PR backend changed files:"
if [ -s "${TMP_CHANGED}" ]; then
	sed 's/^/ - /' "${TMP_CHANGED}"
else
	echo " - (none)"
fi

requires_full_backend=0
while IFS= read -r path; do
	[ -n "${path}" ] || continue
	case "${path}" in
		pyproject.toml|uv.lock|Makefile|docker-compose*.yml|Dockerfile)
			requires_full_backend=1
			;;
		.github/workflows/ci.yml|tests/conftest.py|tests/fixtures/*|migrations/*|migrations/**/*)
			requires_full_backend=1
			;;
		app/core/config.py|app/core/db.py|app/core/models.py|app/api/auth.py)
			requires_full_backend=1
			;;
	esac
done < "${TMP_CHANGED}"

if [ "${requires_full_backend}" = "1" ]; then
	echo "[info] High-risk backend surface changed; running full backend gate."
	.venv/bin/ruff check .
	.venv/bin/mypy app
	.venv/bin/python -m pytest tests/api tests/contract tests/domain -q
	exit 0
fi

echo "[info] Running targeted PR backend gate."
bash scripts/check-release-policy.sh
pnpm run test:anti-drift
bash scripts/check-changed-python-quality.sh

echo "[run] pytest contract gate"
.venv/bin/python -m pytest tests/contract -q

while IFS= read -r path; do
	case "${path}" in
		tests/api/test_*.py|tests/contract/test_*.py|tests/domain/test_*.py|tests/core/test_*.py|tests/dev/test_*.py)
			printf '%s\n' "${path}"
			;;
	esac
done < "${TMP_CHANGED}" | sort -u > "${TMP_TESTS}"

if [ -s "${TMP_TESTS}" ]; then
	echo "[run] pytest changed test files"
	.venv/bin/python -m pytest $(cat "${TMP_TESTS}") -q
else
	echo "[ok] No changed pytest files detected."
fi
