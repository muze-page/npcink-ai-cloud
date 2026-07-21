from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.dev.live_site_addon_install import APPROVAL_TEXT
from app.dev.live_site_preflight import SiteTarget
from app.dev.live_site_stage1 import GuardError, build_stage_report, parse_scopes


def _target() -> SiteTarget:
    return SiteTarget("npcink", "http://npcink.local/", Path("/site/app/public"))


def _stage_kwargs(tmp_path: Path) -> dict[str, object]:
    return {
        "target": _target(),
        "php_bin": "/php",
        "wp_bin": "/wp",
        "addon_zip": Path("/addon.zip"),
        "output_dir": tmp_path,
        "base_url": "http://127.0.0.1:8010",
        "internal_token": "internal-token",
        "account_id": "acct_live",
        "site_id": "site_live",
        "site_name": "Live Site",
        "site_url": "http://npcink.local/",
        "key_label": "Live key",
        "scopes": ["runtime:execute"],
        "timeout_seconds": 1,
    }


def test_parse_scopes_accepts_csv_and_sequence() -> None:
    assert parse_scopes("catalog:read, runtime:execute ,,") == [
        "catalog:read",
        "runtime:execute",
    ]
    assert parse_scopes([" runtime:read ", ""]) == ["runtime:read"]


def test_execute_requires_exact_approval_before_builders_run(tmp_path) -> None:
    calls: list[str] = []

    def addon_builder(**_kwargs: object) -> dict[str, object]:
        calls.append("addon")
        return {"addon_active": True}

    def identity_builder(**_kwargs: object) -> dict[str, object]:
        calls.append("identity")
        return {"secret_file": ""}

    with pytest.raises(GuardError, match="exact approval"):
        build_stage_report(
            **_stage_kwargs(tmp_path),
            execute=True,
            approval_text="同意",
            addon_builder=addon_builder,
            identity_builder=identity_builder,
        )

    assert calls == []


def test_prepare_mode_runs_both_prepare_reports_without_writes(tmp_path) -> None:
    calls: list[tuple[str, bool, str]] = []

    def addon_builder(**kwargs: object) -> dict[str, object]:
        calls.append(("addon", bool(kwargs["execute"]), str(kwargs["approval_text"])))
        return {
            "mode": "prepare",
            "boundary": {"wordpress_writes": False},
            "addon_active": False,
        }

    def identity_builder(**kwargs: object) -> dict[str, object]:
        calls.append(("identity", bool(kwargs["execute"]), str(kwargs["approval_text"])))
        return {
            "mode": "prepare",
            "boundary": {"cloud_identity_provisioning": False},
            "secret_file": "",
        }

    report = build_stage_report(
        **_stage_kwargs(tmp_path),
        execute=False,
        approval_text="",
        addon_builder=addon_builder,
        identity_builder=identity_builder,
    )

    assert calls == [("addon", False, ""), ("identity", False, "")]
    assert report["ok"] is True
    assert report["boundary"]["wordpress_writes"] is False  # type: ignore[index]
    assert report["boundary"]["cloud_identity_provisioning"] is False  # type: ignore[index]
    assert (tmp_path / "stage1-report.json").exists()
    assert (tmp_path / "summary.md").exists()


