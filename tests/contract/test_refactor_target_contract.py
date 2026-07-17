from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


TARGET_CONTRACTS = (
    "docs/refactor-master-plan-v1.md",
    "docs/decisions/004-wordpress-first-cloud-runtime-refactor.md",
    "docs/multi-platform-connector-boundary-v1.md",
    "docs/media-runtime-boundary-v1.md",
    "docs/refactor-deletion-inventory-v1.md",
)

BASELINE_EVIDENCE = "docs/refactor-baseline-2026-07-14.md"

BASELINE_RAW_SEARCH_COUNTS = {
    "DEBT-P1-SITE-01": 99,
    "DEBT-P1-CONTRACT-01": 17,
    "DEBT-P3-BLOB-01": 20,
    "DEBT-P3-BASE64-01": 4,
    "DEBT-P3-TOKEN-01": 22,
}


def test_readme_links_all_accepted_target_contracts() -> None:
    readme = _read("README.md")

    assert "## Target Refactor Contracts" in readme
    assert "accepted target contracts for the P0-P5 refactor" in readme
    assert "not evidence" in readme
    assert "implementation is complete" in readme
    assert "WordPress-first through P5" in readme
    assert "other CMS adapters are post-P5 validation work" in readme

    for path in TARGET_CONTRACTS:
        assert (ROOT / path).is_file()
        assert path in readme


def test_readme_links_pre_refactor_baseline_evidence() -> None:
    readme = _read("README.md")
    target_section = readme.split("## Target Refactor Contracts", maxsplit=1)[1]
    target_section = target_section.split("\n## ", maxsplit=1)[0]

    assert (ROOT / BASELINE_EVIDENCE).is_file()
    assert BASELINE_EVIDENCE in target_section
    assert "Baseline evidence (not target-contract completion proof)" in target_section


def test_pre_refactor_baseline_locks_stable_evidence_markers() -> None:
    baseline = _read(BASELINE_EVIDENCE)

    for required in (
        "Pre-refactor local baseline; not a production benchmark",
        "16cf860f",
        "45 passed",
        "50 passed",
        "80 passed",
        "233 passed",
        "bounded-memory",
    ):
        assert required in baseline

    for marker, count in BASELINE_RAW_SEARCH_COUNTS.items():
        assert f"| `{marker}` | `{count}` |" in baseline


def test_master_plan_freezes_the_wordpress_first_p0_p5_sequence() -> None:
    master = _read("docs/refactor-master-plan-v1.md")

    for phase_heading in (
        "### P0 — Target Contracts And Baseline",
        "### P1 — Identity, Site, And Runtime Foundation",
        "### P2 — WordPress Text Runtime Loop",
        "### P3 — Media Runtime",
        "### P4 — Portal And Admin Contraction",
        "### P5 — Hardening, Matrix, And Release Closure",
    ):
        assert phase_heading in master

    for required in (
        "`WORDPRESS_FIRST`",
        "During P0-P5",
        "`NO_COMPATIBILITY_LAYER`",
        "## Post-P5 Validation — Typecho PoC",
        "thin Typecho adapter",
        "cross-platform connector and Media Runtime target contracts",
        "current API/schema/module deletion inventory",
    ):
        assert required in master


def test_wordpress_first_adr_freezes_the_refactor_decisions() -> None:
    adr = _read("docs/decisions/004-wordpress-first-cloud-runtime-refactor.md")

    for marker in (
        "WORDPRESS_FIRST",
        "PLATFORM_CHANNEL_ORTHOGONAL",
        "LOCAL_CONTROL_PLANE",
        "NO_COMPATIBILITY_LAYER",
        "ONE_ACTIVE_CONTRACT_VERSION",
        "NO_FULL_REWRITE",
    ):
        assert marker in adr

    assert "WordPress/Core remains the local control plane" in adr


def test_connector_contract_freezes_one_suggestion_only_runtime() -> None:
    connector = _read("docs/multi-platform-connector-boundary-v1.md")

    for required in (
        "WORDPRESS_ONLY_NOW",
        "PLATFORM_CHANNEL_ORTHOGONAL",
        "LOCAL_CAPABILITY_TRUTH",
        "ONE_CLOUD_RUNTIME",
        "SUGGESTION_ONLY",
        "platform_kind=wordpress",
        "site_url",
        "object_revision",
        "npcink-ai-client-adapter",
        "## Post-P5 Typecho PoC Acceptance",
    ):
        assert required in connector


