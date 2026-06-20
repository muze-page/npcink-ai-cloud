from __future__ import annotations

from pathlib import Path

from app.dev.live_site_addon_install import (
    APPROVAL_TEXT,
    approval_matches,
    install_command,
    normalize_approval,
    plugin_active,
    plugin_list_command,
    validate_prewrite_report,
)
from app.dev.live_site_addon_package import ADDON_PLUGIN_BASENAME
from app.dev.live_site_preflight import SiteTarget


def _target() -> SiteTarget:
    return SiteTarget("npcink", "http://npcink.local/", Path("/site/app/public"))


def test_approval_matches_expected_text_with_whitespace_normalization() -> None:
    wrapped = APPROVAL_TEXT.replace("，", "，\n")

    assert approval_matches(wrapped) is True
    assert normalize_approval(" a\n b\tc ") == "abc"
    assert approval_matches("同意") is False


def test_plugin_active_matches_build_slug_and_active_status() -> None:
    assert (
        plugin_active(
            [
                {"name": "magick-ai-cloud-addon", "status": "active", "version": "0.1.0"},
            ]
        )
        is True
    )
    assert (
        plugin_active(
            [
                {"name": "magick-ai-cloud-addon", "status": "inactive", "version": "0.1.0"},
            ]
        )
        is False
    )


def test_validate_prewrite_report_allows_only_cloud_addon_blocker() -> None:
    report = {
        "preflight": {
            "evaluation": {"blockers": ["cloud_addon_unverified"]},
            "local_site": {"matched": True, "mysql_socket_exists": True},
        },
        "addon_zip": {"exists": True, "contains_main_plugin": True},
        "database_export": {"ok": True},
    }

    assert validate_prewrite_report(report) == []

    report["preflight"]["evaluation"]["blockers"] = [  # type: ignore[index]
        "wordpress_identity_mismatch",
        "cloud_addon_unverified",
    ]
    assert validate_prewrite_report(report) == [
        "unexpected preflight blockers: wordpress_identity_mismatch"
    ]


def test_wp_commands_target_addon_zip_and_plugin_list() -> None:
    install = install_command(
        target=_target(),
        php_bin="/php",
        wp_bin="/wp",
        mysql_socket="/tmp/mysql.sock",
        addon_zip=Path("/addon.zip"),
    )
    plugin_list = plugin_list_command(
        target=_target(),
        php_bin="/php",
        wp_bin="/wp",
        mysql_socket="/tmp/mysql.sock",
    )

    assert install[:6] == [
        "/php",
        "-d",
        "mysqli.default_socket=/tmp/mysql.sock",
        "-d",
        "pdo_mysql.default_socket=/tmp/mysql.sock",
        "/wp",
    ]
    assert install[-5:] == ["plugin", "install", "/addon.zip", "--force", "--activate"]
    assert "--path=/site/app/public" in install
    assert f"--url={_target().url}" in install
    assert plugin_list[-4:] == [
        "plugin",
        "list",
        "--fields=name,status,version",
        "--format=json",
    ]
    assert ADDON_PLUGIN_BASENAME == "magick-ai-cloud-addon/magick-ai-cloud-addon.php"
