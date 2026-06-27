from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.dev.live_site_preflight import _dict, _list, _text
from app.dev.live_site_stage1_acceptance import DEFAULT_STAGE_REPORT, load_json

DEFAULT_OUTPUT_ROOT = Path(".tmp/live-site-save-verify-handoff")
ADDON_ADMIN_PAGE_SLUG = "npcink-cloud-addon"


def _principal_base(url: str) -> str:
    return url.rstrip("/") + "/wp-admin/"


def _addon_admin_url(url: str) -> str:
    return _principal_base(url) + "admin.php?page=" + ADDON_ADMIN_PAGE_SLUG


def _secret_path_from_stage(stage_report: dict[str, object]) -> Path | None:
    outputs = _dict(stage_report.get("outputs"))
    value = _text(outputs.get("secret_file"))
    return Path(value) if value else None


def _secret_summary(path: Path | None) -> tuple[dict[str, object], list[str]]:
    failures: list[str] = []
    summary: dict[str, object] = {
        "path": str(path) if path is not None else "",
        "exists": False,
        "json_object": False,
        "site_id": "",
        "key_id": "",
        "site_id_present": False,
        "key_id_present": False,
        "secret_present": False,
        "cloud_api_key_present": False,
        "cloud_api_key_length": 0,
    }

    if path is None:
        failures.append("stage report outputs.secret_file is empty")
        return summary, failures
    if not path.exists():
        failures.append(f"secret file does not exist: {path}")
        return summary, failures
    if path.stat().st_size <= 0:
        failures.append(f"secret file is empty: {path}")
        summary["exists"] = True
        return summary, failures

    summary["exists"] = True
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        failures.append(f"secret file is not valid JSON: {exc}")
        return summary, failures
    if not isinstance(raw, dict):
        failures.append("secret file JSON root is not an object")
        return summary, failures

    summary["json_object"] = True
    site_id = _text(raw.get("site_id"))
    key_id = _text(raw.get("key_id"))
    secret = _text(raw.get("secret"))
    cloud_api_key = _text(raw.get("cloud_api_key"))
    summary.update(
        {
            "site_id": site_id,
            "key_id": key_id,
            "site_id_present": bool(site_id),
            "key_id_present": bool(key_id),
            "secret_present": bool(secret),
            "cloud_api_key_present": bool(cloud_api_key),
            "cloud_api_key_length": len(cloud_api_key),
        }
    )
    for key in ("site_id", "key_id", "secret", "cloud_api_key"):
        if not _text(raw.get(key)):
            failures.append(f"secret file missing {key}")
    return summary, failures


def _stage_target(stage_report: dict[str, object]) -> dict[str, object]:
    target = _dict(stage_report.get("target"))
    return {
        "label": _text(target.get("label")),
        "url": _text(target.get("url")),
        "path": _text(target.get("path")),
    }


def _identity_target(stage_report: dict[str, object]) -> dict[str, object]:
    identity = _dict(stage_report.get("identity_provision"))
    target = _dict(identity.get("target"))
    return {
        "base_url": _text(target.get("base_url")),
        "account_id": _text(target.get("account_id")),
        "site_id": _text(target.get("site_id")),
        "site_name": _text(target.get("site_name")),
        "wordpress_url": _text(target.get("wordpress_url")),
        "scopes": _list(target.get("scopes")),
    }


def _stage_validation_failures(stage_report: dict[str, object]) -> list[str]:
    failures: list[str] = []
    if stage_report.get("mode") != "execute":
        failures.append(f"stage report mode is not execute: {stage_report.get('mode')!r}")
    if stage_report.get("ok") is not True:
        failures.append("stage report ok is not true")
    if stage_report.get("addon_ready_for_manual_verify") is not True:
        failures.append("addon is not ready for manual verify")
    if stage_report.get("identity_ready_for_manual_verify") is not True:
        failures.append("identity is not ready for manual verify")

    boundary = _dict(stage_report.get("boundary"))
    expected_false = {
        "wordpress_option_writes": False,
        "public_runtime_provisioning": False,
        "cloud_runtime_execution": False,
        "runtime_smoke": False,
        "site_knowledge_sync": False,
        "site_knowledge_search": False,
        "content_writes": False,
        "monitoring_enabled": False,
    }
    for key, expected in expected_false.items():
        if boundary.get(key) is not expected:
            failures.append(f"stage boundary.{key} expected {expected!r}")
    return failures


