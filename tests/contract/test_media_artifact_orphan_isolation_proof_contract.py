"""Static contract for the isolated P3-B4C3 proof gate."""

from __future__ import annotations

import json
import re
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.artifact-orphan-proof.yml"
GATE = ROOT / "scripts/check-artifact-orphan-isolation-proof.sh"
HARNESS = ROOT / "tests/proof/test_media_artifact_orphan_isolation_proof.py"
ADR = ROOT / "docs/decisions/015-persistent-fenced-media-artifact-orphan-cleanup.md"
RUNBOOK = ROOT / "docs/media-derivative-operations-runbook-v1.md"
DOCKERIGNORE = ROOT / ".dockerignore"


def test_isolated_proof_topology_and_default_off_boundary() -> None:
    compose = COMPOSE.read_text()
    dockerignore = DOCKERIGNORE.read_text()
    production_compose = (ROOT / "docker-compose.prod.yml").read_text()
    config = (ROOT / "app/core/config.py").read_text()

    assert "image: postgres:16-alpine" in compose
    assert compose.count("image:") == 1
    assert re.search(r"(?m)^  app-a:$", compose)
    assert re.search(r"(?m)^  app-b:$", compose)
    assert "container_name:" not in compose
    assert "name:" not in compose
    assert "env_file:" not in compose
    assert "secrets:" not in compose
    assert "- .:/app" not in compose
    assert "- ./tests/proof:/app/tests/proof:ro" in compose
    assert compose.count("artifact-proof:/var/lib/npcink-ai-cloud/artifacts") == 1
    assert "- artifact-proof:/var/lib/npcink-ai-cloud/artifacts" in compose
    assert re.search(r"(?m)^volumes:\n  artifact-proof:$", compose)
    assert 'NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_ENABLED: "true"' in compose
    for ignored in (".env", ".env.*", "!.env.example", ".deploy-secrets"):
        assert ignored in dockerignore
    assert "artifact_orphan_cleanup_enabled: bool = Field(default=False)" in config
    assert "NPCINK_CLOUD_ARTIFACT_ORPHAN_CLEANUP_ENABLED:-false" in production_compose


def test_gate_owns_one_random_strict_project_and_redacts_output() -> None:
    gate = GATE.read_text()

    assert GATE.stat().st_mode & stat.S_IXUSR
    assert gate.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert "secrets.token_hex(12)" in gate
    assert "^[a-z0-9][a-z0-9_-]{0,62}$" in gate
    assert gate.count('-p "${PROJECT_NAME}"') == 2
    assert "trap cleanup EXIT" in gate
    assert "handle_signal 130 signal_int INT" in gate
    assert "handle_signal 143 signal_term TERM" in gate
    assert 'kill "-${forwarded_signal}" "${COMPOSE_PID}"' in gate
    assert "CLEANUP_DONE=0" in gate
    assert "down --volumes --remove-orphans --rmi local" in gate
    assert "--rmi all" not in gate
    assert "docker volume prune" not in gate
    assert "COMPOSE_PROJECT_NAME=" not in gate
    assert "sleep " not in gate
    assert "set -x" not in gate
    assert "compose.log" in gate
    assert gate.count('${TMP_DIR}/compose.log') == 2
    assert "cat " not in gate
    assert "grep " not in gate
    assert "tail " not in gate
    assert "P3-B4C3 %s phase=%s compose_exit=%s" in gate
    assert "print_summary PASS complete 0" in gate
    assert "print_summary FAIL teardown 0" in gate
    assert gate.index("if ! cleanup; then") < gate.index("print_summary PASS complete 0")


def test_package_entry_is_dedicated_and_fast_gate_never_starts_proof() -> None:
    package = json.loads((ROOT / "package.json").read_text())
    scripts = package["scripts"]

    assert scripts["check:artifact-orphan-isolation-proof"] == (
        "bash scripts/check-artifact-orphan-isolation-proof.sh"
    )
    assert "artifact-orphan-isolation-proof" not in scripts["check:fast"]
    assert "docker-compose.artifact-orphan-proof.yml" not in scripts["check:fast"]


def test_harness_and_docs_freeze_the_proof_scope() -> None:
    harness = HARNESS.read_text()
    documentation = ADR.read_text() + RUNBOOK.read_text()
    normalized_documentation = " ".join(documentation.split())
    claim_fixture = harness[
        harness.index("def _prepare_claim_case") : harness.index("def _run_claim_race")
    ]

    assert "MIGRATION_HEAD = \"20260716_0066\"" in harness
    assert "SAFETY_WINDOW_SECONDS = 3600" in harness
    assert 'server_version_num // 10000 == 16' in harness
    assert 'cleanup_enabled=False' in harness
    assert 'cleanup_enabled=True' in harness
    assert "time.sleep" not in harness
    assert "pg_sleep" in harness
    assert 'event.listen(production_engine, "before_cursor_execute"' in harness
    assert 'event.remove(production_engine, "before_cursor_execute"' in harness
    assert "production_engine = get_engine(DATABASE_URL)" in harness
    assert "engine = create_engine(DATABASE_URL, pool_pre_ping=True)" in harness
    assert 'phase = f"{case}_sql_ready"' in harness
    assert "if reached or not matcher(statement):" in harness
    assert "sync.record(phase, ROLE)" in harness
    assert "sync.wait_count(phase, 2)" in harness
    assert "assert reached" in harness
    assert 'case="active"' in harness
    assert "matcher=_matches_pass_insert" in harness
    assert "matcher=_matches_claim_update" in harness
    assert 'normalized.startswith("insert into media_artifact_reconciliation_passes ")' in harness
    assert 'normalized.startswith("update media_artifact_orphan_candidates set ")' in harness
    assert claim_fixture.index("MediaArtifactReconciliationPass(") < claim_fixture.index(
        "session.flush()"
    )
    assert claim_fixture.index("session.flush()") < claim_fixture.index(
        "MediaArtifactOrphanCandidate("
    )
    assert "does not enable production cleanup" in documentation
    assert "pnpm run check:artifact-orphan-isolation-proof" in documentation
    assert (
        "bounded `PASS`/`FAIL` summary containing only a fixed phase and numeric "
        "Compose exit code (never keys, paths, tokens, claim identifiers, SQL, or "
        "exception text)"
        in normalized_documentation
    )
    role_a_start = harness.index(
        'if ROLE == "a":\n                _run_two_pass_named_volume_proof()'
    )
    role_a = harness[role_a_start:]
    assert role_a.index('sync.signal("proof_complete")') < role_a.index(
        'sync.wait_count("proof_complete_observed", 1)'
    )
    assert 'sync.record("proof_complete_observed", ROLE)' in role_a
