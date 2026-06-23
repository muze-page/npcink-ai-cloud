from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.dev.live_site_preflight import SiteTarget
from app.dev.live_site_stage1_acceptance import build_acceptance_report, load_json


def _target() -> SiteTarget:
    return SiteTarget("npcink", "http://npcink.local/", Path("/site/app/public"))


def _stage_report(tmp_path: Path, *, mode: str = "execute", ok: bool = True) -> Path:
    secret_file = tmp_path / "identity" / "cloud-api-key.secret.json"
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret_file.write_text('{"cloud_api_key": "mak1_fake"}\n')
    path = tmp_path / "stage1-report.json"
    path.write_text(
        json.dumps(
            {
                "mode": mode,
                "ok": ok,
                "boundary": {
                    "cloud_runtime_execution": False,
                    "runtime_smoke": False,
                    "site_knowledge_sync": False,
                    "site_knowledge_search": False,
                },
                "outputs": {"secret_file": str(secret_file)},
                "identity_provision": {"target": {"site_id": "site_live"}},
            }
        )
        + "\n"
    )
    return path


def _preflight(*, verified: bool = True, site_id: str = "site_live") -> dict[str, object]:
    blockers = [] if verified else ["cloud_addon_unverified"]
    return {
        "overall_decision": "go" if verified else "no-go",
        "sites": [
            {
                "label": "npcink",
                "url": "http://npcink.local/",
                "http": {"ok": True, "status": 200},
                "evaluation": {"decision": "go" if verified else "no-go", "blockers": blockers},
                "wordpress": {
                    "ok": True,
                    "active_plugins": ["npcink-cloud-addon/npcink-cloud-addon.php"],
                    "cloud_settings": {
                        "base_url": "http://127.0.0.1:8010",
                        "site_id": site_id,
                        "key_id_present": True,
                        "secret_present": True,
                        "api_key_present": False,
                        "verified": verified,
                        "verified_at": "2026-06-20T00:00:00+00:00",
                        "monitoring_enabled": False,
                    },
                },
            }
        ],
    }


def test_load_json_rejects_missing_file(tmp_path) -> None:
    with pytest.raises(ValueError, match="could not read JSON"):
        load_json(tmp_path / "missing.json")


def test_acceptance_ready_when_stage1_and_addon_verify(tmp_path) -> None:
    def preflight_builder(**_kwargs: object) -> dict[str, object]:
        return _preflight(verified=True)

    report = build_acceptance_report(
        target=_target(),
        stage_report_path=_stage_report(tmp_path),
        output_dir=tmp_path / "acceptance",
        php_bin="/php",
        wp_bin="/wp",
        timeout_seconds=1,
        min_public_items=10,
        use_local_socket=True,
        preflight_builder=preflight_builder,
    )

    assert report["ready_for_runtime_smoke_approval"] is True
    assert report["boundary"]["cloud_runtime_execution"] is False  # type: ignore[index]
    assert report["boundary"]["site_knowledge_sync"] is False  # type: ignore[index]
    assert not [item for item in report["checks"] if item["ok"] is not True]  # type: ignore[index]
    assert (tmp_path / "acceptance" / "acceptance-report.json").exists()


def test_acceptance_blocks_until_addon_is_verified(tmp_path) -> None:
    def preflight_builder(**_kwargs: object) -> dict[str, object]:
        return _preflight(verified=False)

    report = build_acceptance_report(
        target=_target(),
        stage_report_path=_stage_report(tmp_path),
        output_dir=tmp_path / "acceptance",
        php_bin="/php",
        wp_bin="/wp",
        timeout_seconds=1,
        min_public_items=10,
        use_local_socket=True,
        preflight_builder=preflight_builder,
    )

    failed = {item["name"] for item in report["checks"] if item["ok"] is not True}  # type: ignore[index]
    assert report["ready_for_runtime_smoke_approval"] is False
    assert "preflight_overall_go" in failed
    assert "preflight_no_blockers" in failed
    assert "cloud_addon_verified" in failed


def test_acceptance_checks_stage_identity_matches_addon_settings(tmp_path) -> None:
    def preflight_builder(**_kwargs: object) -> dict[str, object]:
        return _preflight(verified=True, site_id="site_other")

    report = build_acceptance_report(
        target=_target(),
        stage_report_path=_stage_report(tmp_path),
        output_dir=tmp_path / "acceptance",
        php_bin="/php",
        wp_bin="/wp",
        timeout_seconds=1,
        min_public_items=10,
        use_local_socket=True,
        preflight_builder=preflight_builder,
    )

    failed = {item["name"] for item in report["checks"] if item["ok"] is not True}  # type: ignore[index]
    assert report["ready_for_runtime_smoke_approval"] is False
    assert "cloud_site_id_matches_stage1_identity" in failed
