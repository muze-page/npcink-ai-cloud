from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SMOKE_PATH = ROOT / "scripts/media-derivative-wordpress-e2e-smoke.sh"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_b4d_smoke_fails_closed_on_the_npcink_wordpress_site() -> None:
    smoke = SMOKE_PATH.read_text(encoding="utf-8")

    assert "MAGICK_" not in smoke
    for required in (
        "NPCINK_WP_PHP",
        "/php-8.2.29+0/bin/darwin-arm64/bin/php",
        "NPCINK_WP_PATH",
        "/Users/muze/Local Sites/npcink/app/public",
        "NPCINK_WP_MYSQL_SOCKET",
        "/Local/run/PvPC4seEm/mysql/mysqld.sock",
        "NPCINK_WP_EXPECTED_HOME",
        "http://npcink.local/",
        "wordpress_abspath_mismatch",
        "wordpress_home_mismatch",
        "required_plugin_inactive",
        "required_plugin_source_mismatch",
        "required_plugin_source_not_npcink",
        "Docker is required for the Cloud API, worker, and evidence database checks.",
        "Required Cloud container is not running",
        "API_ARTIFACT_MOUNT",
        "WORKER_ARTIFACT_MOUNT",
        "Cloud API and worker must share the same mounted ArtifactStore root",
    ):
        assert required in smoke

    for plugin, file_constant in (
        ("npcink-cloud-addon/npcink-cloud-addon.php", "NPCINK_CLOUD_ADDON_FILE"),
        (
            "npcink-abilities-toolkit/npcink-abilities-toolkit.php",
            "NPCINK_ABILITIES_TOOLKIT_FILE",
        ),
        (
            "npcink-ai-client-adapter/npcink-ai-client-adapter.php",
            "NPCINK_OPENCLAW_ADAPTER_FILE",
        ),
        (
            "npcink-governance-core/npcink-governance-core.php",
            "NPCINK_GOVERNANCE_CORE_FILE",
        ),
        (
            "npcink-workflow-toolbox/npcink-workflow-toolbox.php",
            "NPCINK_TOOLBOX_FILE",
        ),
    ):
        assert plugin in smoke
        assert file_constant in smoke

    identity_check = smoke.index("mde2e_assert_wordpress_identity();")
    stale_cleanup = smoke.index("mde2e_cleanup_stale_smoke_media()", identity_check)
    assert identity_check < stale_cleanup


def test_b4d_smoke_accepts_only_the_addon_projection_of_the_artifact_result() -> None:
    smoke = SMOKE_PATH.read_text(encoding="utf-8")
    routes = _read("app/api/routes/media_derivatives.py")

    for required in (
        'result_json->>\'contract_version\'=\'media_derivative_result.v1\'',
        '$cloud_projection["artifact"]',
        (
            '$expected_result_fields = array("artifact", "created_at", "error", '
            '"job_type", "run_id", "status", "updated_at", "warnings")'
        ),
        (
            '$expected_artifact_fields = array("artifact_id", "artifact_reference", '
            '"checksum", "expires_at", "filename_basis", "filesize_bytes", '
            '"format", "height", "mime_type", "processing_warnings", '
            '"suggested_filename", "width")'
        ),
        '"/^art_[0-9a-f]{32}$/"',
        '"/^sha256:[0-9a-f]{64}$/"',
        'array("http://", "https://", "data:", "storage_key", "base64", "token")',
    ):
        assert required in smoke

    for retired in (
        'cloud_result["derivative"]',
        '"derivative" => array(',
        "preview_url",
        "/v1/runtime/media-derivatives",
        "/v1/runtime/artifacts/",
        "artifact_download_count",
        "/npcink-openclaw-adapter/v1/media-derivative-runs",
        "/npcink-openclaw-adapter/v1/media-derivative-proposal-payload",
    ):
        assert retired not in smoke

    for resource in (
        '@router.post("/media/uploads")',
        '@router.post("/media/jobs")',
        '@router.get("/media/artifacts/{artifact_id}/download")',
        '@router.post("/media/artifacts/{artifact_id}/delivery-ack")',
    ):
        assert resource in routes
    assert '@router.post("/media-derivatives")' not in routes


def test_b4d_smoke_uses_a_real_admin_and_the_exact_local_artifact_seam() -> None:
    smoke = SMOKE_PATH.read_text(encoding="utf-8")

    for required in (
        'get_users(array("role" => "administrator"',
        'current_user_can("manage_options")',
        'current_user_can("upload_files")',
        '"administrator_capability_missing"',
        'npcink_cloud_addon_build_media_derivative_proposal_payload(',
        'npcink_cloud_addon_receive_media_derivative_artifact($local_artifact, $trace_id)',
        (
            '$expected_local_artifact_fields = array("artifact_id", "expires_at", '
            '"filename_basis", "filesize_bytes", "format", "height", "mime_type", '
            '"processing_warnings", "sha256", "suggested_filename", "width")'
        ),
        '!isset($local_artifact["artifact_reference"], $local_artifact["checksum"])',
    ):
        assert required in smoke

    assert "wp_set_current_user(1)" not in smoke
    assert "npcink_cloud_addon_receive_media_derivative_artifact($artifact" not in smoke
    assert '"missing_artifact", $result' not in smoke


