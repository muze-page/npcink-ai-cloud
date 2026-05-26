from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from app.model_intelligence.publisher.utils import (
    build_checksum,
    build_price_summary,
    infer_price_tier,
    normalize_supports,
    now_iso,
    unique_strings,
)


class OpenRouterPublisherSource:
    id = "openrouter"

    def __init__(
        self,
        *,
        base_url: str = "https://openrouter.ai/api/v1",
        api_key: str | None = None,
        site_url: str = "https://openrouter.ai",
        app_name: str = "magick-ai-cloud",
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.site_url = site_url
        self.app_name = app_name
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def fetch_bundle(self) -> dict[str, Any]:
        generated_at = now_iso()
        with self._build_client() as client:
            response = client.get("/models")
            response.raise_for_status()
        payload = response.json()
        rows = payload.get("data")
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("openrouter returned no model rows")

        models = [row for row in (_build_openrouter_model(item, generated_at) for item in rows) if row]
        revision = str(response.headers.get("etag") or response.headers.get("last-modified") or generated_at)
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
                    "source_url": f"{self.base_url}/models",
                    "records_total": len(models),
                    "revision": revision,
                }
            ],
            "models": models,
        }
        return {
            **bundle_core,
            "checksum": build_checksum(bundle_core),
        }

    def _build_client(self) -> httpx.Client:
        headers = {
            "content-type": "application/json",
            "user-agent": self.app_name,
            "x-title": self.app_name,
            "http-referer": self.site_url,
        }
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        return httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=max(self.timeout_seconds, 0.001),
            transport=self.transport,
        )


def _build_openrouter_model(row: Any, generated_at: str) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    model_id = str(row.get("id") or "").strip()
    if not model_id:
        return None
    shape = _derive_shape(row)
    pricing = row.get("pricing") if isinstance(row.get("pricing"), dict) else {}
    price_input = _normalize_price_per_million(pricing.get("prompt"))
    price_output = _normalize_price_per_million(pricing.get("completion"))
    has_exact_price = price_input is not None or price_output is not None
    price_reference_kind = "exact" if has_exact_price else "unavailable"
    price_tier = (
        infer_price_tier(price_input, price_output)
        if has_exact_price
        else _infer_estimated_tier(shape["supports"])
    )
    display_name = str(
        row.get("name") or row.get("canonical_slug") or model_id.split("/")[-1] or model_id
    ).strip()
    description = _build_description(shape["model_type"])
    return {
        "provider": "openrouter",
        "model_id": model_id,
        "display_name": display_name,
        "model_type": shape["model_type"],
        "preview_type": shape["preview_type"],
        "supports": shape["supports"],
        "capability_profile": shape["model_type"],
        "aliases": unique_strings([model_id, str(row.get("canonical_slug") or ""), display_name]),
        "source_ids": ["openrouter"],
        "price_reference_kind": price_reference_kind,
        "price_input": price_input,
        "price_output": price_output,
        "price_tier": price_tier,
        "price_summary": build_price_summary(
            kind=price_reference_kind,
            price_input=price_input,
            price_output=price_output,
            tier=price_tier,
        ),
        "short_description": description["short_description"],
        "best_for": description["best_for"],
        "why_recommended": "来自 OpenRouter 模型目录与价格接口的定时汇聚结果。",
        "updated_at": generated_at,
        "source_url": f"https://openrouter.ai/models/{quote(model_id, safe='')}",
        "metadata": {
            "source": "openrouter",
            "context_length": row.get("context_length") if isinstance(row.get("context_length"), int) else None,
            "architecture": row.get("architecture") if isinstance(row.get("architecture"), dict) else None,
        },
    }


def _derive_shape(row: dict[str, Any]) -> dict[str, Any]:
    architecture = row.get("architecture") if isinstance(row.get("architecture"), dict) else {}
    normalized_id = str(row.get("id") or "").strip().lower()
    input_modalities = [
        str(item or "").strip().lower()
        for item in architecture.get("input_modalities", [])
        if str(item or "").strip()
    ] if isinstance(architecture.get("input_modalities"), list) else []
    output_modalities = [
        str(item or "").strip().lower()
        for item in architecture.get("output_modalities", [])
        if str(item or "").strip()
    ] if isinstance(architecture.get("output_modalities"), list) else []
    supported_parameters = [
        str(item or "").strip().lower()
        for item in row.get("supported_parameters", [])
        if str(item or "").strip()
    ] if isinstance(row.get("supported_parameters"), list) else []
    if "embedding" in output_modalities or "embedding" in normalized_id:
        return {"model_type": "embedding", "preview_type": "embedding", "supports": ["embedding"]}
    if "image" in output_modalities or any(token in normalized_id for token in ("flux", "sdxl", "stable-diffusion", "imagen")):
        return {"model_type": "image_generation", "preview_type": "image", "supports": ["text", "image_generation"]}
    if "image" in input_modalities or "video" in input_modalities or "vision" in normalized_id or "vl" in normalized_id:
        return {
            "model_type": "vision",
            "preview_type": "text",
            "supports": normalize_supports(
                [
                    "text",
                    "vision",
                    "tools" if "tools" in supported_parameters or "tool_choice" in supported_parameters else "",
                    "structured" if "response_format" in supported_parameters else "",
                ]
            ),
        }
    return {
        "model_type": "chat",
        "preview_type": "text",
        "supports": normalize_supports(
            [
                "text",
                "tools" if "tools" in supported_parameters or "tool_choice" in supported_parameters else "",
                "structured" if "response_format" in supported_parameters else "",
            ]
        ),
    }


def _normalize_price_per_million(raw_value: Any) -> float | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    try:
        numeric = float(value)
    except ValueError:
        return None
    if numeric < 0:
        return None
    return round(numeric * 1_000_000, 6)


def _infer_estimated_tier(supports: list[str]) -> str:
    if "embedding" in supports:
        return "low"
    if "image_generation" in supports:
        return "high"
    return "medium"


def _build_description(model_type: str) -> dict[str, str]:
    if model_type == "embedding":
        return {
            "short_description": "适合向量检索、召回和语义相似度计算。",
            "best_for": "知识库检索与语义搜索",
        }
    if model_type == "image_generation":
        return {
            "short_description": "适合文本生图与创意图像生成。",
            "best_for": "海报、配图与创意图像生成",
        }
    if model_type == "vision":
        return {
            "short_description": "适合图文理解、视觉问答和 OCR 场景。",
            "best_for": "图像理解与视觉问答",
        }
    return {
        "short_description": "适合通用文本对话、写作和推理任务。",
        "best_for": "通用问答、写作与推理",
    }
