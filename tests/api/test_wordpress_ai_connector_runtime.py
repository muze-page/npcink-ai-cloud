from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.adapters.providers.base import (
    CatalogInstanceSeed,
    CatalogModelSeed,
    ProviderCatalogSnapshot,
    ProviderExecutionRequest,
    ProviderExecutionResult,
    ProviderMediaCandidate,
)
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import get_session, init_schema
from app.core.models import (
    CatalogInstance,
    CatalogModel,
    MediaArtifact,
    ProviderConnection,
    RoutingBinding,
    RoutingProfile,
    RunRecord,
    ServiceAuditEvent,
    Site,
)
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from app.domain.media_artifacts.input_loading import VISION_IMAGE_MAX_BYTES
from app.domain.media_artifacts.store import LocalVolumeArtifactStore
from app.domain.runtime.service import RuntimeService
from app.domain.site_knowledge.repository import SiteKnowledgeRepository
from app.domain.site_knowledge.service import SiteKnowledgeService
from app.domain.wordpress_ai_connector.contracts import (
    WP_AI_CONNECTOR_MAX_SOURCE_TEXT_CHARS,
)
from app.domain.wordpress_ai_connector.routing_profiles import (
    WP_AI_CONNECTOR_ALT_TEXT_VISION_PROFILE_ID,
    WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID,
    WP_AI_CONNECTOR_CLASSIFICATION_PROFILE_ID,
    WP_AI_CONNECTOR_EDITORIAL_PROFILE_ID,
    WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID,
    WP_AI_CONNECTOR_PROFILE_SPECS_BY_ID,
    WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
)
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_KEY_ID,
    TEST_PORTAL_JWT_SECRET,
    TEST_SECRET,
    build_auth_headers,
    build_internal_headers,
    merge_json_headers,
    seed_site_auth,
)

CONNECTOR_SITE_URL = "https://alpha.example.test"
CONNECTOR_VERSION = "1.0.0-test"
ALT_TEXT_SOURCE_ARTIFACT_ID = "art_0123456789abcdef0123456789abcdef"
ALT_TEXT_PROVIDER_ECHO_MARKER = "c2Vuc2l0aXZlLXByb3ZpZGVyLWVjaG8="
LONG_REWRITE_SOURCE_TEXT = (
    "<block-content>"
    + ("原始选中文本需要通过托管运行时完整改写并返回本地审阅。" * 80)
    + " long rewrite output"
    + "</block-content>"
)
LONG_REWRITE_OUTPUT_TEXT = "改写后的长选区保持完整、清晰且继续由 WordPress 本地审阅。" * 80


def _generated_png_bytes(*, width: int = 64, height: int = 48) -> bytes:
    image = Image.new("RGB", (width, height), color="blue")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _seed_alt_text_artifact(
    tmp_path: Path,
    database_url: str,
    *,
    artifact_id: str = ALT_TEXT_SOURCE_ARTIFACT_ID,
    site_id: str = "site_alpha",
    **overrides: Any,
) -> None:
    store = LocalVolumeArtifactStore(tmp_path / "artifacts")
    stored = store.put(
        io.BytesIO(_generated_png_bytes()),
        max_bytes=VISION_IMAGE_MAX_BYTES,
    )
    values: dict[str, Any] = {
        "artifact_id": artifact_id,
        "run_id": f"run_upload_{artifact_id}",
        "site_id": site_id,
        "media_kind": "image",
        "operation": "image.upload.v1",
        "content_type": "image/png",
        "byte_size": stored.byte_size,
        "storage_key": stored.storage_key,
        "status": "available",
        "format": "png",
        "width": 64,
        "height": 48,
        "checksum": stored.checksum,
        "expires_at": datetime.now(UTC) + timedelta(minutes=30),
    }
    values.update(overrides)
    with get_session(database_url) as session:
        session.add(MediaArtifact(**values))
        session.commit()


def test_wordpress_ai_connector_text_profiles_prefer_gpt55_with_fallbacks() -> None:
    short_text_spec = WP_AI_CONNECTOR_PROFILE_SPECS_BY_ID[WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID]
    editorial_spec = WP_AI_CONNECTOR_PROFILE_SPECS_BY_ID[WP_AI_CONNECTOR_EDITORIAL_PROFILE_ID]
    alt_text_vision_spec = WP_AI_CONNECTOR_PROFILE_SPECS_BY_ID[
        WP_AI_CONNECTOR_ALT_TEXT_VISION_PROFILE_ID
    ]
    classification_spec = WP_AI_CONNECTOR_PROFILE_SPECS_BY_ID[
        WP_AI_CONNECTOR_CLASSIFICATION_PROFILE_ID
    ]

    assert short_text_spec.ordered_tiers[:2] == ("free-gpt55", "hosted-free")
    assert "balanced" in short_text_spec.ordered_tiers
    assert editorial_spec.ordered_tiers[:2] == ("free-gpt55", "hosted-free")
    assert "balanced" in editorial_spec.ordered_tiers
    assert alt_text_vision_spec.execution_kind == "vision"
    assert alt_text_vision_spec.tasks == ("alt_text_suggest",)
    assert classification_spec.ordered_tiers[:2] == ("free-gpt55", "hosted-free")
    assert "balanced" in classification_spec.ordered_tiers


class WordPressAIConnectorTextProvider:
    provider_id = "openai"
    display_name = "WordPress AI Connector Text Provider"
    adapter_type = "openai"

    def __init__(self) -> None:
        self.requests: list[ProviderExecutionRequest] = []

    def fetch_catalog(self) -> ProviderCatalogSnapshot:
        return ProviderCatalogSnapshot(
            provider_id=self.provider_id,
            display_name=self.display_name,
            adapter_type=self.adapter_type,
            models=[
                CatalogModelSeed(
                    model_id="gpt-wp-ai-connector-test",
                    family="gpt-test",
                    feature="text",
                    status="available",
                    context_window=128000,
                    price_input=0.0,
                    price_output=0.0,
                    raw_json={"surface": "wordpress_ai_connector_test"},
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="openai-wp-ai-connector-test",
                            endpoint_variant="responses",
                            region="global",
                            capability_tags=["text", "balanced", "hosted-free"],
                            is_default=True,
                            weight=100,
                        )
                    ],
                ),
                CatalogModelSeed(
                    model_id="gpt-wp-ai-connector-fallback-test",
                    family="gpt-test",
                    feature="text",
                    status="available",
                    context_window=128000,
                    price_input=0.0,
                    price_output=0.0,
                    raw_json={"surface": "wordpress_ai_connector_fallback_test"},
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="zz-openai-wp-ai-connector-fallback-test",
                            endpoint_variant="responses",
                            region="global",
                            capability_tags=["text", "balanced", "hosted-free"],
                            is_default=False,
                            weight=50,
                        )
                    ],
                ),
                CatalogModelSeed(
                    model_id="gpt-wp-ai-vision-test",
                    family="gpt-vision-test",
                    feature="vision",
                    status="available",
                    context_window=128000,
                    price_input=0.0,
                    price_output=0.0,
                    raw_json={"surface": "wordpress_ai_connector_vision_test"},
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="openai-wp-ai-vision-test",
                            endpoint_variant="responses",
                            region="global",
                            capability_tags=["vision", "default", "quality"],
                            is_default=True,
                            weight=100,
                        )
                    ],
                ),
                CatalogModelSeed(
                    model_id="grok-imagine-wp-ai-test",
                    family="grok-imagine-test",
                    feature="image_generation",
                    status="available",
                    context_window=0,
                    price_input=0.0,
                    price_output=0.0,
                    raw_json={"surface": "wordpress_ai_connector_image_test"},
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="openai-wp-ai-image-test",
                            endpoint_variant="image_generations",
                            region="global",
                            capability_tags=[
                                "image_generation",
                                "z-image",
                                "quality",
                                "default",
                            ],
                            is_default=True,
                            weight=100,
                        )
                    ],
                ),
                CatalogModelSeed(
                    model_id="speech-wp-ai-connector-test",
                    family="speech-test",
                    feature="audio_generation",
                    status="available",
                    context_window=0,
                    price_input=0.0,
                    price_output=0.0,
                    raw_json={"surface": "wordpress_ai_connector_audio_test"},
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="openai-wp-ai-audio-test",
                            endpoint_variant="audio_generation",
                            region="global",
                            capability_tags=[
                                "audio_generation",
                                "default",
                                "balanced",
                                "narration",
                            ],
                            is_default=True,
                            weight=100,
                        )
                    ],
                ),
            ],
        )

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        self.requests.append(request)
        task = ""
        metadata = request.input_payload.get("metadata")
        if isinstance(metadata, dict):
            task = str(metadata.get("task") or "")
        source_text = str(request.input_payload.get("text") or "")
        output_text = "Npcink Cloud Addon: WordPress AI scene helper 说明：short title rationale"
        if task == "title_generation" and "reasoning leakage" in source_text:
            output_text = (
                "<think>The user wants one concise title. I should not expose "
                "reasoning.</think>\n\nCloud Runtime Connector Verified"
            )
        elif task == "title_generation" and "reasoning only" in source_text:
            if request.model_id == "gpt-wp-ai-connector-fallback-test":
                output_text = "Hosted Runtime Connector Verified"
            else:
                output_text = (
                    "<think> The user wants a concise WordPress post title about "
                    "verifying a hosted AI runtime connector."
                )
        elif task == "title_generation" and "title fragment" in source_text:
            if request.model_id == "gpt-wp-ai-connector-fallback-test":
                output_text = "Hosted Runtime Connector Verified"
            else:
                output_text = '"Verifying Your'
        elif task == "title_generation" and "title explanation" in source_text:
            output_text = (
                "How to Verify a Hosted AI Runtime Connector: Essential Steps "
                "This title balances clarity and search intent."
            )
        elif task == "title_generation" and "title bundle" in source_text:
            output_text = (
                "下面是基于内容整理的标题建议：\n"
                "## 标题建议\n"
                "1. WordPress AI 连接器测试：云端生成，本地审核\n"
                "2. 用云端运行时增强 WordPress 内容工作流"
            )
        elif task == "title_generation" and "title article boilerplate" in source_text:
            output_text = (
                "下面是我根据你提供的内容，整理润色后的文章版本，适合直接作为 "
                "WordPress 文章发布：\n---\n# WordPress - 流行的建站程序介绍与下载\n正文"
            )
        elif task == "title_generation" and "title summary tail" in source_text:
            output_text = (
                "WordPress - 流行的建站程序介绍与下载 摘要： "
                "WordPress是一款能让您建立出色网站、博客或应用的开源软件"
            )
        if task == "content_classification":
            output_text = (
                '{"suggestions":[{"term":"经验教程","confidence":0.8,"is_new":false}]}'
                if "<available-terms>" in source_text
                else "- WordPress AI\n- Cloud connector\n- Scene runtime"
            )
        elif task == "content_rewrite" and "rewrite variants" in source_text:
            output_text = (
                "可以优化为更自然、专业一点的表达，例如：\n\n"
                "**这个插件非常实用，能够帮助站长高效完成大量内容相关工作。**\n\n"
                "如果你愿意，我还可以继续帮你调整风格。"
            )
        elif task == "content_rewrite" and "rewrite alternatives concise" in source_text:
            output_text = (
                "The selected whole paragraph block is identified clearly. OR "
                "This is the chosen whole paragraph block. Both preserve the core "
                "meaning while explaining the alternatives."
            )
        elif task == "content_rewrite" and "rewrite alternatives" in source_text:
            output_text = (
                "The selected whole paragraph block is identified clearly. OR "
                "This is the chosen whole paragraph block. Both rephrasings preserve "
                "the original meaning while explaining the alternatives."
            )
        elif task == "content_rewrite" and "rewrite legitimate multi sentence" in source_text:
            output_text = (
                "The API supports v1 and v2. Both versions remain available during the "
                "documented migration window."
            )
        elif task == "content_rewrite" and "rewrite legitimate this rewrite" in source_text:
            output_text = (
                "The editor keeps the reviewed paragraph intact. This rewrite also "
                "preserves the second operational requirement."
            )
        elif task == "content_rewrite" and "rewrite legitimate both preserve review" in source_text:
            output_text = (
                "Use the local execution path. OR use the hosted runtime path. "
                "Both preserve review before applying changes."
            )
        elif task == "content_rewrite" and "rewrite legitimate bullet list" in source_text:
            output_text = (
                "- Keep the first editorial requirement intact.\n"
                "- Keep the second editorial requirement intact."
            )
        elif task == "content_rewrite" and "rewrite legitimate numbered list" in source_text:
            output_text = (
                "1. Keep the first migration step intact.\n"
                "2. Keep the second migration step intact."
            )
        elif task == "content_rewrite" and "rewrite legitimate inline bold" in source_text:
            output_text = (
                "Keep the local review step and preserve the **canonical audit trail**. "
                "Apply only after explicit approval."
            )
        elif task == "content_rewrite" and "long rewrite output" in source_text:
            output_text = LONG_REWRITE_OUTPUT_TEXT
        elif task == "content_summary":
            output_text = (
                "### **1. Fast editing support**\n"
                "Npcink Cloud Addon helps WordPress administrators generate useful "
                "scene-specific AI suggestions for titles, excerpts, summaries, SEO "
                "descriptions, and taxonomy classification without exposing chat or "
                "direct WordPress writes.\n\n### **2. Safe operations**"
            )
        elif task == "meta_description":
            if "meta boilerplate" in source_text:
                output_text = "以下是基于你提供的文章内容生成的结果："
            else:
                output_text = (
                    "**Npcink Cloud AI Connector: WordPress AI plugin scene runtime** "
                    "Npcink Cloud Addon connects verified Cloud settings to fixed WordPress "
                    "AI editing scenes without exposing chat or direct writes. ### Details"
                )
        if request.execution_kind == "vision":
            if "provider inline echo" in source_text:
                return ProviderExecutionResult(
                    output={
                        "output_text": ("data:image/png;base64," + ALT_TEXT_PROVIDER_ECHO_MARKER),
                        "model_id": request.model_id,
                        "messages": [
                            {
                                "role": "assistant",
                                "content": ALT_TEXT_PROVIDER_ECHO_MARKER,
                            }
                        ],
                        "usage": {"nested": {"private_echo": ALT_TEXT_PROVIDER_ECHO_MARKER}},
                    },
                    latency_ms=18,
                    tokens_in=42,
                    tokens_out=7,
                    cost=0.0,
                )
            if "provider nested echo" in source_text:
                return ProviderExecutionResult(
                    output={
                        "output_text": "Blue ceramic mug on a white table",
                        "model_id": "gpt-vision-test",
                        "messages": [
                            {
                                "role": "assistant",
                                "content": ALT_TEXT_PROVIDER_ECHO_MARKER,
                            }
                        ],
                        "output": {"raw_echo": ALT_TEXT_PROVIDER_ECHO_MARKER},
                        "usage": {"nested": {"private_echo": ALT_TEXT_PROVIDER_ECHO_MARKER}},
                    },
                    latency_ms=18,
                    tokens_in=42,
                    tokens_out=7,
                    cost=0.0,
                )
            return ProviderExecutionResult(
                output={
                    "output_text": "Blue ceramic mug on a white table",
                    "model_id": request.model_id,
                },
                latency_ms=18,
                tokens_in=42,
                tokens_out=7,
                cost=0.0,
            )
        if request.execution_kind == "image_generation":
            return ProviderExecutionResult(
                output={
                    "model_id": request.model_id,
                    "candidate_count": 1,
                    "usage": {},
                },
                media_candidates=(
                    ProviderMediaCandidate(
                        index=1,
                        content_bytes=_generated_png_bytes(),
                        source_url=None,
                        image_output_hosts=(),
                        claimed_mime_type="image/png",
                        revised_prompt="A clean WordPress editor workspace illustration.",
                        claimed_width=64,
                        claimed_height=48,
                    ),
                ),
                latency_ms=25,
                tokens_in=14,
                tokens_out=0,
                cost=0.0,
            )
        return ProviderExecutionResult(
            output={
                "output_text": output_text,
                "model_id": request.model_id,
                "usage": {
                    "completion_tokens_details": {
                        "reasoning_tokens": 42
                        if task == "title_generation" and "title fragment" in source_text
                        else 0
                    }
                },
            },
            latency_ms=12,
            tokens_in=24,
            tokens_out=8,
            cost=0.0,
        )


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'wp-ai-connector.sqlite3'}"


