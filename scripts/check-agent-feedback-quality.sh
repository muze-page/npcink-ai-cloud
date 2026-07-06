#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "${PYTHON_BIN}" ]; then
	if [ -x ".venv/bin/python" ]; then
		PYTHON_BIN=".venv/bin/python"
	else
		PYTHON_BIN="python3"
	fi
fi

if [ -x ".venv/bin/ruff" ]; then
	RUFF_CMD=( ".venv/bin/ruff" )
else
	RUFF_CMD=( "${PYTHON_BIN}" "-m" "ruff" )
fi

ok() {
	echo "[agent-feedback-quality] $*"
}

ok "Validating Content Support regression fixture"
"${PYTHON_BIN}" -m json.tool \
	tests/fixtures/agent_feedback/content_support_regression_samples.json \
	>/tmp/magick-ai-content-support-regression-samples.json

ok "Running agent feedback API and regression tests"
"${PYTHON_BIN}" -m pytest tests/api/test_agent_feedback_routes.py -q

ok "Running targeted Python lint"
"${RUFF_CMD[@]}" check \
	app/domain/agent_feedback/service.py \
	app/api/routes/service.py \
	tests/api/test_agent_feedback_routes.py

ok "Running Cloud admin type check"
pnpm --dir frontend run type-check

ok "Running targeted Cloud admin lint"
pnpm --dir frontend exec eslint \
	src/app/admin/agent-feedback/page.tsx \
	src/app/admin/layout.tsx \
	src/app/admin/troubleshooting/page.tsx \
	--max-warnings=0

ok "Running read-only dashboard boundary contract"
(
	cd frontend
	node tests/unit/admin-agent-feedback-boundary-contract.mjs
	node tests/unit/admin-agent-feedback-i18n-contract.mjs
)

ok "Agent feedback quality gate passed"
