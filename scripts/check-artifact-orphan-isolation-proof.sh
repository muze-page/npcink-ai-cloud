#!/usr/bin/env bash
set -euo pipefail

# P3-B4C3 isolated PostgreSQL/named-volume proof gate.

umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.artifact-orphan-proof.yml"
TMP_DIR=""
PROJECT_NAME=""
COMPOSE_PID=""
CLEANUP_DONE=0
CLEANUP_STATUS=0

print_summary() {
	local status="$1"
	local phase="$2"
	local compose_exit="$3"
	case "${status}" in
		PASS | FAIL) ;;
		*) return 1 ;;
	esac
	case "${phase}" in
		complete | preflight | compose | teardown | signal_int | signal_term) ;;
		*) return 1 ;;
	esac
	if [[ ! "${compose_exit}" =~ ^[0-9]{1,3}$ ]]; then
		return 1
	fi
	printf 'P3-B4C3 %s phase=%s compose_exit=%s\n' \
		"${status}" "${phase}" "${compose_exit}"
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
		if ! rm -f "${TMP_DIR}/compose.log" >/dev/null 2>&1; then
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
	local forwarded_signal="$3"
	trap - INT TERM
	if [[ -n "${COMPOSE_PID}" ]]; then
		kill "-${forwarded_signal}" "${COMPOSE_PID}" >/dev/null 2>&1 || true
		wait "${COMPOSE_PID}" >/dev/null 2>&1 || true
		COMPOSE_PID=""
	fi
	cleanup >/dev/null 2>&1 || true
	trap - EXIT
	print_summary FAIL "${phase}" "${exit_code}"
	exit "${exit_code}"
}

trap cleanup EXIT
trap 'handle_signal 130 signal_int INT' INT
trap 'handle_signal 143 signal_term TERM' TERM

if ! command -v docker >/dev/null 2>&1 \
	|| ! command -v python3 >/dev/null 2>&1 \
	|| ! docker info >/dev/null 2>&1 \
	|| ! docker compose version >/dev/null 2>&1; then
	print_summary FAIL preflight 125
	exit 1
fi

if ! TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/npcink-b4c3-proof.XXXXXX")"; then
	print_summary FAIL preflight 125
	exit 1
fi
if ! PROJECT_SUFFIX="$(
	python3 -c 'import secrets; print(secrets.token_hex(12))' 2>/dev/null
)"; then
	print_summary FAIL preflight 125
	exit 1
fi
PROJECT_CANDIDATE="npcink-b4c3-${PROJECT_SUFFIX}"

if [[ ! "${PROJECT_CANDIDATE}" =~ ^[a-z0-9][a-z0-9_-]{0,62}$ ]]; then
	print_summary FAIL preflight 125
	exit 1
fi
PROJECT_NAME="${PROJECT_CANDIDATE}"

docker compose \
	-p "${PROJECT_NAME}" \
	-f "${COMPOSE_FILE}" \
	up --build --abort-on-container-exit --exit-code-from app-a \
	>"${TMP_DIR}/compose.log" 2>&1 &
COMPOSE_PID="$!"
COMPOSE_EXIT=0
if wait "${COMPOSE_PID}"; then
	COMPOSE_EXIT=0
else
	COMPOSE_EXIT="$?"
fi
COMPOSE_PID=""

if ((COMPOSE_EXIT != 0)); then
	cleanup >/dev/null 2>&1 || true
	trap - EXIT
	print_summary FAIL compose "${COMPOSE_EXIT}"
	exit 1
fi

if ! cleanup; then
	trap - EXIT
	print_summary FAIL teardown 0
	exit 1
fi
trap - EXIT
print_summary PASS complete 0