def test_execute_skips_identity_when_addon_is_not_active(tmp_path) -> None:
    calls: list[str] = []

    def readiness_builder(**_kwargs: object) -> dict[str, object]:
        calls.append("readiness")
        return {
            "mode": "read_only_readiness",
            "ok": True,
            "ready_for_stage1_execute_after_exact_approval": True,
            "all_failures": [],
            "boundary": {
                "wordpress_writes": False,
                "wordpress_option_writes": False,
                "cloud_identity_provisioning": False,
                "public_runtime_provisioning": False,
                "cloud_runtime_execution": False,
                "site_knowledge_sync": False,
                "site_knowledge_search": False,
                "content_writes": False,
                "monitoring_enabled": False,
            },
        }

    def addon_builder(**kwargs: object) -> dict[str, object]:
        calls.append(f"addon:{kwargs['execute']}")
        return {"mode": "execute", "addon_active": False}

    def identity_builder(**_kwargs: object) -> dict[str, object]:
        calls.append("identity")
        return {"secret_file": "/secret.json"}

    report = build_stage_report(
        **_stage_kwargs(tmp_path),
        execute=True,
        approval_text=APPROVAL_TEXT,
        addon_builder=addon_builder,
        identity_builder=identity_builder,
        readiness_builder=readiness_builder,
    )

    assert calls == ["readiness", "addon:True"]
    assert report["ok"] is False
    assert report["boundary"]["cloud_identity_provisioning"] is False  # type: ignore[index]
    assert report["identity_provision"] == {
        "skipped": True,
        "reason": "addon install did not verify active; identity not provisioned",
    }


def test_execute_report_redacts_identity_secret_material(tmp_path) -> None:
    def readiness_builder(**_kwargs: object) -> dict[str, object]:
        return {
            "mode": "read_only_readiness",
            "ok": True,
            "ready_for_stage1_execute_after_exact_approval": True,
            "all_failures": [],
            "boundary": {
                "wordpress_writes": False,
                "wordpress_option_writes": False,
                "cloud_identity_provisioning": False,
                "public_runtime_provisioning": False,
                "cloud_runtime_execution": False,
                "site_knowledge_sync": False,
                "site_knowledge_search": False,
                "content_writes": False,
                "monitoring_enabled": False,
            },
        }

    def addon_builder(**_kwargs: object) -> dict[str, object]:
        return {"mode": "execute", "addon_active": True}

    def identity_builder(**_kwargs: object) -> dict[str, object]:
        return {
            "mode": "execute",
            "secret_file": str(tmp_path / "cloud-api-key.secret.json"),
            "issued_key": {
                "site_id": "site_live",
                "key_id": "key_live",
                "secret": "secret_live",
                "cloud_api_key": "mak1_sensitive",
            },
        }

    report = build_stage_report(
        **_stage_kwargs(tmp_path),
        execute=True,
        approval_text=APPROVAL_TEXT,
        addon_builder=addon_builder,
        identity_builder=identity_builder,
        readiness_builder=readiness_builder,
    )
    encoded = json.dumps(report)

    assert report["ok"] is True
    assert "secret_live" not in encoded
    assert "mak1_sensitive" not in encoded
    assert report["outputs"]["secret_file"].endswith("cloud-api-key.secret.json")  # type: ignore[index]
    assert "secret_live" not in (tmp_path / "stage1-report.json").read_text()


def test_execute_requires_readiness_before_addon_install(tmp_path) -> None:
    calls: list[str] = []

    def readiness_builder(**_kwargs: object) -> dict[str, object]:
        calls.append("readiness")
        return {
            "mode": "read_only_readiness",
            "ok": False,
            "ready_for_stage1_execute_after_exact_approval": False,
            "all_failures": ["cloud: Cloud /health/ready is not ready"],
            "boundary": {
                "wordpress_writes": False,
                "wordpress_option_writes": False,
                "cloud_identity_provisioning": False,
                "public_runtime_provisioning": False,
                "cloud_runtime_execution": False,
                "site_knowledge_sync": False,
                "site_knowledge_search": False,
                "content_writes": False,
                "monitoring_enabled": False,
            },
        }

    def addon_builder(**_kwargs: object) -> dict[str, object]:
        calls.append("addon")
        return {"addon_active": True}

    def identity_builder(**_kwargs: object) -> dict[str, object]:
        calls.append("identity")
        return {"secret_file": "/secret.json"}

    with pytest.raises(GuardError, match="stage 1 readiness failed"):
        build_stage_report(
            **_stage_kwargs(tmp_path),
            execute=True,
            approval_text=APPROVAL_TEXT,
            addon_builder=addon_builder,
            identity_builder=identity_builder,
            readiness_builder=readiness_builder,
        )

    assert calls == ["readiness"]