def test_b4d_smoke_uses_real_core_sensitive_read_authorization() -> None:
    smoke = SMOKE_PATH.read_text(encoding="utf-8")

    for required in (
        "mde2e_run_governed_read_ability",
        "npcink_openclaw_adapter_core_read_authorization_required",
        '"/npcink-openclaw-adapter/v1/read-requests"',
        '"/npcink-governance-core/v1/read-requests/"',
        '"/approve"',
        '"read_request_id" => $read_request_id',
        '"read_authorization_granted"',
        '"core_authorization_truth"',
        '"npcink_governance_core"',
        '"npcink_governance_core_read_requests"',
        '"cleanup_read_authorization_leak_guard"',
        '"read_authorization_evidence"',
    ):
        assert required in smoke

    assert '"/read-preflight"' not in smoke
    assert '"authorization_required" => false' not in smoke
    assert 'if ($direct["ok"] && 200 === (int) ($direct["status"] ?? 0))' not in smoke


def test_b4d_smoke_allowlists_only_its_ephemeral_setting_fixtures() -> None:
    smoke = SMOKE_PATH.read_text(encoding="utf-8")

    assert "function mde2e_patchable_setting_targets" in smoke
    assert 'array_map("sanitize_key", $created_option_names)' in smoke
    assert 'array_map("sanitize_key", $created_theme_mod_names)' in smoke
    assert (
        'add_filter("npcink_abilities_toolkit_patchable_setting_targets", '
        '"mde2e_patchable_setting_targets", 10, 3);'
    ) in smoke
    assert (
        'remove_filter("npcink_abilities_toolkit_patchable_setting_targets", '
        '"mde2e_patchable_setting_targets", 10);'
    ) in smoke


def test_b4d_smoke_freezes_local_adoption_audit_reference_and_restore_proof() -> None:
    smoke = SMOKE_PATH.read_text(encoding="utf-8")

    for required in (
        "filesize($after_path)",
        'hash_file("sha256", $after_path)',
        "getimagesize($after_path)",
        "wp_get_attachment_metadata($attachment_id)",
        "adopted_file_size_mismatch",
        "adopted_file_checksum_mismatch",
        "adopted_file_image_facts_mismatch",
        "attachment_metadata_facts_mismatch",
        "adopted_file_http_delivery_failed",
        "content_reference_repair_not_applied",
        "page_http_reference_repair_not_visible",
        "settings_reference_repair_not_applied",
        '!isset($adopt_input["file_name"])',
        "proposal.created",
        "proposal.approved",
        "commit.preflighted",
        "proposal.executed",
        "$rollback_rel === $before_rel",
        '"image/png" === get_post_mime_type($attachment_id)',
        "rollback_file_facts_mismatch",
        "npcink_openclaw_adapter_execution_records",
        "npcink_governance_core_audit_log",
        "npcink_governance_core_proposals",
        "cleanup_page_leak_guard",
        "cleanup_option_leak_guard",
        "cleanup_theme_mod_leak_guard",
        "cleanup_governance_leak_guard",
        "cleanup_file_leak_guard",
        "stale_cleanup_file_leak_guard",
        "mde2e_attachment_metadata_relative_files",
        "mde2e_attachment_history_relative_files",
        '"_npcink_ai_cloud_media_derivative_e2e_marker"',
        '"media_derivative_wordpress_e2e_smoke.v1"',
        '"^[0-9]{14}-[0-9a-f]{8}$"',
        '"npcink-media-derivative-e2e-smoke/" . $stamp',
        "RecursiveDirectoryIterator",
    ):
        assert required in smoke

    assert 'NPCINK_MEDIA_DERIVATIVE_E2E_CLEANUP:-1' in smoke
    assert "NPCINK_CLOUD_ARTIFACT_CLEANUP_ENABLED" not in smoke
    assert "p.post_name like" not in smoke
    assert "p.post_title like" not in smoke
    assert 'glob($basedir . "/20[0-9][0-9]/*/"' not in smoke


def test_b4d_smoke_freezes_exact_receive_transfer_and_ack_projections() -> None:
    smoke = SMOKE_PATH.read_text(encoding="utf-8")

    assert (
        '$expected_received_fields = array("artifact_id", "contents", '
        '"delivery_ack", "expires_at", "filesize_bytes", "height", '
        '"mime_type", "sha256", "transfer_evidence", "width")'
    ) in smoke
    assert (
        '$expected_transfer_fields = array("ack_deadline_at", "artifact_id", '
        '"byte_size_verified", "checksum_verified", "content_type_verified", '
        '"contract_version", "delivery_id", "dimensions_verified", '
        '"image_decoded", "received_byte_size", "received_checksum")'
    ) in smoke
    assert (
        '$expected_ack_fields = array("acknowledged_at", '
        '"acknowledgement_scope", "artifact_expires_at", "artifact_id", '
        '"byte_size_verified", "checksum_verified", "contract_version", '
        '"delivery_id", "idempotent_replay", "received_byte_size", '
        '"received_checksum", "status")'
    ) in smoke
    for required in (
        '"media_artifact_verified_transfer.v1"',
        '"media_artifact_delivery_ack.v1"',
        '"verified_transfer_only"',
        'true === ($transfer_evidence["content_type_verified"] ?? null)',
        'true === ($transfer_evidence["image_decoded"] ?? null)',
        'true === ($transfer_evidence["dimensions_verified"] ?? null)',
        'false === ($delivery_ack["idempotent_replay"] ?? null)',
        "$acknowledged_at_ts <= $ack_deadline_at_ts",
        "$ack_expires_at_ts === $cloud_expires_at",
        '$delivery_ack["artifact_expires_at"]',
    ):
        assert required in smoke