def build_handoff_report(
    *,
    stage_report_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stage_report = load_json(stage_report_path)
    target = _stage_target(stage_report)
    identity_target = _identity_target(stage_report)
    secret_file = _secret_path_from_stage(stage_report)
    secret_summary, secret_failures = _secret_summary(secret_file)
    failures = _stage_validation_failures(stage_report) + secret_failures
    ready = not failures
    site_url = _text(target.get("url"))

    report: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "live_site_stage1_save_verify_handoff",
        "mode": "read_only_handoff",
        "target": target,
        "identity_target": identity_target,
        "boundary": {
            "wordpress_writes": False,
            "wordpress_option_writes": False,
            "cloud_identity_provisioning": False,
            "public_runtime_provisioning": False,
            "cloud_runtime_execution": False,
            "runtime_smoke": False,
            "site_knowledge_sync": False,
            "site_knowledge_search": False,
            "content_writes": False,
            "monitoring_enabled": False,
        },
        "inputs": {
            "stage_report": str(stage_report_path),
            "secret_file": str(secret_file) if secret_file is not None else "",
        },
        "admin": {
            "login_url": _principal_base(site_url) if site_url else "",
            "addon_admin_url": _addon_admin_url(site_url) if site_url else "",
            "menu_path": "Npcink AI > Cloud Addon",
            "save_button_label": "Save and Verify",
            "base_url_to_paste": _text(identity_target.get("base_url")),
            "cloud_api_key_source": str(secret_file) if secret_file is not None else "",
            "cloud_api_key_value_redacted": True,
            "monitoring_should_remain_disabled": True,
        },
        "secret_file": secret_summary,
        "failures": failures,
        "ready_for_manual_save_verify": ready,
        "next_steps": next_steps(ready=ready),
    }
    (output_dir / "save-verify-handoff-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "summary.md").write_text(render_markdown(report))
    return report


def next_steps(*, ready: bool) -> list[str]:
    if ready:
        return [
            "open the addon admin URL and complete Save and Verify manually",
            "paste the Cloud Base URL from this report",
            "copy the Cloud API Key only from the local secret file; do not share it",
            "leave monitoring disabled",
            "after the UI reports saved and verified, run the read-only Stage 1 acceptance helper",
        ]
    return [
        "fix the failed handoff checks before opening the addon Save and Verify form",
        "do not paste Cloud API Key, run runtime smoke, run Site Knowledge, or write content yet",
    ]


def render_markdown(report: dict[str, object]) -> str:
    target = _dict(report.get("target"))
    admin = _dict(report.get("admin"))
    secret = _dict(report.get("secret_file"))
    identity_target = _dict(report.get("identity_target"))
    failures = [str(item) for item in _list(report.get("failures"))]
    lines = [
        "# Live Site Save and Verify Handoff",
        "",
        f"Generated at: `{_text(report.get('generated_at'))}`",
        f"Ready for manual Save and Verify: `{report.get('ready_for_manual_save_verify')}`",
        "",
        "## Target",
        "",
        f"- Label: `{_text(target.get('label'))}`",
        f"- URL: `{_text(target.get('url'))}`",
        f"- Path: `{_text(target.get('path'))}`",
        "",
        "## Admin Action",
        "",
        f"- Login URL: `{_text(admin.get('login_url'))}`",
        f"- Addon URL: `{_text(admin.get('addon_admin_url'))}`",
        f"- Menu path: `{_text(admin.get('menu_path'))}`",
        f"- Button: `{_text(admin.get('save_button_label'))}`",
        f"- Cloud Base URL: `{_text(admin.get('base_url_to_paste'))}`",
        f"- Cloud API Key source: `{_text(admin.get('cloud_api_key_source'))}`",
        "- Cloud API Key value: `redacted`",
        "- Monitoring: `leave disabled`",
        "",
        "## Cloud Identity",
        "",
        f"- Account ID: `{_text(identity_target.get('account_id'))}`",
        f"- Site ID: `{_text(identity_target.get('site_id'))}`",
        f"- Secret file site ID: `{_text(secret.get('site_id'))}`",
        f"- Secret file key ID: `{_text(secret.get('key_id'))}`",
        f"- Cloud API Key present: `{secret.get('cloud_api_key_present')}`",
        f"- Cloud API Key length: `{secret.get('cloud_api_key_length')}`",
        f"- Secret present: `{secret.get('secret_present')}`",
        "",
        "## Boundary",
        "",
        "This handoff is read-only. It does not write WordPress options, provision",
        "Cloud identity, call Cloud runtime, run Site Knowledge sync/search, enable",
        "monitoring, or write content.",
        "",
        "## Failures",
        "",
    ]
    if failures:
        lines.extend([f"- {failure}" for failure in failures])
    else:
        lines.append("- none")
    lines.extend(["", "## Next Steps", ""])
    lines.extend([f"- {step}" for step in _list(report.get("next_steps"))])
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the read-only wp-admin Save and Verify handoff after Stage 1 execute."
        )
    )
    parser.add_argument("--stage-report", type=Path, default=DEFAULT_STAGE_REPORT)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or DEFAULT_OUTPUT_ROOT / f"npcink-handoff-{suffix}"
    try:
        report = build_handoff_report(
            stage_report_path=args.stage_report,
            output_dir=output_dir,
        )
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "ok": report["ready_for_manual_save_verify"],
                "mode": report["mode"],
                "output_dir": str(output_dir),
                "admin_url": _dict(report.get("admin")).get("addon_admin_url", ""),
                "failed_checks": report["failures"],
            }
        )
    )
    return 0 if report["ready_for_manual_save_verify"] is True else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
