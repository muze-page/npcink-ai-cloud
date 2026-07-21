from __future__ import annotations

import json
import os
import stat

import pytest

from app.dev.live_site_addon_install import APPROVAL_TEXT
from app.dev.live_site_identity_provision import (
    GuardError,
    build_cli_result,
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


def test_execute_writes_owner_only_secret_file_but_report_is_redacted(tmp_path) -> None:
    calls = []
    output_dir = tmp_path / "identity"

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

    previous_umask = os.umask(0o022)
    try:
        report = build_report(
            base_url="http://127.0.0.1:8010",
            internal_token="internal-token",
            account_id="acct_live",
            site_id="site_live",
            site_name="Live Site",
            site_url="http://site.local/",
            key_label="Live key",
            scopes=["runtime:execute"],
            output_dir=output_dir,
            execute=True,
            approval_text=APPROVAL_TEXT,
            timeout_seconds=1,
            http_post=fake_post,
        )
    finally:
        os.umask(previous_umask)

    secret_file = output_dir / "cloud-api-key.secret.json"
    assert secret_file.exists()
    assert "secret_live" in secret_file.read_text()
    assert stat.S_IMODE(output_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(secret_file.stat().st_mode) == 0o600
    assert secret_file.stat().st_uid == os.geteuid()
    assert "secret_live" not in json.dumps(report)
    assert "secret_live" not in (output_dir / "identity-report.json").read_text()
    assert "secret_live" not in (output_dir / "summary.md").read_text()
    assert len(calls) == 4
    assert calls[0][2]["X-Npcink-Internal-Token"] == "internal-token"
    assert calls[0][2]["Idempotency-Key"].endswith("-account")


@pytest.mark.parametrize("target_kind", ["regular", "symlink"])
def test_execute_refuses_existing_secret_target_before_cloud_write(tmp_path, target_kind) -> None:
    output_dir = tmp_path / "identity"
    output_dir.mkdir(mode=0o700)
    secret_file = output_dir / "cloud-api-key.secret.json"
    expected_contents = "existing credential must survive"
    if target_kind == "regular":
        secret_file.write_text(expected_contents)
        preserved_file = secret_file
    else:
        preserved_file = tmp_path / "preserved.json"
        preserved_file.write_text(expected_contents)
        secret_file.symlink_to(preserved_file)

    def unexpected_post(*_args):
        raise AssertionError("Cloud write must not run for an unsafe secret target")

    with pytest.raises(GuardError, match="refusing to overwrite"):
        build_report(
            base_url="http://127.0.0.1:8010",
            internal_token="internal-token",
            account_id="acct_live",
            site_id="site_live",
            site_name="Live Site",
            site_url="http://site.local/",
            key_label="Live key",
            scopes=["runtime:execute"],
            output_dir=output_dir,
            execute=True,
            approval_text=APPROVAL_TEXT,
            timeout_seconds=1,
            http_post=unexpected_post,
        )

    assert preserved_file.read_text() == expected_contents


def test_execute_refuses_wide_output_directory_before_cloud_write(tmp_path) -> None:
    output_dir = tmp_path / "identity"
    output_dir.mkdir()
    output_dir.chmod(0o755)

    def unexpected_post(*_args):
        raise AssertionError("Cloud write must not run for an unsafe output directory")

    with pytest.raises(GuardError, match="mode 0700"):
        build_report(
            base_url="http://127.0.0.1:8010",
            internal_token="internal-token",
            account_id="acct_live",
            site_id="site_live",
            site_name="Live Site",
            site_url="http://site.local/",
            key_label="Live key",
            scopes=["runtime:execute"],
            output_dir=output_dir,
            execute=True,
            approval_text=APPROVAL_TEXT,
            timeout_seconds=1,
            http_post=unexpected_post,
        )


def test_execute_removes_new_secret_target_when_permission_hardening_fails(
    tmp_path, monkeypatch
) -> None:
    output_dir = tmp_path / "identity"

    def fake_post(_url, payload, _headers, _timeout_seconds):
        data = {}
        if payload.get("label") == "Live key":
            data = {
                "site_id": "site_live",
                "key_id": "key_live",
                "secret": "secret_live",
            }
        return {"ok": True, "status_code": 200, "response": {"data": data}}

    def fail_fchmod(_file_descriptor, _mode):
        raise OSError("simulated permission hardening failure")

    monkeypatch.setattr(os, "fchmod", fail_fchmod)

    with pytest.raises(OSError, match="simulated permission hardening failure"):
        build_report(
            base_url="http://127.0.0.1:8010",
            internal_token="internal-token",
            account_id="acct_live",
            site_id="site_live",
            site_name="Live Site",
            site_url="http://site.local/",
            key_label="Live key",
            scopes=["runtime:execute"],
            output_dir=output_dir,
            execute=True,
            approval_text=APPROVAL_TEXT,
            timeout_seconds=1,
            http_post=fake_post,
        )

    assert not (output_dir / "cloud-api-key.secret.json").exists()


def test_cli_result_uses_an_explicit_secret_free_allowlist(tmp_path) -> None:
    raw_secret = "secret_must_not_reach_stdout"
    result = build_cli_result(
        {
            "mode": "execute",
            "secret_file": "/private/credential.json",
            "issued_key": {"secret": raw_secret},
            "results": [{"response": {"secret": raw_secret}}],
        },
        tmp_path,
    )

    encoded = json.dumps(result)
    assert raw_secret not in encoded
    assert set(result) == {"ok", "mode", "output_dir", "secret_file"}
