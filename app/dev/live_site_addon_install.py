from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.dev.live_site_addon_package import (
    ADDON_PLUGIN_BASENAME,
    DEFAULT_ADDON_ZIP,
    DEFAULT_NPCINK_SITE,
    DEFAULT_OUTPUT_ROOT,
    build_package,
    inspect_addon_zip,
    run_json_command,
    wp_command,
)
from app.dev.live_site_preflight import SiteTarget, _dict, _text, parse_site_spec

APPROVAL_TEXT = (
    "我明确批准在 npcink.local 安装并激活 Cloud addon，provision 专用 Cloud identity，"
    "通过 addon 后台保存 Cloud Base URL 和 Cloud API Key 并验证；本次不运行 runtime "
    "smoke，不运行 Site Knowledge sync/search，不写内容，不启用 monitoring。"
)


class GuardError(RuntimeError):
    """Raised when a guarded write action must not run."""


def normalize_approval(value: str) -> str:
    return "".join(value.split())


def approval_matches(value: str) -> bool:
    return normalize_approval(value) == normalize_approval(APPROVAL_TEXT)


def plugin_active(plugin_rows: object, *, basename: str = ADDON_PLUGIN_BASENAME) -> bool:
    if not isinstance(plugin_rows, list):
        return False
    slug = basename.split("/", 1)[0]
    for row in plugin_rows:
        item = _dict(row)
        if _text(item.get("name")) == slug and _text(item.get("status")) == "active":
            return True
    return False


def validate_prewrite_report(report: dict[str, object]) -> list[str]:
    failures: list[str] = []
    preflight = _dict(report.get("preflight"))
    evaluation = _dict(preflight.get("evaluation"))
    blockers = [str(item) for item in _as_list(evaluation.get("blockers"))]
    unexpected_blockers = [item for item in blockers if item != "cloud_addon_unverified"]
    if unexpected_blockers:
        failures.append(f"unexpected preflight blockers: {', '.join(unexpected_blockers)}")

    local_site = _dict(preflight.get("local_site"))
    if local_site.get("matched") is not True:
        failures.append("Local site metadata did not match the target")
    if local_site.get("mysql_socket_exists") is not True:
        failures.append("Local MySQL socket is missing")

    addon_zip = _dict(report.get("addon_zip"))
    if addon_zip.get("exists") is not True:
        failures.append("addon zip is missing")
    if addon_zip.get("contains_main_plugin") is not True:
        failures.append(f"addon zip does not contain {ADDON_PLUGIN_BASENAME}")

    db_export = _dict(report.get("database_export"))
    if db_export.get("ok") is not True:
        failures.append("database export did not complete")

    return failures


def install_command(
    *,
    target: SiteTarget,
    php_bin: str,
    wp_bin: str,
    mysql_socket: str,
    addon_zip: Path,
) -> list[str]:
    return wp_command(
        target=target,
        php_bin=php_bin,
        wp_bin=wp_bin,
        mysql_socket=mysql_socket,
        args=["plugin", "install", str(addon_zip), "--force", "--activate"],
    )


def plugin_list_command(
    *,
    target: SiteTarget,
    php_bin: str,
    wp_bin: str,
    mysql_socket: str,
) -> list[str]:
    return wp_command(
        target=target,
        php_bin=php_bin,
        wp_bin=wp_bin,
        mysql_socket=mysql_socket,
        args=["plugin", "list", "--fields=name,status,version", "--format=json"],
    )


def run_command(command: list[str], *, timeout_seconds: int) -> dict[str, object]:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc), "command": command}

    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "command": command,
    }


