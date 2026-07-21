from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from app.dev.live_site_addon_install import APPROVAL_TEXT, approval_matches
from app.dev.live_site_addon_package import (
    DEFAULT_ADDON_ZIP,
    DEFAULT_NPCINK_SITE,
    inspect_addon_zip,
)
from app.dev.live_site_env import (
    INTERNAL_TOKEN_ENV_KEY,
    default_env_files,
    resolve_approval_text,
    resolve_env_secret,
)
from app.dev.live_site_identity_provision import (
    DEFAULT_ACCOUNT_ID,
    DEFAULT_BASE_URL,
    DEFAULT_KEY_LABEL,
    DEFAULT_SCOPES,
    DEFAULT_SITE_ID,
    DEFAULT_SITE_NAME,
    DEFAULT_SITE_URL,
    build_request_plan,
)
from app.dev.live_site_preflight import (
    SiteTarget,
    _dict,
    _list,
    _text,
    collect_site,
    parse_site_spec,
)

DEFAULT_OUTPUT_ROOT = Path(".tmp/live-site-stage1-readiness")
ALLOWED_PREFLIGHT_BLOCKERS = {"cloud_addon_unverified"}

SiteCollector = Callable[..., dict[str, object]]
HealthGetter = Callable[[str, dict[str, str], int], dict[str, object]]


def _normalize_base_url(value: str) -> str:
    return (value or DEFAULT_BASE_URL).strip().rstrip("/") + "/"


def get_json(url: str, headers: dict[str, str], timeout_seconds: int) -> dict[str, object]:
    request = Request(url, method="GET", headers={"Accept": "application/json", **headers})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
            status_code = int(getattr(response, "status", 0) or 0)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "status_code": exc.code, "error": body[:500]}
    except URLError as exc:
        return {"ok": False, "status_code": 0, "error": str(exc)}

    try:
        payload = json.loads(body or "{}")
    except json.JSONDecodeError:
        payload = {"raw_body": body[:500]}
    return {"ok": 200 <= status_code < 300, "status_code": status_code, "payload": payload}


def probe_cloud(
    *,
    base_url: str,
    internal_token: str,
    timeout_seconds: int,
    health_getter: HealthGetter = get_json,
) -> dict[str, object]:
    normalized = _normalize_base_url(base_url)
    live = health_getter(urljoin(normalized, "health/live"), {}, timeout_seconds)
    if not internal_token.strip():
        ready: dict[str, object] = {
            "ok": False,
            "skipped": True,
            "reason": "internal_token_missing",
        }
    else:
        ready = health_getter(
            urljoin(normalized, "health/ready"),
            {"X-Npcink-Internal-Token": internal_token},
            timeout_seconds,
        )
    return {
        "base_url": normalized.rstrip("/"),
        "live": live,
        "ready": ready,
    }


def preflight_stage1_failures(preflight: dict[str, object]) -> list[str]:
    failures: list[str] = []
    local_site = _dict(preflight.get("local_site"))
    if local_site.get("matched") is not True:
        failures.append("Local site metadata did not match the target")
    if local_site.get("mysql_socket_exists") is not True:
        failures.append("Local MySQL socket is missing")

    evaluation = _dict(preflight.get("evaluation"))
    blockers = {str(item) for item in _list(evaluation.get("blockers")) if str(item)}
    unexpected_blockers = sorted(blockers - ALLOWED_PREFLIGHT_BLOCKERS)
    if unexpected_blockers:
        failures.append(f"unexpected preflight blockers: {', '.join(unexpected_blockers)}")
    return failures


def addon_zip_failures(addon_zip: dict[str, object]) -> list[str]:
    failures: list[str] = []
    if addon_zip.get("exists") is not True:
        failures.append("addon zip is missing")
    if addon_zip.get("contains_main_plugin") is not True:
        failures.append("addon zip does not contain the main plugin file")
    return failures


def identity_plan_failures(
    *,
    account_id: str,
    site_id: str,
    site_name: str,
    site_url: str,
    key_label: str,
    scopes: list[str],
) -> list[str]:
    failures: list[str] = []
    fields = {
        "account_id": account_id,
        "site_id": site_id,
        "site_name": site_name,
        "site_url": site_url,
        "key_label": key_label,
    }
    for field, value in fields.items():
        if not value.strip():
            failures.append(f"{field} is required")
    if site_id == "site_npcink_trial":
        failures.append("site_npcink_trial must not be reused for live candidate identity")
    if not scopes:
        failures.append("at least one API key scope is required")
    return failures


