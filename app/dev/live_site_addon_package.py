from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from app.dev.live_site_preflight import (
    LOCAL_APP_SUPPORT,
    SiteTarget,
    _dict,
    _text,
    collect_site,
    parse_site_spec,
)

DEFAULT_NPCINK_SITE = SiteTarget(
    "npcink",
    "http://npcink.local/",
    Path("/Users/muze/Local Sites/npcink/app/public"),
)
DEFAULT_ADDON_ZIP = Path("/Users/muze/gitee/magick-ai-cloud-addon/build/magick-ai-cloud-addon.zip")
DEFAULT_OUTPUT_ROOT = Path(".tmp/live-site-addon-package")
ADDON_OPTION_NAME = "npcink_cloud_addon_settings"
ADDON_PLUGIN_BASENAME = "magick-ai-cloud-addon/magick-ai-cloud-addon.php"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_addon_zip(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"exists": False, "path": str(path)}
    info: dict[str, object] = {
        "exists": True,
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "contains_main_plugin": False,
        "plugin_header": {},
    }
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            info["contains_main_plugin"] = ADDON_PLUGIN_BASENAME in names
            if ADDON_PLUGIN_BASENAME in names:
                header = archive.read(ADDON_PLUGIN_BASENAME).decode("utf-8", errors="replace")
                info["plugin_header"] = parse_plugin_header(header)
    except (OSError, zipfile.BadZipFile) as exc:
        info["error"] = str(exc)
    return info


def parse_plugin_header(content: str) -> dict[str, str]:
    fields = {
        "Plugin Name": "plugin_name",
        "Version": "version",
        "Text Domain": "text_domain",
    }
    header: dict[str, str] = {}
    for line in content.splitlines()[:80]:
        stripped = line.strip(" /*\t")
        for label, key in fields.items():
            prefix = f"{label}:"
            if stripped.startswith(prefix):
                header[key] = stripped[len(prefix) :].strip()
    return header


def redact_addon_settings(value: object) -> dict[str, object]:
    settings = _dict(value)
    return {
        "base_url": _text(settings.get("base_url")),
        "site_id": _text(settings.get("site_id")),
        "key_id_present": bool(settings.get("key_id")),
        "secret_present": bool(settings.get("secret")),
        "api_key_present": bool(settings.get("api_key")),
        "timeout": settings.get("timeout", 0),
        "verified": bool(settings.get("verified")),
        "verified_at": _text(settings.get("verified_at")),
        "monitoring": bool(settings.get("monitoring")),
    }


def wp_command(
    *,
    target: SiteTarget,
    php_bin: str,
    wp_bin: str,
    mysql_socket: str,
    args: list[str],
) -> list[str]:
    command = [php_bin]
    if mysql_socket:
        command.extend(
            [
                "-d",
                f"mysqli.default_socket={mysql_socket}",
                "-d",
                f"pdo_mysql.default_socket={mysql_socket}",
            ]
        )
    command.extend([wp_bin, f"--path={target.path}", f"--url={target.url}", *args])
    return command


def run_json_command(command: list[str], timeout_seconds: int) -> tuple[dict[str, object], str]:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        return (
            {
                "ok": False,
                "returncode": result.returncode,
                "error": result.stderr.strip() or result.stdout.strip(),
            },
            result.stdout,
        )
    try:
        return {"ok": True, "payload": json.loads(result.stdout or "null")}, result.stdout
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"non_json_output: {exc}"}, result.stdout


def export_database(
    *,
    target: SiteTarget,
    php_bin: str,
    wp_bin: str,
    mysql_socket: str,
    mysql_bin_dir: str,
    output_path: Path,
    timeout_seconds: int,
) -> dict[str, object]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = wp_command(
        target=target,
        php_bin=php_bin,
        wp_bin=wp_bin,
        mysql_socket=mysql_socket,
        args=["db", "export", str(output_path), "--add-drop-table"],
    )
    env = os.environ.copy()
    if mysql_bin_dir:
        env["PATH"] = f"{mysql_bin_dir}{os.pathsep}{env.get('PATH', '')}"
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "path": str(output_path), "error": str(exc)}

    if result.returncode != 0:
        return {
            "ok": False,
            "path": str(output_path),
            "returncode": result.returncode,
            "error": result.stderr.strip() or result.stdout.strip(),
        }
    return {
        "ok": output_path.exists(),
        "path": str(output_path),
        "bytes": output_path.stat().st_size if output_path.exists() else 0,
        "sha256": sha256_file(output_path) if output_path.exists() else "",
        "stdout": result.stdout.strip(),
        "mysql_bin_dir": mysql_bin_dir,
    }


def find_local_mysql_bin_dir(version: str) -> str:
    if not version:
        return ""
    candidates = sorted(
        (LOCAL_APP_SUPPORT / "lightning-services").glob(f"mysql-{version}*/bin/*/bin")
    )
    for candidate in candidates:
        if (candidate / "mysql").exists() and (candidate / "mysqldump").exists():
            return str(candidate)
    return ""


