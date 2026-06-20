from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app.dev.live_site_addon_install import plugin_active, plugin_list_command
from app.dev.live_site_addon_package import (
    ADDON_OPTION_NAME,
    DEFAULT_NPCINK_SITE,
    run_json_command,
    wp_command,
)
from app.dev.live_site_preflight import SiteTarget, _dict, _text, parse_site_spec

DEFAULT_OUTPUT_ROOT = Path(".tmp/live-site-addon-rollback")
DEFAULT_SNAPSHOT = Path(
    ".tmp/live-site-stage1/npcink-stage1/addon-install/prewrite-package/snapshot.json"
)
APPROVAL_TEXT = (
    "我明确批准在 npcink.local 回滚 Cloud addon 本地接入：停用 Cloud addon，"
    "在预写快照显示原设置为空时删除 npcink_cloud_addon_settings；本次不导入数据库，"
    "不运行 search-replace，不撤销 Cloud identity，不运行 runtime smoke，不运行 Site Knowledge，"
    "不写内容，不启用 monitoring。"
)


class GuardError(RuntimeError):
    """Raised when a guarded rollback action must not run."""


class CommandRunner(Protocol):
    def __call__(self, command: list[str], *, timeout_seconds: int) -> dict[str, object]: ...


class JsonRunner(Protocol):
    def __call__(
        self, command: list[str], timeout_seconds: int
    ) -> tuple[dict[str, object], str]: ...


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def normalize_approval(value: str) -> str:
    return "".join(value.split())


def approval_matches(value: str) -> bool:
    return normalize_approval(value) == normalize_approval(APPROVAL_TEXT)