def test_b4d_smoke_requires_upload_job_run_usage_and_verified_delivery_evidence() -> None:
    smoke = SMOKE_PATH.read_text(encoding="utf-8")
    delivery = _read("app/domain/media_artifacts/delivery.py")

    for required in (
        "media_upload_request.v1",
        "media_job_request.v1",
        "image.upload.v1",
        "image.transform.v1",
        "media_derivative_job_metrics",
        "media_artifacts",
        "run_records",
        "usage_meter_events",
        "media_artifact_deliveries",
        "started_at is not null",
        "completed_at is not null",
        "acked_at is not null",
        "completed_byte_size=d.expected_byte_size",
        "received_byte_size=d.expected_byte_size",
        "completed_checksum=d.expected_checksum",
        "received_checksum=d.expected_checksum",
        "d.byte_size_verified is true",
        "d.checksum_verified is true",
        "Refusing Cloud SQL with invalid run id",
        "Refusing Cloud SQL with invalid artifact id",
        "Refusing Cloud SQL with invalid receive delivery id",
        "^art_[0-9a-f]{32}$",
        "^mdl_[0-9a-f]{32}$",
        'if [ "${DELIVERY_COUNT}" -lt 2 ]',
        'if [ "${VERIFIED_DELIVERY_COUNT}" != "${DELIVERY_COUNT}" ]',
        'if [ "${RECEIVE_DELIVERY_COUNT}" != "1" ]',
        'd.acked_at <= d.ack_deadline_at',
    ):
        assert required in smoke

    first_sql = smoke.index('psql -U "${POSTGRES_USER}"')
    assert smoke.index("invalid run id") < first_sql
    assert smoke.index("invalid artifact id") < first_sql
    assert smoke.index("invalid receive delivery id") < first_sql
    assert '"acknowledgement_scope": "verified_transfer_only"' in delivery


def test_b4d_docs_state_records_real_wordpress_completion_without_cleanup_enablement() -> None:
    media = _read("docs/media-runtime-boundary-v1.md")
    inventory = _read("docs/refactor-deletion-inventory-v1.md")
    combined = f"{media}\n{inventory}"

    assert "P3-B4D complete with real WordPress and Cloud evidence" in media
    assert "P3-B4D is complete" in media
    assert "B4D completed on 2026-07-16" in inventory
    assert "real WordPress smoke evidence pending" not in combined
    assert "Production cleanup remains disabled" in media
    assert "production cleanup remains default-off" in inventory


def test_media_docs_freeze_ack_expiry_and_pending_b5_closeout() -> None:
    media = _read("docs/media-runtime-boundary-v1.md")
    delivery = _read("docs/cloud-media-delivery-boundary-v1.md")
    ack_adr = _read("docs/decisions/011-signed-pull-media-delivery-ack.md")
    runbook = _read("docs/media-derivative-operations-runbook-v1.md")
    inventory = _read("docs/refactor-deletion-inventory-v1.md")
    closeout = _read("docs/media-runtime-b5-closeout-2026-07-16.md")
    combined = "\n".join((media, delivery, ack_adr, runbook, inventory, closeout))

    assert "without changing the artifact's original `expires_at`" in delivery
    assert "preserve the original server-owned `expires_at`" in media
    assert "Delivery ACK records verified transfer only and does not change" in closeout
    assert "## Current Decision Addendum" in ack_adr
    assert "retention clause amended by B4D" in ack_adr
    assert (
        "without changing the artifact's original `expires_at`"
        in ack_adr.replace("\n", " ")
    )
    assert "superseded by the Current Decision Addendum" in ack_adr
    for retired in (
        "retention shortening",
        "shortens artifact retention",
        "shorten the remaining TTL after delivery acknowledgement",
        "WordPress end-to-end smoke pending connector adoption",
    ):
        assert retired not in combined

    assert "P3-B4D WordPress end-to-end smoke complete" in runbook
    assert "Status: pending evidence; P3-B5 is not complete." in closeout
    assert "not the global P5 refactor milestone" in closeout
    assert "does not authorize enabling production orphan cleanup" in closeout
    for required in (
        "Exact package manifest",
        "Fresh environment E2E",
        "Performance and bounded memory",
        "Security and isolation",
        "Upgrade, rollback, and recovery",
        "No old media aliases",
        "Central cross-repository matrix",
        "Independent review",
    ):
        assert required in closeout
    assert "| pending |" in closeout
