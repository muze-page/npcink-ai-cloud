from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domain.media_artifacts.input_loading import LoadedArtifactInput
from app.domain.wordpress_ai_connector.contracts import (
    WordPressOperationContractViolation,
    validate_wordpress_operation_contract,
)
from app.domain.wordpress_ai_connector.routing_profiles import (
    WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
)
from app.domain.wordpress_ai_connector.runtime import WordPressOperationRuntime


def _runtime() -> WordPressOperationRuntime:
    settings = Settings(
        environment="test",
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        admin_session_secret="test-admin-session-secret-at-least-32-bytes",
        portal_jwt_secret="test-portal-jwt-secret-at-least-32-bytes",
    )
    return WordPressOperationRuntime(settings=settings, providers={})


def _operation_payload(
    *,
    task: str = "title_generation",
    request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scene_text_field = (
        "source_text"
        if task in {"title_generation", "content_summary", "content_rewrite"}
        else "prompt"
    )
    scene_request: dict[str, Any] = {
        scene_text_field: "<content>当前文章说明云端运行时如何提供可审阅的内容建议。</content>",
        "task_contract": {
            "contract_version": "ai_task_contract.v1",
            "ability_name": "npcink/title-generation",
            "task": task,
            "task_family": "generation",
            "context_requirements": ["current_content"],
            "constraints": ["single_value", "source_grounded"],
            "output_schema": {"type": "string"},
            "write_posture": "suggestion_only",
        },
    }
    if request:
        scene_request.update(request)
    return {
        "site_id": "site_alpha",
        "site_url": "https://alpha.example.test",
        "platform_kind": "wordpress",
        "connector_id": "npcink-cloud-addon",
        "connector_version": "2.0.0-test",
        "object_ref": {
            "object_type": "post",
            "object_id": "42",
            "object_revision": "7",
        },
        "operation_contract": {
            "contract_version": "wordpress_operation.v1",
            "task": task,
            "request": scene_request,
        },
    }


@pytest.mark.parametrize(
    ("task", "source_text", "expected_max_tokens"),
    [
        (
            "title_generation",
            "<content>当前文章说明云端运行时如何提供可审阅的标题建议。</content>",
            48,
        ),
        (
            "content_summary",
            "<content>当前文章详细解释了托管运行时与本地审阅边界。</content>",
            160,
        ),
        (
            "content_rewrite",
            "<block-content>这段文字需要改写得更加清晰。</block-content>",
            512,
        ),
    ],
)
def test_p2_text_provider_input_projects_source_text_once(
    task: str,
    source_text: str,
    expected_max_tokens: int,
) -> None:
    runtime = _runtime()
    provider_input = runtime.build_provider_input(
        _operation_payload(
            task=task,
            request={
                "source_text": source_text,
                "system_instruction": "  Apply the local Ability instruction.  \n",
            },
        )
    )

    serialized = json.dumps(provider_input, ensure_ascii=False)
    assert provider_input["text"] == source_text
    assert provider_input["input"].count(source_text) == 1
    assert provider_input["input"].count("Apply the local Ability instruction.") == 1
    assert "  Apply the local Ability instruction." not in provider_input["input"]
    assert provider_input["metadata"]["task"] == task
    assert provider_input["metadata"]["suggestion_only"] is True
    assert provider_input["max_tokens"] == expected_max_tokens
    assert "site_alpha" not in serialized
    assert "alpha.example.test" not in serialized
    assert "object_revision" not in serialized
    assert "connector_version" not in serialized


def test_alt_text_provider_input_builds_transient_vision_shapes_from_artifact() -> None:
    runtime = _runtime()
    source_artifact = LoadedArtifactInput(
        artifact_id="art_0123456789abcdef0123456789abcdef",
        content_type="image/png",
        byte_size=11,
        content_bytes=b"image-bytes",
    )
    provider_input = runtime.build_provider_input(
        _operation_payload(
            task="alt_text_suggest",
            request={
                "prompt": "描述主要视觉内容",
                "source_artifact_id": source_artifact.artifact_id,
                "filename": "image.jpg",
                "max_tokens": 96,
            },
        ),
        source_artifact=source_artifact,
    )

    responses_content = provider_input["input"][0]["content"]
    chat_content = provider_input["messages"][0]["content"]
    assert responses_content[-1] == {
        "type": "input_image",
        "image_url": "data:image/png;base64,aW1hZ2UtYnl0ZXM=",
    }
    assert chat_content[-1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,aW1hZ2UtYnl0ZXM="},
    }
    assert provider_input["max_tokens"] == 96
    assert provider_input["temperature"] == 0.0
    assert "image-bytes" not in repr(source_artifact)


def test_alt_text_contract_normalizes_values_without_materializing_omissions() -> None:
    normalized = validate_wordpress_operation_contract(
        {
            "contract_version": "wordpress_operation.v1",
            "task": "alt_text_suggest",
            "request": {
                "source_artifact_id": "art_0123456789abcdef0123456789abcdef",
                "prompt": "  Generate useful alt text.  ",
                "filename": "  blue-mug.jpg  ",
                "existing_alt": "   ",
                "locale": "  en_US  ",
                "max_tokens": 96,
            },
        }
    )

    assert normalized["request"] == {
        "source_artifact_id": "art_0123456789abcdef0123456789abcdef",
        "prompt": "Generate useful alt text.",
        "filename": "blue-mug.jpg",
        "existing_alt": "",
        "locale": "en_US",
        "max_tokens": 96,
    }
    assert "title" not in normalized["request"]
    assert "existing_caption" not in normalized["request"]


@pytest.mark.parametrize(
    ("field_name", "field_value", "expected_error"),
    [
        ("prompt", "   ", "wordpress_operation.alt_text_prompt_invalid"),
        (
            "prompt",
            ("word " * 101).strip(),
            "wordpress_operation.alt_text_prompt_too_large",
        ),
        (
            "filename",
            ("x " * 81).strip(),
            "wordpress_operation.alt_text_request_value_too_large",
        ),
        (
            "existing_caption",
            ("x " * 121).strip(),
            "wordpress_operation.alt_text_request_value_too_large",
        ),
        (
            "locale",
            ("x " * 17).strip(),
            "wordpress_operation.alt_text_request_value_too_large",
        ),
        ("max_tokens", 0, "wordpress_operation.alt_text_max_tokens_invalid"),
        ("max_tokens", 97, "wordpress_operation.alt_text_max_tokens_invalid"),
    ],
)
def test_alt_text_contract_rejects_values_outside_strict_bounds(
    field_name: str,
    field_value: Any,
    expected_error: str,
) -> None:
    request: dict[str, Any] = {
        "source_artifact_id": "art_0123456789abcdef0123456789abcdef",
        "prompt": "Generate useful alt text.",
        field_name: field_value,
    }

    with pytest.raises(WordPressOperationContractViolation) as error:
        validate_wordpress_operation_contract(
            {
                "contract_version": "wordpress_operation.v1",
                "task": "alt_text_suggest",
                "request": request,
            }
        )

    assert error.value.error_code == expected_error


@pytest.mark.parametrize(
    "extra_request",
    [
        {"Image_URL": "https://example.test/image.png"},
        {"Mime-Type": "image/png"},
        {"Storage-Key": "obj_private"},
        {"Raw-Bytes": "private"},
        {"Source-Artifact-ID": "art_abcdefabcdefabcdefabcdefabcdefab"},
        {"unknown_field": "private"},
    ],
)
def test_alt_text_contract_rejects_legacy_alias_and_unknown_fields(
    extra_request: dict[str, Any],
) -> None:
    request = {
        "source_artifact_id": "art_0123456789abcdef0123456789abcdef",
        "prompt": "Generate alt text.",
        **extra_request,
    }

    with pytest.raises(WordPressOperationContractViolation) as error:
        validate_wordpress_operation_contract(
            {
                "contract_version": "wordpress_operation.v1",
                "task": "alt_text_suggest",
                "request": request,
            }
        )

    assert error.value.error_code == (
        "wordpress_operation.alt_text_request_fields_forbidden"
    )


@pytest.mark.parametrize(
    "inline_value",
    [
        "DaTa : ImAgE / PnG ; BaSe64 , cHJpdmF0ZQ==",
        "b64-json = cHJpdmF0ZQ==",
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB",
        "A" * 128,
    ],
)
def test_alt_text_contract_recursively_rejects_obfuscated_inline_media(
    inline_value: str,
) -> None:
    with pytest.raises(WordPressOperationContractViolation) as error:
        validate_wordpress_operation_contract(
            {
                "contract_version": "wordpress_operation.v1",
                "task": "alt_text_suggest",
                "request": {
                    "source_artifact_id": "art_0123456789abcdef0123456789abcdef",
                    "prompt": {"nested": inline_value},
                },
            }
        )

    assert error.value.error_code == (
        "wordpress_operation.alt_text_inline_media_forbidden"
    )


def test_alt_text_provider_output_is_strict_text_only_projection() -> None:
    runtime = _runtime()

    normalized = runtime.normalize_provider_output(
        {
            "output_text": "**Blue mug on a white table**",
            "model_id": "gpt-vision-test",
            "messages": [{"role": "assistant", "content": "raw"}],
            "usage": {"nested": {"private": "raw"}},
            "output": {"private": "raw"},
        },
        input_payload={"metadata": {"task": "alt_text_suggest"}},
    )

    assert normalized == {"output_text": "Blue mug on a white table"}


@pytest.mark.parametrize(
    "output_text",
    [
        "data : image / png ; base64 , c2Vuc2l0aXZlLXByb3ZpZGVyLWVjaG8=",
        "b64_json: c2Vuc2l0aXZlLXByb3ZpZGVyLWVjaG8=",
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB",
        "iVBO Rw0K GgoA AAAN SUhE UgAA AAEA A AAB",
        "A" * 128,
    ],
)
def test_alt_text_provider_output_rejects_inline_media_echo(output_text: str) -> None:
    runtime = _runtime()

    normalized = runtime.normalize_provider_output(
        {
            "output_text": output_text,
            "model_id": "gpt-vision-test",
        },
        input_payload={"metadata": {"task": "alt_text_suggest"}},
    )

    assert normalized == {}


def test_registered_task_provider_input_projects_profile_metadata() -> None:
    runtime = _runtime()
    provider_input = runtime.build_provider_input(
        _operation_payload(
            task="seo_headline",
            request={
                "prompt": "Write one accurate headline for this article.",
                "task_contract": {
                    "contract_version": "ai_task_contract.v1",
                    "ability_name": "example/seo-headline",
                    "task": "seo_headline",
                    "task_family": "generation",
                    "context_requirements": ["current_content", "site_style_profile"],
                    "constraints": [
                        "single_value",
                        "source_grounded",
                        "no_new_numbers",
                    ],
                    "output_schema": {"type": "string"},
                    "write_posture": "suggestion_only",
                },
            },
        )
    )

    assert provider_input["metadata"] == {
        "source_surface": "wordpress_ai_connector",
        "task": "seo_headline",
        "ability_name": "example/seo-headline",
        "task_family": "generation",
        "task_constraints": ["no_new_numbers", "single_value", "source_grounded"],
        "suggestion_only": True,
    }
    assert "Generate the requested value" in provider_input["input"]
    assert "Do not introduce a number" in provider_input["input"]
    assert provider_input["max_tokens"] == 160


def test_provider_output_normalizes_title_summary_and_classification() -> None:
    runtime = _runtime()

    title = runtime.normalize_provider_output(
        {"output_text": "# 云端连接器重构\n\n摘要：不应进入标题"},
        input_payload={"metadata": {"task": "title_generation"}, "text": "当前文章内容"},
    )
    summary_source = "这篇文章说明云端运行时如何为编辑器提供可靠且可审阅的内容建议。"
    summary = runtime.normalize_provider_output(
        {"output_text": "标题建议\n1. 云端连接器\n2. 编辑器助手"},
        input_payload={"metadata": {"task": "content_summary"}, "text": summary_source},
    )
    rewrite = runtime.normalize_provider_output(
        {"output_text": "建议改写为：\n\n**这段文字现在更加清晰。**\n\n说明：已完成"},
        input_payload={
            "metadata": {"task": "content_rewrite"},
            "text": "<block-content>这段文字需要改写得更加清晰。</block-content>",
        },
    )
    classification = runtime.normalize_provider_output(
        {
            "output_text": json.dumps(
                {
                    "suggestions": [
                        {"term": "WordPress", "confidence": 2, "is_new": False},
                        {"term": "Cloud Runtime", "confidence": 0.4},
                    ]
                }
            )
        },
        input_payload={"metadata": {"task": "content_classification"}, "text": ""},
    )

    assert title["output_text"] == "云端连接器重构"
    assert summary["output_text"] == summary_source
    assert rewrite["output_text"] == "这段文字现在更加清晰。"
    assert json.loads(classification["output_text"]) == {
        "suggestions": [
            {"term": "WordPress", "confidence": 1.0, "is_new": False},
            {"term": "Cloud Runtime", "confidence": 0.4, "is_new": True},
        ]
    }


def test_empty_text_output_judgement_is_task_bounded() -> None:
    runtime = _runtime()
    title_input = {"metadata": {"task": "title_generation"}}

    assert runtime.is_empty_text_output(
        input_payload=title_input,
        provider_output={"output_text": ""},
    )
    assert runtime.is_empty_text_output(
        input_payload=title_input,
        provider_output={"output_text": "《未闭合的标题"},
    )
    assert runtime.is_empty_text_output(
        input_payload=title_input,
        provider_output={
            "output_text": "Short title",
            "usage": {"completion_tokens_details": {"reasoning_tokens": 128}},
        },
    )
    assert not runtime.is_empty_text_output(
        input_payload={"metadata": {"task": "comment_moderation"}},
        provider_output={},
    )


def test_managed_policy_projects_profile_runtime_controls() -> None:
    runtime = _runtime()
    merged_policy: dict[str, object] = {
        "timeout_ms": 99,
        "execution_contract": {"ability_name": "connector_runtime.execute"},
    }
    policy = runtime.apply_managed_policy(
        merged_policy,
        default_policy={
            "managed_surface": "wordpress_ai_connector",
            "timeout_ms": 12_001,
            "max_retries": 1,
            "allow_fallback": False,
        },
        profile_id=WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
    )

    assert policy["timeout_ms"] == 12_001
    assert policy["timeout_seconds"] == 13
    assert policy["max_retries"] == 1
    assert policy["retry_max"] == 1
    assert policy["allow_fallback"] is False
    assert policy["managed_surface"] == "wordpress_ai_connector"
    assert policy["task_group"]
    assert policy["routing_intent"]
    execution_contract = cast(dict[str, object], policy["execution_contract"])
    assert execution_contract["retry_max"] == 1
    assert {
        key: value for key, value in execution_contract.items() if key != "retry_max"
    } == {
        "ability_name": "connector_runtime.execute",
        "timeout_seconds": 13,
        "managed_surface": "wordpress_ai_connector",
        "task_group": policy["task_group"],
        "routing_intent": policy["routing_intent"],
    }


def test_site_knowledge_reference_applies_with_explicit_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()
    captured: dict[str, Any] = {}

    class FakeSiteKnowledgeService:
        def __init__(self, session: Session, **kwargs: Any) -> None:
            captured["session"] = session
            captured["usage_callback"] = kwargs["embedding_usage_callback"]

        def execute(self, **kwargs: Any) -> dict[str, Any]:
            captured["execute"] = kwargs
            return {
                "evidence_gate": {"status": "passed"},
                "results": [
                    {
                        "post_id": 11,
                        "title": "用云端能力增强 WordPress 编辑体验",
                        "chunk": "This private chunk must remain hidden.",
                        "score": 0.88,
                    }
                ],
            }

    class FakeSiteKnowledgeRepository:
        def __init__(self, session: Session) -> None:
            captured["repository_session"] = session

        def reference_metadata_for_post_ids(
            self,
            *,
            site_id: str,
            post_ids: list[int],
        ) -> dict[int, dict[str, Any]]:
            captured["metadata_request"] = (site_id, post_ids)
            return {}

    monkeypatch.setattr(
        "app.domain.wordpress_ai_connector.runtime.SiteKnowledgeService",
        FakeSiteKnowledgeService,
    )
    monkeypatch.setattr(
        "app.domain.wordpress_ai_connector.runtime.SiteKnowledgeRepository",
        FakeSiteKnowledgeRepository,
    )
    payload = _operation_payload(
        request={
            "site_knowledge_reference": {
                "enabled": True,
                "mode": "site_title_style",
            }
        }
    )
    provider_input = runtime.build_provider_input(payload)
    session = cast(Session, object())

    def record_usage(*args: Any) -> None:
        captured["usage"] = args

    result = runtime.apply_site_knowledge_reference(
        site_id="site_alpha",
        run_id="run_alpha",
        session=session,
        input_payload=payload,
        provider_input=provider_input,
        embedding_usage_callback=record_usage,
    )

    assert captured["session"] is session
    assert captured["usage_callback"] is record_usage
    assert captured["execute"]["site_id"] == "site_alpha"
    assert captured["execute"]["run_id"] == "run_alpha"
    assert captured["metadata_request"] == ("site_alpha", [11])
    assert "Aggregate style profile" in result["input"]
    assert "This private chunk" not in result["input"]
    assert result["metadata"]["generation_context_status"] == "applied"
    assert result["metadata"]["site_knowledge_reference_count"] == 1


def test_site_knowledge_reference_is_optional_when_retrieval_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()

    class FailingSiteKnowledgeService:
        def __init__(self, session: Session, **kwargs: Any) -> None:
            del session, kwargs

        def execute(self, **kwargs: Any) -> dict[str, Any]:
            del kwargs
            raise RuntimeError("retrieval unavailable")

    monkeypatch.setattr(
        "app.domain.wordpress_ai_connector.runtime.SiteKnowledgeService",
        FailingSiteKnowledgeService,
    )
    payload = _operation_payload(
        request={
            "site_knowledge_reference": {
                "enabled": True,
                "mode": "site_title_style",
            }
        }
    )
    provider_input = runtime.build_provider_input(payload)
    result = runtime.apply_site_knowledge_reference(
        site_id="site_alpha",
        run_id="run_alpha",
        session=cast(Session, object()),
        input_payload=payload,
        provider_input=provider_input,
        embedding_usage_callback=lambda *args: None,
    )

    assert "Generation context" not in result["input"]
    assert result["metadata"]["generation_context_status"] == "unavailable"
    assert result["metadata"]["generation_context_reason"] == "retrieval_failed"


def test_runtime_service_no_longer_defines_wordpress_operation_execution_details() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    service_path = repository_root / "app/domain/runtime/service.py"
    runtime_path = repository_root / "app/domain/wordpress_ai_connector/runtime.py"
    service_source = service_path.read_text(encoding="utf-8")
    runtime_source = runtime_path.read_text(encoding="utf-8")
    service_tree = ast.parse(service_source)
    runtime_tree = ast.parse(runtime_source)
    service_class = next(
        node
        for node in service_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "RuntimeService"
    )
    runtime_class = next(
        node
        for node in runtime_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "WordPressOperationRuntime"
    )
    service_methods = {
        node.name for node in service_class.body if isinstance(node, ast.FunctionDef)
    }
    runtime_methods = {
        node.name for node in runtime_class.body if isinstance(node, ast.FunctionDef)
    }
    imported_modules = {
        alias.name
        for node in ast.walk(runtime_tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_modules.update(
        node.module
        for node in ast.walk(runtime_tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )
    forbidden_import_prefixes = (
        "app.domain.runtime.service",
        "app.domain.commercial",
        "app.adapters.queue",
        "app.adapters.callbacks",
    )
    forbidden_transaction_calls = {
        node.func.attr
        for node in ast.walk(runtime_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"commit", "rollback", "flush", "add", "delete"}
    }
    removed_methods = {
        "_build_wordpress_ai_connector_provider_input",
        "_build_wordpress_ai_connector_alt_text_provider_input",
        "_apply_wordpress_ai_site_knowledge_reference",
        "_wordpress_ai_generation_context_status",
        "_normalize_wordpress_ai_connector_provider_output",
        "_is_empty_wordpress_ai_connector_text_output",
        "_has_unbalanced_wordpress_ai_title_quote",
        "_normalize_wordpress_ai_meta_description",
        "_normalize_wordpress_ai_plain_text_output",
        "_normalize_wordpress_ai_classification_output",
        "_has_wordpress_ai_available_terms",
        "_parse_wordpress_ai_classification_json",
        "_sanitize_wordpress_ai_classification_suggestions",
        "_extract_wordpress_ai_classification_terms",
        "_strip_wordpress_ai_markdown",
        "_extract_wordpress_ai_task_candidate",
        "_extract_wordpress_ai_title_heading",
        "_extract_wordpress_ai_bold_candidate",
        "_extract_wordpress_ai_first_list_item",
        "_is_wordpress_ai_boilerplate_output",
        "_looks_like_wordpress_ai_title_bundle",
        "_strip_wordpress_ai_reasoning_noise",
        "_has_wordpress_ai_reasoning_noise",
        "_extract_wordpress_ai_cjk_text",
        "_trim_incomplete_wordpress_ai_tail",
        "_truncate_wordpress_ai_text",
        "_apply_wordpress_ai_connector_managed_policy",
    }

    assert service_methods.isdisjoint(removed_methods)
    assert {
        "build_provider_input",
        "apply_site_knowledge_reference",
        "normalize_provider_output",
        "is_empty_text_output",
        "apply_managed_policy",
    } <= runtime_methods
    assert not {
        module
        for module in imported_modules
        if any(
            module == prefix or module.startswith(f"{prefix}.")
            for prefix in forbidden_import_prefixes
        )
    }
    assert forbidden_transaction_calls == set()
    assert len(service_source.splitlines()) <= 8_296
