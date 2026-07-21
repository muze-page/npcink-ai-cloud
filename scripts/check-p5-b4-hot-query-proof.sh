#!/usr/bin/env bash
set -euo pipefail

# P5-B4 disposable PostgreSQL 16 hot-query proof. Formal mode is the default;
# quick mode is explicitly non-acceptance evidence.

umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.p5-b4-query-proof.yml"
EXPECTED_DATABASE="npcink_p5_b4_hot_query_proof"
EXPECTED_MARKER="npcink.p5_b4_hot_query_proof.disposable.v1"
MODE="formal"
OUTPUT_FILE="-"
CONFIRMED=0
TMP_DIR=""
PROJECT_NAME=""
CLEANUP_DONE=0
CLEANUP_STATUS=0

usage() {
	printf '%s\n' \
		'Usage: check-p5-b4-hot-query-proof.sh --confirm-disposable [--formal|--quick] [--output FILE]'
}

sha256_file() {
	python3 - "$1" <<'PY'
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())
PY
}

publish_output() {
	local output_file="$1"
	python3 -c '
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

target = Path(sys.argv[1])
descriptor, temporary_name = tempfile.mkstemp(
    dir=str(target.parent),
    prefix=f".{target.name}.",
    suffix=".tmp",
)
try:
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(sys.stdin.buffer.read())
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary_name, 0o600)
    os.replace(temporary_name, target)
except BaseException:
    try:
        os.unlink(temporary_name)
    except FileNotFoundError:
        pass
    raise
' "${output_file}"
}

print_status() {
	local status="$1"
	local phase="$2"
	case "${status}" in
		PASS | FAIL) ;;
		*) return 1 ;;
	esac
	case "${phase}" in
		preflight | database | migration | proof | teardown | complete | signal_int | signal_term) ;;
		*) return 1 ;;
	esac
	printf 'P5-B4-HOT-QUERY %s mode=%s phase=%s\n' "${status}" "${MODE}" "${phase}" >&2
}

cleanup() {
	if ((CLEANUP_DONE)); then
		return "${CLEANUP_STATUS}"
	fi
	CLEANUP_DONE=1
	local cleanup_status=0
	if [[ -n "${PROJECT_NAME}" ]]; then
		if ! docker compose \
			-p "${PROJECT_NAME}" \
			-f "${COMPOSE_FILE}" \
			down --volumes --remove-orphans --rmi local >/dev/null 2>&1; then
			cleanup_status=1
		fi
	fi
	if [[ -n "${TMP_DIR}" && -d "${TMP_DIR}" ]]; then
		if ! find "${TMP_DIR}" -type f -delete >/dev/null 2>&1; then
			cleanup_status=1
		fi
		if ! rmdir "${TMP_DIR}" >/dev/null 2>&1; then
			cleanup_status=1
		fi
	fi
	CLEANUP_STATUS="${cleanup_status}"
	return "${CLEANUP_STATUS}"
}

handle_signal() {
	local exit_code="$1"
	local phase="$2"
	trap - INT TERM
	cleanup >/dev/null 2>&1 || true
	trap - EXIT
	print_status FAIL "${phase}"
	exit "${exit_code}"
}

trap cleanup EXIT
trap 'handle_signal 130 signal_int' INT
trap 'handle_signal 143 signal_term' TERM

while (($#)); do
	case "$1" in
		--confirm-disposable)
			CONFIRMED=1
			shift
			;;
		--formal)
			MODE="formal"
			shift
			;;
		--quick)
			MODE="quick"
			shift
			;;
		--output)
			if (($# < 2)); then
				usage >&2
				exit 2
			fi
			OUTPUT_FILE="$2"
			shift 2
			;;
		--help | -h)
			usage
			exit 0
			;;
		*)
			usage >&2
			exit 2
			;;
	esac
done

if ((CONFIRMED != 1)); then
	printf '%s\n' 'Refusing to start: --confirm-disposable is required.' >&2
	print_status FAIL preflight
	exit 2
fi
if [[ "${OUTPUT_FILE}" != "-" && ! -d "$(dirname "${OUTPUT_FILE}")" ]]; then
	printf '%s\n' 'Refusing to start: output directory does not exist.' >&2
	print_status FAIL preflight
	exit 2
fi
if ! command -v docker >/dev/null 2>&1 \
	|| ! command -v git >/dev/null 2>&1 \
	|| ! command -v python3 >/dev/null 2>&1 \
	|| ! docker info >/dev/null 2>&1 \
	|| ! docker compose version >/dev/null 2>&1; then
	print_status FAIL preflight
	exit 1
fi
if ! P5_B4_CLOUD_REVISION="$(git -C "${ROOT_DIR}" rev-parse HEAD 2>/dev/null)" \
	|| [[ ! "${P5_B4_CLOUD_REVISION}" =~ ^[0-9a-f]{40}$ ]]; then
	print_status FAIL preflight
	exit 1
fi
if ! WORKTREE_STATUS="$(
	git -C "${ROOT_DIR}" status --porcelain=v1 --untracked-files=all 2>/dev/null
)"; then
	print_status FAIL preflight
	exit 1
fi
P5_B4_WORKTREE_DIRTY="false"
if [[ -n "${WORKTREE_STATUS}" ]]; then
	P5_B4_WORKTREE_DIRTY="true"
fi
P5_B4_WORKTREE_STATUS_SHA256="$(
	printf '%s' "${WORKTREE_STATUS}" \
		| python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'
)"
P5_B4_WORKTREE_DIRTY_ENTRY_COUNT="$(
	printf '%s' "${WORKTREE_STATUS}" \
		| python3 -c 'import sys; print(len(sys.stdin.read().splitlines()))'
)"
if [[ "${MODE}" == "formal" && "${P5_B4_WORKTREE_DIRTY}" == "true" ]]; then
	printf '%s\n' \
		'Refusing formal proof: tracked, staged, and untracked worktree state must be clean.' >&2
	print_status FAIL preflight
	exit 2
