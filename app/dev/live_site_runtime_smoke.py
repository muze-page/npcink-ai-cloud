from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from app.core.security import build_body_digest, build_canonical_request, build_hmac_signature
from app.dev.live_site_env import resolve_approval_text
from app.dev.live_site_preflight import _dict, _list, _text

APPROVAL_TEXT = (
    "我明确批准在 npcink.local 运行一次 Cloud runtime resolve smoke；本次不运行 runtime "
    "execute，不运行 Site Knowledge sync/search，不写 WordPress 内容，不启用 monitoring。"
)
DEFAULT_ACCEPTANCE_REPORT = Path(
    ".tmp/live-site-stage1-acceptance/npcink-stage1/acceptance-report.json"
)
DEFAULT_STAGE_REPORT = Path(".tmp/live-site-stage1/npcink-stage1/stage1-report.json")
DEFAULT_OUTPUT_ROOT = Path(".tmp/live-site-runtime-smoke")
DEFAULT_BASE_URL = "http://127.0.0.1:8010"

HttpPost = Callable[[str, dict[str, object], dict[str, str], int], dict[str, object]]


class GuardError(RuntimeError):
    """Raised when runtime smoke must not run."""


def normalize_approval(value: str) -> str:
    return "".join(value.split())


def approval_matches(value: str) -> bool:
    return normalize_approval(value) == normalize_approval(APPROVAL_TEXT)


def load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardError(f"could not read JSON report {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GuardError(f"JSON report {path} must be an object")
    return value


def load_secret_payload(path: Path) -> dict[str, str]:
    payload = load_json(path)
    site_id = _text(payload.get("site_id"))
    key_id = _text(payload.get("key_id"))
    secret = _text(payload.get("secret"))
    if not site_id or not key_id or not secret:
        raise GuardError("secret file must include site_id, key_id, and secret")
    return {"site_id": site_id, "key_id": key_id, "secret": secret}


def build_traceparent(trace_id: str) -> str:
    normalized = "".join(ch for ch in trace_id.lower() if ch in "0123456789abcdef")
    if len(normalized) != 32:
        normalized = normalized.ljust(32, "0")[:32]
    return f"00-{normalized}-0000000000000000-01"


def build_runtime_resolve_payload(*, site_id: str, trace_id: str) -> dict[str, object]:
    return {
        "site_id": site_id,
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "canonical_run_id": f"npcink_runtime_resolve_smoke_{trace_id[:12]}",
        "skill_id": "content_summary_seo",
        "workflow_id": "content_summary_seo_completion",
        "contract_version": "v1",
        "channel": "live-site-smoke",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "data_classification": "internal",
        "storage_mode": "result_only",
        "timeout_seconds": 60,
        "retry_max": 0,
        "retention_ttl": 3600,
        "task_backend": {
            "enabled": False,
            "mode": "inline",
            "callback_mode": "none",
            "polling_interval_sec": 0,
        },
        "profile_id": "text.balanced",
        "trace_id": trace_id,
        "input": {"messages": [{"role": "user", "content": "resolve smoke"}]},
        "policy": {"allow_fallback": True},
    }


def build_signed_headers(
    *,
    method: str,
    path: str,
    site_id: str,
    key_id: str,
    secret: str,
    body: bytes,
    trace_id: str,
    idempotency_key: str,
    timestamp: str,
    nonce: str,
) -> dict[str, str]:
    traceparent = build_traceparent(trace_id)
    canonical_request = build_canonical_request(
        method=method,
        path=path,
        query="",
        site_id=site_id,
        key_id=key_id,
        timestamp=timestamp,
        nonce=nonce,
        idempotency_key=idempotency_key,
        traceparent=traceparent,
        body_digest=build_body_digest(body),
    )
    return {
        "content-type": "application/json",
        "accept": "application/json",
        "X-Npcink-Site-Id": site_id,
        "X-Npcink-Key-Id": key_id,
        "X-Npcink-Timestamp": timestamp,
        "X-Npcink-Nonce": nonce,
        "X-Npcink-Signature": build_hmac_signature(secret, canonical_request),
        "Idempotency-Key": idempotency_key,
        "traceparent": traceparent,
    }


def post_json(
    url: str,
    payload: dict[str, object],
    headers: dict[str, str],
    timeout_seconds: int,
) -> dict[str, object]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = Request(url, data=body, method="POST", headers=headers)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(getattr(response, "status", 0) or 0)
            response_body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status_code": exc.code,
            "response": _parse_json_body(response_body),
        }
    except URLError as exc:
        return {"ok": False, "status_code": 0, "error": str(exc)}
    return {
        "ok": 200 <= status_code < 300,
        "status_code": status_code,
        "response": _parse_json_body(response_body),
    }


