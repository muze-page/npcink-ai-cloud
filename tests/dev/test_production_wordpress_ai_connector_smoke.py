from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.dev.production_wordpress_ai_connector_smoke import (
    APPROVAL_TEXT,
    SmokeError,
    approval_matches,
    build_image_resolve_payload,
    build_smoke_report,
    build_title_execute_payload,
)


def _secret_file(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "site_id": "site_prod",
                "key_id": "key_prod",
                "secret": "secret_prod",
            }
        )
        + "\n"
    )
    return path


def test_approval_text_requires_exact_match() -> None:
    assert approval_matches(APPROVAL_TEXT.replace("；", "；\n")) is True
    assert approval_matches("同意") is False


def test_payloads_preserve_wordpress_ai_connector_boundary() -> None:
    title_payload = build_title_execute_payload(
        site_id="site_prod",
        site_url="https://wordpress.example.test",
        connector_version="1.0.0-test",
    )
    assert title_payload["site_id"] == "site_prod"
    assert title_payload["ability_name"] == "npcink-cloud/connector-runtime"
    assert title_payload["contract_version"] == "cloud_connector_runtime.v1"
    assert title_payload["channel"] == "editor"
    assert title_payload["execution_kind"] == "text"
    assert title_payload["policy"] == {"allow_fallback": False}
    title_input = title_payload["input"]
    assert isinstance(title_input, dict)
    assert title_input["site_url"] == "https://wordpress.example.test"
    assert title_input["platform_kind"] == "wordpress"
    assert title_input["connector_id"] == "npcink-cloud-addon"
    assert title_input["connector_version"] == "1.0.0-test"
    assert title_input["suggestion_only"] is True
    assert title_input["operation_contract"]["contract_version"] == (  # type: ignore[index]
        "wordpress_operation.v1"
    )

    image_payload = build_image_resolve_payload()
    assert image_payload["ability_name"] == "npcink-cloud/generate-image"
    assert image_payload["channel"] == "wordpress_ai_connector"
    assert image_payload["execution_kind"] == "image_generation"
    image_input = image_payload["input"]
    assert isinstance(image_input, dict)
    assert image_input["task"] == "image_generation"


def test_execute_title_requires_exact_approval_before_http(tmp_path: Path) -> None:
    calls: list[str] = []

    with pytest.raises(SmokeError, match="exact approval"):
        build_smoke_report(
            secret_file=_secret_file(tmp_path / "secret.json"),
            base_url="https://cloud.npc.ink",
            output_dir=tmp_path / "out",
            timeout_seconds=1,
            execute_title=True,
            approval_text="同意",
            site_url="https://wordpress.example.test",
            connector_version="1.0.0-test",
            http_get=lambda *_: {"ok": True, "status_code": 200, "response": {"status": "ok"}},
            http_post=lambda *_: calls.append("post") or {"ok": True},
        )

    assert calls == []


def test_resolve_only_writes_redacted_report(tmp_path: Path) -> None:
    calls = []

    def fake_post(url, payload, headers, timeout_seconds):
        calls.append((url, payload, headers, timeout_seconds))
        return {
            "ok": True,
            "status_code": 200,
            "response": {
                "status": "ok",
                "data": {
                    "profile_id": "wp-ai.image-generation",
                    "execution_kind": "image_generation",
                    "policy": {"routing_intent": "media.image_generation"},
                    "selected_candidate": {
                        "provider_id": "openai",
                        "model_id": "grok-imagine-image-quality",
                        "instance_id": "openai-global-grok-imagine-image-quality",
                    },
                },
            },
        }

    report = build_smoke_report(
        secret_file=_secret_file(tmp_path / "secret.json"),
        base_url="https://cloud.npc.ink",
        output_dir=tmp_path / "out",
        timeout_seconds=1,
        execute_title=False,
        approval_text="",
        site_url="https://wordpress.example.test",
        connector_version="1.0.0-test",
        http_get=lambda *_: {"ok": True, "status_code": 200, "response": {"status": "ok"}},
        http_post=fake_post,
    )
    encoded = json.dumps(report)

    assert report["ok"] is True
    assert report["boundary"]["cloud_runtime_execute"] is False  # type: ignore[index]
    assert report["image_resolve"]["profile_id"] == "wp-ai.image-generation"  # type: ignore[index]
    assert report["title_execute"] == {"skipped": True, "reason": "execute_title=false"}
    assert calls[0][0] == "https://cloud.npc.ink/v1/runtime/resolve"
    assert calls[0][2]["X-Npcink-Site-Id"] == "site_prod"
    assert "secret_prod" not in encoded
    assert (tmp_path / "out" / "production-wordpress-ai-connector-smoke-report.json").exists()


def test_execute_title_summarizes_run_without_leaking_secret(tmp_path: Path) -> None:
    post_paths: list[str] = []

    def fake_post(url, payload, headers, timeout_seconds):
        post_paths.append(url)
        if url.endswith("/v1/runtime/resolve"):
            return {
                "ok": True,
                "status_code": 200,
                "response": {
                    "status": "ok",
                    "data": {
                        "profile_id": "wp-ai.image-generation",
                        "execution_kind": "image_generation",
                        "policy": {"routing_intent": "media.image_generation"},
                        "selected_candidate": {"instance_id": "openai-global-image"},
                    },
                },
            }
        return {
            "ok": True,
            "status_code": 200,
            "response": {
                "status": "ok",
                "data": {
                    "run_id": "run_prod_title",
                    "status": "succeeded",
                    "profile_id": "wp-ai.short-text",
                    "selected_model_id": "gpt-5.5",
                    "selected_instance_id": "openai-global-gpt-5-5",
                    "result": {
                        "contract_version": "cloud_connector_result.v1",
                        "output": {"output_text": "Production title"},
                    },
                },
            },
        }

    report = build_smoke_report(
        secret_file=_secret_file(tmp_path / "secret.json"),
        base_url="https://cloud.npc.ink",
        output_dir=tmp_path / "out",
        timeout_seconds=1,
        execute_title=True,
        approval_text=APPROVAL_TEXT,
        site_url="https://wordpress.example.test",
        connector_version="1.0.0-test",
        http_get=lambda *_: {"ok": True, "status_code": 200, "response": {"status": "ok"}},
        http_post=fake_post,
    )

    assert report["ok"] is True
    assert post_paths == [
        "https://cloud.npc.ink/v1/runtime/resolve",
        "https://cloud.npc.ink/v1/runtime/execute",
    ]
    assert report["title_execute"]["run_id"] == "run_prod_title"  # type: ignore[index]
    assert report["title_execute"]["output_text_preview"] == "Production title"  # type: ignore[index]
    assert "secret_prod" not in json.dumps(report)