def build_plan_report(
    *,
    target: SiteTarget,
    php_bin: str,
    wp_bin: str,
    addon_zip: Path,
    output_dir: Path,
    timeout_seconds: int,
    execute: bool,
    approval_text: str,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if execute and not approval_matches(approval_text):
        raise GuardError("exact approval text did not match; no WordPress write was run")

    package_report = build_package(
        target=target,
        php_bin=php_bin,
        wp_bin=wp_bin,
        addon_zip=addon_zip,
        output_dir=output_dir / "prewrite-package",
        export_db=True,
        timeout_seconds=timeout_seconds,
    )
    prewrite_failures = validate_prewrite_report(package_report)
    preflight = _dict(package_report.get("preflight"))
    local_site = _dict(preflight.get("local_site"))
    mysql_socket = _text(local_site.get("mysql_socket"))
    install = {
        "ok": False,
        "skipped": True,
        "reason": "prepare_only",
        "command": install_command(
            target=target,
            php_bin=php_bin,
            wp_bin=wp_bin,
            mysql_socket=mysql_socket,
            addon_zip=addon_zip,
        ),
    }
    plugin_list = {
        "ok": False,
        "skipped": True,
        "reason": "prepare_only",
        "command": plugin_list_command(
            target=target,
            php_bin=php_bin,
            wp_bin=wp_bin,
            mysql_socket=mysql_socket,
        ),
    }

    if execute:
        if prewrite_failures:
            raise GuardError("; ".join(prewrite_failures))
        install = run_command(
            install["command"],  # type: ignore[arg-type]
            timeout_seconds=max(timeout_seconds, 120),
        )
        plugin_list, _ = run_json_command(
            plugin_list["command"],  # type: ignore[arg-type]
            timeout_seconds=timeout_seconds,
        )

    plugin_rows = plugin_list.get("payload") if plugin_list.get("ok") is True else []
    report: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "execute" if execute else "prepare",
        "boundary": {
            "wordpress_writes": execute,
            "wordpress_write_scope": ["plugin_install", "plugin_activate"] if execute else [],
            "cloud_identity_provisioning": False,
            "cloud_runtime_execution": False,
            "site_knowledge_sync": False,
            "wordpress_option_writes": False,
            "content_writes": False,
        },
        "approval": {
            "required_for_execute": APPROVAL_TEXT,
            "provided": bool(approval_text),
            "matched": approval_matches(approval_text),
        },
        "target": {"label": target.label, "url": target.url, "path": str(target.path)},
        "addon_zip": inspect_addon_zip(addon_zip),
        "prewrite_package_dir": str(output_dir / "prewrite-package"),
        "prewrite_failures": prewrite_failures,
        "install": install,
        "plugin_list": plugin_list,
        "addon_active": plugin_active(plugin_rows),
        "next_manual_steps": [
            "provision a dedicated Cloud identity through service-plane/internal ops",
            "save Cloud Base URL and Cloud API Key through wp-admin Save and Verify",
            "re-run live-site-preflight after verification",
            "stop before runtime smoke or Site Knowledge sync/search",
        ],
    }
    (output_dir / "install-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "summary.md").write_text(render_markdown(report))
    return report


def render_markdown(report: dict[str, object]) -> str:
    target = _dict(report.get("target"))
    boundary = _dict(report.get("boundary"))
    install = _dict(report.get("install"))
    plugin_list = _dict(report.get("plugin_list"))
    failures = [str(item) for item in _as_list(report.get("prewrite_failures"))]
    write_scope = ", ".join(str(item) for item in _as_list(boundary.get("wordpress_write_scope")))
    lines = [
        "# Live Site Addon Guarded Install",
        "",
        f"Generated at: `{_text(report.get('generated_at'))}`",
        f"Mode: `{_text(report.get('mode'))}`",
        "",
        "## Boundary",
        "",
        f"- WordPress writes: `{boundary.get('wordpress_writes')}`",
        f"- WordPress write scope: `{write_scope or 'none'}`",
        f"- Cloud identity provisioning: `{boundary.get('cloud_identity_provisioning')}`",
        f"- Cloud runtime execution: `{boundary.get('cloud_runtime_execution')}`",
        f"- Site Knowledge sync/search: `{boundary.get('site_knowledge_sync')}`",
        f"- WordPress option writes: `{boundary.get('wordpress_option_writes')}`",
        f"- Content writes: `{boundary.get('content_writes')}`",
        "",
        "## Target",
        "",
        f"- Label: `{_text(target.get('label'))}`",
        f"- URL: `{_text(target.get('url'))}`",
        f"- Path: `{_text(target.get('path'))}`",
        f"- Prewrite package: `{_text(report.get('prewrite_package_dir'))}`",
        f"- Prewrite failures: `{', '.join(failures) or 'none'}`",
        "",
        "## Install State",
        "",
        f"- Install ok: `{install.get('ok')}`",
        f"- Install skipped: `{install.get('skipped', False)}`",
        f"- Plugin list ok: `{plugin_list.get('ok')}`",
        f"- Addon active: `{report.get('addon_active')}`",
        "",
        "## Next Manual Steps",
        "",
    ]
    lines.extend([f"- {step}" for step in _as_list(report.get("next_manual_steps"))])
    lines.append("")
    return "\n".join(lines)


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare or execute the guarded npcink.local Cloud addon install step."
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
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approval-text", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    target = parse_site_spec(args.site) if args.site else DEFAULT_NPCINK_SITE
    suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or DEFAULT_OUTPUT_ROOT / f"{target.label}-guarded-install-{suffix}"
    try:
        report = build_plan_report(
            target=target,
            php_bin=args.php_bin,
            wp_bin=args.wp_bin,
            addon_zip=args.addon_zip,
            output_dir=output_dir,
            timeout_seconds=args.timeout_seconds,
            execute=args.execute,
            approval_text=args.approval_text,
        )
    except GuardError as exc:
        print(json.dumps({"ok": False, "guard_error": str(exc)}), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "ok": not report["prewrite_failures"],
                "mode": report["mode"],
                "output_dir": str(output_dir),
                "addon_active": report["addon_active"],
            }
        )
    )
    if args.execute:
        return 0 if report["addon_active"] is True else 2
    return 0 if not report["prewrite_failures"] else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