def _parse_json_body(value: str) -> object:
    try:
        return json.loads(value or "{}")
    except json.JSONDecodeError:
        return {"raw_body": value[:1000]}


def validate_acceptance(report: dict[str, object]) -> list[str]:
    failures: list[str] = []
    if report.get("ready_for_runtime_smoke_approval") is not True:
        failures.append("stage1 acceptance is not ready for runtime smoke approval")
    boundary = _dict(report.get("boundary"))
    if boundary.get("cloud_runtime_execution") is not False:
        failures.append("acceptance report did not preserve cloud_runtime_execution=false")
    if boundary.get("site_knowledge_sync") is not False:
        failures.append("acceptance report did not preserve site_knowledge_sync=false")
    if boundary.get("content_writes") is not False:
        failures.append("acceptance report did not preserve content_writes=false")
    failed_checks = [
        _text(item.get("name"))
        for item in (_dict(raw) for raw in _list(report.get("checks")))
        if item.get("ok") is not True
    ]
    if failed_checks:
        failures.append("acceptance checks failed: " + ", ".join(failed_checks))
    return failures


def validate_resolve_response(result: dict[str, object]) -> list[str]:
    failures: list[str] = []
    if result.get("ok") is not True:
        failures.append(f"runtime resolve HTTP failed: {result.get('status_code')}")
        return failures
    response = _dict(result.get("response"))
    if response.get("status") != "ok":
        failures.append(f"runtime resolve envelope was not ok: {response.get('error_code')}")
    data = _dict(response.get("data"))
    required = {
        "profile_id",
        "execution_kind",
        "policy",
        "selected_candidate",
        "candidates",
        "execution_context",
        "run_lifecycle",
        "task_backend",
    }
    missing = sorted(required - set(data.keys()))
    if missing:
        failures.append("runtime resolve data missing keys: " + ", ".join(missing))
    execution_context = _dict(data.get("execution_context"))
    if execution_context.get("execution_pattern") != "inline":
        failures.append("runtime resolve did not preserve execution_pattern=inline")
    if execution_context.get("storage_mode") != "result_only":
        failures.append("runtime resolve did not preserve storage_mode=result_only")
    return failures