def _build_client(tmp_path: Path) -> tuple[str, TestClient, WordPressAIConnectorTextProvider]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )
    provider = WordPressAIConnectorTextProvider()
    CatalogService(database_url, providers={"openai": provider}).refresh_catalog()
    with get_session(database_url) as session:
        site = session.get(Site, "site_alpha")
        assert site is not None
        site.site_url = CONNECTOR_SITE_URL
        session.add(
            ProviderConnection(
                connection_id="openai",
                provider_type="openai_compatible",
                display_name="OpenAI",
                enabled=True,
                base_url="https://api.openai.test/v1",
                config_json={
                    "provider_id": "openai",
                    "kind": "openai_compatible",
                    "capability_ids": [
                        "text_generation",
                        "vision",
                        "image_generation",
                        "audio_generation",
                    ],
                    "runtime_profile_ids": [
                        WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
                        WP_AI_CONNECTOR_ALT_TEXT_VISION_PROFILE_ID,
                        WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID,
                        WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID,
                    ],
                    "model_ids": [
                        "gpt-wp-ai-connector-test",
                        "gpt-wp-ai-connector-fallback-test",
                        "gpt-wp-ai-vision-test",
                        "grok-imagine-wp-ai-test",
                        "speech-wp-ai-connector-test",
                    ],
                },
                secret_ciphertext="configured-in-test",
                status="ready",
                source_role="execution_source",
                metadata_json={},
            )
        )
        session.commit()
    settings = Settings(
        _env_file=None,
        project_name="Npcink AI Cloud WordPress AI Connector Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        artifact_store_root=str(tmp_path / "artifacts"),
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
    )
    client = TestClient(
        create_app(
            CloudServices(
                settings=settings,
                providers={"openai": provider},
            )
        )
    )
    return database_url, client, provider


def _payload(input_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    operation_contract: dict[str, Any] = {
        "contract_version": "wordpress_operation.v1",
        "task": "title_generation",
        "request": {
            "source_text": (
                "<content>Npcink Cloud Addon provides reviewable WordPress AI "
                "suggestions through a hosted runtime.</content>"
            ),
        },
    }
    input_payload: dict[str, Any] = {
        "site_url": CONNECTOR_SITE_URL,
        "platform_kind": "wordpress",
        "connector_id": "npcink-cloud-addon",
        "connector_version": CONNECTOR_VERSION,
        "suggestion_only": True,
        "operation_contract": operation_contract,
    }
    overrides = dict(input_overrides or {})
    if "task" in overrides:
        operation_contract["task"] = overrides.pop("task")
    if "request" in overrides:
        operation_contract["request"] = overrides.pop("request")
    input_payload.update(overrides)
    return {
        "site_id": "site_alpha",
        "ability_name": "npcink-cloud/connector-runtime",
        "contract_version": "cloud_connector_runtime.v1",
        "channel": "editor",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "execution_pattern": "inline",
        "storage_mode": "result_only",
        "data_classification": "public_site_content",
        "timeout_seconds": 60,
        "retry_max": 0,
        "retention_ttl": 86400,
        "input": input_payload,
        "policy": {"allow_fallback": False},
    }


def _image_payload(input_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    input_payload: dict[str, Any] = {
        "contract_version": "image_generation_request.v1",
        "source_surface": "wordpress_ai_connector",
        "connector_id": "npcink-cloud",
        "task": "image_generation",
        "prompt": "A clean media-library illustration of a WordPress editor workspace.",
        "n": 1,
        "aspect_ratio": "16:9",
        "resolution": "medium",
    }
    input_payload.update(input_overrides or {})
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
        "input": input_payload,
        "policy": {"allow_fallback": False},
    }


def _alt_text_payload(input_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    operation_contract: dict[str, Any] = {
        "contract_version": "wordpress_operation.v1",
        "task": "alt_text_suggest",
        "request": {
            "prompt": "Generate accessible alt text for this media item.",
            "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
            "filename": "blue-mug.jpg",
            "title": "Blue mug",
            "existing_alt": "",
            "existing_caption": "",
            "locale": "en_US",
        },
    }
    input_payload: dict[str, Any] = {
        "site_url": CONNECTOR_SITE_URL,
        "platform_kind": "wordpress",
        "connector_id": "npcink-cloud-addon",
        "connector_version": CONNECTOR_VERSION,
        "suggestion_only": True,
        "operation_contract": operation_contract,
    }
    overrides = dict(input_overrides or {})
    if "request" in overrides:
        operation_contract["request"] = overrides.pop("request")
    input_payload.update(overrides)
    return {
        "site_id": "site_alpha",
        "ability_name": "npcink-cloud/connector-runtime",
        "contract_version": "cloud_connector_runtime.v1",
        "channel": "editor",
        "execution_kind": "vision",
        "profile_id": "text.balanced",
        "execution_pattern": "inline",
        "storage_mode": "result_only",
        "data_classification": "internal",
        "timeout_seconds": 60,
        "retry_max": 0,
        "retention_ttl": 86400,
        "input": input_payload,
        "policy": {"allow_fallback": False},
    }


def _execute(
    client: TestClient,
    payload: dict[str, Any],
    *,
    idempotency_key: str = "wp-ai-connector-idem",
    trace_id: str = "tracewpai000000000000000000000001",
) -> Any:
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            body=body,
            site_id="site_alpha",
            key_id=TEST_KEY_ID,
            secret=TEST_SECRET,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
        )
    )
    return client.post("/v1/runtime/execute", content=body, headers=headers)


def _resolve(
    client: TestClient,
    payload: dict[str, Any],
    *,
    idempotency_key: str,
) -> Any:
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/resolve",
            body=body,
            site_id="site_alpha",
            key_id=TEST_KEY_ID,
            secret=TEST_SECRET,
            idempotency_key=idempotency_key,
            trace_id="tracewpairesolve0000000000000001",
        )
    )
    return client.post("/v1/runtime/resolve", content=body, headers=headers)


def _get_result(
    client: TestClient,
    run_id: str,
    *,
    site_id: str = "site_alpha",
    key_id: str = TEST_KEY_ID,
    secret: str = TEST_SECRET,
) -> Any:
    path = f"/v1/runs/{run_id}/result"
    headers = build_auth_headers(
        "GET",
        path,
        site_id=site_id,
        key_id=key_id,
        secret=secret,
        trace_id="tracewpairesult0000000000000001",
    )
    return client.get(path, headers=headers)


def test_wordpress_ai_connector_runtime_executes_scene_bound_text(tmp_path: Path) -> None:
    database_url, client, provider = _build_client(tmp_path)

    response = _execute(client, _payload())

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    result = data["result"]
    assert set(result) == {
        "contract_version",
        "site_id",
        "site_url",
        "platform_kind",
        "connector_id",
        "connector_version",
        "suggestion_only",
        "operation_contract",
        "output",
    }
    assert result["contract_version"] == "cloud_connector_result.v1"
    assert result["site_id"] == "site_alpha"
    assert result["site_url"] == CONNECTOR_SITE_URL
    assert result["platform_kind"] == "wordpress"
    assert result["connector_id"] == "npcink-cloud-addon"
    assert result["connector_version"] == CONNECTOR_VERSION
    assert result["suggestion_only"] is True
    assert result["operation_contract"] == {
        "contract_version": "wordpress_operation.v1",
        "task": "title_generation",
    }
    assert "request" not in result["operation_contract"]
    assert result["output"]["output_text"] == ("Npcink Cloud Addon: WordPress AI scene helper")
    assert data["execution_context"]["contract_version"] == "cloud_connector_runtime.v1"
    assert data["execution_context"]["ability_family"] == "text"
    assert data["execution_context"]["data_classification"] == "public_site_content"
    assert provider.requests[0].ability_name == "npcink-cloud/connector-runtime"
    assert provider.requests[0].execution_kind == "text"
    assert provider.requests[0].profile_id == WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID
    assert provider.requests[0].timeout_ms == 45000
    provider_input = provider.requests[0].input_payload
    assert "messages" not in provider_input
    assert "tools" not in provider_input
    assert "Generate exactly one concise title" in provider_input["input"]
    assert provider_input["text"] == (
        "<content>Npcink Cloud Addon provides reviewable WordPress AI suggestions "
        "through a hosted runtime.</content>"
    )
    assert provider_input["input"].count(provider_input["text"]) == 1
    assert provider_input["max_tokens"] == 48
    assert provider_input["max_output_tokens"] == 48
    assert provider_input["metadata"]["source_surface"] == "wordpress_ai_connector"
    assert provider_input["metadata"]["suggestion_only"] is True
    assert "site_url" not in provider_input
    assert "connector_id" not in provider_input
    assert "operation_contract" not in provider_input

    with get_session(database_url) as session:
        run = session.execute(select(RunRecord)).scalar_one()
        assert run.ability_name == "npcink-cloud/connector-runtime"
        assert run.channel == "editor"
        assert run.execution_kind == "text"
        assert run.profile_id == WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID
        assert run.policy_json["managed_surface"] == "hosted_runtime_profiles"
        assert run.policy_json["platform_kind"] == "wordpress"
        assert run.policy_json["connector_id"] == "wordpress_ai_connector"
        assert run.policy_json["operation_contract_version"] == ("wordpress_operation.v1")
        assert run.policy_json["task_group"] == "short_text"
        assert run.policy_json["routing_intent"] == "content.short_text"
        assert run.policy_json["timeout_ms"] == 45000
        assert run.policy_json["execution_contract"]["contract_version"] == (
            "cloud_connector_runtime.v1"
        )
        assert run.policy_json["execution_contract"]["managed_surface"] == (
            "hosted_runtime_profiles"
        )
        assert run.policy_json["execution_contract"]["platform_kind"] == "wordpress"
        assert run.policy_json["execution_contract"]["connector_id"] == ("wordpress_ai_connector")
        assert run.policy_json["execution_contract"]["operation_contract_version"] == (
            "wordpress_operation.v1"
        )
        assert run.policy_json["execution_contract"]["task_group"] == "short_text"
        assert run.policy_json["execution_contract"]["routing_intent"] == "content.short_text"
        assert run.result_json == result


@pytest.mark.parametrize(
    ("task", "raw_source_text", "expected_source_text", "expected_profile_id"),
    [
        (
            "title_generation",
            "  <content>Current article content for a title.</content>  ",
            "<content>Current article content for a title.</content>",
            WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
        ),
        (
            "content_summary",
            "<content>Current article content that needs a concise summary.</content>",
            "<content>Current article content that needs a concise summary.</content>",
            WP_AI_CONNECTOR_EDITORIAL_PROFILE_ID,
        ),
        (
            "content_rewrite",
            "<block-content>rewrite variants selected paragraph.</block-content>",
            "<block-content>rewrite variants selected paragraph.</block-content>",
            WP_AI_CONNECTOR_EDITORIAL_PROFILE_ID,
        ),
    ],
)
def test_p2_text_tasks_project_source_text_once_with_runtime_evidence(
    tmp_path: Path,
    task: str,
    raw_source_text: str,
    expected_source_text: str,
    expected_profile_id: str,
) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "task": task,
            "request": {
                "source_text": raw_source_text,
                "system_instruction": "  Apply the local Ability instruction.  \n",
            },
        }
    )

    response = _execute(client, payload, idempotency_key=f"p2-source-text-{task}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    assert data["profile_id"] == expected_profile_id
    assert data["provider_id"] == "openai"
    assert data["model_id"] == "gpt-wp-ai-connector-test"
    assert data["instance_id"] == "openai-wp-ai-connector-test"
    assert data["run_id"].startswith("run_")
    assert data["result"]["suggestion_only"] is True
    assert data["result"]["operation_contract"]["task"] == task
    provider_input = provider.requests[0].input_payload
    assert provider_input["text"] == expected_source_text
    assert provider_input["input"].count(expected_source_text) == 1
    assert provider_input["input"].count("Apply the local Ability instruction.") == 1
    assert "prompt" not in provider_input


@pytest.mark.parametrize(
    "task",
    ["title_generation", "content_summary", "content_rewrite"],
)
@pytest.mark.parametrize(
    ("request_payload", "expected_error"),
    [
        ({}, "wordpress_operation.source_text_required"),
        ({"source_text": ""}, "wordpress_operation.source_text_required"),
        ({"source_text": "   \n\t"}, "wordpress_operation.source_text_required"),
        ({"source_text": 42}, "wordpress_operation.source_text_required"),
        ({"source_text": "x" * 12001}, "wordpress_operation.source_text_too_large"),
        (
            {"source_text": "valid source", "prompt": "legacy prompt"},
            "wordpress_operation.prompt_forbidden",
        ),
        (
            {"source_text": "valid source", "system_instruction": 42},
            "wordpress_operation.system_instruction_invalid",
        ),
        (
            {"source_text": "valid source", "system_instruction": "x" * 12001},
            "wordpress_operation.system_instruction_too_large",
        ),
    ],
)
def test_p2_text_source_contract_fails_closed_before_provider(
    tmp_path: Path,
    task: str,
    request_payload: dict[str, object],
    expected_error: str,
) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload({"task": task, "request": dict(request_payload)})

    response = _execute(
        client,
        payload,
        idempotency_key=f"p2-source-contract-{task}-{expected_error}",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == expected_error
    assert provider.requests == []


def test_p2_text_task_allows_trimmed_empty_system_instruction(tmp_path: Path) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "task": "content_summary",
            "request": {
                "source_text": "<content>Current article content.</content>",
                "system_instruction": "  \n\t ",
            },
        }
    )

    response = _execute(
        client,
        payload,
        idempotency_key="p2-empty-system-instruction",
    )

    assert response.status_code == 200
    assert provider.requests[0].input_payload["text"] == (
        "<content>Current article content.</content>"
    )
    assert "  \n\t " not in provider.requests[0].input_payload["input"]


