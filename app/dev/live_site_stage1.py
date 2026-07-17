from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app.dev.live_site_addon_install import (
    APPROVAL_TEXT,
    approval_matches,
)
from app.dev.live_site_addon_install import (
    GuardError as AddonGuardError,
)
from app.dev.live_site_addon_install import (
    build_plan_report as build_addon_install_report,
)
from app.dev.live_site_addon_package import DEFAULT_ADDON_ZIP, DEFAULT_NPCINK_SITE
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
    redact_payload,
)
from app.dev.live_site_identity_provision import (
    GuardError as IdentityGuardError,
)
from app.dev.live_site_identity_provision import (
    build_report as build_identity_report,
)
from app.dev.live_site_preflight import SiteTarget, _dict, _text, parse_site_spec
from app.dev.live_site_stage1_readiness import (
    build_readiness_report as build_stage1_readiness_report,
)

DEFAULT_OUTPUT_ROOT = Path(".tmp/live-site-stage1")


class GuardError(RuntimeError):
    """Raised when stage 1 must not run write actions."""


class AddonInstallBuilder(Protocol):
    def __call__(
        self,
        *,
        target: SiteTarget,
        php_bin: str,
        wp_bin: str,
        addon_zip: Path,
        output_dir: Path,
        timeout_seconds: int,
        execute: bool,
        approval_text: str,
    ) -> dict[str, object]: ...


class IdentityBuilder(Protocol):
    def __call__(
        self,
        *,
        base_url: str,
        internal_token: str,
        account_id: str,
        site_id: str,
        site_name: str,
        site_url: str,
        key_label: str,
        scopes: list[str],
        output_dir: Path,
        execute: bool,
        approval_text: str,
        timeout_seconds: int,
    ) -> dict[str, object]: ...


class ReadinessBuilder(Protocol):
    def __call__(
        self,
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
    ) -> dict[str, object]: ...


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _stage_ok(report: dict[str, object]) -> bool:
    if report.get("mode") == "prepare":
        addon = _dict(report.get("addon_install"))
        identity = _dict(report.get("identity_provision"))
        return not _as_list(addon.get("prewrite_failures")) and identity.get("skipped") is not True
    return (
        report.get("addon_ready_for_manual_verify") is True
        and report.get("identity_ready_for_manual_verify") is True
    )


def _secret_file_from_identity(report: object) -> str:
    identity = _dict(report)
    return _text(identity.get("secret_file"))


def _identity_skipped(reason: str) -> dict[str, object]:
    return {"skipped": True, "reason": reason}


def validate_execute_readiness(report: dict[str, object]) -> list[str]:
    failures: list[str] = []
    if report.get("mode") != "read_only_readiness":
        failures.append("readiness report mode is not read_only_readiness")
    if report.get("ok") is not True:
        failures.append("readiness report is not ok")
    if report.get("ready_for_stage1_execute_after_exact_approval") is not True:
        failures.append("readiness did not mark stage 1 execute as ready")
    for failure in _as_list(report.get("all_failures")):
        failures.append(str(failure))
    boundary = _dict(report.get("boundary"))
    expected_false = [
        "wordpress_writes",
        "wordpress_option_writes",
        "cloud_identity_provisioning",
        "public_runtime_provisioning",
        "cloud_runtime_execution",
        "site_knowledge_sync",
        "site_knowledge_search",
        "content_writes",
        "monitoring_enabled",
    ]
    for key in expected_false:
        if boundary.get(key) is not False:
            failures.append(f"readiness boundary.{key} expected false")
    return failures


