from __future__ import annotations

import re
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


class OllamaPublisherSource:
    id = "ollama"

    def __init__(
        self,
        *,
        base_url: str = "https://ollama.com",
        api_key: str | None = None,
        catalog_limit: int = 120,
        timeout_seconds: float = 30.0,
        app_name: str = "magick-ai-cloud",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.catalog_limit = max(int(catalog_limit), 1)
        self.timeout_seconds = timeout_seconds
        self.app_name = app_name
        self.transport = transport

    def fetch_bundle(self) -> dict[str, Any]:
        generated_at = now_iso()
        model_names: list[str] = []
        with self._build_client() as client:
            tags_response = client.get("/api/tags")
            tags_response.raise_for_status()
            tags_payload = tags_response.json()
            raw_models = tags_payload.get("models")
            if not isinstance(raw_models, list) or not raw_models:
                raise RuntimeError("ollama returned no models")
            for raw in raw_models:
                model_name = str((raw or {}).get("name") or (raw or {}).get("model") or "").strip() if isinstance(raw, dict) else ""
                if not model_name or model_name in model_names:
                    continue
                model_names.append(model_name)
                if len(model_names) >= self.catalog_limit:
                    break
            models: list[dict[str, Any]] = []
            for model_name in model_names:
                show_response = client.post("/api/show", json={"model": model_name})
                if not show_response.is_success:
                    continue
                model = build_ollama_model(model_name, show_response.json(), generated_at, self.base_url)
                if model is not None:
                    models.append(model)

        bundle_core = {
            "bundle_kind": "model_intelligence_bundle_v1",
            "schema_version": "model_intelligence_bundle_v1",
            "generated_at": generated_at,
            "sources": [
                {
                    "source_id": self.id,
                    "source_type": "provider_catalog",
                    "status": "success",
                    "fetched_at": generated_at,
                    "source_url": f"{self.base_url}/api/tags",
                    "records_total": len(models),
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
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        return httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=max(self.timeout_seconds, 0.001),
            transport=self.transport,
        )


def build_ollama_model(
    model_name: str,
    payload: Any,
    generated_at: str,
    base_url: str,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    requested_name = str(model_name or "").strip()
    if not requested_name:
        return None
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    capabilities = [
        str(item or "").strip().lower()
        for item in payload.get("capabilities", [])
        if str(item or "").strip()
    ] if isinstance(payload.get("capabilities"), list) else []
    family = str(details.get("family") or "").strip().lower()
    families = [
        str(item or "").strip().lower()
        for item in details.get("families", [])
        if str(item or "").strip()
    ] if isinstance(details.get("families"), list) else []
    model_info = payload.get("model_info") if isinstance(payload.get("model_info"), dict) else {}
    shape = derive_shape(requested_name, capabilities, family, families, model_info)
    supports = normalize_supports(shape["supports"])
    display_name = requested_name.split(":")[0] or requested_name
    description = build_description(shape["model_type"])
    price_tier = infer_estimated_tier(supports)
    return {
        "provider": "ollama",
        "model_id": requested_name,
        "display_name": display_name,
        "model_type": shape["model_type"],
        "preview_type": shape["preview_type"],
        "supports": supports,
        "capability_profile": shape["model_type"],
        "aliases": unique_strings([requested_name, str(payload.get("model") or ""), display_name]),
        "source_ids": ["ollama"],
        "price_reference_kind": "estimated",
        "price_input": None,
        "price_output": None,
        "price_tier": price_tier,
        "price_summary": build_price_summary(
            kind="estimated",
            price_input=None,
            price_output=None,
            tier=price_tier,
        ),
        "short_description": description["short_description"],
        "best_for": description["best_for"],
        "why_recommended": "来自 Ollama 官方模型目录与详情接口的定时汇聚结果。",
        "updated_at": generated_at,
        "source_url": f"{base_url}/library/{quote(requested_name, safe='')}",
        "metadata": {
            "source": "ollama",
            "family": family,
            "families": families,
            "context_len": extract_context_length(model_info),
            "quantization_level": str(details.get("quantization_level") or "").strip() or None,
            "parameter_size": str(details.get("parameter_size") or "").strip() or None,
        },
    }


def derive_shape(
    model_name: str,
    capabilities: list[str],
    family: str,
    families: list[str],
    model_info: dict[str, Any],
) -> dict[str, Any]:
    capability_set = {str(item).strip().lower() for item in capabilities if str(item).strip()}
    info_keys = [str(key).strip().lower() for key in model_info.keys() if str(key).strip()]
    searchable_values = [
        model_name.lower(),
        family,
        *families,
        str(model_info.get("general.architecture") or "").strip().lower(),
    ]
    token_set = _tokenize_strings(searchable_values)
    family_terms = {family, *families}

    has_embedding = "embedding" in capability_set or (
        not capability_set.intersection({"completion", "vision", "audio", "tools", "thinking", "image"})
        and (
            bool(token_set & {"embedding", "embed", "bge", "gte", "e5", "mxbai"})
            or bool(family_terms & {"bert", "sentence-transformers"})
        )
    )
    has_vision = "vision" in capability_set or bool(
        token_set & {"llava", "vision", "vl", "ocr", "minicpm", "minicpmv"}
    ) or any(".vision." in key for key in info_keys)
    has_image_generation = "image" in capability_set or bool(
        token_set & {"flux", "sdxl", "zimagepipeline", "diffusion"}
    )
    if not has_image_generation and any(term in family_terms for term in ("stable-diffusion", "diffusion")):
        has_image_generation = True
    supports_tools = "tools" in capability_set
    if has_embedding:
        return {"model_type": "embedding", "preview_type": "embedding", "supports": ["embedding"]}
    if has_image_generation:
        return {"model_type": "image_generation", "preview_type": "image", "supports": ["text", "image_generation"]}
    if has_vision:
        return {
            "model_type": "vision",
            "preview_type": "text",
            "supports": ["text", "vision", "tools" if supports_tools else ""],
        }
    return {
        "model_type": "chat",
        "preview_type": "text",
        "supports": ["text", "tools" if supports_tools else ""],
    }


def infer_estimated_tier(supports: list[str]) -> str:
    if "embedding" in supports:
        return "low"
    if "image_generation" in supports:
        return "high"
    return "medium"


def build_description(model_type: str) -> dict[str, str]:
    if model_type == "embedding":
        return {"short_description": "适合本地向量检索、召回和相似度计算。", "best_for": "本地知识库检索与语义搜索"}
    if model_type == "image_generation":
        return {"short_description": "适合本地文本生图和创意图像生成。", "best_for": "本地出图与创意图像工作流"}
    if model_type == "vision":
        return {"short_description": "适合本地图文理解、视觉问答和 OCR 场景。", "best_for": "本地图像理解与视觉问答"}
    return {"short_description": "适合本地通用文本对话、写作和推理任务。", "best_for": "本地问答、写作与推理"}


def extract_context_length(model_info: dict[str, Any]) -> int | None:
    for key in ("general.context_length", "llama.context_length", "qwen2.context_length"):
        candidate = model_info.get(key)
        numeric = int(candidate) if isinstance(candidate, int | str) and str(candidate).isdigit() else None
        if numeric and numeric > 0:
            return numeric
    return None


def _tokenize_strings(values: list[str]) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        for token in re.split(r"[^a-z0-9]+", str(value or "").strip().lower()):
            if token:
                tokens.add(token)
    return tokens
