from __future__ import annotations

import httpx

from app.model_intelligence.publisher.sources.huggingface import HuggingFacePublisherSource
from app.model_intelligence.publisher.sources.siliconflow import (
    DEFAULT_PRICING_URL,
    FALLBACK_PRICING_URL,
    SiliconFlowPublisherSource,
)


def test_huggingface_publisher_source_fetches_allowlist_bundle() -> None:
    fixtures = {
        "BAAI/bge-m3": {
            "id": "BAAI/bge-m3",
            "pipeline_tag": "text-embedding",
            "tags": ["embedding"],
        },
        "llava-hf/llava-1.5-7b-hf": {
            "id": "llava-hf/llava-1.5-7b-hf",
            "pipeline_tag": "image-text-to-text",
            "tags": ["vision"],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        repo_id = str(request.url.path).replace("/api/models/", "", 1)
        return httpx.Response(
            200,
            json=fixtures[repo_id],
            headers={"etag": f"hf-{repo_id}"},
        )

    source = HuggingFacePublisherSource(
        repo_ids=list(fixtures.keys()),
        transport=httpx.MockTransport(handler),
    )

    bundle = source.fetch_bundle()

    assert bundle["sources"][0]["source_id"] == "huggingface"
    assert bundle["sources"][0]["records_total"] == 2
    assert len(bundle["models"]) == 2
    assert bundle["models"][0]["provider"] == "huggingface"
    assert bundle["models"][0]["source_ids"] == ["huggingface"]
    assert {item["model_type"] for item in bundle["models"]} == {"embedding", "vision"}


def test_siliconflow_publisher_source_falls_back_to_secondary_pricing_url() -> None:
    pricing_html = """
    <div class="h-[43px] px-[12px] flex items-center"><div class="flex-1"><a href="https://cloud.siliconflow.cn/models?target=Qwen/Qwen3.5-4B">Qwen/Qwen3.5-4B</a></div><div class="flex-1">免费</div><div class="flex-1">免费</div></div>
    """.strip()

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == DEFAULT_PRICING_URL:
            return httpx.Response(502, text="bad gateway")
        assert str(request.url) == FALLBACK_PRICING_URL
        return httpx.Response(200, text=pricing_html)

    source = SiliconFlowPublisherSource(
        pricing_url=DEFAULT_PRICING_URL,
        transport=httpx.MockTransport(handler),
    )

    bundle = source.fetch_bundle()

    assert bundle["sources"][0]["source_id"] == "siliconflow"
    assert bundle["sources"][0]["source_url"] == FALLBACK_PRICING_URL
    assert bundle["models"][0]["provider"] == "siliconflow"
    assert bundle["models"][0]["source_ids"] == ["siliconflow"]
    assert bundle["models"][0]["source_url"].startswith(FALLBACK_PRICING_URL + "#")
