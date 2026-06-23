from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_SITES = (
    ("wp", "http://wp.local/", "/Users/muze/Local Sites/wp/app/public"),
    ("npcink", "http://npcink.local/", "/Users/muze/Local Sites/npcink/app/public"),
    ("dbd", "http://dbd.local/", "/Users/muze/Local Sites/dbd/app/public"),
)

LOCAL_APP_SUPPORT = Path.home() / "Library/Application Support/Local"

WP_EVAL_SUMMARY = r"""
global $wpdb;
$cloud_option_names = [
    "npcink_cloud_addon_settings",
    "npcink_cloud_addon_settings",
];
$settings = [];
$settings_option_name = "";
foreach ($cloud_option_names as $option_name) {
    $candidate = get_option($option_name, []);
    if (is_array($candidate) && !empty($candidate)) {
        $settings = $candidate;
        $settings_option_name = $option_name;
        break;
    }
}
$active_plugins = (array) get_option("active_plugins", []);
$summary = [
    "siteurl" => get_option("siteurl"),
    "home" => get_option("home"),
    "blogname" => get_option("blogname"),
    "db_name" => DB_NAME,
    "table_prefix" => $wpdb->prefix,
    "is_multisite" => is_multisite(),
    "wp_version" => get_bloginfo("version"),
    "active_theme" => wp_get_theme()->get_stylesheet() . " " . wp_get_theme()->get("Version"),
    "active_plugins" => array_values($active_plugins),
    "counts" => [
        "publish_post_page" => (int) $wpdb->get_var(
            "SELECT COUNT(*) FROM {$wpdb->posts} " .
            "WHERE post_type IN (\"post\", \"page\") AND post_status = \"publish\""
        ),
        "publish_post" => (int) $wpdb->get_var(
            "SELECT COUNT(*) FROM {$wpdb->posts} " .
            "WHERE post_type = \"post\" AND post_status = \"publish\""
        ),
        "publish_page" => (int) $wpdb->get_var(
            "SELECT COUNT(*) FROM {$wpdb->posts} " .
            "WHERE post_type = \"page\" AND post_status = \"publish\""
        ),
        "draft_private_pending_future" => (int) $wpdb->get_var(
            "SELECT COUNT(*) FROM {$wpdb->posts} " .
            "WHERE post_status IN (\"draft\", \"private\", \"pending\", \"future\")"
        ),
        "attachments_inherit" => (int) $wpdb->get_var(
            "SELECT COUNT(*) FROM {$wpdb->posts} " .
            "WHERE post_type = \"attachment\" AND post_status = \"inherit\""
        ),
    ],
    "cloud_settings" => [
        "option_name" => $settings_option_name,
        "base_url" => $settings["base_url"] ?? "",
        "site_id" => $settings["site_id"] ?? "",
        "key_id_present" => !empty($settings["key_id"]),
        "secret_present" => !empty($settings["secret"]),
        "api_key_present" => !empty($settings["api_key"]),
        "timeout" => $settings["timeout"] ?? 0,
        "verified" => !empty($settings["verified"]),
        "verified_at" => $settings["verified_at"] ?? "",
        "monitoring_enabled" => !empty($settings["monitoring_enabled"])
            || !empty($settings["monitoring"]),
    ],
    "sample_public_titles" => $wpdb->get_col(
        "SELECT post_title FROM {$wpdb->posts} " .
        "WHERE post_type IN (\"post\", \"page\") AND post_status = \"publish\" " .
        "ORDER BY ID ASC LIMIT 5"
    ),
];
echo wp_json_encode($summary, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . PHP_EOL;
"""


@dataclass(frozen=True)
class SiteTarget:
    label: str
    url: str
    path: Path


def parse_site_spec(values: list[str]) -> SiteTarget:
    if len(values) != 3:
        raise argparse.ArgumentTypeError("--site expects: label url wordpress_root")
    label, url, root = values
    if not label.strip():
        raise argparse.ArgumentTypeError("site label must not be empty")
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise argparse.ArgumentTypeError(f"site URL is invalid: {url}")
    return SiteTarget(label=label.strip(), url=url.strip(), path=Path(root).expanduser())