def cloud_probe_failures(cloud: dict[str, object]) -> list[str]:
    failures: list[str] = []
    live = _dict(cloud.get("live"))
    ready = _dict(cloud.get("ready"))
    if live.get("ok") is not True:
        failures.append("Cloud /health/live is not reachable")
    if ready.get("ok") is not True:
        if ready.get("skipped") is True:
            failures.append("Cloud /health/ready was skipped because internal token is missing")
        else:
            failures.append("Cloud /health/ready is not ready")
    return failures


def build_readiness_report(
    *,
    target: SiteTarget,
    php_bin: str,
    wp_bin: str,
    addon_zip: Path,
    output_dir: Path,
    base_url: str,
    internal_token: str,
    account_id: str,
    site_id: str,
    site_name: str,
    site_url: str,
    key_label: str,
    scopes: list[str],
    timeout_seconds: int,
    approval_text: str,
    site_collector: SiteCollector = collect_site,
    health_getter: HealthGetter = get_json,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    preflight = site_collector(
        target=target,
        php_bin=php_bin,
        wp_bin=wp_bin,
        timeout_seconds=timeout_seconds,
        min_public_items=10,
        use_local_socket=True,
    )
    addon_zip_report = inspect_addon_zip(addon_zip)
    identity_failures = identity_plan_failures(
        account_id=account_id,
        site_id=site_id,
        site_name=site_name,
        site_url=site_url,
        key_label=key_label,
        scopes=scopes,
    )
    request_plan = build_request_plan(
        account_id=account_id,
        site_id=site_id,
        site_name=site_name,
        site_url=site_url,
        key_label=key_label,
        scopes=scopes,
        idempotency_prefix="npcink-live-readiness",
    )
    cloud = probe_cloud(
        base_url=base_url,
        internal_token=internal_token,
        timeout_seconds=timeout_seconds,
        health_getter=health_getter,
    )
    failures = {
        "preflight": preflight_stage1_failures(preflight),
        "addon_zip": addon_zip_failures(addon_zip_report),
        "identity_plan": identity_failures,
        "cloud": cloud_probe_failures(cloud),
    }
    all_failures = [
        f"{group}: {failure}"
        for group, items in failures.items()
        for failure in items
    ]
    prerequisites_ok = not all_failures
    report: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "live_site_stage1_readiness",
        "mode": "read_only_readiness",
        "ok": prerequisites_ok,
        "ready_for_stage1_execute_after_exact_approval": prerequisites_ok,
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
        "approval": {
            "required_for_stage1_execute": APPROVAL_TEXT,
            "provided": bool(approval_text),
            "matched": approval_matches(approval_text),
        },
        "target": {"label": target.label, "url": target.url, "path": str(target.path)},
        "preflight": preflight,
        "addon_zip": addon_zip_report,
        "cloud": cloud,
        "identity_plan": {
            "base_url": _normalize_base_url(base_url).rstrip("/"),
            "account_id": account_id,
            "site_id": site_id,
            "site_name": site_name,
            "site_url": site_url,
            "key_label": key_label,
            "scopes": scopes,
            "request_paths": [item.path for item in request_plan],
            "internal_token_present": bool(internal_token.strip()),
            "internal_token": {
                "present": bool(internal_token.strip()),
                "source": "caller",
                "length": len(internal_token.strip()),
            },
        },
        "failures": failures,
        "all_failures": all_failures,
        "next_action": next_action(
            prerequisites_ok=prerequisites_ok,
            approval_matched=approval_matches(approval_text),
        ),
    }
    (output_dir / "stage1-readiness-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "summary.md").write_text(render_markdown(report))
    return report


def next_action(*, prerequisites_ok: bool, approval_matched: bool) -> dict[str, object]:
    if not prerequisites_ok:
        return {
            "action": "fix_readiness_failures_before_stage1_execute",
            "approval_text": "",
        }
    if not approval_matched:
        return {
            "action": "run_stage1_execute_after_exact_approval",
            "approval_text": APPROVAL_TEXT,
        }
    return {
        "action": "stage1_execute_prerequisites_ready_and_approval_matched",
        "approval_text": "",
    }


def render_markdown(report: dict[str, object]) -> str:
    target = _dict(report.get("target"))
    boundary = _dict(report.get("boundary"))
    identity_plan = _dict(report.get("identity_plan"))
    internal_token = _dict(identity_plan.get("internal_token"))
    failures = _dict(report.get("failures"))
    next_step = _dict(report.get("next_action"))
    request_paths = ", ".join(str(item) for item in _list(identity_plan.get("request_paths")))
    lines = [
        "# Live Site Stage 1 Readiness",
        "",
        f"Generated at: `{_text(report.get('generated_at'))}`",
        f"OK: `{report.get('ok')}`",
        "",
        "## Boundary",
        "",
        "This report is read-only. It does not install plugins, write options,",
        "provision Cloud identity, call runtime, run Site Knowledge, enable",
        "monitoring, or write WordPress content.",
        "",
        f"- WordPress writes: `{boundary.get('wordpress_writes')}`",
        f"- Cloud identity provisioning: `{boundary.get('cloud_identity_provisioning')}`",
        f"- Public runtime provisioning: `{boundary.get('public_runtime_provisioning')}`",
        f"- Cloud runtime execution: `{boundary.get('cloud_runtime_execution')}`",
        f"- Site Knowledge sync/search: `{boundary.get('site_knowledge_sync')}`",
        "",
        "## Target",
        "",
        f"- Label: `{_text(target.get('label'))}`",
        f"- URL: `{_text(target.get('url'))}`",
        f"- Path: `{_text(target.get('path'))}`",
        "",
        "## Stage 1 Identity Plan",
        "",
        f"- Base URL: `{_text(identity_plan.get('base_url'))}`",
        f"- Account ID: `{_text(identity_plan.get('account_id'))}`",
        f"- Site ID: `{_text(identity_plan.get('site_id'))}`",
        f"- Internal token present: `{identity_plan.get('internal_token_present')}`",
        f"- Internal token source: `{_text(internal_token.get('source')) or 'caller'}`",
        f"- Internal token length: `{internal_token.get('length', 0)}`",
        f"- Request paths: `{request_paths}`",
        "",
        "## Failures",
        "",
    ]
    for group in ["preflight", "addon_zip", "identity_plan", "cloud"]:
        values = [str(item) for item in _list(failures.get(group))]
        lines.append(f"- {group}: `{', '.join(values) or 'none'}`")
    lines.extend(
        [
            "",
            "## Next Action",
            "",
            f"- Action: `{_text(next_step.get('action'))}`",
        ]
    )
    approval_text = _text(next_step.get("approval_text"))
    if approval_text:
        lines.extend(["- Approval text:", "", "```text", approval_text, "```"])
    lines.append("")
    return "\n".join(lines)


def parse_scopes(value: str) -> list[str]:
    return [scope.strip() for scope in value.split(",") if scope.strip()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate read-only readiness evidence before npcink.local Stage 1 execute."
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
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--internal-token", default="")
    parser.add_argument(
        "--env-file",
        action="append",
        type=Path,
        help=(
            "Env file to read for NPCINK_CLOUD_INTERNAL_AUTH_TOKEN. "
            "Defaults to .env and .env.local."
        ),
    )
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID)
    parser.add_argument("--site-id", default=DEFAULT_SITE_ID)
    parser.add_argument("--site-name", default=DEFAULT_SITE_NAME)
    parser.add_argument("--site-url", default=DEFAULT_SITE_URL)
    parser.add_argument("--key-label", default=DEFAULT_KEY_LABEL)
    parser.add_argument("--scopes", default=",".join(DEFAULT_SCOPES))
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--approval-text", default="")
    parser.add_argument("--approval-file", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    target = parse_site_spec(args.site) if args.site else DEFAULT_NPCINK_SITE
    suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or DEFAULT_OUTPUT_ROOT / f"{target.label}-readiness-{suffix}"
    internal_token = resolve_env_secret(
        cli_value=args.internal_token,
        env_key=INTERNAL_TOKEN_ENV_KEY,
        env_files=default_env_files(args.env_file),
    )
    try:
        approval_text = resolve_approval_text(
            cli_value=args.approval_text,
            approval_file=args.approval_file,
        )
    except ValueError as exc:
        print(json.dumps({"ok": False, "guard_error": str(exc)}), file=sys.stderr)
        return 2
    report = build_readiness_report(
        target=target,
        php_bin=args.php_bin,
        wp_bin=args.wp_bin,
        addon_zip=args.addon_zip,
        output_dir=output_dir,
        base_url=args.base_url,
        internal_token=internal_token.value,
        account_id=args.account_id,
        site_id=args.site_id,
        site_name=args.site_name,
        site_url=args.site_url,
        key_label=args.key_label,
        scopes=parse_scopes(args.scopes),
        timeout_seconds=args.timeout_seconds,
        approval_text=approval_text,
    )
    identity_plan = _dict(report.get("identity_plan"))
    identity_plan["internal_token"] = internal_token.redacted()
    (output_dir / "stage1-readiness-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "summary.md").write_text(render_markdown(report))
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "mode": report["mode"],
                "output_dir": str(output_dir),
                "next_action": report["next_action"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["ok"] is True else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
