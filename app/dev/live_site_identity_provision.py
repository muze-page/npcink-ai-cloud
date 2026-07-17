from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from app.dev.live_site_addon_install import APPROVAL_TEXT, approval_matches
from app.dev.live_site_env import (
    INTERNAL_TOKEN_ENV_KEY,
    default_env_files,
    resolve_approval_text,
    resolve_env_secret,
)
from app.domain.commercial.customer_api_keys import build_customer_api_key

DEFAULT_OUTPUT_ROOT = Path(".tmp/live-site-identity")
DEFAULT_BASE_URL = "http://127.0.0.1:8010"
DEFAULT_ACCOUNT_ID = "acct_npcink_local_live"
DEFAULT_SITE_ID = "site_npcink_local_live"
DEFAULT_SITE_NAME = "npcink.local live candidate"
DEFAULT_SITE_URL = "http://npcink.local/"
DEFAULT_KEY_LABEL = "npcink.local live candidate key"
DEFAULT_SCOPES = [
    "catalog:read",
    "runtime:resolve",
    "runtime:execute",
    "runtime:read",
    "stats:read",
    "entitlement:read",
]


class GuardError(RuntimeError):
    """Raised when identity provisioning must not run."""


@dataclass(frozen=True)
class InternalRequest:
    name: str
    method: str
    path: str
    payload: dict[str, object]
    idempotency_key: str


HttpPost = Callable[[str, dict[str, object], dict[str, str], int], dict[str, object]]


def build_request_plan(
    *,
    account_id: str,
    site_id: str,
    site_name: str,
    site_url: str,
    key_label: str,
    scopes: list[str],
    idempotency_prefix: str,
) -> list[InternalRequest]:
    metadata = {
        "source": "live_site_identity_provision",
        "candidate": "npcink.local",
    }
    return [
        InternalRequest(
            name="account_upsert",
            method="POST",
            path="/internal/service/accounts",
            payload={
                "account_id": account_id,
                "name": f"{site_name} account",
                "status": "active",
                "bind_default_free": True,
                "metadata": metadata,
            },
            idempotency_key=f"{idempotency_prefix}-account",
        ),
        InternalRequest(
            name="site_provision",
            method="POST",
            path="/internal/service/sites",
            payload={
                "site_id": site_id,
                "account_id": account_id,
                "name": site_name,
                "status": "provisioning",
                "site_url": site_url,
                "metadata": metadata,
            },
            idempotency_key=f"{idempotency_prefix}-site",
        ),
        InternalRequest(
            name="site_activate",
            method="POST",
            path=f"/internal/service/sites/{site_id}/activate",
            payload={},
            idempotency_key=f"{idempotency_prefix}-activate",
        ),
        InternalRequest(
            name="site_key_issue",
            method="POST",
            path=f"/internal/service/sites/{site_id}/keys",
            payload={
                "key_id": None,
                "secret": None,
                "scopes": scopes,
                "label": key_label,
                "metadata": metadata,
            },
            idempotency_key=f"{idempotency_prefix}-key",
        ),
    ]


def redact_payload(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in {"secret", "cloud_api_key", "signing_secret_ciphertext"}:
                redacted[key_text] = bool(str(item or ""))
            else:
                redacted[key_text] = redact_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    return value


def _normalize_base_url(value: str) -> str:
    return (value or DEFAULT_BASE_URL).strip().rstrip("/") + "/"


def post_json(
    url: str,
    payload: dict[str, object],
    headers: dict[str, str],
    timeout_seconds: int,
) -> dict[str, object]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **headers,
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            status = int(getattr(response, "status", 0) or 0)
    except HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status_code": exc.code,
            "error": response_body,
        }
    except URLError as exc:
        return {"ok": False, "status_code": 0, "error": str(exc)}

    try:
        parsed = json.loads(response_body or "{}")
    except json.JSONDecodeError:
        parsed = {"raw_body": response_body}
    return {"ok": 200 <= status < 300, "status_code": status, "response": parsed}


