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

from app.dev.live_site_env import resolve_approval_text
from app.dev.live_site_runtime_smoke import build_signed_headers, load_secret_payload
from app.dev.live_site_preflight import _dict, _text

DEFAULT_BASE_URL = "https://cloud.npc.ink"
DEFAULT_OUTPUT_DIR = Path(".tmp/production-wordpress-ai-connector-smoke")
APPROVAL_TEXT = (
    "我明确批准在正式 Cloud 运行一次 WordPress AI Connector 标题生成 execute smoke；"
    "本次不写 WordPress，不执行图片生成。"
)

HttpGet = Callable[[str, int], dict[str, object]]
HttpPost = Callable[[str, dict[str, object], dict[str, str], int], dict[str, object]]


class SmokeError(RuntimeError):
    """Raised when production smoke inputs are unsafe or incomplete."""


def normalize_approval(value: str) -> str:
    return "".join(value.split())


def approval_matches(value: str) -> bool:
    return normalize_approval(value) == normalize_approval(APPROVAL_TEXT)


def get_json(url: str, timeout_seconds: int) -> dict[str, object]:
    request = Request(url, method="GET", headers={"accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(getattr(response, "status", 0) or 0)
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "status_code": exc.code, "response": _parse_json_body(body)}
    except URLError as exc:
        return {"ok": False, "status_code": 0, "error": str(exc)}
    return {"ok": 200 <= status_code < 300, "status_code": status_code, "response": _parse_json_body(body)}


def post_json(
    url: str,
    payload: dict[str, object],
    headers: dict[str, str],
    timeout_seconds: int,
) -> dict[str, object]:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
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


def build_title_execute_payload() -> dict[str, object]:
    return {
        "ability_name": "npcink-cloud/wp-ai-connector",
        "contract_version": "wp_ai_connector_runtime.v1",
        "channel": "wordpress_ai_connector",
        "execution_kind": "wordpress_ai_connector",
        "profile_id": "text.balanced",
        "execution_pattern": "inline",
        "storage_mode": "result_only",
        "data_classification": "public_site_content",
        "timeout_seconds": 60,
        "retry_max": 0,
        "retention_ttl": 86400,
        "input": {
            "contract_version": "wp_ai_connector_runtime.v1",
            "source_surface": "wordpress_ai_connector",
            "connector_id": "npcink-cloud",
            "task": "title_generation",
            "write_posture": "suggestion_only",
            "direct_wordpress_write": False,
            "no_conversation": True,
            "expected_response_contract": "wp_ai_connector_result.v1",
            "request": {
                "post_title": "Production Cloud ability-model routing verification",
                "post_excerpt": (
                    "Verify production Cloud WordPress AI Connector title generation "
                    "uses the managed ability-model route."
                ),
                "prompt": "Suggest one concise title for this WordPress post.",
            },
        },
        "policy": {"allow_fallback": False},
    }


def build_image_resolve_payload() -> dict[str, object]:
    return {
        "ability_name": "npcink-cloud/generate-image",
        "contract_version": "image_generation_request.v1",
        "channel": "wordpress_ai_connector",
        "execution_kind": "image_generation",
        "execution_pattern": "inline",
        "storage_mode": "result_only",
        "data_classification": "internal",
        "timeout_seconds": 90,
        "retry_max": 0,
        "retention_ttl": 86400,
        "input": {
            "contract_version": "image_generation_request.v1",
            "source_surface": "wordpress_ai_connector",
            "connector_id": "npcink-cloud",
            "task": "image_generation",
            "prompt": "A clean media-library illustration of a WordPress editor workspace.",
            "n": 1,
            "response_format": "url",
            "aspect_ratio": "16:9",
            "resolution": "medium",
        },
        "policy": {"allow_fallback": False},
    }


def build_smoke_report(
    *,
    secret_file: Path,
    base_url: str,
    output_dir: Path,
    timeout_seconds: int,
    execute_title: bool,
    approval_text: str,
    resolve_image: bool = True,
    http_get: HttpGet = get_json,
    http_post: HttpPost = post_json,
) -> dict[str, object]:
    if execute_title and not approval_matches(approval_text):
        raise SmokeError("exact approval text did not match; title execute smoke was not run")

    output_dir.mkdir(parents=True, exist_ok=True)
    secret_payload = load_secret_payload(secret_file)
    base_url = base_url.rstrip("/")
    trace_seed = hashlib.sha256(str(datetime.now(UTC)).encode()).hexdigest()

    health_result = http_get(urljoin(base_url + "/", "health/live"), timeout_seconds)
    checks: list[dict[str, object]] = [
        {
            "name": "health_live",
            "ok": bool(health_result.get("ok")),
            "status_code": health_result.get("status_code", 0),
            "error_code": _text(_dict(health_result.get("response")).get("error_code")),
        }
    ]

    image_result: dict[str, object] = {"skipped": True, "reason": "resolve_image=false"}
    if resolve_image:
        image_result = _signed_post(
            base_url=base_url,
            path="/v1/runtime/resolve",
            payload=build_image_resolve_payload(),
            secret_payload=secret_payload,
            trace_id="prodimg" + trace_seed[:25],
            idempotency_key=f"prod-wp-ai-image-resolve-{trace_seed[:16]}",
            timeout_seconds=timeout_seconds,
            http_post=http_post,
        )
        checks.append(_build_image_resolve_check(image_result))

    title_result: dict[str, object] = {"skipped": True, "reason": "execute_title=false"}
    if execute_title:
        title_result = _signed_post(
            base_url=base_url,
            path="/v1/runtime/execute",
            payload=build_title_execute_payload(),
            secret_payload=secret_payload,
            trace_id="prodtitle" + trace_seed[:23],
            idempotency_key=f"prod-wp-ai-title-execute-{trace_seed[:16]}",
            timeout_seconds=timeout_seconds,
            http_post=http_post,
        )
        checks.append(_build_title_execute_check(title_result))

    report: dict[str, object] = {
        "ok": all(bool(check.get("ok")) for check in checks),
        "contract_version": "production_wordpress_ai_connector_smoke.v1",
        "base_url": base_url,
        "identity": {
            "site_id": secret_payload["site_id"],
            "key_id_present": bool(secret_payload["key_id"]),
            "secret_present": bool(secret_payload["secret"]),
        },
        "boundary": {
            "cloud_runtime_resolve": bool(resolve_image),
            "cloud_runtime_execute": bool(execute_title),
            "image_generation_execute": False,
            "wordpress_writes": False,
            "site_knowledge_sync": False,
        },
        "checks": checks,
        "health": _redact_result(health_result),
        "image_resolve": _summarize_runtime_response(image_result),
        "title_execute": _summarize_runtime_response(title_result),
        "next_steps": _next_steps(checks, execute_title=execute_title),
    }

    report_path = output_dir / "production-wordpress-ai-connector-smoke-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    report["report_path"] = str(report_path)
    return report


def _signed_post(
    *,
    base_url: str,
    path: str,
    payload: dict[str, object],
    secret_payload: dict[str, str],
    trace_id: str,
    idempotency_key: str,
    timeout_seconds: int,
    http_post: HttpPost,
) -> dict[str, object]:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    timestamp = str(int(datetime.now(UTC).timestamp()))
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
        urljoin(base_url + "/", path.lstrip("/")),
        payload,
        headers,
        timeout_seconds,
    )
    result["trace_id"] = trace_id
    result["idempotency_key"] = idempotency_key
    return result