def test_connector_runtime_uses_only_normalized_envelope_values(tmp_path: Path) -> None:
    database_url, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "site_url": f"  {CONNECTOR_SITE_URL}  ",
            "connector_version": "  1.2.3-test  ",
            "task": "  title_generation  ",
            "object_ref": {
                "object_type": "  post  ",
                "object_id": "  42  ",
                "object_revision": "  7  ",
            },
        }
    )

    response = _execute(
        client,
        payload,
        idempotency_key="connector-normalized-envelope",
    )

    assert response.status_code == 200
    result = response.json()["data"]["result"]
    assert result["site_url"] == CONNECTOR_SITE_URL
    assert result["connector_version"] == "1.2.3-test"
    assert result["object_ref"] == {
        "object_type": "post",
        "object_id": "42",
        "object_revision": "7",
    }
    assert result["operation_contract"] == {
        "contract_version": "wordpress_operation.v1",
        "task": "title_generation",
    }
    assert provider.requests[0].profile_id == WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID
    assert provider.requests[0].input_payload["metadata"]["task"] == "title_generation"
    assert "site_url" not in provider.requests[0].input_payload
    assert "connector_version" not in provider.requests[0].input_payload
    with get_session(database_url) as session:
        run = session.execute(select(RunRecord)).scalar_one()
        assert run.result_json == result


@pytest.mark.parametrize(
    ("case", "expected_error"),
    [
        ("unknown_outer", "connector_runtime.fields_forbidden"),
        ("old_outer_shape", "connector_runtime.fields_required"),
        ("connector_id", "connector_runtime.connector_id_invalid"),
        ("connector_version", "connector_runtime.string_field_invalid"),
        ("suggestion_only", "connector_runtime.suggestion_only_required"),
        ("platform_kind", "connector_runtime.platform_kind_invalid"),
        ("site_url", "connector_runtime.site_url_mismatch"),
        ("channel", "connector_runtime.channel_invalid"),
        ("envelope_version", "connector_runtime.contract_mismatch"),
        ("operation_fields", "wordpress_operation.fields_invalid"),
        ("operation_version", "wordpress_operation.contract_mismatch"),
        ("object_ref_fields", "connector_runtime.object_ref_fields_invalid"),
        ("object_ref_empty", "connector_runtime.string_field_invalid"),
    ],
)
def test_connector_runtime_contract_fails_closed(
    tmp_path: Path,
    case: str,
    expected_error: str,
) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload()
    input_payload = payload["input"]
    assert isinstance(input_payload, dict)
    operation_contract = input_payload["operation_contract"]
    assert isinstance(operation_contract, dict)

    if case == "unknown_outer":
        input_payload["unexpected"] = True
    elif case == "old_outer_shape":
        input_payload.pop("operation_contract")
        input_payload["task"] = "title_generation"
        input_payload["request"] = {"prompt": "Suggest a title."}
    elif case == "connector_id":
        input_payload["connector_id"] = "unknown-connector"
    elif case == "connector_version":
        input_payload["connector_version"] = ""
    elif case == "suggestion_only":
        input_payload["suggestion_only"] = False
    elif case == "platform_kind":
        input_payload["platform_kind"] = "typecho"
    elif case == "site_url":
        input_payload["site_url"] = "https://other.example.test"
    elif case == "channel":
        payload["channel"] = "api"
    elif case == "envelope_version":
        payload["contract_version"] = "cloud_connector_runtime.v2"
    elif case == "operation_fields":
        operation_contract["unknown"] = True
    elif case == "operation_version":
        operation_contract["contract_version"] = "wordpress_operation.v2"
    elif case == "object_ref_fields":
        input_payload["object_ref"] = {"object_type": "post", "object_id": "42"}
    elif case == "object_ref_empty":
        input_payload["object_ref"] = {
            "object_type": "post",
            "object_id": "",
            "object_revision": "7",
        }

    response = _execute(
        client,
        payload,
        idempotency_key=f"connector-contract-{case}",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == expected_error
    assert provider.requests == []


def test_connector_runtime_requires_and_binds_explicit_site_id(tmp_path: Path) -> None:
    _, client, provider = _build_client(tmp_path)
    missing_site_payload = _payload()
    missing_site_payload.pop("site_id")

    missing_response = _execute(
        client,
        missing_site_payload,
        idempotency_key="connector-site-missing",
    )

    assert missing_response.status_code == 422
    assert provider.requests == []

    mismatched_site_payload = _payload()
    mismatched_site_payload["site_id"] = "site_other"
    mismatch_response = _execute(
        client,
        mismatched_site_payload,
        idempotency_key="connector-site-mismatch",
    )

    assert mismatch_response.status_code == 400
    assert mismatch_response.json()["error_code"] == "auth.site_mismatch"
    assert provider.requests == []


def test_connector_runtime_rejects_unknown_public_payload_field(tmp_path: Path) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload()
    payload["unexpected_top_level_field"] = True

    response = _execute(
        client,
        payload,
        idempotency_key="connector-top-level-extra",
    )

    assert response.status_code == 422
    assert provider.requests == []


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("source_surface", "wordpress_ai_connector"),
        ("connector_id", "npcink-cloud-addon"),
        ("connector_version", "1.2.3"),
        ("site_url", CONNECTOR_SITE_URL),
        ("platform_kind", "wordpress"),
        ("object_ref", {"object_type": "post"}),
        ("operation_contract", {"task": "title_generation"}),
        ("expected_response_contract", "cloud_connector_result.v1"),
        ("suggestion_only", False),
        ("write_posture", "suggestion_only"),
        ("no_conversation", True),
        ("direct_wordpress_write", True),
        ("nested_direct_wordpress_write", True),
    ],
)
def test_wordpress_operation_rejects_request_control_fields(
    tmp_path: Path,
    field_name: str,
    field_value: object,
) -> None:
    _, client, provider = _build_client(tmp_path)
    request_payload: dict[str, object] = {
        "source_text": "<content>Current WordPress article content.</content>"
    }
    if field_name == "nested_direct_wordpress_write":
        request_payload["nested"] = {"direct_wordpress_write": field_value}
    else:
        request_payload[field_name] = field_value
    payload = _payload({"request": request_payload})

    response = _execute(
        client,
        payload,
        idempotency_key=f"connector-request-control-{field_name}",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == ("wordpress_operation.control_field_forbidden")
    assert provider.requests == []


def test_connector_runtime_rejects_image_generation_operation(tmp_path: Path) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "task": "image_generation",
            "request": {"prompt": "Generate an image."},
        }
    )

    response = _execute(
        client,
        payload,
        idempotency_key="connector-unreachable-image-generation",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "wordpress_operation.task_not_allowed"
    assert provider.requests == []


def test_connector_runtime_rejects_authenticated_site_platform_drift(
    tmp_path: Path,
) -> None:
    database_url, client, provider = _build_client(tmp_path)
    with get_session(database_url) as session:
        site = session.get(Site, "site_alpha")
        assert site is not None
        site.platform_kind = "typecho"
        session.commit()

    response = _execute(
        client,
        _payload(),
        idempotency_key="connector-platform-drift",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "connector_runtime.platform_kind_mismatch"
    assert provider.requests == []


def test_connector_runtime_preserves_exact_object_reference(tmp_path: Path) -> None:
    database_url, client, _ = _build_client(tmp_path)
    object_ref = {
        "object_type": "post",
        "object_id": "42",
        "object_revision": "7",
    }
    response = _execute(
        client,
        _payload({"object_ref": object_ref}),
        idempotency_key="connector-object-ref",
    )

    assert response.status_code == 200
    result = response.json()["data"]["result"]
    assert result["object_ref"] == object_ref
    assert set(result["object_ref"]) == {
        "object_type",
        "object_id",
        "object_revision",
    }
    with get_session(database_url) as session:
        run = session.execute(select(RunRecord)).scalar_one()
        assert run.result_json == result


def test_connector_runtime_replay_returns_identical_persisted_result(
    tmp_path: Path,
) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload()

    first = _execute(
        client,
        payload,
        idempotency_key="connector-replay",
        trace_id="tracewpaireplayone00000000000001",
    )
    replay = _execute(
        client,
        payload,
        idempotency_key="connector-replay",
        trace_id="tracewpaireplaytwo00000000000002",
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["data"]["idempotent_replay"] is True
    assert replay.json()["data"]["result"] == first.json()["data"]["result"]
    assert len(provider.requests) == 1


def test_connector_runtime_no_store_uses_normalized_transient_and_durable_envelopes(
    tmp_path: Path,
) -> None:
    database_url, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "connector_version": "  3.0.0-no-store  ",
            "task": "  title_generation  ",
        }
    )
    payload["storage_mode"] = "no_store"

    first = _execute(
        client,
        payload,
        idempotency_key="connector-no-store",
        trace_id="tracewpainostoreone000000000001",
    )

    assert first.status_code == 200
    transient_result = first.json()["data"]["result"]
    assert transient_result["connector_version"] == "3.0.0-no-store"
    assert transient_result["operation_contract"]["task"] == "title_generation"
    assert transient_result["output"]["output_text"] == (
        "Npcink Cloud Addon: WordPress AI scene helper"
    )

    run_id = first.json()["data"]["run_id"]
    polled = _get_result(client, run_id)
    assert polled.status_code == 200
    durable_result = polled.json()["data"]["result"]
    assert durable_result["connector_version"] == "3.0.0-no-store"
    assert durable_result["operation_contract"]["task"] == "title_generation"
    assert durable_result["output"] == {"stored": False, "status": "omitted"}

    replay = _execute(
        client,
        payload,
        idempotency_key="connector-no-store",
        trace_id="tracewpainostoretwo000000000002",
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["idempotent_replay"] is True
    assert replay.json()["data"]["result"] == durable_result
    assert len(provider.requests) == 1
    with get_session(database_url) as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        assert run.result_json == durable_result


def test_connector_runtime_queued_worker_persists_pollable_result(tmp_path: Path) -> None:
    database_url, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "site_url": f"  {CONNECTOR_SITE_URL}  ",
            "connector_version": "  2.0.0-worker  ",
            "task": "  title_generation  ",
            "object_ref": {
                "object_type": "  post  ",
                "object_id": "  84  ",
                "object_revision": "  9  ",
            },
        }
    )
    payload["execution_pattern"] = "whole_run_offload"
    payload["task_backend"] = {
        "enabled": True,
        "mode": "queue",
        "callback_mode": "polling_preferred",
        "polling_interval_sec": 1,
    }

    queued_response = _execute(
        client,
        payload,
        idempotency_key="connector-queued",
    )

    assert queued_response.status_code == 200
    queued_data = queued_response.json()["data"]
    assert queued_data["status"] == "queued"
    assert queued_data["result"] == {}
    assert provider.requests == []

    settings = Settings(
        _env_file=None,
        project_name="Npcink AI Cloud Connector Worker Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
    )
    worker = RuntimeService(
        database_url,
        settings=settings,
        providers={"openai": provider},
    )
    processed = worker.process_queued_runs(max_runs=1, timeout_seconds=0)

    assert processed == [
        {
            "run_id": queued_data["run_id"],
            "status": "succeeded",
            "trace_id": queued_data["trace_id"],
        }
    ]
    result_response = _get_result(client, queued_data["run_id"])
    assert result_response.status_code == 200
    result = result_response.json()["data"]["result"]
    assert result["contract_version"] == "cloud_connector_result.v1"
    assert result["site_id"] == "site_alpha"
    assert result["site_url"] == CONNECTOR_SITE_URL
    assert result["connector_version"] == "2.0.0-worker"
    assert result["object_ref"] == {
        "object_type": "post",
        "object_id": "84",
        "object_revision": "9",
    }
    assert result["operation_contract"] == {
        "contract_version": "wordpress_operation.v1",
        "task": "title_generation",
    }
    assert result["output"]["output_text"] == ("Npcink Cloud Addon: WordPress AI scene helper")
    assert provider.requests[0].profile_id == WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID
    assert provider.requests[0].input_payload["metadata"]["task"] == "title_generation"
    assert "site_url" not in provider.requests[0].input_payload
    with get_session(database_url) as session:
        run = session.get(RunRecord, queued_data["run_id"])
        assert run is not None
        assert run.input_json == {}
        assert run.execution_input_ciphertext is None
        assert run.result_json == result


def test_connector_runtime_worker_fails_closed_on_damaged_execution_input(
    tmp_path: Path,
) -> None:
    database_url, client, provider = _build_client(tmp_path)
    payload = _payload()
    payload["execution_pattern"] = "whole_run_offload"
    payload["task_backend"] = {
        "enabled": True,
        "mode": "queue",
        "callback_mode": "polling_preferred",
        "polling_interval_sec": 1,
    }
    queued_response = _execute(
        client,
        payload,
        idempotency_key="connector-damaged-worker-input",
    )
    assert queued_response.status_code == 200
    run_id = queued_response.json()["data"]["run_id"]
    with get_session(database_url) as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        run.execution_input_ciphertext = "damaged-ciphertext"
        session.commit()

    worker = RuntimeService(
        database_url,
        settings=Settings(
            _env_file=None,
            project_name="Npcink AI Cloud Damaged Connector Worker Test",
            environment="test",
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
            admin_session_secret=TEST_ADMIN_SESSION_SECRET,
            portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        ),
        providers={"openai": provider},
    )
    processed = worker.process_queued_runs(max_runs=1, timeout_seconds=0)

    assert processed[0]["run_id"] == run_id
    assert processed[0]["status"] == "failed"
    assert provider.requests == []
    with get_session(database_url) as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        assert run.status == "failed"
        assert run.error_code == "connector_runtime.execution_input_invalid"
        assert run.input_json == {}
        assert run.execution_input_ciphertext is None


def test_connector_runtime_result_is_site_isolated(tmp_path: Path) -> None:
    database_url, client, _ = _build_client(tmp_path)
    response = _execute(
        client,
        _payload(),
        idempotency_key="connector-site-isolation",
    )
    assert response.status_code == 200
    run_id = response.json()["data"]["run_id"]

    beta_secret = "npcink-cloud-beta-secret-for-hmac-sha256-32b"
    seed_site_auth(
        database_url,
        site_id="site_beta",
        key_id="key_beta",
        secret=beta_secret,
        scopes=["runtime:read"],
    )
    isolated_response = _get_result(
        client,
        run_id,
        site_id="site_beta",
        key_id="key_beta",
        secret=beta_secret,
    )

    assert isolated_response.status_code == 404
    assert isolated_response.json()["error_code"] == "runtime.run_not_found"