def test_media_contract_tracks_p3_b4d_real_completion_and_remaining_b5_work() -> None:
    media = _read("docs/media-runtime-boundary-v1.md")

    for required in (
        "Status: P3-B4D complete with real WordPress and Cloud evidence (2026-07-16).",
        "P3-B4C1a routes all",
        "full eligibility `UPDATE` compare-and-set",
        "media_artifact.delivery_window_unavailable",
        "P3-B4C2a instead uses a bounded artifact-store inventory versus",
        "P3-B4C2b persistent",
        "P3-B4C3 separately proves PostgreSQL major 16",
        "P3-B4D is complete",
        "Complete on 2026-07-16.",
        "Session-local in-memory no-delete quarantine",
        "automatic cleanup remains configuration-disabled by default",
        "B4B2 legacy-route",
        "B4B2 removes the legacy routes, token helpers",
        "Summary v2 reports started, stream-completed",
        "P3-B3A atomically replaces that pre-GA public POST route with two resources",
        "P3-B3B1 atomically replaces provider-media image-generation results",
        "P3-B3B2 atomically replaces URL/data-URL WordPress alt-text vision input",
        "metadata-only `MediaArtifact`",
        "exact same sealed temporary file",
        "two disk I/O passes",
        "TEMPORARY_MEDIA_RUNTIME",
        "STREAMED_MEDIA_BYTES",
        "NO_DATABASE_BLOB",
        "SIGNED_PULL",
        "LOCAL_MEDIA_WRITE",
        "POST /v1/runtime/media/uploads",
        "POST /v1/runtime/media/jobs",
        "`image_generation_result.v1` contains artifact references",
        "image.generate.v1",
        "GET /v1/runtime/media/artifacts/{artifact_id}/download",
        "POST /v1/runtime/media/artifacts/{artifact_id}/delivery-ack",
        "independent `MediaArtifactDelivery` evidence",
        "`public_pull_*` replay/rate/rejection scopes",
        "## 7. ArtifactStore Boundary",
        "delivery acknowledgement is never proof of local application",
    ):
        assert required in media

    normalized_media = " ".join(media.split())
    assert "P3-B4C3 PostgreSQL real-concurrency and PG16 migration validation" not in (
        normalized_media
    )
    for required in (
        "run-result reads",
        "initial, transient, and idempotent execution responses",
        "delayed terminal callback payloads",
        "The durable creation-time snapshot is never rewritten by projection.",
        "`media_upload_artifact` / `media_upload_result.v1`",
        "`media_derivative_artifact` / `media_derivative_result.v1`",
        "`image_generation_artifacts` / `image_generation_result.v1`",
        "`audio_generation_candidates` / `audio_generation_result.v1`",
    ):
        assert required in normalized_media

    inventory_adr = " ".join(
        _read(
            "docs/decisions/014-read-only-media-artifact-inventory-reconciliation.md"
        ).split()
    )
    for required in (
        "P3-B4C2b is subsequently implemented by ADR-015",
        "ArtifactInventoryStore",
        "ArtifactPublicationFenceStore",
        "one pass is never deletion authority",
        "C2a does not acquire the exclusive deletion fence",
        "two complete, durable inventory passes",
        "fd-relative conditional unlink",
    ):
        assert required in inventory_adr

    cleanup_adr = " ".join(
        _read(
            "docs/decisions/015-persistent-fenced-media-artifact-orphan-cleanup.md"
        ).split()
    )
    for required in (
        "P3-B4C3 isolated PostgreSQL 16, multi-connection, and named-volume proof implemented",
        "Runtime and deployment configuration default cleanup to disabled",
        "cleanup_candidates_eligible",
        "one non-blocking exclusive session per candidate",
        "any current or future `MediaArtifact.status`",
        "deepest existing pinned directory",
        "POSIX advisory locking",
        "Passing this proof does not enable production cleanup",
    ):
        assert required in cleanup_adr
    assert "P3-B4C3 must prove PostgreSQL 16 multi-connection claims" not in cleanup_adr


def test_image_generation_artifact_adr_freezes_provider_and_cms_boundaries() -> None:
    adr = _read("docs/decisions/008-artifact-only-image-generation-results.md")

    for required in (
        "ProviderMediaCandidate",
        "image_output_hosts",
        "image.generate.v1",
        "suggestion_only=true",
        "requires_local_review=true",
        "storage_mode=no_store",
        "process crash or genuinely uncertain",
        "continues to own download verification",
    ):
        assert required in adr


def test_alt_text_artifact_input_adr_freezes_provider_and_cms_boundaries() -> None:
    adr = _read("docs/decisions/009-artifact-referenced-alt-text-vision-input.md")

    for required in (
        "`source_artifact_id`",
        "accepts only the canonical fields",
        "non-Boolean integer from 1 through 96",
        "fail before run creation",
        "recursively rejects",
        "Idempotent execute replay is checked before current source admission",
        "Immediately before a real provider execution",
        "transient data URL",
        "must not enter `run_records.input_json`",
        "canonical message at",
        "strict text-only projection",
        "nested successful-response",
        "WordPress owns",
    ):
        assert required in adr