def _build_image_resolve_check(result: dict[str, object]) -> dict[str, object]:
    response = _dict(result.get("response"))
    data = _dict(response.get("data"))
    selected = _dict(data.get("selected_candidate"))
    policy = _dict(data.get("policy"))
    ok = (
        bool(result.get("ok"))
        and response.get("status") == "ok"
        and data.get("profile_id") == "wp-ai.image-generation"
        and data.get("execution_kind") == "image_generation"
        and _text(policy.get("routing_intent")) == "media.image_generation"
        and bool(_text(selected.get("instance_id")))
    )
    return {
        "name": "wordpress_ai_image_generation_resolve",
        "ok": ok,
        "profile_id": data.get("profile_id"),
        "routing_intent": policy.get("routing_intent"),
        "selected_instance_id": selected.get("instance_id"),
        "error_code": response.get("error_code"),
    }


def _build_title_execute_check(result: dict[str, object]) -> dict[str, object]:
    response = _dict(result.get("response"))
    data = _dict(response.get("data"))
    result_payload = _dict(data.get("result"))
    ok = (
        bool(result.get("ok"))
        and response.get("status") == "ok"
        and data.get("status") == "succeeded"
        and data.get("profile_id") == "wp-ai.short-text"
        and bool(_text(result_payload.get("output_text")))
    )
    return {
        "name": "wordpress_ai_title_execute",
        "ok": ok,
        "run_id": data.get("run_id"),
        "profile_id": data.get("profile_id"),
        "status": data.get("status"),
        "output_text_present": bool(_text(result_payload.get("output_text"))),
        "error_code": response.get("error_code"),
    }