def test_wordpress_ai_connector_runtime_accepts_registered_task_projection(
    tmp_path: Path,
) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "task": "seo_headline",
            "request": {
                "prompt": "Write one accurate headline for this article.",
                "site_knowledge_reference": {
                    "enabled": True,
                    "mode": "site_title_style",
                },
                "task_contract": {
                    "contract_version": "ai_task_contract.v1",
                    "ability_name": "example/seo-headline",
                    "task": "seo_headline",
                    "task_family": "generation",
                    "context_requirements": ["current_content", "site_style_profile"],
                    "constraints": ["single_value", "source_grounded", "no_new_numbers"],
                    "output_schema": {"type": "string"},
                    "write_posture": "suggestion_only",
                },
            },
        }
    )

    response = _execute(client, payload, idempotency_key="wp-ai-registered-task")

    assert response.status_code == 200
    provider_input = provider.requests[0].input_payload
    assert provider_input["metadata"]["ability_name"] == "example/seo-headline"
    assert provider_input["metadata"]["task_family"] == "generation"
    assert provider_input["metadata"]["task_constraints"] == [
        "no_new_numbers",
        "single_value",
        "source_grounded",
    ]
    assert "Generate the requested value" in provider_input["input"]
    assert "Return exactly one value" in provider_input["input"]
    assert provider_input["max_tokens"] == 160
    assert provider_input["metadata"]["generation_context_reason"] != ("task_policy_unavailable")


def test_wordpress_ai_connector_runtime_rejects_open_ended_task_projection(
    tmp_path: Path,
) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "task": "general_chat",
            "request": {
                "prompt": "Talk about anything.",
                "task_contract": {
                    "contract_version": "ai_task_contract.v1",
                    "ability_name": "example/general-chat",
                    "task": "general_chat",
                    "task_family": "chat",
                    "context_requirements": ["none"],
                    "constraints": [],
                    "output_schema": {"type": "string"},
                    "write_posture": "suggestion_only",
                },
            },
        }
    )

    response = _execute(client, payload, idempotency_key="wp-ai-open-task")

    assert response.status_code == 400
    assert response.json()["error_code"] == "wordpress_operation.ai_task_contract_identity_invalid"
    assert provider.requests == []