def _text(value: object) -> str:
    return str(value or "").strip()


def _host(value: str) -> str:
    return urlparse(value).hostname or ""


def _extract_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return re.sub(r"\s+", " ", unescape(match.group(1))).strip()


def fetch_http_summary(url: str, timeout_seconds: int) -> dict[str, object]:
    command = [
        "curl",
        "-L",
        "-k",
        "--noproxy",
        "*",
        "-sS",
        "-m",
        str(timeout_seconds),
        "-o",
    ]
    with tempfile.NamedTemporaryFile() as body_file:
        command.extend(
            [
                body_file.name,
                "-w",
                "%{http_code}\n%{url_effective}",
                "-H",
                "User-Agent: npcink-ai-cloud-live-preflight/1.0",
                url,
            ]
        )
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds + 2,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "status": 0, "final_url": url, "title": "", "error": str(exc)}

        body_file.seek(0)
        body = body_file.read(256_000).decode("utf-8", errors="replace")

    status, final_url = _parse_curl_write_out(result.stdout, fallback_url=url)
    return {
        "ok": result.returncode == 0 and 200 <= status < 400,
        "status": status,
        "final_url": final_url,
        "title": _extract_title(body),
        "error": result.stderr.strip() if result.returncode != 0 else "",
    }


def _parse_curl_write_out(output: str, *, fallback_url: str) -> tuple[int, str]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return 0, fallback_url
    try:
        status = int(lines[0])
    except ValueError:
        status = 0
    final_url = lines[1] if len(lines) > 1 else fallback_url
    return status, final_url


def run_wp_summary(
    *,
    target: SiteTarget,
    php_bin: str,
    wp_bin: str,
    timeout_seconds: int,
    mysql_socket: str = "",
) -> dict[str, object]:
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
    command.extend(
        [wp_bin, f"--path={target.path}", f"--url={target.url}", "eval", WP_EVAL_SUMMARY]
    )
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc), "command": _safe_command(command)}

    if result.returncode != 0:
        return {
            "ok": False,
            "error": result.stderr.strip() or result.stdout.strip(),
            "returncode": result.returncode,
            "command": _safe_command(command),
        }

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "error": f"WP-CLI returned non-JSON output: {exc}",
            "stdout_preview": result.stdout[:500],
            "command": _safe_command(command),
        }
    payload["ok"] = True
    return payload


def _safe_command(command: list[str]) -> list[str]:
    return [item if item != WP_EVAL_SUMMARY else "<read-only eval summary>" for item in command]


def collect_sql_dump_summary(site_root: Path) -> dict[str, object]:
    sql_path = site_root.parent / "sql" / "local.sql"
    if not sql_path.exists():
        return {"exists": False, "path": str(sql_path), "bytes": 0, "pattern_count": 0}

    pattern = re.compile(r"INSERT INTO.*wp_posts|post_title|https?://[^ ]+\.local")
    count = 0
    with sql_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if pattern.search(line):
                count += 1
    return {
        "exists": True,
        "path": str(sql_path),
        "bytes": sql_path.stat().st_size,
        "pattern_count": count,
    }