def load_snapshot(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise GuardError(f"snapshot not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise GuardError(f"snapshot is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise GuardError(f"snapshot root must be an object: {path}")
    return payload


def snapshot_mysql_socket(snapshot: dict[str, object]) -> str:
    preflight = _dict(snapshot.get("preflight"))
    local_site = _dict(preflight.get("local_site"))
    return _text(local_site.get("mysql_socket"))


def validate_snapshot(snapshot: dict[str, object], *, target: SiteTarget) -> list[str]:
    failures: list[str] = []
    snapshot_target = _dict(snapshot.get("target"))
    if _text(snapshot_target.get("url")).rstrip("/") != target.url.rstrip("/"):
        failures.append("snapshot target URL does not match rollback target")
    if _text(snapshot_target.get("path")) != str(target.path):
        failures.append("snapshot WordPress path does not match rollback target")

    preflight = _dict(snapshot.get("preflight"))
    local_site = _dict(preflight.get("local_site"))
    if local_site.get("matched") is not True:
        failures.append("snapshot did not verify Local site metadata")
    if local_site.get("mysql_socket_exists") is not True:
        failures.append("snapshot MySQL socket was not verified")
    if not _text(local_site.get("mysql_socket")):
        failures.append("snapshot does not include a MySQL socket")

    active_plugins = _dict(snapshot.get("active_plugins"))
    if active_plugins.get("ok") is not True or not isinstance(active_plugins.get("payload"), list):
        failures.append("snapshot does not include a valid active plugin list")
    return failures


def addon_was_active_before(snapshot: dict[str, object]) -> bool:
    active_plugins = _dict(snapshot.get("active_plugins"))
    return plugin_active(active_plugins.get("payload"))


def addon_settings_were_empty(snapshot: dict[str, object]) -> bool:
    settings = _dict(snapshot.get("addon_settings_snapshot"))
    text_fields = ["base_url", "site_id", "verified_at"]
    bool_fields = [
        "key_id_present",
        "secret_present",
        "api_key_present",
        "verified",
        "monitoring_enabled",
    ]
    return all(not _text(settings.get(field)) for field in text_fields) and all(
        settings.get(field) is not True for field in bool_fields
    )


def deactivate_command(
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
        args=["plugin", "deactivate", "magick-ai-cloud-addon"],
    )


def option_delete_command(
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
        args=["option", "delete", ADDON_OPTION_NAME],
    )


def option_snapshot_command(
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
        args=[
            "eval",
            (
                f"$value = get_option('{ADDON_OPTION_NAME}', array()); "
                "$settings = is_array($value) ? $value : array(); "
                "$redacted = array("
                "'option_exists' => $value !== false,"
                "'base_url_present' => !empty($settings['base_url']),"
                "'site_id_present' => !empty($settings['site_id']),"
                "'key_id_present' => !empty($settings['key_id']),"
                "'secret_present' => !empty($settings['secret']),"
                "'api_key_present' => !empty($settings['api_key']),"
                "'verified' => !empty($settings['verified']),"
                "'monitoring_enabled' => !empty($settings['monitoring_enabled']) || "
                "!empty($settings['monitoring']),"
                "); echo wp_json_encode($redacted, JSON_UNESCAPED_SLASHES) . PHP_EOL;"
            ),
        ],
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


def build_rollback_report(
    *,
    target: SiteTarget,
    php_bin: str,
    wp_bin: str,
    snapshot_path: Path,
    output_dir: Path,
    timeout_seconds: int,
    execute: bool,
    approval_text: str,
    command_runner: CommandRunner = run_command,
    json_runner: JsonRunner = run_json_command,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if execute and not approval_matches(approval_text):
        raise GuardError("exact approval text did not match; rollback writes were not run")

    snapshot = load_snapshot(snapshot_path)
    snapshot_failures = validate_snapshot(snapshot, target=target)
    mysql_socket = snapshot_mysql_socket(snapshot)
    was_active_before = addon_was_active_before(snapshot)
    settings_empty_before = addon_settings_were_empty(snapshot)
    deactivate_supported = not was_active_before
    option_delete_supported = settings_empty_before

    planned_deactivate = deactivate_command(
        target=target,
        php_bin=php_bin,
        wp_bin=wp_bin,
        mysql_socket=mysql_socket,
    )
    planned_option_delete = option_delete_command(
        target=target,
        php_bin=php_bin,
        wp_bin=wp_bin,
        mysql_socket=mysql_socket,
    )
    planned_plugin_list = plugin_list_command(
        target=target,
        php_bin=php_bin,
        wp_bin=wp_bin,
        mysql_socket=mysql_socket,
    )
    planned_option_snapshot = option_snapshot_command(
        target=target,
        php_bin=php_bin,
        wp_bin=wp_bin,
        mysql_socket=mysql_socket,
    )

    deactivate: dict[str, object] = {
        "ok": False,
        "skipped": True,
        "reason": "prepare_only",
        "command": planned_deactivate,
    }
    option_delete: dict[str, object] = {
        "ok": False,
        "skipped": True,
        "reason": "prepare_only",
        "command": planned_option_delete,
    }
    plugin_list: dict[str, object] = {
        "ok": False,
        "skipped": True,
        "reason": "prepare_only",
        "command": planned_plugin_list,
    }
    option_snapshot: dict[str, object] = {
        "ok": False,
        "skipped": True,
        "reason": "prepare_only",
        "command": planned_option_snapshot,
    }

    if execute:
        if snapshot_failures:
            raise GuardError("; ".join(snapshot_failures))
        if not deactivate_supported:
            raise GuardError(
                "snapshot shows Cloud addon was active before this trial; "
                "automatic deactivation rollback is unsupported"
            )
        deactivate = command_runner(
            planned_deactivate,
            timeout_seconds=max(timeout_seconds, 60),
        )
        if option_delete_supported:
            option_delete = command_runner(planned_option_delete, timeout_seconds=timeout_seconds)
        else:
            option_delete = {
                "ok": True,
                "skipped": True,
                "reason": "prewrite snapshot contained addon settings; not deleting redacted state",
                "command": planned_option_delete,
            }
        plugin_list, _ = json_runner(planned_plugin_list, timeout_seconds)
        option_snapshot, _ = json_runner(planned_option_snapshot, timeout_seconds)

    plugin_rows = plugin_list.get("payload") if plugin_list.get("ok") is True else []
    addon_active_after = plugin_active(plugin_rows)
    option_payload = _dict(option_snapshot.get("payload"))
    option_exists_after = option_payload.get("option_exists") is True
    ok = (
        len(snapshot_failures) == 0
        if not execute
        else (
            deactivate.get("ok") is True
            and addon_active_after is False
            and (
                not option_delete_supported
                or (
                    option_delete.get("ok") is True
                    and option_snapshot.get("ok") is True
                    and option_exists_after is False
                )
            )
        )
    )

    planned_write_scope = ["plugin_deactivate"]
    if option_delete_supported:
        planned_write_scope.append("option_delete")

    report: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "execute" if execute else "prepare",
        "ok": ok,
        "target": {"label": target.label, "url": target.url, "path": str(target.path)},
        "snapshot_path": str(snapshot_path),
        "boundary": {
            "wordpress_writes": execute,
            "wordpress_write_scope": planned_write_scope if execute else [],
            "planned_wordpress_write_scope": planned_write_scope,
            "database_import": False,
            "search_replace": False,
            "cloud_identity_revoke": False,
            "cloud_runtime_execution": False,
            "runtime_smoke": False,
            "site_knowledge_sync": False,
            "site_knowledge_search": False,
            "content_writes": False,
            "monitoring_enabled": False,
        },
        "approval": {
            "required_for_execute": APPROVAL_TEXT,
            "provided": bool(approval_text),
            "matched": approval_matches(approval_text),
        },
        "snapshot_assessment": {
            "failures": snapshot_failures,
            "addon_was_active_before": was_active_before,
            "addon_deactivate_supported": deactivate_supported,
            "addon_settings_were_empty": settings_empty_before,
            "option_delete_supported": option_delete_supported,
            "mysql_socket": mysql_socket,
        },
        "deactivate": deactivate,
        "option_delete": option_delete,
        "plugin_list": plugin_list,
        "option_snapshot": option_snapshot,
        "addon_active_after": addon_active_after,
        "option_exists_after": option_exists_after,
        "rollback_limits": [
            "does not uninstall plugin files",
            "does not import the database backup",
            "does not run search-replace",
            "does not revoke Cloud identity or API keys",
            "does not call Cloud runtime or Site Knowledge",
        ],
        "next_manual_steps": next_manual_steps(
            execute=execute,
            ok=ok,
            option_delete_supported=option_delete_supported,
        ),
    }
    (output_dir / "rollback-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "summary.md").write_text(render_markdown(report))
    return report


def next_manual_steps(*, execute: bool, ok: bool, option_delete_supported: bool) -> list[str]:
    if not execute:
        return [
            "review the rollback report and snapshot assessment",
            "use the exact rollback approval text before running execute mode",
            "keep Cloud identity revocation as a separate service-plane action if needed",
        ]
    if not ok:
        return [
            "inspect rollback-report.json before attempting any broader recovery",
            "do not import the database or revoke Cloud identity without separate approval",
        ]
    steps = [
        "run the read-only live-site preflight to confirm addon readiness is inactive",
        "decide separately whether to revoke the dedicated Cloud API key through service-plane ops",
    ]
    if not option_delete_supported:
        steps.insert(
            0,
            "addon settings were not deleted because the prewrite snapshot had existing settings",
        )
    return steps


def render_markdown(report: dict[str, object]) -> str:
    target = _dict(report.get("target"))
    boundary = _dict(report.get("boundary"))
    assessment = _dict(report.get("snapshot_assessment"))
    deactivate = _dict(report.get("deactivate"))
    option_delete = _dict(report.get("option_delete"))
    write_scope = ", ".join(str(item) for item in _as_list(boundary.get("wordpress_write_scope")))
    planned_scope = ", ".join(
        str(item) for item in _as_list(boundary.get("planned_wordpress_write_scope"))
    )
    failures = ", ".join(str(item) for item in _as_list(assessment.get("failures")))
    lines = [
        "# Live Site Addon Guarded Rollback",
        "",
        f"Generated at: `{_text(report.get('generated_at'))}`",
        f"Mode: `{_text(report.get('mode'))}`",
        f"OK: `{report.get('ok')}`",
        "",
        "## Boundary",
        "",
        f"- WordPress writes: `{boundary.get('wordpress_writes')}`",
        f"- WordPress write scope: `{write_scope or 'none'}`",
        f"- Planned WordPress write scope: `{planned_scope or 'none'}`",
        f"- Database import: `{boundary.get('database_import')}`",
        f"- Search-replace: `{boundary.get('search_replace')}`",
        f"- Cloud identity revoke: `{boundary.get('cloud_identity_revoke')}`",
        f"- Cloud runtime execution: `{boundary.get('cloud_runtime_execution')}`",
        f"- Site Knowledge sync: `{boundary.get('site_knowledge_sync')}`",
        f"- Site Knowledge search: `{boundary.get('site_knowledge_search')}`",
        f"- Content writes: `{boundary.get('content_writes')}`",
        f"- Monitoring enabled: `{boundary.get('monitoring_enabled')}`",
        "",
        "## Target",
        "",
        f"- Label: `{_text(target.get('label'))}`",
        f"- URL: `{_text(target.get('url'))}`",
        f"- Path: `{_text(target.get('path'))}`",
        f"- Snapshot: `{_text(report.get('snapshot_path'))}`",
        "",
        "## Snapshot Assessment",
        "",
        f"- Failures: `{failures or 'none'}`",
        f"- Addon was active before: `{assessment.get('addon_was_active_before')}`",
        f"- Deactivate supported: `{assessment.get('addon_deactivate_supported')}`",
        f"- Addon settings were empty: `{assessment.get('addon_settings_were_empty')}`",
        f"- Option delete supported: `{assessment.get('option_delete_supported')}`",
        "",
        "## Results",
        "",
        f"- Deactivate ok: `{deactivate.get('ok')}`",
        f"- Deactivate skipped: `{deactivate.get('skipped', False)}`",
        f"- Option delete ok: `{option_delete.get('ok')}`",
        f"- Option delete skipped: `{option_delete.get('skipped', False)}`",
        f"- Addon active after: `{report.get('addon_active_after')}`",
        f"- Option exists after: `{report.get('option_exists_after')}`",
        "",
        "## Rollback Limits",
        "",
    ]
    lines.extend([f"- {item}" for item in _as_list(report.get("rollback_limits"))])
    lines.extend(["", "## Next Manual Steps", ""])
    lines.extend([f"- {step}" for step in _as_list(report.get("next_manual_steps"))])
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare or execute the guarded npcink.local Cloud addon rollback step."
    )
    parser.add_argument(
        "--site",
        nargs=3,
        metavar=("LABEL", "URL", "WORDPRESS_ROOT"),
        help="Target site. Defaults to npcink.local.",
    )
    parser.add_argument("--php-bin", default="/opt/homebrew/bin/php")
    parser.add_argument("--wp-bin", default="/opt/homebrew/bin/wp")
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approval-text", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    target = parse_site_spec(args.site) if args.site else DEFAULT_NPCINK_SITE
    suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or DEFAULT_OUTPUT_ROOT / f"{target.label}-rollback-{suffix}"
    try:
        report = build_rollback_report(
            target=target,
            php_bin=args.php_bin,
            wp_bin=args.wp_bin,
            snapshot_path=args.snapshot,
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
                "ok": report["ok"],
                "mode": report["mode"],
                "output_dir": str(output_dir),
                "addon_active_after": report["addon_active_after"],
                "option_exists_after": report["option_exists_after"],
            }
        )
    )
    return 0 if report["ok"] is True else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
