from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.dev.live_site_runtime_smoke import (
    APPROVAL_TEXT,
    GuardError,
    approval_matches,
    build_signed_headers,
    build_smoke_report,
    build_traceparent,
)


def _acceptance_report(path: Path, *, ready: bool = True) -> Path:
    path.write_text(
        json.dumps(
            {
                "ready_for_runtime_smoke_approval": ready,
                "boundary": {
                    "cloud_runtime_execution": False,
                    "site_knowledge_sync": False,
                    "content_writes": False,
                },
                "checks": [] if ready else [{"name": "cloud_addon_verified", "ok": False}],
            }
        )
        + "\n"
    )
    return path


def _stage_report(path: Path, secret_file: Path) -> Path:
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret_file.write_text(
        json.dumps(
            {
                "site_id": "site_live",
                "key_id": "key_live",
                "secret": "secret_live",
                "cloud_api_key": "mak1_fake",
            }
        )
        + "\n"
    )
    path.write_text(
        json.dumps(
            {
                "outputs": {"secret_file": str(secret_file)},
                "identity_provision": {"target": {"site_id": "site_live"}},
            }
        )
        + "\n"
    )
    return path


def test_approval_matches_expected_text_with_whitespace_normalization() -> None:
    assert approval_matches(APPROVAL_TEXT.replace("；", "；\n")) is True
    assert approval_matches("同意") is False


def test_traceparent_is_stable_shape() -> None:
    assert build_traceparent("abc") == "00-abc00000000000000000000000000000-0000000000000000-01"


def test_signed_headers_do_not_include_secret() -> None:
    headers = build_signed_headers(
        method="POST",
        path="/v1/runtime/resolve",
        site_id="site_live",
        key_id="key_live",
        secret="secret_live",
        body=b"{}",
        trace_id="0123456789abcdef0123456789abcdef",
        idempotency_key="idem-1",
        timestamp="1700000000",
        nonce="nonce-1",
    )

    encoded = json.dumps(headers)
    assert "secret_live" not in encoded
    assert headers["X-Npcink-Site-Id"] == "site_live"
    assert headers["X-Npcink-Key-Id"] == "key_live"
    assert len(headers["X-Npcink-Signature"]) == 64


def test_execute_requires_exact_approval_before_http(tmp_path) -> None:
    calls: list[str] = []

    with pytest.raises(GuardError, match="exact approval"):
        build_smoke_report(
            acceptance_report_path=_acceptance_report(tmp_path / "acceptance.json"),
            stage_report_path=_stage_report(
                tmp_path / "stage1-report.json",
                tmp_path / "identity" / "cloud-api-key.secret.json",
            ),
            output_dir=tmp_path / "out",
            base_url="http://127.0.0.1:8010",
            timeout_seconds=1,
            execute=True,
            approval_text="同意",
            http_post=lambda *_: calls.append("http") or {"ok": True},
        )

    assert calls == []


def test_execute_blocks_when_acceptance_is_not_ready(tmp_path) -> None:
    calls: list[str] = []

    with pytest.raises(GuardError, match="acceptance"):
        build_smoke_report(
            acceptance_report_path=_acceptance_report(tmp_path / "acceptance.json", ready=False),
            stage_report_path=_stage_report(
                tmp_path / "stage1-report.json",
                tmp_path / "identity" / "cloud-api-key.secret.json",
            ),
            output_dir=tmp_path / "out",
            base_url="http://127.0.0.1:8010",
            timeout_seconds=1,
            execute=True,
            approval_text=APPROVAL_TEXT,
            http_post=lambda *_: calls.append("http") or {"ok": True},
        )

    assert calls == []


def test_prepare_after_acceptance_points_to_exact_approval(tmp_path) -> None:
    report = build_smoke_report(
        acceptance_report_path=_acceptance_report(tmp_path / "acceptance.json"),
        stage_report_path=_stage_report(
            tmp_path / "stage1-report.json",
            tmp_path / "identity" / "cloud-api-key.secret.json",
        ),
        output_dir=tmp_path / "out",
        base_url="http://127.0.0.1:8010",
        timeout_seconds=1,
        execute=False,
        approval_text="",
    )

    assert report["ok"] is False
    assert report["boundary"]["runtime_resolve_smoke"] is False  # type: ignore[index]
    assert report["acceptance_failures"] == []
    assert report["next_steps"] == [
        "use the exact runtime resolve smoke approval text before execute mode",
        "do not run /v1/runtime/execute, Site Knowledge, or content writes",
        "rerun this helper with --execute only after the separate approval is provided",
    ]


def test_execute_resolve_smoke_writes_redacted_report(tmp_path) -> None:
    calls = []

    def fake_post(url, payload, headers, timeout_seconds):
        calls.append((url, payload, headers, timeout_seconds))
        return {
            "ok": True,
            "status_code": 200,
            "response": {
                "status": "ok",
                "data": {
                    "profile_id": "text.balanced",
                    "execution_kind": "text",
                    "policy": {"allow_fallback": True},
                    "selected_candidate": {"provider_id": "test"},
                    "candidates": [],
                    "execution_context": {
                        "execution_pattern": "inline",
                        "storage_mode": "result_only",
                    },
                    "run_lifecycle": {},
                    "task_backend": {},
                },
            },
        }

    report = build_smoke_report(
        acceptance_report_path=_acceptance_report(tmp_path / "acceptance.json"),
        stage_report_path=_stage_report(
            tmp_path / "stage1-report.json",
            tmp_path / "identity" / "cloud-api-key.secret.json",
        ),
        output_dir=tmp_path / "out",
        base_url="http://127.0.0.1:8010",
        timeout_seconds=1,
        execute=True,
        approval_text=APPROVAL_TEXT,
        http_post=fake_post,
    )
    encoded = json.dumps(report)

    assert report["ok"] is True
    assert len(calls) == 1
    assert calls[0][0].endswith("/v1/runtime/resolve")
    assert calls[0][1]["site_id"] == "site_live"
    assert "secret_live" not in encoded
    assert "mak1_fake" not in encoded
    assert (tmp_path / "out" / "runtime-resolve-smoke-report.json").exists()