def build_smoke_report(
    *,
    acceptance_report_path: Path,
    stage_report_path: Path,
    output_dir: Path,
    base_url: str,
    timeout_seconds: int,
    execute: bool,
    approval_text: str,
    http_post: HttpPost = post_json,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if execute and not approval_matches(approval_text):
        raise GuardError("exact approval text did not match; runtime resolve smoke was not run")

    acceptance = load_json(acceptance_report_path)
    stage_report = load_json(stage_report_path)
    acceptance_failures = validate_acceptance(acceptance)
    outputs = _dict(stage_report.get("outputs"))
    secret_file = Path(_text(outputs.get("secret_file")))
    trace_id = "npcinkresolve" + hashlib.sha256(str(datetime.now(UTC)).encode()).hexdigest()[:20]
    payload_site_id = _text(_dict(stage_report.get("target")).get("site_id"))
    if not payload_site_id:
        identity_target = _dict(_dict(stage_report.get("identity_provision")).get("target"))
        payload_site_id = _text(identity_target.get("site_id"))
    secret_payload: dict[str, str] = {}
    if execute:
        if acceptance_failures:
            raise GuardError("; ".join(acceptance_failures))
        secret_payload = load_secret_payload(secret_file)
        payload_site_id = secret_payload["site_id"]
    elif secret_file:
        payload_site_id = payload_site_id or "from-secret-file"

    payload = build_runtime_resolve_payload(
        site_id=payload_site_id or "site_npcink_local_live",
        trace_id=trace_id,
    )
    result: dict[str, object] = {"skipped": True, "reason": "prepare_only"}
    response_failures: list[str] = []
    if execute:
        path = "/v1/runtime/resolve"
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        timestamp = str(int(datetime.now(UTC).timestamp()))
        idempotency_key = f"npcink-runtime-resolve-smoke-{trace_id[:16]}"
        nonce = f"nonce-{trace_id[:24]}"
        headers = build_signed_headers(
            method="POST",
            path=path,
            site_id=secret_payload["site_id"],
            key_id=secret_payload["key_id"],
            secret=secret_payload["secret"],
            body=body,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            timestamp=timestamp,
            nonce=nonce,
        )
        result = http_post(
            urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
            payload,
            headers,
            timeout_seconds,
        )
        response_failures = validate_resolve_response(result)

    report: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "execute" if execute else "prepare",
        "stage": "live_site_runtime_resolve_smoke",
        "boundary": {
            "wordpress_writes": False,
            "wordpress_option_writes": False,
            "cloud_identity_provisioning": False,
            "public_runtime_provisioning": False,
            "runtime_resolve_smoke": execute,
            "runtime_execute": False,
            "provider_execution": False,
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
        "inputs": {
            "acceptance_report": str(acceptance_report_path),
            "stage_report": str(stage_report_path),
            "secret_file": str(secret_file) if _text(outputs.get("secret_file")) else "",
            "base_url": base_url,
        },
        "request_plan": {
            "method": "POST",
            "path": "/v1/runtime/resolve",
            "site_id": payload.get("site_id"),
            "ability_name": payload.get("ability_name"),
            "execution_pattern": payload.get("execution_pattern"),
            "storage_mode": payload.get("storage_mode"),
            "policy": payload.get("policy"),
        },
        "acceptance_failures": acceptance_failures,
        "runtime_result": redact_runtime_result(result),
        "response_failures": response_failures,
        "ok": execute and not acceptance_failures and not response_failures,
        "next_steps": next_steps(
            execute=execute,
            ok=not response_failures and not acceptance_failures,
        ),
    }
    (output_dir / "runtime-resolve-smoke-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "summary.md").write_text(render_markdown(report))
    return report


def redact_runtime_result(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in {"x-npcink-signature", "signature", "secret", "cloud_api_key"}:
                redacted[str(key)] = bool(str(item or ""))
            else:
                redacted[str(key)] = redact_runtime_result(item)
        return redacted
    if isinstance(value, list):
        return [redact_runtime_result(item) for item in value]
    return value


def next_steps(*, execute: bool, ok: bool) -> list[str]:
    if not execute:
        if ok:
            return [
                "use the exact runtime resolve smoke approval text before execute mode",
                "do not run /v1/runtime/execute, Site Knowledge, or content writes",
                "rerun this helper with --execute only after the separate approval is provided",
            ]
        return [
            "run Stage 1 execute and wp-admin Save and Verify first",
            "rerun Stage 1 acceptance until ready_for_runtime_smoke_approval=true",
            "use the exact runtime resolve smoke approval text before execute mode",
        ]
    if ok:
        return [
            "record the resolve smoke report as evidence",
            "request separate approval before any /v1/runtime/execute smoke",
            "do not run Site Knowledge sync/search or WordPress content writes",
        ]
    return [
        "fix failed acceptance or runtime resolve checks before any execute smoke",
        "do not run /v1/runtime/execute, Site Knowledge, or content writes",
    ]


def render_markdown(report: dict[str, object]) -> str:
    boundary = _dict(report.get("boundary"))
    acceptance_failures = (
        ", ".join(_text(item) for item in _list(report.get("acceptance_failures"))) or "none"
    )
    response_failures = (
        ", ".join(_text(item) for item in _list(report.get("response_failures"))) or "none"
    )
    lines = [
        "# Live Site Runtime Resolve Smoke",
        "",
        f"Generated at: `{_text(report.get('generated_at'))}`",
        f"Mode: `{_text(report.get('mode'))}`",
        f"OK: `{report.get('ok')}`",
        "",
        "## Boundary",
        "",
        f"- Runtime resolve smoke: `{boundary.get('runtime_resolve_smoke')}`",
        f"- Runtime execute: `{boundary.get('runtime_execute')}`",
        f"- Provider execution: `{boundary.get('provider_execution')}`",
        f"- WordPress writes: `{boundary.get('wordpress_writes')}`",
        f"- Site Knowledge sync/search: `{boundary.get('site_knowledge_sync')}` / "
        f"`{boundary.get('site_knowledge_search')}`",
        f"- Content writes: `{boundary.get('content_writes')}`",
        "",
        "## Failures",
        "",
        f"- Acceptance: `{acceptance_failures}`",
        f"- Runtime response: `{response_failures}`",
        "",
        "## Next Steps",
        "",
    ]
    lines.extend([f"- {step}" for step in _list(report.get("next_steps"))])
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare or execute a guarded npcink.local runtime resolve smoke."
    )
    parser.add_argument("--acceptance-report", type=Path, default=DEFAULT_ACCEPTANCE_REPORT)
    parser.add_argument("--stage-report", type=Path, default=DEFAULT_STAGE_REPORT)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approval-text", default="")
    parser.add_argument("--approval-file", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or DEFAULT_OUTPUT_ROOT / f"npcink-resolve-smoke-{suffix}"
    try:
        approval_text = resolve_approval_text(
            cli_value=args.approval_text,
            approval_file=args.approval_file,
        )
        report = build_smoke_report(
            acceptance_report_path=args.acceptance_report,
            stage_report_path=args.stage_report,
            output_dir=output_dir,
            base_url=args.base_url,
            timeout_seconds=args.timeout_seconds,
            execute=args.execute,
            approval_text=approval_text,
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
                "acceptance_failures": report["acceptance_failures"],
                "response_failures": report["response_failures"],
            }
        )
    )
    return 0 if report["ok"] is True or not args.execute else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