def _summarize_runtime_response(result: dict[str, object]) -> dict[str, object]:
    if result.get("skipped"):
        return {"skipped": True, "reason": result.get("reason")}
    response = _dict(result.get("response"))
    data = _dict(response.get("data"))
    selected = _dict(data.get("selected_candidate"))
    result_payload = _dict(data.get("result"))
    policy = _dict(data.get("policy"))
    return {
        "ok": bool(result.get("ok")),
        "status_code": result.get("status_code", 0),
        "response_status": response.get("status"),
        "error_code": response.get("error_code"),
        "message": response.get("message"),
        "trace_id": result.get("trace_id"),
        "idempotency_key": result.get("idempotency_key"),
        "run_id": data.get("run_id"),
        "run_status": data.get("status"),
        "profile_id": data.get("profile_id"),
        "execution_kind": data.get("execution_kind"),
        "selected_provider_id": selected.get("provider_id"),
        "selected_model_id": selected.get("model_id") or data.get("selected_model_id"),
        "selected_instance_id": selected.get("instance_id") or data.get("selected_instance_id"),
        "routing_intent": policy.get("routing_intent"),
        "output_text_preview": _text(result_payload.get("output_text"))[:200],
    }


def _redact_result(result: dict[str, object]) -> dict[str, object]:
    return {
        "ok": bool(result.get("ok")),
        "status_code": result.get("status_code", 0),
        "response": result.get("response", {}),
        "error": result.get("error", ""),
    }


def _next_steps(
    checks: list[dict[str, object]],
    *,
    execute_title: bool,
) -> list[str]:
    failed = [str(check.get("name")) for check in checks if not bool(check.get("ok"))]
    if failed:
        return [
            "inspect failed checks: " + ", ".join(failed),
            "verify production routing bindings and provider availability before retrying",
        ]
    if not execute_title:
        return [
            "resolve checks passed; rerun with --execute-title and the exact approval text to verify provider execution",
            "after execute, inspect the production run record for profile_id/routing_intent/model evidence",
        ]
    return [
        "production runtime smoke passed",
        "inspect the production run record for durable provider-call evidence",
    ]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run production WordPress AI Connector ability-model routing smoke.",
    )
    parser.add_argument("--secret-file", type=Path, required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout-seconds", type=int, default=90)
    parser.add_argument("--skip-image-resolve", action="store_true")
    parser.add_argument("--execute-title", action="store_true")
    parser.add_argument("--approval-text", default="")
    parser.add_argument("--approval-file", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        approval_text = resolve_approval_text(
            cli_value=args.approval_text,
            approval_file=args.approval_file,
        )
        report = build_smoke_report(
            secret_file=args.secret_file,
            base_url=args.base_url,
            output_dir=args.output_dir,
            timeout_seconds=max(1, int(args.timeout_seconds)),
            execute_title=bool(args.execute_title),
            approval_text=approval_text,
            resolve_image=not bool(args.skip_image_resolve),
        )
    except (SmokeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if bool(report.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