def build_package(
    *,
    target: SiteTarget,
    php_bin: str,
    wp_bin: str,
    addon_zip: Path,
    output_dir: Path,
    export_db: bool,
    timeout_seconds: int,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    preflight = collect_site(
        target=target,
        php_bin=php_bin,
        wp_bin=wp_bin,
        timeout_seconds=timeout_seconds,
        min_public_items=10,
        use_local_socket=True,
    )
    local_site = _dict(preflight.get("local_site"))
    mysql_socket = (
        _text(local_site.get("mysql_socket")) if local_site.get("matched") is True else ""
    )
    mysql_bin_dir = find_local_mysql_bin_dir(_text(local_site.get("mysql_version")))

    active_plugins_cmd = wp_command(
        target=target,
        php_bin=php_bin,
        wp_bin=wp_bin,
        mysql_socket=mysql_socket,
        args=["plugin", "list", "--fields=name,status,version", "--format=json"],
    )
    active_plugins, _ = run_json_command(active_plugins_cmd, timeout_seconds=timeout_seconds)

    option_cmd = wp_command(
        target=target,
        php_bin=php_bin,
        wp_bin=wp_bin,
        mysql_socket=mysql_socket,
        args=[
            "eval",
            (
                f"$value = get_option('{ADDON_OPTION_NAME}', array()); "
                "echo wp_json_encode($value, JSON_UNESCAPED_SLASHES) . PHP_EOL;"
            ),
        ],
    )
    option_result, _ = run_json_command(option_cmd, timeout_seconds=timeout_seconds)
    option_payload = option_result.get("payload") if option_result.get("ok") is True else {}

    db_export: dict[str, object] = {"ok": False, "skipped": True}
    if export_db:
        db_export = export_database(
            target=target,
            php_bin=php_bin,
            wp_bin=wp_bin,
            mysql_socket=mysql_socket,
            mysql_bin_dir=mysql_bin_dir,
            output_path=output_dir / f"{target.label}-pre-addon.sql",
            timeout_seconds=max(timeout_seconds, 120),
        )

    report: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "boundary": {
            "wordpress_writes": False,
            "cloud_identity_provisioning": False,
            "cloud_runtime_execution": False,
            "site_knowledge_sync": False,
            "database_export": export_db,
        },
        "target": {"label": target.label, "url": target.url, "path": str(target.path)},
        "preflight": preflight,
        "addon_zip": inspect_addon_zip(addon_zip),
        "local_mysql_bin_dir": mysql_bin_dir,
        "active_plugins": active_plugins,
        "addon_settings_snapshot": redact_addon_settings(option_payload),
        "database_export": db_export,
        "rollback_inputs": {
            "active_plugins_snapshot": "active_plugins.payload",
            "addon_settings_snapshot": "addon_settings_snapshot",
            "database_export_path": db_export.get("path", ""),
        },
        "next_write_actions_require_approval": [
            "install_or_copy_addon",
            "activate_addon",
            "provision_cloud_identity",
            "save_cloud_base_url_and_api_key",
            "run_runtime_smoke",
            "run_site_knowledge_sync_or_search",
        ],
    }
    (output_dir / "snapshot.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (output_dir / "summary.md").write_text(render_markdown(report))
    return report


def render_markdown(report: dict[str, object]) -> str:
    target = _dict(report.get("target"))
    addon_zip = _dict(report.get("addon_zip"))
    preflight = _dict(report.get("preflight"))
    evaluation = _dict(preflight.get("evaluation"))
    db_export = _dict(report.get("database_export"))
    settings = _dict(report.get("addon_settings_snapshot"))
    lines = [
        "# Live Site Addon Pre-Write Package",
        "",
        f"Generated at: `{_text(report.get('generated_at'))}`",
        "",
        "## Boundary",
        "",
        "This package captures backup and rollback inputs before addon installation.",
        "It does not install or activate plugins, write WordPress options, provision",
        "Cloud identity, run runtime smoke, or run Site Knowledge sync/search.",
        "",
        "## Target",
        "",
        f"- Label: `{_text(target.get('label'))}`",
        f"- URL: `{_text(target.get('url'))}`",
        f"- Path: `{_text(target.get('path'))}`",
        f"- Current preflight decision: `{_text(evaluation.get('decision'))}`",
        f"- Current blockers: `{', '.join(map(str, evaluation.get('blockers', []))) or 'none'}`",
        "",
        "## Addon Package",
        "",
        f"- Path: `{_text(addon_zip.get('path'))}`",
        f"- Exists: `{addon_zip.get('exists')}`",
        f"- Contains main plugin: `{addon_zip.get('contains_main_plugin')}`",
        f"- SHA256: `{_text(addon_zip.get('sha256'))}`",
        "",
        "## Snapshots",
        "",
        f"- Addon settings verified: `{settings.get('verified')}`",
        f"- Addon settings base URL set: `{bool(settings.get('base_url'))}`",
        f"- Addon settings site ID set: `{bool(settings.get('site_id'))}`",
        f"- DB export ok: `{db_export.get('ok')}`",
        f"- DB export path: `{_text(db_export.get('path'))}`",
        "",
        "## Next Actions Require Explicit Approval",
        "",
        "- install or copy addon",
        "- activate addon",
        "- provision Cloud identity",
        "- save Cloud Base URL and Cloud API Key",
        "- run runtime smoke",
        "- run Site Knowledge sync/search",
        "",
    ]
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a no-mutation addon installation pre-write package."
    )
    parser.add_argument(
        "--site",
        nargs=3,
        metavar=("LABEL", "URL", "WORDPRESS_ROOT"),
        help="Target site. Defaults to npcink.local.",
    )
    parser.add_argument("--php-bin", default="/opt/homebrew/bin/php")
    parser.add_argument("--wp-bin", default="/opt/homebrew/bin/wp")
    parser.add_argument("--addon-zip", type=Path, default=DEFAULT_ADDON_ZIP)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--skip-db-export", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    target = parse_site_spec(args.site) if args.site else DEFAULT_NPCINK_SITE
    suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or DEFAULT_OUTPUT_ROOT / f"{target.label}-{suffix}"
    report = build_package(
        target=target,
        php_bin=args.php_bin,
        wp_bin=args.wp_bin,
        addon_zip=args.addon_zip,
        output_dir=output_dir,
        export_db=not args.skip_db_export,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps({"output_dir": str(output_dir), "db_export": report["database_export"]}))
    return 0 if _dict(report.get("database_export")).get("ok") is True else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
