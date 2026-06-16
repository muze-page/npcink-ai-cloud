#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLOUD_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [ ! -x "${CLOUD_DIR}/.venv/bin/python" ]; then
	echo "[fail] Missing ${CLOUD_DIR}/.venv/bin/python. Run 'make bootstrap-dev' first." >&2
	exit 1
fi

profile=""
if [ "${1:-}" = "--profile" ]; then
	profile="${2:-}"
	if [ -z "${profile}" ]; then
		echo "[fail] --profile requires a value." >&2
		exit 1
	fi
	shift 2
fi

targets=("$@")
if [ "${#targets[@]}" -eq 0 ]; then
	case "${profile:-media-derivatives}" in
		media-derivatives)
			targets=(
				"app/domain/media_derivatives/contracts.py"
				"app/domain/media_derivatives/processor.py"
				"app/api/routes/media_derivatives.py"
			)
			;;
		commercial-runtime)
			targets=(
				"app/domain/commercial/credits.py"
				"app/domain/commercial/mixins/_admin_mixin.py"
				"app/domain/commercial/mixins/_runtime_mixin.py"
				"app/domain/commercial/mixins/_billing_mixin.py"
				"app/domain/site_knowledge/metrics.py"
				"app/domain/runtime/service.py"
				"app/api/routes/entitlements.py"
			)
			;;
		*)
			echo "[fail] Unknown mypy target profile: ${profile}" >&2
			exit 1
			;;
	esac
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