fi
if ! P5_B4_COMPOSE_SHA256="$(sha256_file "${COMPOSE_FILE}")" \
	|| ! P5_B4_WRAPPER_SHA256="$(sha256_file "${BASH_SOURCE[0]}")"; then
	print_status FAIL preflight
	exit 1
fi
export P5_B4_CLOUD_REVISION
export P5_B4_COMPOSE_SHA256
export P5_B4_WRAPPER_SHA256
export P5_B4_WORKTREE_DIRTY
export P5_B4_WORKTREE_STATUS_SHA256
export P5_B4_WORKTREE_DIRTY_ENTRY_COUNT

if ! TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/npcink-p5-b4-hot-query.XXXXXX")"; then
	print_status FAIL preflight
	exit 1
fi
if ! PROJECT_SUFFIX="$(python3 -c 'import secrets; print(secrets.token_hex(12))')"; then
	print_status FAIL preflight
	exit 1
fi
PROJECT_CANDIDATE="npcink-p5-b4-query-${PROJECT_SUFFIX}"
if [[ ! "${PROJECT_CANDIDATE}" =~ ^[a-z0-9][a-z0-9_-]{0,62}$ ]]; then
	print_status FAIL preflight
	exit 1
fi
PROJECT_NAME="${PROJECT_CANDIDATE}"

if ! docker compose \
	-p "${PROJECT_NAME}" \
	-f "${COMPOSE_FILE}" \
	up --detach --wait postgres >"${TMP_DIR}/compose.log" 2>&1; then
	print_status FAIL database
	exit 1
fi
if ! docker compose \
	-p "${PROJECT_NAME}" \
	-f "${COMPOSE_FILE}" \
	exec -T postgres \
	psql --set=ON_ERROR_STOP=1 \
	--username p5_b4_proof \
	--dbname "${EXPECTED_DATABASE}" \
	--command "COMMENT ON DATABASE ${EXPECTED_DATABASE} IS '${EXPECTED_MARKER}'" \
	>>"${TMP_DIR}/compose.log" 2>&1; then
	print_status FAIL database
	exit 1
fi
if ! docker compose \
	-p "${PROJECT_NAME}" \
	-f "${COMPOSE_FILE}" \
	run --rm -T proof-runner \
	alembic upgrade head >>"${TMP_DIR}/compose.log" 2>&1; then
	print_status FAIL migration
	exit 1
fi

PROOF_EXIT=0
if docker compose \
	-p "${PROJECT_NAME}" \
	-f "${COMPOSE_FILE}" \
	run --rm -T proof-runner \
	python scripts/p5_b4_hot_query_proof.py \
	--confirm-disposable \
	--mode "${MODE}" \
	>"${TMP_DIR}/result.json" 2>>"${TMP_DIR}/compose.log"; then
	PROOF_EXIT=0
else
	PROOF_EXIT="$?"
fi

if ! python3 - "${TMP_DIR}/result.json" "${MODE}" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text())
assert report["contract_version"] == "p5_b4_hot_query_proof.v1"
assert report["mode"] == sys.argv[2]
assert report["database_identity"]["database_marker_verified"] is True
worktree = report["revision_inputs"]["worktree_contract"]
assert worktree["formal_clean_required"] is True
assert len(worktree["status_sha256"]) == 64
for source_file in report["revision_inputs"]["source_files"].values():
    assert len(source_file["sha256"]) == 64
assert len(report["revision_inputs"]["migrations"]["manifest_sha256"]) == 64
assert len(report["revision_inputs"]["migrations"]["head_file_sha256"]) == 64
assert report["scope_and_limitations"] == {
    "cache_posture": "warm_cache_after_explicit_warmups",
    "connection_posture": "one_postgresql_connection",
    "does_not_prove": [
        "cold_cache_performance",
        "concurrent_contention",
        "production_data_distribution",
        "production_hardware_performance",
        "production_slo",
    ],
    "fixture_scope": "deterministic_synthetic_metadata_only",
    "p95_posture": "engineering_acceptance_threshold_not_production_slo",
    "query_execution_posture": "sequential_queries",
}
assert report["boundary"] == {
    "cloud_role": "runtime_performance_evidence",
    "contains_credentials": False,
    "contains_prompt_or_result_payloads": False,
    "direct_wordpress_write": False,
    "provider_execution_performed": False,
}
if sys.argv[2] == "quick":
    assert report["acceptance"]["eligible"] is False
    assert report["gate_posture"]["formal_gate_applied"] is False
    assert report["gate_posture"]["threshold_status"] == "not_evaluated_non_acceptance_quick"
    assert isinstance(worktree["dirty"], bool)
else:
    assert report["acceptance"]["eligible"] is True
    assert worktree["dirty"] is False
PY
then
	print_status FAIL proof
	exit 1
fi

RESULT_JSON="$(<"${TMP_DIR}/result.json")"
if ! cleanup; then
	trap - EXIT
	print_status FAIL teardown
	exit 1
fi
trap - EXIT

if [[ "${OUTPUT_FILE}" != "-" ]]; then
	if ! printf '%s\n' "${RESULT_JSON}" | publish_output "${OUTPUT_FILE}"; then
		print_status FAIL proof
		exit 1
	fi
else
	printf '%s\n' "${RESULT_JSON}"
fi
if ((PROOF_EXIT != 0)); then
	print_status FAIL proof
	exit 1
fi
print_status PASS complete