def resolve_local_site_metadata(target: SiteTarget) -> dict[str, object]:
    sites_path = LOCAL_APP_SUPPORT / "sites.json"
    if not sites_path.exists():
        return {"matched": False, "reason": "local_sites_json_missing"}
    try:
        sites = json.loads(sites_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"matched": False, "reason": f"local_sites_json_unreadable: {exc}"}

    if not isinstance(sites, dict):
        return {"matched": False, "reason": "local_sites_json_invalid"}

    target_site_root = target.path.parent.parent.resolve()
    target_host = _host(target.url)
    for site_id, site in sites.items():
        if not isinstance(site, dict):
            continue
        site_path = _expand_local_path(_text(site.get("path")))
        site_domain = _text(site.get("domain"))
        if site_path != target_site_root and site_domain != target_host:
            continue
        services = _dict(site.get("services"))
        mysql = _dict(services.get("mysql"))
        nginx = _dict(services.get("nginx"))
        mysql_port = _first_port(mysql)
        nginx_port = _first_port(nginx)
        mysql_socket = LOCAL_APP_SUPPORT / "run" / str(site_id) / "mysql" / "mysqld.sock"
        return {
            "matched": True,
            "site_id": str(site_id),
            "name": _text(site.get("name")),
            "domain": site_domain,
            "path": str(site_path),
            "mysql_version": _text(mysql.get("version")),
            "mysql_service_name": _text(mysql.get("name")),
            "mysql_port": mysql_port,
            "nginx_port": nginx_port,
            "mysql_socket": str(mysql_socket),
            "mysql_socket_exists": mysql_socket.exists(),
        }
    return {"matched": False, "reason": "local_site_not_matched"}


def _expand_local_path(value: str) -> Path:
    if value.startswith("~/"):
        value = str(Path.home() / value[2:])
    return Path(value).expanduser().resolve()


def _first_port(service: dict[str, Any]) -> int | None:
    ports = _dict(service.get("ports"))
    for value in ports.values():
        if isinstance(value, list) and value:
            try:
                return int(value[0])
            except (TypeError, ValueError):
                return None
    return None


def cloud_addon_ready(wp_summary: dict[str, object]) -> bool:
    settings = _dict(wp_summary.get("cloud_settings"))
    return bool(
        _text(settings.get("base_url"))
        and _text(settings.get("site_id"))
        and settings.get("verified") is True
        and (
            settings.get("key_id_present") is True
            or settings.get("secret_present") is True
            or settings.get("api_key_present") is True
        )
    )


def active_cloud_addon_plugin(wp_summary: dict[str, object]) -> bool:
    plugins = wp_summary.get("active_plugins")
    if not isinstance(plugins, list):
        return False
    return any("cloud-addon" in _text(plugin) for plugin in plugins)


def internal_identity_matches(target: SiteTarget, wp_summary: dict[str, object]) -> bool:
    expected_host = _host(target.url)
    siteurl_host = _host(_text(wp_summary.get("siteurl")))
    home_host = _host(_text(wp_summary.get("home")))
    return bool(expected_host and siteurl_host == expected_host and home_host == expected_host)


def public_content_count(wp_summary: dict[str, object]) -> int:
    counts = _dict(wp_summary.get("counts"))
    try:
        return int(counts.get("publish_post_page") or 0)
    except (TypeError, ValueError):
        return 0


def evaluate_candidate(
    *,
    target: SiteTarget,
    http_summary: dict[str, object],
    wp_summary: dict[str, object],
    min_public_items: int,
) -> dict[str, object]:
    blockers: list[str] = []
    warnings: list[str] = []

    if http_summary.get("ok") is not True:
        blockers.append("http_unreachable")
    if wp_summary.get("ok") is not True:
        blockers.append("wpcli_unavailable")
        return {"decision": "no-go", "blockers": blockers, "warnings": warnings}

    if not internal_identity_matches(target, wp_summary):
        blockers.append("wordpress_identity_mismatch")
    if public_content_count(wp_summary) < min_public_items:
        blockers.append("content_set_too_small")
    if not cloud_addon_ready(wp_summary):
        blockers.append("cloud_addon_unverified")
    if not active_cloud_addon_plugin(wp_summary):
        warnings.append("cloud_addon_plugin_not_active")

    decision = "go" if not blockers else "no-go"
    return {"decision": decision, "blockers": blockers, "warnings": warnings}


