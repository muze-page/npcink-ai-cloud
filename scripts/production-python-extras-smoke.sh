#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_TAG="${NPCINK_CLOUD_PROD_EXTRAS_DEFAULT_TAG:-npcink-ai-cloud-api:prod-extra-smoke-default}"
ZILLIZ_TAG="${NPCINK_CLOUD_PROD_EXTRAS_ZILLIZ_TAG:-npcink-ai-cloud-api:prod-extra-smoke-zilliz}"

fail() {
	echo "[fail] $*" >&2
	exit 1
}

ok() {
	echo "[ok] $*"
}

require_cmd() {
	local cmd="$1"
	command -v "${cmd}" >/dev/null 2>&1 || fail "Missing required command: ${cmd}"
}

docker_build() {
	local tag="$1"
	local package_extras="$2"
	docker build \
		--build-arg "PACKAGE_EXTRAS=${package_extras}" \
		-t "${tag}" \
		"${ROOT_DIR}"
}

verify_default_image() {
	docker run --rm "${DEFAULT_TAG}" python - <<'PY'
from __future__ import annotations

import importlib.util
import json

import app.api.main  # noqa: F401

has_pymilvus = importlib.util.find_spec("pymilvus") is not None
summary = {
    "image_role": "default_production_python",
    "app_import_ok": True,
    "pymilvus_installed": has_pymilvus,
    "expected_package_extras": "",
}
print(json.dumps(summary, indent=2, sort_keys=True))
if has_pymilvus:
    raise SystemExit(1)
PY
}

verify_zilliz_image() {
	docker run --rm "${ZILLIZ_TAG}" python - <<'PY'
from __future__ import annotations

import importlib.util
import json

import app.api.main  # noqa: F401

has_pymilvus = importlib.util.find_spec("pymilvus") is not None
summary = {
    "image_role": "zilliz_production_python",
    "app_import_ok": True,
    "pymilvus_installed": has_pymilvus,
    "expected_package_extras": "[zilliz]",
}
print(json.dumps(summary, indent=2, sort_keys=True))
if not has_pymilvus:
    raise SystemExit(1)
PY
}

require_cmd docker

ok "Building default production Python image without optional extras"
docker_build "${DEFAULT_TAG}" ""
ok "Verifying default production image excludes pymilvus"
verify_default_image

if [ "${NPCINK_CLOUD_PROD_EXTRAS_SKIP_ZILLIZ:-0}" = "1" ]; then
	ok "Skipping zilliz extra image build because NPCINK_CLOUD_PROD_EXTRAS_SKIP_ZILLIZ=1"
	exit 0
fi

ok "Building production Python image with zilliz extra"
docker_build "${ZILLIZ_TAG}" "[zilliz]"
ok "Verifying zilliz production image includes pymilvus"
verify_zilliz_image

ok "Production Python extras smoke completed successfully."