def test_deletion_inventory_freezes_items_and_phase_exit_proof() -> None:
    inventory = _read("docs/refactor-deletion-inventory-v1.md")

    for item_id in (
        "IDN-01",
        "CON-01",
        "RUN-01",
        "RUN-02",
        "RUN-03",
        "RUN-04",
        "MED-01",
        "MED-02",
        "MED-03",
        "MED-04",
        "PORT-01",
        "ADM-01",
    ):
        assert item_id in inventory

    assert "NO_COMPATIBILITY_LAYER" in inventory
    assert "## Phase Exit Proof" in inventory
    assert "P3-B4C3 completes the isolated PostgreSQL 16 multi-connection" in inventory
    assert "production default-off" in inventory
    assert "B4D completed on 2026-07-16" in inventory
    assert "real WordPress smoke evidence pending" not in inventory
    assert "P3-B4D completes" in inventory
    assert "C3 PostgreSQL real-concurrency/PG16 migration validation" not in inventory


def test_active_connector_docs_match_the_p1_runtime_contract() -> None:
    ai_task = _read("docs/ai-task-runtime-contract-v1.md")
    alt_text = _read("docs/wordpress-ai-alt-text-vision-contract-feasibility-v1.md")
    smoke = _read("docs/production-wordpress-ai-connector-smoke-runbook-v1.md")
    smoke_builder = _read("app/dev/production_wordpress_ai_connector_smoke.py")

    for required in (
        "Status: active; aligned with the P1 connector reset.",
        "`ai_task_contract.v1`",
        "`wordpress_operation.v1`",
        "`cloud_connector_runtime.v1`",
        "`npcink-cloud/connector-runtime`",
        "`cloud_connector_result.v1`",
        "There is one active connector envelope.",
    ):
        assert required in ai_task

    for required in (
        "Status: Cloud artifact-referenced runtime implemented; addon upload handoff,",
        "real-attachment advertisement, and smoke pending.",
        "`npcink-cloud/connector-runtime`",
        "`cloud_connector_runtime.v1`",
        "`wordpress_operation.v1`",
        "`wp-ai.alt-text-vision`",
        "`cloud_connector_result.v1`",
        "`source_artifact_id`",
        "There is no compatibility request shape.",
        "private provider-preparation edge",
        "must not be cited as cross-repository or production closeout",
    ):
        assert required in alt_text

    for required in (
        "Status: active.",
        "P1-E05 status: operator-only pending.",
        "P1-E06 status: operator-only pending.",
        "ability_name=npcink-cloud/connector-runtime",
        "contract_version=cloud_connector_runtime.v1",
        "channel=editor",
        "profile_id=wp-ai.short-text",
        "`operation_contract.request.source_text`",
        "`request.prompt` is absent",
        "provider_id=<production text provider>",
        "model_id=<production text model>",
        "instance_id=<production text instance>",
        "provider_call_count>=1",
        "idempotent_replay=false",
        "error_code=<empty>",
        "error_stage=<empty>",
        "result.contract_version=cloud_connector_result.v1",
        "title_execute.operation_contract_version=wordpress_operation.v1",
        "result.operation_contract.contract_version=wordpress_operation.v1",
        "Do not mark P1-E05 complete from local pytest output.",
    ):
        assert required in smoke

    superseded_connector_markers = (
        "wp_ai_connector_runtime.v1",
        "wp_ai_connector_result.v1",
        "validate_wordpress_ai_connector_runtime_contract",
    )
    for document in (ai_task, alt_text):
        assert not any(marker in document for marker in superseded_connector_markers)

    title_section = smoke.split("## Title Execute Smoke", maxsplit=1)[1]
    title_section = title_section.split("## Local Test Gate", maxsplit=1)[0]
    for marker in (
        "ability_name=npcink-cloud/wp-ai-connector",
        "contract_version=wp_ai_connector_runtime.v1",
        "channel=wordpress_ai_connector",
        "selected_model_id=",
        "selected_instance_id=",
    ):
        assert marker not in title_section

    title_builder = smoke_builder.split(
        "def build_title_execute_payload", maxsplit=1
    )[1].split("def build_image_resolve_payload", maxsplit=1)[0]
    assert '"source_text"' in title_builder
    for marker in ('"prompt"', '"post_title"', '"post_excerpt"'):
        assert marker not in title_builder

    title_check = smoke_builder.split(
        "def _build_title_execute_check", maxsplit=1
    )[1].split("def _summarize_runtime_response", maxsplit=1)[0]
    for marker in (
        '"run_id"',
        '"trace_id"',
        '"provider_id"',
        '"model_id"',
        '"instance_id"',
        '"provider_call_count"',
        '"idempotent_replay"',
        '"error_code"',
        '"error_stage"',
        '"suggestion_only"',
        '"operation_contract_version"',
        '"wordpress_operation.v1"',
        '"output_text"',
    ):
        assert marker in title_check
    for marker in (
        "selected_provider_id",
        "selected_model_id",
        "selected_instance_id",
    ):
        assert marker not in title_check