def test_wordpress_ai_connector_title_generation_uses_hidden_site_title_style(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client, provider = _build_client(tmp_path)
    captured_input: dict[str, Any] = {}

    def fake_site_knowledge_execute(
        self: SiteKnowledgeService,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del self
        captured_input.update(kwargs["input_payload"])
        return {
            "status": "ready",
            "intent": "writing_context",
            "evidence_gate": {"status": "passed"},
            "results": [
                {
                    "post_id": 11,
                    "title": "用云端能力增强 WordPress 编辑体验",
                    "chunk": "This chunk must not be sent to the title model.",
                    "score": 0.82,
                },
                {
                    "post_id": 11,
                    "title": "用云端能力增强 WordPress 编辑体验",
                    "chunk": "Duplicate chunk.",
                    "score": 0.8,
                },
                {
                    "post_id": 12,
                    "title": "让 AI 更懂你的网站内容",
                    "chunk": "Another private reference chunk.",
                    "score": 0.76,
                },
            ],
        }

    monkeypatch.setattr(SiteKnowledgeService, "execute", fake_site_knowledge_execute)
    payload = _payload(
        {
            "request": {
                "source_text": (
                    "<content>An article about using site-aware AI in WordPress.</content>"
                ),
                "site_knowledge_reference": {
                    "enabled": True,
                    "mode": "site_title_style",
                },
            }
        }
    )

    response = _execute(client, payload, idempotency_key="wp-ai-title-site-style")

    assert response.status_code == 200
    assert response.json()["data"]["result"]["output"]["output_text"] == (
        "Npcink Cloud Addon: WordPress AI scene helper"
    )
    assert captured_input["intent"] == "writing_context"
    assert captured_input["max_results"] == 12
    provider_input = provider.requests[0].input_payload
    assert "用云端能力增强 WordPress 编辑体验" not in provider_input["input"]
    assert "让 AI 更懂你的网站内容" not in provider_input["input"]
    assert "Aggregate style profile" in provider_input["input"]
    assert '"length_preference"' in provider_input["input"]
    assert '"sample_count"' not in provider_input["input"]
    assert "This chunk must not be sent" not in provider_input["input"]
    assert "generation_context.v1" in provider_input["input"]
    assert provider_input["input"].index("generation_context.v1") < provider_input["input"].index(
        "Scene input:"
    )
    assert "Never add a name, number, claim, or event" in provider_input["input"]
    assert provider_input["metadata"]["site_knowledge_reference"] == "applied"
    assert provider_input["metadata"]["site_knowledge_reference_count"] == 1
    assert provider_input["metadata"]["generation_context_status"] == "applied"
    assert provider_input["metadata"]["generation_context_reason"] == "references_applied"


def test_wordpress_ai_connector_title_generation_silently_falls_back_when_site_knowledge_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client, provider = _build_client(tmp_path)

    def fail_site_knowledge_execute(
        self: SiteKnowledgeService,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del self, kwargs
        raise RuntimeError("Unexpected Site Knowledge failure.")

    monkeypatch.setattr(SiteKnowledgeService, "execute", fail_site_knowledge_execute)
    payload = _payload(
        {
            "request": {
                "source_text": "<content>Current WordPress post content.</content>",
                "site_knowledge_reference": {
                    "enabled": True,
                    "mode": "site_title_style",
                },
            }
        }
    )

    response = _execute(client, payload, idempotency_key="wp-ai-title-site-style-fallback")

    assert response.status_code == 200
    provider_input = provider.requests[0].input_payload
    assert "Generation context" not in provider_input["input"]
    assert "site_knowledge_reference" not in provider_input["metadata"]
    assert provider_input["metadata"]["generation_context_status"] == "unavailable"
    assert provider_input["metadata"]["generation_context_reason"] == "retrieval_failed"


@pytest.mark.parametrize(
    ("task", "mode", "expected_marker"),
    [
        ("excerpt_generation", "site_excerpt_style", "Aggregate style profile"),
        ("meta_description", "site_meta_style", "Aggregate style profile"),
        ("content_summary", "site_summary_style", "Aggregate style profile"),
        (
            "content_classification",
            "site_taxonomy_history",
            "Existing taxonomy candidates",
        ),
    ],
)
def test_wordpress_ai_connector_uses_task_bound_hidden_site_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    task: str,
    mode: str,
    expected_marker: str,
) -> None:
    _, client, provider = _build_client(tmp_path)

    def fake_site_knowledge_execute(
        self: SiteKnowledgeService,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del self, kwargs
        return {
            "status": "ready",
            "evidence_gate": {"status": "passed"},
            "results": [
                {
                    "post_id": 11,
                    "title": "Historical title",
                    "chunk": "Historical facts must remain hidden.",
                    "score": 0.91,
                }
            ],
        }

    def fake_reference_metadata(
        self: SiteKnowledgeRepository,
        *,
        site_id: str,
        post_ids: list[int],
    ) -> dict[int, dict[str, Any]]:
        del self
        assert site_id == "site_alpha"
        assert post_ids == [11]
        return {
            11: {
                "excerpt": "A concise site excerpt with the established editorial rhythm.",
                "taxonomies": {
                    "category": ["WordPress AI"],
                    "post_tag": ["Site Knowledge", "Cloud Runtime"],
                },
            }
        }

    monkeypatch.setattr(SiteKnowledgeService, "execute", fake_site_knowledge_execute)
    monkeypatch.setattr(
        SiteKnowledgeRepository,
        "reference_metadata_for_post_ids",
        fake_reference_metadata,
    )
    scene_field = (
        "source_text"
        if task in {"title_generation", "content_summary", "content_rewrite"}
        else "prompt"
    )
    payload = _payload(
        {
            "task": task,
            "request": {
                scene_field: "Run the current WordPress editor task.",
                "site_knowledge_reference": {"enabled": True, "mode": mode},
            },
        }
    )

    response = _execute(client, payload, idempotency_key=f"wp-ai-{mode}")

    assert response.status_code == 200
    provider_input = provider.requests[0].input_payload
    assert expected_marker in provider_input["input"]
    assert "Historical facts must remain hidden." not in provider_input["input"]
    assert "0.91" not in provider_input["input"]
    assert provider_input["metadata"]["site_knowledge_reference"] == "applied"
    assert provider_input["metadata"]["site_knowledge_reference_mode"] == mode
    assert provider_input["metadata"]["generation_context_contract"] == "generation_context.v1"
    if task == "content_classification":
        assert "WordPress AI" in provider_input["input"]
        assert "Site Knowledge" in provider_input["input"]
        assert "term IDs" in provider_input["input"]


@pytest.mark.parametrize(
    ("task", "mode"),
    [
        ("meta_description", "site_meta_style"),
        ("content_summary", "site_summary_style"),
    ],
)
def test_wordpress_ai_connector_new_style_tasks_fall_back_when_retrieval_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    task: str,
    mode: str,
) -> None:
    _, client, provider = _build_client(tmp_path)

    def fail_site_knowledge_retrieval(
        self: SiteKnowledgeService,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del self, kwargs
        raise RuntimeError("Site Knowledge retrieval unavailable")

    monkeypatch.setattr(SiteKnowledgeService, "execute", fail_site_knowledge_retrieval)
    scene_field = (
        "source_text"
        if task in {"title_generation", "content_summary", "content_rewrite"}
        else "prompt"
    )
    response = _execute(
        client,
        _payload(
            {
                "task": task,
                "request": {
                    scene_field: "Run the current WordPress editor task.",
                    "site_knowledge_reference": {"enabled": True, "mode": mode},
                },
            }
        ),
        idempotency_key=f"wp-ai-{mode}-deferred",
    )

    assert response.status_code == 200
    provider_input = provider.requests[0].input_payload
    assert "Generation context" not in provider_input["input"]
    assert provider_input["metadata"]["generation_context_status"] == "unavailable"
    assert provider_input["metadata"]["generation_context_reason"] == "retrieval_failed"


def test_wordpress_ai_connector_title_generation_ignores_non_list_site_knowledge_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client, provider = _build_client(tmp_path)

    def return_invalid_results(
        self: SiteKnowledgeService,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del self, kwargs
        return {
            "status": "ready",
            "evidence_gate": {"status": "passed"},
            "results": {"title": "This object must not be treated as search results."},
        }

    monkeypatch.setattr(SiteKnowledgeService, "execute", return_invalid_results)
    payload = _payload(
        {
            "request": {
                "source_text": "<content>Current WordPress post content.</content>",
                "site_knowledge_reference": {
                    "enabled": True,
                    "mode": "site_title_style",
                },
            }
        }
    )

    response = _execute(
        client,
        payload,
        idempotency_key="wp-ai-title-site-style-non-list-results",
    )

    assert response.status_code == 200
    provider_input = provider.requests[0].input_payload
    assert "Generation context" not in provider_input["input"]
    assert "site_knowledge_reference" not in provider_input["metadata"]
    assert provider_input["metadata"]["generation_context_reason"] == "no_usable_references"


@pytest.mark.parametrize(
    ("task", "reference", "expected_error"),
    [
        (
            "title_generation",
            {"enabled": True, "mode": "site_title_style", "titles": ["Injected"]},
            "wordpress_operation.site_knowledge_reference_fields_forbidden",
        ),
        (
            "content_summary",
            {"enabled": True, "mode": "site_title_style"},
            "wordpress_operation.site_knowledge_reference_mode_invalid",
        ),
        (
            "content_rewrite",
            {"enabled": True, "mode": "site_title_style"},
            "wordpress_operation.site_knowledge_reference_task_not_allowed",
        ),
        (
            "title_generation",
            {"enabled": "yes", "mode": "site_title_style"},
            "wordpress_operation.site_knowledge_reference_enabled_invalid",
        ),
    ],
)
def test_wordpress_ai_connector_site_knowledge_reference_contract_fails_closed(
    tmp_path: Path,
    task: str,
    reference: dict[str, Any],
    expected_error: str,
) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "task": task,
            "request": {
                "source_text": "Run the WordPress AI scene.",
                "site_knowledge_reference": reference,
            },
        }
    )

    response = _execute(
        client,
        payload,
        idempotency_key=f"wp-ai-site-reference-invalid-{expected_error}",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == expected_error
    assert provider.requests == []


def test_wordpress_ai_connector_runtime_executes_alt_text_as_vision(
    tmp_path: Path,
) -> None:
    database_url, client, provider = _build_client(tmp_path)
    _seed_alt_text_artifact(tmp_path, database_url)

    response = _execute(client, _alt_text_payload(), idempotency_key="wp-ai-alt-text")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    assert data["result"]["output"]["output_text"] == "Blue ceramic mug on a white table"
    assert set(data["result"]["output"]) == {"output_text"}
    assert data["execution_context"]["ability_family"] == "vision"
    assert data["execution_context"]["data_classification"] == "internal"
    assert provider.requests[0].execution_kind == "vision"
    assert provider.requests[0].profile_id == WP_AI_CONNECTOR_ALT_TEXT_VISION_PROFILE_ID
    provider_input = provider.requests[0].input_payload
    assert provider_input["metadata"]["task"] == "alt_text_suggest"
    assert provider_input["max_tokens"] == 48
    assert provider_input["max_output_tokens"] == 48
    assert provider_input["temperature"] == 0.0
    responses_content = provider_input["input"][0]["content"]
    image_part = responses_content[-1]
    assert image_part["type"] == "input_image"
    assert image_part["image_url"].startswith("data:image/png;base64,")
    assert "messages" in provider_input
    public_json = json.dumps(data, ensure_ascii=False)
    assert "data:image/" not in public_json
    assert repr(provider.requests[0]).find("data:image/") == -1

    with get_session(database_url) as session:
        run = session.execute(select(RunRecord)).scalar_one()
        assert run.ability_name == "npcink-cloud/connector-runtime"
        assert run.channel == "editor"
        assert run.execution_kind == "vision"
        assert run.ability_family == "vision"
        assert run.profile_id == WP_AI_CONNECTOR_ALT_TEXT_VISION_PROFILE_ID
        assert run.policy_json["task_group"] == "alt_text_vision"
        assert run.policy_json["routing_intent"] == "media.alt_text_vision"
        assert run.policy_json["execution_contract"]["task_group"] == "alt_text_vision"
        assert run.policy_json["execution_contract"]["routing_intent"] == "media.alt_text_vision"
        durable_json = json.dumps(
            {
                "input": run.input_json,
                "result": run.result_json,
            },
            ensure_ascii=False,
        )
        assert "data:image/" not in durable_json
        assert run.execution_input_ciphertext is None


def test_alt_text_provider_success_inline_echo_is_never_persisted(
    tmp_path: Path,
) -> None:
    database_url, client, provider = _build_client(tmp_path)
    _seed_alt_text_artifact(tmp_path, database_url)
    payload = _alt_text_payload(
        {
            "request": {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": "provider inline echo",
                "filename": "blue-mug.png",
            }
        }
    )

    response = _execute(
        client,
        payload,
        idempotency_key="wp-ai-alt-text-provider-inline-echo",
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "failed"
    assert data["result"] == {}
    assert data["error_code"] == "provider.output_quality_rejected"
    assert ALT_TEXT_PROVIDER_ECHO_MARKER not in json.dumps(data, ensure_ascii=False)
    assert len(provider.requests) == 1
    with get_session(database_url) as session:
        run = session.execute(select(RunRecord)).scalar_one()
        assert run.status == "failed"
        assert not run.result_json
        assert ALT_TEXT_PROVIDER_ECHO_MARKER not in json.dumps(
            {
                "input": run.input_json,
                "result": run.result_json,
                "error": run.error_message,
            },
            ensure_ascii=False,
        )


def test_alt_text_provider_nested_success_echo_is_projected_to_text_only(
    tmp_path: Path,
) -> None:
    database_url, client, provider = _build_client(tmp_path)
    _seed_alt_text_artifact(tmp_path, database_url)
    payload = _alt_text_payload(
        {
            "request": {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": "provider nested echo",
                "filename": "blue-mug.png",
            }
        }
    )

    response = _execute(
        client,
        payload,
        idempotency_key="wp-ai-alt-text-provider-nested-echo",
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    assert data["result"]["output"] == {"output_text": "Blue ceramic mug on a white table"}
    assert ALT_TEXT_PROVIDER_ECHO_MARKER not in json.dumps(data, ensure_ascii=False)
    assert len(provider.requests) == 1
    with get_session(database_url) as session:
        run = session.execute(select(RunRecord)).scalar_one()
        assert run.status == "succeeded"
        assert run.result_json == data["result"]
        assert ALT_TEXT_PROVIDER_ECHO_MARKER not in json.dumps(
            run.result_json,
            ensure_ascii=False,
        )


def test_wordpress_ai_connector_runtime_replays_before_artifact_expiry_revalidation(
    tmp_path: Path,
) -> None:
    database_url, client, provider = _build_client(tmp_path)
    _seed_alt_text_artifact(tmp_path, database_url)
    payload = _alt_text_payload()

    first = _execute(
        client,
        payload,
        idempotency_key="wp-ai-alt-text-expiry-replay",
    )
    assert first.status_code == 200
    with get_session(database_url) as session:
        artifact = session.get(MediaArtifact, ALT_TEXT_SOURCE_ARTIFACT_ID)
        assert artifact is not None
        artifact.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    replay = _execute(
        client,
        payload,
        idempotency_key="wp-ai-alt-text-expiry-replay",
        trace_id="tracewpaialtreplay000000000000002",
    )

    assert replay.status_code == 200
    assert replay.json()["data"]["idempotent_replay"] is True
    assert len(provider.requests) == 1


@pytest.mark.parametrize(
    ("request_overrides", "expected_error"),
    [
        (
            {"request": {"prompt": "Generate alt text."}},
            "wordpress_operation.alt_text_source_artifact_required",
        ),
        (
            {
                "request": {
                    "prompt": "Generate alt text.",
                    "source_artifact_id": "art_" + ("a" * 192),
                }
            },
            "wordpress_operation.alt_text_source_artifact_required",
        ),
        (
            {
                "request": {
                    "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                    "prompt": "Generate alt text.",
                    "Image_URL": "https://example.test/file.jpg",
                }
            },
            "wordpress_operation.alt_text_request_fields_forbidden",
        ),
        (
            {
                "request": {
                    "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                    "prompt": "Generate alt text.",
                    "Mime-Type": "image/png",
                }
            },
            "wordpress_operation.alt_text_request_fields_forbidden",
        ),
        (
            {
                "request": {
                    "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                    "prompt": "Generate alt text.",
                    "Storage-Key": "obj_private",
                }
            },
            "wordpress_operation.alt_text_request_fields_forbidden",
        ),
        (
            {
                "request": {
                    "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                    "prompt": "Generate alt text.",
                    "Raw-Bytes": "private",
                }
            },
            "wordpress_operation.alt_text_request_fields_forbidden",
        ),
        (
            {
                "request": {
                    "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                    "prompt": {"nested": "DaTa : ImAgE / PnG ; BaSe64 , cHJpdmF0ZQ=="},
                }
            },
            "wordpress_operation.alt_text_inline_media_forbidden",
        ),
        (
            {
                "request": {
                    "prompt": "Generate alt text.",
                    "image_url": "https://example.test/file.jpg",
                }
            },
            "wordpress_operation.alt_text_request_fields_forbidden",
        ),
        (
            {
                "request": {
                    "prompt": "Generate alt text.",
                    "thumbnail_url": "https://example.test/file.jpg",
                }
            },
            "wordpress_operation.alt_text_request_fields_forbidden",
        ),
        (
            {
                "request": {
                    "prompt": "Generate alt text.",
                    "image_url": "data:image/png;base64,aW1hZ2U=",
                }
            },
            "wordpress_operation.alt_text_inline_media_forbidden",
        ),
        (
            {
                "request": {
                    "prompt": "Generate alt text.",
                    "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                    "mime_type": "image/png",
                }
            },
            "wordpress_operation.alt_text_request_fields_forbidden",
        ),
        (
            {
                "request": {
                    "prompt": "Generate alt text.",
                    "image_base64": "abc",
                }
            },
            "wordpress_operation.alt_text_request_fields_forbidden",
        ),
        (
            {
                "request": {
                    "prompt": "Generate alt text.",
                    "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                    "update_attachment_metadata": True,
                }
            },
            "wordpress_operation.alt_text_request_fields_forbidden",
        ),
        (
            {
                "request": {
                    "prompt": "Generate alt text.",
                    "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                    "messages": [{"role": "user", "content": "chat"}],
                }
            },
            "wordpress_operation.alt_text_request_fields_forbidden",
        ),
    ],
)
def test_wordpress_ai_connector_alt_text_contract_fails_closed(
    tmp_path: Path,
    request_overrides: dict[str, Any],
    expected_error: str,
) -> None:
    database_url, client, provider = _build_client(tmp_path)
    payload = _alt_text_payload(request_overrides)

    response = _execute(
        client,
        payload,
        idempotency_key=f"wp-ai-alt-text-invalid-{expected_error}",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == expected_error
    assert provider.requests == []
    with get_session(database_url) as session:
        assert session.scalars(select(RunRecord)).all() == []


@pytest.mark.parametrize(
    ("case", "scene_request", "expected_error"),
    [
        (
            "source-artifact-type",
            {
                "source_artifact_id": 123,
                "prompt": "Generate alt text.",
            },
            "wordpress_operation.alt_text_source_artifact_required",
        ),
        (
            "prompt-missing",
            {"source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID},
            "wordpress_operation.alt_text_prompt_invalid",
        ),
        (
            "prompt-empty",
            {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": "   ",
            },
            "wordpress_operation.alt_text_prompt_invalid",
        ),
        (
            "prompt-container",
            {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": [],
            },
            "wordpress_operation.alt_text_prompt_invalid",
        ),
        (
            "prompt-number",
            {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": 42,
            },
            "wordpress_operation.alt_text_prompt_invalid",
        ),
        (
            "prompt-bool",
            {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": True,
            },
            "wordpress_operation.alt_text_prompt_invalid",
        ),
        (
            "prompt-too-large",
            {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": ("word " * 101).strip(),
            },
            "wordpress_operation.alt_text_prompt_too_large",
        ),
        (
            "filename-type",
            {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": "Generate alt text.",
                "filename": [],
            },
            "wordpress_operation.alt_text_request_value_invalid",
        ),
        (
            "filename-too-large",
            {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": "Generate alt text.",
                "filename": ("x " * 81).strip(),
            },
            "wordpress_operation.alt_text_request_value_too_large",
        ),
        (
            "title-type",
            {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": "Generate alt text.",
                "title": 7,
            },
            "wordpress_operation.alt_text_request_value_invalid",
        ),
        (
            "title-too-large",
            {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": "Generate alt text.",
                "title": ("x " * 81).strip(),
            },
            "wordpress_operation.alt_text_request_value_too_large",
        ),
        (
            "existing-alt-type",
            {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": "Generate alt text.",
                "existing_alt": False,
            },
            "wordpress_operation.alt_text_request_value_invalid",
        ),
        (
            "existing-alt-too-large",
            {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": "Generate alt text.",
                "existing_alt": ("x " * 121).strip(),
            },
            "wordpress_operation.alt_text_request_value_too_large",
        ),
        (
            "existing-caption-type",
            {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": "Generate alt text.",
                "existing_caption": {},
            },
            "wordpress_operation.alt_text_request_value_invalid",
        ),
        (
            "existing-caption-too-large",
            {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": "Generate alt text.",
                "existing_caption": ("x " * 121).strip(),
            },
            "wordpress_operation.alt_text_request_value_too_large",
        ),
        (
            "locale-type",
            {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": "Generate alt text.",
                "locale": 123,
            },
            "wordpress_operation.alt_text_request_value_invalid",
        ),
        (
            "locale-too-large",
            {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": "Generate alt text.",
                "locale": ("x " * 17).strip(),
            },
            "wordpress_operation.alt_text_request_value_too_large",
        ),
        (
            "max-tokens-string",
            {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": "Generate alt text.",
                "max_tokens": "48",
            },
            "wordpress_operation.alt_text_max_tokens_invalid",
        ),
        (
            "max-tokens-float",
            {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": "Generate alt text.",
                "max_tokens": 48.0,
            },
            "wordpress_operation.alt_text_max_tokens_invalid",
        ),
        (
            "max-tokens-bool",
            {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": "Generate alt text.",
                "max_tokens": True,
            },
            "wordpress_operation.alt_text_max_tokens_invalid",
        ),
        (
            "max-tokens-zero",
            {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": "Generate alt text.",
                "max_tokens": 0,
            },
            "wordpress_operation.alt_text_max_tokens_invalid",
        ),
        (
            "max-tokens-too-large",
            {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": "Generate alt text.",
                "max_tokens": 97,
            },
            "wordpress_operation.alt_text_max_tokens_invalid",
        ),
    ],
)
def test_alt_text_request_value_contract_rejects_before_run_admission(
    tmp_path: Path,
    case: str,
    scene_request: dict[str, Any],
    expected_error: str,
) -> None:
    database_url, client, provider = _build_client(tmp_path)

    response = _execute(
        client,
        _alt_text_payload({"request": scene_request}),
        idempotency_key=f"wp-ai-alt-text-value-invalid-{case}",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == expected_error
    assert provider.requests == []
    with get_session(database_url) as session:
        assert session.scalars(select(RunRecord)).all() == []


def test_queued_alt_text_nested_alias_value_fails_before_encryption_or_provider(
    tmp_path: Path,
) -> None:
    database_url, client, provider = _build_client(tmp_path)
    payload = _alt_text_payload(
        {
            "request": {
                "source_artifact_id": ALT_TEXT_SOURCE_ARTIFACT_ID,
                "prompt": {"nested": {"Image_URL": "https://example.test/private-media.png"}},
            }
        }
    )
    payload["execution_pattern"] = "whole_run_offload"
    payload["task_backend"] = {
        "enabled": True,
        "mode": "queue",
        "callback_mode": "polling_preferred",
        "polling_interval_sec": 1,
    }

    response = _execute(
        client,
        payload,
        idempotency_key="wp-ai-alt-text-queued-nested-alias-invalid",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == ("wordpress_operation.alt_text_prompt_invalid")
    assert provider.requests == []
    with get_session(database_url) as session:
        assert session.scalars(select(RunRecord)).all() == []


def test_alt_text_resolve_admits_metadata_without_reading_storage(tmp_path: Path) -> None:
    database_url, client, provider = _build_client(tmp_path)
    _seed_alt_text_artifact(
        tmp_path,
        database_url,
        storage_key="obj_00000000000000000000000000000000",
    )

    response = _resolve(
        client,
        _alt_text_payload(),
        idempotency_key="wp-ai-alt-text-resolve-metadata-only",
    )

    assert response.status_code == 200
    assert response.json()["data"]["execution_kind"] == "vision"
    assert provider.requests == []


@pytest.mark.parametrize(
    ("case", "overrides", "expected_error"),
    [
        (
            "cross-site",
            {"site_id": "site_beta"},
            "wordpress_operation.alt_text_source_artifact_not_found",
        ),
        (
            "expired",
            {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
            "wordpress_operation.alt_text_source_artifact_expired",
        ),
        (
            "wrong-type",
            {"media_kind": "audio"},
            "wordpress_operation.alt_text_artifact_type_not_allowed",
        ),
        (
            "wrong-mime",
            {"content_type": "image/gif", "format": "gif"},
            "wordpress_operation.alt_text_artifact_type_not_allowed",
        ),
        (
            "oversize",
            {"byte_size": VISION_IMAGE_MAX_BYTES + 1},
            "wordpress_operation.alt_text_source_artifact_too_large",
        ),
        (
            "missing-storage",
            {"storage_key": "obj_00000000000000000000000000000000"},
            "wordpress_operation.alt_text_source_artifact_unavailable",
        ),
        (
            "corrupt-storage",
            {"checksum": "sha256:" + ("0" * 64)},
            "wordpress_operation.alt_text_source_artifact_unavailable",
        ),
    ],
)
def test_new_alt_text_execution_fails_closed_before_provider(
    tmp_path: Path,
    case: str,
    overrides: dict[str, Any],
    expected_error: str,
) -> None:
    database_url, client, provider = _build_client(tmp_path)
    _seed_alt_text_artifact(tmp_path, database_url, **overrides)

    response = _execute(
        client,
        _alt_text_payload(),
        idempotency_key=f"wp-ai-alt-text-artifact-{case}",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == expected_error
    assert provider.requests == []


@pytest.mark.parametrize(
    ("failure", "expected_error"),
    [
        (
            "expired",
            "wordpress_operation.alt_text_source_artifact_expired",
        ),
        (
            "corrupt",
            "wordpress_operation.alt_text_source_artifact_unavailable",
        ),
    ],
)
def test_queued_alt_text_worker_revalidates_artifact_before_provider(
    tmp_path: Path,
    failure: str,
    expected_error: str,
) -> None:
    database_url, client, provider = _build_client(tmp_path)
    _seed_alt_text_artifact(tmp_path, database_url)
    payload = _alt_text_payload()
    payload["execution_pattern"] = "whole_run_offload"
    payload["task_backend"] = {
        "enabled": True,
        "mode": "queue",
        "callback_mode": "polling_preferred",
        "polling_interval_sec": 1,
    }

    queued = _execute(
        client,
        payload,
        idempotency_key=f"wp-ai-alt-text-queued-revalidation-{failure}",
    )
    assert queued.status_code == 200
    run_id = queued.json()["data"]["run_id"]
    assert queued.json()["data"]["status"] == "queued"
    with get_session(database_url) as session:
        artifact = session.get(MediaArtifact, ALT_TEXT_SOURCE_ARTIFACT_ID)
        assert artifact is not None
        if failure == "expired":
            artifact.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        else:
            artifact.checksum = "sha256:" + ("0" * 64)
        session.commit()

    worker = RuntimeService(
        database_url,
        settings=Settings(
            _env_file=None,
            environment="test",
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
            artifact_store_root=str(tmp_path / "artifacts"),
            admin_session_secret=TEST_ADMIN_SESSION_SECRET,
            portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        ),
        providers={"openai": provider},
    )
    processed = worker.process_queued_runs(max_runs=1, timeout_seconds=0)

    assert processed == [
        {
            "run_id": run_id,
            "status": "failed",
            "trace_id": queued.json()["data"]["trace_id"],
        }
    ]
    assert provider.requests == []
    with get_session(database_url) as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        assert run.status == "failed"
        assert run.error_code == expected_error


def test_wordpress_ai_connector_runtime_strips_reasoning_noise_from_title(
    tmp_path: Path,
) -> None:
    _, client, _ = _build_client(tmp_path)
    payload = _payload(
        {
            "request": {
                "source_text": ("<content>reasoning leakage verification content.</content>"),
            },
        }
    )

    response = _execute(client, payload, idempotency_key="wp-ai-connector-think-strip")

    assert response.status_code == 200
    result_text = response.json()["data"]["result"]["output"]["output_text"]
    assert result_text == "Cloud Runtime Connector Verified"
    assert "<think>" not in result_text
    assert "reasoning" not in result_text.lower()


def test_wordpress_ai_connector_runtime_falls_back_on_reasoning_only_title(
    tmp_path: Path,
) -> None:
    database_url, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "request": {
                "source_text": "<content>reasoning only response content.</content>",
            },
        }
    )

    response = _execute(
        client,
        payload,
        idempotency_key="wp-ai-connector-think-only",
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    assert data["fallback_used"] is True
    assert data["result"]["output"]["output_text"] == "Hosted Runtime Connector Verified"
    assert len(provider.requests) == 2
    assert provider.requests[0].model_id == "gpt-wp-ai-connector-test"
    assert provider.requests[1].model_id == "gpt-wp-ai-connector-fallback-test"

    with get_session(database_url) as session:
        run = session.execute(select(RunRecord)).scalar_one()
        assert run.fallback_used is True
        assert run.selected_model_id == "gpt-wp-ai-connector-fallback-test"


def test_wordpress_ai_connector_runtime_falls_back_on_incomplete_title_fragment(
    tmp_path: Path,
) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "request": {
                "source_text": "<content>title fragment response content.</content>",
            },
        }
    )

    response = _execute(
        client,
        payload,
        idempotency_key="wp-ai-connector-title-fragment",
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    assert data["fallback_used"] is True
    assert data["result"]["output"]["output_text"] == "Hosted Runtime Connector Verified"
    assert len(provider.requests) == 2
    assert provider.requests[0].model_id == "gpt-wp-ai-connector-test"
    assert provider.requests[1].model_id == "gpt-wp-ai-connector-fallback-test"


def test_wordpress_ai_connector_runtime_strips_title_explanation_tail(
    tmp_path: Path,
) -> None:
    _, client, _ = _build_client(tmp_path)
    payload = _payload(
        {
            "request": {
                "source_text": "<content>title explanation response content.</content>",
            },
        }
    )

    response = _execute(
        client,
        payload,
        idempotency_key="wp-ai-connector-title-explanation",
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    assert (
        data["result"]["output"]["output_text"]
        == "How to Verify a Hosted AI Runtime Connector: Essential Steps"
    )


def test_wordpress_ai_connector_runtime_extracts_single_title_from_title_bundle(
    tmp_path: Path,
) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "request": {
                "source_text": "<content>title bundle response content.</content>",
            },
        }
    )

    response = _execute(client, payload, idempotency_key="wp-ai-connector-title-bundle")

    assert response.status_code == 200
    provider_input = provider.requests[0].input_payload
    assert "multiple options" in provider_input["input"]
    assert "numbered lists" in provider_input["input"]
    assert (
        response.json()["data"]["result"]["output"]["output_text"]
        == "WordPress AI 连接器测试：云端生成，本地审核"
    )


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        ("title article boilerplate", "WordPress - 流行的建站程序介绍与下载"),
        ("title summary tail", "WordPress - 流行的建站程序介绍与下载"),
    ],
)
def test_wordpress_ai_connector_runtime_extracts_title_from_article_shaped_output(
    tmp_path: Path,
    marker: str,
    expected: str,
) -> None:
    _, client, _ = _build_client(tmp_path)
    payload = _payload(
        {
            "request": {
                "source_text": f"<content>{marker}</content>",
            }
        }
    )

    response = _execute(
        client,
        payload,
        idempotency_key=f"wp-ai-{marker.replace(' ', '-')}",
    )

    assert response.status_code == 200
    assert response.json()["data"]["result"]["output"]["output_text"] == expected


def test_wordpress_ai_connector_runtime_normalizes_rewrite_variant_bundle(
    tmp_path: Path,
) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "task": "content_rewrite",
            "request": {
                "source_text": (
                    "<block-content>rewrite variants response paragraph.</block-content>"
                ),
            },
        }
    )

    response = _execute(client, payload, idempotency_key="wp-ai-connector-rewrite-bundle")

    assert response.status_code == 200
    provider_input = provider.requests[0].input_payload
    assert "Return exactly one rewritten version" in provider_input["input"]
    result_text = response.json()["data"]["result"]["output"]["output_text"]
    assert result_text == "这个插件非常实用，能够帮助站长高效完成大量内容相关工作。"
    assert "如果你愿意" not in result_text


def test_wordpress_ai_connector_runtime_extracts_one_rewrite_from_alternative_explanation(
    tmp_path: Path,
) -> None:
    _, client, _ = _build_client(tmp_path)
    payload = _payload(
        {
            "task": "content_rewrite",
            "request": {
                "source_text": (
                    "<block-content>rewrite alternatives response paragraph.</block-content>"
                ),
            },
        }
    )

    response = _execute(
        client,
        payload,
        idempotency_key="wp-ai-connector-rewrite-alternative-explanation",
    )

    assert response.status_code == 200
    result_text = response.json()["data"]["result"]["output"]["output_text"]
    assert result_text == "The selected whole paragraph block is identified clearly."
    assert " OR " not in result_text
    assert "Both rephrasings" not in result_text


def test_wordpress_ai_connector_runtime_extracts_one_rewrite_from_concise_alternative_explanation(
    tmp_path: Path,
) -> None:
    _, client, _ = _build_client(tmp_path)
    payload = _payload(
        {
            "task": "content_rewrite",
            "request": {
                "source_text": (
                    "<block-content>rewrite alternatives concise response paragraph."
                    "</block-content>"
                ),
            },
        }
    )

    response = _execute(
        client,
        payload,
        idempotency_key="wp-ai-connector-rewrite-alternative-concise-explanation",
    )

    assert response.status_code == 200
    result_text = response.json()["data"]["result"]["output"]["output_text"]
    assert result_text == "The selected whole paragraph block is identified clearly."
    assert " OR " not in result_text
    assert "Both preserve" not in result_text


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        (
            "rewrite legitimate multi sentence",
            "The API supports v1 and v2. Both versions remain available during the "
            "documented migration window.",
        ),
        (
            "rewrite legitimate this rewrite",
            "The editor keeps the reviewed paragraph intact. This rewrite also "
            "preserves the second operational requirement.",
        ),
        (
            "rewrite legitimate both preserve review",
            "Use the local execution path. OR use the hosted runtime path. "
            "Both preserve review before applying changes.",
        ),
        (
            "rewrite legitimate bullet list",
            "- Keep the first editorial requirement intact. "
            "- Keep the second editorial requirement intact.",
        ),
        (
            "rewrite legitimate numbered list",
            "1. Keep the first migration step intact. "
            "2. Keep the second migration step intact.",
        ),
        (
            "rewrite legitimate inline bold",
            "Keep the local review step and preserve the canonical audit trail. "
            "Apply only after explicit approval.",
        ),
    ],
)
def test_wordpress_ai_connector_runtime_preserves_legitimate_rewrite_structure(
    tmp_path: Path,
    marker: str,
    expected: str,
) -> None:
    _, client, _ = _build_client(tmp_path)
    payload = _payload(
        {
            "task": "content_rewrite",
            "request": {
                "source_text": f"<block-content>{marker}.</block-content>",
            },
        }
    )

    response = _execute(
        client,
        payload,
        idempotency_key=f"wp-ai-connector-{marker.replace(' ', '-')}",
    )

    assert response.status_code == 200
    assert response.json()["data"]["result"]["output"]["output_text"] == expected


def test_wordpress_ai_connector_runtime_preserves_long_rewrite_result_contract(
    tmp_path: Path,
) -> None:
    _, client, provider = _build_client(tmp_path)
    assert 320 < len(LONG_REWRITE_SOURCE_TEXT) < WP_AI_CONNECTOR_MAX_SOURCE_TEXT_CHARS
    assert 320 < len(LONG_REWRITE_OUTPUT_TEXT) < WP_AI_CONNECTOR_MAX_SOURCE_TEXT_CHARS
    payload = _payload(
        {
            "task": "content_rewrite",
            "request": {"source_text": LONG_REWRITE_SOURCE_TEXT},
        }
    )

    response = _execute(client, payload, idempotency_key="wp-ai-connector-long-rewrite")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    assert data["profile_id"] == WP_AI_CONNECTOR_EDITORIAL_PROFILE_ID
    result = data["result"]
    assert result["contract_version"] == "cloud_connector_result.v1"
    assert result["suggestion_only"] is True
    assert result["operation_contract"] == {
        "contract_version": "wordpress_operation.v1",
        "task": "content_rewrite",
    }
    assert result["output"]["output_text"] == LONG_REWRITE_OUTPUT_TEXT
    provider_input = provider.requests[0].input_payload
    assert provider_input["text"] == LONG_REWRITE_SOURCE_TEXT
    assert provider_input["input"].count(LONG_REWRITE_SOURCE_TEXT) == 1


def test_wordpress_ai_connector_runtime_projects_classification_json_scene(
    tmp_path: Path,
) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "task": "content_classification",
            "request": {
                "prompt": "Classify this post into WordPress taxonomy suggestions.",
                "response_format": "json",
            },
        }
    )

    response = _execute(
        client,
        payload,
        idempotency_key="wp-ai-connector-classification",
    )

    assert response.status_code == 200
    provider_input = provider.requests[0].input_payload
    assert "Return strict JSON only" in provider_input["input"]
    assert '"suggestions"' in provider_input["input"]
    assert provider_input["max_tokens"] == 220
    assert provider_input["max_output_tokens"] == 220
    assert provider.requests[0].profile_id == WP_AI_CONNECTOR_CLASSIFICATION_PROFILE_ID
    result = json.loads(response.json()["data"]["result"]["output"]["output_text"])
    assert result["suggestions"]
    assert all("term" in suggestion for suggestion in result["suggestions"])
    assert any(
        suggestion["term"] in {"WordPress", "WordPress AI"} for suggestion in result["suggestions"]
    )


