from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.dev.live_site_addon_package import ADDON_OPTION_NAME
from app.dev.live_site_addon_rollback import (
    APPROVAL_TEXT,
    GuardError,
    addon_settings_were_empty,
    addon_was_active_before,
    approval_matches,
    build_rollback_report,
    deactivate_command,
    normalize_approval,
    option_delete_command,
    option_snapshot_command,
    validate_snapshot,
)
from app.dev.live_site_preflight import SiteTarget


def _target() -> SiteTarget:
    return SiteTarget("npcink", "http://npcink.local/", Path("/site/app/public"))


def _snapshot(
    *, active: bool = False, settings: dict[str, object] | None = None
) -> dict[str, object]:
    return {
        "target": {
            "label": "npcink",
            "url": "http://npcink.local/",
            "path": "/site/app/public",
        },
        "preflight": {
            "local_site": {
                "matched": True,
                "mysql_socket_exists": True,
                "mysql_socket": "/tmp/mysql.sock",
            },
        },
        "active_plugins": {
            "ok": True,
            "payload": [
                {
                    "name": "npcink-cloud-addon",
                    "status": "active" if active else "inactive",
                    "version": "0.1.0",
                }
            ],
        },
        "addon_settings_snapshot": settings
        if settings is not None
        else {
            "base_url": "",
            "site_id": "",
            "key_id_present": False,
            "secret_present": False,
            "api_key_present": False,
            "verified": False,
            "verified_at": "",
            "monitoring_enabled": False,
        },
    }


def _write_snapshot(tmp_path: Path, snapshot: dict[str, object]) -> Path:
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot))
    return path


def test_rollback_approval_matches_expected_text_with_whitespace_normalization() -> None:
    wrapped = APPROVAL_TEXT.replace("，", "，\n")

    assert approval_matches(wrapped) is True
    assert normalize_approval(" a\n b\tc ") == "abc"
    assert approval_matches("同意") is False


def test_snapshot_assessment_allows_only_empty_settings_for_option_delete() -> None:
    empty = _snapshot()
    configured = _snapshot(
        settings={
            "base_url": "http://127.0.0.1:8010",
            "site_id": "site_live",
            "key_id_present": True,
            "secret_present": True,
            "api_key_present": False,
            "verified": True,
            "verified_at": "2026-06-20T00:00:00Z",
            "monitoring_enabled": False,
        }
    )

    assert addon_settings_were_empty(empty) is True
    assert addon_settings_were_empty(configured) is False
    assert addon_was_active_before(_snapshot(active=True)) is True
    assert addon_was_active_before(_snapshot(active=False)) is False


def test_validate_snapshot_rejects_wrong_target_or_unverified_socket() -> None:
    snapshot = _snapshot()

    assert validate_snapshot(snapshot, target=_target()) == []

    snapshot["target"]["url"] = "http://dbd.local/"  # type: ignore[index]
    snapshot["preflight"]["local_site"]["mysql_socket_exists"] = False  # type: ignore[index]

    assert validate_snapshot(snapshot, target=_target()) == [
        "snapshot target URL does not match rollback target",
        "snapshot MySQL socket was not verified",
    ]


def test_wp_commands_target_addon_slug_and_option_name() -> None:
    deactivate = deactivate_command(
        target=_target(),
        php_bin="/php",
        wp_bin="/wp",
        mysql_socket="/tmp/mysql.sock",
    )
    option_delete = option_delete_command(
        target=_target(),
        php_bin="/php",
        wp_bin="/wp",
        mysql_socket="/tmp/mysql.sock",
    )
    option_snapshot = option_snapshot_command(
        target=_target(),
        php_bin="/php",
        wp_bin="/wp",
        mysql_socket="/tmp/mysql.sock",
    )

    assert deactivate[-3:] == ["plugin", "deactivate", "npcink-cloud-addon"]
    assert option_delete[-3:] == ["option", "delete", ADDON_OPTION_NAME]
    assert option_snapshot[-2] == "eval"
    assert "secret_present" in option_snapshot[-1]
    assert "--path=/site/app/public" in deactivate
    assert "--url=http://npcink.local/" in deactivate


def test_prepare_report_does_not_run_writes(tmp_path: Path) -> None:
    calls: list[str] = []

    def command_runner(*_args: object, **_kwargs: object) -> dict[str, object]:
        calls.append("command")
        return {"ok": True}

    def json_runner(*_args: object, **_kwargs: object) -> tuple[dict[str, object], str]:
        calls.append("json")
        return {"ok": True, "payload": []}, "[]"

    report = build_rollback_report(
        target=_target(),
        php_bin="/php",
        wp_bin="/wp",
        snapshot_path=_write_snapshot(tmp_path, _snapshot()),
        output_dir=tmp_path / "out",
        timeout_seconds=1,
        execute=False,
        approval_text="",
        command_runner=command_runner,
        json_runner=json_runner,
    )

    assert calls == []
    assert report["ok"] is True
    assert report["boundary"]["wordpress_writes"] is False  # type: ignore[index]
    assert report["boundary"]["planned_wordpress_write_scope"] == [  # type: ignore[index]
        "plugin_deactivate",
        "option_delete",
    ]
    assert (tmp_path / "out" / "rollback-report.json").exists()
    assert (tmp_path / "out" / "summary.md").exists()


