#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLOUD_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="${CLOUD_DIR}"
BASE_REF="${NPCINK_CLOUD_CHANGED_BASE_REF:-origin/master}"

TMP_PATHS="$(mktemp)"
trap 'rm -f "${TMP_PATHS}"' EXIT

normalize_path() {
	local path="$1"
	local rel=""

	case "${path}" in
		"${REPO_ROOT}/"*)
			path="${path#${REPO_ROOT}/}"
			;;
	esac

	case "${path}" in
		*.py)
			if [ -f "${CLOUD_DIR}/${path}" ]; then
				rel="${path}"
			else
				return 1
			fi
			;;
		*)
			return 1
			;;
	esac

	if [ ! -f "${CLOUD_DIR}/${rel}" ]; then
		return 1
	fi

	printf '%s\n' "${rel}"
}

append_path() {
	local normalized=""

	normalized="$(normalize_path "$1" || true)"

	if [ -n "${normalized}" ]; then
		printf '%s\n' "${normalized}" >> "${TMP_PATHS}"
	fi
}

collect_changed_paths() {
	local merge_base=""

	if ! git -C "${REPO_ROOT}" rev-parse --verify --quiet "${BASE_REF}" >/dev/null; then
		if git -C "${REPO_ROOT}" rev-parse --verify --quiet master >/dev/null; then
			BASE_REF="master"
		else
			BASE_REF="$(git -C "${REPO_ROOT}" rev-list --max-parents=0 HEAD | head -n 1)"
		fi
	fi

	merge_base="$(git -C "${REPO_ROOT}" merge-base HEAD "${BASE_REF}")"

	while IFS= read -r path; do
		[ -n "${path}" ] || continue
		append_path "${path}"
	done < <(
		{
			git -C "${REPO_ROOT}" diff --name-only --diff-filter=ACMR "${merge_base}...HEAD"
			git -C "${REPO_ROOT}" diff --name-only --cached --diff-filter=ACMR
			git -C "${REPO_ROOT}" diff --name-only --diff-filter=ACMR
			git -C "${REPO_ROOT}" ls-files --others --exclude-standard
		} | sort -u
	)
}

if [ "$#" -gt 0 ]; then
	for arg in "$@"; do
		append_path "${arg}"
	done
else
	collect_changed_paths
	echo "[info] Comparing changed cloud Python files against base ref: ${BASE_REF}"
fi

if [ ! -s "${TMP_PATHS}" ]; then
	echo "[ok] No changed cloud Python files detected."
	exit 0
fi

sort -u "${TMP_PATHS}" -o "${TMP_PATHS}"

if [ ! -x "${CLOUD_DIR}/.venv/bin/python" ]; then
	echo "[fail] Missing ${CLOUD_DIR}/.venv/bin/python. Run 'make bootstrap-dev' first." >&2
	exit 1
fi

cd "${CLOUD_DIR}"

ruff_targets=()
mypy_targets=()

while IFS= read -r rel; do
	[ -n "${rel}" ] || continue
	ruff_targets+=("${rel}")
	case "${rel}" in
		app/*)
			mypy_targets+=("${rel}")
			;;
	esac
done < "${TMP_PATHS}"

echo "[info] Changed cloud Python files:"
sed 's/^/ - /' "${TMP_PATHS}"

echo "[run] ruff check changed files (correctness/import subset)"
"${CLOUD_DIR}/.venv/bin/python" -m ruff check --select I,F,E9 "${ruff_targets[@]}"

if [ "${#mypy_targets[@]}" -eq 0 ]; then
	echo "[ok] No changed cloud app Python files detected for mypy."
	exit 0
fi

echo "[run] mypy targeted changed app files"
bash "${CLOUD_DIR}/scripts/mypy-targeted.sh" "${mypy_targets[@]}"
