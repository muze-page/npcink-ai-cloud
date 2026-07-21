from __future__ import annotations

import json
from pathlib import Path

from app.dev.live_site_save_verify_handoff import build_handoff_report


def _stage_report(
    tmp_path: Path,
    *,
    mode: str = "execute",
    ok: bool = True,
    secret_payload: dict[str, object] | None = None,
    secret_file_override: str | None = None,
) -> Path:
    secret_file = tmp_path / "identity" / "cloud-api-key.secret.json"
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    if secret_payload is None:
        secret_payload = {
            "site_id": "site_live",
            "key_id": "key_live",
            "secret": "secret_live",
            "cloud_api_key": "mak1_sensitive_customer_key",
        }
    secret_file.write_text(json.dumps(secret_payload) + "\n")
    path = tmp_path / "stage1-report.json"
    path.write_text(
        json.dumps(
            {
                "mode": mode,
                "ok": ok,
                "target": {
                    "label": "npcink",
                    "url": "http://npcink.local/",
                    "path": "/site/app/public",
                },
                "boundary": {
                    "wordpress_option_writes": False,
                    "public_runtime_provisioning": False,
                    "cloud_runtime_execution": False,
                    "runtime_smoke": False,
                    "site_knowledge_sync": False,
                    "site_knowledge_search": False,
                    "content_writes": False,
                    "monitoring_enabled": False,
                },
                "outputs": {
                    "secret_file": (
                        str(secret_file)
                        if secret_file_override is None
                        else secret_file_override
                    )
                },
                "identity_provision": {
                    "target": {
                        "base_url": "http://127.0.0.1:8010",
                        "account_id": "acct_live",
                        "site_id": "site_live",
                        "site_name": "Npcink Local Live",
                        "site_url": "http://npcink.local/",
                        "scopes": ["runtime:resolve", "runtime:execute"],
                    }
                },
                "addon_ready_for_manual_verify": True,
                "identity_ready_for_manual_verify": True,
            }
        )
        + "\n"
    )
    return path


def test_handoff_ready_and_redacts_key_material(tmp_path: Path) -> None:
    report = build_handoff_report(
        stage_report_path=_stage_report(tmp_path),
        output_dir=tmp_path / "handoff",
    )
    encoded = json.dumps(report)
    summary = (tmp_path / "handoff" / "summary.md").read_text()

    assert report["ready_for_manual_save_verify"] is True
    assert report["admin"]["addon_admin_url"] == (  # type: ignore[index]
        "http://npcink.local/wp-admin/admin.php?page=npcink-cloud-addon"
    )
    assert report["admin"]["base_url_to_paste"] == "http://127.0.0.1:8010"  # type: ignore[index]
    assert report["secret_file"]["cloud_api_key_present"] is True  # type: ignore[index]
    assert report["secret_file"]["cloud_api_key_length"] == len(  # type: ignore[index]
        "mak1_sensitive_customer_key"
    )
    assert "mak1_sensitive_customer_key" not in encoded
    assert "secret_live" not in encoded
    assert "mak1_sensitive_customer_key" not in summary
    assert "secret_live" not in summary
    assert (tmp_path / "handoff" / "save-verify-handoff-report.json").exists()


def test_handoff_blocks_when_stage_was_not_execute(tmp_path: Path) -> None:
    report = build_handoff_report(
        stage_report_path=_stage_report(tmp_path, mode="prepare"),
        output_dir=tmp_path / "handoff",
    )

    assert report["ready_for_manual_save_verify"] is False
    assert "stage report mode is not execute: 'prepare'" in report["failures"]


def test_handoff_blocks_when_stage_report_is_not_ok(tmp_path: Path) -> None:
    report = build_handoff_report(
        stage_report_path=_stage_report(tmp_path, ok=False),
        output_dir=tmp_path / "handoff",
    )

    assert report["ready_for_manual_save_verify"] is False
    assert "stage report ok is not true" in report["failures"]


def test_handoff_blocks_when_secret_file_missing(tmp_path: Path) -> None:
    stage_report = _stage_report(tmp_path)
    secret_file = tmp_path / "identity" / "cloud-api-key.secret.json"
    secret_file.unlink()

    report = build_handoff_report(
        stage_report_path=stage_report,
        output_dir=tmp_path / "handoff",
    )

    assert report["ready_for_manual_save_verify"] is False
    assert f"secret file does not exist: {secret_file}" in report["failures"]
    assert report["secret_file"]["exists"] is False  # type: ignore[index]


def test_handoff_blocks_when_secret_file_path_is_empty(tmp_path: Path) -> None:
    report = build_handoff_report(
        stage_report_path=_stage_report(tmp_path, secret_file_override=""),
        output_dir=tmp_path / "handoff",
    )

    assert report["ready_for_manual_save_verify"] is False
    assert "stage report outputs.secret_file is empty" in report["failures"]
    assert report["secret_file"]["path"] == ""  # type: ignore[index]


def test_handoff_blocks_when_cloud_api_key_missing(tmp_path: Path) -> None:
    report = build_handoff_report(
        stage_report_path=_stage_report(
            tmp_path,
            secret_payload={
                "site_id": "site_live",
                "key_id": "key_live",
                "secret": "secret_live",
            },
        ),
        output_dir=tmp_path / "handoff",
    )

    assert report["ready_for_manual_save_verify"] is False
    assert "secret file missing cloud_api_key" in report["failures"]
    assert report["secret_file"]["cloud_api_key_present"] is False  # type: ignore[index]


def test_handoff_boundary_stays_read_only(tmp_path: Path) -> None:
    report = build_handoff_report(
        stage_report_path=_stage_report(tmp_path),
        output_dir=tmp_path / "handoff",
    )

    assert report["boundary"] == {
        "wordpress_writes": False,
        "wordpress_option_writes": False,
        "cloud_identity_provisioning": False,
        "public_runtime_provisioning": False,
        "cloud_runtime_execution": False,
        "runtime_smoke": False,
        "site_knowledge_sync": False,
        "site_knowledge_search": False,
        "content_writes": False,
        "monitoring_enabled": False,
    }
