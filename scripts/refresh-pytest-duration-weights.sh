#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
EXPECTED_SHARDS=3

usage() {
	cat <<'EOF'
Usage:
  pnpm run ci:pytest:weights:refresh -- <successful-cloud-ci-run-id>

Downloads all backend pytest timing artifacts from one successful GitHub
Actions run and atomically regenerates ci/pytest-backend-durations.json.
EOF
}

if [ "${1:-}" = "--" ]; then
	shift
fi
if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
	usage
	exit 0
fi
if [ "$#" -ne 1 ] || ! [[ "$1" =~ ^[0-9]+$ ]]; then
	usage >&2
	exit 2
fi

if ! command -v gh >/dev/null 2>&1; then
	echo "[error] GitHub CLI (gh) is required" >&2
	exit 1
fi

PYTHON_BIN="${NPCINK_CLOUD_CI_PYTHON:-python3}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
	echo "[error] Python executable is unavailable: ${PYTHON_BIN}" >&2
	exit 1
fi

RUN_ID="$1"
TEMP_ROOT="${TMPDIR:-/tmp}"
TEMP_ROOT="${TEMP_ROOT%/}"
TEMP_DIR="$(mktemp -d "${TEMP_ROOT}/npcink-pytest-weights.XXXXXX")"
OUTPUT_TEMP=""
cleanup() {
	rm -rf "${TEMP_DIR}"
	if [ -n "${OUTPUT_TEMP}" ]; then
		rm -f "${OUTPUT_TEMP}"
	fi
}
trap cleanup EXIT

gh run download "${RUN_ID}" \
	--dir "${TEMP_DIR}" \
	--pattern 'pytest-backend-timing-shard-*'

reports=()
while IFS= read -r report_path; do
	reports+=("${report_path}")
done < <(find "${TEMP_DIR}" -type f -name 'pytest-backend-shard-*.xml' -print | sort)

if [ "${#reports[@]}" -ne "${EXPECTED_SHARDS}" ]; then
	echo "[error] expected ${EXPECTED_SHARDS} pytest shard reports, found ${#reports[@]}" >&2
	exit 1
fi

OUTPUT_TEMP="$(mktemp "${ROOT_DIR}/ci/.pytest-backend-durations.XXXXXX")"
"${PYTHON_BIN}" "${ROOT_DIR}/scripts/write-pytest-duration-weights.py" \
	"${reports[@]}" \
	--output "${OUTPUT_TEMP}" \
	--source-label "GitHub Actions run ${RUN_ID} pytest-backend timing shards"
mv "${OUTPUT_TEMP}" "${ROOT_DIR}/ci/pytest-backend-durations.json"
OUTPUT_TEMP=""

printf '[ok] Refreshed pytest duration weights from run %s (%s shards)\n' \
	"${RUN_ID}" "${#reports[@]}"