def collect_site(
    *,
    target: SiteTarget,
    php_bin: str,
    wp_bin: str,
    timeout_seconds: int,
    min_public_items: int,
    use_local_socket: bool,
) -> dict[str, object]:
    local_site = resolve_local_site_metadata(target) if use_local_socket else {"matched": False}
    mysql_socket = ""
    if local_site.get("matched") is True and local_site.get("mysql_socket_exists") is True:
        mysql_socket = _text(local_site.get("mysql_socket"))
    http_summary = fetch_http_summary(target.url, timeout_seconds=timeout_seconds)
    wp_summary = run_wp_summary(
        target=target,
        php_bin=php_bin,
        wp_bin=wp_bin,
        timeout_seconds=timeout_seconds,
        mysql_socket=mysql_socket,
    )
    sql_dump = collect_sql_dump_summary(target.path)
    evaluation = evaluate_candidate(
        target=target,
        http_summary=http_summary,
        wp_summary=wp_summary,
        min_public_items=min_public_items,
    )
    return {
        "label": target.label,
        "url": target.url,
        "path": str(target.path),
        "http": http_summary,
        "wordpress": wp_summary,
        "local_site": local_site,
        "sql_dump": sql_dump,
        "evaluation": evaluation,
    }


def build_report(
    *,
    targets: list[SiteTarget],
    php_bin: str,
    wp_bin: str,
    timeout_seconds: int,
    min_public_items: int,
    use_local_socket: bool,
    quiet: bool = True,
) -> dict[str, object]:
    sites = []
    for target in targets:
        if not quiet:
            print(f"[preflight] checking {target.label} ({target.url})", file=sys.stderr)
        site = collect_site(
            target=target,
            php_bin=php_bin,
            wp_bin=wp_bin,
            timeout_seconds=timeout_seconds,
            min_public_items=min_public_items,
            use_local_socket=use_local_socket,
        )
        sites.append(site)
        if not quiet:
            decision = _text(_dict(site.get("evaluation")).get("decision"))
            print(f"[preflight] {target.label}: {decision}", file=sys.stderr)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "boundary": {
            "mode": "read_only_preflight",
            "wordpress_writes": False,
            "cloud_runtime_execution": False,
            "site_knowledge_sync": False,
            "cloud_identity_provisioning": False,
        },
        "tooling": {
            "php_bin": php_bin,
            "wp_bin": wp_bin,
            "timeout_seconds": timeout_seconds,
            "min_public_items": min_public_items,
            "use_local_socket": use_local_socket,
        },
        "sites": sites,
        "overall_decision": "go"
        if sites and all(_dict(site.get("evaluation")).get("decision") == "go" for site in sites)
        else "no-go",
    }