def test_execute_requires_exact_approval_before_runner_is_called(tmp_path: Path) -> None:
    calls: list[str] = []

    def command_runner(*_args: object, **_kwargs: object) -> dict[str, object]:
        calls.append("command")
        return {"ok": True}

    with pytest.raises(GuardError, match="exact approval"):
        build_rollback_report(
            target=_target(),
            php_bin="/php",
            wp_bin="/wp",
            snapshot_path=_write_snapshot(tmp_path, _snapshot()),
            output_dir=tmp_path / "out",
            timeout_seconds=1,
            execute=True,
            approval_text="同意",
            command_runner=command_runner,
        )

    assert calls == []


def test_execute_deactivates_and_deletes_option_when_snapshot_was_empty(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def command_runner(command: list[str], *, timeout_seconds: int) -> dict[str, object]:
        calls.append(command)
        return {"ok": True, "returncode": 0, "command": command, "timeout": timeout_seconds}

    def json_runner(command: list[str], timeout_seconds: int) -> tuple[dict[str, object], str]:
        calls.append(command)
        if command[-4:] == ["plugin", "list", "--fields=name,status,version", "--format=json"]:
            return {
                "ok": True,
                "payload": [{"name": "npcink-cloud-addon", "status": "inactive"}],
            }, "[]"
        return {"ok": True, "payload": {"option_exists": False}}, "{}"

    report = build_rollback_report(
        target=_target(),
        php_bin="/php",
        wp_bin="/wp",
        snapshot_path=_write_snapshot(tmp_path, _snapshot()),
        output_dir=tmp_path / "out",
        timeout_seconds=1,
        execute=True,
        approval_text=APPROVAL_TEXT,
        command_runner=command_runner,
        json_runner=json_runner,
    )

    assert report["ok"] is True
    assert report["addon_active_after"] is False
    assert report["option_exists_after"] is False
    assert calls[0][-3:] == ["plugin", "deactivate", "npcink-cloud-addon"]
    assert calls[1][-3:] == ["option", "delete", ADDON_OPTION_NAME]


def test_execute_skips_option_delete_when_snapshot_had_existing_settings(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    snapshot = _snapshot(
        settings={
            "base_url": "http://127.0.0.1:8010",
            "site_id": "site_live",
            "key_id_present": True,
            "secret_present": True,
            "api_key_present": False,
            "verified": True,
            "verified_at": "2026-06-20T00:00:00Z",
            "monitoring_enabled": False,
        }
    )

    def command_runner(command: list[str], *, timeout_seconds: int) -> dict[str, object]:
        calls.append(command)
        return {"ok": True, "returncode": 0, "command": command, "timeout": timeout_seconds}

    def json_runner(command: list[str], timeout_seconds: int) -> tuple[dict[str, object], str]:
        calls.append(command)
        if command[-4:] == ["plugin", "list", "--fields=name,status,version", "--format=json"]:
            return {
                "ok": True,
                "payload": [{"name": "npcink-cloud-addon", "status": "inactive"}],
            }, "[]"
        return {"ok": True, "payload": {"option_exists": True}}, "{}"

    report = build_rollback_report(
        target=_target(),
        php_bin="/php",
        wp_bin="/wp",
        snapshot_path=_write_snapshot(tmp_path, snapshot),
        output_dir=tmp_path / "out",
        timeout_seconds=1,
        execute=True,
        approval_text=APPROVAL_TEXT,
        command_runner=command_runner,
        json_runner=json_runner,
    )

    assert report["ok"] is True
    assert report["option_delete"]["skipped"] is True  # type: ignore[index]
    assert [call[-3:] for call in calls].count(["option", "delete", ADDON_OPTION_NAME]) == 0


def test_execute_rejects_snapshot_where_addon_was_already_active(tmp_path: Path) -> None:
    calls: list[str] = []

    def command_runner(*_args: object, **_kwargs: object) -> dict[str, object]:
        calls.append("command")
        return {"ok": True}

    with pytest.raises(GuardError, match="was active before"):
        build_rollback_report(
            target=_target(),
            php_bin="/php",
            wp_bin="/wp",
            snapshot_path=_write_snapshot(tmp_path, _snapshot(active=True)),
            output_dir=tmp_path / "out",
            timeout_seconds=1,
            execute=True,
            approval_text=APPROVAL_TEXT,
            command_runner=command_runner,
        )

    assert calls == []