def test_wordpress_ai_connector_runtime_preserves_existing_only_taxonomy_terms(
    tmp_path: Path,
) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "task": "content_classification",
            "request": {
                "prompt": (
                    "<taxonomy>category</taxonomy>\n"
                    "<content>介绍 WordPress AI 写作辅助。</content>\n"
                    "<available-terms>经验教程, 资源</available-terms>"
                ),
                "response_format": "json",
            },
        }
    )

    response = _execute(
        client,
        payload,
        idempotency_key="wp-ai-connector-classification-existing-only",
    )

    assert response.status_code == 200
    provider_input = provider.requests[0].input_payload
    assert "Choose only exact term names" in provider_input["input"]
    result = json.loads(response.json()["data"]["result"]["output"]["output_text"])
    assert result == {
        "suggestions": [
            {"term": "经验教程", "confidence": 0.8, "is_new": False},
        ]
    }


def test_wordpress_ai_connector_runtime_normalizes_meta_description_scene(
    tmp_path: Path,
) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "task": "meta_description",
            "request": {
                "prompt": (
                    "为这篇文章生成 SEO 描述：Npcink Cloud Addon 让 WordPress AI 插件"
                    "在固定能力场景中调用云端运行时，只提供建议式输出，不提供通用聊天入口。"
                ),
            },
        }
    )

    response = _execute(client, payload, idempotency_key="wp-ai-connector-meta")

    assert response.status_code == 200
    provider_input = provider.requests[0].input_payload
    assert "120 to 155 characters" in provider_input["input"]
    assert provider_input["max_tokens"] == 80
    result_text = response.json()["data"]["result"]["output"]["output_text"]
    assert "**" not in result_text
    assert "###" not in result_text
    assert len(result_text) <= 155
    assert "云端运行时" in result_text


def test_wordpress_ai_connector_runtime_falls_back_on_meta_boilerplate(
    tmp_path: Path,
) -> None:
    _, client, _ = _build_client(tmp_path)
    payload = _payload(
        {
            "task": "meta_description",
            "request": {
                "prompt": (
                    "为这篇文章生成 SEO 描述：meta boilerplate。Npcink Cloud Addon "
                    "让 WordPress AI 插件在固定能力场景中调用云端运行时，只提供"
                    "建议式输出，不提供通用聊天入口。"
                ),
            },
        }
    )

    response = _execute(client, payload, idempotency_key="wp-ai-connector-meta-boilerplate")

    assert response.status_code == 200
    result_text = response.json()["data"]["result"]["output"]["output_text"]
    assert "以下是基于" not in result_text
    assert "建议式输出" in result_text


def test_wordpress_ai_connector_runtime_normalizes_summary_text_scene(
    tmp_path: Path,
) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "task": "content_summary",
            "request": {
                "source_text": (
                    "<content>Npcink Cloud Addon connects WordPress to a hosted runtime "
                    "while local review retains final write authority.</content>"
                ),
            },
        }
    )

    response = _execute(client, payload, idempotency_key="wp-ai-connector-summary")

    assert response.status_code == 200
    provider_input = provider.requests[0].input_payload
    assert "Return only the summary" in provider_input["input"]
    assert provider_input["max_tokens"] == 160
    assert provider.requests[0].profile_id == WP_AI_CONNECTOR_EDITORIAL_PROFILE_ID
    result_text = response.json()["data"]["result"]["output"]["output_text"]
    assert "**" not in result_text
    assert "###" not in result_text
    assert not result_text.endswith("2.")
    assert len(result_text) <= 220


