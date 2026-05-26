from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from app.model_intelligence.publisher.utils import (
    build_checksum,
    build_price_summary,
    normalize_supports,
    now_iso,
    unique_strings,
)


class HuggingFacePublisherSource:
    id = "huggingface"

    def __init__(
        self,
        *,
        repo_ids: list[str],
        base_url: str = "https://huggingface.co",
        api_token: str | None = None,
        timeout_seconds: float = 30.0,
        app_name: str = "magick-ai-cloud",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.repo_ids = [repo_id.strip() for repo_id in repo_ids if repo_id.strip()]
        self.base_url = base_url.rstrip("/")
        self.api_token = str(api_token or "").strip()
        self.timeout_seconds = timeout_seconds
        self.app_name = app_name
        self.transport = transport

    def fetch_bundle(self) -> dict[str, Any]:
        generated_at = now_iso()
        models: list[dict[str, Any]] = []
        revisions: list[str] = []
        with self._build_client() as client:
            for repo_id in self.repo_ids:
                response = client.get(f"/api/models/{quote(repo_id, safe='/')}")
                response.raise_for_status()
                revisions.append(
                    str(
                        response.headers.get("etag")
                        or response.headers.get("last-modified")
                        or generated_at
                    ).strip()
                )
                model = _build_huggingface_model(repo_id, response.json(), generated_at, self.base_url)
                if model is not None:
                    models.append(model)
        if not models:
            raise RuntimeError("huggingface returned no model rows")

        bundle_core = {
            "bundle_kind": "model_intelligence_bundle_v1",
            "schema_version": "model_intelligence_bundle_v1",
            "generated_at": generated_at,
            "sources": [
                {
                    "source_id": self.id,
                    "source_type": "allowlist_catalog",
                    "status": "success",
                    "fetched_at": generated_at,
                    "source_url": f"{self.base_url}/api/models",
                    "records_total": len(models),
                    "revision": "|".join(sorted(revisions)),
                }
            ],
            "models": models,
        }
        return {**bundle_core, "checksum": build_checksum(bundle_core)}

    def _build_client(self) -> httpx.Client:
        headers = {
            "content-type": "application/json",
            "user-agent": self.app_name,
        }
        if self.api_token:
            headers["authorization"] = f"Bearer {self.api_token}"
        return httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=max(self.timeout_seconds, 0.001),
            transport=self.transport,
        )


def _build_huggingface_model(
    repo_id: str,
    payload: Any,
    generated_at: str,
    base_url: str,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    normalized_repo_id = str(repo_id or "").strip()
    if not normalized_repo_id:
        return None

    pipeline_tag = str(payload.get("pipeline_tag") or "").strip().lower()
    tags = [
        str(tag).strip().lower()
        for tag in payload.get("tags", [])
        if str(tag).strip()
    ] if isinstance(payload.get("tags"), list) else []
    shape = _derive_shape(normalized_repo_id, pipeline_tag, tags)
    if shape is None:
        return None

    display_name = (
        str(payload.get("id") or "").strip().split("/")[-1]
        or normalized_repo_id.split("/")[-1]
        or normalized_repo_id
    )
    price_tier = _infer_estimated_tier(shape["supports"])
    description = _build_description(shape["model_type"])
    return {
        "provider": "huggingface",
        "model_id": normalized_repo_id,
        "display_name": display_name,
        "model_type": shape["model_type"],
        "preview_type": shape["preview_type"],
        "supports": shape["supports"],
        "capability_profile": shape["model_type"],
        "aliases": unique_strings([normalized_repo_id, display_name]),
        "source_ids": ["huggingface"],
        "price_reference_kind": "unavailable",
        "price_input": None,
        "price_output": None,
        "price_tier": price_tier,
        "price_summary": build_price_summary(
            kind="unavailable",
            price_input=None,
            price_output=None,
            tier=price_tier,
        ),
        "short_description": description["short_description"],
        "best_for": description["best_for"],
        "why_recommended": "来自 Hugging Face allowlist 模型情报接口的定时汇聚结果。",
        "updated_at": generated_at,
        "source_url": f"{base_url}/{quote(normalized_repo_id, safe='/')}",
        "metadata": {
            "source": "huggingface",
            "pipeline_tag": pipeline_tag or None,
            "tags": tags,
        },
    }


def _derive_shape(
    repo_id: str,
    pipeline_tag: str,
    tags: list[str],
) -> dict[str, Any] | None:
    normalized = f"{repo_id} {' '.join(tags)} {pipeline_tag}".lower()
    if pipeline_tag in {"text-embedding", "feature-extraction", "sentence-similarity"}:
        return {
            "model_type": "embedding",
            "preview_type": "embedding",
            "supports": ["embedding"],
        }
    if pipeline_tag in {"image-text-to-text", "visual-question-answering", "image-classification"}:
        return {
            "model_type": "vision",
            "preview_type": "text",
            "supports": ["text", "vision"],
        }
    if pipeline_tag in {"text-to-image", "image-to-image", "unconditional-image-generation"}:
        return {
            "model_type": "image_generation",
            "preview_type": "image",
            "supports": ["text", "image_generation"],
        }
    if pipeline_tag in {"text-generation", "text2text-generation", "conversational"}:
        return {
            "model_type": "chat",
            "preview_type": "text",
            "supports": ["text"],
        }
    if any(token in normalized for token in ("llava", "vision", "vlm")):
        return {
            "model_type": "vision",
            "preview_type": "text",
            "supports": ["text", "vision"],
        }
    if any(token in normalized for token in ("flux", "sdxl", "stable-diffusion")):
        return {
            "model_type": "image_generation",
            "preview_type": "image",
            "supports": ["text", "image_generation"],
        }
    return None


def _infer_estimated_tier(supports: list[str]) -> str:
    normalized = normalize_supports(supports)
    if "embedding" in normalized:
        return "low"
    if "image_generation" in normalized:
        return "high"
    return "medium"


def _build_description(model_type: str) -> dict[str, str]:
    if model_type == "embedding":
        return {"short_description": "适合向量检索、召回和相似度计算。", "best_for": "知识库检索与语义搜索"}
    if model_type == "image_generation":
        return {"short_description": "适合文本生图和图像生成工作流。", "best_for": "海报、配图与创意图像生成"}
    if model_type == "vision":
        return {"short_description": "适合图文理解、视觉问答和 OCR 场景。", "best_for": "图像理解与视觉问答"}
    return {"short_description": "适合通用文本对话、写作和推理任务。", "best_for": "通用问答、写作与推理"}
