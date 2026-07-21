#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
UV_BIN="${UV_BIN:-uv}"
UVX_BIN="${UVX_BIN:-uvx}"
PIP_AUDIT_VERSION="2.10.1"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

export UV_NO_PROGRESS=1

audit_export() {
	local label="$1"
	shift
	local requirements_file="${TMP_DIR}/${label}.txt"

	echo "[run] Exporting locked ${label} Python dependencies"
	"${UV_BIN}" export \
		--quiet \
		--locked \
		--no-emit-project \
		--format requirements.txt \
		--output-file "${requirements_file}" \
		"$@"

	echo "[run] Auditing locked ${label} Python dependencies"
	"${UVX_BIN}" --from "pip-audit==${PIP_AUDIT_VERSION}" pip-audit \
		--disable-pip \
		--progress-spinner off \
		--require-hashes \
		--requirement "${requirements_file}"
}

cd "${ROOT_DIR}"

echo "[run] Verifying uv.lock is synchronized with pyproject.toml"
"${UV_BIN}" lock --check

audit_export default
audit_export zilliz --extra zilliz

echo "[ok] Locked default and zilliz Python dependency audits passed."