def test_wordpress_ai_connector_image_generation_uses_managed_image_profile(
    tmp_path: Path,
) -> None:
    database_url, client, provider = _build_client(tmp_path)

    response = _execute(
        client,
        _image_payload(),
        idempotency_key="wp-ai-image-generation",
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    assert data["profile_id"] == WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID
    result = data["result"]
    assert result["artifact_type"] == "image_generation_artifacts"
    assert result["contract_version"] == "image_generation_result.v1"
    assert result["operation"] == "image.generate.v1"
    assert result["suggestion_only"] is True
    assert result["requires_local_review"] is True
    assert len(result["artifacts"]) == 1
    artifact_result = result["artifacts"][0]
    assert artifact_result["artifact_reference"] == {"artifact_id": artifact_result["artifact_id"]}
    assert "download_url" not in artifact_result
    assert artifact_result["status"] == "available"
    assert artifact_result["media_kind"] == "image"
    assert artifact_result["operation"] == "image.generate.v1"
    assert artifact_result["content_type"] == "image/png"
    assert artifact_result["format"] == "png"
    assert artifact_result["width"] == 64
    assert artifact_result["height"] == 48
    assert artifact_result["filesize_bytes"] > 0
    assert artifact_result["checksum"].startswith("sha256:")
    serialized_result = json.dumps(result, sort_keys=True)
    assert "https://" not in serialized_result
    assert "b64_json" not in serialized_result
    assert "provider_response_format" not in serialized_result
    assert "storage_key" not in serialized_result
    assert provider.requests[0].execution_kind == "image_generation"
    assert provider.requests[0].profile_id == WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID
    assert provider.requests[0].timeout_ms == 90000
    assert "response_format" not in provider.requests[0].input_payload

    replay = _execute(
        client,
        _image_payload(),
        idempotency_key="wp-ai-image-generation",
        trace_id="tracewpaiimagegenerationreplay001",
    )
    assert replay.status_code == 200, replay.text
    replay_data = replay.json()["data"]
    assert replay_data["idempotent_replay"] is True
    assert replay_data["run_id"] == data["run_id"]
    assert replay_data["result"] == result
    assert len(provider.requests) == 1

    with get_session(database_url) as session:
        run = session.execute(select(RunRecord)).scalar_one()
        artifact = session.execute(select(MediaArtifact)).scalar_one()
        assert run.ability_name == "npcink-cloud/generate-image"
        assert run.channel == "wordpress_ai_connector"
        assert run.execution_kind == "image_generation"
        assert run.profile_id == WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID
        assert run.policy_json["managed_surface"] == "hosted_runtime_profiles"
        assert run.policy_json["task_group"] == "image_generation"
        assert run.policy_json["routing_intent"] == "media.image_generation"
        assert run.policy_json["timeout_ms"] == 90000
        assert run.policy_json["execution_contract"]["routing_intent"] == "media.image_generation"
        persisted_result = json.dumps(run.result_json, sort_keys=True)
        assert "https://" not in persisted_result
        assert "b64_json" not in persisted_result
        assert "provider_response_format" not in persisted_result
        assert "storage_key" not in persisted_result
        assert artifact.artifact_id == artifact_result["artifact_id"]
        assert artifact.run_id == run.run_id == data["run_id"]
        assert artifact.site_id == "site_alpha"
        assert artifact.media_kind == "image"
        assert artifact.operation == "image.generate.v1"
        assert artifact.status == "available"
        assert artifact.content_type == "image/png"
        assert artifact.format == "png"
        assert artifact.width == 64
        assert artifact.height == 48
        assert artifact.byte_size == artifact_result["filesize_bytes"]
        assert artifact.checksum == artifact_result["checksum"]


def test_wordpress_ai_connector_runtime_rejects_timeout_above_scene_limit(
    tmp_path: Path,
) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload()
    payload["timeout_seconds"] = 61

    response = _execute(client, payload, idempotency_key="wp-ai-connector-timeout")

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "connector_runtime.timeout_exceeded"
    assert provider.requests == []


def test_wordpress_ai_connector_runtime_rejects_generic_chat_shape(tmp_path: Path) -> None:
    _, client, provider = _build_client(tmp_path)
    payload = _payload(
        {
            "request": {
                "messages": [
                    {
                        "role": "user",
                        "content": "Chat about anything.",
                    }
                ]
            }
        }
    )

    response = _execute(client, payload, idempotency_key="wp-ai-connector-chat-shape")

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "wordpress_operation.chat_or_secret_field_forbidden"
    assert provider.requests == []


def test_wordpress_ai_connector_runtime_fails_closed_on_managed_profile_contract_drift(
    tmp_path: Path,
) -> None:
    database_url, client, provider = _build_client(tmp_path)
    with get_session(database_url) as session:
        profile = session.get(
            RoutingProfile,
            WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
        )
        assert profile is not None
        policy = dict(profile.default_policy_json or {})
        policy["operation_contract_version"] = "wordpress_operation.v2"
        profile.default_policy_json = policy
        session.commit()

    response = _execute(
        client,
        _payload(),
        idempotency_key="runtime-profile-contract-drift",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "runtime_profiles.managed_contract_invalid"
    assert "operation_contract_version=wordpress_operation.v1" in payload["message"]
    assert provider.requests == []
    with get_session(database_url) as session:
        assert session.scalars(select(RunRecord)).all() == []


def _runtime_profile_replacement_from_projection(
    profiles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "profile_id": profile["profile_id"],
            "candidate_instance_ids": profile["candidate_instance_ids"],
            "timeout_ms": profile["timeout_ms"],
            "allow_fallback": profile["allow_fallback"],
            "max_retries": profile["max_retries"],
            "note": profile["note"],
        }
        for profile in profiles
    ]


def test_admin_runtime_profiles_updates_hosted_candidates(
    tmp_path: Path,
) -> None:
    database_url, client, provider = _build_client(tmp_path)

    get_response = client.get(
        "/internal/service/admin/runtime-profiles",
        headers=build_internal_headers(),
    )

    assert get_response.status_code == 200
    assert get_response.json()["message"] == "Hosted runtime profiles loaded"
    data = get_response.json()["data"]
    assert data["contract_version"] == "cloud-hosted-runtime-profiles.v1"
    assert data["surface"] == "admin_hosted_runtime_profiles"
    assert data["projection_kind"] == "hosted_runtime_profile_configuration"
    assert data["owner"] == "cloud_runtime"
    assert data["platform_kind"] == "wordpress"
    assert data["connector_id"] == "wordpress_ai_connector"
    assert data["operation_contract_version"] == "wordpress_operation.v1"
    assert data["boundary"]["admin_surface"] == "platform_admin_only"
    assert data["boundary"]["results_write_posture"] == "suggestion_only"
    assert data["boundary"]["public_runtime_accepts_raw_model_instance"] is False
    assert data["boundary"]["cloud_owns"] == ["hosted_candidate_chain"]
    assert data["boundary"]["local_plugin_owns"] == [
        "ability_truth",
        "workflow_truth",
        "prompt_truth",
        "router_truth",
        "adoption_truth",
        "final_write_truth",
    ]
    assert data["boundary"]["direct_wordpress_write"] is False
    assert len(data["profiles"]) == 6
    assert all(len(profile["candidate_instance_ids"]) <= 2 for profile in data["profiles"])
    assert set(data["available_instances"]) == {
        "text",
        "vision",
        "image_generation",
        "audio_generation",
    }
    assert data["available_instances"]["text"][0]["instance_id"] == ("openai-wp-ai-connector-test")
    assert data["available_instances"]["vision"][0]["instance_id"] == ("openai-wp-ai-vision-test")
    assert data["available_instances"]["image_generation"][0]["instance_id"] == (
        "openai-wp-ai-image-test"
    )
    assert data["available_instances"]["audio_generation"][0]["instance_id"] == (
        "openai-wp-ai-audio-test"
    )
    assert "embedding" not in data["available_instances"]
    short_text = next(
        profile
        for profile in data["profiles"]
        if profile["profile_id"] == WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID
    )
    assert short_text["platform_kind"] == "wordpress"
    assert short_text["connector_id"] == "wordpress_ai_connector"
    assert "candidates" not in short_text
    assert "selection_policy" not in short_text
    assert short_text["note"] == ""
    assert short_text["tasks"] == [
        "excerpt_generation",
        "meta_description",
        "title_generation",
        "audio_summary_script",
    ]
    assert short_text["routing_intent"] == "content.short_text"
    alt_text_vision = next(
        profile
        for profile in data["profiles"]
        if profile["profile_id"] == WP_AI_CONNECTOR_ALT_TEXT_VISION_PROFILE_ID
    )
    assert alt_text_vision["execution_kind"] == "vision"
    assert alt_text_vision["routing_intent"] == "media.alt_text_vision"
    assert alt_text_vision["tasks"] == ["alt_text_suggest"]
    assert alt_text_vision["candidate_instance_ids"] == ["openai-wp-ai-vision-test"]
    image_generation = next(
        profile
        for profile in data["profiles"]
        if profile["profile_id"] == WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID
    )
    assert image_generation["execution_kind"] == "image_generation"
    assert image_generation["routing_intent"] == "media.image_generation"
    assert image_generation["tasks"] == ["image_generation"]
    assert image_generation["candidate_instance_ids"] == ["openai-wp-ai-image-test"]
    assert image_generation["timeout_ms"] == 90000
    audio_generation = next(
        profile
        for profile in data["profiles"]
        if profile["profile_id"] == WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID
    )
    assert audio_generation["execution_kind"] == "audio_generation"
    assert audio_generation["routing_intent"] == "audio.generation"
    assert audio_generation["tasks"] == [
        "article_narration",
        "article_audio_summary",
    ]
    assert audio_generation["candidate_instance_ids"] == ["openai-wp-ai-audio-test"]

    replacement_profiles = _runtime_profile_replacement_from_projection(data["profiles"])
    assert len(replacement_profiles) == len(WP_AI_CONNECTOR_PROFILE_SPECS_BY_ID)
    assert {profile["profile_id"] for profile in replacement_profiles} == set(
        WP_AI_CONNECTOR_PROFILE_SPECS_BY_ID
    )
    for profile in replacement_profiles:
        if profile["profile_id"] == WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID:
            profile.update(
                {
                    "candidate_instance_ids": ["openai-wp-ai-connector-test"],
                    "timeout_ms": 12000,
                    "allow_fallback": True,
                    "max_retries": 1,
                    "note": "short-text canary",
                }
            )
        if profile["profile_id"] == WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID:
            profile.update(
                {
                    "timeout_ms": 90000,
                    "allow_fallback": False,
                    "max_retries": 0,
                    "note": "image-generation canary",
                }
            )

    response = client.put(
        "/internal/service/admin/runtime-profiles",
        headers=merge_json_headers(
            build_internal_headers(idempotency_key="wp-ai-routing-admin-save-001")
        ),
        json={
            "contract_version": "cloud-hosted-runtime-profiles.v1",
            "platform_kind": "wordpress",
            "connector_id": "wordpress_ai_connector",
            "operation_contract_version": "wordpress_operation.v1",
            "profiles": replacement_profiles,
        },
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Hosted runtime profiles saved"
    payload = response.json()["data"]
    assert payload["receipt"]["event_kind"] == "runtime_profiles.update"
    assert payload["receipt"]["scope_kind"] == "runtime_profile_catalog"
    assert payload["receipt"]["scope_id"] == "wordpress_ai_connector"
    assert payload["receipt"]["effective_summary"] == ("Hosted runtime profiles were updated.")
    updated = next(
        profile
        for profile in payload["profiles"]
        if profile["profile_id"] == WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID
    )
    assert updated["candidate_instance_ids"] == ["openai-wp-ai-connector-test"]
    assert updated["timeout_ms"] == 12000
    assert updated["max_retries"] == 1
    assert updated["note"] == "short-text canary"
    assert "selection_policy" not in updated
    assert "candidates" not in updated
    updated_image = next(
        profile
        for profile in payload["profiles"]
        if profile["profile_id"] == WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID
    )
    assert updated_image["candidate_instance_ids"] == ["openai-wp-ai-image-test"]
    assert updated_image["timeout_ms"] == 90000
    assert updated_image["allow_fallback"] is False
    assert updated_image["note"] == "image-generation canary"
    assert updated["revision"].startswith("runtime-profiles-admin-")

    round_trip_response = client.get(
        "/internal/service/admin/runtime-profiles",
        headers=build_internal_headers(),
    )
    assert round_trip_response.status_code == 200
    round_trip_profiles = round_trip_response.json()["data"]["profiles"]
    round_trip_short_text = next(
        profile
        for profile in round_trip_profiles
        if profile["profile_id"] == WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID
    )
    assert round_trip_short_text["note"] == "short-text canary"
    assert "selection_policy" not in round_trip_short_text
    assert "candidates" not in round_trip_short_text

    CatalogService(database_url, providers={"openai": provider}).refresh_catalog()
    refreshed_response = client.get(
        "/internal/service/admin/runtime-profiles",
        headers=build_internal_headers(),
    )
    assert refreshed_response.status_code == 200
    refreshed_short_text = next(
        profile
        for profile in refreshed_response.json()["data"]["profiles"]
        if profile["profile_id"] == WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID
    )
    assert refreshed_short_text["candidate_instance_ids"] == ["openai-wp-ai-connector-test"]
    assert refreshed_short_text["timeout_ms"] == 12000
    assert refreshed_short_text["max_retries"] == 1
    assert refreshed_short_text["note"] == "short-text canary"
    assert refreshed_short_text["revision"] == updated["revision"]

    run_response = _execute(
        client,
        _payload(),
        idempotency_key="wp-ai-routing-admin-run-after-save",
    )

    assert run_response.status_code == 200
    with get_session(database_url) as session:
        run = session.execute(
            select(RunRecord).where(RunRecord.run_id == run_response.json()["data"]["run_id"])
        ).scalar_one()
        assert run.profile_id == WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID
        assert run.policy_json["timeout_ms"] == 12000
        assert run.policy_json["max_retries"] == 1
        assert run.policy_json["routing_intent"] == "content.short_text"
        assert run.policy_json["managed_surface"] == "hosted_runtime_profiles"
        assert run.policy_json["platform_kind"] == "wordpress"
        assert run.policy_json["connector_id"] == "wordpress_ai_connector"
        assert run.policy_json["operation_contract_version"] == ("wordpress_operation.v1")
        routing_profile = session.get(
            RoutingProfile,
            WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
        )
        assert routing_profile is not None
        default_policy = routing_profile.default_policy_json
        assert isinstance(default_policy, dict)
        assert default_policy["operator_note"] == "short-text canary"
        assert default_policy["operation_contract_version"] == ("wordpress_operation.v1")
        routing_binding = session.get(
            RoutingBinding,
            WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
        )
        assert routing_binding is not None
        selection_policy = routing_binding.selection_policy_json
        assert isinstance(selection_policy, dict)
        assert selection_policy["strategy"] == "ordered"
        assert selection_policy["managed_surface"] == "hosted_runtime_profiles"
        assert selection_policy["platform_kind"] == "wordpress"
        assert selection_policy["connector_id"] == "wordpress_ai_connector"
        assert selection_policy["operation_contract_version"] == ("wordpress_operation.v1")
        assert selection_policy["operator_note"] == "short-text canary"
        audit_event = session.execute(
            select(ServiceAuditEvent).where(
                ServiceAuditEvent.event_kind == "runtime_profiles.update"
            )
        ).scalar_one()
        assert audit_event.scope_kind == "runtime_profile_catalog"
        assert audit_event.scope_id == "wordpress_ai_connector"
        audit_payload = audit_event.payload_json
        assert isinstance(audit_payload, dict)
        assert audit_payload["contract_version"] == "cloud-hosted-runtime-profiles.v1"
        assert audit_payload["platform_kind"] == "wordpress"
        assert audit_payload["connector_id"] == "wordpress_ai_connector"
        assert audit_payload["operation_contract_version"] == ("wordpress_operation.v1")


def test_admin_runtime_profiles_rejects_unknown_profile(tmp_path: Path) -> None:
    _, client, _ = _build_client(tmp_path)

    response = client.put(
        "/internal/service/admin/runtime-profiles",
        headers=merge_json_headers(
            build_internal_headers(idempotency_key="wp-ai-routing-admin-save-unknown")
        ),
        json={
            "contract_version": "cloud-hosted-runtime-profiles.v1",
            "platform_kind": "wordpress",
            "connector_id": "wordpress_ai_connector",
            "operation_contract_version": "wordpress_operation.v1",
            "profiles": [
                {
                    "profile_id": "text.balanced",
                    "candidate_instance_ids": ["openai-wp-ai-connector-test"],
                    "timeout_ms": 12000,
                    "allow_fallback": True,
                    "max_retries": 0,
                }
            ],
        },
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "runtime_profiles.invalid_profile"


def test_admin_runtime_profiles_rejects_incomplete_replacement(tmp_path: Path) -> None:
    _, client, _ = _build_client(tmp_path)
    get_response = client.get(
        "/internal/service/admin/runtime-profiles",
        headers=build_internal_headers(),
    )
    assert get_response.status_code == 200
    replacement_profiles = _runtime_profile_replacement_from_projection(
        get_response.json()["data"]["profiles"]
    )
    omitted = replacement_profiles.pop()

    response = client.put(
        "/internal/service/admin/runtime-profiles",
        headers=merge_json_headers(
            build_internal_headers(idempotency_key="runtime-profiles-incomplete-replacement")
        ),
        json={
            "contract_version": "cloud-hosted-runtime-profiles.v1",
            "platform_kind": "wordpress",
            "connector_id": "wordpress_ai_connector",
            "operation_contract_version": "wordpress_operation.v1",
            "profiles": replacement_profiles,
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "runtime_profiles.invalid_profile"
    assert "must replace the complete catalog" in payload["message"]
    assert omitted["profile_id"] in payload["message"]


def test_admin_runtime_profiles_rejects_more_than_primary_and_fallback(
    tmp_path: Path,
) -> None:
    _, client, _ = _build_client(tmp_path)
    get_response = client.get(
        "/internal/service/admin/runtime-profiles",
        headers=build_internal_headers(),
    )
    assert get_response.status_code == 200
    replacement_profiles = _runtime_profile_replacement_from_projection(
        get_response.json()["data"]["profiles"]
    )
    short_text_profile = next(
        profile
        for profile in replacement_profiles
        if profile["profile_id"] == WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID
    )
    short_text_profile["candidate_instance_ids"] = [
        "openai-wp-ai-connector-test",
        "zz-openai-wp-ai-connector-fallback-test",
        "third-candidate-must-be-rejected",
    ]

    response = client.put(
        "/internal/service/admin/runtime-profiles",
        headers=merge_json_headers(
            build_internal_headers(idempotency_key="runtime-profiles-three-candidates")
        ),
        json={
            "contract_version": "cloud-hosted-runtime-profiles.v1",
            "platform_kind": "wordpress",
            "connector_id": "wordpress_ai_connector",
            "operation_contract_version": "wordpress_operation.v1",
            "profiles": replacement_profiles,
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "runtime_profiles.invalid_profile"
    assert "supports at most two candidate instances" in payload["message"]


@pytest.mark.parametrize(
    "payload_overrides",
    [
        {"contract_version": "cloud-hosted-runtime-profiles.v2"},
        {"platform_kind": "typecho"},
        {"connector_id": "npcink-cloud-addon"},
        {"operation_contract_version": "wordpress_operation.v2"},
        {"unexpected_control_plane": True},
    ],
)
def test_admin_runtime_profiles_requires_frozen_platform_contract(
    tmp_path: Path,
    payload_overrides: dict[str, Any],
) -> None:
    _, client, _ = _build_client(tmp_path)
    payload: dict[str, Any] = {
        "contract_version": "cloud-hosted-runtime-profiles.v1",
        "platform_kind": "wordpress",
        "connector_id": "wordpress_ai_connector",
        "operation_contract_version": "wordpress_operation.v1",
        "profiles": [],
    }
    payload.update(payload_overrides)

    response = client.put(
        "/internal/service/admin/runtime-profiles",
        headers=merge_json_headers(
            build_internal_headers(
                idempotency_key=(
                    f"runtime-profiles-invalid-platform-contract-{next(iter(payload_overrides))}"
                )
            )
        ),
        json=payload,
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "missing_field",
    ["contract_version", "operation_contract_version"],
)
def test_admin_runtime_profiles_requires_explicit_contract_versions(
    tmp_path: Path,
    missing_field: str,
) -> None:
    _, client, _ = _build_client(tmp_path)
    payload: dict[str, Any] = {
        "contract_version": "cloud-hosted-runtime-profiles.v1",
        "platform_kind": "wordpress",
        "connector_id": "wordpress_ai_connector",
        "operation_contract_version": "wordpress_operation.v1",
        "profiles": [],
    }
    payload.pop(missing_field)

    response = client.put(
        "/internal/service/admin/runtime-profiles",
        headers=merge_json_headers(
            build_internal_headers(
                idempotency_key=f"runtime-profiles-missing-version-{missing_field}"
            )
        ),
        json=payload,
    )

    assert response.status_code == 422


def test_admin_runtime_profiles_rejects_execution_kind_mismatch(
    tmp_path: Path,
) -> None:
    _, client, _ = _build_client(tmp_path)

    response = client.put(
        "/internal/service/admin/runtime-profiles",
        headers=merge_json_headers(
            build_internal_headers(idempotency_key="wp-ai-routing-admin-save-kind-mismatch")
        ),
        json={
            "contract_version": "cloud-hosted-runtime-profiles.v1",
            "platform_kind": "wordpress",
            "connector_id": "wordpress_ai_connector",
            "operation_contract_version": "wordpress_operation.v1",
            "profiles": [
                {
                    "profile_id": WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
                    "candidate_instance_ids": ["openai-wp-ai-image-test"],
                    "timeout_ms": 12000,
                    "allow_fallback": True,
                    "max_retries": 0,
                }
            ],
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "runtime_profiles.invalid_profile"
    assert "may only use text instances" in payload["message"]


def test_admin_runtime_profiles_enforces_per_profile_timeout_limits(
    tmp_path: Path,
) -> None:
    _, client, _ = _build_client(tmp_path)
    get_response = client.get(
        "/internal/service/admin/runtime-profiles",
        headers=build_internal_headers(),
    )
    assert get_response.status_code == 200
    replacement_profiles = _runtime_profile_replacement_from_projection(
        get_response.json()["data"]["profiles"]
    )
    audio_profile = next(
        profile
        for profile in replacement_profiles
        if profile["profile_id"] == WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID
    )
    audio_profile["timeout_ms"] = 120000

    audio_response = client.put(
        "/internal/service/admin/runtime-profiles",
        headers=merge_json_headers(
            build_internal_headers(idempotency_key="runtime-profiles-audio-timeout-max")
        ),
        json={
            "contract_version": "cloud-hosted-runtime-profiles.v1",
            "platform_kind": "wordpress",
            "connector_id": "wordpress_ai_connector",
            "operation_contract_version": "wordpress_operation.v1",
            "profiles": replacement_profiles,
        },
    )

    assert audio_response.status_code == 200
    saved_audio_profile = next(
        profile
        for profile in audio_response.json()["data"]["profiles"]
        if profile["profile_id"] == WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID
    )
    assert saved_audio_profile["timeout_ms"] == 120000

    replacement_profiles = _runtime_profile_replacement_from_projection(
        audio_response.json()["data"]["profiles"]
    )
    short_text_profile = next(
        profile
        for profile in replacement_profiles
        if profile["profile_id"] == WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID
    )
    short_text_profile["timeout_ms"] = 60001

    short_text_response = client.put(
        "/internal/service/admin/runtime-profiles",
        headers=merge_json_headers(
            build_internal_headers(idempotency_key="runtime-profiles-short-text-timeout-over-max")
        ),
        json={
            "contract_version": "cloud-hosted-runtime-profiles.v1",
            "platform_kind": "wordpress",
            "connector_id": "wordpress_ai_connector",
            "operation_contract_version": "wordpress_operation.v1",
            "profiles": replacement_profiles,
        },
    )

    assert short_text_response.status_code == 400
    payload = short_text_response.json()
    assert payload["error_code"] == "runtime_profiles.invalid_profile"
    assert "timeout_ms exceeds max 60000" in payload["message"]


def test_admin_runtime_profiles_matches_routing_readiness_for_projection_and_put(
    tmp_path: Path,
) -> None:
    database_url, client, _ = _build_client(tmp_path)
    with get_session(database_url) as session:
        unhealthy_instance = session.get(
            CatalogInstance,
            "openai-wp-ai-connector-test",
        )
        deprecated_model = session.get(
            CatalogModel,
            "gpt-wp-ai-connector-fallback-test",
        )
        unavailable_model = session.get(
            CatalogModel,
            "speech-wp-ai-connector-test",
        )
        degraded_instance = session.get(
            CatalogInstance,
            "openai-wp-ai-vision-test",
        )
        unknown_instance = session.get(
            CatalogInstance,
            "openai-wp-ai-image-test",
        )
        assert unhealthy_instance is not None
        assert deprecated_model is not None
        assert unavailable_model is not None
        assert degraded_instance is not None
        assert unknown_instance is not None
        unhealthy_instance.health_status = "unhealthy"
        deprecated_model.is_deprecated = True
        unavailable_model.status = "disabled"
        degraded_instance.health_status = "degraded"
        unknown_instance.health_status = "unknown"
        session.commit()

    get_response = client.get(
        "/internal/service/admin/runtime-profiles",
        headers=build_internal_headers(),
    )

    assert get_response.status_code == 200
    data = get_response.json()["data"]
    available_instance_ids = {
        kind: {instance["instance_id"] for instance in instances}
        for kind, instances in data["available_instances"].items()
    }
    assert "openai-wp-ai-connector-test" not in available_instance_ids["text"]
    assert "zz-openai-wp-ai-connector-fallback-test" not in available_instance_ids["text"]
    assert "openai-wp-ai-audio-test" not in available_instance_ids["audio_generation"]
    assert "openai-wp-ai-vision-test" in available_instance_ids["vision"]
    assert "openai-wp-ai-image-test" in available_instance_ids["image_generation"]

    profiles_by_id = {profile["profile_id"]: profile for profile in data["profiles"]}
    assert profiles_by_id[WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID]["candidate_instance_ids"] == []
    assert (
        profiles_by_id[WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID]["candidate_instance_ids"] == []
    )
    assert profiles_by_id[WP_AI_CONNECTOR_ALT_TEXT_VISION_PROFILE_ID]["candidate_instance_ids"] == [
        "openai-wp-ai-vision-test"
    ]
    assert profiles_by_id[WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID][
        "candidate_instance_ids"
    ] == ["openai-wp-ai-image-test"]

    eligible_replacement = _runtime_profile_replacement_from_projection(data["profiles"])
    eligible_response = client.put(
        "/internal/service/admin/runtime-profiles",
        headers=merge_json_headers(
            build_internal_headers(idempotency_key="runtime-profiles-readiness-eligible")
        ),
        json={
            "contract_version": "cloud-hosted-runtime-profiles.v1",
            "platform_kind": "wordpress",
            "connector_id": "wordpress_ai_connector",
            "operation_contract_version": "wordpress_operation.v1",
            "profiles": eligible_replacement,
        },
    )
    assert eligible_response.status_code == 200

    invalid_candidates = (
        (
            WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
            "openai-wp-ai-connector-test",
            "unhealthy",
        ),
        (
            WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
            "zz-openai-wp-ai-connector-fallback-test",
            "deprecated",
        ),
        (
            WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID,
            "openai-wp-ai-audio-test",
            "unavailable",
        ),
    )
    for profile_id, instance_id, case in invalid_candidates:
        replacement = _runtime_profile_replacement_from_projection(
            eligible_response.json()["data"]["profiles"]
        )
        target_profile = next(
            profile for profile in replacement if profile["profile_id"] == profile_id
        )
        target_profile["candidate_instance_ids"] = [instance_id]
        response = client.put(
            "/internal/service/admin/runtime-profiles",
            headers=merge_json_headers(
                build_internal_headers(idempotency_key=f"runtime-profiles-readiness-{case}")
            ),
            json={
                "contract_version": "cloud-hosted-runtime-profiles.v1",
                "platform_kind": "wordpress",
                "connector_id": "wordpress_ai_connector",
                "operation_contract_version": "wordpress_operation.v1",
                "profiles": replacement,
            },
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["error_code"] == "runtime_profiles.invalid_profile"
        assert "may only use routing-eligible" in payload["message"]


def test_admin_runtime_profiles_requires_enabled_provider_model(
    tmp_path: Path,
) -> None:
    database_url, client, _ = _build_client(tmp_path)
    with get_session(database_url) as session:
        row = session.get(ProviderConnection, "openai")
        assert row is not None
        config = dict(row.config_json or {})
        config["model_ids"] = [
            "gpt-wp-ai-connector-test",
            "grok-imagine-wp-ai-test",
        ]
        row.config_json = config
        session.commit()

    get_response = client.get(
        "/internal/service/admin/runtime-profiles",
        headers=build_internal_headers(),
    )

    assert get_response.status_code == 200
    data = get_response.json()["data"]
    assert data["available_instances"]["audio_generation"] == []
    audio_generation = next(
        profile
        for profile in data["profiles"]
        if profile["profile_id"] == WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID
    )
    assert audio_generation["candidate_instance_ids"] == []
    assert audio_generation["status"] == "needs_candidates"

    replacement_profiles = _runtime_profile_replacement_from_projection(data["profiles"])
    empty_chain_response = client.put(
        "/internal/service/admin/runtime-profiles",
        headers=merge_json_headers(
            build_internal_headers(idempotency_key="runtime-profiles-empty-audio-chain")
        ),
        json={
            "contract_version": "cloud-hosted-runtime-profiles.v1",
            "platform_kind": "wordpress",
            "connector_id": "wordpress_ai_connector",
            "operation_contract_version": "wordpress_operation.v1",
            "profiles": replacement_profiles,
        },
    )

    assert empty_chain_response.status_code == 200
    empty_chain_audio = next(
        profile
        for profile in empty_chain_response.json()["data"]["profiles"]
        if profile["profile_id"] == WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID
    )
    assert empty_chain_audio["candidate_instance_ids"] == []
    assert empty_chain_audio["status"] == "needs_candidates"
    with get_session(database_url) as session:
        audio_binding = session.get(
            RoutingBinding,
            WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID,
        )
        assert audio_binding is not None
        assert audio_binding.candidate_instance_ids == []

    response = client.put(
        "/internal/service/admin/runtime-profiles",
        headers=merge_json_headers(
            build_internal_headers(idempotency_key="wp-ai-routing-admin-save-model-allowlist")
        ),
        json={
            "contract_version": "cloud-hosted-runtime-profiles.v1",
            "platform_kind": "wordpress",
            "connector_id": "wordpress_ai_connector",
            "operation_contract_version": "wordpress_operation.v1",
            "profiles": [
                {
                    "profile_id": WP_AI_CONNECTOR_AUDIO_GENERATION_PROFILE_ID,
                    "candidate_instance_ids": ["openai-wp-ai-audio-test"],
                    "timeout_ms": 90000,
                    "allow_fallback": True,
                    "max_retries": 0,
                }
            ],
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "runtime_profiles.invalid_profile"
    assert "may only use models enabled for provider openai" in payload["message"]
