from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
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
    scene_request: dict[str, Any] = {
        "prompt": "为当前文章生成一个准确、简洁的标题。",
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


def test_title_provider_input_projects_only_operation_content() -> None:
    runtime = _runtime()
    provider_input = runtime.build_provider_input(_operation_payload())

    serialized = json.dumps(provider_input, ensure_ascii=False)
    assert provider_input["text"] == "为当前文章生成一个准确、简洁的标题。"
    assert provider_input["metadata"]["task"] == "title_generation"
    assert provider_input["metadata"]["suggestion_only"] is True
    assert provider_input["max_tokens"] == 48
    assert "site_alpha" not in serialized
    assert "alpha.example.test" not in serialized
    assert "object_revision" not in serialized
    assert "connector_version" not in serialized


def test_alt_text_provider_input_preserves_vision_shapes() -> None:
    runtime = _runtime()
    provider_input = runtime.build_provider_input(
        _operation_payload(
            task="alt_text_suggest",
            request={
                "prompt": "描述主要视觉内容",
                "image_url": "https://cdn.example.test/image.jpg",
                "thumbnail_url": "https://cdn.example.test/thumb.jpg",
                "filename": "image.jpg",
                "mime_type": "image/jpeg",
                "max_tokens": 120,
            },
        )
    )

    responses_content = provider_input["input"][0]["content"]
    chat_content = provider_input["messages"][0]["content"]
    assert responses_content[-1] == {
        "type": "input_image",
        "image_url": "https://cdn.example.test/image.jpg",
    }
    assert chat_content[-1] == {
        "type": "image_url",
        "image_url": {"url": "https://cdn.example.test/image.jpg"},
    }
    assert provider_input["max_tokens"] == 96
    assert provider_input["temperature"] == 0.0


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
