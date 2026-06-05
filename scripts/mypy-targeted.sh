#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLOUD_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [ ! -x "${CLOUD_DIR}/.venv/bin/python" ]; then
	echo "[fail] Missing ${CLOUD_DIR}/.venv/bin/python. Run 'make bootstrap-dev' first." >&2
	exit 1
fi

targets=("$@")
if [ "${#targets[@]}" -eq 0 ]; then
	targets=(
		"app/domain/media_derivatives/contracts.py"
		"app/domain/media_derivatives/processor.py"
		"app/api/routes/media_derivatives.py"
	)
fi

tmp_config="$(mktemp)"
trap 'rm -f "${tmp_config}"' EXIT

cat > "${tmp_config}" <<'EOF'
[mypy]
python_version = 3.12
check_untyped_defs = True
disallow_untyped_defs = True
ignore_missing_imports = True
warn_redundant_casts = True
warn_unused_ignores = True
warn_unused_configs = True
EOF

cd "${CLOUD_DIR}"

echo "[run] mypy targeted files with an isolated config"
"${CLOUD_DIR}/.venv/bin/python" -m mypy \
	--config-file "${tmp_config}" \
	--follow-imports=skip \
	"${targets[@]}"
