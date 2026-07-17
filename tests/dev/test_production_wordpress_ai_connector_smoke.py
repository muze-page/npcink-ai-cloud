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


def _image_resolve_response() -> dict[str, object]:
    return {
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
    }


def _title_execute_response() -> dict[str, object]:
    return {
        "status": "ok",
        "data": {
            "run_id": "run_prod_title",
            "trace_id": "trace_prod_title",
            "status": "succeeded",
            "profile_id": "wp-ai.short-text",
            "provider_id": "openai",
            "model_id": "gpt-5.5",
            "instance_id": "openai-global-gpt-5-5",
            "provider_call_count": 1,
            "idempotent_replay": False,
            "error_code": "",
            "error_stage": "",
            "result": {
                "contract_version": "cloud_connector_result.v1",
                "suggestion_only": True,
                "operation_contract": {
                    "contract_version": "wordpress_operation.v1",
                    "task": "title_generation",
                },
                "output": {"output_text": "Production title"},
            },
        },
    }


def _build_execute_report(
    tmp_path: Path,
    title_response: dict[str, object],
) -> dict[str, object]:
    def fake_post(url, payload, headers, timeout_seconds):
        response = (
            _image_resolve_response()
            if url.endswith("/v1/runtime/resolve")
            else title_response
        )
        return {"ok": True, "status_code": 200, "response": response}

    return build_smoke_report(
        secret_file=_secret_file(tmp_path / "secret.json"),
        base_url="https://cloud.npc.ink",
        output_dir=tmp_path / "out",
        timeout_seconds=1,
        execute_title=True,
        approval_text=APPROVAL_TEXT,
        site_url="https://wordpress.example.test",
        connector_version="1.0.0-test",
        http_get=lambda *_: {
            "ok": True,
            "status_code": 200,
            "response": {"status": "ok"},
        },
        http_post=fake_post,
    )


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
    operation = title_input["operation_contract"]
    assert isinstance(operation, dict)
    request = operation["request"]
    assert isinstance(request, dict)
    assert request["source_text"].startswith("<content>")  # type: ignore[union-attr]
    assert request["source_text"].endswith("</content>")  # type: ignore[union-attr]
    assert len(request["source_text"]) <= 12_000  # type: ignore[arg-type]
    for removed_field in ("prompt", "post_title", "post_excerpt"):
        assert removed_field not in request

    image_payload = build_image_resolve_payload()
    assert image_payload["ability_name"] == "npcink-cloud/generate-image"
    assert image_payload["channel"] == "wordpress_ai_connector"
    assert image_payload["execution_kind"] == "image_generation"
    image_input = image_payload["input"]
    assert isinstance(image_input, dict)
    assert image_input["task"] == "image_generation"
    assert "response_format" not in image_input


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
            "response": _image_resolve_response(),
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
    assert report["image_resolve"]["selected_instance_id"] == (  # type: ignore[index]
        "openai-global-grok-imagine-image-quality"
    )
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
                "response": _image_resolve_response(),
            }
        return {
            "ok": True,
            "status_code": 200,
            "response": _title_execute_response(),
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
    assert report["title_execute"]["trace_id"] == "trace_prod_title"  # type: ignore[index]
    assert report["title_execute"]["provider_id"] == "openai"  # type: ignore[index]
    assert report["title_execute"]["model_id"] == "gpt-5.5"  # type: ignore[index]
    assert report["title_execute"]["instance_id"] == (  # type: ignore[index]
        "openai-global-gpt-5-5"
    )
    assert report["title_execute"]["provider_call_count"] == 1  # type: ignore[index]
    assert report["title_execute"]["idempotent_replay"] is False  # type: ignore[index]
    assert report["title_execute"]["error_code"] == ""  # type: ignore[index]
    assert report["title_execute"]["error_stage"] == ""  # type: ignore[index]
    assert report["title_execute"]["suggestion_only"] is True  # type: ignore[index]
    assert report["title_execute"]["operation_contract_version"] == (  # type: ignore[index]
        "wordpress_operation.v1"
    )
    assert report["title_execute"]["operation_task"] == "title_generation"  # type: ignore[index]
    assert report["title_execute"]["output_text_preview"] == "Production title"  # type: ignore[index]
    title_check = next(
        check
        for check in report["checks"]  # type: ignore[union-attr]
        if check["name"] == "wordpress_ai_title_execute"
    )
    assert title_check["operation_contract_version"] == "wordpress_operation.v1"
    for removed_field in (
        "selected_provider_id",
        "selected_model_id",
        "selected_instance_id",
    ):
        assert removed_field not in report["title_execute"]  # type: ignore[operator]
    assert "secret_prod" not in json.dumps(report)


@pytest.mark.parametrize(
    "missing_path",
    (
        ("data", "run_id"),
        ("data", "trace_id"),
        ("data", "status"),
        ("data", "profile_id"),
        ("data", "provider_id"),
        ("data", "model_id"),
        ("data", "instance_id"),
        ("data", "provider_call_count"),
        ("data", "idempotent_replay"),
        ("data", "error_code"),
        ("data", "error_stage"),
        ("data", "result", "contract_version"),
        ("data", "result", "suggestion_only"),
        ("data", "result", "operation_contract", "contract_version"),
        ("data", "result", "operation_contract", "task"),
        ("data", "result", "output", "output_text"),
    ),
)
def test_execute_title_rejects_missing_current_evidence(
    tmp_path: Path,
    missing_path: tuple[str, ...],
) -> None:
    title_response = _title_execute_response()
    cursor = title_response
    for part in missing_path[:-1]:
        nested = cursor[part]
        assert isinstance(nested, dict)
        cursor = nested
    cursor.pop(missing_path[-1])

    report = _build_execute_report(tmp_path, title_response)

    title_check = next(
        check
        for check in report["checks"]  # type: ignore[union-attr]
        if check["name"] == "wordpress_ai_title_execute"
    )
    assert report["ok"] is False
    assert title_check["ok"] is False


@pytest.mark.parametrize("error_field", ("error_code", "error_stage"))
def test_execute_title_rejects_non_string_empty_error_evidence(
    tmp_path: Path,
    error_field: str,
) -> None:
    title_response = _title_execute_response()
    data = title_response["data"]
    assert isinstance(data, dict)
    data[error_field] = 0

    report = _build_execute_report(tmp_path, title_response)
    title_check = next(
        check
        for check in report["checks"]  # type: ignore[union-attr]
        if check["name"] == "wordpress_ai_title_execute"
    )

    assert report["ok"] is False
    assert title_check["ok"] is False