def render_markdown(report: dict[str, object]) -> str:
    sites = _list(report.get("sites"))
    lines = [
        "# Live Site Read-Only Preflight Evidence",
        "",
        f"Generated at: `{_text(report.get('generated_at'))}`",
        "",
        "## Boundary",
        "",
        "This evidence was generated by read-only HTTP and WP-CLI inspection.",
        "It does not run Cloud runtime, Site Knowledge sync/search, Cloud identity",
        "provisioning, WordPress option writes, plugin activation, database import,",
        "search-replace, or content writes.",
        "",
        f"Overall decision: `{_text(report.get('overall_decision'))}`",
        "",
        "## Candidate Summary",
        "",
        "| Candidate | HTTP | Title | siteurl/home | Public posts/pages | Cloud addon | Decision |",
        "| --- | ---: | --- | --- | ---: | --- | --- |",
    ]
    for site in sites:
        wordpress = _dict(site.get("wordpress"))
        http = _dict(site.get("http"))
        settings = _dict(wordpress.get("cloud_settings"))
        counts = _dict(wordpress.get("counts"))
        siteurl_home = f"{_text(wordpress.get('siteurl'))} / {_text(wordpress.get('home'))}"
        cloud_state = "verified" if settings.get("verified") is True else "empty/unverified"
        lines.append(
            "| {label} | {status} | {title} | {siteurl_home} | {count} | "
            "{cloud_state} | {decision} |".format(
                label=f"`{_text(site.get('label'))}`",
                status=_text(http.get("status")),
                title=f"`{_text(http.get('title'))}`",
                siteurl_home=f"`{siteurl_home}`",
                count=_text(counts.get("publish_post_page")),
                cloud_state=cloud_state,
                decision=f"`{_text(_dict(site.get('evaluation')).get('decision'))}`",
            )
        )
    lines.extend(["", "## Detailed Evidence", ""])
    for site in sites:
        lines.extend(_render_site_detail(_dict(site)))
    lines.extend(
        [
            "## Required Before Live Execution",
            "",
            "1. Select one exact candidate hostname and WordPress root.",
            "2. Confirm browser, WP-CLI, `siteurl/home`, and active DB all match.",
            "3. Take a fresh database and files backup.",
            "4. Confirm Cloud addon install/activation path and current option snapshot.",
            "5. Provision a dedicated live Cloud identity and key, not a staging identity.",
            "6. Sample content/PII categories before Site Knowledge sync.",
            "7. Get second explicit approval naming the exact live site and exact action.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_site_detail(site: dict[str, object]) -> list[str]:
    wordpress = _dict(site.get("wordpress"))
    evaluation = _dict(site.get("evaluation"))
    sql_dump = _dict(site.get("sql_dump"))
    local_site = _dict(site.get("local_site"))
    plugins = _list(wordpress.get("active_plugins"))
    titles = _list(wordpress.get("sample_public_titles"))
    blockers = ", ".join(str(item) for item in _list(evaluation.get("blockers"))) or "none"
    warnings = ", ".join(str(item) for item in _list(evaluation.get("warnings"))) or "none"
    db_table = f"{_text(wordpress.get('db_name'))}` / `{_text(wordpress.get('table_prefix'))}"
    local_socket = "matched"
    if local_site.get("matched") is not True:
        local_socket = f"not matched ({_text(local_site.get('reason'))})"
    lines = [
        f"### `{_text(site.get('label'))}`",
        "",
        f"- URL: `{_text(site.get('url'))}`",
        f"- Path: `{_text(site.get('path'))}`",
        f"- Decision: `{_text(evaluation.get('decision'))}`",
        f"- Blockers: `{blockers}`",
        f"- Warnings: `{warnings}`",
        f"- Blog name: `{_text(wordpress.get('blogname'))}`",
        f"- DB/table: `{db_table}`",
        f"- WordPress version: `{_text(wordpress.get('wp_version'))}`",
        f"- Active theme: `{_text(wordpress.get('active_theme'))}`",
        f"- Local mapping: `{local_socket}`",
        f"- SQL dump: `exists={sql_dump.get('exists')}, bytes={sql_dump.get('bytes')}, "
        f"pattern_count={sql_dump.get('pattern_count')}`",
        "- Active plugins:",
    ]
    lines.extend([f"  - `{_text(plugin)}`" for plugin in plugins] or ["  - none"])
    lines.append("- Sample public titles:")
    lines.extend([f"  - `{_text(title)}`" for title in titles] or ["  - none"])
    lines.append("")
    return lines


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate read-only Npcink AI Cloud live-site preflight evidence."
    )
    parser.add_argument(
        "--site",
        action="append",
        nargs=3,
        metavar=("LABEL", "URL", "WORDPRESS_ROOT"),
        help="Candidate site. Repeatable. Defaults to wp/npcink/dbd Local sites.",
    )
    parser.add_argument("--php-bin", default="/opt/homebrew/bin/php")
    parser.add_argument("--wp-bin", default="/opt/homebrew/bin/wp")
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--min-public-items", type=int, default=10)
    parser.add_argument(
        "--no-local-socket",
        action="store_true",
        help="Do not auto-apply the matching Local app MySQL socket for WP-CLI.",
    )
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress logs on stderr.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    targets = (
        [parse_site_spec(values) for values in args.site]
        if args.site
        else [SiteTarget(label, url, Path(path)) for label, url, path in DEFAULT_SITES]
    )
    report = build_report(
        targets=targets,
        php_bin=args.php_bin,
        wp_bin=args.wp_bin,
        timeout_seconds=args.timeout_seconds,
        min_public_items=args.min_public_items,
        use_local_socket=not args.no_local_socket,
        quiet=args.quiet,
    )
    markdown = render_markdown(report)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown)
    if not args.json_out and not args.markdown_out:
        print(markdown)
    return 0 if report["overall_decision"] == "go" else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