def build_stage_report(
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
    execute: bool,
    approval_text: str,
    addon_builder: AddonInstallBuilder = build_addon_install_report,
    identity_builder: IdentityBuilder = build_identity_report,
    readiness_builder: ReadinessBuilder = build_stage1_readiness_report,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if execute and not approval_matches(approval_text):
        raise GuardError("exact approval text did not match; stage 1 writes were not run")

    readiness_report: dict[str, object] = {
        "skipped": True,
        "reason": "prepare_only",
    }
    if execute:
        readiness_report = readiness_builder(
            target=target,
            php_bin=php_bin,
            wp_bin=wp_bin,
            addon_zip=addon_zip,
            output_dir=output_dir / "readiness",
            base_url=base_url,
            internal_token=internal_token,
            account_id=account_id,
            site_id=site_id,
            site_name=site_name,
            site_url=site_url,
            key_label=key_label,
            scopes=scopes,
            timeout_seconds=timeout_seconds,
            approval_text=approval_text,
        )
        readiness_failures = validate_execute_readiness(readiness_report)
        if readiness_failures:
            raise GuardError("stage 1 readiness failed: " + "; ".join(readiness_failures))

    try:
        addon_report = addon_builder(
            target=target,
            php_bin=php_bin,
            wp_bin=wp_bin,
            addon_zip=addon_zip,
            output_dir=output_dir / "addon-install",
            timeout_seconds=timeout_seconds,
            execute=execute,
            approval_text=approval_text if execute else "",
        )
    except AddonGuardError as exc:
        raise GuardError(str(exc)) from exc

    addon_active = addon_report.get("addon_active") is True
    identity_report: dict[str, object] | None = None
    identity_status: dict[str, object]

    if execute and not addon_active:
        identity_status = _identity_skipped(
            "addon install did not verify active; identity not provisioned"
        )
    else:
        try:
            identity_report = identity_builder(
                base_url=base_url,
                internal_token=internal_token if execute else "",
                account_id=account_id,
                site_id=site_id,
                site_name=site_name,
                site_url=site_url,
                key_label=key_label,
                scopes=scopes,
                output_dir=output_dir / "identity",
                execute=execute,
                approval_text=approval_text if execute else "",
                timeout_seconds=timeout_seconds,
            )
        except IdentityGuardError as exc:
            raise GuardError(str(exc)) from exc
        identity_status = identity_report

    secret_file = _secret_file_from_identity(identity_report)
    report: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "execute" if execute else "prepare",
        "stage": "live_site_cloud_addon_stage1",
        "target": {"label": target.label, "url": target.url, "path": str(target.path)},
        "boundary": {
            "wordpress_writes": execute,
            "wordpress_write_scope": ["plugin_install", "plugin_activate"] if execute else [],
            "wordpress_option_writes": False,
            "cloud_identity_provisioning": execute and addon_active,
            "identity_owner": "internal_service_operations",
            "public_runtime_provisioning": False,
            "cloud_runtime_execution": False,
            "runtime_smoke": False,
            "site_knowledge_sync": False,
            "site_knowledge_search": False,
            "content_writes": False,
            "monitoring_enabled": False,
            "readiness_checked": execute,
        },
        "approval": {
            "required_for_execute": APPROVAL_TEXT,
            "provided": bool(approval_text),
            "matched": approval_matches(approval_text),
        },
        "outputs": {
            "stage_dir": str(output_dir),
            "addon_install_dir": str(output_dir / "addon-install"),
            "identity_dir": str(output_dir / "identity"),
            "stage_report": str(output_dir / "stage1-report.json"),
            "summary": str(output_dir / "summary.md"),
            "readiness_report": str(output_dir / "readiness" / "stage1-readiness-report.json")
            if execute
            else "",
            "secret_file": secret_file,
        },
        "readiness": redact_payload(readiness_report),
        "addon_install": redact_payload(addon_report),
        "identity_provision": redact_payload(identity_status),
        "addon_ready_for_manual_verify": addon_active,
        "identity_ready_for_manual_verify": bool(secret_file) if execute else True,
        "next_manual_steps": next_manual_steps(
            execute=execute,
            addon_active=addon_active,
            secret_file=secret_file,
        ),
    }
    report["ok"] = _stage_ok(report)

    (output_dir / "stage1-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "summary.md").write_text(render_markdown(report))
    return report


def next_manual_steps(*, execute: bool, addon_active: bool, secret_file: str) -> list[str]:
    if not execute:
        return [
            "review addon-install and identity prepare reports under this stage directory",
            "use the exact approval text before running stage 1 in execute mode",
            "stage 1 execute still stops before addon settings save, runtime smoke, "
            "and Site Knowledge",
        ]
    if not addon_active:
        return [
            "fix addon install/activation before provisioning Cloud identity",
            "do not save Cloud settings, run runtime smoke, or run Site Knowledge",
        ]
    if not secret_file:
        return [
            "fix Cloud identity/key issuance before opening the addon Save and Verify form",
            "do not run runtime smoke or Site Knowledge",
        ]
    return [
        f"read the customer-facing Cloud API Key from {secret_file}",
        "open npcink.local wp-admin and use the addon Save and Verify form",
        "leave monitoring disabled",
        "run read-only preflight after Save and Verify",
        "stop before runtime smoke or Site Knowledge sync/search",
    ]


def render_markdown(report: dict[str, object]) -> str:
    target = _dict(report.get("target"))
    boundary = _dict(report.get("boundary"))
    outputs = _dict(report.get("outputs"))
    write_scope = ", ".join(str(item) for item in _as_list(boundary.get("wordpress_write_scope")))
    lines = [
        "# Live Site Stage 1: Addon Install + Cloud Identity",
        "",
        f"Generated at: `{_text(report.get('generated_at'))}`",
        f"Mode: `{_text(report.get('mode'))}`",
        f"OK: `{report.get('ok')}`",
        "",
        "## Target",
        "",
        f"- Label: `{_text(target.get('label'))}`",
        f"- URL: `{_text(target.get('url'))}`",
        f"- Path: `{_text(target.get('path'))}`",
        "",
        "## Boundary",
        "",
        f"- WordPress writes: `{boundary.get('wordpress_writes')}`",
        f"- WordPress write scope: `{write_scope or 'none'}`",
        f"- WordPress option writes: `{boundary.get('wordpress_option_writes')}`",
        f"- Cloud identity provisioning: `{boundary.get('cloud_identity_provisioning')}`",
        f"- Identity owner: `{boundary.get('identity_owner')}`",
        f"- Public runtime provisioning: `{boundary.get('public_runtime_provisioning')}`",
        f"- Runtime smoke: `{boundary.get('runtime_smoke')}`",
        f"- Site Knowledge sync: `{boundary.get('site_knowledge_sync')}`",
        f"- Site Knowledge search: `{boundary.get('site_knowledge_search')}`",
        f"- Content writes: `{boundary.get('content_writes')}`",
        f"- Monitoring enabled: `{boundary.get('monitoring_enabled')}`",
        f"- Readiness checked: `{boundary.get('readiness_checked')}`",
        "",
        "## Outputs",
        "",
        f"- Stage report: `{outputs.get('stage_report')}`",
        f"- Addon install dir: `{outputs.get('addon_install_dir')}`",
        f"- Identity dir: `{outputs.get('identity_dir')}`",
        f"- Readiness report: `{outputs.get('readiness_report') or 'not generated'}`",
        f"- Secret file: `{outputs.get('secret_file') or 'not generated'}`",
        "",
        "## Readiness",
        "",
        f"- Addon ready for manual verify: `{report.get('addon_ready_for_manual_verify')}`",
        f"- Identity ready for manual verify: `{report.get('identity_ready_for_manual_verify')}`",
        "",
        "## Next Manual Steps",
        "",
    ]
    lines.extend([f"- {step}" for step in _as_list(report.get("next_manual_steps"))])
    lines.append("")
    return "\n".join(lines)


def parse_scopes(value: str | Sequence[str]) -> list[str]:
    if isinstance(value, str):
        return [scope.strip() for scope in value.split(",") if scope.strip()]
    return [str(scope).strip() for scope in value if str(scope).strip()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare or execute the guarded npcink.local stage 1 Cloud addon and identity step."
        )
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
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approval-text", default="")
    parser.add_argument("--approval-file", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    target = parse_site_spec(args.site) if args.site else DEFAULT_NPCINK_SITE
    suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or DEFAULT_OUTPUT_ROOT / f"{target.label}-stage1-{suffix}"
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
        report = build_stage_report(
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
            execute=args.execute,
            approval_text=approval_text,
        )
        report["internal_token"] = internal_token.redacted()
        (output_dir / "stage1-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n"
        )
    except (GuardError, ValueError) as exc:
        print(json.dumps({"ok": False, "guard_error": str(exc)}), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "ok": report["ok"],
                "mode": report["mode"],
                "output_dir": str(output_dir),
                "addon_ready_for_manual_verify": report["addon_ready_for_manual_verify"],
                "identity_ready_for_manual_verify": report["identity_ready_for_manual_verify"],
                "secret_file": _dict(report.get("outputs")).get("secret_file", ""),
            }
        )
    )
    return 0 if report["ok"] is True else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
