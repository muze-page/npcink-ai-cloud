from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

from app.dev.live_site_addon_package import (
    ADDON_PLUGIN_BASENAME,
    find_local_mysql_bin_dir,
    inspect_addon_zip,
    redact_addon_settings,
    wp_command,
)
from app.dev.live_site_preflight import SiteTarget


def test_inspect_addon_zip_reports_main_plugin_header(tmp_path: Path) -> None:
    addon_zip = tmp_path / "addon.zip"
    with ZipFile(addon_zip, "w") as archive:
        archive.writestr(
            ADDON_PLUGIN_BASENAME,
            """
            <?php
            /**
             * Plugin Name:       Npcink Cloud Addon
             * Version:           0.1.0
             * Text Domain:       npcink-cloud-addon
             */
            """,
        )

    result = inspect_addon_zip(addon_zip)

    assert result["exists"] is True
    assert result["contains_main_plugin"] is True
    assert result["plugin_header"] == {
        "plugin_name": "Npcink Cloud Addon",
        "version": "0.1.0",
        "text_domain": "npcink-cloud-addon",
    }
    assert result["sha256"]


def test_redact_addon_settings_keeps_presence_only_for_secret_fields() -> None:
    result = redact_addon_settings(
        {
            "base_url": "https://cloud.example.com",
            "site_id": "site_live",
            "key_id": "key_live",
            "secret": "do-not-print",
            "api_key": "also-do-not-print",
            "verified": True,
        }
    )

    assert result["base_url"] == "https://cloud.example.com"
    assert result["site_id"] == "site_live"
    assert result["key_id_present"] is True
    assert result["secret_present"] is True
    assert result["api_key_present"] is True
    assert "do-not-print" not in str(result)
    assert "also-do-not-print" not in str(result)


def test_wp_command_injects_local_mysql_socket_before_wp_bin() -> None:
    command = wp_command(
        target=SiteTarget("npcink", "http://npcink.local/", Path("/site/app/public")),
        php_bin="/php",
        wp_bin="/wp",
        mysql_socket="/tmp/mysql.sock",
        args=["plugin", "list"],
    )

    assert command[:5] == [
        "/php",
        "-d",
        "mysqli.default_socket=/tmp/mysql.sock",
        "-d",
        "pdo_mysql.default_socket=/tmp/mysql.sock",
    ]
    assert command[5:] == [
        "/wp",
        "--path=/site/app/public",
        "--url=http://npcink.local/",
        "plugin",
        "list",
    ]


def test_find_local_mysql_bin_dir_uses_matching_version(
    tmp_path: Path, monkeypatch: object
) -> None:
    support_dir = tmp_path / "Local"
    bin_dir = support_dir / "lightning-services" / "mysql-8.4.0" / "bin" / "darwin-arm64" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "mysql").write_text("")
    (bin_dir / "mysqldump").write_text("")
    monkeypatch.setattr("app.dev.live_site_addon_package.LOCAL_APP_SUPPORT", support_dir)

    assert find_local_mysql_bin_dir("8.4.0") == str(bin_dir)
