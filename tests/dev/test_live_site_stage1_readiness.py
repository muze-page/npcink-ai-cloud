from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from app.dev.live_site_addon_install import APPROVAL_TEXT
from app.dev.live_site_addon_package import ADDON_PLUGIN_BASENAME
from app.dev.live_site_preflight import SiteTarget
from app.dev.live_site_stage1_readiness import (
    ALLOWED_PREFLIGHT_BLOCKERS,
    addon_zip_failures,
    build_readiness_report,
    cloud_probe_failures,
    identity_plan_failures,
    next_action,
    preflight_stage1_failures,
    probe_cloud,
)


def _target() -> SiteTarget:
    return SiteTarget("npcink", "http://npcink.local/", Path("/site/app/public"))


def _preflight(*, blockers: list[str] | None = None) -> dict[str, object]:
    return {
        "label": "npcink",
        "url": "http://npcink.local/",
        "path": "/site/app/public",
        "local_site": {
            "matched": True,
            "mysql_socket_exists": True,
            "mysql_socket": "/tmp/mysql.sock",
        },
        "evaluation": {"blockers": blockers if blockers is not None else []},
    }


def _addon_zip(tmp_path: Path) -> Path:
    path = tmp_path / "addon.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr(
            ADDON_PLUGIN_BASENAME,
            """
            <?php
            /**
             * Plugin Name: Npcink Cloud Addon
             * Version: 0.1.0
             */
            """,
        )
    return path


def test_preflight_allows_only_cloud_addon_unverified_blocker() -> None:
    assert ALLOWED_PREFLIGHT_BLOCKERS == {"cloud_addon_unverified"}
    assert preflight_stage1_failures(_preflight(blockers=["cloud_addon_unverified"])) == []

    assert preflight_stage1_failures(
        _preflight(blockers=["wordpress_identity_mismatch", "cloud_addon_unverified"])
    ) == ["unexpected preflight blockers: wordpress_identity_mismatch"]


def test_addon_zip_failures_require_existing_main_plugin(tmp_path: Path) -> None:
    missing = addon_zip_failures({"exists": False, "contains_main_plugin": False})
    assert missing == [
        "addon zip is missing",
        "addon zip does not contain the main plugin file",
    ]

    assert addon_zip_failures({"exists": True, "contains_main_plugin": True}) == []


def test_identity_plan_rejects_trial_site_and_missing_scopes() -> None:
    assert identity_plan_failures(
        account_id="acct_live",
        site_id="site_npcink_trial",
        site_name="Live Site",
        site_url="http://npcink.local/",
        key_label="Live key",
        scopes=[],
    ) == [
        "site_npcink_trial must not be reused for live candidate identity",
        "at least one API key scope is required",
    ]


def test_probe_cloud_uses_live_and_ready_without_exposing_token() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def health_getter(
        url: str, headers: dict[str, str], timeout_seconds: int
    ) -> dict[str, object]:
        calls.append((url, headers))
        return {"ok": True, "status_code": 200, "timeout": timeout_seconds}

    report = probe_cloud(
        base_url="http://127.0.0.1:8010",
        internal_token="internal-token",
        timeout_seconds=2,
        health_getter=health_getter,
    )

    assert report["live"]["ok"] is True  # type: ignore[index]
    assert report["ready"]["ok"] is True  # type: ignore[index]
    assert calls == [
        ("http://127.0.0.1:8010/health/live", {}),
        (
            "http://127.0.0.1:8010/health/ready",
            {"X-Npcink-Internal-Token": "internal-token"},
        ),
    ]
    assert "internal-token" not in json.dumps(report)


def test_cloud_probe_failures_require_live_ready_and_token() -> None:
    assert cloud_probe_failures({"live": {"ok": True}, "ready": {"ok": True}}) == []
    assert cloud_probe_failures(
        {"live": {"ok": False}, "ready": {"ok": False, "skipped": True}}
    ) == [
        "Cloud /health/live is not reachable",
        "Cloud /health/ready was skipped because internal token is missing",
    ]


def test_build_readiness_report_ok_after_prerequisites_without_approval(tmp_path: Path) -> None:
    def site_collector(**_kwargs: object) -> dict[str, object]:
        return _preflight(blockers=["cloud_addon_unverified"])

    def health_getter(
        url: str, headers: dict[str, str], timeout_seconds: int
    ) -> dict[str, object]:
        return {"ok": True, "status_code": 200}

    report = build_readiness_report(
        target=_target(),
        php_bin="/php",
        wp_bin="/wp",
        addon_zip=_addon_zip(tmp_path),
        output_dir=tmp_path / "out",
        base_url="http://127.0.0.1:8010",
        internal_token="internal-token",
        account_id="acct_live",
        site_id="site_live",
        site_name="Live Site",
        site_url="http://npcink.local/",
        key_label="Live key",
        scopes=["runtime:execute"],
        timeout_seconds=1,
        approval_text="",
        site_collector=site_collector,
        health_getter=health_getter,
    )

    assert report["ok"] is True
    assert report["ready_for_stage1_execute_after_exact_approval"] is True
    assert report["approval"]["matched"] is False  # type: ignore[index]
    assert report["next_action"] == {
        "action": "run_stage1_execute_after_exact_approval",
        "approval_text": APPROVAL_TEXT,
    }
    encoded = json.dumps(report)
    assert "internal-token" not in encoded
    assert (tmp_path / "out" / "stage1-readiness-report.json").exists()
    assert (tmp_path / "out" / "summary.md").exists()


def test_build_readiness_report_blocks_when_cloud_ready_fails(tmp_path: Path) -> None:
    def site_collector(**_kwargs: object) -> dict[str, object]:
        return _preflight()

    def health_getter(
        url: str, headers: dict[str, str], timeout_seconds: int
    ) -> dict[str, object]:
        if url.endswith("/health/ready"):
            return {"ok": False, "status_code": 503}
        return {"ok": True, "status_code": 200}

    report = build_readiness_report(
        target=_target(),
        php_bin="/php",
        wp_bin="/wp",
        addon_zip=_addon_zip(tmp_path),
        output_dir=tmp_path / "out",
        base_url="http://127.0.0.1:8010",
        internal_token="internal-token",
        account_id="acct_live",
        site_id="site_live",
        site_name="Live Site",
        site_url="http://npcink.local/",
        key_label="Live key",
        scopes=["runtime:execute"],
        timeout_seconds=1,
        approval_text=APPROVAL_TEXT,
        site_collector=site_collector,
        health_getter=health_getter,
    )

    assert report["ok"] is False
    assert report["failures"]["cloud"] == ["Cloud /health/ready is not ready"]  # type: ignore[index]
    assert report["next_action"] == {
        "action": "fix_readiness_failures_before_stage1_execute",
        "approval_text": "",
    }


def test_next_action_distinguishes_readiness_from_approval() -> None:
    assert next_action(prerequisites_ok=False, approval_matched=False) == {
        "action": "fix_readiness_failures_before_stage1_execute",
        "approval_text": "",
    }
    assert next_action(prerequisites_ok=True, approval_matched=True) == {
        "action": "stage1_execute_prerequisites_ready_and_approval_matched",
        "approval_text": "",
    }