def execute_request_plan(
    *,
    base_url: str,
    internal_token: str,
    plan: list[InternalRequest],
    timeout_seconds: int,
    http_post: HttpPost = post_json,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for item in plan:
        url = urljoin(_normalize_base_url(base_url), item.path.lstrip("/"))
        result = http_post(
            url,
            item.payload,
            {
                "X-Npcink-Internal-Token": internal_token,
                "Idempotency-Key": item.idempotency_key,
            },
            timeout_seconds,
        )
        results.append(
            {
                "name": item.name,
                "method": item.method,
                "path": item.path,
                "idempotency_key": item.idempotency_key,
                "result": result,
            }
        )
        if result.get("ok") is not True:
            break
    return results


def extract_issued_key(results: list[dict[str, object]]) -> dict[str, str]:
    for result in results:
        if result.get("name") != "site_key_issue":
            continue
        response = result.get("result")
        if not isinstance(response, dict):
            continue
        envelope = response.get("response")
        if not isinstance(envelope, dict):
            continue
        data = envelope.get("data")
        if not isinstance(data, dict):
            continue
        site_id = str(data.get("site_id") or "")
        key_id = str(data.get("key_id") or "")
        secret = str(data.get("secret") or "")
        if site_id and key_id and secret:
            return {
                "site_id": site_id,
                "key_id": key_id,
                "secret": secret,
                "cloud_api_key": build_customer_api_key(
                    site_id=site_id,
                    key_id=key_id,
                    secret=secret,
                ),
            }
    return {}


def build_report(
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
    http_post: HttpPost = post_json,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if execute and not approval_matches(approval_text):
        raise GuardError("exact approval text did not match; no Cloud identity write was run")
    if execute and not internal_token.strip():
        raise GuardError("internal token is required for execute mode")
    if site_id == "site_npcink_trial":
        raise GuardError("site_npcink_trial must not be reused for live candidate identity")

    idempotency_prefix = f"npcink-live-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    plan = build_request_plan(
        account_id=account_id,
        site_id=site_id,
        site_name=site_name,
        site_url=site_url,
        key_label=key_label,
        scopes=scopes,
        idempotency_prefix=idempotency_prefix,
    )
    results = (
        execute_request_plan(
            base_url=base_url,
            internal_token=internal_token,
            plan=plan,
            timeout_seconds=timeout_seconds,
            http_post=http_post,
        )
        if execute
        else []
    )
    issued_key = extract_issued_key(results)
    if issued_key:
        (output_dir / "cloud-api-key.secret.json").write_text(
            json.dumps(issued_key, indent=2, sort_keys=True) + "\n"
        )

    report: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "execute" if execute else "prepare",
        "boundary": {
            "cloud_identity_provisioning": execute,
            "identity_owner": "internal_service_operations",
            "public_runtime_provisioning": False,
            "wordpress_writes": False,
            "cloud_runtime_execution": False,
            "site_knowledge_sync": False,
        },
        "approval": {
            "required_for_execute": APPROVAL_TEXT,
            "provided": bool(approval_text),
            "matched": approval_matches(approval_text),
        },
        "target": {
            "base_url": _normalize_base_url(base_url).rstrip("/"),
            "account_id": account_id,
            "site_id": site_id,
            "site_name": site_name,
            "site_url": site_url,
            "scopes": scopes,
        },
        "request_plan": [
            {
                "name": item.name,
                "method": item.method,
                "path": item.path,
                "payload": item.payload,
                "idempotency_key": item.idempotency_key,
            }
            for item in plan
        ],
        "results": redact_payload(results),
        "secret_file": str(output_dir / "cloud-api-key.secret.json") if issued_key else "",
        "issued_key": redact_payload(issued_key),
        "next_manual_steps": [
            "paste Cloud Base URL and Cloud API Key into the addon wp-admin Save and Verify form",
            "do not run runtime smoke until addon verification is confirmed",
            "do not run Site Knowledge sync/search until a separate approval names that action",
        ],
    }
    (output_dir / "identity-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "summary.md").write_text(render_markdown(report))
    return report


def render_markdown(report: dict[str, object]) -> str:
    boundary = _dict(report.get("boundary"))
    target = _dict(report.get("target"))
    lines = [
        "# Live Site Cloud Identity Provisioning",
        "",
        f"Generated at: `{report.get('generated_at')}`",
        f"Mode: `{report.get('mode')}`",
        "",
        "## Boundary",
        "",
        f"- Cloud identity provisioning: `{boundary.get('cloud_identity_provisioning')}`",
        f"- Identity owner: `{boundary.get('identity_owner')}`",
        f"- Public runtime provisioning: `{boundary.get('public_runtime_provisioning')}`",
        f"- WordPress writes: `{boundary.get('wordpress_writes')}`",
        f"- Cloud runtime execution: `{boundary.get('cloud_runtime_execution')}`",
        f"- Site Knowledge sync/search: `{boundary.get('site_knowledge_sync')}`",
        "",
        "## Target",
        "",
        f"- Base URL: `{target.get('base_url')}`",
        f"- Account ID: `{target.get('account_id')}`",
        f"- Site ID: `{target.get('site_id')}`",
        f"- WordPress URL: `{target.get('site_url')}`",
        f"- Secret file: `{report.get('secret_file') or 'not generated'}`",
        "",
        "## Next Manual Steps",
        "",
    ]
    lines.extend([f"- {item}" for item in _list(report.get("next_manual_steps"))])
    lines.append("")
    return "\n".join(lines)


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare or execute guarded Cloud identity provisioning for npcink.local."
    )
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
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approval-text", default="")
    parser.add_argument("--approval-file", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    scopes = [scope.strip() for scope in args.scopes.split(",") if scope.strip()]
    suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or DEFAULT_OUTPUT_ROOT / f"npcink-live-identity-{suffix}"
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
        report = build_report(
            base_url=args.base_url,
            internal_token=internal_token.value,
            account_id=args.account_id,
            site_id=args.site_id,
            site_name=args.site_name,
            site_url=args.site_url,
            key_label=args.key_label,
            scopes=scopes,
            output_dir=output_dir,
            execute=args.execute,
            approval_text=approval_text,
            timeout_seconds=args.timeout_seconds,
        )
        report["internal_token"] = internal_token.redacted()
        (output_dir / "identity-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n"
        )
    except (GuardError, ValueError) as exc:
        print(json.dumps({"ok": False, "guard_error": str(exc)}), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "ok": True,
                "mode": report["mode"],
                "output_dir": str(output_dir),
                "secret_file": report["secret_file"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
