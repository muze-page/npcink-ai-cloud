from __future__ import annotations

import json

import pytest

from app.dev.live_site_addon_install import APPROVAL_TEXT
from app.dev.live_site_identity_provision import (
    GuardError,
    build_report,
    build_request_plan,
    extract_issued_key,
    redact_payload,
)


def test_request_plan_uses_internal_service_operations() -> None:
    plan = build_request_plan(
        account_id="acct_live",
        site_id="site_live",
        site_name="Live Site",
        site_url="http://site.local/",
        key_label="Live key",
        scopes=["runtime:execute"],
        idempotency_prefix="live-001",
    )

    assert [item.path for item in plan] == [
        "/internal/service/accounts",
        "/internal/service/sites",
        "/internal/service/sites/site_live/activate",
        "/internal/service/sites/site_live/keys",
    ]
    assert plan[0].payload["bind_default_free"] is True
    assert plan[-1].payload["scopes"] == ["runtime:execute"]


def test_redact_payload_hides_secret_and_cloud_api_key() -> None:
    redacted = redact_payload(
        {
            "secret": "plain-secret",
            "cloud_api_key": "customer-key-placeholder",
            "nested": [{"secret": "nested-secret"}],
        }
    )

    encoded = json.dumps(redacted)
    assert "plain-secret" not in encoded
    assert "customer-key-placeholder" not in encoded
    assert "nested-secret" not in encoded
    assert redacted == {
        "secret": True,
        "cloud_api_key": True,
        "nested": [{"secret": True}],
    }


def test_extract_issued_key_builds_customer_wrapper() -> None:
    issued = extract_issued_key(
        [
            {
                "name": "site_key_issue",
                "result": {
                    "ok": True,
                    "response": {
                        "data": {
                            "site_id": "site_live",
                            "key_id": "key_live",
                            "secret": "secret_live",
                        }
                    },
                },
            }
        ]
    )

    assert issued["site_id"] == "site_live"
    assert issued["key_id"] == "key_live"
    assert issued["secret"] == "secret_live"
    assert issued["cloud_api_key"].startswith("mak1_")


def test_execute_requires_exact_approval(tmp_path) -> None:
    with pytest.raises(GuardError, match="exact approval"):
        build_report(
            base_url="http://127.0.0.1:8010",
            internal_token="token",
            account_id="acct_live",
            site_id="site_live",
            site_name="Live Site",
            site_url="http://site.local/",
            key_label="Live key",
            scopes=["runtime:execute"],
            output_dir=tmp_path,
            execute=True,
            approval_text="同意",
            timeout_seconds=1,
            http_post=lambda *_: {"ok": True},
        )


def test_execute_writes_secret_file_but_report_is_redacted(tmp_path) -> None:
    calls = []

    def fake_post(url, payload, headers, timeout_seconds):
        calls.append((url, payload, headers, timeout_seconds))
        data = {}
        if url.endswith("/keys"):
            data = {
                "site_id": "site_live",
                "key_id": "key_live",
                "secret": "secret_live",
            }
        return {"ok": True, "status_code": 200, "response": {"data": data}}

    report = build_report(
        base_url="http://127.0.0.1:8010",
        internal_token="internal-token",
        account_id="acct_live",
        site_id="site_live",
        site_name="Live Site",
        site_url="http://site.local/",
        key_label="Live key",
        scopes=["runtime:execute"],
        output_dir=tmp_path,
        execute=True,
        approval_text=APPROVAL_TEXT,
        timeout_seconds=1,
        http_post=fake_post,
    )

    secret_file = tmp_path / "cloud-api-key.secret.json"
    assert secret_file.exists()
    assert "secret_live" in secret_file.read_text()
    assert "secret_live" not in json.dumps(report)
    assert len(calls) == 4
    assert calls[0][2]["X-Npcink-Internal-Token"] == "internal-token"
    assert calls[0][2]["Idempotency-Key"].endswith("-account")
